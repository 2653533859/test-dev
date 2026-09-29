---
created: 2026-07-31
tags: [App自动化测试/专项测试]
---

# App 性能指标采集：FPS、内存、CPU、流量与耗电

![[assets/perf-metrics-pipeline.svg]]
*图示：性能指标采集链路——自动化脚本驱动典型用户操作，同时通过 adb / dumpsys / 系统接口把 FPS、内存、CPU、流量、耗电五类指标收集回来，落盘做趋势对比。*

> 功能对了但卡、烫、费流量，用户照样卸载。性能专项测试就是把「卡顿/内存泄漏/CPU 飙高/偷跑流量/掉电快」量化成可回归的数字。

## 概念

### 五类指标与采集入口

| 指标 | 含义 | 采集命令/接口 |
|---|---|---|
| FPS | 帧率，掉帧即卡顿 | `dumpsys gfxinfo` 的 `Janky frames` / `dumpsys SurfaceFlinger --latency` |
| 内存 | PSS/USS，泄漏看趋势 | `dumpsys meminfo 包名` |
| CPU | 进程占用率，飙高即异常 | `top -d 1` / `dumpsys cpuinfo` |
| 流量 | 上下行字节，偷跑流量 | `cat /proc/net/xt_qtaguid/stats` 或 `dumpsys netstats` |
| 耗电 | 电流/电量，掉电快 | `dumpsys batterystats` / `Battery Historian` |

### 关键认知：性能要「在操作发生时采集」

光看静态内存没意义，要在**典型用户操作（滑动列表、进大图页、退后台）期间**采集，才能暴露问题。所以性能测试 = 「脚本驱动操作」+「同步采指标」两条线并行。

## 用法

### 一、内存采集（泄漏看趋势）

```python
def mem_pss(adb, pkg):
    out = adb.shell(f"dumpsys meminfo {pkg}")
    import re
    m = re search(r"TOTAL\s+(\d+)", out)
    return int(m.group(1)) if m else None    # 单位 KB（PSS）

# 操作前后各采一次，差值异常大即疑似泄漏
before = mem_pss(adb, "com.xxx.app")
do_heavy_operation(driver)                    # 反复进出一个大页面
after = mem_pss(adb, "com.xxx.app")
assert after - before < 20 * 1024             # 单次操作泄漏容忍 <20MB
```

### 二、FPS / 掉帧

```bash
# 操作期间采集 gfxinfo
adb shell dumpsys gfxinfo com.xxx.app
# 关注：
#   Janky frames: 12 (8.33%)   → 掉帧率
#   Number Missed Vsync: ...
```

```python
def jank_rate(adb, pkg):
    out = adb.shell(f"dumpsys gfxinfo {pkg}")
    import re
    total = int(re search(r"Total frames rendered: (\d+)", out).group(1))
    janky = int(re search(r"Janky frames: (\d+)", out).group(1))
    return janky / total if total else None
```

### 三、CPU 占用

```bash
# 采样进程 CPU（%）
adb shell top -d 1 -n 1 | grep com.xxx.app
# 或
adb shell dumpsys cpuinfo | grep com.xxx.app
```

```python
def cpu_usage(adb, pkg):
    out = adb.shell("dumpsys cpuinfo")
    import re
    m = re search(rf"{pkg}\s+(\d+\.?\d*)%", out)
    return float(m.group(1)) if m else None
```

### 四、流量统计

```bash
# 按 uid 查上下行字节（需要 App 的 uid）
adb shell cat /proc/net/xt_qtaguid/stats | grep "uid=10xxx"
# 或更简单：
adb shell dumpsys netstats | grep -A5 com.xxx.app
```

### 五、耗电（Battery Historian 前置）

```bash
# 重置电池统计，跑场景，再导出
adb shell dumpsys batterystats --reset
do_scenario(driver)
adb shell dumpsys batterystats com.xxx.app > batterystats.txt
# 上传 batterystats.txt 到 Battery Historian 看耗电归因
```

### 六、封装成性能采集 fixture

```python
@pytest.fixture
def perf_probe(adb):
    metrics = {}
    metrics['mem_before'] = mem_pss(adb, PKG)
    yield metrics
    metrics['mem_after'] = mem_pss(adb, PKG)
    metrics['jank'] = jank_rate(adb, PKG)
    metrics['cpu'] = cpu_usage(adb, PKG)
    allure.attach(json.dumps(metrics), "perf", allure.attachment_type.JSON)
```

## 踩坑

1. **只采一次内存就下结论**：内存随GC 波动，单次可能刚好在低位。泄漏要看「多次相同操作后的趋势」，操作 N 次内存单调上升才是真泄漏。
2. **`dumpsys meminfo` 的 TOTAL 是 PSS 不是 USS**：PSS 含共享内存按比例分摊，跨进程对比会虚高。看泄漏关注自身私有内存（`Private Dirty`），别只看 TOTAL。
3. **FPS 在静态页测没意义**：页面不動就没有渲染负载，掉帧率为 0。必须在滚动/动画/转场期间采，且连续操作几秒让数据稳定。
4. **`top` 在不同 Android 版本字段顺序不同**：用 `dumpsys cpuinfo` 按包名 grep 更稳，避免解析列错位。
5. **流量统计要按 uid 而非按网卡**：全网卡流量含系统和其他 App，必须用 App 的 `uid` 过滤，否则数据污染。uid 可从 `ps | grep 包名` 拿到。
6. **耗电测试不控制屏幕/亮度**：屏幕是耗电大户，屏幕亮度不同电量差异巨大。耗电对比要固定亮度、关自动旋转、同网络环境。
7. **后台耗电被 alarm/wakelock 偷跑**：退后台后若有 `WakeLock` 没释放或 `AlarmManager` 频繁唤醒，耗电飙升。用 `dumpsys batterystats` 看 `WakeLock` 持有时长。
8. **模拟器性能数据不可信**：AVD 的 CPU/内存是宿主机虚拟化，FPS、耗电完全失真。性能专项必须在真机跑。
9. **采集命令本身消耗资源影响结果**：频繁 `dumpsys`/`top` 会占用 CPU，污染被测指标。采样间隔设 1~2 秒，别每 100ms 采一次。
10. **没设性能基线与劣化阈值**：采了一堆数但没「超过多少算坏」，等于没测。每个指标要定版本间相对劣化红线（如内存涨 15% 报警），接入 CI 趋势看板。

## 面试怎么答

**30 秒骨架**：App 性能专项有五类核心指标——FPS/掉帧（`dumpsys gfxinfo` 的 Janky frames）、内存 PSS（`dumpsys meminfo`）、CPU（`dumpsys cpuinfo`）、流量（按 uid 查 `xt_qtaguid/stats`）、耗电（`dumpsys batterystats` + Battery Historian）。关键是「在操作发生时同步采集」，且内存看多次操作的趋势、FPS 在滚动/动画时采、流量按 uid 过滤、耗电固定屏幕亮度。

**追问**：怎么判断内存泄漏？——不是看单次绝对值，而是重复相同操作（进出一个大页面）多次，每次操作后采 PSS，若私有内存单调上升且不随GC 回落，就是泄漏。

## 参考

- [Android 性能测量官方文档](https://developer.android.com/topic/performance)
- [Battery Historian](https://github.com/google/battery-historian)
- 相关笔记：[[App 启动耗时测量]]、[[adb 常用命令详解]]、[[App 弱网测试：Charles 与网络损伤注入]]
