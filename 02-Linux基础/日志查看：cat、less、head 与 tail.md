---
created: 2026-07-31
tags: [Linux基础/文本处理]
---

# 日志查看：cat、less、head 与 tail

> 在几百兆的日志里快速定位问题：实时盯 `tail -f`、翻阅用 `less`、取头尾用 `head`/`tail`，并且不把服务器内存撑爆。

## 概念

### 为什么不能对大日志用 cat

`cat big.log` 会把内容一股脑推给终端，几百万行滚过去你什么也看不见，终端还会因为渲染卡死。更糟的是通过 SSH 看远程日志时，全部数据都要走网络。

正确的心智模型是：**先想清楚你要的是「哪一段」**，再选命令。

| 需求 | 命令 |
|------|------|
| 文件很小，全看 | `cat` |
| 翻阅、搜索、跳转 | `less` |
| 只看开头（表头、格式） | `head` |
| 只看结尾（最新日志） | `tail` |
| 实时盯着新日志 | `tail -f` / `tail -F` |
| 按关键字捞 | `grep`（见 [[grep 正则与管道]]） |

### less 为什么比 more 好

`less` 是**按需读取**的：打开 1GB 日志时它只加载你当前看到的那一屏，内存占用几乎恒定，所以 `less huge.log` 秒开。而 `more` 只能向下翻不能回退，`cat` 更是要把整个文件推给终端。这就是那句老梗「less is more」的由来。

### tail -f 的底层机制

`tail -f` 的实现是：打开文件、`lseek` 到末尾、然后循环 `read()`；读到 EOF 就 sleep 一小会儿（现代实现用 `inotify` 监听文件变更事件）再试。

关键点：**它持有的是 inode 句柄，不是文件名**。所以日志被 `logrotate` 切割（`mv` 改名）后，`tail -f` 仍在盯着那个已改名的旧文件，屏幕永远不再更新。`tail -F`（等价 `--follow=name --retry`）会周期性检查路径对应的 inode 有没有变，变了就重新打开——**盯生产日志一律用 `-F`**。

## 用法

### cat 与它的变体

```bash
cat app.log                    # 全量输出（仅限小文件）
cat -n app.log                 # 带行号
cat -A app.log                 # 显示不可见字符：$ 行尾、^I 制表符、^M 回车
cat a.log b.log > all.log      # 拼接
cat > note.txt <<'EOF'         # 用 here-doc 快速写文件
第一行
EOF
tac app.log | head -20         # tac = 倒序 cat，看最新的 20 行（另一种思路）
zcat access.log.1.gz | grep 500   # 直接读 gz，不用先解压
```

`cat -A` 是排查「配置看着一模一样却不生效」的杀手锏——通常是行尾混进了 Windows 的 `\r`（显示为 `^M`），或者末尾有看不见的空格。

```bash
# Windows 换行导致的 "bad interpreter: /bin/bash^M"
cat -A deploy.sh | head -1        # #!/bin/bash^M$
sed -i 's/\r$//' deploy.sh        # 修复
# 或 dos2unix deploy.sh
```

### less：日志翻阅主力

```bash
less app.log
less +F app.log         # 打开即进入类似 tail -f 的跟随模式（Ctrl+C 退出跟随，继续翻阅）
less +G app.log         # 直接跳到文件末尾
less -N app.log         # 显示行号
less -S app.log         # 长行不折行，左右滚动（看有宽字段的日志很舒服）
less -i app.log         # 搜索忽略大小写
journalctl -u nginx | less    # 管道进 less 也可以
```

进入 less 后的按键（必须背下来的几个）：

```text
/关键字     向下搜索      ?关键字   向上搜索
n / N       下一个 / 上一个匹配
g / G       跳到文件头 / 文件尾
Ctrl+F / Ctrl+B   下一页 / 上一页
数字 + g    跳到指定行，如 1000g
F           进入跟随模式（同 tail -f），Ctrl+C 退出
&关键字     只显示匹配的行（相当于内置 grep，非常好用）
-S 回车     运行中切换是否折行
q           退出
```

`&ERROR` 这个功能被严重低估：不用退出 less、不用重新跑 grep，直接在当前文件里过滤，`&` 后回车清空过滤。

### head 与 tail

```bash
head -n 20 app.log        # 前 20 行
head -c 200 app.log       # 前 200 字节（看二进制文件头）
tail -n 100 app.log       # 后 100 行
tail -n +1000 app.log     # 从第 1000 行开始到结尾（注意 + 号）
tail -f app.log           # 实时跟随
tail -F app.log           # 跟随「文件名」，日志切割后自动重开（推荐）
tail -f -n 200 app.log    # 先显示最后 200 行再跟随
tail -f app.log | grep --line-buffered ERROR    # 实时过滤，必须加 --line-buffered
tail -f app1.log app2.log # 同时跟多个文件，会显示 ==> 文件名 <== 分隔
```

取「中间某一段」的两种写法：

```bash
sed -n '1000,1100p' app.log            # 第 1000–1100 行（推荐，可加 q 提前退出）
head -n 1100 app.log | tail -n 101     # 等价写法
awk 'NR>=1000 && NR<=1100' app.log     # awk 版本
```

