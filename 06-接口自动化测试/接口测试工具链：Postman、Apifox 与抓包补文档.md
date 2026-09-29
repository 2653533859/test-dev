---
created: 2026-07-31
tags: [接口自动化测试/工具链]
---

# 接口测试工具链：Postman、Apifox 与抓包补文档

> 写自动化之前，先用工具把接口手工跑通一遍——自动化脚本调不通时，你要能立刻分清是「脚本写错了」还是「接口本身就有问题」。

## 概念

### 为什么不能上来就写 requests

新手最常见的翻车顺序是：拿到接口文档 → 直接写 pytest 用例 → 跑出 401/500 → 花两小时怀疑自己的代码。

问题在于**没有隔离变量**。一个接口调用链上至少有四个可疑点：

1. 接口文档写错了（字段名、必填项、Content-Type）
2. 环境不对（域名、网关、测试账号没权限）
3. 服务端本身有 bug
4. 你的脚本写错了

手工工具（Postman / Apifox）的价值就是**先把 1～3 排干净**，确认「这个请求在工具里 200 了」，再翻译成代码。此时脚本不通，一定是第 4 点。

### 三类工具的分工

| 工具 | 本质 | 在流程中的位置 | 不可替代的点 |
|------|------|----------------|--------------|
| Swagger / OpenAPI | 接口**契约的机器可读来源** | 需求/联调阶段 | 能被程序解析，批量生成用例骨架 |
| Postman / Apifox | 手工调试 + 集合运行 | 写自动化之前 | 快速试参、环境变量、脚本前置处理 |
| 抓包（Charles / Fiddler / mitmproxy） | 观察**真实流量** | 文档不全 / 对不上时 | 拿到文档里没写的 header、加密后的真实 body |

一句话概括：**Swagger 给你「应该是什么」，抓包给你「实际是什么」，Postman 是中间的验证台。**

### Apifox 与 Postman 的区别

Postman 是纯粹的 API 客户端，文档能力弱；Apifox 把「文档 + 调试 + Mock + 自动化」缝在一起，改了文档字段，Mock 数据和用例参数同步变。国内团队用 Apifox 的多，本质原因是**它强迫后端把文档当作单一数据源**，而不是写完接口再补一份很快过期的 Word。

对测试来说，选哪个不重要，重要的是：**你的自动化用例的接口定义，必须和团队公认的那份文档同源**，否则永远在追着后端改。

## 用法

### 从 OpenAPI 文档批量生成用例骨架

Swagger 页面右上角一般能拿到 `openapi.json` / `swagger.json`。这个 JSON 是结构化的，可以直接解析出所有接口，避免手工抄。

```python
import json
from pathlib import Path

spec = json.loads(Path("openapi.json").read_text(encoding="utf-8"))

for path, methods in spec["paths"].items():
    for method, detail in methods.items():
        if method not in ("get", "post", "put", "delete", "patch"):
            continue  # 跳过 parameters、summary 这类同级键
        summary = detail.get("summary", "")
        # 必填 query / path 参数
        required = [
            p["name"] for p in detail.get("parameters", [])
            if p.get("required")
        ]
        print(f"{method.upper():6} {path:40} {summary}  必填={required}")
```

输出直接就是一张待覆盖清单，再配合下面这段生成 pytest 骨架：

```python
def gen_case(path: str, method: str, summary: str) -> str:
    """把接口定义翻译成一段可以直接粘进用例文件的骨架。"""
    func = path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
    return f'''
def test_{method}_{func}(api_client):
    """{summary}"""
    r = api_client.{method}("{path}")
    assert r.status_code == 200
    # TODO: 补结构断言与业务断言
'''

print(gen_case("/api/v1/orders", "post", "创建订单"))
```

**注意**：生成的只是骨架，用例的价值在断言和边界设计，这一步只是省掉抄接口路径的体力活。

### Postman 环境变量与前置脚本

Postman 的核心是**变量分层**：全局 < 集合 < 环境 < 局部。测试环境切换靠换 Environment，而不是改一堆 URL。

前置脚本（Pre-request Script）里写登录取 token，是最常用的套路：

```javascript
// Pre-request Script：没有 token 或已过期就重新登录
const token = pm.environment.get("access_token");
if (!token) {
    pm.sendRequest({
        url: pm.environment.get("base_url") + "/api/login",
        method: "POST",
        header: { "Content-Type": "application/json" },
        body: { mode: "raw", raw: JSON.stringify({ username: "qa", password: "123456" }) }
    }, (err, res) => {
        pm.environment.set("access_token", res.json().data.token);
    });
}
```

请求头里就写 `Authorization: Bearer {{access_token}}`。

### 用 mitmproxy 补文档缺失的字段

App 端接口最常见的情况是：文档只写了业务字段，实际请求里还有一堆设备号、签名、埋点 header。这些必须抓包才能拿到。

