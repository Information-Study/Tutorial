---
title: "cron 排程實務與陷阱"
desc: "格式差一欄、% 沒跳脫、鎖檔卡死、帳號到期：排程「沒跑」或「跑了但沒人知道失敗」的現場鑑識與生產級 wrapper"
aliases: [crontab, "cron.d", flock, "crontab -r", "run-parts"]
tags: [群組/Linux, linux/伺服器, 主題/排程, 主題/cron]
category: 系統服務與排程
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[020-01-18-guide-Linux-排程工作]]", "[[020-01-22-guide-Linux-Shell腳本進階]]"]
updated: 2026-08-28
---

# cron 排程實務與陷阱

> [!abstract] 這篇你會學到
> - 分辨六種 crontab 來源的格式差異，看懂「少寫一欄使用者」為什麼不會報錯、只會安靜地整行不執行
> - 用 `journalctl` + 盤點指令做**現場鑑識**，證明一支排程「其實已經 47 天沒成功過」
> - ★★★★ 把 `>/dev/null 2>&1` 換成 `logger` / 專屬日誌 —— **這一行是機關備份事故延遲三個月才被發現的唯一原因**
> - 用 `flock -n -E` + `timeout` 組出不會重疊、也不會卡死佔鎖的排程，並分辨「被跳過」與「真的失敗」
> - 找出 cron 靜默拒跑的帳號類原因：`cron.allow`、`nologin`、`chage` 到期、家目錄不存在、SELinux
> - 把 crontab 納入變更管理，避免 `crontab -r` 一鍵清空且無法復原
> - 寫出一支可以直接抄走的生產級排程 wrapper：鎖、逾時、日誌、耗時統計、退出碼分類、失敗通報

## 前置知識

這篇假設你已經會下面這些，**不會重講**：

| 你應該已經會 | 在哪一篇 |
| --- | --- |
| cron 五欄語法、`*/15`、`crontab -e/-l` 基本操作 | [[020-01-18-guide-Linux-排程工作]] |
| 四大失敗原因的初階說明（PATH、登入環境、工作目錄、`%`） | [[020-01-18-guide-Linux-排程工作]] |
| `flock -n` 基本用法、`MAILTO`、`CRON_TZ`、anacron 與 `cron.daily` 概念 | [[020-01-18-guide-Linux-排程工作]] |
| `set -euo pipefail`、`trap`、退出碼、`$?` 與 `PIPESTATUS` | [[020-01-22-guide-Linux-Shell腳本進階]] |
| 基本的 shell 變數、重導向、管線 | [[020-01-21-cmd-Linux-Shell腳本入門]] |
| `journalctl -u`、日誌位置與 facility 觀念 | [[020-01-19-guide-Linux-日誌系統]] |
| systemd timer 的能力比較與選型決策 | [[020-02-02-02-cmd-systemd-timer與cron選型]] |

**這篇的定位是「事故現場」。** [[020-01-18-guide-Linux-排程工作]] 教你怎麼把排程寫對；這篇教你**排程寫錯了要怎麼發現**，
以及在機關環境裡真正弄壞過東西的那幾行細節。全篇只圍繞一個主題：

> **排程沒跑，或者跑了但沒人知道它失敗。**

> [!tip] 讀完之後該做的第一件事
> 到你負責的每一台伺服器上跑一次「觀念說明」最後那張盤點指令，
> 把所有 `>/dev/null 2>&1` 的排程列出來。那份清單就是你未來三個月的待辦事項。

---

## 觀念說明

### 一次 cron 執行要通過七道關卡

維運人員最常問的是「排程怎麼沒跑」。但「沒跑」其實是七個完全不同的故障，
每一個都在不同的地方留下（或不留下）痕跡：

```text
   ┌──────────────────────────────────────────────────────────────┐
   │ ① 檔案有沒有被讀進來                                          │
   │    檔名含 `.`／權限不是 644 root／檔尾少一個換行 → 整檔忽略    │
   │    痕跡：syslog 一行 ERROR，之後永遠安靜        ★★★★         │
   ├──────────────────────────────────────────────────────────────┤
   │ ② 這一行的格式對不對                                          │
   │    cron.d 少了使用者欄 → 指令被當成使用者名稱 → 整行不執行     │
   │    痕跡：syslog 一行 bad username                ★★★★         │
   ├──────────────────────────────────────────────────────────────┤
   │ ③ 時間到了沒                                                  │
   │    機器時區／CRON_TZ／NTP 大幅校時／VM 快照還原造成時間跳躍    │
   │    痕跡：幾乎沒有                                ★★★          │
   ├──────────────────────────────────────────────────────────────┤
   │ ④ 這個帳號准不准跑                                            │
   │    cron.allow/deny、shell 是 nologin、chage 到期、沒有家目錄   │
   │    痕跡：syslog 的 PAM 訊息，但 systemctl status 仍是 active   │
   │                                                  ★★★★         │
   ├──────────────────────────────────────────────────────────────┤
   │ ⑤ 有沒有被鎖擋住                                              │
   │    上一輪卡死沒放鎖 → 之後每一輪都被 flock -n 跳過             │
   │    痕跡：你自己有寫才有，沒寫就是完全靜音        ★★★★         │
   ├──────────────────────────────────────────────────────────────┤
   │ ⑥ 指令本身跑得對不對                                          │
   │    PATH／環境／工作目錄／`%` 截斷（見 [[020-01-18-guide-Linux-排程工作]]）         │
   ├──────────────────────────────────────────────────────────────┤
   │ ⑦ 失敗了誰會知道                                              │
   │    `>/dev/null 2>&1` → 沒人知道。MAILTO 但沒 MTA → 沒人知道。 │
   │                                                  ★★★★★        │
   └──────────────────────────────────────────────────────────────┘
```

★★★★ **關卡 ①②④⑤⑦ 的共同特徵是：`systemctl status cron` 永遠顯示 `active (running)`。**
服務是活的，只是你的工作沒跑。所以「服務有起來」完全不能當作「排程有跑」的證據 ——
這是機關稽核時最常見的誤判。

### cron 只記錄「有啟動」，不記錄「結果」

這是本篇一切問題的根源。Debian／Ubuntu 的 cron 預設只記錄工作**開始**：

```bash
sudo journalctl -u cron --since "today" -n 5 --no-pager
```

預期輸出：

```text
Aug 28 02:00:01 srv01 CRON[41233]: (ops) CMD (/home/ops/sync.sh >/dev/null 2>&1)
Aug 28 03:17:01 srv01 CRON[41590]: (root) CMD (cd / && run-parts --report /etc/cron.hourly)
```

★★★★ 這一行 `CMD (...)` 的意思**只有**「cron 在這個時間點 fork 了一個程序去執行這串字」。
它**不代表**：指令存在、指令成功、指令有跑完、指令跑了多久。
腳本第一行就 `command not found` 退出，日誌長得跟成功時**一模一樣**。

Debian／Ubuntu 的 cron 有 `-L <loglevel>` 可以把記錄調到「連結束與失敗都記」，
是一個 bitmask 的加總：

| 值 | 記錄什麼 |
| --- | --- |
| `1` | 所有工作的**開始**（預設值） |
| `2` | 所有工作的**結束** |
| `4` | ★★★ 所有**退出碼非 0** 的工作 |
| `8` | 工作的 process number |

所以 `-L 15` 是「全開」。Ubuntu 24.04 之後 `/etc/default/cron` 已標示為 deprecated，要用 drop-in：

```bash
sudo systemctl edit cron.service
```

在編輯器中填入：

```ini
[Service]
Environment="EXTRA_OPTS=-L 15"
```

```bash
sudo systemctl restart cron
systemctl show cron -p ExecStart --no-pager
```

預期輸出：

```text
ExecStart={ path=/usr/sbin/cron ; argv[]=/usr/sbin/cron -f -P $EXTRA_OPTS ; ... }
```

之後失敗的工作會多出這樣一行：

```text
Aug 28 02:00:03 srv01 CRON[41233]: (ops) CMDEND (/home/ops/sync.sh >/dev/null 2>&1)
Aug 28 02:00:03 srv01 CRON[41233]: (ops) FAILED (exit status 127)
```

> [!warning] `-L 15` 是**輔助**，不是解答
> 它只告訴你「退出碼不是 0」，不會告訴你「為什麼」。真正的錯誤訊息還是在 stderr，
> 而 stderr 被你自己丟進 `/dev/null` 了。★★★★ **記錄是腳本自己的責任**，見下方「輸出處理」。
> 而且開了 `-L 15` 之後 cron 的日誌量會明顯變大，記得配合 [[100-01-02-guide-日誌-日誌集中與輪替]] 調整輪替。

### 六種 crontab 來源與它們的格式差異

★★★★ **這張表是本篇最重要的一張表。**「格式差一欄」是機關環境最常見的排程失效原因，
因為 `/etc/crontab` 與 `/etc/cron.d/*` 多了一個**使用者欄**，而使用者 crontab 沒有。

| # | 來源 | 欄位格式 | 誰執行 | 變更方式 | 星級 |
| --- | --- | --- | --- | --- | --- |
| 1 | `crontab -e`（`/var/spool/cron/crontabs/<user>`） | 五欄 + **指令** | 該使用者 | `crontab` 指令，★★★★ 不要直接編輯檔案 | ★★★ |
| 2 | `/etc/crontab` | 五欄 + **使用者** + 指令 | 指定的使用者 | 直接編輯 | ★★★ |
| 3 | `/etc/cron.d/<name>` | 五欄 + **使用者** + 指令 | 指定的使用者 | 放檔案 | ★★★★ |
| 4 | `/etc/cron.{hourly,daily,weekly,monthly}/` | **可執行腳本**，不是 crontab 格式 | root（由 run-parts） | 放腳本並 `chmod +x` | ★★★ |
| 5 | `/etc/anacrontab` | 四欄：`period delay job-id command` | root | 直接編輯 | ★★ |
| 6 | systemd timer | 完全不是 cron | unit 指定的 `User=` | `systemctl` | ★★★ |

**同一份工作可以同時存在於多個來源，cron 不會幫你去重。**
★★★ 機關常見事故：管理員 A 在使用者 crontab 加了備份，管理員 B 三個月後在 `/etc/cron.d/` 又加一次，
結果每天備份跑兩份，磁碟一個月後爆掉。盤點的時候六個來源都要看。

### 格式寫錯的後果不是報錯，是整行消失

假設你要在 `/etc/cron.d/data-sync` 裡排一支腳本，但**忘了寫使用者欄**：

```cron
# ✗ 這是使用者 crontab 的格式，放在 /etc/cron.d 裡是錯的
0 2 * * * /usr/local/bin/data-sync.sh
```

cron 會把第六欄 `/usr/local/bin/data-sync.sh` 當成**使用者名稱**去查 `/etc/passwd`，查不到就放棄這一行。
在 syslog 留下的痕跡大概是這樣（★★ 訊息文字依 cron 實作與版本略有差異）：

```text
Aug 28 01:59:01 srv01 cron[912]: Error: bad username; while reading /etc/cron.d/data-sync
```

★★★★ **注意這行的時間點**：它出現在 cron **讀取檔案**的時候（存檔後一分鐘內），
不是在排程時間 02:00。所以如果你隔天早上才去 `journalctl --since "02:00"` 找，
你會什麼都找不到 —— 看起來就像「排程時間到了但完全沒動靜」。
這是為什麼很多人查了半天以為是時間設定問題。

正確寫法（六欄）：

```cron
0 2 * * * datasync /usr/local/bin/data-sync.sh
```

> [!danger] ★★★★ 三種讓 `/etc/cron.d/` 整檔被忽略的寫法
> 這三種都**不會**在排程時間留下任何訊息：
>
> ```bash
> # ① 檔名含有 `.`（Debian/Ubuntu 嚴格，見下一節）
> /etc/cron.d/data-sync.cron      # ✗ 整檔忽略
>
> # ② 權限不是 644 或擁有者不是 root
> sudo chmod 664 /etc/cron.d/data-sync    # ✗ syslog: BAD FILE MODE
>
> # ③ 檔尾沒有換行字元
> printf '0 2 * * * datasync /usr/local/bin/data-sync.sh' | sudo tee /etc/cron.d/data-sync
> # ✗ syslog: ERROR (Missing newline before EOF, this crontab file will be ignored)
> ```
>
> ③ 特別陰險，因為用 `cat` 看檔案內容**完全正常**。檢查方式：
>
> ```bash
> tail -c1 /etc/cron.d/data-sync | xxd
> ```
>
> 預期輸出（正確時最後一個位元組是 `0a`）：
>
> ```text
> 00000000: 0a                                       .
> ```
>
> 沒有輸出或不是 `0a` 就是踩到了。用 `printf '...\n'` 或 heredoc 產生檔案就不會有這問題。

### 全機排程盤點（六個來源一次撈）

```bash
sudo tee /usr/local/bin/cron-inventory >/dev/null <<'SCRIPT'
#!/usr/bin/env bash
# 盤點本機所有排程來源；唯讀，安全。
echo "══ 1. 使用者 crontab ══"
while IFS=: read -r u _; do
  c=$(crontab -u "$u" -l 2>/dev/null | grep -vE '^\s*(#|$)') || continue
  [ -n "$c" ] && printf '【%s】\n%s\n' "$u" "$c"
done < /etc/passwd

echo "══ 2. /etc/crontab ══"
grep -vE '^\s*(#|$)' /etc/crontab

echo "══ 3. /etc/cron.d ══"
for f in /etc/cron.d/*; do
  [ -f "$f" ] || continue
  printf '── %s (mode %s owner %s) ──\n' "$f" \
    "$(stat -c '%a' "$f")" "$(stat -c '%U' "$f")"
  grep -vE '^\s*(#|$)' "$f"
done

echo "══ 4. run-parts 目錄（--test 才是可信的驗證）══"
for d in hourly daily weekly monthly; do
  printf '── cron.%s ──\n' "$d"
  run-parts --test "/etc/cron.$d" 2>/dev/null
done

echo "══ 5. anacron ══"
grep -vE '^\s*(#|$)' /etc/anacrontab 2>/dev/null

echo "══ 6. systemd timer ══"
systemctl list-timers --all --no-pager

echo "══ ★★★★ 高風險：把輸出丟掉的排程 ══"
grep -rlE '>\s*/dev/null\s+2>&1|2>&1\s*>\s*/dev/null' \
  /etc/crontab /etc/cron.d/ /var/spool/cron/crontabs/ 2>/dev/null
SCRIPT
sudo chmod 755 /usr/local/bin/cron-inventory
sudo cron-inventory | head -40
```

