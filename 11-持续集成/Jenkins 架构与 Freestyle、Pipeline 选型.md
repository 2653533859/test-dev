---
created: 2026-07-31
tags: [持续集成/Jenkins]
---

# Jenkins 架构与 Freestyle、Pipeline 选型

> Jenkins 本身只是个「插件宿主 + 调度器」。理解 Controller/Agent 分工和 JENKINS_HOME 的地位，比记住界面上有哪些按钮重要得多。

![[assets/jenkins-architecture.svg]]
*图示：Controller 只负责解析、调度、存配置和展示报告，构建全部下沉到按 label 匹配的 Agent；下方对比 Freestyle 与 Pipeline 的本质差异。*

## 概念

### Jenkins 是什么

一句话：**一个用 Java 写的、靠插件扩展一切能力的自动化任务调度平台**。

Jenkins 核心极小，几乎所有实际功能——拉 Git 代码、跑 Docker、发钉钉、生成 Allure 报告——都由插件提供。这带来两个直接后果：

- **优点**：1800+ 插件，几乎任何工具都有集成，私有化部署、完全可控
- **缺点**：插件质量参差、版本依赖复杂，「升级一个插件挂掉三条流水线」是 Jenkins 运维的日常

### Controller / Agent 架构

**Controller（主节点，旧称 master）**职责：

- 提供 Web UI 和 REST API
- 存储所有配置（`JENKINS_HOME`）
- 解析 Jenkinsfile，把 stage 拆成任务排进队列
- 按 label 把任务分配给 Agent
- 收集 Agent 回传的日志、产物、测试报告
- 管理凭据、插件、权限

**Agent（构建节点，旧称 slave）**职责：只有一个——**执行具体的构建步骤**。

**铁律：Controller 上不要跑构建。** 原因有三：

1. **安全**：构建脚本能读到 `JENKINS_HOME`，里面有全部凭据（哪怕加密了，master key 也在同一目录）
2. **稳定**：构建吃满 CPU/内存会拖垮整个 Jenkins，所有人都用不了
3. **环境隔离**：不同项目需要不同 Python/JDK/浏览器版本，堆在 Controller 上必然打架

正确配置：Controller 的执行器数量设为 **0**。

```text
Manage Jenkins → Nodes → Built-In Node → Number of executors: 0
```

### JENKINS_HOME：Jenkins 的全部身家

```text
$JENKINS_HOME/
├── config.xml              全局配置
├── credentials.xml         凭据（加密）
├── secrets/                加密主密钥 ← 泄露等于所有凭据泄露
├── jobs/
│   └── <job名>/
│       ├── config.xml      任务配置
│       └── builds/         历史构建记录与日志
├── plugins/                插件 jar
├── nodes/                  Agent 配置
├── users/
└── workspace/              构建工作目录（可清理）
```

**备份 = 备份 JENKINS_HOME（可排除 `workspace/` 和旧 `builds/`）。** 恢复只需要把目录还原、启动即可。这也是「Jenkins 配置全在文件系统里」的体现——没有数据库。

### Agent 连接方式

| 方式 | 原理 | 适用 |
|------|------|------|
| SSH | Controller 主动 SSH 到 Agent 启动 agent.jar | Linux Agent，最常用 |
| JNLP / inbound | Agent 主动连 Controller | Agent 在内网/NAT 后面、Windows |
| Docker Cloud | 每次构建动态起一个容器当 Agent，用完销毁 | **最推荐**，环境天然干净 |
| Kubernetes | 每次构建起一个 Pod | 大规模、弹性伸缩 |

动态 Agent（Docker/K8s）的好处非常大：**每次构建都是全新环境**，彻底消灭「上次构建残留导致这次莫名其妙成功/失败」这类幽灵问题。

### Freestyle vs Pipeline

