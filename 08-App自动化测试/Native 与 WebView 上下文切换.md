---
created: 2026-07-31
tags: [App自动化测试/混合应用]
---

# Native 与 WebView 上下文切换

![[assets/native-webview-context.svg]]
*图示：同一块屏幕上原生控件与 H5 页面共存，但分属两套完全不同的控件树——NATIVE_APP 走无障碍节点，WEBVIEW 走 Chrome DevTools 协议，必须显式切换才能看到对方。*

> 「元素明明在屏幕上，脚本就是找不到」——混合应用里，这句话十次有八次是上下文没切。

## 概念

### 什么是 context

Appium 的 **context（上下文）** 表示「当前命令作用在哪一套控件体系上」：

| context 值 | 底层 | 定位方式 | page_source |
|-----------|------|---------|------------|
| `NATIVE_APP` | UiAutomator2 / XCUITest 读无障碍树 | resource-id、UiSelector | XML |
| `WEBVIEW_com.demo.app` | Chrome DevTools Protocol（Android）/ Safari 远程调试（iOS） | CSS、XPath | HTML |

**关键点：两套树互不可见。** 在 `NATIVE_APP` 上下文里，一个 WebView 只是一个 `android.webkit.WebView` 节点，里面的 div、button 全都看不到；切到 `WEBVIEW_xxx` 后反过来，原生的标题栏、TabBar 全都消失。

### 三类 App 形态

| 类型 | 构成 | 定位方式 |
|------|------|---------|
| **Native** | 全部原生控件 | 只用 NATIVE_APP |
| **Hybrid（混合）** | 原生外壳 + WebView 嵌 H5 | 需要来回切换 |
| **Web App** | 纯浏览器里的移动网页 | 直接用 `browserName: Chrome`，等同 Selenium |

现在电商、金融 App 大量采用混合方案（活动页、营销页、H5 商详用 WebView，主框架用原生），**所以上下文切换是必备技能而不是边角知识**。

### Android 侧的实现机制

切到 WebView 时，Appium 做了这些事：

```text
① 通过 adb 读取 /proc/net/unix，找出设备上所有 WebView 的 devtools socket
     @webview_devtools_remote_<pid>
② 用 adb forward 把这个 unix socket 映射到 PC 的一个端口
③ 访问 http://localhost:<port>/json/list 拿到页面列表（title、url、webSocketDebuggerUrl）
④ 启动一个匹配版本的 chromedriver，让它接管这个 WebView
⑤ 之后所有命令走 chromedriver → CDP → WebView
```

**两个硬性前提**：

1. **App 必须开启 WebView 调试**：开发要在代码里调 `WebView.setWebContentsDebuggingEnabled(true)`。Release 包通常关着，所以自动化要用 debug 包或专门的测试包。这是「contexts 里只有 NATIVE_APP」最常见的原因。
2. **chromedriver 版本要匹配设备的 WebView（Chrome）内核版本**。Appium 会尝试自动下载，内网环境下要手动准备。

## 用法

### 一、查看与切换

```python
# 当前所有可用上下文
print(driver.contexts)
# ['NATIVE_APP', 'WEBVIEW_chrome', 'WEBVIEW_com.demo.app']

print(driver.current_context)      # 'NATIVE_APP'

driver.switch_to.context("WEBVIEW_com.demo.app")
# 此刻可以用纯 Web 的方式操作
driver.find_element(AppiumBy.CSS_SELECTOR, "#submit-btn").click()

driver.switch_to.context("NATIVE_APP")     # 一定记得切回来
```

### 二、稳健的切换封装（生产可用）

裸调 `driver.contexts` 会踩两个坑：WebView 还没加载完时列表里没有它；多 WebView 时不知道该切哪个。下面这个封装解决两者：

