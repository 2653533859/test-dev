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

（新增笔记后在此挂双链）

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
