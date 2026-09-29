---
created: 2026-07-31
tags: [持续集成/Git]
---

# Git stash 与 cherry-pick

> 一个解决「活干到一半被打断」，一个解决「这个提交我只想要它一个」。两个命令都在做同一件事：把改动当补丁搬运。

## 概念

### stash：把工作区打包塞进抽屉

`git stash` 做三件事：

1. 把**工作区**和**暂存区**的改动各自打包成 commit 对象
2. 存进 `refs/stash` 这个特殊引用（一个栈结构）
3. 把工作区还原成 HEAD 的干净状态

关键点：**stash 存的是真正的 commit 对象**，不是什么临时文本文件。所以即使 `stash drop` 掉了，只要没被 gc 回收，理论上还能通过 `git fsck` 找回来。

为什么需要它：Git 切分支时，如果工作区的改动和目标分支冲突，会直接拒绝切换：

```text
error: Your local changes to the following files would be overwritten by checkout:
        tests/test_login.py
Please commit your changes or stash them before you switch branches.
```

这时你有三个选择：提交半成品（污染历史）、丢弃改动（工作没了）、**stash（正解）**。

### cherry-pick：把某个提交的改动复制到当前分支

`git cherry-pick <commit>` 把指定 commit 相对它父提交的**差异**算成补丁，应用到当前分支，生成一个**新的 commit**（内容一样，SHA 不同，因为父提交不同）。

它和 merge 的本质区别：

- merge：把一条线的**全部历史**汇入
- cherry-pick：只复制**一个（或几个）提交的改动**，历史不关联

典型场景就一个：**我只想要这一个修复，不想要它所在分支的其他东西**。

比如线上出了紧急 bug，开发在 `develop` 上已经顺手修了，但 develop 上还堆着一堆没测过的新功能，不能整体发布。这时从 `main` 拉 hotfix 分支，`cherry-pick` 那个修复提交，测完直接上线。

### 一个必须理解的后果：重复提交

cherry-pick 会让同一个改动在历史里出现两次（两个不同 SHA）。后续 `develop` 合并回 `main` 时，Git 用三方合并处理：如果两边内容完全一致，通常能自动消解；如果 cherry-pick 后又在任一边微调过，就会产生冲突。

这就是「**cherry-pick 不能替代 merge**」的原因——它是精确手术，不是常规同步手段。用多了历史会变得难以追踪。

## 用法

### 一、stash 常用操作

```bash
# 存起来（只存已跟踪文件的改动）
git stash
git stash push -m "登录用例改到一半"        # 带说明，强烈建议

# 关键参数
git stash -u        # --include-untracked，连新建的未跟踪文件一起存
git stash -a        # --all，连 .gitignore 忽略的文件也存（慎用，会把 .venv 存进去）
git stash -k        # --keep-index，暂存区的内容保留在工作区（想只测试已 add 的部分时用）

# 只 stash 某几个文件（Git 2.13+）
git stash push -m "只挪配置" config/env.yaml tests/conftest.py

# 查看
git stash list
# stash@{0}: On feature/login: 登录用例改到一半
# stash@{1}: WIP on main: 3f2a1b8 fix: token
git stash show stash@{0}            # 看统计
git stash show -p stash@{0}         # 看完整 diff

# 取出
git stash pop                       # 应用最新的并从栈里删除
git stash apply stash@{1}           # 应用指定的但保留在栈里（可重复应用到多个分支）
git stash pop --index               # 连暂存状态一起还原（哪些是 add 过的）

# 清理
git stash drop stash@{0}
git stash clear                     # 清空全部，危险，没有确认提示

# 从 stash 直接开一个分支（适合 stash 后主干变化很大、pop 必冲突的情况）
git stash branch feature/rescue stash@{0}
```

### 二、stash 的典型使用场景

**场景 1：被紧急任务打断**

```bash
# 正在写用例，突然要救火
git stash push -u -m "接口用例 wip"
git switch main && git pull --rebase
git switch -c hotfix/9012-token
# ...修复、提交、推送...
git switch feature/api-cases
git stash pop
```

**场景 2：pull 之前清空工作区**

```bash
git stash
git pull --rebase origin main
git stash pop      # 这里可能冲突，按 [[Git 冲突解决]] 的流程处理
```

更省事的做法是配置自动 stash，让 rebase 自己处理：

```bash
git config --global rebase.autoStash true
```

**场景 3：验证「这个改动是不是我引起的」**

```bash
git stash            # 把改动挪走，回到干净状态
pytest tests/test_login.py     # 干净状态下也失败 → 不是我的锅
git stash pop        # 改动拿回来
```

