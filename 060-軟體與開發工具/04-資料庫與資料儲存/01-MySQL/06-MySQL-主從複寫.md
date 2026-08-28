---
title: "MySQL 主從複寫"
desc: "用 GTID 建立可維運的 MySQL 主從複寫：延遲判讀、複寫中斷修復與零雙寫的切換程序"
aliases: [replication, 主從, GTID, SHOW REPLICA STATUS, CHANGE REPLICATION SOURCE TO, 讀寫分離]
tags: [群組/軟體與開發工具, 服務/mysql, 主題/高可用, 主題/複寫]
category: 資料庫與資料儲存
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[05-MySQL-備份與還原]]", "[[02-MySQL-使用者與權限]]", "[[04-MySQL-設定檔與調校]]"]
updated: 2026-08-28
---

# MySQL 主從複寫

> [!abstract] 這篇你會學到
> - 用 **GTID** 在兩台 Ubuntu 上建起一套**真的能維運**的主從複寫（不是跑得起來就好）
> - 看懂 `SHOW REPLICA STATUS` 的每一個關鍵欄位，知道 **`Seconds_Behind_Source` 什麼時候在騙你**
> - 找出複寫延遲的真正元兇（**無主鍵表**、單筆大交易、單執行緒 applier）並修掉
> - 複寫斷掉時**先查分歧原因再決定怎麼修**，而不是反射性跳過錯誤
> - ★★★★★ 執行一次**不會產生雙寫（split brain）**的計畫性切換，並且切壞了切得回來
> - ★★★★ 理解「**複寫不是備份**」—— 並在應用端正確處理讀寫分離的延遲陷阱

---

## 前置知識

| 篇章 | 你會用到裡面的什麼 |
| --- | --- |
| [[05-MySQL-備份與還原]] | ★★★★ 備份與 PITR。**本篇不取代它** —— 複寫與備份是兩件事，兩件都要做 |
| [[02-MySQL-使用者與權限]] | 建 `repl` 複寫帳號、`REPLICATION SLAVE` 權限、來源網段限制 |
| [[04-MySQL-設定檔與調校]] | `my.cnf` 的載入順序、buffer pool 與 `innodb_flush_log_at_trx_commit` |
| [[07-MySQL-安全強化]] | `bind-address`、TLS 憑證的產製與 `REQUIRE SSL`。本篇只說「複寫連線要走加密」 |
| [[02-防火牆-ufw基礎與實務]] | 只放行從庫 IP 對 3306，不對外開放 |

> [!tip] 這篇在 LXMP 架構的哪個位置
> LXMP（Linux + Nginx/Apache + MySQL + PHP/Laravel）的 **M** 從單機變成兩台之後，
> 上層要跟著改：Laravel 的 `config/database.php` 要分 read/write（見本篇最後一段），
> Nginx 那層的健康檢查與維護模式見 [[04-Nginx-反向代理與負載平衡]]，
> 整套堆疊的實際部署見 [[02-範例-Laravel完整堆疊]]。

---

## 觀念說明

### ★★★★ 先把這件事講死：複寫不是備份

機關導入複寫之後最常見、也最貴的認知錯誤，就是把從庫當成備份，然後把備份排程停掉。

```text
  09:41:07.000   有人在正式庫下 DROP TABLE members;
  09:41:07.043   主庫 binlog 寫入這個事件
  09:41:07.061   從庫 IO thread 收到
  09:41:07.088   從庫 applier 忠實地執行 → 從庫的 members 也沒了

  ★★★★ 全程 0.088 秒。你有兩台機器，但你有零份 members。
```

複寫是**同步機制**，不是**時光機**。它會用最快的速度把你的錯誤複製到每一台從庫。

| 威脅 | 複寫擋得住嗎 | 備份擋得住嗎 |
| --- | --- | --- |
| 主機硬碟故障、電源掛掉 | ★★★★ 可以，切到從庫即可 | 可以，但要重建，RTO 以小時計 |
| 機房斷網、單點失效 | ★★★★ 可以 | 不行（除非有異地備份 + 異地主機） |
| `DROP TABLE` / `DELETE` 沒加 `WHERE` | ★★★★★ **完全擋不住** | ★★★★★ 可以（PITR 回到誤操作前一秒） |
| 勒索軟體加密資料檔 | ★★★★★ **完全擋不住**（加密後的寫入照樣同步） | 可以（離線備份） |
| 應用程式的邏輯 bug 寫爛資料 | ★★★★★ **完全擋不住** | 可以 |
| 誤刪整台 VM | 可以 | 可以 |

> [!danger] ★★★★★ 導入複寫不能減少任何一次備份
> 備份策略、備份驗證與**還原演練**全部在 [[05-MySQL-備份與還原]]，
> 機關層級的災難復原制度見 [[04-備份災難復原與入侵應變]] 與 [[06-災難復原與異地備援]]。
> 本篇只負責「硬體故障與單點」這一格。
>
> 本篇後面會給你一個**折衷武器**：**延遲從庫**（`SOURCE_DELAY=3600`）。
> 它讓你有一小時的緩衝去撈誤刪的資料，但它仍然**不是備份**，只是縮短了 PITR 的痛苦。

### 機關導入複寫的兩個真實動機

不要為了「聽起來比較高可用」而導入。只有這兩個動機值得付出多一台機器的維運成本：

| 動機 | 具體長相 | 本篇對應段落 |
| --- | --- | --- |
| **分流** ★★★ | 月報表、稽核查詢、`mysqldump` 全部打到從庫，主庫只服務線上交易 | 讀寫分離、延遲判讀 |
| **頂替** ★★★★ | 主庫主機板掛了，30 分鐘內把服務指到從庫 | 計畫性切換與故障切換 |

★★ 如果你的真實需求是「資料不能不見」，答案是**備份 + 異地**，不是複寫。
★★ 如果你的真實需求是「查詢很慢」，先看 [[04-效能瓶頸排查方法論]] 與 [[04-MySQL-設定檔與調校]]，
加從庫不會讓一個缺索引的查詢變快，只會讓它在兩台機器上都很慢。

### 資料是怎麼流過去的

```text
        主庫 db1  10.0.1.11                             從庫 db2  10.0.1.12
 ┌─────────────────────────────────┐         ┌──────────────────────────────────┐
 │  應用連線 (Laravel / PHP-FPM)   │         │  報表 / 稽核查詢（唯讀）         │
 │            ↓ INSERT/UPDATE      │         │            ↑                     │
 │      InnoDB buffer pool         │         │      InnoDB buffer pool          │
 │            ↓                    │         │            ↑                     │
 │      redo log + binlog          │         │      ┌─────────────────┐         │
 │            ↓                    │         │      │ Applier (SQL)   │         │
 │   mysql-bin.000123 ─────────┐   │         │      │  coordinator    │         │
 │                             │   │         │      │  worker × N     │         │
 │   ┌──────────────────────┐  │   │         │      └────────▲────────┘         │
 │   │ Binlog Dump Thread   │◄─┘   │         │               │                  │
 │   │ （每個從庫一條）      │      │         │      relay-bin.000045            │
 │   └──────────┬───────────┘      │         │               ▲                  │
 └──────────────┼──────────────────┘         │      ┌────────┴────────┐         │
                │                            │      │   IO Thread     │         │
                └──── TCP 3306 / TLS ────────┼─────►│ （只有一條）    │         │
                      repl@10.0.1.%          │      └─────────────────┘         │
                                             └──────────────────────────────────┘
```

三條執行緒，各自會壞，壞法不一樣：

| 執行緒 | 在哪台 | 職責 | 壞掉的症狀 |
| --- | --- | --- | --- |
| **Binlog Dump** | 主庫 | 把 binlog 事件推給從庫 | 主庫 `SHOW PROCESSLIST` 看不到 `Binlog Dump GTID` |
| **IO Thread** | 從庫 | 收事件、寫進 relay log | ★★★★ `Replica_IO_Running: No`／`Connecting`，網路或帳號問題 |
| **Applier (SQL)** | 從庫 | 從 relay log 讀出來執行 | ★★★★ `Replica_SQL_Running: No`，資料衝突或大交易卡住 |

> [!note] ★★★ 為什麼要分成兩條執行緒
> 因為**「拿到資料」與「套用資料」要解耦**。
> 主庫掛掉時，IO thread 早就把事件抓進 relay log 了，applier 可以繼續把它們跑完 ——
> 這正是計畫性切換時「等從庫追平」的技術基礎。
> 也因此 **relay log 堆了一大坨還沒套用時，`Seconds_Behind_Source` 依然可能顯示很小的值**。

### 三種複寫模式：先選型再動手

| 模式 | 主庫何時回應用「commit 成功」 | 主庫掛掉的資料遺失 | 寫入延遲成本 | 什麼時候用 |
| --- | --- | --- | --- | --- |
| **非同步**（預設） | 自己寫完 binlog 就回 | ★★★ 可能遺失最後幾筆 | 幾乎為零 | **絕大多數機關系統**、報表分流、本篇主線 |
| **半同步** `rpl_semi_sync` | 至少一台從庫**收到**（不是套用完）才回 | ★★ 大幅降低 | 每筆交易多一個 RTT | 金流、不能掉單的表單系統 |
| **群組複寫 MGR / InnoDB Cluster** | 多數節點達成共識才回 | ★ 最低 | 最高，且對網路品質敏感 | 需要**自動故障切換**且有人力長期維運時 |

> [!warning] ★★★ 半同步不等於「不會掉資料」
> 半同步保證的是「**至少一台從庫收到了 binlog 事件**」，
> 不保證從庫已經套用完，也不保證主庫本地的 InnoDB 已經落盤。
> 而且預設有 `rpl_semi_sync_source_timeout`（毫秒），
> ★★★★ **逾時後會自動降級成非同步而且不會發警報** —— 你以為有半同步，其實沒有。
> 要監控 `Rpl_semi_sync_source_status` 這個狀態變數。

> [!tip] MGR / InnoDB Cluster 什麼時候該考慮（本篇不展開建置）
> 三個條件同時成立才考慮：**① 需要秒級自動切換**（人來切太慢）、
> **② 三個節點在同一機房、網路延遲穩定在 1ms 以內**、
> **③ 有人能長期維運**（MGR 出事時的排查難度遠高於主從）。
> 只滿足其中一兩項時，一套「主從 + 寫得清楚的切換 runbook + 演練紀錄」更可靠。
> ProxySQL / MHA / Orchestrator 也一樣：它們讓切換自動化，但也讓故障模式變多。
> 選型的通盤討論見 [[04-高可用與負載平衡架構]]。

### ★★★★ GTID vs 傳統 binlog file + position

這是本篇最重要的一個選型決定，而且**新建系統沒有第二個選項**。

| | 傳統 file + position | **GTID（本篇主線）** |
| --- | --- | --- |
| 從庫怎麼記錄進度 | 「我讀到 `mysql-bin.000123` 的第 197845 個 byte」 | 「我執行過 `3e11fa47-…:1-45210`」 |
| 換一台主庫時 | ★★★★ 要人工去新主庫上算出**對應的 file + position**，算錯就資料錯亂 | `SOURCE_AUTO_POSITION=1`，從庫自己協商 |
| 判斷主從是否追平 | 只能比對數字，跨機器沒有意義 | `GTID_SUBTRACT()` 一句話得到答案 |
| 跳過一筆壞交易 | `sql_replica_skip_counter=1`（很容易跳錯筆數） | 注入空交易，**跳過的是哪一筆有明確紀錄** |
| 級聯／多來源 | 極易出錯 | 天然支援 |

GTID 長這樣，`來源 UUID:交易序號`：

```text
3e11fa47-71ca-11e1-9e33-c80aa9429562:1-45210
└──────── 主庫的 server_uuid ────────┘ └ 這台主庫產生的第 1~45210 筆交易 ┘
```

> [!danger] ★★★★ 沒有 GTID 的複寫，故障切換難度差好幾個等級
> 傳統模式下，主庫掛掉要把從庫接到另一台從庫時，你必須人工推算 position。
> 半夜三點、壓力之下、算錯一次 = 資料永久分歧。
> **新建一律 `gtid_mode=ON` + `enforce_gtid_consistency=ON`。**

> [!info]- 既有系統從 position 模式切到 GTID 的注意事項
> MySQL 8.0 支援**線上**啟用 GTID，不需要停機，但必須**依序**在
> **所有節點（主庫與全部從庫）**上做，而且中間任一步失敗都要停下來查：
>
> ```sql
> -- 【1】全部節點：先確認沒有違反 GTID 一致性的語句
> SET @@GLOBAL.ENFORCE_GTID_CONSISTENCY = WARN;
> -- 觀察數天，錯誤日誌若出現 "Statement violates GTID consistency" 就要先改應用
>
> -- 【2】全部節點：轉成強制
> SET @@GLOBAL.ENFORCE_GTID_CONSISTENCY = ON;
>
> -- 【3】全部節點，依序執行（每一步都要等所有節點的 ONGOING_ANONYMOUS_TRANSACTION_COUNT 歸零）
> SET @@GLOBAL.GTID_MODE = OFF_PERMISSIVE;
> SET @@GLOBAL.GTID_MODE = ON_PERMISSIVE;
> -- 等到所有節點：SELECT @@GLOBAL.GTID_OWNED; 與匿名交易計數都為空
> SET @@GLOBAL.GTID_MODE = ON;
>
> -- 【4】從庫上改用 auto position
> STOP REPLICA;
> CHANGE REPLICATION SOURCE TO SOURCE_AUTO_POSITION = 1;
> START REPLICA;
> ```
>
> ★★★★ 三個常見地雷：
> **①** `CREATE TABLE ... SELECT` 與**非交易式表（MyISAM）與 InnoDB 混在同一個交易**
> 會違反 GTID 一致性，`ENFORCE_GTID_CONSISTENCY=ON` 之後直接報錯 —— 所以要先用 `WARN` 觀察。
> **②** 所有節點的 `gtid_mode` 差距不能超過一階（`OFF` ↔ `OFF_PERMISSIVE` ↔ `ON_PERMISSIVE` ↔ `ON`），
> 跳著改會直接被拒絕。
> **③** 改完記得把 `gtid_mode` 與 `enforce_gtid_consistency` **寫進 my.cnf**，
> 否則下次重啟就打回原形，而且從庫會用 auto position 連一台沒開 GTID 的主庫 → 直接斷線。

---

## 環境準備與安裝

### 本篇的固定環境

| 角色 | 主機名 | IP | 版本 | `server_id` |
| --- | --- | --- | --- | --- |
| 主庫（source） | `db1` | `10.0.1.11` | Ubuntu 24.04 + MySQL 8.0 | `11` |
| 從庫（replica） | `db2` | `10.0.1.12` | Ubuntu 24.04 + MySQL 8.0 | `12` |
| 應用（Laravel/PHP-FPM） | `app1` | `10.0.1.21` | — | — |

★★★ **兩台的 MySQL 版本必須相同或「主庫較舊」**。
MySQL 官方支援「從庫版本 ≥ 主庫版本」的複寫（升級時就是靠這個先升從庫），
但**反過來（主庫較新、從庫較舊）不支援**，會出現無法解析的 binlog 事件。

```bash
# 兩台都跑，確認版本一致
mysql -e "SELECT VERSION(), @@server_uuid\G"
```

預期輸出：

```text
*************************** 1. row ***************************
      VERSION(): 8.0.43-0ubuntu0.24.04.1
  @@server_uuid: 3e11fa47-71ca-11e1-9e33-c80aa9429562   # ★★★ 兩台必須不同（見下方）
```

> [!danger] ★★★★ 用 VM 範本或磁碟複製建第二台？先檢查 `server_uuid`
> `server_uuid` 存在 **datadir 下的 `auto.cnf`**。
> 如果 db2 是把 db1 整顆磁碟 clone 出來的，兩台的 `server_uuid` 會**一模一樣**，
> 複寫會出現看起來毫無道理的錯誤（`Fatal error: The replica I/O thread stops because
> source and replica have equal MySQL server UUIDs`）。
>
> ```bash
> # 從庫上：停掉服務、刪掉 auto.cnf、重啟讓它重新產生
> sudo systemctl stop mysql
> sudo rm -f /var/lib/mysql/auto.cnf
> sudo systemctl start mysql
> mysql -e "SELECT @@server_uuid;"    # ★ 確認已經跟主庫不同
> ```

