---
title: "SSH 與遠端管理 常見故障排除"
desc: "依症狀查的故障排除索引：判斷分流、處置步驟與一頁式急救卡，原理連回原文"
aliases: [SSH 與遠端管理故障排除, SSH 與遠端管理排錯]
tags: [群組/Linux, 主題/故障排除]
category: SSH與遠端管理
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: []
updated: 2026-08-29
---

# SSH 與遠端管理 常見故障排除

> [!abstract] 怎麼用這份手冊
> - 依「你看到什麼症狀」查，不是依「這屬於什麼技術」查
> - 找到症狀 → 看判斷分流 → 照處置步驟做 → 想懂原理再點進原文
> - ★★★★ 緊急時直接跳到最下面的「一頁式急救卡」
> - ★★★★★ 本手冊**不重講原理**。每個情境結尾的「原理詳見」就是原文入口，
>   照著點進去看，不要在這裡找教學。

## 快速索引（依症狀）

| 症狀（你會看到的） | 最可能的原因 | 先下這個指令 | 原理詳見 |
| --- | --- | --- | --- |
| ★★★★★ `connect to host X port 22: Connection refused` | 封包有到，那個埠上卻沒人聽：sshd 沒跑、埠改過、連錯機器 | `nc -zv <主機> 22` | [[020-02-01-01-cmd-SSH-原理與第一次連線]] |
| ★★★★★ `connect to host X port 22: Connection timed out`（卡很久） | 封包被靜默丟棄：防火牆 DROP、路由不通、機器沒開 | `nc -zv <主機> 22` | [[020-02-01-01-cmd-SSH-原理與第一次連線]] |
| ★★★★★ `Permission denied (publickey).` | 前四階段全過，純粹是使用者認證被拒 | 伺服器端 `journalctl -u ssh \| grep -i refused` | [[020-02-01-02-cmd-SSH-金鑰認證與ssh-agent]] |
| ★★★★★ 滿畫面 `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!` | 主機金鑰換了：重灌／換機／LB 後端不同／**或真的被中間人攔截** | `ssh-keygen -lF <主機>` | [[020-02-01-01-cmd-SSH-原理與第一次連線]] |
| ★★★★★ 改完 `sshd_config` 重啟後，所有人（含自己）都連不進去 | 語法錯、`AllowGroups` 漏了自己、`ListenAddress` 綁到不存在的 IP | 主控台 `sudo sshd -t` | [[020-02-01-04-svc-sshd-伺服器端設定]] |
| ★★★★★ 設了 `PasswordAuthentication no`，還是跳出密碼提示且能登入 | `KbdInteractiveAuthentication` 預設 `yes`，走 PAM 一樣驗密碼 | `sudo sshd -T \| grep -Ei 'passwordauth\|kbdinteractive'` | [[020-02-01-07-svc-SSH-安全強化]] |
| ★★★★ `Too many authentication failures`，而你確定金鑰是對的 | agent 裡金鑰太多，還沒輪到對的就撞上 `MaxAuthTries` | `ssh -o IdentitiesOnly=yes -i <金鑰> <主機>` | [[020-02-01-03-svc-SSH-客戶端設定檔]] |
| ★★★★ 改了 `~/.ssh/config` 完全沒反應，`ssh -G` 也是舊值 | `Host *` 排在前面 —— ssh_config 是**第一個值勝出** | `ssh -G <別名>` | [[020-02-01-03-svc-SSH-客戶端設定檔]] |
| ★★★★ `ssh -G` 顯示新值，實際連進去仍是舊行為 | ControlPersist 舊 socket 還活著，連線根本沒重建 | `ssh -O check <別名>` | [[020-02-01-03-svc-SSH-客戶端設定檔]] |
| ★★★★ 在主檔末尾改的 sshd 設定完全沒作用 | `Include` 在第 1 行，被 `sshd_config.d/` 裡編號更小的檔蓋掉 | `sudo sshd -T \| grep -i <關鍵字>` | [[020-02-01-04-svc-sshd-伺服器端設定]] |
| ★★★★ 改了 `Port 2222` 卻還是聽 22，`ss` 顯示 Process 是 `systemd` | Ubuntu 22.10+ socket activation，`sshd_config` 的 `Port` 被忽略 | `sudo ss -lntp \| grep :22` | [[020-02-01-04-svc-sshd-伺服器端設定]] |
| ★★★★ `channel N: open failed: administratively prohibited` | **伺服器拒絕轉發**：`AllowTcpForwarding`／`PermitOpen`／金鑰上的 `restrict` | `sudo sshd -T -C user=<帳號>,host=x,addr=<IP>` | [[020-02-01-05-cmd-SSH-隧道與埠轉發]] |
| ★★★★ SFTP 帳號一連上就 `Connection closed` | chroot 路徑某一層不是 root 擁有、或 group/other 可寫 | `namei -l /srv/sftp/<帳號>` | [[020-02-01-06-svc-SFTP-與受限使用者]] |
| ★★★★ 公鑰已部署卻仍要密碼，客戶端看不出任何原因 | 家目錄／`.ssh`／`authorized_keys` 權限太寬，`StrictModes` 靜默忽略 | 伺服器端 `journalctl -u ssh \| grep -i 'bad ownership'` | [[020-02-01-02-cmd-SSH-金鑰認證與ssh-agent]] |
| ★★★★ `Could not open a connection to your authentication agent.` | `SSH_AUTH_SOCK` 沒帶到：新終端、`sudo` 之後、cron／systemd | `ssh-add -l; echo "$SSH_AUTH_SOCK"` | [[020-02-01-02-cmd-SSH-金鑰認證與ssh-agent]] |
| ★★★★ 加固之後備份／監控任務全紅，卻沒有任何人回報錯誤 | `AllowGroups` 漏了服務帳號，或老客戶端演算法被擋 | `sudo journalctl -u ssh \| grep -i 'not allowed'` | [[020-02-01-07-svc-SSH-安全強化]] |
| ★★★ `kex_exchange_identification: read: Connection reset by peer` | TCP 通了卻立刻被踢：fail2ban 封鎖、`MaxStartups` 滿、IPS 阻擋 | `sudo fail2ban-client status sshd` | [[020-02-01-01-cmd-SSH-原理與第一次連線]] |
| ★★★ `Unable to negotiate … no matching key exchange method found` | 演算法加固後，老客戶端／老設備談不攏 | `ssh -vv <主機> 2>&1 \| tail -3` | [[020-02-01-07-svc-SSH-安全強化]] |

## 依情境展開

### ★★★★★ 情境一：完全連不上，畫面停在那裡或立刻被拒

**現象**：三種畫面，處理方向**完全相反**，第一件事就是分清楚是哪一種。

```text
（A）ssh: connect to host 192.168.20.31 port 22: Connection refused
     ★★★★ 幾乎是「秒回」，按下 Enter 馬上跳出來
（B）ssh: connect to host 192.168.20.31 port 22: Connection timed out
     ★★★★ 游標卡住二十秒到兩分鐘才跳出來
（C）kex_exchange_identification: read: Connection reset by peer
     ★★★ TCP 明明通了，卻在交握第一句話就被切斷
```

**判斷分流**：

```bash
$ getent hosts srv-web01 && nc -zv 192.168.20.31 22
192.168.20.31   srv-web01.example.gov.tw srv-web01
Connection to 192.168.20.31 22 port [tcp/ssh] succeeded!
```

- `getent` 沒輸出 → ★★★ 是 DNS／`/etc/hosts` 問題，**跟 SSH 無關**，先修名稱解析
- 解出來的 IP 不是你以為的那台 → DNS 快取或 DHCP 換過位址，先確認要連的到底是誰
- `succeeded!` → TCP 通的，問題在認證，跳**情境二**
- 秒回 `refused` → 走【1】｜卡住到逾時 → 走【3】｜`reset by peer` → 走【4】

**處置步驟**：

【1】`refused`：到主機端（主控台或另一條既有連線）確認服務在不在、聽哪個埠。

```bash
$ sudo ss -lntp | grep -E ':(22|2222)\s'
LISTEN 0 4096 *:22 *:* users:(("sshd",pid=4210,fd=3))
```

- 完全沒輸出 → ★★★★ 服務真的沒跑：`sudo systemctl start ssh`（RHEL 是 `sshd`）
- `users:(("systemd",pid=1,...))` → ★★★★ socket activation 模式，這是正常的，
  但 `sshd_config` 的 `Port` 不會生效，跳**情境六**【5】
- 有在聽但埠號不是 22 → 有人改過埠，用 `ssh -p <埠>` 連

【2】服務正常聽 22 卻仍 `refused`：你連到的**不是這台機器**。查 ARP 與 DHCP 租約，
確認 IP 沒被別台機器搶走：`ip neigh show 192.168.20.31`。

【3】`timed out`：這是防火牆或路由，**不要再在 SSH 上找答案**。

```bash
$ sudo ufw status verbose | grep -E '22|2222'          # RHEL：firewall-cmd --list-all
22/tcp                     ALLOW IN    10.10.0.0/24
```

★★★★ 重點是**放行的來源網段有沒有涵蓋你**。很多人看到「有 22/tcp 這條」就跳過，
其實自己的網段根本不在裡面。規則寫法見 [[090-02-02-guide-防火牆-ufw基礎與實務]]。

【4】`reset by peer`：TCP 通了卻被主動切斷，三個常見兇手。

