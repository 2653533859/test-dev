---
created: 2026-07-31
tags: [App自动化测试/环境]
---

# iOS 自动化环境：Xcode 与 WebDriverAgent

> iOS 自动化的全部难度都在环境上。脚本写法和 Android 几乎一样，但把 WebDriverAgent 成功装进真机，能卡住一整天。

## 概念

### 为什么 iOS 没有 adb 这种东西

Android 提供了 `adbd` 这个官方调试守护进程，PC 可以直接下发系统级命令。iOS 出于封闭策略**没有等价物**：

- 没有官方 shell 通道，不能 `adb shell`；
- 不能随便往设备装 App，任何 App 都必须**用有效的开发者证书签名**；
- 系统级 UI 自动化能力只暴露给 XCUITest 框架，而 XCUITest 只能在 Xcode 的测试 target 里跑。

于是 Appium 的解法是：**做一个 iOS App（WebDriverAgent），把它当作测试 target 用 `xcodebuild` 装进设备并运行，让它在设备内部起一个 HTTP 服务，代替 adbd 的角色。**

```text
Mac 上的 XCUITest Driver
  │  xcodebuild test-without-building -project WebDriverAgent.xcodeproj \
  │            -scheme WebDriverAgentRunner -destination 'id=<udid>'
  ▼
设备内 WebDriverAgentRunner 启动，监听 :8100
  │  通过 usbmuxd（iproxy）把设备 8100 映射到 Mac 本地端口
  ▼
XCUITest Driver 用 HTTP 调 WDA → WDA 调 XCUITest API → 操作被测 App
```

这条链路里，`wdaLocalPort`（默认 8100）就是 Mac 侧那个映射端口，多设备并行时必须每台设备一个。

### 硬性前提

| 前提 | 说明 | 能绕过吗 |
|------|------|---------|
| **一台 Mac** | `xcodebuild` 只在 macOS 上有 | 不能。CI 需要 Mac mini 或云 Mac |
| **Xcode + Command Line Tools** | 编译 WDA | 不能 |
| **Apple 开发者账号** | 给 WDA 签名 | 免费账号可以，但证书 7 天过期 |
| **设备 UDID 已注册**（真机） | 加入开发者账号的设备列表 | 免费账号自动处理，上限 3 台 |
| **设备上信任证书** | 设置 → 通用 → VPN与设备管理 | 不能，必须手点一次 |

**模拟器要简单得多**：不需要真实证书，`xcodebuild` 直接跑，也不用信任步骤。所以「先在模拟器上跑通，再攻真机」是正确的推进顺序。

### 免费账号 vs 付费账号

免费 Apple ID 也能签 WDA，但：

- 证书 **7 天过期**，过期后 WDA 装不上或起不来，得重签；
- 单账号最多 3 台设备、10 个 App ID；
- 无法用于 CI（每周手工重签不现实）。

**做长期回归就买 99 美元/年的开发者账号**，证书一年有效，这钱省不得。

## 用法

### 一、装工具链

```bash
# Xcode（App Store 装，或 xcodes 工具管理多版本）
xcode-select --install
xcodebuild -version

# 设备通信与端口转发工具
brew install libimobiledevice
brew install ios-deploy

# 列出已连接的真机 UDID
idevice_id -l
# 00008030-001A2C3D0E4F002E

# 查设备信息
ideviceinfo -u 00008030-001A2C3D0E4F002E | grep ProductVersion
```

Appium 侧：

```bash
appium driver install xcuitest
appium driver list --installed
appium-doctor --ios        # 一键体检，缺什么它会说
```

### 二、准备 WebDriverAgent（真机的核心步骤）

XCUITest Driver 自带一份 WDA 源码，先找到它：

```bash
# 典型路径
cd ~/.appium/node_modules/appium-xcuitest-driver/node_modules/appium-webdriveragent
# Appium 2.x 也可能在 ~/.appium/appium-xcuitest-driver/node_modules/appium-webdriveragent

open WebDriverAgent.xcodeproj
```

在 Xcode 里对 **两个 target** 都做同样的操作：`WebDriverAgentLib` 和 `WebDriverAgentRunner`

1. Signing & Capabilities → 勾选 **Automatically manage signing**；
2. Team 选你的开发者账号；
3. Bundle Identifier 改成**全局唯一**的值，比如 `com.yourname.WebDriverAgentRunner`（默认那个 `com.facebook.WebDriverAgentRunner` 早被全世界注册过，会报 bundle id 不可用）。

然后命令行验证能不能装上：

```bash
xcodebuild -project WebDriverAgent.xcodeproj \
  -scheme WebDriverAgentRunner \
  -destination 'id=00008030-001A2C3D0E4F002E' \
  test
```