### 安裝

```bash
# ═══ 兩台都做：Ubuntu 24.04 內建套件庫的 MySQL 8.0 ═══
sudo apt update
sudo apt install -y mysql-server percona-toolkit
sudo systemctl enable --now mysql
mysql --version
```

預期輸出：

```text
mysql  Ver 8.0.43-0ubuntu0.24.04.1 for Linux on x86_64 ((Ubuntu))
```

`percona-toolkit` 提供本篇會用到的 `pt-heartbeat`、`pt-table-checksum`、`pt-table-sync`。
安裝與初始化（`mysql_secure_installation`、`bind-address`）見 [[01-MySQL-安裝與初始化]]。

> [!warning] ★★★ MySQL 8.4 LTS 把舊語法**移除**了，不是「不建議」而已
> 從 MySQL 8.0.22 起 `MASTER/SLAVE` 系列被 `SOURCE/REPLICA` 取代，舊語法還能用；
> 但到了 **MySQL 8.4 LTS，`CHANGE MASTER TO`、`START SLAVE`、`STOP SLAVE`、
> `SHOW SLAVE STATUS`、`SHOW MASTER STATUS`、`RESET MASTER` 全部直接移除**。
>
> 影響最大的其實不是你手打的指令，而是**你抄來的監控腳本、Zabbix/Nagios 樣板、
> 交接文件裡的 SOP**。升級到 8.4 之前，先 `grep -ri "slave status" /usr/local/bin /etc/zabbix`。
> 本篇一律用**新語法**，下方 callout 給完整對照。

> [!info]- ★★★ MySQL 8.0.22+ / 8.4 / MariaDB 完整術語對照表
> | 舊語法（≤8.0.21、MariaDB 全系列） | 新語法（8.0.22+，8.4 唯一可用） |
> | --- | --- |
> | `CHANGE MASTER TO` | `CHANGE REPLICATION SOURCE TO` |
> | `MASTER_HOST` / `MASTER_PORT` | `SOURCE_HOST` / `SOURCE_PORT` |
> | `MASTER_USER` / `MASTER_PASSWORD` | `SOURCE_USER` / `SOURCE_PASSWORD` |
> | `MASTER_AUTO_POSITION` | `SOURCE_AUTO_POSITION` |
> | `MASTER_SSL` / `MASTER_SSL_CA` | `SOURCE_SSL` / `SOURCE_SSL_CA` |
> | `MASTER_DELAY` | `SOURCE_DELAY` |
> | `START SLAVE` / `STOP SLAVE` | `START REPLICA` / `STOP REPLICA` |
> | `RESET SLAVE ALL` | `RESET REPLICA ALL` |
> | `SHOW SLAVE STATUS` | `SHOW REPLICA STATUS` |
> | `SHOW SLAVE HOSTS` | `SHOW REPLICAS` |
> | `SHOW MASTER STATUS` | `SHOW BINARY LOG STATUS`（8.2+；8.0 仍用舊名） |
> | `RESET MASTER` | `RESET BINARY LOGS AND GTIDS` |
> | `slave_parallel_workers` | `replica_parallel_workers` |
> | `log_slave_updates` | `log_replica_updates` |
> | `slave_skip_errors` | `replica_skip_errors` |
> | `sql_slave_skip_counter` | `sql_replica_skip_counter` |
> | `Slave_IO_Running` / `Slave_SQL_Running` | `Replica_IO_Running` / `Replica_SQL_Running` |
> | `Seconds_Behind_Master` | `Seconds_Behind_Source` |
> | `Last_IO_Error` / `Last_SQL_Error` | 沒改名 |
> | 權限 `REPLICATION SLAVE` | ★★★ **沒有改名**，仍然是 `REPLICATION SLAVE` |
>
> ★★★★ 最後一列是最容易寫錯的：語法全改了，**權限名稱卻沒改**。
> 打 `GRANT REPLICATION REPLICA ON *.* TO ...` 會直接語法錯誤。

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> # ★★★★ RHEL 8/9 的 dnf module 預設指向 MariaDB，"mysql" 才是 Oracle MySQL
> sudo dnf module list mysql mariadb
> sudo dnf install -y mysql-server
> sudo systemctl enable --now mysqld        # ★ 服務名是 mysqld，不是 mysql
> ```
> | 項目 | Ubuntu 24.04 | Rocky / AlmaLinux 9 |
> | --- | --- | --- |
> | 服務名 | `mysql` | `mysqld` |
> | 主設定檔 | `/etc/mysql/my.cnf` | `/etc/my.cnf` |
> | 客製片段目錄 | `/etc/mysql/mysql.conf.d/` | `/etc/my.cnf.d/` |
> | datadir | `/var/lib/mysql` | `/var/lib/mysql` |
> | 錯誤日誌 | `/var/log/mysql/error.log` | `/var/log/mysql/mysqld.log` |
> | 強制存取控制 | ★★★★ **AppArmor** | ★★★★ **SELinux** |
> | 防火牆 | `ufw` | `firewalld` |
>
> ```bash
> # ★★★★ SELinux：binlog / relay log 放到非預設路徑一定要補標籤，否則 MySQL 起不來
> sudo semanage fcontext -a -t mysqld_db_t "/data/binlog(/.*)?"
> sudo restorecon -Rv /data/binlog
> sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" \
>   source address="10.0.1.12/32" port protocol="tcp" port="3306" accept'
> sudo firewall-cmd --reload
> ```

> [!info]- MariaDB 差異（機關的 RHEL 主機預設常常是這個）
> ★★★★ **MariaDB 的複寫與 MySQL 8.0 不相容，兩者不能互為主從。**
> 動手前先確認你面前的是哪一個：
>
> ```bash
> mysql -e "SELECT VERSION();"
> # 10.11.x-MariaDB → 是 MariaDB，本篇語法要換
> ```
>
> | 主題 | MySQL 8.0/8.4 | MariaDB 10.x/11.x |
> | --- | --- | --- |
> | 指令 | `CHANGE REPLICATION SOURCE TO` | ★★★ **維持 `CHANGE MASTER TO`** |
> | 狀態 | `SHOW REPLICA STATUS` | ★★★ **維持 `SHOW SLAVE STATUS`** |
> | GTID 格式 | `uuid:序號` | `domain-server_id-序號`（例：`0-11-45210`），**兩者完全不同** |
> | 啟用 GTID | `gtid_mode=ON` + `enforce_gtid_consistency=ON` | 沒有這兩個變數，改用 `CHANGE MASTER TO MASTER_USE_GTID=slave_pos` |
> | 並行 applier | `replica_parallel_workers` | `slave_parallel_threads` |
> | 半同步 | 外掛 `rpl_semi_sync_source` | 內建，`rpl_semi_sync_master_enabled=ON` |
> | `super_read_only` | 有 | 有（10.5+） |
>
> ★★★ 本篇的**觀念、判讀方法、切換程序、雙寫風險**在 MariaDB 上完全一樣，
> 只有指令名稱與 GTID 表示法要換。

### 網路與防火牆

```bash
# ═══ db1（主庫）：只放行從庫那一台的 3306 ═══
sudo ufw allow from 10.0.1.12 to any port 3306 proto tcp comment 'MySQL repl from db2'
sudo ufw status numbered
```

預期輸出：

```text
[ 3] 3306/tcp                   ALLOW IN    10.0.1.12    # MySQL repl from db2
```

```bash
# ═══ db2（從庫）：確認連得到主庫 ═══
nc -zv 10.0.1.11 3306
```

預期輸出：

```text
Connection to 10.0.1.11 3306 port [tcp/mysql] succeeded!
```

> [!danger] ★★★★ 不要 `ufw allow 3306`
> 沒有來源限制的 3306 等於把整個資料庫掛在網路上。
> 規則寫法與順序陷阱見 [[02-防火牆-ufw基礎與實務]]，
> `bind-address` 與 TLS 憑證的產製見 [[07-MySQL-安全強化]]。

### ★★★★ 對時：NTP 沒同步，延遲數字全部是假的

`Seconds_Behind_Source` 的算法是「**從庫本地時間** − **正在套用的 binlog 事件的時間戳**」。
兩台機器的時鐘差 30 秒，這個數字就會憑空多（或少）30 秒。

```bash
# 兩台都跑
timedatectl show -p NTPSynchronized -p TimeUSec
```

預期輸出：

```text
NTPSynchronized=yes                    # ★★★★ 必須是 yes
TimeUSec=Sat 2026-08-29 10:14:07 CST
```

```bash
# 沒同步時
sudo timedatectl set-ntp true
sudo systemctl restart systemd-timesyncd
```

---

## 基礎設定：把複寫建起來

### 【1】主庫設定

Ubuntu 的 `/etc/mysql/my.cnf` 會依序讀 `/etc/mysql/conf.d/` 與 `/etc/mysql/mysql.conf.d/`，
**同名參數後讀到的贏**。所以客製片段用 `zz-` 開頭，確保排在 `mysqld.cnf` 後面：

```bash
sudo tee /etc/mysql/mysql.conf.d/zz-replication.cnf > /dev/null << 'EOF'
[mysqld]
# ─── 身分 ───────────────────────────────────────────────
server_id                      = 11        # ★★★ 全叢集唯一，撞號會出現無法解釋的斷線
report_host                    = db1

# ─── binlog ────────────────────────────────────────────
log_bin                        = /var/log/mysql/mysql-bin
binlog_format                  = ROW       # ★★★★ 一定是 ROW，理由見下方
binlog_row_image               = FULL      # 先用 FULL，確定沒問題再考慮 MINIMAL
sync_binlog                    = 1         # ★★★★ 每筆交易 fsync binlog，掉電不掉交易
innodb_flush_log_at_trx_commit = 1         # ★★★★ 與上一行成對，缺一不可

# ─── binlog 保留 ───────────────────────────────────────
binlog_expire_logs_seconds     = 1209600   # ★★★★ 14 天。預設 2592000（30 天）
max_binlog_size                = 512M

# ─── GTID ──────────────────────────────────────────────
gtid_mode                      = ON
enforce_gtid_consistency       = ON
log_replica_updates            = ON        # ★★★ 為了將來能降級成從庫，主庫也要開

# ─── 並行 applier 的前置（切換後這台會變從庫）─────────
binlog_transaction_dependency_tracking = WRITESET
EOF

sudo systemctl restart mysql
```

驗證：

```bash
mysql -e "SELECT @@server_id, @@gtid_mode, @@enforce_gtid_consistency,
                 @@binlog_format, @@sync_binlog, @@binlog_expire_logs_seconds\G"
```

預期輸出：

```text
*************************** 1. row ***************************
               @@server_id: 11
               @@gtid_mode: ON
@@enforce_gtid_consistency: ON
           @@binlog_format: ROW
             @@sync_binlog: 1
@@binlog_expire_logs_seconds: 1209600
```

```bash
mysql -e "SHOW MASTER STATUS\G"      # MySQL 8.2+ / 8.4 改用 SHOW BINARY LOG STATUS
```

預期輸出：

```text
*************************** 1. row ***************************
             File: mysql-bin.000003
         Position: 1421
     Executed_Gtid_Set: 3e11fa47-71ca-11e1-9e33-c80aa9429562:1-8
```

> [!danger] ★★★ `server_id` 撞號的症狀特別難查
> 兩台從庫用同一個 `server_id` 連同一台主庫時，**主庫會把先連的那條 dump thread 踢掉**，
> 於是兩台從庫輪流斷線重連，錯誤日誌只寫
> `A replica with the same server_uuid/server_id as this replica has connected to the source`。
> 你會看到「複寫每隔幾分鐘斷一次、重連後又好了」這種完全不像資料問題的現象。
>
> **做法**：把 `server_id` 寫進主機建置的標準流程，用固定規則（例如 IP 最後一段）產生，
> 並登記在資產清冊裡。制度面見 [[08-變更管理流程]]。

> [!note] ★★★★ 為什麼 `binlog_format` 一定要 ROW
> | 格式 | binlog 裡記什麼 | 風險 |
> | --- | --- | --- |
> | `STATEMENT` | 原始 SQL 文字 | ★★★★★ `NOW()`、`UUID()`、`RAND()`、`LIMIT` 沒有 `ORDER BY`、觸發器 —— **主從算出不同結果，而且不會報錯**，你要幾個月後對帳才會發現 |
> | `MIXED` | 平常 STATEMENT，遇到不安全語句才 ROW | ★★★ 判斷規則是黑盒子，出事後難以重建現場 |
> | **`ROW`** | 「第 12345 列，這些欄位從 A 變成 B」 | **主從逐列一致**，代價是 binlog 較大 |
>
> ROW 的代價很實在：一句 `UPDATE orders SET status=1`（影響 50 萬列）在 STATEMENT 下是
> 50 個 byte，在 ROW 下是 50 萬列的前後映像。這也是本篇「拆大交易」建議的由來。
> `binlog_row_image=MINIMAL` 可以只記主鍵與有變動的欄位、大幅縮小 binlog，
> ★★★ 但 `pt-table-sync` 與部分 CDC 工具需要 `FULL` —— 先用 `FULL`，有量測到問題再調。

> [!danger] ★★★★ `binlog_expire_logs_seconds` 設太短 = 從庫追不回來只能整台重做
> 從庫離線期間，主庫上的 binlog 是它唯一的補課教材。
> **binlog 保留時間必須 > 「從庫可能離線的最長時間」+「你重建一台從庫需要的時間」。**
>
> ```text
>   週五 18:00  從庫主機當機，沒人發現
>   週一 09:00  上班發現，開機
>              → 離線 63 小時
>   若 binlog_expire_logs_seconds = 172800（2 天）
>              → 需要的 GTID 已經被清掉
>              → Last_IO_Error 1236: The replica is connecting ... but the source
>                has purged binary logs containing GTIDs that the replica requires
>              → ★★★★ 唯一解法：重做整台從庫（重新 dump / XtraBackup），
>                 資料量大的話要停機好幾個小時
> ```
>
> 算法：**連假 4 天 + 重建 8 小時 + 緩衝 2 天 ≈ 14 天**，這就是上面 `1209600` 的由來。
> 代價是磁碟。用下面這句先估算你每天產生多少 binlog：
>
> ```bash
> mysql -e "SHOW BINARY LOGS;" | awk 'NR>1 {s+=$2} END {print s/1024/1024/1024 " GB"}'
> ```
>
> 磁碟真的不夠時，**不要縮短保留時間**，改成「binlog 另外掛一顆磁碟」或
> 「把舊 binlog 複製到備份儲存」（順便讓 PITR 的可回溯範圍變長，見 [[05-MySQL-備份與還原]]）。

### 【2】複寫帳號

```sql
-- ★ 在主庫 db1 上執行
CREATE USER 'repl'@'10.0.1.%'
  IDENTIFIED WITH caching_sha2_password BY '請換成 32 字元以上的隨機密碼'
  REQUIRE SSL;                                  -- ★★★★ 強制加密

GRANT REPLICATION SLAVE ON *.* TO 'repl'@'10.0.1.%';   -- ★★★ 權限名稱沒有改成 REPLICA
FLUSH PRIVILEGES;