★★★ 最後那段 grep 撈出來的檔案清單，就是「一旦失敗你永遠不會知道」的排程清單。

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> | 項目 | Ubuntu／Debian | RHEL 系（cronie） |
> | --- | --- | --- |
> | 套件 | `cron` | `cronie` + `crontabs` |
> | 服務名 | `cron.service` | ★★★ `crond.service` |
> | 使用者 crontab 路徑 | `/var/spool/cron/crontabs/` | `/var/spool/cron/` |
> | 日誌 | `journalctl -u cron`、`/var/log/syslog` | `journalctl -u crond`、`/var/log/cron` |
> | `cron.d` 檔名含 `.` | ★★★★ **整檔忽略** | 只忽略開頭是 `.`／`#` 與結尾 `~`、`.rpmsave`、`.rpmorig`、`.rpmnew`；`backup.cron` **會執行** |
> | 變更偵測 | spool 目錄 mtime 輪詢 | inotify（可用 `crond -i` 關閉） |
> | 記錄層級 | `cron -L 15` | 由 `/etc/sysconfig/crond` 的 `CRONDARGS` 控制 |
> | `run-parts` | Debian 版 C 程式，支援 `--test`、`--lsbsysinit` | crontabs 套件的 shell 腳本，規則不同（見下節） |
>
> ★★★★ **跨發行版搬遷排程時，`/etc/cron.d/backup.cron` 在 RHEL 上跑得好好的，
> 搬到 Ubuntu 就整檔失效。** 這是「同一份 Ansible playbook 在兩種 OS 上結果不同」的經典來源。
> 一律用**不含點**的檔名就兩邊都安全。

---

## 基礎操作

### 兩套完全不同的檔名規則，不要混為一談

★★★★ 很多人把「`cron.d` 檔名不能有點」跟「`cron.daily` 腳本不能有 `.sh`」當成同一條規則，
其實它們是**兩個不同程式**的兩套規則，而且在 RHEL 上結論還相反。

| | `/etc/cron.d/*` | `/etc/cron.daily/*` |
| --- | --- | --- |
| 由誰篩選 | **cron 常駐程式本身** | **run-parts** |
| Debian／Ubuntu 規則 | 只允許 `[A-Za-z0-9_-]`，★★★★ 含 `.` 一律忽略 | 同樣只允許 `[A-Za-z0-9_-]`（除非 `--lsbsysinit`） |
| RHEL 系規則 | 只擋開頭 `.`／`#`、結尾 `~`／`.rpm*`；`a.b` 可執行 | 擋 `.rpmsave`、`.rpmorig`、`.rpmnew`、`.swp`、`,v`、`~`、開頭 `.` |
| 還需要什麼 | 檔案 644 / root、檔尾換行 | ★★★ **可執行位元 `chmod 755`** |
| 驗證方式 | 存檔後看 syslog 有沒有 ERROR | ★★★★ `run-parts --test <dir>` |

`run-parts --test` 是**唯一可信**的驗證方式 —— 它印出「真的會被執行」的清單但不執行：

```bash
sudo cp /path/to/cleanup.sh /etc/cron.daily/cleanup.sh
sudo chmod 755 /etc/cron.daily/cleanup.sh
run-parts --test /etc/cron.daily
```

預期輸出（★★★★ 注意 `cleanup.sh` **沒有出現**）：

```text
/etc/cron.daily/apt-compat
/etc/cron.daily/dpkg
/etc/cron.daily/logrotate
```

改名後再測：

```bash
sudo mv /etc/cron.daily/cleanup.sh /etc/cron.daily/cleanup
run-parts --test /etc/cron.daily
```

```text
/etc/cron.daily/apt-compat
/etc/cron.daily/cleanup          # ★ 現在出現了
/etc/cron.daily/dpkg
/etc/cron.daily/logrotate
```

> [!tip] 把 `run-parts --test` 寫進部署腳本的驗收步驟
> 只要你的部署流程有往 `cron.daily` 放東西，部署後就跑一次 `--test` 並 `grep` 你的檔名，
> 撈不到就讓部署失敗。★★★ 這比「上線兩週後發現清理排程從來沒跑過」便宜太多。

### `%` 是換行符號，不是百分比

在 crontab 的**指令欄**裡，`%` 有兩個特殊意義（`man 5 crontab`）：

1. **第一個未跳脫的 `%` 之後的所有內容**，會被當成**標準輸入**餵給指令。
2. 之後的每一個 `%` 都會被轉成**換行字元**。

所以這一行：

```cron
0 3 * * * root tar czf /backup/db-$(date +%F).tar.gz /var/lib/mysql
```

cron 實際執行的是：

```text
指令： tar czf /backup/db-$(date +
stdin： F).tar.gz /var/lib/mysql
```

★★★★ 結果是：`tar` 收到一個叫 `/backup/db-<日期>` 的殘缺參數（`date +` 只印出空字串），
**它甚至可能「成功」建立一個空檔案然後 exit 0**。
沒有錯誤訊息、沒有非零退出碼、監控一片綠燈，直到你要還原那天。

驗證你手上的排程有沒有踩到：

```bash
grep -rnE '[^\\]%' /etc/crontab /etc/cron.d/ /var/spool/cron/crontabs/ 2>/dev/null
```

預期輸出（有踩到時）：

```text
/etc/cron.d/db-backup:3:0 3 * * * root tar czf /backup/db-$(date +%F).tar.gz /var/lib/mysql
```

兩種修法：

```cron
# 修法 A：跳脫（可行，但一段時間後沒人記得為什麼有反斜線）
0 3 * * * root tar czf /backup/db-$(date +\%F).tar.gz /var/lib/mysql

# 修法 B ★★★★ 推薦：crontab 只呼叫腳本，日期、管線、判斷全部寫在腳本裡
0 3 * * * root /usr/local/bin/db-backup.sh
```

> [!danger] 這條規則只在 crontab 裡成立
> 同一行指令貼到終端機跑**完全正常**，這就是它難以自己看出來的原因。
> ★★★★ **判斷準則：只要 crontab 那一行裡出現 `%`、`|`、`&&`、`$(...)`、引號，
> 就該把它搬進腳本。** crontab 的指令欄應該只有「一個絕對路徑加幾個參數」。

### 另一個安靜的殺手：`SHELL=/bin/sh`

`/etc/crontab` 的預設是 `SHELL=/bin/sh`，在 Ubuntu 上 `/bin/sh` 是 **dash**，不是 bash：

```bash
ls -l /bin/sh
```

```text
lrwxrwxrwx 1 root root 4 Mar 31 2026 /bin/sh -> dash
```

★★★ 所以這些 bash 專屬語法在 crontab 指令欄裡會直接失敗：

| 寫法 | 在 dash 的結果 |
| --- | --- |
| `cmd &> /var/log/x.log` | ★★★ dash 不支援 `&>`，會被解析成 `cmd &`（背景執行）加上 `> /var/log/x.log`，行為完全不同 |
| `[[ -f /x ]] && cmd` | `[[: not found` |
| `source /etc/profile` | `source: not found`（要用 `.`） |
| `arr=(a b c)` | 語法錯誤 |

修法一樣是「搬進腳本」，並在腳本第一行寫 `#!/usr/bin/env bash`。
要在 crontab 裡改也可以，但**只影響同一個檔案裡後續的行**：

```cron
SHELL=/bin/bash
0 3 * * * root /usr/local/bin/db-backup.sh
```

### 輸出處理：靜默失敗 vs. 有紀錄

同一支排程的兩個版本，差別只在最後那一小段：

```cron
# ✗✗✗ 版本 A：靜默失敗（★★★★★ 全機關最常見的一行）
0 2 * * * datasync /usr/local/bin/data-sync.sh >/dev/null 2>&1
```

版本 A 的實際後果：腳本裡 `mysql` 密碼過期、NAS 掛載點消失、磁碟滿了 ——
**這三種情況在日誌裡的表現完全相同：什麼都沒有。**

```cron
# ✓ 版本 B：所有輸出進 journal，標上 tag 與 cron.err facility
0 2 * * * datasync /usr/local/bin/data-sync.sh 2>&1 | /usr/bin/logger -t data-sync -p cron.err
```

之後就撈得到了：

```bash
sudo journalctl -t data-sync --since "-1d" --no-pager | tail -5
```

預期輸出：

```text
Aug 28 02:00:01 srv01 data-sync[41233]: [start] pid=41233 host=srv01
Aug 28 02:14:37 srv01 data-sync[41233]: [error] rsync 退出碼 12：無法連線到 nas01:873
Aug 28 02:14:37 srv01 data-sync[41233]: [end] exit=2 duration=876s
```

> [!danger] ★★★★ 版本 B 有一個必須知道的副作用：退出碼被管線吃掉了
> `cmd | logger` 這條管線的退出碼是 **logger 的**（永遠是 0），不是你腳本的。
> 所以：
>
> ```cron
> # ✗ 這個 || 永遠不會觸發，因為 logger 永遠成功
> 0 2 * * * datasync /usr/local/bin/x.sh 2>&1 | logger -t x || /usr/local/bin/alert.sh
> ```
>
> 也代表 cron 的 `-L 15` 記錄到的 `FAILED (exit status N)` 會變成 `exit status 0`。
> **三種正解**：
>
> ```cron
> # ① 最推薦：腳本自己 logger、自己判斷失敗、自己通報。crontab 行保持乾淨
> 0 2 * * * datasync /usr/local/bin/data-sync.sh
>
> # ② 導到專屬 log 檔（不經過管線，退出碼完整保留）
> 0 2 * * * datasync /usr/local/bin/data-sync.sh >> /var/log/data-sync/data-sync.log 2>&1
>
> # ③ 真的要用管線就明確指定 shell 並開 pipefail
> SHELL=/bin/bash
> 0 2 * * * datasync set -o pipefail; /usr/local/bin/data-sync.sh 2>&1 | logger -t data-sync
> ```
>
> 本篇的實戰範例採用 ①：**記錄與通報是腳本的責任，crontab 只負責「什麼時候呼叫誰」。**

用 ② 的話，logrotate 是**必要的**，不是可選的（見 [[100-01-02-guide-日誌-日誌集中與輪替]]）：

```bash
sudo tee /etc/logrotate.d/data-sync >/dev/null <<'EOF'
/var/log/data-sync/*.log {
    daily
    rotate 30
    missingok
    notifempty
    compress
    delaycompress
    create 0640 datasync adm
    su datasync adm
}
EOF
sudo logrotate --debug /etc/logrotate.d/data-sync
```

預期輸出（`--debug` 只模擬不執行）：

```text
rotating pattern: /var/log/data-sync/*.log  after 1 days (30 rotations)
empty log files are not rotated, old logs are removed
considering log /var/log/data-sync/data-sync.log
  Now: 2026-08-28 10:12
  Last rotated at 2026-08-27 00:00
```

★★★ 沒有 logrotate 的排程日誌檔，兩年後會變成一個 40 GB 的檔案，
然後在某個凌晨把根分割區塞爆，連帶讓資料庫停止服務。

### cron 的日誌到底在哪

```bash
# Ubuntu / Debian
sudo journalctl -u cron --since "-2d" --no-pager | tail -20
sudo grep CRON /var/log/syslog | tail -20
```

★★★★ **查不到任何 cron 記錄時，先懷疑 rsyslog 把它濾掉了。**
很多機關的資安強化腳本或集中蒐集設定會為了降噪，把 cron facility 整個丟掉：

```bash
grep -rn -i cron /etc/rsyslog.conf /etc/rsyslog.d/
```

預期輸出（正常的 Ubuntu，`cron.*` 那行是註解掉的）：

```text
/etc/rsyslog.d/50-default.conf:10:#cron.*                       /var/log/cron.log
/etc/rsyslog.d/50-default.conf:33:#       cron,daemon.none;\
```

如果你看到的是下面這種，那就是有人主動把 cron 丟掉了：

```text
/etc/rsyslog.d/49-noise.conf:3::programname, isequal, "CRON" stop
/etc/rsyslog.d/49-noise.conf:4:cron.*  ~
```

★★★ 這時 `/var/log/syslog` 裡什麼都沒有，但 **journald 仍然有**（journald 不受 rsyslog 規則影響），
所以 `journalctl -u cron` 還是撈得到。這也是為什麼本篇一律用 `journalctl` 示範。

要把 cron 分流到自己的檔案（機關稽核常要求）：

```bash
sudo sed -i 's/^#cron\.\*/cron.*/' /etc/rsyslog.d/50-default.conf
sudo systemctl restart rsyslog
sudo tail -f /var/log/cron.log
```

---

## 進階設定與調校

### 重疊執行的完整解法

[[020-01-18-guide-Linux-排程工作]] 已經教過 `flock -n`。這裡談的是**取捨**與**踩得到的坑**。

| 寫法 | 拿不到鎖時的行為 | 適用情境 | 星級 |
| --- | --- | --- | --- |
| `flock -n` | 立刻放棄，退出碼 **1** | ★★★★ 排程預設值：跳過這一輪，下一輪再來 | ★★★★ |
| `flock -w 60` | 等最多 60 秒，逾時退出碼 1 | 執行時間短、稍微錯開就能跑完 | ★★★ |
| `flock`（不加） | ★★★ **無限等待** | 幾乎不該用於 cron：會累積出幾百個等待中的程序把記憶體吃光 | ★★★★ |
| `flock -n -E 75` | 立刻放棄，退出碼 **75** | ★★★★ 可以和「真的失敗」分開的唯一方法 | ★★★★ |

`-E` 是本節的重點：

```bash
flock -n -E 75 /run/lock/data-sync.lock /usr/local/bin/data-sync.sh; echo "exit=$?"
```

第一次執行（拿得到鎖）：

```text
exit=0
```

同時開第二個終端機再跑一次：

```text
exit=75      # ★★★★ 不是 1，可以明確區分「被跳過」與「執行失敗」
```

沒有 `-E` 的話兩者都是 1，監控端無法分辨「今天沒跑，因為上一輪還在跑（正常）」
與「今天跑了，但腳本 exit 1（不正常）」。

> [!warning] `-E` 對 `-w` 逾時同樣生效
> `flock -w 60 -E 75` 的意思是「等 60 秒還拿不到就以 75 離開」。★★ 兩個情境共用同一個退出碼，
> 需要分辨的話就用兩個不同的值（例如 `-n -E 75` 與 `-w 60 -E 76`）。

**鎖檔放哪裡：**

| 位置 | 開機後 | 適用 | 星級 |
| --- | --- | --- | --- |
| `/run/lock/<name>.lock` | ★★★★ tmpfs，**開機自動清空** | 推薦。殘留鎖檔不會跨重開機 | ★★★★ |
| `/var/lock/` | 在現代發行版上是 `/run/lock` 的符號連結 | 等同上者，寫哪個都行 | ★★★ |
| `/tmp/<name>.lock` | 可能被 systemd-tmpfiles 清掉 | ★★★ 別用：`/tmp` 有 sticky bit，任何使用者都能先建立同名檔案佔位 | ★★★★ |
| ★★★★ NFS／CIFS 共用目錄 | 語意不可靠 | **絕對不要**，見下方 | ★★★★ |

