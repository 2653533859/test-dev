---
created: 2026-07-31
tags: [性能测试/断言与监听]
---

# JMeter 断言：响应断言与 JSON 断言

> 没有断言的压测报告是废纸。**HTTP 200 不代表业务成功**——服务端可能返回 `{"code":500,"msg":"库存不足"}`，JMeter 一样判定为「成功」，你的 TPS 数字里全是失败业务。

## 概念

### 为什么压测必须加断言

JMeter 判定采样「成功」的默认标准非常宽松：**只要拿到了 HTTP 响应且响应码是 2xx/3xx，就算成功**。这意味着以下情况全部被算作成功：

| 实际情况 | HTTP 状态 | JMeter 判定 | 后果 |
|----------|-----------|-------------|------|
| 业务失败 `{"code":500,"msg":"库存不足"}` | 200 | **成功** | TPS 虚高，压的是错误分支 |
| 参数错误 `{"code":400}` | 200 | **成功** | 同上 |
| 降级返回兜底数据 | 200 | **成功** | 系统已经在降级你还在测 |
| 返回空列表（本该有数据） | 200 | **成功** | 压的是「查不到数据」的快速路径 |
| 401 未授权 | 401 | **失败**（4xx 默认失败） | 这个能发现 |

**最危险的是第一类**：错误分支通常极快（参数校验失败几毫秒就返回，根本不查数据库），混在样本里会把 TPS 拉高、把响应时间拉低，制造出「性能优异」的假象。

我实际遇到过：压测报告显示 TPS 850、P95 只有 90ms，团队很满意。加了业务断言重跑，错误率 78%——因为测试库的库存早就被前几轮压光了，所有下单请求都走「库存不足」的快速返回分支。真实 TPS 只有 180。

### 断言的种类

| 断言 | 校验对象 | 性能开销 | 推荐 |
|------|----------|----------|------|
| **响应断言** Response Assertion | 响应体/头/码，支持包含、匹配、相等 | 低（用 Substring 时） | **主力** |
| **JSON 断言** JSON Assertion | JSONPath 取值后比对 | 中（要解析 JSON） | JSON 接口精确校验 |
| **JSR223 断言** | 任意 Groovy 逻辑 | 中（勾缓存后低） | 复杂逻辑 |
| 大小断言 Size Assertion | 响应字节数 | 极低 | 判断是否返回空 |
| 持续时间断言 Duration Assertion | 单次响应时间 | 极低 | **压测慎用**，见踩坑 |
| XPath 断言 | XML | 高 | 非必要不用 |

### 响应断言的关键配置

```text
Apply to                 Main sample only（默认，对主采样生效）
要测试的响应字段          响应文本 / 响应代码 / 响应信息 / Response Headers / 
                        Request Headers / URL样本 / Document(text)
模式匹配规则              包括(Contains) / 匹配(Matches) / 相等(Equals) / 
                        字符串(Substring) / 否(Not) / 或者(Or)
要测试的模式              可填多个
```

**「包括」和「字符串」的区别是性能关键**：

| 规则 | 底层实现 | 性能 |
|------|----------|------|
| 包括（Contains） | **正则匹配** | 慢 |
| 字符串（Substring） | 纯字符串查找 | **快 3～10 倍** |
| 匹配（Matches） | 正则完整匹配 | 慢 |
| 相等（Equals） | 字符串全等 | 快 |

**压测断言一律用「字符串（Substring）」**，除非确实需要正则能力。这一条在高 TPS 下能省下大量压力机 CPU。

「否（Not）」和「或者（Or）」是**修饰符**，可以和上面四种叠加使用：

- `Substring + Not`：响应中**不包含**某字符串
- `Substring + Or`：多个模式满足**任意一个**即通过（默认是「全部满足」）

### 多个断言的叠加行为

一个采样器下挂多个断言时，**全部执行，任一失败则该采样标记为失败**。这和信息头管理器的「合并」、定时器的「累加」都不同。

