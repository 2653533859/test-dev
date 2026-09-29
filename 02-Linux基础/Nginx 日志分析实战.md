---
created: 2026-07-31
tags: [Linux基础/日志分析实战]
---

# Nginx 日志分析实战

测试/线上出问题时，Nginx 的 `access.log` 是最直接的「黑匣子」：谁访问的、访问了什么、返回什么状态码、花了多久。本章用前面学的 `awk`/`grep`/`sort`/`uniq` 串成完整排查流水线，覆盖常考的「Top 10 IP」「错误码分布」「慢请求」。

![[assets/log-analysis-pipeline.svg]]

*图示：从原始日志到可读结论的流水线——过滤 → 字段提取 → 聚合 → Top N，结果再反推监控规则形成闭环。*

## 概念

Nginx 默认 `access.log` 行形如（combined 格式）：

```text
192.168.1.10 - - [31/Jul/2026:10:20:33 +0800] "GET /api/users HTTP/1.1" 200 1024 "https://ref" "Mozilla/5.0"
```

关键字段（按空格切分，但注意引号内可能含空格）：

- `$1` 客户端 IP（或经代理后的 `X-Forwarded-For`）
- `$9` HTTP 状态码（如 200 / 404 / 502）
- `$10` 响应体字节数
- `request_time`：Nginx 处理该请求的总耗时（秒，含上游），定位慢请求的核心指标
- `upstream_response_time`：后端应用耗时，区分「慢在 Nginx 还是慢在应用」

日志分析的本质是个 ETL：过滤（只关心 5xx / 慢请求）→ 提取字段 → 聚合计数 → 取 Top N。所有动作都靠 `awk` 取列 + `sort | uniq -c | sort -rn` 做计数排序。

## 用法

### 1. Top 10 访问 IP（识别爬虫/恶意刷量）

```bash
awk '{print $1}' access.log | sort | uniq -c | sort -rn | head -10
```

### 2. 各状态码分布

```bash
awk '{print $9}' access.log | sort | uniq -c | sort -rn
```

### 3. 慢请求 Top 10（按 request_time 倒序，需日志含该字段）

```bash
# 假设 log_format 含 $request_time，且其在某固定列，这里用 $NF 取最后一列示意
awk '{print $(NF-1), $7}' access.log | sort -rn | head -10
```

### 4. 5xx 错误集中在哪些 URL

```bash
awk '$9>=500 {c[$7]++} END {for (u in c) print c[u], u}' access.log \
  | sort -rn | head
```

### 5. 某 IP 在指定时间段的行为

```bash
awk '$1=="192.168.1.10" && $4>="[31/Jul/2026:10:00" && $4<="[31/Jul/2026:11:00"' access.log
```

### 6. 实时统计每秒请求数（QPS 粗看）

```bash
tail -f access.log | awk '{print $4}' | uniq -c
```

## 踩坑

1. **字段列号对不上**：默认 combined 格式里 `"GET /api/users HTTP/1.1"` 是一个带引号的整段，用空格切分时 `$7` 才是 URL、`$9` 是状态码；但一旦 `log_format` 改过顺序，列号全错位——**别死记列号，按实际日志校对**。
2. **`request_time` 不在默认日志里**：很多 Nginx 默认 combined 格式没有 `request_time`，需要先改 `log_format` 加上，否则无法分析慢请求。
3. **`sort | uniq -c | sort -rn` 顺序不能乱**：必须先 `sort` 让相同行相邻，`uniq -c` 才能计数，最后 `sort -rn` 按次数倒序。
4. **引号内空格破坏 `awk` 默认分词**：`$0` 里 `"Mozilla/5.0 (X11; ...)"` 含空格，`awk` 按空格切会把 UA 拆成多列。需要精确解析时，用 `awk -F'"'` 按引号分段，或改用 `grep -oP` 正则提取。
5. **`uniq -c` 计的是「相邻相同行」**：忘记先 `sort` 会得出错误计数（只合并了已相邻的）。
6. **`tail -f` 管道里 `awk` 不立即刷新**：`tail -f` 持续输出时，管道缓冲可能让 `uniq -c` 不实时更新；实时看建议 `stdbuf -oL` 或只看非流式统计。
7. **大日志直接 `awk` 全量扫描慢**：几十 GB 日志全量跑很慢，应先用 `sed -n '/时间段/p'` 或 `grep` 缩小范围，或按天切分（`access.log.2026-07-31`）。
8. **`$9>=500` 对空/非数字字段报错或误判**：日志若有异常行（被截断），`$9` 可能不是数字，`awk` 会当 0 处理而漏掉；可加 `$9 ~ /^[0-9]+$/ && $9>=500` 守卫。
9. **`X-Forwarded-For` 才是真实用户 IP**：前端有 CDN/反向代理时 `$1` 是代理 IP，真实客户端在请求头的 `X-Forwarded-For` 第一个值，分析来源 IP 要取它。
10. **`sort -rn` 对中文/特殊字符排序**：Top URL 含中文路径时排序顺序可能不符合直觉，仅影响展示顺序不影响计数。

## 面试怎么答

**Q：统计访问最多的 IP 前 10，怎么写？**
`awk '{print $1}' access.log | sort | uniq -c | sort -rn | head -10`。核心是 `awk` 取第一列（客户端 IP），`sort | uniq -c` 计数，`sort -rn` 倒序，`head` 取前 10。注意若有反代要取 `X-Forwarded-For`。

**Q：怎么找慢请求？**
前提是 `log_format` 含 `request_time`。用 `awk` 提取该字段与 URL，按耗时倒序取 Top N：`awk '{print $request_time, $uri}' access.log | sort -rn | head`。进一步要把 `request_time` 与 `upstream_response_time` 对比，判断慢在 Nginx 还是后端应用。

**Q：502/504 突然增多，怎么用日志定位？**
先 `awk '$9>=500{...}'` 看 5xx 集中在哪些 URL 和上游；结合 `upstream_response_time` 是否为空（504 通常是上游超时无响应），再去看对应后端服务的进程与端口（见 [[Linux 端口占用排查：netstat、ss 与 lsof]]）和 `error.log` 的上游连接错误。

**Q：`sort | uniq -c | sort -rn` 每一步在干什么？**
第一次 `sort` 让相同行聚到一起；`uniq -c` 给相邻相同行计次数并前缀数量；最后 `sort -rn` 按数量数值倒序（`-r` 倒序，`-n` 按数值而非字典）。顺序不能省第一步 `sort`。

**Q：为什么日志分析要「先过滤再聚合」？**
全量日志聚合慢且噪音多。先按状态码（5xx）、耗时阈值、或时间窗过滤出关心的子集，再聚合，既快又准，也更符合「排查一个问题」的实际场景。

## 参考

- [Nginx `log_format` 官方文档](https://nginx.org/en/docs/http/ngx_http_log_module.html)
- [Awk 简明教程](https://man7.org/linux/man-pages/man1/awk.1.html)
- 相关笔记：[[awk 列处理与统计]]
- 相关笔记：[[grep 正则与管道]]
- 相关笔记：[[sed 流编辑与替换]]
- 相关笔记：[[Linux 端口占用排查：netstat、ss 与 lsof]]
