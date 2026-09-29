---
created: 2026-07-31
tags: [面试题/App自动化测试]
---

# Appium 的工作原理

> 从一行 `driver.find_element()` 到手机上真的点了一下，中间经过四层。讲清这条链路，排障能力就有了。

## 30 秒回答骨架

Appium 是一个 **C/S 架构的 HTTP 服务**，遵循 W3C WebDriver 协议，核心链路四层：

1. **脚本层（Client）**：Python/Java 客户端把 API 调用翻译成 HTTP 请求，发给 Appium Server。
2. **Appium Server（Node.js）**：接收请求，根据 `Desired Capabilities` 里的 `automationName` 选择对应的 **Driver**（Android 用 UiAutomator2，iOS 用 XCUITest）。
3. **平台 Driver**：把 WebDriver 协议命令转成平台原生自动化框架的调用。Android 侧会往设备上装一个 **bootstrap 服务端 APK**（`io.appium.uiautomator2.server`），通过 adb 端口转发建立通信。
4. **设备层**：设备上的 server 调用 **Google UiAutomator2 / Apple XCUITest** 框架，由系统级 API 完成真正的点击、输入、取控件树。

一句话总结优势：**因为统一在 WebDriver 协议这一层做抽象，所以一套脚本能跨 Android/iOS、跨原生/H5/混合应用，且不需要重新编译被测 App。**

## 展开

### 完整调用链

```text
测试脚本 (Python appium-client)
   │  HTTP POST /session/{id}/element  {"using":"id","value":"btn_login"}
   ▼
Appium Server (Node.js, 默认 :4723)
   │  按 automationName 路由到 UiAutomator2Driver
   ▼
UiAutomator2 Driver
   │  adb forward tcp:8200 tcp:6790  → 转发到设备
   ▼
设备内 io.appium.uiautomator2.server (instrumentation 进程)
   │  调用 UiAutomator2 API
   ▼
Android 系统 AccessibilityService → 目标 App 界面
```

反向再把结果一层层包成 JSON 返回。**每一个 `find_element` / `click` 都是一次完整的 HTTP 往返**——这解释了为什么 Appium 用例比 Web 慢得多，也解释了为什么「减少不必要的查找」是 App 自动化最有效的提速手段。

### Desired Capabilities 关键字段

```python
from appium.options.android import UiAutomator2Options

caps = {
    "platformName": "Android",
    "appium:automationName": "UiAutomator2",   # 决定用哪个 driver，最关键
    "appium:deviceName": "emulator-5554",
    "appium:appPackage": "com.example.shop",
    "appium:appActivity": ".ui.SplashActivity",
    "appium:noReset": True,        # 不清数据，保留登录态，跑得快
    "appium:fullReset": False,     # True 会卸载重装，用例最干净但最慢
    "appium:newCommandTimeout": 120,   # 多久没收到命令就断开 session
    "appium:autoGrantPermissions": True,  # 自动授予权限，跳过系统弹窗
    "appium:unicodeKeyboard": True,       # 支持中文输入
    "appium:resetKeyboard": True,
}
driver = webdriver.Remote("http://127.0.0.1:4723", options=UiAutomator2Options().load_capabilities(caps))
```

`noReset` / `fullReset` 是**用例隔离与执行速度的核心权衡**：冒烟用 `noReset` 快，回归首条用例用 `fullReset` 保证干净起点。

### 三类应用的定位差异

| 类型 | 界面构成 | 定位方式 | 需要切 context |
|------|---------|---------|---------------|
| 原生（Native） | Android View / iOS UIKit | `resource-id`、`accessibility id`、`class name`、UiSelector | 否 |
| 混合（Hybrid） | 原生壳 + WebView | 原生部分同上；WebView 内用 CSS/XPath | 是 |
| 纯 H5 | 浏览器 | CSS/XPath | 是（或直接用 Chromedriver） |

上下文切换：

```python
print(driver.contexts)   # ['NATIVE_APP', 'WEBVIEW_com.example.shop']
driver.switch_to.context("WEBVIEW_com.example.shop")
driver.find_element(By.CSS_SELECTOR, "#pay-btn").click()
driver.switch_to.context("NATIVE_APP")     # 用完切回来，否则后续原生定位全找不到
```

怎么判断当前元素是原生还是 WebView：用 Appium Inspector 或 `uiautomatorviewer` 看控件树，如果整个页面只有一个 `android.webkit.WebView` 节点、里面没有子控件，那就是 WebView，得切 context 才看得到内部结构。调试 H5 部分可以在 Chrome 打开 `chrome://inspect`，前提是 App 的 WebView 开了 `setWebContentsDebuggingEnabled(true)`（一般只有 debug 包开）。

### 定位方式的优先级

```python
# 最优：resource-id（唯一、稳定、快）
driver.find_element(AppiumBy.ID, "com.example.shop:id/btn_login")

# 次优：accessibility id（跨平台通用，对应 content-desc / iOS label）
driver.find_element(AppiumBy.ACCESSIBILITY_ID, "登录按钮")

# Android 专用：UiSelector，支持链式与滚动查找，性能好于 XPath
driver.find_element(
    AppiumBy.ANDROID_UIAUTOMATOR,
    'new UiScrollable(new UiSelector().scrollable(true))'
    '.scrollIntoView(new UiSelector().text("退出登录"))',
)

# 最后才用 XPath：要遍历整棵控件树，在复杂页面上可能耗时数秒
driver.find_element(AppiumBy.XPATH, "//android.widget.TextView[@text='确定']")
```

**XPath 在 Appium 上的代价远高于 Web**：每次查找都要把整个控件树 dump 成 XML 再解析，页面复杂时单次可能 3~5 秒。这是 App 自动化最典型的性能陷阱。

