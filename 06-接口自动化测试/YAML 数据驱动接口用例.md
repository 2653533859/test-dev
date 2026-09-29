---
created: 2026-07-31
tags: [接口自动化测试/数据驱动]
---

# YAML 数据驱动接口用例

> 数据驱动的价值不是「把参数搬进文件」，而是让加一条用例的成本从「写一个函数」降到「加五行 YAML」。做不到这一点的数据驱动，是在给自己增加维护量。

## 概念

### 什么时候该上数据驱动

不是所有用例都适合。判断标准很简单：**同一段请求逻辑 + 不同的输入输出**。

| 场景 | 适合数据驱动？ |
|------|----------------|
| 一个接口的 20 组参数校验 | 非常适合 |
| 边界值批量覆盖 | 非常适合 |
| 多环境同一套用例 | 适合（数据里放变量） |
| 需要复杂前置造数 + 数据库校验的业务流 | 不适合，硬写 Python 更清晰 |
| 并发、幂等这类需要特殊控制流的 | 不适合 |

**反模式**：把所有用例都塞进 YAML，最后 YAML 里出现 `if`、`for`、`eval` 这类东西——那说明你在用 YAML 写代码，不如直接写 Python。

### YAML 比 Excel 好在哪

| 维度 | YAML | Excel |
|------|------|-------|
| Git diff | 逐行可读，冲突好解 | 二进制，无法 diff |
| 嵌套结构 | 原生支持 | 只能塞 JSON ��符串 |
| 注释 | 支持 `#` | 单元格批注，易丢 |
| 类型 | 自动识别 int/bool/null | 全是字符串，易出「1 变 1.0」 |
| 非技术同事编辑 | 需要一点学习成本 | 门槛低 |

技术团队内部用 YAML，需要产品/业务同学参与维护时才考虑 Excel。**Excel 最大的坑是类型丢失**：单元格里的 `1` 读出来可能是 `1.0`（float），`TRUE` 变成 `True` 字符串，`001` 变成 `1`。

### 三种数据驱动的粒度

1. **参数级**：只有请求参数不同，断言逻辑写在 Python 里
2. **用例级**：请求 + 期望结果都在 YAML 里，Python 只有一个通用 runner
3. **流程级**：多个步骤串成一条流，YAML 描述整条链路

粒度越大越灵活，但 runner 越复杂。**建议从 1 开始，确有需要再升级**，别一上来就造一个「YAML 描述一切」的框架。

## 用法

### 粒度一：参数级数据驱动

```yaml
# data/create_order_invalid.yaml
- case: 缺失必填 sku_id
  body: {quantity: 1}
  expected_status: 400
  expected_code: 100001

- case: quantity 为 0（下边界外）
  body: {sku_id: SKU001, quantity: 0}
  expected_status: 400
  expected_code: 100002

- case: quantity 为 100（上边界外）
  body: {sku_id: SKU001, quantity: 100}
  expected_status: 400
  expected_code: 100002

- case: quantity 类型错误
  body: {sku_id: SKU001, quantity: "abc"}
  expected_status: 400

- case: remark 超长 201 字符
  body:
    sku_id: SKU001
    quantity: 1
    remark: "aaaaaaaaaa……（201 字符，实际用 !!python 生成或写全）"
  expected_status: 400
```

```python
# test_create_order.py
from pathlib import Path
import pytest
import yaml

DATA_DIR = Path(__file__).parent / "data"


def load_cases(filename: str):
    """加载 YAML 并转成 pytest.param，用 case 字段做用例 id。"""
    raw = yaml.safe_load((DATA_DIR / filename).read_text(encoding="utf-8"))
    return [pytest.param(item, id=item["case"]) for item in raw]


@pytest.mark.parametrize("case", load_cases("create_order_invalid.yaml"))
def test_create_order_invalid(api, case):
    r = api.post("/api/v1/orders", json=case["body"])
    assert r.status_code == case["expected_status"], \
        f"{case['case']}: 期望 {case['expected_status']} 实际 {r.status_code} {r.text[:300]}"
    if "expected_code" in case:
        assert r.json()["code"] == case["expected_code"]
```

`id=item["case"]` 让报告里直接显示中文用例名，这是最值得做的一个小细节。

### 粒度二：用例级 runner

```yaml
# testcases/order_api.yaml
config:
  name: 订单接口用例集
  base_url: ${ENV_BASE_URL}
  headers:
    Content-Type: application/json

tests:
  - name: 创建订单-仅必填
    request:
      method: POST
      path: /api/v1/orders
      json: {sku_id: SKU001, quantity: 1}
    validate:
      status: 200
      jsonpath:
        $.code: 0
        $.data.status: UNPAID
      schema: order_detail          # 引用预注册的 Schema 名
    extract:
      order_id: $.data.order_id

  - name: 查询刚创建的订单
    request:
      method: GET
      path: /api/v1/orders/${order_id}
    validate:
      status: 200
      jsonpath:
        $.data.order_id: ${order_id}
        $.data.status: UNPAID

  - name: 取消订单
    request:
      method: POST
      path: /api/v1/orders/${order_id}/cancel
    validate:
      status: 200
      jsonpath:
        $.data.status: CANCELLED
```

