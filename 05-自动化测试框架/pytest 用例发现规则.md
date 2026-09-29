---
created: 2026-07-31
tags: [自动化测试框架/pytest]
---

# pytest 用例发现规则

![[assets/pytest-collection.svg]]
*图示：pytest 先定位 rootdir 与配置文件，再按命名约定递归收集，生成 Session → Package → Module → Class → Function 的收集树；「本地能跑、CI 收集 0 条」几乎都出在前两步。*

> 搞清楚 pytest 到底从哪里、按什么规则找到你的用例，是排查「用例没跑」「重复执行」「import 冲突」的前提。

## 概念

### 收集（collection）是独立于执行的一个阶段

pytest 运行分两个大阶段：

1. **collection**：找文件 → import 模块 → 遍历模块内成员 → 生成 Item 树；
2. **execution**：对每个 Item 依次跑 setup / call / teardown。

很多人以为「用例没跑 = 用例失败」，其实大量情况是**收集阶段就没找到它**，压根没进入执行。所以第一个要掌握的命令是：

```bash
pytest --collect-only -q        # 只收集不执行，看到底找到了哪些用例
pytest --co -q                  # 简写
```

### rootdir 与 inifile：一切的起点

pytest 启动时先做两件事：确定 **rootdir**（根目录）和 **inifile**（配置文件）。

查找逻辑（简化版）：

1. 取命令行参数里的路径（不带参数就是当前目录）作为起点；
2. 从起点**向上逐级**查找，遇到第一个包含以下文件之一的目录即为 rootdir：
   - `pytest.ini`（优先级最高，即使为空也生效）
   - `pyproject.toml`（需含 `[tool.pytest.ini_options]` 段）
   - `tox.ini`（需含 `[pytest]` 段）
   - `setup.cfg`（需含 `[tool:pytest]` 段）
3. 都找不到，则回退到 `setup.py` 所在目录，再不行就是公共祖先目录。

rootdir 的作用：

- 它是**相对路径的基准**（`testpaths`、`--alluredir` 等）；
- 它决定了 `sys.path` 的插入位置（rootdir 模式相关）；
- 它出现在每次运行的输出头部，**排障第一眼就该看它**。

```text
rootdir: /home/ci/workspace/qa-framework
configfile: pytest.ini
testpaths: tests
```

> 强烈建议**项目根目录一定放一个 `pytest.ini`**（哪怕只有 `[pytest]` 一行）。这是消除「本地和 CI 行为不一致」的最省事做法——它把 rootdir 钉死了。

### 命名约定：默认规则与自定义

| 配置项 | 默认值 | 含义 |
|--------|--------|------|
| `python_files` | `test_*.py` `*_test.py` | 哪些文件被视为测试模块 |
| `python_classes` | `Test*` | 哪些类被视为测试类 |
| `python_functions` | `test*` | 哪些函数/方法被视为用例 |
| `testpaths` | 无（当前目录） | 不带参数时从哪些目录开始找 |
| `norecursedirs` | `*.egg .* _darcs build CVS dist node_modules venv {arch}` | 不递归进入的目录 |

自定义写法：

```ini
[pytest]
testpaths = tests
python_files = test_*.py check_*.py
python_classes = Test* Check*
python_functions = test_* check_*
norecursedirs = .git .venv build dist data
addopts = -ra -q --strict-markers
```

**测试类有一条硬约束：不能定义 `__init__` 方法**。因为 pytest 需要自己实例化这个类，有 `__init__` 就无法用无参方式构造。踩这个坑时 pytest 只给一条 warning 就跳过了，非常容易被忽略：

```text
PytestCollectionWarning: cannot collect test class 'TestLogin' because it has a __init__ constructor
```

### 收集树与 nodeid

收集完成后得到一棵 Node 树：

```text
<Session qa-framework>
  <Dir tests>
    <Dir api>
      <Module test_login.py>
        <Class TestLogin>
          <Function test_ok>
          <Function test_wrong_pwd[空密码]>
```

每个叶子节点有唯一的 **nodeid**，格式是 `相对路径::类名::方法名[参数id]`：

```text
tests/api/test_login.py::TestLogin::test_wrong_pwd[空密码]
```

