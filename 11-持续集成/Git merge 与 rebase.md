---
created: 2026-07-31
tags: [持续集成/Git]
---

# Git merge 与 rebase

> 两条命令得到的**代码内容**完全一样，差别只在**历史长什么样**——以及谁会因此被坑。

![[assets/git-merge-vs-rebase.svg]]
*图示：merge 保留分叉并生成一个有两个父提交的合并点 M；rebase 把 X、Y 重放到 D 之后变成全新的 X'、Y'，历史成一条直线但 SHA 全变了。*

## 概念

### 两者到底做了什么

设有历史：`A—B—C—D` 是 main，`B—X—Y` 是 feature。

**`git merge main`（在 feature 上）**：Git 找出 feature 和 main 的**共同祖先** B，做三方合并（three-way merge：base=B、ours=Y、theirs=D），产生一个新的合并提交 M。M 的特殊之处是**有两个父提交**（Y 和 D）。原来的 X、Y、D 一个都没变。

**`git rebase main`（在 feature 上）**：Git 把 X、Y 相对于 B 的改动算成补丁，然后从 D 开始**逐个重新应用**这些补丁，生成 X'、Y'。注意是「生成」——X' 的父提交变成了 D，父提交变了则哈希必然变，所以 **X' 是一个全新的 commit，X 变成了悬空对象**。

一句话概括：**merge 是「记录事实：这两条线在此汇合」，rebase 是「伪造历史：假装我一开始就是从最新的 main 出发写的」。**

### 为什么 rebase 后 SHA 一定会变

commit 的 SHA-1 是对以下内容整体哈希的：

```text
tree      <目录快照的哈希>
parent    <父提交的 SHA>
author    <作者 + 时间戳>
committer <提交者 + 时间戳>

<commit message>
```

`parent` 是哈希输入的一部分。rebase 改变了父提交，SHA 必然改变——这不是 Git 的选择，是内容寻址存储的数学后果。

这条推论直接解释了两件事：

1. rebase 之后本地和远程「分叉」了，普通 `push` 会被拒绝，必须 `--force-with-lease`。
2. 别人如果基于你原来的 X、Y 开发过，他手上的父提交在你的新历史里已经不存在了，他一 pull 就会得到重复提交，一片混乱。这就是「**不要 rebase 公共分支**」这条黄金法则的完整推导。

### fast-forward：merge 的特殊情况

如果 main 从分叉点之后没有任何新提交（即 main 是 feature 的祖先），Git 不会创建合并提交，而是直接把 main 的指针**前移**到 feature——这叫 fast-forward。

```text
merge 前：A—B—X—Y (feature)
              ↑ main 在 B
merge 后：A—B—X—Y
                ↑ main 直接移到 Y，没有新 commit
```

fast-forward 的问题是历史上丢失了「这几个提交是一个特性」的信息。所以团队规范里常要求 `--no-ff` 强制生成合并提交（见 [[Git 分支模型：Git Flow 与 trunk-based]]）。

### 第三条路：squash

`git merge --squash` 或平台上的 Squash and merge：把 feature 上的 N 个提交压成**一个**新 commit 合到 main。

三种方式的对比：

| 方式 | main 上留下 | 分叉可见 | SHA 变化 | 适合 |
|------|------------|---------|---------|------|
| `merge --no-ff` | N+1 个提交 | 是 | 否 | 需要保留完整开发过程 |
| `rebase` + ff | N 个提交 | 否 | 是 | 提交本身就干净、有价值 |
| `squash` | 1 个提交 | 否 | 是 | 过程提交是垃圾（"fix"、"再改改"） |

## 用法

### 一、merge：把 main 的更新拿进 feature

```bash
git switch feature/login-sms
git fetch origin
git merge origin/main
# 有冲突就解，解完：
git add .
git merge --continue          # 或 git commit
# 想放弃这次合并回到干净状态：
git merge --abort
```

### 二、rebase：把 feature 挪到 main 最新点之后

```bash
git switch feature/login-sms
git fetch origin
git rebase origin/main

# 冲突时 rebase 会停在某个 commit 上（注意：是逐个 commit 停）
# 解完冲突后：
git add .
git rebase --continue         # 继续下一个 commit
git rebase --skip             # 跳过当前 commit（确认它的改动已无意义时）
git rebase --abort            # 整个放弃，回到 rebase 前

# rebase 后本地历史被改写，推送需要：
git push --force-with-lease
```

**`--force-with-lease` 而不是 `--force`**：前者会检查「远程当前的 commit 是否还是我上次 fetch 到的那个」，如果同事在这期间推过东西，它会拒绝而不是覆盖。`--force` 则无条件覆盖，能把同事一整天的工作抹掉。个人分支强推只准用 `--force-with-lease`。

