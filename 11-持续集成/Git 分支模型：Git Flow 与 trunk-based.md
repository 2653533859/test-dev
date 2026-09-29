---
created: 2026-07-31
tags: [持续集成/Git]
---

# Git 分支模型：Git Flow 与 trunk-based

> 分支模型不是「哪个更先进」的技术选择，而是「你多久发一次版」决定的工程约束。

![[assets/git-branch-models.svg]]
*图示：Git Flow 靠 develop / release / feature 多条长命分支承载版本节奏；trunk-based 只留主干，特性分支活不过一天，靠 PR + CI 保证主干随时可发。*

## 概念

### 分支模型要解决的核心矛盾

一个团队同时面临三件互相打架的事：

1. 多人并行开发，代码要隔离，不能互相踩
2. 集成要尽早，隔离越久合并越痛
3. 线上要稳定，随时可能来紧急修复

分支模型就是在这三者之间的取舍。**分支存在的时间越长，隔离越好，但集成越痛**——这是全部权衡的根源。

有个经验公式可以感受一下：合并冲突的代价大致随分支存活时间**超线性**增长。分支活 1 天，冲突通常是几行；活 2 周，冲突可能涉及重构过的整个模块，还伴随语义冲突（代码能合上但逻辑错了，编译器和 Git 都发现不了）。

### Git Flow：为「有版本号的发布」设计

Vincent Driessen 在 2010 年提出，五类分支：

| 分支 | 生命周期 | 从哪来 | 合到哪去 |
|------|---------|--------|---------|
| `main` | 永久 | — | — |
| `develop` | 永久 | main | main（经 release） |
| `feature/*` | 数天～数周 | develop | develop |
| `release/*` | 数天 | develop | main + develop |
| `hotfix/*` | 数小时 | main | main + develop |

它的隐含前提是：**发布是一个事件**。有明确的封版、提测、回归、上线节点，`release` 分支就是那段「只修 bug 不加功能」的封版期。

适用场景：客户端 App（要过应用市场审核）、私有化部署产品（要维护 v1.2 / v2.0 多个版本）、有正式版本号和发布窗口的系统。

### Trunk-based：为「持续发布」设计

只有一条长命分支 `main`（trunk）。所有人从 main 拉短分支，**24 小时内**必须合回去；或者干脆直接往 main 提交（大厂内部单仓模式）。

核心约束有三条，缺一条就跑不起来：

1. **每次合入前必须过全量 CI**——没有 CI 的 trunk-based 就是灾难。
2. **未完成的功能靠特性开关（feature flag）藏起来**，而不是靠分支藏起来。代码合进 main 但开关关着，线上不受影响。
3. **main 必须永远可发布**，红灯是最高优先级事故。

适用场景：SaaS、Web 服务、内部平台，一天发布多次。

### 为什么 CI 天然偏向 trunk-based

「持续集成」这个词的原义就是 **continuous integration——持续地把代码集成到主干**。如果一个 feature 分支活了两周才合，那两周里 CI 跑的是「分支上的集成」，而不是「和主干的集成」，真正的集成风险被推迟到了最后一刻，这从定义上就不叫 CI（参见 [[持续集成、持续交付与持续部署]]）。

Git Flow 里 `develop` 就是为了缓解这个问题——它是一条「准主干」，让 feature 至少能早点跟别人的代码碰面。但代价是多了一层同步成本和一个永远要往回合的 `release`。

## 用法

### 一、Git Flow 完整走一遍

```bash
# 1. 从 develop 开特性分支
git switch develop
git pull --rebase
git switch -c feature/login-sms

# 2. 开发中定期同步 develop，避免最后大冲突
git fetch origin
git rebase origin/develop        # 短分支用 rebase 保持线性

# 3. 完成后合回 develop，用 --no-ff 保留「这是一个特性」的信息
git switch develop
git merge --no-ff feature/login-sms -m "feat: 短信登录"
git push origin develop
git branch -d feature/login-sms

# 4. 封版：拉 release 分支，之后 develop 可以继续接新功能
git switch -c release/1.4.0 develop
# ...测试期间只在 release 分支修 bug...
git commit -am "fix: 修复短信验证码倒计时"

# 5. 上线：合进 main 打 tag，同时把 release 上的修复合回 develop
git switch main
git merge --no-ff release/1.4.0
git tag -a v1.4.0 -m "1.4.0 正式发布"
git push origin main --tags
git switch develop
git merge --no-ff release/1.4.0     # 关键！否则 bug 修复在下个版本会丢
git branch -d release/1.4.0

# 6. 线上急救
git switch -c hotfix/1.4.1 main
git commit -am "fix: 支付回调空指针"
git switch main && git merge --no-ff hotfix/1.4.1 && git tag v1.4.1
git switch develop && git merge --no-ff hotfix/1.4.1   # 同样要回合
```

