---
created: 2026-07-31
tags: [Python基础/面向对象]
---

# Python 魔术方法

## 概念：魔术方法（dunder methods）是「协议的钩子」

名字前后带双下划线的方法，如 `__init__`、`__len__`、`__add__`，被称为**魔术方法 / 双下方法（dunder）**。它们不是给你直接调用的（`obj.__len__()` 很少手写），而是 Python 在遇到**语法或内置函数**时自动调用的「协议钩子」。

```python
len(obj)        # 自动调用 obj.__len__()
obj + other     # 自动调用 obj.__add__(other)
str(obj)        # 自动调用 obj.__str__()
obj[key]        # 自动调用 obj.__getitem__(key)
```

理解魔术方法 = 理解「Python 的语法糖背后调用了哪个方法」。这些方法的底层机制与描述符、属性查找密切相关（见 [[Python 类与对象：属性、继承、MRO 与 property]]、[[Python 描述符 descriptor]]）。

## 用法一：构造与表示

```python
class Point:
    def __init__(self, x, y):       # 实例化时自动调用（不是构造函数，是初始化器）
        self.x = x
        self.y = y

    def __repr__(self):             # 给开发者看的「官方」字符串（debug/REPL）
        return f"Point({self.x}, {self.y})"

    def __str__(self):              # 给用户看的字符串（str()/print 优先）
        return f"({self.x}, {self.y})"

p = Point(1, 2)
print(p)            # (1, 2)  —— 用 __str__
print(repr(p))      # Point(1, 2) —— 用 __repr__
```

规则：`print`/`str()` 优先用 `__str__`，没有就 fallback 到 `__repr__`；`__repr__` 的目标是「尽可能 `eval(repr(obj)) == obj`」（ unambiguous）。**永远至少实现 `__repr__`**，否则对象打印成 `<Point object at 0x...>` 毫无信息。

> 关于「构造」：`__init__` 是初始化器；真正的构造（分配内存、创建实例）是 `__new__`，极少重写。多数类只需 `__init__`。

## 用法二：运算重载

```python
class Vec:
    def __init__(self, x, y):
        self.x, self.y = x, y

    def __add__(self, other):
        return Vec(self.x + other.x, self.y + other.y)

    def __eq__(self, other):
        return self.x == other.x and self.y == other.y

    def __lt__(self, other):        # 支持 sorted/< 比较
        return (self.x, self.y) < (other.x, other.y)

v = Vec(1, 2) + Vec(3, 4)
print(v.x, v.y)          # 4 6
print(Vec(1, 2) == Vec(1, 2))   # True
```

常见运算符映射：`__add__`(+)、`__sub__`(-)、`__mul__`(*)、`__truediv__`(/)、`__eq__`(==)、`__ne__`(!=)、`__lt__`/ `__le__`/ `__gt__`/ `__ge__`(比较)、`__neg__`(-x)、`__hash__`(hash)。

### 反向与反射运算

当 `a + b` 而 `a.__add__(b)` 返回 `NotImplemented` 时，Python 会尝试 `b.__radd__(a)`（反射）。这让「右操作数类型更懂怎么加」得以生效（如 `1 + myobj`）。

```python
def __radd__(self, other):
    return self.__add__(other)
```

## 用法三：容器协议（让对象像 list/dict）

```python
class MyList:
    def __init__(self, items):
        self._items = list(items)

    def __len__(self):
        return len(self._items)

    def __getitem__(self, idx):
        return self._items[idx]

    def __setitem__(self, idx, value):
        self._items[idx] = value

    def __iter__(self):
        return iter(self._items)

    def __contains__(self, item):
        return item in self._items

ml = MyList([10, 20, 30])
print(len(ml))        # 3
print(ml[0])          # 10
ml[0] = 99
print(20 in ml)       # True
for x in ml: print(x)
```

实现这些后，你的对象就能用 `len()`、`[]`、索引、`in`、迭代——成为「类容器」。这背后就是迭代器协议（见 [[Python 生成器与迭代器]]）和容器协议。

