---
created: 2026-07-31
tags: [App自动化测试/adb]
---

# adb logcat 日志抓取与崩溃定位

> 「App 闪退了」不是一个合格的缺陷描述。带着 logcat 里那段 stack trace 提单，才是测试开发该有的产出。

## 概念

### logcat 是什么

Android 内核里维护着若干**环形缓冲区（ring buffer）**，App 和系统写日志进去，`logcat` 负责把它们读出来。

「环形」意味着**满了会覆盖最老的数据**。默认每个 buffer 只有 256KB 到几 MB，日志量大的 App 几十秒就转一圈。这解释了两个现象：

- 崩溃后过了几分钟才去抓日志，那段 stack trace 已经被冲掉了；
- 加大 buffer（`adb logcat -G 16M`）能显著提高抓取成功率。

### 五个 buffer

```bash
adb logcat -b main       # 默认，App 打的普通日志
adb logcat -b crash      # 崩溃专用，Java crash 会同时进这里 —— 排障首选
adb logcat -b system     # 系统框架日志
adb logcat -b events     # 结构化系统事件（am_proc_start、am_anr 等）
adb logcat -b radio      # 通信模块，测试很少用
adb logcat -b all        # 全部
```

**`-b crash` 是最该记住的那个**：它信噪比极高，崩溃时直接看这里，不用在 main 的海量日志里捞。

### 六个日志级别

```text
V (Verbose) < D (Debug) < I (Info) < W (Warn) < E (Error) < F (Fatal)
```

过滤语法是 `TAG:LEVEL`，`*:S` 表示其他 tag 全部静默（S = Silent）：

```bash
adb logcat AndroidRuntime:E *:S       # 只看 AndroidRuntime 的 Error 及以上
adb logcat *:E                        # 所有 tag 的 Error 及以上
```

### 三类「App 挂了」，日志特征完全不同

| 类型 | 表现 | 关键 tag / 关键字 |
|------|------|-----------------|
| **Java Crash** | 弹「应用已停止运行」 | `AndroidRuntime` + `FATAL EXCEPTION` |
| **Native Crash** | 直接闪退，可能无弹窗 | `DEBUG` + `*** *** ***` + `signal 11 (SIGSEGV)` |
| **ANR** | 卡死 5 秒后弹「无响应」 | `ActivityManager` + `ANR in` |

**这三类的定位路径完全不同**，先分清类型再往下查，是提高效率的关键。

## 用法

### 一、基础抓取

```bash
adb logcat -c                        # 清空缓冲区（跑用例前必做，避免混入历史日志）
adb logcat -G 16M                    # 加大缓冲区，防止关键日志被冲掉

adb logcat                           # 实时流式输出（Ctrl+C 停）
adb logcat -d                        # dump 当前缓冲区后立即退出 —— 脚本里必须用这个
adb logcat -d > log.txt              # 存文件

adb logcat -v time                   # 带时间戳
adb logcat -v threadtime             # 带时间 + PID + TID，最常用的格式
adb logcat -v threadtime -d -b crash > crash.txt
```

`-v threadtime` 输出格式：

```text
07-31 14:22:31.482  8123  8123 E AndroidRuntime: FATAL EXCEPTION: main
 └日期  └时间       └PID  └TID └级别 └TAG        └内容
```

### 二、只看某个 App 的日志

```bash
# 方法一：按 PID 过滤（最精确）
adb shell pidof com.demo.app                     # 拿到 PID
adb logcat --pid=$(adb shell pidof com.demo.app)

# 方法二：按 tag 过滤
adb logcat MyAppTag:D *:S

# 方法三：正则（logcat 自带 -e）
adb logcat -e "com.demo.app"

# 方法四：管道 grep（最灵活，但会丢掉多行 stack trace 的上下文）
adb logcat -d | grep -A 30 "FATAL EXCEPTION"     # -A 30 带出后 30 行堆栈
```

**注意方法四的陷阱**：崩溃堆栈是多行的，直接 `grep FATAL` 只会得到一行标题。一定要加 `-A`（after context）把堆栈带出来。

### 三、定位 Java Crash

```bash
adb logcat -d -b crash -v threadtime
```

