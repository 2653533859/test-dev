---
created: 2026-07-31
tags: [App自动化测试/混合应用]
---

# WebView H5 调试：chrome-inspect 实战

> Appium Inspector 看不清 WebView 里的 DOM。真正给混合应用做 H5 调试的工具是 Chrome 自带的 `chrome://inspect`——它能让你像调普通网页一样，对着手机里的 H5 打断点。

![[assets/chrome-inspect-debug.svg]]
*图示：chrome://inspect 的 CDP 通信原理（App 进程 → unix domain socket → adb forward → PC Chrome），标准调试流程（先 grep devtools 确认 socket 存在再开 Chrome），DevTools 高价值用法（Console 验证选择器 / Network 判断前后端责任），以及「Appium 切不进 WebView」的分而治之排查思路。*

## 概念

### 它是怎么工作的

Android WebView 内核就是 Chromium。开启调试后，每个 WebView 实例会在设备内创建一个 **unix domain socket**：

```text
@webview_devtools_remote_<pid>
```

PC 上的 Chrome 打开 `chrome://inspect` 时，它通过 adb 扫描这些 socket、建立端口转发，然后用 **Chrome DevTools Protocol（CDP）** 与之通信——和你调试 PC 上的网页走的是完全同一套协议。

**所以 Appium 切 WebView 上下文，和 `chrome://inspect` 用的是同一条通道。** 理解这点后，「Appium 切不进 WebView」这个问题就有了一个绝佳的验证手段：先用 `chrome://inspect` 试，如果它也看不到，那就是 App 或设备的问题，跟 Appium 无关。

### 前提条件

| 条件 | 检查方式 |
|------|---------|
| App 开启了 WebView 调试 | 见下面的 socket 检查 |
| USB 调试已开、设备已授权 | `adb devices` 显示 `device` |
| PC 上 Chrome 能访问调试资源 | 国内网络下需要能访问 Chrome 的资源域名 |

**开启 WebView 调试是开发侧的事**：

```java
// 开发在 Application 或 Activity 里加这段
if (BuildConfig.DEBUG) {
    WebView.setWebContentsDebuggingEnabled(true);
}
```

注意那个 `if (BuildConfig.DEBUG)`——**这就是为什么 release 包调试不了**。要么找开发要 debug 包，要么让他们出一个「开了调试开关的测试包」，这应该写进测试准入要求里。

## 用法

### 一、先用命令行确认 WebView 可调试

在开 Chrome 之前，用 adb 三秒钟判断有没有戏：

```bash
adb shell cat /proc/net/unix | grep devtools
# 5 [ ACC ]  STREAM  LISTENING  123456 @webview_devtools_remote_8123
#                                        └─ 8123 是 App 进程的 PID

adb shell pidof com.demo.app
# 8123     ← 和上面的 PID 对上，说明这个 App 的 WebView 可调试
```

**没有输出 = App 没开调试开关**，不用再折腾 Chrome 了，直接找开发。

### 二、chrome://inspect 的标准流程

```text
1. 手机用 USB 连接 PC，确认 adb devices 正常
2. 手机上打开 App，进入包含 H5 的页面
3. PC Chrome 地址栏输入 chrome://inspect/#devices
4. 勾选 Discover USB devices
5. 设备列表下会列出所有可调试的 WebView，形如：
     WebView in com.demo.app (120.0.6099.230)
       活动页标题
       https://m.demo.com/promotion?id=123
       [inspect]
6. 点 inspect，弹出完整的 DevTools 窗口
```

打开后能做的事，和调 PC 网页**完全一样**：

- Elements：实时 DOM 树，鼠标悬停会在手机上高亮对应元素；
- Console：直接执行 JS，`document.querySelector('.btn')` 立刻验证选择器；
- Network：看 H5 发出的所有请求、响应体、耗时；
- Sources：打断点单步调试；
- Application：看 localStorage、Cookie、SessionStorage。

### 三、写 Appium 定位器时的正确姿势

**在 Console 里先验证选择器，再写进代码**，这是最高效的工作流：

