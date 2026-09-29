---
created: 2026-07-31
tags: [持续集成/Docker]
---

# Dockerfile 编写与镜像构建优化

> Dockerfile 写得好不好，直接决定 CI 构建快不快、镜像安不安全、环境可不可复现。核心是「缓存顺序」和「层精简」两条原则。

## 概念

### Dockerfile 的本质

Dockerfile 是一份**声明式的镜像构建配方**：每条指令产生一层。构建时 Docker 逐条执行，能命中缓存就跳过、不能命中就重建并使其后所有层失效。所以写 Dockerfile 不是「能跑就行」，而是「**让不变的层尽量靠前、常变的层尽量靠后**」，最大化缓存复用。

### 为什么测试镜像要专门优化

测试场景里 Docker 镜像通常用来：跑自动化框架、起被测服务。如果镜像几百 MB、构建要几分钟，CI 每次都慢、磁盘也吃紧。而且测试镜像常带 `pip install` 大量依赖，依赖清单一改就全量重装，优化缓存顺序收益极大。

### 两个核心原则

1. **缓存友好**：依赖安装（变动少）放前面，代码 COPY（变动多）放后面
2. **镜像精简**：少层、少无用文件、非 root 运行、固定基础镜像版本

## 用法

### 一、一份优化过的测试框架 Dockerfile

```dockerfile
# 1) 锁版本基础镜像（避免 latest 漂移）
FROM python:3.11-slim

# 2) 系统依赖：合并到一条 RUN，清 apt 缓存，减少层体积
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libxml2-dev \
 && rm -rf /var/lib/apt/lists/*

# 3) 先只复制依赖清单，利用缓存：只有 requirements.txt 变了才重装
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4) 再复制代码（频繁变动），放后面
COPY . .

# 5) 非 root 运行，安全
RUN useradd -m qa && chown -R qa:qa /app
USER qa

# 6) 默认命令
CMD ["pytest", "tests/", "-m", "smoke"]
```

关键点逐条对应原则：`requirements.txt` 先于代码 COPY，依赖没变就跳过 `pip install`；`rm -rf /var/lib/apt/lists/*` 防止 apt 缓存进镜像；`--no-cache-dir` 不让 pip 留缓存；`USER qa` 不以 root 跑。

### 二、构建时传参（多版本 Python 测试）

```dockerfile
ARG PY=3.11
FROM python:${PY}-slim
```

```bash
docker build --build-arg PY=3.9 -t qa-auto:py39 -f Dockerfile.test .
```

配合 GitHub Actions matrix 的多个 Python 版本，一份 Dockerfile 构建多版本测试镜像（见 [[GitHub Actions matrix、缓存与 artifact]]）。

### 三、`.dockerignore` 减少上下文

```text
.git
__pycache__
*.pyc
logs/
allure-results/
venv/
```

不写 `.dockerignore`，`COPY . .` 会把 `.git`、`venv`、历史产物全打进镜像上下文，既慢又臃肿，还可能泄露。它和 `.gitignore` 是两套独立规则（见 [[Git .gitignore 规则与失效排查]]）。

### 四、多阶段构建：只在构建期要的东西不进最终镜像

```dockerfile
# 构建阶段：装编译工具
FROM python:3.11-slim AS builder
RUN apt-get update && apt-get install -y gcc
COPY . /src
RUN pip install --no-cache-dir --prefix=/install -r /src/requirements.txt

# 运行阶段：干净瘦身
FROM python:3.11-slim
COPY --from=builder /install /usr/local
COPY . /app
WORKDIR /app
CMD ["pytest"]
```

最终镜像不含 gcc 等编译工具，体积小、攻击面小。

### 五、构建并验证

```bash
docker build -t qa-auto:1.0 -f Dockerfile.test .
docker run --rm qa-auto:1.0 pytest tests/api -m smoke --alluredir=allure-results
docker images qa-auto:1.0        # 看体积
docker history qa-auto:1.0       # 看每层贡献
```

## 踩坑

1. **`COPY . .` 放在 `pip install` 之前导致每次重装**。代码一改，缓存失效，依赖全重装，CI 慢几分钟。正确顺序：先 COPY 依赖清单装依赖，再 COPY 代码。

