---
created: 2026-07-31
tags: [接口自动化测试/鉴权]
---

# Token 与 JWT 鉴权的获取与刷新

> access_token 通常只活几十分钟，一轮回归跑两小时——不做自动刷新，跑到一半就会成片 401。

![[assets/jwt-auth-refresh-flow.svg]]
*图示：登录取双 token → 业务请求带 Bearer → 401 时用 refresh_token 换新并重放原请求，且只重放一次以避免死循环。*

## 概念

### JWT 的结构

JWT（JSON Web Token）是三段 Base64URL 拼起来的字符串，用 `.` 分隔：

```text
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9 . eyJzdWIiOiIxMDAxIiwiZXhwIjoxNzY3MjAwMDAwfQ . dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk
└──────────── header ────────────┘   └───────────── payload ─────────────┘   └──────────── signature ────────────┘
```

- **header**：`{"alg": "HS256", "typ": "JWT"}`，声明签名算法
- **payload**：业务声明（claims），如 `sub`（用户 ID）、`exp`（过期时间戳）、`iat`（签发时间）、自定义的 `role`/`tenant_id`
- **signature**：`HMACSHA256(base64(header) + "." + base64(payload), secret)`

**关键认知：payload 只是 Base64 编码，不是加密**。任何人拿到 token 都能解出里面的内容。签名保证的是「不可篡改」，不是「不可见」。这直接影响两件事：

1. 测试时可以**本地解码 token 拿到 `exp`**，提前判断是否过期，不用等 401
2. 安全测试要检查 payload 里有没有塞敏感信息（手机号、身份证）

### 为什么要 access + refresh 双 token

单 token 有个两难：有效期短则用户频繁重登，长则被盗用后风险窗口大。双 token 的拆分是：

- `access_token`：短期（5～30 分钟），每次请求都带，被盗用影响窗口小
- `refresh_token`：长期（7～30 天），**只在刷新接口用一次**，通常还会「一次性」——用过就作废并下发新的（refresh token rotation）

对自动化的含义：**refresh 逻辑必须串行且加锁**。并发场景下多个线程同时拿旧 refresh_token 去刷新，只有第一个成功，其余全部失败并把整个登录态搞废。

### 无状态带来的测试点

服务端不存 session，全靠验签，这带来一批 JWT 特有的测试用例：

| 场景 | 构造方式 | 期望 |
|------|----------|------|
| token 过期 | 等待 / 本地伪造 `exp` 为过去 | 401 |
| 签名被篡改 | 改 payload 但不重算签名 | 401 |
| `alg: none` 攻击 | header 改成 `{"alg":"none"}`，去掉签名 | 401（若通过则是严重漏洞） |
| 越权 | 用 A 的 token 访问 B 的资源 | 403 |
| 登出后 token 仍可用 | 登出后立即复用旧 token | 应 401（需服务端维护黑名单） |

最后一条特别值得测：**JWT 天生无法「注销」**，很多团队只是前端删了 token，服务端根本没作废。这是真实存在的高危缺陷。

## 用法

### 本地解析 JWT（不验签）

```python
import base64
import json
import time

def decode_jwt_payload(token: str) -> dict:
    """只解 payload，不验签。用于测试时读取 exp、sub 等信息。"""
    payload_b64 = token.split(".")[1]
    # Base64URL 去掉了尾部 '='，需要补齐到 4 的倍数
    padding = "=" * (-len(payload_b64) % 4)
    raw = base64.urlsafe_b64decode(payload_b64 + padding)
    return json.loads(raw)

token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMDAxIiwiZXhwIjoxNzY3MjAwMDAwfQ.xxx"
claims = decode_jwt_payload(token)
print(claims)                                  # {'sub': '1001', 'exp': 1767200000}
print("已过期" if claims["exp"] < time.time() else "有效")
```

有了 `exp`，就能**主动提前刷新**而不是被动等 401，用例更稳：

```python
def is_expiring(token: str, buffer_sec: int = 60) -> bool:
    """剩余有效期不足 buffer_sec 秒就认为需要刷新。"""
    exp = decode_jwt_payload(token).get("exp", 0)
    return exp - time.time() < buffer_sec
```

