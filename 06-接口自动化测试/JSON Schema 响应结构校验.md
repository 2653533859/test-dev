---
created: 2026-07-31
tags: [接口自动化测试/断言]
---

# JSON Schema 响应结构校验

> 后端把 `total` 从 int 改成 string、把空数组改成 null，业务值断言全部通过，前端线上炸掉——这类「结构漂移」只有 Schema 能系统性拦住。

## 概念

### Schema 解决的是「契约」问题

业务值断言关心「值对不对」，Schema 关心「形状对不对」：

```python
# 业务断言：只看具体值，形状变了发现不了
assert r.json()["data"]["total"] == 100
# "100" == 100 → False，这条能发现
# 但 {"total": 100, "list": null} 里 list 变 null，你没断言就漏了
```

一个接口有二三十个字段，逐个写 `assert isinstance(x, int)` 不现实。Schema 的价值是**用一份声明式配置覆盖所有字段的形状**，而且这份配置可以被多条用例复用（列表接口和详情接口共用同一个订单对象 Schema）。

### JSON Schema 的核心关键字

| 关键字 | 作用 | 例子 |
|--------|------|------|
| `type` | 类型 | `"integer"` / `"string"` / `"array"` / `"object"` / `"null"` |
| `required` | 必填字段列表 | `["order_id", "status"]` |
| `properties` | 各字段的子 Schema | `{"amount": {"type": "string"}}` |
| `items` | 数组元素的 Schema | `{"type": "object", ...}` |
| `enum` | 枚举取值 | `["UNPAID", "PAID"]` |
| `pattern` | 字符串正则 | `"^\\d+\\.\\d{2}$"` |
| `minimum` / `maximum` | 数值范围 | `{"minimum": 1}` |
| `minLength` / `maxLength` | 字符串长度 | `{"maxLength": 200}` |
| `additionalProperties` | 是否允许多余字段 | `false` = 严格模式 |
| `nullable` / `anyOf` | 可为 null | `{"type": ["string", "null"]}` |

### 两个最容易搞错的语义

**1）`required` 只管「键存在」，不管值**

```python
schema = {"type": "object", "required": ["name"]}
# {"name": null} → 通过！required 只检查键在不在
# 要禁止 null，得写 "properties": {"name": {"type": "string"}}
```

**2）`additionalProperties` 默认是 `true`**

默认允许响应里有 Schema 没定义的字段。这通常是对的——后端加字段是向后兼容的变更，不该让用例红。但如果你要做**严格契约测试**（多一个字段也算违约），就设成 `false`。

我的建议：**日常回归用宽松模式（默认），契约测试用严格模式**。

## 用法

### 基本用法

```bash
pip install jsonschema
```

```python
import jsonschema

ORDER_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["code", "msg", "data"],
    "properties": {
        "code": {"type": "integer"},
        "msg": {"type": "string"},
        "data": {
            "type": "object",
            "required": ["order_id", "status", "amount", "items", "created_at"],
            "properties": {
                "order_id": {"type": "integer", "minimum": 1},
                "status": {"enum": ["UNPAID", "PAID", "CANCELLED", "REFUNDED"]},
                # 金额用字符串，且必须两位小数
                "amount": {"type": "string", "pattern": r"^\d+\.\d{2}$"},
                # 可能为 null 的字段这样写
                "coupon_id": {"type": ["string", "null"]},
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["sku_id", "quantity", "price"],
                        "properties": {
                            "sku_id": {"type": "string"},
                            "quantity": {"type": "integer", "minimum": 1},
                            "price": {"type": "string"},
                        },
                    },
                },
                "created_at": {"type": "string", "format": "date-time"},
            },
        },
    },
}

jsonschema.validate(instance=response.json(), schema=ORDER_SCHEMA)
```

### 把错误信息变得可读

`jsonschema` 默认的报错很长，直接抛出来在报告里几乎不可读。封装一下：

```python
import jsonschema
from jsonschema import Draft202012Validator


def assert_schema(data: dict, schema: dict, *, max_errors: int = 5):
    """一次报出所有结构错误，而不是只报第一个。"""
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if not errors:
        return
    lines = [f"响应结构校验失败，共 {len(errors)} 处："]
    for e in errors[:max_errors]:
        path = ".".join(str(p) for p in e.absolute_path) or "<root>"
        lines.append(f"  - {path}: {e.message}")
    if len(errors) > max_errors:
        lines.append(f"  ... 还有 {len(errors) - max_errors} 处")
    raise AssertionError("\n".join(lines))
```

`iter_errors` 比 `validate` 好用得多：`validate` 遇到第一个错误就抛，你得改一个跑一次；`iter_errors` 一次性把所有问题列出来。

