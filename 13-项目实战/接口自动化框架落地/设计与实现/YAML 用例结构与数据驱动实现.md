---
created: 2026-07-31
tags: [项目实战/接口自动化框架]
---

# YAML 用例结构与数据驱动实现

> 定义一套刚好够用的 YAML 用例结构，让加一条用例只需要加几行数据，不用碰 Python。

## 概念

数据驱动的本质是**把「变的部分」和「不变的部分」分开**：请求怎么发、断言怎么做是不变的逻辑，写在 Python 里；入参和期望值是变的数据，放在 YAML 里。

关键设计决策是**边界划在哪**。两个极端都不好：

- **划得太靠数据侧**（HttpRunner 式，连接口路径、提取表达式、前后置步骤全在 YAML）：一旦需要条件判断、循环、加签这类逻辑，YAML 就开始长出「表达式」，本质是在配置文件里发明一门残疾的编程语言。
- **划得太靠代码侧**（数据直接写在 `parametrize` 里）：改一个金额也要提代码 PR，非编码同学完全无法参与。

本项目划的位置：**YAML 只描述「一次调用的输入与期望输出」，不描述控制流**。判断标准很直接——YAML 里一旦出现 `if`、`for`、`eval`，说明这条用例不该用数据驱动，回去写 Python。

## 用法

### 用例数据结构

```yaml
# data/order/create_order.yaml
- name: 正常下单-普通商品
  marks: [smoke, p0]
  payload:
    skuId: "${sku_id}"        # ${} 表示从上下文变量池取值
    quantity: 1
    couponId: null
  expect:
    status_code: 200
    schema: order_create      # 对应 schemas/order_create.json
    fields:
      data.status: WAIT_PAY
      data.payAmount: 99.00
  extract:                     # 提取结果写回上下文，供后续用例使用
    order_id: $.data.orderId

- name: 库存不足-下单失败
  payload:
    skuId: "${sku_id_no_stock}"
    quantity: 999
  expect:
    status_code: 200           # 业务失败仍返回 200，靠 code 区分
    fields:
      code: 40010
      message: 库存不足

- name: 数量为零-参数校验
  payload:
    skuId: "${sku_id}"
    quantity: 0
  expect:
    status_code: 400
    fields:
      code: 40001
```

### 加载与参数化

```python
# core/loader.py
from pathlib import Path
import yaml

DATA_DIR = Path(__file__).parent.parent / "data"

def load_cases(relative_path: str) -> list[dict]:
    """读取 YAML 用例集。返回 list[dict]，每个 dict 是一条用例。"""
    with open(DATA_DIR / relative_path, encoding="utf-8") as f:   # 必须显式 utf-8
        cases = yaml.safe_load(f)                                  # 绝不用 yaml.load
    return cases

def case_ids(cases: list[dict]) -> list[str]:
    """用中文 name 作为用例 ID，报告里可读。"""
    return [c["name"] for c in cases]
```

```python
# tests/test_order_create.py
import pytest
from core.loader import load_cases, case_ids

CASES = load_cases("order/create_order.yaml")

@pytest.mark.parametrize("case", CASES, ids=case_ids(CASES))
def test_create_order(case, api_order, ctx, assert_response):
    payload = ctx.render(case["payload"])        # 渲染 ${} 变量
    resp = api_order.create(payload)
    assert_response(resp, case["expect"])        # 三层断言统一入口
    ctx.extract(resp, case.get("extract", {}))   # 提取字段回写上下文
```

三行主体逻辑，一眼看得懂发生了什么——**这是分层是否合格的检验标准**。

### 变量渲染与上下文池

```python
# core/context.py
import re
from jsonpath_ng import parse as jsonpath_parse

VAR_PATTERN = re.compile(r"\$\{(\w+)\}")

class Context:
    """用例级上下文变量池，不跨用例共享。"""

    def __init__(self, initial: dict | None = None):
        self._data = dict(initial or {})

    def render(self, obj):
        """递归替换 ${var}。整串就是一个变量时保留原始类型，否则做字符串插值。"""
        if isinstance(obj, str):
            full = VAR_PATTERN.fullmatch(obj)
            if full:
                return self._data[full.group(1)]          # 保留 int / bool / None
            return VAR_PATTERN.sub(lambda m: str(self._data[m.group(1)]), obj)
        if isinstance(obj, dict):
            return {k: self.render(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.render(v) for v in obj]
        return obj

    def extract(self, resp, rules: dict):
        """按 JSONPath 规则从响应里取值存入池子。"""
        body = resp.json()
        for var_name, expr in rules.items():
            matches = jsonpath_parse(expr).find(body)
            if not matches:
                raise AssertionError(f"提取变量 {var_name} 失败，JSONPath 无匹配：{expr}")
            self._data[var_name] = matches[0].value
```

