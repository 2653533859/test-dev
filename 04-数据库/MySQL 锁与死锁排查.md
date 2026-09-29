---
created: 2026-07-31
tags: [数据库/事务]
---

# MySQL 锁与死锁排查

![[assets/deadlock-cycle.svg]]

*图示：两个事务互相等待对方持有的锁形成环路，InnoDB 检测到后回滚其中之一。*

## 概念

InnoDB 是**行级锁**，锁定的是索引记录而不是行数据本身。理解了「锁挂在索引上」这一点，很多锁行为才讲得通。锁主要分为几类：

| 锁类型 | 锁定范围 | 典型触发 |
| --- | --- | --- |
| 记录锁（Record Lock） | 单条索引记录 | `WHERE id = 1` 命中唯一索引 |
| 间隙锁（Gap Lock） | 两条记录之间的「空隙」 | RR 下范围/不存在的 key 查询 |
| Next-Key Lock | 间隙锁 + 记录锁（左开右闭） | RR 下默认的行锁算法 |
| 意向锁（Intention Lock） | 表级，表有无行锁的标记 | 加行锁前自动加，不阻塞读写只阻塞表锁 |

### 两个关键点

1. **锁是加在索引上的**。如果 `WHERE` 条件没走索引，InnoDB 只能锁**全表**（等价于把所有聚簇索引记录都锁了），这是最常见的「我明明只改一行却把整张表堵死」的原因。
2. **RR 默认用 Next-Key Lock**。它既锁住命中的记录，也锁住它前面的间隙，目的是**防幻读**（别的事务不能在间隙里插入新行）。但也正因为锁了间隙，RR 比 RC 更容易出现锁等待和死锁。

### 死锁

死锁是两个或多个事务**互相等待**对方持有的锁，形成环路。InnoDB 内置死锁检测（`innodb_deadlock_detect=ON`），一旦发现环路会**立即回滚代价较小的事务**（通常是改动行数少的那个），并抛出 `ERROR 1213 (40001): Deadlock found`。注意：被回滚的事务需要业务层**重试**。

## 用法

### 复现一个死锁

两个会话，表：`CREATE TABLE t (id INT PRIMARY KEY, v INT); INSERT INTO t VALUES (1,1),(2,2);`

| 时刻 | 会话 1 | 会话 2 |
| --- | --- | --- |
| T1 | `BEGIN; UPDATE t SET v=10 WHERE id=1;` | |
| T2 | | `BEGIN; UPDATE t SET v=20 WHERE id=2;` |
| T3 | `UPDATE t SET v=11 WHERE id=2;` （等会话2的锁） | |
| T4 | | `UPDATE t SET v=21 WHERE id=1;` （等会话1的锁 → 死锁） |

T4 时形成「1 等 2、2 等 1」的环，InnoDB 立刻报错回滚其中之一，另一个继续执行。

### 查看当前锁等待

```sql
-- 5.7 / 8.0 通用：正在等待锁的事务
SELECT * FROM information_schema.INNODB_TRX
WHERE trx_state = 'LOCK WAIT'\G

-- 8.0 推荐使用 performance_schema 的锁视图
SELECT * FROM performance_schema.data_lock_waits;
SELECT * FROM performance_schema.data_locks;
```

### 排查死锁现场：SHOW ENGINE INNODB STATUS

```sql
SHOW ENGINE INNODB STATUS\G
```

在输出里找 `LATEST DETECTED DEADLOCK` 段，它会打印：
- 参与的两个事务各自持有了什么锁、在等什么锁
- 各自执行的最后一条 SQL
- 谁被回滚了

这是定位死锁原因最直接的依据。

## 踩坑

