---
created: 2026-07-31
tags: [持续集成/Git]
---

# Git 冲突解决

> 冲突不是错误，是 Git 在说「这两处改动我判断不了该听谁的，你来定」。慌是因为不知道自己在哪、在合谁。

## 概念

### 冲突是怎么产生的

Git 合并用的是**三方合并（three-way merge）**，涉及三个版本：

- **base**：两条分支的共同祖先（merge base）
- **ours**：当前分支的版本
- **theirs**：要合进来的分支的版本

对每一个改动块（hunk），Git 的判断逻辑是：

| base → ours | base → theirs | 结果 |
|-------------|---------------|------|
| 没变 | 变了 | 用 theirs |
| 变了 | 没变 | 用 ours |
| 变成一样的 | 变成一样的 | 用任意一个 |
| 变成不一样的 | 变成不一样的 | **冲突** |

所以冲突的严格定义是：**同一段内容，两边从同一个起点改成了不同的样子**。

### 会产生冲突的几类情况

1. **内容冲突**：同一行或相邻行两边都改了。最常见。
2. **删改冲突**：一边删了文件，一边改了这个文件。Git 提示 `deleted by us / modified by them`。
3. **改名冲突**：一边把 `a.py` 改名成 `b.py`，一边改了 `a.py` 的内容。Git 的改名检测是靠内容相似度**猜**的，猜不中就变成「删除 + 新增」两个冲突。
4. **目录/文件冲突**：一边把 `config` 建成目录，一边建成文件。
5. **语义冲突**：两边改的不是同一行，Git 顺利合并，但代码逻辑坏了。**Git 不会报冲突，这类最危险**（见 [[Git merge 与 rebase]]）。

### merge 冲突 vs rebase 冲突：ours 和 theirs 会反过来

这是最容易搞错的地方，直接导致「解冲突时选反了」。

**merge 时**：你站在自己分支上，`ours` = 你的分支，`theirs` = 要合进来的分支。符合直觉。

**rebase 时**：Git 是把「你的提交」逐个重放到「目标分支」上，此时**目标分支才是基础**，所以 `ours` = 目标分支（比如 main），`theirs` = 你正在被重放的那个提交。**完全反过来了。**

```bash
# merge：ours=feature（我的），theirs=main
git switch feature && git merge main

# rebase：ours=main（目标），theirs=feature（我的，正在被重放）
git switch feature && git rebase main
```

记忆方法：**rebase 时「我」是客人，正被一个个搬到主人（main）家里，所以 theirs 才是我。**

## 用法

### 一、遇到冲突后的标准动作

```bash
git merge origin/main
# Auto-merging tests/test_login.py
# CONFLICT (content): Merge conflict in tests/test_login.py
# Automatic merge failed; fix conflicts and then commit the result.

# 第一步永远是看清现状
git status
# You have unmerged paths.
#   both modified:   tests/test_login.py
#   deleted by them: config/old.yaml

# 只列出冲突文件（脚本里好用）
git diff --name-only --diff-filter=U
```

### 二、读懂冲突标记

默认的 `merge` 样式只有两段：

```python
def login(user, pwd):
<<<<<<< HEAD
    timeout = 30
=======
    timeout = 60
>>>>>>> origin/main
    return post("/login", json={"user": user, "pwd": pwd}, timeout=timeout)
```

只看到 30 和 60，你不知道原来是多少，也就判断不了谁改了、改的意图是什么。**强烈建议改成 `zdiff3` 样式**：

```bash
git config --global merge.conflictstyle zdiff3
```

之后冲突长这样：

```python
<<<<<<< HEAD
    timeout = 30
||||||| base
    timeout = 10
=======
    timeout = 60
>>>>>>> origin/main
```

现在信息完整了：原值是 10，我改成 30，对方改成 60。这时才能做出有依据的判断（比如问对方为什么要 60，是不是有慢接口）。

### 三、四种解法

```bash
# 解法 1：手动编辑（最常用）——删掉所有 <<<<<<< ======= >>>>>>> 标记，留下正确内容
vim tests/test_login.py
git add tests/test_login.py

# 解法 2：整个文件要我的版本
git checkout --ours  tests/test_login.py && git add tests/test_login.py
# 解法 3：整个文件要对方的版本
git checkout --theirs tests/test_login.py && git add tests/test_login.py

# 解法 4：用图形化工具（配好后一条命令逐个文件过）
git mergetool

# 全部解完
git merge --continue        # merge 场景
git rebase --continue       # rebase 场景

# 中途想放弃
git merge --abort
git rebase --abort
```

