#!/usr/bin/env bash
# ==============================================================================
# 全链路性能压测执行脚本（Linux 无头 CLI 模式）
# ==============================================================================
set -euo pipefail

SCENARIO="${1:-order_full_link.jmx}"
REPORT_DIR="reports/$(date +%Y%m%d_%H%M%S)"
JTL_FILE="${REPORT_DIR}/result.jtl"
HTML_DIR="${REPORT_DIR}/html_report"

echo "=========================================="
echo "  启动 JMeter 压测场景: ${SCENARIO}"
echo "  输出目录: ${REPORT_DIR}"
echo "=========================================="

mkdir -p "${REPORT_DIR}"

# 施压机内核与 JVM 堆优化参数配置
export HEAP="-Xms4g -Xmx4g -XX:MaxMetaspaceSize=512m -XX:+UseG1GC -XX:MaxGCPauseMillis=100"

# 非 GUI 命令行执行
# -n: 非 GUI 模式
# -t: 测试脚本路径
# -l: 原始采样结果 JTL 文件
# -e: 测试完成后生成 HTML Dashboard
# -o: HTML 报告输出目录
# -J: 传入动态变量（目标并发、压测持续时长）
jmeter -n \
  -t "${SCENARIO}" \
  -l "${JTL_FILE}" \
  -e -o "${HTML_DIR}" \
  -Jthreads=500 \
  -Jduration=300 \
  -Jinflux_host=127.0.0.1 \
  -Jinflux_port=8086

echo "=========================================="
echo "  压测完成！"
echo "  HTML 报告已生成至: ${HTML_DIR}/index.html"
echo "=========================================="