★★★★ **鎖檔的權限與擁有者也是攻擊面。** 如果排程用 `datasync` 帳號跑、鎖檔卻在
任何人都能寫的目錄，別的使用者可以先建立一個同名檔案並持有鎖，
你的排程就會**每一輪都被「跳過」**，而且退出碼是 75，監控看起來完全正常。

```bash
sudo install -d -o datasync -g datasync -m 0750 /run/lock/data-sync.d
```

搭配 systemd-tmpfiles 讓它重開機後仍然存在：

```bash
sudo tee /etc/tmpfiles.d/data-sync.conf >/dev/null <<'EOF'
d /run/lock/data-sync.d 0750 datasync datasync -
d /var/log/data-sync    0750 datasync adm       -
EOF
sudo systemd-tmpfiles --create /etc/tmpfiles.d/data-sync.conf
ls -ld /run/lock/data-sync.d
```

預期輸出：

```text
drwxr-x--- 2 datasync datasync 40 Aug 28 10:20 /run/lock/data-sync.d
```

> [!danger] ★★★★ 不要把 flock 的鎖檔放在 NFS／CIFS 上
> 常見錯誤想法：「兩台主機都會跑這支同步，那就把鎖放在共用儲存上，兩台就不會撞。」
>
> 事實（`man 2 flock`）：Linux 2.6.12 之後 NFS client 是把 `flock()` **模擬**成
> 對整個檔案的 fcntl byte-range lock；2.6.37 之後又多了 `local_lock` 掛載選項，
> **可以讓 flock 變成純本機鎖**。於是：
>
> | 情況 | 結果 |
> | --- | --- |
> | 掛載時帶 `-o nolock`（NFSv3 常見）或 `-o local_lock=all` | ★★★★ 兩台主機**各自都拿得到鎖** → 同時對同一份資料寫入 |
> | NFS server 重啟、網路中斷後鎖恢復 | 鎖狀態可能不一致，出現雙重執行的時間窗 |
> | CIFS／SMB 掛載 | 語意隨伺服器實作而異，`nobrl` 選項直接關掉 byte-range lock |
> | 對端是 NAS 廠商自製的 NFS 實作 | ★★★ 行為要自己實測，不能假設 |
>
> **正確做法**：鎖放本機 `/run/lock/`，並在架構層面確保「只有一台主機負責這支排程」
> （用 [[020-02-02-01-svc-systemd-unit撰寫實戰]] 的 unit 部署到單一台，或用資料庫層的 advisory lock）。
> 需要跨主機互斥時，用真正的分散式鎖（DB 的 `GET_LOCK()`、Consul、etcd），不要用檔案。
>
> 檢查你的掛載參數：
>
> ```bash
> findmnt -t nfs,nfs4,cifs -o TARGET,SOURCE,OPTIONS
> ```
>
> ```text
> TARGET     SOURCE              OPTIONS
> /mnt/nas   nas01:/export/data  rw,relatime,vers=4.2,rsize=1048576,local_lock=none
> ```
>
> ★★★ 看到 `local_lock=all`、`local_lock=flock` 或 `nolock` 就代表鎖只在本機有效。

### 逾時保護：沒有 `timeout` 的排程會「從此再也不跑」

這是本篇最值得記住的因果鏈：

```text
① rsync 對到一台掛掉的 NAS，TCP 沒有回應也沒有 RST
        ↓
② rsync 卡在 read() 上，沒有逾時，程序永遠不結束
        ↓
③ 這個程序持有 /run/lock/data-sync.lock
        ↓
④ 之後每一輪 flock -n 都拿不到鎖 → 立刻退出
        ↓
⑤ 外觀：「排程從那天之後再也沒跑過」，而且沒有任何錯誤
        ↓
⑥ 三個月後要還原資料時才發現            ★★★★
```

標準寫法：

```bash
timeout --signal=TERM --kill-after=30s 30m /usr/local/bin/slow-job.sh
echo "exit=$?"
```

| 參數 | 意義 | 星級 |
| --- | --- | --- |
| `--signal=TERM` | 逾時先送 SIGTERM，讓程式有機會清理（收尾、關閉檔案、rollback） | ★★★ |
| `--kill-after=30s` | ★★★★ TERM 之後再等 30 秒仍沒死，補一發 SIGKILL。**沒有這個就可能還是卡住** | ★★★★ |
| `30m` | 逾時長度。★★★ 設成「正常耗時的 2～3 倍」，不是「你希望它多快跑完」 | ★★★ |
| 退出碼 `124` | ★★★★ 代表**逾時被砍**，要和業務失敗分開處理 | ★★★★ |
| `--preserve-status` | 逾時時回傳指令自己的退出碼而不是 124 | ★★ 通常**不要**用，會失去 124 這個訊號 |

驗證它真的會生效：

```bash
timeout --signal=TERM --kill-after=5s 3s sleep 300; echo "exit=$?"
```

預期輸出（大約 3 秒後）：

```text
exit=124
```

> [!tip] ★★★ `timeout` 只砍它直接啟動的那個程序
> 如果你的腳本裡再 fork 出 `rsync`、`mysql`，`timeout` 砍掉腳本後那些子程序**可能還活著**
> （而且還握著資料庫連線）。兩種解法：
> - 腳本裡用 `trap 'kill 0' EXIT` 或 `kill -- -$$` 砍整個 process group；
> - ★★★★ 或者根本改用 systemd timer + `TimeoutStartSec=` —— systemd 用 cgroup 管理，
>   `KillMode=control-group` 會把整棵程序樹一起清掉，這是 cron 做不到的。見 [[020-02-02-02-cmd-systemd-timer與cron選型]]。

實戰範例採用「雙層保護」：外層在 crontab 用 `timeout` 保護整支腳本，
內層在腳本裡對每個高風險指令（rsync、mysql）再各給一個較短的 `timeout`。

### cron 靜默拒跑：權限與帳號類原因

★★★★ 這一類的共同特徵是：**排程根本沒有被啟動，`CMD` 那行完全不會出現**，
但 `systemctl status cron` 還是 `active (running)`。

**① `/etc/cron.allow` 與 `/etc/cron.deny`**

```bash
ls -l /etc/cron.allow /etc/cron.deny 2>&1
```

```text
ls: cannot access '/etc/cron.allow': No such file or directory
-rw-r--r-- 1 root root 0 Aug 10 2026 /etc/cron.deny
```

| 檔案狀態 | 誰可以用 cron |
| --- | --- |
| 兩個都不存在 | 依發行版，Debian 系通常是所有人 |
| `cron.allow` 存在 | ★★★★ **只有清單內的人**，`cron.deny` 完全被忽略 |
| 只有 `cron.deny` | 清單以外的所有人都可以 |

★★★★ 機關導入 TWGCB／CIS 基準時常會建立 `cron.allow` 只放 `root`，
結果原本用服務帳號跑的排程**當晚全部停止**，而且 `crontab -l` 還看得到內容。
新增服務帳號時記得同步：

```bash
echo "datasync" | sudo tee -a /etc/cron.allow
sudo chmod 600 /etc/cron.allow
```

> [!warning] ★★★ `cron.allow` 只擋「使用者 crontab」
> `/etc/cron.d/` 與 `/etc/crontab` 裡指定的使用者**不受 `cron.allow` 限制**
> （因為那是 root 寫的系統排程）。所以「改用 `/etc/cron.d`」順帶解掉這個問題 ——
> 但也代表 `cron.allow` 不是一道完整的防線，稽核時兩邊都要看。

**② 帳號 shell 是 nologin**

```bash
getent passwd datasync
```

```text
datasync:x:997:997::/var/lib/data-sync:/usr/sbin/nologin
```

★★★ cron 執行工作時會用該帳號的 shell（或 crontab 裡的 `SHELL=`）。
`/usr/sbin/nologin` 會直接印出一行訊息然後 exit 1。
服務帳號的正解不是給它 `/bin/bash`，而是在 crontab 檔裡明確指定：

```cron
SHELL=/bin/bash
0 2 * * * datasync /usr/local/bin/data-sync.sh
```

**③ ★★★★ 密碼／帳號到期 —— 機關環境最常見的隱形殺手**

cron 執行前會走 PAM 的 account 階段（`/etc/pam.d/cron`），
`pam_unix` 會檢查 `/etc/shadow` 的到期欄位。只要過期，cron **直接拒跑**：

```bash
sudo chage -l datasync
```

預期輸出（★★★★ 看這兩行）：

```text
Last password change                                    : Feb 12, 2025
Password expires                                        : Aug 11, 2026
Password inactive                                       : never
Account expires                                         : never
Minimum number of days between password change          : 0
Maximum number of days between password change          : 180
Number of days of warning before password expires       : 7
```

`Password expires` 已經過去 → 當天起所有該帳號的排程停止。syslog 會有類似這樣的訊息：

```text
Aug 12 02:00:01 srv01 CRON[41233]: Authentication token is no longer valid; new one required
Aug 12 02:00:01 srv01 CRON[41233]: pam_unix(cron:account): account datasync has expired (account expired)
```

★★★★ **這是機關環境的第一名。** 資安要求「所有帳號 180 天強制換密碼」，
政策一上路，半年後所有服務帳號的排程在同一個週末集體停擺，而且沒有任何人收到通知。

正解：服務帳號**不該有密碼期限**，並且要能證明它不能互動登入：

```bash
# 密碼與帳號都不設到期
sudo chage -M -1 -E -1 datasync
# 鎖住密碼登入（帳號仍可被 cron/systemd 使用）
sudo passwd -l datasync
sudo chage -l datasync | grep -E 'Password expires|Account expires'
```

```text
Password expires                                        : never
Account expires                                         : never
```

> [!warning] ★★★ `passwd -l` 與 PAM 的互動要驗證
> `passwd -l` 是在密碼雜湊前面加 `!`。多數發行版的 `pam_unix` account 階段不會因此拒絕 cron，
> 但**有些強化過的 PAM 設定會**。改完一定要實測：排一個一分鐘後執行的測試排程，
> 確認 `journalctl -t <tag>` 撈得到輸出，不要只看 `chage -l` 就收工。
> 帳號政策的完整說明見 [[020-01-09-cmd-Linux-使用者與群組管理]]。

**④ 家目錄不存在**

cron 會 `chdir()` 到使用者的家目錄。目錄不存在時，Debian 系的 cron 通常仍會執行（退回 `/`），
但腳本裡任何相對路徑、`~/.config`、暫存檔都會爆掉。★★★ 服務帳號一律建家目錄：

```bash
sudo install -d -o datasync -g datasync -m 0750 /var/lib/data-sync
```

**⑤ SELinux / AppArmor 阻擋**

Ubuntu 用 AppArmor，RHEL 系用 SELinux。★★★ 症狀是「同一支腳本手動 `sudo -u datasync` 跑得動，
cron 跑就 Permission denied」。

```bash
# Ubuntu：看有沒有 DENIED
sudo journalctl -k --since "-1h" | grep -i apparmor | tail
sudo aa-status | head -5
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照：用 ausearch 佐證 SELinux 拒絕
> ```bash
> sudo ausearch -m avc -ts recent | tail -20
> ```
> 預期輸出：
> ```text
> type=AVC msg=audit(1756...): avc:  denied  { write } for  pid=4123 comm="data-sync.sh"
>   name="data-sync.lock" dev="tmpfs" ino=1234 scontext=system_u:system_r:system_cronjob_t:s0
>   tcontext=system_u:object_r:var_run_t:s0 tclass=file permissive=0
> ```
> ★★★★ 看到 `scontext=...system_cronjob_t` 就確定是 cron 情境下的 SELinux 拒絕，
> 手動執行時 context 不同所以不會擋。診斷用：
> ```bash
> sudo ausearch -m avc -ts recent | audit2why
> sudo semanage fcontext -a -t var_run_t "/run/lock/data-sync(/.*)?"
> sudo restorecon -Rv /run/lock/data-sync.d
> ```
> ★★★ **不要用 `setenforce 0` 當解法**，那是把整台機器的防護關掉。詳見 [[090-02-07-guide-防護-SELinux與AppArmor]]。

### 時間有三層，要分清楚是哪一層錯

```text
   ┌─────────────────────────────────────────────────┐
   │ 第一層：機器時區    timedatectl                  │
   │   → 決定所有 cron 排程行的基準                    │
   ├─────────────────────────────────────────────────┤
   │ 第二層：crontab 檔案的 CRON_TZ / TZ               │
   │   → ★★★ 只影響「同一個檔案裡、這一行之後」的排程   │
   ├─────────────────────────────────────────────────┤
   │ 第三層：應用程式自己的時區                        │
   │   → PHP date.timezone、MySQL time_zone、          │
   │     Java user.timezone、Laravel config/app.php    │
   │   → ★★★★ 排程在 02:00 跑，但程式算出的「昨天」    │
   │     是 UTC 的昨天 → 報表少一天或多一天            │
   └─────────────────────────────────────────────────┘
```

```bash
timedatectl
```

預期輸出：

```text
               Local time: Fri 2026-08-28 10:31:07 CST
           Universal time: Fri 2026-08-28 02:31:07 UTC
                 Time zone: Asia/Taipei (CST, +0800)     # ★★★ 第一層看這裡
System clock synchronized: yes
              NTP service: active                        # ★★★ 見 [[020-01-28-cmd-Linux-時間同步NTP與chrony]]
```

★★★ `CRON_TZ` 的作用域是**檔案內、宣告之後**：

```cron
# /etc/cron.d/reports
0 1 * * * report /usr/local/bin/local-report.sh      # 用機器時區 CST

