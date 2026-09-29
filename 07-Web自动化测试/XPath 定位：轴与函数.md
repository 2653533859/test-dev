---
created: 2026-07-31
tags: [Web自动化测试/元素定位]
---

# XPath 定位：轴与函数

> XPath 是 CSS 做不到时的补位工具：按文本找、向上找父级、按相对位置找兄弟。讲清轴（axis）、常用函数与性能边界。

## 概念

### XPath 是什么

XPath 是 W3C 定义的**在 XML/HTML 文档树中寻址节点**的语言。浏览器通过 `document.evaluate()` 提供 XPath 1.0 支持（注意：**只有 1.0**，2.0/3.0 的函数如 `ends-with`、`matches` 用不了）。

它相对 CSS 的核心优势只有两个，但都很致命：

1. **能按文本内容定位**：`//button[text()='提交']`
2. **能沿任意方向遍历**：父、祖先、前面的兄弟、后面的兄弟——CSS 只能往下和往后。

代价：语法啰嗦、可读性差、复杂表达式在 Chrome 上求值比 CSS 慢。所以定位是**「CSS 优先，XPath 补位」**，见 [[CSS 选择器定位]]。

### 绝对路径 vs 相对路径

```text
/html/body/div[2]/div[1]/form/input[1]     ← 绝对路径，从根开始，禁止使用
//form[@id='login']//input[@name='user']   ← 相对路径，// 表示任意位置开始
```

**浏览器 F12「Copy XPath」给出的往往是绝对或半绝对路径，直接粘进代码是新人最常见的错误**——前端加一层包裹 div，整条路径全断。永远手写相对路径，且从最近的稳定锚点起步。

### 节点测试与谓语

```text
//div[@class='card']
 ↑    ↑        ↑
 轴   节点测试  谓语（方括号里的过滤条件）
```

谓语可以叠加，按从左到右顺序求值：

```text
//input[@type='text'][@name='user']      # 两个条件都满足（等价 and）
//ul/li[1]                                # 第 1 个 li（XPath 下标从 1 开始）
//ul/li[last()]                           # 最后一个
//ul/li[position()<=3]                    # 前 3 个
(//button[@class='pay'])[2]               # 注意括号：全文档所有 pay 按钮中的第 2 个
```

`//ul/li[1]` 与 `(//ul/li)[1]` 完全不同：前者是「每个 ul 下的第 1 个 li」（可能返回多个），后者是「全文档所有 ul 的 li 拼起来的第 1 个」（只返回 1 个）。**这是 XPath 最容易出错的地方之一。**

### 轴（axis）：XPath 的杀手锏

轴决定了「从当前节点往哪个方向找」。完整语法是 `轴::节点测试[谓语]`。

| 轴 | 含义 | 例子 |
|----|------|------|
| `child::` | 直接子节点（默认轴，可省略） | `//div/child::span` ≡ `//div/span` |
| `parent::` 或 `..` | 直接父节点 | `//span[text()='已支付']/parent::td` |
| `ancestor::` | 所有祖先 | `//span[text()='已支付']/ancestor::tr` |
| `ancestor-or-self::` | 祖先加自己 | `//input/ancestor-or-self::form` |
| `following-sibling::` | 后面的同级兄弟 | `//label[text()='用户名']/following-sibling::input` |
| `preceding-sibling::` | 前面的同级兄弟 | `//td[text()='总价']/preceding-sibling::td[1]` |
| `following::` | 文档中后面的所有节点 | `//h2[text()='收货信息']/following::input[1]` |
| `preceding::` | 文档中前面的所有节点 | `//button/preceding::label[1]` |
| `descendant::` | 所有后代 | `//form/descendant::input` ≡ `//form//input` |

**`following-sibling` 和 `following` 的区别**：前者只在同一个父节点下找兄弟；后者跨越整棵树，找文档顺序上排在当前节点之后的所有节点。前者更精确、更快，优先用它。

`preceding-sibling::td[1]` 的下标含义要注意：在 `preceding-sibling` 轴上，**`[1]` 表示「离当前节点最近的那一个」**，不是文档顺序上的第一个。反向轴的下标是从当前节点往回数的。

## 用法

### 常用函数

```text
//button[text()='提交']                       # 文本完全等于（注意：不含子元素的文本）
//button[contains(text(),'提')]               # 文本包含
//button[normalize-space(text())='提交']      # 去掉首尾空白与连续空格后比较 ← 最实用
//div[contains(@class,'card')]                # class 包含（class 多值时必须用 contains）
//input[starts-with(@id,'user_')]             # 属性前缀匹配
//a[@href and @title]                         # 同时具有两个属性
//div[not(contains(@class,'disabled'))]       # 取反
//tr[count(td)>3]                             # 子元素计数
//button[string-length(text())>2]             # 文本长度
//*[@id='x' or @name='x']                     # 或
//div[.='总计：100']                           # . 表示当前节点的全部文本（含后代）
```

