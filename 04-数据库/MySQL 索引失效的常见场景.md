---
created: 2026-07-31
tags: [数据库/索引]
---

# MySQL 索引失效的常见场景

> 「明明建了索引，`EXPLAIN` 却是 `type: ALL`」——这篇把所有让索引失效的写法列全，并解释每一条背后的原理。

## 概念

### 索引失效的两大类原因

不要死记「索引失效的 N 种情况」，本质只有两类：

**第一类：无法在 B+ 树上定位（结构性失效）**

索引是有序结构，查找依赖「拿一个确定的值或区间去二分」。任何让 MySQL 无法从条件中提取出「索引列的确定值 / 区间」的写法，都会导致索引不可用。函数运算、隐式转换、前置通配、缺最左列都属于这一类，**这类是硬性失效，优化器想用也用不了**。

**第二类：优化器认为走索引更慢（成本性失效）**

索引可用，但优化器基于成本模型算出「走二级索引 + 大量随机回表」比「顺序全表扫」更贵，于是主动放弃。这类不是 bug，反而通常是正确决策。

区分这两类很重要：第一类要改 SQL，第二类要改索引设计或缩小结果集，而不是无脑 `FORCE INDEX`。

## 用法

沿用这张表逐条演示：

```sql
CREATE TABLE `user` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `phone`      VARCHAR(16)     NOT NULL,
  `name`       VARCHAR(32)     NOT NULL,
  `age`        TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `status`     TINYINT UNSIGNED NOT NULL DEFAULT 1,
  `created_at` DATETIME        NOT NULL,
  `remark`     VARCHAR(255)    NOT NULL DEFAULT '',
  PRIMARY KEY (`id`),
  KEY `idx_phone` (`phone`),
  KEY `idx_name` (`name`),
  KEY `idx_created` (`created_at`),
  KEY `idx_status_age` (`status`, `age`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;
```

### 1. 索引列参与运算或函数

```sql
-- ❌ 失效：索引里存的是 created_at 原值，不是 DATE() 的结果
SELECT * FROM `user` WHERE DATE(created_at) = '2026-07-31';
-- ✅ 改写成范围条件
SELECT * FROM `user`
WHERE created_at >= '2026-07-31 00:00:00' AND created_at < '2026-08-01 00:00:00';

-- ❌ 失效
SELECT * FROM `user` WHERE age + 1 = 30;
-- ✅ 把运算挪到常量侧
SELECT * FROM `user` WHERE age = 29;

-- ❌ 失效
SELECT * FROM `user` WHERE LEFT(phone, 3) = '138';
-- ✅
SELECT * FROM `user` WHERE phone LIKE '138%';
```

MySQL 8.0.13+ 提供函数索引作为兜底：

```sql
ALTER TABLE `user` ADD KEY `idx_date` ((DATE(created_at)));
-- 此后 WHERE DATE(created_at) = '2026-07-31' 可以走索引
```

### 2. 隐式类型转换

```sql
-- phone 是 VARCHAR，条件给了数字
-- ❌ MySQL 遵循「字符串与数字比较时，把字符串转成数字」→ 相当于对列做了 CAST() → 失效
SELECT * FROM `user` WHERE phone = 13800138000;
-- ✅ 加引号
SELECT * FROM `user` WHERE phone = '13800138000';

-- 反过来：age 是 TINYINT，条件给字符串 '28'
-- ✅ 不失效！转换发生在常量侧，'28' 被转成 28
SELECT * FROM `user` WHERE age = '28';
```

**记忆点：列是字符串、值给数字 → 失效；列是数字、值给字符串 → 不失效。**

同类问题还有**字符集不一致**：两表 JOIN，一个 `utf8mb4` 一个 `utf8mb3`，连接列需要转换字符集，被驱动表的索引失效。

### 3. LIKE 前置通配

```sql
-- ❌ 失效：没有左边界，B+ 树无从定位
SELECT * FROM `user` WHERE name LIKE '%三';
SELECT * FROM `user` WHERE name LIKE '%三%';

-- ✅ 可用：等价于 name >= '张' AND name < '章'，是范围查询
SELECT * FROM `user` WHERE name LIKE '张%';
```

必须做后置/中间模糊匹配时的方案：全文索引（`FULLTEXT` + `MATCH AGAINST`）、Elasticsearch、或者存一个反转列 `name_rev` 再用 `LIKE '三反转%'`。

### 4. 不满足最左前缀

```sql
-- 索引 (status, age)
SELECT * FROM `user` WHERE age = 28;        -- ❌ 缺最左列 status
SELECT * FROM `user` WHERE status = 1;      -- ✅
```

详见 [[MySQL 联合索引与最左前缀]]。

