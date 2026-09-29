---
created: 2026-07-31
tags: [面试题/安全测试]
---

# SQL 注入的原理与防御

> 核心是「数据被当成了代码」。答清楚参数化查询为什么有效、转义为什么不够，这题就满分了。

**范围声明**：本笔记的验证方法只在自己有权限的测试环境与靶场（DVWA、Juice Shop）中使用，不针对任何未授权目标。

## 30 秒回答骨架

**原理**：应用把用户输入直接拼接进 SQL 字符串，导致输入里的引号、注释符改变了 SQL 的语法结构，**数据越界成了代码**。

**根因一句话**：违反了「代码与数据分离」原则。

**防御按优先级**：

1. **参数化查询（预编译）——首选**。SQL 模板先送数据库编译好执行计划，参数以「值」的形式单独传输，无论内容是什么都不会再参与语法解析。
2. **表名/列名/ORDER BY 方向无法参数化的部分用白名单**，映射到固定的合法值，不要拼用户输入。
3. **最小权限**：应用账号不给 `DROP`/`FILE`/`GRANT`，读写分离，Web 账号不能访问系统库。
4. **纵深防御**：WAF、输入校验、错误信息不外抛（避免报错注入）、SAST/SCA 接入 CI。

**转义为什么不够**：转义依赖「用对函数 + 每一处都不遗漏 + 字符集匹配」，任何一处疏漏就破防；而且数字型注入场景根本没有引号可转义（`WHERE id = $input`，输入 `1 OR 1=1` 无需引号）。宽字节注入（GBK 下 `%df%27` 吃掉转义反斜杠）也能绕过转义。

## 展开

### 拼接是怎么破的

```python
# 有漏洞的写法
sql = f"SELECT * FROM t_user WHERE name = '{name}' AND pwd = '{pwd}'"
```

输入 `name = admin' -- `，拼出来变成：

```sql
SELECT * FROM t_user WHERE name = 'admin' -- ' AND pwd = ''
```

`--` 之后被当注释丢弃，密码校验整段消失。输入 `' OR '1'='1` 则让 WHERE 恒真。

数据库拿到的是**一整个字符串**，它没有任何办法知道哪一段是开发者写的、哪一段是用户输入的——这就是问题的本质。

### 参数化查询为什么有效

```python
# 正确写法（pymysql）
cursor.execute(
    "SELECT * FROM t_user WHERE name = %s AND pwd = %s",
    (name, pwd),      # 参数以元组单独传，不是拼进字符串
)
```

关键在于**执行流程被拆成了两步**：

1. **Prepare**：把 `SELECT * FROM t_user WHERE name = ? AND pwd = ?` 送给数据库，此时就完成了词法/语法解析和执行计划生成。**SQL 的结构在这一刻已经定死了。**
2. **Execute**：参数值通过二进制协议单独发送，数据库直接把它当作 `name` 列的一个比较值填进去，**不会再走一遍语法解析**。

所以哪怕参数值是 `' OR '1'='1`，它也只是一个字符串字面量，等价于在库里找一个名字真的叫 `' OR '1'='1` 的用户——找不到，返回空。

**这就是「代码与数据分离」的具体实现**：结构在 prepare 阶段确定，数据在 execute 阶段填充，两者物理隔离。

一个必须区分清楚的坑：

```python
# 这不是参数化！只是用 % 做了字符串格式化，等价于拼接
cursor.execute("SELECT * FROM t_user WHERE name = '%s'" % name)   # 危险
# 这才是参数化：把参数交给驱动，逗号不是百分号
cursor.execute("SELECT * FROM t_user WHERE name = %s", (name,))    # 安全
```

**面试官很喜欢拿这两行代码让你辨认**，区别只在一个逗号。

### 参数化覆盖不到的地方

参数化只能替换**值**，不能替换 SQL 的结构元素：

