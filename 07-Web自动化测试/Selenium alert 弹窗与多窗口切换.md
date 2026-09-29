---
created: 2026-07-31
tags: [Web自动化测试/交互]
---

# Selenium alert 弹窗与多窗口切换

![[assets/window-handles.svg]]
*图示：新窗口打开后 driver 的 current 仍指向原窗口，必须显式按句柄切换；alert 是浏览器级模态框，不在 DOM 里，未处理时任何 DOM 操作都会抛异常。*

> 两类「不在当前 DOM 里」的对象：浏览器原生弹窗和新窗口/标签页。它们都需要显式切换上下文，忘了切就是一连串怪异报错。

## 概念

### alert：浏览器级模态框，不在 DOM 里

`alert()` / `confirm()` / `prompt()` 是**浏览器渲染的原生对话框**，不是页面元素。用 `find_element` 永远找不到它，DevTools 里也看不到对应节点。

它弹出时会**冻结页面的 JS 执行**（同步阻塞），此时 WebDriver 的任何 DOM 操作都会抛：

```text
UnexpectedAlertPresentException: Alert Text: 确认删除该订单？
Message: unexpected alert open: {Alert text : 确认删除该订单？}
```

三种原生弹窗的差别：

| 类型 | JS 返回值 | Selenium 处理 |
|------|----------|--------------|
| `alert("msg")` | `undefined` | `accept()`（只有确定按钮） |
| `confirm("msg")` | `true` / `false` | `accept()` → true，`dismiss()` → false |
| `prompt("msg", "默认")` | 输入的字符串 / `null` | `send_keys("x")` 后 `accept()` |

**注意区分**：页面上那些好看的「确认对话框」（Ant Design Modal、ElementUI MessageBox）**是普通 DOM 元素**，用 `find_element` 正常定位就行，跟 `switch_to.alert` 无关。判断方法：能在 DevTools 里选中的就是 DOM 弹窗。

### 窗口句柄（window handle）

每个窗口/标签页有一个唯一的字符串句柄，形如 `CDwindow-4A6E7B...`。WebDriver 会话有一个「当前窗口」状态：

- `driver.current_window_handle` → 当前窗口句柄；
- `driver.window_handles` → 所有句柄的列表；
- `driver.switch_to.window(handle)` → 切换当前窗口。

**关键点：点击 `target="_blank"` 链接后，浏览器确实开了新标签页，但 driver 的当前窗口仍然指向原窗口。** 这就是「新页面明明打开了，元素却找不到」的原因。

另一个坑：`window_handles` 的顺序**不保证**是打开顺序（规范未定义，各 driver 实现不同）。所以不能写 `handles[-1]`，要用**差集**求新句柄。

## 用法

### alert 处理

```python
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

wait = WebDriverWait(driver, 10)

driver.find_element(By.ID, "delete-btn").click()

alert = wait.until(EC.alert_is_present())     # 等待弹窗出现，不要裸 driver.switch_to.alert
print(alert.text)                              # 读取提示文案，通常需要断言
alert.accept()                                 # 点"确定"
# alert.dismiss()                              # 点"取消"

# prompt 输入
alert = wait.until(EC.alert_is_present())
alert.send_keys("测试备注")
alert.accept()
```

`EC.alert_is_present()` 会返回 `Alert` 对象，所以可以直接接着用。**不要写 `driver.switch_to.alert` 后立刻操作**——弹窗可能还没弹出来，抛 `NoAlertPresentException`。

### 兜底：清理意外弹窗

有些页面在 `beforeunload` 时会弹「确定要离开吗」，会污染后续用例。用例收尾加一层兜底：

```python
from selenium.common.exceptions import NoAlertPresentException

def dismiss_any_alert(driver):
    try:
        driver.switch_to.alert.dismiss()
    except NoAlertPresentException:
        pass          # 没有弹窗是正常情况
```

### 提前禁用 alert（更彻底的做法）

如果测试目标不是弹窗本身，可以在页面加载后把原生弹窗函数替换掉，从根上消除干扰：

```python
driver.execute_script("""
    window.alert = function(){};
    window.confirm = function(){ return true; };     // 默认全部确认
    window.prompt = function(){ return 'auto'; };
""")
```

