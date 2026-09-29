---
created: 2026-07-31
tags: [Python基础/标准库]
---

# Python os 与 shutil 文件操作

## 概念：os 管「系统接口」，shutil 管「高级文件动作」

- `os` / `os.path`：偏底层，提供与操作系统交互的接口——路径拼接、环境变量、目录遍历、权限、进程等。直来直去，但很多操作要自己组合。
- `shutil`：**高级文件操作**——复制、移动、删除整棵树、归档，帮你把 `os` 的多个步骤封装成一个可靠动作。

现代 Python 更推荐用 `pathlib`（见 [[Python pathlib 路径处理]]）做路径与文件读写，但 `os`/`shutil` 在「系统级操作」（环境变量、权限、目录树拷贝）上仍不可替代。

## 用法一：os.path 路径处理（与 pathlib 对照）

```python
import os

path = "/home/user/data/file.txt"
print(os.path.dirname(path))    # /home/user/data
print(os.path.basename(path))   # file.txt
print(os.path.join("a", "b", "c"))   # a/b/c（自动用系统分隔符）
print(os.path.splitext(path))   # ('/home/user/data/file', '.txt')
print(os.path.exists(path))     # 是否存在
print(os.path.isfile(path))     # 是否文件
print(os.path.isdir(path))      # 是否目录

# 获取绝对路径、规范化（.. 折叠）
print(os.path.abspath("data/../tmp"))
```

跨平台用 `os.path.join` 而非手写 `"/"` 拼接——Windows 是 `\`，Linux 是 `/`。`os.sep` 是当前系统分隔符。

## 用法二：目录遍历 os.walk

```python
import os

for root, dirs, files in os.walk("project"):
    # root：当前目录路径
    # dirs：该目录下的子目录名列表（可原地修改以剪枝）
    # files：该目录下的文件名列表
    for f in files:
        full = os.path.join(root, f)
        print(full)

# 剪枝：跳过 .git 目录
for root, dirs, files in os.walk("project"):
    dirs[:] = [d for d in dirs if d != ".git"]
```

`os.walk` 自顶向下（默认）或自底向上（`topdown=False`）遍历整棵目录树，是批量扫描文件的利器。

## 用法三：shutil 高级操作

```python
import shutil

shutil.copy("a.txt", "b.txt")          # 复制文件（保留内容）
shutil.copy2("a.txt", "b.txt")         # 复制并尽量保留元数据（mtime 等）
shutil.copytree("src/", "dst/")        # 递归复制整棵目录树
shutil.move("a.txt", "backup/")        # 移动（跨设备时是复制+删除）
shutil.rmtree("tmp/")                  # 递归删除目录树（危险！不可恢复）
shutil.make_archive("backup", "zip", "data/")  # 把 data/ 打包成 backup.zip
```

**`shutil.rmtree` 极其危险**：直接递归删除，不经过回收站，误删即永久丢失。生产环境应加二次确认或先备份。

## 用法四：环境变量与系统信息

```python
import os

print(os.environ.get("HOME"))         # 读环境变量（推荐 .get 避免 KeyError）
os.environ["MY_VAR"] = "1"             # 设置（仅当前进程及子进程生效）

print(os.getcwd())                     # 当前工作目录
os.chdir("/tmp")                       # 切换工作目录
```

> 环境变量是进程级的：`os.environ` 的修改只影响当前 Python 进程及其后续启动的子进程，不写回系统。

## 用法五：os 的其他常用

```python
import os

os.mkdir("new_dir")                    # 建单层目录（父不存在则报错）
os.makedirs("a/b/c", exist_ok=True)    # 递归建目录，exist_ok 防重复报错
os.remove("x.txt")                     # 删文件（不能删目录）
os.rename("old", "new")                # 重命名/移动
os.listdir(".")                        # 列出目录下条目名（不含 . 和 ..）
os.stat("x.txt").st_size              # 文件大小（字节）
```

`makedirs(..., exist_ok=True)` 是日常最安全的建目录写法，避免「已存在就崩」。

## 踩坑

1. **`shutil.rmtree` / `os.remove` 不可恢复**：删前务必确认路径，关键数据先备份。它们不进回收站。
2. **手写路径分隔符不跨平台**：用 `os.path.join` 或 `pathlib`，别写死 `"/"` 或 `"\\"`。
3. **`os.remove` 删目录会报错**：删目录用 `os.rmdir`（空目录）或 `shutil.rmtree`（整树）。
4. **`os.listdir` 不含 `.`/`..` 但是返回名字不是完整路径**：要 `os.path.join(dir, name)` 才是可用路径。
5. **`os.walk` 剪枝要在遍历中修改 `dirs` 列表**：原地改 `dirs[:] = ...` 才生效，重新赋值 `dirs = ...` 无效。
6. **环境变量不存在直接 `os.environ["X"]` 抛 KeyError**：用 `.get("X")` 或 `os.environ.get("X", default)`。
7. **`os.rename` 跨设备/跨盘可能失败**：跨文件系统移动用 `shutil.move`（内部会复制后删除）。
8. **相对路径依赖当前工作目录**：脚本里 `open("data.txt")` 的相对路径随 `cwd` 变化，建议用 `__file__` 或 `pathlib.Path` 锚定。

## 面试怎么答

**Q：os 和 shutil 的区别？**
A：os 偏底层系统接口（路径、目录遍历、环境变量、权限、进程）；shutil 提供高级文件动作（复制整树、移动、删除树、归档），把 os 的多个步骤封装成可靠操作。日常读写推荐 pathlib。

**Q：shutil.rmtree 有什么风险？**
A：它递归永久删除目录树，不进回收站，误删不可恢复。使用前必须确认路径、对关键数据先备份，必要时加二次确认。

**Q：怎么安全地建多级目录？**
A：用 `os.makedirs(path, exist_ok=True)`，父目录不存在会自动创建，`exist_ok=True` 避免目录已存在时报错。

**Q：os.walk 的 dirs 怎么剪枝？**
A：在循环中原地修改 `dirs` 列表（如 `dirs[:] = [d for d in dirs if ...]`），遍历器就不会进入被剪掉的子目录。重新赋值 `dirs` 变量无效，必须原地改。
