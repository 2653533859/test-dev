---
created: 2026-07-31
tags: [计算机网络/TCP]
---

# TCP TIME_WAIT 与 CLOSE_WAIT 堆积排查

> 两个名字很像的状态，含义完全相反：**TIME_WAIT 多半是正常的、CLOSE_WAIT 多半是 bug**。搞混这一点，排查方向就会整个跑偏。

![[assets/tcp-state-machine.svg]]
*图示：主动关闭方经 FIN_WAIT_1 → FIN_WAIT_2 → TIME_WAIT 等 2MSL 后关闭；被动关闭方停在 CLOSE_WAIT，直到应用自己调 close() 才继续。*

## 概念

### 谁会进入哪个状态

一句话定位：

- **主动关闭的一方**（先发 FIN 的那个）→ 最终进入 **TIME_WAIT**
- **被动关闭的一方**（后发 FIN 的那个）→ 中间会经过 **CLOSE_WAIT**

所以看到某台机器上一堆 TIME_WAIT，第一反应应该是「这台机器是主动关连接的一方」——通常是客户端、或者是配置了短连接的反向代理。

### TIME_WAIT：为什么必须等 2MSL

MSL（Maximum Segment Lifetime）是报文在网络中的最大生存时间，RFC 建议 2 分钟，Linux 实现里写死为 30 秒，所以 **2MSL = 60 秒**，而且**不可通过 sysctl 修改**（想改只能改内核宏 `TCP_TIMEWAIT_LEN` 重新编译）。

等这 60 秒有两个理由，缺一不可：

**理由一：保证最后一个 ACK 能到达对端。**

四次挥手的第四个包（主动方发的 ACK）如果丢了，被动方会超时重传它的 FIN。如果主动方已经彻底 CLOSED，收到这个 FIN 只会回一个 RST，被动方就会以异常方式关闭连接（可能导致它认为数据没发完）。停留在 TIME_WAIT 期间，主动方还能正常重发 ACK。

**理由二：让本次连接的所有残留报文在网络中自然消亡。**

假设不等待，立刻用同一个四元组 `(源IP, 源端口, 目的IP, 目的端口)` 建立新连接（所谓「化身连接」）。此时上一个连接迟到的数据包突然到达，序列号如果恰好落在新连接的接收窗口内，就会被当作新连接的数据接收——**数据错乱，且极难排查**。等待 2MSL 保证旧报文全部消失。

### CLOSE_WAIT：卡住的一定是应用代码

被动方收到 FIN 后，**内核会自动回 ACK**（这一步不需要应用参与），然后连接进入 CLOSE_WAIT，等待应用调用 `close()`。

关键在于：**CLOSE_WAIT 没有超时机制**。内核会一直等下去。只要应用不 `close()`，这个状态就永远保持，socket 和文件描述符一直被占着。

所以 **CLOSE_WAIT 堆积 100% 是应用层 bug**，典型原因：

1. 异常分支里漏了关闭（try 里 `conn.close()`，但异常抛出后没执行到）
2. 连接池实现有缺陷，归还连接时没检测到对端已关闭
3. 代码里读到 `recv()` 返回 0（对端已关）却没有处理，继续循环
4. 线程/协程卡死在别的地方，压根没走到 close 逻辑

### 两者的危害对比

| | TIME_WAIT 堆积 | CLOSE_WAIT 堆积 |
|---|---------------|-----------------|
| 性质 | 协议正常行为 | 应用代码缺陷 |
| 会自动消失吗 | 会，60 秒后 | **不会，永久占用** |
| 主要危害 | 占用本地端口，端口耗尽后无法建新连接 | 占用 fd，达到 `ulimit -n` 后无法接受任何新连接 |
| 典型触发 | 短连接高频压测、Nginx 未开 upstream keepalive | 代码漏 close、连接池泄漏 |
| 处理思路 | 调参 + 改用长连接 | **必须改代码**，调参无效 |
| 紧急程度 | 一般 | 高，会导致服务彻底不可用 |

## 用法

### 一条命令看清状态分布

