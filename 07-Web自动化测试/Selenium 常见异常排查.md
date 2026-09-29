---
created: 2026-07-31
tags: [Web自动化测试/稳定性治理]
---

# Selenium 常见异常排查

![[assets/stale-element.svg]]
*图示：StaleElement 的产生过程（引用指向具体 DOM 节点而非选择器），以及四种高频异常「找不到 / 摸不着 / 点不了 / 过期了」的分工与解法。*

> 面试必问的三兄弟：`NoSuchElementException` / `StaleElementReferenceException` / `ElementNotInteractableException`。分清它们，UI 排障就成功了一半。

## 概念

### 四种异常的语义边界

它们描述的是**元素生命周期的四个不同失败点**：

| 异常 | 语义 | 元素在 DOM 里吗 | 常见根因 |
|------|------|:---:|---------|
| `NoSuchElementException` | 找不到 | ✗ | 选择器错、还没渲染、在 iframe/Shadow DOM 内、在另一个窗口 |
| `ElementNotInteractableException` | 摸不着 | ✓ | 不可见、尺寸为 0、disabled、在视口外 |
| `ElementClickInterceptedException` | 点不了 | ✓ | 被遮罩/Toast/固定顶栏挡住 |
| `StaleElementReferenceException` | 过期了 | 曾经在 | 引用的节点被销毁重建 |

**先看报错类型定性，能直接排除掉一大半可能性。**

### StaleElement 的本质

`find_element` 返回的 `WebElement` 内部持有一个 **element id**（形如 `f.8A2...d4.e.42`），它指向浏览器端一个**具体的 DOM 节点对象**，而不是「那个选择器」。

当前端重渲染时（React 的 reconciliation、Vue 的 patch、jQuery 的 `.html()` 替换），旧节点被销毁、新节点被创建——**即使新节点长得一模一样、选择器也能匹配到，它也是另一个对象**。此时用旧的 element id 去操作，driver 找不到对应节点，抛 Stale。

典型触发场景：

1. 表格排序、分页、筛选后操作行内元素；
2. 点击后局部 DOM 被替换（Tab 切换、列表刷新）；
3. 页面跳转/刷新后使用之前的引用；
4. 轮询刷新的看板类页面（最难缠，随时可能重渲染）；
5. 从 iframe 切出后使用 iframe 内的元素引用。

**根治方式只有一个：不缓存 WebElement，用的时候重新定位。**

Playwright 的 locator 是惰性的、每次动作重新解析 DOM，所以**根本不存在这个异常**——这是它架构上的直接收益，见 [[Playwright 语义定位器]]。

### ElementClickIntercepted 的报错很有用

```text
ElementClickInterceptedException: Message: element click intercepted:
Element <button data-testid="submit">...</button> is not clickable at point (640, 380).
Other element would receive the click: <div class="ant-spin-blur">...</div>
```

**最后一行直接告诉你谁挡住了**。这是排查这类问题最快的入口——不需要猜，报错里就有答案。

## 用法

### 通用排查五步法

遇到定位类失败，按这个顺序走，不要跳步：

```text
1. 看报错类型 → 定性是"找不到""摸不着""点不了"还是"过期了"
2. 加显式等待 → 大多数是时序问题，等待能解决就是渲染慢
3. 检查上下文 → 是不是在 iframe / Shadow DOM / 另一个窗口里
4. 验证选择器 → DevTools 控制台 $$("...").length 是否为 1
5. 看失败截图和页面源码 → 页面到底停在什么状态（是不是根本没登录、报错页、权限不足）
```

**第 5 步经常被跳过，但它能解决最诡异的一类问题**——比如「所有用例都找不到元素」，截图一看是登录态失效跳到了登录页。

### 失败时自动收集现场

排查的前提是有现场。在 conftest 里挂钩子：