### 5. OR 连接了无索引的列

```sql
-- ❌ remark 无索引 → 为了找出所有满足 remark 的行必须全表扫，索引没意义
SELECT * FROM `user` WHERE phone = '138...' OR remark = 'vip';

-- ✅ 两边都有索引时，优化器可能用 index merge（Extra: Using union）
SELECT * FROM `user` WHERE phone = '138...' OR name = '张三';

-- ✅ 万能改写：拆成 UNION ALL，各自走各自的索引
SELECT * FROM `user` WHERE phone = '138...'
UNION
SELECT * FROM `user` WHERE remark = 'vip';
```

注意 `AND` 没有这个问题——`AND` 只要有一个条件能用索引就能缩小范围。

### 6. 使用了 `!=`、`<>`、`NOT IN`、`NOT LIKE`

```sql
-- ⚠️ 通常失效（优化器判断否定条件命中的行太多，不如全表扫）
SELECT * FROM `user` WHERE status != 1;
SELECT * FROM `user` WHERE status NOT IN (1, 2);
```

这属于**成本性失效**。如果否定条件的结果集其实很小（比如 `status` 有 100 个取值），优化器仍会走索引。可以改写成正向的 `IN` 列表帮优化器一把。

### 7. `IS NULL` / `IS NOT NULL`

```sql
SELECT * FROM `user` WHERE remark IS NULL;      -- 可能走索引（NULL 值在 B+ 树里排最前，是可定位的）
SELECT * FROM `user` WHERE remark IS NOT NULL;  -- 通常失效（范围太大）
```

InnoDB 的索引**会存储 NULL 值**，所以 `IS NULL` 本身是可以走索引的，能不能走取决于 NULL 值占比。这是一个和「老八股」说法不同的细节，值得记住。

### 8. 优化器判断全表扫更快

```sql
-- status 只有 0/1 两个值，status = 1 占了 95% 的行
SELECT * FROM `user` WHERE status = 1;
-- type: ALL —— 走索引要回表 95 万次随机 I/O，不如顺序扫一遍
```

一般认为**结果集超过全表 20%~30% 时，优化器倾向于全表扫描**。解法是加覆盖索引（不回表就没有随机 I/O 的问题），或者从业务上缩小结果集。

### 9. 统计信息过期

```sql
-- 大批量导数后，Cardinality 严重失真，优化器选错索引
ANALYZE TABLE `user`;        -- 重新采样统计信息（很快，不锁表）
SHOW INDEX FROM `user`;      -- 检查 Cardinality 是否合理
```

「同一条 SQL 昨天秒回今天超时」，八成是这个原因。

### 10. `ORDER BY` 导致的额外排序

不算索引失效，但同样是性能杀手：

```sql
-- ❌ Using filesort：排序列和 WHERE 列不在同一个索引上
SELECT * FROM `user` WHERE status = 1 ORDER BY created_at;
-- ✅ 建联合索引 (status, created_at)
ALTER TABLE `user` ADD KEY `idx_status_created` (`status`, `created_at`);
```

### 强制干预（谨慎使用）

```sql
SELECT * FROM `user` FORCE INDEX (idx_phone) WHERE phone = '138...';   -- 强制
SELECT * FROM `user` IGNORE INDEX (idx_name)  WHERE name = '张三';      -- 排除
```

`FORCE INDEX` 是**止血手段不是解药**：数据分布变化后可能反而更慢，而且索引名改了 SQL 会直接报错。优先用 `ANALYZE TABLE` 和优化索引设计解决。

## 踩坑

1. **`WHERE phone = 13800138000` 不加引号**。线上最隐蔽的一类慢查询——SQL 完全正确、结果也对，就是慢，看 `EXPLAIN` 才发现全表扫。而且这个坑在 ORM 里高发（Python 传了 int）。
2. **JOIN 两表字符集/排序规则不一致**。老库 `utf8`、新表 `utf8mb4`，连接时隐式转换让被驱动表索引失效。`SHOW CREATE TABLE` 对比确认。
3. **以为 `IS NULL` 一定不走索引**。InnoDB 会索引 NULL 值，`IS NULL` 是可以走的。别拿老资料的结论当定论，**以本机 `EXPLAIN` 为准**。
4. **`FORCE INDEX` 上线后爆炸**。数据量增长导致原本正确的强制索引变成错误选择，且失去了优化器自适应能力。
5. **函数索引也有前提**。`WHERE DATE(created_at) = ?` 走函数索引，要求表达式**和索引定义完全一致**，写成 `WHERE DATE(created_at) >= ?` 或 `CAST(created_at AS DATE)` 就不匹配了。
6. **只在测试库验证 `EXPLAIN`**。测试库几百行数据，优化器怎么选都无所谓；生产几千万行的选择完全不同。压测/性能验证要用同量级数据。
7. **`LIMIT` 让优化器改主意**。`SELECT * FROM t WHERE a = 1 ORDER BY id LIMIT 1` 时，优化器可能认为「顺着主键扫很快就能凑够 1 行」而放弃 `idx_a`，结果在数据分布不均时扫遍全表。这是一个非常隐蔽的坑，解法是加 `ORDER BY a, id` 或用覆盖索引。
8. **索引列上有隐式排序规则差异**。`utf8mb4_general_ci` 和 `utf8mb4_0900_ai_ci` 在同一张表的不同列上混用，JOIN 时也会失效。
9. **在 `WHERE` 里对索引列做 `CAST`/`CONVERT`**，等同于函数运算。
10. **区分不了「没走索引」和「走了但很慢」**。`type: ALL` 是没走；`type: ref` 但 `rows` 巨大、`Extra` 有 `Using filesort` 是走了但不够好。定位方向完全不同。