```bash
# 启动代理，手机 WiFi 代理指向 <本机IP>:8080，并安装 mitmproxy 证书
mitmproxy -p 8080

# 只关心某个域名，避免噪音
mitmproxy -p 8080 --set view_filter="~d api.example.com"
```

mitmproxy 支持用 Python 脚本自动落盘，方便批量对比文档：

```python
# dump_api.py：mitmdump -s dump_api.py
import json
from mitmproxy import http

def response(flow: http.HTTPFlow) -> None:
    if "api.example.com" not in flow.request.pretty_host:
        return
    record = {
        "method": flow.request.method,
        "url": flow.request.pretty_url,
        "req_headers": dict(flow.request.headers),
        "req_body": flow.request.get_text(),
        "status": flow.response.status_code,
        "resp_body": flow.response.get_text()[:2000],
    }
    with open("captured.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
```

抓到的 `captured.jsonl` 可以直接喂给脚本，和 `openapi.json` 做字段差集，把「文档里没有但实际必传」的 header 找出来。

### Postman 集合 → 代码的正确姿势

Postman 有「Code snippet」能一键导出 requests 代码，但**导出来的代码不能直接进仓库**：它会把 token、Cookie、host 全部硬编码进去。

正确做法是只抄三样东西：请求方法与路径、必要的 header 清单、body 结构。其余交给自己的封装层（见 [[requests Session 会话保持与 Cookie]]）。

## 踩坑

1. **Postman 能通、脚本 401**：多半是 Postman 的 Cookie Jar 悄悄帮你带上了登录 Cookie，而脚本里用的是 `requests.get()` 裸调用。Postman 右上角 Cookies 面板能看到实际带了什么，逐条对齐。
2. **Postman 能通、脚本 415 Unsupported Media Type**：Postman 选 `raw + JSON` 会自动加 `Content-Type: application/json`，代码里用 `data=` 传 dict 则是表单编码。见 [[requests 的 params、data 与 json 参数区别]]。
3. **Swagger 上「Try it out」通了，正式环境不通**：Swagger 页面往往部署在服务内网，绕过了网关鉴权/限流。测试要走和真实客户端一样的入口域名。
4. **抓 HTTPS 抓出一堆 `CONNECT`，看不到明文**：证书没装或没被信任。Android 7+ 用户证书默认不被 App 信任，需要 root 装系统证书，或用带 `network_security_config` 的测试包。
5. **抓包时 App 直接连不上网**：App 做了 SSL Pinning（证书绑定），检测到中间人就断开。要么要开发出一个关掉 pinning 的测试包，要么用 Frida hook，别硬刚。
6. **文档字段的「可选」不可信**：文档写可选、实际不传就 500 的情况极其常见。设计用例时对每个「可选」字段都单独跑一条不传的用例，这本身就是很有价值的一类缺陷。
7. **导出的 Postman 集合把生产 token 提交进了 Git**：Postman 导出 JSON 会带上环境变量当前值。提交前务必清空敏感变量，或把环境文件加进 `.gitignore`。

## 面试怎么答

**Q：接口文档不全或者和实际不一致，你怎么做接口测试？**

A：分三步。第一步用 Swagger / Apifox 拿到现有契约，能解析 `openapi.json` 就批量导出接口清单，先明确覆盖范围。第二步对文档存疑的接口用 Postman 手工跑通，把真实的必填项、Content-Type、错误码试出来。第三步如果是 App 或前端才有的接口，直接用 Charles / mitmproxy 抓真实流量，把文档里没写的 header（设备号、签名、traceId）补上，并且把抓到的报文和文档做差集，输出一份「文档与实现不一致清单」提给开发——这件事本身就是测试的产出，不只是为了自己写脚本方便。

**Q：为什么不直接把 Postman 集合跑起来当自动化？**

A：Postman + Newman 确实能跑，适合冒烟。但做体系化自动化有三个硬伤：一是断言写在 JS 脚本里，没法复用 Python 生态的 JSON Schema、数据库校验；二是集合是 JSON 大文件，多人协作时 Git 冲突极难合；三是数据驱动、参数化、fixture 依赖管理能力远不如 pytest。所以我的做法是 **Postman 只做调试和探索性验证，正式用例落在 pytest + requests 上**。

**Q：抓包工具你用哪个，区别是什么？**

A：Charles 图形化好、改包（Rewrite / Map Local）方便，日常调试首选；Fiddler 在 Windows 上轻量，扩展性好；mitmproxy 是命令行 + Python 脚本，优势是能写脚本批量处理，适合放进 CI 或做流量录制回放。选型看场景：手工调试用 Charles，要做流量录制生成用例就用 mitmproxy。

## 参考

- [OpenAPI Specification](https://spec.openapis.org/oas/latest.html)
- [Postman Scripting 文档](https://learning.postman.com/docs/writing-scripts/intro-to-scripts/)
- [mitmproxy 官方文档](https://docs.mitmproxy.org/stable/)
- 相关笔记：[[requests 请求与响应对象]]、[[requests 的 params、data 与 json 参数区别]]、[[接口用例设计维度]]
