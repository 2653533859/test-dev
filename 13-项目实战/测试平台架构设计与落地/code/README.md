# 测试平台工程脚手架与容器配置

本项目提供企业级自动化测试平台的核心后端架构与分布式调度引擎的最小可运行拓扑。

## 目录文件说明

- `docker-compose.yml`：集成部署 FastAPI Web 后端、Celery 分布式任务调度节点、PostgreSQL 数据库与 Redis 消息中间件；
- `requirements.txt`：核心依赖清单（FastAPI + Pydantic v2 + Celery + SQLAlchemy）。

## 架构核心职责

1. **Web API (`app/`)**：提供用例资产树维护、执行计划编排与 WebSocket 实时日志流推流；
2. **Celery Worker**：监听 Redis 优先级任务队列，按需动态拉起轻量级 Runner 沙箱容器执行用例并回写报告；
3. **PostgreSQL**：持久化项目空间、测试用例元数据、执行历史与多维质量度量指标。

## 本地启动与联调

```bash
# 启动所有核心支撑容器
docker compose up -d

# 查看 API 交互式文档
# 访问 http://localhost:8000/docs
```
