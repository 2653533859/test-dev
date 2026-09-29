---
created: 2026-07-31
tags: [Linux基础/Shell脚本]
---

# Shell 脚本流程控制与函数

有了变量和参数，脚本就能做判断、循环和复用。本章讲条件分支 `if`/`case`、循环 `for`/`while`、以及函数——它们是把「一长串命令」组织成可读、可维护脚本的骨架。

## 概念

- **条件判断 `if`**：`if command; then ... fi`，判断的是「命令的退出码是否为 0」。常用 `test`/`[ ]`/`[[ ]]` 做比较，`[[ ]]` 是 bash 增强版（支持 `&&` `||` 和正则 `=~`，且不必对变量加引号防分词）。
- **分支 `case`**：类似其他语言的 switch，用模式匹配，适合解析参数、按环境分支。
- **循环 `for`/`while`/`until`**：`for` 遍历列表，`while` 当条件为真时持续，`until` 条件为假时持续。
- **函数（function）**：`func_name() { ... }` 或 `function func_name { ... }`。Shell 函数没有「返回值」机制（不能 `return 字符串`），`return` 只能返回 0–255 的整数退出码；要传数据靠 `echo` 输出再用 `$( )` 捕获，或通过全局变量。

为什么用函数：避免重复、把一段逻辑命名后可读性高、可单独测试。测试脚本里常把「起服务 / 等端口就绪 / 收日志」封装成函数。

## 用法

### if / 条件

```bash
# 测试文件/字符串/数字
if [[ -f "$conf" ]]; then
  echo "配置文件存在"
elif [[ -z "$env" ]]; then
  echo "env 为空"
else
  echo "使用默认"
fi

# 数字比较用 -eq -ne -gt -lt -ge -le
if [[ $count -gt 100 ]]; then echo "超量"; fi

# 字符串匹配正则
if [[ "$url" =~ ^https:// ]]; then echo "是 https"; fi
```

### case

```bash
case "$env" in
  prod)  base="https://api.prod.com" ;;
  staging) base="https://api.staging.com" ;;
  dev|test) base="http://localhost:8080" ;;
  *) echo "未知环境: $env"; exit 1 ;;
esac
```

### 循环

```bash
# for 遍历
for f in *.log; do
  echo "处理 $f"
done

# for 数字区间
for i in $(seq 1 10); do
  echo "第 $i 次"
done

# while 读文件（逐行，注意 IFS= 防丢首尾空格）
while IFS= read -r line; do
  echo "$line"
done < access.log

# 直到端口就绪
until curl -s "http://localhost:8080/health"; do
  sleep 1
done
```

### 函数

```bash
wait_for_port() {
  local host="$1" port="$2"
  until nc -z "$host" "$port" 2>/dev/null; do
    sleep 1
  done
  echo "$host:$port ready"
}

# 调用并捕获输出
msg=$(wait_for_port localhost 8080)
echo "$msg"
```

## 踩坑

1. **`[ ]` 里变量要加引号**：`[ $var = "x" ]` 当 `$var` 为空会变成 `[ = "x" ]` 语法错；用 `[[ ]]` 可不加引号。
2. **`[` 与 `[[` 混用**：`[` 是外部命令（test），不支持 `&&`/`||` 和 `=~`；`&&` 在 `[` 里要用 `-a`，可读性差，建议统一 `[[ ]]`。
3. **数字比较用 `=`**：`[[ $a = 5 ]]` 是字符串比较，`5` 和 `05` 不等；数字要用 `-eq`。
4. **函数 `return` 不能返回字符串**：`return "ok"` 会报「numeric argument required」。要返回数据用 `echo` + `$( )`。
5. **`for i in $(cat file)` 会按空格/换行拆分**：含空格的行会碎；逐行读请用 `while read`。
6. **`while read` 在管道里丢变量**：`cat file | while read` 子 Shell 改的变量循环外不可见；改成 `while read ... done < file` 重定向输入。
7. **循环里修改 `IFS` 不还原**：改了 `IFS` 会影响后续分词，记得先存原值再还原：`old=$IFS; IFS=,; ...; IFS=$old`。
8. **`seq` 在某些环境不可用**：BSD/macOS 的 `seq` 行为一致，但更可移植的是 `for ((i=1;i<=10;i++))`（bash C 风格）。
9. **函数内 `cd` 影响全局**：函数里 `cd` 改的是当前 Shell 工作目录，最好用子 Shell `(cd dir && ...)` 隔离。
10. **`exit` 在函数里会退出整个脚本**：想只退出函数用 `return`；测试框架里误用 `exit` 会提前终止。

## 面试怎么答

**Q：`[ ]` 和 `[[ ]]` 区别？**
`[` 是 `test` 命令的别名，属于 POSIX，能力有限（不支持 `&&`/`||`、正则、且变量必须加引号）；`[[ ]]` 是 bash 关键字，支持 `&&`、`||`、`=~` 正则，变量可不加引号也不会因空值报错。写 bash 脚本优先 `[[ ]]`。

**Q：Shell 函数怎么「返回」一个字符串？**
Shell 函数没有字符串返回通道。`return` 只能返回 0–255 整数退出码。要返回数据，用 `echo`/`printf` 输出，调用方用 `var=$(func)` 捕获；或写入全局变量。

**Q：`for` 和 `while read` 读文件哪个更可靠？**
`for line in $(cat file)` 按空白（空格+换行）拆分，会破坏含空格的行；正确逐行读取是 `while IFS= read -r line; do ... done < file`，`IFS=` 保留首尾空格，`-r` 禁止反斜杠转义。

**Q：怎么让脚本里的循环/判断更安全？**
开头 `set -euo pipefail`：`-e` 命令失败即停，`-u` 禁止未定义变量，`-o pipefail` 管道任一段失败即整体失败。再配合 `trap` 做清理。

**Q：`until` 和 `while` 区别？**
`while cmd` 是「cmd 退出码为 0 时继续」，`until cmd` 是「cmd 退出码非 0 时继续」。常见写法：`until curl 健康检测; do sleep 1; done` 等端口起来。

## 参考

- [`bash(1)` man page](https://man7.org/linux/man-pages/man1/bash.1.html)
- [Bash 条件表达式（GNU）](https://www.gnu.org/software/bash/manual/html_node/Bash-Conditional-Expressions.html)
- 相关笔记：[[Shell 脚本基础：变量、参数与退出码]]
- 相关笔记：[[管道与重定向]]
- 相关笔记：[[Nginx 日志分析实战]]
