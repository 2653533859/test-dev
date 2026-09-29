---
created: 2026-07-31
tags: [App自动化测试/环境]
---

# Appium Inspector 元素检查与定位调试

> Web 端有浏览器 F12，App 端对应的就是 Appium Inspector。但它比 F12 弱得多——理解它的局限，比学会点按钮更重要。

![[assets/element-inspection.svg]]
*图示：Appium Inspector 本质是一个图形化 client（建 session → GET /source 拿控件树 XML → GET /screenshot 拿截图 → 叠加渲染），核心工作流 Refresh → Select → Search for element，候选表达式优先级，以及 Inspector 连不上时的三种替代方案。*

## 概念

### 它做的三件事

Appium Inspector 不是什么神秘工具，它就是一个**图形化的 Appium client**：

1. 用你填的 capabilities 建一个真实 session；
2. 调 `GET /session/{id}/source` 拿控件树 XML，调 `GET /session/{id}/screenshot` 拿截图；
3. 把两者叠在一起渲染，你点截图上某处，它在 XML 里反查对应节点，展示属性并推荐定位表达式。

**关键推论：Inspector 占用一个 session。** 所以 Inspector 连着的时候脚本连不上同一台设备（除非配了不同的 `systemPort`）；Inspector 里看到的控件树，就是脚本里 `driver.page_source` 拿到的同一份数据，不会多也不会少。

Appium 2.x 起，Inspector 从 Appium Desktop 中独立出来，是一个单独下载的应用（`appium-inspector`），Server 要自己另起。

### 控件树里的属性各是什么

以 Android 一个按钮为例：

```xml
<android.widget.Button
    index="2"
    package="com.demo.app"
    class="android.widget.Button"
    text="立即登录"
    resource-id="com.demo.app:id/btn_login"
    content-desc="login-submit"
    checkable="false" checked="false"
    clickable="true"  enabled="true"
    focusable="true"  focused="false"
    scrollable="false" long-clickable="false"
    password="false"  selected="false"
    bounds="[108,1204][972,1336]"
    displayed="true" />
```

| 属性 | 用途 | 注意 |
|------|------|------|
| `resource-id` | 最佳定位依据 | RN / 混淆构建可能为空 |
| `content-desc` | 对应 `accessibility id` | 双端通用，优先级最高 |
| `text` | 显示文本 | 多语言环境下会变，慎用 |
| `class` | 控件类型 | 只能配合其他条件缩小范围 |
| `clickable` | 能否点击 | **为 false 时点它无效，要点它的父节点** |
| `enabled` | 是否可用 | false 时点击不报错但没反应 |
| `bounds` | 坐标区域 `[left,top][right,bottom]` | 算中心点做坐标兜底时用 |
| `displayed` | 是否在屏幕上 | 屏幕外元素为 false |
| `index` | 同级序号 | 会变，绝对不要用来定位 |

**`clickable="false"` 是新手最常撞的坑**：设计上文字 `TextView` 常常不可点，可点的是包着它的 `LinearLayout`。直接点 TextView 不报错但页面纹丝不动。

## 用法

### 一、连接配置

先起 Server（Inspector 不会帮你起）：

```bash
appium --address 127.0.0.1 --port 4723
```

Inspector 里填：

```text
Remote Host:  127.0.0.1
Remote Port:  4723
Remote Path:  /            ← Appium 2.x 是 /，1.x 是 /wd/hub，填错报 404
```

Capabilities（JSON 视图直接粘贴更快）：

```json
{
  "platformName": "Android",
  "appium:automationName": "UiAutomator2",
  "appium:deviceName": "emulator-5554",
  "appium:appPackage": "com.demo.app",
  "appium:appActivity": ".ui.MainActivity",
  "appium:noReset": true,
  "appium:newCommandTimeout": 600
}
```

> `newCommandTimeout` 一定调大。默认 60 秒，你在 Inspector 里研究控件树超过一分钟，session 就自己断了，表现为「点刷新突然报错」。

### 二、核心工作流

| 按钮 | 作用 | 什么时候用 |
|------|------|-----------|
| **Refresh Source & Screenshot** | 重新抓树 | **每次页面变化后都必须点**，否则看的是旧快照 |
| **Select Elements**（默认） | 点截图选元素 | 常规查看 |
| **Tap/Swipe By Coordinates** | 坐标操作 | 无法选中的元素（自绘、遮挡） |
| **Start/Stop Recording** | 录制成代码 | 只用来抄定位表达式，不要直接用生成的脚本 |
| **Search for element** | 试定位表达式 | **最有价值的功能**，见下 |

**「Search for element」是这个工具的精髓**：你可以直接输入一个 XPath 或 UiAutomator 表达式，它会告诉你匹配到几个元素、分别是谁。写复杂定位时在这里试通了再写进代码，能省掉「改脚本 → 跑 → 报错 → 再改」的循环。

```text
Locator Strategy: -android uiautomator
Selector:  new UiSelector().resourceIdMatches(".*btn_.*").clickable(true)
→ 结果：Found 3 elements
```

### 三、Inspector 推荐的定位表达式要不要直接抄

它会给出一组候选：

```text
id             com.demo.app:id/btn_login          ← 抄这个
accessibility id  login-submit                    ← 更该抄这个
xpath          //android.widget.Button[@text="立即登录"]   ← 可用
xpath          /hierarchy/android.widget.FrameLayout/.../android.widget.Button[2]  ← 千万别抄
```

**优先级判断���则见 [[Appium 控件定位策略]]**。Inspector 生成的绝对路径 XPath 换个机型就废，它只是「保证能选中当前这一个」，不保证稳定。

### 四、Inspector 之外的替代方案

