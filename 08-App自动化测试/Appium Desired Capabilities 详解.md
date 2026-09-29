---
created: 2026-07-31
tags: [App自动化测试/Appium]
---

# Appium Desired Capabilities 详解

> capabilities 是你和 Appium Server 之间唯一的「配置协议」。90% 的「session 起不来」都是这里写错了。

![[assets/capabilities-matching.svg]]
*图示：capabilities 四类字段（通用 / App 定位 / 会话行为 / 平台特有）各管一件事，POST /session 的路由流程（platformName 选 driver → automationName → udid 连设备 → app 起应用），以及 noReset / 默认 / fullReset 三档重置策略的隔离级别。*

## 概念

### 它到底是什么

capabilities 是创建 session 时 **POST /session 请求体里的那个 JSON**，告诉 Server 三件事：

1. 我要测什么平台、哪台设备（选 driver、选设备）；
2. 我要测哪个 App（装包、启动）；
3. 我希望这次会话有哪些行为（是否重置、是否自动授权、超时多久）。

它是**一次性的**：session 建立后不能改。想改行为只能销毁 session 重建。

### W3C 格式与 `appium:` 前缀

Appium 2.x 严格遵循 W3C WebDriver 规范。规范只定义了少数标准字段（`platformName`、`browserName`、`browserVersion`、`acceptInsecureCerts` 等），**其余全部是厂商扩展，必须带 `appium:` 前缀**：

```json
{
  "capabilities": {
    "alwaysMatch": {
      "platformName": "Android",
      "appium:automationName": "UiAutomator2",
      "appium:deviceName": "emulator-5554",
      "appium:appPackage": "com.demo.app"
    },
    "firstMatch": [{}]
  }
}
```

漏了前缀会报 `Bad parameters` 或 `invalid argument: The capabilities object is not valid`。

**Python 里不要手写 dict**，用 Options 对象，它会自动加前缀：

```python
from appium.options.android import UiAutomator2Options

opts = UiAutomator2Options()
opts.platform_name = "Android"          # 标准字段，无前缀
opts.app_package = "com.demo.app"       # 自动变成 appium:appPackage
opts.set_capability("appium:systemPort", 8201)   # 没有对应属性的用这个
```

### 四大类字段

| 类别 | 作用 | 代表字段 |
|------|------|---------|
| **通用** | 选平台与 driver | `platformName`、`automationName`、`deviceName`、`udid` |
| **App 定位** | 装哪个包、起哪个页 | `app`、`appPackage`、`appActivity`、`bundleId` |
| **会话行为** | 重置策略、超时 | `noReset`、`fullReset`、`newCommandTimeout` |
| **平台特有** | 各 driver 独有 | `systemPort`、`unicodeKeyboard`、`wdaLocalPort` |

## 用法

### 通用字段

```python
opts.platform_name = "Android"           # 必填。Android / iOS
opts.automation_name = "UiAutomator2"    # 必填。决定用哪个 driver
opts.device_name = "emulator-5554"       # Android 上其实只是个标签
opts.udid = "R5CT30XXXXX"                # 真正唯一标识设备，多设备必填
opts.platform_version = "13"             # 选做，写了会做版本校验
opts.new_command_timeout = 300           # 多久没新命令就自动结束 session（秒）
```

**`deviceName` 与 `udid` 的区别是高频误区**：Android 上 `deviceName` 基本被忽略（写什么都行），真正决定连哪台设备的是 `udid`。只连一台设备时可以不写 `udid`，多设备时不写就是随机连一台。

### App 定位：三种起 App 的方式

```python
# 方式一：给 apk 路径，Appium 负责安装并启动（CI 上常用）
opts.app = "/builds/artifacts/demo-release.apk"      # 也支持 http URL

# 方式二：App 已装在设备上，只需启动（本地调试最常用，最快）
opts.app_package = "com.demo.app"
opts.app_activity = ".ui.SplashActivity"

# 方式三：iOS
opts.bundle_id = "com.demo.app"          # iOS 用 bundleId
```