这在排查「本地跑挂了但不确定是环境问题还是我改坏了」时特别好用。

### 三、cherry-pick 常用操作

```bash
# 单个提交
git cherry-pick a1b2c3d

# 多个不连续的提交
git cherry-pick a1b2c3d 7e8f9a0

# 连续区间（左开右闭：不含 A，含 B）
git cherry-pick A..B
# 包含 A 本身
git cherry-pick A^..B

# 只把改动放进工作区，不自动提交（想合并成一个提交时用）
git cherry-pick -n a1b2c3d 7e8f9a0
git commit -m "fix: 合并两处 token 修复"

# 在 message 里自动附加 "(cherry picked from commit ...)"，强烈建议开
git cherry-pick -x a1b2c3d

# 冲突处理
git cherry-pick --continue
git cherry-pick --skip
git cherry-pick --abort
```

`-x` 参数值得默认打开：它会在新提交的 message 末尾加一行来源标注，半年后回头查「这个修复是从哪来的」时能救命。

### 四、hotfix 完整流程

```bash
# 1. 开发在 develop 上修好了，提交是 a1b2c3d
git log --oneline develop -5
# a1b2c3d fix: 支付回调空指针
# 9f8e7d6 feat: 新增优惠券模块      ← 这个还没测，不能上线

# 2. 从生产 tag 拉 hotfix 分支
git switch -c hotfix/1.4.1 v1.4.0

# 3. 只摘那一个修复
git cherry-pick -x a1b2c3d

# 4. 测试同学在这条分支上跑回归
#    （CI 里按分支名前缀 hotfix/ 触发「精简回归套件」，见 [[Jenkins 参数化构建与触发方式]]）

# 5. 合入 main 打 tag 发布
git switch main
git merge --no-ff hotfix/1.4.1
git tag -a v1.4.1 -m "紧急修复支付回调空指针"
git push origin main --tags
```

### 五、找出「哪些提交还没被 cherry-pick 过去」

```bash
# git cherry 会用「补丁内容」而不是 SHA 来比对
git cherry -v main hotfix/1.4.1
# + a1b2c3d fix: 支付回调空指针     ← + 表示 main 上还没有
# - 9f8e7d6 feat: 优惠券            ← - 表示等价改动 main 上已有
```

发布前用它自查「hotfix 上的修复是不是都回合 develop 了」，能避免 [[Git 分支模型：Git Flow 与 trunk-based]] 里提到的「hotfix 漏回合导致 bug 复发」这个经典事故。

### 六、在 CI 里的应用：自动回合

```groovy
// Jenkinsfile 片段：hotfix 合入 main 后，自动 cherry-pick 到 develop
stage('Sync hotfix to develop') {
    when { branch pattern: "hotfix/.*", comparator: "REGEXP" }
    steps {
        withCredentials([usernamePassword(credentialsId: 'git-bot',
                                          usernameVariable: 'GU', passwordVariable: 'GP')]) {
            sh '''
                git config user.name  "ci-bot"
                git config user.email "ci-bot@example.com"
                git fetch origin develop
                git switch -c sync-develop origin/develop

                # 把本次 hotfix 的所有提交摘过去
                if git cherry-pick -x origin/main..HEAD@{1}; then
                    git push https://$GU:$GP@git.example.com/app.git sync-develop:develop
                else
                    git cherry-pick --abort
                    echo "自动回合冲突，已创建告警，请人工处理"
                    exit 1
                fi
            '''
        }
    }
}
```

自动回合能解决大部分情况，冲突时退回人工——这比「完全靠人记得回合」可靠得多。

## 踩坑

1. **`git stash` 不存未跟踪文件**。新建的 `conftest.py`、新的用例文件不会被 stash，切分支后它们还留在工作区，可能污染另一条分支甚至被误提交。**养成习惯：一律用 `git stash -u`。**

2. **`git stash clear` 没有二次确认**。栈里十几个 stash 一秒清空，且不像 commit 那样能从 reflog 找回（stash 有自己的 reflog，但 `clear` 会一并清掉）。抢救方法：

   ```bash
   git fsck --unreachable | grep commit | cut -d' ' -f3 | xargs git log --merges --no-walk
   ```

   能不能找回全看有没有 gc 过，别赌。

3. **stash 太多，忘了哪个是哪个**。`stash@{0}: WIP on main: 3f2a1b8` 这种默认 message 毫无信息量，一周后完全不知道存的是什么。**永远用 `git stash push -m "说明"`。**