典型输出：

```text
07-31 14:22:31.482  8123  8123 E AndroidRuntime: FATAL EXCEPTION: main
07-31 14:22:31.482  8123  8123 E AndroidRuntime: Process: com.demo.app, PID: 8123
07-31 14:22:31.482  8123  8123 E AndroidRuntime: java.lang.NullPointerException:
        Attempt to invoke virtual method 'java.lang.String com.demo.model.User.getName()'
        on a null object reference
07-31 14:22:31.482  8123  8123 E AndroidRuntime:  at com.demo.ui.ProfileActivity.onCreate(ProfileActivity.java:64)
07-31 14:22:31.482  8123  8123 E AndroidRuntime:  at android.app.Activity.performCreate(Activity.java:8051)
        ...
07-31 14:22:31.482  8123  8123 E AndroidRuntime: Caused by: java.io.IOException: 用户接口返回空
07-31 14:22:31.482  8123  8123 E AndroidRuntime:  at com.demo.net.UserApi.fetch(UserApi.java:31)
```

**阅读顺序**：

1. 第一行确认是 Java crash，`Process:` 确认是不是被测 App（不是的话你抓错进程了）；
2. 异常类型 + 消息，`NullPointerException` 已经指明了空的是 `User.getName()`；
3. **堆栈里第一个属于 App 包名的行**（`com.demo.ui.ProfileActivity.onCreate:64`）就是问题现场，上面那些 `android.app.*` 是框架栈；
4. **有 `Caused by:` 一定要看最后一个** —— 真正的根因在链条末端，前面的都是包装。

提缺陷时把「异常类型 + App 包名那一行 + 最后一个 Caused by」三样贴上，开发基本能直接定位。

### 四、定位 Native Crash

```bash
adb logcat -d -b crash | grep -A 40 "\*\*\* \*\*\*"
```

```text
*** *** *** *** *** *** *** *** *** *** *** *** ***
Build fingerprint: 'google/sdk_gphone64/…:13/…'
pid: 9011, tid: 9077, name: RenderThread  >>> com.demo.app <<<
signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0x0
backtrace:
      #00 pc 000000000004b1a0  /data/app/…/lib/arm64/libdemo.so (decode_frame+128)
      #01 pc 000000000004c2f4  /data/app/…/lib/arm64/libdemo.so (render+64)
```

| signal | 含义 | 常见原因 |
|--------|------|---------|
| SIGSEGV (11) | 非法内存访问 | 空指针、野指针、越界 |
| SIGABRT (6) | 主动 abort | C++ 未捕获异常、断言失败 |
| SIGBUS (7) | 内存对齐错误 | 少见 |

backtrace 里是内存地址，**测试拿到这些就够了**——把完整段落贴给开发，他们用 `ndk-stack` 配合符号表还原成源码行号：

```bash
adb logcat -d | ndk-stack -sym ./obj/local/arm64-v8a
```

### 五、定位 ANR

ANR（Application Not Responding）触发条件：主线程 5 秒没响应输入事件、BroadcastReceiver 10 秒没处理完、Service 20 秒没启动完。

```bash
# 1. 日志里确认发生了 ANR
adb logcat -d | grep -i "ANR in"
# ActivityManager: ANR in com.demo.app (com.demo.app/.ui.MainActivity)
# Reason: Input dispatching timed out

# 2. 关键证据在 traces 文件里（记录了 ANR 那一刻所有线程的堆栈）
adb shell ls /data/anr/
adb pull /data/anr/anr_2026-07-31-14-30-12-123 ./
# 部分设备是 /data/anr/traces.txt

# 3. 也可以主动抓当前所有线程堆栈（怀疑卡顿但还没到 ANR 时）
adb shell kill -3 $(adb shell pidof com.demo.app)   # SIGQUIT 触发 dump
adb pull /data/anr/
```

traces 里找 `"main" prio=5 tid=1` 那一段，看主线程卡在哪个方法上：

```text
"main" prio=5 tid=1 Native
  | state=S schedstat=( 0 0 0 ) …
  at java.net.SocketInputStream.socketRead0(Native method)     ← 主线程在做网络 IO
  at com.demo.net.SyncApi.blockingCall(SyncApi.java:88)
```