```python
import time
from selenium.common.exceptions import WebDriverException


class ContextHelper:
    NATIVE = "NATIVE_APP"

    def __init__(self, driver, timeout: int = 20, interval: float = 0.5):
        self.driver = driver
        self.timeout = timeout
        self.interval = interval

    def wait_for_webview(self) -> str:
        """轮询等 WebView 上下文出现，返回其名字。"""
        deadline = time.time() + self.timeout
        last = []
        while time.time() < deadline:
            last = self.driver.contexts
            webviews = [c for c in last if c.startswith("WEBVIEW")]
            if webviews:
                return webviews[-1]      # 通常最后一个是最新打开的
            time.sleep(self.interval)
        raise TimeoutError(f"{self.timeout}s 内未出现 WebView 上下文，当前：{last}")

    def switch_to_webview_by_url(self, keyword: str) -> str:
        """一个 App 有多个 WebView 时，按 URL 关键字挑正确的那个。"""
        self.wait_for_webview()
        for ctx in self.driver.contexts:
            if not ctx.startswith("WEBVIEW"):
                continue
            try:
                self.driver.switch_to.context(ctx)
            except WebDriverException:
                continue
            # 切进去后还可能有多个 window handle（多个 H5 页面）
            for handle in self.driver.window_handles:
                self.driver.switch_to.window(handle)
                if keyword in (self.driver.current_url or ""):
                    return ctx
        self.driver.switch_to.context(self.NATIVE)
        raise RuntimeError(f"未找到 URL 含 '{keyword}' 的 WebView")

    def switch_to_native(self) -> None:
        if self.driver.current_context != self.NATIVE:
            self.driver.switch_to.context(self.NATIVE)
```

**`window_handles` 那一层容易被忽略**：切到 WEBVIEW 上下文后，里面可能还有多个页面（iframe、新开的 tab），要再切 window。这是「切了 context 还是找不到元素」的隐藏原因。

### 三、用上下文管理器保证一定切回来

忘记切回原生是高频错误。用 `with` 从语法上杜绝：

```python
from contextlib import contextmanager


@contextmanager
def in_webview(driver, helper: ContextHelper, url_keyword: str = ""):
    """在 with 块里处于 WebView 上下文，退出时无论成败都切回原生。"""
    origin = driver.current_context
    if url_keyword:
        helper.switch_to_webview_by_url(url_keyword)
    else:
        driver.switch_to.context(helper.wait_for_webview())
    try:
        yield driver
    finally:
        driver.switch_to.context(origin)


# 使用
from appium.webdriver.common.appiumby import AppiumBy

helper = ContextHelper(driver)

driver.find_element(AppiumBy.ID, "com.demo.app:id/banner_activity").click()   # 原生：点进活动页

with in_webview(driver, helper, url_keyword="/promotion"):
    driver.find_element(AppiumBy.CSS_SELECTOR, "input[name=phone]").send_keys("13800000000")
    driver.find_element(AppiumBy.CSS_SELECTOR, ".btn-submit").click()
    assert "领取成功" in driver.page_source

# 出了 with 自动回到 NATIVE_APP
driver.find_element(AppiumBy.ACCESSIBILITY_ID, "back").click()                # 原生：点返回
```

上下文管理器的写法参考 [[Python 上下文管理器]]，这类「必须成对出现」的操作都适合这么封装。

### 四、chromedriver 版本匹配

```bash
# 查设备上 WebView 的内核版本
adb shell dumpsys package com.google.android.webview | grep versionName
# versionName=120.0.6099.230

# 国产 ROM 可能是自己的内核
adb shell dumpsys package com.android.webview | grep versionName
adb shell pm list packages | grep -i webview
```

准备本地 chromedriver 目录，让 Appium 按需匹配：

```python
opts.set_capability("appium:chromedriverExecutableDir", "/opt/chromedrivers")
opts.set_capability("appium:chromedriverChromeMappingFile", "/opt/chromedrivers/mapping.json")
# 或者指定单个可执行文件
opts.set_capability("appium:chromedriverExecutable", "/opt/chromedrivers/chromedriver_120")
# 联网环境可让 Appium 自动下载
opts.set_capability("appium:chromedriverAutodownload", True)
```

`mapping.json` 格式：

```json
{
  "120.0.6099.230": "/opt/chromedrivers/chromedriver_120",
  "114.0.5735.196": "/opt/chromedrivers/chromedriver_114"
}
```

### 五、混合页面的 Page Object 怎么写

关键是**把「切上下文」这件事封在页面对象内部，用例层完全不感知**：

