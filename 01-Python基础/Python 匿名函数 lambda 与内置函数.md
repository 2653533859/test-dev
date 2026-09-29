---
created: 2026-07-31
tags: [Python基础/函数式]
---

# Python 匿名函数 lambda 与内置函数

> `lambda` 的限制来自“语句/表达式”之分；`map/filter/sorted/zip/any/all` 这些内置函数是“迭代器 + 协议”思想的集大成。理解它们为什么返回迭代器、为什么有的返回操作数，才算真正会用。

## 概念

### 1. `lambda` 为什么只能是单表达式

`lambda args: expr` 是**匿名函数表达式**（详见 [[Python 基础语法]]）。因为 Python 把“def 函数体”当作语句块，而 `lambda` 要能出现在表达式位置，所以**只能是一个表达式**——不能有赋值语句、不能写 `return`（表达式值即返回）、不能多行、不能写 `if/for` 块（三元 `x if c else y` 是表达式可以用）。复杂逻辑用 `def`。

### 2. `map` / `filter` 返回迭代器（惰性）

`map(f, seq)` / `filter(p, seq)` 返回**迭代器**，不立即计算，逐个 `next()` 时才执行。**只消费一次**——遍历完再 `for` 是空的，需多次用先 `list()`。

```python
squares = map(lambda x: x*x, range(5))   # 迭代器，未计算
print(list(squares))                       # [0,1,4,9,16]
print(list(squares))                       # [] 已耗尽
```

### 3. `sorted` 稳定且返回新列表

`sorted(seq, key=, reverse=)` 用 **Timsort**，是**稳定排序**（相等元素保持原相对顺序），返回**新列表**不动原序列。`list.sort()` 才是原地。

### 4. `any` / `all` 的短路与空序列语义

- `any(i)`：有一个真则真，遇真短路
- `all(i)`：全真才真，遇假短路
- **空序列**：`any([]) == False`、`all([]) == True`（逻辑上“存在量词”对空集假、“全称量词”对空集真——恒真）

### 5. `isinstance` vs `type`

`isinstance(x, int)` 兼容子类（`bool` 是 int 子类也 True）；`type(x) == int` 不兼容子类。判断类型用 `isinstance`。

### 6. `zip` / `enumerate` / `iter` / `next`

`zip` 并行遍历，以**最短序列**结束；`enumerate` 带索引；`iter`/`next` 是迭代协议底层入口。

## 用法

```python
cases.sort(key=lambda c: c.priority)            # lambda 作 key

squares = list(map(lambda x: x*x, range(5)))
evens = list(filter(lambda x: x % 2 == 0, range(10)))

print(any(r.ok for r in responses))
print(all(200 <= r.status_code < 300 for r in responses))

pairs = list(zip(ids, names))
total = sum(r.elapsed for r in responses)
print(isinstance(resp, dict))                    # True
```

## 踩坑

- **`lambda` 不能写语句**：多行/赋值/异常用 `def`；别硬塞进 lambda 牺牲可读性。
- **循环里 lambda 捕获变量是延迟绑定**：`fs=[lambda:i for i in range(3)]` 全拿到最终 i，要 `lambda i=i: i` 立即绑定（见 [[Python 闭包与作用域 LEGB]]）。
- **`map`/`filter` 只消费一次**：需要多次用先 `list()`。
- **`all([])` 为 True、`any([])` 为 False**：断言“全部满足”时空集合是 True（逻辑恒真），别误判。
- **`type` vs `isinstance`**：判断类型用 `isinstance`（兼容子类）；`bool` 是 `int` 子类。
- **`sorted` 返回新列表、`list.sort` 原地**：别写 `xs = xs.sort()`（得 None）。
- **`zip` 最短优先**：长度不一致静默截断，要补齐用 `itertools.zip_longest`。

## 面试怎么答

`lambda` 是单表达式匿名函数，受“语句/表达式”语法限制（不能有赋值/`return`/语句块），复杂逻辑用 `def`，循环里捕获变量有延迟绑定坑。`map`/`filter` 返回惰性迭代器（只消费一次）；`sorted` 稳定排序返回新列表、`list.sort` 原地。

`any`/`all` 短路；`all([])` 为 True、`any([])` 为 False（空全集真）。`isinstance` 兼容子类、判断类型优先于 `type`。`zip` 以最短序列结束。大批量处理优先推导式/生成器（可读且常更快）。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/library/functions.html
- 相关笔记：[[Python 闭包与作用域 LEGB]] [[Python 列表方法与操作]] [[Python 推导式与表达式]]