```bash
$ sudo fail2ban-client status sshd
|- Currently banned: 1
`- Banned IP list:   10.10.90.14        # ★★★★ 你自己的 IP 被鎖了
```

- 自己在封鎖名單 → `sudo fail2ban-client set sshd unbanip 10.10.90.14`，
  ★★★★ 但**先修好造成反覆失敗的根因**（通常是情境五）再重試，否則馬上又被鎖
- `journalctl -u ssh` 出現 `beyond MaxStartups` → 連線數爆掉，多半有腳本在暴衝或正被掃
- 日誌**一行都沒有** → 請求根本沒到 sshd，是中間的 IPS／資安設備切的

【5】最後手段：兩邊同時抓包，看 TCP 走到哪一步。

```bash
$ sudo tcpdump -i any -nn 'tcp port 22 and host 192.168.20.10'
IP 192.168.20.10.52288 > 192.168.20.31.22: Flags [S], seq 1024...
IP 192.168.20.31.22 > 192.168.20.10.52288: Flags [R.], seq 1, ack 1025...
       # ★★★ 立刻回 RST = 沒人聽或被 REJECT；只有 [S] 沒有任何回應 = 封包在中途被吃掉
```

**原理**：SSH 連線分六個階段，`refused`／`timeout` 卡在第一階段（TCP），
`reset` 卡在第二階段（版本交換）。知道卡在哪一階段，排查方向就固定了。
　→ 原理詳見 [[020-02-01-01-cmd-SSH-原理與第一次連線]]

**預防**：
- ★★★★ 改防火牆一律「**先加新規則、確認能連、再刪舊規則**」，順序不可顛倒
- ★★★★ 把維運網段寫進 fail2ban 的 `ignoreip`，避免排錯時把自己鎖掉
  （見 [[090-02-05-guide-防護-Fail2ban入侵防護]]）
- ★★★ 重要主機用固定 IP 或 DHCP 保留，不要靠動態租約

### ★★★★★ 情境二：`Permission denied (publickey).` —— 金鑰登不進去

**現象**：`ssh ops@10.10.20.31` 只回一行 `ops@10.10.20.31: Permission denied (publickey).`

★★★★ 這行代表**前四個階段全部成功**（TCP、版本、演算法、主機金鑰都過了），
問題**純粹在使用者認證**。網路、防火牆、sshd 有沒有跑，全部不必再查。

**判斷分流**：

```bash
$ ssh -v -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519_ops ops@10.10.20.31 true 2>&1 \
    | grep -E 'Offering|Server accepts key'
debug1: Offering public key: /home/wangxm/.ssh/id_ed25519_ops ED25519 SHA256:cNg... explicit
debug1: Server accepts key: /home/wangxm/.ssh/id_ed25519_ops ED25519 SHA256:cNg... explicit
```

- 有 `Server accepts key` 卻仍失敗 → 金鑰沒問題，是**登入之後**的階段，跳【5】
- 只有 `Offering` 沒有 `accepts` → 伺服器不接受這把 → 走【1】
- 連 `Offering` 都沒有 → 客戶端根本沒讀到金鑰檔 → 跳【4】
- `Offering` 了三把以上 → 跳**情境五**

**處置步驟**：

【1】★★★★★ 最關鍵的一步：**去看伺服器端日誌**。客戶端永遠只會說
`Permission denied (publickey).`，真正的原因只在伺服器上。

```bash
$ sudo journalctl -u ssh --since '5 min ago' --no-pager | grep -iE 'refused|invalid|not allowed|expired'
Aug 28 10:31:02 web01 sshd[2841]: Authentication refused: bad ownership or modes for directory /home/ops
```

| 日誌訊息 | 問題在哪 | 下一步 |
| --- | --- | --- |
| ★★★★ `bad ownership or modes for directory …` | 家目錄對 group/other 可寫 | 走【2】 |
| ★★★★ `bad ownership or modes for file …authorized_keys` | 檔案權限或擁有者不對 | 走【2】 |
| ★★★★ `Authentication refused: expired key` | `expiry-time=` 到期 | 更新選項欄或輪替金鑰 |
| ★★★★ `client IP address not allowed` | `from=` 不符 | 走【3】確認真實來源 IP |
| ★★★★ `not allowed because none of user's groups are listed in AllowGroups` | 帳號不在允許群組 | `sudo usermod -aG ssh-users ops` |
| ★★★ `account has expired` | `chage -E` 到期 | `sudo chage -l ops` 確認 |
| ★★★ `Public key SHA256:... blacklisted` | 命中 `RevokedKeys` 的 KRL | 這把已被撤銷，重新簽發 |
| ★★★★★ **完全沒有任何訊息** | 連線根本沒到 sshd | 回**情境一** |

RHEL 系請用 `sudo journalctl -u sshd` 或 `sudo tail -50 /var/log/secure`。
看不到細節時把 `LogLevel` 調成 `VERBOSE`。

【2】權限：★★★★ 最常見的原因，而且客戶端**完全看不出來**。

```bash
$ sudo ls -ld /home/ops /home/ops/.ssh /home/ops/.ssh/authorized_keys
drwxrwxr-x 5 ops  ops  4096 Aug 28 09:00 /home/ops          # ★★★★ group 有 w → 就是它
drwx------ 2 ops  ops  4096 Aug 28 09:00 /home/ops/.ssh
-rw------- 1 root root  742 Aug 28 09:00 /home/ops/.ssh/authorized_keys   # ★★★★ owner 錯
```

```bash
sudo chmod go-w /home/ops
sudo chmod 700 /home/ops/.ssh && sudo chmod 600 /home/ops/.ssh/authorized_keys
sudo chown -R ops:ops /home/ops/.ssh
```

★★★★ RHEL 上權限全對還是不行，八成是 SELinux context 不對（手動建目錄或用 `cp` 造成）：
`sudo restorecon -R -v /home/ops/.ssh`，再 `sudo ausearch -m avc -ts recent | grep ssh` 確認。

【3】確認公鑰真的在檔案裡、而且沒被編輯器換行截斷；`from=` 相關要先知道伺服器**實際看到**的來源 IP。

```bash
$ ssh-keygen -lf ~/.ssh/id_ed25519_ops.pub            # 客戶端
256 SHA256:cNgXnpcfTlWLmrBBnVB63+416+aHzJNnF/R1+K+gMlQ ops-wangxm-2026 (ED25519)
$ sudo ssh-keygen -lf /home/ops/.ssh/authorized_keys  # 伺服器端，要出現同一串 SHA256
$ ssh ops@10.10.20.31 'echo $SSH_CONNECTION'
10.10.90.14 51422 10.10.20.31 22      # ★★★★ 第一欄才是 from= 該寫的位址
```

★★★★ 伺服器端印出的行數比你貼進去的少 = 有公鑰被截斷。走 NAT 或跳板時，
`$SSH_CONNECTION` 的第一欄**不會**是你筆電的 IP。

【4】客戶端讀不到金鑰檔。★★★ 注意：**ssh 不會因為 `IdentityFile` 指向不存在的檔案而報錯**，
它只是安靜地不送那把。

```bash
$ ssh -G 10.10.20.31 | awk '$1=="identityfile"{print $2}' | while read -r f; do
    p="${f/#\~/$HOME}"; test -f "$p" && echo "OK   $p" || echo "MISS $p"; done
MISS /home/wangxm/.ssh/id_rsa
OK   /home/wangxm/.ssh/id_ed25519_ops
```

★★★ 最常見的打字錯誤：寫成 `~/ssh/` 少了那個點、`_ops` 寫成 `-ops`。
私鑰本身能不能開啟用 `ssh-keygen -y -f <私鑰>` 驗：
`bad permissions` → `chmod 600`；`error in libcrypto` → 檔案損毀或被改成 CRLF，從備份復原。

【5】`Server accepts key` 卻還是進不去：問題在登入之後。

```bash
$ sudo getent passwd ops | cut -d: -f7; sudo passwd -S ops
/usr/sbin/nologin                     # ★★★★ shell 是 nologin
ops L 2026-08-01 0 99999 7 -1         # ★★★ L = 帳號被鎖
```

`command=` 綁死指令的金鑰若「登入後立刻斷線」，★★★ 常見原因是包裝腳本沒有 `+x`、
shebang 寫錯，或該帳號沒有可執行的 shell（`command=` 仍需要 shell 來啟動它）。

**原理**：sshd 的 `StrictModes` 會在**權限太寬時靜默忽略** `authorized_keys`，
客戶端只看得到一句籠統的 `Permission denied (publickey).`。
　→ 原理詳見 [[020-02-01-02-cmd-SSH-金鑰認證與ssh-agent]]

**預防**：
- ★★★★★ 部署完公鑰**一定要另開新終端實測**，舊終端不要關
- ★★★★ 用 `ssh-copy-id` 或 `cat >> ... <<'EOF'` 部署，不要用滑鼠貼進編輯器
- ★★★ 服務帳號的金鑰統一加 `from=` 與 `expiry-time=`，並排入每季盤點

### ★★★★★ 情境三：改壞設定，把自己鎖在門外了

**現象**：你剛剛 `systemctl restart ssh`，然後 `ssh admin@10.10.0.20` 回
`Connection refused`（服務起不來），或 `Permission denied (publickey,password).`（設定把你擋掉）。

