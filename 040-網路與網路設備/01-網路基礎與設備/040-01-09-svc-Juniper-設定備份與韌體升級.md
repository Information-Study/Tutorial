---
title: "Juniper 設定備份與韌體升級"
desc: "save／load 與 system archival 自動備份、request system software add 升級流程、雙分割區與 snapshot，以及升級失敗時的回退"
aliases: [system archival, request system software add, request system snapshot, rollback rescue, dual-root, JTAC recommended]
tags: [群組/網路與設備, 網路/設備, 主題/網路]
category: 網路基礎與設備
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[040-01-05-cmd-Juniper-JunOS-基礎操作]]", "[[040-01-07-guide-Juniper-管理IP與遠端存取]]"]
updated: 2026-09-02
---

# Juniper 設定備份與韌體升級

> [!abstract] 這篇你會學到
> - ★★★★★ **`system archival` 每次 commit 自動把設定送到外部伺服器** ——
>   設定好之後，「忘記備份」這件事就不存在了
> - ★★★★★ **雙分割區（dual root）與 `request system snapshot`**：
>   Juniper 設備有兩份可開機的系統，升級失敗還能從另一份開起來
> - ★★★★★ **`commit confirmed` 在遠端升級時的救命用法**，以及它救不了的情況
>   要用 `request system reboot in N` 補上
> - ★★★★ 升級前的六項檢查（磁碟空間、雜湊驗證、`validate`、設定備份、rescue、變更時窗）
>   與升級後的八項驗證
> - ★★★★ `request system software rollback` 回到升級前的版本，以及它為什麼有時候不管用
> - ★★★★ Junos 版本編號 `21.4R3-S5.4` 每一段的意思，以及怎麼挑「該升到哪一版」
> - ★★★ Virtual Chassis 的升級、`show system snapshot`、`Host 0 Boot from backup root` 告警怎麼處理
> - 產出一份完整的「交換器韌體升級 SOP」與升級前後檢查表

> [!warning] 未實機驗證
> ★★★★★ 本專案沒有實體 Juniper 設備可驗證。
> **韌體升級是本手冊風險最高的操作之一**：`request system software add` 的可用選項、
> `request system snapshot` 的行為、分割區配置（EX2300／EX3400 與 EX4300／EX4600 差異很大）、
> Virtual Chassis 的升級方式，**都依機型與 Junos 版本而不同**。
> 導入前務必：
> 1. 讀該版本的 **Release Notes** 與該機型的 **Software Installation and Upgrade Guide**
> 2. 在**同型號的測試機**上完整走一遍
> 3. 第一次在正式環境做時，**人在機房、console 線接著**

## 前置知識

- [[040-01-05-cmd-Juniper-JunOS-基礎操作]] —— `commit confirmed`、`rollback`、`file copy`、`request system`
- [[040-01-07-guide-Juniper-管理IP與遠端存取]] —— 備份要送到哪、走什麼協定
- [[020-02-01-01-cmd-SSH-原理與第一次連線]] —— SCP 傳輸的基礎
- [[100-02-08-guide-維運-變更管理流程]] —— 變更時窗、簽核、回退計畫
- [[040-01-19-guide-網路設備-交換器汰換與遷移實務]] —— 換機時的設定搬遷

## 觀念說明

### JunOS 的設定到底存在哪裡 ★★★★

```text
   commit
     │
     ├──▶ /config/juniper.conf.gz          ← ★★★★★ 目前生效的設定（rollback 0）
     │                                        開機時載入的就是它
     ├──▶ /config/juniper.conf.1.gz        ← rollback 1
     ├──▶ /config/juniper.conf.2.gz        ← rollback 2
     ├──▶ /config/juniper.conf.3.gz        ← rollback 3
     ├──▶ /var/db/config/juniper.conf.4.gz ← rollback 4
     │        ⋮                               （一路到 49）
     └──▶ /var/db/config/juniper.conf.49.gz

   request system configuration rescue save
     └──▶ /config/rescue.conf.gz            ← ★★★★★ 救援設定
                                               不受 50 版輪替影響，只有你手動更新
```

★★★★★ **這 50 份加上 rescue，全部都在設備自己身上。**
設備硬體故障、被偷、火災、韌體升級把檔案系統搞壞 —— 這些備份就一起沒了。
**所以「設備內建的 rollback」不算備份**，它只是「回退機制」。

| 層級 | 是什麼 | 保護什麼 | 不保護什麼 | 星級 |
| --- | --- | --- | --- | --- |
| `rollback 1~49` | 設備內的 commit 歷史 | ★★★★★ 改壞了 | 設備本身壞掉 | ★★★★★ |
| `rescue` | 設備內手動存的已知好狀態 | ★★★★★ 連續改壞好幾版 | 設備本身壞掉 | ★★★★★ |
| 外部備份（`file copy`／`archival`） | ★★★★★ **真正的備份** | 設備故障、遺失、換機 | 備份伺服器也壞掉 | ★★★★★ |
| 異地／離線備份 | 備份的備份 | ★★★★ 機房災害、勒索軟體 | — | ★★★★ |

★★★★ 這就是資料備份的 **3-2-1 原則**用在網路設備上：
**3 份副本、2 種媒介、1 份異地**。詳細原理見 [[100-02-04-guide-維運-每月維護作業]] 與
[[020-02-03-01-svc-標準化-新機建置標準流程]]。

### 三種備份格式，用途不同 ★★★★

```text
netadmin@sw> show configuration | display set | save /var/tmp/a.set        ← ① set 格式
netadmin@sw> show configuration | save /var/tmp/a.conf                     ← ② 階層格式
netadmin@sw> file copy /config/juniper.conf.gz /var/tmp/a.conf.gz          ← ③ 原始壓縮檔
```

| 格式 | 特徵 | 適合 | 星級 |
| --- | --- | --- | --- |
| ① `\| display set` | 一行一條完整路徑，可直接貼 | ★★★★★ **交接文件、變更佐證、diff 比對、換機還原** | ★★★★★ |
| ② 階層格式（curly brace） | 好讀，`load merge/override` 用 | 大段還原 | ★★★★ |
| ③ `/config/juniper.conf.gz` | 設備原生格式，含註解與中繼資料 | ★★★ 災難復原時最完整 | ★★★ |

★★★★★ **日常備份請用 ①（set 格式）**：
- 兩個版本 `diff` 一下就知道改了什麼（階層格式的 diff 很難讀）
- `grep` 找得到（「哪台設備用了 VLAN 40？」`grep "vlan-id 40" *.set`）
- 貼到另一台設備上就是完整設定
- 進版控（git）之後，每一次變更都有 commit 訊息與作者

### Junos 版本編號怎麼讀 ★★★★

```text
          21  .  4  R  3  -  S  5  .  4
          │      │  │  │     │  │     │
          │      │  │  │     │  │     └── spin：同一個 SR 的小修正
          │      │  │  │     │  └──────── Service Release 編號
          │      │  │  │     └─────────── Service Release（★★★★ 累積修正）
          │      │  │  └───────────────── 該版本的第 3 次 Release
          │      │  └──────────────────── R = 正式版（X = 特殊版本）
          │      └─────────────────────── 季（1～4）
          └────────────────────────────── 年（2021）
```

| 挑版本的原則 | 說明 | 星級 |
| --- | --- | --- |
| ★★★★★ 查 **JTAC Recommended Junos Software Versions** | Juniper 官方公布「建議用這幾版」的清單，是最重要的依據 | ★★★★★ |
| ★★★★ 選 **EEOL（Extended End of Life）** 版本 | 支援期限長很多，機關設備汰換週期 5～7 年，不選 EEOL 會很快沒有安全更新 | ★★★★★ |
| ★★★★ 不要用 `Rn`（沒有 `-S`）的第一版 | R1 通常還有不少已知問題，等到 R2／R3 + 幾個 SR 比較穩 | ★★★★ |
| ★★★★ 全機關版本**收斂** | 同一批設備用同一版，排錯與文件才管得動 | ★★★★ |
| ★★★★★ 查 **Juniper Security Advisories（PSIRT）** | 目前版本有沒有已知高風險漏洞，這是升級的主要理由 | ★★★★★ |
| ★★★ 讀 Release Notes 的 **Known Issues** | 你用到的功能有沒有在已知問題清單裡 | ★★★★ |

```text
netadmin@sw> show version | match "Model|Junos:"
Model: ex4300-48t
Junos: 21.4R3-S5.4
```

> [!warning] ★★★★★ 韌體升級的理由排序
> 1. ★★★★★ **修補已知的高風險漏洞**（PSIRT 公告）—— 這是唯一「非升不可」的理由
> 2. ★★★★ **修正你正在遇到的 bug**（TAC 明確指出某版修掉了）
> 3. ★★★ **需要新功能**（例如要用某個新的 ELS 功能）
> 4. ★★ **版本太舊快要 EOL**，未來沒有安全更新
>
> ★★★★★ **「因為有新版所以升級」不是理由。**
> 網路設備的韌體升級有實質風險（升級失敗、新版有新 bug、設定行為改變），
> 沒有明確理由就不要動。這跟伺服器的「定期更新」思維不一樣 ——
> 交換器一年升一次到兩次是合理的節奏。

### 雙分割區（dual root partitioning）★★★★★

這是 Juniper 設備最重要的一道保險：**設備裡有兩份可以開機的系統**。

```text
   ┌──────────────────────────────────────────────────────┐
   │  內建儲存（internal flash / SSD）                     │
   │                                                       │
   │  ┌────────────────────┐   ┌────────────────────┐    │
   │  │  slice 1（alternate）│   │  slice 2（primary） │    │
   │  │  Junos 21.4R3-S5.4  │   │  Junos 23.4R2-S3   │    │
   │  │  ← 升級前的舊版本    │   │  ← 目前開機用的     │    │
   │  └────────────────────┘   └────────────────────┘    │
   │                                                       │
   │  ┌──────────────────────────────────────────────┐   │
   │  │ /config 分割區（設定檔，★★★★ 兩個 slice 共用）│   │
   │  └──────────────────────────────────────────────┘   │
   └──────────────────────────────────────────────────────┘

   ★★★★★ primary 開機失敗 → 韌體自動改從 alternate 開機
          並產生告警：Host 0 Boot from backup root
```

| 概念 | 意義 | 星級 |
| --- | --- | --- |
| `primary` slice | 目前用來開機的那一份 | ★★★★ |
| `alternate` / `backup` slice | 另一份，通常是升級前的舊版本 | ★★★★★ |
| `request system snapshot` | ★★★★★ **把目前的系統複製到另一個 slice** | ★★★★★ |
| `Host 0 Boot from backup root` | ★★★★★ **primary 壞了，現在跑的是備援** —— 必須立刻處理 | ★★★★★ |
| `request system reboot slice alternate` | 下次從另一個 slice 開機 | ★★★★ |

> [!danger] ★★★★★ 看到 `Host 0 Boot from backup root` 告警不要忽略
> 它的意思是：**主分割區已經壞了，你現在是靠備援分割區在跑**。
> 這時候設備看起來一切正常，但你已經**沒有第二份保險了** ——
> 備援再壞一次，設備就開不起來。
>
> 標準處理：
> 1. 先確認目前跑的版本是不是你要的（`show version`）
> 2. `request system snapshot`（把目前這份健康的系統複製回去，修復主分割區）
> 3. `show system snapshot media internal` 確認兩個 slice 都有正確版本
> 4. 告警消失（可能需要重開機）
> 5. ★★★★ 若 snapshot 反覆失敗，很可能是**儲存媒體實體損壞**，準備報修／換機

