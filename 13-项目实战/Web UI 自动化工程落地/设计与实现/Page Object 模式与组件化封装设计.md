---
created: 2026-09-28
tags: [项目实战/Web自动化测试]
---

# Page Object 模式与组件化封装设计

> 摆脱传统「一个 HTML 页面对应一个 Class」的面条式封装，采用「页面对象（Page Object）+ 复合组件（Component-Based Object）」分层设计，大幅提升 UI 自动化的维护性与定位器重用度。

## 概念

在 Web UI 自动化中，经典的 Page Object（PO）模式核心原则是：
1. **公开服务而非细节**：页面类暴露给用例的是业务操作方法（如 `login()`、`search_goods()`），而不是具体的控件细节（如 `input_username`、`click_btn`）。
2. **方法返回新的页面对象**：跳转产生新页面或新状态时返回对应的页面实例。
3. **断言不放在页面对象内部**：页面对象负责提供数据和状态查询（`get_title()`、`is_login_success()`），具体的 `assert` 逻辑保留在测试用例层。

然而在现代前端（Vue / React / Angular）开发盛行的背景下，页面普遍由大量通用组件拼接而成（如通用分页表格 `Table`、确认模态框 `Modal`、树形级联选择器 `Cascader`）。如果仍然采用简单的单层 Page 类，会导致重复编写表格数据解析、弹窗确认等代码。

因此，进阶架构设计为**组件化（Component-Based）PO 模式**：
- **BasePage**：底层通用基础设施（Page 原语、全局等待、截图/高亮、导航代理）。
- **BaseComponent**：挂载在具体页面或父容器下的独立业务组件，拥有相对定位器上下文。
- **BusinessPage**：具体的业务页面，组合多个业务组件与页面专属定位器。
- **Test Case**：面向业务流程编排调用。

## 用法

### 1. 顶层 BasePage 设计

封装 Playwright 原生 `Page` 对象，避免把原始底层句柄直接裸露给上层，同时增强日志记录与等待保护。

```python
# core/base_page.py
from typing import Optional
from playwright.sync_api import Page, Locator, expect

class BasePage:
    """所有页面对象的基础基类。"""

    def __init__(self, page: Page):
        self.page = page

    def navigate_to(self, url: str):
        """统一导航跳转，默认等待网络空闲或 DOMContentLoaded。"""
        self.page.goto(url, wait_until="domcontentloaded")

    def find(self, selector: str) -> Locator:
        """封装标准定位器，可链式调用。"""
        return self.page.locator(selector)

    def find_by_role(self, role: str, **kwargs) -> Locator:
        """优先使用语义化 Role 定位（无障碍与高稳定性）。"""
        return self.page.get_by_role(role, **kwargs)

    def wait_for_url_contains(self, partial_url: str, timeout: int = 10000):
        """等待 URL 包含特定路径，常用于重定向断言。"""
        self.page.wait_for_url(f"**/*{partial_url}*", timeout=timeout)
```

### 2. 通用组件封装（BaseComponent & TableComponent）

以中后台最常见的动态表格组件为例，利用 Playwright 的 `locator` 链式调用和嵌套特性，实现针对表格特定行、列的动态检索：

```python
# core/components/table.py
from typing import List, Optional
from playwright.sync_api import Locator

class TableComponent:
    """Ant Design / Element Plus 风格的数据表格组件。"""

    def __init__(self, root_locator: Locator):
        # 组件定位器全部限定在 root_locator 范围内，避免污染全局
        self.root = root_locator
        self.rows = self.root.locator("tbody tr")
        self.headers = self.root.locator("thead th")

    def get_row_by_text(self, text: str) -> Locator:
        """通过行内包含的特定文本精准获取单行 Locator。"""
        return self.rows.filter(has_text=text)

    def get_cell_text(self, row_idx: int, col_idx: int) -> str:
        """获取指定行列的文本。"""
        cell = self.rows.nth(row_idx).locator("td").nth(col_idx)
        return cell.inner_text().strip()

    def click_action_in_row(self, row_keyword: str, action_name: str):
        """在匹配行内点击具体操作按钮（如：编辑、删除、发货）。"""
        target_row = self.get_row_by_text(row_keyword)
        # 链式定位行内特定按钮
        target_row.get_by_role("button", name=action_name).click()
```

