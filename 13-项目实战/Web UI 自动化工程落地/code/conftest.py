import os
import pytest
import allure
from playwright.sync_api import Page, BrowserContext

@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """全局配置统一的浏览器视口、语言与缩放，避免无头渲染截断。"""
    return {
        **browser_context_args,
        "viewport": {"width": 1920, "height": 1080},
        "device_scale_factor": 1.0,
        "locale": "zh-CN",
        "ignore_https_errors": True,
    }

@pytest.fixture(scope="function")
def context(browser, browser_context_args) -> BrowserContext:
    """每个用例独享隔离的 BrowserContext，按需录制 Trace。"""
    ctx = browser.new_context(**browser_context_args)
    # 开启追踪录制
    ctx.tracing.start(screenshots=True, snapshots=True, sources=True)
    yield ctx
    ctx.close()

@pytest.fixture(scope="function")
def page(context: BrowserContext) -> Page:
    """用例独享的 Page 对象。"""
    p = context.new_page()
    yield p
    p.close()

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """测试用例执行钩子：失败时捕获屏幕截图、保存 Trace Viewer 并挂载 Allure。"""
    outcome = yield
    report = outcome.get_result()

    if report.when == "call" and report.failed:
        page = item.funcargs.get("page")
        context = item.funcargs.get("context")

        # 1. 失败自动截屏并附加到 Allure
        if page:
            try:
                screenshot_bytes = page.screenshot(full_page=True)
                allure.attach(
                    screenshot_bytes,
                    name=f"Failure_Screenshot_{item.name}",
                    attachment_type=allure.attachment_type.PNG,
                )
            except Exception as e:
                print(f"[conftest] 截屏捕获失败: {e}")

        # 2. 失败导出 Trace 压缩包
        if context:
            try:
                os.makedirs("artifacts/traces", exist_ok=True)
                trace_file = f"artifacts/traces/trace_{item.name}.zip"
                context.tracing.stop(path=trace_file)
                allure.attach.file(
                    trace_file,
                    name=f"Playwright_Trace_{item.name}",
                    attachment_type="application/zip",
                    extension="zip",
                )
            except Exception as e:
                print(f"[conftest] 保存 Trace 失败: {e}")
