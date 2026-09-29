---
created: 2026-07-31
tags: [数据库/事务]
---

# MySQL MVCC 多版本并发控制

![[assets/mvcc-version-chain.svg]]

*图示：undo log 版本链 + ReadView 可见性判断，决定一个事务能看到哪个版本的数据。*

## 概念

MVCC（Multi-Version Concurrency Control，多版本并发控制）是 InnoDB 实现**读不加锁、读写不阻塞**的底层机制。它通过给每行数据保存「多个历史版本」，让读请求去读自己该看到的那个版本，从而避免了读和写之间互相阻塞。

核心结论先记住：

- **快照读（Snapshot Read）**：普通的 `SELECT` 走 MVCC，不加锁，读的是某个时间点的快照。
- **当前读（Current Read）**：`SELECT ... FOR UPDATE`、`UPDATE`、`DELETE`、`INSERT` 读的是最新已提交版本，并且加锁。
- MVCC 只在 **RC（读已提交）** 和 **RR（可重复读）** 两个隔离级别下生效；RU 直接读最新，SERIALIZABLE 退化为加锁读。

### 三个隐藏字段

InnoDB 每行记录除了你定义的列，还自带几个隐藏字段：

| 字段 | 含义 |
| --- | --- |
| `DB_TRX_ID` | 最近一次修改这行的事务 ID |
| `DB_ROLL_PTR` | 回滚指针，指向 undo log 里的上一个版本 |
| `DB_ROW_ID` | 行 ID（没有聚簇索引键时作为隐藏主键） |

### undo log 版本链

每次更新一行，InnoDB 会把**修改前的旧值**写入 undo log，并用 `DB_ROLL_PTR` 把新旧版本串成一条链表。最新版本在聚簇索引页里，历史版本在 undo log 里，通过回滚指针一路往前追溯。

### ReadView（读视图）

事务在**第一次快照读**时（RR）或**每次快照读**时（RC）生成一个 ReadView，里面记录了四个关键信息：

- `m_ids`：当前**活跃（未提交）**的事务 ID 列表
- `min_trx_id`：`m_ids` 里的最小值
- `max_trx_id`：系统将要分配的下一个事务 ID
- `creator_trx_id`：创建这个 ReadView 的事务自己的 ID

可见性判断规则（顺着版本链从新到旧找第一个可见的）：
1. 若 `DB_TRX_ID == creator_trx_id`：是自己改的，可见。
2. 若 `DB_TRX_ID < min_trx_id`：在 ReadView 生成前就已提交，可见。
3. 若 `DB_TRX_ID >= max_trx_id`：在 ReadView 生成后才开启，不可见，顺着指针找更早版本。
4. 若 `min_trx_id <= DB_TRX_ID < max_trx_id`：看它是否在 `m_ids` 里 —— 在（未提交）就不可见，不在（已提交）就可见。

## 用法

### 实验：RR 下可重复读是怎么做到的

准备一张表：

```sql
CREATE TABLE account (
  id   INT PRIMARY KEY,
  name VARCHAR(20),
  balance INT
);
INSERT INTO account VALUES (1, 'A', 100);
```

开两个会话，都设置 `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;`（MySQL 默认）。

会话 1：

```sql
START TRANSACTION;
SELECT balance FROM account WHERE id = 1;   -- 读到 100
```

会话 2（另一个连接）：

```sql
START TRANSACTION;
UPDATE account SET balance = 200 WHERE id = 1;
COMMIT;
```

会话 1 再次读：

```sql
SELECT balance FROM account WHERE id = 1;   -- RR 下仍然读到 100！
```

原因：会话 1 在第一次 `SELECT` 时就生成了 ReadView，之后整个事务都复用这个 ReadView，所以看到的始终是「事务开始那一刻」的快照，这就是**可重复读**。

### 实验：RC 下每次读都重新生成 ReadView

同样的步骤，但隔离级别设为 `READ COMMITTED`：

```sql
SET TRANSACTION ISOLATION LEVEL READ COMMITTED;
START TRANSACTION;
SELECT balance FROM account WHERE id = 1;   -- 100
-- 会话2 提交 200 后
SELECT balance FROM account WHERE id = 1;   -- RC 下读到 200
```

因为 RC 每次 `SELECT` 都重新生成 ReadView，已经提交的会话 2 自然就可见了。

### MVCC 与「幻读」的关系

RR 级别下 MVCC 解决了**快照读**的幻读（同一事务内多次范围查询看到同样的数据行）。但**当前读**（如 `SELECT ... FOR UPDATE`）可能看到别的事务新插入并提交的行 —— 这时靠 **Next-Key Lock（间隙锁 + 记录锁）** 来防住，详见 [[MySQL 锁与死锁排查]]。