### `commit confirmed` 在升級時能救什麼、不能救什麼 ★★★★★

```text
   ┌─────────────────────────────────────────────────────────────┐
   │  情境 A：改設定改壞了                                        │
   │  → ★★★★★ commit confirmed 完全能救。時間到自動回滾。        │
   ├─────────────────────────────────────────────────────────────┤
   │  情境 B：升級後新版本對某個設定的解讀不同，導致管理面斷掉    │
   │  → ★★★★★ commit confirmed 能救。升級後第一次調整設定時務必用。│
   ├─────────────────────────────────────────────────────────────┤
   │  情境 C：升級本身失敗，設備開不起來                          │
   │  → ★★★★★ commit confirmed 完全救不了（它是設定層的機制）。   │
   │     救你的是：雙分割區 + snapshot + console 線。             │
   ├─────────────────────────────────────────────────────────────┤
   │  情境 D：升級成功但新版有 bug，功能異常                      │
   │  → ★★★★★ commit confirmed 救不了。                          │
   │     救你的是：request system software rollback + reboot。    │
   └─────────────────────────────────────────────────────────────┘
```

★★★★★ **升級這件事需要三層保險，缺一不可**：

| 層級 | 機制 | 救得了什麼 |
| --- | --- | --- |
| 1. 設定層 | `commit confirmed` + `rollback` + `rescue` | 設定改壞 |
| 2. 系統層 | 雙分割區 + `request system snapshot` + `request system software rollback` | 韌體版本問題 |
| 3. 實體層 | ★★★★★ **console 線 + 有人到得了現場** | 上面兩層都失效時 |

★★★★★ **第 3 層是無法省略的。** 遠端升級交換器而現場沒有任何人可以接 console，
就是在賭「升級一定會成功」。機關的標準做法是：
**韌體升級一律安排在有人在場的時間，或至少確保 4 小時內有人到得了現場。**

## 環境準備與安裝

### 步驟 1：手動備份（每次變更前後都要做）★★★★★

```text
netadmin@sw> show configuration | display set | save /var/tmp/sw-20260902.set
Wrote 412 lines of output to '/var/tmp/sw-20260902.set'

netadmin@sw> file copy /var/tmp/sw-20260902.set scp://netadmin@10.99.0.5//backup/acc-3f-ex2300/
Password for netadmin@10.99.0.5:
/var/tmp/sw-20260902.set                      100%   18KB   4.1MB/s   00:00
```

★★★★★ **`scp://user@host//absolute/path` 要打兩條斜線**：
第一條分隔 host 與 path，第二條是絕對路徑的根。只打一條會寫到該使用者的家目錄底下。

★★★★ 其他常用的備份對象：

```text
netadmin@sw> show configuration | save /var/tmp/sw.conf
netadmin@sw> show interfaces descriptions | save /var/tmp/sw-ports.txt
netadmin@sw> show vlans | save /var/tmp/sw-vlans.txt
netadmin@sw> show ethernet-switching table | save /var/tmp/sw-mac.txt
netadmin@sw> show chassis hardware | save /var/tmp/sw-hw.txt
netadmin@sw> show version | save /var/tmp/sw-ver.txt
```

★★★★ `show chassis hardware`（序號）與 `show version` 這兩份特別重要：
報修 RMA、盤點、稽核都會用到。

### 步驟 2：rescue 設定 ★★★★★

```text
netadmin@sw> request system configuration rescue save

netadmin@sw> show system alarms
No alarms currently active

netadmin@sw> file list /config/
/config/:
juniper.conf.gz
juniper.conf.1.gz
juniper.conf.2.gz
juniper.conf.3.gz
rescue.conf.gz
...
```

★★★★★ **rescue 存的是「你現在確認好用的狀態」**。
`show system alarms` 裡的 `Rescue configuration is not set` 告警消失就是存成功了。

還原：

```text
netadmin@sw> configure exclusive
[edit]
netadmin@sw# rollback rescue
load complete
[edit]
netadmin@sw# show | compare
[edit]
netadmin@sw# commit confirmed 10
```

★★★★ 什麼時候該更新 rescue：
- ★★★★★ 每一次變更**驗證通過之後**
- 新設備建置完成、基準設定套完之後
- 韌體升級成功並驗證之後
- **不要**在剛改完還沒驗證時存 —— 那可能把壞的狀態存成「救援」

## 基礎設定

手動備份靠人記得，一定會漏。接下來把備份變成「不需要有人記得」的機制。

### 步驟 3：`system archival` 自動備份 ★★★★★

★★★★★ **這是本節最重要的設定。** 設好之後每次 commit 都自動把設定送到外部伺服器，
「忘記備份」這件事就不存在了。

```text
netadmin@sw> configure exclusive
[edit]
netadmin@sw# set system archival configuration transfer-on-commit
[edit]
netadmin@sw# set system archival configuration archive-sites "scp://backup@10.99.0.5:/backup/switches" password "請改成你們的密碼"
[edit]
netadmin@sw# show | compare
[edit system]
+   archival {
+       configuration {
+           transfer-on-commit;
+           archive-sites {
+               "scp://backup@10.99.0.5:/backup/switches" password "$9$..."; ## SECRET-DATA
+           }
+       }
+   }
[edit]
netadmin@sw# commit confirmed 10 comment "啟用設定自動備份"
commit complete
```

| 設定 | 意義 | 星級 |
| --- | --- | --- |
| `transfer-on-commit` | ★★★★★ **每次 commit 就傳一次**（建議） | ★★★★★ |
| `transfer-interval 1440` | 每 1440 分鐘（一天）傳一次 | ★★★ |
| `archive-sites "scp://user@host:/path"` | 目的地（可設多個，依序嘗試） | ★★★★★ |
| `password "..."` | SCP／FTP 的密碼（★★★★ 存成 `$9$`，**可逆，等同明文**） | ★★★★ |

★★★★★ 傳過去的檔名格式：

```bash
backup@backup-srv:~$ ls -l /backup/switches/
-rw-r--r-- 1 backup backup  4218 Sep  2 16:41 acc-3f-ex2300_juniper.conf.gz_20260902_164122
-rw-r--r-- 1 backup backup  4211 Sep  2 14:12 acc-3f-ex2300_juniper.conf.gz_20260902_141258
-rw-r--r-- 1 backup backup  8842 Sep  2 16:44 core-ex4300_juniper.conf.gz_20260902_164401
```

★★★★ **檔名自帶主機名稱與時間戳**，所以多台設備可以送到同一個目錄，不會互相蓋掉。

驗證（★★★★★ **一定要到備份伺服器上確認真的有檔案**，不能只看設備端沒報錯）：

```bash
backup@backup-srv:~$ ls -lt /backup/switches/ | head -3
-rw-r--r-- 1 backup backup 4218 Sep  2 16:41 acc-3f-ex2300_juniper.conf.gz_20260902_164122

backup@backup-srv:~$ zcat /backup/switches/acc-3f-ex2300_juniper.conf.gz_20260902_164122 | head -5
## Last commit: 2026-09-02 16:41:22 CST by netadmin
version 21.4R3-S5.4;
system {
    host-name acc-3f-ex2300;
```

> [!danger] ★★★★★ `archive-sites` 的密碼是 `$9$` 編碼，等同明文
> Junos 的 `$9$` 不是雜湊而是**可逆編碼**，網路上有現成解碼工具。
> 也就是說：**任何能讀到交換器設定備份的人，都拿得到你的備份伺服器帳密**。
>
> 對策（依安全性排序）：
> 1. ★★★★★ 備份伺服器上開一個**專用帳號**，權限只能寫入備份目錄，不能登入 shell
>    （`/usr/sbin/nologin` 或限制在 SFTP chroot，見 [[020-02-01-06-svc-SFTP-與受限使用者]]）
> 2. ★★★★ 該帳號**只能寫不能讀**（`chmod` 讓它無法列出／下載別台的備份）
> 3. ★★★★ 備份伺服器不對外，只在管理網段
> 4. ★★★ 定期輪替該密碼

> [!warning] ★★★★ 未實機驗證：`archive-sites` 的路徑格式
> `scp://user@host:/path` 中冒號後面的路徑寫法（相對／絕對）在不同 Junos 版本
> 曾有差異，部分版本也支援 `ftp://` 與 `http://`。
> 設好之後**一定要到備份伺服器實際確認檔案有進來**，
> 並故意做一次 commit 驗證自動傳輸真的觸發。

### 步驟 4：把備份納入版控 ★★★★

★★★★ 進階做法：備份伺服器上寫一支排程，把收到的設定檔轉成 `set` 格式並 `git commit`。

```bash
#!/bin/bash
# /usr/local/bin/switch-config-git.sh
# 把 Juniper archival 送來的設定檔整理進 git，每天跑一次
set -euo pipefail

INBOX=/backup/switches
REPO=/srv/netconfig
LOG=/var/log/switch-config-git.log

exec >>"$LOG" 2>&1
echo "=== $(date '+%F %T') 開始 ==="

cd "$REPO"

# 每台設備只保留「最新一份」在 repo 裡，歷史交給 git
for f in "$INBOX"/*_juniper.conf.gz_*; do
    [ -e "$f" ] || continue
    base=$(basename "$f")
    host=${base%%_juniper.conf.gz_*}
    mkdir -p "$REPO/$host"
    # 解壓成純文字，git 才 diff 得出來
    zcat "$f" > "$REPO/$host/juniper.conf"
done

if [[ -n "$(git status --porcelain)" ]]; then
    git add -A
    git commit -m "設定自動備份 $(date '+%F %T')"
    echo "已提交變更"
else
    echo "無變更"
fi

# 保留 inbox 90 天
find "$INBOX" -name '*_juniper.conf.gz_*' -mtime +90 -delete
echo "=== $(date '+%F %T') 完成 ==="
```

★★★★★ 好處：`git log` 就是完整的變更歷史，`git diff` 一眼看出誰在什麼時候改了什麼，
而且**跨設備、跨時間都查得到**。搭配 systemd timer 排程見
[[020-02-02-02-cmd-systemd-timer與cron選型]]。

★★★★ **備份最重要的一件事不是「有備份」，是「還原得回來」。**
每季至少做一次還原演練：拿一台測試設備，`load override` 某台正式設備的備份，
確認 `commit check` 通過。沒演練過的備份不算備份。

## 進階設定與調校

### 升級前的六項檢查 ★★★★★

> [!danger] ★★★★★ 這六項全部通過才可以動手，缺一項就停下來
> 韌體升級失敗的代價是設備變磚，而且往往發生在半夜、沒人在現場的時候。

**檢查 1：磁碟空間 ★★★★★**

```text
netadmin@sw> show system storage
Filesystem              Size       Used      Avail  Capacity   Mounted on
/dev/gpt/junos          2.9G       1.6G       1.1G       59%  /.mount
devfs                   1.0K       1.0K         0B      100%  /.mount/dev
/dev/gpt/config          92M       368K        84M        0%  /.mount/config
/dev/gpt/var            8.6G       1.2G       6.7G       15%  /.mount/var
```

★★★★★ **`/var` 至少要有韌體檔案 3 倍的空間**（要放安裝檔、解開的內容、備份）。
不夠就先清：

```text
netadmin@sw> request system storage cleanup dry-run
List of files to delete:

        Size Date          Name
      312.4M Jun 14 09:22  /var/tmp/junos-install-ex-x86-32-21.4R2.tgz
       11.2M Aug 03 11:02  /var/log/messages.0.gz
        4.1M Aug 10 03:00  /var/log/messages.1.gz
        1.0K Jul 03 11:02  /var/tmp/rtsdb/if-rtsdb

netadmin@sw> request system storage cleanup
List of files to delete:
...
Delete these files ? [yes,no] (no) yes
```