SHOW GRANTS FOR 'repl'@'10.0.1.%';
```

預期輸出：

```text
+---------------------------------------------------------------+
| Grants for repl@10.0.1.%                                      |
+---------------------------------------------------------------+
| GRANT REPLICATION SLAVE ON *.* TO `repl`@`10.0.1.%`           |
+---------------------------------------------------------------+
```

| 決定 | 為什麼 | 星級 |
| --- | --- | --- |
| 只給 `REPLICATION SLAVE` | 複寫只需要讀 binlog，**不需要任何資料表權限** | ★★★★ |
| 來源限 `10.0.1.%` | 不寫 `%`。最嚴格是逐台寫 `'repl'@'10.0.1.12'` | ★★★★ |
| `REQUIRE SSL` | 複寫連線裡是**未加密的完整資料變更內容**，含個資 | ★★★★ |
| 不加 `REPLICATION CLIENT` | 那是給監控帳號看 `SHOW REPLICA STATUS` 用的，職責分離 | ★★ |

> [!warning] ★★★ `caching_sha2_password` + 沒開 TLS = 連不上
> MySQL 8.0 預設的 `caching_sha2_password` 在**非加密連線**上，
> 第一次認證需要透過 RSA 公鑰交換密碼。從庫沒拿到公鑰時會出現
> `Authentication plugin 'caching_sha2_password' reported error: Authentication requires
> secure connection`。
> **正解是設定 TLS**（本篇作法）。
> 真的沒有 TLS 時才退而求其次加 `GET_SOURCE_PUBLIC_KEY=1`，
> ★★★★ 但那代表**複寫流量全程明文**，機關個資系統不可接受。

> [!danger] ★★★★ 密碼會留在 `~/.mysql_history` 與螢幕截圖裡
> `CHANGE REPLICATION SOURCE TO ... SOURCE_PASSWORD='xxx'` 這句話會被記進
> 執行者的 `~/.mysql_history`。交接、外包廠商、螢幕分享都會外洩。
>
> ```bash
> # 執行敏感 SQL 前先關掉歷程
> MYSQL_HISTFILE=/dev/null mysql -u root -p
> # 或事後清掉
> shred -u ~/.mysql_history 2>/dev/null; touch ~/.mysql_history; chmod 600 ~/.mysql_history
> ```

### 【3】初始資料同步：兩條路，選錯會拖垮主庫

從庫要先有一份「某個 GTID 位置的完整快照」，才能從那裡開始接續。

| 方法 | 資料量 | 對主庫的衝擊 | 停機 |
| --- | --- | --- | --- |
| `mysqldump --single-transaction` | **< 50 GB** | ★★★ 長時間持有一致性快照，undo 暴增、磁碟吃緊 | 不用 |
| **Percona XtraBackup** | **> 50 GB** | ★ 幾乎只有磁碟 I/O | 不用 |
| 停機冷拷貝 datadir | 任意 | 無 | ★★★★ 要停機 |

> [!danger] ★★★ 上百 GB 的庫用 mysqldump 做初始同步會把主庫拖垮
> `--single-transaction` 會開一個 REPEATABLE READ 的長交易。
> 500 GB 的庫 dump 六個小時 = 主庫要保留六個小時的 undo 版本，
> `ibdata1` / undo tablespace 暴增，同時線上查詢因為要走 undo 鏈而變慢。
> 我看過因此把正式庫磁碟撐爆的案例。
>
> **超過 50 GB 一律用 XtraBackup，並且排在離峰時段（機關通常是 22:00 之後）。**
> 排程與公告流程走 [[08-變更管理流程]]。

#### 路線 A：mysqldump（小資料量）

```bash
# ═══ 在 db2（從庫）上，直接對主庫抓 ═══
sudo mysqldump \
  --host=10.0.1.11 --user=backup --password \
  --single-transaction \
  --source-data=2 \
  --set-gtid-purged=ON \
  --routines --events --triggers \
  --hex-blob --default-character-set=utf8mb4 \
  --databases appdb appdb_log \
  > /var/backups/db1-seed.sql
```

| 旗標 | 作用 | 星級 |
| --- | --- | --- |
| `--single-transaction` | InnoDB 一致性快照，不鎖表 | ★★★★ |
| `--source-data=2` | 把 binlog 位置寫成**註解**（8.0.26 前叫 `--master-data`） | ★★ |
| `--set-gtid-purged=ON` | ★★★★ **關鍵**：在 dump 開頭產生 `SET @@GLOBAL.gtid_purged=...` | ★★★★ |
| `--routines --events --triggers` | 預設**不會**匯出這三種，漏了會發現預存程序不見了 | ★★★ |
| `--databases appdb ...` | ★★★ 建議逐一列出，不要用 `--all-databases`（見下方） |  ★★★ |

```bash
# 確認 gtid_purged 有寫進去
grep -m1 'gtid_purged' /var/backups/db1-seed.sql
```

預期輸出：

```text
SET @@GLOBAL.GTID_PURGED=/*!80000 '+'*/ '3e11fa47-71ca-11e1-9e33-c80aa9429562:1-45210';
```

> [!warning] ★★★ 為什麼不用 `--all-databases`
> `--all-databases` 會一併匯出 `mysql` schema 的使用者與權限表。
> 匯入從庫時可能覆蓋掉從庫自己的帳號（包含你的監控帳號），
> 而且 8.0 的 `mysql` schema 是 InnoDB 資料字典，直接灌 INSERT 風險很高。
> **實務作法**：資料用 `--databases` 列出應用 schema，
> 帳號用 `SHOW CREATE USER` / `pt-show-grants` 另外匯出，見 [[02-MySQL-使用者與權限]]。

匯入從庫：

```bash
# ★★★★ 匯入前必須清掉從庫的 GTID 狀態，否則 gtid_purged 設不進去
mysql -e "RESET BINARY LOGS AND GTIDS;"     # MySQL 8.0.34 前叫 RESET MASTER
mysql < /var/backups/db1-seed.sql
mysql -e "SELECT @@GLOBAL.gtid_purged\G"
```

預期輸出：

```text
*************************** 1. row ***************************
@@GLOBAL.gtid_purged: 3e11fa47-71ca-11e1-9e33-c80aa9429562:1-45210
```

★★★★ 如果這裡是空的，你等一下 `START REPLICA` 之後從庫會**從第 1 筆交易開始重放**，
結果就是一堆 `1062 duplicate key`。看到空值就停下來，先查 `RESET BINARY LOGS AND GTIDS` 有沒有跑。

#### 路線 B：Percona XtraBackup（大資料量）

> [!warning] 未實機驗證
> 本段依 Percona 官方文件撰寫，未在實機環境驗證。
> ★★★★ **XtraBackup 的主版本必須與 MySQL 對齊**（MySQL 8.0 → XtraBackup 8.0，
> MySQL 8.4 → XtraBackup 8.4），版本不合會在 `--prepare` 階段失敗或產生無法啟動的資料目錄。
> 實作前請對照你手上版本的官方文件。

```bash
# 【1】在 db2 上，串流備份主庫（不落地在主庫、不吃主庫磁碟）
ssh db1 "xtrabackup --backup --stream=xbstream --user=bkp --password=xxx --parallel=4" \
  | xbstream -x -C /var/lib/mysql-seed

# 【2】套用 redo log，讓資料檔變成一致狀態
xtrabackup --prepare --target-dir=/var/lib/mysql-seed

# 【3】★★★★ 記下位置資訊，這是接上複寫的依據
cat /var/lib/mysql-seed/xtrabackup_binlog_info
```

預期輸出：

```text
mysql-bin.000012	1975	3e11fa47-71ca-11e1-9e33-c80aa9429562:1-45210
```

```bash
# 【4】換掉從庫的 datadir
sudo systemctl stop mysql
sudo mv /var/lib/mysql /var/lib/mysql.old       # ★★★ 先搬不要刪，這是你的回滾路
sudo mv /var/lib/mysql-seed /var/lib/mysql
sudo chown -R mysql:mysql /var/lib/mysql
sudo rm -f /var/lib/mysql/auto.cnf              # ★★★★ 一定要刪，否則 server_uuid 撞號
sudo systemctl start mysql

# 【5】把 GTID 位置告訴從庫
mysql -e "RESET BINARY LOGS AND GTIDS;
          SET @@GLOBAL.gtid_purged='3e11fa47-71ca-11e1-9e33-c80aa9429562:1-45210';"
```

### 【4】從庫設定

```bash
sudo tee /etc/mysql/mysql.conf.d/zz-replication.cnf > /dev/null << 'EOF'
[mysqld]
server_id                      = 12        # ★★★ 與主庫不同
report_host                    = db2

# ─── 唯讀保護（★★★★ 兩行都要）─────────────────────
read_only                      = ON
super_read_only                = ON

# ─── relay log ─────────────────────────────────────────
relay_log                      = /var/log/mysql/db2-relay-bin
relay_log_recovery             = ON        # ★★★★ 從庫崩潰後自動修復 relay log
relay_log_purge                = ON
skip_replica_start             = ON        # ★★★ 開機不自動啟動複寫（見下方）

# ─── 並行 applier ──────────────────────────────────────
replica_parallel_workers       = 8
replica_preserve_commit_order  = ON        # 8.0.27+ 預設就是 ON
binlog_transaction_dependency_tracking = WRITESET

# ─── GTID + binlog（★★★ 從庫也要開，將來才能升主庫）──
log_bin                        = /var/log/mysql/mysql-bin
log_replica_updates            = ON
gtid_mode                      = ON
enforce_gtid_consistency       = ON
binlog_format                  = ROW
binlog_expire_logs_seconds     = 1209600
sync_binlog                    = 1
innodb_flush_log_at_trx_commit = 1
EOF

sudo systemctl restart mysql
mysql -e "SELECT @@read_only, @@super_read_only, @@skip_replica_start,
                 @@relay_log_recovery, @@replica_parallel_workers\G"
```

預期輸出：

```text
*************************** 1. row ***************************
              @@read_only: 1
        @@super_read_only: 1        # ★★★★ 這行是 1 才算數
     @@skip_replica_start: 1
      @@relay_log_recovery: 1
 @@replica_parallel_workers: 8
```

> [!danger] ★★★★ 只設 `read_only` 而沒設 `super_read_only`，遲早出現主從分歧
> `read_only=ON` **不會擋住具有 `SUPER` 或 `CONNECTION_ADMIN` 權限的帳號**。
> 而在多數機關環境裡，那個帳號叫 `root`，而且維運人員每天都用它登入。
>
> ```sql
> -- 從庫上，只設了 read_only=ON 時
> mysql> SELECT @@read_only, @@super_read_only;
> +-------------+-------------------+
> | @@read_only | @@super_read_only |
> |           1 |                 0 |
> +-------------+-------------------+
>
> mysql> UPDATE appdb.settings SET v='x' WHERE k='maint';   -- 用 root 執行
> Query OK, 1 row affected (0.00 sec)      -- ★★★★ 寫進去了，而且主庫不知道
> ```
>
> 從這一刻起，這台從庫的資料與主庫**永久不同**。
> 主庫之後如果對同一列做 `UPDATE`，ROW 模式下前映像對不起來 → `1032 record not found`，
> 複寫直接停住；或更糟的是**永遠不報錯**，你在報表上看到錯的數字。
>
> **`super_read_only=ON` 會連 `SUPER` 帳號一起擋**，是唯一正解。
> 要在從庫做維護時，明確地 `SET GLOBAL super_read_only=OFF`，做完馬上關回去 ——
> 這一開一關本身就是稽核軌跡。

> [!note] ★★★ 為什麼要 `skip_replica_start=ON`
> 從庫重開機後**不要自動開始追資料**。
> 想像你正在做故障切換、剛把 db2 升成主庫，這時 db2 意外重啟 ——
> 如果沒有 `skip_replica_start`，它會自動重新連回舊主庫繼續當從庫，
> 而應用此時已經在寫 db2 了 → ★★★★★ **雙寫**。
> 代價是每次重啟後要手動 `START REPLICA`，這個代價值得付。
> 記得把「重啟後檢查複寫是否啟動」寫進 [[04-健康檢查與可用性監控]] 的檢查項。

### 【5】建立複寫連線

```sql
-- ★ 在 db2（從庫）上執行
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST            = '10.0.1.11',
  SOURCE_PORT            = 3306,
  SOURCE_USER            = 'repl',
  SOURCE_PASSWORD        = '……',
  SOURCE_AUTO_POSITION   = 1,             -- ★★★★ GTID 模式，不用給 file/position
  SOURCE_SSL             = 1,             -- ★★★★ 強制 TLS
  SOURCE_SSL_CA          = '/etc/mysql/ssl/ca.pem',
  SOURCE_CONNECT_RETRY   = 10,            -- 斷線後每 10 秒重試
  SOURCE_RETRY_COUNT     = 86400,         -- ★★★ 重試 86400 次 ≈ 撐 10 天不放棄
  SOURCE_HEARTBEAT_PERIOD = 10;           -- 主庫閒置時每 10 秒送心跳，用來偵測假死連線

START REPLICA;
```

```bash
mysql -e "SHOW REPLICA STATUS\G" | grep -E 'Running|Source_Host|Last_.*Error|Gtid'
```

預期輸出：

```text
              Replica_IO_State: Waiting for source to send event
                   Source_Host: 10.0.1.11
             Replica_IO_Running: Yes            # ★★★★ 必須 Yes
            Replica_SQL_Running: Yes            # ★★★★ 必須 Yes
                  Last_IO_Error:
                 Last_SQL_Error:
             Retrieved_Gtid_Set: 3e11fa47-71ca-11e1-9e33-c80aa9429562:45211-45260
              Executed_Gtid_Set: 3e11fa47-71ca-11e1-9e33-c80aa9429562:1-45260
    Auto_Position: 1
```

> [!tip] ★★★ `SOURCE_HEARTBEAT_PERIOD` 解決「複寫看起來好好的但其實斷了」
> 主庫沒有寫入時，dump thread 不會送任何東西，
> 從庫的 TCP 連線可能早就被中間的防火牆／NAT 靜默丟棄，但 IO thread 還顯示 `Yes`。
> 心跳讓從庫在沒有真實事件時也能確認連線活著，
> 逾時（預設 `replica_net_timeout`，8.0.26+ 預設 60 秒）後主動重連。
> ★★★ **機關的防火牆常常有 30~60 分鐘的閒置連線回收**，這個參數不設會定期出事。

主庫上確認從庫已經接上：

```bash
mysql -e "SHOW REPLICAS; SHOW PROCESSLIST\G" | grep -E 'Binlog Dump|Server_id|Host'
```

預期輸出：

```text
Server_id: 12
     Host: db2
  Command: Binlog Dump GTID          # ★★★ 主庫上每個從庫對應一條
