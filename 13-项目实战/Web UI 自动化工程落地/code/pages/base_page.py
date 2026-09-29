from playwright.sync_api import Page, Locator

class BasePage:
    """所有页面对象的基础抽象类。"""

    def __init__(self, page: Page):
        self.page = page

    def open(self, url: str):
        """跳转至指定目标 URL。"""
        self.page.goto(url, wait_until="domcontentloaded")

    def find(self, selector: str) -> Locator:
        """封装标准定位器，支持链式过滤。"""
        return self.page.locator(selector)

    def find_by_role(self, role: str, **kwargs) -> Locator:
        """优先使用可访问性 Role 语义化定位。"""
        return self.page.get_by_role(role, **kwargs)

    def find_by_placeholder(self, text: str) -> Locator:
        """占位符文本定位。"""
        return self.page.get_by_placeholder(text)

    def get_title(self) -> str:
        """获取当前页面标题。"""
        return self.page.title()

    def get_current_url(self) -> str:
        """获取当前 URL。"""
        return self.page.url
