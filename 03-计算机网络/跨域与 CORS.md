---
created: 2026-07-31
tags: [计算机网络/跨域]
---

# 跨域与 CORS

> 前端调后端报 `blocked by CORS policy`，几乎是每个前后端分离项目的「成人礼」。理解 CORS 不是背一首诗，而是看清浏览器在「同源策略」这道门上，到底开了哪几道缝。

![[assets/cors-preflight.svg]]
*图示：简单请求直过，非简单请求先 OPTIONS 预检再放行。*

## 概念

### 同源策略到底在防什么

浏览器有个铁律：**一个源的文档，不能读另一个源的资源**。同源 = 协议 + 域名 + 端口全同。

```text
https://a.com:443  vs  https://b.com:443   ← 不同源（域名不同）
https://a.com     vs  http://a.com        ← 不同源（协议不同）
https://a.com     vs  https://a.com:8080  ← 不同源（端口不同）
```

这道门防的是：**恶意网站 B 偷偷用你的已登录态去调接口 A**。没有同源策略，任何网页都能让你的浏览器带着你的 Cookie 去打别人的服务。

### CORS 是「服务器给浏览器开的白名单」

CORS 不是浏览器单方面限制，而是**服务端通过响应头，明确告诉浏览器「我允许谁来跨域」**。核心响应头：

| 响应头 | 作用 |
|--------|------|
| `Access-Control-Allow-Origin` | 允许哪些源（`*` / `https://a.com`） |
| `Access-Control-Allow-Methods` | 允许的 HTTP 方法 |
| `Access-Control-Allow-Headers` | 允许带哪些自定义请求头 |
| `Access-Control-Allow-Credentials` | 是否允许带 Cookie（`true` 时 Origin 不能是 `*`，必须明确指定） |

### 简单请求 vs 预检请求

浏览器自己判断：

- **简单请求**：GET / HEAD / POST，且只带 `Accept`/`Accept-Language`/`Content-Language`/`Content-Type` 等「CORS 安全头」，且 `Content-Type` 只能是 `application/x-www-form-urlencoded`、`multipart/form-data`、`text/plain`。→ **直接发，不预检**。
- **非简单请求**：带了 `Authorization`、`application/json`，或用了 PUT / DELETE / PATCH。→ **先发一个 OPTIONS 预检**，服务端回 `Allow-*` 头，浏览器确认放行后才发真正的请求。

## 用法

### 后端加最松的 CORS（测试期先用，上线前收紧）

```python
# Flask 最简：允许所有源、带凭证
from flask import Flask, request, make_response

app = Flask(__name__)

@app.route("/api/data")
def data():
    resp = make_response('{"ok":1}')
    resp.headers["Access-Control-Allow-Origin"] = "*"
    # 若要带 Cookie，Origin 不能用 *，必须显式写来源，并加下面这行
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp
```

### Nginx 层统一加 CORS（更常见的生产做法）

```nginx
# 在 server 块里加；注意 proxy_pass 的后端若也带 CORS 头会冲突，二选一
location /api/ {
    add_header 'Access-Control-Allow-Origin' 'https://app.example.com';
    add_header 'Access-Control-Allow-Methods' 'GET, POST, PUT, DELETE, OPTIONS';
    add_header 'Access-Control-Allow-Headers' 'Content-Type, Authorization';
    add_header 'Access-Control-Allow-Credentials' 'true';
    if ($request_method = 'OPTIONS') {
        return 204;   # 预检直接返回空 204，不往上游转发
    }
    proxy_pass http://backend;
}
```

### 前端怎么正确「跨域」调用

```javascript
// 带凭证的跨域请求，XMLHttpRequest / fetch 都一样
fetch("https://api.internal/v1/orders", {
  method: "POST",
  credentials: "include",           // 关键：带上 Cookie
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ id: 1 }),
});
// 服务端必须回：
//   Access-Control-Allow-Origin: https://app.example.com  （不能是 *）
//   Access-Control-Allow-Credentials: true
```

### 本地联调时绕开 CORS 的几种姿势

