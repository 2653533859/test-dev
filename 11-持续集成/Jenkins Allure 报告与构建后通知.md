---
created: 2026-07-31
tags: [持续集成/Jenkins]
---

# Jenkins Allure 报告与构建后通知

> 自动化跑完不给人看 = 白跑。Allure 解决「结果好看懂」，通知解决「结果有人看」。两者都在 `post` 里收尾。

## 概念

### 为什么是 Allure 而不是 JUnit 报告

Jenkins 原生能渲染 JUnit 的 `testResults`，但它只给出**用例通过/失败的数字和堆栈**，看不到请求/响应、截图、步骤、趋势。对测试开发来说，排查一个失败用例经常需要：这条用例发了什么请求、返回了什么、关联的 bug 单号是多少。

Allure 是一层**测试结果的展示框架**：你的测试框架（pytest/TestNG/JUnit）先把结果写成 Allure 的 JSON/附件，Jenkins 用 **Allure Plugin** 在构建后把这些结果聚合成一个带步骤、附件、趋势、分类的 HTML 报告。它和「测试框架」是解耦的——Allure 不管你用什么跑，只消费标准格式的结果目录。

### 为什么通知要放在 post

流水线失败但没人知道，等于没测。通知必须**无论成败都触发**，这正是 `post` 的职责（stage 失败会跳过后续 stage，但 post 一定跑）。更精细地，用 `post { changed }` 只在状态翻转时通知，避免连续红灯刷屏。

### 通知渠道

- **邮件**：`mail` step，适合正式归档，但年轻人不怎么看
- **钉钉/企业微信**：通过 webhook 机器人发群消息，测试团队最常用
- **Slack**：海外团队常用

## 用法

### 一、Allure 接入五步

```groovy
pipeline {
    agent { label 'api' }
    stages {
        stage('测试') {
            steps {
                sh '''
                    . .venv/bin/activate
                    pip install allure-pytest
                    pytest tests/api -m smoke --alluredir=allure-results -v
                '''
            }
            // 即便测试失败也要保留结果，方便看报告
            post { always { stash name: 'allure', includes: 'allure-results/**' } }
        }
    }
    post {
        always {
            // 1) 生成 Allure 报告（插件提供）
            allure includeProperties: false,
                  results: [[path: 'allure-results']],
                  reportBuildPolicy: 'ALWAYS'   // 失败也生成
            // 2) 同时保留 JUnit 原生结果（可选）
            junit allowEmptyResults: true, testResults: 'junit.xml'
            // 3) 归档日志等附件
            archiveArtifacts artifacts: 'logs/**,allure-results/**', allowEmptyArchive: true
        }
    }
}
```

前端测试代码侧（pytest 示例，让 Allure 记录步骤和附件）：

```python
import allure, requests

@allure.feature("登录")
@allure.story("正确密码登录")
def test_login():
    with allure.step("发送登录请求"):
        r = requests.post("/login", json={"u": "a", "p": "1"})
        allure.attach(r.text, name="响应体", attachment_type=allure.attachment_type.JSON)
    assert r.status_code == 200
```

### 二、Allure 的历史趋势

要看到「通过率随构建变化的曲线」，需要保留历史：

```groovy
allure(
    includeProperties: false,
    results: [[path: 'allure-results']],
    // 关键：把上一次的报告历史复制进来
    properties: [[key: 'allure.issues.tracker.pattern', value: 'https://jira/%s']]
)
```

更稳妥的做法是用 **allurectl / Allure TestOps** 或在 `post` 里 `stash` 历史目录 `allure-report/history` 供下次 `unstash`，趋势才有连续性。

### 三、钉钉通知

```groovy
post {
    failure {
        script {
            def msg = """{
              "msgtype": "markdown",
              "markdown": {
                "title": "接口自动化构建失败",
                "text": "### 接口自动化构建失败\\n- 任务：${env.JOB_NAME}\\n- 构建号：#${env.BUILD_NUMBER}\\n- 提交人：${env.CHANGE_AUTHOR}\\n- [查看详情](${env.BUILD_URL})"
              }
            }"""
            // webhook secret 走凭据，见 [[Jenkins 凭据管理]]
            sh "curl -s -X POST -H 'Content-Type: application/json' -d '${msg}' \${DINGTALK_WEBHOOK}"
        }
    }
    changed {
        // 状态翻转（红转绿/绿转红）才通知，避免刷屏
        echo '状态变化，发群通知'
    }
}
```

> 注意：上面的 `curl` 里 `${msg}` 含 JSON，单引号包 shell 变量、双引号给 JSON，容易引号地狱。生产里更推荐用 **DingTalk Plugin** 或把消息体写到文件再 `curl --data @file.json`。

### 四、企业微信 / 邮件

