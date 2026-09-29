---
created: 2026-07-31
tags: [数据库/事务]
---

# MySQL 事务与 ACID

> 转账扣了钱没到账、订单支付了库存没减——这类 bug 的根源都在事务。测开要能设计出「中途失败」「并发执行」的场景来验证事务边界。

## 概念

### 事务是什么

事务是**一组要么全做、要么全不做的数据库操作**。经典例子是转账：

```sql
UPDATE account SET balance = balance - 100 WHERE id = 1;   -- 扣钱
UPDATE account SET balance = balance + 100 WHERE id = 2;   -- 加钱
```

这两句之间如果宕机，钱就凭空消失了。事务保证它们是一个原子单元。

### ACID 四大特性与实现机制

面试问 ACID，光背定义拿不到分，**要能说出每个特性靠什么机制实现**：

| 特性 | 含义 | InnoDB 的实现 |
|------|------|--------------|
| **A** 原子性 Atomicity | 全成功或全回滚 | **undo log**（回滚日志） |
| **C** 一致性 Consistency | 数据从一个合法状态到另一个合法状态 | 由 A、I、D 加上业务约束共同保证（是**目的**不是手段） |
| **I** 隔离性 Isolation | 并发事务互不干扰 | **锁 + MVCC** |
| **D** 持久性 Durability | 提交后即使宕机也不丢 | **redo log**（重做日志） |

一致性是**目标**，其他三个是**手段**——这句话答出来就比大多数人强。

### undo log：原子性的底座

每次修改数据前，InnoDB 先把**修改前的旧值**写进 undo log：

```text
执行 UPDATE balance 100 → 200
  undo log 记录：「把 balance 改回 100」的逆操作
ROLLBACK 时：按 undo log 逆序执行，把数据恢复原状
```

undo log 还有第二个用途——**MVCC 的版本链**（详见 [[MySQL MVCC 多版本并发控制]]）。所以一个长事务会导致 undo log 无法清理，表空间暴涨。

### redo log：持久性的底座

如果每次提交都把数据页刷到磁盘，随机 I/O 会拖死性能。InnoDB 的做法是 **WAL（Write-Ahead Logging，预写日志）**：

```text
1. 修改内存中的数据页（Buffer Pool），标记为脏页
2. 把「对哪个页做了什么修改」顺序写入 redo log（顺序 I/O，很快）
3. 提交成功返回客户端
4. 脏页由后台线程择机刷盘（随机 I/O，慢，但不阻塞用户）

宕机后重启：读 redo log 重做未落盘的修改 → 数据不丢
```

**关键点：redo log 是顺序写，数据页是随机写。用一次顺序写换掉一次随机写，这就是 WAL 的价值。**

### redo log 与 binlog 的区别（高频考点）

| | redo log | binlog |
|---|---|---|
| 层次 | InnoDB **引擎层** | MySQL **Server 层**（所有引擎都有） |
| 内容 | 物理日志：「在某数据页的某偏移做了什么修改」 | 逻辑日志：SQL 语句或行变更 |
| 写入方式 | **循环写**，空间固定，写满覆盖 | **追加写**，写满换下一个文件 |
| 用途 | **崩溃恢复**（crash-safe） | **主从复制、数据归档、误删恢复** |

两者通过 **两阶段提交（2PC）** 保证一致：`redo prepare` → 写 `binlog` → `redo commit`。这样无论在哪一步宕机，恢复时都能判断该提交还是回滚，避免主从数据不一致。

## 用法

### 基本事务控制

```sql
-- 查看当前自动提交状态（默认 ON：每条语句自成一个事务）
SELECT @@autocommit;

-- 显式事务
START TRANSACTION;                 -- 或 BEGIN;
UPDATE account SET balance = balance - 100 WHERE id = 1;
UPDATE account SET balance = balance + 100 WHERE id = 2;
COMMIT;                            -- 提交；出错则 ROLLBACK;

-- 关闭自动提交（整个会话后续语句都需要显式 COMMIT）
SET autocommit = 0;
```

### 保存点：部分回滚

```sql
START TRANSACTION;
INSERT INTO orders (user_id, amount, status) VALUES (1, 100, 'paid');
SAVEPOINT sp_order;                            -- 打个存档

INSERT INTO order_item (order_id, sku) VALUES (LAST_INSERT_ID(), 'A1');
-- 发现明细有问题，只回滚到存档，订单主表的插入保留
ROLLBACK TO SAVEPOINT sp_order;

INSERT INTO order_item (order_id, sku) VALUES (LAST_INSERT_ID(), 'A2');
COMMIT;

RELEASE SAVEPOINT sp_order;                    -- 释放存档
```

