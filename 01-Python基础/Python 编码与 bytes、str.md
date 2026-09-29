---
created: 2026-07-31
tags: [Python基础/文本]
---

# Python 编码与 bytes、str

> 中文乱码、请求体编码错误、文件读写报错，十有八九来自对“文本 vs 字节”分界不清。这是 Unicode 模型没理解透。测试开发处理接口、日志、文件，这是硬通货。

## 概念

### 1. 文本与字节是两个世界

- **`str`：Unicode 码点序列**。每个字符是一个 Unicode 码点（一个整数，如 `'中'` 是 `U+4E2D`）。`str` 与“字节”无关，是人类可读的抽象层。
- **`bytes`：原始字节序列**（每个元素 0–255）。用于网络传输、文件存储、加密。不可直接当文本处理。

二者通过**编解码**转换：
- `str.encode(encoding)` → `bytes`（文本按编码规则变成字节）
- `bytes.decode(encoding)` → `str`（字节按编码规则还原文本）

### 2. 为什么必须“显式指定编码”

同一个码点在不同编码下字节不同：`'中'` 在 UTF-8 是 3 字节 `E4 B8 AD`，在 GBK 是 2 字节 `D6 D0`。如果读文件/响应时用**错误的编码**解码，就会得到乱码或抛 `UnicodeDecodeError`。Python 3 的 `str` 内部统一用 Unicode，但**与外界交换时（文件、网络、终端）总是 bytes**，必须显式选编码。

### 3. UTF-8 是事实标准

UTF-8 是**变长**（1–4 字节）、**ASCII 兼容**的编码：英文字母仍占 1 字节，中文通常 3 字节。它跨平台、无字节序问题，是 Web/JSON/现代系统的默认。GBK/GB2312 是中文双字节编码、**非 ASCII 兼容**，Windows 本地环境常默认它，是乱码重灾区。

### 4. `open()` 的默认编码是“看平台脸色”

`open("f", "r")` 不指定 `encoding` 时，用的是 `locale.getpreferredencoding()`——Linux 通常是 UTF-8，Windows 常是 `cp936`（即 GBK）。这就是“我本地能跑、服务器乱码”的根源。**永远显式 `encoding="utf-8"`**。

### 5. 错误处理 `errors=`

`encode`/`decode` 遇到无法处理的字符，默认 `strict` 抛异常；可选 `ignore`/`replace`/`backslashreplace`/`surrogateescape`（用于文件名在 bytes/str 间无损往返）。

## 用法

```python
text = "小明"
b = text.encode("utf-8")          # b'\xe5\xb0\x8f\xe6\x98\x8e'（3 字节中文）
back = b.decode("utf-8")           # "小明"

# 文件永远显式编码
with open("cases.json", "r", encoding="utf-8") as f:
    data = f.read()
with open("out.txt", "w", encoding="utf-8") as f:
    f.write(data)

# 响应体是 bytes，先 decode
html = resp.content.decode("utf-8")

# 宽字符计数：码点 vs 字节
s = "中文"
print(len(s), len(s.encode("utf-8")))   # 2 6
```

## 踩坑

- **`UnicodeDecodeError`**：用错编码读数据。定位：确认数据真实编码（看 `Content-Type` 的 charset、`file` 命令、BOM），统一 UTF-8；必要时 `errors="replace"` 容错读取脏数据。
- **`TypeError: can't concat str and bytes`**：str 与 bytes 不能直接拼接/格式化；网络/subprocess 给的是 bytes，要先 `decode`；写文件用 str。
- **Windows 默认 GBK**：`open` 不指定 encoding 在 Win 上默认 GBK，中文极易报错；永远显式 `utf-8`。
- **BOM 坑**：Windows 记事本存 UTF-8 常带 BOM（`EF BB BF`），`"ï»¿"` 开头的假乱码；用 `encoding="utf-8-sig"` 读，或用编辑器存无 BOM。
- **`len(str)` 是码点数不是字节数**：中文字节宽度用 `len(s.encode("utf-8"))`；对齐/截断按字节要小心（emoji 占 1 码点多字节）。
- **`bytes` 不能 `%`/f-string 直接拼 str**：`b"a" + "b"` 报错；统一转成同一类型再操作。

## 面试怎么答

`str` 是 Unicode 码点序列（人类可读），`bytes` 是原始字节（网络/存储）；二者靠 `encode`/`decode` 转换，必须显式指定编码。UTF-8 变长、ASCII 兼容，是事实标准；GBK 非兼容、Windows 常默认，是乱码主因。

常见坑：① `open` 不指定 encoding 在 Windows 默认 GBK，中文乱码，要显式 UTF-8；② `str` 与 `bytes` 不能拼接（TypeError）；③ 响应体是 bytes 要先 decode；④ `len(str)` 是码点数非字节数；⑤ BOM 导致假乱码用 `utf-8-sig`。网络传输/文件存储用 bytes，业务处理用 str。

## 参考

- 官方文档：https://docs.python.org/zh-cn/3/howto/unicode.html
- 相关笔记：[[Python 字符串方法与切片]] [[Python 字符串格式化与 f-string]] [[Python pathlib 路径处理]]
