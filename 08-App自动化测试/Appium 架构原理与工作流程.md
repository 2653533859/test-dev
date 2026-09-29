---
created: 2026-07-31
tags: [App自动化测试/Appium]
---

# Appium 架构原理与工作流程

![[assets/appium-arch.svg]]
*图示：一次 `click()` 从测试脚本出发，要依次穿过 Client 库、Appium Server、平台 Driver、设备内代理进程、系统测试框架五层，才最终落到被测 App 上。*

> 面试第一问永远是「说说 Appium 的工作原理」。答不出中间有几层、每层干什么，后面所有排障问题都会答得很虚。

## 概念

### Appium 的设计哲学

Appium 官方有四条「设计理念」，理解了它们就理解了这套架构为什么要绕这么多弯：

1. **不应该为了自动化而重新编译 App，也不应该往 App 里塞 SDK。** 所以 Appium 走的是系统级测试框架（UiAutomator2 / XCUITest），从外部驱动 App，App 本身完全无感知。
2. **不应该被限定在某种语言或框架里。** 所以它选了 W3C WebDriver 协议——一套纯 HTTP + JSON 的规范，任何语言只要能发 HTTP 请求就能写 Appium 脚本。
3. **不应该重复造轮子。** 所以 Appium 自己不实现自动化能力，而是**包装**厂商提供的官方框架。
4. **应该是开源的。**

这四条推导出了那个「五层三明治」结构。**理解这一点，就能理解 Appium 的两个固有缺陷：链路长导致慢，依赖官方框架导致能力受限。**

### 五层分别是什么

| 层 | 运行位置 | 具体是什么 | 出问题的典型表现 |
|----|---------|-----------|----------------|
| ① Client 库 | 你的机器 | `Appium-Python-Client` 等，把方法调用翻译成 HTTP 请求 | client 与 server 大版本不匹配，报 `invalid argument` |
| ② Appium Server | 你的机器 / 远程 | Node.js 服务，默认监听 `4723`，只做路由与会话管理 | 端口被占、driver 没装 |
| ③ Driver 插件 | 与 Server 同进程 | UiAutomator2 Driver / XCUITest Driver，平台适配层 | `Could not find a driver for automationName` |
| ④ 设备内代理 | **手机里** | Android 是 `appium-uiautomator2-server.apk`；iOS 是 WebDriverAgentRunner | `instrumentation process cannot be initialized` |
| ⑤ 系统测试框架 | 手机系统层 | UiAutomator2 / Accessibility 服务 / XCUITest | 自绘 UI 拿不到控件树 |

**关键认知：Appium Server 本身完全不懂 Android 和 iOS。** 它就是个协议路由器，看到 `automationName: UiAutomator2` 就把请求交给对应 driver。这也是为什么 Appium 2.x 把 driver 拆成了独立安装的插件——核心极薄，能力全在 driver 里。

### Android 侧：session 建立时设备上发生了什么

这段是面试区分度最高的地方，多数人只答到「Appium Server 通过 adb 操作手机」，就止步了。实际上：

```bash
# 1. Driver 往设备里推三个 apk（首次或版本不符时）
adb install appium-uiautomator2-server.apk           # 真正的服务端
adb install appium-uiautomator2-server-debug-androidTest.apk  # instrumentation 入口
adb install io.appium.settings.apk                   # 系统能力助手：改输入法、开关网络、监听 Toast

# 2. 用 instrumentation 拉起服务（不是普通启动 Activity）
adb shell am instrument -w io.appium.uiautomator2.server.test/androidx.test.runner.AndroidJUnitRunner

# 3. server apk 在设备内监听 6790 端口，通过端口转发暴露给 PC
adb forward tcp:8200 tcp:6790
```

之后 Appium Server 发给设备的每条命令，实际是**向 PC 的 8200 端口发 HTTP 请求**，由 adb 转发进设备的 6790，由 server apk 调用 UiAutomator2 API 执行。

> 为什么必须用 `am instrument` 而不是普通启动？因为 UiAutomator2 API 只能在 instrumentation 测试进程里调用——它需要 `android.permission.INJECT_EVENTS` 这类系统级能力，普通 App 进程拿不到。

`io.appium.settings` 这个「隐形第三者」是很多疑难杂症的根源：它负责切输入法（所以你会发现跑完自动化输入法变了）、开关 WiFi/数据、以及**监听 Toast**（Toast 不在控件树里，靠 AccessibilityService 的事件回调抓）。

### iOS 侧：为什么 iOS 环境这么难搭

iOS 没有 adb 这种官方调试通道，Appium 用的是 **WebDriverAgent（WDA）**——一个 Facebook 开源、现由 Appium 维护的 iOS App：

```text
XCUITest Driver
   └─ xcodebuild 编译并安装 WebDriverAgentRunner 到设备
        └─ WDA 在设备内监听 8100，暴露 WebDriver 接口
             └─ 通过 usbmuxd / iproxy 把 8100 映射到 Mac 本地
                  └─ WDA 调用 XCUITest 框架操作 App
```

