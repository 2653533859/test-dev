---
created: 2026-07-31
tags: [计算机网络/渲染链路]
---

# 从输入 URL 到页面渲染的完整链路

> 这是计算机网络知识最终落到「前端可观测」的地方。把前面所有知识点串成一条线：DNS → TCP → TLS → HTTP → 浏览器渲染。面试被问「中间发生了什么」，这就是标准答案骨架。

![[assets/url-to-render.svg]]
*图示：从回车到绘制的完整链路，每一跳对应前面讲过的某一个知识点。*

## 概念

### 完整链路（自上而下九步）

```text
① 浏览器地址栏输入 URL，做 URL 解析（协议/主机/路径/片段）
        ↓
② DNS 解析：查缓存 → hosts → 递归解析器 → 权威，拿到服务器 IP
        ↓
③ TCP 三次握手：与服务器建立可靠连接（详见 TCP 笔记）
        ↓
④ TLS 握手：协商对称密钥，建立加密通道（详见 HTTPS 笔记）
        ↓
⑤ 发送 HTTP 请求：带上 Cookie / Token / 各种头（详见 HTTP 报文笔记）
        ↓
⑥ 服务器处理：可能经反向代理 → 后端 → 数据库，返回 HTTP 响应
        ↓
⑦ 浏览器接收响应，做 MIME 嗅探，决定怎么处理（下载 / 渲染）
        ↓
⑧ 解析 HTML：构建 DOM 树；并发请求 CSS / JS / 图片（受同源/CORS 限制）
        ↓
⑨ 渲染：Style → Layout → Paint → Composite，像素上屏
```

### 每一步对应前面哪个知识点

| 链路环节 | 对应笔记 |
|---------|---------|
| ② DNS | [[DNS 解析过程与 CDN 对测试的影响]] |
| ③ TCP 握手 | [[TCP 三次握手与四次挥手]]、[[TCP 可靠传输与滑动窗口]] |
| ④ TLS | [[HTTPS 加密原理与 TLS 握手过程]]、[[HTTPS 证书链与抓包为什么要装根证书]] |
| ⑤ 发请求 | [[HTTP 报文结构与请求方法]]、[[HTTP 常见请求头与响应头]] |
| ⑧ CSS/JS 加载 | [[跨域与 CORS]]、[[Cookie、Session、Token 与 JWT 的区别与适用场景]] |
| 代理层 | [[正向代理与反向代理]]、[[抓包工具选型：Wireshark、Fiddler、Charles 与 mitmproxy]] |

## 用法

### 用 Performance API 亲手测「各阶段耗时」

```javascript
// 在页面里跑，看清导航各阶段时间戳
const [entry] = performance.getEntriesByType("navigation");
console.log({
  start: entry.startTime,
  dns: entry.domainLookupEnd - entry.domainLookupStart,   // 对应链路第 ② 步
  tcp: entry.connectEnd - entry.connectStart,            // 第 ③ 步
  ssl: entry.secureConnectionStart,                      // 第 ④ 步（HTTPS 才有）
  ttfb: entry.responseStart - entry.requestStart,        // 第 ⑥ 步（首字节）
  dom: entry.domInteractive - entry.domLoading,          // 第 ⑧ 步
  load: entry.loadEventEnd - entry.startTime,            // 第 ⑨ 步完成
});
```

### 用 curl + tcpdump 复现「前两跳」

```bash
# 终端 1：抓 DNS + TLS 握手
sudo tcpdump -i any -w /tmp/nav.pcap "host api.internal and (port 53 or 443)"

# 终端 2：发起一次完整请求（相当于链路 ②→⑥）
curl -w @- -o /dev/null https://api.internal/health <<'EOF'
DNS:    %{time_namelookup}s
TCP:    %{time_connect}s
TLS:    %{time_appconnect}s
TTFB:   %{time_starttransfer}s
总耗时: %{time_total}s
EOF
```

### 用 Chrome DevTools 看「渲染」这一步

```text
# Network 面板里点任意请求 → Timing 标签，直接看到：
#   Queueing → Stalled → DNS Lookup → Initial connection
#   → SSL → Request sent → Waiting (TTFB) → Download → 渲染
# 和上面的链路一一对应
```

