---
created: 2026-09-28
tags: [面试题/自动化测试框架]
---

# 自动化测试用例高频偶发失败（Flaky）的系统性治理

> Flaky Tests（飘忽不定的测试）是指在被测代码未经任何修改的情况下，多次重复执行时结果呈现非确定性（有时 PASS 有时 FAIL）的用例。治理 Flaky Tests 绝不能单纯依赖重试机制，必须从「根因分析分类 → 确定性重构 → 自动检测与隔离熔断 → 防劣化门禁」建立闭环。

## 30 秒回答骨架

- **Flaky 测试的危害**：腐蚀研发团队对自动化测试的信任（“反正这次挂了可能是网络抖动，再点一次构建”），导致构建堵塞，并在海量误报中掩盖真正的业务逻辑 Bug。
- **四大典型根因**：
  1. **异步时序与竞争（Async Timing）**：未等待元素处于 Interactable 状态、前端过渡动画未完成即点击、接口异步落库尚未提交；
  2. **测试数据污染与共享状态（Shared State）**：硬编码测试账号/ID、不同用例或 Worker 抢占同一资源、用例执行顺序依赖；
  3. **环境与基础设施抖动（Infra Instability）**：DNS 波动、第三方外联依赖超时、网关限流、浏览器驱动僵尸进程占用资源；
  4. **时间与时区边界（Time/Date Dependency）**：月底、跨年、夏令时或 `time.sleep` 假定固定等待耗时。
- **治理闭环体系**：
  - **切忌滥用 `pytest-rerunfailures`**（掩盖真问题，增加整体执行耗时）；
  - 建立 **Flaky 识别监控体系**（统计重试通过率、用例稳定性打分）；
  - **自动隔离舱机制（Quarantine）**：高频 Flaky 用例自动打标移出阻断性主门禁，进入观察队列；
  - **确定性重构**：全面替换 `sleep` 为显式轮询断言（Eventual Consistency / Polling Wait），保证测试数据动态生成与物理隔离。

## 展开

### 1. Flaky 治理体系四大阶段（四步闭环）

```text
               +-----------------------------+
               | 1. 检测与度量 (Detection)   |
               | - CI 重试后通过的用例打标    |
               | - 计算稳定性评分 (P/F 波动率)|
               +--------------+--------------+
                              | 达到 Flaky 阈值
                              v
               +-----------------------------+
               | 2. 隔离熔断 (Quarantine)    |
               | - 自动加上 @pytest.mark.flaky|
               | - 从阻断主卡点降级为通知队列|
               +--------------+--------------+
                              | 派发修复工单 (SLA 限期 3 天)
                              v
               +-----------------------------+
               | 3. 根因剖析与重构 (Refactor)|
               | - 确定性等待 (Smart Wait)   |
               | - 数据独立 (Isolated Data)  |
               | - 依赖解耦 (Mocking 外部)   |
               +--------------+--------------+
                              | 压测验证 (连续 50 次 PASS)
                              v
               +-----------------------------+
               | 4. 防劣化与恢复 (Gatekeeper)|
               | - 摘除隔离标记，回归主流水线 |
               | - 建立代码审查禁止 sleep    |
               +-----------------------------+
```

### 2. 核心根因与精准重构手段

#### ① 异步时序问题（Async & Animation）
- **错误写法**：
  ```python
  # 凭经验硬编码 sleep，机器卡顿时依然超时；机器快时白白浪费时间
  driver.find_element(By.ID, "submit_btn").click()
  time.sleep(3)
  assert driver.find_element(By.ID, "success_tips").text == "操作成功"
  ```
- **正确重构**：显式等待或者基于条件谓词的轮询
  ```python
  from selenium.webdriver.support.ui import WebDriverWait
  from selenium.webdriver.support import expected_conditions as EC

  # 1. 确保按钮可点击（无遮罩、动画结束）
  btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "submit_btn")))
  btn.click()

  # 2. 显式断言目标状态就绪
  WebDriverWait(driver, 10).until(
      EC.text_to_be_present_in_element((By.ID, "success_tips"), "操作成功")
  )
  ```
  *(注：若使用 Playwright，其内置 Auto-wait 会在 action 前自动校验 Attached、Visible、Stable、Receives Events，天然消除了 80% 的动画时序 Flaky)*

#### ② 接口异步处理（最终一致性轮询）
当发起转账/发货请求后，后台 MQ 异步消费并落库，如果接口请求后立即 `assert db.query_order_status() == "SUCCESS"`，必定高频偶发挂掉。
- **重构方案**：基于轮询重试库（如 `tenacity`）封装**最终一致性等待**：
  ```python
  from tenacity import retry, stop_after_delay, wait_fixed, retry_if_result

  @retry(stop=stop_after_delay(15), wait=wait_fixed(0.5), retry_if_result(lambda res: res != "SUCCESS"))
  def wait_for_order_success(order_id):
      return query_db_order_status(order_id)
  ```

