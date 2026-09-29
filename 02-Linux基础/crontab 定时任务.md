---
created: 2026-07-31
tags: [Linux基础/进程与服务]
---

# crontab 定时任务

> 每天定时跑回归、定期清日志、每 5 分钟采集一次监控——以及为什么你的 cron「明明配了却没执行」。

![[assets/cron-schedule.svg]]
*图示：crontab 五字段（分时日月周）解析与「日和周同时非 * 时是或关系」的反直觉语义，crond 每分钟扫描调度的流程，flock 防重叠 + 重定向输出，以及 cron 与 systemd timer 的能力对比。*

## 概念

### cron 的工作方式

`crond` 是一个常驻守护进程，**每分钟**醒来一次，检查所有 crontab 文件，把当前时间匹配上的任务 fork 出来执行。

因为调度精度是分钟级，所以：需要秒级的任务 cron 干不了（要靠脚本内部 `sleep` 循环或改用 systemd timer 的 `OnUnitActiveSec`）；机器关机期间错过的任务**不会补跑**（这点 `anacron` 和 systemd timer 的 `Persistent=true` 可以解决）。

### 配置文件在哪

| 位置 | 说明 |
|------|------|
| `crontab -e`（用户级） | 存在 `/var/spool/cron/<用户名>`，**不要直接编辑这个文件** |
| `/etc/crontab` | 系统级，格式**多一列「执行用户」** |
| `/etc/cron.d/*` | 系统级，推荐放自定义任务，同样多一列用户 |
| `/etc/cron.{hourly,daily,weekly,monthly}/` | 放可执行脚本即可，由 run-parts 调度 |

用户级和系统级的**格式差一列**，这是抄错配置的高发点：

```text
用户级（crontab -e）：  分 时 日 月 周  命令
系统级（/etc/cron.d）： 分 时 日 月 周  用户  命令
```

### 时间字段

```text
*  *  *  *  *  command
│  │  │  │  └── 星期 0-7（0 和 7 都是周日）
│  │  │  └───── 月 1-12
│  │  └──────── 日 1-31
│  └─────────── 时 0-23
└────────────── 分 0-59
```

特殊符号：

```text
*        每一个
,        枚举        如 0,15,30,45
-        范围        如 9-18
/        步长        如 */5 每 5 个单位
@reboot  开机时执行一次
@daily / @midnight   等价 0 0 * * *
@hourly  等价 0 * * * *
```

**「日」和「周」同时指定时是「或」的关系**，不是「与」。`0 0 1 * 1` 表示「每月 1 号 **或** 每周一」都执行，而不是「每月第一个周一」——这是 cron 语义里最反直觉的一条。要实现「每月第一个周一」只能在脚本里再判断一次日期。

## 用法

### 基本操作

```bash
crontab -e            # 编辑当前用户的 crontab（会做语法检查）
crontab -l            # 列出
crontab -r            # 删除全部（危险，和 -e 挨着，容易手滑）
crontab -l > cron.bak # 改之前先备份，养成习惯
crontab -u jenkins -l # 查看别的用户的（需要 root）
```

### 常见时间表达式

```bash
*/5 * * * *      每 5 分钟
0 * * * *        每小时整点
30 2 * * *       每天 02:30
0 9-18 * * 1-5   工作日 9 点到 18 点每小时
0 0 1 * *        每月 1 号零点
0 3 * * 0        每周日 03:00
*/10 9-18 * * *  9 到 18 点之间每 10 分钟
@reboot          开机后执行
```

拿不准就用在线的 crontab 表达式解析器验证，或者：

```bash
# 用 systemd 的工具反推 OnCalendar，间接验证理解是否正确
systemd-analyze calendar "Mon *-*-* 03:00:00"
```

### 测试开发场景的实用配置

```bash
# 每天凌晨 2 点跑冒烟用例，日志按天存
0 2 * * * cd /opt/autotest && /usr/local/bin/python3 -m pytest -m smoke >> /var/log/autotest/smoke_$(date +\%F).log 2>&1

# 每 10 分钟做一次接口健康检查，失败才告警
*/10 * * * * /opt/tools/health_check.sh >> /var/log/health.log 2>&1

# 每天凌晨 3 点清理 7 天前的测试报告
0 3 * * * find /var/log/autotest -name "*.log" -mtime +7 -delete

# 每 5 分钟采集一次资源水位（压测期间留证据）
*/5 * * * * /usr/bin/top -b -n 1 | head -20 >> /var/log/perf/top.log 2>&1

# 每周一早上 8 点重建测试数据
0 8 * * 1 /opt/tools/reset_testdata.sh > /var/log/reset.log 2>&1
```

