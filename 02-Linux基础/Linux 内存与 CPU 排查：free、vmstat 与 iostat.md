---
created: 2026-07-31
tags: [Linux基础/资源排查]
---

# Linux 内存与 CPU 排查：free、vmstat 与 iostat

> 压测时 TPS 上不去，到底卡在 CPU、内存、还是磁盘？用四个命令在两分钟内把方向定下来。

## 概念

### free：Linux 的「内存快用完了」通常是假象

```text
              total        used        free      shared  buff/cache   available
Mem:           15Gi       4.2Gi       0.4Gi       0.1Gi        10Gi        10Gi
Swap:         2.0Gi          0B       2.0Gi
```

新手看到 `free` 只剩 0.4G 就慌了，其实要看的是 **`available`**。

- **`buff/cache`** 是内核用空闲内存做的页缓存（缓存磁盘数据）和缓冲区。这部分内存**随时可以被回收**，属于「借用」。Linux 的哲学是「空闲内存就是浪费」，所以它会尽可能把内存拿来当缓存。
- **`available`** 是内核估算出的「新程序真正能拿到多少内存」，= free + 可回收的 cache。**这才是判断内存够不够的唯一指标。**

真正需要警惕的信号是：`available` 持续走低、`Swap` 的 `used` 持续上涨、以及 `dmesg` 里出现 OOM killer。

### CPU 的几个时间维度

`top` 第三行：

```text
%Cpu(s):  25.3 us,  5.1 sy,  0.0 ni, 65.2 id,  4.1 wa,  0.0 hi,  0.3 si,  0.0 st
```

| 字段 | 含义 | 高了说明什么 |
|------|------|--------------|
| `us` | 用户态 | 应用自身在算（业务逻辑、GC、序列化） |
| `sy` | 内核态 | 系统调用频繁：大量小 I/O、频繁创建进程、上下文切换 |
| `ni` | 调整过优先级的用户态进程 | — |
| `id` | 空闲 | — |
| `wa` | **I/O 等待** | CPU 空转等磁盘，瓶颈在存储 |
| `hi`/`si` | 硬/软中断 | 网卡中断压力大（高并发网络场景） |
| `st` | 被虚拟化层偷走 | **云主机被同宿主机的邻居抢了 CPU**，说明宿主超卖 |

`st` 值得单独说：在云上做性能测试时，如果 `st` 持续大于 5%，你测出来的数据是不可信的，需要换机器或找云厂商。

### load average 的正确读法

`load` 是「运行队列长度 + **不可中断睡眠（D 状态）的任务数**」的滑动平均。这个「加上 D 状态」是 Linux 特有的，导致 load 同时反映 CPU 压力和 I/O 压力。

判断方法：

- load 高 + `us`/`sy` 高 → **CPU 瓶颈**
- load 高 + `wa` 高 + CPU 大量 idle → **I/O 瓶颈**
- load 高但 CPU 和磁盘都不忙 → 查 D 状态进程（NFS 挂死、磁盘故障）

阈值参考：持续 `load > CPU 核数` 就算过载。核数用 `nproc` 查。

## 用法

### free：内存

```bash
free -h             # 人类可读
free -m             # MB
free -h -s 2        # 每 2 秒刷新一次
cat /proc/meminfo   # 全部细节
```

按进程看内存占用：

```bash
ps aux --sort=-%mem | head -10
ps -eo pid,rss,comm --sort=-rss | head -10
cat /proc/1234/status | grep -E "VmRSS|VmSwap"
cat /proc/1234/smaps_rollup | grep -E "^(Rss|Pss|Swap)"   # Pss 更准（共享内存按比例分摊）
```

**排查内存泄漏**：定时采集 RSS 画趋势线，只涨不跌就是泄漏。

```bash
while true; do
    echo "$(date '+%F %T') $(ps -o rss= -p 1234)"
    sleep 60
done >> /var/log/rss_trend.log
```

**OOM 排查**：

```bash
dmesg -T | grep -i -E "out of memory|killed process"
journalctl -k | grep -i oom
grep -i oom /var/log/messages
```

内核 OOM killer 会打印被杀进程和当时的内存快照，这是「服务莫名其妙消失了、日志里没有任何异常」的标准答案。可以通过 `/proc/<pid>/oom_score_adj` 调整某个进程被选中的概率（-1000 到 1000，越小越不容易被杀）。

### vmstat：系统级全景，第一个该跑的命令

```bash
vmstat 1 10        # 每秒一次，共 10 次（第一行是开机以来的平均值，忽略它）
vmstat -s          # 内存统计汇总
vmstat -d          # 磁盘统计
```

```text
procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st
 3  0      0 412000  62000 9800000   0    0     0    24  1200 3400 25  5 65  4  0
```

**最该盯的五个字段**：