1. **没走索引导致锁全表**：`UPDATE t SET v=1 WHERE name='x'`，若 `name` 无索引，InnoDB 锁扫描到的所有聚簇记录，等价于表锁，其他写全部阻塞。先 `EXPLAIN` 确认走没走索引。
2. **RR 下间隙锁把并发「堵死」**：范围更新 `UPDATE t SET v=1 WHERE id BETWEEN 10 AND 20` 在 RR 下会锁住 10~20 及相邻间隙，别的事务连插入 21 都可能被卡。高并发写入考虑降到 RC + 业务防重。
3. **死锁被回滚后没重试**：InnoDB 自动回滚一方并抛 `1213`，**被回滚的事务不会自动重试**，业务代码必须捕获该异常后重试，否则这次更新就丢了。
4. **以为 SELECT 一定不加锁**：普通 `SELECT` 才不加锁；`SELECT ... FOR UPDATE` / `LOCK IN SHARE MODE` 是当前读，会加记录锁/间隙锁，用之前想清楚会不会引发锁竞争。
5. **事务里混了慢操作**：事务内调用外部接口、sleep、人工审核，持有锁的时间被拉长，锁等待和死锁概率陡增。事务要「短平快」，只在事务里放必要的 SQL。
6. **加锁顺序不一致引发死锁**：多个事务以**不同顺序**更新同一批资源必然死锁（如一个先 A 后 B，另一个先 B 后 A）。统一「按主键升序 / 固定顺序」加锁能从根上规避。
7. **大事务 + 多行更新放大死锁面**：一次更新上千行，锁的范围大、冲突概率高。拆批、减小事务粒度能显著降低死锁率。
8. **用 `SELECT` 结果做判断再 `UPDATE` 却没加锁**：两段式「先查后改」如果不加 `FOR UPDATE`，查到的值在改之前可能已被别的事务改掉，出现「丢失更新」。要么加锁，要么用带条件的原子 `UPDATE`（如 `UPDATE ... SET v=v+1 WHERE ...`）。

## 面试怎么答

**Q：MySQL 的锁有哪几类？**
A：按粒度有表锁和行锁；行锁里 InnoDB 有记录锁（锁单条）、间隙锁（锁间隙防插入）、Next-Key Lock（记录锁+间隙锁，RR 默认，防幻读）；还有表级的意向锁作为标记。核心要记住：行锁是加在索引上的。

**Q：为什么没走索引的更新会锁整张表？**
A：因为行锁锁定的是索引记录，条件没命中索引时 InnoDB 只能做全表扫描，对扫描到的每条聚簇记录加锁，效果等同表锁，并发写入全部被堵。

**Q：怎么排查死锁？**
A：先看应用日志捕获 `1213` 死锁异常；再用 `SHOW ENGINE INNODB STATUS` 看 `LATEST DETECTED DEADLOCK` 段，里面有双方持有/等待的锁和对应 SQL；定位后统一加锁顺序、缩短事务、降低 RR 间隙锁影响来规避。日常监控可用 `performance_schema.data_locks` / `data_lock_waits`。

**Q：死锁和锁等待有什么区别？**
A：锁等待是单方向的「A 等 B 释放」，B 提交后 A 继续，正常；死锁是双向环路「A 等 B、B 等 A」，谁都走不下去，InnoDB 会检测并回滚代价小的一方来打破环。

## 参考

- [MySQL 8.0 InnoDB 锁机制](https://dev.mysql.com/doc/refman/8.0/en/innodb-locking.html)
- [MySQL 8.0 死锁检测与排查](https://dev.mysql.com/doc/refman/8.0/en/innodb-deadlock-detection.html)
- [MySQL 8.0 PERFORMANCE_SCHEMA 锁等待表](https://dev.mysql.com/doc/refman/8.0/en/performance-schema-data-locks-table.html)
- [[MySQL 事务与 ACID]] —— 锁在 ACID 中如何支撑隔离性
- [[MySQL 事务隔离级别与并发读问题]] —— 隔离级别对锁行为的影响
- [[MySQL MVCC 多版本并发控制]] —— 快照读不加锁，当前读才加锁，二者如何配合