成功的标志是终端输出：

```text
ServerURLHere->http://192.168.1.30:8100<-ServerURLHere
```

**看到这行就成了**。此时手机上会多出一个白色图标的 WebDriverAgentRunner App。

首次运行会失败一次，因为设备还没信任证书：手机 → 设置 → 通用 → VPN与设备管理 → 开发者应用 → 信任。

### 三、验证 WDA 在跑

```bash
# 端口转发：Mac 本地 8100 → 设备 8100
iproxy 8100 8100 &

# 探活
curl http://127.0.0.1:8100/status
# {"value":{"build":{...},"os":{"name":"iOS","version":"17.2"},"ready":true},...}

# 甚至可以直接看设备当前控件树（浏览器打开）
open http://127.0.0.1:8100/inspector
```

### 四、跑第一个用例

```python
import pytest
from appium import webdriver
from appium.options.ios import XCUITestOptions
from appium.webdriver.common.appiumby import AppiumBy


@pytest.fixture()
def driver():
    opts = XCUITestOptions()
    opts.platform_name = "iOS"
    opts.automation_name = "XCUITest"
    opts.platform_version = "17.2"
    opts.device_name = "iPhone 15"
    opts.udid = "00008030-001A2C3D0E4F002E"      # 真机必填；模拟器可省
    opts.bundle_id = "com.apple.Preferences"      # iOS 用 bundleId，不是 appPackage
    opts.set_capability("appium:wdaLocalPort", 8100)
    opts.set_capability("appium:xcodeOrgId", "ABCDE12345")       # 你的 Team ID
    opts.set_capability("appium:xcodeSigningId", "iPhone Developer")
    opts.set_capability("appium:updatedWDABundleId", "com.yourname.WebDriverAgentRunner")
    opts.set_capability("appium:usePrebuiltWDA", True)           # 复用已装好的 WDA，提速
    opts.no_reset = True

    d = webdriver.Remote("http://127.0.0.1:4723", options=opts)
    yield d
    d.quit()


def test_open_settings(driver):
    # iOS 首选 accessibility id（对应 accessibilityIdentifier / label）
    el = driver.find_element(AppiumBy.ACCESSIBILITY_ID, "通用")
    el.click()
    assert driver.find_element(
        AppiumBy.IOS_PREDICATE, 'name == "关于本机"'
    ).is_displayed()
```

### 五、iOS 特有的定位方式

iOS 除了通用策略，还有两种更强的：

```python
from appium.webdriver.common.appiumby import AppiumBy

# iOS Predicate String：类 SQL 的属性过滤，快
driver.find_element(AppiumBy.IOS_PREDICATE, 'type == "XCUIElementTypeButton" AND name CONTAINS "登录"')
driver.find_element(AppiumBy.IOS_PREDICATE, 'label == "确定" AND visible == 1')

# iOS Class Chain：兼顾层级与性能，介于 predicate 与 XPath 之间
driver.find_element(AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeCell[`name CONTAINS "订单"`][2]')
driver.find_element(AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`label == "提交"`]')
```

| 策略 | 性能 | 表达能力 | 建议 |
|------|------|---------|------|
| accessibility id | 最快 | 单一属性 | 首选 |
| iOS Predicate | 快 | 属性组合、模糊匹配 | 次选 |
| iOS Class Chain | 中 | 属性 + 层级 + 索引 | 需要层级时用 |
| XPath | 慢 | 最强 | 最后手段 |

**iOS 上 XPath 比 Android 还慢**，因为 XCUITest 的树遍历本身开销大。能用 predicate 就别用 XPath。

## 踩坑

1. **`xcodebuild failed with code 65`**
   万能报错码，实际原因在上面几十行日志里。高频原因：Bundle ID 冲突、Team 没选、证书过期、设备没信任、Xcode 版本与 iOS 版本不匹配。**必须往上翻日志找 `error:` 那一行**，不要拿 65 去搜索。

2. **Bundle ID 已被占用**
   默认的 `com.facebook.WebDriverAgentRunner` 全网都在用。改成自己的域名反写，并且 `WebDriverAgentLib` 和 `WebDriverAgentRunner` 两个 target 都要改。

3. **免费证书 7 天过期**
   现象是「上周好好的，这周 WDA 起不来」。重新在 Xcode 里 build 一次即可，但这决定了免费账号不能上 CI。

4. **设备锁屏 / 未信任电脑**
   WDA 无法在锁屏状态下安装。跑之前解锁并在设备上点「信任此电脑」。CI 环境要把自动锁屏关掉：设置 → 显示与亮度 → 自动锁定 → 永不。

