---
created: 2026-07-31
tags: [性能测试/JMeter组件]
---

# JMeter 线程组与阶梯加压

> 线程组是 JMeter 里唯一决定「压多大、压多久」的组件。**一个线程 = 一个虚拟用户**，这个模型的边界在哪，直接决定了你能压出多大压力。

## 概念

### 线程模型：一个线程一个虚拟用户

JMeter 的并发模型非常朴素：**每个虚拟用户对应一个真实的 Java 线程**，线程内串行执行采样器，跑完一轮循环再来一轮。

这个设计有两个直接后果：

**后果一：线程之间完全隔离。** 每个线程有自己的变量空间（`vars`）、自己的 Cookie 存储、自己的 CSV 读取位置。这是好事——模拟不同用户天然隔离。

**后果二：线程数受限于压力机资源。** 每个 Java 线程默认占 1MB 栈空间，加上 JMeter 自身的对象开销，**一台 8C16G 的压力机通常只能稳定跑 1000～3000 线程**。想压 1 万并发，要么减小 think time（用更少线程打出同样 TPS），要么上分布式。

这也是 JMeter 和 Gatling / wrk 这类基于异步 IO 的工具的本质差异：后者用少量线程 + 事件循环支撑海量连接，JMeter 是「一个用户一个线程」的重量级模型。

### 四种线程组

| 类型 | 何时执行 | 用途 |
|------|----------|------|
| setUp Thread Group | 所有普通线程组**之前** | 全局准备：登录、清数据、预热 |
| Thread Group（普通） | 主体阶段，多个组默认并行 | 业务压测 |
| tearDown Thread Group | 所有普通线程组**之后** | 清理：删测试数据 |
| Concurrency Thread Group（插件） | 同普通线程组 | 阶梯加压、按并发数控制 |

### 普通线程组的关键参数

```text
线程数（num_threads）        虚拟用户数
Ramp-Up 时间（ramp_time）    多少秒内把线程全部启动完
循环次数（loops）            每个线程跑几轮；-1 = 永远
调度器（scheduler）          启用后用「持续时间」控制何时停
持续时间（duration）         压测跑多久（秒）
启动延迟（delay）            延迟多少秒后才开始启动线程
出错后动作（on_sample_error） continue / start next loop / stop thread / stop test
```

**最重要的配置组合**：

```text
scheduler = true
duration  = 1800
loops     = -1（永远循环）
```

**几乎所有压测都应该用这个组合**，而不是用循环次数控制时长。原因见下一节。

### 为什么不能用循环次数控制时长

假设：200 线程、ramp-up 200 秒、循环 10 次、单轮耗时 1 秒。

```text
t=0s    线程 1 启动
t=1s    线程 2 启动，线程 1 已跑完 1 轮
...
t=10s   线程 11 启动，线程 1 跑完 10 轮 → 退出
t=11s   线程 12 启动，线程 2 退出
...
t=200s  线程 200 启动，此时线程 1~190 早已全部退出
```

**全程同时在跑的线程数最多只有约 11 个**，而不是 200。服务端完全感受不到 200 并发的压力，你会以为「系统性能真好」。

用 `scheduler + duration + loops=-1` 就没这个问题：线程跑完一轮立刻开下一轮，直到 duration 到点才统一停止，**加压完成后能维持真正的 200 并发稳态**。

### 出错后动作（on_sample_error）的选择

| 取值 | 行为 | 什么时候用 |
|------|------|-----------|
| Continue | 继续执行下一个采样器 | **压测默认，几乎总是选这个** |
| Start Next Thread Loop | 跳过本轮剩余请求，从下一轮开始 | 链路强依赖时（登录失败就没必要下单） |
| Stop Thread | 该线程退出 | 调试时用 |
| Stop Test | 优雅停止整个测试 | setUp 前置条件失败时 |
| Stop Test Now | 强制停止 | 极少用 |

**压力测试必须用 Continue 或 Start Next Thread Loop。** 如果误设成 Stop Thread，压到系统开始出错时，线程会一个个退出，**并发数悄悄下降**——你以为「TPS 稳定在 200」，实际是因为压力在减小，数据完全失真。

### 阶梯加压：为什么需要插件

原生线程组只能线性 ramp-up，做不了「50 → hold → 100 → hold → 150」这种阶梯。容量测试需要每级稳态数据，所以必须上插件。

两个可选组件：

| 组件 | 控制维度 | 推荐度 |
|------|----------|--------|
| Stepping Thread Group | 按**启动线程数**分级 | 老组件，官方已标注 deprecated |
| Concurrency Thread Group | 按**目标并发数**分级 | **推荐** |