失败信息会累积在 `Assertion.failureMessage` 里，聚合报告的错误统计能看到。

### 断言的性能代价

断言在**每个采样的响应上都要执行一次**。1000 TPS 意味着每秒执行 1000 次断言。

性能开销排序（从低到高）：

```text
大小断言 < 响应断言(Substring) < 响应断言(Contains/正则) 
        < JSON 断言 < JSR223 断言(未缓存) < XPath 断言
```

**优化原则**：

1. 用 Substring 而不是 Contains
2. 断言字符串越短越好（`"code":0` 比整段 JSON 快）
3. JSON 断言只在必要时用（正则/Substring 能解决就不用）
4. JSR223 断言必须勾「Cache compiled script」
5. **不要给每个请求都挂 5 个断言**，抓关键的 1～2 个

## 用法

### 响应断言：最常用的三种写法

**写法一：校验业务码（最重要）**

```xml
<ResponseAssertion guiclass="AssertionGui" testname="断言-业务码为0">
  <collectionProp name="Asserion.test_strings">
    <stringProp name="code0">"code":0</stringProp>
  </collectionProp>
  <!-- 响应文本 -->
  <stringProp name="Assertion.test_field">Assertion.response_data</stringProp>
  <boolProp name="Assertion.assume_success">false</boolProp>
  <!-- 2=Contains 8=Equals 16=Substring 1=Matches；加 4 表示 Not -->
  <intProp name="Assertion.test_type">16</intProp>
</ResponseAssertion>
```

`test_type` 取值速查：

```text
1  = Matches（正则完整匹配）
2  = Contains（正则包含）
8  = Equals（完全相等）
16 = Substring（字符串包含，性能最好）
+4 = Not（取反），如 20 = Substring + Not
+32 = Or（任一满足）
```

**写法二：排除错误关键词（Substring + Not）**

```xml
<ResponseAssertion testname="断言-无系统异常">
  <collectionProp name="Asserion.test_strings">
    <stringProp name="e1">Exception</stringProp>
    <stringProp name="e2">系统繁忙</stringProp>
    <stringProp name="e3">服务降级</stringProp>
  </collectionProp>
  <stringProp name="Assertion.test_field">Assertion.response_data</stringProp>
  <!-- 16 + 4 = 20 → Substring + Not -->
  <intProp name="Assertion.test_type">20</intProp>
</ResponseAssertion>
```

**「服务降级」这类关键词的断言在压测里价值极高**——系统在高压下触发熔断降级时返回的是兜底数据，HTTP 200、响应极快，不断言根本发现不了，你会以为系统扛住了。

**写法三：校验响应码**

```xml
<ResponseAssertion testname="断言-HTTP 200">
  <collectionProp name="Asserion.test_strings">
    <stringProp name="200">200</stringProp>
  </collectionProp>
  <!-- 响应代码字段 -->
  <stringProp name="Assertion.test_field">Assertion.response_code</stringProp>
  <intProp name="Assertion.test_type">8</intProp>
</ResponseAssertion>
```

### JSON 断言：精确校验字段值

```xml
<JSONPathAssertion guiclass="JSONPathAssertionGui" testname="JSON断言-code">
  <stringProp name="JSON_PATH">$.code</stringProp>
  <stringProp name="EXPECTED_VALUE">0</stringProp>
  <boolProp name="JSONVALIDATION">true</boolProp>
  <boolProp name="EXPECT_NULL">false</boolProp>
  <boolProp name="INVERT">false</boolProp>
  <!-- 用正则匹配期望值 -->
  <boolProp name="ISREGEX">false</boolProp>
</JSONPathAssertion>
```

**JSON 断言 vs 响应断言 Substring 的取舍**：

| | 响应断言 `"code":0` | JSON 断言 `$.code == 0` |
|--|--------------------|------------------------|
| 性能 | 快 | 慢（要解析整个 JSON） |
| 精确度 | 会误匹配（如 `"errorCode":0`） | 精确 |
| 格式容错 | `"code": 0`（有空格）会失败 | 不受空格影响 |

