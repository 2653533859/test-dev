---
created: 2026-07-31
tags: [计算机网络/HTTP]
---

# HTTP 常见请求头与响应头

> 请求头是客户端的「自我介绍 + 诉求」，响应头是服务端的「处理说明书」。绝大多数「明明接口没问题却表现异常」的疑难杂症，答案都藏在响应头里。

## 概念

### 头部字段的分类

按作用可以分成五类，理解分类比死记字段名有用得多：

| 类别 | 作用 | 代表字段 |
|------|------|---------|
| 通用头 | 请求响应都能用 | `Date`、`Connection`、`Cache-Control`、`Via` |
| 请求头 | 描述客户端与请求诉求 | `Host`、`User-Agent`、`Accept`、`Authorization`、`Referer` |
| 响应头 | 描述服务端与响应元信息 | `Server`、`Location`、`Set-Cookie`、`ETag` |
| 实体头 | 描述消息体本身 | `Content-Type`、`Content-Length`、`Content-Encoding` |
| 安全头 | 指示浏览器执行安全策略 | `Strict-Transport-Security`、`Content-Security-Policy` |

字段名**大小写不敏感**（`content-type` 与 `Content-Type` 等价），但 HTTP/2 起要求全部小写传输。所以代码里读 header 一定要用大小写不敏感的方式——`requests` 的 `resp.headers` 已经是 `CaseInsensitiveDict`，但如果你自己解析原始报文就要注意。

### 必知的请求头

**`Host`** —— HTTP/1.1 唯一强制必填的头。它让一台服务器（一个 IP）能承载多个域名，也就是虚拟主机。测试时用 IP 直连但没带对 `Host`，Nginx 会 fallback 到默认 server 块，返回完全不同的站点——这是「我明明请求的是 A 服务怎么返回了 B 的内容」的经典原因。

**`Content-Type`** —— 声明**请求体的格式**。服务端据此选择解析器。常见值：

```text
application/json                     JSON API 主流
application/x-www-form-urlencoded    传统表单
multipart/form-data; boundary=xxx    文件上传
text/plain                           纯文本
application/octet-stream             二进制流
```

传了 JSON 但 Content-Type 写成 form，服务端会解析失败返回 400/415，这是接口测试的常见自制 bug。

**`Accept` 系列** —— 内容协商，告诉服务端「我能接受什么」：

```text
Accept: application/json, text/plain;q=0.9    想要什么格式（q 是权重）
Accept-Encoding: gzip, deflate, br             支持什么压缩
Accept-Language: zh-CN,zh;q=0.9,en;q=0.8      想要什么语言
```

**`Accept-Language` 是国际化测试的核心开关**——不用切系统语言，改这个头就能验证多语言返回。

**`Authorization`** —— 携带凭证，两种主流形式：

```text
Authorization: Bearer eyJhbGciOiJIUzI1NiJ9...          Token / JWT
Authorization: Basic dXNlcjpwYXNz                       Basic 认证，是 base64(user:pass) 不是加密
```

Basic 认证的值只是 Base64，**任何人抓包都能一秒解出明文密码**，必须配合 HTTPS 使用。这是安全测试的常见发现点。

**`Cookie`** —— 携带服务端之前通过 `Set-Cookie` 种下的键值对。详见 [[Cookie、Session、Token 与 JWT 的区别与适用场景]]。

**`User-Agent`** —— 客户端标识。很多服务端会据此做**风控拦截**：默认的 `python-requests/2.31.0` 经常被 WAF 直接拦掉，表现为「浏览器能访问，脚本 403」。

**`Referer`** —— 来源页面地址（历史拼写错误，正确拼法是 Referrer，但协议里将错就错）。用于防盗链和 CSRF 防护，也是测试防盗链功能的关键开关。

**`X-Forwarded-For` / `X-Real-IP`** —— 经过代理时记录真实客户端 IP。格式是逗号分隔的链路：

