---
created: 2026-07-31
tags: [安全测试/注入]
---

# XSS 三种类型与输出编码防御

> XSS 的本质是「浏览器把数据当成了脚本」。三种类型的区别在于数据从哪来、在哪拼进页面，防御统一做在输出侧。

![[assets/xss-types.svg]]
*图示：反射型、存储型、DOM 型三条数据流路径对比——反射型随请求来随响应回，存储型落库后影响所有访问者，DOM 型全程在前端 JS 里流转、服务端和 WAF 都看不到。*

## 概念

### 一句话原理

服务端或前端把用户可控的数据**拼进了 HTML 文本**，浏览器解析这段 HTML 时，把其中的内容当作标签和脚本执行了。

和 SQL 注入同构：SQL 注入是数据混进了 SQL 语法树，XSS 是数据混进了 HTML/JS 语法树。**解释器变成了浏览器**。

### 三种类型的核心区别

| 维度 | 反射型 Reflected | 存储型 Stored | DOM 型 |
|------|-----------------|--------------|--------|
| 数据来源 | 本次请求的参数 | 数据库里已存的内容 | 前端能拿到的任意来源（URL、postMessage、localStorage） |
| 拼接位置 | 服务端渲染响应时 | 服务端渲染响应时 | 浏览器里的 JS |
| 服务端能否看到 payload | 能 | 能 | **不一定**（`#` 后的内容不发给服务端） |
| 影响范围 | 需诱导单个受害者点链接 | 所有访问该页面的人 | 需诱导点链接 |
| 危害等级 | 中 | **高** | 中～高 |
| 典型入口 | 搜索回显、错误提示、404 页 | 评论、昵称、工单标题、文件名 | 前端路由、锚点取值、模板渲染 |

**面试高频区分点**：反射型和存储型的差别是「payload 存不存」，不是「危害大小」；DOM 型的关键差别是「服务端全程没参与」，所以后端过滤和 WAF 都拦不住，必须审前端代码。

### DOM 型为什么特殊：source 与 sink

DOM 型 XSS 分析靠两个概念：

- **source（污染源）**：前端读取外部可控数据的地方。`location.href`、`location.search`、`location.hash`、`document.referrer`、`window.name`、`postMessage` 的 `event.data`、`localStorage`。
- **sink（危险汇聚点）**：把字符串当 HTML 或代码执行的地方。`innerHTML`、`outerHTML`、`document.write`、`eval`、`setTimeout(字符串)`、`new Function`、jQuery 的 `$(...)` 和 `.html()`。

**只要 source 的数据能不加处理地流到 sink，就存在 DOM XSS。**

```javascript
// 典型的 source → sink：hash 里的内容直接写进 innerHTML
const tab = location.hash.slice(1);
document.getElementById("title").innerHTML = "当前板块：" + tab;
```

因为 `#` 后面的内容浏览器不会发给服务端，抓包里根本看不到，服务端日志也没有——这就是为什么 DOM XSS 只能靠代码审计和前端调试来发现。

### 防御为什么必须做在输出侧

同一份数据 `a"b<c`，放在不同位置需要的编码完全不同：

```text
放进 HTML 文本节点   → 需要转义 < > & " '           （HTML 实体编码）
放进 HTML 属性值     → 属性必须加引号 + 实体编码
放进 <script> 里     → 需要 JS 字符串编码（\u 形式）
放进 URL 参数        → 需要 URL 编码（encodeURIComponent）
放进 CSS             → 需要 CSS 编码
```

**输入侧不知道这份数据以后会被输出到哪里**，所以在输入时统一转义会造成两个问题：一是编码方式选错，该转的没转住；二是数据被污染（用户名里真的有 `<` 时，数据库里存成了 `&lt;`，导出、比对、搜索全乱）。

正确原则：**入库存原文，输出时按上下文编码**。

## 用法

### 模板引擎的自动转义与它的缺口

主流模板引擎默认开启 HTML 转义，安全问题往往出在**开发主动关掉它**的地方：

```python
# Jinja2 / Flask：默认自动转义，以下三种写法会绕过它
# {{ content | safe }}        —— 显式标记为安全
# {% autoescape false %}      —— 整块关闭
# Markup(user_input)          —— 代码里包装成 Markup

# 正确：需要富文本时先净化再标记安全
import bleach
ALLOWED_TAGS = ["p", "br", "strong", "em", "ul", "ol", "li", "a"]
ALLOWED_ATTRS = {"a": ["href", "title"]}
clean = bleach.clean(user_html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
```

