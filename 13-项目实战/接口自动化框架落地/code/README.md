---
created: 2026-07-31
tags: [项目实战/接口自动化框架]
---

# code 示例说明

本目录是**能说明设计意图的最小可运行示例**，clone 后可直接跑（无真实 API 时跑到「连接超时」即视为链路通）。完整工程另开仓库维护。

- 仓库地址（占位）：`https://github.com/<your-name>/api-autotest`

## 文件清单

```text
code/
├── README.md            本说明
├── requirements.txt     依赖清单（固定版本号）
├── config.yaml          多环境配置：test / dev / staging / prod 的 base_url
├── conftest.py          横切关注点：多环境、token 跨进程共享、数据隔离与清理
├── http_client.py       HttpClient 封装：Session 复用、强制超时、幂等重试、日志
├── assertions.py        三层断言：状态码 / JSON Schema / 业务字段
├── context.py           用例级上下文变量池：变量存取、模板渲染、响应字段提取
├── test_order_create.py 用例示例：YAML 数据驱动 + 三层断言 + 提取回写
├── create_order.yaml    用例数据示例
├── pytest.ini           标记注册与默认参数
└── schemas/
    └── order_create.json  订单创建接口的 JSON Schema
```

## 跑起来

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置凭据（密码走环境变量，不进代码库）
export TEST_PASSWORD='your-password'

# 3. 跑冒烟用例（默认 test 环境，无真实 API 会跑到「连接超时」）
pytest -m smoke

# 4. 切换环境
pytest -m smoke --env dev
pytest -m smoke --env staging

# 5. 并行 + Allure 报告
pytest -m smoke -n 4 --alluredir=allure-results
allure serve allure-results
```

## 验证链路是否通

无真实后端时，`pytest -m smoke` 应跑到「连接超时」（`requests.exceptions.ConnectionError`），
**不应**出现 `ImportError` 或 `FixtureNotFound`——出现说明工程结构有缺失。

## 设计说明

对应的拆解笔记：

- [[YAML 用例结构与数据驱动实现]]
- [[Token 鉴权与会话管理实现]]
- [[三层断言与响应校验实现]]
- 项目总览：[[接口自动化框架落地/接口自动化框架落地]]
