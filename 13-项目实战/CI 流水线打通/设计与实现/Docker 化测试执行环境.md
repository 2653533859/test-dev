---
created: 2026-07-31
tags: [项目实战/持续集成]
---

# Docker 化测试执行环境

> 让「在我机器上是好的」这句话彻底失效：执行环境跟着代码走，agent 只需要有 Docker。

## 概念

### 要解决的问题

CI 改造初期统计过失败原因，**真正的用例问题只占 4 成**，其余都是环境：

- agent 上是 Python 3.9，本地是 3.11，某个语法直接报错。
- 某个 agent 手工装过 `allure` 命令行，另一个没装，构建随机失败。
- 上一个 Job 残留的 Chrome 进程和 `/tmp` 文件影响下一个 Job。
- 有人在 agent 上 `pip install` 了个新版本库，全组构建当天集体挂。

这类问题的共同点是**不可复现、排查成本高、且会周期性复发**。容器化把执行环境变成一个带版本的镜像制品，agent 退化成「只提供 CPU 和 Docker」的哑资源。

### 两种容器化粒度

| 粒度 | 说明 | 本项目 |
|------|------|--------|
| **执行器容器化** | 跑测试的环境（Python、依赖、浏览器）打成镜像 | 采用 |
| **被测服务容器化** | 用 docker compose 拉起整套待测服务 | 部分采用（核心链路） |

被测服务容器化最干净，但 6 个微服务 + MySQL + Redis + MQ 全拉起要 8 分钟、吃 6G 内存，agent 扛不住并发。最终只对核心链路这么做，其余仍连共享测试环境并靠数据前缀隔离。

## 用法

### 执行器镜像

```dockerfile
FROM python:3.11-slim

# 时区：不设的话容器内是 UTC，报告时间差 8 小时，时间断言凌晨必挂
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 系统依赖：allure 命令行需要 JRE；curl 用于健康检查
RUN apt-get update && apt-get install -y --no-install-recommends \
        default-jre-headless curl unzip \
    && rm -rf /var/lib/apt/lists/*

ARG ALLURE_VERSION=2.29.0
RUN curl -sL -o /tmp/allure.zip \
        "https://github.com/allure-framework/allure2/releases/download/${ALLURE_VERSION}/allure-${ALLURE_VERSION}.zip" \
    && unzip -q /tmp/allure.zip -d /opt && rm /tmp/allure.zip \
    && ln -s /opt/allure-${ALLURE_VERSION}/bin/allure /usr/local/bin/allure

# 依赖单独一层：requirements.txt 没变就命中缓存，构建从 2 分钟降到 10 秒
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 非 root 用户，避免容器内生成的文件在宿主机上属主是 root 导致 cleanWs 失败
RUN useradd -m -u 1000 qa
USER qa

CMD ["pytest", "--version"]
```

`COPY requirements.txt` 单独一层是 Dockerfile 的核心技巧：**变化频率低的放前面**。代码每次都变，依赖很少变，分层后依赖层长期命中缓存。

### 被测服务编排

```yaml
# deploy/docker-compose.test.yml
services:
  mysql:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: ${DB_ROOT_PASSWORD}
      MYSQL_DATABASE: shop_test
    volumes:
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 5s
      timeout: 3s
      retries: 20

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 10

  order-service:
    image: registry.internal/shop/order-service:${SERVICE_TAG:-latest}
    environment:
      SPRING_PROFILES_ACTIVE: test
      TZ: Asia/Shanghai
    depends_on:
      mysql:
        condition: service_healthy      # 等健康检查通过，而不是等容器启动
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/actuator/health"]
      interval: 5s
      timeout: 3s
      retries: 30
    ports:
      - "8080:8080"
```

```bash
# 拉起并等所有服务健康
docker compose -f deploy/docker-compose.test.yml up -d --wait
# 用完彻底清理，-v 连数据卷一起删，避免残留数据影响下次
docker compose -f deploy/docker-compose.test.yml down -v
```

`depends_on` 配 `condition: service_healthy` 是重点：默认的 `depends_on` **只保证容器启动顺序，不保证服务可用**。MySQL 容器起来了但还在初始化，应用连过去直接失败。

### 在 Jenkins 里用

```groovy
agent {
    docker {
        image 'registry.internal/qa/pytest-runner:3.11'
        // 挂 docker.sock 让容器内能操作宿主机 Docker（DooD）
        args '-v /var/run/docker.sock:/var/run/docker.sock -v pip-cache:/root/.cache/pip'
    }
}
```

