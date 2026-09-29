---
created: 2026-07-31
tags: [Linux基础/文件与目录]
---

# Linux 文件与目录操作

> 在没有图形界面的测试机上，用 `ls` / `cd` / `cp` / `mv` / `rm` 完成部署包投放、配置备份与现场清理，并且不误删。

## 概念

### 一切皆文件，一切挂在一棵树上

Linux 没有 Windows 的 `C:` / `D:` 盘符概念，所有东西都挂在唯一的根 `/` 下。磁盘分区、U 盘、甚至内核暴露的进程信息，都是「挂载」到这棵树的某个目录上。理解这点，才能理解为什么 `df` 看到的是「分区 → 挂载点」的映射，也才能理解为什么 `mv` 跨分区时会变慢。

测试工作中高频出现的几个目录：

| 目录 | 用途 | 测试场景里意味着什么 |
|------|------|----------------------|
| `/etc` | 全局配置 | 改 `nginx.conf`、`hosts`、时区 |
| `/var/log` | 日志 | 90% 的排查从这里开始 |
| `/tmp` | 临时文件 | 重启可能被清空，别放测试报告 |
| `/opt`、`/usr/local` | 第三方软件 | 被测服务、JDK 常装在这 |
| `/proc` | 内核虚拟文件系统 | `/proc/<pid>/` 能反查进程细节 |
| `~`（`/home/用户名`） | 用户家目录 | 脚本、临时数据的落脚点 |

### 绝对路径与相对路径：脚本出错的头号来源

- **绝对路径**以 `/` 开头，从根开始描述，例如 `/var/log/nginx/access.log`，在任何工作目录下含义都一样。
- **相对路径**相对于「当前工作目录（CWD）」，例如 `./logs/app.log`、`../conf/app.yaml`。

关键在于：**CWD 是进程的属性，不是脚本文件的属性**。你在 `/home/test` 下执行 `bash /opt/tools/deploy.sh`，脚本里的 `./conf` 指的是 `/home/test/conf`，不是 `/opt/tools/conf`。这就是「本地跑好好的，Jenkins 上一跑就 `No such file or directory`」的根因——Jenkins 的工作目录和你手工执行时不一样。

```bash
# 让脚本永远以「脚本自身所在目录」为基准，写在脚本开头
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="${SCRIPT_DIR}/conf/app.yaml"
```

几个特殊路径符号：`.` 当前目录、`..` 上级目录、`~` 当前用户家目录、`~test` 用户 test 的家目录、`-` 上一次所在目录（`cd -` 可来回横跳）。

## 用法

### ls：看清文件的元信息

```bash
ls -l          # 长格式：权限、硬链接数、属主、属组、大小、时间、名字
ls -lh         # 大小人类可读（K/M/G）
ls -la         # 含隐藏文件（以 . 开头的）
ls -lt         # 按修改时间倒序，排查「最近谁动了文件」必用
ls -ltr        # 时间正序，最新的排最后，看日志目录很顺手
ls -li         # 显示 inode 号，判断硬链接是否指向同一实体
ls -ld /var/log   # 看目录本身的属性，而不是列出目录内容
```

`ls -l` 的输出逐字段拆开：

```text
-rw-r--r--   1  root  root   4096  Jul 31 10:20  app.yaml
 ①          ②   ③     ④      ⑤      ⑥            ⑦
① 类型+权限（- 普通文件 / d 目录 / l 软链接）
② 硬链接数（目录的这个值 = 子目录数 + 2）
③ 属主  ④ 属组  ⑤ 字节数  ⑥ 最后修改时间  ⑦ 文件名
```

排查时最常用的一条组合：**找出目录下最近被改过的 10 个文件**。

```bash
ls -lt /etc/nginx/conf.d | head -n 11    # 第一行是 total，所以取 11 行
```

### cd 与 pwd：稳住工作目录

```bash
cd /var/log        # 绝对
cd ../nginx        # 相对
cd                 # 不带参数 = 回家目录
cd -               # 回到上一个目录
pwd                # 打印当前目录
pwd -P             # 打印解析软链接后的真实路径
```

