---
created: 2026-07-31
tags: [性能测试/JMeter组件]
---

# JMeter 组件执行顺序与作用域

![[assets/jmeter-execution-order.svg]]
*图示：JMeter 单次采样的完整执行链路——配置元件 → 前置处理器 → 定时器 → 采样器 → 后置处理器 → 断言 → 监听器，以及非采样器组件按「作用域」而非「位置」生效的规则。*

> JMeter 里 90% 的「明明配了却不生效」都源于两件事没搞清：**执行顺序**和**作用域**。这一篇是所有 JMeter 组件笔记的地基。

## 概念

### 两条独立的规则

很多人把这两件事混成一件，这是所有困惑的根源：

- **执行顺序**：在一次采样中，各类组件按固定的**类别顺序**执行，与它们在树里的上下位置无关。
- **作用域**：某个组件对**哪些采样器**生效，由它在树里的**父子层级**决定，与上下位置无关。

**位置只在「同层级、同类型的多个组件之间」才决定先后。**

### 执行顺序：一次采样的完整链路

```text
0. 配置元件（Configuration Element）      —— 初始化，提供数据
1. 前置处理器（Pre-Processor）            —— 请求发出前改数据
2. 定时器（Timer）                        —— 等待
3. 采样器（Sampler）                      —— 真正发请求（唯一产生流量的组件）
4. 后置处理器（Post-Processor）           —— 从响应里提取数据
5. 断言（Assertion）                      —— 校验响应
6. 监听器（Listener）                     —— 收集/展示结果
```

记忆口诀：**配前定采后断听**（配置、前置、定时、采样、后置、断言、监听）。

几个必须记住的推论：

- **定时器在采样器之前执行**。你把定时器拖到采样器下面，它依然会在这个采样器发请求之前等待。「先发请求再等」在 JMeter 里做不到（要实现这个效果，得把定时器挂到**下一个**采样器上）。
- **断言在后置处理器之后**。所以断言里可以引用后置处理器提取出来的变量。
- **监听器最后执行**。所以监听器能看到断言的结果（失败标红）。
- **只有采样器会真正发出网络请求**。其他所有组件都是围绕采样器工作的辅助元件。

### 全局的一次性执行

在上面的循环之外，还有两个只跑一次的阶段：

```text
测试计划启动
├── setUp Thread Group        ← 先跑完，再进入正常线程组
├── 【正常线程组们】           ← 默认并行启动，除非勾了「独立运行」
└── tearDown Thread Group     ← 所有正常线程组结束后才跑
```

`setUp` 用来做准备（登录拿全局 token、清理脏数据、预热缓存），`tearDown` 用来做清理（删测试数据、恢复环境）。

**注意**：`tearDown` 默认在「测试正常结束」时才执行。如果你在 GUI 里点了停止按钮，或者用 `shutdown` 强杀，tearDown 可能不会跑。测试计划里有个 `tearDown After Shutdown` 选项要勾上。

### 作用域：父子层级决定生效范围

**核心规则：一个非采样器组件，对它的父节点下的所有采样器（含更深层级）生效。**

看这棵树：

```text
测试计划
└── 线程组
    ├── HTTP 信息头管理器 A          ← 作用域：线程组下所有采样器
    ├── HTTP 请求 1
    ├── 简单控制器
    │   ├── HTTP 信息头管理器 B      ← 作用域：只有 HTTP 请求 2、3
    │   ├── HTTP 请求 2
    │   └── HTTP 请求 3
    └── HTTP 请求 4
        └── 响应断言 C               ← 作用域：只有 HTTP 请求 4
```

- 信息头管理器 A：对请求 1、2、3、4 都生效
- 信息头管理器 B：对请求 2、3 生效（请求 2、3 会**同时**受 A 和 B 影响）
- 响应断言 C：只对请求 4 生效（挂在采样器下面 = 只作用于这个采样器）

**三种挂载位置的含义**：

| 挂在哪 | 作用域 |
|--------|--------|
| 测试计划下 | 所有线程组的所有采样器 |
| 线程组下 | 该线程组的所有采样器 |
| 控制器下 | 该控制器内的所有采样器 |
| 采样器下（作为子节点） | 仅该采样器 |

**这是 JMeter 最重要的设计**，理解了它，「为什么我的断言对所有请求都生效了」「为什么这个 CSV 被别的线程组也读了」这类问题就都解决了。

