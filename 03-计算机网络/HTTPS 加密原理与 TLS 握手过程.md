---
created: 2026-07-31
tags: [计算机网络/HTTPS]
---

# HTTPS 加密原理与 TLS 握手过程

> HTTPS = HTTP + TLS。它要同时解决三个问题：**别人看不到（机密性）、别人改不了（完整性）、对面确实是他（身份认证）**。少解决任何一个，加密都没有意义。

![[assets/tls-handshake.svg]]
*图示：TLS 1.2 握手全过程——用非对称加密安全地协商出一把对称密钥，之后所有数据用对称加密传输。*

## 概念

### HTTP 的三个致命问题

| 问题 | 后果 | TLS 的解法 |
|------|------|-----------|
| 明文传输 | 任何中间节点都能看到密码、Token | **对称加密**（AES） |
| 内容可被篡改 | 运营商插广告、注入恶意脚本 | **消息认证码**（HMAC / AEAD） |
| 身份无法验证 | DNS 劫持后你连的是钓鱼站却毫无察觉 | **数字证书 + 证书链** |

**第三点最容易被忽略但最关键**。如果只加密不验证身份，中间人可以直接冒充服务端跟你建立加密连接——你加密得再好，也是把秘密加密后交给了骗子。

### 对称加密 vs 非对称加密

**对称加密**：加密和解密用同一把密钥。代表算法 AES、ChaCha20。

- 优点：**快**，AES 有 CPU 硬件指令（AES-NI）加速，吞吐可达 GB/s 级
- 致命问题：**密钥怎么安全地送到对方手里？** 在不安全的网络上传密钥，等于没加密

**非对称加密**：公钥加密、私钥解密（或私钥签名、公钥验签）。代表算法 RSA、ECC。

- 优点：**公钥可以公开**，完美解决密钥分发问题
- 缺点：**慢**，RSA 比 AES 慢几百倍到上千倍，且能加密的数据长度受密钥长度限制

**TLS 的方案是两者结合**：用非对称加密安全地协商出一把对称密钥（只需要在握手阶段做一次），之后的海量业务数据全用对称加密传输。**用慢但安全的方式传钥匙，用快的方式传数据。**

### 数字证书解决什么问题

即使有了非对称加密，还有一个漏洞：**你怎么知道拿到的公钥真的是目标网站的，而不是中间人的？**

中间人可以拦截服务端的公钥，换成自己的公钥发给你。你用中间人的公钥加密，中间人解密后再用真实服务端的公钥转发——全程无感。

**数字证书就是「公钥的身份证」**，由权威第三方 CA（Certificate Authority）用自己的私钥对「域名 + 公钥 + 有效期 + 签发者」这一整套信息做签名。

验证逻辑：

1. 操作系统/浏览器内置了一批**根证书**（受信任的 CA 公钥）
2. 收到服务端证书后，用签发它的上级 CA 公钥验签
3. 上级 CA 证书再用它的上级验签，一路验到根证书
4. 根证书在本地信任库里 → 整条链可信

这就是**证书链**。详见 [[HTTPS 证书链与抓包为什么要装根证书]]。

### TLS 1.2 握手全过程

```text
客户端                                                    服务端
   |                                                        |
   |  ① ClientHello                                         |
   |     · 支持的 TLS 版本                                    |
   |     · 密码套件列表（如 TLS_ECDHE_RSA_WITH_AES_128_GCM）  |
   |     · 随机数 Random1                                     |
   |     · SNI: api.example.com  ← 告诉服务端要访问哪个域名     |
   |------------------------------------------------------->|
   |                                                        |
   |  ② ServerHello                                         |
   |     · 选定的 TLS 版本与密码套件                           |
   |     · 随机数 Random2                                     |
   |  ③ Certificate（服务端证书链）                            |
   |  ④ ServerKeyExchange（ECDHE 参数，1.2 中 ECDHE 套件才有）  |
   |  ⑤ ServerHelloDone                                     |
   |<-------------------------------------------------------|
   |                                                        |
   | ⑥ 客户端验证证书：签名链 / 有效期 / 域名匹配 / 吊销状态      |
   |                                                        |
   |  ⑦ ClientKeyExchange                                   |
   |     · 用证书公钥加密 Pre-Master Secret（或发 ECDHE 公钥）   |
   |  ⑧ ChangeCipherSpec（之后我发的都加密了）                  |
   |  ⑨ Finished（用会话密钥加密的校验值，验证握手没被篡改）      |
   |------------------------------------------------------->|
   |                                                        |
   |  ⑩ ChangeCipherSpec + Finished                          |
   |<-------------------------------------------------------|
   |                                                        |
   |  === 之后所有 HTTP 报文用会话密钥对称加密 ===              |
```

