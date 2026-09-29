---
created: 2026-07-31
tags: [数据库/SQL]
---

# MySQL 建表与字段类型选择

> 字段类型选错，索引效率、存储成本、边界 bug 全都跟着来。测试同学看懂建表语句，就能提前设计出一批边界值用例。

## 概念

### 类型选择的三条原则

1. **够用就好（smaller is better）**。类型越小，一个数据页能塞的行越多，B+ 树越矮，扫描的页数越少。索引列尤其如此——二级索引的叶子节点还要带一份主键，主键类型越大，所有二级索引都跟着变胖。
2. **简单优于复杂**。整型比较比字符串快（不涉及字符集和排序规则），能用 `INT` 存的枚举就别用 `VARCHAR`；IP 可以用 `INT UNSIGNED` + `INET_ATON()` 存。
3. **尽量 `NOT NULL`**。`NULL` 列需要额外的 NULL 标志位、让索引统计和优化器判断变复杂、参与比较时产生三值逻辑陷阱。用 `0`、`''`、`'1970-01-01'` 之类的默认值代替。

### 整数类型的取值范围

| 类型 | 字节 | 有符号范围 | 无符号范围 | 典型用途 |
|------|------|-----------|-----------|---------|
| `TINYINT` | 1 | -128 ~ 127 | 0 ~ 255 | 状态、开关、年龄 |
| `SMALLINT` | 2 | -32768 ~ 32767 | 0 ~ 65535 | 小计数 |
| `MEDIUMINT` | 3 | ±838 万 | 0 ~ 1677 万 | 少用 |
| `INT` | 4 | ±21 亿 | 0 ~ 42 亿 | 普通主键、计数 |
| `BIGINT` | 8 | ±922 京 | 极大 | 大表主键、金额（分）、时间戳（毫秒） |

**`INT(11)` 里的 11 不是长度**！它只是 `ZEROFILL` 时的显示宽度，跟存储范围毫无关系，`INT(1)` 一样能存 21 亿。MySQL 8.0.17 起已废弃这个语法。

### 字符串类型

| 类型 | 存储 | 特点 |
|------|------|------|
| `CHAR(n)` | 定长 n 字符，不足补空格 | 定长数据（MD5、手机号、性别）快，但**尾部空格会被去掉** |
| `VARCHAR(n)` | 变长，额外 1~2 字节存长度 | 通用首选 |
| `TEXT` / `LONGTEXT` | 变长，超长内容单独存储 | **不能有默认值、索引必须指定前缀长度**，不建议放主表 |

`VARCHAR(n)` 的 `n` 是**字符数**不是字节数。`utf8mb4` 下一个字符最多 4 字节，所以 `VARCHAR(255)` 最多占 1020 字节。InnoDB 单行长度上限约 65535 字节，字段太多太长会报 `Row size too large`。

### 时间类型

| 类型 | 字节 | 范围 | 时区 |
|------|------|------|------|
| `DATETIME` | 5~8 | 1000-01-01 ~ 9999-12-31 | **不做时区转换**，存什么读什么 |
| `TIMESTAMP` | 4~7 | 1970-01-01 ~ **2038-01-19** | 按连接时区转换存取 |
| `DATE` | 3 | 只有日期 | — |
| `BIGINT` 存毫秒戳 | 8 | 无限制 | 应用层解释 |

**2038 问题**：`TIMESTAMP` 底层是 32 位秒级时间戳，2038 年 1 月 19 日会溢出。做「远期有效期」测试时，用 `TIMESTAMP` 存 2040 年会直接报错——这是一个很好的边界用例。

### 金额：永远不要用 FLOAT / DOUBLE

```sql
CREATE TABLE t (a FLOAT, b DECIMAL(10, 2));
INSERT INTO t VALUES (0.1 + 0.2, 0.1 + 0.2);
SELECT a = 0.3, b = 0.3 FROM t;    -- a: 0（不相等！） b: 1
```

`FLOAT`/`DOUBLE` 是二进制浮点，无法精确表示十进制小数。金额用 **`DECIMAL(M, D)`**（定点数，按十进制精确存储）或**用 `BIGINT` 存「分」**。

## 用法

一张遵循规范的建表语句：