4. **`stash pop` 冲突后 stash 没被删除**。pop 遇冲突时会保留 stash 条目（这是好事，防止丢失），但很多人以为 pop 失败就没事了，解完冲突后忘记 `git stash drop`，下次 pop 又把老改动应用一遍。

5. **在错误的分支 `stash pop`**。stash 不记录来源分支，pop 到哪个分支全看你当时在哪。把 feature 的改动 pop 到 main 上，然后顺手 `commit -am` 一提，就污染主干了。pop 前先 `git branch --show-current` 确认。

6. **cherry-pick 一个合并提交**。合并提交有两个父提交，Git 不知道该相对哪个算差异，报 `is a merge but no -m option was given`。要写 `git cherry-pick -m 1 <merge-commit>`（`-m 1` 表示相对第一父提交，即主干那条线）。

7. **cherry-pick 漏摘依赖提交**。要摘的修复依赖前一个提交里新增的工具函数，只摘后者会产生 `NameError` 或冲突。判断方法：`git show <commit>` 看它引用了什么，必要时用区间 `git cherry-pick A^..B` 一起摘。

8. **滥用 cherry-pick 代替 merge**。有人图省事天天从 develop 摘提交到自己分支，导致同一改动在历史里出现 N 次，后续真正合并时冲突炸裂，`git log` 也彻底失真。**cherry-pick 是特例手段，常规同步用 merge/rebase。**

9. **cherry-pick 后原分支又改了那个提交**（`commit --amend` 或 rebase 过），两边内容不再等价，后续合并必冲突。摘之前确认源提交是稳定的、已推送的。

10. **在 CI 的 detached HEAD 上 stash**。Jenkins checkout 后常处于分离头指针状态，此时 stash 没问题，但切走就很难找回。CI 脚本里不应该依赖 stash，要清工作区就用 `git clean -fdx` + `git reset --hard`。

## 面试怎么答

**Q：`git stash` 是干什么的，用过哪些参数？**

A：把工作区和暂存区的改动打包成 commit 对象存进 stash 栈，然后把工作区还原成干净状态，用于「活干到一半要切分支」的场景。常用 `git stash push -u -m "说明"`——`-u` 是关键，不加的话新建的未跟踪文件不会被存走，切过去还留在工作区；`-m` 是为了以后看得懂存的是什么。取回用 `pop`（用完删）或 `apply`（保留，可以应用到多个分支）。如果 stash 之后主干变化很大、pop 必冲突，可以用 `git stash branch <name>` 直接基于当时的基点开一条分支再合。另外我全局配了 `rebase.autoStash=true`，rebase 时自动帮我 stash 和还原。

**Q：什么场景用 cherry-pick？**

A：最典型的是紧急修复。开发在 develop 上把线上 bug 修了，但 develop 上还堆着没测过的新功能，不能整体发布。我们就从生产 tag 拉 hotfix 分支，`cherry-pick -x` 只摘那一个修复提交，跑精简回归，测完合 main 打 tag 上线。`-x` 会在 message 里自动记录来源提交，方便追溯。另一个场景是「某个提交提错分支了」，摘到正确分支再把原处 revert 掉。

**Q：cherry-pick 有什么风险？**

A：它是复制改动生成新提交，SHA 不同，所以同一个改动会在历史里出现两次。后续两条分支真正合并时，如果内容完全一致 Git 一般能自动消解，但只要任一边微调过就会冲突。而且历史上看不出这两个提交是同源的，追踪困难。所以我把它当特例手段——只在「确实只要这一个提交」时用，常规同步一律 merge 或 rebase。还有两个具体坑：摘合并提交必须加 `-m 1` 指定相对哪个父提交；摘的提交如果依赖前面提交里的新函数，要一起摘，否则代码跑不起来。

**Q：stash 之后 pop 冲突了怎么办？**

A：按正常冲突流程解——`git status` 看哪些文件冲突，编辑解决，`git add`。要注意两点：一是 pop 遇冲突时 stash 条目**不会**被删除，这是 Git 的保护机制，解完冲突后要手动 `git stash drop`，否则下次 pop 会重复应用；二是如果冲突特别多，说明 stash 之后基线变化太大，更省事的做法是 `git stash branch <新分支名>`，Git 会基于 stash 创建时的那个 commit 建分支并还原改动，此时不会有冲突，再按正常流程 rebase 主干。

## 参考

- [git-stash 文档](https://git-scm.com/docs/git-stash)
- [git-cherry-pick 文档](https://git-scm.com/docs/git-cherry-pick)
- 相关笔记：[[Git 常用命令与四区模型]]、[[Git 冲突解决]]、[[Git 分支模型：Git Flow 与 trunk-based]]、[[Git reset 与 revert]]
