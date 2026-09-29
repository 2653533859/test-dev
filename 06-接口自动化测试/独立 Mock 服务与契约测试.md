---
created: 2026-07-31
tags: [接口自动化测试/Mock]
---

# 独立 Mock 服务与契约测试

> 进程内 Mock 解决不了两个问题：多方共用，以及「Mock 数据和真实接口悄悄不一致」。前者靠独立 Mock 服务，后者靠契约测试。

## 概念

### 为什么需要独立 Mock 服务

`responses` 这类进程内打桩只对当前 Python 进程生效。但真实项目里的需求往往是：

- 前端也要联调，他们跑在浏览器里
- 被测的是**服务 A**，A 会去调服务 B——Mock 要拦的是 A 发出的请求，不是测试脚本发出的
- 需要在 CI 环境里长期跑，多个流水线共用
- 要模拟真实网络行为（延迟、连接重置、分块传输）

这些都要求 Mock 是一个**独立进程、监听端口、能被任何客户端访问**的服务。

### 三种落地方式

| 方案 | 特点 | 适合 |
|------|------|------|
| Flask / FastAPI 手写 | 完全可控，能写复杂逻辑 | 需要有状态、有业务规则的 Mock |
| WireMock / MockServer | 配置化，功能全（延迟、故障注入、录制回放） | 团队级共用 |
| Apifox / Postman Mock Server | 和文档同源，零维护 | 前后端联调 |

### 契约测试要解决什么

Mock 有一个根本性缺陷：**它固化的是「我以为上游长这样」**。

```text
第 1 天：上游返回 {"userId": 1001, "userName": "张三"}
        我写了 Mock，用例全绿
第 30 天：上游重构，改成 {"user_id": 1001, "name": "张三"}
        我的 Mock 还是老的 → 用例依然全绿
        线上：我的代码取 userId 拿到 None → 炸
```

Mock 越多，这个风险越大。契约测试（Contract Testing）就是来堵这个洞的：

> **消费者**（调用方）声明「我需要上游返回什么」，产出一份契约文件；
> **提供者**（被调方）用同一份契约跑校验，验证自己确实提供了这些。
> 任一方违约，CI 立刻失败。

这叫**消费者驱动契约**（Consumer-Driven Contract, CDC），代表工具是 Pact。

### 契约测试 vs 集成测试

| 维度 | 契约测试 | 端到端集成测试 |
|------|----------|----------------|
| 是否需要双方同时在线 | 否（异步，通过契约文件） | 是 |
| 速度 | 秒级 | 分钟级 |
| 能发现什么 | 接口结构/字段不一致 | 完整业务逻辑问题 |
| 定位精度 | 精确到字段 | 常常只知道「某处挂了」 |
| 环境依赖 | 无 | 全链路环境 |

契约测试**不能替代**集成测试，它替代的是「为了发现字段改名而跑的那部分昂贵的集成测试」。

## 用法

### 用 FastAPI 快速搭一个 Mock 服务

