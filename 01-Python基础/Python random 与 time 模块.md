---
created: 2026-07-31
tags: [Python基础/标准库]
---

# Python random 与 time 模块

![[assets/prng-seed.svg]]
*图示：`random` 是伪随机（Mersenne Twister）——同 `seed` 产生完全可复现序列，不可用于密码学；密码学安全用 `secrets`/`os.urandom`。*

> 造随机测试数据、制造可复现的脏数据、给请求加等待、给慢用例计时——这两个模块天天用。但“伪随机”“sleep 阻塞”“计时该用哪个时钟”都是原理问题，用错会埋坑。

## 概念

### 1. `random` 是伪随机（PRNG）

`random` 用的是 **Mersenne Twister** 这类**伪随机数生成器（PRNG）**：它内部维护一个状态，每次“随机”其实是按确定算法从状态算出下一个数，再更新状态。`seed(n)` 设定初始状态。

- **相同 seed → 相同序列**（完全确定、可复现）
- **不 seed → 用系统时间/熵源初始化**（每次不同）
- 因为算法确定，**可预测**：知道足够多输出能反推内部状态 → 所以**不是密码学安全**

生成 token/验证码/密码要用 `secrets` 模块（基于 OS 熵源的真随机）。

### 2. 常用 API 的语义

- `random()` → [0,1) 浮点
- `randint(a,b)` → [a,b] 闭区间整数；`randrange(start,stop,step)` → range 上随机取
- `choice(seq)` → 随机一个；`choices(seq, k=n)` → **有放回**抽 n 个（可重复）；`sample(seq, k=n)` → **无放回**抽 n 个（不重复）
- `shuffle(lst)` → 原地 Fisher-Yates 洗牌
- `uniform(a,b)` / `gauss(mu,sigma)`

### 3. `time` 模块：时钟与等待

- `time()` → Unix 时间戳（自 epoch 的秒数，浮点）
- `sleep(sec)` → **阻塞当前线程**指定秒数
- `perf_counter()` → **单调时钟**（只增不减，不受 NTP 校时/系统时间回拨影响），**计时首选**
- `time_ns()` → 纳秒级整数
- `timeit` 模块：多次运行小段代码，自动关 GC、取最优，测性能最稳

### 4. 为什么计时用 `perf_counter` 而非 `time()`

`time()` 返回“墙上时钟”，系统校时（NTP）会把时间往回拨或往前跳，导致两次 `time()` 差为负或异常。`perf_counter` 是硬件单调计数器，专为测量短时间间隔设计，不受校时影响。

## 用法

```python
import random, time, timeit

random.seed(42)                       # 固定种子，可复现
print(random.randint(1, 100))
print(random.sample(range(10), 3))    # 无放回，不重复

phone = "138" + "".join(random.choices("0123456789", k=8))  # 有放回

# 计时
t0 = time.perf_counter()
time.sleep(0.1)
print(time.perf_counter() - t0)

# 测性能
print(timeit.timeit("'-'.join(str(i) for i in range(100))", number=10000))
```

## 踩坑

- **`random` 非密码学安全**：token/验证码/密码绝不用 `random`，用 `secrets`（MT 状态可预测）。
- **不 seed 每次不同**：CI 造随机数据要可复现就固定 `seed`；但 fixture 若固定 seed 可能掩盖偶发问题，权衡使用。
- **`choices` 有放回、`sample` 无放回**：要“抽 n 个不重复”用 `sample`；`choices` 会重复。
- **`sleep` 阻塞**：会卡住线程；异步函数里用 `await asyncio.sleep`；pytest 里优先框架的显式等待而非裸 `sleep`。
- **计时用错时钟**：`time.time()` 受校时影响，计时用 `perf_counter()`。
- **`shuffle` 原地**：返回 `None`，别写 `lst = random.shuffle(lst)`。
- **GIL 下 `sleep(0)`**：会让出 GIL，不保证精确纳秒级。

## 面试怎么答

`random` 是 PRNG（如 Mersenne Twister）：seed 决定初始状态，同 seed 同序列（可复现），但状态可预测，**非密码学安全**——token 用 `secrets`。`choices` 有放回、`sample` 无放回、`shuffle` 原地。

`time.sleep` 阻塞线程；计时用 `perf_counter()`（单调时钟，不受 NTP 校时影响），不用 `time.time()`（可能被回拨）。测小段性能用 `timeit`（多次运行取最优、关 GC）。

## 参考

- random 文档：https://docs.python.org/zh-cn/3/library/random.html
- time 文档：https://docs.python.org/zh-cn/3/library/time.html
- 相关笔记：[[Python 并发编程]] [[Python 编码与 bytes、str]]
