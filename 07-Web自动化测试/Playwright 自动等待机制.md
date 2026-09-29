---
created: 2026-07-31
tags: [Web自动化测试/等待策略]
---

# Playwright 自动等待机制

![[assets/playwright-auto-wait.svg]]
*图示：`click()` 内部的可操作性检查链——attached → visible → stable → enabled → receives events，任一项不满足就重试整条链，超时报错会说明卡在哪一项。*

> Playwright 「不用写等待」的真相：等待没有消失，只是被内置成了每个动作的前置检查链。理解这条链，才知道它能解决什么、不能解决什么。

## 概念

### 可操作性检查（actionability checks）

Playwright 在执行任何交互动作前，会**反复检查一组条件，全部满足才真正操作**：

| 检查项 | 含义 | 解决的 flaky |
|--------|------|-------------|
| **attached** | 元素已挂载到 DOM | 「元素还没渲染出来」 |
| **visible** | 有非空 bounding box 且 `visibility != hidden` | 「元素在 DOM 里但 `display:none`」 |
| **stable** | 连续两帧动画位置相同 | 「弹窗滑入动画途中点击落空」 |
| **enabled** | 不是 disabled 状态 | 「表单校验完成前按钮是灰的」 |
| **editable** | 非 readonly（仅输入类动作） | 「回填期间输入框只读」 |
| **receives events** | 命中测试通过：该点坐标上最上层元素就是它（或其后代） | 「被遮罩/Toast/固定顶栏挡住」 |

不同动作检查的项不同：

| 动作 | attached | visible | stable | enabled | editable | receives events |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| `click` / `dblclick` / `tap` | ✓ | ✓ | ✓ | ✓ | | ✓ |
| `fill` | ✓ | ✓ | | ✓ | ✓ | |
| `check` / `uncheck` | ✓ | ✓ | ✓ | ✓ | | ✓ |
| `hover` | ✓ | ✓ | ✓ | | | ✓ |
| `select_option` | ✓ | ✓ | ✓ | ✓ | | |
| `text_content` / `get_attribute` | ✓ | | | | | |
| `scroll_into_view_if_needed` | ✓ | | ✓ | | | |

注意 `text_content()` 只要求 attached——**它不等可见**。这是「读到空字符串」的常见原因，要断言文本应该用 `expect(...).to_have_text(...)`。

### 「stable」这一项为什么珍贵

Selenium 里最难治的一类 flaky 是**动画期间点击落空**：模态框正在 slide-in，`element_to_be_clickable` 判定通过（可见且 enabled），但点击派发的那一刻元素已经移动了几十像素，点到了旁边。

Playwright 的 stable 检查通过**连续两个 animation frame 比较元素 bounding box** 来判断动画是否结束。这类问题在 Playwright 里基本消失，而在 Selenium 里只能靠「等遮罩消失 + 加个短 sleep」这种土办法。

### 「receives events」怎么实现的

在元素中心点执行 `document.elementFromPoint(x, y)`，看返回的是不是目标元素或它的后代。如果不是（说明被别的元素盖住了），就继续等。

超时后的报错非常具体：

```text
TimeoutError: locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for get_by_role("button", name="提交")
  -   locator resolved to <button class="submit">提交</button>
  - attempting click action
  -   waiting for element to be visible, enabled and stable
  -   element is visible, enabled and stable
  -   scrolling into view if needed
  -   done scrolling
  -   <div class="loading-mask">…</div> intercepts pointer events    ← 直接告诉你谁挡住了
  - retrying click action, attempt #23
```

**这段 call log 是 Playwright 排障体验的核心**——它不只说「超时了」，还说「元素找到了、可见了、稳定了，但被 `.loading-mask` 挡住了，重试了 23 次」。Selenium 的 `ElementClickInterceptedException` 也会给遮挡元素信息，但没有这么完整的时间线。

### 超时的层次

```text
全局：pytest.ini / launch 参数
  └─ page.set_default_timeout(10_000)         所有动作与定位
       └─ page.set_default_navigation_timeout(30_000)   仅导航
            └─ locator.click(timeout=5_000)    单次调用覆盖
                 └─ expect(...).to_be_visible(timeout=3_000)   单次断言覆盖
```

默认值：动作 30 秒，`expect` 断言 5 秒。**`expect` 的超时是独立配置的**，很多人调了 `set_default_timeout` 发现断言超时没变就是因为这个。

```python
from playwright.sync_api import expect
expect.set_options(timeout=10_000)     # 全局设置 expect 断言超时
```

## 用法

### 什么都不用写的日常

