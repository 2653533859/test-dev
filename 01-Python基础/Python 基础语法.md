---
created: 2026-07-31
tags: [Python基础/语法]
---

# Python 基础语法

> “缩进即语法”不是风格偏好，而是 Python 刻意的设计选择。理解它和“语句/表达式”“字节码编译”“命名空间”的关系，才能解释很多新人踩的坑。

## 概念

### 1. 为什么用缩进划分代码块

多数语言用 `{}` 划分块，Python 用**缩进**。设计动机：① 强制统一风格，消除“括号风格之争”；② 视觉上代码块与逻辑块一致，可读性好；③ 编译器不需要括号配对，语法更简单。

代价：缩进错了就是**语法错误**（`IndentationError`/`TabError`），不能“逻辑对但缩进错”。

### 2. 语句 vs 表达式（这解释了 lambda 的限制）

Python 是“语句为主”的语言：
- **表达式**：能算出值的片段（`a + b`、`func()`、`x if c else y`）
- **语句**：做动作的完整行（`if`/`for`/`return`/`赋值`）

`lambda` 是**匿名函数表达式**，因为要能放在表达式位置（如 `sorted(key=lambda x: x.v)`），所以**只能是单个表达式，不能包含语句**（不能有 `=` 赋值语句、`return`、`if` 块等）。要写多行逻辑用 `def`。3.8 的海象 `:=` 是唯一让“赋值”出现在表达式里的口子。

### 3. 编译执行模型

CPython 不是“边读边执行”源码，而是先把源码**编译成字节码（`.pyc`）**再在虚拟机上执行。`python script.py` 的流程：解析 → 编译成 `codeobject` → 执行。`import` 的模块会缓存 `.pyc` 加速。

### 4. 标识符、关键字、代码块

- 标识符：字母/下划线开头、区分大小写，不能是关键字（`keyword.kwlist` 共 35 个）
- 关键字是不可赋值的保留字（`class = 1` → SyntaxError）；`True/False/None` 首字母大写且不可重绑
- 代码组：以 `:` 结尾的复合语句（if/for/def/class）下行必须缩进
- 多行：`\` 续行，或在 `()`/`[]`/`{}` 内天然换行（推荐后者）
- `pass`：空语句占位，保持语法完整（如 `if x: pass`）

## 用法

```python
import keyword
print(keyword.kwlist)          # 35 个关键字

def add(a, b):
    return a + b               # 缩进决定归属

config = {                     # 括号内自动续行
    "host": "127.0.0.1",
    "port": 443,
}

xs = [1, 2, 3]
y = [v * 2 for v in xs]        # 推导式是表达式
```

## 踩坑

- **混用 Tab 与空格** → `TabError`；编辑器统一“4 空格替换 Tab”。
- **冒号后忘缩进** → `IndentationError: expected an indented block`。
- **中文标识符语法允许但严禁**：`变量 = 1` 能跑，但破坏协作、工具链、可读性。
- **把关键字当变量名** → `SyntaxError`；`class`/`def`/`lambda` 等都不能作名。
- **三引号≠注释**：紧贴 def/class/module 首行会变成 docstring（`__doc__` 可读），纯多行注释用多个 `#`。
- **`\` 续行后行尾有空格/注释** → 续行失效，报错；括号内换行无此问题。
- **缩进不一致**：同一块混用不同缩进量会 `IndentationError`。

## 面试怎么答

Python 用缩进划分代码块（不是 `{}`），是刻意设计：强制风格统一、语法简单、可读性好；代价是缩进错直接语法错误。标识符字母/下划线开头、区分大小写、不能是关键字。

底层：源码先编译成字节码（`.pyc`）再执行。`lambda` 只能是单表达式（因为 Python 语句/表达式区分，lambda 是表达式不能含语句）。多行用括号最稳。核心区别于 C/Java：缩进是语法一部分。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/reference/lexical_analysis.html
- 相关笔记：[[Python 运算符]] [[Python 函数参数与调用]]
