---
created: 2026-07-31
tags: [Python基础/类型系统]
---

# Python typing 进阶：泛型、Protocol 与 TypedDict

![[assets/protocol-subtype.svg]]
*图示：Protocol 实现结构化子类型——`list`/`str`/自定义类不继承 Sized，只因实现了 `__len__` 就类型兼容（鸭子类型类型化）。*

## 概念：注解从「标类型」到「描述结构」

基础注解（`x: int`）只标单值类型。进阶场景需要表达：
- 「任意类型但内部一致」→ **泛型（Generic + TypeVar）**
- 「只要有某些方法/属性即可，不必继承」→ **结构化子类型（Protocol）**
- 「字典里有哪些固定键、各自什么类型」→ **TypedDict**

这些都在 `typing` 模块，服务于静态检查器（mypy/pyright）。再次强调：**运行时都不强制**（见 [[Python 工程化：虚拟环境、导入机制与类型注解]]）。

## 用法一：TypeVar 与泛型函数

```python
from typing import TypeVar, Sequence

T = TypeVar("T")              # 一个类型变量，占位「某种类型」

def first(items: Sequence[T]) -> T:
    return items[0]

reveal = first([1, 2, 3])     # mypy 推断返回 int
reveal2 = first(("a", "b"))   # 推断返回 str
```

`TypeVar` 表示「调用时确定的某一个具体类型」，函数内部保持类型一致：传入 `list[int]`，返回 `int`；传入 `tuple[str]`，返回 `str`。这就是**参数化多态**。

### 约束与边界

```python
from typing import TypeVar, Union

# 限制 T 只能是 int 或 str
T = TypeVar("T", int, str)
# 或 UpperBound：
U = TypeVar("U", bound="Sequence")   # U 必须是 Sequence 或其子类
```

## 用法二：Generic 自定义泛型类

```python
from typing import Generic, TypeVar, List

T = TypeVar("T")

class Stack(Generic[T]):
    def __init__(self) -> None:
        self._items: List[T] = []
    def push(self, item: T) -> None:
        self._items.append(item)
    def pop(self) -> T:
        return self._items.pop()

s: Stack[int] = Stack()
s.push(1)                # OK
# s.push("x")            # mypy 报错：期望 int
```

`Generic[T]` 让你定义的类也能「带类型参数」，像 `list[int]` 那样使用。

## 用法三：Protocol —— 鸭子类型的类型化

```python
from typing import Protocol

class Sized(Protocol):
    def __len__(self) -> int: ...

def count(obj: Sized) -> int:
    return len(obj)

count([1, 2, 3])        # list 有 __len__ → 满足
count("hello")          # str 有 __len__ → 满足
# count(42)             # int 没有 __len__ → mypy 报错
```

传统 OOP 用「继承」约束：`def count(obj: BaseSized)` 要求传入 `BaseSized` 的子类。但 `list`/`str` 不可能继承你的 `BaseSized`。**Protocol 实现结构化子类型（鸭子类型）**：「走起来像鸭子、叫起来像鸭子，就是鸭子」——只要对象实现了协议要求的方法/属性，就类型兼容，**无需显式继承**。这是 Python 动态哲学和静态类型检查的美妙结合。

> `@runtime_checkable` 装饰的 Protocol 还支持运行时 `isinstance(x, Sized)`（但只检查「是否有该方法名」，不检查签名）。

## 用法四：TypedDict —— 给字典加「字段 schema」

```python
from typing import TypedDict

class User(TypedDict):
    name: str
    age: int
    email: str

def greet(u: User) -> str:
    return f"{u['name']}, {u['age']}"

greet({"name": "张三", "age": 20, "email": "a@b.com"})   # OK
# greet({"name": "李"})   # mypy：缺 age、email
```

`TypedDict` 让「字典里有固定键」这件事可被静态检查。它**运行时仍是普通 dict**（`isinstance` 检查不到字段），只服务于类型检查器。适合描述 JSON/API 响应的结构。

### 必需与可选字段

```python
from typing import TypedDict, NotRequired   # 3.11+ NotRequired；旧版 Optional 语义不同

class User(TypedDict, total=False):
    name: str          # total=False 下所有字段默认可选
    age: int

class Partial(TypedDict):
    name: str
    age: NotRequired[int]    # 仅 age 可选
```

## 用法五：Callable、Union、字面量

```python
from typing import Callable, Union, Literal

# 可调用对象：参数 (int,int) 返回 int
Op = Callable[[int, int], int]

def apply(f: Op, a: int, b: int) -> int:
    return f(a, b)

# Union 表示「或」
def parse(x: Union[str, bytes]) -> str: ...

# Literal 限定为几个字面量值之一
def set_level(level: Literal["low", "mid", "high"]) -> None: ...
```

Python 3.10+ 可用 `X | Y` 代替 `Union[X, Y]`，`int | str`；3.8+ 的 `Literal` 用于枚举式约束。

## 踩坑

1. **注解运行时无效**：`TypedDict`/`Protocol` 在运行时只是 dict/普通类，`isinstance` 查不到字段（除非 `@runtime_checkable` 的 Protocol，且只查方法名）。
2. **TypeVar 名要大写且唯一**：约定用 `T`/`K`/`V`，并用 `TypeVar("T")` 名字串与变量名一致。
3. **Protocol 误当基类继承**：Protocol 是「结构契约」，不需要（也不应该）被继承来「满足」它——任何实现了对应方法的类自动兼容。
4. **`Optional[X]` 与 `NotRequired` 混淆**：`Optional[int]`=「int 或 None」，字段仍必须出现；`NotRequired[int]`=「可整段缺失」。两者语义不同。
5. **泛型类实例化了却不在变量注解上声明**：`Stack()` 不标注 `Stack[int]`，检查器无法推断 `push` 应接收 int。
6. **过度注解降低可读性**：不是每行都要注解，公共 API 边界、复杂结构（TypedDict/Protocol）才最值得。
7. **旧 Python 用新语法**：`X | Y` 需 3.10+，`NotRequired` 需 3.11+，低版本要用 `Union`/`Optional` 与 `total=False`。

## 面试怎么答

**Q：TypeVar 有什么用？**
A：表示「调用时确定的某一具体类型」，用于写泛型函数/类，保证内部类型一致（如 `first(list[int]) -> int`）。它是参数化多态的基础。

**Q：Protocol 解决了什么问题？**
A：它实现结构化子类型（鸭子类型）的类型化。只要对象实现了协议要求的方法/属性就类型兼容，无需显式继承，解决了「list/str 等内置类型无法继承自定义基类」的约束难题。

**Q：TypedDict 和 dataclass 区别？**
A：TypedDict 描述「字典的固定键结构」，运行时仍是普通 dict，只为静态检查服务；dataclass 生成真正的类实例（带方法、可比较等）。API 响应/JSON 用 TypedDict，需要行为/方法的数据对象用 dataclass。

**Q：Union 和 Optional 是什么？**
A：`Union[X, Y]` 表示「X 或 Y」；`Optional[X]` 是 `Union[X, None]` 的简写，表示「X 或 None」。Python 3.10+ 可用 `X | Y`、`X | None` 替代。
