---
created: 2026-07-31
tags: [自动化测试框架/pytest]
---

# pytest 标记与用例筛选

> 给用例贴标签，然后在不同场景（提交前、合并前、每日回归）跑不同的子集——这是把「分层测试」从口号变成 CI 机制的关键一步。

## 概念

### marker 是什么

marker 是挂在测试项上的**元数据标签**，本身不改变用例行为，作用有三个：

1. **筛选执行**：`pytest -m smoke` 只跑冒烟；
2. **条件跳过**：`skipif` / `xfail` 这类内置 marker 会改变执行结果；
3. **给 fixture / hook 读取**：fixture 里用 `request.node.get_closest_marker("no_rollback")` 改变行为。

标记方式有三个层级，作用范围逐级扩大：

```python
import pytest

# 1. 模块级：本文件所有用例都带
pytestmark = pytest.mark.api
# 多个标记用列表
pytestmark = [pytest.mark.api, pytest.mark.slow]


# 2. 类级
@pytest.mark.smoke
class TestLogin:
    def test_ok(self): ...       # 继承 smoke
    def test_fail(self): ...     # 继承 smoke


# 3. 函数级
@pytest.mark.p0
def test_critical(): ...


# 4. 参数级（单条数据）
@pytest.mark.parametrize("n", [
    1,
    pytest.param(0, marks=pytest.mark.xfail(reason="BUG-1234")),
])
def test_x(n): ...
```

四个层级的 marker 会**叠加**，不是覆盖。用 `request.node.iter_markers()` 能拿到全部，`get_closest_marker(name)` 拿最近的一个。

### 必须注册 marker

自定义 marker 不注册的话，pytest 会给 warning：

```text
PytestUnknownMarkWarning: Unknown pytest.mark.smok - is this a typo?
```

注意上面示例里的 `smok`——**打错字的 marker 不会报错，只会静默不匹配**，导致 `pytest -m smoke` 少跑一批用例还没人发现。所以两件事必须做：

```ini
# pytest.ini
[pytest]
markers =
    smoke: 冒烟用例，每次部署后必跑
    p0: 最高优先级，阻塞发布
    api: 接口层用例
    e2e: 端到端用例，依赖完整环境
    slow: 单条超过 10 秒的慢用例
    flaky: 已知不稳定，需要治理
addopts = --strict-markers
```

`--strict-markers` 把「未注册 marker」从 warning 升级成 **error**，这是防打错字的唯一可靠手段，强烈建议默认开启。

也可以在 conftest 里用代码注册（适合动态生成）：

```python
# conftest.py
def pytest_configure(config):
    for line in [
        "smoke: 冒烟用例",
        "p0: 最高优先级",
    ]:
        config.addinivalue_line("markers", line)
```

### 内置 marker：skip / skipif / xfail

| marker | 语义 | 报告状态 |
|--------|------|---------|
| `skip` | 无条件跳过 | SKIPPED (s) |
| `skipif(cond)` | 条件成立时跳过 | SKIPPED (s) |
| `xfail` | 预期失败 | 真挂了 → XFAIL (x)；意外通过 → XPASS (X) |

```python
import sys

import pytest


@pytest.mark.skip(reason="功能已下线，等产品确认后删除")
def test_deprecated(): ...


@pytest.mark.skipif(sys.platform == "win32", reason="仅 Linux 支持")
def test_linux_only(): ...


@pytest.mark.skipif("config.getoption('--env') == 'prod'",
                    reason="破坏性用例不在生产跑")
def test_delete_all(): ...


@pytest.mark.xfail(reason="BUG-1234 已提单，待修复")
def test_known_bug():
    assert calc(0) == 1        # 挂了记 XFAIL，不算失败


@pytest.mark.xfail(strict=True, reason="修复后必须删掉这个标记")
def test_strict_xfail():
    assert calc(0) == 1        # 意外通过会记为 FAILED，逼你清理标记


@pytest.mark.xfail(raises=ConnectionError, reason="第三方服务不稳定")
def test_specific_exception():
    call_third_party()          # 只有抛 ConnectionError 才算 xfail，其它异常照常失败
```

