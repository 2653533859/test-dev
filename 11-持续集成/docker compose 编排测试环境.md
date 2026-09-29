---
created: 2026-07-31
tags: [持续集成/Docker]
---

# docker compose 编排测试环境

> 一整套被测环境 = 被测应用 + 数据库 + 缓存 + Mock 服务。手写一堆 `docker run` 既难记又易错。docker compose 用一份 YAML 把它们编排成一个整体，一条命令起停。

## 概念

### 为什么测试要用 compose

做接口/集成测试时，被测系统往往依赖一堆周边服务：MySQL 存数据、Redis 做缓存、也许还有个消息队列、一个 Mock 第三方支付的桩服务。如果每次测试都手敲五六个 `docker run`，参数一长就乱，而且谁先起、谁后起、谁等谁就绪都没法表达。

docker compose 把「多容器应用」定义成一份声明式 YAML：`services` 列出每个容器、`networks` 定义它们怎么互通、`volumes` 定义数据怎么持久、`depends_on` 表达启动顺序、`healthcheck` 表达就绪条件。一条 `docker compose up` 全部起好，一条 `docker compose down` 全部清掉。它在 CI 里尤其有价值——每次构建拉起一套干净的被测环境，跑完即毁。

### compose 和 k8s 的定位区别

compose 是单机、开发/测试/CI 用的轻量编排；k8s 是生产级多机编排。测试环境用 compose 足够，别为了「显得高级」上 k8s，反而增加维护成本。

## 用法

### 一、一份接口自动化测试环境的 compose

```yaml
# docker-compose.test.yaml
version: "3.8"
services:
  mysql:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: test123
      MYSQL_DATABASE: testdb
    ports:
      - "3306:3306"
    volumes:
      - mysql-data:/var/lib/mysql
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    healthcheck:                # 关键：声明就绪条件
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-ptest123"]
      interval: 5s
      timeout: 3s
      retries: 10

  redis:
    image: redis:7
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 10

  app:                          # 被测应用
    build: ./app
    depends_on:
      mysql:
        condition: service_healthy    # 等 mysql 真正就绪再起
      redis:
        condition: service_healthy
    environment:
      DB_HOST: mysql
      REDIS_HOST: redis
    ports:
      - "8080:8080"

volumes:
  mysql-data:
```

### 二、在 CI 里起环境 + 跑测试 + 清环境

```groovy
// Jenkinsfile 片段（见 [[Jenkinsfile Pipeline 语法]]）
stage('启动测试环境') {
    steps {
        sh 'docker compose -f docker-compose.test.yaml up -d --wait'   // --wait 等所有 healthcheck 通过
    }
}
stage('接口测试') {
    steps { sh 'pytest tests/api -m smoke' }
}
post {
    always {
        sh 'docker compose -f docker-compose.test.yaml down -v || true'  // -v 连同卷一起清
    }
}
```

`--wait` 会等所有 service 的 healthcheck 通过才返回，比手写 `sleep 30` 可靠得多。

### 三、用 compose 跑测试框架本身

```yaml
# 把自动化框架也作为 service，依赖被测环境
services:
  mysql: { /* 同上 */ }
  app:   { /* 同上 */ }
  tester:
    build:
      context: .
      dockerfile: Dockerfile.test
    depends_on:
      app:
        condition: service_healthy
    environment:
      BASE_URL: http://app:8080
    command: pytest tests/api -m smoke --alluredir=/results
    volumes:
      - ./allure-results:/results     # 结果挂出来归档
```

这样「测试执行」也是容器，整个环境完全自包含，`docker compose up --abort-on-container-exit` 跑完即出结果。

### 四、多套环境并行不冲突

```yaml
# 用 -p 指定项目名，隔离网络/卷，避免并行串数据
docker compose -p ci-42 -f docker-compose.test.yaml up -d
docker compose -p ci-42 down -v
```

CI 里用构建号当项目名前缀，多份并行互不干扰。

## 踩坑

1. **`depends_on` 默认只等「启动」不等「就绪」**。app 依赖 mysql，但 mysql 刚起还在初始化，app 就连上去报错。必须配合 `condition: service_healthy` + healthcheck，或用 `--wait`。

