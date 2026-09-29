---
created: 2026-07-31
tags: [数据库/SQL]
---

# SQL 多表连接：INNER JOIN 与 LEFT JOIN

> 校验一个订单详情接口，往往要连用户表、商品表、优惠券表——JOIN 是测试同学查数据绕不开的一关。

![[assets/join-types.svg]]
*图示：同一组数据在 INNER / LEFT / RIGHT / FULL OUTER 四种连接下的结果差异——关键看「匹配不上的行留不留、用什么补」。*

## 概念

### JOIN 的本质：笛卡尔积 + 过滤

理解 JOIN 只需要一句话：

> `A JOIN B ON 条件` = 先取 A 和 B 的**笛卡尔积**（A 的每一行去配 B 的每一行，共 m × n 行），再用 `ON` 条件筛掉不满足的组合。

数据库当然不会真的物化 m × n 行，优化器会用嵌套循环（Nested-Loop Join）、Hash Join 等算法优化，但**语义上等价于这个过程**。所有 JOIN 的诡异结果（行数暴涨、数据重复）都能用这个模型解释。

### 驱动表与被驱动表

嵌套循环连接的伪代码：

```text
for 每一行 r1 in 驱动表 A:              -- 外层循环，扫一次
    for 匹配的行 r2 in 被驱动表 B:       -- 内层循环，A 有几行就查几次 B
        if ON 条件成立: 输出 r1 + r2
```

**结论**：被驱动表的连接列**必须有索引**，否则内层每次都要全表扫，复杂度从 O(m × log n) 退化成 O(m × n)。这是 JOIN 慢查询的头号原因。

MySQL 优化器一般会选**结果集小的表做驱动表**（小表驱动大表），`LEFT JOIN` 则强制左表为驱动表。

### INNER 与 OUTER 的分界

- **INNER JOIN**：只输出匹配成功的组合，两边的「孤儿行」全丢。
- **LEFT JOIN**（`LEFT OUTER JOIN` 的简写）：左表**全部保留**，右表匹配不上时用 `NULL` 填充。
- **RIGHT JOIN**：反过来。实际工程中基本不用——把两张表交换位置写成 `LEFT JOIN` 更符合阅读习惯。
- **FULL OUTER JOIN**：MySQL **不支持**，需要 `LEFT JOIN UNION RIGHT JOIN` 模拟。

## 用法

```sql
CREATE TABLE `user` (
  `id`   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(32)     NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

CREATE TABLE `orders` (
  `id`      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id` BIGINT UNSIGNED NOT NULL,
  `amount`  DECIMAL(10, 2)  NOT NULL,
  `status`  VARCHAR(16)     NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_user_id` (`user_id`)        -- 被驱动表的连接列必须建索引
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

INSERT INTO `user` (id, name) VALUES (1, '张三'), (2, '李四'), (3, '王五');
INSERT INTO `orders` (user_id, amount, status) VALUES
(1, 100.00, 'paid'), (1, 50.00, 'refund'), (2, 300.00, 'paid'), (9, 50.00, 'paid');
```

### INNER JOIN：取交集

```sql
SELECT u.id, u.name, o.id AS order_id, o.amount
FROM `user` u
INNER JOIN orders o ON u.id = o.user_id;
-- 张三 100 / 张三 50 / 李四 300
-- 王五（无订单）和 user_id=9 的孤儿订单都不出现
```

注意：**张三出现了两次**。一对多关系下，左表的行会按右表匹配数量「膨胀」。这正是下面 `COUNT` 出错的根源。

### LEFT JOIN：左表保底

```sql
-- 所有用户 + 各自的订单（没有订单的也要列出来）
SELECT u.id, u.name, o.id AS order_id, o.amount
FROM `user` u
LEFT JOIN orders o ON u.id = o.user_id;
-- 张三 100 / 张三 50 / 李四 300 / 王五 NULL NULL
```

### LEFT JOIN 的杀手锏：找「没有关联记录」的行

反查孤儿数据，测试对数时高频使用：

