---
title: "系統服務與排程 常見故障排除"
desc: "依症狀查的故障排除索引：判斷分流、處置步驟與一頁式急救卡，原理連回原文"
aliases: [系統服務與排程故障排除, 系統服務與排程排錯]
tags: [群組/Linux, 主題/故障排除]
category: 系統服務與排程
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: []
updated: 2026-08-29
---

# 系統服務與排程 常見故障排除

> [!abstract] 怎麼用這份手冊
> - 依「你看到什麼症狀」查，不是依「這屬於什麼技術」查
> - 找到症狀 → 看判斷分流 → 照處置步驟做 → 想懂原理再點進原文
> - ★★★★ 緊急時直接跳到最下面的「一頁式急救卡」
> - ★★★ 這裡**只有處置**，沒有原理。每個情境結尾的「原理詳見」才是完整說明，
>   兩邊寫重複的東西日後一定會不同步

---

## 快速索引（依症狀）

| 症狀（你會看到的） | 最可能的原因 | 先下這個指令 | 原理詳見 |
| --- | --- | --- | --- |
| ★★★★★ 「手動跑得好好的，放進 cron 就不動」 | cron 不讀 `.bashrc`／`.profile`，PATH 只有 `/usr/bin:/bin` | `sudo -u <u> env -i PATH=/usr/bin:/bin HOME=<home> /bin/sh -c '<cmd>'` | [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]] |
| ★★★★ 時間到了完全沒反應，journal 連一行 `CMD` 都沒有 | 檔名含 `.`／權限不是 `644 root:root`／檔尾少換行，整檔被拒讀 | `stat -c '%a %U:%G' <f>; tail -c1 <f> \| xxd` | [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]] |
| ★★★★ syslog 出現一行 `bad username`，之後永遠安靜 | `/etc/cron.d/` 的行寫成使用者 crontab 格式，少了使用者欄 | `awk 'NF && $1!~/^#\|=/ {print NF" 欄"}' <f>` | [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]] |
| ★★★★ 「從某天起再也沒跑過」，而且完全沒有錯誤 | 上一輪卡死佔住 flock，之後每輪 `-n` 直接跳過 | `sudo fuser -v /run/lock/<name>.lock` | [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]] |
| ★★★★ 備份檔 0 byte／檔名怪異，但排程「成功」 | crontab 指令欄的 `%` 未跳脫，指令被攔腰截斷 | `grep -rnE '[^\\]%' /etc/cron.d/ /etc/crontab` | [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]] |
| ★★★★ 備份連續失敗三個月才被發現 | `>/dev/null 2>&1` 把 stderr 丟掉，沒有任何人會知道 | `grep -rn 'dev/null' /etc/cron.d/ /var/spool/cron/` | [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]] |
| ★★★★ 半年後「所有服務帳號的排程同時停擺」 | 密碼／帳號到期政策生效，PAM account 檢查擋掉 | `sudo chage -l <u> \| grep -i expires` | [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]] |
| ★★★★ 重開機後服務 `failed`，手動 `start` 就正常 | 只寫 `After=` 沒寫 `Wants=`；或該等 `network-online.target` | `systemctl status <u>; systemd-analyze critical-chain <u>` | [[020-02-02-01-svc-systemd-unit撰寫實戰]] |
| ★★★★ `Cannot assign requested address`／`Temporary failure in name resolution` | 用了 `network.target`，網卡還沒拿到 IP | `systemctl is-enabled systemd-networkd-wait-online.service` | [[020-02-02-01-svc-systemd-unit撰寫實戰]] |
| ★★★★ 資料「消失」：寫出去的檔案在 NAS 上找不到 | 掛載完成前服務就啟動，寫進被蓋住的本機空目錄 | `systemctl show <u> -p RequiresMountsFor` | [[020-02-02-01-svc-systemd-unit撰寫實戰]] |
| ★★★★ 第一次上線好好的，重開機後永遠起不來（PID／socket 寫不出來） | 自己在 `/run` 底下 `mkdir`，而 `/run` 是 tmpfs，開機即清空 | `systemctl show <u> -p RuntimeDirectory` | [[020-02-02-01-svc-systemd-unit撰寫實戰]] |
| ★★★★ `systemctl status` 綠燈，網站卻 502 | `Type=` 與實際行為不符，systemd 誤判「起來了」 | `systemctl show <u> -p Type,MainPID; curl -fsS 127.0.0.1:<port>/healthz` | [[020-02-02-01-svc-systemd-unit撰寫實戰]] |
| ★★★★★ 重開機後前台整個不見，`systemctl status pm2-*` 卻是 `active` | unit 的 `PM2_HOME` 與當初 `pm2 save` 的不同，`resurrect` 讀到空 dump | `sudo tr '\0' '\n' < /proc/<pid>/environ \| grep PM2_HOME` | [[020-02-02-05-svc-systemd-PM2與systemd整合]] |
| ★★★★ `Job for x.service failed`，但設定檔明明已修好 | 撞過 StartLimit，rate limit 計數器沒清 | `sudo systemctl reset-failed <u> && sudo systemctl start <u>` | [[020-02-02-04-svc-systemd-服務自動復原與看門狗]] |
| ★★★★ 服務整晚每 30 秒重啟一次，狀態卻是 `active (running)` | `RestartSec` > `StartLimitIntervalSec`，永遠撞不到上限 → 不會 failed → 不告警 | `systemctl show <u> -p NRestarts,RestartUSec,StartLimitIntervalUSec` | [[020-02-02-04-svc-systemd-服務自動復原與看門狗]] |
| ★★★★ `/var` 被寫滿，`df` 顯示 journal 佔十幾 GB | 重啟迴圈把每次失敗都寫進 journal | `journalctl --disk-usage; sudo journalctl --vacuum-size=500M` | [[020-02-02-04-svc-systemd-服務自動復原與看門狗]] |
| ★★★★ 服務每天固定被殺幾次，`grep -i oom` 有記錄 | 記憶體洩漏撞到 `MemoryMax=`／整機 OOM | `journalctl -u <u> --since -1d \| grep -iE 'oom\|out of memory'` | [[020-02-02-04-svc-systemd-服務自動復原與看門狗]] |
| ★★★★ 重開機後某支 timer 再也沒跑，`list-timers` 也找不到 | timer 只 `start` 沒 `enable` | `systemctl is-enabled <u>.timer` | [[020-02-02-02-cmd-systemd-timer與cron選型]] |
| ★★★★ 前手離職後，某支排程默默停了數月 | `--user` timer，使用者登出即被收掉，且 `Linger=no` | `loginctl show-user <u> -p Linger` | [[020-02-02-02-cmd-systemd-timer與cron選型]] |
| ★★★★ 雲端主機的備份跑在上午尖峰時段 | 機器時區是 `Etc/UTC`，`OnCalendar=03:00` 等於台北 11:00 | `timedatectl; systemd-analyze calendar '<運算式>'` | [[020-02-02-02-cmd-systemd-timer與cron選型]] |
| ★★★★ `systemctl stop` 卡滿 90 秒後 `Killing process ... SIGKILL` | 程式不理 SIGTERM，或 `sh -c` 沒 `exec` 導致訊號只到 shell | `systemctl show <u> -p TimeoutStopUSec,KillMode` | [[020-02-02-01-svc-systemd-unit撰寫實戰]] |
| ★★★★ `systemctl stop` 顯示 `inactive`，但埠還被佔著 | 殘留程序在 `user@.service` 的 cgroup，不歸這個 unit 管 | `cat /proc/<pid>/cgroup` | [[020-02-02-05-svc-systemd-PM2與systemd整合]] |
| ★★★★ 遷移後對方機關收到兩份資料 | 新 timer 已 enable、舊 crontab 行沒註解，兩邊都在跑 | `sudo grep -RIn '<關鍵字>' /etc/cron* /var/spool/cron/` | [[020-02-02-02-cmd-systemd-timer與cron選型]] |
| ★★★ 改了 unit 檔卻沒生效，行為還是舊的 | 忘記 `daemon-reload`；或有 drop-in 在覆寫 | `systemctl cat <u> \| grep '^# /'` | [[020-02-02-01-svc-systemd-unit撰寫實戰]] |
| ★★★ `journalctl -u X.service` 一片空白，但 timer 顯示每天都有跑 | 查錯 unit 名 —— timer 與 service 不同名 | `systemctl show <u>.timer -p Unit` | [[020-02-02-02-cmd-systemd-timer與cron選型]] |
| ★★★ 部署明明成功，頁面卻沒更新 | 兩個 PM2 God Daemon 並存，對外服務的是舊那份 | `ps -eo user,pid,args \| grep -F 'God Daemon'` | [[020-02-02-05-svc-systemd-PM2與systemd整合]] |
| ★★★ 手動 `sudo -u svc` 跑得動，被 cron／systemd 叫就 `Permission denied` | RHEL 系的 SELinux context 不同 | `sudo ausearch -m avc -ts recent \| tail -20` | [[090-02-07-guide-防護-SELinux與AppArmor]] |

