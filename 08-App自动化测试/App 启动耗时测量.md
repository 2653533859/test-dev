---
created: 2026-07-31
tags: [App自动化测试/专项测试]
---

# App 启动耗时测量

> 启动速度是用户对 App 的第一印象。冷启多 1 秒，留存就掉一截。怎么测、指标从哪来、怎么在自动化里稳定采集，是专项测试的基本功。

## 概念

### 冷启 / 温启 / 热启

| 类型 | 触发 | 耗时构成 |
|---|---|---|
| 冷启动 Cold | 进程不存在 → 启动 | Application 初始化 + 闪屏 + 首页首帧，最慢 |
| 温启动 Warm | 进程在后台被回收 → 重建 | 比冷启少一部分，但 Activity 重建 |
| 热启动 Hot | 进程/Activity 都在后台 | 仅 onResume，最快 |

自动化通常测**冷启动**，因为最稳定、最贴近用户首次打开，且不受「进程残留」干扰。

### 指标从哪来：两个权威来源

1. **`adb shell am start -W`**：系统直接返回 `TotalTime`（从 startActivity 到首屏可交互），是官方标准指标。
2. **`adb shell dumpsys gfxinfo` / `Displayed` 行**：logcat 里 `ActivityManager: Displayed` 打印的 `总时间`，含窗口绘制。

`am start -W` 的 `TotalTime` 比 `WaitTime` 更接近「用户感知的启动完成」（WaitTime 还含系统调度等待）。

## 用法

### 一、am start -W 测冷启（最权威）

```bash
# 先杀进程保证冷启
adb shell am force-stop com.xxx.app
# -W 等待启动完成并打印耗时；-S 先停止再启动
adb shell am start -W -S -n com.xxx.app/.SplashActivity
# 输出含：
#   ThisTime: 指最后一个 Activity 启动耗时
#   TotalTime: 整个启动链总耗时（关注这个）
#   WaitTime: 系统调度等待 + TotalTime
```

```python
def measure_cold_start(pkg, activity, adb):
    adb.shell(f"am force-stop {pkg}")
    time.sleep(1)                       # 等进程彻底死
    out = adb.shell(f"am start -W -S -n {pkg}/{activity}")
    # 解析 TotalTime
    import re
    m = re search(r"TotalTime: (\d+)", out)
    return int(m.group(1)) if m else None
```

### 二、用 Python 类封装多次采样

```python
def measure_cold_start_avg(pkg, activity, adb, n=5):
    samples = []
    for _ in range(n):
        t = measure_cold_start(pkg, activity, adb)
        if t: samples.append(t)
    return sum(samples) / len(samples), max(samples), min(samples)

# 取中位数更抗毛刺
import statistics
median = statistics.median(samples)
```

单次测量受 CPU 调度抖动影响大，必须多次采样取中位数/平均，并记 max 作为劣化预警。

### 三、从 logcat 抓 Displayed 时间

```bash
# 过滤启动完成日志
adb logcat -c
adb shell am start -n com.xxx.app/.SplashActivity
adb logcat | grep "Displayed com.xxx.app"
# 输出：ActivityManager: Displayed com.xxx.app/.MainActivity: +1s234ms
```

### 四、首屏可交互时间（更贴近用户）

`TotalTime` 只到「窗口可绘制」，未必到「用户能点」。要测真正首屏可交互，需在首页关键元素出现时打点：

```python
start = time.time()
driver.launch_app()
WebDriverWait(driver, 15).until(
    EC.element_to_be_clickable((AppiumBy.ID, "com.xxx:id/btn_home"))
)
first_interactive = time.time() - start   # Appium 视角的首屏可交互耗时
```

## 踩坑

1. **`am start -W` 但进程没死，测成温启**：忘了先 `force-stop`，测出来的是热/温启时间，虚低。冷启必须每次先强杀 + 等进程彻底退出。
2. **只测 1 次就下结论**：CPU 调度、IO 竞争让单次波动可达 30%，一次 800ms 一次 1400ms。必须 5~10 次取中位数。
3. **`TotalTime` 和「用户感知」不一致**：`TotalTime` 到首帧绘制，若首帧后还有 1 秒数据加载才出内容，用户体感更慢。关键路径要补「首屏可交互」打点（见用法四）。
4. **把 `WaitTime` 当成启动耗时**：WaitTime = TotalTime + 系统调度等待，包含不属于 App 的耗时，对比不同机型会失真。横向对比只用 `TotalTime`。
5. **`-S` 在某些 ROM 上不生效**：部分国产 ROM 的 `am start -S` 强停逻辑有差异，仍残留。保险先显式 `am force-stop` 再 `start`。
6. **首次启动含引导页/权限申请，后续启动不含**：第一次冷启有引导页、权限框，时间天然长；做「启动耗时回归」要固定是否跳过引导，否则基线漂移。建议配 `noReset` 跳过引导后再测。
7. **后台保活 App 被系统杀后温启被当成冷启**：系统内存紧张回收了进程，你以为热启实际是温启，数据不可比。测试机要锁内存、关省电策略。
8. **多进程 App 的 `TotalTime` 只算主进程**：有的 App 把初始化放子进程，主进程 `TotalTime` 小但用户还要等子进程。要结合 `Displayed` 与首屏可交互双指标。
9. **采样间隔太短，CPU 没降频恢复**：连续启动 5 次，后几次因发热降频反而更慢。采样间隔加 2~3 秒，或测一轮重启设备一次。
10. **不同机型绝对数值不可比，只比相对劣化**：启动耗时高度依赖硬件，跨机型比绝对值无意义，正确做法是「同机型盯版本间相对变化」。

## 面试怎么答

**30 秒骨架**：App 启动分冷/温/热三种，自动化主要测冷启，最贴近用户首次打开且不受进程残留干扰。权威指标用 `adb shell am start -W`，关注 `TotalTime`（从 startActivity 到首屏可绘制），配合 `logcat` 的 `Displayed` 行。测法上必须先 `force-stop` 保证冷启，再多次采样取中位数抗抖动，还要补一个「首页关键元素可交互」的打点来贴近真实体感。

**追问**：为什么不能只信 TotalTime？——它只到首帧绘制，若首帧后还有数据加载，用户体感更慢，所以要结合首屏可交互时间；另外单次测量波动大，必须多次采样取中位。

## 参考

- [Android 启动时间官方测量](https://developer.android.com/topic/performance/vitals/launch-time)
- 相关笔记：[[adb 常用命令详解]]、[[App 性能指标采集：FPS、内存、CPU、流量与耗电]]、[[Appium 应用启停、重置与设备状态恢复]]