| 字段 | 含义 | 判断 |
|------|------|------|
| `r` | 运行队列长度 | 持续 > CPU 核数 → CPU 不够 |
| `b` | 阻塞（D 状态）进程数 | 持续 > 0 → I/O 有问题 |
| `si`/`so` | 换入/换出内存 | **持续非 0 → 内存不足，性能已经崩了** |
| `bi`/`bo` | 块设备读/写（块/秒） | 结合 iostat 看 |
| `cs` | 每秒上下文切换 | 突然飙高 → 线程过多或锁竞争严重 |

`si`/`so` 非 0 是红线：一旦开始 swap，磁盘比内存慢几个数量级，响应时间会雪崩。压测时看到 swap 活动，测试结果直接作废。

`cs`（context switch）在性能测试里很有价值：线程池配得过大、锁竞争激烈时，CPU 大量时间浪费在切换上，表现为 `sy` 高、`cs` 高但吞吐反而下降。

### iostat：磁盘

```bash
iostat -x 1            # 扩展统计，每秒一次 ← 主力命令（属于 sysstat 包）
iostat -xm 1           # 单位 MB
```

```text
Device  r/s   w/s   rMB/s  wMB/s  await  r_await  w_await  aqu-sz  %util
vda     2.0   180   0.02   45.2   28.5   1.2      29.1     5.2     98.7
```

| 字段 | 含义 | 判断 |
|------|------|------|
| `r/s` `w/s` | 每秒读写次数（IOPS） | 对比磁盘规格 |
| `await` | 平均 I/O 响应时间（毫秒） | SSD 应 < 1ms，机械盘 < 20ms；**超过就是慢** |
| `aqu-sz` | 平均队列长度 | 持续 > 1 说明在排队 |
| `%util` | 设备繁忙时间百分比 | 接近 100% → **磁盘打满** |

注意 `%util` 在 SSD 和 NVMe 上会失真：它们能并行处理多个请求，`%util` 100% 不代表真的到极限。这时更应该看 `await` 和 `aqu-sz`。

按进程看 I/O：

```bash
iotop -oP              # 只显示有 I/O 的进程（需 root）
pidstat -d 1           # 每个进程的读写速率
cat /proc/1234/io      # 某进程累计读写字节数
```

### mpstat / sar / pidstat：更细的视角

```bash
mpstat -P ALL 1        # 每个 CPU 核心的使用率（发现单核打满的问题）
pidstat -u 1           # 每个进程的 CPU
pidstat -r 1           # 每个进程的内存
pidstat -w 1           # 每个进程的上下文切换次数
sar -u 1 3             # CPU 历史
sar -r -f /var/log/sa/sa31    # 读取历史采样（事后复盘的关键）
```

`sar` 的价值在于**事后复盘**：告警发生在凌晨三点，人没在现场，`sar` 的历史数据（sysstat 默认每 10 分钟采一次）能还原当时的资源水位。压测环境务必装上 sysstat。

### 完整的性能排查流程

```bash
# 0. 先看全局，30 秒定方向
uptime                 # load average 趋势
vmstat 1 5             # r/b/si/so/cs/wa 五个关键字段
free -h                # available 和 swap

# 1. 根据方向深挖
# CPU 高 → 找进程 → 找线程 → 找代码
top -b -n 1 | head -15
top -H -p <pid> -b -n 1 | head
printf "%x\n" <tid> && jstack <pid> | grep -A 30 "nid=0x<hex>"

# 内存高 → 看是谁 + 是否泄漏 + 有没有 OOM
ps aux --sort=-%mem | head
dmesg -T | grep -i "killed process"

# I/O 高 → 看设备 → 看进程
iostat -x 1 5
iotop -oP

# 网络 → 见端口与连通性排查笔记
ss -s
```

## 踩坑

1. **看到 `free` 很小就以为内存不够**。要看 `available`。`buff/cache` 是可回收的页缓存，是好事不是问题。

2. **手动 `echo 3 > /proc/sys/vm/drop_caches` 释放缓存**。这只是把有用的缓存丢掉，之后所有读操作都要重新访问磁盘，性能反而暴跌。除非是为了做基准测试对齐初始状态，生产上不要这么干。

3. **`vmstat 1` 第一行数据不准**。第一行是**系统启动以来的平均值**，没有参考价值，要看第二行开始的采样。同理 `iostat` 也是。

4. **`%util` 100% 就断定磁盘是瓶颈**。SSD/NVMe 支持并行 I/O，`%util` 会虚高。要结合 `await`（响应时间）和 `aqu-sz`（队列长度）综合判断。

5. **load 高就加 CPU**。先分清是 CPU 型还是 I/O 型。`wa` 高、`b` 列非 0 → 加 CPU 一点用没有，要优化磁盘或减少 I/O。

6. **忽略 `st`（steal time）**。云主机上 `st` 高说明宿主机超卖，你的性能测试数据不可信。这个坑很隐蔽，因为所有本机指标看起来都正常。

