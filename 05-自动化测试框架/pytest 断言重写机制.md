---
created: 2026-07-31
tags: [自动化测试框架/pytest]
---

# pytest 断言重写机制

![[assets/assert-rewrite.svg]]
*图示：pytest 通过自定义 import hook 在导入测试模块时改写 AST，把断言表达式的中间值绑到临时变量上，失败时才能打印出 `assert 5 == 6 + where 5 = calc(2, 3)` 这种带上下文的信息。*

> 为什么 pytest 用一句原生 `assert` 就能给出比 `assertEqual` 更详细的失败信息——以及为什么你封装的工具类里 `assert` 却没有这个待遇。

## 概念

### 原生 assert 的信息量为零

Python 的 `assert` 语句等价于：

```python
if not expr:
    raise AssertionError(msg_if_any)
```

失败时 traceback 只有一行 `AssertionError`，**不会告诉你 expr 里各个子表达式的值**：

```python
def calc(a, b):
    return a + b

assert calc(2, 3) == 6
# AssertionError        ← 就这样，一无所知
```

这正是 unittest 提供 `assertEqual` / `assertIn` / `assertAlmostEqual` 一整套方法的原因——它们在方法内部拿得到 `a` 和 `b`，可以自己拼出详细的失败信息。代价是你必须记住几十个方法名，还要区分 `assertEqual` 和 `assertIs`、`assertCountEqual` 这种命名坑。

pytest 的选择是：**保留原生 `assert`，改造编译过程**。

### 断言重写：在 import 时改 AST

pytest 启动时会向 `sys.meta_path` 注册一个自定义的导入器 `AssertionRewritingHook`。当一个「需要重写的模块」被 import 时：

1. hook 拦截该模块的加载；
2. 读源码 → `ast.parse()` 得到语法树；
3. 遍历语法树，把每个 `ast.Assert` 节点**替换**成一段展开代码：把断言表达式的每个子表达式求值后绑到 `@py_assert0`、`@py_assert1` 这类临时变量上，再判断结果，失败时用这些临时变量拼出解释文本；
4. 编译改写后的 AST 得到 code object，执行它；
5. 把结果缓存成 `.pyc` 写进 `__pycache__`（带一个特殊标记，避免和普通 pyc 混淆）。

用一段简化伪代码感受改写效果：

```python
# 你写的
assert calc(2, 3) == 6

# pytest 实际执行的（大意，真实生成的代码更啰嗦）
@py_assert0 = calc(2, 3)
@py_assert2 = 6
@py_assert1 = @py_assert0 == @py_assert2
if not @py_assert1:
    @py_format = _format_explanation(
        "assert %(py0)s == %(py2)s" % {...},
        left=@py_assert0, right=@py_assert2, call="calc(2, 3)"
    )
    raise AssertionError(_pytest.assertion.util.format_explanation(@py_format))
```

于是失败输出变成：

```text
E       assert 5 == 6
E        +  where 5 = calc(2, 3)
```

**关键点：中间值必须在断言执行时就被保存下来**。因为异常抛出后，那些临时对象可能已经不可达了。这就是为什么必须改写代码，而不能事后从 traceback 里反推。

### 哪些模块会被重写

这是最容易被忽视、也是最实用的一点。pytest **只重写三类模块**：

1. **测试模块本身**（符合 `python_files` 命名约定的文件）；
2. **`conftest.py`**；
3. **通过 setuptools entry point 注册的 pytest 插件**（如 `pytest-django`）。

**不会重写**：你自己写的 `utils/`、`core/`、`pages/` 等普通业务/工具模块。

后果非常具体：

```python
# core/checker.py  ← 不会被重写
def check_response(resp, expected_code):
    assert resp.json()["code"] == expected_code    # 失败信息只有 AssertionError


# tests/test_login.py  ← 会被重写
def test_login(api):
    resp = api.login("admin", "wrong")
    check_response(resp, 0)         # 挂了只看到一行 AssertionError，看不到实际 code
```

解法是显式注册：

