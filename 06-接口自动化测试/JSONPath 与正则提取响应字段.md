---
created: 2026-07-31
tags: [接口自动化测试/数据驱动]
---

# JSONPath 与正则提取响应字段

> `r.json()["data"]["list"][0]["order"]["id"]` 这种写法，响应结构一变就是几十条用例同时挂掉，而且报错只有一句 `KeyError: 'order'`。

## 概念

### 为什么不直接用字典下标

三个问题：

1. **报错信息没用**：`KeyError: 'order'` 不告诉你实际响应长什么样，也不告诉你是哪一层缺失
2. **不可配置**：提取规则写死在代码里，改结构要翻遍所有用例文件
3. **表达能力弱**：「取列表里 status 为 PAID 的第一个元素的 id」，用下标写要三行循环

JSONPath 用一行表达式解决这三点：`$.data.list[?(@.status=='PAID')].id`，而且可以放进 YAML 配置。

### JSONPath 语法速查

| 语法 | 含义 | 例子 |
|------|------|------|
| `$` | 根节点 | `$` |
| `.key` / `['key']` | 子节点 | `$.data.order_id` |
| `..key` | **递归**搜索所有层级 | `$..order_id` |
| `*` | 通配 | `$.data.list[*].id` |
| `[n]` | 数组下标 | `$.data.list[0]` |
| `[-1]` | 倒数第一个（jsonpath-ng 支持） | `$.data.list[-1]` |
| `[start:end]` | 切片 | `$.data.list[0:3]` |
| `[?(@.k=='v')]` | 过滤（需 ext 扩展） | `$.data.list[?(@.status=='PAID')]` |
| `[?(@.price>100)]` | 数值比较 | `$.items[?(@.price>100)].name` |
| `` `len` `` | 长度（jsonpath-ng 扩展） | `$.data.list.` + `` `len` `` |

**`..` 递归搜索很好用也很危险**：`$..id` 会把所有层级的 `id` 都捞出来，包括你不想要的。能用精确路径就别用递归。

### JSONPath vs 正则：什么时候用哪个

| 场景 | 用什么 |
|------|--------|
| JSON 响应取字段 | JSONPath |
| HTML / 纯文本响应 | 正则 |
| Set-Cookie、Location 等响应头里取值 | 正则 |
| JWT 里取 payload | Base64 解码，不是正则 |
| 日志文件里找关键字 | 正则 |

**永远不要用正则解析 JSON**。`re.search(r'"order_id":\s*(\d+)', r.text)` 看起来能跑，但遇到嵌套的同名字段、值里含引号、字段顺序变化就全错。

## 用法

### 安装与基础用法

```bash
pip install jsonpath-ng
```

注意导入的是 `jsonpath_ng.ext`（带过滤表达式支持），不是 `jsonpath_ng`：

```python
from jsonpath_ng.ext import parse

data = {
    "code": 0,
    "data": {
        "total": 3,
        "list": [
            {"order_id": 1001, "status": "PAID",   "amount": "19.90", "user": {"id": 1}},
            {"order_id": 1002, "status": "UNPAID", "amount": "39.80", "user": {"id": 2}},
            {"order_id": 1003, "status": "PAID",   "amount": "9.90",  "user": {"id": 1}},
        ],
    },
}

# 取单值
print([m.value for m in parse("$.data.total").find(data)])
# [3]

# 取所有 order_id
print([m.value for m in parse("$.data.list[*].order_id").find(data)])
# [1001, 1002, 1003]

# 过滤：只要已支付的
print([m.value for m in parse("$.data.list[?(@.status=='PAID')].order_id").find(data)])
# [1001, 1003]

# 数值比较
print([m.value for m in parse("$.data.list[?(@.amount>'10.00')].order_id").find(data)])
# [1001, 1002]

# 嵌套字段
print([m.value for m in parse("$.data.list[0].user.id").find(data)])
# [1]

# 递归搜索所有 order_id（谨慎使用）
print([m.value for m in parse("$..order_id").find(data)])
# [1001, 1002, 1003]
```

### 封装成好用的提取函数

裸 API 每次都要写 `[m.value for m in ...]`，且找不到时返回空列表而不报错。封装一下：

