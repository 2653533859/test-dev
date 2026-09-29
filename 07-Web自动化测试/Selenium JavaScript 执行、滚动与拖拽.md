---
created: 2026-07-31
tags: [Web自动化测试/交互]
---

# Selenium JavaScript 执行、滚动与拖拽

> `execute_script` 是把双刃剑：能解决 90% 的疑难交互，也能悄悄让用例变成「假通过」。这篇讲清什么时候该用、什么时候绝不能用。

## 概念

### execute_script 做了什么

```python
driver.execute_script("return document.title")
```

driver 把这段字符串发给浏览器，在**当前页面的 JS 上下文里**求值，返回值序列化回来。类型映射规则：

| JS 返回 | Python 收到 |
|---------|------------|
| DOM 元素 | `WebElement`（可以继续 `.click()`） |
| 元素数组 | `list[WebElement]` |
| number / string / boolean | 对应的 Python 类型 |
| object | `dict` |
| `undefined` / 无 return | `None` |

参数通过 `arguments` 数组传入，**WebElement 会被自动转换成 JS 的 DOM 节点**：

```python
el = driver.find_element(By.ID, "x")
driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
driver.execute_script("return arguments[0] + arguments[1];", 1, 2)     # 3
```

### 什么时候用 JS 是对的，什么时候是错的

这是本篇最重要的判断标准：

**✓ 合理使用**——做「用户做不到但也不该测」的辅助动作：

- 滚动页面到某个位置；
- 读取 DOM 状态（`getComputedStyle`、`scrollHeight`、`localStorage`）；
- 造前置数据（写 localStorage/sessionStorage、注入 token 跳过登录）；
- 让隐藏的 file input 可交互（见 [[Selenium 文件上传与下载]]）；
- 清理干扰元素（关掉客服浮窗、埋点弹层）。

**✗ 错误使用**——用 JS 替代本应验证的用户交互：

- `arguments[0].click()` 绕过遮罩/不可见/disabled；
- `arguments[0].value='x'` 代替 `send_keys`；
- `arguments[0].removeAttribute('disabled')` 后再点。

错误使用的共同问题：**它们让用例在真实用户做不到的情况下"通过"了**。按钮被 loading 遮罩挡住说明页面还没就绪，disabled 说明前端校验没过——这些都是真实的产品状态，绕过它们等于把测试变成了「验证 DOM 里有这个元素」，失去了端到端测试的意义。

**一个自检问题：真实用户此刻能做到这个操作吗？** 答案是「不能」的话，就不该用 JS 绕过。

## 用法

### 滚动

```python
# 滚动到元素（最常用）
el = driver.find_element(By.ID, "footer-btn")
driver.execute_script("arguments[0].scrollIntoView({block:'center', behavior:'instant'});", el)

# 滚到页面顶部/底部
driver.execute_script("window.scrollTo(0, 0);")
driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

# 相对滚动
driver.execute_script("window.scrollBy(0, 500);")

# 容器内部滚动（侧边栏、弹窗内列表）
driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", container_el)
```

**`block:'center'` 而不是默认的 `'start'`**：默认会把元素滚到视口顶部，而很多站点有固定顶栏（fixed header），元素会被顶栏盖住导致点不到。居中最安全。

**`behavior:'instant'` 而不是 `'smooth'`**：平滑滚动是动画，滚动过程中立刻点击会落空。要么用 instant，要么滚完等位置稳定。

### 无限滚动加载

```python
import time

def scroll_to_load_all(driver, max_rounds: int = 20) -> int:
    """向下滚动直到页面高度不再变化，返回滚动轮数。"""
    last_height = driver.execute_script("return document.body.scrollHeight")
    for i in range(max_rounds):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        try:
            WebDriverWait(driver, 5).until(
                lambda d: d.execute_script("return document.body.scrollHeight") > last_height
            )
        except TimeoutException:
            return i        # 高度不再增长，说明加载完了
        last_height = driver.execute_script("return document.body.scrollHeight")
    raise AssertionError(f"滚动 {max_rounds} 轮仍在加载，可能是死循环或数据量超预期")
```

