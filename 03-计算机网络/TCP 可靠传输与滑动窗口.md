---
created: 2026-07-31
tags: [计算机网络/TCP]
---

# TCP 可靠传输与滑动窗口

> IP 层只提供「尽力而为」的投递——可能丢、可能乱序、可能重复。TCP 用序列号、确认、重传、窗口这四件套，在不可靠的地基上盖出了可靠的房子。

![[assets/tcp-sliding-window.svg]]
*图示：发送方缓冲区被切成「已确认 / 已发未确认 / 可发 / 不可发」四段，窗口随 ACK 到达向右滑动；丢包时靠三次重复 ACK 触发快速重传。*

## 概念

### 可靠性由哪几个机制共同保证

| 问题 | TCP 的解法 |
|------|-----------|
| 数据丢了 | 超时重传 + 快速重传 |
| 数据乱序到达 | 序列号排序，接收缓冲区重组 |
| 数据重复 | 序列号去重 |
| 数据损坏 | 校验和 checksum，坏了直接丢弃当作丢包 |
| 发得太快，接收方处理不过来 | 流量控制（滑动窗口 rwnd） |
| 发得太快，中间网络扛不住 | 拥塞控制（cwnd + 慢启动等算法） |

面试里最容易漏答的是最后两条——**流量控制和拥塞控制是两回事**，前者保护接收方，后者保护网络。

### 序列号与累计确认

TCP 的序列号是**按字节编号**的，不是按包。`seq=1000, len=500` 表示这个段携带的是第 1000 到 1499 字节。

确认号 `ack=1500` 的含义是：**「1500 之前的字节我全收到了，我下一个期待 1500」**——这叫**累计确认**。它有个很漂亮的性质：单个 ACK 丢了完全没关系，后面任何一个更大的 ACK 都能覆盖它。

代价是：如果中间某个段丢了，后面的段即使收到了也没法确认（只能一直重复 ack 丢失位置），这就是 **SACK（Selective ACK）** 出现的原因——它让接收方能额外告诉发送方「我还额外收到了 3000-4000 这一段」，发送方就只补丢的那一块，不用全部重传。现代系统默认开启：

```bash
cat /proc/sys/net/ipv4/tcp_sack     # 1 = 开启
```

### 滑动窗口：为什么不能「发一个等一个」

最朴素的可靠传输是「停止等待」：发一个包，等 ACK，再发下一个。它的吞吐上限是 `MSS / RTT`。

算一笔账：MSS = 1460 字节，RTT = 50ms，那么吞吐 = 1460 / 0.05 ≈ **28 KB/s**。哪怕你有千兆带宽也只能跑出这个速度——**时间全浪费在等待上了**。

滑动窗口的思路是**流水线**：不等 ACK，一口气把窗口内的数据全发出去，边发边收 ACK，收到 ACK 就把窗口往右滑，腾出空间继续发。吞吐上限变成 `窗口大小 / RTT`。

窗口开到多大合适？理论最优值是 **BDP（带宽时延积）= 带宽 × RTT**。比如 100Mbps 带宽、50ms RTT：

```text
BDP = 100 Mbit/s × 0.05 s = 5 Mbit = 625 KB
```

也就是说窗口至少要开到 625KB 才能把链路跑满。但 TCP 头里的窗口字段只有 16 位，最大 65535 字节——所以才有了**窗口缩放选项（Window Scale）**，在三次握手时协商一个位移因子，把窗口扩大到最多 1GB。

```bash
cat /proc/sys/net/ipv4/tcp_window_scaling    # 1 = 开启
```

**这解释了一个常见的性能困惑**：跨国专线带宽标称很高，但单条 TCP 连接就是跑不满。因为 RTT 大（比如 200ms），BDP 极大，如果窗口没开够，吞吐就被卡死在 `窗口 / RTT`。解法要么调大窗口，要么开多条并发连接。

### 发送窗口 = min(rwnd, cwnd)

- **rwnd（接收窗口）**：接收方在每个 ACK 里通过 TCP 头的 Window 字段告诉发送方「我的缓冲区还剩多少」。这是**流量控制**，防止把接收方撑爆。
- **cwnd（拥塞窗口）**：发送方**自己维护**的一个变量，网络里根本没有人告诉你这个值，它是通过「丢包」这个信号推测出来的。这是**拥塞控制**，防止把中间网络压垮。

