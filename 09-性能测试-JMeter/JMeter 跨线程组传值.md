---
created: 2026-07-31
tags: [性能测试/参数化]
---

# JMeter 跨线程组传值

> A 线程组登录拿到 token，B 线程组要用——直接 `${TOKEN}` 取到的是空值。**因为 JMeter 的变量是线程私有的，跨线程组必须走属性或文件。**

## 概念

### 为什么 `${VAR}` 跨不过线程组

JMeter 的作用域模型里有两套完全不同的存储：

| | 变量 Variables | 属性 Properties |
|--|---------------|-----------------|
| 引用方式 | `${VAR}` | `${__P(NAME)}` |
| 存储位置 | `JMeterVariables`（每线程一份） | `JMeterUtils` 的全局 Properties |
| 作用域 | **单个线程** | **整个 JVM** |
| 生命周期 | 线程结束即销毁 | 整个测试进程 |
| 线程安全 | 天然隔离，无竞争 | 所有线程共享，有竞争 |
| 分布式下 | 每台 slave 各自独立 | **每台 slave 各自独立**（不同步！） |

**变量线程私有是刻意的设计**：100 个线程模拟 100 个独立用户，各自的 token、购物车、会话必须互不干扰。如果变量是全局的，线程 A 登录后线程 B 的 token 就被覆盖了，压测模型完全失真。

所以「跨线程组传值」的本质是：**把某个值从「线程私有空间」提升到「JVM 全局空间」。**

### 三种跨线程组传值方案

| 方案 | 适合 | 优点 | 缺点 |
|------|------|------|------|
| **属性（Property）** | 全局共享的**单个值** | 简单、内存操作快 | 所有线程读到同一份；分布式下不同步 |
| **文件中转** | 每线程不同的**大批量数据** | 数据量不限，可切分 | 有 IO 开销，需处理并发写 |
| **外部存储（Redis/DB）** | 分布式压测下的共享数据 | 真正全局，跨机器 | 引入外部依赖，有网络开销 |

### 属性方案：最常用

**写入**（两种等价方式）：

```text
函数写法：${__setProperty(GLOBAL_TOKEN,${TOKEN},)}
脚本写法：props.put("GLOBAL_TOKEN", vars.get("TOKEN"))
```

**读取**：

```text
${__P(GLOBAL_TOKEN)}
${__P(GLOBAL_TOKEN,默认值)}
${__property(GLOBAL_TOKEN,localVar,默认值)}    ← 读取并存进本地变量
```

**关键约束：属性是全局唯一的键值对。** 100 个线程都往 `GLOBAL_TOKEN` 里写，最后一个写的赢。所以属性**只适合传「所有线程共用的同一个值」**，比如：

- 管理员 token（所有线程都用同一个管理员身份）
- 全局配置（本轮压测的批次号、开始时间）
- 一个用于所有线程的公共资源 ID

**绝对不能用属性传「每个线程不同的值」**——那样所有线程会读到同一个值，参数化彻底失效。

### 每线程不同的值怎么跨线程组传

如果 A 线程组的 100 个线程各创建了一个订单，B 线程组的 100 个线程要各支付一个——这时属性方案无能为力。

**方案一：属性 + 线程号做后缀**

```text
写：props.put("ORDER_" + ctx.getThreadNum(), orderNo)
读：${__P(ORDER_${__threadNum()})}
```

前提是两个线程组的线程数一致且能一一对应，比较脆弱。

**方案二：文件中转（推荐）**

A 线程组把订单号写进文件，B 线程组用 CSV Data Set Config 读。这是最稳的做法。

**方案三：合并成一个线程组**

很多时候「跨线程组传值」的需求本身就是设计问题。**如果 A 和 B 是同一个业务链路的前后步骤，就应该放在同一个线程组里**，用变量直接传，根本不需要跨。

真正需要跨线程组的场景其实很少，主要是：

- setUp 线程组做全局准备（登录管理员、拿全局配置）
- 生产者-消费者模型（A 组不停创建订单，B 组不停消费处理）

## 用法

### 方案一：setUp 线程组 + 属性（全局 token）

