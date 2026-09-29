---
created: 2026-07-31
tags: [持续集成/质量门禁]
---

# SonarQube 静态扫描接入

> 单元测试看「逻辑对不对」，SonarQube 看「代码坏不坏」。它在不跑业务的情况下，用静态分析找出 bug、漏洞、坏味道、重复代码、覆盖率缺口。是质量门禁里「代码健康」那一关。

## 概念

### SonarQube 解决什么问题

自动化测试能发现「功能是否按预期」，但发现不了「代码本身臭不臭」：空指针隐患、SQL 注入风险、复杂度过高的函数、重复代码、没有覆盖到的关键分支。这些问题不会让用例立刻红，但会累积成技术债，最终引发线上事故。

SonarQube 是静态代码分析平台：它**不执行你的代码**，而是解析 AST（抽象语法树）、数据流、控制流，按规则打分。核心产出：

- **Bugs**：明显的逻辑错误（如空指针解引用）
- **Vulnerabilities**：安全漏洞（如硬编码密码、SQL 注入）
- **Code Smells**：坏味道（过长函数、重复代码、命名差）
- **Coverage**：单测覆盖率（接入 JaCoCo/coverage.py 的数据）
- **Duplications**：重复代码比例

### 扫描链路：Scanner → SonarQube Server → Quality Gate

```text
代码 + 测试覆盖率报告
  → sonar-scanner 把源码和报告推给 SonarQube Server
    → 服务端按规则分析，计算各维度指标
      → 对照 Quality Gate 阈值判定 PASS / FAIL
        → CI 取这个结果决定阻断与否（见 [[质量门禁设计与失败即阻断]]）
```

### SonarQube 与本地 lint 的区别

`flake8`/`ruff` 是快、轻、本地的风格/基础错误检查；SonarQube 是重、集中、跨项目的历史趋势和深度分析（含跨文件数据流、安全规则）。两者不冲突：本地 lint 做快反馈，SonarQube 做门禁级把关。

## 用法

### 一、用 sonar-scanner 扫 Python 项目

```bash
# 安装 scanner 后，在项目根目录放 sonar-project.properties
```

```properties
# sonar-project.properties
sonar.projectKey=qa-auto-api
sonar.projectName=接口自动化项目
sonar.sources=app,tests
sonar.sourceEncoding=UTF-8

# 语言
sonar.python.coverage.reportPaths=coverage.xml
sonar.python.xunit.reportPath=junit.xml

# 排除不需要扫的
sonar.exclusions=**/migrations/**,**/venv/**

# 服务器地址（CI 里用环境变量/凭据注入，不要硬编码）
sonar.host.url=https://sonar.example.com
sonar.token=${SONAR_TOKEN}
```

```bash
# 生成覆盖率报告（coverage.py）
pytest --cov=app --cov-report=xml:coverage.xml --junitxml=junit.xml

# 扫描
sonar-scanner
```

### 二、在 Jenkins 里集成

```groovy
stage('SonarQube 扫描') {
    steps {
        withSonarQubeEnv('sonar-server') {        // 在 Jenkins 系统配置里登记的服务器
            sh 'pytest --cov=app --cov-report=xml:coverage.xml --junitxml=junit.xml'
            sh 'sonar-scanner'
        }
    }
}

stage('质量门禁') {
    steps {
        // 等待 SonarQube 返回 Quality Gate 结果，FAIL 则阻断
        timeout(time: 5, unit: 'MINUTES') {
            waitForQualityGate abortPipeline: true
        }
    }
}
```

`waitForQualityGate abortPipeline: true` 是关键——它把 SonarQube 的判定结果变成流水线成败，实现「扫描不过就阻断」。

### 三、在 GitHub Actions 里集成

```yaml
jobs:
  sonar:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0            # Sonar 需要完整历史做 new code 分析
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r requirements.txt && pytest --cov=app --cov-report=xml
      - uses: SonarSource/sonarcloud-github-action@master
        env:
          SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}   # 走 secrets，见 [[Jenkins 凭据管理]]
```

### 四、Quality Gate 阈值配置

在 SonarQube 后台设门禁，例如：

```text
新代码（New Code）覆盖率 >= 80%
新增 Bugs == 0
新增 Vulnerabilities == 0
新增 Code Smells 不增长
```

