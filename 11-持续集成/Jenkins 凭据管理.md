---
created: 2026-07-31
tags: [持续集成/Jenkins]
---

# Jenkins 凭据管理

> 凭据是「不该出现在代码和日志里的秘密」。Jenkins 凭据系统的目标只有一个：让脚本能用上密码，但永远看不到密码本身。

## 概念

### 凭据解决什么问题

一条流水线要连的东西几乎都有秘密：代码仓库的 token、Docker 镜像仓库的账号、测试环境的数据库密码、第三方平台（钉钉/企业微信）的 webhook secret、云厂商的 AK/SK。把这些写进 Jenkinsfile 或打在镜像里是严重安全事故：代码仓库一旦公开或内鬼拉库，秘密全泄露。

Jenkins 凭据系统的设计是：**秘密只存在 Jenkins 的凭据存储里（通常加密在 `$JENKINS_HOME/credentials.xml` 或对接到外部 vault），脚本只能通过凭据 ID 引用，运行时由 Jenkins 把值注入成环境变量或文件，且打印时自动打码成 `****`**。

### 凭据的几种类型

- **Secret text**：一段字符串，如 API token、webhook secret
- **Username with password**：用户名 + 密码，自动展开成 `XXX_USR` 和 `XXX_PSW`
- **SSH Username with private key**：私钥，用于拉私有仓库 / 登服务器
- **Secret file**：一个文件（如 `kubeconfig`、`*.pem` 证书），运行时落到临时文件
- **Certificate**：PKCS#12 证书

关键认知：**凭据用「ID」引用，不用「值」引用**。脚本里只写 `credentials('docker-registry')`，具体值只有管理员在凭据系统里能看到。

## 用法

### 一、在 environment 里注入

```groovy
pipeline {
    agent any
    environment {
        // Secret text：注入成一个变量
        API_TOKEN  = credentials('qa-api-token')
        // Username with password：自动展开成 DOCKER_USR / DOCKER_PSW
        DOCKER     = credentials('docker-registry')
        // SSH 私钥：注入成文件，变量指向文件路径
        SSH_KEY    = credentials('deploy-key')
    }
    stages {
        stage('用 token 调接口') {
            steps {
                sh 'curl -H "Authorization: Bearer $API_TOKEN" https://api.example.com/health'
            }
        }
        stage('登镜像仓库') {
            steps {
                sh 'echo "$DOCKER_PSW" | docker login -u "$DOCKER_USR" --password-stdin registry.example.com'
            }
        }
        stage('用私钥拉私有依赖') {
            steps {
                sh 'ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no git@github.com ...'
            }
        }
    }
}
```

注意 `Username with password` 注入的是两个变量：`${DOCKER_USR}` 和 `${DOCKER_PSW}`，没有 `${DOCKER}` 本身。

### 二、在 withCredentials 块里局部用

比 `environment` 更细粒度：只在块内可见，块结束自动清除，适合临时用一下。

```groovy
steps {
    withCredentials([string(credentialsId: 'qa-api-token', variable: 'TOKEN')]) {
        sh 'curl -H "Authorization: Bearer $TOKEN" https://api.example.com/health'
    }
    // 这里 $TOKEN 已失效，更安全
}
```

Secret file 用法：

```groovy
withCredentials([file(credentialsId: 'kubeconfig', variable: 'KUBE')]) {
    sh 'kubectl --kubeconfig=$KUBE get pods -n test'
}
```

### 三、凭据在 withCredentials 里的类型映射

```groovy
// Secret text
withCredentials([string(credentialsId: 't', variable: 'V')]) { }

// Username with password
withCredentials([usernamePassword(credentialsId: 'u', usernameVariable: 'U', passwordVariable: 'P')]) { }

// SSH private key
withCredentials([sshUserPrivateKey(credentialsId: 'k', keyFileVariable: 'KEY', usernameVariable: 'USER')]) { }

// Secret file
withCredentials([file(credentialsId: 'f', variable: 'F')]) { }
```

### 四、凭据作用域与权限

- **系统级凭据**：所有 job 可用
- **文件夹（Folder）级凭据**：只在该文件夹下的 job 可用，适合按团队隔离
- 配合 **Credentials Binding Plugin** 才能在 `withCredentials` 里用 `file`/`sshUserPrivateKey`

建议按团队建 Folder，把测试环境的凭据圈在测试团队的 Folder 里，避免跨团队误用和越权。

## 踩坑

1. **把 secret 写进 `string` 参数**。前面说过，`password` 参数仍是明文变量，日志里即便打码也能在内存转储、构建产物里泄露。机密只用 `credentials()`。

