#!/usr/bin/env python3
"""
scripts/prepare_quartz.py
配置并准备 Quartz 构建环境：
1. 映射根目录 首页.md 到 index.md
2. 为各模块目录挂载同名 MOC 为该目录的 index.md
3. 配置 Quartz 基础路径 baseUrl、站点标题 pageTitle 与中文语言 locale
4. 生成 .nojekyll 防止静态资源被 GitHub Pages 过滤
"""

import re
import shutil
import sys
from contextlib import suppress
from pathlib import Path

# 保证在 Windows 环境或默认非 UTF-8 控制台下正常输出
if sys.stdout:
    reconfig_stdout = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfig_stdout):
        with suppress(Exception):
            reconfig_stdout(encoding="utf-8", errors="replace")


def setup_indexes(content_root: Path) -> None:
    """挂载根目录与模块目录的 index.md 索引页"""
    # 1. 映射首页.md
    home_page = content_root / "首页.md"
    target_index = content_root / "index.md"
    if home_page.exists() and not target_index.exists():
        shutil.copy2(home_page, target_index)
        print("✓ 已映射首页: content/index.md <- 首页.md")

    # 2. 为每个包含同名 MOC 的模块目录生成 index.md
    for item in content_root.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            moc_file = item / f"{item.name}.md"
            sub_index = item / "index.md"
            if moc_file.exists() and not sub_index.exists():
                shutil.copy2(moc_file, sub_index)
                print(f"✓ 已挂载模块目录索引: {item.name}/index.md")


def configure_quartz(engine_dir: Path) -> None:
    """修改 Quartz 配置文件以适配 GitHub Pages 子路径"""
    site_title = 'pageTitle: "SDET 测试开发技能知识库"'
    site_base = "baseUrl: 2653533859.github.io/test-dev"
    site_locale = "locale: zh-CN"

    # 处理 YAML 配置文件
    for cfg in engine_dir.glob("quartz.config*.yaml"):
        txt = cfg.read_text(encoding="utf-8")
        txt = re.sub(r"baseUrl:\s*.*", site_base, txt)
        txt = re.sub(r"pageTitle:\s*.*", site_title, txt)
        txt = re.sub(r"locale:\s*.*", site_locale, txt)
        cfg.write_text(txt, encoding="utf-8")
        print(f"✓ 已更新 YAML 配置: {cfg.name}")

    # 处理 TS 配置文件（兼容 Quartz 4）
    ts_cfg = engine_dir / "quartz.config.ts"
    if ts_cfg.exists():
        txt = ts_cfg.read_text(encoding="utf-8")
        ts_base = 'baseUrl: "2653533859.github.io/test-dev"'
        ts_locale = 'locale: "zh-CN"'
        txt = re.sub(r'baseUrl:\s*".*?"', ts_base, txt)
        txt = re.sub(r'pageTitle:\s*".*?"', site_title, txt)
        txt = re.sub(r'locale:\s*".*?"', ts_locale, txt)
        ts_cfg.write_text(txt, encoding="utf-8")
        print("✓ 已更新 TS 配置: quartz.config.ts")


def main() -> None:
    workspace_root = Path(__file__).resolve().parent.parent
    engine_dir = workspace_root / "quartz-engine"
    content_root = engine_dir / "content"

    if content_root.exists():
        setup_indexes(content_root)

    if engine_dir.exists():
        configure_quartz(engine_dir)


if __name__ == "__main__":
    main()