5. **`usePrebuiltWDA` 用错时机**
   它跳过编译直接用设备上已有的 WDA，能把 session 建立时间从 60 秒降到 10 秒。但**换了 Xcode 版本、换了设备、WDA 被卸载后必须先关掉它跑一次完整编译**，否则报「WDA not found」。

6. **多设备并行端口冲突**
   每台设备必须独立的 `wdaLocalPort`（8100、8101、8102…）和独立的 `mjpegServerPort`（截屏流端口，默认 9100）。不然第二台设备的 session 会连到第一台的 WDA 上，出现「操作打在了另一台手机上」这种诡异现象。

7. **模拟器上通过、真机上失败**
   常见于权限弹窗（真机才弹）、键盘（真机弹软键盘会遮挡元素，模拟器默认用电脑键盘不弹）、性能（真机慢，等待要更长）。**iOS 的软键盘遮挡问题比 Android 严重**，建议 capabilities 里加 `appium:connectHardwareKeyboard: false` 让模拟器也弹软键盘，暴露问题。

8. **`Could not connect to WDA` / 8100 端口不通**
   先手动 `iproxy 8100 8100` 加 `curl /status` 确认 WDA 本身活着。若 WDA 活着但 Appium 连不上，通常是 `wdaLocalPort` 配置和实际转发端口不一致。

9. **iOS 权限弹窗必须处理**
   通知、定位、相机权限弹窗是**系统级 Alert**，不在 App 控件树里。用 `appium:autoAcceptAlerts: true` 自动点允许，或 `autoDismissAlerts` 自动拒绝。注意这两个是二选一，而且一旦开启会拦截所有 alert，包括你想断言的业务弹窗。

10. **Xcode 升级把环境搞崩**
    Xcode 大版本升级后 WDA 常需重新编译，有时还要更新 `appium-xcuitest-driver`。**团队里应该锁定 Xcode 版本**，像锁定依赖版本一样管理。

## 面试怎么答

**Q：iOS 自动化和 Android 有什么区别？**
A：脚本层面几乎一样，都是 W3C WebDriver 那套 API，换个 `automationName` 和 capabilities 就行。区别全在底层和环境。Android 有 adb 这个官方调试通道，Appium 往设备里装一个 server apk 用 `am instrument` 拉起来就能干活；iOS 没有 adb，Appium 得靠 WebDriverAgent——一个用 XCUITest 框架写的 iOS App，必须用 `xcodebuild` 编译、用有效开发者证书签名、装进设备跑起来，它在设备内监听 8100 端口，再通过 usbmuxd 映射到 Mac 本地。所以 iOS 自动化必须有 Mac、有 Xcode、有开发者账号，环境成本高得多。定位策略上 iOS 多了 predicate string 和 class chain 两种，都比 XPath 快。

**Q：WebDriverAgent 是什么，为什么它老出问题？**
A：WDA 是 Appium 在 iOS 设备上的执行代理，本质是一个 XCUITest 测试 target。它出问题的根源是 iOS 的签名机制：每次装 WDA 都要过一遍签名和信任流程，证书会过期、Bundle ID 会冲突、设备要手动信任、Xcode 升级后要重编。这些都不是 Appium 的 bug，是苹果的封闭策略带来的固有成本。实践上我会做三件事降低痛苦：用付费开发者账号避免证书 7 天过期；配 `usePrebuiltWDA` 复用已装好的 WDA，把 session 建立时间从一分钟降到十几秒；团队锁定 Xcode 版本，不要各人各版本。

**Q：iOS 上元素定位你怎么选？**
A：优先 accessibility id，对应开发在代码里设的 `accessibilityIdentifier`，最快也最稳。需要组合条件时用 iOS Predicate String，比如 `type == "XCUIElementTypeButton" AND label CONTAINS "登录"`，语法像 SQL，性能远好于 XPath。需要层级和索引时用 Class Chain。XPath 放在最后——iOS 上 XPath 比 Android 还慢，因为 XCUITest 遍历控件树本身就重，一次查找一两秒很常见。治本还是推动开发给关键控件加 `accessibilityIdentifier`，这和 Web 端约定 `data-testid` 是一回事。

## 参考

- [Appium · XCUITest Driver](https://appium.github.io/appium-xcuitest-driver/latest/)
- [WebDriverAgent 项目](https://github.com/appium/WebDriverAgent)
- [Apple · XCUITest 文档](https://developer.apple.com/documentation/xctest/user-interface-tests)
- 相关笔记：[[Appium 架构原理与工作流程]]
- 相关笔记：[[Appium Desired Capabilities 详解]]
- 相关笔记：[[Appium 控件定位策略]]
- 相关笔记：[[08-App自动化测试]]
