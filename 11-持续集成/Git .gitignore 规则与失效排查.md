---
created: 2026-07-31
tags: [持续集成/Git]
---

# .gitignore 规则与失效排查

> 「我明明写了忽略规则，它还是被提交了」——90% 的原因是：**文件已经被 Git 跟踪了，.gitignore 对已跟踪文件完全无效。**

## 概念

### .gitignore 只管「未跟踪文件」

这是全部理解的起点。Git 把文件分成三种状态：

- **untracked**：Git 从没见过它
- **tracked**：已经 `git add` 过，进入了索引
- **ignored**：匹配 `.gitignore` 规则的 **untracked** 文件

`.gitignore` 的作用是让 Git **不要把某个 untracked 文件报告成「未跟踪」**，仅此而已。一旦文件进过索引（哪怕只 add 过一次、后来又删了 `.gitignore` 规则），它就永远是 tracked，之后的改动照样会被 `git status` 报出来、照样能被 `git commit -a` 提交。

所以「忽略规则不生效」的正确说法通常是「**这个文件早就被跟踪了**」。

### 规则文件的优先级

Git 会按顺序读取多个忽略源，**后面的覆盖前面的**：

1. `$GIT_DIR/info/exclude`——仓库本地，不提交，个人专用
2. 仓库根目录的 `.gitignore`——**提交进仓库，团队共享**
3. 子目录里的 `.gitignore`——只对该目录及其子目录生效
4. `core.excludesFile` 指向的全局忽略文件——本机所有仓库生效

同一层级内，**后面的规则覆盖前面的**。这条很重要，是写「先忽略全部、再放行个别」这种规则的基础。

### 匹配语法

| 写法 | 含义 |
|------|------|
| `*.log` | 任意目录下所有 `.log` 文件 |
| `/build` | **仅**仓库根目录的 `build`（开头的 `/` 锚定根） |
| `build/` | 任意位置名为 `build` 的**目录**（结尾 `/` 限定目录） |
| `doc/*.txt` | 只匹配 `doc/` 下一层的 txt，不含 `doc/a/b.txt` |
| `doc/**/*.txt` | `doc/` 下任意深度的 txt |
| `!important.log` | **取消**忽略（否定规则） |
| `?` | 匹配单个字符 |
| `[0-9]` | 字符范围 |
| `# 注释` | 注释行 |

### 否定规则的致命限制

```gitignore
# ❌ 不生效！
logs/
!logs/keep.log
```

**如果父目录被忽略了，Git 根本不会进去扫描，里面的否定规则永远没机会生效**——这是性能优化：目录被排除就整棵子树跳过。

正确写法是**逐层放行目录**：

```gitignore
# ✅ 生效
logs/*
!logs/keep.log

# 多层的情况，每一层都要放行
data/*
!data/fixtures/
data/fixtures/*
!data/fixtures/users.json
```

模式一律是：**用 `dir/*` 而不是 `dir/` 来忽略内容**，这样目录本身没被排除，Git 还会进去扫描。

## 用法

### 一、SDET 项目的实用模板

```gitignore
# ===== Python =====
__pycache__/
*.py[cod]
*.egg-info/
.eggs/
build/
dist/

# 虚拟环境（各种命名都堵上）
.venv/
venv/
env/
ENV/

# ===== 测试产物 =====
.pytest_cache/
.tox/
.nox/
htmlcov/
.coverage
.coverage.*
coverage.xml
report.html
allure-results/
allure-report/
screenshots/
logs/*
!logs/.gitkeep

# Selenium / Appium 驱动
chromedriver*
geckodriver*
*.apk
*.ipa

# JMeter 运行产物（脚本本身要提交）
*.jtl
jmeter.log
jmeter-report/

# ===== IDE =====
.idea/
.vscode/*
!.vscode/settings.json      # 团队共享的格式化配置留下
!.vscode/extensions.json
*.swp

# ===== OS =====
.DS_Store
Thumbs.db
desktop.ini

# ===== 敏感信息（重中之重）=====
.env
.env.*
!.env.example               # 模板要提交，让新人知道需要哪些变量
config/local.yaml
*.pem
*.key
credentials.json
secrets/
```

几个 SDET 特有的判断：

- **`allure-results/` 要忽略，Allure 报告靠 CI 归档**（见 [[Jenkins Allure 报告与构建后通知]]），提交进仓库会让仓库迅速膨胀
- **`.env` 忽略但 `.env.example` 提交**，否则新人不知道要配哪些变量
- **驱动二进制忽略**，用 `webdriver-manager` 或 CI 里下载，别把 15MB 的 chromedriver 提交进去
- **`logs/` 目录本身要保留**（有些框架启动时不会自动建目录），所以用 `logs/*` + `!logs/.gitkeep`

### 二、验证规则是否按预期工作

