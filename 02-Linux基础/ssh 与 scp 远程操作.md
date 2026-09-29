---
created: 2026-07-31
tags: [Linux基础/网络]
---

# ssh 与 scp 远程操作

> 免密登录测试机、批量分发部署包、用隧道把内网服务映射到本地——测试开发每天都在用的远程能力。

## 概念

### 公钥认证的原理

SSH 支持密码和公钥两种认证方式。公钥认证的流程：

1. 客户端生成一对密钥：**私钥**（`~/.ssh/id_ed25519`，绝不外传）和**公钥**（`~/.ssh/id_ed25519.pub`）。
2. 把公钥追加到服务器的 `~/.ssh/authorized_keys`。
3. 登录时服务器发一个随机挑战，客户端用私钥签名，服务器用公钥验签——**私钥全程没有离开客户端**。

比密码安全在于：不会被暴力破解、不会在网络上传输任何可重放的秘密、可以按机器/人员精细授权和吊销。CI 系统（Jenkins、GitLab Runner）连测试机必须用公钥。

### known_hosts 与中间人防护

第一次连接时 SSH 会显示服务器的指纹并要求确认，确认后写入 `~/.ssh/known_hosts`。之后每次连接都会核对——如果服务器公钥变了（可能是重装系统，也可能是中间人攻击），会弹出大段警告并**拒绝连接**。

这是防中间人的机制，不要习惯性地 `StrictHostKeyChecking=no` 关掉它。

### 权限要求为什么这么严

sshd 会检查一系列文件权限，不满足就**静默拒绝公钥登录**（客户端只看到「回退到密码认证」，看不到原因）：

| 路径 | 要求 |
|------|------|
| `~`（家目录） | 不能对 group/other 可写（`755` 或更严） |
| `~/.ssh` | `700` |
| `~/.ssh/authorized_keys` | `600`（或 `644`） |
| `~/.ssh/id_*`（私钥） | `600` |

原因是：如果家目录或 `.ssh` 对别人可写，别人就能替换 `authorized_keys` 把自己的公钥塞进去。

## 用法

### 登录与密钥

```bash
ssh user@10.0.0.5                     # 基本登录
ssh -p 2222 user@10.0.0.5             # 指定端口
ssh -i ~/.ssh/test_key user@10.0.0.5  # 指定私钥
ssh user@10.0.0.5 'df -h; uptime'     # 执行单条命令后退出（脚本里最常用）
ssh -v user@10.0.0.5                  # 调试认证过程（-vvv 更详细）

# 生成密钥（推荐 ed25519，比 RSA 更短更快更安全）
ssh-keygen -t ed25519 -C "tester@ci"
ssh-keygen -t rsa -b 4096 -C "tester@ci"     # 老系统不支持 ed25519 时

# 分发公钥（自动处理权限，优于手动 cat）
ssh-copy-id user@10.0.0.5
ssh-copy-id -i ~/.ssh/test_key.pub -p 2222 user@10.0.0.5

# 手动分发（没有 ssh-copy-id 时）
cat ~/.ssh/id_ed25519.pub | ssh user@10.0.0.5 \
    'mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'
```

### config 文件：把长命令变成短别名

`~/.ssh/config` 是提效最明显的一个文件：

```text
Host uat
    HostName 10.0.0.5
    User tester
    Port 2222
    IdentityFile ~/.ssh/test_key
    ServerAliveInterval 60
    ServerAliveCountMax 3

Host prod-*
    User ops
    IdentityFile ~/.ssh/prod_key
    StrictHostKeyChecking yes

# 通过跳板机访问内网机器（-J 的配置版）
Host inner-db
    HostName 192.168.1.100
    User dba
    ProxyJump jumpserver

Host jumpserver
    HostName 1.2.3.4
    User jump
    IdentityFile ~/.ssh/jump_key

Host *
    ServerAliveInterval 60
    ControlMaster auto
    ControlPath ~/.ssh/cm-%r@%h:%p
    ControlPersist 10m
```

