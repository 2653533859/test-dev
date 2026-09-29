---
created: 2026-07-31
tags: [数据库/SQL]
---

# SQL 数据变更：INSERT、UPDATE 与 DELETE

> 造数据、改状态、清现场——测试同学最容易「一条 SQL 毁掉整个测试环境」的地方。这篇除了语法，重点是安全操作规范。

## 概念

### DML 与 DDL 的根本区别

| | DML（`INSERT`/`UPDATE`/`DELETE`） | DDL（`CREATE`/`ALTER`/`DROP`/`TRUNCATE`） |
|---|---|---|
| 事务 | **可回滚**，受事务控制 | **隐式提交**，无法回滚 |
| 触发器 | 会触发 | 不触发 |
| 记录 binlog | 逐行或语句级 | 语句级 |

关键结论：**`DELETE` 写错了还能 `ROLLBACK` 救回来，`TRUNCATE` 和 `DROP` 敲下回车就没了**。这是 `DELETE` / `TRUNCATE` / `DROP` 这道经典面试题的核心。

### `DELETE` / `TRUNCATE` / `DROP` 对比

| | `DELETE FROM t` | `TRUNCATE TABLE t` | `DROP TABLE t` |
|---|---|---|---|
| 类型 | DML | DDL | DDL |
| 能否 `WHERE` | 能 | 不能，只能全清 | 不适用 |
| 能否回滚 | **能**（事务内） | 不能 | 不能 |
| 表结构 | 保留 | 保留 | **一起删掉** |
| 自增值 | **不重置**（InnoDB 8.0 后重启也保留） | **重置为 1** | 不适用 |
| 速度 | 慢（逐行删、写 undo） | 快（直接重建表空间） | 最快 |
| 触发器 | 触发 | 不触发 | 不触发 |

测试场景的选择：**清空一张造数用的临时表用 `TRUNCATE`（快且重置自增，用例可复现）；删部分数据用 `DELETE` 且必须带 `WHERE`**。

## 用法

### INSERT 的几种形态

```sql
-- 单行插入：显式指定列名（强烈推荐，表结构变更时不会错位）
INSERT INTO `user` (name, city, age) VALUES ('张三', '北京', 28);

-- 批量插入：一条语句插多行，比循环单条快一个数量级（少了 N 次网络往返和事务提交）
INSERT INTO `user` (name, city, age) VALUES
('李四', '上海', 35),
('王五', '北京', 22),
('赵六', '广州', 41);

-- 从查询结果插入：造数据时从生产脱敏表灌到测试表
INSERT INTO user_backup (id, name, city)
SELECT id, name, city FROM `user` WHERE created_at < '2026-01-01';

-- 忽略冲突：主键/唯一键重复时跳过，不报错（注意它会吞掉其他错误，慎用）
INSERT IGNORE INTO `user` (id, name) VALUES (1, '张三');

-- 存在则更新（upsert）：幂等造数的利器
INSERT INTO `user` (id, name, age) VALUES (1, '张三', 29)
ON DUPLICATE KEY UPDATE name = VALUES(name), age = VALUES(age);
-- MySQL 8.0.20+ 推荐新语法，VALUES() 已废弃
INSERT INTO `user` (id, name, age) VALUES (1, '张三', 29) AS new
ON DUPLICATE KEY UPDATE name = new.name, age = new.age;

-- REPLACE：先 DELETE 再 INSERT（危险！未指定的列会被重置为默认值，且自增 id 会变）
REPLACE INTO `user` (id, name) VALUES (1, '张三');
```

### UPDATE

```sql
-- 基本更新
UPDATE `user` SET age = 30, city = '深圳' WHERE id = 1;

-- 基于原值计算（原子操作，并发安全）
UPDATE account SET balance = balance - 100 WHERE id = 1 AND balance >= 100;

-- 条件更新
UPDATE orders
SET status = CASE WHEN amount > 200 THEN 'vip_paid' ELSE 'paid' END
WHERE status = 'unpaid' AND created_at < NOW() - INTERVAL 1 DAY;

-- 多表关联更新：把用户表的城市同步到订单快照表
UPDATE orders o
JOIN `user` u ON o.user_id = u.id
SET o.city_snapshot = u.city
WHERE o.city_snapshot IS NULL;

-- 带排序与限制（只改最新的 10 条）
UPDATE orders SET status = 'cancel' WHERE status = 'unpaid' ORDER BY id DESC LIMIT 10;
```