| | Freestyle | Pipeline |
|---|---|---|
| 配置存放 | Jenkins 界面 → `jobs/*/config.xml` | 仓库里的 `Jenkinsfile` |
| 版本管理 | 无（改了没记录、无法回滚） | 跟代码一起版本化、可 review |
| 结构表达 | 单段串行 | stage / parallel / when / post |
| 可视化 | 只有一条日志 | Stage View，一眼看出挂在哪一步 |
| 断点续跑 | Controller 重启构建就废了 | durable，能续跑 |
| 复用 | 复制粘贴 | Shared Library |
| 上手 | 点点点，快 | 要学 Groovy DSL |

**结论：新项目一律 Pipeline。** Freestyle 只适合「临时验证一下某个命令」。

核心理由是 **Pipeline as Code**：流水线定义是工程资产，应该像代码一样被 review、被 diff、被回滚。Freestyle 的配置改了就是改了，谁改的、改了啥、怎么回退，全靠人记。

### Declarative vs Scripted Pipeline

Pipeline 有两种语法：

- **Declarative（声明式）**：`pipeline { agent ... stages { ... } }`，结构固定、校验严格、报错友好，**默认选它**
- **Scripted（脚本式）**：`node { ... }`，本质是 Groovy 脚本，灵活但没有结构约束，容易写成一坨

声明式里遇到复杂逻辑时，可以用 `script { }` 块内嵌脚本式代码，兼顾两者。详见 [[Jenkinsfile Pipeline 语法]]。

## 用法

### 一、Docker 方式部署 Jenkins

```bash
# 数据卷持久化 JENKINS_HOME，容器可随时重建
docker volume create jenkins_home

docker run -d --name jenkins \
  -p 8080:8080 -p 50000:50000 \
  -v jenkins_home:/var/jenkins_home \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --restart unless-stopped \
  jenkins/jenkins:lts-jdk17
```

- `8080` 是 Web UI，`50000` 是 JNLP Agent 连接端口
- 挂 `docker.sock` 是为了让 Jenkins 能在宿主机上起容器（Docker outside of Docker）。**注意这等于把宿主机 root 权限给了 Jenkins**，生产环境要评估风险，更安全的做法是用独立的 Docker Agent 节点

```bash
# 取初始管理员密码
docker exec jenkins cat /var/jenkins_home/secrets/initialAdminPassword
```

### 二、测试团队必装插件清单

```text
基础
  Pipeline                    流水线核心（套件）
  Git / Git Parameter         拉代码、按分支/tag 参数化
  Credentials Binding         把凭据注入成环境变量
  Timestamper                 日志加时间戳（排查耗时必备）
  Workspace Cleanup           构建前后清工作区
  Build Timeout               超时自动中止，防卡死

报告
  Allure Jenkins Plugin       Allure 报告（见 [[Jenkins Allure 报告与构建后通知]]）
  JUnit                       解析 junit xml，趋势图
  HTML Publisher              发布任意 HTML 报告
  Cobertura / Coverage        覆盖率趋势与门禁

触发与通知
  Generic Webhook Trigger     通用 webhook，比各家专用插件灵活
  GitLab / GitHub Branch Source
  Email Extension             可定制邮件模板
  DingTalk                    钉钉机器人

进阶
  Blue Ocean                  更好看的流水线可视化
  Docker Pipeline             在 Pipeline 里用 docker 指令
  Kubernetes                  动态 Pod Agent
  Role-based Authorization    按角色划权限
  Configuration as Code       用 YAML 定义 Jenkins 自身配置
```

**插件管理原则**：只装真正用到的。每个插件都是一份升级负担和一个潜在的安全漏洞面。

### 三、配置一个 Linux Agent（SSH 方式）

Agent 机器准备：

```bash
# Agent 上：装 JDK（Agent 只需要 JRE 跑 agent.jar）
sudo apt update && sudo apt install -y openjdk-17-jre-headless git python3-venv

# 建专用用户与工作目录
sudo useradd -m -s /bin/bash jenkins
sudo mkdir -p /home/jenkins/agent && sudo chown -R jenkins: /home/jenkins

# 把 Controller 的公钥加进来
sudo -u jenkins mkdir -p /home/jenkins/.ssh
sudo -u jenkins tee /home/jenkins/.ssh/authorized_keys < controller_id_rsa.pub
sudo -u jenkins chmod 700 /home/jenkins/.ssh
sudo -u jenkins chmod 600 /home/jenkins/.ssh/authorized_keys
```

