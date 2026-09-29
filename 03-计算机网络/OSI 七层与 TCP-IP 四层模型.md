---
created: 2026-07-31
tags: [计算机网络/分层模型]
---

# OSI 七层与 TCP/IP 四层模型

> 分层不是为了背诵，而是为了在故障发生时能快速回答一个问题：**这次的问题出在哪一层？**

![[assets/network-layers.svg]]
*图示：OSI 七层与 TCP/IP 四层的对应关系、各层典型协议与数据单位，以及发送方逐层封装出的报文结构。*

## 概念

### 为什么要分层

设想不分层的世界：浏览器要自己处理网卡驱动、自己算路由、自己重传丢包、自己解析域名。每写一个新应用都要把这套东西重写一遍，换一种物理介质（网线换 Wi-Fi）所有软件都得改。

分层的本质是**依赖倒置 + 接口隔离**：

- 每层只依赖下层提供的**能力抽象**，不关心它怎么实现。TCP 只要求「网际层能把一个包尽力送到某个 IP」，至于中间走光纤还是 4G，它不管。
- 每层只跟对端的**同层**对话（对等实体通信）。HTTP 只跟对面的 HTTP 说话，中间的 TCP/IP 对它是透明的。

这直接决定了排查思路：**从下往上逐层验证，第一个不通的层就是问题所在**。

### 两个模型的关系

OSI 七层是 ISO 定的理论参考模型，工程上从未完整实现；TCP/IP 四层是实际跑在互联网上的模型。面试问「几层」，标准答案是「OSI 七层、TCP/IP 四层，教材上还有个折中的五层模型」。

| OSI 七层 | TCP/IP 四层 | 干什么 | 数据单位 | 典型协议 |
|---------|------------|--------|---------|---------|
| 应用层 | 应用层 | 定义业务语义 | 报文 message | HTTP、DNS、FTP、SSH、SMTP |
| 表示层 | 应用层 | 编码、加密、压缩 | 报文 | TLS（严格说跨会话/表示层） |
| 会话层 | 应用层 | 建立/管理会话 | 报文 | RPC 会话、NetBIOS |
| 传输层 | 传输层 | 端到端、进程到进程 | 段 segment / 数据报 datagram | TCP、UDP |
| 网络层 | 网际层 | 主机到主机、路由选路 | 包 packet | IP、ICMP、ARP |
| 数据链路层 | 网络接口层 | 相邻节点、MAC 寻址、差错校验 | 帧 frame | Ethernet、PPP |
| 物理层 | 网络接口层 | 比特流、电气信号 | 比特 bit | 网线、光纤、无线电 |

### 三个「地址」层层递进

初学者最容易混的是 MAC、IP、端口的分工，这三者恰好对应三层：

```text
MAC 地址（链路层）  → 定位「同一个局域网内的哪台设备」，出了网关就换掉
IP  地址（网际层）  → 定位「全网哪台主机」，端到端不变（NAT 除外）
端口号（传输层）    → 定位「这台主机上的哪个进程」
```

所以一次通信真正的五元组是：`(源 IP, 源端口, 目的 IP, 目的端口, 协议)`。这也是 `ss -tanp` 和防火墙规则的基本单位。

### 封装与解封装

发送方从上往下每层加一个头，接收方从下往上每层剥一个头：

```text
HTTP 报文
→ + TCP 头(20B, 含端口/序号)      = TCP 段
→ + IP 头(20B, 含源目的 IP)        = IP 包
→ + 以太网头(14B) + 尾(4B CRC)     = 以太网帧
→ 变成比特流上线
```

一个常被追问的数字：以太网 MTU 默认 1500 字节，减去 IP 头 20 + TCP 头 20，TCP 的 **MSS 通常是 1460**。超过就要分片，而分片会显著降低传输效率与可靠性——这是很多「大包丢包、小包正常」故障的根因。

## 用法

### 用命令逐层验证

这是**分层模型在测试工作中唯一的正确用法**：把「接口访问不通」这种模糊描述，拆成可以逐层证伪的步骤。

