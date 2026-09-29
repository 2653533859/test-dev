---
created: 2026-07-31
tags: [数据库/执行计划]
---

# MySQL 慢查询日志与 SQL 优化流程

> 性能测试跑出「接口 P95 超标」，下一步就是去数据库找慢 SQL。这篇讲怎么开日志、怎么分析、按什么顺序优化。

![[assets/slow-query-workflow.svg]]
*图示：慢 SQL 从发现到验证的完整闭环——用慢查询日志找出 TopN，用 `EXPLAIN` 定位瓶颈类型，按 type / rows / filesort / 回表四条支线分别处理，最后必须同口径回归验证。*

## 概念

### 慢查询日志记录什么

MySQL 会把**执行时间超过阈值**的 SQL 写进慢查询日志，包括：

- 查询耗时 `Query_time`；
- 锁等待时间 `Lock_time`；
- 发送给客户端的行数 `Rows_sent`；
- **实际扫描的行数 `Rows_examined`** ← 最关键的指标。

`Rows_examined / Rows_sent` 的比值是**扫描效率比**：返回 10 行却扫了 100 万行（比值 10 万），基本可以断定索引有问题。

### 慢的四种根因

排查时先归类，别一上来就乱调：

| 根因 | 特征 | 手段 |
|------|------|------|
| **索引问题** | `Rows_examined` 巨大，`type: ALL` | 加/改索引、改写 SQL |
| **锁等待** | `Query_time` 大但 `Rows_examined` 小，`Lock_time` 大 | 查 `SHOW ENGINE INNODB STATUS`、缩短事务 |
| **数据量问题** | SQL 和索引都对，就是数据太多 | 分页、归档、分库分表 |
| **资源问题** | 全库变慢，不针对某条 SQL | 看 CPU / IO / Buffer Pool 命中率 / 连接数 |

**只有第一类才是「优化 SQL」，其余三类改 SQL 没用**——这是新手最容易走弯路的地方。

## 用法

### 开启慢查询日志

```sql
-- 查看当前配置
SHOW VARIABLES LIKE 'slow_query%';
SHOW VARIABLES LIKE 'long_query_time';
SHOW VARIABLES LIKE 'log_queries_not_using_indexes';

-- 运行时开启（重启失效，适合临时排查）
SET GLOBAL slow_query_log = 'ON';
SET GLOBAL long_query_time = 1;                    -- 单位秒，支持小数如 0.1
SET GLOBAL log_queries_not_using_indexes = 'ON';   -- 额外记录未走索引的 SQL
SET GLOBAL log_output = 'FILE';                    -- FILE / TABLE / FILE,TABLE
```

> `long_query_time` 的修改**只对新建连接生效**，当前会话要重连才看得到效果。这个坑很多人踩过，改完发现日志没变化以为没生效。

永久生效写配置文件：

```text
[mysqld]
slow_query_log = 1
slow_query_log_file = /var/log/mysql/slow.log
long_query_time = 1
log_queries_not_using_indexes = 1
log_slow_admin_statements = 1
min_examined_row_limit = 100
```

日志条目长这样：

```text
# Time: 2026-07-31T10:23:11.123456Z
# User@Host: app[app] @ 10.0.1.5 []  Id: 8823
# Query_time: 3.245812  Lock_time: 0.000121  Rows_sent: 10  Rows_examined: 2104398
SET timestamp=1785492191;
SELECT * FROM orders WHERE DATE(created_at) = '2026-07-31' ORDER BY amount DESC LIMIT 10;
```

一眼看出问题：返回 10 行扫了 210 万行。

### 分析工具

```bash
# mysqldumpslow：MySQL 自带，按不同维度聚合
# -s 排序方式：t 总耗时 / at 平均耗时 / c 出现次数 / ar 平均返回行数
# -t 取前 N 条
mysqldumpslow -s at -t 10 /var/log/mysql/slow.log

# pt-query-digest：Percona Toolkit，输出报告更专业（推荐）
pt-query-digest /var/log/mysql/slow.log > report.txt

# 只分析最近 1 小时
pt-query-digest --since '1h' /var/log/mysql/slow.log

# 直接分析 processlist（没开慢日志时应急用）
pt-query-digest --processlist h=127.0.0.1,u=root,p=xxx --run-time 60
```

`pt-query-digest` 报告的核心是把 SQL **按指纹（去掉具体参数值后的模板）聚合**，告诉你哪一类 SQL 占了总耗时的百分之多少。优化要从占比最高的那条开始，而不是从最慢的单条开始——一条 10 秒但一天跑 1 次的，远不如一条 0.5 秒但一秒跑 100 次的重要。

### 不开慢日志时的实时排查