```

---

## ★★★★ SHOW REPLICA STATUS 判讀（本篇最實用的一段）

複寫建好之後，你 99% 的時間都花在看這個輸出。**只有六個欄位真正重要。**

```bash
mysql -e "SHOW REPLICA STATUS\G"
```

| 欄位 | 健康的值 | 出問題時代表什麼 | 星級 |
| --- | --- | --- | --- |
| `Replica_IO_Running` | `Yes` | `No`／`Connecting` = 連不上主庫、帳號錯、binlog 被清、TLS 失敗 | ★★★★ |
| `Replica_SQL_Running` | `Yes` | `No` = **applier 撞到錯誤停住**，看 `Last_SQL_Error` | ★★★★ |
| `Last_IO_Error` | 空 | 1236（binlog 被清）、2003（連不上）、1045（密碼錯） | ★★★★ |
| `Last_SQL_Error` | 空 | 1062（重複鍵）、1032（找不到列）、1146（表不存在） | ★★★★ |
| `Seconds_Behind_Source` | 0~數秒 | ★★★★ **會騙人**，見下方 | ★★★ |
| `Retrieved_Gtid_Set` vs `Executed_Gtid_Set` | 兩者相同 | 差距 = **真正還沒套用完的交易**（relay log 積壓） | ★★★★ |

### ★★★★ `Seconds_Behind_Source` 為什麼會騙你

它的定義是「**從庫本地時鐘** − **applier 正在執行的那個事件在主庫上的時間戳**」。
這個定義有四個致命的盲點：

| 情境 | 顯示的值 | 真相 | 星級 |
| --- | --- | --- | --- |
| **IO thread 斷了、SQL thread 把 relay log 跑完了** | **`0`** | ★★★★★ 從庫可能落後好幾個小時，但它顯示「完全同步」 | ★★★★★ |
| SQL thread 停住 | `NULL` | 複寫已死。`NULL` 比大數字更嚴重 | ★★★★ |
| 主庫閒置（半夜沒有交易） | `0` | 沒有新事件可比，數字沒有意義 | ★★ |
| 兩台時鐘沒對 NTP | 差幾秒到幾分鐘 | 純粹是時鐘誤差 | ★★★ |
| 大交易正在套用中 | 卡在某個值不動 | 正在跑一筆很大的交易，其實有在動 | ★★ |

> [!danger] ★★★★★ 只監控 `Seconds_Behind_Source` 的告警系統等於沒有告警
> 最危險的組合是「IO thread 斷掉 + relay log 已跑完」：
> `Replica_IO_Running: No` 但 `Seconds_Behind_Source: 0`。
> 只抓延遲秒數的 Zabbix 樣板會**一片綠燈**，直到主庫掛掉那天你才發現
> 從庫的資料停在三天前。
>
> **告警必須同時檢查：兩個 Running 欄位 + GTID 落差 + 心跳表真延遲。**
> 本篇的實戰腳本就是在做這四件事。

### 用 GTID 落差算出真正的落後量

```sql
-- 【1】主庫上取得已執行的 GTID 集合
mysql -h 10.0.1.11 -e "SELECT @@GLOBAL.gtid_executed\G"
```

```text
@@GLOBAL.gtid_executed: 3e11fa47-71ca-11e1-9e33-c80aa9429562:1-45260
```

```sql
-- 【2】從庫上：主庫有、但我還沒執行的部分
mysql -h 10.0.1.12 -e "SELECT GTID_SUBTRACT(
    '3e11fa47-71ca-11e1-9e33-c80aa9429562:1-45260',
    @@GLOBAL.gtid_executed) AS missing\G"
```

預期輸出（追平時）：

```text
missing:
```

沒追平時：

```text
missing: 3e11fa47-71ca-11e1-9e33-c80aa9429562:45241-45260   # ★ 還差 20 筆交易
```

★★★★ 這是**唯一不會騙人**的延遲指標，也是計畫性切換時判斷「可以切了」的依據。

```sql
-- 【3】從庫上：已經抓進 relay log 但還沒套用的（applier 的積壓）
SELECT GTID_SUBTRACT(
  (SELECT RECEIVED_TRANSACTION_SET FROM performance_schema.replication_connection_status),
  @@GLOBAL.gtid_executed) AS relay_backlog\G
```

### 心跳表：量出「秒」為單位的真延遲

GTID 落差告訴你「差幾筆」，心跳表告訴你「差幾秒」—— 這才是能寫進 SLA 的數字。

```sql
-- ★ 主庫上建表（從庫會自動同步過去）
CREATE DATABASE IF NOT EXISTS ops;
CREATE TABLE ops.heartbeat (
  id      TINYINT      NOT NULL PRIMARY KEY,     -- ★★★ 一定要有主鍵，理由見下一節
  ts      DATETIME(6)  NOT NULL,
  host    VARCHAR(64)  NOT NULL
) ENGINE=InnoDB;
INSERT INTO ops.heartbeat VALUES (1, NOW(6), @@hostname);

-- ★ 用 MySQL EVENT 每秒更新（需要 event_scheduler=ON）
SET GLOBAL event_scheduler = ON;
CREATE EVENT ops.ev_heartbeat
  ON SCHEDULE EVERY 1 SECOND
  DO UPDATE ops.heartbeat SET ts = NOW(6), host = @@hostname WHERE id = 1;
```

```bash
# 從庫上量真延遲
mysql -e "SELECT TIMESTAMPDIFF(MICROSECOND, ts, NOW(6))/1000000 AS lag_sec,
                 host AS written_by FROM ops.heartbeat WHERE id=1;"
```

預期輸出：

```text
+---------+------------+
| lag_sec | written_by |
+---------+------------+
|  0.4270 | db1        |    # ★ 0.43 秒，健康
+---------+------------+
```

★★★★ 注意 `written_by` 欄位：切換之後這裡應該變成 `db2`。
**如果切換後它還是 `db1`，代表舊主庫還在寫 —— 這就是雙寫的第一個徵兆。**

> [!tip] 也可以用 `pt-heartbeat`（Percona Toolkit）
> ```bash
> # 主庫上：常駐更新
> pt-heartbeat --database ops --table pt_heartbeat --update --daemonize
> # 從庫上：讀出延遲
> pt-heartbeat --database ops --table pt_heartbeat --monitor --check
> ```
> ★★ 用 EVENT 的好處是不需要額外的常駐程序、切換時自動跟著走；
> 用 `pt-heartbeat` 的好處是支援多層級聯與更完整的輸出格式。二選一即可。

告警門檻怎麼設，寫進 [[03-系統監控與告警]]：

| 指標 | 警告 | 嚴重 | 星級 |
| --- | --- | --- | --- |
| `Replica_IO_Running` != Yes | — | ★★★★ 立即 | ★★★★ |
| `Replica_SQL_Running` != Yes | — | ★★★★ 立即 | ★★★★ |
| 心跳延遲 | > 30 秒 | > 300 秒 | ★★★ |
| GTID 落差筆數 | > 1000 | > 50000 | ★★★ |
| 從庫 `super_read_only` != 1 | ★★★★ 立即 | — | ★★★★ |

---

## 進階設定與調校

### ★★★★ 延遲元兇第一名：沒有主鍵的表

ROW 格式的 `UPDATE` / `DELETE` 事件，從庫要先**找到那一列**才能改。
有主鍵時是一次 B-tree 查找；**沒有主鍵、也沒有唯一索引時，從庫會對整張表做全表掃描 ——
而且是「每一列變更掃一次」**。

```text
  主庫：DELETE FROM access_log WHERE created_at < '2026-01-01';   影響 200 萬列
        主庫用索引，8 秒跑完

  從庫（access_log 沒有主鍵，共 5000 萬列）：
        每刪一列 → 掃 5000 萬列找目標
        200 萬 × 5000 萬 次比對
        ★★★★ 從庫延遲從 0 秒衝到 6 小時，applier 單執行緒卡死，其他交易全部排隊
```

找出所有沒有主鍵的表：

```sql
SELECT t.TABLE_SCHEMA, t.TABLE_NAME, t.TABLE_ROWS,
       ROUND(t.DATA_LENGTH/1024/1024) AS data_mb
FROM information_schema.TABLES t
LEFT JOIN information_schema.TABLE_CONSTRAINTS c
  ON  t.TABLE_SCHEMA = c.TABLE_SCHEMA
  AND t.TABLE_NAME   = c.TABLE_NAME
  AND c.CONSTRAINT_TYPE = 'PRIMARY KEY'
WHERE t.TABLE_TYPE = 'BASE TABLE'
  AND t.TABLE_SCHEMA NOT IN ('mysql','sys','information_schema','performance_schema')
  AND c.CONSTRAINT_NAME IS NULL
ORDER BY t.DATA_LENGTH DESC;
```

預期輸出：

```text
+--------------+---------------+------------+---------+
| TABLE_SCHEMA | TABLE_NAME    | TABLE_ROWS | data_mb |
+--------------+---------------+------------+---------+
| appdb        | access_log    |   49821330 |   12480 |   # ★★★★ 這張就是未爆彈
| appdb        | temp_import   |     102841 |      38 |
+--------------+---------------+------------+---------+
```

修法（★★★ 大表要用線上 DDL，並走變更管理流程 [[03-風險與變更管理]]）：

```sql
-- 有現成的唯一欄位就直接升為主鍵
ALTER TABLE appdb.access_log ADD PRIMARY KEY (log_id), ALGORITHM=INPLACE, LOCK=NONE;

-- 沒有就補一個代理鍵
ALTER TABLE appdb.access_log
  ADD COLUMN id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY FIRST;
```

> [!warning] ★★★ 這個檢查應該是「新表上線前的把關項目」
> 不要等到延遲爆炸才來補主鍵 —— 大表加主鍵本身就是一次高風險變更。
> 把上面那段 SQL 放進 [[07-自動化健康檢查實戰]] 的每日檢查，發現一張處理一張。

### 其他延遲成因與對策

| 成因 | 症狀 | 對策 | 星級 |
| --- | --- | --- | --- |
| **無主鍵表** | 延遲持續增長，從庫 CPU 100% 單核 | 補主鍵 | ★★★★ |
| **單筆大交易** | 延遲週期性跳到幾百秒又回到 0 | 拆成每次 1000~5000 列的批次，中間 `sleep` | ★★★★ |
| **applier 單執行緒** | 主庫多核心滿載、從庫只有一核在跑 | `replica_parallel_workers` + WRITESET | ★★★ |
| 從庫上跑長報表 | 延遲與報表時段完全重合 | 報表加 `MAX_EXECUTION_TIME`，或再加一台從庫 | ★★★ |
| 從庫硬體較差 | 長期性、平穩的落後 | ★★★ 從庫規格**不要低於主庫**，切換後它就是主庫 | ★★★ |
| `sync_binlog=1` + 慢磁碟 | 從庫 I/O wait 高 | 從庫可考慮 `sync_binlog=0`（★★ 犧牲從庫本身的崩潰安全） | ★★ |

### 開啟並行 applier

```sql
STOP REPLICA SQL_THREAD;
SET GLOBAL replica_parallel_workers = 8;         -- 約等於 CPU 核心數，先從 4~8 試
SET GLOBAL replica_preserve_commit_order = ON;   -- 8.0.27+ 預設 ON
START REPLICA SQL_THREAD;

-- ★★★★ 主庫上也要設，並行度來自「主庫寫 binlog 時算好的相依關係」
SET GLOBAL binlog_transaction_dependency_tracking = WRITESET;
```

> [!note] ★★★ 並行度是主庫決定的，不是從庫
> `WRITESET` 讓**主庫**在寫 binlog 時分析每筆交易改了哪些列，
> 沒有衝突的交易標成同一個「可並行群組」。從庫的 worker 只是照著這個標記分工。
> 所以**只在從庫開 `replica_parallel_workers` 而主庫還是 `COMMIT_ORDER`，效果非常有限**
> —— 這是最常見的「開了並行但沒變快」的原因。
>
> MySQL 8.0 的預設是 `COMMIT_ORDER`（要手動改成 `WRITESET`），
> MySQL 8.2 起 `WRITESET` 成為預設值，該變數本身在新版已標記為 deprecated。
> ★★ `WRITESET` 需要 `binlog_format=ROW`，這是選 ROW 的另一個理由。

查看每個 worker 在做什麼：

```bash
mysql -e "SELECT WORKER_ID, THREAD_ID, SERVICE_STATE, LAST_ERROR_MESSAGE
          FROM performance_schema.replication_applier_status_by_worker;"
```

預期輸出：

```text
+-----------+-----------+---------------+--------------------+
| WORKER_ID | THREAD_ID | SERVICE_STATE | LAST_ERROR_MESSAGE |
+-----------+-----------+---------------+--------------------+
|         1 |        52 | ON            |                    |   # ★ 全部 ON
|         2 |        53 | ON            |                    |
...
```

★★★★ 並行 applier 出錯時，`SHOW REPLICA STATUS` 的 `Last_SQL_Error` 可能只給你摘要，
**真正的錯誤在 `replication_applier_status_by_worker` 的 `LAST_ERROR_MESSAGE`**。

### ★★★★ 延遲從庫：誤操作的救生艇

```sql
STOP REPLICA;
CHANGE REPLICATION SOURCE TO SOURCE_DELAY = 3600;   -- 刻意落後 1 小時
START REPLICA;
```

```bash
mysql -e "SHOW REPLICA STATUS\G" | grep -E 'SQL_Delay|SQL_Remaining_Delay|Replica_SQL_Running_State'
```

預期輸出：

```text
                    SQL_Delay: 3600
          SQL_Remaining_Delay: 3412            # ★ 距離套用下一筆事件還要等 3412 秒
    Replica_SQL_Running_State: Waiting until SOURCE_DELAY seconds after source executed event
```

用法：有人 09:41 下了 `DROP TABLE members`，你在 10:05 發現。
延遲從庫上的 `members` **還在**（它要到 10:41 才會執行那個 DROP）。

```sql
-- 【1】立刻凍住延遲從庫，不要讓它繼續套用
STOP REPLICA SQL_THREAD;      -- ★★★★★ 這是整個流程最緊急的一步，先做這個

-- 【2】確認資料還在
SELECT COUNT(*) FROM appdb.members;

-- 【3】把資料撈出來
-- （在 shell 上）
--   mysqldump -h 10.0.1.12 --single-transaction appdb members > /var/backups/members-rescue.sql
```

| 比較 | 延遲從庫 | PITR（[[05-MySQL-備份與還原]]） |
| --- | --- | --- |
| 恢復速度 | ★★★★ 分鐘級，資料就在線上 | 小時級，要還原全備 + 重放 binlog |
| 可回溯範圍 | 只有 `SOURCE_DELAY` 那段時間 | ★★★★ 整個 binlog 保留期 |
| 成本 | 一台機器 | 備份儲存空間 |
| 兩者關係 | **互補，不是二選一** | **互補，不是二選一** |

★★★ 延遲從庫**不能同時當故障切換的目標**（它永遠落後一小時）。
需要兩者都要時，架構是「主庫 + 即時從庫（切換用）+ 延遲從庫（救援用）」。

### 半同步（可選）

> [!warning] 未實機驗證
> 本段依 MySQL 8.0 官方文件撰寫，未在實機環境驗證。
> ★★★ 8.0.26 起外掛與變數改名（`master`→`source`、`slave`→`replica`），
> **新舊版外掛不能同時安裝**。請對照你的實際版本。

```sql
-- 主庫（MySQL 8.0.26+）
INSTALL PLUGIN rpl_semi_sync_source SONAME 'semisync_source.so';
SET GLOBAL rpl_semi_sync_source_enabled = 1;
SET GLOBAL rpl_semi_sync_source_timeout = 1000;      -- 毫秒

-- 從庫
INSTALL PLUGIN rpl_semi_sync_replica SONAME 'semisync_replica.so';
SET GLOBAL rpl_semi_sync_replica_enabled = 1;
STOP REPLICA IO_THREAD; START REPLICA IO_THREAD;     -- ★★★ 要重啟 IO thread 才生效
```

```bash
# ★★★★ 這個狀態變數一定要納入監控
mysql -e "SHOW STATUS LIKE 'Rpl_semi_sync_source_status';"
```

預期輸出：

```text
+-----------------------------+-------+
| Variable_name               | Value |
+-----------------------------+-------+
| Rpl_semi_sync_source_status | ON    |    # ★★★★ OFF = 已靜默降級成非同步
+-----------------------------+-------+
```

---

## 複寫中斷的正確處理

### ★★★★ 第一原則：不要反射性地跳過錯誤

複寫停住時，`Last_SQL_Error` 給了你一個明確的錯誤。網路上最常見的答案是「跳過它」。
**跳過錯誤只是把「複寫停了」這個看得見的問題，換成「主從資料不一致」這個看不見的問題。**

複寫會停下來，是因為它偵測到「主庫叫我做的事，在我這裡做不出來」——
這代表**主從已經不一致了**。停下來是保護機制，不是故障。

| 錯誤碼 | 訊息 | 真正的成因 | 星級 |
| --- | --- | --- | --- |
| **1062** | `Duplicate entry 'xxx' for key 'PRIMARY'` | 從庫**已經有**這一列 → 曾被直接寫入（`super_read_only` 沒設）／初始同步的 GTID 起點錯了／同一筆交易被重放 | ★★★★ |
| **1032** | `Can't find record in 'xxx'` | 從庫**少了**這一列或欄位值對不上 → 從庫被人刪過／初始同步時漏資料 | ★★★★ |
| 1146 | `Table 'appdb.xxx' doesn't exist` | 主庫上做的 DDL 在從庫沒有（有人在從庫上 `DROP`，或曾用 `replica_skip_errors` 跳過 DDL） | ★★★ |
| 1050 | `Table 'xxx' already exists` | 從庫已存在同名表，通常是初始同步範圍與 binlog 起點重疊 | ★★★ |
| 1236 | `the source has purged binary logs...` | ★★★★ 主庫 binlog 被清掉了，從庫離線太久 → **只能重做整台從庫** | ★★★★ |
| 1594 | `Relay log read failure` | relay log 損毀（多半是從庫非正常關機） | ★★★ |
| 2003 | `Can't connect to MySQL server` | 網路／防火牆／主庫沒起來 | ★★★ |
| 1045 | `Access denied for user 'repl'` | 密碼錯、來源網段沒涵蓋、`REQUIRE SSL` 但連線沒帶憑證 | ★★★ |