```python
from typing import Any
from jsonpath_ng.ext import parse

_CACHE: dict[str, Any] = {}


def _compile(expr: str):
    """表达式解析有开销，缓存起来。"""
    if expr not in _CACHE:
        _CACHE[expr] = parse(expr)
    return _CACHE[expr]


def jp_all(data, expr: str) -> list:
    """返回所有匹配值，可能为空列表。"""
    return [m.value for m in _compile(expr).find(data)]


def jp_one(data, expr: str):
    """返回第一个匹配值；无匹配直接抛错，绝不静默返回 None。"""
    matches = _compile(expr).find(data)
    if not matches:
        import json
        raise AssertionError(
            f"JSONPath 提取失败：{expr} 无匹配\n"
            f"实际响应: {json.dumps(data, ensure_ascii=False)[:800]}"
        )
    return matches[0].value


def jp_get(data, expr: str, default=None):
    """允许缺失的场景用这个，显式传 default。"""
    matches = _compile(expr).find(data)
    return matches[0].value if matches else default
```

**`jp_one` 无匹配就抛错**是最重要的设计。用 `.get()` 链式取值拿到 `None` 之后，后续请求变成 `/api/orders/None`，报个 404，你会去查询接口找半天 bug——实际问题在提取那一步。

### 在断言和提取里使用

```python
def test_order_list(api):
    r = api.get("/api/v1/orders", params={"page": 1, "size": 10})
    body = r.json()

    # 断言：列表长度与 total 一致
    assert len(jp_all(body, "$.data.list[*]")) == jp_one(body, "$.data.total")

    # 断言：所有订单都属于当前用户（越权检查）
    user_ids = set(jp_all(body, "$.data.list[*].user.id"))
    assert user_ids <= {CURRENT_USER_ID}, f"返回了他人订单: {user_ids}"

    # 断言：所有金额都是两位小数字符串
    for amount in jp_all(body, "$.data.list[*].amount"):
        assert isinstance(amount, str) and "." in amount and len(amount.split(".")[1]) == 2

    # 提取：拿第一个未支付订单的 id，给下一步用
    unpaid_id = jp_one(body, "$.data.list[?(@.status=='UNPAID')].order_id")
```

`user_ids <= {CURRENT_USER_ID}` 这行是集合的子集判断，用来做批量越权检查非常简洁。

### 提取规则配置化

把表达式从代码里挪到配置，是数据驱动的关键一环：

```yaml
# testcases/order_flow.yaml
- name: 创建订单
  request: {method: POST, path: /api/v1/orders, json: {sku_id: SKU001, quantity: 1}}
  extract:
    order_id: $.data.order_id
    amount: $.data.amount
    first_item_sku: $.data.items[0].sku_id

- name: 查询订单
  request: {method: GET, path: /api/v1/orders/${order_id}}
  validate:
    jsonpath:
      $.data.order_id: ${order_id}
      $.data.amount: ${amount}
```

```python
def do_extract(resp_json: dict, rules: dict[str, str], ctx: dict) -> None:
    for var_name, expr in rules.items():
        ctx[var_name] = jp_one(resp_json, expr)
```

响应结构变了只改 YAML 一行，不用动代码。

### 正则提取：非 JSON 场景

```python
import re

# 1) 从 Set-Cookie 里取 SESSIONID
set_cookie = r.headers.get("Set-Cookie", "")
m = re.search(r"SESSIONID=([^;]+)", set_cookie)
assert m, f"响应头未下发 SESSIONID: {set_cookie}"
session_id = m.group(1)

# 2) 从重定向 Location 里取授权码（OAuth 场景）
location = r.headers["Location"]
code = re.search(r"[?&]code=([^&]+)", location).group(1)

# 3) 从 HTML 里取 CSRF token
m = re.search(r'<input[^>]+name="csrf_token"[^>]+value="([^"]+)"', r.text)
csrf = m.group(1) if m else None

# 4) 从日志里统计错误
errors = re.findall(r"ERROR\s+\[(\S+)\]\s+(.+)", log_text)
assert not errors, f"日志中发现 {len(errors)} 条错误: {errors[:3]}"
```

封装一个带清晰报错的版本：

```python
def re_one(text: str, pattern: str, group: int = 1, *, flags=0) -> str:
    m = re.search(pattern, text, flags)
    if not m:
        raise AssertionError(
            f"正则提取失败：{pattern!r} 无匹配\n文本片段: {text[:500]}"
        )
    return m.group(group)
```

### 命名分组让正则可读

```python
LOG_PATTERN = re.compile(
    r"(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"
    r"(?P<level>\w+)\s+"
    r"\[(?P<trace_id>[a-f0-9]+)\]\s+"
    r"(?P<msg>.+)"
)

for line in log_lines:
    m = LOG_PATTERN.match(line)
    if m and m.group("level") == "ERROR":
        print(m.group("trace_id"), m.group("msg"))
```

比 `m.group(3)` 好维护太多。参考 [[Python 正则表达式深入：分组、断言与贪婪]]。

