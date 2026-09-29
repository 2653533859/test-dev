---
created: 2026-09-29
tags: [WebSocket测试/MOC, MOC]
---

# 14-WebSocket测试

实时双向全双工长连接测试全景。告别传统 HTTP 单向短连接思维，掌握现代即时通信、协同看板、金融行情及事件驱动系统的自动化测试与性能调优。

## 学习目标

- 深入理解 RFC 6455 规范：101 升级握手算法、二进制帧（Frame）布局与客户端掩码机制
- 熟练使用 `websocket-client` 与 `websockets` 异步协程搭建具备超时兜底的自动化用例
- 掌握全双工异步广播的事件流断言与滑动窗口缓冲设计，彻底解决 Flaky 偶发失败
- 建立心跳保活（Ping/Pong）、断线重连（指数退避）与 CSWSH 跨站劫持安全防护测试能力
- 掌握 JMeter 长连接两阶段压测模型（建连风暴与长连接持有）及单机内核调优

## 计划覆盖的知识点

- 协议原理：HTTP 101 Upgrade 升级握手、Sec-WebSocket-Key / Accept 计算签名、二进制帧（FIN/RSV/Opcode/Mask/Payload）
- 自动化测试：`websocket-client` 同步客户端封装、`websockets` 异步并发长连接、pytest fixture 会话生命周期
- 稳定性机制：TCP 半开连接、NAT 网关超时、Ping/Pong 协议帧、带抖动的指数退避重连算法
- 安全防护：握手期鉴权、Token 过期服务端踢下线、CSWSH（跨站 WebSocket 劫持）漏洞攻防、未授权频道越权订阅
- 异步断言：1 对 N 广播推送、无序消息到达、滑动窗口消息缓冲、谓词匹配器（Predicate Matcher）
- 性能压测：建连风暴与长连接持有双阶段模型、JMeter WebSocket Samplers 插件、施压机内核与系统句柄参数调优

## 笔记索引

### 1、协议底层原理
- [[WebSocket 协议原理与数据帧结构]] —— 101 Upgrade 握手、RFC 6455 二进制帧布局与客户端掩码异或机制，配完整生命周期图

### 2、自动化框架与实战
- [[Python WebSocket 自动化测试实战]] —— websocket-client 同步封装、websockets 异步并发与 pytest fixture 生命周期集成
- [[WebSocket 广播推送与异步断言设计]] —— 1 对 N 广播场景、滑动窗口消息缓冲、谓词匹配器与防 Flaky 策略

### 3、稳定性与心跳保活
- [[WebSocket 心跳保活与断线重连机制测试]] —— Ping/Pong 协议帧、半开连接检测、网络损伤注入与指数退避重连

### 4、安全与权限防护
- [[WebSocket 鉴权与安全防护测试]] —— 握手期鉴权、Token 过期实时踢人、CSWSH 跨站劫持攻防与水平越权订阅校验

### 5、性能压测与调优
- [[WebSocket 性能压测与 JMeter 落地]] —— 建连风暴与长连接持有双阶段模型、JMeter 插件实战与单机万级并发内核调优

## 常考点

- WebSocket 握手阶段与数据传输阶段分别走什么协议，为什么说它脱离了 HTTP
- 为什么客户端发给服务端的帧必须做掩码（Mask）混淆，而服务端推流不用
- 客户端意外断网（如拔掉网线或进电梯），服务端在不发消息的情况下如何感知连接已死
- 针对异步推流和无序消息到达，自动化测试用例如何设计才能避免偶发 Flaky 失败
- 什么是 CSWSH（跨站 WebSocket 劫持）？为什么同源策略（SOP）无法防御该漏洞
- WebSocket 压测与普通 HTTP 压测的核心区别是什么？施压机单机并发受哪些操作系统参数制约

## 动态索引 (Dataview)

> 若在 Obsidian 中安装了 Dataview 插件，下方将自动渲染本模块笔记清单：

```dataview
TABLE file.mtime as "最后修改", tags as "分类标签"
FROM "14-WebSocket测试"
WHERE file.name != "14-WebSocket测试"
SORT file.name ASC
```

## 参考

- RFC 6455 规范官方文档：`https://datatracker.ietf.org/doc/html/rfc6455`
- 相关笔记：[[03-计算机网络]]、[[05-自动化测试框架]]、[[06-接口自动化测试]]、[[09-性能测试-JMeter]]、[[10-安全测试]]
