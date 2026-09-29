---
created: 2026-07-31
tags: [性能测试/参数化]
---

# JMeter 关联：正则表达式提取器与 JSON 提取器

![[assets/correlation-dataflow.svg]]
*图示：参数化与关联的完整数据流——CSV 提供每线程不同的账号，登录响应经 JSON 提取器取出 token 存入线程私有变量池，后续请求引用；跨线程组时需转成 JVM 属性。*

> 关联（Correlation）解决的是「**后一个请求依赖前一个响应**」。录制回放之所以失败，99% 是因为漏了关联——token、sessionId、订单号这些动态值，回放时必须从上一步的响应里现取。

## 概念

### 什么是关联，为什么录制回放会失败

录制脚本时，服务端返回了 `token=abc123`，脚本把它硬编码进了后续请求。第二天回放，`abc123` 早就过期了，所有请求返回 401。

**关联就是把「硬编码的动态值」改成「从上一步响应里实时提取」。**

需要关联的典型值：

| 值 | 来源 | 特征 |
|----|------|------|
| token / JWT | 登录响应 | 有过期时间，每次登录都不同 |
| sessionId / JSESSIONID | 响应 Cookie | Cookie 管理器可自动处理 |
| CSRF token | 页面 HTML 或响应头 | 每个会话不同 |
| 订单号 / 流水号 | 创建接口响应 | 后续查询、支付都要用 |
| 分页游标 / cursor | 列表接口响应 | 翻页依赖 |
| 商品 ID | 列表接口响应 | 进详情页要用真实存在的 ID |

**判断一个值要不要关联的方法：把脚本放到第二天再跑一遍，凡是失败的地方，多半是漏了关联。**

### 三种提取器怎么选

| 提取器 | 适用响应格式 | 性能 | 推荐度 |
|--------|-------------|------|--------|
| JSON 提取器（JSON Extractor） | JSON | 高 | **JSON 接口首选** |
| 正则表达式提取器 | 任意文本、HTML、响应头 | 中（正则复杂时低） | 通用兜底 |
| XPath2 提取器 | XML / HTML | 低 | XML 接口 |
| 边界提取器（Boundary Extractor） | 任意文本 | **最高** | 左右边界明确时的最优选 |

**性能差异在高 TPS 下会体现出来**：正则回溯严重的表达式会吃掉压力机大量 CPU。能用 JSON 提取器就不要用正则，能用边界提取器就不要写复杂正则。

### JSON 提取器（JSONPath）

配置项：

```text
Names of created variables    TOKEN            ← 变量名
JSON Path expressions         $.data.token     ← JSONPath 表达式
Match No.                     1                ← 取第几个匹配
Default Values                NOT_FOUND        ← 提取失败时的兜底值
```

**JSONPath 语法速查**：

```text
$                    根节点
$.data.token         取 data 下的 token
$.data.list[0].id    取数组第一个元素的 id
$.data.list[*].id    取所有元素的 id（配合 Match No.=-1）
$..id                递归搜索所有层级的 id
$.data.list[?(@.status=='PAID')].orderNo   条件过滤
$.data.list.length() 数组长度
```

**Match No. 的三个取值**：

```text
1    取第一个匹配（最常用）
0    随机取一个匹配  ← 模拟真实用户随机点击，很实用
-1   取全部匹配，生成 VAR_1、VAR_2、...、VAR_matchNr
```

**`Match No.=0`（随机）是被严重低估的功能**：列表接口返回 20 个商品，用 0 就能让每个线程随机点开不同的商品，缓存命中率更接近真实，而不是所有线程都点第一个。

### 正则表达式提取器

配置项：

```text
Name of created variable    TOKEN
Regular Expression          "token"\s*:\s*"([^"]+)"
Template                    $1$            ← 引用第几个捕获组
Match No.                   1
Default Value               NOT_FOUND
Field to check              主体 / 响应头 / URL / 响应码
```

**`Template` 的写法**：

```text
$1$        取第 1 个捕获组
$2$        取第 2 个捕获组
$1$-$2$    拼接两个组
$0$        整个匹配串（含捕获组外的部分）
```

**「要检查的响应字段」很关键**：

