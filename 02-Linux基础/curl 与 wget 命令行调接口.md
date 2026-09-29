---
created: 2026-07-31
tags: [Linux基础/网络]
---

# curl 与 wget 命令行调接口

> 在没有 Postman 的服务器上验证接口、看真实的请求响应头、量出每一段耗时——测试开发的日常武器。

## 概念

### curl 与 wget 的定位差异

| 维度 | curl | wget |
|------|------|------|
| 定位 | **传输数据**（支持 20+ 协议） | **下载文件** |
| 默认输出 | 输出到 stdout | 保存为文件 |
| 请求方法 | 全支持（GET/POST/PUT/PATCH/DELETE） | 基本只有 GET/POST |
| 递归下载 | 不支持 | 支持（`-r` 可整站抓取） |
| 断点续传 | `-C -` | `-c` |
| 重定向 | **默认不跟随**，要加 `-L` | 默认跟随 |
| 典型用途 | 调接口、看响应头、测耗时 | 下载安装包、镜像文件 |

**一句话**：调接口用 `curl`，下载文件用 `wget`。

### 为什么测试开发必须会 curl

- 服务器上没有图形界面，Postman 用不了。
- 能看到**最原始**的请求和响应（`-v`），排查「Postman 能通、代码不通」这类问题时是唯一可信的参照。
- 能精确测量 DNS、TCP、TLS、首字节等各阶段耗时（`-w`），定位「接口慢在哪一段」。
- 能直接嵌进 Shell 脚本做健康检查、冒烟验证、CI 门禁。
- 浏览器 F12 里可以「Copy as cURL」，把浏览器的请求原样搬到服务器上复现。

## 用法

### 基本请求

```bash
curl https://api.example.com/users                 # GET，响应打到 stdout
curl -s https://api.example.com/users              # 静默：不显示进度条（脚本里必加）
curl -o users.json https://api.example.com/users   # 保存到文件
curl -O https://example.com/app.tar.gz             # 用远端文件名保存
curl -L https://short.url/abc                      # 跟随 301/302 重定向
curl -i https://api.example.com/users              # 响应头 + 响应体
curl -I https://api.example.com/users              # 只要响应头（发 HEAD 请求）
curl -v https://api.example.com/users              # 详细过程：DNS、TLS 握手、请求头、响应头
```

`-v` 输出的符号：`*` 是 curl 的过程信息、`>` 是发出的请求、`<` 是收到的响应。

### POST 与各种 body

```bash
# JSON（最常用）
curl -X POST https://api.example.com/login \
     -H "Content-Type: application/json" \
     -d '{"username":"test","password":"123456"}'

# 从文件读 body（body 很长时）
curl -X POST https://api.example.com/orders \
     -H "Content-Type: application/json" \
     -d @order.json

# 表单
curl -X POST https://api.example.com/login \
     -d "username=test&password=123456"

# 文件上传（multipart/form-data）
curl -X POST https://api.example.com/upload \
     -F "file=@/tmp/report.pdf" \
     -F "type=report"

# 其他方法
curl -X PUT    -H "Content-Type: application/json" -d '{"name":"new"}' https://api.example.com/users/1
curl -X DELETE https://api.example.com/users/1
```

> **注意**：`-d` 会自动把方法改成 POST，所以 `curl -d '...' url` 里的 `-X POST` 可以省略。但 `-X` 和 `-L` 混用有坑：重定向后 curl 会保持你显式指定的方法，可能不符合预期。

### 鉴权

```bash
# Bearer Token
curl -H "Authorization: Bearer eyJhbGciOi..." https://api.example.com/me

# Basic Auth
curl -u username:password https://api.example.com/me
curl -u username https://api.example.com/me           # 不写密码会交互式提示（更安全）

# 自定义 header
curl -H "X-Request-Id: test-001" -H "X-Env: uat" https://api.example.com/ping

# Cookie
curl -b "sessionid=abc123" https://api.example.com/profile
curl -c cookies.txt -d "user=test&pwd=123" https://api.example.com/login   # 保存 cookie
curl -b cookies.txt https://api.example.com/profile                        # 带上 cookie
```

登录态串联的完整例子：

```bash
# 1. 登录拿 token
TOKEN=$(curl -s -X POST https://api.example.com/login \
        -H "Content-Type: application/json" \
        -d '{"username":"test","password":"123456"}' | jq -r '.data.token')

# 2. 用 token 调业务接口
curl -s -H "Authorization: Bearer ${TOKEN}" https://api.example.com/orders | jq '.data[] | {id, status}'
```

`jq` 是处理 JSON 响应的最佳搭档，服务器上装一个（`yum install jq`）能省大量时间。

### 只取状态码 / 测耗时（性能排查关键）

