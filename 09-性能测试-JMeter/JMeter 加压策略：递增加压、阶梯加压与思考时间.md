---
created: 2026-07-31
tags: [性能测试/压测模型]
---

# JMeter 加压策略：递增加压、阶梯加压与思考时间

![[assets/ramp-up-curve.svg]]
*图示：三种加压曲线对比——一次性拉满会制造假雪崩，递增加压平滑但无稳态平台期，阶梯加压每级 hold 住才能读出稳态 TPS 并精确定位容量拐点。*

> 同样是压 200 并发，**怎么加上去**决定了你测到的是真实性能还是加压过程本身造成的假象。

## 概念

### 为什么加压方式会影响结果

系统不是「无状态的计算器」，它有**冷启动过程**：

1. **JIT 编译**：JVM 前几千次调用走解释执行，之后才编译成机器码，性能差 10 倍以上。
2. **连接池预热**：HikariCP、Druid 默认懒创建连接，第一批请求要等建连（含 TCP 握手 + 数据库认证，几十毫秒）。
3. **缓存预热**：Redis、本地缓存都是空的，前几百个请求全部穿透到数据库。
4. **类加载**：首次访问某个代码路径要加载类、初始化静态块。
5. **文件系统缓存**：数据库的 buffer pool 是冷的，全走磁盘 IO。

**如果 0 秒瞬间打进 200 个并发，这 200 个请求全部撞在最脆弱的冷启动窗口上**，结果是：响应时间极高、大量超时、连接池被打爆。你测到的是「系统冷启动时被突袭会怎样」，而不是「系统的稳态性能是多少」。

### JMeter 的 Ramp-Up 机制

普通线程组有两个关键参数：

- `num_threads`：线程总数
- `ramp_time`：把这些线程**全部启动完**需要多少秒

启动节奏是**线性均匀**的：

```text
每个线程的启动间隔 = ramp_time / num_threads
```

例：200 线程、ramp-up 200 秒 → 每秒启动 1 个线程，第 200 秒时全部就位。

例：200 线程、ramp-up 20 秒 → 每 0.1 秒启动 1 个，第 20 秒全部就位。

例：200 线程、ramp-up 0 秒 → **全部瞬间启动**。

**ramp-up 该设多少的经验法则**：

```text
ramp_time ≈ num_threads / 期望的每秒新增用户数
```

一般让每秒新增 1～5 个用户比较接近真实（真实系统的用户不会同时涌入）。200 线程通常设 40～200 秒。

### ramp-up 的一个隐蔽陷阱

**ramp-up 期间已经启动的线程如果跑完了循环次数，会直接退出。**

假设 200 线程、ramp-up 200 秒、循环次数 10 次，单次循环耗时 1 秒：

- 第 1 个线程在第 0 秒启动，跑 10 秒后（第 10 秒）就退出了
- 第 200 个线程在第 200 秒才启动

**结果是：从头到尾根本没有 200 个线程同时在跑**，最大并发可能只有 10 几个。这是新手最常见的「为什么我压 200 线程但服务端看不到压力」的原因。

解法有两个：

1. **用调度器（Scheduler）按时长运行**，而不是按循环次数：勾选 `scheduler`，设置 `duration`，循环次数设为「永远（-1）」。
2. **让循环次数足够大**，保证第一个线程在最后一个线程启动前不会退出。

推荐永远用第一种。

### 三种加压策略

**一次性加压（ramp-up = 0）**

- 所有线程瞬间启动
- **用途**：只用于「突发流量」专项测试（比如秒杀开始瞬间、消息推送后的洪峰）
- **不适合**：常规负载/容量测试，会制造假雪崩

**递增加压（线性 ramp-up）**

- 线程数随时间线性上升到目标值，然后保持
- **用途**：常规负载测试。曲线平滑，能观察 TPS 随并发增长的趋势
- **缺点**：没有稳态平台期，每个并发水位只停留一瞬间，读不出该水位的准确 TPS

**阶梯加压（Stepping / Concurrency Thread Group）**

