---
created: 2026-07-31
tags: [计算机网络/HTTP]
---

# HTTP 状态码分类与易混对比

> 状态码是服务端给出的**第一层归因**：4xx 说「是你的问题」，5xx 说「是我的问题」。测试的价值在于验证这个归因有没有搞反。

## 概念

### 五大类

| 类别 | 含义 | 记忆 |
|------|------|------|
| 1xx | 信息性，请求已收到，继续处理 | 很少见 |
| 2xx | 成功 | 干成了 |
| 3xx | 重定向，需要进一步动作 | 换个地方找 |
| 4xx | 客户端错误 | **你错了** |
| 5xx | 服务端错误 | **我错了** |

**4xx / 5xx 的分界线极其重要**：它决定了故障责任归属，也决定了监控告警该不该响。一个把参数校验失败返回成 500 的接口，会污染整个服务的错误率指标，让真正的故障淹没在噪声里。这是接口测试中一定要提的缺陷。

### 常见状态码速查

```text
2xx  200 OK                成功，GET/PUT/PATCH 的常态
     201 Created           创建成功，应带 Location 头指向新资源
     202 Accepted          已接受但异步处理中（如提交批量任务）
     204 No Content        成功但无返回体，DELETE 的常态
     206 Partial Content   断点续传/分片下载，配合 Range 头

3xx  301 Moved Permanently 永久重定向
     302 Found             临时重定向
     303 See Other         POST 后跳转到 GET（PRG 模式）
     304 Not Modified      协商缓存命中，无 body
     307 Temporary Redirect 临时重定向，保持原方法
     308 Permanent Redirect 永久重定向，保持原方法

4xx  400 Bad Request       请求格式/参数错误
     401 Unauthorized      未认证（其实是「你是谁」没搞清楚）
     403 Forbidden         已认证但无权限
     404 Not Found         资源不存在
     405 Method Not Allowed 路径存在但方法不对
     408 Request Timeout   客户端发得太慢，服务端等超时
     409 Conflict          状态冲突（如重复创建、并发修改）
     413 Payload Too Large 请求体太大
     414 URI Too Long      URL 太长
     415 Unsupported Media Type  Content-Type 不支持
     422 Unprocessable Entity    格式对但语义错（参数校验失败）
     429 Too Many Requests 限流

5xx  500 Internal Server Error  服务端代码异常（兜底）
     501 Not Implemented   服务端不支持该方法
     502 Bad Gateway       网关拿到了上游的无效响应
     503 Service Unavailable    服务不可用（过载/维护中）
     504 Gateway Timeout   网关等上游超时
```

### 易混对比一：301 vs 302 vs 307/308

| | 301 | 302 | 307 | 308 |
|---|-----|-----|-----|-----|
| 永久/临时 | 永久 | 临时 | 临时 | 永久 |
| 浏览器缓存 | **会缓存**（强缓存） | 不缓存 | 不缓存 | 会缓存 |
| 方法是否保持 | 可能被改成 GET | 可能被改成 GET | **严格保持** | **严格保持** |
| SEO 权重 | 转移到新地址 | 不转移 | 不转移 | 转移 |

**301 最大的坑是浏览器会永久缓存**。一旦线上误配了 301（比如把 http 跳到一个错误的 https 地址），用户浏览器会记住这个跳转，即使服务端修好了，老用户仍然会跳到错的地方，除非清缓存。所以**不确定是不是永久的时候，一律先用 302**。

**307/308 存在的原因**：历史上浏览器对 301/302 的实现不规范，收到 302 后经常把 POST 改成 GET 并丢弃 body。307/308 是 RFC 后来补充的、明确要求「必须保持原方法和 body」的版本。测重定向接口时这是关键差异点。

### 易混对比二：401 vs 403

这是面试最爱问的一对，也是实际项目里最常被实现错的一对。

- **401 Unauthorized**：**身份未验证**。名字有误导性——它实际的意思是 "Unauthenticated"（未认证）。含义是「我不知道你是谁，请提供凭证」。**规范要求 401 响应必须带 `WWW-Authenticate` 头**告诉客户端该怎么认证。
- **403 Forbidden**：**身份已验证，但没有权限**。含义是「我知道你是谁，但你不能干这个」。重新登录也没用。

判断口诀：**401 换个凭证可能就行了，403 换个凭证也没用，得换个人。**

典型场景：

```text
没带 token / token 过期 / token 签名错误   → 401
token 有效，但你是普通用户想删别人的订单   → 403
IP 不在白名单                              → 403
```