Vue / React 的对应缺口：

```text
Vue    v-html="userInput"                 关闭了默认转义
React  dangerouslySetInnerHTML={{...}}     命名已经在警告你
Angular bypassSecurityTrustHtml(...)
```

代码审计时直接搜这几个关键字，基本能定位到所有高风险点。

### 前端 sink 的安全替代

```javascript
// 危险：把字符串当 HTML 解析
el.innerHTML = "当前板块：" + tab;

// 安全：当纯文本插入，标签不会被解析
el.textContent = "当前板块：" + tab;

// 需要设置属性时用 setAttribute，且 href 要校验协议
const url = new URL(userUrl, location.origin);
if (!["http:", "https:"].includes(url.protocol)) throw new Error("协议不允许");
link.setAttribute("href", url.href);      // 防 javascript: 伪协议
```

`javascript:` 伪协议是很容易漏掉的一类：`<a href="javascript:...">` 即使做了 HTML 实体编码也照样执行，因为它不依赖尖括号。**凡是用户可控的 URL，都要校验协议白名单。**

### 纵深防御：CSP 与 Cookie 属性

```text
Content-Security-Policy: default-src 'self'; script-src 'self' 'nonce-{随机值}'; object-src 'none'; base-uri 'self'
```

CSP 的作用是「即使有 XSS，脚本也执行不了 / 数据也传不出去」。关键点：

- 必须去掉 `unsafe-inline`，否则内联脚本照样能跑，CSP 形同虚设；
- 用 nonce 或 hash 放行必要的内联脚本；
- `object-src 'none'` 和 `base-uri 'self'` 常被忽略，但能挡掉几类绕过。

Cookie 侧：`HttpOnly` 让 JS 读不到会话 Cookie，能把「XSS 直接盗会话」这条最短路径掐掉（但 XSS 仍可代替用户发请求，所以只是缓解）。

### 在授权靶场里怎么验证

用 **DVWA 的三个 XSS 模块** 或 **Juice Shop** 练手。探针一律用无害的 `alert(1)` 或 `console.log(1)`，不使用任何外传数据的脚本。

**反射型验证：**

```bash
# 本地靶场，观察参数是否原样出现在响应 HTML 里
curl -s "http://127.0.0.1:8080/vulnerabilities/xss_r/?name=probe123" | grep -o 'probe123.\{0,40\}'
```

先看数据落在了 HTML 的什么位置——文本节点里、属性值里、还是 `<script>` 里，位置决定了要不要闭合引号或标签。再看特殊字符是否被转成了实体：

```text
输入 probe<">123
响应里出现 probe&lt;&quot;&gt;123   → 已做实体编码，安全
响应里出现 probe<">123             → 原样输出，存在风险
```

**存储型验证：**

在评论/昵称里提交无害探针，然后**换一个账号**打开列表页，看是否触发。存储型的关键是「影响他人」，所以必须用第二个账号确认。测完记得删掉测试数据，别留在共享测试环境里。

**DOM 型验证：**

抓包看不到，必须用浏览器开发者工具：

```text
1. Sources 面板全局搜 innerHTML / document.write / eval / $(  
2. 对每个命中处，反查它的数据来自哪个 source
3. 在赋值那一行打断点，改 URL hash 后刷新，观察变量值
4. 用 textContent 替换验证修复是否生效
```

## 踩坑

1. **只在输入侧过滤**。既挡不全（不同输出上下文需要的编码不同），又污染数据（用户名里的 `<` 被永久存成 `&lt;`）。正确做法是入库存原文、输出按上下文编码。
2. **黑名单过滤 `<script>`**。事件属性 `onerror`、`onload`，`javascript:` 伪协议，`<svg>`、`<img>` 标签都能触发脚本，不带 `script` 字样。黑名单必然漏。
3. **富文本场景直接放行**。富文本确实需要保留标签，但必须用成熟的净化库做**标签+属性白名单**（Python 用 bleach，JS 用 DOMPurify），不能自己写正则。
4. **忽略属性上下文**。`<div title={{ v }}>` 属性没加引号时，即使做了实体编码，输入 `x onmouseover=alert(1)` 照样能注入新属性。属性值必须加引号。
5. **URL 参数只做 HTML 编码**。`<a href="{{ url }}">` 里如果 url 是 `javascript:alert(1)`，HTML 编码完全无效。要额外校验协议白名单。
6. **CSP 配了但留着 `unsafe-inline`**。等于没配。上线前用浏览器控制台确认 CSP 真的在拦截。
7. **DOM XSS 用抓包工具找**。`#` 后的内容不发给服务端，Burp 的 history 里什么都看不到，只能审前端代码。这是最容易漏测的一类。
8. **存储型探针没清理**。`alert(1)` 留在测试环境的评论区，其他同学做功能测试时不停弹窗。测完必须删数据。
9. **只测了前台没测后台**。存储型 XSS 打管理员是最经典的提权路径：用户提交的内容在运营后台被渲染，一旦有 XSS，攻击者拿到的是管理员权限。后台的展示页必须一起测。