### 標準處理流程

```bash
# 【1】先看錯誤全文，不要只看摘要
mysql -e "SHOW REPLICA STATUS\G" | grep -A2 -E 'Last_SQL_Error|Last_IO_Error'
mysql -e "SELECT WORKER_ID, LAST_ERROR_NUMBER, LAST_ERROR_MESSAGE
          FROM performance_schema.replication_applier_status_by_worker
          WHERE LAST_ERROR_NUMBER <> 0\G"
```

```bash
# 【2】★★★★ 找出是哪一筆 GTID 卡住
mysql -e "SELECT LAST_QUEUED_TRANSACTION, APPLYING_TRANSACTION
          FROM performance_schema.replication_applier_status_by_worker\G"
```

預期輸出：

```text
LAST_QUEUED_TRANSACTION: 3e11fa47-71ca-11e1-9e33-c80aa9429562:45261
    APPLYING_TRANSACTION: 3e11fa47-71ca-11e1-9e33-c80aa9429562:45261
```

```bash
# 【3】★★★★ 到主庫上把這筆交易的內容挖出來，看它到底要做什麼
mysqlbinlog --base64-output=DECODE-ROWS --verbose \
  --include-gtids='3e11fa47-71ca-11e1-9e33-c80aa9429562:45261' \
  /var/log/mysql/mysql-bin.000012 | head -60
```

預期輸出：

```text
### UPDATE `appdb`.`members`
### WHERE
###   @1=10247            /* INT meta=0 nullable=0 is_null=0 */
###   @3='王小明'          /* ★ 這是「前映像」—— 從庫上這一列必須長這樣才找得到 */
### SET
###   @1=10247
###   @3='王大明'
```

```sql
-- 【4】比對從庫上那一列的實際狀態
SELECT * FROM appdb.members WHERE id = 10247\G
```

看到什麼代表什麼：

- 那一列**不存在** → 從庫曾被刪過，或初始同步不完整 → 走「補資料」而非「跳過」
- 那一列**存在但欄位值不同** → 從庫曾被直接寫入 → 先查誰寫的（見安全性一節的稽核）
- 那一列**與 SET 之後的值一模一樣** → 這筆交易已經套用過 → **這種情況才適合跳過**

### 真的必須跳過時：GTID 模式下注入空交易

```sql
-- ★★★★ 只有在【4】確認「跳過不會造成資料差異」時才做
STOP REPLICA;
SET GTID_NEXT = '3e11fa47-71ca-11e1-9e33-c80aa9429562:45261';
BEGIN; COMMIT;                    -- 產生一筆什麼都不做的交易，佔掉這個 GTID
SET GTID_NEXT = 'AUTOMATIC';
START REPLICA;

-- 驗證
SELECT @@GLOBAL.gtid_executed\G
```

> [!danger] ★★★★ 注入空交易 = 你簽名同意「這筆交易永遠不會被套用」
> 它跟 `sql_replica_skip_counter`（只能用在非 GTID 模式）不同的是：
> **被跳過的是哪一筆有明確紀錄**，`gtid_executed` 裡有它、但資料沒有它。
> 三件事一定要做：
> **①** 把跳過的 GTID 與原因寫進 [[09-事件處理與升級流程]] 的事件單。
> **②** 跳過後**必須**跑一次 `pt-table-checksum` 確認影響範圍。
> **③** 一次要跳很多筆，代表分歧已經很嚴重 —— **重做整台從庫比逐筆跳快也安全**。
>
> ★★★★★ **絕對不要在 my.cnf 寫 `replica_skip_errors = 1062,1032`。**
> 那等於永久關掉這個保護機制，從此複寫「永遠不會斷」，
> 而主從的資料會靜默地愈差愈遠，直到你切換過去才發現整個資料庫是錯的。

### 驗證與修復一致性

```bash
# 【1】檢查（在主庫上跑，會自動比對所有從庫）
pt-table-checksum --host=10.0.1.11 --user=checksum --ask-pass \
  --databases=appdb --max-lag=30 --chunk-time=0.5
```

預期輸出：

```text
            TS ERRORS  DIFFS     ROWS  DIFF_ROWS  CHUNKS SKIPPED    TIME TABLE
08-29T10:22:41      0      0   184213          0      19       0   6.201 appdb.orders
08-29T10:22:49      0      2    49821          7       5       0   3.114 appdb.members
                           ↑
                    ★★★★ DIFFS 不是 0 = 主從不一致
```

```bash
# 【2】先「只看不改」，確認 pt-table-sync 打算怎麼修
pt-table-sync --print --replicate=percona.checksums h=10.0.1.11 h=10.0.1.12

# 【3】確認無誤後才執行（★★★★ 一定要從主庫方向推，不要直接寫從庫）
pt-table-sync --execute --replicate=percona.checksums h=10.0.1.11 h=10.0.1.12
```

★★★ `pt-table-checksum` 需要 `binlog_format=ROW`（本篇已設）與一個有適當權限的帳號；
它會在主庫上寫 `percona.checksums`，這個寫入本身也會複寫過去 —— 這正是它的運作原理。
★★★ 跑之前先在測試環境試一次，`--max-lag` 設好，否則它會把已經很喘的從庫壓垮。

---

## ★★★★★ 計畫性切換與故障切換

> [!danger] ★★★★★ 全程只有一個真正的敵人：雙寫（split brain）
> 如果在任何一個時間點，**舊主庫與新主庫同時可寫**，
> 兩邊會各自產生不同的 GTID，寫入不同的資料。
> 這種分歧**無法自動合併** —— 沒有任何工具能判斷「兩筆同時修改的訂單，哪一筆才對」。
> 唯一的收場是人工逐表比對，或是宣告其中一邊的資料作廢。
>
> 因此整個程序的核心不是「怎麼把服務指到新主庫」，
> 而是**「怎麼確認舊主庫已經不可寫」**。下面每一個 ★★★★ 的步驟都在做這件事。

> [!warning] ★★★★ 請務必先在測試環境完整演練過再上正式機
> 切換是少數「照著念也會出錯」的操作，因為出錯時你在壓力之下。
> 建議每半年演練一次，把每一步的**實際耗時**記下來 ——
> 這個數字就是你的 RTO，也是寫進 [[06-災難復原與異地備援]] 的依據。

### 計畫性切換（主庫還活著，例如要換硬體）

| 步驟 | 動作 | 在哪台 | 驗證 |
| --- | --- | --- | --- |
| 【1】 | 應用進維護模式 | app1 | 前台顯示維護頁 |
| 【2】 | ★★★★ 主庫封寫 | db1 | `super_read_only=1` |
| 【3】 | ★★★★ 等從庫追平 | db2 | GTID 落差為空 |
| 【4】 | 從庫脫離複寫 | db2 | `SHOW REPLICA STATUS` 為空 |
| 【5】 | ★★★★ 從庫開放寫入 | db2 | `super_read_only=0` |
| 【6】 | 應用改連線 | app1 | 寫入測試成功 |
| 【7】 | ★★★★ 舊主降級為從庫 | db1 | 反向複寫正常 |
| 【8】 | 解除維護模式 | app1 | 服務恢復 |

```bash
# ═══【1】app1：應用進維護模式（Laravel）═══
php /var/www/app/artisan down --secret="檢查用的隨機字串" --render="errors::503"
```

```bash
# ═══【2】db1：封寫（★★★★ 這一步就是防雙寫的核心）═══
mysql -h 10.0.1.11 -e "SET GLOBAL super_read_only = ON;"
mysql -h 10.0.1.11 -e "SELECT @@read_only, @@super_read_only;"
```

預期輸出：

```text
+-------------+-------------------+
| @@read_only | @@super_read_only |
|           1 |                 1 |    # ★★★★ 兩個都要 1
+-------------+-------------------+
```

```bash
# ★★★★ 確認沒有殘留的寫入連線（有的話先 KILL，否則它們的交易還沒進 binlog）
mysql -h 10.0.1.11 -e "SELECT ID, USER, HOST, DB, COMMAND, TIME, STATE, INFO
  FROM information_schema.PROCESSLIST
  WHERE COMMAND NOT IN ('Sleep','Binlog Dump GTID') AND USER NOT IN ('repl','system user')\G"
```

```bash
# ═══【3】db2：等追平（★★★★ 不追平就切 = 資料遺失）═══
SRC=$(mysql -h 10.0.1.11 -N -e "SELECT @@GLOBAL.gtid_executed;" | tr -d '\n')
mysql -h 10.0.1.12 -N -e "SELECT GTID_SUBTRACT('$SRC', @@GLOBAL.gtid_executed);"
```

預期輸出：

```text
                       # ★★★★ 必須是空字串。非空就繼續等，不要跳過這一步
```

也可以用官方的等待函式（最多等 300 秒，回傳 0 代表已追平）：

```bash
mysql -h 10.0.1.12 -N -e "SELECT WAIT_FOR_EXECUTED_GTID_SET('$SRC', 300);"
```

```text
0        # ★ 0 = 已追平；1 = 逾時，★★★★ 逾時就中止切換並回滾
```

```bash
# ═══【4】【5】db2：脫離複寫、開放寫入 ═══
mysql -h 10.0.1.12 -e "
  STOP REPLICA;
  RESET REPLICA ALL;              -- ★★★ 清掉複寫設定，避免重啟後又跑去連舊主庫
  SET GLOBAL super_read_only = OFF;
  SET GLOBAL read_only = OFF;"

mysql -h 10.0.1.12 -e "SHOW REPLICA STATUS\G"     # ★ 應該輸出 Empty set
mysql -h 10.0.1.12 -e "SELECT @@read_only, @@super_read_only;"
```

```text
Empty set (0.00 sec)
+-------------+-------------------+
| @@read_only | @@super_read_only |
|           0 |                 0 |
+-------------+-------------------+
```

★★★★ 同時把 db2 的 `zz-replication.cnf` 裡的 `read_only`／`super_read_only` 改成 `OFF`，
否則**下次重啟又變回唯讀，整個服務會在半夜自己掛掉**。

```bash
# ═══【6】app1：切連線 ═══
sudo sed -i 's/^DB_HOST=10\.0\.1\.11$/DB_HOST=10.0.1.12/' /var/www/app/.env
cd /var/www/app && php artisan config:clear && php artisan config:cache
sudo systemctl reload php8.3-fpm            # ★★★ 見 [[02-PHP-FPM設定與Pool調校]]
php artisan tinker --execute="DB::statement('SELECT 1'); echo DB::selectOne('SELECT @@hostname h')->h;"
```

```text
db2        # ★★★★ 確認真的連到新主庫
```

> [!tip] ★★★ 用 VIP 或 ProxySQL 可以免去改 `.env`
> `.env` + `config:cache` 的作法簡單、可稽核，但每次切換都要動應用主機。
> 規模大一點的環境會用 **Keepalived VIP**（切換時把 VIP 飄到新主庫）
> 或 **ProxySQL**（應用固定連 ProxySQL，由它決定後端）。
> 這兩種的建置見 [[04-高可用與負載平衡架構]]，本篇不展開。
> ★★★★ 但要注意：**VIP 飄移本身也可能造成雙寫**（舊主庫沒真的死、VIP 兩邊都在）——
> 「確認舊主已不可寫」這一步在任何架構下都不能省。

```bash
# ═══【7】db1：降級為 db2 的從庫 ═══
mysql -h 10.0.1.11 -e "
  CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='10.0.1.12', SOURCE_USER='repl', SOURCE_PASSWORD='……',
    SOURCE_AUTO_POSITION=1, SOURCE_SSL=1, SOURCE_SSL_CA='/etc/mysql/ssl/ca.pem';
  START REPLICA;"
mysql -h 10.0.1.11 -e "SHOW REPLICA STATUS\G" | grep -E 'Running|Source_Host'
```

```text
Source_Host: 10.0.1.12
Replica_IO_Running: Yes
Replica_SQL_Running: Yes         # ★★★★ 這一步能成功，是因為當初主庫也開了 log_replica_updates
```

★★★★ db1 的 `read_only`／`super_read_only` 保持 `ON`，並寫進它的 my.cnf。
**它現在是從庫，被寫入就是雙寫。**

```bash
# ═══【8】app1：解除維護模式 ═══
php /var/www/app/artisan up
curl -sS -o /dev/null -w '%{http_code}\n' https://app.example.gov.tw/healthz
```

```text
200
```

### ★★★★★ 回滾：切換失敗怎麼指回原主庫

只要**還沒有任何寫入落在 db2 上**，回滾非常單純。判斷點在【6】之前還是之後。

```bash
# ═══ 情境 A：在【6】之前發現問題（db2 還沒收到任何寫入）═══
php /var/www/app/artisan down                       # 確保應用仍在維護模式
mysql -h 10.0.1.12 -e "SET GLOBAL super_read_only=ON; SET GLOBAL read_only=ON;"
mysql -h 10.0.1.12 -e "
  CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='10.0.1.11', SOURCE_USER='repl', SOURCE_PASSWORD='……',
    SOURCE_AUTO_POSITION=1, SOURCE_SSL=1, SOURCE_SSL_CA='/etc/mysql/ssl/ca.pem';
  START REPLICA;"
mysql -h 10.0.1.11 -e "SET GLOBAL super_read_only=OFF; SET GLOBAL read_only=OFF;"
php /var/www/app/artisan up
```

```bash
# ═══ 情境 B：在【6】之後才發現（db2 已經有新寫入）═══
# ★★★★★ 不能直接把應用指回 db1 —— db1 缺少 db2 上的新交易，指回去等於資料遺失。
# 正確做法：修正問題後繼續用 db2，讓 db1 以從庫身分把 db2 的新交易追回來。
mysql -h 10.0.1.12 -N -e "SELECT @@GLOBAL.gtid_executed;"   # 記下新主庫的 GTID
mysql -h 10.0.1.11 -e "SHOW REPLICA STATUS\G" | grep -E 'Running|Error'
# 確認 db1 追平後，才有資格談「切回去」，而那是另一次完整的計畫性切換
```

### 故障切換（主庫已經掛了）

主庫掛掉時，【2】【3】做不到 —— 你無法封寫一台連不上的機器，也無法確認它是否追平。

```bash
# 【1】★★★★★ 第一件事不是切換，是「確定舊主庫真的死了」
ping -c3 10.0.1.11
ssh 10.0.1.11 'systemctl is-active mysql'
# 連得上但 MySQL 掛了 → 立刻 systemctl stop mysql && systemctl disable mysql
# 完全連不上 → ★★★★ 從交換器端關掉那個 port，或請機房確認電源已斷（STONITH 的精神）
```

> [!danger] ★★★★★ 「主庫沒回應」不等於「主庫已停止寫入」
> 最典型的災難：主庫只是網路卡掉了，MySQL 還活著、應用的部分連線還通。
> 你切到 db2、應用開始寫 db2，然後網路恢復 —— 舊主庫上還有一批寫入，
> 兩邊 GTID 分岔，**永久分歧**。
> **在確認舊主庫不可寫之前，一行都不要往新主庫寫。**

