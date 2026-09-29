---
created: 2026-07-31
tags: [自动化测试框架/pytest]
---

# conftest.py 查找规则与作用域

![[assets/conftest-lookup.svg]]
*图示：conftest.py 只对「自己所在目录及其子目录」生效，用例向上逐级查找祖先目录的 conftest，兄弟目录之间互不可见；同名 fixture 由离用例最近的那个胜出。*

> pytest 的「隐式插件」机制：不需要 import，放对目录就生效——也正因为隐式，出问题时最难定位。

## 概念

### conftest.py 是什么

一句话定义：**conftest.py 是 pytest 的「目录级本地插件」**。

pytest 在收集阶段会自动发现并加载它，你**不需要也不应该** import 它。它能承载三类东西：

1. **fixture**：供该目录及子目录下所有用例使用；
2. **hook 实现**：`pytest_collection_modifyitems`、`pytest_runtest_makereport` 等；
3. **收集控制**：`collect_ignore`、`collect_ignore_glob`、`pytest_collect_file`。

为什么设计成「自动发现」而不是 import？因为测试目录通常不是一个规范的 Python 包，跨目录 import 会引入路径问题；而且 fixture 的解析是 pytest 在运行时按名字做的，本来就不依赖 import。

### 查找规则：只向上，不向旁

给定一个测试文件 `tests/api/test_login.py`，pytest 会收集**从 rootdir 到该文件所在目录**这条路径上的所有 conftest.py：

```text
project/
├── conftest.py            ① 对所有用例生效
└── tests/
    ├── conftest.py        ② 对 tests/ 下所有用例生效
    ├── api/
    │   ├── conftest.py    ③ 只对 tests/api/ 下生效
    │   └── test_login.py  ← 能看到 ①②③
    └── web/
        ├── conftest.py    ④ 只对 tests/web/ 下生效
        └── test_home.py   ← 能看到 ①②④，看不到 ③
```

两条推论：

- **兄弟目录互不可见**：`tests/api/conftest.py` 里的 fixture，`tests/web/` 用不了。想共享就往上提到 `tests/conftest.py`。
- **同名 fixture 就近覆盖**：`tests/api/conftest.py` 和根 conftest 都定义了 `client`，`tests/api/` 下的用例拿到的是前者。

这条「就近覆盖」规则非常有用——可以在根 conftest 定义一个通用版本，在子目录里按需特化。

### 加载与执行顺序

conftest.py 按目录层级**从外向内**加载：根 → tests → api → 测试模块。

这带来两个具体影响：

**1. `pytest_addoption` 必须写在 rootdir 的顶层 conftest.py**

命令行参数在 pytest 启动早期就要解析完，那时子目录的 conftest 还没加载。写在子目录会报：

```text
ERROR: usage: pytest [options]
pytest: error: unrecognized arguments: --env=uat
```

**2. 同名 hook 会「全部执行」，不是覆盖**

fixture 是「就近覆盖」，hook 是「全部调用」。多个 conftest 里都定义了 `pytest_collection_modifyitems`，三个都会被执行。执行顺序默认是 **LIFO**——离用例最近的先执行（内层优先）。

```python
# tests/conftest.py
def pytest_collection_modifyitems(items):
    print("tests 层 hook")


# tests/api/conftest.py
def pytest_collection_modifyitems(items):
    print("api 层 hook")

# 输出顺序：api 层 hook → tests 层 hook
```

这个差异（fixture 覆盖 vs hook 叠加）是面试高频题。

### fixture 的四级查找顺序

用例请求一个 fixture 名时，pytest 按以下顺序找，**先找到先用**：

1. 测试**类**内定义的 fixture；
2. 测试**模块**内定义的 fixture；
3. 最近的 **conftest.py**，然后逐级向上；
4. **插件**注册的 fixture（如 pytest 内置的 `tmp_path`、`capsys`，或 pytest-django 提供的）。

排查「fixture not found」或「拿到的不是我以为的那个」，用：

