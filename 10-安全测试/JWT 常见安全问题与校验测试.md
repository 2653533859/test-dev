---
created: 2026-07-31
tags: [安全测试/认证与会话]
---

# JWT 常见安全问题与校验测试

> JWT 的前两段只是 Base64URL 编码，不是加密。所有安全性都压在「服务端有没有认真验第三段签名」这一件事上。

![[assets/jwt-verify-flow.svg]]
*图示：JWT 三段结构与服务端完整校验链（alg → 签名 → exp/nbf → iss/aud → 黑名单），以及挂在链路上的四类常见缺陷——算法缺陷、签名缺陷、时效缺陷、注销缺陷。*

## 概念

### 三段结构：能看不等于能改

一个 JWT 用 `.` 分成三段：

```text
eyJhbGciOiJIUzI1NiJ9 . eyJzdWIiOiIxMDAxIiwicm9sZSI6InVzZXIifQ . 4f2Kx...
   Header 算法与类型          Payload 业务声明                    Signature 签名
```

自己动手解一遍，这是理解 JWT 的第一步：

```bash
# 解开 payload（第二段）。base64url 需要补齐 = 号
echo 'eyJzdWIiOiIxMDAxIiwicm9sZSI6InVzZXIifQ==' | base64 -d
# {"sub":"1001","role":"user"}
```

```python
import base64, json

def decode_jwt(token: str) -> dict:
    """只解码不验签，测试时用来快速查看内容。生产代码绝不能这么用。"""
    header_b64, payload_b64, _sig = token.split(".")

    def _d(seg: str) -> dict:
        seg += "=" * (-len(seg) % 4)               # base64url 补位
        return json.loads(base64.urlsafe_b64decode(seg))

    return {"header": _d(header_b64), "payload": _d(payload_b64)}
```

**关键认知**：任何拿到 token 的人都能看到 payload 的全部内容。所以里面不能放密码、身份证号、完整手机号——**这属于「敏感信息泄露」，不是「JWT 被破解」**，两者定级和修复方式都不同。

### 签名是唯一的防线

第三段签名 = `HMAC(base64(header) + "." + base64(payload), 密钥)`。改掉前两段任何一个字节，签名就对不上。

于是整条安全链只剩一个假设：**服务端每次都用正确的算法和密钥验了签名**。这个假设一旦被绕过——接受了 `alg: none`、被降级成用公钥当 HMAC 密钥、或者干脆只 decode 不 verify——攻击者就能自己伪造 payload，把 `role: user` 改成 `role: admin`。

### 标准声明各管什么

| 声明 | 含义 | 不校验会怎样 |
|------|------|-------------|
| `sub` | 主体，通常是用户 id | —— |
| `exp` | 过期时间（Unix 秒） | token 永久有效 |
| `nbf` | 生效时间，早于它无效 | 影响较小 |
| `iat` | 签发时间 | 无法判断 token 年龄 |
| `iss` | 签发方 | A 系统的 token 能用到 B 系统 |
| `aud` | 接收方 | 同上，多服务共用密钥时尤其危险 |
| `jti` | token 唯一 id | 无法做黑名单与防重放 |

### JWT vs Session：核心差别是「能不能收回」

```text
Session  服务端存状态 → 删掉记录立刻失效 → 天然支持登出、踢人、改密下线
JWT      服务端不存状态 → 签出去就收不回 → 登出、改密需要额外机制
```

选 JWT 的理由通常是「分布式下省掉共享存储」，但一旦要支持登出和踢人，又不得不查一次库（黑名单或版本号），无状态的优势就被抵消了大半。**面试被问「为什么用 JWT」时答不出这个 trade-off 是减分项**。会话侧的整体测试见 [[认证与会话安全测试]]。

## 用法

### 测试原则：只动自己的 token

以下所有验证遵循同一条纪律：**在授权的测试环境里，用自己账号登录拿到的 token，做「解码查看 → 篡改字段 → 重放观察」**。不对他人 token 做破解或爆破尝试；写报告时 token 要脱敏，只保留 payload 的结构说明。

### 检查 1：payload 里有没有不该放的东西

最容易发现、也最容易被忽视的一条。

```text
不该出现  password / pwd（哪怕是哈希值）
          身份证号、完整手机号、完整邮箱、银行卡号
          内网地址、调试信息、其他系统的凭据
可以出现  sub、role、exp、iat、iss、aud、jti、tenant_id
```

发现了单独提一条「敏感信息泄露」，定级方式见 [[敏感信息泄露与传输配置测试]]。

### 检查 2：alg 是否被信任（算法缺陷）

历史上最经典的一类 JWT 漏洞：服务端读 header 里的 `alg` 来决定用什么算法验签，而 header 恰恰是可篡改的。