```javascript
// 在 chrome://inspect 的 Console 里
document.querySelectorAll('.btn-submit').length      // 1  ← 唯一，可用
document.querySelectorAll('input[name=phone]').length // 1

// 看清楚元素的完整属性
document.querySelector('.btn-submit').outerHTML
// '<button class="btn-submit" data-testid="claim-submit">立即领取</button>'
```

发现有 `data-testid` 就用它，这是最稳的：

```python
driver.switch_to.context("WEBVIEW_com.demo.app")
driver.find_element(AppiumBy.CSS_SELECTOR, "[data-testid='claim-submit']").click()
```

对比一下工作流的差异：

| 方式 | 反馈周期 |
|------|---------|
| 改脚本 → 跑用例 → 看报错 → 再改 | 每轮 30 秒~2 分钟 |
| Console 里试选择器 → 确认唯一 → 写进代码 | 每轮 2 秒 |

### 四、Network 面板做接口层验证

混合应用一个高价值用法：**在 UI 操作的同时观察 H5 发出的请求**，能快速判断「是前端没渲染，还是后端没返回」。

```text
点击「立即领取」后 Network 里看到：
  POST /api/coupon/claim   → 200，响应 {"code":0,"data":{"couponId":"C123"}}
  但页面没有任何变化
→ 结论：接口成功了，前端渲染有问题，缺陷归前端
```

这个判断能力，能让你提的缺陷单直接指向责任方，而不是含糊的「点了没反应」。

### 五、看不到 DevTools 界面时的离线方案

`chrome://inspect` 的 DevTools 前端资源默认从 Google 的域名加载，国内网络下常常白屏。三种绕法：

```bash
# 方案一：直接用 CDP 的 HTTP 接口，完全不需要 DevTools 界面
adb forward tcp:9222 localabstract:webview_devtools_remote_8123

curl http://127.0.0.1:9222/json/list
# [{
#   "id": "3F2504E0-4F89",
#   "title": "限时活动",
#   "url": "https://m.demo.com/promotion?id=123",
#   "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/3F2504E0-4F89"
# }]

# 方案二：用本地的 DevTools 前端
# 浏览器打开 http://127.0.0.1:9222 会有一个简易的页面列表
```

```python
# 方案三：用 Python 直接读 CDP 的页面列表 —— 可以做成自动化的一部分
import json
import subprocess
import urllib.request


def list_webview_pages(pkg: str, local_port: int = 9222) -> list[dict]:
    pid = subprocess.run(["adb", "shell", "pidof", pkg],
                         capture_output=True, text=True).stdout.strip().split()[0]
    socket_name = f"localabstract:webview_devtools_remote_{pid}"
    subprocess.run(["adb", "forward", f"tcp:{local_port}", socket_name],
                   check=True, timeout=10)
    with urllib.request.urlopen(f"http://127.0.0.1:{local_port}/json/list", timeout=10) as r:
        return json.loads(r.read().decode())


for page in list_webview_pages("com.demo.app"):
    print(page["title"], "|", page["url"])
```

**这个函数在自动化里很实用**：切 WebView 上下文之前先查一下有哪些页面、URL 是什么，就能精确决定切到哪个，而不是盲取 `contexts[-1]`，见 [[Native 与 WebView 上下文切换]]。

### 六、iOS 侧的对应方案

```bash
brew install ios-webkit-debug-proxy
ios_webkit_debug_proxy -c <udid>:27753 -d

# 然后 Safari → 开发 → 设备名 → 页面，或访问 http://localhost:9221
```

设备上要开：设置 → Safari → 高级 → **网页检查器**。Mac 上 Safari 要开：偏好设置 → 高级 → **在菜单栏中显示"开发"菜单**。

## 踩坑

1. **`chrome://inspect` 设备下没有任何 WebView**
   按顺序查：`adb devices` 正常吗 → `adb shell cat /proc/net/unix | grep devtools` 有输出吗 → 没有就是 App 没开调试开关，找开发。**先用命令行判断，别在 Chrome 界面上瞎点。**

2. **点了 inspect 一片空白**
   DevTools 前端资源加载不出来（网络问题）。用上面的 CDP HTTP 接口方案绕过，或配置可用的网络环境。

