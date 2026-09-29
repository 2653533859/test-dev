---
created: 2026-07-31
tags: [Python基础/数据结构]
---

# Python dataclasses

## 概念：自动生成样板代码的「数据类」

当你写这样一个类，绝大部分代码都是样板：

```python
class Point:
    def __init__(self, x: int, y: int):
        self.x = x
        self.y = y
    def __repr__(self):
        return f"Point(x={self.x}, y={self.y})"
    def __eq__(self, other):
        return self.x == other.x and self.y == other.y
```

`dataclasses`（Python 3.7+）用装饰器 + 字段声明，让编译器**自动生成 `__init__`、`__repr__`、`__eq__` 等方法**：

```python
from dataclasses import dataclass

@dataclass
class Point:
    x: int
    y: int

p = Point(1, 2)
print(p)                 # Point(x=1, y=2)
print(p == Point(1, 2))  # True（自动 __eq__ 比字段）
```

### 底层原理

`@dataclass` 是一个**类装饰器**，在类定义后运行：它扫描类体内的「带类型注解的变量」作为字段，然后用 `types.new_class` / 动态生成函数体，把 `__init__`、`__repr__`、`__eq__` 等写入类的命名空间。你写的 `x: int` 只是**注解 + 类变量初始值**，真正的赋值在生成的 `__init__` 里完成。

> 注意：`@dataclass` 不会自动加 `__hash__`（除非 `eq=True, frozen=True` 或显式指定）；默认 `frozen=False` 时可变，故 `__hash__` 被设为 `None`（不可哈希），与 `list` 同理。

## 用法一：默认值与 `field`

```python
from dataclasses import dataclass, field

@dataclass
class Config:
    name: str = "default"
    tags: list[str] = field(default_factory=list)   # 可变默认必须 default_factory
    # debug: bool = field(default=False, repr=False)  # repr=False 不进 repr
```

**可变默认值陷阱**：和 [[函数默认参数的可变对象陷阱]] 同源——直接在类里写 `tags: list = []`，所有实例共享同一列表。dataclass 里用 `field(default_factory=list)` 每次新建。

## 用法二：frozen 不可变数据类

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Const:
    x: int
    y: int

c = Const(1, 2)
# c.x = 3   # dataclasses.FrozenInstanceError: cannot assign to field
```

`frozen=True` 让生成的 `__setattr__`/`__delattr__` 直接抛错，得到**不可变对象**，并可哈希（自动生成 `__hash__`），适合做字典键或配置常量。

## 用法三：post_init 后处理

```python
from dataclasses import dataclass, field

@dataclass
class Range:
    lo: int
    hi: int
    _span: int = field(default=0, init=False)   # init=False: 不由构造参数传入

    def __post_init__(self):
        if self.lo > self.hi:
            raise ValueError("lo 必须 <= hi")
        self._span = self.hi - self.lo

r = Range(1, 10)
print(r._span)     # 9
```

`__post_init__` 在生成的 `__init__` 末尾被调用，用于校验、计算派生字段（`init=False` 的字段只能在这里赋值）。

## 用法四：order 比较与 asdict

```python
from dataclasses import dataclass, asdict, astuple

@dataclass(order=True)
class Item:
    price: int
    name: str

items = [Item(3, "c"), Item(1, "a"), Item(2, "b")]
print(sorted(items))          # 按第一个字段 price 排序

it = Item(1, "a")
print(asdict(it))             # {'price': 1, 'name': 'a'}（深拷贝导出字典）
```

`order=True` 自动生成 `<`、`<=`、`>`、`>=`（基于字段顺序逐个比较）。`asdict` 把 dataclass 递归转成普通 dict（深拷贝，改结果不影响原对象）。

## 踩坑

1. **可变默认直接 `= []`**：同函数默认参数陷阱，所有实例共享。用 `field(default_factory=list)`。
2. **默认可变却期望相等**：共享列表被一个实例改了，别的实例也跟着变，且 `==` 比较可能意外相等/不等。
3. **`frozen=False` 默认不可哈希**：想当 dict 键会报 `TypeError: unhashable`。要么 `frozen=True`，要么显式 `eq=True, frozen=True` 让其生成 `__hash__`。
4. **继承时字段顺序**：dataclass 会把父类的字段放在前面、子类字段在后，生成的 `__init__` 参数顺序也如此。多重继承字段顺序要心里有数。
5. **`__post_init__` 里给 `init=False` 字段赋值**才合法；在 `__init__` 之前赋值会失败，因为那些字段不在构造参数里。
6. **`asdict` 是深拷贝**：大数据结构有性能成本，且会脱离 dataclass 类型。

## 面试怎么答

**Q：dataclass 和 普通 class 比有什么优势？**
A：用装饰器自动生成 `__init__`、`__repr__`、`__eq__` 等样板方法，减少重复代码、降低出错。字段用类型注解声明，可读性强。

**Q：dataclass 为什么可变默认值要用 default_factory？**
A：因为可变对象是共享引用（同函数默认参数的经典陷阱），直接 `= []` 会让所有实例共用一个对象。default_factory 在每次构造时调用工厂函数新建独立对象。

**Q：怎么让 dataclass 不可变、可哈希？**
A：加 `@dataclass(frozen=True)`。它会禁止字段赋值并自动生成 `__hash__`，使实例可当字典键。

**Q：dataclass 和 namedtuple / pydantic 怎么选？**
A：namedtuple 是不可变元组子类、最轻量（见 [[Python collections 模块]]）；dataclass 默认可变、支持默认值/校验/比较，纯 Python 标准库；pydantic（见 [[Python pydantic 数据校验]]）在 dataclass 思路上加了运行时类型校验与转换，适合外部脏数据边界。
