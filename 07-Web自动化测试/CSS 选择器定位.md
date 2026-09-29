---
created: 2026-07-31
tags: [Web自动化测试/元素定位]
---

# CSS 选择器定位

> UI 自动化里 80% 的定位应该用 CSS 选择器解决。讲清语法边界、和 XPath 的取舍、以及浏览器如何匹配它。

## 概念

### 为什么优先用 CSS

CSS 选择器是**浏览器原生能力**：`document.querySelectorAll` 由渲染引擎的 C++ 代码实现，走的是浏览器内部为样式匹配优化过的索引路径（id 索引、class 索引、tag 索引）。而 XPath 在浏览器里是另一套引擎（`document.evaluate`），Chrome 上对复杂表达式的求值明显更慢。

三个实际理由：

1. **快**：简单选择器上 CSS 通常比等价 XPath 快若干倍，一条用例几十次定位下来差异可感知。
2. **短**：`div.card > .title` 对 `//div[contains(@class,'card')]/*[contains(@class,'title')]`。
3. **前端同事看得懂**：CSS 是前端日常语言，出问题沟通成本低。

**CSS 唯一的硬伤是不能向上/向前找**（没有父选择器、没有前置兄弟选择器，`:has()` 在浏览器里已支持但 Selenium 对老内核不保证）。需要「根据子元素找父元素」「找某元素前面的兄弟」时才切 XPath，见 [[XPath 定位：轴与函数]]。

### 浏览器怎么匹配选择器：从右往左

理解这一点能解释性能差异，也能写出更好的选择器。

对 `div.container ul li.active`，浏览器**不是**先找 `div.container` 再往下走，而是：

1. 先用最右边的 **key selector**（`li.active`）拿候选集——这一步走 class 索引，很快；
2. 对每个候选**向上回溯**校验祖先是否满足 `ul`、`div.container`。

推论：**最右边的选择器越具体，匹配越快**。`.btn-submit` 优于 `div div div button`。写一长串后代选择器不但慢，还极其脆弱——中间任何一层 DOM 结构变化就断。

## 用法

### 语法速查

```python
from selenium.webdriver.common.by import By

driver.find_element(By.CSS_SELECTOR, "#login")            # id
driver.find_element(By.CSS_SELECTOR, ".btn.btn-primary")  # 同时有两个 class（注意中间无空格）
driver.find_element(By.CSS_SELECTOR, "input[name='user']")# 属性精确匹配
driver.find_element(By.CSS_SELECTOR, "form input")        # 后代（任意层级）
driver.find_element(By.CSS_SELECTOR, "form > input")      # 直接子元素
driver.find_element(By.CSS_SELECTOR, "label + input")     # 紧邻的下一个兄弟
driver.find_element(By.CSS_SELECTOR, "label ~ input")     # 后面所有兄弟中的 input
```

### 属性选择器：应对动态 class

前端框架（尤其 CSS Modules、styled-components、Tailwind 的 JIT）会生成 `btn_3f9a2` 这种带哈希后缀的 class，每次构建都变。属性的子串匹配是救命稻草：

```python
"[class^='btn_']"        # ^= 前缀匹配   → btn_3f9a2 ✓
"[class$='_active']"     # $= 后缀匹配   → tab_active ✓
"[class*='submit']"      # *= 包含匹配   → form-submit-btn ✓
"[data-testid='login']"  # 最佳实践：让前端加稳定测试属性
"[href^='/order/']"      # 按链接前缀找一类链接
```

三者优先级：**能用 `data-testid` 就别用 class 匹配**，见 [[元素定位稳定性策略与 data-testid]]。

### 结构伪类

```python
"ul li:first-child"       # 第一个
"ul li:last-child"        # 最后一个
"ul li:nth-child(3)"      # 第 3 个（从 1 开始，不是 0）
"ul li:nth-child(2n)"     # 偶数行
"ul li:nth-child(-n+3)"   # 前 3 个
"tr:nth-of-type(2) td:nth-of-type(3)"   # 第 2 行第 3 列
"input:not([disabled])"   # 排除禁用
"option:checked"          # 已选中的下拉项
```

`:nth-child(n)` 与 `:nth-of-type(n)` 的区别是高频坑：

```html
<div>
  <h3>标题</h3>
  <p>第一段</p>
  <p>第二段</p>
</div>
```

- `p:nth-child(2)` → 「父元素的第 2 个孩子，且它得是 p」→ 匹配「第一段」；
- `p:nth-of-type(2)` → 「父元素下第 2 个 p」→ 匹配「第二段」。

**混排结构下几乎总是应该用 `:nth-of-type`。**

### Selenium 中的实战写法

```python
from selenium.webdriver.common.by import By

# 表格：取第 2 行的"操作"列按钮
row = driver.find_element(By.CSS_SELECTOR, "table#orders tbody tr:nth-of-type(2)")
row.find_element(By.CSS_SELECTOR, "button[data-action='cancel']").click()

# 批量取一列文本（先取父容器再局部查找，减少全文档扫描）
cells = driver.find_elements(By.CSS_SELECTOR, "table#orders tbody tr td:nth-of-type(1)")
order_ids = [c.text for c in cells]

# 组合选择器：一次拿两类元素
errors = driver.find_elements(By.CSS_SELECTOR, ".error-msg, .warning-msg")
```

**局部查找（`element.find_element`）** 是重要技巧：把作用域限制在某个容器内，既快又不会误命中页面别处的同名元素。

### Playwright 中的 CSS 增强

Playwright 在标准 CSS 上加了几个私有伪类，非常实用：