```bash
# 统计各 TCP 状态的数量（最常用）
ss -tan | awk 'NR>1 {print $1}' | sort | uniq -c | sort -rn

# 输出示例
#  28451 TIME-WAIT
#    892 ESTAB
#    437 CLOSE-WAIT     ← 这个数字持续上涨就是有泄漏
#      6 LISTEN
```

`ss` 比 `netstat` 快得多（直接读 netlink 而非遍历 `/proc`），连接数上万时差距非常明显，生产环境优先用 `ss`。

### 定位 CLOSE_WAIT 是哪个进程、连着谁

```bash
# 1. 找出有 CLOSE_WAIT 的进程和对端地址
ss -tanp state close-wait

# 输出：Recv-Q Send-Q Local Address:Port  Peer Address:Port  Process
#            1      0    10.0.1.15:8080     10.0.2.30:51234   users:(("python3",pid=2841,fd=17))

# 2. 按进程聚合，找出泄漏最严重的那个
ss -tanp state close-wait | grep -oP 'pid=\K\d+' | sort | uniq -c | sort -rn

# 3. 看这个进程的 fd 使用情况，判断离上限还有多远
ls /proc/2841/fd | wc -l
cat /proc/2841/limits | grep 'open files'

# 4. 看具体是哪些 fd 是 socket
ls -l /proc/2841/fd | grep socket | head
```

拿到 PID 后，配合 `py-spy dump --pid 2841`（Python）或 `jstack 2841`（Java）看线程栈，通常能直接定位到卡住的代码位置。

### 复现一个 CLOSE_WAIT

理解它最快的方式是自己造一个：

```python
# server.py —— 故意不关闭连接
import socket

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", 9999))
srv.listen(5)
print("listening on 9999")

conns = []
while True:
    conn, addr = srv.accept()
    data = conn.recv(1024)
    print(f"收到 {len(data)} 字节，故意不 close()")
    conns.append(conn)          # 只是存起来，永远不关 → CLOSE_WAIT 泄漏
```

```python
# client.py —— 发完就关，制造 FIN
import socket

for i in range(20):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("127.0.0.1", 9999))
    s.sendall(b"hello")
    s.close()                   # 客户端主动关 → 客户端进 TIME_WAIT，服务端进 CLOSE_WAIT
print("客户端已全部关闭")
```

```bash
# 运行后观察
ss -tan | grep -E '9999' | awk '{print $1}' | sort | uniq -c
#   20 CLOSE-WAIT     ← 服务端侧，永远不会消失
#   20 TIME-WAIT      ← 客户端侧，60 秒后自动清零
```

把 server.py 里改成 `conn.close()`，CLOSE_WAIT 立刻归零。这个对比实验比任何文字解释都直观。

### 正确的关闭写法

```python
import socket
from contextlib import closing

# 方式一：with 语句（socket 对象支持上下文管理器）
with socket.create_connection(("127.0.0.1", 9999), timeout=5) as s:
    s.sendall(b"hello")
    data = s.recv(1024)
# 离开 with 自动 close，即使中间抛异常

# 方式二：try/finally
s = socket.create_connection(("127.0.0.1", 9999), timeout=5)
try:
    s.sendall(b"hello")
finally:
    s.close()

# requests 用 Session 时也要记得关
import requests
with requests.Session() as sess:
    sess.get("https://api.example.com/orders")
```

### TIME_WAIT 的调参

```bash
# 1. 扩大本地端口范围（默认 32768-60999，约 2.8 万个）
sysctl -w net.ipv4.ip_local_port_range="1024 65535"

# 2. 允许 TIME_WAIT 状态的端口被新的【出向】连接复用
#    原理：靠 TCP 时间戳判断旧报文，安全，推荐开启
sysctl -w net.ipv4.tcp_tw_reuse=1

# 3. 增大 TIME_WAIT 的最大数量，超过后内核直接清理并打日志
sysctl -w net.ipv4.tcp_max_tw_buckets=262144

# 持久化写入 /etc/sysctl.conf 后 sysctl -p 生效
```

