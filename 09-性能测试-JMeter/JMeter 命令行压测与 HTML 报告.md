---
created: 2026-07-31
tags: [性能测试/执行与监控]
---

# JMeter 命令行压测与 HTML 报告

![[assets/gui-vs-cli.svg]]
*图示：GUI 模式把 CPU 浪费在界面渲染和监听器回调上，施压端先成瓶颈；CLI 模式只跑采样引擎，把资源全留给发压，再用 jtl + HTML 报告 / Backend Listener 看结果。*

## 概念

JMeter 有两种运行形态：GUI（图形界面）和 CLI（非图形、命令行）。GUI 只是用来**写脚本、调试脚本**的，不是用来跑压测的。真正产生压测负载，必须在 CLI 模式（`jmeter -n`）下运行。

为什么 GUI 不能跑压测？因为 GUI 要持续重绘界面、刷新组件、把每个样本推给各种监听器做可视化，这些开销吃掉的 CPU 和内存，会直接挤占「发请求」所需的资源，导致**施压端自己先成为瓶颈**——你测出来的 TPS 其实是「JMeter 界面能跑多快」，不是「系统能扛多快」。所以行业铁律：**GUI 只调试，CLI 才压测**。

CLI 模式把资源全留给采样引擎，结果落盘为 jtl，再离线生成 HTML 报告或用 Backend Listener 实时推到 Grafana（见 [[JMeter 监控：InfluxDB + Grafana]]）。

## 用法

### 基本命令行

```bash
# -n 非 GUI；-t 指定脚本；-l 结果落 jtl
jmeter -n -t order_test.jmx -l result.jtl

# 指定远程 slave（分布式，见 [[JMeter 分布式压测]]）
jmeter -n -t order_test.jmx -r -l result.jtl

# 用属性覆盖脚本里的变量（不用改 jmx）
jmeter -n -t order_test.jmx -l result.jtl -Jusers=500 -Jrampup=120
```

脚本里用 `${__P(users, 200)}` 读取，默认值 200，命令行 `-Jusers=500` 覆盖。这样同一脚本能复用在不同梯度压测，见 [[JMeter 加压策略：递增加压、阶梯加压与思考时间]]。

### 生成 HTML 报告

```bash
# 先跑出 jtl，再生成（报告目录必须不存在或为空）
jmeter -n -t order_test.jmx -l result.jtl -e -o report/

# 或者基于已有 jtl 单独生成
jmeter -g result.jtl -e -o report/
```

报告目录打开 `report/index.html` 即可看：

- **Dashboard 页**：APDEX（应用性能指数）、聚合分位线汇总、错误分布。
- **Charts 页**：随时间变化的 TPS、RT（含 P95/P99）、活跃线程数、错误率、网络吞吐曲线，比 GUI 监听器直观得多。

### jtl 字段精简（必做）

默认 jtl 可能是 XML 且带全字段，百万样本几 G。生产压测改 CSV 并关响应体：

```bash
# bin/user.properties
jmeter.save.saveservice.output_format=csv
jmeter.save.saveservice.response_data=false
jmeter.save.saveservice.requestHeaders=false
jmeter.save.saveservice.responseHeaders=false
jmeter.save.saveservice.samplerData=false
# 出错时保留响应体，便于排查
jmeter.save.saveservice.response_data.on_error=true
```

### 常见 JVM 调优（施压端）

CLI 跑大并发时，JMeter 自身 JVM 要加内存，改 `bin/jmeter` 或 `bin/jmeter.bat` 里的 `HEAP`：

```bash
# 把默认 1g 提到 4g，避免 OOM
HEAP="-Xms4g -Xmx4g"
```

但注意：加内存只是让施压端不崩，**不会让单机能发更多压**。单机瓶颈到了就该上分布式（[[JMeter 分布式压测]]）。

## 踩坑

