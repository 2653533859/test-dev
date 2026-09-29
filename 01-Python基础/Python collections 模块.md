---
created: 2026-07-31
tags: [Python基础/数据结构]
---

# Python collections 模块

## 概念：collections 是「针对常见场景优化的容器」

内置的 `list`/`dict`/`set`/`tuple` 够用，但有些高频场景用它们写起来啰嗦或效率低。`collections` 提供了一批**专门容器**，本质是对内置类型的封装/特化，解决「计数、有序字典、默认取值、双端队列、具名元组」等痛点。

## 用法一：Counter —— 计数神器

```python
from collections import Counter

words = ["a", "b", "a", "c", "a", "b"]
c = Counter(words)
print(c)                 # Counter({'a': 3, 'b': 2, 'c': 1})

# 最常见 top N
print(c.most_common(2))  # [('a', 3), ('b', 2)]

# 缺失键返回 0，不会 KeyError
print(c["z"])            # 0

# 支持集合式运算
print(c + Counter({"a": 1}))   # Counter({'a': 4, ...})
```

原理：`Counter` 是 `dict` 子类，重写了缺失键返回 0，并提供了计数相关的便捷方法。适合词频统计、投票计数、缺失值统计。

## 用法二：defaultdict —— 访问即初始化

```python
from collections import defaultdict

# 普通 dict 统计分组要写判断；defaultdict 自动建空容器
groups = defaultdict(list)
for key, val in [("a", 1), ("a", 2), ("b", 3)]:
    groups[key].append(val)     # key 不存在时自动 defaultdict(list) → []
print(groups)                   # defaultdict(<class 'list'>, {'a': [1, 2], 'b': [3]})

# 注意：default_factory 的值是「工厂函数」，每次缺失都调用它
dd = defaultdict(int)           # int() → 0
dd["x"] += 1
```

**和 `dict.setdefault` 的区别**：`setdefault(k, [])` 每次都会构造一个空列表（即使键已存在，也白建一个），`defaultdict` 只在真正缺失时调用工厂函数，更省、更干净。详见 [[Python 字典方法与操作]] 的 `setdefault`。

## 用法三：deque —— 双端队列

```python
from collections import deque

dq = deque([1, 2, 3])
dq.append(4)          # 右端入
dq.appendleft(0)      # 左端入
dq.pop()              # 右端出 → 4
dq.popleft()          # 左端出 → 0

# 有界队列：满了最左被挤掉
log = deque(maxlen=3)
for i in range(10):
    log.append(i)
print(log)            # deque([7, 8, 9], maxlen=3)
```

**为什么不用 `list` 做队列**：`list.pop(0)` 删头部是 O(n)（要搬移后面所有元素）；`deque.popleft()` 是 O(1)，因为底层是双向链表式结构。做 BFS、滑动窗口、历史记录缓冲时用 `deque`。

## 用法四：OrderedDict —— 保序字典（历史角色）

```python
from collections import OrderedDict

od = OrderedDict()
od["b"] = 2
od["a"] = 1
print(list(od.keys()))    # ['b', 'a'] —— 按插入顺序
```

**重要变化**：从 Python 3.7 起，普通 `dict` **已经保证插入顺序**（详见 [[Python 字典方法与操作]] 的 compact dict）。所以 `OrderedDict` 现在主要价值为：① 需要 `move_to_end`/`popitem(last=...)` 等顺序操作；② 需要「相等时还要求顺序一致」（普通 dict 只比键值，不比顺序）。新代码一般直接用语普通 `dict` 即可。

## 用法五：namedtuple —— 轻量具名元组

```python
from collections import namedtuple

Point = namedtuple("Point", ["x", "y"])
p = Point(1, 2)
print(p.x, p.y)            # 1 2（可用名字访问，不用 p[0]）
print(p[0])                # 1（仍是元组，支持下标）
print(p._asdict())         # {'x': 1, 'y': 2}
```

`namedtuple` 是**元组子类**，不可变、轻量、可哈希，比字典省内存，适合当「不可变数据记录」。需要可变性就用 `dataclasses`（见 [[Python dataclasses]]）。

## 用法六：ChainMap —— 多字典「视图合并」

```python
from collections import ChainMap

defaults = {"color": "红", "size": "M"}
user = {"size": "L"}
cm = ChainMap(user, defaults)   # 查找顺序：先 user 后 defaults
print(cm["size"])              # L（user 覆盖）
print(cm["color"])             # 红（fallback 到 defaults）
```

`ChainMap` 不真正合并数据，而是把多个 dict 串成查找链，命中第一个就返回。适合「配置优先级」（用户配置覆盖默认配置）场景，零拷贝、省内存。

## 踩坑

1. **`defaultdict` 的工厂函数会「无中生有」**：访问任意不存在的键都会创建默认值，遍历时可能多出意料之外的键。要警惕只「读」就写入了。
2. **`Counter` 缺失键返回 0**：这是特性，但若误把 `c[k] += 1` 当成「已存在才加」，会凭空造出计数项。
3. **`deque` 当栈用别混 `pop`/`popleft`**：`pop()` 是右端，`popleft()` 是左端，方向搞反逻辑就错。
4. **`namedtuple` 不可变**：`p.x = 3` 会报 `AttributeError`，需要改字段就新建或用 dataclass。
5. **还把 `OrderedDict` 当「保序」唯一手段**：3.7+ 普通 dict 已保序，多数情况不需要它。
6. **`most_common` 在大 Counter 上频繁调用**：排序有成本，热路径注意。

## 面试怎么答

**Q：Counter 和 defaultdict 有什么区别？**
A：Counter 是「计数专用」的 dict 子类，键缺失返回 0、提供 `most_common` 等计数方法；defaultdict 是「访问缺失键自动调工厂函数初始化」的 dict 子类，用途更通用（如自动建列表分组）。

**Q：什么时候用 deque 而不是 list？**
A：需要频繁在两端增删（队列、BFS、滑动窗口）时用 deque，因为 `popleft`/`appendleft` 是 O(1)；而 list 头部删除是 O(n) 搬移。

**Q：OrderedDict 还有必要用吗？**
A：Python 3.7+ 普通 dict 已保证插入顺序，所以单纯「保序」不需要它。仅当你需要顺序相关操作（`move_to_end`、`popitem` 顺序控制）或要求「相等含顺序」时才用 OrderedDict。

**Q：namedtuple 和 dataclass 怎么选？**
A：namedtuple 不可变、极轻量、可哈希，适合不可变数据记录；dataclass 默认可变、可配默认值/校验/比较方法，适合需要修改或方法的数据对象。