```sql
CREATE TABLE `order_info` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `order_no`    CHAR(32)        NOT NULL                COMMENT '订单号，定长32位',
  `user_id`     BIGINT UNSIGNED NOT NULL                COMMENT '用户ID',
  `amount`      DECIMAL(12, 2)  NOT NULL DEFAULT 0.00   COMMENT '金额，元',
  `status`      TINYINT UNSIGNED NOT NULL DEFAULT 0     COMMENT '0待付 1已付 2已退 3取消',
  `remark`      VARCHAR(255)    NOT NULL DEFAULT ''     COMMENT '备注，避免 NULL',
  `ext`         JSON                     DEFAULT NULL   COMMENT '扩展字段',
  `is_deleted`  TINYINT UNSIGNED NOT NULL DEFAULT 0     COMMENT '逻辑删除',
  `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_order_no` (`order_no`),
  KEY `idx_user_status_created` (`user_id`, `status`, `created_at`)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci
  COMMENT = '订单主表';
```

逐条解释设计意图：

- **`BIGINT UNSIGNED AUTO_INCREMENT` 主键**：自增保证顺序写入，避免 B+ 树页分裂（详见 [[MySQL 聚簇索引与二级索引回表]]）；`UNSIGNED` 让正数范围翻倍。
- **`order_no` 用 `CHAR(32)`**：定长，不浪费长度字节，比较快。业务唯一键加 `UNIQUE`，让数据库兜底防重。
- **`status` 用 `TINYINT` 而不是 `VARCHAR`**：省空间、比较快，含义写在 `COMMENT` 里。
- **`remark NOT NULL DEFAULT ''`**：避免 `NULL` 引发的三值逻辑坑。
- **`updated_at ON UPDATE CURRENT_TIMESTAMP`**：数据库自动维护更新时间，测试变更类接口时可以直接断言这个字段有没有变。
- **`utf8mb4`**：`utf8` 是 MySQL 的历史遗留，只支持 3 字节，**存不了 emoji 和部分生僻字**（报 `Incorrect string value: '\xF0\x9F...'`）。永远用 `utf8mb4`。

### 常用 DDL 操作

```sql
-- 查看建表语句：拿到别人的库先看这个
SHOW CREATE TABLE order_info;
DESC order_info;                      -- 简版字段列表

-- 加字段（MySQL 8.0 的 INSTANT DDL 对末尾加列几乎瞬间完成）
ALTER TABLE order_info ADD COLUMN `channel` VARCHAR(16) NOT NULL DEFAULT '' COMMENT '渠道';

-- 改类型 / 改名
ALTER TABLE order_info MODIFY COLUMN `remark` VARCHAR(512) NOT NULL DEFAULT '';
ALTER TABLE order_info CHANGE COLUMN `remark` `note` VARCHAR(512) NOT NULL DEFAULT '';

-- 加索引
ALTER TABLE order_info ADD KEY `idx_created` (`created_at`);
ALTER TABLE order_info DROP INDEX `idx_created`;

-- 复制表结构（含索引），造数用
CREATE TABLE order_info_bak LIKE order_info;
INSERT INTO order_info_bak SELECT * FROM order_info WHERE created_at < '2026-01-01';
```

> `CREATE TABLE b AS SELECT * FROM a` 只复制数据和列定义，**不复制主键、索引、自增、默认值**。要完整结构必须用 `CREATE TABLE b LIKE a`。

### 从建表语句能设计出哪些用例

看到上面这张表，测试用例立刻可以铺开：

```text
order_no  CHAR(32) NOT NULL UNIQUE
  → 传 33 位是否报错 / 传空串 / 重复下单是否被唯一键拦住 / 大小写是否算重复（ci 排序规则下算）
amount    DECIMAL(12,2)
  → 0.001（第三位小数是否四舍五入或报错）/ 负数 / 9999999999.99 上限 / 超上限溢出
status    TINYINT UNSIGNED
  → 传 256 / 传 -1 / 传未定义的枚举值 4
remark    VARCHAR(255) utf8mb4
  → 255 个中文（字符数不是字节数）/ emoji / 前后空格是否被 trim
created_at DATETIME
  → 2038-01-20（如果是 TIMESTAMP 会溢出）/ 闰秒 / 跨时区
```

## 踩坑

