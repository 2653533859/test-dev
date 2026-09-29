---
created: 2026-07-31
tags: [Linux基础/进程与服务]
---

# nohup 与后台任务管理

> 压测跑到一半 SSH 断了、任务全没了——搞清 `&`、`nohup`、`disown`、`tmux` 各自解决什么问题。

![[assets/job-control.svg]]
*图示：前台 / 停止 / 后台三种作业状态的切换键，以及关闭 SSH 时 SIGHUP 沿「内核 → shell → 作业」的传递链路，和三种让任务活下来的手段。*

## 概念

### 作业控制（job control）：终端、会话与进程组

一次 SSH 登录会创建一个**会话（session）**，会话绑定一个**控制终端**，shell 是会话首进程。你在 shell 里敲的每条命令（或用管道串起来的一串命令）构成一个**作业（job）**，对应一个**进程组**。

- 同一时刻只有一个作业是**前台作业**，它独占终端输入，能收到 Ctrl+C（SIGINT）、Ctrl+Z（SIGTSTP）。
- 其他是**后台作业**，不接收终端输入，但**标准输出仍然连着终端**。

这解释了两个日常现象：后台任务的输出会突然插到你正在输入的命令中间；后台任务如果试图读 stdin，会收到 SIGTTIN 信号被自动停止（`jobs` 里显示 `Stopped (tty input)`）。

### SIGHUP：为什么关掉终端任务就死了

当 SSH 连接断开或终端窗口关闭时，内核给会话首进程（也就是 shell）发 **SIGHUP**（hang up，源自早年调制解调器挂断）。bash 收到后，会把 SIGHUP **转发给它的所有作业**。SIGHUP 的默认动作是终止进程，于是所有后台任务陪葬。

破解方式有三类，对应三种不同的思路：

| 方式 | 原理 | 适合 |
|------|------|------|
| `nohup cmd &` | 启动时把 SIGHUP 设为 IGNORE，并重定向输出 | 一次性长任务 |
| `cmd & disown -h %1` | 把作业从 shell 的作业表里摘掉 / 标记不发 HUP | 已经跑起来了才想起来 |
| `tmux` / `screen` | 任务跑在独立会话里，终端断开不影响 | 需要交互、需要回看输出 |
| `setsid cmd` | 直接新建会话，脱离当前控制终端 | 脚本里启动守护进程 |
| `systemd` 服务 | 交给 init 托管，开机自启 + 自动重启 | 长期运行的服务 |

### nohup 到底做了什么

`nohup cmd` 只做两件事：

1. 把 SIGHUP 的处理设为忽略。
2. **如果 stdout 是终端**，把它重定向到 `./nohup.out`（当前目录不可写则用 `$HOME/nohup.out`）；stderr 若是终端则重定向到 stdout 相同的位置。

注意 `nohup` **不会把任务放到后台**——后台是 `&` 干的事。两者是正交的，通常一起用。

## 用法

### 标准写法

```bash
# 最完整的一行：后台 + 免疫 SIGHUP + 输出落盘 + 断开 stdin
nohup ./run_pressure_test.sh > /var/log/pressure.log 2>&1 < /dev/null &
echo $!                                # 打印刚启动的后台任务 PID
echo $! > /var/run/pressure.pid        # 存下来便于后续停止
```

四个部分缺一不可：

- `nohup`：忽略 SIGHUP。
- `> log 2>&1`：显式重定向，别依赖 `nohup.out`（顺序不能反，见 [[管道与重定向]]）。
- `< /dev/null`：断开 stdin，防止任务读输入时被 SIGTTIN 停掉。
- `&`：放后台。

### jobs / fg / bg：当前终端内的作业管理

```bash
sleep 300 &            # 直接后台启动，输出 [1] 12345（作业号 1，PID 12345）
jobs                   # 列出当前 shell 的所有作业
jobs -l                # 带 PID
fg %1                  # 把作业 1 调到前台
bg %1                  # 让「已停止」的作业 1 在后台继续跑
kill %1                # 按作业号杀（不用查 PID）
wait                   # 等待所有后台作业结束（脚本里做并发控制常用）
wait %1                # 等待指定作业
```

