---
created: 2026-07-31
tags: [Web自动化测试/进阶]
---

# Selenium Grid 与并行执行

![[assets/grid-topology.svg]]
*图示：Grid 的 Hub-Node 拓扑（Hub 按 capability 把并发 session 路由到不同浏览器的 Node），以及它与「单机多进程并行」「Playwright 分片并行」的对比。*

> 用例从 10 条涨到 1000 条，串行跑要几小时。并行不是「可选项」，是 UI 自动化上规模的必经之路。

## 概念

### 为什么要并行

UI 用例天然慢（启动浏览器、等渲染、等网络）。假设单条平均 8 秒，1000 条串行 ≈ 2.2 小时。并行到 20 个 slot，降到 ~7 分钟。**并行的本质是「用机器换时间」**，让自动化能在 CI 门禁里跑完，而不是隔夜。

### Selenium Grid 是什么

Grid 是 Selenium 官方的「分布式执行」组件，分两层：

- **Hub（中枢）**：接收测试脚本的 session 请求，按 `capabilities`（浏览器、版本、平台）把请求路由到合适的 Node。脚本只连 Hub，不关心背后是哪台机器。
- **Node（节点）**：真正跑浏览器的工作机，向 Hub 注册自己能提供的 capability。

Selenium 4 的 Grid 完全重写了，基于 Netty + WebSocket，**自带一个友好控制台**（`/ui`），并且官方提供了 Docker 镜像，一条命令起整套集群：

```bash
# 一条命令起一个「单机全功能」Grid（含 Hub + 多个浏览器 Node）
docker run -d -p 4444:4444 --shm-size="2g" selenium/standalone-chromium:latest

# 或分布式：先起 Hub，再起 Node 注册
docker run -d -p 4442-4444:4442-4444 selenium/hub:latest
docker run -d --link <hub容器> -e SE_EVENT_BUS_HOST=<hub> \
  -e SE_NODE_GRID_URL=http://<hub>:4444 \
  selenium/node-chromium:latest
```

`--shm-size="2g"` 是经典坑：**Docker 默认 `/dev/shm` 只有 64M，Chrome 渲染大页面会崩**，必须调大（详见 [[Selenium 常见异常排查]] 里的 `chrome not reachable`）。

### 并行 ≠ 无序

并行只是「同时跑多条用例」，但每条用例自己必须**独立可重复**（见 [[UI 测试脏数据清理与数据隔离]]）。如果用例之间靠共享状态串味，并行只会把问题放大成「完全随机失败」。

## 用法

### 脚本侧：把远端地址指向 Hub

```python
from selenium import webdriver
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

# 关键就一行：remote_webdriver 指向 Hub 地址，而不是本地 driver
options = webdriver.ChromeOptions()
options.browser_version = "120"          # 声明需要的版本
options.platform_name = "Linux"           # 声明需要的平台

driver = webdriver.Remote(
    command_executor="http://localhost:4444",   # Hub 地址
    options=options,
)
driver.get("https://example.com")
print(driver.capabilities["browserName"])        # Grid 实际分配到的浏览器
driver.quit()
```

**不需要在脚本机器上装浏览器和 driver**——那是 Node 的事。脚本和 Hub/Node 可以完全分离，这就是 Grid 的价值。

### 并行执行：pytest-xdist（单机多进程）

如果只有一台机器，用 `pytest-xdist` 起多个进程各自开一个 driver 即可，不需要 Grid：

```bash
# -n 4 表示 4 个 worker 进程并发
pytest -n 4
```

```python
# conftest.py：每个 worker 一个独立 driver（注意隔离测试账号/数据）
import pytest

@pytest.fixture
def driver(worker_id):
    opts = webdriver.ChromeOptions()
    opts.add_argument("--headless=new")
    drv = webdriver.Chrome(options=opts)
    yield drv
    drv.quit()
```

`worker_id` 能保证每个进程有独立身份，用来隔离脏数据（见 [[UI 测试脏数据清理与数据隔离]]）。

### 多机并行：Grid + 测试框架的并发

Grid 提供的是「并发 slot」，真正并发调度用例还是靠测试框架。例如 pytest 配合 `pytest-xdist` 把用例分到多进程，每个进程再连 Hub 拿一个 session：

```bash
# 4 个进程，每个进程连 Grid Hub，Hub 把 session 分散到不同 Node
pytest -n 4 --dist=loadfile \
  -o "addopts=--remote-hub=http://grid:4444"
```

要注意**用例分发策略**（`--dist`）：`loadfile` 保证同一文件里的用例在同一进程，便于共享 fixture；`loadscope` 按 module/class 分。选错策略可能导致有依赖的用例被拆到不同进程。

### Playwright 的并行：shard 分片

Playwright 不需要中心 Hub，它靠「多进程 + Context 隔离」天然并行：

```bash
# 把全部用例分 5 片，CI 上起 5 个 job 各跑一片
pytest --browser chromium -n 4
# 或官方 test runner 的分片
npx playwright test --shard=1/5
```

