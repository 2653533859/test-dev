---
created: 2026-07-31
tags: [Web自动化测试/交互]
---

# Selenium 表单交互：输入、点击与下拉框

> `send_keys` / `click` / `Select` 这三个最基础的 API，恰恰是踩坑最多的地方：清不干净的输入框、点了没反应的按钮、不是 `<select>` 的下拉框。

## 概念

### WebDriver 的「真实用户交互」原则

W3C WebDriver 规范要求 `click` / `send_keys` **模拟真实用户输入**，而不是直接调 JS：

- `click` → 计算元素中心点坐标 → 检查该点是否被遮挡 → 派发完整的 `mousedown` / `mouseup` / `click` 事件序列；
- `send_keys` → 逐个字符派发 `keydown` / `keypress` / `input` / `keyup` 事件。

这带来两个后果：

1. **能触发前端的所有事件监听**（输入联想、实时校验、按键快捷方式），保真度高；
2. **对元素状态要求严格**：不可见、被遮挡、disabled 都会失败——这些失败**是有价值的**，因为真实用户此刻也做不到。

对比 `execute_script("arguments[0].click()")`：它绕过所有检查直接触发 DOM 的 click handler，但**不产生鼠标事件**，依赖 `mousedown` 或 hover 的组件会失效，而且会掩盖真实的可用性问题。所以 JS 点击是**降级手段而非常规手段**，见 [[Selenium JavaScript 执行、滚动与拖拽]]。

### `clear()` 为什么经常清不干净

`clear()` 的规范行为是：如果元素是可编辑的表单控件，把 value 设为空并派发一个 `change` 事件。问题在于**它派发的事件序列和用户手动删除不一样**：

- React 受控组件用 `value={state}` 绑定，`clear()` 改了 DOM 的 value 但没触发 React 的合成事件 → **React 重渲染时又把旧值写回来**；
- 有些组件监听的是 `input` 事件而不是 `change`；
- 有些组件在 blur 时才回填格式化后的值。

**表现**：`clear()` 后 `send_keys("新值")` 变成了「旧值新值」拼接，或者干脆没变。

## 用法

### 输入：三档写法

```python
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

el = driver.find_element(By.ID, "username")

# 1) 常规
el.clear()
el.send_keys("qa01")

# 2) clear 不生效时：全选后覆盖（模拟用户 Ctrl+A 再输入）
el.send_keys(Keys.CONTROL, "a")          # macOS 用 Keys.COMMAND
el.send_keys("qa01")

# 3) 逐字删除（前两种都失败时的兜底，慢但最贴近真实操作）
for _ in range(len(el.get_attribute("value"))):
    el.send_keys(Keys.BACKSPACE)
el.send_keys("qa01")
```

**推荐顺序就是 1 → 2 → 3**，写用例时先用 1，遇到问题再降级。可以把这个逻辑封进 BasePage 的 `fill()` 里统一处理。

### 特殊按键与组合键

```python
from selenium.webdriver.common.keys import Keys

el.send_keys("关键词", Keys.ENTER)        # 输入后回车提交
el.send_keys(Keys.TAB)                    # 切到下一个字段（触发 blur 校验）
el.send_keys(Keys.ESCAPE)                 # 关闭下拉/弹层
el.send_keys(Keys.CONTROL, "c")           # 复制
el.send_keys(Keys.ARROW_DOWN, Keys.ENTER) # 选中联想列表第一项 ← 搜索框常用
```

**`Keys.ENTER` 与点击提交按钮不等价**：前者触发表单的 submit 事件，后者触发按钮的 click。有些页面只绑了其中一个，测的时候要按真实交互路径选。

### 读取输入框的值

```python
el.text                       # ✗ input 元素的 text 永远是空字符串
el.get_attribute("value")     # ✓ 当前值（会随用户输入变化）
el.get_attribute("placeholder")
el.get_property("value")      # 与 get_attribute("value") 在多数情况等价
```

**`input` 的内容不在 `text` 里**——这是新手最常见的困惑之一。`text` 取的是元素的可见文本节点，而 input 的值存在 DOM property 里。

`get_attribute` 与 `get_property` 的区别：前者优先返回 HTML 属性（初始值），后者返回 DOM 对象的当前属性值。对于 `value` 这类会变的，Selenium 的 `get_attribute` 做了特殊处理会返回当前值；但对 `checked`、`disabled` 这类，建议用 `is_selected()` / `is_enabled()`。

### 点击与状态判断

```python
btn = driver.find_element(By.CSS_SELECTOR, "[data-testid='submit']")

btn.is_displayed()      # 可见（考虑 display/visibility/尺寸，但不考虑遮挡）
btn.is_enabled()        # 未 disabled
btn.is_selected()       # 复选框/单选/option 是否选中

btn.click()
```

**点击前的正确等待**是 `EC.element_to_be_clickable`，见 [[Selenium 显式等待]]。

