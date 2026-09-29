---
created: 2026-07-31
tags: [Python基础/标准库]
---

# Python logging 日志

![[assets/logging-arch.svg]]
*图示：logging 四件套——Logger 产生日志、Handler 决定输出目的地、Formatter 决定格式；子 Logger 默认 `propagate` 向上传给父 Handler。*

> `print` 调试在脚本跑完就丢了；`logging` 能带级别、带时间、带模块名、输出到文件和控制台，是定位失败用例的标配。理解 Logger/Handler/Formatter 的分层传播与“延迟格式化”，才不会再掉进“没日志/重复日志”的坑。

## 概念

### 1. 四个核心组件

- **Logger**：入口，`logging.getLogger(name)`，同名返回同一实例（模块级用 `__name__`）。决定“这条日志要不要发”。
- **Handler**：决定“发到哪”（`StreamHandler` 控制台、`FileHandler` 文件、`SMTPHandler`…）。一个 Logger 可有多个 Handler。
- **Formatter**：决定“长什么样”（时间/级别/模块/行号/信息），用 `%`-style 或 `{`/`$` style。
- **Filter**：更细的过滤（按 Logger 名、字段）。

### 2. 级别与传播

五级（数值递增）：`DEBUG(10) < INFO(20) < WARNING(30) < ERROR(40) < CRITICAL(50)`。

- 每条日志有级别；Logger 和 Handler 各有**阈值**，低于阈值被丢弃。
- **effective level**：取“自身 level 与继承链”的最小值；未设置则向上继承父 Logger（最终到 root）。
- **propagate**：子 Logger 默认把日志向上传给父 Logger 的 Handler（所以 root 配好 Handler，子 Logger 自动有文件/控制台输出）。

### 3. 为什么 `basicConfig` 重复调用无效

`basicConfig(...)` 只在**根 Logger 还没有任何 Handler 时**生效一次。若框架/库已给 root 加了 Handler（常见于 pytest、Django），你再调 `basicConfig` 会被静默忽略——这是“为什么我配了格式却不生效”的头号原因。要重配置先 `logging.getLogger().handlers.clear()`。

### 4. 延迟格式化：`%` 占位 vs f-string

`log.info("x=%s", x)` 内部用 `%` 格式化，但**只有级别通过、真的要输出时**才格式化字符串。好处：级别不够时**不格式化**（省 CPU、且格式化抛异常也不会影响主流程）。这正是不用 f-string 预拼接的原因（见 [[Python 字符串格式化与 f-string]]）。

### 5. 日志事件：LogRecord

每条日志是一个 `LogRecord` 对象，携带 `created`(时间)、`levelname`、`name`(Logger 名)、`lineno`、`msg`、`exc_info` 等。Handler/Formatter 消费它。

## 用法

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler("run.log", encoding="utf-8"),
              logging.StreamHandler()],
)
log = logging.getLogger("api_test")
log.info("开始执行用例 %s", "login")     # % 占位，懒求值
log.exception("请求失败")                 # 自动带 traceback
```

## 踩坑

- **`basicConfig` 只在 root 无 Handler 时生效**：重复调用无效；被框架占用时先清 handlers 再配。
- **`propagate` 导致重复日志**：子 Logger 和父 Logger 都有 Handler 时，一条日志被输出多次；要么只在 root 配 Handler，要么设子 `propagate=False`。
- **级别不够仍格式化**：用 `log.info("x=%s", x)` 而非 f-string 预拼接；懒求值省性能且不掩盖异常。
- **`log.exception` 才带 traceback**：普通 `log.error` 没有栈，定位信息不足。
- **多进程写同一日志文件不安全**：FileHandler 非进程安全；多进程用 `QueueHandler` 或按进程分文件。
- **日志里打印敏感信息**：密码/token 别进日志。
- **`extra` 自定义字段**：`log.info("...", extra={"user": u})` 可在 Formatter 里用 `%(user)s`，便于结构化日志。

## 面试怎么答

`logging` 四件套：Logger（入口/级别判定）、Handler（输出目的地）、Formatter（格式）、Filter（细过滤）。级别 DEBUG<INFO<WARNING<ERROR<CRITICAL；有效级别取自身与继承链最小；子 Logger 默认 propagate 把日志上传给父 Handler。

关键坑：① `basicConfig` 只在 root 无 Handler 时生效，重复调用无效（框架已配时不生效）；② 用 `getLogger(__name__)`，参数用 `%` 占位懒求值（级别不够不格式化），别用 f-string 预拼接；③ `log.exception` 才带 traceback；④ 多进程写同一文件要用 QueueHandler。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/library/logging.html
- 相关笔记：[[Python 异常处理]] [[Python 字符串格式化与 f-string]] [[Python pathlib 路径处理]]