> `--ours` / `--theirs` 是**整文件**级别的取舍，不是逐块。文件里既有你的改动又有对方的改动时，用它一定会丢东西。只在「配置文件、锁文件这类可以整体取一边」的场景用。

### 四、看清楚三方各自是什么

冲突状态下，三个版本都还在暂存区里，可以精确取出来对比：

```bash
git show :1:tests/test_login.py > /tmp/base.py     # 阶段1 = base
git show :2:tests/test_login.py > /tmp/ours.py     # 阶段2 = ours
git show :3:tests/test_login.py > /tmp/theirs.py   # 阶段3 = theirs

diff /tmp/base.py /tmp/ours.py       # 我改了什么
diff /tmp/base.py /tmp/theirs.py     # 对方改了什么
```

复杂冲突（比如整个函数被重构过）用这招比盯着冲突标记高效得多。

### 五、几类特殊冲突的处理

**删改冲突**：

```bash
git status
# deleted by them: config/old.yaml    ← 对方删了，我改了

# 认同删除：
git rm config/old.yaml
# 认为不该删（比如我加了新配置项）：
git add config/old.yaml
```

**二进制文件冲突**（图片、`.xlsx` 测试数据、`.jmx` 脚本）：没法合并，只能整体二选一。

```bash
git checkout --theirs testdata/users.xlsx
git add testdata/users.xlsx
```

预防手段：这类文件在 `.gitattributes` 里标记为 binary，并约定「同一时间只有一个人改」，或者干脆改用 CSV 等文本格式让 Git 能合（见 [[Git .gitignore 规则与失效排查]]）。

**依赖锁文件冲突**（`poetry.lock`、`package-lock.json`、`requirements.txt` 排序变化）：不要手工解，会解出一个谁的环境都装不上的四不像。

```bash
# 取一边然后重新生成
git checkout --theirs poetry.lock
poetry lock --no-update
git add poetry.lock
```

### 六、rerere：让 Git 记住你的解法

长期维护的分支反复 rebase 主干时，同一个冲突要解很多遍。开启 rerere 后，Git 会记录「这个冲突你是怎么解的」，下次遇到一模一样的冲突自动套用。

```bash
git config --global rerere.enabled true

# 之后再遇到已记录过的冲突：
git rebase origin/main
# Resolved 'tests/test_login.py' using previous resolution.

git rerere status     # 看当前有哪些冲突被自动解了
git rerere diff       # 看自动解出来的结果，确认无误再 add
```

注意：**rerere 自动解完仍要 `git add` 并人工确认一眼**，它复用的是文本层面的解法，不保证语义仍然正确。

### 七、把「预防冲突」做进流水线

解冲突最好的办法是不产生冲突。CI 层面能做两件事：

```yaml
# .github/workflows/conflict-check.yml
# PR 一开就检查能不能干净地合进 main，早于 review 暴露问题
name: conflict-check
on:
  pull_request:
    branches: [main]

jobs:
  can-merge:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: 试合并，失败即报冲突
        run: |
          git config user.name ci
          git config user.email ci@example.com
          git fetch origin main
          if ! git merge --no-commit --no-ff origin/main; then
            echo "::error::与 main 存在冲突，请先本地 rebase/merge 解决后再推"
            git merge --abort
            exit 1
          fi
          git merge --abort
```

配合分支保护里的 "Require branches to be up to date before merging"，可以从制度上杜绝「陈旧分支闷头合入」（见 [[质量门禁设计与失败即阻断]]）。

## 踩坑

1. **把冲突标记提交进仓库**。`<<<<<<< HEAD` 这几行直接进了代码，Python 立刻 `SyntaxError`，YAML 直接解析失败。CI 上一片红才发现。**加一道 pre-commit 钩子拦死它**：

   ```bash
   # .git/hooks/pre-commit（记得 chmod +x）
   #!/bin/sh
   if git diff --cached --check | grep -q "conflict marker"; then
       echo "存在冲突标记，禁止提交"; exit 1
   fi
   if git grep -nE '^(<{7}|={7}|>{7})( |$)' -- $(git diff --cached --name-only); then
       echo "检测到未解决的冲突标记"; exit 1
   fi
   ```

2. **rebase 时 `--ours` / `--theirs` 选反**。以为 `--ours` 是自己的改动，结果 rebase 下 `ours` 是主干，一条命令把自己一天的工作覆盖没了。**不确定时先 `git show :2:file` 和 `:3:file` 看清楚再动手。**

