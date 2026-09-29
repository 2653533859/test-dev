---
created: 2026-07-31
tags: [Linux基础/文本处理]
---

# awk 列处理与统计

> 日志按列切开、条件过滤、分组求和——`awk` 一行顶一个 Python 脚本，是日志分析里最有杠杆的工具。

## 概念

### awk 是一门语言，不是一个命令

`awk` 的执行模型只有一句话：**读一行 → 对每个 pattern 求值 → 命中就执行 action → 读下一行**。

```bash
awk 'BEGIN{初始化} pattern1{action1} pattern2{action2} END{收尾}' file
```

- `BEGIN` 块：读第一行**之前**执行一次，用来设分隔符、打表头、初始化变量。
- 主体：`pattern { action }`。省略 pattern 表示每行都执行；省略 action 默认是 `{print}`。
- `END` 块：读完所有行**之后**执行一次，用来输出汇总结果。

这个「三段式」正是分组统计的天然结构：BEGIN 初始化累加器 → 主体逐行累加 → END 输出结果。

### 内置变量

| 变量 | 含义 |
|------|------|
| `$0` | 当前整行 |
| `$1` `$2` ... | 第 1、2 列（`$NF` 是最后一列，`$(NF-1)` 倒数第二列） |
| `NF` | 当前行的列数（Number of Fields） |
| `NR` | 已读的总行数（Number of Records），即「第几行」 |
| `FNR` | 当前文件内的行号（多文件时与 NR 不同） |
| `FS` | 输入列分隔符，默认「连续空白」 |
| `OFS` | 输出列分隔符，默认空格 |
| `RS` / `ORS` | 输入 / 输出的「行」分隔符 |
| `FILENAME` | 当前文件名 |

**默认分隔符的特殊性**：`FS` 默认值是空格，但它有个特殊语义——表示「按连续空白（空格+Tab）切分，且忽略行首行尾空白」。一旦你显式写 `-F' '`（单个空格），就变成严格按单个空格切，连续空格会切出空列。这是新手最容易踩的坑。

### 为什么 awk 比 grep + cut 强

- 能按**列**做数值比较：`$9 >= 500`
- 有**关联数组**（字典），天然支持分组统计：`count[$1]++`
- 有 `printf`、数学函数、字符串函数
- BEGIN/END 让「初始化—累加—汇总」一气呵成

## 用法

### 取列与过滤

```bash
awk '{print $1}' access.log                # 第 1 列
awk '{print $1, $9}' access.log            # 多列，逗号会用 OFS（空格）连接
awk '{print $NF}' access.log               # 最后一列
awk '{print NR, $0}' app.log               # 加行号
awk -F: '{print $1, $7}' /etc/passwd       # 指定分隔符为冒号
awk -F'\t' '{print $2}' data.tsv           # Tab 分隔
awk -F'[,;]' '{print $2}' data.txt         # 多个分隔符（正则字符集）
awk 'BEGIN{FS=":"; OFS=" -> "} {print $1, $7}' /etc/passwd   # 输入输出分隔符都改
```

### 条件过滤（pattern 的写法）

```bash
awk '$9 == 500' access.log                 # 第 9 列等于 500（数值比较）
awk '$9 >= 400 && $9 < 500' access.log     # 4xx
awk '$10 > 1000000' access.log             # 响应体大于 1MB
awk '/ERROR/' app.log                      # 正则匹配整行（等价 grep）
awk '$0 !~ /health/' access.log            # 整行不含 health
awk '$7 ~ /^\/api\//' access.log           # 第 7 列以 /api/ 开头
awk 'NR >= 100 && NR <= 200' app.log       # 取第 100–200 行
awk 'NR % 100 == 0' app.log                # 抽样：每 100 行取 1 行
awk '/START/,/END/' app.log                # 范围模式：从 START 行到 END 行
awk 'length($0) > 500' app.log             # 超长行（往往是异常堆栈或攻击载荷）
```

### 统计：关联数组 + END

这是 awk 的杀手锏。

