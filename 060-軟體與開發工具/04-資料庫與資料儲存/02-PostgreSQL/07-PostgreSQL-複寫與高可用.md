---
title: "PostgreSQL 複寫與高可用"
desc: "用 WAL 串流複寫建起可維運的 PostgreSQL 主備：延遲判讀、複寫槽爆磁碟的防呆、pg_rewind 降級與零雙寫切換"
aliases: [streaming replication, standby, WAL, pg_basebackup, pg_rewind, replication slot, 主備, 故障切換]
tags: [群組/軟體與開發工具, 服務/postgresql, 主題/高可用, 主題/複寫]
category: 資料庫與資料儲存
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[05-PostgreSQL-備份與還原]]", "[[04-PostgreSQL-設定檔與pg_hba]]", "[[02-PostgreSQL-角色與權限]]"]
updated: 2026-08-28
---

# PostgreSQL 複寫與高可用

> [!abstract] 這篇你會學到
> - 用 `pg_basebackup` + **複寫槽（replication slot）** 在兩台 Ubuntu 上建起一套**真的能維運**的 WAL 串流複寫
> - 看懂 `pg_stat_replication` 的 `write_lag` / `flush_lag` / `replay_lag` 三種延遲，知道**哪一個才是你該告警的那個**
> - ★★★★★ 避開 PostgreSQL 兩個最貴的坑：**複寫槽撐爆 `pg_wal` 讓主庫停擺**、
>   **單台同步 standby 掛掉讓全站寫入卡死**
> - ★★★★ 執行一次**不會產生雙寫（split brain）**的計畫性切換，並用 `pg_rewind` 把舊主庫降級成 standby 而不用重灌
> - 處理 standby 上跑報表最常見的 `canceling statement due to conflict with recovery`，並知道代價在哪
> - 理解 **timeline（時間軸）**這個 MySQL 沒有的概念 —— promote 之後為什麼舊 standby 會接不回來

---

## 前置知識

| 篇章 | 你會用到裡面的什麼 |
| --- | --- |
| [[05-PostgreSQL-備份與還原]] | ★★★★ WAL 歸檔、PITR 與還原演練。**本篇不取代它** —— 複寫與備份是兩件事 |
| [[04-PostgreSQL-設定檔與pg_hba]] | ★★★★ `pg_hba.conf` 的比對順序、`scram-sha-256`、改完該 reload 還是 restart |
| [[02-PostgreSQL-角色與權限]] | 建 `replicator` 角色、`REPLICATION` 屬性、`pg_monitor` 預設角色 |
| [[06-PostgreSQL-效能調校與索引]] | `shared_buffers`、checkpoint 行為；standby 規格為什麼不能比主庫差 |
| [[06-MySQL-主從複寫]] | ★★★ 對照組。兩套資料庫的複寫觀念相通，**故障模式完全不同**，本篇會逐項對照 |
| [[02-防火牆-ufw基礎與實務]] | 只放行 standby 那一台 IP 的 5432，不對外開放 |
| [[28-時間同步NTP與chrony]] | ★★★ 兩台沒對時，你算出來的延遲秒數全是假的 |

★★ 本篇的 SQL 語法本身不再解釋，需要複習 `SELECT` / `CREATE ROLE` 這類基本語法請看 [[03-SQL基礎操作]]，
`psql` 的操作技巧（`\watch`、`\x`、`-At`）看 [[03-psql-操作與常用指令]]。

---

## 觀念說明

### ★★★★ 先講死一次：複寫不是備份

```text
  14:22:31.000   有人在正式庫下 DROP TABLE 民眾申請案件;
  14:22:31.004   主庫寫入 WAL 記錄這個 catalog 變更
  14:22:31.021   standby 的 walreceiver 收到
  14:22:31.033   standby 的 startup process 忠實重放 → standby 的表也沒了
  ★★★★★ 全程 0.033 秒。你有兩台機器，但你有零份資料。
```

| 威脅 | 複寫擋得住嗎 | 備份（含 PITR）擋得住嗎 |
| --- | --- | --- |
| 主機硬碟壞、電源掛掉、記憶體故障 | ★★★★ 可以，promote standby 即可 | 可以，但 RTO 以小時計 |
| 機房斷網、單點失效 | ★★★★ 可以 | 不行（除非異地備份 + 異地主機） |
| `DROP TABLE` / `DELETE` 忘了 `WHERE` | ★★★★★ **完全擋不住** | ★★★★★ 可以（PITR 回到誤操作前一秒） |
| 勒索軟體加密資料檔 | ★★★★★ **完全擋不住** | 可以（離線／不可變備份） |
| 應用程式邏輯 bug 寫爛資料 | ★★★★★ **完全擋不住** | 可以 |
| 磁碟靜默毀損（bit rot） | ★★ 有 data checksums 才抓得到 | 可以 |

> [!danger] ★★★★★ 導入複寫不能減少任何一次備份
> 完整的備份策略、WAL 歸檔與**還原演練**在 [[05-PostgreSQL-備份與還原]]；
> 機關層級的災難復原制度看 [[03-備份策略與還原演練]] 與 [[06-災難復原與異地備援]]。
> 本篇只負責「硬體故障與單點」這一格。
> 後面會給你一個折衷武器 —— **延遲 standby**（`recovery_min_apply_delay = '1h'`），
> 它讓你有一小時緩衝去撈誤刪的資料，但它**仍然不是備份**。

★★ 值得為它付一台機器成本的動機只有兩個：**分流**（報表、對帳、`pg_dump` 移到 standby）
與**頂替**（主庫掛了 30 分鐘內有一台能上）。
如果真實需求是「查詢很慢」，先看 [[04-效能瓶頸排查方法論]] 與 [[06-PostgreSQL-效能調校與索引]] ——
加一台 standby 不會讓缺索引的查詢變快。

### 資料是怎麼流過去的

PostgreSQL 的複寫只有一種燃料：**WAL（Write-Ahead Log，預寫日誌）**。
主庫做的每一件會改變資料的事，都先寫成 WAL 記錄，standby 拿到同一份 WAL 逐筆重放。

```text
        主庫 pg1  10.0.1.11                            standby pg2  10.0.1.12
 ┌──────────────────────────────────┐        ┌───────────────────────────────────┐
 │ 應用連線 (Laravel / PHP-FPM)     │        │ 報表 / 稽核查詢（唯讀）           │
 │           ↓ INSERT/UPDATE        │        │           ↑                       │
 │   shared_buffers → WAL buffer    │        │   ┌───────────────────────┐       │
 │           ↓ fsync                │        │   │ startup process       │       │
 │   pg_wal/0000000100000000000000A3│        │   │ （★★★★ 只有一個！）  │       │
 │           ↓                      │        │   └──────────▲────────────┘       │
 │   ┌──────────────────────┐       │        │   pg_wal/（收到的 WAL 落地）      │
 │   │ walsender（每台一條）│       │        │   ┌──────────┴────────────┐       │
 │   │ 綁 replication slot  │       │        │   │ walreceiver（一條）   │       │
 │   └──────────┬───────────┘       │        │   └───────────────────────┘       │
 └──────────────┼──────────────────-┘        └───────────────────────────────────┘
                └──── TCP 5432 / TLS ────────────────►
                      replicator@10.0.1.12
       ┌───────────────────┐
       │ archiver → /srv/wal│  ★★★★ 歸檔是另一條路，standby 斷線太久時的救命繩
       └───────────────────┘
```

三個角色，各自會壞，壞法不一樣：

| 角色 | 在哪台 | 職責 | 壞掉的症狀 |
| --- | --- | --- | --- |
| **walsender** | 主庫 | 把 WAL 推給 standby | ★★★★ 主庫 `pg_stat_replication` 空的（一列都沒有） |
| **walreceiver** | standby | 收 WAL、寫進 `pg_wal/` | ★★★★ standby `pg_stat_wal_receiver` 空的、日誌出現 `could not connect` |
| **startup process** | standby | 重放 WAL | ★★★★ `replay_lag` 一直增加，`pg_stat_activity` 看到 `startup` 在 `RecoveryWalStream` 等待 |
| **archiver** | 主庫 | 把寫滿的 WAL 段丟去歸檔 | ★★★★★ 歸檔失敗會讓 `pg_wal/` 一直累積 → 磁碟滿 → 主庫停擺 |

> [!note] ★★★★ startup process 只有一個，而且不能並行
> MySQL 的 applier 可以開 8 條 worker 平行套用；**PostgreSQL 的 WAL 重放是單一行程、嚴格照順序**。
> 這代表：standby 追不上時，**你不能靠「加執行緒」解決**，只能減少主庫產生 WAL 的量
> （拆大交易、少建無用索引、關掉不必要的 `full_page_writes` 放大來源），或給 standby 更快的磁碟。
> ★★★ 也因此 **standby 的 I/O 規格不能比主庫差** —— 這是機關採購最常犯的錯：
> 「備援機拿舊機器頂一下就好」，結果平常追不上、真的要切的時候落後兩小時。

### ★★★★ PostgreSQL vs MySQL：同一件事，兩套做法

這張表是本篇與 [[06-MySQL-主從複寫]] 的橋。**觀念相通，故障模式完全不同**。

| 主題 | MySQL 8.0 | **PostgreSQL 16/17（本篇）** |
| --- | --- | --- |
| 複寫的燃料 | binlog（複寫專用，與 redo log 分開） | ★★★★ **WAL**（崩潰復原與複寫共用同一份） |
| 進度怎麼標記 | GTID `uuid:1-45210` | **LSN** `0/A3C1F8` + **timeline** |
| 複寫粒度 | 可以只複寫某幾個 DB／表 | ★★★★ **物理複寫是整個 cluster，不能挑**（要挑就用邏輯複寫） |
| standby 能不能寫 | 靠 `super_read_only` 擋，root 可繞過 | ★★★★ **物理上就不可寫**，超級使用者也寫不進去 |
| 重放並行度 | `replica_parallel_workers` 可開多條 | ★★★★ **單一 startup process，不可並行** |
| 主庫要保留多少日誌 | `binlog_expire_logs_seconds`（時間） | ★★★★ **複寫槽**（保到 standby 收到為止）＋ `max_slot_wal_keep_size` |
| 保留機制的風險 | binlog 被清掉 → 從庫要重做 | ★★★★★ **槽不清 → `pg_wal` 撐爆 → 主庫直接停止服務** |
| 跳過一筆壞交易 | 注入空交易可跳過 | ★★★★★ **辦不到**。WAL 是物理層的，跳過就是資料毀損 |
| 主從版本可否不同 | 從庫可較新 | ★★★★ **大版本必須完全相同**（物理複寫的頁面格式綁死） |
| 切換後舊主庫怎麼辦 | 設 auto position 就能接回 | ★★★★ 產生了新 timeline，要 `pg_rewind` 或重做 |
| 官方自動切換 | MGR / InnoDB Cluster | ★★★ **核心沒有內建**，要靠 Patroni / repmgr（外部工具） |

> [!danger] ★★★★★ 從 MySQL 過來的人最容易踩的一顆雷
> 在 MySQL 世界，複寫斷掉時「跳過那筆交易」是常見的急救手段（雖然本手冊也不建議）。
> **PostgreSQL 沒有這個選項，而且不該去找。**
> WAL 記錄的是「第幾個檔案第幾個 block 的 bytes 改成什麼」，
> 跳過一筆 = 資料檔破洞 = 之後每一筆重放都建立在錯誤的基礎上。
> PostgreSQL 的複寫壞掉時，正解永遠只有兩個：**修好連線繼續重放**，或**重建整台 standby**。

### 物理複寫 vs 邏輯複寫：先選型再動手

| | **物理（串流）複寫** ← 本篇主線 | 邏輯複寫（publication / subscription） |
| --- | --- | --- |
| 複寫什麼 | 整個 cluster 的 WAL（byte 層級） | 指定資料表的 INSERT/UPDATE/DELETE（列層級） |
| 副本可否寫入 | ★★★★ 完全唯讀 | 可以寫（要自己避免衝突） |
| 大版本可否不同 | ★★★★ **不行** | 可以（跨大版本升級常用這招） |
| DDL 會不會過去 | ★★★★ 會（`CREATE INDEX` 也照複寫） | ★★★★ **不會**，要兩邊各自執行 |
| 序列（sequence）值 | 會 | ★★★★ **不會同步**，切換前要手動 `setval` |
| 沒有主鍵的表 | 沒差 | ★★★★ 需要 `REPLICA IDENTITY`，否則 UPDATE/DELETE 直接報錯 |
| 適用情境 | **高可用、故障切換、報表分流** | 跨版本升級、資料整合、只要幾張表 |

★★★ 高可用要的是物理複寫。邏輯複寫看起來彈性大，但「DDL 不過去」與「序列不同步」
這兩件事會讓它在故障切換情境下變成陷阱。本篇進階段落會談邏輯複寫，但**不把它當主備方案**。

### 同步還是非同步：這是一個資料 vs 可用性的取捨

`synchronous_commit` 決定主庫什麼時候敢回應用「commit 成功」：

| 值 | 主庫等到什麼才回 | 主庫瞬間掛掉的資料遺失 | 寫入成本 | 用在哪 |
| --- | --- | --- | --- | --- |
| `off` | 連自己的 WAL 都還沒 fsync | ★★★★★ 可能遺失數秒 | 最低 | 只用於可重建的暫存資料 |
| `local` | 自己 fsync 完 | ★★★ 主庫救得回來就沒事，切換會掉 | 低 | 明確不要同步時 |
| `on`（預設） | 自己 fsync 完（沒設 `synchronous_standby_names` 時） | ★★★ 切換可能掉最後幾筆 | 低 | **絕大多數機關系統、本篇主線** |
| `remote_write` | standby 的 OS 收到（尚未落磁碟） | ★★ standby 同時斷電才會掉 | 中 | 折衷 |
| `on` + 有同步 standby | standby **fsync 完** | ★ 幾乎不掉 | 高（多一個 RTT） | 金流、不能掉單的收件系統 |
| `remote_apply` | standby **重放完、查得到** | ★ 幾乎不掉 | 最高 | 需要「寫完立刻能在 standby 讀到」 |