```bash
pytest --fixtures                      # 列出所有可用 fixture 及其来源文件
pytest --fixtures tests/api/           # 只看某目录能用哪些
pytest --fixtures-per-test tests/api/test_login.py   # 看每条用例实际用到哪些、来自哪里
```

`--fixtures-per-test` 输出会精确到文件行号，是解决覆盖问题最快的手段：

```text
tests/api/test_login.py::test_ok (fixtures used):
  client -- tests/api/conftest.py:12       ← 用的是 api 层的，不是根层的
  db     -- conftest.py:8
```

### 典型的三层职责划分

一个成熟框架的 conftest 分工大致是：

| 位置 | 放什么 |
|------|--------|
| 根 `conftest.py` | `pytest_addoption`（`--env` 等）、全局配置解析、session 级基础设施（DB 连接池、日志初始化）、全局 hook（失败截图、报告环境信息） |
| `tests/conftest.py` | 跨类型共享的业务 fixture：登录态、测试账号工厂、通用清理 |
| `tests/api/conftest.py` | 接口层专用：`api_client`、鉴权 header、接口 mock server |
| `tests/web/conftest.py` | UI 层专用：`browser`/`page` fixture、浏览器选项、失败截图实现 |

## 用法

### 根 conftest：命令行参数 + 全局配置

```python
# conftest.py（rootdir 顶层）
import pytest

pytest.register_assert_rewrite("core.assertions")   # 必须在 import core 之前

from core.config import load_settings   # noqa: E402


def pytest_addoption(parser):
    """注册自定义命令行参数。只在 rootdir 顶层 conftest 生效。"""
    parser.addoption("--env", action="store", default="test",
                     choices=["test", "uat", "prod"], help="运行环境")
    parser.addoption("--headless", action="store_true", default=False,
                     help="UI 用例是否无头模式")
    # 也可以往 ini 里加配置项
    parser.addini("api_timeout", help="接口超时秒数", default="10")


@pytest.fixture(scope="session")
def env(request) -> str:
    return request.config.getoption("--env")


@pytest.fixture(scope="session")
def settings(env):
    """解析后的全局配置，session 内只算一次。"""
    s = load_settings(env)
    print(f"\n>>> 本次执行环境: {env}  base_url={s.base_url}")
    return s


def pytest_configure(config):
    """注册自定义 marker，避免 --strict-markers 报 unknown mark。"""
    for line in ("smoke: 冒烟用例", "api: 接口用例", "e2e: 端到端用例"):
        config.addinivalue_line("markers", line)


def pytest_report_header(config):
    """在报告头部打印环境信息，排障第一眼就能看到。"""
    return f"env: {config.getoption('--env')}"
```

### 中间层 conftest：业务 fixture

```python
# tests/conftest.py
import pytest

from core.http import HttpClient
from core.user_factory import create_user, delete_user


@pytest.fixture(scope="session")
def http(settings) -> HttpClient:
    """会话级 HTTP 客户端，复用连接池。"""
    client = HttpClient(base_url=settings.base_url, timeout=settings.timeout)
    yield client
    client.close()


@pytest.fixture(scope="session")
def admin_token(http, settings) -> str:
    """登录一次，整个会话复用 token。"""
    resp = http.post("/api/login", json=settings.admin_account)
    assert resp.status_code == 200, f"登录失败: {resp.text}"
    return resp.json()["data"]["token"]


@pytest.fixture
def temp_user(http):
    """function 级：每条用例一个全新账号，天然支持并行。"""
    user = create_user(http)
    yield user
    delete_user(http, user.id)      # 无论用例成败都清理
```

### 子目录 conftest：特化与覆盖

