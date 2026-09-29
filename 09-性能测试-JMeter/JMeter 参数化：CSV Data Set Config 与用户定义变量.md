---
created: 2026-07-31
tags: [性能测试/参数化]
---

# JMeter 参数化：CSV Data Set Config 与用户定义变量

> 100 个线程都用同一个账号下单，压出来的是「行锁竞争」而不是系统真实性能。**参数化不是为了让脚本好看，是为了让压力模型不失真。**

## 概念

### 为什么必须参数化

不参数化会造成三类严重的失真：

1. **数据库行锁竞争**：100 个线程改同一条用户记录，全部串行等锁。你测到的是锁竞争极限，不是业务处理能力。
2. **缓存命中率虚高**：所有请求查同一个商品 ID，第一次之后全部命中缓存，TPS 高得离谱。生产环境的缓存命中率可能只有 60%，压测显示 99%。
3. **唯一键冲突**：注册接口用同一个手机号，第二个请求开始全部报「已存在」，错误率 99%。

**参数化的目标不是「让数据不一样」，而是「让数据的分布接近生产」。**

### 四种参数化方式对比

| 方式 | 数据来源 | 特点 | 适用 |
|------|----------|------|------|
| 用户定义变量 | 脚本内写死 | 全局常量，所有线程相同 | 环境地址、固定配置 |
| CSV Data Set Config | 外部 CSV 文件 | **每线程取不同行**，可控性最好 | 账号、商品 ID 等真实数据 |
| 函数助手 | 运行时生成 | `__Random`、`__time`、`__UUID` | 随机数、时间戳、唯一 ID |
| JDBC PreProcessor | 从数据库实时查 | 数据永远是新鲜的 | 需要真实关联数据时 |

实践里最常用的是 **CSV + 函数助手组合**：CSV 提供真实的账号密码，函数生成唯一的订单号和随机的数量。

### 用户定义变量（User Defined Variables）

本质是**全局常量**，在测试开始时求值一次，所有线程读到同一份。

```text
host       = ${__P(host,api.example.com)}
version    = v1
order_src  = PERF_TEST
```

**关键限制：它不是「每线程一份」，也不会在运行中变化。** 想让每个线程拿不同的值，用户定义变量做不到，必须用 CSV 或函数。

它最大的价值是**配合 `__P()` 做环境隔离**：

```text
host = ${__P(host,test.example.com)}
```

```bash
# 测试环境
jmeter -n -t order.jmx -Jhost=test.example.com
# 预发环境
jmeter -n -t order.jmx -Jhost=pre.example.com
```

### CSV Data Set Config 的核心机制

**每个线程每轮循环从 CSV 里读一行**，读到的值绑定到指定变量名。

```text
文件名          user.csv（推荐用相对路径）
文件编码        UTF-8
变量名称        username,password,userId
忽略首行        True（CSV 有表头时必须）
分隔符          ,
遇到文件结束再次循环?  Recycle on EOF
遇到文件结束停止线程?  Stop thread on EOF
线程共享模式    Sharing mode
```

### Sharing mode（共享模式）—— 最重要也最容易错的配置

| 模式 | 行为 | 场景 |
|------|------|------|
| All threads（默认） | **所有线程组的所有线程共用一个读取指针** | 每条数据只被用一次（如注册手机号） |
| Current thread group | 该线程组内的线程共用一个指针 | 多线程组各用各的数据 |
| Current thread | **每个线程独立从头读整个文件** | 每个线程都要遍历全部数据 |

**默认的 All threads 是最常用的**：100 个线程排队从文件里取行，线程 1 取第 1 行、线程 2 取第 2 行……天然实现了「每个虚拟用户一个账号」。

**Current thread 是个陷阱**：每个线程都从第一行开始读，结果 100 个线程全部读到第 1 行——和不参数化没区别。

### Recycle on EOF vs Stop thread on EOF

这两个开关的组合决定了数据用完时的行为：

| Recycle | Stop thread | 数据用完时 | 适用 |
|---------|-------------|-----------|------|
| True | False | **回到文件开头循环读** | 长时间压测（默认选这个） |
| False | True | 线程结束 | 数据必须唯一且用完就停 |
| False | False | 变量值变成 `<EOF>` | **危险，几乎永远不要** |

**`Recycle=False, Stop=False` 是最阴的一种配置**：数据用完后变量不报错，而是被赋值成字符串 `<EOF>`，请求带着 `username=<EOF>` 继续发，服务端返回 404/400，但脚本一切「正常」。压了 8 小时，前 20 分钟数据有效，后面全是垃圾。

