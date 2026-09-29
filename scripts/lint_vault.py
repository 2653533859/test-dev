#!/usr/bin/env python3
"""
scripts/lint_vault.py
测试开发技能知识库（SDET Vault）内容与结构一致性体检脚本。
零第三方依赖，纯标准库运行。
"""

import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from collections import defaultdict


def strip_code_blocks(text: str) -> str:
    """去除围栏代码块和行内反引号，避免代码中出现的正则或示例干扰语法检测"""
    text_no_fenced = re.sub(r"```[\s\S]*?```", "", text)
    text_no_inline = re.sub(r"`[^`\n]+`", "", text_no_fenced)
    return text_no_inline


def parse_frontmatter(content: str):
    """解析 Markdown 文件的 YAML frontmatter"""
    if not content.startswith("---"):
        return None, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None, content
    fm_text = parts[1]
    body = parts[2]
    meta = {}
    for line in fm_text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                v = [item.strip() for item in v[1:-1].split(",") if item.strip()]
            meta[k] = v
    return meta, body


def main():
    vault_root = Path(__file__).resolve().parent.parent
    os.chdir(vault_root)

    print(f"==================================================")
    print(f"  SDET 知识库健康体检: {vault_root.resolve()}")
    print(f"==================================================\n")

    all_md_files = []
    for p in vault_root.rglob("*.md"):
        parts = p.relative_to(vault_root).parts
        if any(part.startswith(".") for part in parts):
            continue
        all_md_files.append(p)

    # 建立笔记名索引 (不含 .md 后缀)
    note_name_to_path = {}
    for p in all_md_files:
        name = p.name[:-3]
        note_name_to_path[name] = p

    # 收集所有的图片/SVG资源文件
    all_asset_files = set()
    for p in vault_root.rglob("*"):
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(vault_root).parts):
            all_asset_files.add(p.name)

    errors = defaultdict(list)
    warnings = defaultdict(list)
    referenced_notes = set()
    total_links = 0
    total_code_blocks = 0
    bare_code_blocks = 0

    link_pattern = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
    code_fence_pattern = re.compile(r"^```(\S*)", re.MULTILINE)

    for p in all_md_files:
        rel_path = p.relative_to(vault_root).as_posix()
        try:
            content = p.read_text(encoding="utf-8")
        except Exception as e:
            errors["文件读取失败"].append(f"{rel_path}: {e}")
            continue

        # 豁免特殊说明文件（根目录配置与工程内 README）
        is_special_file = (
            rel_path in ["README.md", "CLAUDE.md", "首页.md", "00-测试开发学习指南与成长路径.md"]
            or rel_path.startswith("_模板/")
            or p.name == "README.md"
        )
        meta, body = parse_frontmatter(content)

        # 1. 检查 Frontmatter 规范
        if not is_special_file:
            if meta is None:
                errors["缺失 Frontmatter"].append(rel_path)
            else:
                if "created" not in meta:
                    errors["Frontmatter 缺失 created"].append(rel_path)
                elif not re.match(r"^\d{4}-\d{2}-\d{2}$", str(meta["created"])):
                    warnings["created 日期格式建议为 YYYY-MM-DD"].append(f"{rel_path} ({meta['created']})")

                if "tags" not in meta or not meta["tags"]:
                    errors["Frontmatter 缺失 tags"].append(rel_path)
                else:
                    if len(p.relative_to(vault_root).parts) == 2 and p.name == f"{p.parent.name}.md" and "MOC" not in meta["tags"]:
                        warnings["模块入口 MOC 建议包含 MOC 标签"].append(rel_path)

        # 2. 检查代码块语言标注
        for m in code_fence_pattern.finditer(content):
            lang = m.group(1).strip()
            total_code_blocks += 1
            if not lang:
                # 只有空语言才记录，如果是闭合的 ``` 则不计
                # 统计奇数位置打开的围栏
                bare_code_blocks += 1

        # 3. 检查双链引用及目标有效性
        content_no_code = strip_code_blocks(content)
        for m in link_pattern.finditer(content_no_code):
            target = m.group(1).strip()
            # 排除已知特殊排除项（正则 POSIX 类与占位符示例）
            if target in [":digit:", ":space:", ":alpha:", ":alnum:", "笔记名", ""]:
                continue
            
            total_links += 1
            # 处理形如 路径/笔记名 或 纯笔记名
            target_name = Path(target).name
            if target_name.endswith(".md"):
                target_name = target_name[:-3]

            if target_name.endswith((".svg", ".png", ".jpg", ".jpeg", ".gif")):
                # 检查嵌入资源是否存在
                if target_name not in all_asset_files:
                    errors["静态资源死链 (图片/SVG不存在)"].append(f"{rel_path} -> [[{target}]]")
            else:
                referenced_notes.add(target_name)
                if target_name not in note_name_to_path:
                    errors["双链死链 (目标笔记不存在)"].append(f"{rel_path} -> [[{target}]]")

        # 4. 检查正文骨架完整性 (仅抽检标准技术知识点笔记)
        if not is_special_file and not rel_path.startswith("12-面试题/") and not rel_path.startswith("13-项目实战/"):
            if p.name != f"{p.parent.name}.md":
                # 检查四段骨架
                for section in ["概念", "用法", "踩坑", "面试怎么答"]:
                    if f"## {section}" not in body:
                        warnings[f"知识点笔记骨架缺失 [## {section}]"].append(rel_path)

    # 5. 检查孤立笔记 (Orphaned Notes)
    for name, p in note_name_to_path.items():
        rel_path = p.relative_to(vault_root).as_posix()
        if (
            rel_path in ["首页.md", "README.md", "CLAUDE.md"]
            or rel_path.startswith("_模板/")
            or p.name == "README.md"
            or p.name == f"{p.parent.name}.md"  # MOC 自身由 首页.md 引用
        ):
            continue
        if name not in referenced_notes:
            warnings["孤立笔记 (未被任何其他笔记双链引用)"].append(rel_path)

    # 6. 校验全库 SVG 的 XML 语法有效性
    svg_count = 0
    for p in vault_root.rglob("*.svg"):
        if any(part.startswith(".") for part in p.relative_to(vault_root).parts):
            continue
        svg_count += 1
        try:
            ET.parse(p)
        except Exception as e:
            errors["SVG XML 解析异常"].append(f"{p.relative_to(vault_root).as_posix()}: {e}")

    # 输出统计报告
    print(f"📊 基础统计：")
    print(f"  - Markdown 文件总数 : {len(all_md_files)} 篇")
    print(f"  - 校验双链数量      : {total_links} 处")
    print(f"  - SVG 流程图总数    : {svg_count} 张\n")

    has_error = False
    if errors:
        has_error = True
        print("❌ 错误项（阻断级）：")
        for err_title, items in errors.items():
            print(f"  [{err_title}] ({len(items)} 处):")
            for item in items[:10]:
                print(f"    - {item}")
            if len(items) > 10:
                print(f"    ... 还有 {len(items) - 10} 处未列出")
        print()
    else:
        print("✅ 阻断级检查全部通过（0 错误项）！\n")

    if warnings:
        print("⚠️ 优化建议与提示项：")
        for warn_title, items in warnings.items():
            print(f"  [{warn_title}] ({len(items)} 处):")
            for item in items[:5]:
                print(f"    - {item}")
            if len(items) > 5:
                print(f"    ... 还有 {len(items) - 5} 处未列出")
        print()
    else:
        print("✨ 无任何警告或缺失项，符合极高质量标准！\n")

    sys.exit(1 if has_error else 0)


if __name__ == "__main__":
    main()
