---
created: 2026-07-31
tags: [App自动化测试/专项测试]
---

# App 安装、卸载与升级测试

> 安装包装不上、覆盖升级后数据丢、卸载残留文件占空间——这些「边缘路径」出问题，用户第一反应是「这 App 垃圾」。升级测试尤其重要：大多数用户是从旧版本走过来的，不是每次都全新安装。

## 概念

### 三类安装场景

| 场景 | 命令/动作 | 验什么 |
|---|---|---|
| 全新安装 | `adb install app.apk` | 首装引导、权限申请、无旧数据 |
| 覆盖安装（升级） | `adb install -r app.apk` | 数据保留、DB 迁移、不闪退 |
| 降级安装 | `adb install -r -d app.apk` | 高版本数据能否兼容（`-d` 允许降级） |

### 升级测试的隐藏雷区

1. **数据库 Schema 迁移**：旧版 DB version 1，新版 version 2，`onUpgrade` 没写好，升级后打开就崩。
2. **SharedPreferences 字段变更**：旧版存的字段被新版逻辑误读。
3. **文件路径/格式变更**：旧版缓存的文件新版本解析不了。
4. **用户登录态保留**：升级后不该让用户重新登录（除非强制）。

## 用法

### 一、安装/卸载脚本化

```python
def install(adb, apk):
    adb.shell(f"install -r {apk}")        # -r 覆盖

def uninstall(adb, pkg):
    adb.shell(f"uninstall {pkg}")          # 连带清数据

def clear_data(adb, pkg):
    adb.shell(f"pm clear {pkg}")            # 不清包只清数据
```

### 二、覆盖升级用例（核心）

```python
def test_upgrade_keeps_data(adb, driver):
    # 1. 装旧版
    install(adb, "app_v1.0.apk")
    driver.launch_app()
    # 2. 旧版里产生数据（登录、收藏）
    login(driver); add_favorite(driver)
    old_token = get_login_token(driver)
    driver.terminate_app(PKG)
    # 3. 覆盖安装新版
    install(adb, "app_v2.0.apk")
    driver.launch_app()
    # 4. 断言数据保留、未强制重新登录
    assert is_logged_in(driver)
    assert old_token == get_login_token(driver)
    assert favorite_count(driver) > 0
```

### 三、降级安装（验证兼容）

```bash
# -d 允许降级安装，验证高版本数据在低版本能否不崩
adb install -r -d app_v1.0.apk
```

注意：降级通常需要旧包 `versionCode` 更低，且 `minSdk` 允许；很多 App 不允许降级，要和产品确认是否支持。

### 四、卸载残留检查

```python
def test_no_residue_after_uninstall(adb):
    install(adb, "app.apk")
    driver.launch_app(); do_something(driver)   # 产生缓存
    uninstall(adb, PKG)
    # 外部存储残留目录应被清（或明确归属）
    out = adb.shell("ls /sdcard/Android/data/")
    assert PKG not in out
```

### 五、安装失败场景覆盖

```text
应覆盖的安装异常：
  - 存储空间不足（用 adb 填满 /data 再装）
  - 包名冲突/签名不一致（用不同签名包覆盖装）
  - 低版本系统装高 minSdk 包（应友好提示而非闪退）
```

## 踩坑

1. **只测全新安装，漏了覆盖升级**：线上绝大多数用户是升级上来的，全新安装通过但升级崩溃的案例极多（DB 迁移漏写）。升级用例必须用「先装旧版跑数据→覆盖新版」的真实路径。
2. **`install -r` 被签名不一致拦截却没断言**：签名变了 `adb install -r` 直接失败，用例如果没检查返回值，后面 `launch_app` 跑的是旧版，假绿。安装命令要校验返回 `Success`。
3. **升级后登录态丢失被当成正常**：产品要求升级保留登录，但 `onUpgrade` 清了 token，用例没断言登录态，上线后用户全被踢出。登录态保留是升级核心断言。
4. **`pm clear` 在卸载测试里误用**：想卸干净却用 `pm clear` 只清数据不卸包，残留包还在。卸载要用 `uninstall`，清数据才用 `pm clear`，两者别混。
5. **外部存储残留没清理导致空间告警**：卸载后 `/sdcard/Android/data/包名` 没删，长期累积占空间。卸载残留要列入兼容性/专项检查。
6. **Android 11+ 分区存储让旧路径读不到**：旧版存到非 `scoped` 目录的文件，升级后新版按分区存储读不到，报文件丢失。升级要处理历史文件迁移。
7. **`install` 在模拟器上慢到超时**：模拟器安装比真机慢数倍，CI 里 `install` 超时设太短会假红。安装命令 timeout 单独放大。
8. **多 ABI 包安装到错误架构设备**：只打 arm64，装到 32 位老设备直接「INSTALL_FAILED_CPU_ABI_INCOMPATIBLE」。兼容性矩阵里的老设备要对 `armeabi-v7a`。
9. **降级安装没和产品确认是否支持**：很多 App 不支持降级，`install -d` 会失败，误报 bug。先确认降级策略再写用例。
10. **升级中断（装一半拔线/电量耗尽）后状态不可知**：半截安装可能留损坏数据。异常升级路径要测「中断后再装」能否恢复，而非只测顺利升级。

## 面试怎么答

**30 秒骨架**：安装卸载升级测试有三条主路径——全新安装、覆盖升级（`adb install -r`）、卸载。其中升级测试最关键也最易出问题，因为线上用户大多从旧版升上来，要验证 DB Schema 迁移、SharedPreferences、缓存文件、登录态这四样在覆盖安装后正确保留且不崩。脚本上要用「先装旧版产生数据→覆盖新版→断言数据/登录态保留」的真实路径，安装命令必须校验 `Success` 返回值。

**追问**：升级最该防什么？——DB 迁移漏写导致升级后打开闪退，以及登录态被清让用户重新登录，这两个是最高频的线上事故。

## 参考

- [Android adb install 文档](https://developer.android.com/studio/command-line/adb#move)
- 相关笔记：[[adb 常用命令详解]]、[[Appium 应用启停、重置与设备状态恢复]]、[[App 兼容性测试与云真机平台]]
