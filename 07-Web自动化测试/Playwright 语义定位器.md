---
created: 2026-07-31
tags: [Web自动化测试/Playwright]
---

# Playwright 语义定位器

> `get_by_role` / `get_by_label` / `get_by_text` 为什么比 CSS 更抗改版：它们定位的是「用户看到的东西」，而不是「DOM 长什么样」。

## 概念

### Locator 不是元素，是「查找方式」

这是理解 Playwright 的第一道坎。Selenium 的 `find_element` **立刻执行查找并返回一个 WebElement 引用**，页面一刷新这个引用就失效（`StaleElementReferenceException`）。

Playwright 的 `page.get_by_role(...)` **什么都不做**，只是记下「怎么找」。真正的查找发生在每次动作或断言时：

```python
btn = page.get_by_role("button", name="提交")   # 此刻页面里根本还没有这个按钮也没关系
page.goto("https://example.com/form")            # 换页
btn.click()                                       # 此刻才真正查找 + 自动等待 + 点击
```

三个直接后果：

1. **没有 StaleElement 问题**。每次用都重新解析，DOM 重建不影响 locator。
2. **可以提前定义、复用**，Page Object 里把 locator 定义成类属性是安全的。
3. **locator 自带自动等待**，见 [[Playwright 自动等待机制]]。

### 语义定位器：按「用户怎么感知」来找

Playwright 官方推荐的定位优先级：

```text
get_by_role  >  get_by_label / get_by_placeholder  >  get_by_text  >  get_by_test_id  >  CSS / XPath
```

理由是**抗改版能力与「意图表达力」成正比**。`page.get_by_role("button", name="提交")` 表达的是「那个叫『提交』的按钮」——只要产品需求没变，这个描述就不变，哪怕前端把 `<button>` 换成 `<div role="button">`、把 class 全改了，定位依然有效。而 `.form > div:nth-child(3) > button.btn-primary` 表达的是「DOM 第三层那个元素」，改版必断。

### ARIA role 是什么

`get_by_role` 依据的是 **ARIA（Accessible Rich Internet Applications）语义树**，也就是屏幕阅读器看到的那棵树。浏览器会给原生标签隐式赋予 role：

| HTML | 隐式 role | accessible name 来源 |
|------|----------|---------------------|
| `<button>提交</button>` | `button` | 内部文本 |
| `<a href="...">首页</a>` | `link` | 内部文本 |
| `<input type="text">` | `textbox` | 关联的 `<label>` / `aria-label` / `placeholder` |
| `<input type="checkbox">` | `checkbox` | 关联 label |
| `<h1>~<h6>` | `heading`（带 level） | 内部文本 |
| `<table>` | `table` | `<caption>` |
| `<ul>/<ol>` | `list` | — |
| `<select>` | `combobox` | 关联 label |
| `<img alt="头像">` | `img` | `alt` |
| `<div role="dialog">` | `dialog`（显式声明） | `aria-label` / `aria-labelledby` |

**副作用很有价值**：如果一个元素用 `get_by_role` 找不到，通常说明它的可访问性有问题（比如用 `<div>` 假装按钮却没加 `role` 和 `aria-label`）。UI 自动化因此顺带成了 a11y 的守门人，这个论点在面试里很加分。

## 用法

### 八个 get_by_* 方法

```python
# 1) role —— 首选
page.get_by_role("button", name="登录").click()
page.get_by_role("link", name="订单中心").click()
page.get_by_role("heading", name="收货信息", level=2)
page.get_by_role("checkbox", name="记住我").check()
page.get_by_role("textbox", name="用户名").fill("qa01")
page.get_by_role("button", name="提交", exact=True)      # 精确匹配，默认是子串+大小写不敏感
page.get_by_role("row", name="SO20260731001")            # 表格行

# 2) label —— 表单元素首选
page.get_by_label("用户名").fill("qa01")
page.get_by_label("同意条款").check()

# 3) placeholder —— 没有 label 时的退路
page.get_by_placeholder("请输入手机号").fill("13800000000")

# 4) text —— 非交互元素（提示、标题、正文）
page.get_by_text("下单成功").is_visible()
page.get_by_text("总计", exact=True)
import re
page.get_by_text(re.compile(r"共\s*\d+\s*件商品"))        # 支持正则

# 5) alt_text —— 图片
page.get_by_alt_text("公司 logo").click()

# 6) title —— title 属性（hover 提示）
page.get_by_title("关闭").click()

# 7) test_id —— 语义都不可用时的稳定兜底
page.get_by_test_id("submit-order")

# 8) locator —— CSS / XPath 逃生舱
page.locator("div.legacy-widget >> css=input")
```

