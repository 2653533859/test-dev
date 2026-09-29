---
created: 2026-07-31
tags: [性能测试/执行与监控]
---

# JMeter 分布式压测

## 概念

单台压测机有物理上限：CPU、网卡、端口数、JVM 内存都有限。当你需要几万甚至几十万并发，或者单机能发压的 TPS 已经顶满，但被测系统还很闲，就说明**施压端成了瓶颈**。这时要用分布式压测（Distributed Testing）：一台 master（控制机）调度多台 slave（负载机/执行机），把压力分摊出去。

架构是 1 个 master + N 个 slave：

- **slave**：运行 `jmeter-server`，真正执行脚本、发请求、产生负载。slave **不把响应结果回传给 master**（只回传统计摘要），所以网络开销很小。
- **master**：把 jmx 脚本分发到所有 slave，统一启动/停止，收集各 slave 的汇总数据合并成一份报告。

设计动机就一句话：**施压端的瓶颈不能掩盖被测系统的真实能力**，分布式把发压能力横向扩展。

## 用法

### 准备 slave

每台 slave 机器上启动 server（确保和 master 同版本 JMeter、同 jdk）：

```bash
# slave 机器
jmeter-server -Dserver.rmi.ssl.disable=true
```

### 配置 master 知道 slave 在哪

在 master 的 `bin/jmeter.properties` 里列出 slave 地址：

```bash
# 多个用逗号分隔
remote_hosts=192.168.1.11,192.168.1.12,192.168.1.13
```

### master 一键调度

```bash
# -r 启动所有 remote_hosts 上的 slave
jmeter -n -t order_test.jmx -r -l result.jtl -e -o report/

# 或指定其中几台
jmeter -n -t order_test.jmx -R 192.168.1.11,192.168.1.12 -l result.jtl
```

### 总并发怎么算

总并发 = 每个 slave 的线程数 × slave 数量。比如脚本里线程组设 1000，挂 3 台 slave，总并发就是 3000。**脚本里的线程数是「每台 slave 的线程数」，不是总数**——这是最容易算错的点。

## 踩坑

1. **总并发 = 单 slave 线程数 × slave 数**：脚本里写的线程数是每台机器的，不是全局。误以为 1000 线程挂 3 台还是 1000，实际是 3000，容易把系统打爆。
2. **master 把 jmx 分发，但 CSV 数据文件不自动分发**：如果脚本用 [[JMeter 参数化：CSV Data Set Config 与用户定义变量]] 读本地 CSV，每台 slave 必须**自己机器上有这份 CSV**，且路径一致。否则有的 slave 读不到数据，参数化为空。
3. **slave 与 master 版本/jdk 必须一致**：版本不一致可能脚本不兼容、结果字段对不上，甚至连不上。
4. **RMI 端口与防火墙**：默认 RMI 通信有端口协商，跨网段/云环境常被防火墙挡。可固定 `server.rmi.port` 并在安全组放行，或同一内网部署。
5. **SSL 默认开启要配证书**：测试内网可 `-Dserver.rmi.ssl.disable=true` 关掉，省去证书；生产环境应配置正式证书。
6. **slave 回传的是汇总不是明细**：master 合并的是各机统计，想看单请求明细得去 slave 本地 jtl 或开 response_data.on_error，别指望 master 有全部样本。
7. **仍受单机带宽限制，但瓶颈转移了**：分布式解决的是「发压算力」，如果 slave 网卡本身是瓶颈（大响应体），加机器也救不了，要减响应体或换万兆网卡。
8. **时间点不同步导致报告曲线错位**：各机器时钟不一致，合并后的 TPS 随时间曲线会抖动。建议 slave 都做 NTP 时间同步。
9. **master 自己也会成瓶颈（slave 太多）**：slave 超过几十台时，master 收集汇总也有开销。极端规模要考虑分层调度或改用 [[JMeter 监控：InfluxDB + Grafana]] 直接入库。
10. **参数化数据在 slave 间要错开**：同一份 CSV 复制到各 slave，会导致不同 slave 用相同账号/数据撞车（如重复下单）。应给每台 slave 分配不同数据分片，或用 [[JMeter 跨线程组传值]] 的 Redis 方案全局去重。
11. **GUI 远程启动（Remote Start）同样禁忌**：GUI 里点远程启动只是方便调试，正式压测仍走 CLI `-r`。
12. **ramp-up 在每台 slave 上独立生效**：阶梯加压的时间参数按每台机器算，整体爬坡会和单机预期一致（因为是并发叠加），但要注意总并发突变幅度。

## 面试怎么答

**Q：什么时候需要分布式压测？架构是怎样的？**

答：当单台压测机 CPU/网卡/端口/JVM 到顶，但被测系统还很闲、TPS 上不去时，说明施压端成了瓶颈，就要分布式。架构是 1 个 master + N 个 slave：slave 跑 `jmeter-server` 真正发压，只回传统计摘要（不回传每个响应，所以网络开销小）；master 分发 jmx、统一调度、合并各 slave 的汇总报告。总并发 = 单 slave 线程数 × slave 数。

**Q：分布式下 CSV 参数化文件怎么处理？**

答：master 只分发 jmx 脚本，**不自动分发 CSV 数据文件**。所以每台 slave 机器上必须自己放一份同路径的 CSV。但这带来第二个坑：如果各 slave 用完全相同的 CSV，会出现多台机器用同一批账号/数据撞车（比如重复下单、重复注册）。正确做法是给每台 slave 分配不同的数据分片，或者用 Redis 等共享存储做全局唯一数据分配，参见 [[JMeter 跨线程组传值]]。

**Q：分布式压测总并发算错会怎样？**

答：脚本里的线程数是「每台 slave 的线程数」。如果脚本写 1000 线程、挂了 5 台 slave，实际总并发是 5000，不是 1000。算错通常会把系统直接打挂（超出预期容量），或者反过来以为压力够了其实没够。所以每次跑分布式前我都会先算一遍「单线程数 × 机器数 = 总并发」，并对照 [[压测模型推算：目标 TPS 与二八原则]] 的目标值核一遍。

## 参考

- 官方文档：<https://jmeter.apache.org/usermanual/remote-test.html>
- [[JMeter 参数化：CSV Data Set Config 与用户定义变量]]
- [[JMeter 跨线程组传值]]
- [[JMeter 监控：InfluxDB + Grafana]]
- [[JMeter 命令行压测与 HTML 报告]]
