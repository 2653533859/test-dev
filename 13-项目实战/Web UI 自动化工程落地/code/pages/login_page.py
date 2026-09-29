from playwright.sync_api import Page, Locator
from pages.base_page import BasePage

class LoginPage(BasePage):
    """SaaS 后台运营系统登录页面对象。"""

    LOGIN_URL = "https://demo.playwright.dev/login"

    def __init__(self, page: Page):
        super().__init__(page)
        # 页面专属控件定位器（惰性求值）
        self.username_input = self.find_by_placeholder("请输入用户名/手机号")
        self.password_input = self.find_by_placeholder("请输入密码")
        self.login_btn = self.find_by_role("button", name="登录")
        self.remember_checkbox = self.find("input[type='checkbox']")
        self.error_alert = self.find(".ant-alert-message, .error-tip")
        self.user_profile = self.find(".user-avatar, .ant-dropdown-link")

    def load(self):
        """加载登录页面。"""
        self.open(self.LOGIN_URL)
        return self

    def login(self, username: str, password: str, remember: bool = False):
        """核心业务动作：执行登录操作。"""
        self.username_input.fill(username)
        self.password_input.fill(password)
        if remember:
            self.remember_checkbox.check()
        self.login_btn.click()

    def get_error_message(self) -> str:
        """获取登录失败后的错误提示信息。"""
        return self.error_alert.inner_text().strip()
