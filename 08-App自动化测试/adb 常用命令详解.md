---
created: 2026-07-31
tags: [App自动化测试/adb]
---

# adb 常用命令详解

![[assets/adb-dataflow.svg]]
*图示：adb 的三段式结构——命令行 Client 发给本机常驻的 Server（:5037），Server 再经 USB/Wi-Fi 转给设备内的 adbd 守护进程，由它代为执行 pm、am、dumpsys 等系统命令。*

> adb 是 App 测试的瑞士军刀。会不会用 adb，决定了你是「只能点点点的执行者」还是「能自己定位问题的测试开发」。

## 概念

### 三段式结构

**adb = Android Debug Bridge**，注意名字里的 Bridge——它是一座桥，不是一个工具：

| 角色 | 位置 | 生命周期 |
|------|------|---------|
| **Client** | PC，你敲的每条 `adb xxx` | 发完命令即退出 |
| **Server** | PC，后台常驻单例，监听 `127.0.0.1:5037` | 首次执行 adb 时自动启动 |
| **Daemon (adbd)** | 设备内 | 随「USB 调试」开关启停 |

理解这个结构能解释两件事：

1. **为什么设备状态诡异时 `adb kill-server` 常常有效**——它重置的是中间那个 Server，设备列表、连接状态都会重建。
2. **为什么多个 adb 版本会打架**——它们都想占 5037 端口，版本不同会互相踢掉对方的 Server，报 `adb server version doesn't match this client`。

### 一个关键区分：adb 命令 vs shell 命令

```bash
adb install app.apk          # install 是 adb 自己的子命令
adb shell pm list packages   # pm 是 Android 系统的命令，adb 只是帮你在设备里执行它
```

`adb shell` 后面跟的 `pm` / `am` / `dumpsys` / `input` / `settings` 都是 **Android 系统自带的可执行程序**，参数要查 AOSP 文档而不是 adb 文档。这个区分能解释为什么「同样的 adb 命令在不同 Android 版本上行为不同」——变的是系统命令，不是 adb。

## 用法

### 一、设备连接与管理

```bash
adb devices -l                       # -l 显示型号，多设备时便于辨认
# emulator-5554  device product:sdk_gphone64_x86_64 model:sdk_gphone64_x86_64
# R5CT30XXXXX    device product:a52qnaxx model:SM_A525F

adb -s R5CT30XXXXX shell             # 多设备必须用 -s 指定
adb kill-server && adb start-server  # 状态异常时的万能第一招

adb tcpip 5555                       # 切到无线调试（先用 USB 连一次）
adb connect 192.168.1.20:5555
adb disconnect 192.168.1.20:5555

adb wait-for-device                  # 脚本里等设备就绪，避免竞态
adb root                             # 仅 userdebug/eng 版本或已 root 设备可用
adb remount                          # 重挂载 /system 为可写
```

设备状态三种异常：

| 状态 | 含义 | 处理 |
|------|------|------|
| `unauthorized` | 手机上没点授权 | 看手机屏幕点「允许」并勾「一律允许」 |
| `offline` | adbd 失联 | 重插线 / `kill-server` / 重启手机 |
| 列表为空 | 驱动、数据线、端口问题 | 换线换口，Windows 装驱动 |

### 二、应用管理（install / uninstall / pm）

```bash
adb install app.apk
adb install -r app.apk               # -r 保留数据覆盖安装（升级测试必用）
adb install -d app.apk               # -d 允许降级安装（版本回退测试）
adb install -g app.apk               # -g 安装时授予全部运行时权限（自动化省事）
adb install -t app.apk               # -t 允许安装 test-only 包
adb install-multiple base.apk split_config.apk   # 安装 AAB 拆分出的多个 apk

adb uninstall com.demo.app
adb uninstall -k com.demo.app        # -k 卸载但保留数据与缓存目录

# 包查询
adb shell pm list packages | grep demo             # 列出所有包
adb shell pm list packages -3                      # 只看第三方应用
adb shell pm list packages -f com.demo.app         # 连带显示 apk 路径
adb shell pm path com.demo.app                     # 单独查 apk 路径
adb shell dumpsys package com.demo.app | grep versionName   # 查版本号

# 数据清理与权限
adb shell pm clear com.demo.app                    # 清数据 = 恢复到刚安装状态
adb shell pm grant com.demo.app android.permission.CAMERA
adb shell pm revoke com.demo.app android.permission.ACCESS_FINE_LOCATION
adb shell pm reset-permissions                     # 重置全部权限（复现首次授权流程）
```