★★★★ `dry-run` 先看要刪什麼。★★★★★ 它會刪掉舊的日誌與暫存檔，
**如果那些日誌還有稽核價值，先 `file copy` 出去**。

**檢查 2：下載並驗證韌體檔案 ★★★★★**

```text
netadmin@sw> file copy scp://netadmin@10.99.0.5//images/junos-install-ex-x86-32-23.4R2-S3.tgz /var/tmp/
Password for netadmin@10.99.0.5:
junos-install-ex-x86-32-23.4R2-S3.tgz         100%  318MB  42.1MB/s   00:07

netadmin@sw> file checksum sha256 /var/tmp/junos-install-ex-x86-32-23.4R2-S3.tgz
SHA256 (/var/tmp/junos-install-ex-x86-32-23.4R2-S3.tgz) = 4f2a91c8e7b30d5a6218f4c09b7e3d1a85c6f209d34b7e81a0c92f5b6d1e4a73
```

★★★★★ **這個雜湊必須跟 Juniper 下載頁面公布的完全一致**。
不一致代表檔案下載不完整或被竄改 —— **絕對不要繼續**。
傳輸中斷造成的損壞檔案裝上去，設備就開不起來了。

**檢查 3：`validate` ★★★★★**

```text
netadmin@sw> request system software validate /var/tmp/junos-install-ex-x86-32-23.4R2-S3.tgz
Checking compatibility with configuration
Initializing...
Verified manifest signed by PackageProductionEc_2022 method ECDSA256+SHA256
Using junos-install-ex-x86-32-23.4R2-S3
Validating against /config/juniper.conf.gz
mgd: commit complete
Validation succeeded
```

★★★★★ **這一步會把你目前的設定拿去跟新版本做相容性檢查**。
新版本移除或改名的設定項，會在這裡被抓出來，而不是升級之後才發現「設定載不進去」。

失敗的樣子：

```text
Validating against /config/juniper.conf.gz
[edit protocols]
  'dot1x'
    warning: statement has been deprecated
[edit ethernet-switching-options]
  syntax error
mgd: configuration check-out failed
Validation failed
```

★★★★★ **驗證失敗就不要升級**。先在測試機上把設定調整成新版可接受的形式，
測試通過後再回到正式設備。

**檢查 4：設定備份與 rescue ★★★★★**

```text
netadmin@sw> show configuration | display set | save /var/tmp/pre-upgrade-20260902.set
netadmin@sw> file copy /var/tmp/pre-upgrade-20260902.set scp://netadmin@10.99.0.5//backup/acc-3f-ex2300/
netadmin@sw> request system configuration rescue save
```

**檢查 5：建立目前系統的 snapshot ★★★★★**

```text
netadmin@sw> show system snapshot media internal
Information for snapshot on       internal (/dev/da0s1a) (backup)
Creation date: Jun 14 09:41:22 2026
JUNOS version on snapshot:
  junos  : 21.4R2-domestic
Information for snapshot on       internal (/dev/da0s2a) (primary)
Creation date: Aug 25 10:12:41 2026
JUNOS version on snapshot:
  junos  : 21.4R3-S5.4-domestic
```

★★★★ 備援分割區還停留在更舊的 `21.4R2`。★★★★★ **升級前先把目前這個健康的版本
複製到備援分割區**，這樣升級失敗時可以退回到「你確定好用的那一版」：

```text
netadmin@sw> request system snapshot slice alternate
Formatting alternate root (/dev/da0s1a)...
Copying '/dev/da0s2a' to '/dev/da0s1a' .. (this may take a few minutes)
The following filesystems were archived: / /var

netadmin@sw> show system snapshot media internal
Information for snapshot on       internal (/dev/da0s1a) (backup)
Creation date: Sep 02 15:22:07 2026
JUNOS version on snapshot:
  junos  : 21.4R3-S5.4-domestic
Information for snapshot on       internal (/dev/da0s2a) (primary)
Creation date: Aug 25 10:12:41 2026
JUNOS version on snapshot:
  junos  : 21.4R3-S5.4-domestic
```

★★★★★ **兩個 slice 現在都是 21.4R3-S5.4** —— 升級失敗就從 alternate 開機回到這一版。

> [!warning] ★★★★ 未實機驗證：`request system snapshot` 的選項
> `slice alternate` / `media internal|usb` / `partition` / `recovery` 等選項的支援情況
> **依機型差異很大**。EX2300／EX3400 等較新的機種分割區配置與 EX4200／EX4300 不同，
> 部分機型的 `request system snapshot` 不接受 `slice` 參數。
> **升級前務必用 `request system snapshot ?` 確認**，並讀該機型的
> Software Installation and Upgrade Guide。

**檢查 6：時窗、人員與回退計畫 ★★★★★**

| 項目 | 要確認什麼 | 星級 |
| --- | --- | --- |
| 變更時窗 | 對服務影響最小的時段，已公告 | ★★★★★ |
| ★★★★★ 現場人員 | **有人到得了現場接 console**（或人就在現場） | ★★★★★ |
| 回退決策點 | 「幾點之前沒恢復就回退」寫清楚 | ★★★★★ |
| 回退步驟 | 已寫成逐條指令，不是「到時候再想」 | ★★★★★ |
| 通知名單 | 誰要知道、怎麼通知 | ★★★★ |
| 驗證清單 | 升級後要驗哪些項目，誰負責 | ★★★★ |
| 備品 | 同型號備援設備／console 線／USB 恢復碟 | ★★★★ |

★★★★ 完整的變更管理流程見 [[100-02-08-guide-維運-變更管理流程]] 與
[[080-03-04-guide-發布-上線檢查表與回退計畫]]。

### 執行升級 ★★★★★

```text
netadmin@sw> request system software add /var/tmp/junos-install-ex-x86-32-23.4R2-S3.tgz no-copy unlink reboot
```

| 選項 | 意義 | 星級 |
| --- | --- | --- |
| `no-copy` | ★★★★ 不再複製一份到安裝目錄（省磁碟空間，檔案已在 `/var/tmp`） | ★★★★ |
| `unlink` | ★★★★ 安裝完自動刪掉安裝檔（省空間） | ★★★★ |
| `reboot` | ★★★★★ 安裝完自動重開機 | ★★★★★ |
| `validate` / `no-validate` | 強制做／跳過設定相容性檢查（★★★★★ **不要用 `no-validate`**） | ★★★★★ |
| `partition` | 重新分割再安裝（★★★★★ **會清掉設定**，僅救援用） | ★★★★★ |
| `member <n>` | Virtual Chassis 指定成員 | ★★★ |

```text
Verified junos-install-ex-x86-32-23.4R2-S3 signed by PackageProductionEc_2022
  method ECDSA256+SHA256
Verified manifest signed by PackageProductionEc_2022 method ECDSA256+SHA256
Checking compatibility with configuration
Initializing...
Validating against /config/juniper.conf.gz
mgd: commit complete
Validation succeeded
Saving state for rollback ...
Installing package '/var/tmp/junos-install-ex-x86-32-23.4R2-S3.tgz' ...
Verified junos-install-ex-x86-32-23.4R2-S3.tgz
Extracting junos-install-ex-x86-32-23.4R2-S3 ...
...
Rebooting ...
```

★★★★★ **重開機大約 5～15 分鐘（依機型）**。這段時間：
- 交換器完全不轉發流量 —— **接在上面的所有裝置都斷網**
- SSH 連線會斷
- 不要拔電源、不要重複下指令

★★★★ 從 console 可以看到完整的開機過程；只有 SSH 的話就是等待，
用 `ping` 監看什麼時候回來：

```bash
$ ping 10.99.0.11
PING 10.99.0.11 (10.99.0.11) 56(84) bytes of data.
From 10.99.1.5 icmp_seq=1 Destination Host Unreachable
... (約 8 分鐘) ...
64 bytes from 10.99.0.11: icmp_seq=487 ttl=64 time=1.02 ms
```

### 升級後的八項驗證 ★★★★★

```text
netadmin@sw> show version | match "Model|Junos:"
Model: ex4300-48t
Junos: 23.4R2-S3
```

| # | 驗證項 | 指令 | 通過標準 | 星級 |
| --- | --- | --- | --- | --- |
| 1 | 版本正確 | `show version` | 是你要升的那一版 | ★★★★★ |
| 2 | 無系統告警 | `show system alarms` / `show chassis alarms` | ★★★★★ 特別注意 `Boot from backup root` | ★★★★★ |
| 3 | 硬體完整 | `show chassis hardware` | 電源、風扇、介面卡都在 | ★★★★★ |
| 4 | 設定完整載入 | `show configuration \| display set \| count` | ★★★★★ 行數與 pre-upgrade 備份一致 | ★★★★★ |
| 5 | 介面狀態 | `show interfaces terse` | 該 up 的都 up，數量對得上 | ★★★★★ |
| 6 | VLAN 與 MAC | `show vlans` / `show ethernet-switching table` | 成員正確、MAC 學得到 | ★★★★★ |
| 7 | 管理面 | 新開一條 SSH、`show route 0.0.0.0/0`、syslog 有進來 | 都正常 | ★★★★★ |
| 8 | 使用者實測 | 抽測 PC／AP／印表機／伺服器 | 服務正常 | ★★★★★ |

★★★★★ **第 4 項是最容易被忽略也最危險的**：

```text
netadmin@sw> show configuration | display set | count
Count: 405 lines
```

★★★★★ pre-upgrade 是 412 行，現在是 405 行 —— **少了 7 行**。
新版本可能移除或改名了某些設定項，而 JunOS 在升級時會**默默丟掉不認識的設定**。
一定要 diff 出來看是哪 7 行：

```bash
$ diff pre-upgrade-20260902.set post-upgrade-20260902.set
< set protocols dot1x authenticator interface ge-0/0/1.0 supplicant single-secure
< set ethernet-switching-options storm-control interface all level 3
...
```

★★★★★ 少掉的通常是被 deprecated 的語法。**要立刻用新語法補回來**，
否則你以為有的保護其實已經不在了 —— 這種問題不會有任何告警。

```text
netadmin@sw> show system alarms
No alarms currently active

netadmin@sw> show system snapshot media internal
Information for snapshot on       internal (/dev/da0s1a) (backup)
Creation date: Sep 02 15:22:07 2026
JUNOS version on snapshot:
  junos  : 21.4R3-S5.4-domestic
Information for snapshot on       internal (/dev/da0s2a) (primary)
Creation date: Sep 02 16:04:51 2026
JUNOS version on snapshot:
  junos  : 23.4R2-S3-domestic
```

★★★★★ **backup 是舊版、primary 是新版** —— 這正是你要的狀態。
**在確認新版穩定跑一段時間（建議至少一週）之前，不要對備援分割區做 snapshot**，
那份舊版就是你的退路。

### 回退：升級後發現有問題 ★★★★★

**情況 A：設定層的問題（新版對某設定的解讀不同）**

```text
netadmin@sw> configure exclusive
[edit]
netadmin@sw# rollback 1
[edit]
netadmin@sw# show | compare
[edit]
netadmin@sw# commit confirmed 10
```

**情況 B：韌體本身的問題，要退回舊版 ★★★★★**

