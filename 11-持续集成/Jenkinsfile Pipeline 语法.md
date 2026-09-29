---
created: 2026-07-31
tags: [持续集成/Jenkins]
---

# Jenkinsfile Pipeline 语法

> Declarative Pipeline 的骨架只有五个词：`pipeline` / `agent` / `stages` / `steps` / `post`。剩下的都是在这五个位置上做文章。

![[assets/jenkins-pipeline-flow.svg]]
*图示：stage 顺序流转（含 parallel 并行块），任一 step 非零退出即中断；post 块无论成败都会执行，负责报告、清环境、通知。*

## 概念

### 为什么是声明式

Jenkins Pipeline 有两套语法：

- **Scripted**：`node { ... }`，本质是一段 Groovy 脚本，想写什么写什么
- **Declarative**：`pipeline { ... }`，结构固定，Jenkins 在**执行前**就能校验语法和结构

声明式的核心价值是**结构可预测**：Jenkins 提前知道有哪些 stage，所以能画出 Stage View、能在 Controller 重启后恢复、能在语法错时立刻报错而不是跑到一半崩。代价是灵活性受限——需要复杂逻辑时用 `script { }` 内嵌脚本式代码作为逃生舱。

**默认用声明式**，这不是风格问题，是可维护性问题。

### 骨架与执行顺序

```groovy
pipeline {
    agent { }        // 必需：在哪台机器上跑
    options { }      // 流水线级选项：超时、历史保留、并发控制
    environment { }  // 环境变量
    parameters { }   // 构建参数
    triggers { }     // 自动触发规则
    tools { }        // 自动安装并加入 PATH 的工具（jdk/maven/nodejs）

    stages {         // 必需：核心内容
        stage('名字') {
            agent { }        // 可选：覆盖顶层 agent
            when { }         // 可选：条件执行
            environment { }  // 可选：stage 级变量
            steps { }        // 必需：具体做什么
        }
    }

    post { }         // 可选但强烈建议：收尾
}
```

执行顺序：`parameters/triggers` 声明生效 → 分配 `agent` → 注入 `environment` → 按顺序执行 `stages` → **无论成败**执行 `post`。

### 关键机制：step 的失败判定

`sh 'command'` 的成功与否**完全由退出码决定**：0 是成功，非 0 就是失败，失败即中断当前 stage 和整条流水线。

这条规则决定了所有「质量门禁」的实现方式——让不达标的命令返回非零：

```groovy
sh 'pytest tests/ --cov-fail-under=80'   // 覆盖率不足 → pytest 退出码非 0 → 流水线红
```

反过来，想「失败也继续」有三种写法，语义完全不同：

```groovy
sh 'flake8 . || true'                              // 完全忽略，构建仍是 SUCCESS
catchError(buildResult: 'UNSTABLE', stageResult: 'FAILURE') {
    sh 'pytest tests/flaky'                        // 标记为 UNSTABLE（黄），继续跑
}
script {
    def code = sh(script: 'pytest tests/', returnStatus: true)  // 拿到退出码自己判断
    if (code == 1) { unstable('有用例失败') }
    else if (code > 1) { error('pytest 自身出错') }
}
```

第三种最适合测试场景：pytest 退出码 1 表示「有用例失败」，2 以上表示「pytest 自己崩了/参数错」，这两者应该区别对待。

## 用法

### 一、一条完整的接口自动化流水线