**长时间压测必须 `Recycle=True`**。但要注意：Recycle 会导致数据重复使用，如果是注册这类要求唯一的接口，就不能 recycle，而应该准备足够多的数据或改用函数生成。

## 用法

### 准备 CSV 数据文件

```text
username,password,userId
perf_user_0001,Test@123,100001
perf_user_0002,Test@123,100002
perf_user_0003,Test@123,100003
```

**数据量的经验法则**：

```text
所需数据行数 = 线程数 × (压测时长 / 单轮耗时) 
```

如果不 recycle，200 线程压 30 分钟、单轮 3 秒，需要 `200 × (1800/3) = 12 万行`。这通常不现实，所以大多数情况会开 recycle，但要保证**数据量至少 ≥ 线程数**，让每个线程拿到不同的初始数据。

用 Python 快速造数据：

```python
"""生成压测账号 CSV。"""
import csv

ROWS = 5000
with open("user.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["username", "password", "userId"])
    for i in range(1, ROWS + 1):
        # 用固定前缀打标，方便事后从库里精确清理
        w.writerow([f"perf_user_{i:06d}", "Test@123", 100000 + i])
print(f"已生成 {ROWS} 行")
```

配套的清理 SQL（压测数据必须能被精确定位）：

```sql
-- 事后清理：靠固定前缀锁定压测账号产生的数据
DELETE FROM t_order
WHERE user_id IN (
    SELECT id FROM t_user WHERE username LIKE 'perf\_user\_%' ESCAPE '\'
);
```

### CSV Data Set Config 配置（jmx）

```xml
<CSVDataSet guiclass="TestBeanGUI" testname="账号数据" enabled="true">
  <!-- 相对路径基准是「jmx 文件所在目录」，分布式压测时每台机器都要有这个文件 -->
  <stringProp name="filename">data/user.csv</stringProp>
  <stringProp name="fileEncoding">UTF-8</stringProp>
  <stringProp name="variableNames">username,password,userId</stringProp>
  <!-- CSV 带表头时必须为 true，否则第一行表头会被当数据用掉 -->
  <boolProp name="ignoreFirstLine">true</boolProp>
  <stringProp name="delimiter">,</stringProp>
  <boolProp name="quotedData">false</boolProp>
  <!-- 长时间压测：循环读取 -->
  <boolProp name="recycle">true</boolProp>
  <boolProp name="stopThread">false</boolProp>
  <!-- shareMode: all / group / thread -->
  <stringProp name="shareMode">shareMode.all</stringProp>
</CSVDataSet>
```

在请求里引用：

```xml
<stringProp name="Argument.value">{"username":"${username}","password":"${password}"}</stringProp>
```

### 用户定义变量：环境与常量集中管理

```xml
<Arguments guiclass="ArgumentsPanel" testname="全局配置" enabled="true">
  <collectionProp name="Arguments.arguments">
    <elementProp name="host" elementType="Argument">
      <stringProp name="Argument.name">host</stringProp>
      <!-- 命令行 -Jhost=xxx 可覆盖，不传则用默认值 -->
      <stringProp name="Argument.value">${__P(host,test-api.example.com)}</stringProp>
    </elementProp>
    <elementProp name="apiVersion" elementType="Argument">
      <stringProp name="Argument.name">apiVersion</stringProp>
      <stringProp name="Argument.value">v1</stringProp>
    </elementProp>
    <elementProp name="orderSource" elementType="Argument">
      <stringProp name="Argument.name">orderSource</stringProp>
      <stringProp name="Argument.value">PERF_TEST</stringProp>
    </elementProp>
  </collectionProp>
</Arguments>
```

### 混合参数化：CSV + 函数

真实的下单请求通常需要三类数据：

```text
{
  "username": "${username}",                      ← CSV：真实账号
  "orderNo":  "PT${__time(yyyyMMddHHmmss)}${__Random(1000,9999)}",  ← 函数：唯一订单号
  "skuId":    "${skuId}",                         ← CSV：真实商品
  "num":      ${__Random(1,5)},                   ← 函数：随机数量
  "source":   "${orderSource}"                    ← 用户定义变量：常量标记
}
```

这样既保证了**数据真实性**（账号和商品来自真实数据），又保证了**唯一性**（订单号不冲突），还保留了**可清理性**（source 字段打标）。

### 多线程组的数据隔离

三个线程组分别压不同业务，各用各的数据：

```text
测试计划
├── 线程组-首页浏览
│   └── CSV: browse_user.csv （shareMode = Current thread group）
├── 线程组-搜索
│   └── CSV: keyword.csv     （shareMode = Current thread group）
└── 线程组-下单
    └── CSV: order_user.csv  （shareMode = Current thread group）
```

