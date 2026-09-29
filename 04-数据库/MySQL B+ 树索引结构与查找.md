---
created: 2026-07-31
tags: [数据库/索引]
---

# MySQL B+ 树索引结构与查找

> 「为什么加了索引就快了」不能只答「像书的目录」——面试官想听的是 B+ 树的扇出、树高与磁盘 I/O 次数之间的关系。

![[assets/bplus-tree.svg]]
*图示：三层 B+ 树查找 `id = 30` 的路径——非叶节点只存键与页号，叶子节点存全部数据并用双向链表串起来，因此点查只需 3 次页 I/O，范围查询可以顺着链表横扫。*

## 概念

### 索引要解决的问题：磁盘 I/O

数据库的数据在磁盘上，**一次磁盘 I/O 的代价比内存访问高 5~6 个数量级**。所以索引结构的设计目标不是「比较次数最少」，而是**「磁盘 I/O 次数最少」**。

InnoDB 与磁盘交互的最小单位是**页（page）**，默认 **16KB**。读一个字节和读整页 16KB 的代价几乎一样。因此结论是：

> 让每次 I/O 读到的页里，包含尽可能多的「导航信息」，从而用最少的页数定位到目标。

### 为什么是 B+ 树，不是别的

| 结构 | 为什么被淘汰 |
|------|------------|
| 二叉搜索树 / 平衡树 | 树高 log₂N，100 万行要约 20 层 = 20 次 I/O，太深 |
| 红黑树 | 同上，且非严格平衡，最坏情况更深 |
| 哈希索引 | O(1) 点查很快，但**不支持范围查询、不支持排序、不支持最左前缀**，且哈希冲突时退化 |
| B 树 | 非叶节点也存**数据行**，导致单页能放的键变少、扇出小、树更高；且范围查询要中序回溯 |
| **B+ 树** | 非叶只存键、扇出极大树极矮；数据全在叶子层且用链表相连，范围查询与排序天然高效 |

### 扇出（fan-out）：为什么三层能存两千万行

算一笔账（InnoDB 默认配置）：

```text
一个页 16KB = 16384 字节
非叶节点的一条记录 = 键值 8 字节（BIGINT） + 页号 6 字节 = 14 字节
一个非叶页能放的指针数 ≈ 16384 / 14 ≈ 1170

叶子节点一行假设 1KB → 一个叶子页放 16 行

树高 1 层（只有叶子）：           16 行
树高 2 层：1170 × 16          ≈  1.8 万行
树高 3 层：1170 × 1170 × 16   ≈  2100 万行
```

**结论：两千万行的表，索引树只有 3 层。** 而且根页几乎常驻内存（InnoDB Buffer Pool），实际磁盘 I/O 通常只有 1~2 次。这就是索引快的量化解释。

### B+ 树的三个结构特征

1. **非叶节点只存索引键和子页指针，不存行数据** → 单页能放的键极多 → 扇出大 → 树矮。
2. **所有数据都在叶子节点** → 任何一次查询的路径长度相同，**性能稳定可预测**。
3. **叶子节点之间有双向链表** → `WHERE id BETWEEN 30 AND 100`、`ORDER BY id` 可以定位到起点后顺着链表横扫，不用回到根节点重新查找。

页内部还有一层优化：记录按主键顺序组成单向链表，并划分成若干「槽（slot）」，页目录支持**二分查找**，所以页内定位也不是线性扫描。

## 用法

### 创建与查看索引

```sql
-- 建表时定义
CREATE TABLE `user` (
  `id`    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `name`  VARCHAR(32)     NOT NULL,
  `email` VARCHAR(64)     NOT NULL,
  `city`  VARCHAR(32)     NOT NULL DEFAULT '',
  `age`   TINYINT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),                       -- 聚簇索引
  UNIQUE KEY `uk_email` (`email`),          -- 唯一索引
  KEY `idx_city_age` (`city`, `age`),       -- 联合索引
  KEY `idx_name_prefix` (`name`(8))         -- 前缀索引：只索引前 8 个字符
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

-- 事后添加
ALTER TABLE `user` ADD KEY `idx_age` (`age`);
CREATE INDEX idx_age ON `user` (age);          -- 等价写法

-- 查看
SHOW INDEX FROM `user`;
SHOW CREATE TABLE `user`;
```

