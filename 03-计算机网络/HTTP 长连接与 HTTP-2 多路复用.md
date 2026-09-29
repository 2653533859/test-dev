---
created: 2026-07-31
tags: [计算机网络/HTTP]
---

# HTTP 长连接与 HTTP/2 多路复用

> HTTP 的每一次版本演进，都是在解决同一个问题的不同层次：**怎样让一条 TCP 连接上跑更多请求、少等一点。**

![[assets/http-multiplexing.svg]]
*图示：HTTP/1.1 一条连接同时只能跑一个请求（队头阻塞），HTTP/2 用带 Stream ID 的帧交错传输实现多路复用，HTTP/3 换到 QUIC 上连 TCP 层的队头阻塞也一并解决。*

## 概念

### HTTP/1.0：一次请求一条连接

每发一个请求就三次握手建连、收到响应就四次挥手断开。一个包含 30 个资源的页面，要建 30 次连接。

代价有三层，一层比一层隐蔽：

1. **握手延迟**：每条连接白白多花 1 个 RTT（HTTPS 更多，还要 TLS 握手）
2. **慢启动惩罚**：每条新连接的 cwnd 都要从头涨（initcwnd 默认 10 个 MSS ≈ 14KB），**永远跑不到高速状态就结束了**
3. **TIME_WAIT 堆积**：主动关闭方每关一条就多一个 TIME_WAIT，端口消耗巨大

第 2 点是最容易被忽略、但影响最大的。详见 [[TCP 可靠传输与滑动窗口]]。

### HTTP/1.1：长连接（Keep-Alive）

**默认开启持久连接**，一条 TCP 连接上可以串行发送多个请求。

```text
Connection: keep-alive          （HTTP/1.1 的默认行为，写不写都一样）
Keep-Alive: timeout=60, max=100 （服务端建议：空闲 60s 关闭，最多复用 100 次）
Connection: close               （显式声明本次响应后关闭）
```

这解决了重复握手和慢启动的问题，但留下了一个新问题——**队头阻塞（Head-of-Line Blocking）**。

一条连接同一时刻只能处理一个请求：请求 A 发出后，必须等 A 的响应完整返回，才能发请求 B。如果 A 是一个耗时 3 秒的接口，B 和 C 就得干等 3 秒。

HTTP/1.1 曾定义过**流水线（Pipelining）**，允许不等响应就连续发多个请求。但服务端**必须按请求顺序返回响应**，所以队头阻塞只是从「客户端等待」挪到了「服务端排队」，并没有真正解决。加上代理实现混乱，浏览器全部默认禁用了它，这个特性事实上已经死亡。

浏览器的实际对策是**对同一个域名开 6 条并行连接**（Chrome 是 6）。这带来了 HTTP/1.1 时代的一整套「优化技巧」：

- **域名分片**：把资源拆到 `img1.cdn.com`、`img2.cdn.com`，突破 6 条限制
- **雪碧图**：把几十个小图标合成一张大图，减少请求数
- **资源合并**：所有 JS 打包成一个文件
- **内联**：小图片转 base64 直接嵌进 CSS

记住这些，因为**到了 HTTP/2 它们全部变成负优化**。

### HTTP/2：多路复用

HTTP/2 的核心改动是**二进制分帧层**。它不再是文本协议，而是把消息拆成一个个带元数据的**帧（Frame）**：

```text
+-----------------------------------------------+
|                 Length (24 bits)              |
+---------------+---------------+---------------+
|   Type (8)    |   Flags (8)   |
+-+-------------+---------------+---------------+
|R|                 Stream Identifier (31)      |     ← 关键：流 ID
+=+=============================================+
|                   Frame Payload               |
+-----------------------------------------------+
```

**每个帧都带 Stream ID**，接收端按 ID 把帧重新组装成完整的请求/响应。这意味着不同请求的帧可以**交错传输**——一条 TCP 连接上，A、B、C 三个请求的帧混在一起飞，谁先处理完谁先回。

四个核心特性：

1. **多路复用**：一条连接并行跑任意多个请求，彻底解决**应用层**队头阻塞
2. **头部压缩 HPACK**：用静态表 + 动态表 + 霍夫曼编码。第一个请求发完整头部，后续请求只发「索引号 + 差异部分」。对于头部动辄几百字节、body 却只有几十字节的 API 请求，压缩率极高
3. **服务端推送 Server Push**：服务端主动推送客户端还没请求的资源。**注意：这个特性因为命中率低、容易推重复资源浪费带宽，Chrome 从 106 版起已默认禁用，实际已被废弃**
4. **流优先级**：客户端可以标记「这个 CSS 比那张图片重要」，服务端据此调度

### HTTP/2 仍未解决的：TCP 层队头阻塞