```groovy
pipeline {
    agent { label 'linux && api' }

    options {
        timeout(time: 30, unit: 'MINUTES')                              // 必配，防卡死
        buildDiscarder(logRotator(numToKeepStr: '30', artifactNumToKeepStr: '10'))
        disableConcurrentBuilds()                                       // 同一分支不并发，避免抢环境
        timestamps()                                                    // 日志加时间戳
        ansiColor('xterm')                                              // 保留 pytest 彩色输出
        skipDefaultCheckout()                                           // 关掉自动 checkout，自己控制
    }

    parameters {
        choice(name: 'ENV', choices: ['test', 'staging'], description: '测试环境')
        string(name: 'MARKERS', defaultValue: 'smoke', description: 'pytest -m 表达式')
        booleanParam(name: 'CLEAN_DATA', defaultValue: true, description: '跑完清理测试数据')
    }

    environment {
        BASE_URL   = "https://${params.ENV}.example.com"
        PYTHONPATH = "${WORKSPACE}"
        // 凭据注入，日志里会自动打码，见 [[Jenkins 凭据管理]]
        API_TOKEN  = credentials('qa-api-token')
    }

    stages {
        stage('准备') {
            steps {
                cleanWs()
                checkout scm
                sh '''
                    python3 -m venv .venv
                    . .venv/bin/activate
                    pip install -q -r requirements.txt
                    pip list | grep -E "pytest|requests|allure"
                '''
            }
        }

        stage('静态检查') {
            steps {
                sh '. .venv/bin/activate && ruff check .'
            }
        }

        stage('启动测试环境') {
            steps {
                sh 'docker compose -f docker-compose.test.yaml up -d --wait'
            }
        }

        stage('接口测试') {
            steps {
                script {
                    def code = sh(
                        script: """
                            . .venv/bin/activate
                            pytest tests/api -m "${params.MARKERS}" \
                                   --base-url="${BASE_URL}" \
                                   --alluredir=allure-results \
                                   --junitxml=junit.xml -v
                        """,
                        returnStatus: true
                    )
                    if (code == 1) {
                        // 有用例失败：标 UNSTABLE，让 post 还能生成报告
                        unstable("存在失败用例，详见 Allure 报告")
                    } else if (code > 1) {
                        error("pytest 执行异常，退出码 ${code}")
                    }
                }
            }
        }

        stage('质量门禁') {
            steps {
                script {
                    // 解析 junit.xml 算通过率，不达标直接 error 阻断
                    def pass = sh(
                        script: '''python3 - <<'PY'
import xml.etree.ElementTree as ET
r = ET.parse("junit.xml").getroot()
total = int(r.get("tests", 0)); fail = int(r.get("failures", 0)) + int(r.get("errors", 0))
print(round((total - fail) / total * 100, 2) if total else 0)
PY''',
                        returnStdout: true
                    ).trim() as Double

                    echo "本次通过率：${pass}%"
                    if (pass < 95) {
                        error("通过率 ${pass}% 低于门禁阈值 95%")
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
            sh 'docker compose -f docker-compose.test.yaml down -v || true'
        }
        failure  { echo '通知责任人：构建失败' }
        unstable { echo '通知责任人：有用例失败' }
        cleanup  { cleanWs() }
    }
}
```

### 二、agent 的几种写法

```groovy
agent any                                   // 任意可用节点
agent none                                  // 顶层不占节点，由各 stage 自己声明
agent { label 'linux && chrome' }           // 按 label，支持 && || !
agent {
    docker {
        image 'python:3.11-slim'
        args  '-v /root/.cache/pip:/root/.cache/pip -u root'
        label 'docker'                      // 在哪台宿主机起容器
        reuseNode true                      // 复用当前节点的 workspace
    }
}
agent {
    dockerfile {                            // 用仓库里的 Dockerfile 现场构建镜像
        filename 'Dockerfile.test'
        dir '.'
        additionalBuildArgs '--build-arg PY=3.11'
    }
}
agent {
    kubernetes {                            // K8s 动态 Pod
        yaml '''
apiVersion: v1
kind: Pod
spec:
  containers:
  - name: python
    image: python:3.11-slim
    command: ["sleep"]
    args: ["infinity"]
'''
    }
}
```

### 三、parallel：并行加速

```groovy
stage('并行测试') {
    parallel {
        stage('接口用例') {
            agent { label 'api' }
            steps { sh 'pytest tests/api --alluredir=r-api' }
            post { always { stash name: 'r-api', includes: 'r-api/**' } }
        }
        stage('UI 用例') {
            agent { label 'chrome' }
            steps { sh 'pytest tests/ui --alluredir=r-ui' }
            post { always { stash name: 'r-ui', includes: 'r-ui/**' } }
        }
        stage('契约测试') {
            agent { label 'api' }
            steps { sh 'pytest tests/contract --alluredir=r-ct' }
            post { always { stash name: 'r-ct', includes: 'r-ct/**' } }
        }
    }
}

stage('汇总报告') {
    agent { label 'api' }
    steps {
        unstash 'r-api'; unstash 'r-ui'; unstash 'r-ct'
        sh 'mkdir -p allure-results && cp -r r-*/* allure-results/'
    }
}
```

两个要点：

- **并行分支跑在不同节点 = 不同工作区**，产物必须 `stash`/`unstash` 传递
- 默认某个并行分支失败会终止其他分支，想让它们跑完用 `failFast false`（默认就是 false，写 `failFast true` 才是快速失败）