```text
X-Forwarded-For: 真实客户端IP, 第一层代理IP, 第二层代理IP
```

**这个头可以被客户端任意伪造**，所以「基于 IP 的限流/白名单」如果直接信任 XFF 的第一个值就存在绕过漏洞——安全测试必测。正确做法是只信任「从右往左数第 N 个」（N 由已知的可信代理层数决定）。

**`Range`** —— 请求资源的某一段，配合响应的 `206 Partial Content` 实现断点续传和视频拖拽播放：

```text
Range: bytes=0-1023        请求前 1024 字节
Range: bytes=1024-         从 1024 字节到结尾
```

### 必知的响应头

**`Content-Type`** —— 声明**响应体格式**，浏览器据此决定渲染方式。`charset` 参数缺失是中文乱码的头号原因：

```text
Content-Type: application/json; charset=utf-8
Content-Type: text/html; charset=utf-8
```

**`Content-Length` vs `Transfer-Encoding: chunked`** —— 两种告知消息体长度的方式，**互斥**：

- `Content-Length: 1024`：提前知道总长度，一次性声明。
- `Transfer-Encoding: chunked`：分块传输，长度未知（流式生成、大文件、SSE），每块前面写自己的长度，最后用长度 0 的块表示结束。

两者同时出现时，不同服务器的解析优先级不一致，这正是 **HTTP 请求走私**漏洞的成因。

**`Set-Cookie`** —— 种 Cookie，属性决定安全性：

```text
Set-Cookie: SESSIONID=abc123; Path=/; Domain=.example.com; Max-Age=3600; HttpOnly; Secure; SameSite=Lax
```

- `HttpOnly`：JS 无法通过 `document.cookie` 读取，**防 XSS 窃取**
- `Secure`：只在 HTTPS 下发送
- `SameSite`：`Strict` / `Lax` / `None`，**防 CSRF**。设为 `None` 时必须同时设 `Secure`，否则现代浏览器直接丢弃

**登录态相关的 Cookie 必须同时有 HttpOnly + Secure + SameSite**，这是安全测试的固定检查项。

**缓存三兄弟** —— 决定浏览器要不要发请求：

```text
Cache-Control: max-age=3600, public          强缓存：1 小时内直接用本地副本，不发请求
Cache-Control: no-cache                       每次都要跟服务端确认（协商缓存）
Cache-Control: no-store                       绝对不缓存，敏感数据必须加
ETag: "33a64df551425fcc55e"                   资源指纹，配合 If-None-Match 做协商缓存
Last-Modified: Fri, 31 Jul 2026 06:00:00 GMT  最后修改时间，配合 If-Modified-Since
```

`no-cache` 和 `no-store` 极易混淆：**`no-cache` 是「可以存但每次要问」，`no-store` 才是「根本不许存」**。涉及个人隐私、订单详情、Token 的响应必须用 `no-store`。

**`Location`** —— 3xx 时指示跳转目标；201 时指示新创建资源的地址。

**安全头** —— 都是给浏览器看的指令：

```text
Strict-Transport-Security: max-age=31536000; includeSubDomains   强制走 HTTPS（HSTS）
X-Content-Type-Options: nosniff                  禁止浏览器猜测 MIME，防 XSS
X-Frame-Options: DENY                            禁止被 iframe 嵌套，防点击劫持
Content-Security-Policy: default-src 'self'      限制资源加载来源，防 XSS
Referrer-Policy: no-referrer-when-downgrade      控制 Referer 泄露
```

这些头**只在浏览器环境生效**，用 curl 或 requests 测试完全感知不到——所以安全扫描要专门检查这些头是否存在。

## 用法

### 查看与统计响应头

