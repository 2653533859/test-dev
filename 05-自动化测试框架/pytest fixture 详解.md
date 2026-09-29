---
created: 2026-07-31
tags: [自动化测试框架/fixture]
---

# pytest fixture 详解

![[assets/pytest-fixture-scope.svg]]
*图示：四种作用域是套娃关系——session 包 module、module 包 class、class 包 function；依赖方向只能「窄依赖宽」，反过来会报 ScopeMismatch。*

> pytest 最核心的设计。理解 fixture 就理解了 pytest 与 unittest 的本质差距：从「固定的三层前后置」变成「可组合、可依赖、可参数化的依赖注入」。

## 概念

### fixture 解决什么问题

`setUp` / `tearDown` 的模型有三个硬伤：

1. **粒度固定**：只有 function / class / module 三档，且每档只能有一个；
2. **不能按需组合**：一个类里 10 条用例，只有 2 条需要数据库，`setUp` 里建连接会让另外 8 条也白建；
3. **不能传值**：`setUp` 里建的东西只能挂 `self`，用例和前置之间是隐式耦合，看用例签名不知道它依赖什么。

fixture 把这三点全解了：

```python
def test_create_order(db, logged_in_client, temp_sku):
    ...
```

看函数签名就知道这条用例依赖三样东西——**这就是依赖注入（DI）**。pytest 在执行前解析签名里的每个参数名，去找同名 fixture，按依赖关系拓扑排序后依次执行，把返回值注入进来。

### 定义与 yield 前后置

```python
import pytest


@pytest.fixture
def db_conn():
    conn = create_conn()        # setup：yield 之前
    yield conn                  # 把值交给用例
    conn.close()                # teardown：yield 之后
```

`yield` 版本比 `return` 版本多了后置能力。三个要点：

1. `yield` **只能出现一次**（多次 yield 会报错，它不是生成器用例）；
2. 用例执行**失败或异常**时，`yield` 之后的代码**依然会执行**；
3. 如果 `yield` **之前**抛异常，用例记为 Error，`yield` 之后的代码不执行（此时用 `request.addfinalizer` 更安全）。

```python
@pytest.fixture
def safe_resource(request):
    conn = create_conn()
    request.addfinalizer(conn.close)     # 注册即生效，后面炸了也会清理

    user = create_user()
    request.addfinalizer(lambda: delete_user(user.id))

    raise RuntimeError("模拟中途失败")   # 上面两个 finalizer 仍会按 LIFO 执行
    yield user
```

`addfinalizer` 与 `yield` 的关系，等价于 unittest 里 `addCleanup` 与 `tearDown` 的关系。

### 四种作用域

| scope | 创建时机 | 销毁时机 | 典型用途 |
|-------|---------|---------|---------|
| `function`（默认） | 每条用例前 | 每条用例后 | 需要干净状态的测试数据、临时目录 |
| `class` | 每个测试类前 | 类内用例跑完 | 类内共享的业务上下文 |
| `module` | 每个模块前 | 模块内跑完 | 模块级的 driver、mock server |
| `package` | 每个包（目录）前 | 包内跑完 | 目录级共享资源（用得少） |
| `session` | 整次运行前 | 全部跑完 | DB 连接池、登录 token、Docker 容器 |

**硬约束：作用域窄的可以依赖宽的，反过来不行。**

```python
@pytest.fixture(scope="function")
def user(): ...


@pytest.fixture(scope="session")
def pool(user):     # ✗ session 依赖 function
    ...
# ScopeMismatch: You tried to access the function scoped fixture user
# with a session scoped request object
```

原因很直白：session 级 fixture 只创建一次，而 function 级 fixture 每条用例都不一样，session 级的没法决定用哪一个。

选型口诀：

- **建得慢、能安全复用** → session（登录 token、连接池、启动的容器）；
- **一组用例共享上下文** → module / class；
- **要求互不干扰** → function（默认，也是最安全的默认值）。

一条重要经验：**默认写 function，只有当它成为性能瓶颈时才往上提**，并且提之前先确认「用例不会修改它的状态」。

### autouse：自动应用

```python
@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    """不需要用例声明，自动对本 conftest 目录树下所有用例生效。"""
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    yield
```

适合做**横切关注点**：日志分隔线、环境变量重置、每条用例前清缓存。

代价是**隐式**——用例签名里看不到它，新人排查时找不到「这个环境变量是谁设的」。所以两条纪律：

