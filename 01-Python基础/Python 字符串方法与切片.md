---
created: 2026-07-31
tags: [Python基础/文本]
---

# Python 字符串方法与切片

> 字符串是“不可变的字符序列”，这个底层事实决定了它的几乎所有行为：为什么不能 `s[0]='x'`、为什么切片会新建对象、为什么循环拼接慢、为什么有 intern 驻留。接口文本处理、日志解析全建立在这之上。

## 概念

### 1. 字符串是不可变序列

`str` 在底层是**连续的 Unicode 码点数组**，创建后不可变（和 tuple 类似）。这意味着：

- 不能 `s[0] = 'x'`（`TypeError`）；“修改”必须新建字符串
- 索引 `s[i]` O(1)；切片 `s[a:b]` **新建**一个字符串（因为不可变，不能返回“原数组的视图”）
- 拼接 `s + t` 会创建新字符串并拷贝两边内容

### 2. 为什么循环拼接慢

```python
s = ""
for ch in many_chars:
    s += ch          # 每轮都新建字符串 + 全量拷贝
```

每轮 `+=` 都是“新建 + 拷贝”，总时间 O(n²)。正确做法：`chars = []; chars.append(...); "".join(chars)`（一次拷贝）。

### 3. 切片与索引的行为差异

- 索引越界 `s[100]` → `IndexError`
- 切片越界 `s[100:]` → 返回 `""`（不报错，因为切片结果本就是“可能为空的新串”）

### 4. 字符串驻留（intern）

短字符串/标识符会被解释器 intern（复用同一对象），所以 `a="ab"; b="ab"; a is b` 常为 `True`。这是性能优化（字典键查找、比较更快），但**不能依赖**来做值比较（见 [[Python 运算符]]）。

### 5. 方法速查（常用）

- 查找：`find`(无则 -1) / `index`(无则抛) / `rfind` / `count` / `startswith` / `endswith`
- 变形：`upper`/`lower`/`title`/`capitalize`/`swapcase`/`strip`/`lstrip`/`rstrip`/`center`/`ljust`/`rjust`/`zfill`
- 处理：`split`/`rsplit`/`splitlines`/`join`/`replace`/`translate`/`expandtabs`
- 判断：`isdigit`/`isalpha`/`isalnum`/`isnumeric`/`islower`/`isupper`/`isspace`/`istitle`
- 编码：`encode`；`decode` 是 bytes 方法

### 6. 原始字符串 `r"..."`

`r"\n"` 里的 `\` 不当转义，正则、Windows 路径首选，避免写 `"\\d+"`。

## 用法

```python
s = "  Hello, World!  "
print(s.strip())                       # "Hello, World!"
print(s.split(","))                    # ['  Hello', ' World!  ']
print("-".join(["a", "b", "c"]))       # a-b-c
print(s.lower().startswith("  hello")) # True
print(s.replace("World", "Python"))

text = "abcdef"
print(text[1:4])     # bcd
print(text[::-1])    # fedcba（反转，新建串）

import re
pat = r"\d+\.\d+"    # 原始串，无需 \\ 
```

## 踩坑

- **字符串不可变**：`s[0] = "x"` 直接 TypeError；要改转 `list(s)` 再改或重建。
- **切片越界不报错、索引越界才报错**：`s[100:]` 返回 `""`，容易被当成“空结果”掩盖 bug。
- **`split` 默认按空白且合并连续空白**：`"a  b".split()` → `['a','b']`；按固定分隔符用 `split(",")`，空串要过滤。
- **`find` 返回 -1、`index` 抛异常**：按“找不到要不要报错”选；`if x in s` 比 `if s.find(x)>=0` 清晰。
- **循环 `+=` 拼接 O(n²)**：大量拼接用 `list` + `join`。
- **`r"\"` 非法**：原始串不能以单个 `\` 结尾；Windows 路径用 `r"C:\temp"` 且别以 `\` 结尾。
- **`len()` 按码点不是字节**：中文字节宽度用 `len(s.encode("utf-8"))` 之类。

## 面试怎么答

str 是不可变序列（连续码点数组）：不能原地改、切片/拼接都新建对象、所以循环 `+=` 是 O(n²)（用 list+join）。切片越界返回空串、索引越界才报错。方法链 `s.strip().split().lower()` 很常用；`find` 返回 -1、`index` 抛异常；`join` 是字符串方法（`"".join(list)`）。原始串 `r"..."` 用于正则/路径。文本判断优先 `in` 和 `startswith/endswith`。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/library/stdtypes.html#string-methods
- 相关笔记：[[Python 字符串格式化与 f-string]] [[Python 编码与 bytes、str]] [[Python 正则表达式深入：分组、断言与贪婪]]