有一种特殊做法：为了防止攻击者通过状态码探测资源是否存在（**资源枚举**），有些系统会把「无权限访问某资源」返回成 **404** 而不是 403。GitHub 访问别人的私有仓库就是返回 404。这是有意的安全设计，测试时要先确认产品预期，别当 bug 提。

### 易混对比三：502 vs 503 vs 504

三个都是「服务端不行了」，但责任方完全不同，这直接决定了你该找谁：

- **502 Bad Gateway**：网关（Nginx/LB）**成功连上了上游，但上游返回了无效响应**——上游进程崩了、返回了乱七八糟的数据、连接被上游中途 RST。**说明上游应用挂了或不稳定。**
- **504 Gateway Timeout**：网关连上了上游，但**在超时时间内没等到完整响应**。**说明上游还活着，只是太慢**——慢 SQL、死锁、外部依赖卡住、线程池排队。
- **503 Service Unavailable**：服务**主动**告知不可用，通常是过载保护、熔断降级、发布维护中。规范建议带 `Retry-After` 头告诉客户端多久后重试。

一句话区分：**502 是「上游死了」，504 是「上游慢死了」，503 是「我主动不干了」**。

排查路径也完全不同：

```text
502 → 看上游应用进程是否存活、有没有 OOM、有没有崩溃日志
504 → 看上游的慢请求日志、DB 慢查询、下游依赖的响应时间；同时确认网关的 proxy_read_timeout 是否设得过短
503 → 看是不是熔断器打开了、是不是达到了限流阈值、是不是在灰度发布
```

### 易混对比四：400 vs 422

- **400 Bad Request**：请求本身**格式**就不对——JSON 语法错误、Content-Type 不匹配、缺少必填字段导致无法解析。
- **422 Unprocessable Entity**：格式完全正确，服务端能解析，但**语义上不合法**——比如 `{"age": -5}`，JSON 没问题，但年龄不能是负数。

很多框架（如 Spring Validation、FastAPI）用 422 表示参数校验失败。这个区分不是强制的，但团队内部应当统一，否则客户端没法做统一的错误处理。

### 易混对比五：200 包裹业务错误码

国内很多后端喜欢这样：

```json
HTTP/1.1 200 OK

{"code": 50001, "message": "库存不足", "data": null}
```

无论业务成功失败，HTTP 状态码永远是 200，靠 body 里的 `code` 区分。

这种设计的问题：

- **监控失真**：网关和 APM 按 HTTP 状态码统计错误率，所有故障都被记成成功，错误率永远是 0%。
- **无法利用 HTTP 语义**：CDN 会缓存 200 响应，把错误响应也缓存了；客户端的自动重试机制无法判断该不该重试。
- **链路追踪断裂**：APM 工具无法自动标记异常 span。

作为测试，遇到这种设计要在评审阶段提出来。如果历史包袱改不了，那么**用例必须同时断言 HTTP 状态码和业务 code**，且监控要基于业务 code 单独配置。

## 用法

### 快速查看状态码

```bash
# 只输出状态码，适合脚本判断
curl -o /dev/null -s -w "%{http_code}\n" https://api.example.com/v1/orders/1

# 看重定向链条：从哪跳到哪，跳了几次
curl -sIL https://example.com | grep -iE '^(HTTP/|location:)'
# HTTP/1.1 301 Moved Permanently
# location: https://example.com/
# HTTP/2 200

# -L 跟随重定向，--max-redirs 限制次数防止死循环
curl -sL --max-redirs 5 -o /dev/null -w "%{http_code} 最终地址:%{url_effective}\n" http://example.com
```

### 验证重定向是否保持方法

```bash
# 302：很多客户端会把 POST 改成 GET（观察最终请求）
curl -v -X POST -d "a=1" -L http://example.com/old-api

# 307：必须保持 POST 和 body
curl -v -X POST -d "a=1" -L http://example.com/moved-api
```

在 `requests` 里可以直接检查跳转历史：

```python
import requests

r = requests.post("http://example.com/old-api", data={"a": 1}, allow_redirects=True)
for h in r.history:
    print(h.status_code, h.url, "→", h.headers.get("Location"))
print("最终:", r.status_code, r.url, r.request.method)   # 看 method 有没有被改成 GET
```

### 验证 304 协商缓存

```bash
# 第一次请求，记录 ETag
ETAG=$(curl -sI https://example.com/app.js | grep -i '^etag:' | awk '{print $2}' | tr -d '\r')
echo "ETag=$ETAG"

# 带 If-None-Match 再请求，应返回 304 且无 body
curl -sI -H "If-None-Match: $ETAG" https://example.com/app.js | head -1
# HTTP/2 304
```

