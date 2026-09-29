#!/usr/bin/env bash
# ==============================================================================
# Fastbot 智能 Monkey 稳定性压测执行脚本
# ==============================================================================
set -euo pipefail

SERIAL="${1:-}"
PACKAGE="${2:-com.mall.app}"
DURATION="${3:-60}"

if [ -z "${SERIAL}" ]; then
    echo "用法: $0 <device_serial> [package_name] [duration_minutes]"
    exit 1
fi

echo "=========================================="
echo "  启动 Fastbot 巡检: 设备 ${SERIAL}"
echo "  目标包名: ${PACKAGE} | 持续时长: ${DURATION} 分钟"
echo "=========================================="

# 扩大 logcat 缓冲区以防崩溃日志冲刷丢失
adb -s "${SERIAL}" logcat -G 16M
adb -s "${SERIAL}" logcat -c

# 启动 Fastbot
adb -s "${SERIAL}" shell CLASSPATH=/data/local/tmp/monkey.jar:/data/local/tmp/fastbot-thirdpart.jar \
    exec app_process /data/local/tmp com.android.commands.monkey.Monkey \
    -p "${PACKAGE}" \
    --agent reuseq \
    --running-minutes "${DURATION}" \
    --throttle 300 \
    --output-directory /sdcard/fastbot_output/ \
    -v -v

echo "=========================================="
echo "  Fastbot 执行完毕，拉取崩溃与运行日志..."
echo "=========================================="
mkdir -p reports/fastbot_logs/
adb -s "${SERIAL}" pull /sdcard/fastbot_output/ reports/fastbot_logs/
adb -s "${SERIAL}" logcat -d -b crash > "reports/fastbot_logs/crash_${SERIAL}.log"
