---
created: 2026-07-31
tags: [Python基础/IO]
---

# Python 输入、输出与文件读写

> `input`/`print`/`open` 是与外界交换数据的接口，但底层是流、编码、缓冲、迭代器。细节错一个：中文乱码、文件没关泄漏 fd、大文件爆内存。

## 概念

### 1. `input`：从 stdin 读一行，永远返回 str

`input(prompt)` 把提示写到 stdout，从 `sys.stdin` 读一行并 **`rstrip("\n")`**，返回类型**永远是 `str`**。它不是“智能读取类型”，要数字必须 `int(input())`。非交互环境（CI、被 import）调用 `input()` 会 `EOFError`。

### 2. `print`：写 stdout 的可配置接口

`print(*objs, sep=' ', end='\n', file=sys.stdout, flush=False)`：
- `sep` 分隔多个对象；`end` 结尾（默认换行）
- `file` 重定向到任意“有 write 方法的对象”（文件、StringIO）
- `flush=True` **强制刷新缓冲区**，CI/管道里实时看到日志

`print` 内部先 `str()` 各对象再拼接输出。

### 3. `open` 与缓冲 IO

`open(path, mode, encoding=None, buffering=-1)` 返回**文件对象**（Buffered IO）。关键：
- 模式 `r`/`w`（清空）/`a`（追加）/`+`（读写）/`b`（二进制）/`t`（文本，默认）
- **文本模式 `t`**：自动在 str↔bytes 间 encode/decode，并按平台转换换行符（`\n` ↔ Windows 的 `\r\n`）
- **二进制模式 `b`**：直接读写 bytes，不转码、不转换行
- 不指定 `encoding` 时取平台默认（Windows 常 GBK）——中文乱码根源（见 [[Python 编码与 bytes、str]]）

### 4. 文件对象是迭代器（逐行惰性）

`for line in f:` 一行行读，**不一次性载入内存**；`read()` 全读、`readline()` 一行、`readlines()` 全读成列表（大文件别用）。

### 5. `with` 靠上下文管理器关文件

`with open(...) as f:` 退出块时调用 `f.__exit__` → `f.close()`，保证句柄释放。忘记 close 在大量/长运行场景会耗尽文件描述符（fd）。

## 用法

```python
age = int(input("age: "))              # 必须转类型
print("a", "b", sep="-", end="")       # a-b-c（不换行）

with open("cases.json", "r", encoding="utf-8") as f:
    for line in f:                      # 逐行，省内存
        print(line.rstrip())

with open("out.txt", "w", encoding="utf-8") as f:
    f.write("hello\n")

with open("img.png", "rb") as f:        # 二进制
    data = f.read()
```

## 踩坑

- **`input` 返回 str**：直接当数字运算 `TypeError`；非交互环境 `EOFError`。
- **不关文件泄漏 fd**：务必 `with`；忘了 close 在服务器/大循环里耗尽描述符。
- **`w` 模式清空已存在文件**：误用丢数据；只读 `r`、追加 `a`。
- **编码不显式 → 中文乱码**：Windows 默认 GBK，写 `encoding="utf-8"`。
- **`read()` 全读占内存**：大文件用 `for line in f:` 逐行。
- **二进制读到 bytes**：`rb` 下内容不能当 str；要 `.decode("utf-8")`。
- **`print(..., flush=True)`**：CI/管道里实时日志，否则被缓冲延迟。
- **文本模式换行符转换**：Windows 下 `\n` 写文件变 `\r\n`，跨平台比对字节要注意；二进制模式不转换。

## 面试怎么答

`input` 永远返回 str（需转类型，非交互环境 EOFError）。`print` 可配 sep/end/file/flush（flush 实时日志）。`open` 用 `with` 自动关文件防 fd 泄漏；`w` 清空、`r` 读、`a` 追加、`b` 二进制；文本模式自动编解码+换行转换，**不指定 encoding 在 Windows 默认 GBK 会乱码，务必 utf-8**。文件对象是迭代器，大文件逐行 `for line in f:` 省内存，别 `read()` 全读。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/tutorial/inputoutput.html
- 相关笔记：[[Python 编码与 bytes、str]] [[Python pathlib 路径处理]] [[Python 上下文管理器]]
