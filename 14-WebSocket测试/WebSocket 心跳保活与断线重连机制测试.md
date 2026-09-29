---
created: 2026-09-29
tags: [WebSocket测试/心跳重连]
---

# WebSocket 心跳保活与断线重连机制测试

> 解决长连接在复杂网络环境中的「假死」与「雪崩」：深入测试 RFC 6455 协议级 Ping/Pong、应用层自定义心跳、TCP 半开连接检测与指数退避重连算法。

## 概念

### 为什么必须有心跳保活机制

TCP 协议本身虽然具有 Keep-Alive 机制，但在真实的移动互联网或公网环境中，WebSocket 长连接必须实现应用层或协议层心跳：

```text
 客户端 ═════════► NAT 网关 / 防火墙 / Nginx ═════════► 服务端
                      │
                      ▼ 超过 60 秒无任何报文往来
            NAT 表项被静默剔除 (连接处于半开状态)
                      │
   客户端以为连接还活着   │   服务端也以为连接还活着
   (发出的数据直接丢失)   │   (占用文件描述符与内存资源)
```

1. **NAT 网关超时清理**：运营商的 NAT 网关或公司防火墙为了节省内存，通常会在连接空闲 30~60 秒后直接删除 NAT 映射表项。此时双方 TCP 连接处于**半开（Half-Open）状态**，双方均未收到任何 RST 或 FIN 包，误以为连接正常；
2. **中间反向代理超时断开**：Nginx 默认配置了 `proxy_read_timeout 60s;`，若 60 秒内无数据帧流动，Nginx 会主动切断长连接；
3. **僵尸连接识别与资源回收**：客户端异常掉电、拔掉网线或进电梯丢网时，服务端若无心跳探测，会一直持有该连接，导致服务端连接池耗尽。

### 协议级 Ping/Pong vs 应用层心跳

| 维度 | RFC 6455 协议级心跳 (Opcode 0x9/0xA) | 业务应用层心跳 (文本 JSON 帧) |
| :--- | :--- | :--- |
| **底层标识** | 控制帧 `0x9` (Ping) 与 `0xA` (Pong) | 普通文本帧 `0x1`，载荷为 `{"type": "ping"}` |
| **传输开销** | 极小（仅 2 字节帧头，无额外应用层头） | 相对略大（需 JSON 序列化与解析） |
| **透明性** | 浏览器与成熟客户端会自动拦截并默默应答 | 必须由前端 JS 业务代码显式监听并回复 |
| **穿透性** | 极少数老旧反向代理可能会过滤底层控制帧 | 兼容性最好，任何支持文本帧的网关均可穿透 |

---

## 用法

### 1. 指数退避断线重连算法测试（Exponential Backoff with Jitter）

客户端遭遇网络闪断时，绝不能立即以固定高频死循环重试，否则当服务端重启时会引发**「重连风暴（Reconnection Storm）」**直接打穿网关。标准重连应采用带抖动的指数退避：

$$\text{SleepTime} = \min(\text{MaxInterval}, \text{BaseInterval} \times 2^{\text{retry}}) \pm \text{RandomJitter}$$

```python
import random
import time
import pytest
import websocket


def connect_with_retry(
    url: str, max_retries: int = 5, base_delay: float = 0.5
) -> websocket.WebSocket:
    """带指数退避和抖动的健壮重连逻辑"""
    for attempt in range(max_retries):
        try:
            ws = websocket.create_connection(url, timeout=3.0)
            print(f"✅ 第 {attempt+1} 次连接成功！")
            return ws
        except (
            websocket.WebSocketException,
            ConnectionRefusedError,
            TimeoutError,
        ) as e:
            if attempt == max_retries - 1:
                raise e

            # 计算下一次重试休眠时间：base * (2 ^ attempt) + 随机抖动
            delay = min(10.0, base_delay * (2**attempt))
            jitter = random.uniform(0.1, 0.5)
            sleep_time = delay + jitter
            print(
                f"❌ 第 {attempt+1} 次连接失败，等待 {sleep_time:.2f}s 后重试..."
            )
            time.sleep(sleep_time)
```

### 2. 弱网损伤注入模拟心跳超时断开测试