`get_by_text` 的匹配规则要记牢：**默认是「子串 + 大小写不敏感 + 空白归一化」**，`exact=True` 时变成「完全相等 + 大小写敏感」但仍会归一化空白。

### 自定义 test_id 属性名

默认认 `data-testid`。团队用别的属性名可以改：

```python
# conftest.py
playwright.selectors.set_test_id_attribute("data-qa")
# 之后 page.get_by_test_id("submit") 会匹配 [data-qa='submit']
```

### 链式与过滤：解决「找到多个」

真实页面里 `get_by_role("button", name="删除")` 常常命中十几个。Playwright 的解法是**收窄作用域**而不是加索引：

```python
# ✗ 脆弱：依赖顺序
page.get_by_role("button", name="删除").nth(3).click()

# ✓ 先锁定行，再在行内找按钮
page.get_by_role("row", name="SO20260731001").get_by_role("button", name="删除").click()

# ✓ filter：按包含的文本 / 子元素筛选
page.get_by_role("listitem").filter(has_text="iPhone 15").get_by_role("button", name="加购").click()
page.get_by_role("listitem").filter(has=page.get_by_role("img", name="缺货")).count()
page.get_by_role("listitem").filter(has_not_text="已下架")

# ✓ 组合定位：同时满足两个 locator
page.get_by_role("button").and_(page.get_by_title("订阅"))
page.get_by_role("button", name="确认").or_(page.get_by_role("button", name="OK"))
```

`filter(has=...)` 里传的 locator 是**相对于外层元素**解析的，不是相对页面。

### 严格模式（strict mode）

Playwright **默认开启严格模式**：如果 locator 匹配到多个元素，动作会直接报错，而不是像 Selenium 那样默默取第一个。

```text
Error: strict mode violation: get_by_role("button", name="删除") resolved to 12 elements:
    1) <button class="btn-del">删除</button> aka get_by_role("row", name="SO001").get_by_role("button")
    2) ...
```

**这是特性不是 bug**：Selenium 里「定位到多个默认取第一个」会让用例静默地点错东西，排查时一头雾水。Playwright 强制你把定位写精确。报错信息还会贴心地给出建议写法。

需要批量操作时用显式复数 API：

```python
count = page.get_by_role("listitem").count()
for item in page.get_by_role("listitem").all():
    print(item.text_content())
page.get_by_role("listitem").first / .last / .nth(2)     # 显式取单个，不违反严格模式
```

### 配合 expect 断言

```python
from playwright.sync_api import expect

expect(page.get_by_test_id("total")).to_have_text("￥199.00")
expect(page.get_by_role("button", name="提交")).to_be_enabled()
expect(page.get_by_role("listitem")).to_have_count(3)
expect(page.get_by_text("下单成功")).to_be_visible(timeout=10_000)
expect(page).to_have_url(re.compile(r"/order/\d+"))
```

`expect()` 是**带自动重试的断言**：它会在超时时间内反复求值，直到条件成立或超时。这和 `assert page.get_by_text("下单成功").is_visible()` 有本质区别——后者是瞬时快照，异步渲染慢一拍就假失败。**UI 断言一律用 `expect`，不用裸 `assert`。**

### Codegen：自动生成语义定位器

```bash
playwright codegen https://example.com
```

录制时它会**优先生成 `get_by_role` 这类语义定位器**，是学习定位写法的最好工具。但录出来的代码不能直接当用例用——没有分层、没有断言、数据写死，只能当定位器的草稿。

## 踩坑

1. **strict mode violation 刷屏**
   不要用 `.first` 糊过去，那等于退回 Selenium 的静默取第一个。正确解法是收窄作用域（先定位卡片/行，再在内部找）或用 `filter()`。只有「就是要第一个」的语义（比如列表首项）才用 `.first`。

2. **`get_by_role` 找不到明明看得见的按钮**
   通常是前端用 `<div class="btn" onclick="...">` 假装按钮，没有 role 也没有 accessible name。可以在 DevTools 的 Accessibility 面板确认它的 role 与 name。短期用 `get_by_text` 或 `get_by_test_id` 兜底，长期推动前端补 `role="button"` 和 `aria-label`。