```text
测试计划
├── setUp Thread Group（1 线程 1 循环）
│   ├── HTTP 请求 - 管理员登录
│   │   └── JSON 提取器 $.data.token → ADMIN_TOKEN
│   └── JSR223 Sampler - 提升为全局属性
├── 线程组-业务A（100 线程）
│   └── HTTP 信息头管理器：Authorization: Bearer ${__P(ADMIN_TOKEN)}
└── 线程组-业务B（50 线程）
    └── HTTP 信息头管理器：Authorization: Bearer ${__P(ADMIN_TOKEN)}
```

setUp 里的 JSR223 Sampler：

```groovy
// 把线程私有变量提升为 JVM 全局属性
def token = vars.get("ADMIN_TOKEN")

// 前置校验：拿不到 token 就没必要往下压了
if (!token || token == "NOT_FOUND" || token.length() < 20) {
    log.error("setUp 管理员登录失败，终止整个测试。实际值=${token}")
    prev.setStopTest(true)
    return
}

props.put("ADMIN_TOKEN", token)
// 同时记录一个批次号，供后续数据清理使用
props.put("BATCH_ID", "PT" + System.currentTimeMillis())
log.info("全局属性已就绪: token=${token.take(12)}...  batch=${props.get('BATCH_ID')}")
```

**`prev.setStopTest(true)` 这一步必须有**。setUp 失败还继续压，等于 150 个线程压半小时的 401。

用函数写法也可以（不需要 JSR223）：

```text
在登录请求后加一个 BeanShell/JSR223 或者直接在某个字段里调用：
${__setProperty(ADMIN_TOKEN,${ADMIN_TOKEN},)}
```

但函数写法没法做校验和日志，实战中还是推荐 JSR223。

### 方案二：文件中转（每线程不同的订单号）

**A 线程组：写文件**

```groovy
// JSR223 PostProcessor（挂在「创建订单」请求下）
def orderNo = vars.get("ORDER_NO")
if (!orderNo || orderNo == "NOT_FOUND") {
    return
}

// 用 JMeter 的 basedir 保证相对路径正确
def path = org.apache.jmeter.services.FileServer.getFileServer().getBaseDir() + "/orders.csv"
def f = new File(path)

// 多线程并发写同一个文件，必须加锁，否则会出现半行、串行
synchronized (ctx.getThreadGroup()) {
    f << "${orderNo}\n"
}
```

**`synchronized` 是必须的**——100 个线程同时往一个文件追加，不加锁会写出损坏的行（一行的内容被另一行截断）。

更稳的做法是**每个线程写自己的文件**，避免锁竞争：

```groovy
def path = org.apache.jmeter.services.FileServer.getFileServer().getBaseDir() +
           "/orders_${ctx.getThreadNum()}.csv"
new File(path) << "${vars.get('ORDER_NO')}\n"
```

压测结束后合并：

```bash
cat orders_*.csv > orders.csv
wc -l orders.csv
```

**B 线程组：用 CSV 读**

```xml
<CSVDataSet testname="读取订单号">
  <stringProp name="filename">orders.csv</stringProp>
  <stringProp name="variableNames">ORDER_NO</stringProp>
  <boolProp name="ignoreFirstLine">false</boolProp>
  <boolProp name="recycle">true</boolProp>
  <stringProp name="shareMode">shareMode.all</stringProp>
</CSVDataSet>
```

**时序问题**：B 线程组读文件时，A 线程组可能还没写完。解决办法是给 B 线程组设置**启动延迟**：

```xml
<!-- B 线程组延迟 120 秒启动，等 A 攒够数据 -->
<stringProp name="ThreadGroup.delay">120</stringProp>
```

或者干脆分两次跑：先跑 A 生成数据，再跑 B 消费。

### 方案三：Redis 共享（分布式压测的正解）

**属性在分布式压测下是不同步的**——每台 slave 是独立的 JVM，`props.put()` 只在本机生效。三台 slave 会各自登录、各自存一份 token，看起来「能用」，但如果需要真正的全局唯一数据（比如全局递增序号），就必须用外部存储。

装 Redis 插件：

```bash
./PluginsManagerCMD.sh install jpgc-redis
```

或者直接用 JSR223 + Jedis（把 `jedis-x.x.x.jar` 放进 `lib/`）：

