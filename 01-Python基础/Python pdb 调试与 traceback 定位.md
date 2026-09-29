---
created: 2026-07-31
tags: [Python基础/调试]
---

# Python pdb 调试与 traceback 定位

![[assets/pdb-stack.svg]]
*图示：traceback 从下往上读——最底部是异常类型与出错那一行（现场），往上是调用栈各帧（谁调用了谁）；pdb 用 `w` 看栈、`p` 看变量。*

## 概念：调试的本质是「在运行时观察程序状态」

代码出错或行为不对时，靠「读代码猜」效率低。调试的核心是：**让程序在特定位置暂停，查看变量、单步执行、跟踪调用链**。Python 标准库自带 `pdb`（交互式调试器），无需第三方工具即可深入运行时。

配套技能是**读 traceback（堆栈回溯）**——它是 Python 报错时打印的那一长串，包含了「从哪一行、经哪些函数调用、最终在哪炸」的完整路径。会读 traceback 比会用 pdb 更日常。

## 用法一：设置断点并运行 pdb

```python
import pdb

def buggy(a, b):
    pdb.set_trace()        # 程序跑到这行会暂停，进入 pdb 交互
    return a / b

buggy(1, 0)
```

现代 Python 3.7+ 推荐直接用内置函数，不必 import：

```python
def buggy(a, b):
    breakpoint()           # 等价 pdb.set_trace()，可被环境变量 PYTHONBREAKPOINT=0 关闭
    return a / b
```

运行脚本后，终端停在 `(Pdb)` 提示符，可用命令交互。

### 常用 pdb 命令速查

| 命令 | 含义 |
|------|------|
| `n` (next) | 执行下一行（**不进**函数内部） |
| `s` (step) | 执行下一行（**进**函数内部） |
| `c` (continue) | 继续跑到下一个断点/结束 |
| `l` (list) | 显示当前行附近代码 |
| `p x` | 打印变量 x 的值 |
| `pp obj` | 漂亮打印（多行） |
| `a` (args) | 打印当前函数参数 |
| `w` (where) | 打印当前调用栈 |
| `b 行号` | 在该行设断点 |
| `return` | 执行到当前函数返回 |
| `q` (quit) | 退出调试器 |

```text
> demo.py(3)buggy()
-> return a / b
(Pdb) p a, b
(1, 0)
(Pdb) n
ZeroDivisionError: division by zero
```

当程序暂停时，你可以用 `p` 看任意变量、修改变量（在 pdb 里直接赋值），再 `c` 继续——这是定位「变量怎么变成错的」的最快方式。

## 用法二：事后调试（post-mortem）

程序已经崩了，你想立刻在「崩溃现场」检查变量：

```python
import pdb, traceback

try:
    buggy(1, 0)
except Exception:
    traceback.print_exc()        # 打印完整堆栈
    pdb.post_mortem()            # 进入 pdb，停在异常抛出处
```

`pdb.post_mortem()` 让你在异常发生的那一帧检查当时的局部变量，不用重新跑、不用提前埋断点。生产/脚本崩了排查第一现场极有用。

## 用法三：命令行直接调试脚本

```bash
python -m pdb demo.py        # 以 pdb 启动脚本，从第一行开始可单步
```

适合「想从入口一步步跟」的调试。配合 `b 行号` 设断点、`c` 跑到位。

## 用法四：读懂 traceback

```text
Traceback (most recent call last):
  File "demo.py", line 10, in <module>
    main()
  File "demo.py", line 7, in main
    result = buggy(1, 0)
  File "demo.py", line 4, in buggy
    return a / b
ZeroDivisionError: division by zero
```

**读法（从下往上）**：
1. **最底部是「异常类型 + 信息」**：`ZeroDivisionError: division by zero` —— 错的类型和原因。
2. **往上每一段是一个「调用帧」**：`File ... line ... in 函数名` + `-> 该行代码`。最上面是入口，最靠近底部的是「最后执行到的那行」（出错现场）。
3. **`most recent call last`** 表示列表是按「最早调用 → 最近调用」排列，所以**出错的代码在最底部那帧**。

定位 bug 的套路：**先看最底部异常类型，再读最底部那帧的文件/行/代码**，多半就在那一行或它的直接原因。若该行调用了别的函数，再往上看一帧找「传入了什么错参数」。

## 用法五：打印调用栈（非交互）

```python
import traceback

def f():
    traceback.print_stack()     # 打印当前调用栈，看谁调用了我

def g():
    f()

g()
```

不用进 pdb 也能把当前调用链打出来，适合快速确认「这个函数是怎么被调到的」。

## 踩坑

1. **忘记 `n` 和 `s` 的区别**：`n` 把函数当一行跳过，`s` 才进函数内部。想看子函数逻辑用 `s`，否则用 `n` 快速过。
2. **`breakpoint()` 留在生产代码**：提交前务必删掉，或用 `PYTHONBREAKPOINT=0` 全局禁用；否则脚本会卡在交互等输入。
3. **在 pdb 里改了变量以为改了源码**：pdb 里的赋值是运行时改内存，不写回 `.py` 文件，重启后又恢复原样。它只用于观察/临时试探。
4. **不看 traceback 直接猜**：异常信息已告诉你类型、行号、调用链，先读再动手，比盲目加 print 高效。
5. **`post_mortem` 在异常被吞掉时没用**：若有 `except: pass` 吞掉异常，程序没「崩」，pdb 不会触发，也看不到现场。至少 `logging.exception` 或 `raise`。
6. **把 `traceback.print_exc` 的异常重新 `raise` 时注意异常链**：用 `raise ... from e` 保留原链（见 [[Python 异常处理]]），避免丢失根因。
7. **多线程/异步里 pdb 交互混乱**：pdb 是单线程交互式，线程池/asyncio 里断点可能卡住或输出错乱。这类场景优先用日志 + traceback，而非交互断点。

## 面试怎么答

**Q：怎么用 pdb 调试？**
A：在代码里 `breakpoint()`（或 `pdb.set_trace()`）设断点，运行后进入 `(Pdb)` 交互；用 `n` 单步（不进函数）、`s` 单步（进函数）、`p 变量` 查看、`c` 继续、`b 行号` 设断点、`q` 退出。也可用 `python -m pdb script.py` 从入口跟。

**Q：什么是 post-mortem 调试？**
A：程序崩后调用 `pdb.post_mortem()`，在异常抛出的那一帧进入调试器，检查当时的局部变量，无需重新跑或提前埋点，适合排查第一现场。

**Q：怎么读 traceback？**
A：从下往上读——最底部是异常类型和原因；其上是出错现场那一行（文件/行号/代码）；再往上是调用链各帧。先确认异常类型，再看出错那行及其传入参数，多数 bug 就在那。

**Q：breakpoint() 和 pdb.set_trace() 区别？**
A：两者都触发 pdb 断点。`breakpoint()` 是 Python 3.7+ 内置函数，可用环境变量 `PYTHONBREAKPOINT=0` 全局禁用，更适合留在代码里；`pdb.set_trace()` 是旧的、强制进入 pdb。