`UPDATE ... WHERE id = 1 AND balance >= 100` 这种写法叫 **CAS（compare-and-set）**，把校验和更新塞进一条原子语句，避免「先查再改」的并发覆盖问题。用 `affected_rows` 判断是否真的改成功了。

### DELETE

```sql
-- 必须带 WHERE
DELETE FROM orders WHERE status = 'cancel' AND created_at < '2026-01-01';

-- 限制影响行数，防手抖
DELETE FROM orders WHERE user_id = 999 ORDER BY id LIMIT 100;

-- 多表关联删除：删掉孤儿订单（对应用户已不存在）
DELETE o FROM orders o
LEFT JOIN `user` u ON o.user_id = u.id
WHERE u.id IS NULL;

-- 清空表
TRUNCATE TABLE tmp_test_data;
```

### 安全操作规范（测试环境铁律）

1. **先 `SELECT` 后 `UPDATE`/`DELETE`**：把 `WHERE` 条件原封不动放到 `SELECT COUNT(*)` 里跑一遍，确认影响行数符合预期。

   ```sql
   SELECT COUNT(*) FROM orders WHERE status = 'cancel' AND created_at < '2026-01-01';
   -- 确认是 37 行，符合预期，再执行
   DELETE      FROM orders WHERE status = 'cancel' AND created_at < '2026-01-01';
   ```

2. **开启安全模式**，禁止不带 key 的批量更新删除：

   ```sql
   SET SQL_SAFE_UPDATES = 1;
   -- 此后 UPDATE/DELETE 若 WHERE 没用到索引列或没有 LIMIT，会报错：
   -- Error Code: 1175. You are using safe update mode ...
   ```

3. **用事务包裹，确认无误再提交**：

   ```sql
   START TRANSACTION;
   DELETE FROM orders WHERE user_id = 123;
   SELECT ROW_COUNT();      -- 看影响行数
   -- 符合预期 → COMMIT;   不符合 → ROLLBACK;
   ROLLBACK;
   ```

4. **改数据前先备份**：`CREATE TABLE orders_bak_20260731 AS SELECT * FROM orders WHERE ...;`（注意这种建表不会复制索引和约束，只作临时备份用）。

## 踩坑

1. **`UPDATE` / `DELETE` 忘写 `WHERE`**——全表被改/被删。这是测试环境事故第一名。开 `SQL_SAFE_UPDATES`，在客户端配置里也打开对应保护。
2. **`WHERE` 条件写成 `=` 但值类型不匹配**。`WHERE name = 0` 在 MySQL 里会把所有非数字字符串隐式转换成 0，结果**匹配全表**。字符串条件一定加引号。
3. **`REPLACE INTO` 把没指定的列清空了**。它的语义是 DELETE + INSERT 而非 UPDATE，未出现在语句里的列会回到默认值，自增主键也会变化，外键关联全断。**用 `ON DUPLICATE KEY UPDATE` 代替**。
4. **`INSERT IGNORE` 吞掉真实错误**。它不只忽略重复键，还会把数据截断、类型错误等降级成 warning，插进去的可能是脏数据。用完记得 `SHOW WARNINGS;`。
5. **批量 `INSERT` 超过 `max_allowed_packet`**。报错 `Packet for query is too large`。造数脚本要分批，每批 500~1000 行比较稳。
6. **`DELETE` 大表不释放磁盘空间**。`DELETE` 只是标记删除，`.ibd` 文件不会变小，产生的空洞要 `OPTIMIZE TABLE`（会锁表重建）才能回收。清空整表用 `TRUNCATE`。
7. **`DELETE` 大量数据导致主从延迟 / 锁等待**。一次删几百万行会产生巨大的 undo 和 binlog，从库回放跟不上。**分批删**：

   ```sql
   -- 循环执行直到 ROW_COUNT() = 0
   DELETE FROM orders WHERE created_at < '2025-01-01' LIMIT 1000;
   ```