| 选项 | 用途 |
|------|------|
| 主体（Body） | 默认，从响应体提取 |
| 主体（无引号） | 去掉转义引号后再匹配 |
| **信息头（Response Headers）** | 从 `Set-Cookie`、`Location`、自定义头里提取 |
| URL | 从重定向后的 URL 里提取 |
| 响应代码 | 提取状态码 |

从 302 的 `Location` 头里提取跳转参数，就必须选「信息头」。

### 边界提取器（Boundary Extractor）—— 被忽视的高性能选择

```text
Left Boundary     "token":"
Right Boundary    "
```

它做的是简单的字符串查找，**没有正则回溯，性能是正则提取器的数倍**。左右边界明确的场景（绝大多数）都应该优先用它。

### 变量 vs 属性：作用域的根本区别

这是关联里最重要的概念（详见 [[JMeter 跨线程组传值]]）：

| | 变量 `${VAR}` | 属性 `${__P(NAME)}` |
|--|--------------|---------------------|
| 作用域 | **线程私有** | **JVM 全局** |
| 生命周期 | 线程结束即销毁 | 整个测试期间 |
| 跨线程组 | 不可见 | 可见 |
| 适合放 | 每个用户不同的 token | 全局共享的配置 |

**提取器提取出来的永远是变量（线程私有）**，这是正确的设计——100 个线程各自登录拿到各自的 token，天然隔离。想跨线程组共享才需要转成属性。

### 提取失败的静默灾难

**提取失败时不会报错**，变量会被赋成 Default Value。如果默认值设了 `NOT_FOUND`，后续请求就会带着 `Authorization: Bearer NOT_FOUND` 继续压。

服务端返回 401，但如果你没配断言，**JMeter 认为这些请求「成功」了**（HTTP 401 也是一个正常响应，只要不是连接失败）。结果是：压了半小时，TPS 很漂亮（因为 401 返回极快），实际一个业务请求都没成功。

**所以关联和断言必须配套**：提取之后立刻断言提取结果非空。

## 用法

### JSON 提取器：提取 token

响应体：

```text
{
  "code": 0,
  "message": "success",
  "data": {
    "token": "eyJhbGciOiJIUzI1NiJ9.xxx",
    "userId": 100023,
    "expireIn": 7200
  }
}
```

配置（jmx）：

```xml
<JSONPostProcessor guiclass="JSONPostProcessorGui" testname="提取 token">
  <!-- 多个变量用分号分隔，可一次提取多个字段 -->
  <stringProp name="JSONPostProcessor.referenceNames">TOKEN;USER_ID</stringProp>
  <stringProp name="JSONPostProcessor.jsonPathExprs">$.data.token;$.data.userId</stringProp>
  <stringProp name="JSONPostProcessor.match_numbers">1;1</stringProp>
  <stringProp name="JSONPostProcessor.defaultValues">NOT_FOUND;-1</stringProp>
</JSONPostProcessor>
```

**一个提取器能同时提取多个字段**，用分号分隔，三个配置项的数量必须一一对应。这比挂 5 个提取器高效得多。

紧跟一个断言拦住提取失败：

```xml
<ResponseAssertion guiclass="AssertionGui" testname="断言-token 有效">
  <collectionProp name="Asserion.test_strings">
    <stringProp>NOT_FOUND</stringProp>
  </collectionProp>
  <!-- 变量名：对 TOKEN 变量做断言 -->
  <stringProp name="Scope.variable">TOKEN</stringProp>
  <stringProp name="Assertion.scope">variable</stringProp>
  <!-- 16 = Substring，6 表示取反（NOT） -->
  <intProp name="Assertion.test_type">18</intProp>
</ResponseAssertion>
```

用 JSR223 断言更清晰可控：

```groovy
// JSR223 Assertion：校验 token 提取成功
def token = vars.get("TOKEN")
if (!token || token == "NOT_FOUND" || token.length() < 20) {
    AssertionResult.setFailure(true)
    AssertionResult.setFailureMessage("token 提取失败: ${token}")
    // 提取失败说明后续请求全是无效的，跳到下一轮循环
    ctx.setRestartNextLoop(true)
}
```

### 从列表里随机取一个商品 ID

响应：

```text
{"data":{"list":[{"id":1001,"name":"A"},{"id":1002,"name":"B"},{"id":1003,"name":"C"}]}}
```

**方式一：Match No. = 0（随机）**

