---
created: 2026-07-31
tags: [数据库/SQL]
---

# SQL 分组取 Top N 与排名查询

> 「第二高的薪水」「每个部门工资前三」——面试现场手写 SQL 的重灾区，本篇给出 MySQL 8.0 窗口函数写法和 5.7 兼容写法两套模板。

## 概念

### 为什么普通聚合做不到

`GROUP BY` 只能把一个组压成**一行**，而 Top N 需要在每组内保留**多行明细并带上组内名次**。聚合函数把明细丢掉了，所以做不到。

MySQL 8.0 引入的**窗口函数（Window Function）**正是为此设计：

> 窗口函数 = 「不折叠行的聚合」。它对每一行，都在一个「窗口」（一批相关行）上做计算，然后把结果作为新列贴回这一行。

语法骨架：

```sql
函数名() OVER (
    PARTITION BY 分组列      -- 可选：把结果集切成若干窗口，类似 GROUP BY 但不折叠
    ORDER BY   排序列        -- 可选：窗口内排序，排名类函数必需
)
```

### 三个排名函数的区别

对成绩 `[90, 90, 80, 70]`：

| 函数 | 结果 | 说明 |
|------|------|------|
| `ROW_NUMBER()` | 1, 2, 3, 4 | 强行编号，并列也不同号 |
| `RANK()` | 1, 1, 3, 4 | 并列同名次，**后面跳号** |
| `DENSE_RANK()` | 1, 1, 2, 3 | 并列同名次，**后面不跳号** |

选哪个取决于业务语义：「工资第二高」通常指去重后的第二档，用 `DENSE_RANK()`；「每组取 3 条明细」用 `ROW_NUMBER()`。

## 用法