典型场景：命令跑起来才发现会跑很久。

```text
$ ./long_task.sh
^Z                       # Ctrl+Z 挂起，显示 [1]+ Stopped
$ bg %1                  # 让它在后台继续
$ disown -h %1           # 标记为不接收 SIGHUP
$ exit                   # 安全退出，任务继续
```

唯一的遗憾是输出还连着已经关闭的终端，可能报错或丢失——所以**能提前 nohup 就别事后补救**。

### disown 的三个用法

```bash
disown %1        # 从作业表移除，shell 退出时不再管它
disown -h %1     # 保留在作业表但标记「不发送 SIGHUP」
disown -a        # 对所有作业生效
```

### tmux：最推荐的方式

`nohup` 的致命缺陷是**不能回到那个交互界面**。压测、迁移数据、跑长时间构建时，你往往需要中途看进度、按个键。tmux 解决这个问题。

```bash
tmux new -s perf            # 新建名为 perf 的会话
# 在里面正常跑命令，就像本地终端
# Ctrl+B 然后按 D  → detach，任务继续在后台跑

tmux ls                     # 列出所有会话
tmux attach -t perf         # 重新连回去，输出历史都在
tmux kill-session -t perf   # 结束会话
```

常用快捷键（前缀都是 `Ctrl+B`）：

```text
d      detach（离开但不结束）
c      新建窗口          n / p   下一个 / 上一个窗口
%      垂直分屏          "       水平分屏
方向键  切换面板          [       进入滚动模式（q 退出）
```

**判断标准**：跑完就完、只要日志 → `nohup`；需要交互 / 分屏 / 断线重连 → `tmux`；要长期运行的服务 → 写成 systemd unit（见 [[systemctl 服务管理]]）。

### 脚本里的并发控制

```bash
#!/usr/bin/env bash
set -euo pipefail

# 并发在 5 台机器上执行检查，全部完成后汇总
for host in host1 host2 host3 host4 host5; do
    ssh "$host" 'df -h /data' > "/tmp/df_${host}.txt" 2>&1 &
done
wait                                # 等所有后台任务结束
cat /tmp/df_*.txt
```

限制并发数（避免一次起几百个）：

```bash
max_jobs=4
for f in *.log; do
    while [ "$(jobs -rp | wc -l)" -ge "$max_jobs" ]; do sleep 0.2; done
    gzip "$f" &
done
wait
```

更简单的写法是直接用 `xargs -P`：

```bash
ls *.log | xargs -P 4 -I{} gzip {}
```

### 停止后台任务

```bash
# 用之前存的 pid 文件
PID=$(cat /var/run/pressure.pid)
kill -15 "$PID"
sleep 5
kill -0 "$PID" 2>/dev/null && kill -9 "$PID"

# 或者按命令行特征
pgrep -af "run_pressure_test.sh"     # 先确认
pkill -f "run_pressure_test.sh"      # 再杀
```

## 踩坑

1. **只写 `&` 没写 `nohup`，SSH 一断任务就没**。这是最常见的一条。`&` 只负责放后台，不改变 SIGHUP 行为。

2. **`nohup.out` 撑爆磁盘**。默认输出全塞进 `nohup.out`，一个跑几天的任务能写出几十 G。**永远显式重定向**，甚至重定向到 `/dev/null`（如果你确实不要输出）。

3. **重定向顺序写反**。`nohup cmd 2>&1 > log &` 会让错误信息仍打到终端（终端关闭后可能触发写错误）。正确是 `> log 2>&1`。

4. **后台任务变成 Stopped**。任务读了 stdin，收到 SIGTTIN 被停止。加 `< /dev/null` 断开输入。交互式命令（会问 y/n 的）不适合放后台，或者用 `yes | cmd`、`-y` 参数。

5. **`nohup` 之后当前目录被删，任务报错**。进程的 CWD 还指向已删除的目录。脚本里先 `cd` 到一个稳定路径。

6. **`disown` 后仍然被杀**。有些 shell（或 `huponexit` 选项开启时）行为不同；容器 / systemd 环境下退出时会杀掉整个 cgroup 里的进程，`disown` 也救不了。这种场景必须用 systemd 或 `setsid`。