**两者的本质差异**：Stepping 控制的是「启动了多少线程」，如果线程因为出错退出了，它不会补；Concurrency 控制的是「维持多少并发」，线程死了会自动补新线程上去，**保证压力恒定**。长时间压测和压力测试必须用 Concurrency。

## 用法

### 标准参数化线程组模板

```xml
<ThreadGroup guiclass="ThreadGroupGui" testname="订单压测" enabled="true">
  <stringProp name="ThreadGroup.num_threads">${__P(threads,50)}</stringProp>
  <stringProp name="ThreadGroup.ramp_time">${__P(rampup,50)}</stringProp>
  <boolProp name="ThreadGroup.scheduler">true</boolProp>
  <stringProp name="ThreadGroup.duration">${__P(duration,600)}</stringProp>
  <stringProp name="ThreadGroup.delay">${__P(delay,0)}</stringProp>
  <stringProp name="ThreadGroup.on_sample_error">continue</stringProp>
  <elementProp name="ThreadGroup.main_controller" elementType="LoopController">
    <boolProp name="LoopController.continue_forever">true</boolProp>
    <stringProp name="LoopController.loops">-1</stringProp>
  </elementProp>
</ThreadGroup>
```

命令行灵活切换压法：

```bash
# 冒烟：1 线程跑 1 分钟，确认脚本能跑通
jmeter -n -t order.jmx -l smoke.jtl -Jthreads=1 -Jrampup=1 -Jduration=60

# 基准：单用户 10 分钟，摸清纯净响应时间
jmeter -n -t order.jmx -l base.jtl -Jthreads=1 -Jrampup=1 -Jduration=600

# 负载：100 并发跑 30 分钟
jmeter -n -t order.jmx -l load.jtl -e -o rpt-load/ \
  -Jthreads=100 -Jrampup=100 -Jduration=1800

# 稳定性：60 并发跑 8 小时
nohup jmeter -n -t order.jmx -l stab.jtl \
  -Jthreads=60 -Jrampup=120 -Jduration=28800 > stab.log 2>&1 &
```

### 多线程组按业务配比

生产统计出首页 : 搜索 : 下单 = 5 : 3 : 2，总目标 490 线程：

```xml
<!-- 线程组 1：首页 245 线程 -->
<ThreadGroup testname="TG-首页-50%">
  <stringProp name="ThreadGroup.num_threads">${__P(t_home,245)}</stringProp>
  <stringProp name="ThreadGroup.ramp_time">${__P(rampup,120)}</stringProp>
  <boolProp name="ThreadGroup.scheduler">true</boolProp>
  <stringProp name="ThreadGroup.duration">${__P(duration,1800)}</stringProp>
</ThreadGroup>
```

```bash
jmeter -n -t mix.jmx -l mix.jtl -e -o rpt-mix/ \
  -Jt_home=245 -Jt_search=146 -Jt_order=97 \
  -Jrampup=120 -Jduration=1800
```

**多线程组比吞吐量控制器更好的地方**：每个业务可以有独立的 think time、独立的 CSV 数据源、独立的 SLA，报告里也天然按线程组分开统计。

### Concurrency Thread Group 阶梯加压

先装插件：

```bash
# 把 jmeter-plugins-manager-x.x.jar 放进 lib/ext/ 后
cd apache-jmeter-5.6.3/bin
./PluginsManagerCMD.sh install jpgc-casutg,jpgc-tst,jpgc-perfmon
```

配置（20 分钟内分 4 级加到 200，然后维持 20 分钟）：

```xml
<com.blazemeter.jmeter.threads.concurrency.ConcurrencyThreadGroup
    guiclass="com.blazemeter.jmeter.threads.concurrency.ConcurrencyThreadGroupGui"
    testname="容量测试 50→200">
  <stringProp name="TargetLevel">${__P(target,200)}</stringProp>
  <stringProp name="RampUp">${__P(ramp,20)}</stringProp>
  <stringProp name="Steps">${__P(steps,4)}</stringProp>
  <stringProp name="Hold">${__P(hold,20)}</stringProp>
  <!-- M=分钟 S=秒 H=小时 -->
  <stringProp name="Unit">M</stringProp>
  <elementProp name="ThreadGroup.main_controller" elementType="LoopController">
    <boolProp name="LoopController.continue_forever">true</boolProp>
    <stringProp name="LoopController.loops">-1</stringProp>
  </elementProp>
</com.blazemeter.jmeter.threads.concurrency.ConcurrencyThreadGroup>
```

**参数含义（最容易理解错的地方）**：