**`text()` 与 `.` 的区别是高频坑**：

```html
<button>提交 <span>订单</span></button>
```

- `//button[text()='提交 ']` → `text()` 只取直接子文本节点，值是 `"提交 "`（含尾空格），且不含 span 里的「订单」；
- `//button[.='提交 订单']` → `.` 是节点的字符串值，等于所有后代文本拼接。

**含子元素的按钮一律用 `.` 或 `contains(.,'...')`，别用 `text()`。**

### XPath 1.0 没有 `ends-with`

```text
//input[ends-with(@id,'_name')]        ✗ XPath 1.0 不支持，浏览器会报错
//input[substring(@id, string-length(@id)-4)='_name']   ✓ 用 substring 手动实现
```

Chrome 的 `document.evaluate` 只实现 1.0，同样不可用的还有 `matches()`（正则）、`lower-case()`。大小写不敏感匹配的 1.0 写法：

```text
//button[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'submit')]
```

极其难看。遇到这种需求，说明该换 Playwright 的 `get_by_text`（默认大小写不敏感）了。

### 实战：表格行内操作

这是 XPath 最不可替代的场景——**根据一行里的某个特征，操作同一行的另一个元素**。

```python
from selenium.webdriver.common.by import By

# 场景：订单表格里，找到订单号为 SO20260731001 的那一行，点它的"取消"按钮
xpath = (
    "//table[@id='orders']//td[normalize-space(text())='SO20260731001']"
    "/ancestor::tr[1]"                      # 向上找到所在行
    "//button[normalize-space(text())='取消']"  # 再在行内向下找按钮
)
driver.find_element(By.XPATH, xpath).click()
```

拆解思路（**这个「向下定位特征 → 向上到公共祖先 → 再向下到目标」的三段式是 XPath 的核心套路**）：

1. 先定位到能唯一标识这一行的元素（订单号单元格）；
2. `ancestor::tr[1]` 上溯到最近的行容器；
3. 在行容器内向下找要操作的按钮。

### 实战：label 找对应输入框

```python
# <label for="user">用户名</label><input id="user">
"//label[normalize-space(text())='用户名']/following-sibling::input[1]"

# label 包裹 input 的结构：<label>用户名 <input></label>
"//label[contains(.,'用户名')]//input"

# 通过 for 属性关联（更稳）：先取 label 的 for，再按 id 找 —— 这种 Playwright 的 get_by_label 一行搞定
```

### 动态构造 XPath 的安全写法

```python
def row_action(order_no: str, action: str) -> str:
    # 注意：order_no 里如果有单引号会破坏表达式
    if "'" in order_no:
        raise ValueError("订单号不应包含单引号")
    return (
        f"//table[@id='orders']//td[normalize-space()='{order_no}']"
        f"/ancestor::tr[1]//button[normalize-space()='{action}']"
    )

driver.find_element(By.XPATH, row_action("SO20260731001", "取消")).click()
```

`normalize-space()` 不传参时默认作用于当前节点的字符串值，等价 `normalize-space(.)`，比 `normalize-space(text())` 更宽容（能匹配含子元素的节点）。

### Playwright 里的 XPath

Playwright 支持 XPath，但**大部分场景有更好的替代**：

```python
page.locator("xpath=//button[text()='提交']")     # 显式前缀
page.locator("//button[text()='提交']")           # 以 // 开头会自动识别为 XPath

# 更推荐的等价写法
page.get_by_role("button", name="提交")
page.locator("tr", has_text="SO20260731001").get_by_role("button", name="取消")
```

最后那个 `has_text` 过滤 + 链式定位，完全替代了上面那串三段式 XPath，可读性天差地别。

## 踩坑

1. **直接用 DevTools 的 Copy XPath**
   生成的是 `/html/body/div[3]/div/div[2]/...` 这种结构快照，DOM 一变就全断。永远手写相对 XPath。

2. **`//ul/li[1]` 与 `(//ul/li)[1]` 混淆**
   前者对每个 ul 各取第 1 个 li（可能返回多个元素，`find_element` 会取第一个但语义不对），后者才是「全局第 1 个」。要「全局第 N 个」必须加括号。

