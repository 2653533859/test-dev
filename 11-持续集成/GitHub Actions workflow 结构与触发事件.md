---
created: 2026-07-31
tags: [持续集成/GitHub Actions]
---

# GitHub Actions workflow 结构与触发事件

![[assets/gha-workflow.svg]]
*图示：event 触发 workflow，workflow 由若干 job 组成，job 里是串行 step；job 之间默认并行，靠 `needs` 串依赖；每个 job 跑在独立的 runner 上。*

## 概念

### 为什么 GitHub Actions 和 Jenkins 思路不同

Jenkins 是「一个常驻服务 + 一堆节点」，你要自己装、自己管。GitHub Actions 是**托管式**的：你只写 YAML，GitHub 在它自己的 runner 池（或你提供的自托管 runner）上按事件临时起机器跑。对测试开发最直观的好处是：**配置文件就在仓库的 `.github/workflows/` 里，和代码一起版本管理，新人 clone 下来就知道 CI 长什么样**。

### 四个核心概念

- **event**：什么事件触发，如 `push`、`pull_request`、`schedule`、`workflow_dispatch`
- **workflow**：一个 YAML 文件 = 一条流水线，由若干 job 组成
- **job**：一组 step，默认跑在**一个独立的 runner 虚拟机**里，job 之间天然隔离
- **step**：job 里按顺序执行的最小单元，可以是一条 `run`（shell 命令）或一个 `uses`（复用 action）

关键认知：**每个 job 是一台干净的新机器**，`working-directory` 默认是仓库根，job 之间不共享文件——这点和 Jenkins 的 stage 共享 workspace 完全不同（见 [[Jenkinsfile Pipeline 语法]] 的 stash 问题）。

## 用法

### 一、最小可用 workflow

```yaml
# .github/workflows/api-tests.yml
name: API 自动化

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: '0 2 * * *'          # 每天北京时间≈10点（UTC 2 点）
  workflow_dispatch:             # 允许在 UI 手动触发

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: pytest tests/api -m smoke --alluredir=allure-results
```

### 二、触发事件精解

```yaml
on:
  # 只在某些路径变化时触发，避免文档改动也跑测试
  push:
    paths:
      - 'src/**'
      - 'tests/**'
    branches: [main, 'release/**']
  # PR 事件的细分
  pull_request:
    types: [opened, synchronize, reopened]
  # 手动触发时可填参数
  workflow_dispatch:
    inputs:
      markers:
        description: 'pytest -m 表达式'
        default: 'smoke'
        required: true
  # 别的 workflow 调用（可传 inputs）
  workflow_call:
    inputs:
      env:
        type: string
        default: 'test'
  # release 发布时
  release:
    types: [published]
```

几种易混的 push vs pull_request：

- `push` 在代码合进分支后触发，适合跑「合并后的全量」和部署
- `pull_request` 在 PR 未合入时触发，适合跑「合入前的门禁」——这是保护主干的关键

### 三、job 依赖与并发控制

```yaml
jobs:
  lint:
    runs-on: ubuntu-latest
    steps: [ ... ]
  build:
    needs: lint            # 等 lint 成功才跑
    runs-on: ubuntu-latest
    steps: [ ... ]
  api-test:
    needs: build
    runs-on: ubuntu-latest
    steps: [ ... ]
  ui-test:
    needs: build           # 和 api-test 并行
    runs-on: ubuntu-latest
    steps: [ ... ]
```

并发控制，避免多次 push 堆积：

```yaml
concurrency:
  group: ci-${{ github.ref }}        # 同一分支串行
  cancel-in-progress: true           # 新 push 取消旧的在跑的
```

### 四、secrets 与环境变量

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    env:
      API_TOKEN: ${{ secrets.QA_API_TOKEN }}     # 仓库/组织级密钥
      BASE_URL: https://test.example.com
    steps:
      - run: curl -H "Authorization: Bearer $API_TOKEN" $BASE_URL/health
