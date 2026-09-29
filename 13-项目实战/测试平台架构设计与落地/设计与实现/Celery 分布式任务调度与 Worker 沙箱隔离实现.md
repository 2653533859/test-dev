---
created: 2026-09-29
tags: [项目实战/测试平台]
---

# Celery 分布式任务调度与 Worker 沙箱隔离实现

> 解决测试平台并发执行性能与系统稳定性瓶颈：通过 Celery 分布式任务队列 + Redis 优先级路由，结合轻量 Docker 容器化执行沙箱，实现高可用弹性调度与环境彻底隔离。

## 概念

### 为什么必须引入分布式异步调度

如果测试平台直接在 Web 服务的请求-响应主线程中执行自动化用例（例如用户点击「运行」，API 接口阻塞等待 10 分钟直到用例跑完），会导致灾难性后果：

1. **HTTP 连接超时中断**：网关通常有 60 秒的连接超时限制，长跑用例必然导致前端 504 Gateway Timeout；
2. **Web 进程资源耗尽**：一个用例套件拉起浏览器实例或进行密集计算，会吃满 Web 容器的 CPU 和内存，导致其他正常查看报告的用户全部被卡死；
3. **缺乏并发调度与排队能力**：如果 5 个项目同时触发构建，本地进程并发暴增，极易导致测试环境崩溃。

### 架构设计：Celery 异步调度模型

```text
  用户点击运行 / CI Webhook
            │
            ▼
  ┌──────────────────┐
  │  FastAPI 接收端点  │ 立即响应 {"task_id": "uuid-1234", "status": "PENDING"}
  └─────────┬────────┘
            │ 投递异步任务指令 (发布到 Redis Broker)
            ▼
  ┌────────────────────────────────────────────────────────┐
  │                   Redis 消息中间件                      │
  │   [high_priority_queue]   [regression_queue]           │
  │   (单用例即时调试任务)       (全量回归/定时调度批量任务)   │
  └─────────┬───────────────────────────────┬──────────────┘
            │ 抢占消费                      │ 抢占消费
            ▼                               ▼
  ┌──────────────────┐            ┌──────────────────┐
  │ Celery Worker-01 │            │ Celery Worker-02 │
  │ (运行在物理节点 A) │            │ (运行在物理节点 B) │
  └─────────┬────────┘            └─────────┬────────┘
            │ 动态启动隔离容器                      │
            ▼                               ▼
  ┌──────────────────┐            ┌──────────────────┐
  │ Docker Runner 沙箱│            │ Docker Runner 沙箱│
  │ (独立 Python/驱动)│            │ (独立 Python/驱动)│
  └──────────────────┘            └──────────────────┘
```

---

## 用法

### 1. Celery 生产级配置与任务路由

```python
# app/core/celery_app.py
from celery import Celery
from kombu import Queue, Exchange

celery_app = Celery("qa_platform_worker")

# 基础配置
celery_app.conf.update(
    broker_url="redis://:SecurePass123@redis:6379/1",
    result_backend="redis://:SecurePass123@redis:6379/2",
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=False,
    # 核心稳定性参数
    task_acks_late=True,  # 任务执行完成后才发送 ACK，防止 Worker 崩溃丢任务
    task_reject_on_worker_lost=True,  # Worker 异常退出时自动将任务重投回队列
    worker_prefetch_multiplier=1,  # 避免 Worker 一次性抢占过多长耗时用例
    task_time_limit=1800,  # 强制超时时间 30 分钟（防止死循环卡死 Worker）
)

# 优先级多队列路由配置
default_exchange = Exchange("default", type="direct")
celery_app.conf.task_queues = (
    Queue("high_priority", default_exchange, routing_key="task.high"),
    Queue("regression", default_exchange, routing_key="task.regression"),
)
celery_app.conf.task_default_queue = "regression"
```

### 2. 异步执行任务定义与 Docker Runner 调用

