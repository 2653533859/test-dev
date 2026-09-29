---
created: 2026-07-31
tags: [自动化测试框架/插件]
---

# pytest-xdist 并行执行

![[assets/xdist-distribution.svg]]
*图示：xdist 是「主控进程收集分发 + 多 worker 独立进程执行」的模型——每个 worker 都是完整的 pytest 进程，所以 session 级 fixture 会被执行 N 次，进程间内存完全不共享。*

> 把 2 小时的回归压到 20 分钟。但并行的前提是用例互相独立，否则只会得到「随机失败的 2 小时」。

## 概念

### 它是怎么工作的

`pytest -n 4` 之后发生的事：

1. **主控进程（master）**完成收集，得到完整的 nodeid 列表；
2. 用 `execnet` 启动 4 个**独立的 Python 进程**（gw0~gw3），每个都是完整的 pytest 运行时；
3. 每个 worker **各自重新收集一遍**用例（为了保证 nodeid 一致，会做一致性校验）；
4. master 按 `--dist` 策略把 nodeid 分发给 worker；
5. worker 执行完把 TestReport 序列化回传，master 汇总输出。

三个必须记住的推论：

- **worker 是独立进程**，内存不共享。模块级全局变量、单例、缓存，各 worker 各一份。
- **session 级 fixture 会执行 N 次**（每个 worker 一次），不是一次。
- **执行顺序不可预测**，任何依赖用例顺序的设计都会崩。

### `-n` 的取值

```bash
pytest -n 4              # 固定 4 个 worker
pytest -n auto           # 等于 CPU 逻辑核数
pytest -n logical        # 同 auto（显式）
pytest -n 0              # 禁用并行（覆盖 addopts 里的配置，调试时用）
```

选值经验：

- **接口/单元测试**（CPU 与网络混合）：`auto` 或 `CPU 核数`；
- **UI 测试**（每个 worker 一个浏览器，吃内存）：`2~4`，按内存算，一个 Chrome 约 300–500 MB；
- **CI 容器里**：`auto` 会读到宿主机核数（容器 CPU limit 读不到），经常起 64 个 worker 把容器打爆。**CI 里必须显式指定数字**。

### `--dist` 分发策略

| 策略 | 分发粒度 | 适用 |
|------|---------|------|
| `load`（默认） | 单条用例，谁空闲发给谁 | 用例完全独立，负载最均衡 |
| `loadfile` | 同一文件的用例发给同一 worker | 有 module 级 fixture，避免重复建 |
| `loadscope` | 同一 class/module 发给同一 worker | 有 class 级共享状态 |
| `loadgroup` | 按 `@pytest.mark.xdist_group("name")` 分组 | 需要手工指定哪些用例必须同进程 |
| `each` | 每个用例在**所有** worker 上都跑一遍 | 跨环境/跨平台冒烟 |
| `no` | 不分发 | 配合 `--tx` 手工控制 |

```bash
pytest -n 4 --dist=loadfile
pytest -n 4 --dist=loadgroup
```

`loadgroup` 是解决「少数用例必须串行/同进程」的最佳工具：

```python
@pytest.mark.xdist_group("account-lock")
def test_lock_account(): ...


@pytest.mark.xdist_group("account-lock")
def test_unlock_account(): ...
# 这两条一定在同一个 worker 上按顺序执行，其它用例照常并行
```

### 并行的真正门槛：用例独立性

xdist 本身很好用，难的是让用例能并行。三类冲突：

**1. 数据冲突**——多个用例操作同一条数据。

```python
# 反例：所有用例共用固定手机号，并行时互相覆盖
PHONE = "13800138000"


def test_register():
    register(PHONE)          # gw0 注册

def test_register_duplicate():
    delete_user(PHONE)       # gw1 同时把它删了 → gw0 的断言挂
    ...
```

**2. 资源冲突**——固定端口、固定文件路径、固定下载目录。