**这是双刃剑**：它改变了被测系统行为，只适合弹窗不属于测试关注点的场景（比如清理埋点弹窗），核心业务确认框不能这么做。

### 多窗口切换：完整流程

```python
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

wait = WebDriverWait(driver, 10)

origin = driver.current_window_handle          # ① 记住原窗口
before = set(driver.window_handles)

driver.find_element(By.CSS_SELECTOR, "a[target='_blank']").click()

wait.until(EC.number_of_windows_to_be(len(before) + 1))    # ② 等新窗口真的出现
new_handle = (set(driver.window_handles) - before).pop()   # ③ 差集求新句柄，不依赖顺序

driver.switch_to.window(new_handle)            # ④ 切过去
assert "订单详情" in driver.title
driver.find_element(By.ID, "confirm").click()

driver.close()                                  # ⑤ 关掉新窗口（只关当前窗口）
driver.switch_to.window(origin)                 # ⑥ 必须切回！否则后续抛 NoSuchWindowException
```

第 ⑥ 步是最容易漏的：**`close()` 之后当前窗口已经不存在了，driver 处于「悬空」状态**，任何操作都会报 `NoSuchWindowException: target window already closed`。

### 封装成上下文管理器

把「触发动作」作为回调传进去，切换与回收都由封装保证：

```python
from contextlib import contextmanager
from typing import Callable

@contextmanager
def opened_window(driver, trigger: Callable[[], None], timeout: int = 10):
    """执行 trigger 触发新窗口，自动切入；退出时关闭新窗口并切回原窗口。"""
    origin = driver.current_window_handle
    before = set(driver.window_handles)

    trigger()
    WebDriverWait(driver, timeout).until(
        lambda d: len(set(d.window_handles) - before) == 1
    )
    new_handle = (set(driver.window_handles) - before).pop()
    driver.switch_to.window(new_handle)
    try:
        yield new_handle
    finally:
        if new_handle in driver.window_handles:
            driver.close()
        driver.switch_to.window(origin)

# 使用
trigger = lambda: driver.find_element(By.CSS_SELECTOR, "a[target='_blank']").click()
with opened_window(driver, trigger):
    assert "订单详情" in driver.title
    driver.find_element(By.ID, "confirm").click()
# 出了 with：新窗口已关闭，当前窗口已切回原窗口
```

### Selenium 4 主动开新标签页

```python
driver.switch_to.new_window("tab")        # 新标签页，并自动切过去
driver.switch_to.new_window("window")     # 新窗口
driver.get("https://example.com/other")
```

比「用 JS `window.open()` 再手动切」干净得多。

### Playwright：事件驱动，不用管句柄

Playwright 用**事件捕获**而不是句柄枚举：

```python
# 新页面
with context.expect_page() as page_info:          # 先声明"接下来会开新页"
    page.get_by_role("link", name="查看详情").click()
new_page = page_info.value                         # 拿到新 Page 对象
new_page.wait_for_load_state()
expect(new_page).to_have_title(re.compile("订单详情"))
new_page.close()
# page 仍然指原页面，不需要切回

# 弹窗：预先注册处理器（必须在触发前注册）
page.on("dialog", lambda dialog: dialog.accept())
page.get_by_role("button", name="删除").click()

# 需要断言弹窗文案时
with page.expect_event("dialog") as info:
    page.get_by_role("button", name="删除").click()
dialog = info.value
assert dialog.message == "确认删除该订单？"
dialog.accept()
```

**Playwright 默认会自动 dismiss 所有 dialog**（没注册 handler 时），这和 Selenium 的「卡住报错」相反。所以如果你的用例依赖弹窗点确定，必须显式注册 `page.on("dialog", ...)`。

## 踩坑

1. **点了新窗口链接直接找元素**
   报 NoSuchElement。driver 的当前窗口没变，必须显式切换。这个坑排在多窗口问题第一位。

2. **用 `window_handles[-1]` 取新窗口**
   顺序不保证，Firefox 和 Chrome 行为还不一致。永远用差集：`set(after) - set(before)`。

3. **点击后立刻取句柄**
   新窗口的创建是异步的，点击返回时 `window_handles` 可能还是 1 个。必须 `wait.until(EC.number_of_windows_to_be(n))`。

