---
created: 2026-07-31
tags: [性能测试/参数化]
---

# JMeter 函数助手常用函数

> 函数是 JMeter 里唯一能在**运行时动态求值**的机制。搞不清「什么时候求值、求值几次、结果给谁看」，就会写出「所有线程订单号都一样」这类经典 bug。

## 概念

### 函数的语法与求值时机

```text
${__函数名(参数1,参数2,变量名)}
```

**最重要的一条规则：函数在「被引用的那一刻」求值，每次引用都重新求一次。**

```text
${__Random(1,100)}  写在请求 body 里
→ 线程 1 第 1 轮：37
→ 线程 1 第 2 轮：82
→ 线程 2 第 1 轮：15
```

这和用户定义变量（测试开始时求值一次，永远不变）是本质区别。

**但有一个巨大的例外**：如果把函数写在**用户定义变量**里，它只在测试启动时求值一次，之后所有线程都读到同一个固定值。

```text
用户定义变量：orderNo = ${__Random(1000,9999)}
→ 所有线程、所有轮次的 orderNo 都是同一个值，比如永远是 4271
```

**这是最常见的一个坑**。想让每次都不同，必须把函数直接写在使用它的地方（请求 body、header、路径里），或者用 `__V()` 做二次求值。

### 大多数函数的最后一个参数：变量名

```text
${__Random(1,100,myNum)}
                  ^^^^^ 把结果同时存进变量 myNum
```

存进变量后，后面可以用 `${myNum}` 反复引用**同一个值**：

```text
${__Random(1,100,num)}          ← 生成 37，存入 num
后面用 ${num} 拿到的都是 37      ← 不会重新生成
```

这个特性用来解决「一个随机值要在多处使用」的问题。比如订单号既要放 body 又要在断言里校验：

```text
body:  {"orderNo":"${__UUID(,orderNo)}", ...}
断言:  期望响应里包含 ${orderNo}
```

不用这个技巧的话，断言里的 `${__UUID()}` 会生成一个新的 UUID，永远匹配不上。

**这个「最后一个参数是变量名」的约定几乎所有 JMeter 函数都遵守，留空则不存变量。**

### 常用函数分类速查

**随机与唯一性**

| 函数 | 作用 | 示例 |
|------|------|------|
| `__Random(min,max,var)` | 区间随机整数 | `${__Random(1,100)}` |
| `__RandomString(len,chars,var)` | 随机字符串 | `${__RandomString(8,abcdefg123)}` |
| `__RandomFromMultipleVars(vars,var)` | 从多个变量里随机取一个 | 变量名之间用竖线分隔 |
| `__UUID()` | 生成 UUID | `${__UUID()}` |
| `__counter(perThread,var)` | 递增计数器 | `${__counter(FALSE)}` |

**时间**

| 函数 | 作用 | 示例 |
|------|------|------|
| `__time(format,var)` | 当前时间 | `${__time(yyyyMMddHHmmss)}` |
| `__timeShift(fmt,date,shift,locale,var)` | 时间偏移 | `${__timeShift(yyyy-MM-dd,,P7D,,)}` |

**属性与变量**

| 函数 | 作用 | 示例 |
|------|------|------|
| `__P(name,default)` | 读 JVM 属性（命令行 `-J` 传入） | `${__P(host,localhost)}` |
| `__property(name,var,default)` | 读属性并存变量 | `${__property(env,,test)}` |
| `__setProperty(name,value,ret)` | 设置属性（跨线程组传值） | `${__setProperty(TK,${TOKEN},)}` |
| `__V(varName)` | **二次求值**，解析拼接出来的变量名 | `${__V(user_${idx})}` |

**上下文信息**

| 函数 | 作用 |
|------|------|
| `__threadNum()` | 当前线程序号（从 1 开始） |
| `__machineName()` | 压力机主机名 |
| `__machineIP()` | 压力机 IP |
| `__samplerName()` | 当前采样器名 |

**编码与脚本**

| 函数 | 作用 |
|------|------|
| `__urlencode(str)` | URL 编码（中文参数必用） |
| `__base64Encode(str)` | Base64 编码 |
| `__digest(algo,str,salt,upper,var)` | MD5/SHA 摘要（做签名用） |
| `__groovy(script,var)` | **执行 Groovy 脚本，能力最强** |

### `__counter` 的两个模式

```text
${__counter(TRUE)}    每个线程独立计数：线程1 → 1,2,3...  线程2 → 1,2,3...
${__counter(FALSE)}   全局共享计数：所有线程共用一个计数器 → 1,2,3,4,5...
```

