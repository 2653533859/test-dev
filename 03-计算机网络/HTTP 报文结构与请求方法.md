---
created: 2026-07-31
tags: [计算机网络/HTTP]
---

# HTTP 报文结构与请求方法

> 接口测试的每一次断言，本质上都是在校验一段 HTTP 报文的某个字段。看不懂报文，就只能靠工具的图形界面猜。

## 概念

### 报文的物理结构

HTTP 报文是**纯文本**（HTTP/2 起改为二进制分帧，但语义不变），结构固定为四部分：

```text
<起始行>CRLF
<头部字段>: <值>CRLF
<头部字段>: <值>CRLF
CRLF                    ← 空行，头部结束的唯一标志
<消息体>
```

关键点：**空行（`\r\n\r\n`）是头部与消息体的分界**，解析器就是靠它判断头部读完了。这也意味着头部字段的值里不能出现裸的 CRLF——否则攻击者可以注入伪造的头部甚至伪造整个响应，这就是 **CRLF 注入 / HTTP 响应拆分漏洞**，安全测试的必测项。

### 请求报文

```text
POST /api/v1/orders?source=app HTTP/1.1
Host: api.example.com
Content-Type: application/json
Content-Length: 47
Authorization: Bearer eyJhbGciOiJIUzI1NiJ9...
User-Agent: pytest-client/1.0

{"sku_id": 10086, "qty": 2, "coupon": "NEW50"}
```

请求行三要素：**方法 + 请求目标 + 协议版本**。

- 方法：`POST`，**区分大小写，必须大写**
- 请求目标：`/api/v1/orders?source=app`，注意是**相对路径**（正向代理场景下才是完整 URL）
- 版本：`HTTP/1.1`

### 响应报文

```text
HTTP/1.1 201 Created
Content-Type: application/json; charset=utf-8
Content-Length: 62
Location: /api/v1/orders/98765
Date: Fri, 31 Jul 2026 06:12:44 GMT

{"order_id": 98765, "status": "created", "amount": "199.00"}
```

状态行三要素：**协议版本 + 状态码 + 原因短语**。原因短语（`Created`）纯粹给人看，程序绝不能依赖它做判断——不同服务端写法不一致，HTTP/2 里更是被彻底删除了。

### URL 各部分与谁有关

```text
https://user:pw@api.example.com:8443/v1/orders?page=2&size=20#section
└─┬─┘   └──┬──┘ └──────┬───────┘└─┬┘└───┬───┘└──────┬──────┘└──┬──┘
scheme   userinfo     host      port  path       query      fragment
```

一个高频面试点：**`#fragment` 不会发送给服务端**，它纯粹是浏览器本地用来定位锚点的。所以服务端日志里永远看不到 fragment，前端 SPA 路由用 hash 模式时服务端也拿不到路由信息。

另一个易错点：请求行里发送的是 `path?query`，而 `host` 是放在 `Host` 头里的——这是 HTTP/1.1 相比 1.0 的关键改进，正因为有了 `Host` 头，一台服务器才能用一个 IP 承载多个域名（虚拟主机）。

### 请求方法与它们的语义约定

| 方法 | 语义 | 安全 | 幂等 | 可缓存 | 通常带 Body |
|------|------|:----:|:----:|:------:|:----------:|
| GET | 获取资源 | 是 | 是 | 是 | 否 |
| HEAD | 只要响应头，不要 Body | 是 | 是 | 是 | 否 |
| POST | 提交数据 / 创建资源 | 否 | **否** | 一般否 | 是 |
| PUT | **整体替换**资源 | 否 | 是 | 否 | 是 |
| PATCH | **部分更新**资源 | 否 | 否（不保证） | 否 | 是 |
| DELETE | 删除资源 | 否 | 是 | 否 | 一般否 |
| OPTIONS | 查询支持的能力 / CORS 预检 | 是 | 是 | 否 | 否 |
| TRACE | 回显请求，用于诊断 | 是 | 是 | 否 | 否 |
| CONNECT | 建立隧道（HTTPS 代理） | 否 | 否 | 否 | 否 |

两个术语必须分清，这是面试高频陷阱：

- **安全（Safe）**：不会修改服务端资源。GET/HEAD/OPTIONS/TRACE 是安全的。
- **幂等（Idempotent）**：执行 N 次和执行 1 次，对服务端的**最终状态**影响相同。

