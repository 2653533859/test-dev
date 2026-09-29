---
created: 2026-07-31
tags: [Linux基础/权限]
---

# Linux 文件权限与 chmod、chown

> 看懂 `-rwxr-xr--` 每一位的含义，用 `chmod` / `chown` 修掉「Permission denied」，并知道什么时候该用 `sudo`、什么时候 777 是在埋雷。

![[assets/permission-bits.svg]]
*图示：权限串拆成「类型 + u/g/o 三组 rwx」，内核鉴权按属主 → 属组 → 其他的顺序命中即停，且目录上的 rwx 语义与文件完全不同。*

![[assets/user-group-permission.svg]]
*图示：用户（uid）→ 组（gid）→ 文件三方归属关系，chown/chgrp/chmod 三种操作的作用范围，以及「usermod -aG 加组后必须重新登录」「容器 uid 对不齐」等高频规则。*

## 概念

### 三组权限 × 三种动作

每个文件的 inode 里存着 9 个权限位，分成三组：

- **u（user / owner）**：文件属主
- **g（group）**：文件所属组
- **o（others）**：既不是属主也不在属组里的其他人
- （`a` = all，是 u+g+o 的简写，不是第四组）

每组三位 `rwx`，位权分别是 `r=4`、`w=2`、`x=1`，所以一组的取值就是 0–7 的八进制数字：

```text
rwx = 4+2+1 = 7      rw- = 4+2 = 6      r-x = 4+1 = 5      r-- = 4
```

`-rwxr-xr--` 拆开就是：`-`（普通文件）+ `rwx`（属主 7）+ `r-x`（属组 5）+ `r--`（其他 4），即 **754**。

### 内核鉴权：命中即停，不叠加

这是最容易答错的点。进程访问文件时，内核按顺序判断：

1. 进程的 uid == 文件属主 uid？→ **只用 u 位判定，结束**。
2. 否则，进程的 gid（或附加组）包含文件属组？→ **只用 g 位判定，结束**。
3. 否则 → 用 o 位判定。

**反直觉的结论**：权限 `704`（`rwx---rwx`）时，属组成员反而**读不了**这个文件，因为在第 2 步就命中了全空的 g 位，不会退回去用更宽松的 o 位。面试爱考这个。

root 是例外，拥有 `CAP_DAC_OVERRIDE` 能力，可以无视读写权限（但执行文件时仍要求至少有一个 x 位）。

### 目录上的 rwx 完全是另一套语义

| 位 | 对文件 | 对目录 |
|----|--------|--------|
| `r` | 读内容 | 能 `ls` 列出里面有哪些名字 |
| `w` | 改内容 | 能在里面**新建 / 删除 / 改名**条目（必须同时有 x） |
| `x` | 执行 | 能 `cd` 进入、能访问里面的条目（穿越权限） |

两个重要推论：

- **删除一个文件看的是「所在目录」的 w 权限，不是文件本身的权限**。所以你能删掉一个自己没有写权限、甚至不属于自己的文件——只要目录可写。`/tmp` 靠 **粘滞位（sticky bit）** 来堵这个洞。
- **只有 x 没有 r 的目录**（`--x`）可以「穿过去」访问已知名字的文件，但不能列目录。这是一种常见的加固手法。

### 三个特殊位

| 位 | 八进制 | 作用 | 显示 |
|----|--------|------|------|
| SUID | 4000 | 执行该程序时以**文件属主**身份运行 | `u` 位的 x 变 `s` |
| SGID | 2000 | 对文件：以属组身份运行；对目录：新建文件自动继承目录的组 | `g` 位的 x 变 `s` |
| Sticky | 1000 | 目录内文件只有属主（或 root）能删 | `o` 位的 x 变 `t` |

```bash
ls -l /usr/bin/passwd      # -rwsr-xr-x  → SUID，普通用户改密码时临时以 root 跑
ls -ld /tmp                # drwxrwxrwt  → sticky，人人可写但只能删自己的
```

安全测试里，「查找异常 SUID 程序」是提权排查的固定动作：

```bash
find / -xdev -perm -4000 -type f 2>/dev/null
```

### umask：新建文件的默认权限从哪来

