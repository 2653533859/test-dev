---
created: 2026-07-31
tags: [数据库/索引]
---

# MySQL 联合索引与最左前缀

> 「索引 `(a, b, c)`，哪些查询用得上」是数据库面试的必考题。答案不用背，理解排序规则就能现场推导。

![[assets/leftmost-prefix.svg]]
*图示：联合索引叶子节点按 `(a, b, c)` 字典序排列——a 全局有序，b 只在同一个 a 内有序，c 只在同一个 (a, b) 内有序，所以少了左边的列就无法二分定位。*

## 概念

### 联合索引的排序规则 = 字典序

联合索引 `(a, b, c)` 的叶子节点，是按 **`a` 优先、`a` 相同看 `b`、`b` 相同看 `c`** 的顺序排列的，完全等同于按「姓、名、字」排序的人名册：

```text
(1, 1, 1) → (1, 1, 9) → (1, 2, 3) → (2, 1, 5) → (2, 3, 1) → (3, 0, 7)
 ↑ a 列：1 1 1 2 2 3          全局单调不减 ✅
 ↑ b 列：1 1 2 1 3 0          只在 a 相同的段内有序 ⚠️
 ↑ c 列：1 9 3 5 1 7          只在 (a,b) 相同的段内有序 ⚠️
```

**B+ 树的查找依赖有序性做二分**。所以：

- 有 `a` 的条件 → 能在整棵树上二分定位 → 用得上；
- 没有 `a` 只有 `b` → `b` 在整棵树里是乱的 → **无法定位，索引失效**；
- 有 `a` 和 `c` 但没 `b` → 能用 `a` 定位，但定位到 `a=1` 这一段后，`c` 在这一段里是乱的（因为中间隔着 `b`）→ **`c` 只能作为过滤条件（ICP），不能用于定位**。

这就是**最左前缀原则**：**必须从索引的最左列开始，且不能跳过中间的列**。

### 范围条件会「截断」后续列

```text
WHERE a = 1 AND b > 5 AND c = 3
```

用 `a = 1` 定位到一段，再用 `b > 5` 定位到子区间 —— 但这个子区间里包含 `b = 6`、`b = 7`、`b = 8`……**每一个 b 值内部 c 各自独立有序，整体上 c 是乱的**，所以 `c` 无法继续二分。

**规则**：**等值条件可以一路往右延伸，遇到第一个范围条件（`>` `<` `>=` `<=` `BETWEEN` `LIKE 'x%'`）就停止。**

由此推出索引设计的核心原则：**等值列放左边，范围列放右边**。

### 索引列顺序怎么定

优先级从高到低：

1. **能命中最多查询的列放最左**（比如所有查询都带 `tenant_id`）；
2. **等值查询列在前，范围查询列在后**；
3. **选择性高（区分度大）的列在前**——能更快缩小结果集；
4. **`ORDER BY` / `GROUP BY` 的列考虑放进来**，避免 `filesort`。

## 用法

```sql
CREATE TABLE `orders` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`    BIGINT UNSIGNED NOT NULL,
  `status`     TINYINT UNSIGNED NOT NULL,
  `created_at` DATETIME        NOT NULL,
  `amount`     DECIMAL(10, 2)  NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_u_s_c` (`user_id`, `status`, `created_at`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;
```

### 逐条推演哪些查询能用上索引

```sql
-- ✅ 全用：user_id + status + created_at
EXPLAIN SELECT * FROM orders
WHERE user_id = 1 AND status = 1 AND created_at > '2026-01-01';
-- key_len 覆盖三列

-- ✅ 用前两列
EXPLAIN SELECT * FROM orders WHERE user_id = 1 AND status = 1;

-- ✅ 只用第一列
EXPLAIN SELECT * FROM orders WHERE user_id = 1;

-- ✅ 顺序颠倒也没关系！优化器会自动重排 WHERE 条件
EXPLAIN SELECT * FROM orders WHERE status = 1 AND user_id = 1;
-- 「最左前缀」说的是索引定义的列顺序，不是 SQL 里的书写顺序

-- ⚠️ 跳过 status：只能用 user_id 定位，created_at 靠 ICP 过滤
EXPLAIN SELECT * FROM orders WHERE user_id = 1 AND created_at > '2026-01-01';
-- Extra: Using index condition

-- ⚠️ 范围截断：user_id、status 用于定位，created_at 无法定位
EXPLAIN SELECT * FROM orders
WHERE user_id = 1 AND status > 0 AND created_at = '2026-07-31 10:00:00';

-- ❌ 缺最左列：完全用不上，type = ALL
EXPLAIN SELECT * FROM orders WHERE status = 1 AND created_at > '2026-01-01';
```

