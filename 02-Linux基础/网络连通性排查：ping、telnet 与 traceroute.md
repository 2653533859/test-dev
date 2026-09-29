---
created: 2026-07-31
tags: [Linux基础/网络]
---

# 网络连通性排查：ping、telnet 与 traceroute

> 「网络不通」是个太笼统的说法。按 IP 可达 → 端口可达 → 路径可达 → DNS 正确的顺序拆开，才能定位到具体是哪一层的问题。

## 概念

### 四个层次，四种工具

| 层次 | 问题 | 工具 |
|------|------|------|
| IP 可达（网络层） | 主机之间能不能通 | `ping`（ICMP） |
| 端口可达（传输层） | 目标端口能不能建立 TCP 连接 | `telnet` / `nc` / `curl` |
| 路径与丢包 | 卡在中间哪一跳 | `traceroute` / `mtr` |
| 名字解析 | 域名解析到了哪个 IP | `dig` / `nslookup` / `host` |

**关键认知：`ping` 通不代表服务可用，`ping` 不通也不代表网络不通。**

- ping 走的是 ICMP 协议，和 TCP 完全是两回事。ICMP 通了只说明 IP 层可达，端口有没有监听、防火墙放没放行 TCP，它一概不知道。
- 反过来，很多云主机和生产环境**默认禁 ICMP**（安全策略），此时 ping 不通但 TCP 服务完全正常。

所以排查连通性，**永远以 TCP 层的探测（telnet/nc/curl）为准**，ping 只作参考。

### traceroute 的原理

traceroute 利用 IP 头里的 **TTL** 字段：先发一个 TTL=1 的包，第一跳路由器把 TTL 减到 0，丢弃并回一个 ICMP Time Exceeded，于是知道了第一跳是谁；再发 TTL=2 探到第二跳……依次递增直到到达目标。

Linux 版 traceroute 默认发 **UDP** 包（高端口），Windows 的 `tracert` 用 ICMP。很多防火墙只放行特定协议，所以：

```bash
traceroute -T -p 443 api.example.com    # 用 TCP 探测，最贴近真实业务流量
```

**`* * *` 不一定代表不通**：很多路由器配置为不回 ICMP Time Exceeded，只是「不吭声」地转发。只要最后一跳能到，中间有星号是正常的。

## 用法

### ping：IP 层可达性与延迟

```bash
ping baidu.com                 # 持续，Ctrl+C 停止并看统计
ping -c 4 10.0.0.5             # 只发 4 个包（脚本里必须限制次数）
ping -i 0.2 -c 20 10.0.0.5     # 间隔 0.2 秒，快速探测抖动
ping -s 1400 10.0.0.5          # 指定包大小，探测 MTU 问题
ping -M do -s 1472 10.0.0.5    # 禁止分片，用来定位 MTU 黑洞
ping -W 2 -c 1 10.0.0.5        # 超时 2 秒
```

输出怎么读：

```text
64 bytes from 10.0.0.5: icmp_seq=1 ttl=64 time=0.35 ms
--- 10.0.0.5 ping statistics ---
100 packets transmitted, 98 received, 2% packet loss, time 99150ms
rtt min/avg/max/mdev = 0.28/0.41/12.3/0.85 ms
```

- **`time`（RTT）**：同机房应 < 1ms，同城 < 5ms，跨地域 30–50ms，跨国 100ms+。
- **`packet loss`**：任何非 0 的丢包在内网都是异常。
- **`mdev`（抖动）**：远大于 avg 说明网络不稳定，这对性能测试的影响比平均延迟更大。
- **`ttl`**：可以粗略反推经过了几跳（初始值通常是 64/128/255，看减了多少）。

### telnet / nc：端口层可达性

```bash
telnet 10.0.0.5 3306
# 成功：Connected to 10.0.0.5.（退出：Ctrl+] 然后输入 quit）
# 失败：Connection refused / Connection timed out

nc -zv 10.0.0.5 3306           # -z 只探测不发数据，-v 显示结果（推荐）
nc -zv 10.0.0.5 20-100         # 扫一段端口
nc -zvu 10.0.0.5 53            # UDP 探测（结果不可靠，UDP 无连接）
nc -w 3 -zv 10.0.0.5 3306      # 3 秒超时

curl -v telnet://10.0.0.5:3306          # curl 也能干这事
timeout 3 bash -c 'echo > /dev/tcp/10.0.0.5/3306' && echo OK || echo FAIL
```

最后一条是**纯 bash 内建**的探测方式，不需要装任何工具，在精简容器里救命。

**两种失败的含义完全不同**：

| 现象 | 含义 | 排查方向 |
|------|------|----------|
| `Connection refused` | 包到了目标机，但端口没人监听（对方回了 RST） | 服务没启动、端口写错、绑定地址是 127.0.0.1 |
| `Connection timed out` | 包被静默丢弃，没有任何回应 | 防火墙 DROP、云安全组、路由不通、目标机宕机 |
| `No route to host` | 本地路由表里找不到到目标的路径 | 网关配置、网段规划 |

