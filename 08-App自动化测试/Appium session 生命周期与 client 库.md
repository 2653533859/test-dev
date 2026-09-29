---
created: 2026-07-31
tags: [App自动化测试/Appium]
---

# Appium session 生命周期与 client 库

![[assets/appium-session-lifecycle.svg]]
*图示：`webdriver.Remote()` 这一行背后的七个步骤——从 POST /session、加载 driver、装三个 apk、拉起 instrumentation 服务、启动 App，到每条命令带 sessionId，最后 DELETE 回收。*

> 「为什么第一条用例特别慢？」「为什么跑完 CI 机器上残留一堆进程？」答案都在 session 生命周期里。

## 概念

### session 是什么

session 是 **WebDriver 协议里的会话概念**：客户端和某个被自动化目标之间的一段有状态连接。它有三个特征：

1. **有唯一 ID**：`sessionId`，之后每条命令的 URL 都带着它；
2. **独占资源**：一个 session 对应一台设备的一次完整控制权，天然串行；
3. **有明确的开始和结束**：`POST /session` 创建，`DELETE /session/{id}` 销毁。

**理解「独占」很关键**：一台设备同一时刻只能有一个活跃 session。想并行只能多设备，不能在同一设备上开两个 session 分头跑用例。

### 创建 session 时到底做了多少事

`webdriver.Remote(...)` 这一行看着简单，Android 上实际执行的步骤（对照上面的图）：

```text
① POST /session，body 是 W3C 格式的 capabilities
② Server 按 automationName 加载 UiAutomator2 Driver
③ Driver 检查并安装三个 apk：
     io.appium.uiautomator2.server
     io.appium.uiautomator2.server.test
     io.appium.settings
④ adb shell am instrument 拉起 server，adb forward tcp:8200 tcp:6790
⑤ 按重置策略处理 App 数据，再 am start 启动到 appActivity
⑥ 返回 sessionId 与实际生效的 capabilities
```

**步骤③④是耗时大头**。首次运行要装三个包，通常 20–40 秒；之后 Appium 会校验版本，若一致则跳过安装，降到 8–15 秒。这就是「第一条用例特别慢」的原因。

### 销毁 session 时做什么

`driver.quit()` → `DELETE /session/{id}`：

- 停止设备上的 instrumentation 进程；
- 移除 `adb forward` 端口转发；
- 按 `fullReset` 决定是否卸载 App；
- 恢复输入法（若配了 `resetKeyboard`）；
- Server 侧释放 session 对象。

**不 quit 的后果是逐步累积的**：端口不释放 → 下次 session 抢占失败；instrument 进程残留 → 设备变慢；Server 里僵尸 session 堆积 → 内存涨。CI 上跑几百条用例后设备「变得很奇怪」，多半是这个原因。

### client 库的角色

`Appium-Python-Client` 做的事很薄：

```text
driver.find_element(AppiumBy.ID, "x")
   └─ 转成 POST /session/{id}/element  body: {"using":"id","value":"x"}
   └─ 收到 {"value":{"element-6066-11e4-a52e-4f735466cecf":"00000000-..."}}
   └─ 包装成 WebElement 对象返回

element.click()
   └─ POST /session/{id}/element/{elementId}/click
```

它继承自 `selenium.webdriver.Remote`，所以**Selenium 的 API 大部分能直接用**：`WebDriverWait`、`expected_conditions`、`ActionChains`。Appium 在此之上扩展了移动端特有的方法。

```bash
pip install Appium-Python-Client        # 会自动带上匹配版本的 selenium
```

版本对应关系要注意：Appium-Python-Client 2.x 对应 Appium Server 1.x，3.x 起对应 Server 2.x。混用会出现莫名其妙的参数错误。

## 用法

### 最小闭环

```python
from appium import webdriver
from appium.options.android import UiAutomator2Options

opts = UiAutomator2Options()
opts.platform_name = "Android"
opts.automation_name = "UiAutomator2"
opts.udid = "emulator-5554"
opts.app_package = "com.demo.app"
opts.app_activity = ".ui.MainActivity"
opts.new_command_timeout = 300

driver = webdriver.Remote("http://127.0.0.1:4723", options=opts)
try:
    print("sessionId:", driver.session_id)
    print("实际生效的 caps:", driver.capabilities)
finally:
    driver.quit()        # 放 finally，保证异常时也能回收
```

### 用 pytest fixture 管理生命周期（推荐做法）

```python
import pytest
from appium import webdriver
from appium.options.android import UiAutomator2Options


@pytest.fixture(scope="session")
def appium_url() -> str:
    return "http://127.0.0.1:4723"


@pytest.fixture(scope="function")
def driver(appium_url, device_profile):
    """function 级：每条用例独立 session，隔离性最好但最慢。"""
    opts = UiAutomator2Options().load_capabilities(device_profile)
    d = webdriver.Remote(appium_url, options=opts)
    d.implicitly_wait(0)          # 关掉隐式等待，统一用显式等待
    yield d
    # yield 之后的代码即使用例失败也会执行
    try:
        d.quit()
    except Exception as e:
        print(f"quit 失败（session 可能已断）: {e}")
```

