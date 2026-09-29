---
created: 2026-07-31
tags: [Web自动化测试/稳定性治理]
---

# UI 用例失败重跑与截图 trace

![[assets/failure-trace.svg]]
*图示：失败重跑与现场收集的整体流程——用例失败后由钩子自动收集截图/源码/日志，再做有限次重跑，仍失败才标记失败并把 artifacts 附到报告。*

> UI 自动化最现实的问题不是「会不会写」，而是「跑一百次会不会有那么几次飘」。重跑和现场收集，是治理 flaky 的两件基础设施。

## 概念

### 为什么需要重跑和 trace

UI 测试运行在「真实浏览器 + 真实网络 + 真实渲染」的最不稳定一层，失败天然分两类：

| 类型 | 含义 | 该不该重跑 |
|------|------|:---:|
| **真实失败（real failure）** | 功能真的坏了，或者选择器真的写错 | ✗ 重跑会掩盖 bug |
| **偶发失败（flaky）** | 时序竞争、网络抖动、动画未结束、CI 机器慢 | ✓ 重跑能消除噪声 |

**重跑的目的不是让用例「通过」，而是把「偶发噪声」和「真实 bug」区分开**。一条用例如果重跑 2 次后稳定通过，说明它是 flaky，值得去修等待策略；如果重跑 2 次仍然失败，说明它大概率是个真 bug——这时候 trace 就是定罪的证据。

### 重跑的核心原则：有限次 + 区分「真失败」

反模式是这样：

```python
# ✗ 危险：无限重试把"元素真的消失"拖成超时，掩盖真问题
while True:
    try:
        el.click()
        break
    except Exception:
        time.sleep(0.3)
```

正确做法是**只针对已知偶发的竞争点做有限次重试**，且重跑的次数要写进配置、可控。重跑本身不解决任何问题，它只是「给偶发失败第二次机会」，真正的治理是把 flaky 用例修到不需要重跑。

### trace / 截图 / 录屏 各自回答什么问题

| 产物 | 回答的问题 | 代价 |
|------|-----------|------|
| **截图（screenshot）** | 失败那一刻页面长什么样 | 极低 |
| **page_source** | DOM 结构、元素到底在不在 | 极低 |
| **控制台日志** | 前端有没有 JS 报错导致渲染中断 | 低（Chrome 支持） |
| **录屏（video）** | 失败前发生了什么交互 | 中（磁盘 + 编码） |
| **trace（Playwright）** | 任意时刻的 DOM 快照 + 网络 + 动作时间线，可回放 | 中高 |

**截图是底线，trace 是天花板**。Selenium 时代基本靠截图 + 源码；Playwright 的 trace 等于把整个执行过程录成了一个可交互的「飞行记录仪」，排查效率是代际差异。

## 用法

### Selenium：pytest-rerunfailures 做重跑

```bash
pip install pytest-rerunfailures
```

```python
# 命令行：每个失败用例最多重跑 2 次，仅重跑标记了 flaky 的
pytest --reruns 2 --only-rerun StaleElementReferenceException

# 或在用例上精细化控制
import pytest

@pytest.mark.flaky(reruns=3, reruns_delay=1)
def test_poll_table(driver):
    ...
```

`--only-rerun` 很关键：只重跑指定异常（如 `StaleElementReferenceException`、`ElementClickInterceptedException`），**不重跑 `AssertionError`**——断言失败一般代表真 bug，重跑没意义还会拖慢流水线。

### Selenium：失败时自动收集现场（conftest 钩子）

```python
# conftest.py
import pytest
from pathlib import Path
from datetime import datetime

@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return

    driver = item.funcargs.get("driver")
    if driver is None:
        return

    ts = datetime.now().strftime("%H%M%S")
    out = Path("artifacts") / f"{item.name}_{ts}"
    out.mkdir(parents=True, exist_ok=True)
    try:
        driver.save_screenshot(str(out / "screen.png"))
        (out / "page.html").write_text(driver.page_source, encoding="utf-8")
        (out / "url.txt").write_text(driver.current_url, encoding="utf-8")
        logs = driver.get_log("browser")      # Chrome 控制台日志
        (out / "console.log").write_text(
            "\n".join(f"{e['level']}: {e['message']}" for e in logs), encoding="utf-8"
        )
    except Exception as e:     # 有未处理 alert 时截图会抛异常，不能让钩子挂掉
        print(f"收集失败现场时出错: {e}")
```

钩子用 `hookwrapper` + `tryfirst`，保证在报告生成后、且早于其他钩子执行。**钩子内部必须 try 包住**——有未处理 alert 时 `save_screenshot` 会抛 `UnexpectedAlertPresentException`，否则钩子崩溃、现场全丢。详见 [[Selenium 常见异常排查]]。

### 把 artifacts 挂到 Allure 报告

```python
import allure

@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        driver = item.funcargs.get("driver")
        if driver is not None:
            allure.attach(
                driver.get_screenshot_as_png(),
                name="failure_screenshot",
                attachment_type=allure.attachment_type.PNG,
            )
            allure.attach(
                driver.page_source,
                name="page_source",
                attachment_type=allure.attachment_type.HTML,
            )
```

### Playwright：一行开启 trace / video / screenshot

Playwright 把三件套做成 context 级别的一等公民，**不需要自己写钩子**：