> [!tip] 表格查不到你的症狀時 ★★★
> 先跑一次「一頁式急救卡」的六條指令。它們涵蓋 **90% 的分流判斷**：
> 只要知道「這是服務問題還是排程問題」「是沒被啟動還是啟動了失敗」，
> 剩下的就一定落在下面某一個情境裡。

---

## 依情境展開

### ★★★★★ 情境一：手動跑得動，放進 cron 就不動

**現象**　值班的說法幾乎都是同一句：「我用 `sudo bash /usr/local/bin/data-sync.sh` 跑完全正常，
排程就是不動。」日誌（有留的話）長這樣：

```text
Aug 28 02:00:01 srv01 CRON[41233]: (datasync) CMD (/usr/local/bin/data-sync.sh)
Aug 28 02:00:01 srv01 data-sync[41235]: /usr/local/bin/data-sync.sh: line 88: mysql: command not found
```

**判斷分流**　★★★★★ 不要用你的 shell 重現，要用 **cron 的環境**重現。
`sudo bash script.sh` 是無效重現 —— 你的 PATH、語系、`HOME`、shell 全都不一樣：

```bash
sudo -u datasync env -i PATH=/usr/bin:/bin HOME=/var/lib/data-sync SHELL=/bin/sh \
     /bin/bash -c '/usr/local/bin/data-sync.sh'; echo "exit=$?"
```

- ★★★★ 重現失敗（`command not found`／找不到檔案）→ **確診環境差異**，往下走【1】
- 跑成功、排程仍不動 → cron 根本沒啟動它 → 跳**情境二**
- 重現失敗但錯誤是「連不上 DB／NAS」→ 是那個時間點的外部條件 → 跳**情境三**

**處置步驟**

【1】確認退出碼（`127` = `command not found`）：
`sudo journalctl -u cron --since "-2d" | grep -iE 'data-sync|FAILED'`。
★★★ 看不到 `FAILED` 行是正常的 —— Debian/Ubuntu 的 cron 預設只記「開始」不記結果。

【2】把環境補進**腳本自己**，不要補進 crontab、更不要靠 `.bashrc`：

```bash
sudo sed -i '/^set -euo pipefail/a export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\nexport LC_ALL=C.UTF-8' /usr/local/bin/data-sync.sh
head -4 /usr/local/bin/data-sync.sh
```

```text
#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C.UTF-8
```

【3】確認 shell。cron 預設 `SHELL=/bin/sh`，Ubuntu 的 `/bin/sh` 是 dash ——
`[[ ]]`、`&>`、`source`、陣列全都會爆：

```bash
head -1 /usr/local/bin/data-sync.sh; ls -l /bin/sh   # → /bin/sh -> dash
```

【4】確認工作目錄（cron 的 cwd 是家目錄，相對路徑都會指錯），再用【判斷分流】那條
`env -i` 重驗一次，`exit=0` 才算修好：

```bash
grep -nE '^\s*(cd|source|\.)\s+[^/]' /usr/local/bin/data-sync.sh || echo "沒有相對路徑，OK"
```

**原理**　cron 給的是近乎空白的環境：不讀 `/etc/profile`、不讀 `~/.bashrc`、不讀 `~/.profile`，
PATH 通常只有 `/usr/bin:/bin`。排程腳本必須「環境自足」。
　→ 原理詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]，
　　載入順序見 [[020-01-20-guide-Linux-環境變數與設定檔]]

**預防**　crontab 一行只寫「絕對路徑 + 參數」；每支腳本開頭固定四行
（`set -euo pipefail`、`export PATH`、`export LC_ALL`、`export HOME`）；
上線驗收一定跑一次 `env -i` 重現 —— 這 30 秒省掉三個月後的事故。

---

### ★★★★★ 情境二：時間到了完全沒動靜，連日誌都沒有

**現象**

```text
Aug 28 02:00:01 srv01 CRON[41590]: (root) CMD (cd / && run-parts --report /etc/cron.hourly)
（你的工作那一行完全不存在）
```

★★★★ 和情境一的決定性差別：這裡連 `CMD` 行都沒有，代表 cron **根本沒嘗試執行它** ——
怎麼改腳本都沒用。

**判斷分流**

```bash
F=/etc/cron.d/data-sync
stat -c '%a %U:%G %n' "$F"; tail -c1 "$F" | xxd
awk 'NF && $1!~/^#/ && $1!~/=/ {print NF" 欄 → "$0}' "$F"
sudo journalctl -u cron --since "-1d" | grep -iE 'bad username|BAD FILE MODE|Missing newline|Error'
```

```text
644 root:root /etc/cron.d/data-sync
00000000: 0a                                       .
9 欄 → 0 2 * * *   datasync   /usr/bin/timeout --kill-after=30s 45m /usr/local/bin/data-sync.sh
```

- mode 不是 `644`／擁有者不是 `root:root`，或 `tail -c1` 不是 `0a`（檔尾少換行）→ **整檔**被拒讀，走【1】
- 欄數只有 6 且第 6 欄是路徑，或看到 `bad username` → **少了使用者欄**，走【2】
- 以上都正常 → 是帳號被拒跑，走【3】

**處置步驟**

【1】修檔案的三個載入條件：`sudo chown root:root "$F"`、`sudo chmod 644 "$F"`、
檔尾補一個換行；再用 `ls /etc/cron.d/ | grep '\.'` 掃出含點的檔名（那些永遠不會被讀）。

【2】補使用者欄。★★★★ `/etc/cron.d/` 與 `/etc/crontab` 是**七欄**（五欄時間＋使用者＋指令），
`crontab -e` 編的是**六欄**（沒有使用者欄），兩者不能互相貼：

```bash
sudo tee "$F" >/dev/null <<'EOF'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
0 2 * * * datasync /usr/bin/timeout --signal=TERM --kill-after=30s 45m /usr/local/bin/data-sync.sh
EOF
awk 'NF && $1!~/^#/ && $1!~/=/ {print NF" 欄"}' "$F"    # → 7 欄
```

【3】查帳號准不准跑（★★★★ 機關環境第一名的原因）：

```bash
U=datasync
ls -l /etc/cron.allow /etc/cron.deny 2>&1 | head -2
grep -x "$U" /etc/cron.allow 2>/dev/null || echo "不在 cron.allow 裡"
sudo chage -l "$U" | grep -E 'Password expires|Account expires'
getent passwd "$U" | cut -d: -f6 | xargs -I{} sh -c 'test -d {} || echo "★★★★ 家目錄 {} 不存在"'
sudo journalctl -u cron --since "-2d" | grep -iE 'pam|authentication|expired'
```

- `cron.allow` **存在**而帳號不在裡面 → 使用者 crontab 直接被拒（`/etc/cron.d/` 不受影響）
- 任一 `expires` 不是 `never` 且已過期 → ★★★★ 確診：`sudo chage -M -1 -E -1 "$U"`
- 看到 `account has expired` / `Authentication token is no longer valid` → 同上確診

【4】使用者 crontab 專屬坑：直接 `>>` 附加到 spool 檔，mtime 沒變、cron 不重載。
用 `sudo crontab -u "$U" <file>` 部署；急救可 `sudo touch /var/spool/cron/crontabs`。

**原理**　一次 cron 執行要通過七道關卡（檔案載入 → 行格式 → 時間 → 帳號許可 → 鎖 →
指令本身 → 通報）。①②④ 失敗時 `systemctl status cron` **永遠還是 `active (running)`** ——
「服務有起來」不等於「排程有跑」。
　→ 原理詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]

**預防**　排程一律走 `/etc/cron.d/` + git，不用 `crontab -e`；部署腳本固定驗
mode、檔尾換行、欄數三件事；服務帳號建立時就 `chage -M -1 -E -1` 並在密碼政策留例外紀錄。

---

### ★★★★ 情境三：「從某天起再也沒跑過」，而且完全沒有錯誤

**現象**　`journalctl -u cron` 每天都有 `CMD (...)` 那行，但產出檔案停在三個月前，
沒有錯誤、沒有告警、監控全綠。

**判斷分流**

```bash
L=/run/lock/data-sync.d/data-sync.lock
ls -l "$L" 2>/dev/null && sudo fuser -v "$L" 2>&1
pgrep -af 'data-sync|rsync|mysql' || echo "沒有相關程序"
```