怎么查 `appPackage` 和 `appActivity`：

```bash
# 手动打开 App 后，查当前前台页面
adb shell dumpsys window | grep mCurrentFocus
# mCurrentFocus=Window{... com.demo.app/com.demo.app.ui.SplashActivity}

# 或者从 apk 里解析
aapt dump badging demo.apk | grep -E "package:|launchable-activity:"
```

**`appActivity` 写相对路径要带点**：`.ui.MainActivity` 会被拼成 `com.demo.app.ui.MainActivity`；写 `ui.MainActivity`（无点）会被当成完整类名，报 `ActivityNotFound`。

### 重置策略：三种组合，决定用例隔离级别

这组字段是 capabilities 里**最需要想清楚**的：

| 配置 | session 开始时 | session 结束时 | 适用 |
|------|--------------|--------------|------|
| 默认（都 false） | 清除 App 数据，不重装 | 不卸载 | 常规回归，用例间干净 |
| `noReset=True` | **什么都不做**，保留数据与登录态 | 不卸载 | 调试、已登录用例、提速 |
| `fullReset=True` | 卸载后重装 | **卸载** | 首次安装/新用户流程测试 |

```python
opts.no_reset = True        # 保留登录态，session 建立最快
opts.full_reset = False     # 两者不能同时 True，会报错
```

**实践建议**：本地调试一律 `noReset=True`（每次重新登录太浪费时间）；CI 回归用默认；只有专门测「首次安装引导流程」的用例才用 `fullReset`。

### Android 常用特有字段

```python
opts.set_capability("appium:systemPort", 8201)          # 端口转发用的 PC 侧端口，多设备并行必须错开
opts.set_capability("appium:autoGrantPermissions", True) # 自动授予所有 manifest 里声明的权限
opts.set_capability("appium:unicodeKeyboard", True)      # 换成 Appium 输入法，支持中文
opts.set_capability("appium:resetKeyboard", True)        # session 结束后恢复原输入法
opts.set_capability("appium:skipServerInstallation", True)   # 跳过装 server apk，提速
opts.set_capability("appium:skipDeviceInitialization", True) # 跳过设备初始化，提速
opts.set_capability("appium:disableWindowAnimation", True)   # 关动画，提稳定性
opts.set_capability("appium:ignoreHiddenApiPolicyError", True)
opts.set_capability("appium:uiautomator2ServerLaunchTimeout", 60000)
opts.set_capability("appium:adbExecTimeout", 60000)      # 单条 adb 命令超时（慢设备要调大）
opts.set_capability("appium:chromedriverExecutableDir", "/opt/chromedrivers")  # WebView 用
opts.set_capability("appium:appWaitActivity", "*.MainActivity")  # 等待哪个页面出现算启动完成
opts.set_capability("appium:appWaitDuration", 30000)
```

**`autoGrantPermissions` 是省心利器**：不加的话，App 首次启动弹一堆权限框，每个都要写代码点掉。加了之后 Appium 在安装时用 `pm grant` 直接授权，弹窗根本不出现。

**`appWaitActivity` 解决启动页跳转问题**：很多 App 的 `appActivity` 是 SplashActivity，但它 2 秒后就跳走了。如果不配 `appWaitActivity`，Appium 可能在等 Splash 时它已经消失，报 `Activity used to start app doesn't exist`。

### iOS 常用特有字段

```python
opts.set_capability("appium:wdaLocalPort", 8100)
opts.set_capability("appium:usePrebuiltWDA", True)
opts.set_capability("appium:xcodeOrgId", "ABCDE12345")
opts.set_capability("appium:xcodeSigningId", "iPhone Developer")
opts.set_capability("appium:updatedWDABundleId", "com.yourname.WebDriverAgentRunner")
opts.set_capability("appium:autoAcceptAlerts", True)      # 自动点系统弹窗的「允许」
opts.set_capability("appium:connectHardwareKeyboard", False)  # 强制弹软键盘
```

