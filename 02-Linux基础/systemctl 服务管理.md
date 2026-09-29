---
created: 2026-07-31
tags: [Linux基础/进程与服务]
---

# systemctl 服务管理

> 启停被测服务、查为什么起不来、把自己的测试工具做成开机自启的服务——systemd 是现代 Linux 的服务入口。

![[assets/systemd-lifecycle.svg]]
*图示：systemd unit 的三条生命周期路径（start 解析依赖 → fork ExecStart → active；reload 发 SIGHUP 零中断；stop SIGTERM → SIGKILL 清 cgroup），target 层级与 enable 的关系，以及 enable 与 start 是两件独立的事。*

## 概念

### systemd 是 PID 1，管的是「单元」

传统 SysV init 靠 `/etc/init.d/` 下的 Shell 脚本串行启动服务，慢且难以描述依赖。systemd 把所有可管理的对象抽象成**单元（unit）**，用声明式配置描述依赖，并行启动。

| 单元类型 | 后缀 | 说明 |
|----------|------|------|
| 服务 | `.service` | 最常打交道的，一个后台进程 |
| 挂载 | `.mount` | 文件系统挂载点 |
| 定时器 | `.timer` | cron 的替代品，支持依赖和日志 |
| 套接字 | `.socket` | 按需启动（有连接才拉起服务） |
| 目标 | `.target` | 一组单元的集合，类似「运行级别」 |

配置文件位置的优先级（**从低到高**）：

```text
/usr/lib/systemd/system/   发行版和软件包自带（不要手改，升级会覆盖）
/etc/systemd/system/       管理员自定义（改这里）
/run/systemd/system/       运行时临时
```

想微调官方 unit，用 `systemctl edit nginx` 生成 `/etc/systemd/system/nginx.service.d/override.conf`，只覆盖需要改的字段，比整份复制更好维护。

### systemd 与 nohup 的本质区别

`nohup` 起的进程没人管：挂了不会重启、机器重启不会自动拉起、日志要自己管、资源不受限。systemd 提供的是**进程监管**：

- 崩溃自动重启（`Restart=`）
- 依赖顺序（`After=`、`Requires=`）
- 资源限制（`MemoryMax=`、`CPUQuota=`，底层是 cgroup）
- 统一日志（journald）
- 精确的启停语义（它知道自己拉起的所有子进程，`stop` 能清理干净整棵进程树）

## 用法

### 日常操作

```bash
systemctl start nginx           # 启动
systemctl stop nginx            # 停止
systemctl restart nginx         # 重启（stop + start，有中断）
systemctl reload nginx          # 重载配置（发 SIGHUP，不中断连接，前提是服务支持）
systemctl reload-or-restart nginx   # 支持 reload 就 reload，否则 restart
systemctl status nginx          # 查看状态（最常用，信息最全）
systemctl enable nginx          # 开机自启
systemctl disable nginx         # 取消开机自启
systemctl enable --now nginx    # 开机自启 + 立即启动（一步到位）
systemctl is-active nginx       # 只输出 active/inactive，脚本里用
systemctl is-enabled nginx      # 是否开机自启
systemctl mask nginx            # 彻底屏蔽，连手动 start 都不行（防止被依赖唤起）
systemctl unmask nginx
```

**`enable` 与 `start` 是两件独立的事**：`start` 是现在跑起来，`enable` 是下次开机也跑。改完配置只 `enable` 没 `start` 是新手最常见的困惑。

### 查状态与排障

```bash
systemctl status nginx -l --no-pager     # 完整状态，不分页
systemctl list-units --type=service --state=running     # 所有运行中的服务
systemctl list-unit-files --state=enabled               # 所有开机自启项
systemctl --failed                                       # 所有启动失败的单元
systemctl cat nginx                                      # 查看完整的 unit 文件内容
systemctl show nginx -p Restart -p ExecStart             # 查看解析后的某个属性
systemctl list-dependencies nginx                        # 依赖树
systemd-analyze blame                                    # 开机耗时排行，找拖慢启动的服务
```

`systemctl status` 的输出要会读：

```text
● nginx.service - A high performance web server
     Loaded: loaded (/usr/lib/systemd/system/nginx.service; enabled; ...)
                                                              ↑ 是否开机自启
     Active: active (running) since Fri 2026-07-31 10:20:31 CST; 2h ago
             ↑ active(running) / inactive(dead) / failed / activating
   Main PID: 1234 (nginx)
      Tasks: 5 (limit: 4915)
     Memory: 12.3M
     CGroup: /system.slice/nginx.service
             ├─1234 nginx: master process
             └─1235 nginx: worker process
    ↑ 该服务的整棵进程树，比 ps 更可靠
```

