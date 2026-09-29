---
created: 2026-07-31
tags: [接口自动化测试/鉴权]
---

# requests Session 会话保持与 Cookie

> 「Postman 能通、脚本 401」十有八九是这里的问题：Session 同时承担 Cookie 状态机和连接池两个职责，裸函数调用两样都没有。

![[assets/session-cookie-flow.svg]]
*图示：Session 在登录响应中自动收下 Set-Cookie，后续请求自动带上并复用同一条 TCP 连接；裸调用则每次都是全新会话。*

## 概念

### Session 到底保持了什么

`requests.Session` 是一个**跨请求的上下文容器**，它持有四样东西：

1. **CookieJar**：自动收下响应的 `Set-Cookie`，自动在后续请求带上匹配的 `Cookie`
2. **连接池（HTTPAdapter）**：同一 host 的请求复用 TCP + TLS 连接（keep-alive）
3. **默认配置**：`headers`、`auth`、`proxies`、`verify`、`cert`、`params`
4. **hooks**：响应钩子，可以做统一日志、统一断言前置处理

`requests.get()` 这类顶层函数每次内部临时建一个 Session、用完即弃，所以上面四样一样都留不下。

### Cookie 为什么能「自动」

HTTP 本身是无状态的，会话是靠 Cookie 这个约定实现的：

```text
① 客户端 POST /login
② 服务端校验通过，响应头带 Set-Cookie: SESSIONID=ab12; Path=/; HttpOnly
③ 客户端把它存进 CookieJar
④ 后续请求匹配 domain/path，自动加请求头 Cookie: SESSIONID=ab12
⑤ 服务端用 SESSIONID 找到服务端 session，认出「你是谁」
```

requests 的 CookieJar 是 `RequestsCookieJar`（继承自标准库 `http.cookiejar.CookieJar`），它**会遵守 domain、path、expires、secure 这些属性**。这意味着：

- 登录接口在 `a.example.com` 下发的 Cookie，请求 `b.example.com` 时**不会**带上
- 标了 `Secure` 的 Cookie，http 请求不会带
- 过期的 Cookie 会被自动丢弃

这些"没带上 Cookie"的场景，本质上都是 Cookie 属性不匹配，而不是 requests 有 bug。

### Session vs Token：两种会话机制

| 维度 | Cookie-Session | Token（JWT） |
|------|----------------|--------------|
| 状态存哪 | 服务端存 session，客户端只存 ID | 全部信息在 token 里，服务端无状态 |
| 携带方式 | `Cookie` 头（浏览器自动） | `Authorization` 头（手动加） |
| 跨域 | 受 domain 限制，麻烦 | 天然支持 |
| 自动化里的处理 | Session 自动搞定 | 需要自己管理 header，见 [[Token 与 JWT 鉴权的获取与刷新]] |

老的管理后台多是前者，前后端分离和 App 基本都是后者。实际项目里两者混用也很常见（Web 端用 Cookie，App 端用 Token）。

## 用法

### 基本用法：登录一次，后续复用

```python
import requests

with requests.Session() as s:
    s.headers.update({
        "User-Agent": "qa-autotest/1.0",
        "Accept": "application/json",
    })

    r = s.post("https://api.example.com/api/login",
               json={"username": "qa01", "password": "Pwd@123"},
               timeout=(3, 10))
    r.raise_for_status()
    print(s.cookies.get_dict())   # {'SESSIONID': 'ab12...'}

    # 不需要手动带 Cookie
    r = s.get("https://api.example.com/api/user/profile", timeout=(3, 10))
    assert r.status_code == 200
```

`with` 会在退出时调用 `s.close()` 释放连接池，长期运行的脚本不写容易泄漏连接。

### 在 pytest 里用 fixture 承载

这是框架里的标准写法。登录一次，整个测试会话复用：