```sql
-- 从未下过单的用户
SELECT u.id, u.name
FROM `user` u
LEFT JOIN orders o ON u.id = o.user_id
WHERE o.id IS NULL;                     -- 匹配不上 → 右表列全为 NULL
```

```sql
-- 反向：脏数据检查，找出 user_id 在用户表里不存在的订单（外键孤儿）
SELECT o.id, o.user_id
FROM orders o
LEFT JOIN `user` u ON o.user_id = u.id
WHERE u.id IS NULL;                     -- 输出 user_id = 9 那条
```

### ON 与 WHERE 的致命区别

这是 `LEFT JOIN` 最高频的坑，必须理解执行顺序：`ON` 在**连接阶段**生效，`WHERE` 在**连接完成后**对结果集过滤。

```sql
-- 写法 A：条件在 ON 里 —— 左表全保留，王五和只有退款单的用户都在
SELECT u.name, o.id, o.amount
FROM `user` u
LEFT JOIN orders o ON u.id = o.user_id AND o.status = 'paid';
-- 张三 100 / 李四 300 / 王五 NULL

-- 写法 B：条件在 WHERE 里 —— 王五那行 o.status 是 NULL，NULL = 'paid' 为 UNKNOWN 被过滤
SELECT u.name, o.id, o.amount
FROM `user` u
LEFT JOIN orders o ON u.id = o.user_id
WHERE o.status = 'paid';
-- 张三 100 / 李四 300     ← LEFT JOIN 退化成了 INNER JOIN
```

**记忆口诀**：`LEFT JOIN` 中，**右表的过滤条件放 `ON`，左表的过滤条件放 `WHERE`**。

### JOIN + 聚合：统计每个用户的订单数

```sql
-- 错误：COUNT(*) 会把「王五 NULL」那一行也数成 1
SELECT u.name, COUNT(*) AS cnt
FROM `user` u LEFT JOIN orders o ON u.id = o.user_id
GROUP BY u.id, u.name;
-- 王五 → 1 ❌

-- 正确：COUNT(右表非空列) 会跳过 NULL
SELECT u.name, COUNT(o.id) AS cnt, IFNULL(SUM(o.amount), 0) AS total
FROM `user` u LEFT JOIN orders o ON u.id = o.user_id
GROUP BY u.id, u.name;
-- 王五 → 0 ✅
```

### 多表连接与自连接

```sql
-- 三表连接：从左往右依次两两连接
SELECT u.name, o.id, c.title
FROM `user` u
JOIN orders o        ON u.id = o.user_id
LEFT JOIN coupon c   ON o.coupon_id = c.id
WHERE o.status = 'paid';

-- 自连接：同一张表当两张用，必须起别名。找出同部门里工资比自己高的人
SELECT e1.name AS 本人, e2.name AS 比他高的人
FROM employee e1
JOIN employee e2 ON e1.dept = e2.dept AND e2.salary > e1.salary;
```

## 踩坑

1. **JOIN 后行数膨胀，`SUM` 被重复累加**。用户表连订单表再连订单明细表，主表金额会被明细行数乘一遍。典型症状：对账金额是真实值的 2 倍、3 倍。**解法**：先把子表聚合成一行再 JOIN。

   ```sql
   SELECT u.name, IFNULL(o.total, 0) AS total
   FROM `user` u
   LEFT JOIN (
     SELECT user_id, SUM(amount) AS total FROM orders GROUP BY user_id
   ) o ON u.id = o.user_id;
   ```