### journalctl：日志在这里

systemd 服务的输出默认进 journald，不再是 `/var/log/xxx.log`。

```bash
journalctl -u nginx                     # 该服务的全部日志
journalctl -u nginx -n 100              # 最后 100 行
journalctl -u nginx -f                  # 实时跟随（等价 tail -f）
journalctl -u nginx --since "10 min ago"
journalctl -u nginx --since today --until "2026-07-31 15:00"
journalctl -u nginx -p err              # 只看 error 及以上级别
journalctl -u nginx -o cat              # 只输出消息正文，去掉时间戳前缀
journalctl -xe                          # 最近的日志 + 解释信息，排查启动失败第一选择
journalctl --disk-usage                 # 日志占了多少磁盘
journalctl --vacuum-time=7d             # 只保留 7 天（磁盘满时的应急手段）
```

**服务起不来的标准排查链路**：

```bash
systemctl status myapp -l      # 1. 看 Active 状态和最后几行日志
journalctl -u myapp -n 50      # 2. 看完整日志
journalctl -xe                 # 3. 看 systemd 自己的解释（权限、路径、依赖问题都在这）
systemctl cat myapp            # 4. 确认配置是不是你以为的那份
```

### 写一个自己的服务

把测试用的 mock server 做成服务：

```ini
# /etc/systemd/system/mock-server.service
[Unit]
Description=测试用 Mock Server
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=tester
Group=tester
WorkingDirectory=/opt/mock-server
Environment="ENV=uat"
EnvironmentFile=-/etc/mock-server/env
ExecStart=/opt/mock-server/venv/bin/python /opt/mock-server/app.py --port 8080
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal
MemoryMax=512M

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload            # 改了 unit 文件必须先 reload！
sudo systemctl enable --now mock-server
systemctl status mock-server
```

关键字段说明：

| 字段 | 说明 |
|------|------|
| `Type=simple` | ExecStart 启动的就是主进程（**不能自己 fork 到后台**） |
| `Type=forking` | 程序会 fork 后父进程退出（传统守护进程），需配 `PIDFile=` |
| `Type=oneshot` | 跑完就退出，常配 `RemainAfterExit=yes` |
| `Restart=on-failure` | 非零退出码才重启；`always` 是无论如何都重启 |
| `RestartSec` | 重启间隔，防止崩溃循环把 CPU 打满 |
| `After=` | 启动**顺序**（不代表依赖） |
| `Requires=` | 强依赖，被依赖者失败则自己也失败 |
| `WantedBy=multi-user.target` | `enable` 时挂到哪个 target 下 |

`ExecStart` **必须是绝对路径**，且不会经过 shell 解析——管道、`&&`、变量展开都不生效。需要 shell 特性时写成 `ExecStart=/bin/bash -c '...'`。

### systemd timer 替代 crontab

```ini
# /etc/systemd/system/report.service
[Unit]
Description=生成每日测试报告

[Service]
Type=oneshot
ExecStart=/opt/tools/daily_report.sh
```