**`pm clear` 是 App 自动化里最重要的一条命令之一**：它比重装快得多，能把 App 恢复到「刚装完、没登录、没缓存」的状态，是用例间隔离的首选手段。

### 三、Activity 管理（am）

```bash
# 启动应用（两种写法）
adb shell am start -n com.demo.app/.ui.MainActivity
adb shell monkey -p com.demo.app -c android.intent.category.LAUNCHER 1   # 不知道入口 Activity 时

# 带参数启动（深链接测试）
adb shell am start -a android.intent.action.VIEW -d "demoapp://order/12345"

# 带 -W 会打印启动耗时，这是启动性能测试的数据来源
adb shell am start -W -n com.demo.app/.ui.MainActivity
# ThisTime: 486
# TotalTime: 486
# WaitTime: 512

adb shell am force-stop com.demo.app       # 强杀（模拟用户手动清后台）
adb shell am kill com.demo.app             # 温和杀，只杀后台进程

adb shell am broadcast -a com.demo.ACTION_TEST --es key value   # 发广播

# 查当前处于前台的 Activity —— 找 appActivity 的标准姿势
adb shell dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'
adb shell dumpsys activity activities | grep mResumedActivity
```

### 四、文件传输

```bash
adb push ./testdata.json /sdcard/Download/     # PC → 设备
adb pull /sdcard/ui.xml ./                     # 设备 → PC
adb pull /sdcard/Pictures/                     # 拉整个目录

# 应用私有目录默认不可读，除非 root 或用 run-as（debug 包）
adb shell run-as com.demo.app cat /data/data/com.demo.app/shared_prefs/config.xml
```

### 五、UI 交互与取证

```bash
# 模拟输入
adb shell input tap 540 1200                     # 点击坐标
adb shell input swipe 540 1600 540 600 300       # 滑动：起点 终点 耗时ms
adb shell input swipe 540 1200 540 1200 1500     # 起终点相同 + 长耗时 = 长按
adb shell input text "hello"                     # 输入文本（不支持中文，见踩坑）
adb shell input keyevent 4                       # 返回键
adb shell input keyevent 3                       # HOME
adb shell input keyevent 26                      # 电源键
adb shell input keyevent 82                      # MENU
adb shell input keyevent 66                      # 回车/搜索

# 截图与录屏
adb shell screencap -p /sdcard/s.png && adb pull /sdcard/s.png
adb exec-out screencap -p > s.png                # 一步到位，不落设备磁盘
adb shell screenrecord --time-limit 30 /sdcard/r.mp4
adb shell screenrecord --bit-rate 4000000 --size 720x1280 /sdcard/r.mp4

# 控件树
adb shell uiautomator dump /sdcard/ui.xml && adb pull /sdcard/ui.xml
```

### 六、系统信息与性能数据

```bash
adb shell getprop ro.build.version.release     # Android 版本
adb shell getprop ro.product.model             # 机型
adb shell wm size                              # 屏幕分辨率
adb shell wm density                           # 屏幕密度

# 性能采集，详见 App 性能指标采集那篇
adb shell dumpsys meminfo com.demo.app | grep TOTAL
adb shell dumpsys gfxinfo com.demo.app framestats
adb shell dumpsys battery
adb shell top -n 1 -p $(adb shell pidof com.demo.app)

# 网络
adb shell svc data disable                     # 关移动数据（弱网测试）
adb shell svc wifi enable
adb shell ping -c 4 www.example.com

# 关闭动画（自动化稳定性必做）
adb shell settings put global window_animation_scale 0
adb shell settings put global transition_animation_scale 0
adb shell settings put global animator_duration_scale 0
```

