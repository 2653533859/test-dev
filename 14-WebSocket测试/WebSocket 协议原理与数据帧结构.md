---
created: 2026-09-29
tags: [WebSocket测试/协议原理]
---

# WebSocket 协议原理与数据帧结构

> 理解长连接底层通信的基石：深入剖析基于 RFC 6455 规范的 HTTP Upgrade 协议升级握手、位级别二进制数据帧布局、客户端掩码异或算法与控制帧状态机。

![[assets/websocket-lifecycle.svg]]
*图示：WebSocket 完整生命周期——从基于 HTTP 的 101 Upgrade 升级握手，到全双工二进制帧交互与心跳探测，再到双方确认的 0x8 关闭帧握手。*

## 概念

### 为什么长轮询（Long Polling）被淘汰

在实时通信场景（股票行情、即时聊天、实时协同看板）中，传统的 HTTP 轮询与 Comet 长轮询存在三大根本缺陷：

1. **高昂的头部开销**：每次 HTTP 请求都需要重复传输冗长的 Cookie、User-Agent 等 Headers（动辄 1KB~2KB），而实际推送的消息体可能只有几十字节，有效载荷比极低；
2. **半双工单向限制**：HTTP 只能由客户端单向发起拉取，服务端无法主动推流；
3. **高频建连与 TCP 握手开销**：长轮询在单次消息返回后连接立刻断开，高并发下导致大量 TCP 连接处于 TIME_WAIT 状态，浪费服务器端口与文件句柄。

### HTTP Upgrade 握手机制与安全校验

WebSocket 连接复用了 HTTP 的端口（80/443），但在建立时通过请求头宣告协议升级：

```http
客户端握手请求:
GET /chat HTTP/1.1
Host: server.example.com
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==
Sec-WebSocket-Version: 13
Origin: https://client.example.com

服务端响应 (101 Switching Protocols):
HTTP/1.1 101 Switching Protocols
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=
```

#### Sec-WebSocket-Accept 计算签名算法
为了防止普通 HTTP 缓存服务器错误缓存握手请求，服务端必须执行确定性签名推导：
1. 取出客户端的 `Sec-WebSocket-Key` 字符串；
2. 拼接 RFC 6455 规定的全局唯一魔术字符串（Magic GUID）：`258EAFA5-E914-47DA-95CA-C5AB0DC85B11`；
3. 对拼接后的字符串计算 **SHA-1 哈希**；
4. 将哈希值转换为 **Base64 编码**，作为 `Sec-WebSocket-Accept` 返回。

```python
import base64
import hashlib

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
client_key = "dGhlIHNhbXBsZSBub25jZQ=="
sha1_hash = hashlib.sha1((client_key + GUID).encode("utf-8")).digest()
expected_accept = base64.b64encode(sha1_hash).decode("utf-8")
assert expected_accept == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
```

### RFC 6455 数据帧（Frame）底层布局

一旦握手完成，TCP 连接脱离 HTTP 协议，进入纯二进制数据帧流模式。每个 WebSocket 帧的位结构如下：

```text
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-------+-+-------------+-------------------------------+
|F|R|R|R| opcode|M| Payload len |    Extended payload length    |
|I|S|S|S|  (4)  |A|     (7)     |             (16/64)           |
|N|V|V|V|       |S|             |   (if payload len==126/127)   |
| |1|2|3|       |K|             |                               |
+-+-+-+-+-------+-+-------------+ - - - - - - - - - - - - - - - +
|     Extended payload length continued, if payload len == 127  |
+ - - - - - - - - - - - - - - - +-------------------------------+
|                               |Masking-key, if MASK set to 1  |
+-------------------------------+-------------------------------+
| Masking-key (continued)       |          Payload Data         |
+-------------------------------- - - - - - - - - - - - - - - - +
:                     Payload Data continued ...                :
+---------------------------------------------------------------+
```

- **FIN（1 bit）**：指示此帧是否为消息的最后一帧（1 表示消息完结，0 表示后续还有分片分段帧）；
- **RSV1~RSV3（3 bits）**：保留字段，通常用于扩展协议（如压缩扩展 `permessage-deflate` 为 1，否则必须全为 0）；
- **Opcode（4 bits）**：操作码，定义当前帧的类型：
  - `0x0`：连续帧（Continuation Frame，用于前置分片传输）；
  - `0x1`：文本帧（Text Frame，UTF-8 编码文本）；
  - `0x2`：二进制帧（Binary Frame，Protobuf、字节流或图片）；
  - `0x8`：连接关闭帧（Connection Close Frame）；
  - `0x9`：Ping 控制帧；
  - `0xA`：Pong 控制帧；