```python
# conftest.py
import pytest
from pathlib import Path
from datetime import datetime

@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return

    driver = item.funcargs.get("driver")
    if driver is None:
        return

    ts = datetime.now().strftime("%H%M%S")
    out = Path("artifacts") / f"{item.name}_{ts}"
    out.mkdir(parents=True, exist_ok=True)
    try:
        driver.save_screenshot(str(out / "screen.png"))
        (out / "page.html").write_text(driver.page_source, encoding="utf-8")
        (out / "url.txt").write_text(driver.current_url, encoding="utf-8")
        logs = driver.get_log("browser")          # 浏览器控制台日志（Chrome）
        (out / "console.log").write_text(
            "\n".join(f"{e['level']}: {e['message']}" for e in logs), encoding="utf-8"
        )
    except Exception as e:      # 截图本身失败（比如有未处理 alert）不能影响报告
        print(f"收集失败现场时出错: {e}")
```

**`get_log("browser")` 常被忽略但很有价值**——前端 JS 报错会导致页面渲染中断，元素永远不出现，控制台日志能直接看到根因。

详见 [[UI 用例失败重跑与截图 trace]]。

### 处理 StaleElement：重新定位

```python
# ✗ 缓存引用
rows = driver.find_elements(By.CSS_SELECTOR, "[data-testid='order-item']")
driver.find_element(By.ID, "refresh").click()
for row in rows:              # 刷新后 rows 里的引用全部 stale
    print(row.text)

# ✓ 用到时重新定位
driver.find_element(By.ID, "refresh").click()
wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='order-item']")))
count = len(driver.find_elements(By.CSS_SELECTOR, "[data-testid='order-item']"))
for i in range(count):
    row = driver.find_elements(By.CSS_SELECTOR, "[data-testid='order-item']")[i]   # 每轮重新取
    print(row.text)
```

更好的做法是**按业务主键定位**而不是按索引遍历，见 [[元素定位稳定性策略与 data-testid]]。

### 通用重试装饰器

对轮询刷新的页面，重新定位也可能在下一毫秒又 stale。这时需要一个重试层：

```python
import time
import functools
from selenium.common.exceptions import (
    StaleElementReferenceException,
    ElementClickInterceptedException,
)

def retry_on_stale(times: int = 3, delay: float = 0.3):
    """对可能因 DOM 重建而失败的操作做有限重试。"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last = None
            for attempt in range(times):
                try:
                    return func(*args, **kwargs)
                except (StaleElementReferenceException,
                        ElementClickInterceptedException) as e:
                    last = e
                    time.sleep(delay)
            raise last
        return wrapper
    return decorator


@retry_on_stale(times=3)
def click_order_cancel(driver, order_no: str):
    row = driver.find_element(
        By.CSS_SELECTOR, f"[data-testid='order-item'][data-order-no='{order_no}']"
    )
    row.find_element(By.CSS_SELECTOR, "[data-testid='cancel']").click()
```

**注意重试次数要有限且要短**。无限重试会把「元素真的不存在」拖成超时，掩盖真实问题。

### 处理 ElementNotInteractable

```python
el = driver.find_element(By.ID, "target")

# 情况 1：在视口外 → 滚进来
driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)

# 情况 2：还是 disabled → 等它 enabled（通常是表单校验没过）
wait.until(lambda d: d.find_element(By.ID, "target").is_enabled())

# 情况 3：真正的 input 被隐藏，只有 label 可点
driver.find_element(By.CSS_SELECTOR, "label[for='target']").click()

# 情况 4：元素还在展开动画中 → 等位置稳定
def position_stable(locator, tolerance=1):
    def _check(d):
        el = d.find_element(*locator)
        p1 = el.location
        time.sleep(0.15)
        p2 = el.location
        return abs(p1["x"] - p2["x"]) <= tolerance and abs(p1["y"] - p2["y"]) <= tolerance
    return _check

wait.until(position_stable((By.ID, "target")))
```

### 处理 ElementClickIntercepted