**注意 `%` 必须转义成 `\%`**。在 crontab 里 `%` 是特殊字符（表示换行，`%` 之后的内容会作为 stdin 传给命令），`date +%F` 会被截断，必须写成 `date +\%F`。这个坑几乎每个人都踩过一次。

### 写一个健壮的 cron 脚本

cron 的执行环境和你的登录 shell **完全不同**，所以脚本要自己把环境立起来：

```bash
#!/usr/bin/env bash
set -euo pipefail

# 1) 显式设置 PATH —— cron 的默认 PATH 只有 /usr/bin:/bin
export PATH=/usr/local/bin:/usr/bin:/bin:$PATH

# 2) 显式指定工作目录，不要依赖 cron 的默认（家目录）
cd /opt/autotest

# 3) 需要的环境变量自己加载
source /etc/profile.d/app_env.sh
export LANG=en_US.UTF-8

# 4) 防止上一轮没跑完就又启动（flock 文件锁）
exec 200>/var/lock/autotest.lock
flock -n 200 || { echo "$(date '+%F %T') 上一轮仍在运行，跳过"; exit 0; }

# 5) 所有输出自带时间戳
echo "$(date '+%F %T') 开始执行"
python3 -m pytest -m smoke
echo "$(date '+%F %T') 执行完成，退出码 $?"
```

`flock` 这段是 cron 脚本的标配：任务执行时间超过调度间隔时（比如 5 分钟一次的任务跑了 8 分钟），会出现多个实例并发，轻则日志错乱，重则数据被重复处理。也可以在 crontab 里直接套：

```bash
*/5 * * * * /usr/bin/flock -n /var/lock/collect.lock /opt/tools/collect.sh
```

### 排查 cron 没执行

```bash
# 1. crond 服务在跑吗
systemctl status crond        # CentOS/RHEL
systemctl status cron         # Debian/Ubuntu

# 2. 任务配对了吗
crontab -l

# 3. 看 cron 自己的日志：有没有触发
grep CRON /var/log/syslog                 # Debian/Ubuntu
tail -f /var/log/cron                     # CentOS/RHEL
journalctl -u crond --since "1 hour ago"  # systemd 系统

# 4. 有触发但没结果 → 一定是脚本自身的问题，看你重定向的日志文件
# 5. 用「最小环境」复现
env -i /bin/bash --noprofile --norc -c '/opt/tools/collect.sh'
```

第 5 步是杀手锏：`env -i` 清空所有环境变量来执行，能立刻复现出「手动跑好好的、cron 里跑就失败」的绝大多数问题。

## 踩坑

1. **PATH 不同导致 `command not found`**。cron 的默认 PATH 通常只有 `/usr/bin:/bin`，`python3`、`docker`、`jmeter` 这些装在 `/usr/local/bin` 或 conda 环境里的命令全都找不到。解法：命令写**绝对路径**（`which python3` 查出来），或在 crontab 顶部写 `PATH=/usr/local/bin:/usr/bin:/bin`，或在脚本里 export。

2. **环境变量全都没有**。cron 不会加载 `.bashrc`、`.bash_profile`、`/etc/profile`。`JAVA_HOME`、`PYTHONPATH`、代理设置、虚拟环境统统失效。要在脚本里显式 `source`。

3. **`%` 没转义**。`date +%F` 在 crontab 里会被拦腰截断，必须写 `date +\%F`。或者干脆把命令封进脚本文件，脚本里不受这个限制。

4. **没有重定向输出，邮件塞满 `/var/spool/mail`**。cron 会把任务的 stdout/stderr 通过本地邮件发给用户，久而久之几个 G。要么 `>> log 2>&1`，要么 `> /dev/null 2>&1`，要么在 crontab 顶部写 `MAILTO=""`。

5. **相对路径找不到文件**。cron 的工作目录是用户家目录，不是脚本所在目录。脚本里先 `cd` 到确定路径。

6. **脚本没有执行权限或缺 shebang**。`chmod +x`，第一行写 `#!/usr/bin/env bash`。或者在 crontab 里显式 `bash /path/to/x.sh`。

