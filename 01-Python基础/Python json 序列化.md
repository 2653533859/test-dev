---
created: 2026-07-31
tags: [Python基础/标准库]
---

# Python json 序列化

> 接口测试几乎天天和 JSON 打交道：`requests` 的 `.json()`、断言比对、用例数据文件。理解 JSON 的类型模型和 Python 对象图的“双向映射边界”，才知道哪些对象能序列化、为什么 datetime 会报错、`ensure_ascii` 为什么会乱。

## 概念

### 1. JSON 是跨语言的文本格式

JSON（ECMA-404）只支持一套固定类型：`object`(→dict) / `array`(→list) / `string` / `number` / `bool` / `null`(→None)。它是**文本**、**跨语言**、**安全**的交换格式（不像 [[Python pickle 序列化]] 能执行代码）。

### 2. Python 的双向映射

| JSON | Python |
|---|---|
| object | `dict` |
| array | `list`（注意：`tuple` 也被序列化成 array，反序列化回不来 tuple） |
| string | `str` |
| number | `int` / `float` |
| true/false | `True`/`False` |
| null | `None` |

`json.dumps(obj)` 序列化、`json.loads(str)` 反序列化。底层是 `JSONEncoder`/`JSONDecoder` 递归遍历。

### 3. 哪些 Python 对象“默认不支持”

`JSONEncoder` 只认识上表类型。`datetime`、`set`、`bytes`、自定义类实例、lambda 等**默认不支持**，直接 `TypeError: Object of type X is not JSON serializable`。解决：
- 用 `default` 回调：返回“可序列化”的表示（如 `dt.isoformat()`）
- 或先转成 dict（`dataclasses.asdict`、`__dict__`、`pydantic`）

### 4. `ensure_ascii` 与字符转义

`dumps` 默认 `ensure_ascii=True`：所有非 ASCII 字符被转成 `\uXXXX` 转义（如 `"中文"` → `"\u4e2d\u6587"`）。这**不影响数据正确性**，但日志/报告里难读。中文友好要 `ensure_ascii=False`。

### 5. 浮点与大小数

`float('nan')` 能 dump，但**不符合标准 JSON**，很多语言解析不了。大整数 JSON 用 number 表示，跨语言注意精度（JS 的 number 是双精度，超大 int 会丢精度）。

## 用法

```python
import json
from datetime import datetime

data = {"name": "alice", "age": 18, "tags": ("a", "b")}
s = json.dumps(data, ensure_ascii=False, indent=2)
print(s)                        # tags 变数组；中文保留

def encoder(o):
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(f"not serializable: {o!r}")

print(json.dumps({"t": datetime(2026, 1, 1)}, default=encoder))

resp = json.loads('{"code":0,"msg":"ok"}')
assert resp["code"] == 0
```

## 踩坑

- **`ensure_ascii=True` 让中文变 `\uXXXX`**：日志/报告难读，通常设 `ensure_ascii=False`（数据正确，仅表示不同）。
- **`tuple` 被序列化成 array**：反序列化回来是 list 不是 tuple；要保留 tuple 用 `default`/`object_hook` 自定义或 `tuple` 类型标记。
- **`datetime`/`set`/自定义对象默认不支持**：`TypeError`，用 `default` 回调或先转 dict。
- **反序列化不校验结构**：`resp["missing"]` 会 `KeyError`；接口断言先确认字段存在，用 `.get()` 或 pydantic 校验。
- **`float('nan')` 不标准**：跨语言解析不了，避免。
- **大文件**：`json.load(f)` 流式读，别先 `f.read()` 再 `loads`，省一次全量字符串。
- **重复 key**：标准允许对象有重复 key，`json.loads` 默认后者覆盖前者，注意脏数据。

## 面试怎么答

`json` 模块做 Python 与 JSON 互转，类型映射固定（tuple→array、None→null）。它只支持基础类型，`datetime`/`set`/自定义对象默认不支持，靠 `default` 回调或预转换。两个高频坑：`ensure_ascii` 默认 True 把中文转义（影响可读性）；解析后不校验结构，访问缺失 key 会 KeyError，接口断言要先确认字段。

对比 pickle：json 文本、跨语言、安全、只基础类型；pickle 二进制、Python 专用、灵活但有 RCE 红线。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/library/json.html
- 相关笔记：[[Python pickle 序列化]] [[Python pathlib 路径处理]] [[Python pydantic 数据校验]]
