---
created: 2026-07-31
tags: [Python基础/MOC, MOC]
---

# 01-Python基础

自动化脚本与测试框架的语言底座。目标不是把 Python 学成后端开发，而是能写出可读、可维护、能被别人接手的测试代码。

## 学习目标

- 熟练使用列表 / 字典 / 集合完成数据处理，理解可变与不可变对象带来的坑
- 能用类和装饰器封装测试工具，看懂主流框架源码
- 会读 traceback、会用 pdb 和日志定位问题
- 能写并发脚本压接口，知道 GIL 的边界在哪

## 计划覆盖的知识点

- 数据类型：str / list / dict / set / tuple，深浅拷贝，可变对象作默认参数的陷阱
- 函数：位置与关键字参数、`*args` / `**kwargs`、闭包、作用域
- 面向对象：类与实例属性、继承与 MRO、`__init__` 与魔术方法、`@property`、`classmethod` / `staticmethod`
- 装饰器与迭代器：装饰器原理与带参装饰器、生成器与 `yield`、上下文管理器
- 异常处理：异常层级、自定义异常、`try/finally` 与资源释放
- 标准库：`os` / `pathlib` / `json` / `re` / `datetime` / `logging` / `subprocess`
- 并发：多线程与 GIL、多进程、`concurrent.futures`、asyncio 与 async/await
- 工程化：虚拟环境、依赖管理、包与模块导入机制、类型注解、black / ruff

## 笔记索引

（新增笔记后在此挂双链）

## 常考点

- 深拷贝与浅拷贝的区别，`copy.deepcopy` 什么时候会出问题
- 装饰器的执行时机，`functools.wraps` 解决什么问题
- 可变对象作为函数默认参数为什么危险
- GIL 是什么，为什么多线程压 CPU 密集任务没用、压 IO 密集任务有用
- 迭代器与生成器的区别，生成器省内存的原理

## 参考

- [Python 官方文档](https://docs.python.org/zh-cn/3/)