新建文件的权限 = 基准权限 & ~umask。基准：**文件 666、目录 777**（文件默认不给 x）。

```bash
umask            # 通常是 0022
# 文件：666 & ~022 = 644
# 目录：777 & ~022 = 755
umask 077        # 收紧：文件 600、目录 700，处理敏感数据时用
```

## 用法

### chmod：两种写法

```bash
# 数字（绝对）写法：一次性覆盖全部 9 位
chmod 755 deploy.sh          # rwxr-xr-x
chmod 644 app.yaml           # rw-r--r--
chmod 600 id_rsa             # rw------- （SSH 私钥必须）
chmod 700 ~/.ssh
chmod 4755 /usr/local/bin/tool   # 带 SUID

# 符号（相对）写法：只改指定位，其他不动
chmod u+x deploy.sh          # 给属主加执行权
chmod g-w app.yaml           # 去掉属组写权
chmod o=  secret.txt         # 其他人权限清零（等号赋值）
chmod a+r README.md          # 所有人可读
chmod u+x,g+r,o-rwx file
chmod +x script.sh           # 等价 a+x，会受 umask 影响
```

递归与「只改目录不改文件」：

```bash
chmod -R 755 /app                       # 递归，但会把所有文件也加上 x（不推荐）

# 正确姿势：目录 755、文件 644 分开处理
find /app -type d -exec chmod 755 {} +
find /app -type f -exec chmod 644 {} +

# 或者用大写 X：只给「本来就有 x 的文件」和「目录」加 x
chmod -R u=rwX,go=rX /app
```

大写 `X` 是个很实用的技巧：对目录始终生效，对文件只在它已有某个 x 位时才加，正好避免把 `.yaml`、`.log` 全变成可执行文件。

### chown / chgrp：改属主与属组

```bash
chown jenkins app.log            # 只改属主
chown jenkins:jenkins app.log    # 属主与属组一起改
chown :www-data app.log          # 只改属组（等价 chgrp）
chown -R app:app /data/app       # 递归
chown --reference=old.conf new.conf   # 照抄另一个文件的属主属组，改配置后回滚神器
```

`chown` **只有 root 能用**（普通用户不能把自己的文件送给别人，否则可以绕过磁盘配额）。改属组时，普通用户只能改成自己所属的组。

### sudo：什么时候用、怎么用对

```bash
sudo systemctl restart nginx
sudo -u jenkins bash -c 'cd /app && ./deploy.sh'    # 以指定用户执行
sudo -i                                              # 切到 root 的登录 shell
sudo -l                                              # 看当前用户被授权哪些命令
visudo                                               # 编辑 /etc/sudoers（务必用 visudo，它会做语法检查）
```

在 `/etc/sudoers.d/` 里放独立文件比直接改 `/etc/sudoers` 更好维护：

```text
# /etc/sudoers.d/jenkins  —— 只授权必要命令，不要给 ALL
jenkins ALL=(ALL) NOPASSWD: /bin/systemctl restart myapp, /usr/bin/docker
```

### 排查 Permission denied 的标准动作

```bash
id                              # 我是谁、在哪些组
ls -l /path/to/file             # 文件的属主属组与权限
namei -l /data/app/conf.yaml    # 逐级打印路径上每一层的权限（找「哪一层缺 x」）
```

`namei -l` 是被严重低估的命令：文件本身权限没问题、却仍然 `Permission denied`，八成是路径中间某级目录缺 `x`。

## 踩坑

1. **SSH 报 `Permissions 0644 for 'id_rsa' are too open`**。私钥必须 `chmod 600 ~/.ssh/id_rsa`，`~/.ssh` 目录 `700`，`authorized_keys` `600`。而且**家目录本身不能对组/其他人可写**，否则 sshd 会拒绝公钥登录且日志里只写一句含糊的 `Authentication refused: bad ownership`。

2. **`chmod -R 777` 图省事，埋两个雷**。一是安全风险；二是很多服务（sshd、Nginx、crontab、Postfix）会主动检查权限，过宽反而**拒绝工作**。crontab 文件权限不对时，任务会静默不执行。

3. **文件权限没问题但仍然 denied**。路径上某级目录缺 `x`。用 `namei -l 完整路径` 逐级看，别只盯着最后那个文件。