```text
netadmin@sw> request system software rollback
Restoring boot file package
Junos version '21.4R3-S5.4' will become active at next reboot
WARNING: A reboot is required to load this software correctly
WARNING:     Use the 'request system reboot' command
WARNING:         when software installation is complete

netadmin@sw> request system reboot
Reboot the system ? [yes,no] (no) yes
```

★★★★★ 重開後確認：

```text
netadmin@sw> show version | match Junos:
Junos: 21.4R3-S5.4
```

> [!danger] ★★★★★ `request system software rollback` 不是萬能的
> 它依賴設備上還保留著「上一個版本的安裝狀態」。以下情況會失敗：
> - 用了 `unlink` 且系統已清掉舊版的還原資料
> - 中間又做了 `request system snapshot`，把備援分割區蓋成新版
> - 儲存空間不足導致還原資料沒被保留
> - 跨太多版本的升級（例如 15.1 直接升 23.4）
>
> ★★★★★ **所以「升級前先 snapshot 到 alternate slice」不能省** ——
> 那才是真正保證退得回去的做法。`software rollback` 失敗時的最後手段是：
> ```text
> netadmin@sw> request system reboot slice alternate
> ```
> 從備援分割區開機（★★★★ 這需要 console 或設備還連得上）。

**情況 C：設備開不起來 ★★★★★**

只能接 console 線，在開機時中斷進入 loader，從備援分割區開機或用 USB 恢復。
★★★★★ **這一段的實際按鍵與步驟依機型不同，必須查該機型的手冊**，
不要在正式環境現場摸索。

### Virtual Chassis 的升級 ★★★

```text
netadmin@vc> show virtual-chassis
Virtual Chassis ID: 0019.e250.47c0
                                           Mstr           Mixed Route
Member ID  Status   Serial No    Model      prio  Role      Mode  Mode
0 (FPC 0)  Prsnt    PE3721480001 ex4300-48t 129   Master*   N     VC
1 (FPC 1)  Prsnt    PE3721480002 ex4300-48t 129   Backup    N     VC
2 (FPC 2)  Prsnt    PE3721480003 ex4300-48t 0     Linecard  N     VC
```

★★★★ Virtual Chassis 升級的兩種方式：

| 方式 | 指令 | 中斷時間 | 星級 |
| --- | --- | --- | --- |
| 一般升級（全部一起重開） | `request system software add ... reboot` | ★★★★★ 整個 VC 全斷（5～15 分鐘） | ★★★★★ |
| NSSU（Nonstop Software Upgrade） | `request system software nonstop-upgrade /var/tmp/x.tgz` | ★★★ 逐台重開，中斷很短 | ★★★ |

> [!warning] ★★★★ 未實機驗證：NSSU 有很多前提條件
> NSSU 需要：VC 設定正確、機型與版本支援、開啟 GRES／NSR、
> 而且**跨主要版本升級通常不支援 NSSU**。
> 前提沒滿足時 NSSU 會中途失敗，情況比一般升級更難處理。
> 導入前務必讀該版本的 NSSU 文件與 Release Notes，並在測試 VC 上驗證。
> ★★★★ 機關環境若有安排維護時窗，**一般升級（全部一起重開）反而更單純可控**。

### 定期健康檢查 ★★★★

★★★★ 排進每月維護（[[100-02-04-guide-維運-每月維護作業]]）：

```text
netadmin@sw> show version
netadmin@sw> show system alarms
netadmin@sw> show chassis alarms
netadmin@sw> show chassis hardware
netadmin@sw> show system storage
netadmin@sw> show system snapshot media internal
netadmin@sw> show system uptime
netadmin@sw> show system commit | last 10
netadmin@sw> show interfaces extensive | match "Physical interface|CRC/Align" | no-more
```

★★★★★ **要 TAC 報修時，一次抓齊所有資訊**：

```text
netadmin@sw> request support information | save /var/tmp/rsi-20260902.txt
netadmin@sw> file copy /var/tmp/rsi-20260902.txt scp://netadmin@10.99.0.5//support/
```

★★★★ `request support information` 會收集版本、設定、硬體、日誌、各種狀態 ——
這是開 TAC case 時的第一份附件，先附上可以省掉一輪來回。

> [!info]- Cisco IOS 對照（簡表，完整內容見 [[040-01-14-svc-Cisco-設定備份與韌體升級]]）
> | 目的 | JunOS | Cisco IOS |
> | --- | --- | --- |
> | 備份設定到外部 | `file copy /var/tmp/x.set scp://u@h//path/` | `copy running-config scp:` / `tftp:` |
> | 自動備份 | ★★★★★ `set system archival configuration transfer-on-commit` | `archive` + `path` + `write-memory` |
> | 存救援設定 | `request system configuration rescue save` | `archive config` |
> | 還原設定 | `load override` / `load set` + `commit` | `configure replace flash:backup force` |
> | 看磁碟空間 | `show system storage` | `dir flash:` / `show file systems` |
> | 清空間 | `request system storage cleanup` | `delete flash:...` |
> | 檔案雜湊 | `file checksum sha256 <file>` | `verify /md5 flash:...` |
> | 升級前驗證 | ★★★★★ `request system software validate <file>` | ★ 無等價功能 |
> | 安裝韌體 | `request system software add <file> reboot` | `copy tftp: flash:` + `boot system flash:...` |
> | 雙分割區／快照 | ★★★★★ `request system snapshot slice alternate` | ★★★ 多映像檔 + `boot system` 順序 |
> | 退回舊版 | `request system software rollback` + reboot | 改 `boot system` 順序 + `reload` |
> | 從備援開機 | `request system reboot slice alternate` | ROMMON 手動指定映像 |
> | 收集報修資訊 | `request support information` | `show tech-support` |
>
> ★★★★★ 最大差異：**JunOS 有 `validate`（升級前先驗證設定相容性）與雙分割區**，
> 這兩項讓 Juniper 的升級比 Cisco 安全不少。
> 完整對照見 [[040-01-15-cmd-網路設備-Juniper與Cisco指令對照]]。

## 完整實戰範例

**情境**：機關收到 Juniper 安全公告，目前的 `21.4R3-S5.4` 有一個高風險漏洞，
需要升級到 `23.4R2-S3`。對象是 3F 接取交換器 `acc-3f-ex2300`（10.99.0.11）。
變更時窗是週六上午 08:00～12:00，你人在機房、console 線已接好。

### 步驟 0：升級前一週的準備 ★★★★

| 項目 | 內容 |
| --- | --- |
| 讀 Release Notes | `23.4R2-S3` 的 Known Issues 有沒有影響你用到的功能 |
| 查 JTAC Recommended | 確認 `23.4R2-S3` 在建議清單上 |
| 下載韌體與雜湊值 | 從 Juniper 支援網站下載，記下官方公布的 SHA256 |
| 測試機驗證 | ★★★★★ 同型號測試機完整走一遍，記下實際耗時 |
| 變更單 | 時窗、影響範圍、回退決策點（10:00）、通知名單 |
| 公告 | ★★★★ 3F 使用者週六 08:00～10:00 網路中斷 |
| 現場準備 | console 線、筆電、USB 恢復碟、備援交換器 |

### 步驟 1：08:00 動手前的完整快照 ★★★★★

```text
netadmin@acc-3f-ex2300> set cli screen-length 0
netadmin@acc-3f-ex2300> set cli timestamp
Sep 06 08:02:11
CLI timestamp set to: %b %d %T

netadmin@acc-3f-ex2300> show version | save /var/tmp/pre-version.txt
netadmin@acc-3f-ex2300> show chassis hardware | save /var/tmp/pre-hw.txt
netadmin@acc-3f-ex2300> show system alarms | save /var/tmp/pre-alarms.txt
netadmin@acc-3f-ex2300> show interfaces terse | save /var/tmp/pre-terse.txt
netadmin@acc-3f-ex2300> show interfaces descriptions | save /var/tmp/pre-desc.txt
netadmin@acc-3f-ex2300> show vlans | save /var/tmp/pre-vlans.txt
netadmin@acc-3f-ex2300> show ethernet-switching table | save /var/tmp/pre-mac.txt
netadmin@acc-3f-ex2300> show route | save /var/tmp/pre-route.txt
netadmin@acc-3f-ex2300> show configuration | display set | save /var/tmp/pre-upgrade.set

netadmin@acc-3f-ex2300> show configuration | display set | count
Sep 06 08:04:02
Count: 412 lines
```

★★★★★ **把 412 這個數字記下來** —— 升級後要對照。

```text
netadmin@acc-3f-ex2300> file copy /var/tmp/pre-upgrade.set scp://netadmin@10.99.0.5//backup/acc-3f-ex2300/20260906/
Password for netadmin@10.99.0.5:
/var/tmp/pre-upgrade.set                      100%   18KB   4.1MB/s   00:00

netadmin@acc-3f-ex2300> request system configuration rescue save
Sep 06 08:05:14

netadmin@acc-3f-ex2300> show system alarms
Sep 06 08:05:20
No alarms currently active
```

★★★★★ **升級前系統必須是「零告警」的狀態**。有告警就先處理完再升級 ——
帶著問題升級，之後你分不清哪些問題是升級造成的。

### 步驟 2：磁碟空間 ★★★★★

```text
netadmin@acc-3f-ex2300> show system storage
Sep 06 08:06:41
Filesystem              Size       Used      Avail  Capacity   Mounted on
/dev/gpt/junos          2.9G       1.6G       1.1G       59%  /.mount
/dev/gpt/config          92M       412K        84M        0%  /.mount/config
/dev/gpt/var            8.6G       2.9G       5.0G       36%  /.mount/var

netadmin@acc-3f-ex2300> request system storage cleanup dry-run
Sep 06 08:07:02
List of files to delete:

        Size Date          Name
      312.4M Jun 14 09:22  /var/tmp/junos-install-ex-x86-32-21.4R2.tgz
       11.2M Aug 03 11:02  /var/log/messages.0.gz
        4.1M Aug 10 03:00  /var/log/messages.1.gz
```

★★★★ 那兩份 `messages` 日誌先帶走再刪：

```text
netadmin@acc-3f-ex2300> file copy /var/log/messages.0.gz scp://netadmin@10.99.0.5//backup/acc-3f-ex2300/logs/
netadmin@acc-3f-ex2300> file copy /var/log/messages.1.gz scp://netadmin@10.99.0.5//backup/acc-3f-ex2300/logs/

netadmin@acc-3f-ex2300> request system storage cleanup
Delete these files ? [yes,no] (no) yes

netadmin@acc-3f-ex2300> show system storage | match var
/dev/gpt/var            8.6G       2.5G       5.4G       31%  /.mount/var
```

★★★★★ 5.4G 可用，韌體檔 318MB —— 空間充足。

### 步驟 3：下載並驗證韌體 ★★★★★

```text
netadmin@acc-3f-ex2300> file copy scp://netadmin@10.99.0.5//images/junos-install-ex-x86-32-23.4R2-S3.tgz /var/tmp/
Password for netadmin@10.99.0.5:
junos-install-ex-x86-32-23.4R2-S3.tgz         100%  318MB  38.2MB/s   00:08

netadmin@acc-3f-ex2300> file checksum sha256 /var/tmp/junos-install-ex-x86-32-23.4R2-S3.tgz
Sep 06 08:12:44
SHA256 (/var/tmp/junos-install-ex-x86-32-23.4R2-S3.tgz) =
  4f2a91c8e7b30d5a6218f4c09b7e3d1a85c6f209d34b7e81a0c92f5b6d1e4a73
```

★★★★★ 與 Juniper 網站公布的雜湊逐字比對 —— **完全一致才繼續**。

### 步驟 4：`validate` ★★★★★

