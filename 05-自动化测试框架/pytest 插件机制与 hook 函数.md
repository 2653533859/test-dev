---
created: 2026-07-31
tags: [自动化测试框架/插件]
---

# pytest 插件机制与 hook 函数

![[assets/pytest-hook-flow.svg]]
*图示：一次运行的五个阶段，以及每个阶段你能挂载的 hook；逐条用例循环里「每个阶段结束都生成一份 TestReport」，这才是失败截图/附加日志唯一正确的挂点。*

> 理解插件机制，才算从「会用 pytest」跨到「能改 pytest」。`conftest.py` 本质上就是一个本地插件，hook 就是它对外开放的扩展点。

## 概念

### pytest 的插件到底是什么

pytest 把自己几乎所有的内部行为都暴露成「hook 函数」。所谓插件，就是**任何定义了 `pytest_xxx` 命名函数、且能被 pytest 发现的对象**：

- **内置插件**：pytest 自带（`pytest_terminal`、`pytest_main` 等几十个）
- **第三方插件**：`pip install pytest-xdist` 之后，它通过 setuptools 的 `entry_points` 注册 `pytest11` 组，pytest 启动时自动加载
- **本地插件**：你项目里的 `conftest.py` —— 它不需要任何注册，pytest 在收集阶段顺着目录树找到即生效

所以「写插件」和「写 conftest」没有本质区别，只是 conftest 只能作用于它所在目录及子目录，而第三方插件是全局的。

### hook 的调用顺序与「叠加」语义

这是最容易被误解的点：**同名 hook 在多个地方定义时，不会互相覆盖，而是全部执行**。

pytest 把收集到的所有实现按「距离被测用例由近到远」排序，调用顺序是 **LIFO（后进先出）**——离得越近的越晚执行。例如：

- 根目录 `conftest.py` 的 `pytest_collection_modifyitems`
- 子目录 `conftest.py` 的 `pytest_collection_modifyitems`

两者都会跑。这对「多级目录各自加一层逻辑」是好事，但也意味着你不能假设「只有我这一个实现」。

### hookwrapper：包住别人的实现

普通 hook 是「并列执行」；`@pytest.hookimpl(hookwrapper=True)` 的实现则会**包裹**其它所有实现：

```python
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield          # 这里 pytest 会去执行其它 makereport 实现，拿到结果
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        # 此时用例刚执行完，driver 还活着
        _attach_screenshot(item, report)
```

`yield` 之前的代码是前置，`yield` 之后的代码是后置，且你能通过 `outcome.get_result()` 拿到别人算出来的结果再加工。失败截图、附加日志全靠这套机制。

## 用法

### 1. 加自定义命令行参数（--env）

```python
# conftest.py
def pytest_addoption(parser):
    parser.addoption(
        "--env",
        action="store",
        default="test",
        help="运行环境：test / staging / prod",
    )


@pytest.fixture
def env(request):
    return request.config.getoption("--env")
```

### 2. 收集后批量改用例（修 nodeid 乱码 / 打标记 / 改顺序）

```python
def pytest_collection_modifyitems(items):
    for item in items:
        # 中文用例名在有些 CI 里会乱码，这里统一处理
        item._nodeid = item._nodeid.encode("utf-8", "replace").decode("utf-8")
        # 自动给慢接口用例打标记
        if "slow_api" in item.name:
            item.add_marker(pytest.mark.slow)
```

### 3. 注册自定义 marker，避免 --strict-markers 报错

```python
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: 标记耗时较长的接口用例"
    )
```

### 4. hookwrapper 统一挂载失败截图

```python
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        driver = item.funcargs.get("driver")   # 从 fixture 注入里取
        if driver:
            allure.attach(
                driver.get_screenshot_as_png(),
                name="失败截图",
                attachment_type=AttachmentType.PNG,
            )
```

## 踩坑

1. **以为 hook 会覆盖**：在子目录 conftest 又写了一遍 `pytest_collection_modifyitems`，发现根目录的逻辑「没了」——其实是两个都跑了，只是顺序没预期。需要协调时用 hookwrapper 或把逻辑收口到一层。
2. **hookwrapper 里不 `yield`**：忘了 `yield outcome`，导致整个测试流程被你截断，用例根本不执行。hookwrapper 必须 yield 一次。
3. **`outcome.get_result()` 在 yield 前调用**：会抛 `OutcomeNotReady`。必须先 `yield` 再取结果。
4. **`pytest_collection_modifyitems` 改顺序影响 xdist 分片**：你手动重排了 items，但 xdist 按排好的顺序切片，可能导致某个 worker 分到一堆慢用例。需要负载均衡时优先用 `--dist loadgroup` / `loadfile`。
5. **hook 里抛异常拖垮整个 session**：hook 在收集/配置阶段执行，一旦抛错，后面用例全不跑。hook 里尽量 try/except 兜底。
6. **忘了 `pytest_configure` 注册 marker**：用 `@pytest.mark.slow` 但没注册，开 `--strict-markers` 直接报错。marker 要么在 `pytest.ini` 的 `[markers]` 声明，要么在 `pytest_configure` 里 `addinivalue_line`。
7. **conftest 顶部 import 失败会静默**：conftest 里 import 了一个不存在的模块，pytest 报「conftest import error」但信息很隐晦，排查时先确认 conftest 自身能单独 import。
8. **`pytest_runtest_makereport` 的 `call.when` 判断错**：setup 阶段失败 `report.when == "setup"`，截图要在 `call` 阶段才代表「用例体执行失败」。用错阶段要么截不到、要么在 setup 失败时也乱截。

## 面试怎么答

- **问：pytest 插件和 unittest 的扩展方式有什么不同？**
  答：unittest 基本靠继承 `TestCase` 重写 `setUp`/`tearDown` 来扩展，耦合在类里；pytest 把内部行为全暴露成 hook，扩展是「面向切面」的，可以不碰用例代码就给全局加参数、改收集、挂截图。插件还能通过 entry_points 全局注册，复用性强。
- **问：想实现「失败自动截图」应该挂哪个 hook？**
  答：用 `pytest_runtest_makereport` 的 hookwrapper，判断 `report.when == "call" and report.failed`，在 yield 之后、driver 还活着时截图。强调截图必须在 fixture 回收 driver 之前完成，否则要先把 report 挂到 item 上延后处理。
- **追问：同名 hook 多处定义会怎样？**
  答：全部执行，LIFO 顺序，不会覆盖；需要包裹别人时用 `hookwrapper=True`。

## 参考

- [pytest 官方文档：hook 参考](https://docs.pytest.org/en/stable/reference/reference.html#hooks)
- [Writing plugins](https://docs.pytest.org/en/stable/how-to/plugins.html)
- 相关笔记：[[conftest.py 查找规则与作用域]]、[[pytest-xdist 并行执行]]、[[测试报告：pytest-html 与 Allure]]
