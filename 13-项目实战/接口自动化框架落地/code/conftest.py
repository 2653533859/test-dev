"""横切关注点注入：多环境、token 跨进程共享、数据隔离与后置清理。

关键点：
1. scope="session" 在 pytest-xdist 下是「每个 worker 各执行一次」，不是全局一次。
   token 用文件锁 + 缓存做跨进程共享。
2. 造数走 fixture，yield 后置清理，断言失败也能清干净。
"""

import getpass
import json
import logging
import os
import time
from pathlib import Path

import pytest
import requests
import yaml
from filelock import FileLock

from http_client import HttpClient, OrderApi

logger = logging.getLogger(__name__)

# 断言辅助函数所在模块要注册重写，否则失败信息会退化。必须在 import 之前调用。
pytest.register_assert_rewrite("assertions")

TOKEN_CACHE = Path(".pytest_cache/token.json")
SAFETY_MARGIN = 300  # 提前 5 分钟视为过期，避免长回归跑到一半 token 失效


def pytest_addoption(parser):
    parser.addoption("--env", default="test", help="运行环境：test / staging")


@pytest.fixture(scope="session")
def env_conf(pytestconfig) -> dict:
    """读取环境配置。敏感信息不落盘，从环境变量取。"""
    env = pytestconfig.getoption("--env")
    conf = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))[env]
    logger.info("当前运行环境：%s -> %s", env, conf["base_url"])
    return conf


@pytest.fixture(scope="session")
def token(env_conf) -> str:
    """全局唯一 token：文件锁保证多 worker 只登录一次。

    背景：服务端是单点登录策略，后登录的 token 会挤掉先前的。
    4 个 worker 各自登录会导致大面积 401。
    """
    TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(f"{TOKEN_CACHE}.lock", timeout=30):  # 不设 timeout 会死等
        if TOKEN_CACHE.exists():
            cached = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
            if cached["expire_at"] - time.time() > SAFETY_MARGIN:
                return cached["token"]

        resp = requests.post(
            f"{env_conf['base_url']}/api/v1/auth/login",
            json={
                "username": env_conf["user"],
                "password": os.environ["TEST_PASSWORD"],
            },
            timeout=(5, 15),
        )
        assert resp.status_code == 200, f"登录失败：{resp.status_code} {resp.text}"
        body = resp.json()["data"]

        TOKEN_CACHE.write_text(
            json.dumps({"token": body["accessToken"],
                        "expire_at": time.time() + body["expiresIn"]}),
            encoding="utf-8",
        )
        logger.info("登录成功，token 有效期 %ss", body["expiresIn"])
        return body["accessToken"]


@pytest.fixture(scope="session")
def client(env_conf, token) -> HttpClient:
    """鉴权态客户端。"""
    return HttpClient(env_conf["base_url"], token=token)


@pytest.fixture(scope="session")
def guest_client(env_conf) -> HttpClient:
    """游客态客户端。与鉴权态严格隔离，否则 cookie 污染会造成假阳性。"""
    return HttpClient(env_conf["base_url"])


@pytest.fixture(scope="session")
def data_prefix() -> str:
    """数据隔离前缀：CI 里用构建号，本地用用户名 + 时间戳。"""
    return os.getenv("BUILD_TAG", f"local-{getpass.getuser()}-{int(time.time())}")


@pytest.fixture
def api_order(client) -> OrderApi:
    return OrderApi(client)


@pytest.fixture
def sku(client, data_prefix, worker_id):
    """每条用例独享一个商品，用完即删，避免并行时互相踩踏库存。"""
    code = f"{data_prefix}-{worker_id}-{int(time.time() * 1000)}"
    resp = client.post("/api/v1/goods", json={"code": code, "stock": 999, "price": 99.00})
    assert resp.status_code == 200, f"造数失败：{resp.text}"
    goods_id = resp.json()["data"]["id"]

    yield goods_id  # yield 之后的清理，断言失败时照样执行

    try:
        client.delete(f"/api/v1/goods/{goods_id}")
    except Exception as e:  # 清理失败只告警，不能把用例结果带红
        logger.warning("清理商品 %s 失败：%s", goods_id, e)


@pytest.fixture
def ctx():
    """用例级上下文变量池。绝不能设成 session 级，否则并行时变量互相覆盖。"""
    from context import Context

    return Context()
