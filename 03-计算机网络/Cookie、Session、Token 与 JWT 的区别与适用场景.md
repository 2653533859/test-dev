---
created: 2026-07-31
tags: [计算机网络/身份认证]
---

# Cookie、Session、Token 与 JWT 的区别与适用场景

> 图示：四种机制解决的是同一个问题——「这次请求是谁」，但「状态存在哪、谁来校验」完全不同。

## 概念

HTTP 本身是无状态的，服务器每收到一个请求都无法天然知道「这是不是上一秒那个用户」。四种机制都是在补「身份」这一环，区别在**状态存储位置**与**校验方**：

- **Cookie**：服务器通过 `Set-Cookie` 下发，浏览器按域名自动在后续请求里带上（`Cookie` 请求头）。**状态在客户端**（浏览器），本质是一小块键值对，容量约 4KB。
- **Session**：服务器自己维护一份会话数据（内存/Redis/数据库），只通过 Cookie 给客户端一个无意义的 `sessionId` 作为索引。**状态在服务端**，客户端只持有一个「取货号」。
- **Token（泛指）**：服务端签发的、自包含凭证，客户端拿到后每次请求手动带在 `Authorization` 头里。**服务端不存状态**，靠签名校验真伪。
- **JWT（JSON Web Token）**：Token 的一种标准实现，把「用户信息 + 过期时间 + 签名」编码进三段式字符串（`header.payload.signature`），服务端拿到后用密钥验签名即可信任，**无需查库**。

一句话区分：**Cookie 是「浏览器自动带的小纸条」，Session 是「服务端存档+客户端取号」，Token 是「自包含凭证」，JWT 是「签过名的 Token」。**

## 用法

最常见的登录流程对比：

```python
# Session 方案：服务端存状态
# 登录成功后
session["user_id"] = 123          # 落在 Redis/内存
response.set_cookie("sessionid", sid, httponly=True, secure=True, samesite="Lax")

# 后续请求：框架自动从 Cookie 取 sessionid -> 查 Redis -> 还原 user_id

# JWT 方案：服务端不存状态
import jwt
token = jwt.encode(
    {"user_id": 123, "exp": 1700000000},
    "SECRET_KEY",                  # 服务端持有的密钥
    algorithm="HS256",
)
# 客户端存 localStorage，之后每次请求头带：Authorization: Bearer <token>
# 服务端只验签名，不查库
```

适用边界：

- 传统服务端渲染、单域名 Web 应用 → **Session + Cookie**（简单、可主动失效）。
- 前后端分离、多端（Web/App/小程序）、需要水平扩展的微服务 → **Token / JWT**（无状态、跨域友好）。
- 跨站携带身份且有 CSRF 风险 → Cookie 务必加 `SameSite`；跨域 API → 用 `Authorization: Bearer` 的 Token，配合 CORS 白名单。

## 踩坑

- **Cookie 没加 `HttpOnly`**：JS 能读，XSS 一打就被盗。敏感 Cookie 必须 `HttpOnly; Secure; SameSite=Lax/Strict`。
- **Session 集群不共享**：多实例部署时如果 Session 存在单机内存，用户会被随机踢下线——必须落到 Redis 这类共享存储。
- **Token 无法主动失效**：JWT 一旦签发，过期前都有效。退出登录如果只是前端删 token，token 仍可被重放。解法：短过期 + Refresh Token，或服务端维护一个「黑名单 / 版本号」。
- **JWT 塞敏感信息**：payload 只是 base64 编码、可被解码，绝不能放密码、身份证号；密钥泄露等于全员伪造。
- **Token 存 localStorage**：页面被 XSS 拿到就能盗走；高安全场景考虑存内存 + 短期过期。

## 面试怎么答

先点出核心差异：状态在服务端（Session）还是客户端（Token/JWT），以及是否依赖浏览器自动携带（Cookie）。

- **JWT 和 Session 怎么选？** Session 服务端可控、能立即踢人，适合强管控的传统应用；JWT 无状态、易水平扩展、适合多端 API，但失效不灵活，要配 Refresh Token。
- **JWT 为什么比 Session 更适合微服务？** 每个服务用同一把公钥/密钥就能本地验签，不用每次回源查会话中心，降低耦合。
- **Token 被盗了怎么办？** 缩短 access token 有效期，用 refresh token + 服务端撤销列表；关键操作加二次校验（如支付密码、设备指纹）。
- **Cookie 和 Token 会一起用吗？** 会。例如用 HttpOnly Cookie 存 refresh token（防 XSS），用内存里的 access token 调 API，兼顾安全与体验。

## 参考

- [RFC 7519 - JSON Web Token (JWT)](https://datatracker.ietf.org/doc/html/rfc7519)
- [MDN: HTTP cookies](https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Cookies)
- [JWT 官方介绍](https://jwt.io/introduction)
- 相关笔记：[[跨域与 CORS]]、[[HTTPS 加密原理与 TLS 握手过程]]、[[认证与会话安全测试]]、[[Token 与 JWT 鉴权的获取与刷新]]