`render` 里区分「整串是变量」和「字符串里嵌变量」是必要的：`"${quantity}"` 应该得到整数 `1`，而 `"order-${order_id}"` 应该得到字符串。忽略这点会导致所有参数都变成字符串，后端参数校验直接 400。

## 踩坑

1. **`yaml.load` 的反序列化风险**：`yaml.load` 可以构造任意 Python 对象，读到恶意 YAML 能执行代码。一律用 `yaml.safe_load`。新版 PyYAML 不传 `Loader` 会告警，也是这个原因。

2. **YAML 1.1 的布尔陷阱**：以下写法全部会被解析成布尔值。

   ```yaml
   status: on        # True，不是字符串 "on"
   enabled: yes      # True
   answer: no        # False
   country: NO       # False（挪威国家码，经典坑）
   ```

   解法：所有字符串值加引号 `status: "on"`。团队里直接定成规范，不靠自觉。

3. **`null` 和空字符串不是一回事**：`couponId:` （后面留空）解析成 `None`，`couponId: ""` 是空串。后端对这两者的处理经常不同，写用例时要明确意图；想测「字段不传」应该在代码里 `pop` 掉这个 key，而不是设成 `None`。

4. **前导零被吃掉**：`phone: 013800138000` 会被当成数字（甚至八进制）解析。手机号、订单号、身份证一律加引号。

5. **`ids` 用中文在 Allure 里显示为 Unicode 转义**：`test_create_order[\u6b63\u5e38\u4e0b\u5355]`。在 `pytest.ini` 加：

   ```ini
   [pytest]
   disable_test_id_escaping_and_forfeit_all_rights_to_community_support = True
   ```

6. **`ids` 重复导致 pytest 自动加后缀**：两条用例的 `name` 相同时，pytest 会生成 `[正常下单0]`、`[正常下单1]`，报告里根本分不清。加载时做唯一性校验，重名直接抛错。

7. **在模块顶层 `load_cases()` 的副作用**：文件在收集期就被读取，YAML 语法错误会导致**整个模块收集失败**，报错信息还很隐晦（`ERROR collecting ...`）。这其实是好事——尽早暴露，但要知道去哪看错。

8. **上下文池设成 session 级导致并行踩踏**：曾把 `ctx` 做成全局单例，`order_id` 被多条用例互相覆盖。上下文必须是 function 或 class 作用域；确需跨用例传递的（比如串联场景），用 `class` 作用域并把这组用例绑在同一个 class 里。

## 面试怎么答

**Q：数据驱动的好处是什么？不就是省点代码？**

A：省代码是次要的，核心是**让每组数据成为一条可独立定位、独立重跑的用例**。如果把 5 组数据写在一个 for 循环里，第 2 组失败后面就不跑了，报告只显示 1 条失败，排查得翻日志；用 `parametrize` 展开后，5 条独立计数，失败 1 条其余照跑，还能 `-k "库存不足"` 精确重跑。另外它把用例维护的门槛降到「改 YAML」，测试同学不用碰框架代码。

**Q：为什么选 YAML 不选 Excel 或 JSON？**

A：JSON 不支持注释、多行字符串难写，用例数据需要注释说明业务含义；Excel 是二进制，无法 diff、无法 code review、合并冲突只能靠人肉，且要额外依赖 openpyxl。YAML 是纯文本、支持注释、层级表达清晰、Git 友好。唯一代价是缩进敏感和几个历史语法坑，团队定个规范就能规避。

**Q：数据驱动和参数化是一回事吗？**

A：参数化是**技术手段**（`pytest.mark.parametrize`），数据驱动是**设计思想**（用例逻辑与数据分离）。数据驱动通常用参数化实现，但数据可以来自 YAML、CSV、数据库甚至接口，参数化只是最后一步的挂载方式。

**Q：如果一条用例需要判断「A 字段存在时才校验 B」，YAML 怎么写？**

A：不写。这是我们定的硬规则——YAML 里出现任何条件表达式，说明这条用例不适合数据驱动，回到 Python 用例里正常写 if。踩过这个坑：早期有人在 YAML 里塞表达式用 `eval` 解析，既不安全又没法调试，后来全部重构掉了。配置化的边界必须守住，否则会演变成在配置文件里发明一门语言。

## 参考

- PyYAML 文档：`https://pyyaml.org/wiki/PyYAMLDocumentation`
- 相关笔记：[[数据驱动测试：YAML 与 Excel 驱动]]、[[YAML 数据驱动接口用例]]、[[pytest 参数化 parametrize]]、[[JSONPath 与正则提取响应字段]]
- 所属项目：[[接口自动化框架落地]]
