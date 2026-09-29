---
created: 2026-09-29
tags: [项目实战/测试平台]
---

# 实时日志流推送与 WebSocket 双工通道设计

> 提升测试人员交互调试体验：基于 FastAPI WebSocket 原生协议与 Redis 发布/订阅（Pub/Sub）机制，构建微秒级低延迟的自动化执行实时日志推流控制台。

## 概念

### 为什么不能采用传统 HTTP 轮询

在初期的测试平台中，很多团队采用「定时轮询（Polling）」来获取用例执行日志（前端每隔 1 秒请求一次 `/api/tasks/{id}/logs`）：

1. **高并发下服务被自身打崩**：如果有 20 个人同时在线调试用例，前端每秒发起 20 次 HTTP 请求查询数据库，极易造成数据库连接池耗尽与服务端 CPU 飙高；
2. **延迟高且日志断续**：轮询存在天然的时间窗口延迟（最坏情况延迟 1 秒），测试人员在前端感觉卡顿、缺乏「正在控制台执行」的真实沉浸感；
3. **无意义的网络开销**：大量轮询请求返回的都是「暂无新日志」的空响应，无效占用网络带宽。

### WebSocket + Redis Pub/Sub 架构设计

```text
  前端 xterm.js 终端 ◄═══════ WebSocket 双工连接 ═══════► FastAPI WebSocket 网关
                                                               │
                                                               ▼ 订阅指定频道 (Channel: task_{id})
                                                     ┌──────────────────────┐
                                                     │    Redis Pub/Sub     │
                                                     └──────────────────────┘
                                                               ▲
                                                               │ 发布实时输出 (PUBLISH)
                                                     ┌──────────────────────┐
                                                     │ Celery Runner 执行器  │
                                                     └──────────────────────┘
```

- **单连接长驻**：客户端仅在点击运行用例时建立一条 TCP WebSocket 长连接，执行结束自动平稳关闭；
- **发布订阅解耦（Pub/Sub）**：执行器只负责向特定的 Redis 频道 `PUBLISH task_{id} "log line..."`；Web 节点无需保存执行器状态，只要订阅该频道并实时把数据写入 WebSocket 通道即可，支持多 Web 实例横向扩展。

---

## 用法

### 1. FastAPI WebSocket 端点与 Redis 订阅器

```python
import asyncio
import json
import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()
REDIS_URL = "redis://:SecurePass123@redis:6379/3"


@router.websocket("/ws/logs/{execution_id}")
async def websocket_logs_endpoint(websocket: WebSocket, execution_id: int):
    """实时测试日志推流长连接端点"""
    await websocket.accept()

    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    pubsub = redis_client.pubsub()
    channel_name = f"channel_execution_{execution_id}"
    await pubsub.subscribe(channel_name)

    try:
        # 发送建立连接确认
        await websocket.send_text(
            json.dumps({"type": "info", "msg": f"成功连接至执行任务 #{execution_id}"})
        )

        while True:
            # 异步监听 Redis 频道的新消息（非阻塞）
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message:
                log_data = message["data"]
                # 推送至前端 xterm 终端
                await websocket.send_text(log_data)
                # 若检测到结束标志则主动断开
                if "[EXECUTION_FINISHED]" in log_data:
                    break
            # 让出协程事件循环，防止死循环占用
            await asyncio.sleep(0.01)
    except WebSocketDisconnect:
        print(f"客户端主动关闭了连接: {execution_id}")
    finally:
        await pubsub.unsubscribe(channel_name)
        await pubsub.close()
        await redis_client.close()
        try:
            await websocket.close()
        except RuntimeError:
            pass
```

### 2. 执行器（Runner）端异步日志写出封装

```python
import redis

# 同步执行器环境使用标准 redis 库发布
r = redis.Redis(
    host="redis", port=6379, db=3, password="SecurePass123", decode_responses=True
)


class PlatformLogger:

    def __init__(self, execution_id: int):
        self.channel = f"channel_execution_{execution_id}"

    def write(self, line: str):
        """格式化日志并实时推送到 Redis 广播队列"""
        formatted = f"[STDOUT] {line.strip()}"
        r.publish(self.channel, formatted)

    def finish(self, status: str):
        """发送结束通知信号"""
        r.publish(self.channel, f"[EXECUTION_FINISHED] 任务执行完毕，最终状态: {status}")
```

---

## 踩坑

1. **日志爆发（Log Flood）导致前端页面卡死甚至浏览器崩溃**：
   - *案例*：某些测试用例开启了 DEBUG 级别，一秒内向控制台疯狂打印数万行 JSON 报文。WebSocket 毫无节制地推过去，直接把前端 Vue DOM 与 `xterm.js` 内存撑爆，浏览器标签页直接崩溃白屏。
   - *解法*：在后端引入**滑动窗口节流缓冲（Batch Buffering）**机制。不要每产生一行就发一次 WebSocket，而是将 50ms 内收集到的多行日志合并为一个数组一次性推流，大幅降低渲染频率。
2. **用户刷新或关闭网页导致连接泄露与后台僵尸订阅**：
   - *案例*：用户中途关闭了浏览器标签，FastAPI 协程没有捕获到断开信号，一直在循环向一个死连接尝试推送，并在 Redis 中残留了大量订阅。
   - *解法*：严格在 `try...except WebSocketDisconnect` 与 `finally` 块中执行 `pubsub.unsubscribe()`，并在 Redis 侧设置频道监听超时时间，双向兜底资源回收。

---

## 面试怎么答

**Q：测试平台中的「实时执行控制台」是如何实现的？如何解决高并发多人同时在线查看的性能问题？**
> 1. **全双工直连与发布订阅解耦**：彻底摒弃传统的 HTTP 定时轮询，采用 **FastAPI WebSocket + Redis Pub/Sub** 的流式架构。每个任务对应一个 Redis 唯一频道，分布式 Runner 执行器产生日志时直接向该频道发送报文，Web 实例只负责桥接推流给当前前端，避免了对后端数据库的频繁读取。
> 2. **前后端背压与节流合并**：针对接口打印海量日志（如爬虫或复杂断言）的场景，在后端实现了微批缓冲合并（50ms 窗口聚合），避免细碎消息高频触发前端重绘；前端结合 WebGL 加速的 `xterm.js` 进行虚拟列表渲染，确保了即使在一秒打印数万行日志时，用户界面依然丝滑不卡顿。

---

## 参考

- FastAPI WebSocket 官方指南：`https://fastapi.tiangolo.com/advanced/websockets/`
- xterm.js 终端前端组件：`https://xtermjs.org/`
- 相关笔记：[[05-自动化测试框架]]、[[测试框架日志与断言封装]]、[[03-计算机网络]]
- 所属项目：[[测试平台架构设计与落地/测试平台架构设计与落地]]