**`--no-ff` 为什么重要**：不加它时，如果 develop 没有新提交，Git 会做 fast-forward——直接把指针前移，历史上看不出「这几个提交属于同一个特性」。加了 `--no-ff` 会强制生成合并提交，`git log --graph` 上能看到清晰的特性泡泡，回滚整个特性时也只需 `revert -m 1 <merge-commit>`。

### 二、Trunk-based 走一遍

```bash
# 1. 从 main 拉短分支，命名带上工号/需求号方便追溯
git switch main
git pull --rebase
git switch -c tb/wang-4821-sms-login

# 2. 小步提交，当天完成
git commit -am "feat: 短信登录接口 + 用例"

# 3. 推上去开 PR，CI 自动跑；期间随时 rebase 主干
git push -u origin tb/wang-4821-sms-login
git fetch origin && git rebase origin/main && git push --force-with-lease

# 4. CI 全绿 + review 通过 → squash merge 进 main
#    squash 让 main 上一个需求 = 一个 commit，历史极干净
```

`--force-with-lease` 比 `--force` 安全：如果远程分支在你上次 fetch 之后被别人推过新东西，它会拒绝推送，而不是无声覆盖。**个人分支强推只准用这个**。

### 三、特性开关：trunk-based 的配套设施

未完成的功能怎么合进 main 而不影响线上？用开关包起来：

```python
# config/feature_flags.py —— 简化示例，生产上通常接配置中心
import os

FLAGS = {
    "sms_login": os.getenv("FF_SMS_LOGIN", "off") == "on",
}

def enabled(name: str) -> bool:
    return FLAGS.get(name, False)
```

```python
# api/login.py
from config.feature_flags import enabled

def login(payload):
    if enabled("sms_login") and payload.get("type") == "sms":
        return login_by_sms(payload)      # 新逻辑，线上默认关闭
    return login_by_password(payload)     # 老逻辑
```

对测试同学的直接影响：**用例也要按开关分组**，并且两条分支都要覆盖。

```python
# tests/test_login.py
import os
import pytest

@pytest.mark.skipif(os.getenv("FF_SMS_LOGIN") != "on", reason="短信登录开关未开")
def test_login_by_sms(client):
    resp = client.post("/login", json={"type": "sms", "phone": "13800000000", "code": "1234"})
    assert resp.status_code == 200

def test_login_by_password(client):
    """开关关闭时的老路径，必须永远保持绿灯"""
    resp = client.post("/login", json={"type": "pwd", "user": "u1", "pwd": "p1"})
    assert resp.status_code == 200
```

CI 里跑两轮：一轮开关全关（验证线上现状不被破坏），一轮开关全开（验证新功能）。

```yaml
# .github/workflows/ci.yml 片段
jobs:
  test:
    strategy:
      matrix:
        flags: ["off", "on"]
    runs-on: ubuntu-latest
    env:
      FF_SMS_LOGIN: ${{ matrix.flags }}
    steps:
      - uses: actions/checkout@v4
      - run: pytest tests/ -v
```

### 四、分支保护：让规则不靠自觉

无论哪种模型，主干分支都必须开保护规则，否则模型只是文档。以 GitHub 为例：

```text
Settings → Branches → Branch protection rules → main
  [x] Require a pull request before merging
      [x] Require approvals: 1
  [x] Require status checks to pass before merging
      [x] ci / build
      [x] ci / api-test
      [x] sonarqube
  [x] Require branches to be up to date before merging
  [x] Do not allow bypassing the above settings   ← 管理员也不能绕
```

「Require branches to be up to date」这一条经常被忽略：不勾的话，A 和 B 各自基于旧 main 通过了 CI，先后合入后，**合并结果**这个从未被测试过的状态可能是坏的。勾上后要求先 rebase 到最新 main 再跑一次 CI（详见 [[质量门禁设计与失败即阻断]]）。

### 五、分支命名规范

```text
feature/<需求号>-<简述>     feature/4821-sms-login
bugfix/<缺陷号>-<简述>      bugfix/9012-token-expire
hotfix/<版本>-<简述>        hotfix/1.4.1-pay-npe
release/<版本>              release/1.4.0
test/<简述>                 test/api-case-refactor
```

命名带需求号的实际收益：CI 可以从分支名解析出需求号，自动回写测试结果到需求管理系统；出问题时也能一眼追溯到需求上下文。

## 踩坑

1. **Git Flow 里 hotfix 忘记回合 develop**。线上紧急修复只合进了 main，下个版本从 develop 出来，同一个 bug 原样复发。这是 Git Flow 最经典的事故，必须靠流程卡死（CI 检查 main 上的 commit 是否都在 develop 里）。

