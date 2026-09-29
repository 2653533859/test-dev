---
created: 2026-07-31
tags: [Python基础/数据类型]
---

# Python 枚举 enum

## 概念：枚举是「一组有名字的常量」

代码中经常出现「状态、类型、选项」这类离散取值。新手常用字符串/整数魔法值：

```python
# 反例：魔法字符串散落各处，拼写错也无提示
status = "active"
if status == "activ":      # 拼错，静默不命中
    ...
```

`enum.Enum` 把这些取值收拢成**有名字的、不可变的成员**，提供类型安全、自动补全、防拼错、可迭代。

```python
from enum import Enum

class Color(Enum):
    RED = 1
    GREEN = 2
    BLUE = 3

print(Color.RED)           # Color.RED
print(Color.RED.name)      # 'RED'
print(Color.RED.value)     # 1
```

每个成员是 `Color` 的**单例实例**，身份唯一：`Color.RED is Color(1)` 为 True。

## 用法一：访问与比较

```python
from enum import Enum

class Status(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"

s = Status.PENDING
print(s.name, s.value)          # PENDING pending

# 通过值取成员
print(Status("pending"))        # Status.PENDING
# 通过名字取成员
print(Status["PENDING"])        # Status.PENDING

# 身份比较（枚举成员是单例，用 is 也行）
print(s == Status.PENDING)      # True
print(s == "pending")           # False（类型安全：不会和普通字符串混）

# 枚举成员不可变
# Status.PENDING = "x"    # AttributeError: Cannot reassign members
```

关键好处：`s == "pending"` 返回 False——枚举成员**不会**和裸字符串/数字意外相等，避免了魔法值相互误比。

## 用法二：遍历、函数分发、IntEnum/StrEnum

```python
from enum import Enum

class Op(Enum):
    ADD = 1
    SUB = 2
    MUL = 3

# 遍历所有成员
for member in Op:
    print(member, member.value)

# 用字典做「枚举 → 行为」分发，比长 if/elif 优雅
dispatch = {
    Op.ADD: lambda a, b: a + b,
    Op.SUB: lambda a, b: a - b,
    Op.MUL: lambda a, b: a * b,
}
print(dispatch[Op.ADD](2, 3))    # 5
```

### IntEnum / StrEnum（Python 3.11+）

```python
from enum import IntEnum, StrEnum

class Level(IntEnum):       # 成员既是枚举也是 int
    LOW = 1
    HIGH = 2

print(Level.LOW == 1)       # True（可与 int 比较）
print(Level.LOW < Level.HIGH)   # True（支持排序）

class Mode(StrEnum):        # 成员既是枚举也是 str
    READ = "r"
    WRITE = "w"

print(Mode.READ == "r")      # True
```

- 普通 `Enum`：成员**不**等于其 value（最严格，推荐默认用）。
- `IntEnum`：成员可比大小、可当 int 用，但也会和裸 int 相等（失去部分类型安全）。
- `StrEnum`（3.11+）：成员可当 str 用，适合要序列化/JSON 的场景。

> 别名（aliases）：多个名字指向同一 value 会成别名，遍历只出现一次。`unique` 装饰器可强制值唯一。

## 用法三：unique 与自定义行为

```python
from enum import Enum, unique

@unique
class Status(Enum):
    A = 1
    B = 2
    # C = 1    # @unique 会报 ValueError：值 1 已存在

# 给枚举加方法
class Planet(Enum):
    EARTH = (5.97, 6371)
    def __init__(self, mass, radius):
        self.mass = mass
        self.radius = radius

print(Planet.EARTH.mass)     # 5.97
```

枚举成员可以有自己的属性/方法，`__init__` 接收 value 元组里的分量。

## 踩坑

1. **用魔法字符串代替枚举**：拼写错误无提示、易混比。优先用枚举表达离散状态。但也不要为了「颜色这种纯展示」过度设计枚举——简单配置未必需要。
2. **以为普通 Enum 成员 == value**：普通 `Enum` 的 `Color.RED != 1` 也不等于 `"red"`。要和值比较就用 `Color.RED.value`。
3. **用 IntEnum 反而丢了类型安全**：`IntEnum` 成员 `== 1` 为 True，可能和裸 int 意外混比。不需要数值运算就用普通 Enum。
4. **枚举成员可被重新赋值**：枚举是单例且不可变，`Status.A = x` 会 AttributeError——这是特性，确保状态唯一。
5. **别名导致遍历「少成员」**：两个名字同 value 是一个成员的别名，遍历只出现一次。需要值唯一用 `@unique`。
6. **JSON 序列化直接 dump 枚举报错**：枚举不是原生 JSON 类型，要 `json.dumps(obj, default=lambda o: o.value)` 或存 `.value`。
7. **低版本用 StrEnum**：StrEnum 是 3.11+，老版本用 `str` 子类枚举或 `.value` 兜底。

## 面试怎么答

**Q：枚举解决了什么问题？**
A：把离散取值（状态、类型、选项）收拢成有名字、不可变、单例的成员，提供类型安全、自动补全、防拼错、可迭代。比散落的魔法字符串/整数更可靠。

**Q：普通 Enum 和 IntEnum 有什么区别？**
A：普通 Enum 成员不等于其 value（最严格，推荐默认用）；IntEnum 成员既是枚举也是 int，可比较大小、可当 int 用，但也会和裸 int 意外相等，类型安全弱一些。

**Q：枚举成员怎么取？值能重复吗？**
A：通过 `Enum.NAME` 按名字、`Enum(value)` 按值、`Enum["NAME"]` 按名字取。默认允许别名（同值多名字），用 `@unique` 强制值唯一否则报 ValueError。

**Q：枚举能当字典键/JSON 序列化吗？**
A：枚举成员可哈希，能当 dict 键。但 JSON 不能直接序列化枚举，需指定 `default=lambda o: o.value` 或序列化 `.value`/`.name`。