### 工程化：把 capabilities 抽成配置文件

硬编码在代码里是新手做法。正确姿势是外部配置 + 环境变量覆盖：

```yaml
# config/devices.yaml
default: &default
  platformName: Android
  automationName: UiAutomator2
  newCommandTimeout: 300
  autoGrantPermissions: true
  disableWindowAnimation: true
  noReset: false

local_emulator:
  <<: *default
  udid: emulator-5554
  systemPort: 8200
  noReset: true                # 本地调试保留登录态

ci_device_1:
  <<: *default
  udid: R5CT30XXXXX
  systemPort: 8201

ci_device_2:
  <<: *default
  udid: R5CT31YYYYY
  systemPort: 8202
```

```python
import os
import yaml
import pytest
from appium import webdriver
from appium.options.android import UiAutomator2Options

W3C_STANDARD = {"platformName", "browserName", "browserVersion",
                "acceptInsecureCerts", "pageLoadStrategy"}


def build_options(profile: str) -> UiAutomator2Options:
    with open("config/devices.yaml", encoding="utf-8") as f:
        caps = yaml.safe_load(f)[profile]

    # apk 路径由 CI 注入，不写死在配置里
    if apk := os.getenv("APK_PATH"):
        caps["app"] = apk

    opts = UiAutomator2Options()
    for k, v in caps.items():
        # 标准字段不加前缀，其余自动补 appium:
        opts.set_capability(k if k in W3C_STANDARD else f"appium:{k}", v)
    return opts


@pytest.fixture(scope="function")
def driver(request):
    profile = request.config.getoption("--device", default="local_emulator")
    d = webdriver.Remote(
        os.getenv("APPIUM_URL", "http://127.0.0.1:4723"),
        options=build_options(profile),
    )
    yield d
    d.quit()
```

这样一来，`pytest --device=ci_device_1` 就能切设备，CI 里并行跑多机型只是传不同参数的事。配置分层思路和 [[多环境配置与环境隔离]] 一致。

## 踩坑

1. **漏掉 `appium:` 前缀**
   Appium 2.x 最常见的入门错误。用 Options 对象而不是裸 dict 就能避免。

2. **`noReset` 和 `fullReset` 同时为 True**
   直接报错 `Cannot both fullReset and noReset be true`。语义上也矛盾。

3. **`newCommandTimeout` 默认 60 秒**
   打断点调试、或者用例里有长等待，超过 60 秒 session 自动销毁，之后所有操作报 `A session is either terminated or not started`。调试期设 600。

4. **多设备并行没错开 `systemPort`**
   第二个 session 抢不到 8200，报 `Cannot start the 'com.demo.app' application` 或直接超时。**并行的前提是每个 session 有独立的 `systemPort`（Android）/ `wdaLocalPort`（iOS）。**

5. **`appActivity` 相对路径漏了开头的点**
   `.ui.MainActivity` 对，`ui.MainActivity` 错。

6. **`appWaitActivity` 没配，启动页一闪而过导致失败**
   报 `Activity used to start app doesn't exist or cannot be launched`。配成通配 `*.MainActivity` 或直接 `*`。

7. **`unicodeKeyboard=True` 后忘了 `resetKeyboard=True`**
   跑完自动化，手机输入法永久停在 Appium 那个不可见的输入法上，用真机的人会以为手机坏了。这两个必须成对出现。

8. **`autoGrantPermissions` 掩盖了权限相关缺陷**
   它把权限流程整个跳过了。**专门测权限逻辑的用例必须关掉它**，否则「拒绝定位权限后 App 应有降级提示」这类用例根本测不到。

