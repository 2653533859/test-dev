---
created: 2026-07-31
tags: [Python基础/函数式]
---

# Python 装饰器

![[assets/decorator-stack.svg]]
*图示：`@` 等价于 `func = deco(func)`，多个装饰器自下而上包裹；运行时调用顺序由外到内，`@wraps` 保留元信息。*

> 装饰器 = 高阶函数 + 语法糖，是“在不改原函数代码的前提下加功能”的标准手段。pytest 的 fixture、`mock.patch`、Flask 的路由全是它。理解执行时机、`functools.wraps` 为什么必须、带参装饰器的三层嵌套，才算真正会用。

## 概念

### 1. `@` 是语法糖：`func = decorator(func)`

`@decorator` 贴在 `def f` 上，等价于 `f = decorator(f)`。所以装饰器本质是**接收函数、返回函数**的可调用对象。

```python
def deco(f):
    def wrapper(*a, **k):
        return f(*a, **k)
    return wrapper

@deco
def f(): ...
# 等价于 f = deco(f)
```

### 2. 执行时机：在 import（def）时，不是调用时

装饰器在**模块加载、函数定义时**就执行了——它立即用原函数构造出 wrapper 并替换。所以：
- 装饰器里的“重活”（连接数据库、复杂计算）会在**导入时**就跑，拖慢启动
- 带参装饰器的外层在定义时执行；每次调用只跑 wrapper

### 3. 为什么必须 `functools.wraps`

`wrapper` 是一个**全新的函数对象**，它**没有**原函数的元信息（`__name__`/`__doc__`/`__module__`/`__qualname__`/`__annotations__`）。后果：
- 日志打印函数名变成 `wrapper`
- `mock.patch("module.f")` 按名找不到（因为名字变了）
- pytest 的节点 id、报错位置都显示 `wrapper`

`functools.wraps(func)`（即 `update_wrapper`）把原函数的这些元信息**复制**到 wrapper 上：

```python
import functools
def deco(f):
    @functools.wraps(f)
    def wrapper(*a, **k):
        return f(*a, **k)
    return wrapper
```

### 4. 带参装饰器：三层嵌套

当装饰器本身要接收参数（`@retry(3)`），结构是三层：外层收参数 → 返回真正的装饰器 → 装饰器收函数返回 wrapper。

```python
def retry(times=3):
    def deco(f):
        @functools.wraps(f)
        def wrapper(*a, **k):
            for i in range(times):
                try:
                    return f(*a, **k)
                except Exception:
                    if i == times - 1:
                        raise
        return wrapper
    return deco
```

### 5. 叠加顺序

`@a @b def f` 等价于 `f = a(b(f))`——**从下往上包**，b 先包 f，a 再包 b(f)。执行时 a 在外层先进入。

### 6. 类装饰器

装饰器也可以是类（实现 `__call__`），或类方法上的装饰器（`@property`/`@classmethod` 本质是描述符，见 [[Python 描述符 descriptor]]）。

## 用法

```python
import time, functools

def timer(f):
    @functools.wraps(f)
    def wrapper(*a, **k):
        start = time.perf_counter()
        try:
            return f(*a, **k)
        finally:
            print(f"{f.__name__} 耗时 {time.perf_counter()-start:.3f}s")
    return wrapper

@timer
def slow():
    time.sleep(0.1)
```

## 踩坑

- **忘了 `@functools.wraps`**：函数名/文档/签名全变 `wrapper`，日志、mock、测试定位全乱——这是头号坑。
- **装饰器在导入时执行**：带参装饰器若有重活（连库、算东西），会拖慢启动，且 import 失败会整体崩。
- **异常被吞**：包装时若 catch 了异常却不重抛，原错误消失；重试装饰器要 `raise` 最后的异常。
- **`ThreadPoolExecutor` 里装饰器抛的异常**：要 `fut.result()` 才重新暴露，否则静默丢失。
- **叠加顺序理解错**：`@a @b` 是 `a(b(f))`，a 在外；调试时从外往里看调用栈。
- **类方法装饰器与描述符混用**：`@property` 等本质是描述符，和函数装饰器机制不同，别套用同一套心智模型。

## 面试怎么答

装饰器是高阶函数，`@` 是 `f = deco(f)` 的语法糖。核心点：① 执行时机在**导入/定义时**，不是调用时，重活会拖慢启动；② 必须 `@functools.wraps`，否则 wrapper 丢失原函数元信息（`__name__`/`__doc__`），导致日志、mock.patch、pytest 全部错乱；③ 带参装饰器三层嵌套（收参数→装饰器→wrapper）；④ 叠加 `@a @b` = `a(b(f))`，从下往上包。常见用途：日志、计时、鉴权、重试、缓存、pytest fixture。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/glossary.html#term-decorator
- 相关笔记：[[Python 闭包与作用域 LEGB]] [[Python 函数参数与调用]] [[Python 描述符 descriptor]]