## 踩坑

1. **容器内时区是 UTC**：报告时间全差 8 小时，且「断言创建时间是今天」的用例在北京时间早上 8 点前必挂——**只在凌晨失败**，排查了很久才反应过来。`ENV TZ` + `/etc/localtime` 软链，两步都要做，只设环境变量对某些 C 库不生效。

2. **`docker run` 生成的文件属主是 root**：Jenkins 的 `cleanWs()` 以普通用户运行，删不掉 root 属主的 `allure-results`，workspace 越堆越大。Dockerfile 里创建与宿主机 Jenkins 用户同 UID（通常 1000）的用户并 `USER qa`。

3. **镜像 tag 用 `latest`**：某天基础镜像更新，Python 小版本变了，一个依赖不兼容，全组构建挂掉且**无法回滚到昨天的环境**。所有镜像锁具体版本号，包括 `FROM`。

4. **`depends_on` 不等于服务就绪**：见上文，必须配 healthcheck + `condition: service_healthy`。用 `sleep 30` 顶替是常见但错误的做法——环境快时白等，慢时照样失败。

5. **不清理容器导致端口占用和磁盘打满**：`down -v` 放进 `post { always }`，且加 `|| true` 保证清理失败不影响构建结论。另外定期 `docker system prune`，悬空镜像积累得比想象中快。

6. **每次构建重装依赖耗时 2 分钟**：把 pip 缓存挂成 named volume，装依赖降到 15 秒。GitHub Actions 侧用 `actions/setup-python` 的 `cache: pip`。

7. **DooD 的路径陷阱**：容器内挂 docker.sock 操作宿主机 Docker 时，`-v $(pwd):/app` 里的 `$(pwd)` 是**容器内路径**，宿主机上并不存在，挂载会得到空目录。要用 `WORKSPACE` 环境变量传宿主机真实路径。

8. **镜像体积失控**：一开始用 `python:3.11`（约 1G），换 `slim` 后降到 400M 左右；`apt-get` 后不清 `/var/lib/apt/lists` 会白白多几十 M；`pip install --no-cache-dir` 同理。镜像小意味着每次拉取快，直接影响流水线时长。

## 面试怎么答

**Q：为什么要把测试执行环境容器化？**

A：解决「在我机器上是好的」。我们统计过 CI 改造初期的失败原因，真正的用例问题只占 4 成，其余都是环境差异——agent 上 Python 版本不对、某个包没装、上个任务残留进程。这类问题不可复现、排查成本高还会周期性复发。容器化后执行环境变成带版本的镜像制品，跟着代码走，agent 只需要提供 Docker。

**Q：Docker 镜像怎么优化构建速度和体积？**

A：分层缓存是核心——把变化频率低的放前面，`COPY requirements.txt` 单独一层再 `pip install`，依赖没变就命中缓存，我们这里从 2 分钟降到 10 秒。体积上用 slim 或 alpine 基础镜像、`apt-get` 后清理 lists、`pip install --no-cache-dir`、合并 RUN 层减少层数；编译型项目还可以用多阶段构建只保留产物。

**Q：docker compose 里怎么保证服务启动顺序？**

A：`depends_on` 只保证容器启动顺序，不保证服务可用——MySQL 容器起来了可能还在初始化。正确做法是给每个服务配 healthcheck，`depends_on` 用 `condition: service_healthy`，再配合 `up -d --wait`。不要用 `sleep 30` 顶替，环境快时白等、慢时照样失败。

**Q：容器化有什么坑？**

A：印象最深的是时区。容器默认 UTC，报告时间差 8 小时还算小事，麻烦的是「断言创建时间是今天」这类用例**只在北京时间早上 8 点前失败**，白天怎么都复现不了，查了很久。另一个是文件属主问题——容器内以 root 生成的文件，宿主机上的 Jenkins 用户删不掉，workspace 一直堆积，需要在镜像里创建同 UID 的非 root 用户。

## 参考

- Dockerfile 最佳实践：`https://docs.docker.com/develop/develop-images/dockerfile_best-practices/`
- Compose healthcheck：`https://docs.docker.com/reference/compose-file/services/#healthcheck`
- 相关笔记：[[11-持续集成]]、[[多环境配置与环境隔离]]
- 同项目：[[Jenkinsfile 多阶段流水线设计]]、[[质量门禁与失败通知策略]]
- 所属项目：[[CI 流水线打通]]