输出效果：

```text
AssertionError: 响应结构校验失败，共 3 处：
  - data.amount: '19.9' does not match '^\\d+\\.\\d{2}$'
  - data.items: None is not of type 'array'
  - data.status: 'PAYING' is not one of ['UNPAID', 'PAID', 'CANCELLED', 'REFUNDED']
```

### Schema 复用：`$defs` 与 `$ref`

列表接口和详情接口共用同一个订单对象，别复制两份：

```python
COMMON_DEFS = {
    "$defs": {
        "order": {
            "type": "object",
            "required": ["order_id", "status", "amount"],
            "properties": {
                "order_id": {"type": "integer", "minimum": 1},
                "status": {"enum": ["UNPAID", "PAID", "CANCELLED", "REFUNDED"]},
                "amount": {"type": "string", "pattern": r"^\d+\.\d{2}$"},
            },
        },
        "page": {
            "type": "object",
            "required": ["total", "page", "size"],
            "properties": {
                "total": {"type": "integer", "minimum": 0},
                "page": {"type": "integer", "minimum": 1},
                "size": {"type": "integer", "minimum": 1, "maximum": 100},
            },
        },
    }
}

ORDER_DETAIL_SCHEMA = {
    **COMMON_DEFS,
    "type": "object",
    "properties": {"data": {"$ref": "#/$defs/order"}},
    "required": ["data"],
}

ORDER_LIST_SCHEMA = {
    **COMMON_DEFS,
    "type": "object",
    "properties": {
        "data": {
            "allOf": [
                {"$ref": "#/$defs/page"},
                {
                    "type": "object",
                    "required": ["list"],
                    "properties": {"list": {"type": "array",
                                            "items": {"$ref": "#/$defs/order"}}},
                },
            ]
        }
    },
    "required": ["data"],
}
```

### 从真实响应反向生成 Schema

给存量接口补 Schema 时，手写几十个字段太累。用 `genson` 先生成再手工收紧：

```bash
pip install genson
```

```python
from genson import SchemaBuilder
import json

builder = SchemaBuilder()
# 喂多个样本，覆盖可选字段与 null 的情况
for sample in [resp1.json(), resp2.json(), resp3.json()]:
    builder.add_object(sample)

print(json.dumps(builder.to_schema(), indent=2, ensure_ascii=False))
```

**生成的只是起点**，必须手工加三样东西：`enum`（状态枚举）、`pattern`（金额/手机号格式）、`minimum`（ID 必须为正）。只有 `type` 的 Schema 拦不住多少问题。

### 用 pydantic 替代（更 Pythonic）

如果团队更习惯写类，`pydantic` 是更好的选择——有类型提示、IDE 补全，报错信息也更友好：

```python
from decimal import Decimal
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, ValidationError


class OrderStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class OrderItem(BaseModel):
    sku_id: str
    quantity: int = Field(ge=1)
    price: Decimal


class OrderData(BaseModel):
    order_id: int = Field(ge=1)
    status: OrderStatus
    amount: Decimal
    coupon_id: Optional[str] = None
    items: list[OrderItem] = Field(min_length=1)


class OrderResponse(BaseModel):
    code: int
    msg: str
    data: OrderData


def test_create_order(api, sku):
    r = api.post("/api/v1/orders", json={"sku_id": sku, "quantity": 2})
    assert r.status_code == 200
    try:
        parsed = OrderResponse.model_validate(r.json())
    except ValidationError as e:
        raise AssertionError(f"响应结构不符:\n{e}\n原始响应: {r.text[:800]}") from None
    assert parsed.data.status == OrderStatus.UNPAID
    assert parsed.data.amount == Decimal("39.80")
```

**pydantic 的额外好处**：校验完拿到的是带类型的对象，后续断言有 IDE 补全，`parsed.data.amount` 拼错会被静态检查发现，而 `r.json()["data"]["amount"]` 拼错只有运行时才报。缺点是默认会做类型强转（`"100"` 转成 `100`），要严格模式得配 `model_config = ConfigDict(strict=True)`。参考 [[Python pydantic 数据校验]]。

### 从 OpenAPI 文档直接取 Schema

如果团队有规范的 Swagger，Schema 根本不用自己写：

```python
import json
from pathlib import Path

spec = json.loads(Path("openapi.json").read_text(encoding="utf-8"))

def schema_of(path: str, method: str, status: str = "200") -> dict:
    node = spec["paths"][path][method]["responses"][status]
    schema = node["content"]["application/json"]["schema"]
    # $ref 指向 components，把 components 一起带上供解析
    return {**schema, "components": spec.get("components", {})}
```

