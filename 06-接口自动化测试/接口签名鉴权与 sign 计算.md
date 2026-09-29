---
created: 2026-07-31
tags: [接口自动化测试/鉴权]
---

# 接口签名鉴权与 sign 计算

> 签名校验失败时服务端只会甩给你一个「签名错误」，不会告诉你差在哪。搞清楚待签字符串是怎么拼的，才能少走两小时弯路。

## 概念

### 为什么要签名

Token 解决的是「你是谁」，签名解决的是另外三个问题：

1. **防篡改**：请求参数在传输途中被中间人改了（比如金额 100 改成 1），服务端能发现
2. **防重放**：抓到的请求包不能被无限次重放（靠 `timestamp` + `nonce`）
3. **身份认证**：只有持有 `app_secret` 的调用方才能算出正确签名

HTTPS 已经能防篡改和窃听，为什么还要签名？因为**开放平台的调用方是第三方服务器，而不是浏览器**——证书可能被替换、日志可能被留存、网关可能做 TLS 卸载。签名是应用层的独立保障，和传输层安全互补。

### 通用的签名算法骨架

绝大多数厂商（支付宝、微信支付、各类开放平台）的方案都是这个模式的变体：

```text
① 收集参与签名的参数（业务参数 + app_id + timestamp + nonce）
② 剔除 sign 本身、剔除空值
③ 按参数名 ASCII 升序排序
④ 拼成 key1=value1&key2=value2 的字符串
⑤ 拼上密钥：stringA + "&key=" + app_secret
⑥ 做摘要：MD5 / HMAC-SHA256 / RSA 签名
⑦ 结果转大写十六进制或 Base64，放进 sign 参数或请求头
```

差异全在细节上，而这些细节恰恰是踩坑重灾区：

| 变量点 | 常见取值 | 影响 |
|--------|----------|------|
| 空值处理 | 剔除 / 保留为空串 | 决定 stringA 内容 |
| 嵌套对象 | 整体 JSON 字符串 / 展平 / 不参与 | 差别巨大 |
| body 参与方式 | 原始 body 字符串 / 解析后再排序 | 决定能否用 `json=` |
| 大小写 | 结果转大写 / 小写 | 直接对不上 |
| 密钥拼接 | `&key=secret` / HMAC 的 key / 前后都拼 | 算法本身不同 |
| 时间戳单位 | 秒 / 毫秒 | 服务端时间窗校验���败 |

**没有通用实现，必须按对方文档逐字对齐。**

### 三种摘要方式

- **MD5**：`md5(stringA)`，最简单，安全性最弱（长度扩展攻击、彩虹表），老系统居多
- **HMAC-SHA256**：`hmac(key=secret, msg=stringA, digestmod=sha256)`，对称密钥，目前主流
- **RSA / SM2**：非对称，私钥签名公钥验签，用于对安全要求高的支付场景

## 用法

### 实现一个通用签名器

```python
import hashlib
import hmac
import json
import time
import uuid
from typing import Any


def build_sign_string(params: dict, *, skip_empty: bool = True) -> str:
    """按 key 的 ASCII 升序拼成 k1=v1&k2=v2。"""
    items = []
    for k in sorted(params):
        if k == "sign":
            continue
        v = params[k]
        if skip_empty and (v is None or v == ""):
            continue
        # 嵌套对象转紧凑 JSON（这一步各家不同，必须对文档确认）
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        elif isinstance(v, bool):
            v = "true" if v else "false"     # Python 的 True 会变 'True'，必须转
        items.append(f"{k}={v}")
    return "&".join(items)


def sign_md5(params: dict, secret: str) -> str:
    string_a = build_sign_string(params)
    string_sign_temp = f"{string_a}&key={secret}"
    return hashlib.md5(string_sign_temp.encode("utf-8")).hexdigest().upper()


def sign_hmac_sha256(params: dict, secret: str) -> str:
    string_a = build_sign_string(params)
    return hmac.new(
        secret.encode("utf-8"),
        string_a.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest().upper()
```

验证一遍：

```python
params = {
    "app_id": "wx1234",
    "amount": 100,
    "desc": "",                  # 空值会被剔除
    "nonce": "abc123",
    "timestamp": 1767200000,
}
print(build_sign_string(params))
# amount=100&app_id=wx1234&nonce=abc123&timestamp=1767200000
print(sign_md5(params, "SECRET"))
# 大写 32 位十六进制
```

### 封装进 Session：签名对用例透明

签名逻辑绝不能散落在每条用例里。挂在 Session 层：

