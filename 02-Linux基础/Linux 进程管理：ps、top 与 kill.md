---
created: 2026-07-31
tags: [Linux基础/进程与服务]
---

# Linux 进程管理：ps、top 与 kill

> 服务卡住、CPU 打满、进程杀不掉——从看清进程状态开始，用对信号，别一上来就 `kill -9`。

![[assets/process-state.svg]]
*图示：进程在 R / S / D / T / Z 之间的迁移路径，以及 kill 各个信号的真实语义——D 状态连 SIGKILL 都不响应，Z 状态要处理的是父进程。*

## 概念

### 进程状态：ps 的 STAT 列到底在说什么

| 状态 | 含义 | 排查意义 |
|------|------|----------|
| `R` | 运行中或在就绪队列 | 大量 R 说明 CPU 是瓶颈 |
| `S` | 可中断睡眠（等网络、等锁、sleep） | **绝大多数进程的常态，不是问题** |
| `D` | 不可中断睡眠（等磁盘/NFS I/O） | 出现即异常：磁盘故障、NFS 挂死；`kill -9` 也杀不掉 |
| `T` | 已停止（Ctrl+Z 或 SIGSTOP） | 被人挂起了，`fg`/`bg` 或 `kill -CONT` 恢复 |
| `Z` | 僵尸（已退出，父进程没回收） | 大量僵尸说明父进程有 bug，没调 `wait()` |

附加标记：`s` 会话首进程、`l` 多线程、`+` 前台进程组、`<` 高优先级、`N` 低优先级。所以 `Ssl+` 读作「可中断睡眠 + 会话首 + 多线程 + 前台」。

**僵尸进程为什么杀不掉**：它已经死了，只剩一条 task_struct 记录退出码，等父进程调 `wait()` 来取。`kill` 一个僵尸没有任何意义。正确做法是找它的父进程（`ps -o ppid= -p <zpid>`）——修 bug，或者重启父进程；父进程一旦退出，僵尸会被 init/systemd 收养并立即回收。僵尸不占内存和 CPU，但**占 PID**，量大时会耗尽 PID 空间导致无法创建新进程。

### 进程与线程在 Linux 里的关系

Linux 内核不严格区分进程和线程，二者都是「任务（task）」，线程只是共享地址空间的任务。所以：

- `ps -ef` 默认只显示进程（线程组主 task），`ps -eLf` 才显示线程（`LWP` 列是线程 ID）。
- `top` 默认按进程聚合，按 `H` 切到线程视图——**排查「Java 进程 CPU 300%，到底哪个线程在烧」必须用线程视图**。

### 信号：kill 传的是消息，不是屠刀

| 信号 | 编号 | 能否捕获 | 语义 |
|------|------|----------|------|
| SIGHUP | 1 | 可 | 终端挂断；很多服务重定义为「重载配置」 |
| SIGINT | 2 | 可 | Ctrl+C |
| SIGQUIT | 3 | 可 | Ctrl+\，会生成 core dump；对 Java 进程是打印线程栈 |
| SIGKILL | 9 | **不可** | 内核直接销毁，进程没有任何清理机会 |
| SIGTERM | 15 | 可 | **默认信号**，礼貌地请你退出 |
| SIGSTOP | 19 | **不可** | 暂停 |
| SIGCONT | 18 | 可 | 恢复 |

`kill -9` 的代价是实打实的：内存缓冲区里没落盘的数据丢失、锁文件 / PID 文件残留导致下次启不来、数据库连接不释放、临时文件不清理。**顺序永远是 `-15` → 等几秒 → 还在就 `-9`。**

## 用法

### ps：进程快照

两套语法并存（UNIX 风格带 `-`，BSD 风格不带），常用的就这几条：

```bash
ps -ef                  # 全部进程，UNIX 风格：UID PID PPID C STIME TTY TIME CMD
ps aux                  # 全部进程，BSD 风格：多了 %CPU %MEM VSZ RSS STAT
ps -ef | grep java      # 找进程（会带出 grep 自己）
pgrep -af java          # 更干净：只列 java 相关的 PID + 完整命令行
ps -eLf | grep java     # 显示线程
ps -p 1234 -o pid,ppid,stat,rss,etime,cmd     # 自定义列
ps --sort=-%mem -eo pid,rss,cmd | head        # 按内存倒序
ps -ef --forest         # 树状显示父子关系（也可用 pstree -p）
ps -o ppid= -p 1234     # 查某进程的父进程 PID
```

`ps aux` 各列的含义里，最容易误读的是内存两列：

- **VSZ**（虚拟内存）：进程申请的地址空间总量，包含没真正用的、共享库、mmap 的文件。**这个数字大不代表占内存多**。
- **RSS**（常驻内存）：真正在物理内存里的部分。**看内存占用要看 RSS**，但多个进程共享的库会被重复计算。

### top / htop：动态监控

