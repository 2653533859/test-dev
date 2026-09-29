---
created: 2026-07-31
tags: [Web自动化测试/Playwright]
---

# Playwright 安装与浏览器管理

> Playwright 为什么不需要 driver、`playwright install` 到底装了什么，以及 Browser / Context / Page 三层模型如何决定用例隔离与执行速度。

## 概念

### 没有 driver 这一层

Selenium 是「脚本 → driver 进程 → 浏览器」，Playwright 是：

```text
测试脚本（Python 进程）
   │  WebSocket + JSON（Playwright 私有协议，长连接）
   ▼
Node.js driver（随 playwright 包分发的 server 进程）
   │  CDP（Chromium）/ 各自的调试协议（Firefox、WebKit 打过补丁）
   ▼
Chromium / Firefox / WebKit
```

两个本质差异：

1. **长连接而非短连接**。Selenium 每个命令一次 HTTP 请求，Playwright 走一条 WebSocket 双向通道。因此 Playwright 能**从浏览器侧接收事件推送**（请求发出、对话框弹出、页面新开），这是自动等待、网络拦截能实现得这么干净的底层原因。
2. **浏览器是 Playwright 自己编译分发的**。它下载的 Chromium/Firefox/WebKit 是打过补丁的特定构建，版本与 `playwright` 库严格绑定，所以**永远不存在「driver 和浏览器版本不匹配」这个问题**——版本是锁死的。

代价是浏览器不是你机器上那个正式版 Chrome。要测真实 Chrome 得用 `channel="chrome"`。

### Browser / BrowserContext / Page 三层

这是 Playwright 设计上最值钱的一点，直接决定了它比 Selenium 快：

| 层 | 是什么 | 开销 | 隔离性 |
|----|-------|------|--------|
| `Browser` | 一个浏览器进程 | 重（百毫秒~秒级） | 进程级 |
| `BrowserContext` | 浏览器内的一个「独立隐身会话」 | 极轻（毫秒级） | cookie / localStorage / 缓存 / 权限完全隔离 |
| `Page` | 一个标签页 | 轻 | 共享所属 context 的存储 |

Selenium 想要用例间零污染，只能每条用例开一个新浏览器（贵）。Playwright 可以**一个 Browser 复用到底，每条用例开一个新 Context**——隔离等价于新开浏览器，成本却只有几毫秒。这是并行执行能力的基础。

## 用法

### 安装

```bash
pip install playwright
playwright install                 # 下载 chromium + firefox + webkit（约 500MB~1GB）
playwright install chromium        # 只装 chromium，CI 上强烈建议这样
playwright install --with-deps chromium   # Linux 上顺带装系统依赖库（需要 sudo）
```

`playwright install` 把浏览器下载到：

- Windows：`%USERPROFILE%\AppData\Local\ms-playwright`
- Linux：`~/.cache/ms-playwright`
- macOS：`~/Library/Caches/ms-playwright`

可以用环境变量改路径，CI 上常用来做缓存：

```bash
export PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright   # 自定义目录，便于容器层缓存
export PLAYWRIGHT_BROWSERS_PATH=0                    # 装到 pip 包目录内（随虚拟环境走）
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1            # 镜像里已内置浏览器时跳过下载
```

### 同步 API 最小示例

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=200)   # slow_mo：每步慢放 200ms，调试神器
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        ignore_https_errors=True,          # 测试环境自签证书
    )
    page = context.new_page()
    page.goto("https://playwright.dev/python/")
    page.get_by_role("link", name="Get started").click()
    print(page.title())
    context.close()
    browser.close()
```

注意 `with sync_playwright() as p` 这层：它启动/回收那个 Node driver 进程，忘了会残留。

### 用 pytest-playwright 插件（推荐）

```bash
pip install pytest-playwright
pytest --browser chromium --headed --slowmo 300 -n 4
```

插件直接提供 `page` / `context` / `browser` fixture，**`page` 是 function 级、每条用例自动开新 context**，隔离与回收都不用自己写：

```python
# test_login.py
from playwright.sync_api import Page, expect

def test_login(page: Page):
    page.goto("https://example.com/login")
    page.get_by_label("用户名").fill("qa01")
    page.get_by_label("密码").fill("******")
    page.get_by_role("button", name="登录").click()
    expect(page.get_by_test_id("user-name")).to_have_text("qa01")   # 自带重试的断言
```

常用命令行参数：

```bash
pytest --headed                 # 有头模式
pytest --browser firefox --browser webkit    # 多浏览器跑同一批用例
pytest --tracing retain-on-failure           # 失败时保留 trace
pytest --video retain-on-failure --screenshot only-on-failure
pytest --device "iPhone 13"                  # 移动端仿真
```

### 用真实 Chrome / Edge 而不是 Chromium

```python
browser = p.chromium.launch(channel="chrome")        # 本机安装的正式版 Chrome
browser = p.chromium.launch(channel="msedge")        # 本机 Edge
```

先 `playwright install chrome` 或确保本机已装。**验收/兼容性测试建议用 `channel="chrome"`**，功能回归用自带 Chromium（版本可控、下载可缓存）。

### 登录态复用：storage_state

UI 用例最大的时间浪费是每条都重登一遍。Playwright 用 `storage_state` 把 cookie + localStorage 序列化成 JSON 复用：

```python
# 1) 只登录一次，落盘
context = browser.new_context()
page = context.new_page()
page.goto("https://example.com/login")
page.get_by_label("用户名").fill("qa01")
page.get_by_label("密码").fill("******")
page.get_by_role("button", name="登录").click()
page.wait_for_url("**/dashboard")
context.storage_state(path="state.json")      # 存下来
context.close()