```groovy
// 企业微信机器人（webhook）
sh 'curl -s -X POST ...'

// 邮件（需要配置 SMTP）
mail to: 'qa-team@example.com',
     subject: "构建 ${currentBuild.currentResult}: ${env.JOB_NAME} #${env.BUILD_NUMBER}",
     body: "详情：${env.BUILD_URL}"
```

## 踩坑

1. **测试失败就没报告**。如果 Allure 生成只放在测试 stage 之后、而测试 stage 失败被跳过了，报告就缺了。务必把 `allure` step 放到 `post { always }`，并且测试 stage 用 `stash` 保留 `allure-results`。

2. **`--alluredir` 目录和 `results` 路径对不上**。pytest 写 `allure-results`，Jenkins 的 `allure results: [[path: 'xxx']]` 指成别的路径，报告是空的。两边路径必须一致。

3. **Allure 报告打不开 / 403**。Jenkins 的安全策略默认禁止加载内联 JS，需要在「全局安全配置」里把 **Content Security Policy** 放宽（如 `sandbox; default-src 'self'; img-src *; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'`）。这是常见卡点。

4. **趋势图一直是断的**。每次构建是干净的 workspace，`history` 目录丢了。需要用 `stash`/`unstash` 或外部存储保留历史，否则「历史趋势」永远是单点。

5. **通知 JSON 引号地狱**。直接在 Groovy 字符串里拼 JSON 再传给 shell，双引号冲突导致 curl 发的是坏数据。改成写文件 + `curl -d @file`，或装专用通知插件。

6. **钉钉 webhook secret 硬编码**。webhook 地址本身就是发消息的凭证，写死在 Jenkinsfile 等于谁都能往你们群发消息。走凭据（见 [[Jenkins 凭据管理]]）。

7. **`post` 里通知命令失败把构建变红**。SUCCESS 的构建因为 `curl` 网络抖动失败变成 FAILURE。通知类命令一律加 `|| true`，或包一层 `catchError(buildResult: 'SUCCESS')`。

8. **`changed` 通知首构建也发**。第一次构建没有「上次状态」，`changed` 可能按从无到有处理。可接受，但若想避免，加 `currentBuild.previousBuild != null` 判断。

9. **Allure 结果目录被 `.gitignore` 忽略导致归档为空**。确认 `allure-results` 没被忽略规则排除（见 [[Git .gitignore 规则与失效排查]]），虽然一般它是构建产物不在仓库里，但归档时路径要真实存在。

10. **JUnit 和 Allure 双写但 pytest 失败导致两者都空**。pytest 崩溃（非用例失败）时 `junit.xml` 和 `allure-results` 都没生成，归档报空。加 `allowEmptyResults/allowEmptyArchive` 并区分「退出码 1」和「大于 1」（见 [[Jenkinsfile Pipeline 语法]]）。

## 面试怎么答

**Q：怎么在 Jenkins 上展示自动化测试结果？**

A：我用 Allure。分两层：测试代码侧用 allure-pytest 这类适配器，把结果写成 Allure 标准的 JSON 和附件目录 `allure-results`，还能在用例里用 `allure.step`、`allure.attach` 记录请求响应和截图；Jenkins 侧装 Allure Plugin，在 `post { always }` 里调用 `allure results: [[path: 'allure-results']]` 生成带步骤、附件、趋势的 HTML 报告。我特意把报告生成放在 post 的 always 里，并且测试 stage 用 stash 保留结果目录，这样即使有用例失败也能看到报告。和原生 JUnit 报告比，Allure 能看请求响应和趋势，排查效率高得多。

**Q：测试失败了怎么通知到人？**

A：通知放在 `post` 里，因为 stage 失败会跳过后续 stage，但 post 一定执行。我一般 `failure` 里发钉钉到测试群，带上任务名、构建号、提交人和构建链接；`changed` 里做状态翻转通知，避免连续红灯刷屏。钉钉 webhook 本身是发消息的凭证，我走凭据注入不硬编码。还有个坑是通知命令自己也可能因网络抖动失败，把 SUCCESS 的构建变成红色，所以通知命令我都加 `|| true` 或用 `catchError` 包住。

**Q：Allure 的历史趋势怎么保住？**

A：因为每次构建 workspace 是干净的，上次的 `history` 目录会丢，趋势图就断了。做法是在 post 里把 `allure-report/history` 用 stash 存起来，下次构建先 unstash 再生成报告，让历史连续；规模再大就用 allurectl 把结果推到 Allure TestOps 集中管理。只靠每次独立构建是攒不出趋势的。

## 参考

- [Allure Plugin for Jenkins](https://plugins.jenkins.io/allure-jenkins-plugin/)
- [Allure pytest 文档](https://docs.qameta.io/allure/)
- 相关笔记：[[Jenkinsfile Pipeline 语法]]、[[Jenkins 凭据管理]]、[[Jenkins 参数化构建与触发方式]]、[[质量门禁设计与失败即阻断]]、[[CI 实践串联：接口自动化流水线]]
