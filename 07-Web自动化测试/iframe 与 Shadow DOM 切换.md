---
created: 2026-07-31
tags: [Web自动化测试/元素定位]
---

# iframe 与 Shadow DOM 切换

![[assets/frame-shadow-dom.svg]]
*图示：iframe 是独立 document（Selenium 需有状态切换），Shadow DOM 是同文档内的封装子树（需逐层取 shadow_root）；两者都是普通 find_element 穿不过去的查找边界。*

> 「元素在页面上明明看得到，`find_element` 就是报 NoSuchElement」——十次里有八次是这两个边界之一。

## 概念

### iframe：文档里嵌了另一个文档

`<iframe>` 会创建一个**完全独立的浏览上下文**：独立的 `document`、独立的 `window`、独立的 JS 执行环境，甚至可以是另一个域名（支付、验证码、富文本编辑器、地图组件几乎都是 iframe）。

WebDriver 协议里，会话有一个**「当前上下文（current browsing context）」状态**。所有 `find_element` 都只在当前上下文里查找。所以：

- 主文档里 `find_element` 找 iframe 内的元素 → `NoSuchElementException`；
- 必须先 `switch_to.frame(...)` 把当前上下文切进去；
- **切进去之后，主文档的元素反过来也找不到了**，必须 `switch_to.default_content()` 切回来。

**这是有状态的操作**，也是它最容易出错的地方——忘了切回来，后续所有步骤莫名其妙全失败。

### Shadow DOM：同一文档内的封装子树

Shadow DOM 是 Web Components 标准的一部分。宿主元素（如 `<my-dialog>`）通过 `attachShadow()` 挂一棵**影子树**，这棵树里的 DOM 和 CSS 与外部隔离——外部样式进不去，外部选择器也**选不到**。

关键区别：**它和主文档在同一个 document、同一个 JS 上下文里**，所以不需要「切换上下文」，只需要「拿到 shadow root 这个入口，再从它开始查找」。

两种模式：

```javascript
this.attachShadow({ mode: "open" });    // element.shadowRoot 可访问 → 自动化可测
this.attachShadow({ mode: "closed" });  // element.shadowRoot 返回 null → 外部拿不到
```

**`closed` 模式是自动化的死路**：`shadow_root` 属性拿不到，标准手段全部失效。遇到只能推动前端改成 `open`（绝大多数场景没有用 closed 的必要）。

现实中会遇到 Shadow DOM 的地方：Chrome 内置 UI（`<input type="file">` 的按钮、视频播放器控件、`chrome://` 页面）、Salesforce Lightning、Polymer/Lit 写的组件、部分低代码平台。

## 用法

### Selenium：切换 iframe 的三种方式

```python
from selenium.webdriver.common.by import By

# 1) 按索引（最脆弱，页面多个 iframe 时顺序会变，仅调试用）
driver.switch_to.frame(0)

# 2) 按 id 或 name 属性（可读，前提是前端给了）
driver.switch_to.frame("payment-frame")

# 3) 按 WebElement（最通用，可用任意选择器先定位 iframe 元素）  ← 推荐
frame_el = driver.find_element(By.CSS_SELECTOR, "iframe[src*='/pay/']")
driver.switch_to.frame(frame_el)

# 在 iframe 内操作
driver.find_element(By.ID, "card-number").send_keys("4111111111111111")
driver.find_element(By.ID, "pay-submit").click()

# 切回主文档 —— 必须做，否则后续步骤全在 iframe 里找元素
driver.switch_to.default_content()
```

嵌套 iframe 要**逐层切入**，但**只需一次 `default_content()` 就能回到最外层**：

```python
driver.switch_to.frame("outer")
driver.switch_to.frame("inner")        # 从 outer 内部继续往里切
driver.find_element(By.ID, "target").click()
driver.switch_to.parent_frame()        # 回到 outer
driver.switch_to.default_content()     # 一步回到最外层主文档
```

### 用上下文管理器杜绝「忘记切回来」

这是工程上最值得做的一层封装：

```python
from contextlib import contextmanager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

@contextmanager
def in_frame(driver, locator, timeout: int = 10):
    """进入 iframe 执行操作，无论成功失败都切回主文档。"""
    WebDriverWait(driver, timeout).until(
        EC.frame_to_be_available_and_switch_to_it(locator)   # 等 iframe 出现并自动切入
    )
    try:
        yield
    finally:
        driver.switch_to.default_content()                    # 异常也保证切回

# 使用
with in_frame(driver, (By.CSS_SELECTOR, "iframe[src*='/pay/']")):
    driver.find_element(By.ID, "card-number").send_keys("4111111111111111")
    driver.find_element(By.ID, "pay-submit").click()
# 出了 with 就已经回到主文档
```

