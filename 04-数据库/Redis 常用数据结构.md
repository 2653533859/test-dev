---
created: 2026-07-31
tags: [数据库/Redis]
---

# Redis 常用数据结构

## 概念

Redis 是内存 KV 数据库，value 支持多种数据结构。测开常和它打交道是因为**缓存层几乎都用 Redis**，懂结构才能设计缓存 key、评估大 key、判断缓存命中。五种最常用结构：

| 结构 | 特点 | 典型用途 |
| --- | --- | --- |
| String | 最基础，存字符串/数字，支持自增 | 缓存值、计数器、分布式锁 |
| Hash | 字段-值映射，适合存对象 | 用户信息、商品属性 |
| List | 有序双向链表，可两端推拉 | 消息队列、最新列表 |
| Set | 无序去重集合，支持交并差 | 标签、共同好友、去重 |
| ZSet（有序集合） | 带 score 排序，按分排行 | 排行榜、延迟队列 |

底层还有 `HyperLogLog`（基数统计）、`Bitmap`（位图签到）、`Geo`（地理位置）等扩展结构，按需了解。

### 底层编码：同一种结构有多种实现

Redis 对每种数据结构会根据**元素数量和大小**自动选择底层编码，理解这一点才能解释「为什么数据量小很快、大了突然变慢」。常见编码对应关系：

| 结构 | 小数据编码 | 大数据编码 | 切换阈值 |
| --- | --- | --- | --- |
| String | int（纯数字）/ embstr | raw | embstr 在 44 字节内，超了转 raw |
| Hash | listpack（7.0+，原 ziplist） | hashtable | 元素超 128 或单个值超 64 字节 |
| List | listpack（7.0+，原 quicklist+ziplist） | quicklist（节点内 listpack） | 元素超 128 或单个值超 64 字节 |
| Set | intset（全整数） | hashtable | 元素超 512 或含非整数 |
| ZSet | listpack（7.0+，原 ziplist） | skiplist + hashtable | 元素超 128 或单个值超 64 字节 |

几个关键编码的原理：

- **SDS（Simple Dynamic String）**：String 的底层不是 C 字符串，而是 SDS——头部记录长度，`O(1)` 取 `strlen`，二进制安全（不靠 `\0` 判结束），空间预分配减少频繁 realloc。
- **listpack**：紧凑的连续内存结构，小数据时省内存且访问快。Redis 7.0 用 listpack 替换了 ziplist（ziplist 有「连锁更新」的性能陷阱：中间元素扩张会引发后续元素 cascading relocate）。
- **intset**：全整数集合的紧凑数组，有序存储支持二分查找，省内存；插入非整数或超阈值升级为 hashtable。
- **dict（hashtable）**：渐进式 rehash——扩容时不一次性搬全表（会阻塞），而是每次操作搬一小桶，分摊到后续请求中。
- **skiplist（跳跃表）**：ZSet 大数据时的核心结构，多层链表实现 `O(logN)` 查找和范围扫描，比红黑树更易实现且范围操作高效；ZSet 同时用 hashtable 保存 member→score 映射，保证单点查找 `O(1)`。

用 `OBJECT ENCODING key` 可以查看某个 key 的实际编码，测试大 key 性能时务必关注编码是否已从紧凑型升级到 hashtable/skiplist。

## 用法

### String：缓存与计数

```bash
SET user:1001 "{name:'A',age:20}" EX 3600      # 缓存用户，1小时过期
GET user:1001
INCR article:views:1001                          # 阅读量 +1
SET lock:order:1001 1 EX 10 NX                   # 简易分布式锁（NX=不存在才设，EX=过期）
```

### Hash：存对象字段

```bash
HSET user:1001 name "A" age 20
HGET user:1001 name
HGETALL user:1001
```

### ZSet：排行榜

```bash
ZADD rank:game 100 userA 200 userB 150 userC
ZREVRANGE rank:game 0 2 WITHSCORES     # 前三名（高分在前）
ZRANK rank:game userC                  # userC 的排名
```

### 测试常用：构造缓存命中/未命中

```bash
# 造一个缓存命中场景
SET cache:product:888 "{price:99}" EX 60
# 模拟缓存过期
TTL cache:product:888
EXPIRE cache:product:888 1
# 等待后触发回源
```

## 踩坑

1. **key 无限膨胀不设置过期**：缓存只 `SET` 不 `EXPIRE`，内存被撑满触发 `maxmemory` 淘汰甚至 OOM。任何缓存 key 都要有 TTL。
2. **大 key 拖垮性能**：单个 String 几 MB、Hash/List 几十万元素，序列化/删除都会阻塞。控制单 key 大小，列表分页拆分。
3. **热 key 集中打爆单节点**：某个爆款商品 key 极高 QPS 落在同一分片。用本地缓存 + 多副本/分散 key 兜底。
4. **`DEL` 大 key 阻塞主线程**：百万级元素的 key 直接 `DEL` 会长时间卡住。用 `UNLINK`（异步删除）替代。
5. **分布式锁只 `SETNX` 不设过期**：拿到锁的进程崩了，锁永不释放。必须 `SET key val EX t NX` 一步到位带过期。
6. **锁过期但业务没执行完（锁误删）**：A 的锁到期释放，B 拿到锁，A 完成后误删了 B 的锁。用唯一 value + `Lua` 脚本「校验 value 再删」保证只删自己的。
7. **用了错误的数据结构**：把对象硬塞进 String 每次整体读写，改一个字段也要全量序列化。多字段对象用 Hash 局部更新更高效。
8. **缓存与数据库双写不一致**：先更缓存再更 DB 或反之都可能脏，需明确策略（详见 [[缓存与数据库一致性及测试点]]）。
9. **`EXPIRE` 精度与「过期即删」误区**：Redis 过期是惰性+定期删除，key 到点不会瞬间消失，极端情况下过期后短暂仍可读。一致性测试别假设「到点立刻无」。
10. **混淆 `INCR` 与字符串自增**：对 `SET k "100"` 再 `INCR` 可行，但若存的是 JSON 字符串则 `INCR` 报错。计数场景用独立 String key。

## 面试怎么答

**Q：Redis 常用数据结构有哪些，分别用在什么场景？**
A：String（缓存值/计数/锁）、Hash（对象属性）、List（队列/最新列表）、Set（去重/标签）、ZSet（排行榜/延迟队列）。选结构的核心是「读写模式匹配」——要排序用 ZSet，要字段级更新用 Hash，要计数用 String 的 `INCR`。

**Q：什么是大 key、热 key，怎么处理？**
A：大 key 是单个 value 过大（如巨型 Hash/List），删除和序列化会阻塞；热 key 是单 key 极高并发。大 key 靠拆分、分批 `UNLINK`；热 key 靠本地缓存、多副本、key 打散。

**Q：Redis 做分布式锁要点？**
A：用 `SET key val EX t NX` 原子加锁并带过期，避免死锁；释放锁用 Lua 脚本校验 value 后删除，避免误删别人的锁；业务耗时可能超锁过期时要做续期（看门狗）。

## 参考

- [Redis 官方文档：数据类型](https://redis.io/docs/data-types/)
- [Redis 官方文档：数据类型底层数据结构](https://redis.io/docs/reference/internals/data-types/)
- [Redis 官方文档：分布式锁（Redlock）](https://redis.io/docs/manual/patterns/distributed-locks/)
- [[缓存穿透、击穿与雪崩]] —— 三大问题与 Redis 缓存设计
- [[缓存与数据库一致性及测试点]] —— 缓存与 DB 双写的测试点
- [[数据库测试数据构造与清理策略]] —— 测试数据管理思路
