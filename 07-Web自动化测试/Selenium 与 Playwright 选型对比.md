---
created: 2026-07-31
tags: [Web自动化测试/选型]
---

# Selenium 与 Playwright 选型对比

> 面试必问的「你们为什么用 X 不用 Y」。答案不是「Playwright 更新更好」，而是要能从架构差异推出能力差异，再落到团队约束上。

## 概念

### 一句话结论

**新项目、单团队、以 Chromium 系为主 → Playwright；存量资产多、需要跨语言/跨团队复用、要接老旧浏览器或商业 Grid → Selenium。**

下面把这个结论拆开讲。

### 架构差异是一切差异的根

| 维度 | Selenium 4 | Playwright |
|------|-----------|-----------|
| 通信 | HTTP 短连接，W3C WebDriver 协议 | WebSocket 长连接，私有协议 |
| 中间层 | 各浏览器厂商的 driver 进程 | 自带 Node driver + 自编译浏览器 |
| 事件方向 | 客户端单向发命令，只能轮询 | 双向，浏览器主动推事件 |
| 标准 | W3C 标准，厂商实现 | 非标准，微软单方维护 |

**「浏览器能不能主动推事件给测试端」这一条，几乎决定了后面所有能力差。**

- 能推事件 → 可以在元素「变得可交互的那一刻」立即执行动作 → **自动等待**；
- 能推事件 → 可以拦截每一个网络请求并改写 → **网络 Mock**；
- 能推事件 → 可以完整记录操作、DOM 快照、网络流水 → **Trace Viewer**。

Selenium 要做这些，得绕道 CDP（`driver.execute_cdp_cmd`）或第三方库，且只在 Chromium 系可用。

### 能力对照

| 能力 | Selenium | Playwright |
|------|----------|-----------|
| 等待 | 手写 `WebDriverWait` + `expected_conditions` | 每个动作内置自动等待（可见/稳定/可点/未被遮挡） |
| 定位 | CSS / XPath / id / name 等 8 种 By | 语义定位器 `get_by_role/label/text/test_id` + CSS/XPath |
| iframe | `switch_to.frame()` 有状态切换 | `frame_locator()` 无状态链式穿透 |
| Shadow DOM | 需要 JS 或 `shadow_root`（4.x） | CSS 定位器自动穿透 open shadow root |
| 多标签页 | `window_handles` 手动切 | `context.pages` / `expect_page()` 事件捕获 |
| 网络 Mock | 需接 CDP，仅 Chromium | `page.route()` 全内核支持 |
| 并行 | 起多个 driver / Selenium Grid | 一个 Browser 多 Context，天然轻量并行 |
| 调试 | 截图 + 日志 | Trace Viewer（时间旅行）、Inspector、Codegen |
| 语言 | Java / Python / C# / JS / Ruby / Kotlin | Python / JS / Java / .NET |
| 浏览器 | 所有主流 + IE + 移动端厂商实现 | Chromium / Firefox / WebKit（自编译） |
| 生态 | 20 年积累，Grid、云测（Sauce/BrowserStack）原生支持 | 生态年轻但增长快，云测支持逐渐补齐 |

### 什么时候 Selenium 仍然是对的选择

1. **存量资产大**。已有几千条 Selenium 用例、成熟的 PO 分层，迁移成本远大于收益。
2. **多语言团队**。后端 Java、测开 Python，Selenium 生态跨语言更成熟（尤其 Java）。
3. **必须测真实设备/老浏览器**。IE11、国产浏览器、真机移动端浏览器，Playwright 覆盖不到。
4. **重度依赖商业云测平台**。Sauce Labs / BrowserStack / 自建 Grid 对 WebDriver 协议支持最完备。
5. **合规要求用 W3C 标准**。Playwright 协议是私有的，供应商锁定风险由微软一家承担。

### 什么时候 Playwright 明显更优

1. **新项目、稳定性优先**。自动等待直接消灭了 UI 自动化里 70% 的 flaky 来源。
2. **需要 Mock 后端**。前端联调期、异常分支覆盖（500、超时、空数据），`page.route()` 一行搞定。
3. **CI 上追求速度**。Context 级隔离 + `pytest -n` 并行，同样机器上吞吐量常有数倍差距。
4. **排查失败成本高**。Trace Viewer 能回放每一步的 DOM 快照、控制台、网络，远超「一张失败截图」。
5. **需要移动端仿真、多语言/时区场景**。`device`、`locale`、`timezone_id` 都是 context 级一行配置。

## 用法

同一个「登录并断言用户名」的场景，两边写法对比。

### Selenium 版

```python
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

driver = webdriver.Chrome()
wait = WebDriverWait(driver, 10)
try:
    driver.get("https://example.com/login")
    # 每个元素都要自己想清楚等哪种状态
    wait.until(EC.visibility_of_element_located((By.ID, "username"))).send_keys("qa01")
    driver.find_element(By.ID, "password").send_keys("******")
    wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type=submit]"))).click()
    # 断言也要自己包一层等待，否则会读到旧值
    text = wait.until(
        EC.text_to_be_present_in_element((By.CSS_SELECTOR, "[data-testid=user-name]"), "qa01")
    )
    assert text
finally:
    driver.quit()
```

### Playwright 版

```python
from playwright.sync_api import sync_playwright, expect

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("https://example.com/login")
    # 每个动作内置自动等待，不用写 wait
    page.get_by_label("用户名").fill("qa01")
    page.get_by_label("密码").fill("******")
    page.get_by_role("button", name="登录").click()
    # expect 断言自带轮询重试，直到超时才失败
    expect(page.get_by_test_id("user-name")).to_have_text("qa01")
    browser.close()
```