重点看 **New Code（新增代码）** 而非全量——对存量大项目，全量门禁永远过不了；聚焦「这次改动不引入新问题」更现实。

## 踩坑

1. **`fetch-depth: 0` 没设导致 new code 分析失效**。Sonar 的「新代码」对比需要完整 git 历史，浅克隆下它判断不了哪些是新增改动。CI 里 checkout 要 `fetch-depth: 0`。

2. **coverage 报告路径对不上**。配了 `sonar.python.coverage.reportPaths=coverage.xml`，但 pytest 生成的是 `coverage.xml` 在当前目录没问题，有时却在其他路径，Sonar 读不到，覆盖率显示 0。确认路径与生成位置一致。

3. **token 硬编码进 `sonar-project.properties`**。该文件常进仓库，token 泄露。用 `sonar.token` 走环境变量或 CI secrets（见 [[Jenkins 凭据管理]]）。

4. **全量门禁阈值太高永远红**。存量项目坏味道几万条，门禁永远 FAIL，团队放弃。改用 New Code 视角，只卡「本次新增」。

5. **`waitForQualityGate` 没有 timeout 卡住**。Sonar 服务慢或挂了，这个 step 一直等。务必套 `timeout`，否则占节点。

6. **只扫 main 不扫 PR**。没在 PR 触发扫描，合并后才发现引入漏洞。配置 PR 装饰（GitHub/GitLab 的 PR comment）实时反馈。

7. **把 Sonar 当唯一质量保障**。Sonar 是静态分析，不跑业务，发现不了逻辑错误和集成问题。它和单测、自动化是互补关系，不是替代（见 [[质量门禁设计与失败即阻断]]）。

8. **扫描范围太大拖慢**。把 `node_modules`/`venv`/`migrations` 都扫了，分析慢且噪音多。用 `sonar.exclusions` 排除不该扫的。

9. **本地 lint 和 Sonar 规则重复且冲突**。ruff 报的和 Sonar 报的重叠，开发者两边改。约定：本地 lint 管风格快反馈，Sonar 管深度/安全，规则集对齐避免重复噪音。

10. **`sonar.sources` 包含测试代码导致覆盖率算错**。测试文件被当成源码统计，覆盖率虚高。sources 只放业务代码，测试单独用 `sonar.tests`。

## 面试怎么答

**Q：SonarQube 在 CI 里起什么作用，和你自己写的单测有什么关系？**

A：它和单测是互补的。单测是动态执行，验证功能是否按预期；SonarQube 是静态分析，不跑代码，靠解析语法树和数据流找出空指针隐患、安全漏洞、坏味道、重复代码这些单测发现不了的问题。在 CI 里我一般先跑单测生成覆盖率报告，再用 sonar-scanner 把源码和报告推到 SonarQube 服务端，然后用 `waitForQualityGate` 把它的判定结果变成流水线成败，实现「扫描不过就阻断」。它是质量门禁里「代码健康」那一关。

**Q：SonarQube 的门禁怎么设才合理？**

A：核心是看「新增代码」而不是全量。存量大的项目全量门禁永远过不了，团队会放弃。我聚焦 New Code：这次改动新增的 Bugs 和 Vulnerabilities 必须是 0，新增代码覆盖率不低于 80%，坏味道不增长。这样既不给团队制造无法完成的任务，又能保证「每次提交不引入新问题」。另外扫描要在 PR 阶段就跑，配合代码平台的 PR 装饰实时反馈，而不是合并后才发现漏洞。

**Q：SonarQube 能替代测试吗？**

A：不能，它们是不同维度。Sonar 是静态的，不执行业务逻辑，发现不了「逻辑算错」「接口联调挂」这类问题；这些得靠单测和接口/UI 自动化。我把它定位成「代码健康门禁」——管代码臭不臭、有没有安全漏洞，和单测的「功能对不对」、自动化的「端到端通不通」三者一起构成完整的质量门禁。三者互补，缺一不可。

## 参考

- [SonarQube 官方文档](https://docs.sonarqube.org/latest/)
- [SonarScanner 使用](https://docs.sonarqube.org/latest/analysis/scan/sonarscanner/)
- [Quality Gate 概念](https://docs.sonarqube.org/latest/user-guide/quality-gates/)
- 相关笔记：[[质量门禁设计与失败即阻断]]、[[Jenkins 凭据管理]]、[[GitHub Actions workflow 结构与触发事件]]