- 分级增加：50 → hold 5min → 100 → hold 5min → 150 → hold 5min → 200
- **用途**：容量测试的标准做法。每一级都有足够长的稳态期，可以取该级后半段的均值作为该并发下的准确 TPS
- **能精确定位拐点**：画出「并发数 - 稳态 TPS」表格，TPS 不再增长的那一级就是拐点

### 思考时间（Think Time）

真实用户收到响应后不会立刻发下一个请求。JMeter 用**定时器**模拟：

| 定时器 | 行为 | 适用 |
|--------|------|------|
| 固定定时器 Constant Timer | 每次都等固定毫秒 | 简单场景 |
| 均匀随机定时器 Uniform Random Timer | 固定值 + [0, 随机上限) 均匀分布 | 常用 |
| 高斯随机定时器 Gaussian Random Timer | 固定值 + 正态分布偏差 | **最接近真实用户** |
| 常数吞吐量定时器 Constant Throughput Timer | 按目标 TPS 反推等待时间 | 定速压测 |

**为什么推荐高斯随机而不是固定定时器**：固定 3 秒会让所有线程形成**人为同步**——它们在同一批次发请求、同一批次等待，制造出周期性的 TPS 尖刺和低谷，服务端看到的是脉冲流量而不是平滑流量。高斯分布让每个用户的等待时间在均值附近随机波动，流量自然打散。

## 用法

### 参数化的线程组配置（推荐模板）

```xml
<ThreadGroup guiclass="ThreadGroupGui" testname="订单场景" enabled="true">
  <!-- 线程数、ramp-up、持续时间全部走属性，命令行可覆盖 -->
  <stringProp name="ThreadGroup.num_threads">${__P(threads,50)}</stringProp>
  <stringProp name="ThreadGroup.ramp_time">${__P(rampup,50)}</stringProp>
  <!-- 关键：用调度器按时长跑，不要按循环次数 -->
  <boolProp name="ThreadGroup.scheduler">true</boolProp>
  <stringProp name="ThreadGroup.duration">${__P(duration,600)}</stringProp>
  <stringProp name="ThreadGroup.delay">0</stringProp>
  <elementProp name="ThreadGroup.main_controller" elementType="LoopController">
    <!-- -1 = 永远循环，由 duration 控制何时停 -->
    <stringProp name="LoopController.loops">-1</stringProp>
    <boolProp name="LoopController.continue_forever">true</boolProp>
  </elementProp>
  <!-- 出错后继续，不要让一个失败请求带走整个线程 -->
  <stringProp name="ThreadGroup.on_sample_error">continue</stringProp>
</ThreadGroup>
```

对应的执行命令：

```bash
# 负载测试：100 线程，100 秒加压，跑 30 分钟
jmeter -n -t order.jmx -l load.jtl -e -o report-load/ \
  -Jthreads=100 -Jrampup=100 -Jduration=1800

# 突发流量：200 线程瞬间拉满，跑 5 分钟
jmeter -n -t order.jmx -l burst.jtl -e -o report-burst/ \
  -Jthreads=200 -Jrampup=0 -Jduration=300
```

一份脚本、多种压法，这是必须养成的习惯。

### 阶梯加压：Concurrency Thread Group

原生线程组做不了阶梯加压，需要 `jpgc-casutg` 插件（Custom Thread Groups）。

安装：

```bash
# 1. 下载插件管理器 jar 放到 lib/ext/
#    https://jmeter-plugins.org/get/
# 2. 命令行安装插件
cd apache-jmeter-5.6.3/bin
./PluginsManagerCMD.sh install jpgc-casutg
```

**Concurrency Thread Group** 是目前最推荐的阶梯加压组件（比老的 Stepping Thread Group 更精确，它按「目标并发数」而不是「启动线程数」控制）：