### 用 key_len 验证到底用了几列

`EXPLAIN` 的 `key_len` 精确告诉你**索引里有几列参与了定位**。计算规则：

```text
列本身的字节数
  + 1（该列允许 NULL 时的标志位）
  + 2（变长类型 VARCHAR/VARBINARY 的长度前缀）

BIGINT NOT NULL          → 8
TINYINT UNSIGNED NOT NULL→ 1
DATETIME NOT NULL        → 5（MySQL 5.6.4+）
VARCHAR(32) NOT NULL utf8mb4 → 32 × 4 + 2 = 130
VARCHAR(32) NULL utf8mb4     → 32 × 4 + 2 + 1 = 131
```

于是本例中：

```text
key_len = 8   → 只用了 user_id
key_len = 9   → user_id + status
key_len = 14  → user_id + status + created_at
```

**这是判断「索引究竟用了几列」最可靠的手段**，比看 `key` 有没有值靠谱得多。

### 覆盖索引 + 联合索引的组合拳

```sql
-- 常见查询：查某用户已支付订单的总金额
SELECT SUM(amount) FROM orders WHERE user_id = 1 AND status = 1;

-- 当前索引 (user_id, status, created_at) 不含 amount → 要回表
-- 把 amount 加到索引末尾，变成覆盖索引
ALTER TABLE orders ADD KEY `idx_u_s_amt` (`user_id`, `status`, `amount`);
-- Extra: Using index，完全不回表
```

放在索引末尾的 `amount` 不参与定位，只是「搭便车」被带到叶子上，这种做法有时叫「索引附加列」。

### ORDER BY 也要遵守最左前缀

```sql
-- ✅ 排序方向一致 + 满足最左前缀 → 索引天然有序，无需 filesort
SELECT * FROM orders WHERE user_id = 1 ORDER BY status, created_at;

-- ❌ 跳过 status 排序 → Using filesort
SELECT * FROM orders WHERE user_id = 1 ORDER BY created_at;

-- ❌ 混合排序方向（MySQL 8.0 之前）→ Using filesort
SELECT * FROM orders WHERE user_id = 1 ORDER BY status ASC, created_at DESC;
-- MySQL 8.0 支持降序索引，可以这样建：
ALTER TABLE orders ADD KEY `idx_mix` (`user_id`, `status` ASC, `created_at` DESC);
```

### 索引跳跃扫描（MySQL 8.0.13+）

8.0 引入 **Index Skip Scan**，在最左列**基数很低**时，可以枚举最左列的所有值，对每个值分别做一次范围扫描，从而在缺失最左列条件时也能用上索引：

```sql
-- 索引 (status, created_at)，status 只有 0/1/2/3 四个值
SELECT * FROM orders WHERE created_at > '2026-01-01';
-- Extra: Using index for skip scan
-- 相当于自动改写成 status IN (0,1,2,3) AND created_at > ...
```

但**只在最左列基数极低时才可能生效**，不能当成最左前缀失效的兜底方案。

### 联合索引 vs 多个单列索引

```sql
-- 方案 A：三个单列索引
KEY idx_u (user_id), KEY idx_s (status), KEY idx_c (created_at)

-- 方案 B：一个联合索引
KEY idx_u_s_c (user_id, status, created_at)
```

查询 `WHERE user_id = 1 AND status = 1` 时：

- 方案 A：优化器通常**只能选一个索引**（选择性最高的那个），另一个条件回表后过滤。少数情况会用 **index merge**（对两个索引的结果取交集），但要额外做集合运算，效率不如联合索引。
- 方案 B：一次定位直达，还可能覆盖。

**结论：多条件组合查询优先建联合索引，而不是给每列都建单列索引。**

## 踩坑

