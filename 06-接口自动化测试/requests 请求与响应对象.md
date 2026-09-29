---
created: 2026-07-31
tags: [接口自动化测试/requests]
---

# requests 请求与响应对象

> 搞清楚 `requests.get()` 这一行背后发生了什么，才能知道超时、编码、重定向、流式下载这些问题该在哪一层解决。

![[assets/requests-request-response-flow.svg]]
*图示：从顶层 API 到 Response 对象的完整流转——params/data/json 在 ③④ 阶段定型，响应体默认在 ⑧ 全量读入内存。*

## 概念

### 四个核心对象

requests 的整个模型只有四个对象，看懂它们的关系，90% 的疑难杂症都能自己推理出答案：

| 对象 | 角色 | 关键点 |
|------|------|--------|
| `Request` | 你写的「意图」 | 只是参数容器，还没有被编码 |
| `PreparedRequest` | 真正要发出去的报文快照 | URL 已拼好、body 已编码、header 已定型，**不可变** |
| `Response` | 服务端回来的结果 | 默认已把 body 全部读进内存 |
| `Session` | 会话上下文 | 持有 CookieJar、连接池、默认 header、Adapter |

`requests.get(url)` 是个**便捷函数**：它内部临时 `with sessions.Session() as session:` 建一个 Session，发完就扔。所以裸函数调用既不保持 Cookie，也不复用连接。

### prepare 阶段做了什么

这是最值得记住的一段。`Session.prepare_request()` 会做这些事：

1. 把 `session.headers` 与本次 `headers` **合并**（本次优先，值为 `None` 表示删除该头）
2. 把 `session.cookies` 与本次 `cookies` 合并，序列化成 `Cookie` 请求头
3. 处理 `params`：URL-encode 后拼到 query string
4. 处理 body：`data` / `json` / `files` 三选一（见 [[requests 的 params、data 与 json 参数区别]]），并**自动补 `Content-Type` 和 `Content-Length`**
5. 应用 `auth`（如 `HTTPBasicAuth` 会算出 `Authorization: Basic xxx`）

一旦 `PreparedRequest` 生成，请求内容就固定了。这解释了一个常见困惑：**为什么在 response hook 里改 `r.request.headers` 没有任何效果**——报文早就发出去了。

### 为什么 Response 拿到就已经「读完了」

`r.content` 默认在 `Session.send()` 里就被完整读取（`content=True`），这样连接才能尽快归还给连接池。代价是**下载大文件时会把整个文件塞进内存**。要惰性读就得 `stream=True`，此时连接会一直占着，直到你读完或 `r.close()`。

## 用法

### 检查真正发出去的报文

调试接口时最有用的一招：不要猜，直接把 `PreparedRequest` 打出来。

```python
import requests

req = requests.Request(
    method="POST",
    url="https://httpbin.org/post",
    params={"page": 1, "kw": "订单 查询"},
    json={"order_id": 100231, "amount": 19.9},
    headers={"X-Trace-Id": "t-001"},
)
prepared = requests.Session().prepare_request(req)

print(prepared.method)   # POST
print(prepared.url)      # https://httpbin.org/post?page=1&kw=%E8%AE%A2%E5%8D%95+%E6%9F%A5%E8%AF%A2
print(dict(prepared.headers))
# {'X-Trace-Id': 't-001', 'Content-Length': '35', 'Content-Type': 'application/json'}
print(prepared.body)     # b'{"order_id": 100231, "amount": 19.9}'
```

注意 `Content-Type: application/json` 是 requests **自动加的**，你没写。中文被 URL 编码成 `%E8%AE%A2...` 也是自动的。

发送这个 prepared 对象：

```python
with requests.Session() as s:
    r = s.send(prepared, timeout=(3, 10))
    print(r.status_code)
```

### Response 常用属性的取值边界

