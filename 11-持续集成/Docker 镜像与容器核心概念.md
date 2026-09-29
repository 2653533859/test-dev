---
created: 2026-07-31
tags: [持续集成/Docker]
---

# Docker 镜像与容器核心概念

![[assets/docker-image-layers.svg]]
*图示：镜像由多层只读层叠加（COPY/RUN 各产生一层），容器在镜像之上加一层可写层；改同一文件只在新层覆盖；构建时某层变了，其下所有层缓存失效。*

## 概念

### 为什么测试开发必须懂 Docker

测试最痛的问题之一是「**在我机器上能跑**」。开发、测试、CI 三套环境，Python 版本、依赖、系统库不一致，用例本地绿、CI 红，排查半天是缺了个 `libxml2`。Docker 把「应用 + 它依赖的一切」打成**不可变的镜像**，在哪里跑都是同一份，从根本上消灭环境漂移。

对测试开发的三个高频用途：

- 把自动化框架打成镜像，CI 里 `docker run` 即用，无需在 runner 上装 Python/依赖
- 起一套被测服务（数据库、中间件、被测应用）做集成测试
- 固定浏览器版本跑 UI 自动化，避免 runner 上升级导致用例集体失败

### 镜像 vs 容器

- **镜像（Image）**：只读模板，相当于「类」或「安装包」，由多层（layer）叠加而成
- **容器（Container）**：镜像的运行实例，相当于「对象」，在镜像之上加了一层**可写层**

`docker run` 做的事：拿镜像 → 在它上面叠一个可写层 → 启动进程。你改文件、写日志都发生在这层可写层；容器删了，这层也没了，镜像本身不变。

### 分层与写时复制（Copy-on-Write）

镜像是分层的：Dockerfile 里每条 `RUN`/`COPY`/`ADD` 产生一层，层只读、可复用、可缓存。容器启动时：

- 读操作：直接读镜像的只读层
- 写操作：先**复制**要改的文件到可写层再改（copy-on-write），原始只读层不受影响

这就是为什么「同一个镜像起 100 个容器」不占 100 倍空间——只读层共享，只多 100 个薄薄的可写层。

## 用法

### 一、最常用的镜像/容器命令

```bash
# 拉取与查看
docker pull python:3.11-slim
docker images                      # 本地镜像列表
docker image inspect python:3.11-slim

# 运行容器（关键参数）
docker run -d --name myapi -p 8080:8080 -e ENV=test -v $(pwd)/logs:/app/logs myapi:1.0
docker ps                          # 运行中的容器
docker ps -a                       # 含已退出的
docker logs -f myapi               # 看日志
docker exec -it myapi bash         # 进容器排错

# 清理
docker stop myapi && docker rm myapi
docker rmi myapi:1.0               # 删镜像（有容器依赖则先删容器）
docker system prune -f             # 清掉悬空镜像/停掉的容器（CI 常用）
```

### 二、用现有镜像跑测试环境

```bash
# 起一个 MySQL，供接口自动化连
docker run -d --name test-mysql \
  -e MYSQL_ROOT_PASSWORD=test123 \
  -e MYSQL_DATABASE=testdb \
  -p 3306:3306 \
  mysql:8.0

# 等它健康再跑用例（CI 里用 wait-for-it 或 docker compose 的 healthcheck）
```

### 三、把自动化框架打成镜像

```dockerfile
# 见 [[Dockerfile 编写与镜像构建优化]]，这里只演示怎么用
docker build -t qa-auto:1.0 -f Dockerfile.test .
docker run --rm qa-auto:1.0 pytest tests/api -m smoke
```

镜像是不可变的：同一 `qa-auto:1.0` 在任何人、任何机器上跑，环境完全一致。这正是它解决「环境漂移」的终极手段。

### 四、理解分层对排错的意义

```bash
docker history myapi:1.0           # 看每一层怎么来的、占多大
docker diff mycontainer            # 看容器可写层相对镜像改了哪些文件
```

`docker history` 能定位「哪一层把镜像搞大了」；`docker diff` 能看容器运行时产生了什么临时文件，帮你决定哪些该写进 volume 而不是污染镜像。

## 踩坑

1. **「在我机器上能跑」搬到容器里失败**。容器内是精简系统（slim/alpine），缺 `libxml2`、`libssl` 等系统库，pip 装的包运行时报错。解决：在 Dockerfile 里 `apt-get install` 补齐，或换非 slim 基础镜像。

