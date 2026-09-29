---
created: 2026-07-31
tags: [App自动化测试/专项测试]
---

# App 弱网测试：Charles 与网络损伤注入

![[assets/weak-network-test.svg]]
*图示：弱网测试链路——脚本通过代理（Charles / toxiproxy）把损伤注入到 App 与后端之间，再驱动 App 走异常网络路径，验证超时、重试与降级表现。*

> 用户真在地铁、电梯、山村。弱网下不崩、能重试、有提示，是 App 质量的分水岭。弱网测试的本质是「在脚本可控的网络损伤下跑真实用例」。

## 概念

### 弱网要模拟哪几类损伤

| 损伤类型 | 参数 | 用户场景 |
|---|---|---|
| 延迟 Latency | RTT 200ms~2000ms | 跨省/跨国、信号弱 |
| 带宽限制 Bandwidth | 上行/下行 KB/s | 2G、拥挤 wifi |
| 丢包 Packet Loss | 5%~30% | 移动切换基站 |
| 抖动 Jitter | 延迟波动 | 高速移动 |
| 断网/恢复 | 瞬时断开 | 进隧道 |

### 两条主流技术路线

1. **代理类（Charles / Fiddler）**：让设备走 HTTP 代理，在代理上设 Throttle。优点是能同时看报文、改响应；缺点是只覆盖走代理的流量（HTTPS 需装证书），且对 TCP 层丢包模拟不够真实。
2. **损伤注入类（toxiproxy / Linux tc / adb）**：在网络栈层注入丢包、延迟，覆盖所有流量更真实，适合混沌工程式压测。

## 用法

### 一、Charles 代理 + Throttle（最常用）

```bash
# 设备设置代理指向 Charles 主机 IP:8888
# Charles → Proxy → Throttle Settings 预设：
#   2G: 上行 20KB/s 下行 50KB/s 延迟 500ms
#   3G: 上行 100KB/s 下行 250KB/s 延迟 150ms
#   Very Bad Network: 延迟 2000ms 丢包 30%
```

```python
# 自动化里只需确保设备代理已指向 Charles，用例照常跑
# 验证弱网下「发送验证码」有超时提示而非 ANR
send_code_btn.click()
# 弱网延迟下按钮应进入 loading，而非卡死
WebDriverWait(driver, 15).until(
    EC.visibility_of_ELEMENT((AppiumBy.ID, "com.xxx:id/tv_error"))
)
assert "网络" in driver.find_ELEMENT(AppiumBy.ID, "com.xxx:id/tv_error").text
```

### 二、toxiproxy 注入丢包/延迟（代码可控）

```python
import requests

# 创建一个带延迟+丢包的 proxy
requests.post("http://toxiproxy:8474/proxies", json={
    "name": "app-backend",
    "listen": "0.0.0.0:8080",
    "upstream": "backend.internal:80",
    "enabled": True,
})
# 注入 1000ms 延迟 + 20% 收包丢包
requests.post("http://toxiproxy:8474/proxies/app-backend/toxics", json={
    "type": "latency", "attributes": {"latency": 1000}
})
requests.post("http://toxiproxy:8474/proxies/app-backend/toxics", json={
    "type": "packet_loss", "attributes": {"loss": 20}
})
```

```python
# 用例里动态开关损伤，模拟「进隧道断网再恢复」
requests.post("http://toxiproxy:8474/proxies/app-backend", json={"enabled": False})  # 断网
time.sleep(5)
requests.post("http://toxiproxy:8474/proxies/app-backend", json={"enabled": True})   # 恢复
```

### 三、adb 直接限速（Android 免代理）

```bash
# 通过 adb 限制带宽（需 root 或 shell 权限，部分 ROM 支持）
adb shell settings put global wifi_idle_ms 0
# 用 tc netem 注入（root 设备）
adb shell tc qdisc add dev wlan0 root netem delay 800ms loss 15%
```

### 四、用 pytest 参数化覆盖多档网络

```python
@pytest.mark.parametrize("profile", ["wifi", "3g", "bad", "offline"])
def test_login_under_network(driver, profile, proxy_ctl):
    proxy_ctl.apply(profile)        # 切到对应损伤档
    do_login(driver)
    # 弱网下断言：要么登录成功，要么有明确错误提示，绝不 ANR
    assert not is_anr(driver)
```

## 踩坑

1. **Charles 没装 HTTPS 证书，HTTPS 流量抓不到也拦不住**：设备必须装 Charles root 证书并信任（Android 7+ 还要在 App `res/xml/ network_security_config` 里加用户证书信任），否则只看到 CONNECT 失败。
2. **代理只覆盖应用层流量，WebSocket/长连可能直连**：部分 SDK 绕过系统代理走直连 IP，弱网没生效，用例假绿。验证损伤是否真的生效：在 App 里请求一个可控接口，看耗时是否随配置变化。
3. **toxiproxy 只代理 TCP，UDP（如音视频）不受影响**：音视频弱网要另走 tc netem。别假设一套代理覆盖全部。
4. **弱网用例超时设太短，把「正常慢」当失败**：弱网 RTT 2000ms，接口本来就要 3~5 秒，timeout 设 3 秒必红。弱网档的等待阈值要单独放大。
5. **断网恢复后 App 不自动重连**：很多 App 断了就停在错误页不重试。弱网测试要验证「恢复后能否手动/自动重试成功」，这恰恰是常出 bug 处。
6. **丢包导致 Mock 响应也丢，断言误判**：toxiproxy 丢的是后端包，如果你的测试桩也在同一链路，桩响应也丢。测试桩要放在损伤之外（或单独豁免）。
7. **iOS 模拟器走的是宿主机网络，Charles 代理要设对**：iOS 模拟器的代理在宿主机网络栈，真机要连同一 wifi 段。两者配置位置不同，别配错。
8. **弱网用例在 CI 上把整条流水线拖慢数倍**：弱网档每个操作都慢，全套跑完可能 10 倍时长。弱网只挑核心链路参数化，不要全量套弱网。
9. **「断网」用 `airplane mode` 命令不稳定**：`adb shell am broadcast -a android.intent.action.AIRPLANE_MODE` 在部分 ROM 被禁，且恢复有延迟。优先用代理 disable / toxiproxy `enabled:false`，更可控。
10. **没验证降级 UI**：弱网不只是「要不崩」，还要「有 loading、有重试按钮、有友好文案」。断言要覆盖这三件套，而非只看不闪退。

## 面试怎么答

**30 秒骨架**：弱网测试是往真实用例链路里注入可控的网络损伤——延迟、带宽限制、丢包、抖动、断网恢复。常用两条路线：Charles 代理做 Throttle，好处是能同时看报文、改响应，适合覆盖应用层 HTTP；toxiproxy / `tc netem` 在网络栈层注入，更真实覆盖全流量。自动化里把损伤配置参数化，弱网档放大超时阈值，断言目标是「不崩、有 loading、有重试、有友好提示」。

**追问**：Charles 有什么局限？——只覆盖走代理的流量，HTTPS 要装证书，对 TCP 层丢包/UDP 长连模拟不真实，所以全链路弱网要上 tc netem 或 toxiproxy。

## 参考

- [Charles Throttle 设置](https://www.charlesproxy.com/documentation/)
- [toxiproxy 文档](https://github.com/Shopify/toxiproxy)
- 相关笔记：[[App UI 自动化稳定性治理]]、[[adb 常用命令详解]]、[[App 性能指标采集：FPS、内存、CPU、流量与耗电]]
