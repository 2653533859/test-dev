---
created: 2026-07-31
tags: [Linux基础/文本处理]
---

# sed 流编辑与替换

> 批量改配置里的环境地址、从日志里抽取指定行区间、清洗掉 Windows 换行——不用打开编辑器就能改文本。

![[assets/sed-awk-workflow.svg]]
*图示：sed 与 awk 两种工作模型对比——sed 的「模式空间 → 执行命令 → 默认打印 → 清空」循环 vs awk 的「BEGIN → 逐行 pattern{action} → END」三段式，以及「改文本用 sed、算数据用 awk」的分工口诀。*

## 概念

### 流编辑器的工作模型

`sed`（stream editor）不是交互式编辑器，它的循环是固定的：

1. 从输入读一行，放进**模式空间（pattern space）**（**不含末尾换行符**）。
2. 对模式空间依次执行所有脚本命令。
3. 除非用了 `-n`，否则把模式空间的内容打印出来。
4. 清空模式空间，读下一行，重复。

理解这个循环能解释很多行为：为什么 `-n` 配合 `p` 才能只打印指定行（否则每行都会被默认打印一次）；为什么跨行操作要用**保持空间（hold space）**这个额外的暂存区。

### 命令语法

```text
sed [选项] '[地址范围]命令[参数]' 文件
```

**地址范围**可以是：

```text
（省略）    所有行
5           第 5 行
5,10        第 5 到 10 行
5,+3        第 5 行及其后 3 行
$           最后一行
/正则/      匹配正则的行
/开始/,/结束/  从匹配开始到匹配结束的区间
1~3         第 1 行开始每隔 3 行（GNU 扩展）
/正则/!     取反：不匹配的行
```

**常用命令**：

| 命令 | 作用 |
|------|------|
| `s/old/new/` | 替换（substitute），最常用 |
| `d` | 删除该行 |
| `p` | 打印（配合 `-n`） |
| `a text` | 在该行后追加 |
| `i text` | 在该行前插入 |
| `c text` | 替换整行 |
| `y/abc/xyz/` | 逐字符转换（类似 `tr`） |
| `q` | 退出（读到这行就停，大文件提速关键） |

### sed 与 awk 的分工

`sed` 面向「行文本的模式替换」，`awk` 面向「列的提取与计算」。要改字符串用 sed，要按第几列做数值比较、分组求和用 awk。二者都能干的事（比如打印指定行区间），谁顺手用谁。

## 用法

### 替换 s 命令

```bash
sed 's/test/uat/' app.conf              # 每行只替换「第一个」匹配
sed 's/test/uat/g' app.conf             # g = global，替换该行所有匹配
sed 's/test/uat/2' app.conf             # 只替换每行的第 2 个匹配
sed 's/test/uat/gi' app.conf            # i = 忽略大小写
sed '3,10s/test/uat/g' app.conf         # 只在第 3–10 行替换
sed '/^#/!s/test/uat/g' app.conf        # 跳过注释行再替换
sed 's/test/uat/gp' -n app.conf         # 只输出被替换过的行（便于确认）
sed 's/test/uat/gw changed.txt' app.conf  # 把被改的行同时写入另一个文件
```

**分隔符可以换**。路径里全是 `/` 时，用 `|`、`#`、`,` 都行，避免满屏转义：

```bash
sed 's|/usr/local/old|/opt/new|g' app.conf     # 清爽
sed 's/\/usr\/local\/old/\/opt\/new/g' app.conf # 等价但难读（「转义地狱」）
```

**反向引用与特殊符号**：

```bash
sed -E 's/([0-9]{4})-([0-9]{2})-([0-9]{2})/\3\/\2\/\1/' dates.txt  # 2026-07-31 → 31/07/2026
sed 's/.*/[&]/' names.txt                # & 表示「整个匹配到的内容」，给每行加方括号
sed -E 's/(host=)\S+/\1127.0.0.1/' app.conf   # 保留 key，只换 value
```

`\1`–`\9` 是分组反向引用，`&` 是整个匹配。注意基本正则下分组要写 `\(...\)`，加 `-E` 后写 `(...)` 即可——**建议一律加 `-E`**。

### 原地修改：-i 与备份

