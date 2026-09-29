---
created: 2026-07-31
tags: [Web自动化测试/交互]
---

# Selenium 文件上传与下载

> 上传的核心认知是「不要点那个按钮」，下载的核心认知是「浏览器下载不在 DOM 里，得靠文件系统验证」。这两件事都有标准解法。

## 概念

### 上传：为什么不能点「选择文件」按钮

点击 `<input type="file">` 会唤起**操作系统级的文件选择对话框**。它不是网页元素，WebDriver 完全控制不了它——DOM 里没有，CDP 里也拿不到。

很多人的第一反应是用 pywinauto、AutoIt、pyautogui 去操作这个系统对话框。**这是错误方向**：平台相关（Windows 脚本在 Linux CI 上跑不了）、无头模式下压根没有对话框、依赖屏幕坐标极不稳定。

正确解法：**直接对 `<input type="file">` 元素 `send_keys(文件绝对路径)`**。

WebDriver 规范对 file input 的 `send_keys` 做了特殊处理——它不是模拟键盘输入，而是**直接把文件路径设置进元素的 files 列表并派发 `change` 事件**，效果等价于用户在对话框里选了文件，且完全不需要弹出对话框。

### 下载：验证的是文件系统不是页面

点击下载链接后，文件由浏览器进程写到磁盘。测试要验证的是：

1. 文件**下载完成**（不是 `.crdownload` 临时文件）；
2. 文件**名字对**；
3. 文件**内容对**（大小、行数、关键字段）。

这些都发生在浏览器之外，所以需要：**指定一个可控的下载目录 → 触发下载 → 轮询等待文件出现且完整 → 解析校验**。

## 用法

### 上传：标准写法

```python
import os
from selenium.webdriver.common.by import By

file_path = os.path.abspath("testdata/发票.pdf")     # 必须是绝对路径

upload_input = driver.find_element(By.CSS_SELECTOR, "input[type='file']")
upload_input.send_keys(file_path)                     # 不要 click！

# 等待上传完成的信号（进度条消失 / 文件名出现 / 接口返回）
wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".upload-item-done")))
```

### 上传：input 被隐藏时

组件库常把真正的 input 用 `display:none` 或 `opacity:0` 藏起来，只显示一个漂亮的按钮。`send_keys` 到隐藏元素可能抛 `ElementNotInteractableException`。

**注意：这种情况下用 JS 把它显示出来是合理的**——因为我们不是要「模拟用户点击这个隐藏元素」，只是要给它塞个值：

```python
driver.execute_script(
    "arguments[0].style.display='block';"
    "arguments[0].style.opacity=1;"
    "arguments[0].style.visibility='visible';"
    "arguments[0].style.width='200px';"
    "arguments[0].style.height='40px';",
    upload_input,
)
upload_input.send_keys(file_path)
```

比起用系统级工具点对话框，这个方案跨平台、无头可用、稳定。

### 上传：多文件

```python
# input 带 multiple 属性时，用换行符分隔多个路径
paths = "\n".join([os.path.abspath(p) for p in ["a.png", "b.png", "c.png"]])
upload_input.send_keys(paths)
```

没有 `multiple` 属性时传多个路径会报错。

### 上传：拖拽上传区域

很多组件只提供拖拽区域，DOM 里仍然有隐藏的 file input——**先在 DevTools 里找**，找到就用 `send_keys`。确实没有的话，需要用 JS 构造 `DataTransfer` 派发 drop 事件：

```python
JS_DROP_FILE = """
var target = arguments[0], offsetX = arguments[1], offsetY = arguments[2],
    document = target.ownerDocument || document, window = document.defaultView;
var input = document.createElement('INPUT');
input.type = 'file';
input.style.display = 'none';
input.onchange = function () {
  var rect = target.getBoundingClientRect(),
      x = rect.left + (offsetX || (rect.width >> 1)),
      y = rect.top + (offsetY || (rect.height >> 1)),
      dataTransfer = { files: this.files, types: ['Files'] };
  ['dragenter', 'dragover', 'drop'].forEach(function (name) {
    var evt = document.createEvent('MouseEvent');
    evt.initMouseEvent(name, !0, !0, window, 0, 0, 0, x, y, !1, !1, !1, !1, 0, null);
    evt.dataTransfer = dataTransfer;
    target.dispatchEvent(evt);
  });
  setTimeout(function () { document.body.removeChild(input); }, 25);
};
document.body.appendChild(input);
return input;
"""

drop_zone = driver.find_element(By.CSS_SELECTOR, ".upload-dragger")
tmp_input = driver.execute_script(JS_DROP_FILE, drop_zone, 0, 0)
tmp_input.send_keys(os.path.abspath("testdata/发票.pdf"))
```

思路是：临时造一个真的 file input，用 `send_keys` 给它塞文件，再用它的 files 构造 `DataTransfer` 派发到拖拽区。

### 上传：Playwright 的做法

Playwright 提供了专门 API，比 Selenium 干净：