9. **`app` 指向的 apk 每次 session 都重装，很慢**
   本地调试改用 `appPackage` + `appActivity`，App 装一次就行，session 建立能从 40 秒降到 8 秒。

10. **把 apk 路径、账号密码写死在代码里提交上库**
    路径应由 CI 注入环境变量，凭据走 CI 的 secrets。硬编码不仅不灵活，还是安全问题。

11. **`platformVersion` 写死导致换设备就失败**
    它会做严格校验，`13` 和 `13.0` 都可能对不上。不是必须的话就别写。

12. **以为改 capabilities 能影响已存在的 session**
    capabilities 只在 `POST /session` 时生效一次。想改行为必须 `quit()` 后重建。

## 面试怎么答

**Q：Desired Capabilities 是什么，常用哪些字段？**
A：它是创建 session 时发给 Appium Server 的一份 JSON 配置，告诉 Server 用哪个 driver、连哪台设备、测哪个 App、以及这次会话的行为策略。必填的是 `platformName` 和 `automationName`，这两个决定加载哪个 driver。设备维度真正起作用的是 `udid`，`deviceName` 在 Android 上基本只是个标签。App 维度要么给 `app` 让 Appium 装包，要么给 `appPackage` 加 `appActivity` 直接起已装好的应用。行为维度我最常配四个：`noReset` 控制是否保留数据、`newCommandTimeout` 防止调试时 session 自己断、`autoGrantPermissions` 跳过权限弹窗、`systemPort` 用于多设备并行时错开端口。Appium 2.x 要注意非标准字段必须带 `appium:` 前缀。

**Q：`noReset`、`fullReset` 和默认行为有什么区别？**
A：三档隔离级别。默认行为是 session 开始时清除 App 数据但不重装，相当于 `pm clear`，App 回到刚安装状态但省掉了安装时间，适合常规回归。`noReset=true` 是什么都不做，保留登录态和所有本地数据，session 建立最快，适合本地调试和「已登录用户」的功能用例。`fullReset=true` 是卸载重装，结束后还会卸载，环境最干净但最慢，只在测首次安装引导流程时才需要。实践上我会分场景配：本地 `noReset`，CI 回归用默认，安装流程用例单独一套 `fullReset` 的配置。

**Q：多台设备并行执行，capabilities 上要注意什么？**
A：三点。第一，每台设备必须显式指定 `udid`，只写 `deviceName` 在多设备时会随机连一台。第二，Android 每个 session 要配不同的 `systemPort`，因为它是 `adb forward` 用的 PC 侧端口，默认都是 8200 会冲突；iOS 对应的是 `wdaLocalPort` 和 `mjpegServerPort`。第三，如果一台机器上跑多个 Appium Server 实例，`--port` 也要错开。工程上我不会把这些硬编码，而是抽成 YAML 配置，每台设备一个 profile，通过 pytest 的命令行参数选，CI 里配合 pytest-xdist 分发。

**Q：capabilities 应该怎么管理？**
A：绝对不硬编码在代码里。我的做法是抽成 YAML，用锚点定义公共部分，各设备 profile 继承后覆盖差异项；apk 路径这类每次构建都变的东西通过环境变量由 CI 注入；账号密码走 CI 的 secrets 不进代码库。代码里用一个 `build_options()` 函数把配置转成 Options 对象，顺便处理 `appium:` 前缀。这样切设备就是 `pytest --device=xxx`，扩展新机型只加一段配置，不改任何代码。

## 参考

- [Appium · Capabilities](https://appium.io/docs/en/latest/guides/caps/)
- [UiAutomator2 Driver Capabilities](https://github.com/appium/appium-uiautomator2-driver#capabilities)
- 相关笔记：[[Appium session 生命周期与 client 库]]
- 相关笔记：[[Appium 应用启停、重置与设备状态恢复]]
- 相关笔记：[[多环境配置与环境隔离]]
- 相关笔记：[[08-App自动化测试]]
