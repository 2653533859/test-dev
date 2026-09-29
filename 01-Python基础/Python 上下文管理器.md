---
created: 2026-07-31
tags: [Python基础/函数式]
---

# Python 上下文管理器

![[assets/context-manager.svg]]
*图示：`with` 进入时调用 `__enter__()` 获取资源、退出时调用 `__exit__()` 释放；无论正常/异常/return，`__exit__` 总会执行。*

> `with` 保证“无论是否异常，资源都被正确释放”。它背后是 `__enter__`/`__exit__` 协议（对应 SETUP_WITH/WITH_CLEANUP 字节码）。测试里管文件、连接、锁、临时环境、mock 还原，全靠它。

## 概念

### 1. 协议：`__enter__` / `__exit__`

上下文管理器是实现这两个方法的对象：
- `__enter__()`：进入 `with` 块时调用，返回值可被 `as` 绑定
- `__exit__(exc_type, exc_val, exc_tb)`：退出时调用（**即使抛异常也会进**）；返回**真值会吞掉异常**，返回 falsy（或 None）则异常继续向外抛

```python
class CM:
    def __enter__(self):
        print("enter"); return self
    def __exit__(self, et, ev, tb):
        print("exit")

with CM() as c:
    print("body")
# enter → body → exit
```

### 2. `with` 的字节码语义

`with` 编译成：先 `SETUP_WITH`（调 `__enter__`，结果压栈），执行块体，最后 `WITH_CLEANUP_START`/`WITH_CLEANUP_FINISH`（调 `__exit__` 并决定异常去留）。所以**资源释放是语言级保证**，不依赖你是否记得写 `finally`。

### 3. `__exit__` 返回真值 = 吞异常

这是个双刃剑：`__exit__` 返回 `True` 会让 `with` 块里的异常**被吞掉**——外面完全不知道出错了。除非明确要忽略某类异常，否则返回 `None`（不吞）。

### 4. `@contextmanager`：用生成器写 CM

`contextlib.contextmanager` 装饰一个含 `yield` 的生成器，把它变成 CM：
- `yield` 之前 = `__enter__`（yield 的值被 `as` 绑定）
- `yield` 之后（通常在 `finally` 里）= `__exit__`

```python
from contextlib import contextmanager
@contextmanager
def temp_env(key, value):
    import os
    old = os.environ.get(key)
    os.environ[key] = value
    try:
        yield                      # 进入块
    finally:
        # 退出清理
        if old is None: os.environ.pop(key, None)
        else: os.environ[key] = old
```

原理：生成器在 `yield` 处暂停把控制权交给 `with` 块，`with` 块结束后生成器从 `yield` 之后恢复，执行清理。`with` 块抛异常时，异常会在 `yield` 处抛出，被 `try/finally` 捕获并清理（异常继续上抛，除非 finally 里处理）。

### 5. `ExitStack`：动态管理多个

`contextlib.ExitStack()` 在运行时按需要进入多个 CM（循环里动态打开文件），退出时逆序清理。

## 用法

```python
from contextlib import contextmanager, suppress, closing

@contextmanager
def temp_env(key, value):
    import os
    old = os.environ.get(key)
    os.environ[key] = value
    try:
        yield
    finally:
        if old is None: os.environ.pop(key, None)
        else: os.environ[key] = old

with temp_env("ENV", "test"):
    print(os.environ["ENV"])

with suppress(FileNotFoundError):     # 吞掉指定异常
    os.remove("maybe_missing.log")
```

## 踩坑

- **`__exit__` 返回 True 会吞异常**：排查时以为没报错其实被吃了；除非明确忽略，否则别返回 True。
- **`contextmanager` 里 yield 前抛异常不清理**：yield 之前（__enter__ 阶段）的异常不会触发清理逻辑，资源可能没创建也就无需释放，但要小心。
- **生成器里 yield 后必须有清理**：靠 `try/finally` 保证 `with` 块异常/提前退出时仍清理；否则资源泄漏。
- **mock 还原**：`patch` 本身是 CM，`with mock.patch(...) as m:` 退出自动还原，比手动 `stop()` 稳。
- **`closing()`**：对非 CM 但有 `close()` 的对象（如某些连接），用 `contextlib.closing` 包成 CM。
- **异常上抛**：CM 不吞异常时，块内异常会正常向外抛，别忘了上层捕获。

## 面试怎么答

上下文管理器通过 `__enter__`/`__exit__` 管理资源生命周期，`with` 是语法糖（编译成 SETUP_WITH + 清理字节码），保证退出时清理、异常也能兜底。手写类或 `@contextmanager` 生成器都能实现——`yield` 前是 `__enter__`、之后是 `__exit__`。

关键坑：① `__exit__` 返回真值会**吞掉异常**，排查时最隐蔽；② `contextmanager` 里清理放 `try/finally`，保证异常/提前退出仍释放；③ `patch` 作为 CM 退出自动还原 mock，比手动 stop 稳。典型用途：文件、连接、锁、临时环境、mock 还原。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/library/contextlib.html
- 相关笔记：[[Python 魔术方法]] [[Python 生成器与迭代器]] [[Python 异常处理]]