```python
# 报错，表名不能参数化
cursor.execute("SELECT * FROM %s WHERE id = %s", (table, uid))
```

排序字段、排序方向、表名、列名这类必须用白名单：

```python
ALLOWED_SORT = {"create_time", "pay_amount", "order_id"}
ALLOWED_ORDER = {"ASC", "DESC"}

def build_sql(sort_by: str, order: str) -> str:
    if sort_by not in ALLOWED_SORT:
        raise ValueError(f"非法排序字段: {sort_by}")
    if order.upper() not in ALLOWED_ORDER:
        raise ValueError(f"非法排序方向: {order}")
    return f"SELECT * FROM t_order ORDER BY {sort_by} {order.upper()}"
```

注意是**白名单（枚举合法值）而不是黑名单（过滤危险字符）**。黑名单永远列不全，大小写混写、编码变形、注释分割（`UN/**/ION`）都能绕。

### ORM 也会注入

用了 ORM 不等于安全，只要有裸 SQL 或字符串拼接的入口就有风险：

```python
# SQLAlchemy 危险写法
session.execute(f"SELECT * FROM t_user WHERE id = {uid}")
# 安全写法
session.execute(text("SELECT * FROM t_user WHERE id = :uid"), {"uid": uid})

# MyBatis 的经典区别
# ${}  直接字符串替换 → 有注入风险
# #{}  预编译占位符   → 安全
```

**MyBatis 的 `${}` 和 `#{}`** 是 Java 岗高频追问点，值得单独记住。

### 测试时怎么验证（仅限授权环境）

按类型分四种，测试时优先用无损的判断方式：

| 类型 | 判断依据 | 无损探测 payload |
|------|---------|-----------------|
| 报错注入 | 页面回显数据库错误 | 单引号 `'` 看是否报 SQL 语法错误 |
| 联合查询注入 | 有数据回显 | `' ORDER BY 99 -- ` 看是否报列数越界 |
| 布尔盲注 | 页面有真/假两种状态 | `' AND 1=1 -- ` 与 `' AND 1=2 -- ` 结果不同 |
| 时间盲注 | 无任何回显 | `' AND SLEEP(3) -- ` 响应时间明显变长 |

**优先用布尔法而不是 `SLEEP`**：`SLEEP` 会占住数据库连接，在共享测试环境上并发探测可能把连接池打满，影响别人。

自动化用例里可以把这些 payload 做成数据驱动的安全冒烟：

```python
INJECTION_PAYLOADS = [
    "' OR '1'='1",
    "1' AND 1=1 -- ",
    "1' AND 1=2 -- ",
    "'; SELECT 1 -- ",
    "1 UNION SELECT NULL,NULL -- ",
]

@pytest.mark.security
@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_search_no_sql_injection(api_client, payload):
    r = api_client.get("/goods/search", params={"kw": payload})
    # 1. 不能 500（说明 SQL 报错了）
    assert r.status_code != 500, f"payload 触发服务端异常: {payload}"
    # 2. 响应里不能出现数据库错误特征
    body = r.text.lower()
    for kw in ("sql syntax", "mysql", "sqlstate", "ora-0", "unclosed quotation"):
        assert kw not in body, f"响应泄露数据库信息: {kw}"
    # 3. 恒真条件不能返回全量数据
    if payload == "' OR '1'='1":
        assert r.json()["data"]["total"] < TOTAL_GOODS
```

## 可能被追问的点