**结论**：日常校验用响应断言 Substring，字段名容易冲突或者响应格式不稳定时用 JSON 断言。**不要两个都挂**。

`JSONVALIDATION=false` 时只检查路径是否存在，不校验值——用来做「字段存在性」断言，比校验值快。

### JSR223 断言：复杂业务校验

```groovy
// JSR223 Assertion（务必勾选 Cache compiled script if available）
import groovy.json.JsonSlurper

// 先看 HTTP 层面
if (prev.getResponseCode() != "200") {
    AssertionResult.setFailure(true)
    AssertionResult.setFailureMessage("HTTP ${prev.getResponseCode()}")
    return
}

def body = prev.getResponseDataAsString()

// 空响应快速失败，避免后面解析抛异常
if (!body) {
    AssertionResult.setFailure(true)
    AssertionResult.setFailureMessage("响应体为空")
    return
}

try {
    def json = new JsonSlurper().parseText(body)

    if (json.code != 0) {
        AssertionResult.setFailure(true)
        AssertionResult.setFailureMessage("业务码异常: code=${json.code} msg=${json.message}")
        return
    }
    // 业务级校验：订单号必须生成
    if (!json.data?.orderNo) {
        AssertionResult.setFailure(true)
        AssertionResult.setFailureMessage("下单成功但未返回订单号")
        return
    }
    // 金额校验：不能是 0 或负数
    if ((json.data.amount ?: 0) <= 0) {
        AssertionResult.setFailure(true)
        AssertionResult.setFailureMessage("订单金额异常: ${json.data.amount}")
    }
} catch (Exception e) {
    AssertionResult.setFailure(true)
    // 响应可能是 HTML 错误页，截断打印便于定位
    AssertionResult.setFailureMessage("响应非法JSON: ${body.take(200)}")
}
```

**`prev` 是上一个采样结果对象**，常用方法：

```groovy
prev.getResponseCode()          // "200"
prev.getResponseDataAsString()  // 响应体
prev.getResponseHeaders()       // 响应头
prev.getTime()                  // 响应耗时（毫秒）
prev.getLatency()               // TTFB
prev.isSuccessful()             // 当前成功状态
prev.setStopTest(true)          // 停止整个测试
```

### 断言提取结果非空（关联的标配）

```groovy
// JSR223 Assertion：校验 token 提取成功
def token = vars.get("TOKEN")
if (!token || token == "NOT_FOUND" || token.length() < 20) {
    AssertionResult.setFailure(true)
    AssertionResult.setFailureMessage("token 提取失败: ${token}")
    // 后续请求必然全挂，直接跳到下一轮，省掉无效压力
    ctx.setRestartNextLoop(true)
}
```

用响应断言也能做，但要把「Apply to」的作用域改成变量：

```xml
<ResponseAssertion testname="断言-TOKEN非空">
  <stringProp name="Assertion.scope">variable</stringProp>
  <stringProp name="Scope.variable">TOKEN</stringProp>
  <collectionProp name="Asserion.test_strings">
    <stringProp>NOT_FOUND</stringProp>
  </collectionProp>
  <!-- Substring + Not -->
  <intProp name="Assertion.test_type">20</intProp>
</ResponseAssertion>
```

### 一个请求的标准断言配置

```text
HTTP 请求 - 创建订单
├── JSON 提取器 → ORDER_NO
├── 响应断言：Substring  "code":0            ← 业务码
├── 响应断言：Substring + Not  Exception|降级  ← 排除异常
└── JSR223 断言：校验 ORDER_NO 提取成功        ← 关联校验
```

**三个断言就够了，不要更多。** 每多一个断言，1000 TPS 下就是每秒多 1000 次执行。

### 让断言失败时能定位问题

压测时关掉了察看结果树，断言失败后怎么知道失败原因？在 jtl 里保留失败信息：

