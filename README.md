# test-dev

测试开发（SDET）技能知识库，Markdown 笔记形态，用 [Obsidian](https://obsidian.md) 阅读与编辑。

## 结构

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
12-面试题/             按模块归类的高频题与答题思路
13-项目实战/           端到端练手项目
14-WebSocket测试/      RFC 6455 协议、自动化测试、心跳重连、CSWSH防护、性能压测
15-AI与大模型测试/      大模型评测体系、RAGAS、Agent 工具调用轨迹、安全护栏
_附件/                图片等附件
_模板/                笔记模板
首页.md               知识库总入口（地图）
```

## 在线网站与本地预览

除了在 Obsidian 中打开外，本知识库已配置 **Quartz 双向链接静态网站生成流水线**：

1. **在线浏览（GitHub Pages）**：
   - 推送代码后，GitHub Actions 会自动编译部署至 GitHub Pages；
   - 包含完整的 `[[双向链接]]` 智能跳转、全局交互式知识图谱（Graph View）、暗黑主题与全文搜索。
2. **本地一键预览**：
   ```bash
   python scripts/preview_site.py
   ```
   即可在本地 `http://localhost:8080` 启动高保真 Web 预览。

## 用法

用 [Obsidian](https://obsidian.md) 打开本目录作为库（Vault），从 [首页.md](首页.md) 开始浏览。

每个模块目录下有一篇同名 MOC 笔记作为该模块索引，例如 [01-Python基础/01-Python基础.md](01-Python基础/01-Python基础.md)。

笔记规范见 [CLAUDE.md](CLAUDE.md)。
