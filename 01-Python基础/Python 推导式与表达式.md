---
created: 2026-07-31
tags: [Python基础/语法]
---

# Python 推导式与表达式

## 概念：推导式是「用声明式语法构造容器」

凡是「遍历一个可迭代对象，对每个元素做变换/过滤，收集结果」这种事，Python 用**推导式（comprehension）**一行搞定，比手写 `for` + `append` 更短、且通常更快（在 C 层循环，不反复回调 Python 字节码）。

四种推导式：

| 形式 | 产出 | 语法 |
|------|------|------|
| 列表推导 | `list` | `[expr for x in iter if cond]` |
| 字典推导 | `dict` | `{k: v for ...}` |
| 集合推导 | `set` | `{expr for ...}` |
| 生成器表达式 | 迭代器（惰性） | `(expr for ...)` |

> 生成器表达式是「惰性版列表推导」，不立即算、边取边算（详见 [[Python 生成器与迭代器]]）。

## 用法一：列表推导

```python
nums = [1, 2, 3, 4, 5]

# 平方
squares = [x * x for x in nums]
print(squares)          # [1, 4, 9, 16, 25]

# 带过滤：只要偶数
evens = [x for x in nums if x % 2 == 0]
print(evens)            # [2, 4]

# 变换 + 过滤
pairs = [x for x in range(10) if x % 2 == 0]
```

等价手写 `for`：

```python
squares = []
for x in nums:
    squares.append(x * x)
```

推导式不只是短，还**避免反复 `list.append` 的方法调用开销**，C 层循环更快。

## 用法二：嵌套推导与笛卡尔积

```python
# 扁平化二维列表
matrix = [[1, 2], [3, 4], [5, 6]]
flat = [x for row in matrix for x in row]
print(flat)             # [1, 2, 3, 4, 5, 6]

# 注意顺序：外层循环在前，内层在后
# 等价于：
# for row in matrix:
#     for x in row:
#         flat.append(x)
```

**读嵌套推导的技巧**：把 `for` 子句按出现顺序当成「从外到内的嵌套 for」，最左边/最前的是外层循环。别和生成器的 `for` 顺序搞反。

笛卡尔积（配合 [[Python itertools 模块]] 的 `product` 也可）：

```python
combo = [(a, b) for a in "AB" for b in range(2)]
print(combo)            # [('A',0),('A',1),('B',0),('B',1)]
```

## 用法三：字典推导与集合推导

```python
# 字典推导：单词 → 长度
words = ["apple", "banana", "pear"]
d = {w: len(w) for w in words}
print(d)                # {'apple': 5, 'banana': 6, 'pear': 4}

# 反转键值
rev = {v: k for k, v in d.items()}

# 集合推导：去重 + 变换
s = {len(w) for w in words}      # {5, 6, 4}（集合天然去重）
print(s)
```

注意：**字典推导 `{k: v ...}` 和集合推导 `{expr ...}` 外形都是 `{}`，区别在有冒号 `:`**。空 `{}` 是空字典，不是集合（空集要 `set()`）。

## 用法四：生成器表达式（惰性）

```python
# 列表推导：立即算完，占满内存
big_list = [x * x for x in range(10_000_000)]   # 内存爆炸风险

# 生成器表达式：惰性，按需产出一个
gen = (x * x for x in range(10_000_000))        # 几乎不占内存
print(next(gen))     # 0
print(next(gen))     # 1
```

生成器表达式用 `()`，产出的是迭代器，**边取边算**。适合大数据流、一次性遍历。但它**只能遍历一次**——用完就空了，需要多次用就转 `list` 或用新表达式。

### 函数里直接用生成器表达式省括号

```python
total = sum(x * x for x in range(10))   # 单个参数时可省略外层 ()
print(total)            # 285
```

`sum()`/`max()`/`min()`/`any()`/`all()` 接收单个可迭代参数时，生成器表达式的括号可省，写成 `sum(x for x in ...)`。

## 用法五：条件表达式（三元）在推导里

```python
# x 为偶数取 '偶'，否则取 '奇'
labels = ["偶" if x % 2 == 0 else "奇" for x in range(5)]
print(labels)          # ['偶', '奇', '偶', '奇', '偶']
```

Python 的条件表达式是 `A if cond else B`（**条件在中间**，和很多语言 `cond ? A : B` 顺序不同），在推导式的「产出表达式」位置用。

## 踩坑

1. **推导式里写副作用**：推导式是为「产出集合」设计的，在里面 `print`/`append` 外部列表是反模式，不如用普通 `for`。
2. **生成器表达式只遍历一次**：二次 `for x in gen` 会得到空。需要复用就 `list(gen)` 或重创表达式。
3. **嵌套推导顺序读反**：记住「从左到右 = 从外到内」。写复杂嵌套前先在脑中展开等价 for 循环。
4. **列表推导替代 `map`/`filter` 可读性更好**：社区偏好推导式，但超长推导式（三层嵌套）可读性差，应拆成普通循环。
5. **集合/字典推导混淆 `{}`**：空 `{}` 是 dict；集合推导要有表达式且去重语义；别误以为 `{x for x in ...}` 保留了顺序（集合无序）。
6. **在推导里捕获循环变量做闭包**：和 [[Python 闭包与作用域 LEGB]] 的延迟绑定同理，推导里的变量在推导结束后才定值——不过推导式有独立作用域，变量不会泄漏到外层，这点比 `for` 循环安全。
7. **推导式处理异常**：推导里抛异常会整体中断，没有「跳过坏元素」的机制；需要容错就写 `for` + `try`。

## 面试怎么答

**Q：列表推导和手写 for+append 比有什么优势？**
A：更短、可读性更好、且运行更快——推导式在 C 层循环，避免了反复 Python 层 `list.append` 方法调用开销。

**Q：生成器表达式和列表推导的区别？**
A：列表推导 `[]` 立即算完返回 list，占内存；生成器表达式 `()` 返回惰性迭代器，边取边算，几乎不占内存、只能遍历一次。大数据流用生成器表达式。

**Q：字典推导和集合推导外形都是 {}，怎么区分？**
A：字典推导有 `key: value` 的冒号；集合推导只有单个表达式。空 `{}` 表示空字典，不是集合。

**Q：推导式的执行顺序是？**
A：过滤 `if` 在 `for` 之后（先取元素再判条件）；嵌套推导按 `for` 出现顺序即「从外到内」的嵌套 for 循环；产出表达式在最前。