### Toast 怎么捕获

Toast 不是普通 View，不在 UiAutomator2 默认的控件树里，也不响应点击。UiAutomator2 driver 通过 AccessibilityService 的 `TYPE_NOTIFICATION_STATE_CHANGED` 事件把它以 `android.widget.Toast` 节点的形式暴露出来：

```python
# Toast 只存在约 2~3.5 秒，必须立刻用短轮询去抓
toast = WebDriverWait(driver, 5, poll_frequency=0.2).until(
    EC.presence_of_element_located(
        (AppiumBy.XPATH, "//android.widget.Toast")
    )
)
assert toast.get_attribute("text") == "库存不足"
```

前提是 `automationName` 必须是 UiAutomator2（老的 UiAutomator1 不支持）。如果 App 用的是自定义 Toast（本质是 Dialog 或悬浮 View），反而更好抓——它就是普通控件。**抓不到就退而求其次：让开发在 Toast 同时打一行日志，用 `adb logcat` 断言。**

## 可能被追问的点

- **Appium 和 UiAutomator2 直连（如 uiautomator2 库）比，优势劣势是什么？** Appium 胜在跨平台、协议标准、生态成熟（Inspector、云真机平台都支持）；劣势是链路长、慢、依赖 Node 环境。直连库速度快得多，但只能跑 Android，且需要自己处理很多细节。项目里如果只测 Android 且追求速度，直连是合理选择。
- **为什么装 App 之后第一次跑特别慢？** UiAutomator2 driver 要往设备装两个 APK（server 和 test）、启动 instrumentation 进程、建 adb 转发。可以用 `skipServerInstallation` / `skipDeviceInitialization` 在同一设备连续执行时跳过。
- **元素定位不到有哪些常见原因？** ①页面还没渲染完（缺等待）；②元素在 WebView 里没切 context；③被系统弹窗/权限框遮挡；④元素在屏幕外没滚动到；⑤定位用的 `resource-id` 是动态生成的；⑥当前在另一个 Activity（`driver.current_activity` 确认）。
- **iOS 侧链路有什么不同？** Appium 走 XCUITest driver，会在设备上编译安装 **WDA（WebDriverAgent）**，通过 usbmuxd/`iproxy` 做端口转发。iOS 真机必须有开发者证书签名 WDA，这是环境搭建最大的坑。
- **App 启动速度怎么测？** `adb shell am start -W -n pkg/activity` 直接输出 `ThisTime`/`TotalTime`/`WaitTime`；更准的是让开发埋点上报「Application.onCreate 到首屏可交互」；也可以用 `adb shell screenrecord` 录屏后逐帧分析。
- **兼容性测试怎么选机型？** 依据线上真实数据（友盟/神策的机型分布），覆盖 Top 80% 的机型；再按维度补齐：主流 Android 版本各一台、不同厂商 ROM（华为/小米/OPPO/vivo 各一）、不同分辨率与刘海屏、低端机（内存 4G 以下）各一台。剩下的长尾交给云真机平台跑冒烟。

## 结合自己项目的例子

商城中台配套的 C 端 App 上，我负责搭 Appium 自动化，跑核心交易链路 60 条用例。中间踩过一个很典型的坑，正好能串起上面的原理。

**现象**：支付流程的用例在本地跑 100% 通过，接到 Jenkins 上跑就有 40% 概率在「点击确认支付」这一步失败，报 `NoSuchElementException`。

**排查过程**：

1. 先加失败截图钩子。截图显示页面**明明已经渲染出了「确认支付」按钮**，元素却找不到——这就排除了「等待不够」这个最常见的猜测。
2. 用 `driver.page_source` 把失败时的控件树 dump 下来，发现整个支付页在控件树里只是一个 `android.webkit.WebView` 空节点。原来收银台是 H5 实现的。
3. 那为什么本地能过？对比发现本地用的是 debug 包（WebView 开了调试），Jenkins 上拉的是 release 包。`driver.contexts` 在 release 包上只返回 `['NATIVE_APP']`——**WebView 没开 `setWebContentsDebuggingEnabled`，Appium 就发现不了这个 context**。
4. 本地那 60% 的"成功"其实也不是真成功：脚本走的是坐标点击的兜底分支，机型分辨率一致时能蒙对，Jenkins 上挂的模拟器分辨率不同就点空了。

**解法**：

- 推动 Android 同学在**测试渠道包**里打开 WebView 调试开关（release 正式包不开），CI 改为拉测试渠道包。
- 脚本里把坐标兜底全部删掉，改成显式的 context 切换 + CSS 定位，并封装成上下文管理器防止忘记切回：

```python
from contextlib import contextmanager

@contextmanager
def webview(driver, timeout=10):
    end = time.time() + timeout
    ctx = None
    while time.time() < end:
        ctx = next((c for c in driver.contexts if c.startswith("WEBVIEW")), None)
        if ctx:
            break
        time.sleep(0.5)
    assert ctx, f"未找到 WebView context，当前: {driver.contexts}"
    driver.switch_to.context(ctx)
    try:
        yield
    finally:
        driver.switch_to.context("NATIVE_APP")
```

- 顺带做了一次提速：把页面里 17 处 XPath 定位换成 `resource-id` 和 `UiSelector`，单条支付用例从 48 秒降到 19 秒，全量 60 条从 41 分钟降到 17 分钟。

这个案例我很喜欢讲，因为它能同时展示三件事：**懂原理（知道去 dump 控件树、知道 context 机制）、能定位环境差异（debug 包 vs release 包）、以及不满足于「能跑通」（发现坐标点击这种假通过并清理掉）。**

## 参考

- 相关笔记：[[08-App自动化测试]]、[[05-自动化测试框架]]
