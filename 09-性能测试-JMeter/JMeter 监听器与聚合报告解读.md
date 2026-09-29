---
created: 2026-07-31
tags: [性能测试/断言与监听]
---

# JMeter 监听器与聚合报告解读

## 概念

监听器（Listener）是 JMeter 中负责「收集、展示、落地」采样结果的组件。采样器（Sampler）只负责发请求并产出原始结果，真正把结果变成你能看懂的指标（TPS、RT、错误率、分位线），靠的是监听器。

常见监听器分三类：

- **结果展示类**：查看结果树（View Results Tree）、用表格查看结果、图形结果。这些会把每个样本的细节（请求头、响应体、断言结果）保留在内存里，**只适合调试**。
- **指标汇总类**：聚合报告（Aggregate Report）、汇总报告（Summary Report）、断言结果。它们实时滚动计算统计量，压测时开销相对较小，但仍会占用内存。
- **数据落地/转发类**：Backend Listener，把指标推送到 InfluxDB / Prometheus，再由 Grafana 展示，这是生产压测最推荐的方式，详见 [[JMeter 监控：InfluxDB + Grafana]]。

设计动机很直接：压测不是「把请求发出去」就完了，你最终要回答的是「系统扛不扛得住、瓶颈在哪」。如果只跑不收集，跑完一无所有；如果收集得太重（每个样本全量存盘/存内存），又会反噬施压端自身，导致压测机先成为瓶颈，测出来的数字失真。所以监听器的核心矛盾是：**既要采集足够信息，又不能自己拖垮压测**。

## 用法

### 聚合报告字段逐字解读

聚合报告（Aggregate Report）是出报告时最常用的表格，每一列含义如下：

| 字段 | 含义 | 注意点 |
| --- | --- | --- |
| Label | 采样器名称，或 `TOTAL` 汇总 | 事务控制器会合并出独立 Label |
| # Samples | 该 Label 的样本总数 | 分布式下是各 slave 合并值 |
| Average | 平均响应时间（ms） | 易被长尾拉高，单独看意义有限 |
| Median | 50% 分位 RT（P50） | 一半请求快于它 |
| 90% Line | P90 响应时间 | 业务最常用 SLA 水位 |
| 95% Line | P95 响应时间 | 比 P90 更严格 |
| 99% Line | P99 响应时间 | 反映最慢那 1% 用户体验 |
| Min / Max | 最小 / 最大 RT | Max 只代表单次极端值 |
| Error % | 错误率 | 含 HTTP 非 2xx + 断言失败 |
| Throughput | 吞吐量 = 请求/秒 | 即 TPS，分母含思考时间 |
| Received KB/sec | 下行带宽 | 大响应体时涨得快 |
| Sent KB/sec | 上行带宽 | 大请求体时涨得快 |
| Avg. Bytes | 平均响应体积 | 排查大报文拖慢网络 |

分位线怎么算的：把所有样本 RT 从小到大排序，P90 就是「第 90% 位置」那个值——表示 90% 的请求都比它快。JMeter 用的是「最近秩（nearest rank）」式的取整算法，样本量越大越平滑。

### 命令行落地 jtl 再生成 HTML 报告

GUI 跑压测是禁忌（渲染 + 监听器会把施压端 CPU 吃满，详见 [[JMeter 命令行压测与 HTML 报告]]）。正确姿势是 CLI 跑、落 jtl、再生成报告：

```bash
# 非 GUI 模式跑测，结果写 jtl
jmeter -n -t script.jmx -l result.jtl

# 基于 jtl 生成 HTML 仪表盘报告到 report/ 目录（目录必须不存在或为空）
jmeter -g result.jtl -e -o report/
```

一步到位也可以：

```bash
jmeter -n -t script.jmx -l result.jtl -e -o report/
```

HTML 报告里有 `Dashboard` 和 `Charts` 两页：Dashboard 给 APDEX、分位线汇总；Charts 给随时间变化的 TPS、RT、并发、错误率曲线，比 GUI 监听器直观得多。

### jtl 精简，避免 XML 体积爆炸

默认 jtl 可能是 XML 且记录所有字段，百万样本时几个 G。生产压测改成 CSV 并只存必要字段：

```bash
# bin/user.properties 或 jmeter.properties
jmeter.save.saveservice.output_format=csv
jmeter.save.saveservice.timestamp_format=yyyy-MM-dd HH:mm:ss
# 只保留这些列，丢弃响应体/请求体
jmeter.save.saveservice.response_data=false
jmeter.save.saveservice.requestHeaders=false
jmeter.save.saveservice.responseHeaders=false
jmeter.save.saveservice.samplerData=false
# 只在出错时记录响应体，便于排查
jmeter.save.saveservice.response_data.on_error=true
```

### 查看结果树只用于调试

调试脚本时打开查看结果树，能看每个请求的请求头、响应体、提取变量。但**正式压测必须关掉或只勾「Errors」**：勾了 Errors 就只记录失败样本，内存可控；全量记录百万样本会直接 OOM。