```xml
<com.blazemeter.jmeter.threads.concurrency.ConcurrencyThreadGroup
    guiclass="com.blazemeter.jmeter.threads.concurrency.ConcurrencyThreadGroupGui"
    testname="阶梯加压 50→200">
  <!-- 目标并发总数 -->
  <stringProp name="TargetLevel">200</stringProp>
  <!-- 加压总时长（单位见 Unit） -->
  <stringProp name="RampUp">20</stringProp>
  <!-- 分几级加上去：4 级 → 50/100/150/200 -->
  <stringProp name="Steps">4</stringProp>
  <!-- 到达目标后维持多久 -->
  <stringProp name="Hold">20</stringProp>
  <!-- M = 分钟，S = 秒 -->
  <stringProp name="Unit">M</stringProp>
  <stringProp name="LogFilename"></stringProp>
  <elementProp name="ThreadGroup.main_controller" elementType="LoopController">
    <stringProp name="LoopController.loops">-1</stringProp>
    <boolProp name="LoopController.continue_forever">true</boolProp>
  </elementProp>
</com.blazemeter.jmeter.threads.concurrency.ConcurrencyThreadGroup>
```

上面这份配置的含义：**20 分钟内分 4 级加压到 200 并发（每级 5 分钟，每级增加 50），到顶后再维持 20 分钟。**

### 从阶梯结果里读出拐点

阶梯压测跑完后，按时间段切分 jtl，算出每一级的稳态 TPS。**关键：每一级要丢掉前 1 分钟（加压抖动期），只取后半段。**

```python
"""从 jtl 里按阶梯时间段切分，算每一级的稳态 TPS 和 P95。"""
import csv

JTL = "capacity.jtl"
# 每级的 (并发数, 起始秒, 结束秒)，起始秒已跳过每级前 60s 的抖动期
STEPS = [
    (50, 60, 300),
    (100, 360, 600),
    (150, 660, 900),
    (200, 960, 1200),
]

rows = []
with open(JTL, newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        rows.append((int(r["timeStamp"]), int(r["elapsed"]), r["success"] == "true"))

start_ts = min(x[0] for x in rows)

print(f"{'并发':>6} {'样本':>8} {'TPS':>8} {'P95(ms)':>9} {'错误率':>8}")
for conc, s, e in STEPS:
    seg = [x for x in rows if s <= (x[0] - start_ts) / 1000 < e]
    if not seg:
        continue
    n = len(seg)
    tps = n / (e - s)
    rts = sorted(x[1] for x in seg)
    p95 = rts[min(int(n * 0.95), n - 1)]
    err = sum(not x[2] for x in seg) / n
    print(f"{conc:>6} {n:>8} {tps:>8.1f} {p95:>9} {err:>7.2%}")
```

典型输出：

```text
    并发       样本      TPS   P95(ms)      错误率
    50     22800     95.0       520      0.00%
   100     44100    183.8       560      0.00%
   150     50400    210.0       720      0.00%
   200     50880    212.0      1180      0.31%
```

**怎么读这张表**：

- 50 → 100：TPS 从 95 涨到 184（接近翻倍），P95 几乎不变 → 还在轻压区
- 100 → 150：TPS 只从 184 涨到 210（涨幅 14%），P95 从 560 涨到 720 → **进入拐点区**
- 150 → 200：TPS 基本不动（210 → 212），P95 翻倍到 1180，开始出错 → **饱和区**

**结论：拐点在 150 并发附近，最大稳态 TPS 约 210。** 如果 SLA 是 P95 < 800ms，那么可用容量是 150 并发 / 210 TPS。

### 思考时间的三种配置

**固定定时器**（简单但会造成同步）：

```xml
<ConstantTimer guiclass="ConstantTimerGui" testname="固定等待 3s">
  <stringProp name="ConstantTimer.delay">3000</stringProp>
</ConstantTimer>
```

**均匀随机定时器**（3～5 秒均匀分布）：

```xml
<UniformRandomTimer guiclass="UniformRandomTimerGui" testname="随机等待 3~5s">
  <!-- 固定偏移量 -->
  <stringProp name="ConstantTimer.delay">3000</stringProp>
  <!-- 在 [0, 2000) 内均匀随机后叠加 -->
  <stringProp name="RandomTimer.range">2000.0</stringProp>
</UniformRandomTimer>
```

**高斯随机定时器**（推荐，均值 3s，标准差 0.5s）：

