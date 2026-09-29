---
created: 2026-07-31
tags: [Web自动化测试/环境]
---

# Selenium 环境搭建与 Selenium Manager

> 把「driver 与浏览器版本对不上」这个新手第一天就会遇到的问题一次讲清，并说明 Selenium 4.6+ 的 Selenium Manager 是怎么把它自动化掉的。

## 概念

### Selenium 的三层结构

写 `driver.find_element(...)` 时，实际发生的事情横跨三个进程：

```text
测试脚本（Python 进程）
   │  HTTP + JSON（W3C WebDriver 协议）
   ▼
chromedriver / geckodriver（本地驱动进程，监听 127.0.0.1:随机端口）
   │  浏览器私有调试协议（Chrome 是 CDP）
   ▼
Chrome / Firefox 浏览器进程
```

三个关键推论：

1. **Selenium 本身不控制浏览器**，它只是 W3C WebDriver 协议的一个 HTTP 客户端。`click()` 这类调用被序列化成 `POST /session/{id}/element/{eid}/click` 发给 driver。
2. **driver 是浏览器厂商提供的**，chromedriver 由 Chrome 团队维护，geckodriver 由 Mozilla 维护。所以 **driver 版本必须与本机浏览器主版本匹配**——driver 内部按对应版本的浏览器内部协议实现，版本错位时握手就会失败。
3. **网络调用有成本**。每一次 `find_element` 都是一次进程间 HTTP round-trip（毫秒级）。这解释了后面「为什么显式等待的轮询间隔不能设太小」「为什么隐式等待会拖慢整个用例」。

### 版本匹配为什么老出问题

Chrome 是**自动静默升级**的。你今天调通的脚本，明天 Chrome 后台升到新的大版本，chromedriver 还停在旧版本，于是报：

```text
SessionNotCreatedException: Message: session not created:
This version of ChromeDriver only supports Chrome version 114
Current browser version is 127.0.6533.89
```

Selenium 4.6 之前的解法是手动下载对应 driver、或者用第三方库 `webdriver-manager` 在运行时下载。**Selenium 4.6+ 内置了 Selenium Manager**，把这件事收进了官方实现。

### Selenium Manager 做了什么

Selenium Manager 是一个用 Rust 写的小可执行文件，随 `selenium` 包一起分发。当你 `webdriver.Chrome()` 且**没有显式指定 driver 路径**时，Selenium 会自动调用它：

1. 探测本机浏览器版本（Windows 读注册表 / 可执行文件版本信息，Linux/macOS 执行 `chrome --version`）。
2. 查询官方 endpoint（Chrome for Testing 的 `known-good-versions` 元数据）确定匹配的 driver 版本。
3. 若本地缓存（`~/.cache/selenium`）没有，就下载并缓存。
4. 把 driver 路径回传给 Selenium，启动会话。

**如果本机连浏览器都没有**，Selenium Manager 还能顺带把 Chrome for Testing 浏览器一起下下来（4.11+ 的能力），这对 CI 容器很有用。

## 用法

### 最小可运行脚本（Selenium 4.6+）

```python
# pip install selenium>=4.20
from selenium import webdriver
from selenium.webdriver.common.by import By

driver = webdriver.Chrome()          # 不传 Service，触发 Selenium Manager 自动解析 driver
try:
    driver.get("https://www.selenium.dev/selenium/web/web-form.html")
    print(driver.title)
    driver.find_element(By.NAME, "my-text").send_keys("hello")
    driver.find_element(By.CSS_SELECTOR, "button").click()
    print(driver.find_element(By.ID, "message").text)
finally:
    driver.quit()                     # 必须 quit：否则 driver 进程与浏览器进程都残留
```

`driver.quit()` 与 `driver.close()` 的区别是常考点：

- `close()` 只关**当前窗口**，还有别的窗口时浏览器进程还在。
- `quit()` 结束**整个会话**：关掉所有窗口、终止 driver 进程、释放临时 user-data-dir。