实际发送窗口取两者较小值。所以性能上不去时要先判断是被哪个卡住的：抓包看 ACK 里的 win 字段，如果长期很小甚至为 0，是接收方处理不过来（rwnd 受限）；如果 win 很大但发送速率仍上不去，那就是 cwnd 受限（网络拥塞或丢包）。

### 拥塞控制四阶段

```text
cwnd
 ↑
 |            /\        慢启动阈值 ssthresh
 |           /  \        ----------------------
 |    ______/    \___
 |   /   拥塞避免  |  快速恢复（收到 3 个重复 ACK）
 |  /  (线性+1)   ↓
 | / 慢启动        超时 → cwnd 直接砍回 1，重新慢启动
 |/ (指数×2)
 +----------------------------------------→ 时间
```

1. **慢启动**：cwnd 从 1 个 MSS 开始，每收到一个 ACK 就 +1，实际效果是**每个 RTT 翻倍**（指数增长）。名字叫"慢"，其实涨得飞快，只是起点低。
2. **拥塞避免**：cwnd 达到 ssthresh 后改为每个 RTT 只 +1（线性增长），小心试探。
3. **快速重传 + 快速恢复**：收到 3 个重复 ACK，判定为个别丢包（网络还通着），ssthresh 减半、cwnd 减半，从拥塞避免继续——不用回到起点。
4. **超时重传**：连 ACK 都收不到了，判定网络严重拥塞，cwnd **直接砍回 1**，ssthresh 减半，重新慢启动。

**超时的代价远大于快速重传**，这是性能优化的关键认知：偶发丢包（触发快速重传）影响有限，而 RTO 超时会让吞吐断崖式下跌。

现代 Linux 默认用 CUBIC；BBR 是 Google 提出的新算法，不以丢包为拥塞信号，而是主动测量带宽和 RTT，在高丢包率的长肥管道上提升显著：

```bash
sysctl net.ipv4.tcp_congestion_control        # 查看当前算法
sysctl -w net.ipv4.tcp_congestion_control=bbr # 切换到 BBR（需内核 4.9+）
```

### 慢启动对短连接的隐藏成本

一个常被忽略的点：**每条新建的 TCP 连接都要重新经历慢启动**。初始 cwnd（initcwnd）Linux 默认是 10 个 MSS ≈ 14KB。也就是说，一个 100KB 的页面，第一个 RTT 只能发出 14KB，需要好几个 RTT 才能传完。

这正是**长连接（Keep-Alive）价值巨大**的底层原因——复用连接就是复用已经"热身"好的大 cwnd。压测时如果不开 Keep-Alive，每次都在慢启动阶段，测出来的吞吐会显著低于真实生产表现。

## 用法

### 用 iperf3 实测窗口对吞吐的影响

```bash
# 服务端
iperf3 -s

# 客户端：默认窗口
iperf3 -c 10.0.2.30 -t 10

# 客户端：手动指定较小的窗口，观察吞吐骤降
iperf3 -c 10.0.2.30 -t 10 -w 64K

# 客户端：开 4 条并发流，看总吞吐是否明显高于单流（若是，说明单流被窗口卡住了）
iperf3 -c 10.0.2.30 -t 10 -P 4
```

### 用 ss 看单条连接的窗口与重传

```bash
ss -tin dst 10.0.2.30
```

输出里的关键字段：

```text
cubic wscale:7,7 rto:204 rtt:3.5/1.75 mss:1448 cwnd:10 ssthresh:7
bytes_sent:52480 bytes_retrans:1448 retrans:0/2 rcv_space:14480
```

- `rtt:3.5/1.75` —— 平滑 RTT 3.5ms，抖动 1.75ms。RTT 抖动大说明链路不稳。
- `cwnd:10` —— 拥塞窗口只有 10 个 MSS，还在慢启动初期或者刚被丢包打回来。
- `retrans:0/2` —— 当前重传 0 个，累计重传 2 次。**重传率超过 1% 就要认真查链路了**。
- `ssthresh:7` —— 阈值被降到 7，说明**发生过拥塞**。
- `rcv_space` —— 接收缓冲区大小，接收窗口的依据。

### 全局重传率统计