```text
netadmin@acc-3f-ex2300> request system software validate /var/tmp/junos-install-ex-x86-32-23.4R2-S3.tgz
Sep 06 08:14:07
Checking compatibility with configuration
Initializing...
Verified manifest signed by PackageProductionEc_2022 method ECDSA256+SHA256
Using junos-install-ex-x86-32-23.4R2-S3
Validating against /config/juniper.conf.gz
mgd: commit complete
Validation succeeded
```

★★★★★ `Validation succeeded` —— 設定與新版相容。

### 步驟 5：snapshot 到備援分割區 ★★★★★

```text
netadmin@acc-3f-ex2300> show system snapshot media internal
Sep 06 08:16:22
Information for snapshot on       internal (/dev/da0s1a) (backup)
Creation date: Jun 14 09:41:22 2026
JUNOS version on snapshot:
  junos  : 21.4R2-domestic
Information for snapshot on       internal (/dev/da0s2a) (primary)
Creation date: Aug 25 10:12:41 2026
JUNOS version on snapshot:
  junos  : 21.4R3-S5.4-domestic

netadmin@acc-3f-ex2300> request system snapshot slice alternate
Sep 06 08:17:03
Formatting alternate root (/dev/da0s1a)...
Copying '/dev/da0s2a' to '/dev/da0s1a' .. (this may take a few minutes)
The following filesystems were archived: / /var

netadmin@acc-3f-ex2300> show system snapshot media internal
Sep 06 08:21:48
Information for snapshot on       internal (/dev/da0s1a) (backup)
Creation date: Sep 06 08:17:41 2026
JUNOS version on snapshot:
  junos  : 21.4R3-S5.4-domestic
Information for snapshot on       internal (/dev/da0s2a) (primary)
Creation date: Aug 25 10:12:41 2026
JUNOS version on snapshot:
  junos  : 21.4R3-S5.4-domestic
```

★★★★★ **兩個 slice 都是 21.4R3-S5.4** —— 退路準備好了。

### 步驟 6：08:25 執行升級 ★★★★★

```text
netadmin@acc-3f-ex2300> request system software add /var/tmp/junos-install-ex-x86-32-23.4R2-S3.tgz no-copy unlink reboot
Sep 06 08:25:11
Verified junos-install-ex-x86-32-23.4R2-S3 signed by PackageProductionEc_2022
  method ECDSA256+SHA256
Checking compatibility with configuration
Initializing...
Validating against /config/juniper.conf.gz
mgd: commit complete
Validation succeeded
Saving state for rollback ...
Installing package '/var/tmp/junos-install-ex-x86-32-23.4R2-S3.tgz' ...
Extracting junos-install-ex-x86-32-23.4R2-S3 ...
...
Rebooting ...

*** FINAL System shutdown message from netadmin@acc-3f-ex2300 ***
System going down IMMEDIATELY
```

★★★★ 從管理站監看什麼時候回來：

```bash
$ ping 10.99.0.11
PING 10.99.0.11 (10.99.0.11) 56(84) bytes of data.
From 10.99.1.5 icmp_seq=1 Destination Host Unreachable
... (等待中) ...
64 bytes from 10.99.0.11: icmp_seq=512 ttl=64 time=1.14 ms
```

★★★★ 大約 08:34 回來，實際耗時 9 分鐘（與測試機的紀錄相符）。

### 步驟 7：08:35 升級後八項驗證 ★★★★★

```text
netadmin@acc-3f-ex2300> show version | match "Model|Junos:"
Sep 06 08:35:41
Model: ex2300-48t
Junos: 23.4R2-S3
```

★★★★★ **① 版本正確。**

```text
netadmin@acc-3f-ex2300> show system alarms
Sep 06 08:36:02
No alarms currently active

netadmin@acc-3f-ex2300> show chassis alarms
No alarms currently active
```

★★★★★ **② 零告警**（特別確認沒有 `Boot from backup root`）。

```text
netadmin@acc-3f-ex2300> show chassis hardware
Hardware inventory:
Item             Version  Part number  Serial number     Description
Chassis                                PE3721480001      EX2300-48T
Routing Engine 0 REV 09   650-000000   BUILTIN           RE-EX2300-48T
FPC 0            REV 09   650-000000   BUILTIN           EX2300-48T
  PIC 0                   BUILTIN      BUILTIN           48x10/100/1000 Base-T
  PIC 1                   BUILTIN      BUILTIN           4x10G SFP+
Power Supply 0
```

★★★★★ **③ 硬體與 pre-hw.txt 一致。**

```text
netadmin@acc-3f-ex2300> show configuration | display set | count
Sep 06 08:37:14
Count: 409 lines
```

★★★★★ **④ 少了 3 行！** 立刻導出來比對：

```text
netadmin@acc-3f-ex2300> show configuration | display set | save /var/tmp/post-upgrade.set
netadmin@acc-3f-ex2300> file copy /var/tmp/post-upgrade.set scp://netadmin@10.99.0.5//backup/acc-3f-ex2300/20260906/
```

```bash
$ diff pre-upgrade.set post-upgrade.set
150,152d149
< set protocols layer2-control bpdu-block disable-timeout 300
< set protocols rstp bpdu-block-on-edge
< set forwarding-options storm-control-profiles SC-ACCESS all no-unknown-unicast
```

★★★★★ 三項保護設定被新版丟掉了。查 Release Notes 確認新版的對應語法後補回來
（這一步就是為什麼要對照行數）。

```text
netadmin@acc-3f-ex2300> show interfaces terse | match "up    up" | count
Sep 06 08:41:22
Count: 42 lines
```

★★★★★ **⑤ 42 個埠 up，與 pre-terse.txt 一致。**

```text
netadmin@acc-3f-ex2300> show vlans
Routing instance        VLAN name             Tag       Interfaces
default-switch          MGMT                  99
                                                        ge-0/0/48.0*
default-switch          OFFICE                10
                                                        ge-0/0/1.0*
                                                        ...
netadmin@acc-3f-ex2300> show ethernet-switching table | count
Count: 23 lines
```

★★★★★ **⑥ VLAN 成員正確、MAC 學得到（23 筆，與 pre-mac.txt 相符）。**

```text
netadmin@acc-3f-ex2300> show route 0.0.0.0/0
inet.0: 6 destinations, 6 routes (6 active, 0 holddown, 0 hidden)
0.0.0.0/0          *[Static/5] 00:07:12
                    >  to 10.99.0.1 via irb.99
```

從管理站新開一條 SSH：

```bash
$ ssh netadmin@10.99.0.11
netadmin@acc-3f-ex2300>
```

到 syslog 伺服器確認有收到這台的新訊息：

```bash
$ tail -3 /var/log/network/acc-3f-ex2300.log
Sep  6 08:35:12 acc-3f-ex2300 /kernel: Copyright (c) 1996-2026, Juniper Networks, Inc.
Sep  6 08:36:41 acc-3f-ex2300 mgd[4102]: UI_LOGIN_EVENT: User 'netadmin' login, class 'super-user'
```

★★★★★ **⑦ 管理面全部正常。**

★★★★★ **⑧ 使用者實測**（請值班同仁到 3F）：

| 測試 | 結果 |
| --- | --- |
| 辦公 PC 上網 | 通 |
| 會議室 AP 無線 | 通 |
| 影印室印表機列印測試頁 | 通 |
| 停用的網路孔插線 | 無反應（正確） |

### 步驟 8：08:50 補回被丟掉的設定 ★★★★★

```text
netadmin@acc-3f-ex2300> configure exclusive
[edit]
netadmin@acc-3f-ex2300# set protocols rstp bpdu-block-on-edge
[edit]
netadmin@acc-3f-ex2300# set protocols layer2-control bpdu-block disable-timeout 300
[edit]
netadmin@acc-3f-ex2300# set forwarding-options storm-control-profiles SC-ACCESS all no-unknown-unicast
[edit]
netadmin@acc-3f-ex2300# show | compare
[edit protocols]
+   rstp {
+       bpdu-block-on-edge;
+   }
+   layer2-control {
+       bpdu-block {
+           disable-timeout 300;
+       }
+   }
[edit forwarding-options storm-control-profiles SC-ACCESS all]
+     no-unknown-unicast;
[edit]
netadmin@acc-3f-ex2300# commit check
configuration check succeeds
[edit]
netadmin@acc-3f-ex2300# commit confirmed 10 comment "CR-0906 升級後補回三項保護設定"
commit confirmed will be automatically rolled back in 10 minutes unless confirmed
commit complete
```

★★★★★ **升級後的第一次設定變更一定要用 `commit confirmed`** ——
新版本對設定的解讀可能不同，這是最容易出事的時刻。

```text
[edit]
netadmin@acc-3f-ex2300# run show configuration | display set | count
Count: 412 lines
[edit]
netadmin@acc-3f-ex2300# commit comment "CR-0906 行數已回到 412，驗證通過"
commit complete
```

★★★★★ **412 行，與升級前完全一致。**

### 步驟 9：09:10 收尾 ★★★★

```text
netadmin@acc-3f-ex2300> request system configuration rescue save

netadmin@acc-3f-ex2300> show configuration | display set | save /var/tmp/final-20260906.set
netadmin@acc-3f-ex2300> file copy /var/tmp/final-20260906.set scp://netadmin@10.99.0.5//backup/acc-3f-ex2300/20260906/

netadmin@acc-3f-ex2300> show system snapshot media internal
Information for snapshot on       internal (/dev/da0s1a) (backup)
Creation date: Sep 06 08:17:41 2026
JUNOS version on snapshot:
  junos  : 21.4R3-S5.4-domestic
Information for snapshot on       internal (/dev/da0s2a) (primary)
Creation date: Sep 06 08:33:12 2026
JUNOS version on snapshot:
  junos  : 23.4R2-S3-domestic
```

★★★★★ **備援分割區保留舊版 21.4R3-S5.4。**
★★★★★ **接下來一週不要對備援分割區做 snapshot** —— 那是你的退路。
一週後新版確認穩定，再跑 `request system snapshot slice alternate` 讓兩份都是新版。

更新文件：資產清單的韌體版本欄、變更單結案、通知使用者已恢復。

### 升級 SOP 檢查表 ★★★★★

