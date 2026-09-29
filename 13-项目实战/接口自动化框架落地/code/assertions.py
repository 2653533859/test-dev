"""三层断言：协议层（状态码）→ 结构层（JSON Schema）→ 业务层（具体字段）。

设计要点见笔记《三层断言与响应校验实现》。
核心原则：只校验这条用例关心的字段，结构稳定性交给 Schema 兜底，
避免后端新增字段导致大面积误报。
"""

import json
import time
from decimal import Decimal
from pathlib import Path

import jsonschema
from jsonpath_ng import parse as jsonpath_parse

SCHEMA_DIR = Path(__file__).parent / "schemas"


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.json").read_text(encoding="utf-8"))


def assert_status(resp, expected: int = 200) -> None:
    """一层：协议层。失败信息带上 URL 和响应体，省一次手工复现。"""
    assert resp.status_code == expected, (
        f"状态码不符：期望 {expected}，实际 {resp.status_code}\n"
        f"URL: {resp.request.method} {resp.url}\n"
        f"响应: {resp.text[:500]}"
    )


def assert_schema(body: dict, schema_name: str) -> None:
    """二层：结构层。additionalProperties 保持 true，允许新增字段。"""
    try:
        jsonschema.validate(instance=body, schema=load_schema(schema_name))
    except jsonschema.ValidationError as e:
        path = ".".join(str(p) for p in e.absolute_path) or "<root>"
        raise AssertionError(
            f"响应结构校验失败 [{schema_name}]\n路径: {path}\n原因: {e.message}"
        ) from None  # 屏蔽 jsonschema 冗长的内部调用栈


def _equal(got, want) -> bool:
    """金额类比较绕开浮点误差。注意必须经过 str，Decimal(0.1) 本身就带误差。"""
    if isinstance(want, float) or isinstance(got, float):
        return Decimal(str(got)) == Decimal(str(want))
    return got == want


def assert_fields(body: dict, expected: dict) -> None:
    """三层：业务层。一次收集所有差异再抛，避免改一个跑一次。"""
    errors = []
    for path, want in expected.items():
        expr = path if path.startswith("$") else f"$.{path}"
        matches = jsonpath_parse(expr).find(body)
        if not matches:
            errors.append(f"  {path}: 字段不存在")
            continue
        got = matches[0].value
        if not _equal(got, want):
            errors.append(f"  {path}: 期望 {want!r}，实际 {got!r}")

    if errors:
        raise AssertionError("业务字段校验失败：\n" + "\n".join(errors))


def assert_response(resp, expect: dict) -> None:
    """统一入口：按 YAML 里 expect 段的配置逐层校验。"""
    assert_status(resp, expect.get("status_code", 200))
    body = resp.json()
    if "schema" in expect:
        assert_schema(body, expect["schema"])
    if "fields" in expect:
        assert_fields(body, expect["fields"])


def wait_until(fn, timeout: float = 10, interval: float = 0.5):
    """轮询直到 fn 返回真值。用于异步落库校验，替代硬编码 sleep。

    sleep 的问题是双向的：环境快时白等，环境慢时仍然失败。
    """
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"等待超时（{timeout}s），最后一次结果：{last}")