2. **`echo` 出凭据值就泄露**。即便 Jenkins 自动打码，你若手动 `echo "$API_TOKEN"` 或在命令里拼接打印，打码机制不生效。原则：不打印、不拼进日志的命令参数（尽量用环境变量而非命令行参数传秘密，因为命令行参数会出现在 `ps` 里）。

3. **`Username with password` 变量名搞错**。注入的是 `XXX_USR` 和 `XXX_PSW`，新手常写 `${DOCKER}` 想拿用户名，结果是空的。

4. **凭据 ID 改了导致流水线全红**。脚本里硬编码了旧 ID，凭据改名或迁移后找不到。建议 ID 用有意义的稳定命名（如 `qa-api-token`），并在团队文档里登记，别用 `credentials-1` 这种自动生成的。

5. **凭据存在系统级，Folder job 看不到**。凭据建在系统作用域，但 job 在 Folder 下，作用域不继承时取不到。要么把凭据建在 Folder 级，要么开「跨文件夹可见」。

6. **`withCredentials` 块外还能读到变量**。理论上块结束变量就被清了，但如果你在块里把它写进了 `env.XXX` 或文件，残留还在。保持「即用即销」。

7. **凭据过多导致轮换困难**。几十个散落的凭据，某密钥要轮转时一个个改很痛苦。统一接外部 **HashiCorp Vault** 或用 Folder 级凭据 + 命名规范，能大幅降低轮换成本。

8. **SSH 私钥没设 passphrase 或权限过宽**。私钥文件在 agent 上是明文落盘的（`/tmp/...`），agent 被攻陷就泄露。用完即弃的临时 agent + 不在 agent 持久化凭据是更优解。

9. **Docker 凭据助手把密码写进 `~/.docker/config.json`**。登录命令 `docker login` 默认把密码（或 Base64）存在 config.json。用 `--password-stdin` 配合凭据，且构建后清理该文件。

10. **凭据绑定插件没装**。用了 `withCredentials` 的 `file`/`sshUserPrivateKey` 报错说不支持该类型，是缺 **Credentials Binding Plugin**。

## 面试怎么答

**Q：Jenkins 里怎么安全管理密码、token 这类秘密？**

A：绝对不写进 Jenkinsfile 或镜像。我把它们统一存进 Jenkins 凭据系统，按类型分：Secret text 存 API token 和 webhook secret，Username with password 存镜像仓库账号，SSH 私钥存 deploy key，证书和 kubeconfig 用 Secret file。脚本里只通过凭据 ID 引用，比如 `environment { TOKEN = credentials('qa-api-token') }` 或 `withCredentials` 块。运行时 Jenkins 把值注入成环境变量或临时文件，并且打印时自动打码成星号。我习惯用 `withCredentials` 做局部注入，块结束自动失效，比顶层 environment 更安全。凭据按团队建在 Folder 级，做好隔离和命名规范，方便轮换。

**Q：`withCredentials` 和顶层 `environment` 里用 credentials 有什么区别？**

A：顶层 `environment` 里注入的凭据对整个流水线所有 stage 可见，适合几乎每个阶段都要用的核心秘密，比如 API token。但可见范围大，风险也大。`withCredentials` 是块级作用域，只在花括号里有效，块结束立刻清除，适合临时用一下，比如只在登录镜像仓库那一步才需要 Docker 密码。安全上我优先用 `withCredentials`，只在确实全局需要时放 environment。两者都不会在日志里明文打印，这是凭据系统提供的保护，但前提是别自己 `echo` 出来。

**Q：凭据泄露了怎么处理？**

A：分三步。第一，立刻在源头（代码平台、镜像仓库、第三方平台）吊销并重新生成该密钥。第二，在 Jenkins 里更新对应凭据的值（ID 不变，脚本无需改）。第三，排查是否有构建日志或归档产物里残留了旧值——Jenkins 打码只针对 `credentials()` 注入的变量，凡是你手动打印过的、或命令行参数里带过的都可能是明文，必要时清理相关构建记录。最后把这套流程沉淀成「密钥轮转 SOP」，避免下次手忙脚乱。

## 参考

- [Jenkins 凭据插件文档](https://www.jenkins.io/doc/book/using/using-credentials/)
- [Credentials Binding Plugin](https://plugins.jenkins.io/credentials-binding/)
- 相关笔记：[[Jenkinsfile Pipeline 语法]]、[[Jenkins 参数化构建与触发方式]]、[[Jenkins Allure 报告与构建后通知]]、[[CI 实践串联：接口自动化流水线]]