用 `WebDriverWait` 判断高度变化而不是 `sleep(2)`，快很多也更可靠。加 `max_rounds` 上限防止死循环。

### 读取 DOM 状态

```python
# 伪元素内容（Selenium 拿不到伪元素，只能靠 JS）
content = driver.execute_script(
    "return window.getComputedStyle(arguments[0], '::before').getPropertyValue('content');", el
)

# 实际生效的样式
color = driver.execute_script(
    "return window.getComputedStyle(arguments[0]).color;", el
)

# 元素是否真的在视口内
in_view = driver.execute_script("""
    const r = arguments[0].getBoundingClientRect();
    return r.top >= 0 && r.left >= 0
        && r.bottom <= window.innerHeight && r.right <= window.innerWidth;
""", el)

# 页面是否加载完成
driver.execute_script("return document.readyState") == "complete"

# 前端框架就绪标志
driver.execute_script("return !!window.__NUXT__")
```

### 造前置数据：跳过登录

这是 JS 执行**最有价值**的用法之一，能给回归套件省下大量时间：

```python
# 先通过接口拿 token（比走 UI 登录快得多）
import requests
token = requests.post("https://example.com/api/login",
                      json={"user": "qa01", "pwd": "***"}).json()["token"]

driver.get("https://example.com")           # 必须先访问同域页面，否则 localStorage 写不进去
driver.execute_script("window.localStorage.setItem('token', arguments[0]);", token)
driver.add_cookie({"name": "sid", "value": token, "domain": ".example.com"})
driver.refresh()                             # 刷新后进入已登录态
```

**顺序很重要**：`localStorage` 和 `add_cookie` 都是域绑定的，必须**先 `get()` 到目标域**才能写。在 `about:blank` 上写会抛异常或静默失效。

### 清理干扰元素

```python
# 关掉客服浮窗、广告条这类会挡住点击的元素
driver.execute_script("""
    document.querySelectorAll('.customer-service-float, .ad-banner, .cookie-tip')
            .forEach(e => e.remove());
""")
```

**这属于合理使用**：这些元素不是测试目标，且真实用户会手动关掉它们。但如果一个元素挡住了业务按钮而用户关不掉，那是 bug，不该由测试代码抹平。

### ActionChains：真实的鼠标与键盘序列

需要 hover、拖拽、右键、双击时，用 `ActionChains` 而不是 JS——它派发的是**真实的鼠标事件序列**：

```python
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys

actions = ActionChains(driver)

# 悬停展开菜单
actions.move_to_element(menu).perform()
wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".submenu")))
driver.find_element(By.CSS_SELECTOR, ".submenu-item").click()

# 右键
actions.context_click(el).perform()

# 双击
actions.double_click(el).perform()

# 按住修饰键点击（多选）
actions.key_down(Keys.CONTROL).click(item1).click(item2).key_up(Keys.CONTROL).perform()

# 链式：移动 → 点击 → 输入
actions.move_to_element(el).click().send_keys("text").perform()
```

**`perform()` 才真正执行**——ActionChains 是把动作攒成队列，忘了 `perform()` 是常见错误（代码不报错，但什么也没发生）。

### 拖拽：三种方案

**方案 A：`drag_and_drop`（HTML5 拖拽下经常失效）**

```python
actions.drag_and_drop(source, target).perform()
```

它内部是 `click_and_hold` + `move_to_element` + `release`。对 jQuery UI 这类基于 mouse 事件的拖拽有效，但**对 HTML5 原生拖拽（`draggable="true"` + dragstart/drop 事件）经常无效**——因为 HTML5 拖拽由浏览器底层的拖放子系统驱动，合成的鼠标事件触发不了它。

**方案 B：分步 + 中间停顿（提高成功率）**

