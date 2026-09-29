---
created: 2026-07-31
tags: [Linux基础/MOC, MOC]
---

# 02-Linux基础

测试环境部署、日志排查、线上问题定位都在 Linux 上完成。目标是不用查手册就能独立完成一次问题排查。

## 学习目标

- 熟练完成文件、权限、进程、服务的日常操作
- 会用 grep / awk / sed 三件套从大日志里捞出关键信息
- 能写 Shell 脚本把重复操作自动化
- 服务出问题时，能按 CPU / 内存 / 磁盘 / 网络 四个方向定位

## 计划覆盖的知识点

- 文件与目录：`ls` / `cd` / `cp` / `mv` / `rm` / `find` / `ln`，绝对与相对路径
- 权限：`chmod` / `chown`、rwx 数字含义、`sudo`
- 文本处理：`cat` / `less` / `head` / `tail -f`、`grep` 正则、`awk` 列处理、`sed` 替换、管道与重定向
- 进程与服务：`ps` / `top` / `kill` / `jobs` / `nohup`、`systemctl`、`crontab` 定时任务
- 资源排查：`free` / `df` / `du` / `iostat` / `vmstat`
- 网络：`netstat` / `ss` / `lsof -i` 查端口占用、`curl` / `wget`、`ping` / `telnet` / `traceroute`、`ssh` 与 `scp`
- Shell 脚本：变量、条件判断、循环、函数、退出码、参数传递
- 日志分析实战：从一段 Nginx / 应用日志里统计错误码分布、找出慢请求

## 笔记索引

### 01、文件与目录

- [[Linux 文件与目录操作]] —— ls/cd/cp/mv/rm 与绝对相对路径，脚本里取自身目录的写法
- [[find 文件查找与批量处理]] —— 按名/时间/大小查找，并用 -exec 或 xargs 批量处理
- [[软链接与硬链接的区别]] —— inode 机制、ln 与 ln -s，蓝绿部署与日志轮转中的应用

### 02、权限

- [[Linux 文件权限与 chmod、chown]] —— rwx 数字含义、内核鉴权顺序、SUID/SGID/sticky、umask 与 sudo

### 03、文本处理

- [[管道与重定向]] —— fd 0/1/2、管道内核缓冲、2>&1 顺序、here-doc 与进程替换
- [[日志查看：cat、less、head 与 tail]] —— less 跟随模式、tail -f 与 -F、cat -A 看换行符
- [[grep 正则与管道]] —— BRE/ERE/PCRE、上下文行、退出码与计数陷阱
- [[awk 列处理与统计]] —— 模式动作、关联数组、双文件比对与去重惯用法
- [[sed 流编辑与替换]] —— s 替换、-i.bak、保持区与区间地址

### 04、进程与服务

- [[Linux 进程管理：ps、top 与 kill]] —— R/S/D/T/Z 状态、信号语义、kill 与 kill -9
- [[nohup 与后台任务管理]] —— SIGHUP 链路、nohup/&/disown/tmux 四种保活方式
- [[systemctl 服务管理]] —— unit 类型、journalctl、写 .service、Type=simple/forking
- [[crontab 定时任务]] —— cron 时间格式、% 转义、环境变量差异与 flock 互斥

### 05、资源排查

- [[Linux 磁盘空间排查：df 与 du]] —— df 定位分区、du 逐层下钻、inode 耗尽与被删占用的 lsof +L1
- [[Linux 内存与 CPU 排查：free、vmstat 与 iostat]] —— available 与 free 区别、vmstat/iostat 关键列、容器里看 steal

### 06、网络

- [[Linux 端口占用排查：netstat、ss 与 lsof]] —— ss 比 netstat 快、0.0.0.0 与 127.0.0.1、拒绝 vs 超时的 CLOSE_WAIT/TIME_WAIT
- [[curl 与 wget 命令行调接口]] —— -w 计时拆分、Bearer 鉴权、--resolve、-f 非零退出
- [[网络连通性排查：ping、telnet 与 traceroute]] —— ICMP 与 TCP 区别、mtr、DNS 与 MTU
- [[ssh 与 scp 远程操作]] —— 公钥登录、~/.ssh/config、scp/rsync、端口转发与 ProxyJump

### 07、Shell 脚本

- [[Shell 脚本基础：变量、参数与退出码]] —— 变量引号陷阱、位置参数、getopts、退出码与 set -euo pipefail
- [[Shell 脚本流程控制与函数]] —— if/case/for/while、函数返回数据与子 Shell 变量坑

### 08、日志分析实战

- [[Nginx 日志分析实战]] —— access.log 字段、Top10 IP、5xx 分布、慢请求与 request_time 流水线

## 常考点

- 查看某个端口被哪个进程占用，写出完整命令
- 统计日志中出现次数最多的 IP 前 10 名（`awk` + `sort` + `uniq` + `head` 组合）
- `kill` 与 `kill -9` 的区别，什么时候不该用 `-9`
- 磁盘满了怎么排查（`df` 定位分区、`du` 逐层下钻、被删除但句柄未释放的文件用 `lsof`）
- 软链接与硬链接的区别

## 参考

- 相关笔记：[[03-计算机网络]]