### 同类型组件的叠加行为

同一个采样器如果受多个同类组件影响，行为不是「覆盖」而是各有各的规则：

| 组件类型 | 多个同时作用时的行为 |
|----------|---------------------|
| HTTP 信息头管理器 | **合并**（同名 header 后者覆盖前者） |
| 定时器 | **累加**（3s + 2s = 等 5s） |
| 断言 | **全部执行**，任一失败则该采样标记失败 |
| 后置处理器 | 按上下顺序**依次执行** |
| CSV Data Set Config | 各自独立读各自的文件 |

**定时器累加**是最容易踩的坑——线程组级挂了 3 秒，某个请求下又挂了 2 秒，实际等 5 秒，TPS 直接腰斩。

### 控制器不改变执行顺序，只改变作用域和循环

逻辑控制器（简单控制器、循环控制器、事务控制器等）**不参与上面的 7 步顺序**，它们的作用是：

1. **划分作用域边界**（把一组采样器和它们的专属配置圈起来）
2. **控制采样器是否执行、执行几次**（If / Loop / Once Only）
3. **聚合统计**（事务控制器）

## 用法

### 验证执行顺序的最小实验

用 JSR223 组件在各阶段打日志，跑一次就能看清顺序：

```text
线程组（1 线程 1 循环）
├── JSR223 PreProcessor    → log.info("2. 前置处理器")
├── 固定定时器 100ms
├── HTTP 请求 - httpbin
│   ├── JSR223 PostProcessor → log.info("4. 后置处理器")
│   ├── 响应断言              → （断言失败时会在日志里体现）
│   └── JSR223 Assertion     → log.info("5. 断言")
└── JSR223 Listener        → log.info("6. 监听器")
```

各 JSR223 组件的脚本（语言选 Groovy）：

```groovy
// JSR223 PreProcessor
log.info("[${new Date().format('HH:mm:ss.SSS')}] 2. 前置处理器执行")
```

```groovy
// JSR223 PostProcessor
log.info("[${new Date().format('HH:mm:ss.SSS')}] 4. 后置处理器执行, 响应码=${prev.getResponseCode()}")
```

```groovy
// JSR223 Assertion
log.info("[${new Date().format('HH:mm:ss.SSS')}] 5. 断言执行")
```

```groovy
// JSR223 Listener
log.info("[${new Date().format('HH:mm:ss.SSS')}] 6. 监听器执行, 耗时=${prev.getTime()}ms")
```

运行并观察日志：

```bash
jmeter -n -t order-demo.jmx -l demo.jtl -j demo.log
grep -E '^\S+ \S+ INFO' demo.log | grep -oE '\[.*' 
```

输出会严格按 2 → 4 → 5 → 6 的顺序，**即使你把 JSR223 Listener 拖到树的最上面也一样**。

### 作用域实战：全局 header + 单接口特殊 header

典型需求：所有接口都带 `Content-Type: application/json`，但上传接口要用 `multipart/form-data`。

```text
线程组
├── HTTP 信息头管理器（全局）
│      Content-Type: application/json
│      Accept: application/json
├── HTTP 请求 - 登录
├── HTTP 请求 - 查询
└── HTTP 请求 - 上传文件
    └── HTTP 信息头管理器（局部）
           Content-Type: multipart/form-data
```

**同名 header 后者（更近的）覆盖前者**，所以上传接口最终的 `Content-Type` 是 `multipart/form-data`，而 `Accept` 依然继承自全局。这是最优雅的写法，不需要为上传接口单独复制一份全局 header。

对应的 jmx 片段：

```xml
<!-- 线程组级：全局 header -->
<HeaderManager guiclass="HeaderPanel" testname="全局请求头">
  <collectionProp name="HeaderManager.headers">
    <elementProp name="" elementType="Header">
      <stringProp name="Header.name">Content-Type</stringProp>
      <stringProp name="Header.value">application/json</stringProp>
    </elementProp>
    <elementProp name="" elementType="Header">
      <stringProp name="Header.name">Accept</stringProp>
      <stringProp name="Header.value">application/json</stringProp>
    </elementProp>
  </collectionProp>
</HeaderManager>
```

### setUp / tearDown 的标准用法

**setUp 线程组：全局登录拿 token，存成属性供所有线程组使用**