**会话密钥怎么来的**：双方各自用 `Random1 + Random2 + Pre-Master Secret` 通过密钥导出函数（PRF/HKDF）算出同一把 Master Secret，再派生出实际使用的加密密钥和 MAC 密钥。

为什么要三个随机数？防**重放攻击**。如果只用 Pre-Master，攻击者录下一次握手就能重放。两个明文随机数保证了每次会话的密钥都不同。

### 密码套件怎么读

```text
TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256
 |    |     |        |    |    |
 |    |     |        |    |    └─ 哈希算法：SHA256（用于 PRF 和 HMAC）
 |    |     |        |    └────── 加密模式：GCM（带认证的加密 AEAD）
 |    |     |        └─────────── 对称算法：AES-128
 |    |     └──────────────────── 身份认证：RSA（证书里的签名算法）
 |    └────────────────────────── 密钥交换：ECDHE（椭圆曲线临时 DH）
 └─────────────────────────────── 协议：TLS
```

**ECDHE 中的 E 代表 ephemeral（临时）**，这是**前向保密（Forward Secrecy）**的关键：每次会话用临时生成的密钥对，用完即弃。即使服务端私钥将来泄露，攻击者也无法解密之前录制的流量。

对比：传统 RSA 密钥交换（`TLS_RSA_WITH_...`）把 Pre-Master 用服务端公钥加密传输，**一旦私钥泄露，历史流量全部可解**。所以 TLS 1.3 直接把 RSA 密钥交换删掉了。

### TLS 1.3 的改进

| | TLS 1.2 | TLS 1.3 |
|---|---------|---------|
| 握手 RTT | 2-RTT | **1-RTT**，会话复用 0-RTT |
| 密钥交换 | RSA / DHE / ECDHE | **只保留 (EC)DHE**，强制前向保密 |
| 密码套件数量 | 上百种（很多不安全） | **只剩 5 种** |
| 不安全算法 | 仍支持 RC4、MD5、SHA1、CBC | **全部移除** |
| 证书传输 | 明文 | **加密**（ServerHello 后即加密） |

1-RTT 的实现方式：客户端在 ClientHello 里**直接猜一个密钥交换参数发过去**（KeyShare 扩展），如果服务端认可这个算法，就能少一轮往返。

**0-RTT 有安全代价**：会话复用时携带的早期数据（early data）**没有前向保密、且可被重放**。所以 0-RTT 只能用于幂等请求，绝不能用于下单、支付。这是个很好的面试追问点。

## 用法

### 用 openssl 完整查看握手

```bash
# 最常用的诊断命令，输出证书链、协商结果、密码套件
openssl s_client -connect api.example.com:443 -servername api.example.com

# 关键输出解读：
# ---
# Certificate chain
#  0 s:CN = api.example.com          ← 服务端证书（叶子）
#    i:C = US, O = Let's Encrypt, CN = R3   ← 签发者
#  1 s:C = US, O = Let's Encrypt, CN = R3   ← 中间证书
#    i:C = US, O = ISRG, CN = ISRG Root X1  ← 根
# ---
# SSL handshake has read 3512 bytes and written 396 bytes
# New, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384
# Verify return code: 0 (ok)          ← 0 表示验证通过
```