Playwright 的 `BrowserContext` 是「浏览器内的独立空间」（独立 cookie/storage/缓存），天然没有 Selenium 的 profile 串味问题——这是它并行更省心的架构原因，详见 [[Playwright 安装与浏览器管理]]。

### 无头模式与 CI

CI 上没有显示器，必须用**无头模式**，否则起不来：

```python
opts = webdriver.ChromeOptions()
opts.add_argument("--headless=new")     # 新版无头，渲染更接近有头
opts.add_argument("--no-sandbox")       # CI 容器里通常以 root 跑，需要关沙箱
opts.add_argument("--disable-dev-shm-usage")   # 容器 /dev/shm 小，改用 /tmp
opts.add_argument("--window-size=1920,1080")   # 固定窗口，避免布局差异导致的 flaky
```

**`--window-size` 很关键**：无头默认窗口很小，元素可能在视口外导致「找不到/点不到」，且不同机器窗口不一致会让视觉和定位结果漂移。固定窗口能消除这类偶发失败。详见 [[Selenium 常见异常排查]]。

## 踩坑

1. **忘了调 `--shm-size` / `--disable-dev-shm-usage`**
   Chrome 在容器里默认 64M 共享内存，渲染稍大的页就崩，报 `chrome not reachable`。Docker 用 `--shm-size="2g"`，或代码里加 `--disable-dev-shm-usage`。

2. **CI 用 root 跑却没加 `--no-sandbox`**
   root 用户下 Chrome 沙箱会直接失败。容器里加 `--no-sandbox`（仅限可信 CI 环境）。

3. **用例不独立就开并行**
   串行时偶尔串味还能跑，并行后「完全随机失败」。并行前先把脏数据隔离做好。

4. **Grid 版本和 Selenium 客户端版本不匹配**
   Selenium 4 的 Grid 协议和 3 不兼容。客户端 `selenium` 版本要和 Grid 镜像版本对齐。

5. **Node 没注册上 / Hub 看不到 Node**
   通常网络不通或 `SE_NODE_GRID_URL` 配错。看 Hub 控制台 `/ui` 确认 Node 在线再跑。

6. **并行数设太大压垮 Node**
   一个 Node 同时开 30 个 Chrome 会 OOM。按机器内存估算 slot 数（一般每 Chrome ~300-500M）。

7. **无头窗口太小导致 flaky**
   没设 `--window-size`，元素在视口外。固定窗口尺寸。

8. **把测试账号/prefix 当成全局单一**
   多 worker 共用一个账号，互相覆盖。每个 `worker_id` 配独立账号或前缀。

## 面试怎么答

**Q：Selenium Grid 解决什么问题？你怎么并行跑用例？**
A：Grid 解决「分布式执行」——它把 Hub 和 Node 分开，Hub 按 capability 把并发 session 路由到不同机器、不同浏览器的 Node 上，脚本只连 Hub，背后有多少机器、是什么系统它都不关心。这样能把 1000 条用例从串行几小时压到几分钟。并行本身靠测试框架调度：单机我用 pytest-xdist 起多进程，每个进程一个 driver；多机就各进程连 Grid Hub，Hub 再分散到 Node。Playwright 则不需要中心 Hub，靠多进程加 BrowserContext 隔离天然并行。但要注意，并行只是同时跑，每条用例必须独立可重复，脏数据隔离做不好，并行只会把串味放大成完全随机失败。

**Q：CI 上跑浏览器自动化要注意什么？**
A：几条必选项。第一，容器里 `/dev/shm` 默认只有 64M，Chrome 渲染大页面会崩，要么 Docker 设 `--shm-size=2g`，要么加 `--disable-dev-shm-usage`。第二，CI 通常以 root 跑，要加 `--no-sandbox`。第三，无头模式必开 `--headless=new`，而且一定要固定 `--window-size`，不然默认窗口很小，元素在视口外会引发「找不到/点不到」的偶发失败，不同机器窗口不一致还会让结果漂移。第四，浏览器和 driver 版本匹配，现在用 Selenium Manager 基本自动解决了，见 [[Selenium 环境搭建与 Selenium Manager]]。

**Q：Grid 和 pytest-xdist 什么关系？**
A：它们在不同层。Grid 提供的是「远端浏览器的并发能力」——一堆 Node 上有很多 slot 可以同时使用；pytest-xdist 提供的是「用例在本地的并发调度」——把用例分到多个 Python 进程。两者配合：xdist 把用例分到 N 个进程，每个进程连 Grid Hub 拿一个 session，Hub 再把 session 分配到具体 Node。如果只是单机，只用 xdist 起多进程开多个本地 driver 就够了，不需要 Grid。

## 参考

- [Selenium · Grid](https://www.selenium.dev/documentation/grid/)
- [pytest-xdist](https://pytest-xdist.readthedocs.io/)
- [Playwright · Parallel](https://playwright.dev/python/docs/test-runners)
- 相关笔记：[[Selenium 环境搭建与 Selenium Manager]]
- 相关笔记：[[Selenium 常见异常排查]]
- 相关笔记：[[Playwright 安装与浏览器管理]]
- 相关笔记：[[UI 测试脏数据清理与数据隔离]]
- 相关笔记：[[07-Web自动化测试]]