动态生成并行分支（用例按模块自动切分）：

```groovy
stage('动态并行') {
    steps {
        script {
            def modules = ['user', 'order', 'pay', 'coupon']
            def branches = [:]
            modules.each { m ->
                branches["test-${m}"] = {
                    sh "pytest tests/api/${m} --alluredir=allure-results/${m}"
                }
            }
            parallel branches
        }
    }
}
```

### 四、when：条件执行

```groovy
stage('只在 main 上部署') {
    when { branch 'main' }
    steps { sh './deploy.sh' }
}

stage('只在 PR 上跑门禁') {
    when { changeRequest() }
    steps { sh 'pytest -m smoke' }
}

stage('代码有变化才跑') {
    when { changeset "src/**" }
    steps { sh 'pytest tests/unit' }
}

stage('按参数决定') {
    when { expression { params.RUN_FULL_REGRESSION } }
    steps { sh 'pytest tests/ -m regression' }
}

stage('组合条件') {
    when {
        allOf {
            branch 'main'
            not { changeRequest() }
            environment name: 'DEPLOY_ENABLED', value: 'true'
        }
    }
    steps { sh './deploy.sh' }
}

stage('前面失败了也要跑') {
    when { expression { true } }
    // 默认前面失败后续 stage 会跳过；要强制执行加这个：
    options { skipStagesAfterUnstable() }   // 反向控制
    steps { echo '...' }
}
```

`when` 默认在**进入 agent 之后**求值，如果条件不满足还是会占用节点。加 `beforeAgent true` 可以先判断再分配节点：

```groovy
when {
    beforeAgent true          // 省节点资源
    branch 'main'
}
```

同理还有 `beforeInput true`、`beforeOptions true`。

### 五、input：人工审批

```groovy
stage('确认发布') {
    steps {
        script {
            def result = input(
                message: '确认发布到生产环境？',
                ok: '发布',
                submitter: 'release-manager,qa-lead',    // 只有这些人能点
                parameters: [
                    choice(name: 'STRATEGY', choices: ['灰度10%', '全量'], description: '发布策略')
                ]
            )
            env.DEPLOY_STRATEGY = result
        }
    }
}
```

**`input` 会一直占着 agent 等人来点**，这是很常见的资源浪费。两个解法：

```groovy
// 方案 1：把 input 放在 agent none 的 stage 里
stage('审批') {
    agent none
    steps { timeout(time: 4, unit: 'HOURS') { input message: '确认发布？' } }
}

// 方案 2：options 里加 beforeAgent
```

**永远给 `input` 套 `timeout`**，否则没人点的流水线会永远挂在队列里。

### 六、environment 与凭据

```groovy
environment {
    // 普通变量
    APP_VERSION = '1.4.0'
    // 引用其他变量
    FULL_NAME   = "app-${APP_VERSION}"
    // Shell 命令的输出
    GIT_SHORT   = "${sh(script: 'git rev-parse --short HEAD', returnStdout: true).trim()}"
    // 凭据：Secret text
    API_TOKEN   = credentials('qa-api-token')
    // 凭据：Username with password → 自动展开成 XXX_USR 和 XXX_PSW
    REGISTRY    = credentials('docker-registry')
}

steps {
    sh 'echo $REGISTRY_USR'      // 用户名
    sh 'echo $REGISTRY_PSW'      // 密码（日志中显示为 ****）
}
```

常用内置变量：

```text
${env.BUILD_NUMBER}    构建号
${env.BUILD_URL}       本次构建的 URL（通知里必带）
${env.JOB_NAME}        任务名
${env.WORKSPACE}       工作目录绝对路径
${env.GIT_COMMIT}      提交 SHA
${env.GIT_BRANCH}      分支名
${env.CHANGE_ID}       PR 号（Multibranch 下）
${env.CHANGE_AUTHOR}   PR 作者
```

### 七、post 的六种条件

```groovy
post {
    always   { }   // 总是执行 —— 清环境、生成报告放这里
    success  { }   // 本次成功
    failure  { }   // 本次失败
    unstable { }   // 测试有失败但没崩（junit/unstable() 触发）
    changed  { }   // 状态和上次不同（绿转红 / 红转绿）—— 通知的最佳时机
    fixed    { }   // 上次失败这次成功
    regression { } // 上次成功这次失败
    aborted  { }   // 被中止（超时/人工停止）
    cleanup  { }   // 最后执行，在所有其他 post 之后
}
```