> [!danger] ★★★★★ 開同步複寫之前一定要先懂這件事
> 設了 `synchronous_standby_names = 'pg2'` 之後，**只要 pg2 離線，主庫的每一個 commit 都會無限期卡住**。
> 不是變慢，是**整個系統的寫入完全停止**，而且 `pg_stat_activity` 會看到一堆
> `wait_event = SyncRep`。這比「掉最後三筆交易」嚴重得多。
> 兩個防呆，缺一不可：
> **①** 至少配兩台 standby 並用 quorum 寫法 `ANY 1 (pg2, pg3)`。
> **②** 寫進 runbook：緊急時 `ALTER SYSTEM SET synchronous_standby_names = '';` + `reload`
> 可以立刻解除卡死（代價是那段期間退回非同步）。
> **只有一台 standby 卻設同步 = 你把單點故障從一台變成兩台。**

### ★★★★★ 複寫槽：保命繩，也是絞索

複寫槽（replication slot）讓主庫「保留 standby 還沒收到的 WAL，一個 byte 都不刪」。
沒有槽的話 standby 離線太久，需要的 WAL 就被 checkpoint 清掉了，只能整台重做。

代價是：**standby 掛掉沒人管，主庫的 `pg_wal/` 會一直長，長到磁碟滿為止。**

```text
  Day 0  standby 網路斷了，沒人看告警
  Day 1  pg_wal 12 GB   ← 還好
  Day 3  pg_wal 84 GB   ← 磁碟 78% 
  Day 4  pg_wal 涨滿    ← PANIC: could not write to file "pg_wal/xlogtemp.xxxx": No space left on device
         ★★★★★ 主庫直接關機。不是變慢，是整個資料庫服務停止。
```

解法是 `max_slot_wal_keep_size`（PostgreSQL 13 起）：

```ini
max_slot_wal_keep_size = 64GB   # ★★★★ 槽最多只能拖住 64 GB WAL，超過就讓它失效
```

★★★★ 這個設定的意思是「**寧可犧牲 standby，也要保住主庫**」——
超過門檻時槽會被標成 `lost`，那台 standby 之後只能重建，但主庫活著。
這幾乎永遠是對的取捨。**設定 64GB 的前提是 `pg_wal` 所在分割區至少有 100 GB 以上的餘裕。**

### ★★★★ timeline：MySQL 沒有、但你一定會撞到的概念

每次有 standby 被 promote 成主庫，PostgreSQL 就把 **timeline ID 加一**，
並在 `pg_wal/` 產生一個 `.history` 檔記錄「我是在 LSN 0/A3C1F8 這個點從 timeline 1 分家的」。

```text
timeline 1 ────────────●────────────────────  ← 舊主庫 pg1 繼續寫（如果沒關掉 = 雙寫）
                       │ 0/A3C1F8 promote
                       └──────────────────    timeline 2  ← 新主庫 pg2
                          00000002.history
```

這件事有三個直接後果：

- ★★★★ **舊主庫不能直接改設定就接回新主庫當 standby**。它在 timeline 1 上有新主庫沒有的 WAL，
  必須用 `pg_rewind` 把它倒回分家點，或整台重做。
- ★★★ 其他 standby 要跟著新主庫，靠的是 `recovery_target_timeline = 'latest'`（PostgreSQL 12 起是預設值）。
- ★★★★ **雙寫（split brain）在 PostgreSQL 是靜默發生的** —— 兩邊各自在自己的 timeline 上寫，
  誰也不會報錯，直到你想把它們合起來才發現合不了。切換程序的每一步都是為了防這件事。

---

## 環境準備與安裝

### 本篇的固定環境

| 角色 | 主機名 | IP | 版本 | 用途 |
| --- | --- | --- | --- | --- |
| 主庫（primary） | `pg1` | `10.0.1.11` | Ubuntu 24.04 + PostgreSQL 17 | 應用讀寫 |
| 備庫（standby） | `pg2` | `10.0.1.12` | Ubuntu 24.04 + PostgreSQL 17 | 唯讀報表 + 頂替 |
| 應用 | `app1` | `10.0.1.21` | Laravel / Nuxt | 見 [[03-範例-Nuxt與PostgreSQL]] |
| WAL 歸檔 | `bak1` | `10.0.1.31` | `/srv/wal`（NFS 或 rsync 目的地） | 見 [[05-PostgreSQL-備份與還原]] |

> [!danger] ★★★★ 兩台的 PostgreSQL **大版本與 binary 必須完全一致**
> 物理複寫傳的是資料頁的 byte，17.2 對 17.5 這種小版本差異通常沒問題（官方建議仍是一致），
> 但 **16 對 17 絕對不行**，standby 會在啟動時直接 `FATAL: database files are incompatible with server`。
> 升級時的正確順序是：先升 standby → 切換 → 再升舊主庫，或者用邏輯複寫做跨版本升級。

### 安裝（兩台都做）

Ubuntu 24.04 內建的是 PostgreSQL 16；要用 17 就加 PGDG 套件庫：

```bash
sudo apt install -y curl ca-certificates
sudo install -d /usr/share/postgresql-common/pgdg
sudo curl -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
  --fail https://www.postgresql.org/media/keys/ACCC4CF8.asc
echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
  | sudo tee /etc/apt/sources.list.d/pgdg.list
sudo apt update && sudo apt install -y postgresql-17 postgresql-client-17
```

驗證：

```bash
pg_lsclusters
```

預期輸出：

```text
Ver Cluster Port Status Owner    Data directory              Log file
17  main    5432 online postgres /var/lib/postgresql/17/main /var/log/postgresql/postgresql-17-main.log
```

★★★ 第三方套件庫的加入方式（金鑰、pinning、離線機關的鏡像做法）見 [[01-PostgreSQL-安裝與初始化]]。

> [!danger] ★★★★ Debian／Ubuntu 的路徑分家 —— 這是本篇最容易毀掉一次維運的細節
> 官方 tarball 與 RHEL 把設定檔放在資料目錄裡；**Debian 系把它們搬到 `/etc`**：
>
> | 東西 | Ubuntu／Debian | 官方原生／RHEL |
> | --- | --- | --- |
> | 資料目錄 `PGDATA` | `/var/lib/postgresql/17/main` | `/var/lib/pgsql/17/data` |
> | `postgresql.conf` / `pg_hba.conf` | ★★★★ `/etc/postgresql/17/main/` | 資料目錄內 |
> | `postgresql.auto.conf` | ★★★★ **仍在資料目錄內**（`ALTER SYSTEM` 寫這裡） | 資料目錄內 |
> | `standby.signal` | 資料目錄內 | 資料目錄內 |
> | 服務控制 | `pg_ctlcluster 17 main <cmd>` | `systemctl … postgresql-17` |
>
> ★★★★★ **`pg_basebackup` 只複製資料目錄** —— 也就是說，
> 在 Ubuntu 上做完 base backup，**主庫的 `postgresql.conf` 與 `pg_hba.conf` 不會跟過去**。
> 很多人因此在切換當下才發現 standby 的 `shared_buffers` 還是安裝預設的 128MB，
> 或是 `pg_hba.conf` 根本沒有應用程式那一段 —— **切過去之後應用全部連不上**。
> 對策寫在後面的實戰腳本裡：**設定檔要另外 rsync 過去並納入版控**。

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> sudo dnf install -y https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm
> sudo dnf -qy module disable postgresql          # ★★★★ 不關掉會裝到 AppStream 的舊版
> sudo dnf install -y postgresql17-server postgresql17-contrib
> sudo /usr/pgsql-17/bin/postgresql-17-setup initdb   # ★★★ standby 那台**不要**跑 initdb
> sudo systemctl enable --now postgresql-17
> ```
> | 項目 | Ubuntu 24.04 | Rocky / AlmaLinux 9 |
> | --- | --- | --- |
> | 服務名 | `postgresql@17-main` | `postgresql-17` |
> | 資料目錄 | `/var/lib/postgresql/17/main` | `/var/lib/pgsql/17/data` |
> | 設定檔 | `/etc/postgresql/17/main/` | ★★★★ 資料目錄內（所以 `pg_basebackup` 會一起複製過去） |
> | 日誌 | `/var/log/postgresql/` | `/var/lib/pgsql/17/data/log/` |
> | 強制存取控制／防火牆 | AppArmor / `ufw` | ★★★★ SELinux / `firewalld` |
>
> ```bash
> # ★★★★ SELinux：WAL 歸檔目錄放在非預設路徑一定要補標籤，否則 archive_command 會靜默失敗
> sudo semanage fcontext -a -t postgresql_db_t "/srv/wal(/.*)?" && sudo restorecon -Rv /srv/wal
> sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" \
>   source address="10.0.1.12/32" port protocol="tcp" port="5432" accept'
> sudo firewall-cmd --reload
> ```
> ★★★ RHEL 系因為設定檔在資料目錄內，`pg_basebackup` 會把主庫的 `postgresql.conf` 一起帶過去 ——
> 這解決了上面那個 Debian 的坑，但帶來另一個：**standby 會繼承主庫的 `archive_command`**，
> 記得在 standby 上把 `archive_mode` 設成 `off` 或 `always` 並想清楚要哪一個。

### 網路、防火牆與時間

```bash
# ═══ pg1（主庫）：只放行 standby 那一台 ═══
sudo ufw allow from 10.0.1.12 to any port 5432 proto tcp comment 'PG streaming repl from pg2'
sudo ufw status numbered

# ═══ pg2（standby）：確認連得到 ═══
nc -zv 10.0.1.11 5432
timedatectl show -p NTPSynchronized --value
```

預期輸出：

```text
[ 4] 5432/tcp          ALLOW IN    10.0.1.12       # PG streaming repl from pg2
Connection to 10.0.1.11 5432 port [tcp/postgresql] succeeded!
yes                                                # ★★★ 不是 yes 就先去修 NTP
```

> [!danger] ★★★★ 不要 `sudo ufw allow 5432`
> 沒有來源限制的 5432 等於把整個資料庫掛在網路上，
> 而且 PostgreSQL 的預設 `listen_addresses` 一旦從 `localhost` 改成 `*`，這個洞立刻生效。
> 規則寫法見 [[02-防火牆-ufw基礎與實務]]，`listen_addresses` 與 `pg_hba` 的搭配見 [[04-PostgreSQL-設定檔與pg_hba]]。

---

## 基礎設定：把串流複寫建起來

### 【1】主庫參數

```bash
sudo -u postgres tee -a /etc/postgresql/17/main/conf.d/zz-replication.conf > /dev/null << 'EOF'
# ── 複寫基礎（PostgreSQL 17 的預設值已經夠用，這裡寫明是為了可稽核）──
wal_level = replica                 # ★★★ 預設就是 replica；改 logical 才需要邏輯複寫
max_wal_senders = 10                # ★★ 預設 10，每台 standby 佔 1，pg_basebackup 再佔 1~2
max_replication_slots = 10          # ★★ 預設 10
wal_keep_size = 1GB                 # ★★ 沒有槽時的最低保障；有槽時當緩衝

# ── ★★★★★ 防止複寫槽撐爆磁碟（沒有這行，主庫遲早會因為 pg_wal 滿而停機）──
max_slot_wal_keep_size = 64GB

# ── ★★★★ pg_rewind 的前置條件，事後補設要重啟，現在就開 ──
wal_log_hints = on

# ── standby 上要能查詢（預設就是 on，寫明以免被人關掉）──
hot_standby = on

# ── 逾時：主庫這邊多久沒聽到 standby 回報就砍掉 walsender ──
wal_sender_timeout = 60s

# ── WAL 歸檔（★★★★ 這是 PITR 的來源，也是 standby 斷線太久時的救命繩）──
archive_mode = on
archive_command = 'test ! -f /srv/wal/%f && cp %p /srv/wal/%f'
EOF
```

★★★★ 這些參數**哪些要重啟、哪些 reload 就好**，是 PostgreSQL 最常被搞錯的一件事：

| 參數 | 生效方式 | 漏掉會怎樣 |
| --- | --- | --- |
| `wal_level` / `max_wal_senders` / `max_replication_slots` / `wal_log_hints` | ★★★★ **restart** | 只 reload 的話 `SHOW` 出來還是舊值，你以為改好了 |
| `archive_mode` | ★★★★ **restart** | 同上 |
| `archive_command` | reload | — |
| `max_slot_wal_keep_size` / `wal_keep_size` | reload | — |
| `synchronous_standby_names` / `synchronous_commit` | ★★★ reload | 緊急解除同步卡死時**不需要重啟**，這點很重要 |
| `primary_conninfo` / `primary_slot_name`（standby） | ★★★ reload（會重啟 walreceiver） | PostgreSQL 13 起才可 reload，更舊的版本要重啟 |
| `hot_standby_feedback` / `max_standby_streaming_delay` | reload | — |

```bash
sudo pg_ctlcluster 17 main restart
sudo -u postgres psql -c "SELECT name, setting, context FROM pg_settings
  WHERE name IN ('wal_level','max_wal_senders','wal_log_hints','max_slot_wal_keep_size','archive_mode');"
```

預期輸出：

```text
          name          | setting  |  context
------------------------+----------+------------
 archive_mode           | on       | postmaster
 max_slot_wal_keep_size | 65536    | sighup       # ★★ 單位是 MB
 max_wal_senders        | 10       | postmaster
 wal_level              | replica  | postmaster
 wal_log_hints          | on       | postmaster   # ★★★★ 這行是 on 才能用 pg_rewind