```bash
# 看全部响应头
curl -sI https://api.example.com/v1/orders/1

# 检查关键安全头是否配齐（可以做成 CI 的安全门禁）
curl -sI https://example.com | grep -iE 'strict-transport|x-frame|x-content-type|content-security|referrer-policy'

# 验证 gzip 压缩是否生效（对比响应体大小）
curl -s -o /dev/null -w "无压缩: %{size_download} 字节\n" https://example.com/app.js
curl -s -H "Accept-Encoding: gzip" -o /dev/null -w "gzip: %{size_download} 字节\n" https://example.com/app.js
```

### 用请求头驱动测试场景

```bash
# 国际化：不切环境，只改 Accept-Language
curl -H "Accept-Language: en-US" https://api.example.com/v1/products/1
curl -H "Accept-Language: ja-JP" https://api.example.com/v1/products/1

# 模拟移动端（很多接口会按 UA 返回不同内容）
curl -H "User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)" https://example.com

# 伪造来源 IP，测试基于 IP 的限流/白名单是否可被绕过（安全测试）
curl -H "X-Forwarded-For: 127.0.0.1" https://api.example.com/admin/stats

# 测试防盗链
curl -H "Referer: https://evil.com" https://cdn.example.com/paid-video.mp4

# 断点续传：请求第 100-199 字节，应返回 206 和 Content-Range
curl -i -H "Range: bytes=100-199" https://example.com/big.zip | head -8

# 灰度发布：很多网关按自定义头分流
curl -H "X-Gray-Tag: canary" https://api.example.com/v1/orders/1
```

### 缓存行为验证

```python
import requests

URL = "https://example.com/app.js"

# 第一次请求，拿 ETag 和 Cache-Control
r1 = requests.get(URL, timeout=10)
etag = r1.headers.get("ETag")
print("Cache-Control:", r1.headers.get("Cache-Control"))
print("ETag:", etag)
assert r1.status_code == 200

# 带 If-None-Match 再请求，应命中协商缓存返回 304 且 body 为空
r2 = requests.get(URL, headers={"If-None-Match": etag}, timeout=10)
assert r2.status_code == 304
assert len(r2.content) == 0, "304 不应有响应体"


def test_sensitive_api_not_cached(auth_headers):
    """订单详情这类敏感接口必须 no-store，防止被 CDN 或浏览器缓存"""
    r = requests.get("https://api.example.com/v1/orders/98765",
                     headers=auth_headers, timeout=10)
    cc = r.headers.get("Cache-Control", "")
    assert "no-store" in cc, f"敏感接口缓存策略不安全: {cc}"
```

### Cookie 安全属性检查

```python
import requests


def test_login_cookie_security():
    r = requests.post("https://example.com/login",
                      data={"u": "alice", "p": "secret"}, timeout=10)

    # requests 解析后的 cookie 对象能直接读属性
    for c in r.cookies:
        if c.name.upper() in ("SESSIONID", "JSESSIONID", "TOKEN"):
            assert c.secure, f"{c.name} 缺少 Secure，明文 HTTP 下会泄露"
            assert c.has_nonstandard_attr("HttpOnly"), f"{c.name} 缺少 HttpOnly，XSS 可窃取"
            samesite = c.get_nonstandard_attr("SameSite", "")
            assert samesite.lower() in ("lax", "strict"), f"{c.name} SameSite={samesite} 存在 CSRF 风险"
```

### 让 requests 的所有请求都带上统一头

```python
import requests

session = requests.Session()
session.headers.update({
    "User-Agent": "qa-automation/1.0 (+https://wiki.example.com/qa)",  # 避免被 WAF 拦
    "Accept": "application/json",
    "X-Request-Id": "auto-test",     # 便于在服务端日志里检索本次测试产生的请求
})

r = session.get("https://api.example.com/v1/orders", timeout=10)
```

**给自动化请求打上可识别的 `User-Agent` 和 `X-Request-Id`**，能让后端在排查时一眼区分「测试流量」和「真实流量」，是很值得推行的团队规范。

## 踩坑