```bash
# 只看证书有效期（监控证书过期的标准做法）
echo | openssl s_client -connect api.example.com:443 -servername api.example.com 2>/dev/null \
  | openssl x509 -noout -dates -subject -issuer

# notBefore=Jun  1 00:00:00 2026 GMT
# notAfter=Aug 30 23:59:59 2026 GMT
# subject=CN = api.example.com
# issuer=C = US, O = Let's Encrypt, CN = R3

# 强制指定 TLS 版本，验证服务端是否还支持不安全的老版本
openssl s_client -connect api.example.com:443 -tls1      # 应当失败
openssl s_client -connect api.example.com:443 -tls1_1    # 应当失败
openssl s_client -connect api.example.com:443 -tls1_2    # 应当成功
openssl s_client -connect api.example.com:443 -tls1_3    # 应当成功

# 查看服务端支持的密码套件（枚举方式）
nmap --script ssl-enum-ciphers -p 443 api.example.com
```

### curl 侧的验证

```bash
# -v 会打印 TLS 握手细节
curl -v https://api.example.com/ 2>&1 | grep -E 'SSL connection|subject|issuer|ALPN'

# 忽略证书错误（仅用于自签名的测试环境，生产脚本严禁使用）
curl -k https://test.internal/

# 指定自定义 CA（正确的内网测试做法，比 -k 安全）
curl --cacert /path/to/internal-ca.pem https://test.internal/

# 双向认证：带上客户端证书
curl --cert client.crt --key client.key https://mtls.example.com/api

# 分阶段耗时：定位 TLS 握手是不是瓶颈
curl -o /dev/null -s -w "TCP:%{time_connect}s TLS完成:%{time_appconnect}s 总:%{time_total}s\n" \
  https://api.example.com/
# TLS 握手耗时 = time_appconnect - time_connect
```

### 证书过期监控脚本

证书过期是**最常见也最容易避免**的线上事故，值得做成定时任务：

```python
import ssl
import socket
from datetime import datetime, timezone


def days_until_expiry(host: str, port: int = 443) -> int:
    """返回证书还有多少天过期"""
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=5) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:   # server_hostname 即 SNI
            cert = ssock.getpeercert()
    # notAfter 格式：'Aug 30 23:59:59 2026 GMT'
    expire = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    return (expire - datetime.now(timezone.utc)).days


DOMAINS = ["api.example.com", "www.example.com", "cdn.example.com"]

for d in DOMAINS:
    try:
        left = days_until_expiry(d)
        level = "严重" if left < 7 else ("警告" if left < 30 else "正常")
        print(f"[{level}] {d}: 还有 {left} 天过期")
    except Exception as e:
        print(f"[异常] {d}: {e}")
```

### 用 pytest 做 TLS 安全基线检查

```python
import ssl
import socket
import pytest

HOST = "api.example.com"


def _handshake(protocol_version):
    ctx = ssl.SSLContext(protocol_version)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((HOST, 443), timeout=5) as s:
        with ctx.wrap_socket(s, server_hostname=HOST) as ss:
            return ss.version()


def test_tls10_disabled():
    """TLS 1.0 已被 PCI DSS 禁用，服务端不应支持"""
    with pytest.raises((ssl.SSLError, OSError)):
        _handshake(ssl.PROTOCOL_TLSv1)


def test_tls12_or_above():
    ctx = ssl.create_default_context()
    with socket.create_connection((HOST, 443), timeout=5) as s:
        with ctx.wrap_socket(s, server_hostname=HOST) as ss:
            assert ss.version() in ("TLSv1.2", "TLSv1.3")
            cipher, ver, bits = ss.cipher()
            assert bits >= 128, f"加密强度不足: {bits} bits"
            assert "RC4" not in cipher and "MD5" not in cipher


def test_cert_valid_for_hostname():
    """默认 context 会校验域名与有效期，抛异常就说明证书有问题"""
    ctx = ssl.create_default_context()
    with socket.create_connection((HOST, 443), timeout=5) as s:
        with ctx.wrap_socket(s, server_hostname=HOST):
            pass    # 不抛异常即通过
```

### 抓 HTTPS 明文的合规方式

```bash
# 方式一：SSLKEYLOGFILE —— 让客户端导出会话密钥给 Wireshark 解密
export SSLKEYLOGFILE=/tmp/sslkeys.log
curl https://api.example.com/v1/orders
# Wireshark → 首选项 → Protocols → TLS → (Pre)-Master-Secret log filename

# Chrome 也支持（启动前设置环境变量）
SSLKEYLOGFILE=/tmp/sslkeys.log google-chrome

# 方式二：用中间人代理（需装根证书），详见证书链笔记
mitmproxy --listen-port 8080
```