`changed` 特别实用：只在状态翻转时通知，避免连续红灯天天刷屏（见 [[Jenkins Allure 报告与构建后通知]]）。

### 八、Shared Library：抽取复用逻辑

十条流水线都要「装依赖 + 跑 pytest + 出报告」，复制粘贴十份是灾难。抽成共享库：

```groovy
// 库仓库结构：vars/runPytest.groovy
def call(Map cfg = [:]) {
    def markers  = cfg.get('markers', 'smoke')
    def baseUrl  = cfg.get('baseUrl', 'https://test.example.com')
    def threshold = cfg.get('threshold', 95)

    sh """
        python3 -m venv .venv && . .venv/bin/activate
        pip install -q -r requirements.txt
        pytest tests -m "${markers}" --base-url="${baseUrl}" \
               --alluredir=allure-results --junitxml=junit.xml
    """
}
```

```groovy
// 业务流水线里
@Library('qa-pipeline-lib@v1.2') _

pipeline {
    agent { label 'api' }
    stages {
        stage('Test') {
            steps {
                runPytest(markers: 'smoke or p0', baseUrl: 'https://test.example.com')
            }
        }
    }
}
```

共享库带版本号（`@v1.2`），升级可控、可回滚。

## 踩坑

1. **Groovy 单引号和双引号的区别**。单引号是字面量，**不做变量插值**；双引号才会。

   ```groovy
   sh 'echo ${BASE_URL}'    // Groovy 不插值，交给 shell 展开 —— 通常这是对的
   sh "echo ${BASE_URL}"    // Groovy 先插值成实际值再交给 shell
   ```

   涉及**密码**时必须用单引号让 shell 自己展开，否则密码会被插值进命令行，出现在日志和 `ps` 输出里。

2. **`sh` 多行脚本每行是独立的？不是**。`sh '''...'''` 是一个脚本整体执行，但**每个 `sh` step 之间**是独立进程，`cd`、`source`、变量都不会跨 step 保留。

   ```groovy
   sh '. .venv/bin/activate'      // 这个 step 结束，venv 就失效了
   sh 'pytest tests/'             // 用的是系统 python，找不到包
   ```

   正确写法是放进同一个 `sh` 块，或者直接用 `.venv/bin/pytest` 绝对路径。

3. **`set -e` 与多行脚本**。Jenkins 的 `sh` 默认加了 `-xe`，任一行失败就整体失败。如果你希望某行失败继续，要显式 `|| true`。反过来，管道里的失败会被吞掉：

   ```groovy
   sh 'pytest tests/ | tee test.log'   // 退出码是 tee 的（0），pytest 失败被吞了！
   sh 'set -o pipefail; pytest tests/ | tee test.log'   // 正确
   ```

   这个坑非常隐蔽，很多「流水线绿了但用例其实失败了」都源于此。

4. **`when` 不生效**。`when { branch 'main' }` 在**非** Multibranch 的普通 Pipeline job 里拿不到分支信息，永远不匹配。要么用 Multibranch，要么改用 `when { expression { env.GIT_BRANCH == 'origin/main' } }`。

5. **并行 stage 之间文件不共享**。以为在同一台机器上，结果并行分支被调度到不同节点，`allure-results` 只收集到一部分。必须 `stash`/`unstash`。

6. **`post` 里的步骤也会失败**。`post { always { sh 'docker compose down' } }` 如果 compose 文件不存在会报错，把已经 SUCCESS 的构建变成 FAILURE。post 里的清理命令都要加 `|| true`。

7. **忘记 `timeout`，流水线挂死占用节点**。等待某个服务启动的循环写死了、`input` 没人点、pytest 卡在网络请求上——一个节点被占几天。**`options { timeout(...) }` 是必填项**。

8. **`script` 块里用 `def` 定义的变量在其他 stage 取不到**。`def` 是局部的，跨 stage 传值要用 `env.XXX = ...`（只能存字符串）。

9. **`environment` 里 `credentials()` 用在 `agent none` 的顶层会报错**。凭据绑定需要节点上下文，把它挪到具体 stage 的 `environment` 里。

