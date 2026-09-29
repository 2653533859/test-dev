#!/usr/bin/env python3
"""
移动端核心性能数据（FPS/PSS/启动时间）自动化采集工具
"""

import argparse
import json
import re
import subprocess
import time


def run_adb(serial: str, cmd: str) -> str:
    full_cmd = f"adb -s {serial} {cmd}"
    res = subprocess.run(
        full_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    return res.stdout.strip()


def get_cold_launch_time(serial: str, package: str, activity: str) -> int:
    """采集冷启动耗时 TotalTime (ms)"""
    # 强制杀死进程确保冷启动
    run_adb(serial, f"shell am force-stop {package}")
    time.sleep(1)
    out = run_adb(serial, f"shell am start -W -n {package}/{activity}")
    for line in out.splitlines():
        if "TotalTime:" in line:
            return int(line.split(":")[1].strip())
    return -1


def get_pss_memory(serial: str, package: str) -> int:
    """采集进程物理内存占用 PSS (KB)"""
    out = run_adb(serial, f"shell dumpsys meminfo {package}")
    for line in out.splitlines():
        if "TOTAL PSS:" in line:
            match = re.search(r"TOTAL\s+PSS:\s+(\d+)", line)
            if match:
                return int(match.group(1))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Android Performance Collector")
    parser.add_argument("--serial", required=True, help="设备序列号")
    parser.add_argument("--package", required=True, help="目标应用包名")
    parser.add_argument(
        "--activity", default=".ui.MainActivity", help="启动 Activity"
    )
    args = parser.parse_args()

    print(f"正在为设备 {args.serial} 采集应用 {args.package} 性能数据...")
    cold_time = get_cold_launch_time(args.serial, args.package, args.activity)
    pss_kb = get_pss_memory(args.serial, args.package)

    metrics = {
        "device": args.serial,
        "package": args.package,
        "cold_launch_ms": cold_time,
        "pss_mb": round(pss_kb / 1024.0, 2),
        "timestamp": int(time.time()),
    }
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
