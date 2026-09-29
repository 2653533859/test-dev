---
created: 2026-07-31
tags: [项目实战/持续集成]
---

# Jenkinsfile 多阶段流水线设计

> 把流水线写进仓库、按触发源跑不同深度的测试，并保证「无论成败都发通知、都清现场」。

## 概念

### 为什么是 Pipeline as Code

Jenkins 支持在 GUI 里点点点配 Job，但团队规模一上来就撑不住：

- 改了什么、谁改的、为什么改，**全无记录**；出问题只能靠回忆。
- 无法 Code Review，一个人手滑改错参数，全组的构建跟着挂。
- 迁移或重建 Jenkins 时，几十个 Job 的配置只能靠人肉对着截图重配。

Jenkinsfile 放进被测仓库后，流水线变更和代码变更走同一套流程：提 PR、review、合入、可回滚。

### 声明式 vs 脚本式

| 类型 | 特点 | 适用 |
|------|------|------|
| **Declarative（选定）** | `pipeline { }` 结构固定，有 `post`、`options`、`when` 等语法糖，可读性好 | 绝大多数场景 |
| Scripted | `node { }` 纯 Groovy，灵活但没有护栏 | 需要复杂动态编排时 |

声明式里遇到需要逻辑判断的地方，用 `script { }` 块局部逃生即可，不必整体退回脚本式。

### 阶段划分原则

一个阶段只做一件事，且**失败时能从阶段名直接判断问题归属**：

```text
Checkout（代码/缓存）→ Lint（静态检查）→ Deploy（起被测服务）
  → Test（并行分片执行）→ Gate（质量门禁）→ Report（报告归档）
  → post always（通知 + 清理）
```

看到「Deploy 挂了」就知道是环境问题不用叫开发，看到「Gate 挂了」就知道是用例真失败——**阶段名本身就是一次故障分类**。

## 用法

### 完整骨架

```groovy
pipeline {
    agent {
        docker {
            image 'registry.internal/qa/pytest-runner:3.11'
            args '-v /var/run/docker.sock:/var/run/docker.sock -v pip-cache:/root/.cache/pip'
        }
    }

    options {
        timeout(time: 60, unit: 'MINUTES')       // 兜底，防止 hang 死占用 agent
        buildDiscarder(logRotator(numToKeepStr: '30'))
        disableConcurrentBuilds(abortPrevious: true)  // 同分支新构建自动取消旧的
        timestamps()
    }

    environment {
        TZ = 'Asia/Shanghai'
        TEST_ENV = "${params.ENV ?: 'test'}"
        // 凭据以环境变量注入，日志中自动掩码
        TEST_PASSWORD = credentials('qa-test-account-password')
    }

    triggers {
        cron(env.BRANCH_NAME == 'main' ? 'H 2 * * *' : '')   // 只有主干配夜间定时
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                sh 'pip install -q -r requirements.txt'
            }
        }

        stage('Lint') {
            steps {
                sh 'ruff check . && python scripts/check_case_naming.py'
            }
        }

        stage('Deploy') {
            steps {
                sh 'docker compose -f deploy/docker-compose.test.yml up -d --wait'
                sh 'python scripts/wait_health.py --timeout 120'   // 轮询健康检查
            }
        }

        stage('Test') {
            steps {
                script {
                    // 分层触发：PR 只跑冒烟，主干跑接口全量，定时跑全部
                    def scope = env.CHANGE_ID ? "-m smoke"
                              : (env.BRANCH_NAME == 'main' ? "-m 'smoke or api'" : "")
                    sh """
                        pytest ${scope} -n 4 --dist loadfile \
                            --reruns 1 --reruns-delay 2 \
                            --alluredir=allure-results \
                            --junitxml=reports/junit.xml
                    """
                }
            }
        }

        stage('Gate') {
            steps {
                sh 'python scripts/gate.py --junit reports/junit.xml --min-pass-rate 100'
            }
        }

        stage('Report') {
            steps {
                allure includeProperties: false, results: [[path: 'allure-results']]
            }
        }
    }

    post {
        always {
            sh 'docker compose -f deploy/docker-compose.test.yml down -v || true'
            script { notifyWeCom(currentBuild.currentResult) }
            cleanWs()
        }
    }
}
```

### 几个关键写法的理由

**`--dist loadfile` 而不是默认的 `load`**：默认按用例分发，同一个文件的用例可能被拆到不同 worker，而串联型用例（下单 → 支付 → 退款）依赖同文件内的执行顺序和共享 fixture。`loadfile` 保证同文件的用例在同一个 worker 上跑。

**`disableConcurrentBuilds(abortPrevious: true)`**：开发连续推三次代码时，前两次构建已经没有意义，自动取消省资源，也避免同分支多构建抢环境。

**`cron('H 2 * * *')` 里的 `H`**：Jenkins 特有语法，把任务散列到该小时内的随机分钟。写 `0 2 * * *` 会导致所有定时 Job 在 02:00 整点同时启动，master 直接被压垮。