**每个 CSV 挂在各自线程组下 + shareMode 设为 Current thread group**，这样三组数据完全隔离，互不干扰。

如果都挂在测试计划下用默认的 All threads，三个线程组会抢同一份数据（如果文件名相同的话），或者虽然文件不同但作用域覆盖全局，容易在后期维护时出乱子。

### 验证参数化是否真的生效

调试阶段用 Debug Sampler + 察看结果树：

```text
线程组（2 线程，2 循环，用于调试）
├── CSV Data Set Config
├── Debug Sampler          ← 输出当前所有变量的值
└── 察看结果树
```

或者用 JSR223 打日志（这种方式在命令行调试时更实用）：

```groovy
// JSR223 PostProcessor
log.info("线程=${ctx.getThreadNum()} 循环=${vars.getIteration()} " +
         "username=${vars.get('username')} userId=${vars.get('userId')}")
```

跑 2 线程 2 循环，日志应该显示 4 个不同的 username。如果 4 个都一样，说明 shareMode 配错了。

### 分布式压测时的 CSV 分发

分布式压测下，**每台 slave 机器都需要一份 CSV 文件**，且路径要一致。

两种策略：

**策略一：全量复制（简单，但数据会重复）**

```bash
# 每台 slave 都放同一份完整文件
for host in 10.0.1.11 10.0.1.12 10.0.1.13; do
  scp -r data/ "user@${host}:/opt/jmeter/data/"
done
```

三台机器都从第 1 行开始读，会出现重复账号。

**策略二：切分文件（推荐，数据不重复）**

```bash
#!/bin/bash
# split-csv.sh：把 user.csv 按 slave 数量切分并分发
SLAVES=(10.0.1.11 10.0.1.12 10.0.1.13)
N=${#SLAVES[@]}

# 保留表头，把数据行均分成 N 份
head -1 user.csv > /tmp/header.txt
tail -n +2 user.csv | split -n "l/${N}" - /tmp/part_

i=0
for f in /tmp/part_*; do
  cat /tmp/header.txt "$f" > "/tmp/user_${i}.csv"
  scp "/tmp/user_${i}.csv" "user@${SLAVES[$i]}:/opt/jmeter/data/user.csv"
  i=$((i + 1))
done
echo "已切分并分发到 ${N} 台压力机"
```

## 踩坑

1. **`Recycle=False, Stop thread=False` 导致变量变成 `<EOF>`**。数据用完后请求带着 `username=<EOF>` 继续发，服务端返回 400，但压测「正常」跑完。看报告时错误率 80% 才发现，8 小时白压。**长跑必须 `Recycle=True`。**

2. **shareMode 设成 Current thread，所有线程读到同一行**。每个线程独立从头读，结果 100 个线程全用第 1 行的账号——参数化等于没做。

3. **忘了勾「忽略首行」，表头被当数据用掉**。第一个线程拿到的 `username` 是字符串 `"username"`，登录失败。CSV 带表头时 `ignoreFirstLine` 必须为 true。

4. **CSV 文件编码不对，中文乱码**。Excel 另存为 CSV 默认是 GBK/ANSI，JMeter 按 UTF-8 读会乱码。**用文本编辑器另存为 UTF-8（无 BOM）**，或者在 JMeter 里把 fileEncoding 设成 GBK。

5. **UTF-8 带 BOM，第一个字段值前面多了不可见字符**。表现极其诡异：`username` 明明看着一样但登录就是失败。用 `head -c 3 user.csv | xxd` 看是不是 `efbbbf`。

6. **CSV 用了绝对路径，分布式压测时 slave 找不到文件**。`D:\data\user.csv` 在 Linux slave 上不存在。**用相对路径**（相对于 jmx 所在目录），并保证每台 slave 都有对应文件。

7. **数据量小于线程数**。CSV 只有 50 行但开了 200 线程，且 recycle=true，那么线程 51~200 会和前 50 个用重复账号，重新引入行锁竞争。**数据量至少要 ≥ 线程数。**

8. **用户定义变量以为是「每线程一份」**。想用它做参数化，发现所有线程值都一样。用户定义变量是全局常量，参数化要用 CSV 或函数。

9. **CSV 里有引号但没勾 `Allow quoted data`**。字段值是 `"北京, 朝阳区"`（含逗号），不勾引号支持时会被逗号切成两个字段，后面所有列全部错位。

10. **注册接口用了 recycle**。手机号第二轮开始全部重复，报「已注册」，错误率 100%。**唯一性接口不能 recycle**，要么准备足够多数据，要么用 `__time` + `__Random` 或 `__UUID` 动态生成。

