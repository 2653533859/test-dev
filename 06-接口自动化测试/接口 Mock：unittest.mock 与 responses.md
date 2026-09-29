---
created: 2026-07-31
tags: [接口自动化测试/Mock]
---

# 接口 Mock：unittest.mock 与 responses

> 上游服务没开发完、第三方沙箱不稳定、「余额不足」这种分支根本造不出来——Mock 不是为了偷懒，是为了让本来测不了的场景变得可测。

![[assets/mock-decouple-upstream.svg]]
*图示：同一条用例的三种上游替换方式——进程内打桩最快，独立 Mock 服务最真实，真实上游用于少量集成回归。*

## 概念

### 什么时候该 Mock

| 情况 | 该 Mock 吗 |
|------|------------|
| 上游接口还没开发完 | 是 |
| 第三方服务（支付、短信、地图）有调用配额或费用 | 是 |
| 需要构造上游超时、500、脏数据 | 是（几乎只能靠 Mock） |
| 上游偶发不稳定，导致用例假红 | 是，但要另外有真实集成用例兜底 |
| 你要测的就是「和上游的集成是否正确」 | **否**，Mock 了就没意义了 |

核心原则：**Mock 掉的是「不是本次被测对象」的部分**。测支付回调处理逻辑时，Mock 掉支付网关是对的；测「我们和支付网关能不能通」时，Mock 就把测试目标本身消掉了。

### 三个层次的 Mock

1. **`unittest.mock`**：替换 Python 对象/函数。粒度最细，也最"假"——连 requests 都没走
2. **`responses` / `requests-mock`**：在 requests 的 `HTTPAdapter` 层拦截。走了 requests 的完整流程（参数编码、header 处理），只是最后不真的发包
3. **独立 Mock Server**：真过网络。见 [[独立 Mock 服务与契约测试]]

接口自动化里**首选第 2 种**：它保留了 requests 的行为（能验证你的参数编码逻辑对不对），又不依赖网络。

### mock 的核心概念

```python
from unittest.mock import Mock, MagicMock, patch
```

- `Mock()`：万能替身，访问任何属性/调用任何方法都返回新的 Mock
- `MagicMock()`：Mock 的增强版，额外支持魔术方法（`__len__`、`__iter__`、`__getitem__`）
- `patch()`：在指定作用域内**临时替换**某个对象，退出时自动还原
- `return_value`：调用后返回什么
- `side_effect`：调用时的副作用——可以是异常（抛出）、列表（依次返回）、函数（动态计算）

**`patch` 最大的坑是「patch 的位置」**：要 patch「使用处」的名字，不是「定义处」。后面详述。

## 用法

### responses：拦截 requests 请求

```bash
pip install responses
```

```python
import responses
import requests


@responses.activate
def test_get_user_profile():
    responses.add(
        responses.GET,
        "https://api.example.com/api/v1/user/1001",
        json={"code": 0, "data": {"id": 1001, "name": "张三", "vip": True}},
        status=200,
    )

    r = requests.get("https://api.example.com/api/v1/user/1001", timeout=5)
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "张三"

    # 验证请求确实发出，且只发了一次
    assert len(responses.calls) == 1
    assert responses.calls[0].request.headers["Accept"] == "*/*"
```

`responses.calls` 能拿到所有被拦截的请求，**验证「我发出去的请求对不对」和验证「我怎么处理响应」同样重要**。

### 构造异常场景

这是 Mock 最不可替代的价值：

```python
import requests
import responses


@responses.activate
def test_upstream_timeout_handled():
    """上游超时时，我们的服务应降级返回默认值而不是 500。"""
    responses.add(
        responses.GET,
        "https://api.upstream.com/rate",
        body=requests.exceptions.ConnectTimeout("connect timeout"),
    )
    result = get_exchange_rate_with_fallback()      # 被测函数
    assert result == DEFAULT_RATE, "上游超时未走降级逻辑"


@responses.activate
def test_upstream_500_retried():
    """上游 500 时应该重试，第二次成功。"""
    responses.add(responses.GET, "https://api.upstream.com/rate", status=500)
    responses.add(responses.GET, "https://api.upstream.com/rate",
                  json={"rate": 7.2}, status=200)
    assert get_exchange_rate_with_fallback() == 7.2
    assert len(responses.calls) == 2, "没有触发重试"


@responses.activate
def test_upstream_returns_garbage():
    """上游返回非 JSON（比如网关的 HTML 错误页），不能让我们的服务崩。"""
    responses.add(responses.GET, "https://api.upstream.com/rate",
                  body="<html>502 Bad Gateway</html>",
                  content_type="text/html", status=502)
    assert get_exchange_rate_with_fallback() == DEFAULT_RATE
```

**同一 URL 注册多个响应会按顺序消费**，这是模拟「第一次失败第二次成功」的标准写法。

### 动态响应：根据请求内容返回不同结果