### 三、交互式 rebase：提交历史的手术刀

这是 rebase 最高频、最有价值的用法，跟「同步主干」无关。

```bash
git rebase -i HEAD~5          # 整理最近 5 个提交
```

打开的编辑器内容：

```text
pick a1b2c3d feat: 短信登录接口
pick d4e5f6a fix: 忘了加参数校验
pick 7g8h9i0 fix: typo
pick j1k2l3m feat: 短信登录用例
pick n4o5p6q wip

# 可用指令：
# p, pick   = 保留
# r, reword = 保留但改 message
# e, edit   = 停下来让你修改这个提交的内容
# s, squash = 与上一个合并，保留两条 message
# f, fixup  = 与上一个合并，丢弃本条 message
# d, drop   = 删除该提交
```

改成：

```text
pick a1b2c3d feat: 短信登录接口
fixup d4e5f6a fix: 忘了加参数校验
fixup 7g8h9i0 fix: typo
pick j1k2l3m feat: 短信登录用例
drop n4o5p6q wip
```

结果：5 个提交变成 2 个语义清晰的提交，`fix: typo` 这类噪音全部并进对应的功能提交。**开 PR 前做一次，review 的人会感谢你。**

配套技巧——写代码时随手 `--fixup`，最后一键自动整理：

```bash
git commit --fixup a1b2c3d        # 生成 "fixup! feat: 短信登录接口"
git rebase -i --autosquash HEAD~5 # 自动把 fixup 排到对应提交下方并标 fixup
```

### 四、rebase 冲突的正确处理姿势

merge 冲突只解一次；**rebase 冲突可能解 N 次**（N = 被重放的提交数），因为它是逐个提交重放的。这是很多人讨厌 rebase 的原因。

两个减负手段：

```bash
# 1. 开启 rerere：记住你的冲突解法，下次同样冲突自动套用
git config --global rerere.enabled true

# 2. 重放前先把自己的提交压少一点，冲突次数自然减少
git rebase -i HEAD~8       # 先 squash 成 2 个
git rebase origin/main     # 再重放，最多解 2 次
```

`rerere`（reuse recorded resolution）在长期维护分支、反复 rebase 主干的场景下能省掉大量重复劳动。

### 五、团队常见的组合策略

```bash
# 策略：本地 rebase 保持线性，合入主干 merge --no-ff 留痕
git switch feature/login-sms
git fetch origin && git rebase origin/main    # 私有分支，随便 rebase
git rebase -i origin/main                     # 整理提交
git push --force-with-lease

# PR 通过后（由平台执行，或本地）：
git switch main
git merge --no-ff feature/login-sms
```

配置固化到仓库，减少口头约定：

```bash
git config --global pull.rebase true            # pull 默认 rebase，不产生垃圾合并提交
git config --global rebase.autoStash true       # rebase 前自动 stash 工作区改动
git config --global merge.conflictstyle zdiff3  # 冲突标记里带上共同祖先版本，更好判断
```

`zdiff3` 冲突样式非常值得开，它会多显示一段 base：

```text
<<<<<<< HEAD
timeout = 30
||||||| base
timeout = 10
=======
timeout = 60
>>>>>>> origin/main
```

有了 base 就能看出「我从 10 改到 30，对方从 10 改到 60」，而不是对着两个值瞎猜（详见 [[Git 冲突解决]]）。

### 六、在 CI 中的体现

流水线里经常需要「基于最新主干验证」，两种写法：

```groovy
stage('Rebase onto main') {
    steps {
        sh '''
            git fetch origin main
            # CI 上 rebase 失败说明有冲突，直接让流水线红灯，别硬合
            git rebase origin/main || {
                echo "存在冲突，请本地 rebase 后重推"
                git rebase --abort
                exit 1
            }
        '''
    }
}
```

```yaml
# GitHub Actions：PR 的 merge commit 其实已经是「合并后」的状态
on:
  pull_request:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      # actions/checkout 在 pull_request 事件下默认检出的是 refs/pull/N/merge
      # 即「PR 合进 main 之后」的虚拟提交，天然验证了合并结果
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - run: pytest tests/
```

这是 GHA 的一个隐藏知识点：`pull_request` 事件检出的不是你的分支 HEAD，而是 Git 预先算好的合并结果。所以 CI 绿灯代表「合进去之后是绿的」，比只测分支本身更有意义。

## 踩坑

1. **在共享分支上 rebase**。有人对 `develop` 做了 rebase 并强推，所有基于它开发的同事一 pull 就出现重复提交和大量假冲突，只能全员 `git reset --hard origin/develop` 重来，未推送的工作全丢。**铁律：只 rebase 自己的、没推给别人用的分支。**

2. **rebase 后用 `git push -f`（不带 lease）覆盖同事提交**。同事在你的分支上帮你改过一处，被你无声抹掉，几天后才发现。永远用 `--force-with-lease`。