差别不只是「少写几行」：Selenium 版里**每一处 `wait.until` 都是一个需要人做正确判断的决策点**（等 presence 还是 visibility 还是 clickable），判断错了就是一条 flaky 用例。Playwright 把这个决策内置成了固定的可操作性检查链。

### 迁移策略：不要推倒重来

存量 Selenium 项目想上 Playwright，务实做法是**分层替换而非重写**：

```python
# 1) Page Object 的对外方法签名保持不变
class LoginPage:
    def login(self, user: str, pwd: str) -> "DashboardPage": ...

# 2) 只替换底层驱动实现，业务层与用例层一行不改
#    selenium_impl.py / playwright_impl.py 提供同样的 click / fill / text 原语
```

如果 PO 分层做得好（见 [[Page Object 模式与分层设计]]），迁移成本主要落在页面类内部；如果用例里到处裸写 `driver.find_element`，那就是重写。**这一点本身就是「为什么要做 PO 分层」的最好论据。**

### 混合策略

不少团队的实际选择是：

- **冒烟/核心链路**用 Playwright（快、稳、跑在每次提交上）；
- **兼容性回归**用 Selenium + 云测 Grid（覆盖真实浏览器矩阵，每晚跑一次）。

两套并存的前提是**测试数据构造和断言逻辑走同一套 API 层**，只有 UI 驱动层不同。

## 踩坑

1. **为了「用新东西」而迁移**。没有量化「当前 flaky 率、单轮耗时、定位失败耗时」就动手，迁完发现 flaky 还在——因为根因是测试数据和环境，不是框架。**先测量再选型。**

2. **以为 Playwright 就不会 flaky**。自动等待只解决「元素状态」这一类不稳定。异步数据落库延迟、用例间数据串味、第三方依赖抖动，换框架一个都解决不了。

3. **Playwright 自带 Chromium ≠ 用户的 Chrome**。验收场景要用 `channel="chrome"` 跑真实浏览器，否则可能漏掉只在正式版出现的渲染/编解码差异（比如 H.264 视频，Chromium 开源构建默认不带专有编解码器）。

4. **Selenium 4 已经不是 Selenium 3 了**。面试里还在说「Selenium 只能靠 sleep、不支持相对定位」是知识陈旧。Selenium 4 有相对定位器 `locate_with(...).below(...)`、CDP 接入、`shadow_root`、新的 `Select` 支持。对比要基于 4.x。

5. **两套框架并存却不统一测试数据层**。同一个测试账号被两套用例同时改，跨框架串味，排查时两边互相甩锅。并存必须共用数据构造与清理 API。

6. **只看「哪个写起来短」**。团队技能栈、CI 资源、云测合同、跨语言协作这些约束的权重通常大于语法糖。

## 面试怎么答

**Q：Selenium 和 Playwright 怎么选？**
A：先看约束再看能力。约束层面：存量用例规模、团队语言栈、要不要覆盖 IE/国产浏览器、有没有商业云测合同——这几条任意一条重，就留在 Selenium。没有这些包袱的新项目我选 Playwright，核心理由有三个：一是自动等待把 UI 自动化最大的 flaky 来源（元素状态判断）内置成了框架能力，不再依赖每个人的等待写法水平；二是 Context 级隔离让并行既快又干净，CI 耗时能压下来；三是 Trace Viewer 让失败定位从「看一张截图猜」变成「回放整个过程」，排查成本差一个量级。

**Q：Playwright 的优势具体在哪，底层为什么能做到？**
A：根子在通信架构。Selenium 走 HTTP 短连接的 WebDriver 协议，只能客户端单向发命令、靠轮询感知状态；Playwright 用 WebSocket 长连接，浏览器能主动推事件。有了事件推送，才能做到动作前自动检查元素可见、稳定、可接收事件、未被遮挡，也才能做 `page.route()` 全内核网络拦截和完整 trace 录制。Selenium 想做同类事得绕 CDP，而且只在 Chromium 上可用。

**Q：那 Selenium 是不是要被淘汰了？**
A：不会。Selenium 是 W3C 标准的参考实现，所有浏览器厂商都必须支持 WebDriver 协议；Playwright 协议是私有的，浏览器也是自己编译的构建。真实设备云测、老旧浏览器兼容、跨语言大团队协作这些场景，Selenium 生态仍然不可替代。而且 Selenium 4 也在补课，比如相对定位器和 CDP 接入。技术选型是看约束匹配度，不是看谁新。

**Q：如果让你把存量 Selenium 项目迁到 Playwright，你怎么做？**
A：不重写。先看 PO 分层做得怎么样——如果用例层只调页面对象方法、不碰 driver，那就只替换页面类内部的驱动实现，用例和业务层不动，可以按模块灰度迁移，两套并存跑一段时间对比稳定性和耗时。前提是测试数据构造和清理走统一 API 层，不然两套用例会互相串味。如果用例里到处裸写 `find_element`，那我会先做一轮 PO 重构再谈迁移，因为那种代码换什么框架都难维护。

## 参考

- [Playwright Python 文档](https://playwright.dev/python/)
- [Selenium 文档](https://www.selenium.dev/documentation/)
- [W3C WebDriver 规范](https://www.w3.org/TR/webdriver2/)
- 相关笔记：[[Selenium 环境搭建与 Selenium Manager]]
- 相关笔记：[[Playwright 安装与浏览器管理]]
- 相关笔记：[[Playwright 自动等待机制]]
- 相关笔记：[[Page Object 模式与分层设计]]
- 相关笔记：[[07-Web自动化测试]]
