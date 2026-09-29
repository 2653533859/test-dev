---
created: 2026-07-31
tags: [Python基础/面向对象]
---

# Python 类与对象：属性、继承、MRO 与 property

![[assets/mro-diamond.svg]]
*图示：菱形继承下 C3 MRO 线性化顺序 `D→B→C→A→object`，`super()` 按 MRO 取「下一个」。*

## 概念一：Python 是「一切皆对象」，类也是对象

`class` 定义时，Python 会执行类体，创建一个**类对象**（type 的实例），把它绑定到名字。`class` 的基类、方法、类变量都挂在这个类对象的命名空间里。实例对象则各有自己的 `__dict__` 存实例属性。

### 属性查找链（最关键的底层）

访问 `obj.x` 时，Python 按这样的顺序找：

1. **实例自身** `obj.__dict__`（及其实例属性）
2. **类** `type(obj).__dict__` 及其实例方法、类变量
3. **父类**（按 MRO 顺序）

```python
class A:
    x = "类变量"

a = A()
print(a.x)          # 类变量（实例没有，找到类上）
a.x = "实例变量"      # 在实例 __dict__ 写入，覆盖类的 x（不影响类）
print(a.x)          # 实例变量
print(A.x)          # 类变量（未被改动）
```

> 关键认知：`a.x = 值` 是**在实例上新建/覆盖属性**，不会改类变量。要避免「实例意外遮盖类变量」，常把可变类变量改成在 `__init__` 里初始化实例属性。

## 概念二：MRO 与 C3 线性化

Python 支持**多重继承**，当 `class D(B, C)` 且 B、C 都继承 A 时，「`D` 的父类查找顺序」由 **MRO（Method Resolution Order）** 决定，算法是 **C3 线性化**。

```python
class A: pass
class B(A): pass
class C(A): pass
class D(B, C): pass

print(D.__mro__)
# (<class 'D'>, <class 'B'>, <class 'C'>, <class 'A'>, <class 'object'>)
```

C3 的目标：① 保持继承声明顺序（先 B 后 C）；② 单调（子类总在父类前）；③ 满足所有父类的局部顺序。它保证了「菱形继承」下 `A` 只出现一次、且在 `B`/`C` 之后。

### 逐步理解菱形

```
    object
      A
     / \
    B   C
     \ /
      D
```

`D` 继承 `B`、`C`，`B`、`C` 都继承 `A`。`D.__mro__` 必须让 `D→B→C→A→object`：D 最前，B 在 C 前（声明顺序），A 在 B/C 之后（因为 B、C 才是 A 的直接子类），object 永远最后。如果 C3 算不出满足所有约束的顺序，会抛 `TypeError: Cannot create a consistent method resolution order`，即「继承图有冲突」。

### super() 不是「调父类」，是「按 MRO 调下一个」

```python
class A:
    def hello(self):
        print("A")
class B(A):
    def hello(self):
        super().hello()      # 按 MRO 找 B 之后下一个类的 hello
        print("B")

B().hello()     # A 先打印，再 B
```

`super()` 绑定的是「MRO 中当前类的下一个」，所以多重继承里协作调用能正确串成一条链，不会重复调用 A。这是写 `super().__init__()` 能避免菱形重复初始化的原因。

## 概念三：property —— 把「方法调用」伪装成「属性访问」

有时你想「读起来像属性，但内部有计算/校验」。`property` 把方法变成可像属性一样访问的 descriptor（见 [[Python 描述符 descriptor]]）。

```python
class Circle:
    def __init__(self, r):
        self._r = r

    @property
    def radius(self):
        return self._r

    @radius.setter
    def radius(self, value):
        if value < 0:
            raise ValueError("半径不能为负")
        self._r = value

    @property
    def area(self):          # 只读属性（没有 setter）
        return 3.14159 * self._r ** 2

c = Circle(3)
print(c.area)        # 像属性一样读，其实是调用方法
c.radius = 5         # 像赋值属性，其实走 setter 校验
# c.radius = -1      # ValueError
# c.area = 10        # AttributeError: 只读
```

`property` 让「受控访问」和「公开字段」对外接口一致——将来把裸字段改成带校验的属性，调用方代码不用改。这是 Python 的「统一访问原则」。

## 用法：类变量 vs 实例变量、`__slots__`

```python
class Demo:
    shared = []          # 类变量：所有实例共享（小心！）

    def __init__(self):
        self.own = []    # 实例变量：每个实例独立

# __slots__：禁止 __dict__，固定属性名，省内存、防手滑加属性
class Point:
    __slots__ = ("x", "y")
    def __init__(self):
        self.x = 0
        self.y = 0

p = Point()
# p.z = 1    # AttributeError: 'Point' object has no attribute 'z'
```

`__slots__` 用元组固定允许的属性名，实例不再有 `__dict__`，**大幅减少内存**——当你要创建百万级实例时很关键。代价是失去动态加属性的灵活性、且某些动态特性受限。

## 踩坑

1. **可变类变量被所有实例共享**：`shared = []` 后 `a.shared.append(1)`，b 也看得到。要在 `__init__` 里初始化实例属性，或用 `None` + 懒加载。
2. **`a.x = 值` 误以为改了类变量**：实际只在实例上新建属性，类的 `x` 没变。要改类变量用 `类名.x = 值`。
3. **`super()` 当「父类」用**：它是「MRO 下一个」，多重继承里用 `super().__init__()` 才能正确串链，避免重复/遗漏初始化。
4. **MRO 冲突 TypeError**：继承顺序设计不当（如 `class A(B, C), class B(C), class C(A)` 这类循环/矛盾）会让 C3 无解。调整继承结构。
5. **property 没 setter 却赋值**：只读属性赋值会 `AttributeError`。需要可写就加 `@x.setter`。
6. **用 property 做重计算却当字段缓存**：每次访问都重算（如 `area`）。重计算应加缓存（`functools.cached_property`，3.8+）。
7. **`__slots__` 忘了子类也要定义**：子类若没自己的 `__slots__`，会重新有 `__dict__`，slots 的内存优势在子类失效。

## 面试怎么答

**Q：访问 obj.x 的查找顺序是？**
A：先查实例 `__dict__`，再查类及其类变量/方法，最后按 MRO 查父类。实例上 `obj.x = v` 只是在实例写入，不改类变量。

**Q：什么是 MRO？为什么需要它？**
A：MRO 是多重继承下属性和方法的查找顺序，由 C3 线性化算法决定。它保证声明顺序、子类在父类前、菱形继承中公共基类只出现一次。用 `类名.__mro__` 查看。

**Q：super() 是调用父类吗？**
A：不是直接调父类，而是按 MRO 调「当前类的下一个」。这样多重继承里 `super().__init__()` 能正确协作，避免公共基类被重复初始化。

**Q：property 有什么用？**
A：把方法封装成「像属性一样访问」的接口，可在读/写时插入计算或校验，且对外接口稳定（将来从裸字段改成受控属性，调用方代码不变）。只读属性只定义 getter 不加 setter 即可。