## 面试怎么答

**Q：什么情况下索引会失效？**
A：我一般分两类讲。**第一类是结构性失效**，MySQL 根本没法在 B+ 树上定位：索引列参与函数或运算（`DATE(created_at) = ?`、`age + 1 = ?`）；隐式类型转换（列是 `VARCHAR` 却传数字，等价于对列做 `CAST`）；`LIKE` 前置通配 `'%x'` 没有左边界；不满足联合索引的最左前缀；`OR` 连接了没有索引的列。**第二类是成本性失效**，索引能用但优化器算下来不划算：结果集占比太大（一般超过 20%~30%）时走索引要大量随机回表，不如顺序全表扫；否定条件 `!=` / `NOT IN` 通常也归于这类；还有统计信息过期导致的误判。区分这两类很重要，第一类改 SQL 写法，第二类调索引设计或用 `ANALYZE TABLE` 刷新统计信息。

**Q：为什么隐式类型转换会让索引失效？**
A：MySQL 的类型转换规则是：字符串和数字比较时，把**字符串**转成数字。如果索引列是 `VARCHAR` 而条件给了数字，等价于 `WHERE CAST(phone AS SIGNED) = 13800138000`，相当于对列做了函数运算，索引里存的原值用不上了。反过来，如果列是数字类型、条件给字符串，转换发生在常量侧，索引照样能用。所以规则是「列是字符串就一定要加引号」。

**Q：`IS NULL` 会走索引吗？**
A：会的，这一点常被老八股答错。InnoDB 的 B+ 树会存储 `NULL` 值，并把它排在最前面，所以 `IS NULL` 是一个可定位的条件。能不能走取决于 `NULL` 的占比——占比小就走索引，占比大优化器还是会全表扫。`IS NOT NULL` 因为通常命中绝大多数行，一般不走。当然从设计角度，字段应尽量 `NOT NULL`，从源头避免这类判断。

**Q：`EXPLAIN` 显示走了索引但还是慢，怎么办？**
A：先看三个字段。`rows` 很大说明索引的选择性不够或者条件区分度低，考虑换更有区分度的索引列顺序。`Extra` 出现 `Using filesort` 说明排序无法利用索引，把 `ORDER BY` 的列加进联合索引。`Extra` 没有 `Using index` 说明在回表，如果回表次数多就构造覆盖索引，深分页场景用延迟关联。另外还要看 `key_len` 确认联合索引到底用了几列，可能只用了第一列。

**Q：能用 `FORCE INDEX` 解决索引选错吗？**
A：可以但不推荐作为长期方案。它只是绕过了优化器，数据分布变化后可能反而更慢，而且索引改名会导致 SQL 直接报错，失去了优化器自适应的能力。正确顺序是：先 `ANALYZE TABLE` 刷新统计信息，看是不是 `Cardinality` 失真导致的误判；再检查 SQL 写法有没有让索引失效；再看索引设计是否合理、要不要加覆盖索引。这些都试过了还是选错，才用 `FORCE INDEX` 临时止血，并记录下来后续跟进。

## 参考

- [MySQL 8.0 类型转换规则](https://dev.mysql.com/doc/refman/8.0/en/type-conversion.html)
- [MySQL 8.0 索引提示](https://dev.mysql.com/doc/refman/8.0/en/index-hints.html)
- [PostgreSQL 索引使用与优化器选择](https://www.postgresql.org/docs/current/indexes-examine.html)
- 相关笔记：[[MySQL 联合索引与最左前缀]]、[[MySQL EXPLAIN 执行计划解读]]、[[MySQL 聚簇索引与二级索引回表]]、[[MySQL 慢查询日志与 SQL 优化流程]]
