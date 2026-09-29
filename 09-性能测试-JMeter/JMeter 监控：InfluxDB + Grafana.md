---
created: 2026-07-31
tags: [性能测试/执行与监控]
---

# JMeter 监控：InfluxDB + Grafana

## 概念

压测时只看 JMeter 自己产出的 TPS/RT 是不够的——那只是「客户端视角」，你还需要实时看到**被测系统的服务端指标**（CPU、内存、GC、数据库连接、接口耗时分布）。把两端数据放在同一时间轴上对比，才能判断「TPS 掉的那一刻，服务端到底发生了什么」。

InfluxDB + Grafana 是 JMeter 生态最常用的实时监控方案：

- **InfluxDB**：时序数据库，专门存带时间戳的指标点（TPS、RT、活跃线程、错误率…），写入快、按时间查快。
- **Grafana**：可视化面板，从 InfluxDB 拉数据画成曲线，提供现成的 JMeter 仪表盘模板。
- **Backend Listener**：JMeter 里的组件，把采样结果实时推送到 InfluxDB，替代落 jtl 再离线看报告的方式，实现「边压边看」。

设计动机：CLI 跑压测没有界面，传统的「跑完看 HTML 报告」是滞后的。如果你要在压测进行中实时干预（比如发现错误率飙升想立刻停），就需要一个实时通道，这就是 Backend Listener → InfluxDB → Grafana 的价值。

## 用法

### 1. 起 InfluxDB 和 Grafana

```bash
# docker 起 InfluxDB（1.8 版本，JMeter 官方 backend 适配最好）
docker run -d -p 8086:8086 \
  -e INFLUXDB_DB=jmeter \
  -e INFLUXDB_ADMIN_USER=admin -e INFLUXDB_ADMIN_PASSWORD=admin \
  --name influxdb influxdb:1.8

# docker 起 Grafana
docker run -d -p 3000:3000 --name grafana grafana/grafana
```

### 2. JMeter 加 Backend Listener

在测试计划里加 `Backend Listener`，选 `org.apache.jmeter.visualizers.BackendListenerClientImpl` 的 InfluxDB 实现：

```text
# Backend Listener 关键配置
backend_influxdb 实现类: org.apache.jmeter.visualizers.backend.influxdb.InfluxdbBackendListenerClient
influxdbUrl: http://<influxdb-ip>:8086/write?db=jmeter
application: order-service      # 应用名， Grafana 里区分不同压测
measurement: jmeter              # 默认
summaryOnly: false               # false 才记录每个采样器明细
testTitle: 订单压测-2026-07-31
```

`summaryOnly=false` 很重要：设为 true 只记 TOTAL 汇总，看不到单个接口曲线；设为 false 才能按接口名钻取。

### 3. Grafana 导入仪表盘

Grafana 里 Add Data Source → 选 InfluxDB，URL 填 `http://<influxdb-ip>:8086`，Database 填 `jmeter`。然后导入官方仪表盘模板（如 ID `5496` 或社区 Apache JMeter Dashboard），即可看到：

- 实时 TPS、RT（含 P95/P99）、错误率；
- 按接口拆分的响应时间；
- 活跃线程数（并发）随时间变化；
- 与 [[服务端资源监控与 JVM、GC、慢 SQL 定位]] 的服务端面板放在同一屏，两端对照。

### 4. 常用 InfluxQL 查询

```sql
-- 查某应用的总 TPS
SELECT sum("count") / 60 FROM "jmeter" WHERE "application"='order-service' AND "transaction"='TOTAL' GROUP BY time(1m)

-- 查单个接口 P95 响应时间
SELECT percentile("pct95", 95) FROM "jmeter" WHERE "application"='order-service' AND "transaction"='下单'
```

## 踩坑