```bash
# 这个命令是排查神器：告诉你某文件被哪个文件的第几行规则忽略了
git check-ignore -v allure-results/xxx.json
# .gitignore:23:allure-results/    allure-results/xxx.json

# 没有输出 = 没被任何规则忽略
git check-ignore -v tests/conftest.py
# （无输出，退出码 1）

# 列出所有被忽略的文件
git status --ignored -s

# 看看哪些文件已经被跟踪了（排查「规则不生效」的关键一步）
git ls-files | grep -E "\.env|allure-results"
```

### 三、修复「已被跟踪」的文件

```bash
# 1. 先确认它确实被跟踪了
git ls-files --error-unmatch .env      # 有输出说明被跟踪

# 2. 从索引中移除，但保留本地文件（--cached 是关键）
git rm --cached .env

# 3. 目录的话加 -r
git rm -r --cached .idea/
git rm -r --cached allure-results/

# 4. 确认 .gitignore 里有对应规则，然后提交
git commit -m "chore: 停止跟踪本地配置与测试产物"
```

**千万别漏 `--cached`**：不加的话是真删本地文件。

批量清理（`.gitignore` 改完后一次性让所有规则生效）：

```bash
git rm -r --cached .          # 从索引移除所有文件（本地文件不动）
git add .                     # 重新添加，此时会遵守 .gitignore
git status                    # 检查：应该只显示那些「被移除跟踪」的文件
git commit -m "chore: 应用 .gitignore 规则"
```

这个操作会产生一个大 diff，但内容都是删除跟踪，是安全的。执行前 `git status` 确认工作区干净。

### 四、彻底从历史中抹掉（敏感信息泄露时）

`git rm --cached` 只是「以后不跟踪了」，**历史里那个文件还在**，任何人 `git log -p` 都能翻出来。密钥泄露必须重写历史：

```bash
# 推荐 git-filter-repo（官方推荐，替代已废弃的 filter-branch）
pip install git-filter-repo

# 从所有历史中彻底删除某个文件
git filter-repo --invert-paths --path config/secrets.yaml

# 或者替换掉所有出现过的密钥字符串
echo 'AKIAIOSFODNN7EXAMPLE==>REMOVED' > replacements.txt
git filter-repo --replace-text replacements.txt

# 重写后必须强推，且所有人重新 clone
git remote add origin git@github.com:org/repo.git
git push --force --all
git push --force --tags
```

**但最重要的一步是：立刻去把那个密钥作废并轮换。** 历史重写不能保证没人已经拉过、没被爬虫扫走。GitHub 的 fork 和缓存也可能仍然保留旧对象。

### 五、CI 里加一道防线

靠人记得不提交敏感文件是不可靠的，用钩子和流水线卡：

```bash
# .git/hooks/pre-commit  （chmod +x；团队共享用 pre-commit 框架）
#!/bin/sh
set -e

# 1. 拦截大文件（> 5MB）
MAX=5242880
for f in $(git diff --cached --name-only --diff-filter=A); do
    [ -f "$f" ] || continue
    size=$(wc -c < "$f")
    if [ "$size" -gt "$MAX" ]; then
        echo "❌ $f 超过 5MB（$size 字节），请用 Git LFS 或不要提交"
        exit 1
    fi
done

# 2. 拦截疑似密钥
if git diff --cached | grep -nE '(AKIA[0-9A-Z]{16}|-----BEGIN .*PRIVATE KEY-----|password\s*=\s*["\x27][^"\x27]{6,})'; then
    echo "❌ 检测到疑似密钥/明文密码，禁止提交"
    exit 1
fi
```

团队统一管理用 `pre-commit` 框架，配置本身提交进仓库：

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: check-added-large-files
        args: ["--maxkb=5120"]
      - id: detect-private-key
      - id: end-of-file-fixer
      - id: trailing-whitespace
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.4
    hooks:
      - id: gitleaks
```

```bash
pip install pre-commit
pre-commit install          # 安装到 .git/hooks
pre-commit run --all-files  # 存量检查
```

流水线里再兜一次底（钩子能被 `--no-verify` 绕过，CI 不能）：

```yaml
# .github/workflows/secret-scan.yml
name: secret-scan
on: [push, pull_request]

jobs:
  gitleaks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0        # 扫全历史，浅克隆会漏
      - uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### 六、个人偏好放全局，别污染团队文件

```bash
git config --global core.excludesFile ~/.gitignore_global
```

```gitignore
# ~/.gitignore_global —— 只跟你的开发环境有关的东西
.DS_Store
Thumbs.db
.idea/
*.swp
.vscode/
```

**判断标准**：这条规则跟「项目本身」有关（如 `__pycache__/`、`allure-results/`）就写进仓库的 `.gitignore`；跟「我用什么编辑器/什么操作系统」有关就写进全局。往仓库 `.gitignore` 里塞 `.idea/`、`.DS_Store` 是常见但不讲究的做法。

## 踩坑

1. **规则写了但文件已被跟踪**。最高频问题。`git check-ignore -v <file>` 显示确实匹配了规则，但 `git status` 还是报改动——因为 `.gitignore` 管不了已跟踪文件。用 `git rm --cached` 解决。

