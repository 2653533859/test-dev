---
created: 2026-07-31
tags: [Python基础/语法]
---

# Python 条件控制与断言

> `if` 判断的不是“真/假”两个字，而是对象的“真值协议”。而 `assert` 在优化模式下会被整体删除——这条常被忽视，是用断言做关键校验的致命坑。

## 概念

### 1. 真值判定：来自 `__bool__` / `__len__`

`if x:` 等价于 `if bool(x):`。`bool(x)` 的规则：
1. 若对象实现了 `__bool__`，用它的返回值
2. 否则若实现了 `__len__`，`len(x) != 0` 为真（空容器/空串为假）
3. 否则为真

所以 `0`、`0.0`、`""`、`[]`、`{}`、`set()`、`None`、`False` 都是假；非零数字、非空容器为真。**不要用 `if x == True`**，直接用 `if x:`。

### 2. `assert` 会被优化模式删除

`assert cond, msg` 在字节码层面是一条 `ASSERT` 指令。**当用 `python -O`（或设 `PYTHONOPTIMIZE=1`）运行时，Python 会整体跳过所有 assert**，根本不执行 `cond` 求值。这意味着：
- assert 只适合“开发期自检/不可能发生”的断言
- **绝不能用 assert 做安全/业务关键校验**（权限、金额、外部输入），因为生产开了 `-O` 等于没校验

需要关键校验用显式 `if not cond: raise ValueError(...)`。

### 3. `match` / `case`（3.10+）：结构模式匹配

不是简单的 switch（Python 没有传统 switch）。它按**解构**匹配：能匹配字面量、类型、序列/映射结构、并绑定变量，还能加 `if` 守卫（guard）。

```python
match status:
    case 0: ...
    case 4 | 5: ...
    case [code, *_]: ...        # 序列解构
    case {"code": c}: ...       # 映射解构
    case _: ...                  # 通配
```

### 4. 三元与链式比较

`a if cond else b` 是表达式（详见 [[Python 推导式与表达式]]）。`a < x < b` 等价于 `a < x and x < b` 且 `x` 只求一次。

## 用法

```python
status = resp.get("code", -1)

if status == 0:
    print("ok")
elif status in (400, 404):
    print("client err")
else:
    print("other")

# 开发期自检（别用于关键校验）
assert status == 0, f"期望成功, 实际 {status}"

# match-case（3.10+）
match resp:
    case {"code": 0, "data": d}:
        print("拿到数据", d)
    case _:
        print("未匹配")
```

## 踩坑

- **`assert` 被 `-O` 删除**：关键校验（权限/金额/外部输入）绝不用 assert，用 `if not cond: raise`。测试里若用 pytest 的 assert，pytest 会重写 assert 提供详细对比，但生产 `-O` 仍会移除。
- **`if x == True` 不必要且易错**：`if x is True` 与 `if x:` 不等价（`x=1` 时前者 False 后者 True）；直接 `if x:`。
- **`else` 还能跟 for/while/try**：循环没被 `break` 才执行 `else`，少用之但面试爱考。
- **链式比较里的函数只调一次**：`0 < f() < 10` 中 `f()` 只调一次。
- **`match` 的 `_` 是通配**（不绑定），`case x:` 才绑定变量 `x`；guard `case p if p>0:` 在匹配后额外判断。
- **真值陷阱**：自定义对象若实现了 `__len__`，空时 `if obj` 为假，可能误判“未初始化”。

## 面试怎么答

条件判断基于真值协议：`bool(x)` 先看 `__bool__` 再看 `__len__`（空为假），所以 `0/""/[]/{}`/`None` 为假，直接用 `if x:` 别写 `== True`。

最关键的坑：`assert` 在 `python -O` 优化模式下被**整体删除**，不做求值——所以关键业务/安全校验绝不能用 assert，用 `if not cond: raise`。3.10+ 有 `match/case` 结构模式匹配（解构+守卫），不是传统 switch。`else` 可跟循环（未被 break 才执行）。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/reference/compound_stmts.html#if
- 相关笔记：[[Python 推导式与表达式]] [[Python 异常处理]]