**幂等说的是「最终状态」，不是「返回值相同」**。举例：`DELETE /orders/1` 第一次返回 200 删除成功，第二次返回 404 not found——返回值不同，但资源最终都是「不存在」这个状态，所以它是幂等的。

**PUT 幂等而 POST 不幂等**的原因：`PUT /orders/1` 指定了资源标识，重复执行就是重复覆盖同一个资源；`POST /orders` 每次都创建一个新订单，执行三次就有三个订单。

**PATCH 为什么不保证幂等**：如果 PATCH 的语义是「把库存减 1」，那执行三次就减了 3。只有当 PATCH 的载荷是「把字段设为某个绝对值」时才幂等。RFC 明确说明 PATCH 不保证幂等。

### 幂等性对测试的实际价值

这不是纯理论，它直接决定**重试策略是否安全**：

- 网关/客户端配置自动重试时，**只有幂等方法可以安全重试**。对 POST 做自动重试会导致重复下单、重复扣款。
- 所以支付、下单类接口必须由业务层提供**幂等键**（`Idempotency-Key` 头或业务流水号），这是接口测试必须覆盖的用例：**用同一个幂等键请求两次，第二次应返回第一次的结果而不是创建新记录。**

## 用法

### 用 curl 看完整报文

```bash
# -v 显示请求头（>）和响应头（<）
curl -v https://api.example.com/v1/orders/1

# --trace-ascii 输出最详尽的收发内容，包括 body 的十六进制
curl --trace-ascii - https://api.example.com/v1/orders/1

# 只看响应头（发的是 HEAD 请求）
curl -I https://api.example.com/v1/orders/1

# 发 GET 但只打印响应头（发的仍是 GET，适合 HEAD 被禁用的接口）
curl -sD - -o /dev/null https://api.example.com/v1/orders/1
```

### 各方法的调用示例

```bash
# GET 带查询参数（--get + --data-urlencode 会自动做 URL 编码，比手拼安全）
curl -G https://api.example.com/v1/orders \
  --data-urlencode "keyword=手机 壳" \
  --data-urlencode "page=2"

# POST JSON
curl -X POST https://api.example.com/v1/orders \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"sku_id": 10086, "qty": 2}'

# POST 表单
curl -X POST https://api.example.com/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=alice&password=secret"

# POST 文件上传（multipart/form-data，curl 会自动生成 boundary）
curl -X POST https://api.example.com/v1/upload \
  -F "file=@./report.pdf" \
  -F "biz_type=invoice"

# PUT 整体替换
curl -X PUT https://api.example.com/v1/orders/98765 \
  -H "Content-Type: application/json" \
  -d '{"sku_id": 10086, "qty": 5, "coupon": null}'

# PATCH 部分更新
curl -X PATCH https://api.example.com/v1/orders/98765 \
  -H "Content-Type: application/merge-patch+json" \
  -d '{"qty": 5}'

# DELETE
curl -X DELETE https://api.example.com/v1/orders/98765 -H "Authorization: Bearer $TOKEN"

# OPTIONS 查看接口支持哪些方法（看响应的 Allow 头）
curl -X OPTIONS -i https://api.example.com/v1/orders
```

### 三种 Content-Type 的报文长什么样

```text
# application/json
Content-Type: application/json

{"sku_id":10086,"qty":2}

# application/x-www-form-urlencoded（特殊字符要 URL 编码，空格变 + 或 %20）
Content-Type: application/x-www-form-urlencoded

sku_id=10086&qty=2&remark=%E5%8A%A0%E6%80%A5

# multipart/form-data（可传二进制，boundary 是分隔符）
Content-Type: multipart/form-data; boundary=----WebKitFormBoundaryABC123

------WebKitFormBoundaryABC123
Content-Disposition: form-data; name="biz_type"

invoice
------WebKitFormBoundaryABC123
Content-Disposition: form-data; name="file"; filename="report.pdf"
Content-Type: application/pdf

<二进制内容>
------WebKitFormBoundaryABC123--
```

### 用 Python 精确控制并校验报文