CRON_TZ=UTC
0 1 * * * report /usr/local/bin/utc-report.sh        # ★★★ 這行起算才是 UTC
```

在 `/etc/cron.d/reports` 裡設的 `CRON_TZ` **不會**影響 `/etc/cron.d/backup` 或任何使用者 crontab。
★★★★ 反過來說，**改機器時區會讓所有沒宣告 `CRON_TZ` 的排程一起位移**：
把伺服器從 `Asia/Taipei` 改成 `UTC`，原本 02:00 的備份會在台北時間 10:00 執行，
撞上上班尖峰。

**時間跳躍的兩種來源與 cron 的處理規則**（`man 8 cron`，Debian／Ubuntu）：

| 情況 | cron 的行為 | 星級 |
| --- | --- | --- |
| 時間**往前**跳 **小於 3 小時**（例：DST 開始、NTP 小幅校正） | ★★★ 被跳過那段時間內「有指定時分」的工作，會在校時後**盡快補跑一次** | ★★★ |
| 時間**往後**跳 **小於 3 小時**（例：DST 結束） | 落在重複時段裡的工作**不會再跑一次** | ★★★ |
| 跳躍**超過 3 小時** | ★★★★ 視為「時鐘校正」，**不補跑**，直接用新時間繼續 | ★★★★ |
| 分／時欄位是 `*` 的工作 | 不受上述規則影響，一律照新時間跑 | ★★ |

★★★★ 「超過 3 小時不補跑」這條規則在兩個場景會咬人：

1. **虛擬機從快照還原／暫停後恢復**：VM 睡了一整晚，恢復後時間直接跳到現在，
   中間所有排程**全部消失**，不會補。這是「測試機還原快照後備份就再也沒跑」的原因。
2. **新機器第一次 NTP 校時**：BIOS 時間差了兩天，chrony 一口氣校正回來 → 中間排程全消失。

```bash
# 看時間有沒有被大幅校正過
sudo journalctl -u chrony --since "-7d" | grep -iE 'step|slew|System clock'
```

預期輸出：

```text
Aug 21 03:14:52 srv01 chronyd[701]: System clock wrong by 7412.339 seconds, adjustment started
Aug 21 05:18:24 srv01 chronyd[701]: System clock was stepped by 7412.339 seconds
```

★★★★ 看到 `stepped by` 而且數字大於 10800（3 小時），就知道那一天的排程有一批沒跑，
而且 cron 不會補。要能補跑就得改用 systemd timer 的 `Persistent=true`（見 [[020-02-02-02-cmd-systemd-timer與cron選型]]）
或 anacron。

> [!warning] ★★★ 台灣沒有 DST，但你還是會遇到
> 雲端主機預設是 UTC（沒有 DST，反而安全）；但海外分支、跨國 VPN 對端、
> AWS 上跑 `America/New_York` 的機器，每年會出現兩次「02:30 的排程沒跑」或「跑了兩次」。
> **判斷準則：任何跨時區的排程，一律把機器與 crontab 都設 UTC，只在報表輸出時才轉當地時間。**

### `@reboot` 為什麼不能當作「開機後執行」

`@reboot` 的執行時機是 **cron 服務啟動的那一刻**，不是「系統完全就緒」。

```bash
systemctl show cron -p After --no-pager
```

預期輸出：

```text
After=remote-fs.target nss-user-lookup.target sysinit.target basic.target system.slice
```

★★★★ 注意這裡**沒有** `network-online.target`、`mysql.service`、`nfs-client.target`。
所以 `@reboot` 執行時，下面這些都**不保證**已經就緒：

| 你以為已經好了 | 實際狀況 |
| --- | --- |
| 網路 | ★★★★ 介面可能剛 up，DHCP 還沒拿到 IP，DNS 還不能解析 |
| NFS 掛載 | ★★★★ 掛載點可能還是空目錄 → 腳本對空目錄做 rsync `--delete` → **刪光遠端資料** |
| 資料庫 | MySQL/PostgreSQL 可能還在做 crash recovery |
| 其他服務 | 完全沒有相依關係可以宣告 |

而且 `@reboot` 的支援度依實作而異：Debian cron 與 cronie 都支援，但容器映像裡常見的
BusyBox cron **不支援**；`crontab -l` 看得到那一行，它就是不會執行。

★★★★ **正式環境的正解是 systemd unit**，因為它可以宣告相依：

```ini
[Unit]
Description=Data sync bootstrap
After=network-online.target mnt-nas.mount mariadb.service
Wants=network-online.target
Requires=mnt-nas.mount

[Service]
Type=oneshot
User=datasync
ExecStart=/usr/local/bin/data-sync.sh

[Install]
WantedBy=multi-user.target
```

完整的 unit 撰寫方式（包含 `Requires` 與 `After` 的差別、`Type=` 的選擇）見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]；
「這種情況該不該整支改用 timer」的決策表見 [[020-02-02-02-cmd-systemd-timer與cron選型]]。

### crontab 的變更管理

> [!danger] ★★★★★ `crontab -r` 沒有二次確認，而且沒有任何備份
> ```bash
> crontab -r
> ```
> 執行後**沒有輸出、沒有確認、沒有回收桶**。該使用者的所有排程立刻消失。
> `-r` 和 `-e` 在鍵盤上相鄰，`-l` 也只差一個字。
> 更糟的是 `sudo crontab -r -u root` —— 整台機器的 root 排程一次清空。
>
> **這是本篇唯一的 ★★★★★，因為它同時滿足：不可逆、無警告、無痕跡、影響全部。**

四層防護，建議全做：

**① 用 `-i` 讓 `-r` 需要確認（vixie cron 的 `crontab -i`）**

```bash
# 加到 /etc/profile.d/，全機生效
echo "alias crontab='crontab -i'" | sudo tee /etc/profile.d/crontab-safe.sh
```

之後：

```bash
crontab -r
```

```text
crontab: really delete ops's crontab? (y/n)
```

★★★ **alias 只在互動式 shell 生效**，透過 `sudo crontab -r`、腳本、Ansible 呼叫時**完全沒用**。
所以它是最低限度的防護，不是解答。

**② 每天備份所有使用者的 crontab**

```bash
sudo tee /etc/cron.d/crontab-backup >/dev/null <<'EOF'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# ★★★ 每天 00:30 備份所有 crontab，保留 90 天
30 0 * * * root /usr/local/bin/crontab-backup.sh
EOF

sudo tee /usr/local/bin/crontab-backup.sh >/dev/null <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
DEST="/var/backups/crontab/$(date +%Y-%m-%d)"
install -d -m 0700 "$DEST"
while IFS=: read -r u _; do
  crontab -u "$u" -l >"$DEST/user-$u.cron" 2>/dev/null || rm -f "$DEST/user-$u.cron"
done < /etc/passwd
cp -a /etc/crontab "$DEST/etc-crontab"
cp -a /etc/cron.d "$DEST/etc-cron.d"
find /var/backups/crontab -maxdepth 1 -type d -mtime +90 -exec rm -rf {} +
logger -t crontab-backup -p cron.info "備份完成：$DEST"
SCRIPT
sudo chmod 700 /usr/local/bin/crontab-backup.sh
sudo /usr/local/bin/crontab-backup.sh && ls /var/backups/crontab/
```

預期輸出：

```text
2026-08-28
```

**③ ★★★★ 根本解：使用者 crontab 保持空的，全部改用 `/etc/cron.d/` + 版本庫**

```bash
# 排程檔跟著設定管理走，部署時複製過去
sudo install -o root -g root -m 0644 \
     /srv/ops-config/cron.d/data-sync /etc/cron.d/data-sync