**`__counter(FALSE)` 在分布式压测下会失效**——它是 JVM 级的，每台 slave 各有一份，三台机器会生成三套 1,2,3...，造成主键冲突。分布式场景要用 `__machineIP()` 或 `__threadNum()` 加前缀来保证全局唯一。

### `__V()`：动态变量名的唯一解法

JMeter 不支持 `${${varName}}` 这种嵌套写法。要根据循环变量拼出变量名，必须用 `__V()`：

```text
已有变量：user_1=alice, user_2=bob, user_3=carol
循环变量：idx = 2

${user_${idx}}       ← 不生效，JMeter 原样输出这个字符串
${__V(user_${idx})}  ← 正确，先算出 "user_2"，再解析成 "bob"
```

这在处理**正则提取器的多匹配结果**时是必需的（提取器会生成 `VAR_1`、`VAR_2`、`VAR_matchNr` 这样一组变量）。

### `__groovy()`：函数搞不定就用它

前面所有函数能力有限时，`__groovy()` 可以执行任意 Groovy 代码：

```text
${__groovy(new Date().format('yyyy-MM-dd'),)}
${__groovy(vars.get('price').toInteger() * 2,)}
${__groovy((1..5).collect{ it * 10 }.join(','),)}
```

**但要注意性能**：函数在每次引用时都会编译执行一遍 Groovy 脚本，高 TPS 下会成为压力机的瓶颈。复杂逻辑应该用 JSR223 组件（可以勾选「缓存编译结果」）而不是 `__groovy()` 函数。

## 用法

### 生成全局唯一的订单号

单机压测：

```text
PT${__time(yyyyMMddHHmmss)}${__Random(100000,999999)}
```

分布式压测（必须带机器标识，否则多台机器会撞号）：

```text
PT${__machineIP()}-${__time(yyyyMMddHHmmssSSS)}-${__threadNum()}-${__counter(TRUE)}
```

更简洁可靠的方案：

```text
${__UUID()}
```

UUID 是全局唯一的，不需要考虑分布式问题。缺点是 36 个字符比较长，且不携带业务语义（看不出是什么时候生成的）。

### 时间函数的完整用法

```text
# 当前时间戳（毫秒）
${__time()}

# 当前时间戳（秒）
${__time(/1000)}

# 格式化时间
${__time(yyyy-MM-dd HH:mm:ss)}
${__time(yyyyMMdd)}

# 7 天后（P7D = period 7 days）
${__timeShift(yyyy-MM-dd,,P7D,,)}

# 3 小时前（PT-3H = negative 3 hours）
${__timeShift(yyyy-MM-dd HH:mm:ss,,PT-3H,,)}

# 基于指定日期偏移：2026-07-31 之后 30 天
${__timeShift(yyyy-MM-dd,2026-07-31,P30D,,)}
```

`__timeShift` 的偏移量用的是 ISO-8601 Duration 格式：

```text
P1D    = 1 天
P1M    = 1 月
P1Y    = 1 年
PT1H   = 1 小时
PT30M  = 30 分钟
P1DT2H = 1 天 2 小时
前面加负号表示往前偏移：P-7D
```

### 接口签名：`__digest` 做 MD5

很多接口要求 `sign = MD5(参数串 + secret)`：

```text
# 参数按字典序拼接后加密
${__digest(MD5,appId=${appId}&timestamp=${ts}&nonce=${nonce}${SECRET},,true,)}
                                                                      ^^^^ 转大写
```

参数依次是：算法、待加密串、salt、是否大写、存入变量名。

复杂签名逻辑建议用 JSR223 PreProcessor 写：

```groovy
// JSR223 PreProcessor：计算接口签名
import java.security.MessageDigest

def params = [
    appId    : vars.get("appId"),
    timestamp: System.currentTimeMillis().toString(),
    nonce    : UUID.randomUUID().toString().replace("-", "").take(16),
]

// 1. 按 key 字典序拼接
def raw = params.sort { it.key }
                .collect { k, v -> "${k}=${v}" }
                .join("&") + vars.get("SECRET")

// 2. MD5 后转大写
def sign = MessageDigest.getInstance("MD5")
        .digest(raw.getBytes("UTF-8"))
        .encodeHex().toString().toUpperCase()

// 3. 写回变量供请求引用
params.each { k, v -> vars.put(k, v) }
vars.put("sign", sign)

log.debug("签名原文=${raw}  sign=${sign}")
```

**用 JSR223 而不是函数的原因**：勾上「Cache compiled script」后脚本只编译一次，高并发下性能远好于 `__groovy()` 函数。

### `__V()` 处理正则提取的多个匹配结果

正则提取器设置 `匹配数字 = -1`（提取所有匹配）后，会生成：

```text
itemId_matchNr = 5
itemId_1 = 1001
itemId_2 = 1002
itemId_3 = 1003
itemId_4 = 1004
itemId_5 = 1005
```

