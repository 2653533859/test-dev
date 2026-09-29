---
created: 2026-09-29
tags: [WebSocket测试/自动化实战]
---

# Python WebSocket 自动化测试实战

> 告别单调的一问一答：基于 `websocket-client`（同步轻量测试）与 `websockets`（异步高并发协程），构建支持超时兜底、长连接会话生命周期管理与事件驱动的自动化测试工程。

## 概念

### 自动化库选型：同步 vs 异步

在 Python 生态中，测试 WebSocket 接口主要有两大核心库，各有明确的适用场景：

| 选型维度 | `websocket-client` (同步客户端) | `websockets` (基于 asyncio 异步) |
| :--- | :--- | :--- |
| **编程模型** | 同步阻塞式调用，代码风格与 requests 类似 | 基于 Python 协程与事件循环（`async / await`） |
| **测试场景** | 适用于**单接口功能验证**、CI 冒烟用例、少量数据帧交互 | 适用于**多端协同广播测试**、模拟上千长连接并发、流式推送持续监听 |
| **pytest 集成** | 直接使用标准 pytest，上手零心智负担 | 需引入 `pytest-asyncio` 插件，用例声明为 `async def` |
| **超时控制** | 支持方法级 `settimeout(seconds)` | 原生支持 `asyncio.wait_for(ws.recv(), timeout)` |

---

## 用法

### 1. 同步长连接测试客户端封装（带连接管理与断言）

针对大多数 CI 自动化用例，封装一个具备超时保护、自动重连与 JSON 序列化的客户端基类：

```python
import json
import logging
from typing import Any, Dict, Optional
import websocket


class SyncWebSocketClient:
    """企业级同步 WebSocket 测试客户端封装"""

    def __init__(
        self,
        url: str,
        token: Optional[str] = None,
        default_timeout: float = 5.0,
    ):
        self.url = url
        self.default_timeout = default_timeout
        headers = [f"Authorization: Bearer {token}"] if token else []
        # 创建连接（握手阶段注入鉴权 Header）
        self.ws = websocket.create_connection(
            self.url, header=headers, timeout=self.default_timeout
        )
        self.ws.settimeout(self.default_timeout)

    def send_json(self, data: Dict[str, Any]):
        """发送 JSON 文本帧"""
        payload = json.dumps(data)
        logging.info(f"==> WS 发送帧: {payload}")
        self.ws.send(payload)

    def recv_json(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        """接收单条 JSON 帧并反序列化（带超时保护）"""
        if timeout:
            self.ws.settimeout(timeout)
        try:
            raw = self.ws.recv()
            logging.info(f"<== WS 收到帧: {raw}")
            return json.loads(raw)
        finally:
            self.ws.settimeout(self.default_timeout)

    def close(self):
        """标准 0x8 优雅关闭连接"""
        if self.ws and self.ws.connected:
            self.ws.close()
```

### 2. pytest 自动化用例与 Fixture 深度整合

在 `conftest.py` 中利用 `yield` 管理长连接的生命周期，确保用例抛出异常时后置清理依然能安全执行：

```python
# conftest.py
import pytest
from client import SyncWebSocketClient


@pytest.fixture(scope="function")
def ws_client():
    client = SyncWebSocketClient("wss://api.mall.internal/ws/order?channel=101")
    yield client
    # 后置清理：断开长连接，释放服务端资源
    client.close()


# test_order_ws.py
def test_order_status_subscription(ws_client):
    """测试订单状态变更订阅并等待服务端异步推流"""
    # 1. 客户端发送订阅指令
    ws_client.send_json(
        {
            "action": "subscribe",
            "order_id": "ORD-2026-9901",
            "events": ["PAID", "SHIPPED"],
        }
    )

    # 2. 接收订阅成功的 ACK 响应
    ack = ws_client.recv_json(timeout=2.0)
    assert ack["code"] == 200
    assert ack["msg"] == "Subscribed successfully"

    # 3. 模拟触发业务端事件（可调用 HTTP 支付接口）
    # ... trigger_payment_api("ORD-2026-9901") ...

    # 4. 断言 WebSocket 收到服务端主动推送的状态变更帧
    event_frame = ws_client.recv_json(timeout=5.0)
    assert event_frame["event"] == "PAID"
    assert event_frame["data"]["order_id"] == "ORD-2026-9901"
```