### 复选框与单选框：先判断再操作

```python
cb = driver.find_element(By.ID, "agree")

# ✗ 直接 click 是切换语义，重复执行会反复开关
cb.click()

# ✓ 幂等写法
def set_checkbox(el, checked: bool):
    if el.is_selected() != checked:
        el.click()

set_checkbox(cb, True)
```

**幂等性很重要**：用例重跑、步骤复用时，直接 `click()` 会让状态和预期相反，而且这种错误极难排查（因为单跑没问题，连跑就错）。

自定义样式的复选框常把真正的 `<input type="checkbox">` 藏起来（`opacity:0` 或 `display:none`），点它会抛 `ElementNotInteractableException`。这时要点关联的 `<label>` 或包裹容器：

```python
driver.find_element(By.CSS_SELECTOR, "label[for='agree']").click()
```

### 原生下拉框：Select 类

只有 `<select>` 标签能用 `Select`：

```python
from selenium.webdriver.support.ui import Select

sel = Select(driver.find_element(By.ID, "city"))

sel.select_by_visible_text("上海")      # 按显示文本 ← 最可读，优先用
sel.select_by_value("SH")               # 按 value 属性 ← 最稳定，不受文案改动影响
sel.select_by_index(2)                  # 按索引 ← 最脆弱，选项顺序会变

# 读取
print(sel.first_selected_option.text)
print([o.text for o in sel.options])
print([o.text for o in sel.all_selected_options])   # 多选框

# 多选
sel.deselect_all()
sel.select_by_visible_text("北京")
sel.select_by_visible_text("上海")
sel.deselect_by_value("BJ")
```

`Select` 对非 `<select>` 元素会抛：

```text
UnexpectedTagNameException: Element should have been "select" but was "div"
```

### 自定义下拉框：三步法

Ant Design、ElementUI、Vue-Select 的下拉框都是 `div` 模拟的，`Select` 用不了。通用套路是**点开 → 等选项渲染 → 点选项**：

```python
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

wait = WebDriverWait(driver, 10)

# ① 点开
driver.find_element(By.CSS_SELECTOR, "[data-testid='city-select']").click()

# ② 等下拉面板渲染完成（关键：面板常常是 append 到 body 下的，不在触发器内部）
panel = wait.until(EC.visibility_of_element_located(
    (By.CSS_SELECTOR, ".ant-select-dropdown:not(.ant-select-dropdown-hidden)")
))

# ③ 在面板内选中目标项（局部查找，避免命中页面别处的同名文本）
panel.find_element(By.XPATH, ".//div[@class='ant-select-item-option-content'][text()='上海']").click()

# ④ 校验回填（很多组件动画期间点击会落空，一定要断言）
wait.until(EC.text_to_be_present_in_element(
    (By.CSS_SELECTOR, "[data-testid='city-select'] .ant-select-selection-item"), "上海"
))
```

三个要点：

1. **下拉面板通常渲染在 `body` 末尾**（避免父容器 `overflow:hidden` 裁剪），所以不能从触发器往下找，要用全局定位；
2. **XPath 局部查找记得加 `.`**：`.//div[...]` 而不是 `//div[...]`；
3. **必须校验回填结果**——展开动画期间点击落空是这类组件最常见的 flaky，不校验就会带着错误数据往下走。

支持搜索的下拉框可以走「输入 + 回车」这条更稳的路径：

```python
trigger = driver.find_element(By.CSS_SELECTOR, "[data-testid='city-select']")
trigger.click()
trigger.find_element(By.CSS_SELECTOR, "input").send_keys("上海")
wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".ant-select-item-option-active")))
trigger.find_element(By.CSS_SELECTOR, "input").send_keys(Keys.ENTER)
```

### 表单整体填写：数据驱动

```python
FORM_FIELDS = {
    "username": (By.ID, "username"),
    "email": (By.ID, "email"),
    "phone": (By.NAME, "phone"),
}

def fill_form(page, data: dict):
    for field, value in data.items():
        page.fill(FORM_FIELDS[field], str(value))

fill_form(page, {"username": "qa01", "email": "qa01@test.com", "phone": "13800000000"})
```

配合 pytest 参数化就是一套完整的表单校验用例集。

## 踩坑

1. **`clear()` 后值又回来了**
   React/Vue 受控组件的经典问题。降级用 `Ctrl+A` 覆盖或逐字 BACKSPACE。**不要用 `execute_script("arguments[0].value=''")`**——那样连 `input` 事件都不触发，前端 state 完全不更新，后续提交的还是旧值。

2. **`send_keys` 中文输入失败**
   某些环境下 chromedriver 对非 ASCII 字符处理有问题（尤其旧版）。先升级 driver；仍不行时用 CDP `Input.insertText`：
   ```python
   driver.execute_cdp_cmd("Input.insertText", {"text": "中文内容"})
   ```
   这个方法会正常触发 input 事件。

