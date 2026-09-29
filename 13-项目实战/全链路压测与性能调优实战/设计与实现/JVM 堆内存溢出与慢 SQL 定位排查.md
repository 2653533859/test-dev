---
created: 2026-09-28
tags: [项目实战/性能测试]
---

# JVM 堆内存溢出与慢 SQL 定位排查

> 性能调优进阶实操手册：从 Linux 基础命令排查到 JVM GC 行为诊断、Arthas 运行时方法耗时探测，再到 MySQL 执行计划 EXPLAIN 深度调优，建立立体化全栈排查能力闭环。

## 概念

在性能压测过程中，系统吞吐量上不去通常集中在两大典型病灶：
1. **计算层（JVM）性能瓶颈**：CPU 满载、线程争死锁、或者内存溢出（OOM）、垃圾回收（GC）导致频繁 Stop-The-World（STW）全局停顿。
2. **持久层（MySQL）性能瓶颈**：慢 SQL 拖垮数据库 CPU、锁等待或全表扫描耗尽数据库连接池（HikariCP / Druid）。

针对这两个维度，排查必须遵循**由外而内、自底向上**的标准排障链路：`操作系统资源观测 -> 进程状态与线程栈分析 -> 运行时方法细粒度追踪 -> 数据库底层执行计划校验`。

## 用法

### 1. JVM 堆内存与 GC 停顿排查链路

#### 第一步：定位高消耗 Java 进程与 GC 状态
```bash
# 查看全局各进程占用
top

# 实时监测目标 Java 进程的垃圾回收行为（每 1000ms 刷新一次，共输出 10 次）
# 关注 S0, S1, E, O, M, YGC, YGCT, FGC, FGCT, GCT
jstat -gcutil <PID> 1000 10
```
*判断依据*：如果 `O`（老年代 Old Generation）使用率长期处于 90% 以上，且 `FGC`（Full GC 计数）频繁自增，每次 `FGCT` 耗时数秒，说明存在内存泄露或大对象堆积。

#### 第二步：导出堆快照与内存泄露定位
```bash
# 生成 Heap Dump 文件
jmap -dump:live,format=b,file=heap_dump.hprof <PID>
```
使用 **Eclipse MAT (Memory Analyzer Tool)** 打开 `heap_dump.hprof`：
1. 查看 **Leak Suspects** 报告，MAT 会自动标出占比最大的几个对象。
2. 展开 **Dominator Tree（支配树）**，按 `Retained Heap`（深堆大小）降序排列。
3. 对异常大对象右键选择 `Path to GC Roots -> exclude all phantom/weak/soft references`，寻找是哪个类或全局静态变量引用了该对象，导致无法被回收。

### 2. Arthas 在线动态诊断命令集

无需重启应用，通过阿里开源的 **Arthas** 直接 attach 到目标 JVM：

```bash
# 启动 Arthas
curl -O https://arthas.aliyun.com/arthas-boot.jar
java -jar arthas-boot.jar <PID>
```

#### 实用命令与场景：
- **查看最忙的 CPU 线程栈**：
  ```bash
  # 显示占用 CPU 最高的前 3 个线程堆栈
  thread -n 3
  
  # 查找当前处于死锁或阻塞状态的线程
  thread -b
  ```
- **方法耗时追踪（定位慢逻辑/慢调用）**：
  ```bash
  # 追踪下单接口中耗时超过 50ms 的子调用路径
  trace com.mall.order.service.impl.OrderServiceImpl createOrder '#cost > 50'
  ```
- **查看方法入参与返回值（无需加日志打印）**：
  ```bash
  # 监控扣减库存方法传入的入参和执行异常
  watch com.mall.order.service.impl.StockServiceImpl deductStock "{params, returnObj, throwExp}" -x 2
  ```

### 3. MySQL 慢查询日志与 EXPLAIN 执行计划排查

#### 第一步：开启并抓取慢查询
```sql
-- 运行时动态开启慢查询（耗时超过 0.5s 记录）
SET GLOBAL slow_query_log = 'ON';
SET GLOBAL long_query_time = 0.5;
```

#### 第二步：利用 mysqldumpslow 统计汇总 Top 慢 SQL
```bash
# 按照查询总耗时排序，打印耗时前 10 名的慢 SQL
mysqldumpslow -s t -t 10 /var/lib/mysql/mysql-slow.log
```