7. **任务重叠执行**。执行时间超过调度间隔就会并发。用 `flock -n` 加锁。

8. **时区不对，半夜的任务在中午跑**。crond 用的是系统时区。`timedatectl` 确认，或在 crontab 顶部加 `CRON_TZ=Asia/Shanghai`。容器里尤其常见——镜像默认是 UTC，比北京时间差 8 小时。

9. **`crontab -r` 手滑清空所有任务**。它紧挨着 `-e` 且没有二次确认。改前先 `crontab -l > ~/cron.bak`，或者把任务用文件管理（`/etc/cron.d/`）并纳入版本控制。

10. **`/etc/cron.d/` 里的文件名带点号会被忽略**。`run-parts` 只处理符合 `[a-zA-Z0-9_-]+` 的文件名，`myjob.cron` 这种带 `.` 的会被静默跳过。文件权限也必须是 644 且属主 root，权限不对同样静默失败。

11. **DST（夏令时）跳变导致任务跑两次或不跑**。国内没有夏令时不受影响，跨国项目要留意，凌晨 2–3 点的任务尽量避开。

## 面试怎么答

**Q：写一个「每天凌晨 2 点执行脚本」的 cron 表达式。**

A：`0 2 * * * /opt/tools/backup.sh >> /var/log/backup.log 2>&1`。五个字段依次是分、时、日、月、周，所以 `0 2 * * *` 是每天 02:00。实际写的时候还有三个必须注意的点：脚本用绝对路径；一定要重定向输出，否则 cron 会给本地用户发邮件，长期下来撑满 `/var/spool/mail`；日志重定向要写 `2>&1` 把错误也收进去，否则出问题时日志里什么都看不到。

**Q：cron 任务没执行，怎么排查？**

A：按「有没有触发」分成两半。先看 crond 服务是否运行（`systemctl status crond`）、`crontab -l` 确认任务确实配上了、再查 cron 日志（`/var/log/cron` 或 `journalctl -u crond`）看有没有触发记录。

如果日志里根本没有触发记录，问题在配置：表达式写错、`/etc/cron.d` 下的文件名带点或权限不对被忽略、时区不对（容器默认 UTC 差 8 小时）。

如果有触发记录但没有效果，问题在脚本环境。最常见的三个原因：PATH 不全导致 `command not found`；没有加载环境变量（cron 不读 `.bashrc`，`JAVA_HOME`、虚拟环境都没有）；相对路径失效（cron 的 CWD 是家目录）。定位手法是 `env -i /bin/bash --noprofile --norc -c '脚本路径'`，用干净环境本地复现。

**Q：crontab 和 systemd timer 怎么选？**

A：cron 胜在简单，一行配置搞定，几乎所有 Linux 都有。systemd timer 配置啰嗦（要写 `.service` 和 `.timer` 两个文件），但功能强得多：日志自动进 journald 可按时间和级别检索、`systemctl list-timers` 能看下次触发时间和上次执行结果、`Persistent=true` 能补跑关机期间错过的任务、支持依赖关系和资源限制、`RandomizedDelaySec` 可以打散避免同时惊群。

选择上：临时的、简单的清理任务用 cron；生产环境需要可观测、需要补跑、需要和其他服务有依赖关系的定时任务用 systemd timer。另外要注意 cron 不保证任务不重叠，两者都建议在脚本里加 `flock` 互斥。

**Q：`0 0 1 * 1` 是什么意思？**

A：这是个陷阱题。字面是「日=1，周=周一」，但 cron 里**当「日」和「周」都不是 `*` 时，两者是或的关系**——所以它表示「每月 1 号执行，或者每周一执行」，一个月大概会跑五次，而不是「每月第一个周一」。要实现「每月第一个周一」，只能写成 `0 0 1-7 * 1`（1 到 7 号里的周一）——这个写法依然是「或」，所以还得在脚本开头加一句 `[ "$(date +\%d)" -le 7 ] || exit 0` 之类的判断来兜底。

## 参考

- [`crontab(5)` man page](https://man7.org/linux/man-pages/man5/crontab.5.html)
- [`crontab(1)` man page](https://man7.org/linux/man-pages/man1/crontab.1.html)
- 相关笔记：[[systemctl 服务管理]]
- 相关笔记：[[Shell 脚本基础：变量、参数与退出码]]
