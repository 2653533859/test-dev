---
created: 2026-09-28
tags: [面试题/数据库]
---

# 大表百万级深分页 LIMIT 优化方案

> `LIMIT 1000000, 20` 缓慢的本质是 MySQL 引擎必须完整扫描并回表读取前 $1000020$ 条完整行数据，最后将前 $1000000$ 条丢弃，造成了海量无用的随机磁盘 IO。核心优化思路是：通过「覆盖索引延迟关联（Deferred Join）」避免无效回表，或通过「标签记录游标分页（Cursor / Keyset Pagination）」将复杂度直接降至 $O(1)$。

## 30 秒回答骨架

- **慢查询根因**：MySQL 执行 `SELECT * FROM orders WHERE status=1 ORDER BY id LIMIT 1000000, 20;` 时，虽然最终只要 20 条，但在 InnoDB 引擎层必须先通过辅助索引（或主键索引）**顺序扫描并回表读取 1000020 行完整的聚簇索引页**，将上百万行数据搬入 Server 层后再白白丢弃前 100 万行，带来致命的磁盘随机读与 Buffer Pool 内存污染。
- **三大主流优化策略**：
  1. **游标记录翻页（Keyset Pagination / 最佳实践）**：改用 `WHERE id > last_max_id LIMIT 20`。直接借助 B+ 树的快速检索能力 $O(\log N)$ 树高定位，完全不扫描前面的废弃行，耗时恒定在毫秒级（常用于移动端瀑布流、消息拉取）；
  2. **覆盖索引子查询延迟关联（Deferred Join）**：`SELECT * FROM orders JOIN (SELECT id FROM orders WHERE status=1 ORDER BY id LIMIT 1000000, 20) AS t USING(id);`。子查询只查主键，命中覆盖索引（无需回表与聚簇扫描），最后只有取出的 20 条数据才发生 20 次聚簇索引回表；
  3. **产品业务与架构妥协**：限制最大翻页深度（如百度/淘宝/京东仅允许翻前 100 页），或者对于数仓离线大表导出改用 Elasticsearch 游标（Search After）或 ClickHouse。

## 展开

### 1. 为什么深分页会发生大量的“无效回表”？

InnoDB 表的数据是按 B+ 树聚簇索引组织存放的。

```text
普通分页 LIMIT 1000000, 20 执行路径：
+-----------------------+           +-----------------------+
|  二级索引 B+ 树 (status) |           |  主键聚簇索引 (表真实数据) |
+-----------------------+           +-----------------------+
| status=1 -> [id=1]    | --------> | 回表读取全部字段...   | (第 1 次)
| status=1 -> [id=2]    | --------> | 回表读取全部字段...   | (第 2 次)
| ...                   |           | ...                   |
| status=1 -> [id=100万] | --------> | 回表读取全部字段...   | (第 1000000 次)
+-----------------------+           +-----------------------+
                                                |
                                                v
                                    【Server 层将前 100 万条全部抛弃！】
```

在执行计划中，`type` 往往是 `ref` 或 `index`，看似走了索引，但实际上在引擎内部执行了 $1000020$ 次聚簇索引回表查询。大表单行字节数较长时，将导致数百万次磁盘物理 IO 读取，把 Buffer Pool 中的热数据全部置换出去。

### 2. 方案对比与具体 SQL 写法

#### 方案 A：延迟关联（Deferred Join，适用于仍需跳页的场景）

利用二级索引或主键索引包含主键 ID 的特性，只通过覆盖索引快速定位偏移量对应的主键集合：

```sql
-- 原低效 SQL (耗时约 4.8 秒)
SELECT id, order_no, user_id, amount, create_time 
FROM t_order 
WHERE user_id = 888 
ORDER BY id 
LIMIT 1000000, 20;

-- 优化为延迟关联 SQL (耗时约 0.15 秒，性能提升 30+ 倍)
SELECT t1.id, t1.order_no, t1.user_id, t1.amount, t1.create_time
FROM t_order t1
JOIN (
    -- 子查询中仅扫描索引树中的 id，完全不需要访问数据页回表
    SELECT id 
    FROM t_order 
    WHERE user_id = 888 
    ORDER BY id 
    LIMIT 1000000, 20
) t2 ON t1.id = t2.id;
```

**原理**：子查询 `(SELECT id ...)` 完全在二级索引树（或主键索引树）上完成遍历，不发生聚簇索引回表；外部 `JOIN` 仅仅针对过滤出来的 **20 个主键 ID** 精准点查回表 20 次。

#### 方案 B：游标记录法（Keyset Pagination / 连续分页首选）

前端每次翻页时，将上一页返回数据的最大（或最小）主键 ID 作为参数回传：

```sql
-- 翻下一页时 (耗时约 1~2 毫秒，复杂度 O(log N))
SELECT id, order_no, user_id, amount, create_time
FROM t_order
WHERE user_id = 888 AND id > 18567290
ORDER BY id ASC
LIMIT 20;
```