2. **忘了 `.dockerignore` 把 `.git` 和 `venv` 打进去**。镜像体积暴涨，还把本地 venv（可能是另一个平台编译的）带进去，运行时冲突。务必配 `.dockerignore`。

3. **`apt-get` 缓存没清**。`RUN apt-get install` 后不 `rm -rf /var/lib/apt/lists/*`，几百 MB 缓存留在镜像层。apt 和 pip 都要清缓存。

4. **用 `latest` 基础镜像，构建不可复现**。今天 3.11 明天 3.12，同样的 Dockerfile 构建出不同环境。锁 `python:3.11-slim`，重要场景锁 digest。

5. **用 `pip install` 默认缓存进镜像**。`RUN pip install` 不带 `--no-cache-dir`，pip 的 `~/.cache` 留在层里。加 `--no-cache-dir`。

6. **以 root 跑测试容器**。容器内 root 进程一旦被逃逸有风险，且写的文件属主是 root，挂载 volume 时宿主机权限错乱。加 `USER` 非 root。

7. **`CMD` 写成 `RUN pytest`**。在构建阶段就跑测试，镜像构建依赖测试通过，且测试产物留在镜像里。测试应在 `docker run` 时跑，不在构建时。

8. **一条 RUN 里 `&&` 写错，层不合并**。分开写多条 RUN 会产生更多层、体积更大，且中间层残留。能用一条 `&&` 链完成的合并成一层。

9. **`ARG` 在 `FROM` 之后才生效的误解**。`ARG` 在 `FROM` 之前声明的才能用在 `FROM` 里；想在构建期用，要在 `FROM` 之后再声明一次。多阶段常见坑。

10. **Windows 换行符导致 `exec format error`**。Dockerfile 被存成 CRLF，RUN 指令末尾 `^M` 解析失败。仓库 `.gitattributes` 设 `*.Dockerfile text eol=lf`。

## 面试怎么答

**Q：怎么写一个利于 CI 缓存的 Dockerfile？**

A：核心是把「变动频率低」的指令放前面、「变动频率高」的放后面，因为 Docker 构建是一层一层缓存的，某一层变了它下面所有层缓存全部失效。具体到 Python 测试镜像：先用 `FROM python:3.11-slim` 锁版本基础镜像；装系统依赖合并到一条 RUN 并清掉 apt 缓存；然后**先只 COPY `requirements.txt` 装依赖**，再 COPY 代码——这样改代码不会触发 `pip install` 重装，只有依赖清单变了才重装。最后加 `.dockerignore` 防止把 `.git`/`venv` 打进上下文，用 `--no-cache-dir` 避免 pip 缓存留在镜像里，并以非 root 用户运行。

**Q：多阶段构建解决什么问题？**

A：解决「构建期需要但运行期不需要的东西污染最终镜像」的问题。比如编译 Python 包需要 gcc，但运行时根本用不到。多阶段里，第一阶段装 gcc 编译安装依赖到指定前缀，第二阶段用干净的基础镜像只把产物 COPY 过来，最终镜像不含编译器，体积小、攻击面小。测试框架镜像体积下来了，CI 拉取和启动都更快。

**Q：`.dockerignore` 和 `.gitignore` 有什么关系？**

A：两者完全独立、互不影响。`.gitignore` 决定哪些文件不进 git 仓库；`.dockerignore` 决定 `docker build` 时哪些文件不进构建上下文（也就是不被 `COPY . .` 带进去）。常见错误是以为配了 gitignore 就够了，结果 `.git`、`venv`、日志被 COPY 进镜像，体积暴涨还可能泄露。写 Dockerfile 必须单独配 `.dockerignore`，把 `.git`、`__pycache__`、`venv`、`allure-results` 等排除。

## 参考

- [Dockerfile 最佳实践](https://docs.docker.com/build/building/best-practices/)
- [.dockerignore 文档](https://docs.docker.com/build/concepts/context/#dockerignore-files)
- 相关笔记：[[Docker 镜像与容器核心概念]]、[[Docker 数据卷与网络]]、[[Git .gitignore 规则与失效排查]]、[[GitHub Actions matrix、缓存与 artifact]]
