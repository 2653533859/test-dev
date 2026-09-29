---
created: 2026-07-31
tags: [Web自动化测试/等待策略]
---

# Selenium 显式等待

![[assets/explicit-wait.svg]]
*图示：WebDriverWait 的轮询循环——每隔 poll 秒调一次条件函数，为真立即返回、超时抛 TimeoutException；右侧对比 sleep 的两种浪费。*

> UI 自动化最核心的一个 API。讲透它的轮询实现、`expected_conditions` 怎么选、以及为什么 `sleep` 必须禁用。

## 概念

### 问题根源：测试脚本和页面渲染是两个异步时钟

现代前端页面上，一个元素从「代码发起请求」到「用户能点击」要经历：

```text
点击按钮 → 发 XHR → 后端处理 → 返回 JSON → 前端 setState
        → 虚拟 DOM diff → 真实 DOM 插入 → 浏览器布局(layout)
        → 绘制(paint) → CSS 过渡动画结束 → 元素真正可交互
```

这个链路耗时从几十毫秒到几秒不等，**取决于网络、后端负载、机器性能**——CI 机器比本机慢是常态。而测试脚本是同步顺序执行的，它不知道页面进行到哪一步了。

三种应对方式：

| 方式 | 机制 | 问题 |
|------|------|------|
| `time.sleep(n)` | 无条件挂起 n 秒 | 快了浪费时间，慢了照样失败 |
| 隐式等待 | 全局设定，找不到元素时轮询重试 | 只管「元素在不在 DOM」，管不了可见/可点，还会与显式等待相乘 |
| **显式等待** | 针对某个条件轮询，成立即返回 | 需要每处判断等什么条件——但这正是它的价值 |

### WebDriverWait 的实现（源码级）

`WebDriverWait.until()` 的逻辑非常简单，理解它就理解了一切：

```python
# selenium/webdriver/support/wait.py 的核心逻辑（简化）
def until(self, method, message=""):
    end_time = time.monotonic() + self._timeout
    while True:
        try:
            value = method(self._driver)      # 调条件函数
            if value:                          # 真值即成功
                return value                   # 注意：返回的是条件函数的返回值
        except self._ignored_exceptions:       # 默认忽略 NoSuchElementException
            pass                               # 吞掉，继续轮询
        time.sleep(self._poll)                 # 默认 0.5 秒
        if time.monotonic() > end_time:
            break
    raise TimeoutException(message, screen, stacktrace)
```

四个要点：

1. **返回值是条件函数的返回值**。`EC.visibility_of_element_located` 返回 WebElement，所以可以 `wait.until(...).click()` 链式写。
2. **`ignored_exceptions` 默认包含 `NoSuchElementException`**，所以条件函数内部找不到元素不会中断轮询。想连 `StaleElementReferenceException` 一起忽略要显式传。
3. **先判断再 sleep，最后检查超时**——所以**至少会执行一次**条件检查，`timeout=0` 也会检查一次。
4. **实际耗时可能略超 timeout**：如果最后一次检查恰好耗时很长（比如一次慢查询），总时间会超出。`timeout` 是「不早于」而非「精确」。

### 为什么 `sleep` 必须禁用

图右侧已经画了：元素 1 秒就绪时白等 9 秒（100 条用例 × 10 处等待 = 浪费十几分钟），元素 12 秒才到时直接失败。

**更隐蔽的第三个问题**：`sleep` 失败时抛的是 `NoSuchElementException`，看报错完全不知道是「定位写错了」还是「等得不够久」。而 `TimeoutException` 配上 `message` 参数能直接告诉你「等待订单列表加载超时」。**可诊断性差异比时间浪费更致命。**

唯一可接受 `sleep` 的场景：等待一个**没有任何 DOM 可观测信号**的过程（比如某些 canvas 动画、防抖节流窗口），且必须写注释说明为什么。

## 用法

### 基本用法