- **MASK（1 bit）**：客户端发送给服务端的帧**必须置为 1**，服务端推流给客户端必须置为 0；
- **Payload Length（7 bits / 7+16 bits / 7+64 bits）**：
  - 若值 $\le 125$，即实际数据长度；
  - 若值为 $126$，后续 2 字节（16 位无符号整数）表示实际长度；
  - 若值为 $127$，后续 8 字节（64 位无符号整数）表示实际长度；
- **Masking-key（32 bits / 4 字节）**：当 MASK=1 时存在，用于防止毒化代理缓存的随机异或掩码。

---

## 用法

### 1. 手动解析二进制数据帧与掩码解码（Python）

```python
def decode_masked_payload(raw_frame: bytes) -> tuple[int, str]:
    """解析 RFC 6455 原始二进制帧并还原客户端文本报文"""
    byte0 = raw_frame[0]
    byte1 = raw_frame[1]

    fin = (byte0 >> 7) & 1
    opcode = byte0 & 0x0F
    is_masked = (byte1 >> 7) & 1
    payload_len = byte1 & 0x7F

    offset = 2
    if payload_len == 126:
        payload_len = int.from_bytes(raw_frame[2:4], byteorder="big")
        offset = 4
    elif payload_len == 127:
        payload_len = int.from_bytes(raw_frame[2:10], byteorder="big")
        offset = 10

    if not is_masked:
        # 服务端下发的未掩码数据
        payload_data = raw_frame[offset : offset + payload_len]
    else:
        # 客户端上送的掩码数据，提取 4 字节掩码并通过 XOR 异或还原
        mask_key = raw_frame[offset : offset + 4]
        offset += 4
        masked_data = raw_frame[offset : offset + payload_len]
        payload_data = bytearray(
            masked_data[i] ^ mask_key[i % 4] for i in range(len(masked_data))
        )

    text_msg = (
        payload_data.decode("utf-8") if opcode == 0x1 else payload_data.hex()
    )
    return opcode, text_msg
```

---

## 踩坑

1. **客户端发出的帧未掩码导致协议错误（1002 Protocol Error）**：
   - *现象*：自研压测脚本直接向服务端 TCP socket 写入原始明文帧，服务端直接返回 1002 错误并粗暴掐断连接。
   - *根因*：RFC 6455 规范强制规定：**客户端发出的所有数据帧 MASK 标志位必须为 1**，且必须带 4 字节随机 Masking-key 并进行异或编码。这是为了防止老旧的透明中间件代理将 WebSocket 帧误当成 HTTP GET 进行有害的缓存劫持。
2. **大包分片传输（Fragmentation）拼接丢失**：
   - *现象*：客户端发送了一张 2MB 的图片，服务端只收到第一段。
   - *解法*：超过单帧最大限制时，第一帧 `FIN=0, opcode=0x2`，中间帧 `FIN=0, opcode=0x0`，最后一帧 `FIN=1, opcode=0x0`。测试脚本在手动校验报文时必须实现分片累加拼接。
3. **关闭状态码与关闭原因（Close Code & Reason）**：
   - 收到 `opcode=0x8` 时，负载前 2 字节为大端关闭状态码（如 `1000` 表示正常关闭，`1001` 表示端点离开，`1008` 表示策略违规）。很多测试用例在主动调用 `close()` 时遗漏了状态码，导致服务端记作异常掉线。

---

## 面试怎么答

**Q：WebSocket 与 HTTP 到底是什么关系？它的握手过程与底层数据帧是如何设计的？**
> 1. **连接建立与协议升级**：WebSocket 并非一种全新的传输层协议，它复用了 HTTP 的端口与 TCP 连接。客户端发起带有 `Upgrade: websocket` 与随机串 `Sec-WebSocket-Key` 的 HTTP GET 请求，服务端通过 SHA-1 拼接固定 GUID 计算出 `Sec-WebSocket-Accept` 并返回 **101 Switching Protocols**，完成握手升级。
> 2. **轻量二进制帧设计**：握手后连接脱离 HTTP，进入精简的二进制帧（Frame）通信。每个帧的头部开销最小仅 2 个字节（相比 HTTP 动辄数 KB 头开销微乎其微）。帧头包含表示消息完结的 FIN 位、区分文本/二进制/Ping/Pong/Close 的 4 位 Opcode，以及动态扩展的长度字段。
> 3. **客户端掩码安全设计**：规范强制要求客户端发送的帧必须经过 4 字节随机 Mask 掩码异或混淆，防止恶意脚本毒化透明代理缓存，而服务端推流则无需掩码，兼顾了安全与效率。

---

## 参考

- RFC 6455: The WebSocket Protocol：`https://datatracker.ietf.org/doc/html/rfc6455`
- 相关笔记：[[03-计算机网络]]、[[HTTP 长连接与 HTTP-2 多路复用]]、[[14-WebSocket测试]]
