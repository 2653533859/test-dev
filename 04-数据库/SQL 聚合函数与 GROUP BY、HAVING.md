---
created: 2026-07-31
tags: [数据库/SQL]
---

# SQL 聚合函数与 GROUP BY、HAVING

> 「把明细折叠成统计口径」是数据校验的核心动作——对账、统计报表、批量断言全靠它。

## 概念

### 聚合的本质：多行折叠成一行

`GROUP BY` 做的事情是：**按分组键把结果集切成若干个桶，每个桶最后只输出一行**。聚合函数（`COUNT` / `SUM` / `AVG` / `MAX` / `MIN`）就是「把一个桶里的多行压成一个值」的函数。

理解这一点，就能明白一个铁律：

> `SELECT` 列表里出现的列，要么是分组键，要么被聚合函数包裹。

因为其他列在一个桶里有多个值，数据库不知道该输出哪一个。

### 聚合函数与 `NULL`

这是最容易出错的地方，逐个记：

| 函数 | 对 `NULL` 的处理 |
|------|------------------|
| `COUNT(*)` | 统计行数，`NULL` 也算 |
| `COUNT(列)` | **跳过该列为 `NULL` 的行** |
| `COUNT(DISTINCT 列)` | 去重后统计，同样跳过 `NULL` |
| `SUM` / `AVG` | 跳过 `NULL`；**全为 `NULL` 时返回 `NULL` 而不是 0** |
| `MAX` / `MIN` | 跳过 `NULL` |

`AVG(col)` 的分母是「非 NULL 的行数」，不是总行数——这是对账差异的常见来源。

## 用法

沿用 [[SQL 查询基础：SELECT、WHERE 与 ORDER BY]] 的 `user` 表，再加一张订单表：