```

★★★ `context` 欄就是「怎麼生效」的權威答案：`postmaster` = 要重啟、`sighup` = reload 即可、
`user` = 連線層可改。以後別再猜。

### 【2】複寫角色與 `pg_hba.conf`

```sql
-- 在主庫上執行
CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD '請換成 20 字以上隨機密碼';
```

★★★ `REPLICATION` 是**角色屬性**，不是 `GRANT` 出來的權限；它讓這個角色能開複寫連線，
但**不能讀任何一張表**。這正是我們要的最小權限。角色設計見 [[02-PostgreSQL-角色與權限]]。

```bash
# ★★★★ replication 連線在 pg_hba 是獨立的一種，database 欄位必須寫 replication
sudo -u postgres tee -a /etc/postgresql/17/main/pg_hba.conf > /dev/null << 'EOF'
# TYPE  DATABASE      USER        ADDRESS         METHOD
hostssl replication   replicator  10.0.1.12/32    scram-sha-256
EOF
sudo pg_ctlcluster 17 main reload
```

> [!danger] ★★★★ `pg_hba.conf` 的三個必踩坑（詳見 [[04-PostgreSQL-設定檔與pg_hba]]）
> **①** `DATABASE` 欄寫 `all` **不會**匹配複寫連線 —— 必須明寫 `replication`。
> 這是「帳號密碼都對、就是連不上、錯誤訊息說 no pg_hba.conf entry for replication connection」的唯一原因。
> **②** ★★★★ **由上往下比對，第一條符合的就定案，不會再往下找**。
> 如果上面已經有一條 `host all all 0.0.0.0/0 trust`（安裝時偷懶留下的），你這條永遠不會被用到，
> 而且那條本身就是重大資安缺失。
> **③** `pg_hba.conf` 改完 **reload 就生效**，不用重啟；但 `listen_addresses` 要重啟。
> 用 `SELECT * FROM pg_hba_file_rules;` 可以在不重載的情況下檢查語法與順序。

驗證規則有沒有被讀進去：

```bash
sudo -u postgres psql -c "SELECT line_number, type, database, user_name, address, auth_method, error
  FROM pg_hba_file_rules WHERE 'replication' = ANY(database);"
```

```text
 line_number |  type   |   database    | user_name  |  address  | auth_method  | error
-------------+---------+---------------+------------+-----------+--------------+-------
          98 | hostssl | {replication} | {replicator}| 10.0.1.12 | scram-sha-256|       # ★★★ error 必須是空的
```

### 【3】建立複寫槽

```sql
SELECT * FROM pg_create_physical_replication_slot('pg2_slot');
SELECT slot_name, slot_type, active, wal_status FROM pg_replication_slots;
```

預期輸出：

```text
 slot_name | slot_type | active | wal_status
-----------+-----------+--------+------------
 pg2_slot  | physical  | f      |             # ★★ 還沒有 standby 連上來，active=f 正常
```

★★ 也可以讓 `pg_basebackup -C -S pg2_slot` 幫你建；手動建的好處是**在 base backup 開始前槽就存在**，
備份期間產生的 WAL 一定被保住 —— 資料量大、base backup 要跑數小時的機關系統務必先建。

### 【4】在 standby 上做 base backup

```bash
# ═══ 全部在 pg2 上執行 ═══
# ★★★★ 密碼放 .pgpass，不要寫在指令列（會留在 history 與 ps 裡）
sudo -u postgres bash -c 'umask 077; \
  echo "10.0.1.11:5432:replication:replicator:那組密碼" >> ~postgres/.pgpass'
sudo -u postgres chmod 0600 ~postgres/.pgpass

sudo pg_ctlcluster 17 main stop
# ★★★★★ 下一行會刪掉 standby 上現有的資料。確認你在 pg2、不是 pg1。
sudo -u postgres mv /var/lib/postgresql/17/main /var/lib/postgresql/17/main.old
sudo -u postgres mkdir -m 0700 /var/lib/postgresql/17/main

sudo -u postgres pg_basebackup \
  --host=10.0.1.11 --port=5432 --username=replicator \
  --pgdata=/var/lib/postgresql/17/main \
  --wal-method=stream \
  --slot=pg2_slot \
  --write-recovery-conf \
  --checkpoint=fast \
  --progress --verbose
```

預期輸出：

```text
pg_basebackup: initiating base backup, waiting for checkpoint to complete
pg_basebackup: checkpoint completed
pg_basebackup: write-ahead log start point: 0/A3000028 on timeline 1
pg_basebackup: starting background WAL receiver
 8213476/8213476 kB (100%), 1/1 tablespace
pg_basebackup: write-ahead log end point: 0/A50001C8
pg_basebackup: syncing data to disk ...
pg_basebackup: base backup completed          # ★★★★ 沒看到這行就是失敗，不要往下做
```

各旗標為什麼要加：

| 旗標 | 作用 | 不加會怎樣 |
| --- | --- | --- |
| `--wal-method=stream`（`-X stream`） | 備份期間另開一條連線同步收 WAL | ★★★★ 用 `fetch` 時，備份太久會缺 WAL 而無法啟動 |
| `--slot=pg2_slot`（`-S`） | 綁定複寫槽 | ★★★ 備份期間主庫可能清掉需要的 WAL |
| `--write-recovery-conf`（`-R`） | 自動產生 `standby.signal` 並把 `primary_conninfo` 寫進 `postgresql.auto.conf` | ★★★ 要手工寫，容易漏 |
| `--checkpoint=fast` | 立刻做 checkpoint 而不是等 | 不加的話可能空等十幾分鐘才開始 |
| `--progress --verbose` | 顯示進度 | 大資料量時你會不知道它是在跑還是卡住 |

★★★ `-S` 只能跟 `-X stream` 一起用。要順便建槽就再加 `-C`（`--create-slot`）。

### 【5】standby 的設定

`-R` 已經幫你寫好了，先確認內容：

```bash
sudo -u postgres cat /var/lib/postgresql/17/main/postgresql.auto.conf
ls -l /var/lib/postgresql/17/main/standby.signal
```

```text
# Do not edit this file manually!
primary_conninfo = 'user=replicator passfile=''/var/lib/postgresql/.pgpass'' channel_binding=prefer
  host=10.0.1.11 port=5432 sslmode=prefer ...'
primary_slot_name = 'pg2_slot'
-rw------- 1 postgres postgres 0 Aug 28 10:14 /var/lib/postgresql/17/main/standby.signal
```

★★★★ **`standby.signal` 這個 0 byte 的空檔案，就是「我是 standby」的唯一開關。**
它存在 → 開機進入 recovery 模式；把它刪掉重啟 → 這台立刻變成可寫的主庫。
切換程序的所有小心翼翼，最後都收束在這個檔案上。

補上該有的設定（`ALTER SYSTEM` 會寫進 `postgresql.auto.conf`，優先度高於 `postgresql.conf`）：

```bash
sudo -u postgres tee -a /etc/postgresql/17/main/conf.d/zz-standby.conf > /dev/null << 'EOF'
hot_standby = on
hot_standby_feedback = on          # ★★★ standby 要跑報表就開，代價見「進階設定」
max_standby_streaming_delay = 30s  # ★★★ 預設值；報表查詢會被殺掉的元凶
wal_receiver_timeout = 60s
wal_receiver_status_interval = 10s
restore_command = 'cp /srv/wal/%f %p'   # ★★★★ 串流斷掉時的第二條路
recovery_min_apply_delay = 0            # 之後要做延遲 standby 就改這裡
EOF
```

★★★★ `primary_conninfo` 一定要補兩樣東西 —— **`application_name`**（同步複寫與監控靠它認人）
與 **`sslmode`**（複寫流量是完整的資料副本，不加密等於在內網廣播個資）：

```bash
sudo -u postgres psql -c "ALTER SYSTEM SET primary_conninfo =
  'host=10.0.1.11 port=5432 user=replicator passfile=''/var/lib/postgresql/.pgpass''
   application_name=pg2 sslmode=verify-full sslrootcert=/etc/ssl/certs/ourca.pem';" 2>/dev/null \
  || echo "★ 這條要在 standby 啟動後才能下，先手動編 postgresql.auto.conf"
```

★★★ 自建 CA 與憑證發放見 [[08-用自建CA簽發伺服器憑證]] 與 [[10-憑證部署到各服務]]；
測試環境至少用 `sslmode=require`，正式環境一定要 `verify-full`（否則擋不住中間人）。

### 【6】啟動並驗證

```bash
sudo pg_ctlcluster 17 main start
sudo -u postgres psql -c "SELECT pg_is_in_recovery();"
```

```text
 pg_is_in_recovery
-------------------
 t                    # ★★★★ t = 這台是 standby。是 f 就代表你建出了第二個主庫，立刻停下來
```

主庫這邊：

```sql
SELECT application_name, client_addr, state, sync_state,
       sent_lsn, write_lsn, flush_lsn, replay_lsn
FROM pg_stat_replication;
```

```text
 application_name | client_addr | state     | sync_state | sent_lsn  | write_lsn | flush_lsn | replay_lsn
------------------+-------------+-----------+------------+-----------+-----------+-----------+------------
 pg2              | 10.0.1.12   | streaming | async      | 0/A50003F8| 0/A50003F8| 0/A50003F8| 0/A50003F8
```

★★★★ `state` 要是 **`streaming`**。看到 `catchup` 代表還在追（剛建起來時正常，持續數小時就不正常）。
**一列都沒有 = 複寫根本沒接上**，這是最該告警的狀態。

standby 這邊：

```sql
SELECT status, sender_host, slot_name, latest_end_lsn, latest_end_time FROM pg_stat_wal_receiver;
```

```text
  status   | sender_host | slot_name | latest_end_lsn |        latest_end_time
-----------+-------------+-----------+----------------+-------------------------------
 streaming | 10.0.1.11   | pg2_slot  | 0/A50003F8     | 2026-08-28 10:21:44.113+08
```

端到端測試（★★★ 一定要做，`state=streaming` 不代表資料真的到得了）：

```bash
# pg1
sudo -u postgres psql -c "CREATE TABLE IF NOT EXISTS repl_probe(id int, ts timestamptz);"
sudo -u postgres psql -c "INSERT INTO repl_probe VALUES (1, now());"
# pg2（等一秒）
sudo -u postgres psql -c "SELECT * FROM repl_probe;"
```

```text
 id |              ts
----+-------------------------------
  1 | 2026-08-28 10:22:07.418291+08   # ★★★★ 看得到才算複寫真的通了
```

### 【7】確認 standby 真的寫不進去

```bash
sudo -u postgres psql -c "INSERT INTO repl_probe VALUES (2, now());"
```

```text
ERROR:  cannot execute INSERT in a read-only transaction
```

★★★★ 這個錯誤是**好消息**。PostgreSQL 的 standby 是物理層唯讀，
**連 superuser 也寫不進去** —— 這一點比 MySQL 的 `read_only`（`SUPER` 帳號可繞過）安全得多，
你不需要像 [[06-MySQL-主從複寫]] 那樣去操心 `super_read_only`。

---

## 進階設定與調校

### ★★★★ 三種延遲，你該告警哪一個

```sql
SELECT application_name,
       write_lag, flush_lag, replay_lag,
       pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS behind_bytes
FROM pg_stat_replication;
```

```text
 application_name | write_lag | flush_lag | replay_lag | behind_bytes
------------------+-----------+-----------+------------+--------------
 pg2              | 00:00:00.001| 00:00:00.002| 00:00:00.31|      1245184
```

| 欄位 | 意思 | 代表什麼問題 |
| --- | --- | --- |
| `write_lag` | 主庫 commit → standby **寫進 OS** 的時間 | ★★★ 大 = **網路**慢或頻寬不足 |
| `flush_lag` | → standby **fsync 落磁碟** | ★★★ 大 = standby 的**磁碟寫入**慢 |
| `replay_lag` | → standby **重放完、查得到** | ★★★★ 大 = **startup process 追不上**（單執行緒瓶頸、鎖衝突） |
| `behind_bytes` | LSN 落差（byte） | ★★★★ **最誠實的指標**，不受時鐘與閒置影響 |

在 standby 上另一個角度：

```sql
SELECT pg_last_wal_receive_lsn() AS received,
       pg_last_wal_replay_lsn()  AS replayed,
       pg_last_xact_replay_timestamp() AS last_xact,
       now() - pg_last_xact_replay_timestamp() AS behind_time;
```

```text
  received  |  replayed  |          last_xact          |  behind_time
------------+------------+-----------------------------+----------------
 0/A5100000 | 0/A50F8000 | 2026-08-28 10:31:02.7+08    | 00:00:00.42
```

> [!danger] ★★★★★ `behind_time` 在兩種情況下會騙你，而且騙得很兇
> **①** **主庫閒置**（深夜沒交易）→ `pg_last_xact_replay_timestamp()` 停在最後一筆交易的時間，
> `behind_time` 會一路長到「8 小時」，但複寫其實好好的。只看這個數字的告警會半夜狂叫。
> **②** ★★★★★ **walreceiver 斷線但 WAL 已重放完** → `replay_lag` 是 `NULL`、
> `behind_time` 可能很小，但實際上你已經落後數天。
> **正解：把「`pg_stat_wal_receiver` 有沒有那一列」與「`behind_bytes`」一起看。**
> 這跟 [[06-MySQL-主從複寫]] 裡 `Seconds_Behind_Source: 0` 的假綠燈是同一個陷阱，
> 換了資料庫，人性沒變。

### ★★★★ standby 跑報表：`canceling statement due to conflict with recovery`

這是機關把報表移到 standby 之後，第一週一定會收到的抱怨。

```text
ERROR:  canceling statement due to conflict with recovery
DETAIL:  User query might have needed to see row versions that must be removed.
```

成因：主庫的 `VACUUM` 清掉了某些舊版本的列，這個清除動作透過 WAL 傳過來，
standby 上正在跑的長查詢還需要那些列 → 兩者衝突 →
**等 `max_standby_streaming_delay`（預設 30 秒）之後，PostgreSQL 選擇殺掉查詢、保住複寫進度**。

三種處理方式，各有代價：

| 做法 | 設定 | 代價 |
| --- | --- | --- |
| 讓 standby 反向告訴主庫「我還在用」 | `hot_standby_feedback = on` | ★★★★ **主庫的 VACUUM 會被拖住 → table bloat 變嚴重**。standby 上一個忘了關的查詢，可以讓主庫的表膨脹到數十 GB |
| 允許重放延後久一點 | `max_standby_streaming_delay = 5min` | ★★★★ 切換時 standby 可能落後 5 分鐘 → **RPO 直接變差** |
| 兩者都不動，報表改在主庫或改用邏輯複寫副本 | — | ★★ 主庫多一份負載，但故障模式最單純 |

★★★★ 本手冊的建議：**開 `hot_standby_feedback = on`，同時在主庫設 `idle_in_transaction_session_timeout`
與監控最長交易時間**，把「忘了 commit 的連線拖垮主庫」這條路堵死。
把 `max_standby_streaming_delay` 調到分鐘級是最糟的選擇 —— 它拿你最在意的 RPO 去換報表順暢。

### 同步複寫的正確開法

```bash
sudo -u postgres psql -c "ALTER SYSTEM SET synchronous_standby_names = 'ANY 1 (pg2, pg3)';"
sudo pg_ctlcluster 17 main reload
sudo -u postgres psql -c "SELECT application_name, sync_state FROM pg_stat_replication;"
```

```text
 application_name | sync_state
