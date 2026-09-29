---
created: 2026-07-31
tags: [项目实战/接口自动化框架]
---

# Token 鉴权与会话管理实现

> 让 200 多条用例共享一个 token、并行执行时不互相挤掉、跑到一半过期能自动续，且用例代码里看不见任何鉴权细节。

## 概念

鉴权是接口自动化的第一道坎，需求看起来简单——「登录拿 token，每个请求带上」——但真正落地要回答四个问题：

1. **token 什么时候取**：每条用例取一次（慢、可能触发风控）还是全局取一次（快，但要处理共享）。
2. **怎么传给每个请求**：用例里手动拼 header（侵入、容易漏）还是在客户端层自动注入。
3. **过期了怎么办**：全量回归跑 20 多分钟，token 有效期可能只有 30 分钟。
4. **并行时怎么办**：`pytest-xdist` 的每个 worker 是独立进程，session fixture 会**各执行一次**。

本项目的答案：**session 级 fixture + 跨进程文件缓存 + 客户端层自动注入 + 提前量刷新**。

### 一个必须先搞清的语义

`scope="session"` 的「session」指的是**一次 pytest 进程的完整运行**，不是「所有 worker 共享」。在 xdist 下有 N 个 worker 就有 N 个进程，session fixture 就执行 N 次。这是最高频的认知错误，直接导致了本项目的第一个线上级故障（4 个 worker 各自登录，单点登录策略下互相挤掉 token，大面积 401）。

## 用法

### 客户端层自动注入

鉴权不该出现在用例里，统一在 `HttpClient` 处理。

```python
# core/http_client.py
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class HttpClient:
    """封装 Session：统一 base_url、超时、重试、鉴权注入、日志。"""

    def __init__(self, base_url: str, token: str | None = None, timeout=(5, 15)):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        # 只对幂等方法和特定状态码重试，POST 默认不重试避免重复下单
        retry = Retry(
            total=2, backoff_factor=0.5,
            status_forcelist=[502, 503, 504],
            allowed_methods=["GET", "HEAD", "OPTIONS"],
        )
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=20)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def request(self, method: str, path: str, **kwargs):
        kwargs.setdefault("timeout", self.timeout)     # 强制超时，杜绝无限等待
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        resp = self.session.request(method, url, **kwargs)
        logger.info("%s %s -> %s (%.0fms)", method, url,
                    resp.status_code, resp.elapsed.total_seconds() * 1000)
        return resp

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)
```

用 `Session` 而不是每次 `requests.post()` 有两个实打实的收益：**连接池复用**（TCP 握手 + TLS 握手省掉，全量回归实测快约 15%）和 **header/cookie 统一持有**。

### 跨 worker 共享 token

```python
# conftest.py
import json, os, time
from pathlib import Path
from filelock import FileLock
import pytest

CACHE = Path(".pytest_cache/token.json")
SAFETY_MARGIN = 300          # 提前 5 分钟视为过期

@pytest.fixture(scope="session")
def token(env_conf):
    """全局唯一 token：文件锁保证多 worker 只登录一次。"""
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(f"{CACHE}.lock", timeout=30):
        if CACHE.exists():
            cached = json.loads(CACHE.read_text(encoding="utf-8"))
            if cached["expire_at"] - time.time() > SAFETY_MARGIN:
                return cached["token"]

        resp = requests.post(
            f"{env_conf['base_url']}/auth/login",
            json={"username": env_conf["user"],
                  "password": os.environ["TEST_PASSWORD"]},   # 密码走环境变量
            timeout=(5, 15),
        )
        assert resp.status_code == 200, f"登录失败：{resp.text}"
        body = resp.json()["data"]
        CACHE.write_text(json.dumps({
            "token": body["accessToken"],
            "expire_at": time.time() + body["expiresIn"],
        }), encoding="utf-8")
        return body["accessToken"]


@pytest.fixture(scope="session")
def client(env_conf, token):
    return HttpClient(env_conf["base_url"], token=token)


@pytest.fixture(scope="session")
def guest_client(env_conf):
    """未登录客户端，用于「无权限应返回 401」这类用例，与鉴权态严格隔离。"""
    return HttpClient(env_conf["base_url"])
```

### 401 自动重试一次

即使有提前量，仍可能遇到服务端主动失效 token（比如管理员改密）。在客户端层兜底：

```python
def request(self, method, path, _retry_auth=True, **kwargs):
    resp = self._do_request(method, path, **kwargs)
    if resp.status_code == 401 and _retry_auth:
        logger.warning("401，强制刷新 token 后重试一次")
        new_token = refresh_token(force=True)          # 会清掉文件缓存
        self.session.headers["Authorization"] = f"Bearer {new_token}"
        return self.request(method, path, _retry_auth=False, **kwargs)
    return resp
```

