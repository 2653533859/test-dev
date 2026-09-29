---
created: 2026-07-31
tags: [Python基础/并发]
---

# Python asyncio 实战

![[assets/asyncio-eventloop.svg]]
*图示：协程在事件循环里靠 `await` 让出/唤醒，gather 并发启动、总耗时≈最慢任务而非累加。*

## 概念：asyncio 是「单线程里的协作式多任务」

`asyncio` 解决的是**海量 I/O 并发**的问题：几千上万个网络连接在单线程内被高效调度，内存占用低、没有线程切换开销。

它的核心三件套：
- **协程（coroutine）**：用 `async def` 定义的函数，调用它不会立即执行，而是返回一个协程对象。
- **事件循环（event loop）**：调度中心，负责在「等待点」把控制权切到下一个就绪的协程。
- **await 等待点**：遇到 `await`，当前协程**主动让出**控制权；当等待的对象就绪后，循环再把它唤醒继续往下跑。

### 为什么是「协作式」而不是「抢占式」

线程是抢占式的：OS 随时可能把 CPU 从你手里抢走。协程是协作式的：**只有当你写 `await` 时才会让出**。这意味着：

```python
async def bad():
    total = 0
    for i in range(10_000_000):   # 纯 CPU 循环，没有 await
        total += i
    return total
```

这段循环里没有 `await`，事件循环**根本没机会切换到别的协程**，整个程序被卡住。所以 asyncio 的世界里，**任何阻塞都要换成「可等待的」版本**：`time.sleep` → `await asyncio.sleep`，`requests.get` → `await aiohttp.get`。

### async/await 与生成器的血缘

`async def` 底层就是「一个能暂停/恢复的函数」，和 `yield` 同源：遇到 `await` 暂停，事件循环在将来某个时刻把它恢复。区别是协程的暂停点语义专门服务于 I/O 等待，并且 `await` 后面必须是「可等待对象」（实现了 `__await__` 的对象：协程、Task、Future，以及标准库里 awaitable 的锁/队列等）。

## 用法一：跑起来——asyncio.run 与 gather

```python
import asyncio

async def fetch(name, delay):
    print(f"{name} 开始")
    await asyncio.sleep(delay)     # 让出控制权
    print(f"{name} 完成，用时 {delay}s")
    return name

async def main():
    # gather：并发启动多个协程，总耗时 ≈ max，而非 sum
    results = await asyncio.gather(
        fetch("A", 2),
        fetch("B", 1),
        fetch("C", 1),
    )
    print(results)                 # ['A', 'B', 'C']

asyncio.run(main())                # 创建循环 → 跑 main → 关闭循环
```

`asyncio.run(main())` 是 Python 3.7+ 的推荐入口：它创建事件循环、运行 `main` 直到完成、然后清理关闭。你**不应该**在脚本里手动 `loop.run_forever()` 了，`run` 已经封装好。

### 逐步推导 gather 的并发

三个任务延迟分别是 2、1、1 秒：
- t=0：A 启动 → await sleep → 让出；B 启动 → await → 让出；C 启动 → await → 让出
- t=1：B、C 的 sleep 就绪，完成；A 还在睡
- t=2：A 完成
- 总耗时 ≈ 2 秒，而非 2+1+1=4 秒

若改成串行 `await fetch("A",2); await fetch("B",1); ...`，则总耗时是累加的 4 秒。这就是并发的加速来源。

## 用法二：create_task 与「 fire and forget」

`gather` 适合「等所有结果」。如果某个协程只是顺手触发、不想阻塞当前流程，用 `asyncio.create_task` 把它变成「任务」立即调度：

```python
async def main():
    task = asyncio.create_task(fetch("后台", 3))   # 立即排入循环，不等它
    print("主协程继续干别的")
    await task                                     # 这里才等它完成
```

`create_task` 返回的 `Task` 本身也是可等待对象。注意：**任务一旦 `create_task` 就被调度，但若主协程什么都不 await 就结束，`asyncio.run` 会取消未完成的任务并抛 `CancelledError`**——所以别忘了最后 `await` 它，或用 `gather` 收集。

## 用法三：asyncio.Queue —— 协程间安全通信

线程间用 `queue.Queue`，协程间必须用 `asyncio.Queue`（它的 `get`/`put` 都是 `await` 的，不会阻塞整个循环）：

