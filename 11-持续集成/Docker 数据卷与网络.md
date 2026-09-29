---
created: 2026-07-31
tags: [持续集成/Docker]
---

# Docker 数据卷与网络

> 容器里的文件是临时的，数据要留、容器间要通——这分别是「卷」和「网络」要解决的事。测试里它们用来持久化测试数据、连通被测服务。

## 概念

### 为什么需要卷（Volume）

前面讲过，容器在镜像之上加一层可写层，容器删了这层就没了。但测试经常需要**持久化的东西**：

- 数据库的数据文件（不想每次起库都重新初始化）
- 测试产生的日志、截图、Allure 结果（要看、要归档）
- 复用依赖缓存（如 Maven/pip 的 `~/.cache`）

Docker 提供三种数据挂载方式：

- **volume（命名卷）**：Docker 管理的持久化存储，生命周期独立于容器，最推荐
- **bind mount（绑定挂载）**：把宿主机的某个目录挂进容器，调试/看结果最方便
- **tmpfs**：只存内存，容器停就丢，适合临时敏感数据

核心区别：bind mount 是「宿主机路径 ↔ 容器路径」的映射，你看得到文件在宿主机哪；volume 是 Docker 在 `/var/lib/docker/volumes/` 下管理的，路径对你透明、更适合数据库这类「我不关心文件在哪、只要它持久」的场景。

### 为什么需要网络

容器默认在各自的网络命名空间里，彼此隔离。多容器协作（如「被测应用 + MySQL + Redis」）需要它们能互相访问。Docker 的网络驱动：

- **bridge（默认）**：同一 bridge 网络内容器可通过**容器名**互访
- **host**：容器直接用宿主机网络，无隔离（性能高但不安全）
- **none**：无网络

测试编排最常用自建 bridge 网络，让 `app` 能 `ping mysql` 而不是靠 `--link`（已废弃）。

## 用法

### 一、卷与绑定挂载

```bash
# 命名卷：数据库数据持久化
docker run -d --name test-mysql -v mysql-data:/var/lib/mysql mysql:8.0

# 绑定挂载：把宿主机当前目录的 logs 挂进容器，方便看结果
docker run -d --name myapi -v $(pwd)/logs:/app/logs myapi:1.0

# 只读挂载（防止容器误改宿主机文件）
docker run -v $(pwd)/config:/app/config:ro myapi:1.0

# 查看与管理卷
docker volume ls
docker volume inspect mysql-data
docker volume rm mysql-data
```

CI 里日志、截图用 bind mount 挂出来，构建后直接 `archiveArtifacts`（见 [[Jenkins Allure 报告与构建后通知]]）。

### 二、自建网络让容器互通

```bash
# 建一个专用桥接网络
docker network create test-net

# 起 MySQL 和 被测应用，都连这个网络
docker run -d --name mysql --network test-net -e MYSQL_ROOT_PASSWORD=123 mysql:8.0
docker run -d --name app --network test-net -e DB_HOST=mysql myapp:1.0
```

容器内 `app` 可以直接用主机名 `mysql` 访问数据库，因为同一 bridge 网络内有内建的 DNS 解析。比已废弃的 `--link` 更干净。

### 三、在测试代码里用容器化的依赖

```python
# pytest 中按需起一个 Redis 容器做集成测试
import subprocess, time, redis

def test_cache():
    subprocess.run(["docker", "run", "-d", "--name", "t-redis",
                    "--network", "test-net", "redis:7"], check=True)
    time.sleep(2)                      # 等就绪（生产用 healthcheck 而非 sleep）
    r = redis.Redis(host="t-redis", port=6379)
    r.set("k", "v")
    assert r.get("k") == b"v"
    subprocess.run(["docker", "rm", "-f", "t-redis"])
```

### 四、host 网络与端口映射的区别

```bash
# bridge 模式：容器内部端口映射到宿主机端口，外部通过宿主机 IP:端口 访问
docker run -p 8080:8080 myapp:1.0

# host 模式：直接用宿主机网络栈，不需 -p，性能略好但不隔离
docker run --network host myapp:1.0
```