### 在测试中构造事务场景

```python
import pymysql

conn = pymysql.connect(host="127.0.0.1", user="test", password="test",
                       database="testdb", autocommit=False)  # 关键：关掉自动提交
try:
    with conn.cursor() as cur:
        cur.execute("UPDATE account SET balance = balance - 100 WHERE id = %s AND balance >= 100", (1,))
        if cur.rowcount != 1:
            raise ValueError("余额不足，扣款失败")     # 主动制造中断
        cur.execute("UPDATE account SET balance = balance + 100 WHERE id = %s", (2,))
    conn.commit()
except Exception as e:
    conn.rollback()                                   # 验证回滚后数据完整
    print(f"事务回滚: {e}")
finally:
    conn.close()
```

**测开视角的用例设计**：

```text
1. 正常路径：转账成功，两个账户金额之和不变
2. 中途异常：在两条 UPDATE 之间 kill 掉进程 / 抛异常 → 断言两边金额都没变
3. 余额不足：扣款条件不满足 → 断言收款方也没有加钱
4. 并发转账：两个线程同时转账 → 断言总额守恒、没有超额扣款
5. 幂等性：同一笔请求重放两次 → 断言只扣一次（依赖唯一键或状态机）
6. 网络超时：应用侧超时但数据库实际提交了 → 断言不会重复扣款
```

第 6 条是最容易被漏掉的**分布式场景**：客户端超时不等于服务端失败。

### 查看事务状态

```sql
-- 当前所有活跃事务
SELECT trx_id, trx_state, trx_started, trx_mysql_thread_id, trx_query
FROM information_schema.INNODB_TRX;

-- 找出运行超过 60 秒的长事务（重点排查对象）
SELECT trx_id, trx_started, TIMESTAMPDIFF(SECOND, trx_started, NOW()) AS 持续秒数, trx_query
FROM information_schema.INNODB_TRX
WHERE TIMESTAMPDIFF(SECOND, trx_started, NOW()) > 60;

-- 详细的事务与锁信息
SHOW ENGINE INNODB STATUS;
```

### 关键参数

```sql
SHOW VARIABLES LIKE 'innodb_flush_log_at_trx_commit';   -- redo log 刷盘策略
SHOW VARIABLES LIKE 'sync_binlog';                      -- binlog 刷盘策略
```

`innodb_flush_log_at_trx_commit` 的三个取值，是「性能 vs 安全」的经典权衡：

| 值 | 行为 | 风险 |
|---|------|------|
| `1`（默认） | 每次提交都 `fsync` 到磁盘 | 最安全，**不丢数据**，性能最低 |
| `2` | 每次提交写到 OS 缓存，每秒 `fsync` | MySQL 进程崩溃不丢，**操作系统崩溃丢 1 秒** |
| `0` | 每秒才写一次并 `fsync` | 最快，**MySQL 崩溃就丢 1 秒数据** |

生产必须是 `1`（配合 `sync_binlog = 1` 称为「双 1 配置」）。**测试环境造大批量数据时可以临时改成 `2` 或 `0` 提速几倍，造完记得改回来。**

## 踩坑

1. **忘了关 `autocommit`，事务根本没生效**。默认 `autocommit = 1` 时每条语句独立提交，`ROLLBACK` 回滚不了任何东西。Python 的 `pymysql` 默认 `autocommit=False`（符合 DB-API 规范），但有些框架会改，务必确认。
2. **DDL 会隐式提交事务**。事务中间执行 `CREATE TABLE`、`ALTER TABLE`、`TRUNCATE` 会**自动提交前面所有操作**，后续 `ROLLBACK` 无效。造数脚本里千万别混用。
3. **长事务的连锁危害**。一个跑了半小时的事务会：持有锁不放导致大面积阻塞；undo log 无法 purge，`ibdata` 文件持续膨胀；MVCC 版本链变长导致快照读越来越慢；主从延迟加剧。**排查方法**：`information_schema.INNODB_TRX` 找 `trx_started` 很早的事务。
4. **在事务里做慢操作**。调外部 HTTP 接口、发消息队列、读大文件——这些操作把事务持续时间从毫秒拉到秒级。**事务里只做数据库操作**。
5. **异常没捕获导致连接归还时自动回滚/提交**。不同连接池策略不同，有的归还时 `rollback`，有的 `commit`。必须显式处理。
6. **误以为 `ROLLBACK` 能撤销自增值**。回滚后 `AUTO_INCREMENT` 计数器**不回退**（为了并发下不重复分配），id 会出现空洞。断言 id 连续必然失败。
7. **事务中读到自己未提交的修改**。这是正常行为（本事务内可见自己的修改），但容易在写用例时误判。
8. **`innodb_flush_log_at_trx_commit = 0/2` 忘了改回来**。测试环境改快了，结果误配到预发或生产，一次宕机丢一秒数据。
9. **嵌套事务不存在**。MySQL 里再执行一次 `START TRANSACTION` 会**隐式提交**前一个事务，不是嵌套。要分段回滚只能用 `SAVEPOINT`。
10. **大事务撑爆 undo**。一次 `DELETE` 几百万行是一个巨大事务，undo log 暴涨、回滚耗时可能比执行还长。分批处理。