留 60 秒缓冲很有必要：请求发出到服务端校验之间有延迟，卡在临界点上会偶发 401。

### 封装一个自动刷新的 Session

这是框架里最实用的一段代码。核心思路：**在 `request()` 里做前置检查 + 后置重试，用例层完全无感知**。

```python
import threading
import time
import requests

class AuthSession(requests.Session):
    def __init__(self, base_url: str, username: str, password: str):
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._access = None
        self._refresh = None
        self._lock = threading.Lock()      # 防止并发刷新
        self.login()

    # ---------- 凭据管理 ----------
    def login(self):
        r = super().post(f"{self.base_url}/api/login",
                         json={"username": self._username, "password": self._password},
                         timeout=(3, 10))
        assert r.status_code == 200, f"登录失败: {r.status_code} {r.text[:300]}"
        data = r.json()["data"]
        self._access = data["access_token"]
        self._refresh = data["refresh_token"]

    def refresh_token(self):
        """用 refresh_token 换新 access_token；换不动就整体重登。"""
        r = super().post(f"{self.base_url}/api/refresh",
                         json={"refresh_token": self._refresh},
                         timeout=(3, 10))
        if r.status_code != 200:
            self.login()               # refresh 也失效了，退回重新登录
            return
        data = r.json()["data"]
        self._access = data["access_token"]
        # refresh token rotation：服务端可能同时换发新的 refresh
        self._refresh = data.get("refresh_token", self._refresh)

    # ---------- 请求拦截 ----------
    def request(self, method, url, **kwargs):
        if not url.startswith("http"):
            url = f"{self.base_url}{url}"
        kwargs.setdefault("timeout", (3, 10))

        # 前置：快过期就先刷新，减少 401 概率
        with self._lock:
            if is_expiring(self._access):
                self.refresh_token()
            token = self._access

        headers = kwargs.pop("headers", {}) or {}
        headers.setdefault("Authorization", f"Bearer {token}")
        r = super().request(method, url, headers=headers, **kwargs)

        # 后置：万一还是 401，刷新后只重放一次
        if r.status_code == 401 and not kwargs.get("_retried"):
            with self._lock:
                self.refresh_token()
                token = self._access
            headers["Authorization"] = f"Bearer {token}"
            r = super().request(method, url, headers=headers, _retried=True, **kwargs)
        return r
```

几个设计要点：

- **`headers.setdefault`** 而不是直接赋值：这样用例层可以传自定义的 `Authorization` 来测越权/非法 token 场景。
- **`_retried` 标记**：只重放一次。不加这个，token 服务真挂了会无限递归。
- **`_lock`**：并发跑用例时防止多个线程同时刷新，把 refresh_token 消耗掉。

### 在 pytest 里使用

```python
# conftest.py
import pytest

@pytest.fixture(scope="session")
def api(base_url):
    s = AuthSession(base_url, "qa01", "Pwd@123")
    yield s
    s.close()

@pytest.fixture
def bad_token_headers():
    """构造一个签名被篡改的 token，用于负向用例。"""
    return {"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI5OTk5In0.tampered"}
```

```python
# test_auth.py
def test_profile_ok(api):
    r = api.get("/api/user/profile")
    assert r.status_code == 200

def test_invalid_signature_rejected(api, bad_token_headers):
    r = api.get("/api/user/profile", headers=bad_token_headers)
    assert r.status_code == 401

def test_no_token_rejected(api):
    r = api.get("/api/user/profile", headers={"Authorization": None})
    assert r.status_code == 401
```

### 构造过期 token 测试

不想干等，就自己签一个已过期的（需要知道测试环境的 secret，从配置里拿）：

```python
import jwt   # pip install pyjwt
import time

expired = jwt.encode(
    {"sub": "1001", "exp": int(time.time()) - 10},
    key="test-env-secret",
    algorithm="HS256",
)
r = api.get("/api/user/profile", headers={"Authorization": f"Bearer {expired}"})
assert r.status_code == 401
assert r.json()["code"] == "TOKEN_EXPIRED"    # 顺便验错误码是否可区分
```

拿不到 secret 时，退而求其次把 `exp` 篡改成过去时间（签名会对不上，测出来的是「签名非法」而非「过期」，错误码不同）——这两条其实应该分别覆盖。

## 踩坑