```python
from playwright.sync_api import Page, expect

def test_place_order(page: Page):
    page.goto("https://example.com/cart")             # 默认等到 load 事件
    page.get_by_role("button", name="结算").click()    # 自动等可见/稳定/可点/未遮挡
    page.get_by_label("收货地址").fill("上海市…")       # 自动等可编辑
    page.get_by_role("button", name="提交订单").click()
    expect(page.get_by_test_id("order-status")).to_have_text("待发货")   # 自动重试断言
```

对比 [[Selenium 显式等待]] 里同样场景要写的四次 `wait.until`——**减少的不只是代码量，更是「每次都要判断该等什么条件」的决策负担**。

### 显式等待 API（自动等待不够时）

```python
# 等元素达到指定状态
page.locator(".spinner").wait_for(state="hidden")        # attached/detached/visible/hidden
page.locator("#result").wait_for(state="visible", timeout=15_000)

# 等 URL / 导航
page.wait_for_url("**/order/*")
with page.expect_navigation():
    page.get_by_role("button", name="提交").click()

# 等特定网络响应完成（比等 DOM 更精确）
with page.expect_response(lambda r: "/api/orders" in r.url and r.status == 200) as resp:
    page.get_by_role("button", name="查询").click()
data = resp.value.json()          # 顺便拿到接口返回，可直接做数据断言

# 等请求发出
with page.expect_request("**/api/track") as req:
    page.get_by_role("button", name="埋点按钮").click()

# 等自定义 JS 条件
page.wait_for_function("() => window.__APP_READY__ === true")
page.wait_for_function("() => document.querySelectorAll('.item').length >= 10")

# 等加载状态
page.wait_for_load_state("domcontentloaded")   # 默认 load
page.wait_for_load_state("networkidle")        # 500ms 无网络活动 —— 官方不推荐，见踩坑
```

**`expect_response` 是很多人不知道的利器**：与其猜「点了查询按钮后该等哪个 DOM 元素」，不如直接等那个接口返回——它是业务动作真正完成的最准确信号，还能顺手拿到响应体做接口层断言。

### expect 断言全家桶

```python
from playwright.sync_api import expect
import re

expect(locator).to_be_visible()
expect(locator).to_be_hidden()
expect(locator).to_be_enabled()
expect(locator).to_be_checked()
expect(locator).to_be_empty()
expect(locator).to_have_text("已支付")                 # 精确（会归一化空白）
expect(locator).to_contain_text("已支付")              # 包含
expect(locator).to_have_value("13800000000")
expect(locator).to_have_attribute("href", re.compile(r"/order/\d+"))
expect(locator).to_have_class(re.compile(r"active"))
expect(locator).to_have_count(3)
expect(page).to_have_url(re.compile(r"/dashboard"))
expect(page).to_have_title("订单中心")
expect(locator).not_to_be_visible()                   # 取反用 not_ 前缀
```

**`expect` 与 `assert` 的本质区别**：`expect` 在超时窗口内反复求值（web-first assertion），`assert` 是一次性快照。异步渲染场景下 `assert page.locator("#x").text_content() == "y"` 必然偶发失败。

### 关掉自动等待：force 与 dispatch_event

```python
locator.click(force=True)              # 跳过除 attached 外的所有可操作性检查
locator.dispatch_event("click")        # 直接派发 DOM 事件，完全不走真实点击
locator.click(no_wait_after=True)      # 不等待点击引发的导航
```

**`force=True` 是一个危险的止痛药**。它常被用来「绕过遮罩」，但遮罩存在通常意味着页面真的还在加载——真实用户此刻也点不到。用 `force` 通过的用例，掩盖的是一个真实的可用性问题。

合理使用 `force` 的场景很窄：比如元素被一个**纯装饰性、不拦截真实用户交互**的伪元素覆盖（CSS 实现问题），或者测试目标就是「非常规交互」。用之前先问：真实用户能点到吗？

## 踩坑

1. **`wait_for_load_state("networkidle")` 滥用**
   官方明确不推荐。带轮询、长连接、心跳、埋点上报的现代页面**永远不会 networkidle**，等到超时为止。要等具体信号：`expect_response` 等接口、`expect(...)` 等 DOM 状态。

2. **`text_content()` 读到空字符串**
   它只等 attached 不等 visible，元素刚挂载还没填内容就读了。用 `expect(loc).to_have_text(...)` 或先 `loc.wait_for(state="visible")`。

3. **用 `assert` 而不是 `expect`**
   `assert page.get_by_test_id("total").is_visible()` 是瞬时判断，没有重试。所有 UI 断言都该用 `expect`。团队里可以加一条 lint 规则或 review checklist。

