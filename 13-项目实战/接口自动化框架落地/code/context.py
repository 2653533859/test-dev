"""用例级上下文变量池：变量存取、模板渲染、响应字段提取。

设计要点：
1. 绝不设成 session 级，并行时变量互相覆盖会出诡异问题。
2. ${var} 渲染保留原始类型：整串是占位符时返回原值（数字、None、bool），
   部分拼接时统一转字符串。
"""

import re
from typing import Any

_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


class Context:
    """用例级上下文：每条用例独立一份，互不污染。"""

    def __init__(self):
        self._store: dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        self._store[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._store.get(key, default)

    def render(self, obj: Any) -> Any:
        """递归渲染 ${var} 占位符。

        整串是单个占位符时返回原始类型（数字、None、bool），
        否则做字符串拼接。
        """
        if isinstance(obj, dict):
            return {k: self.render(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.render(v) for v in obj]
        if isinstance(obj, str):
            return self._render_str(obj)
        return obj

    def _render_str(self, s: str) -> Any:
        # 整串是单个 ${var}，返回原始类型
        match = _VAR_PATTERN.fullmatch(s.strip())
        if match:
            return self._store.get(match.group(1), s)

        # 部分拼接，统一转字符串
        def repl(m: "re.Match[str]") -> str:
            val = self._store.get(m.group(1))
            return "" if val is None else str(val)

        return _VAR_PATTERN.sub(repl, s)

    def extract(self, resp, mapping: dict) -> None:
        """从响应里按 JSONPath 提取值回写到上下文，供后续串联用例使用。"""
        if not mapping:
            return
        from jsonpath_ng import parse as jsonpath_parse

        body = resp.json()
        for key, expr in mapping.items():
            matches = jsonpath_parse(expr).find(body)
            if matches:
                self._store[key] = matches[0].value