**3. 全局状态冲突**——修改环境变量、修改配置单例、`monkeypatch` 全局对象。进程隔离让这类冲突比多线程少，但共享的外部资源（同一个 Redis key、同一个日志文件）依然会冲。

### 隔离的三板斧

```python
import os
import uuid

import pytest


# 1. 数据唯一化：每条用例造自己的数据
@pytest.fixture
def temp_user(api):
    phone = f"138{uuid.uuid4().int % 10**8:08d}"      # 每次不同
    u = api.create_user(phone=phone)
    yield u
    api.delete_user(u.id)


# 2. 用 worker id 做资源分片
@pytest.fixture(scope="session")
def worker_id() -> str:
    """非并行时返回 'master'，并行时返回 'gw0'/'gw1'..."""
    return os.environ.get("PYTEST_XDIST_WORKER", "master")


@pytest.fixture(scope="session")
def db_schema(worker_id):
    """每个 worker 用独立的库/schema，彻底隔离。"""
    name = f"test_{worker_id}"
    create_schema(name)
    yield name
    drop_schema(name)


@pytest.fixture(scope="session")
def free_port(worker_id):
    """按 worker 分配端口，避免端口占用。"""
    idx = 0 if worker_id == "master" else int(worker_id.replace("gw", ""))
    return 9000 + idx


# 3. 账号池：从池里领，用完还
@pytest.fixture
def account(account_pool):
    acc = account_pool.acquire()       # 内部用文件锁或 Redis 保证互斥
    yield acc
    account_pool.release(acc)
```

`PYTEST_XDIST_WORKER` 环境变量是最重要的一个钩子——它是实现「按 worker 分片」的唯一依据。xdist 还提供了内置的 `worker_id` fixture，效果相同。

### session 级初始化只做一次

有些初始化必须全局只做一次（建表、灌基础数据、启动 mock server）。跨进程只能靠**文件锁 + 标记文件**：

```python
import json

import pytest
from filelock import FileLock       # pip install filelock


@pytest.fixture(scope="session")
def shared_setup(tmp_path_factory, worker_id):
    if worker_id == "master":
        return do_init()             # 没并行，直接做

    # 所有 worker 共享的根临时目录（xdist 保证同一次运行下相同）
    root = tmp_path_factory.getbasetemp().parent
    marker = root / "shared_setup.json"
    with FileLock(str(marker) + ".lock"):
        if marker.is_file():
            data = json.loads(marker.read_text())        # 别人已经做过了
        else:
            data = do_init()
            marker.write_text(json.dumps(data))
    return data
```

这是 xdist 官方文档给出的标准范式，接口框架里「全局登录拿 token」「建测试库」都该这么写。

## 用法

### 一套可直接抄的配置

```ini
# pytest.ini
[pytest]
addopts =
    -ra
    --strict-markers
    --dist=loadfile
markers =
    serial: 必须串行执行的用例
```

```bash
# 本地调试：不并行，输出清晰
pytest tests/api -n 0 -v

# 本地跑全量
pytest tests/api -n auto

# CI：显式指定数量，避免读到宿主机核数
pytest tests/api -n 4 --dist=loadfile --alluredir=./allure-results

# 串行用例单独一轮跑
pytest -m serial -n 0
pytest -m "not serial" -n 4
```

「先并行跑大部分、再串行跑少数」这个两段式，是处理少量无法并行用例的最实用方案。

### 与 allure / rerunfailures 一起用

```bash
pytest -n 4 \
       --dist=loadfile \
       --reruns 2 --reruns-delay 3 \
       --alluredir=./allure-results \
       --clean-alluredir
```

注意事项：

- `--alluredir` 在并行下是**多进程写同一目录**，allure 用的是「每条用例一个 json 文件」，天然无冲突，可以直接用；
- `-n` 与 `--reruns` 可以叠加，重跑发生在同一个 worker 内；
- **`-x`（首次失败即停）在并行下语义变模糊**——其它 worker 已经跑出去的用例还会继续，停止不是即时的。

### 输出与调试