```

secrets 在日志里自动打码，和 Jenkins 凭据同理（见 [[Jenkins 凭据管理]]）。

## 踩坑

1. **job 之间不共享文件**。在 job A 生成的 `allure-results`，job B 里读不到，因为是两个不同机器。要么放同一个 job，要么用 `actions/upload-artifact` + `download-artifact`（见 [[GitHub Actions matrix、缓存与 artifact]]）。

2. **`paths` 过滤导致 PR 不触发测试**。配了 `paths: ['src/**']`，但你的改动只动了 `tests/`，结果测试没跑，代码却合并了。路径过滤要覆盖「会影响测试的所有目录」。

3. **`schedule` 的时区是 UTC**。写 `0 2 * * *` 以为是北京时间凌晨 2 点，其实是 UTC 2 点（北京 10 点）。换算好或用 `TZ` 在 step 里处理。

4. **`pull_request` 拿不到 `secrets` 里的某些值**。来自 fork 的 PR 出于安全默认拿不到仓库 secrets（防止恶意 PR 偷密钥）。需要受信任的 contributor 或显式配置。

5. **`concurrency` group 命名太宽误杀**。用 `ci-${{ github.ref }}` 是按分支隔离，合理；但如果用固定 `ci-main` 所有分支共享，会互相取消。按 `github.ref` 或 `github.head_ref` 隔离更准。

6. **`actions/checkout@v4` 默认只拉最新一层**。需要完整历史（比如 `git diff` 看改动）要加 `fetch-depth: 0`，否则 `git` 相关步骤报浅克隆错误。

7. **runner 镜像里缺系统依赖**。ubuntu-latest 没有 `libxml2` 之类的库，pip 安装失败。用 `sudo apt-get install` 或换带依赖的 container，注意用 `container:` 字段而非手动装。

8. **手动 `workflow_dispatch` 参数类型限制**。只支持 `choice`/`string`/`boolean`/`environment`，没有 Jenkins 那种 `file`。需要上传文件时得另想办法。

9. **`uses` 锁版本用 tag 还是 commit**。用 `@v4` 这种移动 tag 可能被维护者改内容（虽罕见），更高安全级别用 `@a1b2c3d` 具体 commit SHA。

10. **YAML 缩进敏感**。`run:` 下的多行命令缩进错一格就解析成别的字段。多行脚本用 `|` 块标量，并保证缩进一致。

## 面试怎么答

**Q：GitHub Actions 的基本结构是怎样的？**

A：核心是四个层级。最外层是 workflow，一个 YAML 文件对应一条流水线，放在 `.github/workflows/` 下，和代码一起版本管理。workflow 由 `on` 指定触发事件，由 `jobs` 定义若干任务。每个 job 跑在一台独立的 runner 虚拟机上，job 之间默认并行，用 `needs` 串依赖。job 里是顺序执行的 step，每个 step 要么是一条 `run` 的 shell 命令，要么用 `uses` 复用一个 action。最关键的一点：每个 job 是干净的新机器，job 之间不共享文件，要传产物得用 artifact，这跟 Jenkins 同一个 workspace 共享文件的模型很不一样。

**Q：push 和 pull_request 触发有什么区别，你分别用来做什么？**

A：push 是代码已经合进分支之后触发，适合跑合并后的全量测试和部署；pull_request 是 PR 还没合入时触发，适合跑合入前的质量门禁——这是保护主干的关键，能在合并前拦住不达标代码。实际我两个都配：PR 时跑 smoke 门禁快速反馈，push 到 main 后跑全量回归加出报告。另外我还会用 `paths` 过滤，只有 src 和 tests 改动才跑测试，避免文档改动也空跑。

**Q：GitHub Actions 怎么管理密钥？**

A：用仓库或组织级的 secrets，在 workflow 里通过 `${{ secrets.XXX }}` 引用，日志里自动打码，和 Jenkins 凭据理念一样。要注意来自 fork 的 PR 出于安全默认拿不到仓库 secrets，防止恶意 PR 偷密钥——这点 Jenkins 私有部署一般没这问题。敏感程度高的我还会把 `uses` 的 action 锁到具体 commit SHA 而非移动 tag，避免 action 被篡改。

## 参考

- [GitHub Actions 官方文档](https://docs.github.com/en/actions)
- [Workflow 语法参考](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions)
- 相关笔记：[[GitHub Actions matrix、缓存与 artifact]]、[[Jenkins 架构与 Freestyle、Pipeline 选型]]、[[Jenkins 凭据管理]]