```python
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

wait = WebDriverWait(driver, timeout=10, poll_frequency=0.5)

# 等到可点击后点击（返回 WebElement，可链式）
wait.until(
    EC.element_to_be_clickable((By.CSS_SELECTOR, "[data-testid='submit']")),
    message="提交按钮 10 秒内未变为可点击"      # 一定要写，失败时省一半排查时间
).click()

# 等到消失（比如 loading 遮罩）
wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, ".loading-mask")))

# 等文本出现
wait.until(EC.text_to_be_present_in_element((By.ID, "status"), "已支付"))
```

注意 locator 要传**元组**：`(By.ID, "x")`，多写一层括号是新手最常见的语法错误。

### expected_conditions 选型表

**选错条件是 flaky 的头号来源**，这张表要背下来：

| 条件 | 判定 | 用在什么场景 |
|------|------|------------|
| `presence_of_element_located` | 元素在 DOM 中 | 只需读属性、判断是否渲染；**不保证可见** |
| `visibility_of_element_located` | 在 DOM + 可见（有尺寸、非 `display:none`） | 读文本、断言展示 |
| `invisibility_of_element_located` | 不可见或不在 DOM | 等 loading 消失 |
| `element_to_be_clickable` | 可见 + `enabled` | **点击前的标准条件** |
| `presence_of_all_elements_located` | 至少 1 个匹配 | 取列表；注意「至少 1 个」≠「全部加载完」 |
| `text_to_be_present_in_element` | 元素文本包含指定串 | 状态流转断言 |
| `text_to_be_present_in_element_value` | input 的 value 包含 | 表单回填校验 |
| `element_located_to_be_selected` | 复选框/单选被选中 | 勾选后校验 |
| `title_is` / `title_contains` | 页面标题 | 跳转校验 |
| `url_contains` / `url_matches` | URL | 路由跳转校验 |
| `alert_is_present` | 原生弹窗出现 | 见 [[Selenium alert 弹窗与多窗口切换]] |
| `frame_to_be_available_and_switch_to_it` | iframe 可用并切入 | 见 [[iframe 与 Shadow DOM 切换]] |
| `staleness_of` | 指定元素已从 DOM 移除 | **等待页面刷新**的经典技巧 |
| `number_of_windows_to_be` | 窗口数量 | 新标签页 |
| `new_window_is_opened` | 窗口集合变化 | 新标签页 |

**`staleness_of` 的经典用法**——等待整页刷新完成：

```python
old = driver.find_element(By.TAG_NAME, "html")
driver.find_element(By.ID, "refresh").click()
wait.until(EC.staleness_of(old))            # 老的 html 元素失效 = 新页面已开始加载
wait.until(EC.visibility_of_element_located((By.ID, "content")))
```

这比「等某个元素出现」可靠，因为刷新前后可能是同一个元素，等不出变化。

### 自定义条件：lambda

`until` 接受任意「接收 driver、返回真值」的可调用对象。复杂条件直接写 lambda：

```python
# 等列表行数达到预期
wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "[data-testid='order-item']")) >= 10)

# 等某个数值稳定下来（结束动画/滚动）
wait.until(lambda d: d.find_element(By.ID, "total").text.strip() != "")

# 等 JS 变量就绪（前端框架挂载完成）
wait.until(lambda d: d.execute_script("return window.__APP_READY__ === true"))

# 等 jQuery ajax 全部结束（老项目常用）
wait.until(lambda d: d.execute_script("return jQuery.active == 0"))

# 等文档加载完成
wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
```

### 自定义条件类：可复用、报错友好

```python
class TextStabilized:
    """等某元素文本连续两次轮询保持一致（应对数字滚动动画）。"""

    def __init__(self, locator):
        self.locator = locator
        self.previous = object()      # 哨兵值，保证首次不相等

    def __call__(self, driver):
        current = driver.find_element(*self.locator).text
        if current and current == self.previous:
            return current            # 稳定了，返回文本
        self.previous = current
        return False

total = wait.until(TextStabilized((By.ID, "total")), message="总价一直在变，未稳定")
```