```groovy
// JSR223 PostProcessor：把订单号推进 Redis 队列
import redis.clients.jedis.Jedis

// 复用连接，别每次都新建（放 props 里做单例）
def jedis = props.get("JEDIS_POOL")
if (jedis == null) {
    synchronized (this) {
        if (props.get("JEDIS_POOL") == null) {
            props.put("JEDIS_POOL", new Jedis("10.0.1.100", 6379))
        }
    }
    jedis = props.get("JEDIS_POOL")
}

jedis.lpush("perf:orders", vars.get("ORDER_NO"))
```

消费端：

```groovy
// JSR223 PreProcessor：从 Redis 队列取一个订单号
def jedis = props.get("JEDIS_POOL")
def orderNo = jedis.rpop("perf:orders")

if (orderNo == null) {
    // 队列空了，跳过本次请求
    log.warn("订单队列为空，跳过本轮")
    ctx.setRestartNextLoop(true)
    return
}
vars.put("ORDER_NO", orderNo)
```

**这个模式能完美实现跨机器的生产者-消费者压测**：一批 slave 跑「创建订单」线程组，另一批跑「支付订单」线程组，通过 Redis 队列衔接。

### 验证属性是否真的写进去了

```groovy
// JSR223 Sampler：打印所有自定义属性
props.entrySet()
     .findAll { it.key.toString().startsWith("ADMIN_") ||
                it.key.toString().startsWith("BATCH_") }
     .each { log.info("属性 ${it.key} = ${it.value}") }
```

或者在 B 线程组的第一个请求前加 Debug Sampler，配合察看结果树查看。

## 踩坑

1. **直接用 `${TOKEN}` 跨线程组，取到原样字符串**。B 线程组里 `${TOKEN}` 没有对应的变量，JMeter 会**原样输出 `${TOKEN}` 这 8 个字符**（不是空字符串，也不报错）。请求头变成 `Authorization: Bearer ${TOKEN}`，服务端返回 401。这个表现很迷惑，因为看日志会以为「token 传过去了只是格式不对」。

2. **用属性传每个线程不同的值**。100 个线程都 `props.put("TOKEN", 自己的token)`，最后一个写的覆盖所有，然后所有线程都用这一个 token 去压。表现是：数据库行锁竞争严重、TPS 异常低、或者服务端限流把你干掉。**属性只能传全局共享的单值。**

3. **分布式压测下以为属性是全局的**。三台 slave 各自是独立 JVM，`props` 不同步。用 `__counter(FALSE)` + 属性做全局唯一序号，三台机器生成三套 1,2,3...，主键冲突。**分布式要用 Redis 或数据库。**

4. **setUp 失败但测试继续跑**。setUp 里登录接口挂了，`ADMIN_TOKEN` 是 `NOT_FOUND`，`props.put` 存进去的也是 `NOT_FOUND`，150 个线程压半小时全是 401。**setUp 里必须做校验 + `prev.setStopTest(true)`。**

5. **多线程并发写同一个文件，写出损坏的行**。100 个线程同时 `file << text`，输出会出现 `PT2026073110ORDPT20260731102345\n` 这种被截断拼接的行。B 线程组读到这种脏数据后请求全部失败。**必须 `synchronized` 加锁，或者每线程写独立文件。**

6. **B 线程组启动时 A 还没写出数据**。两个线程组默认**同时启动**，B 一开始读文件发现是空的或者不存在，报错退出。**给 B 设置 `delay`，或者分两次跑。**

7. **文件路径用了绝对路径，分布式下 slave 找不到**。用 `FileServer.getFileServer().getBaseDir()` 拿到 jmx 所在目录，拼相对路径。

8. **`__setProperty` 的第三个参数没留空**。`${__setProperty(NAME,VALUE,)}` 第三个参数是「是否返回原值」，一般留空。填了 `true` 的话函数会把旧值输出到请求里，产生莫名其妙的内容。

9. **属性值被后续线程组意外覆盖**。两个线程组都往 `TOKEN` 里写，互相覆盖。**属性名要带明确前缀**：`ADMIN_TOKEN`、`MERCHANT_TOKEN`。

10. **Redis 连接每次新建，压测把 Redis 连接数打爆**。JSR223 里每次 `new Jedis(...)` 而不复用，500 TPS 下每秒创建 500 个连接。**必须做连接复用**（放 `props` 里做单例，或用 JedisPool）。

