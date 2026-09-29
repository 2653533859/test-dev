---
created: 2026-07-31
tags: [Linux基础/网络]
---

# Linux 端口占用排查：netstat、ss 与 lsof

> 「Address already in use」到底是谁占了端口？接口连不上，是服务没起、绑错地址，还是被防火墙拦了？

![[assets/port-troubleshoot.svg]]
*图示：两条排查链路——A 查端口被谁占用（ss → ps → 处置），B 由内向外收敛「连不上」的原因（本机回环 → 监听地址 → 远端握手），并区分 refused 与 timeout 指向的不同方向。*

## 概念

### ss 为什么取代了 netstat

`netstat` 的实现是**逐行解析 `/proc/net/tcp`**，连接数上万时会慢到不可用，而且它对每个连接都要去 `/proc/<pid>/fd/` 里反查属主进程，复杂度是 O(连接数 × 进程数)。

`ss`（socket statistics）走的是内核的 **netlink 接口**（`sock_diag`），直接从内核拿结构化数据，几万连接也是秒出。现在 `net-tools`（netstat/ifconfig/route）在多数发行版里已经不预装了。

**对照表**：

| 目的 | netstat（旧） | ss（新） |
|------|---------------|----------|
| 所有 TCP 监听 + 进程 | `netstat -lntp` | `ss -lntp` |
| 所有连接 | `netstat -antp` | `ss -antp` |
| UDP | `netstat -lunp` | `ss -lunp` |
| 统计汇总 | `netstat -s` | `ss -s` |
| 路由表 | `netstat -rn` | `ip route` |

参数含义（两者通用）：`-l` listening、`-n` 不做 DNS/服务名解析（**加上会快很多**）、`-t` TCP、`-u` UDP、`-p` 显示进程（**需要 root**）、`-a` 全部。

### 监听地址：0.0.0.0 vs 127.0.0.1

这是「本机 curl 通、别的机器连不上」的头号原因。

| Local Address | 含义 |
|---------------|------|
| `0.0.0.0:8080` | 监听**所有网卡**，外部可访问 |
| `127.0.0.1:8080` | 只监听回环，**只有本机能连** |
| `192.168.1.10:8080` | 只监听这一张网卡 |
| `[::]:8080` | IPv6 的所有地址（通常也覆盖 IPv4） |

很多框架的默认配置是 `127.0.0.1`（出于安全考虑），比如 Flask 的 `app.run()`、Node 的部分脚手架。部署到测试环境要显式改成 `0.0.0.0`。

### TCP 状态与 TIME_WAIT

```text
LISTEN → SYN_SENT/SYN_RECV → ESTABLISHED → FIN_WAIT1/2 → TIME_WAIT → CLOSED
```

- **TIME_WAIT**：主动关闭连接的一方进入，持续 2×MSL（Linux 上固定 60 秒）。目的是确保最后的 ACK 能重传、以及让旧连接的迷途报文自然消亡。**压测机上出现几万个 TIME_WAIT 是正常现象**，因为客户端主动关闭了大量短连接。
- **CLOSE_WAIT**：被动关闭方收到 FIN 后进入，等应用调用 `close()`。**大量 CLOSE_WAIT 堆积是应用 bug**——代码里没有关闭连接（忘了 `close()`、异常路径没走到 finally）。这是面试高频题。

## 用法

### 查端口被谁占用

```bash
ss -lntp                        # 所有 TCP 监听端口 + 进程（最常用）
ss -lntp | grep :8080           # 定位具体端口
ss -lntp 'sport = :8080'        # 用过滤表达式（更精确，不会误匹配 18080）
lsof -i :8080                   # 另一个角度：看谁打开了这个端口
lsof -i :8080 -sTCP:LISTEN      # 只看监听
fuser -n tcp 8080               # 只输出 PID，脚本里方便
fuser -k -n tcp 8080            # 直接杀掉占用者（慎用）
netstat -lntp | grep 8080       # 旧系统
```

拿到 PID 之后：

```bash
ps -p 1234 -o pid,ppid,user,etime,cmd     # 是什么进程、跑了多久
ls -l /proc/1234/exe                       # 可执行文件真实路径
ls -l /proc/1234/cwd                       # 工作目录
systemctl status 1234                      # 属于哪个 systemd 服务（能直接反查）
```

`systemctl status <PID>` 是个冷门但极好用的技巧——直接告诉你这个进程属于哪个 unit，从而知道该用 `systemctl stop` 而不是 `kill`。

### 查连接状态与分布