**`skip` 和 `xfail` 的区别是面试必考点**：

- `skip` = **不执行**。用于「环境不支持」「功能下线」——执行了也没意义。
- `xfail` = **照常执行，但失败不算数**。用于「已知 bug，等修复」——一旦 bug 修好，`strict=True` 的 xfail 会因为 XPASS 变成 FAILED，主动提醒你删标记。

这就是为什么**已知 bug 应该用 `xfail(strict=True)` 而不是 `skip`**：skip 的用例会永远躺在那里，三年后没人知道它为什么被跳过。

运行时动态跳过：

```python
def test_need_service(service):
    if not service.alive():
        pytest.skip("依赖服务未启动")        # 运行时决定
    ...


# fixture 里跳过：会跳过所有依赖它的用例
@pytest.fixture
def redis_conn():
    if not redis_available():
        pytest.skip("Redis 未部署，跳过相关用例")
    return connect()


# 模块级跳过（比如缺少可选依赖）
pytest.importorskip("playwright")           # import 失败就跳过整个模块
```

### 两种筛选：`-m` 与 `-k`

| 选项 | 匹配对象 | 语法 |
|------|---------|------|
| `-m` | marker | `and` / `or` / `not` / 括号 |
| `-k` | nodeid 字符串（含参数 id） | `and` / `or` / `not` / 括号，子串匹配 |

```bash
# -m：按标记
pytest -m smoke
pytest -m "smoke and not slow"
pytest -m "api or e2e"
pytest -m "p0 and (api or e2e)"

# -k：按名字子串
pytest -k login                        # 名字含 login
pytest -k "login and not 边界"
pytest -k "test_create or test_delete"
pytest -k "密码错误"                    # 参数 id 也能匹配

# 两者可以叠加
pytest -m smoke -k "not slow_case"
```

`-k` 匹配的是完整 nodeid（含文件路径、类名、方法名、参数 id），所以 `pytest -k "api"` 会连带匹配 `tests/api/` 目录下的所有用例——有时是惊喜，有时是惊吓。

## 用法

### 用 marker 落地测试分层与 CI 分级

```python
# tests/api/test_order.py
import pytest

pytestmark = pytest.mark.api          # 整个文件都是接口层


@pytest.mark.p0
@pytest.mark.smoke
def test_create_order(client): ...


@pytest.mark.p2
@pytest.mark.slow
def test_order_list_pagination_10k(client): ...
```

```yaml
# .github/workflows/ci.yml
jobs:
  pre-commit:
    steps:
      - run: pytest -m "unit" -q --maxfail=1              # 秒级
  merge-request:
    steps:
      - run: pytest -m "api and not slow" -n 4            # 分钟级
  deploy-smoke:
    steps:
      - run: pytest -m "smoke and p0" --maxfail=1         # 部署后卡口
  nightly:
    steps:
      - run: pytest -m "not flaky" -n 8                   # 全量
```

这套配置的价值：**同一份用例集，通过标记切出四种执行策略**，不需要维护四份用例列表。

### 自动打标记：按目录批量

手写 marker 容易漏，用 hook 按目录自动打：

```python
# conftest.py
def pytest_collection_modifyitems(config, items):
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        if "/tests/unit/" in path:
            item.add_marker(pytest.mark.unit)
        elif "/tests/api/" in path:
            item.add_marker(pytest.mark.api)
        elif "/tests/e2e/" in path:
            item.add_marker(pytest.mark.e2e)
            item.add_marker(pytest.mark.slow)     # e2e 默认都算慢用例
```

### 根据环境自动跳过

```python
# conftest.py
def pytest_collection_modifyitems(config, items):
    env = config.getoption("--env")
    skip_destructive = pytest.mark.skip(reason=f"破坏性用例不在 {env} 执行")
    for item in items:
        if env == "prod" and item.get_closest_marker("destructive"):
            item.add_marker(skip_destructive)
```

这比在每条用例上写 `@pytest.mark.skipif(...)` 干净得多，而且策略集中在一处，改起来只改一个地方。