3. **rebase 中途冲突解到一半忘了自己在哪**。`git status` 会明确告诉你 "interactive rebase in progress; onto abc1234, Last command done...". 不确定就 `git rebase --abort` 回到原点重来，代价只是重解一次冲突。

4. **rebase 把别人的提交也带过来了**。执行 `git rebase main` 时若当前分支包含别人合进来的提交，这些提交会被重放成新 SHA，导致「同一个改动在历史里出现两次」。用 `git rebase --onto` 精确指定重放区间：

   ```bash
   # 只把 B..feature 这段重放到 main 上，跳过之前误合进来的部分
   git rebase --onto main B feature
   ```

5. **squash merge 后本地分支再往主干 rebase，产生重复冲突**。因为 squash 生成的是全新 commit，Git 认不出你分支上的原提交已经合过了。正确做法是 squash merge 后**直接删除本地分支**，需要继续开发就从新 main 重新拉。

6. **合并提交的 revert 姿势不对**。`git revert <merge-commit>` 会报 "commit is a merge but no -m option was given"，因为 Git 不知道你要撤销相对哪个父提交的改动。要写 `git revert -m 1 <merge-commit>`（`-m 1` 表示保留第一父提交即主干那条线）。后续这个特性想重新合入时还要先 revert 掉这个 revert，是 Git Flow 里的经典陷阱。

7. **`pull.rebase` 没配，历史里全是 "Merge branch 'main' of github.com:..."**。这种自动合并提交没有任何信息量，还会把 `git log --graph` 搅成一团。全局配 `pull.rebase true`。

8. **语义冲突：合上了但逻辑错了**。A 把函数 `get_token()` 改名成 `fetch_token()`，B 在自己分支新增了三处 `get_token()` 调用。两边改的不是同一行，Git 自动合并成功、无冲突，但代码直接 `AttributeError`。**Git 只懂文本不懂语义，这就是为什么合并后必须跑 CI**，而不是「没冲突就等于没问题」。

## 面试怎么答

**Q：`git merge` 和 `git rebase` 的区别？**

A：merge 是三方合并，找共同祖先，产生一个有两个父提交的合并提交，历史保留分叉，是对「什么时候合的」这个事实的如实记录。rebase 是把我分支上的提交依次重放到目标分支的最新提交之后，历史变成线性，但因为父提交变了，每个提交的 SHA 都会变，本质上是生成了一批新提交、丢弃了旧的。代码结果一样，区别在历史形态和安全性：merge 绝对安全，rebase 改写历史，只能用在没有共享出去的分支上。

**Q：团队里该用哪个？**

A：我一般用组合策略。私有的 feature 分支同步主干用 rebase，保持线性、避免历史里塞满无意义的合并提交；开 PR 前用 `rebase -i` 把 "fix typo"、"再改改" 这类过程提交 squash 掉，让 review 更清爽。合入主干时用 merge --no-ff 或平台的 squash merge，前者保留特性边界方便整体回滚，后者让主干一个需求一个 commit。核心原则就一条：**只对没推给别人用的提交做 rebase**，已共享的历史一律 merge。

**Q：为什么说 rebase 危险？**

A：因为它改写历史。commit 的 SHA 包含父提交，rebase 换了父提交，SHA 就变了，本地和远程会分叉，必须强推。如果这条分支别人也在用，他们本地的父提交在新历史里已经不存在，pull 之后会出现重复提交和满屏假冲突，很容易在解冲突过程中丢代码。所以公共分支绝对不 rebase，个人分支强推也只用 `--force-with-lease`，它会检查远程有没有被别人更新过。

**Q：合并没有冲突，是不是就说明合并是安全的？**

A：不是。Git 只做文本层面的合并，判断不了语义。典型例子：A 把某个函数改了名，B 在自己分支新增了对旧函数名的调用，两人改的不是同一行，Git 会顺利合并，但代码直接跑不起来。这类叫语义冲突。所以合并之后必须跑一遍完整 CI，而且 PR 门禁最好开「require branches to be up to date」，强制先 rebase 到最新主干再跑一次，验证的是合并后的状态而不是分支本身。这也是 GitHub Actions 在 `pull_request` 事件下默认检出合并结果而不是分支 HEAD 的原因。

## 参考

- [Pro Git · 变基](https://git-scm.com/book/zh/v2/Git-分支-变基)
- [git-merge 文档](https://git-scm.com/docs/git-merge) / [git-rebase 文档](https://git-scm.com/docs/git-rebase)
- 相关笔记：[[Git 常用命令与四区模型]]、[[Git 冲突解决]]、[[Git 分支模型：Git Flow 与 trunk-based]]、[[Git reset 与 revert]]