**注意**：条件对象带状态时不能跨 `until` 复用，每次要新建实例。

### 忽略 StaleElementReferenceException

列表频繁重渲染时，条件函数内部拿到的元素可能在下一步就失效。把这个异常也加入忽略列表：

```python
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
)

wait = WebDriverWait(
    driver,
    timeout=10,
    poll_frequency=0.3,
    ignored_exceptions=(NoSuchElementException, StaleElementReferenceException),
)
```

### `until_not`：等待条件不成立

```python
wait.until_not(EC.presence_of_element_located((By.CSS_SELECTOR, ".spinner")))
```

语义上等价于 `until(invisibility_of_...)`，但 `until_not` 更通用（可以对任意条件取反）。

### 封装：把等待收进操作原语

**用例层不该出现 `WebDriverWait`**。正确做法是把它藏进基础操作层：

```python
class BasePage:
    def __init__(self, driver, timeout: int = 10):
        self.driver = driver
        self.wait = WebDriverWait(driver, timeout)

    def click(self, locator, desc: str = ""):
        self.wait.until(
            EC.element_to_be_clickable(locator),
            message=f"[{desc or locator}] 未在超时内变为可点击",
        ).click()

    def fill(self, locator, text: str, desc: str = ""):
        el = self.wait.until(
            EC.visibility_of_element_located(locator),
            message=f"[{desc or locator}] 未在超时内可见",
        )
        el.clear()
        el.send_keys(text)

    def text_of(self, locator, desc: str = "") -> str:
        return self.wait.until(
            EC.visibility_of_element_located(locator),
            message=f"[{desc or locator}] 未在超时内可见",
        ).text
```

这样**每个操作都自带正确的等待条件**，用例层写 `self.click(SUBMIT_BTN, "提交按钮")` 就够了。这是 Page Object 的核心收益之一，见 [[Page Object 模式与分层设计]]。

### 超时值怎么定

- **默认 10 秒**覆盖绝大多数交互；
- **页面跳转/首屏加载** 20~30 秒；
- **报表生成、批量导出**这类明确的慢操作，单独放大到 60 秒并加注释；
- **不要全局设成 60 秒**——失败用例会拖到天荒地老，一轮回归多花几十分钟。超时值是「多久算异常」的业务判断，不是「保险起见调大点」。

## 踩坑

1. **locator 忘了包成元组**
   `EC.element_to_be_clickable(By.ID, "x")` 报 `TypeError: __init__() takes 2 positional arguments but 3 were given`。正确是 `EC.element_to_be_clickable((By.ID, "x"))`。

2. **点击前用 `presence_of_element_located`**
   元素在 DOM 里但还是 `display:none` 或被遮罩盖住，点击抛 `ElementNotInteractableException` / `ElementClickInterceptedException`。点击前用 `element_to_be_clickable`。

3. **`element_to_be_clickable` 也不保证点得到**
   它只检查「可见 + enabled」，**不检查是否被其他元素遮挡**。全屏 loading 遮罩、固定顶栏、Toast 提示都会挡住。稳妥做法是先等遮罩消失：
   ```python
   wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, ".loading-mask")))
   wait.until(EC.element_to_be_clickable(SUBMIT)).click()
   ```

4. **等待「元素出现」但元素一直都在**
   典型场景：列表刷新前后都有 `.order-item`，等它出现瞬间成立，实际拿到的是旧数据。正确做法是等**旧元素 stale**、或等**特定内容出现**、或等 loading 出现再消失。

5. **`presence_of_all_elements_located` 只保证至少 1 个**
   分批渲染的列表会取到不完整数据。要等固定条数用 lambda 判 `len(...) == n`，或等分页器显示总数。

6. **超时值全局调大掩盖真问题**
   把 10 秒改成 60 秒让用例「过了」，其实是页面性能退化。等待时间应该被监控——某个等待突然从 1 秒涨到 20 秒，那是个 bug 不是等待配置问题。

