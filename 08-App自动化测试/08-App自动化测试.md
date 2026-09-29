---
created: 2026-07-31
tags: [App自动化测试/MOC, MOC]
---

# 08-App自动化测试

比 Web 自动化更重环境。真正的难点是设备与环境治理，以及移动端特有的专项测试。

## 学习目标

- 独立搭起 Android 自动化环境并跑通第一个用例
- 熟练使用 adb 完成安装、日志抓取、性能数据采集
- 会定位原生、H5、混合应用三类控件
- 能设计移动端专项测试方案（弱网、兼容、耗电、内存、启动速度）

## 计划覆盖的知识点

- 环境：JDK、Android SDK、adb、Appium Server 与 Appium Inspector、真机与模拟器、iOS 需要的 Xcode 与 WDA
- adb 常用命令：`devices` / `install` / `shell` / `logcat` / `pull` / `push`、抓崩溃日志、`am` 与 `pm`
- Appium 基础：Desired Capabilities 各字段含义、client 库、session 生命周期
- 控件定位：`resource-id` / `accessibility id` / XPath、UiAutomator2 定位器、坐标定位的代价
- 混合应用：Native 与 WebView 上下文切换、H5 页面调试（chrome://inspect）
- 常见操作：滑动与手势、长按、键盘输入、系统弹窗与权限授权、应用启停与重置
- 稳定性：等待策略、弹窗拦截、设备状态恢复、失败截图
- 专项测试：弱网测试（Charles / 网络模拟）、兼容性测试与云真机平台、性能采集（FPS、内存、CPU、流量、启动耗时）、耗电、安装卸载与升级
- 其他方案：UIAutomator2、Airtest / Poco 的适用场景

## 笔记索引

### 1、环境与架构

- [[Appium 架构原理与工作流程]] —— 五层架构、W3C WebDriver 协议、Android/iOS 两条链路与常见环境坑
- [[Appium 2.0 架构革新与 Plugin 插件生态]] —— 微内核解耦、W3C 协议强制规范与 images 等官方插件实战
- [[Android 自动化测试环境搭建]] —— JDK/SDK/Appium/Inspector 五组件、真机模拟器选型、跑通首用例
- [[Appium Inspector 元素检查与定位调试]] —— 控件树属性、Search for element 工作流、uiautomator dump 替代
- [[iOS 自动化环境：Xcode 与 WebDriverAgent]] —— WDA 编译签名信任流程、iOS Predicate/Class Chain 定位

### 2、adb 与 Appium 基础

- [[adb 常用命令详解]] —— adb 三段式结构、设备/pm/am/文件/UI/性能命令、Python 工具类封装
- [[adb logcat 日志抓取与崩溃定位]] —— 五大 buffer、Java/Native/ANR 三类崩溃、崩溃检测 fixture
- [[Appium Desired Capabilities 详解]] —— W3C + appium: 前缀、四类字段、重置策略与 YAML 分层配置
- [[Appium session 生命周期与 client 库]] —— session 创建七步、pytest fixture 管理、client 库继承 Selenium

### 3、定位与混合应用

- [[Appium 控件定位策略]] —— 七种定位策略优先级、XPath 慢的机制、UiScrollable 与 PO 封装
- [[Native 与 WebView 上下文切换]] —— context 含义、切换助手与 chromedriver 版本匹配
- [[WebView H5 调试：chrome-inspect 实战]] —— CDP 原理、chrome://inspect 流程与离线调试方案

### 4、常见操作与稳定性

- [[Appium 手势操作：滑动、长按与多点触控]] —— W3C Actions、TouchAction 废弃、双指捏合
- [[Appium 键盘输入与中文输入问题]] —— unicodeKeyboard 预授权、自绘框清值与软键盘遮挡
- [[Appium 系统权限弹窗处理]] —— 权限框预授权与运行时兜底、厂商二次弹窗
- [[Android Toast 捕获方案]] —— UiAutomator2 抓 Toast、XPath 为何抓不到、iOS 差异
- [[Appium 应用启停、重置与设备状态恢复]] —— launch/activate/terminate/clearApp、noReset 与 fullReset
- [[App UI 自动化稳定性治理]] —— 等待策略、弹窗拦截、崩溃检测、失败取证与状态恢复闭环
- [[移动端自动化弹窗动态拦截与巡检机制]] —— 异常驱动黑名单自愈、UiWatcher 异步守护与多层浮层处理

### 5、专项测试与选型

- [[App 弱网测试：Charles 与网络损伤注入]] —— 代理 Throttle 与 toxiproxy/tc 损伤注入、参数化多档
- [[App 启动耗时测量]] —— 冷/温/热启动、am start -W 与 Displayed、采样取中位
- [[App 性能指标采集：FPS、内存、CPU、流量与耗电]] —— 五类指标采集入口与泄漏趋势判断
- [[App 兼容性测试与云真机平台]] —— 机型矩阵、云真机接入与重点兼容场景
- [[App 安装、卸载与升级测试]] —— 全新/覆盖升级/卸载残留、DB 迁移与登录态保留
- [[UiAutomator2、Airtest 与 Poco 选型对比]] —— 原生/图像/游戏引擎三方案适用场景

## 常考点

- Appium 的工作原理，从脚本到设备中间经过哪几层
- 原生控件和 WebView 控件怎么区分，上下文如何切换
- Toast 提示怎么捕获
- 元素定位不到的常见原因（未渲染完、在弹窗遮挡下、控件在另一个 context）
- App 启动速度、内存、卡顿分别怎么测，指标从哪来
- 兼容性测试怎么选机型

## 参考

- [Appium 文档](https://appium.io/docs/en/latest/)
- 相关笔记：[[05-自动化测试框架]]、[[09-性能测试-JMeter]]