**`quit()` 要包 try**：如果 session 已经因为超时断了，`quit()` 自己会抛异常，把真正的用例失败原因盖掉。

### session 作用域怎么选：速度与隔离的权衡

| 作用域 | 每条用例耗时 | 隔离性 | 适用 |
|--------|------------|--------|------|
| `function` | +10~40s | 最好 | 用例数少、稳定性优先 |
| `class` | 一组共享 | 中 | 同一业务模块的连续场景 |
| `session` | 只建一次 | 最差 | 用例多、时间紧、有可靠的状态恢复 |

**App 自动化和 Web 不同**：Web 建 session 只要一两秒，App 要十几秒起。100 条用例用 function 级 session，光建会话就浪费 20 分钟。所以**大多数团队选 session 级 driver + 用例级状态重置**：

```python
@pytest.fixture(scope="session")
def driver(appium_url, device_profile):
    opts = UiAutomator2Options().load_capabilities(device_profile)
    d = webdriver.Remote(appium_url, options=opts)
    yield d
    d.quit()


@pytest.fixture(autouse=True)
def reset_app_state(driver):
    """每条用例前把 App 拉回首页，用 App 重启代替 session 重建。"""
    pkg = driver.capabilities["appPackage"]
    driver.terminate_app(pkg)        # 相当于 am force-stop，一两百毫秒
    driver.activate_app(pkg)         # 重新拉起
    yield
```

`terminate_app` + `activate_app` 只要几百毫秒，而重建 session 要十几秒。**用「重启 App」换掉「重建 session」，是 App 自动化提速最有效的一招。** 代价是 App 数据不会被清，需要额外处理数据隔离，见 [[Appium 应用启停、重置与设备状态恢复]]。

### session 保活与自动恢复

```python
from selenium.common.exceptions import InvalidSessionIdException, WebDriverException


def is_session_alive(driver) -> bool:
    try:
        _ = driver.current_activity      # 发一个轻量命令探活
        return True
    except (InvalidSessionIdException, WebDriverException):
        return False


@pytest.fixture(autouse=True)
def ensure_session(request, driver_holder):
    """session 级 driver 挂了就自动重建，避免后续用例全军覆没。"""
    if not is_session_alive(driver_holder.driver):
        print("检测到 session 已失效，重建中…")
        driver_holder.rebuild()
    yield
```

这在长时间稳定性测试里很有必要——跑两小时中间设备重启一次，没有自恢复机制的话后面几百条用例全红。

### 加速 session 建立

```python
opts.set_capability("appium:skipServerInstallation", True)     # 跳过装 server apk
opts.set_capability("appium:skipDeviceInitialization", True)   # 跳过设备初始化
opts.set_capability("appium:skipUnlock", True)                 # 跳过解锁流程
opts.set_capability("appium:noReset", True)                    # 不清数据
opts.set_capability("appium:ignoreHiddenApiPolicyError", True)
```

实测能把二次 session 从 15 秒降到 5 秒左右。**但首次运行必须关掉 `skipServerInstallation`**，否则设备上没有 server apk，直接失败。合理做法是 CI 流水线里第一步单独跑一次「预热 session」，之后的用例全部开加速。

### 查看 Server 上现有的 session

```bash
curl http://127.0.0.1:4723/sessions
# {"value":[{"id":"7f3a...","capabilities":{...}}]}

# 手动杀掉僵尸 session
curl -X DELETE http://127.0.0.1:4723/session/7f3a...
```

CI 上可以在任务开始前调 `/sessions` 清理残留，避免上一次失败的构建留下的 session 占着设备。

## 踩坑

1. **`driver.quit()` 写在用例末尾而不是 fixture teardown**
   用例中途抛异常就永远执行不到，session 泄漏。**必须放在 fixture 的 `yield` 之后或 `finally` 里。**

2. **`A session is either terminated or not started`**
   最常见原因是 `newCommandTimeout` 超时（默认 60 秒）。调试打断点、或用例里有长时间等待都会触发。调到 300 以上。

3. **`quit()` 自身抛异常盖掉真实失败原因**
   session 已断时 `quit()` 会抛，而它在 teardown 里，pytest 会把它报成 error 而不是原来的 failure。包 try/except。

4. **用 `driver.close()` 代替 `quit()`**
   Web 里 `close()` 关当前窗口、`quit()` 结束会话。移动端 `close()` 语义模糊（部分 driver 上等价于关 App），**回收 session 必须用 `quit()`**。