```python
# conftest.py
import pytest
import requests

BASE_URL = "https://api.example.com"

@pytest.fixture(scope="session")
def logged_session():
    s = requests.Session()
    s.headers.update({"User-Agent": "qa-autotest/1.0"})
    r = s.post(f"{BASE_URL}/api/login",
               json={"username": "qa01", "password": "Pwd@123"},
               timeout=(3, 10))
    assert r.status_code == 200, f"前置登录失败: {r.status_code} {r.text[:300]}"
    yield s
    s.close()

@pytest.fixture(scope="session")
def anon_session():
    """未登录会话，专门测 401 场景。"""
    s = requests.Session()
    yield s
    s.close()
```

```python
# test_profile.py
def test_get_profile(logged_session):
    r = logged_session.get(f"{BASE_URL}/api/user/profile", timeout=(3, 10))
    assert r.status_code == 200
    assert r.json()["data"]["username"] == "qa01"

def test_get_profile_without_login(anon_session):
    r = anon_session.get(f"{BASE_URL}/api/user/profile", timeout=(3, 10))
    assert r.status_code == 401
```

**注意这里为什么要有两个 fixture**：负向用例必须用干净的会话，否则永远测不出「未登录被拦截」。很多人在正向用例的 session 上直接 `del cookies` 来测，很容易漏删。

### 手动操作 Cookie

```python
# 读
s.cookies.get_dict()                       # 全部
s.cookies.get("SESSIONID")                 # 单个
s.cookies.get("SESSIONID", domain=".example.com", path="/")   # 精确定位

# 写（造特定场景，比如伪造过期/非法 session）
s.cookies.set("SESSIONID", "invalid-token",
              domain="api.example.com", path="/")

# 删
s.cookies.clear()                          # 清空
s.cookies.clear(domain="api.example.com")  # 按域清

# 单次请求临时带额外 Cookie（不会写入 Session 的 jar）
s.get(url, cookies={"debug": "1"})
```

### 会话级 header 与单次 header 的合并规则

```python
s = requests.Session()
s.headers.update({"X-App": "qa", "Accept": "application/json"})

# 单次覆盖：X-App 变成 admin，Accept 保留
s.get(url, headers={"X-App": "admin"})

# 单次删除会话级 header：传 None
s.get(url, headers={"Accept": None})
```

传 `None` 删除某个头，是文档里容易被忽略但很实用的技巧——比如测「不带 Accept 头时服务端返回什么」。

### 持久化 Cookie：跨进程复用登录态

调试时不想每次都跑登录：

```python
import http.cookiejar
import requests

s = requests.Session()
s.cookies = http.cookiejar.LWPCookieJar("cookies.txt")
try:
    s.cookies.load(ignore_discard=True)   # ignore_discard: 连会话 Cookie 一起加载
except FileNotFoundError:
    s.post(f"{BASE_URL}/api/login", json={...}, timeout=(3, 10))
    s.cookies.save(ignore_discard=True)
```

> 生产/CI 里**不要**这么干：cookies.txt 是明文凭据，且会造成用例之间的隐式依赖。这个技巧只用于本地调试提速，文件记得进 `.gitignore`。

### 用 hooks 做统一日志

```python
import logging

logger = logging.getLogger("api")

def log_response(r, *args, **kwargs):
    logger.info("%s %s -> %s (%.0f ms)\n  req_body=%.300s\n  resp=%.500s",
                r.request.method, r.url, r.status_code,
                r.elapsed.total_seconds() * 1000,
                r.request.body, r.text)

s = requests.Session()
s.hooks["response"].append(log_response)
```

挂上之后所有请求都有结构化日志，排查失败用例时不用再到处加 print。

## 踩坑