```python
# conftest.py 的最顶部（必须在 import core.checker 之前）
import pytest

pytest.register_assert_rewrite("core.checker", "core.assertions")

from core.checker import check_response      # 现在它会被重写了  # noqa: E402
```

**顺序是硬要求**：`register_assert_rewrite` 只对「尚未被 import 的模块」生效。模块一旦进了 `sys.modules`，再注册也没用，而且 pytest 只会给一条 warning：

```text
PytestAssertRewriteWarning: Module already imported so cannot be rewritten: core.checker
```

### 断言解释的几种典型输出

重写机制对不同类型的比较有专门的「解释器」，输出质量差别很大：

```python
def test_diff_types():
    # 字符串：给出逐字符差异位置
    assert "hello world" == "hello werld"
    # E   AssertionError: assert 'hello world' == 'hello werld'
    # E     - hello werld
    # E     ?         ^
    # E     + hello world
    # E     ?         ^

    # 列表：给出第一个不同的索引
    assert [1, 2, 3] == [1, 2, 4]
    # E     At index 2 diff: 3 != 4

    # 字典：给出差异的 key
    assert {"a": 1, "b": 2} == {"a": 1, "b": 3}
    # E     Differing items:
    # E     {'b': 2} != {'b': 3}

    # 集合：给出多出/缺少的元素
    assert {1, 2} == {1, 3}
    # E     Extra items in the left set: 2
    # E     Extra items in the right set: 3
```

想看完整对比（默认会截断长内容）用 `-vv`：

```bash
pytest -vv                    # 不截断 diff
pytest --tb=long              # 完整 traceback
pytest --assert=plain         # 关闭重写，退化成原生 assert（排查重写本身出问题时用）
```

### 自定义对象的比较：`pytest_assertrepr_compare`

对自己定义的类，默认输出只有 `assert <Order object at 0x...> == <Order object at 0x...>`，毫无价值。可以实现 hook 定制：

```python
# conftest.py
from dataclasses import fields


def pytest_assertrepr_compare(config, op, left, right):
    """当两个 Order 对象比较失败时，输出逐字段差异。"""
    if op == "==" and isinstance(left, Order) and isinstance(right, Order):
        lines = ["Order 对象不相等，逐字段对比:"]
        for f in fields(Order):
            lv, rv = getattr(left, f.name), getattr(right, f.name)
            flag = "  " if lv == rv else "≠ "
            lines.append(f"  {flag}{f.name}: {lv!r}  vs  {rv!r}")
        return lines
    return None
```

输出：

```text
E   Order 对象不相等，逐字段对比:
E       order_id: 1001  vs  1001
E     ≠ status: 'PAID'  vs  'WAIT_PAY'
E     ≠ amount: 99.0  vs  100.0
```

这是接口自动化框架里非常值得做的一件事——把响应对象的 diff 直接打在报告上，省掉一半排查时间。

## 用法

### 断言的正确写法

```python
import pytest


def test_basic():
    resp = {"code": 0, "data": {"id": 1, "name": "qa"}}

    # 好：一次断言一个语义，失败信息精确
    assert resp["code"] == 0
    assert resp["data"]["name"] == "qa"

    # 不好：把多个条件用 and 串起来，失败时不知道是哪个条件挂了
    # assert resp["code"] == 0 and resp["data"]["name"] == "qa"


def test_with_message():
    code = 10001
    # 附加消息：注意消息是「补充」，不是「替代」——重写的解释依然会打印
    assert code == 0, f"登录失败，服务端返回 code={code}"


def test_exception():
    # 断言抛异常
    with pytest.raises(ValueError) as exc_info:
        int("abc")
    assert "invalid literal" in str(exc_info.value)

    # 直接用 match 正则更简洁
    with pytest.raises(ValueError, match=r"invalid literal.*'abc'"):
        int("abc")

    # 断言不抛特定异常：直接调用即可，抛了就是 Error
    int("123")


def test_approx():
    # 浮点比较必须用 approx，不要用 ==
    assert 0.1 + 0.2 == pytest.approx(0.3)
    assert 0.1 + 0.2 == pytest.approx(0.3, rel=1e-6)
    # 还支持容器
    assert [0.1 + 0.2, 1.0] == pytest.approx([0.3, 1.0])
    assert {"a": 0.1 + 0.2} == pytest.approx({"a": 0.3})


def test_warns():
    with pytest.warns(DeprecationWarning, match="已废弃"):
        legacy_api()
```

