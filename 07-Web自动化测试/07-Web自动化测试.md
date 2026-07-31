---
created: 2026-07-31
tags: [Web自动化测试/MOC, MOC]
---

# 07-Web自动化测试

技术门槛不高，难点全在稳定性。写得出来是入门，长期跑不飘才是能力。

## 学习目标

- 熟练使用 Selenium 与 Playwright，能说清两者的差异与选型理由
- 定位元素稳、等待策略对，不靠 `sleep` 硬撑
- 用 Page Object 组织代码，页面改动时只改一处
- 有一套治理用例不稳定（flaky）的方法论

## 计划覆盖的知识点

- 环境：WebDriver 与浏览器版本匹配、Selenium Manager、Playwright 安装与浏览器下载
- 元素定位：CSS 选择器、XPath（轴与函数）、Playwright 的语义定位器（`get_by_role` / `get_by_text`）
- 定位稳定性：优先级策略、动态 ID、`data-testid` 约定、iframe 与 Shadow DOM
- 等待策略：隐式等待、显式等待与 `expected_conditions`、Playwright 自动等待、强制等待为什么该禁用
- 常见交互：输入与点击、下拉框、alert 弹窗、多窗口与标签页切换、文件上传下载、拖拽、滚动、JS 执行
- Page Object 模式：页面类拆分、元素与操作分离、链式调用、business 层封装
- 稳定性治理：失败重跑、失败截图与录屏、日志与 trace、脏数据清理
- 进阶：Selenium Grid 与 Playwright 并行、无头模式、网络拦截与 Mock、CDP、视觉对比测试

## 笔记索引

（新增笔记后在此挂双链）

## 常考点

- 显式等待与隐式等待的区别，混用会有什么问题
- 为什么不能用 `sleep`，遇到元素时有时无怎么解决
- `NoSuchElementException` / `StaleElementReferenceException` / `ElementNotInteractableException` 分别什么原因
- Page Object 解决什么问题，你怎么分层
- 用例经常随机失败，你怎么排查和治理
- Selenium 与 Playwright 怎么选，Playwright 的优势在哪

## 参考

- [Playwright Python 文档](https://playwright.dev/python/)
- [Selenium 文档](https://www.selenium.dev/documentation/)
- 相关笔记：[[05-自动化测试框架]]