### fixture 读取 marker 改变行为

```python
@pytest.fixture
def db(request):
    conn = create_conn()
    tx = conn.begin()
    yield conn
    # 默认回滚保证用例隔离，打了 no_rollback 标记的用例才提交
    if request.node.get_closest_marker("no_rollback"):
        tx.commit()
    else:
        tx.rollback()


@pytest.fixture
def browser(request):
    """从 marker 参数里读浏览器类型。"""
    marker = request.node.get_closest_marker("browser")
    name = marker.args[0] if marker else "chrome"
    drv = launch(name)
    yield drv
    drv.quit()


@pytest.mark.browser("firefox")
def test_on_firefox(browser): ...
```

`marker.args` 是位置参数，`marker.kwargs` 是关键字参数，两者都能读。

### 统计与治理

```bash
# 看每个 marker 有多少用例
pytest --co -q -m smoke | tail -1
pytest --co -q -m "not smoke" | tail -1

# 列出所有已注册 marker 及说明
pytest --markers

# 报告里显示 skip / xfail 的原因（-ra 显示除 pass 外所有摘要）
pytest -ra
```

`-ra` 的输出是治理 skip 的关键工具：

```text
=========================== short test summary info ============================
SKIPPED [3] tests/test_pay.py:12: 支付网关沙箱未开通
XFAIL tests/test_calc.py::test_zero - BUG-1234 已提单，待修复
XPASS tests/test_calc.py::test_neg - BUG-1200 应该已修复，请删除 xfail 标记
```

建议在 CI 里把 `-ra` 设进 `addopts`，让每次执行都暴露被跳过的用例。

## 踩坑

1. **marker 打错字静默失效**。`@pytest.mark.smok` 不会报错，只有一条容易被淹没的 warning，结果 `pytest -m smoke` 少跑一批用例，上线后才发现漏测。**必须开 `--strict-markers`**，这是零成本的保险。

2. **`-m` 和 `-k` 搞混**。`-m smoke` 按 marker，`-k smoke` 按名字。用例名里没有 `smoke` 字样时 `-k smoke` 什么都匹配不到，会以为「标记没生效」。

3. **`-k` 意外匹配到目录名**。`-k "api"` 会匹配 `tests/api/` 下所有用例，因为 nodeid 里包含路径。想精确匹配用例名时加更多限定：`-k "test_login and api"`。

4. **中括号在 shell 里被解释**。`pytest tests/test_a.py::test_x[case1]` 在 bash 里 `[]` 是通配符，可能匹配不到文件。**加引号**：`pytest "tests/test_a.py::test_x[case1]"`。

5. **用 `skip` 掩盖已知 bug**。`@pytest.mark.skip(reason="有 bug")` 一挂就是两年，bug 早修了也没人知道要恢复。**已知 bug 用 `xfail(strict=True)`**——bug 修好后 XPASS 会变成 FAILED，强制你来清理标记。

6. **`xfail` 不加 `strict` 导致「假绿灯」**。默认 `strict=False` 时，用例意外通过记 XPASS 但 CI 仍是绿的，标记永远堆积。在 ini 里全局设 `xfail_strict = true` 更省心。

7. **`skipif` 的条件在收集期求值**。`@pytest.mark.skipif(get_env() == "prod", ...)` 里的 `get_env()` 在收集阶段就调用了，此时命令行参数可能还没解析到你的配置对象里。用字符串形式 `@pytest.mark.skipif("config.getoption('--env') == 'prod'")`，或者放到 `pytest_collection_modifyitems` 里统一处理。

8. **类级 marker 加在 `unittest.TestCase` 子类上部分失效**。`pytest.mark.parametrize` 完全不生效，`skip`/`skipif` 可以用但建议改用 `unittest.skip`。混用两套框架时要留意。

9. **`pytestmark` 写成了 `pytest_mark` 或放错位置**。变量名必须精确是 `pytestmark`，且要在模块顶层。写错了不报错，只是不生效。

