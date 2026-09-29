---
created: 2026-07-31
tags: [数据库/执行计划]
---

# MySQL EXPLAIN 执行计划解读

> 测开对数据库的硬指标之一：**看得懂 `EXPLAIN`，能判断一条 SQL 有没有走索引、慢在哪里**。这篇逐列拆解。

## 概念

### EXPLAIN 是什么

`EXPLAIN` 让优化器**只做决策不真执行**，输出它准备怎么读表：用哪个索引、大概扫多少行、要不要临时表和排序。

它是**估算值**，不是实际执行结果——`rows` 来自统计信息采样，可能有较大偏差。要看真实执行数据用 MySQL 8.0.18+ 的 `EXPLAIN ANALYZE`。

### 关注优先级

`EXPLAIN` 有十几列，但排查问题时看这五列就够了，按优先级排序：

```text
1. type      访问类型 —— 是不是全表扫
2. key       实际用了哪个索引 —— 有没有走索引
3. key_len   用了索引的几个列 —— 联合索引用全了吗
4. rows      预估扫描行数 —— 扫描量是否合理
5. Extra     附加信息 —— 有没有 filesort / temporary
```

## 用法

```sql
CREATE TABLE `orders` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`    BIGINT UNSIGNED NOT NULL,
  `status`     TINYINT UNSIGNED NOT NULL,
  `amount`     DECIMAL(10, 2)  NOT NULL,
  `created_at` DATETIME        NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_u_s_c` (`user_id`, `status`, `created_at`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

EXPLAIN SELECT * FROM orders WHERE user_id = 1 AND status = 1;
```

典型输出：

```text
+----+-------------+--------+------------+------+---------------+-----------+---------+-------------+------+----------+-------+
| id | select_type | table  | partitions | type | possible_keys | key       | key_len | ref         | rows | filtered | Extra |
+----+-------------+--------+------------+------+---------------+-----------+---------+-------------+------+----------+-------+
|  1 | SIMPLE      | orders | NULL       | ref  | idx_u_s_c     | idx_u_s_c | 9       | const,const |   12 |   100.00 | NULL  |
+----+-------------+--------+------------+------+---------------+-----------+---------+-------------+------+----------+-------+
```

### type：访问类型（最重要）

**性能从好到差**：

| type | 含义 | 判断 |
|------|------|------|
| `system` | 表只有一行（系统表） | 理想 |
| `const` | 通过**主键或唯一索引**等值匹配，最多返回一行 | 理想 |
| `eq_ref` | JOIN 时，被驱动表用主键/唯一索引等值匹配，每行匹配一条 | 很好 |
| `ref` | 用**非唯一索引**等值匹配，可能返回多行 | 好 |
| `ref_or_null` | 同 `ref`，外加 `IS NULL` 判断 | 好 |
| `range` | 索引范围扫描（`>` `<` `BETWEEN` `IN` `LIKE 'x%'`） | 可接受 |
| `index` | **全索引扫描**——遍历整棵索引树 | 差 |
| `ALL` | **全表扫描**——遍历聚簇索引所有叶子 | 最差 |

**及格线：至少要到 `range`；OLTP 的核心查询应该在 `ref` 或以上。**

```sql
-- const：主键等值
EXPLAIN SELECT * FROM orders WHERE id = 1;

-- ref：非唯一索引等值
EXPLAIN SELECT * FROM orders WHERE user_id = 1;

-- range：范围
EXPLAIN SELECT * FROM orders WHERE id BETWEEN 1 AND 100;
EXPLAIN SELECT * FROM orders WHERE user_id IN (1, 2, 3);

-- index：扫全索引（比 ALL 好一点，因为索引比数据小，且常是覆盖索引）
EXPLAIN SELECT user_id FROM orders;

-- ALL：全表扫
EXPLAIN SELECT * FROM orders WHERE amount > 100;
```

**`index` 和 `ALL` 的区别**：`index` 扫的是索引树（体积小、可能覆盖），`ALL` 扫的是聚簇索引全部叶子（含所有行数据）。两者都是「扫全部」，`index` 只是稍微便宜一点，都不是好现象。

### key / possible_keys / key_len

- `possible_keys`：优化器**考虑过**的索引。为 `NULL` 说明压根没有可用索引 → 该建索引了。
- `key`：**实际选中**的索引。为 `NULL` 说明没走索引。
- **`possible_keys` 有值但 `key` 为 `NULL`** → 优化器认为走索引更慢（成本性放弃），常见于结果集占比过大或统计信息失真。

`key_len` 计算规则（用来判断联合索引用了几列）：

```text
基础字节数：
  TINYINT 1 / SMALLINT 2 / INT 4 / BIGINT 8
  DATETIME 5 / TIMESTAMP 4 / DATE 3
  CHAR(n)    utf8mb4 → n × 4
  VARCHAR(n) utf8mb4 → n × 4 + 2（2 字节长度前缀）
额外：
  该列允许 NULL → +1
```

本例 `key_len = 9` = `user_id`(BIGINT 8) + `status`(TINYINT 1)，说明**只用了两列**，`created_at` 没参与定位——和 SQL 里确实只有两个条件吻合。

