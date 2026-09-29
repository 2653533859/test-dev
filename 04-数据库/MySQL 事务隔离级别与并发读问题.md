---
created: 2026-07-31
tags: [数据库/事务]
---

# MySQL 事务隔离级别与并发读问题

> 「四种隔离级别分别解决什么问题、MySQL 默认哪一种」是必考题。这篇给出可复现的双会话实验，看完能自己动手验证。

![[assets/isolation-levels.svg]]
*图示：脏读、不可重复读、幻读三类问题的发生过程，以及四种隔离级别对它们的解决情况——隔离性越强，并发性能越低。*

## 概念

### 三类并发读问题，一句话区分

| 问题 | 读到了什么 | 触发的操作 |
|------|-----------|-----------|
| **脏读** | 别人**未提交**的数据 | 别的事务 `UPDATE` 后未提交 |
| **不可重复读** | 同一行两次读**值不同** | 别的事务 `UPDATE` 并已提交 |
| **幻读** | 同一范围两次读**行数不同** | 别的事务 `INSERT` / `DELETE` 并已提交 |

**不可重复读和幻读的区别是最容易搞混的**，抓住这个记忆点：

> 不可重复读针对 **UPDATE**，关注**同一行的内容变了**；幻读针对 **INSERT/DELETE**，关注**结果集多出或少了行**。

从解决手段看也不同：不可重复读只要锁住读过的行（行锁）就能解决；幻读要锁住整个范围（间隙锁），因为「还不存在的行」没法加行锁。

### 四种隔离级别

| 级别 | 脏读 | 不可重复读 | 幻读 | 说明 |
|------|------|-----------|------|------|
| `READ UNCOMMITTED` 读未提交 | ✗ | ✗ | ✗ | 几乎不用 |
| `READ COMMITTED` 读已提交 | ✓ | ✗ | ✗ | Oracle / PostgreSQL 默认 |
| `REPEATABLE READ` 可重复读 | ✓ | ✓ | 基本✓ | **MySQL 默认** |
| `SERIALIZABLE` 串行化 | ✓ | ✓ | ✓ | 全部串行，性能最差 |

（✓ = 解决，✗ = 会发生）

### 为什么 MySQL 默认是 RR 而不是 RC

这是一个有历史原因的好问题：早期 MySQL 的 binlog 只有 **STATEMENT 格式**，在 RC 级别下，由于没有间隙锁，并发的 `INSERT` 和 `DELETE` 语句在 binlog 里的**记录顺序可能与实际执行顺序不一致**，导致从库回放后数据和主库不同。RR 通过间隙锁保证了顺序，才能让主从一致。

现在有了 ROW 格式的 binlog，这个约束不存在了，所以**很多互联网公司（阿里、腾讯等）的规范里都把线上隔离级别调成 RC**——RC 加锁范围更小、没有间隙锁、死锁概率低、并发性能更好。

### MySQL 的 RR 是怎么处理幻读的

标准 SQL 里 RR 是允许幻读的，但 MySQL 的 RR **基本消除了幻读**，靠的是两套机制：

1. **快照读（普通 `SELECT`）** → 走 **MVCC**，整个事务复用第一次读时生成的 ReadView，别人新插入的行不在快照里，自然看不到。
2. **当前读（`SELECT ... FOR UPDATE` / `LOCK IN SHARE MODE` / `UPDATE` / `DELETE`）** → 走 **Next-Key Lock**（行锁 + 间隙锁），把范围锁住，别人根本插不进来。

说「基本」是因为仍有边界情况——先快照读再当前读，会突然看到新行（见踩坑第 4 条）。

## 用法

### 查看与设置隔离级别

```sql
-- MySQL 8.0
SELECT @@global.transaction_isolation, @@session.transaction_isolation;
-- MySQL 5.7 及以前
SELECT @@global.tx_isolation, @@session.tx_isolation;

-- 设置（作用域：SESSION 当前会话 / GLOBAL 之后的新连接）
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;
SET GLOBAL  TRANSACTION ISOLATION LEVEL READ COMMITTED;
```

配置文件永久生效：

```text
[mysqld]
transaction-isolation = READ-COMMITTED
```

### 实验一：复现脏读（READ UNCOMMITTED）

准备两个客户端会话，按时间顺序交替执行：

```sql
-- 建表
CREATE TABLE account (id INT PRIMARY KEY, balance DECIMAL(10,2));
INSERT INTO account VALUES (1, 100.00);
```