**原理**：MySQL 直接通过 B+ 树的树高层级（通常仅 3~4 次 IO）直接 Seek 定位到 `id = 18567290` 所在的叶子节点，然后顺着叶子节点的双向链表向后读取 20 条记录即可，彻底消灭偏移量扫描。

### 3. 三大优化方案综合选型对照表

| 方案 | 优点 | 缺点 / 业务限制 | 适用场景 |
| :--- | :--- | :--- | :--- |
| **游标分页 (id > last_id)** | 性能极高恒定为毫秒级，不受分页深度影响 | **不支持随机跨页跳转**（不能直接点第 500 页）；要求排序字段单调递增且连续 | 移动端下拉刷新、无限滚动流、后台大数据导出批处理任务 |
| **延迟关联 (Deferred Join)** | **支持任意跨页跳转**；兼容传统分页组件 UI | 随着偏移量进一步扩大到千万级别，子查询遍历二级索引本身的扫描开销也会增加 | 后台管理系统列表、报表查询、需要指定跳页的场景 |
| **业务限制最大页数** | 研发成本为 0，彻底根治深度扫描 | 牺牲了翻到最后极端页面的能力 | 绝大多数 C 端搜索页面（如淘宝只展示前 100 页） |

## 可能被追问的点

- **如果业务排序不是基于自增主键 `id`，而是按 `create_time DESC` 排序，游标分页怎么写？**
  - 如果按非唯一字段排序，可能存在重复的 `create_time`，单纯 `WHERE create_time < last_time` 会导致相同时间的数据被漏掉；
  - **解决方案**：建立 `(create_time, id)` 联合索引，游标采用复合条件比较（Row Value Constructor 语法或分解条件）：
    ```sql
    WHERE (create_time < '2026-09-28 10:00:00') 
       OR (create_time = '2026-09-28 10:00:00' AND id < 10052)
    ORDER BY create_time DESC, id DESC
    LIMIT 20;
    ```
- **对于离线数据同步或数仓导出（如亿级单表），如何高效全表扫描？**
  - 切忌用 `LIMIT offset, limit` 循环扫描；
  - 应该基于主键区间切片（Slice ID Range）：例如通过计算 `min(id)` 和 `max(id)`，划分为 `[1, 100000]`, `[100001, 200000]` 的批次并行拉取；
  - 或者利用 `WHERE id > ? ORDER BY id LIMIT 5000` 滚动拉取直至无数据。
- **为什么在测试环境深分页不慢，到了生产环境慢 SQL 频出？**
  - 测试环境数据量小（通常几万条），全表或索引都在操作系统 Page Cache 或 InnoDB Buffer Pool 中，内存访问掩盖了回表的高昂代价；
  - 生产环境表体积可能达数十 GB，远超 Buffer Pool 内存容量，上百万次回表会导致高频的真实磁盘随机寻道（Random Disk Read），产生严重的 IO 瓶颈。

## 结合自己项目的例子

在公司自动化测试平台历史执行结果看板（`tb_test_execution_record` 表，累积超 1200 万行测试报告流水数据）中，测试管理者需要按项目维度分页检索历史压测执行详情。

- **问题爆发**：
  - 用户在筛选某个大项目并翻到 5000 页之后（单页 50 条，偏移量达 25 万+）时，数据库告警报警慢 SQL 激增，API 响应时间从 120ms 劣化到 8.6 秒，导致前端页面网关直接触发 504 Gateway Timeout 超时。
  - `EXPLAIN` 分析：虽然命中了 `idx_project_id` 索引，但 `rows` 预估扫描高达 250050 行，回表读取了长文本 `error_stack` 和 `params_json` 字段。
- **优化改动**：
  1. **UI 体验改造**：针对普通分页场景，引入“延迟关联优化器”；
     ```sql
     SELECT r.id, r.project_id, r.status, r.duration, r.create_time 
     FROM tb_test_execution_record r
     JOIN (
         SELECT id FROM tb_test_execution_record 
         WHERE project_id = 105 
         ORDER BY id DESC 
         LIMIT 250000, 50
     ) sub ON r.id = sub.id;
     ```
  2. **导出大报告场景**：对于全量测试报告导出的后台定时任务，彻底重构掉分页循环，改用基于 Redis 记录偏移主键游标的 `WHERE project_id = 105 AND id < :last_id ORDER BY id DESC LIMIT 500` 滚动流式导出；
  3. **字段精简**：列表查询禁止把大字段 `error_stack` 查出，仅在用户点击查看单条详情时按 ID 精准回表单查。
- **成效**：5000 页深分页响应耗时从 8.6 秒骤降至 **180 毫秒**；数据全量导出耗时降低 75%，消除了 Buffer Pool 抖动引发的数据库 CPU 飙高隐患。

## 参考

- 高性能 MySQL (第4版)：*优化分页与索引回表 (Deferred Joins)*
- MySQL 官方文档：*Optimization and Indexes*
- 相关笔记：[[04-数据库]]、[[联合索引最左前缀与索引失效场景]]、[[Redis 缓存与 MySQL 双写一致性保障方案]]
