---
created: 2026-07-31
tags: [自动化测试框架/pytest]
---

# pytest 参数化 parametrize

![[assets/parametrize-cartesian.svg]]
*图示：叠加多个 parametrize 装饰器会生成笛卡尔积；nodeid 里的参数 id 拼接顺序是「最靠近函数的装饰器在前」——这个细节决定了你能不能用 `-k` 精确筛到某条数据。*

> 一份用例逻辑 + N 份数据 = N 条独立用例。这是把「等价类表」直接变成可执行用例的桥梁。

## 概念

### 为什么不是 for 循环

新人常写成这样：

```python
def test_login_bad():
    for username in ["", "ab", "a" * 21, "qa user"]:
        resp = login(username, "Passw0rd")
        assert resp.status_code == 400      # 第一个失败就中断了
```

问题有四个：

1. **第一条挂了后面不跑**，一次只能发现一个问题；
2. 报告里**只有 1 条用例**，看不出覆盖了几种输入；
3. 失败时不知道**是哪个值挂的**（除非自己拼 message）；
4. **不能单独重跑**某一个值，不能给某个值单独打 skip/xfail。

`parametrize` 在**收集阶段**就把它展开成 N 个独立的 Item，四个问题全解决：

```python
@pytest.mark.parametrize("username", ["", "ab", "a" * 21, "qa user"])
def test_login_bad(username):
    assert login(username, "Passw0rd").status_code == 400
```

```text
test_login_bad[]         PASSED
test_login_bad[ab]       PASSED
test_login_bad[a21]      FAILED
test_login_bad[qa user]  PASSED
```

**关键认知：参数化发生在收集期，不是执行期。** 参数列表里的表达式在 pytest 收集用例时就会被求值，所以里面**不能放运行时才能确定的东西**（比如 fixture 的返回值、需要登录后才能拿到的 ID）。

### 基本形式

```python
import pytest


# 单参数：字符串名 + 值列表
@pytest.mark.parametrize("n", [1, 2, 3])
def test_single(n): ...


# 多参数：逗号分隔的名字 + 元组列表
@pytest.mark.parametrize("a, b, expected", [
    (1, 1, 2),
    (2, 3, 5),
    (-1, 1, 0),
])
def test_add(a, b, expected):
    assert a + b == expected


# 名字也可以用列表形式
@pytest.mark.parametrize(["a", "b"], [(1, 2), (3, 4)])
def test_list_names(a, b): ...
```

### 笛卡尔积：叠加装饰器

```python
@pytest.mark.parametrize("browser", ["chrome", "firefox"])
@pytest.mark.parametrize("role", ["admin", "guest"])
def test_login(role, browser):
    ...
```

生成 **2 × 2 = 4** 条：

```text
test_login[admin-chrome]
test_login[guest-chrome]
test_login[admin-firefox]
test_login[guest-firefox]
```

注意 id 的拼接顺序：**最靠近函数的装饰器（`role`）在前**。这是装饰器自底向上应用的自然结果，但很反直觉，写 `-k` 筛选时经常踩。

想避免笛卡尔积、只测指定组合，就用**一个装饰器 + 元组**：

```python
@pytest.mark.parametrize("role, browser", [
    ("admin", "chrome"),
    ("guest", "firefox"),
])
def test_login(role, browser): ...        # 只有 2 条
```

### ids：让报告可读

默认 id 由 pytest 从值推导，规则是：

- `str` / `int` / `bool` / `None` → 直接用其字面量；
- 其它类型（dict、对象、list）→ 退化成 `参数名0`、`参数名1`。

所以下面这种写法在报告里完全不可读：

```python
@pytest.mark.parametrize("payload", [
    {"user": "admin", "pwd": "123"},
    {"user": "", "pwd": "123"},
])
def test_login(payload): ...
# test_login[payload0]  test_login[payload1]   ← 谁看得懂
```

三种给 id 的方式：