```python
page.set_input_files("input[type='file']", "testdata/发票.pdf")
page.set_input_files("input[type='file']", ["a.png", "b.png"])       # 多文件
page.set_input_files("input[type='file']", [])                        # 清空已选

# 甚至可以不用真实文件，直接构造内存文件
page.set_input_files("input[type='file']", {
    "name": "test.csv",
    "mimeType": "text/csv",
    "buffer": b"id,name\n1,foo\n",
})

# 隐藏 input 也能直接用（Playwright 对 set_input_files 不做可见性检查）
# 点击触发型：用 expect_file_chooser 捕获
with page.expect_file_chooser() as fc:
    page.get_by_role("button", name="上传").click()
fc.value.set_files("testdata/发票.pdf")
```

**内存文件那种写法在造测试数据时非常有用**——不用在仓库里堆一堆测试文件，也不用担心路径问题。

### 下载：配置下载目录

```python
import os
import tempfile
from selenium import webdriver

download_dir = tempfile.mkdtemp(prefix="dl_")      # 每条用例独立目录，避免互相干扰

opts = webdriver.ChromeOptions()
opts.add_experimental_option("prefs", {
    "download.default_directory": download_dir,
    "download.prompt_for_download": False,      # 不弹"另存为"对话框
    "download.directory_upgrade": True,
    "safebrowsing.enabled": True,               # 避免"此文件可能有害"拦截
    "plugins.always_open_pdf_externally": True, # PDF 直接下载而不是在浏览器里预览
})
driver = webdriver.Chrome(options=opts)
```

**用临时目录而不是固定目录**：并行执行时多个用例往同一个目录下载，文件会互相干扰（尤其同名文件会被加 `(1)` 后缀，断言就断不准了）。

无头模式下旧版 Chrome 会禁用下载，需要额外用 CDP 打开：

```python
driver.execute_cdp_cmd("Page.setDownloadBehavior", {
    "behavior": "allow",
    "downloadPath": download_dir,
})
```

### 下载：等待完成并校验

```python
import time
from pathlib import Path

def wait_for_download(directory: str, timeout: int = 30, suffix: str = ".xlsx") -> Path:
    """等待下载完成：出现目标后缀文件，且没有 .crdownload 临时文件残留。"""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        files = list(Path(directory).glob(f"*{suffix}"))
        partial = list(Path(directory).glob("*.crdownload"))    # Chrome 的临时文件
        if files and not partial:
            newest = max(files, key=lambda p: p.stat().st_mtime)
            size1 = newest.stat().st_size
            time.sleep(0.5)
            if newest.stat().st_size == size1 and size1 > 0:     # 文件大小稳定 = 写完了
                return newest
        time.sleep(0.5)
    raise TimeoutError(f"{timeout}s 内未在 {directory} 检测到完成的 {suffix} 文件")

# 使用
driver.find_element(By.CSS_SELECTOR, "[data-testid='export-btn']").click()
f = wait_for_download(download_dir, suffix=".xlsx")

assert f.name.startswith("订单导出_")
assert f.stat().st_size > 1024          # 不是空文件

# 内容校验
import openpyxl
wb = openpyxl.load_workbook(f)
ws = wb.active
assert ws.cell(1, 1).value == "订单号"
assert ws.max_row == 11                  # 表头 + 10 条数据
```

**双重判定（无 `.crdownload` + 大小稳定）很有必要**：某些情况下临时文件已消失但写入还没 flush 完，直接读会拿到不完整内容。

Firefox 的临时文件后缀是 `.part`，跨浏览器时两个都要判。

### 下载：Playwright 的做法

Playwright 有一等公民的 download 事件，**完全不需要轮询文件系统**：

```python
with page.expect_download() as dl_info:
    page.get_by_role("button", name="导出").click()
download = dl_info.value

print(download.suggested_filename)       # 服务端建议的文件名
path = download.path()                    # 阻塞直到下载完成，返回临时文件路径
download.save_as("output/订单导出.xlsx")   # 另存到指定位置
# download.failure() 可拿到失败原因
```

`download.path()` 内部就包含了「等待完成」的语义，这是 Playwright 事件驱动架构的又一个体现。

### 只验证下载接口，不落盘

如果测试目标只是「导出接口能返回正确数据」，其实**不必走浏览器下载**。拿着浏览器的 cookie 直接用 requests 请求导出接口，更快更稳：

```python
import requests

cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
resp = requests.get("https://example.com/api/orders/export", cookies=cookies, timeout=30)

assert resp.status_code == 200
assert "spreadsheetml" in resp.headers["Content-Type"]
assert int(resp.headers["Content-Length"]) > 1024
```

**这是很值得推荐的分层思路**：UI 层只验证「点击导出按钮触发了正确的请求」，数据正确性交给接口层验证，见 [[06-接口自动化测试]]。

## 踩坑

1. **对上传按钮 `click()`**
   唤起系统对话框后用例直接卡死（driver 等不到响应），最后超时。永远对 `input[type=file]` 用 `send_keys`。