runner 实现：

```python
import os
import re
from pathlib import Path

import pytest
import yaml
from jsonpath_ng.ext import parse

PLACEHOLDER = re.compile(r"\$\{(\w+)\}")


def render(obj, ctx: dict):
    """递归替换 ${var}；整串就是占位符时保留原类型。"""
    if isinstance(obj, str):
        m = PLACEHOLDER.fullmatch(obj)
        if m:
            key = m.group(1)
            if key not in ctx:
                raise KeyError(f"未定义的变量 ${{{key}}}，当前上下文: {list(ctx)}")
            return ctx[key]
        return PLACEHOLDER.sub(lambda x: str(ctx[x.group(1)]), obj)
    if isinstance(obj, dict):
        return {k: render(v, ctx) for k, v in obj.items()}
    if isinstance(obj, list):
        return [render(v, ctx) for v in obj]
    return obj


def jsonpath_one(data, expr: str):
    matches = parse(expr).find(data)
    if not matches:
        raise AssertionError(f"JSONPath {expr} 无匹配\n响应: {data}")
    return matches[0].value


def run_suite(api, suite_file: Path, schemas: dict):
    suite = yaml.safe_load(suite_file.read_text(encoding="utf-8"))
    ctx = dict(os.environ)                       # 环境变量可直接当变量用
    for step in suite["tests"]:
        req = render(step["request"], ctx)
        r = api.request(req["method"], req["path"],
                        json=req.get("json"), params=req.get("params"))

        v = step.get("validate", {})
        if "status" in v:
            assert r.status_code == v["status"], \
                f"[{step['name']}] 状态码期望 {v['status']} 实际 {r.status_code}: {r.text[:300]}"
        if "schema" in v:
            assert_schema(r.json(), schemas[v["schema"]])
        for expr, expected in render(v.get("jsonpath", {}), ctx).items():
            actual = jsonpath_one(r.json(), expr)
            assert actual == expected, \
                f"[{step['name']}] {expr} 期望 {expected!r} 实际 {actual!r}"

        for key, expr in step.get("extract", {}).items():
            ctx[key] = jsonpath_one(r.json(), expr)


SUITES = list((Path(__file__).parent / "testcases").glob("*.yaml"))


@pytest.mark.parametrize("suite_file", SUITES, ids=lambda p: p.stem)
def test_suite(api, suite_file, schemas):
    run_suite(api, suite_file, schemas)
```

> 注意：整个 suite 作为**一个** pytest 用例。也可以让每个 step 变成独立用例，但那样 step 之间就无法共享 ctx 了（除非用 module 级 fixture 存 ctx，那又回到了状态共享的坑）。**业务流按 suite 粒度报告，是更务实的选择**。

### 环境隔离：变量分层

```yaml
# config/env.yaml
default: &default
  timeout: 10
  headers:
    User-Agent: qa-autotest/1.0

test:
  <<: *default
  base_url: https://api-test.example.com
  db_host: 10.0.0.5
  users:
    normal: {username: qa01, password: Pwd@123}
    admin:  {username: admin01, password: Adm@123}

staging:
  <<: *default
  base_url: https://api-stg.example.com
  db_host: 10.0.1.5
  users:
    normal: {username: qa01, password: ${STG_QA_PWD}}
    admin:  {username: admin01, password: ${STG_ADMIN_PWD}}
```

`&default` / `<<: *default` 是 YAML 的锚点与合并，能避免复制粘贴。密码用 `${ENV_VAR}` 从环境变量注入，**绝不写死在文件里**。

```python
# conftest.py
import os
import yaml
from pathlib import Path

def pytest_addoption(parser):
    parser.addoption("--env", default="test", help="运行环境: test / staging")

@pytest.fixture(scope="session")
def env_config(request):
    env = request.config.getoption("--env")
    cfg = yaml.safe_load(Path("config/env.yaml").read_text(encoding="utf-8"))[env]
    return render(cfg, dict(os.environ))     # 解析 ${ENV_VAR}
```

```bash
pytest --env=staging -m smoke
```

### YAML 的类型陷阱

YAML 1.1 有一批「善意」的隐式类型转换，会坑到你：

```yaml
version: 1.20        # → float 1.2，尾部 0 丢了！
phone: 13800138000   # → int，不是字符串
zipcode: 010010      # → 可能被当八进制
flag: yes            # → YAML 1.1 里是 bool True（PyYAML 会转）
country: NO          # → bool False！挪威的国家码经典坑
password: 123456     # → int
empty:               # → None，不是空字符串
time: 12:30          # → 可能被解析成 sexagesimal
```

解决办法：**凡是「看起来像数字但语义是字符串」的，一律加引号**。

