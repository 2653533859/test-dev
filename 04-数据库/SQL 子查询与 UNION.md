---
created: 2026-07-31
tags: [数据库/SQL]
---

# SQL 子查询与 UNION

> 子查询是「把一次查询的结果当成另一次查询的输入」，UNION 是「把多次查询的结果竖着摞起来」。前者容易写出性能灾难，后者容易踩去重的坑。

## 概念

### 子查询的三种形态

按**返回值的形状**分类，决定了它能出现在哪里、能配什么运算符：

| 形态 | 返回 | 可用位置 | 配套运算符 |
|------|------|----------|-----------|
| 标量子查询 | 1 行 1 列 | `SELECT` / `WHERE` / `HAVING` | `=` `>` `<` |
| 列子查询 | N 行 1 列 | `WHERE` | `IN` / `ANY` / `ALL` / `EXISTS` |
| 表子查询（派生表） | N 行 M 列 | `FROM` | 必须起别名 |

### 相关子查询 vs 非相关子查询

这是**性能的分水岭**：

- **非相关子查询**：子查询不引用外层的列，可以独立执行。数据库**只算一次**，把结果缓存成常量（物化）。
- **相关子查询（DEPENDENT SUBQUERY）**：子查询里引用了外层的列，**外层每扫一行就要重新执行一遍子查询**，复杂度 O(n × m)。

```sql
-- 非相关：内层独立，只跑一次
SELECT * FROM orders WHERE user_id IN (SELECT id FROM `user` WHERE city = '北京');

-- 相关：内层引用了外层的 o.user_id，外层每行跑一次
SELECT * FROM orders o WHERE EXISTS (SELECT 1 FROM `user` u WHERE u.id = o.user_id);
```

`EXPLAIN` 里看到 `DEPENDENT SUBQUERY` 就要警惕了。

### `EXISTS` 的语义：只问「有没有」

`EXISTS` 是一个**布尔判断**，子查询一旦找到第一条匹配行就立刻返回 `TRUE` 并**短路退出**，不关心返回什么内容。所以 `SELECT 1`、`SELECT *`、`SELECT NULL` 完全等价，写 `SELECT 1` 只是表达「我不关心列」。

## 用法

沿用 [[SQL 多表连接：INNER JOIN 与 LEFT JOIN]] 的 `user` / `orders` 表。

### WHERE 中的子查询

```sql
-- 标量子查询：找出金额高于平均值的订单
SELECT id, amount FROM orders
WHERE amount > (SELECT AVG(amount) FROM orders);

-- 列子查询 IN
SELECT * FROM orders
WHERE user_id IN (SELECT id FROM `user` WHERE name LIKE '张%');

-- ANY / ALL：比某组值中任意一个大 / 比全部都大
SELECT * FROM orders WHERE amount > ANY (SELECT amount FROM orders WHERE status = 'refund');
SELECT * FROM orders WHERE amount > ALL (SELECT amount FROM orders WHERE status = 'refund');
```

`> ANY (子查询)` 等价于 `> MIN(...)`，`> ALL` 等价于 `> MAX(...)`——后者写法更直观也更快。

### EXISTS / NOT EXISTS

```sql
-- 有过订单的用户
SELECT * FROM `user` u
WHERE EXISTS (SELECT 1 FROM orders o WHERE o.user_id = u.id);

-- 从未下单的用户（比 NOT IN 安全，比 LEFT JOIN 语义更直白）
SELECT * FROM `user` u
WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.user_id = u.id);
```

### FROM 中的派生表

```sql
-- 先聚合再连接，避免 JOIN 后行数膨胀
SELECT u.name, IFNULL(t.total, 0) AS total
FROM `user` u
LEFT JOIN (
  SELECT user_id, SUM(amount) AS total
  FROM orders WHERE status = 'paid'
  GROUP BY user_id
) t ON u.id = t.user_id;        -- 派生表必须有别名 t，否则报 Every derived table must have its own alias
```

### CTE：把派生表写成可读的形式（MySQL 8.0+）