这样 Schema 和文档天然同源，后端改了文档，用例立刻能感知到差异——这已经接近契约测试了，见 [[独立 Mock 服务与契约测试]]。

## 踩坑

1. **`required` 不等于「非 null」**：`{"name": null}` 能通过 `required: ["name"]`。要禁 null 必须在 `properties` 里写死 `type`。
2. **Schema 写得太松等于没写**：只有 `{"type": "object"}` 的 Schema 什么都拦不住。至少要有完整的 `required` 列表和每个字段的 `type`。
3. **`additionalProperties` 用错场合**：日常回归设 `false`，后端加个无害字段就全线红，团队很快就会把这条校验删掉。除非做严格契约测试，否则保持默认。
4. **`format` 默认不校验**：`{"format": "date-time"}` 在 `jsonschema` 里默认只是注解，不会真的验证。要生效得装 `jsonschema[format]` 并传 `format_checker=Draft202012Validator.FORMAT_CHECKER`。
5. **浮点数金额进 Schema**：`{"type": "number"}` 的 `19.90` 在 JSON 里就是 `19.9`，你想校验两位小数就得用字符串 + `pattern`。这也是为什么建议金额字段用字符串传输。
6. **整数被 `type: "number"` 放过**：JSON Schema 里 `integer` 是 `number` 的子集，写 `number` 则 `1.5` 也算通过。要整数就写 `integer`。
7. **Python 的 `True` 在 Schema 里是 `boolean`，但 `1` 也可能被当成 integer 通过**：`jsonschema` 对 Python 对象校验时，`True` 是 `int` 的子类，`{"type": "integer"}` 会放过 `True`。严格场景加 `"not": {"type": "boolean"}`。
8. **每个接口一份 Schema，改一次改十处**：分页结构、通用响应包装（`code`/`msg`/`data`）、常见业务对象都应该抽到 `$defs` 里复用。
9. **只在正向用例里校验 Schema**：错误响应也有结构（`{"code": 400001, "msg": "...", "data": null}`），也该有 Schema，否则错误响应的格式漂移没人管。
10. **用 genson 生成后直接用**：生成的 Schema 只有 `type`，把 `enum`、`pattern`、`minimum` 补上才有价值。

## 面试怎么答

**Q：什么是 JSON Schema，接口测试里怎么用？**

A：JSON Schema 是描述 JSON 数据结构的声明式规范，能约束字段是否必填、类型、枚举值、字符串格式、数值范围、数组元素结构。在接口测试里它是断言体系的第二层——业务值断言只覆盖你手动挑出来的几个关键字段，而一个响应有二三十个字段，逐个写 `isinstance` 不现实。用 Schema 一份配置就能覆盖全部字段的「形状」，还能在列表接口和详情接口之间用 `$defs` + `$ref` 复用。它拦的是后端重构时最典型的破坏性变更：字段被删或改名、int 悄悄变成 string、空数组变成 null——这些业务值断言通常发现不了，但前端一定会崩。

**Q：JSON Schema 和 pydantic 你会选哪个？**

A：看团队习惯。JSON Schema 的优势是语言无关，能直接从 OpenAPI 文档里取，天然和后端契约同源，做契约测试更顺；缺点是纯字典写起来啰嗦，没有 IDE 支持。pydantic 的优势是写成 Python 类，有类型提示和补全，校验完拿到的是带类型的对象，后续断言 `parsed.data.amount` 写错会被静态检查抓到，报错信息也更友好；缺点是默认会做类型强转，`"100"` 会被转成 `100`，把 int 变 string 这种漂移放过去了，得开 strict 模式。我的选择是：**如果团队有规范的 Swagger 就用 JSON Schema 直接从文档取，否则用 pydantic**。

**Q：Schema 校验通过了，是不是就不用写别的断言了？**

A：不是，Schema 只保证形状对，不保证值对。`{"amount": "0.01"}` 完全符合「字符串、两位小数」的 Schema，但如果单价 19.90 买了 2 件，正确答案应该是 39.80——这个必须靠业务值断言。反过来业务值断言也替代不了 Schema：你不可能对二三十个字段逐个断言具体值，而且很多字段的值是动态的。两者是互补的：Schema 覆盖广度，业务断言覆盖深度，再往下还有数据库落库校验。

## 参考

- [JSON Schema 官方文档](https://json-schema.org/understanding-json-schema/)
- [jsonschema Python 库](https://python-jsonschema.readthedocs.io/en/stable/)
- [genson](https://github.com/wolverdude/GenSON)
- 相关笔记：[[接口断言三层体系]]、[[Python pydantic 数据校验]]、[[独立 Mock 服务与契约测试]]
