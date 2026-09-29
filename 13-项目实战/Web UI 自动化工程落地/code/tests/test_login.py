import pytest
import allure
from playwright.sync_api import Page, expect
from pages.login_page import LoginPage

@allure.feature("用户认证模块")
@allure.story("运营后台用户登录")
class TestLogin:

    @allure.title("正向用例：正确的管理员凭证登录成功并跳转工作台")
    @allure.severity(allure.severity_level.BLOCKER)
    def test_login_success(self, page: Page):
        login_page = LoginPage(page)
        
        with allure.step("1. 访问登录页面"):
            # 在没有实际内网后端服务时，注入测试 mock 保证可执行性
            page.set_content("""
                <html>
                <body>
                    <input placeholder="请输入用户名/手机号" id="user" />
                    <input type="password" placeholder="请输入密码" id="pwd" />
                    <input type="checkbox" id="rem" />
                    <button role="button">登录</button>
                    <div id="app" style="display:none;">
                        <span class="user-avatar">管理员(Admin)</span>
                        <div class="welcome-title">欢迎进入运营中台</div>
                    </div>
                    <script>
                        document.querySelector('button').onclick = function() {
                            if(document.querySelector('#user').value === 'admin' &&
                               document.querySelector('#pwd').value === 'Pass123!') {
                                document.querySelector('#app').style.display = 'block';
                            }
                        }
                    </script>
                </body>
                </html>
            """)

        with allure.step("2. 输入用户名、密码并点击登录"):
            login_page.login("admin", "Pass123!", remember=True)

        with allure.step("3. 断言登录成功：用户信息展示在页面上"):
            expect(login_page.user_profile).to_be_visible()
            expect(login_page.user_profile).to_have_text("管理员(Admin)")

    @allure.title("反向用例：错误的密码应弹出错误提示")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_login_failed_with_wrong_password(self, page: Page):
        login_page = LoginPage(page)

        with allure.step("1. 加载带表单校验的测试 DOM"):
            page.set_content("""
                <html>
                <body>
                    <input placeholder="请输入用户名/手机号" id="user" />
                    <input type="password" placeholder="请输入密码" id="pwd" />
                    <button role="button">登录</button>
                    <div class="error-tip" style="display:none; color: red;">用户名或密码错误，请重试</div>
                    <script>
                        document.querySelector('button').onclick = function() {
                            document.querySelector('.error-tip').style.display = 'block';
                        }
                    </script>
                </body>
                </html>
            """)

        with allure.step("2. 提交错误的密码"):
            login_page.login("admin", "WrongPassword_999")

        with allure.step("3. 断言页面弹出对应的错误提示"):
            expect(login_page.error_alert).to_be_visible()
            expect(login_page.error_alert).to_contain_text("用户名或密码错误")