## 面试怎么答

**Q：什么是 ACID？分别怎么实现的？**
A：A 是原子性，事务内操作要么全做要么全不做，靠 **undo log** 实现——修改前先记录逆操作，回滚时逆序执行。I 是隔离性，并发事务互不干扰，靠**锁和 MVCC** 实现。D 是持久性，提交后不丢数据，靠 **redo log** 实现——采用 WAL 机制，先顺序写日志再异步刷脏页，宕机后用 redo log 重做。C 是一致性，指数据从一个合法状态转移到另一个合法状态，它是**目的**而不是手段，由前面三个特性加上主键、外键、唯一约束等业务规则共同保证。

**Q：redo log 和 binlog 有什么区别？为什么需要两阶段提交？**
A：层次不同——redo log 是 InnoDB 引擎层的，binlog 是 Server 层的，所有引擎都有。内容不同——redo log 是物理日志，记录「在某个数据页的什么位置做了什么修改」；binlog 是逻辑日志，记录 SQL 或行变更。写法不同——redo log 空间固定循环写，写满覆盖旧的；binlog 是追加写，可以一直保留。用途不同——redo log 用于崩溃恢复，binlog 用于主从复制和数据恢复。之所以要两阶段提交，是因为两份日志必须保持一致：如果先写 redo 后写 binlog，中间宕机会导致主库有数据而从库没有；反过来则从库多出数据。所以流程是 redo 写入 prepare 状态、写 binlog、再把 redo 置为 commit，恢复时如果发现 redo 是 prepare 状态就去检查 binlog 是否完整，完整就提交，不完整就回滚。

**Q：什么是长事务？有什么危害？怎么排查？**
A：长时间不提交的事务。危害有四个：一是持有的锁一直不释放，其他事务大面积阻塞甚至超时；二是 undo log 无法被 purge 线程清理，表空间持续膨胀；三是 MVCC 版本链越来越长，其他事务的快照读要沿着链回溯更多版本，性能下降；四是主库长事务会导致从库回放延迟。排查用 `information_schema.INNODB_TRX` 查 `trx_started` 早的事务，或者监控 `SHOW ENGINE INNODB STATUS` 里的 History list length。预防手段是设置 `innodb_rollback_on_timeout`、控制事务粒度、事务里不做 RPC 和文件 IO。

**Q：作为测试，你怎么验证一个转账功能的事务正确性？**
A：我会设计六类场景。第一是正常路径，断言转账后两个账户余额之和不变。第二是中途异常，在两次更新之间注入异常或直接 kill 连接，断言两边余额都没有变化。第三是前置条件不满足，比如余额不足，断言收款方也没有增加。第四是并发场景，多线程同时对同一账户转账，断言总额守恒且没有超额扣款——这需要看代码用的是悲观锁 `SELECT ... FOR UPDATE` 还是 CAS 式的 `WHERE balance >= 100`。第五是幂等性，同一请求重放两次断言只生效一次。第六是最容易漏的分布式场景：客户端超时但服务端实际已提交，断言重试时不会重复扣款。验证手段上，除了接口断言，我还会直接查数据库表和流水表做交叉校验。

## 参考

- [MySQL 8.0 InnoDB 事务模型](https://dev.mysql.com/doc/refman/8.0/en/innodb-transaction-model.html)
- [MySQL 8.0 事务语句](https://dev.mysql.com/doc/refman/8.0/en/commit.html)
- [PostgreSQL 事务与并发控制](https://www.postgresql.org/docs/current/transaction-iso.html)
- 相关笔记：[[MySQL 事务隔离级别与并发读问题]]、[[MySQL MVCC 多版本并发控制]]、[[MySQL 锁与死锁排查]]、[[SQL 数据变更：INSERT、UPDATE 与 DELETE]]