```text
-rw-r--r-- 1 datasync datasync 0 Jul 12 02:00 /run/lock/data-sync.d/data-sync.lock
                     USER        PID ACCESS COMMAND
/run/lock/...lock:   datasync  38102 F....  data-sync.sh
datasync 38109 rsync -a --contimeout=30 rsync://nas01...
```

- ★★★★ 鎖檔 mtime 停在很久以前 **且** `fuser` 找得到持有者 → **確診：舊程序卡死佔鎖**，往下走
- `fuser` 找不到程序 → 鎖檔只是殘留空檔，**不影響 flock**（flock 綁的是 fd 不是檔案存在）；
  ★★★ 不需要也不應該刪它，回情境一或情境二

**處置步驟**

【1】先看它卡在哪（`sudo ls -l /proc/38109/fd/`、`sudo cat /proc/38109/stack`）——
這是唯一一次能看到現場的機會，砍掉就沒了。

【2】溫和地砍，給它收尾的機會；30 秒不死才補 SIGKILL：

```bash
sudo kill -TERM 38102; sleep 30; pgrep -a data-sync || echo "已結束"
sudo kill -KILL 38102 38109      # 只在上一行還有輸出時才做
```

【3】★★★★ 補上逾時保護，否則下個月一模一樣再來一次：

```cron
0 2 * * * datasync /usr/bin/timeout --signal=TERM --kill-after=30s 45m /usr/local/bin/data-sync.sh
```

【4】驗證 `timeout` 真的生效，退出碼 `124` 有被腳本分辨出來：
`timeout --signal=TERM --kill-after=5s 3s sleep 300; echo "exit=$?"` 應回 `exit=124`。

【5】確認鎖檔在**本機**（`df -T /run/lock/data-sync.d` 應顯示 `tmpfs`）。
★★★★ 放在 NFS／CIFS 上的鎖，`local_lock`／`nolock` 會讓它只在本機有效，
兩台主機會同時寫入同一份資料互相覆蓋。

**原理**　因果鏈：NAS 沒回應 → `rsync` 卡在 `read()` 永不結束 → 該程序持有 flock →
之後每輪 `flock -n` 拿不到鎖就立刻退出 → 外觀是「再也沒跑過」且完全靜音。
　→ 原理詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]

**預防**　外層 `timeout` 保護整支腳本 + 內層對每個高風險指令再給一個較短的；
退出碼固定分類（`0` 成功／`1` 業務失敗／`2` 環境失敗／`75` 被跳過／`124` 逾時）；
監控看「最後一次**成功**的時間戳」而不是服務狀態；
★★★★ 根治是改用 systemd timer —— cgroup 會把整棵程序樹清掉，cron 做不到。

---

### ★★★★ 情境四：排程「成功」了，但產出的檔案是空的或壞的

**現象**

```text
-rw-r--r-- 1 root root      0 Aug 28 03:00 db-
-rw-r--r-- 1 root root      0 Aug 27 03:00 db-
-rw-r--r-- 1 root root 4.2G   Jul 11 03:00 db-2026-07-11.tar.gz
```

**判斷分流**

```bash
grep -rnE '[^\\]%' /etc/crontab /etc/cron.d/ /var/spool/cron/crontabs/ 2>/dev/null
```

```text
/etc/cron.d/db-backup:3:0 3 * * * root tar czf /backup/db-$(date +%F).tar.gz /var/lib/mysql
```

- 有輸出 → ★★★★ **確診：`%` 截斷**，走【1】
- 沒輸出但檔案還是空的 → 是腳本問題，先確認它有沒有把 stderr 丟掉，走【3】

**處置步驟**

【1】看懂 cron 到底執行了什麼 —— 第一個未跳脫的 `%` 之後全部變成 **stdin**：

```text
實際執行： tar czf /backup/db-$(date +
餵的stdin： F).tar.gz /var/lib/mysql
```

★★★★ 結果是 `tar` 建出一個叫 `db-` 的空檔然後 **exit 0** —— 監控一片綠燈，
直到要還原那天才發現。

【2】兩種修法，**選 B**：

```cron
# 修法 A：跳脫（可行，但半年後沒人記得為什麼有反斜線）
0 3 * * * root tar czf /backup/db-$(date +\%F).tar.gz /var/lib/mysql
# ★★★★ 修法 B（推薦）：crontab 只呼叫腳本，日期／管線／判斷全寫在腳本裡
0 3 * * * root /usr/local/bin/db-backup.sh
```

【3】拿掉靜默失敗。★★★★★ 這一行是全機關最常見的一行，
也是備份事故延遲三個月才被發現的唯一原因：

```cron
# ✗✗✗  0 2 * * * datasync /usr/local/bin/data-sync.sh >/dev/null 2>&1
# ✓     0 2 * * * datasync /usr/local/bin/data-sync.sh
```

【4】確認退出碼不會被管線吃掉。★★★ `cmd | logger` 的退出碼永遠是 `logger` 的（永遠 0），
`||` 通報永遠不會觸發 —— 用 `grep -nE '\|\s*logger' /usr/local/bin/*.sh` 掃一次。

【5】加最後一道防線：腳本自己檢查產出物合不合理，不合理就以非 0 退出 ——
`[ -s "$OUT" ] || die 1 "備份檔為空"`、`[ "$(stat -c %s "$OUT")" -gt 1048576 ] || die 1 "異常小"`。

**原理**　`%` 在 crontab 指令欄是「stdin 分隔 / 換行」符號，不是百分比 ——
而且這條規則**只在 crontab 裡成立**，同一行貼到終端機跑完全正常，所以極難自己看出來。
　→ 原理詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]

**預防**　crontab 一行只允許「絕對路徑 + 參數」，`grep -rnE '[^\\]%'` 納入每月巡檢；
備份類排程一律驗產出物大小與可還原性；通報走 webhook + 旗標檔，
不要依賴 `MAILTO`（多數機關主機根本沒有可用的 MTA）。

---

### ★★★★ 情境五：服務起不來 —— status 與 journalctl 怎麼讀

**現象**

```text
Job for apply-api.service failed.
See "systemctl status apply-api.service" and "journalctl -xeu apply-api.service" for details.
```

★★★ 這則訊息**不含任何原因**，它只是叫你去看下一層。

**判斷分流**　★★★★ 固定先看 systemd 判在哪一層，再看應用日誌；顛倒過來會多花一小時：

```bash
systemctl status apply-api --no-pager -l | head -12
```

```text
     Loaded: loaded (/etc/systemd/system/apply-api.service; enabled)
     Active: failed (Result: exit-code) since Fri 2026-08-28 16:22:03 CST; 12s ago
    Process: 8412 ExecStartPre=/usr/bin/php artisan --version (code=exited, status=255/EXCEPTION)
```

| 你看到的 | 意義 | 往哪走 |
| --- | --- | --- |
| ★★★★ `Loaded: bad-setting` / `error` | unit 檔本身有問題 | 本情境【1】 |
| `Process: ExecStartPre=... status≠0` | 前置步驟就失敗 | 本情境【3】 |
| `Main PID: ... status=1/FAILURE` | 應用自己退出 | 本情境【4】 |
| ★★★★ `status=127` / `203` | 找不到執行檔／權限 | 本情境【5】 |
| `Result: timeout` | 啟動或停止逾時 | **情境十一** |
| `Result: start-limit-hit` | 撞重啟上限 | **情境八** |
| `Result: oom-kill` | 被記憶體殺手殺掉 | **情境九** |
| `Result: watchdog` | 看門狗判定假死 | **情境八**【5】 |
| `active (running)` 但你覺得不對 | 綠燈說謊 | **情境七** |

**處置步驟**

【1】unit 檔語法。★★★★ `Unknown key` 代表**那一行被完全忽略**，不是只是報錯：

```bash
systemd-analyze verify /etc/systemd/system/apply-api.service
#  → :14: Unknown key name 'Requres' in section 'Unit', ignoring.
#  → more than one ExecStart=  ← drop-in 沒清空，跳情境十二【1】
```

【2】看 systemd **真正在用**的值，而不是你以為寫進去的：

```bash
systemctl show apply-api -p ExecStart,User,WorkingDirectory,ProtectSystem,Type
#  ★★★★ 和你的檔案不同 → 有 drop-in 在覆寫，跳情境十二
```

【3】前置步驟失敗：用**同一個身分、同一份環境**手動跑一次：

```bash
sudo -u apply env $(grep -v '^#' /etc/apply/api.env | xargs) \
     /usr/bin/php /srv/www/api/artisan --version
```

手動跑得起來、systemd 跑不起來 → 差別在沙箱或環境變數，走【6】。
手動也跑不起來 → 是應用／相依套件問題，與 systemd 無關。

【4】只看「這一次」的日誌，不要被三個月歷史淹沒（指令見「一頁式急救卡」⑤）。