配好之后 `ssh uat` 就等价于那一长串参数，`scp file uat:/tmp/` 也能用。

- **`ServerAliveInterval 60`**：每 60 秒发一个心跳，解决「挂着不动就断开」。
- **`ControlMaster` + `ControlPersist`**：连接复用，后续 ssh 到同一台机器复用已有 TCP 连接，秒连——批量操作时提速非常明显。

### scp 与 rsync：传文件

```bash
# scp
scp local.txt user@10.0.0.5:/tmp/                  # 上传
scp user@10.0.0.5:/var/log/app.log ./              # 下载
scp -r ./dist user@10.0.0.5:/opt/app/              # 整个目录
scp -P 2222 -i ~/.ssh/key file user@host:/tmp/     # 注意是大写 -P（ssh 是小写 -p）
scp -C large.tar.gz user@host:/tmp/                # 压缩传输
scp -l 8192 big.iso user@host:/tmp/                # 限速 8Mbps，避免打满测试环境带宽

# rsync（更推荐：增量、断点、保权限）
rsync -avz ./dist/ user@10.0.0.5:/opt/app/dist/    # 增量同步
rsync -avz --delete ./dist/ user@host:/opt/app/dist/   # 删除目标端多余文件（危险，先 -n 预演）
rsync -avzn ./dist/ user@host:/opt/app/dist/       # -n = dry-run 预演
rsync -avz --progress --partial big.iso user@host:/tmp/   # 显示进度 + 断点续传
rsync -avz -e 'ssh -p 2222' ./src/ user@host:/dst/ # 指定 ssh 参数
rsync -avz --exclude='*.pyc' --exclude='.git' ./ user@host:/opt/app/
```

**`rsync` 的尾斜杠语义**（最容易搞错的一点）：

- `rsync -a src/ dst/` → 把 src **里面的内容**同步到 dst
- `rsync -a src dst/` → 把 src **这个目录本身**同步进去，变成 `dst/src`

**scp 与 rsync 怎么选**：一次性传小文件用 scp（无需目标端装 rsync）；反复同步、大文件、需要断点续传或增量用 rsync。OpenSSH 9.0 起 scp 底层已改用 SFTP 协议，历史上的通配符安全问题（CVE-2020-15778 等）也促使官方推荐用 sftp/rsync 替代 scp。

### 端口转发（隧道）：测试场景的利器

```bash
# 本地转发：把远端的服务映射到本地端口
# 场景：测试库只允许跳板机访问，我想用本地的 Navicat 连
ssh -L 13306:127.0.0.1:3306 user@jumpserver
# 之后本地 localhost:13306 就是远端的 3306

# 映射到跳板机能访问的第三方机器
ssh -L 13306:192.168.1.100:3306 user@jumpserver

# 远程转发：把本地服务暴露给远端
# 场景：远端服务要回调我本机跑的 mock server
ssh -R 8080:127.0.0.1:8080 user@remote

# 动态转发（SOCKS5 代理）：整个内网都能访问
ssh -D 1080 user@jumpserver
# 浏览器/curl 配 socks5://127.0.0.1:1080

# 只做转发不登录 shell：-N 不执行命令，-f 后台运行
ssh -fNL 13306:127.0.0.1:3306 user@jumpserver
```

隧道是测试环境访问受限资源最干净的方式，不需要改任何网络策略。

### 跳板机

```bash
ssh -J jump_user@jumpserver inner_user@192.168.1.100     # 一条命令直达（推荐）
ssh -J j1@host1,j2@host2 user@target                     # 多级跳板
```

配到 `~/.ssh/config` 的 `ProxyJump` 里之后，`scp`、`rsync`、`ansible` 都能自动走跳板。

### 批量操作

