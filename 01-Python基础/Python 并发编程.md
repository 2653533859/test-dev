---
created: 2026-07-31
tags: [Python基础/并发]
---

# Python 并发编程

![[assets/gil-timeline.svg]]
*图示：GIL 在 I/O 阻塞时释放、CPU 密集时不释放——多线程并发加速只发生在「等待空窗期」。*

![[assets/concurrency-decision-tree.svg]]
*图示：并发模型选型决策树——CPU 密集选多进程（绕过 GIL 真并行），I/O 密集按并发规模选多线程或协程。*

![[assets/concurrency-timing.svg]]
*图示：同一任务（3×「1u CPU + 2u I/O」）在四种模型下的时间线对比——多进程耗时最短（3u），多线程/协程居中（5u），串行最慢（9u）；纯 CPU 段在多线程与协程下均被串行化，加速只来自 I/O 重叠。*

## 概念：并发（concurrency）与并行（parallelism）不是一回事

先纠正一个最常见的误解：**并发 ≠ 并行**。

- **并发**是「多个任务在一段时间内都往前推进」，强调*结构*——你一个人同时盯着三个锅，时不时搅一下，每个锅都在进展，但同一瞬间你只动了一勺。
- **并行**是「多个任务在同一时刻同时执行」，强调*硬件*——三个人各守一个锅，真正同时操作。

Python 的并发模型之所以复杂，根本原因在于 **GIL（Global Interpreter Lock，全局解释器锁）**。

### GIL 到底是什么

CPython 的内存管理不是线程安全的。对象引用计数（`ob_refcnt`）是多个线程共享的热数据，如果两条线程同时 `INCREF`/`DECREF` 同一个对象，会出现竞态导致引用计数出错、对象被提前释放或泄漏，进而引发崩溃。

GIL 是一把**进程级互斥锁**，规定：**任意时刻只有一个线程能持有这把锁、从而执行 Python 字节码**。所以即使在多核 CPU 上，Python 多线程也无法让纯 Python 字节码真正并行执行。

```python
import sys
a = [1, 2, 3]
# a 这个 list 对象头部有 ob_refcnt
# 每多一个名字引用它，引用计数 +1
b = a
assert sys.getrefcount(a) - 1 == 1  # getrefcount 自己也会临时 +1
```

### 那多线程有什么用？—— I/O 等待时释放 GIL

关键点：**GIL 在「进入阻塞型 I/O」时会被释放**。

当线程调用 `read()`、`recv()`、`time.sleep()`、网络请求等会阻塞的操作时，CPython 会先释放 GIL，让别的线程有机会运行，等 I/O 完成、线程被唤醒后再重新去抢 GIL。

所以多线程的价值在于**「等 I/O 的空窗期」可以切换去干别的活**。对于 CPU 密集计算，线程切换反而因抢锁带来额外开销，**多线程毫无加速**。

### 三类并发模型如何选

| 模型 | 底层 | 适合 | 不适合 | 并行度 |
|------|------|------|--------|--------|
| `threading` 多线程 | OS 线程 + GIL | I/O 密集（网络、磁盘） | CPU 密集 | 并发，不并行 |
| `multiprocessing` 多进程 | 多进程（各自独立 GIL） | CPU 密集 | 大量小任务、需共享内存 | 真并行 |
| `asyncio` 协程 | 单线程事件循环 | 海量 I/O、高并发连接 | CPU 密集、阻塞调用 | 并发，不并行 |

记忆口诀：**算得多用进程，等得多用线程或协程；连接数爆炸用 asyncio。**

## 用法一：threading 多线程

```python
import threading
import time

def worker(n):
    # 这个函数的字节码在一个时刻只能被一个线程执行
    print(f"线程 {n} 开始")
    time.sleep(1)          # 阻塞 → 释放 GIL → 其他线程可运行
    print(f"线程 {n} 结束")

threads = []
for i in range(3):
    t = threading.Thread(target=worker, args=(i,))
    threads.append(t)
    t.start()              # start 只是让 OS 调度，并不保证立刻跑

for t in threads:
    t.join()               # 阻塞当前（主）线程，直到 t 结束
print("全部完成")
```

`join()` 是「等待」。如果不 `join`，主线程可能提前退出（但在脚本里主线程退出会带走整个进程，子线程会被强杀）。

### 共享状态与锁

多个线程改同一个可变对象，必须用 `Lock` 把「读—改—写」这段临界区保护起来，否则会丢更新（race condition）。

```python
import threading

counter = 0
lock = threading.Lock()

def inc():
    global counter
    for _ in range(100000):
        with lock:            # 等价于 lock.acquire() ... lock.release()
            counter += 1       # 这一行其实三步：LOAD→ADD→STORE

ts = [threading.Thread(target=inc) for _ in range(4)]
for t in ts: t.start()
for t in ts: t.join()
print(counter)           # 有锁 → 400000；去掉锁 → 远小于 400000
```

**为什么会出现丢更新**：`counter += 1` 在字节码层面是 `LOAD` 当前值、`+1`、`STORE` 回去。两个线程可能都 `LOAD` 到同一个旧值，各自 `+1` 后 `STORE`，结果只加了一次。锁保证了这三步原子化。

### 死锁：两个锁交叉获取

```python
import threading, time

a = threading.Lock()
b = threading.Lock()

def t1():
    with a:
        time.sleep(0.1)
        with b:               # 等 b，但 b 被 t2 拿着
            pass

def t2():
    with b:
        time.sleep(0.1)
        with a:               # 等 a，但 a 被 t1 拿着 → 死锁
            pass

threading.Thread(target=t1).start()
threading.Thread(target=t2).start()
```