`EC.frame_to_be_available_and_switch_to_it` 一次解决两件事：**等 iframe 加载完 + 切入**。直接 `switch_to.frame` 而不等待，是「iframe 偶发切换失败」的主因。

### Selenium：Shadow DOM

Selenium 4.x 提供了 `shadow_root` 属性（需要 Chrome 96+）：

```python
host = driver.find_element(By.CSS_SELECTOR, "my-dialog")
shadow = host.shadow_root                       # 返回 ShadowRoot 对象
btn = shadow.find_element(By.CSS_SELECTOR, ".confirm")
btn.click()
```

**限制很硬**：`ShadowRoot` 只支持 `By.CSS_SELECTOR`（和 `By.TAG_NAME` 等少数几种），**不支持 XPath**——因为 XPath 的求值上下文是整个 document，进不了影子树。

嵌套影子树要一层层剥：

```python
root1 = driver.find_element(By.CSS_SELECTOR, "outer-widget").shadow_root
root2 = root1.find_element(By.CSS_SELECTOR, "inner-widget").shadow_root
target = root2.find_element(By.CSS_SELECTOR, "button.ok")
```

写成工具函数会舒服很多：

```python
def pierce(driver, *selectors):
    """按 selectors 逐层穿透 shadow root，最后一个选择器返回目标元素。
    pierce(driver, "outer-widget", "inner-widget", "button.ok")
    """
    node = driver.find_element(By.CSS_SELECTOR, selectors[0])
    for sel in selectors[1:]:
        node = node.shadow_root.find_element(By.CSS_SELECTOR, sel)
    return node
```

老版本 Selenium 或 `shadow_root` 不可用时，退回 JS：

```python
btn = driver.execute_script(
    "return document.querySelector('my-dialog').shadowRoot.querySelector('.confirm')"
)
btn.click()      # execute_script 返回的 DOM 节点会被自动包装成 WebElement
```

### Playwright：iframe 用 frame_locator

Playwright 没有「当前上下文」这个状态，穿透是**链式且无状态**的：

```python
frame = page.frame_locator("iframe[src*='/pay/']")
frame.get_by_label("卡号").fill("4111111111111111")
frame.get_by_role("button", name="支付").click()
# 不需要切回来，page.xxx 始终指主文档
page.get_by_text("支付成功").is_visible()

# 嵌套 iframe：继续链下去
page.frame_locator("#outer").frame_locator("#inner").get_by_role("button").click()
```

**`frame_locator` 同样是惰性的**，自带自动等待——iframe 还没加载完不会立刻报错，会等到超时。这一点比 Selenium 省心得多。

也可以拿 `Frame` 对象（适合需要在 frame 上做 `goto`、`wait_for_load_state` 的场景）：

```python
frame = page.frame(name="payment-frame")          # 按 name
frame = page.frame(url=re.compile(r"/pay/"))      # 按 URL
frame.wait_for_load_state("networkidle")
```

### Playwright：Shadow DOM 自动穿透

**Playwright 的 CSS 定位器默认穿透 open shadow root**，什么都不用做：

```python
page.locator("my-dialog .confirm").click()          # 直接穿透，无需取 shadow root
page.get_by_role("button", name="确认").click()      # 语义定位器同样穿透
```

注意：

- **XPath 不穿透**（同 Selenium，XPath 引擎只认 document）；
- `closed` 模式同样不可达；
- 穿透是「自动」的，所以选择器可能意外命中影子树里的同名元素，必要时用 `:light()` 伪类限制只在明处 DOM 查找。

## 踩坑

1. **忘记 `switch_to.default_content()`**
   iframe 操作完没切回来，后续所有 `find_element` 都在 iframe 里找，报一堆莫名其妙的 NoSuchElement。**用上面的 `in_frame` 上下文管理器根治**，别靠自觉。

2. **iframe 还没加载完就切**
   报 `NoSuchFrameException` 或切进去后立刻找不到内部元素。用 `EC.frame_to_be_available_and_switch_to_it` 等待，不要裸 `switch_to.frame`。

3. **iframe 内的元素引用在切出后失效**
   ```python
   with in_frame(driver, IFRAME):
       el = driver.find_element(By.ID, "x")
   el.click()      # ✗ 已切回主文档，这个引用抛 StaleElementReferenceException / NoSuchElement
   ```
   **所有对该元素的操作必须在 `with` 块内完成**，块外只传出纯数据（文本、值）。