# 2) 后续每条用例基于它开 context —— 秒进已登录状态，且 context 之间仍互相隔离
logged_in = browser.new_context(storage_state="state.json")
```

配合 pytest 就是一个 session 级 fixture 生成 `state.json`，function 级 fixture 用它建 context。

### 异步 API

```python
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto("https://example.com")
        print(await page.title())
        await browser.close()

asyncio.run(main())
```

同步 API 底层其实就是把异步 API 包了一层（`greenlet` 驱动）。**同一进程里不要混用 sync 和 async API**，会报 `It looks like you are using Playwright Sync API inside the asyncio loop`。

## 踩坑

1. **`Executable doesn't exist at .../chrome-1091/chrome-win/chrome.exe`**
   装了 `playwright` 但忘了 `playwright install`，或者升级了 `playwright` 版本后浏览器构建号变了。解法：重新跑 `playwright install`。CI 上把 `pip install` 与 `playwright install` 绑在同一层，别只缓存其中一个。

2. **CI 镜像体积失控**
   默认三个内核近 1GB。只装需要的：`playwright install chromium`。或者直接用官方镜像 `mcr.microsoft.com/playwright/python:v1.4x.0-jammy`（浏览器与系统依赖都已内置，配合 `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`）。

3. **Linux 缺系统依赖**：报 `Host system is missing dependencies to run browsers`。跑 `playwright install-deps` 或 `playwright install --with-deps chromium`（需要 root）。

4. **`sync_playwright()` 没有用 `with`**
   Node driver 进程不回收，跑久了几十个残留进程。要么用 `with`，要么手动 `p.stop()`。

5. **`browser.new_page()` 与 `context.new_page()` 混淆**
   `browser.new_page()` 会隐式创建一个一次性 context。图省事没问题，但如果你想复用 `storage_state` 或设置 viewport/locale，必须显式 `new_context()`。

6. **默认 viewport 是 1280×720，不是最大化**
   Playwright 无头/有头都用固定 viewport。响应式站点在 720p 下可能走移动端布局，导致定位器全线失效。显式设 `viewport={"width":1920,"height":1080}`，或 `no_viewport=True` 跟随窗口。

7. **`storage_state` 存不下 sessionStorage**
   `storage_state` 只包含 cookie 和 localStorage。依赖 sessionStorage 的登录态要用 `context.add_init_script()` 手动注入。

8. **超时单位是毫秒**
   `page.set_default_timeout(30)` 不是 30 秒而是 30 毫秒，会导致所有操作瞬间超时。正确写法 `page.set_default_timeout(30_000)`。

## 面试怎么答

**Q：Playwright 和 Selenium 在架构上的区别？**
A：Selenium 走 W3C WebDriver 协议，脚本每个命令一次 HTTP 请求发给独立的 driver 进程，driver 再驱动浏览器；Playwright 用一条 WebSocket 长连接连到自带的 Node driver，能双向通信、接收浏览器事件推送。所以 Playwright 能天然实现自动等待、网络拦截、事件监听，而 Selenium 这些能力要么靠客户端轮询，要么得单独接 CDP。另外 Playwright 的浏览器是自己分发的固定构建，不存在版本匹配问题。

**Q：Playwright 的 Context 是什么，有什么用？**
A：BrowserContext 是浏览器内的独立会话，cookie、localStorage、缓存、权限完全隔离，创建成本只有毫秒级。它让「用例级完全隔离」变得很便宜：一个 Browser 进程复用到底，每条用例开一个新 context，效果等同新开浏览器但快几个数量级。这是 Playwright 并行执行比 Selenium 有优势的核心。

**Q：UI 用例每条都要登录，太慢怎么优化？**
A：用 `storage_state` 把登录后的 cookie + localStorage 落盘成 JSON，session 级只登录一次；每条用例用 `browser.new_context(storage_state="state.json")` 建 context，直接进入已登录态，用例之间还是互相隔离的。要跑多角色就存多份 state。Selenium 侧的等价做法是 `driver.add_cookie()` 注入 cookie，但对 localStorage 就要额外用 JS 注入了。

**Q：Playwright 在 CI 上怎么部署？**
A：优先用官方镜像 `mcr.microsoft.com/playwright/python:vX-jammy`，浏览器和系统依赖都内置，配 `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` 避免运行时下载。自建镜像的话在构建阶段执行 `playwright install --with-deps chromium`，只装需要的内核控制体积，并把 `PLAYWRIGHT_BROWSERS_PATH` 指到固定目录方便做层缓存。

## 参考

- [Playwright Python · Installation](https://playwright.dev/python/docs/intro)
- [Playwright · Browsers](https://playwright.dev/python/docs/browsers)
- [Playwright · Authentication（storage_state）](https://playwright.dev/python/docs/auth)
- 相关笔记：[[Selenium 环境搭建与 Selenium Manager]]
- 相关笔记：[[Playwright 自动等待机制]]
- 相关笔记：[[Playwright 语义定位器]]
- 相关笔记：[[07-Web自动化测试]]
