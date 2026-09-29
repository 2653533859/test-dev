---
created: 2026-09-29
tags: [项目实战/App自动化测试]
---

# 智能 Monkey 稳定性压测与崩溃聚类分析

> 告别低效的原生盲目 Monkey 随机乱点：基于强化学习驱动的智能遍历工具 Fastbot + 崩溃堆栈特征指纹聚类算法，将移动端复杂链路深层崩溃捕获效率提升 400%。

## 概念

### 原生 Android Monkey 的三大硬伤

Google 原生的 Android Monkey 工具采用「完全随机事件注入」机制：

1. **盲目探索与状态陷入**：原生 Monkey 不感知当前页面有什么控件，经常无脑点击左上角「返回」或「退出登录」，在登录界面死循环几个小时，核心深层业务链路（如商品搜索、下单、商品详情）探索率极低；
2. **极易逃逸跳出应用**：随机点击极易触发右上角分享跳转到微信、唤起系统设置修改系统时间或进入电话拨号盘，导致测试中途失控；
3. **海量重复崩溃淹没排查精力**：一旦界面发生空指针异常，后续连续几十次点击都会反复触发同一个 Crash，产生数百份 logcat 文件，研发需要耗费数小时人工肉眼去重。

### Fastbot 智能遍历与聚类架构

字节跳动开源的 **Fastbot** 将强化学习（Q-Learning / 决策树模型）与 Android 原生 GUI 树结合：

```text
               当前界面 GUI 控件树 (Dump XML)
                         │
                         ▼
        ┌─────────────────────────────────┐
        │  Fastbot 智能决策引擎 (Agent)    │
        │  • 识别界面类型 (表单/列表/详情) │
        │  • 计算各控件探索奖励值 (Reward) │
        │  • 屏蔽黑名单 Activity/敏感词   │
        └────────────────┬────────────────┘
                         │ 下发加权智能动作 (点击/滑动/输入)
                         ▼
               触发异常崩溃 (Crash / ANR)
                         │
                         ▼
        ┌─────────────────────────────────┐
        │    崩溃指纹提取与聚类算法       │
        │  1. 截取前后 30s logcat 日志    │
        │  2. 正则提取首个业务堆栈包名     │
        │  3. 计算 MD5 指纹去重归因       │
        └─────────────────────────────────┘
```

---

## 用法

### 1. Fastbot 生产级运行配置与执行

通过向设备推入 `fastbot-thirdpart.jar` 与 `monkey.jar`，配置引导字符串与黑名单：

```bash
# 1. 将 Fastbot 引擎推入设备
adb push fastbot-thirdpart.jar /data/local/tmp/
adb push monkey.jar /data/local/tmp/

# 2. 配置黑名单 Activity（防止跳出或退出登录）
cat <<EOF > /tmp/awl.strings
com.mall.app.ui.setting.AccountLogoutActivity
com.mall.app.ui.pay.ThirdPartyPayActivity
EOF
adb push /tmp/awl.strings /sdcard/awl.strings

# 3. 执行智能 Monkey 巡检（运行 60 分钟，限制每秒事件数 3）
adb shell CLASSPATH=/data/local/tmp/monkey.jar:/data/local/tmp/fastbot-thirdpart.jar \
    exec app_process /data/local/tmp com.android.commands.monkey.Monkey \
    -p com.mall.app \
    --agent reuseq \
    --running-minutes 60 \
    --throttle 300 \
    --output-directory /sdcard/fastbot_output/ \
    -v -v
```

### 2. 崩溃自动聚合去重算法（Python）

从 logcat 中提炼出第一行业务代码堆栈，生成唯一 Issue 指纹：

```python
import hashlib
import re
from typing import Optional

# 匹配业务核心包名堆栈的正则
APP_STACK_PATTERN = re.compile(r"at (com\.mall\.[a-zA-Z0-9_$.]+)\(")


def extract_crash_fingerprint(logcat_text: str) -> Optional[dict]:
    """提取崩溃核心堆栈特征并计算唯一去重指纹"""
    lines = logcat_text.splitlines()
    exception_type = ""
    culprit_stack = ""

    for i, line in enumerate(lines):
        if "FATAL EXCEPTION:" in line:
            # 找到异常类型（如 java.lang.NullPointerException）
            if i + 1 < len(lines):
                exception_type = lines[i + 1].strip().split(":")[0]

        # 查找第一个属于本公司业务代码的堆栈行
        match = APP_STACK_PATTERN.search(line)
        if match and not culprit_stack:
            culprit_stack = match.group(1)

    if exception_type and culprit_stack:
        # 指纹特征：异常类型 + 罪魁祸首代码行
        raw_fingerprint = f"{exception_type}@{culprit_stack}"
        md5_sig = hashlib.md5(raw_fingerprint.encode("utf-8")).hexdigest()[:12]
        return {
            "signature": md5_sig,
            "exception_type": exception_type,
            "culprit": culprit_stack,
        }
    return None
```

---

## 踩坑

1. **输入框注入导致生产垃圾数据或账号被封禁**：
   - *案例*：Monkey 遇到输入框自动乱打字符，把 `111111` 提交成了测试账号的身份证号，或把评论区刷了成百上千条乱码废话。
   - *解法*：向 Fastbot 注入 `max.xpath.strings` 配置，针对 `EditText` 进行语义匹配，如果是搜索框输入「iPhone」，如果是手机号框输入测试白名单号码，严禁纯随机乱码。
2. **Logcat 缓存溢出导致崩溃上下文丢失**：
   - *案例*：App 崩溃发生后，由于后续系统日志输出过多，默认 256KB 的 logcat 环形缓冲区被快速冲刷，提取日志时只剩半截堆栈。
   - *解法*：测试启动前必须先扩大 logcat 缓冲区：`adb logcat -G 16M`，确保留存完整的崩溃调用链。

---

## 面试怎么答

**Q：你们的 App 稳定性测试（Monkey）是怎么做的？与原生 Monkey 有什么区别？如果产生大量崩溃如何去重？**
> 1. **技术选型升级**：我们淘汰了原生无脑随机的 Monkey，采用基于强化学习的 **Fastbot** 引擎。原生 Monkey 盲目乱点探索率低，而 Fastbot 能够解析控件树，通过模型奖励机制自适应探索未覆盖的深层 Activity，使崩溃发现效率提升 4 倍。
> 2. **定向约束与防逃逸**：配置白名单与黑名单 Activity，严禁测试跳出到第三方微信或进入敏感的「注销账号」界面；同时向特定输入框注入合规的业务字典数据，避免脏数据污染。
> 3. **智能崩溃聚类去重**：每次捕获到 Crash/ANR 时，自研算法会自动解析堆栈，提取「异常类名」与「首个包含公司包名的堆栈方法」生成 MD5 指纹进行 Group By 聚合。即便夜间触发了 500 次崩溃，平台最终只汇总为 3 个具体的 Bug 单发给对应开发，极大减轻了研发排障负担。

---

## 参考

- Fastbot 官方使用手册：`https://github.com/bytedance/Fastbot_Android/blob/main/HANDBOOK.md`
- 相关笔记：[[08-App自动化测试]]、[[adb logcat 日志抓取与崩溃定位]]、[[App UI 自动化稳定性治理]]
- 所属项目：[[移动端质量巡检与稳定性专项/移动端质量巡检与稳定性专项]]