## 踩坑

1. **以为 MVCC 能解决所有并发问题**：MVCC 只覆盖快照读。一旦你用 `FOR UPDATE`/`UPDATE`，就进入当前读，要靠锁来保序，别把 MVCC 当万能锁。
2. **长事务是 undo log 膨胀的元凶**：版本链依赖 undo log，而 undo log 只有在「没有任何活跃事务还需要它」时才能被 purge 清理。一个开了几小时没提交的事务，会让一堆旧版本无法回收，表空间越来越大、回滚变慢。
3. **RR 下看到「旧数据」误以为是 bug**：其实是可重复读的预期行为。测并发用例时，务必明确你测的是「同一事务内可重复读」还是「跨事务读到最新提交」。
4. **把 `SELECT` 不加锁当成绝对安全**：快照读虽然不加锁，但如果你的业务逻辑是「先读后写」依赖读到的旧值做判断，再 `UPDATE`，中间别的事务可能已经改了 —— 这种要用当前读 + 合适的锁（乐观锁 / `FOR UPDATE`）保护。
5. **误以为 ReadView 在事务开始时就生成**：RR 下 ReadView 是在**第一次快照读**时生成，不是 `START TRANSACTION` 那一刻。如果 `START` 后先等了几秒才第一次 `SELECT`，这几秒内别人提交的版本你也能看到。
6. **RC 下「读已提交」不等于「读已提交的最新」**：RC 每次快照读重新生成 ReadView，确实能读到已提交的，但如果别的事务在你读之后又改又提交，你下一次读又会变 —— 不可重复读问题依然存在，这正是 RC 与 RR 的区别。
7. **大事务里反复快照读，ReadView 复用导致「看不到现在」**：RR 复用 ReadView 是优点也是坑，测试「实时性」需求时，RR 事务内永远看不到别人新提交的数据，要分清是不是隔离级别导致的。
8. **delete 产生的版本也会进链**：删除并不是立刻物理删除，而是打一个「删除标记」版本进 undo log，同样参与版本链和可见性判断，purge 线程后续才真正清理。

## 面试怎么答

**Q：MVCC 是什么？解决了什么问题？**
A：MVCC 是多版本并发控制，核心是为每行数据维护多个历史版本（通过 undo log 版本链 + 隐藏事务 ID 字段），读请求根据 ReadView 判断可见性，读历史版本而不加锁。它让「读不加锁、读写不阻塞」，提升了并发性能，并支撑了 RC 和 RR 两个隔离级别。

**Q：RC 和 RR 在 MVCC 上的根本区别是什么？**
A：只有一点 —— ReadView 的生成时机。RC 每次 `SELECT` 都重新生成 ReadView，所以能读到每次已提交的最新值，存在不可重复读和幻读；RR 在第一次快照读时生成 ReadView 并整个事务复用，所以同一事务内多次读结果一致，配合 Next-Key Lock 还能防住当前读的幻读。

**Q：MVCC 能完全避免幻读吗？**
A：不能。MVCC 解决的是快照读场景下的幻读；当前读（加锁读 / 写）情况下要靠 Next-Key Lock 锁住间隙来防止别的事务插入，两者配合才在 RR 下解决幻读。

**Q：undo log 一直不清理会怎样？怎么避免？**
A：版本链依赖 undo log，undo log 只有在没有活跃事务还需要它时才能被 purge。长事务 / 未提交事务会卡住 purge，导致 undo 膨胀、回滚段变慢、磁盘占用上涨。避免手段：尽量短事务、及时提交、监控长事务（`information_schema.INNODB_TRX`）。

## 参考

- [MySQL 8.0 InnoDB 多版本机制](https://dev.mysql.com/doc/refman/8.0/en/innodb-multi-versioning.html)
- [MySQL 8.0 InnoDB 一致性非锁定读](https://dev.mysql.com/doc/refman/8.0/en/innodb-consistent-read.html)
- [MVCC 论文：Berndsson & Proceedings of the 2008 ACM SIGMOD](https://dl.acm.org/doi/10.1145/1376616.1376670)
- [[MySQL 事务与 ACID]] —— ACID 中 MVCC 如何支撑 I（隔离性）
- [[MySQL 事务隔离级别与并发读问题]] —— 四种隔离级别与脏读/不可重复读/幻读
- [[MySQL 锁与死锁排查]] —— 当前读与 Next-Key Lock 如何补 MVCC 的短板