```python
import json
import responses


@responses.activate
def test_order_query_by_status():
    def callback(request):
        params = dict(x.split("=") for x in (request.url.split("?")[-1]).split("&"))
        status = params.get("status", "ALL")
        all_orders = [
            {"order_id": 1001, "status": "PAID"},
            {"order_id": 1002, "status": "UNPAID"},
        ]
        data = [o for o in all_orders if status in ("ALL", o["status"])]
        return (200, {"Content-Type": "application/json"},
                json.dumps({"code": 0, "data": {"list": data, "total": len(data)}}))

    responses.add_callback(
        responses.GET, "https://api.example.com/api/v1/orders",
        callback=callback, content_type="application/json",
    )

    r = requests.get("https://api.example.com/api/v1/orders",
                     params={"status": "PAID"}, timeout=5)
    assert r.json()["data"]["total"] == 1
```

### 校验请求体：Mock 也要断言「发出去的对不对」

```python
from responses import matchers


@responses.activate
def test_create_order_sends_correct_body():
    responses.add(
        responses.POST,
        "https://api.example.com/api/v1/orders",
        json={"code": 0, "data": {"order_id": 1001}},
        status=200,
        match=[
            matchers.json_params_matcher({"sku_id": "SKU001", "quantity": 2}),
            matchers.header_matcher({"Content-Type": "application/json"}),
        ],
    )
    create_order("SKU001", 2)       # 被测的封装函数
    # 请求体不匹配时，responses 会抛 ConnectionError 提示没有注册的 mock 匹配
```

`match` 参数让 Mock 变成了双向校验：不仅返回假数据，还断言了你的请求构造逻辑。

### unittest.mock：替换 Python 层的对象

适合被测对象不是 HTTP 调用，或者你想跳过整个客户端：

```python
from unittest.mock import patch, MagicMock


def test_send_sms_on_order_paid():
    """订单支付成功后应调用短信服务，且参数正确。"""
    with patch("myapp.services.order.sms_client") as mock_sms:
        mock_sms.send.return_value = {"code": 0, "msg_id": "M001"}

        handle_order_paid(order_id=1001, phone="13800138000")

        mock_sms.send.assert_called_once()
        args, kwargs = mock_sms.send.call_args
        assert kwargs["phone"] == "13800138000"
        assert "支付成功" in kwargs["content"]
```

常用断言方法：

```python
mock_obj.assert_called()                 # 至少调用过一次
mock_obj.assert_called_once()            # 恰好一次
mock_obj.assert_called_with(1, x=2)      # 最后一次调用的参数
mock_obj.assert_called_once_with(1, x=2) # 恰好一次且参数匹配
mock_obj.assert_not_called()             # 从未调用
mock_obj.call_count                      # 调用次数
mock_obj.call_args_list                  # 所有调用的参数列表
```

### patch 的位置：最容易搞错的地方

```python
# myapp/services/order.py
from myapp.clients.sms import send_sms      # ← 导入时就绑定了名字

def handle_paid(order_id, phone):
    send_sms(phone, "支付成功")
```

```python
# 错误：patch 定义处，不生效
with patch("myapp.clients.sms.send_sms") as m:
    handle_paid(1001, "138...")
    m.assert_called()        # 失败！order 模块里的 send_sms 还是原来那个

# 正确：patch 使用处
with patch("myapp.services.order.send_sms") as m:
    handle_paid(1001, "138...")
    m.assert_called()        # 通过
```

**原因**：`from x import y` 在导入时就把 `y` 绑定到了当前模块的命名空间。patch 定义处只改了原模块的属性，使用处的引用还指向旧对象。记忆口诀：**patch where it's used, not where it's defined**。

如果用 `import myapp.clients.sms` + `sms.send_sms(...)` 的写法，patch 定义处就有效——因为每次调用都通过模块属性查找。参考 [[Python 模块与包的使用]]。

### side_effect 的三种用法

```python
from unittest.mock import Mock

# 1) 抛异常
m = Mock(side_effect=TimeoutError("上游超时"))
# m() 会抛 TimeoutError

# 2) 依次返回（模拟重试场景）
m = Mock(side_effect=[{"code": 500}, {"code": 500}, {"code": 0}])
# 前两次返回 500，第三次成功；调用第四次抛 StopIteration

# 3) 动态计算
def fake_query(order_id):
    return {"order_id": order_id, "status": "PAID" if order_id % 2 else "UNPAID"}

m = Mock(side_effect=fake_query)
print(m(1001))   # {'order_id': 1001, 'status': 'PAID'}
```

### pytest fixture 化

```python
import pytest
import responses


@pytest.fixture
def mock_upstream():
    with responses.RequestsMock(assert_all_requests_are_fired=True) as rsps:
        yield rsps


def test_something(mock_upstream):
    mock_upstream.add(responses.GET, "https://api.upstream.com/rate",
                      json={"rate": 7.2})
    assert get_rate() == 7.2
    # 退出 fixture 时会检查所有注册的 mock 都被真的调用过
```

`assert_all_requests_are_fired=True` 很有用：能发现「你注册了 Mock 但代码根本没调那个接口」的情况——通常意味着代码逻辑走错了分支。

## 踩坑

