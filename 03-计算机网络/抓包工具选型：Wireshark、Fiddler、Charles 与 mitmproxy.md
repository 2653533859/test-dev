---
created: 2026-07-31
tags: [计算机网络/抓包]
---

# 抓包工具选型：Wireshark、Fiddler、Charles 与 mitmproxy

> 接口测试、性能定位离不开抓包。四种工具各守一段：Wireshark 看「网卡层」，Fiddler/Charles 是「HTTP 正向代理」，mitmproxy 是「可编程的 HTTPS 中间人」。选错工具，等于拿手术刀去拧螺丝。

![[assets/mitm-proxy.svg]]
*图示：mitmproxy 作为可编程正向代理，解密 HTTPS 后把明文交给你。*

## 概念

### 四工具定位一览

| 工具 | 工作层 | 看得到什么 | 最适合 |
|------|--------|-----------|--------|
| **Wireshark** | 网卡/抓包驱动 | 所有协议的原始包（TCP/UDP/DNS/TLS 记录） | 看重传、乱序、RST、握手失败 |
| **Fiddler** | HTTP 正向代理 | 明文 HTTP + 解密后的 HTTPS（装根后） | Windows 桌面端调试 Web |
| **Charles** | HTTP 正向代理 | 同 Fiddler，跨平台 GUI 更强 | 移动端 HTTPS 抓包 |
| **mitmproxy** | 可编程正向代理 | 能写 Python 改请求/响应 | 自动化测试、CI 里动态改包 |

### 为什么抓不到 HTTPS 明文

HTTPS 流量在网卡层看是**密文 TLS 记录**——Wireshark 抓到也是一堆加密字节。要看到明文，只有两条路：

1. **SSLKEYLOGFILE**：让客户端（Chrome / curl / 自己的程序）把协商出的对称密钥导出来，Wireshark 用它解密。最干净、不改架构。
2. **中间人代理（装根证书）**：让流量经过你信任的代理，代理用你装的根证书动态签叶子证书，从而明文可见。适合无法改客户端的环境。

## 用法

### Wireshark 抓「为什么连不上」

```bash
# 1) 抓 10 秒 443 端口的包，过滤重传和 RST
tshark -i any -f "tcp port 443" -a duration:10 \
  -Y "tcp.analysis.retransmission || tcp.flags.reset == 1" -V > /tmp/cap.txt

# 2) 看 TLS 握手失败：过滤 tls.handshake.type == 1（ClientHello）
tshark -r /tmp/cap.pcap -Y "tls.handshake.type == 1" -T fields -e ip.dst
```

### Fiddler / Charles 解密 HTTPS（装根）

```text
# Fiddler: Tools → Options → HTTPS → 勾选 "Decrypt HTTPS traffic" → 信任根证书
# Charles: Proxy → SSL Proxying Settings → 添加域名 → Install Charles Root Certificate
# 之后浏览器走 127.0.0.1:8888，所有 HTTPS 变明文
```

### mitmproxy 在 CI 里动态改包（最实用）

```python
# addon.py —— 自动化测试里把响应里的错误码改成成功，验证前端容错
from mitmproxy import http

def response(flow: http.HTTPFlow):
    if "api.internal" in flow.request.pretty_url:
        # 把 500 伪装成 200，测前端降级
        if flow.response.status_code == 500:
            pass
        # 真改法：
        if flow.response.status_code >= 500:
            flow.response.status_code = 200
            flow.response.headers["X-Injected-By"] = "mitmproxy-test"
            flow.response.text = '{"ok":true,"injected":true}'

# 启动：
#   mitmdump -s addon.py -p 8080
# 之后代码 / 浏览器把代理指到 127.0.0.1:8080 即可
```

### curl 配合 mitmproxy 解密

```bash
# 让 curl 走 mitmproxy（HTTP 代理），且用 SSLKEYLOGFILE 双保险
export HTTPS_PROXY=http://127.0.0.1:8080
export SSLKEYLOGFILE=/tmp/keys.log
curl -v https://api.internal/health      # 既经代理解密，又能用 Wireshark 看明文
```

## 踩坑

1. **Wireshark 抓不到云服务器的包**。云厂商的网卡在宿主机侧，虚拟机里抓 `any` 只能看到**出虚拟机的那一段**，看不到宿主机和物理交换机之间的链路。真要抓全链路，得在宿主机或交换机做端口镜像（SPAN）。

2. **Fiddler/Charles 抓不到「不走代理」的流量**。很多程序（尤其 Java / 某些 SDK）会读 `NO_PROXY` 环境变量或自己写死直连，绕过系统代理。现象是「工具里空空如也，但请求明明发出去了」——这时只能靠 SSLKEYLOGFILE 那条路。

3. **移动端抓 HTTPS 必须装根，且 iOS 还得手动信任**。iOS 13+ 装了描述文件还不够，要到「设置 → 关于本机 → 证书信任设置」里手动开关打开，否则 HTTPS 仍被拦。这是 Apple 故意加的摩擦。

4. **mitmproxy 的 addon 语法随版本变**。老教程写 `def response(context, flow)` 在新版会报错（改成 `flow: http.HTTPFlow`）。复制粘贴前先 `mitmproxy --version` 对齐文档。

5. **抓包文件太大卡死 Wireshark**。高 QPS 服务抓 10 秒就是几 GB。正确做法：用 `tshark -b filesize:100000` 按 100MB 滚动切割，或先 `-f` 过滤再抓。

6. **代理和「直连」在日志里分不清**。你以为流量走了 mitmproxy，其实是直连了真实服务端——区别只在客户端有没有把代理指过去。排查：`netstat -an | grep 8080` 看有没有连上代理端口，或 `curl -x http://127.0.0.1:8080` 显式走代理验证。

## 面试怎么答

**Q：四种工具怎么选？**

A：看**你要什么层的信息**。**Wireshark** 看「网卡原始包」——排查重传、乱序、RST、握手失败这类网络层问题；**Fiddler / Charles** 看「HTTP 应用层」——调试 Web 前后端交互、改参数重放；**mitmproxy** 是「可编程的中间人」——在自动化测试里动态改响应、模拟弱网、批量改包。一句话：**网络问题用 Wireshark，应用调试用 Fiddler/Charles，自动化用 mitmproxy**。

**Q：为什么 HTTPS 不能「直接」被 Wireshark 解密？**

A：因为 TLS 的目的是**让中间人即使抓到包也看不懂**。Wireshark 抓到的是密文 TLS 记录，没有密钥就是一堆乱码。解密的唯一前提是拿到对称密钥——要么客户端主动用 `SSLKEYLOGFILE` 导出，要么你作为受信任的中间人（装根证书）参与握手。这就是「抓 HTTPS 明文必须装根」的根本原因。

**Q：mitmproxy 和 Fiddler 本质区别？**

A：**Fiddler / Charles 是「带 GUI 的现成工具」**，点点点就能用，但改包逻辑受限于它提供的功能；**mitmproxy 是「可编程的代理」**，你用 Python 写 addon，能做任何 Fiddler 做不到的事（比如根据请求内容动态决定改不改、改什么）。所以前者适合手动调试，后者适合**塞进 CI 做自动化**。

## 参考

- [Wireshark 官方文档](https://www.wireshark.org/docs/)
- [mitmproxy 官方文档](https://docs.mitmproxy.org/stable/)
- [Charles 官方文档](https://www.charlesproxy.com/documentation/)
- 相关笔记：[[HTTPS 证书链与抓包为什么要装根证书]]、[[跨域与 CORS]]、[[从输入 URL 到页面渲染的完整链路]]