2. **`git rm --cached` 漏了 `--cached`**，本地文件被真删。`.env` 没了，本地环境直接跑不起来。删之前先备份一份。

3. **`logs/` + `!logs/keep.log` 不生效**。父目录被排除，Git 不会进去扫。改成 `logs/*` + `!logs/keep.log`。

4. **空目录提交不上去**。Git 只跟踪文件不跟踪目录。测试框架需要 `logs/`、`screenshots/` 存在才能启动，但目录是空的提交不了，CI 上直接 `FileNotFoundError`。解法：放一个 `.gitkeep` 空文件，并在 `.gitignore` 里 `!` 放行它。或者在代码里 `Path("logs").mkdir(exist_ok=True)` 自己建（更推荐，不依赖 Git 行为）。

5. **`.env` 提交上去了才发现**。`git rm --cached` 只是不再跟踪，**历史里还在**，任何人都能翻出来。必须 `git filter-repo` 重写历史 + **立即轮换密钥**。后者比前者重要一百倍。

6. **`.gitignore` 忽略了 CI 需要的文件**。有人图省事写了 `*.yaml`，把 `docker-compose.yaml`、`.github/workflows/*.yml` 也忽略了，CI 直接不触发，排查半天。规则要精确，别用大范围通配。

7. **`git add -f` 强行添加后忘了**。`-f` 能绕过忽略规则把文件加进来，一旦加进来它就是 tracked，之后规则再也管不住它了。

8. **子模块 / 子目录 `.gitignore` 覆盖了根目录规则**。子目录里的规则优先级更高，可能用 `!` 把根目录忽略的东西放行了。`git check-ignore -v` 会告诉你到底是哪个文件的哪一行在起作用。

9. **忽略了 `poetry.lock` / `package-lock.json`**。锁文件**必须提交**，否则 CI 上装的依赖版本和本地不一致，出现「本地绿 CI 红」的经典问题。要忽略的是 `.venv/`、`node_modules/`，不是锁文件。

10. **CI 上 gitleaks 扫不出历史泄露**。因为默认浅克隆只有一个 commit。必须 `fetch-depth: 0`。

## 面试怎么答

**Q：`.gitignore` 写了为什么不生效？**

A：几乎都是因为文件已经被 Git 跟踪了。`.gitignore` 只对未跟踪文件生效，一旦文件进过索引，忽略规则就管不了它。排查步骤是：先 `git check-ignore -v <file>` 确认规则本身有没有匹配上——如果没匹配，是规则写错了；如果匹配了但 `git status` 还报它，就是已跟踪，用 `git rm --cached <file>` 从索引移除再提交。另一个常见原因是否定规则写在了被忽略的目录下，比如 `logs/` 加 `!logs/keep.log` 不生效，因为父目录被排除后 Git 不会进去扫描，得改成 `logs/*`。

**Q：不小心把密钥提交上去了怎么办？**

A：处理顺序很关键。**第一步是立刻作废并轮换那个密钥**，不是删文件——因为提交历史可能已经被别人拉走、被爬虫扫走，GitHub 的 fork 和对象缓存也可能留有副本，删得再干净也不能假定它没泄露。第二步才是清理历史，用 `git filter-repo --invert-paths --path <file>` 重写，然后强推，并通知所有人重新 clone。第三步是补防线：仓库加 `.gitignore` 规则，本地装 pre-commit 钩子跑 gitleaks 和 detect-private-key，CI 里再加一道 secret scan 兜底——因为本地钩子能被 `--no-verify` 绕过，CI 不能。敏感配置应该走环境变量或 CI 的凭据管理，根本不进仓库。

**Q：测试项目里哪些该忽略、哪些不该？**

A：该忽略的是「能重新生成的产物」和「本机相关的东西」：`__pycache__`、`.pytest_cache`、`.venv`、`allure-results`、`htmlcov`、`*.jtl`、下载的 chromedriver、`.idea`。不该忽略的有三类：一是锁文件 `poetry.lock`、`requirements.txt`，忽略了会导致 CI 和本地依赖版本不一致，出现「本地绿 CI 红」；二是配置模板 `.env.example`，新人靠它知道要配哪些变量；三是流水线定义 `Jenkinsfile`、`.github/workflows/*.yml`、`docker-compose.yaml`，这些是 pipeline as code 的核心资产。另外空目录 Git 不跟踪，框架依赖的 `logs/`、`screenshots/` 目录要放 `.gitkeep`，或者更稳妥地在代码里 mkdir。

## 参考

- [gitignore 官方文档](https://git-scm.com/docs/gitignore)
- [GitHub 官方 .gitignore 模板集](https://github.com/github/gitignore)
- [git-filter-repo](https://github.com/newren/git-filter-repo)
- [pre-commit 框架](https://pre-commit.com/)
- 相关笔记：[[Git 常用命令与四区模型]]、[[Jenkins 凭据管理]]、[[GitHub Actions matrix、缓存与 artifact]]