`pwd` 与 `pwd -P` 的差异在有软链接时会咬人：如果 `/app` 是指向 `/data/release-20260731` 的软链接，`cd /app && pwd` 显示 `/app`，而 `pwd -P` 显示 `/data/release-20260731`。发版脚本里若要记录「这次部署的真实目录」，必须用 `pwd -P`。

### cp：复制，注意目录与属性

```bash
cp a.txt b.txt                 # 复制文件
cp -r conf/ conf_bak/          # 复制目录必须加 -r（recursive）
cp -a conf/ conf_bak/          # 归档模式：保留权限、属主、时间戳、软链接
cp -i a.txt /tmp/              # 目标已存在时交互确认
cp -n a.txt /tmp/              # 目标已存在时不覆盖（no-clobber）
cp app.yaml{,.bak}             # Brace 展开：等价于 cp app.yaml app.yaml.bak
```

`cp -a` 是改配置前做备份的正确姿势：普通 `cp` 会把文件属主改成执行者、时间戳改成当前时间，回滚后可能因权限不对导致服务起不来。

`cp source/ dest/` 里**结尾斜杠的语义**要留神：`cp -r conf dest` 在 `dest` 已存在时是把 `conf` 整个目录塞进去变成 `dest/conf`；`dest` 不存在时才是「复制成 dest」。这是脚本里目录层级莫名多一层的常见原因。

### mv：改名与移动是同一件事

```bash
mv old.log new.log                 # 改名
mv app.log /var/log/archive/       # 移动
mv -f a b                          # 强制覆盖，不提示
mv access.log{,.$(date +%F)}       # 日志切割：access.log → access.log.2026-07-31
```

底层机制：**同一文件系统内的 `mv` 只是改目录项（rename 系统调用），不搬数据，无论文件多大都是瞬间完成**；跨文件系统（比如从 `/tmp` 移到挂载的 `/data`）则退化成「复制 + 删除」，大文件会很慢，而且中途 Ctrl+C 可能留下半个文件。

> 日志切割的坑：把 `access.log` 用 `mv` 改名后，Nginx 进程仍持有原 inode 的写句柄，继续往改名后的文件写，新 `access.log` 一直是空的。必须再发一个 `kill -USR1 <nginx_pid>` 让它重新打开日志文件。参见 [[Linux 磁盘空间排查：df 与 du]]。

### rm：最危险的命令

```bash
rm a.txt              # 删文件
rm -r logs/           # 删目录
rm -f a.txt           # 不存在也不报错、不提示
rm -rf /tmp/build/*   # 常见清理写法
rm -- -file           # 删以 - 开头的文件（-- 表示后面不再是选项）
rm ./-file            # 同上，另一种写法
```

Linux **没有回收站**，`rm` 之后只能靠备份。工程上的自保手段：

```bash
# 1) 先 ls 确认通配符匹配到什么，再把 ls 换成 rm
ls /tmp/build/*.tmp

# 2) 用变量拼路径时，一定加引号并做非空校验，防止 ${DIR} 为空导致 rm -rf /*
DIR="/tmp/build"
[ -n "${DIR}" ] && [ -d "${DIR}" ] && rm -rf "${DIR:?}/"   # :? 保证变量为空时报错退出

# 3) 危险目录改用 mv 到回收站目录，定时清理
mkdir -p ~/.trash && mv target_dir ~/.trash/
```

### 目录创建与删除

```bash
mkdir -p /data/app/{conf,logs,bin}   # -p 递归创建，配合 brace 一次建三个子目录
rmdir empty_dir                      # 只能删空目录（安全）
tree -L 2 /data/app                  # 直观看两层结构（需安装 tree）
```

## 踩坑

1. **Jenkins 上 `No such file or directory`，本地却正常**。原因是相对路径依赖 CWD，Jenkins 的 workspace 与本地不同。解法：脚本开头用 `SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"` 统一基准，或显式 `cd "${WORKSPACE}"`。