看到主线程在 `socketRead0`，结论就很清楚了：主线程做了同步网络请求。

### 六、在自动化里自动归档日志

```python
import subprocess
import datetime
from pathlib import Path


class LogCollector:
    def __init__(self, serial: str, out_dir: str = "logs"):
        self.prefix = ["adb", "-s", serial]
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)

    def clear(self) -> None:
        """用例开始前清空，保证抓到的日志只属于本条用例。"""
        subprocess.run(self.prefix + ["logcat", "-c"], timeout=10)
        subprocess.run(self.prefix + ["logcat", "-G", "16M"], timeout=10)

    def dump(self, case_name: str) -> dict[str, Path]:
        """用例失败时调用，把三类日志分别落盘。"""
        ts = datetime.datetime.now().strftime("%H%M%S")
        files = {}
        for name, args in {
            "crash": ["-b", "crash"],
            "main": ["-b", "main"],
        }.items():
            path = self.out / f"{case_name}_{ts}_{name}.log"
            # 必须带 -d，否则 logcat 不会退出，subprocess 永久阻塞
            r = subprocess.run(
                self.prefix + ["logcat", "-d", "-v", "threadtime"] + args,
                capture_output=True, text=True, timeout=60,
                encoding="utf-8", errors="ignore",
            )
            path.write_text(r.stdout, encoding="utf-8")
            files[name] = path
        return files

    def has_crash(self) -> bool:
        r = subprocess.run(
            self.prefix + ["logcat", "-d", "-b", "crash"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="ignore",
        )
        return "FATAL EXCEPTION" in r.stdout or "*** ***" in r.stdout
```

挂到 pytest 上：

```python
import pytest
import allure


@pytest.fixture(autouse=True)
def collect_log(request, log_collector):
    log_collector.clear()
    yield
    # 无论成败都检查有没有崩溃 —— 用例通过但 App 崩了也是缺陷
    if log_collector.has_crash():
        files = log_collector.dump(request.node.name)
        for name, path in files.items():
            allure.attach.file(str(path), name=f"logcat-{name}",
                               attachment_type=allure.attachment_type.TEXT)
        pytest.fail("用例执行期间检测到 App 崩溃，详见附件 logcat-crash")
```

**`has_crash()` 这个检查很值钱**：很多 App 崩溃后会自动重启回首页，用例断言可能照样通过，缺陷就这么漏过去了。把崩溃检测做成 `autouse` 的 fixture，等于给每条用例免费加了一个隐式断言。参考 [[pytest fixture 详解]] 里 autouse 的用法。

## 踩坑

1. **脚本里忘了 `-d`，subprocess 永久阻塞**
   `adb logcat` 不加 `-d` 是流式输出，永不返回。这是 CI 挂死的经典原因。**所有脚本里的 logcat 一律带 `-d` 并设 timeout。**

2. **崩溃日志被环形缓冲区冲掉**
   日志量大的 App 几十秒就转一圈。对策：用例前 `logcat -c` 清空、`logcat -G 16M` 扩容、失败后**立刻**抓取而不是等整轮跑完。

3. **只 grep 一行，丢了堆栈**
   `grep "FATAL EXCEPTION"` 只得到标题行。要 `grep -A 30` 或者直接 dump 整个 crash buffer 存档。

4. **抓错进程**
   多进程 App（主进程 + push 进程 + WebView 进程）PID 不同。用 `pidof` 时注意可能返回多个 PID；崩溃日志里认准 `Process:` 那一行。

5. **中文乱码 / UnicodeDecodeError**
   Windows 上 `subprocess` 默认用 GBK 解码，遇到 UTF-8 日志直接抛异常。必须显式 `encoding="utf-8", errors="ignore"`。

6. **release 包堆栈被混淆**
   ProGuard/R8 混淆后堆栈是 `a.b.c.d(Unknown Source)`。需要开发用对应版本的 `mapping.txt` 做 retrace。**提单时一定要写清 App 的版本号和构建号**，否则映射表都找不对。