并行下 `print` 和日志会交错，几乎不可读。三个应对：

```bash
# 1. 显示每条用例归属哪个 worker
pytest -n 4 -v          # 输出前缀 [gw0] [gw1]

# 2. 复现问题时先关并行
pytest -n 0 "tests/api/test_x.py::test_y" -v -s

# 3. 日志按 worker 分文件
```

```python
# conftest.py：每个 worker 写独立日志文件
import logging
import os
from pathlib import Path


def pytest_configure(config):
    worker = os.environ.get("PYTEST_XDIST_WORKER", "master")
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    handler = logging.FileHandler(log_dir / f"pytest-{worker}.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] [" + worker + "] %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
```

### 验证并行安全性

上并行前先做一次「乱序 + 并行」双重压力测试：

```bash
# 1. 先用 pytest-randomly 打乱顺序跑几遍，暴露顺序依赖
pytest -p randomly --randomly-seed=12345
pytest -p randomly --randomly-seed=54321

# 2. 再开并行跑几遍，暴露数据冲突
pytest -n 4 && pytest -n 4 && pytest -n 4

# 3. 对比串行结果
pytest -n 0
```

如果三种模式结果不一致，说明用例之间有隐式依赖，先修用例再开并行。

## 踩坑

1. **session 级 fixture 被执行 N 次**。以为登录只发生一次，实际 4 个 worker 各登录一次，触发风控「同一账号频繁登录」被锁。解法：用文件锁 + 标记文件保证全局只做一次，或者干脆给每个 worker 分配不同账号。

2. **CI 容器里 `-n auto` 起了 64 个 worker**。`auto` 读的是宿主机的 CPU 核数，容器的 CPU limit 它读不到，结果内存被打爆、OOM Kill。**CI 里必须写死数字**，或者用 `-n $(nproc)`（nproc 在设了 cgroup limit 的新内核下能读到正确值）。

3. **用例共用固定测试数据，并行后随机失败**。最典型的是固定手机号、固定订单号、固定账号。表现是「串行全过、并行随机挂几条，且每次挂的不一样」。这是并行改造 90% 的工作量所在——把所有固定数据改成动态生成。

4. **依赖用例执行顺序**。`test_01_create` → `test_02_query` 这种设计在并行下必然崩，两条用例可能在不同 worker 上同时跑。要么改成自包含用例（自己造数据），要么用 `--dist=loadgroup` + `xdist_group` 标记绑到同一 worker。

5. **worker 崩溃导致 `node down: Not properly terminated`**。通常是被测代码或 fixture 里调用了 `sys.exit()`、`os._exit()`，或者进程被 OOM Kill。报错信息很不友好，排查时先降到 `-n 2` 再 `-n 0`，同时看系统 dmesg 有没有 OOM 记录。

6. **worker 之间收集结果不一致**，报 `Different tests were collected between gw0 and gw1`。原因是收集期存在随机性——比如用了 `pytest-randomly` 但 seed 不固定、参数化数据来自「每次调用结果不同」的函数（`datetime.now()`、`random`、集合遍历顺序）。**参数化数据必须是确定性的**。

7. **`-x` 在并行下不会立即停**。已经分发出去的用例还会跑完，所以看到的失败数可能大于 1。想要严格 fail-fast，用 `--maxfail=1` 配合 `-n 0`，或者接受这个语义差异。

8. **临时文件/下载目录冲突**。多个 worker 同时往 `./downloads/` 写同名文件。用 `tmp_path`（每条用例独立）或按 `worker_id` 分目录。

9. **数据库连接池被打满**。4 个 worker × 每个池 10 连接 = 40 个连接，加上应用自己的，很容易超过 MySQL 的 `max_connections`。并行度上去后要同步调小每个 worker 的池大小。

10. **性能并没有 4 倍提升**。用例大部分时间在等接口响应，瓶颈在被测服务而不是测试机。并行前先看瓶颈在哪——如果被测服务是单实例，压上去只会让响应变慢甚至触发限流。