```text
TargetLevel=200, RampUp=20分钟, Steps=4, Hold=20分钟

→ 每级增加 200/4 = 50 个并发
→ 每级持续 20/4 = 5 分钟
→ 时间轴：
   0~5min    : 50 并发
   5~10min   : 100 并发
   10~15min  : 150 并发
   15~20min  : 200 并发
   20~40min  : 200 并发（Hold 阶段）
→ 总时长 = RampUp + Hold = 40 分钟
```

`RampUp` 是**加压总时长**，不是每级时长。这是最常见的误解。

### 压力机自身的调优

想压更多线程，压力机本身要先调好，否则瓶颈出在压力机身上。

**调大 JMeter 的 JVM 堆**（`bin/jmeter` 或 `bin/jmeter.bat`）：

```bash
# 默认只有 1G，压测时至少给 4~8G（不要超过物理内存的 60%）
export HEAP="-Xms4g -Xmx4g -XX:MaxMetaspaceSize=512m"
# G1 更适合大堆，减少长停顿
export JVM_ARGS="-XX:+UseG1GC -XX:MaxGCPauseMillis=100"
```

**调小线程栈**（线程多时能省下大量内存）：

```bash
# 默认 1M，压测脚本调用栈不深，256k 足够
export JVM_ARGS="$JVM_ARGS -Xss256k"
```

1000 个线程从 1M 降到 256k，能省下约 750MB。

**Linux 内核参数**（避免端口耗尽和文件句柄不足）：

```bash
# 查看当前可用端口范围
cat /proc/sys/net/ipv4/ip_local_port_range

# 扩大端口范围（默认 32768~60999，只有 2.8 万个）
sudo sysctl -w net.ipv4.ip_local_port_range="10000 65535"

# 允许 TIME_WAIT 状态的连接被复用
sudo sysctl -w net.ipv4.tcp_tw_reuse=1

# 加大文件句柄上限（每个连接占一个 fd）
ulimit -n 65535
```

**验证压力机没成为瓶颈**：

```bash
# 压测过程中另开终端观察
# 1. CPU 是否打满（超过 80% 就危险）
top -bn1 | head -5

# 2. TIME_WAIT 是否堆积（几万个就要担心端口耗尽）
ss -s

# 3. JMeter 自己是否在频繁 Full GC
jstat -gcutil $(pgrep -f ApacheJMeter) 2000 10
```

## 踩坑

1. **用循环次数控制压测时长，实际并发远低于设定值**。前面详细分析过：200 线程 ramp-up 200 秒循环 10 次，全程最多 11 个线程同时在跑。**永远用 `scheduler + duration + loops=-1`。**

2. **on_sample_error 设成 Stop Thread，压力悄悄下降**。压力测试跑到后期系统开始报错，线程一个个退出，聚合报告里 TPS 看起来「稳定」，实际是并发数在缩水。这份报告结论完全错误。

3. **线程数开太大，压力机自己先崩**。8G 内存的机器开 5000 线程，JMeter 先 OOM 或者陷入 Full GC 风暴。**压测前必须先做「压力机自检」**：只压一个 `httpbin/status/200` 之类的空接口，看压力机能稳定支撑多少线程。

4. **忘了调 JVM 堆**。JMeter 默认 `-Xmx1g`，压 500 线程加上结果缓存很容易打满，表现是 TPS 剧烈波动、周期性掉零——那是在 Full GC。

5. **端口耗尽**。高 TPS 短连接场景下，Linux 默认只有约 2.8 万个临时端口，且 TIME_WAIT 要等 60 秒回收。表现是压到某个点开始大量 `Address already in use` 或连接超时。解法：扩大端口范围 + `tcp_tw_reuse=1` + **在 HTTP 请求里启用 KeepAlive**。

6. **Concurrency Thread Group 的 RampUp 理解成「每级时长」**。设 `RampUp=20分钟, Steps=4` 以为总共跑 80 分钟加压，实际是 20 分钟加完。反过来也有人以为总时长就是 RampUp，忘了还有 Hold。**总时长 = RampUp + Hold。**

7. **多个线程组共享同一个 CSV，数据被抢**。三个线程组都挂了同一个 CSV Data Set，默认 `Sharing mode = All threads` 时它们共用一个读取指针，互相抢数据。要么每组一份文件，要么把 CSV 挂到各自线程组下并设成 `Current thread group`。

8. **setUp 线程组失败了但测试继续跑**。setUp 里登录失败，token 是空的，后面 490 个线程全部压出 401，白压半小时。**setUp 里要做前置校验，失败就 `prev.setStopTest(true)` 停掉整个测试。**

9. **delay（启动延迟）和 ramp-up 混淆**。`delay` 是「延迟多久才开始启动第一个线程」，`ramp_time` 是「开始启动后用多久启动完」。想做「先压 A 业务 5 分钟，再叠加 B 业务」，是给 B 线程组设 `delay=300`，不是设 ramp-up。