1. **summaryOnly 默认 true 只记 TOTAL**：想看单接口曲线必须设 false，否则仪表盘里只有一条总 TOTAL 线，无法定位是哪个接口慢。
2. **influxdbUrl 的 db 参数要和库名一致**：`?db=jmeter` 必须和 InfluxDB 实际库名匹配，否则写入报 404。
3. **InfluxDB 2.x 不兼容官方 backend**：JMeter 自带 InfluxDB backend 直连的是 1.x 的 write 协议，2.x 要加 token/改路径，建议用 1.8 省心。
4. **application 名不规范，多轮压测数据混在一起**：每轮压测给不同的 application（或 testTitle），否则历史数据和本轮叠加，曲线串了。
5. **Backend Listener 也有开销**：实时推送要占一点网络/CPU，超大并发时如果 InfluxDB 写入慢会反压，必要时降低推送频率或关掉明细。
6. **Grafana 时间轴要和压测时间对齐**：默认 Grafana 显示最近 6 小时，压测只有 10 分钟可能被压扁，手动调时间窗到压测区间。
7. **只盯客户端 TPS 不盯服务端**：InfluxDB 里只有 JMeter 视角，必须配合 [[服务端资源监控与 JVM、GC、慢 SQL 定位]] 的服务端指标（node_exporter、JVM exporter）同屏看，否则没法判断瓶颈在服务端还是压测端。
8. **网络分区导致数据断点**：压测机到 InfluxDB 的网络抖动会让曲线出现空缺，排查时别误以为系统宕了，先看 InfluxDB 是否收到点。
9. **measurement 冲突**：多个不同脚本用同一个 measurement=jmeter 但不同 application，靠 application 区分是对的；别用同一个 application 跑不同脚本，会混淆。
10. **数据保留策略不设会无限涨**：InfluxDB 默认永久保留，长期压测库越来越大，应设 retention policy（如保留 30 天）。
11. **Backend Listener 放在线程组外还是内**：它应加在「测试计划」根下（和线程组同级），不是塞进某个线程组，否则只监控该线程组数据。
12. **仪表盘模板版本差异**：不同 Grafana 模板字段名可能不同（如 `pct95` vs `p95`），导入后若空白，检查 measurement 和字段名映射。

## 面试怎么答

**Q：JMeter 实时监控为什么用 InfluxDB + Grafana，而不是直接看报告？**

答：CLI 跑压测没有界面，传统「跑完生成 HTML 报告」是滞后的，你没法在压测进行中看到服务端发生了什么、也没法在错误率飙升时及时干预。InfluxDB 是时序库，适合存 TPS/RT 这种带时间戳的指标；Grafana 提供现成仪表盘；中间的 Backend Listener 把 JMeter 采样结果实时推到 InfluxDB，实现「边压边看」。关键是把客户端视角（TPS/RT）和服务端视角（CPU/GC/慢 SQL，见 [[服务端资源监控与 JVM、GC、慢 SQL 定位]]）放在同一时间轴对照，才能快速判断瓶颈。

**Q：Backend Listener 的关键配置有哪些？**

答：核心是四点：实现类用 InfluxDB 的 `InfluxdbBackendListenerClient`；`influxdbUrl` 指向 `http://ip:8086/write?db=jmeter` 且 db 名要对；`application` 每轮压测给不同值避免数据混叠；`summaryOnly` 设 false 才能记录每个接口明细曲线。另外它要加在测试计划根下，不是某个线程组里，否则只监控局部。

**Q：监控看到 TPS 掉、RT 涨，下一步怎么查？**

答：先把 JMeter 客户端视角和服务端视角同屏对照。如果服务端 CPU/内存/GC 都正常，但 TPS 掉、RT 涨，大概率是被测应用线程池满或下游依赖慢；如果服务端 CPU 也跟着飙，可能是算法/序列化重或锁竞争。具体按 [[性能瓶颈定位顺序与调优对策]] 的链路逐层下钻：压测机→网络→网关→应用→JVM→数据库，配合 JVM/GC 和慢 SQL 监控定点。

## 参考

- 官方文档（Backend Listener）：<https://jmeter.apache.org/usermanual/component_reference.html#Backend_Listener>
- InfluxDB 文档：<https://docs.influxdata.com/influxdb/v1.8/>
- Grafana 文档：<https://grafana.com/docs/grafana/latest/>
- [[服务端资源监控与 JVM、GC、慢 SQL 定位]]
- [[性能瓶颈定位顺序与调优对策]]
