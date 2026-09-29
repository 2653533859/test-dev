---
created: 2026-07-31
tags: [持续集成/Jenkins]
---

# Jenkins 参数化构建与触发方式

> 触发决定「什么时候跑」，参数决定「这次跑什么」。两者配合，一条流水线才能既自动又灵活。

## 概念

### 为什么需要参数化

写完流水线后立刻会遇到一个矛盾：自动化用例可能只想跑 `smoke`，也可能想跑全量回归；可能打测试环境，也可能打预发；可能想用最新的代码，也可能想用某个历史 tag 验证 bug。如果每换一个场景就改一次 Jenkinsfile 再提交，效率太低。

参数化构建让「运行配置」从代码里剥离出来，变成**运行流水线时由人/系统填入的值**。Jenkinsfile 里用 `parameters` 声明有哪些参数，运行时在 UI 勾选或填入，参数值通过全局变量 `params.XXX` 访问。

### 为什么需要多种触发

手动点「Build Now」只适合调试。真正落地的 CI 必须满足：**代码一推就自动跑、定时回归自动跑、依赖更新自动跑**。Jenkins 的触发方式本质是「谁来告诉 Jenkins 该跑了」：

- 用户手动点（调试用）
- 代码平台通过 Webhook 推（最常见）
- 定时（cron，适合夜间全量）
- 上游任务成功（流水线级联）
- SCM 轮询（最不推荐，已逐渐被 Webhook 取代）

触发和参数是正交的两件事：触发器可以自动带上参数（比如 Webhook 根据 PR 标题决定 `MARKERS`）。

## 用法

### 一、参数类型

```groovy
pipeline {
    agent any
    parameters {
        choice(name: 'ENV', choices: ['test', 'staging', 'prod'], description: '目标环境')
        string(name: 'MARKERS', defaultValue: 'smoke', description: 'pytest -m 表达式')
        booleanParam(name: 'CLEAN_DATA', defaultValue: true, description: '跑完清理测试数据')
        password(name: 'ADMIN_PWD', defaultValue: '', description: '管理员密码（界面打码）')
        text(name: 'TEST_PLAN', defaultValue: '', description: '多行测试计划说明')
        file(name: 'EXTRA_CASES', description: '上传额外用例 zip（少用，注意存储）')
    }
    stages {
        stage('打印参数') {
            steps {
                echo "ENV=${params.ENV}"
                echo "MARKERS=${params.MARKERS}"
                echo "CLEAN_DATA=${params.CLEAN_DATA}"
            }
        }
    }
}
```

要点：

- `choice` 是下拉单选，`string` 是单行文本，`booleanParam` 是勾选框
- `password` 在界面和日志里打码，但**本质上仍是明文变量**，真正的密钥请用 `credentials()`（见 [[Jenkins 凭据管理]]）
- 新增/删除参数后，**第一次构建必须手动点一次**（Jenkins 在构建时才更新参数定义），否则 `params.新参数` 是 null

### 二、多种触发方式

```groovy
pipeline {
    agent any
    triggers {
        // GitLab / GitHub Webhook 推送触发（推荐）
        gitlab(
            triggerOnPush: true,
            triggerOnMergeRequest: true,
            branchFilterType: 'All'
        )
        // 定时：每天凌晨 2 点跑全量回归（注意时区是 Jenkins 服务器时区）
        cron('0 2 * * *')
        // 轮询 SCM：每 5 分钟看一次仓库（不推荐，用 Webhook 替代）
        pollSCM('H/5 * * * *')
        // 上游任务成功触发：上游构建完再跑
        upstream(
            upstreamProjects: 'deploy-test-env',
            threshold: hudson.model.Result.SUCCESS
        )
    }
    stages {
        stage('按需跑') {
            when {
                // 定时触发时强制全量，PR 触发时只跑 smoke
                expression { currentBuild.getBuildCauses('hudson.triggers.TimerTrigger$TimerTriggerCause') }
            }
            steps { echo '这是定时触发，跑全量回归' }
        }
    }
}
```

### 三、Webhook 的接线

```text
开发者 push
  → 代码平台（GitLab/GitHub）按事件发 HTTP POST 到 /jenkins/gitlab-webhook/
    → Jenkins 收到后匹配对应 job 的触发器规则
      → 启动构建，并从 payload 解析出分支、提交人、PR 号等
```

容易忽略的点：

- Webhook URL 要带 `/jenkins/generic-webhook-trigger/` 这类具体路径，取决于装了哪个插件
- 多分支场景用 **Multibranch Pipeline + Git 插件**，它内置了分支级 Webhook 路由，比手写 `gitlab()` 触发器省心（见 [[Jenkins 架构与 Freestyle、Pipeline 选型]]）
- 网络不通时（内网 Jenkins），代码平台需要能访问到它，常用「反向代理 + 公网域名」或「内网穿透」方案

### 四、用 Generic Webhook Trigger 把参数接进来