### 3. 业务 Page 实现（组合组件与专属方法）

业务页面（例如登录页、订单管理页）继承 `BasePage`，并聚合通用组件：

```python
# pages/order_page.py
from playwright.sync_api import Page
from core.base_page import BasePage
from core.components.table import TableComponent

class OrderPage(BasePage):
    """订单管理业务页面。"""

    def __init__(self, page: Page):
        super().__init__(page)
        # 组合表格组件
        self.table = TableComponent(self.page.locator(".ant-table-wrapper"))
        self.search_input = self.page.get_by_placeholder("请输入订单编号")
        self.search_btn = self.page.get_by_role("button", name="查询")
        self.order_status_filter = self.page.locator(".status-dropdown")

    def search_order(self, order_sn: str):
        """业务服务：查询订单。"""
        self.search_input.fill(order_sn)
        self.search_btn.click()
        # 等待表格加载状态消失
        self.page.locator(".ant-spin-spinning").wait_for(state="hidden", timeout=5000)

    def ship_order(self, order_sn: str):
        """业务服务：发货。"""
        self.table.click_action_in_row(order_sn, "发货")
        # 确认发货弹窗
        self.page.locator(".confirm-modal").get_by_role("button", name="确认").click()
```

## 踩坑

1. **定位器过早评估（Eager Evaluation）陷阱**：
   - 在 Selenium 时代，`driver.find_element()` 是立即发起网络请求查询 DOM 的，若元素未渲染立刻抛错。
   - Playwright 的 `page.locator()` 是**惰性求值（Lazy Evaluation）**，只有在执行 `click()` / `fill()` / `inner_text()` 等 Action 操作时才会真正去查询 DOM 并执行自动等待。
   - *踩坑实践*：切勿在 `__init__` 中调用任何会立即执行查找的原生 API（如 `element_handle = page.query_selector()`），统一在类属性中使用 `page.locator()`。
2. **绝对 CSS 路径脆弱性**：
   - 严禁使用 `/html/body/div[2]/div/div[3]/table/tbody/tr[1]/td[2]` 这类极易受版本变更破坏的定位器。
   - 推荐优先级：`get_by_role` > `get_by_test_id`（让前端统一埋 `data-testid`）> 具备语义的 CSS Class（如 `.order-table`）。
3. **断言侵入 Page Object**：
   - 曾有开发测试在 `OrderPage.ship_order()` 内部直接写 `assert "发货成功" in message`。一旦产品将提示文案修改为「订单已推送仓储」，需要修改底层 Page 文件。正确做法是由 Page 返回提示文本或者 Locator，由 Test Case 负责执行 `expect(page.locator(".toast")).to_have_text(...)`。

## 面试怎么答

**Q：在现代前端框架下，你的 Page Object 模式做了哪些演进？**
> 传统 PO 模式往往按单一 HTML 页面映射一个 Page 类，这在现代组件化前端（Vue/React）中容易出现大量冗余代码（例如每个页面都有弹窗、表格、分页）。我们的演进思路是**组件化驱动的复合 PO 模式**：
> 1. 将高频复用的 UI 片段（如 Ant Design 的 Table、Modal、Drawer）下沉为独立的 `ComponentObject`，组件持有父容器的 `Locator` 上下文，具备相对定位和专属操作逻辑。
> 2. 页面对象 `BusinessPage` 负责组合这些组件与自身业务控件，对外仅暴露完整的业务服务方法（如 `query_order()`），屏蔽 DOM 细节。
> 3. 用例层专注于业务流程编排与断言，断言不写在 Page 内部。这样当前端 UI 库升级或组件结构调整时，只需维护对应的组件类，上层数十条用例完全无需改动。

## 参考

- Playwright 官方 Locators 指南：`https://playwright.dev/python/docs/locators`
- 相关笔记：[[07-Web自动化测试]]、[[Page Object 模式与分层设计]]、[[测试框架分层架构设计]]
- 所属项目：[[Web UI 自动化工程落地/Web UI 自动化工程落地]]