```bash
# 【2】檢查從庫落後多少（這就是你即將遺失的資料量）
mysql -h 10.0.1.12 -e "SHOW REPLICA STATUS\G" | grep -E 'Retrieved_Gtid_Set|Executed_Gtid_Set'
# ★★★★ Retrieved 比 Executed 多的部分，是「已收到但還沒套用」→ 先等它跑完
mysql -h 10.0.1.12 -e "STOP REPLICA IO_THREAD;"     # 停 IO、讓 applier 把 relay log 跑完
mysql -h 10.0.1.12 -e "SELECT WAIT_FOR_EXECUTED_GTID_SET('<Retrieved_Gtid_Set 的值>', 300);"

# 【3】之後與計畫性切換的【4】~【8】相同
```

★★★★ 舊主庫救回來之後，**不要直接 `START REPLICA` 讓它接回去**。
先比對它的 `gtid_executed` 是否為新主庫的子集：

```bash
OLD=$(mysql -h 10.0.1.11 -N -e "SELECT @@GLOBAL.gtid_executed;" | tr -d '\n')
mysql -h 10.0.1.12 -N -e "SELECT GTID_SUBTRACT('$OLD', @@GLOBAL.gtid_executed) AS orphan;"
```

```text
orphan:                     # ★ 空 = 舊主庫沒有多出來的交易，可以安全接回

orphan: 3e11fa47-…:45261-45268
        # ★★★★★ 舊主庫上有 8 筆交易沒複寫出去 → 資料已分歧
        # 不要接回去。用 mysqlbinlog 把這 8 筆挖出來人工判讀，
        # 決定要補到新主庫還是作廢，然後重做這台從庫。
```

---

## 應用端讀寫分離

### Laravel 的 read/write 設定

```php
// config/database.php
'mysql' => [
    'driver' => 'mysql',
    'read'  => [ 'host' => ['10.0.1.12'] ],          // 從庫，唯讀
    'write' => [ 'host' => ['10.0.1.11'] ],          // 主庫
    'sticky' => true,                                 // ★★★★ 見下方
    'port'     => env('DB_PORT', '3306'),
    'database' => env('DB_DATABASE'),
    'username' => env('DB_USERNAME'),
    'password' => env('DB_PASSWORD'),
    'charset'  => 'utf8mb4',
    'collation'=> 'utf8mb4_unicode_ci',
    'options'  => [
        PDO::MYSQL_ATTR_SSL_CA => '/etc/mysql/ssl/ca.pem',   // ★★★ 應用連線也走 TLS
    ],
],
```

### ★★★★ 「剛寫入立刻讀取卻讀不到」

這是導入讀寫分離後**必然會遇到**的問題，而且它在測試環境（延遲 0.01 秒）不會出現，
只會在正式環境流量上來之後出現，症狀是「使用者按了儲存，畫面顯示沒存到，再按一次就變兩筆」。

```text
  t=0.000  POST /orders     → 寫入主庫 db1，訂單 id=9001
  t=0.004  302 導向 /orders/9001
  t=0.010  GET /orders/9001 → 讀從庫 db2
                              db2 還沒收到這筆 → 404
  t=0.180  db2 收到了。使用者重整就看得到 —— 但他已經按了第二次送出
```

| 處理方式 | 有效範圍 | 星級 |
| --- | --- | --- |
| `'sticky' => true` | ★★★★ **同一個 request 內**寫入後的所有讀取自動走主庫 | ★★★★ |
| `DB::connection('mysql')->getPdo()`（強制主庫連線） | 明確指定的那幾個查詢 | ★★★ |
| 佇列 job 用 `->afterCommit()` + 延遲派送 | ★★★★ **跨 request 的情境，`sticky` 救不到** | ★★★★ |
| 寫入後直接用記憶體中的物件，不重新查 | 最省事、最可靠 | ★★★ |

> [!danger] ★★★★ `sticky` 只在「同一個 request」內有效
> 它對這三種情境**完全無效**：
> **①** 前端寫入後另外發一個 AJAX 去讀（兩個 request）。
> **②** 佇列 job：`OrderCreated` 派送後 worker 立刻執行，此時主庫的交易可能還沒 commit。
> ★★★★ Laravel 的解法是佇列連線設 `'after_commit' => true` 或
> job 加 `public $afterCommit = true;`，並視延遲加上 `->delay(now()->addSeconds(5))`。
> **③** 排程任務、API 給第三方回呼。
>
> 原則寫成一句話給開發團隊：
> **「凡是需要看到自己剛寫的資料，就走主庫。」**
> Eloquent 的細節見 [[04-Laravel-Eloquent與資料庫]]，佇列見 [[03-Laravel-佇列排程與Supervisor]]。

★★★ 從庫上跑報表時，記得給查詢設上限，避免一支寫爛的報表把 applier 卡住：

```sql
SELECT /*+ MAX_EXECUTION_TIME(30000) */ ...   -- 30 秒後自動中止
```

---

## 完整實戰範例

情境：db1（10.0.1.11）與 db2（10.0.1.12）已依前面兩節建好 GTID 主從、心跳表也已就緒。
現在要做完最後兩件事 —— **部署複寫監控腳本**，然後**排一次計畫性切換演練**。

### 複寫監控腳本

```bash
sudo tee /usr/local/bin/mysql-repl-check.sh > /dev/null << 'EOF'
#!/usr/bin/env bash
# mysql-repl-check.sh — MySQL 從庫複寫健康檢查
# 用法：mysql-repl-check.sh [--source-host 10.0.1.11]
# 退出碼：0 正常 / 1 警告 / 2 嚴重（含複寫中斷）
set -euo pipefail

SOURCE_HOST="${SOURCE_HOST:-10.0.1.11}"
LAG_WARN="${LAG_WARN:-30}"          # 秒
LAG_CRIT="${LAG_CRIT:-300}"         # 秒
GTID_WARN="${GTID_WARN:-1000}"      # 落後交易筆數
LOGFILE="/var/log/mysql-repl-check.log"
STATEFILE="/run/mysql-repl-check.state"
ALERT_CMD="${ALERT_CMD:-}"          # 例：/usr/local/bin/send-alert.sh
MYSQL="mysql --defaults-file=/etc/mysql/repl-check.cnf -N -B"

RC=0; MSGS=()

log()  { printf '%s [%s] %s\n' "$(date '+%F %T')" "$1" "$2" >> "$LOGFILE"; }
warn() { MSGS+=("WARN: $1"); log WARN "$1"; [[ $RC -lt 1 ]] && RC=1 || true; }
crit() { MSGS+=("CRIT: $1"); log CRIT "$1"; RC=2; }

die() { log FATAL "$1"; printf 'FATAL: %s\n' "$1" >&2; exit 2; }

# ── 前置檢查 ──────────────────────────────────────────────
command -v mysql >/dev/null || die "找不到 mysql client"
[[ -r /etc/mysql/repl-check.cnf ]] || die "讀不到 /etc/mysql/repl-check.cnf（權限應為 600）"
$MYSQL -e "SELECT 1" >/dev/null 2>&1 || die "無法連線本機 MySQL，服務可能已停止"

# ── 【1】本機必須是從庫且唯讀 ─────────────────────────────
STATUS="$($MYSQL -e "SHOW REPLICA STATUS\G" 2>/dev/null || true)"
[[ -n "$STATUS" ]] || die "SHOW REPLICA STATUS 為空 —— 這台不是從庫，或已被 RESET REPLICA ALL"

field() { sed -n "s/^ *$1: *//p" <<< "$STATUS" | head -1; }

SRO="$($MYSQL -e "SELECT @@super_read_only")"
[[ "$SRO" == "1" ]] || crit "super_read_only=$SRO（應為 1）—— 從庫可被寫入，有主從分歧風險"

# ── 【2】兩條執行緒 ───────────────────────────────────────
IO="$(field Replica_IO_Running)"; SQLT="$(field Replica_SQL_Running)"
[[ "$IO"   == "Yes" ]] || crit "Replica_IO_Running=$IO；Last_IO_Error=[$(field Last_IO_Error)]"
[[ "$SQLT" == "Yes" ]] || crit "Replica_SQL_Running=$SQLT；Last_SQL_Error=[$(field Last_SQL_Error)]"

# ── 【3】錯誤欄位（即使 Running=Yes 也可能殘留警告）────────
LE="$(field Last_Errno)"; [[ -z "$LE" || "$LE" == "0" ]] || warn "Last_Errno=$LE $(field Last_Error)"

# ── 【4】GTID 落差（★★★★ 不會騙人的指標）─────────────────
if SRC_GTID="$(mysql --defaults-file=/etc/mysql/repl-check.cnf -h "$SOURCE_HOST" -N -B \
                 -e "SELECT @@GLOBAL.gtid_executed" 2>/dev/null | tr -d '\n')"; then
  MISSING="$($MYSQL -e "SELECT GTID_SUBTRACT('$SRC_GTID', @@GLOBAL.gtid_executed)" | tr -d '\n')"
  if [[ -n "$MISSING" ]]; then
    N="$(awk -F'[:-]' '{s=0; for(i=3;i<=NF;i+=2){s+=$(i+1)-$i+1} print s+0}' <<< "$MISSING")"
    [[ "$N" -gt "$GTID_WARN" ]] && warn "GTID 落後約 $N 筆交易：$MISSING"
  fi
else
  warn "連不到主庫 $SOURCE_HOST，無法比對 GTID（主庫可能已故障）"
fi

# ── 【5】心跳表真延遲（★★★★ 不要只信 Seconds_Behind_Source）──
LAG="$($MYSQL -e "SELECT ROUND(TIMESTAMPDIFF(MICROSECOND, ts, NOW(6))/1000000,2)
                  FROM ops.heartbeat WHERE id=1" 2>/dev/null || echo "")"
if [[ -z "$LAG" ]]; then
  warn "讀不到 ops.heartbeat —— 心跳 EVENT 可能沒在跑（檢查主庫 event_scheduler）"
elif awk -v l="$LAG" -v c="$LAG_CRIT" 'BEGIN{exit !(l>c)}'; then
  crit "心跳延遲 ${LAG}s（門檻 ${LAG_CRIT}s）"
elif awk -v l="$LAG" -v w="$LAG_WARN" 'BEGIN{exit !(l>w)}'; then
  warn "心跳延遲 ${LAG}s（門檻 ${LAG_WARN}s）"
fi

# ── 【6】對照 Seconds_Behind_Source，不一致時特別提醒 ──────
SBS="$(field Seconds_Behind_Source)"
if [[ "$SBS" == "0" && "$IO" != "Yes" ]]; then
  crit "Seconds_Behind_Source=0 但 IO thread 已斷 —— 這是最危險的假綠燈"
fi

# ── 輸出與告警 ────────────────────────────────────────────
if [[ ${#MSGS[@]} -eq 0 ]]; then
  echo "OK 複寫正常 lag=${LAG}s io=$IO sql=$SQLT"
  log OK "複寫正常 lag=${LAG}s"
  rm -f "$STATEFILE"
else
  printf '%s\n' "${MSGS[@]}"
  # ★★★ 只在狀態改變時告警，避免每分鐘洗頻
  NEW="$(printf '%s\n' "${MSGS[@]}" | md5sum | cut -d' ' -f1)"
  OLD="$(cat "$STATEFILE" 2>/dev/null || true)"
  if [[ "$NEW" != "$OLD" && -n "$ALERT_CMD" ]]; then
    "$ALERT_CMD" "[db2] MySQL 複寫異常" "$(printf '%s\n' "${MSGS[@]}")" || log WARN "告警送出失敗"
  fi
  echo "$NEW" > "$STATEFILE"
fi
exit "$RC"
EOF

sudo chmod 750 /usr/local/bin/mysql-repl-check.sh
```

專用帳號與設定檔（★★★★ 不要用 root 跑監控）：

```sql
-- 兩台都建
CREATE USER 'replcheck'@'10.0.1.%' IDENTIFIED BY '……' REQUIRE SSL;
GRANT REPLICATION CLIENT, PROCESS ON *.* TO 'replcheck'@'10.0.1.%';
GRANT SELECT ON ops.* TO 'replcheck'@'10.0.1.%';
```

```bash
sudo tee /etc/mysql/repl-check.cnf > /dev/null << 'EOF'
[client]
user = replcheck
password = ……
ssl-ca = /etc/mysql/ssl/ca.pem
ssl-mode = VERIFY_CA
EOF
sudo chmod 600 /etc/mysql/repl-check.cnf     # ★★★★ 密碼檔權限
sudo chown root:root /etc/mysql/repl-check.cnf
```

驗證與排程：

```bash
sudo /usr/local/bin/mysql-repl-check.sh; echo "exit=$?"
```

預期輸出：

```text
OK 複寫正常 lag=0.31s io=Yes sql=Yes
exit=0
```

```bash
# 刻意製造故障來驗證腳本真的會抓到（★★★ 演練必做）
mysql -e "STOP REPLICA IO_THREAD;"
sudo /usr/local/bin/mysql-repl-check.sh; echo "exit=$?"
mysql -e "START REPLICA IO_THREAD;"
```

```text
CRIT: Replica_IO_Running=No；Last_IO_Error=[]
exit=2
```

```bash
# systemd timer，每分鐘跑一次（寫法見 [[02-systemd-timer與cron選型]]）
sudo tee /etc/systemd/system/mysql-repl-check.service > /dev/null << 'EOF'
[Unit]
Description=MySQL replication health check
[Service]
Type=oneshot
Environment=ALERT_CMD=/usr/local/bin/send-alert.sh
ExecStart=/usr/local/bin/mysql-repl-check.sh
EOF

sudo tee /etc/systemd/system/mysql-repl-check.timer > /dev/null << 'EOF'
[Unit]
Description=Run MySQL replication check every minute
[Timer]
OnBootSec=3min
OnUnitActiveSec=1min
[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now mysql-repl-check.timer
systemctl list-timers mysql-repl-check.timer --no-pager
```

```text
NEXT                        LEFT  LAST                       PASSED  UNIT
Sat 2026-08-29 10:41:00 CST  38s  Sat 2026-08-29 10:39:59 CST  22s ago mysql-repl-check.timer
```

### 切換演練與耗時紀錄

照著前一節的【1】~【8】做一次，並把**實際耗時**填進這張表。這份紀錄就是你的 RTO 依據，
也是 [[08-變更管理流程]] 要求的演練證明。

| 步驟 | 動作 | 目標耗時 | 實測 | 備註 |
| --- | --- | --- | --- | --- |
| 【1】 | 應用進維護模式 | < 10s | 6s | `artisan down` |
| 【2】 | db1 `super_read_only=ON` + 清殘留連線 | < 30s | 21s | ★★★★ 有 2 條長連線需 KILL |
| 【3】 | 等 db2 追平 | < 60s | 3s | 離峰時段落差本來就小 |
| 【4】【5】 | db2 脫離複寫、開放寫入 | < 20s | 8s | 別忘了改 my.cnf |
| 【6】 | 改 `.env` + `config:cache` + reload FPM | < 60s | 34s | |
| 【7】 | db1 降級為從庫 | < 30s | 17s | |
| 【8】 | 解除維護模式 + 驗證 | < 60s | 41s | |
| | **總計（RTO）** | **< 5 分鐘** | **2 分 10 秒** | |

### 驗收檢查表

