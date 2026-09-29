---
created: 2026-07-31
tags: [Web自动化测试/PageObject]
---

# Page Object 模式与分层设计

![[assets/page-object-layers.svg]]
*图示：四层分层结构与各层的改动来源——一次改动只应穿透一层，90% 的维护落在页面对象层，换驱动框架只改基础操作层。*

> PO 不是「把选择器抽成常量」这么简单。它要解决的是「前端改一个按钮，测试要改几十个文件」这个真问题。

## 概念

### 没有 PO 的样子

```python
def test_login_success(driver):
    driver.get("https://example.com/login")
    driver.find_element(By.ID, "username").send_keys("qa01")
    driver.find_element(By.ID, "password").send_keys("******")
    driver.find_element(By.CSS_SELECTOR, "button.submit").click()
    WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.ID, "welcome")))
    assert driver.find_element(By.ID, "welcome").text == "欢迎，qa01"
```

单看没问题。但当你有 50 条用例都要先登录，前端把 `button.submit` 改成 `button.btn-login` 时——**你要改 50 个地方**。而且这 50 处的等待写法各不相同，有的用了 presence 有的用了 visibility，稳定性参差不齐。

### PO 的核心主张

**把「页面长什么样、怎么操作」的知识，集中到一个地方。**

用例层只表达业务意图：

```python
def test_login_success(driver):
    dashboard = LoginPage(driver).open().login("qa01", "******")
    assert dashboard.welcome_text() == "欢迎，qa01"
```

前端改版时，只改 `LoginPage` 这一个类。

### 四层结构（对应上图）

| 层 | 职责 | 允许出现 | 禁止出现 |
|----|------|---------|---------|
| **用例层** | 描述业务场景与断言 | 页面对象、业务流程对象、`assert` | `driver`、`By`、`WebDriverWait`、选择器 |
| **业务流程层** | 编排跨页面的完整链路 | 页面对象 | 元素操作、断言 |
| **页面对象层** | 一个页面的定位与动作 | 定位常量、页面动作方法 | `assert`、测试数据 |
| **基础操作层** | 带等待的操作原语 | `driver`、`WebDriverWait`、日志 | 业务语义 |

**分层的唯一判据：一次改动应该只穿透一层。**

- 需求变了 → 只改用例层；
- 流程顺序变了 → 只改业务流程层；
- 前端改版 → 只改页面对象层；
- 换驱动框架 → 只改基础操作层。

如果某类改动总是要动两层以上，说明分层错了。

### 两条最容易违反的规则

**规则一：页面对象里不写断言。**

页面对象的职责是「提供操作和查询」，判断对错是用例的事。写成 `page.assert_login_success()` 会导致：同一个页面被不同用例复用时，断言逻辑要么不够用要么过度；失败信息也难以定位到具体用例意图。**页面对象提供 `welcome_text()`，用例来 `assert`。**

例外：**页面自身的完整性检查**（比如 `open()` 后确认页面确实加载了）可以放在页面对象里，因为那是「页面就绪」而不是「业务正确」。

**规则二：页面对象方法要用业务语言，不是操作语言。**

```python
page.click_submit_button()      # ✗ 操作语言，泄漏了实现
page.login(user, pwd)           # ✓ 业务语言
```

业务语言的好处是：前端把「提交按钮」改成「回车提交」，`login()` 的签名不变，用例一行都不用改。

## 用法

### 基础操作层：BasePage

