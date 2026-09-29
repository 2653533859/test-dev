# Web UI 自动化工程样例代码

本目录包含了基于 Playwright + pytest + Page Object 模式的企业级 Web UI 自动化工程最小可运行示例。

## 技术栈与依赖
- **Python**: 3.9+
- **Playwright**: 1.40.0+
- **pytest**: 7.4.0+
- **pytest-playwright**: 0.4.0+
- **allure-pytest**: 2.13.0+

## 目录结构
```text
code/
├── pytest.ini            # pytest 核心运行配置
├── requirements.txt      # 依赖包列表
├── conftest.py           # 全局 Fixture 与失败截图、Trace 收集钩子
├── pages/
│   ├── base_page.py      # BasePage 基类与原子操作封装
│   └── login_page.py     # 登录页 Page Object 封装
└── tests/
    └── test_login.py     # 登录与权限核心业务用例
```

## 快速上手

### 1. 安装依赖与浏览器内核
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 执行测试

```bash
# 1. 默认无头模式运行全部用例
pytest

# 2. 有头模式调试观察浏览器运行过程
pytest --headed

# 3. 失败时自动保存 Trace Viewer 与截图（排障推荐）
pytest --tracing=retain-on-failure --screenshot=only-on-failure

# 4. 生成并查看 Allure 报告
pytest --alluredir=allure-results
allure serve allure-results
```

### 3. 查看失败 Trace
如果用例执行失败，在 `artifacts/traces/` 目录下将生成 `trace_<test_name>.zip`，可通过以下命令回放检查：
```bash
playwright show-trace artifacts/traces/trace_test_login_success.zip
```