### pytest 里的状态码断言

```python
import pytest
import requests

BASE = "https://api.example.com/v1"


@pytest.mark.parametrize("payload,expected_status,expected_code", [
    ({"sku_id": 10086, "qty": 1},   201, None),        # 正常创建
    ({"sku_id": 10086},             422, "PARAM_MISS"), # 缺必填 → 语义错误
    ({"sku_id": 10086, "qty": -1},  422, "PARAM_INVALID"),
    ({"sku_id": 999999, "qty": 1},  404, "SKU_NOT_FOUND"),
    ({"sku_id": 10086, "qty": 99999}, 409, "STOCK_NOT_ENOUGH"),
])
def test_create_order_status(payload, expected_status, expected_code, auth_headers):
    r = requests.post(f"{BASE}/orders", json=payload, headers=auth_headers, timeout=10)
    assert r.status_code == expected_status, f"实际返回 {r.status_code}: {r.text[:200]}"
    if expected_code:
        assert r.json()["code"] == expected_code


def test_401_without_token():
    r = requests.get(f"{BASE}/orders", timeout=10)
    assert r.status_code == 401
    # 规范要求 401 必须带 WWW-Authenticate
    assert "WWW-Authenticate" in r.headers


def test_403_other_user_resource(auth_headers_user_b):
    """用户 B 的 token 去访问用户 A 的订单，应当 403 而不是 200"""
    r = requests.get(f"{BASE}/orders/{USER_A_ORDER_ID}", headers=auth_headers_user_b, timeout=10)
    assert r.status_code in (403, 404), "越权漏洞：B 能看到 A 的订单"


def test_405_wrong_method(auth_headers):
    r = requests.request("TRACE", f"{BASE}/orders", headers=auth_headers, timeout=10)
    assert r.status_code == 405
    assert "Allow" in r.headers        # 405 应告知支持哪些方法
```

### 从日志统计状态码分布

```bash
# 从 Nginx access.log 统计状态码分布（假设状态码是第 9 列）
awk '{print $9}' /var/log/nginx/access.log | sort | uniq -c | sort -rn

# 找出所有 5xx 的请求，看集中在哪些接口
awk '$9 ~ /^5/ {print $7}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -20

# 统计 504 的耗时分布，验证是不是卡在网关超时阈值上（假设最后一列是 request_time）
awk '$9 == 504 {print $NF}' /var/log/nginx/access.log | sort -n | tail -5
```

## 踩坑

1. **把参数校验失败返回成 500**。后端没做入参校验，非法参数直接进业务逻辑抛空指针，被全局异常处理器兜成 500。危害：污染错误率指标、触发不必要的告警、客户端无法区分「我传错了」和「服务挂了」而做出错误的重试决策。这是接口测试的必测项——**用各种非法入参轰接口，任何一个返回 5xx 的都是缺陷**。

2. **404 到底是哪一层返回的分不清**。同样是 404，可能是：Nginx 找不到 location 规则（返回 Nginx 默认的 HTML 页面）、应用框架没匹配到路由（返回框架的 JSON）、业务逻辑判断资源不存在（返回业务的 JSON）。区分方法是看 `Server` 响应头和 body 格式。找错层会浪费大量排查时间。

3. **误配 301 后无法回滚**。前面提过，浏览器会永久缓存 301。生产事故案例：运维把 `www.example.com` 301 到了一个测试域名，5 分钟后改回来，但已经访问过的用户浏览器持续跳错，客服电话被打爆。**规避原则：拿不准就用 302；确实要用 301，先在预发环境用不同浏览器完整验证。**

4. **测试环境的 502 和生产的 502 原因往往不同**。测试环境通常是「后端服务压根没启动」，生产则更多是「服务 OOM 重启」或「上游主动 RST」。别把测试环境的经验直接套到生产排查上。

5. **504 时只查后端，忘了查网关配置**。网关的 `proxy_read_timeout` 默认 60 秒，如果某个报表接口本来就要跑 90 秒，那 504 是网关配置问题不是后端慢。排查 504 要**同时看两端**：后端日志里这个请求实际跑了多久、网关配置的超时是多少。

   ```text
   location /api/report {
       proxy_pass http://backend;
       proxy_connect_timeout 5s;      # 与上游建连的超时
       proxy_send_timeout 60s;        # 向上游发送请求的超时
       proxy_read_timeout 120s;       # 等上游响应的超时 ← 504 通常卡在这
   }
   ```

