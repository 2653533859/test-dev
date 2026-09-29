---
created: 2026-07-31
tags: [Linux基础/文件与目录]
---

# find 文件查找与批量处理

> 在几十万文件的服务器上按名字、时间、大小、权限精确捞出目标文件，并安全地批量处理它们。

## 概念

### find 是「遍历 + 表达式求值」，不是简单的搜索

`find` 的完整语法是：

```text
find [起始路径...] [选项] [表达式]
```

它会**深度优先遍历**起始路径下的每一个文件，对每个文件依次求值表达式。表达式由「测试条件」（`-name`、`-mtime`）和「动作」（`-print`、`-delete`、`-exec`）组成，它们之间默认是**逻辑与**（`-a`），可以用 `-o` 表示或、`!` 或 `-not` 表示非、`\( \)` 分组。

理解「表达式从左到右短路求值」很关键：`find . -name "*.log" -delete` 是先判断名字匹配、再执行删除；如果写成 `find . -delete -name "*.log"`，`-delete` 会先对每个文件求值（也就是先删掉），这是灾难性的顺序错误。

### find vs locate vs which vs whereis

| 命令 | 原理 | 速度 | 实时性 |
|------|------|------|--------|
| `find` | 实时遍历文件系统 | 慢（受目录规模影响） | 完全实时 |
| `locate` | 查 `mlocate.db` 索引库 | 极快 | 依赖 `updatedb`，可能滞后一天 |
| `which` | 在 `$PATH` 里找可执行文件 | 快 | 实时 |
| `whereis` | 找二进制/源码/man 页 | 快 | 实时 |

排查现场首选 `find`（结果一定是当前真实状态）；只是想知道某个包大概装哪了，`locate` 更快。

## 用法

### 按名字查找

```bash
find /var/log -name "*.log"          # 区分大小写
find /var/log -iname "*.LOG"         # 忽略大小写
find . -name "test_*.py" -type f     # 只要普通文件
find . -path "*/node_modules/*" -prune -o -name "*.js" -print   # 排除某目录
```

`-type` 的取值：`f` 普通文件、`d` 目录、`l` 软链接、`s` socket、`p` 管道。

> `-name` 的模式**必须加引号**。不加引号时，Shell 会先用通配符在当前目录展开 `*.log`，把展开结果当参数传给 `find`，行为完全不符合预期。

### 按时间查找（排查现场最常用）

| 参数 | 含义 |
|------|------|
| `-mtime n` | 内容最后修改于 n×24 小时前 |
| `-atime n` | 最后访问时间 |
| `-ctime n` | inode 变更时间（改权限、改属主也会更新） |
| `-mmin n` | 单位改成分钟 |

数字前缀语义：`-mtime +7` 是「7 天以前」，`-mtime -7` 是「7 天以内」，`-mtime 7` 是「恰好第 7 天那一天」。**记不住就只用 `+` 和 `-`，别用裸数字。**

```bash
find /var/log -name "*.log" -mtime +30            # 30 天前的老日志
find /app -type f -mmin -10                       # 最近 10 分钟被改过的文件
find /etc -type f -newer /etc/nginx/nginx.conf    # 比某文件更新的文件
```

「发布后服务异常，看看刚才谁动过配置」——`find /etc -type f -mmin -30` 一把梭。

### 按大小、权限、属主查找

```bash
find / -type f -size +500M                 # 大于 500M，磁盘满时定位大文件
find . -size -1k -type f                   # 小于 1k
find . -type f -perm 777                   # 权限恰好 777（安全测试常查）
find . -type f -perm -u+s                  # 带 SUID 位，提权风险点
find /home -user jenkins -type f           # 属主是 jenkins
find /data ! -user root                    # 属主不是 root
```

`-size` 单位：`c` 字节、`k` KB、`M` MB、`G` GB。**默认单位是 512 字节的块**，所以 `-size +100` 不是 100MB，务必带单位。

### 组合条件

```bash
# 30 天前 且 大于 100M 的日志
find /var/log -name "*.log" -mtime +30 -size +100M

# .log 或 .gz（注意转义括号与 -o）
find /var/log \( -name "*.log" -o -name "*.gz" \) -mtime +7

# 排除 .git 与 node_modules 后统计代码行数
find . \( -name .git -o -name node_modules \) -prune -o -name "*.py" -print
```

### 对结果执行动作：-exec、-delete、xargs

三种方式，性能与安全性不同。

```bash
# 1) -exec ... \;  每个文件起一个进程，慢但简单
find . -name "*.tmp" -exec rm -f {} \;

# 2) -exec ... +   把多个文件拼成一条命令，进程数大幅减少（推荐）
find . -name "*.tmp" -exec rm -f {} +

# 3) xargs：配合 -print0 / -0 处理带空格的文件名（推荐）
find . -name "*.tmp" -print0 | xargs -0 rm -f

# 4) -delete：find 内建，最快，但要先用 -print 预演
find . -name "*.tmp" -print          # 先看
find . -name "*.tmp" -delete         # 再删
```