`SHOW INDEX` 输出里最值得关注的列：

- `Key_name`：索引名，`PRIMARY` 是主键；
- `Seq_in_index`：该列在联合索引里的位置（从 1 开始）；
- `Cardinality`：**基数**，该列不同值的估算个数。优化器靠它判断索引选择性，值越接近总行数，索引越有效；
- `Non_unique`：0 表示唯一索引。

### 验证树高（进阶）

MySQL 没有直接查树高的语句，但可以从 `information_schema` 的内部表看到：

```sql
-- 需要 8.0 且开启 innodb_metrics，PAGE_LEVEL 即树高 - 1
SELECT NAME, INDEX_NAME, PAGE_NO, LEVEL
FROM information_schema.INNODB_BUFFER_PAGE
WHERE TABLE_NAME LIKE '%user%' AND INDEX_NAME IS NOT NULL;
```

日常更实用的判断方式是看 `EXPLAIN` 的 `rows` 和 `type`，详见 [[MySQL EXPLAIN 执行计划解读]]。

### 前缀索引：长字符串列的折中

```sql
-- 全字段索引太大（email 64 字符）
-- 先测算不同前缀长度的选择性，选择性 = 不同值数 / 总行数，越接近 1 越好
SELECT
  COUNT(DISTINCT LEFT(email, 6))  / COUNT(*) AS sel6,
  COUNT(DISTINCT LEFT(email, 8))  / COUNT(*) AS sel8,
  COUNT(DISTINCT LEFT(email, 12)) / COUNT(*) AS sel12,
  COUNT(DISTINCT email)           / COUNT(*) AS sel_full
FROM `user`;
-- 假设 sel8 = 0.98 已接近 sel_full = 1.0，则取 8

ALTER TABLE `user` ADD KEY `idx_email_prefix` (`email`(8));
```

代价：**前缀索引无法用于覆盖索引**（叶子上只有截断值，MySQL 无法确定完整值），也无法用于 `ORDER BY` 和 `GROUP BY`。

### 索引不是越多越好

每加一个索引，就多一棵 B+ 树需要维护：

- **写放大**：一次 `INSERT` 要更新 N 棵树；`UPDATE` 索引列要在树里做删除 + 插入。
- **空间成本**：索引可能比数据本身还大。
- **优化器负担**：候选索引太多，选错的概率上升。

经验值：**单表索引控制在 5 个以内，联合索引列不超过 5 列**。

## 踩坑

1. **误以为「加了索引一定走索引」**。优化器基于成本估算，如果它认为走索引回表的代价高于全表扫（比如查询要返回全表 30% 以上的数据），会主动放弃索引。这不是 bug。
2. **随机主键导致页分裂**。自增主键是顺序追加，写满一页开新页；UUID 是随机值，新行要插到已满页的中间，触发**页分裂**——把半页数据搬到新页，产生碎片和额外 I/O。表现为写入 TPS 逐渐下降、`.ibd` 文件异常膨胀。
3. **在低基数列上建索引**。性别、`is_deleted` 这类只有 2~3 个值的列，`Cardinality` 极低，走索引反而比全表扫慢（大量随机回表）。这类列只有和高选择性列组成联合索引才有意义。
4. **前缀索引长度选太短**。选择性不足会导致索引扫出一大堆候选再逐个回表校验，`EXPLAIN` 的 `rows` 很大。
5. **`Cardinality` 统计不准导致选错索引**。InnoDB 的基数是采样估算的（采样页数由 `innodb_stats_persistent_sample_pages` 控制，默认 20 页），大批量导入数据后可能严重偏离。执行 `ANALYZE TABLE t;` 重新统计。这是「昨天还好好的 SQL 今天突然全表扫」的常见原因。
6. **删除数据后索引不缩小**。`DELETE` 只标记删除，页内空洞不会自动合并，索引体积不降。`OPTIMIZE TABLE`（本质是重建表）可回收，但会锁写。
7. **在频繁更新的列上建索引**。每次更新都要维护 B+ 树，写性能明显下降。状态机字段要权衡。
8. **`utf8mb4` 下索引长度超限**。InnoDB 单个索引键最长 3072 字节（`DYNAMIC` 行格式），`utf8mb4` 一字符 4 字节，所以 `VARCHAR(768)` 就是上限，超了报 `Specified key was too long`。