7. **在循环里新建 WebDriverWait**
   每次 `WebDriverWait(driver, 10)` 都是新对象，超时从头计。在 for 循环里等 N 个元素，总耗时可能 N×10 秒。把 wait 提到循环外，或用一个整体条件。

8. **和隐式等待混用导致超时相乘**
   这是最经典的坑，单独一篇讲：[[Selenium 隐式等待与显式等待混用冲突]]。

9. **`poll_frequency` 设得太小**
   `poll_frequency=0.05` 意味着每 50ms 一次 HTTP 往返，10 秒就是 200 次请求，driver 端压力大反而更慢。默认 0.5 秒对绝大多数场景够用，追求响应快可以设 0.2。

10. **没写 `message`**
    失败时只有一行 `TimeoutException` 和一堆栈，看不出等的是什么。`message` 参数几乎零成本，一定要写。

## 面试怎么答

**Q：为什么不能用 `sleep`？**
A：三个问题。第一，浪费时间——元素 1 秒就绪你也要等满 10 秒，几百条用例累积起来是几十分钟；第二，不可靠——CI 机器慢或后端抖动时 10 秒不够，照样失败，你只能不断调大，进入恶性循环；第三也是最关键的，可诊断性差——`sleep` 之后失败抛的是 NoSuchElementException，你分不清是定位写错了还是等得不够久，而显式等待抛 TimeoutException 并且能带上「等待订单列表加载超时」这样的描述。所以 `sleep` 我只在「完全没有 DOM 可观测信号」的极少数场景用，而且必须写注释说明原因。

**Q：`WebDriverWait` 的原理是什么？**
A：它是一个轮询循环。构造时记下 timeout 和 poll interval，`until()` 里循环调用条件函数：返回真值就立即返回该值，返回假值或抛出被忽略的异常（默认忽略 NoSuchElementException）就 sleep 一个 poll 间隔后重试，直到超过 timeout 抛 TimeoutException。因为返回的是条件函数的返回值，所以 `wait.until(EC.element_to_be_clickable(loc)).click()` 可以链式写。条件函数只要是「接收 driver、返回真值」的可调用对象就行，所以可以传 lambda 或自定义类实现任意条件。

**Q：`presence` / `visibility` / `clickable` 怎么选？**
A：按你接下来要做的操作来选。只是判断元素渲染了、要读属性，用 presence；要读文本或断言展示效果，用 visibility，因为 presence 下元素可能是 `display:none` 读出来是空字符串；要点击，用 element_to_be_clickable，它额外检查 enabled。有个重要补充：clickable 也不检查元素有没有被遮挡，全屏 loading 遮罩、Toast、固定顶栏都会挡住点击，所以严谨的点击前置是「先等遮罩不可见，再等按钮可点击」。

**Q：显式等待还是解决不了偶发失败，怎么办？**
A：说明等错了对象。常见的是「等的条件在动作前就已经成立」——比如列表刷新前后都存在 `.item`，等它出现瞬间通过，拿到的其实是旧数据。这类要换成等旧元素 stale、等 loading 出现再消失、或者等待特定内容而非元素存在。再往下如果还不稳，那通常已经不是前端时序问题，而是测试数据或后端异步落库的问题，得从数据层面治理，见我们对 flaky 用例的分层排查方法。

## 参考

- [Selenium · Waiting strategies](https://www.selenium.dev/documentation/webdriver/waits/)
- [Selenium Python API · expected_conditions](https://www.selenium.dev/selenium/docs/api/py/webdriver_support/selenium.webdriver.support.expected_conditions.html)
- 相关笔记：[[Selenium 隐式等待与显式等待混用冲突]]
- 相关笔记：[[Playwright 自动等待机制]]
- 相关笔记：[[Selenium 常见异常排查]]
- 相关笔记：[[Page Object 模式与分层设计]]
- 相关笔记：[[07-Web自动化测试]]