```python
actions.click_and_hold(source).pause(0.3) \
       .move_to_element(target).pause(0.3) \
       .move_by_offset(2, 2).pause(0.3) \
       .release().perform()
```

多加几个中间移动点和停顿，能让前端的 dragover 逻辑有机会响应。**这是排序列表、看板拖拽最实用的写法。**

**方案 C：JS 模拟 HTML5 拖拽事件**

```python
JS_DND = """
const src = arguments[0], tgt = arguments[1];
const dt = new DataTransfer();
['dragstart','dragenter','dragover','drop','dragend'].forEach(type => {
    const evt = new DragEvent(type, {bubbles:true, cancelable:true, dataTransfer:dt});
    (type === 'dragstart' || type === 'dragend' ? src : tgt).dispatchEvent(evt);
});
"""
driver.execute_script(JS_DND, source, target)
```

**这是降级方案**：能让用例跑通，但没有验证真实的拖拽体验。用之前要想清楚——如果拖拽本身就是被测功能，用 JS 模拟就等于没测。这种场景更推荐 Playwright：

```python
page.drag_and_drop("#src", "#dst")                    # 对 HTML5 拖拽支持更好
# 或手动控制轨迹
page.locator("#src").hover()
page.mouse.down()
page.locator("#dst").hover()
page.mouse.up()
```

### 滑块验证码

```python
slider = driver.find_element(By.CSS_SELECTOR, ".slider-btn")
actions.click_and_hold(slider)
for dx in [50, 60, 40, 30, 15, 5]:      # 模拟人手的变速轨迹
    actions.move_by_offset(dx, 0).pause(0.1)
actions.pause(0.3).release().perform()
```

**但更该做的是让测试环境关掉验证码**。验证码的设计目标就是「阻止自动化」，用自动化去破解它是在和产品的安全设计对抗，投入产出比极低且随时会因风控升级而失效。正确做法是推动提供测试环境白名单或万能验证码。

## 踩坑

1. **用 JS 点击绕过遮罩**
   最常见的错误用法。遮罩存在通常意味着页面真的还在加载，真实用户此刻也点不到。应该等遮罩消失，等不到就是发现了 bug。

2. **用 JS 赋值代替 `send_keys`**
   `arguments[0].value='x'` 不触发 `input` 事件，React/Vue 的 state 完全不更新，提交时发出去的还是旧值——而用例还会「通过」。这是最危险的假通过。必须补派发事件：
   ```python
   driver.execute_script("""
       const el = arguments[0];
       const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
       setter.call(el, arguments[1]);
       el.dispatchEvent(new Event('input', {bubbles:true}));
   """, el, "新值")
   ```
   但既然要写这么多，不如老老实实用 `send_keys`。

3. **忘记 `perform()`**
   ActionChains 不执行也不报错，静默失败。

4. **`move_by_offset` 越界**
   偏移量算错让鼠标移出视口，抛 `MoveTargetOutOfBoundsException`。先 `scrollIntoView` 再算偏移。

5. **`scrollIntoView` 后元素被固定顶栏遮挡**
   默认 `block:'start'` 把元素滚到视口顶部，正好在 fixed header 下面。用 `block:'center'`。

6. **smooth 滚动导致点击落空**
   滚动是动画，`scrollIntoView` 返回时元素还在移动。用 `behavior:'instant'`，或滚完等位置稳定。

7. **在 `about:blank` 上写 localStorage**
   抛 `SecurityError` 或静默失效。必须先 `driver.get()` 到目标域。

8. **`execute_script` 返回值序列化失败**
   返回包含循环引用的对象（比如 `window`、DOM 节点的父链）会报错或卡住。只返回基本类型、数组、简单对象或 DOM 元素。

9. **`execute_async_script` 忘了调 callback**
   异步脚本的最后一个参数是回调，不调就一直等到 `script_timeout` 超时：
   ```python
   driver.execute_async_script("""
       const done = arguments[arguments.length - 1];
       setTimeout(() => done('ok'), 1000);
   """)
   ```