| 階段 | # | 項目 | 星級 |
| --- | --- | --- | --- |
| 前期 | 1 | 讀 Release Notes 的 Known Issues | ★★★★ |
| 前期 | 2 | 確認目標版本在 JTAC Recommended 清單上、是 EEOL | ★★★★★ |
| 前期 | 3 | 同型號測試機完整演練，記錄耗時 | ★★★★★ |
| 前期 | 4 | 變更單含回退決策點與逐條回退步驟 | ★★★★★ |
| 前期 | 5 | ★★★★★ **確認有人到得了現場接 console** | ★★★★★ |
| 當日 | 6 | `show system alarms` 為零告警 | ★★★★★ |
| 當日 | 7 | 完整快照（版本／硬體／介面／VLAN／MAC／路由／設定） | ★★★★★ |
| 當日 | 8 | 記下 `show configuration \| display set \| count` 的行數 | ★★★★★ |
| 當日 | 9 | 設定備份已送到外部伺服器 | ★★★★★ |
| 當日 | 10 | `request system configuration rescue save` | ★★★★★ |
| 當日 | 11 | `show system storage` 空間足夠（韌體檔 3 倍） | ★★★★★ |
| 當日 | 12 | `file checksum sha256` 與官方公布值一致 | ★★★★★ |
| 當日 | 13 | `request system software validate` 通過 | ★★★★★ |
| 當日 | 14 | `request system snapshot slice alternate`（保留舊版退路） | ★★★★★ |
| 升級 | 15 | `request system software add ... reboot` | ★★★★★ |
| 驗證 | 16 | 版本正確 | ★★★★★ |
| 驗證 | 17 | 零告警（特別是 `Boot from backup root`） | ★★★★★ |
| 驗證 | 18 | 硬體清單一致 | ★★★★★ |
| 驗證 | 19 | ★★★★★ **設定行數一致**，不一致就 diff 並補回 | ★★★★★ |
| 驗證 | 20 | 介面 up 數量一致 | ★★★★★ |
| 驗證 | 21 | VLAN 成員與 MAC 表正常 | ★★★★★ |
| 驗證 | 22 | 新開 SSH 成功、路由正常、syslog 有進來 | ★★★★★ |
| 驗證 | 23 | 使用者實測（PC／AP／印表機／伺服器） | ★★★★★ |
| 收尾 | 24 | 補回被丟掉的設定（用 `commit confirmed`） | ★★★★★ |
| 收尾 | 25 | 重存 rescue、備份新設定 | ★★★★★ |
| 收尾 | 26 | ★★★★★ **一週內不要 snapshot 備援分割區** | ★★★★★ |
| 收尾 | 27 | 更新資產清單的版本欄、變更單結案 | ★★★★ |

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 升級後設備開不起來，console 停在 loader | 韌體檔案損壞（雜湊沒驗）、磁碟空間不足導致安裝不完整、電源中斷 | console 進 loader，從備援分割區開機或用 USB 恢復（★★★★★ 步驟依機型，查手冊）。★★★★★ 預防：升級前 `file checksum` + `validate` + `snapshot` |
| ★★★★★ 升級成功但設定少了幾行，某些保護功能失效 | 新版移除或改名了某些設定項，JunOS 升級時默默丟掉不認識的設定 | ★★★★★ 用 `show configuration \| display set \| count` 對照行數，`diff` 找出少了什麼，查 Release Notes 用新語法補回 |
| ★★★★★ `show system alarms` 出現 `Host 0 Boot from backup root` | 主分割區損壞，現在跑的是備援 | `request system snapshot` 修復主分割區；反覆失敗代表儲存媒體實體損壞，準備報修 |
| ★★★★★ `request system software rollback` 說沒有可回退的版本 | 用了 `unlink`、或中間做過 snapshot 把備援蓋掉、或空間不足 | `request system reboot slice alternate` 從備援分割區開機。★★★★★ 預防：升級前一定要 snapshot |
| ★★★★ `request system software add` 失敗：磁碟空間不足 | `/var` 滿了 | `request system storage cleanup`（先把有用的日誌 `file copy` 出去）；必要時 `file delete` 舊映像檔 |
| ★★★★ `validate` 失敗：`statement has been deprecated` | 目前設定用了新版不支援的語法 | ★★★★★ **不要繼續升級**。先在測試機把設定改成新版可接受的形式 |
| ★★★★ `file checksum` 與官方值不符 | 下載不完整、傳輸中斷、來源不可信 | 重新下載並重新驗證。★★★★★ **絕對不要用雜湊不符的檔案升級** |
| ★★★★ `archival` 設好了但備份伺服器沒收到檔案 | 路徑格式錯、密碼錯、SSH 金鑰不接受、防火牆擋、目錄權限不足 | `show log messages \| match "archive\|transfer"` 看錯誤；在備份伺服器 `tcpdump` 確認有無連線；手動 `file copy` 測同一組帳密 |
| ★★★★ `file copy` 到 SCP 檔案跑到奇怪的位置 | `scp://user@host/path` 只打一條斜線 = 相對於家目錄 | 絕對路徑要打**兩條**：`scp://user@host//backup/x.set` |
| ★★★★ 升級後 SSH 連不上但 ping 得到 | 新版對 SSH 演算法／`lo0` filter 的解讀不同 | console 進入，`show configuration system services ssh`；★★★★ 檢查 `show firewall filter PROTECT-RE` 的 deny 計數 |
| ★★★ `rollback rescue` 之後設定跟預期不同 | rescue 是很久以前存的 | `show system commit` 對照；★★★★ 每次變更驗證後都要重存 rescue |
| ★★★ 升級耗時遠超過測試機的紀錄 | 機型不同、儲存媒體老化、`no-copy` 沒用造成多一次複製 | 耐心等（**不要拔電源**）；超過 30 分鐘完全沒動靜才考慮介入 |
| ★★★ Virtual Chassis 升級後某個成員版本不同 | 該成員升級失敗或沒被包含 | `show virtual-chassis` + `show version invoke-on all-routing-engines`；對該成員單獨 `request system software add ... member N` |
| ★★★ NSSU 中途失敗，VC 處於混合版本狀態 | 前提條件沒滿足（GRES／NSR 沒開、跨主要版本） | ★★★★ 情況比一般升級難處理。改用一般升級（全部一起重開） |
| ★★★ 備份檔還原到新設備後 `commit check` 失敗 | 備份含該設備專屬的設定（序號綁定、憑證、VC 成員 ID） | 逐項排除設備專屬設定；換機流程見 [[040-01-19-guide-網路設備-交換器汰換與遷移實務]] |
| ★★ `request system storage cleanup` 刪掉了還要用的日誌 | 沒先 `dry-run` | ★★★★ 先 `dry-run`，把有稽核價值的日誌 `file copy` 出去再刪 |

### 排查步驟

**【1】升級後第一件事：確認版本與告警 ★★★★★**

```text
netadmin@sw> show version | match Junos:
Junos: 23.4R2-S3

netadmin@sw> show system alarms
1 alarms currently active
Alarm time               Class  Description
2026-09-06 08:34:12 CST  Minor  Host 0 Boot from backup root
```

★★★★★ 看到 `Boot from backup root` 代表**主分割區有問題，現在跑的是備援**。
先確認 `show version` 顯示的是哪一版：
- 顯示**舊版** → 升級沒成功，設備 fallback 到備援了
- 顯示**新版** → 升級成功但主分割區有損傷，跑 `request system snapshot` 修復

**【2】設定有沒有完整載入 ★★★★★**

```text
netadmin@sw> show configuration | display set | count
Count: 409 lines
```

跟升級前的行數不一樣 → 導出來 `diff`：

```bash
$ diff pre-upgrade.set post-upgrade.set
```

★★★★★ **每一行差異都要解釋得出來**。查 Release Notes 的
"Changes in Behavior and Syntax" 章節，找到新版的對應寫法補回去。

**【3】介面與二層 ★★★★**

```text
netadmin@sw> show interfaces terse | match "up    up" | count
Count: 42 lines

netadmin@sw> show ethernet-switching table | count
Count: 23 lines

netadmin@sw> show vlans
```

數字對得上就過。少了 → 對照 `pre-terse.txt` 找出是哪個埠。

**【4】管理面 ★★★★★**

```text
netadmin@sw> show route 0.0.0.0/0
netadmin@sw> show configuration system services
netadmin@sw> show firewall filter PROTECT-RE
```

★★★★★ 從管理站**新開一條 SSH**（不要只靠既有連線），並到 syslog 伺服器確認有新訊息進來。

**【5】需要回退時的決策 ★★★★★**

```text
   問題在哪一層？
     │
     ├─ 設定層（某個設定行為變了）
     │    → rollback 1 + commit confirmed，或補上新版語法
     │
     ├─ 韌體層（功能異常、效能異常、bug）
     │    → request system software rollback + request system reboot
     │       失敗的話 → request system reboot slice alternate
     │
     └─ 系統層（開不起來）
          → console → loader → 從備援分割區開機 → USB 恢復
```

★★★★★ **決策點要在變更單裡事先寫好**，例如「10:00 前沒恢復服務就執行回退」。
★★★★ 現場臨時判斷會傾向「再試一下就好」，那正是把 4 小時時窗用光的原因。
原則見 [[100-02-10-guide-維運-故障排除方法論]]。

**【6】自動備份沒運作 ★★★★**

```text
netadmin@sw> show log messages | match -i "archive|transfer|scp" | last 20
Sep  6 08:41:22  sw cfmd[3812]: Transfer file to scp://backup@10.99.0.5:/backup/switches failed
```

★★★★ 依序查：
1. 手動 `file copy` 用同一組帳密測 —— 通不通？
2. 備份伺服器上 `tcpdump -i any port 22 and host 10.99.0.11` —— 有沒有連線進來？
3. 目標目錄的權限 —— 那個帳號寫得進去嗎？
4. `show configuration system archival | display set` —— 路徑格式對不對？

## 安全性注意事項

> [!danger] ★★★★★ 設定備份檔是一份完整的攻擊地圖
> 一份交換器設定備份包含：完整的網路拓樸、VLAN 與網段規劃、管理網段位置、
> 所有帳號與密碼雜湊（`$6$`）、SNMP community、RADIUS／TACACS+ 密鑰（`$9$`，**可逆**）、
> ACL 規則、以及設備型號與韌體版本（可對照已知漏洞）。
> **保護等級必須比照密碼檔。**

| 項目 | 風險 | 做法 | 星級 |
| --- | --- | --- | --- |
| 備份放共用磁碟機／聊天軟體 | ★★★★★ 完整網路情報外洩 | 專用目錄、限定權限、不放共用槽 | ★★★★★ |
| 用 FTP／TFTP 傳輸備份 | ★★★★★ 明文傳輸，同網段抓包即得 | 一律用 SCP／SFTP | ★★★★★ |
| `archive-sites` 密碼是 `$9$` | ★★★★★ 可逆編碼，等同明文外洩備份伺服器帳密 | 專用帳號、只寫不讀、不能登入 shell、不對外 | ★★★★★ |
| 備份伺服器與辦公網互通 | 一台辦公 PC 中勒索軟體就加密掉所有備份 | 備份伺服器放管理網段；另做離線／異地副本 | ★★★★★ |
| 從不驗證備份能否還原 | ★★★★★ 出事時才發現備份是壞的 | 每季還原演練（測試設備 `load override` + `commit check`） | ★★★★★ |
| 韌體檔案來源不明 | 供應鏈攻擊 | ★★★★★ 只從 Juniper 官方支援網站下載，一定驗雜湊 |★★★★★ |
| 用 `no-validate` 跳過檢查 | 設定與新版不相容而不自知 | ★★★★★ **永遠不要用** | ★★★★★ |
| 版本過舊不升級 | 已知高風險漏洞持續存在，稽核缺失 | 訂閱 Juniper Security Advisories；每季評估 | ★★★★★ |
| 全機關版本混亂 | 排錯困難、漏洞管理不可能 | 版本收斂，資產清單記錄每台的版本 | ★★★★ |
| 遠端升級無現場支援 | ★★★★★ 升級失敗即無法救援 | 一律安排在有人到得了現場的時段 | ★★★★★ |
| 升級後不比對設定行數 | 保護設定被默默丟掉，稽核時才發現 | 逐次比對 + diff | ★★★★★ |
| 升級後立刻 snapshot 備援分割區 | ★★★★★ 把退路蓋掉了 | 新版穩定運行一週後才 snapshot | ★★★★★ |
| rescue 從未更新 | 救援設定是三年前的 | 每次變更驗證後重存 | ★★★★ |