```sql
-- 看当前正在执行的 SQL，Time 列是已执行秒数
SHOW FULL PROCESSLIST;

-- 8.0 推荐用 sys 库，可读性更好
SELECT * FROM sys.session WHERE command != 'Sleep' ORDER BY time DESC;

-- 按平均耗时排序的 TOP SQL（来自 performance_schema，不需要开慢日志）
SELECT
  query,
  db,
  exec_count,
  ROUND(avg_latency / 1000000000, 3) AS avg_sec,
  rows_sent_avg,
  rows_examined_avg
FROM sys.statement_analysis
ORDER BY avg_latency DESC
LIMIT 10;

-- 全表扫描的 SQL
SELECT * FROM sys.statements_with_full_table_scans LIMIT 10;

-- 杀掉失控的查询（谨慎，先确认不是重要业务）
KILL QUERY 8823;
```

### 优化流程（按顺序执行）

```text
第 0 步：量化现状
  记录当前耗时、Rows_examined、QPS。没有基线就没法证明优化有效。

第 1 步：确认是不是 SQL 的问题
  Lock_time 大 → 锁问题，去查事务，不是改 SQL
  全库都慢    → 资源问题，看 CPU / IO / 连接数

第 2 步：EXPLAIN 定位瓶颈类型
  type = ALL              → 没走索引
  rows 巨大               → 索引选择性差
  Extra: Using filesort   → 排序未走索引
  Extra: Using temporary  → 临时表
  无 Using index 且回表多 → 需要覆盖索引

第 3 步：按类型对症下药
  没走索引   → 检查函数/隐式转换/最左前缀/LIKE 前置通配；补索引
  选择性差   → 调整联合索引列顺序，高选择性列靠前；ANALYZE TABLE
  filesort   → ORDER BY 列进联合索引，保持方向一致
  临时表     → GROUP BY 列进索引；减少参与分组的数据量
  回表多     → 构造覆盖索引；深分页用延迟关联

第 4 步：SQL 层面改写
  SELECT * → 只查需要的列
  深分页   → 游标分页 / 延迟关联
  相关子查询 → 改 JOIN
  OR       → UNION ALL 或 index merge

第 5 步：回归验证
  同口径对比耗时和 Rows_examined
  确认写入性能没有明显退化（每加一个索引都有写代价）
  在生产量级数据上验证，不要在几百行的测试库下结论
```

### 常用优化改写对照

```sql
-- ① 函数导致失效
-- 慢
SELECT * FROM orders WHERE DATE(created_at) = '2026-07-31';
-- 快
SELECT * FROM orders WHERE created_at >= '2026-07-31' AND created_at < '2026-08-01';

-- ② 深分页
-- 慢
SELECT * FROM orders ORDER BY id LIMIT 500000, 20;
-- 快（游标分页）
SELECT * FROM orders WHERE id > 500000 ORDER BY id LIMIT 20;
-- 快（延迟关联，适用于不能保证 id 连续的场景）
SELECT o.* FROM orders o
JOIN (SELECT id FROM orders ORDER BY id LIMIT 500000, 20) t ON o.id = t.id;

-- ③ 相关子查询
-- 慢
SELECT u.name, (SELECT COUNT(*) FROM orders o WHERE o.user_id = u.id) FROM `user` u;
-- 快
SELECT u.name, IFNULL(t.cnt, 0)
FROM `user` u
LEFT JOIN (SELECT user_id, COUNT(*) cnt FROM orders GROUP BY user_id) t ON u.id = t.user_id;

-- ④ OR 拆分
-- 慢
SELECT * FROM `user` WHERE phone = '138...' OR email = 'a@b.c';
-- 快
SELECT * FROM `user` WHERE phone = '138...'
UNION
SELECT * FROM `user` WHERE email = 'a@b.c';

-- ⑤ 批量删除拆分，避免长事务和主从延迟
-- 慢且危险
DELETE FROM orders WHERE created_at < '2025-01-01';
-- 安全（循环执行到 ROW_COUNT() = 0）
DELETE FROM orders WHERE created_at < '2025-01-01' LIMIT 1000;
```

### 测试同学的落地做法

在性能测试流程中，慢查询日志应该是**标准产出物**：

```bash
# 压测前：清空慢日志、降低阈值
mysql -e "SET GLOBAL long_query_time = 0.1;"
mv /var/log/mysql/slow.log /var/log/mysql/slow.log.bak
mysql -e "FLUSH SLOW LOGS;"

# 压测中：观察实时状态
mysqladmin -i 5 extended-status | grep -E 'Slow_queries|Threads_running'

# 压测后：出报告
pt-query-digest /var/log/mysql/slow.log > perf_report_$(date +%F).txt
mysql -e "SET GLOBAL long_query_time = 1;"
```

把 `pt-query-digest` 报告的 Top 5 SQL 连同 `EXPLAIN` 输出一起附在性能测试报告里，比只报一个「TPS 不达标」有价值得多。

## 踩坑