7. **压测时开着 swap**。一旦 `si`/`so` 非 0，响应时间会失控且不可复现。性能测试环境建议 `swapoff -a`，或至少把 `vm.swappiness` 调到 1。

8. **容器里看到的是宿主机的指标**。`free`、`top`、`vmstat` 读的是 `/proc`，而容器默认共享宿主机的 `/proc`，所以在容器里看到的内存总量是宿主机的。要看容器自己的限额得读 cgroup：

   ```bash
   cat /sys/fs/cgroup/memory.max            # cgroup v2
   cat /sys/fs/cgroup/memory/memory.limit_in_bytes   # v1
   ```

   Java 8u191+ 加 `-XX:+UseContainerSupport` 才会正确识别容器内存限制，否则堆会按宿主机内存算然后被 OOM kill。

9. **没装 sysstat，事后无数据可查**。`iostat`、`mpstat`、`sar`、`pidstat` 都在 `sysstat` 包里。压测环境提前 `yum install sysstat` 并启用采集服务。

10. **只看平均值**。`iostat` 的 `await` 是平均值，掩盖了长尾。性能问题往往体现在 P99 上，需要更细粒度的采样（`blktrace`、`bpftrace`）或者应用侧的埋点。

## 面试怎么答

**Q：服务器 load 很高，你怎么排查？**

A：先分清是 CPU 型还是 I/O 型，因为 Linux 的 load 同时包含运行队列和 D 状态（等 I/O）任务。

跑 `vmstat 1 5` 看几个字段：`r` 列（运行队列）持续大于 CPU 核数说明 CPU 不够；`b` 列非 0、`wa` 高说明在等 I/O；`si`/`so` 非 0 说明内存不足开始 swap，这时候什么都别谈先解决内存。

如果是 CPU 型，`top` 找到进程，`top -H -p pid` 找到线程，转十六进制后用 `jstack` 或 `py-spy` 定位到代码。如果是 I/O 型，`iostat -x 1` 看 `await` 和 `%util` 确认是哪块盘慢，`iotop -oP` 找出是哪个进程在读写。还要留意云主机的 `st`（steal time），高的话说明宿主机超卖，本机怎么优化都没用。

**Q：`free` 里的 `buff/cache` 和 `available` 有什么区别？**

A：`buff/cache` 是内核拿空闲内存做的页缓存和缓冲区，用来加速磁盘访问，这部分在应用需要内存时会被自动回收，所以它「被占用」不等于「不可用」。`available` 是内核估算的「新进程实际能申请到的内存」，约等于 `free` 加上可回收的那部分 cache，减去内核认为必须保留的部分。判断内存是否吃紧只看 `available`，以及 swap 有没有在活动。Linux 的设计哲学是空闲内存就是浪费，所以长期运行的机器 `free` 值很小是完全正常的。

**Q：怎么判断是内存泄漏？**

A：单次快照没有意义，必须看趋势。定时采集目标进程的 RSS（`ps -o rss= -p <pid>` 或 `/proc/<pid>/status` 的 `VmRSS`），画出时间曲线——如果在业务量平稳的情况下 RSS 单调上升、GC 之后也不回落，基本可以判定泄漏。

配合的证据链有：`dmesg -T | grep -i "killed process"` 看是不是已经被 OOM killer 干掉过；Java 应用用 `jstat -gcutil` 看老年代占用是否持续上涨、Full GC 后是否回落，`jmap -histo:live` 对比两次快照找出增长的对象类型；Python 用 `tracemalloc` 或 `objgraph`。另外要排除「假泄漏」——比如缓存设计上就是要占内存、或者 JVM 堆本来就配得大，这些是预期行为。

**Q：`top` 里的 `wa` 高意味着什么？**

A：`wa`（iowait）表示 CPU 处于空闲、但系统中有进程在等待磁盘 I/O 完成的时间占比。它高说明 CPU 有余力，瓶颈在存储侧——可能是磁盘本身慢、IOPS 打满、大量随机小 I/O、或者 RAID 卡电池失效导致写缓存关闭。

下一步是 `iostat -x 1` 看具体设备的 `await`（响应时间）和 `%util`，再用 `iotop -oP` 或 `pidstat -d 1` 找出是哪个进程在制造 I/O。要注意 `wa` 的一个陷阱：它的分母是 CPU 时间，如果同时有 CPU 密集任务把 CPU 占满，`wa` 反而会显示得很低——所以不能只凭 `wa` 低就排除 I/O 问题，还要看 `vmstat` 的 `b` 列。

## 参考

- [`vmstat(8)` man page](https://man7.org/linux/man-pages/man8/vmstat.8.html)
- [`iostat(1)` man page](https://man7.org/linux/man-pages/man1/iostat.1.html)
- [`proc(5)` man page](https://man7.org/linux/man-pages/man5/proc.5.html)
- 相关笔记：[[Linux 进程管理：ps、top 与 kill]]
- 相关笔记：[[Linux 磁盘空间排查：df 与 du]]