```bash
ss -antp                                 # 所有 TCP 连接
ss -tan state established                # 只看已建立
ss -tan state time-wait | wc -l          # 数 TIME_WAIT
ss -s                                    # 汇总统计，一眼看总量
ss -antp 'dport = :3306'                 # 连到 MySQL 的连接
ss -antp 'dst 10.0.0.5'                  # 连到某个 IP 的

# 按状态统计分布（排查连接泄漏的第一条命令）
ss -ant | awk 'NR>1 {print $1}' | sort | uniq -c | sort -rn

# 找出连接数最多的客户端 IP
ss -ant state established | awk 'NR>1 {split($5,a,":"); print a[1]}' | sort | uniq -c | sort -rn | head
```

### lsof：从「文件」角度看网络

`lsof` 的价值在于它把 socket 当文件看，能和进程的其他资源一起排查。

```bash
lsof -i                          # 所有网络连接
lsof -i tcp:8080                 # 指定协议和端口
lsof -i @10.0.0.5                # 与某 IP 的连接
lsof -p 1234                     # 某进程打开的所有文件（含 socket、日志、so）
lsof -u jenkins                  # 某用户打开的
lsof +L1                         # 已删除但仍被持有的文件（磁盘满排查）
lsof /var/log/app.log            # 谁在用这个文件（改日志前必查）
```

### 排查「连不上」的完整链路

```bash
# 第 1 层：服务进程在不在
systemctl status myapp
ps -ef | grep myapp

# 第 2 层：端口有没有监听、绑在哪个地址
ss -lntp | grep 8080
# 看到 127.0.0.1:8080 → 外部必然连不上，改配置绑 0.0.0.0

# 第 3 层：本机能不能通
curl -v http://127.0.0.1:8080/health
curl -v http://<本机内网IP>:8080/health     # 这一步能区分「绑定问题」和「防火墙问题」

# 第 4 层：从客户端机器测
telnet 10.0.0.5 8080
nc -zv 10.0.0.5 8080                        # 更现代，-z 只探测不发数据
curl -v --connect-timeout 5 http://10.0.0.5:8080/health

# 第 5 层：防火墙
sudo iptables -L -n --line-numbers
sudo firewall-cmd --list-all                # CentOS/RHEL
sudo ufw status                             # Ubuntu
# 云主机还要去控制台看安全组规则

# 第 6 层：中间链路
traceroute -T -p 8080 10.0.0.5              # TCP 模式探测路径
mtr 10.0.0.5                                # 持续探测，看丢包在哪一跳
```

**核心判据**：

- `Connection refused` → 包**到达了**目标机，但那个端口没人监听。方向：服务没起、端口写错、绑定地址不对。
- `Connection timed out` → 包**被丢弃了**，没有任何响应。方向：防火墙 DROP、安全组、路由不通、目标机器宕机。

这两个错误指向完全不同的排查方向，分清楚能省一半时间。

### 容器场景

```bash
docker ps                                  # 看端口映射 0.0.0.0:8080->8080/tcp
docker port <container>
docker exec -it <container> ss -lntp       # 容器内部的监听（镜像里可能没有 ss）
nsenter -t $(docker inspect -f '{{.State.Pid}}' <container>) -n ss -lntp   # 从宿主机进容器网络命名空间看
```

容器里最常见的坑：应用绑了 `127.0.0.1`，那是**容器内部的回环**，即使做了端口映射，宿主机也转发不进去。容器内必须绑 `0.0.0.0`。

## 踩坑

1. **`ss -lntp` 看不到 PID**。没加 `sudo`。非 root 只能看到自己的进程。

2. **`grep :8080` 误匹配到 18080、8080x**。用 `ss -lntp 'sport = :8080'` 精确过滤，或 `grep ':8080\b'`。

3. **端口显示被占用却找不到进程**。两种可能：一是 TIME_WAIT 残留的连接（不属于任何存活进程），`ss -tan state time-wait '( sport = :8080 )'` 确认，等 60 秒或让服务加 `SO_REUSEADDR`；二是进程在别的网络命名空间里（容器、netns）。

4. **服务重启报 Address already in use，但确实没进程占用**。老连接处于 TIME_WAIT 且服务没设 `SO_REUSEADDR`。这是服务端代码问题（大多数框架默认已设置）。不要用 `net.ipv4.tcp_tw_recycle` 去「优化」——这个参数在 NAT 环境下会导致丢连接，且已在 4.12 内核移除。

5. **本机 curl 通，别的机器不通**。九成是绑定地址问题（`127.0.0.1` vs `0.0.0.0`），剩下的是防火墙。用「本机 curl 内网 IP」这一步就能把两者区分开。

6. **大量 CLOSE_WAIT**。应用没有关闭连接。查代码里 HTTP client / 数据库连接是否在 finally 或 with 里关闭；连接池配置是否有最大空闲时间。`kill` 进程只是临时缓解。

7. **大量 TIME_WAIT 就以为是故障**。压测机上属于正常。真需要缓解可以开 `net.ipv4.tcp_tw_reuse=1`（客户端侧安全）、扩大 `ip_local_port_range`、或者改用长连接/连接池——这比调内核参数更根本。

