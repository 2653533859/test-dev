---
created: 2026-07-31
tags: [App自动化测试/环境]
---

# Android 自动化测试环境搭建

> App 自动化劝退新人的第一关不是写脚本，是环境。搞清楚每个组件为什么需要、装在哪、怎么验证，比照着教程复制粘贴命令有价值得多。

## 概念

### 五个组件，各自解决什么问题

| 组件 | 作用 | 谁依赖它 |
|------|------|---------|
| **JDK** | Android SDK 的部分工具（`apksigner`、`aapt2`）是 Java 写的 | Android SDK 工具链 |
| **Android SDK** | 提供 `adb`、`emulator`、`aapt` 等命令行工具 | Appium 的 UiAutomator2 Driver |
| **Node.js** | Appium Server 是 Node 程序 | Appium 本体 |
| **Appium Server** | 协议路由 + driver 宿主 | 测试脚本 |
| **Appium Inspector** | 图形化查看控件树、生成定位表达式 | 写脚本的人 |

**注意 JDK 的定位常被误解**：不是「Appium 用 Java 写的所以要 JDK」，Appium 是 Node 写的。JDK 是给 Android SDK 的工具链用的，而且 UiAutomator2 Driver 在处理 apk 签名（判断是否需要重签名）时会调用 `apksigner`。所以 `JAVA_HOME` 必须正确，否则会报 `Could not find 'apksigner.jar'` 这类看上去毫不相关的错。

### 环境变量为什么必须配

Appium 定位 Android 工具的顺序是：

```text
ANDROID_HOME（或新名 ANDROID_SDK_ROOT）
  └─ $ANDROID_HOME/platform-tools/adb
  └─ $ANDROID_HOME/build-tools/<version>/apksigner
  └─ $ANDROID_HOME/emulator/emulator

JAVA_HOME
  └─ $JAVA_HOME/bin/java
```

它**不完全依赖 PATH**——很多人 `adb` 在终端能跑，Appium 却报找不到 SDK，原因就是只把 `platform-tools` 加进了 PATH，没设 `ANDROID_HOME`。

## 用法

### 一、装 JDK 并验证

```bash
java -version
# openjdk version "17.0.10" ...

# Windows（PowerShell 里查）/ Git Bash：
echo $JAVA_HOME
# 应输出 JDK 根目录，例如 C:/Program Files/Java/jdk-17
```

> Appium 对 JDK 版本不敏感，8/11/17 都行；但如果同时要跑 Android Gradle 构建，跟项目要求的版本对齐。

### 二、装 Android SDK

不必装完整 Android Studio，只要 command line tools 也行，但对新手而言装 Studio 更省事（自带 SDK Manager 与 AVD Manager）。

必装的三个包：

```text
Android SDK Platform-Tools      → adb、fastboot
Android SDK Build-Tools         → apksigner、aapt2
Android Emulator + 系统镜像       → 模拟器（用真机可跳过）
```

配置环境变量（Windows 用系统设置面板；类 Unix 写进 `~/.bashrc`）：

```bash
export ANDROID_HOME="$HOME/Library/Android/sdk"        # macOS 默认路径
export PATH="$PATH:$ANDROID_HOME/platform-tools"
export PATH="$PATH:$ANDROID_HOME/emulator"
export PATH="$PATH:$ANDROID_HOME/build-tools/34.0.0"
```

验证：

```bash
adb version
# Android Debug Bridge version 1.0.41

adb devices
# List of devices attached
# emulator-5554   device        ← 出现 device 才算通
```

### 三、装 Appium Server

```bash
node -v          # 建议 LTS 版本，Appium 2.x 要求 >= 14
npm i -g appium
appium -v        # 2.x.x

# 关键：2.x 起 driver 要单独装
appium driver install uiautomator2
appium driver list --installed
# ✔ uiautomator2@3.x.x [installed (npm)]
```

启动：

```bash
appium --address 127.0.0.1 --port 4723 --allow-insecure adb_shell
# --allow-insecure adb_shell 允许脚本里执行 driver.execute_script("mobile: shell", ...)
# 生产环境慎用，本地调试很方便
```

