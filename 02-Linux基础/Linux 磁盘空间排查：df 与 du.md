---
created: 2026-07-31
tags: [Linux基础/资源排查]
---

# Linux 磁盘空间排查：df 与 du

> 「No space left on device」——从定位分区到逐层下钻，再到 inode 耗尽和「删了却没释放」这两个隐藏分支。

![[assets/disk-full-troubleshoot.svg]]
*图示：磁盘满的三条分支——真占满（du 下钻）、inode 耗尽（df -i）、已删除但句柄未释放（lsof +L1），以及各自的处置方式。*

## 概念

### df 与 du 数据来源完全不同

这是理解一切的前提。

- **`df`（disk free）** 读的是**文件系统的超级块**，直接问文件系统「你还剩多少块」。它统计的是**已分配的块**，包括那些「目录项已删除但 inode 还没回收」的文件。
- **`du`（disk usage）** 是**遍历目录树**，把能看到的每个文件的占用累加起来。看不到目录项的文件，它就统计不到。

所以当 **`df` 显示满了，`du` 加起来却小得多**，几乎可以断定是「文件被 `rm` 了，但仍有进程持有句柄，inode 未回收」。这是线上磁盘告警里最经典的一类。

### 为什么会「有空间却写不进去」

两种情况：

1. **inode 耗尽**。文件系统在格式化时就固定了 inode 数量，每个文件（无论多小）占一个 inode。海量小文件（session 文件、缓存碎片、邮件队列、K8s 日志碎片）会把 inode 用光，此时 `df -h` 显示还有空间，但创建新文件报 `No space left on device`。用 `df -i` 才能看出来。
2. **保留块**。ext4 默认给 root 保留 5% 的空间，普通用户看到 `Use% 100%` 时其实还有 5% 是 root 专用的。这也是为什么 `df` 里 `Size ≠ Used + Avail`。

```bash
tune2fs -l /dev/sda1 | grep -i "reserved"     # 查看保留块数
tune2fs -m 1 /dev/sda1                        # 大容量数据盘可以调到 1%，释放不少空间
```

## 用法

### df：先定位是哪个分区

```bash
df -h                       # 人类可读（G/M）
df -h /var/log              # 只看某路径所在的分区
df -i                       # 看 inode 使用率 ← 磁盘满必查的第二条命令
df -Th                      # 带文件系统类型（ext4/xfs/tmpfs/overlay）
df -h --total               # 带汇总行
df -x tmpfs -x devtmpfs -h  # 排除内存文件系统，输出更干净
```

输出怎么读：

```text
Filesystem      Size  Used Avail Use% Mounted on
/dev/vda1        50G   47G  0.5G  99% /
/dev/vdb1       200G  120G   80G  61% /data
tmpfs           7.8G     0  7.8G   0% /dev/shm
overlay          50G   47G  0.5G  99% /var/lib/docker/...
```

**关键是看 `Mounted on` 而不是路径直觉**。`/data` 是独立分区时，清理 `/var/log` 对它毫无帮助。`overlay` 类型说明是容器的联合文件系统，要去宿主机的 Docker 目录处理。

### du：逐层下钻找出大目录

```bash
du -sh /var/log                       # 单个目录总大小（s = summarize）
du -h --max-depth=1 /var | sort -rh   # 第一层各子目录大小，倒序 ← 主力命令
du -h -d 1 /var | sort -rh | head -10 # 同上的简写
du -sh /var/log/* | sort -rh | head   # 按文件/子目录列出
du -x -h -d 1 /                       # -x 不跨文件系统，避免把挂载的数据盘也算进来
du -sh --exclude="*.gz" /var/log      # 排除已归档的
du -ah /var/log | sort -rh | head -20 # 含文件，找出最大的 20 个条目
```

**标准下钻流程**（每次只看一层，跟着最大的那个走）：

```bash
du -x -h -d 1 / | sort -rh | head -5
# 发现 /var 占 40G
du -x -h -d 1 /var | sort -rh | head -5
# 发现 /var/log 占 38G
du -x -h -d 1 /var/log | sort -rh | head -5
# 发现 /var/log/app 占 37G
ls -lhS /var/log/app | head
# 找到 catalina.out 35G
```

比一次性 `du -ah /` 快得多，也不会把终端刷屏。

### 直接找大文件