### 软断言：一次跑完收集所有失败

原生 `assert` 是**硬断言**——第一条失败就中断。校验一个大响应体时，你希望一次看到所有不匹配的字段。用 `pytest-check` 插件：

```python
# pip install pytest-check
import pytest_check as check


def test_response_all_fields(api):
    resp = api.get_user(1).json()
    check.equal(resp["code"], 0, "业务码")
    check.equal(resp["data"]["name"], "qa", "用户名")
    check.equal(resp["data"]["age"], 18, "年龄")
    check.is_in("vip", resp["data"]["tags"], "标签")
    # 四条全部执行，失败的会一起报出来
```

或者手写一个轻量版（不引第三方依赖时够用）：

```python
import contextlib
from typing import Iterator


class SoftAssert:
    def __init__(self):
        self.errors: list[str] = []

    @contextlib.contextmanager
    def check(self, desc: str) -> Iterator[None]:
        try:
            yield
        except AssertionError as e:
            self.errors.append(f"[{desc}] {e}")

    def assert_all(self):
        if self.errors:
            raise AssertionError(
                f"共 {len(self.errors)} 项校验失败:\n" + "\n".join(self.errors)
            )


def test_soft(api):
    sa = SoftAssert()
    resp = api.get_user(1).json()
    with sa.check("业务码"):
        assert resp["code"] == 0
    with sa.check("用户名"):
        assert resp["data"]["name"] == "qa"
    sa.assert_all()      # 最后统一抛
```

注意这个手写版**在工具模块里的 `assert` 不会被重写**，所以要么把 `SoftAssert` 放进 `conftest.py`，要么用 `register_assert_rewrite` 注册它所在的模块。

### 验证重写是否生效

```bash
# 看某模块有没有被重写：跑一条故意失败的用例，观察输出是否带 where 子句
pytest tests/test_demo.py::test_fail -q

# 对比：关掉重写再跑一次
pytest tests/test_demo.py::test_fail -q --assert=plain
```

两次输出一样 → 说明这个 assert 所在的模块本来就没被重写。

## 踩坑

1. **工具层封装的断言没有详细信息**。把断言抽到 `utils/assertions.py` 后，所有失败都退化成一行 `AssertionError`，排查全靠猜。这是最高频的坑，解法是 `pytest.register_assert_rewrite("utils.assertions")`，且必须写在 `conftest.py` 顶部、在 import 该模块之前。

2. **`register_assert_rewrite` 写晚了静默失效**。写在 `conftest.py` 里 import 语句之后，模块已进 `sys.modules`，注册无效，只有一条容易被淹没的 `PytestAssertRewriteWarning`。把它作为 conftest 的第一段代码（仅次于 `import pytest`）。

3. **`__pycache__` 缓存了旧的重写结果**。切分支或改了 pytest 版本后出现「断言信息格式诡异」「明明改了断言还报老错」，清缓存即可：`find . -name "__pycache__" -type d -exec rm -rf {} +`。只读文件系统（某些容器）下 pytest 无法写缓存，会退化为每次重新重写，只影响速度不影响正确性。

4. **`assert` 后面跟元组恒为真**。`assert (a == b, "msg")` 这个写法是把一个**非空元组**作为断言表达式，永远为真，用例永远通过。Python 会给 `SyntaxWarning: assertion is always true`，但很多人忽略了。正确写法是 `assert a == b, "msg"`（逗号不加括号）。

5. **用 `-O` 运行导致所有 assert 被剔除**。Python 的 `-O` 优化模式会移除所有 `assert` 语句。如果 CI 里设了 `PYTHONOPTIMIZE=1`，所有用例都会「通过」。这是灾难级的静默失效，务必检查 CI 环境变量。

