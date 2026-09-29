# 移动端质量巡检与稳定性脚本工程

本项目包含移动端 Fastbot 智能 Monkey 执行脚本与 Android 原生性能指标静默采集工具。

## 目录文件说明

- `fastbot_run.sh`：自动化部署并运行 Fastbot 智能遍历巡检，自动拉取崩溃与运行日志；
- `perf_collector.py`：基于 Android `dumpsys` 的冷启动耗时、物理内存 PSS 采集工具。

## 快速使用

```bash
# 1. 采集特定真机应用的性能指标
python perf_collector.py --serial <device_id> --package com.mall.app --activity .ui.MainActivity

# 2. 启动 60 分钟智能巡检压测
chmod +x fastbot_run.sh
./fastbot_run.sh <device_id> com.mall.app 60
```