1. **`python-requests` 默认 UA 被 WAF 拦截**。现象是浏览器访问正常、Postman 正常，一到脚本就 403 或返回验证码页面。原因是默认 `User-Agent: python-requests/2.31.0` 被识别为爬虫。改成正常浏览器 UA 或团队约定的测试 UA 即可。**排查时对比「浏览器 F12 复制为 cURL」和「自己脚本发的请求」的头部差异，是定位这类问题最快的办法。**

2. **中文乱码：`Content-Type` 缺 charset**。响应头只有 `Content-Type: application/json` 没有 `charset=utf-8` 时，`requests` 会按 RFC 猜成 `ISO-8859-1`，`resp.text` 就是乱码。两种解法：

   ```python
   r = requests.get(url)
   print(r.text)                    # 乱码：ä¸­æ

   # 解法一：手动指定编码
   r.encoding = "utf-8"
   print(r.text)                    # 正常

   # 解法二：绕过 text，直接用 json()（内部按 UTF-8 解）或自己 decode
   print(r.json())
   print(r.content.decode("utf-8"))
   ```

   同时应当把「响应头缺 charset」作为缺陷提给后端，因为浏览器也会受影响。

3. **手动设了 `Content-Length` 却又改了 body**。用 `requests` 时不要手动设 `Content-Length`，库会自动计算。手动设错会导致服务端读不全或一直等待，表现为请求挂起直到超时。

4. **`SameSite=Lax` 导致跨站请求带不上 Cookie**。Chrome 80 后 `SameSite` 默认值从 `None` 改成了 `Lax`，意味着**跨站的 POST 请求不再自动携带 Cookie**。很多老系统的 iframe 嵌入、第三方支付回调因此突然失效。要跨站带 Cookie 必须显式 `SameSite=None; Secure`，且必须是 HTTPS。

5. **`X-Forwarded-For` 被无脑信任导致限流绕过**。如果服务端代码是 `ip = request.headers.get("X-Forwarded-For").split(",")[0]`，那么客户端只要自己塞一个 `X-Forwarded-For: 1.2.3.4`，每次换一个值就能无限绕过限流和 IP 黑名单。**这是我在接口安全测试里屡试屡中的一个点。**正确做法是网关层覆写这个头，或者只取「从右往左数第 N 个」。

6. **CORS 场景下自定义响应头前端读不到**。跨域时，JS 默认只能读取 6 个基本响应头（`Cache-Control`、`Content-Language`、`Content-Type`、`Expires`、`Last-Modified`、`Pragma`）。自定义头（比如 `X-Total-Count` 分页总数）必须由服务端通过 `Access-Control-Expose-Headers` 显式暴露：

   ```text
   Access-Control-Expose-Headers: X-Total-Count, X-Request-Id
   ```

   现象是「curl 能看到这个头，浏览器控制台里读出来是 null」。详见 [[跨域与 CORS]]。

7. **头部字段大小写导致的解析失败**。自己解析原始报文时用 `headers["Content-Type"]` 精确匹配，遇到服务端返回 `content-type`（HTTP/2 强制小写）就取不到。永远用大小写不敏感的取值方式。

8. **敏感接口没设 `no-store`，响应被 CDN 缓存**。真实事故：订单详情接口没设缓存控制头，CDN 按默认策略缓存了 5 分钟，导致**用户 A 看到了用户 B 的订单**。这类缺陷极其严重，检查方法是对所有需要鉴权的接口断言 `Cache-Control` 包含 `no-store` 或 `private`。

9. **头部值里包含换行导致注入**。如果服务端把用户输入直接拼进响应头（比如 `Location: /redirect?to=<用户输入>`），用户输入里带 `%0d%0a` 就能注入额外的头甚至完整的响应体。测试方法是在任何会被回显到响应头的参数里注入 `%0d%0aX-Injected:%20true`，然后检查响应头里有没有出现 `X-Injected`。