【5】`127`／`203`：用 `env -i` 模擬 systemd 的乾淨環境：

```bash
systemctl show apply-api -p ExecStart --value
sudo -u apply env -i PATH=/usr/bin:/bin /usr/bin/php --version
#  → { path=/home/ops/.nvm/versions/node/v18.19.0/bin/node ; ... }
#  ★★★★ ExecStart 指向 /home/*/.nvm/ 就是它：開機時 /home 可能沒掛載、版本也可能換掉
```

【6】沙箱擋住了什麼：

```bash
sudo journalctl -u apply-api -b | grep -iE 'read-only|permission denied|operation not permitted'
```

```text
php[8420]: file_put_contents(/srv/www/api/storage/logs/laravel.log): Read-only file system
```

`Read-only file system` → `ProtectSystem=` 擋的，把路徑加進 `ReadWritePaths=`，
**不要**把 `ProtectSystem=` 整個關掉。`Operation not permitted` 而路徑正常 →
多半是 `SystemCallFilter=` 或 capability。二分法確認：用 `systemd-run --unit=nosandbox --collect`
帶同樣的 `User=`／`WorkingDirectory=`／`EnvironmentFile=` 但**不帶沙箱**跑一次，
能跑就代表確實是沙箱擋的，再逐項加回來。

**原理**　systemd 的失敗分四層：unit 檔本身 → 前置步驟 → 執行檔／環境 → 應用邏輯。
`Result:` 那一欄就是 systemd 告訴你它判在哪一層，先讀它可以直接跳過三層。
　→ 原理詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]，
　　status 各欄位見 [[020-01-17-cmd-Linux-systemd服務管理]]

**預防**　上線前跑 `systemd-analyze verify` 並用 `systemd-run` 不落檔試跑；
unit 檔納入 git，drop-in 檔名加序號前綴；`ExecStart=` 一律絕對路徑，
不用 nvm／pyenv 這種會漂移的路徑。

---

### ★★★★ 情境六：重開機後服務掛掉，手動 start 就正常

**現象**　★★★★ 全機關「只有開機會失敗一次」事故的頭號來源：

```text
● collector.service - Asset Collector
     Active: failed (Result: exit-code) since Fri 2026-08-28 08:31:07 CST; 3min ago
8月 28 08:31:07 srv01 python[921]: OSError: [Errno 99] Cannot assign requested address
```

上去手動 `systemctl start` → `active`。於是被誤判成「偶發」，追一整天。

**判斷分流**

```bash
sudo journalctl -u collector -b | grep -iE 'cannot assign|name resolution|no such file|connection refused'
systemctl show collector -p After,Wants,Requires,RequiresMountsFor
```

| 錯誤關鍵字 | 問題在 | 走 |
| --- | --- | --- |
| ★★★★ `Cannot assign requested address` / `Temporary failure in name resolution` | 網路還沒好 | 【1】 |
| ★★★★ 檔案「寫進去了但找不到」／目標目錄是空的 | 掛載還沒好 | 【3】 |
| ★★★★ PID／socket 檔寫不出來（`/run/xxx/` 不存在） | `/run` 是 tmpfs，開機清空 | 【4】 |
| `Connection refused` 連 DB／Redis | 相依服務沒被拉起來 | 【5】 |

**處置步驟**

【1】網路：★★★★ 兩行**缺一不可**：

```ini
[Unit]
After=network-online.target
Wants=network-online.target      # ★★★★ 沒這行，target 不會被拉起來，After 等於白寫
```

【2】確認 wait-online 真的有 enable，否則 `network-online.target` 會「秒到達」：

```bash
systemctl is-enabled systemd-networkd-wait-online.service   # → enabled
systemctl list-dependencies network-online.target
```

★★★ NetworkManager 環境（Ubuntu Desktop、RHEL 系）要 enable 的是
`NetworkManager-wait-online.service`，不是 networkd 那支。

【3】掛載：★★★★ 這是無聲資料遺失，比服務起不來嚴重 ——
服務寫進被掛載點蓋住的本機空目錄，掛載完成後那些檔案看不見也刪不掉：

```ini
[Unit]
RequiresMountsFor=/srv/share/uploads
```

```bash
# fstab 對應加上： nas01:/export /srv/share/uploads nfs4 _netdev,x-systemd.automount 0 0
sudo systemctl daemon-reload      # ★★★ 改 fstab 之後一定要 reload，.mount unit 才會重生成
findmnt /srv/share/uploads
```

【4】`/run` 底下的目錄交給 systemd 建，不要自己 `mkdir` ——
`[Service]` 加 `RuntimeDirectory=collector` 與 `RuntimeDirectoryMode=0750`。

【5】相依服務：★★★ 預設 `Wants=` + `After=`，不要用 `Requires=`（理由見情境十二【4】）：

```bash
systemctl list-dependencies --after collector.service | head
```

【6】攤開整條時序鏈，看誰拖住誰：

```bash
systemd-analyze critical-chain collector.service
```

```text
collector.service +412ms
└─mysql.service @6.201s +1.994s
  └─network-online.target @6.180s
    └─systemd-networkd-wait-online.service @2.109s +4.070s
```

★★ `@` 是「開始啟動的時間點」、`+` 是「花了多久」
`wait-online` 佔 4 秒通常是在等一張沒插線的備援網卡。

【7】★★★★ **唯一可信的驗收是真的重開機**，不是 `systemctl restart`：

```bash
sudo reboot
# 開機後：
systemctl is-system-running; systemctl --failed --no-legend
```

**原理**　`After=` 管**順序**、`Wants=`／`Requires=` 管**強度**，兩者互不相干，
不是同一件事的強弱版本。只寫 `After=X` 的意思是「如果 X 也要啟動，那我排在它後面」——
X 沒被 enable 就根本不會起來。而 `network.target` 只代表網路**子系統**啟動了，
不代表任何一張網卡拿到 IP。
　→ 原理詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]

**預防**　新 unit 的驗收清單固定有「重開機一次」；`Requires=` 只用在
「對方不在我就絕對不該存在」（綁 VPN 介面、LUKS 裝置）；
連線類相依交給應用層重試 + `Restart=on-failure`，不要用相依關係硬撐。

---

### ★★★★ 情境七：status 是綠燈，服務其實是壞的

**現象**　值班說「服務是 active 啊」，但使用者打不開網頁，或前台整個不見：

```text
● nuxt-app.service - Nuxt SSR front-end
     Active: active (running) since Mon 2026-05-11 03:14:02 CST; 3 months ago
```

**判斷分流**　★★★★ 綠燈說謊有四種成因，先用這條分流：

```bash
sudo ss -lptnH 'sport = :3000'
#  → LISTEN 0 511 127.0.0.1:3000 users:(("node",pid=1899,fd=22))
```

- 沒有輸出 → 應用根本沒在聽，走【1】
- 有輸出 → 有東西在聽，但可能是**別的**東西，走【2】

**處置步驟**

【1】`Type=` 選錯，systemd 誤判「啟動完成」：

```bash
systemctl show nuxt-app -p Type,PIDFile,MainPID,NotifyAccess
#  → Type=forking / MainPID=0   ★★★★ pid 檔沒出現 → forking 判定失敗
```

| ExecStart 的實際行為 | 該用的 Type | 誤用的後果 |
| --- | --- | --- |
| 前景不 fork（`pm2-runtime`、`node index.mjs`） | `simple` / ★★★ `exec` | 寫成 `forking` → 卡在 activating |
| 會 fork 到背景（`pm2 start`） | `forking` + `PIDFile=` | 寫成 `simple` → systemd 誤判服務已結束 |
| ★★★★ 後面有人在等它（Nginx、部署腳本） | `notify` + 應用送 `READY=1` | 用 `simple` → 啟動後數秒內全部 502 |

【2】確認在聽的那個程序歸誰管：`cat /proc/1899/cgroup`。
`/system.slice/nuxt-app.service` 是正常；
★★★★ `/user.slice/.../session-3.scope` 代表有人手動起的，`systemctl` 管不到。

【3】★★★★★ PM2 環境專屬：`PM2_HOME` 一致性 —— 這是「重開機後前台整個不見、
但 status 綠燈」的唯一成因：

```bash
sudo tr '\0' '\n' < /proc/1899/environ | grep -E '^(PM2_HOME|NODE_ENV|PORT)='
systemctl show pm2-ops -p Environment
```

```text
PM2_HOME=/root/.pm2                              # 實際在跑的
Environment=PATH=... PM2_HOME=/home/ops/.pm2     # ★★★★★ unit 說的
```

兩者不同 → **確診，重開機必炸**。多半是有人用過 `sudo pm2 save`，存到了 `/root/.pm2`。