难点全在「安装 WDA」这一步：需要 Mac、需要 Xcode、需要开发者证书签名、真机还需要在设备上信任证书。详见 [[iOS 自动化环境：Xcode 与 WebDriverAgent]]。

## 用法

### 亲手验证这条链路

不写任何代码，用 curl 手撸一个 session，能彻底看清协议层：

```bash
# 启动 server（另开一个终端）
appium --address 127.0.0.1 --port 4723 --log-level debug

# 1. 创建 session（注意 W3C 格式：capabilities.alwaysMatch，字段带 appium: 前缀）
curl -X POST http://127.0.0.1:4723/session \
  -H 'Content-Type: application/json' \
  -d '{
        "capabilities": {
          "alwaysMatch": {
            "platformName": "Android",
            "appium:automationName": "UiAutomator2",
            "appium:deviceName": "emulator-5554",
            "appium:appPackage": "com.android.settings",
            "appium:appActivity": ".Settings"
          }
        }
      }'
# 返回 {"value":{"sessionId":"7f3a...","capabilities":{...}}}

# 2. 用返回的 sessionId 找元素
curl -X POST http://127.0.0.1:4723/session/7f3a.../element \
  -H 'Content-Type: application/json' \
  -d '{"using":"id","value":"com.android.settings:id/search_action_bar"}'

# 3. 销毁 session
curl -X DELETE http://127.0.0.1:4723/session/7f3a...
```

同时观察设备侧的证据：

```bash
adb forward --list          # 能看到 tcp:8200 tcp:6790 这条转发
adb shell ps | grep uiautomator2   # 能看到 instrumentation 进程在跑
adb shell pm list packages | grep appium   # 三个 apk 都在
```

**建议每个人都跑一遍这三条命令**。跑过之后，「Appium 怎么控制手机」这个问题就再也不会答得空洞了。

### Python 版等价代码

```python
from appium import webdriver
from appium.options.android import UiAutomator2Options

opts = UiAutomator2Options()
opts.platform_name = "Android"
opts.automation_name = "UiAutomator2"
opts.device_name = "emulator-5554"
opts.app_package = "com.android.settings"
opts.app_activity = ".Settings"

# 这一行内部就是上面那个 POST /session
driver = webdriver.Remote("http://127.0.0.1:4723", options=opts)
print(driver.session_id)        # 和 curl 返回的是同一个东西
driver.quit()                   # 内部是 DELETE /session/{id}
```

### 读懂 Appium Server 日志

排障 80% 靠这份日志。它的行格式是 `[组件] 内容`，按组件就能判断卡在哪一层：

```text
[HTTP] --> POST /session/{id}/element            ← 层①②：请求到达 Server
[AndroidUiautomator2Driver@4c1f] Calling AppiumDriver...  ← 层③：driver 接手
[UiAutomator2] Sending command to instrumentation server  ← 层④：转发进设备
[ADB] Running 'adb -P 5037 -s emulator-5554 shell ...'    ← 层④：走 adb
[UiAutomator2] Got response with status 200               ← 层⑤：设备执行成功
[HTTP] <-- POST /session/{id}/element 200 187 ms          ← 整条链路耗时
```

**看最后那个耗时**：一次简单的 `find_element` 通常 50–300ms。如果单条命令动辄 1–3 秒，基本可以确定是 XPath 定位在 dump 全量控件树，见 [[Appium 控件定位策略]]。

## 踩坑

1. **`Could not find a driver for automationName 'UiAutomator2'`**
   Appium 2.x 起 driver 不再内置，必须单独装：`appium driver install uiautomator2`。用 `appium driver list --installed` 确认。这是从 1.x 升上来的人第一个撞的墙。

2. **`instrumentation process cannot be initialized` / `Could not proxy command to remote server`**
   层④断了。按顺序查：`adb devices` 设备在不在 → 有没有安全软件（部分国产 ROM 的「后台弹出界面」限制）杀掉了 instrument 进程 → 手动 `adb uninstall io.appium.uiautomator2.server` 等三个包再让 Appium 重装 → 检查 `systemPort` 是否被别的 session 占用。

3. **同时跑多设备互相打架**
   两个 session 默认都用 `8200` 做端口转发，第二个必然失败。多设备并行必须给每个 session 指定不同的 `appium:systemPort`（Android）或 `appium:wdaLocalPort`（iOS）。

4. **client 与 server 版本错配**
   Appium 2.x 要求 capabilities 用 W3C 格式（自定义字段带 `appium:` 前缀）。用老版 client 连新 server 会报 `Bad parameters` 或 `invalid argument`。Python 侧统一改用 `UiAutomator2Options` 对象而不是裸 dict，就不用手写前缀。

