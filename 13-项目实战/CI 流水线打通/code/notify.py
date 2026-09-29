"""企微机器人失败通知：可定位、可点击、可追责。

三条经验：
1. 成功不通知（主干除外），否则机器人两周内必被折叠。
2. 必须带失败用例名和错误摘要，「构建失败」四个字没人会点进去看。
3. 通知本身失败不能影响构建结论，调用方要包 try/except。
"""

import argparse
import os

import requests

from gate import parse_junit

TEMPLATE = """\
**{icon} {status}** · `{job}` #{build}
> 分支：{branch}　触发：{trigger}
> 用例：{executed} 条，通过率 **{pass_rate:.1f}%**

{failed_block}[查看 Allure 报告]({report_url})　[构建日志]({build_url})
"""


def escape(text: str) -> str:
    """转义 Markdown 特殊字符，避免错误信息里的反引号炸掉整张卡片。"""
    return text.replace("`", "'").replace("*", "·").replace("\n", " ")


def build_failed_block(failed_cases: list[dict]) -> str:
    if not failed_cases:
        return ""
    lines = ["**失败用例（Top 3）**"]
    for c in failed_cases[:3]:
        lines.append(f"- `{escape(c['name'])}`")
        lines.append(f"  {escape(c['message'])[:80]}")
    if len(failed_cases) > 3:
        lines.append(f"- ……另有 {len(failed_cases) - 3} 条，详见报告")
    return "\n".join(lines) + "\n\n"


def notify(status: str, result: dict) -> None:
    branch = os.getenv("BRANCH_NAME", "unknown")

    # 成功静默，避免刷屏导致机器人被折叠；主干构建例外，作为每日健康信号
    if status == "SUCCESS" and branch != "main":
        print("构建成功且非主干，跳过通知")
        return

    build_url = os.getenv("BUILD_URL", "")
    content = TEMPLATE.format(
        icon="[通过]" if status == "SUCCESS" else "[失败]",
        status="构建通过" if status == "SUCCESS" else "构建失败",
        job=os.getenv("JOB_NAME", "-"),
        build=os.getenv("BUILD_NUMBER", "-"),
        branch=branch,
        trigger=os.getenv("COMMIT_AUTHOR", "webhook"),
        executed=result["executed"],
        pass_rate=result["pass_rate"],
        failed_block=build_failed_block(result["failed_cases"]),
        report_url=f"{build_url}allure/",
        build_url=f"{build_url}console",
    )

    # @ 到具体的人。用 @all 等于没 @，需要维护 commit author 到企微账号的映射表。
    mentioned = [os.getenv("COMMIT_AUTHOR_WECOM")] if os.getenv("COMMIT_AUTHOR_WECOM") else []

    webhook = os.environ.get("WECOM_WEBHOOK")
    if not webhook:
        # webhook 走凭据注入；本地或未配置时 graceful 退出，不抛 KeyError
        print("未设置 WECOM_WEBHOOK 环境变量，跳过通知")
        return

    resp = requests.post(
        webhook,
        json={
            "msgtype": "markdown",
            "markdown": {"content": content},
            "mentioned_list": mentioned,
        },
        timeout=10,
    )
    print(f"通知发送：{resp.status_code} {resp.text[:200]}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--status", required=True, help="SUCCESS / FAILURE / UNSTABLE")
    p.add_argument("--junit", required=True)
    args = p.parse_args()

    notify(args.status, parse_junit(args.junit))


if __name__ == "__main__":
    main()