8. **自增 id 不连续**。事务回滚、`INSERT IGNORE` 失败都会消耗自增值且不归还（InnoDB 的自增计数器不回退，保证并发下不重复）。用例断言 id 连续必然翻车。
9. **`UPDATE` 时被自己 `SELECT` 的子查询坑到**。MySQL 不允许 `UPDATE t SET ... WHERE id IN (SELECT id FROM t ...)`，报 `You can't specify target table 't' for update in FROM clause`。解法是再套一层派生表：`WHERE id IN (SELECT id FROM (SELECT id FROM t ...) tmp)`。
10. **触发器和级联外键放大影响**。删一行主表可能级联删掉几万行子表，`ON DELETE CASCADE` 在测试库要格外小心。

## 面试怎么答

**Q：`DELETE`、`TRUNCATE`、`DROP` 的区别？**
A：三个维度看。第一，类型不同：`DELETE` 是 DML，可以带 `WHERE`、能在事务里回滚、会触发触发器；`TRUNCATE` 和 `DROP` 是 DDL，隐式提交，**无法回滚**。第二，作用范围不同：`DELETE` 可以删部分行，`TRUNCATE` 清空全表但保留结构，`DROP` 连表结构一起删。第三，实现和副作用不同：`DELETE` 逐行删除、写 undo log、速度慢且不释放磁盘空间，自增值不重置；`TRUNCATE` 直接丢弃并重建表空间，速度快，自增值重置为 1。测试场景里清理造数临时表用 `TRUNCATE`，删业务数据用带 `WHERE` 的 `DELETE`。

**Q：怎么实现「存在就更新，不存在就插入」？**
A：MySQL 用 `INSERT ... ON DUPLICATE KEY UPDATE`，依赖主键或唯一索引冲突来判断。不要用 `REPLACE INTO`，因为它的实现是先删后插，未指定的列会被重置为默认值，自增主键也会变，很容易造成数据丢失和外键失效。另一个选择是 `INSERT IGNORE`，但它只跳过不更新，而且会把很多错误降级成 warning，需要谨慎。

**Q：你在测试环境执行 `UPDATE` 时怎么保证安全？**
A：四步。第一，同样的 `WHERE` 条件先用 `SELECT COUNT(*)` 跑一遍，确认影响行数符合预期；第二，开启 `SQL_SAFE_UPDATES`，强制 `WHERE` 必须命中索引或带 `LIMIT`；第三，用显式事务包裹，执行后看 `ROW_COUNT()`，符合预期才 `COMMIT`，否则 `ROLLBACK`；第四，涉及重要数据先做一份备份表。另外团队层面应该做到测试库和生产库连接配置隔离，避免连错库。

**Q：为什么批量 `INSERT` 比循环单条快？**
A：主要省了三样东西。一是网络往返，1000 条单独执行就是 1000 个 RTT；二是 SQL 解析和优化的开销；三是事务提交次数，如果每条自动提交，就要刷 1000 次 redo log。批量插入把这些摊薄了。实践中一批 500~1000 行比较合适，太大会撞 `max_allowed_packet` 上限，也会让单个事务持锁太久。

## 参考

- [MySQL 8.0 INSERT 语法](https://dev.mysql.com/doc/refman/8.0/en/insert.html)
- [MySQL 8.0 TRUNCATE TABLE](https://dev.mysql.com/doc/refman/8.0/en/truncate-table.html)
- [PostgreSQL INSERT / UPDATE / DELETE 语法](https://www.postgresql.org/docs/current/dml.html)
- 相关笔记：[[MySQL 建表与字段类型选择]]、[[数据库测试数据构造与清理策略]]、[[MySQL 事务与 ACID]]