```python
import requests

r = requests.get("https://httpbin.org/json", timeout=5)

r.status_code      # int，200
r.ok               # bool，status_code < 400（注意 3xx 也算 ok）
r.reason           # 'OK'
r.headers          # 大小写不敏感的字典：r.headers['content-type'] 也能取到
r.encoding         # 'utf-8' 或 None
r.text             # str，用 r.encoding 解码 r.content 得到
r.content          # bytes，原始字节
r.json()           # dict/list，等价于 json.loads(r.text)
r.elapsed          # timedelta，从发出到收到响应头的耗时（不含 body 下载）
r.url              # 最终 URL（重定向后的）
r.history          # 重定向链上的 Response 列表，没重定向就是 []
r.cookies          # 本次响应的 Cookie
r.request          # 对应的 PreparedRequest，排查时很有用
```

### 处理编码：`r.text` 中文乱码的根因

`r.encoding` 的推断规则是：

1. 响应头 `Content-Type` 里有 `charset=xxx` → 用它
2. 没有 charset，但 Content-Type 是 `text/*` → **HTTP/1.1 规范默认 ISO-8859-1**
3. 都没有 → `None`，此时 `r.text` 会用 `chardet`/`charset_normalizer` 猜

第 2 条就是中文乱码的元凶：服务端返回 `Content-Type: text/html`（不带 charset）但内容是 UTF-8，requests 按 ISO-8859-1 解码，全成了 `ä¸­æ`。

```python
r = requests.get(url)
if r.encoding == "ISO-8859-1":
    # 用 <meta charset> 或响应内容猜出来的编码覆盖
    r.encoding = r.apparent_encoding   # 或直接写死 'utf-8'
print(r.text)

# 更稳的做法：绕过 r.text，自己解码
print(r.content.decode("utf-8"))
```

顺带说：`r.json()` **不受 `r.encoding` 影响**——它内部会先按 JSON 规范探测 BOM 和 UTF-8/16/32，所以 `r.text` 乱码但 `r.json()` 正常是完全可能的。

### 非 2xx 不会抛异常

这是 requests 最容易误伤新手的设计：**HTTP 错误状态码不是 Python 异常**。

```python
r = requests.get("https://httpbin.org/status/500")
print(r.status_code)   # 500
r.json()               # 这里才炸：json.decoder.JSONDecodeError

# 想让它抛异常，显式调用：
r.raise_for_status()   # requests.exceptions.HTTPError: 500 Server Error
```

封装请求层时的推荐写法：

```python
def request(self, method, path, **kwargs):
    r = self.session.request(method, self.base_url + path, **kwargs)
    # 记录日志，失败排查全靠它
    logger.info("%s %s -> %s (%.0fms) body=%.500s",
                method, r.url, r.status_code,
                r.elapsed.total_seconds() * 1000, r.text)
    return r   # 注意：不在这里 raise_for_status，把断言权交给用例层
```

**为什么不在封装层 raise**：接口测试要测的恰恰包含 4xx/5xx 场景（参数非法应该返回 400），封装层一抛异常，用例就没法断言错误码了。

### 重定向与 history

```python
r = requests.get("https://httpbin.org/redirect/2")
print(r.url)                              # 最终落地 URL
print([h.status_code for h in r.history]) # [302, 302]

# 关掉自动重定向，专门测 302 本身
r = requests.get("https://httpbin.org/redirect/1", allow_redirects=False)
print(r.status_code, r.headers["Location"])   # 302 /get
```

测「未登录访问受限页面应该跳登录页」这类用例时，必须 `allow_redirects=False`，否则你断言到的是登录页的 200，而不是那个 302。

### 流式下载与 stream

```python
with requests.get(url, stream=True, timeout=(3, 30)) as r:
    r.raise_for_status()
    with open("big.zip", "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
```

`stream=True` 时**必须用 `with` 或手动 `r.close()`**，否则连接不会归还连接池，量一大就把池耗尽。

## 踩坑