★★★★★ **先深呼吸，然後檢查一件事：你原本那個終端機還在嗎？**
`reload` 與 `restart` 都**不會**踢掉已建立的連線 —— 舊 session 是獨立的子程序。
只要沒有 `exit`、沒有關掉它，它就是現成的逃生梯，什麼都還來得及。

**判斷分流**：按這個順序找退路，**由便宜到昂貴**。

```text
① 原本那個 SSH 終端機還開著嗎？        → 有 → 路徑 A，兩分鐘解決
② 同一台上還有別的既有連線嗎？          → tmux／screen／同事的 session（w 看得到）
③ IPMI / iDRAC / iLO 可以登入嗎？      → 有 → 路徑 B
④ 這是 PVE / VMware 上的 VM 嗎？       → 是 → 路徑 B（網頁 console）
⑤ 這是公有雲主機嗎？                   → 是 → 路徑 B（serial console，可能要先啟用）
⑥ 事前有掛自動回滾 timer 嗎？          → 有 → 路徑 C，什麼都不用做，等它
⑦ 以上全沒有                           → 路徑 D，最壞的情況
```

**處置步驟**：

【路徑 A】★★★★★ 舊連線還活著 —— **不要關它，也不要在裡面亂試新指令**。

```bash
$ sudo sshd -t                       # 先看語法錯在哪；沒有輸出就是過
/etc/ssh/sshd_config.d/50-gov-baseline.conf line 12: Bad configuration option: AllowGroup
/etc/ssh/sshd_config.d/50-gov-baseline.conf: terminating, 1 bad configuration options
$ sudo sshd -T | grep -Ei 'port|listenaddress|allowgroups|permitrootlogin|passwordauth'
port 2222                            # ★★★★ 埠被改了，要用 -p 2222 連
allowgroups ssh-admins               # ★★★★ 你在不在這個群組？id 一下
```

最快的復原是把剛加的檔案先移走，確認能連之後再回頭慢慢修：

```bash
sudo mv /etc/ssh/sshd_config.d/50-gov-baseline.conf /root/50-gov-baseline.conf.broken
sudo sshd -t && sudo systemctl reload ssh
```

★★★★ **然後立刻在第二個終端機測新連線**，成功了才算完：

```bash
$ ssh -o ControlPath=none -o ControlMaster=no admin@10.10.0.20 'echo NEW-SESSION-OK'
NEW-SESSION-OK
```

【路徑 B】★★★★ 走頻外管理（IPMI／iDRAC／iLO／PVE console／雲端 serial console）。
拿到 login prompt 之後做的事跟路徑 A 完全一樣。兩個常見絆腳石：

- ★★★★ console 只給本機登入，而你把 `PermitRootLogin` 關了又忘了本機管理員密碼 → 只能走路徑 D
- ★★★ 雲端 serial console 多半要先在主控台**啟用**，事到臨頭才啟用可能得重開機

【路徑 C】★★★★ 事前掛了自動回滾 timer —— 什麼都不用做，坐著等；事後用
`journalctl -u sshd-rollback` 確認它確實跑過。

【路徑 D】★★★★★ 沒有任何遠端途徑 —— 只剩實體接觸。

- 實體機：接螢幕鍵盤，開機進單一使用者模式／`init=/bin/bash`，掛成可寫後還原 `sshd_config` 備份
  （見 [[020-01-25-guide-Linux-開機流程與GRUB救援]]）
- 虛擬機：掛救援 ISO 開機，或直接還原前一份快照／備份（見 [[050-01-03-06-svc-PVE-備份與還原]]）
- ★★★★ 兩者都做不到 → 這台機器等於報廢重建。**這就是為什麼要事前預防。**

**原理**：`reload` 送出的 `SIGHUP` 只讓 sshd 主程序重讀設定，
**已建立的連線是獨立子程序，完全不受影響**。而 `sshd -t` 只驗語法，
**不會告訴你會不會被鎖在外面**（`AllowGroups nobody-at-all` 語法完全正確）。
　→ 原理詳見 [[020-02-01-04-svc-sshd-伺服器端設定]]

**預防**：★★★★★ 這一段是全章最該背起來的東西，**七道保險，動 sshd 設定前逐項做**。

```text
 ① 保留一條已登入的 session，全程不要關      ← 最便宜、最有效
 ② sudo sshd -t                              語法檢查（沒輸出 = 過）
 ③ sudo sshd -T / sshd -T -C ...             驗證「真正生效的值」
 ④ systemd-run --on-active=5m 自動回滾 timer  ← 保險絲，套用【之前】就掛好
 ⑤ /usr/sbin/sshd -D -p 2222 -f 新檔          在另一個埠前景試跑
 ⑥ 確認 IPMI / iDRAC / console【現在】能登入  最後一條路
 ⑦ systemctl reload ssh（不是 restart）
```

```bash
$ sudo cp -a /etc/ssh/sshd_config /etc/ssh/sshd_config.bak
$ sudo systemd-run --on-active=5m --unit=sshd-rollback \
    /bin/sh -c 'cp -a /etc/ssh/sshd_config.bak /etc/ssh/sshd_config && systemctl reload ssh'
Running timer as unit: sshd-rollback.timer
$ sudo systemctl stop sshd-rollback.timer     # ★★★★★ 驗證新連線成功後一定要停掉
```

> [!danger] ★★★★★ 忘了停 timer 的後果比你想的糟
> 你改好設定、測試通過、關掉筆電去吃飯 —— 五分鐘後設定被自動還原，
> 但**防火牆、客戶端 `~/.ssh/config`、監控系統都還照新設定在跑**。
> 下午回來一堆「連不上」告警，而設定檔看起來完全正常（因為它已經被還原了）。
> 這種案件極難查。**「驗證完立刻停 timer」要練成肌肉記憶。**

★★★★ 換埠也要「先加後減」，不要一次把舊埠關掉 —— 先讓 sshd 同時聽 `Port 22` 與
`Port 2222`，確認新埠連得上，隔幾天再拿掉舊的。

★★★★★ 還有一個很多人忽略的前置條件：**頻外管理要「現在」就驗一次**，不是「應該能用」。
機關最常見的事故起點就是「iDRAC 密碼是三年前同事設的，沒人知道」。

### ★★★★★ 情境四：滿畫面的 `REMOTE HOST IDENTIFICATION HAS CHANGED!`

**現象**：

```text
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
IT IS POSSIBLE THAT SOMEONE IS DOING SOMETHING NASTY!
The fingerprint for the ED25519 key sent by the remote host is
SHA256:7bQvL2xR9dK4mN8sT0uY3wZ6cA1eG5hJ2kP4nX7rV9M.
Offending ECDSA key in /home/wangxm/.ssh/known_hosts:14
```

> [!danger] ★★★★★ 絕對不要反射性地執行 `ssh-keygen -R`
> 這個警告有四種成因，其中一種是**你真的正在被攔截**。
> 直接刪掉記錄再連進去 = 主動把帳號密碼交給攻擊者，而且抹掉了唯一的證據。
> **先分流，再處置。這是本章唯一「先停手」的情境。**

**判斷分流**：三個指紋要對照，**判準是第三個**。

```bash
# 【a】對方現在送過來的指紋（★★★ 只讀不登入，不會污染 known_hosts）
$ ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -v srv-web01 2>&1 | grep 'Server host key'
debug1: Server host key: ssh-ed25519 SHA256:7bQvL2xR9dK4mN8sT0uY3wZ6cA1eG5hJ2kP4nX7rV9M
# 【b】known_hosts 目前記著的
$ ssh-keygen -lF srv-web01
# Host srv-web01 found: line 14
srv-web01 SHA256:kV3mQ0Zc8pQ2rT1sXhN9dW7bLyF4uJ6aE0oG5PnRcIs
# 【c】★★★★★ 到主機 console 上取「真值」—— 這是唯一的判準
$ sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
256 SHA256:7bQvL2xR9dK4mN8sT0uY3wZ6cA1eG5hJ2kP4nX7rV9M root@srv-web01 (ED25519)
```

```text
【c】==【a】                → 成因①：主機真的換過 key（重灌／重建）→ 走【1】
【c】==【b】                → ★★★★★ 成因④：有人在中間 → 立刻停手，走【3】
console 連不上、IP 上是別台 → 成因②：IP 被別人拿走 → 走【2】
這台在 LB／VIP 後面        → 成因③：輪到不同的後端 → 走【2】
```

★★★★★ 上面【a】那條指令**只能用來讀指紋，絕對不可以真的登入或輸入密碼**。

**處置步驟**：

【1】確認是自己重灌／重建造成的：刪掉舊記錄，重新做一次帶外驗證再登記。

