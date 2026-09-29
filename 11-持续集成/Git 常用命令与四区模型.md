---
created: 2026-07-31
tags: [持续集成/Git]
---

# Git 常用命令与四区模型

> 记不住 Git 命令的根因不是命令多，而是不知道每条命令在「工作区 / 暂存区 / 本地仓库 / 远程仓库」之间搬了什么。

![[assets/git-areas.svg]]
*图示：Git 四区模型——add / commit / push 是向右搬运，restore / reset / fetch 是向左回退，stash 是把工作区改动临时挪到一边。*

## 概念

### Git 不是「存差异」，是「存快照」

SVN 那一代版本控制存的是「相对上一版改了哪几行」（delta）。Git 反过来：**每次 commit 存的是当时整个项目的完整快照**，没变的文件只存一个指向旧文件对象的指针。

这个设计决定了 Git 的一切行为特征：

- **切分支极快**：切分支就是把 HEAD 指针指向另一个 commit，然后按快照把工作区刷成对应状态，不需要逐行打补丁。
- **本地就能查全部历史**：`.git` 目录里是完整仓库副本，`git log`、`git diff`、`git blame` 全部离线可用。
- **commit 一旦生成就不可变**：commit 的 SHA-1 是「树对象 + 父提交 + 作者 + 时间 + message」整体算出来的哈希，改任何一项都会产生一个**新** commit（这就是 `rebase`、`commit --amend` 之后 SHA 会变的原因，详见 [[Git merge 与 rebase]]）。

### 四个区，一条单向主干

| 区域 | 物理位置 | 装的是什么 | 谁能看到 |
|------|----------|-----------|---------|
| 工作区 Working Tree | 你的项目目录 | 你正在编辑的文件 | 只有你 |
| 暂存区 Index / Stage | `.git/index` | 下次 commit 的快照草稿 | 只有你 |
| 本地仓库 Local Repo | `.git/objects` | 已封存的 commit 对象 | 只有你 |
| 远程仓库 Remote | 服务器 | 团队共享的 commit | 所有人 |

**为什么要有暂存区**——这是初学者最不理解的一环。暂存区的价值在于让你**挑选**这次提交包含什么。你改了 5 个文件，其中 3 个是 bug 修复、2 个是顺手改的格式，可以只 `add` 那 3 个，提交一个干净的原子 commit，剩下 2 个下次再提。没有暂存区就只能「全提交或全不提交」。

### HEAD 到底是什么

`HEAD` 是一个指向「你当前在哪」的指针，内容通常是 `ref: refs/heads/main`——即指向分支，分支再指向 commit。

```bash
cat .git/HEAD                 # ref: refs/heads/main
cat .git/refs/heads/main      # 3f2a1b... 当前分支最新 commit 的 SHA
```

理解这个链条后，很多命令就不用背了：

- `git commit` = 生成新 commit 对象，让当前分支的 ref 指向它
- `git checkout <branch>` = 改 HEAD 指向哪个分支 + 刷新工作区
- `git reset <commit>` = 让当前分支的 ref 指向另一个 commit（详见 [[Git reset 与 revert]]）

## 用法

### 一、初始化与身份配置

```bash
# 全局身份，直接影响 commit 里记录的 author，CI 上排查是谁提交的全靠它
git config --global user.name "zhang.san"
git config --global user.email "zhang.san@example.com"

# 中文文件名不转义成 \344\270\255，否则 git status 看不懂
git config --global core.quotepath false

# 换行符：Windows 用 true（检出转 CRLF、提交转 LF），Linux/Mac 用 input
git config --global core.autocrlf true

# 看当前生效的配置以及它来自哪个文件
git config --list --show-origin
```

### 二、日常提交四连

```bash
git status                      # 先看现状，永远是第一步
git status -s                   # 精简输出：?? 未跟踪, A 已暂存, M 已修改

git add tests/test_login.py     # 加单个文件
git add tests/                  # 加整个目录
git add -u                      # 只加「已跟踪且被修改/删除」的，不加新文件
git add -A                      # 全加（含新增、删除）
git add -p                      # 交互式逐块挑选，做原子提交的利器

git commit -m "fix: 修复登录接口 token 过期未刷新"
git commit -am "..."            # -a 等价于先 add -u，注意：不含新文件

git log --oneline --graph --decorate -10   # 看最近 10 条，带分支图
```