```sql
WITH paid_stat AS (
  SELECT user_id, SUM(amount) AS total, COUNT(*) AS cnt
  FROM orders WHERE status = 'paid'
  GROUP BY user_id
),
big_user AS (
  SELECT user_id FROM paid_stat WHERE total > 200     -- CTE 可以引用前面定义的 CTE
)
SELECT u.name, p.total, p.cnt
FROM `user` u
JOIN paid_stat p ON u.id = p.user_id
WHERE u.id IN (SELECT user_id FROM big_user);
```

CTE 的价值是**可读性和复用**：同一个中间结果在下面被引用多次时不用复制粘贴子查询。

### UNION 与 UNION ALL

```sql
-- UNION：合并后去重（会做一次排序或哈希去重，有性能开销）
SELECT name FROM `user` WHERE city = '北京'
UNION
SELECT name FROM `user` WHERE age > 30;

-- UNION ALL：直接拼接，不去重，快得多
SELECT id, 'order' AS src FROM orders WHERE amount > 100
UNION ALL
SELECT id, 'refund' AS src FROM refund_record WHERE amount > 100;
```

使用规则：

1. 各分支的**列数必须相同**，对应位置的**类型要兼容**；
2. 结果集的列名取**第一个分支**的列名；
3. `ORDER BY` 和 `LIMIT` 只能写在**最后一个分支之后**，作用于合并后的整体；想给单个分支排序要用括号包起来。

```sql
(SELECT id, amount FROM orders WHERE status = 'paid'   ORDER BY amount DESC LIMIT 3)
UNION ALL
(SELECT id, amount FROM orders WHERE status = 'refund' ORDER BY amount DESC LIMIT 3)
ORDER BY amount DESC;      -- 作用于合并结果
```

### 模拟 FULL OUTER JOIN

MySQL 没有全外连接，用 `UNION` 拼：

```sql
SELECT u.id, u.name, o.id AS oid FROM `user` u LEFT  JOIN orders o ON u.id = o.user_id
UNION
SELECT u.id, u.name, o.id AS oid FROM `user` u RIGHT JOIN orders o ON u.id = o.user_id;
```

### 子查询、JOIN、EXISTS 怎么选

同一个需求「查有订单的用户」，三种写法：

```sql
SELECT * FROM `user` u WHERE u.id IN (SELECT user_id FROM orders);                  -- IN
SELECT * FROM `user` u WHERE EXISTS (SELECT 1 FROM orders o WHERE o.user_id = u.id); -- EXISTS
SELECT DISTINCT u.* FROM `user` u JOIN orders o ON u.id = o.user_id;                -- JOIN
```

经验法则（MySQL 8.0 优化器已能把很多 `IN` 改写成半连接 semi-join，差距缩小，但仍有参考价值）：

- **子查询结果集小、外表大** → 用 `IN`（内层只算一次，物化成临时表）；
- **子查询结果集大、外表小** → 用 `EXISTS`（外层行少，内层能走索引短路）；
- **需要用到两张表的列** → 只能用 `JOIN`，但记得 `DISTINCT` 防膨胀。

## 踩坑

1. **`NOT IN` 遇到 `NULL` 返回空集**。这是最致命的坑：

   ```sql
   -- 如果 orders 里存在 user_id IS NULL 的行，下面这条永远返回 0 行
   SELECT * FROM `user` WHERE id NOT IN (SELECT user_id FROM orders);
   ```

   原理：`NOT IN (1, 2, NULL)` 展开为 `id != 1 AND id != 2 AND id != NULL`，最后一项恒为 `UNKNOWN`，整个 `AND` 结果不可能为 `TRUE`。**解法**：改用 `NOT EXISTS`，或在子查询加 `WHERE user_id IS NOT NULL`。而 `NOT EXISTS` 没有这个问题。

2. **相关子查询写在 `SELECT` 列表里，N+1 查询**。

   ```sql
   -- user 有 10 万行，这个子查询就执行 10 万次
   SELECT u.name, (SELECT COUNT(*) FROM orders o WHERE o.user_id = u.id) AS cnt FROM `user` u;
   ```

   改成 `LEFT JOIN` 一个预聚合的派生表。