```text
测法 A（alg=none）
  header 改成 {"alg":"none","typ":"JWT"}，签名段留空但保留末尾的点
  重放业务接口 → 期望 401；返回 200 说明服务端接受了「无签名」

测法 B（RS256 降级为 HS256）
  原本用非对称 RS256（私钥签、公钥验），把 alg 改成 HS256
  服务端若按 header 选算法，就会拿公开的公钥当 HMAC 密钥去验
  期望：服务端固定算法白名单，直接 401

测法 C（换个签名算法名）
  HS256 改成 HS384 / HS512，看是否被无条件接受
```

**判定标准很干脆：只要改了 header 之后服务端还认，就是高危。** 修复只有一句——服务端固定算法，绝不读 header 里的 `alg`。

### 检查 3：签名到底验没验

```text
测法 1  只改 payload 里的非关键字段（如 nickname），签名段原样不动
        → 期望 401。返回 200 说明服务端只 decode 没 verify，这是最严重的情况
测法 2  改 role: user → admin，签名不动，重放管理接口
        → 期望 401。若通过则是垂直越权 + 签名未校验的组合，直接 P0
测法 3  把签名段随便改一位字符
        → 期望 401
测法 4  把自己 token 里的 sub 改成另一个测试账号的 id，签名不动
        → 期望 401
```

一段可复用的测试脚本（只跑自己的 token、只打测试环境）：

```python
import base64, json, requests

BASE = "http://test-app.internal.com"          # 仅指向自有测试环境
MY_TOKEN = "<自己登录拿到的 token>"

def rebuild(token: str, header_patch=None, payload_patch=None, sig=None) -> str:
    h, p, s = token.split(".")

    def _d(seg):
        return json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))

    def _e(obj):
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = _d(h)
    payload = _d(p)
    if header_patch:
        header.update(header_patch)
    if payload_patch:
        payload.update(payload_patch)
    new_sig = s if sig is None else sig
    return f"{_e(header)}.{_e(payload)}.{new_sig}"

def probe(name: str, token: str):
    r = requests.get(f"{BASE}/api/profile",
                     headers={"Authorization": f"Bearer {token}"}, timeout=5)
    flag = "！！可能有漏洞" if r.status_code == 200 else "ok"
    print(f"{name:20s} -> {r.status_code} {flag}")

probe("baseline 原样",  MY_TOKEN)
probe("alg=none",       rebuild(MY_TOKEN, header_patch={"alg": "none"}, sig=""))
probe("篡改 role",       rebuild(MY_TOKEN, payload_patch={"role": "admin"}))
probe("破坏签名",        rebuild(MY_TOKEN, sig="AAAA"))
```

除 baseline 外的每一行都应打印非 200；出现 200 就意味着对应的校验缺失。

### 检查 4：时效与注销（时效缺陷 + 注销缺陷）

```text
时效 1  解开 payload 看有没有 exp。没有 exp = 永久有效，直接提缺陷
时效 2  看 exp - iat 的跨度。access token 超过 1 小时就偏长，几天几月是明显问题
注销 1  登出后拿旧 token 重放业务接口 → 期望 401（详见认证与会话笔记）
注销 2  改密码后旧 token 是否还能用 → 期望 401
重放    同一个 token 短时间内高频重放，看有没有 jti + 一次性校验（多数业务不强制）
```

时效和注销这两类缺陷在 JWT 里格外突出，因为无状态令牌天生「收不回」，如果没有黑名单或版本号机制，登出和改密就是纯前端动作。

### 检查 5：密钥强度（需要开发配合，不做爆破）

密钥弱是 HS256 的致命伤，但**测试人员不应该去跑爆破字典**——那既超范围又没意义。合规做法是通过代码审计或与开发确认：

```text
不合格  密钥是 secret / 123456 / 项目名 / 默认示例值
        密钥硬编码在源码或提交进了 Git 仓库
        多个环境（测试/预发/生产）共用同一个密钥
合格    ≥ 32 字节的随机值 · 走密钥管理服务 · 按环境隔离 · 不入库不入仓
```

密钥泄露的排查思路属于 [[敏感信息泄露与传输配置测试]] 的范畴。

### 修复参考

```python
import jwt   # PyJWT

SECRET = load_secret_from_kms()               # 强随机、按环境隔离、不入仓

def issue(user) -> str:
    return jwt.encode(
        {"sub": str(user.id), "role": user.role,
         "ver": user.token_version,            # 支持改密/登出后失效
         "iss": "app-auth", "aud": "app-api",
         "iat": now(), "exp": now() + 900},    # access token 15 分钟
        SECRET, algorithm="HS256",
    )

def verify(token: str) -> dict:
    claims = jwt.decode(
        token, SECRET,
        algorithms=["HS256"],                  # 固定白名单，绝不读 header 的 alg
        issuer="app-auth", audience="app-api", # 校验 iss / aud
        options={"require": ["exp", "iss", "aud", "sub"]},
    )
    user = User.get(claims["sub"])
    if not user or user.token_version != claims.get("ver"):
        raise jwt.InvalidTokenError()          # 版本号对不上 = 已登出/已改密
    return claims
```

要点：**固定 `algorithms` 白名单**、校验 `iss/aud/exp`、access token 短效、用 `token_version` 换取可撤销性。