```bash
# 1) 用 --disable-web-security 起一个「不检查同源」的 Chrome（仅本地调试）
google-chrome --disable-web-security --user-data-dir=/tmp/chrome-nosec

# 2) 开发服务器配 proxy（Vite / webpack-dev-server）
# vite.config.js
server: { proxy: { '/api': { target: 'https://api.internal', changeOrigin: true } } }

# 3) 用 fetch 的 mode 不强求——其实浏览器里没法关，只能靠上面两种
```

## 踩坑

1. **`Allow-Origin: *` 和 `Credentials: true` 不能共存**。规范要求：一旦带凭证（Cookie），`Allow-Origin` 就**不能**是 `*`，必须显式写来源。漏了这个，浏览器会直接拒掉整个响应。这是 CORS 里最容易写错的一行。

2. **预检 OPTIONS 被网关/网关当业务请求处理**。很多框架把 OPTIONS 也路由到业务 handler，结果返回了 404 / 405，浏览器认为预检失败。正确做法：在网关或框架最前面统一 `return 204` 吞掉 OPTIONS。

3. **Nginx 加的 CORS 头 + 后端也加 = 响应里出现两个 `Access-Control-Allow-Origin`**。浏览器看到重复头会直接报错。要么 Nginx 加、后端不加，要么反过来，别两边都加。

4. **`withCredentials` 前端设了，后端没回 `Allow-Credentials`**。看起来「请求发出了但永远拿不到响应」，其实是响应被浏览器拦截。定位：DevTools 的 Network 里该请求状态是 `(failed) net::ERR_FAILED`，Console 里才会看到 CORS 报错——容易误以为是网络问题。

5. **跨域时 Cookie 的 `SameSite` 也来掺和**。即使 CORS 放行，`SameSite=Lax` 的 Cookie **不会**随跨域请求带过去（除非是顶部导航的 GET）。所以带凭证的跨域还要配合 `SameSite=None; Secure`。这是 CORS 之外另一道独立的大门。

6. **WebSocket / `<img>` / `<script>` 不受 CORS 限制**。JSONP 就是钻了这个空子（`<script src=跨域>` 永远能加载），但也因此它只能做 GET。现代做法是用 CORS 取代 JSONP。

## 面试怎么答

**Q：CORS 是浏览器限制还是服务器限制？**

A：两者配合。浏览器**默认**拦截跨域响应（同源策略），但**是否放行由服务器用 CORS 响应头决定**。也就是说，即使服务端没加 CORS 头，服务端其实「已经把数据发回来了」——只是浏览器把响应藏起来不给你 JS 读。所以「服务器返回了但前端读不到」这种描述才是准确的。用 Postman / curl 直连永远不受 CORS 限制，因为只有浏览器才执行同源策略。

**Q：为什么要有预检（preflight）？**

A：预检是给服务端一个「在真正动数据之前先说清楚规则」的机会。试想没有预检，攻击网站能直接发 `DELETE /api/transfer` 这种非简单请求——虽然浏览器仍会拦截读取响应，但**请求本身已经打到服务端了**（正常 GET 转账的副作用就发生了）。预检把「能否跨域」的确认提前到真正改数据之前，避免非简单请求被滥用。

**Q：什么时候可以不用 CORS？**

A：三种常见情况。第一，**同源部署**（前后端同域，最省事）；第二，**服务端主动「不检查来源」**（如公开 API 设 `Allow-Origin: *`，适合纯读取、无需登录的资源）；第三，**反向代理把跨域变成同域**（开发期 Vite proxy、生产期 Nginx 反代，前端看到的永远是同源）。

## 参考

- [MDN - CORS](https://developer.mozilla.org/zh-CN/docs/Web/HTTP/CORS)
- [Fetch Standard - CORS Protocol](https://fetch.spec.whatwg.org/#cors-protocol)
- [阮一峰 - CORS 详解](https://www.ruanyifeng.com/blog/2016/04/cors.html)
- 相关笔记：[[正向代理与反向代理]]、[[Cookie、Session、Token 与 JWT 的区别与适用场景]]、[[从输入 URL 到页面渲染的完整链路]]
