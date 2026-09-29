---
created: 2026-07-31
tags: [计算机网络/TCP]
---

# TCP 三次握手与四次挥手

> 建连要三次、断连要四次，根源都在一句话：**TCP 是全双工的，每个方向都要单独确认、单独关闭**。

![[assets/tcp-handshake.svg]]
*图示：三次握手建立双向可靠通道，四次挥手分两个方向依次关闭；被动方收到 FIN 后先回 ACK，等自己数据发完才发自己的 FIN。*

## 概念

### 握手到底在「握」什么

很多人以为三次握手是「打招呼确认对方在线」。不对。TCP 是**面向连接、可靠、有序**的协议，可靠和有序都建立在**序列号（seq）**之上。三次握手真正要完成的是两件事：

1. **确认双向通路都是通的**（我能发你能收，你能发我能收）
2. **交换并同步双方的初始序列号 ISN**（Initial Sequence Number），后续所有数据的排序、去重、重传都靠它

顺带还协商了 MSS、窗口缩放因子（wscale）、是否支持 SACK 等选项。

### 三次握手的完整过程

```text
客户端                                                服务端
  |                                                      |
  |  ① SYN=1, seq=x                                      |   状态: LISTEN
  |----------------------------------------------------->|
  | 状态: SYN_SENT                          状态: SYN_RCVD |
  |                                                      |
  |  ② SYN=1, ACK=1, seq=y, ack=x+1                      |
  |<-----------------------------------------------------|
  | 状态: ESTABLISHED                                     |
  |                                                      |
  |  ③ ACK=1, seq=x+1, ack=y+1                           |
  |----------------------------------------------------->|
  |                                     状态: ESTABLISHED |
```

注意两个细节，这是区分「背过」和「懂了」的分水岭：

- **SYN 报文不携带数据，但消耗一个序列号**。所以第二个包的 `ack=x+1` 而不是 `ack=x`。
- **客户端在发出第三个包时就进入 ESTABLISHED 了**，服务端要收到第三个包才进入。这个时间差是后面很多问题的根源。

### 为什么必须是三次，两次不行？

标准答案是「防止已失效的连接请求报文突然又传到服务端」。展开推演：

假设只要两次（客户端发 SYN、服务端回 SYN+ACK 就认为连接建立）：

1. 客户端发出 SYN-1，这个包在某个网络节点上滞留了，迟迟没到。
2. 客户端超时重传 SYN-2，正常完成通信，连接关闭。
3. 此时滞留的 SYN-1 终于到了服务端。服务端一看是新的连接请求，回 SYN+ACK，**并直接认为连接已建立，分配好接收缓冲区、TCB 控制块，开始等数据**。
4. 客户端早就关了，根本不理它。服务端的资源就这么白白挂着。

第三次握手的本质是：**让服务端得到「客户端确实还在、并且确实想连」的确认**。

从更抽象的角度：要让双方都确认「双向通路可用」，理论上需要的最少交互次数就是 3。第一次让服务端确认「客户端的发送 + 服务端的接收」正常；第二次让客户端确认「服务端的发送 + 客户端的接收」正常；第三次让服务端确认「客户端的接收 + 服务端的发送」正常。少一次就一定有一个方向没被验证。

那四次行不行？行，但第二、三次可以合并（服务端的 ACK 和 SYN 一起发），合并后就是三次，多出来的一次纯属浪费。

### 四次挥手的完整过程

```text
客户端(主动关闭)                                      服务端(被动关闭)
  |  ① FIN=1, seq=u                                      |
  |----------------------------------------------------->|
  | 状态: FIN_WAIT_1                     状态: CLOSE_WAIT |
  |                                                      |
  |  ② ACK=1, ack=u+1        (内核立即回，无需应用参与)     |
  |<-----------------------------------------------------|
  | 状态: FIN_WAIT_2                                      |
  |                            ← 服务端此时可能还在发数据 → |
  |  ③ FIN=1, ACK=1, seq=w   (应用调用 close() 才发出)     |
  |<-----------------------------------------------------|
  | 状态: TIME_WAIT                       状态: LAST_ACK  |
  |                                                      |
  |  ④ ACK=1, ack=w+1                                    |
  |----------------------------------------------------->|
  | 等 2MSL 后 → CLOSED                    状态: CLOSED   |
```

