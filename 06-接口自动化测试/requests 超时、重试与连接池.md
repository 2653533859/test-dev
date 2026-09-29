---
created: 2026-07-31
tags: [接口自动化测试/requests]
---

# requests 超时、重试与连接池

> 用例跑着跑着卡死、CI 任务超时被杀、偶发 `Connection aborted` —— 90% 是超时没设、重试策略没配、连接池被打满这三件事。

## 概念

### requests 默认没有超时

这是最反直觉、也是杀伤力最大的默认值：**`timeout` 不传就是永不超时**。服务端不回包、网络黑洞、TCP 连接建立后对端不响应，你的用例会一直挂着。

在 CI 里的表现是：任务卡在某一条用例上，直到 Jenkins 的全局超时把整个 job 杀掉，日志里啥也看不出来。

### timeout 的两个值

`timeout` 可以传单个数字，也可以传元组 `(connect_timeout, read_timeout)`：

- **connect timeout**：与服务端建立 TCP 连接（含 DNS 解析、TLS 握手）的最长等待。这个值应该**略大于三次握手的 RTT**，通常 3～5 秒足够；连不上一般是环境问题，等再久也没用。
- **read timeout**：**两次接收到数据之间的最长间隔**，不是「整个响应的总时长」。

第二点特别关键：`timeout=(3, 10)` 不代表「10 秒内必须下载完」。如果服务端每 9 秒吐一个字节，这个请求能跑一整天都不超时。**要限制总时长必须自己在外层控制**（如 `signal`、线程 + `join(timeout)`，或改用 `httpx` 的 `Timeout(total=...)`）。

### 三层重试的区别

| 层级 | 实现 | 重试对象 | 适用 |
|------|------|----------|------|
| 传输层 | `urllib3.Retry` + `HTTPAdapter` | 连接失败、读失败、指定状态码 | 网络抖动、502/503 |
| 用例层 | `pytest-rerunfailures`、`tenacity` | 整条用例 | 有状态的业务流 |
| 断言层 | 轮询等待（poll until） | 异步结果 | 最终一致性场景 |

**不要混用**。传输层重试对「幂等的读接口」最安全；对创建订单这种非幂等接口，重试会造成重复下单，必须关掉。

### 连接池是 Session 的另一半价值

`HTTPAdapter` 默认 `pool_connections=10`（缓存 10 个不同 host 的连接池）、`pool_maxsize=10`（每个池最多 10 条连接）。并发跑用例时如果线程数 > `pool_maxsize`，多出来的请求要么排队，要么直接丢弃连接并打出警告：

```text
WARNING urllib3.connectionpool: Connection pool is full, discarding connection: api.example.com
```

这个 warning 不会让用例失败，但会导致连接反复建立/销毁，跑得越来越慢。

## 用法

### 全局强制超时：给封装层兜底

最好的做法不是「记得每次传 timeout」，而是**让忘记传变得不可能**：

```python
import requests

class TimeoutSession(requests.Session):
    """所有请求默认带超时，用例层可以覆盖。"""

    def __init__(self, timeout=(3.05, 10)):
        super().__init__()
        self._default_timeout = timeout

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", self._default_timeout)
        return super().request(method, url, **kwargs)

s = TimeoutSession()
s.get("https://httpbin.org/delay/20")   # 10 秒后抛 ReadTimeout，不会永久挂起
```

> connect timeout 常写成 `3.05` 而不是 `3`：TCP 重传的初始退避是 3 的倍数，稍大一点能避免恰好卡在重传边界上，这是 requests 文档里的建议。

### 配置传输层重试

```python
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

retry = Retry(
    total=3,                       # 总重试次数上限
    connect=3,                     # 连接失败重试
    read=2,                        # 读失败重试
    backoff_factor=0.5,            # 退避：0.5s, 1s, 2s（指数）
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "HEAD", "OPTIONS"],   # 只重试幂等方法
    raise_on_status=False,         # 重试耗尽后返回响应而不是抛异常
)

adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
session = requests.Session()
session.mount("http://", adapter)
session.mount("https://", adapter)

r = session.get("https://httpbin.org/status/503", timeout=(3, 10))
print(r.status_code)   # 503（重试 3 次后仍失败）
```

几个参数的实际含义：

- `backoff_factor=0.5` 的等待序列是 `0.5 * (2 ** (n-1))`，即 0.5s → 1s → 2s。设成 0 就是立即重试（不推荐，服务端还没缓过来）。
- `allowed_methods` 在旧版 urllib3 里叫 `method_whitelist`，默认**不含 POST**，这是刻意为之：POST 通常非幂等。
- `raise_on_status=False` 很重要——接口测试要断言 503 本身时，不希望它变成异常。

### 只对特定接口关闭重试

创建订单这类接口，重试 = 重复下单：

```python
no_retry_adapter = HTTPAdapter(max_retries=0)
session.mount("https://api.example.com/api/orders", no_retry_adapter)
```

`mount` 按前缀最长匹配，所以更具体的路径会覆盖 `https://`。

### 用 tenacity 做业务级重试

传输层重试搞不定「返回 200 但业务码是处理中」的场景，这时用 `tenacity`：

