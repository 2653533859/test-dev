---
created: 2026-09-28
tags: [项目实战/Web自动化测试]
---

# Trace Viewer 与失败自动捕获流水线集成

> 解决 UI 自动化「在 CI 容器挂了却无法复现」的最大痛点：基于 Playwright Tracing 机制实现按需低损耗录制，并在 pytest 失败钩子中自动捕获完整时空现场（DOM、控制台报错、网络请求、录屏与截图），一键挂载至 Allure 报告。

## 概念

在 CI/CD 流水线中，UI 自动化通常在完全没有图形界面的 Linux Docker 容器中以无头（Headless）模式运行。一旦某条复杂的端到端业务用例失败，传统的排查手段存在巨大局限：

1. **单张截图（Screenshot）信息量严重不足**：截图只能展现失败那一瞬间的表象。你无法知道究竟是用户名前一步没有输进去、还是点击按钮根本没有触发事件、亦或是后台接口返回了 500 异常。
2. **文本日志（Logs）缺乏直观视图**：排查人员不得不来回比对前置步骤的时间戳和后台应用日志，耗时动辄半小时以上。

### Playwright Trace Viewer：时空倒流排障神器

Playwright 提供了业界最领先的 **Trace Viewer** 机制。它能够在测试执行过程中，以极低的内存损耗在后台实时抓取：
- **时间轴与逐帧快照（Filmstrip & Snapshots）**：每一步操作（`click`、`fill`、`navigate`）执行前后的实时 DOM 状态，支持无极时间轴倒流查看页面变化。
- **全量网络请求（Network Waterfall）**：页面发起的所有 HTTP/WebSocket 请求、请求头、Payload、响应体与网络状态码。
- **控制台输出与系统调用（Console & Action Metadata）**：前端 JavaScript `console.error` 报错、未捕获的 Promise 异常、Playwright 底层 Actionability 检查详细耗时。

**性能权衡考量**：如果全局给所有用例无脑开启 Trace 和视频录制，会导致磁盘占用骤增且执行耗时增加 30% 以上。最佳实践是**仅失败时保留（`retain-on-failure`）**：在用例执行期间将追踪暂存于内存或临时缓冲区中，用例通过则立即丢弃，仅当用例断言或执行失败时才打包落盘。

## 用法

### 1. pytest-playwright 命令行与配置集成

在最简场景下，`pytest-playwright` 插件原生支持命令行参数：

```bash
# 本地排查或 CI 构建时运行：仅失败保留 trace、视频与截图
pytest --tracing retain-on-failure --video retain-on-failure --screenshot only-on-failure --alluredir=allure-results
```

如果需要在本地回放某次失败生成的 trace 压缩包：

```bash
playwright show-trace allure-results/trace_test_login_failed.zip
# 或者直接在浏览器中打开官方免安装排查器：https://trace.playwright.dev/
```

### 2. conftest.py 自动化钩子与 Allure 报告深度绑定

为了在团队的 Allure 自动化测试报告中直接点开失败截图、播放视频以及打包下载 Trace ZIP 包，需要在 `conftest.py` 中编写 `pytest_runtest_makereport` 钩子。

```python
# tests/conftest.py
import os
import pytest
import allure
from playwright.sync_api import sync_playwright, Page, BrowserContext

@pytest.fixture(scope="function")
def context(browser) -> BrowserContext:
    """为每个测试函数创建隔离的 BrowserContext，开启 Tracing 功能。"""
    # 启动录制时设置 screenshots 与 snapshots 为 True
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        record_video_dir="artifacts/videos/",
    )
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    yield context
    # 正常结束若无失败，直接关闭 context，trace 将不持久化保存
    context.close()

@pytest.fixture(scope="function")
def page(context: BrowserContext) -> Page:
    """创建当前页对象。"""
    page = context.new_page()
    yield page
    page.close()

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """用例执行失败时，自动捕获截图、Trace包并附加至 Allure 报告。"""
    outcome = yield
    report = outcome.get_result()

    if report.when == "call" and report.failed:
        # 获取用例注入的 page 与 context fixture
        page: Page = item.funcargs.get("page")
        context: BrowserContext = item.funcargs.get("context")

        if page:
            # 1. 自动截取当前失败瞬间的屏幕并附加到 Allure
            try:
                screenshot_bytes = page.screenshot(full_page=True)
                allure.attach(
                    screenshot_bytes,
                    name=f"Failure_Screenshot_{item.name}",
                    attachment_type=allure.attachment_type.PNG,
                )
            except Exception as e:
                print(f"截屏失败: {e}")

        if context:
            # 2. 导出 Trace Viewer 压缩包并附加到 Allure
            try:
                os.makedirs("artifacts/traces", exist_ok=True)
                trace_path = f"artifacts/traces/trace_{item.name}.zip"
                context.tracing.stop(path=trace_path)
                
                allure.attach.file(
                    trace_path,
                    name=f"Playwright_Trace_{item.name}",
                    attachment_type="application/zip",
                    extension="zip",
                )
            except Exception as e:
                print(f"保存 Trace 失败: {e}")
```

