---
created: 2026-07-31
tags: [面试题/持续集成]
---

# git merge 与 git rebase 的区别

> 一个保留真实历史，一个重写成直线。选哪个取决于「这个分支有没有被别人用」。

## 30 秒回答骨架

**本质区别**：`merge` 是**合并**，生成一个新的合并提交，把两条历史连起来，分叉结构原样保留；`rebase` 是**变基**，把当前分支的提交逐个「摘下来重放」到目标分支的最新提交之后，**生成的是全新的 commit（哈希变了）**，历史变成一条直线。

**怎么选**：

- **公共分支（main / develop / release）只用 merge**。rebase 会重写历史，别人已经拉过的提交哈希变了，再 pull 会冲突甚至丢代码。
- **自己的特性分支同步主干进展用 rebase**，保持历史线性、好 review；合回主干时再用 `merge --no-ff`，让每个特性有一个明确的合并点。
- 团队约定一句话：**「只对没有推送、或只有自己在用的分支做 rebase」**——这就是 rebase 的黄金法则。

## 展开

### 图示对比

初始状态：

```text
      A---B---C   feature
     /
D---E---F---G     main
```

`git checkout feature && git merge main`：

```text
      A---B---C---M   feature
     /           /
D---E---F-------G     main
```

多出一个合并提交 M（有两个父提交）。A、B、C 的哈希不变，历史真实但有分叉。

`git checkout feature && git rebase main`：

```text
              A'--B'--C'   feature
             /
D---E---F---G               main
```

A、B、C 被**重新应用**到 G 之后，变成全新的 A'、B'、C'（内容一样但哈希不同）。历史是直线，但「feature 是从 E 拉出来的」这个事实丢失了。

### 为什么公共分支不能 rebase

因为 rebase 生成的是新对象。假设同事已经基于 C 做了工作，你把 feature rebase 之后强推：

```bash
git rebase main
git push --force        # 危险
```

同事再 `git pull` 时，本地的 C 和远端的 C' 内容相同但哈希不同，Git 认为是两条不同的历史，会产生大量诡异冲突；如果他处理不当，很容易把自己的提交弄丢。

如果确实要推 rebase 后的分支，用 `--force-with-lease` 而不是 `--force`：

```bash
git push --force-with-lease
```

它会先检查远端分支是否还停在你上次见到的位置，**如果别人期间推了新东西就拒绝推送**，能防住覆盖他人提交这类事故。

### 常用组合：先 rebase 再 merge --no-ff

我们团队的分支流程是这样的：

```bash
# 1. 特性分支开发期间，定期同步主干（保持线性、提前暴露冲突）
git checkout feature/coupon
git fetch origin
git rebase origin/main
# 有冲突就逐个解决
git add <file>
git rebase --continue        # 放弃则 git rebase --abort

# 2. 开发完成，合回主干时保留特性边界
git checkout main
git merge --no-ff feature/coupon -m "feat: 优惠券叠加规则"
```

`--no-ff` 强制生成合并提交。默认的 fast-forward 会把 feature 的提交直接接到 main 上，看不出「这几个提交属于同一个特性」，回滚时也不能一条命令撤掉整个特性。

`git log --graph --oneline` 出来的效果就是主干一条清晰的主线，每个特性是一个鼓包，历史既干净又能追溯。

### 其他几个高频命令的区别

**`reset` vs `revert`**：

| 命令 | 行为 | 是否改历史 | 适用 |
|------|------|-----------|------|
| `git reset --soft HEAD~1` | 撤销提交，改动留在暂存区 | 是 | 本地改提交信息或重新组织提交 |
| `git reset --mixed HEAD~1` | 撤销提交，改动留在工作区（默认） | 是 | 本地重新 add |
| `git reset --hard HEAD~1` | 撤销提交并丢弃改动 | 是 | 本地确认不要的改动，**危险** |
| `git revert <commit>` | 生成一个反向提交抵消原提交 | 否 | **已推送的提交**，公共分支唯一正确选择 |

**已推送的提交怎么撤销？答案永远是 `revert`**，因为它不改历史，别人 pull 下来就是一个正常的新提交。

`reset --hard` 误删了怎么救？`git reflog` 找到之前的 HEAD 位置，再 `git reset --hard <那个哈希>`。reflog 默认保留 90 天，这是 Git 的后悔药。

**`cherry-pick`**：把某个提交单独摘到当前分支，典型场景是 hotfix 在 main 上修完，要同步一份到 release 分支。

**`stash`**：临时保存工作区改动去处理别的事。`git stash push -m "wip"`、`git stash list`、`git stash pop`。注意 `stash` 默认不含未跟踪文件，要加 `-u`。