```bash
$ ssh-keygen -R srv-web01 && ssh-keygen -R 192.168.20.31   # ★★★ 用 IP 連過的也要刪
$ ssh srv-web01
ED25519 key fingerprint is SHA256:7bQvL2xR9dK4mN8sT0uY3wZ6cA1eG5hJ2kP4nX7rV9M.
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

★★★ 這裡可以**直接貼上整串 `SHA256:...`**，不符時 ssh 會拒絕放行 —— 比人眼比對可靠得多。

【2】成因②③：先用 `ip neigh show <IP>` 確認那個 IP 上的機器到底是誰（MAC 有沒有變），
不要急著改 known_hosts。LB／VIP 後面有多台時，正解是**讓所有後端共用同一組 host key**，
或改用 SSH 主機憑證。

【3】★★★★★ 成因④，懷疑中間人：**立刻停手**。

- ✗ 不要再嘗試連線、不要輸入密碼；✗ **不要執行 `ssh-keygen -R`（那是在銷毀證據）**
- ✓ 保留當下的終端機輸出（截圖／存檔）並記下時間，拔掉這台工作站的網路
- ✓ 改用另一條可信路徑聯絡，依 [[090-07-04-guide-資安實踐-資安事件應變流程]] 通報

**原理**：SSH 的信任模型是 TOFU（第一次使用時信任），known_hosts 記的就是那次的指紋。
指紋變了只有兩種可能 —— 對方換了身分，或者你連到的根本不是對方。
　→ 原理詳見 [[020-02-01-01-cmd-SSH-原理與第一次連線]]

**預防**：
- ★★★★★ 新機上架時就在 console 上抄下指紋、寫進資產紀錄，第一次連線用它比對
- ★★★★ 全機關共用一份 `/etc/ssh/ssh_known_hosts`，由組態管理派送，個人不必各自 TOFU
- ★★★★★ 規模大了就導入 SSH 主機憑證，一勞永逸（見 [[020-02-01-07-svc-SSH-安全強化]]）
- ★★★★★ **永遠不要**為了省事設 `StrictHostKeyChecking no` —— 那等於把這道警告永久關掉

### ★★★★ 情境五：`Too many authentication failures`，但你確定金鑰是對的

**現象**：`Received disconnect from 10.10.20.31 port 22:2: Too many authentication failures`

★★★★ 這個坑的難處在於：**你的金鑰確實是對的，也確實在 agent 裡**。
但 ssh 會把 agent 裡**所有**金鑰依序送出去試，伺服器的 `MaxAuthTries`（預設 6，
加固過的常設成 3）在輪到正確那把之前就先把你踢掉了。

**判斷分流**：

```bash
$ ssh -v 10.10.20.31 2>&1 | grep -c 'Offering public key'; ssh-add -l | wc -l
6        # ★★★★ 送出了 6 把 → 確定是這個問題
9        # agent 裡有 9 把
```

- 送出三把以上 → 走【1】｜只送一把仍失敗、或一把都沒送 → 回**情境二**

**處置步驟**：

【1】立刻能用的解法 —— 只送指定的那把。

```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519_ops ops@10.10.20.31
```

★★★★ `IdentitiesOnly=yes` 的意思是「**只用我明確指定的金鑰**」。
少了它，`-i` 只是「多加一把候選」，agent 裡那一堆還是照送。

【2】長久解法：寫進 `~/.ssh/config`，逐站指定，並在 `Host *`（放檔案最後）設全域預設。

```text
Host web01
    HostName 10.10.20.31
    User ops
    IdentityFile ~/.ssh/id_ed25519_ops
    IdentitiesOnly yes

Host *
    IdentitiesOnly yes
