---
created: 2026-07-31
tags: [Python基础/工程化]
---

# Python 模块与包的使用

![[assets/import-resolution.svg]]
*图示：`import` 时先查 `sys.modules` 缓存，再按 `sys.path` 查找、编译字节码、执行顶层代码、存入缓存——故模块只执行一次。*

> 导入报错 90% 是“路径没找着”或“循环导入”。理解 `import` 的底层流程（sys.modules → sys.path → 编译 .pyc）、`__name__` 的本质、相对导入为什么不能在主脚本跑，问题就清楚了。

## 概念

### 1. `import` 的底层流程

执行 `import mod` 时：
1. 查 `sys.modules`（已导入缓存）——有就直接返回，**不重复执行**
2. 否则按 `sys.path`（含当前目录、安装包、`PYTHONPATH`）依次找 `mod.py`/包
3. 找到后**执行模块顶层代码**（定义函数/类、顶层语句），把结果放进一个 module 对象，缓存到 `sys.modules`
4. 把名字 `mod` 绑定到当前命名空间

所以“导入”= “执行一次模块代码 + 建立引用”。顶层有副作用（print/连接）会每次第一次 import 时执行。

### 2. `from mod import name` 做了什么

先执行上面的导入，再把 `mod.name` **绑定到当前命名空间的 `name`**。所以 `from x import *` 是把 mod 的（或 `__all__` 指定的）所有名字绑过来——会污染当前命名空间，且 `pyflakes` 难查未定义，避免。

### 3. `__name__` 的本质

每个模块有个 `__name__`：
- 被直接运行（`python mod.py`）：`__name__ == "__main__"`
- 被导入：`__name__ == 模块全名`（如 `package.mod`）

`if __name__ == "__main__":` 就是利用这点：**直接运行时才执行主逻辑，被导入时只定义不执行**。这是 CLI 入口、避免导入副作用的标准写法。

### 4. 包与 `__init__.py`

包是含 `__init__.py` 的目录。`__init__.py` 在包被导入时执行，可放包级初始化、`__all__`。相对导入 `from . import x` / `from ..sub import y` 基于**当前模块的 `__name__`（绝对名）** 解析。

### 5. 为什么主脚本不能直接相对导入

`python mod.py` 时，`mod` 的 `__name__` 是 `"__main__"`，**没有包上下文**（它不是某个包的子模块），所以 `from . import x` 找不到“当前包”，抛 `ImportError: attempted relative import with no known parent package`。要用 `python -m package.mod` 运行（`-m` 会把它作为包内模块加载，提供包上下文）。

### 6. 循环导入

`a.py` 顶层 `import b`，`b.py` 顶层 `import a`：`a` 执行到 `import b` 时 `b` 开始执行，`b` 又 `import a`——此时 `a` 还在执行中、`sys.modules['a']` 已存在但是**半初始化**（顶层符号还没定义完），`b` 拿到的是不完整的 `a`，若用到 `a.foo` 就 `AttributeError`。解决：把 import 移到函数内（延迟导入）、或抽出公共符号到第三个模块。

## 用法

```python
# 显式导入（推荐）
from utils.http import request
import requests as http

# 入口守卫
def main(): ...
if __name__ == "__main__":
    main()

# -m 运行包内模块（支持相对导入）
# python -m my_pkg.run
```

## 踩坑

- **循环导入**：用延迟导入（函数内 import）或抽公共模块解决。
- **相对导入在主脚本跑报错**：用 `python -m package.mod`，别直接 `python mod.py`。
- **`from mod import *` 污染**：避免；显式 import 或用 `__all__` 约束。
- **同名文件遮蔽库**：目录下有 `requests.py` 会遮蔽真正的 requests 包，诡异难查——别用库名当文件名。
- **`__init__.py` 写重逻辑**：包导入就执行，拖慢启动；保持轻量。
- **`import` 只执行一次**：多次 import 不会重跑顶层代码（有 `sys.modules` 缓存）；热重载要 `importlib.reload`。
- **顶层副作用**：模块顶层 print/连接会在每次首次 import 执行，CI 日志被污染。

## 面试怎么答

`import` 流程：查 `sys.modules` 缓存 → 按 `sys.path` 找 → 执行模块顶层代码 → 缓存并返回。所以导入=执行一次+建立引用，顶层有副作用每次首次 import 都跑。

`__name__` 直接运行为 `"__main__"`、被导入为模块全名；`if __name__ == "__main__"` 隔离导入副作用。相对导入依赖包绝对名，主脚本直接跑没有包上下文会报错，要 `python -m package.mod`。循环导入用延迟导入/抽公共模块解决。同名文件遮蔽标准库是隐蔽坑。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/tutorial/modules.html
- 相关笔记：[[Python 工程化：虚拟环境、导入机制与类型注解]] [[Python 函数参数与调用]]