11. **`--dist=load` 打散了 module fixture**。同一文件的用例被分到不同 worker，module 级 fixture 各建一次。有重量级 module fixture（浏览器、mock server）时应该用 `--dist=loadfile`。

## 面试怎么答

**Q：怎么加速自动化用例的执行？**

A（30 秒骨架）：先定位瓶颈再动手。如果瓶颈在测试机，用 `pytest-xdist` 做多进程并行，`pytest -n 4`；如果瓶颈在被测服务，并行反而更慢，得先做服务端扩容或降低并发。xdist 的模型是主控进程收集分发、多个独立 worker 进程执行，所以进程间内存不共享、session 级 fixture 会被执行 N 次、执行顺序不可预测。真正的门槛不是配置，是**用例独立性**——固定测试数据、用例间顺序依赖、共享资源，这三类问题不解决，并行只会带来随机失败。

**追问 1：并行下 session 级 fixture 怎么办？**

A：分两种情况。如果是「每个 worker 各自持有一份」没问题的资源（HTTP 客户端、日志器），直接用就行，多建几次不影响。如果是「全局只能做一次」的初始化（建表、灌基础数据、启动 mock server），需要跨进程同步：用 `filelock` 加文件锁，配合一个标记文件——第一个拿到锁的 worker 执行初始化并把结果写进标记文件，后面的 worker 直接读文件。这是 xdist 官方文档给的标准范式。另外用 `PYTEST_XDIST_WORKER` 环境变量能拿到当前 worker id，可以按 worker 分配独立的数据库 schema、端口、账号，做物理隔离。

**追问 2：哪些用例不能并行，怎么处理？**

A：三类——必须按顺序执行的、修改全局共享状态的、抢占独占资源的。处理方式有两个层次。首选是**改造用例**：把固定数据改成 uuid 动态生成，把「先创建后查询」的两条用例合并成一条自包含用例。改造不了的，用 `--dist=loadgroup` 加 `@pytest.mark.xdist_group("组名")` 把它们绑到同一个 worker 顺序执行，其它用例照常并行。再不行就打 `serial` 标记，CI 里分两轮跑：`pytest -m "not serial" -n 4` 然后 `pytest -m serial -n 0`。

**追问 3：并行后出现随机失败怎么排查？**

A：四步。第一步先确认是不是并行引起的——同一个 seed 下 `-n 0` 串行跑几遍，如果串行稳定、并行随机挂，基本可以确定是并行冲突。第二步用 `-v` 看失败用例分布在哪些 worker，同一 worker 内连续失败通常是 fixture 问题，跨 worker 分散失败通常是数据冲突。第三步查测试数据——有没有固定手机号、固定账号、共用的 Redis key。第四步用 `pytest-randomly` 打乱顺序串行跑，如果乱序也挂，说明本质是**用例顺序依赖**而不是并行问题，那是更根本的设计缺陷。

**追问 4：`--dist` 几种策略怎么选？**

A：默认 `load` 是按单条用例分发、谁空闲发给谁，负载最均衡，适合用例完全独立的场景。如果有重量级的 module 级 fixture（浏览器实例、mock server），用 `loadfile` 让同一文件的用例落到同一 worker，避免每个 worker 都建一遍。有 class 级共享状态用 `loadscope`。少数用例需要绑定在一起时用 `loadgroup` 配合 `xdist_group` 标记。我一般默认配 `loadfile`——它在负载均衡和 fixture 复用之间比较平衡。

## 参考

- [pytest-xdist 官方文档](https://pytest-xdist.readthedocs.io/)
- [xdist：并行下的 session fixture 范式](https://pytest-xdist.readthedocs.io/en/stable/how-to.html#making-session-scoped-fixtures-execute-only-once)
- 相关笔记：[[pytest fixture 详解]]、[[pytest 失败重跑与执行顺序控制]]、[[测试报告：pytest-html 与 Allure]]、[[分层测试模型与测试金字塔]]