```

好處：可以 code review、有 git 歷史、`crontab -r` 動不到、跟著 `/etc` 一起備份、
`grep -r` 一次看完全機排程。

**④ 一定要用使用者 crontab 時，用檔案部署而不是 `crontab -e`**

```bash
crontab -l > /tmp/ops.cron.bak        # ★★★★ 動手前先備份
cp /tmp/ops.cron.bak /tmp/ops.cron
vim /tmp/ops.cron
crontab /tmp/ops.cron                 # 整份取代，語法錯會拒絕安裝
crontab -l                            # 確認
```

語法有誤時：

```text
"/tmp/ops.cron":3: bad minute
errors in crontab file, can't install.
```

★★★ **注意 `crontab <file>` 是「整份取代」不是「附加」** —— 檔案裡沒有的排程就會消失。

> [!danger] ★★★★ 直接編輯 `/var/spool/cron/crontabs/<user>` 不一定會被載入
> Debian／Ubuntu 的 cron 是靠 **spool 目錄的 mtime** 判斷「有沒有人改過」，
> 目錄 mtime 變了才會去逐一檢查各檔案的 mtime。
>
> ```bash
> # ✗ append 只改到檔案 mtime，目錄 mtime 沒變 → cron 不會重新載入
> echo '*/5 * * * * /usr/local/bin/x.sh' | sudo tee -a /var/spool/cron/crontabs/ops
> ```
>
> 結果是：`crontab -l` 看得到新排程，但它**永遠不會執行**，
> 直到下次有人用 `crontab` 指令改了任何一個使用者的排程、或 cron 重啟為止。
> 這種「看得到、不會跑」的狀態是最難查的一種。
>
> 硬要直接改的話至少補一下目錄 mtime：
>
> ```bash
> sudo touch /var/spool/cron/crontabs
> ```
>
> ★★★ 但正解永遠是 `crontab <file>`。RHEL 系的 cronie 用 inotify，沒有這個問題 ——
> **這也是「同一套自動化腳本在 RHEL 正常、在 Ubuntu 失效」的另一個來源。**

---

## 完整實戰範例

### 情境

某機關的資料交換伺服器上有一行排程，是三年前離職的同仁留下的：

```cron
0 2 * * * /home/ops/sync.sh >/dev/null 2>&1
```

它每天凌晨 2 點從 NAS 同步一批資料，再匯入 MariaDB 給前台查詢系統用。
今天前台反映「查不到最近的資料」。我們要做的是：**先鑑識，再改造，最後留下可回滾的紀錄。**

### ① 現場鑑識：證明它已經 47 天沒成功

**【鑑識 1】確認排程本身還在，而且 cron 有啟動它**

```bash
sudo crontab -l -u ops
sudo journalctl -u cron --since "-3d" | grep -c 'sync.sh'
```

預期輸出：

```text
0 2 * * * /home/ops/sync.sh >/dev/null 2>&1
3
```

★★★★ 三天有三筆 `CMD` 記錄 —— **cron 確實有啟動它**。
到這裡很多人會下結論「排程有跑，是程式的問題」，然後把問題丟給開發。
但 `CMD` 只代表「有 fork」，不代表跑完，更不代表成功。

**【鑑識 2】看資料本身的時間戳（唯一可信的證據）**

```bash
stat -c '%y  %n' /var/lib/appdb/last_import
mysql -N -B appdb -e "SELECT MAX(imported_at) FROM import_log;"
find /mnt/nas/export -maxdepth 1 -type f -printf '%TY-%Tm-%Td %p\n' | sort | tail -3
```

預期輸出：

```text
2026-07-12 02:14:38.221 +0800  /var/lib/appdb/last_import
2026-07-12 02:14:38
2026-08-28 01:03:11 /mnt/nas/export/batch-20260828.csv
```

★★★★ **來源檔案一直在更新（8/28），但最後一次成功匯入是 7/12 —— 已經 47 天。**
排程每天都被啟動，每天都失敗，每天都沒有人知道。

**【鑑識 3】手動重現，把被丟掉的錯誤訊息找回來**

```bash
sudo -u ops -H /home/ops/sync.sh; echo "exit=$?"
```

預期輸出：

```text
rsync: [Receiver] failed to connect to nas01 (10.20.1.8): Connection timed out (110)
rsync error: error in socket IO (code 10) at clientserver.c(139)
exit=10
```

真相：7/12 那天 NAS 換了新的 IP，`sync.sh` 裡寫死的主機名沒跟著改。
★★★★ **這個錯誤訊息 47 天來每天都產生了一次，每天都被 `>/dev/null 2>&1` 丟掉。**

**【鑑識 4】檢查有沒有卡死的舊程序與殘留鎖**

```bash
pgrep -af 'sync.sh|rsync' || echo "沒有殘留程序"
ls -l /var/lock/*.lock /run/lock/*.lock 2>/dev/null || echo "沒有殘留鎖檔"
```

```text
沒有殘留程序
沒有殘留鎖檔
```

★★★ 這次沒有卡死（rsync 自己逾時了），但**原本的腳本根本沒有鎖也沒有逾時** ——
只要哪天 NAS 是「連得上但不回應」，它就會永遠卡住。這是下一次事故。

### ② 建立服務帳號與目錄

```bash
# 專屬服務帳號，不能互動登入，密碼與帳號都不設到期 ★★★★
sudo useradd --system --shell /usr/sbin/nologin \
     --home-dir /var/lib/data-sync --create-home datasync
sudo chage -M -1 -E -1 datasync
sudo passwd -l datasync

# 目錄（重開機後由 tmpfiles 重建 /run 底下的部分）
sudo install -d -o datasync -g datasync -m 0750 /var/lib/data-sync/work
sudo install -d -o datasync -g adm      -m 0750 /var/log/data-sync

sudo tee /etc/tmpfiles.d/data-sync.conf >/dev/null <<'EOF'
d /run/lock/data-sync.d 0750 datasync datasync -
d /var/log/data-sync    0750 datasync adm       -
EOF
sudo systemd-tmpfiles --create /etc/tmpfiles.d/data-sync.conf

# 讓服務帳號能用資料庫（密碼放在只有它讀得到的檔案，不進版本庫）★★★★
sudo install -o datasync -g datasync -m 0600 /dev/null /var/lib/data-sync/.my.cnf
sudo tee /var/lib/data-sync/.my.cnf >/dev/null <<'EOF'
[client]
user=datasync
password=請改成實際密碼
host=127.0.0.1
EOF
sudo chown datasync:datasync /var/lib/data-sync/.my.cnf
sudo chmod 600 /var/lib/data-sync/.my.cnf

sudo chage -l datasync | grep -E 'Password expires|Account expires'
```

預期輸出：

```text
Password expires                                        : never
Account expires                                         : never
```

### ③ 生產級腳本 `/usr/local/bin/data-sync.sh`

```bash
sudo tee /usr/local/bin/data-sync.sh >/dev/null <<'SCRIPT'
#!/usr/bin/env bash
#
# data-sync.sh — 從 NAS 同步資料並匯入 MariaDB（生產級排程 wrapper）
#
# 退出碼約定（★★★★ 監控端依這個分類決定要不要叫人起床）
#   0   成功
#   1   業務失敗：資料本身有問題，需要人工判斷
#   2   環境失敗：來源不可達、磁碟不足、相依指令缺少 → 要通報
#   75  暫時性／被跳過：上一輪還在跑，或對端暫時忙碌 → 不通報，但連三次要通報
#   124 逾時被 timeout 砍掉 → 一定要通報
#
set -euo pipefail

# ── 設定（唯一需要修改的區塊）─────────────────────────────
readonly TAG="data-sync"
readonly SRC="rsync://nas01.example.gov.tw/export/"
readonly WORK="/var/lib/data-sync/work"
readonly LOCK_DIR="/run/lock/data-sync.d"
readonly LOCK_FILE="${LOCK_DIR}/${TAG}.lock"
readonly FAIL_FLAG="/run/${TAG}.fail"
readonly LOG_FILE="/var/log/data-sync/${TAG}.log"
readonly DB="appdb"
readonly ALERT_URL="${DATA_SYNC_ALERT_URL:-https://alert.example.gov.tw/hooks/data-sync}"
readonly RSYNC_TIMEOUT="20m"     # 內層保護：單一指令
readonly MYSQL_TIMEOUT="15m"
# ★★★ cron 那一行的外層 timeout 必須大於這兩者的總和
# ─────────────────────────────────────────────────────────

# ★★★★ cron 不讀 .bashrc，PATH 必須自己給（Ubuntu 24.04+ 的 cron -P 會繼承 systemd 的 PATH，
# 但不要依賴那個行為，跨機器就不成立）
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C.UTF-8
export HOME="${HOME:-/var/lib/data-sync}"

readonly START_TS=$(date +%s)
EXIT_CODE=1
TMP_DIR=""

# ── 記錄：同時進 journal 與專屬日誌檔 ─────────────────────
log() {
  local level="$1"; shift
  local msg="[$level] $*"
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$msg" >>"$LOG_FILE" 2>/dev/null || true
  logger -t "$TAG" -p "cron.${level}" -- "$msg" 2>/dev/null || true
}
info() { log info "$@"; }
warn() { log warning "$@"; }
err()  { log err "$@"; }

die() {  # die <退出碼> <訊息>
  EXIT_CODE="$1"; shift
  err "$*"
  exit "$EXIT_CODE"
}

# ── 收尾：無論怎麼結束都會執行 ★★★★ ─────────────────────
on_exit() {
  local rc=$?
  [ "$rc" -ne 0 ] && EXIT_CODE="$rc"
  local dur=$(( $(date +%s) - START_TS ))

  # 清暫存（鎖由 fd 關閉時自動釋放，不需要也不應該手動 rm 鎖檔）
  [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ] && rm -rf -- "$TMP_DIR"

  case "$EXIT_CODE" in
    0)   info "[end] exit=0 duration=${dur}s"; rm -f -- "$FAIL_FLAG" ;;
    75)  info "[end] exit=75 duration=${dur}s 已被跳過或暫時性失敗" ;;
    124) err  "[end] exit=124 duration=${dur}s ★★★★ 逾時被強制中止"; notify "逾時 ${dur}s" ;;
    *)   err  "[end] exit=${EXIT_CODE} duration=${dur}s"; notify "退出碼 ${EXIT_CODE}" ;;
  esac
  exit "$EXIT_CODE"
}
trap on_exit EXIT

# ── 通報：寫旗標檔給監控撿 + 打 webhook ───────────────────
notify() {
  local reason="$1"
  # 旗標檔：即使 webhook 打不出去，Zabbix/Nagios 也撿得到 ★★★★
  printf '%s exit=%s reason=%s host=%s\n' \
    "$(date -Is)" "$EXIT_CODE" "$reason" "$(hostname -s)" >"$FAIL_FLAG" 2>/dev/null || true
  # ★★★ --max-time 是必要的：通報端點掛掉不可以拖垮排程
  curl -fsS --max-time 15 --retry 2 --retry-delay 3 \
       -H 'Content-Type: application/json' \
       -d "{\"host\":\"$(hostname -s)\",\"job\":\"${TAG}\",\"exit\":${EXIT_CODE},\"reason\":\"${reason}\"}" \
       "$ALERT_URL" >/dev/null 2>&1 \
    || warn "通報端點無回應，已寫入旗標檔 ${FAIL_FLAG}"
}

# ── 取鎖：拿不到就以 75 離開，和真正的失敗區分開 ★★★★ ───
acquire_lock() {
  install -d -m 0750 "$LOCK_DIR" 2>/dev/null || true
  exec 9>"$LOCK_FILE" || die 2 "無法建立鎖檔 ${LOCK_FILE}"
  if ! flock -n 9; then
    local holder
    holder=$(ss -p 2>/dev/null | true; fuser "$LOCK_FILE" 2>/dev/null || echo "未知")
    EXIT_CODE=75
    info "[skip] 另一份實例仍在執行（持有者 pid: ${holder}），本輪跳過"
    exit 75
  fi
  info "[start] pid=$$ host=$(hostname -s) user=$(id -un)"
}

# ── 前置檢查：把「環境問題」在做事之前就擋下來 ────────────
preflight() {
  local cmd
  for cmd in rsync mysql curl flock timeout logger; do
    command -v "$cmd" >/dev/null 2>&1 || die 2 "缺少必要指令：${cmd}"
  done
  [ -d "$WORK" ] || die 2 "工作目錄不存在：${WORK}"
  [ -w "$WORK" ] || die 2 "工作目錄不可寫：${WORK}"

  # 磁碟空間：低於 2 GB 就不要開始 ★★★
  local avail_mb
  avail_mb=$(df -Pm "$WORK" | awk 'NR==2 {print $4}')
  [ "$avail_mb" -ge 2048 ] || die 2 "磁碟空間不足：${avail_mb}MB < 2048MB"

  # 資料庫連得上嗎（10 秒內要有回應）
  timeout 10s mysql --defaults-file=/var/lib/data-sync/.my.cnf \
      -N -B "$DB" -e "SELECT 1;" >/dev/null 2>&1 \
    || die 2 "資料庫 ${DB} 無法連線"

  info "前置檢查通過（可用空間 ${avail_mb}MB）"
}

# ── 同步：內層 timeout，退出碼分類 ────────────────────────
sync_files() {
  TMP_DIR=$(mktemp -d "${WORK}/.stage.XXXXXX")
  info "開始同步 ${SRC} → ${TMP_DIR}"

  local rc=0
  timeout --signal=TERM --kill-after=30s "$RSYNC_TIMEOUT" \
    rsync -a --no-motd --contimeout=30 --timeout=120 \
          --exclude='*.tmp' "$SRC" "$TMP_DIR/" >>"$LOG_FILE" 2>&1 || rc=$?

  case "$rc" in
    0)  : ;;
    124) die 124 "rsync 逾時（超過 ${RSYNC_TIMEOUT}），對端可能無回應" ;;
    10|12|30|35) die 2 "rsync 連線類錯誤（退出碼 ${rc}）：對端不可達或逾時" ;;
    23|24) warn "rsync 部分檔案未傳輸（退出碼 ${rc}），繼續處理已取得的部分" ;;
    *)  die 1 "rsync 失敗，退出碼 ${rc}" ;;
  esac

  local n
  n=$(find "$TMP_DIR" -type f -name '*.csv' | wc -l)
  [ "$n" -gt 0 ] || die 1 "同步完成但沒有任何 CSV 檔，來源可能已變更"
  info "同步完成，取得 ${n} 個檔案"
}

# ── 匯入：先進暫存表再交換，失敗不會留下半套資料 ★★★★ ───
import_db() {
  local f rc=0
  for f in "$TMP_DIR"/*.csv; do
    [ -e "$f" ] || continue
    info "匯入 $(basename "$f")"
    rc=0
    timeout --signal=TERM --kill-after=30s "$MYSQL_TIMEOUT" \
      mysql --defaults-file=/var/lib/data-sync/.my.cnf "$DB" <<SQL >>"$LOG_FILE" 2>&1 || rc=$?
START TRANSACTION;
CREATE TEMPORARY TABLE staging LIKE records;
LOAD DATA LOCAL INFILE '${f}' INTO TABLE staging
  FIELDS TERMINATED BY ',' ENCLOSED BY '"' IGNORE 1 LINES;
REPLACE INTO records SELECT * FROM staging;
INSERT INTO import_log (source_file, row_count, imported_at)
  SELECT '$(basename "$f")', COUNT(*), NOW() FROM staging;
COMMIT;
SQL
    case "$rc" in
      0)  : ;;
      124) die 124 "資料庫匯入逾時（超過 ${MYSQL_TIMEOUT}），可能有鎖等待" ;;
      *)  die 1 "匯入 $(basename "$f") 失敗，退出碼 ${rc}" ;;
    esac
  done
}

# ── 驗證：確認結果真的正確，不要只看退出碼 ★★★★ ─────────
verify() {
  local last
  last=$(mysql --defaults-file=/var/lib/data-sync/.my.cnf -N -B "$DB" \
           -e "SELECT COALESCE(MAX(imported_at),'1970-01-01') FROM import_log;")
  local age=$(( $(date +%s) - $(date -d "$last" +%s) ))
  [ "$age" -lt 3600 ] || die 1 "驗證失敗：最新匯入時間 ${last} 距今 ${age}s，資料未更新"
  date -Is >"${WORK}/../last_import"
  info "驗證通過，最新匯入時間 ${last}"
}

main() {
  acquire_lock
  preflight
  sync_files
  import_db
  verify
  EXIT_CODE=0
}
main "$@"
SCRIPT

sudo chown root:root /usr/local/bin/data-sync.sh
sudo chmod 755 /usr/local/bin/data-sync.sh
sudo bash -n /usr/local/bin/data-sync.sh && echo "語法檢查通過"
```

預期輸出：

```text
語法檢查通過
```

> [!warning] 未實機驗證
> 上面腳本裡的 `rsync://nas01...`、`appdb` 資料表結構與 `ALERT_URL` 是示範用的佔位值。
> ★★★ `LOAD DATA LOCAL INFILE` 需要伺服器端 `local_infile=1`，而且在多數機關的資安基準中是**關閉**的；
> 實際導入時請改用 `mariadb-import` 或應用層匯入，並依你的資料表結構調整 SQL。
> 腳本的**框架**（鎖、逾時、記錄、退出碼分類、通報、驗證、trap）是可以直接沿用的部分。

### ④ 部署 crontab 與 logrotate

```bash
# ★★★★ 六欄格式、專屬帳號、外層 timeout（45m > 20m + 15m）、不重導向輸出
sudo tee /etc/cron.d/data-sync >/dev/null <<'EOF'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
MAILTO=""
# 分 時 日 月 週 使用者 指令
0 2 * * *   datasync   /usr/bin/timeout --signal=TERM --kill-after=30s 45m /usr/local/bin/data-sync.sh
EOF
sudo chown root:root /etc/cron.d/data-sync
sudo chmod 644 /etc/cron.d/data-sync

# ★★★★ 檔尾換行檢查
tail -c1 /etc/cron.d/data-sync | xxd

sudo tee /etc/logrotate.d/data-sync >/dev/null <<'EOF'
/var/log/data-sync/*.log {
    daily
    rotate 30
    missingok
    notifempty
    compress
    delaycompress
    create 0640 datasync adm
    su datasync adm
}
EOF
sudo logrotate --debug /etc/logrotate.d/data-sync >/dev/null && echo "logrotate 設定正確"
```

預期輸出：

```text
00000000: 0a                                       .
logrotate 設定正確
```

### ⑤ 驗收檢查表

★★★★ **每一項都要真的跑過並看到預期結果**，不是「看起來應該沒問題」。

| # | 檢查項 | 指令 | 預期結果 |
| --- | --- | --- | --- |
| 1 | cron 有讀進這個檔 | `sudo journalctl -u cron --since "-5min" \| grep -i 'error\|bad\|orphan'` | ★★★★ **沒有任何輸出** |
| 2 | 六欄格式正確 | `awk 'NF && $1!~/^#/ && $1!~/=/ {print NF" 欄: "$0}' /etc/cron.d/data-sync` | 欄數 ≥ 7（五欄+使用者+指令） |
| 3 | 檔案權限正確 | `stat -c '%a %U:%G %n' /etc/cron.d/data-sync` | `644 root:root /etc/cron.d/data-sync` |
| 4 | 檔尾有換行 | `tail -c1 /etc/cron.d/data-sync \| xxd` | `00000000: 0a` |
| 5 | 帳號沒到期 | `sudo chage -l datasync \| grep -E 'expires'` | 兩行都是 `never` |
| 6 | 帳號准跑 cron | `grep -c datasync /etc/cron.allow 2>/dev/null \|\| echo "無 allow 檔"` | `1` 或「無 allow 檔」 |
| 7 | ★★★★ 手動跑得起來 | `sudo -u datasync -H /usr/local/bin/data-sync.sh; echo $?` | `0`，且 `/var/log/data-sync/` 有內容 |
| 8 | ★★★★ 鎖真的有效 | 兩個終端機同時跑上一行 | 第二個立刻結束、`echo $?` 得到 **75** |
| 9 | ★★★★ 逾時真的有效 | `sudo iptables -I OUTPUT -d <NAS_IP> -j DROP` 後手動執行 | 20 分鐘後 exit **124**，journal 有「逾時被強制中止」 |
| 10 | ★★★★ 通報真的有到 | `sudo -u datasync bash -c 'EXIT_CODE=1; ...'` 或暫時把 `verify()` 改成 `die 1 test` | 收到 webhook，且 `/run/data-sync.fail` 存在 |
| 11 | 旗標檔會被清掉 | 修回正常後再跑一次 | `ls /run/data-sync.fail` → No such file |
| 12 | journal 撈得到 tag | `sudo journalctl -t data-sync --since "-10min" --no-pager` | 看得到 `[start]` 與 `[end] exit=0 duration=...` |
| 13 | 日誌會輪替 | `sudo logrotate -f /etc/logrotate.d/data-sync; ls /var/log/data-sync/` | 出現 `data-sync.log.1` |
| 14 | 監控撿得到旗標 | 在監控端設「`/run/data-sync.fail` 存在」或「24h 內無 `exit=0`」告警 | 觸發測試告警成功 |

第 9 項恢復環境：

```bash
sudo iptables -D OUTPUT -d <NAS_IP> -j DROP
```

### ⑥ 回滾

★★★ 任何變更都要先想好怎麼退回去。這次的回滾只有四步：

```bash
# 1. 移除新排程
sudo rm -f /etc/cron.d/data-sync

# 2. 還原原本的使用者 crontab（步驟 ① 之前已備份）
sudo crontab -u ops /var/backups/crontab/2026-08-28/user-ops.cron
sudo crontab -l -u ops

# 3. 確認沒有殘留的鎖與旗標（★★★ 忘了清旗標，監控會一直紅燈）
sudo rm -f /run/data-sync.fail
sudo fuser -v /run/lock/data-sync.d/data-sync.lock 2>&1 || echo "沒有程序持有鎖"
sudo rm -f /run/lock/data-sync.d/data-sync.lock

# 4. 確認沒有卡住的舊程序
pgrep -af 'data-sync.sh|rsync' || echo "沒有殘留程序"
```

預期輸出：

```text
0 2 * * * /home/ops/sync.sh >/dev/null 2>&1
沒有程序持有鎖
沒有殘留程序
```

★★★ 服務帳號 `datasync`、腳本與 logrotate 設定可以留著不刪（它們沒有被任何排程呼叫就不會執行），
下次要重新啟用只要把 `/etc/cron.d/data-sync` 放回去。真的要清乾淨才 `userdel -r datasync`。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `crontab -r` 之後所有排程消失，無法復原 | `-r` 無二次確認、無備份 | 從 `/var/backups/crontab/` 還原；長期改用 `/etc/cron.d` + 版本庫，並加 `alias crontab='crontab -i'` |
| ★★★★ `/etc/cron.d/x` 的排程完全沒動靜，syslog 只有一行 `bad username` | 寫成使用者 crontab 格式，**少了使用者欄** | 補上使用者欄（五欄+使用者+指令）；用驗收表第 2 項的 `awk` 檢查欄數 |
| ★★★★ 排程時間到了完全沒反應，`journalctl --since "02:00"` 什麼都沒有 | 檔案在**載入階段**就被拒絕（檔名含 `.`、mode 不是 644、檔尾少換行） | 存檔後一分鐘內看 `journalctl -u cron`；檢查 `tail -c1 \| xxd` 是否為 `0a` |
| ★★★★ 備份檔是 0 byte 或檔名怪異，但排程「成功」 | crontab 指令欄的 `%` 未跳脫，指令從 `%` 之後被截斷 | 改 `\%`，更好的是把整段搬進腳本；用 `grep -rnE '[^\\]%'` 全機掃 |
| ★★★★ 備份連續失敗三個月才被發現 | `>/dev/null 2>&1` 丟掉所有 stderr | 改用 `logger -t <tag> -p cron.err` 或專屬 log 檔；腳本自己記錄並通報 |
| ★★★★ 排程「從某天起再也沒跑過」，無任何錯誤 | 上一輪卡死（NAS 無回應／DB 鎖）持有 flock，之後每輪被 `-n` 跳過 | `fuser <lock>` 找出持有者並砍掉；補上 `timeout --kill-after` 並處理退出碼 124 |
| ★★★★ 半年後所有服務帳號排程同時停擺 | 密碼／帳號到期政策生效，PAM account 檢查失敗 | `chage -M -1 -E -1 <user>`；syslog 找 `account has expired` / `Authentication token is no longer valid` |
| ★★★★ 兩台主機同時對同一份資料寫入，互相覆蓋 | flock 的鎖檔放在 NFS/CIFS 上，`local_lock`／`nolock` 讓鎖只在本機有效 | 鎖一律放本機 `/run/lock/`；跨主機互斥改用 DB advisory lock 或架構上只讓一台跑 |
| ★★★★ `@reboot` 的同步腳本把遠端資料刪光 | 執行時 NFS 尚未掛載，對空目錄做 `rsync --delete` | 改用 systemd unit 宣告 `Requires=mnt-nas.mount`、`After=network-online.target` |
| ★★★ 導入 TWGCB 基準當晚所有使用者排程停止 | 新建的 `/etc/cron.allow` 沒有列入服務帳號，且它一存在 `cron.deny` 就失效 | 把服務帳號加進 `cron.allow`，或把排程搬到不受限的 `/etc/cron.d` |
| ★★★ `crontab -l` 看得到新排程但永遠不執行 | 直接 `>>` 附加到 `/var/spool/cron/crontabs/<user>`，spool 目錄 mtime 沒變、cron 不重載 | 用 `crontab <file>` 部署；急救可 `touch /var/spool/cron/crontabs` |
| ★★★ `cron.daily/cleanup.sh` 從來沒執行過 | run-parts 忽略含 `.` 的檔名（Debian）／沒有可執行位元 | 改名為 `cleanup`、`chmod 755`，用 `run-parts --test` 確認出現在清單裡 |
| ★★★ `cmd \| logger` 之後 `\|\|` 通報永遠不觸發 | 管線退出碼是 logger 的（永遠 0） | 讓腳本自己判斷與通報；或 `SHELL=/bin/bash` 加 `set -o pipefail` |
| ★★★ 排程一天跑兩次，磁碟被塞爆 | 同一支腳本同時登記在使用者 crontab 與 `/etc/cron.d/`，cron 不會去重 | 用 `cron-inventory` 六個來源一起盤點，只保留一處 |
| ★★★ 改了機器時區之後所有排程時間集體位移 | 沒宣告 `CRON_TZ` 的排程一律跟隨系統時區 | 跨時區環境全部用 UTC；需要當地時間的個別檔案再宣告 `CRON_TZ` |
| ★★★ VM 從快照還原後，中間那段時間的排程全部沒補跑 | 時間跳躍超過 3 小時被視為時鐘校正，cron 不補跑 | 需要補跑就用 systemd timer 的 `Persistent=true` 或 anacron |
| ★★★ 設了 `MAILTO` 卻從來沒收到告警信 | 機器沒有可用的 MTA，信堆在 `/var/mail/` 或直接消失 | 不要依賴 MAILTO；用 webhook + 旗標檔，並由監控主動檢查 |
| ★★★ `/var/log/syslog` 完全找不到 cron 記錄 | rsyslog 被加了降噪規則把 cron facility 丟掉 | `grep -rn -i cron /etc/rsyslog.d/`；改用不受影響的 `journalctl -u cron` |
| ★★ 手動 `sudo -u svc` 跑得動，cron 跑就 Permission denied | SELinux 的 `system_cronjob_t` context 與手動執行不同 | `ausearch -m avc -ts recent \| audit2why`；用 `semanage fcontext` 修正標籤 |
| ★★ crontab 裡的 `&>`、`[[ ]]` 無效 | 預設 `SHELL=/bin/sh` 在 Ubuntu 是 dash | 加 `SHELL=/bin/bash`，或把邏輯搬進有 `#!/usr/bin/env bash` 的腳本 |

### 排查步驟

★★★★ **固定照這個順序走**，不要跳。多數人一開始就往「腳本有 bug」的方向查，
結果 80% 的案例根本是前四步就能定案。

**【1】確認 cron 服務活著，而且最近有讀到你的檔案**

```bash
systemctl is-active cron && sudo journalctl -u cron --since "-10min" --no-pager | tail -10
```

預期輸出（正常）：

```text
active
Aug 28 10:31:01 srv01 CRON[42011]: (root) CMD (cd / && run-parts --report /etc/cron.hourly)
```

- 看到 `Error:`、`bad username`、`BAD FILE MODE`、`Missing newline` → **問題在【2】**，檔案根本沒被接受。
- 完全沒有任何 CRON 記錄（連別人的排程也沒有）→ 跳到 **【8】**，rsyslog／journald 可能有問題。
- 一切正常但你的工作沒出現 → 繼續 **【3】**。

**【2】確認這一行的格式與檔案本身合格**

```bash
F=/etc/cron.d/data-sync
stat -c '%a %U:%G %n' "$F"
tail -c1 "$F" | xxd
awk 'NF && $1!~/^#/ && $1!~/=/ {print NF" 欄 → "$0}' "$F"
```

預期輸出：

```text
644 root:root /etc/cron.d/data-sync
00000000: 0a                                       .
9 欄 → 0 2 * * *   datasync   /usr/bin/timeout --signal=TERM --kill-after=30s 45m /usr/local/bin/data-sync.sh
```

- mode 不是 `644` 或擁有者不是 `root:root` → cron 拒讀，`chown root:root && chmod 644`。
- `tail -c1` 沒有輸出 `0a` → 檔尾缺換行，整檔被忽略，`echo >> "$F"` 補上。
- 欄數只有 6 且第 6 欄是路徑 → **少了使用者欄**，這是最常見的一種。

**【3】確認 cron 到底有沒有啟動它**

```bash
sudo journalctl -u cron --since "-2d" | grep -i data-sync
```

預期輸出（有啟動）：

```text
Aug 27 02:00:01 srv01 CRON[38221]: (datasync) CMD (/usr/bin/timeout ... /usr/local/bin/data-sync.sh)
Aug 28 02:00:01 srv01 CRON[41233]: (datasync) CMD (/usr/bin/timeout ... /usr/local/bin/data-sync.sh)
```

- **有 `CMD` 行** → cron 沒問題，問題在腳本或環境，跳到 **【6】**。
- **完全沒有 `CMD` 行**，但【2】都正常 → 問題是帳號或時間，繼續 **【4】**。

**【4】確認這個帳號准不准跑 cron（★★★★ 機關環境第一名）**

```bash
U=datasync
ls -l /etc/cron.allow /etc/cron.deny 2>&1 | head -2
grep -x "$U" /etc/cron.allow 2>/dev/null || echo "不在 cron.allow 裡"
getent passwd "$U"
sudo chage -l "$U" | grep -E 'Password expires|Account expires'
sudo journalctl -u cron --since "-2d" | grep -iE 'pam|authentication|expired'
```

預期輸出（正常）：

```text
ls: cannot access '/etc/cron.allow': No such file or directory
-rw-r--r-- 1 root root 0 /etc/cron.deny
不在 cron.allow 裡
datasync:x:997:997::/var/lib/data-sync:/usr/sbin/nologin
Password expires                                        : never
Account expires                                         : never
```

- `cron.allow` **存在**且帳號不在裡面 → 使用者 crontab 直接被拒（`/etc/cron.d` 不受影響）。
- 任一 `expires` 不是 `never` 且日期已過 → ★★★★ 就是它，`sudo chage -M -1 -E -1 "$U"`。
- 看到 `account has expired` 或 `Authentication token is no longer valid` → 確診。

**【5】確認時間那一層**

```bash
timedatectl | grep -E 'Time zone|synchronized'
grep -h '^CRON_TZ' /etc/crontab /etc/cron.d/* 2>/dev/null
sudo journalctl -u chrony --since "-7d" | grep -i 'stepped by'
```

預期輸出：

```text
                 Time zone: Asia/Taipei (CST, +0800)
System clock synchronized: yes
```

- 時區不是你以為的那個 → 所有排程集體位移。
- 看到 `System clock was stepped by 7412.339 seconds`（> 10800 秒）→ ★★★★ 那天的排程沒補跑，
  這是「只有某一天沒跑」的典型解釋，見 [[020-01-28-cmd-Linux-時間同步NTP與chrony]]。

**【6】確認鎖有沒有被卡住的舊程序佔著**

```bash
L=/run/lock/data-sync.d/data-sync.lock
ls -l "$L" 2>/dev/null && sudo fuser -v "$L" 2>&1
pgrep -af 'data-sync|rsync' || echo "沒有相關程序"
```

預期輸出（★★★★ 卡住時長這樣）：

```text
-rw-r--r-- 1 datasync datasync 0 Jul 12 02:00 /run/lock/data-sync.d/data-sync.lock
                     USER        PID ACCESS COMMAND
/run/lock/...lock:   datasync  38102 F....  data-sync.sh
datasync 38102 /bin/bash /usr/local/bin/data-sync.sh
datasync 38109 rsync -a --contimeout=30 rsync://nas01...
```

- 鎖檔的 mtime 停在很久以前，而且 `fuser` 找得到持有者 → **確診：舊程序卡死佔鎖**。
  處理：`sudo kill -TERM 38102`，等 30 秒不死再 `kill -KILL`，然後補上 `timeout`。
- `fuser` 找不到任何程序 → 鎖檔只是殘留的空檔，**不影響 flock**（flock 綁的是 fd 不是檔案存在），
  ★★★ 不需要也不應該刪它。

**【7】用和 cron 一樣的環境重現**

★★★ 直接 `sudo bash script.sh` 是**無效的重現**，因為你的環境變數、PATH、shell 都不一樣。
要盡量接近 cron：

```bash
sudo -u datasync env -i \
     PATH=/usr/bin:/bin HOME=/var/lib/data-sync SHELL=/bin/sh \
     /bin/bash -c '/usr/local/bin/data-sync.sh'; echo "exit=$?"
```

預期輸出（重現成功時會看到真正的錯誤）：

```text
/usr/local/bin/data-sync.sh: line 88: mysql: command not found
exit=2
```

- 手動跑成功、`env -i` 跑失敗 → 確診是環境差異（PATH、語系、缺變數），
  修法是在腳本裡自己 `export`，不要依賴外部環境。
- 兩種都成功 → 問題不在腳本，回到 **【4】【5】【6】**。

**【8】確認日誌管道本身沒被切斷**

```bash
grep -rn -i cron /etc/rsyslog.conf /etc/rsyslog.d/ | grep -v '^\s*#'
sudo journalctl -t data-sync --since "-2d" --no-pager | tail -3
```

- rsyslog 裡有 `stop` 或 `~` 針對 CRON → `/var/log/syslog` 查不到是正常的，改用 journalctl。
- `journalctl -t <tag>` 也撈不到，但你確定腳本有跑 → 檢查腳本裡的 `logger` 是不是被 `|| true` 吞掉了錯誤，
  或 `logger` 不在 PATH 裡。

**【9】RHEL 系再加一步：SELinux**

```bash
sudo ausearch -m avc -ts today | grep -i cron | tail -5
```

- 有 `denied` 且 `scontext` 含 `system_cronjob_t` → ★★★★ 確診是 SELinux，用 `audit2why` 看原因，
  用 `semanage fcontext` + `restorecon` 修標籤，**不要 `setenforce 0`**。見 [[090-02-07-guide-防護-SELinux與AppArmor]]。

---

## 安全性注意事項

> [!danger] ★★★★★ 排程腳本可寫 = 把該帳號的權限送人
> ```bash
> ls -l /usr/local/bin/data-sync.sh
> ```
> ```text
> -rwxrwxr-x 1 root staff 4821 Aug 28 10:12 /usr/local/bin/data-sync.sh   # ✗ group 可寫
> ```
> 這支腳本以某個帳號執行。任何能寫它的人，等於能以那個帳號執行任意指令；
> 如果排程是 root，那就是**整台機器**。
> ```bash
> sudo chown root:root /usr/local/bin/data-sync.sh
> sudo chmod 755 /usr/local/bin/data-sync.sh
> ```
> 全機稽核：
> ```bash
> sudo find /usr/local/bin /etc/cron.d /etc/cron.daily /etc/cron.hourly \
>      \( -perm -o+w -o -perm -g+w \) -ls
> ```
> 預期輸出：**沒有任何一行**。

> [!danger] ★★★★ 不要把密碼寫在 crontab 或指令列
> ```cron
> 0 2 * * * root mysqldump -u root -pP@ssw0rd appdb > /backup/db.sql   # ✗✗✗
> ```
> 三重外洩：
> 1. `/etc/cron.d/` 是 644，**全機任何使用者都讀得到**；
> 2. 執行期間 `ps aux` 看得到完整指令列，**任何使用者都看得到密碼**；
> 3. cron 的 `CMD` 日誌會把整行寫進 syslog，然後被集中蒐集到 SIEM，**擴散到日誌平台**。
>
> 正解：`--defaults-file=` 指向一個 0600、屬於服務帳號的檔案（實戰範例就是這樣做的）。
> ```bash
> sudo grep -rniE 'password|passwd|token|secret|api[-_]?key' /etc/cron.d/ /etc/crontab \
>      /var/spool/cron/crontabs/ 2>/dev/null
> ```
> 預期輸出：**沒有任何一行**。有的話那些憑證要視為已外洩，全部更換。

> [!danger] ★★★★ 排程是入侵者建立持續性存取（persistence）的頭號手法
> 攻擊者拿到權限後第一件事往往是留一個排程，這樣就算你改了密碼他還是回得來。
> 六個來源都要納入基線比對：
> ```bash
> sudo cron-inventory > /var/backups/cron-inventory-$(date +%F).txt
> diff /var/backups/cron-inventory-2026-07-01.txt \
>      /var/backups/cron-inventory-2026-08-28.txt
> ```
> ★★★★ **每一個新增項目都要能說出是誰、什麼時候、為了什麼加的。** 說不出來就當成事件處理。
> 特別注意這些特徵：指令裡有 `curl ... | sh`、`base64 -d`、`/dev/tcp/`、`wget -O- ... | bash`、
> 路徑在 `/tmp` 或 `/dev/shm`、`@reboot` 加上網路連線。
> 集中蒐集與長期保存見 [[090-05-09-guide-資安設備-日誌集中與SIEM]]。

> [!warning] ★★★ 最小權限：先問「這真的需要 root 嗎」
> ```cron
> 0 2 * * * root     /usr/local/bin/data-sync.sh    # ✗ 出事就是全機
> 0 2 * * * datasync /usr/local/bin/data-sync.sh    # ✓ 出事只影響這個帳號的資料
> ```
> 服務帳號要 `--system --shell /usr/sbin/nologin`，並且**不設密碼**。
> 這同時也是 TWGCB 與 CIS 的檢查項目，見 [[020-01-09-cmd-Linux-使用者與群組管理]]。

> [!warning] ★★★ 稽核軌跡：排程日誌本身是稽核證據
> 機關的個資與資安稽核會問「你怎麼證明每天的備份都有成功」。
> `>/dev/null 2>&1` 的排程**沒有任何證據可以提供**。
> 至少要能回答：哪一天跑的、跑多久、退出碼是多少、處理了幾筆。
> 實戰範例的 `[start]` / `[end] exit=N duration=Ns` 就是為了這個而設計的，
> 保存期限與集中蒐集依機關規定辦理（見 [[100-01-02-guide-日誌-日誌集中與輪替]]）。

> [!warning] ★★★ 通報端點也是攻擊面
> `curl` 打到 webhook 時：一定要 `--max-time`（避免通報端點掛掉拖垮排程）、
> 一定要驗證 TLS（**不要**加 `-k`）、URL 裡的 token 要放環境變數或 0600 的檔案而不是寫死在腳本裡、
> 通報內容**不要**帶資料樣本（可能含個資）。★★★ 只帶主機名、工作名、退出碼、原因摘要就夠了。

---

## 速查表

### 判斷準則（先看這張）

| 症狀 | 最可能的原因 | 先查什麼 | 星級 |
| --- | --- | --- | --- |
| journal 有 `CMD` 但沒結果 | 腳本失敗且輸出被丟掉 | 手動用 `env -i` 重現 | ★★★★ |
| journal 完全沒有 `CMD` | 檔案被拒／帳號被拒 | `journalctl -u cron` 存檔那一分鐘 | ★★★★ |
| 從某天起再也沒跑 | 卡死程序佔著 flock | `fuser <lock>` | ★★★★ |
| 只有某一天沒跑 | 時間跳躍超過 3 小時 | `journalctl -u chrony \| grep stepped` | ★★★ |
| 半年後集體停擺 | 帳號／密碼到期 | `chage -l` | ★★★★ |
| 一天跑兩次 | 登記在兩個來源 | `cron-inventory` | ★★★ |
| 產出的檔案是空的 | `%` 未跳脫指令被截斷 | `grep -rnE '[^\\]%'` | ★★★★ |

### 診斷指令

| 指令 | 用途 | 星級 |
| --- | --- | --- |
| `journalctl -u cron --since "-1d"` | Ubuntu 的 cron 日誌（不受 rsyslog 過濾影響） | ★★★★ |
| `journalctl -u crond` | ★★★ RHEL 系服務名不同 | ★★★ |
| `journalctl -t <tag>` | 撈自己用 `logger -t` 打的記錄 | ★★★★ |
| `run-parts --test /etc/cron.daily` | 唯一可信的 `cron.daily` 驗證方式 | ★★★★ |
| `tail -c1 <file> \| xxd` | 檢查檔尾換行（`0a`） | ★★★★ |
| `awk 'NF && $1!~/^#|=/ {print NF}' <file>` | 數欄位，抓「少一欄」 | ★★★★ |
| `fuser -v <lockfile>` | 誰持有這個鎖 | ★★★★ |
| `chage -l <user>` | 帳號／密碼到期 | ★★★★ |
| `findmnt -t nfs,nfs4,cifs -o TARGET,OPTIONS` | 看 `local_lock`／`nolock` | ★★★★ |
| `grep -rn -i cron /etc/rsyslog.d/` | 日誌有沒有被過濾掉 | ★★★ |
| `ausearch -m avc -ts recent` | RHEL 的 SELinux 拒絕 | ★★★ |
| `sudo -u <u> env -i PATH=/usr/bin:/bin HOME=... bash -c '...'` | 模擬 cron 環境重現 | ★★★★ |

### 檔案與路徑

| 路徑 | 內容 | 注意 | 星級 |
| --- | --- | --- | --- |
| `/etc/cron.d/<name>` | 系統排程，**六欄** | 檔名不可含 `.`（Debian）、644 root、檔尾要換行 | ★★★★ |
| `/etc/crontab` | 系統排程，**六欄** | 套件更新可能覆寫，建議別動 | ★★★ |
| `/var/spool/cron/crontabs/<u>` | 使用者 crontab（Debian） | ★★★★ 不要直接編輯 | ★★★★ |
| `/var/spool/cron/<u>` | 使用者 crontab（RHEL） | 同上 | ★★★ |
| `/etc/cron.allow` / `cron.deny` | 誰能用 `crontab` | allow 存在時 deny 完全失效 | ★★★★ |
| `/run/lock/` | 鎖檔（tmpfs，開機清空） | ★★★★ 不要放 NFS | ★★★★ |
| `/run/<job>.fail` | 失敗旗標，給監控撿 | 成功時記得刪掉 | ★★★ |
| `/etc/logrotate.d/<job>` | 排程日誌輪替 | 沒有它，log 會塞爆根分割區 | ★★★ |
| `/etc/tmpfiles.d/<job>.conf` | 重開機後重建 `/run` 底下目錄 | 沒有它，重開機後鎖目錄消失 | ★★★ |

### 生產級排程的必備元素

| 元素 | 寫法 | 漏掉的後果 | 星級 |
| --- | --- | --- | --- |
| 互斥 | `flock -n -E 75` 或腳本內 `exec 9>lock; flock -n 9` | 重疊執行、資料互相覆蓋 | ★★★★ |
| 逾時 | `timeout --signal=TERM --kill-after=30s 30m` | 卡死佔鎖，之後永遠不跑 | ★★★★ |
| 記錄 | `logger -t <tag> -p cron.err` 或專屬 log + logrotate | 失敗三個月沒人知道 | ★★★★ |
| 退出碼分類 | 0／1／2／75／124 | 監控無法分辨「跳過」與「壞掉」 | ★★★★ |
| 失敗通報 | 旗標檔 + webhook（`--max-time`） | 告警是假的 | ★★★★ |
| 收尾 | `trap on_exit EXIT` | 暫存檔堆積、旗標沒清 | ★★★ |
| 前置檢查 | 相依指令、磁碟、DB 連線 | 做到一半才失敗，留下半套資料 | ★★★ |
| 結果驗證 | 檢查資料真的更新了 | 退出碼 0 但什麼都沒做 | ★★★★ |
| 環境自足 | 腳本自己 `export PATH`／`LC_ALL` | 換一台機器就壞 | ★★★ |

### 退出碼約定

| 退出碼 | 意義 | 監控該怎麼反應 | 星級 |
| --- | --- | --- | --- |
| `0` | 成功 | 清除旗標 | ★★ |
| `1` | 業務失敗（資料有問題） | 上班時間通知 | ★★★ |
| `2` | 環境失敗（不可達／磁碟／相依） | ★★★★ 立即通知 | ★★★★ |
| `75` | 被跳過或暫時性失敗 | 不通知；連續 3 次才通知 | ★★★★ |
| `124` | ★★★★ `timeout` 強制中止 | 立即通知，並檢查有無殘留程序 | ★★★★ |
| `126` | 檔案存在但不可執行 | 檢查 `chmod +x` 與掛載的 `noexec` | ★★★ |
| `127` | `command not found` | ★★★★ 幾乎都是 PATH 問題 | ★★★★ |

---

## 練習題

> [!question]- 練習 1：找出你環境裡所有「靜默失敗」的排程並排序處理
> **題目**：在一台測試機上，用本篇的 `cron-inventory` 盤點六種來源，
> 找出所有把輸出丟進 `/dev/null` 的排程，並依「失敗了會不會出事」排出處理順序。
>
> **參考解答**：
>
> ```bash
> sudo cron-inventory > /tmp/inv.txt
> grep -rlE '>\s*/dev/null\s+2>&1' /etc/crontab /etc/cron.d/ /var/spool/cron/crontabs/ 2>/dev/null
> ```
>
> 假設結果是：
>
> ```text
> /etc/cron.d/db-backup
> /etc/cron.d/tmp-cleanup
> /var/spool/cron/crontabs/ops
> ```
>
> 排序原則（★★★★ 依「失敗後多久會被發現」而不是「多久跑一次」）：
>
> | 順位 | 排程 | 理由 |
> | --- | --- | --- |
> | 1 | `db-backup` | ★★★★★ 失敗要到還原那天才發現，而那天通常已經來不及 |
> | 2 | `ops` 的資料同步 | ★★★★ 影響前台資料正確性，但使用者會抱怨，還有機會被發現 |
> | 3 | `tmp-cleanup` | ★★★ 失敗會慢慢塞爆磁碟，磁碟監控會先叫 |
>
> 每一支的最小修法（不改腳本內容也能立刻收效）：
>
> ```cron
> # 先加上專屬日誌，讓錯誤至少留下來
> 0 3 * * * root /usr/local/bin/db-backup.sh >> /var/log/db-backup.log 2>&1
> ```
>
> 再補 logrotate，最後才依實戰範例的框架重寫腳本。

> [!question]- 練習 2：重現「卡死佔鎖」並確認 `timeout` 真的救得回來
> **題目**：做一個會永遠卡住的假排程，觀察後續每一輪都被跳過的現象，
> 再加上 `timeout` 驗證問題消失。
>
> **參考解答**：
>
> ```bash
> # ① 準備一支會卡死的腳本
> sudo tee /usr/local/bin/stuck.sh >/dev/null <<'EOF'
> #!/usr/bin/env bash
> echo "開始 $(date -Is)" | logger -t stuck
> sleep 100000        # 模擬 NAS 不回應
> EOF
> sudo chmod 755 /usr/local/bin/stuck.sh
>
> # ② 每分鐘跑一次，只有 flock 沒有 timeout
> sudo tee /etc/cron.d/stuck >/dev/null <<'EOF'
> * * * * * root /usr/bin/flock -n -E 75 /run/lock/stuck.lock /usr/local/bin/stuck.sh
> EOF
>
> # ③ 等三分鐘後觀察
> sleep 200
> sudo journalctl -t stuck --no-pager
> ```
>
> 預期輸出（★★★★ 只有第一次跑起來，之後完全靜音）：
>
> ```text
> Aug 28 10:41:01 srv01 stuck[43012]: 開始 2026-08-28T10:41:01+08:00
> ```
>
> 確認鎖被誰佔著：
>
> ```bash
> sudo fuser -v /run/lock/stuck.lock
> ```
>
> ```text
>                      USER        PID ACCESS COMMAND
> /run/lock/stuck.lock: root      43012 F....  stuck.sh
> ```
>
> ④ 加上 `timeout` 後重測：
>
> ```bash
> sudo tee /etc/cron.d/stuck >/dev/null <<'EOF'
> * * * * * root /usr/bin/flock -n -E 75 /run/lock/stuck.lock /usr/bin/timeout --signal=TERM --kill-after=10s 30s /usr/local/bin/stuck.sh
> EOF
> sudo pkill -f stuck.sh
> sleep 200
> sudo journalctl -t stuck --no-pager | tail -3
> ```
>
> 現在每分鐘都會有一筆「開始」，因為 30 秒後就被砍掉、鎖被釋放。
>
> ⑤ 清理：`sudo rm -f /etc/cron.d/stuck /usr/local/bin/stuck.sh; sudo pkill -f stuck.sh`

> [!question]- 練習 3：驗證帳號到期會讓 cron 靜默拒跑
> **題目**：在測試機上建一個帳號，故意讓它的密碼過期，證明 cron 拒跑，
> 並找出對應的 syslog 訊息與修復指令。
>
> **參考解答**：
>
> ```bash
> # ① 建帳號並排一個每分鐘的排程
> sudo useradd -m -s /bin/bash testcron
> echo '* * * * * /usr/bin/logger -t testcron "跑了 $(date +\%s)"' \
>   | sudo crontab -u testcron -
> sleep 70 && sudo journalctl -t testcron --no-pager | tail -2
> ```
>
> ```text
> Aug 28 10:52:01 srv01 testcron[44001]: 跑了 1756349521
> ```
>
> ```bash
> # ② 讓密碼立刻過期（模擬 180 天政策到期）★★★★
> sudo chage -d 2020-01-01 -M 30 testcron
> sudo chage -l testcron | grep 'Password expires'
> sleep 130
> sudo journalctl -t testcron --since "-2min" --no-pager | wc -l
> sudo journalctl -u cron --since "-2min" | grep -i testcron
> ```
>
> 預期輸出：
>
> ```text
> Password expires                                        : Jan 31, 2020
> 0
> Aug 28 10:55:01 srv01 CRON[44120]: Authentication token is no longer valid; new one required
> Aug 28 10:55:01 srv01 CRON[44120]: (testcron) PAM ERROR (Authentication token is no longer valid; new one required)
> ```
>
> ★★★★ 重點：`systemctl status cron` 仍然是 `active (running)`，
> `crontab -l -u testcron` 也還看得到排程，只是它不跑了。
>
> ```bash
> # ③ 修復並確認恢復
> sudo chage -M -1 -E -1 testcron
> sudo chage -d "$(date +%F)" testcron
> sleep 70 && sudo journalctl -t testcron --since "-1min" --no-pager | tail -1
>
> # ④ 清理
> sudo crontab -u testcron -r && sudo userdel -r testcron
> ```
>
> 服務帳號的正解是一開始就 `--system` 建立並 `chage -M -1 -E -1`，不要等政策上路才處理。

---

## 小測驗

Q1. `/etc/cron.d/backup` 裡寫了 `0 2 * * * /usr/local/bin/backup.sh`，存檔後排程完全沒跑。錯在哪？syslog 的訊息會在什麼時間點出現？

Q2. 一支排程在 RHEL 上跑得好好的，用同一份 Ansible playbook 部署到 Ubuntu 就完全失效，檔名是 `/etc/cron.d/db.backup`。為什麼？

Q3. `0 3 * * * root tar czf /backup/db-$(date +%F).tar.gz /var/lib/mysql` 這一行實際上會執行什麼？產出的檔案會是什麼樣子？

Q4. `flock -n` 與 `flock -n -E 75` 的差別是什麼？為什麼在排程裡這個差別很重要？

Q5. （是非）鎖檔放在 NFS 共用目錄上，就能讓兩台主機的排程互斥。

Q6. 某支排程「從 7/12 之後再也沒跑過」，但 `journalctl -u cron` 每天都有 `CMD` 那一行。最可能的原因是什麼？該用哪一個指令確診？

Q7. 機關導入「密碼 180 天強制更換」政策六個月後，所有服務帳號的排程在同一週集體停擺。`systemctl status cron` 顯示什麼？怎麼查、怎麼修？

Q8. `0 2 * * * /usr/local/bin/x.sh 2>&1 | logger -t x || /usr/local/bin/alert.sh` 這一行的 `alert.sh` 什麼時候會被執行？

Q9. 你在 `/etc/cron.d/reports` 檔案中間加了 `CRON_TZ=UTC`。它會影響哪些排程行？如果改的是 `timedatectl set-timezone UTC` 呢？

Q10. 一台 VM 從三天前的快照還原回來，還原後那三天的每日備份會不會補跑？為什麼？想要補跑該用什麼？

> [!question]- 測驗答案
>
> **Q1.** ★★★★ 少了**使用者欄**。`/etc/cron.d/` 與 `/etc/crontab` 是「五欄 + 使用者 + 指令」共六欄，
> 使用者 crontab 才是「五欄 + 指令」。cron 會把第六欄 `/usr/local/bin/backup.sh` 當成使用者名稱去查
> `/etc/passwd`，查不到就整行放棄。
> 正確寫法：`0 2 * * * root /usr/local/bin/backup.sh`。
> ★★★★ **訊息出現在「存檔後一分鐘內」cron 重新載入檔案的時候，不是排程時間 02:00。**
> 所以隔天早上用 `journalctl --since "02:00"` 去找會什麼都找不到，看起來像「時間設定錯誤」。
> 驗證欄數：`awk 'NF && $1!~/^#|=/ {print NF}' /etc/cron.d/backup`，至少要 7。
> 見「格式寫錯的後果不是報錯，是整行消失」與排查步驟【2】。
>
> **Q2.** ★★★★ 檔名裡有 `.`。這是**兩套不同規則**：
> Debian／Ubuntu 的 cron 規定 `/etc/cron.d/` 的檔名「只能是大小寫字母、數字、底線、減號」，
> 含 `.` 一律忽略（設計目的是避開 `.dpkg-dist`、`.dpkg-old` 這類套件管理殘留檔）；
> RHEL 的 cronie 寬鬆得多，只忽略開頭是 `.`／`#`、結尾是 `~`／`.rpmsave`／`.rpmorig`／`.rpmnew` 的檔案，
> 所以 `db.backup` 在 RHEL 上**會執行**。
> 修法：`sudo mv /etc/cron.d/db.backup /etc/cron.d/db-backup`，一律用不含點的檔名兩邊都安全。
> ★★★ 注意這跟 `cron.daily` 的 `run-parts` 規則又是另一套，不要混為一談。
> 見「兩套完全不同的檔名規則」。
>
> **Q3.** ★★★★ `%` 在 crontab 的指令欄是特殊字元：第一個未跳脫的 `%` **之後的所有內容會變成標準輸入**，
> 後續的 `%` 會被轉成換行。所以 cron 實際執行的是 `tar czf /backup/db-$(date +`，
> stdin 是 `F).tar.gz /var/lib/mysql`。
> `date +` 印出空字串，於是產生的是一個叫 `/backup/db-.tar.gz` 的檔案，
> 而且 `tar` **沒有收到任何來源路徑**，可能建出一個幾乎空的壓縮檔然後 `exit 0`。
> ★★★★ 最可怕的地方是它「成功」了 —— 沒有錯誤、退出碼是 0、監控全綠。
> 修法：寫成 `date +\%F`，或（推薦）把整段搬進腳本，crontab 只留 `/usr/local/bin/db-backup.sh`。
> 全機掃描：`grep -rnE '[^\\]%' /etc/cron.d/ /etc/crontab /var/spool/cron/crontabs/`。
> 見「`%` 是換行符號，不是百分比」。
>
> **Q4.** 兩者的**行為**相同（拿不到鎖立刻放棄），差別在**退出碼**：
> `-n` 的衝突退出碼預設是 `1`，`-E 75` 改成 `75`。
> ★★★★ 這很重要，因為排程有兩種「今天沒做事」：
> ①「上一輪還在跑，這輪跳過」——**正常**，不該叫人起床；
> ②「腳本執行了但失敗，exit 1」——**不正常**，要立刻處理。
> 沒有 `-E` 的話兩者都是 1，監控端無法分辨，只能二選一：要嘛半夜被正常的跳過吵醒，
> 要嘛把真正的失敗一起忽略掉。
> 實測：開兩個終端機同時跑 `flock -n -E 75 /run/lock/x.lock sleep 60; echo $?`，
> 第二個會立刻印出 `75`。
> ★★ `-E` 對 `-w` 的逾時同樣生效，要分辨兩種情境就給兩個不同的值。
> 見「重疊執行的完整解法」。
>
> **Q5.** ★★★★ **錯。** `man 2 flock` 說明：Linux 2.6.12 之後 NFS client 是把 `flock()`
> **模擬**成對整個檔案的 fcntl byte-range lock；2.6.37 之後又加入 `local_lock` 掛載選項，
> **可以讓 flock 變成純本機鎖**。
> 只要掛載時帶了 `-o nolock`（NFSv3 很常見）或 `-o local_lock=all`，
> 兩台主機會**各自都拿得到鎖**，於是同時對同一份資料寫入。
> 即使沒有這些選項，NFS server 重啟或網路中斷後的鎖恢復期間仍有雙重執行的時間窗，
> CIFS 更是隨伺服器實作而異（`nobrl` 直接關掉 byte-range lock）。
> 檢查：`findmnt -t nfs,nfs4,cifs -o TARGET,OPTIONS`，看到 `local_lock=all` 或 `nolock` 就確定不可靠。
> **正解**：鎖放本機 `/run/lock/`，跨主機互斥用 DB advisory lock 或架構上只讓一台跑。
> 見「鎖檔放哪裡」的 danger callout。
>
> **Q6.** ★★★★ 最可能是**上一輪卡死的程序還持有 flock**，之後每一輪都被 `flock -n` 立刻跳過。
> 典型觸發：rsync 對到「連得上但不回應」的 NAS，或 mysql 卡在鎖等待，沒有 `timeout` 就永遠不結束。
> `CMD` 那行照樣每天出現，因為 cron 確實有 fork 出 `flock`，只是它 0.01 秒就退出了。
> 確診指令：
> ```bash
> sudo fuser -v /run/lock/data-sync.d/data-sync.lock
> pgrep -af 'data-sync|rsync'
> ```
> 看到一個啟動時間停在 7/12 的程序就確診。
> 處理：`kill -TERM <pid>`，30 秒不死再 `kill -KILL`，然後**補上**
> `timeout --signal=TERM --kill-after=30s 30m` 並處理退出碼 124。
> ★★★ 順帶一提：鎖檔本身存在不代表被鎖住，flock 綁的是 file descriptor，殘留的空檔案不影響。
> 見「逾時保護」與排查步驟【6】。
>
> **Q7.** ★★★★ `systemctl status cron` 顯示 **`active (running)`** —— 服務完全正常，
> 只是 cron 在執行工作前會走 PAM 的 account 階段，`pam_unix` 檢查 `/etc/shadow` 的到期欄位失敗，
> 於是**直接拒跑**，而且 journal 裡連 `CMD` 那行都不會出現。
> 查：
> ```bash
> sudo chage -l datasync | grep -E 'Password expires|Account expires'
> sudo journalctl -u cron --since "-2d" | grep -iE 'expired|Authentication token'
> ```
> 會看到 `Authentication token is no longer valid; new one required` 或
> `pam_unix(cron:account): account datasync has expired`。
> 修：`sudo chage -M -1 -E -1 datasync`（密碼與帳號都不設到期），
> 並用 `sudo passwd -l datasync` 鎖住互動登入。
> ★★★ 改完要實測一個一分鐘後的測試排程確認真的恢復，不要只看 `chage -l`。
> 服務帳號應該一開始就用 `useradd --system` 建立。見「cron 靜默拒跑」③。
>
> **Q8.** ★★★★ **永遠不會執行。** `||` 判斷的是**整條管線的退出碼**，
> 而管線的退出碼是**最後一個指令**（`logger`）的，`logger` 幾乎永遠成功回傳 0。
> 所以 `x.sh` 就算 exit 1、exit 127 甚至被 timeout 砍掉，`alert.sh` 都不會被呼叫 ——
> 這是一種「以為裝了告警其實沒有」的假安全感，比完全沒裝更危險。
> 同樣的原因，cron 的 `-L 15` 記錄到的也會是 `exit status 0`。
> 三種正解：① 讓腳本自己 `logger`、自己判斷、自己通報（本篇實戰範例的做法）；
> ② 導到檔案 `>> /var/log/x.log 2>&1`，不經過管線，退出碼完整保留；
> ③ 一定要用管線就 `SHELL=/bin/bash` 加 `set -o pipefail`。
> 見「輸出處理：靜默失敗 vs. 有紀錄」的 danger callout。
>
> **Q9.** ★★★ `CRON_TZ=UTC` 的作用域是「**同一個檔案裡、這一行之後**」的排程行。
> 所以它只影響 `/etc/cron.d/reports` 裡寫在它下面的那幾行；
> 同檔案中寫在它**上面**的行、以及 `/etc/cron.d/backup`、`/etc/crontab`、
> 任何使用者的 crontab 都**完全不受影響**。
> 而 `timedatectl set-timezone UTC` 是**第一層**（機器時區），
> ★★★★ 會讓**所有沒有宣告 `CRON_TZ` 的排程一起位移**：原本 02:00 的備份會變成台北時間 10:00 執行，
> 直接撞上上班尖峰。
> 還有第三層要注意：應用程式自己的時區（PHP `date.timezone`、MySQL `time_zone`）不會跟著改，
> 於是「排程在對的時間跑了，但程式算出來的『昨天』是 UTC 的昨天」，報表會少一天或多一天。
> 見「時間有三層」。
>
> **Q10.** ★★★★ **不會補跑。** 依 `man 8 cron`，時間跳躍**超過 3 小時**會被 cron 視為「時鐘校正」，
> 直接用新時間繼續，中間錯過的工作全部消失；只有跳躍**小於 3 小時**時，
> 往前跳被略過的（有指定時分的）工作才會盡快補跑一次，往後跳落在重複時段的工作則不會重跑。
> 快照還原、VM 暫停後恢復、新機器第一次 NTP 大幅校時，都屬於「超過 3 小時」這一類。
> 佐證：
> ```bash
> sudo journalctl -u chrony --since "-7d" | grep -i 'stepped by'
> ```
> 看到 `System clock was stepped by 7412.339 seconds`（> 10800 秒）就確定那段時間的排程沒跑。
> 要能補跑有兩個選擇：systemd timer 的 `Persistent=true`（記錄上次執行時間，開機後補跑一次，
> 見 [[020-02-02-02-cmd-systemd-timer與cron選型]]），或 anacron（見 [[020-01-18-guide-Linux-排程工作]]）。
> ★★★ 另外，快照還原後也要檢查有沒有殘留的鎖檔與 `.fail` 旗標。
> 見「時間有三層」的跳躍規則表。