------------------+------------
 pg2              | quorum       # ★★★ ANY 語法下是 quorum，FIRST 語法下才叫 sync
 pg3              | quorum
```

| 寫法 | 語意 |
| --- | --- |
| `'pg2'` | ★★★★★ 只認 pg2。**pg2 一掛，主庫全部寫入卡死** |
| `'FIRST 1 (pg2, pg3)'` | 優先等 pg2，pg2 不在就等 pg3 |
| `'ANY 1 (pg2, pg3)'` | ★★★★ **兩台任一台回應即可**，建議寫法 |
| `''`（空字串） | 退回非同步。★★★★ **緊急解卡就是設成這個再 reload** |

> [!tip] ★★★★ 把「解除同步卡死」寫成一行貼在 runbook 第一頁
> ```bash
> sudo -u postgres psql -c "ALTER SYSTEM SET synchronous_standby_names = '';" \
>   && sudo pg_ctlcluster 17 main reload
> ```
> 半夜三點、寫入全卡、一堆電話進來的時候，沒有人想得起來語法。

### 延遲 standby：誤刪資料的緩衝墊

```bash
sudo -u postgres psql -c "ALTER SYSTEM SET recovery_min_apply_delay = '1h';"
sudo pg_ctlcluster 17 main reload
```

★★★ 這台 standby 會**永遠慢主庫一小時**。有人誤刪資料時，一小時內你可以：

```sql
SELECT pg_wal_replay_pause();                    -- ★★★★ 第一件事：先按暫停，別讓它重放過去
SELECT pg_get_wal_replay_pause_state();          -- 'paused'
-- 從這台把資料撈出來，或直接 promote 成獨立的救援庫
```

★★★★ 但它**不能同時當高可用備援**（永遠落後一小時，切過去等於掉一小時資料），
所以延遲 standby 是**第三台**，不是把主備那台改設定。真正的誤刪救援還是 PITR，見 [[05-PostgreSQL-備份與還原]]。

### 級聯複寫與邏輯複寫

```text
pg1（主庫） ──► pg2（standby，開 hot_standby + 本身也當 sender）──► pg3（級聯 standby）
                 ★★★ 異地那台掛在 pg2 後面，主庫只需要負擔一條 walsender
```

級聯只需要在 pg3 的 `primary_conninfo` 指向 pg2。★★★ 注意 pg2 被 promote 時，
pg3 會透過 timeline history 自動跟上（`recovery_target_timeline = 'latest'`）。

邏輯複寫本篇不當主備方案，但兩個情境值得知道：

```sql
-- 主庫（需 wal_level = logical，★★★★ 這個要重啟）
CREATE PUBLICATION pub_app FOR TABLE public.案件, public.附件;
-- 訂閱端
CREATE SUBSCRIPTION sub_app
  CONNECTION 'host=10.0.1.11 dbname=appdb user=replicator password=...'
  PUBLICATION pub_app;
```

> [!info]- ★★★ PostgreSQL 16／17 在複寫上的新東西（版本相依，動手前先確認你的版本）
> | 版本 | 功能 | 為什麼對維運有意義 |
> | --- | --- | --- |
> | 16 | 可在 **standby 上做邏輯解碼** | 把資料整合／CDC 的負擔從主庫移走 |
> | 17 | **`pg_createsubscriber`** | 把既有的物理 standby **原地轉成邏輯訂閱者**，不用重新複製一次資料 —— 跨大版本升級（16→17）時省下數小時 |
> | 17 | **failover slots**：`sync_replication_slots = on` + `synchronized_standby_slots` | ★★★★ 以前主庫故障切換時，邏輯複寫的槽會消失、下游要重來；17 起可以自動同步到 standby |
> | 17 | `pg_basebackup --incremental` + `pg_combinebackup` | 增量 base backup，見 [[05-PostgreSQL-備份與還原]] |
>
> failover slot 的兩個前提：standby 必須用 `primary_slot_name` 連（物理槽），
> 且 standby 上 `hot_standby_feedback = on`。
> ```sql
> -- 主庫：建立可故障切換的邏輯槽
> SELECT pg_create_logical_replication_slot('sub_app', 'pgoutput', false, false, true);
> SELECT slot_name, failover, synced FROM pg_replication_slots;
> ```
> ★★ 這一段是 17 才有的路，16 上請沿用「切換後在新主庫重建邏輯訂閱」的做法。

### 自動切換要不要做

PostgreSQL 核心**沒有內建自動故障切換**。要自動化就得引入外部元件：

| 方案 | 做什麼 | 什麼時候值得 |
| --- | --- | --- |
| **人工切換 + runbook + 定期演練** | 本篇主線 | ★★★★ 絕大多數機關系統。RTO 5 分鐘可接受時，這是最可靠的 |
| **repmgr** | 監控 + 輔助切換指令 | 想要半自動、指令統一 |
| **Patroni + etcd/Consul** | 分散式共識自動選主 | ★★★ 需要秒級自動切換、且有人力長期維運 etcd |
| **HAProxy / pgbouncer + VIP** | 連線層導流，讓應用不必改連線字串 | ★★★★ 幾乎一定要有，否則切換得改應用設定 |

> [!warning] ★★★★ 自動切換會讓故障模式變多，不是變少
> Patroni 之類的方案把「人判斷錯」換成「網路分割時系統判斷錯」。
> 沒有可靠的 fencing（把舊主庫真的關掉）時，自動切換**製造雙寫的機率比人工還高**。
> 導入前先確認：etcd 有沒有三個節點、網路是不是穩定、有沒有人看得懂 Patroni 的日誌。
> 選型的通盤討論見 [[04-高可用與負載平衡架構]]。

---

## 完整實戰範例

情境：某機關的線上申辦系統（Nuxt + Laravel + PostgreSQL 17），
主庫 `pg1` 已上線，現在要建 standby、上監控，並在下次維護時窗做一次**計畫性切換演練**。

### (A) 一鍵建 standby：`/usr/local/bin/pg-standby-build.sh`

```bash
sudo tee /usr/local/bin/pg-standby-build.sh > /dev/null << 'EOF'
#!/usr/bin/env bash
# 在 standby 主機上執行，把本機重建為指定主庫的串流 standby。
# ★★★★★ 這支腳本會刪掉本機現有的 PostgreSQL 資料，只准在 standby 上跑。
set -euo pipefail

PRIMARY="${PRIMARY:-10.0.1.11}"
PGVER="${PGVER:-17}"
CLUSTER="${CLUSTER:-main}"
SLOT="${SLOT:-pg2_slot}"
APPNAME="${APPNAME:-pg2}"
REPLUSER="${REPLUSER:-replicator}"
PGDATA="/var/lib/postgresql/${PGVER}/${CLUSTER}"
PGCONF="/etc/postgresql/${PGVER}/${CLUSTER}"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="${PGDATA}.old-${STAMP}"

log()  { printf '%s [%s] %s\n' "$(date '+%F %T')" "$1" "$2"; }
die()  { log FATAL "$1"; exit 1; }

step_precheck() {
  log STEP "【1】前置檢查"
  [[ "$(id -u)" -eq 0 ]] || die "請用 root 或 sudo 執行"
  command -v pg_basebackup >/dev/null || die "找不到 pg_basebackup，PostgreSQL client 沒裝?"

  # ★★★★★ 防呆：本機若是主庫（不在 recovery 且有應用連線）就中止
  if sudo -u postgres psql -tAc "SELECT pg_is_in_recovery()" 2>/dev/null | grep -qx 'f'; then
    local n
    n="$(sudo -u postgres psql -tAc "SELECT count(*) FROM pg_stat_activity
         WHERE backend_type='client backend' AND pid<>pg_backend_pid()" 2>/dev/null || echo 0)"
    [[ "$n" -eq 0 ]] || die "本機看起來是有 ${n} 條應用連線的主庫。中止。"
    log WARN "本機是主庫但無應用連線；5 秒後繼續，Ctrl-C 可中止"
    sleep 5
  fi

  # 版本必須一致
  local vlocal vremote
  vlocal="$(pg_config --version | awk '{print $2}' | cut -d. -f1)"
  vremote="$(sudo -u postgres psql -h "$PRIMARY" -U "$REPLUSER" -d postgres -tAc \
             "SHOW server_version" 2>/dev/null | cut -d. -f1 || true)"
  [[ -n "$vremote" ]] || die "連不到主庫 ${PRIMARY}（檢查 pg_hba、防火牆、.pgpass）"
  [[ "$vlocal" == "$vremote" ]] || die "版本不一致：本機 ${vlocal}、主庫 ${vremote}。物理複寫要求大版本相同"
  log OK "主庫 ${PRIMARY} 可連線，版本 ${vremote}"

  # 磁碟空間：主庫資料量的 1.2 倍
  local need avail
  need="$(sudo -u postgres psql -h "$PRIMARY" -U "$REPLUSER" -d postgres -tAc \
          "SELECT sum(pg_database_size(datname))/1024/1024 FROM pg_database" | cut -d. -f1)"
  avail="$(df -Pm "$(dirname "$PGDATA")" | awk 'NR==2{print $4}')"
  (( avail > need * 12 / 10 )) || die "空間不足：需要約 $((need*12/10)) MB，只有 ${avail} MB"
  log OK "空間充足（需要約 $((need*12/10)) MB，可用 ${avail} MB）"
}

step_slot() {
  log STEP "【2】確認主庫上的複寫槽 ${SLOT}"
  local exists
  exists="$(sudo -u postgres psql -h "$PRIMARY" -U "$REPLUSER" -d postgres -tAc \
            "SELECT count(*) FROM pg_replication_slots WHERE slot_name='${SLOT}'")"
  if [[ "$exists" == "0" ]]; then
    die "主庫上沒有槽 ${SLOT}。請先在主庫執行：SELECT pg_create_physical_replication_slot('${SLOT}');"
  fi
  log OK "槽存在"
}

step_stop_and_move() {
  log STEP "【3】停服務並把現有資料目錄改名保留（★★★★ 這就是回滾點）"
  pg_ctlcluster "$PGVER" "$CLUSTER" stop --skip-systemctl-redirect || true
  if [[ -d "$PGDATA" ]]; then
    mv "$PGDATA" "$BACKUP"
    log OK "舊資料目錄已移到 ${BACKUP}"
  fi
  install -d -o postgres -g postgres -m 0700 "$PGDATA"
}

step_basebackup() {
  log STEP "【4】pg_basebackup（資料量大時會跑很久）"
  if ! sudo -u postgres pg_basebackup \
        --host="$PRIMARY" --username="$REPLUSER" \
        --pgdata="$PGDATA" --wal-method=stream --slot="$SLOT" \
        --write-recovery-conf --checkpoint=fast --progress --verbose; then
    log FATAL "pg_basebackup 失敗，執行回滾"
    rollback
    exit 1
  fi
  log OK "base backup 完成"
}

step_conf() {
  log STEP "【5】補 standby 專屬設定與 application_name"
  # ★★★★ Debian 系的設定檔在 /etc，pg_basebackup 不會帶過來，這裡自己補
  install -d -o postgres -g postgres "${PGCONF}/conf.d"
  sudo -u postgres tee "${PGCONF}/conf.d/zz-standby.conf" > /dev/null <<CONF
hot_standby = on
hot_standby_feedback = on
max_standby_streaming_delay = 30s
wal_receiver_timeout = 60s
restore_command = 'cp /srv/wal/%f %p'
CONF
  # application_name 直接改寫 auto.conf 裡的 primary_conninfo
  sudo -u postgres sed -i \
    "s|^primary_conninfo = '\(.*\)'|primary_conninfo = '\1 application_name=${APPNAME}'|" \
    "${PGDATA}/postgresql.auto.conf"
  grep -q 'application_name' "${PGDATA}/postgresql.auto.conf" \
    || die "primary_conninfo 補 application_name 失敗，請手動檢查 postgresql.auto.conf"
  [[ -f "${PGDATA}/standby.signal" ]] || die "找不到 standby.signal —— pg_basebackup 沒帶 -R?"
  log OK "設定完成"
}

step_start_verify() {
  log STEP "【6】啟動並驗證"
  pg_ctlcluster "$PGVER" "$CLUSTER" start
  local i=0
  until sudo -u postgres psql -tAc "SELECT 1" >/dev/null 2>&1; do
    i=$((i+1)); (( i < 60 )) || die "60 秒內沒有起來，看 /var/log/postgresql/"
    sleep 1
  done
  [[ "$(sudo -u postgres psql -tAc 'SELECT pg_is_in_recovery()')" == "t" ]] \
    || die "★★★★★ 本機不在 recovery 模式 —— 它變成第二個主庫了，立刻停機處理"

  local st
  i=0
  until st="$(sudo -u postgres psql -tAc "SELECT status FROM pg_stat_wal_receiver")"; [[ "$st" == "streaming" ]]; do
    i=$((i+1)); (( i < 120 )) || die "120 秒內沒進入 streaming（目前：${st:-無})"
    sleep 1
  done
  log OK "walreceiver 狀態 streaming"

  # ★★★★ 端到端驗證：主庫寫一筆，這裡讀得到才算數
  local token="probe-${STAMP}"
  sudo -u postgres psql -h "$PRIMARY" -U postgres -d postgres \
    -c "CREATE TABLE IF NOT EXISTS repl_probe(t text, ts timestamptz default now());" \
    -c "INSERT INTO repl_probe(t) VALUES ('${token}');" >/dev/null
  i=0
  until sudo -u postgres psql -tAc "SELECT count(*) FROM repl_probe WHERE t='${token}'" | grep -qx '1'; do
    i=$((i+1)); (( i < 30 )) || die "30 秒內讀不到探測資料，複寫沒有真的通"
    sleep 1
  done
  log OK "端到端驗證通過"
}