多路复用只解决了**应用层**的队头阻塞。底层还是一条 TCP 连接，而 **TCP 保证字节流有序交付**——只要有一个 TCP 段丢了，后面所有已到达的数据都必须在内核缓冲区里等它重传完成，**不管这些数据属于哪个 Stream**。

于是出现一个反直觉的现象：**在高丢包网络下（如弱信号移动网络），HTTP/2 的表现可能比 HTTP/1.1 更差**。因为 HTTP/1.1 有 6 条独立的 TCP 连接，一条卡住其他 5 条还能跑；HTTP/2 只有一条，卡住就全卡。

### HTTP/3：换掉传输层

既然问题出在 TCP，那就不用 TCP。HTTP/3 基于 **QUIC**，QUIC 跑在 **UDP** 之上，在用户态自己实现了可靠传输。

带来的收益：

1. **真正的多路复用**：QUIC 的每个 Stream 独立维护序列号和重传，**一个 Stream 丢包只阻塞自己**
2. **握手更快**：QUIC 把传输层握手和 TLS 1.3 握手合并，首次连接 **1-RTT**，会话复用 **0-RTT**（TCP + TLS1.2 需要 3 个 RTT）
3. **连接迁移**：QUIC 用 **Connection ID** 而非四元组标识连接，手机从 Wi-Fi 切到 5G，IP 变了但连接不断
4. **协议在用户态**：不用等操作系统内核升级就能迭代拥塞控制算法

代价是 UDP 常被企业防火墙屏蔽，且用户态处理 CPU 开销更高。

### 版本对比总表

| | HTTP/1.0 | HTTP/1.1 | HTTP/2 | HTTP/3 |
|---|---------|----------|--------|--------|
| 传输层 | TCP | TCP | TCP | **UDP (QUIC)** |
| 连接复用 | 否 | 是（串行） | 是（并行） | 是（并行） |
| 应用层队头阻塞 | 有 | 有 | **无** | 无 |
| 传输层队头阻塞 | 有 | 有 | **有** | **无** |
| 报文格式 | 文本 | 文本 | 二进制帧 | 二进制帧 |
| 头部压缩 | 无 | 无 | HPACK | QPACK |
| 加密 | 可选 | 可选 | 事实强制 | **强制内置** |
| 建连 RTT（含加密） | 1(TCP)+2(TLS) | 同左 | 同左 | **1，复用时 0** |

## 用法

### 确认实际使用的协议版本

```bash
# curl 显示协议版本（响应行的 HTTP/2、HTTP/1.1）
curl -sI https://www.example.com | head -1

# 强制用各版本请求，对比行为
curl -I --http1.1 https://www.example.com
curl -I --http2   https://www.example.com
curl -I --http3   https://www.example.com     # 需要 curl 编译时带 HTTP/3 支持

# 看 ALPN 协商结果（TLS 握手时协商用哪个应用层协议）
openssl s_client -connect www.example.com:443 -alpn h2,http/1.1 </dev/null 2>/dev/null | grep -i 'ALPN'
# ALPN protocol: h2
```

浏览器里：F12 → Network → 右键表头 → 勾选 **Protocol** 列，会显示 `http/1.1`、`h2`、`h3`。

### 实测长连接的收益

```python
import time
import requests

URL = "https://api.example.com/v1/health"
N = 200

# 短连接：每次新建 TCP + TLS
t0 = time.perf_counter()
for _ in range(N):
    requests.get(URL, timeout=10)
short = time.perf_counter() - t0

# 长连接：Session 复用底层连接池
t0 = time.perf_counter()
with requests.Session() as s:
    for _ in range(N):
        s.get(URL, timeout=10)
long = time.perf_counter() - t0

print(f"短连接 {N} 次: {short:.2f}s")
print(f"长连接 {N} 次: {long:.2f}s")
print(f"提升: {short / long:.1f}x")
```

HTTPS 场景下差距通常在 3 倍以上——省掉的是每次的 TCP 握手 + TLS 握手 + 慢启动。

### 验证 HTTP/2 的多路复用效果

```bash
# 用 h2load（nghttp2 自带）压测，-m 指定单连接内的最大并发流数
h2load -n 1000 -c 1 -m 1   https://api.example.com/v1/health   # 单连接串行
h2load -n 1000 -c 1 -m 100 https://api.example.com/v1/health   # 单连接 100 并发流

# 对比两者的 requests/s——如果 -m 100 提升明显，说明多路复用确实生效
```

### 抓 HTTP/2 的包

HTTP/2 强制在 TLS 之上，`tcpdump` 抓到的是密文。要看明文有两种办法：