10. **skip 数量无人监控**。CI 只看 failed 数，skip 了 200 条也是绿灯。建议在 `pytest_terminal_summary` 里对 skip 比例做阈值告警：

    ```python
    def pytest_terminal_summary(terminalreporter, exitstatus, config):
        skipped = len(terminalreporter.stats.get("skipped", []))
        total = sum(len(v) for v in terminalreporter.stats.values())
        if total and skipped / total > 0.1:
            terminalreporter.write_line(
                f"⚠ 跳过率 {skipped}/{total} 超过 10%，请检查", red=True)
    ```

## 面试怎么答

**Q：pytest 怎么做用例分组和选择性执行？**

A（30 秒骨架）：用 marker 打标签 + `-m` 表达式筛选。标记可以打在模块级（`pytestmark` 变量）、类级、函数级、甚至参数级（`pytest.param(..., marks=...)`），四层会叠加。执行时 `pytest -m "smoke and not slow"` 支持逻辑运算。另一个筛选方式是 `-k`，它匹配 nodeid 字符串子串，包括参数 id，适合临时精确跑某几条。工程上我会按「分层 + 优先级」两个维度打标记——`unit/api/e2e` 和 `p0/p1/p2`，然后在 CI 里切成提交前跑单测、合并前跑接口、部署后跑冒烟、每日跑全量四档。

**追问 1：自定义 marker 有什么坑？**

A：最大的坑是**打错字静默失效**。`@pytest.mark.smok` 不会报错，只给一条 warning，结果 `-m smoke` 少跑一批用例，还以为都跑了。解法是在 ini 里用 `markers = ` 注册所有 marker，并且开 `--strict-markers` 把未注册 marker 变成硬错误。顺带 `pytest --markers` 能列出所有已注册标记和说明，相当于给团队的一份文档。

**追问 2：`skip` 和 `xfail` 什么时候用哪个？**

A：`skip` 是**不执行**，用于「执行了也没意义」的场景——环境不支持、功能已下线、依赖服务没部署。`xfail` 是**照常执行但失败不计入失败数**，用于「已知 bug，等修复」。关键区别在后续治理：skip 的用例会永远躺在那里没人管；而 `xfail(strict=True)` 在 bug 被修复后会因为 XPASS 变成 FAILED，强制提醒你删掉标记。所以我的规矩是**已知 bug 一律用 `xfail(strict=True)` 并在 reason 里写 JIRA 单号**，ini 里全局设 `xfail_strict = true`。另外还要监控跳过率，在 CI 摘要里对超过 10% 的跳过率告警，否则 skip 会悄悄堆积。

**追问 3：怎么避免手动给每条用例打标记？**

A：用 `pytest_collection_modifyitems` hook 在收集完成后批量打。按目录路径判断，`tests/api/` 下的自动加 `api`，`tests/e2e/` 下的自动加 `e2e` 和 `slow`。同样的地方还能做环境相关的自动跳过——生产环境自动给带 `destructive` 标记的用例加上 skip。好处是策略集中在一处，改的时候不用翻几百个文件。

**追问 4：marker 除了筛选还能干什么？**

A：可以被 fixture 和 hook 读取来改变行为。比如我的 `db` fixture 默认在用例结束后回滚事务保证隔离，但打了 `@pytest.mark.no_rollback` 的用例会提交——fixture 里用 `request.node.get_closest_marker("no_rollback")` 判断。marker 还能带参数，`@pytest.mark.browser("firefox")` 的参数通过 `marker.args` / `marker.kwargs` 读出来，fixture 据此启动对应浏览器。这种「用标记声明用例需求、用 fixture 实现」的模式，比给每条用例传一堆参数干净。

## 参考

- [pytest 官方：How to mark test functions](https://docs.pytest.org/en/stable/how-to/mark.html)
- [pytest 官方：skip 与 xfail](https://docs.pytest.org/en/stable/how-to/skipping.html)
- 相关笔记：[[分层测试模型与测试金字塔]]、[[pytest 参数化 parametrize]]、[[pytest 插件机制与 hook 函数]]、[[pytest 失败重跑与执行顺序控制]]