```sql
CREATE TABLE `orders` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`    BIGINT UNSIGNED NOT NULL,
  `amount`     DECIMAL(10, 2)  NOT NULL,
  `status`     VARCHAR(16)     NOT NULL COMMENT 'paid/refund/cancel',
  `coupon_id`  BIGINT UNSIGNED          DEFAULT NULL,
  `created_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_user_created` (`user_id`, `created_at`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

INSERT INTO `orders` (user_id, amount, status, coupon_id) VALUES
(1, 100.00, 'paid',   NULL),
(1,  50.00, 'paid',   9),
(1,  20.00, 'refund', NULL),
(2, 300.00, 'paid',   9),
(3,  10.00, 'cancel', NULL);
```

### 基本聚合

```sql
-- 全表聚合：不写 GROUP BY 时整张表就是一个桶，永远返回 1 行
SELECT
  COUNT(*)            AS 订单数,
  COUNT(coupon_id)    AS 用券订单数,     -- 跳过 NULL → 2
  SUM(amount)         AS 总额,
  AVG(amount)         AS 均额,
  MAX(amount)         AS 最大单,
  MIN(amount)         AS 最小单
FROM orders;
```

### GROUP BY 分组统计

```sql
-- 每个用户的下单笔数与金额
SELECT user_id, COUNT(*) AS cnt, SUM(amount) AS total
FROM orders
GROUP BY user_id
ORDER BY total DESC;

-- 多列分组：桶 = (user_id, status) 的组合
SELECT user_id, status, COUNT(*) AS cnt
FROM orders
GROUP BY user_id, status;

-- 按天分组（对日期做函数会让索引失效，量大时改存冗余日期列）
SELECT DATE(created_at) AS d, COUNT(*) AS cnt, SUM(amount) AS total
FROM orders
GROUP BY DATE(created_at)
ORDER BY d;
```

### 条件聚合：一次查询产出多个口径

**这是最实用的技巧**，把 `CASE WHEN` 塞进聚合函数，避免写多条 SQL 再拼装：

```sql
SELECT
  user_id,
  COUNT(*)                                              AS 总单数,
  SUM(CASE WHEN status = 'paid'   THEN 1 ELSE 0 END)    AS 已支付数,
  SUM(CASE WHEN status = 'refund' THEN 1 ELSE 0 END)    AS 退款数,
  SUM(CASE WHEN status = 'paid'   THEN amount ELSE 0 END) AS 实付金额,
  -- COUNT 遇到 NULL 会跳过，所以也可以写成这种更短的形式
  COUNT(CASE WHEN status = 'paid' THEN 1 END)           AS 已支付数2
FROM orders
GROUP BY user_id;
```

### HAVING：过滤「组」

```sql
-- 找出下单超过 2 笔、且总金额大于 100 的用户
SELECT user_id, COUNT(*) AS cnt, SUM(amount) AS total
FROM orders
WHERE status <> 'cancel'      -- WHERE 先过滤行：把取消单排除在统计外
GROUP BY user_id
HAVING cnt >= 2 AND total > 100;   -- HAVING 后过滤组：MySQL 允许用别名
```

`WHERE` 与 `HAVING` 的分工要牢记：

```text
FROM orders
  ↓
WHERE status <> 'cancel'      ← 逐行判断，能走索引，减少参与分组的数据量
  ↓
GROUP BY user_id              ← 折叠成桶
  ↓
HAVING COUNT(*) >= 2          ← 判断整个桶，只能在这里用聚合函数
```

**能放 `WHERE` 的绝不放 `HAVING`**：`WHERE` 在分组前就把数据砍掉了，`HAVING` 是分组算完才丢弃，白算一遍。

### GROUP_CONCAT：把组内明细拼成一行

做数据校验时非常好用，能一眼看到某个用户到底下了哪些单：

```sql
SELECT
  user_id,
  COUNT(*) AS cnt,
  GROUP_CONCAT(id ORDER BY id SEPARATOR ',') AS order_ids
FROM orders
GROUP BY user_id;
```

> 注意 `GROUP_CONCAT` 有长度上限，由 `group_concat_max_len` 控制（默认 1024 字节），**超长会被静默截断**，用于断言时务必先 `SET SESSION group_concat_max_len = 102400;`。

### WITH ROLLUP：小计与合计

```sql
-- 在结果末尾多出一行「合计」，分组列显示为 NULL
SELECT IFNULL(status, '合计') AS status, COUNT(*) AS cnt, SUM(amount) AS total
FROM orders
GROUP BY status WITH ROLLUP;
```

## 踩坑

1. **`SUM` 返回 `NULL` 而不是 0**。当没有任何行匹配时，`SELECT SUM(amount) FROM orders WHERE 1 = 0` 返回 `NULL`。程序里直接拿去做加法会报错或算错，务必写 `IFNULL(SUM(amount), 0)`。而 `COUNT(*)` 在无匹配时返回 `0`，两者行为不一致。
2. **`COUNT(列)` 与 `COUNT(*)` 结果对不上**。不是数据丢了，是该列有 `NULL`。校验「用券率」这类指标时特别容易掉进去。
3. **MySQL 5.7 之前允许 `SELECT` 非分组列**。`SELECT user_id, amount FROM orders GROUP BY user_id` 在旧版会随机返回桶里某一行的 `amount`，看起来能跑但结果不确定。5.7 之后默认开启 `ONLY_FULL_GROUP_BY`，会直接报错 `Expression #2 of SELECT list is not in GROUP BY clause...`。**正确做法是补聚合函数或补分组键，而不是去关掉这个 sql_mode**。
4. **`AVG` 的分母陷阱**。`AVG(col)` 分母是非 `NULL` 行数。如果想让 `NULL` 按 0 参与平均，得写 `AVG(IFNULL(col, 0))` 或 `SUM(col) / COUNT(*)`。
5. **`GROUP BY` 后 `ORDER BY` 别丢**。MySQL 8.0 起 `GROUP BY` **不再隐式排序**（5.7 及之前会隐式按分组键排序），依赖旧行为的用例升级后会偶发失败，必须显式写 `ORDER BY`。
6. **对分组列做函数会导致临时表 + 文件排序**。`GROUP BY DATE(created_at)` 无法利用 `created_at` 索引，`EXPLAIN` 里会出现 `Using temporary; Using filesort`。大表建议加一个冗余的 `stat_date` 列并建索引。
7. **`HAVING` 里用别名不通用**。MySQL 允许 `HAVING cnt >= 2`，但标准 SQL 和部分数据库（如某些版本的 Oracle）要求写完整的 `HAVING COUNT(*) >= 2`。跨库脚本写完整表达式更稳。
8. **`COUNT(DISTINCT a, b)` 与 `COUNT(DISTINCT a), COUNT(DISTINCT b)` 不是一回事**。前者是按组合去重计数，只要有一列为 `NULL` 整行就不计。

## 面试怎么答

**Q：`COUNT(*)`、`COUNT(1)`、`COUNT(列)` 有什么区别？哪个快？**
A：语义上 `COUNT(*)` 和 `COUNT(1)` 都是统计行数，包含 `NULL` 行，结果永远一样；`COUNT(列)` 会跳过该列为 `NULL` 的行，语义就不同了。性能上，InnoDB 对 `COUNT(*)` 做了专门优化，优化器会选一棵最小的二级索引树来扫（因为二级索引叶子节点比聚簇索引小，扫的页更少），所以 `COUNT(*)` 不比 `COUNT(1)` 慢，官方也明确建议用 `COUNT(*)`。而 `COUNT(主键)` 反而可能走聚簇索引，扫的数据量更大。

**Q：`WHERE` 和 `HAVING` 的区别？**
A：执行时机不同——`WHERE` 在 `GROUP BY` 之前对原始行过滤，`HAVING` 在分组后对组过滤。因此 `WHERE` 里不能用聚合函数，`HAVING` 里可以。性能上 `WHERE` 能走索引且能减少参与分组的数据量，所以能写在 `WHERE` 的条件不要放到 `HAVING`。

**Q：`ONLY_FULL_GROUP_BY` 是什么？**
A：MySQL 5.7 起默认开启的 sql_mode，要求 `SELECT`、`HAVING`、`ORDER BY` 中出现的非聚合列必须在 `GROUP BY` 里。它防止的是「一个分组里某列有多个值，却随便返回一个」这种结果不确定的查询。遇到报错的正确姿势是补 `GROUP BY` 或加 `MAX()`/`ANY_VALUE()`，而不是关掉这个模式——关掉只是把不确定性藏起来了。

**Q：怎么用一条 SQL 统计多种状态的订单数？**
A：条件聚合。`SUM(CASE WHEN status = 'paid' THEN 1 ELSE 0 END)` 或者利用 `COUNT` 跳过 `NULL` 的特性写成 `COUNT(CASE WHEN status = 'paid' THEN 1 END)`。相比查多次再在代码里拼，这样只扫一遍表，而且各口径的数据快照一致，不会因为两次查询之间数据变化导致对不上。

## 参考

- [MySQL 8.0 聚合函数](https://dev.mysql.com/doc/refman/8.0/en/aggregate-functions.html)
- [MySQL GROUP BY 处理](https://dev.mysql.com/doc/refman/8.0/en/group-by-handling.html)
- [PostgreSQL 聚合函数与 GROUP BY](https://www.postgresql.org/docs/current/functions-aggregate.html)
- 相关笔记：[[SQL 查询基础：SELECT、WHERE 与 ORDER BY]]、[[SQL 分组取 Top N 与排名查询]]、[[MySQL EXPLAIN 执行计划解读]]