2. **alpine 的 musl 与很多 wheel 不兼容**。Python 包在 alpine（musl libc）上常编译失败或运行时崩。测试镜像建议用 `python:3.11-slim`（Debian/glibc）而非 alpine，除非你明确要小体积。

3. **容器里改了文件，重启就没了**。因为改在可写层，容器删除即丢失。需要持久化的（数据库数据、日志、截图）必须挂 volume（见 [[Docker 数据卷与网络]]）。

4. **镜像越积越大撑爆磁盘**。CI 频繁 build，悬空镜像和停掉的容器堆积。`docker system prune` 定期清，或在 CI 末尾 `docker rmi` 本次构建的镜像。

5. **`latest` 标签导致环境漂移**。今天 `python:latest` 是 3.12，明天是 3.13，用例集体行为变化。所有基础镜像**锁版本**：`python:3.11-slim`，必要时锁 digest（`python:3.11-slim@sha256:...`）。

6. **容器进程退出了但 `docker ps` 看不到**。因为主进程跑完就退出了（比如 `pytest` 跑完），容器变成 `Exited`。这是正常的，`docker logs` 看结果；想保持运行加 `-d` 且主进程是长驻服务。

7. **端口映射冲突**。`-p 8080:8080` 本地 8080 已被占会启动失败。CI 用动态端口或确保每次 `docker rm` 干净。

8. **Windows 上路径/换行符问题**。Dockerfile 用 CRLF 会导致 `exec format error`，需在仓库 `.gitattributes` 里设 `*.Dockerfile text eol=lf`（也见 [[Git .gitignore 规则与失效排查]]）。

9. **容器时区不对，时间相关用例失败**。基础镜像默认 UTC，依赖「当前时间」的测试会差 8 小时。Dockerfile 里设 `ENV TZ=Asia/Shanghai` 并装 `tzdata`。

10. **`docker exec` 进去看到的环境和用例跑的不一样**。exec 进的是已有容器，但用例可能是新起的容器/不同镜像。排错要进「实际跑用例的那个容器」，最好直接看 CI 日志而非本地 exec 猜。

## 面试怎么答

**Q：镜像和容器有什么区别？**

A：镜像是个只读的模板，相当于安装包或者类；容器是镜像运行起来的实例，相当于对象。镜像由多层只读层叠加，容器在镜像之上加了一层可写层，你运行时改文件、写日志都在这层。容器删掉，可写层也没了，镜像本身不变。正因为只读层是共享的，同一个镜像起一百个容器不会占一百倍空间，只多了薄薄的可写层。这也是测试里它价值巨大的原因——镜像不可变，在谁机器上跑环境都一样，彻底消灭「在我机器上能跑」。

**Q：Docker 解决了测试中的什么问题？**

A：最核心的是环境一致性。测试最痛的「本地绿、CI 红」大半是环境不一致：Python 版本、依赖、系统库差一点就表现不同。Docker 把框架和依赖一起打成不可变镜像，在哪跑都一致。对测试开发三个高频用途：把自动化框架打成镜像，CI 里直接 run 不用装环境；起被测服务（数据库、中间件）做集成测试；固定浏览器版本跑 UI 避免 runner 升级导致用例集体失败。另外分层机制让镜像可缓存、可复用，CI 构建也快。

**Q：什么是镜像分层，对 CI 有什么影响？**

A：Dockerfile 里每条 RUN/COPY/ADD 产生一个只读层，层可以缓存和复用。构建时如果某一层变了，它下面所有层缓存失效需要重建，所以它上面所有层都要重新执行——这就是为什么 Dockerfile 里要把「少变动的指令」放前面、「常变动的代码 COPY」放后面，让缓存命中率最高。排错时 `docker history` 能看每层占多大、`docker diff` 能看容器运行时改了哪些文件，帮助定位镜像膨胀和该挂 volume 的内容。

## 参考

- [Docker 官方文档：Images](https://docs.docker.com/get-started/docker-concepts/the-basics/what-is-an-image/)
- [Docker 官方文档：Containers](https://docs.docker.com/get-started/docker-concepts/the-basics/what-is-a-container/)
- 相关笔记：[[Dockerfile 编写与镜像构建优化]]、[[Docker 数据卷与网络]]、[[docker compose 编排测试环境]]、[[Git .gitignore 规则与失效排查]]