```xml
<JSONPostProcessor testname="随机取商品ID">
  <stringProp name="JSONPostProcessor.referenceNames">SKU_ID</stringProp>
  <stringProp name="JSONPostProcessor.jsonPathExprs">$.data.list[*].id</stringProp>
  <!-- 0 = 随机取一个匹配 -->
  <stringProp name="JSONPostProcessor.match_numbers">0</stringProp>
  <stringProp name="JSONPostProcessor.defaultValues">0</stringProp>
</JSONPostProcessor>
```

**方式二：Match No. = -1 后用 `__V()` 随机取**（能拿到匹配总数，更灵活）

```xml
<stringProp name="JSONPostProcessor.match_numbers">-1</stringProp>
```

生成 `SKU_ID_1` 到 `SKU_ID_n` 以及 `SKU_ID_matchNr`，然后：

```text
${__V(SKU_ID_${__Random(1,${SKU_ID_matchNr})})}
```

**为什么要随机取而不是永远取第一个**：所有线程都请求同一个商品详情，Redis 缓存 100% 命中，数据库压力为零，压出来的 TPS 严重虚高。随机取才能让缓存命中率接近生产。

### 正则提取器：从响应头提取

从 `Set-Cookie` 里提取自定义 token：

```xml
<RegexExtractor guiclass="RegexExtractorGui" testname="从响应头提取">
  <stringProp name="RegexExtractor.refname">AUTH_TOKEN</stringProp>
  <stringProp name="RegexExtractor.regex">X-Auth-Token:\s*([^\r\n]+)</stringProp>
  <stringProp name="RegexExtractor.template">$1$</stringProp>
  <stringProp name="RegexExtractor.match_number">1</stringProp>
  <stringProp name="RegexExtractor.default">NOT_FOUND</stringProp>
  <!-- 关键：从响应头而不是响应体提取 -->
  <stringProp name="RegexExtractor.useHeaders">true</stringProp>
</RegexExtractor>
```

从 HTML 页面提取 CSRF token：

```xml
<RegexExtractor testname="提取 CSRF token">
  <stringProp name="RegexExtractor.refname">CSRF</stringProp>
  <!-- 用 [^"]+ 而不是 .+，避免贪婪匹配跨到后面去 -->
  <stringProp name="RegexExtractor.regex">name="_csrf"\s+value="([^"]+)"</stringProp>
  <stringProp name="RegexExtractor.template">$1$</stringProp>
  <stringProp name="RegexExtractor.match_number">1</stringProp>
  <stringProp name="RegexExtractor.default">NO_CSRF</stringProp>
</RegexExtractor>
```

**正则写法的两条铁律**：

1. **用 `[^"]+` 而不是 `.+`**。`.+` 是贪婪匹配，会一直吃到行尾最后一个引号，提取出一大串垃圾。
2. **用 `.+?` 时也要小心**。非贪婪虽然能限制范围，但在长响应体上回溯成本很高，高 TPS 下会拖垮压力机。**优先用字符类排除法 `[^x]+`。**

### 边界提取器：性能最优解

```xml
<BoundaryExtractor guiclass="BoundaryExtractorGui" testname="边界提取 token">
  <stringProp name="BoundaryExtractor.refname">TOKEN</stringProp>
  <stringProp name="BoundaryExtractor.lboundary">"token":"</stringProp>
  <stringProp name="BoundaryExtractor.rboundary">"</stringProp>
  <stringProp name="BoundaryExtractor.match_number">1</stringProp>
  <stringProp name="BoundaryExtractor.default">NOT_FOUND</stringProp>
</BoundaryExtractor>
```

同样是提取 token，边界提取器的 CPU 消耗大约是正则提取器的 1/3～1/5。**在 1000+ TPS 的压测里，这个差异足以决定压力机能不能撑住。**

### 完整的关联链路示例

```text
线程组
├── CSV Data Set Config（username, password）
├── HTTP 信息头管理器（Authorization: Bearer ${TOKEN}）
├── 仅一次控制器
│   └── HTTP 请求 - 登录
│       ├── JSON 提取器 → TOKEN, USER_ID
│       └── JSR223 断言（校验 TOKEN 非 NOT_FOUND）
├── HTTP 请求 - 商品列表
│   ├── JSON 提取器（Match No.=0）→ SKU_ID
│   └── 响应断言（code == 0）
├── HTTP 请求 - 商品详情 /item/${SKU_ID}
├── HTTP 请求 - 创建订单
│   ├── JSON 提取器 → ORDER_NO
│   └── 响应断言
└── HTTP 请求 - 支付订单 /pay/${ORDER_NO}
```