1. `autouse` fixture **命名加下划线前缀**，提示它不是给你显式调用的；
2. **放在尽量小的作用范围**（对应目录的 conftest），不要在根 conftest 里写只有 UI 用例需要的 autouse。

### fixture 间依赖与执行顺序

fixture 可以互相依赖，pytest 会做拓扑排序：

```python
@pytest.fixture(scope="session")
def settings(): ...


@pytest.fixture(scope="session")
def http(settings): ...


@pytest.fixture(scope="session")
def token(http, settings): ...


@pytest.fixture
def client(http, token): ...


def test_x(client): ...
# 执行顺序：settings → http → token → client → test_x
# 销毁顺序相反：client → token → http → settings（LIFO）
```

同一优先级下，实际执行顺序由三个因素决定，优先级从高到低：

1. **scope**：宽的先执行（session 先于 function）；
2. **依赖关系**：被依赖的先执行；
3. **autouse**：同 scope 下 autouse 的先于非 autouse 的。

不要依赖「参数书写顺序」——它不决定执行顺序。

### 参数化 fixture

给 fixture 加 `params`，它会**把依赖它的所有用例复制一份**：

```python
@pytest.fixture(params=["chrome", "firefox", "webkit"])
def browser(request):
    name = request.param            # 通过 request.param 拿当前参数
    drv = launch(name)
    yield drv
    drv.quit()


def test_login(browser):    ...     # 自动变成 3 条用例
def test_search(browser):   ...     # 也变成 3 条
```

这是 `parametrize` 做不到的：`parametrize` 只作用于被装饰的那一个用例，参数化 fixture 作用于**所有引用它的用例**，且带前后置。跨浏览器、跨环境、跨数据库版本的矩阵测试就靠它。

配 `ids` 让报告可读：

```python
@pytest.fixture(params=["chrome", "firefox"], ids=["谷歌浏览器", "火狐浏览器"])
def browser(request): ...
```

### 间接参数化：`indirect=True`

让 `parametrize` 的值先经过 fixture 加工再进用例：

```python
@pytest.fixture
def user(request):
    """request.param 是 parametrize 传进来的原始值。"""
    role = request.param
    u = create_user(role=role)
    yield u
    delete_user(u.id)


@pytest.mark.parametrize("user", ["admin", "guest"], indirect=True)
def test_permission(user):
    # user 已经是创建好的用户对象，不是字符串 "admin"
    assert user.role in ("admin", "guest")
```

用途：参数需要「加工 + 前后置」时。`indirect` 还能只对部分参数生效：

```python
@pytest.mark.parametrize("user, expected_code",
                         [("admin", 200), ("guest", 403)],
                         indirect=["user"])       # 只有 user 走 fixture
def test_access(user, expected_code): ...
```

## 用法

### 工厂型 fixture：一条用例要多个实例

fixture 默认「一次调用一个值」，需要多个时返回**工厂函数**：

```python
@pytest.fixture
def make_user(http):
    """工厂 fixture：可以在一条用例里调多次，且统一清理。"""
    created = []

    def _make(role="guest", **kwargs):
        u = create_user(http, role=role, **kwargs)
        created.append(u)
        return u

    yield _make

    for u in reversed(created):       # 逆序清理
        delete_user(http, u.id)


def test_transfer(make_user):
    payer = make_user(role="vip", balance=100)
    payee = make_user(role="guest", balance=0)
    transfer(payer, payee, 50)
    assert payee.balance == 50
```

工厂模式是测试数据管理的标准解法，比「预置多个 fixture（`user_a`、`user_b`）」灵活得多。

### 通过 `request` 拿到上下文

`request` 是内置 fixture，携带当前用例的全部元信息：

```python
@pytest.fixture
def context(request):
    print(request.node.nodeid)          # tests/test_a.py::test_x[param]
    print(request.node.name)            # test_x[param]
    print(request.fspath)               # 用例文件绝对路径
    print(request.cls)                  # 所在测试类（函数式用例为 None）
    print(request.module.__name__)      # 所在模块
    print(request.config.getoption("--env"))    # 命令行参数
    print(request.node.get_closest_marker("smoke"))   # 该用例的 marker
    yield
```

结合 marker 让 fixture 有条件地改变行为，是很实用的技巧：

```python
@pytest.fixture
def db(request):
    """用例打了 @pytest.mark.no_rollback 就不回滚事务。"""
    conn = create_conn()
    tx = conn.begin()
    yield conn
    if request.node.get_closest_marker("no_rollback"):
        tx.commit()
    else:
        tx.rollback()
```