### 为什么挥手要四次

因为 **TCP 全双工，关闭是「半关闭」语义的两次独立操作**。

客户端发 FIN 只表示「**我没有数据要发了**」，不表示「我不能收了」。服务端收到后，内核会立刻回 ACK（这是协议栈行为，不需要应用代码参与），但服务端的应用可能还有数据没发完——比如一个大文件正在传输到一半。所以服务端不能把 ACK 和自己的 FIN 合并发送，必须等应用主动调用 `close()` 才发第三个包。

**握手时能合并（SYN+ACK），挥手时不能合并（ACK 与 FIN 分开），根本原因就是中间夹了一段「被动方应用层的收尾时间」。**

一个反例可以印证：如果服务端应用在收到 FIN 时正好没有任何待发数据，且立刻 `close()`，Linux 内核确实会把 ACK 和 FIN 合并成一个包发出——这时候抓包看到的就是「三次挥手」。所以严格说是「四次」是常态，不是铁律。

## 用法

### 抓包看握手

```bash
# 只抓握手和挥手相关的包：SYN、FIN、RST 三个标志位任一置位
sudo tcpdump -i any -nn 'tcp[tcpflags] & (tcp-syn|tcp-fin|tcp-rst) != 0 and host api.example.com'
```

发起一个请求，会看到：

```text
10.0.1.15.51234 > 93.184.216.34.443: Flags [S],  seq 1450233123, win 64240, options [mss 1460,sackOK,wscale 7]
93.184.216.34.443 > 10.0.1.15.51234: Flags [S.], seq 3821059912, ack 1450233124, win 65535, options [mss 1440]
10.0.1.15.51234 > 93.184.216.34.443: Flags [.],  ack 3821059913, win 502
...数据传输...
10.0.1.15.51234 > 93.184.216.34.443: Flags [F.], seq 1450233800, ack 3821061200
93.184.216.34.443 > 10.0.1.15.51234: Flags [.],  ack 1450233801
93.184.216.34.443 > 10.0.1.15.51234: Flags [F.], seq 3821061200, ack 1450233801
10.0.1.15.51234 > 93.184.216.34.443: Flags [.],  ack 3821061201
```

标志位速查：`[S]` = SYN，`[S.]` = SYN+ACK（点号代表 ACK），`[.]` = 纯 ACK，`[F.]` = FIN+ACK，`[P.]` = PSH+ACK（带数据），`[R]` = RST。

### Wireshark 里的过滤表达式

```text
tcp.flags.syn == 1 && tcp.flags.ack == 0     # 只看第一次握手（新建连接请求）
tcp.flags.reset == 1                          # 看 RST，定位连接被强制中断
tcp.analysis.retransmission                   # 看重传，判断链路质量
tcp.stream eq 3                               # 只看第 3 条 TCP 流的全过程
```

排查握手问题的实用技巧：**只看 SYN 但没有 SYN+ACK**，说明请求根本没到服务端（防火墙丢包）或服务端没监听；**SYN 后收到 RST**，说明包到了但端口没进程监听（Connection refused）；**SYN 重传多次后超时**，说明中间被静默丢弃（安全组 DROP 而非 REJECT）。

### 观察连接状态

```bash
# 看各状态的连接数分布
ss -tan | awk 'NR>1 {print $1}' | sort | uniq -c | sort -rn

# 输出示例
#  8534 TIME-WAIT
#   312 ESTAB
#    27 CLOSE-WAIT
#     3 LISTEN

# 看半连接队列（SYN_RECV）是否堆积——SYN Flood 或 backlog 太小的征兆
ss -tan state syn-recv | wc -l

# 查看 accept 队列溢出次数，非 0 且持续增长说明应用 accept 太慢
netstat -s | grep -i 'listen'
# 输出：xxx times the listen queue of a socket overflowed
```

