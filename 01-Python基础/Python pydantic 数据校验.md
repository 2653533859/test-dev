---
created: 2026-07-31
tags: [Python基础/工程化]
---

# Python pydantic 数据校验

## 概念：把「数据校验」交给声明式模型

实际工程中，外部数据（API 请求、配置文件、环境变量）往往**类型不对、字段缺失、格式非法**。手写 `if not isinstance(x, int)` 校验冗长且易漏。Pydantic 的核心思路：**用类型注解声明「数据应该长什么样」，运行时自动校验、转换、报错**。

> 关联：Python 的类型注解本身运行时无效（见 [[Python 工程化：虚拟环境、导入机制与类型注解]]）。Pydantic 正是「把注解变成真校验」的利器之一。

它底层基于 Python 的**类型提示 + 描述符 + dataclasses 思路**，用 Rust 实现的核心（`pydantic-core`）解析快、校验严。

## 用法一：定义模型与自动校验

```python
from pydantic import BaseModel, field_validator

class User(BaseModel):
    name: str
    age: int
    email: str

# 传入合法数据 → 自动构造
u = User(name="张三", age=20, email="a@b.com")
print(u.name)            # 张三

# 传入类型不符 → pydantic 自动尝试转换或报错
u2 = User(name="李四", age="25", email="c@d.com")  # "25" 被转成 int 25
print(u2.age)            # 25

# 无法转换 → 抛 ValidationError，含每个字段的详细原因
bad = User(name="王五", age="abc", email="x")
# pydantic_core._pydantic_core.ValidationError: ...
```

关键认知：**Pydantic 会做「宽松转换」**——`"25"`→`25`，`1`→`True`(bool 是 int 子类)，但 `"abc"`→int 失败就报错。这种设计对处理脏数据很友好，但也可能「静默吞掉」你没料到的转换，需要留意。

## 用法二：字段约束与默认值

```python
from pydantic import BaseModel, Field

class Product(BaseModel):
    title: str = Field(min_length=1, max_length=50)
    price: float = Field(gt=0, description="价格必须为正")
    stock: int = Field(default=0, ge=0)
    tags: list[str] = Field(default_factory=list)   # 可变默认值用 default_factory

p = Product(title="书", price=9.9)
print(p.stock, p.tags)      # 0 []
```

- `ge/gt/le/lt`：数值的 ≥、>、≤、<。
- **可变默认值（list/dict）必须用 `default_factory`**，否则所有实例共享同一对象（和 [[函数默认参数的可变对象陷阱]] 同理）。

## 用法三：自定义校验 `field_validator` / `model_validator`

```python
from pydantic import BaseModel, field_validator, model_validator

class Signup(BaseModel):
    password: str
    confirm: str

    @field_validator("password")
    def pwd_strength(cls, v):
        if len(v) < 8:
            raise ValueError("密码至少 8 位")
        return v

    @model_validator(mode="after")
    def pw_match(self):
        if self.password != self.confirm:
            raise ValueError("两次密码不一致")
        return self
```

- `field_validator`：单字段校验，返回转换后的值。
- `model_validator(mode="after")`：拿到完整对象后做跨字段校验（如两次密码比对）。

## 用法四：嵌套模型与 JSON 互转

```python
from pydantic import BaseModel
from typing import list

class Address(BaseModel):
    city: str
    zip: str

class Person(BaseModel):
    name: str
    addresses: list[Address]

data = {
    "name": "张三",
    "addresses": [{"city": "北京", "zip": "100000"}],
}
p = Person.model_validate(data)     # 字典 → 模型（含嵌套校验）
print(p.model_dump())               # 模型 → 普通字典
print(p.model_dump_json())          # 模型 → JSON 字符串
```

`model_validate` 接受 dict / JSON 字符串 / 任意对象并递归校验嵌套结构；`model_dump()` 反向导出为 dict，非常适合做 API 入参/出参的边界转换。

## 用法五：ConfigDict 与严格模式（v2）

```python
from pydantic import BaseModel, ConfigDict

class Strict(BaseModel):
    model_config = ConfigDict(strict=True)   # 关闭宽松转换
    age: int

# Strict 模式下 "25" 直接报错，不会转成 25
# Strict(age="25")  → ValidationError
```

`strict=True` 适合「外部输入必须就是声明类型」的严格边界（如 API 网关）。

## 踩坑

1. **可变默认值直接写 `tags: list[str] = []`**：所有实例共享同一列表，一改全改。必须用 `Field(default_factory=list)`。
2. **以为注解等于校验**：裸类型注解没有运行时校验；只有放进 `BaseModel` 才生效。Pydantic 才是校验层。
3. **宽松转换「静默吞错」**：`age="25"` 被默默转成 25，可能掩盖上游传错类型的问题。严格边界用 `ConfigDict(strict=True)`。
4. **bool 是 int 子类**：`Field(gt=0)` 下 `flag: int = True` 能通过（True==1>0）。需要纯整数时用 `Strict(int)` 或显式校验。
5. **v1 与 v2 API 差异大**：`class Config:`、`@validator` 是 v1；`model_config`、`field_validator`、`model_validator` 是 v2。混用会报错，注意版本。
6. **`model_validator` 忘了 `return self`**（after 模式）：校验器需要返回对象，否则对象字段会丢失。
7. **在热路径里反复 validate 大对象**：虽用 Rust 核心很快，但大规模高频校验仍有成本，可考虑缓存或预编译。

## 面试怎么答

**Q：Pydantic 解决了什么问题？**
A：用声明式模型把外部脏数据的校验、类型转换、错误报告自动化。开发者只写类型注解，运行时自动校验并给出每个字段的详细错误，省去大量手写 `if isinstance` 的样板。

**Q：Pydantic 的宽松转换是优点还是坑？**
A：两者都是。它把 `"25"`→`25`、`1`→`True` 自动转换，对处理真实脏数据很友好；但也可能静默掩盖类型传错。需要严格边界时开启 `ConfigDict(strict=True)`。

**Q：为什么列表默认值要用 default_factory？**
A：因为可变对象是共享引用（同 [[函数默认参数的可变对象陷阱]]），直接 `= []` 会让所有实例共用一个列表。用 `default_factory=list` 每次新建独立对象。

**Q：Pydantic 和 dataclass 什么关系？**
A：都用于定义带字段的数据类（见 [[Python dataclasses]]）。但 dataclass 只负责自动生成 `__init__`/`__repr__` 等，不做运行时校验；Pydantic 在 dataclass 思路上叠加了类型校验与转换。`pydantic.dataclasses.dataclass` 还能让普通 dataclass 也获得校验能力。