```python
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_result

def is_processing(resp):
    return resp.json().get("data", {}).get("status") == "PROCESSING"

@retry(stop=stop_after_attempt(10),
       wait=wait_fixed(2),
       retry=retry_if_result(is_processing))
def query_order(client, order_id):
    return client.get(f"/api/orders/{order_id}")

r = query_order(client, 100231)
assert r.json()["data"]["status"] == "PAID"
```

这就是「轮询等待最终一致性」的标准写法，比 `time.sleep(20)` 稳定得多也快得多。

### 排查连接池告警

```python
import logging
logging.basicConfig(level=logging.DEBUG)
# urllib3 会打印 "Starting new HTTPS connection (1): ..." 
# 复用成功时不会打印这一行，可以据此确认连接池是否生效
```

并发场景把池调大到线程数：

```python
from concurrent.futures import ThreadPoolExecutor

WORKERS = 32
adapter = HTTPAdapter(pool_connections=WORKERS, pool_maxsize=WORKERS)
session.mount("https://", adapter)

with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    list(ex.map(lambda i: session.get(f"{base}/api/items/{i}", timeout=(3, 10)),
                range(200)))
```

> `requests.Session` 本身**不是严格线程安全**的（Cookie 更新有竞态）。多线程共用一个 Session 做只读 GET 通常没问题，但涉及登录态变更时应该每线程一个 Session，或加锁。参考 [[Python 并发编程]]。

## 踩坑

1. **忘记 timeout，CI 卡死**：最常见也最致命。解决方案是封装层兜底（上面的 `TimeoutSession`），而不是靠 code review。
2. **以为 read timeout 是总耗时**：它是「两次数据之间的间隔」。下载大文件时不要因为怕超时就把 read timeout 设得极大，那样反而失去保护；应该设合理的间隔值 + 外层总时长控制。
3. **对 POST 开启了重试，造出重复数据**：`Retry` 的 `allowed_methods` 默认不含 POST 是有道理的，不要随手加进去。确实要重试的，先确认接口幂等（有幂等键 / idempotency-key）。
4. **`Retry` 配了但没生效**：多半是 `session.mount()` 只挂了 `"http://"`，请求走的却是 https；或者用了 `requests.get()` 裸函数而不是这个 session。
5. **`raise_on_status` 默认行为变化**：不同 urllib3 版本默认值不同，重试耗尽后有时抛 `MaxRetryError`（被 requests 包成 `RetryError`），有时返回响应。显式写 `raise_on_status=False` 更可控。
6. **`Connection pool is full` 只是 warning，被忽略**：性能悄悄退化。CI 日志里 grep 一下这行，有就调大 `pool_maxsize`。
7. **`ConnectionResetError` / `Connection aborted`**：服务端提前关闭了 keep-alive 连接，而客户端还在复用。常见于服务端 `keepalive_timeout` 小于客户端复用间隔。处理方式：开启 connect 重试，或在长间隔场景显式 `Connection: close`。
8. **重试掩盖了真实缺陷**：接口本来就有 5% 概率 500，配上重试后用例全绿，问题被藏起来了。**重试要打日志并统计**，重试率超阈值应该单独报出来，而不是静默吞掉。

## 面试怎么答

**Q：requests 的 timeout 参数怎么设，为什么要用元组？**

A：元组是 `(connect_timeout, read_timeout)`。connect 是建立 TCP 连接（含 DNS 和 TLS 握手）的上限，一般 3～5 秒，连不上通常是环境问题；read 是**两次收到数据之间的最大间隔**，不是响应总时长——这点很多人搞错，服务端慢慢吐数据是不会触发 read timeout 的。另外 requests 默认不设超时，等于永久等待，所以我在框架封装层重写了 `Session.request`，用 `setdefault` 强制兜一个默认超时，防止有人忘了传导致 CI 卡死。

**Q：接口偶发失败，你会加重试吗？**

A：分情况，而且会分层。传输层用 `urllib3.Retry` 挂在 `HTTPAdapter` 上，只对 GET/HEAD 这类幂等方法、只对 429/5xx 重试，配指数退避；创建类的非幂等接口坚决不加，否则会造出重复数据。业务上的「异步处理中」用 `tenacity` 做轮询等待，而不是 `sleep` 死等。最重要的一条是：**重试必须打日志和统计重试率**，否则它会把真实的稳定性问题掩盖掉——本来该暴露的 5% 失败率被重试洗成 100% 通过，那自动化就失去意义了。

**Q：几百条用例跑得越来越慢，怎么排查？**

A：先看是不是每条用例都新建了 Session——没有连接复用，每次都要重新 TCP + TLS 握手，开销很大，应该用 fixture 复用同一个 Session。其次看日志里有没有 `Connection pool is full, discarding connection`，有的话说明并发数超过了 `pool_maxsize`，连接在反复建销毁，把 `HTTPAdapter(pool_maxsize=并发数)` 调上去。再看 `stream=True` 的响应有没有正常关闭，没关会一直占着连接不归还。最后才是看服务端本身是否有性能衰减。

## 参考

- [requests 官方文档 - Timeouts](https://requests.readthedocs.io/en/latest/user/advanced/#timeouts)
- [urllib3 Retry API](https://urllib3.readthedocs.io/en/stable/reference/urllib3.util.html#urllib3.util.Retry)
- [tenacity 文档](https://tenacity.readthedocs.io/en/latest/)
- 相关笔记：[[requests 请求与响应对象]]、[[requests Session 会话保持与 Cookie]]、[[Python 并发编程]]