```python
import requests

class SignedSession(requests.Session):
    def __init__(self, base_url: str, app_id: str, app_secret: str):
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.app_id = app_id
        self.app_secret = app_secret

    def request(self, method, url, *, json_body=None, params=None, **kwargs):
        if not url.startswith("http"):
            url = f"{self.base_url}{url}"
        kwargs.setdefault("timeout", (3, 10))

        payload: dict[str, Any] = dict(json_body or {})
        payload["app_id"] = self.app_id
        payload["timestamp"] = int(time.time())          # 注意单位！有的要毫秒
        payload["nonce"] = uuid.uuid4().hex
        payload["sign"] = sign_hmac_sha256(payload, self.app_secret)

        # 关键：用 data= 自己序列化，保证发出去的 body 与待签内容一致
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                          sort_keys=True).encode("utf-8")
        headers = kwargs.pop("headers", {}) or {}
        headers.setdefault("Content-Type", "application/json; charset=utf-8")
        return super().request(method, url, params=params, data=body,
                               headers=headers, **kwargs)
```

**为什么用 `data=` 而不是 `json=`**：`json=` 内部的 `json.dumps` 用默认分隔符 `(', ', ': ')`，带空格，而且不保证 key 顺序。你本地按紧凑无空格算的签名，和实际发出去的 body 对不上；如果服务端是「取原始 body 重新算签名」的实现方式，必然失败。详见 [[requests 的 params、data 与 json 参数区别]]。

### RSA 签名

```python
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
import base64

def sign_rsa(params: dict, private_key_pem: bytes) -> str:
    string_a = build_sign_string(params)
    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    signature = private_key.sign(
        string_a.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode()
```

验签（测试自己的响应签名时用）：

```python
def verify_rsa(params: dict, sign_b64: str, public_key_pem: bytes) -> bool:
    from cryptography.exceptions import InvalidSignature
    public_key = serialization.load_pem_public_key(public_key_pem)
    try:
        public_key.verify(
            base64.b64decode(sign_b64),
            build_sign_string(params).encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except InvalidSignature:
        return False
```

### 签名机制本身的测试用例

签名不只是「让用例能跑通」的障碍，它本身是被测对象：

```python
import pytest

def test_sign_ok(signed_client):
    r = signed_client.post("/api/pay", json_body={"amount": 100})
    assert r.status_code == 200

def test_tampered_param_rejected(raw_session, base_url, app_secret):
    """算完签名后偷偷改金额，服务端必须拒绝。"""
    payload = {"app_id": "wx1234", "amount": 100,
               "timestamp": int(time.time()), "nonce": uuid.uuid4().hex}
    payload["sign"] = sign_hmac_sha256(payload, app_secret)
    payload["amount"] = 1          # 签名之后篡改
    r = raw_session.post(f"{base_url}/api/pay", json=payload, timeout=(3, 10))
    assert r.status_code in (400, 403)
    assert "sign" in r.text.lower()

def test_expired_timestamp_rejected(raw_session, base_url, app_secret):
    """时间戳超出服务端允许窗口（通常 5 分钟）。"""
    payload = {"app_id": "wx1234", "amount": 100,
               "timestamp": int(time.time()) - 3600, "nonce": uuid.uuid4().hex}
    payload["sign"] = sign_hmac_sha256(payload, app_secret)
    r = raw_session.post(f"{base_url}/api/pay", json=payload, timeout=(3, 10))
    assert r.status_code in (400, 403)

def test_replay_rejected(raw_session, base_url, app_secret):
    """同一个 nonce 重放第二次应被拒绝。"""
    payload = {"app_id": "wx1234", "amount": 100,
               "timestamp": int(time.time()), "nonce": uuid.uuid4().hex}
    payload["sign"] = sign_hmac_sha256(payload, app_secret)
    first = raw_session.post(f"{base_url}/api/pay", json=payload, timeout=(3, 10))
    assert first.status_code == 200
    second = raw_session.post(f"{base_url}/api/pay", json=payload, timeout=(3, 10))
    assert second.status_code in (400, 409), "nonce 未做防重放，可被重放攻击"
```

最后一条经常能测出真问题：很多实现只校验了签名和时间戳，**根本没存 nonce**，在 5 分钟窗口内可以无限重放。支付场景下这是致命的。

### 对不上签名时的排查手段

不要盲猜，让服务端把它算出来的 stringA 吐出来对比。多数框架在 debug 级别日志里有。拿不到时，用二分法定位：

```python
def diff_sign_string(mine: str, theirs: str):
    """逐字符比对两个待签字符串，输出第一个不同的位置。"""
    for i, (a, b) in enumerate(zip(mine, theirs)):
        if a != b:
            print(f"第 {i} 位不同: 我={a!r}({ord(a)}) 对方={b!r}({ord(b)})")
            print(f"我的  : ...{mine[max(0, i-20):i+20]}...")
            print(f"对方的: ...{theirs[max(0, i-20):i+20]}...")
            return
    if len(mine) != len(theirs):
        print(f"长度不同: {len(mine)} vs {len(theirs)}")
        print(f"多出来的部分: {(mine if len(mine) > len(theirs) else theirs)[min(len(mine), len(theirs)):]!r}")
    else:
        print("完全一致，问题出在密钥或摘要算法")
```