11. **该合并成一个线程组的场景，硬做跨线程组传值**。「创建订单 → 支付订单」是同一条业务链路，放在一个线程组里用变量直接传就行，非要拆成两个线程组再想办法传值，是自找麻烦。**先问自己：真的需要跨线程组吗？**

## 面试怎么答

**Q：JMeter 里怎么跨线程组传值？**

A：先说清楚为什么不能直接传：JMeter 的**变量 `${VAR}` 是线程私有的**，存在每个线程各自的 `JMeterVariables` 里，线程结束就销毁，其他线程组完全看不到。这是刻意的设计——100 个线程模拟 100 个独立用户，各自的 token 和会话必须隔离，否则压测模型就失真了。

跨线程组要把值提升到 **JVM 全局的属性空间**，有三种方案：

**方案一，属性（Property）**，适合传全局共享的单个值。写入用 `props.put("KEY", value)` 或函数 `${__setProperty(KEY,${VAR},)}`，读取用 `${__P(KEY)}`。典型场景是 setUp 线程组登录管理员账号，把 token 提升为属性供所有业务线程组使用。

**局限很明确：属性是全局唯一的键值对，只能传所有线程共用的同一个值。** 如果 100 个线程各有各的 token，都往同一个属性里写，最后一个会覆盖所有，然后所有线程用同一个 token 去压——数据库行锁竞争、限流触发，压测结果完全失真。

**方案二，文件中转**，适合传每线程不同的批量数据。A 线程组把订单号写进 CSV，B 线程组用 CSV Data Set Config 读。要注意两点：多线程并发写文件必须加 `synchronized` 锁（否则会写出被截断的损坏行），或者干脆每个线程写独立文件最后合并；另外 B 线程组要设置启动延迟，等 A 攒够数据。

**方案三，Redis 或数据库**，这是分布式压测下的唯一正解。因为**属性在分布式下是不同步的**——每台 slave 是独立 JVM，`props.put()` 只在本机生效。需要真正跨机器共享时，用 Redis 队列做生产者-消费者是最优雅的：一批 slave 跑创建订单，另一批跑支付订单，通过队列衔接。

最后补一句实践建议：**很多「跨线程组传值」的需求本身是设计问题**。如果两个操作属于同一条业务链路，就应该放在同一个线程组里用变量直接传。真正需要跨线程组的场景其实很少，主要就是 setUp 做全局准备和生产者-消费者这两类。

**Q：变量和属性有什么区别？**

A：核心是**作用域和生命周期**。

变量 `${VAR}` 存在 `JMeterVariables` 里，**每个线程一份**，线程结束就销毁，天然线程安全无竞争。所有提取器（正则、JSON、边界）提取出来的都是变量，CSV Data Set 读出来的也是变量。

属性存在 JMeter 的全局 Properties 里，**整个 JVM 共享一份**，测试期间一直存在。命令行 `-Jname=value` 传进来的、`props.put()` 写的、`jmeter.properties` 里配的，都是属性。

选择原则很简单：**每个用户不同的数据用变量，全局共享的配置用属性。** 把用户级数据放属性里是最常见的误用，会导致所有线程读到同一个值。

还有两个容易忽略的点：

一是**属性在分布式压测下不同步**。每台 slave 独立 JVM，各有各的属性表，`__counter(FALSE)` 这类依赖全局状态的东西在分布式下会重复。

二是**变量取不到时的行为很坑**——JMeter 不会报错也不会给空字符串，而是**原样输出 `${VAR}` 这个字符串**。所以请求头会变成 `Authorization: Bearer ${TOKEN}` 发出去，服务端返回 401，你看日志会以为是「格式问题」而不是「变量根本不存在」。调试时用 Debug Sampler 或 Debug PostProcessor 确认变量是否真的存在。

## 参考

- [JMeter Properties and Variables 官方说明](https://jmeter.apache.org/usermanual/test_plan.html#properties)
- [JMeter `__setProperty` 函数文档](https://jmeter.apache.org/usermanual/functions.html#__setProperty)
- 相关笔记：[[JMeter 关联：正则表达式提取器与 JSON 提取器]]
- 相关笔记：[[JMeter 函数助手常用函数]]
- 相关笔记：[[JMeter 组件执行顺序与作用域]]
- 相关笔记：[[JMeter 分布式压测]]
