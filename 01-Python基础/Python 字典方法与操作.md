---
created: 2026-07-31
tags: [Python基础/容器]
---

# Python 字典方法与操作

![[assets/hashtable.svg]]
*图示：dict 是哈希表——`hash(key)` 定位槽位，冲突时开放寻址/挂链，负载因子过高触发扩容 rehash；键必须可哈希。*

> 字典是接口响应、测试用例、配置项的通用载体。它的底层是哈希表，理解“键必须可哈希”“3.7+ 为何保序”“扩容 rehash”，才能解释那些看似诡异的行为。

## 概念

### 1. 字典的底层：哈希表（hash table）

`dict` 用**开放寻址的哈希表**实现：对每个键算 `hash(key)` 得到桶位置，值存在该桶。这带来：

- 平均 `get`/`set`/`in` 是 **O(1)**
- 键必须**可哈希**（`__hash__` 稳定且 `__eq__` 一致），所以 `list`/`dict`/`set` 不能做键
- 哈希冲突时用探测法找下一个空桶

### 2. 为什么键必须可哈希

如果键是可变对象（如 list），它进字典后内容变了，`hash` 就变了，再次查找时算出的桶位置和当初存的位置不一致，字典就“找不到”它了。所以 Python 直接禁止可变对象哈希：`hash([1,2])` → `TypeError`。需要复合键就用 `tuple`（元素都不可变）。

### 3. 3.7+ 为什么保序（compact dict）

老版本 dict 不保证顺序。CPython 3.7 起用 **compact dict**：底层除了哈希表，还维护一个**按插入顺序的索引数组**。这样遍历顺序 = 插入顺序，且不牺牲查找性能。注意：这是实现细节，但已成为语言保证（3.7 起）。`{**a, **b}` 合并、dict 推导都遵循。

### 4. 扩容与 rehash

装填率（元素数/桶数）过高时，dict 会**翻倍扩容并 rehash**（重新计算所有键的桶位置）。所以插入是均摊 O(1)，但偶尔一次插入会触发全量 rehash（较慢）。`d.popitem()` 在 3.7+ 默认删**最后插入**的键值对（LIFO），旧版是随机的。

### 5. 取数语义

- `d[k]`：键不存在抛 `KeyError`
- `d.get(k, default)`：安全，缺失返回 default（默认 `None`）
- `d.setdefault(k, default)`：缺失则**写入** `k: default` 并返回 default，适合“懒初始化嵌套结构”
- `d.pop(k, default)`：删并返回值，缺失给 default（不给则 KeyError）
- `d.update(other)` / `d | other`（3.9+）：合并

### 6. 视图对象 `keys/values/items`

返回的是**动态视图**，会实时反映字典变化；不是列表，要固定快照用 `list(d.keys())`。

## 用法

```python
resp = {"code": 0, "msg": "ok", "data": {"id": 1}}

uid = resp.get("data", {}).get("id")     # 嵌套安全取数
print(resp.get("trace", "none"))         # "none"

groups = {}
groups.setdefault("smoke", []).append("login")   # 懒建分组

for k, v in resp.items():
    print(k, v)

merged = resp | {"env": "test"}          # 3.9+ 合并，返回新 dict
```

## 踩坑

- **`d[k]` 缺失抛 `KeyError`**：不确定键存在用 `get`；或先 `if k in d`。
- **遍历中增删键 → `RuntimeError`**：`for k in d: if bad: del d[k]` 会报错；先 `list(d)` 复制键再删。
- **同一键重复赋值后者覆盖**：`{'a':1,'a':2}` → `{'a':2}`。
- **视图是动态的**：`ks = d.keys()` 后改 `d`，`ks` 跟着变；要静态快照 `list(d.keys())`。
- **`setdefault` 的默认值是同一个对象引用**：`setdefault("x", [])` 每次命中同一空列表；但若传可变默认且多次调用，注意共享（一般无碍，因为只在缺失时写入）。
- **`copy()` 是浅拷贝**：嵌套 dict 仍共享，深拷贝见 [[Python 浅拷贝与深拷贝]]。
- **键必须可哈希**：复合键用 `tuple`，别用 `list`。

## 面试怎么答

dict 底层是哈希表（开放寻址），平均 O(1) 查找；键必须可哈希（hash 稳定+eq 一致），所以 list/dict/set 不能做键，复合键用 tuple。3.7+ 保序是 compact dict（维护插入顺序索引），已成语言保证。

取数：`d[k]` 缺失抛 KeyError，用 `get` 安全；`setdefault` 缺失则写入默认并返回，适合懒建嵌套结构；`popitem` 删最后插入对。遍历用 `items()`；遍历中删键要遍历键副本（否则 RuntimeError）。视图对象动态反映变化。扩容时 rehash。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/tutorial/datastructures.html#dictionaries
- 相关笔记：[[Python 浅拷贝与深拷贝]] [[Python 可变对象与不可变对象]] [[Python 推导式与表达式]]