```xml
<GaussianRandomTimer guiclass="GaussianRandomTimerGui" testname="高斯等待 3s±0.5s">
  <stringProp name="ConstantTimer.delay">3000</stringProp>
  <stringProp name="RandomTimer.range">500.0</stringProp>
</GaussianRandomTimer>
```

**放置位置决定作用范围**：

```text
线程组
├── 高斯随机定时器          ← 对下面所有采样器都生效（每个请求前都等）
├── HTTP 请求 - 登录
├── HTTP 请求 - 查询
└── HTTP 请求 - 下单
    └── 固定定时器 500ms   ← 只对「下单」这一个请求生效
```

**同一个采样器如果同时受多个定时器影响，等待时间会累加。** 上例中「下单」前实际等待 = 高斯(3000±500) + 500ms。这是很容易漏掉的坑。

## 踩坑

1. **ramp-up 设 0 做常规压测**。200 线程瞬间涌入，撞上 JIT 未编译、缓存空、连接池未预热，报告里全是超时。团队花两天查「性能问题」，最后发现把 ramp-up 改成 60 秒就一切正常。**这不是系统的问题，是加压方式制造的假象。**

2. **用循环次数控制时长，导致实际并发远低于设定值**。200 线程、ramp-up 200s、循环 10 次，前面的线程早就跑完退出了，最大同时在跑的可能只有 15 个。**永远用 Scheduler + duration，循环设为永远。**

3. **ramp-up 太长，稳态时间不够**。总共只跑 10 分钟，ramp-up 设了 8 分钟，真正的稳态期只有 2 分钟，还要扣掉抖动，有效数据太少。**经验值：ramp-up 时间不超过总时长的 1/3。**

4. **阶梯加压每级 hold 太短**。30 秒一级，读到的是加压瞬间的抖动值。JIT 编译、连接池扩容、缓存填充都需要时间。**每级至少 hold 3～5 分钟，且丢掉前 1 分钟的数据。**

5. **算稳态 TPS 时把加压期的数据也算进去了**。直接用整轮的聚合报告 TPS 做结论，这个值是所有阶梯的平均，既不是 50 并发的 TPS 也不是 200 并发的，毫无意义。**必须按时间段切分 jtl 单独统计。**

6. **多个定时器叠加导致等待时间翻倍**。线程组级挂了一个 3 秒的定时器，某个采样器下面又挂了一个 2 秒的，实际等 5 秒。压出来 TPS 只有预期的一半，查了半天以为服务端慢。**定时器是累加的，不是覆盖的。**

7. **定时器放在采样器后面以为不生效**。JMeter 的定时器是**作用域生效**而非顺序生效——放在最后一个采样器下面，它依然会在该采样器执行前等待。想「请求完再等」的直觉在 JMeter 里不成立。

8. **所有线程用固定 think time，制造出周期性尖刺**。200 个线程整齐划一地等 3 秒再一起发请求，服务端看到的 TPS 是锯齿波：某一瞬间 200 个请求同时到达，然后 3 秒空闲。这会让 P99 极难看，且和真实流量完全不符。**用高斯或均匀随机定时器打散。**

9. **Concurrency Thread Group 的 Steps 理解错**。`Steps=4, TargetLevel=200, RampUp=20分钟` 的含义是「20 分钟内分 4 次加到 200」，每次加 50，每级持续 5 分钟。有人以为 `RampUp` 是「每级持续时间」，结果实际跑了 80 分钟。

10. **stress 场景忘了设 `on_sample_error`**。默认是 `continue`，但如果误设成 `stopthread`，压到出错时线程会一个个退出，并发数悄悄下降，你看到的「TPS 稳定」其实是因为压力在减小。压力测试必须保持 `continue`。

## 面试怎么答

**Q：ramp-up 时间怎么设，设 0 会有什么问题？**

A：ramp-up 是把所有线程启动完所需的时间，JMeter 按 `ramp_time / num_threads` 的间隔线性启动。经验上让每秒新增 1～5 个用户比较接近真实，200 线程一般设 40～200 秒。

