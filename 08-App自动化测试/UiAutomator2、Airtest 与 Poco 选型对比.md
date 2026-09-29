---
created: 2026-07-31
tags: [App自动化测试/选型]
---

# UiAutomator2、Airtest 与 Poco 选型对比

> 不是所有 App 自动化都该上 Appium。UiAutomator2 底层、Airtest 图像、Poco 控件——三者定位不同，选错工具，后期维护成本差十倍。

## 概念

### 三者的定位与血缘

| 工具 | 本质 | 定位方式 | 适用 |
|---|---|---|---|
| **UiAutomator2 (Google 原生)** | Android 官方 UI 测试框架 | 原生控件树（UiSelector） | 纯原生、底层、CI 友好 |
| **Airtest** | 网易开源，基于图像识别 | **截图/图像匹配** | 游戏、无控件树、脚本易写 |
| **Poco** | 网易开源，Airtest 姊妹，嵌在引擎里 | **引擎内控件树**（Unity/Cocos 等） | 游戏、自绘引擎、跨平台 |

关键区分：**UiAutomator2 是 Google 官方、只管 Android 原生**；**Airtest 是图像驱动**、不依赖控件树；**Poco 是游戏引擎内的控件树**，能拿到 Unity/Cocos 里 `GameObject` 层级。

### 为什么不是「Appium 通吃」

Appium 是「跨平台统一协议」层，底层 Android 还是调 UiAutomator2 Server。但：
- 自绘/游戏引擎（Unity）在 Android 无障碍树里就是一个大黑块，Appium 拿不到内部按钮 → 此时 Poco 才能拿到引擎内节点。
- 连内部节点都没有的纯画面（视频/游戏渲染）→ 只能用 Airtest 图像识别。
- 纯原生、要稳定 CI、要和标准 WebDriver 协议对齐 → UiAutomator2/Appium 最省心。

## 用法

### 一、UiAutomator2 原生写法（不通过 Appium）

```python
from uiautomator2 import Device

d = Device("emulator-5554")
d.app_start("com.xxx.app")
d(text="登录").click()
d(resourceId="com.xxx:id/et_pwd").set_text("123456")
assert d(text="首页").exists
```

比 Appium 轻，无 Server 中转，直接走 `atx-agent`，**快、稳、但只 Android 原生**。

### 二、Airtest 图像驱动

```python
from airtest.core.api import *

auto_setup(__file__)
# 截图后点图（不依赖控件）
touch(Template(r"tpl_login_btn.png"))
# 断言画面出现
assert exists(Template(r"tpl_home.png"))
```

图像匹配对分辨率敏感：换机型截图要重截，或开多分辨率模板。

### 三、Poco 引擎内控件

```python
from poco.drivers.unity3d.unity_poco import UnityPoco
from airtest.core.api import *

auto_setup(__file__)
poco = UnityPoco()
# 直接操作游戏内 GameObject
poco("ShopPanel").child("buy_btn").click()
assert poco("CoinText").get_text() == "100"
```

Poco 能拿到 Unity/Cocos 的节点名、文本、坐标，是游戏 UI 自动化的唯一正解。

### 四、三者组合典型架构

```text
原生 App + 内嵌游戏模块：
  Appium + UiAutomator2   → 测原生壳、登录、跳转
  Poco                    → 切到游戏模块测内部玩法
  Airtest                 → 兜底纯画面/动画校验

纯游戏：直接 Airtest + Poco，无需 Appium。
```

## 踩坑

1. **用 Appium 测 Unity 游戏，拿不到按钮**：Unity 自绘在原生无障碍树是黑块，Appium 全体找不到。该上 Poco 拿引擎内节点，或 Airtest 图像。
2. **Airtest 图像换分辨率全失效**：一张截图模板只匹配固定分辨率/主题，换机型或夜间模式直接匹配失败。图像方案要管理多套模板或结合特征点。
3. **图像识别不稳定、维护成本高**：UI 一改版，所有截图模板得重截；且识别有置信度阈值，偶发点错。能拿控件树（Poco/U2）就别用图像。
4. **UiAutomator2 原生库无法跨平台**：写 `uiautomator2` 直接绑死 Android，iOS 没戏。要双端统一用 Appium 封装。
5. **Poco 需要游戏包嵌入 SDK**：Poco 要在游戏工程里集成 `poco-sdk`，纯 APK 逆向拿不到引擎节点。接入前要和游戏开发确认 SDK 已埋。
6. **Airtest 在 CI 无头环境需要接真机/模拟器**：图像识别依赖渲染画面，无头跑不了，必须真机或带显示的模拟器，且要避免动画干扰匹配。
7. **Appium + UiAutomator2 双层反而更慢**：Appium 多一层 HTTP 中转，纯 Android 原生、不要跨平台时，直接用 `uiautomator2` 库更轻快。
8. **Poco 控件名随版本乱改导致用例脆**：游戏 GameObject 名重构，Poco 选择器全断。游戏侧要约定稳定节点命名或加 `poco` 专用测试 id。
9. **三者混用会话管理混乱**：Appium 管一个 driver、Poco 另起一个，context 切来切去易冲突。架构上要明确「谁主导生命周期」。
10. **选型不看团队技能**：Airtest 的 IDE 对测试同学友好（录屏生成脚本），Appium 对开发更顺手。选型要给团队能力留余量，别为了「先进」选维护不动的。

## 面试怎么答

**30 秒骨架**：UI 自动化选型看「应用形态」。纯 Android 原生、要稳定 CI、要和 WebDriver 协议对齐，用 UiAutomator2（或包一层的 Appium）；游戏/自绘引擎在原生树里是黑块，拿不到内部按钮，要用 Poco 拿引擎内 GameObject 节点；连节点都没有的纯画面/动画，只能用 Airtest 图像识别。Airtest 和 Poco 是网易姊妹，常组合——Poco 控控件、Airtest 兜底画面。

**追问**：那 Appium 还有必要吗？——要跨平台统一（Android+iOS 一套脚本）、要和标准 Selenium/WebDriver 生态对齐时 Appium 仍是首选；纯 Android 且不要跨端，直接用 `uiautomator2` 库更轻。选型核心是「应用形态」而非「工具流行度」。

## 参考

- [UiAutomator2 文档](https://github.com/openatx/uiautomator2)
- [Airtest 文档](https://airtest.readthedocs.io/)
- [Poco 文档](https://poco.readthedocs.io/)
- 相关笔记：[[Appium 架构原理与工作流程]]、[[Appium 控件定位策略]]、[[Native 与 WebView 上下文切换]]
