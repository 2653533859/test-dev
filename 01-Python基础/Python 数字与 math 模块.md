---
created: 2026-07-31
tags: [Python基础/数据类型]
---

# Python 数字与 math 模块

> 数字看起来简单，但“浮点为什么不准”“`round(0.5)` 为什么是 0”都来自底层数值模型。接口断言、金额比对、状态码运算天天和数字打交道，理解 IEEE 754 和任意精度整数是基本功。

## 概念

### 1. 三种数字类型

- **`int`：任意精度整数**。Python 的 int 没有固定位数（C 层用数组存多“数字位”），所以 `10 ** 100` 也不会溢出，只受内存限制。代价是大整数运算比固定位数慢。
- **`float`：双精度浮点（IEEE 754）**。`float` 用 64 位表示（1 符号 + 11 指数 + 52 尾数），**绝大多数十进制小数无法被二进制精确表示**，所以 `0.1 + 0.2 != 0.3`。
- **`complex`：复数** `3+4j`，测试里较少用。

### 2. 为什么 `0.1 + 0.2 != 0.3`

`0.1` 在二进制里是无限循环小数 `0.0001100110011...`，float 只能截断存储，于是 `0.1` 实际存的是 `0.1000000000000000055...`。两个近似值相加，误差累积，结果自然不等于 `0.3` 的近似表示。这是**所有遵循 IEEE 754 的语言的通病**，不是 Python bug。

正确做法：
- 比较用 `math.isclose(a, b, rel_tol=1e-9)`（允许相对误差）
- 金额用 `decimal.Decimal`（十进制精确）

### 3. `round` 的银行家舍入（round half to even）

`round(x)` 默认对 `.5` 向**最近的偶数**取整，不是“四舍五入进一”：

```python
round(0.5)    # 0
round(1.5)    # 2
round(2.5)    # 2
```

原因：统计上，向偶数取整能让大量 `.5` 的累积偏差更小（避免系统性偏高）。所以别假设 `round` 总是“进一”。

### 4. `Decimal`：十进制精确

`decimal.Decimal` 用十进制模型表示数字，**适合金额**。必须用**字符串**构造（`Decimal("0.1")`），否则会先经历 float 误差：

```python
from decimal import Decimal
Decimal("0.1") + Decimal("0.2")     # Decimal('0.3') 精确
Decimal(0.1) + Decimal(0.2)         # 仍带误差
```

### 5. 进制与转换

`0b`/`0o`/`0x` 字面量；`bin()/oct()/hex()` 转出；`int("1010", 2)` 按基转换。`bool` 是 `int` 的子类（`True == 1`、`True + 1 == 2`）。

### 6. `math` 模块要点

`sqrt/floor/ceil/abs/pow/pi/e/gcd/isclose/comb/perm` 等。`math.isclose` 是浮点比较的正确姿势。

## 用法

```python
import math
from decimal import Decimal

print(0.1 + 0.2)                      # 0.30000000000000004
print(math.isclose(0.1 + 0.2, 0.3))   # True

print(Decimal("0.1") + Decimal("0.2"))  # 0.3

print(bin(10), oct(10), hex(10))       # 0b1010 0o12 0xa
print(int("1010", 2))                 # 10

print(round(0.5), round(1.5), round(2.5))  # 0 2 2
print(math.gcd(12, 18))               # 6
```

## 踩坑

- **`0.1 + 0.2 != 0.3`**：浮点二进制误差；断言金额/比例用 `math.isclose` 或 `Decimal`，别直接 `==`。
- **`round` 银行家舍入**：`.5` 向偶数，`round(0.5)=0`；需要“四舍五入进一”自己实现。
- **`Decimal` 用字符串构造**：`Decimal(0.1)` 先被 float 污染，要 `Decimal("0.1")`。
- **`bool` 是 `int` 子类**：`True + 1 == 2`、`[0, 1, 2][True] == 2`；把 bool 当索引/数字用会出反直觉结果。
- **`int(True)` 是 1**：统计 `sum(flags)` 时若 flags 是 bool 列表能直接求和，但语义要清楚。
- **除零**：`x / 0` → `ZeroDivisionError`；`math.sqrt(-1)` → `ValueError`（不是 complex）。
- **大整数性能**：`int` 任意精度，但超大数（千位数）运算比固定位数慢，压测循环里别用超大幂运算。

## 面试怎么答

Python 数字：`int` 任意精度（不溢出，受内存限）、`float` 是 IEEE 754 双精度（二进制表示导致 `0.1+0.2≠0.3`）、`complex` 复数。`float` 误差是通病，比较用 `math.isclose` 或金额用 `Decimal`（务必字符串构造）。

`round` 是银行家舍入（`.5` 向偶数），不是简单四舍五入——`round(0.5)=0`。`bool` 是 `int` 子类（`True==1`）。进制转换 `int("1010", 2)`。面试常考：为什么浮点不准、怎么安全比较、Decimal 用途、round 行为。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/library/math.html
- 相关笔记：[[Python 运算符]] [[Python 编码与 bytes、str]] [[Python 可变对象与不可变对象]]
