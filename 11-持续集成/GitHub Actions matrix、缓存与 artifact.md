---
created: 2026-07-31
tags: [持续集成/GitHub Actions]
---

# GitHub Actions matrix、缓存与 artifact

> matrix 解决「多环境都要跑」，cache 解决「每轮都重装依赖太慢」，artifact 解决「job 之间传文件」。三者是 GitHub Actions 提速和扩覆盖的三件套。

## 概念

### 为什么需要这三个机制

上一节讲了「每个 job 是独立机器、彼此不共享文件」。这带来三个随之而来的问题：

1. 我想在 Python 3.9 / 3.10 / 3.11 各跑一遍测试 —— 难道写三份 job？→ **matrix** 用一份配置生成多份 job
2. 每轮都 `pip install` 几十秒甚至几分钟，太慢 —— → **cache** 把依赖目录缓存到 runner 池，命中就跳过
3. job A 生成了报告，job B（部署/汇总）要用 —— → **artifact** 把文件暂存，跨 job 甚至跨 workflow 取用

三者解决的是托管式 CI 的天然局限：机器是临时的、彼此隔离的，所以「复制环境」「存依赖」「传产物」都得靠平台机制，而不是像 Jenkins 那样靠持久化的节点。

### 三个概念的区别（最容易混）

- **cache**：给「本 job 自己下次提速」用，键命中就解压，可能过期；不保证一定在
- **artifact**：给「别的 job / 人下载」用，构建产物，保留一段时间（默认 90 天）
- **matrix**：不是存储，是「批量生成 job」的语法糖

## 用法

### 一、matrix 多环境

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false          # 一个环境挂了不让其他环境停（测试推荐 false）
      max-parallel: 4           # 最多同时 4 个
      matrix:
        python: ['3.9', '3.10', '3.11']
        os: [ubuntu-latest, windows-latest]
        include:                # 额外组合
          - python: '3.11'
            os: ubuntu-latest
            markers: 'smoke'
        exclude:                # 排除组合
          - python: '3.9'
            os: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - run: pytest tests/ -m "${{ matrix.markers || 'all' }}"
```

`fail-fast: false` 对测试很重要：默认 true 时一个环境失败会立刻取消其他还在跑的环境，你会少看到很多失败信息。测试场景我几乎都设 false。

### 二、缓存依赖

```yaml
steps:
  - uses: actions/checkout@v4
  - uses: actions/setup-python@v5
    with:
      python-version: '3.11'
  # 关键：缓存 pip 下载的 wheel 目录
  - uses: actions/cache@v4
    with:
      path: ~/.cache/pip
      key: ${{ runner.os }}-pip-${{ hashFiles('requirements.txt') }}
      restore-keys: |
        ${{ runner.os }}-pip-
  - run: pip install -r requirements.txt
```

缓存命中规则：

- `key` 完全匹配才命中；`requirements.txt` 变了 hash 就变，自动失效
- `restore-keys` 是兜底：key 没命中时，用它前缀匹配一个旧的缓存（比如只改了一行依赖，仍能复用大部分）
- `path` 可以写多个目录，用换行分隔

### 三、artifact 上传与下载

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: pytest tests/ --alluredir=allure-results
      - uses: actions/upload-artifact@v4
        with:
          name: allure-results      # 必填且同一 workflow 内唯一
          path: allure-results/
          retention-days: 7
  report:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: allure-results
          path: allure-results/
      - run: allure generate allure-results -o allure-report
```

注意 `upload-artifact@v4` 要求每个 artifact 的 `name` 在同一 workflow 内**唯一**，重复名会直接失败（v3 没有这个限制，升级时要改）。

### 四、用 matrix + artifact 做分片汇总

```yaml
jobs:
  shard:
    strategy:
      matrix:
        shard: [1, 2, 3, 4]
    steps:
      - run: pytest tests/ --shard-id=${{ matrix.shard }} --num-shards=4 --alluredir=r-${{ matrix.shard }}
      - uses: actions/upload-artifact@v4
        with:
          name: shard-${{ matrix.shard }}
          path: r-${{ matrix.shard }}/
  merge:
    needs: shard
    steps:
      - uses: actions/download-artifact@v4
        with:
          pattern: shard-*        # 一次性下载所有匹配的分片
          merge-multiple: true
          path: allure-results/
      - run: allure generate allure-results -o allure-report
```

## 踩坑

1. **`fail-fast` 默认 true 吞掉失败信息**。一个 Python 版本失败，其他版本被取消，你只看到一条红。测试矩阵务必设 `fail-fast: false`。

