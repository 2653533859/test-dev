#!/usr/bin/env python3
"""
scripts/preview_site.py
SDET 知识库本地静态网站一键预览工具。
使用 Quartz 引擎渲染静态网站（支持双向链接、全文搜索与交互式图谱）。
"""

import os
import shutil
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

# 保证在 Windows 环境或默认非 UTF-8 控制台下正常输出
if sys.stdout:
    reconfig_stdout = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfig_stdout):
        with suppress(Exception):
            reconfig_stdout(encoding="utf-8", errors="replace")


def resolve_binary(name: str) -> str:
    """解析系统可执行文件路径，在 Windows 下优先匹配 .cmd 或 .exe"""
    binary_path = shutil.which(name)
    if not binary_path:
        raise FileNotFoundError(f"未在系统 PATH 中找到可执行工具: {name}")
    return binary_path


def run_quartz_preview(vault_root: Path) -> None:
    """使用 Quartz 引擎进行高保真静态站构建与本地预览"""
    print("🚀 准备使用 Quartz 引擎渲染静态网站...")
    quartz_dir = vault_root / ".quartz-cache"

    git_bin = resolve_binary("git")
    npm_bin = resolve_binary("npm")
    npx_bin = resolve_binary("npx")

    if not quartz_dir.exists():
        print("📦 正在拉取 Quartz 模板引擎（仅首次需要）...")
        subprocess.run(
            [git_bin, "clone", "--depth", "1", "https://github.com/jackyzha0/quartz.git", str(quartz_dir)],
            check=True,
            shell=False,
        )
        print("📥 正在安装依赖...")
        subprocess.run(
            [npm_bin, "ci"],
            cwd=str(quartz_dir),
            check=True,
            shell=False,
        )

    # 同步内容
    content_dir = quartz_dir / "content"
    if content_dir.exists():
        try:
            shutil.rmtree(content_dir)
        except OSError as err:
            print(f"⚠️ 清理旧缓存目录提示: {err}")

    content_dir.mkdir(parents=True, exist_ok=True)

    print("🔄 正在同步知识库笔记到构建目录...")
    ignore_dirs = {
        ".git",
        ".github",
        ".obsidian",
        ".claude",
        ".claudian",
        ".workbuddy",
        "scripts",
        ".quartz-cache",
        ".ruff_cache",
    }
    for item in vault_root.iterdir():
        if item.name in ignore_dirs or item.name.startswith("."):
            continue
        dest = content_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        elif item.is_file() and item.suffix == ".md":
            shutil.copy2(item, dest)

    # 映射首页.md 到 index.md
    index_source = content_dir / "首页.md"
    if index_source.exists():
        shutil.copy2(index_source, content_dir / "index.md")

    print("\n==================================================")
    print("🎉 静态站点服务启动中！")
    print("   本地地址: http://localhost:8080")
    print("   按 Ctrl + C 可退出预览服务")
    print("==================================================\n")

    subprocess.run(
        [npx_bin, "quartz", "build", "--serve"],
        cwd=str(quartz_dir),
        check=False,
        shell=False,
    )


def main() -> None:
    vault_root = Path(__file__).resolve().parent.parent
    os.chdir(vault_root)

    has_node = shutil.which("node") is not None and shutil.which("npm") is not None

    if has_node:
        try:
            run_quartz_preview(vault_root)
        except KeyboardInterrupt:
            print("\n👋 静态网站预览已停止。")
        except Exception as err:
            print(f"⚠️ 静态站构建提示: {err}")
            print("💡 您也可直接将代码推送到 GitHub，由 GitHub Actions 自动在线部署到 GitHub Pages。")
    else:
        print("⚠️ 未检测到 Node.js 环境，建议安装 Node.js 后获得完整的双链静态站体验。")


if __name__ == "__main__":
    main()
