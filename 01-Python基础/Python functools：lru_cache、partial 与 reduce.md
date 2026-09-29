---
created: 2026-07-31
tags: [Python基础/函数式]
---

# Python functools：lru_cache、partial 与 reduce

![[assets/lru-cache.svg]]
*图示：`lru_cache` 以参数元组为 key 缓存返回值——命中直接返回、未命中才执行函数并存入，超 `maxsize` 淘汰最久未用；参数必须可哈希。*

## 概念：functools 是「高阶函数工具箱」

`functools` 提供操作「函数」本身的函数。本篇讲三个最常用、也最能体现 Python 函数式思想的东西：

- `lru_cache`：**记忆化**，缓存函数结果，避免重复计算。
- `partial`：**偏函数**，固定部分参数，生成新函数。
- `reduce`：**归约**，把序列「折叠」成单个值。

它们都体现了「函数是对象，可以传递、包装、组合」的一等公民地位（见 [[Python 函数参数与调用]]）。

## 用法一：lru_cache —— 记忆化缓存

```python
from functools import lru_cache
import time

@lru_cache(maxsize=128)
def fib(n: int) -> int:
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)

print(fib(50))    # 瞬间算出，因为中间结果被缓存复用
```

**为什么快**：朴素递归 `fib(50)` 会指数级重复算 `fib(10)` 成千上万次。加 `lru_cache` 后，每次算过的 `(n)` → 结果被存进字典，再遇到相同 `n` 直接返回，复杂度从 O(2^n) 降到 O(n)。

### 原理

`@lru_cache` 把原函数包进一个「带缓存的包装函数」：以**参数元组**为 key（所以参数必须可哈希！），查缓存命中就返回，未命中才调用原函数并存结果。`maxsize` 是缓存容量，`128` 是默认；`maxsize=None` 表示无上限（小心内存）。`cache_info()` 可看命中率：

```python
print(fib.cache_info())
# CacheInfo(hits=48, misses=51, maxsize=128, currsize=51)
```

> `cache_clear()` 清空缓存。注意：`lru_cache` 持有参数的强引用，若缓存「含大对象的参数」且不限制 `maxsize`，可能造成内存泄漏。

## 用法二：partial —— 偏函数

```python
from functools import partial

def power(base: int, exp: int) -> int:
    return base ** exp

square = partial(power, exp=2)     # 固定 exp=2
cube = partial(power, exp=3)

print(square(3))     # 9 = power(3, 2)
print(cube(3))       # 27 = power(3, 3)

# 实战：给 int 指定固定进制
from functools import partial
bases = partial(int, base=2)       # 固定 base=2
print(bases("101"))                # 5（把二进制字符串转 int）
```

`partial(func, *args, **keywords)` 返回一个新可调用对象：调用它时，会把预置的 `args`/`keywords` 拼到实际传入的前面/合并。**位置参数会被前置**，关键字参数合并（同名的以 partial 调用时传入的为准，实际传入可覆盖）。

适合给回调「预设参数」：`btn.on_click(partial(handle, user_id=7))`，避免写 `lambda`。

## 用法三：reduce —— 归约

```python
from functools import reduce

# 把列表「折叠」成单值： (((1*2)*3)*4)*5
product = reduce(lambda a, b: a * b, [1, 2, 3, 4, 5], 1)
print(product)     # 120

# 等价写法：从左到右累积
total = reduce(lambda a, b: a + b, [10, 20, 30], 0)   # 60
```

`reduce(f, iterable, initializer)`：取 `initializer` 作为初始累加值，然后对序列依次 `acc = f(acc, x)`。

**现代风格提醒**：Python 社区一般更推荐用 `sum()`/`min()`/`max()`/`any()` 或显式 `for` 循环替代 `reduce`，因为 `reduce` 可读性较差（Guido 本人就主张不把它放进内置）。但做「自定义归约」（如累积拼接字符串、合并字典）时仍好用。

## 用法四：其他常用 functools

```python
from functools import wraps

# wraps：保留被装饰函数的 __name__/__doc__（详见 [[Python 装饰器]]）
def mydecorator(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return f(*args, **kwargs)
    return wrapper

from functools import singledispatch

# singledispatch：根据第一个参数的类型分派不同实现（函数重载）
@singledispatch
def handler(obj):
    raise NotImplementedError("不支持的类型")

@handler.register(int)
def _(obj: int):
    return f"int: {obj}"

@handler.register(str)
def _(obj: str):
    return f"str: {obj}"

print(handler(1))    # int: 1
print(handler("x"))  # str: x
```

`wraps` 在写装饰器时几乎是必选项（否则被装饰函数丢了元信息）；`singledispatch` 是轻量的单分派多态，比一长串 `if isinstance` 优雅。

## 踩坑

1. **`lru_cache` 的参数必须可哈希**：函数参数里有 `list`/`dict` 等不可哈希对象会直接报 `TypeError: unhashable type`。先转成 `tuple` 或设计可哈希参数。
2. **`lru_cache` 缓存大对象泄漏内存**：`maxsize=None` 且参数含大对象时，缓存无限增长。设合理 `maxsize` 或定期 `cache_clear()`。
3. **`lru_cache` 缓存了「有副作用」的函数**：被缓存后副作用只跑一次，后续命中不重跑——若依赖每次执行（如记日志、发请求），不能用 lru_cache。
4. **`partial` 位置参数顺序**：预置的位置参数会插到实际传入参数最前面，拼错顺序会得到奇怪结果。
5. **`partial` 固定可变默认值**：`partial(f, x=[])` 的 `[]` 在 partial 创建时构造一次，类似默认参数陷阱（见 [[函数默认参数的可变对象陷阱]]）。
6. **`reduce` 没有 initializer 且序列为空**：会抛 `TypeError`。给个 initializer 更安全。
7. **装饰器忘加 `@wraps`**：被装饰函数 `__name__`/`__doc__` 变成 wrapper 的，影响调试和反射。

## 面试怎么答

**Q：lru_cache 的原理和适用场景？**
A：以参数元组为 key 缓存返回值，命中直接返回，避免重复计算。适合纯函数、重复调用多、计算贵的场景（如递归、查表）。注意参数必须可哈希，且要控制 maxsize 防内存膨胀。

**Q：lru_cache 为什么要求参数可哈希？**
A：因为它内部用参数元组做 dict 的 key 来存缓存，不可哈希（如 list/dict）无法做 key，会报 TypeError。

**Q：partial 是做什么的？**
A：偏函数，固定原函数的部分参数生成新函数，常用于预设回调参数。位置参数前置、关键字参数合并，调用时传入的可以覆盖预置的。

**Q：reduce 现在还推荐用吗？**
A：简单归约优先用 `sum`/`min`/`max`/显式循环，可读性更好。复杂自定义归约（如合并字典、累积拼接）仍可用 `functools.reduce`，但代码评审里常被要求改写得更直白。