### 四、用官方体检工具一键排查

**这是最该先学会的一条命令**，能省掉 90% 的盲目搜索：

```bash
npm i -g appium-doctor        # 或 Appium 2.x 推荐 appium-installer
appium-doctor --android
```

输出示例：

```text
✔ The Java version is 17.0.10
✔ ANDROID_HOME is set to: /Users/x/Library/Android/sdk
✔ adb exists at: /Users/x/Library/Android/sdk/platform-tools/adb
✖ emulator could NOT be found in /Users/x/Library/Android/sdk/emulator
✖ JAVA_HOME is NOT set
```

有 `✖` 就照着提示补，别急着写脚本。

### 五、准备设备：真机 vs 模拟器

真机接入：

```bash
# 手机：设置 → 关于手机 → 连点「版本号」7 次 → 开发者选项 → USB 调试
adb devices
# 若显示 unauthorized，看手机屏幕点「允许」并勾选「一律允许」

# 无线调试（Android 11+ 可用配对码；老版本用下面这招）
adb tcpip 5555
adb connect 192.168.1.20:5555
```

模拟器：

```bash
# 列出已创建的 AVD
emulator -list-avds

# 启动（-no-snapshot-load 强制冷启动，避免快照状态污染）
emulator -avd Pixel_6_API_33 -no-snapshot-load

# 关键：选 x86_64 镜像而不是 arm，否则在 x86 机器上要模拟指令集，慢十倍
```

| 维度 | 真机 | 模拟器 |
|------|------|--------|
| 速度 | 一般 | x86 镜像下更快 |
| 传感器/摄像头/指纹 | 真实 | 模拟或缺失 |
| 支付、推送、地图 SDK | 正常 | 常缺 Google 服务或被风控拦截 |
| 兼容性覆盖 | 需买设备 | 任意 API 版本随便建 |
| 跑 CI | 需设备农场 | 容器里可跑（`--no-window`） |

**实践建议：日常开发调试用模拟器，回归与验收必须上真机。** 很多问题（性能、指纹、Push、厂商 ROM 定制）模拟器上根本复现不了。

### 六、跑通第一个用例

```python
import pytest
from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy


@pytest.fixture()
def driver():
    opts = UiAutomator2Options()
    opts.platform_name = "Android"
    opts.automation_name = "UiAutomator2"
    opts.device_name = "emulator-5554"
    opts.app_package = "com.android.settings"     # 用系统设置当小白鼠，不用装包
    opts.app_activity = ".Settings"
    opts.no_reset = True
    opts.new_command_timeout = 120

    d = webdriver.Remote("http://127.0.0.1:4723", options=opts)
    yield d
    d.quit()                                       # 一定要放在 yield 后面


def test_open_settings(driver):
    # 系统设置里一定存在的元素：搜索框
    el = driver.find_element(AppiumBy.ID, "com.android.settings:id/search_action_bar")
    assert el.is_displayed()
```

跑之前先确认 `appPackage` / `appActivity` 是对的：

```bash
# 先手动打开目标 App，然后查当前页面
adb shell dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'
# mCurrentFocus=Window{... com.android.settings/com.android.settings.homepage.SettingsHomepageActivity}
```

## 踩坑

1. **`adb devices` 显示 `unauthorized`**
   手机上没确认 RSA 授权框。若一直不弹：开发者选项里「撤销 USB 调试授权」再重插；仍不行则 `adb kill-server && adb start-server`。

2. **`adb devices` 空列表（Windows 高发）**
   缺 USB 驱动。装厂商驱动或 Google USB Driver；换一根**数据线**（很多线只能充电）；换 USB 口（前置口供电不足很常见）。

3. **两个 adb 打架：`adb server version doesn't match this client`**
   电脑上存在多个 adb（Android Studio 自带一个、单独装了一个、某手机助手偷偷装了一个）。它们抢 5037 端口且版本不同。解决：统一到 SDK 里那个，把其他从 PATH 里踢掉，然后 `adb kill-server`。

