---
created: 2026-07-31
tags: [性能测试/JMeter组件]
---

# JMeter HTTP 请求与信息头、Cookie 管理器

> HTTP 请求是唯一真正产生流量的采样器。**它的实现类选择、KeepAlive 开关、连接池配置，直接决定压力机能打出多少 TPS。**

## 概念

### HTTP 请求采样器的关键配置

```text
协议        http / https
服务器名    api.example.com（不带协议、不带路径）
端口        80 / 443（留空则按协议默认）
方法        GET / POST / PUT / DELETE
路径        /v1/order/create
内容编码    UTF-8（中文参数必填，否则乱码）
自动重定向  Follow Redirects / Redirect Automatically
Use KeepAlive  ← 压测必开
实现        HttpClient4 / Java / 空
```

### 「实现」选哪个：HttpClient4 vs Java

这是压测里影响性能最大的一个下拉框，但几乎没人注意。

| 实现 | 底层 | 连接池 | 推荐 |
|------|------|--------|------|
| HttpClient4 | Apache HttpComponents | **有连接池，支持 KeepAlive 复用** | **压测必选** |
| Java | JDK 自带 `HttpURLConnection` | 池化能力弱 | 不推荐 |
| 空（默认） | 取 `jmeter.properties` 里的 `jmeter.httpsampler` | 默认就是 HttpClient4 | 可接受 |

**为什么必须用 HttpClient4**：它有真正的连接池，配合 KeepAlive 能让同一个线程复用 TCP 连接。用 Java 实现或关掉 KeepAlive，每个请求都要走一次完整的 TCP 三次握手（HTTPS 还要加 TLS 握手，几十毫秒），结果是：

1. **响应时间虚高**：建连时间被计入 RT
2. **TPS 上不去**：压力机 CPU 大量消耗在握手上
3. **端口耗尽**：每次连接用掉一个临时端口，TIME_WAIT 堆积后压不动

### 自动重定向 vs 跟随重定向

两个看似一样的选项，行为差别很大：

| 选项 | 行为 | 报告里 |
|------|------|--------|
| Redirect Automatically | HttpClient 内部自动跟随 | **只有 1 条采样记录**，耗时是总耗时 |
| Follow Redirects | JMeter 自己发第二次请求 | **有子采样记录**，能看到每一跳的耗时 |

**压测推荐 `Follow Redirects`**，因为它能让你看到重定向链的每一跳耗时。如果发现一个接口有 3 次重定向，那是明显的性能问题（3 次网络往返），用 `Redirect Automatically` 会把它们藏起来只显示一个总数。

**更重要的是**：`Redirect Automatically` 模式下，重定向后的请求**不会应用后置处理器和断言**，容易导致提取不到数据。

### HTTP 信息头管理器（HTTP Header Manager）

配置请求头。**它是配置元件，按作用域生效**（详见 [[JMeter 组件执行顺序与作用域]]）。

多个信息头管理器同时作用于一个采样器时是**合并**：

- 不同名的 header 全部叠加
- 同名的 header，**层级更近的覆盖更远的**

压测中必配的 header：

```text
Content-Type: application/json     ← POST JSON 必须，否则服务端解析失败
Accept: application/json
User-Agent: JMeter/PerfTest         ← 打标，方便服务端日志区分压测流量
X-Request-Source: PERF_TEST         ← 自定义标记，用于数据清理和链路追踪
```

**`X-Request-Source` 这类标记是实战刚需**：服务端可以据此把压测流量路由到影子库、日志里可以过滤压测请求、事后清理数据时有明确依据。

### HTTP Cookie 管理器

管理 Cookie 的自动接收和回传，等价于浏览器的 Cookie 行为。

关键点：**Cookie 管理器的存储是线程私有的**。100 个线程 = 100 份独立的 Cookie 存储，天然模拟 100 个独立浏览器会话。这也是为什么它必须挂在线程组级而不是测试计划级——挂在测试计划级时，多个线程组会共享？不会，依然是线程私有，但**作用域会覆盖到所有线程组**，如果不同线程组模拟不同角色，就会出现意料之外的 Cookie 行为。

核心配置：

```text
Clear cookies each iteration?   每轮循环清空 Cookie
                                → 模拟「每次都是新用户」时勾上
                                → 模拟「登录后持续操作」时不勾
Implementation                  HC4CookieHandler（推荐）
Cookie Policy                   standard（默认，推荐）
```

**`Clear cookies each iteration` 的选择直接影响压力模型**：

- **勾上**：每轮都是新会话，每轮都要重新登录，服务端 session 创建压力大
- **不勾**：一个线程一个长会话，更接近真实用户（登录一次操作很多次）

大多数场景选**不勾**，然后把登录放在「仅一次控制器（Once Only Controller）」里。