随机取其中一个：

```text
${__V(itemId_${__Random(1,${itemId_matchNr})})}
```

拆解求值过程：

```text
1. ${itemId_matchNr}                    → 5
2. ${__Random(1,5)}                     → 3
3. 拼接得到字符串 "itemId_3"
4. __V("itemId_3") 二次求值             → 1003
```

**没有 `__V()` 就做不到这件事**，因为 `${itemId_${__Random(1,5)}}` 会被 JMeter 原样输出。

### 用 `__P()` 实现脚本环境无关

```text
用户定义变量：
  host      = ${__P(host,test-api.example.com)}
  threads   = ${__P(threads,50)}
  duration  = ${__P(duration,600)}
  dbUrl     = ${__P(dbUrl,jdbc:mysql://test-db:3306/shop)}
```

```bash
# 测试环境（用默认值）
jmeter -n -t order.jmx -l test.jtl

# 预发环境
jmeter -n -t order.jmx -l pre.jtl \
  -Jhost=pre-api.example.com \
  -JdbUrl=jdbc:mysql://pre-db:3306/shop \
  -Jthreads=200 -Jduration=1800
```

也可以把参数集中写进属性文件：

```text
# pre.properties
host=pre-api.example.com
threads=200
duration=1800
dbUrl=jdbc:mysql://pre-db:3306/shop
```

```bash
jmeter -n -t order.jmx -l pre.jtl -q pre.properties -e -o rpt/
```

`-q` 加载额外属性文件，比一长串 `-J` 清爽得多，也方便做环境配置版本管理。

### 中文参数编码

```text
# GET 请求 query 参数带中文
/search?keyword=${__urlencode(${keyword})}

# 双层编码（某些网关需要）
${__urlencode(${__urlencode(${keyword})})}
```

### 调试函数：先在函数助手对话框里试

GUI 里 `选项 → 函数助手对话框`，选函数、填参数、点「生成」，能直接看到求值结果和可复制的函数串。**写复杂函数前先在这里验证一遍**，比在脚本里反复跑快得多。

命令行环境下用 Debug Sampler 验证：

```text
线程组（1 线程 1 循环）
├── Debug Sampler
└── 察看结果树
```

或者用 JSR223 打日志：

```groovy
log.info("orderNo=" + vars.get("orderNo"))
log.info("当前线程=" + ctx.getThreadNum())
```

## 踩坑

1. **把函数写在用户定义变量里，所有线程拿到同一个值**。`orderNo = ${__Random(1000,9999)}` 在测试启动时求值一次就固定了，之后 200 个线程用的都是同一个订单号，唯一索引冲突，错误率 99%。**函数要写在使用它的地方**（请求 body、header 里），或者用 `__V()` 强制二次求值。

2. **同一个随机值在两处引用，结果不一致**。body 里 `${__UUID()}`、断言里也写 `${__UUID()}`，两次求值生成了两个不同的 UUID，断言永远失败。**用「最后一个参数存变量」的写法**：`${__UUID(,oid)}` 生成并存入 `oid`，后面用 `${oid}` 引用。

3. **`__counter(FALSE)` 在分布式压测下重复**。计数器是 JVM 级的，三台 slave 各有一份，都从 1 开始，生成的序号完全重复，主键冲突。**分布式场景加机器标识**：`${__machineIP()}-${__counter(TRUE)}`，或者直接用 `__UUID()`。

4. **`${${varName}}` 嵌套不生效**。JMeter 不支持这种写法，会原样输出字符串。**必须用 `${__V(user_${idx})}`。** 这个坑在处理正则多匹配结果时一定会遇到。

5. **`__time()` 精度不够导致重复**。`${__time(yyyyMMddHHmmss)}` 只精确到秒，高 TPS 下同一秒内有几百个请求，订单号大量重复。**至少精确到毫秒 `yyyyMMddHHmmssSSS`，并叠加随机数或线程号。**

6. **`__timeShift` 的偏移格式写错**。写成 `7D` 或 `+7d` 都不行，必须是 ISO-8601 的 `P7D`；小时要写 `PT1H` 而不是 `P1H`（时间部分必须有 `T` 前缀）。

7. **高频使用 `__groovy()` 拖垮压力机**。每次引用都重新编译执行 Groovy 脚本，在 500 TPS 下压力机 CPU 被脚本编译吃掉一半。**复杂逻辑用 JSR223 组件并勾选「Cache compiled script if available」。**

8. **`__P()` 没写默认值，取不到时变量为空**。`${__P(host)}` 在没传 `-Jhost` 时会得到空字符串，请求发到一个空域名，报 `Unknown host`。**永远写默认值 `${__P(host,localhost)}`。**