Jenkins 界面：`Manage Jenkins → Nodes → New Node`

```text
Name:               linux-api-01
Remote root dir:    /home/jenkins/agent
Labels:             linux api docker        ← 关键，Pipeline 靠它选节点
Usage:              Only build jobs with label expressions matching this node
Launch method:      Launch agents via SSH
  Host:             10.0.1.21
  Credentials:      jenkins-ssh-key（见 [[Jenkins 凭据管理]]）
  Host Key Strategy: Known hosts file
Number of executors: 2                      ← 一般设成 CPU 核数或略少
```

**executors 数量的取舍**：设太大会让多个构建抢 CPU、互相拖慢甚至 OOM；UI 自动化这种独占浏览器/端口的任务，executors 通常设 1，避免同一台机上两个构建抢同一个 4444 端口。

### 四、按 label 把任务分到对的机器

```groovy
// 整条流水线固定在一类节点上
pipeline {
    agent { label 'linux && api' }        // 支持 && || ! 表达式
    stages { /* ... */ }
}
```

```groovy
// 不同 stage 用不同节点：接口用例在 Linux 跑，UI 用例在有浏览器的 Windows 跑
pipeline {
    agent none                            // 顶层不占用节点
    stages {
        stage('接口回归') {
            agent { label 'linux && api' }
            steps { sh 'pytest tests/api' }
        }
        stage('UI 回归') {
            agent { label 'windows && chrome' }
            steps { bat 'pytest tests\\ui' }
        }
    }
}
```

**注意**：换了 agent 就换了工作区，上一个 stage 生成的文件在下一个 stage 里不存在。要传递必须用 `stash`/`unstash`：

```groovy
stage('构建') {
    agent { label 'linux' }
    steps {
        sh 'python -m build'
        stash name: 'dist', includes: 'dist/**'
    }
}
stage('测试') {
    agent { label 'windows' }
    steps {
        unstash 'dist'
        bat 'pytest tests/'
    }
}
```

### 五、动态 Docker Agent（强烈推荐）

每次构建起一个全新容器，跑完销毁，环境永远干净：

```groovy
pipeline {
    agent {
        docker {
            image 'python:3.11-slim'
            label 'docker'                       // 在哪台宿主机上起容器
            args  '-v /root/.cache/pip:/root/.cache/pip'   // 挂缓存加速
        }
    }
    stages {
        stage('Test') {
            steps {
                sh 'pip install -r requirements.txt'
                sh 'pytest tests/api --alluredir=allure-results'
            }
        }
    }
}
```

更彻底的做法是用自己维护的测试框架镜像，连依赖安装都省了（见 [[Dockerfile 编写与镜像构建优化]]）：

```groovy
agent { docker { image 'registry.example.com/qa-runner:1.4.0' } }
```

### 六、Job 类型怎么选

```text
Freestyle project        临时验证，不推荐用于正式流水线
Pipeline                 单分支流水线，Jenkinsfile 可写在界面或从 SCM 拉
Multibranch Pipeline     ★ 自动发现仓库里所有含 Jenkinsfile 的分支/PR，
                           各自建一条流水线，分支删了自动清理 —— PR 门禁首选
Organization Folder      自动扫描整个 GitHub 组织/GitLab 群组下所有仓库
Folder                   目录，用来组织归类
```

**Multibranch Pipeline 是做 PR 门禁的正确姿势**：新建分支自动出流水线、提 PR 自动跑、合并后自动删，不需要人工维护 job。

### 七、从 Freestyle 迁移到 Pipeline

Freestyle 里的配置逐项对应：