【4】確認只有一個 God Daemon：`ps -eo user,pid,args | grep -F 'God Daemon' | grep -v grep`
必須只有 1 行。★★★★ 兩個 daemon 並存的第二種結局最難查：對外服務的是**舊版本的程式碼**，
部署明明成功、頁面卻沒更新。

【5】PM2 架構 A 的根本盲區 —— unit 監看的是 God Daemon，worker 全 `errored` 也不影響判定：

```bash
curl -fsS --max-time 5 http://127.0.0.1:3000/healthz || echo "★★★★ 應用沒回應"
sudo -iu ops pm2 jlist | jq -r '.[] | "\(.name) \(.pm2_env.status) restarts=\(.pm2_env.restart_time)"'
#  → nuxt-app errored restarts=142
```

【6】止血：以 unit 宣告的 `PM2_HOME` 重來一次。根治是遷到架構 B
（unit 直接跑 `pm2-runtime`，日誌進 journal），或加一支健康檢查 timer 打 `/healthz`。
★★★★ 順便問一句：**你的監控是不是只在看 `systemctl is-active`？** 是的話這個情境會一直復發。

```bash
sudo -u ops PM2_HOME=/home/ops/.pm2 pm2 start /var/www/app/current/ecosystem.config.cjs
sudo -u ops PM2_HOME=/home/ops/.pm2 pm2 save && sudo systemctl restart pm2-ops
```

**原理**　`Type=simple` 在 `fork()` 完成的瞬間就宣告成功；`Type=forking` 只看 PID 檔；
PM2 架構 A 的 unit 監看的是 God Daemon 而不是應用。三者的共同點：
**systemd 判定的「活著」和「能接請求」是兩件事**。
　→ 原理詳見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]，
　　`Type=notify` 的正解見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]

**預防**　對外服務一律 `Type=notify` 或搭健康檢查 timer；禁止互動式 `pm2 start`／`sudo pm2 save`；
`PM2_HOME` 在 unit 裡明寫並移出 `/home`（改 `/var/lib/<user>/.pm2`）。

---

### ★★★★ 情境八：服務一直在重啟，卻沒有人知道

**現象**　兩種完全不同的畫面，根因是同一組參數：

```text
死法一：Active: failed (Result: start-limit-hit) since Sat 2026-08-28 03:11:12 CST; 9h ago
死法二：Active: active (running) since Sat 2026-08-28 14:04:31 CST; 12s ago   ← 「剛剛」才起來
```

★★★★ 死法二最危險 —— 它從來不會進 `failed`，所以 `OnFailure=` 告警**一次都不會觸發**，
整晚每 30 秒重啟一次也沒人知道。

**判斷分流**

```bash
systemctl show apply-api -p NRestarts,Result,ActiveEnterTimestamp
systemctl show apply-api -p RestartUSec,StartLimitIntervalUSec,StartLimitBurst
journalctl -u apply-api --since -1h | grep -c 'Scheduled restart job'
```

```text
NRestarts=2873
Result=success
ActiveEnterTimestamp=Sat 2026-08-28 14:04:31 CST
RestartUSec=30s
StartLimitIntervalUSec=10s      # ★★★★ RestartSec(30s) > Interval(10s) → 永遠撞不到上限
StartLimitBurst=5
118
```

- `Result=start-limit-hit` → 死法一，走【1】
- `NRestarts` 很大 + `ActiveEnterTimestamp` 是剛剛 → 死法二，走【2】
- 三個參數都是預設值（`100ms` / `10s` / `5`）→ ★★★★ 你的設定寫錯區段了，走【3】

**處置步驟**

【1】死法一：★★★★ 修好根因後**必須**清計數器，否則 `systemctl start` 一直被擋，
而且錯誤訊息跟原因完全無關：

```bash
sudo systemctl reset-failed apply-api && sudo systemctl start apply-api
systemctl is-active apply-api      # → active
```

【2】死法二：把比例調回會撞上限。★★★★ 準則是 `RestartSec × (Burst − 1) < IntervalSec`：

```ini
[Unit]
StartLimitIntervalSec=300
StartLimitBurst=5
[Service]
Restart=on-failure
RestartSec=10            # 10 × 4 = 40 < 300 ✓
```

【3】★★★★ 確認寫對區段。`StartLimitIntervalSec=` / `StartLimitBurst=` 在 **`[Unit]`**，
不是 `[Service]`（systemd 230 之後）。寫錯區段**不會報錯，只會安靜失效** ——
`StartLimitBurst=` 甚至連 `Unknown key` 警告都沒有：

```bash
systemctl show apply-api -p StartLimitIntervalUSec,StartLimitBurst   # ★★★ 一律用 show 看生效值
```

【4】找出「為什麼一直掛」的退出碼：
`journalctl -u apply-api -n 30 | grep -iE 'main process exited|failed with result'`，
會看到類似 `Main process exited, code=exited, status=78/CONFIG`。
`78/CONFIG`、`1/FAILURE` 且每次都一樣 → **設定檔問題，重啟一萬次也一樣**。
修完根因後用 `RestartPreventExitStatus=78` 把它擋在重啟迴圈外。

【5】`Result=watchdog`：先確認應用到底有沒有在送心跳：

```bash
systemctl show apply-api -p WatchdogUSec,NotifyAccess,Type,Restart
journalctl -u apply-api | grep -i watchdog | tail -5
#  → WatchdogUSec=30s / Restart=no  ★★★★ 假死後會就地停機
#  → Watchdog timeout (limit 30s)!
```

每 30 秒準時觸發一次 → 應用根本沒實作心跳，**移除 `WatchdogSec=`**，改健康檢查 timer；
`Restart=no` → 立刻補上 `Restart=on-failure`。

【6】PM2 環境專屬：兩層重啟互踩，★★★★ `RestartSec` 必須 ≥ PM2 的 `min_uptime`：

```bash
systemctl show nuxt-app -p RestartSec         # → RestartSec=1s   ★★★★ 太短
grep -E 'min_uptime|restart_delay|max_restarts' /var/www/app/current/ecosystem.config.cjs
#  → min_uptime: '10s'   兩層搶著重啟
```

【7】部署造成的假失敗：worker 收 SIGTERM 以 143 退出被當成失敗 → `SuccessExitStatus=143 SIGTERM`。

【8】收尾時掃一次整機（`systemctl is-system-running` + `systemctl --failed`），
確認沒有別的 unit 也在安靜地死。回 `degraded` 就代表還有。

**原理**　`RestartSec` 與 `StartLimitIntervalSec` 的比值決定服務走向哪一種安靜的死亡：
設太急 → 1 秒內撞上限、服務永久停擺；設太鬆 → 永遠不撞上限、無限重啟灌爆磁碟。
**兩種結局都沒有人會知道**，而預設值剛好是前者。
　→ 原理詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]

**預防**　建議值 `RestartSec=10` / `StartLimitIntervalSec=300` / `StartLimitBurst=5`；
★★★★ 監控加 `NRestarts` 增量與 `systemctl is-system-running`；
★★★★★ **絕對不要**順手設 `StartLimitAction=reboot-force`（一支 worker 掛掉會害整台機器
進重開機迴圈，而根因重開機修不好）；測 `Restart=on-failure` 要用
`systemctl kill -s SIGKILL <unit>` —— 用 `kill <pid>` 送的是 SIGTERM（乾淨退出），
測出「沒重啟」是**測試方法錯**不是設定錯。

---

### ★★★★ 情境九：被 OOM Killer 殺掉，或 `/var` 被 journal 塞爆

**現象**

```text
systemd[1]: apply-api.service: A process of this unit has been killed by the OOM killer.
/dev/mapper/vg-var  20G   20G     0  100% /var
```

**判斷分流**

```bash
journalctl -u apply-api --since -1d | grep -iE 'out of memory|oom-kill|memory limit'
systemctl show apply-api -p MemoryMax,MemoryPeak,MemoryCurrent,OOMPolicy
journalctl --disk-usage
```

```text
MemoryMax=2147483648
MemoryPeak=2147480000        # ★★★★ 貼著上限 = cgroup 限額打死的，不是整機沒記憶體
Archived and active journals take up 12.4G in the file system.
```

- `MemoryPeak` 貼著 `MemoryMax` → cgroup 限額太低或程式洩漏，走【2】
- `MemoryMax=infinity` 而系統 log 有 `Out of memory: Killed process` → 整機記憶體不足，走【3】
- journal 佔 10 GB 以上 → 是重啟迴圈的副作用，先做【1】止血，再回**情境八**

**處置步驟**

【1】磁碟止血：`sudo journalctl --vacuum-size=500M`（★★★ 只是止血，不做【2】幾天後會再爆）。

【2】確認是不是「每天固定被殺幾次」的洩漏型：