```yaml
version: "1.20"
phone: "13800138000"
zipcode: "010010"
flag: "yes"
country: "NO"
password: "123456"
empty: ""
```

### 一定要用 `safe_load`

```python
yaml.safe_load(text)    # 正确
yaml.load(text)         # 危险：能构造任意 Python 对象，等于 eval
```

`yaml.load` 支持 `!!python/object/apply:os.system ["rm -rf /"]` 这种标签，读取不可信的 YAML 等于执行任意代码。测试数据文件虽然一般可信，但养成习惯没坏处。

## 踩坑

1. **用例 id 没设，报告里全是 `test_x[case0]`**：失败了得回去数第几条。用 `pytest.param(..., id=中文名)`。
2. **YAML 隐式类型转换**：手机号变 int、`1.20` 变 `1.2`、`NO` 变 `False`。加引号。
3. **用 `yaml.load` 而不是 `safe_load`**：安全隐患，且某些 YAML 特性会导致奇怪行为。
4. **占位符替换把类型改了**：`{"order_id": "${order_id}"}` 渲染成字符串 `"100231"`，后端严格校验类型时 400。runner 里要处理「整串就是占位符」的情况，保留原类型。
5. **YAML 里写逻辑**：出现 `condition: "${amount} > 100"`、`eval` 字段，说明粒度选错了。这类用例回归 Python。
6. **数据文件和代码不同步**：YAML 里加了新字段，runner 不认识，静默忽略。runner 应该对未知字段报错（fail fast），而不是跳过。
7. **敏感信息写进 YAML 提交**：密码、token、真实手机号。用 `${ENV_VAR}` 占位，CI 里注入。
8. **一个 YAML 文件塞几百条用例**：加载慢、diff 难看、定位困难。按接口或模块拆文件。
9. **中文乱码**：Windows 下 `open(path)` 默认用 GBK。一律显式 `encoding="utf-8"`。
10. **YAML 缩进用了 Tab**：YAML 规范不允许 Tab 缩进，报 `found character '\t' that cannot start any token`。编辑器配置成空格。
11. **过度设计 runner**：为了支持 YAML 里的循环、条件、函数调用，runner 越写越复杂，最后成了一个残废版的编程语言，新人看不懂也调不动。**框架的复杂度上限应该是：新人半小时能看懂 runner 全部代码**。

## 面试怎么答

**Q：你们的接口用例数据是怎么管理的？**

A：用 YAML 做数据驱动，按接口或模块拆文件。分两种粒度：参数校验和边界值这类「同一段逻辑跑不同输入」的，用参数级驱动，YAML 里只放 body 和期望的状态码、业务码，Python 里写一个参数化的测试函数，用 `pytest.param(..., id=中文用例名)` 让报告可读；业务流用例用用例级驱动，YAML 里描述 request、validate、extract 三段，一个通用 runner 负责渲染占位符、发请求、跑断言、提取变量传给下一步。环境差异用 YAML 锚点做分层配置，密码这类敏感信息用 `${ENV_VAR}` 从环境变量注入，绝不写进仓库。

**Q：为什么用 YAML 不用 Excel？**

A：主要是可维护性。YAML 是纯文本，Git 能逐行 diff，多人协作时冲突好解，代码评审时能看清改了什么；Excel 是二进制，diff 出来是一坨，冲突基本只能二选一。其次 YAML 原生支持嵌套结构和注释，而 Excel 表达嵌套 JSON 只能往单元格里塞字符串。还有个很实际的坑是 Excel 会丢类型：单元格里的 `1` 读出来可能是 `1.0`，`001` 变成 `1`，`TRUE` 变成布尔——这些都会让请求体和预期不一致。只有在需要产品或业务同学直接参与维护用例数据时，我才会考虑 Excel。

**Q：数据驱动是不是所有用例都该用？**

A：不是，这是我踩过的坑。数据驱动适合「同一段请求逻辑 + 不同输入输出」的场景，比如参数校验、边界值、多环境。但需要复杂前置造数、数据库校验、并发控制的用例，硬塞进 YAML 会让 runner 越来越复杂——为了支持条件判断加个 `condition` 字段，为了支持循环加个 `loop`，最后 runner 变成一个残废版的编程语言，新人看不懂也调不动，还不如直接写 Python 清晰。我的判断标准是：**如果 YAML 里开始出现逻辑，就说明这条用例应该回归代码**。框架复杂度的上限是新人半小时能读完 runner 的全部代码。

## 参考

- [PyYAML 文档](https://pyyaml.org/wiki/PyYAMLDocumentation)
- [YAML 1.2 规范](https://yaml.org/spec/1.2.2/)
- [pytest parametrize 文档](https://docs.pytest.org/en/stable/how-to/parametrize.html)
- 相关笔记：[[JSONPath 与正则提取响应字段]]、[[接口串联与依赖参数提取传递]]、[[接口用例设计维度]]、[[05-自动化测试框架]]