```python
# mock_server.py
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import asyncio
import uvicorn

app = FastAPI(title="Upstream Mock")

# 用内存字典维持简单状态，让 Mock 能支持「创建后能查到」
_orders: dict[int, dict] = {}
_next_id = 1000


class CreateOrder(BaseModel):
    sku_id: str
    quantity: int


@app.post("/api/v1/orders")
async def create_order(body: CreateOrder):
    global _next_id
    _next_id += 1
    order = {"order_id": _next_id, "sku_id": body.sku_id,
             "quantity": body.quantity, "status": "UNPAID"}
    _orders[_next_id] = order
    return {"code": 0, "msg": "ok", "data": order}


@app.get("/api/v1/orders/{order_id}")
async def get_order(order_id: int):
    if order_id not in _orders:
        raise HTTPException(status_code=404, detail="order not found")
    return {"code": 0, "msg": "ok", "data": _orders[order_id]}


# ---------- 故障注入：专门给异常用例用 ----------
@app.get("/api/v1/_chaos/timeout")
async def chaos_timeout(seconds: float = 30):
    await asyncio.sleep(seconds)
    return {"code": 0}


@app.get("/api/v1/_chaos/status/{code}")
async def chaos_status(code: int):
    raise HTTPException(status_code=code, detail=f"injected {code}")


@app.get("/api/v1/_chaos/garbage")
async def chaos_garbage():
    from fastapi.responses import HTMLResponse
    return HTMLResponse("<html>502 Bad Gateway</html>", status_code=502)


# ---------- 状态重置：用例之间隔离 ----------
@app.post("/api/v1/_admin/reset")
async def reset():
    _orders.clear()
    return {"code": 0, "msg": "reset ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

两个设计要点值得强调：

- **`_chaos/*` 故障注入端点**：超时、指定状态码、返回非 JSON 垃圾。这些是异常场景用例的弹药库。
- **`_admin/reset` 重置端点**：Mock 有状态就必然需要隔离机制，否则用例互相污染。

### 在 pytest 里启停 Mock 服务

```python
# conftest.py
import subprocess
import sys
import time

import pytest
import requests


@pytest.fixture(scope="session")
def mock_server():
    proc = subprocess.Popen([sys.executable, "mock_server.py"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = "http://127.0.0.1:8000"
    # 轮询等待就绪，不要 sleep 死等
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            if requests.get(f"{base}/docs", timeout=1).status_code == 200:
                break
        except requests.exceptions.ConnectionError:
            time.sleep(0.3)
    else:
        proc.kill()
        raise RuntimeError("Mock 服务 15 秒内未就绪")

    yield base
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture(autouse=True)
def reset_mock(mock_server):
    """每条用例前重置 Mock 状态。"""
    requests.post(f"{mock_server}/api/v1/_admin/reset", timeout=3)
```

```python
def test_upstream_timeout_fallback(api, mock_server, monkeypatch):
    monkeypatch.setenv("UPSTREAM_BASE_URL", mock_server)
    r = api.get("/api/v1/_chaos/timeout", params={"seconds": 30})
    # 被测服务应该在自己的超时时间内降级，而不是一直等
```

### 用 Docker Compose 把 Mock 放进 CI

```yaml
# docker-compose.test.yml
services:
  mock-upstream:
    build: ./mock
    ports:
      - "8000:8000"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/docs"]
      interval: 3s
      timeout: 2s
      retries: 10

  api-tests:
    build: ./tests
    depends_on:
      mock-upstream:
        condition: service_healthy
    environment:
      UPSTREAM_BASE_URL: http://mock-upstream:8000
      BASE_URL: http://app:8080
    command: pytest -v --alluredir=/reports
```

`condition: service_healthy` 保证测试容器等 Mock 真正就绪再启动，比 `sleep 10` 可靠。参考 [[11-持续集成]]。

### Pact 契约测试：消费者侧

```bash
pip install pact-python
```

```python
# tests/contract/test_user_service_consumer.py
import atexit
import pytest
from pact import Consumer, Provider

pact = Consumer("OrderService").has_pact_with(
    Provider("UserService"), pact_dir="./pacts", port=1234
)
pact.start_service()
atexit.register(pact.stop_service)


def test_get_user_contract():
    expected = {"user_id": 1001, "name": "张三", "vip_level": 3}

    (pact
        .given("用户 1001 存在且是 3 级会员")      # provider state
        .upon_receiving("查询用户 1001 的请求")
        .with_request("GET", "/api/v1/users/1001")
        .will_respond_with(200, body=expected))

    with pact:
        # 用真实的客户端代码去调，验证客户端能正确解析
        from myapp.clients.user import UserClient
        client = UserClient(base_url="http://localhost:1234")
        user = client.get_user(1001)
        assert user.name == "张三"
        assert user.vip_level == 3
```

运行后在 `./pacts/` 下生成契约文件：

```json
{
  "consumer": {"name": "OrderService"},
  "provider": {"name": "UserService"},
  "interactions": [{
    "description": "查询用户 1001 的请求",
    "providerState": "用户 1001 存在且是 3 级会员",
    "request": {"method": "GET", "path": "/api/v1/users/1001"},
    "response": {
      "status": 200,
      "body": {"user_id": 1001, "name": "张三", "vip_level": 3}
    }
  }]
}
```

### Pact：提供者侧验证

```bash
# UserService 的 CI 里执行：启动真实服务，用契约文件逐条回放校验
pact-verifier \
  --provider-base-url=http://localhost:8080 \
  --pact-url=./pacts/orderservice-userservice.json \
  --provider-states-setup-url=http://localhost:8080/_pact/setup
```

`--provider-states-setup-url` 指向一个测试专用端点，Pact 会在回放每条交互前调用它，让提供者把数据准备成 `providerState` 描述的状态（「用户 1001 存在且是 3 级会员」）。

**关键流程**：消费者的契约文件通过 Pact Broker 共享给提供者，提供者每次改动都要跑一遍全部消费者的契约。有人改了字段名，CI 立刻红——在合并代码之前，而不是上线之后。

### 轻量替代方案：用 OpenAPI 当契约

不想引入 Pact 全套时，一个务实的做法是**拿 OpenAPI 文档当契约**：

```python
import json
from pathlib import Path
import jsonschema
import pytest


@pytest.fixture(scope="session")
def openapi_spec():
    return json.loads(Path("openapi.json").read_text(encoding="utf-8"))


def response_schema(spec, path, method, status="200"):
    node = spec["paths"][path][method.lower()]["responses"][status]
    schema = node["content"]["application/json"]["schema"]
    return {**schema, "components": spec.get("components", {})}


def test_order_matches_openapi(api, sku, openapi_spec):
    """真实响应必须符合 Swagger 文档声明的结构。"""
    r = api.post("/api/v1/orders", json={"sku_id": sku, "quantity": 1})
    schema = response_schema(openapi_spec, "/api/v1/orders", "post")
    jsonschema.validate(r.json(), schema)
```

同时用**同一份 Schema 校验 Mock 数据**，这样 Mock 和真实接口就被同一个契约约束住了：

```python
def test_mock_data_matches_openapi(openapi_spec):
    mock_response = load_mock_fixture("create_order.json")
    schema = response_schema(openapi_spec, "/api/v1/orders", "post")
    jsonschema.validate(mock_response, schema)   # Mock 过期了这里就红
```

这条用例很便宜，但价值极高——它是 Mock 与现实之间的锚点。见 [[JSON Schema 响应结构校验]]。

## 踩坑

1. **Mock 服务有状态但没有重置机制**：用例之间互相污染，单跑通过、全跑失败。加 `_admin/reset` 端点并用 `autouse` fixture 调用。
2. **等待 Mock 就绪用 `sleep`**：机器慢的时候 sleep 不够，CI 偶发失败。用轮询 + 超时，或 Docker 的 healthcheck。
3. **Mock 端口冲突**：CI 上多个流水线并发，8000 端口被占。用随机端口（`socket` 取空闲端口）或容器内固定端口 + 动态宿主端口。
4. **Mock 服务比真实服务还复杂**：为了模拟各种业务规则，Mock 里写了几千行逻辑，自己都需要测试了。**Mock 应该是"够用就好"**，复杂业务规则该走真实服务。
5. **Mock 数据永不更新**：这是最隐蔽的坑，用例全绿但保护不了任何东西。必须用契约或 Schema 把 Mock 和真实接口绑住。
6. **Pact 的 provider state 没实现**：提供者侧验证时数据准备不了，契约回放全失败。这需要提供者团队配合，不是测试单方面能推动的——**契约测试的最大成本是组织协作，不是技术**。
7. **契约写得太具体**：把 `created_at` 的具体时间戳写进契约，提供者永远验不过。契约里动态字段用 matcher（`Like`、`Term`、`EachLike`）而不是具体值。
8. **把契约测试当成端到端测试用**：契约只校验「接口形状」，不校验业务逻辑正确性。它替代不了集成测试。
9. **契约文件没有版本管理和共享机制**：手工拷贝 JSON 文件，很快就乱。要用 Pact Broker 或至少放进制品库。
10. **Mock 服务在生产网络可达**：测试用的 Mock 服务暴露在公网，被误当成真实服务调用。务必限制在内网/CI 网络。

## 面试怎么答

**Q：进程内 Mock 和独立 Mock 服务怎么选？**

A：看拦截点在哪。如果被测对象就是我的测试脚本发出的请求，`responses` 这类进程内打桩最合适——最快、不过网络、造异常最方便。但有三种情况必须上独立 Mock 服务：一是被测的是服务 A，而 A 会去调服务 B，我要拦的是 A 发出的请求，进程内打桩够不着；二是前端、其他团队也要用同一套 Mock；三是要模拟真实的网络行为，比如慢响应、连接重置。独立 Mock 我一般用 FastAPI 手写，几十行就能起来，还会特意加两类端点：`_chaos/*` 做故障注入（超时、指定状态码、返回 HTML 垃圾），`_admin/reset` 做状态重置保证用例隔离。

**Q：什么是契约测试，为什么需要它？**

A：契约测试解决的是「Mock 和真实接口悄悄不一致」这个问题。Mock 固化的是「我以为上游长这样」，上游今天把 `userId` 改成 `user_id`，我的 Mock 还是老的，用例依然全绿，线上直接炸。契约测试的做法是消费者驱动：调用方声明「我需要你返回哪些字段、什么类型」，产出一份契约文件；提供方在自己的 CI 里用同一份契约回放校验，确认确实提供了这些。任一方违约，在合并代码之前就红了。工具层面 Pact 是主流，需要提供者配合实现 provider state 来准备数据。

如果团队推不动 Pact 全套，有个很务实的轻量方案：**拿 OpenAPI 文档当契约**——用文档里的 response schema 同时校验真实响应和 Mock 数据。真实响应不符说明后端没按文档实现，Mock 不符说明 Mock 过期了。成本极低但把最关键的洞堵上了。

**Q：契约测试能替代集成测试吗？**

A：不能，它们的目标不同。契约测试只校验「接口形状」——字段在不在、类型对不对，它的优势是快、不需要双方同时在线、定位精确到字段。集成测试校验的是完整的业务逻辑和数据流转，比如下单减库存、支付改状态这些跨服务的一致性。契约测试真正替代掉的，是「为了发现字段改名而不得不跑的那部分昂贵的端到端测试」——这部分本来占了集成测试很大比例，而且失败时定位极慢。所以合理的结构是：大量契约测试 + 少量核心链路的端到端集成测试，而不是二选一。

## 参考

- [Pact 官方文档](https://docs.pact.io/)
- [pact-python](https://github.com/pact-foundation/pact-python)
- [WireMock](https://wiremock.org/docs/)
- [FastAPI 文档](https://fastapi.tiangolo.com/)
- 相关笔记：[[接口 Mock：unittest.mock 与 responses]]、[[JSON Schema 响应结构校验]]、[[11-持续集成]]
