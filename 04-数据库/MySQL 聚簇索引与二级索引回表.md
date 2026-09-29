---
created: 2026-07-31
tags: [数据库/索引]
---

# MySQL 聚簇索引与二级索引回表

> 「回表」是 MySQL 性能问题里出现频率最高的词。搞懂它，就能解释为什么 `SELECT *` 慢而 `SELECT id, name` 快。

![[assets/clustered-vs-secondary.svg]]
*图示：二级索引的叶子只存「索引列 + 主键值」，要拿其他列必须用主键回聚簇索引再查一次——这就是回表；如果查询需要的列在二级索引上全都有，就成了覆盖索引，可以省掉这一步。*

## 概念

### 聚簇索引：索引即数据

InnoDB 的表**本身就是一棵 B+ 树**，这棵树叫**聚簇索引（clustered index）**，它的叶子节点存放的是**完整的行数据**。所以「表数据」和「主键索引」是同一个东西，不存在独立的「数据文件」。

InnoDB 选谁做聚簇索引，有一套固定顺序：

```text
1. 有主键          → 用主键
2. 没主键但有 UNIQUE NOT NULL 索引 → 用第一个这样的索引
3. 都没有          → 自动生成 6 字节隐藏列 ROW_ID 做聚簇索引（对用户不可见，也无法利用）
```

对比一下 MyISAM：MyISAM 的索引和数据是分开的两个文件（`.MYI` / `.MYD`），索引叶子存的是**行的物理地址**，这叫**非聚簇索引 / 堆表**。InnoDB 用聚簇索引的好处是主键查询极快（找到叶子就拿到整行），代价是二级索引要回表。

### 二级索引：叶子存主键，不存行地址

除聚簇索引外的所有索引都是**二级索引（secondary index）**，也叫辅助索引。它的叶子节点存的是：

```text
[索引列的值] + [主键值]
```

**为什么存主键而不是物理地址？** 因为行会因为页分裂、页合并、行更新而在物理上移动。如果二级索引存物理地址，每次行移动都要更新所有二级索引，代价巨大。存主键值就把这一层解耦了——行怎么挪，主键都不变。

代价就是：**通过二级索引查到主键后，还要拿这个主键去聚簇索引里再走一遍 B+ 树，才能取到完整行。这次额外的查找就叫「回表」（back to table）。**

### 回表的成本

```text
SELECT * FROM user WHERE name = '王五';

① 走 idx_name 二级索引：3 次 I/O → 得到 id = 3
② 拿 id = 3 走聚簇索引： 3 次 I/O → 得到整行
总计 6 次 I/O，是主键查询的 2 倍
```

如果 `WHERE name LIKE '王%'` 匹配了 1000 行，就要**回表 1000 次**，而且这 1000 次是**随机 I/O**（主键值无序分布），代价远超一次顺序全表扫。这就是优化器有时宁可全表扫也不走二级索引的原因。

### 覆盖索引：回表的解药

如果一个查询**需要的所有列，在二级索引的叶子节点上都能拿到**，就不需要回表了。这种情况叫**覆盖索引（covering index）**，`EXPLAIN` 的 `Extra` 列会显示 `Using index`。

注意「覆盖索引」不是一种索引类型，而是**索引与查询的匹配关系**——同一个索引，对某些查询是覆盖的，对另一些不是。

## 用法

```sql
CREATE TABLE `user` (
  `id`    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `name`  VARCHAR(32)     NOT NULL,
  `city`  VARCHAR(32)     NOT NULL DEFAULT '',
  `age`   TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `bio`   TEXT,
  PRIMARY KEY (`id`),
  KEY `idx_name` (`name`),
  KEY `idx_city_age` (`city`, `age`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;
```

### 观察回表与覆盖索引