```bash
# 看整机的重传情况，这是判断"是不是网络问题"最快的一招
nstat -az | grep -iE 'TcpRetransSegs|TcpOutSegs'

# 或者
netstat -s | grep -iE 'retransmit|segments send out'
# 重传率 = 重传段数 / 发出总段数，正常应远低于 1%
```

### 用 tc 注入丢包，验证系统的容错能力

这是混沌测试里最常用的一招，可以复现「弱网导致接口超时」类问题：

```bash
# 给 eth0 出方向注入 5% 丢包
sudo tc qdisc add dev eth0 root netem loss 5%

# 注入 200ms 延迟 ± 50ms 抖动，模拟跨国链路
sudo tc qdisc change dev eth0 root netem delay 200ms 50ms distribution normal

# 组合：延迟 + 丢包 + 乱序
sudo tc qdisc change dev eth0 root netem delay 100ms loss 2% reorder 25% 50%

# 查看当前规则
tc qdisc show dev eth0

# 用完一定要删掉，否则整台机器的网络都受影响
sudo tc qdisc del dev eth0 root
```

配合前面的 `ss -tin` 观察，能直观看到丢包注入后 cwnd 被打下来、重传数飙升的全过程。

### Wireshark 里定位传输问题

```text
tcp.analysis.retransmission              # 重传包
tcp.analysis.fast_retransmission         # 快速重传
tcp.analysis.duplicate_ack               # 重复 ACK
tcp.analysis.zero_window                 # 接收窗口为 0，接收方顶不住了
tcp.analysis.window_full                 # 发送方把窗口填满了，在等 ACK
tcp.analysis.out_of_order                # 乱序
```

`Statistics → TCP Stream Graphs → Time Sequence (tcptrace)` 能画出序列号随时间的增长曲线：曲线平滑上升说明传输顺畅；出现平台期说明卡住了；出现回退的小点就是重传。

## 踩坑

1. **看到重传就断定「网络有问题」**。互联网上 0.1% 以内的重传是完全正常的。真正需要警惕的是：重传率持续 >1%、或者出现大量**超时重传**（不是快速重传）。区分方法是看 Wireshark 里重传发生的时间间隔——快速重传几乎是立即的，超时重传会有一个明显的 RTO 空档（通常 200ms 起步，且指数退避）。

2. **Zero Window 被误判成网络问题，其实是应用问题**。抓包看到大量 `TCP ZeroWindow`，意味着接收方的接收缓冲区满了——数据到了内核但**应用层没有及时 `read()`**。根因在应用：线程池打满、处理逻辑里有慢 SQL、消费者阻塞。这时候扩带宽毫无用处，要去优化应用的消费速度。

3. **压测不开 Keep-Alive，测出来的数据没有参考价值**。每次新建连接都要走三次握手 + 慢启动，测出的 QPS 会显著偏低，还会额外制造海量 TIME_WAIT。JMeter 的 HTTP 请求默认勾选了 Use KeepAlive，但要确认服务端也支持；`wrk`/`ab` 需要显式加参数：

   ```bash
   ab -n 10000 -c 100 -k http://api.example.com/health   # -k 开启 Keep-Alive
   wrk -t4 -c100 -d30s --latency http://api.example.com/health  # wrk 默认长连接
   ```

4. **Nagle 算法与延迟确认的组合，导致 40ms 的诡异延迟**。Nagle 算法会把小包攒起来一起发（等上一个包的 ACK 回来），延迟确认（Delayed ACK）会把 ACK 延迟最多 40ms 再发（期望能捎带数据）。两者相遇就是死等：发送方等 ACK 才发下一个小包，接收方等数据才捎带 ACK。表现为「每个请求稳定多出约 40ms」。解法是在小包交互频繁的场景（如 RPC、游戏）关闭 Nagle：

   ```python
   import socket
   s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
   s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)   # 关闭 Nagle
   ```

5. **跨国链路单连接跑不满带宽，误以为是带宽不够**。这是典型的 BDP 问题：RTT 200ms、带宽 200Mbps，BDP = 5MB，而默认接收缓冲区上限可能只有 6MB 甚至更小，一旦不够就被卡死。调大缓冲区上限：

   ```bash
   # 三个值分别是 min / default / max
   sysctl -w net.ipv4.tcp_rmem="4096 87380 16777216"
   sysctl -w net.ipv4.tcp_wmem="4096 65536 16777216"
   ```

   或者干脆用多并发连接绕过——CDN 和下载工具就是这么干的。

