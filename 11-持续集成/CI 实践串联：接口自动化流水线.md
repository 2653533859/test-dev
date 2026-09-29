---
created: 2026-07-31
tags: [持续集成/实践]
---

# CI 实践串联：接口自动化流水线

![[assets/ci-practice-e2e.svg]]
*图示：开发者 push → 代码平台 webhook 触发 Jenkins → compose 起被测环境 → 容器内跑 pytest → 生成 Allure + JUnit → 门禁判定 → 钉钉通知。一条链路把本模块所有知识点串起来。*

## 概念

### 为什么需要「实践串联」

前面每一篇都是一个点：Git 怎么协作、Jenkins 怎么写、Docker 怎么起环境、Allure 怎么出报告、门禁怎么拦。真实项目里它们是**一条链路**——任何一环断了，自动化就落不了地。这篇把前面各知识点串成一条「提交代码自动触发接口自动化 + Allure 报告 + 钉钉通知」的完整流水线，作为本模块的收口。

### 一条落地链路长什么样

```text
开发者 push / 提 PR
  → 代码平台发 webhook
    → Jenkins 触发 Multibranch Pipeline
      → cleanWs + checkout
      → docker compose up -d --wait 起被测环境（MySQL/Redis/被测应用）
      → 容器内跑 pytest（多模块并行/分片）
      → 生成 allure-results + junit.xml
      → 质量门禁：解析通过率、SonarQube（见 [[质量门禁设计与失败即阻断]]、[[SonarQube 静态扫描接入]]）
      → post：生成 Allure 报告、归档、docker compose down -v、钉钉通知（见 [[Jenkins Allure 报告与构建后通知]]）
```

### 关键设计取舍

- **环境用 Docker 固化**：被测环境写成 `docker-compose.test.yaml`，任何人/任何 runner 上拉起都一致，消灭「环境漂移」
- **测试在容器内跑**：自动化框架打成镜像（见 [[Dockerfile 编写与镜像构建优化]]），runner 无需预装 Python
- **门禁硬阻断**：通过率/覆盖率不达标则 `error`，并设为 required status check（见 [[质量门禁设计与失败即阻断]]）
- **通知用 changed**：只在状态翻转时钉钉通知，避免刷屏

## 用法

### 一、被测环境的 compose

```yaml
# docker-compose.test.yaml
services:
  mysql:
    image: mysql:8.0
    environment: { MYSQL_ROOT_PASSWORD: test123, MYSQL_DATABASE: testdb }
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-ptest123"]
      interval: 5s
      retries: 10
  app:
    build: ./app
    depends_on: { mysql: { condition: service_healthy } }
    environment: { DB_HOST: mysql }
    ports: ["8080:8080"]
```

### 二、完整 Jenkinsfile（串联版）

