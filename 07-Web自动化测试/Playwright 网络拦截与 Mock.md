---
created: 2026-07-31
tags: [Web自动化测试/进阶]
---

# Playwright 网络拦截与 Mock

![[assets/network-mock.svg]]
*图示：页面发起请求后，先经 `page.route` 注册的 handler 决策——命中则 `fulfill` 返回 Mock 数据、或 `abort` 模拟异常；未命中则 `continue_` 走真实网络。*

> 真正的端到端测试不该依赖第三方接口，但现实中支付、短信、地图这些外部依赖既慢又不可控。Playwright 的 `route` 让你在不改应用代码的前提下，把网络层「劫持」掉。

## 概念

### 为什么需要网络 Mock

端到端测试的理想是「跑真实全链路」，但有几个现实问题：

1. **外部依赖不稳定**：调短信网关、支付渠道，网络一抖用例就飘。
2. **难以构造的边界**：要测「余额不足」「接口 500」「弱网超时」，真实后端很难配合造这些状态。
3. **成本与合规**：每次都真发短信、真扣款，钱和合规都扛不住。
4. **提速**：把慢接口替换成毫秒级 Mock，整条链路快几倍。

### route 的本质：协议层拦截

Playwright 基于 CDP（Chrome DevTools Protocol），`page.route()` 在**浏览器网络层**注册拦截器。页面发出的每个请求在被发送到网络之前，先交给你的 handler。handler 有三个选择：

| 方法 | 行为 | 典型用途 |
|------|------|---------|
| `route.fulfill()` | 直接返回你构造的响应，**不发真实请求** | 返回固定 Mock 数据 |
| `route.continue_()` | 放行，走真实网络（可改 header/url） | 给所有请求加 token |
| `route.abort()` | 中断请求，模拟网络错误 | 模拟断网、4xx/5xx |

**这是协议层拦截，不是 JS 层面 mock**，所以即使前端代码写死了 `fetch("https://api/price")`，也能被拦下来换成你的数据。这是它相对「在前端代码里改接口地址」的根本优势：测试代码零侵入业务代码。

> Selenium 没有等价能力——它跑在 WebDriver 协议之上，碰不到网络层。要 Mock 只能自己在应用里加开关、或架一个 Mock Server（如 `mockserver` / `wiremock`），复杂度高很多。

## 用法

### 拦截并 Mock 一个接口

```python
from playwright.sync_api import sync_playwright

def test_price_mock():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        # 拦截 /api/price 这个接口，返回我们造的低价
        def handle(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"sku":"A1","price":9.9,"currency":"CNY"}',
            )
        page.route("**/api/price", handle)

        page.goto("/product/A1")
        # 页面读到的价格就是 Mock 的 9.9，而不是真实后端的值
        assert page.get_by_test_id("price").inner_text() == "¥9.9"
        browser.close()
```

**URL 模式支持 glob**：`**/api/price` 表示任意前缀的 `/api/price`。也可以用正则 `re.compile(r"\.json$")` 或 `string:` 精确匹配。

### 拦截特定请求并改内容（不阻断）

```python
# 放行真实请求，但给所有请求加上鉴权头
def add_auth(route, request):
    route.continue_(headers={**request.headers, "X-Test-Token": "xxxx"})

page.route("**/*", add_auth)
```

`continue_` 的 `headers` 参数是**覆盖/追加**，不是替换原 header——写错容易丢掉关键头（如 `Cookie`）。需要保留原 header 时务必 `**request.headers` 展开再追加。

### 模拟异常与弱网

```python
# 模拟接口 500
def fail_500(route):
    route.fulfill(status=500, body="internal error")

page.route("**/api/order", fail_500)

# 模拟网络中断（前端要能优雅降级）
page.route("**/api/feed", lambda r: r.abort())

# 模拟弱网：给每个请求加 2 秒延迟
def slow(route, request):
    import time
    time.sleep(2)
    route.continue_()
page.route("**/api/slow", slow)
```

模拟异常的价值在于**验证前端容错**——接口挂了页面是不是白屏？有没有兜底 UI？这是纯功能测试覆盖不到的。

### 用 HAR 文件录制并回放（最省事的「全量 Mock」）

```python
# 录制：先跑一遍真实流量，存成 HAR
context = browser.new_context(record_har_path="mock.har")
page.goto("/")
context.close()

# 回放：之后用 HAR 里录的真实响应喂给页面，完全不联网
context = browser.new_context(record_har_path="mock.har",
                              record_har_mode="replay")
```

HAR 模式适合「我就想让页面稳定地跑起来，不关心接口细节」的场景，比逐个写 handler 省事，但改了接口结构后 HAR 要重新录。