### rows 与 filtered

- `rows`：预估要**读取**的行数。这是评估查询代价最直观的数字，越接近最终返回的行数越好。
- `filtered`：读出来后，**经条件过滤剩下的百分比**。

```text
实际参与后续步骤的行数 ≈ rows × filtered / 100
```

如果 `rows = 100000` 而最终只返回 10 行，说明索引选择性太差，扫了一堆没用的。

### Extra：附加信息（细节都在这）

| Extra | 含义 | 好坏 |
|-------|------|------|
| `Using index` | **覆盖索引**，不回表 | 很好 |
| `Using index condition` | **索引下推 ICP**，减少回表 | 较好 |
| `Using where` | Server 层做了额外过滤 | 中性 |
| `Using index for skip scan` | 跳跃扫描（8.0.13+） | 中性 |
| `Using filesort` | **额外排序**，无法用索引顺序 | 差 |
| `Using temporary` | **创建临时表**（常见于 `GROUP BY`、`DISTINCT`、`UNION`） | 差 |
| `Using join buffer (Block Nested Loop)` | 被驱动表无索引，走 join buffer | 差 |
| `Impossible WHERE` | 条件恒假，不用执行 | 中性 |
| `Select tables optimized away` | 优化器直接用索引算出结果（如 `MAX(id)`） | 很好 |

> `Using filesort` 不代表一定用到磁盘文件。数据量小于 `sort_buffer_size` 时在内存里排（快），超了才落盘（慢）。但无论如何都是额外开销。

### select_type：查询类型

| 值 | 含义 |
|----|------|
| `SIMPLE` | 简单查询，无子查询和 UNION |
| `PRIMARY` | 最外层查询 |
| `SUBQUERY` | `SELECT`/`WHERE` 中的子查询（非相关） |
| `DEPENDENT SUBQUERY` | **相关子查询，外层每行执行一次** ← 危险信号 |
| `DERIVED` | `FROM` 子句中的派生表 |
| `UNION` / `UNION RESULT` | UNION 的分支与合并 |
| `MATERIALIZED` | 子查询被物化成临时表 |

### id：执行顺序

- **id 相同** → 从上到下依次执行（JOIN 时上面的是驱动表）；
- **id 不同** → **数字越大越先执行**（内层子查询先于外层）；
- **id 为 NULL** → `UNION RESULT` 的合并步骤，最后执行。

### 三种输出格式

```sql
-- 传统表格
EXPLAIN SELECT * FROM orders WHERE user_id = 1;

-- JSON：信息最全，能看到 cost 成本估算
EXPLAIN FORMAT=JSON SELECT * FROM orders WHERE user_id = 1;

-- 树形（8.0.16+）：直观展示算子嵌套关系
EXPLAIN FORMAT=TREE SELECT * FROM orders o JOIN `user` u ON o.user_id = u.id;

-- 实际执行并输出真实耗时与行数（8.0.18+）★最实用
EXPLAIN ANALYZE SELECT * FROM orders WHERE user_id = 1 AND status = 1;
```

`EXPLAIN ANALYZE` 的输出会给出 `actual time=0.05..0.12 rows=12 loops=1`，把**估算值和真实值放在一起对比**，一眼能看出优化器是不是估错了。注意它会**真正执行 SQL**，对 `UPDATE`/`DELETE` 要在事务里跑并回滚。

### 完整排查示例

```sql
-- 现象：这条查询要 3 秒
SELECT * FROM orders WHERE DATE(created_at) = '2026-07-31' ORDER BY amount DESC LIMIT 10;

EXPLAIN ...;
-- type: ALL          → 全表扫，没走索引
-- key: NULL          → 确认没走
-- rows: 2100000      → 扫了 210 万行
-- Extra: Using where; Using filesort  → 还额外排了序

-- 分析：DATE() 函数让 idx_created 失效；amount 排序无索引
-- 优化 1：去掉函数，改范围条件
SELECT * FROM orders
WHERE created_at >= '2026-07-31 00:00:00' AND created_at < '2026-08-01 00:00:00'
ORDER BY amount DESC LIMIT 10;
-- type: range  key: idx_created  rows: 3200  Extra: Using filesort

-- 优化 2：如果这是高频查询，建联合索引让排序也走索引
ALTER TABLE orders ADD KEY `idx_created_amount` (`created_at`, `amount`);
-- 注意：created_at 是范围条件，amount 无法用于排序消除，此处 filesort 仍在
-- 真正有效的做法是缩小时间范围后接受小数据量的 filesort，或按业务改成
-- WHERE created_at = 某天 AND ... 的分区/分表设计
```

这个例子也说明：**优化不是套公式，要一步步 `EXPLAIN` 验证**。

## 踩坑

