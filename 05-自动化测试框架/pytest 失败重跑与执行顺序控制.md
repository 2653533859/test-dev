---
created: 2026-07-31
tags: [自动化测试框架/pytest插件]
---

# pytest 失败重跑与执行顺序控制

> 图示：重跑是把「偶发失败」和「真 bug」区分开的缓冲，顺序控制是不得已的妥协——两者都该慎用。

## 概念

- **失败重跑（rerun）**：靠 `pytest-rerunfailures` 插件，用例失败后自动再跑 N 次，只要有一次通过就记为通过。用来消化「偶发/不稳定（flaky）」用例，避免 CI 被噪声打断。
- **执行顺序控制**：靠 `pytest-ordering` 插件，用 `@pytest.mark.order(n)` 强制用例按指定序号跑。pytest 默认顺序是「按模块/文件收集顺序、文件内按定义顺序」，并不保证跨文件的稳定次序。

两个能力解决不同问题：重跑是**容错**，顺序控制是**编排**。但它们都容易掩盖设计问题。

## 用法

```bash
# 安装
pip install pytest-rerunfailures pytest-ordering
```

```python
# 失败重跑：命令行对全部用例
# pytest test_login.py --reruns 3 --reruns-delay 1

# 或只对标记的用例重跑（更推荐，精确控制）
import pytest

@pytest.mark.flaky(reruns=3, reruns_delay=1)
def test_pay_callback_eventually():
    # 回调可能延迟到达，前两次查不到属正常抖动
    assert get_callback_status() == "done"
```

```python
# 执行顺序控制：仅当用例间真有硬依赖时才用
import pytest

@pytest.mark.order(2)
def test_create_order():
    ...

@pytest.mark.order(1)
def test_prepare_user():
    ...
```

## 踩坑

- **重跑掩盖真 bug**：把「偶发失败」全靠重跑抹平，等于把 CI 变成薛定谔的绿。先确认是环境/异步导致的 flaky，再标记 `flaky`，并持续统计重跑命中率，命中率高的要回头修用例。
- **`flaky` 滥用到核心断言**：只应对「等待类」抖动（回调、异步、弱网），不能用来包住「接口契约」断言。
- **顺序控制破坏隔离**：用例一旦依赖顺序，就失去了独立可跑性——单跑某一个必然挂，并行（`xdist`）下 `order` 基本失效，且多人改代码时顺序极易冲突。
- **重跑 + 有副作用的用例**：被重跑的用例若会写库/发消息，重跑会产生重复数据，必须确保用例幂等或自带清理。
- **`reruns-delay` 太小**：抖动还没恢复就立刻重跑，等于没重跑；太大拖慢流水线，按业务恢复时间取中间值（通常 1–2s）。

## 面试怎么答

- **为什么不建议让用例互相依赖 / 控制顺序？** 独立可跑、可并行是自动化的根基；依赖顺序会让「定位失败」「并行提速」「单测调试」全部失效。`pytest-ordering` 是兜底，不是常态。
- **flaky 用例你怎么处理？** 先区分：环境/异步抖动 → 加 `flaky` 重跑 + 统计命中率；用例自身不幂等/有依赖 → 重构用例，而不是无脑重跑。
- **重跑能替代重试机制吗？** 不能。重跑是测试侧兜底，生产侧要有幂等 + 真实重试（如接口超时重试）。两者目的不同。
- **并行和顺序控制冲突怎么办？** 说明顺序控制只适用于必须串行的极少数场景（如准备/清理），其余一律设计成无依赖，交给 `xdist` 并行。

## 参考

- [pytest-rerunfailures](https://pypi.org/project/pytest-rerunfailures/)
- [pytest-ordering](https://pypi.org/project/pytest-ordering/)
- 相关笔记：[[pytest 标记与用例筛选]]、[[pytest-xdist 并行执行]]、[[pytest fixture 详解]]、[[测试框架日志与断言封装]]