1. **Postman 通、脚本 401**：Postman 有自己的 Cookie Jar 帮你保持了登录态，而脚本用了 `requests.get()` 裸调用。改用 Session。
2. **登录成功但后续接口还是 401**：
   - 服务端用的是 Token 不是 Cookie，登录响应的 token 在 body 里，需要你手动放进 `Authorization` 头
   - 登录域名和业务域名不同，Cookie 的 domain 不匹配
   - Cookie 带了 `Secure` 但你请求的是 http
   - 排查手段：`print(s.cookies)` 看 jar 里有什么，`print(r.request.headers)` 看实际发了什么
3. **`scope="session"` 的登录 fixture 让用例互相污染**：某条用例做了「修改密码」或「登出」，后面所有用例的会话全废。有状态变更的用例应该用独立的 `function` 级会话。
4. **并发跑用例共用一个 Session 出现串号**：`Session` 不是严格线程安全的，CookieJar 更新有竞态。多线程/`pytest-xdist` 场景下应该每个 worker 一个 Session（`scope="session"` 在 xdist 下本来就是每 worker 一份，这点刚好合适）。
5. **`s.cookies.set()` 不写 domain**：设进去了但发请求时匹配不上，表现为「明明设了却没带」。带上 `domain` 和 `path`。
6. **重定向丢 header**：requests 在跨域重定向时会**主动剥离 `Authorization` 头**（安全考虑），Cookie 也会按 domain 重新匹配。测跨域跳转时用 `allow_redirects=False` 分段验证。
7. **忘记 `s.close()`**：长时间运行的脚本连接泄漏，最终 `Too many open files`。用 `with` 或在 fixture 的 `yield` 后关闭。
8. **登录失败没有明确报错**：登录 fixture 里如果不 assert，后面几百条用例全部 401，报告里一片红但看不出根因。**前置 fixture 一定要断言并给出清晰的失败信息**。

## 面试怎么答

**Q：`requests.Session` 有什么用？**

A：两件事。一是保持会话状态——自动收下响应的 `Set-Cookie` 并在后续请求按 domain/path 匹配带上，登录态就这么维持住了；二是复用连接——底层 `HTTPAdapter` 维护 urllib3 连接池，同一 host 的请求走 keep-alive，省掉重复的 TCP 三次握手和 TLS 握手。此外还能统一设置 headers、auth、proxies 和响应 hooks。用裸的 `requests.get()` 每次都是新建再丢弃的临时 Session，这两个好处一个都没有，几百条用例跑下来性能差距很明显。

**Q：接口自动化里登录态怎么管理？**

A：用 pytest fixture 承载 Session。`scope="session"` 的 fixture 里跑一次登录、断言成功、`yield` 出去给所有用例复用，结束时 close。同时会额外准备一个未登录的 `anon_session`，专门给 401/403 这类负向用例用——不然永远测不出鉴权是否真的生效。如果是 Token 机制，就在 fixture 里把 token 塞进 `session.headers`，并在 Session 子类里做过期自动刷新，用例层完全无感知。要注意有状态变更的用例（改密码、登出）不能共用会话级 fixture，得单独开。

**Q：登录成功了但后面的接口还是 401，你怎么排查？**

A：先分清是 Cookie 机制还是 Token 机制。打印 `session.cookies` 看 jar 里有没有东西——空的说明服务端根本没下发 Cookie，那多半是 Token 机制，token 在响应 body 里，需要手动放到 `Authorization` 头。如果 jar 里有 Cookie 但请求没带，就看 domain 和 path 匹配不匹配、是不是 `Secure` 标记而我走了 http。最直接的手段是 `print(r.request.headers)` 对比 Postman/抓包里真实客户端发的头，逐个字段对齐，差在哪一眼就看出来了。

## 参考

- [requests 官方文档 - Session Objects](https://requests.readthedocs.io/en/latest/user/advanced/#session-objects)
- [MDN - HTTP Cookies](https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Cookies)
- 相关笔记：[[requests 请求与响应对象]]、[[Token 与 JWT 鉴权的获取与刷新]]、[[requests 超时、重试与连接池]]、[[接口串联与依赖参数提取传递]]