```sql
CREATE TABLE `employee` (
  `id`     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `name`   VARCHAR(32)     NOT NULL,
  `dept`   VARCHAR(32)     NOT NULL,
  `salary` DECIMAL(10, 2)  NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_dept_salary` (`dept`, `salary`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

INSERT INTO `employee` (name, dept, salary) VALUES
('A', '研发', 30000), ('B', '研发', 30000), ('C', '研发', 25000),
('D', '研发', 20000), ('E', '测试', 22000), ('F', '测试', 18000),
('G', '测试', 18000), ('H', '产品', 26000);
```

### 场景一：每个部门工资前 2 名（MySQL 8.0）

```sql
SELECT dept, name, salary, rk
FROM (
  SELECT
    dept, name, salary,
    DENSE_RANK() OVER (PARTITION BY dept ORDER BY salary DESC) AS rk
  FROM employee
) t
WHERE rk <= 2                 -- 窗口函数不能直接写在 WHERE 里，必须套一层子查询
ORDER BY dept, rk;
```

**为什么必须套子查询**：窗口函数在 `SELECT` 阶段计算，而 `WHERE` 早于 `SELECT` 执行，所以 `WHERE rk <= 2` 在同一层里拿不到 `rk`。用 `CTE` 写更清爽：

```sql
WITH ranked AS (
  SELECT dept, name, salary,
         DENSE_RANK() OVER (PARTITION BY dept ORDER BY salary DESC) AS rk
  FROM employee
)
SELECT * FROM ranked WHERE rk <= 2 ORDER BY dept, rk;
```

### 场景二：第二高的薪水（经典题）

```sql
-- 写法 1：DENSE_RANK，语义最准（并列第一算一档）
SELECT DISTINCT salary
FROM (SELECT salary, DENSE_RANK() OVER (ORDER BY salary DESC) rk FROM employee) t
WHERE rk = 2;

-- 写法 2：LIMIT + DISTINCT，5.7 也能用
SELECT DISTINCT salary FROM employee ORDER BY salary DESC LIMIT 1 OFFSET 1;

-- 写法 3：子查询排除最大值
SELECT MAX(salary) FROM employee
WHERE salary < (SELECT MAX(salary) FROM employee);
```

三种写法的**边界行为不同**，这正是面试官想追问的点：

- 表里不足两档薪水时，写法 1 和写法 2 返回**空结果集（0 行）**；
- 写法 3 返回**一行 `NULL`**（`MAX` 对空集返回 `NULL`）。

LeetCode 这类题一般要求返回 `NULL`，所以标准答案常写成：

```sql
SELECT (SELECT DISTINCT salary FROM employee ORDER BY salary DESC LIMIT 1 OFFSET 1) AS SecondHighestSalary;
```

外层包一个标量子查询，无结果时自动变成 `NULL`。

### 场景三：MySQL 5.7 没有窗口函数怎么办

**关联子查询计数法**——「比我高的有几个」：

```sql
-- 每个部门工资前 2 名（比自己高的不同薪水少于 2 个）
SELECT e1.dept, e1.name, e1.salary
FROM employee e1
WHERE (
  SELECT COUNT(DISTINCT e2.salary)
  FROM employee e2
  WHERE e2.dept = e1.dept AND e2.salary > e1.salary
) < 2
ORDER BY e1.dept, e1.salary DESC;
```

原理：对每一行 `e1`，去数同部门里薪水严格大于它的**不同薪水档位**有几个。前 2 名意味着比它高的档位数是 0 或 1。

代价：这是 O(n²) 的关联子查询，几万行就会明显变慢，只适合小表或面试作答。生产上要么升 8.0，要么在应用层分组取。

### 场景四：其他常用窗口函数

```sql
SELECT
  dept, name, salary,
  SUM(salary)  OVER (PARTITION BY dept)                    AS 部门总额,   -- 不排序 = 整窗聚合
  ROUND(salary / SUM(salary) OVER (PARTITION BY dept), 4)  AS 占比,
  SUM(salary)  OVER (PARTITION BY dept ORDER BY salary)    AS 累计和,     -- 带排序 = 累计聚合
  LAG(salary)  OVER (PARTITION BY dept ORDER BY salary DESC)  AS 上一名薪水,
  LEAD(salary) OVER (PARTITION BY dept ORDER BY salary DESC)  AS 下一名薪水,
  salary - LAG(salary) OVER (PARTITION BY dept ORDER BY salary DESC) AS 与上一名差值
FROM employee;
```

注意 `SUM() OVER (...)` **加不加 `ORDER BY` 语义完全不同**：不加是整个窗口的总和，加了会变成「从窗口第一行到当前行」的累计和（默认帧 `RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`）。这是窗口函数最隐蔽的坑。

### 场景五：每组取最新一条（测试对数常用）

```sql
-- 每个用户最近一笔订单
WITH latest AS (
  SELECT id, user_id, amount, created_at,
         ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at DESC, id DESC) AS rn
  FROM orders
)
SELECT id, user_id, amount, created_at FROM latest WHERE rn = 1;
```

排序键里**一定要加 `id` 兜底**，否则 `created_at` 相同的两行谁排第一是随机的，自动化用例会偶发失败。

## 踩坑

1. **窗口函数不能写在 `WHERE` / `HAVING` 里**。报错 `Window function is allowed only in SELECT list and ORDER BY clause`。必须套子查询或 CTE。
2. **`ROW_NUMBER` 和 `DENSE_RANK` 用混导致「第二高」算错**。有并列时用 `ROW_NUMBER` 取 `rk = 2`，拿到的是并列第一里的第二个人，不是第二档薪水。
3. **`SUM() OVER (ORDER BY ...)` 变成了累计和**。想要整组合计时不要写 `ORDER BY`，或显式写帧 `ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING`。
4. **MySQL 5.7 及以下没有窗口函数和 CTE**。`WITH` 和 `OVER` 都会语法报错。写脚本前先 `SELECT VERSION();` 确认版本。
5. **`LIMIT 1 OFFSET 1` 忘了 `DISTINCT`**。有并列第一时，`OFFSET 1` 拿到的还是最高薪水。
6. **关联子查询法在大表上是灾难**。数据量上万后可能跑几十秒，`EXPLAIN` 会看到 `DEPENDENT SUBQUERY`。
7. **排名不稳定**。`ORDER BY` 的列有重复值时，`ROW_NUMBER` 的编号顺序在不同执行计划下可能变化，必须追加唯一列做 tie-breaker。
8. **`PARTITION BY` 和 `GROUP BY` 混用要小心**。窗口函数在 `GROUP BY` **之后**计算，所以 `SUM(x) OVER ()` 里的 `x` 已经是聚合后的结果了。

## 面试怎么答

**Q：查出工资第二高的员工，写一条 SQL。**
A：我会先反问一句「并列第一时算不算第二」，明确语义。如果要的是第二档薪水，用 `DENSE_RANK() OVER (ORDER BY salary DESC)` 取 `rk = 2` 最准确；MySQL 5.7 环境用 `SELECT DISTINCT salary FROM employee ORDER BY salary DESC LIMIT 1 OFFSET 1`。要注意的边界是：不存在第二高时，`LIMIT` 写法返回空集，如果要求返回 `NULL`，得在外面套一层标量子查询。

**Q：怎么取每个分组的前 N 条？**
A：8.0 用 `ROW_NUMBER()/DENSE_RANK() OVER (PARTITION BY 组 ORDER BY 排序列 DESC)`，套一层子查询后 `WHERE rn <= N`。必须套子查询是因为窗口函数在 `SELECT` 阶段才计算，`WHERE` 阶段拿不到。5.7 用关联子查询数「比我大的有几个」，但复杂度 O(n²)，大表不可用。

**Q：`RANK`、`DENSE_RANK`、`ROW_NUMBER` 区别？**
A：都是排名函数，区别只在并列处理。`ROW_NUMBER` 强行给唯一序号；`RANK` 并列同号但后续跳号（1,1,3）；`DENSE_RANK` 并列同号且不跳号（1,1,2）。选型看语义：取明细行用 `ROW_NUMBER`，取「第几档」用 `DENSE_RANK`。

**Q：窗口函数和 `GROUP BY` 的区别？**
A：`GROUP BY` 把 N 行折叠成 1 行，明细丢失；窗口函数保留原有行数，只是给每行附加一个基于窗口计算出的值。执行顺序上窗口函数在 `GROUP BY`、`HAVING` 之后、`ORDER BY` 之前。所以要「明细 + 组内统计」同时呈现（比如每行显示自己占部门总额的比例）只能用窗口函数。

## 参考

- [MySQL 8.0 窗口函数](https://dev.mysql.com/doc/refman/8.0/en/window-functions.html)
- [MySQL WITH（CTE）语法](https://dev.mysql.com/doc/refman/8.0/en/with.html)
- [PostgreSQL 窗口函数教程](https://www.postgresql.org/docs/current/tutorial-window.html)
- 相关笔记：[[SQL 聚合函数与 GROUP BY、HAVING]]、[[SQL 子查询与 UNION]]、[[SQL 查询基础：SELECT、WHERE 与 ORDER BY]]
