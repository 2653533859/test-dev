---
created: 2026-07-31
tags: [App自动化测试/定位]
---

# Android Toast 捕获方案

> Toast 是 Android 上那种「底部弹一下、2 秒自动消失」的轻提示。它不在控件树里常驻，抓不到就证明不了「密码错误」这类校验逻辑，是面试常客。

## 概念

### Toast 为什么难抓

Toast 本质是 `Toast.show()` 用 `WindowManager` 加的一个 `TYPE_APPLICATION_OVERLAY` 悬浮窗，**不走普通 View 树**，且默认约 2 秒后 `cancel`。UiAutomator2 的常规 `findElement` 是基于 Accessibility 节点快照的，Toast 出现窗口极短，常规轮询很容易错过。

### 两条可行路径

1. **UiAutomator2 的 `AppiumBy.ANDROID_UIAUTOMATOR` 表达式**：UiAutomator2 在 2.0+ 支持了 `UiSelector().text()` 对 Toast 的 `text` 匹配，表达式里用 `className("android.widget.Toast")`，这是最干净的方案。
2. **logcat 抓取**：Toast 展示时系统会打印一条 `NotificationManager` 相关日志，从 `adb logcat` 里捞，但依赖系统实现、不保证有，仅作兜底。

## 用法

### 一、首选：UiAutomator2 表达式匹配（稳定）

```python
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 等 Toast 出现并断言文案
toast = WebDriverWait(driver, 5).until(
    EC.presence_of_ELEMENT(
        (AppiumBy.ANDROID_UIAUTOMATOR,
         'new UiSelector().className("android.widget.Toast")')
    )
)
assert "密码错误" in toast.text
```

关键点：`WebDriverWait` 的 timeout 要大于 Toast 存活时间（2 秒），且用 `presence_of_ELEMENT` 而非 `visibility`（Toast 可能 `displayed=false`）。

### 二、按文本模糊匹配 Toast

```python
# 只关心文案含某关键字（不限定完整文本）
toast = driver.find_ELEMENT(
    AppiumBy.ANDROID_UIAUTOMATOR,
    'new UiSelector().className("android.widget.Toast").textContains("失败")'
)
```

`textContains` / `textStartsWith` 在文案偶尔变体时更稳。

### 三、封装成通用断言

```python
def assert_toast(driver, keyword, timeout=5):
    locator = (AppiumBy.ANDROID_UIAUTOMATOR,
               f'new UiSelector().className("android.widget.Toast").textContains("{keyword}")')
    try:
        el = WebDriverWait(driver, timeout).until(EC.presence_of_ELEMENT(locator))
        return keyword in el.text
    except Exception:
        return False
```

### 四、logcat 兜底（不推荐主用）

```python
# 监听 logcat，Toast 展示常带 'Toast' 标记
lines = adb.logcat(filter_spec="'*:S' Tag:MyApp", timeout=3)
assert any("密码错误" in ln for ln in lines)
```

## 踩坑

1. **`find_ELEMENT` 直接抓 Toast 十次有九次空**：Toast 存活 2 秒且不在常驻树里，同步 `find` 命中的概率极低。必须 `WebDriverWait` + `presence_of_ELEMENT` 轮询。
2. **用 XPath `//android.widget.Toast` 抓不到**：XPath 基于当前快照 dump，Toast 出现窗口短，dump 时刻往往已消失。改用 `ANDROID_UIAUTOMATOR` 表达式，它在设备侧实时匹配，命中率高得多。
3. **`appium:automationName` 不是 `UiAutomator2`**：只有 UiAutomator2 driver 支持 `className("android.widget.Toast")`，用老的 `Appium`/`UiAutomator` driver 直接失效。Android 自动化必须 `UiAutomator2`。
4. **`timeout` 设成 2 秒以下**：Toast 存活约 2 秒，刚出现你这头才开始等，窗口过窄。timeout 设 5 秒更稳。
5. **用 `visibility_of_ELEMENT` 而非 `presence`**：Toast 的 `displayed` 状态在部分 ROM 上为 false，可见性条件永不满足。用 `presence_of_ELEMENT` 即可。
6. **iOS 根本没有 Toast 概念**：iOS 的 HUD/提示是 App 自己实现的 UIView，不能用 `android.widget.Toast`。要按普通控件 `find_ELEMENT` 抓，或让开发给提示加上稳定 `accessibilityIdentifier`。
7. **自定义 Toast（如 Snackbar）不是系统 Toast**：`Snackbar` 是普通 `View`，正常 `find_ELEMENT(AppiumBy.ID, ...)` 即可，别套 `className("android.widget.Toast")`，会落空。
8. **多 Toast 快速连发只抓到最后一条**：轮询期间若连续弹多条，表达式只匹配当前节点。需要逐条校验时，应在每次操作后单独等、单独断言。
9. **断言后 Toast 还没消失就做下一步操作**：Toast 覆盖在按钮上可能导致点击被吞。断言完 `time.sleep(2)` 等其消失或点空白处先消掉。
10. **`textContains` 注入特殊字符报错**：文案含单引号会破坏 UiSelector 字符串，需要转义或改用 `textMatches` + 正则。

## 面试怎么答

**30 秒骨架**：Toast 是 `WindowManager` 挂的悬浮窗，不进普通控件树且约 2 秒消失，常规 `findElement` 抓不到。正确做法是用 UiAutomator2 driver，配 `AppiumBy.ANDROID_UIAUTOMATOR` 表达式 `new UiSelector().className("android.widget.Toast")`，再用 `WebDriverWait` + `presence_of_ELEMENT` 轮询，timeout 设 5 秒。XPath 和同步 find 基本抓不到，iOS 没有系统 Toast 要按普通控件处理。

**追问**：为什么非得 UiAutomator2？——只有它在设备侧实时匹配无障碍节点，表达式在设备内执行，能赶上 Toast 短暂的存活窗口；XPath 要 dump 整树回传，早就错过了。

## 参考

- [UiAutomator2 Toast 支持说明](https://github.com/appium/appium-uiautomator2-server)
- 相关笔记：[[Appium 控件定位策略]]、[[Appium Inspector 元素检查与定位调试]]、[[adb logcat 日志抓取与崩溃定位]]