> [!warning] ★★★★ 稽核常見缺失（備份與版本管理）
> 1. **無定期設定備份機制**，或備份僅存在設備本機
> 2. **未曾驗證備份可還原**（有備份不等於還原得回來）
> 3. 備份檔存放位置無存取控制
> 4. **韌體版本過舊且無升級計畫**，存在已知高風險漏洞
> 5. 無設備韌體版本清冊
> 6. 升級無變更紀錄、無回退計畫
>
> 本篇的 `system archival` + 每季還原演練 + 版本清冊三件事，
> 可以一次解決 1～3 與 5。第 4、6 項需要制度面配合，見
> [[100-02-08-guide-維運-變更管理流程]] 與 [[040-02-12-guide-機房-設備生命週期管理]]。

## 速查表

| 指令 / 設定項 | 說明 | 星級 |
| --- | --- | --- |
| `show configuration \| display set \| save /var/tmp/x.set` | 匯出 set 格式備份 | ★★★★★ |
| `show configuration \| display set \| count` | ★★★★★ 記下行數，升級後比對 | ★★★★★ |
| `file copy /var/tmp/x.set scp://u@h//abs/path/` | 送到外部（★★★★★ **兩條斜線**） | ★★★★★ |
| `file copy scp://u@h//path/file /var/tmp/` | 從外部取回 | ★★★★ |
| `set system archival configuration transfer-on-commit` | ★★★★★ 每次 commit 自動備份 | ★★★★★ |
| `set system archival configuration transfer-interval 1440` | 定時備份（分鐘） | ★★★ |
| `set system archival configuration archive-sites "scp://u@h:/path" password "..."` | 備份目的地 | ★★★★★ |
| `request system configuration rescue save` | 存救援設定 | ★★★★★ |
| `request system configuration rescue delete` | 刪除救援設定 | ★★ |
| `rollback rescue` + `commit` | 還原到救援設定 | ★★★★★ |
| `rollback N` + `commit` | 還原到第 N 版（0～49） | ★★★★★ |
| `load override /var/tmp/x.conf` | ★★★★★ 整份取代（遠端禁用） | ★★★★★ |
| `load set /var/tmp/x.set` | 載入 set 格式設定 | ★★★★ |
| `save /var/tmp/x.conf` | 設定模式下存 candidate | ★★★ |
| `/config/juniper.conf.gz` | active 設定檔 | ★★★ |
| `/config/rescue.conf.gz` | 救援設定檔 | ★★★ |
| `show system storage` | ★★★★★ 磁碟用量（升級前必看） | ★★★★★ |
| `request system storage cleanup dry-run` | 先看要刪什麼 | ★★★★ |
| `request system storage cleanup` | 清出空間 | ★★★★ |
| `file checksum sha256 <file>` | ★★★★★ 驗證韌體檔案完整性 | ★★★★★ |
| `file checksum md5 <file>` | 同上（舊版本用） | ★★★ |
| `request system software validate <file>` | ★★★★★ 升級前檢查設定相容性 | ★★★★★ |
| `request system software add <file> no-copy unlink reboot` | ★★★★★ 安裝並重開 | ★★★★★ |
| `request system software add <file> member 0` | Virtual Chassis 指定成員 | ★★★ |
| `request system software nonstop-upgrade <file>` | NSSU（★★★★ 前提條件多） | ★★★ |
| `request system software rollback` + `request system reboot` | 退回上一版韌體 | ★★★★★ |
| `request system snapshot slice alternate` | ★★★★★ 複製系統到備援分割區 | ★★★★★ |
| `show system snapshot media internal` | ★★★★★ 兩個分割區各是什麼版本 | ★★★★★ |
| `request system reboot slice alternate` | 從備援分割區開機 | ★★★★★ |
| `request system reboot in 10` / `clear system reboot` | 排程／取消重開（遠端保險） | ★★★★★ |
| `show version` | 版本 | ★★★★★ |
| `show version invoke-on all-routing-engines` | VC／雙 RE 各成員版本 | ★★★ |
| `show system alarms` / `show chassis alarms` | ★★★★★ 升級前後都要是零 | ★★★★★ |
| `Host 0 Boot from backup root` | ★★★★★ 主分割區壞了，立刻 snapshot 修復 | ★★★★★ |
| `show chassis hardware` | 機型與序號（RMA 用） | ★★★★ |
| `show virtual-chassis` | VC 成員與角色 | ★★★ |
| `request support information \| save /var/tmp/rsi.txt` | ★★★★ TAC 報修一次抓齊 | ★★★★ |
| `show system commit` | commit 歷史 | ★★★★ |
| JTAC Recommended Junos Versions | ★★★★★ 挑版本的第一依據 | ★★★★★ |
| Juniper Security Advisories（PSIRT） | ★★★★★ 判斷該不該升級 | ★★★★★ |

## 練習題

> [!question]- 練習 1：把 `system archival` 設起來並實測 ★★★★★
> 1. 在備份伺服器上建一個**專用帳號**（不能登入 shell、只能寫入備份目錄）
> 2. 在測試交換器上設 `transfer-on-commit` 與 `archive-sites`
> 3. 做一次沒有實質影響的 commit（例如改一個埠的 description）
> 4. ★★★★★ **到備份伺服器上確認檔案真的進來了**，`zcat` 看內容
> 5. 故意把密碼改錯，再 commit 一次，看 `show log messages | match archive` 的錯誤訊息
> 6. 改回正確密碼，確認恢復
>
> **要回答的問題**：檔名的格式是什麼？多台設備送到同一個目錄會不會撞名？
> 密碼在設定檔裡長什麼樣？那是雜湊還是可逆編碼？這代表什麼風險？

> [!question]- 練習 2：備份還原演練 ★★★★★
> **有備份不等於還原得回來。這題就是要證明這件事。**
> 1. 從備份伺服器取一份正式設備的 `.set` 備份
> 2. 在測試設備上 `load factory-default`、設 root 密碼、`commit`
> 3. `file copy` 或 `load set terminal` 把備份弄進去
> 4. `load set /var/tmp/x.set`
> 5. `show | compare | no-more` 檢查
> 6. `commit check`
> 7. 記錄：有幾項失敗？失敗原因是什麼？
>
> **要回答的問題**：哪些設定**不該**原封不動搬到另一台？
> （提示：hostname、管理 IP、序號綁定、憑證、SSH host key、VC 成員 ID）
> 一份「可用的備份」是不是應該附一份「還原時要調整哪些項目」的說明？
> 把這個演練排進 [[100-02-05-guide-維運-每季維護作業]]。

> [!question]- 練習 3：查出你們所有設備該不該升級 ★★★★★
> 1. 對每一台 Juniper 設備跑 `show version | match "Model|Junos:"`，做成清單
> 2. 到 Juniper 支援網站查 **JTAC Recommended Junos Software Versions**
> 3. 到 Juniper Security Advisories 查每台目前版本有沒有已知高風險漏洞
> 4. 查每個版本的 EOL／EEOL 日期
> 5. 做成表：設備 / 機型 / 目前版本 / 是否 JTAC 建議 / 已知高風險漏洞 / EOL 日期 / 建議動作
>
> **要回答的問題**：有幾台是「非升不可」（有高風險漏洞）？
> 有幾台是「可以不動」？全機關總共有幾個不同版本？
> 版本收斂到幾個是合理的？把這張表變成年度升級計畫。

> [!question]- 練習 4：完整的升級演練（測試機）★★★★★
> 在測試交換器上完整走一遍本篇的 SOP：
> 1. 前置六項檢查全部做完，每一步的輸出都存檔
> 2. **記錄實際耗時**（下載、validate、snapshot、安裝、重開機各花多久）
> 3. 升級後八項驗證全部做完
> 4. ★★★★★ 特別做：`show configuration | display set | count` 前後比對，`diff` 找出差異
> 5. 然後**故意執行回退**：`request system software rollback` + `request system reboot`
> 6. 確認真的回到舊版
>
> **要回答的問題**：整個流程實際花了多久？回退花了多久？
> 這兩個數字決定你的變更時窗要開多長。設定有沒有被丟掉幾行？
> 如果第 5 步的 rollback 失敗，你的下一步是什麼？

> [!question]- 練習 5：寫一份「交換器韌體升級 SOP」★★★★
> 依本篇的檢查表，寫成貴單位可用的作業程序，至少包含：
> - 什麼情況下才升級（漏洞／bug／功能／EOL 四種理由的判斷標準）
> - 版本選擇的依據（JTAC Recommended、EEOL、Release Notes）
> - 前置檢查清單（六項）
> - 升級步驟（逐條指令）
> - 驗證清單（八項，含設定行數比對）
> - ★★★★★ **回退決策點與逐條回退步驟**
> - 現場支援的要求（誰、多久到得了）
> - 收尾（rescue、備份、文件、資產清單）
>
> 與 [[100-02-08-guide-維運-變更管理流程]] 和
> [[080-03-04-guide-發布-上線檢查表與回退計畫]] 對照，補上簽核與通知的部分。

## 小測驗

Q1. 為什麼「設備上有 50 份 rollback 歷史」不算備份？真正的備份至少要滿足哪三個條件？

Q2. 這行指令會發生什麼事：`set system archival configuration transfer-on-commit`（搭配已設好的 `archive-sites`）？傳過去的檔名長什麼樣？為什麼多台設備可以送到同一個目錄？

Q3. 是非題：升級後 `show version` 顯示是新版本，就代表升級成功了。請說明理由。

Q4. 升級前為什麼一定要跑 `request system snapshot slice alternate`？如果跳過這一步，`request system software rollback` 會不會還能用？

Q5. `show system alarms` 出現 `Host 0 Boot from backup root`。這代表什麼？為什麼「設備看起來一切正常」反而更危險？處理步驟是什麼？

Q6. `commit confirmed` 在韌體升級的哪些情境下有用、哪些情境下完全沒用？沒用的情境要靠什麼？

Q7. 你升級後跑 `show configuration | display set | count` 得到 409 行，升級前是 412 行。這代表什麼？接下來要做什麼？為什麼這件事不會有任何告警？

Q8. 升級成功並驗證通過之後，為什麼「不要立刻對備援分割區做 snapshot」？應該等多久？

Q9. Junos 版本 `21.4R3-S5.4` 每一段代表什麼？挑升級目標版本時，除了「修哪個漏洞」之外還要考慮哪三件事？

Q10. `set system archival configuration archive-sites "scp://backup@10.99.0.5:/backup" password "xxx"` 這行設定在備份檔裡會長什麼樣？有什麼風險？至少提出三項對策。