```bash
# 只输出 HTTP 状态码，健康检查用
curl -s -o /dev/null -w "%{http_code}" https://api.example.com/health

# 分段耗时 —— 定位「接口慢在哪一段」
curl -s -o /dev/null -w "\
DNS解析:      %{time_namelookup}s
TCP连接:      %{time_connect}s
TLS握手:      %{time_appconnect}s
请求发出:     %{time_pretransfer}s
首字节(TTFB): %{time_starttransfer}s
总耗时:       %{time_total}s
下载大小:     %{size_download} bytes
" https://api.example.com/orders
```

怎么读这组数据：

- `time_namelookup` 大 → **DNS 慢**，检查 `/etc/resolv.conf`、换 DNS、或用 `--resolve` 绕过。
- `time_connect - time_namelookup` 大 → **TCP 建连慢**，网络延迟或中间设备。
- `time_appconnect - time_connect` 大 → **TLS 握手慢**，证书链太长、OCSP 检查、加密套件不合适。
- `time_starttransfer - time_pretransfer` 大 → **服务端处理慢**，这才是应用的锅，去查后端。
- `time_total - time_starttransfer` 大 → **传输慢**，响应体太大或带宽不足。

这个拆解能直接回答「接口慢是网络问题还是服务问题」，是性能排查的第一手证据。

### 调试与压测辅助

```bash
curl --connect-timeout 5 --max-time 30 https://api.example.com/slow   # 超时控制
curl --retry 3 --retry-delay 2 https://api.example.com/flaky          # 重试
curl -k https://self-signed.example.com                                # 跳过证书校验（仅测试环境）
curl --resolve api.example.com:443:10.0.0.5 https://api.example.com/   # 绕过 DNS 直连指定 IP，灰度验证利器
curl -x http://127.0.0.1:8888 https://api.example.com/                 # 走代理，配合 Charles/mitmproxy 抓包
curl --http1.1 https://api.example.com/                                # 强制协议版本
curl -H "Accept-Encoding: gzip" --compressed https://api.example.com/  # 压缩传输

# 简易并发压测（正式压测还是要用 JMeter）
seq 1 100 | xargs -P 10 -I{} curl -s -o /dev/null -w "%{http_code} %{time_total}\n" https://api.example.com/health
```

`--resolve` 是灰度发布验证的神器：域名不变、Host 头不变，但强制连到指定的后端 IP，可以逐台验证新版本。

### 在脚本里做健康检查

```bash
#!/usr/bin/env bash
set -uo pipefail

URL="https://api.example.com/health"
CODE=$(curl -s -o /tmp/health_body -w "%{http_code}" --connect-timeout 5 --max-time 10 "$URL")

if [ "$CODE" != "200" ]; then
    echo "$(date '+%F %T') 健康检查失败，状态码=${CODE}"
    cat /tmp/health_body
    exit 1
fi

# 进一步校验响应内容
if ! jq -e '.status == "UP"' /tmp/health_body > /dev/null; then
    echo "状态码 200 但业务状态异常"
    exit 1
fi
echo "OK"
```

注意 `curl` 默认**即使 HTTP 返回 500 也退出码 0**（因为传输成功了）。要让 curl 在 4xx/5xx 时返回非零退出码，加 `-f`（`--fail`）：

```bash
curl -sf https://api.example.com/health || echo "接口异常"
```

### wget 常用

```bash
wget https://example.com/app.tar.gz
wget -O app.tar.gz https://example.com/download?id=123   # 指定文件名
wget -c https://example.com/big.iso                      # 断点续传
wget -q https://example.com/x                            # 静默
wget --spider https://example.com/x                      # 只检查存在性，不下载
wget -r -np -k -p https://docs.example.com/              # 递归下载整站（-np 不上溯父目录）
wget --limit-rate=1m https://example.com/big.iso         # 限速，避免打满测试环境带宽
wget --header="Authorization: Bearer xxx" https://api.example.com/file
```

## 踩坑

1. **curl 默认不跟随重定向**。接口返回 301/302 时你只会看到一个空响应体，误以为接口挂了。加 `-L`。

2. **HTTP 500 时 curl 退出码仍是 0**。脚本里用 `-f` 让它在 4xx/5xx 返回非零，或者显式检查 `%{http_code}`。

3. **JSON 里的引号被 shell 吃掉**。`-d "{"a":1}"` 会出错。用**单引号包住整个 JSON**，JSON 内部用双引号；如果 JSON 里要嵌 shell 变量，改用 `-d @file` 或 here-doc：

   ```bash
   curl -X POST url -H "Content-Type: application/json" -d @- <<EOF
   {"user": "${USER_NAME}", "ts": $(date +%s)}
   EOF
   ```

4. **忘了 `Content-Type: application/json`**。curl 的 `-d` 默认发 `application/x-www-form-urlencoded`，服务端会解析失败返回 400 或 415。

5. **URL 里有 `&` 没加引号**。`curl http://x?a=1&b=2` 会被 shell 当成后台任务分隔符，只请求了 `?a=1`。**URL 一律加双引号**。