5. **session 级 driver 但用例互相依赖**
   共享 session 提速的前提是每条用例都能独立把 App 拉回已知状态。如果用例 B 依赖用例 A 留下的数据，单独跑 B 就失败，`-k` 筛选执行也会失败——这是自动化项目最难还的技术债。

6. **`skipServerInstallation` 在全新设备上导致失败**
   设备上没装过 server apk 就跳过安装，必然起不来。首跑要关掉。

7. **多设备并行时 session 串台**
   `systemPort` 没错开，第二个 session 可能连到第一台设备的 server 上，表现为「操作打在了另一台手机上」。见 [[Appium Desired Capabilities 详解]]。

8. **client 与 server 大版本错配**
   Appium-Python-Client 2.x + Server 2.x 会出现 capabilities 格式不兼容。`pip show Appium-Python-Client` 和 `appium -v` 对一下。

9. **implicit wait 与显式等待混用**
   `implicitly_wait(10)` 加 `WebDriverWait(driver, 10)` 会让超时变成不可预测的叠加值（甚至 10×10）。**一律 `implicitly_wait(0)`，只用显式等待**，同 [[Selenium 隐式等待与显式等待混用冲突]]。

10. **忘记 session 是有状态的**
    切了 context 不切回来、开了新 Activity 没返回、改了设备设置没还原——这些状态会带到下一条用例。session 复用的提速收益，必须用严格的状态恢复来换。

## 面试怎么答

**Q：Appium 的 session 是什么？创建一个 session 发生了什么？**
A：session 是 WebDriver 协议里的会话，代表客户端对一台设备的一次完整控制权，有唯一 sessionId，之后每条命令的 URL 都带着它。创建过程在 Android 上是这样：client 发 `POST /session` 带上 capabilities，Server 根据 `automationName` 加载 UiAutomator2 Driver，driver 检查设备上有没有装 `appium-uiautomator2-server` 这三个 apk，没有或版本不对就装，然后用 `am instrument` 把它拉起来，它在设备内监听 6790 端口，driver 再用 `adb forward` 映射到 PC 的 8200，最后按重置策略处理 App 数据并启动到指定 Activity，返回 sessionId。整个过程首次要 20 到 40 秒，之后跳过安装能降到 10 秒出头——这就是「第一条用例特别慢」的原因。

**Q：session 应该多久重建一次？用例之间怎么隔离？**
A：这是速度和隔离的权衡。App 建 session 要十几秒，比 Web 慢一个量级，所以每条用例一个 session 在用例多的时候不现实——100 条用例光建会话就 20 多分钟。我的做法是 driver 用 session 级作用域，只建一次；用例级隔离靠 `terminate_app` 加 `activate_app` 重启 App，只要几百毫秒。需要清数据的用例单独调 `pm clear` 或走接口重置数据。这样既快又能保证每条用例从已知状态开始。前提是必须有可靠的状态恢复逻辑，否则共享 session 会让用例互相污染，那就得不偿失了。

**Q：忘了 `driver.quit()` 会怎样？**
A：资源不会回收，而且是累积性的。设备上的 instrumentation 进程还在跑，`adb forward` 的端口不释放，下一个 session 想用同一个 `systemPort` 就抢不到；Appium Server 里也会堆积僵尸 session 对象。跑几百条用例后表现为设备越来越慢、session 建立成功率下降。所以 `quit()` 必须放在 pytest fixture 的 teardown 里，不能写在用例末尾——写在末尾的话，用例中途抛异常就执行不到了。另外 `quit()` 本身要包 try，因为 session 如果已经超时断开，它会抛异常，反而把真正的失败原因盖掉。

**Q：Appium 的 client 库和 Selenium 是什么关系？**
A：Appium-Python-Client 直接继承自 Selenium 的 `webdriver.Remote`，因为两者用的是同一套 W3C WebDriver 协议。所以 Selenium 的 API 基本都能用：`WebDriverWait`、`expected_conditions`、`ActionChains` 都是通用的。Appium 在此之上加了移动端特有的东西：`AppiumBy` 里的 `ACCESSIBILITY_ID`、`ANDROID_UIAUTOMATOR`、`IOS_PREDICATE` 这些定位策略，以及 `terminate_app`、`activate_app`、`swipe`、`set_network_connection`、上下文切换这些移动端方法。这也是为什么会 Selenium 的人上手 Appium 很快——协议层是同一套，学的主要是移动端特有的那部分能力和坑。

## 参考

- [Appium · Session 管理](https://appium.io/docs/en/latest/guides/managing-sessions/)
- [Appium-Python-Client 文档](https://github.com/appium/python-client)
- 相关笔记：[[Appium 架构原理与工作流程]]
- 相关笔记：[[Appium Desired Capabilities 详解]]
- 相关笔记：[[Appium 应用启停、重置与设备状态恢复]]
- 相关笔记：[[pytest fixture 详解]]
- 相关笔记：[[08-App自动化测试]]
