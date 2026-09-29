---
created: 2026-07-31
tags: [Python基础/函数]
---

# Python 函数参数与调用

![[assets/call-by-object.svg]]
*图示：函数按对象引用传参——可变对象在函数内修改会影响调用方，不可变对象重新绑定不影响调用方。*

> 函数调用时参数怎么“绑”到形参上，是 Python 最精巧的机制之一。位置参数、`*args`、`**kwargs`、关键字-only、解包——它们不是语法花活，而是“按对象引用传参”这一底层模型在接口层面的展开。

## 概念

### 1. 调用语义：call by object reference

传入函数的不是值、也不是指针，而是**实参对象的一个引用**（详见 [[Python 可变对象与不可变对象]]）。形参名在调用时被绑定到这些引用上。这决定了：改可变对象对调用方可见，重绑定不可变对象不可见。

### 2. 参数绑定的完整顺序

函数定义里，参数必须按以下顺序声明，解释器据此决定每个实参“落到哪个形参”：

```
位置参数(positional)
  → 默认参数(default)
    → *args（收集多余位置参数为元组）
      → 关键字-only（* 之后，只能按名传）
        → **kwargs（收集多余关键字参数为字典）
```

```python
def f(a, b=2, *args, c=10, **kwargs):
    ...
```

- `a`：必选位置参数
- `b=2`：位置或关键字，带默认值
- `*args`：吃掉的剩余位置参数 → 元组
- `c=10`：`*` 之后是**关键字-only**，只能 `f(..., c=...)` 传
- `**kwargs`：剩余关键字参数 → 字典

### 3. 调用端的解包

```python
def f(a, b, c): ...

f(*[1, 2, 3])                 # * 解包位置参数 → a=1,b=2,c=3
f(**{"a": 1, "b": 2, "c": 3}) # ** 解包关键字参数
```

`*iterable` 把可迭代对象的元素展开成位置参数，`**mapping` 把字典展开成关键字参数。

### 4. 为什么有“关键字-only”参数

把常用参数放前面，把可选/危险参数用 `*` 隔开强制命名，能避免“位置传参的脆弱性”——调用方改写顺序也不会传错。典型如 `requests` 的 `requests.get(url, *, timeout=...)`。

### 5. 参数求值时机

实参在**调用时**从左到右逐个求值（不是先全求完再传），这让 `*args` 里能包含会抛错的表达式并精确定位。

## 用法

```python
def request(method, url, *args, timeout=10, **kwargs):
    print(method, url, args, timeout, kwargs)

request("GET", "/api", 1, 2, timeout=5, headers={"x": 1})
# GET /api (1, 2) 5 {'headers': {'x': 1}}

# 关键字-only：强制写清楚，可读性更好
def connect(host, *, port=443, ssl=True):
    ...

# 解包调用
params = ["a", "b"]
opts = {"timeout": 3}
request("POST", "/x", *params, **opts)
```

## 踩坑

- **顺序写错直接 `SyntaxError`**：默认参数必须在 `*args` 前；`**kwargs` 必须最后；`def f(**k, a)` 非法。
- **`*args` 吃掉位置参数**：想在 `*args` 之后保留一个带默认值的参数，必须把它声明为关键字-only（`*` 之后），否则它会被 `*args` 吞掉。
- **`**kwargs` 转发兼容性**：上游传了下游不认识的 key，`func(**kwargs)` 会 `TypeError`；用 `kwargs.pop("key", default)` 显式取出或确认下游签名。
- **可变默认参数的经典坑**：默认参数在 `def` 时求值一次（见 [[函数默认参数的可变对象陷阱]]），别用 `[]`/`{}` 当默认值。
- **解包数量不匹配**：`f(*[1,2,3,4])` 给只接受 3 个形参的函数会 `TypeError: too many positional arguments`。
- **`*` 单独分隔符**：`def f(a, *, b)` 的 `*` 不是参数，只是“后面的都是关键字-only”的标记。

## 面试怎么答

参数声明顺序固定：必选位置 → 默认 → `*args` → 关键字-only（可带默认）→ `**kwargs`。底层是 call by object reference，参数在调用时按顺序绑定到形参引用上。

`*args`/`**kwargs` 用来写“接收任意参数”的包装器（装饰器、请求封装）；`*` 后的参数是关键字-only，强制命名调用、可读性更好。`*` 解包位置参数、`**` 解包字典。经典坑：默认参数在 def 时求值（可变默认值串味）、顺序写错 SyntaxError、`**kwargs` 转发可能因多余 key 报错。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/reference/compound_stmts.html#function-definitions
- 相关笔记：[[Python 可变对象与不可变对象]] [[函数默认参数的可变对象陷阱]] [[Python 闭包与作用域 LEGB]]