### 常用内置 fixture

| fixture | 用途 |
|---------|------|
| `tmp_path` | 每条用例一个独立临时目录（`pathlib.Path`） |
| `tmp_path_factory` | session 级临时目录工厂 |
| `monkeypatch` | 临时改环境变量、属性、字典，用例结束自动还原 |
| `capsys` / `capfd` | 捕获 stdout/stderr |
| `caplog` | 捕获日志记录，可断言日志内容 |
| `recwarn` | 捕获 warning |
| `request` | 当前用例的上下文 |
| `pytestconfig` | 等价于 `request.config` |

```python
def test_config_isolation(monkeypatch, tmp_path):
    # 改环境变量，用例结束自动还原，不污染其它用例
    monkeypatch.setenv("TEST_ENV", "uat")
    # 替换对象属性/方法
    monkeypatch.setattr("core.http.HttpClient.timeout", 1)
    # 临时切工作目录
    monkeypatch.chdir(tmp_path)
    assert os.getenv("TEST_ENV") == "uat"


def test_log_content(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        do_something()
    assert "库存不足" in caplog.text
    assert any(r.levelname == "WARNING" for r in caplog.records)
```

`monkeypatch` 是被严重低估的 fixture——凡是「临时改全局状态」的需求都该用它，因为它保证还原，不会出现「A 用例改了环境变量导致 B 用例挂」。

### 复用与覆盖：同名 fixture 的层层特化

```python
# conftest.py
@pytest.fixture
def user():
    return create_user(role="guest")


# tests/admin/conftest.py —— 特化
@pytest.fixture
def user(user):          # 参数名和自己同名：引用的是上层的那个
    """在上层基础上加工，而不是重新写一遍。"""
    user.role = "admin"
    user.save()
    return user
```

「同名 fixture 引用上层同名 fixture」是 pytest 的官方支持写法（override），不会递归。

### 用 `--setup-show` 看真实执行顺序

排查作用域问题最直接的工具：

```bash
pytest tests/api/test_login.py --setup-show
```

```text
SETUP    S settings
SETUP    S http (settings)
SETUP    S token (http, settings)
tests/api/test_login.py::test_ok
    SETUP    F client (http, token)
    tests/api/test_login.py::test_ok (fixtures used: client, http, settings, token)
    TEARDOWN F client
tests/api/test_login.py::test_wrong_pwd
    SETUP    F client (http, token)
    ...
TEARDOWN S token
TEARDOWN S http
TEARDOWN S settings
```

`S` = session、`M` = module、`C` = class、`F` = function，一眼看出谁建了几次。

## 踩坑

1. **session 级 fixture 被用例修改，污染后续用例**。session 级的 `admin_token` 被某条用例的「修改密码」测试搞失效了，后面所有用例 401。表现是「单跑通过、全跑失败」，且失败位置随机。**宽作用域的 fixture 必须是只读的**，任何会修改它的用例都应该自己造独立数据。

2. **`ScopeMismatch` 报错**。session 级 fixture 依赖了 function 级的。常见于「想在 session 级 fixture 里用 `tmp_path`」——`tmp_path` 是 function 级的，要用 `tmp_path_factory`。

3. **yield 之前抛异常导致资源泄漏**。fixture 里建了连接又建用户，建用户失败，`yield` 后面的清理代码不执行。改用 `request.addfinalizer` 逐个注册。

4. **`autouse` 放在根 conftest，影响面过大**。根 conftest 里写了 autouse 的浏览器启动，纯接口用例也被拖着起浏览器，全量执行时间翻倍。autouse 的作用范围就是它所在 conftest 的目录树，放置位置必须精确。

5. **fixture 名和用例参数名冲突**。`@pytest.mark.parametrize("client", [...])` 而恰好有个 fixture 也叫 `client`——参数会覆盖 fixture，且不报错，行为完全变了。命名上给 fixture 加领域前缀（`api_client` 而不是 `client`）能避免大部分冲突。

6. **在 fixture 里写断言**。fixture 里 `assert resp.status_code == 200` 失败时，用例被记为 **Error** 而不是 **Failed**，Allure 报告里归类到「错误」而不是「失败」，统计口径会乱。前置的校验建议用 `pytest.fail("前置数据准备失败: ...")` 或抛自定义异常，语义更清晰。