6. **在被测业务代码里用 assert 做参数校验**。同样因为 `-O` 会被剔除，生产环境校验直接失效。`assert` 只能用于测试代码，业务代码用 `if ... raise ValueError`。

7. **长字符串/大字典的 diff 被截断**。默认输出会截断，看到 `...` 时用 `-vv`。另外 `--tb=short` 也会省略部分上下文，排查时切 `--tb=long`。

8. **`pytest.approx` 用在整数上出乎意料**。`assert 1 == pytest.approx(1.0000001)` 默认 `rel=1e-6` 是通过的。做金额校验时不要盲目用 approx，金额应当用 `Decimal` 精确比较。

9. **软断言滥用导致「失败堆积」**。一条用例里软断言 20 项，前置数据错了会一次报 20 个失败，反而看不清根因。软断言只适合「同一层级的并列校验」，前置条件仍应该用硬断言快速失败。

## 面试怎么答

**Q：pytest 为什么用 `assert` 就能给出很详细的失败信息？**

A（30 秒骨架）：因为 pytest 做了 **assert 语句重写**。它在 `sys.meta_path` 注册了一个自定义 import hook，测试模块被导入时先解析成 AST，把每个 `assert` 节点替换成一段展开代码——先把断言表达式的各个子表达式求值并绑到临时变量上，再做判断，失败时用这些临时变量拼出解释文本，最后编译执行并缓存到 `__pycache__`。所以失败信息里能看到 `assert 5 == 6` 以及 `where 5 = calc(2, 3)`。原生 Python 的 assert 做不到这一点，因为异常抛出后中间值已经拿不到了，这也是 unittest 必须提供 `assertEqual` 一整套方法的原因。

**追问 1：哪些代码会被重写？**

A：只有三类——符合 `python_files` 约定的测试模块、`conftest.py`、以及通过 entry point 注册的插件。**自己写的 utils / core / pages 这些普通模块不会被重写**。所以很多人把断言封装到工具类之后，发现失败信息退化成一行 `AssertionError`。解决办法是在 conftest 顶部调用 `pytest.register_assert_rewrite("utils.assertions")`，而且必须在该模块被 import 之前调用，否则只会给一条 warning、静默失效。

**追问 2：怎么给自定义对象定制断言输出？**

A：实现 `pytest_assertrepr_compare(config, op, left, right)` hook，判断操作符和类型后返回一个字符串列表，pytest 会把它作为失败解释打印出来。我在接口框架里就用它把响应对象的逐字段 diff 打出来——哪个字段不一致、期望什么实际什么，一眼就能看到，比翻日志快很多。

**追问 3：pytest 的断言有什么坑？**

A：三个印象最深的。一是 `assert (a == b, "msg")` 加了括号变成断言一个非空元组，永远为真、用例永远绿，Python 只给一条 SyntaxWarning。二是 `-O` / `PYTHONOPTIMIZE=1` 会把所有 assert 语句从字节码里剔除，CI 里如果设了这个环境变量，全部用例静默通过。三是浮点比较必须用 `pytest.approx`，直接 `==` 会因为二进制表示误差挂掉，但金额场景应该用 `Decimal` 而不是 approx。

**追问 4：硬断言和软断言怎么选？**

A：默认用硬断言，快速失败、根因清晰。只有在「同一层级的并列字段校验」场景才用软断言——比如一次校验响应体的 10 个字段，希望一次看到全部不匹配项而不是修一个跑一次。实现上用 `pytest-check` 插件，或者自己写一个上下文管理器收集 AssertionError 最后统一抛。要注意前置条件仍然用硬断言，否则前置错了会一次报出十几个衍生失败，反而掩盖根因。

## 参考

- [pytest 官方：Assertion introspection](https://docs.pytest.org/en/stable/how-to/assert.html)
- [pytest 官方：`register_assert_rewrite` API](https://docs.pytest.org/en/stable/reference/reference.html#pytest.register_assert_rewrite)
- 相关笔记：[[pytest 用例发现规则]]、[[测试框架日志与断言封装]]、[[pytest 插件机制与 hook 函数]]