### HTTP 请求默认值（HTTP Request Defaults）

把协议、服务器、端口、编码抽出来公共配置，避免每个请求重复填：

```text
线程组
├── HTTP 请求默认值
│      协议: https
│      服务器: ${__P(host,api.example.com)}
│      端口: 443
│      内容编码: UTF-8
├── HTTP 请求 - 登录   （只填路径 /v1/login）
└── HTTP 请求 - 下单   （只填路径 /v1/order）
```

**这是脚本可移植性的关键**：切换测试/预发/生产环境只需要改一处，或者直接命令行 `-Jhost=pre.example.com`。

## 用法

### 完整的 HTTP 请求配置（jmx 片段）

```xml
<HTTPSamplerProxy guiclass="HttpTestSampleGui" testname="POST 创建订单" enabled="true">
  <elementProp name="HTTPsampler.Arguments" elementType="Arguments">
    <collectionProp name="Arguments.arguments">
      <elementProp name="" elementType="HTTPArgument">
        <boolProp name="HTTPArgument.always_encode">false</boolProp>
        <!-- JSON body 放在 value 里，name 留空 -->
        <stringProp name="Argument.value">{"skuId":"${skuId}","num":${num},"source":"PERF_TEST"}</stringProp>
        <stringProp name="Argument.metadata">=</stringProp>
      </elementProp>
    </collectionProp>
  </elementProp>
  <stringProp name="HTTPSampler.domain">${__P(host,api.example.com)}</stringProp>
  <stringProp name="HTTPSampler.port">443</stringProp>
  <stringProp name="HTTPSampler.protocol">https</stringProp>
  <stringProp name="HTTPSampler.path">/v1/order/create</stringProp>
  <stringProp name="HTTPSampler.method">POST</stringProp>
  <stringProp name="HTTPSampler.contentEncoding">UTF-8</stringProp>
  <!-- 压测三件套 -->
  <boolProp name="HTTPSampler.use_keepalive">true</boolProp>
  <boolProp name="HTTPSampler.postBodyRaw">true</boolProp>
  <stringProp name="HTTPSampler.implementation">HttpClient4</stringProp>
  <!-- 跟随重定向（能看到每一跳） -->
  <boolProp name="HTTPSampler.follow_redirects">true</boolProp>
  <boolProp name="HTTPSampler.auto_redirects">false</boolProp>
  <!-- 超时：不设的话卡死的请求会一直占着线程 -->
  <stringProp name="HTTPSampler.connect_timeout">3000</stringProp>
  <stringProp name="HTTPSampler.response_timeout">10000</stringProp>
</HTTPSamplerProxy>
```

**`postBodyRaw=true`** 是发 JSON body 的关键——不设它，JMeter 会把内容当成表单参数处理。

**超时必设**：默认无超时，一个卡住的请求会永久占用一个线程。压测中如果服务端开始变慢，没超时的话所有线程都会被挂住，并发数实际归零，报告显示 TPS 掉零但看不出原因。

### 信息头管理器：全局 + 局部覆盖

```xml
<!-- 挂在线程组级：全局 -->
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
    <elementProp name="" elementType="Header">
      <stringProp name="Header.name">X-Request-Source</stringProp>
      <stringProp name="Header.value">PERF_TEST</stringProp>
    </elementProp>
    <!-- 引用登录后提取的 token -->
    <elementProp name="" elementType="Header">
      <stringProp name="Header.name">Authorization</stringProp>
      <stringProp name="Header.value">Bearer ${TOKEN}</stringProp>
    </elementProp>
  </collectionProp>
</HeaderManager>
```

上传接口局部覆盖 `Content-Type`：

```xml
<!-- 作为「上传文件」采样器的子节点 -->
<HeaderManager guiclass="HeaderPanel" testname="上传专用头">
  <collectionProp name="HeaderManager.headers">
    <elementProp name="" elementType="Header">
      <stringProp name="Header.name">Content-Type</stringProp>
      <stringProp name="Header.value">multipart/form-data</stringProp>
    </elementProp>
  </collectionProp>
</HeaderManager>
```

结果：上传接口的 `Content-Type` 是 `multipart/form-data`，但 `Accept`、`X-Request-Source`、`Authorization` 依然继承全局。

### Cookie 管理器 + 仅一次控制器：模拟真实登录会话

```text
线程组（100 线程，永远循环，duration=1800）
├── HTTP Cookie 管理器（不勾「每次迭代清除」）
├── HTTP 信息头管理器（全局）
├── 仅一次控制器 Once Only Controller
│   └── HTTP 请求 - 登录          ← 每个线程只执行一次
│       └── JSON 提取器 → TOKEN
├── HTTP 请求 - 首页
├── HTTP 请求 - 搜索
└── HTTP 请求 - 下单
```