nodeid 是 pytest 的通用寻址方式，可以直接粘回命令行精确重跑：

```bash
pytest "tests/api/test_login.py::TestLogin::test_wrong_pwd[空密码]" -v
```

Allure 报告、xdist 分发、`--lf`（last failed）缓存，内部全都用 nodeid 标识用例。

### import 模式：`prepend` / `importlib` 与 `__init__.py`

这是收集阶段最难的一块，也是「两个同名 test 文件冲突」的根源。

默认的 `--import-mode=prepend` 行为：

1. 对一个测试文件，pytest 向上查找**连续存在 `__init__.py` 的目录**，确定它的「basedir」；
2. 把 basedir **插入 `sys.path[0]`**；
3. 用相对 basedir 的点分路径 import 这个模块。

所以：

- 目录里**有** `__init__.py`：`tests/api/test_login.py` 的模块名是 `tests.api.test_login`，唯一；
- 目录里**没有** `__init__.py`：模块名就是 `test_login`，那么 `tests/api/test_login.py` 和 `tests/web/test_login.py` 会**撞名**：

```text
import file mismatch:
imported module 'test_login' has this __file__ attribute:
  /proj/tests/web/test_login.py
which is not the same as the test file we want to collect:
  /proj/tests/api/test_login.py
HINT: remove __pycache__ / unique basename / add __init__.py
```

三种解法：

1. **给测试目录都加 `__init__.py`**（最省心，推荐）；
2. **文件名全局唯一**（`test_api_login.py` / `test_web_login.py`）；
3. **改用 `--import-mode=importlib`**（pytest 6+，不动 `sys.path`，不要求唯一名，是官方推荐的现代模式）。

```ini
[pytest]
addopts = --import-mode=importlib
```

## 用法

### 排障三连

```bash
# 1. 只看收集结果，最快确认「用例有没有被找到」
pytest --collect-only -q

# 2. 数一下收集到多少条（对比预期）
pytest --collect-only -q | tail -1

# 3. 看 rootdir / configfile / testpaths 判定对不对（在输出头部）
pytest --collect-only 2>&1 | head -8
```

如果 `--co` 输出是 `no tests ran`，按这个顺序查：

1. rootdir 和 configfile 是不是预期的那个？
2. 文件名 / 类名 / 函数名符合命名约定吗？
3. 测试类有 `__init__` 吗？
4. 目录被 `norecursedirs` / `--ignore` / `collect_ignore` 排除了吗？
5. 模块 import 时报错了吗（会显示为 collection error，不是 0 条）？

### 精确控制收集范围

```bash
# 指定目录/文件/类/方法
pytest tests/api
pytest tests/api/test_login.py
pytest tests/api/test_login.py::TestLogin
pytest tests/api/test_login.py::TestLogin::test_ok

# 排除某个目录（可重复）
pytest --ignore=tests/e2e --ignore=tests/perf

# 按 glob 排除
pytest --ignore-glob="**/legacy_*"

# 只跑上次失败的
pytest --lf
# 上次失败的优先跑，其余照跑
pytest --ff
# 收集时遇到第一个错误就停
pytest -x --co
```

### 代码级排除：`collect_ignore` 与 `pytest_ignore_collect`

某些场景需要「按条件」排除，比如 Python 版本不够、某个环境不跑 UI 用例：

```python
# conftest.py
import sys

collect_ignore = ["legacy_runner.py"]            # 静态排除，同目录下的文件

collect_ignore_glob = ["*_windows.py"] if sys.platform != "win32" else []


def pytest_ignore_collect(collection_path, config):
    """更灵活的动态排除；返回 True 表示不收集该路径。

    注：pytest 7 之前形参名是 path（py.path.local），7+ 是 collection_path（pathlib.Path）。
    """
    if config.getoption("--env") == "prod" and "destructive" in str(collection_path):
        return True
    return None      # 返回 None 交给其它 hook 决定
```

### 自定义收集：让 YAML 文件变成用例

pytest 的收集机制是可扩展的，这是「YAML 驱动框架」的底层原理——实现 `pytest_collect_file` 返回自定义的 Collector：

