---
created: 2026-07-31
tags: [面试题/自动化测试框架]
---

# fixture 与 setUp 的区别及四种作用域

> pytest 面试第一题。答出「依赖注入 + 作用域 + yield 前后置」三个词，深度就够了。

## 30 秒回答骨架

`setUp` 是 unittest 的**类内前置钩子**，fixture 是 pytest 的**可复用依赖注入机制**。四点区别：

1. **粒度**：`setUp` 只有类级和方法级两档；fixture 有 `function` / `class` / `module` / `session` 四种作用域，还能自定义。
2. **复用范围**：`setUp` 绑死在 TestCase 类里，跨类复用只能靠继承；fixture 放进 `conftest.py` 后，整个目录树的用例都能用，且**按需取用**。
3. **按需注入**：用例声明哪个 fixture 就只初始化哪个，不需要的不会跑；`setUp` 是「这个类里所有用例无差别执行」。
4. **前后置一体**：fixture 用 `yield` 把前置和后置写在同一个函数里，共享局部变量，不用像 `setUp`/`tearDown` 那样靠 `self.xxx` 传递。

再加一句：fixture 之间可以互相依赖、可以参数化，这是 `setUp` 完全做不到的。

## 展开

### 对比 unittest 的写法

```python
import unittest

class TestOrder(unittest.TestCase):
    def setUp(self):
        # 每个用例前都跑，无论这个用例需不需要 db
        self.db = connect_db()
        self.client = login_client()

    def tearDown(self):
        self.db.close()

    def test_create(self):
        ...            # 用到了 client 和 db

    def test_param_validate(self):
        ...            # 只校验参数，db 和 client 都白建了
```

pytest 的等价实现：

```python
import pytest

@pytest.fixture(scope="session")
def db():
    conn = connect_db()
    yield conn         # yield 之前是前置，之后是后置
    conn.close()

@pytest.fixture
def client(db):        # fixture 依赖 fixture
    return login_client(db)

def test_create(client):        # 声明即注入，需要什么写什么
    ...

def test_param_validate():      # 不声明就不初始化，跑得更快
    ...
```

差异一眼可见：**pytest 把「资源」和「用例」解耦了**，资源定义一次，谁要谁声明。

### 四种作用域怎么选

| scope | 生命周期 | 典型用途 | 风险 |
|-------|---------|---------|------|
| `function`（默认） | 每个用例前后各一次 | 造测试数据、重置状态、每次干净的 page 对象 | 慢，但最安全 |
| `class` | 每个测试类一次 | 一组用例共享同一个业务对象（如同一张订单的增删改查流） | 类内用例产生了顺序依赖 |
| `module` | 每个 `.py` 文件一次 | 模块级的环境准备，如某个模块专用的商品数据 | 同上，范围更大 |
| `session` | 整次 pytest 运行一次 | 登录 token、数据库连接池、启动 Docker 环境、WebDriver 复用 | 用例间互相污染；并行时每个 worker 各一份 |

**选型原则**：优先 `function`，只有当初始化开销明显（登录、建连、起浏览器）且资源本身**无状态可共享**时才提升作用域。判断标准是「用例 A 用完这个对象，会不会让用例 B 看到的状态不一样」。

一个常见的折中：session 级建连接池，function 级从池里取连接并在结束时回滚事务，兼顾速度和隔离。

```python
@pytest.fixture(scope="session")
def engine():
    return create_engine(DB_URL, pool_size=5)

@pytest.fixture
def session(engine):
    conn = engine.connect()
    trans = conn.begin()
    yield Session(bind=conn)
    trans.rollback()      # 用例造的数据自动回滚，天然隔离
    conn.close()
```

### yield 与 addfinalizer

```python
@pytest.fixture
def order():
    oid = create_order()
    yield oid
    delete_order(oid)     # 即使用例断言失败，这里也会执行
```

注意：**如果 fixture 的 yield 之前抛异常，后置代码不会执行**（因为还没 yield 出去）。多资源清理要么拆成多个 fixture，要么用 `addfinalizer` 逐个注册：

```python
@pytest.fixture
def env(request):
    a = create_a()
    request.addfinalizer(lambda: destroy_a(a))   # 注册即生效，后面失败也会清
    b = create_b()
    request.addfinalizer(lambda: destroy_b(b))
    return a, b
```

`addfinalizer` 的执行顺序是**后进先出**，符合资源释放的直觉。

### autouse 与 conftest

`autouse=True` 让 fixture 不用声明就自动生效，适合日志分隔线、全局埋点这类横切逻辑：

```python
# conftest.py
@pytest.fixture(autouse=True)
def log_case_boundary(request):
    logger.info(f"===== START {request.node.nodeid} =====")
    yield
    logger.info(f"===== END   {request.node.nodeid} =====")
```

