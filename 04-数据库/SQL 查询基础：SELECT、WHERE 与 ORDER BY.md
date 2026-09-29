---
created: 2026-07-31
tags: [数据库/SQL]
---

# SQL 查询基础：SELECT、WHERE 与 ORDER BY

> 测试同学 80% 的数据库操作就是「查一条数据出来跟接口返回对比」，这篇把单表查询的四件套 `SELECT` / `WHERE` / `ORDER BY` / `LIMIT` 讲透。

## 概念

### SQL 不是「按你写的顺序」执行的

这是所有 SQL 误解的源头。你写的顺序是：

```sql
SELECT ... FROM ... WHERE ... GROUP BY ... HAVING ... ORDER BY ... LIMIT ...;
```

但数据库**逻辑执行顺序**是：

```text
FROM      → 确定数据来源，产生虚拟表 VT1
WHERE     → 逐行过滤 VT1，产生 VT2         （此时还没有列别名！）
GROUP BY  → 按分组键把 VT2 折叠成组，产生 VT3
HAVING    → 过滤「组」，产生 VT4
SELECT    → 计算表达式、生成列别名，产生 VT5
DISTINCT  → 去重
ORDER BY  → 排序（此时可以用 SELECT 里的别名了）
LIMIT     → 截断
```

记住这条链路，下面两个经典报错就不需要背了：

- `WHERE` 里用不了 `SELECT` 定义的别名（`WHERE` 先于 `SELECT` 执行）；
- `ORDER BY` 里可以用别名（`ORDER BY` 后于 `SELECT` 执行）。

### 三值逻辑：`NULL` 不是「空字符串」也不是 0

SQL 的布尔运算是**三值逻辑**：`TRUE` / `FALSE` / `UNKNOWN`。任何值和 `NULL` 做比较，结果都是 `UNKNOWN`，而 `WHERE` 只保留结果为 `TRUE` 的行。

所以 `WHERE age = NULL` 永远查不出东西，必须写 `WHERE age IS NULL`。这是新手最常见的「明明有数据却查不到」。

## 用法

先建一张贯穿本模块的示例表：

```sql
CREATE TABLE `user` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `name`       VARCHAR(32)     NOT NULL,
  `city`       VARCHAR(32)              DEFAULT NULL,
  `age`        TINYINT UNSIGNED         DEFAULT NULL,
  `balance`    DECIMAL(10, 2)  NOT NULL DEFAULT 0.00,
  `status`     TINYINT         NOT NULL DEFAULT 1 COMMENT '1正常 0禁用',
  `created_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

INSERT INTO `user` (name, city, age, balance, status) VALUES
('张三', '北京', 28, 120.50, 1),
('李四', '上海', 35, 0.00,   1),
('王五', '北京', 22, 88.80,  0),
('赵六', NULL,   41, 300.00, 1),
('钱七', '广州', 28, 15.00,  1);
```

### SELECT：只取你要的列

```sql
-- 别用 SELECT *：多传输无用列、无法走覆盖索引、表结构变更时列顺序会漂
SELECT id, name, city FROM `user`;

-- 列别名（AS 可省略，但写上更清楚）
SELECT name AS 姓名, balance AS 余额 FROM `user`;

-- 表达式与函数
SELECT name, balance * 100 AS balance_fen, UPPER(city) AS city_upper FROM `user`;

-- 去重：DISTINCT 作用于「整个选择列表」，不是只作用于第一列
SELECT DISTINCT city, age FROM `user`;
```

### WHERE：行级过滤

```sql
-- 比较、逻辑
SELECT * FROM `user` WHERE age >= 28 AND status = 1;
SELECT * FROM `user` WHERE city = '北京' OR city = '上海';

-- IN：等价于一串 OR，可读性更好
SELECT * FROM `user` WHERE city IN ('北京', '上海');

-- BETWEEN 是闭区间：等价于 age >= 22 AND age <= 30
SELECT * FROM `user` WHERE age BETWEEN 22 AND 30;