设 0 表示所有线程瞬间启动，问题很严重：这批请求会**全部撞在系统的冷启动窗口上**——JVM 的 JIT 还没编译（走解释执行，慢 10 倍以上）、连接池是懒创建的还没建连、Redis 和本地缓存都是空的、数据库 buffer pool 是冷的。结果是响应时间极高、连接池被瞬间打爆、大量超时。

这时候你测到的是「系统被冷启动突袭会怎样」，而不是「系统的稳态处理能力」，两者是完全不同的问题。

唯一合理使用 ramp-up=0 的场景是**突发流量专项测试**，比如秒杀开始的瞬间、App 推送后的洪峰——这时候「冷启动被突袭」正是要测的对象。

还有个隐蔽点值得补充：ramp-up 期间已经启动的线程如果把循环次数跑完就会退出。200 线程 ramp-up 200 秒但循环只设 10 次的话，第一个线程 10 秒就退了，最后一个线程 200 秒才起来，**全程根本没有 200 个线程同时在跑**。所以必须用调度器按时长跑，循环设成永远。

**Q：什么是阶梯加压，为什么容量测试要用它？**

A：阶梯加压是分级递增并发，每一级都稳定压一段时间再往上加，比如 50 → hold 5 分钟 → 100 → hold 5 分钟 → 150 → hold 5 分钟 → 200。

容量测试必须用它，因为容量测试的产出是「系统的最大处理能力」，而要得到这个数字，必须能读出**每个并发水位下的稳态 TPS**。线性递增加压虽然平滑，但每个并发水位只停留一瞬间，读到的都是过渡态数据，没法做结论。

阶梯加压的每一级有足够长的平台期，等 JIT 编译完成、连接池扩容到位、缓存预热完毕，系统进入稳态后再取数据（实践上丢掉每级前 1 分钟，只取后半段）。这样得到一张「并发数 → 稳态 TPS + P95」的表格，**TPS 不再随并发增长的那一级就是拐点**。

实际读数据时要同时看 TPS 和 P95。有时 TPS 还在小幅上涨但 P95 已经超出 SLA 了，这时应该以 SLA 为准——得到的是「可用容量」，比「理论最大吞吐」更有业务意义。

JMeter 原生线程组做不了阶梯，需要装 `jpgc-casutg` 插件用 Concurrency Thread Group，它按目标并发数控制而不是按启动线程数，更精确。

**Q：思考时间怎么设，为什么推荐高斯随机而不是固定值？**

A：思考时间模拟真实用户两次操作之间的间隔，取值应该来自生产埋点统计的真实操作间隔，而不是拍脑袋。

推荐高斯随机定时器而不是固定定时器，原因是**固定值会造成线程的人为同步**。200 个线程如果都等固定 3 秒，它们会形成批次：同一瞬间 200 个请求全部到达，然后 3 秒完全空闲，服务端看到的是锯齿状的脉冲流量。这有两个坏处：一是 P99 会因为瞬时并发尖峰而异常难看，二是这种流量形态和生产完全不符，压出来的瓶颈没有参考价值。

高斯随机定时器让等待时间在均值附近正态分布（比如 3s ± 0.5s），每个用户的节奏被自然打散，服务端收到的是平滑流量，更接近真实。

还要注意两个实现细节：一是**多个定时器会累加不会覆盖**，线程组级挂 3 秒、采样器级又挂 2 秒，实际等 5 秒；二是**定时器按作用域生效而不是按位置顺序**，放在最后一个采样器下面它依然在该采样器之前等待，这一点和直觉相反。

## 参考

- [JMeter Thread Group 文档](https://jmeter.apache.org/usermanual/test_plan.html#thread_group)
- [JMeter Timers 组件参考](https://jmeter.apache.org/usermanual/component_reference.html#timers)
- [jmeter-plugins：Concurrency Thread Group](https://jmeter-plugins.org/wiki/ConcurrencyThreadGroup/)
- 相关笔记：[[JMeter 线程组与阶梯加压]]
- 相关笔记：[[JMeter 定时器与同步定时器集合点]]
- 相关笔记：[[压测模型推算：目标 TPS 与二八原则]]
- 相关笔记：[[性能测试类型：负载、压力、稳定性与容量测试]]
