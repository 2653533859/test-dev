---
created: 2026-07-31
tags: [接口自动化测试/WebSocket]
---

# WebSocket 接口测试思路

> HTTP 是一问一答；WebSocket 是长连双向流。测试思路要从「发请求等响应」切换到「连上后听消息、按帧断言」。

![[assets/websocket-flow.svg]]
*图示：先 HTTP Upgrade 握手，再进入双向消息环，最后发 Close frame 释放连接。*

## 概念

### WebSocket 不是「又一个 HTTP 方法」

握手阶段用 HTTP（`Upgrade: websocket`），一旦 101 切换协议，后续就是独立的 ws 帧，不走 `requests`。所以 `requests` 不能直接测 WS——得用专用库。

### 同步 vs 异步

| 库 | 场景 | 特点 |
|----|------|------|
| `websocket-client` | 同步脚本、CI 里快验 | `ws.recv()` 阻塞等一帧 |
| `websockets` (async) | 高并发压测、批量收消息 | `await ws.recv()` 协程并发 |

## 用法

### 同步连上并断言一条推送

```python
import websocket, json
ws = websocket.create_connection("wss://echo.example.com?token=xxx")
ws.send(json.dumps({"type": "subscribe", "channel": "ticker"}))
msg = json.loads(ws.recv())          # 阻塞等第一帧
assert msg["type"] == "ticker"
ws.close()
```

### 异步批量收

```python
import asyncio, websockets, json
async def main():
    async with websockets.connect("wss://echo.example.com?token=xxx") as ws:
        await ws.send(json.dumps({"type": "subscribe"}))
        msg = json.loads(await ws.recv())
        assert msg["channel"] == "ticker"
asyncio.run(main())
```

## 踩坑

### ① 把 token 放在 URL 外没地方带

WS 握手走 HTTP，鉴权头得在 `create_connection` 前通过 `header=` 注入，否则连上就被拒。常见写法：`websocket.create_connection(url, header={"Authorization: Bearer xxx"})`。

### ② recv 超时没设，用例卡死

默认 `recv()` 永久阻塞，上游不推就挂起整条 CI。`ws.settimeout(5)` 兜底，超时抛错好定位。

### ③ 心跳 ping 没回，连接被服务端踢

服务端发 `ping` 帧，客户端不回 `pong` 会被判死连接。库默认自动回 pong，但你若自己解析帧得手动补。

### ④ 关了连接还发消息报错

`ws.send()` 在 `close()` 之后调用会抛 `WebSocketConnectionClosedException`。断言里先 `if ws.connected:` 再发。

### ⑤ 异步 recv 的顺序竞争

`await ws.recv()` 在并发下消息可能乱序，断言要按 `msg['id']` 而非先后。高并发场景用队列收齐再比对。

## 面试怎么答

「WebSocket 接口怎么自动化？」

- 握手仍走 HTTP，连上后切换协议，不能用 `requests` 直接打；
- 同步用 `websocket-client`、并发用 `websockets` 异步；
- 断言盯的是「收到的帧」而非「响应体」；
- 坑：token 注入位置、recv 超时、心跳 pong、关连接后发送报错、并发顺序竞争——都要在用例里兜底。

## 参考

- websocket-client：<https://pypi.org/project/websocket-client/>
- websockets (async)：<https://websockets.readthedocs.io/en/stable/>
- [[requests Session 会话保持与 Cookie]] —— WS 握手阶段的 Cookie/Token 鉴权
- [[接口 Mock：unittest.mock 与 responses]] —— WS 服务也可用 Mock 打桩
- 专题全景：[[14-WebSocket测试]] —— 全双工协议、心跳保活、CSWSH安全与性能压测
