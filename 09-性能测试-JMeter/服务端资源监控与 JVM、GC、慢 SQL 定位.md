---
created: 2026-07-31
tags: [性能测试/执行与监控]
---

# 服务端资源监控与 JVM、GC、慢 SQL 定位

## 概念

JMeter 测出来 TPS 掉、RT 涨，只说明「系统慢了」，但**慢在哪一层**它说不清。要回答这个问题，必须在压测同时监控**服务端**的资源指标。这一层监控和 [[JMeter 监控：InfluxDB + Grafana]] 的客户端视角是互补的：一个看「压出什么」，一个看「系统扛成什么样」。

监控分三层，由外到内：

- **系统资源层**：CPU、内存、磁盘 IO、网络 IO、连接数、文件句柄。常用 `node_exporter` + Grafana，或 `top`/`nmon`/`dstat` 临时看。
- **JVM 层（Java 应用）**：堆内存、各代占用、GC 次数与耗时、线程数。常用 `jstat`、`jstack`、`jmap`，或 `jmx_exporter` 接 Prometheus/Grafana。
- **数据库层**：慢 SQL、活跃连接数、锁等待、缓冲命中率。靠慢查询日志、`EXPLAIN`、连接池监控（如 Druid）。

定位的核心思路是「先排除外部、再钻进内部」：先确认不是压测机/网络的问题，再看应用进程资源，再看 JVM/GC，最后看数据库。完整链路见 [[性能瓶颈定位顺序与调优对策]]。

## 用法

### 系统资源：边压边看

```bash
# 实时看 CPU、内存、负载
top -H -p $(pgrep -f order-service)

# 看磁盘 IO 与 CPU 等待（%wa 高说明卡在磁盘）
iostat -x 1

# 看网络吞吐与连接数
sar -n DEV 1
ss -s
```

`top` 里 `%wa`（iowait）高说明 CPU 在等磁盘；`load average` 远超核数是过载信号。

### JVM：GC 是否成瓶颈

```bash
# 每 1 秒打印一次 GC 统计（JDK8）
jstat -gcutil <pid> 1000

# 输出示例各列：S0 S1 E O M YGC YGCT FGC FGCT GCT
# O 区（老年代）持续上涨不回落 + FGC 频繁 = 内存泄漏嫌疑
# FGCT 占比高 = Full GC 停顿拖累 RT
```

```bash
# 抓取线程栈，查死锁/大量 BLOCKED/WAITING
jstack <pid> > thread.dump
# 重点看线程状态：BLOCKED 多 = 锁竞争；RUNNABLE 但 CPU 高 = 计算密集
```

### 数据库：定位慢 SQL

```sql
-- MySQL 开慢查询日志后，查超过 1 秒的 SQL
SELECT query_time, sql_text FROM mysql.slow_log
WHERE query_time > 1 ORDER BY query_time DESC LIMIT 20;

-- 对嫌疑 SQL 看执行计划
EXPLAIN SELECT * FROM orders WHERE user_id = 123 AND status = 'PAID';
-- 看 type 列：ALL = 全表扫描（危险）；ref/range = 走索引（好）
-- 看 rows 列：扫描行数越多越慢
-- 看 Extra 列：Using filesort / Using temporary = 排序/临时表，需优化
```

Java 侧用连接池（Druid/HikariCP）监控活跃连接数：连接池打满 + SQL 慢 = 数据库成瓶颈的典型表象。

## 踩坑