1. **patch 错位置**：`patch("定义模块.函数名")` 对 `from x import y` 的使用方式无效。patch 使用处。
2. **`@responses.activate` 忘了加**：请求真的发出去了，用例在有网时通过、CI 里没网就挂，或者更糟——真的往测试环境发了创建订单请求。
3. **Mock 了但断言不到位**：只 mock 返回值不校验请求参数，等于只测了「我能处理这个响应」，没测「我发的请求对不对」。用 `match=[...]` 或 `responses.calls[0].request` 补上。
4. **Mock 覆盖了真实集成测试**：所有上游都 Mock 了，跑一万条用例全绿，上线一联调全崩。**Mock 层用例必须配合少量真实集成用例**。
5. **URL 匹配不上**：`responses.add` 默认精确匹配 URL（含 query）。带动态参数时用正则或 `match_querystring=False`：

   ```python
   import re
   responses.add(responses.GET, re.compile(r"https://api\.example\.com/api/v1/orders/\d+"),
                 json={"code": 0})
   ```

6. **Mock 数据和真实响应结构脱节**：上游改了字段名，Mock 里还是老的，用例永远绿。这就是契约测试要解决的问题，见 [[独立 Mock 服务与契约测试]]。
7. **`Mock()` 的属性访问永远返回 Mock**：`mock.json()["data"]["id"]` 不会报错，返回的是 Mock 对象，断言 `== 1001` 才失败，且报错信息看不懂。用 `spec=` 限制：

   ```python
   from unittest.mock import Mock
   import requests
   m = Mock(spec=requests.Response)      # 访问不存在的属性会 AttributeError
   ```

8. **`side_effect` 列表用尽抛 `StopIteration`**：在生成器上下文里这个异常会被吞掉变成奇怪的行为。注册的响应数要够。
9. **patch 没有还原**：用 `patch` 做装饰器或上下文管理器会自动还原；手动 `mock.patch(...).start()` 忘了 `stop()`，污染后续用例。
10. **Mock 掉了本该被测的东西**：测「支付回调签名校验」时把签名校验函数 Mock 了，用例通过但功能是坏的。想清楚被测对象的边界在哪。

## 面试怎么答

**Q：上游服务不稳定或者还没开��完，你的用例怎么跑？**

A：分层处理。最常用的是 `responses` 库，它在 requests 的 `HTTPAdapter` 层做拦截——好处是我的请求仍然走完了 requests 的完整流程，参数编码、header 处理这些逻辑都被真实执行了，只是最后不真的发包。这样既快又能验证请求构造是否正确。如果被测的不是 HTTP 调用，就用 `unittest.mock.patch` 替换 Python 对象。如果需要多方共用（前端联调、其他团队），就搭独立的 Mock Server，改 base_url 指过去。

但我会强调一点：**Mock 不能全覆盖**。Mock 掉的是「不是本次被测对象」的部分，如果我要测的就是「和上游的集成对不对」，Mock 了测试目标就消失了。所以 Mock 层用例之外，必须保留一小组打真实上游的集成用例，放在冒烟或每日回归里跑。

**Q：`unittest.mock` 的 `patch` 有什么坑？**

A：最大的坑是 patch 的位置。要 patch「使用处」的名字而不是「定义处」。因为 `from x import y` 在导入时就把 `y` 绑定到了使用方模块的命名空间，你去 patch 定义模块的属性，使用方持有的引用还是旧对象，patch 完全不生效，而且不报错——测试照常通过，你以为 Mock 生效了。口诀是 patch where it's used。另一个坑是裸 `Mock()` 访问任何属性都返回新的 Mock 不会报错，`mock.json()["data"]["id"]` 一路通过，直到断言时才失败，报错信息还很难懂，所以我会用 `Mock(spec=SomeClass)` 限制可访问的属性。

**Q：Mock 用多了会不会让测试失去意义？**

A：会，这是真实存在的风险，有两个具体表现。一是**契约漂移**：Mock 里写死的是「我以为上游长这样」，上游真改了字段名，Mock 用例不会红，线上会炸。二是**测试目标被 Mock 掉**：比如测支付回调时顺手把签名校验也 Mock 了，用例全绿但功能是坏的。我的应对是三条：第一，Mock 的边界要清晰，只 Mock 外部依赖，不 Mock 被测逻辑；第二，Mock 时不只校验响应处理，还要用 `match` 断言发出去的请求体和 header 对不对；第三，用契约测试守住结构——上游产出契约文件，双方在 CI 里用同一份契约校验，任一方违约立刻失败，这样 Mock 数据和真实接口��不会静默脱节。

## 参考

- [responses 文档](https://github.com/getsentry/responses)
- [unittest.mock 官方文档](https://docs.python.org/zh-cn/3/library/unittest.mock.html)
- [Where to patch](https://docs.python.org/zh-cn/3/library/unittest.mock.html#where-to-patch)
- 相关笔记：[[独立 Mock 服务与契约测试]]、[[requests 请求与响应对象]]、[[Python 模块与包的使用]]