host 模式在 CI 单机上跑单套测试方便，但多套并行时会端口冲突，且隔离性差，慎用。

## 踩坑

1. **容器数据没挂卷，删容器数据全丢**。MySQL 容器 `docker rm` 后测试数据没了，下次又得重新灌。凡是「删了还想留」的，挂 volume 或 bind mount。

2. **bind mount 路径写错导致空挂载**。`-v logs:/app/logs` 没写绝对路径，Docker 会把它当成一个叫 `logs` 的命名卷而非宿主机目录，日志没落到你期望的地方。宿主机路径用绝对路径（如 `$(pwd)/logs`）。

3. **不同容器同名卷互相污染**。多个测试并行用同一个卷名 `mysql-data`，数据串了。CI 用唯一后缀或每次 `docker volume rm` 干净的卷。

4. **跨网络容器连不上**。app 在 `test-net`、mysql 在默认 `bridge`，互相 ping 不通。要么都连同一自定义网络，要么用 `--network` 明确指定。

5. **用 IP 而非容器名访问**。IP 是动态分配的，重启就变。同一 bridge 网络内一律用**容器名**做主机名。

6. **host 模式端口冲突**。单机多套并行测试用 `--network host` 跑，端口争抢导致一半起不来。优先 bridge + 动态端口，或每套用独立网络。

7. **`--link` 已废弃还再用**。新的 Docker 版本已弃用 `--link`，用自定义网络替代。

8. **忘了清理卷，磁盘爆满**。CI 频繁建卷不删，`/var/lib/docker/volumes` 堆积。`docker volume prune` 定期清无主卷。

9. **Windows/macOS 上 bind mount 性能差**。挂大目录（如 node_modules）在 Docker Desktop 上 I/O 慢。尽量用命名卷承载频繁读写的目录。

10. **权限问题：容器以非 root 写 bind mount 报 Permission denied**。宿主机目录属主是 root，容器内用户没权限写。要么改目录权限，要么容器用户和宿主机 uid 对齐。

## 面试怎么答

**Q：Docker 的 volume 和 bind mount 有什么区别，什么时候用哪个？**

A：两者都是把容器外的存储挂进容器，但用途不同。volume 是 Docker 管理的命名卷，路径对使用者透明，生命周期独立于容器，适合「我不关心文件在哪、只要持久」的场景，比如数据库数据文件。bind mount 是把宿主机的一个具体目录挂进去，你能直接在宿主机上看文件，适合调试和看结果，比如把测试日志、Allure 报告挂出来构建后归档。一个常见坑是 bind mount 必须写绝对路径，写相对路径 Docker 会误当成命名卷，日志就落错地方了。另外不同测试并行别用同名卷，会数据串。

**Q：多个容器之间怎么互相访问？**

A：把它们连到同一个自定义的 bridge 网络，Docker 会提供内建 DNS，容器之间直接用容器名互访，比如 app 容器配 `DB_HOST=mysql` 就能连上同网络的 mysql 容器。不要用已废弃的 `--link`。关键是用容器名而不是 IP，因为 IP 是动态分配的，重启就变。生产编排里这套逻辑由 docker compose 自动搞定。

**Q：测试里怎么管理被测服务的依赖？**

A：我用 Docker 起被测服务，比如 MySQL、Redis 用容器跑，通过自定义网络让被测应用和它们互通；测试产生的日志和截图用 bind mount 挂到宿主机，构建后归档看结果。注意数据持久化和清理：数据库数据挂 volume，避免每次重新初始化；CI 每次跑完要 `docker rm -f` 和 `volume prune`，防止磁盘爆满和并行数据串。等依赖就绪用 healthcheck 而不是 sleep，更稳。

## 参考

- [Docker Volume 文档](https://docs.docker.com/engine/storage/volumes/)
- [Docker Network 文档](https://docs.docker.com/engine/network/)
- 相关笔记：[[Docker 镜像与容器核心概念]]、[[Dockerfile 编写与镜像构建优化]]、[[docker compose 编排测试环境]]、[[Jenkins Allure 报告与构建后通知]]