```python
# 1. ids 列表：一一对应
@pytest.mark.parametrize("payload", [
    {"user": "admin", "pwd": "123"},
    {"user": "", "pwd": "123"},
], ids=["正常账号", "用户名为空"])
def test_login(payload): ...


# 2. ids 函数：对每个值调用一次，返回 str
@pytest.mark.parametrize("payload", [...], ids=lambda p: f"user={p['user'] or '空'}")
def test_login(payload): ...


# 3. pytest.param 的 id 参数（推荐，数据和 id 写在一起不会错位）
@pytest.mark.parametrize("payload", [
    pytest.param({"user": "admin", "pwd": "123"}, id="正常账号"),
    pytest.param({"user": "", "pwd": "123"}, id="用户名为空"),
])
def test_login(payload): ...
```

第三种最推荐——`ids` 列表和数据列表分开写，改数据时极容易错位，而且长数据集下对不上号。

### pytest.param：给单条数据打标记

```python
@pytest.mark.parametrize("n, expected", [
    pytest.param(1, 1, id="正常值"),
    pytest.param(0, 0, id="零值", marks=pytest.mark.xfail(reason="BUG-1234 未修复")),
    pytest.param(-1, 1, id="负数", marks=pytest.mark.skip(reason="需求未定")),
    pytest.param(10**9, 10**9, id="超大值", marks=pytest.mark.slow),
])
def test_abs(n, expected):
    assert abs(n) == expected
```

这是 `parametrize` 相比 `for` 循环最有价值的能力：**单条数据可以独立 skip / xfail / 打标记**，不影响同组其它数据。

## 用法

### 从数据文件驱动

把参数列表抽到 YAML，实现数据与逻辑分离：

```yaml
# data/login_cases.yaml
- name: 正常登录
  request: {username: admin, password: "Passw0rd"}
  expected: {status_code: 200, code: 0}

- name: 密码错误
  request: {username: admin, password: "wrong"}
  expected: {status_code: 200, code: 10002}

- name: 用户名为空
  request: {username: "", password: "Passw0rd"}
  expected: {status_code: 400, code: null}
```

```python
from pathlib import Path

import pytest
import yaml

DATA_DIR = Path(__file__).parent.parent / "data"


def load_cases(filename: str):
    """加载 YAML 用例数据，返回 (参数列表, ids) 两元组。"""
    raw = yaml.safe_load((DATA_DIR / filename).read_text(encoding="utf-8"))
    params = [(c["request"], c["expected"]) for c in raw]
    ids = [c["name"] for c in raw]
    return params, ids


CASES, IDS = load_cases("login_cases.yaml")


@pytest.mark.parametrize("req, expected", CASES, ids=IDS)
def test_login(api, req, expected):
    resp = api.post("/api/login", json=req)
    assert resp.status_code == expected["status_code"]
    if expected["code"] is not None:
        assert resp.json()["code"] == expected["code"]
```

关键点：路径必须用 `Path(__file__).parent` 推导，不能写相对路径——否则换个目录执行就 `FileNotFoundError`。

### `pytest_generate_tests`：动态参数化

`parametrize` 是静态装饰器，需要根据命令行参数、环境、数据库内容动态决定参数时，用 hook：

```python
# conftest.py
def pytest_generate_tests(metafunc):
    """在收集阶段对每个用例函数调用一次，可动态注入参数。"""
    # 1. 按命令行参数决定测哪些浏览器
    if "browser" in metafunc.fixturenames:
        browsers = metafunc.config.getoption("--browsers").split(",")
        metafunc.parametrize("browser", browsers)

    # 2. 从数据库/接口拉取参数
    if "sku_id" in metafunc.fixturenames:
        ids_ = fetch_active_sku_ids()          # 收集期执行，注意别太慢
        metafunc.parametrize("sku_id", ids_, ids=[f"sku-{i}" for i in ids_])
```

```bash
pytest --browsers=chrome,firefox tests/web/
```

`metafunc` 的常用属性：`fixturenames`（用例需要的所有参数名）、`config`、`module`、`cls`、`function`、`definition.get_closest_marker(...)`。