```bash
# 方法一：让客户端导出 TLS 会话密钥，Wireshark 用它解密
export SSLKEYLOGFILE=/tmp/sslkeys.log
curl --http2 https://www.example.com > /dev/null
# Wireshark → 首选项 → Protocols → TLS → (Pre)-Master-Secret log filename 填 /tmp/sslkeys.log

# 方法二：直接用 nghttp 看帧级别的交互
nghttp -nv https://www.example.com
# 输出里能看到 SETTINGS、HEADERS、DATA 帧和各自的 stream_id
```

Wireshark 过滤表达式：

```text
http2                          所有 HTTP/2 帧
http2.type == 1                只看 HEADERS 帧
http2.streamid == 5            只看第 5 号流
```

### Nginx 配置

```text
# 开启 HTTP/2（必须在 HTTPS 上）
server {
    listen 443 ssl;
    http2 on;                        # Nginx 1.25.1+ 的新写法

    # 客户端长连接
    keepalive_timeout 65s;
    keepalive_requests 1000;         # 一条连接最多服务 1000 个请求

    location / {
        proxy_pass http://backend;
        proxy_http_version 1.1;      # 关键：默认 1.0 不支持长连接
        proxy_set_header Connection "";  # 关键：清掉默认的 Connection: close
    }
}

# 到上游的长连接池
upstream backend {
    server 10.0.2.30:8080;
    keepalive 64;                    # 每个 worker 保持 64 条空闲长连接
    keepalive_timeout 60s;
}
```

`proxy_http_version 1.1` + `proxy_set_header Connection ""` 这两行是配置 upstream 长连接的必备组合，**漏了任何一行 keepalive 都不生效**——这是网关机器 TIME_WAIT 暴涨最常见的原因。

## 踩坑

1. **压测不开 Keep-Alive，数据严重失真**。每次新建连接要走握手 + 慢启动，测出的 QPS 会显著低于真实值，同时制造海量 TIME_WAIT 让压测机自己先扛不住。JMeter 的 HTTP 请求默认勾选 Use KeepAlive，但要确认服务端 `keepalive_timeout` 不为 0；`ab` 必须显式加 `-k`。

2. **HTTP/2 下继续用域名分片，性能反而下降**。HTTP/2 的优势建立在「**一条连接**跑所有请求」上——共享连接才能共享 HPACK 动态表、共享拥塞窗口、共享优先级调度。域名分片把请求打散到多个域名，就意味着多条连接，每条都要重新 TLS 握手、重新慢启动、动态表各自为政。**升级到 HTTP/2 时必须同步移除域名分片、雪碧图、资源合并这些 1.1 时代的优化**，否则白升级。

3. **Nginx 配了 upstream keepalive 却不生效**。忘记加 `proxy_http_version 1.1` 或 `proxy_set_header Connection ""`。验证方法：在上游机器上 `ss -tan | grep <网关IP> | wc -l`，看连接数是稳定在 keepalive 配置的数量附近，还是随请求量剧烈波动。

4. **客户端与服务端的 keepalive 超时不匹配，出现偶发 502**。如果客户端的空闲超时（比如 60s）比服务端的（比如 5s）长，那么在 5~60 秒这个窗口内，服务端已经关了连接但客户端不知道，复用这条死连接发请求就会失败。**规则：客户端的 keepalive 超时必须小于服务端的**。这类问题的典型现象是「偶发 502，重试就好，无规律」。

5. **HTTP/2 在弱网下不如 HTTP/1.1**。因为 TCP 层队头阻塞——一条连接丢包，所有 Stream 全停。而 HTTP/1.1 有 6 条独立连接，容错性反而更好。做移动端弱网测试时要专门覆盖这个场景，用 `tc netem` 注入 5% 丢包对比两种协议的表现。

6. **误以为 HTTP/2 必须用 HTTPS**。规范上 HTTP/2 支持明文（h2c），但**所有主流浏览器都只实现了基于 TLS 的 h2**。所以浏览器场景下事实强制 HTTPS，服务间调用可以用 h2c（gRPC 就常用 h2c）。

7. **还在测试 Server Push**。这个特性因为命中率低、容易重复推送浪费带宽，Chrome 106 起已默认禁用，Nginx 也移除了支持。**它已经是历史了**，面试提到时要说清楚这一点，反而是加分项。用 `103 Early Hints` + `preload` 是当下的替代方案。

8. **HTTP/3 被防火墙拦截，测的其实还是 HTTP/2**。很多企业网络只放行 TCP 443，UDP 443 直接丢弃。浏览器发现 QUIC 不通会静默回落到 HTTP/2。**测 HTTP/3 必须在 DevTools 里确认 Protocol 列显示 `h3`**，否则测了个寂寞。

9. **单连接的并发流数有上限**。HTTP/2 的 `SETTINGS_MAX_CONCURRENT_STREAMS` 默认值各家不同（Nginx 默认 128），超过就得排队。压测时如果并发数远超这个值，会发现吞吐上不去——不是服务端慢，是流被限了。

## 面试怎么答