4. **`close()` 后没切回去**
   `NoSuchWindowException: target window already closed`。close 和 switch 要成对出现，最好用上下文管理器保证。

5. **`close()` 关掉了最后一个窗口**
   整个会话结束，后续所有操作抛 `InvalidSessionIdException`。收尾用 `quit()`，中途关子窗口才用 `close()`。

6. **把 DOM 弹窗当 alert 处理**
   对 Ant Design 的 Modal 用 `switch_to.alert` 会抛 `NoAlertPresentException`。判断标准：DevTools 能选中的是 DOM，选不中的才是原生 alert。

7. **alert 弹出时截图失败**
   `driver.save_screenshot()` 在有未处理 alert 时会抛 `UnexpectedAlertPresentException`，导致失败截图钩子自己也挂了。失败截图逻辑里要先 try 一下 dismiss alert，见 [[UI 用例失败重跑与截图 trace]]。

8. **`unhandledPromptBehavior` 配置影响行为**
   W3C 规范定义了这个能力（默认 `dismiss and notify`）。设成 `ignore` 后 alert 不会被自动关掉，某些 driver 版本行为差异大，排查诡异弹窗问题时可以查这个配置。

9. **Playwright 里忘记注册 dialog handler**
   Playwright 默认自动 dismiss，导致「点了确定却没生效」——因为实际点的是取消。要 accept 必须显式注册。

10. **新窗口被浏览器拦截**
    无头模式或某些 popup blocker 配置下，`window.open()` 触发的窗口可能被拦。用 `--disable-popup-blocking` 或改为直接 `driver.get(url)` 走同窗口。

## 面试怎么答

**Q：怎么处理浏览器原生弹窗？**
A：`alert` / `confirm` / `prompt` 是浏览器渲染的模态框，不在 DOM 里，`find_element` 找不到。用 `WebDriverWait` 配 `EC.alert_is_present()` 等它出现并拿到 Alert 对象，然后 `text` 读文案做断言，`accept()` 确定、`dismiss()` 取消，prompt 还能 `send_keys` 输入。要特别区分的是页面上那些组件库的 Modal 确认框，那些是普通 DOM 元素，正常定位就行，用 `switch_to.alert` 反而会报 NoAlertPresent。

**Q：点击链接打开新标签页，怎么操作新页面？**
A：driver 有「当前窗口」这个状态，新窗口打开后当前窗口不会自动变。标准流程是：点击前记下 `current_window_handle` 和当前句柄集合，点击后用 `EC.number_of_windows_to_be` 等新窗口出现，再用集合差集求出新句柄（不能用 `handles[-1]`，顺序不保证），`switch_to.window` 切过去操作，用完 `close()` 再 `switch_to.window(原句柄)` 切回来。close 之后不切回去，后续任何操作都会抛 NoSuchWindowException。我一般把这套封装成上下文管理器，用 `finally` 保证切回。

**Q：Playwright 处理这两类场景有什么不同？**
A：Playwright 是事件驱动的。新页面用 `with context.expect_page()` 包住触发动作，直接拿到新的 Page 对象，不需要句柄也不需要切回，因为 `page` 变量本来就各指各的。弹窗用 `page.on("dialog", handler)` 预先注册处理器，或者用 `expect_event("dialog")` 捕获后断言文案。有个重要差异：Playwright 在没注册 handler 时**默认自动 dismiss** 所有对话框，所以依赖「点确定」的用例必须显式注册 accept，否则会静默走了取消分支——这个坑比 Selenium 的直接报错更隐蔽。

## 参考

- [Selenium · JavaScript alerts, prompts and confirmations](https://www.selenium.dev/documentation/webdriver/interactions/alerts/)
- [Selenium · Working with windows and tabs](https://www.selenium.dev/documentation/webdriver/interactions/windows/)
- [Playwright · Dialogs](https://playwright.dev/python/docs/dialogs)
- [Playwright · Pages（多标签页）](https://playwright.dev/python/docs/pages)
- 相关笔记：[[iframe 与 Shadow DOM 切换]]
- 相关笔记：[[Selenium 常见异常排查]]
- 相关笔记：[[Selenium 显式等待]]
- 相关笔记：[[07-Web自动化测试]]
