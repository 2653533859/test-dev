---
created: 2026-07-31
tags: [持续集成/Git]
---

# Git reset 与 revert

> 判断标准只有一条：**这个提交推出去了吗？** 没推 → reset 随便用；推了 → 只能 revert。

![[assets/git-reset-revert.svg]]
*图示：reset 是移动分支指针、改写历史（三种模式动的区域不同）；revert 是追加一个内容相反的新提交、历史只增不减。*

## 概念

### reset：移动分支指针

`git reset <commit>` 的核心动作是**让当前分支的 ref 指向另一个 commit**。原来指向的那些 commit 并没有被删除，只是没有 ref 指向它们了，变成「悬空对象」，等待 gc 回收（默认 30 天，reflog 记录保留 90 天）。

三种模式的差别在于「除了移指针，还动不动暂存区和工作区」：

| 模式 | HEAD/分支指针 | 暂存区 | 工作区 | 效果 |
|------|--------------|--------|--------|------|
| `--soft` | 移动 | 不动 | 不动 | 提交被撤销，改动全在暂存区里等着重新提交 |
| `--mixed`（默认） | 移动 | 重置为新 HEAD | 不动 | 提交和 add 都撤销，改动留在工作区 |
| `--hard` | 移动 | 重置 | **重置** | 提交和改动全部消失 |

推导记忆：`soft` 最轻只动指针，`mixed` 多动一个暂存区，`hard` 三个全动。**只有 `--hard` 会真正丢失文件内容**，另外两个都是「重新组织一下改动放在哪个区」。

### revert：追加一个反向提交

`git revert <commit>` 计算指定提交的**反向补丁**（它加的行删掉，它删的行加回来），作为一个**新提交**追加到分支末尾。

历史上原提交仍然存在，只是被后面的新提交抵消了。所以：

- **不改写历史** → 不需要强推 → 对所有协作者安全
- 缺点是历史里会留下「做了又撤」的痕迹（这其实是优点：可审计）

### 为什么已推送的提交不能 reset

假设你 `reset --hard` 回退了两个提交然后强推。此时：

- 同事本地的 main 还指向被你删掉的提交
- 他 `git pull` 时，Git 发现远程「倒退」了，会尝试合并，把你删掉的提交又合回来
- 或者他直接 `reset --hard origin/main`，那他基于那两个提交做的后续工作全没了

一句话：**你单方面改写了大家共享的事实**。这就是为什么团队分支必须禁用强推（`Settings → Branches → 取消 Allow force pushes`）。

### 还有一个：`git restore`

Git 2.23 之后，「丢弃工作区改动」这件事从 `checkout`/`reset` 里独立出来了：

```bash
git restore <file>              # 丢弃工作区改动（相当于旧的 checkout -- file）
git restore --staged <file>     # 撤销 add（相当于旧的 reset HEAD file）
git restore --source=HEAD~2 <file>   # 把文件恢复成两个版本前的样子
```

新代码里优先用 `restore`，语义清晰、不容易误伤分支指针。

## 用法

### 一、reset 三种模式实操

```bash
# 准备：最近三个提交
git log --oneline -3
# c3d4e5f (HEAD -> main) wip: 乱七八糟
# b2c3d4e fix: typo
# a1b2c3d feat: 登录用例

# --soft：撤销最近两个提交，改动全在暂存区，直接重新提交成一个干净的
git reset --soft HEAD~2
git status                    # Changes to be committed: ...
git commit -m "feat: 登录用例（含修正）"

# --mixed（默认）：撤销提交和 add，改动回到工作区，可以重新挑选
git reset HEAD~2
git status                    # Changes not staged for commit: ...
git add -p                    # 逐块挑选，拆成多个原子提交

# --hard：全部丢弃，工作区回到 HEAD~2 的样子
git reset --hard HEAD~2       # ⚠ 未提交的改动一并消失，不可恢复
```

### 二、reset 的日常用途（不止是回退）

```bash
# 1. 撤销 add（最常用）
git reset HEAD tests/test_login.py
# 等价于新语法：
git restore --staged tests/test_login.py

# 2. 合并最近 N 个提交成一个（squash 的手工版）
git reset --soft HEAD~5 && git commit -m "feat: 完整的短信登录能力"

# 3. 把本地分支强行对齐远程（放弃本地所有分歧）
git fetch origin
git reset --hard origin/main

# 4. 保留改动但换个分支提交（提错分支的补救）
git reset --soft HEAD~1       # 撤销提交，改动留在暂存区
git stash                     # 挪走
git switch correct-branch
git stash pop && git commit -m "..."
```