```python
import requests

resp = requests.post(
    "https://api.example.com/v1/orders",
    json={"sku_id": 10086, "qty": 2},        # json= 会自动设 Content-Type 并序列化
    headers={"Authorization": "Bearer xxx"},
    timeout=(3, 10),
)

# 看实际发出去的请求报文（调试利器）
req = resp.request
print(req.method, req.url)
print(req.headers)
print(req.body)

# 校验响应的各个层次
assert resp.status_code == 201
assert resp.headers["Content-Type"].startswith("application/json")
assert "Location" in resp.headers            # 201 应当返回新资源位置
assert resp.json()["status"] == "created"
```

### 幂等性用例怎么写

```python
import uuid
import requests

def test_create_order_idempotent():
    """同一个幂等键请求两次，应只创建一笔订单"""
    key = str(uuid.uuid4())
    payload = {"sku_id": 10086, "qty": 1}
    headers = {"Idempotency-Key": key, "Authorization": "Bearer xxx"}

    r1 = requests.post(URL, json=payload, headers=headers, timeout=10)
    r2 = requests.post(URL, json=payload, headers=headers, timeout=10)

    assert r1.status_code == 201
    # 第二次可能返回 200 或 201，但订单号必须是同一个
    assert r2.json()["order_id"] == r1.json()["order_id"]

    # 从查询侧再确认一次，防止服务端只是返回了缓存但实际创建了两笔
    listed = requests.get(f"{URL}?idempotency_key={key}", headers=headers).json()
    assert len(listed["items"]) == 1


def test_put_is_idempotent():
    """PUT 执行两次，资源状态应完全一致"""
    body = {"sku_id": 10086, "qty": 5}
    r1 = requests.put(f"{URL}/98765", json=body, timeout=10)
    r2 = requests.put(f"{URL}/98765", json=body, timeout=10)
    assert r1.status_code == r2.status_code == 200
    assert r1.json() == r2.json()
```

## 踩坑

1. **GET 请求带 Body 是「合法但不可靠」的**。RFC 9110 没有禁止，但明确说明「对 GET 请求的 Body 没有定义语义」。实际情况是：部分反向代理会直接丢弃它、部分 CDN 会拒绝请求、`requests` 支持但一些 HTTP 客户端库不支持。Elasticsearch 的 `_search` 接口历史上就吃过这个亏，后来同时支持了 POST。**结论：需要复杂查询条件就用 POST，不要赌中间设备的行为。**

2. **`Content-Length` 与实际 Body 长度不一致，导致请求走私**。如果手工构造报文（比如用 socket 直接发），长度算错会导致服务端一直等剩余数据（超时挂起）或把后续内容当成下一个请求。更严重的是 `Content-Length` 和 `Transfer-Encoding: chunked` 同时存在时，前后端解析优先级不同就会产生 **HTTP 请求走私（Request Smuggling）**漏洞。安全测试必测项。

3. **URL 长度限制不是协议规定的，而是实现限制**。RFC 没有规定上限，但 Nginx 默认 `large_client_header_buffers` 是 8k，IE 是 2083 字符，很多 CDN 限制 8k。GET 参数拼太长会返回 **414 URI Too Long** 或直接被截断。批量查询（比如传 1000 个 ID）必须改用 POST。

4. **PUT 用成了部分更新，导致字段被清空**。PUT 的语义是**整体替换**——没传的字段应当被置为默认值或 null。很多后端实现偷懒，把 PUT 写成了 PATCH 的行为。这是一个非常值得写用例的点：`PUT` 一个只含部分字段的 body，然后 GET 回来检查未传字段是否被正确清空。语义不一致会在前后端联调时爆雷。

5. **DELETE 被实现成非幂等**。规范要求 DELETE 幂等，但见过「第二次删除返回 500 空指针」的实现——因为代码里直接对查出来的 null 对象操作。用例设计上，**所有幂等方法都应该有「连续调用两次」的用例**。

6. **表单编码时空格的处理不一致**。`application/x-www-form-urlencoded` 里空格编码为 `+`，而 URL path 部分里空格编码为 `%20`。手工拼参数时用错会导致服务端拿到 `+` 字面量。**永远用库函数编码，不要手拼**：

   ```python
   from urllib.parse import urlencode, quote
   print(urlencode({"q": "手机 壳"}))     # q=%E6%89%8B%E6%9C%BA+%E5%A3%B3
   print(quote("手机 壳"))                # %E6%89%8B%E6%9C%BA%20%E5%A3%B3
   ```

