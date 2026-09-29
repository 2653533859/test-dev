---
created: 2026-07-31
tags: [安全测试/安全接入研发流程]
---

# SAST、DAST 与 SCA 接入 CI 流水线

> 范围约束：本笔记讲「如何把安全检测接进研发流程」，所用工具均在自己环境内运行，不针对外部目标。

## 概念

安全不能只靠人工测试兜底，要左移进 CI/CD，让每次提交都过一遍自动化安全网。三类工具分工不同：

- **SAST（静态应用安全测试）**：读源码/字节码，扫注入、硬编码密钥、危险函数调用等。快、早、但误报多。例子：`Semgrep`、`CodeQL`、`Bandit`（Python）、`SpotBugs`。
- **DAST（动态应用安全测试）**：对着运行起来的服务发请求，扫运行时漏洞（如未授权访问、配置错误）。贴近真实利用，但要在部署后跑。例子：`OWASP ZAP`、`w3af`。
- **SCA（软件成分分析）**：扫依赖树，找已知漏洞的第三方库（CVE）。例子：`pip-audit`、`Trivy`、`Dependency-Check`、`npm audit`。

三者位置：**SAST/SCA 在构建前/中（快反馈），DAST 在部署/集成环境（运行时）**。

## 用法

在 CI 里分层挂检测（示意，Jenkinsfile / GitHub Actions 均可）：

```yaml
# 伪代码：PR 阶段做快反馈
stages:
  - sast:      run semgrep / bandit        # 扫源码，失败阻断合并
  - sca:       run pip-audit / trivy fs .  # 扫依赖 CVE
  - build:     docker build
  - deploy_staging: deploy to staging
  - dast:      zap-baseline-scan http://staging  # 对预发跑动态扫描
```

关键配置点：

- SAST/SCA 设为 **PR 门禁**（不修不让合）；DAST 放在 staging，避免误杀主干。
- 给 SAST 配规则基线，先把「必定误报」的规则静默，否则团队会习惯性忽略所有告警。
- `pip-audit` 这类可直接在本地 pre-commit 先跑一遍，最快反馈。

## 踩坑

- **一上来全量阻断**：SAST 误报多，直接当门禁会把团队逼到「全 `@SuppressWarnings`」。先跑出报告、降误报、再逐步提严。
- **SCA 只看直接依赖**：传递依赖（transitive）才是大多数 CVE 来源，工具必须递归扫整棵依赖树。
- **DAST 打生产**：DAST 会主动发「攻击式」请求，只能对 staging/授权靶场跑，绝不能指向生产。
- **漏掉容器镜像**：SCA 不只扫应用依赖，镜像里的 OS 包也要用 `Trivy` 扫。
- **告警无人跟**：接了工具但没有「谁来处理、SLA 多久」的流程，等于没接。

## 面试怎么答

- **SAST、DAST、SCA 区别？** SAST 读码找代码层漏洞（早、误报多），DAST 打运行服务找运行时漏洞（真实、需部署），SCA 扫第三方依赖的已知 CVE（补供应链短板）。
- **为什么 DAST 不放在 PR 阶段？** 它要对运行中的服务发请求，PR 阶段还没部署；且动作偏「攻击」，适合放 staging，避免误伤。
- **安全检测怎么不拖累研发？** SAST/SCA 做 PR 快门禁并先降误报，DAST 放预发，配合清晰的告警处理 SLA。

## 参考

- [OWASP DevSecOps Guideline](https://owasp.org/www-project-devsecops-guideline/)
- 相关笔记：[[漏洞报告编写与风险定级]]、[[OWASP Top 10 全景与测试切入点]]、[[持续集成、持续交付与持续部署]]、[[CI 实践串联：接口自动化流水线]]
