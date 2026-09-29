# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

本仓库是**测试开发（SDET）技能知识库**，内容形态是 Markdown 笔记，不是可运行的代码工程。用中文回复。

## 仓库性质与常用命令

- **没有构建 / 测试 / lint 流程**，不存在 `package.json`、`requirements.txt` 等工程配置。不要尝试运行 `npm run type-check` 之类的验证命令，也不要为了「让项目能跑」而添加工程脚手架。
- 唯一的「验证」是内容自查：文件放在正确模块、frontmatter 完整、双链能解析、对应 MOC 已挂上索引。可运行 `python scripts/lint_vault.py` 进行零依赖一键自检。
- 笔记里的可运行示例（Python 脚本、Dockerfile、Jenkinsfile、JMeter jmx 等）以代码块形式内嵌在笔记中；如需成套的示例工程，放到 `13-项目实战/` 对应子目录下。
- Git：本仓库有远端 `origin`（GitHub `2653533859/test-dev`），提交**手动管理**。按全局规则，不要自动 `commit` / `push`。

## Obsidian 上下文

本仓库是**独立的知识库**，自成一体，与同一磁盘路径下的其他笔记库无关。用 Obsidian 打开本目录作为库（Vault）即可。

- 双链 `[[笔记名]]` 在本库内解析。**新建笔记取名要够具体**（用 `Selenium 显式等待` 而不是 `等待`），避免同名歧义。
- `_附件/` 只放图片等附件，**不放笔记**；`_模板/` 只放模板。

## 目录结构

编号前缀按学习路径排列：基础能力 → 测试技术 → 工程效能 → 沉淀。

```text
01-Python基础/        语法、数据结构、OOP、并发、常用库、工程化
02-Linux基础/         命令、文本处理、Shell、进程与网络排查、日志分析
03-计算机网络/         TCP/IP、HTTP(S)、DNS、抓包分析
04-数据库/            SQL、索引与执行计划、事务、Redis、测试数据构造
05-自动化测试框架/      pytest、unittest、PO 模式、数据驱动、测试报告、框架设计
06-接口自动化测试/      HTTP 接口、requests、鉴权、断言与校验、Mock、契约测试
07-Web自动化测试/       Selenium、Playwright、元素定位、等待策略、稳定性治理
08-App自动化测试/       Appium、Android/iOS 环境、控件定位、真机与云测、专项测试
09-性能测试-JMeter/     压测模型、脚本录制与参数化、监控指标、结果分析与调优
10-安全测试/           OWASP Top 10、越权与注入、抓包改包、扫描工具
11-持续集成/           Git 工作流、Jenkins、GitHub Actions、Docker、质量门禁
12-面试题/             按上述模块归类的高频题与答题思路
13-项目实战/           端到端练手项目（测试平台、框架落地、完整用例集）
14-WebSocket测试/      RFC 6455 协议、自动化测试、心跳重连、CSWSH防护、性能压测
_附件/                图片等附件
_模板/                笔记模板
首页.md               知识库总入口（MOC）
```

每个模块目录下有一篇**同名 MOC 笔记**（如 `01-Python基础/01-Python基础.md`），作为该模块的索引与学习路径。

## 笔记规范

- **文件名用中文**（技术专有名词保留英文，如 `pytest fixture 详解`）；日期统一 `YYYY-MM-DD`。
- **Frontmatter** 必须有 `created` 与 `tags`；模块 MOC 额外打 `MOC` 标签。tags 采用层级式，第一段固定为模块名，例如 `tags: [Web自动化测试/Playwright]`。编辑已有笔记时保留其原 frontmatter。
- **新建笔记套用 `_模板/知识点笔记模板.md`**，保留「概念 → 用法 → 踩坑 → 面试怎么答」这四段骨架；这个知识库的定位是面向面试与实战，纯概念搬运没有价值。
- **新增笔记后，必须在所属模块 MOC 的「笔记索引」里挂一条双链**；跨模块的重要笔记再在 `首页.md` 挂一笔。
- 代码块**必须标注语言**（`python` / `bash` / `sql` / `groovy` / `yaml`；纯目录树等无语言内容用 `text`），便于高亮与后续提取。
- 一篇笔记只讲一个知识点。内容超长时拆分成多篇并在 MOC 下聚成一组，不要写成万字长文。
- 仓库启用了 markdownlint，编辑后留意 IDE 给出的 MD0xx 告警并顺手修掉。

## 边界

本仓库自成一体，**所有内容都写在本目录内**。不要引用、读取或修改本目录之外的其他笔记库（如同级的 `MyKnowledgeBase/`、`Obsidian_md/`），它们与本项目无关。