---

## 延伸閱讀

- [[020-01-18-guide-Linux-排程工作]] — cron 五欄語法、`*/15` 寫法、四大失敗原因、anacron 的基礎，本篇所有陷阱的前提
- [[020-02-02-02-cmd-systemd-timer與cron選型]] — 什麼時候該放棄 cron 改用 timer：`Persistent=`、`RandomizedDelaySec=`、cgroup 逾時的完整比較
- [[020-02-02-01-svc-systemd-unit撰寫實戰]] — `@reboot` 的正確替代方案：用 `Requires=`／`After=` 宣告掛載與資料庫相依
- [[020-02-02-04-svc-systemd-服務自動復原與看門狗]] — 排程失敗之後的告警與自動處置（`OnFailure=`、`Restart=`）
- [[020-01-22-guide-Linux-Shell腳本進階]] — `set -euo pipefail`、`trap`、`PIPESTATUS` 與退出碼設計，本篇的 wrapper 全部建立在這些之上
- [[020-01-09-cmd-Linux-使用者與群組管理]] — 服務帳號建立、`chage` 到期政策、`nologin` 與最小權限
- [[020-01-28-cmd-Linux-時間同步NTP與chrony]] — 時間跳躍的來源與如何避免大幅 step
- [[100-01-02-guide-日誌-日誌集中與輪替]] — 排程日誌的 logrotate 與集中蒐集，稽核軌跡保存
- [[060-01-06-03-guide-傳輸-備份策略與還原演練]] — 「備份排程有跑」與「備份真的能還原」是兩件事
- `man 5 crontab`（`%` 與欄位格式）／`man 8 cron`（檔名規則、`-L` 記錄層級、時間跳躍的 3 小時規則）
- `man 1 flock`（`-n`／`-w`／`-E`）／`man 2 flock`（NFS 上的 flock 語意）／`man 1 timeout`
- Debian cron(8) 官方手冊：<https://manpages.debian.org/stable/cron/cron.8.en.html>
- cronie 專案（RHEL 系的 cron 實作）：<https://github.com/cronie-crond/cronie>
- util-linux flock(1) 手冊：<https://man7.org/linux/man-pages/man1/flock.1.html>