```python
# conftest.py
from playwright.sync_api import sync_playwright

def pytest_runtest_setup(item):
    item._pw = sync_playwright().start()

@pytest.fixture(scope="function")
def page():
    browser = item._pw.chromium.launch()
    context = browser.new_context(
        record_video_dir="videos/",
        record_trace_dir="traces/",
    )
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    yield page
    # 仅失败时保留 trace
    trace_path = f"traces/{item.name}.zip"
    context.tracing.stop(path=trace_path if report.failed else None)
    page.context.close()
    browser.close()
```

更省事的是 `pytest-playwright` 插件，自带命令行开关：

```bash
# 失败用例保留 trace，并自动在失败时截图
pytest --tracing=retain-on-failure --screenshot=only-on-failure --video=retain-on-failure
```

**`retain-on-failure` 是精髓**：通过的用例不保留 trace，既不占磁盘，又能保证失败时有完整记录。

### Playwright：回放 trace

```bash
# 用浏览器打开 trace，可拖动时间轴看每一步的 DOM 快照与网络
playwright show-trace traces/test_login.zip
```

trace 里能看到：每一步操作前后的 DOM 树、网络请求、控制台日志、动作耗时。**排查 flaky 时这比截图强一个数量级**——你能看到「点击之前元素到底在不在」「网络请求是不是卡住了」。

## 踩坑

1. **对所有失败都重跑**
   断言失败（`AssertionError`）代表功能坏，重跑只会拖慢流水线、掩盖真 bug。用 `--only-rerun` 限定到时序类异常，或只对 `@pytest.mark.flaky` 的用例重跑。

2. **重跑次数设太大**
   比如 reruns=5。偶发失败重跑 2 次基本能消，设太多只是把流水线时间拉长，且让人对 flaky 麻木。先设 2，再回头修用例。

3. **用重跑代替修等待**
   最常见误区：用例飘了就加 `--reruns`。重跑只是「容错」，没解决「为什么飘」。应该回到 [[Selenium 显式等待]] / [[Playwright 自动等待机制]] 把等待写对，目标是 flaky 率趋近 0。

4. **截图钩子自己抛异常导致报告缺失**
   有未处理 alert、或 `save_screenshot` 时页面正在导航，会抛异常让钩子崩溃。钩子内部必须 try 包住，且失败信息用 `print` 而非再抛。

5. **CI 上没开 trace 但本地开了**
   本地能复现的问题本地查，CI 上飘的问题必须 CI 留现场。CI 配置里同样加上 `--tracing=retain-on-failure`，否则「只在我机器上飘」的问题永远查不清。

6. **video 全量录制撑爆磁盘**
   每次跑全量录屏，几百条用例能录出几十 G。用 `retain-on-failure` 只保留失败录屏，或单纯靠 screenshot + trace 即可。

7. **把重跑通过当成「用例修好了」**
   重跑通过 ≠ 用例健康。要在报告里统计 flaky 次数，flaky 率超阈值的用例单独拉出来治理。

8. **trace 含敏感信息**
   trace 里记录的是真实页面，可能含登录态 cookie、个人信息。CI 上 artifact 要设访问权限，别把带隐私的 trace 公开。

## 面试怎么答

**Q：UI 用例经常随机失败你怎么治理？**
A：分三步。第一层是「现场」——必须在失败时自动收集截图、page_source、控制台日志，Playwright 还能留 trace 和 video，没有现场一切免谈；我在 conftest 里挂 `pytest_runtest_makereport` 钩子做这个，钩子本身要用 try 包住防止二次崩溃。第二层是「有限重跑」——只对时序类异常（Stale、ClickIntercepted）做 2 次内的重跑，断言失败不重跑，因为那代表真 bug；重跑的目的是区分「偶发噪声」和「真实失败」。第三层也是最关键的——**重跑只是容错，不是修复**，要回到等待策略把用例写稳，目标是 flaky 率趋近 0，并且持续统计 flaky 次数，对高频 flaky 用例单独治理。

**Q：Selenium 和 Playwright 在失败现场上有什么区别？**
A：Selenium 时代基本靠自己写钩子收截图 + page_source + `driver.get_log("browser")` 控制台日志。Playwright 把 screenshot / video / trace 做成了 context 级别的一等公民，一行配置就能开，而且支持 `retain-on-failure` 只在失败时保留，不占磁盘。它的 trace 是代际优势——等于把整个执行过程录成可回放的飞行记录仪，能拖动时间轴看每一步的 DOM 快照、网络请求和动作耗时，排查 flaky 比截图强一个数量级。

**Q：重跑会不会掩盖 bug？**
A：会，所以重跑必须克制。我只对已知的时序竞争点做有限次、可控的重跑，且绝不重跑断言失败。一条用例如果重跑后稳定通过，说明它是 flaky，值得去修等待策略；如果重跑仍然失败，那它大概率是个真 bug，trace 就是证据。重跑是「给偶发失败第二次机会」，不是「让坏用例通过」。

## 参考

- [pytest-rerunfailures](https://pytest-rerunfailures.readthedocs.io/)
- [Playwright · Trace viewer](https://playwright.dev/python/docs/trace-viewer)
- [Playwright · Video](https://playwright.dev/python/docs/videos)
- 相关笔记：[[Selenium 常见异常排查]]
- 相关笔记：[[Selenium 显式等待]]
- 相关笔记：[[Playwright 自动等待机制]]
- 相关笔记：[[UI 测试脏数据清理与数据隔离]]
- 相关笔记：[[07-Web自动化测试]]