### 显式指定 driver 路径（离线环境 / 内网 CI）

内网机器访问不到 Google 的下载源，Selenium Manager 会失败。这时手动下载 driver 并指定路径：

```python
from selenium import webdriver
from selenium.webdriver.chrome.service import Service

service = Service(
    executable_path=r"D:\drivers\chromedriver.exe",
    log_output="chromedriver.log",     # driver 端日志，排查握手失败时非常有用
    service_args=["--verbose"],
)
driver = webdriver.Chrome(service=service)
```

也可以通过环境变量让 Selenium Manager 走内网镜像：

```bash
# 让 Selenium Manager 从私有镜像取元数据与二进制
export SE_CACHE_PATH=/opt/selenium-cache
export SE_AVOID_BROWSER_DOWNLOAD=true      # 只解析 driver，不下载浏览器
```

### Options：CI 里几乎必配的启动参数

```python
from selenium import webdriver

opts = webdriver.ChromeOptions()
opts.add_argument("--headless=new")        # 新版无头模式，行为最接近有头
opts.add_argument("--window-size=1920,1080")   # 无头默认窗口很小，会导致元素"不可见"
opts.add_argument("--no-sandbox")          # Docker root 用户下必须
opts.add_argument("--disable-dev-shm-usage")   # 容器 /dev/shm 默认 64MB，不加会随机崩
opts.add_argument("--disable-gpu")
opts.page_load_strategy = "eager"          # DOMContentLoaded 就返回，不等图片等资源
opts.add_experimental_option("excludeSwitches", ["enable-automation"])  # 去掉"受自动化控制"提示条

driver = webdriver.Chrome(options=opts)
driver.set_page_load_timeout(30)           # 页面加载超时，超时抛 TimeoutException
driver.set_script_timeout(20)              # 异步 JS 执行超时
```

`page_load_strategy` 三档：

| 取值 | `get()` 何时返回 | 适用 |
|------|----------------|------|
| `normal`（默认） | `load` 事件（所有资源加载完） | 一般页面 |
| `eager` | `DOMContentLoaded` | 图片/埋点多、加载慢的页面 |
| `none` | 收到首字节即返回 | 完全自己控制等待的场景 |

### 用 pytest fixture 封装 driver

真实项目不会在用例里裸建 driver，统一收敛到 conftest：

```python
# conftest.py
import pytest
from selenium import webdriver

@pytest.fixture(scope="function")
def driver(request):
    opts = webdriver.ChromeOptions()
    if request.config.getoption("--headless"):
        opts.add_argument("--headless=new")
        opts.add_argument("--window-size=1920,1080")
    drv = webdriver.Chrome(options=opts)
    drv.implicitly_wait(0)          # 显式关掉隐式等待，避免与显式等待混用
    yield drv
    drv.quit()                       # 无论用例成功失败都回收

def pytest_addoption(parser):
    parser.addoption("--headless", action="store_true", default=False)
```

`scope="function"` 意味着每条用例一个全新浏览器：慢，但**用例间零状态污染**。想提速可以改 `scope="session"` 复用浏览器，但必须在每条用例前清 cookie / localStorage，见 [[UI 测试脏数据清理与数据隔离]]。

## 踩坑

1. **`SessionNotCreatedException: only supports Chrome version X`**
   典型的版本错位。先确认 `selenium` 版本 ≥ 4.6（`pip show selenium`），再删掉代码里写死的 `executable_path` 让 Selenium Manager 接管；如果必须写死，删 `~/.cache/selenium` 缓存后重跑。

2. **Selenium Manager 在内网超时**
   报错形如 `Unsuccessful command executed: selenium-manager --browser chrome`。判断依据是它在尝试访问 `googlechromelabs.github.io`。解法：预置 driver + `Service(executable_path=...)`，或在镜像构建阶段就把 driver 烤进容器，别让运行时联网。