## 踩坑

1. **导错包**：`from jsonpath_ng import parse` 不支持 `[?(...)]` 过滤表达式，会报解析错误。必须 `from jsonpath_ng.ext import parse`。
2. **提取失败静默返回 None**：后续用 `None` 拼 URL，错误被延迟到下游，排查成本极高。提取函数必须 fail fast。
3. **`find()` 返回列表，忘了取 `.value`**：拿到的是 `DatumInContext` 对象，打印出来很奇怪。
4. **过滤表达式里的引号**：`$.list[?(@.status=='PAID')]` 里必须用单引号，外层 Python 字符串用双引号。写反了会解析失败。
5. **数值比较的类型问题**：`[?(@.amount>10)]` 中如果 `amount` 是字符串 `"19.90"`，比较行为取决于实现，可能不符合预期。**过滤条件尽量用相等判断，数值筛选在 Python 里做**。
6. **`..` 递归搜索误伤**：`$..id` 会把嵌套对象里同名的 `id` 都捞出来。能写精确路径就写精确路径。
7. **用正则解析 JSON**：`re.search(r'"order_id":\s*(\d+)', r.text)` 会在嵌套同名字段、值含转义引号、字段顺序变化时静默取错值。JSON 一律用 JSONPath。
8. **正则没转义特殊字符**：路径里的 `.`、`?`、`+` 在正则里有特殊含义。用 `re.escape()` 处理动态拼进去的部分。
9. **正则贪婪匹配**：`<td>(.*)</td>` 会一路匹配到最后一个 `</td>`。用非贪婪 `(.*?)`。
10. **每次都重新 `parse()` 表达式**：解析有开销，大量用例下会明显。缓存编译结果。
11. **JSONPath 表达式写错但语法合法**：比如把 `$.data.list` 写成 `$.data.lists`，返回空列表，如果用的是 `jp_get` 带默认值就静默通过了。**断言场景一律用会抛错的版本**。

## 面试怎么答

**Q：接口返回的数据你怎么提取，为什么不用字典下标？**

A：JSON 响应用 JSONPath，非 JSON（响应头、HTML、日志）用正则。不用字典下标主要是三个原因：一是报错信息没用，`KeyError: 'order'` 既不告诉你实际响应长什么样，也不告诉你是哪一层缺失；二是提取规则写死在代码里没法配置化，响应结构一变要翻遍所有用例；三是表达能力弱，比如「取列表里 status 为 PAID 的第一个订单 id」，JSONPath 一行 `$.data.list[?(@.status=='PAID')].order_id` 就搞定了。我会把提取函数封装成失败立刻抛错并带上实际响应片段的版本，绝不返回 None——否则 None 会被拼进下一个请求的 URL，错误延迟到下游，排查成本高得多。

**Q：JSONPath 和正则怎么选？**

A：看数据格式。JSON 结构化数据一律用 JSONPath，**绝不用正则解析 JSON**——`re.search(r'"order_id":\s*(\d+)', text)` 这种写法在嵌套同名字段、值里含转义引号、字段顺序变化时会静默取到错误的值，而且它不会报错，你根本不知道错了。正则的适用场景是非结构化文本：从 `Set-Cookie` 头里取 SESSIONID、从重定向的 Location 里取 OAuth 的 code、从 HTML 里取 CSRF token、从日志文件里找错误关键字。写正则时我会用命名分组 `(?P<name>...)` 提高可读性，动态拼进去的部分用 `re.escape` 转义，避免贪婪匹配用 `.*?`。

**Q：提取的值传给下一个接口，中间某一步取不到怎么办？**

A：立刻失败并给出足够的诊断信息，而不是让 `None` 往下流。我的提取函数在无匹配时抛 `AssertionError`，消息里带上表达式本身和实际响应的前 800 字符，这样看报告就能直接判断是接口没返回这个字段、还是表达式写错了。反面例子是用 `.get()` 链式取值，拿到 `None` 之后请求 `/api/orders/None`，服务端返回 404，你会以为是查询接口的 bug，实际上问题在两步之前的提取。另外提取规则我会放在 YAML 配置里而不是代码里，响应结构变了只改一行配置。

## 参考

- [JSONPath 语法说明](https://goessner.net/articles/JsonPath/)
- [jsonpath-ng](https://github.com/h2non/jsonpath-ng)
- [Python re 模块](https://docs.python.org/zh-cn/3/library/re.html)
- 相关笔记：[[接口串联与依赖参数提取传递]]、[[YAML 数据驱动接口用例]]、[[Python 正则表达式深入：分组、断言与贪婪]]