## 面试怎么答

**Q：说几个你常用的 HTTP 头，以及它们在测试中的作用。**

A（30 秒骨架）：请求侧我最常用四个——`Host` 决定虚拟主机路由，用 IP 直连测试时必须手动带对，否则会打到默认 server；`Content-Type` 声明请求体格式，写错会 415；`Authorization` 带凭证，`Bearer` 是 Token、`Basic` 只是 Base64 不是加密；`Accept-Language` 是国际化测试的开关，不用切系统语言就能验证多语言。响应侧我最关注 `Set-Cookie` 的安全属性、`Cache-Control` 的缓存策略、以及一组安全头。

**Q：`no-cache` 和 `no-store` 有什么区别？**

A：这俩名字很误导。`no-cache` 不是「不缓存」，而是「**可以存，但每次使用前必须向服务端验证**」——也就是走协商缓存，配合 ETag / Last-Modified，命中就返回 304。`no-store` 才是真正的「**一个字节都不许存**」，本地和中间代理都不能留副本。涉及订单、个人信息、Token 的接口必须用 `no-store`。我见过一起事故就是订单详情接口没设缓存头，被 CDN 按默认策略缓存了几分钟，导致用户看到别人的订单——这是很严重的越权数据泄露。

**Q：Cookie 有哪些安全属性，分别防什么？**

A：三个核心属性。`HttpOnly` 让 JS 无法通过 `document.cookie` 读取，防的是 **XSS 窃取会话**；`Secure` 让 Cookie 只在 HTTPS 下发送，防的是**明文链路被嗅探**；`SameSite` 控制跨站请求是否携带 Cookie，`Strict` 完全不带、`Lax` 只有安全的顶级导航才带、`None` 总是带（但必须同时加 Secure），防的是 **CSRF**。所有登录态相关的 Cookie 这三个属性都应该配齐，这是我做接口安全检查的固定项。补充一点：Chrome 80 之后 SameSite 默认值从 None 变成了 Lax，这个变更让不少依赖跨站 Cookie 的老系统突然失效。

**Q：`X-Forwarded-For` 是干什么的，有什么风险？**

A：经过代理后，服务端看到的 `remote_addr` 是代理的 IP，真实客户端 IP 就靠 `X-Forwarded-For` 这个头传递，格式是逗号分隔的链路：`真实客户端, 代理1, 代理2`。风险在于**这个头完全由客户端可控，可以任意伪造**。如果服务端直接取第一个值来做 IP 限流或白名单，攻击者只要自己塞一个 XFF 头、每次换个值，就能无限绕过限流。我在接口安全测试里经常测这一项，命中率很高。正确做法是网关层强制覆写这个头，或者按已知的可信代理层数从右往左取。

**Q：接口返回中文乱码，你怎么排查？**

A：先看响应头的 `Content-Type` 有没有 `charset=utf-8`。如果没有，`requests` 会按 RFC 默认猜成 ISO-8859-1，`resp.text` 就乱码了。临时解法是手动设 `r.encoding = 'utf-8'`，或者直接用 `r.json()` / `r.content.decode('utf-8')` 绕过。但这只是我本地绕过去了，**根因还是服务端响应头不规范，会同样影响浏览器**，所以要作为缺陷提给后端。如果 `charset` 是对的还乱码，那就要往上游查——可能是数据库连接的字符集、或者数据写入时就已经是乱码了。

## 参考

- [MDN - HTTP 标头](https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Headers)
- [RFC 9110 - HTTP Semantics: Fields](https://datatracker.ietf.org/doc/html/rfc9110#section-5)
- [OWASP Secure Headers Project](https://owasp.org/www-project-secure-headers/)
- 相关笔记：[[HTTP 报文结构与请求方法]]、[[HTTP 状态码分类与易混对比]]、[[Cookie、Session、Token 与 JWT 的区别与适用场景]]、[[跨域与 CORS]]
