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

（新增笔记后在此挂双链）

## 常考点

- 查看某个端口被哪个进程占用，写出完整命令
- 统计日志中出现次数最多的 IP 前 10 名（`awk` + `sort` + `uniq` + `head` 组合）
- `kill` 与 `kill -9` 的区别，什么时候不该用 `-9`
- 磁盘满了怎么排查（`df` 定位分区、`du` 逐层下钻、被删除但句柄未释放的文件用 `lsof`）
- 软链接与硬链接的区别

## 参考

- 相关笔记：[[03-计算机网络]]