### 3. 基于 `pytest-asyncio` 的多客户端广播测试

测试聊天室或协作场景（用户 A 发送一条消息，用户 B 与用户 C 能够实时收到）：

```python
import asyncio
import json
import pytest
import websockets


@pytest.mark.asyncio
async def test_chat_room_broadcast():
    uri = "wss://api.mall.internal/ws/chat/room_88"

    # 同时拉起三个并发长连接协程
    async with websockets.connect(uri) as client_a, websockets.connect(
        uri
    ) as client_b, websockets.connect(uri) as client_c:

        # 客户端 A 发送一条广播消息
        msg_payload = {"user": "Alice", "content": "Hello Team!"}
        await client_a.send(json.dumps(msg_payload))

        # 客户端 B 和 C 并发监听接收消息
        async def wait_msg(client):
            res = await asyncio.wait_for(client.recv(), timeout=3.0)
            return json.loads(res)

        b_received, c_received = await asyncio.gather(
            wait_msg(client_b), wait_msg(client_c)
        )

        assert b_received["content"] == "Hello Team!"
        assert c_received["content"] == "Hello Team!"
```

---

## 踩坑

1. **`recv()` 未设超时导致 CI 构建无尽卡死**：
   - *现象*：服务端因 Bug 没有推送预期的事件帧，自动化脚本在 `ws.recv()` 处无限期阻塞，整条 CI 流水线卡死直到 2 小时后被 Jenkins 强杀。
   - *解法*：每一次 `recv()` 调用**必须显式配置超时阈值**（如 5 秒），超时抛出 `TimeoutException`，在报告中清晰指示「未能在 5 秒内接收到事件推送」。
2. **消息顺序错乱导致脆弱断言（Flaky Assertions）**：
   - *现象*：服务端先后推送了「系统公告」和「订单通知」，自动化脚本直接断言第一次收到的帧是订单通知，偶发报错。
   - *解法*：长连接通常伴随心跳帧或系统杂音。测试客户端应实现**消息过滤器（Predicate Matcher）**：在超时窗口内持续消费帧，若收到无关的心跳或公告帧则暂存或跳过，直到匹配到目标事件类型才结束。
3. **未捕获服务端异常断开（ConnectionResetError）**：
   - *现象*：服务端主动踢出连接时，调用 `send()` 会直接抛出 Broken Pipe 异常，用例崩溃无排查现场。
   - *解法*：发送与接收外层捕获 `WebSocketConnectionClosedException`，提取关闭帧中的 Code 与 Reason 打印在断言失败日志中。

---

## 面试怎么答

**Q：WebSocket 接口与普通 HTTP 接口在自动化测试框架设计上有何不同？**
> 1. **连接与生命周期管理**：HTTP 接口是无状态的单次请求，而 WebSocket 是全双工长连接。测试框架必须通过 pytest fixture 的 `yield` 机制，在用例开始前完成 HTTP 升级握手并建立 Session，在用例结束后必须显式发送 0x8 关闭帧完成关闭握手，防止服务端产生僵尸连接泄露。
> 2. **断言维度的转变**：HTTP 是一发一收断言 Status Code 与 Response；而 WebSocket 往往是「发一次指令，后续异步收到多条推送」或者「完全由服务端主动推流」。断言机制需要演进为**事件驱动断言**与**消息流队列消费**，必须配合严谨的超时机制（`timeout` 兜底）与消息类型过滤。
> 3. **多客户端协同验证**：对于即时通讯与协作看板场景，单客户端无法完成闭环测试。我们利用 `pytest-asyncio` 与 `websockets` 协程并发拉起多个长连接实例，模拟多用户并发订阅与广播校验。

---

## 参考

- websocket-client 官方文档：`https://websocket-client.readthedocs.io/`
- websockets (asyncio) 官方指南：`https://websockets.readthedocs.io/`
- 相关笔记：[[06-接口自动化测试]]、[[05-自动化测试框架]]、[[14-WebSocket测试]]