3. **标量子查询返回多行直接报错**。`ERROR 1242 (21000): Subquery returns more than 1 row`。防御性写法是加 `LIMIT 1`，但更该想清楚为什么会多行。
4. **派生表没起别名**。`Every derived table must have its own alias`，`FROM (...)` 后面必须跟别名。
5. **`UNION` 悄悄去重导致行数变少**。业务上明确不会重复、或重复也要保留时，一律用 `UNION ALL`。`UNION` 的去重要做全字段排序/哈希，大结果集下开销显著。
6. **`UNION` 各分支列顺序错位**。列数对得上但语义错位（第一个分支是 `id, name`，第二个是 `name, id`），MySQL 不会报错，只会给出一堆垃圾数据。**按列名逐个核对**。
7. **MySQL 5.7 及以前对派生表不做合并**。子查询会被物化成临时表且无索引，外层条件下推不进去，性能很差。5.7 之后引入 derived merge 优化，8.0 更完善。
8. **CTE 在 MySQL 里不是「只算一次」的保证**。MySQL 可能对被多次引用的 CTE 重复求值（没有 CTE 物化的强保证），别指望它当缓存用。
9. **`IN` 里塞几千个值**。`WHERE id IN (1, 2, ..., 5000)` 会撑爆解析器（受 `max_allowed_packet` 限制）且优化器难处理，改用临时表 JOIN。

## 面试怎么答

**Q：`IN` 和 `EXISTS` 有什么区别？哪个快？**
A：语义上 `IN` 是把子查询结果当集合做值匹配，`EXISTS` 是对外层每一行判断「子查询有没有结果」，找到第一条就短路。性能上没有绝对答案，看两边数据量：子查询结果集小、外表大时 `IN` 更好，因为内层只需执行一次并物化；外表小、子查询表大且连接列有索引时 `EXISTS` 更好。另外一个关键差异是 `NULL`：`NOT IN` 只要候选集里有一个 `NULL` 就恒为空集，而 `NOT EXISTS` 不受影响，所以「反查不存在」的场景优先用 `NOT EXISTS`。MySQL 8.0 的优化器会把很多 `IN` 子查询自动改写成半连接，两者差距已经不大。

**Q：`UNION` 和 `UNION ALL` 的区别？**
A：`UNION` 会对合并结果做去重，实现上需要一次全字段的排序或哈希，有额外开销；`UNION ALL` 直接拼接，不去重，性能好很多。所以在业务上确认不会有重复行、或者重复行本身有意义时，一律用 `UNION ALL`。另外两者都要求各分支列数相同、类型兼容，结果列名取第一个分支的。

**Q：相关子查询为什么慢？**
A：相关子查询引用了外层的列，无法独立求值，外层结果集有多少行，子查询就要执行多少次，本质是 N+1 查询。`EXPLAIN` 里的 `DEPENDENT SUBQUERY` 就是标志。优化思路是改写成 JOIN——把子查询变成一个预聚合的派生表再连接，这样只需要扫一遍。

**Q：什么是 CTE？和子查询有什么区别？**
A：CTE 是 `WITH name AS (...)` 定义的公用表表达式，MySQL 8.0 开始支持。相比 `FROM` 里的派生表，它的优势是可读性——复杂查询可以拆成几个有名字的步骤，从上到下阅读；同一个中间结果可以被引用多次；还支持 `WITH RECURSIVE` 做递归查询，比如查组织架构树、物料清单展开。要注意 MySQL 并不保证被多次引用的 CTE 只计算一次。

## 参考

- [MySQL 8.0 子查询](https://dev.mysql.com/doc/refman/8.0/en/subqueries.html)
- [MySQL 8.0 UNION](https://dev.mysql.com/doc/refman/8.0/en/union.html)
- [PostgreSQL 子查询与 UNION 语法](https://www.postgresql.org/docs/current/queries-union.html)
- 相关笔记：[[SQL 多表连接：INNER JOIN 与 LEFT JOIN]]、[[SQL 分组取 Top N 与排名查询]]、[[MySQL EXPLAIN 执行计划解读]]