`git add -p` 值得单独说：它会把改动按 hunk 拆开逐块问你 `y/n`，可以把「一次改了三件事」的工作区拆成三个语义清晰的 commit。CI 上排查问题时，一个 commit 只干一件事，`git bisect` 才能精确定位。

### 三、看差异：diff 的三种视角

```bash
git diff                    # 工作区 vs 暂存区（改了但还没 add 的）
git diff --staged           # 暂存区 vs HEAD（add 了但还没 commit 的）
git diff HEAD               # 工作区 vs HEAD（本次所有未提交改动）
git diff main..feature      # 两个分支的差异
git diff main...feature     # feature 相对「共同祖先」的差异（PR 视角，更常用）
git diff --stat             # 只看文件级统计，不看具体行
```

两点和三点的区别是面试小坑：`A..B` 是「B 有而 A 没有 + A 有而 B 没有」的纯文本差异；`A...B` 是「从 A、B 的共同祖先算起，B 上新增了什么」，这才是 code review 想看的东西。

### 四、撤销：按「改动在哪个区」选命令

```bash
# 改动还在工作区，想丢掉（Git 2.23+ 推荐写法）
git restore tests/test_login.py
git restore .                    # 丢掉全部工作区改动，不可恢复！

# 已经 add 到暂存区，想撤回到工作区（保留改动内容）
git restore --staged tests/test_login.py

# 已经 commit，想改 message 或补文件（仅限未 push）
git commit --amend -m "新的 message"
git add 漏掉的文件 && git commit --amend --no-edit
```

老命令 `git checkout -- <file>` 和 `git reset HEAD <file>` 效果一样，但 `checkout` 一个词干了「切分支」「丢改动」两件不相干的事，太容易误操作。Git 2.23 之后拆成了 `switch`（切分支）和 `restore`（丢改动），新项目一律用新命令。

### 五、分支操作

```bash
git branch -a                        # 看所有分支（含远程 remotes/origin/*）
git switch -c feature/login-api      # 新建并切换（等价于旧的 checkout -b）
git switch main                      # 切换
git branch -d feature/login-api      # 删除已合并的分支
git branch -D feature/login-api      # 强删未合并的分支（会丢 commit）
git branch -vv                       # 看每个本地分支跟踪的上游及领先/落后数
```

### 六、与远程同步

```bash
git remote -v                          # 看远程地址
git fetch origin                       # 只拉到本地，不动工作区（安全）
git pull origin main                   # = fetch + merge，会动工作区
git pull --rebase origin main          # = fetch + rebase，历史更干净
git push origin feature/login-api      # 推分支
git push -u origin feature/login-api   # 推并设置上游，之后直接 git push 即可
```

**推荐把 pull 默认设成 rebase**，避免本地随手一 pull 就多出一堆无意义的 "Merge branch 'main' of ..." 合并提交：

```bash
git config --global pull.rebase true
```

### 七、排查类命令（测试同学的高频武器）

```bash
# 某一行是谁什么时候改的——定位到人，直接找他确认预期行为
git blame -L 40,60 src/login.py

# 二分查找哪个 commit 引入了 bug，自动化脚本可全自动跑
git bisect start
git bisect bad                 # 当前版本是坏的
git bisect good v1.2.0         # 这个版本是好的
git bisect run pytest tests/test_login.py::test_token   # 自动跑到定位出元凶
git bisect reset

# 搜索历史中所有提交过的内容（找被删掉的代码）
git log -S "get_token" --oneline

# 看某个文件的完整变更史
git log --follow -p -- tests/test_login.py

# 找回「丢失」的 commit：所有 HEAD 移动记录，默认保留 90 天
git reflog
```

`git bisect run` 配合自动化用例是测试开发的杀手锏：给一个可复现的失败用例，它能在 O(log n) 次构建内自动指出是哪个 commit 引入的回归，比人肉回退高效几个数量级。

## 踩坑

1. **`git commit -am` 提交不了新文件**。`-a` 只处理「已被 Git 跟踪」的文件，新建的文件是 untracked，必须先 `git add`。经常出现「本地跑得通、CI 报 `ModuleNotFoundError`」，一查是新建的 `conftest.py` 根本没提交上去。

2. **`git pull` 后本地改动被 merge 冲突淹没**。`pull` = `fetch` + `merge`，工作区有未提交改动时容易乱。安全姿势：先 `git stash`，再 `git pull --rebase`，最后 `git stash pop`（见 [[Git stash 与 cherry-pick]]）。

