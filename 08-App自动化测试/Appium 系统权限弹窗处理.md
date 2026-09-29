---
created: 2026-07-31
tags: [App自动化测试/弹窗]
---

# Appium 系统权限弹窗处理

> 首次启动 App，系统弹个「允许访问相册/定位/通知」的权限框，这是系统级弹窗，不属于 App 的控件树。处理不好，用例全卡在启动页。

## 概念

### 权限弹窗的三种来源

1. **Android 运行时权限（Runtime Permission）**：6.0+ 的 `dangerous` 权限（相机、定位、通讯录等），首次触发时由 `com.android.packageinstaller` 弹出，属于**系统 UI**，不在被测 App 的 activity 里。
2. **iOS 隐私授权框**：首次访问相册/定位/相机时由系统弹，同样脱离 App 控件树。
3. **厂商定制弹窗**：小米/华为/OV 在自家的 `permissioncontroller` 之上还会叠一层「是否允许一直允许/仅使用中允许」，文案和层级各厂商不同，这是兼容性噩梦。

### 为什么不能直接 `find` 它

弹窗由系统进程渲染，你的 `driver` 当前 session 绑定的是被测 App 的 context，默认**看不到系统弹窗的节点**（除非用 UiAutomator2 的全局选择器，但跨进程节点不稳定）。所以主流方案是「**提前授权**」而非「**运行时点掉**」。

## 用法

### 一、首选：capabilities 里预授权（Android）

```yaml
# 直接给 App 预授予危险权限，启动时不弹框
appium:autoGrantPermissions: true
# 更彻底：不弹任何权限框（部分 driver 支持）
appium:noReset: true
```

`autoGrantPermissions` 让 Appium 在 install 后通过 `adb shell pm grant` 把 `AndroidManifest` 里声明的危险权限一次性授予，从源头不弹窗。

### 二、iOS：用 `autoAcceptAlerts`

```yaml
appium:autoAcceptAlerts: true     # 自动点「允许」
# 或只接受系统权限框、自己业务弹窗不点
appium:autoDismissAlerts: false
```

iOS 上 WDA 能识别系统 alert，`autoAcceptAlerts` 会在 alert 出现时自动点第一个按钮（通常是「允许」）。要拒绝用 `autoDismissAlerts`。

### 三、运行时兜底：显式点掉

当 `autoGrantPermissions` 覆盖不到（如某些厂商二次弹窗），需要用例里点：

```python
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def handle_permission_dialog(driver, timeout=5):
    """出现系统权限框就点允许，没出现就跳过"""
    markers = ["允许", "始终允许", "仅在使用期间允许", "OK", "Allow"]
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: any(m in d.page_source for m in markers)
        )
    except Exception:
        return  # 没弹窗，正常往下走
    for txt in markers:
        try:
            el = driver.find_ELEMENT(AppiumBy.XPATH, f"//*[@text='{txt}']")
            if el.is_displayed():
                el.click(); return
        except Exception:
            continue
```

### 四、Android 用 adb 直接授权（CI 最稳）

```bash
# 授予单个权限
adb shell pm grant com.xxx.app android.permission.CAMERA
# 授予所有声明过的危险权限
adb shell pm grant com.xxx.app $(adb shell dumpsys package com.xxx.app | grep -A20 "requested permissions" | grep android.permission | tr '\n' ' ')
```

这完全绕开弹窗，适合 CI 固定设备。

## 踩坑

1. **只开 `autoGrantPermissions` 漏了厂商二次弹窗**：小米的「始终允许」是额外一层，`autoGrantPermissions` 只管标准 runtime permission，厂商框照弹。需要配合运行时兜底策略。
2. **`autoAcceptAlerts` 把业务弹窗也点了**：iOS 上 `autoAcceptAlerts` 是不管三七二十一点第一个按钮，如果某个业务确认框第一个按钮是「取消」，会被误点。关键流程别依赖它，改用显式判定。
3. **点权限框用 `page_source` 却匹配到 App 内同名文案**：比如 App 自己也有「允许」按钮。要限定在系统包名下找，或优先用 `resource-id` 如 `com.android.packageinstaller:id/permission_allow_button`。
4. **弹窗出现时机不确定导致偶发卡住**：有的机子冷启 2 秒弹，有的 5 秒。`WebDriverWait` 的 timeout 设太短会漏点，设太长又拖慢正常用例。建议封装成 autouse fixture，每个用例开始前先尝试清一次。
5. **`pm grant` 对 `normal`/`signature` 权限无效且报错**：只有 `dangerous` 权限能 grant，普通权限默认就给，强行 grant 报 `not a changeable permission`，属正常，忽略即可。
6. **`noReset:true` 下权限被持久化，但换包覆盖安装后失效**：重新 `install -r` 若清了 data，权限回到未授权。CI 里每次 install 后都应重新 `pm grant`。
7. **Android 12+ 的「近似/精确位置」双档弹窗**：选精确位置要点两次才能到底，兜底策略只点一次会卡在第二层。需循环点直到 `page_source` 不再含权限关键词。
8. **iOS 升级后 alert 按钮文案变化**（如 `允许`→`允许访问`），关键词表要随系统版本维护，建议同时匹配英文 fallback。
9. **横屏下权限框按钮坐标偏移导致点错**：优先用 `find_ELEMENT` 定位按钮而非坐标点击。
10. **通知权限框在 Android 13 才成为 runtime permission**：老机型不弹，新机型必弹，同一套用例在不同系统版本表现不一致，自动化要按 API level 分支处理。

## 面试怎么答

**30 秒骨架**：系统权限弹窗是系统进程渲染的，不在被测 App 的控件树里，最好从源头规避——Android 用 `autoGrantPermissions` 或 `adb pm grant` 预授权，iOS 用 `autoAcceptAlerts`（但会无差别点第一个按钮，关键流程慎用）。运行时兜底再封装一个 `handle_permission_dialog`，监听「允许/始终允许」等关键词，弹了就点、没弹就跳过，并做成 autouse fixture。

**追问**：为什么不直接 find 弹窗点？——系统弹窗跨进程，driver 默认看不到稳定节点，且厂商定制层各异，运行时点成本高、易碎，预授权才是最稳解。

## 参考

- [Appium Capabilities: autoGrantPermissions](https://appium.io/docs/en/latest/guides/caps/)
- 相关笔记：[[Appium Desired Capabilities 详解]]、[[App UI 自动化稳定性治理]]、[[adb 常用命令详解]]