```python
# ✓ 正解：等遮挡元素消失（报错信息里已经告诉你是谁了）
wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, ".ant-spin-blur")))
wait.until(EC.element_to_be_clickable((By.ID, "submit"))).click()

# ✓ 固定顶栏遮挡：滚动到居中位置
driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
el.click()

# △ 降级：JS 点击（只在确认是纯装饰性遮挡时用，且要加注释说明原因）
driver.execute_script("arguments[0].click();", el)
```

**不要把 JS 点击当默认解法**——遮罩存在通常意味着页面真的还在加载，绕过它就是在制造假通过，见 [[Selenium JavaScript 执行、滚动与拖拽]]。

### 其他值得认识的异常

| 异常 | 含义 | 处理 |
|------|------|------|
| `TimeoutException` | 显式等待超时 | 看 `message` 确认等的是什么；条件选错还是页面真慢 |
| `InvalidSelectorException` | 选择器语法非法 | XPath 2.0 函数、CSS 里用了 `:contains` |
| `UnexpectedAlertPresentException` | 有未处理的原生弹窗 | 见 [[Selenium alert 弹窗与多窗口切换]] |
| `NoSuchWindowException` | 当前窗口已关闭 | `close()` 后忘了 `switch_to` |
| `NoSuchFrameException` | iframe 不可用 | 用 `frame_to_be_available_and_switch_to_it` 等待 |
| `SessionNotCreatedException` | 会话创建失败 | driver 与浏览器版本不匹配 |
| `InvalidSessionIdException` | 会话已失效 | 浏览器崩了、`quit()` 之后又操作 |
| `WebDriverException: chrome not reachable` | 浏览器进程没了 | 容器内存/`/dev/shm` 不足，或被 OOM kill |
| `MoveTargetOutOfBoundsException` | ActionChains 移出视口 | 先 `scrollIntoView` |
| `JavascriptException` | 注入脚本报错 | 检查脚本语法与返回值可序列化 |

### 让异常自带上下文

裸抛的 Selenium 异常信息量很低。在 BasePage 里包一层，排查效率会有质变：

```python
def click(self, locator, desc: str = ""):
    try:
        self.wait.until(EC.element_to_be_clickable(locator)).click()
    except TimeoutException as e:
        raise TimeoutException(
            f"[{self.__class__.__name__}] 点击「{desc or locator}」失败："
            f"元素未在 {self.timeout}s 内变为可点击；当前 URL={self.driver.current_url}"
        ) from e
```

## 踩坑

1. **看到 NoSuchElement 就无脑加 `sleep`**
   有时能碰对，但掩盖了真实原因，而且下次在更慢的机器上又失败。按五步法定性再动手。

2. **在循环里持有元素引用**
   列表遍历时最容易踩 Stale。每轮重新定位，或者按业务主键定位单个元素。

3. **用 `try/except: pass` 吞掉异常**
   用例「通过」了但什么都没验证。异常要么处理要么抛出，绝不静默吞掉。

4. **无限重试**
   `while True` 重试 stale，遇到元素真的消失就死循环到超时。重试次数要有上限。

5. **失败截图钩子自己抛异常**
   有未处理 alert 时 `save_screenshot` 会抛 `UnexpectedAlertPresentException`，导致钩子挂掉、报告缺失。钩子内部要 try 包住。

6. **忽略浏览器控制台日志**
   前端 JS 报错导致渲染中断时，元素永远不出现。`driver.get_log("browser")` 能直接看到根因，省下大量猜测时间。

7. **误判 Stale 是框架 bug**
   它是正确的行为——引用指向的节点确实没了。要改的是「不要缓存引用」这个写法。

8. **多个异常混在一起处理**
   `except WebDriverException` 把所有异常一网打尽，然后统一重试。不同异常的正确处理方式完全不同，要分开捕获。

9. **只看最后一行报错**
   Selenium 异常的 `Stacktrace` 部分常包含浏览器端信息（比如拦截元素），别忽略。