### 七、端口转发

```bash
adb forward tcp:8200 tcp:6790       # PC:8200 → 设备:6790（Appium 就靠这个）
adb forward --list
adb forward --remove-all

adb reverse tcp:8080 tcp:8080       # 反向：设备访问自己的 8080 = PC 的 8080
                                    # 用途：让手机访问你本机起的 mock server
```

**`adb reverse` 在接口 Mock 联调时特别有用**：本机起了 mock 服务，手机不用改 host、不用配代理，直接访问 `127.0.0.1:8080` 就能打到 PC 上。

### 八、封装成 Python 工具类

```python
import subprocess
import shlex


class Adb:
    def __init__(self, serial: str | None = None):
        self.prefix = ["adb"] + (["-s", serial] if serial else [])

    def run(self, cmd: str, timeout: int = 30) -> str:
        """执行 adb 子命令，返回 stdout。"""
        # 不用 shell=True，避免命令注入；参数用 shlex 切分
        full = self.prefix + shlex.split(cmd)
        r = subprocess.run(full, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="ignore")
        if r.returncode != 0:
            raise RuntimeError(f"adb 失败: {' '.join(full)}\n{r.stderr}")
        return r.stdout.strip()

    def shell(self, cmd: str, timeout: int = 30) -> str:
        return self.run(f"shell {cmd}", timeout)

    def current_activity(self) -> str:
        out = self.shell("dumpsys window")
        for line in out.splitlines():
            if "mCurrentFocus" in line:
                return line.strip()
        return ""

    def clear_app(self, pkg: str) -> None:
        self.shell(f"pm clear {pkg}")

    def disable_animation(self) -> None:
        for k in ("window_animation_scale",
                  "transition_animation_scale",
                  "animator_duration_scale"):
            self.shell(f"settings put global {k} 0")

    @staticmethod
    def devices() -> list[str]:
        out = subprocess.run(["adb", "devices"], capture_output=True,
                             text=True).stdout
        return [l.split()[0] for l in out.splitlines()[1:]
                if l.strip() and l.endswith("device")]


adb = Adb(serial="emulator-5554")
adb.disable_animation()
adb.clear_app("com.demo.app")
print(adb.current_activity())
```

用 `subprocess` 时**不要拼字符串加 `shell=True`**，包名如果来自外部输入会有命令注入风险，参考 [[Python subprocess 调用外部命令]]。

## 踩坑

1. **`adb shell input text` 不支持中文**
   直接输中文会变成空白或乱码。三种解法：换用 Appium 的 `send_keys`（走 UiAutomator2，支持 Unicode）；装 ADBKeyboard 输入法用广播发中文；capabilities 里加 `unicodeKeyboard: true`。详见 [[Appium 键盘输入与中文输入问题]]。

2. **多设备不加 `-s` 报 `more than one device/emulator`**
   写脚本时**永远显式带 `-s`**，别依赖「反正只连了一台」。CI 上插着好几台设备是常态。

3. **`adb server version doesn't match this client`**
   机器上有多个 adb（Android Studio 一个、单装一个、手机助手偷装一个）。统一到 SDK 那个，其余从 PATH 移除，然后 `adb kill-server`。

4. **`adb shell` 输出带 `\r\n`，Python 里比较字符串失败**
   Android shell 输出行尾是 CRLF。`out.strip()` 只处理首尾，中间行要 `out.replace("\r", "")` 或按行 strip。这个坑会导致 `assert version == "1.2.3"` 莫名失败。

5. **`pm clear` 会清掉登录态**
   它相当于「应用信息 → 清除数据」，Token、cookie、引导页标记全没了。做「已登录用户」的用例要么改用 `force-stop`，要么在 fixture 里重新登录，要么用 `noReset: true`。

6. **`adb pull` 应用私有目录权限不足**
   `/data/data/xxx` 普通权限读不了。debug 包可以用 `run-as`；release 包只能 root 或让开发把数据导到 `/sdcard/`。