2. **文件名带空格导致「删多了」**。`rm $file`（未加引号）在 `file="my report.log"` 时会被拆成两个参数，删掉 `my` 和 `report.log`。**所有变量引用一律加双引号**：`rm "$file"`。

3. **`cp` 备份后服务起不来**。用 `cp` 而非 `cp -a`，属主从 `nginx` 变成 `root`、权限从 `640` 变成 `644`，服务读配置时报权限错或安全检查失败。备份统一用 `cp -a`。

4. **`mv` 大文件跨分区中断留下半个文件**。`df` 看一下源和目标是否同一挂载点；跨分区搬大文件用 `rsync -a --partial --progress src dst`，可断点续传。

5. **`rm -rf $DIR/` 中 `$DIR` 为空 = 删根**。经典事故。用 `"${DIR:?未设置}"` 让 Shell 在变量为空时直接报错退出。

6. **删了大文件但 `df` 空间没释放**。因为还有进程持有该文件句柄，inode 未回收。用 `lsof | grep deleted` 找到进程并重启它，详见 [[Linux 磁盘空间排查：df 与 du]]。

7. **`ls` 输出被别名污染**。很多发行版把 `ls` 别名成 `ls --color=auto`，脚本里解析 `ls` 输出会混入 ANSI 颜色码。脚本中**不要解析 `ls` 输出**，用 `find` 或 Shell 通配符遍历。

8. **中文文件名显示成 `????`**。终端与系统 locale 不一致。`export LANG=en_US.UTF-8` 或 `zh_CN.UTF-8`，并确认 SSH 客户端编码同为 UTF-8。

## 面试怎么答

**Q：绝对路径和相对路径的区别？脚本里该用哪个？**

A：绝对路径从 `/` 开始，含义与当前工作目录无关；相对路径基于进程的 CWD 解析。脚本里凡是涉及固定资源（配置、依赖包）都应该用绝对路径，或者用 `dirname "${BASH_SOURCE[0]}"` 换算出脚本自身目录再拼接——因为 CWD 是调用者决定的，CI 上和本地往往不同，这是「本地能跑、流水线报文件不存在」最常见的原因。

**Q：`mv` 一个 10G 的文件为什么有时候瞬间完成、有时候要几分钟？**

A：同一文件系统内 `mv` 只是 `rename` 系统调用，改的是目录项里「文件名 → inode」的映射，数据块一个字节都不动，所以是常数时间；跨文件系统时无法复用 inode，只能复制数据再删源文件，耗时与文件大小成正比，还可能中途失败留下残缺文件。用 `df` 可以判断两个路径是不是同一挂载点。

**Q：误删文件怎么办？平时怎么防？**

A：Linux 的 `rm` 不进回收站，ext4 上恢复概率很低（`extundelete` 需要立刻卸载分区、成功率不稳定），所以重点在防：变量引用加双引号并做非空校验、危险变量用 `${DIR:?}`、通配符先用 `ls` 预演一遍、生产上改用 `mv` 到回收站目录再定时清理、重要数据做定时快照或备份。事故发生后第一动作是**立刻停止对该分区的写入**，避免数据块被覆盖。

**Q：`cp` 和 `cp -a` 有什么区别？**

A：`cp` 只复制内容，属主变成执行者、时间戳刷新、软链接被解引用成实体文件；`cp -a` 等价于 `-dR --preserve=all`，保留权限、属主属组、时间戳，并保持软链接为软链接。备份配置、迁移部署目录必须用 `-a`，否则回滚时会因为权限或属主不对导致服务启动失败。

## 参考

- [GNU Coreutils 官方手册](https://www.gnu.org/software/coreutils/manual/coreutils.html)
- [Filesystem Hierarchy Standard 3.0](https://refspecs.linuxfoundation.org/FHS_3.0/fhs/index.html)
- 相关笔记：[[find 文件查找与批量处理]]
- 相关笔记：[[软链接与硬链接的区别]]
- 相关笔记：[[Linux 文件权限与 chmod、chown]]