分清这三个，能立刻把排查范围缩小一大半。

### traceroute / mtr：路径与丢包

```bash
traceroute api.example.com               # 默认 UDP
traceroute -I api.example.com            # ICMP 模式
traceroute -T -p 443 api.example.com     # TCP 模式（最贴近业务，推荐）
traceroute -n api.example.com            # 不做反向 DNS，快很多
traceroute -m 15 api.example.com         # 最多 15 跳

mtr api.example.com                      # 交互式，持续探测（traceroute + ping 的合体）
mtr -r -c 100 api.example.com            # 报告模式，发 100 个包后输出统计
mtr -rw -c 100 -T -P 443 api.example.com # TCP 模式报告
```

`mtr` 比 traceroute 有用得多：它持续探测并统计**每一跳的丢包率和延迟分布**，能看出丢包是从哪一跳开始的。

读 mtr 结果的关键原则：**只有「从某一跳开始一直到最后一跳都丢包」才说明那一跳有问题**。如果只有中间某一跳显示丢包、后面的跳反而正常，那是因为该路由器对 ICMP 做了限速（deprioritize），不影响转发，属于误报。

### DNS 解析

```bash
dig api.example.com                      # 完整信息（推荐）
dig +short api.example.com               # 只要 IP
dig @8.8.8.8 api.example.com             # 指定 DNS 服务器查（对比本地 DNS 是否有问题）
dig api.example.com +trace               # 从根域开始追踪整个解析链路
dig -x 10.0.0.5                          # 反向解析
nslookup api.example.com                 # 老工具，输出更简单
host api.example.com
getent hosts api.example.com             # 走系统的 nsswitch，会读 /etc/hosts ← 最贴近程序的实际行为

cat /etc/resolv.conf                     # 系统用的 DNS 服务器
cat /etc/hosts                           # 本地静态解析，优先级高于 DNS
```

**`dig` 和程序实际解析结果可能不同**：`dig` 直接查 DNS 服务器，不读 `/etc/hosts`；而程序走的是 glibc 的 NSS（先 hosts 后 DNS）。所以「dig 出来是 A，程序连的是 B」的时候，去看 `/etc/hosts`。用 `getent hosts` 能复现程序的真实行为。

### 网卡与路由

```bash
ip addr                        # 网卡与 IP（替代 ifconfig）
ip route                       # 路由表（替代 route -n）
ip route get 10.0.0.5          # 查到某 IP 会走哪条路由、从哪个网卡出
ip neigh                       # ARP 表
ethtool eth0                   # 网卡速率与双工模式
ss -s                          # 连接数汇总
```

`ip route get` 在多网卡机器上特别有用——能直接告诉你流量从哪个网卡、用哪个源 IP 发出去。

### 完整排查脚本

```bash
#!/usr/bin/env bash
# 一次性收集连通性证据
TARGET_HOST="api.example.com"
TARGET_PORT=443

echo "===== 1. DNS 解析 ====="
getent hosts "$TARGET_HOST" || echo "解析失败"
dig +short "$TARGET_HOST"

echo "===== 2. ICMP 可达性（仅参考） ====="
ping -c 4 -W 2 "$TARGET_HOST" || echo "ping 不通（可能是禁 ICMP）"

echo "===== 3. TCP 端口可达性（以此为准） ====="
nc -zv -w 3 "$TARGET_HOST" "$TARGET_PORT"

echo "===== 4. 应用层 ====="
curl -s -o /dev/null -w "code=%{http_code} total=%{time_total}s\n" \
     --connect-timeout 5 "https://${TARGET_HOST}/health"

echo "===== 5. 路径 ====="
mtr -rw -c 20 -T -P "$TARGET_PORT" "$TARGET_HOST" 2>/dev/null || traceroute -T -p "$TARGET_PORT" -n "$TARGET_HOST"
```

## 踩坑

1. **ping 不通就断定网络故障**。云主机、生产环境普遍禁 ICMP。以 `nc -zv` 或 `curl` 的 TCP 探测为准。

2. **ping 通就以为服务没问题**。ICMP 到 IP 层就结束了，服务进程死了、端口没监听、应用返回 500，ping 一概显示正常。

3. **`telnet` 连上后退不出来**。Ctrl+] 进入 telnet 命令行，输入 `quit`。（这是很多人不敢用 telnet 的原因。）直接用 `nc -zv` 更省事。

4. **忘了云安全组**。本机 `iptables -L` 干干净净，但流量在虚拟网络层就被丢了，现象是 timeout。排查清单里必须包含控制台的安全组和网络 ACL。

5. **`traceroute` 中间全是 `* * *` 就以为断了**。很多路由器不回 ICMP Time Exceeded。只要最终能到达目标就没问题。用 `-T` 模式通常星号会少很多。