## 踩坑

1. **「白屏 3 秒」不知道卡在哪一跳**。先按上面 `curl -w` 拆开看：`time_namelookup` 大就是 DNS 慢；`time_connect` 大是 TCP 握手/网络延迟；`time_appconnect` 大是 TLS 握手贵；`time_starttransfer` 大是后端处理慢（TTFB）。一层层剥，比瞎猜快。

2. **本地改了 hosts，但浏览器还在用缓存的 DNS**。和前面 DNS 笔记里讲的一样，先 `dscacheutil -flushcache`（macOS）或 `ipconfig /flushdns`（Windows），否则你以为解析改了，其实浏览器还没重新查。

3. **TTFB 很高但后端很快**。中间那一段（反向代理、CDN、网关）拖慢了首字节。排查链路 ④→⑥ 之间的每一跳：TLS 终止、代理转发、内部服务网格（Service Mesh）的 sidecar 开销，都算在 TTFB 里。

4. **CDN 缓存让「改了源站前端没变」**。链路第 ⑥ 步返回的是 CDN 边缘的缓存，源站改了页面，用户要等缓存过期才看得到。用 `Cache-Control: no-cache` 或绕过 CDN 直连源站，才能确认是「源站的问题」还是「缓存的假象」。

5. **`SameSite` Cookie 跨站不带，导致「第 ⑧ 步 CSS/JS 加载时没登录态」**。前端跨域加载资源时，如果资源域名和页面域名不同，`SameSite=Lax` 的 Cookie 不会随子资源请求带过去，后端看到的是「匿名用户」，表现形式像「静态资源 403」。这是链路后半段最容易和 CORS 混淆的地方。

6. **代理层把「真实客户端 IP」藏了**。链路第 ③/④ 步经反向代理后，后端拿到的 `$remote_addr` 是代理 IP。要还原真实用户 IP，得靠 `X-Forwarded-For`（见反向代理笔记），否则风控、限流、审计全建立在错误的身份上。

## 面试怎么答

**Q：从输入 URL 到页面渲染，中间发生了什么？**

A：九步——**URL 解析 → DNS 解析拿 IP → TCP 三次握手建连 → TLS 握手协商密钥 → 发 HTTP 请求（带 Cookie/Token/头）→ 服务端经反向代理处理返回响应 → 浏览器 MIME 嗅探决定如何处理 → 解析 HTML 并发请求 CSS/JS/图片 → 渲染上屏**。每一步都能展开讲坑：DNS 看缓存与 hosts、TCP 看重传与窗口、TLS 看证书链与握手 RTT、HTTP 看头部与状态码、渲染看 Layout/Paint/Composite。

**Q：哪一步最容易被忽略但最关键？**

A：**第 ④ 步 TLS 握手**。很多人把「HTTPS 慢」简单归咎于加密开销，其实大头在握手 RTT（TLS 1.2 要 2-RTT，跨地域可能占总耗时近半）。优化思路是升级 TLS 1.3（1-RTT，会话复用 0-RTT）、开启会话复用（Session Resumption）、或用 HTTP/2 多路复用省掉反复握手。

**Q：为什么有时候「页面秒开」但「接口很慢」？**

A：因为**渲染链路和接口链路是两条独立的路径**。页面秒开靠的是 CDN 边缘缓存（链路第 ⑥ 步直接被边缘接住），而接口慢是后端处理（同一步里真实的计算）。两者在 DevTools 里表现为：DOMContentLoaded 很快、但某个 fetch 的 TTFB 很高——正是「前端到了、后端没到」的典型现场。

## 参考

- [浏览器渲染原理（HTML/CSS/JS 解析顺序）](https://developers.google.com/web/updates/2018/09/inside-browser-part1)
- [Navigation Timing API 规范](https://w3c.github.io/navigation-timing/)
- 相关笔记：[[DNS 解析过程与 CDN 对测试的影响]]、[[HTTPS 加密原理与 TLS 握手过程]]、[[TCP 三次握手与四次挥手]]