## 可能被追问的点

- **rebase 时冲突为什么要解决好几次？** 因为它是**逐个提交重放**的，每个提交都可能和新基底冲突。可以用 `git rerere`（记录冲突解决方案自动复用）减轻，或者先把碎提交 squash 成一个再 rebase。
- **`git pull` 默认是什么行为？** 等价于 `git fetch + git merge`，会产生「Merge branch 'main' of ...」这种噪音提交。建议配 `git config --global pull.rebase true` 改成 fetch + rebase，历史干净得多。
- **`merge --squash` 和 `--no-ff` 的区别？** `--squash` 把整个分支的改动压成一个提交（不产生合并关系，分支历史丢失），适合特性分支里有大量「fix typo」这类碎提交的情况；`--no-ff` 保留全部提交并加一个合并点。GitHub 的 Squash and merge 就是前者。
- **Git Flow 和 trunk-based 怎么选？** Git Flow 分支多（master/develop/feature/release/hotfix），适合有明确版本发布周期的产品；trunk-based 只有主干加短生命周期分支，配合 feature flag，适合持续部署的团队。**关键是问清对方团队的发布节奏再回答，不要背定义。**
- **CI/CD 里 merge 与 rebase 有什么影响？** rebase 后哈希变化会让基于 commit 的构建缓存失效；合并策略也影响「哪个提交触发了哪次构建」的追溯。另外 `--no-ff` 的合并点是很好的**流水线触发点和回滚锚点**。
- **持续集成、持续交付、持续部署的区别？** CI 是频繁合入主干并自动构建+测试；持续交付（Continuous Delivery）是每次变更都构建出**随时可发布**的产物，发不发由人决定；持续部署（Continuous Deployment）是通过所有门禁后**自动发到生产**。区别在最后一公里有没有人工卡点。

## 结合自己项目的例子

商城中台的自动化框架仓库最早是「谁都往 main 上直推」的状态，我接手后推动了一次分支规范落地，中间踩过一次 rebase 的坑，讲这个比讲定义有说服力得多。

**踩的坑**：有次我在 `feature/allure-report` 分支上开发，做了 6 个提交并推到了远端，另一个同事基于它做报告样式。我为了同步主干上的一个公共方法改动，直接 `git rebase origin/main` 然后 `git push --force`。同事第二天 pull 时炸了——他本地基于我旧提交的 3 个 commit 和远端对不上，他自己 `reset --hard` 想"清爽一下"，把自己一天的工作弄丢了（后来用 `git reflog` 救回来了，但折腾了一个多小时）。

**复盘后定的规范**（写进了仓库的 `CONTRIBUTING`）：

1. **公共分支保护**：GitHub 上给 `main` 开启分支保护，禁止 force push、禁止直推，必须走 PR 且至少 1 人 approve。
2. **rebase 只用于个人分支**：分支名带 `feature/<姓名>-<功能>`，一旦有第二个人 checkout，就改用 merge 同步。
3. **force push 一律用 `--force-with-lease`**：在团队 Git 别名里直接配好 `git pf`，杜绝裸 `--force`。
4. **合回主干统一 `--no-ff`**，PR 标题就是合并提交信息，格式走 Conventional Commits（`feat:`/`fix:`/`test:`），后续可以自动生成 changelog。

**配套的 CI 门禁**：PR 触发的 GitHub Actions 里跑三件事，任一失败就不允许合并。

```yaml
name: PR Check
on:
  pull_request:
    branches: [main]

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: 安装依赖
        run: pip install -r requirements.txt
      - name: 代码规范
        run: ruff check .
      - name: 冒烟用例
        run: pytest -m smoke -n 4 --maxfail=1
      - name: 框架自测覆盖率门禁
        run: pytest tests/unit --cov=framework --cov-fail-under=70
```

第三条「框架自测」是我特意加的：**自动化框架本身也是代码，它的工具层（断言封装、数据加载器、加解密工具）必须有单测**，否则框架出 bug 会让所有业务用例集体误报，那种事故最难查。

**效果**：规范落地半年，主线历史从原来一团乱麻变成清晰可读，`git log --graph` 一眼能看出每个特性的边界；再没出现过强推覆盖或丢代码的事故；框架的工具层单测覆盖率维持在 78%，期间拦下过 4 次会导致全量误报的改动。

面试讲这个的时候我会强调：**我不是背下了 merge 和 rebase 的区别，而是因为团队真的出过事故，才理解为什么黄金法则是「不对公共分支 rebase」。**

## 参考

- 相关笔记：[[11-持续集成]]、[[05-自动化测试框架]]