```bash
top
top -p 1234             # 只看指定进程
top -H -p 1234          # 看该进程的各个线程（排查 CPU 热点线程）
top -b -n 1 > top.txt   # 批处理模式输出一次，用于脚本采集
```

top 交互键（记住这几个就够）：

```text
P     按 CPU 排序（默认）      M   按内存排序
H     切换线程视图            c   显示完整命令行
1     展开每个 CPU 核心        k   杀进程
x     高亮排序列              q   退出
```

**top 第一行的 load average** 是三个值：过去 1 / 5 / 15 分钟的平均活跃任务数（包含 R 和 **D** 状态）。经验判断：持续大于 CPU 核数说明系统过载；如果 load 很高但 CPU 空闲，多半是**大量 D 状态进程在等 I/O**，方向应该转向磁盘而不是 CPU。

**%CPU 可以超过 100%**：多核环境下 100% 表示一个核跑满，400% 表示占了四个核。

### 定位「CPU 打满的是哪段代码」

这是面试和实战都高频的完整链路：

```bash
# 1. 找出 CPU 最高的进程
top -b -n 1 | head -15
# 假设是 PID 12345（一个 Java 服务）

# 2. 找出该进程里 CPU 最高的线程
top -H -p 12345 -b -n 1 | head -20
# 假设线程 12388 占了 98%

# 3. 线程 ID 转成 16 进制（jstack 里是十六进制的 nid）
printf "%x\n" 12388        # 3064

# 4. 打印线程栈并定位
jstack 12345 | grep -A 30 "nid=0x3064"
```

Python / C 程序则换成 `py-spy dump --pid 12345` 或 `perf top -p 12345`。

### kill / pkill / killall

```bash
kill 1234                 # 默认发 SIGTERM（15）
kill -15 1234             # 同上，显式写出来更清楚
kill -9 1234              # SIGKILL，最后手段
kill -HUP 1234            # 重载配置（Nginx 用 -HUP，reload 更推荐 -USR1/-USR2）
kill -l                   # 列出所有信号

pkill -f "python manage.py runserver"   # 按完整命令行匹配（-f 很关键）
pkill -u jenkins                        # 杀某用户的所有进程
killall nginx                           # 按进程名杀（精确匹配名字，不匹配路径）

# 优雅停止的标准写法
kill -15 "$PID"
for i in {1..10}; do
    kill -0 "$PID" 2>/dev/null || { echo "已退出"; exit 0; }
    sleep 1
done
echo "超时，强制终止"
kill -9 "$PID"
```

`kill -0 PID` 不发送任何信号，只做「这个进程还在不在 / 我有没有权限」的探测，是脚本里做存活检查的标准手段。

### 其他常用

```bash
pstree -p 1234            # 看进程树，找出到底谁 fork 了谁
lsof -p 1234              # 该进程打开的所有文件（含日志、so、socket）
ls -l /proc/1234/cwd      # 进程的工作目录
cat /proc/1234/cmdline | tr '\0' ' '    # 完整启动命令（比 ps 截断的更全）
cat /proc/1234/environ | tr '\0' '\n'   # 进程的环境变量（排查配置没生效必查）
nice -n 10 ./batch.sh     # 以低优先级启动
renice -n 10 -p 1234      # 调整已运行进程的优先级
```

`/proc/<pid>/environ` 在排查「明明 export 了变量，服务却读不到」时是决定性证据——它显示的是进程**启动那一刻**继承到的环境。

## 踩坑

1. **`ps -ef | grep xxx` 把 grep 自己也列出来**。经典解法 `grep [x]xx`（正则不匹配自身），更好的是直接用 `pgrep -af xxx`。

2. **`kill -9` 之后服务起不来**。PID 文件、`.lock` 文件残留，或者端口还在 TIME_WAIT。检查并清理 `/var/run/xxx.pid`，`ss -lntp` 看端口是否释放。这就是不该随手 `-9` 的代价。

3. **D 状态进程 `kill -9` 无效**。不可中断睡眠是内核态在等 I/O 完成，信号根本递不进去。方向应该转向存储：`dmesg -T | tail` 看磁盘报错、`iostat -x 1` 看 `%util` 和 `await`、NFS 挂载点用 `mount` 确认是否 hang。极端情况只能重启。

4. **杀了进程它又自动起来**。上面有守护者：systemd 配了 `Restart=always`、supervisor 在拉、或者 Docker 的 restart policy。正确做法是 `systemctl stop xxx` / `docker stop`，而不是和守护进程赛跑。

5. **`killall java` 把无关服务也杀了**。同一台机器往往跑多个 Java 服务。用 `pkill -f "唯一特征串"`，并且**先用 `pgrep -af` 预演确认命中的是哪些**。

6. **`%CPU` 超过 100% 以为是 bug**。多核下正常，`top` 按 `1` 可以看到每个核的明细。