5. **以为 Appium 能测一切 UI**
   层⑤决定了能力边界：控件树来自无障碍节点。Flutter（自绘）、Unity 游戏、Canvas 渲染的页面，控件树里就是一个大方块。Flutter 要用 `flutter` driver 或让开发加 `Semantics`；游戏只能上图像识别（Airtest），见 [[UiAutomator2、Airtest 与 Poco 选型对比]]。

6. **忽略链路长度带来的性能特征**
   一次操作 100–300ms，一条 20 步的用例光通信就 5 秒起。**所以 App 自动化的用例粒度必须比 Web 更粗**：不要为了「一个断言一条用例」把同一条主流程跑五遍，那是纯浪费。

7. **在 CI 上用 `--session-override` 掩盖问题**
   这个参数会让新 session 直接顶掉旧的。看起来解决了「session 已存在」，实际掩盖了上一条用例没 `quit()` 的资源泄漏。正确做法是把 `driver.quit()` 放进 pytest fixture 的 teardown，见 [[Appium session 生命周期与 client 库]]。

8. **国产 ROM 的权限拦截**
   小米/华为等需要在开发者选项里额外开「USB 调试（安全设置）」，否则无法模拟点击；部分机型还要关掉「MIUI 优化」。这类问题日志里只会表现为「点击无响应但不报错」，最难查。

## 面试怎么答

**Q：说说 Appium 的工作原理，从脚本到设备中间经过哪几层？**
A：一共五层。第一层是 client 库，把 `driver.click()` 这样的方法调用翻译成符合 W3C WebDriver 规范的 HTTP 请求；第二层是 Appium Server，一个 Node.js 服务，默认监听 4723，它本身不懂 Android 和 iOS，只负责会话管理和把请求路由给对应的 driver；第三层是 driver 插件，Android 是 UiAutomator2 Driver、iOS 是 XCUITest Driver，负责把通用命令翻译成平台原生调用；第四层是设备内部的代理进程，Android 上 driver 会往手机里装一个 `appium-uiautomator2-server.apk`，用 `am instrument` 拉起来，它在设备内监听 6790 端口，再用 `adb forward` 映射到 PC，iOS 上对应的是 WebDriverAgent 监听 8100；第五层是系统测试框架，server apk 最终调用 UiAutomator2 的 API 读控件树、注入触摸事件。这个设计的好处是不用改被测 App、语言无关；代价是链路长，一次操作 100 到 300 毫秒。

**Q：为什么 Appium 要设计得这么复杂？直接用 UiAutomator2 不行吗？**
A：直接用 UiAutomator2 要写 Java、要打成测试 apk 装进设备跑，脚本和被测应用绑死，而且完全不能复用到 iOS。Appium 用 W3C WebDriver 协议在中间做了一层抽象，换来三件事：一是语言无关，Python/Java/JS 都能写；二是双端一套脚本，换个 `automationName` 就能跑 iOS；三是 server 可以远程部署，天然支持云真机和设备农场——你脚本连的是一个 URL，那台设备在本地还是在机房无所谓。这个抽象代价是性能，收益是工程可维护性，对测试团队来说这笔账是划算的。

**Q：Appium 有什么做不到的？**
A：三类。第一类是自绘 UI，Flutter、Unity 游戏、Canvas 页面，因为控件树来自系统的无障碍节点，自绘的东西在树里就是一整块，只能靠坐标或者图像识别（Airtest）。第二类是需要 root 或系统签名才能做的事，比如深度修改系统设置、拦截系统级弹窗的某些场景。第三类是性能，链路太长，做不了高频操作，也不适合做压力型的 Monkey 测试——那类场景直接用 `adb shell monkey` 或 UiAutomator 原生更合适。

**Q：多台设备并行执行要注意什么？**
A：每台设备一个独立 session，而 session 之间会抢占端口。Android 必须给每个 session 配不同的 `systemPort`（那个用于 adb forward 的 PC 侧端口，默认 8200），iOS 要配不同的 `wdaLocalPort`（默认 8100），否则第二个 session 起不来。另外每个 session 的 `udid` 要明确指定，不能只靠 `deviceName`。设备多了以后还要考虑一个 Appium Server 进程扛几台，通常一台机器起多个 Server 实例，或者直接用 Selenium Grid / 云真机平台调度，参考 [[Selenium Grid 与并行执行]] 的思路。

## 参考

- [Appium · Introduction](https://appium.io/docs/en/latest/intro/)
- [Appium · UiAutomator2 Driver](https://github.com/appium/appium-uiautomator2-driver)
- [W3C WebDriver 规范](https://www.w3.org/TR/webdriver2/)
- 相关笔记：[[Appium session 生命周期与 client 库]]
- 相关笔记：[[Appium Desired Capabilities 详解]]
- 相关笔记：[[adb 常用命令详解]]
- 相关笔记：[[08-App自动化测试]]