## 踩坑

1. **本地时间不准导致「证书无效」**。证书校验会比对当前时间与 notBefore/notAfter。测试机时钟漂移、Docker 容器时区错误、CI runner 时间不同步，都会导致「证书尚未生效」或「证书已过期」的假报错。**排查证书问题第一步永远是 `date` 看看时间对不对。**

2. **缺少 SNI 导致返回了错误站点的证书**。一个 IP 上跑多个 HTTPS 站点时，服务端靠 ClientHello 里的 SNI 扩展决定返回哪张证书。用 IP 直连或用不支持 SNI 的老客户端，会拿到默认站点的证书，报「域名不匹配」。测试时要显式指定：

   ```bash
   openssl s_client -connect 10.0.2.30:443 -servername api.example.com
   curl --resolve api.example.com:443:10.0.2.30 https://api.example.com/health
   ```

   `--resolve` 比改 hosts 更优雅：只影响这一条命令，且 SNI 和 Host 头都正确。

3. **生产脚本里用 `verify=False` / `-k` 关掉证书校验**。这等于把 HTTPS 降级成「加密但不认人」，中间人攻击畅通无阻。而且一旦养成习惯，真的证书过期了也发现不了。**内网自签名证书的正确做法是把内网 CA 加进信任链**：

   ```python
   import requests
   # 错误做法
   requests.get(url, verify=False)          # 还会刷一堆 InsecureRequestWarning

   # 正确做法
   requests.get(url, verify="/etc/ssl/certs/internal-ca.pem")

   # 或者用环境变量全局指定
   # export REQUESTS_CA_BUNDLE=/etc/ssl/certs/internal-ca.pem
   ```