rollback() {
  log STEP "【R】回滾：還原原本的資料目錄"
  pg_ctlcluster "$PGVER" "$CLUSTER" stop --skip-systemctl-redirect || true
  if [[ -d "$BACKUP" ]]; then
    rm -rf "$PGDATA"; mv "$BACKUP" "$PGDATA"
    pg_ctlcluster "$PGVER" "$CLUSTER" start || log WARN "回滾後啟動失敗，需人工處理"
    log OK "已回滾到 ${STAMP} 之前的狀態"
  else
    log WARN "沒有可回滾的備份目錄（原本就是空的）"
  fi
}

trap 'log FATAL "第 ${LINENO} 行失敗"; rollback' ERR

step_precheck
step_slot
step_stop_and_move
step_basebackup
step_conf
step_start_verify
trap - ERR

log DONE "standby 建置完成。★★★ 確認無誤後手動刪除 ${BACKUP} 釋放空間"
EOF

sudo chmod 750 /usr/local/bin/pg-standby-build.sh
```

執行與預期輸出：

```bash
sudo PRIMARY=10.0.1.11 SLOT=pg2_slot APPNAME=pg2 /usr/local/bin/pg-standby-build.sh
```

```text
2026-08-28 11:02:11 [STEP] 【1】前置檢查
2026-08-28 11:02:12 [OK] 主庫 10.0.1.11 可連線，版本 17
2026-08-28 11:02:12 [OK] 空間充足（需要約 9856 MB，可用 204800 MB）
2026-08-28 11:02:12 [STEP] 【2】確認主庫上的複寫槽 pg2_slot
...
2026-08-28 11:09:47 [OK] 端到端驗證通過
2026-08-28 11:09:47 [DONE] standby 建置完成。★★★ 確認無誤後手動刪除 /var/lib/postgresql/17/main.old-20260828-110211
```

### (B) 監控腳本：`/usr/local/bin/pg-repl-check.sh`

```bash
sudo tee /usr/local/bin/pg-repl-check.sh > /dev/null << 'EOF'
#!/usr/bin/env bash
# 在 standby 上每分鐘執行。exit 0=正常 1=警告 2=嚴重
set -uo pipefail

PRIMARY="${PRIMARY:-10.0.1.11}"
LAG_WARN_MB="${LAG_WARN_MB:-64}"
LAG_CRIT_MB="${LAG_CRIT_MB:-512}"
SLOTMAX_PCT="${SLOTMAX_PCT:-70}"
STATEFILE=/run/pg-repl-check.state
ALERT_CMD="${ALERT_CMD:-}"
PSQL='sudo -u postgres psql -tAc'

RC=0; MSGS=()
warn() { MSGS+=("WARN: $1"); [[ $RC -lt 1 ]] && RC=1 || true; }
crit() { MSGS+=("CRIT: $1"); RC=2; }

# ── 【1】本機必須在 recovery（★★★★★ 不是的話代表意外變成主庫）──
INREC="$($PSQL "SELECT pg_is_in_recovery()" 2>/dev/null || echo "?")"
case "$INREC" in
  t) : ;;
  f) crit "本機不在 recovery —— 它已經是主庫了，檢查是否誤 promote（雙寫風險）" ;;
  *) crit "連不上本機 PostgreSQL"; printf '%s\n' "${MSGS[@]}"; exit 2 ;;
esac

# ── 【2】walreceiver 是否活著（★★★★ 這一項比任何秒數都重要）──
WR="$($PSQL "SELECT status FROM pg_stat_wal_receiver" 2>/dev/null)"
[[ "$WR" == "streaming" ]] || crit "walreceiver 狀態=[${WR:-無此列}]，串流已中斷"

# ── 【3】LSN 落差（byte，不受時鐘與閒置影響）──
if PRI_LSN="$($PSQL "SELECT pg_current_wal_lsn()" -h "$PRIMARY" 2>/dev/null)"; then
  DIFF="$($PSQL "SELECT pg_wal_lsn_diff('${PRI_LSN}', pg_last_wal_replay_lsn())::bigint" 2>/dev/null)"
  MB=$(( DIFF / 1048576 ))
  if   (( MB > LAG_CRIT_MB )); then crit "落後 ${MB} MB（門檻 ${LAG_CRIT_MB} MB）"
  elif (( MB > LAG_WARN_MB )); then warn "落後 ${MB} MB（門檻 ${LAG_WARN_MB} MB）"
  fi
else
  warn "連不到主庫 ${PRIMARY}，無法比對 LSN（主庫可能已故障 → 準備切換）"
fi

# ── 【4】★★★★★ 主庫的複寫槽是否快撐爆（這一項救的是主庫，不是 standby）──
if [[ -n "${PRI_LSN:-}" ]]; then
  SLOTINFO="$($PSQL "SELECT slot_name||' '||coalesce(wal_status,'?')||' '||
      coalesce(round(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)/1048576)::text,'?')
      FROM pg_replication_slots" -h "$PRIMARY" 2>/dev/null || true)"
  MAXMB="$($PSQL "SELECT setting::bigint FROM pg_settings WHERE name='max_slot_wal_keep_size'" \
           -h "$PRIMARY" 2>/dev/null || echo -1)"
  while read -r name status mb; do
    [[ -n "${name:-}" ]] || continue
    case "$status" in
      lost)       crit "複寫槽 ${name} 已失效(lost) —— 該 standby 必須重建" ;;
      unreserved) crit "複寫槽 ${name} 保留的 WAL 已超出上限，即將失效" ;;
    esac
    if (( MAXMB > 0 )) && [[ "$mb" =~ ^[0-9]+$ ]] && (( mb * 100 / MAXMB > SLOTMAX_PCT )); then
      warn "複寫槽 ${name} 已拖住 ${mb} MB WAL（上限 ${MAXMB} MB）"
    fi
  done <<< "$SLOTINFO"
fi

# ── 【5】pg_wal 分割區用量（★★★★ 主庫停機的最後一道防線）──
if PGWAL_PCT="$(ssh -o BatchMode=yes -o ConnectTimeout=5 postgres@"$PRIMARY" \
      "df -P /var/lib/postgresql/17/main/pg_wal | awk 'NR==2{print \$5}' | tr -d %" 2>/dev/null)"; then
  (( PGWAL_PCT > 85 )) && crit "主庫 pg_wal 分割區已用 ${PGWAL_PCT}%"
  (( PGWAL_PCT > 70 && PGWAL_PCT <= 85 )) && warn "主庫 pg_wal 分割區已用 ${PGWAL_PCT}%"
fi