2. **没写 `healthcheck`，`--wait` 立刻返回**。服务进程起了但还没就绪，测试连上去失败。healthcheck 的 `test` 命令要真能反映就绪（如 `mysqladmin ping` 而非 `echo ok`）。

3. **`down` 没加 `-v`，卷残留导致数据串**。下次 `up` 复用旧卷，带着上次测试数据。CI 清环境务必 `down -v`。

4. **并行多套用默认项目名冲突**。两份 compose 都叫默认项目名，网络名撞、卷名撞。CI 用 `-p ci-<build号>` 隔离。

5. **`build` 的 service 每次都重新构建慢**。加 `--build` 才重建，否则用已有镜像；CI 想保证最新加 `--build`，但本地调试可不加。注意缓存和 `--no-cache` 的使用。

6. **端口映射到宿主机冲突**。多套并行都映射 `8080:8080` 会冲突。要么用 `-p` 隔离网络但仍映射同宿主机端口——还是冲突。解决：并行时用不同宿主机端口，或干脆不映射端口、用 compose 内部网络互访。

7. **`command` 覆盖导致容器立刻退出**。在 service 里写了 `command: pytest` 且没 `--keep-alive`，pytest 跑完容器退出，`depends_on` 它的其它服务也起不来。长驻服务用 `command: tail -f /dev/null` 之类保活，或测试容器单独跑。

8. **Windows 换行符让 YAML 解析失败**。`docker-compose.test.yaml` 存成 CRLF，compose 报 YAML 错误。仓库 `.gitattributes` 设 `*.yaml text eol=lf`。

9. **`version` 字段过时警告**。新版 compose 已不强制 `version`，写了旧版本号会告警；新项目可省略 `version`。

10. **环境变量在 compose 里注入但被测应用读不到**。compose 的 `environment` 是给容器进程的环境变量，应用要自己读；若应用读配置文件而非环境变量，要在 Dockerfile 或 entrypoint 里做转换。

## 面试怎么答

**Q：docker compose 在测试里怎么用？**

A：我把被测系统的一整套依赖——比如被测应用、MySQL、Redis、Mock 桩服务——写进一份 compose YAML，用 services 定义每个容器、networks 让它们互通、volumes 持久化数据、depends_on 表达启动顺序。CI 里一条 `docker compose up -d --wait` 拉起整套干净的被测环境，`--wait` 会等所有 healthcheck 通过才返回，比手写 sleep 可靠；跑完在 post 的 always 里 `docker compose down -v` 把环境和卷一起清掉，避免数据残留。整个「环境即代码」，新人一条命令就能复现测试环境。

**Q：`depends_on` 能保证人家就绪了吗？**

A：不能，这是最常见的误解。`depends_on` 默认只保证「启动顺序」——mysql 容器进程起来了 app 才起，但 mysql 可能还在初始化建库，app 连上去就失败。正确做法是给被依赖的服务加 `healthcheck` 声明就绪条件，比如 mysql 用 `mysqladmin ping`，然后 `depends_on` 里写 `condition: service_healthy`，或者用 `docker compose up --wait` 等所有 healthcheck 通过。healthcheck 的探测命令要真能反映就绪，不能写个 `echo ok` 糊弄。

**Q：CI 里多套测试并行怎么避免互相干扰？**

A：核心是用项目名隔离。`docker compose` 默认所有资源都挂在同一个项目名下，多份并行会网络名、卷名撞车。CI 里我用构建号当项目名前缀，比如 `docker compose -p ci-42 -f docker-compose.test.yaml up`，每份都在独立的网络、卷里，互不干扰；跑完 `docker compose -p ci-42 down -v` 精准清理自己那份。另外端口映射要注意，多套都映射宿主机 8080 仍会冲突，尽量用 compose 内部网络互访、不映射宿主机端口。

## 参考

- [Docker Compose 官方文档](https://docs.docker.com/compose/)
- [Compose healthcheck 配置](https://docs.docker.com/compose/healthcheck/)
- 相关笔记：[[Docker 镜像与容器核心概念]]、[[Docker 数据卷与网络]]、[[Dockerfile 编写与镜像构建优化]]、[[Jenkinsfile Pipeline 语法]]