## 用法四：可调用与上下文管理

```python
class Adder:
    def __init__(self, n):
        self.n = n
    def __call__(self, x):        # 让实例可像函数一样调用
        return x + self.n

add5 = Adder(5)
print(add5(10))        # 15（实际调用 add5.__call__(10)）

class DB:
    def __enter__(self):          # with 进入
        return self
    def __exit__(self, *exc):     # with 退出（详见 [[Python 上下文管理器]]）
        print("关闭连接")
        return False

with DB() as db:
    pass
```

`__call__` 让对象「可调用」，常用于带状态的回调/函数对象（如装饰器类、策略对象）。

## 用法五：`__hash__` 与相等性的契约

```python
class Item:
    def __init__(self, val):
        self.val = val
    def __eq__(self, o):
        return isinstance(o, Item) and self.val == o.val
    def __hash__(self):
        return hash(self.val)

# 重写了 __eq__ 后，若想可哈希（当 dict 键/set 元素），必须同时定义 __hash__
s = {Item(1), Item(2)}
```

**严格契约**：`a == b` 必须推出 `hash(a) == hash(b)`。Python 默认：定义了可变对象的类不自动给 `__hash__`（防你改了字段导致 hash 变，破坏 dict 内部定位）。一旦重写了 `__eq__` 又想哈希，必须显式定义 `__hash__`。

## 踩坑

1. **只实现 `__str__` 忘实现 `__repr__`**：对象打印成 `<X object at 0x...>`，调试时毫无信息。至少写 `__repr__`。
2. **`__eq__` 和 `__hash__` 不一致**：重写了 `__eq__` 却没定义 `__hash__`，对象变不可哈希；或 hash 用的字段可变，放进 dict 后改字段就找不到了。
3. **运算返回 `NotImplemented` 而非抛异常**：当不支持的类型，`__add__` 应 `return NotImplemented`，让 Python 去试反射 `__radd__`，否则 `1 + obj` 直接 TypeError 且不尝试反射。
4. **`__init__` 当构造函数**：真正的构造是 `__new__`（分配内存）。绝大多数场景只需 `__init__`（初始化器），不需要重写 `__new__`。
5. **容器协议只实现了部分**：实现了 `__getitem__` 但没 `__len__`，`len()` 会报 TypeError；`for` 循环依赖 `__iter__` 或 `__getitem__`+`__len__` 回退。
6. **魔术方法被直接手写调用**：`obj.__len__()` 不如 `len(obj)` 地道，且绕过可能的优化。约定：魔术方法由解释器触发，不要手动调。
7. **`__eq__` 没处理 `isinstance`**：`Item() == "字符串"` 若无类型判断会 AttributeError，应在 `__eq__` 里判 `isinstance`。

## 面试怎么答

**Q：什么是魔术方法？举例？**
A：前后双下划线的方法，是 Python 语法/内置函数自动调用的协议钩子，如 `len(x)`→`__len__`、`x+y`→`__add__`、`str(x)`→`__str__`、`x[k]`→`__getitem__`。它们让自定义对象具备内置类型的「语法糖」。

**Q：__str__ 和 __repr__ 的区别？**
A：`__str__` 给用户看、重可读；`__repr__` 给开发者看、重无歧义且理想可 `eval` 还原。`print`/`str` 优先 `__str__`，否则 fallback `__repr__`。建议至少实现 `__repr__`。

**Q：重写 __eq__ 后还要注意什么？**
A：必须保证 `a==b` ⟹ `hash(a)==hash(b)`。想让对象可哈希（当 dict 键），要显式定义 `__hash__`；否则默认不可哈希。且 hash 涉及的字段不应可变。

**Q：__new__ 和 __init__ 的区别？**
A：`__new__` 负责真正创建实例（分配内存，类方法），`__init__` 负责初始化实例属性。绝大多数类只写 `__init__`；`__new__` 仅在不可变类型（如 int 子类）或单例等场景重写。