1. **GUI 跑压测数字失真**：界面渲染+监听器回调吃 CPU，施压端先瓶颈，测出的 TPS 是 JMeter 界面的上限而非系统上限。务必 CLI。
2. **`-e -o` 报告目录必须为空/不存在**：目录已存在会直接报错，先删或换名。
3. **`-e -o` 必须配合 `-l`**：没先生成 jtl 无法出报告；报告数据来自 jtl。
4. **没精简 jtl 导致磁盘爆**：XML + 全字段，百万样本几个 G，生产必须改 CSV 并关响应体。
5. **`-J` 属性脚本里要用 `__P` 读，不是 `${变量}`**：脚本里写 `${__P(users,200)}`，命令行 `-Jusers=500` 才能覆盖；直接 `${users}` 读不到命令行属性。
6. **施压端 JVM 内存不够 OOM**：大并发要调大 HEAP，但调内存不等于能发更多压，只是不崩。
7. **单机 CPU 跑满还以为是系统瓶颈**：CLI 下若施压机 CPU 100%，说明是发压端到顶了，不是被测系统，要加机器或减线程，见 [[JMeter 分布式压测]]。
8. **HTML 报告 TPS 曲线含 ramp-up 区**：开头爬坡段 TPS 低是正常的，看稳态区间，别被起步段误导。
9. **生成报告时会读全部 jtl 进内存**：超大数据集生成报告也可能 OOM，必要时用 Backend Listener 实时入库代替离线报告。
10. **Windows 下路径/中文 jmx 名要引号**：`jmeter -t "订单测试.jmx"` 中文名必须加引号，否则找不到文件。
11. **`-r` 分布式要先启 slave 的 jmeter-server**：master 只负责调度，slave 没起就 `-r` 会连不上。
12. **命令行结果看不到明细**：CLI 不渲染，排查失败样本要靠 jtl + `response_data.on_error=true` 或 Grafana，别指望实时界面。

## 面试怎么答

**Q：为什么压测必须用命令行而不是界面？**

答：GUI 要把 CPU 花在界面重绘、组件刷新、监听器实时可视化上，这部分开销挤占了发请求的资源，导致施压端自己先成为瓶颈——你测到的 TPS 是「JMeter 界面能跑多快」，不是系统能扛多快。CLI 模式（`jmeter -n`）只跑采样引擎，资源全留给发压，结果落 jtl 再离线生成 HTML 报告或推到 Grafana。所以铁律是：GUI 写脚本、调试脚本，CLI 才跑真压测。

**Q：jmeter -n -t x.jmx -l r.jtl -e -o report/ 这条命令每一段干嘛的？**

答：`-n` 非 GUI 模式；`-t x.jmx` 指定测试脚本；`-l r.jtl` 把每个样本结果落地成 jtl（这是后续分析的数据源）；`-e -o report/` 基于 jtl 生成 HTML 仪表盘报告到 report 目录。注意 report 目录必须为空或不存在，否则报错；jtl 必须在生成报告前存在。实战里我还会在 user.properties 里把 jtl 改成 CSV、关闭响应体只保留出错时的，避免百万样本撑爆磁盘。

**Q：命令行怎么不改脚本就换并发梯度？**

答：脚本里用 `${__P(users, 200)}` 这类属性函数读取变量（给默认值 200），命令行用 `-Jusers=500 -Jrampup=120` 覆盖。这样同一份 jmx 能在基准、负载、压力不同梯度间复用，不用每次改文件。配合 [[JMeter 加压策略：递增加压、阶梯加压与思考时间]] 的阶梯加压，可以一条命令跑一个梯度，自动化串联起来做全量压测。

## 参考

- 官方文档（CLI 模式）：<https://jmeter.apache.org/usermanual/get-started.html#non_gui>
- 官方文档（HTML 报告）：<https://jmeter.apache.org/usermanual/generating-dashboard.html>
- [[JMeter 分布式压测]]
- [[JMeter 监控：InfluxDB + Grafana]]
- [[JMeter 加压策略：递增加压、阶梯加压与思考时间]]