9. **中文参数忘了 `__urlencode`**。服务端收到乱码或者直接 400。GET 请求的 query 参数尤其容易漏。

10. **函数名大小写写错**。JMeter 函数名**区分大小写**：`__Random` 首字母大写，`__time` 全小写，`__counter` 全小写，`__UUID` 全大写。写成 `__random` 会原样输出 `${__random(1,100)}` 而不报错——请求里就带着这串字符发出去了，非常隐蔽。

11. **`__digest` 的参数顺序记错**。顺序是 `算法, 待加密串, salt, 是否大写, 变量名`。把 salt 和大写标志写反，得到的签名永远错。

## 面试怎么答

**Q：JMeter 里怎么保证每个请求的订单号唯一？**

A：分两种情况。

**单机压测**用「时间戳 + 随机数」：`PT${__time(yyyyMMddHHmmssSSS)}${__Random(100000,999999)}`。注意时间戳必须精确到毫秒，只到秒的话高 TPS 下同一秒内几百个请求会大量重复。

**分布式压测**必须加机器标识，因为 `__counter` 和随机数生成器都是 JVM 级的，多台 slave 会各自从头生成造成重复。写法是 `${__machineIP()}-${__time(yyyyMMddHHmmssSSS)}-${__threadNum()}-${__counter(TRUE)}`。

**最省事的方案是 `${__UUID()}`**，天然全局唯一，不需要考虑分布式问题。缺点是 36 个字符较长，且不携带业务语义，排查问题时看不出生成时间。

这里有个必须提的坑：**函数绝对不能写在「用户定义变量」里**。用户定义变量在测试启动时求值一次就固定了，把 `${__UUID()}` 写在里面，200 个线程从头到尾用的都是同一个 UUID，唯一索引直接冲突。函数必须写在实际使用它的位置——请求 body、header 或路径里。

**Q：`${__V()}` 函数是干什么用的？**

A：做**二次求值**，解决 JMeter 不支持 `${${varName}}` 嵌套引用的问题。

最典型的场景是处理正则提取器的多匹配结果。当提取器的「匹配数字」设为 -1 时，它会生成一组变量：`itemId_matchNr=5`、`itemId_1`、`itemId_2` 到 `itemId_5`。现在我想随机取其中一个，直觉写法是 `${itemId_${__Random(1,5)}}`，但 JMeter 会把它当成普通字符串原样输出。

正确写法是 `${__V(itemId_${__Random(1,${itemId_matchNr})})}`。求值过程是：先算内层的 `${itemId_matchNr}` 得到 5，再算 `${__Random(1,5)}` 得到比如 3，拼接成字符串 `itemId_3`，最后 `__V()` 把这个字符串当变量名再解析一次，得到实际值。

这个函数在做「从列表页随机选一个商品进详情页」这类真实用户行为模拟时是必需的——不能所有线程都点同一个商品，那样缓存命中率会虚高。

**Q：`__P()` 和 `__V()` 有什么区别？**

A：完全是两回事，只是名字容易混。

`__P(name, default)` 读的是 **JVM 属性**，也就是命令行 `-J` 传进来的参数，或者用 `__setProperty()` 设置的值。属性是**全局共享、跨线程组可见**的。它的主要用途是让脚本参数化——同一份 jmx 通过 `-Jhost=xxx -Jthreads=200` 跑不同环境和不同压力，不用改脚本。使用时永远要写默认值，否则取不到就是空字符串，会导致请求发到空域名这类难查的问题。

`__V(varName)` 是**二次求值函数**，处理的是**变量**（线程私有的 `vars`），作用是把拼接出来的字符串当作变量名再解析一遍，解决嵌套引用的问题。

一句话区分：`__P` 是「读全局配置」，`__V` 是「动态解析变量名」。

顺带说一下变量和属性的根本区别，这也是常考点：**变量 `${VAR}` 是线程私有的**，每个线程一份，跨线程组不可见；**属性 `${__P(NAME)}` 是 JVM 全局的**，所有线程共享同一份。所以跨线程组传 token 要用 `__setProperty` 转成属性，但反过来，每个用户不同的数据绝不能放属性里，否则所有线程会读到同一个值。

## 参考

- [JMeter Functions 官方文档](https://jmeter.apache.org/usermanual/functions.html)
- [JMeter 函数助手速查表](https://jmeter.apache.org/usermanual/functions.html#functions)
- 相关笔记：[[JMeter 参数化：CSV Data Set Config 与用户定义变量]]
- 相关笔记：[[JMeter 跨线程组传值]]
- 相关笔记：[[JMeter 关联：正则表达式提取器与 JSON 提取器]]