3. **`driver.quit()` 漏掉导致进程泄漏**
   用例异常退出时若没有 `try/finally` 或 fixture 的 `yield` 回收，chromedriver 与 Chrome 会常驻。CI 机器跑几百条后内存被吃光，表现为「后面的用例大面积超时」。排查：`tasklist | findstr chrome`（Windows）或 `ps -ef | grep chromedriver`。

4. **无头模式下元素「不可见」**
   `--headless` 默认窗口约 800×600，右侧元素落在视口外，点击时抛 `ElementNotInteractableException` 或 `ElementClickInterceptedException`。必须同时加 `--window-size=1920,1080`。

5. **Docker 里随机崩溃（`session deleted because of page crash`）**
   容器 `/dev/shm` 默认只有 64MB，Chrome 共享内存不够。加 `--disable-dev-shm-usage`，或 `docker run --shm-size=2g`。

6. **老代码里的 `desired_capabilities` 报 TypeError**
   Selenium 4.10 起彻底移除了 `desired_capabilities` 参数，全部改用 `Options` 对象。同样被移除的还有位置参数形式的 `webdriver.Chrome("chromedriver.exe")`。

7. **`--headless=old` 与 `--headless=new` 行为不一致**
   老无头模式不支持扩展、部分 CSS 渲染有差异，某些用例只在无头下失败。Chrome 112+ 一律用 `--headless=new`。

8. **同时装了多个 Chrome（正式版 + Chrome for Testing）**
   Selenium Manager 探测到的可能不是你以为的那一个。用 `opts.binary_location = r"C:\...\chrome.exe"` 显式指定浏览器可执行文件。

## 面试怎么答

**Q：说一下 Selenium 的工作原理。**
A：Selenium 客户端是 W3C WebDriver 协议的 HTTP 客户端。脚本调用被序列化成 HTTP 请求发给本地的 chromedriver/geckodriver 进程，driver 再通过浏览器私有协议（Chrome 是 CDP）驱动浏览器，结果沿原路返回。所以是「脚本 → driver → 浏览器」三进程结构，每个 API 调用都有一次进程间通信开销，这也是不能滥用 `find_element` 轮询的原因。

**Q：driver 和浏览器版本不匹配怎么解决？**
A：Selenium 4.6 之前用 `webdriver-manager` 这类第三方库在运行时下载匹配的 driver；4.6 之后官方内置了 Selenium Manager，只要不显式传 `Service(executable_path=...)`，它会自动探测浏览器版本、下载并缓存匹配的 driver。内网/离线 CI 建议关掉自动下载，在镜像构建阶段固化 driver 与浏览器版本，保证环境可复现。

**Q：`close()` 和 `quit()` 的区别？**
A：`close()` 关闭当前窗口，会话还在；`quit()` 结束整个会话，关闭所有窗口并终止 driver 进程、清理临时 profile 目录。用例收尾必须 `quit()`，否则 CI 上进程会堆积把内存吃光。

**Q：CI 上跑 UI 用例需要注意什么？**
A：四点。第一，无头模式用 `--headless=new` 且必须指定 `--window-size`，否则元素落在视口外报不可交互；第二，容器里加 `--no-sandbox --disable-dev-shm-usage` 防止随机 crash；第三，driver 与浏览器版本在镜像里固化，不要运行时联网下载，保证可复现和构建速度；第四，driver 生命周期用 fixture 的 `yield` 管理，保证异常时也能回收，避免进程泄漏。

## 参考

- [Selenium 官方文档 · Install browser drivers](https://www.selenium.dev/documentation/webdriver/getting_started/install_drivers/)
- [Selenium Manager 文档](https://www.selenium.dev/documentation/selenium_manager/)
- [W3C WebDriver 规范](https://www.w3.org/TR/webdriver2/)
- 相关笔记：[[Playwright 安装与浏览器管理]]
- 相关笔记：[[Selenium 与 Playwright 选型对比]]
- 相关笔记：[[Selenium Grid 与并行执行]]
- 相关笔记：[[07-Web自动化测试]]