```python
# app/tasks/test_runner.py
import subprocess
import json
from celery_app import celery_app


@celery_app.task(bind=True, name="run_test_suite_task")
def run_test_suite_task(self, execution_id: int, suite_config: dict):
    """异步执行测试套件的主任务"""
    self.update_state(state="STARTED", meta={"progress": 5})

    # 将用例配置落盘为临时文件供 Runner 挂载
    config_path = f"/tmp/exec_{execution_id}.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(suite_config, f)

    # 动态拉起独立 Docker Runner 容器执行测试（隔离环境）
    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "--name",
        f"runner_{execution_id}",
        "--network",
        "qa_net",
        "-v",
        f"{config_path}:/app/config.json:ro",
        "-v",
        f"/data/reports/{execution_id}:/app/allure-results",
        "qa-runner-python:latest",
        "python",
        "-m",
        "engine.entrypoint",
        "--config",
        "/app/config.json",
    ]

    try:
        # 执行容器命令并捕获返回码
        process = subprocess.run(
            docker_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        return {"execution_id": execution_id, "exit_code": process.returncode}
    except Exception as exc:
        self.update_state(state="FAILURE", meta={"error": str(exc)})
        raise exc
```

---

## 踩坑

1. **`task_acks_late=False` 导致 Worker 崩溃时任务永久蒸发**：
   - *现象*：服务器突然 OOM 重启了一个 Worker，队列里原本正在排队或执行的 10 个用例全部消失，前端状态永远卡在「RUNNING」；
   - *解法*：必须开启 `task_acks_late = True` 配合 `task_reject_on_worker_lost = True`。只有当 Worker 成功产出报告并退出时才发送 ACK，否则 Redis Broker 会将未完成的任务重新派发给健康的 Worker。
2. **Celery 默认预取过多导致单机倾斜**：
   - *现象*：测试用例耗时差异极大（有的 1 秒，有的 5 分钟）。默认 `worker_prefetch_multiplier=4` 让第一个 Worker 一口气预占了后面 4 个用例，导致其他 Worker 空转闲死。
   - *解法*：将 `worker_prefetch_multiplier` 调为 `1`，实现「跑完一个再抢一个」的公平负载均衡调度。
3. **Redis 结果库未设过期时间导致内存打爆**：
   - *现象*：测试平台跑了 3 个月，Redis 实例内存由 200MB 飙到 8GB 发生 OOM；
   - *根因*：每个用例返回的详尽 JSON 报文被 Celery Result Backend 永久保存在 Redis 中。
   - *解法*：配置 `result_expires = 86400`（仅保留 24 小时临时结果），持久化数据在任务结束前显式回写至 PostgreSQL。

---

## 面试怎么答

**Q：你们测试平台的底层调度引擎是如何设计的？如何保证任务执行的隔离性与并发安全性？**
> 1. **异步解耦与优先级队列**：我们采用 **Celery + Redis** 搭建分布式调度集群，将 Web 交互与繁重的自动化执行完全解耦。设计了「即时调试」和「批量回归」两套独立队列，业务测试在页面单步调试时走高优先级队列毫秒级抢占响应，不被长耗时的全量回归阻塞。
> 2. **Docker 沙箱隔离**：为了杜绝不同自动化测试所依赖的 Playwright、浏览器内核、第三方 Python 库版本冲突，每个测试任务通过 Celery 动态拉起独立的 Docker Runner 容器执行，文件通过只读卷挂载，测试跑完容器自动销毁，确保了极高的运行纯净度与宿主环境安全性。
> 3. **任务自愈与高可用**：开启后置确认（Acks Late）与预取限流（Prefetch=1），即使某个执行节点因宿主机异常宕机，任务也能自动重回队列由其余 Worker 节点接管，保证了夜间数百条回归任务的可靠交付。

---

## 参考

- Celery 生产最佳实践：`https://docs.celeryq.dev/en/stable/userguide/optimizing.html`
- 相关笔记：[[05-自动化测试框架]]、[[11-持续集成]]、[[pytest-xdist 并行执行]]
- 所属项目：[[测试平台架构设计与落地]]