```python
# tests/api/conftest.py
import pytest


@pytest.fixture
def client(http, admin_token):
    """接口层专用客户端：自动带鉴权头。

    如果根 conftest 也有名为 client 的 fixture，这里的会覆盖它。
    """
    http.headers.update({"Authorization": f"Bearer {admin_token}"})
    yield http
    http.headers.pop("Authorization", None)     # 用完摘掉，避免污染其它目录


@pytest.fixture(autouse=True)
def _log_case_boundary(request):
    """本目录下所有用例自动打印分隔线，便于日志定位。"""
    print(f"\n===== START {request.node.nodeid} =====")
    yield
    print(f"===== END   {request.node.nodeid} =====")
```

注意 `_log_case_boundary` 用了 `autouse=True` 且下划线开头——`autouse` fixture 不需要被引用，命名加下划线是为了提示「这不是给你显式调用的」。

### 让子目录复用兄弟目录的 fixture：`pytest_plugins`

兄弟目录不可见是硬规则，但如果确实需要共享一批 fixture，可以把它们抽成一个普通模块，用 `pytest_plugins` 显式加载：

```python
# fixtures/db_fixtures.py  ← 普通模块，不叫 conftest.py
import pytest


@pytest.fixture(scope="session")
def db_pool():
    ...


# tests/api/conftest.py
pytest_plugins = ["fixtures.db_fixtures"]      # 显式声明为插件
```

**限制**：pytest 7+ 起，`pytest_plugins` 只允许写在 **rootdir 顶层 conftest.py**，写在子目录会报错：

```text
ERROR: Defining 'pytest_plugins' in a non-top-level conftest is no longer supported
```

所以实际做法是在根 conftest 里统一声明所有 fixture 模块：

```python
# conftest.py（根）
pytest_plugins = [
    "fixtures.db_fixtures",
    "fixtures.api_fixtures",
    "fixtures.web_fixtures",
]
```

这套写法的好处是：fixture 按业务领域组织成模块，而不是全堆在几个 conftest 里，几百行的巨型 conftest 就能拆开了。

## 踩坑

1. **`from conftest import xxx` 导致 fixture 执行两次**。手动 import 会让 conftest 模块被加载两遍（一次由 pytest 自动加载，一次由 import），session 级 fixture 建两份资源，表现为「明明是 session 作用域却初始化了两次」。**永远不要 import conftest。**

2. **`pytest_addoption` 写在子目录 conftest**，报 `unrecognized arguments: --env`。必须放 rootdir 顶层。同理 `pytest_plugins` 在 pytest 7+ 也只能放顶层。

3. **兄弟目录 fixture 不可见，报 `fixture 'xxx' not found`**。新人常见于「在 `tests/api/conftest.py` 写了 `login`，在 `tests/web/` 里用」。解法是上提到 `tests/conftest.py`，或抽成模块用 `pytest_plugins` 加载。

4. **同名 fixture 覆盖导致「行为不是我写的那个」**。子目录 conftest 里不小心定义了和根 conftest 同名的 `client`，用例拿到的是子目录的版本。定位手段：`pytest --fixtures-per-test <文件>`，输出会标明每个 fixture 来自哪个文件的哪一行。

5. **同名 hook 全部执行导致重复副作用**。以为 hook 也是覆盖，在两层 conftest 都写了 `pytest_runtest_makereport` 做失败截图，结果每次失败截两张图、Allure 报告里挂两份附件。**hook 是叠加不是覆盖。**

6. **在 conftest 顶层写重初始化代码**。`conftest.py` 在收集期就被 import 了，顶层写 `driver = webdriver.Chrome()` 会导致 `pytest --collect-only` 也启动浏览器。**顶层只放 import 和常量，资源创建一律放 fixture。**

7. **conftest 里 import 报错，报错位置指向别处**。conftest import 失败会让整个目录收集失败，终端显示的错误文件名可能是某个测试模块，很有迷惑性。看 traceback 最底部确认真实位置。

8. **`autouse` fixture 在根 conftest 定义，影响了不该影响的用例**。在根 conftest 写 `@pytest.fixture(autouse=True)` 的浏览器初始化，导致纯接口用例也启动了浏览器，全量执行时间翻倍。**`autouse` 的作用范围就是它所在 conftest 的目录树，放置位置要精确。**