```bash
# 第 1-2 层：网卡起来了吗、有没有 IP、ARP 能不能解析到网关
ip link show                      # state UP 说明物理/链路层正常
ip addr show
ip neigh                          # 查看 ARP 表，网关是否 REACHABLE

# 第 3 层：能不能路由到对端主机（注意很多云主机默认禁 ICMP，ping 不通不代表网络不通）
ping -c 4 api.example.com
traceroute api.example.com        # 看在第几跳断掉，判断是本地/机房/骨干网问题
ip route get 10.0.1.20            # 查这个目的地会走哪条路由、哪张网卡

# 第 4 层：目标端口有没有在监听、能不能建连
nc -zv api.example.com 443        # succeeded = TCP 三次握手成功
ss -tanp | grep :8080             # 本机侧：LISTEN 说明服务确实起了

# 第 5-7 层：应用层协议本身
curl -v https://api.example.com/health
dig api.example.com               # DNS 属应用层
openssl s_client -connect api.example.com:443 -servername api.example.com
```

### 一条命令看清全部分层耗时

`curl -w` 是接口测试里性价比最高的分层定位工具，它把一次请求的耗时按层拆开：

```bash
curl -o /dev/null -s -w "\
DNS解析:      %{time_namelookup}s\n\
TCP建连:      %{time_connect}s\n\
TLS握手完成:  %{time_appconnect}s\n\
首字节到达:   %{time_starttransfer}s\n\
总耗时:       %{time_total}s\n" \
https://api.example.com/v1/orders
```

读法（都是**累计**时间，要相减才是各阶段耗时）：

- `time_namelookup` 大 → DNS 有问题（第 7 层的 DNS 服务慢，或递归查询链路长）
- `time_connect - time_namelookup` 大 → TCP 握手慢（第 4 层，通常是网络 RTT 高或服务端 backlog 满）
- `time_appconnect - time_connect` 大 → TLS 握手慢（证书链长、OCSP 校验卡住）
- `time_starttransfer - time_appconnect` 大 → **服务端处理慢**，跟网络无关，去查应用日志和慢 SQL
- `time_total - time_starttransfer` 大 → 响应体传输慢，包太大或带宽不足

### 用 tcpdump 看到分层的真实样子

```bash
# 抓一个包，-e 显示链路层头，-n 不做反解析
sudo tcpdump -i eth0 -nne -c 1 'tcp port 443'
```

输出大致长这样，正好对应三层头：

```text
14:22:01.123456 00:16:3e:0a:1b:2c > 00:16:3e:ff:ee:dd, ethertype IPv4 (0x0800), length 74:
    10.0.1.15.51234 > 10.0.2.30.443: Flags [S], seq 1234567890, win 64240,
    options [mss 1460,sackOK,TS val 1 ecr 0,nop,wscale 7], length 0
         ↑链路层 MAC      ↑网际层 IP        ↑传输层端口+标志位
```

## 踩坑

1. **ping 不通就下结论「网络不通」**。ICMP 属网际层，且云厂商安全组默认常常屏蔽 ICMP。正确做法是用 `nc -zv host port` 验证第 4 层，`ping` 只能作为参考。反过来，**ping 通也不代表端口通**——见过太多「ping 得通所以肯定是代码问题」的误判，结果是安全组没放行端口。

2. **`telnet host port` 通了就以为服务正常**。telnet 只验证到传输层握手成功，说明有进程在监听。应用层可能完全是坏的（比如 Java 进程起来了但 Spring 上下文加载失败，所有请求返回 500）。必须用 `curl` 验证到应用层。

3. **MTU 不一致导致的诡异故障**。现象极具迷惑性：小请求全正常，一上传大文件就卡死。原因是路径上某台设备 MTU 更小（VPN、隧道、Docker overlay 网络常见 1450），大包需要分片但 IP 头设置了 DF（Don't Fragment），中间设备丢包又因为 ICMP 被防火墙屏蔽而无法回告——即 **PMTUD 黑洞**。验证方法：

   ```bash
   # -M do 禁止分片，-s 指定负载大小（总包大小 = 负载 + 28 字节头）
   ping -c 2 -M do -s 1472 api.example.com   # 1472+28=1500，通过说明 MTU >= 1500
   ping -c 2 -M do -s 1422 api.example.com   # 若这个通、上面那个不通，说明 MTU 约 1450
   ```

