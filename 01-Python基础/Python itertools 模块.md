---
created: 2026-07-31
tags: [Python基础/数据结构]
---

# Python itertools 模块

![[assets/itertools-tree.svg]]
*图示：组合生成器规模——`product`(n^r) 笛卡尔积、`permutations`(n!/(n-r)!) 全排列、`combinations`(不看顺序)、`combinations_with_replacement`(允许同元素)；均为惰性迭代器。*

## 概念：itertools 提供「内存友好的迭代器工厂」

`itertools` 里所有函数都返回**迭代器（惰性）**，按需产出元素，不一次性占满内存。它把常见的「排列组合、切片、分组、笛卡尔积」做成了高效 C 实现。配合 `[[Python 生成器与迭代器]]` 的惰性思想理解最佳。

粗略分三类：
- **无限迭代器**：`count`、`cycle`、`repeat`
- **终止于最短输入**：`chain`、`zip_longest`、`islice`、`filterfalse`
- **组合生成器**：`product`、`permutations`、`combinations`、`combinations_with_replacement`、`groupby`

## 用法一：无限迭代器

```python
import itertools

# count(start, step) 从 start 无限递增
for i in itertools.count(10, 2):
    if i > 16: break
    print(i)               # 10 12 14 16

# cycle 无限循环遍历
c = itertools.cycle("AB")
print([next(c) for _ in range(5)])   # ['A','B','A','B','A']

# repeat 重复某个值 n 次（不给 n 则无限）
print(list(itertools.repeat(7, 3)))   # [7, 7, 7]
```

⚠️ `count`/`cycle` 没有终点，必须自己用 `break`/切片限制，否则死循环。

## 用法二：chain / islice / zip_longest

```python
import itertools

# chain 把多个可迭代对象串成一条（不真正合并，惰性）
print(list(itertools.chain([1, 2], (3, 4), "ab")))   # [1, 2, 3, 4, 'a', 'b']

# islice 惰性切片（支持 start, stop, step），不生成完整列表
print(list(itertools.islice(range(10), 2, 8, 2)))     # [2, 4, 6]

# zip_longest 与内置 zip 相反：以最长输入为准，缺的补 fillvalue
print(list(itertools.zip_longest("AB", "123", fillvalue="-")))
# [('A','1'), ('B','2'), ('-','3')]
```

相比内置 `zip`（遇最短即停，见 [[Python 循环语句]]），`zip_longest` 保留长序列的剩余元素。

## 用法三：组合生成器（重点）

```python
import itertools

pool = "ABC"

# product 笛卡尔积（多个序列的每一种组合），repeat 表示自身重复几次
print(list(itertools.product(pool, repeat=2)))
# [('A','A'),('A','B'),('A','C'),('B','A')...]  共 3^2=9 个

# permutations 全排列（考虑顺序），长度 r
print(list(itertools.permutations(pool, 2)))     # 3*2=6 个，如 ('A','B')≠('B','A')

# combinations 组合（不考虑顺序），长度 r
print(list(itertools.combinations(pool, 2)))      # 3 个：AB, AC, BC

# combinations_with_replacement 允许重复元素
print(list(itertools.combinations_with_replacement(pool, 2)))
# 6 个：AA, AB, AC, BB, BC, CC
```

记忆：`product`=所有有序组合（可重复）；`permutations`=全排列（不重复、看顺序）；`combinations`=组合（不重复、不看顺序）；`combinations_with_replacement`=组合且允许同元素重复。

**规模警告**：这些生成器产出数量可能爆炸。`product(pool, repeat=10)` 对 62 字符会是 62^10 ≈ 8e17 个，千万别 `list()` 一次性展开。保持惰性、边产边处理。

## 用法四：groupby —— 按「相邻且相等」分组

```python
import itertools

data = [("a", 1), ("a", 2), ("b", 3), ("b", 4), ("a", 5)]
# ⚠️ groupby 只对「相邻相同 key」分组，通常要先排序
data.sort(key=lambda x: x[0])
for key, group in itertools.groupby(data, key=lambda x: x[0]):
    print(key, list(group))
# a [('a',1),('a',2)]
# b [('b',3),('b',4)]
# a [('a',5)]
```

**最容易踩的坑**：`groupby` 不全局分组，它只在 key 连续变化时切组。数据没排序就分组，会把相同 key 的不同片段拆开。所以**用 groupby 前几乎总要先按 key 排序**，或用 `defaultdict(list)`（见 [[Python collections 模块]]）做全局分组更省心。

> `groupby` 返回的 `group` 是迭代器，且**只在当前 key 区间内有效**——一旦进入下一个 key，前一个 group 迭代器就失效了。要保留就 `list(group)`。

## 用法五：实战——笛卡尔积 × 惰性处理

```python
import itertools

def valid(pair):
    return pair[0] != pair[1]

# 只处理满足条件的组合，不一次性展开
for a, b in itertools.product(range(1000), range(1000)):
    if a + b == 999:
        # 边产边消费，内存恒定
        pass
```

## 踩坑

1. **无限迭代器不 `break`**：`count`/`cycle` 必须有终止条件，否则卡死。
2. **`groupby` 忘了先排序**：相同 key 被拆成多个组。先 `sort`，或改用 `defaultdict`。
3. **`groupby` 的 group 迭代器提前失效**：跨 key 后旧 group 不可用，需要保存就立刻 `list()`。
4. **组合生成器直接 `list()` 海量结果**：数量指数级，内存爆炸。保持惰性、边产边消费。
5. **`chain` 与 `chain.from_iterable` 混淆**：`chain(a, b, c)` 接收多个可迭代对象；`chain.from_iterable([a, b, c])` 接收一个「可迭代对象的可迭代」，避免 `*args` 展开。
6. **`zip_longest` 忘设 fillvalue**：默认补 `None`，可能混入逻辑。

## 面试怎么答

**Q：itertools 的函数返回什么？有什么好处？**
A：都返回惰性迭代器，按需产出、不占满内存，适合处理大数据流。配合生成器思想，能在常数内存下完成切片、组合、分组。

**Q：product / permutations / combinations 的区别？**
A：product 是笛卡尔积（所有有序组合，允许重复）；permutations 是全排列（不重复、看顺序）；combinations 是组合（不重复、不看顺序）。combinations_with_replacement 额外允许同元素重复。

**Q：groupby 有什么注意事项？**
A：它只在「相邻相同 key」处切组，不是全局分组。使用前必须按 key 排序，否则相同 key 会被拆散；且每个 group 迭代器只在当前 key 期间有效，跨 key 后失效。
