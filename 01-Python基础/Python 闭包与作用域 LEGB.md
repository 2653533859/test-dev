---
created: 2026-07-31
tags: [Python基础/函数]
---

# Python 闭包与作用域 LEGB

![[assets/legb-closure.svg]]
*图示：名字按 LEGB（Local→Enclosing→Global→Builtin）由内到外查找；闭包靠 `__closure__` 里的 cell 把外层变量「冻结」带走。*

> 变量去哪找？为什么循环里绑定的 lambda 都拿到最后一个值？这背后是 Python 的“命名空间 + 作用域链 + 闭包 cell”机制。理解 LEGB 才算真正读懂变量解析。

## 概念

### 1. 命名空间（namespace）与作用域（scope）

- **命名空间**：名字到对象的映射，本质是个字典。Python 有几个独立的命名空间：局部、全局、内置、以及闭包的“外层”。
- **作用域**：一段代码里“名字可见”的区域。名字的查找按 **LEGB** 顺序进行。

### 2. LEGB 查找链

```
L  Local         —— 当前函数内部的局部变量
E  Enclosing     —— 包裹当前函数的外层函数的局部变量（嵌套函数时才有）
G  Global        —— 模块级（文件顶层）变量
B  Builtin       —— 内置名字（print/len/Exception…）
```

查找规则：先在 Local 找，没有就往 Enclosing 逐层找，再 Global，最后 Builtin；找到即停。

### 3. 赋值即声明局部（除非声明 nonlocal/global）

在函数内对变量 `x = ...` 赋值，Python 会**默认把 `x` 当作当前函数的局部变量**，而不是去外层找。这就导致“在赋值前引用”会 `UnboundLocalError`：

```python
x = 10
def f():
    print(x)      # UnboundLocalError!
    x = 20        # 因为这一行，x 被当成局部变量，上面 print 时它还“未绑定”
```

### 4. 闭包（closure）：内层函数捕获外层变量

当内层函数引用了**外层函数的局部变量**，即使外层函数已经返回，这些变量依然被保留——这就是闭包。原理：外层函数的局部变量被包装成 **cell 对象**，闭包通过 `func.__closure__` 持有这些 cell。

```python
def outer(n):
    def inner():
        return n * 2     # n 是自由变量，被闭包捕获
    return inner

f = outer(5)
print(f.__closure__[0].cell_contents)   # 5，变量被保留
print(f())                              # 10
```

### 5. `nonlocal` 与 `global`

- 想在内层函数**修改**外层（非全局）变量，用 `nonlocal n` 声明，否则会被当成新建局部变量。
- 想修改**模块级全局**变量，用 `global x`。
- 注意：`nonlocal`/`global` 只影响“赋值绑定”，**读取**外层变量不需要任何声明。

### 6. 延迟绑定（经典坑）

闭包捕获的是**变量本身**，不是它当时的**值**。如果闭包在将来才执行（如循环里收集 lambda），它读到的变量已经是最终值：

```python
funcs = [lambda: i for i in range(3)]
print([f() for f in funcs])     # [2, 2, 2]，全拿到最终的 i=2
```

修复：用默认参数把当前值**立即绑定**到 lambda 自己的局部：`lambda i=i: i`。

## 用法

```python
# 计数器的闭包实现
def make_counter():
    n = 0
    def inc():
        nonlocal n
        n += 1
        return n
    return inc

c = make_counter()
print(c(), c())                  # 1 2

# 立即绑定修复延迟绑定
funcs = [lambda i=i: i for i in range(3)]
print([f() for f in funcs])      # [0, 1, 2]

# global 修改模块级变量
total = 0
def add(x):
    global total
    total += x
```

## 踩坑

- **`UnboundLocalError`**：函数内“先读后写”同名单层变量会报错，因为赋值让该名成为局部；要么先赋值，要么用 `global`/`nonlocal` 声明。
- **`nonlocal` 找不到外层**：`nonlocal` 要求外层**存在**该变量（在 enclosing 作用域），否则 `SyntaxError`；它不会退回到 global。
- **`global` 污染模块**：滥用 `global` 让函数依赖/修改全局状态，测试时难以隔离、易串味，能用参数/返回值就别用。
- **延迟绑定**：循环 + lambda/闭包最常见坑，用默认参数或 `functools.partial` 立即绑定当前值。
- **调试闭包**：`func.__code__.co_freevars` 看捕获的变量名，`func.__closure__` 是 cell 元组取 `.cell_contents` 看值。
- **`global`/`nonlocal` 只管绑定**：读外层变量本就允许，别多写声明。

## 面试怎么答

LEGB 是变量查找顺序：局部→外层→全局→内置，找到即停。核心机制：函数内**赋值默认声明为局部变量**，所以“先读后写”同名会 `UnboundLocalError`；想改外层用 `nonlocal`、改全局用 `global`（二者只影响绑定，读不需声明）。

闭包是内层函数捕获外层局部变量，外层函数返回后变量仍存活（靠 cell 对象，`func.__closure__` 可见）。最经典坑是循环+lambda 的**延迟绑定**——闭包捕获变量本身而非当时值，修复用默认参数 `lambda i=i: i` 或 `functools.partial` 立即绑定。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/faq/programming.html#why-do-lambdas-defined-in-a-loop-with-different-values-all-return-the-same-result
- 相关笔记：[[Python 函数参数与调用]] [[Python 装饰器]] [[Python 推导式与表达式]]