6. **密码写在命令行里泄露**。`ps -ef` 和 `~/.bash_history` 都能看到。用 `-u user`（交互输入）、`--netrc`、或从环境变量读。

7. **`-k` 跳过证书校验成了习惯**。测试环境无所谓，但会掩盖真实的证书链问题（中间证书缺失、域名不匹配），上线后暴露。定位证书问题应该用 `curl -v` 看握手细节或 `openssl s_client -connect host:443`。

8. **`-w` 的输出混进了响应体**。`-w` 的内容打到 stdout，如果没有 `-o /dev/null` 或 `-o file`，会和响应体粘在一起。

9. **测耗时时被 DNS 缓存影响**。第一次请求包含 DNS 解析时间，后续被缓存。要测真实首次访问用 `--dns-servers` 或每次换 `--resolve`。

10. **wget 递归下载把整站拖下来**。`-r` 不加 `-np`（no-parent）和 `-l`（层数限制）可能下载几十 G。先用 `--spider` 试探。

11. **容器里没有 curl**。很多精简镜像（Alpine、distroless）不带。用 `wget -qO-`，或者 bash 内建的 `/dev/tcp`：

    ```bash
    exec 3<>/dev/tcp/api.example.com/80
    printf 'GET /health HTTP/1.0\r\nHost: api.example.com\r\n\r\n' >&3
    cat <&3
    ```

## 面试怎么答

**Q：怎么用 curl 发一个带 token 的 POST JSON 请求？**

A：

```bash
curl -X POST https://api.example.com/orders \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer ${TOKEN}" \
     -d '{"sku":"A001","qty":2}' \
     -i
```

三个要点：`-H "Content-Type: application/json"` 必须显式加，否则 curl 默认发表单格式导致服务端 400；JSON 用单引号包裹避免 shell 解析内部的双引号；加 `-i` 能同时看到响应头，方便确认状态码和 trace-id。脚本里还要加 `-s` 静默和 `--max-time` 超时。

**Q：接口响应慢，你怎么用 curl 判断是网络问题还是服务端问题？**

A：用 `-w` 打印分段耗时：

```bash
curl -s -o /dev/null -w "dns:%{time_namelookup} conn:%{time_connect} tls:%{time_appconnect} ttfb:%{time_starttransfer} total:%{time_total}\n" URL
```

然后做差值分析：DNS 解析时间长说明 DNS 服务器有问题；`time_connect` 减 `time_namelookup` 是 TCP 建连耗时，长说明网络 RTT 大或中间设备有问题；`time_appconnect` 减 `time_connect` 是 TLS 握手，长可能是证书链或加密套件问题；**`time_starttransfer` 减 `time_pretransfer` 是服务端处理时间（TTFB），这一段长才是应用的锅**；最后 `time_total` 减 `time_starttransfer` 是响应体传输时间，长说明响应太大或带宽不足。

拿到这组数据就能明确地跟后端说「网络只用了 20ms，你的服务处理花了 3 秒」，避免扯皮。

**Q：curl 和 wget 的区别？**

A：curl 是通用的数据传输工具，支持 HTTP/HTTPS/FTP/SMTP 等二十多种协议，默认把响应输出到 stdout，支持所有 HTTP 方法和完整的请求头控制，适合调接口和调试。wget 是专门的下载工具，默认保存为文件，支持递归下载整站、断点续传、后台下载，适合拉安装包。

有两个默认行为的差异容易踩坑：curl 默认**不跟随**重定向（要加 `-L`），wget 默认跟随；curl 遇到 HTTP 错误码仍然退出码 0（要加 `-f` 才失败），wget 会返回非零。所以在 CI 脚本里用 curl 做检查一定要显式处理状态码。

**Q：怎么在不改 DNS 的情况下把请求打到指定的后端 IP？**

A：用 `--resolve`：

```bash
curl --resolve api.example.com:443:10.0.0.5 https://api.example.com/health
```

它在 curl 内部做了一条 DNS 记录覆盖，域名、SNI、Host 头、证书校验全都保持正常，只是把连接指向了指定 IP。这在灰度发布逐台验证、排查「某个后端节点异常」时非常有用，比改 `/etc/hosts` 干净（不影响其他进程、不需要 root、用完即走）。老写法是 `curl -H "Host: api.example.com" https://10.0.0.5/`，但那样 TLS 的 SNI 和证书校验会出问题，只适合 HTTP。

## 参考

- [curl 官方文档](https://curl.se/docs/manpage.html)
- [Everything curl（官方电子书）](https://everything.curl.dev/)
- [GNU Wget 手册](https://www.gnu.org/software/wget/manual/wget.html)
- 相关笔记：[[网络连通性排查：ping、telnet 与 traceroute]]
- 相关笔记：[[Linux 端口占用排查：netstat、ss 与 lsof]]