**避免死锁**：所有线程按**固定顺序**获取锁（比如永远先 a 后 b），或使用 `lock.acquire(timeout=...)`，或用 `threading.RLock`（可重入锁，同一线程可重复 acquire）。

## 用法二：multiprocessing 多进程绕过 GIL

```python
import multiprocessing as mp

def square(x):
    return x * x

if __name__ == "__main__":       # Windows 上必须放在此保护下：子进程靠 import 主模块重建
    with mp.Pool(4) as pool:
        # map 把可迭代对象分批发给 4 个进程并行算，结果按序返回
        results = pool.map(square, range(10))
    print(results)              # [0, 1, 4, 9, 16, 25, 36, 49, 64, 81]
```

原理：`Pool` 启动 N 个**独立 Python 进程**（各有一份独立 GIL 和独立内存），把任务序列化（pickle）发给子进程，子进程算完再把结果 pickle 回来。

代价：
1. **进程间内存不共享**，通信要靠 `Queue`/`Pipe`/`Value`/`Array` 或 `Manager`，且数据必须可 pickle。
2. **进程创建开销大**，任务太小反而更慢。
3. Windows 下子进程通过「重新 import 主模块」启动，所以入口逻辑必须包在 `if __name__ == "__main__":` 里，否则会无限递归 spawn。

> 进程间共享可变状态：简单数值/数组可用 `mp.Value('i', 0)`、`mp.Array('d', 10)`（背后是共享内存）；复杂对象用 `mp.Manager().dict()`（但 Manager 走网络 socket 代理，慢）。

## 用法三：concurrent.futures —— 统一线程/进程接口

两种模型用同一套 API，切换成本极低：

```python
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import urllib.request

urls = ["https://example.com"] * 5

# I/O 密集 → 线程池
with ThreadPoolExecutor(max_workers=5) as ex:
    futures = [ex.submit(urllib.request.urlopen, u) for u in urls]
    for f in futures:
        print(len(f.result()))      # result() 阻塞直到该任务完成

# CPU 密集 → 把上面的 ThreadPoolExecutor 换成 ProcessPoolExecutor 即可
```

`submit()` 返回 `Future`，`result()` 取结果，`as_completed()` 可按完成顺序遍历，`map()` 用法同 `pool.map`。这是**日常最推荐的上手入口**，比裸 `threading`/`multiprocessing` 省心。

## 用法四：asyncio 协程（详见 [[Python asyncio 实战]]）

asyncio 是**单线程内的协作式多任务**：靠 `await` 主动让出控制权，事件循环在「等待点」切换协程。没有锁、没有线程切换开销，但**一旦某个协程里写了阻塞的同步调用（如 `time.sleep`、同步 `requests.get`），整个事件循环都会被卡住**——因为协作式调度依赖每个协程自觉让出。

```python
import asyncio

async def hello(n):
    await asyncio.sleep(1)     # 主动让出，事件循环去跑别的协程
    print(f"hello {n}")

async def main():
    # asyncio.gather 并发运行多个协程，总耗时≈最慢那个而非累加
    await asyncio.gather(*(hello(i) for i in range(3)))

asyncio.run(main())            # 创建事件循环并运行到 main 结束
```

## 踩坑

1. **CPU 密集用多线程 = 白忙**：多线程受 GIL 限制，计算型任务线程数越多可能越慢。正确做法是用 `multiprocessing` 或把热点用 C 扩展（释放 GIL 的 C 代码，如 NumPy）。
2. **I/O 密集却用多进程**：进程开销大、内存翻倍，连接数一多就扛不住；这种场景 `asyncio` 或线程池更合适。
3. **共享可变状态不加锁**：竞态导致数据错乱且「偶发、难复现」，是并发 bug 里最阴的一类。
4. **死锁**：多把锁交叉获取。用固定获取顺序或 `RLock` 规避。
5. **Windows 多进程忘记 `if __name__ == "__main__":`**：子进程 import 主模块会再次执行顶层代码，导致递归 spawn 崩溃。
6. **asyncio 里调用阻塞函数**：`time.sleep`/`requests` 会卡死整个循环，必须换 `asyncio.sleep`/`aiohttp`/`httpx.AsyncClient`。
7. **`queue.Queue` vs `asyncio.Queue` 用混**：线程间用 `queue.Queue`，协程间用 `asyncio.Queue`，二者不互通。
8. **守护线程 `daemon=True`**：主线程退出时守护线程会被强杀，未完成的写操作可能丢数据。

## 面试怎么答

**Q：Python 多线程为什么不能利用多核？**
A：因为 CPython 有 GIL——一把进程级锁，保证同一时刻只有一个线程执行 Python 字节码，避免引用计数等内存管理出现竞态。所以多线程在 CPU 密集场景无法并行，但在 I/O 阻塞时会释放 GIL，因此适合 I/O 并发。

**Q：什么时候用多进程、多线程、asyncio？**
A：CPU 密集（计算、编码、图像处理）用 `multiprocessing` 真并行；I/O 密集且逻辑简单用 `threading`/`ThreadPoolExecutor`；海量并发连接、高吞吐网络服务用 `asyncio`。还可用 `concurrent.futures` 统一接口。

**Q：GIL 会被去掉吗？**
A：很难。GIL 是 CPython 内存管理与大量 C 扩展（假设单线程语义）的基石。曾有过移除尝试（如 gilectomy、PEP 554 子解释器），但要么性能回退要么兼容崩坏。实际工程上用多进程或释放 GIL 的 C 扩展（NumPy、Cython with `nogil`）绕过，而不是等 GIL 消失。

**Q：什么是死锁？怎么避免？**
A：两个或以上线程各自持有锁、又互相等待对方释放，导致全员永久阻塞。避免：固定加锁顺序、使用可重入锁 `RLock`、加超时 `acquire(timeout=...)`、尽量缩小临界区。
