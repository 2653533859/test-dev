"""HttpClient 封装：Session 复用、强制超时、幂等重试、统一日志与鉴权注入。

设计要点见笔记《Token 鉴权与会话管理实现》。
"""

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# 连接超时 5s、读取超时 15s。绝不允许无超时请求，否则测试环境 hang 住会拖垮整个构建。
DEFAULT_TIMEOUT = (5, 15)


class HttpClient:
    """一个环境一个实例。鉴权信息挂在 Session 默认 header 上，用例层无感知。"""

    def __init__(self, base_url: str, token: str | None = None, timeout=DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

        # 只对幂等方法重试。POST 若自动重试，网络抖动时会造出两笔订单。
        retry = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=[502, 503, 504],
            allowed_methods=["GET", "HEAD", "OPTIONS", "PUT", "DELETE"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=20)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        url = path if path.startswith("http") else f"{self.base_url}{path}"

        resp = self.session.request(method, url, **kwargs)

        logger.info(
            "%s %s -> %s (%.0fms)",
            method, url, resp.status_code, resp.elapsed.total_seconds() * 1000,
        )
        if resp.status_code >= 400:
            # 失败时把响应体打出来，省一次手工复现
            logger.warning("响应体：%s", resp.text[:1000])
        return resp

    def get(self, path: str, **kwargs) -> requests.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> requests.Response:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> requests.Response:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs) -> requests.Response:
        return self.request("DELETE", path, **kwargs)


class OrderApi:
    """接口对象层示例：一个接口一个方法，收敛 url 与必填参数。

    接口新增必填字段时只改这里，用例层不用动。
    """

    def __init__(self, client: HttpClient):
        self.client = client

    def create(self, payload: dict) -> requests.Response:
        return self.client.post("/api/v1/orders", json=payload)

    def detail(self, order_id: str) -> requests.Response:
        return self.client.get(f"/api/v1/orders/{order_id}")

    def cancel(self, order_id: str, reason: str = "自动化测试取消") -> requests.Response:
        return self.client.post(f"/api/v1/orders/{order_id}/cancel", json={"reason": reason})