1. **`r.ok` 把 3xx 当成功**：`r.ok` 是 `status_code < 400`，302 也是 `True`。断言成功用 `r.status_code == 200`，别用 `r.ok`。
2. **`r.text` 乱码但 `r.json()` 正常**：两者解码路径不同，见上文。排查时先打印 `r.encoding` 和 `r.headers['Content-Type']`。
3. **`r.json()` 抛 `JSONDecodeError`，报错信息看不出原因**：因为服务端返回的是 HTML 错误页或空 body。捕获后一定要把 `r.status_code` 和 `r.text[:500]` 打出来。

   ```python
   try:
       data = r.json()
   except ValueError:
       raise AssertionError(
           f"响应不是合法 JSON: status={r.status_code} "
           f"ctype={r.headers.get('Content-Type')} body={r.text[:500]}"
       )
   ```

4. **在 response hook 里改 `r.request`**：无效。报文在 prepare 阶段已定型，要改请求就得改 prepare 之前的参数，或者自定义 `HTTPAdapter`。
5. **`r.elapsed` 不等于接口总耗时**：它只统计到响应头返回，body 下载时间不算。做性能感知时对大响应体会明显偏小。
6. **忘记 `timeout` 导致用例永久挂起**：requests **默认没有超时**，服务端不回包就一直等。详见 [[requests 超时、重试与连接池]]。
7. **`stream=True` 不关闭连接**：连接池被占满后新请求排队，表现为「跑到第 N 条用例开始变慢/卡死」。
8. **响应头大小写**：`r.headers` 是 `CaseInsensitiveDict`，`r.headers['content-type']` 和 `['Content-Type']` 等价；但 `dict(r.headers)` 之后就退化成普通字典，大小写敏感了。

## 面试怎么答

**Q：说一下 `requests.get()` 的执行过程。**

A：`requests.get()` 是便捷函数，内部临时建一个 Session。Session 先把会话级的 headers、cookies、auth 和本次调用的参数合并，通过 `prepare_request()` 生成 `PreparedRequest`——这一步会把 params 编码进 URL、把 data/json 序列化成 body 并自动补 Content-Type 和 Content-Length。然后交给 `HTTPAdapter`，底层用 urllib3 的连接池发出去。收到响应后 `build_response()` 包装成 Response 对象，默认把 body 全量读进内存好尽快归还连接。如果是 3xx 且允许重定向，会循环重发并把中间响应放进 `r.history`。

**Q：`r.text` 中文乱码怎么办？**

A：先看 `r.encoding`。如果是 `ISO-8859-1`，说明响应头的 Content-Type 里没带 charset，requests 按 HTTP/1.1 规范默认成了 latin-1。解决办法：手动 `r.encoding = 'utf-8'` 再取 `r.text`，或者直接 `r.content.decode('utf-8')` 绕过。顺带一提这时候 `r.json()` 通常是正常的，因为它按 JSON 规范自行探测编码，不走 `r.encoding`。根因还是服务端响应头不规范，应该提 bug 让后端补上 `charset=utf-8`。

**Q：接口返回 500，requests 会抛异常吗？**

A：不会。requests 只在网络层出问题时抛异常（`ConnectionError`、`Timeout`、`TooManyRedirects`），HTTP 状态码本身不抛。要抛得显式调 `r.raise_for_status()`。我在封装请求层时**故意不调**，因为接口测试本来就要覆盖 400/401/403 这些负向场景，封装层一抛异常用例就没法断言错误码了，应该把判断权交给断言层。

**Q：`stream=True` 什么时候用，有什么坑？**

A：下载大文件或处理 SSE / 长响应时用，避免一次性把几百 MB 读进内存，配合 `iter_content(chunk_size)` 分块处理。坑在于连接不会自动归还连接池，必须用 `with requests.get(...) as r` 或显式 `r.close()`；另外 `stream=True` 时 `r.elapsed`、`r.text` 的语义都会变，不要混用。

## 参考

- [requests 官方文档 - Advanced Usage](https://requests.readthedocs.io/en/latest/user/advanced/)
- [requests API 文档 - Response](https://requests.readthedocs.io/en/latest/api/#requests.Response)
- 相关笔记：[[requests 的 params、data 与 json 参数区别]]、[[requests 超时、重试与连接池]]、[[requests Session 会话保持与 Cookie]]、[[文件上传下载接口测试]]