7. **fixture 里 `return` 后写清理代码**。`return conn` 之后的代码永远不执行，清理静默失效。必须用 `yield`。这个错误 IDE 也不会警告。

8. **参数化 fixture 让用例数悄悄爆炸**。`browser` fixture 加了 3 个 params，所有引用它的 200 条用例变成 600 条，CI 时长翻三倍。参数化 fixture 影响面很大，加之前先 `pytest --co -q | tail -1` 看看用例总数。

9. **`indirect=True` 忘了写，参数原样传进用例**。`test_permission(user)` 拿到的是字符串 `"admin"` 而不是用户对象，后续 `user.role` 报 `AttributeError: 'str' object has no attribute 'role'`。

10. **并行执行时 session fixture 被执行 N 次**。`pytest -n 4` 下每个 worker 是独立进程，session 级 fixture 每个进程各建一次。如果它做的是「初始化数据库表」这类幂等性差的操作，会互相冲突。解法见 [[pytest-xdist 并行执行]] 里的文件锁方案。

## 面试怎么答

**Q：fixture 和 setUp/tearDown 有什么区别？**

A（30 秒骨架）：三点本质差异。第一是**粒度与组合**——`setUp` 是「类里所有用例都执行」，fixture 是「哪条用例声明了才执行」，10 条用例里只有 2 条要数据库，另外 8 条不会白建连接。第二是**依赖注入**——用例签名里写了什么 fixture 就依赖什么，显式可读，而 `setUp` 只能挂 `self`，是隐式耦合。第三是**可组合、可依赖、可参数化**——fixture 之间能互相依赖，pytest 做拓扑排序；能指定四种作用域；能用 `params` 让所有引用它的用例自动矩阵化。此外 fixture 是跨文件复用的（放 conftest.py），`setUp` 只能靠继承基类复用。

**追问 1：四种作用域怎么选？**

A：默认用 function，保证用例互相独立。当某个资源「建得慢」且「用例不会修改它」时才往上提：登录 token、数据库连接池、启动的 Docker 容器提到 session；浏览器实例、mock server 视情况提到 module 或 class。约束是窄作用域可以依赖宽的，反过来会报 ScopeMismatch——因为 session 级只建一次，没法决定用哪个 function 级实例。我的经验教训是：宽作用域的 fixture 必须当只读用，一旦某条用例改了它的状态，就会出现「单跑通过、全跑随机失败」这种最难查的问题。

**追问 2：`yield` 和 `addfinalizer` 有什么区别？**

A：`yield` 写起来直观，setup 在前、teardown 在后，绝大多数场景够用。但它有个缺陷：如果 `yield` **之前**抛了异常，后面的清理代码不会执行，前半段建的资源就泄漏了。`addfinalizer` 是注册即生效，按 LIFO 逆序执行，无论后续是否异常都会清理。所以一个 fixture 里要建多个资源时，我用 `addfinalizer` 逐个注册。这个关系和 unittest 里 `tearDown` 与 `addCleanup` 的关系完全一样。

**追问 3：参数化 fixture 和 `parametrize` 的区别？**

A：作用范围不同。`@pytest.mark.parametrize` 只作用于被装饰的那一条用例；参数化 fixture（`@pytest.fixture(params=[...])`）会让**所有引用它的用例**都复制一份，而且带前后置。所以跨浏览器、跨环境、跨数据库版本这种矩阵测试用参数化 fixture，单条用例的数据驱动用 parametrize。还有个中间形态是 `indirect=True`——用 parametrize 传值，但让值先经过 fixture 加工并带上前后置，适合「参数需要创建真实资源」的场景。

**追问 4：怎么排查 fixture 相关的问题？**

A：三个命令。`pytest --fixtures` 列出所有可用 fixture 和它们的来源文件；`pytest --fixtures-per-test <文件>` 看每条用例实际用到哪些、来自哪一行，专治「同名 fixture 覆盖」；`pytest --setup-show` 打印真实的 SETUP/TEARDOWN 顺序并标出作用域字母（S/M/C/F），专治「作用域搞错导致重复初始化」。加上 `-p no:randomly` 排除插件干扰，基本能定位所有 fixture 问题。

## 参考

- [pytest 官方：fixtures 参考](https://docs.pytest.org/en/stable/reference/fixtures.html)
- [pytest 官方：How to use fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html)
- 相关笔记：[[conftest.py 查找规则与作用域]]、[[pytest 参数化 parametrize]]、[[pytest-xdist 并行执行]]、[[unittest 框架详解]]