```python
# conftest.py
import pathlib

import pytest
import yaml


def pytest_collect_file(parent, file_path: pathlib.Path):
    """让 case_*.yaml 也能被当成测试文件收集。"""
    if file_path.suffix == ".yaml" and file_path.name.startswith("case_"):
        return YamlFile.from_parent(parent, path=file_path)
    return None


class YamlFile(pytest.File):
    def collect(self):
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        for spec in raw:
            yield YamlItem.from_parent(self, name=spec["name"], spec=spec)


class YamlItem(pytest.Item):
    def __init__(self, *, spec, **kwargs):
        super().__init__(**kwargs)
        self.spec = spec

    def runtest(self):
        actual = call_api(self.spec["request"])
        expected = self.spec["expected"]
        if actual["status_code"] != expected["status_code"]:
            raise YamlException(self.spec, actual)

    def repr_failure(self, excinfo):
        """自定义失败输出，让报告可读。"""
        if isinstance(excinfo.value, YamlException):
            spec, actual = excinfo.value.args
            return (f"用例「{spec['name']}」失败\n"
                    f"  期望: {spec['expected']}\n"
                    f"  实际: {actual}")
        return super().repr_failure(excinfo)

    def reportinfo(self):
        return self.path, 0, f"yaml用例: {self.name}"


class YamlException(Exception):
    pass
```

放好后直接 `pytest --co -q` 就能看到 YAML 里的用例被收集成了 Item。理解这套机制，就理解了 httprunner 之类的「YAML 测试框架」是怎么实现的。

### 用 hook 批量改造收集结果

```python
# conftest.py
def pytest_collection_modifyitems(config, items):
    """收集完成后统一加工用例列表。"""
    # 1. 解决中文 nodeid 在终端显示为 \u4e2d\u6587 的问题
    for item in items:
        item.name = item.name.encode("utf-8").decode("unicode_escape")
        item._nodeid = item.nodeid.encode("utf-8").decode("unicode_escape")

    # 2. 按目录批量打标记，省去每个文件手写
    for item in items:
        if "/e2e/" in str(item.fspath):
            item.add_marker("e2e")
        elif "/api/" in str(item.fspath):
            item.add_marker("api")

    # 3. 冒烟用例排前面，先跑关键路径
    items.sort(key=lambda it: 0 if it.get_closest_marker("smoke") else 1)
```

## 踩坑

1. **CI 上收集 0 条，本地正常**。95% 是 rootdir 判定不同：CI 的工作目录不同，pytest 向上找到了另一个 `setup.cfg` 作为 rootdir，`testpaths` 的相对路径就指错了。解法：项目根放 `pytest.ini` 钉死 rootdir，CI 里显式 `cd $WORKSPACE && pytest`。

2. **两个目录同名 `test_login.py` 报 `import file mismatch`**。目录缺 `__init__.py` 导致模块名撞车。加 `__init__.py`，或者改用 `--import-mode=importlib`。另外这个报错还有一种诱因是**残留的 `__pycache__`**——切换分支后老 `.pyc` 还在，`find . -name __pycache__ -exec rm -rf {} +` 清一下。

3. **测试类写了 `__init__` 导致整类被静默跳过**。只有一条 `PytestCollectionWarning`，混在一堆输出里根本看不见，表现就是「这个文件里的用例一条都没跑」。给 CI 加 `-W error::pytest.PytestCollectionWarning` 可以让它变成硬错误。

4. **用例函数名叫 `test` 开头但有默认参数**，pytest 会把参数当 fixture 找，报 `fixture 'x' not found`。工具函数不要用 `test_` 前缀命名——`test_helper()` 这种名字会被当用例收集。

5. **`python_functions = test*` 误伤**。默认是 `test*` 而非 `test_*`，所以名为 `testify_data()` 的工具函数也会被收集。写明 `python_functions = test_*` 更安全。

6. **模块顶层的重代码在收集期就执行了**。有人在测试模块顶层写 `driver = webdriver.Chrome()` 或 `CONFIG = load_config()`，结果 `pytest --co` 只想看看用例列表，浏览器全启动了、配置在 import 期就固化了（`--env` 参数失效）。**模块顶层只放 import 和常量，一切资源创建放 fixture。**

7. **`conftest.py` 里 import 错误导致整个目录收集失败**，报错却指向某个测试文件，很有迷惑性。看 traceback 最底部的文件名，通常是 conftest。

