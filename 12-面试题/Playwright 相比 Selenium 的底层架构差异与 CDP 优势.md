---
created: 2026-09-28
tags: [面试题/Web自动化测试]
---

# Playwright 相比 Selenium 的底层架构差异与 CDP 优势

> Selenium 基于 W3C WebDriver 标准通过无状态的 HTTP REST API 与各独立 Driver 进程单向轮询交互；而 Playwright 通过单一长连接的双向 WebSocket 直接基于 CDP（Chrome DevTools Protocol）协议与浏览器内核通信，支持底层事件驱动监听、原生自动等待（Auto-wait）与毫秒级 BrowserContext 虚拟环境隔离。

## 30 秒回答骨架

- **通讯架构差异**：
  - **Selenium (W3C WebDriver)**：客户端（Python 代码） $\xrightarrow{\text{HTTP POST/GET}}$ 各浏览器独立 Driver 进程（如 `chromedriver.exe`） $\xrightarrow{\text{内部专有协议}}$ 浏览器。每次查找元素、点击都是一次独立的 HTTP 短请求与轮询，往返延迟大且缺乏双向事件通知机制。
  - **Playwright**：语言绑定端通过 Pipe 或单一长连接与 Node.js 驱动核心通信，驱动核心通过**单一双向 WebSocket 长连接**直接驱动浏览器底层（针对 Chromium 系列基于 CDP 协议，针对 Firefox/WebKit 基于打补丁的原生底层协议）。
- **核心能力差异**：
  1. **原生自动等待（Auto-wait）**：在对元素执行点击、输入前，Playwright 会原生等待元素经历 Attached $\rightarrow$ Visible $\rightarrow$ Stable（动画结束） $\rightarrow$ Enabled $\rightarrow$ Not Obscured（未被遮挡），彻底解决 Selenium 常见的 `StaleElementReferenceException` 和动画拦截；
  2. **多上下文隔离（BrowserContext）**：Selenium 隔离必须重启整个浏览器进程（耗时数秒）；Playwright 启动一次浏览器内核，可毫秒级创建上百个彼此完全隔离的 `BrowserContext`（独立的 Cookie、LocalStorage、Cache 堆栈），支持极致轻量的测试用例并行；
  3. **原生网络拦截与 Tracing**：原生支持在内核层拦截/修改/Mock 网络请求（`page.route`），并内置了包含完整 DOM 快照、操作录屏与网络时序的 Trace Viewer。

## 展开

### 1. 通讯链路与拓扑对比

```text
Selenium (WebDriver 体系)：
+----------------+      HTTP REST       +--------------------+      私有协议      +------------+
| Python Client  | -------------------> | chromedriver.exe   | ----------------> | Chrome 进程 |
| (测试脚本)     | <------------------- | (中间代理进程)      | <---------------- |            |
+----------------+   每次操作一次往返    +--------------------+   (难以直接监听事件)+------------+

Playwright 体系：
+----------------+      Node Pipe       +--------------------+   双向 WebSocket   +------------+
| Python Client  | <==================> | Playwright Core    | <================> | Chromium   |
| (测试脚本)     |     (异步进程通信)    | (内置驱动引擎)      |    (CDP 协议事件)  | (内核级操作)|
+----------------+                      +--------------------+                   +------------+
```

- **Selenium 的缺陷**：HTTP 协议是单向被动的（Request-Response），Selenium 要知道“元素是否出现在页面中”，必须每隔 500ms 不断向 `chromedriver` 发送 HTTP 请求进行轮询；网络延迟与进程间调度使得每次动作都存在额外开销。
- **Playwright 的优势**：WebSocket 是全双工的，浏览器内部 DOM 变化、网络包收发、控制台报错都可以作为**事件（Events）**主动推送到 Playwright 端，几乎实现零轮询延迟响应。

### 2. Auto-wait 状态机判定机制

在 Selenium 中，`driver.find_element().click()` 常常因为按钮还在淡入动画或者被半透明 Loading 遮挡，直接抛出 `ElementClickInterceptedException`。

而在 Playwright 中，执行 `page.locator("button").click()` 时，内核会自动按顺序校验 Actionability Checklist（可操作性检查表）：

```text
[发起 click()] 
     |
     v
1. Attached to DOM? (元素已挂载进 DOM 树)
     | 是
     v
2. Visible? (元素非 hidden，宽高非 0，display/opacity 正常)
     | 是
     v
3. Stable? (连续两帧 requestAnimationFrame 中元素坐标未移动，动画结束)
     | 是
     v
4. Receives Events? (执行点命中测试，坐标点未被遮罩、浮层拦截)
     | 是
     v
5. Enabled? (无 disabled 属性)
     | 是
[执行真实操作系统事件分发 (Dispatch Native Events)]
```
只要任意一步不满足，Playwright 会在超时时间（默认 30s）内自动等待重试，无需编写一行冗余的 `WebDriverWait`。