### 三、revert 实操

```bash
# 撤销一个普通提交
git revert a1b2c3d
# 会打开编辑器写 message，默认是 'Revert "原来的 message"'

# 不自动提交，想改动后再一起提交
git revert -n a1b2c3d
git revert -n 7e8f9a0
git commit -m "revert: 回滚优惠券功能（两个提交）"

# 撤销连续多个提交（注意顺序：从新到旧撤销更不容易冲突）
git revert --no-commit HEAD~3..HEAD
git commit -m "revert: 回滚最近三个提交"

# 撤销一个合并提交 —— 必须指定 -m
git revert -m 1 <merge-commit-sha>
```

**`-m 1` 是什么**：合并提交有两个父提交，`-m 1` 表示「以第一父提交为基准」，即保留主干那条线、撤销被合入的分支带来的改动。合并到 main 时第一父提交总是 main 那条线，所以基本都是 `-m 1`。

### 四、误操作救援：reflog

```bash
# 惨案：reset --hard 回退太多
git reset --hard HEAD~10

# 救援
git reflog
# 3f2a1b8 HEAD@{0}: reset: moving to HEAD~10
# c3d4e5f HEAD@{1}: commit: feat: 关键功能        ← 就是它
# b2c3d4e HEAD@{2}: commit: fix: typo

git reset --hard c3d4e5f       # 或 git reset --hard HEAD@{1}
```

reflog 记录了 **HEAD 的每一次移动**（commit / checkout / reset / rebase / merge 全都有），默认保留 90 天。所以只要提交过，基本救得回来。

也可以只救某个分支：

```bash
git reflog show feature/login-sms     # 看这条分支的移动记录
git branch rescue c3d4e5f             # 基于旧 commit 建一条救援分支
```

救不回来的只有一种情况：**从未 commit 过的工作区改动**（`git reset --hard` 或 `git restore .` 丢掉的）——它们从未进入对象库。

### 五、线上回滚的完整决策

```bash
# 情况 A：改动只在本地，没 push
git reset --hard HEAD~1                    # 直接抹掉

# 情况 B：已 push 到个人 feature 分支，没人基于它开发
git reset --hard HEAD~1
git push --force-with-lease                # 个人分支，可接受

# 情况 C：已 push 到 main / develop，别人已经拉了
git revert HEAD                            # 唯一正解
git push origin main

# 情况 D：整个特性合入后要下线（合并提交）
git revert -m 1 <merge-commit>
git push origin main
```

### 六、在 CI 中的应用

```groovy
// Jenkinsfile：一键回滚流水线
pipeline {
    agent any
    parameters {
        string(name: 'BAD_COMMIT', defaultValue: '', description: '要回滚的提交 SHA')
        booleanParam(name: 'IS_MERGE', defaultValue: false, description: '是否为合并提交')
    }
    stages {
        stage('Revert') {
            steps {
                sh '''
                    git config user.name  "ci-bot"
                    git config user.email "ci-bot@example.com"
                    git fetch origin main && git switch main && git reset --hard origin/main

                    if [ "${IS_MERGE}" = "true" ]; then
                        git revert -m 1 --no-edit "${BAD_COMMIT}"
                    else
                        git revert --no-edit "${BAD_COMMIT}"
                    fi
                '''
            }
        }
        stage('Verify') {
            steps {
                // 回滚也必须过测试，否则可能回滚出新问题
                sh 'pytest tests/smoke -v'
            }
        }
        stage('Push') {
            steps {
                sh 'git push origin main'
            }
        }
    }
    post {
        failure {
            echo '回滚失败或回滚后冒烟不通过，需人工介入'
        }
    }
}
```

注意 `git reset --hard origin/main` 在 CI 里是安全且推荐的——CI 的工作区是一次性的，用它保证起点干净。危险的是在**有人协作的分支上 reset 后强推**，两者不是一回事。

## 踩坑

1. **`reset --hard` 把未提交的改动一起丢了**。很多人只想「撤销上一个提交」，用了 `--hard`，结果工作区里另外几个文件的未提交改动也没了，reflog 救不回来。想撤销提交但保留改动，用 `--soft` 或默认的 `--mixed`。

2. **在共享分支上 reset + 强推**。同事的历史被覆盖，pull 出一堆重复提交，基于被删提交的工作全部失效。**团队分支一律开启保护，禁止强推**，从制度上杜绝。

