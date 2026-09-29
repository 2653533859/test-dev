---
created: 2026-07-31
tags: [自动化测试框架/报告]
---

# 测试报告：pytest-html 与 Allure

![[assets/allure-report-pipeline.svg]]
*图示：Allure 完整链路是「执行产出 result json/attachment → allure generate 生成静态站点 → Jenkins 插件或 allure open 展示」；报告用 epic/feature/story 三级分组、用 step 展开执行时间轴、失败自动挂载截图与日志。*

> 报告的目标不是「证明我跑了」，而是「让没参与测试的人 30 秒看懂哪里挂了、为什么挂」。pytest-html 胜在轻量单文件，Allure 胜在交互与分组。

## 概念

### 两种报告的定位差异

- **pytest-html**：一个 HTML 文件搞定，自带用例列表、耗时、失败 traceback。适合小项目、想直接邮件/IM 发附件的场景。缺点是分组弱、不能附加结构化附件（截图得用 `extra` 手动塞）。
- **Allure**：生成一堆 `*-result.json` 中间产物，再用 `allure` 命令行渲染成一套**静态站点**。支持按业务分组（epic/feature/story）、步骤时间轴、附件、趋势图、严重程度。CI 里体验最好，但依赖 Java 的 allure 命令行。

选型的朴素标准：本地自测/小脚本用 pytest-html；团队级、要接 CI、要给别人看，用 Allure。

## 用法

### pytest-html：最小可用

```bash
pip install pytest-html
pytest --html=report.html --self-contained-html
```

```python
# 失败时把截图塞进报告
import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        driver = item.funcargs.get("driver")
        if driver:
            from pytest_html import extras
            report.extra = [extras.image(driver.get_screenshot_as_base64())]
```

`--self-contained-html` 把 CSS/JS 内联，单文件可直接分发。

### Allure：完整链路

```bash
pip install allure-pytest
pytest --alluredir=./allure-results          # ① 执行产出中间文件
allure generate --clean -o ./allure-report    # ③ 生成静态站点
allure open ./allure-report                  # ④ 本地打开
```

```python
import allure


@allure.epic("电商平台")
@allure.feature("订单模块")
@allure.story("取消订单")
@allure.severity(allure.severity_level.BLOCKER)
def test_cancel_order(order_api):
    with allure.step("创建待支付订单"):
        order = order_api.create()
    with allure.step("调用取消接口"):
        resp = order_api.cancel(order.id)
    assert resp.status == "CANCELLED"
```

Behaviors 三级（`epic > feature > story`）是给非测试同学看的视角；`step` 会在报告里展开成可折叠的执行时间轴；`severity` 用于按严重程度过滤。

## 踩坑

1. **Allure 趋势图不显示**：趋势需要历史数据。把上一轮的 `allure-report/history` 目录拷回 `allure-results/` 再 generate，趋势图才有对比。
2. **失败截图是空白/截不到**：截图必须在 `driver` 销毁前完成。如果 driver 是 function 级 fixture，teardown 阶段 driver 已经 `quit()`。解法是把 report 挂到 item 上（`item.rep_call = report`），由 fixture 在 `yield` 之后读取再截图——这是 Allure 截图最稳的写法。
3. **xdist 并行时 allure-results 写冲突**：多进程往同一目录写 `*-result.json`，文件名带进程/用例维度一般没问题，但要确保 `--alluredir` 是干净目录（`--clean` 只清 report 不清 results），否则混入旧数据。
4. **pytest-html 默认不截图**：必须走 `report.extra` + `extras.image(...)`，且建议用 `get_screenshot_as_base64()` 而非路径，配合 `--self-contained-html` 才能内联。
5. **报告里中文乱码**：Allure 的 json 是 UTF-8，乱码多发生在用 `open()` 读数据文件没指定 `encoding="utf-8"` 时，不是 Allure 的锅。
6. **CI 里 allure 命令找不到**：`allure` 是 Java 工具，CI 机器要装 JDK 并用 Allure Jenkins 插件或 `allure generate`，光装 `allure-pytest` 只产出 results，生不出站点。
7. **step 里包了 fixture 的 yield**：`with allure.step(...)` 只是记录，不能替代 fixture 的前后置；把建连接这种放进 step 里反而让失败定位更乱。
8. **`@allure.title` 用函数生成但没参数化**：title 里用了 `{data}`，记得 `allure.dynamic.title(...)` 在运行时赋值，否则标题全是模板字符串。

## 面试怎么答

- **问：pytest-html 和 Allure 怎么选？**
  答：看受众和集成。pytest-html 单文件、零额外依赖，适合自己看或随邮件发；Allure 需要 Java 命令行渲染，但分组、步骤时间轴、附件、趋势都更专业，适合团队接 CI 给上下游看。
- **问：Allure 失败截图为什么有时截不到？怎么解决？**
  答：因为截图发生在 teardown 阶段，而 driver 在 function 级 fixture 里已经被 quit。标准解法是 `pytest_runtest_makereport` 的 hookwrapper 里把 report 存到 `item.rep_call`，再由 driver fixture 在 `yield` 之后、quit 之前判断 `item.rep_call.failed` 来截图。
- **追问：Allure 的趋势图怎么来的？**
  答：generate 时需要 `allure-results/history` 目录，通常从上一次 `allure-report/history` 拷回来，Allure 据此画历史通过率曲线。

## 参考

- [Allure pytest 文档](https://docs.qameta.io/allure/)
- [pytest-html 文档](https://pytest-html.readthedocs.io/)
- 相关笔记：[[pytest 插件机制与 hook 函数]]、[[pytest-xdist 并行执行]]、[[测试框架日志与断言封装]]
