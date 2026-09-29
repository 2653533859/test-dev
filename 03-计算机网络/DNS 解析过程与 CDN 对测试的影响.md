---
created: 2026-07-31
tags: [计算机网络/DNS]
---

# DNS 解析过程与 CDN 对测试的影响

> 一次 HTTPS 请求的第一公里永远是 DNS：「www.example.com 到底连到哪个 IP？」理解解析链，你才能在「测试环境连错机器」「CDN 回源串流」「hosts 改了不生效」这种问题里一秒定位。

![[assets/dns-resolution.svg]]
*图示：从浏览器到权威 DNS，再到 CDN 边缘节点，完整解析链一览。*

## 概念

### 一次查询经历了哪几跳

你输入域名到拿到 IP，通常经过（可能合并、可能跳过，但逻辑上是这几层）：

```text
① 浏览器缓存 / 系统 hosts        ← 最先查，最快，但最容易被忘记
② 本地 DNS 解析器（Stub Resolver） ← 如 192.168.1.1 / 公共 DNS 8.8.8.8
③ 递归解析器（Resolver）          ← 你运营商或公司网络的 DNS 服务器
④ 根 DNS（.）                     ← 只返回「.com 该问谁」
⑤ 顶级域 DNS（TLD，如 .com）      ← 返回 example.com 的权威 DNS
⑥ 权威 DNS（Authoritative）        ← 真正持有 www.example.com → 1.2.3.4 记录的那台
```

**关键点**：②③ 是「你问谁」，④⑤⑥ 是「一步步逼近答案」。CDN 的魔法就在第 ⑥ 步——权威 DNS 会根据**访问者的 IP 归属**（大致地理/运营商）返回离你最近的边缘节点 IP，于是你「连到的机器」自动变成了 CDN 边缘。

### 记录类型扫一眼

| 类型 | 作用 | 测试里常见场景 |
|------|------|---------------|
| A | 域名 → IPv4 | `www → 1.2.3.4` |
| AAAA | 域名 → IPv6 | 双栈环境必测 |
| CNAME | 域名 → 另一个域名 | `test.internal → app.svc.cluster.local` |
| NS | 指定权威 DNS 是谁 | 换 DNS 服务商时改这个 |
| TXT | 任意文本 | 域名所有权验证、SPF 防垃圾邮件 |
| MX | 邮件服务器 | 基本不碰 |

## 用法

### 手动走一遍解析（比 ping 更有用）

```bash
# dig 是 DNS 诊断的瑞士军刀
dig www.example.com +trace        # 从根一路追到权威，看清每一跳谁答的
dig www.example.com @8.8.8.8      # 指定用公共 DNS 查（绕过公司内网 DNS）
dig www.example.com A +short      # 只看结果 IP，最常用

# nslookup 更「傻瓜」一点，但老脚本里到处都是
nslookup www.example.com

# 本地 hosts 改了不生效？先清缓存再试
# macOS
dscacheutil -flushcache; sudo killall -HUP mDNSResponder
# Windows
ipconfig /flushdns
```

### 在测试环境「劫持」解析结果

```bash
# 方式一：改 /etc/hosts（最直接，但只影响本机）
echo "10.0.2.30 api.internal" | sudo tee -a /etc/hosts
curl https://api.internal/health     # 直接连到 10.0.2.30，绕过 DNS 和 CDN

# 方式二：curl 用 --resolve 临时指定（不改系统，只影响这条命令）
curl --resolve api.internal:443:10.0.2.30 https://api.internal/health

# 方式三：dig 指定权威 DNS 查「真实线上 IP」对比测试环境 IP
dig api.example.com @ns1.real-authoritative.com +short
```

### 看 CDN 把你导向了哪个边缘

```bash
# 查 CNAME 链 + 最终落到的边缘（用两个公共 DNS 对比，差异即 CDN 调度）
dig www.example.com +short @8.8.8.8
dig www.example.com +short @1.1.1.1
# 多次 dig 可能返回不同边缘 IP —— 这就是 CDN 的 Anycast / 地理调度在起作用
```

## 踩坑

1. **改了 hosts 却「有时生效有时不」**。浏览器有 DNS 缓存、系统有缓存、连着容器里的 `/etc/resolv.conf` 还可能指向另一个 DNS。排查顺序永远是：先看本机 hosts → 再 `dscacheutil`/`ipconfig /flushdns` 清缓存 → 最后确认没有任何中间代理（如公司 VPN 客户端）强制走了它的 DNS。

2. **CDN 回源「串流」到测试环境**。CDN 的源站地址（Origin）如果配成了 `test.internal` 而不是 `prod.internal`，所有用户访问都会被导向你的测试机。这种「生产流量打到测试机」的事故，根因往往就是 DNS / CNAME 配错了一层。

3. **DNS 解析超时导致连接被拒（connection refused 之外的另一种）**。TCP 还没连，DNS 先卡 5 秒。用 `curl --resolve` 跳过 DNS 能立刻确认是不是 DNS 的锅。

4. **IPv6 优先导致的「连不上」**。双栈环境里，如果 AAAA 记录存在但目标服务只监听 IPv4，客户端会先尝试 IPv6 失败再退 IPv4，表现为「偶发慢/首包超时」。用 `curl -4` 强制走 v4 验证。

5. **CNAME 不能和任何其他记录类型共存**。比如你给 `www` 设了 CNAME，就不能再给 `www` 设 TXT/MX——DNS 协议层就禁止。配 SPF/DKIM 时经常踩这个坑。

6. **证书校验依赖 SNI，而 SNI 依赖你解析到的 IP 对应的证书**。DNS 把域名指向了错误 IP，即使 TLS 握手成功，也会因为「证书域名不匹配」报 `SSL certificate verify failed`。所以「证书错」和「解析错」经常结伴出现。

## 面试怎么答

**Q：从输入 URL 到查出 IP，具体哪几步？**

A：浏览器先查自身缓存（约 1 分钟 TTL 内直接返回）→ 查系统 hosts → 问本地递归解析器 → 递归器从根开始逐级问 TLD、问权威，最终拿到 A/AAAA 记录。每一步都可能被缓存加速，也可能因为 TTL 设置过长而「改了 DNS 半天才生效」。

**Q：为什么有时改 DNS 要等很久？**

A：因为**中间每一层都有缓存**，且 TTL 决定下游多久才愿意重新来问一次。你改了权威 DNS 的记录，但用户的递归解析器可能还拿着旧 TTL 的缓存，要等它过期后下次查询才会拉到新值。所以「理论上秒级生效，实际上全球收敛要几分钟到几小时」。

**Q：CDN 对测试有什么具体影响？**

A：两点。第一，**测试环境和生产环境可能解析到同一张 CDN 边缘**，如果你用同一个域名做测试，流量会混进生产边缘，污染数据；正确做法是测试用独立子域（如 `test.cdn.example.com`）。第二，**CDN 缓存会掩盖源站问题**——源站挂了但边缘还有缓存，你测「页面正常」其实是缓存扛着，真实回源失败被遮住了。所以测源站健康度必须带 `Cache-Control: no-cache` 或绕开 CDN 直连源站。

## 参考

- [RFC 1034 - Domain Names: Concepts and Facilities](https://datatracker.ietf.org/doc/html/rfc1034)
- [Cloudflare - 什么是 DNS？](https://www.cloudflare.com/learning/dns/what-is-dns/)
- [dig 官方文档](https://linux.die.net/man/1/dig)
- 相关笔记：[[从输入 URL 到页面渲染的完整链路]]、[[HTTPS 加密原理与 TLS 握手过程]]、[[跨域与 CORS]]