3. **`el.text` 读 input 值读到空**
   用 `get_attribute("value")`。

4. **复选框直接 `click()` 导致状态相反**
   用前面的幂等写法。这个坑在「用例重跑」时才暴露，非常隐蔽。

5. **`Select` 用在自定义下拉上**
   抛 `UnexpectedTagNameException`。先在 DevTools 确认标签名。

6. **`select_by_index` 依赖顺序**
   下拉选项常来自接口，顺序会变。优先 `select_by_value`（value 通常是业务编码，稳定），其次 `select_by_visible_text`。

7. **自定义下拉的选项被 `overflow` 裁剪**
   长列表需要滚动才能看到目标项。先用键盘 `ARROW_DOWN` 逐个下移，或者用搜索输入过滤，或者 `scroll_into_view` 目标项。

8. **下拉展开动画期间点击落空**
   最常见的 flaky。必须等面板 `visibility` 之后再点，并且**点完要校验回填**。

9. **disabled 元素 `send_keys` 静默无效**
   有些 driver 版本对 disabled 输入框 `send_keys` 不报错但也不生效。操作前用 `is_enabled()` 断言，或用 `EC.element_to_be_clickable`。

10. **只读日期控件**
    日期输入框常是 `readonly`，只能点开日历面板选。`send_keys` 直接写日期字符串会失败。要么走日历控件交互，要么（在测试目标不是日期控件本身时）用 JS 赋值 + 手动派发 `input` 事件。

11. **表单填完立刻提交**
    很多前端在 blur 时才做校验/格式化。填完最后一个字段直接点提交，可能带着未校验的值。填完加一个 `Keys.TAB` 或点击空白处触发 blur。

## 面试怎么答

**Q：`clear()` 清不掉输入框的值怎么办？**
A：根因是 React/Vue 这类受控组件用 state 绑定 value，`clear()` 修改 DOM value 时派发的事件序列和用户手动删除不同，框架没感知到变化，重渲染时又把旧值写回来。我的处理顺序是：先试 `clear()`，不行就 `send_keys(Keys.CONTROL, "a")` 全选后直接输入覆盖，再不行就逐字 BACKSPACE。绝对不能用 `execute_script` 直接改 value，那样连 input 事件都不触发，前端 state 完全不更新，最后提交的还是旧数据，而且用例还会「通过」——这是最危险的那种假通过。

**Q：下拉框怎么处理？**
A：先看是不是原生 `<select>`。是的话用 `Select` 类，优先 `select_by_value`，因为 value 一般是业务编码比较稳定，`select_by_index` 最不可靠因为选项顺序会变。如果是组件库用 div 模拟的下拉，`Select` 会抛 UnexpectedTagNameException，得走「点开触发器 → 等下拉面板可见 → 在面板内点选项 → 校验回填」四步。有两个细节：下拉面板通常被渲染到 body 末尾而不是触发器内部，所以要全局定位；展开动画期间点击容易落空，所以最后必须断言回填结果，不能点完就往下走。

**Q：`click()` 和 JS 点击有什么区别，什么时候用 JS 点击？**
A：`click()` 走的是真实用户路径——计算元素中心坐标、检查是否被遮挡、派发完整的 mousedown/mouseup/click 序列，所以能触发所有事件监听，保真度高，但对元素状态要求严格。JS 点击直接调元素的 click 方法，绕过所有检查，也不产生鼠标事件，依赖 mousedown 或 hover 的组件会失效。我把 JS 点击当降级手段：只在「元素被一个纯装饰性遮罩挡住」这类确认过是前端 CSS 问题、且不是本次测试目标的场景用，并且会加注释说明原因。用 JS 点击去绕过 loading 遮罩是错的——那说明页面真的还在加载，真实用户也点不到，掩盖问题等于放弃了自动化的价值。

**Q：复选框操作要注意什么？**
A：要幂等。直接 `click()` 是切换语义，用例重跑或者步骤被复用时状态会反过来，而且单跑正常、连跑出错，非常难排查。正确写法是先 `is_selected()` 判断当前状态，和目标状态不一致才点。另外自定义样式的复选框经常把真正的 input 隐藏掉用 CSS 画一个，直接点 input 会抛 ElementNotInteractableException，要点关联的 label。

## 参考

- [Selenium · Keyboard actions](https://www.selenium.dev/documentation/webdriver/actions_api/keyboard/)
- [Selenium · Select lists](https://www.selenium.dev/documentation/webdriver/support_features/select_lists/)
- [Selenium · Web element interactions](https://www.selenium.dev/documentation/webdriver/elements/interactions/)
- 相关笔记：[[Selenium 显式等待]]
- 相关笔记：[[Selenium JavaScript 执行、滚动与拖拽]]
- 相关笔记：[[Selenium 文件上传与下载]]
- 相关笔记：[[Selenium 常见异常排查]]
- 相关笔记：[[07-Web自动化测试]]
