---
created: 2026-07-31
tags: [Web自动化测试/稳定性治理]
---

# UI 测试脏数据清理与数据隔离

![[assets/dirty-data.svg]]
*图示：从左到右隔离性增强的三种策略，以及单用例的数据生命周期（setup 造数 → 执行产生脏数据 → teardown 清理 → 环境干净）。*

> 自动化用例跑多了，最怕两件事：一是脏数据互相串味导致用例时过时不过，二是清理不干净把测试环境搞脏。隔离和清理，是比「能不能跑通」更底层的问题。

## 概念

### 脏数据从哪来

UI 自动化本质是「通过界面真刀真枪地操作业务」：创建订单、注册账号、提交审批……每一步都会在数据库里留下记录。这些记录就是**脏数据**。它们带来的问题：

1. **串味（相互影响）**：用例 A 创建了一个叫 `test_order` 的单子，用例 B 假设库里没有这个单子，结果因为 A 没清而失败。
2. **状态污染**：用例 C 把账号改成「已封禁」，用例 D 默认账号是「正常」，D 跟着失败。
3. **环境脏污**：几百条用例跑完，测试库里堆了几千条垃圾数据，影响手工测试和系统性能。

### 隔离性 vs 成本的权衡

隔离程度越高越干净，但成本和复杂度也越高：

| 策略 | 隔离性 | 成本 | 适用 |
|------|:---:|:---:|------|
| 共用库 + 固定账号 | 最低 | 几乎为 0 | 本地 demo、探索性脚本 |
| 独立测试账号 / 命名空间 | 中 | 低 | 大多数团队 UI 自动化 |
| 即时重建（DB 快照 / 容器） | 最高 | 高 | 核心链路、CI 门禁 |

**没有银弹**。中小团队从「独立测试账号 + 命名前缀约定」起步就能解决 80% 的串味问题；金融、交易等核心链路才值得上「即时重建」。

### 清理的两条路线

- **偏前（预防性清理）**：用例**开头**先按业务主键删除「可能存在的残留数据」再创建。幂等、不怕 setup 失败、即使上次没清干净也能自愈。
- **偏后（清理性清理）**：用例**结尾** teardown 删掉自己造的数据。直观，但用例中途异常、teardown 没执行就会漏清。

经验法则：**重要数据用「偏前 + 偏后双保险」，且偏前为主**——因为偏前的幂等清理不依赖用例是否跑完。

## 用法

### 命名空间 / 前缀约定（最便宜的隔离）

```python
# 所有自动化造的数据统一前缀，便于识别和清理
AUTO_PREFIX = "AUTO_"

def make_order_no():
    import uuid
    return f"{AUTO_PREFIX}{uuid.uuid4().hex[:12]}"

# 清理脚本永远只动 AUTO_ 开头的数据，绝不误伤真实/手工数据
DELETE_ORDERS = "DELETE FROM orders WHERE order_no LIKE 'AUTO_%'"
```

**前缀约定的价值**：一是隔离，手工数据和自动数据一眼可分；二是兜底清理时可以「按前缀批量删」，不用担心误删。

### pytest fixture 的「偏前 + finalizer」模型

```python
import pytest

@pytest.fixture
def clean_order(driver):
    order_no = make_order_no()
    # 偏前：先确保没有同名残留（幂等，不依赖上次是否清干净）
    api_delete_order_if_exists(order_no)
    yield order_no          # 把 order_no 交给用例使用
    # finalizer：用例结束（无论成败）后清理
    try:
        api_delete_order_if_exists(order_no)
    except Exception as e:
        print(f"清理订单 {order_no} 失败: {e}")
```

`yield` 之后的代码就是 finalizer，**即使用例断言失败也会执行**，比 `try/finally` 更优雅。清理失败只 `print` 不抛——清理本身失败不该影响「用例已经失败」的结论，更不该让报告崩溃。

### 用 API 做清理，而不是 UI

```python
# ✗ 慢且脆：用 UI 一步步去删
driver.find_element(...).click()   # 进列表
driver.find_element(...).click()   # 点删除
driver.find_element(...).click()   # 确认

# ✓ 快且稳：直接调后端清理接口
def api_delete_order_if_exists(order_no):
    r = requests.delete(
        f"{API_BASE}/orders/{order_no}",
        headers={"Authorization": TOKEN},
    )
    return r.status_code in (200, 404)   # 404 表示本来就没数据，也算成功
```

**清理走 API 而非 UI** 有三重好处：快（省去一堆点击）、稳（不依赖页面结构）、不会引入二级脏数据（比如删的时候又弹个确认框）。这正是 [[Page Object 模式与分层设计]] 里「业务层可直接调 API 辅助」的思路。

### 事务回滚 / DB 快照（最彻底的隔离）

