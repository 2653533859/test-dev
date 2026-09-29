---
created: 2026-07-31
tags: [App自动化测试/手势]
---

# Appium 手势操作：滑动、长按与多点触控

> 手势是移动端自动化绕不开的动作。底层是一套统一的 W3C Actions 规范，但 Appium 2.x 把老接口废了，很多人还停在 `TouchAction`，一升级就全红。

## 概念

### 手势到底走了哪条路

在 Appium 2.x 里，`TouchAction` / `MultiAction` **已被废弃**，官方推荐直接用 Selenium 的 **W3C Actions API**（`ActionChains` + `PointerInput`）。原因很直接：W3C 规范把「输入源」抽象成三类——`pointer`（手指/鼠标）、`key`（键盘）、`wheel`（滚轮），所有手势都拆成「按下→移动→停顿→抬起」的原子指令序列，由 Appium Server 翻译成 `injectInputEvent` 发到设备。

```text
一个 swipe 的指令序列：
  pointer 按下 (x1,y1)
  → 停顿 0~600ms
  → 移动到 (x2,y2)   # 可拆成多段，模拟曲线/惯性
  → 抬起
```

老 `TouchAction` 本质是这套之上的便捷封装，但实现分散在各个 driver 里，维护成本高，所以统一收敛到 W3C。

### 为什么手势比点击容易翻车

点击是单点确定性事件；手势是**带时间轴和坐标变化的过程**，对屏幕分辨率、设备 DPI、动画时长都敏感。同一段 swipe 代码在 1080p 和 2K 屏上划过的距离百分比完全不同，这是后面踩坑的主因。

## 用法

### 一、点按 tap

```python
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.common.actions import interaction

# 长按 1.5 秒后抬起（长按 = 按下 + 长停顿 + 抬起）
device = PointerInput(interaction.POINTER_TOUCH, "finger")
actions = ActionBuilder(driver, mouse=device)
actions.pointer_action.move_to_location(500, 800)
actions.pointer_action.pointer_down()
actions.pointer_action.pause(1500)   # 停顿即长按
actions.pointer_action.pointer_up()
actions.perform()
```

直接 `element.click()` 对绝大多数控件都够用，**只有需要「单击但带坐标偏移」「双击」「长按」时才上 ActionChains**。

### 二、滑动 swipe（按元素比例，别写死坐标）

```python
def swipe_up(el, driver, duration=400):
    """在元素范围内向上滑 60%，避免写死绝对坐标"""
    rect = el.rect                      # {'x','y','width','height'} 屏幕绝对像素
    cx = rect['x'] + rect['width'] / 2
    start_y = rect['y'] + rect['height'] * 0.8
    end_y = rect['y'] + rect['height'] * 0.2
    driver.swipe(cx, start_y, cx, end_y, duration)   # driver.swipe 内部仍走 W3C

# 长列表滑动到底（带惯性补偿）
def scroll_to_bottom(driver, scrollable, max_iter=20):
    last = None
    for _ in range(max_iter):
        before = driver.page_source
        swipe_up(scrollable, driver)
        time.sleep(0.3)                # 等动画
        if before == driver.page_source:   # 页面不再变化
            break
```

`driver.swipe` 是 Appium 提供的便捷方法，签名 `(start_x, start_y, end_x, end_y, duration_ms)`，duration 是**滑动总时长**，设太小（<100ms）系统判定成点击，设太大显得拖沓。

### 三、长按 long_press

```python
# 长按弹出菜单：按下后 pause 超过 500ms 即为长按
actions = ActionBuilder(driver, mouse=PointerInput(interaction.POINTER_TOUCH, "finger"))
actions.pointer_action.move_to_location(x, y)
actions.pointer_action.pointer_down()
actions.pointer_action.pause(800)
actions.pointer_action.pointer_up()
actions.perform()
```

### 四、多点触控：双指捏合缩放