#### ③ 运行顺序依赖与数据交叉污染
- 用例 A 创建了数据没清理，用例 B 假设数据库为空；或者用例 B 依赖用例 A 执行产生的全局变量。
- **检测工具**：使用 `pytest-randomly` 或 `pytest-reverse` 打乱用例执行顺序，强制暴露出隐式顺序依赖。
- **解法**：每条用例通过 UUID 动态生成数据前缀，在 fixture 的 `yield` 之后通过 `finally` 结构或上下文管理器强制清理。

### 3. 为什么滥用自动重试（Rerun）是饮鸩止渴？

很多团队安装 `pytest-rerunfailures` 并配置 `--reruns 3`：
- **隐藏真正的偶发缺陷**：例如高并发下的线程安全竞态、数据库死锁、MQ 丢消息；
- **拖垮流水线执行效率**：失败用例往往需要等待完整的超时时间（如 30 秒），重跑 3 次意味着单用例等待 90 秒，导致流水线严重阻塞；
- **雪崩效应**：若偶发失败是由服务端压力大或数据库连接池耗尽引起的，盲目重跑只会呈倍数放大系统负载，促成全盘失败。

## 可能被追问的点

- **如何通过数据化手段度量团队的用例稳定性？**
  - **Flaky 指标公式**：$Flaky\_Rate = \frac{构建中因重试而最终通过的用例数 + 隔离区用例数}{总用例数} \times 100\%$；
  - **流水线初次通过率（First-Run Pass Rate, FRPR）**：不计任何重试机制下的 CI 一次性成功率，健康的研发团队通常要求 FRPR $\ge 95\%$。
- **Playwright 与 Selenium 相比，在治理 Flaky 方面底层有哪些本质改进？**
  - Selenium 基于 HTTP 轮询检查元素，无法感知浏览器的渲染主循环（Render Pipeline）；
  - Playwright 直接通过 CDP（Chrome DevTools Protocol）与浏览器内核双向 WebSocket 通信，能够监听 DOM 变更、网络请求生命周期（NetworkIdle）以及 CSS 动画帧（RAF, requestAnimationFrame），在元素处于 Actionable 状态（Visible, Stable, Enabled, Not Covered）前自动等待，无需人工编写冗杂的显式等待。
- **对于三方不可控服务（如短信通道、微信支付）引发的 Flaky，怎么治理？**
  - 测试环境下必须建立 **Mock / Service Virtualization（服务虚拟化）** 体系（如使用 WireMock 或 Mountebank），用可控的桩服务隔绝外网不可靠依赖。

## 结合自己项目的例子

在持续交付流水线中，曾经有一套 950 多个 Web 端 E2E 自动化测试用例，每天跑 10 次以上，构建成功率只有 60% 左右。研发开始忽视测试报告：“流水线挂了不用管，重新触发一次就好”。

- **排查与量化**：
  1. 通过 ELK 汇总 2 周的 CI 执行日志，统计出 34 条贡献了 82% 偶发失败的“超级 Flaky 用例”；
  2. 剖析日志截图发现两大约束：① 弹窗 Modal 消失带有 300ms CSS 淡出过渡动画，代码中虽然元素已 disappear，但 DOM 的遮罩层（mask）尚未移除，导致下一点击击穿到遮罩上报 `ElementClickInterceptedException`；② 账单核销依赖 MQ 异步入账，存在 200ms~1.5s 波动。
- **整改策略**：
  1. **隔离机制**：将 34 条用例打标 `@pytest.mark.flaky_quarantine`，主流水线剔除其阻断权限，移至每小时单独的观察流水线；
  2. **时序重构**：编写统一的页面操作包装器（Safe Action API），点击前等待遮罩完全脱离文档树；对异步落库全面改用基于指数退避的轮询断言；
  3. **数据隔离**：消灭测试库共享账号，改用测试数据工厂实时创建带有时间戳+UUID 的隔离用户。
- **成效**：3 周内将 34 条用例全部重构并连续 50 次跑通，重新并入主流水线；流水线初次通过率（FRPR）由 61.2% 飙升至 **98.8%**，单次构建等待时间从 45 分钟下降至 18 分钟。

## 参考

- Google Testing Blog: *Flaky Tests at Google and How We Mitigate Them*
- Martin Fowler: *Erasing Non-Deterministic Tests*
- 相关笔记：[[05-自动化测试框架]]、[[显式等待与隐式等待的区别]]、[[Playwright 相比 Selenium 的底层架构差异与 CDP 优势]]