```text
setUp Thread Group（1 线程 1 循环）
├── HTTP 请求 - 管理员登录
│   └── JSON 提取器：$.data.token → ADMIN_TOKEN
└── JSR223 Sampler - 把变量提升为全局属性
```

JSR223 Sampler 脚本：

```groovy
// 变量是线程私有的，属性是 JVM 全局的
// 只有转成属性，其他线程组才能读到
def token = vars.get("ADMIN_TOKEN")
if (!token || token == "NOT_FOUND") {
    // 拿不到 token 说明前置登录失败，直接让测试停掉，避免后面压出一堆 401
    log.error("setUp 登录失败，终止测试")
    prev.setStopTest(true)
    return
}
props.put("ADMIN_TOKEN", token)
log.info("全局 token 已就绪: ${token.take(12)}...")
```

其他线程组里用 `${__P(ADMIN_TOKEN)}` 引用。

**tearDown 线程组：清理压测数据**

```text
tearDown Thread Group（1 线程 1 循环）
└── JDBC Request - 删除本轮压测产生的订单
```

```sql
-- 用压测专用标记删除，绝不能用时间范围之类的模糊条件
DELETE FROM t_order
WHERE order_source = 'PERF_TEST'
  AND create_time >= '${TEST_START_TIME}';
```

**关键：压测产生的数据必须带可识别的标记**（比如 `order_source='PERF_TEST'`、用户名前缀 `perf_`），否则清理时无法精确定位，容易误删真实数据。

在测试计划里勾上「Run tearDown Thread Groups after shutdown of main threads」，保证被中断时也能清理。

### 事务控制器：让报告输出业务级 TPS

不加事务控制器时，聚合报告的每一行是一个 HTTP 请求；加了之后能得到「整个业务链路」的耗时。

```xml
<TransactionController guiclass="TransactionControllerGui" testname="TXN-完整下单流程">
  <!-- true: 生成一个父采样，聚合报告里会多出这一行 -->
  <boolProp name="TransactionController.parent">true</boolProp>
  <!-- true: 父采样耗时不含定时器等待时间（重要！） -->
  <boolProp name="TransactionController.includeTimers">false</boolProp>
</TransactionController>
```

**`includeTimers=false` 必须设**，否则 think time 会被算进事务耗时——你的「下单流程耗时」里混进了 3 秒的思考时间，数据完全失真。这是事务控制器最大的坑。

## 踩坑

1. **以为定时器放在采样器后面就是「请求后等待」**。JMeter 的定时器按作用域生效且永远在采样器之前，位置在下面也不改变这一点。想在两个请求之间插等待，就把定时器挂到**后一个请求**的下面。

2. **多个定时器叠加导致 TPS 腰斩**。线程组级有个 3 秒的高斯定时器，某个采样器下又加了 2 秒的固定定时器，实际等 5 秒。压出来 TPS 只有预期一半，团队去查服务端，白折腾。**定时器是累加的。**

3. **断言挂错层级，对所有接口生效**。想给「下单」加个 `"code":0` 的断言，结果拖到了线程组层级，登录、查询接口也被这个断言校验，全部报错。**断言默认要挂在具体采样器下面**，除非确实要全局生效。

4. **CSV Data Set Config 挂在测试计划下，被所有线程组共享读取**。三个线程组都在消费同一个 CSV，数据被抢，某些线程拿不到期望的数据。**除非确实要共享，否则 CSV 挂在线程组下面**，并注意 `Sharing mode` 的设置。

5. **setUp 线程组里提取的变量在其他线程组里取不到**。变量（`vars`）是**线程私有**的，setUp 线程组结束后就没了。必须用 `props.put()` 转成 JVM 属性，别的线程组用 `${__P(name)}` 读。

6. **tearDown 没执行，脏数据留在库里**。手动停止测试或者测试异常中断时，tearDown 默认不跑。要在测试计划里勾选 `Run tearDown Thread Groups after shutdown of main threads`。

7. **事务控制器把 think time 算进了耗时**。`includeTimers` 默认是 true，3 秒 think time 被计入事务响应时间，报告里「下单流程 P95 = 3.5 秒」，实际业务耗时只有 500ms。**必须改成 false。**

8. **事务控制器忘了勾 `parent`**。不勾的话聚合报告里不会多出事务这一行，只有子请求的统计，等于白配。

9. **HTTP Cookie 管理器挂在测试计划下，多线程组共享 Cookie**。不同线程组模拟不同角色，结果 Cookie 串了，A 角色的请求带着 B 角色的会话。**Cookie 管理器应挂在线程组级**，且每个线程组一个。