```text
# user.properties
jmeter.save.saveservice.assertion_results_failure_message=true
jmeter.save.saveservice.assertions=true
# 只保存失败样本的响应数据，成功的不存（关键：兼顾定位能力和磁盘占用）
jmeter.save.saveservice.response_data.on_error=true
```

**`response_data.on_error=true` 是个非常实用的配置**：只有失败的采样才保存响应体，既能定位问题又不会撑爆磁盘。

分析失败原因：

```bash
# 统计各类失败信息的分布
awk -F',' '$8=="false" {print $9}' result.jtl | sort | uniq -c | sort -rn | head -20
```

```bash
# 按接口 + 失败原因分组统计
awk -F',' '$8=="false" {print $3" | "$9}' result.jtl \
  | sort | uniq -c | sort -rn | head -20
```

## 踩坑

1. **不加断言，压了一堆业务失败的请求**。前面详细讲过：HTTP 200 + `{"code":500}` 被判定为成功，错误分支返回极快，TPS 虚高一倍以上。**这是性能测试最常见也最严重的错误。**

2. **只断言 HTTP 状态码**。以为加了「响应码等于 200」就够了，实际业务失败也是 200。**必须断言业务码。**

3. **用「包括（Contains）」而不是「字符串（Substring）」**。Contains 底层走正则，在高 TPS 下白白消耗压力机 CPU。改成 Substring 能快 3～10 倍。这是压测断言的第一优化项。

4. **断言字符串会误匹配**。断言响应包含 `"code":0`，但响应里有 `"errorCode":0`，也能匹配上，业务失败被判成成功。**字段名容易冲突时改用 JSON 断言。**

5. **响应格式有空格导致 Substring 失败**。服务端返回 `{"code": 0}`（冒号后有空格），断言写的是 `"code":0`，永远匹配不上，错误率 100%。**先用察看结果树看清实际响应格式。**

6. **用持续时间断言（Duration Assertion）做 SLA 校验**。设置「响应时间超过 500ms 就失败」，压测到饱和区时所有请求都超时，错误率 100%，报告变成一片红，反而看不出真实情况。**响应时间应该在报告里用 P95 分析，而不是用断言硬卡。** 持续时间断言只适合功能测试。

7. **断言挂错层级，对所有接口生效**。想给「下单」加断言，拖到了线程组层级，登录、查询接口也被这个断言校验，全部报错。**断言默认要挂在具体采样器下面。**

8. **JSR223 断言用 BeanShell 或没勾缓存**。BeanShell 在高并发下有全局锁，会成为压力机瓶颈。**统一用 Groovy 并勾选「Cache compiled script if available」。**

9. **断言太多，压力机成了瓶颈**。给每个请求挂 6 个断言，1000 TPS 下每秒执行 6000 次断言，压力机 CPU 打满。**抓关键的 1～3 个就够。**

10. **压测时开着察看结果树看断言结果**。GUI 模式下察看结果树会缓存所有响应，内存爆掉。**压测用命令行 + `response_data.on_error=true`，只保存失败样本的响应。**

11. **断言失败后不知道原因**。jtl 里没保存失败信息，只知道错误率 30% 但不知道错在哪。**开启 `assertion_results_failure_message=true`。**

12. **`assume_success` 被误勾**。这个选项的意思是「断言执行前先假定成功」，勾上后即使前面的采样已经失败（比如超时），断言也会跑并可能把它改成成功。基本不该用。

## 面试怎么答

**Q：压测为什么必须加断言，不加会怎样？**

A：因为 **JMeter 判定「成功」的标准只到 HTTP 层面**——只要拿到响应且状态码是 2xx/3xx 就算成功。但现代接口普遍用「HTTP 200 + 业务码」的设计，`{"code":500,"msg":"库存不足"}` 也是 HTTP 200，JMeter 会判定为成功。