2. **cache key 没包含依赖清单 hash**。`key: cache-pip` 写死，依赖更新了还在用旧缓存，装出旧版本。必须把 `hashFiles('requirements.txt')` 放进 key。

3. **`restore-keys` 前缀不匹配**。写成和 `key` 完全不同的前缀，兜底完全失效。约定前缀一致，如 `${{ runner.os }}-pip-` 对应 key 的 `${{ runner.os }}-pip-<hash>`。

4. **artifacts 名重复（v4 特有）**。`upload-artifact@v4` 强制 name 唯一，matrix 里若没把 `matrix.xxx` 拼进 name，多份上传互相覆盖报错。拼上分片号即可。

5. **artifact 默认保留 90 天但大文件占配额**。Allure 报告、视频动辄几百 MB，设 `retention-days: 7` 控制成本。

6. **下载 artifact 路径覆盖工作区文件**。`download-artifact` 的 `path` 若指向已有目录，可能和 checkout 的文件混在一起。建议下到独立子目录再处理。

7. **matrix 维度爆炸**。`python × os × db × browser` 一乘几十个 job，既慢又烧额度。只在必要时组合，其余用 `include` 单独列。

8. **cache 在多 OS 下 key 要带 `runner.os`**。Windows 和 Linux 的 `~/.cache/pip` 其实路径不同，但混用同一 key 仍可能串；养成 key 里带 `runner.os` 的习惯。

9. **`download-artifact` 的 `pattern` 需要 v4 且开启**。`merge-multiple` 只合并同名结构，路径会平铺，注意汇总后目录层级是否如预期。

10. **缓存误缓存了构建产物**。把 `node_modules` 之类不该缓存的写进 path。缓存只放「外部下载的依赖」，自己构建的产物用 artifact。

## 面试怎么答

**Q：GitHub Actions 里 cache 和 artifact 有什么区别？**

A：两者都解决「临时机器上文件怎么留」，但目的不同。cache 是给本 job 自己下次提速用的，比如缓存 pip 的下载目录，靠 key 命中，可能过期、不保证一定在，典型用法是把 `requirements.txt` 的 hash 放进 key，依赖没变就直接复用。artifact 是给别的 job 或人下载用的，比如测试 job 产出的 Allure 结果，靠 `upload-artifact`/`download-artifact` 跨 job 传递，保留一段时间默认 90 天。一句话：cache 是省钱提速，artifact 是传产物。matrix 不一样，它不是存储，是批量生成 job 的语法糖，用来在多个 Python 版本或操作系统上跑同一套测试。

**Q：怎么用 GitHub Actions 做测试分片加速？**

A：用 matrix 生成多个分片 job，比如 `shard: [1,2,3,4]`，每个 job 跑 `pytest --shard-id=${{ matrix.shard }} --num-shards=4`，各自把结果上传成 `shard-<id>` 的 artifact。再写一个汇总 job `needs: shard`，用 `download-artifact` 的 `pattern: shard-*` 一次性拉下来合并成完整 Allure 报告。这里两个注意点：一是 upload 的 artifact 名必须唯一，要把分片号拼进去，否则 v4 会报错；二是矩阵测试我设 `fail-fast: false`，避免一个分片失败就取消其他分片，能一次拿到全部失败信息。

**Q：缓存没生效怎么排查？**

A：先看 cache step 的日志，它会打印 `Cache hit` 或 `Cache miss`。miss 的常见原因：key 里没包含依赖清单的 hash，导致每次 key 都变、永远命不中；或者 `restore-keys` 前缀和 key 前缀不一致，兜底也没接上。另一个坑是只给 key 没给 `restore-keys`，一旦 key 变了就完全没缓存可用。正确做法是 key 用 `runner.os-pip-<hashFiles('requirements.txt')>`，再配一个 `runner.os-pip-` 的 restore-keys 做前缀兜底，这样依赖只改一行也能复用大部分。

## 参考

- [GitHub Actions cache 文档](https://docs.github.com/en/actions/using-workflows/caching-dependencies-to-speed-up-workflows)
- [Artifacts 文档](https://docs.github.com/en/actions/using-workflows/storing-workflow-data-as-artifacts)
- [Matrix 策略文档](https://docs.github.com/en/actions/using-jobs/using-a-matrix-for-your-jobs)
- 相关笔记：[[GitHub Actions workflow 结构与触发事件]]、[[Docker 镜像与容器核心概念]]、[[CI 实践串联：接口自动化流水线]]