1. **只看 JMeter 不盯服务端，永远定位不到根因**：客户端 TPS 掉只告诉我们「慢了」，必须服务端监控同屏才知哪层慢。
2. **压测机自己 CPU 100% 却误判系统瓶颈**：先确认是施压端到顶（见 [[JMeter 分布式压测]]），排除后再看服务端，顺序见 [[性能瓶颈定位顺序与调优对策]]。
3. **`%wa` 高当成 CPU 瓶颈**：iowait 高其实是磁盘/IO 慢，方向错了会白优化 CPU。
4. **GC 看次数不看耗时**：YGC 频繁但耗时短没事；FGC 频繁且 `FGCT` 大才是真问题（长停顿直接拉高 RT）。
5. **老年代只涨不落 = 内存泄漏**：O 区持续上升、FGC 后不回落，基本确定有对象回收不掉，要 `jmap -histo` 抓大对象。
6. **`jstack` 要在问题发生时抓**：压测平稳期抓的栈看不到高峰时的锁竞争，要在 TPS 掉/RT 涨的瞬间抓。
7. **慢 SQL 的 rows 大但走了索引也可能慢**：比如回表量大、或 `Using filesort`，看 `EXPLAIN` 的 Extra 比只看 type 更准。
8. **连接池打满不一定是数据库慢**：也可能是连接泄漏（没 close）、或池子配太小，先查活跃连接是否不释放。
9. **监控时间窗没对齐压测区间**：服务端 Grafana 面板时间窗要和压测时间一致，否则看到的是空载数据，白看。
10. **容器化环境看宿主机 CPU 会误判**：容器内 `top` 看到的是宿主机核数，要进容器命名空间或用 cgroup 指标，否则 CPU 数据失真。
11. **只看平均 RT 不抓长尾对应的服务端事件**：P99 飙的那一刻，往往对应一次 FGC 或慢 SQL，要把分位线尖刺和服务端事件对齐看。
12. **没监控网络 IO 与连接数**：TIME_WAIT 堆积、端口耗尽会让 TPS 上不去，但 CPU 内存都正常，容易被漏掉；`ss -s` 看连接状态分布。

## 面试怎么答

**Q：压测发现 TPS 上不去、RT 高，你怎么一步步定位瓶颈？**

答：分两层。先在 JMeter 客户端确认不是施压端瓶颈（CLI 模式、压测机 CPU 没满、必要时分布式，见 [[JMeter 分布式压测]]）。排除后，边压边看服务端监控：① 系统层 `top`/`iostat` 看 CPU、iowait、网络；② JVM 层 `jstat -gcutil` 看老年代和 Full GC 耗时，高就内存/GC 问题；③ 数据库层开慢查询日志 + `EXPLAIN` 找慢 SQL、看连接池活跃数。定位顺序是「压测机→网络→网关→应用→JVM→数据库」逐层下钻，详细见 [[性能瓶颈定位顺序与调优对策]]。我会把客户端 TPS 曲线和服务端各指标放同一屏对照，RT 尖刺那一刻哪个指标异常就是瓶颈。

**Q：怎么判断 GC 是不是性能瓶颈？**

答：用 `jstat -gcutil <pid> 1000` 看两件事：一是 Full GC 频率，`FGC` 一直在涨说明老年代压力大；二是 Full GC 总耗时 `FGCT` 占应用运行时间的比例，比例高意味着大量时间停在 GC，直接拉高 RT、压低 TPS。另外看老年代 `O` 区，如果回收后不回落、只涨不跌，基本是内存泄漏，要用 `jmap -histo` 抓大对象。Young GC 频繁但耗短通常无害。结论：看 GC 不能只看次数，要看「停顿耗时占比」和「老年代回收是否彻底」。

**Q：慢 SQL 怎么定位和优化？**

答：先开慢查询日志（`long_query_time=1`）捞出超过阈值的 SQL，按耗时排序。然后对每个嫌疑 SQL 跑 `EXPLAIN`：看 `type` 是不是 ALL（全表扫描），看 `rows` 扫描行数，看 `Extra` 有没有 `Using filesort`/`Using temporary`。优化方向通常是：加合适索引、避免 `SELECT *`、减少回表、改写子查询为 JOIN、分页深翻用游标。同时看连接池活跃连接是否打满——打满且 SQL 慢，就是数据库成瓶颈，可能要加索引或升级库配置。

## 参考

- JVM 监控工具文档：<https://docs.oracle.com/en/java/javase/17/docs/specs/man/jstat.html>
- MySQL EXPLAIN 文档：<https://dev.mysql.com/doc/refman/8.0/en/explain-output.html>
- [[JMeter 监控：InfluxDB + Grafana]]
- [[性能瓶颈定位顺序与调优对策]]
- [[JMeter 分布式压测]]