| Freestyle 配置项 | Jenkinsfile 写法 |
|---|---|
| 源码管理 Git | `checkout scm` 或 `git url: ..., branch: ...` |
| 构建触发器 定时 | `triggers { cron('H 2 * * *') }` |
| 构建触发器 轮询 | `triggers { pollSCM('H/5 * * * *') }` |
| 参数化构建 | `parameters { string(...) choice(...) }` |
| 执行 Shell | `steps { sh '...' }` |
| 构建后 归档产物 | `archiveArtifacts artifacts: 'dist/**'` |
| 构建后 JUnit | `junit 'reports/*.xml'` |
| 构建后 邮件 | `post { failure { emailext ... } }` |

迁移技巧：Freestyle job 页面有 **Pipeline Syntax → Snippet Generator**，把界面配置生成对应的 Groovy 代码，直接粘进 Jenkinsfile。

## 踩坑

1. **在 Controller 上跑构建**。`agent any` 在没有其他节点时会落到 Built-In Node 上，构建脚本能读到 `JENKINS_HOME/secrets/`，等于所有凭据裸奔；同时构建吃满资源会让整个 Jenkins 卡死。**Controller executors 一律设 0。**

2. **磁盘被构建历史撑爆**。每次构建的日志、归档产物、Allure results 都在 `JENKINS_HOME/jobs/*/builds/` 里累积，几个月就是几百 G。必须配丢弃策略：

   ```groovy
   options {
       buildDiscarder(logRotator(numToKeepStr: '30', artifactNumToKeepStr: '10'))
   }
   ```

3. **workspace 不清理导致幽灵成功**。上次构建残留的 `.pyc`、旧的 `allure-results`、上次生成的配置文件，让这次构建「莫名其妙成功了」或者报告里混进了上次的结果。解法：

   ```groovy
   options { skipDefaultCheckout() }
   stages {
       stage('Prepare') {
           steps {
               cleanWs()          // Workspace Cleanup 插件
               checkout scm
           }
       }
   }
   ```

   或者干脆用动态 Docker Agent，从根上避免。

4. **插件升级炸掉流水线**。Jenkins 插件之间有复杂依赖，「升一个带十个」，升完某个 step 找不到了。规矩：**升级前备份 `JENKINS_HOME`**；不要在周五升级；生产 Jenkins 和测试 Jenkins 分开，先在测试实例验证。

5. **Agent 上没装依赖，报错莫名其妙**。`sh: chromedriver: not found`、`java: command not found`。Agent 环境是需要单独维护的，不会自动继承 Controller 的。这正是推荐动态 Docker Agent 的原因——环境写在 Dockerfile 里，可版本化。

6. **多个构建抢同一个端口/资源**。两条流水线同时在一台 Agent 上起 Selenium Grid，都监听 4444，第二个直接失败。解法：该节点 executors 设 1，或者用 Lockable Resources 插件加锁，或者端口动态分配。

7. **Windows Agent 上 `sh` 步骤失败**。Declarative Pipeline 里 Windows 要用 `bat` 或 `powershell`，不能用 `sh`。跨平台流水线要判断：

   ```groovy
   script {
       if (isUnix()) { sh 'pytest tests/' } else { bat 'pytest tests\\' }
   }
   ```

8. **`JENKINS_HOME` 从没备份过**。硬盘挂了，几十条流水线配置、凭据、历史数据全没。备份策略：定期 tar 打包 `JENKINS_HOME`（排除 `workspace/`），或者用 JCasC（Configuration as Code）插件把配置写成 YAML 进 Git，实现「Jenkins 本身也是代码」。

9. **时区不对，定时任务在半夜错误时间触发**。容器默认 UTC。启动时加 `-e TZ=Asia/Shanghai`，或在 Jenkins 系统配置里设时区。

10. **Agent 与 Controller 的 JDK 版本不匹配**。Jenkins 对 Agent 的 Java 版本有要求，不匹配时连接直接失败且报错信息晦涩。查官方兼容矩阵，Controller 用 JDK 17 时 Agent 也用 17。

