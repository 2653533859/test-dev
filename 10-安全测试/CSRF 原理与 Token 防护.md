---
created: 2026-07-31
tags: [安全测试/Web漏洞]
---

# CSRF 原理与 Token 防护

> CSRF 的根因是「浏览器会自动携带 Cookie」。服务端校验了「你是谁」，却没校验「这次操作是不是你自己发起的」。

![[assets/csrf-token-flow.svg]]
*图示：上半部分是无防护时恶意页面借用受害者会话完成写操作的过程；下半部分是 CSRF Token 的四步校验链，以及它为什么能生效（同源策略让攻击者读不到 token）。*

## 概念

### 根因：Cookie 的自动携带机制

浏览器有一条规则：**只要请求的目标域匹配 Cookie 的作用域，就自动带上它，不管这个请求是从哪个页面发出来的**。

这条规则是为了让「用户在同一个站点的不同页面间跳转不用反复登录」，但它带来的副作用是：evil.com 上的一个表单，只要 action 指向 bank.com，浏览器照样会带上 bank.com 的会话 Cookie。

服务端收到请求，看 Cookie 有效，判定「是本人」，于是执行操作。它没有任何办法区分这个请求是用户在 bank.com 的页面上点的，还是在 evil.com 上被诱导发出的。

### 攻击成立需要的三个条件

缺一不可，这也是测试判断「是否真的可利用」的依据：

1. **受害者已登录目标站点**，且会话还有效；
2. **目标接口是「写操作」且参数完全可预测**（没有攻击者猜不到的值）；
3. **服务端只依赖 Cookie 做身份判定**，没有额外的来源校验。

由此推出一个常被问的点：**为什么 CSRF 危害集中在写操作？** 因为同源策略挡住了响应读取——攻击者能让请求发出去，但读不到返回的内容。所以他能让你转账，但拿不到你的余额。

### CSRF 与 XSS 的区别

| 维度 | XSS | CSRF |
|------|-----|------|
| 脚本在哪执行 | 受害站点自己的域 | 第三方域 |
| 能否读响应 | 能（同源） | 不能 |
| 能力 | 读页面、读 Cookie、任意请求 | 仅能发出预测得到的请求 |
| 防御 | 输出编码、CSP | Token、SameSite、来源校验 |

**关键联动**：如果站点存在 XSS，攻击者可以直接读走页面里的 CSRF token，CSRF 防护立即失效。所以两者必须一起修，不能说「我有 CSRF token 所以安全」。

### Token 防护为什么有效

服务端在渲染表单时下发一个随机值，同时在会话里存一份；提交时要求把这个值带回来，两边比对。

生效的原理**不是「随机值猜不到」**（虽然也需要足够随机），而是：**同源策略让 evil.com 的 JS 读不到 bank.com 页面的 DOM，也读不到 bank.com 的响应体**。所以攻击者能构造出「带 Cookie 的请求」，但构造不出「带正确 token 的请求」。

这就是为什么把 token 放在 Cookie 里而不做任何额外处理是**无效**的——Cookie 会被自动带上，攻击者不需要读到它。必须放在 body 参数或自定义请求头里，也就是「攻击者必须主动写入、但他写不出正确值」的位置。

## 用法

### 三层防御及其适用场景

**第一层：SameSite Cookie（成本最低，优先做）**

```text
Set-Cookie: session=xxx; HttpOnly; Secure; SameSite=Lax
```

| 取值 | 行为 | 适用 |
|------|------|------|
| `Strict` | 任何跨站请求都不带 Cookie | 安全性最高，但从外链跳进来会显示未登录 |
| `Lax` | 跨站的顶级导航 GET 会带，POST/iframe/ajax 不带 | 现代浏览器默认值，平衡之选 |
| `None` | 跨站一律带（必须同时 `Secure`） | 确需跨站的场景，如嵌入式第三方组件 |

注意：`Lax` 只挡住了跨站的 POST，**如果站点存在「用 GET 做写操作」的接口，Lax 挡不住**。这也是为什么「写操作必须用 POST」不只是 RESTful 规范问题，还是安全要求。

**第二层：CSRF Token（主力方案）**

```python
# Flask-WTF 的用法：模板里插入隐藏字段，提交时框架自动校验
# <form method="post">
#   {{ form.csrf_token }}
#   ...
# </form>

# 前后端分离场景（Double Submit Cookie 变体）
# 1. 服务端下发一个 csrf token 到「非 HttpOnly」的 Cookie
# 2. 前端 JS 读出来，放进自定义请求头
# 3. 服务端比对 Header 与 Cookie 是否一致
```

