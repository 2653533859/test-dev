---
created: 2026-07-31
tags: [计算机网络/HTTPS, 计算机网络/证书链]
---

# HTTPS 证书链与抓包为什么要装根证书

> 上一节讲了 TLS 握手「协商出对称密钥」；这一节解决握手里最容易被当成黑盒的一环：**服务端发来的证书，客户端凭什么信它是真的？** 以及引申出的高频问题——抓 HTTPS 包为什么要在测试机装一张自己的根证书。

![[assets/tls-handshake.svg]]
*图示：第 ③ 步 `Certificate` 携带的就是证书链，客户端用它逐级验签。*

## 概念

### 证书链长什么样

一张 X.509 证书里至少装着：域名（CN/SAN）、公钥、签发者（Issuer）、有效期（notBefore / notAfter）、以及**签发者用它的私钥对以上信息做的数字签名**。

验证逻辑是一条「信任链」：

```text
你的浏览器/代码
   └─ 用「中间 CA」的公钥验签 → 确认这张中间证书没被篡改
        └─ 中间 CA 又由「根 CA」签发
             └─ 根 CA 的公钥预装在操作系统/浏览器的信任库里（这就是信任锚）
```

所以一张完整的链通常是三层：

```text
叶子证书 (leaf / end-entity)   ← 给你域名的证书，能直接挂到 443 端口
   ↑ 由 中间证书 (intermediate) 签发
中间证书                       ← 通常由根 CA 授权多家中间机构
   ↑ 由 根证书 (root) 签发
根证书                         ← 预装在 OS / 浏览器 / JDK 的 cacerts 里
```

**缺了任何一层，链都不完整**——很多命令行客户端、Java、移动端不像浏览器那样会自动补全，就会报 `unable to get local issuer certificate`。

### 为什么「抓包要装根证书」

TLS 的安全性最终建立在「**你信任的信任库没被污染**」之上。正常情况下，你只信任操作系统预装的正规根 CA（DigiCert、Let's Encrypt、ISRG 等）。

抓包工具要解密 HTTPS，本质是**扮演一个你自己授权的、受你信任的中间人**：

1. 抓包工具（mitmproxy / Fiddler / Charles）生成一对自己的「根证书 + 私钥」
2. 你把这张根证书**手动装进系统的信任库**（或浏览器的信任库、或 Python 的 `REQUESTS_CA_BUNDLE`、或 Java 的 `cacerts`）
3. 之后这条工具用这张根证书**动态签发任意域名的叶子证书**——因为你的信任库认这张根，客户端就会认为这些假证书也是「合法 CA 签发的」
4. 于是它就能在中间完成 TLS  termination：解密客户端流量 → 明文查看/修改 → 再代客户端去连真实服务端

**关键点**：装根证书 = 你亲自把一把「万能钥匙」交给了抓包工具。这正是为什么正规 CA 绝不会让你装它们的根去做这种事——你装的是**你自己的、只对你这台测试机生效的**根。生产环境绝不会、也不该装这种根证书。

## 用法

### 看一眼真实域名的完整证书链

```bash
# 最直白的查看方式：s_client 会打印整条链
openssl s_client -connect www.example.com:443 -servername www.example.com 2>/dev/null \
  | sed -n '/Certificate chain/,/---/p'

# 输出形如：
# Certificate chain
#  0 s:CN = www.example.com
#    i:C = US, O = Let's Encrypt, CN = R11      ← 叶子，由 R11 签发
#  1 s:C = US, O = Let's Encrypt, moderated, CN = R11   ← 中间
#    i:C = US, O = Internet Security Research Group, CN = ISRG Root X1  ← 根
```

### 自己签发一张「会被本地信任」的根（测试环境专用）

```bash
# 1) 生成根私钥与自签根证书（一次性）
openssl genrsa -out my-root.key 2048
openssl req -x509 -new -nodes -key my-root.key -sha256 -days 3650 \
  -subj "/C=CN/O=TestLab/CN=My Test Root CA" -out my-root.crt

# 2) 用这张根去签发一个域名证书
openssl genrsa -out app.key 2048
openssl req -new -key app.key -subj "/CN=test.internal" -out app.csr
openssl x509 -req -in app.csr -CA my-root.crt -CAkey my-root.key \
  -CAcreateserial -out app.crt -days 825 -sha256

# 3) 让系统信任这张根（macOS / Linux 差异很大，下面是 Linux 的 NSS 方式）
#    Windows / macOS 走系统钥匙串，把 my-root.crt 导入即可
sudo cp my-root.crt /usr/local/share/ca-certificates/my-test-root.crt
sudo update-ca-certificates      # 之后 curl / git / 各类 CLI 都会认 test.internal
```