```python
# framework/base_page.py
import logging
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

logger = logging.getLogger(__name__)
Locator = tuple[str, str]


class BasePage:
    """所有页面对象的基类：提供带等待、带日志的操作原语。"""

    url_path: str = ""              # 子类覆盖，相对路径
    ready_locator: Locator | None = None   # 子类覆盖，判断页面是否加载完成

    def __init__(self, driver: WebDriver, base_url: str = "", timeout: int = 10):
        self.driver = driver
        self.base_url = base_url
        self.wait = WebDriverWait(driver, timeout)

    # --- 页面级 ---
    def open(self):
        self.driver.get(self.base_url + self.url_path)
        return self.wait_until_ready()

    def wait_until_ready(self):
        if self.ready_locator:
            self._wait_visible(self.ready_locator, "页面就绪标志")
        return self

    # --- 操作原语：每个都内置正确的等待条件 ---
    def click(self, locator: Locator, desc: str = ""):
        logger.info("点击 %s", desc or locator)
        self._wait(EC.element_to_be_clickable(locator), desc, "变为可点击").click()
        return self

    def fill(self, locator: Locator, text: str, desc: str = ""):
        logger.info("输入 %s = %s", desc or locator, text)
        el = self._wait_visible(locator, desc)
        el.clear()
        el.send_keys(text)
        return self

    def text_of(self, locator: Locator, desc: str = "") -> str:
        return self._wait_visible(locator, desc).text

    def is_present(self, locator: Locator) -> bool:
        return bool(self.driver.find_elements(*locator))     # 前提：隐式等待为 0

    def wait_gone(self, locator: Locator, desc: str = ""):
        self._wait(EC.invisibility_of_element_located(locator), desc, "消失")
        return self

    # --- 内部：统一异常信息 ---
    def _wait_visible(self, locator: Locator, desc: str = ""):
        return self._wait(EC.visibility_of_element_located(locator), desc, "可见")

    def _wait(self, condition, desc: str, what: str):
        try:
            return self.wait.until(condition)
        except TimeoutException as e:
            raise TimeoutException(
                f"[{self.__class__.__name__}] 等待「{desc or condition}」{what} 超时"
            ) from e
```

**这一层的价值**：

1. 每个操作都自带**正确**的等待条件，写用例的人不需要每次判断；
2. 统一日志，失败时能看到完整操作序列；
3. 异常信息带上页面类名和元素描述，排查从「猜」变成「看」；
4. **换成 Playwright 时只改这个类**（见 [[Selenium 与 Playwright 选型对比]]）。

### 页面对象层

```python
# pages/login_page.py
from selenium.webdriver.common.by import By
from framework.base_page import BasePage


class LoginPage(BasePage):
    url_path = "/login"
    ready_locator = (By.CSS_SELECTOR, "[data-testid='login-form']")

    # 定位常量：全部集中在类属性，改版只改这里
    USERNAME = (By.CSS_SELECTOR, "[data-testid='login-username']")
    PASSWORD = (By.CSS_SELECTOR, "[data-testid='login-password']")
    SUBMIT = (By.CSS_SELECTOR, "[data-testid='login-submit']")
    ERROR_MSG = (By.CSS_SELECTOR, "[data-testid='login-error']")

    def login(self, username: str, password: str) -> "DashboardPage":
        """登录成功，返回下一个页面对象。"""
        self.fill(self.USERNAME, username, "用户名")
        self.fill(self.PASSWORD, password, "密码")
        self.click(self.SUBMIT, "登录按钮")
        return DashboardPage(self.driver, self.base_url).wait_until_ready()

    def login_expecting_failure(self, username: str, password: str) -> "LoginPage":
        """登录失败，停留在当前页。"""
        self.fill(self.USERNAME, username, "用户名")
        self.fill(self.PASSWORD, password, "密码")
        self.click(self.SUBMIT, "登录按钮")
        return self

    def error_message(self) -> str:
        return self.text_of(self.ERROR_MSG, "错误提示")
```

**两个设计要点**：

1. **成功和失败路径分成两个方法**。因为它们返回不同的页面对象，混在一起返回类型不确定，调用方没法链式。
2. **方法返回下一个页面对象**，这是 PO 里「页面跳转」的标准表达，让链式调用成为可能。

```python
# pages/dashboard_page.py
class DashboardPage(BasePage):
    url_path = "/dashboard"
    ready_locator = (By.CSS_SELECTOR, "[data-testid='user-name']")

    USER_NAME = (By.CSS_SELECTOR, "[data-testid='user-name']")
    ORDER_MENU = (By.CSS_SELECTOR, "[data-testid='nav-order']")

    def welcome_text(self) -> str:
        return self.text_of(self.USER_NAME, "用户名")

    def go_to_orders(self) -> "OrderListPage":
        self.click(self.ORDER_MENU, "订单菜单")
        return OrderListPage(self.driver, self.base_url).wait_until_ready()
```

### 列表页：组件化拆分

页面里的表格、卡片列表这类重复结构，抽成独立的**组件对象**，而不是把方法全塞进页面类：