## 踩坑

1. **用了 `json=` 导致签名失败**：requests 的 `json=` 序列化带空格、不排序，与待签字符串不一致。改用 `data=` 自己序列化。这是最高频的坑。
2. **中文编码不一致**：待签字符串必须明确 `encode("utf-8")`。对方文档若要求 GBK，或 URL-encode 后再签，差一步就全错。
3. **`ensure_ascii` 不一致**：`json.dumps` 默认把中文转成 `\uXXXX`，若文档要求原始 UTF-8，得写 `ensure_ascii=False`。
4. **Python 的 `True` 变成 `'True'`**：其他语言（Java/Go/JS）序列化布尔是 `true` 小写。必须手动转，否则纯粹因为大小写对不上。
5. **浮点数格式**：`100.0` 在 Python 里 `str()` 是 `'100.0'`，Java 的 `BigDecimal` 可能是 `'100.00'`。金额字段一律**用字符串传，不要用 float**，既避免精度问题也避免格式歧义。
6. **空值处理规则搞反**：文档说「剔除空值」，但没说 `0` 和 `false` 算不算空。Python 里 `if not v` 会把 `0`、`False`、`[]` 全过滤掉，这几乎肯定是错的。要写 `if v is None or v == ""`。
7. **时间戳单位错**：秒 vs 毫秒差 1000 倍，服务端时间窗校验直接失败，但报错还是笼统的「签名错误」，很难联想到。
8. **本地时钟不准**：Docker 容器或虚拟机时钟漂移超过服务端窗口（通常 ±5 分钟），签名永远过不了。`date` 一下再对比服务端时间。
9. **sign 参数自己参与了签名**：拼 stringA 时忘了排除 `sign` 键。
10. **密钥泄漏进 Git**：`app_secret` 硬编码在代码或 yaml 里提交上去。应该走环境变量 + CI 的凭据管理，仓库里只放占位符。
11. **只测通过路径，不测签名机制本身**：签名校验被后端注释掉了都不知道。上面那几条负向用例必须有。

## 面试怎么答

**Q：接口有签名校验，自动化怎么做？**

A：核心是**把签名逻辑封装在请求层，对用例透明**。我会写一个 `Session` 子类，重写 `request()`，在里面统一注入 `app_id`、`timestamp`、`nonce`，然后按对方文档的规则拼待签字符串——一般是剔除 sign 和空值、按 key 的 ASCII 升序拼成 `k1=v1&k2=v2`、拼上密钥后做 MD5 或 HMAC-SHA256、结果转大写。有个关键细节：**必须用 `data=` 自己序列化 body，不能用 `json=`**，因为 requests 的 `json=` 序列化会带空格且不保证 key 顺序，和你本地算签名用的字符串对不上，服务端一验就失败。密钥从环境变量读，绝不进仓库。

**Q：签名一直对不上，你怎么排查？**

A：先确认待签字符串本身。最快的路径是让后端把服务端算出来的 stringA 打到日志里，两边逐字符 diff，能立刻定位到是少了个参数、多了个空格、还是编码不同。拿不到服务端日志就自查这几个高频点：布尔值 Python 是 `True` 而其他语言是 `true`；中文是不是 UTF-8、`ensure_ascii` 开没开；浮点数格式是 `100.0` 还是 `100.00`；时间戳单位是秒还是毫秒；空值是剔除还是保留；有没有把 `sign` 自己也拼进去了。最后才怀疑摘要算法和密钥。整个过程本质是**二分定位**，不要一次改多个变量。

**Q：签名机制本身你会怎么测？**

A：至少四类负向用例。第一，算完签名后篡改某个参数（比如金额从 100 改成 1），服务端必须拒绝，否则防篡改形同虚设。第二，时间戳超出允许窗口（比如改成一小时前），应该被拒，验证时间窗生效。第三，同一个 `nonce` 重放第二次——很多实现只校验签名和时间戳，压根没存 nonce，5 分钟窗口内可以无限重放，支付场景下这是致命缺陷，这条用例价值最高。第四，用错误的 `app_secret` 算签名，验证密钥校验生效。此外还要确认服务端的错误码能区分「签名错误」「时间戳过期」「重放」，笼统返回一个 `sign error` 对排障很不友好，这本身也是个可以提的建议。

## 参考

- [Python hmac 模块](https://docs.python.org/zh-cn/3/library/hmac.html)
- [Python hashlib 模块](https://docs.python.org/zh-cn/3/library/hashlib.html)
- [cryptography 文档](https://cryptography.io/en/latest/)
- 相关笔记：[[requests 的 params、data 与 json 参数区别]]、[[Token 与 JWT 鉴权的获取与刷新]]、[[加密与解密接口的处理]]