### 与 fixture 配合：`indirect`

参数需要「加工 + 前后置」时，让它先过 fixture（详见 [[pytest fixture 详解]]）：

```python
@pytest.fixture
def user(request):
    u = create_user(role=request.param)
    yield u
    delete_user(u.id)


@pytest.mark.parametrize("user", ["admin", "guest"], indirect=True)
def test_permission(user):
    assert user.token is not None       # user 是真实创建的对象
```

### 用 `-k` 精确筛选参数化用例

```bash
# 只跑 id 含「密码错误」的
pytest -k "密码错误"

# 只跑 chrome 的组合
pytest -k "chrome"

# 组合条件
pytest -k "chrome and admin"
pytest -k "login and not 边界"

# 精确到某一条（注意引号，中括号在 shell 里有特殊含义）
pytest "tests/test_login.py::test_login[密码错误]"
```

`-k` 匹配的是 nodeid 的**字符串子串**，所以给 id 起有区分度的名字很重要——全叫 `case1`/`case2` 就没法筛。

### 参数化的堆叠与 marker 组合

```python
pytestmark = pytest.mark.api      # 模块级标记：本文件所有用例都带 api


@pytest.mark.smoke
@pytest.mark.parametrize("env", ["test", "uat"])
def test_health(env):
    ...
# 每条都同时带 api + smoke 标记
```

## 踩坑

1. **参数列表里放了 fixture 返回值**。`@pytest.mark.parametrize("uid", [get_user_fixture()])` —— 收集期就执行了，此时 fixture 根本没初始化，报 `Fixture "x" called directly` 或拿到脏数据。**参数化是收集期行为**，动态数据要用 `pytest_generate_tests` 或 `indirect`。

2. **参数是可变对象且被用例修改**。参数列表里的 dict 是**所有用例共享的同一个对象**，某条用例往里塞了 key，后面的用例就拿到脏数据：

   ```python
   @pytest.mark.parametrize("payload", [{"user": "a"}])
   def test_x(payload):
       payload["token"] = "..."     # 污染了模块级的那个 dict
   ```

   解法：用例里先 `payload = dict(payload)` 拷贝，或参数用不可变类型（tuple / frozen dataclass）。

3. **dict/对象参数的默认 id 是 `param0`**，报告完全不可读，失败时不知道是哪条数据。永远用 `pytest.param(..., id="中文说明")`。

4. **中文 id 在终端显示成 `\u5bc6\u7801`**。pytest 默认对非 ASCII 做转义。解法是在 conftest 里改 `pytest_collection_modifyitems`（见 [[pytest 用例发现规则]]），或者在 ini 里配 `disable_test_id_escaping_and_forfeit_all_rights_to_community_support = True`（名字就是这么长，官方在劝退）。

5. **`ids` 列表和数据列表错位**。中间插了一条数据忘了同步 ids，导致「报告里叫 A 的用例其实跑的是 B 的数据」，排查时怀疑人生。改用 `pytest.param(..., id=...)` 从根本上避免。

6. **id 重复导致 pytest 自动加后缀**。两条数据的 id 都叫「异常」，pytest 会变成 `异常0`、`异常1`，`-k "异常"` 会同时命中两条，`--lf` 缓存也容易错位。id 必须唯一。

7. **叠加装饰器造成组合爆炸**。三个 parametrize 各 5 个值 = 125 条用例，CI 时长失控。加装饰器前先 `pytest --co -q | tail -1` 看总数。多字段组合应该用 pairwise 精选（见 [[测试用例设计方法：场景法与正交实验法]]）。

8. **参数 id 拼接顺序记反**。以为是 `[chrome-admin]`，实际是 `[admin-chrome]`（靠近函数的装饰器在前），导致 `-k` 筛不到。不确定时先 `--co -q` 看一眼真实 nodeid。

9. **参数名和已有 fixture 同名**。`@pytest.mark.parametrize("client", [...])` 而 conftest 里也有 `client` fixture，参数会覆盖 fixture 且不报错，用例行为完全变了。给 fixture 加领域前缀可以避免。