```bash
find / -xdev -type f -size +1G -exec ls -lh {} \; 2>/dev/null | awk '{print $5, $9}'
find /var/log -type f -size +100M -mtime +7 -printf "%s\t%p\n" | sort -rn | head
ls -lhS /var/log | head -10        # 单目录内按大小排序
ncdu /var                          # 交互式浏览（需安装，强烈推荐）
```

### 三条分支的处置

**分支一：真的被大文件占满**

```bash
# 1) 能截断的日志优先截断而不是删（保住进程句柄）
: > /var/log/app/catalina.out          # 立即释放空间，inode 不变，进程继续写

# 2) 能删的先归档
gzip /var/log/app/access.log.2026-07-*
find /var/log -name "*.log" -mtime +30 -delete

# 3) 根治：配 logrotate
cat > /etc/logrotate.d/myapp <<'EOF'
/var/log/myapp/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
EOF
logrotate -d /etc/logrotate.d/myapp    # -d 是 dry-run，先验证
```

**分支二：inode 耗尽**

```bash
df -i                                  # IUse% 100% 确认
# 找出文件数最多的目录
for d in /var/*; do echo "$(find "$d" -xdev -type f 2>/dev/null | wc -l) $d"; done | sort -rn | head

# 清理时别一次 rm 百万个文件（参数列表会超长，且极慢）
find /var/spool/postfix/maildrop -type f -mtime +7 -delete
find /tmp/sess -type f -mtime +1 -print0 | xargs -0 -n 1000 rm -f
```

**分支三：已删除但句柄未释放**

```bash
lsof +L1                               # 列出 link count < 1 的文件，最直接
lsof | grep -i deleted | sort -k7 -rn | head
# COMMAND  PID  USER  FD  TYPE  DEVICE  SIZE/OFF  NODE  NAME
# java    1234  app   3w  REG   253,1   38654705664  131074 /var/log/app/app.log (deleted)

# 处置一：重启持有句柄的进程（干净）
systemctl restart myapp

# 处置二：不能重启时，直接把那个 fd 截断（立即释放，进程继续跑）
: > /proc/1234/fd/3
```

`/proc/<pid>/fd/<n>` 是进程打开文件的符号链接，往它写空就等于截断原文件——这是生产上不停服释放空间的应急手段。

### 其他容易被忽略的空间占用

```bash
journalctl --disk-usage && journalctl --vacuum-size=500M   # systemd 日志
docker system df && docker system prune -a                 # 容器镜像与层
du -sh /var/lib/docker/containers/*/*-json.log             # 容器日志（默认不轮转！）
rpm -qa --qf '%{size} %{name}\n' | sort -rn | head         # 已装软件包
du -sh ~/.cache /tmp /var/tmp
```

Docker 的 `*-json.log` 是隐形杀手：默认没有大小限制，一个跑几个月的容器能写出几十 G。根治方式是在 `/etc/docker/daemon.json` 配 `log-opts` 的 `max-size` 和 `max-file`。

## 踩坑

1. **`df` 满了但 `du` 加起来对不上**。已删除文件句柄未释放。`lsof +L1` 定位，重启进程或截断 fd。**这是最经典的一道题**。

2. **`df -h` 有空间却报 No space left**。`df -i` 看 inode。海量小文件目录（session、缓存、`/var/spool`）是重灾区。

3. **删了文件空间没变，还越删越慢**。同上，且如果目录里有几百万文件，`rm *` 会因参数列表过长报 `Argument list too long`，要用 `find -delete` 或 `xargs -n 1000`。

4. **在满盘的机器上执行 `du -ah /` 结果自己也卡死**。全盘遍历既慢又占 I/O。用 `-d 1` 逐层下钻。

5. **`du` 把挂载的其他分区也统计进去了**。加 `-x`（`--one-file-system`）。同理 `find` 用 `-xdev`。

6. **`du` 和 `ls` 显示的大小不一样**。`ls -l` 显示的是文件**逻辑大小**，`du` 显示的是**实际占用的块数**。稀疏文件（数据库预分配文件、虚拟机磁盘镜像）逻辑大小 100G 但实际只占几 G；反过来，一个 1 字节的文件也要占一个块（通常 4K）。用 `du --apparent-size` 可以看逻辑大小。