| # | 檢查項 | 指令 | 預期結果 | 星級 |
| --- | --- | --- | --- | --- |
| 1 | 兩台 `server_id` / `server_uuid` 不同 | `mysql -e "SELECT @@server_id,@@server_uuid"` | 兩台皆不同 | ★★★★ |
| 2 | GTID 已啟用 | `mysql -e "SELECT @@gtid_mode,@@enforce_gtid_consistency"` | `ON` / `ON` | ★★★★ |
| 3 | binlog 格式與保留 | `mysql -e "SELECT @@binlog_format,@@binlog_expire_logs_seconds"` | `ROW` / `≥1209600` | ★★★★ |
| 4 | 從庫雙唯讀 | `mysql -e "SELECT @@read_only,@@super_read_only"` | `1` / `1` | ★★★★ |
| 5 | 兩條執行緒 | `mysql -e "SHOW REPLICA STATUS\G" \| grep Running` | 皆 `Yes` | ★★★★ |
| 6 | 複寫走 TLS | `mysql -e "SHOW REPLICA STATUS\G" \| grep Source_SSL_Allowed` | `Yes` | ★★★★ |
| 7 | GTID 已追平 | `SELECT GTID_SUBTRACT(...)` | 空字串 | ★★★★ |
| 8 | 心跳真延遲 | `SELECT ... FROM ops.heartbeat` | < 5 秒 | ★★★ |
| 9 | 無主鍵表 | 本篇的 `information_schema` 查詢 | 0 列 | ★★★★ |
| 10 | 監控腳本可跑 | `mysql-repl-check.sh` | `exit=0` | ★★★ |
| 11 | 監控會抓到故障 | `STOP REPLICA IO_THREAD` 後再跑 | `exit=2` 並發出告警 | ★★★★ |
| 12 | 防火牆只放行從庫 | `sudo ufw status numbered` | 3306 僅 `10.0.1.12` | ★★★★ |
| 13 | 一致性校驗 | `pt-table-checksum` | `DIFFS = 0` | ★★★ |
| 14 | ★★★★ 備份仍照常執行 | `systemctl list-timers \| grep backup` | 排程存在且成功 | ★★★★ |
| 15 | 切換演練有紀錄 | 上方耗時表 | 已填寫並歸檔 | ★★★ |

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ **切換後兩邊資料都在變，GTID 分岔** | 舊主庫沒有真的停止寫入（網路故障誤判、VIP 兩邊都在、`skip_replica_start` 沒設） | 立刻停掉其中一邊；用 `GTID_SUBTRACT` 找出孤兒交易，`mysqlbinlog` 挖出來人工判讀後重做從庫 |
| ★★★★★ **從庫資料與主庫不同但複寫顯示正常** | 曾用 `replica_skip_errors` 或 `sql_replica_skip_counter` 跳過錯誤 | 移除該設定；`pt-table-checksum` 全庫校驗；差異大就重做從庫 |
| ★★★★ **`Seconds_Behind_Source: 0` 但資料是三天前的** | IO thread 早就斷了，relay log 已跑完 | 改看 `Replica_IO_Running` + GTID 落差；監控要同時抓四個指標 |
| ★★★★ **`Last_IO_Error 1236: ... has purged binary logs`** | `binlog_expire_logs_seconds` 太短，從庫離線期間需要的 binlog 已被清 | 只能重做整台從庫（dump / XtraBackup）；同時調大保留時間 |
| ★★★★ **從庫延遲持續增長、單核 CPU 100%** | ROW 模式下對**沒有主鍵的大表**做批次 UPDATE/DELETE | 補主鍵；把批次拆小；把該表的清理改成分批 + `sleep` |
| ★★★★ **`Last_SQL_Error 1062 Duplicate entry`** | 從庫被直接寫入（`super_read_only` 沒設），或初始同步的 `gtid_purged` 設錯 | 先 `mysqlbinlog` 看該筆交易內容再決定；補設 `super_read_only=ON` |
| ★★★★ **從庫重啟後複寫沒啟動、沒人發現** | `skip_replica_start=ON`（正確設定）但缺少開機後的檢查 | 把「複寫是否啟動」納入 `mysql-repl-check.sh` 與開機檢查表 |
| ★★★ **複寫每隔幾分鐘斷一次又自己好** | 兩台從庫 `server_id` 或 `server_uuid` 撞號，互相把對方踢掉 | 改 `server_id`；刪 `auto.cnf` 重新產生 `server_uuid` |
| ★★★ **主庫閒置一晚後，早上發現 IO thread 斷了** | 中間防火牆／NAT 回收閒置 TCP 連線 | 設 `SOURCE_HEARTBEAT_PERIOD=10`；調整防火牆的 session timeout |
| ★★★ `Access denied for user 'repl'` (1045) | 密碼錯／來源網段不含從庫 IP／`REQUIRE SSL` 但連線沒帶憑證 | `SHOW GRANTS`；確認 `SOURCE_SSL=1` 與 `SOURCE_SSL_CA` 路徑正確 |
| ★★★ 升級到 MySQL 8.4 後監控腳本全掛 | `SHOW SLAVE STATUS` 等舊語法在 8.4 已**移除** | 升級前 `grep -ri "slave status"` 全面改成 `REPLICA` 語法 |
| ★★★ 開了 `replica_parallel_workers` 但延遲沒改善 | 主庫仍是 `binlog_transaction_dependency_tracking=COMMIT_ORDER` | 主庫改成 `WRITESET`（並行度由主庫決定） |
| ★★★ 從庫啟動失敗 `Could not open relay log` | relay log 路徑不存在／權限錯／AppArmor（SELinux）擋住 | 檢查 `ls -ld`、`chown mysql:mysql`；SELinux 要 `restorecon` |
| ★★ `Relay log read failure` (1594) | 從庫非正常關機造成 relay log 損毀 | 已設 `relay_log_recovery=ON` 時多半會自動修復；否則 `RESET REPLICA` 後用 auto position 重抓 |
| ★★ `mysqldump` 匯入後從庫從第 1 筆重放 | 匯入前沒有 `RESET BINARY LOGS AND GTIDS`，`gtid_purged` 沒設進去 | 清空從庫、重做匯入流程 |
| ★★ 半同步「有設定但沒作用」 | 逾時後靜默降級成非同步 | 監控 `Rpl_semi_sync_source_status` 狀態變數 |

### 排查步驟

**【1】先確定是「連不上」還是「跑不動」**

```bash
mysql -e "SHOW REPLICA STATUS\G" | grep -E 'Replica_IO_Running|Replica_SQL_Running'
```

```text
Replica_IO_Running: No     Replica_SQL_Running: Yes    # → 走【2】，網路／帳號／binlog 問題
Replica_IO_Running: Yes    Replica_SQL_Running: No     # → 走【4】，資料衝突
Replica_IO_Running: Yes    Replica_SQL_Running: Yes    # → 走【6】，是延遲不是中斷
```

**【2】IO thread 掛掉：看錯誤碼決定往哪走**

```bash
mysql -e "SHOW REPLICA STATUS\G" | grep -A1 Last_IO_Error
```

```text
Last_IO_Error: error connecting to master 'repl@10.0.1.11:3306' - retry-time: 10 ...
```

- 出現 `2003 Can't connect` → 網路／防火牆問題，跳【3】
- 出現 `1045 Access denied` → 帳號問題：主庫上 `SHOW GRANTS FOR 'repl'@'10.0.1.%'`
- 出現 **`1236 ... has purged binary logs`** → ★★★★ **binlog 沒了，準備重做從庫**，不用再查下去

**【3】網路層驗證（在從庫上）**

```bash
nc -zv 10.0.1.11 3306
mysql -h 10.0.1.11 -u repl -p --ssl-mode=REQUIRED -e "SELECT 1;"
```

```text
Connection to 10.0.1.11 3306 port [tcp/mysql] succeeded!    # 通 → 問題在帳號或 TLS
nc: connect ... Connection refused                          # 主庫沒起來或 bind-address 錯
nc: connect ... Connection timed out                        # ★★★ 防火牆擋住（多半是主庫端 ufw）
```

**【4】applier 掛掉：先看它卡在哪一筆交易**

```bash
mysql -e "SELECT WORKER_ID, LAST_ERROR_NUMBER, LAST_ERROR_MESSAGE, APPLYING_TRANSACTION
          FROM performance_schema.replication_applier_status_by_worker
          WHERE LAST_ERROR_NUMBER <> 0\G"
```

```text
   LAST_ERROR_NUMBER: 1032
   LAST_ERROR_MESSAGE: Could not execute Update_rows event on table appdb.members;
                       Can't find record in 'members', Error_code: 1032
APPLYING_TRANSACTION: 3e11fa47-71ca-11e1-9e33-c80aa9429562:45261
```

**【5】★★★★ 用 `mysqlbinlog` 把那筆交易挖出來，再比對從庫實際資料**

```bash
mysqlbinlog --base64-output=DECODE-ROWS --verbose \
  --include-gtids='3e11fa47-71ca-11e1-9e33-c80aa9429562:45261' \
  /var/log/mysql/mysql-bin.000012 | sed -n '1,60p'
```

- 從庫那一列**不存在** → 資料缺漏，走 `pt-table-checksum` / `pt-table-sync`，不要跳過
- 從庫那一列**值不同** → 有人寫過從庫，先查稽核日誌找出是誰
- 從庫那一列**已經是套用後的樣子** → 這筆已生效，才可以注入空交易跳過

**【6】只是延遲：分清楚是「收得慢」還是「套用得慢」**

```bash
mysql -e "SHOW REPLICA STATUS\G" | grep -E 'Retrieved_Gtid_Set|Executed_Gtid_Set'
```

- Retrieved ≈ Executed，但兩者都遠落後主庫 → **收得慢**：網路頻寬、主庫 dump thread 被卡
- Retrieved 遠大於 Executed → **套用得慢**：走【7】

**【7】找出卡住 applier 的元凶**

```bash
mysql -e "SELECT ID,USER,TIME,STATE,LEFT(INFO,120) FROM information_schema.PROCESSLIST
          WHERE USER='system user' OR TIME > 60\G"
mysql -e "SELECT * FROM sys.innodb_lock_waits\G"
```

```text
   USER: system user
   TIME: 842
  STATE: Applying batch of row changes (delete)    # ★★★★ 典型的無主鍵大表症狀
```

看到 `Applying batch of row changes` 停在同一筆很久 → 跑本篇的「無主鍵表」查詢。
看到有長查詢（報表）擋著 → 那支查詢與 applier 搶同一張表的鎖，先 `KILL` 它。

---

## 安全性注意事項

> [!danger] ★★★★★ 絕對禁止的事
> - **把複寫當備份、因此停掉備份排程** —— 一句 `DROP TABLE` 就同時毀掉主從兩份資料。
> - **在 my.cnf 寫 `replica_skip_errors = 1062,1032`** —— 複寫從此不會斷，
>   資料會靜默分歧到你切換過去那天才爆炸，而那時已經沒有正確的版本可以比對。
> - **切換時沒有確認舊主庫不可寫** —— 雙寫造成的分歧無法自動合併，只能人工逐表判讀。
> - **`GRANT ALL ON *.* TO 'repl'@'%'`** —— 複寫帳號只需要 `REPLICATION SLAVE`；
>   給 `%` 等於任何連得到 3306 的人都能拉走**整個資料庫的完整變更歷史**（含個資）。
> - **複寫連線不加密** —— binlog 事件裡是身分證字號、地址、電話的明文前後映像，
>   在機關內網被側錄就是一次個資外洩事件（[[07-台灣資安法規與個資法]]）。

### 機關情境的四個要求

| 要求 | 做法 | 對應 |
| --- | --- | --- |
| **連線加密** ★★★★ | `repl` 帳號 `REQUIRE SSL`、`SOURCE_SSL=1` + `SOURCE_SSL_CA`；監控帳號用 `ssl-mode=VERIFY_CA` | [[07-MySQL-安全強化]] |
| **最小權限** ★★★★ | 複寫帳號只給 `REPLICATION SLAVE`；監控帳號只給 `REPLICATION CLIENT, PROCESS`；來源限內網網段 | [[02-MySQL-使用者與權限]] |
| **稽核軌跡** ★★★★ | 從庫的 `super_read_only` 每一次被關閉都要有紀錄；切換每一步寫進事件單 | [[09-事件處理與升級流程]] |
| **備份加密與異地** ★★★★ | 初始同步用的 dump／XtraBackup 產出是**完整資料庫**，用完要加密或安全刪除 | [[05-MySQL-備份與還原]] |

```bash
# ★★★★ 初始同步的中繼檔案是整份資料庫的明文複本，不要留在 /tmp
sudo shred -u /var/backups/db1-seed.sql
sudo rm -rf /var/lib/mysql.old          # 確認新從庫穩定運作數天後再刪
```

★★★ 誰關掉了從庫的唯讀？把它變成可稽核的事件：

```sql
-- 記錄目前狀態，納入每日健檢報表
SELECT @@hostname AS host, @@read_only, @@super_read_only, NOW() AS checked_at;
```

政府組態基準對資料庫連線加密、帳號最小權限與日誌保留都有對應要求，
導入前先讀 [[01-TWGCB概念與法規要求]] 與 [[02-TWGCB-Linux基準文件解讀]] 確認你的機關適用哪一份基準與版本，
★★★ **不要憑印象引用條號**。

---

## 速查表

### 日常指令

| 指令 | 用途 | 星級 |
| --- | --- | --- |
| `SHOW REPLICA STATUS\G` | 從庫全狀態，先看兩個 `Running` | ★★★★ |
| `SHOW REPLICAS` | 主庫上列出已連線的從庫 | ★★★ |
| `SHOW BINARY LOGS` | 列出 binlog 與大小（估算每日產量） | ★★★ |
| `START REPLICA` / `STOP REPLICA` | 啟停複寫（可加 `IO_THREAD` / `SQL_THREAD`） | ★★★★ |
| `RESET REPLICA ALL` | ★★★★ 清除複寫設定，**切換升主庫時必做** | ★★★★ |
| `SELECT GTID_SUBTRACT(a, b)` | ★★★★ 算真正的落後交易集合 | ★★★★ |
| `SELECT WAIT_FOR_EXECUTED_GTID_SET(s, n)` | 等待追平，回傳 0 = 成功 | ★★★★ |
| `mysqlbinlog --base64-output=DECODE-ROWS -v` | 看某筆交易到底改了什麼 | ★★★★ |
| `pt-table-checksum` / `pt-table-sync` | 主從一致性校驗與修復 | ★★★ |

### 關鍵設定項

| 設定項 | 主庫 | 從庫 | 星級 |
| --- | --- | --- | --- |
| `server_id` | `11` | `12`（★★★ 全叢集唯一） | ★★★★ |
| `gtid_mode` / `enforce_gtid_consistency` | `ON` / `ON` | `ON` / `ON` | ★★★★ |
| `binlog_format` | `ROW` | `ROW` | ★★★★ |
| `binlog_expire_logs_seconds` | `1209600` | `1209600` | ★★★★ |
| `sync_binlog` + `innodb_flush_log_at_trx_commit` | `1` + `1` | `1` + `1` | ★★★★ |
| `log_replica_updates` | `ON` | `ON`（★★★ 將來要能升主庫） | ★★★ |
| `read_only` / `super_read_only` | `OFF` / `OFF` | ★★★★ `ON` / `ON` | ★★★★ |
| `skip_replica_start` | — | `ON` | ★★★ |
| `relay_log_recovery` | — | `ON` | ★★★ |
| `replica_parallel_workers` | — | `4`~`8` | ★★★ |
| `binlog_transaction_dependency_tracking` | `WRITESET` | `WRITESET` | ★★★ |

### 判斷準則

| 看到 | 代表 | 該做什麼 | 星級 |
| --- | --- | --- | --- |
| `Replica_IO_Running: No` | 收不到資料 | 查 `Last_IO_Error`；1236 就準備重做從庫 | ★★★★ |
| `Replica_SQL_Running: No` | 套用不了 | 查 `Last_SQL_Error` + `mysqlbinlog` 看內容 | ★★★★ |
| `Seconds_Behind_Source: NULL` | applier 沒在跑 | 等同 `SQL_Running: No` | ★★★★ |
| `Seconds_Behind_Source: 0` 但 IO 是 No | ★★★★★ 假綠燈 | 立刻處理 IO thread | ★★★★★ |
| `GTID_SUBTRACT` 回傳空字串 | 已追平 | 可以進行切換 | ★★★★ |
| `Retrieved` ≫ `Executed` | relay log 積壓 | applier 追不上，查大交易與無主鍵表 | ★★★★ |
| `super_read_only: 0` 在從庫 | ★★★★ 隨時可能分歧 | 立刻設回 `ON` 並查誰關的 | ★★★★ |