```bash
# 简单批量
for host in host1 host2 host3; do
    echo "===== $host ====="
    ssh -o ConnectTimeout=5 "$host" 'df -h /data | tail -1'
done

# 并发批量（注意 -n 防止 ssh 吞掉 stdin）
cat hosts.txt | xargs -P 10 -I{} ssh -n -o ConnectTimeout=5 {} 'uptime'

# 分发文件到多台
for host in $(cat hosts.txt); do
    rsync -az ./app.jar "$host:/opt/app/" &
done
wait
```

在脚本里用 ssh 有个经典陷阱：**ssh 会读取 stdin**，放在 `while read` 循环里会把剩下的行全部吃掉，导致循环只跑一次。加 `-n`（把 stdin 接到 `/dev/null`）解决：

```bash
while read -r host; do
    ssh -n "$host" 'uptime'
done < hosts.txt
```

### 远程执行的引号问题

```bash
ssh host "echo $HOSTNAME"     # 双引号：$HOSTNAME 在【本地】展开
ssh host 'echo $HOSTNAME'     # 单引号：在【远端】展开 ← 通常是你要的
ssh host "echo \$HOSTNAME"    # 转义，效果同单引号

# 复杂脚本用 here-doc 传过去
ssh host 'bash -s' <<'EOF'
set -euo pipefail
cd /opt/app
./restart.sh
tail -20 logs/app.log
EOF
```

`ssh host 'bash -s' <<'EOF'` 这个组合可以把一整段本地脚本喂给远端执行，比拼一长串命令清爽得多。

## 踩坑

1. **`Permissions 0644 for 'id_rsa' are too open`**。`chmod 600 ~/.ssh/id_rsa`、`chmod 700 ~/.ssh`。

2. **公钥配了还是要密码**。按顺序查：家目录不能对 group/other 可写（`chmod 755 ~`）；`.ssh` 是 700、`authorized_keys` 是 600；公钥内容是否完整一行（复制时被换行截断是高发问题）；服务端 `/etc/ssh/sshd_config` 里 `PubkeyAuthentication yes`；SELinux 环境执行 `restorecon -Rv ~/.ssh`。用 `ssh -vvv` 看客户端日志、服务端 `journalctl -u sshd` 看拒绝原因。

3. **`REMOTE HOST IDENTIFICATION HAS CHANGED!`**。服务器重装或 IP 复用导致公钥变了。确认是预期变更后 `ssh-keygen -R 10.0.0.5` 删掉旧记录。**不要无脑加 `StrictHostKeyChecking=no`**，那等于关掉中间人防护。

4. **`scp -P` 和 `ssh -p` 大小写不同**。scp 是大写 `-P`，ssh 是小写 `-p`。

5. **rsync 的尾斜杠导致目录多套一层**。`src/` 和 `src` 语义不同，操作前用 `-n` 预演。

6. **`rsync --delete` 删了不该删的**。目标端的额外文件会被清掉。永远先 `-avzn` dry-run 确认清单。

7. **循环里的 ssh 把 stdin 吃光，只执行了第一次**。加 `-n`。

8. **长时间 SSH 会话自动断开**。配 `ServerAliveInterval 60` + `ServerAliveCountMax 3`。长任务本身应该跑在 tmux 里（见 [[nohup 与后台任务管理]]）。

9. **`ssh host 'cmd'` 里的变量在本地被展开了**。区分单双引号。

10. **通过 ssh 执行的命令找不到环境变量**。非交互式 ssh 只加载 `~/.bashrc` 的一部分（很多发行版的 `.bashrc` 开头就有「非交互式直接 return」的判断），`/etc/profile` 完全不加载。所以 `ssh host 'java -version'` 可能报 command not found。解法是用绝对路径，或 `ssh host 'source /etc/profile; cmd'`，或 `ssh host 'bash -lc "cmd"'`（`-l` 走登录 shell）。

11. **Jenkins 里 ssh 卡住不返回**。远端启动了后台进程但仍持有 ssh 的 stdout/stderr，ssh 会一直等这些 fd 关闭。远端命令要写成 `nohup cmd > /dev/null 2>&1 &`，把三个 fd 都断开。

