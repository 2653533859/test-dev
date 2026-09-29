---
created: 2026-07-31
tags: [Python基础/面向对象]
---

# Python 描述符 descriptor

![[assets/descriptor-lookup.svg]]
*图示：访问 `obj.x` 的属性查找优先级链——数据描述符 > 实例字典 > 非数据描述符 > 类变量 > 父类（MRO）。*

## 概念：描述符是「属性的托管协议」

描述符是**实现了描述符协议方法的对象**，被「挂」在另一个类的类属性上，从而接管对该属性的**读 / 写 / 删除**行为。它是最底层的「属性管控」机制，你天天都在用——`property`、`classmethod`、`staticmethod`、`functools.cached_property` 全都是描述符实现的。

描述符协议三个方法（实现其一即为描述符）：
- `__get__(self, instance, owner)`：读取 `obj.x` / `Cls.x` 时调用
- `__set__(self, instance, value)`：赋值 `obj.x = v` 时调用
- `__delete__(self, instance)`：删除 `del obj.x` 时调用

含 `__set__` 的叫**数据描述符**；只有 `__get__` 的叫**非数据描述符**。这个区别直接影响属性查找优先级（见下）。

## 用法一：从 property 看描述符本质

`property` 不过是一个实现了 `__get__`/`__set__`/`__delete__` 的描述符类。自己写一个简化版 `MyProperty`：

```python
class MyProperty:
    def __init__(self, fget):
        self.fget = fget
    def __get__(self, instance, owner):
        if instance is None:
            return self           # 类上访问返回描述符自身
        return self.fget(instance)

class Circle:
    def __init__(self, r):
        self._r = r
    @MyProperty
    def radius(self):
        return self._r

c = Circle(3)
print(c.radius)        # 3（触发 MyProperty.__get__(c, Circle)）
```

当访问 `c.radius`，Python 发现 `Circle.radius` 是个实现了 `__get__` 的对象，就改走描述符协议调用 `radius.__get__(c, Circle)`。

### 描述符的「instance / owner」参数

- `instance`：通过**实例**访问时是实例对象（如 `c`）；通过**类**访问时是 `None`。
- `owner`：拥有这个属性的类（如 `Circle`）。
利用这点，描述符能区分「类访问」和「实例访问」。

## 用法二：数据描述符管控赋值

```python
class NonNegative:
    def __init__(self, name):
        self.name = name
    def __get__(self, instance, owner):
        if instance is None:
            return self
        return instance.__dict__[self.name]
    def __set__(self, instance, value):
        if value < 0:
            raise ValueError(f"{self.name} 不能为负")
        instance.__dict__[self.name] = value

class Account:
    balance = NonNegative("balance")
    def __init__(self, b):
        self.balance = b

a = Account(100)
a.balance = 50
print(a.balance)        # 50
# a.balance = -1        # ValueError
```

`NonNegative` 接管了 `balance` 的读写：写时校验非负，读时从实例 `__dict__` 取。这是把「校验逻辑」从每个类里抽出来的复用手段。

## 用法三：属性查找优先级（关键！）

回忆 [[Python 类与对象：属性、继承、MRO 与 property]] 的查找链，加入描述符后完整顺序是：

1. **数据描述符**（有 `__set__`）在类中定义 → **最高优先级**
2. 实例自身的 `__dict__`
3. **非数据描述符**（只有 `__get__`，如普通方法、classmethod）
4. 类变量
5. 父类（按 MRO）
6. `__getattr__`（兜底）

**为什么这点重要**：数据描述符优先级高于实例 `__dict__`。所以上面 `NonNegative` 即使 `instance.__dict__['balance']` 已有值，赋值 `a.balance = v` 仍会走描述符的 `__set__`（而非直接写实例字典），因为数据描述符在查找链更前面。

> 对比：`property` 是数据描述符 → 实例字典里就算有同名键也拦不住它。而普通方法（非数据描述符）可以被实例属性遮盖——`obj.foo = 123` 后 `obj.foo` 拿到 123 而非方法，因为实例字典在非数据描述符之前。

## 用法四：classmethod / staticmethod 也是描述符

```python
class Demo:
    @classmethod
    def cm(cls): print(cls)
    @staticmethod
    def sm(): print("static")

# classmethod 的描述符 __get__ 把「类」作为第一个参数自动传入
Demo.cm()          # 打印 Demo
Demo.sm()          # 打印 static
```

- `classmethod` 描述符的 `__get__` 返回「绑定了类的可调用」，所以 `cm` 自动收到 `cls`。
- `staticmethod` 描述符的 `__get__` 原样返回函数，不绑定任何东西，所以 `sm` 无隐式首参。

这正是装饰器底层机制：它们不是语法糖，而是描述符对象。

## 踩坑

1. **把描述符实例放在实例上而非类上**：描述符必须挂在**类属性**上才生效；放在 `__init__` 里 `self.x = MyDescriptor()` 不会触发协议（那是普通实例属性）。描述符应该是类级别的。
2. **数据描述符的 `__get__` 没处理 `instance is None`**：通过类访问（`Cls.attr`）时 `instance` 是 None，`__get__` 里对 `instance.__dict__` 会 AttributeError。类访问时一般返回描述符自身或类级值。
3. **描述符读时从 `instance.__dict__[name]` 取，却在 `__set__` 里没写同名键**：读写存储位置不一致会导致读不到。约定读写都落到 `instance.__dict__[self.name]`。
4. **误以为 property 能被实例字典遮盖**：property 是数据描述符，优先级高于实例字典，`obj.x = v` 永远走 setter，不会偷偷写实例字典。
5. **在描述符里用 `getattr(instance, self.name)` 读**：会递归触发描述符自身 `__get__`，栈溢出。应直接 `instance.__dict__[self.name]`。
6. **非数据描述符被实例属性遮盖**：普通方法/classmethod 是非数据描述符，若 `obj.method = 1` 会遮盖方法。需要强管控就用数据描述符。

## 面试怎么答

**Q：什么是描述符？它解决了什么？**
A：描述符是实现了 `__get__`/`__set__`/`__delete__` 的对象，挂在类属性上接管该属性的读写删。它是属性管控的底层协议——property、classmethod、staticmethod、cached_property 都是描述符实现的。适合把校验、懒加载、类型检查等逻辑从各业务类抽成可复用组件。

**Q：数据描述符和非数据描述符的区别？**
A：实现了 `__set__` 的是数据描述符；只有 `__get__` 的是非数据描述符。关键区别在查找优先级：数据描述符高于实例字典，非数据描述符低于实例字典。所以 property（数据描述符）无法被实例属性遮盖，而普通方法（非数据描述符）可以被遮盖。

**Q：property 本质是？**
A：property 就是一个内置的描述符类，内部用 `__get__`/`__set__`/`__delete__` 把 getter/setter 方法包装成描述符，挂到类属性上。所以访问 `obj.x` 会走描述符协议调用对应方法。

**Q：classmethod / staticmethod 怎么实现的？**
A：它们也是描述符。classmethod 的 `__get__` 返回绑定了类的可调用（自动传 cls）；staticmethod 的 `__get__` 原样返回函数（不绑定，无隐式首参）。