## 面试怎么答

**Q：XSS 有哪几种？区别是什么？**

A：三种。反射型是参数随请求进来、随响应回显，payload 不落库，需要诱导目标点链接，一次影响一个人；存储型是 payload 存进了数据库，之后所有打开该页面的人都会中招，危害最大，典型入口是评论、昵称、工单标题；DOM 型的特殊之处在于数据全程在前端 JS 里流转，服务端完全没参与，比如从 `location.hash` 取值直接写进 `innerHTML`，因为 `#` 后的内容不会发给服务端，抓包和后端 WAF 都看不到，只能通过审前端代码找 source 到 sink 的链路。另外补一句，2021 版 OWASP Top 10 把 XSS 归到了 A03 注入类别里。

**Q：XSS 的防御做在输入还是输出？为什么？**

A：必须做在输出。核心原因是同一份数据在不同输出位置需要的编码方式完全不同——放在 HTML 文本里要实体编码，放在属性里要实体编码且属性得加引号，放进 `<script>` 里要 JS 字符串编码，放进 URL 里要 URL 编码。输入的时候根本不知道这份数据以后会被输出到哪，统一转义要么选错编码方式挡不住，要么污染数据，比如用户名里本来就有尖括号，存进库变成实体后，导出和搜索全乱套。所以正确做法是入库存原文、输出时按上下文编码，模板引擎的自动转义就是干这个的，重点审的是开发主动关掉转义的地方，比如 Jinja2 的 `|safe`、Vue 的 `v-html`、React 的 `dangerouslySetInnerHTML`。富文本场景保留标签是刚需，那就用 DOMPurify 或 bleach 做标签属性白名单净化，不要自己写正则。

**Q：除了编码，还有什么纵深防御手段？**

A：主要两个。一是 CSP，通过 `script-src` 限制脚本只能从可信来源加载，这样即使被注入了脚本也执行不了，但前提是必须去掉 `unsafe-inline`，否则内联脚本照跑，CSP 就白配了，需要放行的内联脚本用 nonce 或 hash。二是 Cookie 加 `HttpOnly`，让 JS 读不到会话 Cookie，把「XSS 直接盗会话」这条最短路径掐掉；不过要注意这只是缓解，XSS 仍然可以代替用户在当前页面发请求做操作，所以根治还是得靠输出编码。

**Q：XSS 和 CSRF 有什么区别？**

A：立足点完全不同。XSS 是攻击者的脚本在**受害站点自己的域**里执行，因此同源策略对它不设防，它能读页面内容、读 Cookie（没加 HttpOnly 时）、能任意发请求并读到响应，能力接近「完全接管这个页面」。CSRF 是在**第三方域**里，借用浏览器会自动携带 Cookie 的特性让受害者发出一个请求，攻击者读不到响应，只能做「写操作」。所以危害上 XSS 明显更大，而且如果站点存在 XSS，攻击者可以直接读走 CSRF token，CSRF 的防护就失效了——这也是为什么两者必须一起修。

## 参考

- [OWASP Cross Site Scripting Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html)
- [OWASP DOM based XSS Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/DOM_based_XSS_Prevention_Cheat_Sheet.html)
- [MDN：Content Security Policy](https://developer.mozilla.org/zh-CN/docs/Web/HTTP/CSP)
- 相关笔记：[[CSRF 原理与 Token 防护]]、[[SQL 注入原理与参数化防御]]、[[认证与会话安全测试]]、[[OWASP Top 10 全景与测试切入点]]、[[10-安全测试]]
