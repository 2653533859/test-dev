---
created: 2026-07-31
tags: [接口自动化测试/requests]
---

# requests 的 params、data 与 json 参数区别

> 三个参数决定了数据放在 URL 还是 body、body 用什么格式编码、Content-Type 是什么——选错了就是 400 或 415，这是接口自动化最高频的踩坑点。

## 概念

### 一张表说清区别

| 参数 | 数据去哪 | 编码方式 | 自动设置的 Content-Type |
|------|----------|----------|--------------------------|
| `params` | URL 的 query string | URL-encode（`?a=1&b=2`） | 不设置（不影响 body） |
| `data=dict` | 请求 body | 表单编码 `a=1&b=2` | `application/x-www-form-urlencoded` |
| `data=str/bytes` | 请求 body | **原样发送，不加工** | 不设置（要自己写） |
| `json=obj` | 请求 body | `json.dumps()` 序列化 | `application/json` |
| `files=dict` | 请求 body | multipart 分段 | `multipart/form-data; boundary=…` |

关键点：**`params` 和另外三个不是一个维度的**。`params` 管 URL，`data`/`json`/`files` 管 body，`params` 可以和它们任意组合。而 `data`、`json`、`files` 之间有优先级冲突。

### 为什么会有 data 和 json 两个参数

历史原因。早期 Web 表单提交只有 `application/x-www-form-urlencoded` 和 `multipart/form-data` 两种，`data` 就是为它们设计的。后来 REST API 普及，body 基本都是 JSON，requests 在 2.x 里加了 `json` 参数当语法糖，省掉每次手写：

```python
# json= 参数出现之前必须这么写
import json
requests.post(url,
              data=json.dumps({"a": 1}),
              headers={"Content-Type": "application/json"})

# 现在等价于
requests.post(url, json={"a": 1})
```

所以 **`json=` 只做两件事：`json.dumps` + 加 Content-Type 头**。理解这一点，后面所有坑都能自己推理。

### data、json、files 的优先级

看 `models.py` 的 `prepare_body` 逻辑，实际优先级是：

1. `files` 存在 → 走 multipart，`data` 里的键值会被作为**普通表单字段**一起塞进去，`json` 被忽略
2. 否则 `data` 存在 → 用 `data`，`json` **被忽略**
3. 否则 `json` 存在 → 序列化 `json`

也就是说 `requests.post(url, data={"a": 1}, json={"b": 2})` 只会发出 `a=1`，`b` 静默丢失，不报错。这是很阴的一个坑。

## 用法

### 用 httpbin 把差别看清楚

`httpbin.org/post` 会把它收到的东西原样回显，是验证这类问题的最佳工具。

```python
import requests

url = "https://httpbin.org/post"

# 1) params：只影响 URL
r = requests.post(url, params={"page": 2, "size": 10})
print(r.json()["args"])   # {'page': '2', 'size': '10'}
print(r.json()["form"])   # {}
print(r.request.url)      # https://httpbin.org/post?page=2&size=10

# 2) data=dict：表单编码进 body
r = requests.post(url, data={"user": "qa", "pwd": "123"})
print(r.json()["headers"]["Content-Type"])  # application/x-www-form-urlencoded
print(r.json()["form"])                     # {'user': 'qa', 'pwd': '123'}
print(r.json()["json"])                     # None  ← 服务端解析不出 JSON
print(r.request.body)                       # user=qa&pwd=123

# 3) json=dict：JSON 序列化进 body
r = requests.post(url, json={"user": "qa", "pwd": "123"})
print(r.json()["headers"]["Content-Type"])  # application/json
print(r.json()["form"])                     # {}
print(r.json()["json"])                     # {'user': 'qa', 'pwd': '123'}
print(r.request.body)                       # b'{"user": "qa", "pwd": "123"}'
```

看 `form` 和 `json` 两个回显字段的差别，就明白服务端是从哪解析你的数据的。

### params 的进阶用法

```python
# 同名多值：传 list
requests.get(url, params={"id": [1, 2, 3]})
# → ?id=1&id=2&id=3

# 值为 None 的键会被丢弃（很实用，可以拼可选参数）
requests.get(url, params={"page": 1, "keyword": None})
# → ?page=1

# 值为 False / 0 不会被丢弃
requests.get(url, params={"flag": False, "n": 0})
# → ?flag=False&n=0     注意 bool 被转成 'False' 而不是 'false'！

# 已经拼好的 query string 也能直接传
requests.get(url, params="a=1&b=2")
```

**bool 值的坑**：Python 的 `False` 被 `str()` 成 `'False'`，而 JSON 规范和多数后端期望 `'false'`。传布尔型 query 参数时手动转：

```python
params = {"is_vip": str(True).lower()}   # 'true'
```

### data 传字符串：需要自己接管序列化的场景

某些接口要求 body 是 JSON 但 Content-Type 是别的（比如 `text/plain`），或者要求发送特定顺序的 JSON（签名场景），这时必须用 `data=str`：

```python
import json
import requests

payload = {"amount": 100, "order_id": "A001"}
# 签名要求 key 按字典序、无空格
body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
# body = '{"amount":100,"order_id":"A001"}'

r = requests.post(
    url,
    data=body.encode("utf-8"),          # 明确 bytes，避免默认 latin-1 编码问题
    headers={"Content-Type": "application/json; charset=utf-8"},
)
```

