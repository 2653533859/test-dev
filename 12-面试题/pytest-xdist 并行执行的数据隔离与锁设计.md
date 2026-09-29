---
created: 2026-09-28
tags: [面试题/自动化测试框架]
---

# pytest-xdist 并行执行的数据隔离与锁设计

> pytest-xdist 是通过多进程（Worker）独立分配用例执行实现并行的。由于各个 Worker 内存空间隔离，`session` 级别的 fixture 会在每个 Worker 中被重复执行一次；因此多进程必须依赖跨进程文件锁（filelock）保证全局初始化只执行一次，并通过动态租户/前缀或数据库事务回滚实现测试数据隔离。

## 30 秒回答骨架

- **运行模型**：`pytest -n <auto/N>` 底层通过 `execnet` 库孵化多个独立的 Python Worker 进程（`gw0`, `gw1` 等）。Master 进程负责用例收集与分发（按 `--dist load` 或 `--dist loadscope`），Worker 负责独立执行并向 Master 汇送测试报告事件。
- **Fixture 陷阱与文件锁设计**：由于 Worker 之间内存独立，`scope="session"` 的 fixture 不再是「全局只执行一次」，而是「**每个 Worker 进程各自执行一次**」。若该 fixture 涉及全量建表、造基础全局账号或生成 Token，会导致多次重复初始化甚至写冲突。标准解法是基于 `filelock`，利用操作系统文件锁配合临时标志文件，让首个抢到锁的 Worker 完成初始化，后续 Worker 校验标志位直接读取缓存产物。
- **数据隔离策略**：
  1. **分发策略隔离（loadscope）**：用 `--dist loadscope` 保证同一个类或同一模块内的用例固定分配到同一个 Worker，避免同模块上下文冲突；
  2. **数据层面隔离**：结合 Worker 标识符 `worker_id`（如 `gw0`），在创建用户/订单时注入带前缀的动态标识（如 `test_user_gw0_uuid`），或者在数据库级别基于事务隔离与嵌套回滚（`SAVEPOINT`）。

## 展开

### 1. pytest-xdist 进程通信与执行流

```text
                  [ pytest Master 进程 ]
               收集用例集合 (NodeIDs: 1..1000)
                            |
           +----------------+----------------+
           | (IPC socket / pipe 管道通讯)       |
           v                                 v
   [ Worker gw0 进程 ]               [ Worker gw1 进程 ]
- 拥有独立 Python 解释器内存        - 拥有独立 Python 解释器内存
- 独立加载 conftest.py              - 独立加载 conftest.py
- 执行 session fixture (第1次)      - 执行 session fixture (重复第2次!)
- 执行用例并回送结果                 - 执行用例并回送结果
```

### 2. Session Fixture 单次初始化的跨进程锁实现

官方推荐的标准设计模式是利用 `filelock.FileLock` 保护临界区，同时利用 pytest 提供的 `tmp_path_factory` 共享跨进程临时目录：

```python
import json
import pytest
from filelock import FileLock

@pytest.fixture(scope="session")
def global_admin_token(tmp_path_factory, worker_id):
    # 如果是非多进程运行模式（即 worker_id 为 master）直接执行单次初始化
    if worker_id == "master":
        return login_and_get_token()

    # 跨进程共享目录
    root_tmp_dir = tmp_path_factory.getbasetemp().parent
    fn = root_tmp_dir / "admin_token_cache.json"
    lock_file = root_tmp_dir / "admin_token_cache.lock"

    with FileLock(str(lock_file)):
        if fn.is_file():
            # 已经有先行 Worker 写入了数据，直接反序列化读取
            data = json.loads(fn.read_text(encoding="utf-8"))
        else:
            # 抢到锁的首个 Worker，执行远程建连、数据初始化
            token = login_and_get_token()
            data = {"token": token}
            fn.write_text(json.dumps(data), encoding="utf-8")

    return data["token"]
```

### 3. 分发策略选型：`--dist` 的关键差异

- `--dist load`（默认）：将每条独立用例逐一派发给最先空闲的 Worker。
  - **风险**：同一个测试类内部的步骤用例可能会被割裂在 `gw0` 和 `gw1`，如果测试类有类级依赖或复用类属性状态，必崩。
- `--dist loadscope`：将**同一个测试类（`TestClass`）或同一个测试文件**内的用例全部打包分发给同一个 Worker。
  - **收益**：既保证了文件/类内部的状态连续性，又实现了文件维度的多核并行，是**状态相关型自动化套件的最佳实践**。
