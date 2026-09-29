---
created: 2026-07-31
tags: [App自动化测试/设备治理]
---

# Appium 应用启停、重置与设备状态恢复

> 用例之间设备状态不干净，是 App 自动化「今天绿明天红」的头号原因。启动、停止、清数据、冷启，这几件事做对了，稳定性直接上一个台阶。

## 概念

### 启停的本质是 activity / bundle 操作

- **启动 App**：Android 走 `am start -n 包名/Activity`；iOS 走 `xcrun devicectl` / WDA 的 `launchApp`。Appium 封装成 `driver.launch_app()` 和 `driver.activate_app()`。
- **停止/杀死**：Android `am force-stop 包名`；iOS 没有「强杀」概念，只能 `terminate_app`。
- **重置**：`adb shell pm clear 包名` 清掉 `/data/data/包名` 的用户数据，等价于「设置里清除存储」。

### launch_app vs activate_app 的区别

- `launch_app()`：根据 caps 里的 `appActivity` **冷启动**，会重新走 Application 初始化，等同于杀掉后重新点图标。
- `activate_app()`：**把后台 App 切回前台**，不重新初始化进程，快得多，适合用例间只是切回 App 而非重启。

```text
冷启动 launch_app：杀进程 → 新建进程 → Application.onCreate → 闪屏 → 首页   （约 1~3s）
热启动 activate_app：进程在后台 → 提到前台 → onResume                       （约 200ms）
```

## 用法

### 一、用例开始：清数据 + 冷启保证干净

```python
@pytest.fixture
def clean_app(driver):
    # 清数据，保证从零开始
    driver.execute_script("mobile: clearApp", {"appId": "com.xxx.app"})
    driver.launch_app()                 # 冷启
    yield driver
    driver.terminate_app("com.xxx.app")
```

清数据用 `mobile: clearApp`（UiAutomator2 扩展命令）比 `am force-stop` 更彻底，会清 `/data/data`。

### 二、用例之间：热启提速

```python
# 多用例共享同一 session，之间只需切回前台
def test_step_2(driver):
    driver.activate_app("com.xxx.app")     # 不去初始化，秒级切回
    # ...断言
```

### 三、强制停止（模拟崩溃后重启）

```python
driver.terminate_app("com.xxx.app")        # 等同 am force-stop
driver.activate_app("com.xxx.app")         # 重新拉起
```

### 四、capabilities 控制重置策略

```yaml
# 不重装、不清数据（保留登录态，跑得快）
appium:noReset: true
# 每次 session 结束清数据（CI 干净，但慢）
appium:fullReset: true
```

- `noReset: true`：不卸载、不清数据，适合调试时保留状态。
- `fullReset: true`：每次结束卸载重装，最干净但最慢。CI 多用 `noReset` 配用例内 `clearApp`。

### 五、读取 App 是否在前台 / 运行状态

```python
# 判断当前运行 App
current = driver.current_activity           # Android：当前 Activity
# iOS 判断是否在前台
app_state = driver.query_app_state("com.xxx.app")
# 返回 0=未装 1=后台/挂起 2=后台可恢复 3=前台 4=运行中不可交互
```

## 踩坑

1. **`launch_app` 和 `activate_app` 混用导致用例相互污染**：前一个用例留在登录页，下一个用例直接 `activate_app` 以为到首页，实际还在登录页，断言全错。明确「需要干净态用 launch，仅切回用 activate」。
2. **`fullReset` 在 CI 拖慢到不可接受**：每次卸载重装 + 重跑引导页，单用例多花 10~30 秒。优先 `noReset` + 用例内 `clearApp` 局部重置。
3. **`clearApp` 后没重新授权权限**：清数据把 runtime permission 也清了，再次启动又弹权限框（见 [[Appium 系统权限弹窗处理]]）。清完记得重新 `pm grant` 或依赖 `autoGrantPermissions`。
4. **`terminate_app` 在 iOS 上不等于强杀**：iOS 的 `terminate` 是正常退出，不会像 Android `force-stop` 那样清掉后台状态，下次 `activate` 可能直接恢复到上次页面。要真冷启得用 `launch_app`。
5. **并行时多个用例抢同一台设备清数据**：device farm 里 device 是独占的还好，自己写多进程并发时，清数据操作没加锁会互相清掉对方的 App。设备必须用例级独占。
6. **冷启后闪屏/引导页没等就操作**：`launch_app` 后首页要等广告 3 秒，直接 `find_ELEMENT` 报超时。冷启后统一加「等首页标识元素」的等待。
7. **`current_activity` 取到的是壳 Activity**：部分 App 用 `SplashActivity` 做壳，实际内容在 `MainActivity`，断言 Activity 名要和开发对齐真实业务页。
8. **`query_app_state` 在 Android 上返回语义不同**：Android 的 `query_app_state` 也有，但枚举和 iOS 一致，混用没问题；只是 `terminate` 行为两端不同，别假设对称。
9. **清数据后推送 token 失效**：`clearApp` 清了推送注册信息，依赖推送的用例（如消息红点）要先重新走注册流程，否则永远收不到。
10. **`noReset` 累积的脏数据让后期用例变慢**：长期不清，缓存/数据库膨胀，第 200 个用例比第 1 个慢数倍。定期在测试套件层面做一次 `fullReset`（如每 N 个用例或每轮结束）。

## 面试怎么答

**30 秒骨架**：App 自动化的设备状态治理核心是「启停与重置」。冷启动用 `launch_app()`（重走 Application 初始化），热启动用 `activate_app()`（仅切前台，快）。用例级干净态靠 `mobile: clearApp` 清 `/data/data` 再 `launch_app`；全局策略用 caps 的 `noReset`（保留态、快）和 `fullReset`（每次重装、慢但干净）。状态恢复的关键是每个用例开始保证确定起点，结束清掉副作用。

**追问**：`noReset` 和 `fullReset` 怎么选？——CI 跑全套用 `noReset` + 用例内局部 `clearApp` 平衡干净与速度；单设备调试用 `noReset` 保登录态；只有环境脏到诡异才用 `fullReset` 兜底。

## 参考

- [Appium mobile: clearApp 命令](https://appium.io/docs/en/latest/commands/device/app/clear-app/)
- 相关笔记：[[Appium 系统权限弹窗处理]]、[[App UI 自动化稳定性治理]]、[[Appium Desired Capabilities 详解]]