**Q：HTTP/1.1 相比 1.0 有什么改进？**

A：最核心的是**默认开启长连接**，一条 TCP 连接可以复用给多个请求，省掉了每次的三次握手、四次挥手和 TCP 慢启动。其次是新增了**强制的 Host 头**，让一个 IP 能承载多个虚拟主机，这是虚拟主机和 CDN 的基础。另外还支持了分块传输 `Transfer-Encoding: chunked`（长度未知时流式返回）、`Range` 断点续传、以及更完善的缓存控制头 `Cache-Control` 和 `ETag`。

**Q：什么是队头阻塞？HTTP/2 怎么解决的？**

A：HTTP/1.1 虽然有长连接，但一条连接同一时刻只能处理一个请求——前一个响应没回来，后面的请求只能排队。如果第一个请求很慢，后面全被堵住，这就是应用层队头阻塞。浏览器的对策是对同域名开 6 条连接硬扛。HTTP/2 引入**二进制分帧层**，把消息拆成带 Stream ID 的帧，不同请求的帧可以在同一条连接上交错传输，接收端按 ID 重组，从而实现真正的并行——这就是多路复用。

**追问：HTTP/2 彻底解决队头阻塞了吗？**

A：**没有，只解决了应用层的**。底层还是一条 TCP 连接，TCP 保证字节流严格有序交付，所以只要一个 TCP 段丢了，后面所有已到达的数据都要在内核缓冲区等重传完成，不管属于哪个 Stream。这导致一个反直觉的结果：**高丢包的弱网环境下，HTTP/2 可能比 HTTP/1.1 更慢**，因为 1.1 有 6 条独立连接，一条卡住其他还能跑。真正解决这个问题的是 HTTP/3——它换到基于 UDP 的 QUIC，每个 Stream 独立重传，互不影响。

**Q：HTTP/3 为什么要用 UDP？不怕不可靠吗？**

A：不是放弃可靠性，而是把可靠性**从内核的 TCP 挪到用户态的 QUIC 里自己实现**。这么做有三个非做不可的理由：第一，只有摆脱 TCP 的全局有序约束，才能做到 Stream 级别的独立重传，彻底消除队头阻塞；第二，QUIC 把传输层握手和 TLS 1.3 握手合并，首连 1-RTT、复用 0-RTT，而 TCP + TLS1.2 要 3 个 RTT；第三，QUIC 用 Connection ID 而不是四元组标识连接，手机从 Wi-Fi 切到 5G，IP 变了连接也不断，这对移动端体验提升明显。另外协议在用户态还能快速迭代，不用等内核升级。代价是很多企业防火墙屏蔽 UDP，以及用户态处理的 CPU 开销更高。

**Q：升级到 HTTP/2 后，原来的前端优化手段还要保留吗？**

A：**恰恰相反，很多要删掉**。域名分片、雪碧图、资源合并、小文件内联，这些都是为了绕开 HTTP/1.1「6 条连接 + 队头阻塞」的限制。HTTP/2 的优势建立在「一条连接跑所有请求」上——共享连接才能共享 HPACK 动态表、共享拥塞窗口、共享优先级调度。域名分片会把请求打散到多条连接，每条都要重新握手、重新慢启动，直接抵消 HTTP/2 的收益。雪碧图和资源合并则会破坏细粒度缓存——改一个小图标要让整张大图缓存失效。所以升级 HTTP/2 是个**需要重测性能基线**的事，不是改个配置就完事。

**Q：你在测试中怎么验证长连接确实生效了？**

A：几个层次。最直接的是抓包看握手次数——发 100 个请求，如果只看到一次三次握手，那就是复用了。其次在服务端用 `ss -tan | grep <客户端IP> | wc -l` 看连接数是稳定还是暴涨。还可以写个对比脚本：同样 200 次请求，用 `requests.Session()` 和每次新建 `requests.get()` 各跑一遍比耗时，HTTPS 下通常有 3 倍以上差距。网关侧我会重点检查 Nginx 有没有配全 `proxy_http_version 1.1` 和 `proxy_set_header Connection ""`，漏一行 upstream keepalive 就不生效，表现就是网关机器 TIME_WAIT 暴涨。

## 参考

- [RFC 9113 - HTTP/2](https://datatracker.ietf.org/doc/html/rfc9113)
- [RFC 9114 - HTTP/3](https://datatracker.ietf.org/doc/html/rfc9114)
- [MDN - HTTP 的发展](https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Basics_of_HTTP/Evolution_of_HTTP)
- 相关笔记：[[HTTP 报文结构与请求方法]]、[[TCP 可靠传输与滑动窗口]]、[[TCP TIME_WAIT 与 CLOSE_WAIT 堆积排查]]、[[UDP 与 TCP 的取舍]]、[[HTTPS 加密原理与 TLS 握手过程]]
