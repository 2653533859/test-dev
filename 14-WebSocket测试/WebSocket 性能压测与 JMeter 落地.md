---
created: 2026-09-29
tags: [WebSocket测试/性能压测]
---

# WebSocket 性能压测与 JMeter 落地

> 突破短连接压测思维惯性：深入理解 WebSocket 两阶段压测模型（握手风暴与长连接保活持有）、JMeter WebSocket 官方插件实战、单机万级并发瓶颈调优与服务端内存/连接数评估。

## 概念

### WebSocket 压测与传统 HTTP 压测的本质区别

在针对传统 HTTP 接口进行压测时，核心指标是 **TPS（每秒事务数）** 和 **响应时间（RT）**，连接随着请求完成而释放。而 WebSocket 压测存在**完全不同的双重维度模型**：

```text
阶段一：建连风暴期 (Connection Ramp-up)
   测试关注点: 每秒最大握手建立连接速率 (Handshake TPS)
   考验服务端: CPU 计算能力 (SSL/TLS 握手解密、Sec-WebSocket-Accept 哈希计算)

阶段二：长连接保活与高并发推流期 (Sustained Hold & Throughput)
   测试关注点: 恒定保持 10 万+ 在线长连接时的系统资源消耗与消息广播吞吐量
   考验服务端: 内存占用 (每个 Socket 读写缓冲区、TCP 接收/发送窗口)、文件句柄 (ulimit -n)
```

1. **不能单看 TPS**：一个系统能抗住 10 万个在线长连接「静默挂机维持心跳」，但一旦触发全员广播推送，瞬间产生的网络 IO 和网卡带宽可能会立即打崩服务器；
2. **连接数是有重量的**：Linux 内核中每个 TCP Socket 连接都需要分配 `rmem`（读缓冲区）与 `wmem`（写缓冲区）。假设单连接分配 16KB 内存，10 万连接仅内核网络栈就需要消耗近 1.6GB 物理内存，尚未计入 Java/Node.js 应用层 Session 对象的内存开销。

---

## 用法

### 1. JMeter WebSocket 核心插件选型

原生 Apache JMeter 不支持 WebSocket，生产环境压测主流采用社区最为成熟的插件：**`WebSocket Samplers by Peter Doornbosch`**。

核心 Sampler 组件分工：
- **WebSocket Open Connection**：专职负责发起 HTTP Upgrade 握手建立连接并保持；
- **WebSocket Single Write Sampler**：单向向服务端发送数据帧（无需等待应答）；
- **WebSocket Single Read Sampler**：专职监听并读取接收一条服务端推流数据帧；
- **WebSocket request-response Sampler**：发送一条请求帧，并阻塞等待一条响应帧；
- **WebSocket Ping/Pong Sampler**：专职发送底层的 `0x9` 心跳探测帧；
- **WebSocket Close Connection**：发送 `0x8` 关闭帧完成优雅挥手。

### 2. 标准加压测试场景脚本拓扑（JMX 设计）

```text
Test Plan
└── Concurrency Thread Group (目标保持 10,000 在线用户，阶梯加压 10 分钟)
    ├── 1. WebSocket Open Connection (建立长连接)
    │   └── 响应断言 (断言 HTTP 状态码必须为 101)
    ├── Loop Controller (循环保活与业务交互)
    │   ├── 2. WebSocket Ping/Pong Sampler (每隔 20s 发送一次 Ping)
    │   ├── 3. WebSocket Single Write Sampler (上报心跳/业务动作)
    │   └── Constant Timer (思考时间 20 秒)
    └── 4. WebSocket Close Connection (压测结束前优雅断开)
```

### 3. 施压机内核与系统参数调优（破除单机并发瓶颈）

在施压机上发起 10,000+ 长连接时，必须先调优施压机自身的 Linux 系统内核：