```sql
-- 【会话 B】t0：把自己设成读未提交
SET SESSION TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;
START TRANSACTION;

-- 【会话 A】t1：改数据但不提交
START TRANSACTION;
UPDATE account SET balance = 200 WHERE id = 1;
-- 注意：不 COMMIT

-- 【会话 B】t2：读
SELECT balance FROM account WHERE id = 1;
-- 结果：200  ← 脏读！读到了 A 未提交的数据

-- 【会话 A】t3：回滚
ROLLBACK;

-- 【会话 B】t4：再读
SELECT balance FROM account WHERE id = 1;
-- 结果：100  ← B 在 t2 读到的 200 是一个从未真实存在过的值
```

### 实验二：复现不可重复读（READ COMMITTED）

```sql
-- 【会话 B】
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;
START TRANSACTION;
SELECT balance FROM account WHERE id = 1;    -- 100

-- 【会话 A】
START TRANSACTION;
UPDATE account SET balance = 300 WHERE id = 1;
COMMIT;                                       -- 这次真的提交了

-- 【会话 B】同一个事务内，再读一次
SELECT balance FROM account WHERE id = 1;    -- 300 ← 不可重复读！
COMMIT;
```

把会话 B 的隔离级别改成 `REPEATABLE READ` 重跑，第二次读仍是 100 —— 这就是「可重复读」名字的来源。

### 实验三：RR 下的幻读与间隙锁

```sql
CREATE TABLE t (id INT PRIMARY KEY, age INT, KEY idx_age (age));
INSERT INTO t VALUES (1, 10), (5, 20), (10, 30);
```

```sql
-- 【会话 B】RR（默认）
START TRANSACTION;
SELECT * FROM t WHERE age > 15;              -- 快照读，2 行

-- 【会话 A】
INSERT INTO t VALUES (7, 25);                -- 能插入成功
COMMIT;

-- 【会话 B】
SELECT * FROM t WHERE age > 15;              -- 仍是 2 行 ← MVCC 挡住了幻读 ✅
SELECT * FROM t WHERE age > 15 FOR UPDATE;   -- 3 行 ← 当前读看到了新行 ⚠️
COMMIT;
```

如果会话 B 一开始就用当前读，A 就插不进来了：

```sql
-- 【会话 B】
START TRANSACTION;
SELECT * FROM t WHERE age > 15 FOR UPDATE;   -- 加 Next-Key Lock，锁住 (20, +∞)

-- 【会话 A】
INSERT INTO t VALUES (7, 25);
-- 阻塞！等待锁超时：Lock wait timeout exceeded; try restarting transaction
```

### 隔离级别怎么选

```text
READ UNCOMMITTED  → 基本不用，脏读的代价远大于那点性能收益
READ COMMITTED    → 互联网业务推荐：加锁范围小、无间隙锁、死锁少、并发高
                    代价是同一事务内多次读结果可能不同，业务代码要有意识
REPEATABLE READ   → MySQL 默认：需要事务内多次读取一致快照的场景（报表、对账）
SERIALIZABLE      → 只在对一致性要求极高且并发极低的场景用（如财务日终结算）
```

### 测试同学怎么设计相关用例

```text
1. 隔离级别确认：连上被测库先查 @@transaction_isolation，写进测试报告
   —— 隔离级别不同，很多并发 bug 的表现完全不同
2. 并发读写用例：一个线程读、一个线程写，断言读到的值符合当前隔离级别的预期
3. 库存超卖：N 个线程同时下单，断言库存不为负、成功订单数 = 初始库存
4. 幂等性：并发提交同一订单号，断言唯一键生效、只有一笔成功
5. 长事务影响：开一个长事务持锁不放，验证其他请求是超时报错还是无限等待
6. 报表一致性：在生成报表的事务执行中并发修改数据，断言报表数据自洽
```

## 踩坑

1. **不知道被测环境的隔离级别就开始测并发**。测试库是 RR、生产是 RC，同一个用例的结果可能完全不同。**连上库第一件事就是查 `@@transaction_isolation`**。
2. **`SET GLOBAL` 对当前连接不生效**。它只影响之后新建立的连接，当前会话要用 `SET SESSION` 或重连。改完发现没变化多半是这个原因。
3. **混淆不可重复读与幻读**。记住：前者是 `UPDATE` 引起的**值变**，后者是 `INSERT`/`DELETE` 引起的**行数变**。
4. **RR 下的幻读并没有完全消除**。经典反例：

   ```sql
   -- 【B】RR
   START TRANSACTION;
   SELECT * FROM t WHERE age > 15;              -- 快照读，2 行，此刻生成 ReadView
   -- 【A】INSERT (7, 25); COMMIT;
   -- 【B】
   UPDATE t SET age = age + 1 WHERE age > 15;   -- 当前读！把 A 插入的行也改了
   SELECT * FROM t WHERE age > 15;              -- 3 行 ← 幻读出现了
   ```

   原因是 `UPDATE` 是当前读，它「碰过」的行会被本事务的 trx_id 标记，在后续快照读中就变得可见了。

