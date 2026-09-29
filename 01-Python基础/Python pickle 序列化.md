---
created: 2026-07-31
tags: [Python基础/标准库]
---

# Python pickle 序列化

![[assets/pickle-graph.svg]]
*图示：pickle 序列化整个对象图（保留类型/引用/循环）；但攻击对象可借 `__reduce__` 在反序列化时执行任意代码（RCE），绝不能 loads 不可信数据。*

> pickle 能把任意 Python 对象（含类实例、函数引用）原样存盘/传输，但它和 json 的定位完全不同，且有“反序列化不可信数据 = 远程代码执行”的致命红线。原理上讲清楚，才知道什么时候该用、什么时候碰都不能碰。

## 概念

### 1. pickle 是什么

`pickle` 把 Python **对象图**序列化为一段 **bytes**（二进制协议）。`dump`/`dumps` 序列化，`load`/`loads` 反序列化。与 json 只能处理基础类型不同，pickle 支持：
- 自定义类实例、嵌套结构
- 部分内建对象（`datetime`、集合等）

### 2. 底层：靠 `__reduce__` 重建对象

pickle 不是“保存对象内存”，而是通过对象的 `__reduce__()`（或 `__reduce_ex__`）拿到“**重建它需要的 callable + 参数**”，序列化的是这个“重建配方”。反序列化时调用该 callable 重建对象。这就是为什么：
- 类实例 pickle 存的是“按名引用”（模块路径+类名），反序列化时要能 import 到这个类
- 自定义对象可通过实现 `__reduce__` 控制序列化行为

### 3. ⚠️ 安全红线：不可信数据 = RCE

反序列化时，pickle 会**执行 `__reduce__` 返回的代码**来重建对象。如果一个 pickle 字节流是攻击者构造的，它能在反序列化时执行任意 Python 代码——等同于远程代码执行（RCE）。因此铁律：

> **绝不**对外部来源（网络、用户上传、不可信文件）的数据调用 `pickle.loads` / `pickle.load`。

跨系统交换用 `json`（文本、安全、跨语言）。

### 4. 与 json 对比

| | pickle | json |
|---|---|---|
| 类型 | 任意 Python 对象 | 基础类型（object/array/str/num/bool/null） |
| 格式 | 二进制 | 文本 |
| 跨语言 | 否（Python 专用） | 是 |
| 安全 | **不可信数据危险** | 安全 |
| 可读性 | 不可读 | 可读 |

### 5. 协议与局限

- 有协议版本（`protocol=`），不同 Python 版本/协议可能不兼容；跨环境存要固定或升最新。
- 不能 pickle 文件句柄、线程锁、`lambda`、部分 C 扩展对象（`PicklingError`）。
- 类定义变动（字段/路径改了）会导致 unpickle 失败（`AttributeError`）。

## 用法

```python
import pickle
from dataclasses import dataclass

@dataclass
class Case:
    name: str
    steps: int

cases = [Case("登录", 3), Case("支付", 5)]

with open("cases.pkl", "wb") as f:       # 必须二进制模式
    pickle.dump(cases, f)

with open("cases.pkl", "rb") as f:
    loaded = pickle.load(f)
print(loaded[0].name)                     # 登录
```

## 踩坑

- **反序列化不可信数据 = RCE**：永远别 `pickle.loads` 外部/网络/用户数据；用 json 做外部交换。
- **类是按名引用**：反序列化时类路径必须可 import，类定义改了会 `AttributeError`；长期存储不如 json 稳。
- **跨版本/协议不兼容**：`dump(..., protocol=...)` 注意；升级 Python 后旧 pkl 可能 load 失败。
- **不能 pickle 的资源**：文件句柄/锁/`lambda` 会 `PicklingError`。
- **大对象慢且占空间**：缓存/传参优先考虑 json 或专用格式。
- **二进制不可读**：调试时不友好；要人读用 json。

## 面试怎么答

pickle 把任意 Python 对象图序列化为 bytes（二进制、Python 专用），靠 `__reduce__` 拿到“重建 callable+参数”来存/取，支持 json 不支持的对象。

最大红线：**反序列化不可信数据会执行任意代码（RCE）**，绝不对外部数据 unpickle，外部交换用 json。类是按名引用，定义变动会 unpickle 失败；跨版本协议不兼容；文件句柄/锁/lambda 不能 pickle。一句话对比：json 跨语言、安全、基础类型；pickle 灵活、专用、有安全红线。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/library/pickle.html
- 相关笔记：[[Python json 序列化]] [[Python dataclasses]]