```sql
-- ① 需要回表：bio 不在 idx_name 上
EXPLAIN SELECT * FROM `user` WHERE name = '王五';
-- type: ref  key: idx_name  Extra: NULL          ← 没有 Using index，说明回表了

-- ② 覆盖索引：需要的 name、id 在 idx_name 叶子上全有（叶子 = name + 主键 id）
EXPLAIN SELECT id, name FROM `user` WHERE name = '王五';
-- type: ref  key: idx_name  Extra: Using index   ← 覆盖，不回表

-- ③ 联合索引也覆盖：city、age、id 都在 idx_city_age 上
EXPLAIN SELECT id, city, age FROM `user` WHERE city = '北京';
-- Extra: Using index

-- ④ 多要一列 name，就破功了
EXPLAIN SELECT id, city, age, name FROM `user` WHERE city = '北京';
-- Extra: NULL   ← 回表
```

**记住这条判断法则**：二级索引 `(a, b)` 的叶子节点内容 = `a, b, 主键`。`SELECT` 的列 + `WHERE` 的列 ⊆ 这个集合 → 覆盖索引。

### 用覆盖索引优化深分页

经典的 `LIMIT 100000, 10` 优化，本质就是减少回表次数：

```sql
-- 慢：先回表取出 100010 行完整数据，再丢弃前 100000 行
SELECT * FROM `user` ORDER BY city LIMIT 100000, 10;

-- 快：延迟关联（deferred join）
-- 内层只在索引树上扫，覆盖索引不回表；外层只回表 10 次
SELECT u.* FROM `user` u
JOIN (
  SELECT id FROM `user` ORDER BY city LIMIT 100000, 10
) t ON u.id = t.id;
```

```sql
-- 更快：游标分页，直接用主键定位，扫描量恒定
SELECT * FROM `user` WHERE id > 100000 ORDER BY id LIMIT 10;
```

### 索引下推（ICP）：另一种减少回表的机制

MySQL 5.6 引入的 **Index Condition Pushdown**，把本该在 Server 层做的过滤，下推到存储引擎层在索引上先做一遍：

```sql
-- 索引 (city, age)
SELECT * FROM `user` WHERE city LIKE '北%' AND age = 28;
```

- **没有 ICP**：引擎层用 `city LIKE '北%'` 扫出所有匹配行，**每行都回表**，回表后 Server 层再判断 `age = 28`，不匹配的白回表了。
- **有 ICP**：引擎层扫索引时，因为 `age` 也在索引里，**先在索引上过滤掉 `age != 28` 的项**，只对真正满足条件的回表。

`EXPLAIN` 的 `Extra` 显示 `Using index condition` 就是 ICP 生效了。它和 `Using index`（覆盖索引，完全不回表）是两回事，别搞混。

### 三个 Extra 的区别（高频考点）

| Extra | 含义 | 好坏 |
|-------|------|------|
| `Using index` | **覆盖索引**，完全不回表 | 最好 |
| `Using index condition` | **索引下推**，减少了回表次数 | 较好 |
| `Using where` | Server 层做了过滤（数据已从引擎取出） | 一般 |
| `Using index for skip scan` | 跳跃扫描（8.0），联合索引缺最左列时的补救 | 一般 |

## 踩坑

1. **`SELECT *` 是覆盖索引的天敌**。只要表里有一列不在索引上（尤其 `TEXT`/`JSON`），就必然回表。测试查数时也养成只选需要的列的习惯。
2. **回表次数多到优化器放弃索引**。`WHERE city = '北京'` 命中 50 万行，走索引要 50 万次随机回表，优化器算下来不如全表顺序扫，于是 `type` 变成 `ALL`。这时该做的是加覆盖索引或缩小结果集，而不是 `FORCE INDEX` 硬来。
3. **表没有主键**。InnoDB 生成隐藏 `ROW_ID`，这个隐藏列是**全局单调递增的**（不是每表独立），高并发插入多张无主键表时会成为全局竞争点，而且主从复制、`pt-` 工具、数据同步组件大多依赖主键，没有主键会各种出问题。**每张表必须有显式主键**。
4. **主键设计得太大**。UUID 字符串主键 36 字节，每一棵二级索引的每一个叶子项都要多背 28 字节，索引整体膨胀好几倍，Buffer Pool 命中率下降。
5. **误以为 `Using index condition` 就是覆盖索引**。前者仍然回表，只是回得少；后者压根不回表。面试被追问这里挂掉的人不少。
6. **前缀索引无法覆盖**。`KEY idx_name (name(8))` 叶子上只有截断的 8 个字符，MySQL 无法确定完整值，因此 `SELECT name` 也必须回表，`Extra` 不会出现 `Using index`。
7. **主键更新引发灾难**。改主键值意味着整行在聚簇索引里删除再插入，且所有二级索引的叶子项都要改。**主键应视为不可变**。
8. **`ORDER BY` 覆盖索引失效**。`SELECT id, city FROM user WHERE city = '北京' ORDER BY age` 中，`age` 不在 `idx_city` 上，会产生 `Using filesort`。把排序列一并放进联合索引。