```groovy
@Library('qa-pipeline-lib@v1.2') _     // 复用共享库，见 [[Jenkinsfile Pipeline 语法]]

pipeline {
    agent { label 'linux && api' }

    options {
        timeout(time: 30, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '30'))
        disableConcurrentBuilds()
        timestamps()
        ansiColor('xterm')
    }

    parameters {
        choice(name: 'ENV', choices: ['test', 'staging'], description: '环境')
        string(name: 'MARKERS', defaultValue: 'smoke', description: 'pytest -m')
    }

    environment {
        LANG = 'C.UTF-8'
        LC_ALL = 'C.UTF-8'
        PYTHONIOENCODING = 'utf-8'
        BASE_URL   = "http://app:8080"          // compose 内部网络访问
        API_TOKEN  = credentials('qa-api-token') // 凭据注入，见 [[Jenkins 凭据管理]]
        DINGTALK   = credentials('dingtalk-webhook')
    }

    stages {
        stage('准备') {
            steps {
                cleanWs()
                checkout scm
            }
        }

        stage('启动被测环境') {
            steps {
                sh 'docker compose -f docker-compose.test.yaml up -d --wait'
            }
        }

        stage('接口测试') {
            steps {
                script {
                    def code = sh(
                        script: """
                            docker run --rm --network ${COMPOSE_NETWORK} \
                              -v \$(pwd):/work -w /work qa-auto:1.0 \
                              pytest tests/api -m "${params.MARKERS}" \
                                --base-url="${BASE_URL}" \
                                --alluredir=allure-results --junitxml=junit.xml -v
                        """,
                        returnStatus: true
                    )
                    if (code == 1) unstable("有用例失败")
                    else if (code > 1) error("pytest 执行异常，退出码 ${code}")
                }
            }
        }

        stage('质量门禁') {
            parallel {
                stage('通过率门禁') {
                    steps {
                        script {
                            def pass = sh(script: 'python3 calc_pass_rate.py', returnStdout: true).trim() as Double
                            if (pass < 95) error("通过率 ${pass}% 低于 95%")
                        }
                    }
                }
                stage('SonarQube') {
                    steps {
                        withSonarQubeEnv('sonar-server') { sh 'sonar-scanner' }
                        timeout(time: 5, unit: 'MINUTES') {
                            waitForQualityGate abortPipeline: true
                        }
                    }
                }
            }
        }
    }

    post {
        always {
            allure includeProperties: false, results: [[path: 'allure-results']]
            junit allowEmptyResults: true, testResults: 'junit.xml'
            archiveArtifacts artifacts: 'logs/**', allowEmptyArchive: true
            sh 'docker compose -f docker-compose.test.yaml down -v || true'   // 清环境防泄漏
            cleanWs()
        }
        changed {
            // 状态翻转才钉钉通知，避免刷屏（见 [[Jenkins Allure 报告与构建后通知]]）
            script {
                def status = currentBuild.currentResult
                sh "curl -s -X POST -H 'Content-Type: application/json' -d '{\"msgtype\":\"markdown\",\"markdown\":{\"title\":\"CI ${status}\",\"text\":\"任务 ${env.JOB_NAME} #${env.BUILD_NUMBER}: ${status}\\n${env.BUILD_URL}\"}}' \${DINGTALK}"
            }
        }
    }
}
```

### 三、把框架打成镜像（复用 Docker 篇）

```dockerfile
# Dockerfile.test —— 见 [[Docker 镜像与容器核心概念]] 的分层优化原则
FROM python:3.11-slim
WORKDIR /work
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["pytest"]
```

```bash
docker build -t qa-auto:1.0 -f Dockerfile.test .
```

### 四、让门禁真正生效（平台侧）

- GitLab/GitHub 把该 Jenkins job 设为 **required status check**
- 分支保护规则：CI 红 → 禁止合并
- 这一步是门禁生效的最后一公里（见 [[质量门禁设计与失败即阻断]]）

## 踩坑

1. **compose 网络名和测试容器网络名不一致**。pytest 容器用默认网络，被测 app 在 compose 自建网络，`BASE_URL=http://app:8080` 解析不到。让测试容器也连同一 compose 网络（或用 `--network` 指定）。

2. **`--wait` 永远等不到**。某 service 的 healthcheck 永远不通过（比如探测命令写错），`up --wait` 卡住直到流水线 timeout。healthcheck 命令要真能反映就绪，并给足 `retries`。

3. **测试容器挂载当前目录但权限不对**。bind mount 后容器内非 root 用户写不了宿主机目录，Allure 结果写不进去。对齐 uid 或测试容器也用 root（仅测试环境可接受）。

4. **post 里 `docker compose down` 失败把绿变红**。compose 文件或卷异常导致 down 失败，SUCCESS 变 FAILURE。清环境命令一律 `|| true`。

5. **门禁 `parallel` 里一个失败影响另一个**。通过率和 SonarQube 并行，SonarQube 慢导致整体卡。各自独立 `timeout`，且 `failFast false`。