```python
# 方案 A：测试跑在事务里，结束直接回滚（适合能控连接的场景）
@pytest.fixture
def db_transaction():
    conn = get_connection()
    conn.begin()
    yield conn
    conn.rollback()        # 所有写操作原样撤销，零脏数据

# 方案 B：跑前从生产快照还原容器，跑后销毁（CI 常用）
# docker run --rm myapp-test-db:snapshot
```

事务回滚和容器重建是「最干净」的——它保证每条用例看到的环境完全一致，且零残留。代价是基础设施成本，通常只在 CI 门禁或核心链路用。

### Playwright 的 storage_state 复用登录态（避免重复造登录脏数据）

```python
# 登录态用 storage_state 文件持久化，所有用例复用，不重复走登录流程
def test_login_once_and_reuse():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        page = context.new_page()
        page.goto("/login")
        page.fill("#user", "AUTO_tester")
        page.fill("#pwd", "***")
        page.click("#submit")
        context.storage_state(path="state.json")   # 保存 cookie / localStorage

# 后续用例直接 load，省去重复登录产生的会话数据
context = browser.new_context(storage_state="state.json")
```

登录态复用既加速、又避免每条用例都「造一个会话」，是隔离登录脏数据的标准做法。详见 [[Playwright 安装与浏览器管理]]。

## 踩坑

1. **只做偏后清理，不做偏前**
   用例中途异常，teardown 未必执行（或被跳过），脏数据残留。下次跑「偏前再删一次」能自愈，所以重要数据要偏前为主。

2. **清理用 UI 点，结果清理本身也飘**
   UI 清理依赖页面结构，页面一改清理就挂。清理尽量走 API 或 DB 直接操作。

3. **清理失败抛异常，污染报告**
   清理失败（比如数据已被别人删了）不应让用例变红。清理逻辑用 try 包住，失败只记录。

4. **误删手工 / 真实数据**
   全表 `DELETE` 或 `TRUNCATE` 是灾难。一切清理必须带前缀 / 命名空间 / 明确条件，绝不通杀。

5. **多个用例共用同一条业务数据**
   比如都操作 `order_no = "test"`，并发跑时互相覆盖。每条用例用唯一主键（UUID），或者用事务隔离。

6. **本地能跑 CI 飘，因为环境没隔离**
   本地库只有你一个人跑，CI 上几十条用例并发，串味立刻暴露。隔离策略要在 CI 真正承压前就设计好。

7. **忘记清理「副作用」数据**
   创建一个订单，可能连带生成日志、消息队列消息、缓存。只删主表不够，要确认连带数据是否影响后续用例。

8. **storage_state 文件被并发写坏**
   多进程共用同一个 `state.json` 会互相覆盖。每个并行 worker 用独立的 state 文件，或统一在 session 级只生成一次。

## 面试怎么答

**Q：UI 自动化怎么处理测试产生的脏数据？**
A：核心是两件事——**隔离**和**清理**。隔离上，小团队用「独立测试账号 + 数据前缀约定」就能解决大部分串味问题，所有自动造的数据统一加 `AUTO_` 前缀，既能一眼区分手工数据，兜底清理时也能按前缀批量删而不误伤。核心链路才上代价更高的「即时重建」，比如事务回滚或容器从快照还原。清理上，我习惯 pytest fixture 的 `yield` 模型：用例开头先按业务主键幂等删一次残留（偏前、自愈），结尾 finalizer 再删一次（偏后、兜底），且**清理走 API 而不是 UI 点**——更快更稳，也不会引入二级脏数据。清理失败只记录不抛，不能影响用例本来的结论。

**Q：偏前清理和偏后清理你选哪个？**
A：重要数据以偏前为主、偏后为辅双保险。因为偏前的幂等删除不依赖用例是否跑完——即使上次 teardown 因异常没执行，这次开头也会把自己要用的数据清干净，能自愈。偏后清理直观但脆弱，用例中途崩了就可能漏清。所以我的原则是：能偏前就偏前，关键链路双保险。

**Q：为什么清理要走 API 而不是 UI？**
A：三个原因。一是快，省去一堆点击和等待；二是稳，不依赖页面 DOM 结构，前端一改 UI 清理就挂；三是干净，UI 删除常常带确认弹窗、二次跳转，反而可能制造二级脏数据或卡住。后端清理接口一步到位，且没有界面副作用。这在分层设计里也属于「业务层可直接调 API 辅助 UI 测试」的合理用法。

## 参考

- [pytest · Fixtures (teardown / finalizers)](https://docs.pytest.org/en/stable/how-to/fixtures.html)
- [Playwright · Authentication (storage_state)](https://playwright.dev/python/docs/auth)
- 相关笔记：[[Page Object 模式与分层设计]]
- 相关笔记：[[Playwright 安装与浏览器管理]]
- 相关笔记：[[UI 用例失败重跑与截图 trace]]
- 相关笔记：[[07-Web自动化测试]]