Inspector 有时连不上（企业内网、iOS 签名过期、设备被占用），要有备胎：

```bash
# 方案一：uiautomatorviewer（SDK 自带，纯离线，Android 专用）
$ANDROID_HOME/tools/bin/uiautomatorviewer
# 缺点：新版 SDK 已废弃，且不能查看 WebView 内部

# 方案二：直接 dump 控件树，最轻量最可靠
adb shell uiautomator dump /sdcard/ui.xml
adb pull /sdcard/ui.xml ./ui.xml
# 然后用编辑器 / Python 分析，甚至可以写脚本批量比对不同机型的控件树差异

# 方案三：脚本里随时打印
# python: print(driver.page_source)
```

**方案二在排查「CI 上失败但本地正常」时特别好用**：在用例失败的 teardown 里 dump 一份控件树存档，事后就能知道当时页面上到底有什么，见 [[App UI 自动化稳定性治理]]。

### 五、weditor（第三方，配合 uiautomator2 库）

```bash
pip install uiautomator2 weditor
python -m uiautomator2 init      # 往设备装 atx-agent
python -m weditor                # 浏览器里打开检查器
```

它走的是 [[UiAutomator2、Airtest 与 Poco 选型对比]] 里说的 `uiautomator2` Python 库那条路，不依赖 Appium Server，**响应比 Inspector 快很多**，纯 Android 项目很多人只用它。

## 踩坑

1. **Remote Path 填错报 404**
   Appium 2.x 是 `/`，1.x 是 `/wd/hub`。这是从旧教程照抄最常见的错误。

2. **忘了点 Refresh，对着旧快照找元素**
   页面已经跳走了，Inspector 里还是上一页的树，怎么找都找不到目标元素。**任何时候「元素明明在屏幕上却选不中」，先点 Refresh。**

3. **`newCommandTimeout` 太短导致 session 中途断开**
   报错是 `A session is either terminated or not started`，看着像 bug，其实是超时。设 600。

4. **Inspector 占着 session，脚本连不上**
   报 `Could not start a new session, session already exists` 或直接卡住。调试完记得点 Quit Session。

5. **WebView 内部看不到 DOM**
   Inspector 默认在 NATIVE_APP 上下文，H5 区域是一个空白大方块。要在 Inspector 顶部把 context 切到 `WEBVIEW_xxx`，但它对 WebView 的支持并不好，**H5 调试老老实实用 `chrome://inspect`**，见 [[WebView H5 调试：chrome-inspect 实战]]。

6. **抓不到瞬时元素（Toast、加载动画）**
   Inspector 抓树需要一两秒，Toast 早消失了。Toast 根本不在控件树里，要用专门方案，见 [[Android Toast 捕获方案]]。

7. **控件树被弹窗/悬浮窗污染**
   有些机型的悬浮球、屏幕录制提示会出现在树里，还可能盖在目标元素上。看到陌生的 `com.android.systemui:id/...` 节点先排除掉。

8. **直接用录制生成的代码**
   录制出来的代码是线性流水账：绝对 XPath、硬编码坐标、没有等待、没有断言。**它的正确用法是「抄定位表达式」，不是「生成脚本」。** 直接用录制脚本做回归，是 App 自动化项目烂尾的经典起手式。

9. **控件树在长列表页面巨大且卡顿**
   `RecyclerView` 里几十个 item 会让 XML 上万行，Inspector 刷新一次要好几秒。这时可以先滚动到目标附近，或者直接用 `uiautomator dump` 拉下来在编辑器里搜。

## 面试怎么答

**Q：你们怎么找 App 上的元素？**
A：日常用 Appium Inspector，它本质上是个图形化的 Appium client，建一个 session 后把控件树 XML 和截图叠在一起展示，点哪个位置就反查对应节点。但我不直接用它推荐的 XPath，它给的往往是绝对路径，换机型就失效。我的用法是：先看这个元素有没有 `resource-id` 或 `content-desc`，有就用；没有就在 Inspector 的「Search for element」里试写一个 UiSelector 表达式，确认只匹配到一个元素再写进代码。另外我更常用的其实是 `adb shell uiautomator dump` 把控件树拉下来直接看，比开 Inspector 快，而且能存档做机型间比对。

**Q：Inspector 里能看到元素，脚本里却找不到，可能是什么原因？**
A：常见四种。第一，时序问题——Inspector 里是你手动操作到那一页停下来看的，脚本跑得快，元素还没渲染出来，加显式等待。第二，上下文问题——元素在 WebView 里，脚本还在 NATIVE_APP 上下文。第三，定位表达式抄的是绝对 XPath，Inspector 那次的树和脚本跑时的树有细微差别（比如多了一个弹窗节点）。第四，元素在屏幕外，`displayed` 是 false，需要先滚动。排查方法是在失败点打印 `driver.page_source` 存下来，和 Inspector 里的树逐行比对。

**Q：录制回放你们用吗？**
A：只用来抄定位表达式，不用来生成用例。录制脚本有三个硬伤：全是绝对路径定位、没有任何等待、没有断言，本质上是一次操作的流水账。App UI 变动频繁，这种脚本第二个版本就全红了，维护成本远高于重写。正经做法是用 Page Object 分层，把定位收敛到页面类里，参考 [[Page Object 模式与分层设计]]。

## 参考

- [Appium Inspector 项目主页](https://github.com/appium/appium-inspector)
- [Android 开发者 · UI Automator Viewer](https://developer.android.com/training/testing/other-components/ui-automator)
- 相关笔记：[[Appium 控件定位策略]]
- 相关笔记：[[Android 自动化测试环境搭建]]
- 相关笔记：[[UiAutomator2、Airtest 与 Poco 选型对比]]
- 相关笔记：[[08-App自动化测试]]