7. **看 `VSZ` 判断内存泄漏**。VSZ 是虚拟地址空间，Java 进程动辄几个 G 很正常。看 `RSS`，或者更准确地看 `/proc/<pid>/smaps_rollup` 里的 `Pss`（按共享比例分摊）。

8. **load average 高就下结论说 CPU 不够**。Linux 的 load 包含 D 状态（等 I/O）的任务。load 15、CPU 空闲 → 查磁盘 I/O；load 15、`us` 很高 → 才是 CPU 瓶颈。

9. **僵尸进程越来越多**。父进程没有正确 `wait()`。批量找：`ps -ef | awk '$2 ~ /Z/ || /defunct/'`。处理的是父进程不是僵尸本身。

10. **前台跑的压测进程 Ctrl+C 杀不干净**。Ctrl+C 只发给前台**进程组**，它 fork 出的孙进程如果换了进程组就收不到。用 `pkill -f` 或按进程组杀：`kill -TERM -<PGID>`（PID 前加负号表示整个进程组）。

## 面试怎么答

**Q：`kill` 和 `kill -9` 的区别？什么时候不该用 `-9`？**

A：`kill` 默认发 SIGTERM（15），这是一个**可以被捕获**的信号，进程收到后可以执行自己的清理逻辑：把内存缓冲刷盘、关闭数据库连接、删除 PID 文件、向注册中心注销，然后正常退出。`kill -9` 发的是 SIGKILL，**内核不可屏蔽不可捕获**，进程被直接销毁，没有任何清理机会。

所以有状态的服务（数据库、消息队列、正在写文件的应用）绝不能上来就 `-9`，否则可能数据丢失、文件损坏、锁文件残留导致下次启动失败。标准流程是先 `-15`，轮询 `kill -0` 等它退出，超时（比如 30 秒）后再 `-9` 兜底。另外要知道 `-9` 对 D 状态（不可中断睡眠）和 Z 状态（僵尸）都无效——前者信号递不进去，后者进程已经不存在了。

**Q：什么是僵尸进程？怎么处理？**

A：子进程退出后，内核会保留它的一条记录（退出码、资源使用统计），等父进程调用 `wait()`/`waitpid()` 取走，这段时间它就是僵尸（`ps` 里 STAT 为 `Z`，命令行显示 `<defunct>`）。如果父进程一直不回收，僵尸就会堆积。

危害是**占用 PID 表项**，量大时系统无法创建新进程；它不占内存和 CPU。处理办法：`kill` 僵尸本身完全无效，要找到父进程 `ps -o ppid= -p <zpid>`，重启它或修它的代码（正确 `wait`，或把 SIGCHLD 设为 SIG_IGN 让内核自动回收）。父进程一旦退出，孤儿僵尸会被 PID 1 收养并立即清理。容器里特别常见——PID 1 如果是普通应用而不是 init，就不会回收孤儿进程，需要 `docker run --init` 或用 tini。

**Q：一个 Java 服务 CPU 占用 300%，你怎么定位？**

A：分四步。第一步 `top` 找出是哪个进程；第二步 `top -H -p <pid>` 看进程内部各线程的 CPU 占用，找出热点线程 TID；第三步 `printf "%x\n" <tid>` 把线程 ID 转成十六进制，因为 jstack 输出里的 `nid` 是十六进制；第四步 `jstack <pid> | grep -A 30 "nid=0x<hex>"` 拿到该线程的调用栈，就能看到卡在哪个方法。

常见结论有几类：死循环 / 正则回溯、频繁 Full GC（这时线程名是 `GC task thread`，要转去看 `jstat -gcutil`）、序列化或加密的热点计算、锁竞争导致的自旋。如果是 Python 服务就用 `py-spy top --pid`，C/C++ 用 `perf top -p`。

**Q：`ps aux` 里 VSZ 和 RSS 有什么区别？**

A：VSZ 是虚拟内存大小，即进程申请的整个地址空间，包括已映射但从未访问的页、共享库、`mmap` 的文件——这个值经常虚高，Java 一启动就是好几 G。RSS 是常驻集大小，即实际占用的物理内存页，判断内存占用应该看它。但 RSS 也有缺陷：多个进程共享的库页在每个进程里都被完整计一次，把所有进程 RSS 加起来会超过物理内存。更精确的指标是 PSS（按共享进程数分摊），在 `/proc/<pid>/smaps_rollup` 里能看到。

## 参考

- [`ps(1)` man page](https://man7.org/linux/man-pages/man1/ps.1.html)
- [`signal(7)` man page](https://man7.org/linux/man-pages/man7/signal.7.html)
- [`proc(5)` man page](https://man7.org/linux/man-pages/man5/proc.5.html)
- 相关笔记：[[nohup 与后台任务管理]]
- 相关笔记：[[Linux 内存与 CPU 排查：free、vmstat 与 iostat]]
- 相关笔记：[[Linux 端口占用排查：netstat、ss 与 lsof]]