**特别警告**：`net.ipv4.tcp_tw_recycle` 千万不要开。它会导致 NAT 环境下的客户端随机连接失败（因为它按源 IP 判断时间戳递增，而 NAT 后面多个客户端的时间戳互不相关）。这个参数在 Linux 4.12 之后已被彻底移除，网上很多老教程还在推荐它，属于有害建议。

### 从根上解决：改用长连接

调参只是缓解，真正的解法是**减少连接的创建与销毁**。

```python
# 反例：每次请求新建连接，每次都产生一个 TIME_WAIT
import requests
for i in range(10000):
    requests.get("https://api.example.com/health")

# 正解：用 Session 复用底层 TCP 连接
import requests
from requests.adapters import HTTPAdapter

session = requests.Session()
adapter = HTTPAdapter(pool_connections=20, pool_maxsize=100)
session.mount("https://", adapter)
session.mount("http://", adapter)

for i in range(10000):
    session.get("https://api.example.com/health")   # 复用同一批连接
session.close()
```

Nginx 作为反向代理时，默认对上游是短连接（每次请求后主动关闭），这是很多网关机器 TIME_WAIT 高达十几万的元凶：

```text
upstream backend {
    server 10.0.2.30:8080;
    server 10.0.2.31:8080;
    keepalive 64;              # 每个 worker 保持 64 条到上游的长连接
}

server {
    location / {
        proxy_pass http://backend;
        proxy_http_version 1.1;        # 必须，默认 1.0 不支持长连接
        proxy_set_header Connection "";# 必须，清掉默认的 Connection: close
    }
}
```

## 踩坑

1. **看到几万个 TIME_WAIT 就慌，急着改内核参数**。先算账：默认端口范围约 2.8 万个，TIME_WAIT 持续 60 秒，意味着每秒新建连接数超过 `28000 / 60 ≈ 466` 才会开始耗尽端口。压测机上 3 万 TIME_WAIT 是完全正常的现象。**判断标准不是数量，而是有没有出现 `Cannot assign requested address`（EADDRNOTAVAIL）错误**。

2. **误开 `tcp_tw_recycle` 导致线上间歇性连接失败**。现象极其诡异：同一个接口，有的用户能访问、有的不能，重试有时又好了。根因是客户端在 NAT 之后，内核按源 IP 记录最后一次的时间戳，来自同一 NAT 出口但时钟不同的客户端，SYN 会被直接丢弃。切记：**只开 `tw_reuse`，永不开 `tw_recycle`**。

3. **把 CLOSE_WAIT 当成 TIME_WAIT 来调参**。见过团队对着一堆 CLOSE_WAIT 疯狂调 `tcp_tw_reuse`、`tcp_fin_timeout`，毫无效果——因为 CLOSE_WAIT 根本不受这些参数控制，它只等应用调 `close()`。**只要看到 CLOSE_WAIT 持续增长，直接去看代码，不要在系统参数上浪费时间。**

4. **`tcp_fin_timeout` 控制的不是 TIME_WAIT**。这是个高频误解。该参数控制的是 **FIN_WAIT_2** 状态的超时时间（等对方发 FIN 的时间），TIME_WAIT 的 60 秒是硬编码的，改不了。

5. **压测客户端自己成了瓶颈**。单台压测机受本地端口数限制，短连接场景下最多约 466 QPS（如上计算）。压不上去时先检查压测机自己有没有报 EADDRNOTAVAIL，别急着说服务端不行。解决办法：开长连接、加压测机、给压测机配多个 IP。

6. **容器里看到的连接数不对**。容器有独立的 network namespace，宿主机上 `ss -tan` 看不到容器内的连接。要进容器内看，或者用 `nsenter -t <pid> -n ss -tan`。同理，容器内改 sysctl 需要 `--sysctl` 参数或特权模式。

7. **Docker 默认 fd 上限较低导致 CLOSE_WAIT 更快致命**。CLOSE_WAIT 占用 fd，容器内 `ulimit -n` 如果只有 1024，泄漏一千多个连接服务就彻底挂了，报 `Too many open files`。上线前应确认 fd 上限，并对 fd 数量做监控告警。