7. **硬链接被 `du` 只算一次**。同一 inode 的多个名字，`du` 只在第一次遇到时计入，所以分目录统计的和可能小于总量。

8. **`rm` 大文件时系统卡顿**。删除超大文件会产生大量 I/O 释放块。生产上更平滑的做法是先 `truncate -s 0`，或者用 `truncate -s -1G file` 分批缩小。

9. **清了日志但空间没释放（Docker 场景）**。容器内的 `rm` 只是在 overlay 的上层写了个 whiteout，底层镜像层的空间不会释放。要在宿主机层面处理。

10. **`/` 满导致连 ssh 都登不上**。因为无法写临时文件。留一手：提前保留一个大的占位文件（`fallocate -l 1G /reserve.bin`），出事时删掉它换取操作空间。

## 面试怎么答

**Q：磁盘满了怎么排查？**

A：三步走，对应三条可能的分支。

第一步 `df -h` 定位是哪个分区满了——注意看 `Mounted on`，别对着错误的分区清理。第二步 `du -x -h -d 1 /目标分区 | sort -rh | head` 逐层下钻，每次只看一层跟着最大的目录走，最后 `ls -lhS` 找到具体大文件。

如果 `df` 显示有空间却仍然写不进去，第三步查两个隐藏原因：一是 `df -i` 看 inode 是否耗尽——海量小文件会把 inode 用光，此时空间还有但建不了新文件；二是 `df` 和 `du` 对不上时，说明有文件被删了但进程还持有句柄，inode 没回收，用 `lsof +L1` 或 `lsof | grep deleted` 定位，重启进程或者用 `: > /proc/<pid>/fd/<n>` 截断。

处置上优先截断而不是删除（`: > big.log` 能立即释放空间且不破坏进程句柄），事后一定要配 logrotate 根治，否则过几天还会满。

**Q：`df` 和 `du` 为什么会对不上？**

A：数据来源不同。`df` 读文件系统超级块，统计的是「已分配的块」；`du` 是遍历目录树把看得见的文件累加。当文件被 `rm` 后，目录项没了所以 `du` 统计不到，但只要还有进程持有它的打开句柄，`nlink` 归零的 inode 就不会被回收，块也不释放，所以 `df` 依然算它占着。典型场景就是有人直接 `rm` 掉了应用正在写的日志文件。反方向的差异也存在：`du` 因为要遍历，扫不到没有权限的目录，也可能少算。

**Q：`df -h` 显示还有 20G，为什么创建文件报 No space left on device？**

A：大概率是 inode 用完了，`df -i` 一看 `IUse%` 是 100%。文件系统在格式化时就固定了 inode 数量，每个文件不管多小都要占一个，所以海量小文件会先耗尽 inode 再耗尽空间。常见于 session 文件目录、缓存碎片、邮件队列、没清理的临时文件。定位方法是按目录统计文件数量找出异常目录，清理时注意分批（`xargs -n 1000`）避免参数列表过长。根治只能是控制小文件产生，或者重新格式化时调大 inode 密度（`mkfs.ext4 -i`），因为 inode 数量在线是改不了的——这也是 XFS 相比 ext4 的一个优势，它的 inode 是动态分配的。

**Q：日志文件正在被应用写入，能直接 `rm` 吗？**

A：不能。`rm` 之后进程句柄还在，空间不会释放，而且应用会继续往这个「看不见的文件」里写，越写越大，你在文件系统里还找不到它。正确做法有三种：一是 `: > app.log` 直接截断，inode 不变、句柄有效、空间立即释放；二是配 logrotate 用 `copytruncate` 模式，或者 `mv` 之后给进程发信号让它重开文件（Nginx 是 `kill -USR1`）；三是让应用本身支持按大小切割。已经误删的补救是 `lsof | grep deleted` 找到 fd，然后 `: > /proc/<pid>/fd/<n>`。

## 参考

- [`df(1)` man page](https://man7.org/linux/man-pages/man1/df.1.html)
- [`du(1)` man page](https://man7.org/linux/man-pages/man1/du.1.html)
- [logrotate 官方文档](https://linux.die.net/man/8/logrotate)
- 相关笔记：[[软链接与硬链接的区别]]
- 相关笔记：[[Linux 内存与 CPU 排查：free、vmstat 与 iostat]]
- 相关笔记：[[find 文件查找与批量处理]]
