---
created: 2026-07-31
tags: [Python基础/工程化]
---

# Python 工程化：虚拟环境、导入机制与类型注解

## 概念一：为什么需要虚拟环境

Python 的第三方包全局安装会撞车：项目 A 要 `requests==2.25`，项目 B 要 `requests==2.31`，同一个 `site-packages` 只能留一份。虚拟环境（venv）就是给每个项目**建一份独立的 `python` + 独立的 `site-packages`**，互相隔离。

### venv 做了什么

```bash
python -m venv .venv        # 在当前目录生成 .venv/
source .venv/bin/activate   # Linux/Mac 激活（Windows: .venv\Scripts\activate）
python -m pip install requests==2.31
```

`venv` 复制/软链了一个 Python 解释器副本，并把 `sys.prefix` 指向 `.venv`。激活后，`python`、`pip` 都解析到 `.venv` 里的那份，安装的包只进 `.venv/lib/pythonX.Y/site-packages`。

> 原理：激活脚本本质是修改 `PATH`，让 `.venv/bin` 排在最前面。所以「激活」不是魔法，就是改环境变量。

### 依赖锁定与可复现

```bash
pip freeze > requirements.txt     # 导出精确版本
pip install -r requirements.txt   # 别人据此重建一模一样的环境
```

更现代的做法是 `pyproject.toml`（PEP 518/621）声明依赖与构建系统，`pip install .` 或 `pip install -e .`（可编辑安装）。

## 概念二：import 的底层流程（详见 [[Python 模块与包的使用]]）

复习关键链路：

1. 解释器按 `import spam` 找名字，先看 `sys.modules`（已导入缓存）里有没有。
2. 没有则按 `sys.path`（一个目录列表：当前目录、`PYTHONPATH`、标准库、`site-packages`）依次找 `spam.py` 或 `spam/` 包。
3. 找到后**编译成 `.pyc` 字节码**（缓存到 `__pycache__`），创建模块对象，执行其顶层代码，把结果塞进 `sys.modules['spam']`。
4. 把模块绑定到当前命名空间的 `spam` 变量。

因为第 1 步先查 `sys.modules`，所以**模块只会被执行一次**——即使被多处 import，顶层代码（含可能的副作用）只跑一遍。这也是循环导入问题的根源（半初始化的模块被引用）。

相对导入 `from . import x` 只在「作为包的一部分被导入」时有效；**直接 `python mod.py` 运行脚本时，`__name__ == "__main__"`，没有包上下文，`from . import` 会报 `ImportError: attempted relative import with no known parent package`**。

## 概念三：类型注解是「可选提示」，不是强制约束

Python 仍是动态语言。`x: int = "hello"` **运行时不会报错**——注解不阻止错误赋值。它服务于：IDE 补全/检查、静态类型检查器（`mypy`/`pyright`）、生成文档、可读性与重构安全。

```python
def add(a: int, b: int) -> int:
    return a + b

add("a", "b")     # 运行时照常返回 "ab"；只有 mypy 会报错
```

### 变量注解与 `typing`

```python
from typing import List, Dict, Optional, Union, Tuple

names: List[str] = ["a", "b"]
scores: Dict[str, int] = {"a": 1}
maybe: Optional[int] = None            # == Union[int, None]
pair: Tuple[int, str] = (1, "x")
```

Python 3.9+ 很多泛型可用内置类型直接写：`list[str]`、`dict[str, int]`、`tuple[int, str]`、`X | None`（3.10+），无需再 import。

## 用法：类型进阶（详见 [[Python typing 进阶：泛型、Protocol 与 TypedDict]]）

```python
from typing import TypeVar, Protocol, runtime_checkable

T = TypeVar("T")

def first(items: list[T]) -> T:
    return items[0]

@runtime_checkable
class Sized(Protocol):
    def __len__(self) -> int: ...

# 结构化子类型：只要实现了 __len__，就满足 Sized，无需显式继承
def count(x: Sized) -> int:
    return len(x)
```

## 踩坑

1. **虚拟环境没激活就装包**：装到了全局 `site-packages`，项目隔离被破坏。一次 `which python` / `pip --version` 即可确认。
2. **把 `.venv` 提交进 Git**：它体积大且平台相关，应在 `.gitignore` 忽略。提交 `requirements.txt` / `pyproject.toml` 即可重建。
3. **注解当成了运行时校验**：`x: int` 不拦 `x="a"`，真要校验用 `pydantic`（见 [[Python pydantic 数据校验]]）或运行时 `isinstance`。
4. **循环导入**：A import B、B import A。解法：把 import 移到函数内（延迟导入）、合并模块、或抽公共依赖到第三模块。
5. **相对导入在主脚本运行报错**：脚本方式运行没有包上下文。用 `python -m package.module` 以模块方式运行可拿到包上下文。
6. **`from __future__ import annotations`**：加上后注解变成字符串不立即求值，可避免前向引用报错（如注解尚未定义的类），且对运行无影响，推荐在文件头加上。
7. **`isinstance` 不能对 `list[int]` 这类参数化泛型用**：`isinstance(x, list[int])` 会报错（3.9+ 部分支持但受限）；泛型只在类型检查期有意义。

## 面试怎么答

**Q：虚拟环境解决了什么问题？原理？**
A：隔离各项目的第三方依赖版本。`venv` 给项目建独立 Python 和 `site-packages`，激活脚本通过改 `PATH` 让 `.venv/bin` 优先，使 `python`/`pip` 指向隔离环境。

**Q：import 一个模块时发生了什么？**
A：先查 `sys.modules` 缓存；没有就按 `sys.path` 找 `.py`/包；编译成 `.pyc` 缓存、创建模块对象、执行顶层代码、存入 `sys.modules` 并绑定到当前命名空间的名字。因此模块只执行一次。

**Q：Python 的类型注解是强制的吗？**
A：不是。Python 运行时忽略注解，变量仍可赋任意类型值。注解服务于静态检查器、IDE 和可读性，不是运行时约束。

**Q：循环导入怎么解决？**
A：三种常见手法——把 import 放到函数/方法内部（延迟到调用时才导入）、把共同依赖抽到第三个模块、或用类型注解前向引用（`from __future__ import annotations` + 字符串注解）。