**「仅一次控制器」的语义是「每个线程的第一次循环执行一次」**，不是「整个测试执行一次」。100 个线程会产生 100 次登录，之后就复用会话——这正好模拟真实用户「登录一次，操作很多次」的行为。

对比两种模型的服务端压力差异：

| 模型 | 1800 秒内的登录次数 | 说明 |
|------|---------------------|------|
| 登录放在循环里 | 100 线程 × 每轮 1 次 × 数千轮 = 几十万次 | 严重失真，session 表被打爆 |
| 登录放 Once Only | 100 次 | 接近真实 |

### 验证连接复用是否生效

KeepAlive 是否真的在复用连接，可以在压力机上直接观察：

```bash
# 压测中执行：统计到目标服务的连接数
ss -tn state established '( dport = :443 )' | wc -l

# 如果 KeepAlive 生效：连接数 ≈ 线程数（100 线程约 100 条连接）
# 如果没生效：连接数远小于线程数，但 TIME_WAIT 会暴涨
ss -tn state time-wait '( dport = :443 )' | wc -l
```

TIME_WAIT 数量持续上涨（几万级）就说明连接在被反复创建销毁，KeepAlive 没生效。

在 `jmeter.properties` 里调 HttpClient4 的连接池：

```text
# 每个 host 的最大连接数，默认 6（浏览器行为），压测要调大
httpclient4.max_connections_per_host=200
# 连接空闲多久后关闭（毫秒），要大于压测间隔
httpclient4.idletimeout=60000
# 复用连接（KeepAlive 的底层开关）
httpclient4.retrycount=0
```

**`max_connections_per_host` 默认只有 6**，这是模拟浏览器的行为，但压测时会成为严重的瓶颈——200 个线程抢 6 个连接，大量线程在排队等连接，你看到的响应时间里包含了大量的「等连接池」时间。

### 中文参数乱码的处理

```text
内容编码（Content encoding）: UTF-8
```

这个字段留空是中文乱码的第一大原因。另外 GET 请求的 query 参数要勾上 `Encode?`：

```xml
<elementProp name="keyword" elementType="HTTPArgument">
  <boolProp name="HTTPArgument.always_encode">true</boolProp>
  <stringProp name="Argument.name">keyword</stringProp>
  <stringProp name="Argument.value">性能测试</stringProp>
</elementProp>
```

或者用 `__urlencode` 函数手动编码：

```text
${__urlencode(${keyword})}
```

## 踩坑

1. **实现选了「Java」或留空且配置文件里改过默认值**。没有连接池，每个请求重新握手，TPS 只有 HttpClient4 的 1/3，响应时间虚高一倍。**统一显式选 HttpClient4。**

2. **没开 KeepAlive，端口耗尽**。压到几分钟后开始大量 `Address already in use`。`ss -s` 看 TIME_WAIT 有几万个。开 KeepAlive + `net.ipv4.tcp_tw_reuse=1` 解决。

3. **`httpclient4.max_connections_per_host` 用默认值 6**。这是我踩过最隐蔽的一个坑：200 线程压一个接口，TPS 死活上不去，服务端监控显示 CPU 只有 20%，压力机 CPU 也不高。查了半天发现 194 个线程都在等连接池。改成 200 后 TPS 直接翻了 4 倍。**压测前必改这个参数。**

4. **没设超时，服务端变慢时线程全被挂住**。默认无超时，服务端 hang 住后所有线程都在等，TPS 掉到 0 但没有任何错误信息。**必设 `connect_timeout=3000`、`response_timeout=10000`**，超时会记为失败，报告里能看出来。

5. **JSON body 没勾 `postBodyRaw`**。JMeter 把 JSON 当成表单参数发出去，服务端收到的 body 格式完全不对，返回 400。GUI 里的表现是「Body Data」页签和「Parameters」页签选错了。

6. **忘了填内容编码，中文全是乱码**。服务端收到 `??????` 或者 `æ€§èƒ½æµ‹è¯•`。填 `UTF-8` 解决。

7. **登录放在循环里，压出了几十万次登录**。真实用户登录一次操作半小时，压测里每轮都登录，服务端 session 表被打爆、Redis 里堆了几十万个 token。**登录要放「仅一次控制器」里。**

8. **Cookie 管理器勾了「每次迭代清除」但登录在 Once Only 里**。第二轮循环开始 Cookie 被清空，但登录不再执行，后续请求全部 401。这两个配置必须搭配一致。

9. **用 `Redirect Automatically` 导致提取器失效**。登录接口 302 跳转到首页，用自动重定向时后置处理器拿不到中间响应，token 提取失败。**改用 `Follow Redirects`**，或者干脆关掉重定向自己处理跳转。