```python
class OrderRow:
    """订单列表中的一行，是一个组件对象而非页面对象。"""

    def __init__(self, page: BasePage, order_no: str):
        self.page = page
        self.order_no = order_no
        self.root = (
            By.CSS_SELECTOR,
            f"[data-testid='order-item'][data-order-no='{order_no}']",
        )

    def _child(self, css: str) -> tuple[str, str]:
        return (By.CSS_SELECTOR, f"{self.root[1]} {css}")

    def status(self) -> str:
        return self.page.text_of(self._child("[data-testid='status']"), f"订单{self.order_no}状态")

    def cancel(self) -> "OrderRow":
        self.page.click(self._child("[data-testid='cancel']"), f"订单{self.order_no}取消按钮")
        return self


class OrderListPage(BasePage):
    url_path = "/orders"
    ready_locator = (By.CSS_SELECTOR, "[data-testid='order-list']")

    SEARCH_INPUT = (By.CSS_SELECTOR, "[data-testid='order-search']")

    def search(self, keyword: str) -> "OrderListPage":
        self.fill(self.SEARCH_INPUT, keyword, "搜索框")
        self.click((By.CSS_SELECTOR, "[data-testid='search-btn']"), "搜索按钮")
        return self

    def row(self, order_no: str) -> OrderRow:
        return OrderRow(self, order_no)
```

用例里读起来就是自然语言：

```python
def test_cancel_order(driver, base_url, an_order):
    orders = LoginPage(driver, base_url).open().login("qa01", PWD).go_to_orders()
    row = orders.search(an_order.no).row(an_order.no)
    row.cancel()
    assert row.status() == "已取消"
```

**组件化是避免「上帝页面类」的关键**。一个页面类超过 300 行就该考虑拆组件了。

### 业务流程层

跨多个页面的完整链路，不适合放在任何单个页面对象里：

```python
# business/order_flow.py
class OrderFlow:
    """下单主流程：编排多个页面对象，不直接操作元素。"""

    def __init__(self, driver, base_url):
        self.driver = driver
        self.base_url = base_url

    def place_order(self, sku: str, address: str) -> str:
        """从商品页走完整下单流程，返回订单号。"""
        detail = ProductPage(self.driver, self.base_url).open(sku)
        cart = detail.add_to_cart().go_to_cart()
        checkout = cart.checkout()
        checkout.select_address(address)
        result = checkout.submit()
        return result.order_no()
```

用例里就是一行：

```python
def test_order_appears_in_list(driver, base_url):
    order_no = OrderFlow(driver, base_url).place_order("SKU001", "默认地址")
    orders = OrderListPage(driver, base_url).open()
    assert orders.row(order_no).status() == "待付款"
```

**判断要不要加业务流程层**：如果一个链路被三条以上用例复用，就该抽出来。只用一次的不必抽。

### 与 pytest 集成

```python
# conftest.py
import pytest

@pytest.fixture
def base_url():
    return "https://test.example.com"

@pytest.fixture
def login_page(driver, base_url):
    return LoginPage(driver, base_url).open()

@pytest.fixture
def dashboard(login_page):
    """已登录状态，供大部分用例复用。"""
    return login_page.login("qa01", "******")
```

用例直接依赖 `dashboard` fixture，省掉重复的登录步骤。更快的做法是用 cookie 注入跳过 UI 登录，见 [[Selenium JavaScript 执行、滚动与拖拽]]。

### Playwright 版的 PO

Playwright 的 locator 是惰性的，可以**直接把 locator 定义成实例属性**，比 Selenium 的元组常量更优雅：

```python
from playwright.sync_api import Page, expect


class LoginPage:
    def __init__(self, page: Page, base_url: str):
        self.page = page
        self.base_url = base_url
        # locator 惰性求值，在这里定义完全安全
        self.username = page.get_by_label("用户名")
        self.password = page.get_by_label("密码")
        self.submit = page.get_by_role("button", name="登录")
        self.error = page.get_by_test_id("login-error")

    def open(self) -> "LoginPage":
        self.page.goto(f"{self.base_url}/login")
        return self

    def login(self, user: str, pwd: str) -> "DashboardPage":
        self.username.fill(user)
        self.password.fill(pwd)
        self.submit.click()
        return DashboardPage(self.page, self.base_url)
```

因为自动等待内置，**Playwright 的 PO 不需要 BasePage 那层等待封装**，代码量少一半。

## 踩坑

1. **页面对象里写断言**
   `page.assert_login_success()` 让页面对象绑定了特定用例的期望，复用性变差，失败信息也难对应到用例意图。断言留在用例层。

2. **上帝页面类**
   一个类上千行、五十个方法。按功能区拆成组件对象（表格行、筛选栏、弹窗），或者按业务把大页面拆成多个页面对象。

3. **方法名用操作语言**
   `click_submit()`、`input_username()` 泄漏了实现细节，改版时方法名也得跟着改。用 `login()` 这样的业务语义。