### 3. CI Pipeline 中的产物归档与展示

在 Jenkinsfile 或 GitHub Actions 中，将生成出来的 Trace 压缩包和 Allure 静态站点自动上传归档：

```yaml
# .github/workflows/ui-test.yml
- name: Run Web UI Automation
  run: |
    pytest tests/ --alluredir=allure-results --clean-alluredir

- name: Archive Playwright Traces
  if: failure()
  uses: actions/upload-artifact@v4
  with:
    name: playwright-traces
    path: artifacts/traces/
    retention-days: 7
```

## 踩坑

1. **Docker 容器下无头浏览器字体乱码与缺失**：
   - 官方 Alpine / Debian 精简镜像默认没有中文字体（如文泉驿微米黑、思源黑体），页面上的中文全部渲染成豆腐块（□□□）。Trace 截图完全无法看清文本。
   - *解法*：在测试执行镜像的 Dockerfile 中显式安装字体支持：
     ```bash
     apt-get update && apt-get install -y fonts-wqy-zenhei fonts-wqy-microhei
     ```
2. **Trace 停止时机不对导致空文件**：
   - 必须确保在 `context.close()` **之前**调用 `context.tracing.stop(path=trace_path)`。一旦 `context` 提前关闭，内存中的录制数据被清空，生成的 trace.zip 仅有几百字节且无法打开。
3. **CI 上 trace 文件过大耗尽磁盘**：
   - 如果遇到包含长视频播放或海量小图片的页面，单条用例生成的 trace.zip 可能达 50MB。必须严格限制 `--tracing=retain-on-failure`，并在 CI 存储策略中配置 `retention-days: 7` 定期清理历史产物。

## 面试怎么答

**Q：你们在 CI 自动化回归失败时，测试人员是如何快速定位根因的？**
> 过去如果无头 CI 报错，传统的 Selenium 只有一张静态红屏截图和一行堆栈报错，排查一次往往要花半小时在本地抓包复现。我们现在的解决方案是**将 Playwright Trace Viewer 深度挂载至 CI 流水线**：
> 1. **全时空可回溯录制**：通过 `retain-on-failure` 策略，平时 0 额外开销，仅当用例断言或交互失败时，自动把整条链路的 DOM 快照、网络请求瀑布流、控制台日志打包成 Trace ZIP。
> 2. **一键还原事故现场**：测试或开发同学点开 Allure 报告或在浏览器打开 `trace.playwright.dev` 拖入文件，就能如同看录像一样随时间轴拖拽，查看失败前每一毫秒页面的真实渲染、网络接口的入参和响应码，彻底消除「在我本地明明能跑」的争议，平均问题定位时长从 30 分钟压到了 2 分钟以内。

## 参考

- Playwright Trace Viewer 官方文档：`https://playwright.dev/python/docs/trace-viewer`
- Allure 官方报告集成：`https://allurereport.org/docs/`
- 相关笔记：[[07-Web自动化测试]]、[[测试报告：pytest-html 与 Allure]]、[[Jenkinsfile 多阶段流水线设计]]
- 所属项目：[[Web UI 自动化工程落地/Web UI 自动化工程落地]]
