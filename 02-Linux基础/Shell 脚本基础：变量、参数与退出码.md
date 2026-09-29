---
created: 2026-07-31
tags: [Linux基础/Shell脚本]
---

# Shell 脚本基础：变量、参数与退出码

测试开发日常里，Shell 脚本是用来把「重复的手工操作」串成一条可复跑的命令流：一键部署、批量改配置、跑完用例自动收日志。本章先打地基——变量、参数、退出码，这三样是脚本能不能用、能不能被别人放心调用的关键。

## 概念

Shell（如 `bash`）是「逐行解释执行」的命令解释器。脚本的本质是把原本在终端敲的命令写进一个文件，加一点变量和判断。三个核心概念：

- **变量（variable）**：`name=value` 的形式，引用时加 `$`。Shell 变量默认都是字符串，没有类型，需要数字运算时走 `$(( ))` 或 `expr`。
- **位置参数（positional parameter）**：脚本被调用时传进来的参数，用 `$1` `$2` … `${10}` 引用，`$0` 是脚本名，`$@` 是全部参数列表，`$#` 是参数个数。
- **退出码（exit code）**：每条命令执行完都会返回一个 0–255 的整数给 Shell，约定 **0 表示成功，非 0 表示失败**。脚本最后一条命令的退出码就是脚本的退出码，可用 `exit N` 显式指定。`$?` 拿到上一条命令的退出码。

为什么退出码重要：CI/CD、调用方 `if my_script.sh; then ...` 全靠它判断成败。测试脚本不返回正确的退出码，CI 会「假绿」。

## 用法

### 变量定义与作用域

```bash
name="alice"          # 等号两边不能有空格
echo "$name"          # 推荐带引号，防分词
readonly pi=3.14      # 只读变量
unset name            # 删除变量

# 环境变量：子进程可见
export BUILD_DIR=/tmp/build
```

常见内置变量：`$$`(当前 PID)、`$!`(上一后台任务 PID)、`$PPID`(父 PID)。

### 变量引号陷阱

```bash
files="a b.txt c.txt"
for f in $files; do echo "$f"; done   # 不加引号：按空格拆成 3 个
for f in "$files"; do echo "$f"; done # 加引号：整个当 1 个
```

### 参数处理

```bash
#!/usr/bin/env bash
echo "脚本名: $0"
echo "第一个参数: $1"
echo "参数个数: $#"
echo "全部参数(可迭代): $@"

# 安全取带默认值的参数
env="${1:-prod}"          # 没传则用 prod
testcase="${2:-all}"

# 大于等于 10 的位置参数必须加花括号
echo "第 10 个: ${10}"
```

更规范的做法是 `getopts` 解析 `-a -b value` 这种风格：

```bash
while getopts "e:t:vh" opt; do
  case $opt in
    e) env="$OPTARG" ;;
    t) testcase="$OPTARG" ;;
    v) verbose=1 ;;
    h) echo "usage: $0 -e env -t testcase"; exit 0 ;;
    *) exit 1 ;;
  esac
done
```

### 退出码

```bash
ls /not/exist
echo "上条命令退出码: $?"   # 2

# 测试脚本显式返回失败，让 CI 知道挂了
pytest tests/ || exit 1

# 用 trap 在脚本退出时清理临时文件
cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT
```

## 踩坑

1. **`name = value` 写成带空格**：Shell 会把 `name` 当命令执行，报 `command not found`。等号两边不能有空格。
2. **变量不加引号导致分词/通配**：`rm -rf "$dir"` 若 `$dir` 为空且没引号，`rm -rf` 会很危险；含空格的路径不加引号会被拆成多个参数。
3. **`$?` 会被紧随其后的命令覆盖**：想保留要先存下来：`code=$?; echo "exit=$code"`。
4. **`$@` 与 `$*` 的区别**：`"$@"` 每个参数保持独立（推荐），`"$*"` 把所有参数拼成一个字符串。循环参数务必用 `"$@"`。
5. **退出码大于 255 会溢出**：`exit 300` 实际返回 `300 % 256 = 44`，别依赖大数值。
6. **脚本忘了 `set -e` 也没手动判断**：中途命令失败脚本仍继续跑，可能产生脏数据。关键脚本建议开头加 `set -euo pipefail`。
7. **只读变量无法 unset/重新赋值**：`readonly` 后是真的改不了，调试时别困惑。
8. **`#!/usr/bin/env bash` 与 `#!/bin/sh` 行为不同**：`sh` 是 POSIX 子集，不支持数组、`[[ ]]`、`source` 等 bash 特性，迁移脚本要注意。
9. **子 Shell 里改的变量父 Shell 看不到**：`(export x=1)` 加括号是子 Shell，退出后父进程无此变量；函数内改全局变量可以，但管道里的改动（`echo | while read`）也发生在子 Shell，循环外读不到——这是经典坑。
10. **`getopts` 只支持单字符短选项**：不支持 `--long-option`，需要长选项得用 `getopt`（注意 GNU/BSD 差异）或手写 `case "$1" in --env) ...`。

## 面试怎么答

**Q：`set -euo pipefail` 分别管什么？**
- `-e`：任意命令返回非 0 立即退出脚本，避免错误被忽略。
- `-u`：引用未定义变量直接报错退出（默认是当成空字符串，极易出 bug）。
- `-o pipefail`：管道中任意一段失败，整个管道返回非 0（默认只看最后一段）。测试脚本加上它更健壮。

**Q：`$@` 和 `$*` 有什么区别？**
`"$@"` 把每个位置参数作为独立单词展开（带空格的参数不会被拆），`"$*"` 把全部参数用 `IFS` 首字符（默认空格）拼成一个字符串。循环遍历参数时只用 `"$@"`。

**Q：为什么脚本退出码很重要？**
它是脚本与外部（CI、父脚本、cron）的契约：0 成功非 0 失败。`pytest` 全过返回 0、有失败返回非 0，CI 才能正确标记红绿。测试脚本若吞掉错误、始终返回 0，就是「假绿」。

**Q：`$?` 有什么注意点？**
它只保存「最近一条命令」的退出码，且读之前不能被别的命令覆盖。要跨命令保留就先赋值给变量。

**Q：Shell 变量有类型吗？**
没有，默认都是字符串。数字运算需用 `$(( a + b ))`、或 `let`、或 `expr`。比较大小用 `[[ $a -gt $b ]]`（算术）而非 `>`（那是字典序/重定向）。

## 参考

- [`bash(1)` man page](https://man7.org/linux/man-pages/man1/bash.1.html)
- [Bash 参考手册（GNU）](https://www.gnu.org/software/bash/manual/)
- 相关笔记：[[Shell 脚本流程控制与函数]]
- 相关笔记：[[管道与重定向]]
- 相关笔记：[[Nginx 日志分析实战]]
