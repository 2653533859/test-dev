---
created: 2026-07-31
tags: [Python基础/容器]
---

# Python 列表方法与操作

![[assets/dynamic-array.svg]]
*图示：list 是动态数组，append 偶尔触发 O(n) 扩容拷贝（均摊 O(1)）；头部 insert/pop(0) 是 O(n) 搬移。*

> 列表是测试数据处理的第一容器。它的性能特征（哪些操作 O(1)、哪些 O(n)）和“可变序列”的底层实现（动态数组），直接决定你写批量处理时快不快、坑不坑。

## 概念

### 1. 列表的底层：动态数组（dynamic array）

CPython 的 `list` 不是链表，而是一个**指向对象的指针数组**（类似 C++ `vector`）。这带来：

- 按索引访问/赋值 `lst[i]` 是 **O(1)**（直接算偏移）
- 末尾 `append` / `pop()` 平均 **O(1)**（均摊，见扩容）
- 中间 `insert(i, x)` / `pop(i)` / `remove` 是 **O(n)**（要搬移后续元素）

### 2. 扩容策略：超额分配

`append` 快，是因为底层预分配了比当前元素更多的容量。`list` 满时，会申请一块**约 1.125 倍**更大的内存，把旧元素拷过去，再继续 append。所以单次 `append` 偶尔较慢，但**均摊**是 O(1)。`sys.getsizeof(lst)` 能看到容量（`lst.__sizeof__()`）比“元素个数×指针”大。

### 3. 切片创建新列表（浅拷贝）

`lst[a:b]` 返回一个**新列表**，元素是原对象的引用（浅拷贝，见 [[Python 浅拷贝与深拷贝]]）。因为列表可变，切片必须复制一份，否则“改切片影响原列表”会破坏不可变语义。

### 4. `+` 与 `*`

- `a + b`：**新建**一个列表并拷贝两边元素（O(n+m)），不改原列表。
- `a += b` / `a.extend(b)`：**原地**扩展（尽量复用容量），比 `a = a + b` 省一次拷贝。
- `a * n`：重复 n 份；**嵌套列表要小心**——`[[]] * 3` 是三个指向**同一个**内层 list 的引用，改一个全变。要独立副本用 `[[] for _ in range(3)]`。

### 5. `sort` 用 Timsort，原地

`list.sort()` 是**原地**排序（返回 `None`），算法是 Timsort（归并+插入的混合，对部分有序数据极快）。要新列表用内置 `sorted()`。`key=` 接收函数做排序依据，`reverse=True` 降序。

### 6. `copy()` / `clear()`

`copy()` 是浅拷贝；`clear()` 清空（保留容量，不缩容）。

## 用法

```python
import sys
nums = []
for i in range(5):
    nums.append(i)
print(sys.getsizeof(nums))        # 容量比 5 个指针大（预分配）

nums.sort(key=lambda x: -x)        # 原地降序
new = sorted(nums)                 # 新列表

# 嵌套列表的 * 陷阱
bad = [[]] * 3
bad[0].append(1)
print(bad)                         # [[1], [1], [1]] 三个指向同一 list！

good = [[] for _ in range(3)]      # 各自独立
```

## 踩坑

- **`append` vs `extend`**：`append([1,2])` 把整个列表当**一个元素**加进去；`extend([1,2])` 展开。混淆会产生“意外嵌套”。
- **`sort` 返回 `None`**：`sorted_list = nums.sort()` 得到 `None`；要新列表用 `sorted(nums)`。
- **遍历中删元素会跳过**：`for x in lst: if bad: lst.remove(x)` 会漏删（索引错位）；改遍历副本 `for x in lst[:]`、倒序遍历、或列表推导重建。
- **切片是浅拷贝**：`sub = lst[1:3]` 后改 `sub[0]`（若元素可变）会影响原列表里的同一对象；要隔离用 `copy.deepcopy`。
- **`[[]] * n` 共享内层**：需要独立嵌套结构用推导式。
- **`pop(0)` / `insert(0, x)` 是 O(n)**：频繁在头部增删改用 `collections.deque`（见 [[Python collections 模块]]）。
- **大列表 `in` 是 O(n)**：频繁成员判断改用 `set`。

## 面试怎么答

列表底层是动态数组（指针数组），所以索引 O(1)、末尾 append/pop 均摊 O(1)、中间 insert/remove O(n)。append 快靠超额分配（约 1.125 倍扩容）。`sort` 原地返回 None、用 Timsort，要新列表用 `sorted`；`+` 新建列表、`+=`/`extend` 原地。切片和 `copy()` 是浅拷贝。经典坑：append/extend 区别、遍历中删元素漏删、`[[]]*n` 共享内层、pop(0) 慢改用 deque。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/tutorial/datastructures.html#more-on-lists
- 相关笔记：[[Python 浅拷贝与深拷贝]] [[Python 字典方法与操作]] [[Python collections 模块]]