10. **HTML5 拖拽用 `drag_and_drop` 无效**
    没报错但什么都没发生，很迷惑。改用分步 + pause，或 JS 模拟，或换 Playwright。

11. **拿 JS 读到的样式做断言过于严格**
    `getComputedStyle` 返回的颜色是 `rgb(255, 0, 0)` 而不是 `#ff0000`，字体大小带 `px` 单位。断言前要归一化。

## 面试怎么答

**Q：什么时候用 `execute_script`？**
A：我的判断标准是一个自检问题——真实用户此刻能做到这个操作吗。能做到的操作就该用真实交互 API，做不到但也不该测的辅助动作才用 JS。合理场景包括：滚动到元素、读取 `getComputedStyle` 或伪元素这类 Selenium 拿不到的状态、写 localStorage 注入 token 跳过登录、让隐藏的 file input 可交互、清理客服浮窗这类干扰元素。不合理的是用 `arguments[0].click()` 绕过遮罩、用 `value=` 代替 `send_keys`、用 `removeAttribute('disabled')` 后再点——这些让用例在真实用户做不到的情况下通过了，测试就失去了意义。

**Q：用 JS 直接给输入框赋值有什么问题？**
A：不触发 `input` 事件，React/Vue 这类框架的 state 完全不更新。表现是用例「通过」了，但实际提交给后端的还是旧值，等于测了个寂寞——而且这种假通过比直接失败危险得多，因为它会让人以为覆盖到了。要修的话得用 `Object.getOwnPropertyDescriptor` 拿到原生 setter 调用，再手动 `dispatchEvent(new Event('input', {bubbles:true}))`。但既然要写这么多，不如直接用 `send_keys`。

**Q：拖拽怎么实现，为什么 `drag_and_drop` 经常不生效？**
A：`drag_and_drop` 内部是 click_and_hold + move + release 这套合成鼠标事件，对基于 mousedown/mousemove 实现的拖拽（比如 jQuery UI）有效。但 HTML5 原生拖拽走的是浏览器底层的拖放子系统，靠 dragstart/dragover/drop 这套 DragEvent 驱动，合成的鼠标事件触发不了，所以没报错也没效果。我的处理顺序是：先试分步写法，click_and_hold 之后加几个中间移动点和 pause，让前端的 dragover 有机会响应，这能解决大部分排序和看板场景；还不行就用 JS 构造 DataTransfer 派发 DragEvent，但这是降级方案——如果拖拽本身就是被测功能，用 JS 模拟等于没测。这种场景我更倾向用 Playwright，它的 `drag_and_drop` 对 HTML5 拖拽支持好得多。

**Q：滑块验证码怎么处理？**
A：技术上可以用 ActionChains 模拟变速的人手轨迹，配合识别缺口位置，但我不推荐把精力花在这里。验证码的设计目标就是阻止自动化，用自动化去破解它是在和产品的安全设计对抗，风控一升级就失效，维护成本无底洞。正确做法是推动测试环境提供白名单、万能验证码或者关闭验证码的开关，这是测试环境治理问题不是技术问题。如果验证码功能本身要测，那就单独做少量专项用例手工或半自动验证。

## 参考

- [Selenium · Action chains](https://www.selenium.dev/documentation/webdriver/actions_api/)
- [Selenium · Executing JavaScript](https://www.selenium.dev/documentation/webdriver/interactions/)
- [MDN · HTML Drag and Drop API](https://developer.mozilla.org/zh-CN/docs/Web/API/HTML_Drag_and_Drop_API)
- 相关笔记：[[Selenium 表单交互：输入、点击与下拉框]]
- 相关笔记：[[Selenium 文件上传与下载]]
- 相关笔记：[[Selenium 常见异常排查]]
- 相关笔记：[[07-Web自动化测试]]