1. **以为 `WHERE` 的书写顺序影响索引**。不影响，优化器会重排等值条件。真正有影响的是**索引定义的列顺序**和**条件的类型（等值还是范围）**。
2. **范围条件放在了索引中间**。`(status, created_at, user_id)` 遇到 `status = 1 AND created_at > x AND user_id = 1`，`user_id` 就废了。调整为 `(status, user_id, created_at)` 三列全用上。
3. **`LIKE '%关键字'` 让最左列失效**。前缀通配等价于没有左边界，B+ 树无从定位。`LIKE '关键字%'` 则可以（相当于范围条件）。
4. **索引列上做运算 / 函数**。`WHERE DATE(created_at) = '2026-07-31'`、`WHERE user_id + 1 = 2`，索引直接失效——因为索引里存的是原值，不是函数结果。改成范围条件或建函数索引（8.0.13+）。
5. **隐式类型转换**。`user_id` 是 `BIGINT`，写 `WHERE user_id = '1'` 没事（字符串转数字），但如果列是 `VARCHAR` 而条件传数字 `WHERE phone = 13800138000`，MySQL 会把**列**转成数字，导致索引失效。
6. **`OR` 连接的条件只要有一个没索引，整体失效**。`WHERE user_id = 1 OR remark = 'x'`，`remark` 无索引 → 全表扫。改用 `UNION ALL` 拆开。
7. **只看 `key` 不看 `key_len`**。`EXPLAIN` 显示走了 `idx_u_s_c` 不代表三列都用上了，`key_len` 才是真相。
8. **联合索引列太多**。超过 5 列后，索引体积逼近数据本身，写入代价高、Buffer Pool 命中率下降，收益却很小。
9. **`NULL` 值让 key_len 多 1 字节**，算 `key_len` 时忘了这一位会误判用了几列。这也是推荐字段 `NOT NULL` 的一个附带理由。
10. **冗余索引**。已有 `(a, b, c)` 就不需要再建 `(a)` 和 `(a, b)`，它们是前者的前缀，完全被覆盖，白白增加写入成本。可用 `pt-duplicate-key-checker` 检测。

## 面试怎么答

**Q：联合索引 `(a, b, c)`，哪些查询能用上索引？**
A：核心是最左前缀原则。`a`、`a+b`、`a+b+c` 都能用；`b`、`c`、`b+c` 完全用不上；`a+c` 只能用 `a` 定位，`c` 通过索引下推做过滤。原因在于联合索引叶子节点是按 `(a, b, c)` 字典序排的，`a` 全局有序，`b` 只在相同 `a` 内有序，缺了 `a` 的话 `b` 在整棵树里是散乱的，B+ 树无法二分定位。另外要补充两点：一是 `WHERE` 里条件的书写顺序不影响，优化器会重排；二是遇到范围条件会截断，比如 `a = 1 AND b > 5 AND c = 3`，`c` 用不上，因为多个 `b` 值区间内的 `c` 整体无序。

**Q：为什么范围查询后面的列用不了索引？**
A：因为有序性断了。索引按字典序排列，`b` 的值确定后 `c` 才有序。当 `b` 是范围条件时，结果集横跨多个 `b` 值，每段内部 `c` 各自有序，但拼起来就乱了，无法继续做二分定位。所以设计索引时要把等值列放前面、范围列放最后。

**Q：怎么验证一条 SQL 到底用了联合索引的几列？**
A：看 `EXPLAIN` 的 `key_len`。它等于参与定位的各列字节数之和，规则是列类型字节数，可为 `NULL` 加 1 字节标志位，变长类型再加 2 字节长度前缀。比如 `(user_id BIGINT NOT NULL, status TINYINT NOT NULL, created_at DATETIME NOT NULL)`，`key_len` 是 8 就只用了第一列，9 是前两列，14 是三列全用。只看 `key` 字段有值是不够的，那只说明索引被选中了，不代表所有列都参与定位。

**Q：建一个联合索引好还是建多个单列索引好？**
A：如果查询经常是多条件组合，优先建联合索引。多个单列索引时，优化器通常只能选一个用，其余条件要回表后过滤；虽然有 index merge 优化可以对多个索引的结果做交并集，但要额外的集合运算和排序，成本高于一次联合索引定位。而且联合索引更容易构成覆盖索引。反过来，如果各列都是独立单独查询的，那就建单列索引。还有一点，已有 `(a, b, c)` 的情况下再建 `(a)`、`(a, b)` 是冗余索引，只会拖慢写入。

**Q：索引跳跃扫描是什么？**
A：MySQL 8.0.13 引入的优化。当联合索引的最左列基数很低（比如只有几个枚举值）时，即使查询没带最左列条件，优化器也可以枚举最左列的所有取值，对每个值做一次范围扫描，相当于自动补上 `IN` 条件，`Extra` 显示 `Using index for skip scan`。但它只在最左列基数极低时才划算，不能依赖它来兜底最左前缀失效。

## 参考

- [MySQL 8.0 多列索引](https://dev.mysql.com/doc/refman/8.0/en/multiple-column-indexes.html)
- [MySQL 8.0 Skip Scan 优化](https://dev.mysql.com/doc/refman/8.0/en/range-optimization.html#range-access-skip-scan)
- [PostgreSQL 多列索引与最左前缀](https://www.postgresql.org/docs/current/indexes-multicolumn.html)
- 相关笔记：[[MySQL B+ 树索引结构与查找]]、[[MySQL 索引失效的常见场景]]、[[MySQL EXPLAIN 执行计划解读]]、[[MySQL 聚簇索引与二级索引回表]]