## 踩坑

1. **查看结果树全量记录会 OOM、拖慢 TPS**：每个样本都把请求/响应塞进内存，几万样本后施压端先挂。正式跑只勾 Errors，或用 CLI + jtl。
2. **监听器越多越慢，GUI 渲染叠加更致命**：每个样本都会回调所有监听器。所以压测根本不该用 GUI（监听器 + 界面渲染双重开销），必须 CLI，见 [[JMeter 命令行压测与 HTML 报告]]。
3. **Throughput 的分母是「测试总时长」**：包含 ramp-up 启动期、线程预热，所以刚跑完的短脚本吞吐会偏低；算真实 TPS 要扣掉启动和收尾，或用稳定区间的平均值。
4. **90% Line 不是平均值也不是最大值**：它是排序后第 90 分位的 RT，代表「绝大多数用户」的体验水位。只看 Average 会被长尾掩盖，只看 Max 又过度恐慌。
5. **样本量太小，分位线抖动严重**：几百样本时 P95/P99 可能随一次慢请求大幅跳动，至少要几千样本才有统计意义。压测时长要给够。
6. **jtl 默认 XML 体积巨大**：一定要改 `output_format=csv` 并关闭响应体落地，否则磁盘和内存都扛不住。
7. **`-e -o` 必须配合 `-l` 且 -o 目录要空**：没先生成 jtl、或报告目录已存在，都会直接报错。
8. **Error % 不全等于业务失败**：4xx 在某些场景是预期（如「验证码错误」返回 400 算正常分支），这时不能单看 Error %，要结合 [[JMeter 断言：响应断言与 JSON 断言]] 和具体业务断言。
9. **KB/sec 和 TPS 是两回事**：Received/Sent KB/sec 是带宽指标，TPS 是请求速率；大报文会让带宽先到瓶颈而 TPS 上不去，别混为一谈。
10. **分布式压测 jtl 会自动在 master 汇总**：但前提是统一用 `-l` 输出；若各 slave 各自写文件再手动合并，时间戳和汇总容易错。
11. **监听器不跨运行累计**：每次启动测试都从零开始计，历史数据要去 jtl / HTML 报告里翻，别指望界面上的聚合报告会累加上次。
12. **聚合报告保留全量样本算分位，内存重**：超大样本时优先用 Summary Report（滚动统计，内存更友好）或直接 CLI + HTML 报告，别在 GUI 硬扛。

## 面试怎么答

**Q：聚合报告里的 Throughput 和 TPS 是什么关系？怎么看系统达没达标？**

答：JMeter 里的 Throughput 就是 TPS（请求/秒），计算公式是「总样本数 / 测试总时长（秒）」。但要注意两点：一是分母含思考时间，所以真实业务 TPS = 并发数 / 平均 RT（Little's Law，见 [[性能测试核心指标：TPS、响应时间与 P95 分位]]）；二是刚启动期会拉低均值，要取稳定区间。判断达标不能只看这一个值，要三件套一起看：① TPS 是否达到 [[压测模型推算：目标 TPS 与二八原则]] 算出的目标值；② P95/P99 RT 是否低于 SLA 阈值；③ Error % 是否在容忍线内（如 <0.1%）。三者同时满足才算通过。

**Q：为什么压测不能用 GUI 跑、不能开着查看结果树？**

答：两方面。一是 GUI 本身要渲染界面、刷新组件，会吃掉施压端大量 CPU，导致压测机先成瓶颈，数字失真。二是监听器，尤其查看结果树，每个样本都把请求/响应体塞进内存，全量记录几万样本就会 OOM，并且监听器回调本身拖慢采样节奏。正确做法是 CLI 模式 `jmeter -n -t -l` 跑，把结果落 jtl，再用 `-e -o` 生成 HTML 报告，或者用 Backend Listener 推到 Grafana 实时看。调试阶段可以短暂开查看结果树，但只勾 Errors。

**Q：P95 和平均值，报告里该信哪个？**

答：都看，但决策以分位线为主。平均值会被少数超慢请求拉高，也会因快慢抵消而显得「还行」，掩盖长尾。P95/P99 直接回答「95%/99% 的用户实际等多久」，是 SLA 的硬指标。实战里我会用平均值粗看整体水位，用 P95 卡业务达标线，用 P99 查极端长尾是不是数据库慢查询或 GC 停顿造成的，再结合 [[性能瓶颈定位顺序与调优对策]] 去定位。

## 参考

- 官方文档：<https://jmeter.apache.org/usermanual/listeners.html>
- 官方文档（聚合报告）：<https://jmeter.apache.org/usermanual/component_reference.html#Aggregate_Report>
- 官方文档（Backend Listener）：<https://jmeter.apache.org/usermanual/component_reference.html#Backend_Listener>
- [[JMeter 命令行压测与 HTML 报告]]
- [[JMeter 监控：InfluxDB + Grafana]]
- [[JMeter 断言：响应断言与 JSON 断言]]