6. **凭据在容器内取不到**。`credentials()` 注入的是宿主机 agent 的环境变量，但测试跑在 `docker run` 起来的容器里，变量没传进去。用 `-e` 把变量显式传进容器：`docker run -e API_TOKEN=$API_TOKEN ...`。

7. **Allure 报告点开 403**。Jenkins CSP 策略拦截了内联 JS。需在全局安全配置放宽 Content Security Policy（见 [[Jenkins Allure 报告与构建后通知]]）。

8. **没设 `disableConcurrentBuilds`，多分支抢同一环境**。两个 PR 同时触发，都起 `app:8080` 端口冲突。CI 单分支禁止并发，或多套用 `-p ci-<build>` 隔离（见 [[docker compose 编排测试环境]]）。

9. **钉钉通知 JSON 引号地狱**。直接在 Groovy 拼 JSON 再喂给 shell，双引号冲突发坏数据。写文件 + `curl -d @file.json`，或装钉钉插件。

10. **本地能跑、CI 红，靠「我机器上能跑」结案**。这是环境漂移典型症状，本篇用 Docker 固化环境正是治本。遇到先比镜像版本、依赖清单、系统库，而不是甩锅。

## 面试怎么答

**Q：讲讲你怎么把接口自动化接进 CI 的。**

A：一条完整链路是：开发者 push 或提 PR，代码平台发 webhook 触发 Jenkins 的 Multibranch Pipeline；先 cleanWs 加 checkout；然后用 `docker compose up -d --wait` 起一套被测环境，包括 MySQL、Redis 和被测应用，用 healthcheck 等它们真正就绪；测试框架我提前打成镜像，在容器里跑 pytest，通过 `--base-url` 连 compose 内部网络里的 app；跑完生成 allure-results 和 junit.xml；接着并行做质量门禁——解析通过率低于 95% 就 error 阻断，同时跑 SonarQube 扫描，门禁不过就 abort；最后 post 里生成 Allure 报告、归档日志、docker compose down 清环境，并用钉钉在状态翻转时通知。整套环境用 Docker 固化，谁跑都一样，消灭环境漂移。

**Q：这条流水线里最容易出问题的环节是什么？**

A：我认为是「环境准备与清理」和「门禁生效」两处。环境上，compose 的网络名和测试容器网络不一致会导致连不上被测服务，healthcheck 写错会让 `--wait` 一直卡到超时，这两点要靠正确的网络和就绪探测。门禁上，很多人流水线红了但 PR 照样能合并，因为忘了在代码平台把 CI 设为 required status check，门禁没真正拦人。还有清环境——post 里 `docker compose down` 如果没加 `|| true`，清理失败会把成功的构建变红。这些坑本质上都是「以为串起来就行，忽略了边界条件」。

**Q：为什么用 Docker 跑测试而不是直接在 runner 上装 Python？**

A：三个理由。一是环境一致性，镜像不可变，CI 和本地用同一份，彻底解决「我机器上能跑」。二是 runner 零预装，换机器、加新依赖都不用改 runner，扩节点成本极低。三是隔离，每次构建用新容器，避免上一次测试的残留污染。代价是要写好 Dockerfile 的分层缓存和 `.dockerignore`，否则构建慢、镜像大。对测试团队来说这个 trade-off 很划算。

## 参考

- [Jenkins Pipeline 文档](https://www.jenkins.io/doc/book/pipeline/)
- [Docker Compose 文档](https://docs.docker.com/compose/)
- [Allure 报告接入](https://docs.qameta.io/allure/)
- 相关笔记：[[Jenkinsfile Pipeline 语法]]、[[Docker 镜像与容器核心概念]]、[[Dockerfile 编写与镜像构建优化]]、[[docker compose 编排测试环境]]、[[质量门禁设计与失败即阻断]]、[[SonarQube 静态扫描接入]]、[[Jenkins 凭据管理]]、[[Jenkins Allure 报告与构建后通知]]
