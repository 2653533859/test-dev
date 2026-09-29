---
created: 2026-07-31
tags: [Linux基础/文本处理]
---

# grep 正则与管道

> 从上百万行日志里精确捞出目标行，还要带上下文、排除干扰、统计数量——这是排查线上问题的第一把刀。

![[assets/grep-pattern-pipeline.svg]]
*图示：grep 逐行流式匹配管道（tail → grep → awk → sort），三种正则方言 BRE/ERE/PCRE 的差异，上下文参数 -A/-B/-C 的作用，以及退出码用作条件判断、-c 数行数而非次数的陷阱。*

## 概念

### grep 做的事：逐行匹配，输出整行

`grep` 的名字来自 ed 编辑器的命令 `g/re/p`（global / regular expression / print）。它的语义极其简单：**对输入的每一行做正则匹配，命中就把整行打印出来**。

正因为「以行为单位」，它天生适合日志——日志正好是一行一条记录。也正因为如此，跨行的内容（比如 Java 的异常堆栈）它一次只能捞到一行，需要靠 `-A/-B/-C` 带上下文。

### 三种正则方言：BRE / ERE / PCRE

这是 grep 最让人困惑的地方。

| 模式 | 命令 | 特点 |
|------|------|------|
| BRE（基本正则） | `grep` 默认 | `+` `?` `{}` `()` `\|` 都要**转义**才有特殊含义 |
| ERE（扩展正则） | `grep -E`（= `egrep`） | 上述符号直接生效，写法直观 |
| PCRE（Perl 正则） | `grep -P` | 支持 `\d` `\w` `\s`、非贪婪 `*?`、前后向断言 |
| 固定字符串 | `grep -F`（= `fgrep`） | 完全不解析正则，最快 |

```bash
grep "err\|warn" app.log      # BRE：或要写成 \|
grep -E "err|warn" app.log    # ERE：直观（推荐日常用这个）
grep -P "\d{3}ms" app.log     # PCRE：\d 只有 -P 才支持
grep -F "a.b.c" hosts.txt     # 把 . 当普通字符，不当通配
```

**建议**：日常统一用 `grep -E`，需要 `\d`、断言时再上 `-P`，搜索包含大量特殊字符的固定串（IP、路径、版本号）用 `-F`。

### 正则基本元字符

```text
.        任意单个字符
*        前一项 0 次或多次        +  1 次或多次（ERE）    ?  0 或 1 次（ERE）
[abc]    字符集合                [^abc] 取反
[0-9]    范围                    [[:digit:]] POSIX 字符类
^ $      行首 / 行尾
\b       单词边界
{n,m}    重复 n 到 m 次（ERE）
( )      分组（ERE）             |  或（ERE）
```

POSIX 字符类（`[[:digit:]]`、`[[:space:]]`、`[[:alpha:]]`）在 BRE/ERE 下都能用，是 `\d`、`\s` 的可移植替代。

## 用法

### 高频参数

```bash
grep "ERROR" app.log            # 基本匹配
grep -i "error" app.log         # 忽略大小写
grep -v "DEBUG" app.log         # 反选：排除掉包含 DEBUG 的行
grep -n "ERROR" app.log         # 显示行号（配合 less +行号g 跳转）
grep -c "ERROR" app.log         # 只输出匹配的「行数」（注意不是次数）
grep -l "ERROR" *.log           # 只列出哪些文件命中了
grep -L "ERROR" *.log           # 反过来：哪些文件没命中
grep -w "id" app.log            # 全词匹配，不会匹配到 userid、idx
grep -x "OK" result.txt         # 整行完全等于
grep -o "[0-9]\{3\}ms" app.log  # 只输出匹配到的部分，而不是整行
grep -r "TODO" ./src            # 递归目录
grep -rn --include="*.py" "assert" ./tests   # 递归 + 限定文件类型 + 行号
grep -E "a|b" --color=always app.log | less -R   # 保留高亮送进 less
```