但**不要滥用 autouse 做数据准备**，会让用例的依赖变成隐式的，读代码时看不出来这个用例依赖了什么，排查失败非常痛苦。

`conftest.py` 的查找规则：pytest 从用例文件所在目录**一路向上**找到 rootdir，把沿途所有 `conftest.py` 都加载；**只向上不向旁**，兄弟目录的 conftest 互不可见。同名 fixture 就近覆盖。

## 可能被追问的点

- **fixture 的执行顺序是怎样的？** 先按作用域从大到小（session → module → class → function），同作用域内按依赖关系拓扑排序，`autouse` 的排在同作用域显式声明的前面。
- **session 级 fixture 在 pytest-xdist 并行下会执行几次？** 每个 worker 各执行一次，因为 worker 是独立进程。如果 fixture 里有「只能做一次」的操作（建库、初始化数据），要用 `FileLock` + 标记文件让第一个 worker 做、其余等待读取结果。
- **fixture 能参数化吗？** 能，`@pytest.fixture(params=["chrome", "firefox"])`，通过 `request.param` 取值，所有依赖它的用例会自动跑多遍。这是做多浏览器/多环境覆盖的标准手法。
- **fixture 里怎么拿到用例的执行结果？** fixture 本身拿不到，要配合 `pytest_runtest_makereport` 这个 hook，把结果挂到 `item` 上，再在 fixture 后置里读 `request.node.rep_call.failed` 决定要不要截图。
- **`conftest.py` 里能放普通函数吗？** 能，但不推荐——`conftest.py` 的定位是「fixture 与 hook 的注册点」，工具函数应该放 `utils/` 里 import 进来，否则 conftest 会越滚越大。
- **为什么不推荐用例之间有依赖？** 一旦有依赖，单跑一条用例会失败、并行执行会乱序、失败会连锁扩散、失败定位变难。实在避不开（比如必须走完的支付流程），用 `pytest-dependency` 显式声明依赖，或者把整条流程写进一个用例里，用步骤断言而不是拆成多条。

## 结合自己项目的例子

商城中台的接口自动化框架最早是我从 unittest 迁到 pytest 的，动机就是 fixture。

迁移前的痛点很具体：每个 TestCase 的 `setUp` 里都在重复「登录拿 token → 建数据库连接 → 造一个测试商户」，700 多条用例跑一轮 38 分钟，其中登录接口被调了 700 多次，测试环境的认证服务经常被自己人压出限流。而且因为 token 存在 `self.token` 上，跨类没法共享，只能靠一个 `BaseTestCase` 基类往下继承，继承链三层深，改一处影响一大片。

迁移后我按作用域重新划了三层：

```python
# conftest.py（根目录）
@pytest.fixture(scope="session")
def token():
    """整轮只登录一次"""
    return login(USER, PWD)["access_token"]

@pytest.fixture(scope="session")
def api_client(token):
    """Session 复用连接池，自动带鉴权头"""
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    yield s
    s.close()

# tests/order/conftest.py（订单模块专用）
@pytest.fixture
def draft_order(api_client):
    """每条用例一张干净的草稿订单，用完删掉"""
    oid = api_client.post("/order/draft", json=DEFAULT_ORDER).json()["id"]
    yield oid
    api_client.delete(f"/order/{oid}")
```

效果：登录从 700+ 次降到 1 次，全量回归从 38 分钟降到 11 分钟；接上 `pytest-xdist -n 4` 之后进一步到 4 分钟。

并行时踩了一个坑值得讲：session 级的 `token` 在 4 个 worker 下变成登录 4 次，本身可以接受；但我另一个 session fixture 会做「清空并重建测试商户基础数据」，4 个 worker 同时执行导致互相清对方的数据，用例大面积 fail 且**每次失败的用例都不一样**。解法是用 `filelock` 做跨进程互斥，第一个拿到锁的 worker 执行初始化并写一个标记文件，其余 worker 等锁释放后直接读标记跳过：

```python
@pytest.fixture(scope="session")
def base_data(tmp_path_factory, worker_id):
    if worker_id == "master":          # 非并行模式
        return init_base_data()
    root = tmp_path_factory.getbasetemp().parent
    flag = root / "base_data.json"
    with FileLock(str(flag) + ".lock"):
        if flag.is_file():
            return json.loads(flag.read_text())
        data = init_base_data()
        flag.write_text(json.dumps(data))
        return data
```

这个坑我一般会主动讲出来，因为它能证明我不只是「会用 fixture」，而是真的在并行规模下踩过、并且知道 session 作用域的边界在哪。

## 参考

- 相关笔记：[[pytest fixture 详解]]、[[conftest.py 查找规则与作用域]]、[[pytest-xdist 并行执行]]、[[05-自动化测试框架]]