12. **把私钥提交到 Git 仓库**。CI 的密钥应该放凭据管理（Jenkins Credentials、GitHub Secrets），仓库里加 `.gitignore` 排除 `id_*`。

## 面试怎么答

**Q：怎么配置 SSH 免密登录？原理是什么？**

A：三步：本地 `ssh-keygen -t ed25519` 生成密钥对；`ssh-copy-id user@host` 把公钥追加到远端的 `~/.ssh/authorized_keys`；之后 `ssh user@host` 直接进。

原理是非对称加密的挑战应答：服务器发一段随机数据，客户端用私钥签名，服务器用 `authorized_keys` 里的公钥验签通过就放行——**私钥始终不离开本地，网络上也不传输任何可重放的秘密**，所以比密码安全得多，也不怕暴力破解。

实践中最常见的失败原因是权限：家目录不能对 group/other 可写，`~/.ssh` 必须 700，`authorized_keys` 必须 600，私钥必须 600。sshd 检查不通过时会静默回退到密码认证，不给任何提示，所以要用 `ssh -vvv` 和服务端的 `journalctl -u sshd` 来定位。

**Q：`scp` 和 `rsync` 有什么区别？**

A：scp 是全量复制，每次都把整个文件重新传一遍，中断了要从头再来，好处是简单、目标端只要有 sshd 就行。rsync 有增量算法（比对文件块的校验和，只传差异部分）、支持断点续传（`--partial`）、能保留权限属主时间戳（`-a`）、能排除文件（`--exclude`）、能同步删除（`--delete`）、能显示进度。

选择上：一次性传单个小文件用 scp；反复同步部署目录、传大文件、需要保留属性的场景用 rsync。要注意 rsync 的尾斜杠语义（`src/` 是同步内容，`src` 是同步目录本身）和 `--delete` 的危险性，操作前都应该先 `-n` 预演。另外 OpenSSH 官方现在也推荐用 sftp/rsync 替代 scp，因为 scp 的协议设计有历史安全问题。

**Q：测试库只允许跳板机访问，你怎么用本地工具连？**

A：用 SSH 本地端口转发建隧道：

```bash
ssh -fNL 13306:192.168.1.100:3306 user@jumpserver
```

`-L 本地端口:目标主机:目标端口` 的含义是「本地 13306 收到的流量，通过 SSH 加密通道送到跳板机，再由跳板机转发给 192.168.1.100:3306」。`-N` 表示不执行远程命令（只做转发），`-f` 后台运行。建好之后本地 Navicat 连 `127.0.0.1:13306` 就等于连上了内网数据库。

同理，`-R` 是反向转发，用于把本地跑的 mock server 暴露给远端服务回调；`-D` 是动态转发，起一个 SOCKS5 代理，让浏览器或 curl 能访问整个内网。这些都不需要改防火墙规则，是测试环境访问受限资源最干净的做法。

**Q：在 Jenkins 里用 ssh 远程启动服务，任务一直卡住不结束，为什么？**

A：因为远端启动的后台进程继承了 ssh 会话的 stdout 和 stderr，ssh 客户端会等到这些文件描述符全部关闭才退出——只要后台进程还活着，管道就不会关，ssh 就一直挂着。

解法是在远端命令里把三个标准描述符都断开：`ssh host 'nohup ./start.sh > /var/log/app.log 2>&1 < /dev/null &'`。更规范的做法是把服务做成 systemd unit，用 `ssh host 'sudo systemctl restart myapp'`——systemd 接管进程后 ssh 立刻返回，而且有状态可查、崩溃会自动拉起。

## 参考

- [OpenSSH 官方文档](https://www.openssh.com/manual.html)
- [`ssh_config(5)` man page](https://man7.org/linux/man-pages/man5/ssh_config.5.html)
- [rsync 官方手册](https://download.samba.org/pub/rsync/rsync.1)
- 相关笔记：[[Linux 文件权限与 chmod、chown]]
- 相关笔记：[[nohup 与后台任务管理]]