4. **用例层出现 `driver` 或 `By`**
   最常见的分层破坏。一旦开了这个口子，PO 就名存实亡。可以加 lint 规则：`test_*.py` 里禁止 `from selenium`。

5. **页面对象里存测试数据**
   `class LoginPage: DEFAULT_USER = "qa01"` 把数据和页面耦合了。数据应该来自 fixture、配置文件或数据工厂。

6. **过度设计：给每个元素写 getter**
   `def get_username_input(self)` 这类方法没有价值，因为它暴露的还是元素而不是行为。直接在业务方法里用定位常量。

7. **链式返回类型写错**
   `login()` 明明跳到了 dashboard 却 `return self`，后续调用全是 `LoginPage` 的方法，IDE 补全失效、类型检查也发现不了。返回值类型注解要准确。

8. **循环 import**
   `LoginPage` 返回 `DashboardPage`，`DashboardPage` 又能跳回 `LoginPage`，互相 import 直接崩。用 `TYPE_CHECKING` + 字符串注解，或者在方法内部 import。

9. **PO 里直接 `time.sleep`**
   基础操作层就是为了消灭这个而存在的。发现有人写 sleep，说明操作原语覆盖不全，应该补原语而不是妥协。

10. **每个页面各写各的等待**
    有的用 presence 有的用 visibility，稳定性参差不齐。等待策略必须收敛到 BasePage 统一实现。

## 面试怎么答

**Q：Page Object 解决什么问题？**
A：解决 UI 用例的维护成本问题。没有 PO 的时候，定位表达式散落在几十上百条用例里，前端改一个按钮的 class，我要改几十个文件；而且每处的等待写法各不相同，稳定性参差不齐。PO 把「页面长什么样、怎么操作」这部分知识集中到一个类里，用例层只表达业务意图。核心收益是改动收敛——前端改版只改页面类，需求变化只改用例层。

**Q：你们怎么分层？**
A：四层。最上面是用例层，只有业务场景和断言，禁止出现 driver、By、WebDriverWait；下面是业务流程层，编排跨页面的完整链路，比如「下单」要经过商品页、购物车、结算页，被三条以上用例复用的链路才抽到这层；再下面是页面对象层，一个页面一个类，定位常量做类属性，方法用业务语言命名并返回下一个页面对象支持链式；最底下是基础操作层 BasePage，封装 click、fill、text_of 这些原语，每个原语内置正确的等待条件，统一日志和异常信息。分层的判据只有一条：一次改动应该只穿透一层。如果某类改动总要动两层以上，说明分层错了。

**Q：页面对象里能写断言吗？**
A：不能，断言属于用例层。原因是页面对象要被不同用例复用，把断言写进去会导致要么断言不够用要么过度断言，失败信息也难以对应到具体的用例意图。页面对象只提供 `welcome_text()` 这样的查询方法，由用例决定断言什么。唯一的例外是「页面就绪检查」——比如 `open()` 之后确认页面确实加载出来了，那不是业务断言，是页面对象自身的完整性保证。

**Q：PO 有什么局限，你怎么补？**
A：三点。第一，PO 只管 UI 层，测试数据的构造和清理它管不了，得配套数据工厂和清理机制，否则用例照样 flaky。第二，大页面容易演化成上千行的上帝类，我的做法是组件化——表格行、筛选栏、弹窗各自抽成组件对象，页面类超过 300 行就拆。第三，PO 本身不保证等待正确，如果每个页面各写各的等待，稳定性还是参差不齐，所以必须有 BasePage 这层把等待收敛掉。补充一点，PO 做得好还有个隐性收益：驱动框架换成 Playwright 时只需要改基础操作层，用例和业务层一行不动，这是分层最实在的回报。

## 参考

- [Selenium · Page object models](https://www.selenium.dev/documentation/test_practices/encouraged/page_object_models/)
- [Martin Fowler · PageObject](https://martinfowler.com/bliki/PageObject.html)
- [Playwright · Page object models](https://playwright.dev/python/docs/pom)
- 相关笔记：[[Selenium 显式等待]]
- 相关笔记：[[元素定位稳定性策略与 data-testid]]
- 相关笔记：[[UI 测试脏数据清理与数据隔离]]
- 相关笔记：[[Selenium 与 Playwright 选型对比]]
- 相关笔记：[[05-自动化测试框架]]
- 相关笔记：[[07-Web自动化测试]]