```bash
# 1) 按状态码分组计数
awk '{count[$9]++} END {for (c in count) print c, count[c]}' access.log | sort -k2 -rn

# 2) 求和与平均（第 10 列是响应字节数）
awk '{sum += $10} END {print "总流量:", sum/1024/1024, "MB"}' access.log
awk '{sum += $10; n++} END {print "平均:", sum/n}' access.log

# 3) 求最大值并记住是哪一行
awk '$NF > max {max = $NF; line = $0} END {print max; print line}' timing.log

# 4) 每个接口的请求数 + 总耗时 + 平均耗时（多维统计）
awk '{cnt[$7]++; total[$7] += $NF}
     END {for (u in cnt) printf "%-40s %6d次 平均%.1fms\n", u, cnt[u], total[u]/cnt[u]}' \
    access.log | sort -k2 -rn | head -20

# 5) 去重（不排序，保持首次出现顺序）
awk '!seen[$0]++' file.txt

# 6) 按第 1 列去重
awk '!seen[$1]++' access.log
```

`!seen[$0]++` 是 awk 里最经典的一行代码：第一次遇到某行时 `seen[$0]` 是 0（假），`!0` 为真所以打印，同时 `++` 让它变成 1；再次遇到时 `!1` 为假，不打印。比 `sort -u` 强的地方是**保持原始顺序**且不需要排序开销。

### printf 与格式化输出

```bash
awk '{printf "%-30s %8.2f%%\n", $1, $2*100}' data.txt
# %s 字符串  %d 整数  %f 浮点  %-30s 左对齐宽 30  %8.2f 宽 8 保留 2 位
```

注意 `print` 会自动换行，`printf` 不会，需要自己写 `\n`。

### 字符串与数学函数

```bash
awk '{print toupper($1), length($0)}' file
awk '{print substr($0, 1, 19)}' app.log            # 截取时间戳前 19 字符
awk '{n = split($1, arr, "."); print arr[1]}' hosts.txt   # 按 . 切分成数组
awk '{gsub(/\r/, ""); print}' win.txt              # 全局替换（去掉 \r）
awk '{if (match($0, /cost=[0-9]+/)) print substr($0, RSTART, RLENGTH)}' app.log
awk 'BEGIN{printf "%.2f\n", 10/3}'                 # 3.33
```

### 传参与外部变量

```bash
threshold=500
awk -v t="$threshold" '$NF > t' timing.log       # 用 -v 传，不要用 shell 的双引号拼接
awk -v date="$(date +%F)" '$0 ~ date' app.log

# 多文件处理：用 FNR==NR 区分第一个文件
awk 'FNR==NR {ids[$1]; next} $1 in ids' whitelist.txt access.log
```

`FNR==NR` 是处理两个文件的固定套路：读第一个文件时 `FNR`（文件内行号）等于 `NR`（总行号），据此把内容存进数组，`next` 跳过后续处理；读第二个文件时条件不再成立，就用数组做匹配。上例实现了「只保留白名单 IP 的访问记录」。

### 完整脚本形式

一行写不下时用文件：

```bash
# stat.awk
BEGIN { FS = " "; print "接口\t次数\t平均耗时(ms)" }
$9 == 200 { cnt[$7]++; total[$7] += $NF }
END {
    for (u in cnt) printf "%s\t%d\t%.1f\n", u, cnt[u], total[u] / cnt[u]
}
```

```bash
awk -f stat.awk access.log | column -t
```

## 踩坑

1. **`-F' '` 与默认分隔符不等价**。默认（不写 `-F`）是「连续空白切分并忽略首尾空白」，显式写单空格则是严格按单个空格切，`a  b`（两个空格）会切出一个空列，导致 `$2` 为空。对齐格式的日志一律用默认分隔符。

2. **字符串和数字比较搞混**。`awk '$9 == "500"'` 是字符串比较，`awk '$9 == 500'` 是数值比较。当字段是 `0500` 或带空格时两者结果不同。想强制数值化可以 `$9+0 == 500`。

3. **`-F.` 分隔失败**。`-F` 的参数是**正则**，`.` 表示任意字符。切 IP 要写 `-F'\\.'` 或 `-F'[.]'`。

4. **shell 变量直接嵌进 awk 脚本**。`awk "\$1 == \"$name\""` 这种拼接在 name 含特殊字符时会崩，也存在注入风险。**永远用 `-v` 传参**：`awk -v n="$name" '$1 == n'`。