2. **feature 分支活了三周**。合并时冲突几百处，解冲突过程中手抖删掉别人的代码，还全是「能编译通过但逻辑错」的语义冲突。补救成本远高于每天 rebase 的成本。经验值：**分支超过 3 天没合，就该拆需求了**。

3. **没有特性开关就硬上 trunk-based**。半成品功能合进 main，线上直接暴露入口。trunk-based 不是「随便往 main 推」，开关是它的前置条件。

4. **测试环境和分支绑死**。「test 分支部署到测试环境」这种做法在 trunk-based 下会崩：短分支太多，环境不够分。正确做法是按 PR 动态起环境（Docker Compose / K8s namespace，见 [[docker compose 编排测试环境]]），或者用一套环境 + 数据隔离。

5. **squash merge 之后本地分支变「未合并」**。squash 会生成一个全新 commit，Git 认不出原分支已合并，`git branch -d` 报错要求用 `-D`。这是正常现象，不是出了问题。

6. **release 分支上的改动直接改到了 main**。有人图省事在 main 上热改再打 tag，导致 main 和 release 分叉，后续合并一片混乱。规则：**main 只接受来自 release / hotfix 的合并，永远不直接提交**。

7. **自动化测试仓库和被测代码仓库分支不对齐**。被测服务在 `release/1.4.0`，测试仓库还在 main，跑出来一堆「接口不存在」的假失败。解法：测试仓库同步打相同分支/tag，或者在流水线参数里显式指定两边的版本（见 [[Jenkins 参数化构建与触发方式]]）。

8. **长期分支上的 `git pull` 产生「合并的合并」**。历史图变成一团意大利面，`git log --graph` 完全没法看，也无法 revert。解法：本地同步统一用 `git pull --rebase`。

## 面试怎么答

**Q：你们团队用什么分支模型？为什么？**

A：先反问业务形态再回答——这题没有标准答案，答错前提就废了。我们是内部测试平台，一天可能发布多次，用的是 trunk-based：从 main 拉短分支，当天合回，靠 PR + CI 门禁保证 main 随时可发，没做完的功能用特性开关关掉。如果是要过应用市场审核、需要同时维护多个版本的客户端，我会选 Git Flow，因为它的 release 分支正好对应封版回归期，hotfix 分支能在不带上 develop 新功能的前提下紧急修线上。核心判断标准是**发布节奏**：发布是「持续的流」就 trunk-based，是「离散的事件」就 Git Flow。

**Q：Git Flow 有什么问题？**

A：三个。第一，分支层级多，feature → develop → release → main，一个改动要合三次，hotfix 还要回合 develop，漏合就会导致 bug 复发，这是最常见的事故。第二，feature 分支容易活得太久，集成推迟到最后，跟持续集成的理念是相悖的。第三，对测试不友好——测试环境要对应哪条分支说不清，容易出现「测的是 develop、发的是 release」这种版本错位。所以现在很多团队简化成 GitHub Flow：只有 main + 短分支 + PR。

**Q：trunk-based 怎么保证 main 不被搞坏？**

A：靠三层。第一层是 PR 门禁，把构建、单测覆盖率、静态扫描、接口冒烟设成 required status check，不过就是 merge 按钮置灰，管理员也不能绕。第二层是「require branches to be up to date」，强制先 rebase 到最新 main 再跑一次 CI，避免两个各自绿灯的 PR 合起来变红。第三层是特性开关，半成品代码可以合进去但线上不生效，一旦发现问题关开关就能止血，不用回滚发版。加上短分支本身冲突小，实际比长分支更稳。

**Q：`git merge --no-ff` 为什么在分支模型里很重要？**

A：不加 `--no-ff` 时 Git 会 fast-forward，直接前移指针，历史上看不出这几个提交属于同一个特性。加了会强制产生合并提交，一是 `git log --graph` 能看清特性边界，二是要回滚整个特性时可以直接 `git revert -m 1 <merge-commit>` 一次性撤销，而不是逐个 revert。Git Flow 明确要求 feature 合 develop、release 合 main 都用 `--no-ff`。反过来在 trunk-based 里更常用 squash merge，让 main 上「一个需求一个 commit」，也是同样的动机——让历史可读、可回滚。

## 参考

- [Pro Git · 分支管理](https://git-scm.com/book/zh/v2/Git-分支-分支的新建与合并)
- [Trunk Based Development](https://trunkbaseddevelopment.com/)
- [GitHub flow 官方说明](https://docs.github.com/zh/get-started/using-github/github-flow)
- 相关笔记：[[Git 常用命令与四区模型]]、[[Git merge 与 rebase]]、[[持续集成、持续交付与持续部署]]、[[质量门禁设计与失败即阻断]]