4. **`switch_to.frame(0)` 按索引切**
   页面里广告、埋点、客服组件都可能是 iframe，索引随时变。用 `src` 属性片段定位 iframe 元素最稳。

5. **跨域 iframe 里执行 JS 被拦**
   `execute_script` 在切入跨域 iframe 后受同源策略限制，读父页面数据会抛安全错误。这是浏览器行为，绕不过去，只能改用 CDP 或调整测试策略。

6. **ShadowRoot 上用 XPath**
   报 `InvalidArgumentException: invalid locator`。影子树内只能用 CSS。

7. **`closed` 模式的 shadow root**
   `host.shadow_root` 抛 `NoSuchShadowRootException`。没有标准解法，推动前端改 `open`；实在不行只能对该组件放弃 UI 层测试，改为在组件单测里覆盖。

8. **`<input type="file">` 的上传按钮在 Shadow DOM 里**
   Chrome 原生文件选择按钮属于 UA shadow DOM，**根本点不到也不该点**。文件上传应该直接对 input 元素 `send_keys(路径)`，见 [[Selenium 文件上传与下载]]。

9. **Playwright CSS 意外穿透**
   写 `page.locator("button")` 时可能连影子树里的按钮一起命中，触发 strict mode violation。用 `:light(button)` 限制在明处 DOM，或者收窄作用域。

## 面试怎么答

**Q：元素在页面上看得到，代码里报 NoSuchElementException，怎么排查？**
A：我有一个固定的排查顺序。第一步确认是不是时序问题——加显式等待看是否解决，元素可能还没渲染出来。第二步确认是不是在 iframe 里——在 DevTools 里看元素的祖先链有没有 `#document`，有就要先 `switch_to.frame`。第三步确认是不是 Shadow DOM——祖先链里有 `#shadow-root` 就得逐层取 `shadow_root`。第四步确认选择器本身对不对，在控制台跑 `$$()` 看命中数。第五步看是不是元素在另一个窗口或标签页里。这五步能覆盖绝大多数情况。

**Q：Selenium 怎么处理 iframe？**
A：`switch_to.frame()` 切入，参数可以是索引、id/name 或 WebElement，推荐用 WebElement 因为能用任意选择器定位。关键是两点：一是切入前要等 iframe 可用，用 `EC.frame_to_be_available_and_switch_to_it` 一步做完等待和切入；二是操作完必须 `switch_to.default_content()` 切回，否则后续查找全在 iframe 里。我会把这个封装成上下文管理器，用 `try/finally` 保证异常时也切回来，这样调用方就不可能忘。

**Q：Playwright 处理 iframe 有什么不同？**
A：Playwright 没有「当前上下文」这个状态，用 `page.frame_locator("#pay").get_by_role(...)` 链式穿透，不需要切回来，`page` 始终指主文档。因为无状态，就不存在「忘记切回」这类 bug，嵌套 iframe 也只是继续链下去。而且 frame_locator 是惰性的、自带自动等待，iframe 还没加载完也不会立刻失败。

**Q：Shadow DOM 和 iframe 的区别？**
A：iframe 是完全独立的浏览上下文，有自己的 document 和 window，可以跨域，所以 Selenium 需要有状态地切换上下文。Shadow DOM 在同一个 document 里，只是一棵封装的子树，样式和选择器隔离但 JS 上下文是通的，所以不需要切换，只要拿到 shadow root 作为查找起点。实操上，Selenium 用 `element.shadow_root` 逐层穿透且只能用 CSS 不能用 XPath；Playwright 的 CSS 定位器默认自动穿透 open 影子树。另外要注意 `closed` 模式的影子树从外部拿不到，那种情况标准自动化手段全部失效。

## 参考

- [Selenium · Working with iframes and frames](https://www.selenium.dev/documentation/webdriver/interactions/frames/)
- [Selenium · Shadow DOM](https://www.selenium.dev/documentation/webdriver/elements/shadow_dom/)
- [Playwright · Frames](https://playwright.dev/python/docs/frames)
- [MDN · Shadow DOM](https://developer.mozilla.org/zh-CN/docs/Web/API/Web_components/Using_shadow_DOM)
- 相关笔记：[[Selenium 常见异常排查]]
- 相关笔记：[[Selenium alert 弹窗与多窗口切换]]
- 相关笔记：[[Selenium 显式等待]]
- 相关笔记：[[07-Web自动化测试]]