```ini
# /etc/systemd/system/report.timer
[Unit]
Description=每天 02:00 生成报告

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true       # 错过了（比如机器关机）开机后补跑
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

```bash
systemctl enable --now report.timer
systemctl list-timers                  # 看下次触发时间
```

相比 crontab 的优势：有完整日志、能查状态、支持依赖、`Persistent` 能补跑、资源可限制。缺点是配置比一行 cron 啰嗦。对比见 [[crontab 定时任务]]。

## 踩坑

1. **改了 unit 文件不生效**。必须 `systemctl daemon-reload` 让 systemd 重新读取，再 `restart` 服务。这是最高频的坑，没有之一。

2. **`Type=simple` 却让程序自己后台化**。程序 fork 后父进程立刻退出，systemd 以为服务挂了，配合 `Restart=always` 会陷入无限重启。**要么去掉程序的守护化参数（如 `nginx -g 'daemon off;'`、`--foreground`），要么改成 `Type=forking` 并指定 `PIDFile`。**

3. **`ExecStart` 里写了管道 / 通配符 / `$VAR` 不生效**。systemd 不经过 shell。用 `/bin/bash -c "..."` 包一层。

4. **服务读不到环境变量**。systemd 启动的进程环境极其干净，没有你 `.bashrc` 里的任何东西。用 `Environment=` 或 `EnvironmentFile=` 显式声明。验证方法：`cat /proc/<pid>/environ | tr '\0' '\n'`。

5. **相对路径导致 `status=203/EXEC`**。`ExecStart` 必须绝对路径；`203/EXEC` 一般是文件不存在、没有执行权限或缺 shebang。同时用 `WorkingDirectory=` 固定工作目录。

6. **`enable` 了但开机没起来**。检查 `[Install]` 段是否存在、`WantedBy` 是否写对（普通服务用 `multi-user.target`），以及是否依赖网络却没写 `After=network-online.target`。

7. **`Restart=always` 掩盖了真实故障**。服务一直在崩溃重启，`status` 看着是 active。查 `journalctl -u xxx | grep -c "Started"` 或看 `systemctl show xxx -p NRestarts`，重启次数异常就是有问题。也可以配 `StartLimitBurst`/`StartLimitIntervalSec` 让它在频繁失败后停下来。

8. **`systemctl stop` 停不干净**。`Type=forking` 且 PIDFile 不准时，systemd 只杀了它认识的那个 PID。systemd 默认 `KillMode=control-group` 会杀整个 cgroup，但如果被改成 `process` 就会漏。检查 `systemctl status` 里 CGroup 段是否还有残留进程。

9. **journald 日志吃满磁盘**。默认可能占到磁盘的 10%。改 `/etc/systemd/journald.conf` 的 `SystemMaxUse=1G`，应急用 `journalctl --vacuum-size=500M`。

10. **在容器里用 systemctl**。容器的 PID 1 通常不是 systemd，`systemctl` 会报 `Failed to connect to bus`。容器里进程管理交给容器运行时，别用 systemd。

## 面试怎么答

**Q：`systemctl start` 和 `enable` 有什么区别？**

A：`start` 是「现在把它跑起来」，作用于当前运行状态，机器重启后就没了；`enable` 是「注册开机自启」，本质是在 `/etc/systemd/system/xxx.target.wants/` 下建一个指向 unit 文件的符号链接，只影响下次开机、不影响当前。两者正交，所以部署时通常用 `systemctl enable --now xxx` 一次做完。对应地，`disable` 只取消自启不停止当前进程，要彻底停就 `disable --now`，或者用 `mask` 连手动启动都禁掉。

**Q：一个服务启动失败，你怎么排查？**

A：四步。第一步 `systemctl status xxx -l`，看 Active 是 `failed` 还是 `activating`，看退出码——`203/EXEC` 是可执行文件找不到或没权限，`217/USER` 是配的用户不存在，`1` 通常是程序自身报错。第二步 `journalctl -u xxx -n 100 --no-pager` 看程序的完整输出。第三步 `journalctl -xe` 看 systemd 自己的解释信息，依赖、权限、SELinux 的问题会在这里。第四步 `systemctl cat xxx` 确认真正生效的配置——因为可能有 drop-in override，或者你改了文件却忘了 `daemon-reload`。

常见根因排前三的是：改完 unit 忘了 `daemon-reload`；`Type` 与程序实际行为不匹配（simple 配了自守护的程序）；环境变量缺失，因为 systemd 不会加载用户的 `.bashrc`。

**Q：`systemd` 和 `nohup` 起后台任务有什么区别？**

A：`nohup` 只是让进程忽略 SIGHUP 并重定向输出，起完就不管了——崩了不会拉起、机器重启不会自动运行、日志要自己轮转、资源不受限、也没有可靠的停止方式（只能 `pkill -f` 猜）。systemd 是真正的进程监管：声明式描述依赖和启动顺序、崩溃自动重启并可配退避、通过 cgroup 限制内存和 CPU、日志统一进 journald 可按时间和级别检索、`stop` 时按 cgroup 清理整棵进程树不会有残留。临时跑个脚本用 nohup，任何需要长期运行的东西都应该写成 unit。

**Q：`restart` 和 `reload` 的区别？**

A：`restart` 是停掉再启动，进程 PID 变化，期间服务不可用，所有连接断开。`reload` 是让服务重新加载配置而不重启进程，具体行为由 unit 里的 `ExecReload=` 定义，通常是给主进程发 SIGHUP（Nginx 是 `nginx -s reload`，会优雅地起新 worker、老 worker 处理完存量请求再退出），做到零中断。前提是服务本身支持 reload——不支持时 `systemctl reload` 会直接报错，这时可以用 `reload-or-restart`。改配置优先 reload，改了代码或依赖库才需要 restart。

## 参考

- [systemd.service 官方文档](https://www.freedesktop.org/software/systemd/man/systemd.service.html)
- [systemctl 官方文档](https://www.freedesktop.org/software/systemd/man/systemctl.html)
- 相关笔记：[[nohup 与后台任务管理]]
- 相关笔记：[[crontab 定时任务]]
- 相关笔记：[[Linux 进程管理：ps、top 与 kill]]