```bash
sed -i 's/test/uat/g' app.conf           # 直接改文件（危险，先确认）
sed -i.bak 's/test/uat/g' app.conf       # 改之前存一份 app.conf.bak（推荐）
sed -i -e 's/a/b/' -e 's/c/d/' app.conf  # 多条命令
```

安全流程永远是「**先不带 `-i` 看效果 → 确认无误 → 加 `-i.bak` 执行**」。

批量改一堆文件：

```bash
find /app/conf -name "*.yaml" -print0 | xargs -0 sed -i.bak 's/test\.example\.com/uat.example.com/g'
grep -rl "old_domain" /app/conf | xargs sed -i 's/old_domain/new_domain/g'
```

`grep -rl` 先列出真正含关键字的文件，避免对无关文件做无意义的重写（也就不会把它们的 mtime 全刷新一遍）。

### 删除、打印与插入

```bash
sed '1d' data.csv                      # 删第一行（去表头）
sed '$d' data.csv                      # 删最后一行
sed '1,5d' app.log                     # 删前 5 行
sed '/^#/d' app.conf                   # 删所有注释行
sed '/^\s*$/d' app.conf                # 删空行（含只有空白的行）
sed -E '/^(#|\s*$)/d' app.conf         # 一次性去掉注释和空行 → 看配置真实内容的神器

sed -n '100,200p' app.log              # 只打印 100–200 行
sed -n '100,200p;201q' app.log         # 加 q 提前退出，大文件快很多
sed -n '/START/,/END/p' app.log        # 打印区间
sed -n '$=' app.log                    # 统计总行数（等价 wc -l）

sed '1i\#!/usr/bin/env bash' script.sh   # 首行前插入
sed '$a\# EOF' script.sh                 # 末行后追加
sed '/\[mysqld\]/a\max_connections=500' my.cnf   # 在某个段落后插入配置
```

### 实战组合

```bash
# 1) 清洗 Windows 换行（^M）
sed -i 's/\r$//' deploy.sh

# 2) 去掉行首行尾空白
sed -E 's/^[[:space:]]+|[[:space:]]+$//g' data.txt

# 3) 把多个空格压成一个
sed -E 's/[[:space:]]+/ /g' access.log

# 4) 脱敏：把手机号中间四位打码
sed -E 's/(1[3-9][0-9])[0-9]{4}([0-9]{4})/\1****\2/g' user.log

# 5) 从 Nginx 日志里抽出时间和 URL
sed -E 's/.*\[([^]]+)\].*"[A-Z]+ ([^ ]+) .*/\1 \2/' access.log | head

# 6) 提取两个时间点之间的日志
sed -n '/2026-07-31 14:00/,/2026-07-31 14:30/p' app.log > incident.log

# 7) 只在某个 section 内替换
sed '/^\[test\]/,/^\[/ s/level=INFO/level=DEBUG/' config.ini

# 8) 给配置模板填值（配合环境变量）
sed -e "s|__HOST__|${DB_HOST}|g" -e "s|__PORT__|${DB_PORT}|g" app.tpl.yaml > app.yaml
```

最后一条是 CI 里渲染配置模板的常见做法：用 `__XXX__` 这种不会与正则冲突的占位符，比 `envsubst` 更可控。

## 踩坑

1. **`sed -i` 在 macOS / BSD 上语法不同**。GNU 下 `sed -i 's/a/b/' f` 可行；BSD 下 `-i` **必须带备份后缀**，`sed -i '' 's/a/b/' f`。跨平台脚本用 `sed -i.bak` 兼容两边，或用 `perl -pi -e`。

2. **忘了 `g`，只替换了每行第一个**。一行里有多个匹配时结果不完整，而且往往过很久才被发现。

3. **替换内容里含 `/` 导致语法错误**。换分隔符：`sed 's|old|new|g'`。分隔符可以是任意字符。