1. **回归跑到一半成片 401**：token 过期了没刷新。解决就是上面的 `AuthSession`，别在用例里手动传 token。
2. **并发刷新把 refresh_token 消耗掉**：服务端做了 refresh token rotation，旧的用一次就作废。多线程同时刷新，第一个成功后其余全部持旧 token 失败，整个会话报废。必须加锁，或者干脆每个 worker 独立登录。
3. **无限重试死循环**：401 → 刷新 → 还是 401 → 再刷新……token 服务挂掉时会把 CI 跑爆。用 `_retried` 标记限死一次。
4. **`Bearer` 前缀写错**：漏写、写成 `bearer`（部分服务端大小写敏感）、多个空格。这类错误的报错通常只有一个笼统的 401，很难查。`print(r.request.headers['Authorization'])` 直接看。
5. **重定向后 `Authorization` 头丢失**：requests 出于安全考虑会在**跨主机重定向时剥离 Authorization**。表现为「直接请求正常、走网关重定向就 401」。用 `allow_redirects=False` 分段确认。
6. **本地时钟与服务端不同步**：容器里时钟漂移几分钟，本地算出来「还没过期」但服务端认为过期了。所以要留 buffer，且不要完全信任本地时间判断，401 后置重试是必要的兜底。
7. **token 被打进日志/报告**：Allure 报告里把完整请求头贴上去，token 就泄漏了。日志里要脱敏：`token[:8] + "..." + token[-4:]`。
8. **登出用例没测「旧 token 是否失效」**：只断言登出接口返回 200 是不够的，必须紧接着拿旧 token 再请求一次，断言 401。这条用例经常能测出真问题。
9. **多环境共用一份 token 缓存**：把 token 存文件缓存提速，切环境时忘了失效，拿测试环境 token 打预发，一路 401 还以为是权限问题。缓存 key 一定要带环境标识。

## 面试怎么答

**Q：JWT 是什么，和 Session 有什么区别？**

A：JWT 是三段式的自包含令牌，header 声明算法、payload 放业务声明、signature 是前两段的签名。核心区别在于状态存哪：Cookie-Session 是服务端存会话数据、客户端只拿一个 ID；JWT 把信息全放在 token 里，服务端只验签不存状态，所以天然适合分布式和跨域。代价是**没法主动注销**——token 签发出去在过期前一直有效，要支持登出就得额外维护黑名单，这在测试时是个必查点。另外要强调 payload 只是 Base64 编码不是加密，任何人都能解开看，敏感信息不能往里放。

**Q：接口自动化里 token 过期了怎么办？**

A：我不会在用例里手动传 token，而是封装一个 `Session` 子类，在 `request()` 里做两层保障。前置：本地 Base64 解 token 的 `exp`，剩余有效期不足 60 秒就先刷新，减少踩到 401 的概率；后置：万一还是返回 401，就用 refresh_token 换新并**只重放一次**原请求，加 `_retried` 标记防止死循环。刷新逻辑要加线程锁，因为很多服务端做了 refresh token rotation，并发刷新会把凭据消耗掉导致整体登录态崩掉。这样用例层完全感知不到鉴权的存在，只关心业务断言。

**Q：JWT 相关你会设计哪些测试用例？**

A：正向是带合法 token 访问成功。负向至少五类：不带 token 401；token 过期 401，并且错误码要能和「签名非法」区分开；签名被篡改（改 payload 不重算签名）401；`alg` 改成 `none` 且去掉签名段——如果这样能通过就是严重的算法降级漏洞；用 A 用户的 token 访问 B 的资源，应该 403 而不是 200，这是水平越权。另外一定要测登出后旧 token 是否立即失效，很多实现只是前端删了本地存储，服务端压根没作废，这是高频真实缺陷。

## 参考

- [RFC 7519 - JSON Web Token](https://datatracker.ietf.org/doc/html/rfc7519)
- [PyJWT 文档](https://pyjwt.readthedocs.io/en/stable/)
- [OWASP - JSON Web Token Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/JSON_Web_Token_for_Java_Cheat_Sheet.html)
- 相关笔记：[[requests Session 会话保持与 Cookie]]、[[接口签名鉴权与 sign 计算]]、[[接口用例设计维度]]
