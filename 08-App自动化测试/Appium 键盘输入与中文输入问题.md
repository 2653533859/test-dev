---
created: 2026-07-31
tags: [App自动化测试/输入]
---

# Appium 键盘输入与中文输入问题

> 英文输入人人会，中文输入才是 Appium 的经典雷区。根因是虚拟键盘走的是「输入法」而不是「字符注入」，一旦你的 App 装了第三方输入法，自动化就傻了。

## 概念

### 输入有两条路

`element.send_keys("abc")` 底层分两种实现：

1. **ADB 键盘注入（UIAutomator2 默认优化路径）**：driver 直接通过无障碍/adb 把字符串塞进 EditText，**不经过系统输入法**，所以快、且不被输入法切换影响。
2. **真实键盘事件**：当无法走注入（比如某些自绘输入框）时，会唤起系统软键盘，逐字符发送 keyevent，这时候就受当前输入法影响。

中文最坑的点在于：系统输入法（搜狗/百度）收到拼音后还要「候选词上屏」这一步，Appium 发的是字符序列而不是拼音，于是要么输入法吃掉、要么乱码。

### unicodeKeyboard 与 resetKeyboard

这是解决中文输入的标准开关：

- `unicodeKeyboard: true`：让 Appium 在测试期间**临时把系统输入法切换成 Appium 自带的 Unicode 输入法**，它支持直接上屏任意 Unicode 字符（含中文）。
- `resetKeyboard: true`：测试结束后把输入法切回原来的，避免污染后续手工操作。

```yaml
# caps 里这样配
appium:unicodeKeyboard: true
appium:resetKeyboard: true
```

## 用法

### 一、普通输入（最稳的写法）

```python
name_input = driver.find_ELEMENT(AppiumBy.ID, "com.xxx:id/et_name")
name_input.send_keys("张三")
name_input.send_keys("hello@163.com")
```

只要开了 `unicodeKeyboard`，中文直接上屏，不用管输入法候选词。

### 二、清再输入

```python
field = driver.find_ELEMENT(AppiumBy.ID, "com.xxx:id/et_search")
field.clear()                 # Appium 用 Ctrl+A + Delete 实现
field.send_keys("新关键词")
```

注意 `clear()` 对部分自绘 EditText（React Native / Flutter 的 TextInput）可能清不干净，需要先 `field.set_value("")` 再 `send_keys`。

### 三、隐藏键盘

```python
driver.hide_keyboard()        # 收起软键盘
# 更安全：先判断再收
if driver.is_keyboard_shown():
    driver.hide_keyboard()
```

### 四、密码框 / 需要特定键盘布局

```python
# 强制切到数字键盘（靠 caps 不行，要 Element 属性）
pwd = driver.find_ELEMENT(AppiumBy.ID, "com.xxx:id/et_pwd")
pwd.click()                    # 触发 EditText 的 inputType，系统自动弹对应键盘
pwd.send_keys("123456")
```

### 五、iOS 的特殊处理

iOS 的 WDA 用 `UITextField` 的 `typeText`，中文同样靠 `unicodeKeyboard` 解决。iOS 没有 `hide_keyboard` 的「物理返回」，常用 `driver.hide_keyboard()` 触发 `Done` 或点击空白区域。

## 踩坑

1. **没开 `unicodeKeyboard` 直接 `send_keys("中文")`**：第三方输入法把字符当拼音或丢弃，输入框得到空值或乱码。这是最高频问题。
2. **`resetKeyboard` 没开，测完手机输入法被永久换成 Appium 输入法**：同事拿你手机手测发现打不了字，一脸懵。CI 机器无所谓，真机调试务必开 `resetKeyboard`。
3. **`send_keys` 带特殊字符被吞**：有些字符（如 `\n`、`'`）需要转义，换行用 `send_keys("a\nb")` 在 Android 上常变成直接提交表单，要换行得先确认 EditText 支持 multi-line。
4. **`clear()` 在 Flutter/React Native 失效**：自绘文本组件不响应标准清除指令，残留旧值。改用 `element.set_value("")` 或直接 `send_keys` 覆盖。
5. **软键盘遮挡输入框导致元素不可点**：弹起后控件被顶到屏幕外，`click` 报 `ElementNotInteractable`。解决：输入后在 caps 设 `appium:disableKeyboard: true` 或主动 `hide_keyboard()` 再操作下方按钮。
6. **输入法切换有延迟**：`unicodeKeyboard` 切换输入法要 1~2 秒，切换后立刻 `send_keys` 可能丢首字符。可在 fixture 里 `driver.activate_ime()` 之后 `time.sleep(1)` 或用 `wait` 等可交互。
7. **密码框被系统「安全键盘」接管**：银行类 App 用自己的安全键盘，不走系统输入法，Appium 字符注入进不去。`send_keys` 无效，只能逐键用坐标点击（极脆弱），这种场景建议把密码输入从 UI 自动化里摘掉，用接口或 adb 注入绕过。
8. **iOS 的 `typeText` 中文间隔太快丢字**：WDA 对长中文串逐字输入，偶发丢字。拆成短串或加 `pause` 缓解。
9. **混合 WebView 里的 input 用 `send_keys` 无效**：H5 输入框要先切到 WebView 上下文（见 [[Native 与 WebView 上下文切换]]），且最好用 `execute_script` 设置 value 再派发 input 事件。
10. **`send_keys` 触发输入法联想下拉遮挡后续元素**：输入后下拉候选词盖住确认按钮，要在断言前 `hide_keyboard()`。

## 面试怎么答

**30 秒骨架**：Appium 输入中文的核心是输入法。默认 `send_keys` 走的是 ADB/无障碍字符注入，但一旦落到系统软键盘，第三方输入法的候选词机制会让中文乱码。标准解法是 caps 里开 `unicodeKeyboard: true`，让 Appium 临时接管成 Unicode 输入法直接上屏；再开 `resetKeyboard: true` 测完恢复，避免污染设备。

**追问**：为什么不直接用原生输入法？——原生输入法需要「拼音→候选→上屏」多步交互，Appium 发的是成品字符，喂不进去。再追问：自绘输入框清不掉怎么办？——`clear()` 对 Flutter/RN 的 TextInput 常常失效，改用 `set_value("")` 或重新 `send_keys` 覆盖。

## 参考

- [Appium Keyboard 文档](https://appium.io/docs/en/latest/guides/encoding/)
- 相关笔记：[[Appium Desired Capabilities 详解]]、[[Native 与 WebView 上下文切换]]、[[Appium 控件定位策略]]
