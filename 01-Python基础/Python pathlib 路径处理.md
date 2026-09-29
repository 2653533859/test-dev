---
created: 2026-07-31
tags: [Python基础/标准库]
---

# Python pathlib 路径处理

> `pathlib.Path` 把路径当对象，比字符串拼接 `+ "/"` 安全、跨平台、可读。测试脚本里读写用例/报告路径首选它。其底层是“纯路径计算”与“文件系统操作”的清晰分离。

## 概念

### 1. Path 是路径对象，不是字符串

`pathlib.Path` 把路径封装成对象，提供方法而非手动拼字符串。它自动处理平台分隔符（`/` 在 Windows 上被转成 `\`），避免 `os.path.join` 的繁琐。

### 2. `/` 运算符 = 路径拼接

`base / "sub" / "file.py"` 调用的是 `Path.__truediv__`（重载 `/`）。注意：**左边必须是 Path**，右边可以是字符串；`str / Path` 会 `TypeError`。

### 3. 纯路径 vs 具体路径

- `PurePath`（及 `PurePosixPath`/`PureWindowsPath`）：只做**路径计算**，不碰文件系统（不检查存在、不读属性）——可跨平台、可测试
- `Path`：继承 PurePath，额外**接触文件系统**（`exists()`/`read_text()`/`mkdir()` 等）

CPython 按运行平台自动选 `WindowsPath` 或 `PosixPath`。

### 4. 惰性遍历 `glob` / `rglob`

`Path.glob("**/*.json")` / `rglob` 返回**生成器**，惰性遍历目录树，不会一次性把所有匹配路径装内存，适合大目录。

### 5. `resolve` 的语义

`resolve()` 把路径变成**绝对路径并解析符号链接**（在 Windows 上还会规范化大小写/盘符）。常用于“拿到规范路径做相等比较”或“读取 __file__ 定位项目根”。

## 用法

```python
from pathlib import Path

base = Path("cases")
case_file = base / "login" / "data.json"     # / 拼接，跨平台安全

case_file.parent.mkdir(parents=True, exist_ok=True)
case_file.write_text('{"u":"alice"}', encoding="utf-8")
print(case_file.suffix, case_file.stem, case_file.name)  # .json data data.json

for p in base.glob("**/*.json"):            # 惰性遍历
    print(p.relative_to(base))

root = Path(__file__).resolve().parents[2]  # 沿父目录上溯定位项目根
```

## 踩坑

- **`Path("a") / "b"` 合法，`str / Path` 报错**：`/` 左边必须是 Path。
- **`glob("*.json")` 只搜当前层**：递归用 `rglob("*.json")` 或 `glob("**/*.json")`。
- **`resolve()` 会改大小写/盘符（Windows）**：做路径相等比较前先统一 resolve，否则 `C:\X` vs `c:\x` 不相等。
- **读文本务必 `encoding="utf-8"`**：否则 Windows 默认 GBK 容易 `UnicodeDecodeError`（见 [[Python 编码与 bytes、str]]）。
- **`rglob` 大目录慢**：惰性但仍要遍历，超大目录考虑按已知子目录精确匹配。
- **`exists()` 竞态**：检查存在后操作前文件可能被删，关键操作包 try/except 比先 exists 更稳。

## 面试怎么答

`pathlib.Path` 面向对象处理路径：`/` 运算符拼接（基于 `__truediv__`，左边须是 Path）、`glob`/`rglob` 惰性遍历目录树、`resolve()` 解析绝对路径与符号链接。底层区分纯路径（只计算不碰文件系统）和具体路径（接触 IO）。

相比 `os.path`：可读性好、跨平台分隔符自动处理、链式方法方便。测试里用于定位用例文件、生成报告路径、沿 `__file__` 上溯项目根。读文本显式 `utf-8` 避免 Windows GBK 解码失败。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/library/pathlib.html
- 相关笔记：[[Python json 序列化]] [[Python logging 日志]] [[Python os 与 shutil 文件操作]]
