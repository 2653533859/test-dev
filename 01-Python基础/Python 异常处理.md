---
created: 2026-07-31
tags: [Python基础/异常]
---

# Python 异常处理

![[assets/exception-flow.svg]]
*图示：`try/except/else/finally` 的异常分支流程——`finally` 无论是否异常/return 都执行，未捕获异常沿调用栈向上传播。*

> 脚本在 CI 上偶发失败、日志看不出原因时，会读 traceback、会抓、会抛、会兜底资源释放，是把问题真正解决掉的能力。理解异常的类层级、传播机制、异常链，才能写出不吞错、可定位的代码。

## 概念

### 1. 异常是类，有继承体系

所有异常继承自 `BaseException`。日常只应捕获 `Exception` 及其子类：

```
BaseException
├── KeyboardInterrupt   # Ctrl+C
├── SystemExit          # sys.exit()
└── Exception
    ├── ValueError / TypeError / KeyError / IndexError ...
    ├── OSError → FileNotFoundError / PermissionError ...
    └── RuntimeError → RecursionError ...
```

**不要写裸 `except:` 或 `except BaseException:`**——会连 `KeyboardInterrupt`（Ctrl+C 停止）和 `SystemExit` 一起捕获，程序关不掉。

### 2. 异常的传播：沿调用栈向上

`raise exc` 创建异常实例并**中断当前执行**，解释器沿调用栈向上找能处理它的 `except`；找不到就一路冒泡到顶层，打印 traceback 并退出。traceback 从下往上是“调用链”，最上面是你代码里真正抛错的那一行。

### 3. `try/except/else/finally` 的执行流

- `try`：监控可能出错的代码
- `except`：匹配异常类型，命中才执行
- `else`：没异常时才执行（把“可能出错”的范围缩到最小）
- `finally`：**无论成败都执行**（资源释放、锁释放），即使 `try` 里有 `return` 也会先跑 `finally`

### 4. 异常链：`raise ... from ...`

`raise NewExc() from old_exc` 显式设置 **`__cause__`**（因果链），打印时显示“The above exception was the direct cause of the following”。即使不写 `from`，Python 也会自动记录 `__context__`（最近被抑制的异常）。保留异常链能看清根因，而不是只看到最外层的包装异常。

### 5. 自定义异常

继承 `Exception`（或其子类），不要继承 `BaseException`。带上下文信息（code、字段名）便于定位：

```python
class ApiError(Exception):
    def __init__(self, code, msg):
        self.code = code
        super().__init__(f"[{code}] {msg}")
```

## 用法

```python
def call_api():
    raise ApiError(500, "server down")

try:
    call_api()
except ApiError as e:
    print("业务异常:", e.code, e)
else:
    print("请求成功")
finally:
    print("清理资源")

# 包装底层异常，保留根因
try:
    int("abc")
except ValueError as e:
    raise ApiError(400, "参数解析失败") from e
```

## 踩坑

- **裸 `except:`**（无类型）捕获一切包括 `KeyboardInterrupt`，反模式；写具体异常，或至少 `except Exception:`。
- **`except` 顺序**：子类必须写在父类前面，否则 `except Exception:` 先命中，`except ValueError:` 永远到不了（不可达）。
- **`finally` 里的 `return` 覆盖 try 的返回值**：而且会吞掉异常，慎用。
- **`finally` 里又抛异常**：会掩盖 `try` 里原有的异常，异常链上只看到 finally 的。
- **重新抛出用 `raise`（不带参数）**：保留原栈；用 `raise New from Old` 保留因果链，比 `raise New` 信息更全。
- **`logging.exception` 才带 traceback**：普通 `log.error(msg)` 只有信息没栈，定位时信息不足。
- **过度捕获**：`except Exception: pass` 掩盖真 bug；只在“需兜底并记录”的边界捕获，且 log 完整 traceback。

## 面试怎么答

异常是分层级类，继承 `Exception`；日常捕获 `Exception` 子类，别用裸 `except` 或抓 `BaseException`（会连 Ctrl+C 都吞）。traceback 从下往上是调用链，栈最顶的你代码行才是出错点。

`try/except/else/finally` 各司其职，`finally` 保证资源释放（即使 try 有 return）。自定义异常继承 `Exception`。重新抛出用 `raise`（保留栈）或 `raise New from Old` 保留因果链（看清根因）。常见坑：except 顺序（子类在前）、finally 的 return 覆盖返回值、`else` 缩窄监控范围。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/tutorial/errors.html
- 相关笔记：[[Python 上下文管理器]] [[Python logging 日志]]
