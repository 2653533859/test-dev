---
created: 2026-07-31
tags: [Python基础/语法]
---

# Python 循环语句

> `for` 循环的本质是“迭代协议”，不是 C 风格的索引遍历。`range` 是惰性序列、`break/else` 的行为、`enumerate/zip` 都是迭代器——理解协议才能解释遍历删元素为什么漏删。

## 概念

### 1. `for` 的本质：迭代协议

`for x in seq:` 底层等价于：

```python
_it = iter(seq)              # 调用 seq.__iter__() 拿到迭代器
while True:
    try:
        x = next(_it)        # 调用 _it.__next__()
    except StopIteration:
        break
    # 循环体
```

所以**任何实现了迭代协议的对象都能被 for 遍历**：list/dict/str/生成器/文件对象…`next()` 耗尽时抛 `StopIteration`，`for` 捕获它来结束。

### 2. `range` 是惰性序列对象

`range(10**8)` **不占 1 亿个整数内存**——它只是个对象，记录 start/stop/step，按需算第 i 个值。`range` 支持索引、len、`in`，但不展开成列表（要 `list(range(n))` 才展开，别对超大 range 这么干）。

### 3. `while` 与退出路径

`while cond:` 条件为真就重复。**必须保证有退出路径**（条件会变 False、或 `break`），否则死循环。CI 里死循环会卡到超时。

### 4. `break` / `continue` / `pass` / `else`

- `break`：跳出整个循环
- `continue`：跳过本次剩余，进入下一轮
- `pass`：空操作占位
- 循环 `else`：**未被 break 正常结束**时才执行（被 break 跳出则不执行）

### 5. 遍历中删除元素为什么漏删

`for x in lst` 用的是 list 的迭代器，它内部维护一个**当前索引**。删除元素会让后续元素前移，但迭代器索引照常 +1，于是“跳过”了被移动的那个元素。修复：遍历副本 `for x in lst[:]`、倒序遍历、或用列表推导重建。

## 用法

```python
# range 半开区间、惰性
for i in range(3):            # 0 1 2
    print(i)

for i, case in enumerate(cases, 1):    # 带索引
    print(i, case.name)

for code, msg in zip(codes, msgs):      # 并行遍历
    print(code, msg)

n = 3
while n > 0:
    n -= 1

# 循环 else：没 break 才执行
for x in items:
    if x.bad:
        break
else:
    print("全部正常")
```

## 踩坑

- **`range` 左闭右开**：`range(1, 5)` 是 1,2,3,4；想含 5 用 `range(1, 6)`。
- **遍历中删元素漏删**：用 `for x in lst[:]`（副本）/ 倒序 / 列表推导。
- **`while` 死循环**：条件恒真无退出，CI 卡死；加重试上限或超时。
- **`zip` 以最短序列结束**：长度不一致静默截断；补齐用 `itertools.zip_longest`。
- **循环 `else` 易误解**：只有没 `break` 才执行；多数场景用标志位更清晰。
- **大文件 `readlines()` 全读占内存**：逐行用 `for line in f:`（文件对象是迭代器，惰性）。
- **`enumerate` 默认从 0**：要行号从 1 用 `enumerate(lst, 1)`。

## 面试怎么答

`for` 本质走迭代协议：`iter(seq)` 拿迭代器，`next()` 取值，`StopIteration` 结束。`range` 是惰性序列（不展开、省内存）。遍历删除元素会漏删（迭代器索引错位），用副本/倒序/推导式。

`while` 必须有退出路径防死循环。`zip` 以最短序列结束。`break/continue/pass` 各司其职；循环 `else` 仅当**未被 break** 才执行。大循环优先推导式/生成器。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/tutorial/controlflow.html#for-statements
- 相关笔记：[[Python 推导式与表达式]] [[Python 生成器与迭代器]] [[Python itertools 模块]]