#### 第三步：EXPLAIN 核心字段研判
```sql
EXPLAIN SELECT id, order_sn, amount FROM t_order WHERE user_id = 10024 AND status = 2 ORDER BY create_time DESC;
```

*关键字段研读标准*：
- **`type`（访问类型）**：
  - `system` > `const` > `eq_ref` > `ref` > `range` > `index` > `ALL`
  - 达到 `ref` 或 `range` 为合格；若出现 **`ALL`（全表扫描）** 或 **`index`（全索引扫描）**，在大数据量下必死。
- **`key`**：实际命中的索引名称。如果为 `NULL`，表示未命中索引。
- **`rows`**：MySQL 优化器预估需扫描的行数。若 rows 达到几十万甚至百万级别，必须立刻优化。
- **`Extra`**：
  - `Using filesort`：产生了额外的内存/磁盘排序，说明 `ORDER BY` 未命中索引排序。
  - `Using temporary`：使用了临时表保存中间结果，高并发下严重拖垮性能。
  - `Using index`：命中**覆盖索引**，无需回表查询，性能最佳。

## 踩坑

1. **在线生产/压测环境盲目执行 `jmap -dump` 导致长时间服务挂起**：
   - 当 JVM 堆内存高达 32GB 时，执行 `jmap -dump` 会暂停所有用户线程（STW 持续数分钟），直接将服务打崩。
   - *解法*：压测环境建议单节点隔离后执行；或者使用现代的 `jcmd <PID> GC.heap_dump`，更推荐预先配置启动参数 `-XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/data/dump/`，在系统发生 OOM 时由内核自动落盘。
2. **索引字段发生隐式类型转换（Implicit Type Conversion）**：
   - 字段 `user_id` 在表结构定义中是 `varchar(32)`，而在业务代码或 SQL 中传入了整型数字：`WHERE user_id = 10024`。
   - 由于 MySQL 内部会隐式调用 `CAST(user_id AS SIGNED)`，导致 B+ 树索引彻底失效，退化为全表扫描。
3. **最左前缀原则（Leftmost Prefix）断裂**：
   - 建立了联合索引 `idx_a_b_c(a, b, c)`，查询条件为 `WHERE b = 2 AND c = 3`（缺失了最左前导列 `a`），导致联合索引完全无法生效。

## 面试怎么答

**Q：当压测遇到接口响应变慢、TPS 断崖式下跌，你的标准排查思路是怎样的？**
> 调优必须按「系统层 -> 运行时 JVM/线程 -> 应用层代码 -> 数据库与中间件」自底向上循序渐进：
> 1. **系统层看大盘**：利用 `top`、`vmstat`、`iostat` 查看瓶颈究竟落在 CPU、内存、还是磁盘 I/O 上。
> 2. **JVM 层排查 GC 与线程**：
>    - 若 CPU 飙高，用 `top -Hp <pid>` 配合 `jstack` 查找高消耗线程栈，看是否有死循环或正则灾难回溯；
>    - 若 TPS 周期性跌落，用 `jstat -gcutil` 查看是否频繁发生 Full GC，若有则导出 Heap Dump 使用 MAT 支配树定位无界缓存或未释放的大对象。
> 3. **应用运行时精细下钻**：若资源负载平稳但耗时增加，使用 **Arthas** 的 `trace` 动态追踪接口调用链中的每一段内部耗时，精确抓出慢方法或耗时超长的远程 RPC。
> 4. **数据库慢查询下刀**：抓取慢查询日志，对耗时 SQL 执行 `EXPLAIN`。重点查看 `type` 是否退化为 `ALL`、是否命中预期的复合索引，消除 `Using filesort` 和 `Using temporary`，通过合理建立覆盖索引与读写分离破除数据库锁瓶颈。

## 参考

- Arthas 官方命令全集：`https://arthas.aliyun.com/doc/commands.html`
- MySQL 8.0 Reference Manual - EXPLAIN Output Format：`https://dev.mysql.com/doc/refman/8.0/en/explain-output.html`
- 相关笔记：[[09-性能测试-JMeter]]、[[04-数据库]]、[[02-Linux基础]]
- 知识点详解：[[服务端资源监控与 JVM、GC、慢 SQL 定位]]、[[MySQL 索引失效的常见场景]]、[[Linux 内存与 CPU 排查：free、vmstat 与 iostat]]
- 所属项目：[[全链路压测与性能调优实战]]