4. **`chmod -R +x` 把配置文件也变成可执行**。用 `chmod -R u=rwX,go=rX` 或 `find -type f/-type d` 分开处理。

5. **属组权限比其他人更严格时，组成员反而访问不了**。命中 g 位就不会退回 o 位。检查是不是写了 `704`、`750` 之类「中间空、末尾宽」的权限。

6. **容器里挂载卷后 uid 对不上**。宿主机上文件属主 uid=1000，容器内进程 uid=1001，就会写不进去。解法是 `docker run --user $(id -u):$(id -g)`，或在 Dockerfile 里显式建同 uid 用户，而不是 `chmod 777` 挂载目录。

7. **改了组但当前会话不生效**。`usermod -aG docker $USER` 之后必须**重新登录**（或 `newgrp docker`），因为附加组是在登录时写进进程凭据的，已有 shell 不会刷新。

8. **`usermod -G` 少写 `-a` 把用户踢出所有其他组**。永远写 `usermod -aG`（append）。

9. **`/tmp` 里删不掉别人的文件**。粘滞位生效，这是设计如此，不是权限配错。

10. **NFS / 网络文件系统上权限行为不一致**。`root_squash` 会把 root 映射成 `nobody`，看到一堆 `nobody:nogroup` 且 root 也改不动，这是服务端策略问题，不是本机权限问题。

## 面试怎么答

**Q：`chmod 754` 是什么意思？**

A：把权限拆成属主 / 属组 / 其他三组，每组 `r=4 w=2 x=1` 相加。7 = rwx，属主可读写执行；5 = r-x，属组可读可执行不可写；4 = r--，其他人只读。对应 `ls -l` 显示 `-rwxr-xr--`。脚本常用 755（大家能执行、只有属主能改），配置文件用 644，私钥必须 600。

**Q：一个文件权限是 `000`，root 能读吗？普通用户属主能读吗？**

A：root 能，因为它有 `CAP_DAC_OVERRIDE`，绕过 DAC 读写检查。属主不能直接读，但属主有 `chmod` 的权力（chmod 只要求你是属主），所以属主可以先 `chmod u+r` 再读——权限对属主而言更像是「防手滑」而不是「防越权」。

**Q：为什么我对一个文件没有写权限，却能把它删掉？**

A：因为删除操作修改的是**父目录**的内容（删掉一条目录项），检查的是父目录的 `w` 和 `x` 权限，跟文件自身权限无关。这也是 `/tmp` 需要粘滞位（`drwxrwxrwt`）的原因——`/tmp` 人人可写，若没有粘滞位，任何人都能删别人的临时文件。加了 sticky bit 之后，目录内的文件只有属主和 root 能删。

**Q：SUID 是什么？为什么它是安全测试的重点？**

A：SUID 位让程序执行时以**文件属主**（通常是 root）的身份运行，而不是调用者的身份。典型例子是 `/usr/bin/passwd`——普通用户要改密码就得写 `/etc/shadow`，只能靠 SUID 临时提权。风险在于，如果一个 SUID 程序存在命令注入、路径可控（比如内部调用 `system("ls")` 而不带绝对路径）、或者干脆是 `find`、`vim`、`bash` 这类能派生 shell 的通用工具被误设了 SUID，攻击者就能直接拿到 root。所以基线检查里必有一条 `find / -perm -4000 -type f`，比对白名单。

**Q：`umask` 是干什么的？**

A：它是「新建文件时要**去掉**哪些权限」的掩码。文件基准 666、目录基准 777，实际权限 = 基准 & ~umask。默认 022 得到文件 644、目录 755。需要处理敏感数据（密钥、报告）时在脚本里设 `umask 077`，让新建文件只有自己能读。注意 umask 是进程属性，会被子进程继承，改它要在脚本开头做。

## 参考

- [`chmod` 官方手册（GNU Coreutils）](https://www.gnu.org/software/coreutils/manual/html_node/chmod-invocation.html)
- [`path_resolution(7)` man page](https://man7.org/linux/man-pages/man7/path_resolution.7.html)
- 相关笔记：[[Linux 文件与目录操作]]
- 相关笔记：[[ssh 与 scp 远程操作]]
