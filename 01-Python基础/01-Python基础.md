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

## 学习路径

建议按下面顺序学，每组点开对应笔记。先打通对象模型与函数，再上 OOP 与函数式，最后用标准库和并发把测试脚本写得又稳又快。

## 笔记索引

### 一、数据类型与对象模型
- [[Python 可变对象与不可变对象]] —— 可变/不可变、引用语义、函数传参
- [[Python 浅拷贝与深拷贝]] —— 赋值/浅拷贝/深拷贝与嵌套结构
- [[函数默认参数的可变对象陷阱]] —— 默认参数在定义时求值，可变默认值串味

### 二、函数
- [[Python 函数参数与调用]] —— 位置/默认/`*args`/`**kwargs`/关键字-only
- [[Python 闭包与作用域 LEGB]] —— LEGB 查找、闭包、循环+lambda 坑

### 三、面向对象
- [[Python 类与对象：属性、继承、MRO 与 property]] —— 类/实例属性、多继承 MRO、property
- [[Python 魔术方法]] —— `__repr__`/`__str__`/`__eq__`/`__len__` 等

### 四、函数式与资源管理
- [[Python 装饰器]] —— 装饰器原理、`functools.wraps`、带参装饰器
- [[Python 生成器与迭代器]] —— `yield`、惰性求值、省内存
- [[Python 上下文管理器]] —— `with`、资源释放、`contextmanager`
- [[Python functools：lru_cache、partial 与 reduce]] —— 缓存、固化参数、累积归约

### 五、异常处理
- [[Python 异常处理]] —— 异常层级、自定义异常、`try/except/else/finally`、`raise ... from`

### 六、标准库
- [[Python pathlib 路径处理]] —— 跨平台路径、读写、glob 遍历
- [[Python json 序列化]] —— 序列化边界、`ensure_ascii`、自定义类型
- [[Python logging 日志]] —— 级别/Handler/Formatter、basicConfig 坑
- [[Python subprocess 调用外部命令]] —— 调外部命令、安全与阻塞
- [[Python 标准库：re 与 datetime]] —— 正则提取、日期运算与时区
- [[Python os 与 shutil 文件操作]] —— 目录遍历、环境变量、复制删除打包
- [[Python 正则表达式深入：分组、断言与贪婪]] —— 分组、非贪婪、前后向断言
- [[Python random 与 time 模块]] —— 造随机数据、sleep 与计时
- [[Python pickle 序列化]] —— 任意对象序列化与安全红线

### 七、并发
- [[Python 并发编程]] —— GIL、多线程、多进程、asyncio 选型
- [[Python asyncio 实战]] —— 事件循环、gather、限流、避坑

### 八、工程化
- [[Python 工程化：虚拟环境、导入机制与类型注解]] —— venv、导入路径、typing、black/ruff
- [[Python pydantic 数据校验]] —— 运行时数据建模与接口响应校验（第三方库）

### 九、进阶数据结构
- [[Python collections 模块]] —— defaultdict / Counter / deque / namedtuple
- [[Python dataclasses]] —— 数据类建模、`field` 与冻结
- [[Python itertools 模块]] —— 组合排列、链式、分组

### 十、类型系统进阶
- [[Python typing 进阶：泛型、Protocol 与 TypedDict]] —— 泛型、结构化子类型、字典类型

### 十一、调试与定位
- [[Python pdb 调试与 traceback 定位]] —— traceback 阅读、断点调试、CI 定位

### 十二、文本处理与表达式
- [[Python 推导式与表达式]] —— 列表/字典/集合推导式、生成器表达式、三元
- [[Python 字符串格式化与 f-string]] —— %/format/f-string、精度、自调试
- [[Python 编码与 bytes、str]] —— encode/decode、UTF-8/GBK、中文乱码
- [[Python 字符串方法与切片]] —— 索引切片、split/join/strip、查找替换、判断

### 十三、面向对象进阶
- [[Python 描述符 descriptor]] —— 描述符协议、property 底层
- [[Python 枚举 enum]] —— Env/Status 等具名常量、反查与序列化

### 十四、语法与运算符
- [[Python 基础语法]] —— 标识符、缩进、注释、代码块、多行
- [[Python 运算符]] —— 算术/比较/逻辑/成员/身份、优先级、is vs ==

### 十五、基础数据类型
- [[Python 数字与 math 模块]] —— int/float 精度、进制、round、Decimal

### 十六、容器操作
- [[Python 列表方法与操作]] —— 增删改查、排序、拷贝、遍历
- [[Python 字典方法与操作]] —— get/setdefault/合并/遍历、键可哈希
- [[Python 元组与集合]] —— 不可变解包、去重、交并差、frozenset

### 十七、流程控制
- [[Python 条件控制与断言]] —— if/elif、assert 红线、match-case
- [[Python 循环语句]] —— for/while、range、break/else、遍历删元素

### 十八、内置函数与 IO
- [[Python 匿名函数 lambda 与内置函数]] —— lambda、map/filter/sorted/zip/any-all
- [[Python 输入、输出与文件读写]] —— input/print/open、编码、with
- [[Python 模块与包的使用]] —— import、__name__ 守卫、循环导入

## 常考点

- 深拷贝与浅拷贝的区别，`copy.deepcopy` 什么时候会出问题
- 装饰器的执行时机，`functools.wraps` 解决什么问题
- 可变对象作为函数默认参数为什么危险
- GIL 是什么，为什么多线程压 CPU 密集任务没用、压 IO 密集任务有用
- 迭代器与生成器的区别，生成器省内存的原理

## 参考

- [Python 官方文档](https://docs.python.org/zh-cn/3/)