利用 Linux `iptables` 或 `toxiproxy` 模拟客户端在发送心跳后网络彻底中断，断言服务端在达到心跳超时阈值（如连续 3 次未收到 Pong）后主动踢出连接：

```python
import subprocess
import time


def test_heartbeat_timeout_cleanup(ws_client):
    """测试心跳中断时服务端是否能在 15 秒内主动销毁僵尸连接"""
    # 1. 正常接收第一次心跳
    msg = ws_client.recv_json(timeout=5.0)
    assert msg.get("type") in ["ping", "heartbeat"]

    # 2. 模拟网络丢包：利用 iptables DROP 阻止客户端回包
    print("注入网络故障：丢弃所有出站 WebSocket 报文...")
    subprocess.run(
        "iptables -A OUTPUT -p tcp --dport 8080 -j DROP",
        shell=True,
        check=True,
    )

    try:
        # 3. 等待服务端心跳超时检测周期（假设服务端配置 10 秒超时）
        time.sleep(12)

        # 4. 恢复网络后尝试发送数据，预期连接已被服务端单方面重置或关闭
        subprocess.run(
            "iptables -D OUTPUT -p tcp --dport 8080 -j DROP",
            shell=True,
            check=True,
        )

        with pytest.raises(websocket.WebSocketConnectionClosedException):
            ws_client.send_json({"type": "test_alive"})
            ws_client.recv_json(timeout=2.0)
    finally:
        # 确保故障规则一定被清理
        subprocess.run("iptables -F OUTPUT", shell=True)
```

---

## 踩坑

1. **重连成功后丢失订阅状态（Session Loss）**：
   - *现象*：网络闪断重连后，客户端以为连接正常，但再也收不到任何业务通知。
   - *根因*：重连建立的是一条全新的 TCP 连接与全新 WebSocket Session。服务端内存中原有的「用户 A 订阅了订单频道 101」的状态已随旧 Session 销毁。
   - *解法*：客户端重连成功后，必须实现**重新同步（Re-subscribe / State Re-sync）机制**，自动将本地订阅的主题列表重新向服务端补发注册，并补拉断线期间的离线消息。
2. **Ping-Pong 间隔与网关超时时间倒挂**：
   - *现象*：Nginx 配置 `proxy_read_timeout 30s`，而客户端心跳间隔配置为 45 秒。导致每隔 30 秒连接就必然被 Nginx 掐断，客户端陷入频繁断开重连的死循环。
   - *解法*：心跳发送间隔**必须严格小于代理服务器的空闲超时阈值**（通常建议设为代理超时的 $1/2$ 或 $1/3$，例如 Nginx 设 60s，心跳设 20s 发送一次）。

---

## 面试怎么答

**Q：WebSocket 长连接如何保持在线？客户端如果意外掉线如何优雅重连？**
> 1. **双向心跳检测与半开连接消除**：
>    - 采用双向保活机制（通常为 15~30 秒一个心跳周期），既可以采用 RFC 6455 协议级 `0x9 Ping / 0xA Pong` 控制帧，也可采用轻量文本心跳。
>    - 只要连续 N 次（通常为 2~3 次）未收到对端应答，立即判定连接已死，主动调用 `close()` 释放底层 TCP 文件描述符，避免死连接占用服务器内存。
> 2. **重连风暴规避（带抖动的指数退避）**：
>    - 客户端发现网络中断后，必须采用**指数退避（Exponential Backoff）算法并叠加随机抖动（Jitter）**递增重试间隔（例如 1s, 2s, 4s, 8s 直至上限 30s）。杜绝所有客户端在同一时刻并发发起 TCP 握手压垮网关。
> 3. **状态恢复与会话连续性**：
>    - 重连不仅仅是重新连上 Socket，更重要的是「会话重建立」。重连建立后，客户端必须根据本地状态自动向服务端重新发送 Channel 订阅指令，并通过传递上一次收到的 `last_msg_id` 补拉断线期间未送达的消息，确保数据不丢失。

---

## 参考

- Nginx WebSocket 反向代理超时配置：`https://nginx.org/en/docs/http/websocket.html`
- 相关笔记：[[03-计算机网络]]、[[02-Linux基础]]、[[14-WebSocket测试]]