```bash
journalctl -u apply-api --since -7d | grep -c 'killed by the OOM killer'
systemctl show apply-api -p NRestarts
```

★★★ 每天固定 3～4 次 = 記憶體洩漏 + `MemoryMax=` 觸發 + `Restart=` 自動復原。
**看起來很穩定，但每次重啟都掉請求。** 重啟只是止血，要開變更單追根因。

【3】整機層面用 `systemd-cgtop -m --order=memory -n 1 | head -12` 確認誰在吃記憶體。

【4】調整限額（★★★ 要有依據，不是隨便加大）：

```ini
[Service]
MemoryHigh=2500M          # ★★★ 先觸發回收壓力，比直接 kill 溫和
MemoryMax=3G
OOMPolicy=stop
```

【5】長期：把 journal 上限設好，讓重啟迴圈灌不爆磁碟
（`/etc/systemd/journald.conf` 的 `SystemMaxUse=`，建議不超過 `/var` 的 10%）。

**原理**　OOM 有兩層：cgroup 層（`MemoryMax=` 觸發，只殺這個 unit）與整機層
（核心 OOM killer 挑一個殺）。兩者處置完全不同，`MemoryPeak` 貼不貼著 `MemoryMax`
是最快的分辨方法。而 journal 爆掉通常不是獨立問題，是重啟迴圈的下游症狀。
　→ 原理詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]，
　　journal 輪替見 [[020-01-19-guide-Linux-日誌系統]]

**預防**　`journald.conf` 一律設 `SystemMaxUse=`；每個正式服務都設 `MemoryMax=`
並把 `MemoryPeak` 納入月報；★★★ 用「重啟次數」而不是「服務狀態」當監控指標，
洩漏型問題才看得出來。

---

### ★★★★ 情境十：timer 到時間沒觸發

**現象**　`systemctl list-timers` 找不到它，或找得到但 `LAST` 是空的、`NEXT` 停在過去。

**判斷分流**

```bash
systemctl list-timers --all --no-pager | grep -i mof
systemctl list-unit-files --type=timer --no-pager | grep -i mof
#  （第一條沒有輸出）
#  mof-export.timer     disabled  disabled
```

- 兩條都有輸出 → timer 活著，問題在被觸發的 service，走【4】
- 第一條沒有、第二條有 → ★★★★ **檔案在但沒載入**，走【1】
- 兩條都沒有 → 這支根本不是 timer，回**情境二**查 cron 家族，或走【6】查 user timer

**處置步驟**

【1】看 enable 狀態：`systemctl is-enabled mof-export.timer`

| 輸出 | 意義 | 動作 |
| --- | --- | --- |
| `enabled` | 正常 | 往下查 |
| ★★★★ `disabled` | 只 `start` 沒 `enable`，重開機不會起來 | `sudo systemctl enable --now X.timer` |
| `static` | 沒有 `[Install]` 區段 | 補 `[Install]` + `WantedBy=timers.target` 再 enable |
| ★★★ `masked` | 被人刻意封鎖 | **先查清楚誰為什麼 mask**，再 `unmask` |
| `not-found` | 檔案不存在 | 查 `/etc/systemd/system/` 與 `/usr/lib/systemd/system/` |

【2】看 timer 的上次與下次：

```bash
systemctl show mof-export.timer -p NextElapseUSecRealtime,LastTriggerUSec,Persistent,Unit,AccuracyUSec
```

- `LastTriggerUSec=` 空的 → ★★★★ 從未觸發過
- `NextElapseUSecRealtime=` 空的 → 運算式已無下一次（寫了過去的固定日期），走【3】

【3】驗證運算式與時區：

```bash
systemd-analyze calendar '*-*-* 05:00:00' --iterations=5
timedatectl | grep -E 'Time zone|synchronized'
```

```text
    Next elapse: Sat 2026-08-29 05:00:00 CST
       (in UTC): Fri 2026-08-28 21:00:00 UTC
                 Time zone: Asia/Taipei (CST, +0800)
```

★★★★ `Next elapse` 與 `(in UTC)` 是**同一個時間** → 機器時區是 UTC，所有排程集體位移
8 小時（雲端映像的預設值），`sudo timedatectl set-timezone Asia/Taipei`。
迭代結果跳過某些月份 → 踩到月底邊界（29／30／31 號，二月會整月不跑），改 `*-*-28`。

【4】確認綁定的 service 存在，並看它上次的結果：

```bash
SVC=$(systemctl show mof-export.timer -p Unit --value); echo "綁定：$SVC"
systemctl show "$SVC" -p Result,ExecMainStatus,ExecMainStartTimestamp,ExecMainExitTimestamp
```

```text
綁定：mof-transfer.service
Result=exit-code   ExecMainStatus=2
ExecMainStartTimestamp=Fri 2026-08-28 05:03:47 CST
ExecMainExitTimestamp=Fri 2026-08-28 05:03:48 CST
```

★★★ 只花 1 秒但正常要跑三十秒 → **第一步就失敗了**。
★★★ `journalctl -u X.service` 查不到東西，多半是**你查的是 timer 的名字** ——
timer 與 service 不同名，用上面那個 `$SVC` 才對。

【5】手動觸發，把「排程問題」和「腳本問題」切開：

```bash
sudo systemctl start "$SVC"; systemctl show "$SVC" -p Result --value
```

手動成功、排程時失敗 → ★★★ 問題在「那個時間點的環境」：資料還沒產生、網路還沒通、
掛載還沒好 → 回**情境六**補 `After=` / `RequiresMountsFor=`。

【6】`--user` timer 的專屬坑：★★★★ 使用者一登出，整組 user unit 就被收掉。
`loginctl show-user ops -p Linger` 回 `Linger=no` 就是它（前手離職登出後排程默默停了）。
過渡期 `sudo loginctl enable-linger ops`；長期改寫成 system timer + `User=ops`。

【7】兩個收尾檢查：`Persistent=` ★★★ **只對 `OnCalendar=` 有效**，monotonic timer
（`OnBootSec=`／`OnUnitActiveSec=`）設了也沒用（看 `/var/lib/systemd/timers/stamp-*` 有沒有產生）；
開機時被跑兩次 → service 自己也有 `[Install]` 且被 enable 了，`sudo systemctl disable "$SVC"`。

**原理**　timer 的「沉默死亡」有兩種：只 `start` 沒 `enable`（重開機就消失）、
`--user` timer 沒開 lingering（使用者登出就停）。兩種都要等好幾週才會被發現，
因為 `systemctl status` 在事發當下是正常的。
　→ 原理詳見 [[020-02-02-02-cmd-systemd-timer與cron選型]]，
　　時間運算式語法見 [[020-01-18-guide-Linux-排程工作]]

**預防**　上線驗收固定跑 `systemctl is-enabled X.timer`，`enabled` 才算完成；
全機關統一 `timedatectl set-timezone` 並納入標準機建置流程；
多台主機打同一來源時加 `RandomizedDelaySec=1800` + `FixedRandomDelay=true`；
遷移一律**先停舊、再開新**（並存期兩邊都開會造成資料重複）。

---

### ★★★ 情境十一：`systemctl stop` 卡 90 秒，或停完埠還被佔著

**現象**

```text
systemd[1]: nuxt-app.service: State 'stop-sigterm' timed out. Killing.
systemd[1]: nuxt-app.service: Killing process 1899 (node) with signal SIGKILL.
```

更詭異的版本：`systemctl is-active` 回 `inactive`，但 `ss` 顯示埠還被佔著。

**判斷分流**

```bash
systemd-cgls -u pm2-ops.service
cat /proc/1899/cgroup
#  → 0::/user.slice/user-1000.slice/user@1000.service/app.slice/session-3.scope
```

- ★★★★ 程序**不在** unit 的 cgroup 內（顯示 `user@`／`session-`）→ 有人在 SSH session
  手動起的，`systemctl stop` 永遠殺不到它，走【4】
- 程序在 cgroup 內但停不掉 → SIGTERM 沒被處理，走【1】

**處置步驟**

【1】看逾時設定與實際發生了什麼：`systemctl show nuxt-app -p TimeoutStopUSec,KillMode,KillSignal`
搭配 `journalctl -u nuxt-app -b | grep -E "timed out|Killing"`。

【2】確認訊號有沒有真的送到應用。★★★ 用 `sh -c '...'` 而沒有 `exec`，
訊號只會送到 shell，真正的程式收不到：

```bash
systemctl show nuxt-app -p ExecStart --value
#  → { path=/bin/sh ; argv[]=/bin/sh -c "node /srv/app/index.mjs" ; ... }   ★★★★ 缺 exec
```

修法：`ExecStart=` 直接指執行檔，或寫成 `/bin/sh -c 'exec node /srv/app/index.mjs'`。