前后端分离下 Double Submit 能生效的原因：evil.com 虽然能让浏览器带上那个 Cookie，但**读不到它的值**（跨域），因此写不出正确的自定义 Header。加上自定义 Header 会触发 CORS 预检，进一步提高了门槛。

**第三层：来源校验 + 敏感操作二次确认**

```python
# 校验 Origin（优先）或 Referer
ALLOWED_ORIGINS = {"https://app.example.com"}

def check_origin(request) -> bool:
    origin = request.headers.get("Origin")
    if origin:
        return origin in ALLOWED_ORIGINS
    referer = request.headers.get("Referer")
    if referer:
        from urllib.parse import urlparse
        p = urlparse(referer)
        return f"{p.scheme}://{p.netloc}" in ALLOWED_ORIGINS
    # 两者都没有 → 保守拒绝（对写接口而言）
    return False
```

转账、改绑手机、修改支付密码这类高危操作，还应该加短信验证码或密码二次确认——这是 Token 之外最有效的一道。

### 在授权环境里怎么测

测试逻辑很简单：**把「攻击者拿不到的那个东西」去掉，看服务端还认不认**。全程用自己的测试账号，在自有测试环境操作。

用 Burp 的 Repeater 逐项试（详见 [[Burp Suite 抓包改包工作流]]）：

```text
用例 1  删除请求体里的 csrf_token 参数        → 期望 403
用例 2  把 token 值改掉一位字符               → 期望 403
用例 3  用账号 B 登录拿到的 token 配 A 的 Cookie → 期望 403（验证 token 是否绑定会话）
用例 4  用上一次请求用过的旧 token 再提交一次   → 看是否一次性（非强制，但可写进建议）
用例 5  删除 Origin 和 Referer 头             → 期望 403
用例 6  把 Origin 改成 https://evil.com       → 期望 403
用例 7  把 POST 改成 GET，参数放 query        → 期望 405，绝不能执行成功
用例 8  Content-Type 改成 text/plain 再提交    → 检查是否绕过了框架的 CSRF 校验
```

用例 3 和用例 7 最容易发现问题：很多实现的 token 是全局静态的（不绑会话），或者接口同时支持 GET 和 POST。

如果需要构造一个完整的 PoC 页面提交给开发说明问题，**放在本地 `file://` 或本机起的临时服务上**，只指向自有测试环境，不要挂到公网：

```html
<!-- 本地 PoC：仅用于向开发演示「无需 token 也能提交成功」 -->
<form action="http://test-app.internal.com/api/profile/update" method="POST">
  <input name="nickname" value="csrf-poc-test">
</form>
<script>document.forms[0].submit();</script>
```

### 什么情况下不需要 CSRF 防护

- **纯 Bearer Token 认证**（token 存在 localStorage，由 JS 显式放进 `Authorization` 头）：浏览器不会自动携带 `Authorization`，攻击者构造的请求带不上，天然免疫 CSRF。代价是换来了 XSS 风险（localStorage 能被 JS 读）。
- **只读接口**：GET 且无副作用的接口不需要，但前提是它真的没有副作用。

这也是个高频追问：**为什么现在很多前后端分离项目不做 CSRF 防护？** 因为它们用的是 Bearer Token 而非 Cookie 会话。但**只要用了 Cookie 存会话（包括 HttpOnly 的 JWT Cookie），CSRF 防护就必须做**。

## 踩坑

1. **Token 不绑会话**。全站用同一个静态 token，或者 token 只跟时间有关，攻击者自己访问一次站点就能拿到一个有效值。测试用例 3 专门测这个。
2. **只在部分接口校验**。框架配了全局 CSRF 保护，但某几个接口为了对接第三方加了豁免（比如 Django 的 `@csrf_exempt`），豁免后就忘了。代码审计要专门搜豁免注解。
3. **用 GET 做写操作**。`/api/user/delete?id=1` 这类接口，SameSite=Lax 挡不住（顶级导航 GET 会带 Cookie），一个 `<img src>` 就能触发。
4. **校验「参数存在」而非「值正确」**。有的实现只判断 `if 'csrf_token' in request.form`，随便填个值就过了。测试时一定要试「改值」而不只是「删参数」。
5. **Referer 校验用 `startswith`**。`referer.startswith("https://example.com")` 会被 `https://example.com.evil.com` 绕过。必须解析出 host 后做完整匹配。
6. **把 token 放进 URL**。会被记进浏览器历史、访问日志、Referer 头，导致泄露。应放在 body 或自定义 Header。
7. **以为有了 SameSite 就不用 Token**。老版本浏览器不支持 SameSite；且 `Lax` 下 GET 写接口仍有风险。SameSite 是加固，不是替代。
8. **忽略 XSS 的联动**。站点有存储型 XSS 时，脚本可以直接读页面里的 token 再发请求，CSRF 防护完全失效。报告里如果同时发现两者，应说明组合危害。
9. **PoC 页面挂到公网**。演示用的自动提交页面如果放在公网且指向真实域名，会变成真实攻击工具。只放本地、只指向测试环境。

