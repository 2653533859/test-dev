---
created: 2026-09-29
tags: [WebSocket测试/安全防护]
---

# WebSocket 鉴权与安全防护测试

> 长连接安全防线：测试握手期鉴权安全、运行中 Token 过期注销、跨站 WebSocket 劫持（CSWSH 漏洞攻防）以及未授权频道越权订阅。

## 概念

### 传统 HTTP 安全模型在 WebSocket 中的失效

与传统基于「每个请求都携带 Authorization 头部进行无状态鉴权」的 HTTP 接口不同，WebSocket 连接建立后**只在握手阶段校验一次身份**，后续数据帧在长达数小时的交互中不再重复校验身份。这带来了独特的安全风险：

1. **Token 过期但长连接不断开**：用户登录态过期或管理员在后台将用户封禁注销，但因为 WebSocket 长连接已经建立，恶意用户依然能够持续接收内部敏感推送；
2. **跨站 WebSocket 劫持（CSWSH, Cross-Site WebSocket Hijacking）**：
   - 浏览器在发起 WebSocket 握手时，**会自动附带目标域名的 Cookie**；
   - 与普通 AJAX 受同源策略（SOP）严格限制不同，**浏览器对 WebSocket 握手请求完全不施加同源策略拦截**！受害者访问恶意网站时，黑客页面可以直接发起连接到受害者所在银行或企业内网的 WebSocket，若服务端未校验 `Origin` 头，将直接导致长连接被跨站劫持，全量私密数据实时外泄。
3. **未授权频道越权订阅（BOLA）**：用户 A 连上 WebSocket 后，向服务端发送 `{"action": "subscribe", "channel": "user_B_orders"}`，服务端只检查了该连接是否合法登录，未校验该连接是否有权订阅用户 B 的私有频道。

---

## 用法

### 1. CSWSH（跨站 WebSocket 劫持）漏洞自动化验证用例

测试用例通过伪造一个不受信任的外部域名作为 `Origin` 发起握手，断言服务端必须返回 **403 Forbidden** 或拒绝建立握手：

```python
import pytest
import websocket


def test_cswsh_origin_validation():
    """测试服务端是否严格校验握手 Origin 头（防止跨站劫持）"""
    target_ws_url = "wss://api.mall.internal/ws/notifications"

    # 模拟攻击者网站 https://evil-attacker.com 发起的跨站连接请求
    malicious_headers = [
        "Origin: https://evil-attacker.com",
        "Cookie: SESSIONID=valid_user_session_cookie_12345",
    ]

    # 期望：服务端识别到 Origin 属于未授权域名，立即拒绝握手（抛出 403 异常）
    with pytest.raises(websocket.WebSocketBadStatusException) as exc_info:
        websocket.create_connection(target_ws_url, header=malicious_headers)

    assert exc_info.value.status_code in [
        403,
        401,
    ], f"安全漏洞：服务端未校验 Origin 头，允许了来自外部恶意的跨站握手！状态码: {exc_info.value.status_code}"
```

### 2. 运行中 Token 过期强制踢出下线测试

在后台通过 API 吊销用户 Token，断言服务端必须在指定时间（如 5 秒内）主动向该长连接下发关闭帧（Close Code: 4001 / 1008）：

```python
def test_revoked_token_force_disconnect(ws_client, auth_service_api):
    """测试用户被踢出或注销后，长连接是否会被服务端主动强制切断"""
    # 1. 验证长连接初始工作正常
    ws_client.send_json({"type": "ping"})
    assert ws_client.recv_json(timeout=2.0)["type"] == "pong"

    # 2. 调用后台管理接口将当前用户强制注销并加入 Redis 黑名单
    auth_service_api.revoke_user_token(user_id="USR-8801")

    # 3. 再次向 WebSocket 发送消息，断言服务端已主动关闭连接
    with pytest.raises(websocket.WebSocketConnectionClosedException):
        # 等待服务端后台巡检触发踢出（或在下一次通信时拦截）
        for _ in range(5):
            ws_client.send_json({"type": "query_sensitive_data"})
            time.sleep(1)
            ws_client.recv_json(timeout=1.0)
```