【3】三個逾時要對齊（★★★★ 部署期零星 502 的根因）：

| 層 | 參數 | 建議關係 |
| --- | --- | --- |
| 應用 | SIGTERM handler 的收尾耗時 `T_app` | 實測出來 |
| PM2 | `kill_timeout`（預設僅 1600 ms） | ≥ `T_app` + 緩衝，例如 `30000` |
| systemd | `TimeoutStopSec=` | ≥ `kill_timeout`，例如 `45` |

【4】殘留程序的清理與根治：

```bash
sudo kill -TERM 1899; sleep 10; pgrep -a node
sudo loginctl disable-linger ops; loginctl show-user ops -p Linger   # → Linger=no
```

★★ `disable-linger` 是止血不是根治 —— 正式機的應用本來就不該由互動 session 啟動。

【5】部署 `restart` 砍掉進行中工作：★★★★ `TimeoutStopSec` 必須 ≥ 單筆工作最長耗時 + 30s：

```ini
[Service]
TimeoutStopSec=6min
KillMode=mixed          # 主程序收 SIGTERM，子程序交給它自己收
```

【6】PM2 專屬：`ExecStop=pm2 kill` 連到別的 `PM2_HOME` 或 socket 壞掉，殺不到東西：

```bash
sudo rm -f /home/ops/.pm2/rpc.sock /home/ops/.pm2/pub.sock; sudo systemctl restart pm2-ops
```

**原理**　`systemctl stop` 的流程是「送 `KillSignal`（預設 SIGTERM）→ 等 `TimeoutStopSec`
→ 送 SIGKILL」。卡 90 秒代表這三步都走完了，成因只有三種：程式不理 SIGTERM、
訊號只到 shell、逾時設太短。而 cgroup 歸屬決定 systemd 到底殺不殺得到那個程序。
　→ 原理詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]，
　　三層逾時對齊見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]，
　　訊號語意見 [[020-01-10-cmd-Linux-程序管理與訊號]]

**預防**　應用一律註冊 SIGTERM handler（PHP 要載 pcntl、Node 要 `process.on('SIGTERM')`）；
`TimeoutStopSec=` 明寫不用預設值；正式機禁止互動式啟動應用。

---

### ★★★ 情境十二：改了設定卻沒生效，或一改就連鎖出事

**現象**　改了 unit 檔、`restart` 了，行為卻完全沒變；或者相反 ——
只是重啟資料庫，五個 worker 一起消失且沒有回來。

**判斷分流**

```bash
systemctl cat apply-api | grep '^# /'
systemctl show apply-api -p ExecStart,Environment
```

```text
# /etc/systemd/system/apply-api.service
# /etc/systemd/system/apply-api.service.d/90-hardening.conf
# /etc/systemd/system/apply-api.service.d/override.conf     ★★★ 只針對這個實例的覆寫
```

- `show` 的值和你的檔案不同 → 有 drop-in 在覆寫，走【1】
- `show` 的值相同但行為沒變 → 忘了 `daemon-reload` 或改錯檔案，走【3】
- 是「一改就連鎖出事」→ 走【4】

**處置步驟**

【1】drop-in 的 list 型陷阱。★★★★ `ExecStart=` 是 list 型，
沒先寫空值清空會變成**兩條**，unit 直接 `Loaded: bad-setting`：

```ini
[Service]
ExecStart=                                   # ★★★★ 這一行不能少
ExecStart=/usr/bin/php /srv/www/api/artisan queue:work
```

```bash
systemctl show apply-api -p ExecStart | grep -c 'path='    # 必須是 1
```

【2】★★★ template unit 的 drop-in 可以同時存在**兩層**：`app@.service.d/`（所有實例）
與 `app@mail.service.d/`（只有這個實例）。全機盤點用 `systemd-delta --type=extended,overridden`，
確定要清掉某個 unit 的全部覆寫時用 `sudo systemctl revert <unit>`。

【3】★★★ 手動編輯 unit 檔不會自動 reload，看到 `changed on disk` 警告就是漏了這步
（改 `/etc/fstab` 之後也一樣，`.mount` unit 是從 fstab 產生的）：

```bash
sudo systemctl daemon-reload && sudo systemctl restart apply-api
```

【4】連鎖出事：誤用 `Requires=`，★★★ 停止會沿相依鏈**傳播**（而且傳播的是停止不是重啟，
所以停掉之後不會自己回來）：

```bash
systemctl list-dependencies --reverse mysql.service | head
systemctl show apply-worker@mail -p Requires,Wants,After,PartOf
```

修法：改成 `Wants=` + `After=`，讓應用自己重試連線；真的需要連動才用 `PartOf=`／`BindsTo=`。

【5】template unit 只 enable 了一個實例，其他只是 `start` 過 ——
★★★★ 重開機後只有一條 queue 在跑，其他靜默堆積。驗收查
`ls /etc/systemd/system/multi-user.target.wants/ | grep 'apply-worker@'` 的連結數，
補齊用 `sudo systemctl enable --now apply-worker@{mail,sms,report}.service`。

【6】另外兩個「安靜失效」：`Type=oneshot` 跑完變 `inactive`，被 `Requires=` 它的服務
視為未滿足 → 加 `RemainAfterExit=yes`（正常狀態會是 `active (exited)`）；
`systemctl reload` 回報 `Job type reload is not applicable` → unit 沒有 `ExecReload=`，
補 `ExecReload=/bin/kill -HUP $MAINPID`。

**原理**　systemd 的生效值來自「套件 unit + 所有 drop-in 疊加」的結果：
`systemctl cat` 看疊加順序、`systemctl show` 看最終值 —— 兩者都不是你手上那個檔案。
　→ 原理詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]

**預防**　覆寫套件 unit 一律用 `systemctl edit`，不要直接改 `/usr/lib/systemd/system/`；
drop-in 檔名加序號（`10-`、`90-`）並納入 git；
部署腳本固定「`daemon-reload` → `systemctl show` 驗關鍵值 → 才 `restart`」。

---

## 一頁式急救卡

出事時來不及讀長文，先把這幾條跑完，答案通常就出現了。

```bash
# ① 整機健康狀態 —— 一行就知道有沒有東西壞掉
systemctl is-system-running; systemctl --failed --no-legend
#   running  = 全部正常
#   degraded = ★★★★ 至少有一個 unit 在 failed，第二行就是清單
#   starting = 還在開機，等 30 秒再看

# ② 這個服務現在什麼狀態、systemd 判在哪一層
systemctl status <unit> --no-pager -l | head -12
#   Result: exit-code       → 應用自己退出，看退出碼（情境五）
#   Result: start-limit-hit → 撞重啟上限，要 reset-failed（情境八）
#   Result: timeout         → 啟動或停止逾時（情境十一）
#   Result: oom-kill        → 被記憶體殺手殺掉（情境九）
#   Loaded: bad-setting     → unit 檔本身有問題（情境五【1】）

# ③ 它到底重啟了幾次 —— ★★★★ 綠燈說謊時唯一看得出來的地方
systemctl show <unit> -p NRestarts,Result,ActiveEnterTimestamp
#   NRestarts 很大 + ActiveEnterTimestamp 是「剛剛」 = 無限重啟（情境八）

# ④ systemd 真正在用的設定值（不是你檔案裡寫的那個）
systemctl show <unit> -p ExecStart,Type,Restart,RestartUSec,StartLimitIntervalUSec,StartLimitBurst
#   和你的檔案不同 → 有 drop-in 在覆寫（情境十二）
#   三個 Limit 都是 100ms/10s/5 → 你的設定寫錯區段了

# ⑤ 只看「這一次」的日誌，不要被三個月的歷史淹沒
sudo journalctl _SYSTEMD_INVOCATION_ID="$(systemctl show -p InvocationID --value <unit>)" --no-pager
#   沒有輸出 → 服務從沒真的跑起來過，回 ②

# ⑥ 對外的埠到底是誰在聽、那個程序歸誰管
sudo ss -lptnH 'sport = :<port>'; cat /proc/<pid>/cgroup
#   沒有輸出          → 應用沒起來（情境五 / 七）
#   cgroup 是 user@   → ★★★★ 有人手動起的，systemctl 管不到（情境十一）

# ⑦ 排程類：先分辨「沒被啟動」還是「啟動了失敗」
sudo journalctl -u cron --since "-1d" | grep -iE '<關鍵字>|bad username|Error'
systemctl list-timers --all --no-pager | head -20
#   連 CMD 那行都沒有 → 沒被啟動（情境二）
#   有 CMD 但結果不對 → 環境問題（情境一）

# ⑧ 磁碟與記憶體 —— 很多「怪問題」其實只是這兩個
df -h /var /tmp; journalctl --disk-usage; systemd-cgtop -m --order=memory -n 1 | head -8
```