- `--dist loadfile`：按测试文件维度分派给不同 Worker。

### 4. 数据库测试数据多进程隔离策略

1. **动态租户 / Worker 隔离账号体系**：
   - 依赖 pytest 的内置 fixture `worker_id`，生成隔离标识：
   ```python
   @pytest.fixture(scope="function")
   def isolated_user(worker_id):
       username = f"user_{worker_id}_{uuid.uuid4().hex[:8]}"
       user = db.create_user(username)
       yield user
       db.delete_user(user.id)
   ```
2. **数据库事务嵌套回滚（Transactional Rollback）**：
   - 对于只读或本地验证型测试，每个 Worker 在 `setUp` 阶段开启一个数据库事务（`BEGIN`），用例结束后在 `tearDown` 强制执行 `ROLLBACK`，数据永远不落盘到 MySQL 物理表，既消除了并发脏数据污染，又避免了频繁 `INSERT/DELETE` 的磁盘 IO 损耗。

## 可能被追问的点

- **为什么不用普通的 `threading.Lock` 或 `multiprocessing.Lock`，必须用 `filelock`？**
  - `pytest-xdist` 启动 Worker 是通过独立的子进程（跨进程），内存完全不共享，`threading.Lock` 根本跨不了进程；
  - `multiprocessing.Lock` 依赖父子进程之间的句柄继承与 IPC 共享内存对象，而 `pytest-xdist` 基于 `execnet`，在不同 Worker 初始化时没有共享此 Lock 对象上下文；
  - `filelock` 依赖操作系统内核层面的文件锁机制（Linux 的 `fcntl.flock`，Windows 的 `msvcrt.locking`），只要文件路径相同，不同独立进程间即可实现无依赖的互斥等待。
- **并行执行时，测试报告（如 Allure）的结果数据会相互覆盖吗？**
  - Allure 的 pytest 插件在生成结果时，每条用例都会生成以独立 UUID 为文件名的 `-result.json` 文件。
  - 只要确保各个 Worker 的 `--alluredir` 指向同一个目录，且该目录在 Master 初始化时创建，各个 Worker 往同一目录并行写入独立文件并不冲突。
- **如果有部分用例由于历史包袱必须串行（单例接口），如何与并行用例混跑？**
  - 结合插件 `pytest-split` 或 pytest 的标记机制（`@pytest.mark.serial`）；
  - 在 CI 流程中配置分阶段执行：阶段一 `pytest -n auto -m "not serial"` 跑并发用例；阶段二 `pytest -n 1 -m "serial"` 串行跑敏感用例。

## 结合自己项目的例子

在公司电商结算链路的 Web 端与接口自动化测试套件中，全量用例约 1800 条，单进程跑完需 48 分钟。

- **迁移痛点**：引入 `pytest -n 4` 试图压缩时长，但构建结果直接飘红：
  1. `conftest.py` 中有预生成管理员全量测试资金池的逻辑，4 个 Worker 同时触发余额清空与充值，导致出现余额死锁和重复充值异常；
  2. 多条下单用例直接硬编码了公共测试商品 ID `10001`，并发 Worker 同时扣减库存，频频报 `库存不足，下单失败`。
- **落地改造**：
  1. **锁与单次初始化**：基于 `filelock` 重写 `global_mock_server` 与平台初始化 Fixture，保证单次幂等创建；
  2. **商品数据隔离池**：重构商品数据 Fixture，依据 `worker_id` 从 Redis 预热列表中弹出对应分片的 SKU 集合（如 `gw0` 取 `SKU_1001~1500`，`gw1` 取 `SKU_1501~2000`），用后回收；
  3. **分发模式改动**：由默认 `--dist load` 调整为 `--dist loadscope`，确保支付单完整状态机留在同一 Worker 执行。
- **效果**：用例运行耗时从 48 分钟缩短至 13 分钟（提速 3.7 倍），且用例通过率从多进程初期的 82% 稳定回升至 99.4%。

## 参考

- pytest-xdist 官方文档：`Specifying distribution modes` & `Making session-scoped fixtures execute only once`
- 相关笔记：[[05-自动化测试框架]]、[[fixture 与 setUp 的区别及四种作用域]]、[[GIL 对多线程的约束与高并发绕过方案]]
