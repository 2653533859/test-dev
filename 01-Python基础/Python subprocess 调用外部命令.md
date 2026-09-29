---
created: 2026-07-31
tags: [Python基础/标准库]
---

# Python subprocess 调用外部命令

> 测试里经常要起命令行工具（adb、curl、docker、git）。`subprocess` 是官方推荐的子进程调用方式，理解“管道缓冲阻塞”“文本模式解码”“shell 注入”这些机制，才不会卡死或中招。

## 概念

### 1. 替代 `os.system`

`os.system(cmd)` 只能返回退出码、且用 shell 字符串、不安全。`subprocess` 用 `fork`+`exec`（Unix）创建子进程，能精细控制输入/输出/环境变量/超时。

### 2. `run` / `Popen` 的区别

- `subprocess.run(...)`：高层便捷封装，等到进程结束返回 `CompletedProcess`（含 `returncode`/`stdout`/`stderr`）。大多数场景用它。
- `subprocess.Popen(...)`：底层，返回 Popen 对象，可交互（`.communicate()`/`.poll()`/`.wait()`/`.kill()`），适合流式/长时间进程。

### 3. 管道阻塞：最隐蔽的坑

`stdout=PIPE` 时，子进程把输出写进**操作系统管道**。管道有固定缓冲，子进程写满后会**阻塞等待读取**。如果你不读管道（也没重定向到文件/DEVNULL），子进程就卡住，父进程等它也卡住——**死锁**。所以：要么消费输出（`capture_output`/`communicate()`），要么重定向到文件或 `DEVNULL`。

### 4. `text=True` 解码 bytes → str

不指定 `text=True` 时，`stdout`/`stderr` 是 **bytes**。指定 `text=True`（或 `encoding="utf-8"`）后按 locale/指定编码解码成 str。中文不指定会按默认编码（Windows GBK）出错。

### 5. `shell=True` 的安全红线

`shell=True` 通过系统 shell 执行命令字符串，能写管道/通配符，但**命令里拼用户输入 = 命令注入**（如 `; rm -rf /`）。自动化平台尤其危险。原则：能用列表形式（`["ls","-l"]`）就别用 shell。

### 6. `check` 与 `timeout`

`check=True`：非零退出码抛 `CalledProcessError`（含 returncode/stdout/stderr）。`timeout`：超时抛 `TimeoutExpired` 并杀进程，避免脚本卡死。

## 用法

```python
import subprocess

r = subprocess.run(
    ["ping", "-n", "1", "127.0.0.1"],
    capture_output=True, text=True, timeout=10,
)
print(r.returncode, r.stdout)

try:
    subprocess.run(["pytest", "tests/"], check=True, text=True, capture_output=True)
except subprocess.CalledProcessError as e:
    print("测试失败:", e.stderr)

r = subprocess.run(["python", "-c", "print(input())"], input="hi\n",
                   capture_output=True, text=True)
```

## 踩坑

- **管道缓冲阻塞**：`stdout=PIPE` 不消费会卡死子进程；用 `capture_output`/`communicate()` 或重定向文件/`DEVNULL`。
- **bytes vs str**：不指定 `text=True` 得到 bytes，中文直接 `.strip()` 会乱码/解码错；显式 `text=True` 或 `encoding="utf-8"`。
- **`shell=True` 命令注入**：拼用户输入用 shell=True 是高危；用列表形式 + 避免 shell。
- **`CalledProcessError` 含 stdout/stderr**：调试时读 `e.stdout`/`e.stderr` 看子进程输出。
- **Windows 命令名/参数转义**：跨平台用列表形式 + 跨平台工具，别手写 shell 字符串。
- **大输出**：重定向到文件而非 capture，避免内存暴涨。
- **`Popen` 忘记 `wait()`/`communicate()`**：进程可能变僵尸或输出不全。

## 面试怎么答

`subprocess.run` 是调用外部命令的标准方式，返回对象带 returncode/stdout/stderr；`Popen` 是底层可控（流式/交互）。推荐传列表形式、`text=True` 拿 str、`check=True` 失败即抛 `CalledProcessError`、设 `timeout` 防卡死。

两个致命坑：① 管道输出不消费会阻塞子进程（OS 管道缓冲满）→ 用 capture/重定向；② `shell=True` 拼用户输入 = 命令注入，用列表形式避免。不指定 text 得到 bytes，中文要显式解码。多进程写同一日志要 QueueHandler（见 [[Python logging 日志]]）。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/library/subprocess.html
- 相关笔记：[[Python 异常处理]] [[Python logging 日志]] [[Python 编码与 bytes、str]]