## 面试怎么答

**Q：服务器上出现大量 TIME_WAIT，是什么原因，怎么处理？**

A（30 秒骨架）：TIME_WAIT 出现在**主动关闭连接的一方**，是协议要求的正常状态，需要等 2MSL（Linux 上 60 秒）才能释放，目的是保证最后一个 ACK 可靠到达、以及让旧连接的残留报文在网络中消亡。大量出现说明这台机器在高频地主动关闭连接——最常见的是短连接压测，或者 Nginx 反向代理没开 upstream keepalive。危害是占用本地端口，极端情况下端口耗尽报 `Cannot assign requested address`。处理上分两步：治标是扩大 `ip_local_port_range`、开启 `tcp_tw_reuse`；治本是改用长连接复用。要特别注意 `tcp_tw_recycle` 绝对不能开，NAT 环境下会造成随机连接失败，新内核已经把它删了。

**Q：CLOSE_WAIT 大量堆积说明什么？**

A：说明**应用代码有 bug，没有正确关闭连接**。被动关闭方收到对端 FIN 后，内核自动回 ACK 并进入 CLOSE_WAIT，之后就一直等应用调用 `close()`——**这个状态没有任何超时机制**，应用不关就永远不释放。它比 TIME_WAIT 危险得多：TIME_WAIT 60 秒自动消失，CLOSE_WAIT 会一直占着 fd，达到 `ulimit -n` 上限后服务无法接受任何新连接，直接雪崩。排查手段是 `ss -tanp state close-wait` 找到进程 PID，再用 `py-spy dump` 或 `jstack` 看线程栈定位到具体代码，重点查异常分支里漏掉的 close 和连接池的归还逻辑。

**Q：为什么 TIME_WAIT 要等 2MSL，等 1MSL 或者不等行不行？**

A：两个理由。第一，如果最后一个 ACK 丢了，对端会重传 FIN，主动方必须还活着才能重发 ACK；一去一回正好需要 2 倍报文最大生存时间。第二，防止「化身连接」——如果立刻用相同四元组建新连接，上一个连接迟到的报文可能落进新连接的窗口被误收，造成数据错乱。所以必须等到旧报文彻底消亡。1MSL 只够覆盖单向，不够。

**Q：TIME_WAIT 和 CLOSE_WAIT 分别在哪一方，怎么快速区分？**

A：主动关闭方（先发 FIN 的）走 FIN_WAIT_1 → FIN_WAIT_2 → TIME_WAIT；被动关闭方（后发 FIN 的）走 CLOSE_WAIT → LAST_ACK → CLOSED。我记的口诀是「**主动方 TIME_WAIT 等 2MSL，被动方 CLOSE_WAIT 等程序员**」。所以看到 TIME_WAIT 多，说明这台机器在主动关连接，多半是正常的；看到 CLOSE_WAIT 多，说明本机的代码没关连接，一定要改代码。

**Q：如果让你设计一个监控告警，你会怎么定阈值？**

A：TIME_WAIT 我不会直接对数量告警，而是监控**本地端口使用率**（TIME_WAIT + ESTABLISHED 数量 / 端口范围大小），超过 70% 告警；同时对应用日志里的 `Cannot assign requested address` 做关键字告警。CLOSE_WAIT 则要对**趋势**告警——不是看绝对值，而是看它是否持续单调增长（比如 10 分钟内只增不减），因为正常业务下它应该是快速出现又快速消失的瞬时状态。另外一定要配 fd 使用率告警，这是 CLOSE_WAIT 泄漏最终的致命点。

## 参考

- [RFC 9293 - TCP 状态机](https://datatracker.ietf.org/doc/html/rfc9293#section-3.3.2)
- [Linux ip-sysctl 参数文档](https://www.kernel.org/doc/Documentation/networking/ip-sysctl.txt)
- 相关笔记：[[TCP 三次握手与四次挥手]]、[[TCP 可靠传输与滑动窗口]]、[[HTTP 长连接与 HTTP-2 多路复用]]、[[正向代理与反向代理]]