`{}` 是「当前文件路径」的占位符，`\;` 结尾表示一个文件执行一次，`+` 结尾表示尽量批量。

实战组合：

```bash
# 清理 7 天前的日志并打印释放了多少
find /var/log/app -name "*.log" -mtime +7 -printf "%s\n" | awk '{s+=$1} END {print s/1024/1024 " MB"}'
find /var/log/app -name "*.log" -mtime +7 -delete

# 批量替换所有配置里的测试环境域名（配合 sed）
find /app/conf -name "*.yaml" -print0 | xargs -0 sed -i 's/test\.example\.com/uat.example.com/g'

# 找出所有 pytest 用例文件并统计数量
find . -name "test_*.py" -type f | wc -l

# 把找到的日志打包
find /var/log -name "*.log" -mtime -1 -print0 | xargs -0 tar -czf today-logs.tar.gz
```

### 控制遍历深度

```bash
find /data -maxdepth 1 -type d       # 只看第一层子目录，不进去递归
find /data -mindepth 2 -name "*.jar"
```

`-maxdepth 1` 在磁盘排查时非常有用：配合 `du -sh` 逐层下钻，避免一次性扫全盘。

## 踩坑

1. **`-name` 不加引号**。`find . -name *.log` 在当前目录恰好有一个 `.log` 文件时会被 Shell 展开成 `find . -name app.log`，结果只找 `app.log`；有多个时直接报 `paths must precede expression`。**永远加引号**。

2. **`-size +100` 不是 100MB**。默认单位是 512 字节块，`+100` 实际是 50KB。带上 `M` / `G`。

3. **文件名带空格 / 换行导致 `xargs` 拆错**。必须 `find ... -print0 | xargs -0 ...`，用 `\0` 而不是空白符做分隔。

4. **`-mtime 7` 只匹配第 7 天**。想删「7 天以上」写 `+7`。有人写成 `-mtime 7` 结果每天只清掉一天的量，磁盘还是慢慢涨满。

5. **`-exec rm {} \;` 在几十万文件下极慢**。每个文件 fork 一次进程。换成 `-exec rm {} +` 或 `-delete`，速度差一到两个数量级。

6. **在 `/` 下 find 扫到 `/proc`、`/sys` 卡死或报错刷屏**。加 `-xdev` 限制不跨文件系统，或 `2>/dev/null` 屏蔽权限错误：

   ```bash
   find / -xdev -type f -size +1G 2>/dev/null
   ```

7. **删除动作和条件写反**。`find . -delete -name "*.log"` 会先删所有文件。**动作永远写在条件后面**，并且删前先用 `-print` 跑一遍。

8. **软链接不被跟随**。默认 `find` 不进入软链接指向的目录。需要跟随时用 `find -L`，但注意循环软链接会导致无限递归。

9. **`-prune` 的写法反直觉**。排除目录的固定套路是 `find . -path "./排除目录" -prune -o <真正的条件> -print`，末尾的 `-print` 不能省，否则会把被排除的目录也打印出来。

## 面试怎么答

**Q：怎么找出服务器上 30 天前、大于 100M 的日志并清理？**

A：

```bash
find /var/log -type f -name "*.log" -mtime +30 -size +100M -print   # 先预演
find /var/log -type f -name "*.log" -mtime +30 -size +100M -delete  # 再执行
```

要点是三条：`-mtime +30` 里的 `+` 表示「以上」，`-size` 必须带 `M` 单位否则默认是 512 字节块，删除前一定先 `-print` 确认清单。生产上更稳妥的做法是先 `mv` 到临时目录观察一天再删，或者直接交给 `logrotate` 管理。

**Q：`find -exec` 和 `xargs` 有什么区别？**

A：`-exec cmd {} \;` 对每个结果 fork 一次进程，文件多时极慢；`-exec cmd {} +` 会把尽可能多的文件拼成一条命令，接近 `xargs` 的效率。`xargs` 的优势是能配合 `-P` 并行、`-n` 控制每批数量，而且是管道语义、更灵活。共同的坑是文件名里的空格，必须用 `find -print0 | xargs -0` 组合。

**Q：`find` 很慢怎么优化？**

A：一是限制范围——指定更精确的起始目录、用 `-maxdepth` 限层、用 `-xdev` 不跨文件系统；二是把最能过滤掉大多数文件的条件写在前面，利用短路求值（比如 `-type f` 放前面）；三是用 `-prune` 剪掉 `node_modules`、`.git` 这类巨型目录；四是如果只是「找某个包装在哪」，改用基于索引的 `locate`。

## 参考

- [GNU findutils 官方手册](https://www.gnu.org/software/findutils/manual/html_mono/find.html)
- 相关笔记：[[Linux 文件与目录操作]]
- 相关笔记：[[Linux 磁盘空间排查：df 与 du]]
- 相关笔记：[[sed 流编辑与替换]]