10. **多个信息头管理器同名 header 冲突时搞不清谁生效**。规则是「层级更近的覆盖更远的」——采样器子节点 > 控制器 > 线程组 > 测试计划。搞不清时用「察看结果树」看实际发出的请求头。

11. **压测流量没打标，事后无法清理**。压完发现生产库里多了 50 万条测试订单，但没有任何字段能区分它们和真实订单。**从一开始就要在 header 和 body 里带 `PERF_TEST` 标记。**

## 面试怎么答

**Q：JMeter 的 HTTP 请求实现里 HttpClient4 和 Java 有什么区别？**

A：核心区别是**连接池能力**。HttpClient4 基于 Apache HttpComponents，有完整的连接池，配合 KeepAlive 能让同一线程复用 TCP 连接；Java 实现基于 JDK 的 `HttpURLConnection`，池化能力很弱。

在压测场景下这个差异被放大得非常明显：不复用连接意味着每个请求都要走 TCP 三次握手，HTTPS 还要加 TLS 握手（几十毫秒）。后果有三个——响应时间里混入了建连时间导致虚高、压力机 CPU 大量消耗在握手和加解密上导致 TPS 上不去、每次连接消耗一个临时端口导致 TIME_WAIT 堆积最终端口耗尽。

所以压测必须显式选 HttpClient4，并且勾上 KeepAlive。

还有一个配套的关键参数容易被忽略：`jmeter.properties` 里的 `httpclient4.max_connections_per_host` **默认只有 6**，这是模拟浏览器行为的设定。压测时 200 个线程抢 6 个连接，绝大部分线程都在排队等连接池，你测到的响应时间里混了大量排队时间，还会误判成服务端慢。我实际遇到过改完这个参数 TPS 翻 4 倍的情况。

**Q：压测脚本里登录该怎么处理？**

A：**登录必须放在「仅一次控制器（Once Only Controller）」里，绝不能放在循环体内。**

原因是流量模型失真。真实用户是登录一次、操作半小时，而放在循环里的话，100 个线程压 30 分钟会产生几十万次登录请求。这会带来两个问题：一是服务端的 session 表或 Redis 里堆积几十万个 token，压出来的瓶颈是登录接口和 session 存储，而不是你真正想测的业务接口；二是登录接口通常有加密、有验证码校验、有风控，本身很重，会严重稀释业务接口的压力占比。

「仅一次控制器」的语义是「每个线程的第一次循环执行一次」，100 个线程就是 100 次登录，之后靠 Cookie 管理器或提取出的 token 复用会话——这正好对应真实场景。

配套要注意 Cookie 管理器的「每次迭代清除 Cookie」不能勾，否则第二轮开始会话就没了，而登录又不再执行，后面全部 401。

如果需要全局共享一个 token（比如所有线程用同一个管理员账号），更好的做法是放在 setUp 线程组里登录一次，用 `props.put()` 提升成 JVM 属性，其他线程组用 `${__P(TOKEN)}` 读。

**Q：Cookie 管理器和信息头管理器有什么区别，为什么要挂在线程组级？**

A：信息头管理器是**静态配置**请求头，写死什么就发什么（可以引用变量）；Cookie 管理器是**动态维护**会话状态，它会自动接收响应里的 `Set-Cookie` 并在后续请求中自动带上，等价于浏览器的 Cookie 行为。

Cookie 管理器有个重要特性：**它的存储是线程私有的**。100 个线程各有一份独立的 Cookie 存储，天然模拟 100 个独立的浏览器会话，不会串味。

挂在线程组级而不是测试计划级，主要是**作用域**考虑：一个测试计划里可能有多个线程组模拟不同角色（普通用户、管理员、商家），如果 Cookie 管理器挂在测试计划级，它对所有线程组生效，配置就没法差异化——比如你想让管理员组「每次迭代清除 Cookie」而用户组不清除，挂在顶层就做不到。

同样的原则也适用于信息头管理器和 CSV Data Set Config：**能挂在线程组级就不要挂在测试计划级**，保持各线程组的独立性，脚本才好维护。

## 参考

- [JMeter HTTP Request 官方文档](https://jmeter.apache.org/usermanual/component_reference.html#HTTP_Request)
- [JMeter HTTP Cookie Manager 文档](https://jmeter.apache.org/usermanual/component_reference.html#HTTP_Cookie_Manager)
- [JMeter HTTP Header Manager 文档](https://jmeter.apache.org/usermanual/component_reference.html#HTTP_Header_Manager)
- 相关笔记：[[JMeter 组件执行顺序与作用域]]
- 相关笔记：[[JMeter 参数化：CSV Data Set Config 与用户定义变量]]
- 相关笔记：[[JMeter 关联：正则表达式提取器与 JSON 提取器]]
- 相关笔记：[[JMeter 逻辑控制器]]