# ── 輸出與去重告警 ──
if [[ ${#MSGS[@]} -eq 0 ]]; then
  echo "OK 複寫正常 lag=${MB:-?}MB receiver=${WR}"
  rm -f "$STATEFILE"
else
  printf '%s\n' "${MSGS[@]}"
  NEW="$(printf '%s\n' "${MSGS[@]}" | md5sum | cut -d' ' -f1)"
  OLD="$(cat "$STATEFILE" 2>/dev/null || true)"
  if [[ "$NEW" != "$OLD" && -n "$ALERT_CMD" ]]; then
    "$ALERT_CMD" "[pg2] PostgreSQL 複寫異常" "$(printf '%s\n' "${MSGS[@]}")" || true
  fi
  echo "$NEW" > "$STATEFILE"
fi
exit "$RC"
EOF

sudo chmod 750 /usr/local/bin/pg-repl-check.sh
```

★★★★ **監控帳號不要用 superuser**。`pg_monitor` 這個預設角色剛好夠：

```sql
CREATE ROLE replcheck LOGIN PASSWORD '……';
GRANT pg_monitor TO replcheck;     -- ★★★ 含 pg_read_all_stats，看得到 pg_stat_replication 全欄位
```

驗證（★★★ **刻意製造故障確認腳本抓得到**，這一步是演練必做）：

```bash
sudo /usr/local/bin/pg-repl-check.sh; echo "exit=$?"
# 在主庫上暫時擋掉 standby
sudo ssh 10.0.1.11 "ufw insert 1 deny from 10.0.1.12 to any port 5432"
sleep 70
sudo /usr/local/bin/pg-repl-check.sh; echo "exit=$?"
sudo ssh 10.0.1.11 "ufw delete 1"
```

```text
OK 複寫正常 lag=0MB receiver=streaming
exit=0
CRIT: walreceiver 狀態=[無此列]，串流已中斷
exit=2                                    # ★★★★ 有抓到才算數
```

排程（systemd timer 寫法見 [[02-systemd-timer與cron選型]]）：

```bash
sudo tee /etc/systemd/system/pg-repl-check.service > /dev/null << 'EOF'
[Unit]
Description=PostgreSQL replication health check
[Service]
Type=oneshot
Environment=ALERT_CMD=/usr/local/bin/send-alert.sh
ExecStart=/usr/local/bin/pg-repl-check.sh
EOF
sudo tee /etc/systemd/system/pg-repl-check.timer > /dev/null << 'EOF'
[Unit]
Description=Run PostgreSQL replication check every minute
[Timer]
OnBootSec=3min
OnUnitActiveSec=1min
[Install]
WantedBy=timers.target
EOF
sudo systemctl daemon-reload && sudo systemctl enable --now pg-repl-check.timer
systemctl list-timers pg-repl-check.timer --no-pager
```

```text
NEXT                        LEFT  LAST                        PASSED  UNIT
Fri 2026-08-28 11:41:00 CST  42s  Fri 2026-08-28 11:39:58 CST  20s ago pg-repl-check.timer
```

### (C) 計畫性切換 runbook

> [!danger] ★★★★★ 每一步都是為了防雙寫，不要跳步
> PostgreSQL 的雙寫是**靜默的** —— 兩台各自在自己的 timeline 上收資料，
> 誰都不會報錯。等你發現時，兩邊都有對方沒有的公文，而且**沒有工具能自動合併**。

**【1】公告與維護模式**（依 [[08-變更管理流程]] 走時窗與通知）

```bash
ssh app1 "cd /var/www/app && php artisan down --render=errors::503 --retry=120"
```

**【2】切換前檢查：確定現在可以切**

```bash
sudo -u postgres psql -h 10.0.1.11 -c "SELECT application_name, state, sync_state,
  pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS behind_bytes FROM pg_stat_replication;"
sudo -u postgres psql -h 10.0.1.11 -c "SELECT pid, state, now()-xact_start AS dur, query
  FROM pg_stat_activity WHERE xact_start IS NOT NULL ORDER BY dur DESC LIMIT 5;"
```

```text
 application_name |   state   | sync_state | behind_bytes
------------------+-----------+------------+--------------
 pg2              | streaming | async      |         8192   # ★★★★ 必須 streaming、落差要小
```

★★★★ 看到有跑了幾十分鐘的交易就**先處理它再切**，否則【3】的關機會等很久或被 `-m fast` 中斷。

**【3】主庫停止服務（乾淨關機，這是最關鍵的一步）**

```bash
sudo -u postgres psql -h 10.0.1.11 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
  WHERE backend_type='client backend' AND usename NOT IN ('postgres','replicator');"
sudo ssh 10.0.1.11 "pg_ctlcluster 17 main stop -m fast"
sudo ssh 10.0.1.11 "pg_lsclusters"
```

```text
Ver Cluster Port Status Owner    Data directory              Log file
17  main    5432 down   postgres /var/lib/postgresql/17/main /var/log/postgresql/postgresql-17-main.log
```

★★★★★ **`down` 才能往下走。** 主庫還活著就 promote standby = 雙寫。
機關環境還要多做一件事：**確認它不會被自動拉起來**
（`systemctl mask postgresql@17-main`，切換完再 unmask）。

**【4】確認 standby 收完了所有 WAL**

```bash
sudo ssh 10.0.1.11 "/usr/lib/postgresql/17/bin/pg_controldata /var/lib/postgresql/17/main" \
  | grep -E "Latest checkpoint location|Database cluster state"
sudo -u postgres psql -c "SELECT pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn();"
```

```text
Database cluster state:               shut down            # ★★★★ 乾淨關機
Latest checkpoint location:           0/A9000060
 pg_last_wal_receive_lsn | pg_last_wal_replay_lsn
-------------------------+------------------------
 0/A9000110              | 0/A9000110               # ★★★★★ 必須 >= 上面那個 checkpoint location
```

★★★★★ 兩個數字對不起來就**中止切換**、把主庫拉回來。「差一點點應該沒關係」在這裡等於資料遺失。

**【5】promote**

```bash
sudo pg_ctlcluster 17 main promote
sudo -u postgres psql -c "SELECT pg_is_in_recovery();"
sudo -u postgres psql -c "SELECT timeline_id FROM pg_control_checkpoint();"
```

```text
 pg_is_in_recovery
-------------------
 f                     # ★★★★ f = 已經是主庫

 timeline_id
-------------
           2           # ★★★ timeline 從 1 跳到 2，這是不可逆的分水嶺
```

**【6】新主庫補上主庫該有的設定**

```bash
sudo -u postgres psql -c "SELECT pg_create_physical_replication_slot('pg1_slot');"
sudo -u postgres psql -c "ALTER SYSTEM SET hot_standby_feedback = 'off';"   # 它現在是主庫了
sudo pg_ctlcluster 17 main reload
ls -l /etc/postgresql/17/main/pg_hba.conf      # ★★★★ 應用那幾條規則在不在？
```

★★★★ 這是 Debian 系那個坑的清算時刻：如果當初沒把 `pg_hba.conf` 同步過來，
**現在應用會全部連不上，而且你正在維護時窗裡**。

**【7】舊主庫用 `pg_rewind` 降級為 standby**

```bash
sudo ssh 10.0.1.11 "pg_lsclusters | grep -q down" || { echo "★ 舊主庫還在跑，先停"; exit 1; }
sudo -u postgres /usr/lib/postgresql/17/bin/pg_rewind \
  --target-pgdata=/var/lib/postgresql/17/main \
  --source-server="host=10.0.1.12 port=5432 user=postgres dbname=postgres" \
  --config-file=/etc/postgresql/17/main/postgresql.conf \
  --write-recovery-conf --progress --dry-run
```

```text
pg_rewind: connected to server
pg_rewind: servers diverged at WAL location 0/A9000110 on timeline 1
pg_rewind: rewinding from last common checkpoint at 0/A8000098 on timeline 1
pg_rewind: Done!                       # ★★★ --dry-run 不會真的改動，先跑這個確認可行
```

確認可行後拿掉 `--dry-run` 再跑一次，然後：

```bash
sudo -u postgres sed -i "s/10.0.1.11/10.0.1.12/" /var/lib/postgresql/17/main/postgresql.auto.conf
sudo -u postgres psql -c "ALTER SYSTEM SET primary_slot_name = 'pg1_slot';" 2>/dev/null || true
sudo pg_ctlcluster 17 main start
sudo -u postgres psql -c "SELECT pg_is_in_recovery();"    # 預期 t
```

> [!warning] ★★★★ `pg_rewind` 的四個前提，缺一就得整台重做
> **①** 主庫當初有設 `wal_log_hints = on` 或 cluster 建立時開了 data checksums
> （`SHOW data_checksums;` 確認；PostgreSQL 17 以前 `initdb` 預設不開）。
> **②** 目標（舊主庫）必須**乾淨關機**。不是的話 pg_rewind 會自己用 single-user 模式補跑復原，
> 在 Debian 上這一步**需要 `--config-file` 指到 `/etc`**，否則它找不到設定檔。
> **③** 來源（新主庫）用 superuser 連，或依官方文件把 `pg_read_binary_file` 等函式 `GRANT EXECUTE`。
> **④** ★★★★★ **pg_rewind 中途失敗的話，目標資料目錄就報廢了**，只能重新 `pg_basebackup`。
> 所以先 `--dry-run`，並確保 (A) 那支腳本隨時可以用。

**【8】應用切過去**

```bash
ssh app1 "sed -i 's/^DB_HOST=.*/DB_HOST=10.0.1.12/' /var/www/app/.env \
  && php artisan config:cache && systemctl reload php8.3-fpm"
```

★★★ 有 HAProxy／VIP 的話這一步改成切導流，應用完全不用動 —— 這就是為什麼值得多裝一層。

**【9】解除維護模式並驗證**

```bash
ssh app1 "cd /var/www/app && php artisan up"
curl -sS -o /dev/null -w '%{http_code}\n' https://app.example.gov.tw/healthz
sudo -u postgres psql -c "SELECT application_name, state FROM pg_stat_replication;"
```

```text
200
 application_name |   state
------------------+-----------
 pg1              | streaming        # ★★★★ 方向反過來了，複寫仍然是雙向可用的
```

> [!tip] ★★★★ 回滾點在哪裡
> **【6】之前**都可以回滾：把 pg2 停掉、刪掉 `standby.signal` 之外的變更、
> 重新 `pg_basebackup`，然後把 pg1 拉起來當主庫。
> **【8】之後就不能了** —— 應用已經往 pg2 寫入，pg2 上有 pg1 沒有的資料。
> 這時候硬把應用指回 pg1 = 那些新資料全部消失，而且兩邊永久分歧。
> 正解是「繼續用 pg2，把 pg1 修好當 standby」，之後再排一次完整切換切回去。

### 切換演練與耗時紀錄

| 步驟 | 動作 | 目標耗時 | 實測 | 備註 |
| --- | --- | --- | --- | --- |
| 【1】 | 應用進維護模式 | < 10s | 7s | `artisan down` |
| 【2】 | 切換前檢查 | < 60s | 22s | 有 1 條 12 分鐘的長交易先處理 |
| 【3】 | 主庫乾淨關機 + mask | < 60s | 31s | ★★★★ `-m fast` 等連線結束 |
| 【4】 | LSN 比對 | < 30s | 11s | |
| 【5】 | promote | < 20s | 4s | timeline 1 → 2 |
| 【6】 | 新主庫補設定 | < 60s | 38s | 建槽、關 feedback |
| 【7】 | 舊主庫 `pg_rewind` | < 10min | 3m12s | 含 dry-run |
| 【8】 | 應用切連線 | < 60s | 26s | |
| 【9】 | 驗證 + 解除維護 | < 60s | 44s | |
| | **對使用者的中斷（RTO）** | **< 5 分鐘** | **2 分 43 秒** | ★★★ 【7】在服務恢復後做，不計入 |

### 驗收檢查表

| # | 檢查項 | 指令 | 預期結果 | 星級 |
| --- | --- | --- | --- | --- |
| 1 | 兩台大版本一致 | `psql -c "SHOW server_version"` | 同一個大版本 | ★★★★ |
| 2 | standby 在 recovery | `SELECT pg_is_in_recovery();` | `t` | ★★★★★ |
| 3 | 複寫狀態 streaming | `SELECT state FROM pg_stat_replication;` | `streaming` | ★★★★ |
| 4 | walreceiver 活著 | `SELECT status FROM pg_stat_wal_receiver;` | `streaming` | ★★★★ |
| 5 | 使用複寫槽 | `SELECT slot_name, active FROM pg_replication_slots;` | `active = t` | ★★★★ |
| 6 | ★★★★★ 槽有上限 | `SHOW max_slot_wal_keep_size;` | 非 `-1` | ★★★★★ |
| 7 | `wal_log_hints` 已開 | `SHOW wal_log_hints;` | `on` | ★★★★ |
| 8 | 複寫走 TLS | `SELECT ssl FROM pg_stat_ssl JOIN pg_stat_replication USING(pid);` | `t` | ★★★★ |
| 9 | LSN 落差 | 本篇 `pg_wal_lsn_diff` 查詢 | < 64 MB | ★★★★ |
| 10 | standby 寫不進去 | `INSERT` 測試 | `read-only transaction` 錯誤 | ★★★ |
| 11 | 端到端資料真的到 | 探測表 | 讀得到 | ★★★★ |
| 12 | WAL 歸檔正常 | `SELECT * FROM pg_stat_archiver;` | `last_failed_time` 為空 | ★★★★★ |
| 13 | `pg_hba.conf` 已同步到 standby | `diff` 兩台的檔案 | 只有預期差異 | ★★★★ |
| 14 | 監控會抓到故障 | 擋掉 5432 後跑檢查腳本 | `exit=2` 並告警 | ★★★★ |
| 15 | 防火牆只放行 standby | `sudo ufw status numbered` | 5432 僅 `10.0.1.12` | ★★★★ |
| 16 | ★★★★ 備份仍照常執行 | `systemctl list-timers \| grep backup` | 排程存在且成功 | ★★★★★ |
| 17 | 切換演練有紀錄 | 上方耗時表 | 已填寫並歸檔 | ★★★ |

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ **主庫 `PANIC: No space left on device` 後停機，`pg_wal` 幾百 GB** | 複寫槽對應的 standby 早就離線，槽把 WAL 全保住了；`max_slot_wal_keep_size = -1` | 緊急：`SELECT pg_drop_replication_slot('xxx');` 釋放（該 standby 之後要重建）。長期：設 `max_slot_wal_keep_size` 並監控 `pg_replication_slots.wal_status` |
| ★★★★★ **所有寫入都卡住，`pg_stat_activity` 一片 `wait_event=SyncRep`** | `synchronous_standby_names` 指定的唯一 standby 離線 | `ALTER SYSTEM SET synchronous_standby_names='';` + `reload` 立刻解除；改用 `ANY 1 (…)` |
| ★★★★★ **切換後發現兩台都有對方沒有的資料** | 舊主庫沒有真的停止就 promote 了 standby（雙寫） | 立刻停掉其中一邊；用 `pg_waldump` 比對分岔點後人工判讀。**沒有自動合併的方法** |
| ★★★★ **`FATAL: no pg_hba.conf entry for replication connection from host …`** | `pg_hba.conf` 的 DATABASE 欄寫了 `all`（不匹配複寫），或規則排在一條更寬鬆的規則後面 | 明寫 `replication`；用 `SELECT * FROM pg_hba_file_rules;` 檢查順序，見 [[04-PostgreSQL-設定檔與pg_hba]] |
| ★★★★ **standby 啟動失敗 `requested WAL segment … has already been removed`** | standby 離線太久，主庫已清掉需要的 WAL（沒用槽或槽被清） | 有 WAL 歸檔就設好 `restore_command` 讓它補；沒有就整台重建 |
| ★★★★ **standby 啟動即 `FATAL: database files are incompatible with server`** | 兩台 PostgreSQL 大版本不同 | 物理複寫要求大版本一致；先對齊版本再重做 base backup |
| ★★★★ **報表查詢一直被殺：`canceling statement due to conflict with recovery`** | 主庫 VACUUM 清掉了查詢還需要的列版本，超過 `max_standby_streaming_delay` | 開 `hot_standby_feedback = on`（代價是主庫 bloat）；或把長報表移回主庫 |
| ★★★★ **主庫的表急速膨脹、`VACUUM` 清不掉** | standby 開了 `hot_standby_feedback` 又有人在上面掛著一個永不結束的查詢 | 找出 standby 上的長查詢殺掉；設 `idle_in_transaction_session_timeout`；見 [[06-PostgreSQL-效能調校與索引]] |
| ★★★★ **`pg_stat_archiver.last_failed_time` 一直更新，`pg_wal` 緩慢長大** | `archive_command` 失敗（目的地滿、NFS 斷、SELinux 擋、`%p` `%f` 寫錯） | 手動跑一次 `archive_command` 看錯誤；★★★ 歸檔失敗時 PostgreSQL **會一直重試並保留 WAL**，不會放棄 |
| ★★★★ **promote 之後其他 standby 全部斷線** | 它們還跟著舊 timeline，且沒有 timeline history 可循 | 確認 `recovery_target_timeline = 'latest'`（預設）；把新主庫的 `.history` 檔放進歸檔目錄 |
| ★★★ **`pg_rewind` 報 `target server needs to use either data checksums or wal_log_hints = on`** | 建 cluster 時沒開 checksums，且主庫從未設 `wal_log_hints` | 這次只能重做 standby；事後補 `wal_log_hints = on`（要重啟）以備下次 |
| ★★★ **切換後應用全部連不上、`no pg_hba.conf entry`** | Debian 系 `pg_basebackup` 不會複製 `/etc/postgresql/` 下的設定檔 | 把 `postgresql.conf` / `pg_hba.conf` 納入版控並 rsync 到 standby；納入驗收檢查表第 13 項 |
| ★★★ **`could not connect to server: Connection refused` 但主庫明明活著** | 主庫 `listen_addresses` 還是 `localhost` | 改成明確 IP（不建議 `*`）後**重啟**（這個參數不能 reload） |
| ★★★ **複寫每隔 60 秒斷一次又自己好** | 中間防火牆／NAT 回收閒置連線；或 `wal_sender_timeout` 太短 | 調整防火牆 session timeout；`wal_receiver_status_interval` 設得比 timeout 小很多 |
| ★★★ **`pg_basebackup` 跑到一半失敗 `requested WAL segment has already been removed`** | 用了 `-X fetch` 且備份時間太長 | 改用 `-X stream`，並先建好複寫槽再備份 |
| ★★ **`pg_stat_replication` 有列但 `state = catchup` 卡很久** | 初次同步或斷線後補資料；或 standby 磁碟太慢 | 看 `sent_lsn` 有沒有在動；持續數小時就檢查 standby 的 I/O |
| ★★ **`SELECT pg_promote()` 回傳 `f`** | 60 秒內沒完成 promote（還在重放大量 WAL） | 用 `pg_promote(true, 300)` 拉長等待，或改用 `pg_ctlcluster … promote` 後自行輪詢 |

### 排查步驟

**【1】先問一句：主庫還活著嗎？**

```bash
pg_isready -h 10.0.1.11 -p 5432
```

```text
10.0.1.11:5432 - accepting connections     # → 主庫活著，走【2】（是複寫問題）
10.0.1.11:5432 - no response               # → 主庫掛了，走【8】（進入故障切換判斷）
```

**【2】standby 上：連線層還是重放層？**

```bash
sudo -u postgres psql -x -c "SELECT status, sender_host, latest_end_time FROM pg_stat_wal_receiver;"
```

```text
(0 rows)                          # ★★★★ 完全沒有 walreceiver → 連線層問題，走【3】
status | streaming                # 連線正常 → 是延遲不是中斷，走【6】
```

**【3】看 standby 的日誌，錯誤訊息會直接告訴你往哪走**

```bash
sudo tail -50 /var/log/postgresql/postgresql-17-main.log
```

```text
FATAL:  could not connect to the primary server: connection to server ... failed
        → 出現 "no pg_hba.conf entry"  → 走【4】（授權）
        → 出現 "Connection refused"    → 主庫 listen_addresses 或服務沒起來
        → 出現 "Connection timed out"  → ★★★ 防火牆，走【5】
        → 出現 "password authentication failed" → .pgpass 權限或密碼錯
FATAL:  requested WAL segment 0000000100000000000000B2 has already been removed
        → ★★★★ WAL 被清了，槽沒生效或沒用槽。看有沒有歸檔可以補，沒有就重建
```

**【4】授權：在 standby 上直接用複寫協定連連看**

```bash
sudo -u postgres psql "host=10.0.1.11 user=replicator dbname=replication replication=true" -c "IDENTIFY_SYSTEM;"
```

```text
      systemid       | timeline |  xlogpos   | dbname
---------------------+----------+------------+--------
 7412398745120983412 |        1 | 0/AB0001C8 |          # ★★★ 成功 → 授權沒問題，回頭看 primary_conninfo
```

★★★★ 這一招是分辨「帳號問題」與「設定問題」最快的方法 ——
它用的是跟 walreceiver 完全一樣的連線路徑。

**【5】網路層**

```bash
nc -zv 10.0.1.11 5432
sudo ssh 10.0.1.11 "ufw status numbered | grep 5432"
```

```text
Connection to 10.0.1.11 5432 port [tcp/postgresql] succeeded!   # 通 → 問題在授權或 TLS
nc: connect to 10.0.1.11 port 5432 (tcp) timed out              # ★★★ 防火牆
```

**【6】是延遲：先判斷卡在收還是卡在放**

```sql
SELECT pg_wal_lsn_diff(pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn()) AS unreplayed_bytes;
```

```text
 unreplayed_bytes
------------------
        932184064      # ★★★★ 收到了但沒放完 → 重放跟不上，走【7】
                 0      # 收到就放完了 → 是「收不夠快」，看網路頻寬與主庫 walsender
```

**【7】重放跟不上：看 startup process 在等什麼**

```sql
SELECT pid, backend_type, wait_event_type, wait_event, state
FROM pg_stat_activity WHERE backend_type = 'startup';
```

```text
 pid  | backend_type | wait_event_type |     wait_event      | state
------+--------------+-----------------+---------------------+-------
 1123 | startup      | IO              | WALRead             |         # 磁碟 I/O 瓶頸
 1123 | startup      | Lock            | relation            |         # ★★★★ 被 standby 上的查詢擋住
 1123 | startup      | Timeout         | RecoveryRetrieveRetryInterval | # 在等 WAL，其實不是它慢
```

★★★★ 看到 `Lock / relation`：standby 上有查詢鎖住了重放要改的表。
這正是 `max_standby_streaming_delay` 在倒數的情境 —— 要嘛殺掉查詢，要嘛接受延遲。

**【8】主庫真的掛了：切還是不切？**

先確認**主庫是真的死了，不是網路分割**（否則你會製造雙寫）：

```bash
ping -c 3 10.0.1.11                       # 從第三台（例如 app1）ping，不要只從 standby ping
sudo ssh 10.0.1.11 "pg_lsclusters"        # 進得去就代表機器活著，只是 DB 掛了
```

- ★★★★★ **從第三個點確認不到主庫是死的 → 不要 promote**，先處理網路。
- 主庫死透了 → 走切換 runbook 的【4】【5】【6】【8】【9】（跳過【1】【2】【3】，因為已經沒得停）。
- ★★★★ promote 之前，**確保舊主庫不會自己活過來**：`systemctl mask postgresql@17-main`
  或直接把它的網路卡關掉。這就是 fencing。

---

## 安全性注意事項

> [!danger] ★★★★★ 絕對禁止：`pg_hba.conf` 裡出現 `trust` 或 `0.0.0.0/0`
> ```text
> host all all 0.0.0.0/0 trust        # ★★★★★ 任何人連上 5432 就是 superuser，不用密碼
> host replication all  0.0.0.0/0 md5 # ★★★★★ 只要猜到密碼，任何人都能 pg_basebackup 走整個資料庫
> ```
> 第二行的後果要講清楚：複寫連線可以**完整複製整個 cluster 的資料檔**。
> 對方不需要 SELECT 權限、不需要知道表名，一句 `pg_basebackup` 就把全部個資帶走，
> 而且主庫的日誌只會留下一筆看起來很正常的複寫連線。
> 這在個資法下是「未採取適當安全維護措施」的典型案例，見 [[07-台灣資安法規與個資法]]。

> [!danger] ★★★★★ standby 是完整的個資副本，保護等級必須與主庫相同
> 機關最常見的疏漏：主庫做了磁碟加密、限制登入、納入弱點掃描，
> **standby 因為「只是備援」被放在管制較鬆的機房或 VLAN**。
> 對攻擊者來說，standby 上的資料和主庫一模一樣，而且沒有人在看它的日誌。
> 檢核時要一起納入：作業系統強化（[[08-系統強化與稽核]]）、
> 存取控制、稽核軌跡（[[09-資安稽核與符合性檢核]])、實體安全。

> [!danger] ★★★★ 複寫流量不加密 = 把整個資料庫在內網上廣播
> 沒有 `sslmode=require` 以上的設定時，WAL 內容（含所有欄位值）是明文在網路上跑。
> 內網不是可信網路 —— 一台被入侵的印表機就能抓到。
> 正確做法：`pg_hba.conf` 用 `hostssl`（不是 `host`）強制加密，
> `primary_conninfo` 用 `sslmode=verify-full` + 自建 CA 的 `sslrootcert`，
> 見 [[08-用自建CA簽發伺服器憑證]] 與 [[10-憑證部署到各服務]]。
> ★★★ 只寫 `sslmode=require` 擋不住中間人 —— 它加密但不驗證對方是誰。

> [!warning] ★★★★ 最小權限的四個具體落點
> **①** 複寫角色只給 `REPLICATION LOGIN`，**不要給 superuser** —— 它連一張表都不該讀得到。
> **②** 監控帳號用 `GRANT pg_monitor`，不要用 `postgres`。
> **③** `.pgpass` 權限必須 `0600` 且 owner 是 `postgres`；權限不對 libpq 會**靜默忽略整個檔案**，
> 然後你會看到莫名其妙的密碼錯誤。
> **④** ★★★★ 複寫帳號的密碼**與應用帳號分開**，並納入 [[12-憑證生命週期管理]] 那套輪換節奏。

> [!warning] ★★★ WAL 歸檔目錄與備份的保護
> `/srv/wal` 裡的 WAL 檔可以還原出完整資料庫 —— 它的保護等級等同備份。
> 權限 `0700`、owner `postgres`、傳輸加密、異地副本要加密儲存。
> 稽核情境下要能回答「誰在什麼時候讀取過歸檔」，所以歸檔目錄要納入 FIM 監控，
> 見 [[04-Wazuh-FIM檔案完整性監控]]。

★★★ **切換要留稽核軌跡**：誰在什麼時候 promote、為什麼、影響哪些系統、多久恢復。
這份紀錄是 [[09-事件處理與升級流程]] 的產出，也是年度資安稽核會被問到的東西。
`log_line_prefix` 建議含 `%m [%p] %q%u@%d %a` 讓事後查得出是誰下的指令。

---

## 速查表

### 判斷「現在健不健康」的四個指令

| 指令 | 在哪台 | 健康的樣子 | 星級 |
| --- | --- | --- | --- |
| `SELECT pg_is_in_recovery();` | standby | `t` | ★★★★★ |
| `SELECT state, sync_state FROM pg_stat_replication;` | 主庫 | `streaming` | ★★★★ |
| `SELECT status FROM pg_stat_wal_receiver;` | standby | `streaming` | ★★★★ |
| `SELECT slot_name, active, wal_status FROM pg_replication_slots;` | 主庫 | `t` / `reserved` | ★★★★★ |

### 延遲與落差

| 查詢 | 意義 | 星級 |
| --- | --- | --- |
| `pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)` | 主庫視角的落後 byte 數（**最誠實**） | ★★★★ |
| `pg_wal_lsn_diff(pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn())` | 收到但還沒放的量 → 重放瓶頸 | ★★★★ |
| `now() - pg_last_xact_replay_timestamp()` | 時間落差（★★★ 主庫閒置時會假性變大） | ★★★ |
| `replay_lag` 欄位 | 主庫測得的重放延遲（閒置時是 NULL） | ★★★ |

### 關鍵設定項

| 參數 | 建議值 | 生效方式 | 漏掉的後果 | 星級 |
| --- | --- | --- | --- | --- |
| `max_slot_wal_keep_size` | `64GB`（依 `pg_wal` 分割區調整） | reload | ★★★★★ 主庫磁碟滿而停機 | ★★★★★ |
| `wal_log_hints` | `on` | **restart** | 切換後不能用 `pg_rewind` | ★★★★ |
| `synchronous_standby_names` | `ANY 1 (pg2, pg3)` 或空 | reload | 單台同步 standby 掛掉 = 全站寫入卡死 | ★★★★★ |
| `hot_standby_feedback` | `on`（standby 有報表時） | reload | 報表被殺／主庫 bloat（取捨） | ★★★★ |
| `max_standby_streaming_delay` | `30s`（不建議調大） | reload | 調大會直接惡化 RPO | ★★★★ |
| `archive_mode` / `archive_command` | `on` / 可靠的搬移指令 | restart / reload | 沒有 PITR、斷線太久救不回 | ★★★★★ |
| `recovery_target_timeline` | `latest`（預設） | restart | promote 後其他 standby 接不上 | ★★★ |
| `recovery_min_apply_delay` | 延遲 standby 才設 | reload | — | ★★ |

### 檔案與路徑（Ubuntu／Debian）

| 路徑 | 是什麼 | 星級 |
| --- | --- | --- |
| `/var/lib/postgresql/17/main/standby.signal` | ★★★★★ 存在 = 這台是 standby | ★★★★★ |
| `/var/lib/postgresql/17/main/postgresql.auto.conf` | `ALTER SYSTEM` 與 `-R` 寫這裡，**優先度最高** | ★★★★ |
| `/etc/postgresql/17/main/postgresql.conf` | 主設定；★★★★ `pg_basebackup` **不會**複製 | ★★★★ |
| `/etc/postgresql/17/main/pg_hba.conf` | 授權規則；同上，要自己同步 | ★★★★ |
| `/var/lib/postgresql/17/main/pg_wal/` | WAL；★★★★★ 這裡爆掉主庫就停機 | ★★★★★ |
| `/var/log/postgresql/postgresql-17-main.log` | 排錯第一站 | ★★★★ |
| `~postgres/.pgpass` | 複寫密碼；★★★ 必須 `0600` | ★★★ |

### 切換與救援指令

| 指令 | 用途 | 星級 |
| --- | --- | --- |
| `pg_ctlcluster 17 main promote` | standby 升主（Debian 系） | ★★★★★ |
| `SELECT pg_promote(true, 300);` | 同上，SQL 版，可設等待秒數 | ★★★★ |
| `SELECT pg_wal_replay_pause();` | ★★★★ 誤刪救援時的第一個動作 | ★★★★ |
| `pg_rewind --dry-run …` | 舊主庫降級前的可行性確認 | ★★★★ |
| `SELECT pg_drop_replication_slot('x');` | ★★★★★ 槽撐爆磁碟時的急救（該 standby 要重建） | ★★★★★ |
| `ALTER SYSTEM SET synchronous_standby_names='';` | ★★★★★ 同步卡死時解卡 | ★★★★★ |
| `pg_controldata <PGDATA>` | 看 cluster state、timeline、checkpoint 位置 | ★★★★ |

---

## 練習題

> [!question]- 練習 1：把「槽撐爆磁碟」演一次給自己看
> 在測試環境把 `max_slot_wal_keep_size` 設成 `256MB`，關掉 standby，
> 然後在主庫用 `pgbench` 或迴圈灌資料直到槽失效。觀察 `pg_replication_slots.wal_status` 的變化，
> 並記錄從 `reserved` 到 `lost` 的過程。最後把 standby 開回來，確認它救不回來。
>
> **參考解答**
> **① 觀察順序**：`reserved`（正常）→ `extended`（超過 `wal_keep_size` 但還在 slot 上限內）
> → `unreserved`（超過上限，隨時會失效）→ ★★★★ `lost`（WAL 已被刪，槽報廢）。
> ```sql
> SELECT slot_name, wal_status, safe_wal_size,
>        pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS held
> FROM pg_replication_slots;
> ```
> **② standby 開回來的結果**：日誌出現
> `FATAL: requested WAL segment ... has already been removed`，服務起不來。
> **③ 結論**：`max_slot_wal_keep_size` 是「犧牲 standby 保主庫」的開關。
> 有 WAL 歸檔 + `restore_command` 的話還有第二條路可以救 —— 這就是為什麼歸檔不能省。
> ★★★★ 把 `wal_status` 納入監控（本篇腳本的【4】就是在做這件事）。

> [!question]- 練習 2：製造一次 recovery conflict，量化兩種設定的代價
> 在 standby 上跑一個 5 分鐘的長查詢（`SELECT pg_sleep(300)` 搭配一個大表的 `SELECT`），
> 同時在主庫對同一張表大量 `UPDATE` 並手動 `VACUUM`。
> 分別在 `hot_standby_feedback = off` 與 `on` 兩種設定下觀察結果。
>
> **參考解答**
> **① `off` 時**：約 30 秒（`max_standby_streaming_delay`）後查詢被殺：
> `ERROR: canceling statement due to conflict with recovery`。
> 用 `SELECT * FROM pg_stat_database_conflicts;` 可以看到 `confl_snapshot` 計數增加。
> **② `on` 時**：查詢跑完了，但主庫上
> `SELECT n_dead_tup FROM pg_stat_user_tables WHERE relname='…';` 顯示死列一直累積清不掉，
> `pg_total_relation_size` 持續變大。
> **③ 量化**：記錄兩種設定下「查詢成功率」與「主庫表膨脹百分比」。
> ★★★★ 結論是這兩者不可兼得，只能選一個並管理它的副作用
> （選 `on` 就必須監控 standby 上的最長查詢時間）。

> [!question]- 練習 3：完整走一次切換 + `pg_rewind` 降級 + 切回來
> 依 runbook 的【1】~【9】做一次切換，填完耗時表；
> 接著把 pg1 用 `pg_rewind` 降級為 standby，確認方向反過來的複寫正常；
> 一週後再排一次切換切回去。最後回答：如果【3】那步主庫沒有真的停止，會發生什麼？
>
> **參考解答**
> **① 驗證重點**：切換後 pg2 `pg_is_in_recovery()` 為 `f`、timeline = 2、
> pg1 `pg_is_in_recovery()` 為 `t` 且 `pg_stat_wal_receiver.sender_host = 10.0.1.12`。
> **② `pg_rewind` 的兩個常見卡點**：目標沒乾淨關機（Debian 上要補 `--config-file`）、
> `wal_log_hints` 沒開（只能整台重做）。
> **③ 主庫沒真的停止的後果**：★★★★★ 應用切到 pg2 之後，
> 如果還有任何連線（批次程式、忘了改的排程、監控寫入）連著 pg1，
> 兩台會各自在 timeline 1 與 timeline 2 上累積資料。
> `pg_rewind` 會把 pg1 上那些交易**直接丟棄**（這正是它的工作），資料永久消失。
> 所以【3】的 `pg_lsclusters` 顯示 `down` 與 `systemctl mask` 這兩個動作不能省。

---

## 小測驗

Q1. 是非題：「有了 PostgreSQL 串流複寫，每天的 `pg_dump` 與 WAL 歸檔可以改成每週一次。」

Q2. 你在 standby 上執行 `SELECT now() - pg_last_xact_replay_timestamp();` 得到 `08:12:33`。這一定代表複寫壞了嗎？你會再查哪兩件事？

Q3. 主庫的 `pg_wal` 目錄從 8 GB 長到 300 GB，磁碟快滿了。列出你的檢查順序，以及最後的止血手段與它的代價。

Q4. 選擇題：只有一台 standby 的系統，`synchronous_standby_names` 應該設成？(A) `'pg2'` (B) `''`（空，非同步）(C) `'ANY 1 (pg2)'` (D) `'FIRST 1 (pg2)'`

Q5. 這行指令會發生什麼事：在一台正常運作的 standby 上執行 `rm /var/lib/postgresql/17/main/standby.signal` 然後 `pg_ctlcluster 17 main restart`。

Q6. `pg_hba.conf` 裡已經有 `host all all 10.0.1.0/24 scram-sha-256`，你在檔案最後加了 `hostssl replication replicator 10.0.1.12/32 scram-sha-256` 並 reload，結果 standby 仍然報 `no pg_hba.conf entry for replication connection`。為什麼？

Q7. 簡答：計畫性切換時，為什麼「`pg_stat_replication` 顯示 `streaming` 且落差為 0」還不足以直接 promote？你還要比對什麼？

Q8. standby 上的報表查詢一直被 `canceling statement due to conflict with recovery` 殺掉。同事建議把 `max_standby_streaming_delay` 改成 `30min`。這個建議的代價是什麼？你會怎麼做？

Q9. 主庫故障切換後，你想把舊主庫接回來當 standby，直接在它的資料目錄建 `standby.signal`、設好 `primary_conninfo` 就啟動。會發生什麼？正確做法是什麼？

Q10. MySQL 的複寫斷在某筆交易時可以「注入空交易跳過」。PostgreSQL 的 standby 重放卡住時，能不能跳過那筆 WAL？為什麼？

> [!question]- 測驗答案
> **Q1. 錯，而且這是本篇最重要的一題。** ★★★★★
> 複寫與備份防的是完全不同的威脅。複寫防「硬體故障與單點」，
> 備份防「誤操作、勒索加密、應用邏輯 bug」。
> `DROP TABLE` 的 WAL 會在 0.03 秒內忠實重放到每一台 standby —— 你有兩台機器，但你有零份資料。
> 而且 PostgreSQL 還多一層關係：**WAL 歸檔同時是 PITR 的來源與 standby 斷線太久時的救命繩**，
> 停掉歸檔等於同時廢掉兩個機制。
> 相反地，有了 standby 你應該**多做備份**：把 `pg_dump` 移到 standby 上跑，不再影響主庫。
> 參見「先講死一次：複寫不是備份」與 [[05-PostgreSQL-備份與還原]]。
>
> **Q2. 不一定。** ★★★★
> `pg_last_xact_replay_timestamp()` 回傳的是「最後重放的那筆交易在主庫的提交時間」。
> 主庫深夜八小時沒有任何寫入時，這個數字就會長到 8 小時，但複寫完全正常。
> 要再查兩件事：
> **①** `SELECT status FROM pg_stat_wal_receiver;` —— 有沒有那一列、是不是 `streaming`。
> 沒有那一列才是真的斷線。
> **②** `SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), pg_last_wal_replay_lsn())`（連主庫查）——
> byte 落差是 0 就代表真的追平了。
> ★★★★ 監控告警**不要只用時間差**，會半夜狂叫；也不要只用 byte 差，會漏掉「主庫掛了」。
> 兩個都要，而且 walreceiver 存在與否的權重最高。參見「三種延遲，你該告警哪一個」。
>
> **Q3. 檢查順序有三層。** ★★★★★
> **①** `SELECT * FROM pg_stat_archiver;` —— `last_failed_time` 一直在更新代表歸檔失敗，
> PostgreSQL 會**保留所有未歸檔的 WAL 並無限重試**，這是第一大元凶。
> **②** `SELECT slot_name, active, wal_status,
> pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) FROM pg_replication_slots;`
> —— `active = f` 而且拖住幾百 GB 的槽，就是第二大元凶。
> **③** 有沒有超長交易（`pg_stat_activity` 的 `xact_start`）擋住 checkpoint。
> **止血手段**：`SELECT pg_drop_replication_slot('那個槽');`。
> ★★★★ 代價是那台 standby 之後必須整台重建（除非歸檔還在，可用 `restore_command` 補）。
> **永久解**：設 `max_slot_wal_keep_size` 並把 `wal_status` 納入監控。
> 參見「複寫槽：保命繩，也是絞索」。
>
> **Q4. (B) 空字串，也就是非同步。** ★★★★★
> (A)(C)(D) 三個寫法在「只有一台 standby」時是等價的災難：
> **pg2 一離線（維護、重開機、網路抖動），主庫的每個 commit 都會無限期等待**，
> 整個系統的寫入完全停止，`pg_stat_activity` 一片 `wait_event = SyncRep`。
> 你把單點故障從一台變成兩台 —— 任一台掛掉服務都不能用。
> 同步複寫的正確前提是**至少兩台 standby** 並用 `ANY 1 (pg2, pg3)`。
> ★★★★ 如果業務真的不能掉最後幾筆交易而預算只有一台，
> 正解是「非同步 + 縮短 RPO（更頻繁的歸檔）+ 在應用層做冪等重送」，不是硬開同步。
> 參見「同步還是非同步」與「同步複寫的正確開法」。
>
> **Q5. 這台會變成一個獨立的、可寫的主庫，而且是在原本的 timeline 上。** ★★★★★
> `standby.signal` 是「我是 standby」的唯一開關，刪掉重啟就結束 recovery。
> ★★★★★ 危險在於：這**不是 promote** —— 它不會產生新的 timeline history 檔，
> 而且如果原主庫還活著、應用還連著它，你現在有**兩個都在寫的主庫**，
> 兩邊各自累積資料，誰都不會報錯。
> 這就是 PostgreSQL 雙寫的典型製造方式，而且沒有任何工具能自動合併。
> 正確的升主方式永遠是 `pg_ctlcluster 17 main promote` 或 `SELECT pg_promote();`，
> 而且**在確認舊主庫已經 `down` 之後才做**。參見「timeline」與切換 runbook 的【3】【5】。
>
> **Q6. 因為 `pg_hba.conf` 由上往下比對，第一條符合的就定案。** ★★★★
> 但這一題的陷阱不在順序 —— `host all all …` 的 `DATABASE` 欄寫 `all`，
> ★★★★ **`all` 不匹配複寫連線**。複寫是獨立的一種連線類型，必須明寫 `replication`。
> 所以第一條規則根本沒被套用，第二條又……其實會被套用。
> 真正會踩到的情況是：上面已經有一條 `host replication all 10.0.1.0/24 reject`，
> 或是你改的是別的 cluster 的 `pg_hba.conf`（多版本共存時很常見）。
> 排查用：
> ```sql
> SELECT line_number, database, user_name, address, auth_method, error FROM pg_hba_file_rules;
> SHOW hba_file;   -- ★★★★ 先確認你改的是不是這一個檔案
> ```
> 參見【2】那一段與 [[04-PostgreSQL-設定檔與pg_hba]]。
>
> **Q7. 因為那是「切換前」的狀態，你要的是「主庫停止寫入之後」的狀態。** ★★★★★
> `streaming` 只說明連線正常；落差 0 是查詢當下的快照，下一毫秒主庫又寫了新資料。
> 正確順序是：**先把主庫乾淨關機**（`pg_ctlcluster … stop -m fast`），
> 再比對兩個數字：
> ```bash
> pg_controldata <PGDATA> | grep -E "Database cluster state|Latest checkpoint location"
> # standby:
> SELECT pg_last_wal_receive_lsn();
> ```
> `Database cluster state` 必須是 `shut down`，且 standby 的 receive LSN
> 必須 **≥** 主庫的 shutdown checkpoint location。
> ★★★★★ 對不起來就中止切換，不要「差一點點應該沒關係」。參見 runbook 的【3】【4】。
>
> **Q8. 代價是直接惡化 RPO，這是拿最重要的東西換最不重要的。** ★★★★
> `max_standby_streaming_delay = 30min` 的意思是「允許 standby 的重放落後主庫 30 分鐘」。
> 平常沒事，但**主庫故障要切換的那一刻，你可能損失 30 分鐘的資料**，
> 而且切換前要等它把 30 分鐘的 WAL 重放完，RTO 也一起變差。
> 較好的做法有三個，依序考慮：
> **①** `hot_standby_feedback = on`（讓主庫不要清掉 standby 還在用的列），
> 代價是主庫 bloat —— 但配合 `idle_in_transaction_session_timeout` 與長查詢監控是可控的。
> **②** 把那支報表最佳化（多半是缺索引或全表掃描），見 [[06-PostgreSQL-效能調校與索引]]。
> **③** 報表另外用邏輯複寫做一份副本，跟高可用的 standby 分開。
> 參見「standby 跑報表」那一段。
>
> **Q9. 它會啟動失敗，或更糟 —— 看起來成功但資料是錯的。** ★★★★
> 舊主庫在 timeline 1 上有新主庫（timeline 2）沒有的 WAL，
> 兩者已經分岔。直接掛上去時日誌會出現
> `new timeline 2 forked off current database system timeline 1 before current recovery point`。
> 正確做法二選一：
> **①** `pg_rewind`（快，通常幾分鐘）—— 把舊主庫倒回分岔點再接上。
> 前提是當初有 `wal_log_hints = on` 或 data checksums，而且目標乾淨關機。
> ★★★ Debian 上還要加 `--config-file=/etc/postgresql/17/main/postgresql.conf`。
> **②** 整台重做 `pg_basebackup`（慢，但一定成功）—— 就是本篇 (A) 那支腳本。
> ★★★★ `pg_rewind` 會**丟棄**舊主庫上那些沒複寫出去的交易，
> 執行前先確認那些交易是不是重要的（用 `pg_waldump` 看分岔點之後的內容）。
> 參見 runbook 的【7】。
>
> **Q10. 不能，而且不該去找方法。** ★★★★★
> MySQL 的 binlog（ROW 模式）記的是「哪張表的哪一列從 A 變成 B」，是邏輯層的事件，
> 跳過一筆的後果侷限在那一列。
> **PostgreSQL 的 WAL 記的是「哪個檔案的第幾個 block 的哪些 byte 改成什麼」，是物理層的。**
> 跳過一筆 = 資料檔上留一個洞 = 之後每一筆重放都建立在錯誤的基礎上，
> 索引會指向不存在的 tuple，`SELECT` 可能回傳垃圾或直接 crash。
> PostgreSQL 也因此**沒有提供**任何「跳過 WAL 記錄」的介面。
> 卡住時的正解只有兩個：**修好讓它繼續重放**（補 WAL、修連線、解掉擋住的鎖），
> 或**整台重建 standby**。
> ★★★ 這也是為什麼 PostgreSQL 的複寫「壞得比較少，但壞了就得重來」，
> 而備份與歸檔的重要性比 MySQL 更高。參見「PostgreSQL vs MySQL」對照表。

---

## 延伸閱讀

- [[05-PostgreSQL-備份與還原]] — ★★★★★ 本篇一直在說「那個要看這篇」的那篇。WAL 歸檔、PITR 與還原演練
- [[04-PostgreSQL-設定檔與pg_hba]] — ★★★★ `pg_hba.conf` 的比對順序與 `replication` 那一列，本篇最常出錯的地方
- [[02-PostgreSQL-角色與權限]] — `replicator` 與 `replcheck` 的最小權限設計、`pg_monitor` 預設角色
- [[06-PostgreSQL-效能調校與索引]] — standby 追不上時，減少主庫 WAL 產生量的手段
- [[08-PostgreSQL-安全強化]] — TLS 強制、稽核軌跡、個資保護；本篇 `hostssl` 的完整前置作業
- [[06-MySQL-主從複寫]] — ★★★★ 對照組。同一件事在 MySQL 怎麼做、故障模式差在哪
- [[04-高可用與負載平衡架構]] — Patroni / HAProxy / VIP 的選型，以及自動切換值不值得
- [[03-系統監控與告警]] / [[04-健康檢查與可用性監控]] — 把本篇四個指標接進既有監控
- [[08-變更管理流程]] / [[09-事件處理與升級流程]] — 切換演練的公告、紀錄與事後檢討
- PostgreSQL 17 高可用與複寫：<https://www.postgresql.org/docs/17/high-availability.html>
- 熱備援與 standby 設定：<https://www.postgresql.org/docs/17/warm-standby.html>
- `pg_basebackup` / `pg_rewind`：<https://www.postgresql.org/docs/17/app-pgbasebackup.html>、<https://www.postgresql.org/docs/17/app-pgrewind.html>
- 監控用的統計視圖：<https://www.postgresql.org/docs/17/monitoring-stats.html>