9. **多个 conftest 的 fixture 依赖形成隐式耦合**。子目录 fixture 依赖根 conftest 的 fixture 是正常的；反过来根 conftest 的 fixture 依赖子目录 fixture 会报 `fixture not found`（根 conftest 的用例看不到子目录）。依赖方向必须是自内向外。

10. **`--strict-markers` 下 marker 注册写在子目录 conftest**。`pytest_configure` 在各层都会执行，理论上可以写在子目录，但如果用例分布跨目录，就会出现「某些目录下 marker 没注册」的诡异现象。统一放根 conftest 或 ini 里最稳。

## 面试怎么答

**Q：conftest.py 是干什么的，查找规则是什么？**

A（30 秒骨架）：conftest.py 是 pytest 的目录级本地插件，用来放 fixture、hook 实现和收集控制，pytest 自动发现、不需要 import。查找规则是**只向上不向旁**——一条用例能用到从 rootdir 到它所在目录这条路径上所有 conftest 里的 fixture，兄弟目录之间互不可见。加载顺序从外向内，同名 fixture 由离用例最近的覆盖外层的。定位问题用 `pytest --fixtures-per-test <文件>`，能看到每个 fixture 实际来自哪个文件哪一行。

**追问 1：多层 conftest 里定义同名的 fixture 和同名的 hook，行为一样吗？**

A：不一样，这是个坑。**fixture 是就近覆盖**，只有最近的那个生效；**hook 是全部执行**，各层定义的都会被调用，默认按 LIFO 顺序（内层先执行）。我踩过的坑是在两层 conftest 都写了 `pytest_runtest_makereport` 做失败截图，以为内层覆盖了外层，结果每次失败截两张图、Allure 里挂了两份附件。

**追问 2：为什么 `pytest_addoption` 必须写在顶层 conftest？**

A：因为命令行参数在 pytest 启动的最早期就要完成解析，那个时刻只有 rootdir 的顶层 conftest 被加载了，子目录的 conftest 要等到收集阶段才加载。写在子目录会直接报 `unrecognized arguments`。同样的限制还有 `pytest_plugins`——pytest 7 之后也只允许写在顶层 conftest。

**追问 3：不同目录想共享 fixture 怎么办？**

A：两种方式。简单的是**往上提**——把 fixture 挪到共同祖先目录的 conftest 里。更好的方式是**抽成普通模块 + `pytest_plugins`**：把 fixture 按业务领域拆成 `fixtures/db_fixtures.py`、`fixtures/api_fixtures.py`，然后在根 conftest 里 `pytest_plugins = ["fixtures.db_fixtures", ...]` 统一注册。这样既能跨目录共享，又能把几百行的巨型 conftest 拆开，可读性好很多。注意 `pytest_plugins` 只能写在顶层 conftest。

**追问 4：conftest.py 能 import 吗？**

A：不能，也不该。手动 `from conftest import xxx` 会让模块被加载两次——pytest 自动加载一次、你 import 一次，结果是 session 级 fixture 建了两份资源，表现为「session 作用域却初始化了两遍」。fixture 的解析是 pytest 按名字在运行时完成的，本来就不依赖 import。另外 conftest 顶层不要写重初始化代码，因为收集阶段就会执行——`pytest --collect-only` 时把浏览器全启动了就很尴尬。

## 参考

- [pytest 官方：conftest.py 的作用与查找规则](https://docs.pytest.org/en/stable/reference/fixtures.html#conftest-py-sharing-fixtures-across-multiple-files)
- [pytest 官方：插件加载顺序](https://docs.pytest.org/en/stable/how-to/writing_plugins.html)
- 相关笔记：[[pytest fixture 详解]]、[[pytest 用例发现规则]]、[[pytest 插件机制与 hook 函数]]、[[多环境配置与环境隔离]]