10. **Stepping Thread Group 在压力测试中线程死了不补**。压到系统出错，某些线程异常退出，Stepping 不会补新线程，实际并发缓慢下降。**用 Concurrency Thread Group，它按目标并发数补线程。**

## 面试怎么答

**Q：JMeter 一台压力机能压多少并发，不够了怎么办？**

A：JMeter 的模型是**一个虚拟用户一个真实 Java 线程**，所以并发上限受压力机内存和 CPU 限制。经验值：一台 8C16G 的机器，在调优后（堆调到 4～8G、线程栈降到 256k、关掉所有 GUI 监听器）大概能稳定跑 1000～3000 线程。

不够的时候有三条路，按成本从低到高：

**第一，减少 think time 或去掉 think time。** 同样打出 140 TPS，不加 think time 只需要 70 线程，加 3 秒 think time 需要 490 线程。如果测试目的是找接口极限而不是模拟真实用户行为，直接去掉 think time 能省 7 倍线程。

**第二，优化压力机配置。** 调大 JVM 堆、`-Xss256k` 减小线程栈、扩大 Linux 临时端口范围、开启 `tcp_tw_reuse`、提高 `ulimit -n`、启用 HTTP KeepAlive 减少建连。这些做完通常能提升 2～3 倍承载。

**第三，上分布式压测。** 一台 master 控制多台 slave，压力线性叠加。注意 master 只做调度和结果汇总，不参与发压。

还有第四条路：**换工具**。如果需要几万并发的长连接场景，JMeter 的线程模型本身就不合适，Gatling（基于 Akka 的异步模型）或者 wrk 用少量线程就能撑起海量连接，资源效率高一个数量级。

面试时补一句很加分：**压测前一定要先做压力机自检**——压一个几乎零耗时的接口（比如 nginx 直接返回 200），看压力机能打出多少 TPS。如果自检只能打 3000 TPS，那你去压一个目标 5000 TPS 的系统，测到的就是压力机的极限而不是被测系统的。

**Q：为什么压测要用调度器而不是循环次数？**

A：因为用循环次数控制时，**ramp-up 期间先启动的线程会先跑完先退出**，导致全程根本达不到设定的并发数。

举个具体例子：200 线程、ramp-up 200 秒、循环 10 次、单轮 1 秒。第 1 个线程在 0 秒启动，10 秒后跑完 10 轮就退出了；而第 200 个线程要到第 200 秒才启动。整个过程中同时在跑的线程最多只有十几个，服务端根本感受不到 200 并发的压力。

这个坑很隐蔽，因为报告不会报错，你只会看到「TPS 好像有点低」，然后去怀疑服务端性能。

正确配置是 `scheduler=true` + `duration=1800` + `loops=-1`（永远循环）。这样线程跑完一轮立刻开下一轮，加压完成后能维持真正的 200 并发稳态，直到时间到点统一停止。

**Q：Stepping Thread Group 和 Concurrency Thread Group 有什么区别，选哪个？**

A：选 Concurrency Thread Group，Stepping 已经被官方标记为 deprecated。

本质区别在**控制维度**：Stepping 控制的是「启动了多少个线程」，属于开环控制——线程如果因为异常退出了，它不会补；Concurrency 控制的是「维持多少个并发」，属于闭环控制——发现活跃并发不够会自动补新线程上去。

这个差异在两个场景下很致命：一是**压力测试**，压到系统出错时线程容易异常退出，Stepping 下实际压力会缓慢下降，而你从报告上看不出来；二是**长时间稳定性测试**，8 小时里难免有线程死掉，Concurrency 能保证压力恒定。

配置上要特别注意 Concurrency Thread Group 的参数含义：`TargetLevel=200, RampUp=20分钟, Steps=4, Hold=20分钟` 表示「20 分钟内分 4 级（每级 5 分钟、每级加 50）加压到 200，然后维持 20 分钟」，**总时长是 RampUp + Hold = 40 分钟**。很多人把 RampUp 理解成每级时长，算错整整 4 倍。

## 参考

- [JMeter Thread Group 官方文档](https://jmeter.apache.org/usermanual/test_plan.html#thread_group)
- [jmeter-plugins：Concurrency Thread Group](https://jmeter-plugins.org/wiki/ConcurrencyThreadGroup/)
- [JMeter 性能调优建议](https://jmeter.apache.org/usermanual/best-practices.html)
- 相关笔记：[[JMeter 加压策略：递增加压、阶梯加压与思考时间]]
- 相关笔记：[[JMeter 组件执行顺序与作用域]]
- 相关笔记：[[JMeter 分布式压测]]
- 相关笔记：[[压测模型推算：目标 TPS 与二八原则]]