超大文件取中间行时，`sed -n '1000,1100p;1101q' app.log` 加个 `q` 让 sed 读到 1101 行就退出，比全文扫描快得多。

### 实战组合

```bash
# 1) 看最近 10 分钟的错误（日志带时间戳）
tail -n 5000 app.log | grep "$(date -d '10 minutes ago' '+%Y-%m-%d %H:%M')"

# 2) 实时盯着报错并高亮
tail -F app.log | grep --color=always -E "ERROR|Exception|FATAL"

# 3) 一边实时看一边存档
tail -F app.log | tee -a /tmp/watch.log

# 4) 只看新产生的日志（清屏后从当前时刻开始）
tail -n 0 -F app.log

# 5) 压测时观察日志增长速率
watch -n 1 'wc -l app.log'
```

## 踩坑

1. **日志切割后 `tail -f` 不再输出**。`tail -f` 盯的是 inode，logrotate 用 `mv` 改名后 inode 没变，你盯的还是旧文件。**统一用 `tail -F`**。

2. **`tail -f | grep` 半天不出东西**。grep 检测到输出不是终端就转成块缓冲，攒够 4KB 才吐。加 `--line-buffered`：

   ```bash
   tail -F app.log | grep --line-buffered ERROR | tee err.log
   ```

   如果中间还有 `awk`，用 `awk '{print; fflush()}'` 或整体套 `stdbuf -oL`。

3. **`cat` 一个 GB 级文件把终端卡死**。SSH 会话直接假死。补救：Ctrl+C，实在不行 `Ctrl+Z` 后 `kill %1`；下次用 `less`。

4. **`cat` 到二进制文件导致终端乱码、输入不回显**。二进制里的控制字符改变了终端状态。执行 `reset` 或 `stty sane` 恢复。看二进制用 `xxd`、`hexdump -C`、`strings`。

5. **`less` 里搜不到明明存在的关键字**。可能是大小写问题（用 `-i` 或搜索时打 `/-i`），也可能日志被压缩过或者你打开的是被切割前的旧文件。

6. **磁盘满是因为 `tail -f` 的输出被重定向进了文件且没人管**。`nohup tail -f app.log > watch.log &` 这种写法会让 watch.log 无限增长，本身就是磁盘杀手。

7. **`head -n -5`（倒数）在部分实现上不支持**。GNU coreutils 支持 `head -n -5`（去掉最后 5 行），BusyBox / macOS 的实现可能不支持，容器里写脚本要留意。

8. **看 gz 日志先解压，把磁盘撑爆**。直接 `zcat` / `zgrep` / `zless`，不落地：

   ```bash
   zgrep -c "500" access.log.*.gz
   ```

9. **`tail -f` 的进程忘了退出**。SSH 断开后进程可能残留，日积月累几十个 tail 挂着。用 `ps -ef | grep tail` 清理。

## 面试怎么答

**Q：怎么实时查看日志？`tail -f` 和 `tail -F` 有什么区别？**

A：`tail -f` 是跟踪**文件描述符**：它 open 一次之后就一直读那个 inode，文件被 logrotate 改名或删除重建后，它仍盯着旧 inode，屏幕不再更新。`tail -F` 等价于 `--follow=name --retry`，会周期性检查文件名对应的 inode 是否变化，变了就重新打开，文件暂时不存在也会重试。生产环境查日志一律用 `-F`。另外实时过滤时要加 `grep --line-buffered`，否则会因为块缓冲看起来「卡住」。

**Q：一个 5GB 的日志，怎么查看第 100 万行附近的内容？**

A：不要 `cat` 也不要 `vim`。用 `sed -n '999990,1000010p;1000011q' app.log`，`p` 打印区间、末尾的 `q` 让 sed 读完就退出，避免扫完剩下的 4GB。或者 `less app.log` 后输入 `1000000g` 跳转——less 是按需读取的，打开大文件不占内存。如果只是想按关键字定位，直接 `grep -n 关键字` 拿到行号再跳。

**Q：`cat`、`less`、`more`、`tail` 怎么选？**

A：按「读取方式」区分：`cat` 是一次性全量推给 stdout，只适合小文件或作为管道的源头；`more` 只能单向翻页，基本被淘汰；`less` 按需读取、支持双向翻页、搜索、行内过滤（`&关键字`）和跟随模式（`F`），是查大文件的默认选择；`head`/`tail` 用于快速取头尾，`tail -F` 用于实时跟随。日志排查的典型链路是先 `tail -F` 看现状，再 `grep -n` 定位行号，最后 `less +行号g` 看上下文。

**Q：怎么查看被 gzip 压缩的历史日志？**

A：用 z 系列命令直接读，不解压落地：`zcat`、`zgrep`、`zless`、`zdiff`。比如 `zgrep -c "HTTP/1.1\" 500" access.log.*.gz` 可以直接统计各个历史归档里的 500 次数。这样既不占磁盘也快，尤其在磁盘本来就快满的排查场景下很关键。

## 参考

- [`less` 官方 man page](https://man7.org/linux/man-pages/man1/less.1.html)
- [GNU Coreutils - head/tail](https://www.gnu.org/software/coreutils/manual/html_node/Output-of-parts-of-files.html)
- 相关笔记：[[grep 正则与管道]]
- 相关笔记：[[Nginx 日志分析实战]]