### 用 Python 模拟半开连接

理解「三次握手第三个包由客户端决定」最直观的方式，是自己制造一个只完成两次的连接：

```python
import socket
import time

# 建立连接后立刻不发数据也不关闭，观察服务端状态
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(5)
s.connect(("127.0.0.1", 8080))   # connect() 返回时三次握手已完成
print("已建连，此时两端都是 ESTABLISHED，去 ss -tan 看看")
time.sleep(60)                    # 期间在另一个终端观察
s.close()                         # 主动关闭方 → 本机会进入 TIME_WAIT
```

## 踩坑

1. **`connect()` 成功不代表服务可用**。`connect()` 返回只说明三次握手完成，而在 Linux 上，三次握手是**内核协议栈完成的**，即使应用进程卡死（比如 GC 停顿、线程池打满没人调 `accept()`），只要 accept 队列没满，握手照样成功。表现为：端口探测正常、监控报警不响，但所有请求都超时。判断依据是 `netstat -s | grep overflowed` 是否在涨，以及 `ss -lnt` 里 `Recv-Q`（当前 accept 队列长度）是否逼近 `Send-Q`（队列上限）。

2. **压测时大量连接失败，误以为是服务端性能瓶颈**。先查是不是 SYN 队列满了：

   ```bash
   # 半连接队列大小
   cat /proc/sys/net/ipv4/tcp_max_syn_backlog
   # 全连接队列上限取 min(somaxconn, listen() 传入的 backlog)
   cat /proc/sys/net/core/somaxconn
   ```

   很多框架 `listen(backlog)` 默认只有 128，压测时瞬间打满，新连接被静默丢弃，客户端表现为连接超时。这是**配置问题不是性能问题**，容易背锅。

3. **客户端报 `Connection reset by peer`（RST）不等于网络故障**。常见原因：服务端主动 `close()` 了但缓冲区还有未读数据（触发 RST 而非 FIN）、服务端进程崩溃、防火墙/LB 的空闲连接超时踢连接、backlog 溢出且开启了 `tcp_abort_on_overflow`。要区分是哪种，看 RST 出现的时机——握手阶段的 RST 是端口不通，数据传输中的 RST 多是对端异常或被中间设备切断。

4. **长时间空闲的连接被中间设备静默回收**。云 LB、NAT 网关通常有 300s ~ 900s 的空闲超时，超时后直接丢弃连接表项且**不发 FIN/RST**。两端都还以为连接活着，等下次发数据才发现对端不响应，表现为「第一个请求超时、重试就好了」。解决办法是开 TCP Keepalive 或应用层心跳：

   ```bash
   # Linux 默认 7200 秒才开始探活，对于 LB 超时来说太晚，需要调小
   sysctl -w net.ipv4.tcp_keepalive_time=120     # 空闲 120s 后开始探测
   sysctl -w net.ipv4.tcp_keepalive_intvl=30     # 每 30s 探一次
   sysctl -w net.ipv4.tcp_keepalive_probes=3     # 连续 3 次没回应就断开
   ```

   Python 里给单个 socket 开启：

   ```python
   import socket
   s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
   s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
   s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 120)
   s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 30)
   s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
   ```

5. **把「连接超时」和「读取超时」混为一谈**。`requests` 的 `timeout=(3, 30)` 里前者是建连超时（三次握手阶段），后者是读超时（等响应数据）。日志里区分这两种能直接定位问题：连接超时 → 网络/防火墙/backlog；读超时 → 服务端处理慢。生产脚本必须显式区分：

   ```python
   import requests
   try:
       r = requests.get(url, timeout=(3, 30))
   except requests.exceptions.ConnectTimeout:
       print("建连阶段超时 → 查网络、安全组、服务是否监听")
   except requests.exceptions.ReadTimeout:
       print("连上了但服务端半天不回 → 查服务端处理逻辑、慢 SQL")
   ```