1. **在小表上做 `EXPLAIN` 得出错误结论**。几百行的测试库，优化器往往直接选全表扫（因为确实更快），看不出任何索引问题。**性能验证必须用生产量级数据**。
2. **`rows` 当成精确值**。它是基于采样统计的估算，误差可能有数量级。真实值看 `EXPLAIN ANALYZE` 的 `actual rows`。
3. **只看 `key` 不看 `key_len`**。联合索引显示被使用，但可能只用了第一列。
4. **忽略 `Extra` 里的 `Using temporary`**。`GROUP BY` 非索引列、`DISTINCT` 大结果集、`UNION` 去重都会建临时表；超过 `tmp_table_size` 会落磁盘（`Created_tmp_disk_tables` 计数增加），性能断崖式下跌。
5. **`EXPLAIN` 不执行 SQL，所以看不出真实耗时**。一条 `EXPLAIN` 看起来很美的 SQL 也可能因为回表次数多而慢。用 `EXPLAIN ANALYZE` 或直接计时。
6. **`EXPLAIN ANALYZE` 会真的执行**。对 `UPDATE`/`DELETE` 用它，数据就真改了。务必包在 `START TRANSACTION; ... ROLLBACK;` 里。
7. **看到 `DEPENDENT SUBQUERY` 不当回事**。这是 O(n²) 的相关子查询，是性能陷阱的重灾区，应改写成 JOIN。
8. **不同 MySQL 版本执行计划不同**。8.0 有 Hash Join、ICP、Skip Scan 等优化，5.7 没有。测试环境和生产版本要一致。
9. **`filtered` 被忽略**。`rows = 1000, filtered = 1.00` 意味着读 1000 行只留 10 行，选择性很差，但只看 `rows` 会觉得还行。

## 面试怎么答

**Q：`EXPLAIN` 你主要看哪几列？**
A：五列。第一是 `type`，访问类型，从好到差是 `const` > `eq_ref` > `ref` > `range` > `index` > `ALL`，及格线是 `range`，出现 `ALL` 说明全表扫。第二是 `key`，看实际用了哪个索引，如果 `possible_keys` 有值但 `key` 是 `NULL`，说明优化器主动放弃了索引，通常是结果集占比太大或统计信息失真。第三是 `key_len`，用它判断联合索引到底用了几列。第四是 `rows`，预估扫描行数，和实际返回行数差距越大说明索引选择性越差。第五是 `Extra`，看有没有 `Using filesort`、`Using temporary` 这类需要额外开销的操作，以及有没有 `Using index` 这种覆盖索引的好现象。

**Q：`type` 里的 `index` 和 `ALL` 有什么区别？**
A：都是「扫全部」，但扫的对象不同。`index` 是遍历整棵索引 B+ 树的叶子层，`ALL` 是遍历聚簇索引的全部叶子也就是全部行数据。因为二级索引只存索引列加主键，体积远小于完整数据，所以 `index` 的 I/O 量更小，而且往往伴随 `Using index`（覆盖索引，不用回表）。但两者都意味着没有有效缩小扫描范围，都需要优化。

**Q：`Using filesort` 一定要消除吗？**
A：不一定。首先它不代表一定用了磁盘文件——数据量小于 `sort_buffer_size` 时在内存里排序，很快。如果排序的数据只有几十上百行，影响可以忽略。真正要处理的是「大结果集排序」，比如先过滤出十万行再排序，这时候要让 `ORDER BY` 的列进入联合索引，利用索引本身的有序性消除排序。注意消除的前提是排序列满足最左前缀且排序方向一致（8.0 之前不支持混合升降序）。

**Q：`EXPLAIN` 和 `EXPLAIN ANALYZE` 的区别？**
A：`EXPLAIN` 只让优化器输出执行计划，不真正执行，所有数字都是基于统计信息的估算，可能和实际差很远。`EXPLAIN ANALYZE` 是 8.0.18 引入的，它会**真正执行 SQL**，然后以树形结构输出每一步的估算成本、实际耗时、实际返回行数和循环次数，可以直接对比估算和实际的偏差，定位优化器为什么选错。代价是会真实执行，对写操作要放在事务里回滚。

**Q：`EXPLAIN` 显示走索引了但线上还是慢，可能是什么原因？**
A：几种常见情况。一是回表次数太多，索引命中的行很多但每行都要随机 I/O 回聚簇索引取数据，这时要做覆盖索引。二是 `Extra` 有 `Using filesort` 或 `Using temporary`，排序和临时表的开销盖过了索引带来的收益。三是 `rows` 估算准但绝对值就是很大，索引选择性不够。四是根本不是 SQL 的问题——锁等待、连接池耗尽、主从延迟、Buffer Pool 命中率低都会表现为「慢」，要结合 `SHOW PROCESSLIST`、`performance_schema` 一起看。

## 参考

- [MySQL 8.0 EXPLAIN 输出格式](https://dev.mysql.com/doc/refman/8.0/en/explain-output.html)
- [MySQL 8.0 EXPLAIN ANALYZE](https://dev.mysql.com/doc/refman/8.0/en/explain.html#explain-analyze)
- [PostgreSQL EXPLAIN 使用与执行计划](https://www.postgresql.org/docs/current/sql-explain.html)
- 相关笔记：[[MySQL 慢查询日志与 SQL 优化流程]]、[[MySQL 索引失效的常见场景]]、[[MySQL 聚簇索引与二级索引回表]]、[[MySQL 联合索引与最左前缀]]