-- LIKE：% 匹配任意长度，_ 匹配单个字符
SELECT * FROM `user` WHERE name LIKE '张%';     -- 走索引
SELECT * FROM `user` WHERE name LIKE '%三';     -- 前置通配，索引失效

-- NULL 判断
SELECT * FROM `user` WHERE city IS NULL;
SELECT * FROM `user` WHERE city IS NOT NULL;

-- 日期范围：推荐左闭右开，避免时分秒边界丢数据
SELECT * FROM `user`
WHERE created_at >= '2026-07-01 00:00:00'
  AND created_at <  '2026-08-01 00:00:00';
```

### ORDER BY 与 LIMIT

```sql
-- 多列排序：先按 city 升序，city 相同再按 balance 降序
SELECT name, city, balance FROM `user` ORDER BY city ASC, balance DESC;

-- MySQL 中 NULL 视为最小值：升序排最前，降序排最后
SELECT name, city FROM `user` ORDER BY city ASC;   -- 赵六（NULL）排第一

-- 想让 NULL 永远垫底
SELECT name, city FROM `user` ORDER BY (city IS NULL), city ASC;

-- LIMIT n：取前 n 条；LIMIT offset, n：跳过 offset 条再取 n 条
SELECT * FROM `user` ORDER BY id LIMIT 3;          -- 第 1~3 条
SELECT * FROM `user` ORDER BY id LIMIT 2, 3;       -- 第 3~5 条（分页第 2 页，每页 3 条）
SELECT * FROM `user` ORDER BY id LIMIT 3 OFFSET 2; -- 同上，可读性更好
```

分页公式：第 `page` 页、每页 `size` 条 → `LIMIT (page - 1) * size, size`。

### CASE WHEN：把状态码翻译成人话

做数据校验时特别有用，可以直接对齐接口返回的枚举文案：

```sql
SELECT
  name,
  CASE status
    WHEN 1 THEN '正常'
    WHEN 0 THEN '禁用'
    ELSE '未知'
  END AS status_text,
  CASE
    WHEN balance = 0        THEN '零余额'
    WHEN balance < 100      THEN '低'
    ELSE '高'
  END AS balance_level
FROM `user`;
```

### 常用函数速查

```sql
SELECT
  IFNULL(city, '未知')            AS city2,     -- NULL 兜底
  COALESCE(city, name, '-')       AS first_not_null,
  CONCAT(name, '@', IFNULL(city, '')) AS tag,
  LENGTH('中文'),  CHAR_LENGTH('中文'),          -- 6（字节） vs 2（字符）
  DATE_FORMAT(created_at, '%Y-%m-%d') AS d,
  DATEDIFF(NOW(), created_at)     AS days_ago
