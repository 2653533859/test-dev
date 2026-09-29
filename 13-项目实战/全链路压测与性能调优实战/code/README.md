# 全链路压测工程配置与脚本

本项目配套压测执行脚本、监控大屏 Docker Compose 配置以及生产级 CLI 压测执行规范。

## 目录文件说明

- `docker-compose.monitoring.yml`：基于 InfluxDB + Grafana 一键拉起压测流式指标监控大屏；
- `jmeter_cli_run.sh`：生产级非 GUI 压测运行脚本，带 JVM 堆参数优化与 HTML 报告生成。

## 快速开始

### 1. 启动压测实时监控看板

```bash
docker compose -f docker-compose.monitoring.yml up -d
```

- InfluxDB 端口：`8086`（预置数据库 `jmeter`）
- Grafana 控制台：`http://localhost:3000`（默认账密 `admin / admin`）
- 在 Grafana 中导入官方 JMeter Dashboard（模板 ID: `5496`），数据源选择 InfluxDB。

### 2. 运行命令行压测

确保已安装 Apache JMeter 5.5+ 并配置环境变量：

```bash
chmod +x jmeter_cli_run.sh
./jmeter_cli_run.sh order_full_link.jmx
```

测试执行完毕后，可在 `reports/<时间戳>/html_report/index.html` 查看综合性能评估报告。