3. **`git restore .` / `git checkout .` 丢的改动找不回来**。这些改动从未进入 Git 对象库，`reflog` 也救不了。养成习惯：想丢弃前先 `git stash`，确认没用了再 `git stash drop`。

4. **Windows 换行符导致「整个文件都变了」**。`core.autocrlf` 配置不一致时，`git diff` 显示几百行改动但肉眼看不出区别。团队统一在仓库根放 `.gitattributes`：

   ```text
   * text=auto eol=lf
   *.sh text eol=lf
   *.bat text eol=crlf
   *.png binary
   ```

5. **CI 上 `git log` 只有一条记录**。Jenkins / GitHub Actions 默认浅克隆（`--depth 1`），`git describe`、`git log` 拿不到历史，SonarQube 增量分析和「本次改动文件列表」全部失效。解法：GHA 里 `actions/checkout@v4` 设 `fetch-depth: 0`；Jenkins 里去掉 Shallow clone 选项。

6. **detached HEAD 状态下提交，切走就丢了**。`git checkout <sha>` 会进入分离头指针状态，此时 commit 不属于任何分支。切走后提示 "you are leaving 1 commit behind"。补救：`git reflog` 找到 SHA，`git branch rescue <sha>`。

7. **`.git` 目录膨胀到几个 G**。多半是有人提交过大二进制文件（测试用的视频、数据库 dump）。删文件不管用，历史里还在。要么 `git filter-repo` 重写历史（全员重新 clone），要么改用 Git LFS。预防手段是 `.gitignore` 加 pre-commit 大小检查（见 [[Git .gitignore 规则与失效排查]]）。

8. **中文文件名显示成 `\344\270\255`**。没关 `core.quotepath`。在 CI 脚本里按文件名过滤时会直接匹配不上。

## 面试怎么答

**Q：说说 Git 的工作区、暂存区、本地仓库、远程仓库。**

A：工作区是我正在编辑的目录；`git add` 把改动放进暂存区，暂存区是「下次提交的快照草稿」，存在 `.git/index`；`git commit` 把暂存区的快照封成一个不可变的 commit 对象存进本地仓库；`git push` 才把 commit 推到远程共享。设计暂存区的目的是让我能挑选本次提交的内容，做出语义单一的原子提交，而不是被迫全量提交。对应的回退命令分别是 `restore`（丢工作区）、`restore --staged`（撤暂存）、`reset`（移分支指针）。

**Q：`git fetch` 和 `git pull` 的区别？**

A：`fetch` 只把远程的 commit 下载到本地的 `origin/main` 这类远程跟踪分支，**不动我的工作区和当前分支**，是绝对安全的操作。`pull` = `fetch` + `merge`（或 `rebase`），会直接改我当前分支和工作区。团队协作我习惯先 `fetch`，用 `git log HEAD..origin/main` 看清别人改了什么，再决定 merge 还是 rebase；或者配 `pull.rebase=true` 避免产生一堆无意义的合并提交。

**Q：怎么定位一个回归 bug 是哪次提交引入的？**

A：先写一个能稳定复现的用例，然后用 `git bisect`：标记一个已知好的版本和一个坏的版本，Git 会二分切换 commit，我用 `git bisect run pytest tests/xxx.py::test_bug` 让它自动跑，几轮之后直接输出元凶 commit。100 个提交只需要约 7 次构建。定位到 commit 后再用 `git blame` 和 `git show` 看具体改了什么、找作者确认。这套流程在我们回归测试发现问题时非常常用。

**Q：不小心 `git reset --hard` 把提交搞没了怎么办？**

A：只要 commit 曾经生成过，就还在对象库里，只是没有 ref 指向它。用 `git reflog` 看 HEAD 的所有移动记录，找到目标 commit 的 SHA，然后 `git reset --hard <sha>` 或 `git branch rescue <sha>` 恢复。reflog 默认保留 90 天。但要注意：**从未 commit 过的工作区改动救不回来**，因为它们从没进过对象库。

## 参考

- [Git 官方文档 / Pro Git 中文版](https://git-scm.com/book/zh/v2)
- [git-scm reference](https://git-scm.com/docs)
- 相关笔记：[[Git 分支模型：Git Flow 与 trunk-based]]、[[Git merge 与 rebase]]、[[Git reset 与 revert]]、[[Git stash 与 cherry-pick]]、[[Git .gitignore 规则与失效排查]]