**`docker compose down` 后面的 `|| true`**：清理步骤本身失败不应该影响构建结论。但注意这个技巧**只能用在清理上**，用在测试命令上就是灾难（见踩坑 1）。

## 踩坑

1. **`pytest ... || true` 让门禁彻底失效**：早期为了让后面的报告步骤能执行，在测试命令后加了 `|| true`，结果退出码永远是 0，Jenkins 判定构建成功，用例全挂也照样合入。**正确做法**是保留退出码，把报告生成放进 `post { always }`。这个 bug 潜伏了三周才被发现，因为「构建一直是绿的」看起来太正常了。

2. **凭据被打进构建日志**：`sh "curl -H 'token: ${TOKEN}'"` 中 Jenkins 会对已知凭据做掩码，但如果做了字符串拼接或 base64 编码，掩码就失效了。原则是**凭据只在需要它的进程里以环境变量存在，绝不出现在任何 echo/日志里**。另外 `credentials()` 绑定 username/password 类型时会自动生成 `XXX_USR` 和 `XXX_PSW` 两个变量，容易忽略。

3. **workspace 不清理，磁盘打满**：`allure-results` 每次几十 MB，一个月后 agent 磁盘满。报错还很误导——出现在 `pip install` 阶段报 `No space left on device`，第一反应是去查 pip。`cleanWs()` + `buildDiscarder` 双保险。

4. **没有 `timeout`，一次 hang 死占用 agent 一整夜**：某次测试环境无响应，用例卡在没设超时的 HTTP 请求上，构建挂了 9 个小时，后续所有构建排队。`options { timeout(...) }` 是必配项。

5. **Docker 容器时区 UTC**：报告时间差 8 小时，且时间相关断言在早上 8 点前必挂。`ENV TZ=Asia/Shanghai`（详见 [[Docker 化测试执行环境]]）。

6. **`when` 表达式在 `stages` 里判断 `env.CHANGE_ID` 拼写错误不报错**：Groovy 访问不存在的 `env` 属性返回 `null` 而不是抛异常，写错变量名就是「条件永远为假」，静默跳过整个阶段。调试时先 `echo` 出来确认。

7. **共享库版本没锁**：用了 `@Library('qa-shared')`，共享库改了个函数签名，所有仓库的流水线同时挂。改成 `@Library('qa-shared@v1.3')` 锁版本。

8. **Allure 趋势图每次清零**：需要把上次构建的 history 目录拷进本次 results。Jenkins 的 Allure 插件会自动处理，但自建报告服务时要手动 `cp -r`。

## 面试怎么答

**Q：讲一下你们的 CI 流水线是怎么设计的？**

A：Jenkinsfile 进仓库做 Pipeline as Code，声明式语法。阶段是 Checkout、Lint、部署待测服务、Test、质量门禁、报告归档，最后 `post always` 发通知和清理。核心设计是**按触发源分层**：PR 只跑 4 分钟冒烟保证反馈速度，合入主干跑接口全量，夜间跑含 UI 的完整回归。执行环境用 Docker 固化，避免 agent 环境漂移。

**Q：为什么要分层触发？**

A：因为第一版所有触发源都跑全量，40 分钟。开发等不起，开始在 commit message 里加 `[skip ci]` 绕过——CI 被绕过就等于没有 CI。分层之后 PR 阶段 9 分钟出结果，接受度立刻不一样了。这件事的教训是：**流水线的设计约束不只是技术，还有使用者的耐心阈值**。

**Q：`post` 的几种条件有什么区别？**

A：`always` 无论结果都执行，用于通知和清理；`success` / `failure` 分别在成功失败时执行；`unstable` 对应测试失败但构建本身没崩的状态；`changed` 在本次结果与上次不同时触发，适合做「从红转绿」的恢复通知。通知和清理**必须放 always**，放在普通 stage 里一旦前面抛异常就会被跳过，出现「构建挂了但群里没消息」的静默失败——这比不接 CI 更危险，因为大家默认没消息就是没问题。

**Q：怎么保证流水线本身的可维护性？**

A：Jenkinsfile 进仓库跟着 code review 走；公共逻辑抽到 Shared Library 并锁版本，避免共享库一改所有流水线连坐；阶段划分保证从阶段名能直接判断故障归属；关键参数（超时、并行度、门禁阈值）集中在 `environment` 和 `options` 里而不是散落在 shell 命令中。

## 参考

- Jenkins Pipeline 语法：`https://www.jenkins.io/doc/book/pipeline/syntax/`
- Shared Library：`https://www.jenkins.io/doc/book/pipeline/shared-libraries/`
- 相关笔记：[[11-持续集成]]、[[pytest-xdist 并行执行]]、[[pytest 标记与用例筛选]]
- 同项目：[[质量门禁与失败通知策略]]、[[Docker 化测试执行环境]]
- 所属项目：[[CI 流水线打通]]