```

```bash
$ ssh -G web01 | grep -Ei 'identityfile|identitiesonly'
identityfile ~/.ssh/id_ed25519_ops
identitiesonly yes
```

【3】臨時清空 agent（會影響其他連線，慎用）：`ssh-add -D && ssh-add ~/.ssh/id_ed25519_ops`。

【4】★★★★ 順手檢查有沒有因為反覆失敗被 fail2ban 鎖起來：`sudo fail2ban-client status sshd`。

**原理**：`MaxAuthTries` 算的是**單一連線內的認證嘗試次數**，agent 裡每把金鑰都算一次。
沒有 `IdentitiesOnly yes` 時，ssh 還會順便把你所有金鑰的公鑰指紋送給對方（資訊外洩）。
　→ 原理詳見 [[020-02-01-03-svc-SSH-客戶端設定檔]]

**預防**：★★★★ 在 `~/.ssh/config` 的 `Host *` 區塊永久設上 `IdentitiesOnly yes`，
每個 Host 明確指定 `IdentityFile`。這是必設項，不是可選項。

### ★★★★ 情境六：改了設定完全沒生效

**現象**：改了設定、也重載了，行為卻一模一樣。**先分清楚改的是哪一邊** —— 客戶端
`~/.ssh/config` 走【1】【2】，伺服器 `sshd_config` 走【3】～【5】。

**判斷分流**：

```bash
$ ssh -G web01 | awk '$1 ~ /^(hostname|user|port|proxyjump)$/'    # 客戶端
user deploy
hostname 10.10.20.11
port 2222
$ sudo sshd -T | grep -Ei 'passwordauth|kbdinteractive|permitrootlogin|allowgroups|port'  # 伺服器端
passwordauthentication yes
```

```text
hostname 印出來 == 你打的別名   → ★★★★ 沒有任何 Host 區塊匹配到（拼字／大小寫）→【1】
user / port 跟你寫的不一樣      → ★★★★★ Host * 排前面了 →【1】
ssh -G 是新值、實際卻是舊行為   → ★★★★ ControlMaster 舊 socket →【2】
Bad configuration option        → 語法錯，照錯誤行號直接改
sshd -T 跟檔案裡寫的不一樣      → 被別的檔案蓋掉 →【3】
sshd -T 對，但特定人拿到不一樣   → 被寫在 Match 之後 →【4】
改了 Port 沒生效，ss 顯示 systemd → socket activation →【5】
```

**處置步驟**：

【1】★★★★★ 客戶端最大的坑：`ssh_config` 是**第一個值勝出**，不是後面覆蓋前面。

```bash
$ ssh -vvv -o ConnectTimeout=1 web01 true 2>&1 | grep -E 'Including file|Applying options'
debug3: ... Including file /home/opsadmin/.ssh/config.d/20-prod.conf depth 0
debug1: .../90-defaults.conf line 6: Applying options for *
debug1: .../20-prod.conf line 8: Applying options for web01
```

- ★★★★★ `for *` 出現在 `for web01` **之前** → 就是它。`Host *` 一旦排前面，
  底下每個參數都被鎖死，所有具體主機的設定通通失效 → **把 `Host *` 移到整份檔案最後**
  （用 config.d 分檔時，檔名前綴取 `90-`）
- 沒有 `Applying options for web01` → 別名拼錯，或該檔沒被 `Include`（`Including file`
  也沒列出你以為會載入的檔時，是 glob 沒對上 —— 副檔名不是 `.conf`？）

【2】★★★★ `ssh -G` 對了但行為不對：**ControlMaster 舊 socket 還活著**，
你的「重新連線」其實走舊通道，根本沒重讀設定、也沒重新認證。

```bash
$ ssh -O check web01 && ssh -O exit web01 && ls -l ~/.ssh/cm/
Master running (pid=48213)     # ★★★★ 有 master → 新設定不會生效
Exit request sent.
total 0                         # ★★★ 乾淨了，現在重連才算數
```

★★★ 回 `No such file or directory` 代表本來就沒有 master，這條線索排除。
★★★ 看到 `ControlPath too long (... >= 108 bytes)` → 把 `ControlPath` 改成 `~/.ssh/cm/%C`
（UNIX socket 路徑硬性上限 108 bytes）。

【3】★★★★★ 伺服器端最大的坑：`Include /etc/ssh/sshd_config.d/*.conf` 在主檔**第 1 行**，
加上「第一個值勝出」，所以**寫在主檔末尾的設定永遠輸給 drop-in**。

```bash
$ sudo grep -rn -i 'passwordauthentication' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/ | sort
/etc/ssh/sshd_config:120:PasswordAuthentication no                       # 你加的，輸了
/etc/ssh/sshd_config.d/50-cloud-init.conf:1:PasswordAuthentication yes   # ★★★★★ 這個贏
```

解法：把設定寫進 `sshd_config.d/`，取**字典序更前面**的檔名（例如 `49-`），
或停用衝突的那個檔。改完一律用 `sudo sshd -T` 驗證，不要看檔案內容自我安慰。

★★★★ RHEL 特例：`Ciphers`／`MACs` 被 `/etc/sysconfig/sshd` 的 `CRYPTO_POLICY=`
以命令列參數塞入，**優先於任何設定檔**。要改就用 `sudo update-crypto-policies --set`。

【4】★★★★ 設定看起來對，但特定人拿到的不一樣 → 那一行被寫在 `Match` **之後**了。

```bash
$ sudo awk '/^Match/{m=1} m && /^[A-Za-z]/ {print FILENAME": "FNR": "$0}' \
    /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf | head
50-gov-baseline.conf: 44: Match Group ssh-admins Address 10.10.0.0/24
$ sudo sshd -T -C user=ops,host=web01,addr=203.0.113.9 | grep -Ei 'allowgroups|maxauthtries'
allowgroups ssh-remote
maxauthtries 2          # ★★★ 與全域不同 → 證明 Match Address 有命中
```

★★★★ `Match` 的效力一路延伸到「下一個 `Match` 或檔案結尾」。在它後面多寫一行
「以為是全域」的設定，那行就只對那個條件生效。**規則：`Match` 一律放整個檔案最後面。**
輸出跟全域一模一樣 → `Match` 沒命中，多半是走 NAT 後 IP 不是你以為的那個。

【5】★★★★ Ubuntu 22.10 以後的 socket activation：`sshd_config` 的 `Port` **不被使用**。

```bash
$ sudo ss -lntp | grep -E ':(22|2222)\s'
LISTEN 0 4096 *:22 *:* users:(("systemd",pid=1,fd=93))    # ★★★★ 是 systemd 不是 sshd
$ sudo systemctl edit ssh.socket
```

```ini
[Socket]
ListenStream=
ListenStream=2222
```

★★★★★ **第一行那個空的 `ListenStream=` 是必要的** —— 它負責清掉原本的 22。
少了它，systemd 是「追加」不是「取代」，結果會變成 22 和 2222 同時在聽。
改完要 `sudo systemctl daemon-reload && sudo systemctl restart ssh.socket`。

**原理**：`ssh_config` 與 `sshd_config` 都是**第一個值勝出**，
而 `sshd -T`／`ssh -G` 印的是「讀完全部檔案之後真正要用的值」—— 這是唯一可信的答案。
　→ 原理詳見 [[020-02-01-04-svc-sshd-伺服器端設定]]、[[020-02-01-03-svc-SSH-客戶端設定檔]]

**預防**：
- ★★★★★ 客戶端 `Host *` 永遠放檔案最後；伺服器端 `Match` 永遠放檔案最後
- ★★★★★ 伺服器端所有設定寫進 `sshd_config.d/`，主檔不要動
- ★★★★ 改完的驗證動作固定成兩條：`ssh -G <別名>`（客戶端）、`sudo sshd -T`（伺服器端）
- ★★★ 把 `sshd -T` 輸出存成基準快照，日後 `diff` 一行就知道這台跟基準差在哪

### ★★★★ 情境七：隧道建起來了，但連過去就 `channel open failed`

**現象**：`ssh -L` 執行後看起來一切正常，應用程式一連就報錯。回到 ssh 視窗會看到：

```text
channel 3: open failed: administratively prohibited: open failed
channel 3: open failed: connect failed: Connection refused
channel 3: open failed: connect failed: Connection timed out
```

★★★★ 這三行是**三個完全不同的問題**，分清楚可以省掉一小時的亂改參數。

**判斷分流**：

```bash
$ ssh -v -N -L 13306:127.0.0.1:3306 db-tunnel
debug1: Authentication succeeded (publickey).                 # ★★★ 認證這段沒問題
debug1: Local forwarding listening on 127.0.0.1 port 13306.   # ★★★★ 有這行 = 本機 bind 成功
```

- **沒有** `Local forwarding listening` → 問題在**你本機**（埠被占）→【1】
- 有這行，另開終端 `nc -zv 127.0.0.1 13306` 之後回頭看 ssh 視窗印什麼：

```text
administratively prohibited          → A：★★★★ 伺服器政策拒絕 →【2】
connect failed: Connection refused   → B：★★★ 目標沒在聽       →【3】
connect failed: Connection timed out → C：★★★ 中間防火牆       →【3】
```

**處置步驟**：

【1】本機埠被誰占了 —— ★★★ 看清楚再殺，不要盲目 `kill`。

```bash
$ ss -ltnp 'sport = :13306'; ps -o pid,lstart,args -p 48211
LISTEN 0 128 127.0.0.1:13306 0.0.0.0:* users:(("ssh",pid=48211,fd=5))
48211 Thu Aug 27 14:02:11 2026 ssh -N -L 13306:127.0.0.1:3306 db01-old
```

★★★★ 上週指向**舊主機**的殘留隧道，正是「連得上卻資料不對」的元兇。

【2】A：伺服器為什麼拒絕。★★★★ **去伺服器端查，不要在客戶端瞎改參數。**

```bash
$ sudo sshd -T -C user=tunnel,host=ws01.example.gov.tw,addr=10.10.1.20 \
    | grep -iE 'allowtcpforwarding|permitopen|permitlisten'
allowtcpforwarding local
permitopen 127.0.0.1:3306        # ★★★★ 想連 10.10.20.50:3306 就對不上 → 原因找到了
$ sudo grep -n 'restrict\|permitopen' /home/tunnel/.ssh/authorized_keys
1:restrict,permitopen="127.0.0.1:3306",from="10.10.1.0/24" ssh-ed25519 AAAA...
$ sudo journalctl -u ssh --since '10 min ago' | grep -i refused
Aug 28 11:03:12 db01 sshd[9210]: refused local port forward: originator 127.0.0.1 port 41234, target 10.10.20.50 port 3306
```

★★★★ 常見陷阱：`sshd_config` 開了，但**金鑰上的 `restrict` 仍然擋著**（兩者取交集）。
最後那一行日誌同時告訴你「誰想連」「想連到哪」，是排錯與稽核的關鍵證據。

【3】B/C：目標服務到底在不在。★★★ **要在 SSH 伺服器上查，不是在你的工作站。**

```bash
$ ssh -J bastion ops@db01 'ss -ltnp | grep 3306'
LISTEN 0 80 127.0.0.1:3306 0.0.0.0:* users:(("mysqld",pid=1180,fd=25))
```

★★★★ 綁在 `127.0.0.1` → 你的 `-L` target 就**必須**寫 `127.0.0.1`；
若這裡是 `10.10.20.50:3306`，你寫 `127.0.0.1` 就會得到 `Connection refused`。

【4】`-R` 被拒（`Warning: remote port forwarding failed for listen port 8080`）：
埠已被占、`PermitListen` 不允許，或想綁對外但伺服器 `GatewayPorts no`。
★★★★ **多數情況下正確答案是「這件事不該用 `-R` 做」**，改用 `-L` 或正規的反向代理。

【5】隧道活著但後端掛了 —— 最容易誤判的一種。

```bash
$ systemctl --user is-active db-tunnel; ss -Hltn 'sport = :13306' | wc -l
active
1
$ mysqladmin -h 127.0.0.1 -P 13306 ping
mysqladmin: connect to server at '127.0.0.1' failed
```

★★★★ 服務 active + 本機埠在聽 + 後端不通 → 問題在對面的 mysqld，**不在隧道**。
★★★ 另外：`mysql -h localhost` 走 Unix socket 而忽略 `-P`，**一律寫 `-h 127.0.0.1`**。

**原理**：`-L` 的本機埠是**客戶端自己綁的**，綁得起來不代表對面通得了；
真正的失敗要等到有人實際連那個埠、ssh 去開 channel 時才會浮現。
　→ 原理詳見 [[020-02-01-05-cmd-SSH-隧道與埠轉發]]

**預防**：
- ★★★★ 隧道一律加 `ExitOnForwardFailure yes`，讓 bind 失敗時整條 ssh 直接結束（`rc=255`），
  腳本與 systemd 才抓得到失敗、才有機會告警重試
- ★★★★ 常駐隧道做成 systemd user unit + `loginctl enable-linger`，用**無密語**專用金鑰，
  伺服器端用 `restrict,permitopen=` 限死可連的目標
- ★★★ 監控分兩層：本機埠在不在聽（隧道層）＋後端服務 ping 得到嗎（服務層）
- ★★★ 用完的隧道要收掉，養成 `ss -ltnp | grep ssh` 檢查殘留的習慣

### ★★★★ 情境八：SFTP 帳號一連上就被踢

**現象**：三種都很像，但成因不同 ——（A）`Connection closed by 10.10.20.31`（認證過了才被關）；
（B）`subsystem request failed on channel 0`；
（C）連得上、`ls` 正常，但 `put` 一律 `remote open(...): Permission denied`。

**判斷分流**：先看伺服器日誌，這三種在日誌裡長得完全不一樣。

```bash
$ sudo journalctl -u ssh -n 50 --no-pager | grep -i vendor01   # RHEL：tail -50 /var/log/secure
fatal: bad ownership or modes for chroot directory "/srv/sftp/vendor01"
```

| 看到這行 | 代表 | 往哪走 |
| --- | --- | --- |
| ★★★★ `fatal: bad ownership or modes for chroot directory "…"` | chroot 目錄權限 |【1】 |
| ★★★★ `subsystem request for sftp failed, subsystem not found` | subsystem 設定錯 |【2】 |
| ★★★ `bad ownership or modes for file /etc/ssh/authorized_keys/vendor01` | 金鑰檔權限 | `chown root:root` + `chmod 0644` |
| ★★★★ `pam_unix(sshd:account): account vendor01 has expired` | `chage -E` 生效了 |【4】 |
| 沒有錯誤、連得上但寫不進去 | 沒有可寫子目錄 |【3】 |

**處置步驟**：

【1】★★★★★ chroot 的硬規則：**根目錄與它上面的每一層，都必須 root 擁有、
且 group/other 不可寫**。逐層檢查：

```bash
$ namei -l /srv/sftp/vendor01/upload
 drwxr-xr-x root root     /
 drwxr-xr-x root root     srv
 drwxr-xr-x root root     sftp
 drwxr-xr-x root root     vendor01     # ★★★★ 到這層為止都要 root root、沒有 group/other 的 w
 drwxrws--- vendor01 sftp-vendor01 upload
```

- 任何一層是**非 root 擁有者**或出現 `drwxrwx…` → 就是它：`sudo chown root:root <該層>`
  加 `sudo chmod 755 <該層>`。擁有者是 `vendor01` → ★★★ 多半是 `useradd --create-home` 造成的
- ★★★★★ **不要先 `chmod 777`** —— 權限太寬 sshd 一樣拒絕，只會讓你更難查

【2】★★★★ chroot 之下**只能用 `internal-sftp`**，因為 chroot 裡沒有外部 `sftp-server` 執行檔。

```bash
$ sudo sshd -T | grep -i subsystem
subsystem sftp internal-sftp
```

印出 `/usr/lib/openssh/sftp-server` → 改成 `Subsystem sftp internal-sftp`。

【3】★★★★ 連得上但 `put` 被拒：**chroot 根必須不可寫**，所以你需要一個可寫的子目錄。

```bash
$ sudo mkdir -p /srv/sftp/vendor01/upload
$ sudo chown vendor01:sftp-vendor01 /srv/sftp/vendor01/upload && sudo chmod 2770 $_
$ sudo ls -ld /srv/sftp/vendor01 /srv/sftp/vendor01/upload
drwxr-xr-x 3 root     root           4096 Aug 28 09:00 /srv/sftp/vendor01
drwxrws--- 2 vendor01 sftp-vendor01  4096 Aug 28 09:02 /srv/sftp/vendor01/upload
```

★★★ 上傳的檔案權限太寬（0666）→ `ForceCommand` 少了 `-u 0027`，補上。

【4】★★★★ 分辨「帳號到期」與「金鑰到期」—— 客戶端**兩種都只顯示
`Permission denied (publickey).`**，只能從伺服器端分辨。

```bash
$ sudo chage -l vendor01 | grep 'Account expires'
Account expires                         : Nov 26, 2026
$ sudo grep -o 'expiry-time="[0-9]*"' /etc/ssh/authorized_keys/vendor01; date +%F
expiry-time="20261126"
2026-11-27
```

日誌有 `account has expired` → `chage -E` 擋的；只有 `Authentication refused` →
`expiry-time` 或 `from=` 擋的。

【5】★★★★★ 最嚴重的一種：**管理員自己被關進 chroot 了**。這代表 `Match` 條件寫錯人，
或 `Match` 之後又寫了「以為是全域」的設定。**立刻停手**，用逃生梯或主控台把 drop-in 刪掉，
`sshd -t` 之後 reload。之後一律先驗證：

```bash
$ sudo sshd -T -C user=admin,host=localhost,addr=127.0.0.1 | grep -iE 'chroot|forcecommand'
chrootdirectory none
forcecommand none        # ★★★★★ 管理員身上必須是 none
```

★★★ 看到 `chrootdirectory %u` **沒展開**，代表你忘了帶 `-C`，重來一次。

**原理**：chroot 是把使用者的根目錄換掉，核心要求這條路徑上不能有任何一段可被非 root 竄改
（否則等於讓使用者能改寫自己的根），所以權限規則沒有例外。
　→ 原理詳見 [[020-02-01-06-svc-SFTP-與受限使用者]]

**預防**：
- ★★★★★ 建帳號一律用腳本，不要手工 `useradd` + `mkdir`，權限一次做對
- ★★★★★ 套用 `Match` 之前先跑 `sshd -T -C user=<管理員>` 確認**自己沒被吃進去**
- ★★★★ 停用帳號要「四件套」：`usermod --expiredate 1` + 移出群組 + 搬走 `authorized_keys`
  + `pkill -u`。只做 `usermod -L` **只鎖密碼，公鑰照樣能進**
- ★★★★ 到期日兩道都設（`chage -E` 與 `expiry-time=`），並把日期調成昨天實測一次

### ★★★★ 情境九：`Could not open a connection to your authentication agent.`

**現象**：（A）`ssh-add -l` 回 `Could not open a connection to your authentication agent.`；
（B）明明早上輸入過，ssh 又問你 `Enter passphrase for key '...'`；
（C）`sign_and_send_pubkey: signing failed ... from agent: agent refused operation`。

**判斷分流**：

```bash
$ echo "SSH_AUTH_SOCK=[$SSH_AUTH_SOCK]"; ssh-add -l; echo "rc=$?"
SSH_AUTH_SOCK=[]
Could not open a connection to your authentication agent.
rc=2
```

```text
rc=2 且 SSH_AUTH_SOCK 空的           → agent 沒跑或環境變數沒帶到 →【1】
rc=1「The agent has no identities」  → agent 在跑但沒金鑰 → ssh-add 加回去
rc=0 有列出金鑰卻仍要 passphrase      → 送出去的不是那把 → 回情境五
rc=0 卻 agent refused operation      → 金鑰被逾時移除或 agent 鎖住 →【2】
```

**處置步驟**：

【1】★★★★ 三種最常見的「環境變數沒帶到」：`sudo` 之後（sudo 預設清掉 `SSH_AUTH_SOCK`）、
cron／systemd 服務（根本沒有互動 session）、新開的終端機或 tmux（沒繼承到 agent）。

```bash
$ eval "$(ssh-agent -s)" && ssh-add ~/.ssh/id_ed25519_ops && ssh-add -l
Agent pid 51203
Identity added: /home/wangxm/.ssh/id_ed25519_ops (ops-wangxm-2026)
256 SHA256:cNgXnpcfTlWLmrBBnVB63+416+aHzJNnF/R1+K+gMlQ ops-wangxm-2026 (ED25519)
```

★★★ 想跨終端機共用，用 systemd user unit 起 agent，比每個 shell 各起一個好。

★★★★★ **排程與自動化情境不要想辦法把 agent 帶進去** —— 正確做法是改用
**無 passphrase 的受限機器金鑰**，在 `authorized_keys` 上用 `restrict,command=,from=`
把它能做的事限死。這比讓 cron 拿到你的 agent 安全得多。

【2】`agent refused operation` 的三個原因：金鑰被 `ssh-add -t` 的逾時移除了（重新 `ssh-add`）、
agent 被 `ssh-add -x` 鎖住（`ssh-add -X` 解鎖）、★★★ 是 FIDO2 硬體金鑰
（**你要去按一下那顆按鈕**，它在等你觸碰）。

【3】★★★★★ 順便用 `ssh -G <主機> | grep -i forwardagent` 檢查你有沒有在用 `ssh -A`。
agent forwarding 等於把「用你的身分簽章」的能力交給遠端 —— **遠端主機上的 root
可以在你連線期間拿你的 agent 去連任何地方**。需要跳板時改用 `ProxyJump`（`-J`），
它**不需要**把私鑰或 agent 交給跳板機。

**原理**：ssh 透過 `SSH_AUTH_SOCK` 指向的 UNIX socket 跟 agent 說話。環境變數沒帶到，
ssh 就完全不知道有 agent 存在 —— 它不會報錯，只會安靜地改問你密語。
　→ 原理詳見 [[020-02-01-02-cmd-SSH-金鑰認證與ssh-agent]]

**預防**：
- ★★★★★ `Host *` 設 `ForwardAgent no`，需要的個別主機再開，且只開給你信任的跳板
- ★★★★ 跳板一律用 `ProxyJump`，不要用 `ssh -A` + 二段 ssh
- ★★★★ 自動化用專屬的無密語受限金鑰，不要試圖讓 cron 用你的 agent

### ★★★ 情境十：連線會斷、會卡、畫面怪怪的

**現象**：（A）閒置幾分鐘後 `client_loop: send disconnect: Broken pipe`；
（B）連線時卡住五到十秒才出現提示，之後就順了；
（C）`vim`／`top` 畫面破碎、方向鍵變亂碼、中文變成 `?`。

**判斷分流**：

```bash
$ ssh -G <主機> | grep -iE 'serveraliveinterval|gssapiauthentication'; echo "$TERM"
serveraliveinterval 0        # ★★★ 0 = 完全沒有保活封包 → A 的成因
gssapiauthentication yes     # ★★★ 非 Kerberos 環境設成 no → B 的成因之一
xterm-256color
```

**處置步驟**：

【1】A：閒置斷線 —— 中間的 NAT 或狀態防火牆把閒置連線從連線表清掉了。在 `~/.ssh/config`
的 `Host *`（放檔案最後）加上 `ServerAliveInterval 30` 與 `ServerAliveCountMax 3`。
★★★★ 伺服器端的 `ClientAliveInterval` 目的**相反** —— 它常被拿來**強制閒置斷線**
（稽核基準常要求閒置 15 分鐘登出）。加固時先想清楚你要哪一種。

【2】B：登入前卡住幾秒，兩個兇手 —— 伺服器對來源 IP 做反向 DNS 查詢逾時
（伺服器端 `sudo sshd -T | grep -i usedns`，設成 `UseDNS no`），
或客戶端在嘗試 GSSAPI（`-o GSSAPIAuthentication=no`，非 Kerberos 環境直接關掉）。

【3】C：畫面與編碼。

```bash
$ TERM=xterm ssh <主機>                       # 遠端沒有你 TERM 的 terminfo
$ sudo apt install ncurses-term               # 或在遠端補齊（RHEL：dnf install ncurses-term）
$ locale -a | grep -i zh_TW                   # 中文亂碼：伺服器有沒有這個 locale
$ sudo locale-gen zh_TW.UTF-8                 # RHEL：dnf install glibc-langpack-zh
```

★★★ 客戶端 `SendEnv LANG LC_*` 加伺服器端 `AcceptEnv LANG LC_*` 可以把語系帶過去，
但**伺服器上要真的有**那個 locale 才會生效；終端機模擬器本身也必須是 UTF-8。

**原理**：SSH 連線本身沒有心跳，閒置久了在中間設備眼中就是死連線被回收；
而登入前的延遲幾乎都是伺服器在做某種「會逾時的查詢」。
　→ 原理詳見 [[020-02-01-03-svc-SSH-客戶端設定檔]]

**預防**：★★★ 把 `ServerAliveInterval 30` / `ServerAliveCountMax 3` 寫進 `Host *`，
一次解決所有主機。長時間操作用 `tmux`，斷線後 `tmux attach` 回到現場 —— 這比調參數更根本。

### ★★★★ 情境十一：加固之後，某些人／某些系統連不上了

**現象**：加固當下自己測沒問題，隔天開始收到零散災情 ——（A）某台設備跳
`Unable to negotiate ...: no matching key exchange method found`；
（B）某位同仁「我這台一直說 Permission denied，別人都好好的」；
（C）★★★★★ 備份任務、監控探針全紅，而且**沒有任何人回報錯誤**。

★★★★★ （C）最危險：老舊備份軟體被拒絕時**常常不會告警**，
你會在需要還原的那一天才發現「已經三個星期沒有備份了」。

**判斷分流**：

```bash
$ sudo journalctl -u ssh --since '1 day ago' --no-pager \
    | grep -iE 'not allowed|no matching|Unable to negotiate' | tail -20
Aug 29 02:00:11 web01 sshd[8812]: User backupsvc not allowed because none of user's groups are listed in AllowGroups
Aug 29 03:14:52 web01 sshd[9033]: Unable to negotiate with 10.0.40.7 port 41022: no matching cipher found
```

```text
not allowed … AllowGroups      → 存取控制漏了人 →【1】
no matching cipher/kex/host key → 演算法太嚴     →【2】
Certificate invalid …           → 憑證問題       →【3】
```

**處置步驟**：

【1】★★★★ `AllowGroups` 漏了服務帳號。先盤點過去 90 天實際登入過的帳號，再補齊。

```bash
$ sudo lastlog -t 90; sudo sshd -T | grep -i allowgroups
allowgroups ssh-users
$ sudo usermod -aG ssh-users backupsvc && sudo getent group ssh-users
```

★★★ `AllowGroups` 的變更**對新連線立即生效**，不必 reload。

【2】★★★★ 演算法談不攏。先確認對方支援什麼，再決定是升級對方還是開例外。

```bash
$ ssh -vv <對方> 2>&1 | tail -3
Unable to negotiate with 10.0.20.15 port 22: no matching key exchange method found.
Their offer: diffie-hellman-group14-sha1,diffie-hellman-group-exchange-sha1
```

★★★ `Their offer:` 後面就是對方支援的**完整清單**。三種處置，優先序如下：

```text
① ★★★★★ 升級對方（韌體／客戶端）—— 唯一的正解
② ★★★★  排入設備汰換，並訂出落日期限
③ ★★★   真的不能動時：開一個【隔離的第二個 sshd 實例】跑寬鬆設定，
         綁在管理網段、只給那一台用，而且要有落日期限
✗ ★★★★★ 不要為了一台老設備把全機的演算法清單放寬
```

★★★ 單次臨時連老設備（僅限手動，不要寫進 `Host *`）：
`ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa admin@10.0.30.5`。
★★★ `Directive 'Ciphers' is not allowed within a Match block` → 演算法設定**只能全域**，
要差異化就得開第二個 sshd 實例。

【3】★★★★ 憑證式認證的四種典型失敗：

| 日誌訊息 | 原因 | 解法 |
| --- | --- | --- |
| ★★★ `Certificate invalid: expired` | 憑證過期，或**伺服器時間不對** | 重簽；`timedatectl` 檢查 NTP |
| ★★★★ `Certificate invalid: name is not a listed principal` | `AuthorizedPrincipalsFile` 與憑證 principals 沒交集 | 建 `/etc/ssh/auth_principals/<帳號>` 並填入 principal |
| ★★★ 日誌完全沒有憑證欄位 | 客戶端沒送出憑證（檔名不是 `<key>-cert.pub`） | 憑證放私鑰旁並命名正確，或用 `CertificateFile` 明指 |
| ★★★ `PTY allocation request failed on channel 0` | 簽發時用 `-O clear` 卻沒補 `-O permit-pty` | 重簽並加 `-O permit-pty` |

【4】★★★★ 改過埠的話，別忘了兩件連帶的事：

```bash
$ sudo grep -n '^port' /etc/fail2ban/jail.d/*.local
port = ssh        # ★★★★ 這仍然指向 22 → 改成實際埠號，否則封不到人
$ sudo semanage port -a -t ssh_port_t -p tcp 2222   # ★★★★ RHEL：沒這行 sshd 起不來
```

**原理**：加固就是「把選項變少」。每砍掉一個演算法或一個帳號，
都可能砍掉某個你沒盤點到的既有用戶 —— 所以加固的重點不在改設定，在**加固前的盤點**。
　→ 原理詳見 [[020-02-01-07-svc-SSH-安全強化]]

**預防**：
- ★★★★★ 加固前先跑一週 `LogLevel VERBOSE`，把**實際連進來的客戶端版本與帳號**盤點出來
- ★★★★★ 備份與監控任務**必須有成功回報的監控**（沒收到成功訊號就告警），
  不能只靠「失敗會告警」—— 靜默失敗正是最危險的那一種
- ★★★★ 分階段導入：先加日誌與盤點 → 再收緊存取控制 → 最後才動演算法

### ★★★★★ 情境十二：報告上寫「已停用密碼登入」，但其實沒有

**現象**：你在 `sshd_config` 寫了 `PasswordAuthentication no`、也 reload 了，
連線時**還是跳出 `(ops@10.10.20.31) Password:`**，而且輸入正確密碼**真的能登入**。

★★★★★ 這不只是設定沒生效 —— 這代表你交出去的稽核報告是**不實陳述**。

**判斷分流**：

```bash
$ sudo sshd -T | grep -Ei 'passwordauthentication|kbdinteractiveauthentication|usepam'
passwordauthentication no
kbdinteractiveauthentication yes    # ★★★★★ 兇手在這裡
usepam yes
```

```text
兩行都是 no        → 密碼真的關了，你看到的提示是別的東西 →【3】
kbdinteractive yes → ★★★★★ 走 PAM 的 keyboard-interactive 一樣驗密碼 →【1】
passwordauth yes   → 設定根本沒生效 → 回情境六【3】
```

**處置步驟**：

【1】★★★★★ 兩個都要關，缺一不可。

```text
# /etc/ssh/sshd_config.d/60-hardening.conf
PasswordAuthentication no
KbdInteractiveAuthentication no
```

```bash
$ sudo sshd -t && sudo systemctl reload ssh
$ sudo sshd -T | grep -Ei 'passwordauth|kbdinteractive'
passwordauthentication no
kbdinteractiveauthentication no      # ★★★★★ 兩行都是 no 才算數
```

【2】★★★★★ **實測才算數**，而且要分別測兩種方法。這段輸出就是交給稽核的證據。

```bash
$ ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no ops@10.10.20.31
ops@10.10.20.31: Permission denied (publickey).
$ ssh -o PreferredAuthentications=keyboard-interactive -o PubkeyAuthentication=no ops@10.10.20.31
ops@10.10.20.31: Permission denied (publickey).
```

★★★★★ **兩條都要看到 `Permission denied (publickey).`**。只要任何一條跳出密碼提示，
就代表密碼登入還開著。

【3】客戶端角度的驗證 —— 出現 `password` 或 `keyboard-interactive` 就回【1】：

```bash
$ ssh -vvv ops@10.10.20.31 2>&1 | grep -i 'Authentications that can continue'
debug1: Authentications that can continue: publickey      # ★★★★ 只有 publickey = 真的關了
```

【4】★★★★★ 驗證時最容易犯的錯：**你以為的「重新連線」其實是舊連線**。

```bash
$ ssh -O check ops@10.10.20.31
Master running (pid=48213)       # ★★★★★ 你的驗證完全無效，先 ssh -O exit
```

★★★★★ 加固後的驗證**一律用完全乾淨的環境** —— 不吃任何設定檔、不複用連線、不使用 agent：

```bash
ssh -F /dev/null -o ControlPath=none -o ControlMaster=no -o IdentityAgent=none \
    -o PreferredAuthentications=keyboard-interactive -o PubkeyAuthentication=no ops@10.10.20.31
```

**原理**：`PasswordAuthentication` 只管 SSH 協定裡的 `password` 方法；
`KbdInteractiveAuthentication` 管的是 `keyboard-interactive`，而它搭配 `UsePAM yes` 時，
PAM 的 `common-auth` 一樣會去驗系統密碼 —— 兩條路都通往同一個地方。
　→ 原理詳見 [[020-02-01-07-svc-SSH-安全強化]]

**預防**：
- ★★★★★ 「已停用密碼登入」這句話**必須附上兩種方法的實測輸出**才能寫進報告
- ★★★★ 把這兩項寫進組態基準與定期合規檢查腳本，用 `sshd -T` 的輸出自動比對
- ★★★★ 有 2FA 需求時走 `AuthenticationMethods` 明確宣告組合，不要靠單一開關達成

## 一頁式急救卡

出事時來不及讀長文，先跑這幾個。**【1】～【3】在你的機器上跑，【4】～【8】在伺服器上跑**
（透過既有連線、主控台或 IPMI）。

```bash
# ─── 在你自己的機器上 ────────────────────────────────────────────────
# 【1】TCP 到底通不通 —— 分辨 refused / timeout，這是整份手冊的第一分岔
nc -zv <主機> 22
#   succeeded          → 網路與服務都在，問題在認證，跳【3】
#   Connection refused → 封包有到但沒人聽：sshd 沒跑、埠改過、連錯機器
#   卡住到逾時         → 防火牆 DROP 或路由不通，SSH 這邊查不到答案

# 【2】卡在六階段的哪一段 —— 一行定位問題範圍
ssh -v <主機> 2>&1 | grep -E 'Connecting to|Connection established|Server host key|Authentications that can continue'
#   只有 Connecting to               → 階段①，TCP 沒建起來
#   停在 Connection established      → 階段②③，看完整輸出裡的 no matching
#   有 Server host key 沒有 is known → 階段④，去跑 host key 分流，不要直接 -R
#   有 Authentications that can…     → ①～④全過，只剩認證問題

# 【3】排除自己的設定檔與舊連線 —— 最強的一條分界線
ssh -F /dev/null -o ControlPath=none -o IdentitiesOnly=yes -i ~/.ssh/<金鑰> <帳號>@<主機>
#   這樣就成功 → 問題【100% 在客戶端】：~/.ssh/config 或殘留的 ControlMaster socket
#   這樣也失敗 → 客戶端是清白的，往伺服器端查【4】以後

# ─── 在伺服器上（既有連線 / console / IPMI）─────────────────────────
# 【4】真正生效的設定值 —— 不要看檔案內容，要看這個
sudo sshd -T | grep -Ei 'port|listenaddress|allowgroups|allowusers|permitrootlogin|passwordauth|kbdinteractive'
#   跟你寫的不一樣 → 被字典序更前面的 drop-in 蓋掉，或被寫在 Match 之後了

# 【5】服務在不在、聽哪個埠、是誰在聽
sudo ss -lntp | grep -E ':(22|2222)\s'
#   users:(("sshd"…))    → 傳統模式，服務正常
#   users:(("systemd"…)) → socket 啟動模式，sshd_config 的 Port 不生效
#   完全沒有             → 服務沒起來，先 sudo sshd -t 看語法

# 【6】sshd 到底為什麼拒絕 —— 客戶端永遠只說 Permission denied，真相只在這裡
sudo journalctl -u ssh -u ssh.socket --since '10 min ago' --no-pager \
  | grep -iE 'refused|invalid|failed|not allowed|expired|bad ownership'
#   bad ownership or modes    → 家目錄 / .ssh / authorized_keys 權限太寬
#   not allowed … AllowGroups → 帳號不在允許群組
#   一行都沒有                → 請求根本沒到 sshd，回【1】查網路

# 【7】這個人從這個來源連進來會拿到什麼規則（Match 有沒有命中）
sudo sshd -T -C user=<帳號>,host=<主機名>,addr=<來源IP> \
  | grep -Ei 'allowgroups|forcecommand|chroot|allowtcpforwarding|permitopen|maxauthtries'
#   跟全域完全一樣 → Match 沒命中，多半是 NAT 後的 IP 跟你以為的不同
#   管理員身上出現 chroot / forcecommand → ★★★★★ 立刻停手，你正在把自己鎖進去

# 【8】改設定之前的兩道保命符 —— 順序不能顛倒
sudo sshd -t && echo '語法 OK'
sudo systemd-run --on-active=5m --unit=sshd-rollback \
  /bin/sh -c 'cp -a /etc/ssh/sshd_config.bak /etc/ssh/sshd_config && systemctl reload ssh'
#   驗證新連線成功之後，★★★★★ 一定要 sudo systemctl stop sshd-rollback.timer
```

> [!tip] ★★★★★ 三句話版本
> ① 分不清就先跑 `nc -zv` —— **refused 找服務，timeout 找防火牆**。
> ② 客戶端說不出原因就去看**伺服器的 journal**，答案永遠在那裡。
> ③ 動 sshd 設定前，**先掛回滾 timer、先開第二個終端、舊連線不要關**。

## 什麼時候該停手求援

> [!danger] ★★★★★ 以下情況請立刻停止操作 —— 繼續動手會讓證據消失或災情擴大

**【1】★★★★★ 懷疑被中間人攔截（情境四的成因④）**：console 上取到的指紋跟
`known_hosts` 裡的一樣、卻跟現在收到的不一樣。不要再連、不要輸入密碼、
**不要執行 `ssh-keygen -R`（那是在銷毀唯一的證據）**。保留終端機輸出與時間，
拔掉這台工作站的網路，依 [[090-07-04-guide-資安實踐-資安事件應變流程]] 通報。

**【2】★★★★★ 伺服器上出現你不認識的隧道或金鑰**：

```bash
$ sudo ss -lntp | grep sshd | grep -v ':22 '
（正常應該無輸出）
```

有輸出 = 有人開了 `-R` 遠端轉發把內網服務往外送；`authorized_keys` 裡出現沒人認領的公鑰也一樣。
★★★★★ **不要直接刪掉**，那是入侵者的立足點與證據 —— 先保存現場（`journalctl` 與
`authorized_keys` 的副本），再依事件流程處理。

**【3】★★★★★ 日誌有明顯斷層，或 root 從陌生 IP 登入成功過**（`last -F`、`lastb -F` 看得到）：
日誌被清空、時間軸出現空白，代表對方已有 root 權限並在掩蓋足跡。
★★★★★ 這台機器上**任何後續操作都可能覆蓋證據**，包含你的排錯指令本身。
交給資安流程，不要自己「順便看一下」。

**【4】★★★★ 沒有任何頻外管理途徑，而你正要改 sshd 設定**：沒有 IPMI／iDRAC／console、
也不能實體接觸的機器，一旦改壞就等於報廢重建。先停手去把頻外管理弄好，
或至少確定自動回滾 timer 已經掛上並驗證過。「反正等一下再測」是最常見的事故起點。

**【5】★★★★ 災情比你以為的大**：不只 SSH 連不上，連 ping 都不通、其他服務也全掛、
或磁碟已滿到系統無法寫入。這時 SSH 只是症狀不是病因，繼續在 SSH 上找答案只會浪費時間 ——
往上升級成系統層級的事件處理（[[100-02-09-svc-維運-事件處理與升級流程]]）。

**【6】★★★ 同一個問題試了超過三十分鐘，而且開始「隨便改改看」**：★★★★★ 隨機修改設定
會製造新問題，讓單一故障變成多重故障，而且沒人知道你動過什麼。停下來，把做過的動作
寫下來，找第二個人一起看。

**【7】★★★ 需要在正式環境做不可逆的動作**：刪除 `authorized_keys`、重新產生 host key、
`chmod -R`、刪除使用者家目錄 —— 先確認有備份、先取得核准，再動手。

## 延伸閱讀

**本章各篇（原理都在這裡，本手冊只做索引）**

- [[020-02-01-00-idx-SSH]] —— 本章索引與建議閱讀順序
- [[020-02-01-01-cmd-SSH-原理與第一次連線]] —— 連線六階段、host key 帶外驗證、`HOST KEY CHANGED` 分流（情境一、四、十）
- [[020-02-01-02-cmd-SSH-金鑰認證與ssh-agent]] —— `authorized_keys` 權限與選項欄、ssh-agent、agent forwarding 風險（情境二、九）
- [[020-02-01-03-svc-SSH-客戶端設定檔]] —— 第一個匹配值勝出、`ssh -G`、`IdentitiesOnly`、ControlMaster 與 ProxyJump（情境五、六、十）
- [[020-02-01-04-svc-sshd-伺服器端設定]] —— 不鎖門 SOP、`sshd_config.d` 覆寫順序、`KbdInteractive` 與 `ssh.socket` 三大陷阱（情境三、六）
- [[020-02-01-05-cmd-SSH-隧道與埠轉發]] —— 四種轉發的方向感、伺服器端管制與稽核（情境七）
- [[020-02-01-06-svc-SFTP-與受限使用者]] —— chroot 硬規則、四種受限帳號型態、帳號生命週期治理（情境八）
- [[020-02-01-07-svc-SSH-安全強化]] —— 加固基準八項、演算法相容性評估、SSH CA、鎖門預防與回滾（情境十一、十二）
- [[020-02-01-99-exam-SSH-總結小考]] —— 全章 100 題總複習

**排錯時常一起用到的其他章節**

- [[020-01-23-guide-Linux-Linux常見疑難排解]] —— 「網路 vs 服務 vs 權限」的通用分層排查法
- [[020-01-25-guide-Linux-開機流程與GRUB救援]] —— 情境三路徑 D：單一使用者模式救援
- [[020-01-19-guide-Linux-日誌系統]] —— `journalctl` 的完整用法與日誌外送
- [[060-01-04-03-guide-ss-netstat-與lsof]] —— 確認監聽狀態與埠占用的完整用法
- [[060-01-04-01-guide-tcpdump-基礎抓包]] —— 最後手段：兩邊同時抓包看 TCP 走到哪一步
- [[090-02-02-guide-防火牆-ufw基礎與實務]] —— `timeout` 的答案幾乎都在這裡
- [[090-02-05-guide-防護-Fail2ban入侵防護]] —— 被自己的 fail2ban 鎖住時的解法與 `ignoreip`
- [[090-07-04-guide-資安實踐-資安事件應變流程]] —— 情境四與「停手求援」的正式流程
- [[100-02-09-svc-維運-事件處理與升級流程]] —— 什麼時候該升級、要通知誰、怎麼記錄
- [[050-01-03-06-svc-PVE-備份與還原]] —— 虛擬機救不回來時的快照還原
- [[040-02-09-guide-機房-伺服器上架與初始設定]] —— iDRAC／IPMI 初始設定，★★★★ 上架時就做好，不要等到被鎖在外面才找