**每一步提取后都跟一个断言**，这是关联的标准写法。

### 调试关联：Debug PostProcessor

```text
HTTP 请求 - 登录
├── JSON 提取器
└── Debug PostProcessor      ← 输出所有变量当前值
```

配合察看结果树，能看到：

```text
TOKEN=eyJhbGciOiJIUzI1NiJ9.xxx
USER_ID=100023
JMeterThread.last_sample_ok=true
```

命令行调试用 JSR223：

```groovy
// JSR223 PostProcessor：把所有自定义变量打出来
vars.entrySet()
    .findAll { !it.key.startsWith("JMeter") && !it.key.startsWith("__") }
    .each { log.info("  ${it.key} = ${it.value}") }
```

## 踩坑

1. **提取失败不报错，静默压了半小时无效流量**。提取器失败时把 `NOT_FOUND` 赋给变量，后续请求带着它继续发，服务端返回 401——但 401 也是一个正常的 HTTP 响应，JMeter 判定为「成功」。报告里 TPS 很漂亮（401 返回极快），实际零业务成功。**关联必须配套断言。**

2. **正则用 `.+` 贪婪匹配，提取出一大串垃圾**。`"token":"(.+)"` 会一路吃到响应体最后一个引号。**改成 `"token":"([^"]+)"`。**

3. **JSONPath 写错但不报错**。`$.data.tokenn`（多打一个 n）不会报错，只是提取不到，默认值生效。**先用在线 JSONPath 工具或 Debug PostProcessor 验证表达式。**

4. **在响应体里找响应头的内容**。想提取 `Set-Cookie`，但「要检查的响应字段」还是默认的「主体」，永远提取不到。**必须切到「信息头」。**

5. **所有线程都取列表第一个，缓存命中率虚高**。Match No.=1 让 200 个线程全部请求同一个商品详情，Redis 100% 命中，压出来的 TPS 是真实值的好几倍。**用 Match No.=0 随机取。**

6. **跨线程组用 `${TOKEN}` 取不到值**。变量是线程私有的，A 线程组提取的 token 在 B 线程组里读不到，得到的是原样字符串 `${TOKEN}` 或空值。**要用 `__setProperty` 转成属性。**

7. **多个提取器变量名重复，后面的覆盖前面的**。两个接口都提取 `${ID}`，第二个覆盖了第一个，后续引用拿到的是错的。**变量名要带业务前缀**：`ORDER_ID`、`USER_ID`、`SKU_ID`。

8. **复杂正则在高 TPS 下拖垮压力机**。含大量回溯的正则（嵌套量词、`.*?` 套 `.*?`）在长响应体上单次匹配要几毫秒，500 TPS 下就是每秒几秒的 CPU 消耗。**优先用边界提取器或 JSON 提取器。**

9. **`Match No.=-1` 后忘了用 `matchNr`**。取全部匹配时生成的是 `VAR_1`...`VAR_n` 和 `VAR_matchNr`，此时 `${VAR}` 本身是空的。想随机取要用 `${__V(VAR_${__Random(1,${VAR_matchNr})})}`。

10. **提取的值带了多余的引号或空格**。JSONPath 提取字符串时不带引号，但正则如果把引号写进捕获组 `"token":"?(.+?)"?` 就可能带上。用 Debug PostProcessor 确认实际值。

11. **响应是 gzip 压缩的，正则匹配不到**。JMeter 默认会自动解压（只要请求头带了 `Accept-Encoding: gzip`），但如果手动设置了奇怪的头导致解压失败，响应体是二进制乱码。检查察看结果树里的响应内容是否可读。

12. **动态值提取了但没在后续请求里引用**。改完提取器忘了改请求，请求里还是硬编码的旧 token。**改完用 1 线程 1 循环跑一遍，看察看结果树里实际发出的请求。**

## 面试怎么答

**Q：什么是关联，为什么录制的脚本直接回放会失败？**