6. **SYN Flood 攻击与防护**。攻击者伪造大量源 IP 发 SYN 不回第三个包，塞满半连接队列。防护开关：`sysctl -w net.ipv4.tcp_syncookies=1`，队列满时不再分配资源，而是把连接信息编码进序列号发回去，收到第三个包时再还原。安全测试里如果要验证这一项，务必在授权的测试环境进行。

## 面试怎么答

**Q：讲一下 TCP 三次握手。**

A（30 秒骨架）：客户端发 SYN 带自己的初始序列号 x，进入 SYN_SENT；服务端回 SYN+ACK，带自己的序列号 y 并确认 x+1，进入 SYN_RCVD；客户端再回 ACK 确认 y+1，双方进入 ESTABLISHED。核心目的不是「打招呼」，而是**双向确认通路可用 + 同步双方的初始序列号**，顺带协商 MSS、窗口缩放、SACK 等选项。

**Q：为什么是三次，两次不行吗？**

A：两次的话，服务端没法确认客户端是否真的收到了自己的 SYN+ACK。最经典的问题场景是：客户端一个早已超时的 SYN 在网络中滞留很久后才到达服务端，服务端回 SYN+ACK 就直接建连并分配资源，但客户端根本不认这个连接，服务端的 TCB 和缓冲区就白白浪费了。从确认次数上算，要让双方都确认「自己的收发都正常」，三次是理论最小值。四次也能实现，但第二、三次能合并，合并完就是三次。

**Q：为什么挥手要四次，不能像握手一样合并？**

A：因为 TCP 是全双工，两个方向要各关一次。主动方发 FIN 只代表「我没数据要发了」，但仍然能收。被动方收到 FIN 后，内核会立刻回 ACK，可此时被动方的**应用层可能还有数据没发完**，所以不能马上发 FIN——必须等应用调用 `close()`。中间夹了这段应用层收尾时间，ACK 和 FIN 就没法合并。反过来说，如果被动方恰好没有待发数据且立刻关闭，内核确实会把 ACK 和 FIN 合并，抓包就变成「三次挥手」。

**Q：客户端 `connect()` 返回成功，能说明服务是好的吗？**

A：不能。三次握手是内核协议栈完成的，只要 accept 队列没满，即使应用进程卡死、没人调 `accept()`，握手一样成功。所以健康检查绝对不能只做端口探测，必须做到应用层——起码要 `curl` 一个 `/health` 接口并校验返回内容。我排查过一次线上故障就是这个：LB 的健康检查是 TCP 探测，应用因为 Full GC 停顿几十秒完全无响应，但 LB 认为节点健康，流量持续打进去全部超时。

**Q：抓包发现客户端发了 SYN，但一直没收到 SYN+ACK，可能是什么原因？**

A：分几种情况看。如果是 SYN 重传多次后超时（没有任何响应），大概率是包被静默丢弃了——安全组/防火墙配的是 DROP 策略、或者路由不通、或者服务端 SYN 队列满了在丢包。如果收到的是 RST，说明包到了目标主机但那个端口没有进程监听。如果收到 ICMP unreachable，那是路由或主机不可达。我的排查顺序是：先在服务端也抓一份包，判断包到底有没有到达——到了说明是服务端侧的问题，没到就沿路查防火墙和路由。

## 参考

- [RFC 9293 - Transmission Control Protocol](https://datatracker.ietf.org/doc/html/rfc9293)
- [tcpdump 手册](https://www.tcpdump.org/manpages/tcpdump.1.html)
- 相关笔记：[[TCP TIME_WAIT 与 CLOSE_WAIT 堆积排查]]、[[TCP 可靠传输与滑动窗口]]、[[UDP 与 TCP 的取舍]]、[[OSI 七层与 TCP-IP 四层模型]]
