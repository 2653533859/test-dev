---
created: 2026-07-31
tags: [项目实战/持续集成]
---

# code 示例说明

本目录是**能说明设计意图的最小可运行示例**，clone 后可直接本地验证门禁与通知脚本。

- 仓库地址（占位）：`https://github.com/<your-name>/qa-ci-pipeline`

## 文件清单

```text
code/
├── README.md            本说明
├── requirements.txt     依赖清单（requests + pytest）
├── pytest.ini           标记注册与默认参数
├── test_demo.py         最小冒烟用例：生成 JUnit XML 供 gate.py 解析
├── Jenkinsfile          声明式流水线：分层触发、质量门禁、post always 通知与清理
├── api-regression.yml   GitHub Actions 等价实现（放到 .github/workflows/ 下）
├── Dockerfile           测试执行器镜像：时区、分层缓存、非 root 用户
├── docker-compose.test.yml  被测服务编排：healthcheck + service_healthy
├── gate.py              质量门禁：解析 JUnit XML，退出码决定构建结论
└── notify.py            企微通知：可定位、可点击、可追责；缺 webhook 时 graceful 退出
```

## 本地验证

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 跑测试，生成 JUnit XML（必须先建 reports 目录）
mkdir -p reports
pytest -m smoke --junitxml=reports/junit.xml

# 3. 跑质量门禁（退出码 0 = 通过，1 = 阻断）
python gate.py --junit reports/junit.xml --min-pass-rate 98 --max-p0-failures 0
echo "门禁退出码：$?"

# 4. 跑通知脚本（未设置 WECOM_WEBHOOK 时会 graceful 退出，不报错）
export WECOM_WEBHOOK='https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx'
python notify.py --status SUCCESS --junit reports/junit.xml

# 不设 webhook 也能跑，会打印「未设置 WECOM_WEBHOOK 环境变量，跳过通知」
unset WECOM_WEBHOOK
python notify.py --status FAILURE --junit reports/junit.xml
```

## Docker 镜像本地构建

```bash
# 构建测试执行器镜像（CMD 是 pytest --version，用于验证镜像可用）
docker build -t pytest-runner:3.11 .
docker run --rm pytest-runner:3.11
```

## 设计说明

对应的拆解笔记：

- [[Jenkinsfile 多阶段流水线设计]]
- [[质量门禁与失败通知策略]]
- [[Docker 化测试执行环境]]
- 项目总览：[[CI 流水线打通/CI 流水线打通]]