4. **把 TLS 简单归到某一层争论不休**。TLS 工作在传输层之上、应用层之下，OSI 里勉强对应表示层/会话层，TCP/IP 模型里通常直接算应用层。面试里不要纠缠，说清楚「在 TCP 之上、HTTP 之下」即可。

5. **忽略了 NAT 让 IP 不再「端到端不变」**。经过 NAT 网关后源 IP 被改写，所以服务端 `remote_addr` 拿到的是网关 IP。要拿真实客户端 IP 得看 `X-Forwarded-For`（应用层的补救措施），而这个头是可以被伪造的——安全测试的经典切入点。

6. **抓包抓错了网卡**。容器场景下流量走的是 `docker0`/`veth` 而不是 `eth0`；本机自测走 `lo`。抓不到包先用 `tcpdump -D` 列出所有接口，或者直接 `-i any`。

## 面试怎么答

**Q：讲一下 OSI 七层模型。**

A（30 秒骨架）：OSI 是 ISO 定的理论参考模型，自下而上是物理、数据链路、网络、传输、会话、表示、应用七层。实际互联网跑的是 TCP/IP 四层：网络接口层、网际层、传输层、应用层，相当于把 OSI 的 1-2 层合并成网络接口层、5-7 层合并成应用层。分层的价值是每层只依赖下层的抽象能力，可以独立演进——比如从 HTTP/1.1 升到 HTTP/2 不需要改动 TCP。

**追问：分层对你的测试工作有什么实际意义？**

A：它给了我一套**结构化的排查顺序**。接口调不通时我不会一上来就看代码，而是从下往上：先 `ip addr`/`ip route` 确认网络配置，再 `ping`/`traceroute` 看第 3 层可达性，再 `nc -zv` 验证第 4 层端口，最后 `curl -v` 看应用层。日常我还会用 `curl -w` 把一次请求的耗时按 DNS / TCP / TLS / 首字节拆开——如果 `time_starttransfer` 减 `time_appconnect` 很大，那就是服务端处理慢，可以直接把问题甩给后端而不是继续查网络。

**Q：MAC 地址和 IP 地址为什么要同时存在，只用一个不行吗？**

A：分工不同。MAC 是设备出厂固化的物理标识，**扁平无层级**，没法用来做路由聚合——全球几百亿设备，路由器不可能维护一张全量 MAC 表。IP 是分层的逻辑地址，可以按网段聚合，路由表才能压缩到可管理的规模。所以 IP 负责跨网段的端到端寻址，MAC 负责同一网段内相邻节点的投递，每经过一个路由器 MAC 头都会被重写，IP 头基本不变。

**Q：一个数据包从你的电脑发出去，到服务器收到，经历了什么？**

A：应用层生成 HTTP 报文 → 传输层加 TCP 头（源目的端口、序号），拆成不超过 MSS 的段 → 网际层加 IP 头（源目的 IP），查路由表决定下一跳 → 链路层通过 ARP 拿到下一跳的 MAC，封成以太网帧 → 物理层变成电信号发出。中间每经过一个路由器，会剥到网际层看 IP 决定转发方向，然后重新封装链路层头（MAC 换成下一跳的）。到达服务端后逐层剥头，最终把 HTTP 报文交给监听对应端口的进程。

**Q：MSS 和 MTU 是什么关系？**

A：MTU 是链路层一帧能承载的最大载荷，以太网默认 1500 字节；MSS 是 TCP 段里数据部分的最大长度，等于 MTU 减去 IP 头和 TCP 头，通常是 1460。MSS 在三次握手时由双方通过 TCP 选项协商，取较小值。实际工程中最容易踩的是 VPN、隧道、容器 overlay 网络把 MTU 压到 1450 以下，导致大包被丢且 ICMP 又被屏蔽，出现「小请求正常、大请求超时」的黑洞现象。

## 参考

- [RFC 1122 - Requirements for Internet Hosts](https://datatracker.ietf.org/doc/html/rfc1122)
- [MDN - HTTP 概述](https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Overview)
- 相关笔记：[[TCP 三次握手与四次挥手]]、[[UDP 与 TCP 的取舍]]、[[从输入 URL 到页面渲染的完整链路]]、[[抓包工具选型：Wireshark、Fiddler、Charles 与 mitmproxy]]