5. **RC 下没有间隙锁，但仍可能死锁**。RC 只是缩小了加锁范围，唯一索引冲突、多行更新顺序不一致照样死锁。
6. **`SERIALIZABLE` 下普通 `SELECT` 也会加锁**。它会把所有 `SELECT` 隐式转成 `LOCK IN SHARE MODE`，测试时会发现大量本不该有的锁等待。
7. **RC 下主从复制必须用 ROW 格式 binlog**。用 STATEMENT 格式会导致主从不一致，MySQL 实际上会直接报错拒绝。
8. **误以为隔离级别能解决业务并发问题**。隔离级别管的是「读」的可见性，**扣库存这类「读-改-写」逻辑，即使在 SERIALIZABLE 下也需要业务层的锁或 CAS**（比如 `UPDATE stock SET num = num - 1 WHERE id = 1 AND num >= 1`）。这是很多人的认知盲区。
9. **在自动化用例里用 `sleep` 编排并发时序**。不可靠且慢。用 `threading.Barrier` 或 `Event` 精确控制两个连接的执行顺序。

## 面试怎么答

**Q：说说四种隔离级别，MySQL 默认是哪个？**
A：从低到高是读未提交、读已提交、可重复读、串行化。读未提交什么都不解决，会有脏读；读已提交解决脏读，但有不可重复读和幻读；可重复读解决脏读和不可重复读，标准 SQL 里仍允许幻读，但 MySQL 的 InnoDB 通过 MVCC 和间隙锁基本消除了幻读；串行化全部解决，代价是所有事务串行执行。MySQL 默认是可重复读 RR，而 Oracle 和 PostgreSQL 默认是读已提交 RC。

**Q：不可重复读和幻读有什么区别？**
A：不可重复读针对的是 `UPDATE`，同一个事务内两次读**同一行**，值发生了变化；幻读针对的是 `INSERT` 或 `DELETE`，同一个事务内两次读**同一范围**，行数发生了变化。区别不只在语义，更在解决手段：不可重复读只要给读过的行加行锁就能解决，而幻读要防止「还不存在的行被插入」，行锁无能为力，必须用间隙锁把范围锁住。

**Q：MySQL 为什么默认用 RR？**
A：历史原因。早期 MySQL 的 binlog 只有 STATEMENT 格式，在 RC 级别下因为没有间隙锁，并发的插入删除语句写入 binlog 的顺序可能和实际执行顺序不一致，从库回放后数据会和主库不同。RR 的间隙锁保证了这个顺序。现在有了 ROW 格式 binlog，这个限制已经不存在，所以很多互联网公司的数据库规范反而推荐用 RC——加锁范围小、没有间隙锁、死锁概率低、并发性能更好。

**Q：RR 下真的没有幻读吗？**
A：基本没有，但不是绝对。MySQL 靠两套机制处理：普通 `SELECT` 是快照读，走 MVCC，整个事务复用第一次读时的 ReadView，看不到别人新插入的行；`SELECT ... FOR UPDATE`、`UPDATE`、`DELETE` 是当前读，走 Next-Key Lock 锁住范围，别人插不进来。但有个边界情况会破功：事务先做快照读，然后别的事务插入并提交，本事务再执行一次 `UPDATE`——因为 `UPDATE` 是当前读会更新到新插入的行，并给它打上本事务的 trx_id，之后再快照读就能看到这一行了，幻读就出现了。

**Q：作为测试，隔离级别对你的工作有什么影响？**
A：三方面。第一，测并发场景前必须先确认被测环境的隔离级别，并写进报告，因为同一个用例在 RR 和 RC 下的预期结果不同，环境不一致会导致「测试环境过了生产出问题」。第二，设计并发用例时要针对隔离级别的边界，比如 RC 下要验证同一事务内多次查询结果可能不同时业务是否正确处理。第三，也是最重要的——要清楚隔离级别只解决「读」的可见性，扣库存这类读改写逻辑必须靠业务层的锁或 CAS 保证，所以库存超卖用例必须做，不能因为「数据库是 RR」就以为安全。

## 参考

- [MySQL 8.0 事务隔离级别](https://dev.mysql.com/doc/refman/8.0/en/innodb-transaction-isolation-levels.html)
- [MySQL 8.0 SET TRANSACTION](https://dev.mysql.com/doc/refman/8.0/en/set-transaction.html)
- [PostgreSQL 事务隔离级别（含 RR 与 Serializable Snapshot Isolation）](https://www.postgresql.org/docs/current/transaction-iso.html)
- 相关笔记：[[MySQL MVCC 多版本并发控制]]、[[MySQL 锁与死锁排查]]、[[MySQL 事务与 ACID]]
