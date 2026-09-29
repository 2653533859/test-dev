---
created: 2026-07-31
tags: [Python基础/函数式]
---

# Python 生成器与迭代器

![[assets/iterator-protocol.svg]]
*图示：迭代器协议（`__iter__`/`__next__`）与生成器 `yield` 暂停/恢复的状态机；for 循环本质反复 `next()` 直到 `StopIteration`。*

> 处理大日志、大结果集、流式数据时，生成器把内存从 O(n) 降到 O(1)。理解“迭代器协议”和“生成器靠 yield 暂停/恢复”的底层机制，才明白它为什么省内存、为什么只能遍历一次。

## 概念

### 1. 迭代器协议

“可被 for 遍历”的对象都实现了迭代器协议：
- `__iter__()`：返回迭代器自身（或可迭代对象的迭代器）
- `__next__()`：返回下一个元素；没有时抛 `StopIteration`

`for` 循环就是不断调用 `next()` 直到 `StopIteration`（详见 [[Python 循环语句]]）。

### 2. 可迭代对象 vs 迭代器

- **可迭代对象（iterable）**：有 `__iter__`（如 list/str/dict/生成器），能产出迭代器
- **迭代器（iterator）**：实现了 `__iter__`（返回 self）+ `__next__`，**有状态**，记录“下一个该返回什么”

关键区别：迭代器是“有状态的一次性消费对象”；可迭代对象（如 list）可以反复产生新迭代器（所以能多次遍历），而迭代器遍历完就空了。

### 3. 生成器：带 `yield` 的函数

调用含 `yield` 的函数，**不会执行函数体**，而是返回一个 **generator 对象**（它本身就是迭代器）。生成器状态机：
- `GEN_CREATED`：刚创建
- `GEN_SUSPENDED`：`yield` 暂停处
- `GEN_RUNNING`：正在执行
- `GEN_CLOSED`：已结束

每次 `next()`：`yield` 处**暂停并返回值**，下次从暂停处**恢复**继续执行。`return value` 会抛出 `StopIteration(value)`（一般不要用返回值）。

### 4. 为什么省内存：惰性求值

列表推导 `[x*x for x in range(10**8)]` 一次性在内存里建 1 亿个整数。生成器 `(x*x for x in range(10**8))` **一个都不存**，只在被 `next()` 时算当前一个。处理大文件/流式数据，内存恒定 O(1)。

### 5. 高级：`send` / `throw` / `close` / `yield from`

- `g.send(v)`：把 v 作为当前 `yield` 表达式的**值**传进去（启动要先 `next(g)` 或 `send(None)`）
- `g.throw(exc)`：在暂停处抛异常
- `g.close()`：抛 `GeneratorExit` 结束
- `yield from sub`：把迭代委托给 sub（自动转发 send/throw），写递归/管道更干净

## 用法

```python
# 生成器函数
def read_lines(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            yield line.strip()

# 生成器表达式（惰性）
squares = (x * x for x in range(10**8))   # 不占内存
print(next(squares))                       # 0

# 大文件：一行行读，内存恒定
def bad_cases(log_path):
    for line in read_lines(log_path):
        if "FAIL" in line:
            yield line

# send 双向通信
def counter():
    n = 0
    while True:
        inc = yield n
        n += inc or 1
```

## 踩坑

- **生成器只能遍历一次**：遍历完再 `for` 是空的（迭代器状态耗尽）；要多次用转 `list()` 或重新调用生成器函数。
- **`yield` 返回值机制**：`return v` 在生成器里抛 `StopIteration(v)`，一般别用返回值，用 `yield`。
- **启动 send 要先 next**：`g.send(v)` 前生成器须已在 yield 暂停，否则 `TypeError`；首次用 `next(g)` 或 `send(None)`。
- **`yield from` 转发异常**：委托时子生成器的异常会向上抛，注意捕获位置。
- **生成器里资源释放**：用 `try/finally` 或 `with` 保证 `close()` 时也释放（被 `break` 提前退出会触发 close）。
- **惰性陷阱**：生成器表达式包在 `max()`/`sum()` 里是好的；但包在 `if cond in gen` 里会消耗掉它。

## 面试怎么答

可迭代对象有 `__iter__`、能反复产生迭代器；迭代器有 `__next__`、有状态、一次性消费。生成器是带 `yield` 的函数，调用返回 generator（迭代器），`yield` 暂停/恢复，靠惰性求值省内存（O(1) 处理 O(n) 数据）。

区别：迭代器是更底层协议，生成器是语法糖。坑：① 生成器只能遍历一次；② `return v` 抛 StopIteration，别当返回值用；③ `send` 要先 `next` 启动；④ 大文件/流式用生成器，内存恒定。常见用途：大文件处理、流式 API、管道。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/glossary.html#term-generator
- 相关笔记：[[Python 上下文管理器]] [[Python 装饰器]] [[Python 循环语句]]
