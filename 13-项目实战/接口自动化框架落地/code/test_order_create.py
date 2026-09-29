"""用例层示例：只做「调业务方法 + 断言」，不出现 url / header / json 拼装。

判断分层是否到位的标准：接口新增一个必填字段时，本文件一行都不用改。
"""

import pytest
import yaml
from pathlib import Path

from assertions import assert_response, assert_status, wait_until

CASES = yaml.safe_load(Path("create_order.yaml").read_text(encoding="utf-8"))


def case_ids(cases):
    """用中文用例名做 ID，报告里可读。重名直接抛错，避免 pytest 自动加数字后缀。"""
    names = [c["name"] for c in cases]
    assert len(names) == len(set(names)), f"用例名重复：{names}"
    return names


@pytest.mark.smoke
@pytest.mark.parametrize("case", CASES, ids=case_ids(CASES))
def test_create_order(case, api_order, ctx, sku):
    """数据驱动主体：渲染变量 → 发请求 → 三层断言 → 提取回写。"""
    ctx.set("sku_id", sku)

    payload = ctx.render(case["payload"])
    resp = api_order.create(payload)

    assert_response(resp, case["expect"])
    ctx.extract(resp, case.get("extract", {}))


@pytest.mark.p0
def test_下单后异步落库正确(api_order, sku, db):
    """接口返回成功不代表数据写对了，异步场景必须查库确认。"""
    resp = api_order.create({"skuId": sku, "quantity": 2})
    assert_status(resp, 200)
    order_no = resp.json()["data"]["orderId"]

    # 轮询而不是 sleep(3)：环境快时不白等，环境慢时不误报
    row = wait_until(
        lambda: db.query_one(
            "SELECT status, pay_amount FROM t_order WHERE order_no = %s", order_no
        ),
        timeout=10,
        interval=0.5,
    )
    assert row["status"] == 0, f"订单状态应为待支付，实际 {row['status']}"
    assert str(row["pay_amount"]) == "198.00"


@pytest.mark.p0
def test_未登录访问订单详情应返回401(guest_client):
    """用游客态客户端，不能复用鉴权态 Session，否则 cookie 污染会造成假阳性。"""
    resp = guest_client.get("/api/v1/orders/ORD20260731001")
    assert_status(resp, 401)