7. **ANR 的 traces 文件权限**
   `/data/anr/` 在非 root 设备上可能读不了。替代方案是从 logcat 的 `ActivityManager` 日志里找 ANR 摘要，或者用 `adb bugreport` 打包（包含 ANR traces，但文件很大）。

8. **`logcat -c` 在部分设备上清不掉 crash buffer**
   有些 ROM 的 crash buffer 不响应 `-c`。用 `logcat -c -b all` 试试；仍不行就记录清空时刻的时间戳，抓取后按时间过滤。

9. **把 logcat 当成断言依据要谨慎**
   「日志里出现 ERROR 就判失败」听起来很美，实际上第三方 SDK 会打一堆无害的 ERROR。要做的话必须建立白名单，且只针对特定 tag。

10. **忘了区分「用例失败」和「App 崩溃」**
    两者要分别统计。用例失败可能是脚本问题、环境问题；App 崩溃一定是产品缺陷。混在一起看，会掩盖真实的质量信号。

## 面试怎么答

**Q：App 闪退了你怎么定位？**
A：先分类，三种情况处理路径不同。第一步 `adb logcat -d -b crash`，crash buffer 信噪比最高。如果看到 `FATAL EXCEPTION` 加 `AndroidRuntime`，是 Java 崩溃，往下找堆栈里**第一个带 App 包名的行**就是现场，如果有 `Caused by` 链要看最后一个才是根因。如果看到一排星号加 `signal 11 SIGSEGV`，是 Native 崩溃，backtrace 是内存地址，测试这边把整段贴给开发，他们用 ndk-stack 加符号表还原。如果是卡死几秒后弹「无响应」，那是 ANR，`grep "ANR in"` 确认，然后去 `/data/anr/` 拉 traces 文件，看 `"main"` 那个线程卡在什么方法上——十有八九是主线程做了 IO 或者锁等待。提单时把版本号、复现步骤、对应的日志段落一起给，别只写「闪退了」。

**Q：自动化用例里怎么捕获崩溃？**
A：做成 autouse 的 fixture。每条用例开始前 `logcat -c` 清空缓冲区并 `-G 16M` 扩容，结束后不管用例通过还是失败，都 dump 一次 crash buffer 检查有没有 `FATAL EXCEPTION`。这一步很关键——很多 App 崩溃后会自动重启回首页，如果用例正好在那之后做断言，可能照样通过，缺陷就漏了。检测到崩溃就把日志 attach 到 Allure 报告并主动 fail 掉用例。相当于给每条用例免费加了一个隐式断言。

**Q：logcat 的日志会丢吗？为什么？**
A：会。logcat 底层是环形缓冲区，默认每个 buffer 只有几百 KB 到几 MB，写满就覆盖最老的。日志量大的 App 几十秒就能转一圈，所以崩溃后隔几分钟再去抓，那段堆栈很可能已经没了。对策有三条：跑用例前 `logcat -c` 清干净，用 `logcat -G 16M` 把缓冲区调大，以及失败后立刻抓取而不是等整轮结束。长时间稳定性测试还可以起一个后台进程持续 `logcat -v threadtime > file` 落盘，用 logrotate 切分。

**Q：ANR 和 Crash 有什么区别？**
A：Crash 是进程异常终止，Java 层未捕获异常或 Native 层收到致命信号，进程直接没了。ANR 是进程还活着但主线程被阻塞太久，系统认为它失去响应了——具体阈值是输入事件 5 秒、广播 10 秒、Service 20 秒。从测试角度看，Crash 的证据在 logcat 的 crash buffer 里，ANR 的关键证据在 `/data/anr/` 的 traces 文件里，那里面有 ANR 发生那一刻所有线程的堆栈快照。ANR 的根因通常是主线程做了网络请求、数据库操作、大文件 IO，或者等一把被其他线程持有的锁。

## 参考

- [Android 开发者 · Logcat 命令行工具](https://developer.android.com/tools/logcat)
- [Android 开发者 · ANR 诊断](https://developer.android.com/topic/performance/vitals/anr)
- 相关笔记：[[adb 常用命令详解]]
- 相关笔记：[[App UI 自动化稳定性治理]]
- 相关笔记：[[pytest fixture 详解]]
- 相关笔记：[[08-App自动化测试]]