10. **`indirect=True` 漏写**。用例拿到的是原始字符串而不是 fixture 加工后的对象，报 `AttributeError: 'str' object has no attribute 'xxx'`。

11. **参数化数据在模块顶层做重 IO**。`CASES = load_from_db()` 写在模块顶层，`pytest --collect-only` 也会连数据库，收集阶段变慢甚至失败。数据文件读取（本地 IO）可以接受，网络/DB 查询应该放 `pytest_generate_tests` 并做缓存。

## 面试怎么答

**Q：pytest 怎么做数据驱动？**

A（30 秒骨架）：核心是 `@pytest.mark.parametrize`。它在**收集阶段**把一条用例展开成 N 个独立的测试项，每项有自己的 nodeid，可以单独执行、单独重跑、单独打 skip/xfail 标记。这是它相比 for 循环的本质优势——for 循环第一个数据挂了后面就不跑了，报告里也只有一条用例。多个 parametrize 装饰器叠加会产生笛卡尔积；想只测指定组合就用一个装饰器加元组列表。数据量大时把数据抽到 YAML/Excel，用加载函数读出来喂给 parametrize，做到数据与逻辑分离。

**追问 1：怎么让报告里的用例名可读？**

A：用 `pytest.param(data, id="中文说明")`，把 id 和数据写在一起。不推荐单独传 `ids=[...]` 列表，因为改数据时极容易和 ids 错位，出现「报告里叫 A、实际跑的是 B」的情况。特别要注意 dict 或自定义对象作参数时，默认 id 会退化成 `param0`、`param1`，完全不可读，必须显式给。另外中文 id 在终端默认会被转义成 `\uXXXX`，需要在 `pytest_collection_modifyitems` 里做一次 `unicode_escape` 解码。

**追问 2：参数化的值能来自 fixture 吗？**

A：不能直接来自。因为 `parametrize` 是**收集期**求值的，那时 fixture 还没执行。有两种正确做法：一是 `indirect=True`，让 parametrize 的原始值传给同名 fixture 的 `request.param`，由 fixture 加工成真实对象并负责前后置——适合「参数需要创建真实资源」的场景；二是用 `pytest_generate_tests` hook 在收集期动态生成参数，能读命令行参数、环境变量、甚至查数据库。

**追问 3：参数化用例之间会互相影响吗？**

A：会，有个很隐蔽的坑：参数列表里的**可变对象是所有用例共享同一个实例**的。如果某条用例往参数 dict 里塞了 key，后面的用例就拿到被污染的数据，表现是「单跑通过、连跑失败」。我的做法是用例入口先做一次浅拷贝，或者干脆用不可变类型作参数。另一个影响是数据层面的——多条参数化用例如果共用同一个测试账号并修改其状态，同样会互相干扰，这种要靠工厂 fixture 给每条用例造独立数据。

**追问 4：`parametrize` 和参数化 fixture 怎么选？**

A：看作用范围。`parametrize` 只作用于被装饰的那一条用例，适合「这条用例的输入数据集」；参数化 fixture（`@pytest.fixture(params=[...])`）会让所有引用它的用例都复制一份，适合「跨浏览器、跨环境、跨数据库版本」这种矩阵维度，而且自带前后置。要注意参数化 fixture 的影响面很大——给 `browser` fixture 加一个值，全站几百条 UI 用例的数量就翻倍，加之前一定先用 `--co -q` 看看总数。

## 参考

- [pytest 官方：How to parametrize fixtures and test functions](https://docs.pytest.org/en/stable/how-to/parametrize.html)
- [pytest 官方：`pytest_generate_tests` 参考](https://docs.pytest.org/en/stable/reference/reference.html#pytest.hookspec.pytest_generate_tests)
- 相关笔记：[[pytest fixture 详解]]、[[数据驱动测试：YAML 与 Excel 驱动]]、[[测试用例设计方法：等价类与边界值]]、[[pytest 标记与用例筛选]]
