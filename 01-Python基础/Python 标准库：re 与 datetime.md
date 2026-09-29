---
created: 2026-07-31
tags: [Python基础/标准库]
---

# Python 标准库：re 与 datetime

![[assets/regex-backtrack.svg]]
*图示：正则回溯引擎——贪婪量词先吞到末尾再回溯；嵌套量词 `(a+)+$` 遇不可匹配结尾会指数级回溯（ReDoS）。详见 [[Python 正则表达式深入：分组、断言与贪婪]]。*

> 接口响应里的字符串断言、日志时间解析、用例里的动态日期，都离不开 `re` 和 `datetime`。两件套放在一起记：理解正则引擎的“回溯”和 datetime 的“朴素/感知”时区模型，才不会再被坑。

## 概念

### 1. `re`：基于回溯的 NFA 引擎

Python 的 `re` 是 **PCRE 风格、回溯型（NFA）** 正则引擎。匹配时它尝试一条路，遇到多选/量词就“试一条，不行回溯试另一条”。这带来：
- 灵活（支持贪婪/懒惰、前后向断言）
- 但**灾难性回溯**（catastrophic backtracking）：某些 `(a+)+$` + 长字符串会指数级回溯，导致 ReDoS（正则拒绝服务）——处理不可信输入的正则要小心

### 2. 常用 API

- `re.compile(pattern, flags)`：预编译成 `Pattern` 对象（复用+可读，引擎内部也有小缓存）
- `re.match`（仅从**开头**）、`re.search`（全文首个）、`re.fullmatch`（整串）、`re.findall`（所有匹配，有分组只返组）、`re.finditer`（惰性迭代器）
- `re.sub`/`re.split`
- 分组：`()` 捕获、`(?P<name>)` 命名、`(?:)` 非捕获

### 3. 贪婪 vs 非贪婪（回溯的直接体现）

默认量词 `.*` `+` 是**贪婪**（尽量多匹配），`.*?` `+?` 是**非贪婪**（尽量少匹配）。提取标签内文本用非贪婪，否则会吞到最后一个闭合标签。

### 4. `datetime`：naive vs aware（时区模型）

- **naive（朴素）**：`datetime` 无时区信息（不配 `tzinfo`）。Python 默认创建的是 naive。
- **aware（感知）**：配了 `tzinfo`（如 `datetime.timezone.utc`、3.9+ 的 `zoneinfo`），知道自己在哪个时区。
- **naive 与 aware 不能比较/运算**：会 `TypeError`——这是用 datetime 最常见的坑。
- **最佳实践**：存用 UTC（aware），展示按本地时区转换；避免本地 naive 时间跨时区错乱。

### 5. `timedelta` 与格式化

`timedelta` 做日期加减；`strftime`（对象→字符串，格式 `%Y-%m-%d %H:%M:%S`）、`strptime`（字符串→对象，格式必须匹配否则 `ValueError`）。ISO 8601 用 `isoformat()`/`fromisoformat()`（Python 3.7+ 增强）。

## 用法

```python
import re
from datetime import datetime, timedelta, timezone

text = 'order_id=12345, ts=2026-07-31 10:00:00'
m = re.search(r"order_id=(?P<id>\d+)", text)
print(m.group("id"))                       # 12345（命名分组）

TOKEN = re.compile(r"token=([a-f0-9]{32})") # 预编译

now = datetime.now()
future = now + timedelta(days=3)            # naive 加减
aware = datetime.now(timezone.utc)          # aware
print(future.strftime("%Y-%m-%d"))

dt = datetime.strptime("2026-07-31 10:00:00", "%Y-%m-%d %H:%M:%S")
```

## 踩坑

- **`match` vs `search`**：`match` 只从开头，`search` 查全文；“明明有却匹配不到”多半用错了。
- **贪婪吞多**：`.*` 会吞到最后一个闭合标签；取单段内容用 `.*?` 非贪婪。
- **前后向断言不能变长**：`(?<=ab*)` 非法（多数引擎限制），要定长或换思路。
- **`findall` 有分组只返回组**：想拿整串别加捕获分组，或改用 `finditer`。
- **naive/aware 不能比较**：`TypeError`；统一用 UTC aware 或统一 naive。
- **`strptime` 格式不匹配** → `ValueError`；封装带容错的解析函数。
- **ReDoS**：处理不可信输入的正则避免嵌套量词（如 `(a+)+`），否则可被恶意输入打挂。

## 面试怎么答

`re` 是回溯型（NFA）引擎：`compile` 预编译、`match` 开头/`search` 全文/`findall` 取全部、`(?P<name>)` 命名分组；贪婪 `.*` 尽量多、非贪婪 `.*?` 尽量少，提取标签用非贪婪；注意 `findall` 有分组只返组、前后向断言不能变长、ReDoS 风险。

`datetime` 区分 naive（无时区）与 aware（有时区），两者不能比较（TypeError）；最佳实践存 UTC、展示转本地。动态日期用 `timedelta`。`strptime` 格式须匹配否则 ValueError。

## 参考

- re 文档：https://docs.python.org/zh-cn/3/library/re.html
- datetime 文档：https://docs.python.org/zh-cn/3/library/datetime.html
- 相关笔记：[[Python json 序列化]] [[Python logging 日志]] [[Python 正则表达式深入：分组、断言与贪婪]]