4. **`ANDROID_HOME` 配了但 Appium 还是找不到**
   环境变量是在**启动 Appium 的那个终端会话**里生效的。改完 `.bashrc` 要重开终端；Windows 上改完系统变量要重启终端甚至重启 IDE。用 GUI 版 Appium Desktop 时，它继承的是启动它的桌面会话环境，改完可能要重新登录。

5. **`Could not find 'apksigner.jar'`**
   `build-tools` 没装或 `JAVA_HOME` 没设。这个报错的字面意思和真实原因关联很弱，容易查歪。

6. **模拟器选了 ARM 镜像**
   在 x86 电脑上跑 ARM 镜像要做指令翻译，慢到用例大面积超时。建 AVD 时认准 `x86_64`。

7. **`new_command_timeout` 默认 60 秒的坑**
   如果脚本里有断点调试或长时间 sleep，超过 60 秒没有新命令，Appium 会自动结束 session，之后所有操作报 `A session is either terminated or not started`。调试期设成 `300`。

8. **国产 ROM 额外开关**
   MIUI：开发者选项里还要开「USB 调试（安全设置）」，否则无法模拟点击输入；关掉「MIUI 优化」。华为/荣耀：需要在「仅充电模式下允许 ADB 调试」。这些不开的表现是**命令不报错但设备无反应**，极难定位。

9. **公司电脑装 `-g` 全局 npm 包权限不足**
   macOS/Linux 别用 `sudo npm i -g`（后患无穷），用 nvm 管理 Node；Windows 上用管理员终端或改 npm prefix。

10. **模拟器与真机同时连着**
    `adb` 命令不带 `-s` 会报 `more than one device/emulator`；Appium 侧则要显式指定 `udid`，只写 `deviceName` 在多设备时是不可靠的（Appium 拿它做匹配但不保证唯一）。

## 面试怎么答

**Q：搭一套 Android 自动化环境需要哪些东西？**
A：JDK、Android SDK、Node.js、Appium Server 加 UiAutomator2 driver，再加一台真机或模拟器，图形化调试再装个 Appium Inspector。关键不是装了什么，是三个环境变量要对：`JAVA_HOME`、`ANDROID_HOME`、把 `platform-tools` 加进 PATH。因为 Appium 是按 `ANDROID_HOME` 去找 adb 和 apksigner 的，只配 PATH 不配 `ANDROID_HOME` 会出现「终端里 adb 能跑但 Appium 说找不到 SDK」这种迷惑现象。装完先跑 `appium-doctor --android` 体检，比出问题再搜快得多。

**Q：真机和模拟器怎么选？**
A：分阶段。写脚本、调定位、日常回归用模拟器，起停快、可以并行开多个、API 版本随便切。但涉及性能数据、指纹与摄像头、推送、支付、厂商 ROM 定制行为的用例必须上真机——模拟器的性能数据没有参考价值，而且很多 App 会做模拟器检测直接拒绝运行或走风控。上线前的兼容性验收一定是真机矩阵或云真机平台。

**Q：环境搭好了但设备连不上，你怎么排查？**
A：从下往上。先 `adb devices`：空列表就是驱动或数据线问题；`unauthorized` 是手机上没点授权；`offline` 就 `adb kill-server` 重置。设备正常了再看 Appium Server 日志卡在哪一层——如果卡在装 `uiautomator2-server.apk` 或 `am instrument`，通常是国产 ROM 的后台限制或安全软件拦截，手动卸载那三个 appium 包让它重装一般能好。如果日志里压根没有 adb 相关输出，那就是 driver 没装或 `automationName` 写错了。

## 参考

- [Appium · Setting up Android](https://appium.io/docs/en/latest/quickstart/uiauto2-driver/)
- [Android 开发者 · adb 命令](https://developer.android.com/tools/adb)
- 相关笔记：[[Appium 架构原理与工作流程]]
- 相关笔记：[[adb 常用命令详解]]
- 相关笔记：[[Appium Inspector 元素检查与定位调试]]
- 相关笔记：[[08-App自动化测试]]