10. **CI 上失败但本机复现不了**
    大概率是速度差异（CI 更慢）或分辨率差异（无头默认窗口小导致元素在视口外）。先在本机用 `--headless=new --window-size` 复现，再看 CI 的失败截图。

## 面试怎么答

**Q：`NoSuchElementException`、`StaleElementReferenceException`、`ElementNotInteractableException` 分别什么原因？**
A：它们对应元素生命周期的三个不同失败点。NoSuchElement 是「找不到」——元素不在当前查找上下文里，可能是选择器写错、元素还没渲染、在 iframe 或 Shadow DOM 内部、或者在另一个窗口。ElementNotInteractable 是「摸不着」——元素在 DOM 里但不可交互，比如不可见、尺寸为 0、disabled 或者在视口外。StaleElement 是「过期了」——WebElement 内部持有的是一个具体 DOM 节点的引用，前端重渲染后旧节点被销毁，即使新节点长得一样、选择器还能匹配，那也是另一个对象，用旧引用操作就会抛这个异常。还有个相近的 ElementClickIntercepted 是「点不了」，元素可交互但被遮罩挡住了，报错信息里会直接给出拦截它的元素。

**Q：StaleElement 怎么根治？**
A：根本原因是缓存了元素引用，所以根治方式就是不缓存——用的时候重新定位。列表遍历尤其容易踩坑，要么每轮重新 `find_elements` 取，要么更好的做法是按业务主键定位单个元素而不是按索引遍历。对于会轮询刷新的看板类页面，重新定位也可能立刻又 stale，这时加一层有限次数的重试装饰器，注意次数要有上限，无限重试会把「元素真的不存在」拖成超时，掩盖真问题。顺带一提，Playwright 根本没有这个异常，因为它的 locator 是惰性的，每次动作都重新解析 DOM。

**Q：元素被遮挡点不到怎么办？**
A：先看报错，`ElementClickInterceptedException` 的信息里会写明「Other element would receive the click」是哪个元素，通常是 loading 遮罩、Toast 提示或者固定顶栏。正确解法是等那个遮挡元素消失再点，固定顶栏的情况用 `scrollIntoView({block:'center'})` 把目标滚到视口中间。用 JS 点击强行绕过是最后手段，因为遮罩存在往往意味着页面真的还在加载，真实用户此刻也点不到，绕过它就是在制造假通过——如果遮罩永远不消失，那是发现了一个 bug，这才是自动化的价值。

**Q：你排查 UI 用例失败的流程是什么？**
A：五步。第一步看异常类型定性，是找不到、摸不着、点不了还是过期了，这一步能排除大半可能性。第二步加显式等待验证是不是时序问题，绝大多数偶发失败都是。第三步检查上下文，是不是在 iframe、Shadow DOM 或者另一个窗口里。第四步在 DevTools 控制台验证选择器命中数是不是 1。第五步——这步最容易被跳过——看失败截图、页面源码和浏览器控制台日志，确认页面到底停在什么状态。我遇到过「所有用例都找不到元素」，截图一看是登录态失效跳到登录页了；也遇到过前端 JS 报错导致渲染中断，控制台日志里写得清清楚楚。所以我会在 conftest 里挂 `pytest_runtest_makereport` 钩子，失败时自动收集截图、page_source、当前 URL 和浏览器控制台日志，没有现场什么都查不了。

## 参考

- [Selenium · Common exceptions](https://www.selenium.dev/documentation/webdriver/troubleshooting/errors/)
- [W3C WebDriver · Errors](https://www.w3.org/TR/webdriver2/#errors)
- 相关笔记：[[Selenium 显式等待]]
- 相关笔记：[[iframe 与 Shadow DOM 切换]]
- 相关笔记：[[UI 用例失败重跑与截图 trace]]
- 相关笔记：[[Selenium JavaScript 执行、滚动与拖拽]]
- 相关笔记：[[07-Web自动化测试]]
