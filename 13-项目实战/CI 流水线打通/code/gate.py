"""质量门禁：解析 JUnit XML，按通过率与 P0 失败数决定是否阻断。

关键点：退出码是门禁的全部。打印得再漂亮，只要 sys.exit(0)，CI 就认为通过。
设计说明见笔记《质量门禁与失败通知策略》。
"""

import argparse
import sys
import xml.etree.ElementTree as ET


def parse_junit(path: str) -> dict:
    root = ET.parse(path).getroot()
    suites = list(root.iter("testsuite")) if root.tag == "testsuites" else [root]

    total = failures = errors = skipped = 0
    failed_cases = []

    for s in suites:
        total += int(s.get("tests", 0))
        failures += int(s.get("failures", 0))
        errors += int(s.get("errors", 0))
        skipped += int(s.get("skipped", 0))

        for case in s.iter("testcase"):
            node = case.find("failure")
            if node is None:
                node = case.find("error")
            if node is not None:
                failed_cases.append({
                    "name": f"{case.get('classname')}::{case.get('name')}",
                    "message": (node.get("message") or "").strip()[:200],
                    "time": float(case.get("time", 0)),
                })

    executed = total - skipped
    pass_rate = (executed - failures - errors) / executed * 100 if executed else 0.0

    return {
        "total": total,
        "executed": executed,
        "skipped": skipped,
        "failures": failures + errors,
        "pass_rate": pass_rate,
        "failed_cases": failed_cases,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="CI 质量门禁")
    p.add_argument("--junit", required=True, help="JUnit XML 路径")
    p.add_argument("--min-pass-rate", type=float, default=98.0)
    p.add_argument("--max-p0-failures", type=int, default=0)
    args = p.parse_args()

    r = parse_junit(args.junit)
    # P0 用例通过 pytest 标记体现在用例名里，这里做简单匹配；
    # 更严谨的做法是从 allure-results 的 labels 里读标记。
    p0_failed = [c for c in r["failed_cases"] if "p0" in c["name"].lower()]

    print("=" * 60)
    print(f"用例总数 {r['total']}，执行 {r['executed']}，跳过 {r['skipped']}")
    print(f"失败 {r['failures']} 条，通过率 {r['pass_rate']:.2f}%")
    print(f"P0 失败 {len(p0_failed)} 条")
    print("=" * 60)

    for c in r["failed_cases"][:10]:
        print(f"  FAIL {c['name']}\n       {c['message']}")
    if len(r["failed_cases"]) > 10:
        print(f"  ……另有 {len(r['failed_cases']) - 10} 条，详见 Allure 报告")

    blocked = False
    if r["pass_rate"] < args.min_pass_rate:
        print(f"\n[门禁不通过] 通过率 {r['pass_rate']:.2f}% 低于阈值 {args.min_pass_rate}%")
        blocked = True
    if len(p0_failed) > args.max_p0_failures:
        print(f"[门禁不通过] P0 用例失败 {len(p0_failed)} 条，核心链路不容妥协")
        blocked = True

    if blocked:
        sys.exit(1)
    print("\n[门禁通过] 允许合入")
    sys.exit(0)


if __name__ == "__main__":
    main()