### 上下文参数：排查异常必用

```bash
grep -A 20 "Exception" app.log     # 匹配行 + 后 20 行（After）→ 看完整堆栈
grep -B 5  "Exception" app.log     # 匹配行 + 前 5 行（Before）→ 看什么请求触发的
grep -C 10 "Exception" app.log     # 前后各 10 行（Context）
```

排查 Java 服务报错的标准动作就是 `grep -A 30 "Exception" app.log`——只 grep 一行只能看到异常类名，看不到 `Caused by`。

### 多条件组合

```bash
# 与：串联两个 grep
grep "2026-07-31" app.log | grep "ERROR" | grep -v "健康检查"

# 或：用 -E 的 |
grep -E "ERROR|FATAL|Exception" app.log

# 多个模式从文件读（黑名单/白名单场景）
grep -f patterns.txt app.log
grep -vf ignore.txt app.log
```

### 排查实战

```bash
# 1) 统计各错误码出现次数（-o 只取匹配部分）
grep -oE 'HTTP/1\.[01]" [0-9]{3}' access.log | awk '{print $2}' | sort | uniq -c | sort -rn

# 2) 提取所有 IP
grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' access.log | sort -u

# 3) 找出耗时超过 1 秒的请求（PCRE 断言）
grep -P 'cost=\d{4,}ms' app.log

# 4) 在整个代码库里找硬编码的测试环境地址
grep -rn --include="*.py" --include="*.yaml" -E "https?://(test|uat)\." .

# 5) 排除干扰目录
grep -rn "password" . --exclude-dir={.git,node_modules,venv} --exclude="*.log"

# 6) 实时跟踪错误（注意 --line-buffered）
tail -F app.log | grep --line-buffered -E "ERROR|Exception"

# 7) 直接搜压缩的历史日志
zgrep -c "500" access.log.*.gz

# 8) 找出「有 ERROR 但没有 retry」的那些文件
grep -l "ERROR" *.log | xargs grep -L "retry"
```

### grep 的退出码：脚本里的重要用法

| 退出码 | 含义 |
|--------|------|
| 0 | 至少匹配到一行 |
| 1 | 一行都没匹配到 |
| 2 | 出错（文件不存在、正则非法） |

```bash
# 用作条件判断，-q 表示静默（匹配到就立刻退出，大文件更快）
if grep -q "BUILD SUCCESS" build.log; then
    echo "构建成功"
else
    echo "构建失败" && exit 1
fi

# CI 门禁：日志里出现 ERROR 就让流水线红
! grep -qE "ERROR|FATAL" app.log
```

## 踩坑

1. **`grep -c` 数的是「行数」不是「出现次数」**。一行里出现 3 次 ERROR 也只算 1。要数次数：

   ```bash
   grep -o "ERROR" app.log | wc -l
   ```

2. **`grep "a+b"` 匹配不到**。BRE 下 `+` 是普通字符，`a+b` 是字面量；而想表达「一个或多个 a」的 `a+` 在 BRE 下要写 `a\+`。**统一用 `-E`** 就没这个心智负担。

3. **`\d` 在 grep 下不生效**。GNU grep 的 BRE/ERE 不支持 `\d`，要用 `-P` 或 `[0-9]` / `[[:digit:]]`。而 `grep -P` 在部分精简系统（Alpine 的 BusyBox grep）上不可用，写脚本时用 `[0-9]` 更稳。

4. **管道里 grep 不实时输出**。块缓冲问题，加 `--line-buffered`。见 [[管道与重定向]]。

5. **`grep xxx *` 在空目录或无匹配文件时报错**，且如果某个参数以 `-` 开头会被当成选项。用 `grep -- "-v的内容" file` 或 `grep -e "-abc" file` 明确指定模式。