4. **`&` 和 `\1` 在替换串里是特殊字符**。要输出字面量 `&` 得写 `\&`。同理替换串里的 `\` 要写 `\\`。

5. **`sed -i` 之后原文件回不去了**。养成 `-i.bak` 习惯；改生产配置前 `cp -a` 一份。

6. **`sed -i` 会改变文件的 inode**。GNU sed 的 `-i` 实际是「写临时文件 + rename」，所以**硬链接会断开**、正在写这个文件的进程句柄会失效。对正在被写入的日志文件用 `sed -i` 是错误做法。

7. **shell 变量在单引号里不展开**。`sed 's/host/$NEW/'` 里的 `$NEW` 是字面量。要展开就用双引号 `sed "s/host/${NEW}/"`，但此时要小心变量值里的 `/`、`&`、`\` 破坏语法——安全做法是先转义或改用 awk 传参。

8. **正则方言问题**。sed 默认 BRE，`+`、`?`、`|`、`()`、`{}` 都要转义；加 `-E`（GNU 也支持 `-r`）切到 ERE 后写法才和 grep -E、Python 正则一致。**统一加 `-E`**。

9. **`sed -n '1000,2000p' 10G.log` 仍然扫完全文**。sed 不知道后面还有没有匹配，会一直读到 EOF。加 `;2001q` 让它读到就退出。

10. **`a`/`i` 命令在不同实现里语法有差异**。GNU sed 支持 `sed '1i text'`，BSD 必须写成 `sed '1i\'$'\n''text'`。跨平台插入行更稳的做法是用 `awk` 或直接 `{ echo text; cat file; } > new`。

11. **对二进制文件用 sed**。会把文件搞坏，且可能因为没有换行符而把整个文件读进模式空间导致内存爆掉。

## 面试怎么答

**Q：怎么把一个目录下所有配置文件里的测试域名批量换成 UAT 域名？**

A：

```bash
# 1. 先确认影响面
grep -rl "test.example.com" /app/conf
# 2. 预演（不带 -i，看输出对不对）
grep -rl "test.example.com" /app/conf | xargs sed -E 's/test\.example\.com/uat.example.com/g'
# 3. 确认后带备份执行
grep -rl "test.example.com" /app/conf | xargs sed -i.bak -E 's/test\.example\.com/uat.example.com/g'
```

三个要点：用 `grep -rl` 先框定文件避免全量重写；域名里的 `.` 要转义否则会误匹配；`-i.bak` 留后路。文件名可能带空格时还要用 `-print0 | xargs -0`。

**Q：`sed` 和 `awk` 的区别？**

A：`sed` 是流编辑器，核心能力是「按行做模式匹配和文本替换/删除/插入」，语法围绕 `地址 + 命令` 展开，没有变量和数组的概念（严格说有保持空间但很难用）。`awk` 是一门完整的小语言，有变量、关联数组、控制流、函数，核心能力是「按列提取 + 条件判断 + 统计汇总」。判断标准很简单：要**改文本**用 sed，要**算数据**用 awk。

**Q：`sed -i` 有什么风险？**

A：三点。一是不可逆，写错正则就毁了文件，所以要 `-i.bak` 或先不带 `-i` 预演；二是它的实现是「写临时文件再 rename」，会**改变 inode**，导致硬链接断开、正在写该文件的进程句柄失效（所以不能用它改正在被写入的日志）；三是跨平台差异，BSD/macOS 的 `-i` 必须跟备份后缀，`sed -i 's/a/b/'` 在 mac 上会把 `s/a/b/` 当成备份后缀而报错。

**Q：怎么从大日志里截取某个时间段的内容？**

A：

```bash
sed -n '/2026-07-31 14:00/,/2026-07-31 14:30/p' app.log > incident.log
```

用区间地址 `/开始/,/结束/` 配合 `-n ... p`。注意两个坑：一是如果结束模式在文件里不存在，sed 会一路打印到文件末尾；二是超大文件会全文扫描，可以在结束模式后加 `q` 提前退出，写成 `sed -n '/14:00/,/14:30/{p; /14:30/q}'`。如果日志行数很大且时间有序，更快的做法是先用 `grep -n` 拿到起止行号，再 `sed -n '起,止p;止+1q'`。

## 参考

- [GNU sed 官方手册](https://www.gnu.org/software/sed/manual/sed.html)
- 相关笔记：[[awk 列处理与统计]]
- 相关笔记：[[grep 正则与管道]]
- 相关笔记：[[find 文件查找与批量处理]]