A：关联是指**把后续请求所依赖的动态值，改成从前一个请求的响应里实时提取**。

录制回放失败的根本原因是：录制时服务端返回的 token、sessionId、CSRF token、订单号这些值被硬编码进了脚本。这些值都是**一次性或有时效的**——token 会过期、sessionId 换个会话就失效、CSRF token 每次页面加载都不同、订单号更是每次创建都是新的。回放时带着旧值发请求，服务端一律拒绝。

所以录制只是起点，录完必须做三件事：**参数化**（把写死的账号数据换成 CSV）、**关联**（把动态值改成实时提取）、**清理**（删掉图片、CSS、埋点这类无关请求）。

判断哪些值需要关联有个笨办法但很有效：**把脚本隔一天再跑一遍，凡是失败的地方基本都是漏了关联。**

**Q：JMeter 有哪些提取器，怎么选？**

A：主要四种：

**JSON 提取器**，用 JSONPath 语法，JSON 接口首选。语法直观（`$.data.token`），性能好，还能一个提取器同时提取多个字段（变量名、表达式、默认值都用分号分隔，一一对应）。

**边界提取器**，指定左右边界字符串来截取。这是**性能最好**的一个，因为它做的是简单字符串查找，没有正则回溯。左右边界明确的场景都应该优先用它，但很多人不知道有这个组件。

**正则表达式提取器**，通用兜底方案。优势是能处理任意文本格式，还能从**响应头、URL、响应码**里提取（这是 JSON 提取器做不到的，比如从 `Set-Cookie` 或 302 的 `Location` 头里取值）。劣势是复杂正则性能差。

**XPath2 提取器**，处理 XML 和 HTML，性能最差，非必要不用。

选择原则：**JSON 响应用 JSON 提取器，边界明确用边界提取器，需要提取响应头或格式复杂时才用正则。** 在 1000+ TPS 的压测里，提取器的性能差异会直接体现在压力机 CPU 上，我遇到过因为一个回溯严重的正则导致压力机 CPU 打满、误判成服务端瓶颈的情况。

**Q：提取器提取失败会怎样，怎么防范？**

A：这是关联里最阴的一个坑——**提取失败不会报错**，变量会被赋成配置里的 Default Value（比如 `NOT_FOUND`），然后后续请求带着这个值继续发。

服务端会返回 401 或 400，但从 JMeter 的角度看，**这是一个正常收到的 HTTP 响应，采样器判定为「成功」**。于是报告里错误率是 0，TPS 还特别漂亮——因为 401 走的是鉴权拦截器，几毫秒就返回了，比真实业务请求快得多。你会得到一份「性能优异」的报告，实际上一个业务请求都没成功。

防范措施有三层：

**第一层，提取后立刻断言。** 用 JSR223 断言检查变量非空、不等于默认值、长度合理，失败就 `AssertionResult.setFailure(true)`，让这个采样在报告里显示为失败。

**第二层，把默认值设成明显异常的字符串**（`NOT_FOUND` 而不是空字符串），这样在察看结果树和日志里一眼能看出来。

**第三层，正式压测前必做「1 线程 1 循环冒烟」**，配合察看结果树逐个请求检查，确认每个提取器都拿到了预期的值、每个请求实际发出的内容都正确。这一步能拦住绝大部分关联问题，花 5 分钟能省下几小时的无效压测。

我自己的习惯是在 setUp 线程组里做一次完整的业务链路验证，任何一步失败就 `prev.setStopTest(true)` 直接终止整个测试，绝不让无效压测跑下去。

## 参考

- [JMeter Regular Expression Extractor 文档](https://jmeter.apache.org/usermanual/component_reference.html#Regular_Expression_Extractor)
- [JMeter JSON Extractor 文档](https://jmeter.apache.org/usermanual/component_reference.html#JSON_Extractor)
- [JMeter Boundary Extractor 文档](https://jmeter.apache.org/usermanual/component_reference.html#Boundary_Extractor)
- 相关笔记：[[JMeter 跨线程组传值]]
- 相关笔记：[[JMeter 参数化：CSV Data Set Config 与用户定义变量]]
- 相关笔记：[[JMeter 断言：响应断言与 JSON 断言]]
- 相关笔记：[[JMeter 函数助手常用函数]]