10. **中文乱码**。Agent 的 locale 不对，pytest 输出的中文变成 `????`。在 `environment` 里设：

    ```groovy
    environment {
        LANG = 'C.UTF-8'
        LC_ALL = 'C.UTF-8'
        PYTHONIOENCODING = 'utf-8'
    }
    ```

11. **Jenkinsfile 改了但没生效**。Pipeline job 配置成了「Pipeline script」（写在界面上）而不是「Pipeline script from SCM」，改仓库里的文件当然没用。

## 面试怎么答

**Q：讲讲 Jenkinsfile 的基本结构。**

A：声明式 Pipeline 的骨架是 `pipeline` 包住 `agent`、`options`、`environment`、`parameters`、`stages`、`post`。`agent` 决定在哪台节点或哪个容器里跑；`options` 放超时、构建历史保留、禁止并发这些流水线级配置，其中 `timeout` 我认为是必填的，防止卡死占用节点；`environment` 定义变量，还能用 `credentials()` 注入凭据，日志里会自动打码；`stages` 里按阶段拆 `stage`，每个 stage 的 `steps` 是具体命令，stage 还能加 `when` 做条件执行、加自己的 `agent` 换节点；最后 `post` 是收尾，`always` 里放生成报告、清理环境，`failure` 里放通知。执行顺序是分配 agent → 注入环境 → 顺序跑 stages → 无论成败跑 post。

**Q：Pipeline 怎么做并行来加速？**

A：用 `parallel` 块，里面并列多个 stage，比如接口用例、UI 用例、契约测试三条并行跑，总时长从三者之和变成最长的那个。有两个必须注意的点：一是并行分支可能被调度到不同节点，工作区不共享，产物要用 `stash` 和 `unstash` 传递，否则汇总 Allure 报告时只能收到一部分；二是 `failFast` 参数，设 true 时一个分支失败会立刻终止其他分支，适合快速反馈，但测试场景我一般设 false，让所有用例都跑完，一次拿到完整的失败列表。用例多的时候我还会动态生成并行分支，按模块把 `pytest tests/api/<模块>` 切成 N 份，用 Groovy 循环构造 parallel 的 map。

**Q：`post` 有什么用，有哪些条件？**

A：`post` 是无论流水线成功失败都会执行的收尾块，这是它跟普通 stage 最大的区别——stage 失败后面的 stage 会被跳过，但 post 一定会跑。条件有 `always`、`success`、`failure`、`unstable`、`aborted`、`changed`、`fixed`、`regression`、`cleanup`。实际用法上，`always` 里放生成 Allure 报告、归档日志、`docker compose down` 清环境——尤其是清环境必须放这里，放在 stage 里的话测试失败就跳过了，容器会一直泄漏。`failure` 里放钉钉通知。`changed` 很实用，只在状态翻转时通知，避免连续红灯天天刷屏。有个坑是 post 里的命令失败也会让构建变红，所以清理类命令都要加 `|| true`。

**Q：怎么在流水线里实现「测试不通过就阻断」？**

A：本质是让 step 返回非零退出码。最简单的是直接让 pytest 自己失败，有用例挂了它就返回 1，流水线自然红。但实际项目里我需要更细的控制：pytest 退出码 1 是「有用例失败」，大于 1 是「pytest 自身出错」，这两者要区别对待，所以我用 `sh(returnStatus: true)` 拿到退出码，在 `script` 块里判断——退出码 1 就 `unstable()` 标黄让 post 还能生成报告，大于 1 就 `error()` 直接中断。通过率门禁是另加一个 stage，解析 junit.xml 算出通过率，低于阈值就 `error`。要注意一个隐蔽的坑：如果写成 `pytest | tee log`，退出码是 tee 的 0，pytest 失败会被吞掉，必须加 `set -o pipefail`。最后，Jenkins 报红只是信号，真正的阻断还要在代码平台上把这个 job 设成 required status check。

## 参考

- [Pipeline Syntax 官方参考](https://www.jenkins.io/doc/book/pipeline/syntax/)
- [Pipeline Steps Reference](https://www.jenkins.io/doc/pipeline/steps/)
- [Shared Libraries](https://www.jenkins.io/doc/book/pipeline/shared-libraries/)
- 相关笔记：[[Jenkins 架构与 Freestyle、Pipeline 选型]]、[[Jenkins 参数化构建与触发方式]]、[[Jenkins 凭据管理]]、[[Jenkins Allure 报告与构建后通知]]、[[质量门禁设计与失败即阻断]]