2. **`LEFT JOIN` 被 `WHERE` 退化成 `INNER JOIN`**。见上文写法 B。想在保留左表的同时过滤右表，条件必须写在 `ON` 里。
3. **`LEFT JOIN` 后 `COUNT(*)` 把 NULL 行数成 1**。必须 `COUNT(右表的非空列)`。
4. **连接列类型不一致导致索引失效**。`o.user_id` 是 `BIGINT`，`u.id` 是 `VARCHAR`，或者两表字符集/排序规则不同（`utf8` vs `utf8mb4`），MySQL 会隐式转换，索引直接废掉，`EXPLAIN` 里 `type` 变成 `ALL`。**建表时关联列的类型、长度、字符集必须完全一致**。
5. **忘写 `ON` 变成笛卡尔积**。`SELECT * FROM a, b` 或 `CROSS JOIN`，1 万 × 1 万 = 1 亿行，能把测试库打挂。写 JOIN 先写 `ON`。
6. **被驱动表连接列没索引**。1000 行 JOIN 10 万行，没索引就是 1 亿次比较。`EXPLAIN` 里看到 `Using join buffer (Block Nested Loop)` 基本就是这个问题。
7. **`ON` 条件里对列做函数**。`ON DATE(o.created_at) = u.reg_date` 会让索引失效，改成范围条件。
8. **JOIN 太多表**。超过 3~4 张表的 JOIN，优化器选执行计划的搜索空间爆炸（`optimizer_search_depth` 限制），容易选错。测试查数时宁可分几步查再在代码里拼。
9. **`USING(col)` 与 `ON` 的差异**。`USING(user_id)` 要求两表列名相同，且结果集里该列只出现一次；`SELECT *` 时列的数量会不一样，写脚本解析结果要注意。

## 面试怎么答

**Q：`INNER JOIN` 和 `LEFT JOIN` 的区别？**
A：`INNER JOIN` 只返回两表都匹配上的行；`LEFT JOIN` 保留左表全部行，右表没匹配上的用 `NULL` 填充。实际工作中 `LEFT JOIN` 更常用于「主表 + 可选附属信息」的场景，还有一个高频用法是配合 `WHERE 右表主键 IS NULL` 反查「没有关联记录」的数据，比如找从未下单的用户或外键孤儿数据。

**Q：`LEFT JOIN` 时过滤条件写在 `ON` 和 `WHERE` 有什么区别？**
A：`ON` 在连接阶段生效，只决定右表哪些行能被匹配上，左表的行**一定保留**；`WHERE` 在连接完成后对结果集过滤，如果条件涉及右表列，那些被填充为 `NULL` 的行会因为 `NULL` 比较结果是 `UNKNOWN` 而被过滤掉，`LEFT JOIN` 就退化成了 `INNER JOIN`。所以规则是：右表的条件放 `ON`，左表的条件放 `WHERE`。

**Q：JOIN 的底层实现是什么？为什么说小表驱动大表？**
A：MySQL 8.0 之前主要是 Nested-Loop Join：遍历驱动表的每一行，拿连接键去被驱动表查一次。如果被驱动表连接列有索引，就是 Index Nested-Loop，复杂度约 O(m × log n)，此时驱动表行数 m 越小，内层查找次数越少，所以小表驱动大表。如果没索引，会退化成 Block Nested-Loop，把驱动表数据放进 join buffer 批量比较，复杂度 O(m × n)。MySQL 8.0.18 后引入了 Hash Join，对无索引的等值连接性能好很多。核心优化手段还是：**被驱动表的连接列必须有索引，且两边类型一致**。

**Q：为什么 JOIN 之后 `SUM` 的金额变成了两倍？**
A：一对多关系导致主表行被复制。比如一个订单有 3 条明细，`orders JOIN order_item` 后订单主表的 `amount` 会出现 3 次，`SUM` 就乘以 3 了。解法是先把子表 `GROUP BY` 聚合成一行再 JOIN，或者用 `SUM(DISTINCT ...)` 这种取巧写法（但有并列相同值时不准，不推荐）。这个坑在做对账测试时非常常见。

## 参考

- [MySQL 8.0 JOIN 语法](https://dev.mysql.com/doc/refman/8.0/en/join.html)
- [MySQL Nested-Loop Join 算法](https://dev.mysql.com/doc/refman/8.0/en/nested-loop-joins.html)
- [PostgreSQL JOIN 语法与执行计划](https://www.postgresql.org/docs/current/queries-table-expressions.html#QUERIES-FROM)
- 相关笔记：[[SQL 子查询与 UNION]]、[[MySQL EXPLAIN 执行计划解读]]、[[SQL 聚合函数与 GROUP BY、HAVING]]
