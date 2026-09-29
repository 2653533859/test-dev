---
created: 2026-07-31
tags: [App自动化测试/专项测试]
---

# App 兼容性测试与云真机平台

> 安卓碎片化是行业之痛：上万机型、几十系统版本、各厂商定制 ROM。兼容性测试回答「我的 App 在哪些设备上能正常用」，云真机把这件事从「买一柜子手机」变成「按需租用」。

![[assets/special-test-matrix.svg]]
*图示：App 专项测试矩阵——弱网 / 来电中断 / 安装卸载升级 / 兼容性四类场景，每类的验证要点（弱网要 loading+重试+文案、升级要 DB 迁移+登录态、卸载要无残留）与对应工具（Charles Throttle / toxiproxy / adb install -r / pm clear）。*

## 概念

### 兼容性要覆盖的维度

| 维度 | 为什么重要 | 典型问题 |
|---|---|---|
| 系统版本 | API 行为差异（如 6.0 权限、7.0 证书、12 分区存储） | 旧版崩溃、新版限制 |
| 厂商 ROM | 小米/华为/OV 定制权限/后台策略 | 后台被杀、推送收不到 |
| 屏幕分辨率/密度 | 布局适配 | 控件重叠、文字截断 |
| 架构 | arm64 / arm32 | 32 位库缺失闪退 |
| 特殊机型 | 折叠屏/刘海屏/挖孔 | 安全区适配错 |

### 云真机平台的原理

云真机平台（AWS Device Farm、Sauce Labs、HeadSpin、国内各厂商云测、阿里 EMAS、腾讯 WeTest）本质是：**机房里摆满真机，通过视频流 + 指令代理把设备暴露到云端**。你把 App 包和脚本传上去，平台在矩阵设备并行执行，回传截图/日志/性能数据。

```text
本地脚本 → 上传 APK + 用例 → 云平台调度 N 台真机并行跑
        → 每台回传：通过/失败、截图、logcat、性能 → 聚合报告
```

## 用法

### 一、本地选机矩阵（自己有设备时）

```yaml
# 兼容性矩阵示例，按优先级挑
matrix:
  - {brand: Google, model: Pixel, api: 34}     # 最新原生机，验新 API
  - {brand: Xiaomi, model: Redmi, api: 29}      # 老系统 + 国产 ROM
  - {brand: Huawei, model: Mate,  api: 30}      # 无 GMS，验推送降级
  - {brand: Samsung, model: S,    api: 33}      # 国际大厂
  - {brand: OPPO,   model: Reno,  api: 31}      # 折叠屏/高刷
```

### 二、把 Appium 脚本接到云真机（以标准 Appium 云为例）

```python
from appium.webdriver.common.appiumby import AppiumBy
from appium.options.android import UiAutomator2Options

# 云平台给你一个远程 Appium Server 地址 + 设备 caps
opts = UiAutomator2Options()
opts.platform_version = "13"
opts.device_name = "Pixel_7_cloud"
opts.app = "https://your-cdn/app.apk"      # 云平台直接装远程包
opts.set_capability("appium:automationName", "UiAutomator2")

# driver 指向云 Appium Server，其余代码完全不变
driver = webdriver.Remote("https://cloud.appium.server/wd/hub", options=opts)
```

云真机的好处是**脚本接口和本地 Appium 完全一致**，只换 `remote` 地址和 caps，不用改测试逻辑。

### 三、用 pytest 在矩阵上并行

![[assets/parallel-multi-device.svg]]
*图示：多设备并行架构——一台机器跑 N 个 Appium Server（--port 错开），每个 session 绑独立的 systemPort / wdaLocalPort 与 udid，pytest-xdist 分发；单机三设备端口分配示例；云真机平台自带并发调度只需换 remote 地址；并行高频翻车点（端口冲突 / udid 未指定 / 设备争抢）。*

```python
@pytest.mark.parametrize("device", DEVICE_MATRIX)
def test_login_on_matrix(driver, device):
    # driver 已按 device 绑定到对应云真机
    login(driver)
    assert is_home(driver)
```

云平台通常自带并发调度，把 `DEVICE_MATRIX` 拆到多台设备并行，单轮耗时 = 单设备耗时而非累加。

### 四、重点兼容场景

```text
必测兼容场景：
  1. 首次安装引导页（各 ROM 权限框文案不同）
  2. 深链接/推送点击拉起（厂商通道差异）
  3. 横竖屏旋转（折叠屏/平板）
  4. 分屏/小窗（MIUI/OxygenOS）
  5. 暗黑模式（系统主题切换）
```

## 踩坑

1. **只测最新系统版本，老版本上线崩**：大量用户还在 Android 11/12，新 API（如分区存储）在旧版行为不同，只测新系统会漏真崩溃。矩阵必须含 2~3 个老版本。
2. **忽略无 GMS 的华为设备**：华为海外机无 Google 服务，依赖 GMS 推送/登录的模块会静默失败。兼容性要单测「无 GMS 降级路径」。
3. **云真机分辨率单一，漏了折叠屏/挖孔适配**：普通机型布局正常，折叠屏展开后安全区算错、挖孔屏刘海遮挡。特殊形态机型要人工或单独纳入。
4. **脚本里写死设备专属坐标**：云真机分辨率各异，写死 `(500,800)` 在别的机型落到空白。兼容测试更该用 `find_ELEMENT` + `element.rect` 相对定位（见 [[Appium 控件定位策略]]）。
5. **云平台并发数不够，兼容性轮次排几小时**：全矩阵串行跑极慢。优先按「崩溃风险」分层——先核心机型快速冒烟，再全量铺开。
6. **不同设备系统语言/时区导致文案/断言错位**：设备默认英文，你的断言里文「登录成功」匹配不到。统一在 caps/setup 里设 `locale`/`language` 为中文。
7. **厂商后台杀进程策略差异让用例在后台失败**：小米/华为激进回收，退后台再回前台 App 被重建，用例假定「还在原页」就红。后台相关用例要覆盖多厂商保活差异。
8. **只跑通没看截图，渲染问题漏掉**：功能断言过了但控件重叠/文字截断肉眼才看得出。兼容性报告必须附关键页面截图人工抽检。
9. **APK 架构不符目标设备**：只打 arm64 包，在老 32 位设备上装不上直接全红。兼容性矩阵里的老设备要对应 `armeabi-v7a` 包。
10. **云真机资源争抢导致偶发超时**：平台设备被别的租户占用或网络抖动，用例偶红。这类「基础设施红」要和「App 红」区分，靠重试 + 平台健康度判断。

## 面试怎么答

**30 秒骨架**：兼容性测试覆盖系统版本、厂商 ROM、分辨率/密度、CPU 架构、特殊形态（折叠/挖孔）五个维度。碎片化太严重，自己买设备不现实，云真机平台把机房真机通过视频流+指令代理暴露到云端，脚本接口和本地 Appium 完全一致，只换 remote 地址和 caps。做法是定义设备矩阵，把核心用例并行铺到矩阵上，回传通过率+截图+日志。兼容性断言不能只靠功能，还要附截图人工抽检渲染问题。

**追问**：怎么选机型矩阵？——按用户画像 Top 机型 + 必含 2~3 个老系统版本 + 至少一台无 GMS 华为 + 一台折叠/挖孔特殊形态，兼顾覆盖率和成本。

## 参考

- [AWS Device Farm 文档](https://docs.aws.amazon.com/devicefarm/)
- 相关笔记：[[Appium 控件定位策略]]、[[Appium 系统权限弹窗处理]]、[[Appium 应用启停、重置与设备状态恢复]]