11. **压测数据没打标，事后清理困难**。生成账号时用了 `zhangsan001` 这种看起来像真实用户的名字，压完发现无法从库里区分。**永远用固定前缀，如 `perf_user_`。**

12. **CSV 文件太大导致内存问题**。JMeter 的 CSV Data Set 是流式读取的，理论上不占内存，但如果你误用了 `__CSVRead` 函数，它会把整个文件读进内存。百万行的 CSV 会直接把堆吃满。

## 面试怎么答

**Q：JMeter 有哪些参数化方式，怎么选？**

A：主要四种：

**用户定义变量**——全局常量，测试开始时求值一次，所有线程共享同一份。适合环境地址、API 版本、固定标记这类不变的配置。配合 `${__P(host,default)}` 可以让命令行 `-Jhost=xxx` 覆盖，实现一套脚本多环境运行。

**CSV Data Set Config**——从外部文件按行读取，每个线程每轮取一行。这是最主要的参数化方式，适合账号密码、商品 ID 这类需要真实数据的场景，可控性最好，数据也能提前在数据库里准备好。

**函数助手**——运行时动态生成，`__Random` 生成随机数、`__time` 生成时间戳、`__UUID` 生成唯一 ID、`__counter` 生成递增序号。适合订单号这类要求唯一但不需要真实性的字段。

**JDBC PreProcessor**——压测过程中实时从数据库查数据。适合需要保证数据状态正确的场景（比如必须查「未支付」状态的订单去支付），但会给数据库额外增加压力，要谨慎用。

实际项目里通常是**组合使用**：CSV 提供真实账号和商品，函数生成唯一订单号，用户定义变量提供环境地址和压测标记。

**Q：CSV Data Set Config 的 Sharing mode 有什么区别？**

A：三种模式决定了「读取指针是谁的」：

**All threads（默认）**——所有线程组的所有线程**共用一个读取指针**。线程 1 取第 1 行，线程 2 取第 2 行，依次往下。这是最常用的，天然实现「一个虚拟用户一个账号」。

**Current thread group**——同一线程组内的线程共用指针，不同线程组各有各的指针。适合多线程组各压各的业务、各用各的数据。

**Current thread**——**每个线程独立地从文件第一行开始读**。这是个陷阱选项：100 个线程全部读到第 1 行，参数化等于白做。它的合法用途很窄，比如每个线程都需要完整遍历一遍数据集。

配套还要注意 EOF 行为：`Recycle on EOF=True` 表示数据读完回到开头循环，长时间压测必须开；如果两个开关都是 False，数据用完后变量会被赋值成字符串 `<EOF>`，请求照发不误，服务端返回错误，但脚本本身不报任何问题——这是最难发现的一种失败，压完 8 小时才发现后 7 小时的数据全是垃圾。

**Q：为什么压测一定要参数化，不参数化会怎样？**

A：不参数化会让压力模型严重失真，主要三个后果：

**第一，数据库行锁竞争。** 100 个线程改同一条用户记录或同一个商品库存，全部串行等行锁。你测出来 TPS 只有 20，会以为系统性能差，实际上是自己制造的锁竞争，生产环境流量分散在几万个用户上根本不会这样。

**第二，缓存命中率虚高。** 所有请求查同一个商品 ID，第一次之后 100% 命中缓存，数据库压力几乎为零，TPS 高得离谱。而生产环境缓存命中率可能只有 60%，剩下 40% 要打到数据库。用这个压测结果去做容量规划，上线必挂。

**第三，唯一约束冲突。** 注册、下单这类接口有唯一索引，同一份数据第二次提交就报错，错误率飙到 99%，压测根本跑不下去。

所以参数化的本质目标不是「让数据看起来不一样」，而是**让数据的分布特征接近生产**。这也意味着数据量要够（至少 ≥ 线程数）、数据要真实（从生产脱敏导出比随机生成更好）、热点分布要匹配（如果生产上 20% 的商品占了 80% 流量，压测数据也应该有这个倾斜，而不是完全均匀）。

## 参考

- [JMeter CSV Data Set Config 文档](https://jmeter.apache.org/usermanual/component_reference.html#CSV_Data_Set_Config)
- [JMeter User Defined Variables 文档](https://jmeter.apache.org/usermanual/component_reference.html#User_Defined_Variables)
- 相关笔记：[[JMeter 函数助手常用函数]]
- 相关笔记：[[JMeter 关联：正则表达式提取器与 JSON 提取器]]
- 相关笔记：[[JMeter 组件执行顺序与作用域]]
- 相关笔记：[[JMeter 分布式压测]]