### 3. 水平越权频道订阅测试

```python
def test_horizontal_privilege_subscription(ws_client_user_a):
    """测试普通用户 A 尝试订阅管理员或用户 B 的私有数据频道"""
    # 用户 A 发送订阅用户 B 私有通道指令
    ws_client_user_a.send_json(
        {
            "action": "subscribe",
            "topic": "finance_orders_private_user_B",  # 试图偷窥他人财务数据
        }
    )

    response = ws_client_user_a.recv_json(timeout=3.0)
    # 必须显式返回权限拒绝
    assert response["code"] in [403, 40301]
    assert "Permission denied" in response["msg"]
```

---

## 踩坑

1. **将敏感 Token 放在 URL Query Params 导致日志泄漏**：
   - *案例*：前端为了简单，连接写成 `wss://api.mall.com/ws?token=eyJhbGciOi...`。
   - *风险*：所有中间反向代理（Nginx、网关）、浏览器历史记录、服务端访问日志（access.log）中都完整记录了带有该 Token 的完整 URL。Token 极易在日志审计平台中被越权查看。
   - *解法*：在握手阶段通过 `Sec-WebSocket-Protocol` 自定义子协议或标准 `Authorization: Bearer <token>` Header 传递，或者采用两段式临时 Ticket 模式（先通过 HTTPS POST 换取一个 30 秒有效的一次性 ticket 用于握手）。
2. **Origin 校验使用前缀模糊匹配被绕过**：
   - *案例*：服务端校验代码写成 `if origin.startswith("https://mall.com")`。
   - *绕过*：攻击者注册域名 `https://mall.com.evil-hacker.com`，轻松绕过前缀校验。
   - *解法*：严格解析 Origin 域名，使用白名单绝对比对，或严谨使用正则 `r"^https://([a-zA-Z0-9-]+\.)*mall\.com$"`。

---

## 面试怎么答

**Q：WebSocket 相比传统 HTTP 存在哪些特有的安全漏洞？在安全测试中如何展开防护与验证？**
> 1. **跨站 WebSocket 劫持（CSWSH 漏洞）**：
>    - 浏览器在发起 WebSocket 升级握手时不受同源策略（SOP）限制，且会自动带上目标网站的 Cookie。如果服务端在握手阶段未严格校验 `Origin` 请求头，攻击者在第三方网站部署脚本即可诱导受害者浏览器与目标内网建立长连接，窃取实时推送流。
>    - **测试方法**：通过自动化脚本修改 `Origin: https://attacker.com` 尝试握手，验证服务端是否强制返回 403 拒绝。
> 2. **会话时效性断层（Token 过期不踢出）**：
>    - 由于长连接只在握手瞬间校验一次 Token，如果用户密码被修改、账号被后台封禁或 Token 到期，连接依然长驻。
>    - **防御与测试**：必须设计心跳巡检与服务端踢人事件总线。一旦用户认证失效，后台必须向其 WebSocket 连接推送 `0x8` 关闭帧（指定 Close Code: 4001）并强制关闭 TCP 连接。
> 3. **消息层授权与细粒度 ACL**：
>    - 握手鉴权只解决了「这个连接是谁」，必须在每次客户端发送 `subscribe` 订阅指令时，对目标 Topic 进行水平越权与垂直越权校验，禁止普通用户订阅管理通道。

---

## 参考

- PortSwigger: Cross-site WebSocket hijacking (CSWSH)：`https://portswigger.net/web-security/websockets/cross-site-websocket-hijacking`
- OWASP API Security Top 10 - Broken Object Level Authorization
- 相关笔记：[[10-安全测试]]、[[水平越权与垂直越权测试]]、[[14-WebSocket测试]]