FROM `user`;
```

## 踩坑

1. **`WHERE age != 28` 查不到 `age IS NULL` 的行**。三值逻辑下 `NULL != 28` 结果是 `UNKNOWN`，不是 `TRUE`。要连 NULL 一起要：`WHERE age != 28 OR age IS NULL`。
2. **`NOT IN` 遇到子查询里的 `NULL` 会全军覆没**。`WHERE id NOT IN (1, 2, NULL)` 恒为空集，因为 `id != NULL` 是 `UNKNOWN`。改用 `NOT EXISTS`，或在子查询里加 `WHERE col IS NOT NULL`。
3. **`AND` / `OR` 优先级踩坑**。`WHERE a = 1 OR a = 2 AND b = 3` 实际是 `a = 1 OR (a = 2 AND b = 3)`，`AND` 优先级高于 `OR`。**混用一定加括号**。
4. **`LIMIT` 不带 `ORDER BY` 结果不稳定**。没有排序时 MySQL 不保证返回顺序，同一条 SQL 两次执行可能返回不同的行，会导致自动化用例偶发失败。**分页必须带一个唯一列兜底排序**（如 `ORDER BY created_at DESC, id DESC`）。
5. **深分页 `LIMIT 1000000, 20` 极慢**。MySQL 要先扫描并丢弃前 100 万行。改用「游标分页」：`WHERE id > 上一页最后一个 id ORDER BY id LIMIT 20`。
6. **`LIKE '%关键字%'` 让索引彻底失效**，全表扫描。数据量大时应上全文索引或 ES。
7. **`utf8mb4_general_ci` 排序规则默认大小写不敏感**，`WHERE name = 'abc'` 能匹配到 `ABC`。做大小写敏感断言要用 `BINARY name = 'abc'` 或改列排序规则为 `utf8mb4_bin`。
8. **浮点比较别用 `=`**。金额字段用 `DECIMAL` 而不是 `FLOAT/DOUBLE`，否则 `WHERE balance = 0.1` 可能查不出来。
9. **测试环境执行前先 `SELECT` 一遍**。养成先用 `SELECT` 验证 `WHERE` 条件命中了几行，再改成 `UPDATE`/`DELETE` 的习惯。

## 面试怎么答

**Q：SQL 的执行顺序是什么？**
A：书写顺序是 `SELECT → FROM → WHERE → GROUP BY → HAVING → ORDER BY → LIMIT`，但逻辑执行顺序是 `FROM → WHERE → GROUP BY → HAVING → SELECT → DISTINCT → ORDER BY → LIMIT`。由此可以推出两个结论：`WHERE` 里不能用 `SELECT` 定义的别名，而 `ORDER BY` 里可以；`WHERE` 过滤行、`HAVING` 过滤组。

**Q：`WHERE` 和 `HAVING` 的区别？**
A：`WHERE` 在分组前对**原始行**过滤，不能用聚合函数；`HAVING` 在分组后对**组**过滤，可以用聚合函数。性能上能写在 `WHERE` 的条件就别放 `HAVING`，因为 `WHERE` 先过滤能减少参与分组的数据量，而且 `WHERE` 能走索引。

**Q：`NULL` 有什么坑？**
A：三点。第一，`NULL` 参与任何比较结果都是 `UNKNOWN`，所以只能用 `IS NULL` / `IS NOT NULL` 判断；第二，`COUNT(列)` 会跳过 `NULL` 而 `COUNT(*)` 不会；第三，`NOT IN` 的候选集里只要有一个 `NULL`，整个条件就恒为空集，这时应换成 `NOT EXISTS`。

**Q：`LIMIT 1000000, 10` 为什么慢？怎么优化？**
A：MySQL 会先按顺序取出前 1000010 行，再丢弃前 1000000 行，扫描量随页码线性增长。优化有三种思路：一是游标分页，用上一页最后一个 `id` 做 `WHERE id > ?` 条件，让 B+ 树直接定位；二是延迟关联，先在覆盖索引上分页拿主键 `SELECT id FROM t ORDER BY id LIMIT 1000000, 10`，再回表 `JOIN` 取完整行；三是业务上限制最大可翻页数。

**Q：你在测试中怎么用 SQL 做结果校验？**
A：接口返回后，用同样的业务条件去库里查一遍做交叉验证。要点是：只查需要断言的列，条件写死不依赖库里的历史脏数据，日期条件用左闭右开区间，排序带唯一键保证幂等，最后用 `pymysql` 把结果转成 dict 跟接口 JSON 逐字段比对。

## 参考

- [MySQL 8.0 SELECT 语法](https://dev.mysql.com/doc/refman/8.0/en/select.html)
- [MySQL 处理 NULL 值](https://dev.mysql.com/doc/refman/8.0/en/working-with-null.html)
- [PostgreSQL SELECT 语法与执行顺序](https://www.postgresql.org/docs/current/sql-select.html)
- 相关笔记：[[SQL 聚合函数与 GROUP BY、HAVING]]、[[SQL 多表连接：INNER JOIN 与 LEFT JOIN]]、[[MySQL 索引失效的常见场景]]