```python
class PromotionPage:
    """活动页���外壳是原生，主体是 H5。"""

    NATIVE_BACK = (AppiumBy.ACCESSIBILITY_ID, "back")
    NATIVE_TITLE = (AppiumBy.ID, "com.demo.app:id/tv_title")
    H5_PHONE = (AppiumBy.CSS_SELECTOR, "input[name=phone]")
    H5_SUBMIT = (AppiumBy.CSS_SELECTOR, ".btn-submit")
    H5_RESULT = (AppiumBy.CSS_SELECTOR, ".result-toast")

    def __init__(self, driver):
        self.driver = driver
        self.ctx = ContextHelper(driver)

    def title(self) -> str:
        self.ctx.switch_to_native()
        return self.driver.find_element(*self.NATIVE_TITLE).text

    def claim(self, phone: str) -> str:
        with in_webview(self.driver, self.ctx, "/promotion"):
            self.driver.find_element(*self.H5_PHONE).send_keys(phone)
            self.driver.find_element(*self.H5_SUBMIT).click()
            return self.driver.find_element(*self.H5_RESULT).text

    def go_back(self) -> None:
        self.ctx.switch_to_native()
        self.driver.find_element(*self.NATIVE_BACK).click()
```

用例层就是纯业务语义：

```python
def test_claim_coupon(driver):
    page = PromotionPage(driver)
    assert page.title() == "限时活动"
    assert "领取成功" in page.claim("13800000000")
    page.go_back()
```

### 六、绕过上下文切换的两个替代方案

切换本身有成本（首次要起 chromedriver，一两秒），有时可以绕开：

```python
# 方案一：小程序 / 简单 H5，直接在 WebView 里执行 JS（仍需在 WEBVIEW 上下文）
with in_webview(driver, helper):
    driver.execute_script("document.querySelector('.btn-submit').click()")
    text = driver.execute_script("return document.querySelector('.total').innerText")

# 方案二：H5 内容能通过接口验证时，UI 只验「进得去」，数据用接口断言
#         这往往是更划算的选择 —— 混合页面的 UI 自动化投入产出比通常很差
```

**方案二值得强调**：H5 活动页迭代极快、DOM 结构随时变，为它写大量 UI 用例是负收益。合理的策略是 UI 层只保证「从原生能正确进入 H5 并回来」，H5 内部的业务逻辑用接口测试覆盖。

## 踩坑

1. **`contexts` 里只有 `NATIVE_APP`**
   最常见的三个原因：App 没开 `setWebContentsDebuggingEnabled(true)`（release 包默认关，找开发要 debug 包）；WebView 还没加载完（要轮询等）；设备是国产 ROM 用了自研内核，devtools socket 不标准。

2. **切了 context 还是找不到元素**
   WEBVIEW 上下文里可能有多个 window handle。切完 context 要遍历 `driver.window_handles`，按 `current_url` 挑对的那个。

3. **多个 WebView 切错了**
   App 里内嵌广告 SDK、客服 SDK 都会创建 WebView，`contexts` 里好几项。按 URL 或 title 精确匹配，不要盲取第一个或最后一个。

4. **忘记切回 NATIVE_APP**
   后续所有原生元素定位全部失败，报错还很误导（说找不到 id）。用上下文管理器强制切回。

5. **chromedriver 版本不匹配**
   报 `Chrome version must be between X and Y` 或 `no chrome binary at ...`。准备本地 chromedriver 池 + mapping 文件；CI 内网环境必须预先准备好，不能依赖自动下载。

6. **iOS 的 WebView 更麻烦**
   iOS 走 Safari 远程调试协议，需要 `ios-webkit-debug-proxy`（`brew install ios-webkit-debug-proxy`），且设备上要开 设置 → Safari → 高级 → 网页检查器。WKWebView 与 UIWebView 行为也有差异。

7. **切换耗时被低估**
   首次切到 WebView 要启动 chromedriver，一两秒起。在循环里反复切换会拖垮用例耗时。**一次切换里把所有 H5 操作做完**，别切来切去。