```python
import asyncio

async def producer(q):
    for i in range(5):
        await q.put(i)
        print(f"生产 {i}")

async def consumer(q):
    while True:
        item = await q.get()
        print(f"消费 {item}")
        q.task_done()
        if item == 4:
            break

async def main():
    q = asyncio.Queue()
    await asyncio.gather(producer(q), consumer(q))

asyncio.run(main())
```

## 用法四：超时、取消与异常

```python
async def main():
    try:
        # wait_for：超过 1.5 秒就取消 fetch 并抛 TimeoutError
        await asyncio.wait_for(fetch("慢任务", 5), timeout=1.5)
    except asyncio.TimeoutError:
        print("超时取消")

    # gather 默认一个报错就全部抛；return_exceptions=True 可收集异常而非中断
    results = await asyncio.gather(
        fetch("A", 1),
        fetch("B", -1),      # 假设这会抛异常
        return_exceptions=True,
    )
    print(results)           # [返回值, 异常对象]
```

`wait_for` 超时后会向目标任务发 `CancelledError`，这是「协作式取消」——任务需要在 `finally` 里做清理，且不能吞掉 `CancelledError`（否则取消失效）。

## 用法五：真正的并发 I/O——aiohttp 示例

```python
import asyncio, aiohttp

async def get(url, session):
    async with session.get(url) as resp:    # async with + await
        return await resp.text()

async def main():
    urls = ["https://example.com"] * 20
    async with aiohttp.ClientSession() as session:
        # 20 个请求并发发出，比同步 requests 串行快几十倍
        pages = await asyncio.gather(*(get(u, session) for u in urls))
    print(len(pages))

asyncio.run(main())
```

要点：`session` 要复用（每次新建连接开销大）；`async with` 确保连接释放；绝不能在这里用 `requests`，那是同步阻塞会卡死循环。

## 踩坑

1. **在协程里写阻塞调用**（`time.sleep`、`requests.get`、`open` 大文件同步读）：整个事件循环卡死，所有协程一起挂。必须换 awaitable 版本，或用 `loop.run_in_executor` 把阻塞函数丢到线程池。
2. **`async def` 里忘记 `await`**：协程对象不会被运行，只会留下一个「从未执行」的协程，代码静默不工作。
3. **同步函数里直接调用 `async` 函数**：`asyncio.run` 不能在已运行的循环里嵌套调用，会报 `RuntimeError`。在另一个协程里应该用 `await`。
4. **`queue.Queue` 与 `asyncio.Queue` 混用**：线程队列的 `get` 不是 awaitable，放协程里会卡死或报类型错。
5. **任务没被 await 就随主协程退出**：`asyncio.run` 结束会取消所有未 awaited 的任务。
6. **`gather` 一个报错全崩**：用 `return_exceptions=True` 或 `TaskGroup`（3.11+，一个失败会取消其余并汇总异常）。
7. **`CancelledError` 被吞**：在 `except` 里捕获后不重新抛出，会破坏取消机制（3.8+ 中 `CancelledError` 已继承 `BaseException`，更容易误吞）。

## 面试怎么答

**Q：asyncio 和多线程有什么区别？**
A：asyncio 是单线程协作式调度，靠 `await` 主动让出，没有锁、切换开销极低，适合海量 I/O 并发；多线程是 OS 抢占式调度，受 GIL 限制不能并行计算，但能利用阻塞 I/O 的空窗。asyncio 一旦写阻塞调用会卡死整个循环，多线程则不会。

**Q：async/await 的原理？**
A：`async def` 定义的是协程，遇到 `await` 暂停并把控制权交还事件循环，待等待对象就绪后被唤醒继续。它和生成器同源，本质是可暂停/恢复的函数。

**Q：asyncio 为什么适合高并发网络服务？**
A：一个连接对应一个轻量协程，单线程内可调度成千上万连接，内存占用远低于「一连接一线程」，且没有线程上下文切换成本。代价是不能并行做 CPU 密集计算。

**Q：gather 和 create_task 的区别？**
A：`gather` 用于「并发启动并等待一组协程的结果」；`create_task` 是把协程立即变为后台任务去调度，调用者可先干别的、之后再 `await` 它。gather 内部其实也是 `create_task` 把每个协程包成 Task。