- **预编译在 MySQL 里是真的服务端预编译吗？** 不一定。MySQL 驱动有客户端预编译（驱动本地做转义后拼接发送）和服务端预编译（`useServerPrepStmts=true`，走 `COM_STMT_PREPARE` 协议）两种。**客户端预编译如果实现正确同样安全**，但服务端预编译更彻底，且能复用执行计划。
- **宽字节注入是什么？** 数据库字符集为 GBK 时，转义函数把 `'` 变成 `\'`，攻击者传入 `%df'`，GBK 把 `%df%5c`（`\`）解析成一个汉字「運」，反斜杠被"吃掉"，单引号逃逸成功。防御：字符集统一用 UTF-8/utf8mb4，并使用参数化而非转义。
- **二次注入（Second Order）是什么？** 恶意数据在插入时被正确转义存进了库，但后续某处从库里读出来后又拼进了新的 SQL，此时不再有转义，注入成立。**这说明「只在入口做防护」不够，每一次拼 SQL 都必须参数化。**
- **存储过程安全吗？** 存储过程内部如果用了动态 SQL（`PREPARE`/`EXECUTE IMMEDIATE` 拼字符串），照样能注入。
- **为什么 WAF 不能作为唯一防线？** WAF 是基于规则的黑名单，存在绕过手法（编码变形、注释分割、大小写、超长参数、分块传输），且对业务逻辑无感知。它是**减缓层**不是**修复层**。
- **和其他注入的关系？** 命令注入、LDAP 注入、XPath 注入、模板注入、NoSQL 注入的根因完全一样——都是拼接导致数据越界成代码，防御思路也一样：参数化 / 白名单 / 最小权限。回答时能横向串起来会很加分。

## 结合自己项目的例子

商城中台的商户后台有一个「订单导出」功能，支持按多个条件筛选并自定义排序字段。我在做安全冒烟时把它扫出来了。

**发现过程**：我把上面那套注入 payload 做成参数化用例，挂在 `@pytest.mark.security` 上跑全量接口。导出接口在 `sort_by=create_time'` 这个输入下返回了 500，响应体里带着 `You have an error in your SQL syntax`——**报错信息直接把 SQL 片段吐出来了**。

**确认与评估**：在测试环境用布尔法确认（没用 `SLEEP`，因为那台库是共享的）：`sort_by=create_time` 与 `sort_by=(CASE WHEN 1=1 THEN create_time ELSE pay_amount END)` 返回的排序结果不同，说明表达式真的被数据库执行了，可控。

翻代码看到根因：其他条件都规规矩矩用了 MyBatis 的 `#{}`，唯独排序这一段用了 `${}`：

```xml
<!-- 有问题的写法 -->
ORDER BY ${sortBy} ${order}
```

因为 `ORDER BY` 后面确实不能用 `#{}`（会被当成字符串常量，排序失效），开发就图省事直接用了 `${}`。**这正好印证了「参数化覆盖不到结构元素」这个知识点。**

**推动修复**：我在缺陷单里给了具体方案而不只是"存在 SQL 注入"，这点很重要——

1. Java 侧加白名单枚举：`SortField` 枚举类，只允许 6 个字段，非法值抛业务异常。
2. `order` 方向映射成枚举 `ASC`/`DESC`，不接受任意字符串。
3. 全局异常处理器兜底：生产环境不返回原始异常栈，统一返回 `系统繁忙`，异常详情只进日志。

**固化到流程**：修完之后我做了三件事，让同类问题不再复发。

- 用 Grep 在整个后端仓库搜 `${`，一共找出 14 处，逐个评估，其中 3 处确实有风险，一并修掉。
- 把这条检查加进 CI：SonarQube 打开 SQL 注入相关规则，`${}` 用法在代码评审模板里列为必查项。
- 那套安全冒烟用例从「我手动跑」变成了流水线里的一个 stage，每晚随接口回归一起跑，覆盖了 46 个对外接口。

上线后这个漏洞被安全团队的年度渗透测试列为「测试团队自主发现并闭环」的案例。我讲这个例子时会特意点出两点：**一是能自己写用例去主动扫而不是等安全团队兜底；二是修复方案是我给的，说明我理解的不只是「怎么攻」，还有「为什么这样防」。**

## 参考

- 相关笔记：[[10-安全测试]]、[[06-接口自动化测试]]、[[04-数据库]]