8. **`netstat` 在高连接数机器上跑了几分钟没出来**。用 `ss`。

9. **`telnet` 命令不存在**。很多精简镜像不带。用 `nc -zv host port`、`curl -v telnet://host:port`，或者纯 bash 的 `timeout 3 bash -c 'echo > /dev/tcp/host/8080' && echo OK`——最后这个不需要任何额外工具。

10. **只查了本机防火墙，忘了云安全组**。阿里云/腾讯云/AWS 的安全组是在虚拟网络层拦截的，本机 `iptables -L` 里什么都看不到，表现为 timeout。排查清单里必须有这一项。

## 面试怎么答

**Q：怎么查看某个端口被哪个进程占用？写出完整命令。**

A：

```bash
sudo ss -lntp | grep :8080
# 或者
sudo lsof -i :8080 -sTCP:LISTEN
```

`-l` 监听、`-n` 不做名字解析（更快）、`-t` TCP、`-p` 显示进程，必须 sudo 才能看到别人的进程。拿到 PID 后用 `ps -p <pid> -o cmd` 或 `ls -l /proc/<pid>/exe` 确认是什么程序，再用 `systemctl status <pid>` 看它属于哪个服务——如果是 systemd 管的，应该 `systemctl stop` 而不是直接 `kill`，否则会被自动拉起。

补充一点：`ss` 已经取代 `netstat`，因为 netstat 是逐行解析 `/proc/net/tcp`，连接数上万时非常慢，而 ss 走 netlink 接口直接从内核取数据。

**Q：服务启动报 Address already in use，但你发现没有进程占用这个端口，为什么？**

A：大概率是上一次连接还处于 **TIME_WAIT** 状态。主动关闭连接的一方会进入 TIME_WAIT 并持续 2MSL（Linux 上 60 秒），这期间四元组被占用，如果服务没有设置 `SO_REUSEADDR`，重新 bind 同一端口就会失败。确认方法是 `ss -tan state time-wait '( sport = :8080 )'`。解决办法是让服务端在 bind 前设置 `SO_REUSEADDR`（绝大多数框架默认已开），或者等 60 秒。另一种可能是进程在别的网络命名空间里（容器），宿主机 `ss` 看不到，需要 `nsenter` 进它的 netns。

**Q：接口连不上，你怎么排查？**

A：由内向外分层收敛，每一层都能砍掉一半可能性。

第一步在服务器本机 `curl 127.0.0.1:8080`——通，说明服务本身没问题；不通，去查 `systemctl status` 和应用日志。

第二步 `ss -lntp | grep 8080` 看监听地址——如果是 `127.0.0.1` 就找到根因了，外部永远连不上，要改成 `0.0.0.0`。

第三步在本机 `curl 内网IP:8080`——通说明绑定没问题，不通说明本机防火墙就拦了。

第四步从客户端机器 `nc -zv IP 8080`。这一步的报错信息是关键分水岭：`Connection refused` 说明包到了但没人监听，方向在服务侧；`Connection timed out` 说明包被丢了，方向在防火墙、安全组或路由。

第五步查 `iptables`/`firewalld` 和云安全组——安全组特别容易漏，因为它在本机看不到任何痕迹。最后如果跨机房还要 `mtr` 看中间链路丢包。

**Q：大量 CLOSE_WAIT 说明什么问题？**

A：CLOSE_WAIT 是被动关闭方在收到对端 FIN、回了 ACK 之后进入的状态，它在等待**本端应用调用 `close()`**。堆积说明应用拿到了「对方关闭了」的信号却迟迟不关自己这一侧的 socket——本质是应用代码 bug：HTTP 客户端没关、数据库连接没归还、异常路径绕过了 `finally`/`with`、或者线程池阻塞导致回收逻辑跑不到。

危害是每个 CLOSE_WAIT 占一个文件描述符，堆到 `ulimit -n` 上限后会报 `Too many open files`，服务彻底不可用。定位手法是 `ss -ant state close-wait` 看是和哪个对端 IP 的连接堆积，再用 `lsof -p <pid> | grep CLOSE_WAIT` 确认进程，最后去看那段代码的连接生命周期管理。注意它和 TIME_WAIT 完全不同：TIME_WAIT 是主动关闭方的正常状态且会自动消失，CLOSE_WAIT 不会自己消失，只能靠应用修复或重启。

## 参考

- [`ss(8)` man page](https://man7.org/linux/man-pages/man8/ss.8.html)
- [`lsof(8)` man page](https://man7.org/linux/man-pages/man8/lsof.8.html)
- 相关笔记：[[网络连通性排查：ping、telnet 与 traceroute]]
- 相关笔记：[[Linux 进程管理：ps、top 与 kill]]
- 相关笔记：[[03-计算机网络]]