## 踩坑

1. **只 decode 不 verify**。用 `jwt.decode(token, options={"verify_signature": False})` 或干脆手撸 base64 解码后直接信 payload。这是最严重也最常见的错误，等于签名形同虚设。
2. **信任 header 里的 alg**。给了攻击者选择算法的权力，`alg=none` 和 RS256→HS256 降级都源于此。永远在服务端固定算法白名单。
3. **payload 里放敏感数据**。开发常误以为 JWT「加了密」，把手机号、身份证甚至密码哈希塞进 payload，任何人 base64 一解就看到了。
4. **不校验 exp**。库默认大多会校验，但有人为了「调试方便」关掉了过期校验后忘了打开。
5. **不校验 iss / aud，多服务共用密钥**。A 服务签的 token 能直接拿去调 B 服务，越权跨系统。
6. **登出 / 改密后 token 仍有效**。没有黑名单也没有版本号，纯前端删 token。这是 JWT 项目最普遍的会话缺陷。
7. **密钥太弱或进了 Git**。HS256 的密钥一旦弱或泄露，攻击者可以自签任意 token。用强随机密钥并走密钥管理。
8. **refresh token 可无限续期且不可撤销**。access token 做短了，但 refresh token 几个月有效又收不回，等于没做短。
9. **在报告里贴出完整真实 token**。token 是活的凭证，报告要脱敏，只保留 payload 结构说明。

## 面试怎么答

**Q：JWT 是加密的吗？payload 能放敏感信息吗？**

A：不是加密，是签名。标准的 JWT（JWS）前两段 header 和 payload 只是 base64url 编码，任何人拿到 token 都能直接解开看到里面的全部内容，签名只保证「内容没被篡改」，不保证「内容不可读」。所以 payload 里绝对不能放密码、身份证、完整手机号这类敏感数据，否则就是信息泄露。如果确实需要加密内容，要用的是 JWE 而不是 JWS，但业务里很少这么做，更常见的做法是 payload 里只放用户 id 和角色，敏感数据回后端按 id 查。

**Q：JWT 有哪些经典漏洞？你怎么测？**

A：主要四类。第一是算法缺陷：服务端如果信任 header 里的 alg，就会被 alg=none 绕过，或者被 RS256 降级成 HS256、拿公开的公钥当 HMAC 密钥来伪造签名。第二是签名缺陷：最严重的是服务端只 decode 不 verify，我把 payload 里的 role 从 user 改成 admin、签名一个字都不动重放，如果管理接口能通就是签名根本没验。第三是时效缺陷：payload 里没有 exp 就是永久有效，或者有效期长达几个月。第四是注销缺陷：JWT 无状态收不回，登出和改密后旧 token 往往还能用。测法统一是「用自己账号的 token,解码看内容、篡改字段、重放观察」，全程在测试环境、不碰别人的 token、不跑密钥爆破。

**Q：JWT 怎么实现登出？无状态和可撤销矛盾吗？**

A：确实矛盾。纯无状态方案下 token 签出去就收不回，登出只能靠前端删本地存储，token 在有效期内仍然有效。工程上三种折中：一是 access token 做很短（15 分钟内），登出时作废 refresh token，最多留一个短窗口；二是维护黑名单，把登出的 token 的 jti 放进 Redis 并设到原过期时间，校验时查一次；三是在用户表存 token_version 写进 payload，登出或改密时自增，校验时比对。后两种都要查库，牺牲了完全无状态，但换来可撤销性，绝大多数业务系统都应该这么做。答不出这个 trade-off 说明没真正理解为什么用 JWT。

**Q：alg=none 和 RS256 降级到 HS256 分别是怎么回事？**

A：两者都源于「服务端信任了 header 里的 alg」。alg=none 是 JWT 规范里真的定义了一个「不签名」的算法，如果服务端没禁用它，攻击者把 header 的 alg 改成 none、签名段留空，服务端就直接认了内容。RS256 降级更隐蔽：RS256 是非对称的，私钥签名、公钥验签，公钥本来是可以公开的；攻击者把 alg 从 RS256 改成 HS256，而 HS256 是对称的，如果服务端实现是「按 header 的 alg 选算法、用同一份密钥材料」，它就会拿本该公开的公钥当 HMAC 的密钥去验——攻击者手里也有这个公钥，于是能自己签出合法 token。两个问题的修复是同一句话：服务端固定算法白名单，绝不读 header 里的 alg。

## 参考

- [RFC 7519 – JSON Web Token](https://datatracker.ietf.org/doc/html/rfc7519)
- [OWASP JSON Web Token for Java Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/JSON_Web_Token_for_Java_Cheat_Sheet.html)
- [PyJWT 官方文档](https://pyjwt.readthedocs.io/)
- 相关笔记：[[认证与会话安全测试]]、[[水平越权与垂直越权测试]]、[[敏感信息泄露与传输配置测试]]、[[Burp Suite 抓包改包工作流]]、[[10-安全测试]]