## 面试怎么答

**Q：MySQL 为什么用 B+ 树做索引，而不是 B 树、红黑树或哈希？**
A：核心是**减少磁盘 I/O 次数**。数据库最小 I/O 单位是 16KB 的页，索引结构要在一页里塞下尽可能多的导航信息。红黑树、二叉树每个节点只有 2 个分支，100 万行需要约 20 层，就是 20 次 I/O。B 树扇出大一些，但非叶节点也存数据行，占空间导致单页放的键变少、树变高。B+ 树的非叶节点**只存键和指针**，一个 16KB 页能放上千个键，扇出上千，三层就能索引两千万行，实际查询只需 3 次 I/O，其中根页还常驻内存。另外 B+ 树所有数据都在叶子层且用**双向链表**相连，范围查询和 `ORDER BY` 只需定位起点后顺序扫描，这是哈希索引完全做不到的——哈希只支持等值查询，不支持范围、排序和最左前缀。

**Q：一棵 B+ 树能存多少数据？**
A：可以现场算给面试官看。假设主键是 `BIGINT` 8 字节，页号 6 字节，一条非叶记录 14 字节，16KB 页能放约 1170 个指针；叶子页假设一行 1KB，能放 16 行。那么两层是 1170 × 16 ≈ 1.8 万行，三层是 1170 × 1170 × 16 ≈ 2000 万行。所以常说「三层 B+ 树支撑两千万数据」。行越小、主键越短，能存的越多。

**Q：为什么建议用自增主键？**
A：三个原因。第一，自增是顺序写入，新记录总是追加到当前最右的叶子页，写满就开新页，不会触发页分裂；随机主键（如 UUID）要插到已满页的中间，会引发页分裂和碎片，写入性能持续下降。第二，主键短。InnoDB 的二级索引叶子节点存的是主键值，主键从 8 字节变成 36 字节的 UUID，所有二级索引都会跟着膨胀，占用更多内存和 I/O。第三，如果不指定主键，InnoDB 会自己找唯一非空索引，找不到就生成一个 6 字节的隐藏 `ROW_ID`，反而不可控。

**Q：什么是索引的选择性？怎么判断该不该建索引？**
A：选择性 = 不同值的数量 / 总行数，取值 0~1，越接近 1 说明区分度越好。主键选择性是 1，性别列可能只有 0.0000001。选择性太低的列建索引没意义——优化器扫出一大批行还要逐个回表，成本比全表顺序扫还高。判断方法是先 `SELECT COUNT(DISTINCT col) / COUNT(*) FROM t` 算一下，再结合查询频率决定。低选择性的列可以考虑放进联合索引的靠后位置。

## 参考

- [MySQL 8.0 InnoDB 索引](https://dev.mysql.com/doc/refman/8.0/en/innodb-index-types.html)
- [MySQL 8.0 索引优化](https://dev.mysql.com/doc/refman/8.0/en/optimization-indexes.html)
- [Bayer & McCreight：B 树原始论文（Organization of Large Ordered Indices, 1972）](https://doi.org/10.1007/BF00288683)
- [PostgreSQL B-Tree 索引实现](https://www.postgresql.org/docs/current/btree-internals.html)
- 相关笔记：[[MySQL 聚簇索引与二级索引回表]]、[[MySQL 联合索引与最左前缀]]、[[MySQL 索引失效的常见场景]]、[[MySQL 建表与字段类型选择]]