```bash
# 1. 扩大系统级与用户级最大文件句柄数
sysctl -w fs.file-max=1000000
echo "* soft nofile 1000000" >> /etc/security/limits.conf
echo "* hard nofile 1000000" >> /etc/security/limits.conf

# 2. 扩大客户端临时本地可用端口范围 (让单 IP 最多可发起约 6 万连接)
sysctl -w net.ipv4.ip_local_port_range="1024 65535"

# 3. 开启 TIME_WAIT 状态快速回收与复用
sysctl -w net.ipv4.tcp_tw_reuse=1

# 4. 优化 TCP 内存缓冲区，防止施压机自身内存耗尽
sysctl -w net.ipv4.tcp_rmem="4096 87380 4194304"
sysctl -w net.ipv4.tcp_wmem="4096 16384 4194304"
```

---

## 踩坑

1. **建连过快导致网关 SYN 队列溢出（Connection Refused）**：
   - *现象*：压测配置 10 秒内瞬间拉起 5000 个线程建连，大面积报错 `java.net.ConnectException: Connection refused`。
   - *根因*：握手风暴超出服务端半连接队列（`tcp_max_syn_backlog`）与全连接队列（`somaxconn`）上限，未处理的 SYN 包被直接丢弃。
   - *解法*：加压策略必须采用**缓慢性阶梯梯度加压（Ramp-up）**（例如每秒新增 50 个连接缓慢爬坡），并在服务端调大内核队列参数：
     ```bash
     sysctl -w net.core.somaxconn=65535
     sysctl -w net.ipv4.tcp_max_syn_backlog=65535
     ```
2. **JMeter 施压机自身内存被打爆导致压测失真**：
   - *现象*：单台 JMeter 维持到 8000 连接时，JMeter 控制台报错 `java.lang.OutOfMemoryError: Java heap space`。
   - *根因*：JMeter 默认每个连接线程都持有独立的调用栈和消息采样历史，内存消耗大。
   - *解法*：
     1. 严禁使用 GUI 界面压测，必须使用无头 CLI（`jmeter -n -t ...`）；
     2. 调整 JMeter JVM 堆启动参数：`export HEAP="-Xms4g -Xmx4g -XX:+UseG1GC"`；
     3. 突破万级并发时，采用 JMeter **分布式压测（Master-Slave 架构）**，由 3~5 台施压机分摊长连接。

---

## 面试怎么答

**Q：WebSocket 长连接的性能压测与普通 HTTP 接口压测有什么不同？你们是如何评估服务端性能瓶颈的？**
> 1. **双阶段压测模型**：HTTP 压测侧重单次请求事务的吞吐量，而 WebSocket 压测需要分阶段考核：
>    - **建连阶段**：评估系统的**最大连接握手吞吐能力（Handshake TPS）**，考验 CPU 计算能力与 TCP 握手队列（SYN/Accept 队列）；
>    - **保活与推流阶段**：在维持目标长连接数量（如 5 万连接）的同时，评估系统在全量广播与定点推送下的**消息投递延迟、丟包率与服务器物理内存消耗**。
> 2. **服务端资源瓶颈定位**：
>    - 监控每个连接带来的平均内存开销（评估是否发生内存泄漏或 GC STW 停顿）；
>    - 监控网卡带宽与网络软中断（`ksoftirqd` 占用），防止广播风暴瞬间撑爆千兆网卡带宽；
> 3. **施压端工程调优**：单机发起上万长连接时，必须调优施压机本地端口范围（`ip_local_port_range`）与文件描述符（`nofile` 上限调至百万级），结合无头非 GUI 模式消除施压机本身的性能木桶短板。

---

## 参考

- JMeter WebSocket Samplers by Peter Doornbosch：`https://github.com/ptrd/jmeter-websocket-samplers`
- Linux 内核网络高并发调优：`https://www.kernel.org/doc/Documentation/networking/ip-sysctl.txt`
- 相关笔记：[[09-性能测试-JMeter]]、[[JMeter 线程组与阶梯加压]]、[[02-Linux基础]]、[[14-WebSocket测试]]