**为什么签名场景不能用 `json=`**：`json=` 内部的 `json.dumps` 用的是默认参数（`separators=(', ', ': ')`，带空格），你本地算签名用的字符串和实际发出去的 body 不一致，签名必然校验失败。详见 [[接口签名鉴权与 sign 计算]]。

### 中文与非 ASCII

```python
# json= 默认 ensure_ascii=True，中文被转义成 \uXXXX
r = requests.post(url, json={"name": "张三"})
print(r.request.body)   # b'{"name": "\\u5f20\\u4e09"}'

# 想发原始中文（少数后端不认 \u 转义）
body = json.dumps({"name": "张三"}, ensure_ascii=False).encode("utf-8")
r = requests.post(url, data=body,
                  headers={"Content-Type": "application/json; charset=utf-8"})
print(r.request.body)   # b'{"name": "\xe5\xbc\xa0\xe4\xb8\x89"}'
```

`\uXXXX` 是合法 JSON，规范的后端两种都能解析。但确实遇到过日志系统按字节匹配关键字导致查不到的情况，知道有这个开关就行。

### 封装层的推荐做法

不要让用例层去纠结用哪个参数，在封装里按 Content-Type 分派：

```python
class ApiClient:
    def __init__(self, base_url, session=None):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()

    def post(self, path, *, params=None, body=None, content_type="json", **kwargs):
        """content_type: json | form | raw"""
        url = f"{self.base_url}{path}"
        if content_type == "json":
            kwargs["json"] = body
        elif content_type == "form":
            kwargs["data"] = body
        elif content_type == "raw":
            kwargs["data"] = body if isinstance(body, bytes) else str(body).encode()
        else:
            raise ValueError(f"不支持的 content_type: {content_type}")
        return self.session.post(url, params=params, timeout=(3, 10), **kwargs)
```

## 踩坑

1. **415 Unsupported Media Type**：后端要 JSON，你用了 `data=dict`（发成了表单）。改成 `json=`。
2. **400 参数缺失，但明明传了**：同上的反面——后端是 Spring MVC 的 `@RequestParam` 或表单接收，你却用了 `json=`。服务端从 form 里取不到值。用 `data=dict`。
3. **`data` 和 `json` 同时传，`json` 静默丢失**：不报错、不告警，body 里只有 `data` 的内容。排查靠 `print(r.request.body)`。
4. **`data=dict` 里塞嵌套结构**：`data={"user": {"id": 1}}` 会被编码成 `user=%7B%27id%27%3A+1%7D`（Python dict 的 repr 被 URL 编码），完全不是后端想要的。**表单编码只支持一层扁平键值**，有嵌套就必须用 `json=`。
5. **bool 值在 params 里变成 `True`/`False`**：首字母大写，后端按 `"true"` 判断就失效。手动 `.lower()`。
6. **签名接口用了 `json=` 导致签名失败**：`json.dumps` 的分隔符默认带空格，与你算签名时用的字符串不一致。用 `data=` 自己序列化。
7. **`files` 和 `json` 同时传，`json` 被忽略**：上传文件时附带的业务字段要放 `data=`，不能放 `json=`。见 [[文件上传下载接口测试]]。
8. **`params` 里的中文没编码**：requests 会自动 URL-encode，不需要你先 `quote()`。**手动 quote 再传会被二次编码**（`%` 变成 `%25`），后端拿到乱码。
9. **GET 请求带 body**：`requests.get(url, json={...})` 语法上允许，但很多网关/代理会丢弃 GET 的 body。遇到「本地通、测试环境不通」优先查这个。

## 面试怎么答

**Q：`data` 和 `json` 参数有什么区别？**

A：`data` 传字典时按表单编码 `a=1&b=2` 放进 body，Content-Type 自动设为 `application/x-www-form-urlencoded`；`json` 传对象时用 `json.dumps` 序列化成 JSON 字符串，Content-Type 设为 `application/json`。本质上 `json=` 只是「`json.dumps` + 设 header」的语法糖。选哪个取决于后端怎么接收：Spring 的 `@RequestBody` 要 JSON，`@RequestParam` / 表单要 form。另外表单编码只支持扁平键值，有嵌套结构必须用 `json`。

**Q：`params` 和 `data` 能一起用吗？**

A：能，而且很常见。它们不在一个位置：`params` 拼到 URL 的 query string，`data` 进 body。比如 POST `/api/orders?source=app` 带 JSON body，就是 `requests.post(url, params={"source":"app"}, json={...})`。真正互斥的是 `data`、`json`、`files` 三者，同时传的话优先级是 `files` > `data` > `json`，被忽略的那个不会报错，属于静默失效的坑。

**Q：接口报 415，你怎么排查？**

A：415 是服务端不接受当前的 Content-Type。第一步 `print(r.request.headers)` 和 `print(r.request.body)` 看实际发了什么；第二步对照接口文档或抓包看真实客户端发的 Content-Type 是什么。90% 的情况是 `data=dict` 和 `json=` 用反了。剩下的情况可能是后端要 `application/json;charset=UTF-8` 这种带参数的精确匹配，那就用 `data=` 自己序列化并手写完整的 Content-Type。

## 参考

- [requests 官方文档 - More complicated POST requests](https://requests.readthedocs.io/en/latest/user/quickstart/#more-complicated-post-requests)
- [MDN - Content-Type](https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Headers/Content-Type)
- 相关笔记：[[requests 请求与响应对象]]、[[接口签名鉴权与 sign 计算]]、[[文件上传下载接口测试]]