2. **传相对路径**
   `send_keys("testdata/a.png")` 在不同工作目录下解析不同，Grid 环境下更是必然失败。用 `os.path.abspath()`。

3. **Grid / 远程执行时文件不在浏览器所在机器上**
   远程 driver 需要先把文件传到浏览器节点：
   ```python
   from selenium.webdriver.remote.file_detector import LocalFileDetector
   driver.file_detector = LocalFileDetector()      # 让 send_keys 自动上传本地文件到节点
   ```
   不设置的话节点上找不到该路径，报「文件不存在」。

4. **隐藏 input 报 ElementNotInteractableException**
   用 JS 临时改样式让它可交互。这属于合理用法（不是绕过业务校验），但要加注释说明。

5. **上传后立刻断言**
   大文件上传需要时间，要等真正的完成信号（进度条消失、文件项出现「已完成」状态、或者用 `expect_response` 等上传接口返回 200），而不是等固定秒数。

6. **下载目录用固定路径**
   并行执行时文件互相干扰，同名文件被加 `(1)` 后缀导致断言失败。用 `tempfile.mkdtemp()` 每条用例一个目录，并在 teardown 清理。

7. **没等 `.crdownload` 消失就读文件**
   读到不完整内容，解析报错或断言随机失败。要双重判定：临时文件消失 + 文件大小连续两次相同。

8. **无头模式下载被禁用**
   老版 Chrome 无头默认不允许下载。用 `Page.setDownloadBehavior` CDP 命令打开，或升级到较新版本。

9. **PDF 被浏览器内置阅读器打开而不是下载**
   加 `plugins.always_open_pdf_externally: True`。

10. **测试文件被提交进仓库越堆越多**
    大文件（视频、大 Excel）不要进 Git。用代码生成：`openpyxl` 造 Excel、`Pillow` 造图片、`b"..."` 造文本文件，或者 Playwright 的内存文件写法。

11. **下载后忘记清理**
    CI 机器磁盘被下载文件占满。teardown 里 `shutil.rmtree(download_dir, ignore_errors=True)`。

## 面试怎么答

**Q：文件上传怎么做？**
A：核心原则是**不要点那个按钮**。点击 `<input type="file">` 会唤起操作系统级的文件对话框，WebDriver 控制不了它，用例会直接卡死。正确做法是对 input 元素 `send_keys(绝对路径)`——WebDriver 规范对 file input 的 send_keys 做了特殊处理，会直接把文件设进元素的 files 列表并派发 change 事件，等价于用户选了文件，且不需要弹出对话框，无头模式下也能用。要注意三点：路径必须是绝对路径；组件库常把 input 隐藏起来，需要先用 JS 改样式让它可交互；Grid 远程执行时要设 `file_detector = LocalFileDetector()`，否则浏览器节点上找不到本地文件。

**Q：为什么不用 AutoIt 或 pyautogui 操作文件对话框？**
A：三个问题。平台相关，Windows 写的脚本在 Linux CI 上跑不了；无头模式下压根没有对话框可操作；依赖屏幕坐标和窗口焦点，极不稳定，别的窗口一弹出来就失败。而 `send_keys` 方案是 WebDriver 规范支持的标准做法，跨平台、无头可用、稳定。所以这类需求应该优先找框架层的标准解法，而不是往系统层下沉。

**Q：文件下载怎么验证？**
A：下载发生在浏览器进程之外，验证的对象是文件系统。步骤是：先在 ChromeOptions 的 prefs 里指定下载目录并关掉「另存为」弹窗，目录用 `tempfile.mkdtemp` 每条用例独立，避免并行时互相干扰；触发下载后轮询等待，判定条件是「目标后缀文件出现」加「没有 `.crdownload` 临时文件残留」再加「文件大小连续两次采样相同」，三重判定才能确保写完了；最后校验文件名、大小和内容，Excel 用 openpyxl 解析后断言表头和行数。Playwright 的话简单得多，`with page.expect_download()` 捕获事件，`download.path()` 本身就阻塞到下载完成。

**Q：导出功能一定要走 UI 下载吗？**
A：不一定，我倾向于分层。UI 层只验证「点了导出按钮，触发了正确的导出请求」——用 `expect_response` 或者检查请求参数就够了；文件内容的正确性交给接口层测试，拿浏览器的 cookie 直接用 requests 请求导出接口，校验响应头和内容，又快又稳，还能覆盖更多数据组合。UI 层去做全量的数据内容校验，性价比很低而且很容易 flaky。

## 参考

- [Selenium · File upload](https://www.selenium.dev/documentation/webdriver/elements/file_upload/)
- [Playwright · File uploads / downloads](https://playwright.dev/python/docs/input#upload-files)
- [Playwright · Downloads](https://playwright.dev/python/docs/downloads)
- 相关笔记：[[Selenium 表单交互：输入、点击与下拉框]]
- 相关笔记：[[Selenium JavaScript 执行、滚动与拖拽]]
- 相关笔记：[[Selenium Grid 与并行执行]]
- 相关笔记：[[07-Web自动化测试]]