7. **只断言状态码，不断言 Body**。`assert resp.status_code == 200` 是最弱的断言。见过接口返回 `200 OK` 但 body 是 `{"code": 50001, "msg": "系统繁忙"}` 的情况——很多国内后端习惯用 HTTP 200 包裹业务错误码。**用例必须同时断言 HTTP 状态码和业务码。**

8. **`Host` 头被忽略导致测试打错环境**。直接用 IP 访问但没带正确的 `Host` 头，Nginx 会匹配到默认 server 块，返回的是完全不同的站点。指定 IP 测试时要显式设置：

   ```bash
   curl -H "Host: api.example.com" http://10.0.2.30/v1/orders
   # HTTPS 场景还要指定 SNI
   curl --resolve api.example.com:443:10.0.2.30 https://api.example.com/v1/orders
   ```

## 面试怎么答

**Q：说一下 HTTP 请求报文的结构。**

A（30 秒骨架）：分四部分——请求行、请求头、空行、请求体。请求行是「方法 + 请求目标 + 协议版本」，比如 `POST /api/orders HTTP/1.1`；请求头是一堆 key: value；然后是一个空行，**这个空行是头部结束的唯一标志**；最后是可选的请求体。响应报文结构一样，只是第一行变成「协议版本 + 状态码 + 原因短语」。因为空行是分界符，头部值里不能出现裸的 CRLF，否则就是 CRLF 注入漏洞。

**Q：GET 和 POST 有什么区别？**

A：我会分三个层次答。**语义层**：GET 是安全且幂等的读操作，POST 是有副作用、不幂等的写操作，这是 RFC 定义的语义约定。**实现层**：GET 参数在 URL 里、POST 在 body 里；GET 可以被缓存、被浏览器历史记录和日志记录，POST 不会；GET 有 URL 长度限制（不是协议规定，是 Nginx/浏览器的实现限制，通常 8k 左右）。**安全性**：常说「POST 比 GET 安全」其实是误解——两者都是明文，抓包一样能看到，真正的安全靠 HTTPS。POST 的优势只是参数不会残留在浏览器历史、Referer 和服务端 access log 里。

**Q：什么是幂等？哪些方法是幂等的？**

A：幂等指执行一次和执行 N 次，对服务端的**最终状态**影响相同。注意说的是最终状态，不是返回值——`DELETE /orders/1` 第一次返回 200、第二次返回 404，返回值不同但资源最终都是不存在，所以它幂等。GET、HEAD、PUT、DELETE、OPTIONS 是幂等的，POST 和 PATCH 不是。这个概念在工作里非常实用：**只有幂等方法才能安全地配置自动重试**。所以支付、下单这类 POST 接口必须由业务层提供幂等键，我在测这类接口时一定会设计「同一幂等键重复请求」的用例，并且要从查询侧二次确认没有产生重复数据。

**Q：PUT 和 PATCH 的区别？**

A：PUT 是整体替换——请求体是资源的完整新状态，没传的字段应当被清空或置为默认值；PATCH 是部分更新，只改传过来的字段。另外 PUT 幂等，PATCH 不保证幂等（比如 PATCH 语义是「库存减 1」，执行三次就减了 3）。实际工作中我发现很多后端把 PUT 实现成了 PATCH 的行为，这是个很值得测的点：用 PUT 提交一个只含部分字段的 body，再 GET 回来看未传字段有没有被正确清空。语义不一致的话，前端按规范用 PUT 就会莫名其妙丢数据。

**Q：URL 里的 `#` 后面的内容会发给服务端吗？**

A：不会。fragment 是纯客户端的概念，浏览器用它定位页面锚点，不会放进 HTTP 请求。所以服务端 access log 里永远看不到它，SPA 用 hash 路由时服务端也拿不到路由信息——这也是为什么 hash 路由不需要服务端做 rewrite 配置，而 history 路由需要。

## 参考

- [RFC 9110 - HTTP Semantics](https://datatracker.ietf.org/doc/html/rfc9110)
- [MDN - HTTP 消息](https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Messages)
- [MDN - HTTP 请求方法](https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Methods)
- 相关笔记：[[HTTP 状态码分类与易混对比]]、[[HTTP 常见请求头与响应头]]、[[HTTP 长连接与 HTTP-2 多路复用]]、[[跨域与 CORS]]