### 檔案路徑（Ubuntu 24.04）

| 路徑 | 內容 | 星級 |
| --- | --- | --- |
| `/etc/mysql/mysql.conf.d/zz-replication.cnf` | 本篇的複寫設定片段 | ★★★★ |
| `/var/lib/mysql/auto.cnf` | ★★★★ `server_uuid`，clone VM 後必須刪掉 | ★★★★ |
| `/var/log/mysql/mysql-bin.*` | binlog | ★★★★ |
| `/var/log/mysql/db2-relay-bin.*` | 從庫的 relay log | ★★★ |
| `/var/log/mysql/error.log` | ★★★★ 複寫錯誤的完整訊息在這裡 | ★★★★ |
| `/usr/local/bin/mysql-repl-check.sh` | 本篇的監控腳本 | ★★★ |

---

## 練習題

> [!question]- 練習 1：證明「複寫不是備份」
> 在**測試環境**建好主從後，在主庫上執行 `DROP TABLE appdb.demo;`，
> 然後在 10 秒內到從庫確認該表是否還在。接著回答：如果這是正式環境，你有幾個復原選項？
>
> **參考解答**
> 從庫上的 `demo` 表**已經不見了** —— 複寫在毫秒級把 DDL 同步過去。
> ```bash
> mysql -h 10.0.1.12 -e "SHOW TABLES FROM appdb LIKE 'demo';"   # Empty set
> ```
> 正式環境的復原選項只有兩個，**兩個都與複寫無關**：
> **①** 從最近一次全備 + binlog 做 PITR，回到 `DROP` 前一秒（[[05-MySQL-備份與還原]]）。
> **②** 如果有**延遲從庫**且還在延遲窗內，立刻 `STOP REPLICA SQL_THREAD` 把表撈出來。
> ★★★★ 這題的重點是：**多一台從庫沒有讓你多一份可以回溯的資料。**

> [!question]- 練習 2：找出並修掉延遲的真正原因
> 在從庫上刻意建一張沒有主鍵的表、灌 50 萬列，然後在主庫對它做
> `UPDATE t SET c = c + 1;`。觀察 `Seconds_Behind_Source` 與心跳表延遲的變化，
> 找出根因並修掉，記錄修復前後的延遲數字。
>
> **參考解答**
> **① 觀察**：延遲會持續增長，`SHOW PROCESSLIST` 上 `system user` 停在
> `Applying batch of row changes (update)`，從庫單核 CPU 100%。
> **② 定位**：跑本篇「找出所有沒有主鍵的表」那段 SQL，該表會出現在清單裡。
> **③ 修復**：`ALTER TABLE t ADD COLUMN id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY FIRST;`
> **④ 驗證**：重跑同樣的 UPDATE，延遲應該從數十分鐘降到數秒。
> ★★★★ 延伸思考：這個 `ALTER` 本身也會複寫過去，在正式環境對大表執行要走
> [[03-風險與變更管理]] 的流程，並評估 `ALGORITHM=INPLACE, LOCK=NONE` 是否適用。

> [!question]- 練習 3：完整走一次切換與回滾
> 在測試環境依本篇【1】~【8】做一次計畫性切換，填完耗時表；
> 接著在【6】之前刻意中止，執行情境 A 的回滾，確認服務回到 db1 且複寫方向正確。
> 最後回答：如果在【6】之後才中止，為什麼不能用同一套回滾？
>
> **參考解答**
> 回滾後的驗證重點：db1 `super_read_only=0`、db2 `super_read_only=1`、
> db2 的 `SHOW REPLICA STATUS` 顯示 `Source_Host: 10.0.1.11` 且兩個 `Running` 都是 `Yes`、
> 應用 `.env` 的 `DB_HOST` 仍是 `10.0.1.11`。
> **【6】之後不能用同一套回滾的原因**：應用已經往 db2 寫入，
> db2 上產生了 db1 沒有的 GTID。此時把應用指回 db1 =
> ★★★★★ **那些新交易全部消失，而且 db1 之後的寫入會與 db2 的分岔**。
> 正確做法是「繼續用 db2，讓 db1 當從庫追平」，之後再排一次完整的切換切回去。

---

## 小測驗

Q1. 是非題：「有了主從複寫，每天的 mysqldump 備份可以改成每週一次。」

Q2. 從庫的 `SHOW REPLICA STATUS` 顯示 `Seconds_Behind_Source: 0`。這代表主從已同步嗎？請說明至少兩種它會騙人的情境。

Q3. 從庫只設了 `read_only=ON`。你用 `root` 登入從庫執行 `UPDATE appdb.settings SET v='x' WHERE id=1;`，會發生什麼事？後果是什麼？

Q4. 選擇題：新建一套 MySQL 8.0 主從，`binlog_format` 應該選？(A) STATEMENT (B) MIXED (C) ROW (D) 都可以

Q5. 這行指令會發生什麼事：`mysql -e "SET GLOBAL super_read_only=OFF;"` 在一台正在複寫的從庫上執行。

Q6. 從庫離線了一個連假（96 小時），開機後 `Last_IO_Error` 出現 `1236 ... has purged binary logs`。根因是什麼？有沒有辦法只補差額而不重做整台？

Q7. 簡答：計畫性切換時，為什麼「等從庫 GTID 追平」不能用 `Seconds_Behind_Source: 0` 來判斷？應該用什麼？

Q8. 複寫因為 `1062 Duplicate entry` 停住。網路上的答案是注入空交易跳過。你應該先做什麼？

Q9. 團隊回報「開了 `replica_parallel_workers=8` 但從庫延遲完全沒改善」。最可能漏了什麼？

Q10. 應用導入讀寫分離後，使用者反映「儲存後跳轉的詳細頁顯示查無資料，重整就有了」。原因是什麼？`'sticky' => true` 能不能解決所有這類情況？

> [!question]- 測驗答案
> **Q1. 錯，而且是本篇最重要的一題。** ★★★★
> 複寫與備份防的是完全不同的威脅。複寫防「硬體故障與單點」，
> 備份防「誤操作、勒索加密、應用邏輯 bug」。
> `DROP TABLE` 會在 0.1 秒內忠實同步到每一台從庫 —— 你有兩台機器，但你有零份資料。
> 導入複寫**不能減少任何一次備份**，備份頻率的依據是 RPO，與有幾台從庫無關。
> 相反地，複寫還多給了你一個好處：可以把 `mysqldump` 移到從庫上跑，
> 不再影響主庫效能 —— 這是「多做備份」的理由，不是少做的理由。
> 參見本篇「先把這件事講死：複寫不是備份」與 [[05-MySQL-備份與還原]]。
>
> **Q2. 不代表。** ★★★★★
> 這個數字的定義是「從庫本地時鐘 − applier 正在執行的事件在主庫上的時間戳」。
> 四種騙人情境：
> **①** ★★★★★ **IO thread 斷了、relay log 已跑完** → 顯示 `0`，但實際可能落後數天。
> 這是最危險的假綠燈，只監控延遲秒數的告警會一片綠燈。
> **②** 主庫閒置（半夜沒交易）→ 沒有新事件可比，`0` 沒有意義。
> **③** 兩台 NTP 沒對時 → 誤差直接反映成延遲數字。
> **④** `NULL` 代表 SQL thread 根本沒在跑，比大數字更嚴重。
> 正解是同時看 `Replica_IO_Running`、`Replica_SQL_Running`、GTID 落差、心跳表。
> 參見「`Seconds_Behind_Source` 為什麼會騙你」。
>
> **Q3. 會成功寫進去。** ★★★★
> `read_only=ON` **不擋** 具有 `SUPER` 或 `CONNECTION_ADMIN` 權限的帳號，而 `root` 正好有。
> 後果是這台從庫的資料與主庫**永久不同**，而且沒有任何告警。
> 之後主庫若對同一列做 `UPDATE`，ROW 模式的前映像對不上 →
> `1032 Can't find record` 讓複寫停住；或是永遠不報錯，你在報表上看到錯的數字，
> 更糟的是切換過去之後整個系統用的是錯資料。
> 唯一正解是**同時設 `super_read_only=ON`**，它連 `SUPER` 帳號一起擋。
> 參見「只設 `read_only` 而沒設 `super_read_only`」。
>
> **Q4. (C) ROW。** ★★★★
> `STATEMENT` 記錄原始 SQL 文字，遇到 `NOW()`、`UUID()`、`RAND()`、
> 沒有 `ORDER BY` 的 `LIMIT`、觸發器時，**主從會算出不同結果而且完全不報錯** ——
> 你要幾個月後對帳才會發現。
> `MIXED` 的切換規則是黑盒子，出事後難以重建現場。
> `ROW` 記錄「第幾列、哪些欄位從 A 變成 B」，主從逐列一致。
> 代價是 binlog 較大（一句影響 50 萬列的 UPDATE 會產生 50 萬列的前後映像），
> 這也是本篇建議「拆大交易」與「留意 binlog 磁碟」的原因。
> 另外 `pt-table-checksum` 與 WRITESET 並行 applier 都需要 ROW。
> 參見「為什麼 `binlog_format` 一定要 ROW」。
>
> **Q5. 從庫從此可以被任何有權限的帳號寫入。** ★★★★
> 指令本身會成功、沒有任何警告，`SHOW REPLICA STATUS` 也一切正常。
> 這是一顆定時炸彈：只要有人（或某支忘了改連線設定的批次程式）寫進來，
> 主從就永久分歧。
> 合法用途只有一種：在從庫上做維護（例如加索引）時暫時開啟，
> ★★★★ **做完立刻設回 `ON`**，並把這一開一關記進事件單（[[09-事件處理與升級流程]]）。
> 監控腳本應該把 `super_read_only != 1` 列為**嚴重**等級告警。
>
> **Q6. 根因是 `binlog_expire_logs_seconds` 設得比「從庫可能離線的最長時間」短。** ★★★★
> 從庫需要的 GTID 對應的 binlog 已經被主庫清掉，**沒有辦法只補差額** ——
> 那些交易的內容已經不存在於任何地方了。
> 唯一解法是**重做整台從庫**：重新 `mysqldump --set-gtid-purged=ON` 或 XtraBackup，
> `RESET BINARY LOGS AND GTIDS` 後匯入，再 `START REPLICA`。
> 資料量大的話這是好幾個小時的工作。
> 預防：保留時間 > 連假天數 + 重建所需時間 + 緩衝，本篇建議 14 天（`1209600`）。
> 磁碟不夠時**不要縮短保留**，改成把 binlog 掛獨立磁碟或複製到備份儲存。
> 參見「`binlog_expire_logs_seconds` 設太短」。
>
> **Q7. 因為 `Seconds_Behind_Source` 在 IO thread 斷掉時會顯示 `0`，而且它的精度只到秒。** ★★★★
> 切換時你需要的是「主庫上每一筆已提交的交易，從庫都執行過了」這個**集合層級**的保證。
> 正確做法：
> ```sql
> -- 主庫（已封寫）
> SELECT @@GLOBAL.gtid_executed;
> -- 從庫：必須回傳空字串
> SELECT GTID_SUBTRACT('<主庫的值>', @@GLOBAL.gtid_executed);
> -- 或用等待函式，回傳 0 代表追平、1 代表逾時
> SELECT WAIT_FOR_EXECUTED_GTID_SET('<主庫的值>', 300);
> ```
> ★★★★ 逾時就**中止切換並回滾**，不要「差一點點應該沒關係」。
> 參見「計畫性切換」的步驟【3】。
>
> **Q8. 先查為什麼會分歧，不要反射性跳過。** ★★★★
> 複寫停下來是保護機制，它在告訴你「主從已經不一致」。步驟：
> **①** `SELECT ... FROM performance_schema.replication_applier_status_by_worker` 找出卡住的 GTID。
> **②** 到主庫用 `mysqlbinlog --base64-output=DECODE-ROWS -v --include-gtids=...` 看那筆交易的內容。
> **③** 到從庫 `SELECT` 那一列，比對實際狀態。
> 只有在「從庫那一列已經是套用後的樣子」（代表這筆已生效）時，跳過才是安全的。
> 若是「從庫被人寫過」或「初始同步的 `gtid_purged` 設錯」，跳過只會讓分歧擴大。
> ★★★★★ 而且無論如何**不要在 my.cnf 寫 `replica_skip_errors`** ——
> 那等於永久關掉保護，資料會靜默地愈差愈遠。
> 跳過後必須跑 `pt-table-checksum` 確認影響範圍並寫進事件單。
>
> **Q9. 最可能漏了主庫端的 `binlog_transaction_dependency_tracking = WRITESET`。** ★★★
> 並行度不是從庫自己算出來的 —— 是**主庫在寫 binlog 時**分析每筆交易改了哪些列，
> 把沒有衝突的交易標成同一個可並行群組，從庫的 worker 只是照著這個標記分工。
> MySQL 8.0 的預設是 `COMMIT_ORDER`（幾乎沒有並行空間），
> 只在從庫開 worker 數量效果非常有限。
> ```sql
> -- 主庫
> SET GLOBAL binlog_transaction_dependency_tracking = WRITESET;
> ```
> ★★ 另外要確認 `binlog_format=ROW`（WRITESET 的前提），
> 並用 `performance_schema.replication_applier_status_by_worker` 確認 worker 真的都在 `ON`。
> 如果改完仍然沒改善，元凶多半是**無主鍵表**或**單筆大交易**（並行救不了單一巨大交易）。
>
> **Q10. 這是複寫延遲造成的「寫後讀」問題。`sticky` 不能解決所有情況。** ★★★★
> 寫入落在主庫、後續的讀取被導到還沒收到那筆資料的從庫，於是查無資料；
> 幾百毫秒後從庫追上，重整就看得到。
> `'sticky' => true` 只在**同一個 request 內**有效：一旦該 request 有過寫入，
> 之後的讀取自動改走主庫。它救不到三種情境：
> **①** 前端寫入後另外發 AJAX 去讀（兩個獨立 request）。
> **②** ★★★★ 佇列 job —— worker 是另一個行程，要用 `'after_commit' => true`
> 或 job 的 `public $afterCommit = true;`，必要時再 `->delay(now()->addSeconds(5))`。
> **③** 排程任務與第三方回呼。
> 給開發團隊的原則一句話：**「凡是需要看到自己剛寫的資料，就走主庫。」**
> 參見「應用端讀寫分離」與 [[04-Laravel-Eloquent與資料庫]]。

---

## 延伸閱讀

- [[05-MySQL-備份與還原]] — ★★★★ 本篇一直在說「那個要看這篇」的那篇。備份策略、PITR 與**還原演練**
- [[02-MySQL-使用者與權限]] — `repl` 與 `replcheck` 帳號的建立、來源限制與權限盤點
- [[04-MySQL-設定檔與調校]] — `my.cnf` 載入順序、buffer pool 與記憶體預算（從庫規格不要低於主庫）
- [[07-MySQL-安全強化]] — `bind-address`、TLS 憑證產製、稽核日誌；本篇的 `REQUIRE SSL` 前置作業
- [[07-PostgreSQL-複寫與高可用]] — 對照組：PostgreSQL 的 WAL 流複寫與本篇的差異
- [[03-系統監控與告警]] / [[04-健康檢查與可用性監控]] — 把本篇的四個指標接進既有監控
- [[08-變更管理流程]] / [[09-事件處理與升級流程]] — 切換演練的公告、紀錄與事後檢討
- [[04-備份災難復原與入侵應變]] — 勒索與入侵情境下，為什麼從庫幫不上忙
- MySQL 8.0 Replication：<https://dev.mysql.com/doc/refman/8.0/en/replication.html>
- SHOW REPLICA STATUS 欄位說明：<https://dev.mysql.com/doc/refman/8.0/en/show-replica-status.html>
- MySQL Terminology Updates（8.0.22 起的改名對照）：<https://dev.mysql.com/blog-archive/mysql-terminology-updates/>
- Percona Toolkit（pt-table-checksum / pt-heartbeat）：<https://docs.percona.com/percona-toolkit/>