### 在 Page Object 里封装 Mock

```python
# pages/checkout.py
class CheckoutPage:
    def __init__(self, page):
        self.page = page

    def mock_payment_success(self):
        def handler(route):
            route.fulfill(status=200,
                          body='{"status":"paid","order_id":"MOCK123"}')
        self.page.route("**/api/pay", handler)
```

把 Mock 收敛到页面对象，用例层只调语义化方法，可读性和可维护性更好。详见 [[Page Object 模式与分层设计]]。

## 踩坑

1. **route 注册晚于请求发出**
   `page.route` 必须在 `page.goto` **之前**注册，否则首屏请求已经发出去了，拦不到。顺序永远是「先 route，后导航」。

2. **handler 里又触发了被拦截的请求**
   在 handler 里调用了会发同类请求的逻辑，会递归触发 route。注意 handler 内部不要间接触发同模式请求。

3. **用 `continue_` 改 header 丢掉了 Cookie**
   `continue_(headers=...)` 是直接覆盖，不展开原 header 会把 `Cookie` 弄丢，登录态失效。务必 `**request.headers` 先展开。

4. **glob 模式匹配面太宽**
   `**/*` 会拦截一切包括静态资源，可能把 JS/CSS 也拦了导致页面加载异常。尽量写精确的 `**/api/xxx`。

5. **abort 后前端没兜底，用例假失败**
   模拟异常前确认前端有降级逻辑。否则页面白屏，断言失败，但这其实是「前端没容错」的 bug，不是你 Mock 的锅——发现这种问题反而是 Mock 的价值。

6. **Mock 和真实行为不一致**
   Mock 返回的数据结构要和真实接口对齐，否则测的是「前端能解析你的假数据」，上线遇到真数据就崩。建议用 HAR 录制真实响应做基线。

7. **忘了 `route` 是 page 级作用域**
   route 注册在 page 上，新建 page/context 要重新注册。想全局拦截用 `context.route`。

8. **Selenium 用户想照搬**
   Selenium 没有 route 能力，别硬找等价 API。要么用 Mock Server，要么评估迁移 Playwright，见 [[Selenium 与 Playwright 选型对比]]。

## 面试怎么答

**Q：怎么在 UI 自动化里隔离外部接口依赖？**
A：用 Playwright 的话，`page.route()` 在网络层注册拦截器，页面发出的请求在被发送到网络前先交给我的 handler。handler 里可以 `fulfill` 直接返回造好的 Mock 响应、不发真实请求，`continue_` 放行并改 header，或者 `abort` 模拟断网和异常。它基于 CDP，是协议层拦截，不需要改业务代码，前端写死真实地址也能拦下来。常见用法是 Mock 掉支付、短信这些慢且不可控的接口提速和稳化；也可以 abort 模拟 500 来验证前端容错。Selenium 没有这个能力，得自己架 Mock Server，复杂度高很多。另外 HAR 录制回放适合「全量不联网」的场景，比逐个写 handler 省事。

**Q：route 和前端代码里的 mock 有什么区别？**
A：本质区别在于拦截层。前端代码里的 mock 是「在应用逻辑里把接口调用换成假函数」，它改了业务代码，而且只拦得到 JS 调用，绕过去就失效，测试代码侵入生产代码。Playwright 的 route 是「在浏览器网络层拦截」，请求压根没发出去就被换成 Mock 响应，业务代码一行都不用动，且无论前端怎么写都拦得住。所以它既能用于测试，也能安全用于演示、压测造数据，不污染生产逻辑。

**Q：你 Mock 返回的数据要注意什么？**
A：两点。一是结构要和真实接口对齐，Mock 只是替换值，不能把字段名、类型改得和线上不一致，否则测的是「前端能解析你的假数据」，上线遇真数据就崩，建议用 HAR 录真实响应当基线。二是 scope，route 注册在 page 上，新建 page 要重注册，全局拦截用 `context.route`；而且 route 必须在 `goto` 之前注册，不然首屏请求已经发出去拦不到。最后，Mock 是容错验证手段，发现前端在异常下白屏没兜底，那本身是真 bug，是 Mock 的价值不是 Mock 的错。

## 参考

- [Playwright · Network mocking](https://playwright.dev/python/docs/mock)
- [Playwright · APIRequestContext / route](https://playwright.dev/python/docs/api/class-route)
- 相关笔记：[[Selenium 与 Playwright 选型对比]]
- 相关笔记：[[Page Object 模式与分层设计]]
- 相关笔记：[[07-Web自动化测试]]