4. **只部署了叶子证书，漏了中间证书**。浏览器通常能靠 AIA 扩展自动补全中间证书，所以开发本地测试一切正常；但很多命令行工具、Java 客户端、移动端**不会自动补全**，直接报「unable to get local issuer certificate」。表现为「浏览器能访问，App 和脚本报错」。验证方法：

   ```bash
   openssl s_client -connect api.example.com:443 -servername api.example.com 2>/dev/null \
     | grep -E '^ *[0-9] s:'
   # 应当看到叶子证书 + 至少一张中间证书
   ```

   或者直接用 [SSL Labs](https://www.ssllabs.com/ssltest/) 扫描，它会明确指出 "Chain issues: Incomplete"。

5. **TLS 握手成为性能瓶颈却没被发现**。完整握手要 2 个 RTT（TLS 1.2），跨地域场景下可能占到总耗时的一半。压测时如果不开长连接，测的其实是「握手性能」而不是「业务性能」。用 `curl -w` 把 `time_appconnect - time_connect` 单独看，超过 100ms 就要考虑开启会话复用（Session Resumption）或升级 TLS 1.3。

6. **HSTS 导致测试环境无法用 HTTP 访问**。服务端返回 `Strict-Transport-Security` 后，浏览器会**在本地记住这个域名必须走 HTTPS**，之后即使手动输 http:// 也会被浏览器内部 307 跳转到 https。测试环境证书不全时会很麻烦。清除方法：Chrome 访问 `chrome://net-internals/#hsts`，在 Delete domain security policies 里删除该域名。

7. **把「加密」和「编码」搞混**。Base64 是编码不是加密，任何人都能解。见过接口把密码 Base64 后当作「已加密」传输，这在安全测试里是必须提的高危缺陷。Basic 认证的 `Authorization: Basic xxx` 也是同理，纯 Base64，必须依赖 HTTPS 保护。

8. **0-RTT 用在非幂等接口上**。TLS 1.3 的 0-RTT 早期数据可以被重放攻击，如果用在下单、转账接口上，攻击者录制后重放就能造成重复扣款。**0-RTT 只能用于幂等的 GET 请求**，这一点在配置 CDN 和网关时要特别确认。

## 面试怎么答

**Q：HTTPS 的加密过程是怎样的？**

A（30 秒骨架）：HTTPS 是 HTTP 加上 TLS。核心思路是**非对称加密协商密钥、对称加密传数据**。握手时客户端发 ClientHello 带随机数和支持的密码套件，服务端回 ServerHello 选定套件并发来证书；客户端验证证书链、有效期、域名是否匹配；验证通过后用证书里的公钥加密（或用 ECDHE 协商）出 Pre-Master Secret，双方结合两个随机数各自导出同一把会话密钥；之后所有 HTTP 报文用这把对称密钥加密。这么设计是因为非对称加密安全但慢几百倍，对称加密快但没法安全地分发密钥，所以只在握手阶段用一次非对称，把密钥安全送达。

**Q：为什么需要 CA 和证书？只用非对称加密不行吗？**

A：不行，因为**光有公钥无法证明公钥的归属**。中间人可以拦截服务端发来的公钥，替换成自己的，你用它加密后中间人解密再转发给真实服务端，全程无感。证书就是「公钥的身份证」——CA 用自己的私钥对「域名 + 公钥 + 有效期」签名，客户端用操作系统内置的根证书公钥逐级验签。只有验到本地信任库里的根证书，整条链才可信。所以 HTTPS 的安全性最终依赖于「操作系统信任库里的根证书没被污染」，这也是为什么抓包工具必须往信任库里装自己的根证书。

**Q：什么是前向保密？**

A：指**即使服务端私钥将来泄露，攻击者也无法解密之前录制的历史流量**。传统的 RSA 密钥交换不具备这个性质——Pre-Master Secret 是用服务端公钥加密传输的，私钥一旦泄露，把历史流量翻出来全能解。而 ECDHE 的 E 是 ephemeral（临时）的意思，每次会话都用临时生成的密钥对，用完即弃，服务端私钥只用于**签名证明身份**，不参与密钥加密。所以历史流量各自独立，泄露一次不影响其他。TLS 1.3 直接把不具备前向保密的 RSA 密钥交换删掉了，强制使用 (EC)DHE。

**Q：TLS 1.3 相比 1.2 有什么改进？**

A：四点。第一，**握手从 2-RTT 压缩到 1-RTT**，做法是客户端在 ClientHello 里直接猜一个密钥交换参数发过去；会话复用还能做到 0-RTT。第二，**只保留 (EC)DHE 密钥交换**，强制前向保密。第三，**密码套件从上百种精简到 5 种**，把 RC4、MD5、SHA1、CBC 模式这些有已知弱点的算法全部移除，大幅降低配置出错的可能。第四，**证书也加密传输了**，1.2 里证书是明文的，会泄露访问的站点信息。需要注意 0-RTT 有安全代价——早期数据没有前向保密且可被重放，所以只能用于幂等请求。

**Q：HTTPS 就一定安全吗？**

A：不一定，它保护的是**传输通道**，不解决其他环节。几个常见的破绽：客户端如果关闭了证书校验（`verify=False`、`-k`），中间人攻击畅通无阻；如果用户点了「继续访问不安全站点」，加密也就形同虚设；服务端支持 TLS 1.0 或弱密码套件的话，可以被降级攻击；如果证书链不完整或根证书信任库被污染（比如恶意软件装了自己的根证书），整个信任基础就崩了。另外 HTTPS 只加密内容，**SNI 和 DNS 查询仍然是明文的**，观察者还是能看到你访问了哪个域名——这也是 ECH 和 DoH 这些新技术要解决的问题。

## 参考

- [RFC 8446 - TLS 1.3](https://datatracker.ietf.org/doc/html/rfc8446)
- [RFC 5246 - TLS 1.2](https://datatracker.ietf.org/doc/html/rfc5246)
- [SSL Labs 在线检测](https://www.ssllabs.com/ssltest/)
- 相关笔记：[[HTTPS 证书链与抓包为什么要装根证书]]、[[HTTP 长连接与 HTTP-2 多路复用]]、[[抓包工具选型：Wireshark、Fiddler、Charles 与 mitmproxy]]、[[从输入 URL 到页面渲染的完整链路]]