3. **`name` 参数默认是子串匹配**
   `get_by_role("button", name="提交")` 也会命中「提交并支付」。要精确匹配加 `exact=True`。

4. **中文文本里的空白**
   `<button>提 交</button>`（中间有全角/半角空格）用 `name="提交"` 匹配不到。Playwright 会归一化连续空白但不会删除空白。用正则 `re.compile(r"提\s*交")` 或改用 test_id。

5. **locator 是惰性的，别指望它「记住」元素**
   ```python
   items = page.get_by_role("listitem").all()   # all() 是即时快照，返回 locator 列表
   page.reload()
   items[0].click()                              # 页面已重建，这个 locator 仍会重新查找 —— 但语义可能已经不是原来那一项
   ```
   `all()` 在调用时固化了数量与索引。列表会变的场景下，循环里应该在每轮重新求值。

6. **`filter(has=...)` 里用了绝对定位器**
   `filter(has=page.locator("//div[@class='x']"))` 里的 `//` 会从文档根开始，导致过滤条件恒真。要写 `.//` 或直接用 CSS。

7. **把 `get_by_text` 用在交互元素上**
   `page.get_by_text("提交").click()` 可能命中的是按钮里的 `<span>` 而不是按钮本身，点击落在子元素上有时不触发事件。交互元素一律用 `get_by_role`。

8. **`expect` 与 `assert` 混用**
   `assert page.get_by_test_id("total").text_content() == "￥199.00"` 是瞬时读取，异步刷新的数值必然偶发失败。改用 `expect(...).to_have_text(...)`。

9. **改了 test id 属性名却没在所有入口设置**
   `set_test_id_attribute` 是进程级配置，多进程并行（`pytest -n`）时要在 conftest 的 session fixture 里设，确保每个 worker 都执行到。

## 面试怎么答

**Q：Playwright 的 locator 和 Selenium 的 WebElement 有什么区别？**
A：Selenium 的 `find_element` 立即执行查找、返回一个指向具体 DOM 节点的引用，页面重新渲染后引用失效，就是 StaleElementReferenceException 的来源。Playwright 的 locator 是惰性的，它只描述「怎么找」，每次动作或断言时才重新解析 DOM。所以 Playwright 天然没有 stale 问题，locator 也可以在 Page Object 里作为类属性提前定义和复用。

**Q：为什么推荐 `get_by_role` 而不是 CSS？**
A：因为它定位的是「用户感知到的东西」而不是「DOM 长什么样」。`get_by_role("button", name="提交")` 描述的是需求层面的对象，前端把标签、class、层级结构全改了，只要按钮文案没变，定位就有效；CSS 选择器绑定的是实现细节，改版就断。附加价值是它依赖 ARIA 语义树——如果用 role 定位不到，往往说明这个元素的可访问性有缺陷，UI 自动化顺带成了 a11y 的守门人。

**Q：Playwright 的严格模式是什么？**
A：locator 匹配到多个元素时，动作会直接抛 strict mode violation 而不是取第一个。这是刻意设计：Selenium 里静默取第一个会让用例点错元素还查不出原因，是很隐蔽的 bug 来源。遇到严格模式报错，正确解法是收窄作用域——先定位到行或卡片容器，再在容器内找——或者用 `filter(has_text=...)` 过滤，而不是用 `.first` 糊过去。

**Q：定位器优先级你怎么排？**
A：role > label/placeholder > text > test_id > CSS > XPath。前面几档是语义层，跟着需求走；`data-testid` 是和前端约定的稳定契约，语义层覆盖不了时用；CSS 和 XPath 是逃生舱，只在遗留组件、第三方 iframe 这类改不动的地方用。团队里我会把这个优先级写进代码规范，review 时看到裸 XPath 就要求说明理由。

## 参考

- [Playwright · Locators](https://playwright.dev/python/docs/locators)
- [Playwright · Other locators](https://playwright.dev/python/docs/other-locators)
- [MDN · ARIA roles](https://developer.mozilla.org/zh-CN/docs/Web/Accessibility/ARIA/Roles)
- 相关笔记：[[Playwright 自动等待机制]]
- 相关笔记：[[元素定位稳定性策略与 data-testid]]
- 相关笔记：[[CSS 选择器定位]]
- 相关笔记：[[07-Web自动化测试]]