```groovy
properties([
    pipelineTriggers([
        [
            $class: 'GenericTrigger',
            genericVariables: [
                [key: 'PR_TITLE', value: '$.pull_request.title'],
                [key: 'BRANCH',   value: '$.ref.replace("refs/heads/","")']
            ],
            causeString: 'Triggered by webhook: $PR_TITLE',
            token: 'my-secret-token'   // 调用方 URL 里带 ?token=my-secret-token
        ]
    ])
])
```

这样外部系统（比如测试平台）可以用一个 `curl` 带着参数触发 Jenkins，非常适合把自动化接到内部工具链上。

## 踩坑

1. **改了 `parameters` 却读不到新参数**。Jenkins 的参数定义是在「构建时」从 Jenkinsfile 刷新的，新增参数后必须手动触发一次构建，下一次才能用。CI 自动触发时读到的还是旧定义，`params.新参数` 为 null 报错。

2. **`cron` 时区坑**。Jenkins 的 cron 用的是**服务器本地时区**，容器里常常是 UTC，你以为的「北京时间凌晨 2 点」其实是 UTC 2 点。要么在 `cron` 里换算，要么在 Jenkins 系统设置里把时区改成 `Asia/Shanghai`。

3. **Webhook 触发了但没跑对应分支**。普通的 Pipeline job 不知道分支信息，Webhook 进来只会触发默认分支。多分支请用 Multibranch，或在 `when` 里用 `expression { env.GIT_BRANCH == 'origin/xxx' }` 过滤。

4. **`pollSCM` 轮询拖垮仓库**。设成 `*` 每分钟轮询会在大仓上制造大量请求。Webhook 才是正解；如果只能用轮询，至少设成 `H/15 * * * *`（H 表示错峰随机分钟）。

5. **参数默认值写死导致误跑生产**。`ENV` 默认 `prod` 太危险。约定：默认永远是最低危的环境（`test`），要跑高危环境必须人主动选；更严格地，高危环境的 stage 再叠加 `input` 人工确认（见 [[Jenkinsfile Pipeline 语法]]）。

6. **`booleanParam` 是字符串还是布尔**。在 `params` 里它是布尔类型，但一旦在字符串里插值 `echo "${params.CLEAN_DATA}"` 会变成 `true/false` 字符串，传给 shell 后要自己再判断。

7. **上游触发依赖链循环**。A 的失败触发 B 重试，B 的成功又触发 A……形成死循环。级联触发要画清楚 DAG，避免环。

8. **Generic Webhook 的 token 泄露**。URL 里的 token 等同于免密触发权限，应走 HTTPS 且 token 存于凭据，不要硬编码在调用方脚本里明文。

9. **手动触发时没有参数值**。第一次构建前参数还没初始化，手动点「Build with Parameters」会看到空表单；填一次即可，后续有默认值。

10. **`when` 配合 `currentBuild.getBuildCauses()` 返回的是列表**。判断定时触发要检查列表是否非空，而非 `== true`，否则表达式永远假。

## 面试怎么答

**Q：Jenkins 有哪些触发方式，你推荐哪种？**

A：主要有手动、Webhook、定时 cron、轮询 SCM、上游触发这几种。实际落地我首推 Webhook——开发者一推代码，代码平台就 POST 给 Jenkins，实时性最好，也是真正的持续集成。定时 cron 我用来跑夜间全量回归，补偿「白天只跑 smoke」的覆盖盲区。轮询 SCM 基本不推荐，它在仓库上制造大量无谓请求，能用 Webhook 就别用轮询。多分支场景我直接用 Multibranch Pipeline，它内置分支级 Webhook 路由，比手写触发器省心。

**Q：为什么需要参数化构建？**

A：因为「跑什么」不应该写死在代码里。比如我想用同一份 Jenkinsfile 既跑 smoke 又跑全量回归，既打测试环境又打预发，这就需要把环境、pytest 的 markers、是否清理数据这些变成运行参数。声明在 `parameters` 里，运行时由人或外部系统填入，代码里通过 `params.XXX` 读取。一个注意点是新增参数后必须手动构建一次 Jenkins 才会刷新参数定义，否则读到的会是 null。真正常敏感的信息我不放参数，而是走凭据。

**Q：参数和凭据怎么配合用？**

A：参数放「运行配置类」的、非机密的值，比如环境名、用例分组、是否清数据。机密信息比如 token、密码不放参数，尤其是 `string` 和 `password` 参数本质仍是明文，日志和内存里都能看到；机密一律走 `environment { XXX = credentials('id') }`，Jenkins 会在日志里自动打码，存于凭据系统。外部系统带 token 触发时，那个 token 也应存凭据而不是硬编码在调用脚本。

## 参考

- [Jenkins 参数化构建文档](https://www.jenkins.io/doc/book/pipeline/syntax/#parameters)
- [Pipeline Triggers 文档](https://www.jenkins.io/doc/book/pipeline/syntax/#triggers)
- 相关笔记：[[Jenkins 架构与 Freestyle、Pipeline 选型]]、[[Jenkinsfile Pipeline 语法]]、[[Jenkins 凭据管理]]、[[Jenkins Allure 报告与构建后通知]]
