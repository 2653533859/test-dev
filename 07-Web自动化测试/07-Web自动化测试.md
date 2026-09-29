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

### 一、环境

- [[Selenium 环境搭建与 Selenium Manager]] —— WebDriver 与浏览器版本匹配、Selenium Manager 自动解析、Options 与 fixture 封装
- [[Playwright 安装与浏览器管理]] —— 无驱动架构、Browser/Context/Page 三层模型、storage_state 登录态复用
- [[Selenium 与 Playwright 选型对比]] —— 架构差异驱动的选型理由与迁移策略

### 二、元素定位

- [[CSS 选择器定位]] —— 选择器右到左匹配、属性选择器、:nth-child 与 :nth-of-type 的区别
- [[XPath 定位：轴与函数]] —— 轴表、text() 与 . 的区别、三步锁定表格行、局部查找陷阱
- [[Playwright 语义定位器]] —— get_by_role/text/label 等语义定位、Locator 惰性、strict mode

### 三、定位稳定性

- [[元素定位稳定性策略与 data-testid]] —— 定位优先级金字塔、data-testid 约定、动态 DOM 的兜底方案
- [[iframe 与 Shadow DOM 切换]] —— Selenium 有状态切换与上下文管理器、Playwright frame_locator 自动穿透

### 四、等待策略

- [[Selenium 显式等待]] —— WebDriverWait 轮询机制、expected_conditions 选择表、自定义条件与 BasePage 封装
- [[Selenium 隐式等待与显式等待混用冲突]] —— 超时相乘陷阱、为何应在 fixture 中禁用隐式等待
- [[Playwright 自动等待机制]] —— actionability 检查链、expect 断言与 force=True 的风险

### 五、常见交互

- [[Selenium alert 弹窗与多窗口切换]] —— switch_to.alert、窗口句柄差集、Playwright 事件驱动切换
- [[Selenium 表单交互：输入、点击与下拉框]] —— 真实用户交互原则、clear 陷阱、原生 Select 与自定义下拉
- [[Selenium 文件上传与下载]] —— send_keys 上传隐藏 input、下载目录与完成等待、expect_download
- [[Selenium JavaScript 执行、滚动与拖拽]] —— execute_script 使用边界、ActionChains、HTML5 拖拽与滑块验证码

### 六、Page Object 模式

- [[Page Object 模式与分层设计]] —— 四层 BasePage/Page/Component/Flow、链式返回、Playwright PO 实践

### 七、稳定性治理

- [[Selenium 常见异常排查]] —— 四类异常辨析、五步排查法、pytest_runtest_makereport 失败现场钩子
- [[UI 用例失败重跑与截图 trace]] —— 重跑策略、截图/录屏/trace 收集、Allure 附件挂载
- [[UI 测试脏数据清理与数据隔离]] —— 隔离层级、偏前/偏后清理、用 API 而非 UI 清理

### 八、进阶

- [[Selenium Grid 与并行执行]] —— Hub/Node 拓扑、pytest-xdist 单机并行、无头模式与 CI 注意事项
- [[Playwright 网络拦截与 Mock]] —— page.route 协议层拦截、fulfill/continue/abort、HAR 录制回放
- [[视觉对比测试]] —— 基线/像素 diff/阈值、动态区遮罩、Percy/Applitools 云方案

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