1. **改了 `long_query_time` 没生效**。它只对**新建立的连接**生效，已有连接（包括你当前的会话）保持旧值。重连或用 `SET SESSION` 同时改。
2. **慢日志把磁盘写满**。`long_query_time = 0` 会记录所有 SQL，高 QPS 下几分钟就是几个 G。排查完立刻改回去，并配置日志轮转。
3. **只盯最慢的单条 SQL**。真正的性能瓶颈往往是「不算特别慢但调用极频繁」的那条。用 `pt-query-digest` 看**总耗时占比**（`Response time` 的百分比列）而不是最大耗时。
4. **`Rows_examined` 小但 `Query_time` 大**。这不是索引问题，是**锁等待**或**资源争抢**。去看 `Lock_time` 和 `SHOW ENGINE INNODB STATUS`，不要瞎加索引。
5. **在测试库优化，生产不生效**。数据量、数据分布、统计信息、MySQL 版本、参数配置都可能不同。优化结论必须在同量级环境验证。
6. **加索引解决了读，拖垮了写**。每个索引都要在 `INSERT`/`UPDATE` 时维护。高写入表加索引前要评估写放大，压测要覆盖写场景。
7. **忘了 `ANALYZE TABLE`**。大批量导入测试数据后统计信息严重失真，`EXPLAIN` 的结论不可信。造完数据先 `ANALYZE`。
8. **`log_queries_not_using_indexes` 长期开着**。小表查询本来就该全表扫，会产生大量噪音日志。临时排查时开。
9. **忽略了 `Lock_time` 里不包含行锁等待**。`Lock_time` 统计的是表级锁（MDL）时间，InnoDB 行锁等待时间不在里面，要通过 `performance_schema.data_lock_waits` 或 `SHOW ENGINE INNODB STATUS` 看。

## 面试怎么答

**Q：线上一个接口变慢了，你怎么排查到数据库？**
A：分层排查。先看应用监控确认耗时是消耗在数据库调用上，再进数据库侧。第一步看慢查询日志，用 `pt-query-digest` 按总耗时占比排序，找出 Top N 的 SQL 指纹；如果没开慢日志，用 `sys.statement_analysis` 这个视图也能拿到按平均耗时排序的 TOP SQL。第二步对可疑 SQL 做 `EXPLAIN`，看 `type`、`key`、`rows`、`Extra` 定位是没走索引、选择性差、还是有排序和临时表。第三步区分根因：如果 `Rows_examined` 很大就是索引问题；如果 `Rows_examined` 很小但耗时长，那是锁等待或资源问题，要去看 `SHOW ENGINE INNODB STATUS` 和系统资源，这种情况改 SQL 是没用的。最后改完必须在同量级数据下回归验证，并确认写入性能没退化。

**Q：慢查询日志里你最关注哪个字段？**
A：`Rows_examined` 和 `Rows_sent` 的比值。返回 10 行却扫描了 100 万行，说明过滤条件没有被索引有效利用，这是最典型的索引问题信号。单看 `Query_time` 有误导性，因为它可能包含锁等待时间，而锁等待不是 SQL 本身的问题。

**Q：`EXPLAIN` 说走索引了，为什么还慢？**
A：几种可能。回表次数太多——索引命中几万行，每行都要随机 I/O 回聚簇索引，这时要做覆盖索引。`Extra` 里有 `Using filesort` 或 `Using temporary`，额外开销盖过了索引收益。索引选择性不够，`rows` 绝对值仍然很大。还有可能根本不是 SQL 慢，而是锁等待、连接池排队、主从延迟或者 Buffer Pool 命中率低导致的物理读增多，这些都要结合 `SHOW PROCESSLIST` 和 `performance_schema` 一起判断。

**Q：性能测试时你会对数据库做什么？**
A：压测前把 `long_query_time` 调低到 0.1 秒并清空慢日志，确保能捕捉到问题 SQL；准备与生产同量级的数据并执行 `ANALYZE TABLE` 让统计信息准确。压测中监控 `Threads_running`、`Slow_queries`、`Innodb_row_lock_waits`、Buffer Pool 命中率这几个指标。压测后用 `pt-query-digest` 出报告，把 Top 5 慢 SQL 及其 `EXPLAIN` 结果附在性能测试报告里，给开发明确的优化输入，而不是只报一个 TPS 数字。最后记得把 `long_query_time` 改回去。

## 参考

- [MySQL 8.0 慢查询日志](https://dev.mysql.com/doc/refman/8.0/en/slow-query-log.html)
- [MySQL sys schema](https://dev.mysql.com/doc/refman/8.0/en/sys-schema.html)
- [pt-query-digest 文档](https://docs.percona.com/percona-toolkit/pt-query-digest.html)
- 相关笔记：[[MySQL EXPLAIN 执行计划解读]]、[[MySQL 索引失效的常见场景]]、[[MySQL 锁与死锁排查]]
