---
created: 2026-07-31
tags: [自动化测试框架/框架设计]
---

# 数据驱动测试：YAML 与 Excel 驱动

![[assets/data-driven-flow.svg]]
*图示：数据驱动 = 一份「测试脚本」 + 一份「外部数据文件」，由加载器把每行数据喂给参数化用例；数据变化时只改文件、不动代码。*

> 数据驱动解决的是「同一个逻辑、N 组输入输出」的问题。核心是**把测试数据和测试代码分离**，让非开发同学也能维护用例数据。

## 概念

### 数据驱动和参数化的关系

`@pytest.mark.parametrize` 已经能驱动多组数据，但数据写在代码里，非测试同学改不了，而且数据一多代码就臃肿。**数据驱动 = parametrize 的数据外置**：数据搬到 YAML/Excel/JSON，加载器读出来再喂给 parametrize。

三者分工：

- **parametrize**：负责「一组输入对应一条用例」的执行机制（见 [[pytest 参数化 parametrize]]）
- **YAML/Excel**：负责「数据存哪里、谁维护」
- **加载器**：负责「读文件 → 转成 parametrize 能接受的参数列表」

### 什么时候用哪种格式

- **YAML**：人写可读性最好，适合接口入参、断言预期这类结构化数据，首选。
- **Excel**：业务/产品同学最熟悉，适合大批量用例、需要他们批量填充的场景；但类型容易丢（数字变字符串）。
- **JSON**：程序生成的数据、前后端对接的中间产物。

## 用法

### YAML 数据 + 加载器

```yaml
# data/order_cases.yaml
- case: 正常下单
  sku_id: SKU_001
  qty: 1
  expect_status: CREATED
- case: 数量为0
  sku_id: SKU_001
  qty: 0
  expect_status: REJECTED
```

```python
import yaml
import pytest
from api.order_api import OrderApi


def load_cases(path="data/order_cases.yaml"):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.mark.parametrize("case", load_cases())
def test_order(case):
    resp = OrderApi().create(sku_id=case["sku_id"], qty=case["qty"])
    assert resp.status == case["expect_status"]
```

`load_cases()` 在模块导入时执行一次，把 YAML 展开成参数列表，等价于把每组数据逐个 `parametrize` 进去。

### Excel 数据（openpyxl）

```python
from openpyxl import load_workbook


def load_excel(path, sheet="cases"):
    wb = load_workbook(path, data_only=True)
    ws = wb[sheet]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    return [dict(zip(header, r)) for r in rows[1:] if any(r)]
```

读出来同样是 `list[dict]`，后续和 YAML 走同一条 parametrize 路径。

## 踩坑

1. **YAML 缩进用 Tab**：YAML 只认空格，混用 Tab 直接解析报错且定位难。编辑器统一设成 2 空格。
2. **Excel 数字变字符串**：`qty: 1` 读出来可能是 `"1"`，和接口返回的 `int` 比不相等。加载时显式转换类型，或在 YAML 里用 `!!int` 明确。
3. **数据类型丢失导致断言怪异**：`expect_status: 200` 在 Excel 里存成文本，断言 `resp.code == 200` 永远 False，但报错信息看不出类型问题。加载层统一做类型规整。
4. **数据文件和脚本耦合路径**：`open("data/order_cases.yaml")` 写死相对路径，换运行目录就找不到。路径应基于 `__file__` 或走 config 的绝对基准。
5. **多环境数据混在一份文件**：test 和 prod 的用例数据不同（如测试账号），应当按环境分文件或分 key，配 `env` 加载（见 [[多环境配置与环境隔离]]）。
6. **数据里含特殊字符/引号**：YAML 里字符串带 `:`、`#` 要加引号，否则被当注释或键值分隔。Excel 里换行符会让 `iter_rows` 读歪，注意合并单元格。
7. **数据驱动掩盖了用例意图**：一组 YAML 里塞了 200 行，没人知道每条在测什么。建议每条数据配 `case` 字段写清楚场景名，parametrize 的 `ids` 用上它。
8. **加载函数在收集阶段报错拖垮全部用例**：`load_cases()` 在 import 时跑，文件损坏会导致整个模块收集失败。加载失败要给清晰报错，最好和用例执行隔离。

## 面试怎么答

- **问：数据驱动和关键字驱动有什么区别？**
  答：数据驱动只把「数据」外置，测试逻辑还是代码写；关键字驱动进一步把「操作」也外置成关键字表（如「输入/点击/断言」），连步骤都能由非开发人员编排。数据是 KDT 的子集。
- **问：为什么不直接把数据写进 parametrize？**
  答：写在代码里只有开发能改、且数据多时代码臃肿、版本管理也乱。外置到 YAML/Excel 后，数据和脚本分离，业务同学能维护数据，脚本只管逻辑，改数据不用动代码也不用重新 code review。
- **追问：YAML 和 Excel 怎么选？**
  答：结构化、需要开发维护的接口数据用 YAML；需要产品/业务批量填充的大批量用例用 Excel，但要处理好类型丢失。

## 参考

- [pytest parametrize 文档](https://docs.pytest.org/en/stable/how-to/parametrize.html)
- [PyYAML 文档](https://pyyaml.org/wiki/PyYAMLDocumentation)
- 相关笔记：[[pytest 参数化 parametrize]]、[[测试框架分层架构设计]]、[[多环境配置与环境隔离]]
