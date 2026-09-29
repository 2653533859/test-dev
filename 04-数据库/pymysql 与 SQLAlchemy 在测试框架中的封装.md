---
created: 2026-07-31
tags: [数据库/测试相关]
---

# pymysql 与 SQLAlchemy 在测试框架中的封装

## 概念

测开操作数据库通常有两层选择：

- **pymysql**：纯 Python 的 MySQL 驱动，最贴近原生 SQL，适合简单直插、执行任意 SQL、读 `EXPLAIN` 等。
- **SQLAlchemy**：ORM + Core 双模式。ORM 把表映射成 Python 对象，Core 提供跨库统一的 SQL 表达。适合业务代码强 ORM 的项目做对齐，或需要**跨数据库**（MySQL/PostgreSQL 切换）的测试。

在测试框架里，关键是**封装成可复用的数据工具**，而不是在每个用例里重复写连接、提交、关闭。封装目标：连接可配置、自动关连接、事务可回滚、失败有清晰报错。

## 用法

### 封装一个最小 pymysql 工具

```python
import pymysql
from contextlib import contextmanager

class DBHelper:
    def __init__(self, cfg):
        self.cfg = cfg

    @contextmanager
    def conn(self):
        c = pymysql.connect(
            host=self.cfg['host'], user=self.cfg['user'],
            password=self.cfg['password'], db=self.cfg['db'],
            autocommit=False, charset='utf8mb4')
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def query(self, sql, args=None):
        with self.conn() as c:
            cur = c.cursor(pymysql.cursors.DictCursor)  # 返回 dict，断言更友好
            cur.execute(sql, args)
            return cur.fetchall()

    def execute(self, sql, args=None):
        with self.conn() as c:
            cur = c.cursor()
            cur.execute(sql, args)
            return cur.rowcount
```

用例里用：

```python
db = DBHelper(TEST_DB_CFG)
rows = db.query("SELECT status FROM orders WHERE user_id=%s", (1001,))
assert rows[0]['status'] == 1
```

### SQLAlchemy Core 做跨库兼容的校验

```python
from sqlalchemy import create_engine, text

engine = create_engine("mysql+pymysql://tester:x@testdb/shop")
with engine.connect() as con:
    res = con.execute(text("SELECT COUNT(*) AS c FROM orders WHERE status=:s"),
                      {"s": 1})
    assert res.fetchone()["c"] >= 1
```

### 用例级数据隔离：事务回滚

```python
import pytest

@pytest.fixture
def db_tx():
    eng = create_engine("mysql+pymysql://tester:x@testdb/shop")
    conn = eng.connect()
    tx = conn.begin()           # 开事务
    yield conn                  # 用例执行
    tx.rollback()               # 收尾整体回滚，不留数据
    conn.close()
```

## 踩坑

1. **忘记 `commit` 导致数据「没插进去」**：pymysql 默认 `autocommit=False`，不 `commit` 事务里看不到。封装时统一在 `with` 退出时 `commit`，异常 `rollback`。
2. **连接不关闭导致连接池耗尽**：每次测试 `connect` 不 `close`，跑一阵子就 `Too many connections`。务必用 `try/finally` 或 `contextmanager` 保证关闭。
3. **SQL 拼字符串引发注入与报错**：`f"WHERE id={uid}"` 既不安全也易因特殊字符报错。一律用参数化 `%s` / `:name`，驱动负责转义。
4. **`DictCursor` 忘了设，断言取字段名失败**：默认 `tuple` 结果只能按下标取，可读性差且易错位。读校验用 `DictCursor` 按列名取。
5. **测试用真实库而非独立测试库**：用例污染共享库、还可能误删他人数据。配置文件隔离测试库地址，禁止直连生产/开发库。
6. **事务隔离级别影响读到的数据**：框架开了 RR，用例内造数后同事务能读到、跨事务才按隔离级别可见。并发断言要分清「自己事务内」还是「跨连接」。
7. **SQLAlchemy 默认 `autocommit` 行为变化**：1.x 与 2.0 风格（`engine.connect()` 需显式 `begin`）有差异，升级后旧代码可能不提交。统一用 `with engine.begin() as con` 最稳妥。
8. **长连接被服务端超时断开**：MySQL `wait_timeout` 默认 8 小时，闲置连接再执行会 `MySQL server has gone away`。连接池加 `pool_recycle` 或每次用例新建连接。
9. **ORM 对象状态与数据库不同步**：改了 `obj.status=2` 但没 `session.commit()`，断言数据库查不到。ORM 操作必须 `flush`/`commit` 才落库。

## 面试怎么答

**Q：你为什么用 pymysql 而不是 ORM？**
A：造测试数据、执行 `EXPLAIN`、做库级校验时，原生 SQL 最直接可控，pymysql 足够；但如果被测系统是强 ORM 项目、且需要跨库兼容，我会用 SQLAlchemy Core 写统一查询。选型看场景，不迷信 ORM。

**Q：怎么保证自动化用例不污染数据库？**
A：核心是封装 + 隔离。连接/提交/关闭统一封装避免泄漏；数据隔离用「事务回滚」或「标记字段 + 精准 DELETE」；测试库与生产库物理隔离，配置里写死测试库。

**Q：参数化查询除了防注入还有什么好处？**
A：驱动会正确处理类型转义和特殊字符（引号、NULL、`\`），避免手写 SQL 因数据内容报错；同时让 SQL 模板可缓存、可读性好，断言和复用都更方便。

## 参考

- [pymysql 官方文档](https://pymysql.readthedocs.io/en/latest/)
- [SQLAlchemy 2.0 官方文档](https://docs.sqlalchemy.org/en/20/)
- [PEP 249 —— Python DB-API 2.0 规范](https://peps.python.org/pep-0249/)
- [[数据库测试数据构造与清理策略]] —— 造数清数的策略与本工具的结合
- [[MySQL 事务与 ACID]] —— 事务回滚做用例隔离的原理
- [[SQL 数据变更：INSERT、UPDATE 与 DELETE]] —— 底层 DML 语句