> [!tip] 只記得住一件事的話 ★★★★★
> **`systemctl status` 顯示 `active (running)` 不代表服務是好的。**
> 綠燈說謊有四種：`Type=` 選錯、PM2 架構 A 的盲區、無限重啟中剛好被你看到、
> 應用假死但沒有 watchdog。要證明服務是好的，只有一個方法 ——
> **打它的健康檢查端點**。

**接手陌生主機時的排程八來源盤點**（★★★ 少看一個就會漏掉整批排程）：

```bash
# ① 全部使用者的 crontab
sudo sh -c 'for u in $(cut -d: -f1 /etc/passwd); do crontab -lu "$u" 2>/dev/null | grep -q . && echo "== $u"; done'
# ②③ /etc/crontab 與 /etc/cron.d/
sudo grep -RIn --include='*' -e '^[0-9*@]' /etc/crontab /etc/cron.d/ 2>/dev/null
# ④ run-parts 目錄與 anacron
ls -l /etc/cron.{hourly,daily,weekly,monthly}/ ; cat /etc/anacrontab 2>/dev/null
# ⑤ at 佇列
atq
# ⑥ system timer
systemctl list-timers --all --no-pager
# ⑦ user timer（★★★★ 最容易整批漏掉的一層）
loginctl list-users; sudo loginctl show-user <u> -p Linger
# ⑧ 應用自帶的排程（Laravel schedule:list、n8n、資料庫 event scheduler…）
```

---

## 什麼時候該停手求援

★★★★ 以下情況**不要再自己動手**。繼續操作會讓證據消失、或把可以救的災情變成不能救的。
先做的事是「凍結現況 + 通報」，不是「再試一個指令」。

| 情況 | 為什麼要停手 | 停手前唯一該做的事 |
| --- | --- | --- |
| ★★★★★ 懷疑遭入侵（多出不認識的 cron 行、陌生的 timer、God Daemon 跑在 root 底下而沒人知道為什麼） | 排程是入侵者建立持續性存取的頭號手段。你一 `rm` 掉那行，就同時毀掉時間戳、檔案 inode 與關聯證據 | 拍照／截圖，`cp -a` 保留原檔到別的路徑，記下發現時間，立刻通報資安窗口。**不要重開機**（記憶體證據會消失） |
| ★★★★★ 資料庫檔案損毀（`InnoDB: Database page corruption`、服務起不來且日誌指向資料檔） | 反覆 `systemctl restart` 會讓 crash recovery 一再重跑，可能把可修復的損壞擴大 | 立刻 `systemctl stop` 並**設定 `systemctl mask`** 防止自動重啟迴圈，先做整份資料目錄的離線複本，再找 DBA |
| ★★★★★ RAID 降級中（`/proc/mdstat` 出現 `_` 或 `[U_]`、控制器亮黃燈） | 重建期間磁碟負載最高，第二顆掉了就全毀。此時跑備份排程、大量 I/O 或重開機都在加風險 | `cat /proc/mdstat` 存檔，暫停所有 I/O 密集排程，通報硬體廠商。**不要拔任何一顆硬碟**（見 [[020-01-29-guide-Linux-網路儲存與軟體RAID]]） |
| ★★★★ 進入重開機迴圈（設了 `StartLimitAction=reboot-force` 之類的動作） | 機器每幾分鐘重開一次，你連登入都來不及。而且根因（設定檔錯）重開機修不好 | 從帶外管理（iDRAC／iLO／IPMI）或 GRUB 進 rescue mode，見 [[020-01-25-guide-Linux-開機流程與GRUB救援]] |
| ★★★★ 檔案系統唯讀（`Read-only file system` 而 unit 沒設沙箱、`dmesg` 有 I/O error） | 這是硬碟或控制器在示警，不是權限問題。硬 `mount -o remount,rw` 可能造成更大範圍的資料毀損 | `dmesg -T \| tail -50` 存檔，`smartctl -a` 存檔，通報硬體廠商 |
| ★★★★ 磁碟 100% 且你不確定哪些檔案可以刪 | 刪錯東西（例如刪掉還在被寫入的資料檔）不會立刻釋放空間，卻會弄丟資料 | 只清 `journalctl --vacuum-size=` 與 `/var/cache/`，其他一律先問。`du -xh --max-depth=2 /var \| sort -h \| tail` 存檔 |
| ★★★ 改動會影響其他機關／對外交換的排程（資料交換、對外報送） | 停錯一支排程可能造成對方機關收不到資料，而且補送要走公文 | 先確認變更窗口與通報對象，走 [[100-02-08-guide-維運-變更管理流程]] |
| ★★★ 你已經連續改了三個地方，情況變得更糟 | 每多改一項，就多一個變因，回滾也更難 | 停下來，把已經改過的東西列出來，逐項回滾到原狀，再重新從急救卡 ① 開始 |

> [!danger] ★★★★★ 三件在事故當下絕對不要做的事
> 1. **`setenforce 0`** —— 為了「先讓它跑起來」關掉 SELinux，等於在事故中同時拆掉防線，
>    而且事後沒有人會記得開回去。正解是 `ausearch` + `semanage fcontext`。
> 2. **`rm` 掉「看起來沒用」的鎖檔、PID 檔、log 檔** —— 那可能正是唯一的現場證據，
>    而且刪鎖檔對 flock 根本沒有效果（flock 綁的是 fd）。
> 3. **`systemctl restart` 之後就宣告修好** —— 重啟會清掉現場。
>    修好的定義是「知道為什麼壞、而且知道它不會再壞」，不是「現在是綠燈」。
>
> 事故分級與通報時機見 [[100-02-09-svc-維運-事件處理與升級流程]]。

---

## 延伸閱讀

**本章各篇（原理都在這裡）**

- [[020-02-02-00-idx-systemd-系統服務與排程]] — 本章索引與建議閱讀順序
- [[020-02-02-01-svc-systemd-unit撰寫實戰]] — 相依、掛載、目錄委派、drop-in、停機語意、沙箱
- [[020-02-02-02-cmd-systemd-timer與cron選型]] — 八來源盤點、選型決策樹、timer 可觀測性
- [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]] — 七道關卡、`%` 截斷、flock、帳號類拒跑、生產級 wrapper
- [[020-02-02-04-svc-systemd-服務自動復原與看門狗]] — Restart 矩陣、StartLimit 算術、watchdog、OnFailure
- [[020-02-02-05-svc-systemd-PM2與systemd整合]] — `PM2_HOME`、四種雙重管理衝突、三種架構選型
- [[020-02-02-99-exam-systemd-總結小考]] — 全章 100 題總複習

**基礎與周邊**

- [[020-01-17-cmd-Linux-systemd服務管理]] — `systemctl` 基本操作與狀態欄位
- [[020-01-18-guide-Linux-排程工作]] — cron 與 timer 的入門語法
- [[020-01-19-guide-Linux-日誌系統]] — journald 持久化、輪替、`journalctl` 進階過濾
- [[020-01-20-guide-Linux-環境變數與設定檔]] — 登入／非登入 shell 的載入順序
- [[020-01-10-cmd-Linux-程序管理與訊號]] — SIGTERM／SIGKILL 與程序樹
- [[020-01-22-guide-Linux-Shell腳本進階]] — `set -euo pipefail`、`trap`、退出碼設計
- [[020-01-23-guide-Linux-Linux常見疑難排解]] — 全機層級的疑難排解；
  另見 [[020-01-28-cmd-Linux-時間同步NTP與chrony]]（時鐘跳躍造成的漏跑）、
  [[020-01-15-cmd-Linux-磁碟分割與掛載]]（fstab 與掛載選項）、
  [[020-01-25-guide-Linux-開機流程與GRUB救援]]（重開機迴圈的脫困）

**相關章節**

- [[090-02-07-guide-防護-SELinux與AppArmor]] — 「手動跑得動、被排程叫就 denied」
- [[100-01-03-guide-日誌-系統監控與告警]] — 把 `NRestarts` 與 `is-system-running` 接進監控
- [[100-01-04-guide-日誌-健康檢查與可用性監控]] — 不要只監控 `is-active`
- [[100-02-08-guide-維運-變更管理流程]]、[[100-02-09-svc-維運-事件處理與升級流程]]、
  [[100-02-10-guide-維運-故障排除方法論]] — 變更程序、事故分級與通用排查思路
- [[060-03-02-03-guide-PM2-程序管理入門]]、[[060-03-02-04-guide-PM2-進階設定與部署]] — PM2 本身
- [[980-02-guide-附錄-常見錯誤訊息對照]] — 跨章節的錯誤訊息索引