7. **`screenrecord` 有 3 分钟上限且不录音**
   超过会自动停。长流程录制要分段。另外它在部分模拟器上不可用。

8. **`adb connect` 无线调试断连频繁**
   手机休眠、切 WiFi、IP 变化都会断。CI 上不要依赖无线 adb，用 USB。真要用就加重连逻辑。

9. **`settings put global` 改的是全局设置，跑完要还原**
   把动画关了不还原，用真机的人会觉得手机「变得很生硬」。规范做法是在测试套件的 teardown 里恢复成 `1`。

10. **`adb root` 在正式版设备上不可用**
    报 `adbd cannot run as root in production builds`。别在脚本里假设有 root，那样只能在特定设备上跑。

11. **命令超时挂死**
    `adb logcat` 不带 `-d` 会一直流式输出，`subprocess.run` 不设 `timeout` 就永久阻塞。**所有 adb 调用都要设超时。**

## 面试怎么答

**Q：adb 的工作原理是什么？**
A：三段式。你在命令行敲的 `adb xxx` 是 Client，它连本机 5037 端口上的 adb Server；Server 是一个后台常驻的单例进程，负责维护设备列表和多路复用；Server 再通过 USB 或 TCP 把命令发给设备里的 adbd 守护进程，由 adbd 在设备上实际执行。开发者选项里的「USB 调试」开关，控制的就是 adbd 起不起。理解这个结构的实际价值是排障——设备状态诡异先 `adb kill-server` 重置中间层；`adb server version doesn't match` 就是机器上有多个 adb 抢 5037 端口。

**Q：日常测试你最常用哪些 adb 命令？**
A：按场景分几类。装包用 `install -r` 做覆盖升级、`install -g` 直接授全部权限省掉弹窗。用例隔离用 `pm clear` 把 App 清回刚装完的状态，比重装快。定位问题用 `logcat -b crash` 抓崩溃、`dumpsys window | grep mCurrentFocus` 看当前在哪个页面。性能采集用 `am start -W` 量启动耗时、`dumpsys meminfo` 看内存、`dumpsys gfxinfo` 看掉帧。稳定性上跑用例前一定会 `settings put global window_animation_scale 0` 把三个动画缩放关掉，这一条能显著降低 flaky。

**Q：`adb shell pm clear` 和 `am force-stop` 有什么区别？**
A：`force-stop` 只是强制结束进程，相当于用户在最近任务里划掉它，数据、缓存、登录态都还在，下次打开还是登录状态。`pm clear` 是清除应用数据，等价于设置里点「清除数据」，会把 `/data/data/包名` 下的所有内容删掉，包括 SharedPreferences、数据库、缓存，App 回到刚安装的状态，会重新走引导页和登录。所以做「首次启动」「注册流程」用例要用 `pm clear`，做「已登录用户」的功能用例用 `force-stop` 就够，用 `pm clear` 反而要多花时间重新登录。

**Q：怎么在自动化里做设备状态的初始化？**
A：我一般在会话级 fixture 里做一次全局初始化：关三个动画、解锁屏幕、设置屏幕常亮、关掉自动旋转、确认网络状态；在用例级 fixture 里做隔离：`force-stop` 加按需 `pm clear`，然后重新拉起 App 到首页。跑完在 teardown 里把改过的系统设置还原回去。所有这些都封装在一个 `Adb` 工具类里，用 `subprocess` 调用并且都带超时——不带超时的 adb 调用会在设备失联时把整个 CI 挂死。

## 参考

- [Android 开发者 · adb 命令参考](https://developer.android.com/tools/adb)
- [Android 开发者 · dumpsys](https://developer.android.com/tools/dumpsys)
- 相关笔记：[[adb logcat 日志抓取与崩溃定位]]
- 相关笔记：[[App 性能指标采集：FPS、内存、CPU、流量与耗电]]
- 相关笔记：[[Python subprocess 调用外部命令]]
- 相关笔记：[[08-App自动化测试]]
