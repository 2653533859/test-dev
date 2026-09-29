"""最小冒烟用例：用于本地验证 CI 流水线脚本能正常解析 JUnit XML。

跑通后：
- gate.py 能解析出通过率，决定门禁是否通过。
- notify.py 能提取失败用例名和错误摘要。

不要在这里写业务断言——这是流水线自检用例，业务用例另放。
"""

import pytest


@pytest.mark.smoke
def test_addition():
    assert 1 + 1 == 2


@pytest.mark.smoke
def test_string_concat():
    assert "hello" + " " + "world" == "hello world"


@pytest.mark.smoke
def test_list_operations():
    items = [1, 2, 3]
    assert len(items) == 3
    assert sum(items) == 6
