---
created: 2026-07-31
tags: [App自动化测试/稳定性]
---

# App UI 自动化稳定性治理

![[assets/app-stability-flow.svg]]
*图示：稳定性治理是「用例前清场 → 等待策略兜底 → 弹窗/异常拦截 → 失败取证 → 状态恢复」的闭环，目标是让同一套用例在任意干净设备上可重复绿。*

> UI 自动化的价值不在「能跑通一次」，而在「连续跑 500 次还绿」。稳定性治理是 App 自动化和 Web 自动化最拉开差距的地方——设备、系统弹窗、动画、弱网全是不确定性来源。

## 概念

### 不稳定的根因分类

| 来源 | 典型现象 | 治理手段 |
|---|---|---|
| 环境/设备态 | 脏数据、残留登录、缓存膨胀 | `clearApp` + 用例级 `launch_app` |
| 时序 | 动画未结束就操作、网络延迟 | 显式等待 + 智能轮询 |
| 系统干扰 | 权限框、推送、低电量提示 | 弹窗拦截器 autouse fixture |
| 执行异常 | 崩溃、ANR、元素丢失 | 失败取证（截图/日志）+ 自动重试 |
| 设备恢复 | 用例结束残留在异常页 | teardown 恢复首页 |

### 三层治理模型

1. **预防层**：caps 预授权、`noReset`/`clearApp`、等待策略——让大多数用例根本不遇到不稳定。
2. **拦截层**：autouse fixture 在每一步前后清系统弹窗、检测崩溃、拦截非预期弹窗。
3. **恢复层**：失败截图+日志、自动重试、teardown 把设备恢复到已知状态，避免污染下一个用例。

## 用法

### 一、等待策略统一（不要 time.sleep 满天飞）

```python
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from appium.webdriver.common.appiumby import AppiumBy

def wait_click(driver, by, value, timeout=10):
    """统一显式等待，禁止裸 sleep"""
    el = WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((by, value))
    )
    el.click()
    return el

# WebView 里等 JS 渲染完用自定义条件
WebDriverWait(driver, 10).until(
    lambda d: d.execute_script("return document.readyState") == "complete"
)
```

### 二、弹窗拦截器（autouse fixture）

```python
@pytest.fixture(autouse=True)
def dismiss_noise(driver):
    yield driver
    # 每个用例结束后清一次系统/业务噪音弹窗
    for txt in ["允许", "稍后", "取消", "知道了", "更新"]:
        try:
            el = driver.find_ELEMENT(AppiumBy.XPATH, f"//*[@text='{txt}']")
            if el.is_displayed():
                el.click()
        except Exception:
            pass
```

`autouse=True` 让每个用例自动套用，无需手动调用。

### 三、崩溃检测 fixture（结合 logcat）

```python
@pytest.fixture(autouse=True)
def crash_guard(driver):
    collector = LogCollector(driver)
    collector.start()              # 后台抓 logcat
    yield
    if collector.has_crash():      # 见 [[adb logcat 日志抓取与崩溃定位]]
        pytest.fail("用例执行期间检测到 App 崩溃，详情见 Allure 附件")
```

### 四、失败取证与重试

```python
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call" and rep.failed:
        driver = item.funcargs.get("driver")
        # 截图 + 页面源码落 Allure
        allure.attach(driver.get_screenshot_as_png(), "失败截图", allure.attachment_type.PNG)
        allure.attach(driver.page_source, "页面源码", allure.attachment_type.TEXT)
```

```yaml
# pytest 插件做自动重试，只重试因不稳定失败的用例
# pytest.ini
addopts = --reruns 2 --reruns-delay 1
```

### 五、设备状态恢复（teardown）

```python
@pytest.fixture
def reset_after(driver):
    yield
    # 不管成功失败，回到首页，清掉半路弹窗
    try:
        driver.activate_app("com.xxx.app")
        driver.start_activity("com.xxx.app", ".HomeActivity")
    except Exception:
        driver.launch_app()
```

## 踩坑

1. **用 `time.sleep(3)` 代替等待**：动画一慢就等不够，网络一快就白等 3 秒还拖慢整体。一律显式等待条件满足。
2. **弹窗拦截器误点业务确认框**：把「删除」「确认支付」也当成噪音点掉。噪音词表要白名单化，且只在用例 teardown 阶段清，不在用例执行中清业务弹窗。
3. **`autouse` 崩溃检测 fixture 干扰正常断言失败**：用例本就该失败（断言不符），却被当成崩溃 `pytest.fail` 二次失败，报告混乱。崩溃检测只看 logcat 的 `FATAL EXCEPTION`，和断言失败区分开。
4. **重试掩盖了真 bug**：`--reruns` 把偶发失败重试成绿，但偶发可能就是真偶现崩溃。建议重试失败的用例单独标记，定期人工复盘「重试后才绿」的用例。
5. **teardown 恢复首页失败导致连环污染**：前一个用例崩在支付页，teardown 没拉回首页，下一个用例从支付页开始，全红。teardown 失败要降级到 `launch_app` 冷启兜底。
6. **并行时 fixture 共享 driver 串味**：多进程各持独立设备就没事；若伪并行共用一个 session，autouse fixture 会互相清对方状态。设备必须用例级独占。
7. **拦截器在 WebView 上下文里找原生弹窗失败**：切到 H5 后 `find_ELEMENT` 默认在 WebView 上下文，原生权限框不在里面，永远找不到。拦截系统弹窗要切回 NATIVE 上下文再找（见 [[Native 与 WebView 上下文切换]]）。
8. **截图时机在弹窗遮挡后**：截到的图是弹窗而非真实页面，排查无价值。取证前先尝试关弹窗，再截图。
9. **`page_source` 在崩溃瞬间取不到**：崩溃时 driver 会话可能已断，取源码抛异常。取证要 try/except 包住，能取多少取多少。
10. **设备长期运行内存泄漏拖慢后续用例**：连续跑几小时，设备内存吃紧，操作变慢触发超时。长流水线插入定时 `adb reboot` 或设备轮休。

## 面试怎么答

**30 秒骨架**：App UI 自动化的稳定性治理分三层。预防层用 caps 预授权、`clearApp`+`launch_app` 保证干净起点、显式等待替代 sleep；拦截层用 autouse fixture 在用例前后清系统弹窗、检测崩溃、拦截非预期干扰；恢复层做失败截图+日志取证、自动重试、teardown 把设备拉回首页。核心是「每个用例从确定状态开始、在确定性状态结束」，不让脏状态向下游传播。

**追问**：自动重试会不会掩盖 bug？——会，所以重试通过的用例要单独标记复盘，区分「偶现不稳定」和「真偶现崩溃」，不能一律当成绿。

## 参考

- [Appium 稳定性最佳实践](https://appium.io/docs/en/latest/guides/best-practices/)
- 相关笔记：[[App UI 自动化稳定性治理|稳定性治理]]、[[adb logcat 日志抓取与崩溃定位]]、[[Appium 系统权限弹窗处理]]、[[Native 与 WebView 上下文切换]]、[[Appium 应用启停、重置与设备状态恢复]]