8. **H5 页面用了 iframe**
   切到 WEBVIEW 上下文后，如果元素在 iframe 里还要 `driver.switch_to.frame(...)`，逻辑同 Web 端，见 [[iframe 与 Shadow DOM 切换]]。

9. **原生和 H5 的坐标系不同**
   在 WEBVIEW 上下文里拿到的元素坐标是 CSS 像素，原生是设备像素，两者差一个 devicePixelRatio。想在 WebView 元素上做原生手势（比如长按）要做换算，很容易算错。

10. **用 `page_source` 判断在哪个上下文**
    这是个好习惯：XML 开头是 `<hierarchy>` 说明在原生，HTML 开头是 `<html>` 说明在 WebView。调试时先打印一下能省很多猜测。

## 面试怎么答

**Q：原生控件和 WebView 控件怎么区分？上下文如何切换？**
A：先说怎么区分：在 Appium Inspector 或者 `page_source` 里看，如果那块区域是一个 `android.webkit.WebView` 节点、里面一片空白点不进去，那就是 WebView；如果能看到具体的 Button、TextView 层级，就是原生。更直接的办法是打印 `driver.contexts`，如果返回里有 `WEBVIEW_包名` 这一项，说明当前页面有 WebView。切换用 `driver.switch_to.context("WEBVIEW_com.demo.app")`，切完之后定位方式就变成纯 Web 那一套 CSS 选择器和 XPath，`page_source` 也从 XML 变成 HTML。操作完必须 `switch_to.context("NATIVE_APP")` 切回来，否则后续原生元素全部找不到。工程上我会用 Python 的上下文管理器封装，`with in_webview(driver):` 进去、出块自动切回，从语法上杜绝忘记切回的问题。

**Q：`contexts` 里只有 NATIVE_APP，怎么办？**
A：三个方向排查。第一，也是最常见的，App 没开 WebView 调试开关——开发要在代码里调 `WebView.setWebContentsDebuggingEnabled(true)`，release 包一般是关的，所以自动化要用 debug 包。第二，时序问题，页面刚跳转过去 WebView 还没初始化完，`contexts` 里自然没有，要写轮询等待，我一般给 20 秒超时、500 毫秒轮询一次。第三，设备用的是厂商自研 WebView 内核，devtools socket 名字不标准，Appium 扫不到，这种情况可以手动 `adb shell cat /proc/net/unix | grep devtools` 确认到底有没有。

**Q：切到 WebView 后还是找不到元素呢？**
A：两种情况。一是 WEBVIEW 上下文里有多个 window handle，App 里内嵌了广告 SDK 或客服 SDK 的话会有好几个 H5 页面，切完 context 还要遍历 `driver.window_handles` 按 `current_url` 挑对的那个。二是元素在 iframe 里，还要再 `switch_to.frame`，这和 Web 端逻辑一样。调试时我会先打印 `page_source` 的前几百个字符，看开头是 `<hierarchy>` 还是 `<html>`，能立刻确认自己到底在哪一层。

**Q：混合应用的 UI 自动化你怎么做取舍？**
A：我不会给 H5 部分写大量 UI 用例。H5 活动页的迭代速度是原生的好几倍，DOM 结构说变就变，加上上下文切换本身有一两秒开销、chromedriver 版本还要维护，投入产出比很差。我的策略是分层：UI 自动化只覆盖「从原生正确进入 H5、H5 里完成关键动作后能正确回到原生」这条链路，也就是验证壳和内容的衔接；H5 内部的业务逻辑和数据正确性交给接口测试覆盖，那一层稳定得多也快得多。这个取舍本质上还是测试金字塔那套思路，能用低层次测试覆盖的就别放到 UI 层。

## 参考

- [Appium · Hybrid Apps 与上下文](https://appium.io/docs/en/latest/guides/context/)
- [Chrome · Remote debugging WebViews](https://developer.chrome.com/docs/devtools/remote-debugging/webviews)
- 相关笔记：[[WebView H5 调试：chrome-inspect 实战]]
- 相关笔记：[[Appium 控件定位策略]]
- 相关笔记：[[iframe 与 Shadow DOM 切换]]
- 相关笔记：[[Python 上下文管理器]]
- 相关笔记：[[08-App自动化测试]]
