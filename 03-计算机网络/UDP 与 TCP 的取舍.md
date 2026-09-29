---
created: 2026-07-31
tags: [计算机网络/传输层]
---

# UDP 与 TCP 的取舍

> 不是「UDP 不可靠所以不好」，而是「可靠性该由谁来负责」。TCP 把可靠性做进了内核，UDP 把选择权交还给应用。

## 概念

### 两者的本质差异

| 维度 | TCP | UDP |
|------|-----|-----|
| 连接 | 面向连接，需三次握手 | 无连接，`sendto` 直接发 |
| 可靠性 | 确认、重传、去重、排序 | 不管，丢了就丢了 |
| 有序性 | 保证按序交付给应用 | 到达顺序即交付顺序 |
| 边界 | **字节流**，无消息边界 | **数据报**，一次发送 = 一次接收 |
| 头部开销 | 20 字节起（含选项可到 60） | 固定 8 字节 |
| 流量/拥塞控制 | 有 | 无（应用自己做） |
| 通信模式 | 只能 1 对 1 | 支持单播、多播、广播 |
| 首字节延迟 | 至少 1 个 RTT（握手） | 0 RTT |

### 最容易被忽略的差异：字节流 vs 数据报

大部分人能背出「TCP 可靠、UDP 不可靠」，但真正在工程上更常出问题的是**边界差异**。

TCP 是**字节流**：应用调用三次 `send(b"AAA")`、`send(b"BBB")`、`send(b"CCC")`，接收方可能一次 `recv()` 就拿到 `b"AAABBBCCC"`，也可能分五次拿到 `b"AA"`、`b"AB"`、`b"BBC"`、`b"C"`、`b"C"`。**TCP 不保存消息边界**，这就是所谓的「粘包 / 拆包」——严格来说这个叫法本身就是误解，TCP 从来没承诺过有「包」的概念。

所以基于 TCP 的应用协议**必须自己定义消息边界**，三种通用做法：

1. **定长消息**：每条消息固定 N 字节。简单但浪费。
2. **长度前缀**：先发 4 字节长度，再发内容。最常用，Dubbo、gRPC 都是这么干的。
3. **分隔符**：用 `\r\n` 之类的分隔。HTTP 头部就是这么做的（所以 HTTP 头里不能出现裸的换行——这正是 CRLF 注入漏洞的成因）。

UDP 则是**数据报**：`sendto` 一次，对端 `recvfrom` 一次，边界天然保留。发 100 字节，对端要么完整收到 100 字节，要么什么都收不到，**不会收到半个**。

### UDP 的「不可靠」具体指什么

三件事：

1. **可能丢失**——网络拥塞时路由器直接丢弃，没人告诉你。
2. **可能乱序**——两个包走不同路径，后发的先到。
3. **可能重复**——链路层重传等原因导致同一个包到达两次。

但有一点 UDP 是保证的：**收到的数据一定没损坏**（有校验和，坏了直接丢弃）。所以 UDP 是「不保证送到，但保证送到的是对的」。

### 为什么还要用 UDP

因为**很多场景下，TCP 的可靠性不但没用，反而有害**。

以实时音视频为例：一个 200ms 前的音频帧丢了，TCP 会停下来重传它，后面已经到达的帧全部在缓冲区里排队等待（**队头阻塞**）。等重传成功，用户已经卡了半秒。而这个帧即使补回来也毫无意义——它对应的时刻早过去了。这时候正确的做法是**直接丢弃、播下一帧**，UDP 天然支持。

再以 DNS 为例：一次查询就一个小包，用 TCP 的话光三次握手就要一个 RTT，加上四次挥手，为了 100 字节的数据付出巨大开销。UDP 一发一收搞定，丢了应用层重试一次即可。

**核心权衡：TCP 用「延迟」换「可靠」，UDP 用「可能丢」换「低延迟和灵活」。**

### 典型应用场景

| 协议 | 传输层 | 为什么 |
|------|--------|--------|
| HTTP/1.1、HTTP/2 | TCP | 网页内容不能缺字节 |
| HTTP/3、QUIC | **UDP** | 在 UDP 上自己实现可靠性，绕开 TCP 队头阻塞 |
| DNS | UDP 为主 | 单次查询小包，响应超过 512 字节或做区域传送时才转 TCP |
| 音视频通话（RTP/WebRTC） | UDP | 实时性 >> 完整性 |
| 游戏状态同步 | UDP | 旧状态没有重传价值 |
| SNMP、NTP、Syslog | UDP | 轻量、可容忍丢失 |
| MySQL、Redis、Kafka | TCP | 数据一个字节都不能错 |
| QUIC 之上的 gRPC | UDP | 同 HTTP/3 |

**HTTP/3 是理解这个权衡最好的案例**：它没有回到「不可靠」，而是把可靠性从内核的 TCP 挪到了用户态的 QUIC 里自己实现。这样既保留了可靠性，又能做到「单个 Stream 丢包只阻塞自己，不阻塞其他 Stream」——这是 TCP 架构下无论如何做不到的。

## 用法