8. **参数化 id 里有中文，nodeid 变成 `\u767b\u5f55`**。终端和报告都不可读。用上面 `pytest_collection_modifyitems` 里的 `unicode_escape` 转换修复；注意这个改法在 pytest 7+ 需要同时改 `item.name` 和 `item._nodeid`。

9. **软链接目录不被递归**。pytest 默认不跟随 symlink（`follow_symlinks`），在用软链管理共享用例的项目里会「莫名少一半用例」。

10. **`--lf` 缓存跨环境失效**。`.pytest_cache` 记的是 nodeid，容器里路径变了或参数 id 变了就匹配不上，`--lf` 会退化成跑全量。CI 上想用 `--lf` 必须持久化 `.pytest_cache` 目录。

## 面试怎么答

**Q：pytest 是怎么找到测试用例的？**

A（30 秒骨架）：分两步。第一步定位 rootdir 和配置文件——从命令行给的路径向上找 `pytest.ini`、`pyproject.toml`、`tox.ini`、`setup.cfg`，第一个命中的目录就是 rootdir，它是所有相对路径的基准。第二步按命名约定递归收集：默认 `test_*.py` / `*_test.py` 是测试模块，`Test*` 是测试类（且不能有 `__init__`），`test*` 是用例函数。收集结果是一棵 Session → Module → Class → Function 的树，每个叶子有唯一 nodeid，形如 `tests/test_a.py::TestX::test_y[param]`。这些命名规则都能在 ini 里用 `python_files` / `python_classes` / `python_functions` 改。

**追问 1：为什么会出现「本地能跑、CI 收集 0 条」？**

A：绝大多数是 rootdir 判定不一致。CI 的工作目录和本地不同，pytest 向上找配置文件时命中了另一个文件，导致 `testpaths` 的相对路径指向了错的地方。排查手段是看输出头部的 `rootdir:` 和 `configfile:` 两行，再用 `pytest --collect-only -q` 确认收集数量。根治办法是在项目根放一个 `pytest.ini` 把 rootdir 钉死，并在 CI 里显式切到工作目录再执行。

**追问 2：两个目录里有同名测试文件会怎样？**

A：默认的 `prepend` import 模式下会报 `import file mismatch`。原因是 pytest 通过 `__init__.py` 的连续性确定包路径，如果目录里没有 `__init__.py`，两个 `test_login.py` 的模块名都是 `test_login`，`sys.modules` 里撞车。三种解法：给测试目录加 `__init__.py`、文件名全局唯一、或者用 `--import-mode=importlib`（pytest 6+ 的现代模式，不改 `sys.path`，官方推荐）。另外还要注意残留 `__pycache__` 也会引发同样的报错。

**追问 3：怎么让 pytest 收集非 Python 文件（比如 YAML 用例）？**

A：实现 `pytest_collect_file` hook，判断文件后缀后返回一个自定义的 `pytest.File` 子类，在它的 `collect()` 里 yield 自定义的 `pytest.Item`，Item 实现 `runtest()` 执行逻辑和 `repr_failure()` 定制失败输出。httprunner 这类 YAML 驱动框架就是这么做的。不过实际项目里我更倾向于简单方案——用 YAML 存数据、用 `parametrize` 把数据喂给普通 pytest 用例，可维护性比自造收集器高得多。

**追问 4：`pytest_collection_modifyitems` 有什么用？**

A：它在收集完成、执行开始前拿到完整的 items 列表，能做三类事：批量打标记（按目录自动加 `api`/`e2e` marker，不用每个文件手写）、调整执行顺序（冒烟用例排前面）、修正中文 nodeid 的 unicode 转义显示问题。要注意它是「批量后处理」，此时用例还没执行，所以不能在这里访问运行时数据。

## 参考

- [pytest 官方：Good Integration Practices（rootdir 与 import 模式）](https://docs.pytest.org/en/stable/explanation/goodpractices.html)
- [pytest 官方：配置项参考](https://docs.pytest.org/en/stable/reference/customize.html)
- 相关笔记：[[conftest.py 查找规则与作用域]]、[[pytest 断言重写机制]]、[[pytest 插件机制与 hook 函数]]、[[pytest 标记与用例筛选]]