5. **awk 单引号里不能再写单引号**。整个脚本被单引号包着，里面要用单引号得写成 `'"'"'` 这种丑陋形式。更好的办法是用双引号包 awk 脚本（但要转义 `$`），或写成 `.awk` 文件用 `-f` 调用。

6. **`for (k in arr)` 的顺序是不确定的**。关联数组无序，输出顺序不保证。要排序就把结果管道给 `sort`，或用 GNU awk 的 `asorti()`。

7. **管道里 awk 不实时输出**。同样是缓冲问题，在 action 里加 `fflush()`：

   ```bash
   tail -F app.log | awk '/ERROR/ {print; fflush()}'
   ```

8. **大数精度丢失**。awk 用双精度浮点存所有数字，超过 2^53 的整数（比如某些订单号、纳秒时间戳）会失真，打印时还可能变成科学计数法 `1.23457e+18`。用 `printf "%d"` 或 `%.0f` 强制格式，或者干脆当字符串处理。

9. **`gsub` 会修改 `$0`**。`gsub(/x/, "y")` 默认作用于 `$0` 并重建各字段，如果后面还依赖原始列要先备份。返回值是替换次数，不是替换后的字符串。

10. **mawk 与 gawk 行为不一致**。Debian/Ubuntu 默认是 `mawk`，不支持 `asort`、`gensub`、`\d`、时间函数等 GNU 扩展。脚本要跨环境就避开 GNU 扩展，或显式安装 `gawk`。

## 面试怎么答

**Q：统计访问日志中出现次数最多的 10 个 IP。**

A：

```bash
awk '{count[$1]++} END {for (ip in count) print count[ip], ip}' access.log | sort -rn | head -10
```

思路是用 awk 的关联数组做分组计数，`$1` 是 IP 列，`END` 块里遍历输出，再交给 `sort -rn` 降序、`head -10` 取前十。也可以写成经典管道 `awk '{print $1}' access.log | sort | uniq -c | sort -rn | head -10`，但那种写法需要对全量数据排序，awk 版本只在内存里维护一个哈希表，数据量大时快得多。

**Q：`awk`、`sed`、`grep` 三者怎么分工？**

A：`grep` 负责「筛行」，只做匹配和输出整行；`sed` 负责「改文本」，擅长按行做替换、删除、插入，是流编辑器；`awk` 负责「按列处理和统计」，它是一门有变量、数组、控制流的小语言，适合结构化文本的字段提取、条件过滤和分组汇总。实际排查里三者常串起来用：`grep` 先粗筛缩小范围 → `awk` 取列做统计 → `sed` 做格式清洗。

**Q：awk 的 BEGIN 和 END 有什么用？**

A：`BEGIN` 在读取任何输入之前执行一次，用于设置 `FS`/`OFS`、初始化变量、打印表头；`END` 在所有输入处理完之后执行一次，用于输出汇总结果。典型的统计脚本就是这个结构：BEGIN 里初始化，主体逐行往关联数组里累加，END 里遍历数组输出。另外 `BEGIN` 块可以脱离输入单独运行，`awk 'BEGIN{printf "%.2f\n", 10/3}'` 可以当计算器用。

**Q：怎么统计每个接口的平均响应时间？**

A：

```bash
awk '{cnt[$7]++; total[$7] += $NF}
     END {for (u in cnt) printf "%-40s %6d %8.1fms\n", u, cnt[u], total[u]/cnt[u]}' access.log \
| sort -k3 -rn | head -20
```

用两个关联数组分别累计次数和总耗时，END 里相除得到平均值。要注意三点：一是 `$NF` 取最后一列避免列数变化，二是 `printf` 控制对齐便于阅读，三是平均值容易被极端值掩盖，实际做性能分析应该看 P95/P99——那需要把耗时存进数组再排序，或者直接上 `sort -n` + 取分位行。

## 参考

- [GNU Awk 用户手册](https://www.gnu.org/software/gawk/manual/gawk.html)
- [`awk` POSIX 规范](https://pubs.opengroup.org/onlinepubs/9699919799/utilities/awk.html)
- 相关笔记：[[grep 正则与管道]]
- 相关笔记：[[sed 流编辑与替换]]
- 相关笔记：[[Nginx 日志分析实战]]