## 面试怎么答

**Q：介绍一下 Jenkins 的架构。**

A：Jenkins 是 Controller/Agent 架构。Controller 是主节点，负责 Web UI、解析 Jenkinsfile、任务排队与调度、凭据和插件管理、收集日志和报告，所有配置都存在 `JENKINS_HOME` 这个目录里，没有数据库，所以备份就是备份这个目录。Agent 是构建节点，只负责执行具体步骤，通过 SSH 或 JNLP 连上来，靠 label 被匹配。有一条重要实践是 **Controller 上不能跑构建**，执行器要设成 0——因为构建脚本能读到 `JENKINS_HOME/secrets`，等于凭据泄露，而且构建吃资源会拖垮整个 Jenkins。我们的做法是把接口用例、UI 用例、性能压测分到不同 label 的 Agent 上，UI 那台 executors 设成 1 避免抢浏览器端口，更多任务用动态 Docker Agent，每次构建起全新容器、跑完销毁。

**Q：Freestyle 和 Pipeline 有什么区别，怎么选？**

A：最本质的区别是配置放在哪。Freestyle 的配置在 Jenkins 界面上、存成 `config.xml`，改了没有版本记录、不能 code review、也无法回滚，换个 Jenkins 实例还得重新配。Pipeline 是把流水线写成仓库里的 Jenkinsfile，跟代码一起版本化，这就是 Pipeline as Code。除此之外 Pipeline 支持 stage 分段可视化，一眼看出挂在哪一步；支持 parallel 并行、when 条件、post 兜底；Controller 重启后还能续跑；复用逻辑可以抽成 Shared Library。所以新项目我一律用 Pipeline，而且用 Multibranch Pipeline，它能自动发现所有带 Jenkinsfile 的分支和 PR 各建一条流水线，做 PR 门禁最合适。Freestyle 我只在临时验证一条命令时用。

**Q：怎么保证每次构建的环境是干净的？**

A：三个层次。最基础的是每次构建前 `cleanWs()` 清工作区，再 `checkout scm`——不清的话上次残留的 `.pyc`、旧的 allure-results 会导致幽灵成功或者报告混数据。第二层是用 `agent { docker { image ... } }`，每次构建起一个全新容器跑，跑完销毁，连系统级依赖都是干净的。第三层是把测试框架和依赖直接打成镜像，Agent 只负责拉起来，这样本地和 CI 用完全相同的环境，从根上消灭「本地能跑 CI 不能跑」。我们现在用的是第三种，镜像跟框架版本一起打 tag，出问题能精确复现某个版本的环境。

**Q：Jenkins 怎么做备份和迁移？**

A：Jenkins 没有数据库，全部状态都在 `JENKINS_HOME`：`config.xml` 是全局配置，`jobs/` 是任务配置和构建历史，`plugins/` 是插件，`credentials.xml` 加 `secrets/` 是凭据。所以备份就是定期打包这个目录，可以排除 `workspace/`（能重新拉）和过老的 `builds/`（占空间大）。迁移就是把目录还原到新机器再启动，注意插件版本要一致。更工程化的做法是用 Configuration as Code 插件，把 Jenkins 自身的配置写成 YAML 提交进 Git，加上 Job DSL 或 Multibranch 自动发现，这样整个 Jenkins 实例可以从代码重建，配置变更也能走 review。凭据不进 Git，从环境变量或外部密钥管理系统注入。

## 参考

- [Jenkins 官方文档](https://www.jenkins.io/doc/)
- [Managing nodes（Agent 配置）](https://www.jenkins.io/doc/book/managing/nodes/)
- [Jenkins Configuration as Code](https://www.jenkins.io/projects/jcasc/)
- 相关笔记：[[Jenkinsfile Pipeline 语法]]、[[Jenkins 参数化构建与触发方式]]、[[Jenkins 凭据管理]]、[[Jenkins Allure 报告与构建后通知]]、[[持续集成、持续交付与持续部署]]