6. **在共享的测试环境用 `tc` 注入故障，忘记删除规则**。`tc qdisc add ... root` 影响整张网卡的所有流量，会连累同机器上其他人的测试。务必：只在独占环境操作、注入前先记录原有规则、脚本里用 `trap` 保证异常退出也能清理。

   ```bash
   #!/bin/bash
   trap 'sudo tc qdisc del dev eth0 root 2>/dev/null' EXIT
   sudo tc qdisc add dev eth0 root netem loss 5%
   pytest tests/test_weak_network.py
   ```

## 面试怎么答

**Q：TCP 是怎么保证可靠传输的？**

A（30 秒骨架）：靠六个机制配合——① 每个字节都有序列号，用来排序和去重；② 接收方发累计确认 ACK，发送方据此知道哪些到了；③ 没等到 ACK 就重传，分超时重传和三次重复 ACK 触发的快速重传；④ 校验和保证数据没被破坏；⑤ 滑动窗口做流量控制，防止发太快撑爆接收方；⑥ 拥塞控制（慢启动、拥塞避免、快速恢复）防止发太快压垮网络。

**Q：流量控制和拥塞控制的区别？**

A：目标不同。流量控制是**端到端**的，保护接收方——接收方在 ACK 里通过 Window 字段告诉发送方自己缓冲区还剩多少，发送方不能超发。拥塞控制是**面向整个网络**的，保护中间链路——网络不会主动告诉你它堵了，发送方只能通过丢包和 RTT 变化去推测，自己维护一个拥塞窗口 cwnd。实际发送窗口取 `min(rwnd, cwnd)`。排查性能问题时这个区分很有用：抓包看 ACK 里 win 长期为 0，就是接收方应用消费不过来；win 很大但速率上不去，就是网络侧拥塞。

**Q：滑动窗口是干什么的，窗口大小怎么定？**

A：滑动窗口把「发一个等一个」变成流水线批量发送，把吞吐上限从 `MSS/RTT` 提升到 `窗口/RTT`。理论最优窗口是带宽时延积 BDP = 带宽 × RTT。因为 TCP 头的窗口字段只有 16 位（最大 64KB），高带宽长时延链路不够用，所以有窗口缩放选项在握手时协商放大因子。我遇到过跨国接口单连接跑不满带宽的问题，就是 BDP 远大于默认缓冲区，调大 `tcp_rmem` 上限后解决。

**Q：为什么超时重传比快速重传「贵」？**

A：因为两者对网络状况的判断不同。收到 3 个重复 ACK 说明后续的包还在正常到达，网络只是偶发丢包，所以只把 cwnd 和 ssthresh 减半，从拥塞避免继续跑。而超时意味着连 ACK 都收不到了，判定网络严重拥塞，cwnd 直接砍回 1 重新慢启动——吞吐会断崖式下跌，且要好几个 RTT 才能恢复。所以性能测试里我会特别关注超时重传的数量，它比总重传数更能说明问题严重程度。

**Q：你在测试中怎么模拟弱网？**

A：Linux 上用 `tc` 的 netem 模块，可以注入丢包、延迟、抖动、乱序、重复，比如 `tc qdisc add dev eth0 root netem delay 200ms 50ms loss 5%` 模拟跨国弱网。移动端我会用 Charles 的 Throttle 或 Network Link Conditioner。注入后配合 `ss -tin` 观察 cwnd 被打下来、重传数上涨的过程，同时验证客户端的超时设置、重试策略、降级逻辑是否正确——很多线上事故都是弱网下重试风暴放大出来的。用完必须清理 tc 规则，我一般写在脚本的 `trap EXIT` 里防止漏删。

## 参考

- [RFC 5681 - TCP Congestion Control](https://datatracker.ietf.org/doc/html/rfc5681)
- [RFC 2018 - TCP Selective Acknowledgment Options](https://datatracker.ietf.org/doc/html/rfc2018)
- [Linux tc-netem 手册](https://man7.org/linux/man-pages/man8/tc-netem.8.html)
- 相关笔记：[[TCP 三次握手与四次挥手]]、[[TCP TIME_WAIT 与 CLOSE_WAIT 堆积排查]]、[[UDP 与 TCP 的取舍]]