### 3. Browser vs BrowserContext 的轻量级虚拟化

| 维度 | Selenium | Playwright |
| :--- | :--- | :--- |
| **测试隔离机制** | 每次用例重启一次浏览器窗口（`webdriver.Chrome()`）或频繁调清理 Cookie | 单个 `Browser` 实例下秒级创建多个独立的 `BrowserContext` |
| **初始化耗时** | 启动新浏览器进程：~2000ms - 4000ms | 创建新 BrowserContext：**~10ms - 50ms** |
| **资源开销** | 跑 10 个并行 Worker 需要开 10 个完整浏览器进程，内存占满 | 1 个主进程 + 10 个独立 Context，内存节约 70%+ |
| **网络层控制** | 需借助 Browsermob-Proxy 等重型中间人代理工具 | 原生 `page.route("**/*", handler)`，直接拦截内联请求 |

## 可能被追问的点

- **Playwright 是直接调 Chrome DevTools Protocol (CDP)，那它能支持 Firefox 和 Safari 吗？**
  - 能。Microsoft Playwright 团队对 Chromium 直接使用 CDP；但对 Firefox 和 WebKit（Safari 底层内核），Playwright 是在浏览器源码层面给它们打上了官方补丁（Patches），在内核中注入了与 CDP 类似的全双工控制协议通道。因此，在 Playwright 中测试跨浏览器（Cross-browser）使用的是相同的 API 表现。
- **既然 Playwright 这么强，Selenium 在哪些场景下仍有不可替代的优势？**
  - **真机与遗留环境兼容性**：Selenium 支持真实的移动端 Safari / 真实旧版 IE11，支持通过 Appium 控制真机上的移动浏览器；Playwright 对移动端的支持是通过桌面浏览器模拟 User-Agent、分辨率和触摸事件（Emulation），不是真实真机设备。
  - **庞大的企业级基础设施**：已建成的 Selenium Grid / 商业云测平台（Sauce Labs、BrowserStack）对 WebDriver 支持历史积累更成熟。
- **什么是 Playwright Trace Viewer？相比传统的截图和录屏有什么优势？**
  - 传统方案：失败时只能看一张静态 PNG 截图或一段 MP4 视频，无法知道失败瞬间的 DOM 结构、网络请求细节和控制台日志。
  - Trace Viewer：保存的是结构化 Zip 包，解压后可以在本地以交互式方式审查：可拖动时间轴回到过去任意毫秒、动态查看每个动作前后的 DOM 快照（可以在旧快照上审查元素！）、查看完整的请求头/响应体以及 Console 日志。

## 结合自己项目的例子

在公司中后台管理系统（包含大量复杂的 Ant Design 表单、树形表格与拖拽看板）的自动化测试建设中，最初基于 Selenium 编写了 400 多个用例。

- **痛点**：
  1. 表格行拖拽重排用 Selenium `ActionChains` 极不稳定，因为没有原生等待拖拽占位符动画稳定，偶发失败率高达 28%；
  2. 每个用例为了隔离数据重启浏览器，400 条用例在 4 个线程上跑完要耗费 35 分钟；
  3. 前端由于引入了 SSO 单点登录，每次启动新浏览器都要重走完整的账密登录与验证码校验。
- **技术升级**：
  1. **全面迁移至 Playwright (Python)**：
  2. **StorageState 鉴权持久化**：在 global-setup 中仅登录一次，将 Cookie 和 LocalStorage 状态保存为 `auth_state.json`；每个新用例以 `browser.new_context(storage_state="auth_state.json")` 秒级唤起已登录状态；
  3. **利用 Auto-wait 解决拖拽**：使用 `page.locator().drag_to()` 原生完成拖拽交互，彻底告别等待动画的手动 sleep；
  4. **开启网络 Mock 加速**：对于非本链路核心的报表图表和静态资源，直接通过 `page.route` 进行本地 Mock 拦截或请求 abort。
- **收益**：执行时间从 35 分钟大幅降至 **4 分 10 秒**，执行稳定性提升至 99.6%，CI 反馈效率提升近 9 倍。

## 参考

- Playwright 官方架构文档：*Architecture & Auto-waiting*
- Chrome DevTools Protocol 官方规范
- 相关笔记：[[07-Web自动化测试]]、[[显式等待与隐式等待的区别]]、[[自动化测试用例高频偶发失败（Flaky）的系统性治理]]