3. **`git checkout --theirs` 整个文件覆盖，丢掉自己的改动**。文件里同时有双方改动时，整文件取舍必然丢东西。这类丢失特别隐蔽，因为代码能跑、测试可能也过，等到线上才发现某个功能没了。

4. **解完冲突没跑测试就 push**。冲突解得「看起来对」但语义错了，是回归 bug 的重要来源。规矩：**解完冲突必须本地至少跑一遍相关用例**，别指望 CI 兜底（CI 红了也是浪费大家时间）。

5. **`git merge --abort` 失败**。如果 merge 开始前工作区就有未提交改动，abort 可能报 "error: Entry ... would be overwritten by merge"。所以合并前务必保证工作区干净：先 `git stash`（见 [[Git stash 与 cherry-pick]]）。

6. **长期分支的冲突雪球**。两周不同步主干，一次合并 200 个冲突，解到后面开始机械地按 `--theirs`，质量完全失控。**每天 rebase 一次主干**，每次只有 1–2 个冲突，成本几乎为零。

7. **锁文件手工解**。`package-lock.json` 手工合并出来的版本树是不一致的，`npm ci` 直接失败，或者装出一堆版本错乱的依赖。永远「取一边 + 重新生成」。

8. **忘了 `git add` 就 `--continue`**。Git 报 "you must edit all merge conflicts and then mark them as resolved"。解完必须 `add` 才算标记为已解决。

9. **CI 上出现本地没有的冲突**。多半是 CI 用了浅克隆（`fetch-depth: 1`），拿不到共同祖先，Git 只能退化处理。CI 上做合并类操作时必须 `fetch-depth: 0`。

## 面试怎么答

**Q：Git 冲突是怎么产生的，你怎么解决？**

A：Git 用三方合并，比较共同祖先、我方版本、对方版本。只有一边改的地方它能自动合；同一段内容两边从同一起点改成了不同结果，它判断不了，就标记为冲突交给人。我的处理流程是：先 `git status` 看清楚在做什么操作、哪些文件冲突；然后逐个文件看冲突标记，我会把 `merge.conflictstyle` 配成 `zdiff3`，这样能看到原始版本，判断双方各自的修改意图，必要时直接找对方确认；解完 `git add`，再 `merge --continue`；最后**本地跑一遍相关测试**再推。搞不清楚状况时就 `--abort` 回到原点重来，不要在混乱状态里硬解。

**Q：rebase 时的 ours 和 theirs 为什么和 merge 相反？**

A：因为 rebase 的本质是「把我的提交逐个重放到目标分支上」，此时目标分支是基础、是 ours，我正在被重放的那个提交才是外来的 theirs。而 merge 时我站在自己分支上，自己自然是 ours。这个反转坑过很多人，选反了会把自己的改动整个覆盖掉。所以我不太依赖 `--ours/--theirs`，更倾向手动编辑，或者先用 `git show :2:file`、`git show :3:file` 把两边内容取出来看清楚。

**Q：怎么减少冲突？**

A：分四层。第一，流程上——用短命分支，每天至少 rebase 一次主干，分支活得越短冲突越少；分支超过三天没合就该拆需求了。第二，工程上——模块划分清晰，减少多人改同一个文件；把大文件拆小；测试数据这类容易冲突的文件约定单人负责或改成可合并的文本格式。第三，工具上——开 `rerere` 复用冲突解法，开 `zdiff3` 让判断有依据。第四，制度上——PR 门禁开「require branches to be up to date」，强制陈旧分支先同步主干再合，同时 CI 里加一步试合并检查，让冲突在 review 之前就暴露。

**Q：合并冲突解完了，还需要注意什么？**

A：一定要跑测试。Git 只做文本合并，解冲突时很容易解出「语法正确但逻辑错」的代码；还有一类语义冲突根本不会报冲突——比如对方把函数改了名，我新增了对旧名字的调用，两边不同行，Git 自动合并成功但代码直接报错。所以「没冲突 ≠ 合并正确」，最终保障只能是合并后的完整 CI。

## 参考

- [Pro Git · 高级合并](https://git-scm.com/book/zh/v2/Git-工具-高级合并)
- [git-merge 文档 · HOW CONFLICTS ARE PRESENTED](https://git-scm.com/docs/git-merge#_how_conflicts_are_presented)
- 相关笔记：[[Git merge 与 rebase]]、[[Git stash 与 cherry-pick]]、[[Git 常用命令与四区模型]]、[[质量门禁设计与失败即阻断]]