6. **mtr 中间某跳丢包 30% 就报障**。ICMP 限速导致的误报。判断标准是「从某跳开始**到最后一跳持续**丢包」。

7. **`/etc/hosts` 覆盖了 DNS 却忘了**。测试时手动加过一条 hosts，后来环境变了没清理，表现为「dig 结果正确但程序连到了旧 IP」。用 `getent hosts` 复现程序行为。

8. **DNS 缓存导致切换不生效**。nscd / systemd-resolved 会缓存。`systemd-resolve --flush-caches` 或重启 nscd。JVM 还有自己的 DNS 缓存（`networkaddress.cache.ttl`），默认可能永久缓存，切 IP 后必须重启应用。

9. **MTU 问题导致「小包能过大包卡死」**。表现很诡异：ping 通、telnet 通、小请求正常，一传大 body 就 hang。用 `ping -M do -s 1472` 逐步减小找出实际 MTU，常见于 VPN、隧道、容器 overlay 网络。

10. **`nc` 的版本差异**。不同发行版的 nc（BSD 版 / OpenBSD 版 / GNU 版）参数不完全兼容，`-z` 在某些版本上不存在。用 `curl -v telnet://` 或 bash 的 `/dev/tcp` 更通用。

11. **只在自己机器上测**。问题可能出在客户端侧（本地网络、公司代理）。要在多个位置对比测试，才能定位是链路问题还是服务端问题。

## 面试怎么答

**Q：如何判断本机到某台服务器的某个端口是通的？**

A：

```bash
nc -zv -w 3 10.0.0.5 3306
# 或者不装工具的写法
timeout 3 bash -c 'echo > /dev/tcp/10.0.0.5/3306' && echo OK
```

要强调的是**不能用 ping 判断**——ping 走 ICMP，只能说明 IP 层可达，和某个 TCP 端口有没有监听、防火墙有没有放行 TCP 完全是两码事；而且很多环境默认禁 ICMP，ping 不通但服务正常。所以端口连通性必须用 TCP 层的探测：`nc -zv`、`telnet`、`curl -v telnet://`，或者 bash 内建的 `/dev/tcp`。

**Q：`Connection refused` 和 `Connection timed out` 有什么区别？**

A：这是排查方向的分水岭。`Connection refused` 说明 SYN 包**成功到达**了目标主机，但目标端口没有进程监听，内核回了 RST——所以网络是通的，问题在服务侧：服务没启动、端口配错、或者服务只绑了 `127.0.0.1` 导致外部连不上。

`Connection timed out` 说明 SYN 包发出去后**什么回应都没有**，包在中途被静默丢弃了——问题在网络侧：防火墙用 DROP 策略（REJECT 会回 RST 变成 refused）、云安全组没放行、路由不通、或者目标主机宕机。

分清这两个能立刻砍掉一半排查工作：refused 就去查服务和监听地址，timeout 就去查防火墙、安全组和路由。

**Q：`ping` 通但服务连不上，怎么排查？**

A：说明 IP 层没问题，往上层查。第一步在服务器本机 `ss -lntp | grep 端口` 确认端口在监听，并且看**绑定地址**——如果是 `127.0.0.1` 就找到根因了。第二步在服务器本机 `curl 内网IP:端口`，通则说明服务和绑定都没问题，不通则查服务日志。第三步从客户端 `nc -zv`，看是 refused 还是 timeout，按上一题的思路分方向。第四步查两层防火墙：本机的 `iptables`/`firewalld`，以及云平台的安全组——后者最容易漏，因为本机看不到任何痕迹。最后如果跨机房，用 `mtr -T -P 端口` 看中间链路。

**Q：`traceroute` 输出里的星号是什么意思？**

A：星号表示该跳没有在超时时间内返回 ICMP Time Exceeded 报文。绝大多数情况**不是故障**——出于安全和性能考虑，很多路由器配置为不响应或限速响应 ICMP，但仍然正常转发数据包。判断标准是看最后一跳：只要能到达目标，中间的星号可以忽略。

真正说明有问题的是「从某一跳开始，之后所有跳（包括目标）都超时」，那才是链路断在那里。另外 Linux 的 traceroute 默认用 UDP 高端口探测，很容易被防火墙过滤，改用 `traceroute -T -p 443` 走 TCP 会真实得多，因为这和业务流量走的是同一条路径、同一套防火墙规则。持续观测建议用 `mtr`，它能给出每跳的丢包率和延迟分布。

## 参考

- [`ping(8)` man page](https://man7.org/linux/man-pages/man8/ping.8.html)
- [`traceroute(8)` man page](https://man7.org/linux/man-pages/man8/traceroute.8.html)
- [`mtr(8)` man page](https://man7.org/linux/man-pages/man8/mtr.8.html)
- 相关笔记：[[Linux 端口占用排查：netstat、ss 与 lsof]]
- 相关笔记：[[curl 与 wget 命令行调接口]]
- 相关笔记：[[03-计算机网络]]