10. **在采样器下面挂了 HTTP 信息头管理器，以为会覆盖全局的所有 header**。实际是**合并**：同名 header 覆盖，不同名的会叠加。想彻底替换全局 header 做不到，只能不设全局、每个接口各自配。

11. **JSR223 用了 `beanshell` 或者没勾缓存编译**。BeanShell 在高并发下性能极差（每次解释执行且有同步锁），会成为压力机自身的瓶颈。**统一用 Groovy，并勾选 `Cache compiled script if available`**，让脚本只编译一次。

## 面试怎么答

**Q：JMeter 各组件的执行顺序是什么？**

A：一次采样内部按固定的类别顺序执行：**配置元件 → 前置处理器 → 定时器 → 采样器 → 后置处理器 → 断言 → 监听器**。口诀是「配前定采后断听」。

在这之外还有两个只执行一次的阶段：测试开始时先跑完 setUp 线程组，所有正常线程组结束后跑 tearDown 线程组。

有几个推论在实际排错时很关键：

第一，**定时器永远在采样器之前执行**，哪怕你把它拖到采样器下面。所以「先发请求再等待」这个需求在 JMeter 里要通过「把定时器挂到下一个采样器」来实现。

第二，**断言在后置处理器之后**，所以断言里可以直接引用提取器提取出的变量，比如断言 `${TOKEN}` 不为空。

第三，**只有采样器会真正发出网络请求**，其余组件都是辅助元件，不产生流量。

**Q：JMeter 的作用域规则是什么？**

A：核心规则是——**非采样器组件对它的父节点下的所有采样器（包括更深层级）生效，与上下位置无关。**

具体说，一个信息头管理器挂在测试计划下就对所有线程组生效，挂在线程组下就对该线程组所有请求生效，挂在某个控制器下就只对该控制器内的请求生效，作为某个采样器的**子节点**挂着就只对这一个请求生效。

位置（上下顺序）只在一种情况下有意义：**同层级、同类型的多个组件之间**决定先后。比如同一个采样器下挂了两个正则提取器，才按从上到下依次执行。

这条规则解释了 JMeter 里绝大部分「配了但不生效」或者「生效范围超预期」的问题。最常见的是把断言拖到线程组层级，导致所有接口都被这个断言校验；或者把 CSV 挂在测试计划下，被多个线程组抢着消费。

还要补一点：**多个同类组件同时作用于一个采样器时行为不同**——信息头是合并（同名覆盖），定时器是累加，断言是全部执行、任一失败就算失败。定时器累加这一条最容易踩，线程组级 3 秒加上采样器级 2 秒实际等 5 秒，TPS 直接砍半。

**Q：setUp 线程组和普通线程组有什么区别？**

A：setUp 线程组在所有普通线程组之前执行完毕，tearDown 在所有普通线程组结束后执行。普通线程组之间默认是**并行**启动的（除非在测试计划里勾了「独立运行每个线程组」）。

setUp 典型用来做全局准备：管理员登录拿一个全局 token、清理上一轮的脏数据、预热缓存、往数据库塞基础数据。tearDown 用来清理压测产生的数据、恢复环境配置。

有一个必须知道的细节：**setUp 里提取的变量在其他线程组里读不到**，因为 JMeter 的变量 `vars` 是线程私有的，线程结束变量就没了。要跨线程组传值必须用 `props.put()` 把它提升成 JVM 级属性，其他线程组用 `${__P(name)}` 读取。

另一个坑是 **tearDown 在测试被手动停止时默认不执行**，需要在测试计划里勾上 `Run tearDown Thread Groups after shutdown of main threads`，否则压测中途中断会留下一堆脏数据。

## 参考

- [JMeter 执行顺序与作用域官方说明](https://jmeter.apache.org/usermanual/test_plan.html#executionorder)
- [JMeter Component Reference](https://jmeter.apache.org/usermanual/component_reference.html)
- 相关笔记：[[JMeter 线程组与阶梯加压]]
- 相关笔记：[[JMeter HTTP 请求与信息头、Cookie 管理器]]
- 相关笔记：[[JMeter 逻辑控制器]]
- 相关笔记：[[JMeter 定时器与同步定时器集合点]]
- 相关笔记：[[JMeter 跨线程组传值]]