```python
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.common.actions import interaction

def pinch(driver, cx, cy, from_r=300, to_r=100, steps=20):
    """双指向内捏合（缩放）"""
    f1 = PointerInput(interaction.POINTER_TOUCH, "f1")
    f2 = PointerInput(interaction.POINTER_TOUCH, "f2")
    # 手指1：从外向内
    f1.create_pointer_move(duration=0, x=cx - from_r, y=cy)
    f1.create_pointer_down()
    f1.create_pointer_move(duration=300, x=cx - to_r, y=cy)
    f1.create_pointer_up()
    # 手指2：对称
    f2.create_pointer_move(duration=0, x=cx + from_r, y=cy)
    f2.create_pointer_down()
    f2.create_pointer_move(duration=300, x=cx + to_r, y=cy)
    f2.create_pointer_up()
    actions = ActionBuilder(driver)
    actions.add_pointer_input("touch", "f1", f1)
    actions.add_pointer_input("touch", "f2", f2)
    actions.perform()
```

双指必须**同一 `ActionBuilder` 下、各自独立 pointer 输入源**，否则会被解析成两次单指手势。

### 五、按坐标拖拽 drag

拖拽 = 按下→移动到目标→抬起，和 swipe 区别在语义（拖一个对象而非滚动页面），实现上完全一致。注意目标元素若随手指移动（如排序列表），要分段移动并插入 `pause` 给页面渲染时间。

## 踩坑

1. **`TouchAction` 一升级就报错**：Appium 2.x 默认不装 `appium-uiautomator2-driver` 之外的旧接口，导入 `from appium.webdriver.common.touch_action import TouchAction` 可能尚可，但调用已标记 deprecated，新项目直接用 `ActionChains`。
2. **swipe 写死坐标在换机型后失效**：`(500,800)` 在 1080p 是对的，换 2K 屏可能落在无关区域。一律用 `element.rect` 或 `driver.get_window_size()` 取比例。
3. **duration 太小被识别成 tap**：经验值 `250ms~600ms`，小于 100ms 基本判定成点击，反而触发了不该触发的 onClick。
4. **长列表一次 swipe 没到底就断言**：swipe 不带惯性，松手即停。要到底必须循环 + 比对 `page_source` 是否变化。
5. **长按时间不够**：系统长按阈值约 500ms，设 300ms 可能只触发单击。需要稳定触发长按就 pause 800ms 以上。
6. **多点触控两个手指不同步**：用两个独立 `PointerInput` 但放在同一个 `ActionBuilder` 里 `perform`，若分两次 `perform` 会变成串行单指，捏合直接失效。
7. **嵌套滚动容器滑错层**：外层 RecyclerView 和内层横向 ViewPager 都可能消费滑动事件，swipe 起点落在内层会导致只滑了内层。先 `find_element` 定位到正确的可滚动容器再滑。
8. **Uiautomator2 的 swipe 与 WDA 行为不一致**：iOS 的 WDA 对 pointer 序列的容错更低，中途 `pause(0)` 过多会被丢弃，手势分段建议 `pause` 至少 10ms。
9. **拖拽时页面布局抖动**：被拖元素进入新位置触发重排，目标坐标偏移。做法是每移动一段后重新 `find_element` 取最新坐标。
10. **蒙层/半透明遮罩吞手势**：弹窗动画未结束就发 swipe，事件落在遮罩上。手势前加显式等待遮罩消失（`WebDriverWait` + `invisibility_of_element`）。
11. **设备 DPI 导致坐标被缩放**：部分框架传的是逻辑像素，Appium 要的是物理像素，`get_window_size` 返回的就是物理像素，混用会错位。

## 面试怎么答

**30 秒骨架**：Appium 2.x 已经废弃 `TouchAction`，统一走 W3C Actions API，把手指抽象成 `PointerInput`，手势拆成「按下→移动→停顿→抬起」的指令序列。常用手势里 tap/click 直接用 `element.click()` 就够；swipe 用 `driver.swipe()` 但务必基于 `element.rect` 算比例坐标，别写死；长按就是按下后 pause 超过 500ms；双指捏合要用两个独立 pointer 输入源放在同一个 `ActionBuilder` 里执行。

**追问**：为什么不用 TouchAction 了？——老接口实现分散在各 driver，维护成本高且不规范，W3C 规范统一后所有平台一套语义。再追问：如何保证不同分辨率手势一致？——所有坐标都用元素 `rect` 或窗口尺寸算相对比例，且滑动时长设固定区间，避免依赖物理像素。

## 参考

- [Appium Actions 官方文档](https://appium.io/docs/en/latest/guides/actions/)
- 相关笔记：[[Appium 控件定位策略]]、[[Appium session 生命周期与 client 库]]、[[App UI 自动化稳定性治理]]