3. **`text()='提交'` 匹配不到**
   最常见有三个原因：元素含子标签（应改用 `.`）、文本带首尾空白或换行（应用 `normalize-space()`）、文本是 JS 动态填的（应加显式等待，见 [[Selenium 显式等待]]）。

4. **`@class='card'` 在多 class 时失效**
   `class="card card-lg active"` 时 `@class='card'` 不匹配。用 `contains(@class,'card')`——但这又有子串误伤问题（`card-lg` 也含 `card`），严谨写法是 `contains(concat(' ',normalize-space(@class),' '),' card ')`。

5. **用了 XPath 2.0 函数**
   `ends-with`、`matches`、`lower-case` 在浏览器里全部不可用，报 `InvalidSelectorException: Unable to locate an element with the xpath expression`。这个报错信息很有迷惑性——它说的是「表达式非法」而不是「没找到元素」。

6. **XPath 里 `and`/`or` 大小写与位置**
   必须小写，且写在谓语内：`//input[@type='text' and @name='user']`，不能写成 `//input[@type='text'] and [@name='user']`。

7. **`//` 开头在局部查找里的陷阱**
   ```python
   row = driver.find_element(By.XPATH, "//tr[2]")
   row.find_element(By.XPATH, "//button")     # ✗ // 从整个文档根开始，不是从 row 开始！
   row.find_element(By.XPATH, ".//button")    # ✓ 前面加点，表示从当前节点开始
   ```
   这是 XPath 局部查找里排第一的坑，漏了那个点会静默命中页面别处的按钮。

8. **XPath 性能**
   `//*[contains(text(),'x')]` 这种全文档通配扫描在大 DOM（几千节点）上明显变慢，配合隐式等待时会被放大。缩小起点：`//table[@id='orders']//...`。

9. **反向轴的下标方向**
   `preceding-sibling::td[1]` 是「往前数第 1 个」即最靠近的那个，不是文档里的第一个 td。同理 `ancestor::div[1]` 是最近的祖先 div。

## 面试怎么答

**Q：什么时候必须用 XPath？**
A：两类场景 CSS 覆盖不了。第一是按文本定位，标准 CSS 没有文本匹配能力（`:contains` 是 jQuery 扩展，Selenium 会报非法选择器）。第二是逆向遍历——根据子元素找父元素、找前面的兄弟节点，CSS 没有父选择器也没有前置兄弟组合符。最典型的落地场景是表格行内操作：先用订单号单元格定位，`ancestor::tr[1]` 上溯到行，再在行内找操作按钮。除此之外我默认用 CSS。

**Q：绝对路径 XPath 有什么问题？**
A：它是 DOM 结构的快照，前端加一层包裹、调整顺序就全断，而且报错时完全看不出定位意图。DevTools 的 Copy XPath 给的就是这种，不能直接用。正确做法是从最近的稳定锚点（有 id 或 data-testid 的容器）开始写相对路径，链路控制在两三层内。

**Q：`text()` 和 `.` 有什么区别？**
A：`text()` 取的是元素的直接子文本节点，如果元素里还嵌了 span 之类的子标签，子标签里的文字取不到；`.` 是节点的字符串值，等于所有后代文本的拼接。所以 `<button>提交 <span>订单</span></button>` 用 `text()='提交订单'` 匹配不上，得用 `.`。另外文本常带换行和缩进空白，实战里一律套 `normalize-space()`。

**Q：XPath 和 CSS 的性能差异有多大，实际要不要在意？**
A：简单选择器上 CSS 通常快若干倍，因为 CSS 由渲染引擎原生实现并走 class/id 索引，XPath 走的是 `document.evaluate` 这套独立引擎。单次差异是微秒到毫秒级，单看不重要；但一条用例几十次定位、又叠加了隐式等待的轮询，加上 `//*[contains(...)]` 这种全文档扫描，在大 DOM 页面上就会变成秒级差异。所以我的原则不是「XPath 慢所以不用」，而是「用 XPath 时一定要限定起点，别从 `//*` 开始扫」。

## 参考

- [MDN · XPath](https://developer.mozilla.org/zh-CN/docs/Web/XPath)
- [W3C · XML Path Language (XPath) 1.0](https://www.w3.org/TR/1999/REC-xpath-19991116/)
- [Selenium · Locator strategies](https://www.selenium.dev/documentation/webdriver/elements/locators/)
- 相关笔记：[[CSS 选择器定位]]
- 相关笔记：[[元素定位稳定性策略与 data-testid]]
- 相关笔记：[[Playwright 语义定位器]]
- 相关笔记：[[07-Web自动化测试]]