`_retry_auth=False` 的递归保护必须有，否则密码真错时会无限重试。

## 踩坑

1. **xdist 下 session fixture 执行 N 次**：本项目最大的坑，见「概念」段。文件锁 + 缓存解决。另一种方案是用 `worker_id == "master"` 判断，但那只在非并行模式成立，不通用。

2. **token 有效期判断没留余量**：判断 `expire_at > now` 看似正确，但 token 在用例执行到一半时过期，后半段集体 401。留 5 分钟安全余量。

3. **`Session` 复用导致 Cookie 污染，产生假阳性**：登录态 Session 被拿去跑「未登录访问应 401」的用例，结果因为带着 cookie 返回了 200，用例断言 401 失败——这还算好的；更糟的情况是用例写成断言 200，**永远通过但完全没测到东西**。鉴权态和游客态必须用两个独立 Session。

4. **密码硬编码进代码库**：早期写在 `config/env.yaml` 里提交了，被 code review 拦下。所有凭据走环境变量或 CI 凭据管理，YAML 里只留 `${TEST_PASSWORD}` 占位。

5. **`.pytest_cache/token.json` 被提交进 Git**：`.gitignore` 里补上。另外 CI 上要保证每次构建清理缓存，否则跨构建复用了别的环境的 token。

6. **FileLock 不加 timeout 会死等**：某次登录接口挂了，持锁的 worker 卡在 15 秒超时里，其他 worker 无限等待，整个构建 hang 住。`FileLock(..., timeout=30)` 加上，超时就抛错让构建快速失败。

7. **多角色场景硬塞进一个 fixture**：后来要测「管理员 / 普通用户 / 商家」三种角色，最初的做法是加参数改造 `token` fixture，越改越乱。正确做法是做成**工厂 fixture**：

   ```python
   @pytest.fixture(scope="session")
   def client_factory(env_conf):
       cache: dict[str, HttpClient] = {}
       def _make(role: str = "user") -> HttpClient:
           if role not in cache:
               cache[role] = HttpClient(env_conf["base_url"], token=login_as(role))
           return cache[role]
       return _make
   ```

8. **重试放在 POST 上导致重复下单**：`urllib3` 的 `Retry` 默认 `allowed_methods` 只含幂等方法，但有人为了「稳定性」手动加了 POST，结果网络抖动时重试造出两笔订单。非幂等接口绝不自动重试。

## 面试怎么答

**Q：你们的自动化框架怎么处理登录鉴权？**

A：session 级 fixture 登录一次，token 存进 `requests.Session` 的默认 header，用例层完全感知不到鉴权存在。并行执行时因为 xdist 每个 worker 是独立进程、session fixture 会各跑一次，我们用文件锁加缓存让 token 全局只生成一次。另外做了两层保护：判断过期时留 5 分钟安全余量，以及客户端层遇到 401 时强制刷新并重试一次。

**Q：session 作用域的 fixture 在并行执行时会执行几次？**

A：有几个 worker 就执行几次——session 指的是单个 pytest 进程的生命周期，不是全局。这是很多人的认知盲区。要真正做到全局一次，得靠进程外的协调手段，比如文件锁加缓存、或者由 CI 在启动前先取好 token 通过环境变量传进去。

**Q：token 快过期了怎么办？**

A：三层兜底。第一层是判断过期时间时留安全余量，避免临界点；第二层是如果有 refresh token 就用它换新的，避免重新走完整登录流程触发风控；第三层是客户端层拦 401 强制刷新重试一次，并且用递归保护防止密码错误时无限重试。

**Q：为什么要用 Session 而不是直接 `requests.get`？**

A：三个原因。连接池复用，省掉每次 TCP 和 TLS 握手，我们实测全量回归快了约 15%；header 和 cookie 统一持有，鉴权信息只设置一次；可以挂载 `HTTPAdapter` 统一配置重试策略和连接池大小。但要注意 Session 的状态是共享的，登录态和未登录态必须用不同实例，否则会出现 cookie 污染导致的假阳性。

## 参考

- requests Session 文档：`https://requests.readthedocs.io/en/latest/user/advanced/`
- 相关笔记：[[Token 与 JWT 鉴权的获取与刷新]]、[[requests Session 会话保持与 Cookie]]、[[requests 超时、重试与连接池]]、[[pytest fixture 详解]]、[[conftest.py 查找规则与作用域]]、[[pytest-xdist 并行执行]]
- 所属项目：[[接口自动化框架落地]]