6. **429 限流没有配 `Retry-After`，客户端无脑重试打成雪崩**。限流的目的是保护服务，但如果客户端收到 429 立刻重试，反而加剧压力。规范要求 429 和 503 应带 `Retry-After` 头。测限流功能时，除了验证「超过阈值确实被拦」，还要验证**响应头是否引导客户端合理退避**。

7. **只测正常路径，不测状态码本身的正确性**。很多团队的接口用例只有「传对参数返回 200」。真正有价值的用例矩阵是：无 token → 401、越权 → 403、路径不存在 → 404、方法不对 → 405、参数非法 → 400/422、超限流 → 429。**这套「错误码矩阵」应当作为每个接口的基础用例模板。**

8. **HEAD 请求返回了 Body**。规范要求 HEAD 响应不能有 body，但响应头（包括 `Content-Length`）应当和 GET 一致。有些自研框架实现错误，导致 CDN 和监控探针行为异常。

## 面试怎么答

**Q：301 和 302 的区别？**

A：301 是永久重定向，302 是临时。最关键的实际差异是**301 会被浏览器强缓存**——一旦用户访问过，即使服务端后来改了配置，浏览器仍然会跳到缓存的地址，除非清缓存。所以线上配跳转时，只要不能 100% 确定是永久的，一律先用 302。另外 301 会把 SEO 权重转移到新地址，302 不会。还有一对容易被忽略的是 307 和 308：历史上浏览器对 301/302 实现不规范，收到后经常把 POST 改成 GET 并丢弃 body，307（临时）和 308（永久）是规范后来补的、明确要求必须保持原方法和 body 的版本。

**Q：401 和 403 的区别？**

A：401 是**未认证**——我不知道你是谁，请提供凭证。虽然它的名字是 Unauthorized，但实际语义是 Unauthenticated，规范还要求 401 响应必须带 `WWW-Authenticate` 头告诉客户端怎么认证。403 是**已认证但无权限**——我知道你是谁，但你不能干这个，重新登录也没用。判断口诀是「401 换凭证可能行，403 换凭证也没用」。补充一点：有些系统出于防资源枚举的考虑，会把无权限访问返回成 404 而不是 403，比如 GitHub 访问别人的私有仓库，这是有意的安全设计，测的时候要先确认产品预期。

**Q：502 和 504 的区别，分别怎么排查？**

A：两个都是网关返回的。502 Bad Gateway 是网关连上了上游但**收到无效响应**——上游进程崩了、返回了非法数据、或者连接被上游 RST，说明**上游死了**。504 Gateway Timeout 是网关在超时时间内**没等到完整响应**，说明上游还活着只是**太慢**。排查方向完全不同：502 去看上游进程是否存活、有没有 OOM 和崩溃日志；504 去看上游的慢请求、慢 SQL、外部依赖耗时，同时**还要检查网关自己的 proxy_read_timeout 是不是设得太短**——我遇到过报表接口本来就要跑 90 秒但网关只等 60 秒的情况，那是配置问题不是后端问题。

**Q：接口返回 200 但 body 里是错误码，你怎么看？**

A：这是国内很常见的设计，但我认为是反模式。问题有三个：一是监控失真，网关和 APM 按 HTTP 状态码算错误率，所有故障都被记成成功，错误率永远 0%，真出事了告警不响；二是 CDN 会缓存 200 响应，可能把错误响应也缓存了；三是客户端和网关的自动重试机制无法判断该不该重试。如果是新项目我会在接口设计评审时推动用规范的状态码。如果是存量系统改不了，那我的用例必须**同时断言 HTTP 状态码和业务 code**，并且推动监控侧基于业务 code 单独配告警。

**Q：你会为一个新接口设计哪些状态码相关的用例？**

A：我有一套固定的「错误码矩阵」模板：不带 token → 401 且带 WWW-Authenticate；用别人的 token 访问 → 403 或 404（看产品设计）；不存在的资源 ID → 404；用错方法（比如 GET 接口发 DELETE）→ 405 且响应带 Allow 头；必填参数缺失、类型错误、边界越界 → 400 或 422，**绝不能是 500**；超频调用 → 429 且带 Retry-After。这套跑完，接口的健壮性基本就有底了。特别强调那条「非法入参绝不能返回 5xx」——这是最容易发现的真实缺陷。

## 参考

- [RFC 9110 - HTTP Semantics: Status Codes](https://datatracker.ietf.org/doc/html/rfc9110#section-15)
- [MDN - HTTP 响应状态码](https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Status)
- 相关笔记：[[HTTP 报文结构与请求方法]]、[[HTTP 常见请求头与响应头]]、[[正向代理与反向代理]]、[[Cookie、Session、Token 与 JWT 的区别与适用场景]]