## 面试怎么答

**Q：什么是聚簇索引？InnoDB 和 MyISAM 有什么区别？**
A：聚簇索引是指索引的叶子节点直接存放整行数据，索引和数据存在一起。InnoDB 的表就是一棵聚簇索引 B+ 树，选主键做聚簇键；没有主键就选第一个唯一非空索引；都没有就生成 6 字节隐藏 `ROW_ID`。MyISAM 是非聚簇的，索引文件 `.MYI` 和数据文件 `.MYD` 分离，索引叶子存的是行的物理地址，所有索引都是等价的。InnoDB 这样设计的好处是主键查询极快、数据按主键顺序物理聚集有利于范围扫描，代价是二级索引查询需要回表。

**Q：什么是回表？为什么二级索引存主键而不是行地址？**
A：回表指的是走二级索引查到主键值后，再拿主键去聚簇索引里查一次才能获取完整行数据，相当于两次 B+ 树查找。之所以存主键而不是物理地址，是因为 InnoDB 的行会因为页分裂、页合并等原因在物理上移动，如果存地址，每次移动都要同步更新所有二级索引，代价极高；存主键值就把物理位置解耦了，行怎么移动主键都不变。

**Q：什么是覆盖索引？怎么用它优化？**
A：如果一个查询所需的全部列都能从二级索引的叶子节点上直接取到（叶子内容是索引列加主键），就不需要回表，这叫覆盖索引，`EXPLAIN` 的 `Extra` 会显示 `Using index`。优化手段主要有三种：一是精简 `SELECT` 的列，别用 `SELECT *`；二是把高频查询需要的少量列加进联合索引，主动构造覆盖；三是深分页用延迟关联——先在覆盖索引上分页拿主键，再用主键 JOIN 回表取完整行，把 10 万次回表降到 10 次。

**Q：`Using index` 和 `Using index condition` 有什么区别？**
A：`Using index` 是覆盖索引，查询所需列全在索引上，**完全不回表**。`Using index condition` 是索引下推（ICP，5.6 引入），指本来要在 Server 层做的过滤条件被下推到存储引擎层，在索引上先过滤一遍，**仍然会回表，只是回表次数变少了**。举例：索引 `(city, age)`，查询 `city LIKE '北%' AND age = 28`，没有 ICP 时所有 `北%` 的行都要回表再判断 age；有 ICP 时在索引里就把 age 不匹配的过滤掉了。两者都是好现象，但优化力度不同。

## 参考

- [MySQL 8.0 聚簇索引与二级索引](https://dev.mysql.com/doc/refman/8.0/en/innodb-index-types.html)
- [MySQL 索引下推 ICP](https://dev.mysql.com/doc/refman/8.0/en/index-condition-pushdown-optimization.html)
- [PostgreSQL 索引类型（堆表与索引组织表对比）](https://www.postgresql.org/docs/current/indexes-types.html)
- 相关笔记：[[MySQL B+ 树索引结构与查找]]、[[MySQL 联合索引与最左前缀]]、[[MySQL EXPLAIN 执行计划解读]]