1. **用 `utf8` 存 emoji 报错**。`Incorrect string value: '\xF0\x9F\x98\x80'`。MySQL 的 `utf8` 实为 `utf8mb3`，最多 3 字节。**建库建表建连接三处都要设 `utf8mb4`**，少设一处照样乱码。
2. **金额用 `FLOAT` 导致对账差几分钱**。经典的浮点精度问题，且这类 bug 在小数据量下不复现，上量才暴露。
3. **`VARCHAR` 长度按字节算错**。`VARCHAR(10)` 能存 10 个中文，不是 3 个。但索引前缀长度 `KEY idx(col(10))` 里的 10 在不同上下文可能指字节，注意区分。
4. **`CHAR` 尾部空格被吃掉**。`CHAR(10)` 存 `'abc   '` 读出来是 `'abc'`，做「空格保留」的断言会失败。`VARCHAR` 则保留。
5. **`TIMESTAMP` 的 2038 上限与时区漂移**。跨时区部署时，`TIMESTAMP` 会按 `time_zone` 变量转换，同一条数据在两个连接里读出的时间不同；`DATETIME` 不转换。**建议统一用 `DATETIME` + 应用层处理时区**。
6. **`ENUM` 类型看着优雅实则坑多**。底层存的是序号，`ORDER BY` 按序号而非字面值排序；新增枚举值要 `ALTER TABLE` 锁表；`WHERE status = 1` 和 `= '1'` 语义还不一样。用 `TINYINT` + 常量类替代。
7. **大表 `ALTER TABLE` 锁表**。MySQL 5.6+ 支持 Online DDL，但改类型、加全文索引等操作仍需重建表并锁写。生产环境用 `pt-online-schema-change` / `gh-ost`。测试环境改大表结构前先看数据量。
8. **默认值和 `NOT NULL` 不一致导致插入失败**。`NOT NULL` 又没默认值的列，`INSERT` 时不给值会报 `Field 'x' doesn't have a default value`（严格模式下）。
9. **主键用 UUID 字符串**。随机值导致 B+ 树频繁页分裂、写入慢、索引体积大（36 字节 vs 8 字节，还会拖胖所有二级索引）。要用有序 ID 就用雪花算法或 `UUID_TO_BIN(UUID(), 1)` 的交换字节序形式。
10. **忘写 `COMMENT`**。测试同学接手一张几十列的表，没注释只能靠猜，这是效率杀手。

## 面试怎么答

**Q：`CHAR` 和 `VARCHAR` 怎么选？**
A：`CHAR` 是定长，`VARCHAR` 是变长且需要额外 1~2 字节记录长度。长度固定或接近固定的数据用 `CHAR`——比如 MD5、UUID、手机号、身份证，定长没有碎片、更新时不用挪行、比较也稍快。长度差异大的用 `VARCHAR`，避免空间浪费。一个容易被追问的点是 `CHAR` 会**去掉尾部空格**，如果业务上空格有意义就必须用 `VARCHAR`。

**Q：`DATETIME` 和 `TIMESTAMP` 怎么选？**
A：`TIMESTAMP` 占 4 字节、带时区转换、上限是 2038 年；`DATETIME` 占 5~8 字节、不做时区转换、上限 9999 年。跨时区业务如果希望「所有人看到自己本地时间」可以用 `TIMESTAMP`，但要面对 2038 问题；一般推荐用 `DATETIME` 统一存 UTC 时间，时区由应用层处理，更可控。测试时 2038-01-19 是一个必测的边界值。

**Q：为什么金额不能用 `FLOAT`？**
A：`FLOAT`/`DOUBLE` 是 IEEE 754 二进制浮点数，十进制小数如 0.1 在二进制里是无限循环，只能近似存储，累加后会产生误差，`WHERE amount = 0.3` 可能查不出来，对账会差分。应该用 `DECIMAL(M, D)`——它按十进制精确存储，本质是变长的字符串式定点数；或者用 `BIGINT` 存最小货币单位（分），运算全在整数域。

**Q：`INT(11)` 的 11 是什么意思？**
A：是**显示宽度**，只在配合 `ZEROFILL` 时用于左侧补零，和能存多大的数完全无关——`INT` 无论括号里写几，都是 4 字节、范围 ±21 亿。这是一个非常常见的误解，MySQL 8.0.17 已经把这个语法标记为废弃。

**Q：看到建表语句你能设计哪些测试用例？**
A：字段类型天然定义了边界。整型看上下界和溢出；`VARCHAR(n)` 看 n、n+1 个字符以及中文和 emoji 的字节数差异；`DECIMAL(12,2)` 看小数位截断和整数位上限；`NOT NULL` 看不传值；`UNIQUE` 看重复插入以及大小写敏感性（取决于 collation）；时间字段看 2038 边界和时区。另外从索引定义还能反推查询性能相关的用例，从 `ON UPDATE CURRENT_TIMESTAMP` 能推出「更新接口是否刷新了 updated_at」这类断言点。

## 参考

- [MySQL 8.0 数据类型](https://dev.mysql.com/doc/refman/8.0/en/data-types.html)
- [MySQL 8.0 CREATE TABLE](https://dev.mysql.com/doc/refman/8.0/en/create-table.html)
- [PostgreSQL 数据类型](https://www.postgresql.org/docs/current/datatype.html)
- 相关笔记：[[SQL 数据变更：INSERT、UPDATE 与 DELETE]]、[[MySQL B+ 树索引结构与查找]]、[[数据库测试数据构造与清理策略]]