## 面试怎么答

**Q：什么是 CSRF？原理是什么？**

A：CSRF 是跨站请求伪造。根因是浏览器的一条机制——只要请求目标域匹配 Cookie 作用域，就会自动带上 Cookie，不管这个请求是从哪个页面发起的。于是攻击者在自己的页面上放一个指向目标站点的自动提交表单，受害者只要还处于登录态并访问了这个页面，请求就会带着有效会话发到目标站点。服务端看 Cookie 有效，就判定是本人操作。问题的本质是：服务端校验了「你是谁」，但没有校验「这次操作是不是你自己在我的页面上发起的」。另外因为同源策略挡住了响应读取，攻击者拿不到返回内容，所以 CSRF 的危害集中在写操作上，比如转账、改密、删数据。

**Q：CSRF Token 为什么能防住？把 token 放 Cookie 里行不行？**

A：Token 生效的关键不是「随机值猜不到」，而是同源策略——evil.com 的脚本读不到 bank.com 页面的 DOM，也读不到 bank.com 的响应体，所以它能让浏览器带上 Cookie，但写不出正确的 token。至于放 Cookie 里，如果只是放进去、服务端拿 Cookie 里的值和会话比对，那是**无效**的，因为 Cookie 会被自动携带，攻击者根本不需要读到它。正确做法是让 token 出现在「攻击者必须主动写入」的位置，也就是请求体参数或自定义请求头。前后端分离常用的 Double Submit 方案是把 token 放到一个非 HttpOnly 的 Cookie，前端 JS 读出来再塞进自定义 Header，服务端比对两者是否一致——这能生效是因为跨域的 evil.com 读不到那个 Cookie 的值，写不出对应的 Header，而且自定义 Header 还会触发 CORS 预检。

**Q：你会怎么测一个接口有没有 CSRF 防护？**

A：思路是「把攻击者拿不到的东西去掉，看服务端还认不认」。我会用 Burp 的 Repeater 走一组用例：删掉 token 参数、把 token 改一位、用 B 账号的 token 配 A 的 Cookie（验证有没有绑会话）、删掉 Origin 和 Referer、把 Origin 改成恶意域、把 POST 改成 GET 提交、把 Content-Type 换成 text/plain。期望全部返回 403。实际测下来最容易命中的是两个：一是 token 全局静态不绑会话，随便访问一次站点就能拿到有效值；二是接口同时支持 GET 和 POST，一个 img 标签就能触发。如果需要向开发演示，我会写一个自动提交表单的 PoC 页面，但只放在本地、只指向测试环境，绝不挂公网。

**Q：CSRF 和 XSS 的区别？现在前后端分离还需要防 CSRF 吗？**

A：区别在于脚本执行的位置。XSS 是攻击者的代码跑在受害站点自己的域里，同源策略对它不设防，它能读页面、读 Cookie、能发请求并读到响应，能力接近完全接管这个页面；CSRF 是在第三方域里借用浏览器自动带 Cookie 的特性发请求，读不到响应，只能做写操作。所以 XSS 危害更大，而且如果站点有 XSS，攻击者可以直接读走页面里的 CSRF token，CSRF 防护就废了——两者必须一起修。至于前后端分离，要看认证方式：如果用的是 Bearer Token 放在 localStorage、由 JS 显式塞进 Authorization 头，那浏览器不会自动携带，天然免疫 CSRF，但代价是换来了 XSS 能偷 token 的风险；只要还是用 Cookie 存会话，哪怕是 HttpOnly 的 JWT Cookie，CSRF 防护就一定要做。

## 参考

- [OWASP Cross-Site Request Forgery Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- [MDN：SameSite Cookie](https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Headers/Set-Cookie/SameSite)
- 相关笔记：[[XSS 三种类型与输出编码防御]]、[[认证与会话安全测试]]、[[Burp Suite 抓包改包工作流]]、[[OWASP Top 10 全景与测试切入点]]、[[10-安全测试]]