4. **超时单位搞错**
   全部是**毫秒**。`set_default_timeout(30)` = 30 毫秒，会导致所有操作立即超时，报错还很迷惑。

5. **`expect` 的超时和动作超时是两套配置**
   调了 `page.set_default_timeout` 断言还是 5 秒超时，要用 `expect.set_options(timeout=...)`。

6. **用 `force=True` 掩盖遮罩问题**
   前面讲过。正确做法是 `expect(page.locator(".loading-mask")).to_be_hidden()` 等它消失——如果它一直不消失，那就是发现了一个 bug，这才是自动化的价值。

7. **`page.wait_for_timeout()` 当成 sleep 用**
   Playwright 提供了这个 API，但文档明确写「生产测试中不要用」。它和 `time.sleep` 一样是硬等待，只是不阻塞事件循环。

8. **自动等待救不了数据时序**
   点击「提交」后立刻断言列表里有新订单，元素可能已经渲染但后端异步落库还没完成。这类要靠 `expect_response` 等接口返回，或者轮询接口确认数据就绪，或者放宽断言超时。**框架能力止步于前端，后端异步要靠测试设计解决。**

9. **`no_wait_after=True` 用错场景**
   它跳过的是「等待点击引发的导航完成」，不是跳过可操作性检查。只在「点击会打开新页/下载，不希望阻塞」时用。

10. **循环里逐个 `expect` 导致耗时叠加**
    对 20 个元素各 `expect(...).to_be_visible()`，最坏情况 20×5 秒。批量校验用 `to_have_count` 或一次性取文本列表在 Python 侧比较。

## 面试怎么答

**Q：Playwright 为什么不用写等待？**
A：不是不用等，是等待被内置成了每个动作的前置检查链。以 `click` 为例，Playwright 会反复检查五项：元素已挂载、可见、位置稳定（连续两帧 bounding box 不变）、enabled、以及命中测试通过（该坐标最上层元素就是它，没被遮挡），全部满足才真正派发点击，任一项不满足就重试整条链直到超时。所以它不是取消了等待，而是把「该等什么条件」这个每次都要人做的判断，变成了框架固定执行的标准流程——这才是稳定性提升的真正来源，因为它不依赖写用例的人的水平。

**Q：这套机制解决了哪些 Selenium 里的经典问题？**
A：主要三类。第一是动画期间点击落空——Selenium 的 `element_to_be_clickable` 只看可见和 enabled，弹窗滑入过程中判定就通过了，点击落到旁边；Playwright 的 stable 检查会等动画停下来。第二是被遮罩挡住——Selenium 要么抛 ElementClickInterceptedException 要么点到遮罩上，Playwright 会一直重试并在超时报错里明确告诉你是哪个元素拦截了 pointer events。第三是 StaleElementReference——locator 是惰性的，每次动作重新解析 DOM，这个异常在 Playwright 里根本不存在。

**Q：自动等待解决不了什么？**
A：三类。第一，后端异步导致的数据时序——元素渲染好了但数据是旧的，或者提交后异步落库还没完成，这属于测试设计问题，要用 `expect_response` 等接口返回或者轮询确认数据就绪。第二，用例之间的数据串味，换任何框架都不解决。第三，被 `force=True` 或 `dispatch_event` 主动绕过的情况——很多人用 `force` 去「解决」遮罩问题，那等于手动关掉了框架最有价值的保护，而且掩盖了一个真实用户也会遇到的可用性问题。

**Q：`expect` 和 `assert` 有什么区别？**
A：`expect` 是 web-first assertion，会在超时窗口内反复求值直到条件成立，默认 5 秒；`assert` 配 `is_visible()` 或 `text_content()` 是一次性快照。异步渲染的页面上用 `assert` 必然偶发失败——不是断言错了，是断言得太早了。所以 UI 层断言我一律用 `expect`，只有对已经取出来的纯数据做比较时才用 `assert`。

## 参考

- [Playwright · Auto-waiting（actionability）](https://playwright.dev/python/docs/actionability)
- [Playwright · Assertions](https://playwright.dev/python/docs/test-assertions)
- [Playwright · Navigations 与 waiting](https://playwright.dev/python/docs/navigations)
- 相关笔记：[[Selenium 显式等待]]
- 相关笔记：[[Selenium 隐式等待与显式等待混用冲突]]
- 相关笔记：[[Playwright 语义定位器]]
- 相关笔记：[[Selenium 与 Playwright 选型对比]]
- 相关笔记：[[07-Web自动化测试]]
