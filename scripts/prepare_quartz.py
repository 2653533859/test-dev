#!/usr/bin/env python3
"""
scripts/prepare_quartz.py
配置并准备 Quartz 构建环境：
1. 映射根目录 首页.md 到 index.md
2. 递归为各层级（一级/二级/三级）模块与工程目录挂载同名 MOC 为 index.md
3. 配置 Quartz 基础路径 baseUrl、站点标题 pageTitle 与中文语言 locale
4. 部署 404.html 与 .nojekyll，保障多级子路径访问平滑
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
    """挂载根目录与所有层级目录的 index.md 索引页"""
    # 1. 映射根目录 首页.md
    home_page = content_root / "首页.md"
    target_index = content_root / "index.md"
    if home_page.exists() and not target_index.exists():
        shutil.copy2(home_page, target_index)
        print("✓ 已映射首页: content/index.md <- 首页.md")

    # 2. 递归为所有层级子目录挂载 index.md
    for item in sorted(content_root.rglob("*")):
        if item.is_dir() and not item.name.startswith("."):
            moc_file = item / f"{item.name}.md"
            sub_index = item / "index.md"
            if moc_file.exists() and not sub_index.exists():
                shutil.copy2(moc_file, sub_index)
                rel_path = item.relative_to(content_root).as_posix()
                print(f"✓ 已挂载多级目录索引: {rel_path}/index.md")


def sanitize_cross_links(content_root: Path) -> None:
    """自动将所有 Markdown 中的 [[A/A]] 纠正为标准的 [[A]]"""
    def repl(m: re.Match) -> str:
        link = m.group(1).strip()
        if "/" in link and not link.startswith("assets/"):
            parts = link.split("/")
            if len(parts) == 2 and parts[0] == parts[1]:
                return f"[[{parts[0]}]]"
            if len(parts) == 3 and parts[0] == "13-项目实战" and parts[1] == parts[2]:
                return f"[[{parts[1]}]]"
        return m.group(0)

    for md in content_root.rglob("*.md"):
        txt = md.read_text(encoding="utf-8")
        fixed = re.sub(r"\[\[([^\]|#]+)\]\]", repl, txt)
        if fixed != txt:
            md.write_text(fixed, encoding="utf-8")


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


def setup_public_fallbacks(public_dir: Path) -> None:
    """部署 .nojekyll 与 404 智能重定向"""
    (public_dir / ".nojekyll").touch()

    # 404 兜底：处理目录访问末尾缺少斜杠时，自动补全斜杠并跳转
    html_404 = """<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <title>页面跳转中...</title>
  <script>
    var path = window.location.pathname;
    if (!path.endsWith('/') && !path.endsWith('.html')) {
      window.location.replace(path + '/' + window.location.search + window.location.hash);
    } else {
      window.location.replace('/test-dev/');
    }
  </script>
</head>
<body>
  <p>正在定向到正确页面，若未自动跳转请点击 <a href="/test-dev/">首页</a></p>
</body>
</html>
"""
    (public_dir / "404.html").write_text(html_404, encoding="utf-8")
    print("✓ 已部署 .nojekyll 与 404.html 智能重定向守卫")


def main() -> None:
    workspace_root = Path(__file__).resolve().parent.parent
    engine_dir = workspace_root / "quartz-engine"
    content_root = engine_dir / "content"
    public_dir = workspace_root / "public"

    if content_root.exists():
        setup_indexes(content_root)
        sanitize_cross_links(content_root)

    if engine_dir.exists():
        configure_quartz(engine_dir)

    if public_dir.exists():
        setup_public_fallbacks(public_dir)


if __name__ == "__main__":
    main()