后果比「统计不准」严重得多：**错误分支通常返回极快**。参数校验失败、库存不足、限流拒绝这些路径根本不查数据库，几毫秒就返回了。它们混在样本里会同时**把 TPS 拉高、把响应时间拉低**，制造出「性能优异」的假象。

我实际遇到过一次：报告显示 TPS 850、P95 只有 90ms，团队准备签字通过。加了业务断言重跑，错误率 78%——测试库的库存早被前几轮压光，所有下单都走「库存不足」的快速返回。真实 TPS 只有 180，差了 4 倍多。

还有一类更隐蔽的情况：**系统在高压下触发熔断降级，返回兜底数据**。HTTP 200、响应极快、格式也正常，不断言的话你会以为系统扛住了，实际它已经在降级了。所以我会专门加一条 `Substring + Not` 断言，排除「服务降级」「系统繁忙」这类关键词。

**Q：JMeter 有哪些断言，压测时怎么选才不影响性能？**

A：常用的是响应断言、JSON 断言、JSR223 断言三种。

**响应断言**是主力，校验响应体/头/码是否包含某内容。这里有个性能关键点很多人不知道：模式匹配规则里的「**包括（Contains）**」底层走的是**正则匹配**，而「**字符串（Substring）**」是纯字符串查找，**后者快 3～10 倍**。压测断言应该一律用 Substring，除非确实需要正则能力。

**JSON 断言**用 JSONPath 精确取值比对，好处是不会误匹配（响应断言写 `"code":0` 可能被 `"errorCode":0` 误匹配），也不受格式空格影响；代价是要解析整个 JSON，开销更大。所以只在字段名容易冲突或响应格式不稳定时用。

**JSR223 断言**处理复杂逻辑，比如校验订单号非空、金额大于零、提取的 token 有效。必须用 Groovy 并勾选「Cache compiled script」，让脚本只编译一次；用 BeanShell 的话有全局锁，高并发下直接成为压力机瓶颈。

性能优化原则总结成四条：**用 Substring 不用 Contains；断言字符串尽量短；每个请求挂 1～3 个关键断言而不是 6 个；JSR223 必须勾缓存。** 断言是每个采样都要执行的，1000 TPS 就是每秒执行 1000 次，累积开销很可观。

**Q：压测时能用持续时间断言来卡响应时间 SLA 吗？**

A：不建议，这是个常见误区。

持续时间断言的行为是「单次响应超过阈值就把这个采样标记为失败」。问题在于：压测到饱和区时，响应时间必然膨胀，所有请求都会被标记失败，错误率变成 100%，报告一片红。这时候你既看不出真实的错误（业务失败被淹没在超时失败里），也没法分析性能趋势。

**响应时间应该在报告层面用 P95、P99 来评估，而不是在采样层面用断言硬卡。** 断言的职责是判断「这次请求业务上成功了吗」，性能达标与否是报告分析阶段的事，两者不该混。

具体做法是：断言只管业务正确性；压测结束后看聚合报告的 95% Line 是否满足 SLA，不满足就分析瓶颈。如果需要在压测过程中实时监控响应时间是否超标，正确的方式是接 InfluxDB + Grafana 做实时看板并配告警，而不是用断言。

持续时间断言真正适合的场景是**功能测试**——单用户跑接口，验证某个接口不应该慢于某个值，那时候没有并发膨胀的干扰。

## 参考

- [JMeter Response Assertion 文档](https://jmeter.apache.org/usermanual/component_reference.html#Response_Assertion)
- [JMeter JSON Assertion 文档](https://jmeter.apache.org/usermanual/component_reference.html#JSON_Assertion)
- [JMeter JSR223 Assertion 文档](https://jmeter.apache.org/usermanual/component_reference.html#JSR223_Assertion)
- 相关笔记：[[JMeter 监听器与聚合报告解读]]
- 相关笔记：[[JMeter 关联：正则表达式提取器与 JSON 提取器]]
- 相关笔记：[[性能测试核心指标：TPS、响应时间与 P95 分位]]