```python
page.locator("button:has-text('提交')")        # 包含文本（大小写不敏感、子串）
page.locator("button:text-is('提交')")         # 文本完全相等
page.locator("div.card:has(button.pay)")       # 包含某个后代（等价 CSS :has）
page.locator("li:visible")                     # 仅可见元素
page.locator("input >> nth=0")                 # 链式与索引
```

`:has()` 让 CSS 具备了「按子元素筛父元素」的能力，直接抢回了 XPath 的一大块地盘：

```python
# 找到「标题是 iPhone 的那张卡片」里的加购按钮
page.locator("div.product-card:has(h3:text-is('iPhone'))").get_by_role("button", name="加入购物车").click()
```

### 在浏览器里先验证再写进代码

不要靠猜。F12 控制台里：

```javascript
$$("table#orders tbody tr:nth-of-type(2) button")   // 返回匹配元素数组
$$("...").length                                     // 必须是 1，是 0 或 >1 都要改
```

`$$` 是 Chrome DevTools 对 `querySelectorAll` 的别名。**写进代码前先在控制台确认命中数为 1**，这一步能省掉后面一半的调试时间。

## 踩坑

1. **`.btn.primary` 和 `.btn .primary` 差一个空格，含义完全不同**
   前者是「同时具有 btn 和 primary 两个 class 的元素」，后者是「btn 元素的后代中 class 为 primary 的元素」。空格是后代组合符。

2. **class 里有空格却整体写进选择器**
   `class="btn primary"` 时写 `[class='btn primary']` 能匹配，但顺序一变（`class="primary btn"`）就断。应该写 `.btn.primary`。

3. **动态 id 直接写死**
   `#input_1690000000123` 这类带时间戳/随机数的 id 是一次性的。改用 `[id^='input_']`、`[name=...]` 或稳定的 `data-testid`。

4. **`:nth-child` 从 1 开始，且计的是「所有兄弟」**
   写 `:nth-child(0)` 永远匹配不到；混排结构下想按同类计数必须用 `:nth-of-type`。

5. **依赖长链后代选择器**
   `body > div > div > div:nth-child(3) > span` 这种是「DOM 结构快照」，前端加一层包裹 div 就全断。原则：**从最近的稳定锚点开始写**（有 id 或 data-testid 的容器），链路不超过 2~3 层。

6. **CSS 没有父选择器**
   「找到含文本『已支付』的那一行的删除按钮」用纯 CSS 做不到（除非用 `:has()`）。Selenium 里这种场景切 XPath，Playwright 里用 `:has()` 或 `filter(has_text=...)`。

7. **CSS 无法按文本内容定位（标准 CSS）**
   `button:contains('提交')` 是 jQuery 扩展，**不是标准 CSS**，Selenium 里会抛 `InvalidSelectorException`。Selenium 用 XPath `//button[text()='提交']`，Playwright 用 `:has-text()` 或 `get_by_text()`。

8. **伪元素定位不到**
   `::before` / `::after` 生成的内容不在 DOM 里，Selenium 拿不到元素。要断言其内容只能 `execute_script` 读 `getComputedStyle(el, '::before').content`。

9. **属性值里有特殊字符没转义**
   `[class='a.b']` 中的点、`#id:with:colon` 中的冒号需要转义（`#id\\:with\\:colon`），或改用属性选择器 `[id='id:with:colon']` 规避。

## 面试怎么答

**Q：CSS 选择器和 XPath 你怎么选？**
A：默认 CSS。CSS 由浏览器渲染引擎原生实现，走的是为样式匹配优化过的索引，性能更好，写法也更短、前端同事看得懂。只有两类场景我会切 XPath：一是需要按文本定位（标准 CSS 做不到，`:contains` 不是标准），二是需要向上找父元素或向前找兄弟（CSS 没有父选择器和前置兄弟组合符）。用 Playwright 的话这两类也能用 `:has-text()`、`:has()`、`get_by_text()` 覆盖，XPath 用得就更少了。

**Q：浏览器是怎么匹配 CSS 选择器的？**
A：从右往左。先用最右边的 key selector 通过 id/class/tag 索引拿到候选集，再对每个候选向上回溯校验祖先条件。所以最右侧的选择器越具体越快，而写一长串后代选择器既慢又脆弱。这也是为什么我们提倡「从最近的稳定锚点开始定位」而不是从 body 一路点下来。

**Q：`:nth-child` 和 `:nth-of-type` 的区别？**
A：`:nth-child(n)` 是「父元素的第 n 个孩子，并且它还得匹配前面的类型」，计数包含所有兄弟；`:nth-of-type(n)` 是「父元素下第 n 个该类型元素」。混排结构里比如 h3 后面跟几个 p，`p:nth-child(2)` 拿到的是第一个 p，很容易踩坑，所以按同类序号取元素时一律用 `:nth-of-type`。

**Q：前端 class 是构建时生成的哈希，怎么定位？**
A：三个层次。最优是推动前端加 `data-testid` 这类专供测试的稳定属性，写进前端规范并纳入 code review；退而求其次用属性子串匹配 `[class^='btn_']`；再不行就用语义属性（`name`、`aria-label`、`role`、`placeholder`）或 Playwright 的语义定位器。绝对不写哈希 class 和带时间戳的 id，那是一次性的。

## 参考

- [MDN · CSS 选择器](https://developer.mozilla.org/zh-CN/docs/Web/CSS/CSS_Selectors)
- [Selenium · Locator strategies](https://www.selenium.dev/documentation/webdriver/elements/locators/)
- [Playwright · Other locators（CSS 扩展伪类）](https://playwright.dev/python/docs/other-locators)
- 相关笔记：[[XPath 定位：轴与函数]]
- 相关笔记：[[元素定位稳定性策略与 data-testid]]
- 相关笔记：[[Playwright 语义定位器]]
- 相关笔记：[[07-Web自动化测试]]