### Python 侧显式指定信任锚

```python
import requests

# 内网自签 CA 的正确做法：把刚才的 my-root.crt 指给 verify
r = requests.get("https://test.internal/", verify="/usr/local/share/ca-certificates/my-test-root.crt")
print(r.status_code)

# 想复现「证书不被信任」报错？把 verify 指成一张无关的根
try:
    requests.get("https://test.internal/", verify="/etc/ssl/certs/unrelated-ca.pem")
except requests.exceptions.SSLError as e:
    print("预期之中：", e)
```

## 踩坑

1. **「浏览器能访问，脚本报证书错」十有八九是链不完整**。浏览器会自动沿 AIA 扩展拉取缺失的中间证书；而 `requests`、`okhttp`、老版本 `curl` 不会。定位第一步：用上面 `openssl s_client` 看 `Certificate chain` 里到底有几层。

2. **装了根证书但没生效**。macOS 上导入 `.crt` 后仍要在「钥匙串访问」里把这张根的「使用此证书时」改成「始终信任」，否则 Safari 会当没看见。Linux 上改完要 `update-ca-certificates`，且依赖的程序必须读系统证书库（Go / Rust 默认读，Node 默认读，但静态编译的 busybox 不读）。

3. **Docker 容器里「装了根也不认」**。容器镜像往往基于 `debian:slim` 或 `alpine`，它们各自有独立的证书路径（`/etc/ssl/certs/ca-certificates.crt` vs `update-ca-certificates` 生成的 bundle），且 Java 容器读的是 `$JAVA_HOME/lib/security/cacerts`。三个地方要同步，漏一个就半信半疑。

4. **CI 里 `verify=False` 被扫成高危**。安全测试会标记「关闭证书校验」的调用。正确做法是把内网 CA 打进镜像的信任库，而不是全局 `verify=False` 蒙混。

5. **抓包工具的「解密」只对它自己生成的流量有效**。你装了 mitmproxy 的根，只能解密**经过 mitmproxy 转发**的流量；直连真实服务端的流量照常是密文，Wireshark 里看到的仍是 TLS 记录。别指望拿一张测试根去解密生产流量——那恰恰说明信任锚被污染了。

## 面试怎么答

**Q：证书链断了会怎样？**

A：取决于谁在验证。浏览器会直接标红「您的连接不是私密连接」；而 Java 客户端会抛 `sun.security.validator.ValidatorException: PKIX path building failed`；`curl` 报 `SSL certificate problem: unable to get local issuer certificate`。开发本地一切正常（浏览器自动补全）但上线后 App 报错，基本都是叶子证书漏了中间证书这一层。

**Q：为什么不能所有人都用一张自签根？**

A：自签根不在任何正规信任库里，必须**每台机器手动装**才能被信。这意味着它只适合你完全控制的测试机；一旦流到生产，就等于给所有流量发了一张「可以被中间人冒用」的万能通行证。所以规范做法是：**测试环境用自签根，生产用公开 Trust Store（Let's Encrypt 等）签发的证书**。

**Q：抓包装根证书算不算「中间人攻击」？**

A：从技术机制上**完全一样**——都是拦截 + 用自己的根签发。区别只在「是否经过你本人授权」。你明确知情同意并主动安装，就是合法的调试手段；未经用户同意偷偷装根证书（某些恶意软件这么干），就是实打实的中间人攻击。所以合规红线是：**只在你自己的、隔离的测试机上装，绝不进生产**。

**Q：证书链和「证书固定 / Certificate Pinning」什么关系？**

A：Pinning 是把「我信任的具体叶子/中间证书公钥」硬编码进客户端，跳过整条链验证。它比链验证更严格——即使攻击者拿到一张受信 CA 签的假证书，因为公钥对不上 Pin，也会被拒。代价是证书轮换时必须同步更新 Pin，否则直接连不上。

## 参考

- [RFC 5280 - X.509 证书与 CRL 标准](https://datatracker.ietf.org/doc/html/rfc5280)
- [OWASP - 证书与公钥固定](https://owasp.org/www-community/controls/Certificate_and_Public_Key_Pinning)
- [mitmproxy 文档：证书安装](https://docs.mitmproxy.org/stable/concepts-certificates/)
- 相关笔记：[[HTTPS 加密原理与 TLS 握手过程]]、[[抓包工具选型：Wireshark、Fiddler、Charles 与 mitmproxy]]、[[从输入 URL 到页面渲染的完整链路]]