### UDP 收发的最小示例

```python
# udp_server.py
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)   # SOCK_DGRAM = UDP
sock.bind(("0.0.0.0", 9999))
print("UDP server on 9999")

while True:
    # 没有 accept、没有 connection，直接收；一次 recvfrom = 一个完整数据报
    data, addr = sock.recvfrom(65535)
    print(f"来自 {addr}: {data!r}")
    sock.sendto(b"pong:" + data, addr)
```

```python
# udp_client.py
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(2)                      # UDP 必须自己设超时，否则丢包就永久阻塞

for i in range(3):
    sock.sendto(f"ping-{i}".encode(), ("127.0.0.1", 9999))

try:
    while True:
        data, addr = sock.recvfrom(65535)
        print("收到:", data)
except socket.timeout:
    print("2 秒内没有更多响应（可能丢包了，UDP 不会告诉你）")
```

对比一下 TCP 版本会发现：UDP 没有 `listen`、没有 `accept`、没有 `connect`（可选），也没有连接状态——**服务端重启了客户端毫不知情，照发不误**。

### 演示 TCP 的字节流特性（所谓「粘包」）

```python
# tcp_server_stream.py
import socket

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", 9998))
srv.listen(1)
conn, _ = srv.accept()

import time
time.sleep(0.5)                          # 故意等一下，让三条消息在缓冲区里攒到一起
print("收到:", conn.recv(1024))          # 很可能一次就拿到 b'AAABBBCCC'
conn.close()
```

```python
# tcp_client_stream.py
import socket

s = socket.create_connection(("127.0.0.1", 9998))
s.sendall(b"AAA")
s.sendall(b"BBB")
s.sendall(b"CCC")
s.close()
```

### 正确的 TCP 消息分帧：长度前缀

```python
import struct
import socket

def send_msg(sock: socket.socket, payload: bytes) -> None:
    """先发 4 字节大端长度，再发内容"""
    sock.sendall(struct.pack(">I", len(payload)) + payload)

def recv_exactly(sock: socket.socket, n: int) -> bytes:
    """循环读满 n 字节——这是关键，recv 不保证一次读够"""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:                     # 返回空 bytes 表示对端已关闭
            raise ConnectionError("对端关闭了连接")
        buf += chunk
    return buf

def recv_msg(sock: socket.socket) -> bytes:
    header = recv_exactly(sock, 4)
    (length,) = struct.unpack(">I", header)
    return recv_exactly(sock, length)
```

`recv_exactly` 里的循环是新手最容易漏的一步。**`recv(n)` 只保证返回不超过 n 字节，从不保证返回正好 n 字节。**

### 抓 UDP 包

```bash
# 抓 DNS 查询（UDP 53）
sudo tcpdump -i any -nn udp port 53 -A

# 抓 QUIC / HTTP3（UDP 443）
sudo tcpdump -i any -nn udp port 443

# Wireshark 过滤表达式
# udp.port == 53
# dns.flags.response == 0        只看 DNS 查询
# quic
```

### 用 nc 手工测试 UDP 端口

```bash
# 服务端监听 UDP 9999
nc -u -l 9999

# 客户端发送
nc -u 127.0.0.1 9999

# 探测 UDP 端口是否开放（注意：结果不可靠，见踩坑）
nc -zvu 10.0.2.30 53
```

## 踩坑

1. **UDP 端口扫描结果基本不可信**。TCP 端口关闭会回 RST，能明确判断；UDP 端口关闭理论上会回 ICMP Port Unreachable，但**绝大多数防火墙会屏蔽 ICMP**，导致「端口开着」和「端口关着但 ICMP 被屏蔽」表现完全一样——都是没响应。所以 `nmap -sU` 极慢且经常给出 `open|filtered` 这种模糊结论。要确认 UDP 服务是否可用，唯一可靠的办法是**发一个该协议的合法请求看有没有业务响应**，比如测 DNS 就直接 `dig @10.0.2.30 example.com`。

2. **UDP 数据报太大导致 IP 分片，丢包率飙升**。UDP 本身理论最大 65507 字节，但一旦超过 MTU（通常 1500，减去 IP+UDP 头后约 1472 字节负载）就要 IP 分片。**IP 分片的致命之处在于：任何一个分片丢了，整个数据报都要丢弃**（IP 层没有分片级重传）。所以丢包率会被放大。实践中 UDP 单包应控制在 **1472 字节以内**，跨 VPN/隧道时更保守些取 1400。DNS 的 512 字节限制就是这个考虑的历史产物。

3. **`recv()` 缓冲区给小了，UDP 数据会被静默截断**。TCP 下 `recv(10)` 只取 10 字节，剩下的下次再取；UDP 下 `recvfrom(10)` 收到一个 100 字节的数据报，**只给你 10 字节，剩下 90 字节直接丢弃且不报错**。所以 UDP 的接收缓冲区一定要给足（一般直接给 65535）。

4. **UDP 没有连接状态，服务端重启客户端完全无感**。TCP 下服务端挂了，客户端会收到 RST 或读到 0；UDP 下客户端会一直往一个黑洞里发包，直到应用层超时。所以基于 UDP 的协议**必须自己实现心跳和超时**，否则故障发现会非常慢。