3. **`git revert` 之后想重新合入原分支，发现合不进来**。因为 revert 也是一个提交，Git 认为「这个改动已经被处理过了」，再次 merge 时不会重新引入。解法是先 revert 掉那个 revert（`git revert <revert-commit>`），再继续开发。这在 Git Flow 里回滚整个特性后又想恢复的场景很常见，绕不过去。

4. **`git revert <merge-commit>` 报错**。缺 `-m 1`。而且要理解 `-m 1` 的后果：它撤销的是「被合入分支带来的所有改动」，不是「合并这个动作」。

5. **连续 revert 多个提交时顺序搞反**。应该**从新到旧**撤销（`git revert HEAD HEAD~1 HEAD~2`），从旧到新会因为后面的提交依赖前面的内容而不断冲突。

6. **`git reset --hard origin/main` 前忘了自己有本地提交**。分支指针被拉到远程位置，本地那几个提交变悬空。`git reflog` 能救，但先确认再动手总是更好：`git log origin/main..HEAD` 看看本地领先了什么。

7. **用 `reset` 想「回滚线上版本」**。生产环境回滚是部署层面的事（切回上个镜像 tag / 上个制品），不是 Git 层面的事。Git 的 revert 只是让代码库回到正确状态，真正的止血是重新部署上一个已知良好的产物（见 [[持续集成、持续交付与持续部署]]）。

8. **误以为 `git reset` 会删除远程分支上的提交**。reset 只动本地，不 push 的话远程毫发无损。反过来说，本地 reset 完看着干净了，`git push` 会被拒绝（non-fast-forward），这时千万别下意识加 `-f`。

9. **`git reset` 撤销了提交，但被 CI 的构建缓存坑了**。回退后 CI 仍用旧缓存构建出旧产物。回滚后要确认流水线跑的是新的 commit SHA，必要时清缓存（见 [[GitHub Actions matrix、缓存与 artifact]]）。

## 面试怎么答

**Q：`git reset` 和 `git revert` 的区别？**

A：reset 是移动分支指针，改写历史，被跳过的提交变成悬空对象；revert 是生成一个内容相反的新提交追加到末尾，历史只增不减。选择标准就一条：**提交推出去没有**。没推、或者只在自己的分支上，用 reset 最干净；已经推到 main 或者别人已经基于它开发了，只能用 revert，因为 reset 后必须强推，会覆盖同事的历史，导致他们 pull 出重复提交甚至丢工作。

**Q：`reset` 的三种模式分别动了什么？**

A：`--soft` 只移动分支指针，暂存区和工作区都不动，效果是「提交撤销了，改动还在暂存区等着重新提交」，常用来把最近几个提交 squash 成一个：`git reset --soft HEAD~5 && git commit`。`--mixed` 是默认，移指针加上重置暂存区，改动退回工作区，适合想重新挑选提交内容的场景。`--hard` 三个全动，工作区也被覆盖，未提交的改动直接消失且 reflog 救不回来——这是唯一真正危险的模式。

**Q：已经 push 到 main 的错误提交怎么撤销？**

A：`git revert <sha>` 然后正常 push。它不改写历史，对所有人安全。如果撤销的是合并提交，要加 `-m 1` 指定以第一父提交为基准。要注意一个后续陷阱：revert 之后如果还想把原分支重新合进来，Git 会认为这些改动已经处理过而不再引入，得先 revert 掉那个 revert 提交。另外如果是线上事故，Git 层面的 revert 只是让代码库回到正确状态，真正止血还是要在部署层面切回上一个已知良好的镜像。

**Q：不小心 `reset --hard` 了怎么办？**

A：先分清丢的是什么。如果是已经 commit 过的提交，`git reflog` 里能找到——它记录了 HEAD 的每一次移动，默认保留 90 天，找到 SHA 后 `git reset --hard <sha>` 或者 `git branch rescue <sha>` 就能恢复。如果丢的是从未提交过的工作区改动，那就真没了，因为它们从未进入 Git 对象库。所以我的习惯是：任何有风险的操作之前先 `git stash -u` 或者随手打个 wip 提交，只要进了对象库就有得救。

## 参考

- [git-reset 文档](https://git-scm.com/docs/git-reset)
- [git-revert 文档](https://git-scm.com/docs/git-revert)
- [Pro Git · 重置揭密](https://git-scm.com/book/zh/v2/Git-工具-重置揭密)
- 相关笔记：[[Git 常用命令与四区模型]]、[[Git merge 与 rebase]]、[[Git stash 与 cherry-pick]]、[[持续集成、持续交付与持续部署]]