7. **忘了记录 PID，任务停不下来**。启动后立刻 `echo $! > xxx.pid`。注意 `$!` 只在启动后**立刻**取才有效。

8. **`nohup` 的任务输出没有时间戳，事后无法对齐问题**。管道给 `ts`（moreutils）或用 awk 加时间：

   ```bash
   nohup ./task.sh 2>&1 | awk '{print strftime("%F %T"), $0; fflush()}' > task.log &
   ```

9. **在 tmux 里跑，忘了 detach 直接关窗口**。关窗口只是 detach，任务其实还在，`tmux ls` 能看到——很多人误以为丢了又重跑一遍，导致两份任务并发写同一个文件。

10. **用 `nohup` 跑本该是服务的东西**。机器重启后不会自动拉起、挂了也没人管、日志没有轮转。长期运行的东西应该写成 systemd unit。

## 面试怎么答

**Q：`&`、`nohup`、`disown`、`screen/tmux` 有什么区别？**

A：解决的是两个不同问题。`&` 只把作业放到后台，让 shell 立刻返回提示符，它不改变任何信号行为；关闭终端时 shell 会把 SIGHUP 转发给它，任务照样死。

`nohup` 让进程忽略 SIGHUP，并在输出是终端时重定向到 `nohup.out`——它不负责放后台，所以通常写成 `nohup cmd > log 2>&1 &`。

`disown` 是**事后补救**：任务已经用 `&` 跑起来了，`disown -h %1` 把它从 shell 的作业表里摘掉或标记不发 HUP。

`tmux`/`screen` 是另一个思路：任务运行在独立的会话和伪终端里，你的 SSH 只是「附着」上去，断开只是 detach，任务和它的终端都还在，随时可以 attach 回来继续交互、回看输出。需要交互或中途看进度就用 tmux，跑完即走的批处理用 nohup，长期服务则应该交给 systemd。

**Q：`nohup cmd &` 之后为什么还是有输出打到屏幕上？**

A：可能有两种情况。一是 `nohup` 只在 stdout **是终端**时才自动重定向到 `nohup.out`，如果你已经写了 `> log`，stderr 没处理就仍然连着终端；二是重定向顺序写反了 `2>&1 > log`，fd2 复制的是重定向之前的 fd1（终端）。稳妥写法是显式写全：`nohup cmd > log 2>&1 < /dev/null &`。

**Q：后台跑的任务突然变成 Stopped 是怎么回事？**

A：后台作业尝试从终端读取输入时，内核会给它发 SIGTTIN 把它停住（因为终端输入归前台作业独占）；类似地，如果终端设置了 `tostop`，后台作业写输出会收到 SIGTTOU。常见于脚本里有 `read`、有交互式确认、或者调用了会读 stdin 的命令。解决办法是启动时加 `< /dev/null` 断开 stdin，或者给命令加 `-y`/`--yes` 之类的非交互参数。想让它继续跑可以 `fg %1` 到前台把输入喂进去，或者 `kill -CONT`。

**Q：怎么在脚本里并发执行任务并等它们全部完成？**

A：用 `&` 启动多个后台作业，最后用 `wait` 等待全部结束：

```bash
for host in "${hosts[@]}"; do
    ssh "$host" 'uptime' > "/tmp/out_$host" 2>&1 &
done
wait
```

要限制并发数，可以用 `while [ "$(jobs -rp | wc -l)" -ge N ]; do sleep 0.2; done` 做简单节流，或者直接改用 `xargs -P N`，后者更简洁也更不容易写错。要收集每个任务的退出码，就把 PID 存进数组，逐个 `wait "$pid"` 并检查 `$?`。

## 参考

- [Bash Reference Manual - Job Control](https://www.gnu.org/software/bash/manual/html_node/Job-Control.html)
- [`nohup(1)` man page](https://man7.org/linux/man-pages/man1/nohup.1.html)
- 相关笔记：[[Linux 进程管理：ps、top 与 kill]]
- 相关笔记：[[systemctl 服务管理]]
- 相关笔记：[[管道与重定向]]