> [!question]- 測驗答案
> **Q1.** ★★★★★ 因為那 50 份（加上 rescue）**全部都存在設備自己身上**。
> 設備硬體故障、被偷、機房火災、韌體升級把檔案系統搞壞、或設備被入侵後被清空 ——
> 這些「備份」會跟設備一起消失。它們是**回退機制**，不是備份。
>
> 真正的備份至少要滿足：
> 1. ★★★★★ **存在設備以外的地方**（外部伺服器、版控系統）
> 2. ★★★★★ **定期且自動產生**（`transfer-on-commit` 或排程；靠人工記得就一定會漏）
> 3. ★★★★★ **驗證過真的還原得回來**（每季拿測試設備 `load override` + `commit check`）
>
> ★★★★ 進一步做到 3-2-1（3 份副本、2 種媒介、1 份異地）就能抵禦機房災害與勒索軟體。
> 見「JunOS 的設定到底存在哪裡」。
>
> **Q2.** ★★★★★ 它會讓設備在**每一次 `commit` 成功之後**，
> 自動把目前的設定檔透過 SCP／FTP 傳送到 `archive-sites` 指定的位置。
> 檔名格式是 **`<hostname>_juniper.conf.gz_YYYYMMDD_HHMMSS`**，例如：
> ```text
> acc-3f-ex2300_juniper.conf.gz_20260902_164122
> core-ex4300_juniper.conf.gz_20260902_164401
> ```
> ★★★★ 因為**檔名自帶主機名稱與精確到秒的時間戳**，所以多台設備送到同一個目錄
> 既不會互相覆蓋，也不會蓋掉自己的歷史版本。
> ★★★★★ 這是本篇最推薦的設定：設好之後「忘記備份」這件事就不存在了。
> 但務必到備份伺服器上**實際確認檔案有進來**，設備端沒報錯不代表傳成功。
> 見「system archival 自動備份」。
>
> **Q3.** ★★★★★ **錯。** `show version` 只是八項驗證中的第一項。升級「成功」還要確認：
> - ★★★★★ `show system alarms` 零告警（特別是 `Host 0 Boot from backup root` ——
>   有這個告警代表主分割區壞了，你是靠備援在跑）
> - ★★★★★ **設定行數與升級前一致** —— 新版可能默默丟掉不認識的設定項
> - 硬體清單完整（電源、風扇、介面卡）
> - 介面 up 的數量、VLAN 成員、MAC 表都對得上
> - 管理面正常（新開一條 SSH、路由、syslog 有進來）
> - ★★★★★ **使用者實測**（PC／AP／印表機／伺服器）
>
> ★★★★ 只看版本號就宣布完成，是升級事故最常見的起點。見「升級後的八項驗證」。
>
> **Q4.** ★★★★★ 因為 `request system snapshot slice alternate` 會把**目前這個你確定好用的系統**
> 複製到備援分割區，成為升級失敗時的退路。跳過的話，備援分割區裡可能是更舊的版本
> （本篇範例中是 `21.4R2`，而你在跑的是 `21.4R3-S5.4`），退回去會多退好幾版。
>
> ★★★★ `request system software rollback` **不一定還能用**。它依賴設備上保留的
> 「上一版安裝狀態」，以下情況會失敗：
> - 安裝時用了 `unlink`，還原資料被清掉
> - 中間又做了 snapshot，把備援分割區蓋成新版
> - 磁碟空間不足導致還原資料沒保留
> - 跨太多版本升級
>
> ★★★★★ 所以 snapshot **不能省** —— 它是「保證退得回去」的那一層。
> `software rollback` 失敗時的最後手段是 `request system reboot slice alternate`。
> 見「升級前的六項檢查」檢查 5 與「回退」。
>
> **Q5.** ★★★★★ 它代表**主分割區（primary slice）已經損壞，設備這次是從備援分割區開機的**。
>
> 「看起來一切正常」反而危險，因為：★★★★★ **你現在沒有第二份保險了**。
> 備援分割區是你唯一還能開機的系統，它再壞一次設備就開不起來。
> 而且很多人看到 `Minor` 等級的告警就忽略掉，等到真的出事才發現。
>
> 處理步驟：
> 1. `show version` 確認目前跑的是哪一版（是新版還是升級前的舊版？）
> 2. ★★★★★ `request system snapshot`（把目前這份健康的系統複製回主分割區）
> 3. `show system snapshot media internal` 確認兩個 slice 都正常
> 4. 必要時重開機讓告警消失
> 5. ★★★★ **snapshot 反覆失敗 = 儲存媒體實體損壞**，立刻準備報修／換機，
>    並先把設定備份帶出來
>
> 見「雙分割區」。
>
> **Q6.** ★★★★★
> **有用的情境**：
> - 情境 B：★★★★★ **升級後第一次調整設定** —— 新版對某個設定的解讀可能不同，
>   例如補回被丟掉的設定、調整 SSH 或 `lo0` filter。這是升級當天最容易出事的時刻。
> - 一般的設定變更（升級前的準備、升級後的收尾）
>
> **完全沒用的情境**：
> - 情境 C：★★★★★ **升級本身失敗、設備開不起來** ——
>   `commit confirmed` 是設定層的機制，設備都開不起來了它根本沒機會執行。
>   救你的是 **雙分割區 + snapshot + console 線**。
> - 情境 D：★★★★★ **升級成功但新版有 bug** ——
>   設定是對的，問題在韌體。救你的是 `request system software rollback` + reboot，
>   或 `request system reboot slice alternate`。
>
> ★★★★★ 結論：升級需要**三層保險**（設定層 `commit confirmed`、
> 系統層 snapshot／dual-root、實體層 console + 現場人員），缺一不可。
> 見「commit confirmed 在升級時能救什麼、不能救什麼」。
>
> **Q7.** ★★★★★ 代表**有 3 行設定在升級過程中被丟掉了**。
> JunOS 升級時如果遇到新版本已經移除或改名的設定項，會**默默丟棄它們**。
>
> 接下來要做的：
> 1. `show configuration | display set | save /var/tmp/post-upgrade.set`
> 2. `diff pre-upgrade.set post-upgrade.set` 找出是哪 3 行
> 3. 查 Release Notes 的 **"Changes in Behavior and Syntax"** 章節，找新版的對應寫法
> 4. ★★★★★ 用 `commit confirmed` 把等效的設定補回去
> 5. 再次 `count` 確認行數（或至少確認每一項功能都有對應設定）
>
> ★★★★★ **為什麼不會有告警**：從 JunOS 的角度這不是錯誤 ——
> 它「正確地」載入了所有它認得的設定，不認得的就跳過。
> 危險之處在於**丟掉的往往是保護類設定**（本篇範例是 BPDU 保護與 storm-control 選項），
> 你以為有的防護其實已經不在了，而且要到稽核或出事時才會發現。
> 這就是為什麼「記下升級前的行數」是檢查表上的必要項目。見「升級後的八項驗證」第 4 項。
>
> **Q8.** ★★★★★ 因為**備援分割區裡存的是升級前的舊版本，那是你唯一的退路**。
> 一旦跑 `request system snapshot slice alternate`，備援分割區就被新版蓋掉了 ——
> 兩個 slice 都是新版，`request system reboot slice alternate` 也回不去舊版。
>
> ★★★★ 應該等多久：**建議至少一週**。理由是有些問題不會在升級當天顯現：
> - 記憶體洩漏要跑幾天才看得出來
> - 某些功能一週才用一次（週報表系統、月結批次）
> - 尖峰時段的效能問題要遇到尖峰才知道
> - 使用者的零星回報需要時間累積
>
> 一週後（或依貴單位規定的觀察期）確認新版穩定，才跑
> `request system snapshot slice alternate` 讓兩份都是新版，恢復雙保險。
> 見「完整實戰範例步驟 9」與檢查表第 26 項。
>
> **Q9.** ★★★★
> ```text
> 21  .  4  R  3  -  S  5  .  4
> │      │  │  │     │  │     └── spin：同一個 SR 的小修正
> │      │  │  │     │  └──────── Service Release 編號（第 5 個 SR）
> │      │  │  │     └─────────── S = Service Release（累積修正）
> │      │  │  └───────────────── 該版本的第 3 次 Release
> │      │  └──────────────────── R = 正式版（X = 特殊版本）
> │      └─────────────────────── 季（第 4 季）
> └────────────────────────────── 年（2021）
> ```
> 除了「修哪個漏洞」之外還要考慮的三件事：
> 1. ★★★★★ **是不是在 JTAC Recommended Junos Software Versions 清單上** ——
>    Juniper 官方認證過的穩定版本，這是最重要的依據
> 2. ★★★★★ **是不是 EEOL（Extended End of Life）版本** ——
>    支援期限長很多。機關設備汰換週期 5～7 年，選非 EEOL 版本會很快沒有安全更新，
>    兩年後又要再升一次
> 3. ★★★★ **Release Notes 的 Known Issues 有沒有影響你用到的功能** ——
>    以及 "Changes in Behavior and Syntax"（會不會丟掉你的設定）
>
> ★★★ 第四點：全機關**版本收斂**，同一批設備用同一版，排錯與漏洞管理才管得動。
> 見「Junos 版本編號怎麼讀」。
>
> **Q10.** ★★★★★ 在設定檔（與備份檔）裡會長成：
> ```junos
> archive-sites {
>     "scp://backup@10.99.0.5:/backup" password "$9$JHUiqmT3/tOP5Qn"; ## SECRET-DATA
> }
> ```
> ★★★★★ **`$9$` 是 Junos 的可逆編碼，不是雜湊。** 網路上有大量現成的解碼工具，
> 幾秒鐘就能還原成明文。所以：
> **任何拿到這台交換器設定備份的人，都同時拿到了你備份伺服器的帳號密碼** ——
> 而備份伺服器上放著全機關所有網路設備的完整設定，等於一次拿走整張作戰地圖。
>
> 至少三項對策：
> 1. ★★★★★ **備份伺服器上開專用帳號**：`/usr/sbin/nologin` 或 SFTP chroot，
>    無法登入 shell（見 [[020-02-01-06-svc-SFTP-與受限使用者]]）
> 2. ★★★★★ **該帳號只能寫不能讀**：目錄權限設成無法列出或下載已存在的備份，
>    這樣即使密碼外洩，攻擊者也拿不到其他設備的設定
> 3. ★★★★ **備份伺服器只在管理網段**，不對辦公網或外部開放
> 4. ★★★ 定期輪替該密碼，並納入密碼管理流程
> 5. ★★★ 進一步可改用 SSH 金鑰而非密碼（依 Junos 版本支援情況）
>
> ★★★★ 同樣的邏輯適用於設定檔裡所有 `$9$` 欄位：RADIUS secret、TACACS+ secret、
> SNMP community —— **一律視同明文**。見「安全性注意事項」。

## 延伸閱讀

- [[040-01-05-cmd-Juniper-JunOS-基礎操作]] —— `rollback`、`rescue`、`file copy`、`request system` 系列
- [[040-01-06-guide-Juniper-VLAN與Trunk設定]] —— 升級後要驗證的 VLAN 項目
- [[040-01-07-guide-Juniper-管理IP與遠端存取]] —— 備份走的 SCP、管理面驗證
- [[040-01-08-guide-Juniper-埠設定與安全]] —— 升級後最容易被丟掉的保護設定
- [[040-01-14-svc-Cisco-設定備份與韌體升級]] —— Cisco 那一側的完整內容
- [[040-01-15-cmd-網路設備-Juniper與Cisco指令對照]] —— 兩邊指令對照
- [[040-01-18-guide-網路設備-網路設備盤點與文件化]] —— 版本清冊、序號、資產表
- [[040-01-19-guide-網路設備-交換器汰換與遷移實務]] —— 換機時的設定搬遷與注意事項
- [[040-02-12-guide-機房-設備生命週期管理]] —— EOL、汰換規劃、退役資料清除
- [[100-02-08-guide-維運-變更管理流程]] —— 變更單、時窗、簽核
- [[080-03-04-guide-發布-上線檢查表與回退計畫]] —— 回退決策點的訂定方法
- [[100-02-05-guide-維運-每季維護作業]] —— 備份還原演練排進定期作業
- [[100-02-10-guide-維運-故障排除方法論]] —— 「先恢復服務」的決策原則
- [[020-02-02-02-cmd-systemd-timer與cron選型]] —— 備份伺服器端的排程與版控腳本
- Juniper Software Installation and Upgrade Guide：<https://www.juniper.net/documentation/us/en/software/junos/junos-install-upgrade/>
- JTAC Recommended Junos Software Versions：<https://supportportal.juniper.net/>
- Juniper Security Advisories（PSIRT）：<https://supportportal.juniper.net/s/global-search/%40uri?language=en_US>
- Juniper EOL / EEOL 查詢：<https://support.juniper.net/support/eol/>