3. **release 包调试不了**
   `setWebContentsDebuggingEnabled` 通常包在 `BuildConfig.DEBUG` 里。**把「测试包必须开启 WebView 调试」写进准入标准**，这属于可测试性要求，和要求加 `data-testid` 是同性质的事。

4. **inspect 窗口里操作会影响真机**
   DevTools 不是只读的，在 Console 里执行 JS 会真的改变 App 状态。调试生产数据时要小心。

5. **多个 WebView 分不清**
   广告 SDK、客服 SDK 都会创建 WebView，列表里好几项。按 URL 认，别按顺序猜。

6. **inspect 列表不刷新**
   页面跳转后列表可能不更新。点一下 Chrome 的刷新，或者关掉重开 `chrome://inspect`。

7. **国产 ROM 用自研内核**
   部分厂商用 X5（腾讯）等内核，socket 名字不是标准的 `webview_devtools_remote_`。X5 有自己的调试方案（`debugtbs.qq.com`），需要单独处理。

8. **`adb forward` 用完不清理**
   端口一直占着。调试完 `adb forward --remove-all`，尤其是在会跑 Appium 的机器上，可能和 Appium 的转发端口冲突。

9. **DevTools 里能点通、Appium 里点不通**
   多半是元素被原生层遮挡（比如原生的悬浮客服按钮盖在 H5 按钮上）。DevTools 的点击是 JS 层派发的事件，绕过了真实触摸；Appium 是真实坐标点击，会被遮挡。**这种差异本身就是一个值得提的缺陷。**

## 面试怎么答

**Q：H5 页面在 App 里怎么调试？**
A：用 Chrome 的 `chrome://inspect`。原理是 Android WebView 内核就是 Chromium，开启调试后每个 WebView 会在设备里开一个 devtools 的 unix socket，PC 上的 Chrome 通过 adb 找到它并用 Chrome DevTools Protocol 通信，之后就能像调普通网页一样看 DOM、执行 JS、抓网络请求、打断点。前提是开发在代码里调了 `WebView.setWebContentsDebuggingEnabled(true)`，release 包一般关着。我的习惯是先用 `adb shell cat /proc/net/unix | grep devtools` 命令行确认有没有这个 socket，有输出才去开 Chrome，没有就直接找开发，省得在界面上瞎试。

**Q：这个工具对写自动化脚本有什么帮助？**
A：主要两点。第一是验证选择器，在 Console 里 `document.querySelectorAll('.btn-submit').length` 一秒钟就知道选择器唯不唯一，比「改脚本 → 跑一遍 → 看报错」快两个数量级。而且能看到元素的完整属性，如果发现前端已经加了 `data-testid`，直接用它最稳。第二是判断缺陷归属，用 Network 面板看点击后接口有没有发出、返回是什么，如果接口 200 返回正常但页面没变化，那就是前端渲染问题；如果接口压根没发，那是前端交互逻辑问题。提单时能直接说清楚责任方，比「点了没反应」这种描述有用得多。

**Q：`chrome://inspect` 和 Appium 切 WebView 上下文有什么关系？**
A：走的是同一条通道，都是通过 devtools socket 用 CDP 协议和 WebView 通信，Appium 只是在中间多了一层 chromedriver 代理。所以它们是互相验证的关系——如果 Appium 报「contexts 里只有 NATIVE_APP」，我会先用 `chrome://inspect` 试一下，如果 Chrome 也看不到这个 WebView，说明是 App 没开调试开关或者设备用了非标准内核，跟 Appium 无关；如果 Chrome 能看到但 Appium 看不到，那多半是 chromedriver 版本不匹配的问题。这个分而治之的排查思路能省很多时间。

## 参考

- [Chrome DevTools · Remote debugging WebViews](https://developer.chrome.com/docs/devtools/remote-debugging/webviews)
- [Chrome DevTools Protocol](https://chromedevtools.github.io/devtools-protocol/)
- [ios-webkit-debug-proxy](https://github.com/google/ios-webkit-debug-proxy)
- 相关笔记：[[Native 与 WebView 上下文切换]]
- 相关笔记：[[Appium 控件定位策略]]
- 相关笔记：[[08-App自动化测试]]