5. **`sendto` 返回成功不代表对方收到了**。它只表示「数据已经交给内核的发送缓冲区」。这是 UDP 测试中最容易做出错误断言的地方——不能用「发送函数没抛异常」作为通过标准，必须校验业务层的响应。

6. **UDP 接收缓冲区溢出导致静默丢包**。高流量场景下，如果应用消费速度跟不上，内核接收缓冲区满了就直接丢弃新到的包，**没有任何通知**。排查方法：

   ```bash
   # 看 UDP 的接收缓冲区错误计数，RcvbufErrors 持续增长就是溢出了
   netstat -su | grep -iE 'packet receive errors|RcvbufErrors|InErrors'

   # 调大缓冲区上限
   sysctl -w net.core.rmem_max=16777216
   sysctl -w net.core.rmem_default=262144
   ```

   应用侧也要设：

   ```python
   sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
   ```

7. **压测 UDP 服务时，把客户端的丢包算成服务端的错**。UDP 压测时客户端自己的发送缓冲区也会溢出。设计用例时要在两端都统计包计数，才能定位丢包发生在哪一侧。

8. **公司防火墙屏蔽 UDP 443，HTTP/3 测试结果失真**。很多企业网络只放行 TCP 443，QUIC 走不通，浏览器会自动回落到 HTTP/2。测 HTTP/3 时要先确认协议确实生效（Chrome DevTools 的 Protocol 列显示 `h3`），否则测的还是 HTTP/2。

## 面试怎么答

**Q：TCP 和 UDP 的区别？**

A（30 秒骨架）：TCP 面向连接、可靠、有序、基于字节流，有流量控制和拥塞控制，头部 20 字节起，只能一对一；UDP 无连接、不保证可靠和有序、基于数据报保留消息边界，没有流量和拥塞控制，头部固定 8 字节，支持广播多播。选型的核心不是「哪个更好」，而是**可靠性该由谁负责**：TCP 把可靠性做进内核，UDP 把控制权交给应用。实时音视频、游戏、DNS 用 UDP，Web、数据库、消息队列用 TCP。

**Q：既然 TCP 可靠，为什么还有人用 UDP？**

A：因为 TCP 的可靠性在某些场景下反而有害。最典型的是实时音视频：一个 200ms 前的音频帧丢了，TCP 会停下来重传，后面已经到达的帧全在缓冲区排队——这就是队头阻塞，用户体验是「卡顿半秒」。而那个帧补回来也没用了，对应的时刻早过去了。正确做法是直接丢弃播下一帧，只有 UDP 能做到。另外 DNS 这种一问一答的小包，用 TCP 光握手挥手就要付出好几倍于数据本身的开销。

**Q：UDP 不可靠，那要可靠怎么办？**

A：在应用层自己实现。QUIC 就是最好的例子——HTTP/3 底层是 UDP，但 QUIC 在用户态实现了序列号、确认、重传、拥塞控制，可靠性一点不少。这样做的收益是：可靠性的粒度可以做得比 TCP 更细。TCP 的重传会阻塞整条连接上的所有数据，而 QUIC 的每个 Stream 独立重传，一个 Stream 丢包不影响其他 Stream。另外把协议放在用户态还能快速迭代，不用等操作系统内核升级。

**Q：什么是 TCP 粘包，怎么解决？**

A：严格说「粘包」这个词本身就是误解——TCP 是字节流协议，**它从来就没有「包」的概念**，所以谈不上粘。应用连续 send 三次，接收方 recv 一次可能全拿到，也可能分多次拿到，这是设计如此。解决办法是应用层自己定义消息边界，三种方式：定长消息、长度前缀（最常用，先发 4 字节长度再发内容）、特殊分隔符（HTTP 头用 `\r\n`）。UDP 因为是数据报，天然有边界，不存在这个问题。实现长度前缀时有个坑：`recv(n)` 不保证一次读满 n 字节，必须写循环读到够为止。

**Q：UDP 包最大能发多大？**

A：理论上 65507 字节（65535 减去 IP 头 20 和 UDP 头 8），但**工程上必须控制在 1472 字节以内**。因为超过 MTU 就要 IP 分片，而 IP 分片没有分片级重传——任何一个分片丢失，整个数据报都会被丢弃，丢包率会被显著放大。DNS 早期限制 512 字节就是这个考虑。跨 VPN 或隧道时 MTU 更小，我一般保守取 1400。

## 参考

- [RFC 768 - User Datagram Protocol](https://datatracker.ietf.org/doc/html/rfc768)
- [RFC 9000 - QUIC: A UDP-Based Multiplexed and Secure Transport](https://datatracker.ietf.org/doc/html/rfc9000)
- 相关笔记：[[TCP 三次握手与四次挥手]]、[[TCP 可靠传输与滑动窗口]]、[[HTTP 长连接与 HTTP-2 多路复用]]、[[DNS 解析过程与 CDN 对测试的影响]]