6. **搜索包含 `.`、`/`、`*` 的字符串误匹配**。`grep "192.168.1.1"` 里的 `.` 是「任意字符」，会匹配到 `192a168b1c1`。精确匹配用 `-F`，或转义成 `192\.168\.1\.1`。

7. **`grep -r` 扫进 `.git`、`node_modules` 导致奇慢**。用 `--exclude-dir={.git,node_modules}`，或直接换 `rg`（ripgrep，默认尊重 `.gitignore`，快一个数量级）。

8. **中文匹配失败或乱码**。`export LANG=zh_CN.UTF-8`；如果只是想按字节匹配、不做多字节解析，可以 `LC_ALL=C grep ...`，这在大文件上还能显著提速。

9. **`grep -v "DEBUG"` 顺手把包含 DEBUG 字样的正常业务日志也滤掉了**。用 `-w` 全词，或把匹配锚定到日志级别字段：`grep -vE "^\S+ +\S+ +DEBUG"`。

10. **在管道链里用 `grep -q` 会提前退出**。`-q` 匹配到第一行就退出，上游会收到 SIGPIPE。做条件判断很好，但别放在需要完整输出的链路中间。

## 面试怎么答

**Q：`grep`、`egrep`、`fgrep` 有什么区别？**

A：本质是同一个程序的三种正则模式。`grep` 默认用 BRE 基本正则，`+`、`?`、`{}`、`()`、`|` 需要反斜杠转义才有元字符含义；`egrep` 等价 `grep -E`，用 ERE 扩展正则，这些符号直接生效，写法更直观；`fgrep` 等价 `grep -F`，完全不解析正则，把模式当固定字符串，速度最快，适合搜 IP、路径这类带很多 `.` 和 `/` 的内容。现在 `egrep`/`fgrep` 已被标记为废弃，官方推荐直接用 `grep -E` / `grep -F`。另外 `grep -P` 启用 PCRE，才支持 `\d`、`\s` 和前后向断言。

**Q：怎么查看日志里某个异常的完整堆栈？**

A：`grep -A 30 "NullPointerException" app.log`。因为 grep 是逐行匹配，只匹配异常那一行拿不到堆栈和 `Caused by`，必须用 `-A`（后 N 行）；想知道是什么请求触发的就加 `-B`（前 N 行），或者直接 `-C` 前后都要。如果堆栈行数不定，更好的做法是先 `grep -n` 拿到行号，再 `sed -n '起,止p'` 或 `less +行号g` 精确看那一段。

**Q：怎么统计日志里 500 错误出现了多少次？**

A：先区分「行数」和「次数」。`grep -c "500" access.log` 数的是含 500 的行数，而且 `500` 会误匹配到耗时 500ms、字节数 500。正确做法是把匹配锚定到状态码字段：

```bash
grep -cE 'HTTP/1\.[01]" 500 ' access.log
# 或用 awk 按列取，更准
awk '$9 == 500' access.log | wc -l
```

结构化的日志优先用 `awk` 按列判断，`grep` 适合非结构化文本。

**Q：`grep` 在大文件上很慢，怎么优化？**

A：几个方向：一是能用 `-F` 就别用正则；二是 `LC_ALL=C grep` 跳过多字节字符集处理，纯 ASCII 场景能快很多；三是只判断存在性时加 `-q`，匹配到第一行就退出；四是先用 `-m N` 限制匹配数量；五是缩小范围，先按时间用 `sed -n` 截取区间再 grep；六是换 `ripgrep`（`rg`），它多线程 + 自动跳过 `.gitignore`，在代码库里快一个数量级。

## 参考

- [GNU grep 官方手册](https://www.gnu.org/software/grep/manual/grep.html)
- [`regex(7)` man page](https://man7.org/linux/man-pages/man7/regex.7.html)
- 相关笔记：[[管道与重定向]]
- 相关笔记：[[awk 列处理与统计]]
- 相关笔记：[[Nginx 日志分析实战]]
