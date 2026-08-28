---
title: "PostgreSQL 備份與還原"
desc: "pg_dump/pg_restore 旗標拆解、WAL 歸檔與 PITR 時間點還原、可交稽核的還原演練腳本"
aliases: [pg_dump, pg_restore, pg_dumpall, pg_basebackup, WAL, PITR, recovery.signal, pg_verifybackup, 還原演練]
tags: [群組/軟體與開發工具, 服務/postgresql, 主題/備份, 主題/還原, 主題/LXMP]
category: 資料庫與資料儲存
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[03-psql-操作與常用指令]]", "[[04-PostgreSQL-設定檔與pg_hba]]", "[[03-備份策略與還原演練]]"]
updated: 2026-08-28
---

# PostgreSQL 備份與還原

> [!abstract] 這篇你會學到
> - **★★★★★ 完成一次可交稽核的還原演練** —— 在獨立叢集上還原、比對列數、量到真實 RTO、產出演練紀錄。**沒有演練過的備份不算備份**，這是全篇唯一的主張
> - **★★★★ 用 WAL 歸檔做 PITR（時間點還原）**：`recovery.signal` + `restore_command` + `recovery_target_time`，把資料庫倒回誤操作的前 30 秒
> - **★★★★ 認清 PostgreSQL 與 MySQL 最大的差別**：WAL 是**實體**日誌，你**沒辦法**像 `mysqlbinlog` 那樣從裡面讀出「那一列原本的值」，所以救資料**只有** PITR 到旁邊一套叢集這一條路
> - 用 `pg_dump -Fc` / `pg_dumpall -g` / `pg_basebackup` 三件事各司其職，知道**哪一個漏掉會讓還原直接失敗**
> - 寫出可排程的 `pg-backup.sh`（加密 + 異地 + 輪替 + flock + **失敗告警**）與 `pg-pitr-drill.sh`
> - **★★★★ 知道 `archive_command` 失敗時，PostgreSQL 不會停止服務，而是讓 `pg_wal` 一路長到把磁碟塞爆然後 PANIC**

## 前置知識

- [[03-psql-操作與常用指令]] —— 本篇大量使用 `psql -c` / `\l` / `\dt+`，不重複教
- [[04-PostgreSQL-設定檔與pg_hba]] —— `archive_mode` 要寫進 `postgresql.conf`、備份帳號要在 `pg_hba.conf` 開 `replication` 這條，設定檔位置與 reload/restart 的差別看那篇
- [[02-PostgreSQL-角色與權限]] —— 本篇沿用該篇的角色觀念，`pg_read_all_data` 這類預設角色在那裡講
- [[03-SQL基礎操作]] —— 比對步驟用到的 `COUNT(*)`、`LEFT JOIN`、`UPDATE ... FROM` 語法在那篇，**本篇不重講 SQL**
- [[03-備份策略與還原演練]] —— 3-2-1 原則、RPO / RTO 的一般定義、restic / borg、不可變備份的通論**全部在那篇**。本篇只講「PostgreSQL 這套資料庫怎麼做」
- [[05-MySQL-備份與還原]] —— 同一件事在 MySQL 怎麼做。**兩篇建議對照著看**，本篇會不斷點出差異

---

## 觀念說明

### 三條防線，跟 MySQL 一樣但零件不同 ★★★★

```text
   每日 02:00 ──▶ ① 邏輯備份 pg_dump -Fc + pg_dumpall -g   RPO ≤ 24h，可單表救援
   每週日     ──▶ ② 實體備份 pg_basebackup                  RTO 最短，PITR 的起點
   持續       ──▶ ③ ★★★★ WAL 歸檔（archive_command）        RPO ≤ 5 分，PITR 的命脈

   ✗ standby 不是備份 —— 誤 UPDATE 會在毫秒內同步過去。
     串流複寫解決「主機掛掉」，不解決「人做錯事」。建置見 [[07-PostgreSQL-複寫與高可用]]。
   ✗ 只有 ① 沒有 ②③ ＝ 你只能回到昨天凌晨，今天一整天的案件全沒了。
   ✗ 有 ③ 但 WAL 歸檔目錄跟 $PGDATA 同一顆碟 ＝ 那顆碟壞掉時 WAL 陪葬，PITR 是空話。
```

### ★★★★ 跟 MySQL 的對照表：零件對得上，但有一格對不上

| 你在 MySQL 熟悉的 | PostgreSQL 的對應物 | ★★★★ 關鍵差異 |
| --- | --- | --- |
| `mysqldump` | `pg_dump` | ★★★ pg_dump **只做一個 database**，不含角色、不含表空間 |
| `mysqldump --all-databases` | `pg_dumpall` | ★★★ 只有純文字格式，**不能平行還原**，實務上只拿來抓 `-g` |
| （帳號在 `mysql` 系統庫裡） | `pg_dumpall --globals-only` | ★★★★ **漏掉這個，還原時整片 `role "app" does not exist`** |
| XtraBackup | `pg_basebackup` | ★★ 內建，不必另外裝，版本也不會對不上 |
| binlog | **WAL** | ★★★★★ **binlog 是邏輯的、WAL 是實體的** |
| `mysqlbinlog -vv` 讀出被刪那列的欄位值 | **做不到** | ★★★★★ 見下一段，這是本篇最重要的觀念 |
| `--source-data=2` 記下 binlog 座標 | `backup_label`（自動產生） | ★★ pg_basebackup 自動寫，不必你下旗標 |
| `binlog_expire_logs_seconds` | 歸檔目錄的輪替策略 | ★★★ PostgreSQL **不會自動清歸檔**，你不清就會塞爆 |
| `CHECKSUM TABLE` | `pg_verifybackup` + 自己算 `md5(...)` 聚合 | ★★ 語意不同，別直接套用 |

### ★★★★★ 為什麼 PostgreSQL 救資料一定要「還原一整套」

這是 PostgreSQL 維運人員最常誤解的一點，也是從 MySQL 過來的人最容易踩的坑。

```text
   MySQL binlog（ROW 格式）             PostgreSQL WAL
   ─────────────────────────           ────────────────────────────────
   ### DELETE FROM `casedb`.`case`     rmgr: Heap   len: 54
   ### WHERE                            tx: 88412  lsn: 3/8A0C41F8
   ###   @1=100231                      desc: HOT_UPDATE off 27 xmax 88412
   ###   @2='114-A-0231'                     ; new off 91 xmax 0
   ###   @3='張OO'                      blkref #0: rel 1663/16385/16421 blk 5138
   ↑ ★★★★★ 欄位值就在裡面，撈得出來    ↑ ★★★★★ 只有「第 5138 個 block 的第 27 格
                                          改成第 91 格」，沒有任何欄位值
```

**具體後果**：承辦誤下了一句沒有 `WHERE` 的 `UPDATE`，在 MySQL 你可以直接
`mysqlbinlog --base64-output=DECODE-ROWS -vv` 把舊值印出來、寫成 UPDATE 補回去。
**在 PostgreSQL 這條路完全不存在。** 你唯一的辦法是：

```text
   ① 拿基礎備份 → ② 重放 WAL 到「誤操作的前一秒」→ ③ 得到一整套當時的資料庫
   → ④ 用 SQL 從那套資料庫把正確的值 JOIN 回正式庫
```

所以 **PostgreSQL 的 PITR 不是「進階選項」，是「救資料的唯一入口」**。
沒有 WAL 歸檔的 PostgreSQL，等於沒有救援能力。

> [!warning] `pg_waldump` 不是救星 ★★★
> 有 `pg_waldump` 這支工具可以把 WAL 解出來看，但它輸出的是上面右邊那種**實體位址**。
> 它拿來排查「複寫卡在哪」很有用，拿來**還原資料則完全無效** —— 別在事故現場浪費時間。

### ★★★★★ 為什麼不能直接 `cp -a $PGDATA`

```text
   shared_buffers（記憶體）                 磁碟 $PGDATA
   page 1663/16385/16421 blk5138  ── ✗ ──▶ base/16385/16421   [10:00:00 的舊狀態]
   已寫入但尚未 fsync 的 WAL       ── ✗ ──▶ pg_wal/0000...A3   [10:00:04]
   CLOG（交易狀態）                ── ✗ ──▶ pg_xact/0000       [10:00:07]

   ★★★★★ 三份東西的時間點互相矛盾 → 啟動時：
      PANIC:  could not locate a valid checkpoint record
      FATAL:  the database system is starting up   （然後永遠起不來）
```

**什麼情況下複製資料目錄才算有效備份**（滿足其一）：

| 做法 | 為什麼有效 | 代價 | 星級 |
| --- | --- | --- | --- |
| **停機後**複製（stop → 等 log 出現 `database system is shut down` → cp） | 乾淨關機會做完 shutdown checkpoint | 服務中斷 | ★★ |
| **`pg_basebackup`** | 內部會 `pg_backup_start` 取一致點、並同步串流 WAL | 幾乎沒有 | ★★★★ **首選** |
| **`pg_backup_start()` / `pg_backup_stop()` 包住的檔案系統快照** | 有 `backup_label` 標出從哪個 checkpoint 開始重放 | 要正確處理回傳值 | ★★★ |

> [!danger] ★★★★★ 最危險的是「它看起來成功了」
> `rsync -a /var/lib/postgresql/16/main /backup/` 會**正常結束、exit code 0、容量也對**。
> 你會以為有備份。要到真正需要還原的那一天，才發現
> `PANIC: could not locate a valid checkpoint record`，而那時正式庫已經沒了。
> **這種備份的價值是零，但它會讓你以為價值是一百。**

### 三種備份方式的選型 ★★★★

| 面向 | **`pg_dump -Fc`**（邏輯） | **`pg_dump -Fd -j`**（邏輯・平行） | **`pg_basebackup`**（實體） | **WAL 歸檔** |
| --- | --- | --- | --- | --- |
| 產出 | 單一 `.dump` 檔 | 一個目錄，每表一檔 | 整個叢集的檔案 | 16 MB 一段的 WAL |
| 備份耗時（50 GB） | ★★★ 40～80 分 | ★★ 12～25 分 | ★ 8～15 分 | 幾乎不佔時間 |
| **★★★★ 還原 RTO**（50 GB） | ★★★★ **3～6 小時**（重建索引） | ★★ **40～90 分**（`-j` 平行建索引） | ★ **15～30 分** | 視重放量 |
| 只還原一張表 | ★★★ **可以**（`-L` 挑 TOC） | ★★★ 可以 | ✗ 不行 | ✗ 不行 |
| 跨大版本升級 | ★★★ **可以**（16 → 17） | ★★★ 可以 | ✗ **版本必須完全一致** | ✗ |
| 涵蓋範圍 | 單一 database | 單一 database | ★★★★ **整個叢集**（含角色） | 整個叢集 |
| 能做 PITR | ✗ | ✗ | ★★★★ **可以（要配 WAL）** | 本體 |
| 佔用空間 | 小（約 1/8） | 小 | ★★ 大（≈ 原尺寸） | 小但持續累積 |

> [!tip] 一句話選型 ★★★★
> **機關業務系統（≤ 50 GB）：`pg_dump -Fc` 每日 + `pg_dumpall -g` 每日 +
> `pg_basebackup` 每週 + WAL 歸檔持續。四樣全做，因為它們解決的是四種不同的事故。**
> 少了 `pg_dumpall -g` 你還原時會卡在角色不存在；
> 少了 WAL 歸檔你救不回今天的資料；
> 少了 `pg_dump` 你沒辦法只救一張表。

---

## 環境準備與安裝

### 【0】先確認版本與路徑，不要憑印象 ★★★★

Ubuntu／Debian 用 PGDG 套件時，**設定檔不在資料目錄裡**，這跟 RHEL 系相反，
也是 PostgreSQL 備份最常漏掉的一塊。

```bash
psql --version
pg_lsclusters
```

預期輸出：

```text
psql (PostgreSQL) 16.9 (Ubuntu 16.9-1.pgdg24.04+1)
Ver Cluster Port Status Owner    Data directory               Log file
16  main    5432 online postgres /var/lib/postgresql/16/main  /var/log/postgresql/postgresql-16-main.log
```

★★★★ 記住這兩個路徑，備份腳本兩個都要備：

| 路徑 | 內容 | 漏掉的後果 | 星級 |
| --- | --- | --- | --- |
| `/var/lib/postgresql/16/main` | 資料本體（`$PGDATA`） | 沒資料 | ★★★★★ |
| `/etc/postgresql/16/main/` | `postgresql.conf`、**`pg_hba.conf`** | ★★★★ **還原後沒人連得進來**，要重寫一次認證規則 | ★★★★ |

> [!warning] ★★★★ `pg_basebackup` 在 Ubuntu 上抓不到你的設定檔
> `pg_basebackup` 複製的是伺服器回報的 `$PGDATA`。Ubuntu 把 `postgresql.conf` 與
> `pg_hba.conf` 放在 `/etc/postgresql/`（`$PGDATA` 裡只有指向它的符號連結設定），
> **所以基礎備份裡沒有你的設定檔**。災難重建時你會拿到一套可以啟動、但
> `pg_hba.conf` 是套件預設值的資料庫 —— 應用連不進來，而你正在災難現場。
> **`/etc/postgresql/` 一定要另外用 `tar` 備一份**，本篇的腳本就是這樣做的。

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> sudo dnf -qy module disable postgresql          # ★★★ 先關掉 OS 內建模組，否則裝到舊版
> sudo dnf install -y postgresql16-server postgresql16-contrib
> sudo /usr/pgsql-16/bin/postgresql-16-setup initdb
> sudo systemctl enable --now postgresql-16
> ```
>
> 差異一覽：
>
> | 項目 | Ubuntu / Debian | Rocky / AlmaLinux |
> | --- | --- | --- |
> | `$PGDATA` | `/var/lib/postgresql/16/main` | `/var/lib/pgsql/16/data` |
> | `postgresql.conf` | `/etc/postgresql/16/main/` ★★★★ **分開放** | ★★ **就在 `$PGDATA` 裡** |
> | 服務名 | `postgresql@16-main` | `postgresql-16` |
> | 執行檔 | `/usr/lib/postgresql/16/bin`（有 `pg_wrapper`） | `/usr/pgsql-16/bin`（★★ **要自己加 PATH**） |
> | 多叢集工具 | `pg_lsclusters` / `pg_ctlcluster` | ★★ **沒有這些包裝，直接用 `pg_ctl`** |
> | 重啟 | `sudo pg_ctlcluster 16 main restart` | `sudo systemctl restart postgresql-16` |
>
> ★★★★ RHEL 系因為設定檔就在 `$PGDATA` 裡，`pg_basebackup` **會**一併備份到，
> 上面那個 Ubuntu 的坑在 RHEL 不存在 —— 但反過來說，**還原時你會把來源機的
> `pg_hba.conf` 一起蓋過去**，記得檢查裡面有沒有寫死的舊 IP 網段。

### 【1】備份角色要哪些權限，為什麼

角色觀念看 [[02-PostgreSQL-角色與權限]]，這裡只列「備份這件事真正需要什麼」。

```sql
-- ★★★ 兩種備份需要的權限不同，一次給齊
CREATE ROLE backup LOGIN REPLICATION PASSWORD 'ChangeMe';
GRANT pg_read_all_data TO backup;                       -- ★★★ PG14 起的預設角色
GRANT EXECUTE ON FUNCTION pg_backup_start(text, boolean) TO backup;
GRANT EXECUTE ON FUNCTION pg_backup_stop(boolean) TO backup;
```

| 權限 | 給誰用 | 為什麼需要 | 星級 |
| --- | --- | --- | --- |
| `pg_read_all_data` | `pg_dump` | 一次拿到所有 schema 的 `SELECT` 與 `USAGE`，不必逐表 GRANT | ★★★ |
| `REPLICATION` 屬性 | `pg_basebackup` / `pg_receivewal` | ★★★★ **沒有這個直接連不上**，`pg_basebackup` 走的是 replication 協定 | ★★★★ |
| `EXECUTE ON pg_backup_start/stop` | 檔案系統快照法 | 不用快照法就不需要 | ★★ |
| `pg_hba.conf` 的 `replication` 條目 | `pg_basebackup` | ★★★★ **`all` 不包含 `replication`**，要單獨寫一行 | ★★★★ |

★★★★ 最後那條是純新手殺手。`pg_hba.conf` 裡 `DATABASE` 欄位寫 `all` 時
**不涵蓋 replication 連線**，必須另外寫：

```text
# TYPE  DATABASE      USER     ADDRESS        METHOD
local   replication   backup                  peer
host    replication   backup   127.0.0.1/32   scram-sha-256
```

改完 reload（不是 restart）：

```bash
sudo -u postgres psql -c "SELECT pg_reload_conf();"
```

預期輸出：

```text
 pg_reload_conf
----------------
 t                          # ★★ t 只代表訊號送出去了，不代表設定合法
(1 row)
```

★★★ 一定要接著看實際生效的規則，`pg_reload_conf()` 回 `t` **不保證檔案沒寫錯**：

```bash
sudo -u postgres psql -c \
  "SELECT line_number, type, database, user_name, address, auth_method
   FROM pg_hba_file_rules WHERE error IS NOT NULL OR 'replication' = ANY(database);"
```

預期輸出：

```text
 line_number | type  |    database    | user_name |   address   |  auth_method
-------------+-------+----------------+-----------+-------------+----------------
          92 | local | {replication}  | {backup}  |             | peer
          93 | host  | {replication}  | {backup}  | 127.0.0.1   | scram-sha-256
(2 rows)                                                # ★★★★ error 欄有東西就是寫錯了
```

### 【2】★★★★★ 憑證：絕對不要把密碼寫在指令列或環境變數

```bash
# ★★★★★ 絕對不要這樣做
PGPASSWORD='S3cret' pg_dump -h db01 -U backup casedb > casedb.sql
```

備份跑的那 40 分鐘裡，同機任何帳號執行 `cat /proc/<pid>/environ` 就拿得到密碼；
寫在指令列的話連 `ps auxww` 都看得到。**這是內部人取得資料庫憑證最省力的一條路。**

**正解：`~/.pgpass`**

```bash
sudo -u postgres bash -c 'umask 077; cat > ~/.pgpass' <<'EOF'
# hostname:port:database:username:password
localhost:5432:*:backup:ChangeMe
localhost:5432:replication:backup:ChangeMe
EOF
sudo -u postgres ls -l ~/.pgpass
```

預期輸出：

```text
-rw------- 1 postgres postgres 118 Aug 28 09:14 /var/lib/postgresql/.pgpass
```

★★★★ 權限**必須**是 `0600`，多一個 bit PostgreSQL 就直接無視這個檔案並警告：

```text
WARNING: password file "/var/lib/postgresql/.pgpass" has group or world access; permissions
         should be u=rw (0600) or less
```

★★★ 注意第二行：**`replication` 連線的 database 欄位就是字面上的 `replication`**，
`*` 通配符**不涵蓋**它 —— 這跟 `pg_hba.conf` 是同一個規則，也是同一個坑。

> [!tip] 更好的做法：本機一律走 peer ★★★
> 備份腳本用 `sudo -u postgres` 執行、走 unix socket、`pg_hba.conf` 設 `peer`，
> 就**完全不需要密碼檔**。本篇的 `pg-backup.sh` 採這個做法，`.pgpass` 只留給
> 「備份主機在另一台」的情境。

### 【3】★★★★ 開啟 WAL 歸檔：PITR 的命脈

先看現況：

```bash
sudo -u postgres psql -c \
  "SELECT name, setting, context FROM pg_settings
   WHERE name IN ('wal_level','archive_mode','archive_command','archive_timeout','summarize_wal');"
```

預期輸出（全新安裝的 PostgreSQL 16）：

```text
      name       | setting  |  context
-----------------+----------+------------
 archive_command |(disabled)| sighup      # ★★ sighup ＝ 改完 reload 就生效
 archive_mode    | off      | postmaster  # ★★★★ postmaster ＝ 改完必須 restart
 archive_timeout | 0        | sighup
 wal_level       | replica  | postmaster  # ★★★ 預設就是 replica，歸檔夠用
(4 rows)
```

★★★★★ **`context` 這一欄是你判斷「reload 還是 restart」的唯一權威**，
不要背、不要猜、不要相信網路文章 —— 每次改參數前先查這張表。
`summarize_wal` 在 PostgreSQL 16 查不到是正常的，那是 17 才有的參數。

寫入設定：

```bash
sudo install -d -o postgres -g postgres -m 0700 /srv/pgwal/archive
sudo -u postgres tee -a /etc/postgresql/16/main/conf.d/50-archive.conf <<'EOF'
# ★★★★ 改完必須 restart（context = postmaster）
wal_level = replica
archive_mode = on

# ★★★★★ 三個要件：不覆蓋既有檔、失敗回非零、成功回零
archive_command = '/usr/local/bin/pg-archive-wal.sh %p %f'

# ★★★ 沒有寫入時也強制每 5 分鐘切一段 → RPO 上限被鎖在 5 分鐘
archive_timeout = '5min'
EOF
```

★★★★ **不要**直接把 `test ! -f ... && cp ...` 寫進 `archive_command`。
官方文件那行是給你理解語意用的最小示範，正式環境要用腳本，理由是 `cp` **不會 fsync** ——
歸檔目錄所在的機器一斷電，你剛「成功歸檔」的那幾段 WAL 是空的。

```bash
sudo tee /usr/local/bin/pg-archive-wal.sh <<'EOF'
#!/bin/bash
# 歸檔單一 WAL segment。$1 = %p（相對路徑）  $2 = %f（檔名）
set -euo pipefail
DEST=/srv/pgwal/archive

# ★★★★ 已存在就是異常：可能是上一輪 timeline 的殘留，寧可失敗也不要覆蓋
if [[ -f "$DEST/$2" ]]; then
  logger -t pg-archive "REFUSE overwrite $2"
  exit 1
fi

install -m 0600 "$1" "$DEST/$2.tmp"      # ★★★ 先寫暫存名，避免半個檔被當成完整檔
sync -f "$DEST/$2.tmp"                   # ★★★★ 真的落地，斷電才不會拿到空檔
mv -n "$DEST/$2.tmp" "$DEST/$2"
EOF
sudo chmod 0755 /usr/local/bin/pg-archive-wal.sh
sudo pg_ctlcluster 16 main restart
```

驗證歸檔真的在動 —— **這一步不做就等於沒設**：

```bash
sudo -u postgres psql -c "SELECT pg_switch_wal();" >/dev/null
sudo -u postgres psql -x -c "SELECT * FROM pg_stat_archiver;"
```

預期輸出：

```text
-[ RECORD 1 ]------+------------------------------
archived_count     | 3
last_archived_wal  | 000000010000000000000004
last_archived_time | 2026-08-28 09:31:07.442+08     # ★★★★ 時間要是「剛剛」
failed_count       | 0                              # ★★★★★ 這裡不是 0 就是壞的
last_failed_wal    |
last_failed_time   |
stats_reset        | 2026-08-28 09:20:01.117+08
```

> [!danger] ★★★★★ `failed_count` 持續增加＝倒數計時開始
> `archive_command` 一直失敗時，PostgreSQL **不會停止服務、不會拒絕寫入**，
> 它只是**把歸檔不掉的 WAL 全部留在 `pg_wal/` 裡**，每 16 MB 一段一直堆。
> 一台寫入量中等的機關系統一天堆掉 20～60 GB 很常見。
> 終點是磁碟寫滿，然後：
> ```text
> PANIC:  could not write to file "pg_wal/xlogtemp.31544": No space left on device
> LOG:  server process (PID 31544) was terminated by signal 6: Aborted
> ```
> **整個資料庫當場停止服務，而且磁碟滿了連啟動都啟不起來。**
> `pg_stat_archiver.failed_count` 與 `pg_wal` 目錄大小**必須進監控告警**，
> 做法見 [[03-系統監控與告警]]。

### 【4】備份目錄佈局 ★★★

```bash
sudo install -d -o postgres -g postgres -m 0700 \
  /var/backups/postgresql/{dump,globals,base,conf,logs,manifest}
sudo find /var/backups/postgresql -maxdepth 1 -printf '%M %u:%g %p\n'
```

預期輸出：

```text
drwx------ postgres:postgres /var/backups/postgresql
drwx------ postgres:postgres /var/backups/postgresql/base
drwx------ postgres:postgres /var/backups/postgresql/conf
drwx------ postgres:postgres /var/backups/postgresql/dump
drwx------ postgres:postgres /var/backups/postgresql/globals
drwx------ postgres:postgres /var/backups/postgresql/logs
drwx------ postgres:postgres /var/backups/postgresql/manifest
```

★★★★ `0700` 不是龜毛。一份 `casedb` 的 dump 就是一整份個資的明文副本，
`0755` 等於機器上任何帳號都能整份拿走 —— 詳見〈安全性注意事項〉。

---

## 進階應用

### `pg_dump`：每個旗標為什麼要加 ★★★★

```bash
sudo -u postgres pg_dump \
  --format=custom \
  --compress=zstd:level=9 \
  --file=/var/backups/postgresql/dump/casedb-20260828.dump \
  --verbose \
  --lock-wait-timeout=60s \
  --quote-all-identifiers \
  casedb
```

| 旗標 | 為什麼要加 | 漏掉的後果 | 星級 |
| --- | --- | --- | --- |
| `--format=custom`（`-Fc`） | 二進位封存，**可以只挑一張表還原**、可以 `-j` 平行還原 | 純文字只能整份灌回去，救一張表要手動剪檔 | ★★★★ |
| `--compress=zstd:level=9` | PG16 起支援 `gzip` / `lz4` / `zstd` | 用預設 gzip 也能跑，只是慢且大 | ★★ |
| `--file=` | 直接寫檔，不經過 shell 重導向 | ★★★ 用 `>` 時 **pg_dump 失敗你仍然會拿到一個檔**，而且大小看起來很正常 | ★★★ |
| `--lock-wait-timeout=60s` | pg_dump 要對每張表拿 `ACCESS SHARE` 鎖 | ★★★★ 有人在跑 `ALTER TABLE`，備份會**無聲地卡住幾小時** | ★★★★ |
| `--quote-all-identifiers` | 跨大版本還原時保留字清單會變 | 16 → 17 還原時可能語法錯誤 | ★★ |
| `--verbose` | 把每個物件的處理過程寫進 stderr | 出事時沒有線索 | ★★ |

> [!warning] ★★★★ `pg_dump` 是一個長交易，會擋住 vacuum
> `pg_dump` 全程持有一個 repeatable read 快照。這代表**備份跑多久，autovacuum 就有多久
> 沒辦法清掉那段期間產生的 dead tuple**。50 GB 的庫 dump 兩小時，
> 你會在早上看到表膨脹與查詢變慢；極端情況（超大庫 + 高交易量）還會逼近
> transaction ID wraparound 警告。
> **這是 MySQL `--single-transaction` 沒有的副作用**（InnoDB 的 undo 機制不同）。
> 監控：`SELECT max(age(backend_xmin)) FROM pg_stat_activity;`
> 對策：大庫改用 `pg_basebackup` 當主力，`pg_dump` 降頻或移到 standby 上跑
> （做法見 [[07-PostgreSQL-複寫與高可用]]）。

### ★★★★★ `pg_dumpall --globals-only`：漏掉它，還原必定失敗

```bash
sudo -u postgres pg_dumpall --globals-only \
  --file=/var/backups/postgresql/globals/globals-20260828.sql
sudo -u postgres head -20 /var/backups/postgresql/globals/globals-20260828.sql
```

預期輸出：

```text
--
-- PostgreSQL database cluster dump
--
-- Roles
--
CREATE ROLE app_rw;
ALTER ROLE app_rw WITH NOSUPERUSER INHERIT NOCREATEROLE NOCREATEDB LOGIN NOREPLICATION
  NOBYPASSRLS PASSWORD 'SCRAM-SHA-256$4096:xxxx...';    # ★★★★ 密碼雜湊在裡面！
GRANT pg_read_all_data TO backup;
```

★★★★★ **兩件事同時成立**：
① 沒有這個檔，`pg_restore` 會在每個 `ALTER TABLE ... OWNER TO app_rw` 噴
`ERROR: role "app_rw" does not exist`，還原無法完成；
② 這個檔**含有所有帳號的密碼雜湊**，是整份備份裡機敏度最高的一個檔，
**必須加密**，而且不能跟 dump 放在同一個可讀目錄。

### `pg_restore`：只救一張表 ★★★★

`pg_dump -Fc` 產出的封存有一份目錄（TOC），這是它比純文字強的地方。

**【a】先看裡面有什麼**

```bash
sudo -u postgres pg_restore --list \
  /var/backups/postgresql/dump/casedb-20260828.dump | head -12
```

預期輸出：

```text
;
; Archive created at 2026-08-28 02:00:14 +08
;     dbname: casedb
;     TOC Entries: 412
;
215; 1259 16421 TABLE public case_records app_rw      # ★★★ 左邊的 215 就是 TOC id
2914; 0 16421 TABLE DATA public case_records app_rw
3021; 2606 16430 CONSTRAINT public case_records case_records_pkey app_rw
3055; 1259 16612 INDEX public idx_case_records_created app_rw
```

**【b】挑出你要的那幾筆，還原到暫存庫**

```bash
sudo -u postgres pg_restore --list /var/backups/postgresql/dump/casedb-20260828.dump \
  | grep -E 'case_records' > /tmp/toc.list

sudo -u postgres createdb casedb_recover
sudo -u postgres pg_restore --jobs=4 --use-list=/tmp/toc.list \
  --dbname=casedb_recover \
  /var/backups/postgresql/dump/casedb-20260828.dump
```

預期輸出（成功時**完全沒有輸出**）：

```text
                                     # ★★★ pg_restore 成功是安靜的，靠 echo $? 判斷
```

```bash
echo $?
```

```text
0
```

★★★★ **`--jobs` 只對 `-Fc` 與 `-Fd` 有效，而且不能跟 `--single-transaction` 併用。**
平行還原的效益幾乎全部來自平行建索引 —— 50 GB 的庫從 5 小時降到 1 小時是常見幅度。

**【c】把資料搬回正式庫**：用 SQL，語法見 [[03-SQL基礎操作]]，本篇不重講。

### 加速還原的臨時參數 ★★★★

災難重建時 RTO 就是一切。以下參數**只在還原目標機、還原期間**使用：

```bash
sudo -u postgres psql -d casedb_recover <<'EOF'
ALTER SYSTEM SET maintenance_work_mem = '2GB';   -- ★★★ 建索引快很多
ALTER SYSTEM SET max_wal_size = '16GB';          -- ★★★ 減少 checkpoint 次數
ALTER SYSTEM SET autovacuum = off;               -- ★★ 還原完記得開回來
EOF
sudo -u postgres psql -c "SELECT pg_reload_conf();"
```

> [!danger] ★★★★★ `fsync = off` 只能用在「壞掉可以整個重來」的目標
> 關掉 `fsync` 能讓還原快 2～4 倍，但期間**任何一次斷電或 crash，
> 這套資料庫就是不可修復的損毀**，而且損毀不一定會立刻被發現。
> 只在「還原到一台空機、失敗就從頭再灌一次」時使用。
> **絕對不要為了讓正式庫變快而留著這個設定** —— 這是機房停電後資料庫回不來的頭號原因。
> 還原完成第一件事就是改回 `on` 並 **restart**（`fsync` 是 postmaster 參數）。

### `pg_basebackup`：實體備份 ★★★★

```bash
sudo -u postgres pg_basebackup \
  --pgdata=/var/backups/postgresql/base/20260828 \
  --format=tar \
  --compress=server-zstd:level=6 \
  --wal-method=stream \
  --checkpoint=fast \
  --manifest-checksums=SHA256 \
  --progress --verbose
```

| 旗標 | 意義 | 星級 |
| --- | --- | --- |
| `-F tar`（`--format=tar`） | 產出 `base.tar.zst` + `pg_wal.tar.zst`，適合搬運與封存 | ★★★ |
| `--compress=server-zstd:level=6` | ★★★★ **在伺服器端壓縮**，網路只傳壓縮後的量（PG15+） | ★★★★ |
| `-X stream`（`--wal-method=stream`） | 備份期間同步串流 WAL，**備份本身就是自足的** | ★★★★ |
| `-c fast`（`--checkpoint=fast`） | 立刻做 checkpoint 而不是等排程，備份早點開始 | ★★ |
| `--manifest-checksums=SHA256` | ★★★★ 產生可驗證的 `backup_manifest`，**抗竄改與稽核用** | ★★★★ |
| `-P --progress` | 顯示進度 | ★ |

預期輸出：

```text
pg_basebackup: initiating base backup, waiting for checkpoint to complete
pg_basebackup: checkpoint completed
pg_basebackup: write-ahead log start point: 3/8A000060 on timeline 1
2841096/2841096 kB (100%), 1/1 tablespace
pg_basebackup: write-ahead log end point: 3/8C1D2F18         # ★★★ 記下這個 LSN
pg_basebackup: syncing data to disk ...
pg_basebackup: base backup completed
```

★★★★ **`-X stream` 需要兩條 replication 連線**（一條傳資料、一條傳 WAL）。
`max_wal_senders` 預設 10 夠用，但若你已經掛了 8 台 standby，備份會失敗在
`FATAL: number of requested standby connections exceeds max_wal_senders`。

**驗證備份完整性**（`pg_verifybackup`，PG13 起內建）：

```bash
sudo -u postgres pg_verifybackup /var/backups/postgresql/base/20260828
```

預期輸出：

```text
backup successfully verified
```

★★★★ 檔案被改過或缺一塊時：

```text
pg_verifybackup: error: "base/16385/16421" has size 8192 on disk but size 16384 in the manifest
```

> [!warning] ★★★ `pg_verifybackup` 驗證的是「檔案完整」不是「資料庫能起來」
> 它比對 `backup_manifest` 裡的檔案清單與 checksum。通過只代表**備份沒有在複製或
> 搬運途中損壞**，**不代表**這套資料庫還原後能啟動、能查詢、資料是對的。
> 那是〈還原演練〉的工作，兩件事都要做。

> [!info]- PostgreSQL 17 的增量備份（依官方文件，未實機驗證）
> PG17 新增 `pg_basebackup --incremental=<舊的 backup_manifest>`，
> 只複製自上次備份後有變動的區塊，機關系統常見的「50 GB 庫、每天只改 200 MB」
> 可以省下大量空間與時間。
>
> 前置條件：
> ```ini
> summarize_wal = on          # ★★★★ 預設 off，不開就沒有增量的依據
> wal_summary_keep_time = 10d # 摘要保留期，決定你最多能往前接多久的增量鏈
> ```
>
> ★★★★★ **增量備份不能直接還原**，必須先用 `pg_combinebackup` 把
> 「全備份 + 一連串增量」合成一套完整目錄：
> ```bash
> pg_combinebackup /backup/full /backup/inc1 /backup/inc2 -o /var/lib/postgresql/17/main
> ```
> ★★★★ 這代表**你的鏈上任何一個環節遺失，後面全部作廢**。
> 導入前務必先確認你的輪替腳本不會把全備份刪掉而留著增量。
> 若沒有 PG17 環境可驗證，建議先用 pgBackRest（它的增量機制成熟很多年了）。

### `pg_receivewal`：把 RPO 從 5 分鐘壓到接近 0 ★★★

`archive_timeout = 5min` 的意思是**最壞情況會丟 5 分鐘的資料**。
要再往下壓就要用 `pg_receivewal` 即時串流：

```bash
sudo -u postgres psql -c \
  "SELECT * FROM pg_create_physical_replication_slot('walarchive');"
sudo -u postgres pg_receivewal \
  --directory=/srv/pgwal/stream --slot=walarchive --compress=zstd:6 --verbose
```

預期輸出：

```text
pg_receivewal: starting log streaming at 3/8C000000 (timeline 1)
```

> [!danger] ★★★★★ replication slot 會讓主機磁碟寫滿
> slot 的作用是**保證 WAL 在被接走之前不會被刪掉**。所以當 `pg_receivewal`
> 掛掉或備份主機關機而**你忘了刪 slot**，主機的 `pg_wal/` 會無限成長，
> 終點跟前面一樣是 `PANIC: No space left on device`，整個資料庫停擺。
> **必須做兩件事**：
> ① 用 systemd 管理 `pg_receivewal` 並設 `Restart=always`（寫法見 [[01-systemd-unit撰寫實戰]]）；
> ② 監控 `SELECT slot_name, active, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) FROM pg_replication_slots;`，
> 落後超過門檻就告警。
> ★★★ 也可以設 `max_slot_wal_keep_size = '64GB'` 讓 PostgreSQL 在超標時
> **主動作廢 slot**（保住資料庫，犧牲那份歸檔）—— 這是「兩害相權」的設定，
> 導入前要想清楚你寧可失去哪一個。

### ★★★★★ PITR 完整流程：從備份倒回任意一秒

這是本篇的核心。**九個步驟，順序不可調換。**

**【1】停掉目標叢集**（正式庫還原時，此刻服務中斷開始計時）

```bash
sudo pg_ctlcluster 16 main stop
sudo -u postgres pg_lsclusters
```

```text
Ver Cluster Port Status Owner    Data directory              Log file
16  main    5432 down   postgres /var/lib/postgresql/16/main /var/log/.../postgresql-16-main.log
```

**【2】★★★★★ 把舊資料目錄搬開，不要刪除**

```bash
sudo mv /var/lib/postgresql/16/main /var/lib/postgresql/16/main.broken.$(date +%Y%m%d%H%M)
```

★★★★★ **這一步就是你的回滾方案。** 還原失敗、還原到錯的時間點、發現搞錯資料庫 ——
只要舊目錄還在，你都可以搬回去、啟動、回到事故發生時的狀態重新想。
**直接 `rm -rf` 舊目錄的人，沒有第二次機會。**

★★★ 同時把 `pg_wal/` 裡**還沒歸檔**的最後幾段留下來，它們是最新的交易：

```bash
sudo cp -a /var/lib/postgresql/16/main.broken.*/pg_wal/0000*  /srv/pgwal/archive/ || true
```

**【3】還原基礎備份**

```bash
sudo install -d -o postgres -g postgres -m 0700 /var/lib/postgresql/16/main
sudo -u postgres tar -I zstd -xf /var/backups/postgresql/base/20260828/base.tar.zst \
  -C /var/lib/postgresql/16/main
```

**【4】清空 `pg_wal/`**

```bash
sudo -u postgres find /var/lib/postgresql/16/main/pg_wal -mindepth 1 -delete
sudo -u postgres ls /var/lib/postgresql/16/main/pg_wal
```

```text
                                       # ★★★ 應該是空的（archive_status 會自己重建）
```

★★★★ 不清空的話，備份裡帶的舊 WAL 會跟歸檔來的 WAL 混在一起，
重放順序錯亂，症狀是各種難以理解的 `invalid record length`。

**【5】確認 `backup_label` 在**

```bash
sudo -u postgres cat /var/lib/postgresql/16/main/backup_label
```

```text
START WAL LOCATION: 3/8A000060 (file 000000010000000300000008A)
CHECKPOINT LOCATION: 3/8A000098
BACKUP METHOD: streamed
BACKUP FROM: primary
START TIME: 2026-08-28 02:00:14 CST
LABEL: pg_basebackup base backup
START TIMELINE: 1                        # ★★★★ 記住 timeline，後面會用到
```

★★★★★ **`backup_label` 不見＝ PostgreSQL 會誤以為這是一份正常關機的資料目錄**，
從錯的 checkpoint 開始重放，結果是靜默的資料損毀 —— 比起不起來更糟。

**【6】寫入 recovery 設定**

★★★★ PostgreSQL 12 起**沒有 `recovery.conf` 了**。網路上所有叫你建立
`recovery.conf` 的文章都是給 9.x／11 的，照著做會完全沒有效果（檔案會被忽略）。

```bash
sudo -u postgres tee -a /var/lib/postgresql/16/main/postgresql.auto.conf <<'EOF'
restore_command = 'cp /srv/pgwal/archive/%f %p'
recovery_target_time = '2026-08-26 15:46:30+08'
recovery_target_action = 'pause'
recovery_target_inclusive = false
recovery_target_timeline = 'latest'
EOF
```

| 參數 | 為什麼這樣設 | 星級 |
| --- | --- | --- |
| `recovery_target_time` | ★★★★★ **一定要帶時區偏移 `+08`**。不帶的話用的是伺服器 `TimeZone`，還原機常常是 UTC，你會**整整差 8 小時** | ★★★★★ |
| `recovery_target_action = 'pause'` | 到目標點時**暫停**讓你先查資料，確認對了再放行。設 `promote` 是一步到位、沒有反悔機會 | ★★★★ |
| `recovery_target_inclusive = false` | 停在目標時間**之前**（不含）。救誤操作時你要的就是「前一刻」 | ★★★ |
| `recovery_target_timeline = 'latest'` | PG12 起的預設值。★★★ 若這是**第二次**演練，你必須指定 timeline 才回得去 | ★★★ |

```bash
sudo -u postgres touch /var/lib/postgresql/16/main/recovery.signal
```

★★★★★ **忘了 `touch recovery.signal` 是最常見的失敗**。沒有這個檔，PostgreSQL 會
當成普通啟動，只做崩潰復原，**完全不理會你上面寫的所有 `recovery_target_*`**，
然後正常上線，你以為還原成功了，其實資料停在基礎備份那一刻。

**【7】啟動並看著日誌**

```bash
sudo pg_ctlcluster 16 main start
sudo tail -f /var/log/postgresql/postgresql-16-main.log
```

預期輸出：

```text
LOG:  starting point-in-time recovery to 2026-08-26 15:46:30+08
LOG:  restored log file "000000010000000300000008A" from archive      # ★★★★ 一段段重放
LOG:  redo starts at 3/8A000060
LOG:  restored log file "000000010000000300000008B" from archive
LOG:  recovery stopping before commit of transaction 88412, time 2026-08-26 15:47:02.881+08
LOG:  pausing at the end of recovery                                  # ★★★★★ 停在這裡等你
HINT:  Execute pg_wal_replay_resume() to promote.
```

**【8】檢查資料，確認是你要的那一刻**

```bash
sudo -u postgres psql -d casedb -c \
  "SELECT pg_is_in_recovery(), count(*) FROM case_records WHERE status <> 'closed';"
```

```text
 pg_is_in_recovery | count
-------------------+-------
 t                 |  4182          # ★★★★ 4182 筆還在，證明倒回誤操作之前了
```

★★★ 此時資料庫是**唯讀**的（`pg_is_in_recovery() = t`）。看到不對就直接停掉、
改 `recovery_target_time`、把資料目錄重新展開一次再來 —— 這就是為什麼步驟【2】不能刪。

**【9】放行、結束復原**

```bash
sudo -u postgres psql -c "SELECT pg_wal_replay_resume();"
sudo -u postgres psql -c "SELECT pg_is_in_recovery();"
```

```text
 pg_is_in_recovery
-------------------
 f                              # ★★★★ f ＝ 已經是可寫的正常資料庫
```

日誌會出現：

```text
LOG:  redo done at 3/8C1A0F20
LOG:  selected new timeline ID: 2               # ★★★★★ timeline 從 1 跳到 2
LOG:  archive recovery complete
LOG:  database system is ready to accept connections
```

> [!warning] ★★★★★ timeline 分岔：第二次 PITR 一定要指定 timeline
> promote 之後 timeline 從 1 變成 2，歸檔目錄多出一個 `00000002.history`。
> 若你事後發現時間點抓錯要**再還原一次**，`recovery_target_timeline = 'latest'`
> 會把你帶到 **timeline 2**（也就是剛才那次錯誤還原的結果）。
> 要回到原本的歷史，必須明確寫 `recovery_target_timeline = 1`。
> **不懂 timeline 而在事故現場連做三次 PITR，是把事情越弄越糟的標準路徑。**
> ★★★ 每次 PITR 前先看 `ls /srv/pgwal/archive/*.history` 搞清楚現在有幾條分支。

### ★★★★★ 還原演練：本篇的核心

**備份的價值不在備份，在於「還原得回來」。** 沒演練過的備份，價值是零。

| 層級 | 做什麼 | 能證明什麼 | 星級 |
| --- | --- | --- | --- |
| L1 | 檔案存在、大小 > 0 | ★ 幾乎什麼都不能證明 | ★ |
| L2 | `pg_verifybackup` / `pg_restore -l` 讀得出 TOC | 檔案沒有損壞 | ★★ |
| L3 | **在獨立叢集上真的還原起來** | 資料庫能啟動、能連線 | ★★★★ |
| L4 | **比對每張表的列數 + 抽樣資料 + 量 RTO** | ★★★★★ **這才叫「備份可用」** | ★★★★★ |
| L5 | 含 PITR 到指定時間點、含角色還原、含應用連線測試 | 整套災難復原程序可行 | ★★★★★ |

**做到 L4 才能在稽核時說「我們的備份可以還原」。** 頻率建議：
每月一次 L3～L4（自動化），每季一次 L5（人工，有紀錄）。
一般性的演練制度看 [[03-備份策略與還原演練]] 與 [[06-災難復原與異地備援]]。

---

## 完整實戰範例

### 情境：某機關案件系統，週三下午的一句 UPDATE

```text
2026-08-26（三）
  15:47  承辦在 psql 執行了「本來要加 WHERE」的更新：
         UPDATE case_records SET status = 'closed';        ← ★★★★★ 沒有 WHERE
         結果 4,182 筆未結案件全部被標成已結案。
  15:47  ~ 16:05 期間，另外 19 位同仁正常新增 / 修改了 233 筆案件。
  16:05  科長發現案件查詢頁面全空，通報。
  16:07  你接手。
```

**手上的底牌**：8/26 02:00 的 `pg_basebackup`、持續的 WAL 歸檔、8/26 02:00 的 `pg_dump`。

★★★★ **`pg_dump` 在這個情境幫不上忙**（它是 02:00 的狀態，中間 13 小時的資料會全丟）。
唯一的路是 PITR。這正是前面說的「PostgreSQL 救資料只有 PITR 一條路」。

### 【1】立刻凍結寫入，保全現場（16:08）★★★★

```bash
sudo -u postgres psql -d casedb <<'EOF'
REVOKE CONNECT ON DATABASE casedb FROM app_rw;
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
 WHERE datname = 'casedb' AND usename = 'app_rw';
EOF
```

預期輸出：

```text
REVOKE
 pg_terminate_backend
----------------------
 t
 t
(2 rows)                        # ★★★ 兩條應用連線被踢掉了
```

★★★★ **為什麼要凍結**：每多一分鐘，事故後的新資料就多一批。等一下你要把
「舊的正確值」搬回來，新資料越多，比對與合併就越危險。
★★★ 同時立刻確認 WAL 歸檔還活著 —— 它是你唯一的救命繩：

```bash
sudo -u postgres psql -c \
  "SELECT last_archived_time, failed_count FROM pg_stat_archiver;"
```

```text
      last_archived_time       | failed_count
-------------------------------+--------------
 2026-08-26 16:05:14.221+08    |            0     # ★★★★ 到事故後仍在歸檔，可以做
```

### 【2】確認底牌完整（16:12）

```bash
sudo -u postgres pg_verifybackup /var/backups/postgresql/base/20260826
ls /srv/pgwal/archive/ | wc -l
```

```text
backup successfully verified
1874                                   # ★★★ 從 02:00 到現在的 WAL 都在
```

### 【3】在 5433 埠開一套「時光機」叢集（16:15～16:52）★★★★★

**★★★★★ 絕對不要在正式庫上做 PITR。** 正式庫是你僅存的、含有 16:05 之後
正常資料的那一份。在旁邊開一套獨立叢集，這是唯一安全的做法。

```bash
sudo install -d -o postgres -g postgres -m 0700 /var/lib/postgresql/tm/data
sudo -u postgres tar -I zstd -xf \
  /var/backups/postgresql/base/20260826/base.tar.zst -C /var/lib/postgresql/tm/data
sudo -u postgres find /var/lib/postgresql/tm/data/pg_wal -mindepth 1 -delete

sudo -u postgres tee -a /var/lib/postgresql/tm/data/postgresql.auto.conf <<'EOF'
port = 5433
restore_command = 'cp /srv/pgwal/archive/%f %p'
recovery_target_time = '2026-08-26 15:46:50+08'    # ★★★★ 誤操作前 10 秒
recovery_target_inclusive = false
recovery_target_action = 'pause'
archive_mode = off                                 # ★★★★★ 千萬別讓它去污染歸檔目錄
EOF
sudo -u postgres touch /var/lib/postgresql/tm/data/recovery.signal
sudo -u postgres /usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/postgresql/tm/data -w start
```

★★★★★ `archive_mode = off` 這行漏掉的後果非常嚴重：時光機叢集 promote 後會是
timeline 2，它會把 timeline 2 的 WAL **寫進你正式庫的歸檔目錄**，
把兩條歷史混在一起。之後你再想從正式庫做 PITR，會踩到一堆對不上的 WAL。

驗證時光機是對的：

```bash
sudo -u postgres psql -p 5433 -d casedb -c \
  "SELECT status, count(*) FROM case_records GROUP BY status ORDER BY 2 DESC;"
```

```text
  status  | count
----------+-------
 open     |  3106
 pending  |  1076
 closed   | 41982
(3 rows)                        # ★★★★ 4182 筆未結案件回來了（3106 + 1076）
```

### 【4】把正確的 status 搬回正式庫（16:55）★★★★★

★★★★★ **不要**把時光機整套灌回正式庫 —— 那會把 16:05 之後 19 位同仁做的
233 筆正常異動全部抹掉，**而那 233 筆沒有任何備份可以救**。
正確做法是**只搬那一欄、只搬受影響的列**。

用 `postgres_fdw` 或 dump 單表都可以，這裡用最不需要額外設定的做法：

```bash
# 從時光機只匯出 id 與 status 兩欄
sudo -u postgres psql -p 5433 -d casedb -c \
  "\copy (SELECT id, status FROM case_records) TO '/tmp/status_1546.csv' CSV"
wc -l /tmp/status_1546.csv
```

```text
46164 /tmp/status_1546.csv
```

```bash
sudo -u postgres psql -p 5432 -d casedb <<'EOF'
BEGIN;
CREATE TEMP TABLE fix (id bigint PRIMARY KEY, status text);
\copy fix FROM '/tmp/status_1546.csv' CSV

-- ★★★★★ 只更新「現在是 closed、但 15:46 不是 closed、且事故後沒被人動過」的列
SELECT count(*) FROM case_records c JOIN fix f USING (id)
 WHERE c.status = 'closed' AND f.status <> 'closed'
   AND c.updated_at < '2026-08-26 15:47:00+08';
EOF
```

```text
 count
-------
  4182                      # ★★★★★ 數字要跟事故報告一致，不一致就 ROLLBACK 重想
```

確認是 4182 之後才真正更新：

```bash
sudo -u postgres psql -p 5432 -d casedb <<'EOF'
BEGIN;
CREATE TEMP TABLE fix (id bigint PRIMARY KEY, status text);
\copy fix FROM '/tmp/status_1546.csv' CSV
UPDATE case_records c SET status = f.status
  FROM fix f
 WHERE c.id = f.id
   AND c.status = 'closed' AND f.status <> 'closed'
   AND c.updated_at < '2026-08-26 15:47:00+08';
COMMIT;
EOF
```

```text
BEGIN
UPDATE 4182                 # ★★★★★ 就是這個數字，多一筆少一筆都要停下來查
COMMIT
```

### 【5】驗證與解除凍結（17:10）

```bash
sudo -u postgres psql -d casedb <<'EOF'
SELECT status, count(*) FROM case_records GROUP BY status ORDER BY 2 DESC;
SELECT count(*) FROM case_records WHERE updated_at >= '2026-08-26 15:47:00+08';
GRANT CONNECT ON DATABASE casedb TO app_rw;
EOF
```

```text
  status  | count
----------+-------
 open     |  3121
 pending  |  1094
 closed   | 41949
(3 rows)

 count
-------
   233                      # ★★★★ 事故後的 233 筆正常異動一筆都沒少
GRANT
```

★★★★ **兩個數字都要對**：4182 筆救回來、233 筆沒被蓋掉。
只驗第一個就宣布結案，是把另一場事故留給下週的自己。

### 【6】收尾與事故時間軸

```bash
sudo -u postgres /usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/postgresql/tm/data stop
sudo rm -rf /var/lib/postgresql/tm /tmp/status_1546.csv     # ★★★★ CSV 含個資，要刪
```

| 時間 | 動作 | 累計 |
| --- | --- | --- |
| 15:47 | 事故發生 | — |
| 16:05 | 發現（★★★ **18 分鐘的偵測落差，這是最該改善的一格**） | 18 分 |
| 16:08 | 凍結寫入 | 21 分 |
| 16:15 | 開始 PITR | 28 分 |
| 16:52 | 時光機就緒 | 65 分 |
| 17:10 | 資料修復完成、服務恢復 | **83 分（實際 RTO）** |

改善項：① 對 `case_records` 的批次 UPDATE 加告警（受影響列數 > 100 就通知）；
② 正式庫禁止承辦直接 psql，改走管理介面；
③ ★★★★ 把上面整套流程寫成腳本並每月演練 —— 就是下面兩支。

### 交付物一：`/usr/local/bin/pg-backup.sh`

```bash
#!/bin/bash
#===============================================================================
# pg-backup.sh — PostgreSQL 每日備份（dump + globals + conf，週日加 basebackup）
# 用法：pg-backup.sh [daily|weekly]
# 以 postgres 身分執行，走 unix socket + peer，不需要密碼
#===============================================================================
set -euo pipefail
IFS=$'\n\t'

PGVER=16
CLUSTER=main
PGDATA_CONF="/etc/postgresql/${PGVER}/${CLUSTER}"
BASE=/var/backups/postgresql
ARCHIVE=/srv/pgwal/archive
KEEP_DUMP_DAYS=14                 # ★★★ 保留期 > 全備份間隔 + 你發現問題所需的時間
KEEP_BASE_DAYS=35
KEEP_WAL_DAYS=35                  # ★★★★ 必須 >= KEEP_BASE_DAYS，否則舊備份無法 PITR
MIN_FREE_GB=20
AGE_RECIPIENT="age1qy7k9v0zk8l4pxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
OFFSITE="backup@nas01:/srv/pgbackup/db01/"
WEBHOOK="https://chat.example.gov.tw/hooks/xxxxxxxx"
LOCK=/var/lock/pg-backup.lock
MODE="${1:-daily}"
TS=$(date +%Y%m%d-%H%M)
LOG="${BASE}/logs/${TS}.log"

log()  { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG"; }
die()  { log "FATAL: $*"; exit 1; }

# ★★★★ 失敗告警：沒有這一段，腳本連續失敗三週也沒人知道
alert() {
  local msg="pg-backup 失敗 @$(hostname -s) [$MODE]: $*"
  curl -fsS -m 10 -X POST -H 'Content-Type: application/json' \
       -d "{\"text\":\"$msg\"}" "$WEBHOOK" || true
  printf '%s\n' "$msg" | mail -s "[CRIT] pg-backup 失敗" dba@example.gov.tw || true
  logger -t pg-backup -p daemon.err "$msg"
}
trap 'rc=$?; [[ $rc -ne 0 ]] && alert "exit=$rc line=$LINENO"; exit $rc' ERR

#--- 0. 單一執行 --------------------------------------------------------------
exec 9>"$LOCK"
flock -n 9 || die "另一個 pg-backup 還在跑（$LOCK）"      # ★★★ 備份重疊會拖垮 IO

#--- 1. 前置檢查 --------------------------------------------------------------
preflight() {
  log "=== 前置檢查 ==="
  command -v age >/dev/null || die "缺少 age，請 apt install age"
  pg_isready -q || die "PostgreSQL 沒在跑"

  local free
  free=$(df -BG --output=avail "$BASE" | tail -1 | tr -dc '0-9')
  [[ $free -ge $MIN_FREE_GB ]] || die "備份磁碟只剩 ${free}G（門檻 ${MIN_FREE_GB}G）"

  # ★★★★ 歸檔壞掉時就算 dump 成功也做不了 PITR，寧可現在就吵
  local failed
  failed=$(psql -tAc "SELECT failed_count FROM pg_stat_archiver;")
  [[ "$failed" == "0" ]] || die "WAL 歸檔失敗 ${failed} 次，先修歸檔再談備份"
  log "前置檢查通過（可用空間 ${free}G，歸檔失敗數 0）"
}

#--- 2. 全域物件（角色、表空間）------------------------------------------------
dump_globals() {
  log "=== 匯出全域物件 ==="
  local out="${BASE}/globals/globals-${TS}.sql"
  pg_dumpall --globals-only --file="$out"
  grep -q '^CREATE ROLE' "$out" || die "globals 檔沒有任何 CREATE ROLE，內容可疑"
  # ★★★★★ 這個檔含密碼雜湊，立刻加密、立刻刪明文
  age -r "$AGE_RECIPIENT" -o "${out}.age" "$out" && shred -u "$out"
  log "globals → ${out}.age"
}

#--- 3. 設定檔（Ubuntu 的 /etc/postgresql 不在 basebackup 裡）------------------
dump_conf() {
  log "=== 備份設定檔 ==="
  tar -czf "${BASE}/conf/etc-postgresql-${TS}.tar.gz" -C /etc postgresql
  tar -tzf "${BASE}/conf/etc-postgresql-${TS}.tar.gz" | grep -q 'pg_hba.conf' \
    || die "設定檔備份裡沒有 pg_hba.conf"          # ★★★★ 驗證，不是只看 exit code
  log "設定檔 OK"
}

#--- 4. 邏輯備份 --------------------------------------------------------------
dump_databases() {
  log "=== 邏輯備份 ==="
  local dbs db out
  dbs=$(psql -tAc "SELECT datname FROM pg_database
                    WHERE datallowconn AND datname NOT IN ('template0','template1');")
  for db in $dbs; do
    out="${BASE}/dump/${db}-${TS}.dump"
    log "  pg_dump ${db} ..."
    pg_dump --format=custom --compress=zstd:level=9 --quote-all-identifiers \
            --lock-wait-timeout=120s --file="$out" "$db"

    # ★★★★ 驗證：讀得出 TOC 才算數，「檔案存在」不是驗證
    local n
    n=$(pg_restore --list "$out" | grep -c '^[0-9]') || true
    [[ ${n:-0} -gt 0 ]] || die "${db} 的 dump 讀不出 TOC（${n} 筆），檔案有問題"
    log "  ${db}: TOC ${n} 筆, $(du -h "$out" | cut -f1)"

    age -r "$AGE_RECIPIENT" -o "${out}.age" "$out" && rm -f "$out"
    sha256sum "${out}.age" >> "${BASE}/manifest/SHA256SUMS-${TS}"
  done
}

#--- 5. 實體備份（每週）-------------------------------------------------------
base_backup() {
  [[ "$MODE" == "weekly" ]] || { log "=== 略過 basebackup（daily）==="; return 0; }
  log "=== pg_basebackup ==="
  local dir="${BASE}/base/${TS}"
  pg_basebackup --pgdata="$dir" --format=tar --compress=server-zstd:level=6 \
                --wal-method=stream --checkpoint=fast \
                --manifest-checksums=SHA256 --verbose
  pg_verifybackup "$dir" || die "pg_verifybackup 不通過：$dir"   # ★★★★ 必驗
  ln -sfn "$dir" "${BASE}/base/latest"
  log "basebackup OK → $dir"
}

#--- 6. 異地 -----------------------------------------------------------------
offsite() {
  log "=== 異地同步 ==="
  rsync -a --delete-delay --partial \
        -e 'ssh -o BatchMode=yes -o ConnectTimeout=15' \
        "${BASE}/" "$OFFSITE" || die "異地同步失敗（$OFFSITE）"
  log "異地同步完成"
}

#--- 7. 輪替 -----------------------------------------------------------------
rotate() {
  log "=== 輪替 ==="
  find "${BASE}/dump"    -name '*.age'  -mtime "+${KEEP_DUMP_DAYS}" -delete
  find "${BASE}/globals" -name '*.age'  -mtime "+${KEEP_DUMP_DAYS}" -delete
  find "${BASE}/conf"    -name '*.tar.gz' -mtime "+${KEEP_DUMP_DAYS}" -delete
  find "${BASE}/base"    -maxdepth 1 -type d -mtime "+${KEEP_BASE_DAYS}" \
       -exec rm -rf {} +

  # ★★★★★ WAL 只能清「最舊那份仍要保留的 basebackup 之前」的，多刪一段 PITR 就斷了
  local oldest
  oldest=$(ls -1d "${BASE}"/base/2* 2>/dev/null | head -1) || true
  if [[ -n "${oldest:-}" && -f "${oldest}/backup_manifest" ]]; then
    pg_archivecleanup "$ARCHIVE" \
      "$(grep -oE '[0-9A-F]{24}' "${oldest}/backup_manifest" | head -1)" || true
    log "已清理早於 ${oldest} 的 WAL"
  else
    log "找不到可參照的 basebackup，★★★★ 本輪不清 WAL（寧可佔空間也不要斷鏈）"
  fi
}

#--- 8. 摘要 -----------------------------------------------------------------
summary() {
  log "=== 摘要 ==="
  du -sh "${BASE}"/{dump,base,globals,conf} | tee -a "$LOG"
  df -h "$BASE" | tail -1 | tee -a "$LOG"
  log "完成（模式：$MODE）"
}

preflight; dump_globals; dump_conf; dump_databases; base_backup; offsite; rotate; summary
```

**回滾方式**：這支腳本**只寫入備份目錄、不動資料庫**，最壞情況是產出一份壞備份。
發現某一輪有問題時，刪掉那一輪的檔案、把 `${BASE}/base/latest` 的符號連結指回
前一個目錄即可：

```bash
sudo -u postgres ln -sfn /var/backups/postgresql/base/20260819-0200 \
                          /var/backups/postgresql/base/latest
```

排程（用 systemd timer，理由見 [[02-systemd-timer與cron選型]]）：

```ini
# /etc/systemd/system/pg-backup.service
[Unit]
Description=PostgreSQL backup
After=postgresql.service

[Service]
Type=oneshot
User=postgres
ExecStart=/usr/local/bin/pg-backup.sh daily
Nice=10
IOSchedulingClass=idle          # ★★★ 別讓備份拖垮線上查詢
```

### 交付物二：`/usr/local/bin/pg-pitr-drill.sh`

★★★★★ **這支才是真正證明「你的備份有用」的東西。** 每月自動跑一次，
輸出可以直接貼進稽核報告。

```bash
#!/bin/bash
#===============================================================================
# pg-pitr-drill.sh — 還原演練：在 5433 埠還原最新 basebackup + PITR，比對後拆除
# 用法：pg-pitr-drill.sh ["2026-08-28 03:00:00+08"]
#===============================================================================
set -euo pipefail

PGVER=16
BIN=/usr/lib/postgresql/${PGVER}/bin
BASE=/var/backups/postgresql
ARCHIVE=/srv/pgwal/archive
DRILL=/var/lib/postgresql/drill
PORT=5433
TARGET="${1:-$(date -d '-1 hour' '+%Y-%m-%d %H:%M:%S%:z')}"
RPT="${BASE}/logs/drill-$(date +%Y%m%d).txt"
START_TS=$(date +%s)

log() { printf '[%s] %s\n' "$(date +%T)" "$*" | tee -a "$RPT"; }
die() { log "DRILL FAILED: $*"; cleanup; exit 1; }

cleanup() {
  # ★★★★ 無論成敗都要拆掉，否則下次演練會撞埠、而且佔著磁碟
  [[ -d "$DRILL/data" ]] && "$BIN/pg_ctl" -D "$DRILL/data" -m immediate stop 2>/dev/null || true
  rm -rf "$DRILL"
}
trap cleanup EXIT

log "===== PITR 還原演練 $(date '+%F %T') ====="
log "目標時間點：$TARGET"

#--- 1. 展開最新 basebackup ---------------------------------------------------
SRC=$(readlink -f "${BASE}/base/latest") || die "找不到 ${BASE}/base/latest"
log "來源備份：$SRC"
pg_verifybackup "$SRC" || die "來源備份 pg_verifybackup 不通過"

install -d -m 0700 "$DRILL/data"
tar -I zstd -xf "$SRC/base.tar.zst" -C "$DRILL/data" || die "展開 base.tar.zst 失敗"
find "$DRILL/data/pg_wal" -mindepth 1 -delete
[[ -f "$DRILL/data/backup_label" ]] || die "backup_label 不見了，這份備份不能用"

#--- 2. recovery 設定 ---------------------------------------------------------
cat >> "$DRILL/data/postgresql.auto.conf" <<EOF
port = ${PORT}
archive_mode = off
restore_command = 'cp ${ARCHIVE}/%f %p'
recovery_target_time = '${TARGET}'
recovery_target_action = 'promote'
recovery_target_inclusive = true
max_connections = 20
shared_buffers = 256MB
EOF
touch "$DRILL/data/recovery.signal"

#--- 3. 啟動並等待復原完成 ----------------------------------------------------
log "啟動演練叢集 ..."
"$BIN/pg_ctl" -D "$DRILL/data" -l "$DRILL/pg.log" -w -t 1800 start \
  || { tail -30 "$DRILL/pg.log" | tee -a "$RPT"; die "演練叢集啟動失敗"; }

for i in $(seq 1 180); do
  inrec=$("$BIN/psql" -p "$PORT" -tAc "SELECT pg_is_in_recovery();" postgres 2>/dev/null || echo x)
  [[ "$inrec" == "f" ]] && break
  sleep 10
done
[[ "${inrec:-x}" == "f" ]] || die "30 分鐘內沒有結束復原（still in recovery）"
RTO=$(( $(date +%s) - START_TS ))
log "復原完成，實際 RTO = ${RTO} 秒"

#--- 4. ★★★★★ L4 比對：列數，不是表數 -----------------------------------------
log "----- 列數比對 -----"
FAIL=0
for db in $("$BIN/psql" -p "$PORT" -tAc \
      "SELECT datname FROM pg_database WHERE datallowconn AND datname NOT LIKE 'template%';" postgres); do
  while IFS='|' read -r tbl; do
    [[ -z "$tbl" ]] && continue
    a=$("$BIN/psql" -p 5432   -d "$db" -tAc "SELECT count(*) FROM $tbl;" 2>/dev/null || echo ERR)
    b=$("$BIN/psql" -p "$PORT" -d "$db" -tAc "SELECT count(*) FROM $tbl;" 2>/dev/null || echo ERR)
    if [[ "$a" == "ERR" || "$b" == "ERR" ]]; then
      log "  ?? ${db}.${tbl}: 讀取失敗 (prod=$a drill=$b)"; FAIL=$((FAIL+1))
    elif [[ "$b" -eq 0 && "$a" -gt 0 ]]; then
      log "  !! ${db}.${tbl}: 演練庫是空的 (prod=$a)"; FAIL=$((FAIL+1))   # ★★★★★
    else
      log "  ok ${db}.${tbl}: prod=$a drill=$b"
    fi
  done < <("$BIN/psql" -p "$PORT" -d "$db" -tAc \
      "SELECT quote_ident(schemaname)||'.'||quote_ident(relname)
         FROM pg_stat_user_tables ORDER BY 1;")
done

#--- 5. 角色與擴充套件 --------------------------------------------------------
log "----- 角色 / 擴充套件 -----"
ra=$("$BIN/psql" -p 5432    -tAc "SELECT count(*) FROM pg_roles;" postgres)
rb=$("$BIN/psql" -p "$PORT" -tAc "SELECT count(*) FROM pg_roles;" postgres)
[[ "$ra" == "$rb" ]] || { log "  !! 角色數 prod=$ra drill=$rb"; FAIL=$((FAIL+1)); }
log "  角色數 prod=$ra drill=$rb"

#--- 6. 結論 -----------------------------------------------------------------
log "----- 結論 -----"
if [[ $FAIL -eq 0 ]]; then
  log "PASS：備份可還原，實測 RTO ${RTO} 秒，目標時間點 ${TARGET}"
else
  log "FAIL：${FAIL} 項不通過，★★★★★ 這代表你目前沒有可用的備份，立刻處理"
  exit 1
fi
```

### 驗收檢查表

| # | 檢查項 | 指令 | 預期結果 | 星級 |
| --- | --- | --- | --- | --- |
| 1 | 歸檔在動 | `psql -c "SELECT last_archived_time, failed_count FROM pg_stat_archiver;"` | 時間是幾分鐘內、`failed_count = 0` | ★★★★★ |
| 2 | `pg_wal` 沒異常長大 | `du -sh $PGDATA/pg_wal` | 穩定在 `max_wal_size` 的數倍以內 | ★★★★ |
| 3 | 歸檔目錄不同碟 | `df /srv/pgwal/archive $PGDATA \| awk '{print $1}'` | ★★★★ 兩行**不同** | ★★★★ |
| 4 | dump 讀得出 TOC | `pg_restore -l casedb-*.dump \| grep -c '^[0-9]'` | > 0 | ★★★★ |
| 5 | globals 有角色 | `age -d globals-*.age \| grep -c '^CREATE ROLE'` | > 0 | ★★★★★ |
| 6 | `pg_hba.conf` 有被備份 | `tar -tzf etc-postgresql-*.tar.gz \| grep pg_hba` | 有一行 | ★★★★ |
| 7 | basebackup 完整 | `pg_verifybackup $BASE/base/latest` | `backup successfully verified` | ★★★★ |
| 8 | 備份目錄權限 | `stat -c '%a %U' /var/backups/postgresql` | `700 postgres` | ★★★★ |
| 9 | 異地有到 | `ssh nas01 'ls -l /srv/pgbackup/db01/dump \| tail -3'` | 今天的檔案 | ★★★★ |
| 10 | **還原演練通過** | `/usr/local/bin/pg-pitr-drill.sh` | 最後一行 `PASS` | ★★★★★ |
| 11 | 實測 RTO 在承諾內 | 演練報告的 `RTO = N 秒` | ≤ 服務水準承諾 | ★★★★ |
| 12 | 失敗會告警 | 故意 `chmod 000 /srv/pgwal/archive` 跑一次 | 群組收到訊息 | ★★★★★ |

★★★★★ **第 12 項最容易被跳過，也最重要**。「備份腳本失敗但沒有人知道」是
機關資料庫災難最常見的前置條件，而它**只能靠故意弄壞一次來驗證**。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `PANIC: could not write to file "pg_wal/xlogtemp...": No space left on device`，資料庫停止服務 | `archive_command` 長期失敗（或 replication slot 沒人接），WAL 全堆在 `pg_wal/` | 緊急：清出空間讓它先起來（**★★★★★ 絕對不可以直接 `rm pg_wal/` 裡的檔**，用 `pg_archivecleanup` 或先擴 LV）。根因：修好歸檔、把 `failed_count` 納入監控 |
| ★★★★★ 還原後 `PANIC: could not locate a valid checkpoint record` | 用 `cp`／`rsync` 熱複製了 `$PGDATA`，或 `backup_label` 被刪 | 這份備份無效，換一份。改用 `pg_basebackup` |
| ★★★★★ PITR 完成但資料停在備份那一刻 | 忘了 `touch recovery.signal`，`recovery_target_*` 被完全忽略 | 重新展開備份、建 `recovery.signal`、再啟動。日誌要看到 `starting point-in-time recovery to ...` |
| ★★★★ 還原時整片 `ERROR: role "app_rw" does not exist` | `pg_dump` **不含角色**，忘了先灌 `pg_dumpall -g` | 先 `psql -f globals.sql`，再 `pg_restore` |
| ★★★★ `ERROR: extension "postgis" is not available` | 目標機沒裝該擴充套件的**作業系統套件** | `apt install postgresql-16-postgis-3` 後重跑。★★★ 演練機的擴充套件清單必須跟正式庫一致 |
| ★★★★ `FATAL: no pg_hba.conf entry for host ..., user "backup", database "replication"` | `pg_hba.conf` 的 `all` **不包含 replication** | 加一行 `host replication backup 127.0.0.1/32 scram-sha-256`，然後 `pg_reload_conf()` |
| ★★★★ `recovery_target_time` 設對了卻差 8 小時 | 時間字串沒帶時區，套用了伺服器的 `TimeZone`（常是 UTC） | 一律寫成 `'2026-08-26 15:46:30+08'`。時間本身的正確性見 [[28-時間同步NTP與chrony]] |
| ★★★★ 第二次 PITR 回到的是「上一次錯誤還原的結果」 | promote 後 timeline 前進，`recovery_target_timeline='latest'` 帶你去新分支 | 明確指定 `recovery_target_timeline = 1`。先 `ls $ARCHIVE/*.history` 看清楚分支 |
| ★★★★ `pg_dump` 卡住幾小時沒有任何輸出 | 有人在跑 `ALTER TABLE`，pg_dump 等 `ACCESS SHARE` 鎖；後面所有查詢又被 pg_dump 擋住 | 加 `--lock-wait-timeout=60s` 讓它快速失敗。查 `SELECT * FROM pg_locks WHERE NOT granted;` |
| ★★★★ 備份期間表膨脹、查詢變慢 | `pg_dump` 的長快照擋住 autovacuum | 監控 `max(age(backend_xmin))`；大庫改用 `pg_basebackup`，或把 dump 移到 standby |
| ★★★ `pg_restore` 只有一顆 CPU 在跑，慢到不行 | 用了 `-Fp`（純文字），或 `-Fc` 但沒加 `-j` | 改 `-Fc`／`-Fd` 並加 `--jobs=$(nproc)`。★★ `-j` 不能與 `--single-transaction` 併用 |
| ★★★ 還原後查詢慢十倍 | 還原不含最佳化統計值 | `VACUUM ANALYZE;`（或 `vacuumdb -a -z -j4`）。★★★ 這一步要寫進還原程序，不是選配 |
| ★★★ `WARNING: database "casedb" has a collation version mismatch` | 還原到不同 glibc 版本的作業系統，文字排序規則變了 | `REINDEX DATABASE casedb;` 之後 `ALTER DATABASE casedb REFRESH COLLATION VERSION;`。★★★★ 不處理的話**索引會查不到本來存在的資料** |
| ★★★ `pg_dump: error: server version: 17.4; pg_dump version: 16.9` | 用舊版 `pg_dump` 連新版伺服器 | `pg_dump` 版本必須 ≥ 伺服器版本。Ubuntu 上用 `pg_dump --cluster 17/main` 讓 `pg_wrapper` 挑對執行檔 |
| ★★ 備份檔比昨天小很多但沒報錯 | 某個 schema 被 REVOKE 掉、`pg_dump` 悄悄跳過 | 比對 `pg_restore -l` 的 TOC 筆數而不是檔案大小；TOC 掉超過 5% 就告警 |

### 排查步驟

**【1】先確定「壞的是備份，還是資料庫」**

```bash
sudo -u postgres pg_isready; sudo -u postgres psql -c "SELECT version();"
```

預期輸出：

```text
/var/run/postgresql:5432 - accepting connections
                     version
--------------------------------------------------
 PostgreSQL 16.9 (Ubuntu 16.9-1.pgdg24.04+1) on x86_64-pc-linux-gnu
```

看到 `no response` → 資料庫本身有事，先看【2】；
正常回應 → 資料庫活著，跳到【3】。

**【2】資料庫起不來：看它卡在哪一句**

```bash
sudo tail -40 /var/log/postgresql/postgresql-16-main.log
```

| 看到 | 代表 | 去哪 |
| --- | --- | --- |
| `No space left on device` | ★★★★★ 磁碟滿，多半是 `pg_wal` 爆掉 | 【4】 |
| `could not locate a valid checkpoint record` | ★★★★★ 資料目錄不一致（熱複製／缺 `backup_label`） | 只能還原，見 PITR 流程 |
| `the database system is starting up` 持續數分鐘 | 正在做崩潰復原或 WAL 重放 | ★★★ **耐心等**，強制 kill 會讓情況更糟 |
| `FATAL: could not open file "pg_wal/000000010000..."` | 缺 WAL 段 | 【5】 |

**【3】備份沒產出：先看鎖，再看歸檔**

```bash
sudo -u postgres psql -x -c \
  "SELECT pid, state, wait_event_type, wait_event, now()-query_start AS dur, left(query,60) AS q
     FROM pg_stat_activity WHERE state <> 'idle' ORDER BY dur DESC LIMIT 3;"
```

預期輸出：

```text
-[ RECORD 1 ]---+------------------------------------------------------
pid             | 31544
state           | active
wait_event_type | Lock                       # ★★★★ Lock 就是在等鎖，不是在做事
wait_event      | relation
dur             | 02:41:18                   # ★★★★ 兩小時多，備份根本沒動
q               | LOCK TABLE public.case_records IN ACCESS SHARE MODE
```

`wait_event_type = Lock` → 有 DDL 擋著，看 `pg_locks WHERE NOT granted`；
`wait_event_type = IO` → 磁碟慢，看【6】；
沒有任何 pg_dump 程序 → 腳本根本沒被觸發，看【7】。

**【4】`pg_wal` 爆掉的正確處理順序**

```bash
sudo du -sh /var/lib/postgresql/16/main/pg_wal
sudo -u postgres psql -c "SELECT * FROM pg_stat_archiver;" 2>/dev/null || echo "資料庫已停"
sudo -u postgres psql -tAc \
  "SELECT slot_name, active, restart_lsn FROM pg_replication_slots;" 2>/dev/null
```

預期輸出：

```text
187G	/var/lib/postgresql/16/main/pg_wal        # ★★★★★ 這就是元凶
walarchive|f|3/8A000060                       # ★★★★ active = f 的 slot 在扣著 WAL
```

處理順序（**不可跳號**）：
① 先空出磁碟（刪 `/var/log` 的舊檔、擴 LV，見 [[15-磁碟分割與掛載]]）讓資料庫能起來；
② `SELECT pg_drop_replication_slot('walarchive');` 解除扣留；
③ 修 `archive_command`；
④ 確認 `failed_count` 停止增加後，才用 `pg_archivecleanup` 清舊 WAL。
★★★★★ **任何情況下都不要 `rm` `pg_wal/` 裡的檔案** —— 那是尚未落地的交易，
刪掉就是無法復原的資料損毀。

**【5】缺 WAL 段：確認鏈有沒有斷**

```bash
ls /srv/pgwal/archive/ | grep -E '^[0-9A-F]{24}$' | sort | \
  awk 'NR>1 && strtonum("0x" substr($0,17,8)) != prev+1 {print "GAP before " $0}
       {prev = strtonum("0x" substr($0,17,8))}'
```

預期輸出（健康時**沒有輸出**）：

```text
                                     # ★★★★ 有 GAP 那幾行就是 PITR 的終點
```

有 GAP → 你只能還原到 GAP 之前那一刻，**後面的資料回不來**，立刻通報而不是繼續試。

**【6】還原太慢：確認瓶頸在 CPU 還是 IO**

```bash
sudo -u postgres psql -p 5433 -c \
  "SELECT wait_event_type, count(*) FROM pg_stat_activity GROUP BY 1;"
iostat -x 2 3 | tail -12
```

預期輸出：

```text
 wait_event_type | count
-----------------+-------
 IO              |     6        # ★★★ IO 佔多數 → 磁碟是瓶頸
```

IO 為主 → 調 `maintenance_work_mem`、`max_wal_size`，或換更快的還原目標碟；
沒有 wait_event（純 CPU）→ 加 `--jobs`，平行建索引。

**【7】腳本沒被觸發**

```bash
systemctl list-timers pg-backup.timer
journalctl -u pg-backup.service --since '-3d' --no-pager | tail -20
```

預期輸出：

```text
NEXT                        LEFT     LAST                        PASSED  UNIT
Sat 2026-08-29 02:00:00 CST 16h left Fri 2026-08-28 02:00:12 CST 7h ago  pg-backup.timer
```

`LAST` 是 `n/a` 或很久以前 → timer 沒啟用（`systemctl enable --now pg-backup.timer`）；
有跑但 `journalctl` 看到 `另一個 pg-backup 還在跑` → 上一輪卡住了，看【3】。

**【8】最後一關：真的還原一次**

前七步都正常但你仍然不確定備份可不可用時，**唯一的答案是跑演練**：

```bash
sudo -u postgres /usr/local/bin/pg-pitr-drill.sh
```

預期輸出（結尾）：

```text
[03:41:22] PASS：備份可還原，實測 RTO 1876 秒，目標時間點 2026-08-28 02:30:00+08
```

★★★★★ 看到 `FAIL` 就是**你現在沒有可用的備份**，這是最高優先事件，
不是「下週再處理」的技術債。

---

## 安全性注意事項

> [!danger] ★★★★★ 絕對禁止
> - **把 dump 檔放在 `0755` 目錄或家目錄。** 一份 `casedb.dump` 就是全體案件當事人的
>   姓名、身分證字號、地址、聯絡電話的完整明文副本。機器上任何一個帳號
>   （包含被入侵的 Web 服務帳號）`cp` 一下就整份帶走，**而且存取紀錄上看不出異常**。
>   備份目錄一律 `0700 postgres:postgres`，落地即加密。
> - **把 `pg_dumpall -g` 的輸出當成一般設定檔。** 它含有**所有帳號的
>   SCRAM 密碼雜湊**，拿去離線暴力破解就是一整套資料庫憑證。這個檔的機敏度
>   **高於 dump 本身**。
> - **在指令列或 `PGPASSWORD` 放密碼。** 同機任何帳號 `ps auxww` 或
>   `cat /proc/<pid>/environ` 就取得。用 `.pgpass`（0600）或 peer 認證。
> - **`rm -rf` 事故現場的舊資料目錄。** 還原失敗、時間點抓錯、發現搞錯庫時，
>   舊目錄是你唯一的回頭路。一律 `mv` 成 `.broken.<時間戳>`，確認新環境穩定
>   一週後再刪。
> - **在正式庫上直接做 PITR。** 正式庫是唯一含有「事故之後正常資料」的副本，
>   在它身上重放 WAL 等於把那些資料一起丟掉，**而它們沒有備份**。
> - **在演練叢集開著 `archive_mode = on`。** 它會把新 timeline 的 WAL 寫進
>   正式庫的歸檔目錄，把兩條歷史混在一起，之後正式的 PITR 會踩到對不上的 WAL。
> - **把備份腳本的失敗只寫進 log 檔。** 沒有人每天讀 `/var/backups/*/logs/`。
>   **失敗沒有告警＝沒有備份**，而且通常在最需要的那天才發現。

**機關情境的具體要求**：

| 要求 | 具體做法 | 星級 |
| --- | --- | --- |
| **個資保護** | 備份落地即用 `age`／GPG 加密；金鑰**不放在同一台機器**；還原演練用的 CSV 中繼檔用完 `shred -u` | ★★★★★ |
| **最小權限** | 備份角色只給 `pg_read_all_data` + `REPLICATION`，**不給 superuser**；還原用的高權限帳號臨時開、用完 `DROP` | ★★★★ |
| **稽核軌跡** | `--manifest-checksums=SHA256` 與備份的 `SHA256SUMS` 一起異地存放，可證明備份未被竄改；演練報告保留三年 | ★★★★ |
| **異地與抗勒索** | 異地端用**只允許寫入不允許刪除**的帳號（或物件儲存的 object lock）；★★★★★ 勒索軟體最先做的事就是刪掉它找得到的備份 | ★★★★★ |
| **測試資料去識別化** | 拿正式備份灌測試環境前，先 `UPDATE` 掉姓名、身分證、電話等欄位。**「只是測試環境」不是外洩的免責理由** | ★★★★★ |
| **法遵** | 保留期限與當事人權利（如刪除請求）要一併考慮 —— 備份裡的個資也是個資，見 [[07-台灣資安法規與個資法]] 與 [[09-資安稽核與符合性檢核]] | ★★★★ |

> [!warning] ★★★★ 備份會讓「刪除」變得不完全
> 當事人行使刪除權、你在正式庫刪了他的資料 —— 但 14 天內的所有 dump、
> 35 天內的所有 basebackup 與 WAL 裡，那筆資料都還在。
> 這不是要你不備份，而是**要有書面的保留期政策**（例如「備份最長保留 35 天，
> 期滿自動銷毀」），並在個資檔案安全維護計畫中寫明。稽核會問這一題。

---

## 速查表

### 備份指令 ★

| 用途 | 指令 | 星級 |
| --- | --- | --- |
| 單庫邏輯備份 | `pg_dump -Fc -Z zstd:9 -f db.dump casedb` | ★★★★ |
| 平行邏輯備份 | `pg_dump -Fd -j 4 -f /backup/dir casedb` | ★★★ |
| **全域物件（必做）** | `pg_dumpall --globals-only -f globals.sql` | ★★★★★ |
| 只要 schema | `pg_dump --schema-only -f schema.sql casedb` | ★★ |
| 實體備份 | `pg_basebackup -D /backup/base -Ft -Xs -c fast --manifest-checksums=SHA256` | ★★★★ |
| 驗證實體備份 | `pg_verifybackup /backup/base` | ★★★★ |
| 即時 WAL 串流 | `pg_receivewal -D /srv/pgwal/stream -S walarchive` | ★★★ |
| 強制切一段 WAL | `psql -c "SELECT pg_switch_wal();"` | ★★ |
| 建命名還原點 | `psql -c "SELECT pg_create_restore_point('before_migrate');"` | ★★★ |

### 還原指令 ★

| 用途 | 指令 | 星級 |
| --- | --- | --- |
| 看封存內容 | `pg_restore -l db.dump` | ★★★ |
| 平行整庫還原 | `pg_restore -j 4 -d casedb db.dump` | ★★★★ |
| 只還原挑選的物件 | `pg_restore -L toc.list -d casedb db.dump` | ★★★★ |
| 先刪再建 | `pg_restore --clean --if-exists -d casedb db.dump` | ★★★ |
| 灌角色 | `psql -f globals.sql postgres` | ★★★★★ |
| 還原後統計 | `vacuumdb -a -z -j 4` | ★★★ |
| 清舊 WAL | `pg_archivecleanup /srv/pgwal/archive 000000010000000300000012` | ★★★★ |
| 合併增量（PG17） | `pg_combinebackup /b/full /b/inc1 -o /new/data` | ★★★ |

### PITR 設定項 ★

| 參數 | 值 | 生效方式 | 星級 |
| --- | --- | --- | --- |
| `wal_level` | `replica` | ★★★★ restart | ★★★ |
| `archive_mode` | `on` | ★★★★ **restart** | ★★★★ |
| `archive_command` | 腳本路徑 | reload | ★★★★★ |
| `archive_timeout` | `5min` | reload | ★★★ |
| `restore_command` | `cp /srv/pgwal/archive/%f %p` | 復原時讀取 | ★★★★★ |
| `recovery_target_time` | ★★★★★ **要帶 `+08`** | 啟動時讀取 | ★★★★★ |
| `recovery_target_action` | `pause`（可反悔）／`promote` | 啟動時讀取 | ★★★★ |
| `recovery_target_inclusive` | `false` ＝ 停在目標前 | 啟動時讀取 | ★★★ |
| `recovery_target_timeline` | `latest`（預設）／`1` | 啟動時讀取 | ★★★★ |
| `recovery.signal` | ★★★★★ **檔案存在才會進入 PITR** | 啟動時檢查 | ★★★★★ |
| `summarize_wal`（PG17） | `on`，增量備份前提 | reload | ★★★ |

### 檔案與路徑 ★

| 路徑 | 內容 | 星級 |
| --- | --- | --- |
| `/var/lib/postgresql/16/main` | Ubuntu `$PGDATA` | ★★★★ |
| `/etc/postgresql/16/main/` | ★★★★ Ubuntu 設定檔，**不在 basebackup 裡** | ★★★★ |
| `/var/lib/pgsql/16/data` | RHEL `$PGDATA`（設定檔也在裡面） | ★★★ |
| `$PGDATA/backup_label` | ★★★★★ 標示從哪個 checkpoint 重放，**不可刪** | ★★★★★ |
| `$PGDATA/recovery.signal` | 進入 PITR 的開關 | ★★★★★ |
| `$PGDATA/postgresql.auto.conf` | `ALTER SYSTEM` 與 recovery 設定寫這裡 | ★★★★ |
| `$PGDATA/pg_wal/` | ★★★★★ 未歸檔的 WAL，**絕對不可 `rm`** | ★★★★★ |
| `/srv/pgwal/archive/*.history` | timeline 分支紀錄，PITR 前必看 | ★★★★ |

### 判斷準則 ★

| 問題 | 答案 | 星級 |
| --- | --- | --- |
| 改了參數要 reload 還是 restart？ | ★★★★ 查 `pg_settings.context`：`sighup` → reload，`postmaster` → restart | ★★★★ |
| 歸檔健康嗎？ | `pg_stat_archiver.failed_count = 0` **且** `last_archived_time` 是幾分鐘內 | ★★★★★ |
| 這份備份能 PITR 嗎？ | 有 `backup_label` + 從它的 START WAL 之後的 WAL 都在 | ★★★★★ |
| WAL 可以清到哪？ | ★★★★★ 清到「最舊那份仍保留的 basebackup 的起始 WAL」為止，多刪一段就斷鏈 | ★★★★★ |
| 備份可用嗎？ | 只有演練 `PASS` 才算數，`pg_verifybackup` 通過不算 | ★★★★★ |
| 該用 dump 還是 basebackup？ | 救單表／跨版本 → dump；整機重建／PITR → basebackup。**兩個都要有** | ★★★★ |

---

## 練習題

> [!question]- 練習 1：把歸檔弄壞，然後修好
> **題目**：在測試機上刻意讓 `archive_command` 失敗，觀察後果並修復。
>
> **參考解答**：
> ```bash
> sudo chmod 000 /srv/pgwal/archive
> sudo -u postgres psql -c "SELECT pg_switch_wal();"
> sleep 30
> sudo -u postgres psql -x -c "SELECT * FROM pg_stat_archiver;"
> ```
> 預期看到：
> ```text
> failed_count    | 4                                     # ★★★★ 開始累積
> last_failed_wal | 000000010000000000000012
> ```
> 同時 `/var/log/postgresql/*.log` 會出現
> `archive command failed with exit code 1`，而**資料庫仍然正常服務** ——
> 這就是危險之處：★★★★ 使用者完全無感，但你的 PITR 能力已經歸零。
>
> 接著觀察 `pg_wal` 開始長大：`watch -n5 'du -sh /var/lib/postgresql/16/main/pg_wal'`。
> 修復：`sudo chmod 700 /srv/pgwal/archive` → PostgreSQL 會**自動重試**並把積壓的
> 段落全部補送，`failed_count` 停止增加、`archived_count` 快速上升。
> ★★★ 注意 `failed_count` **不會自動歸零**，要 `SELECT pg_stat_reset_shared('archiver');`。
> 這也是監控要看「增量」而不是「絕對值」的原因。

> [!question]- 練習 2：只還原一張表，不碰其他表
> **題目**：`casedb` 裡的 `attachments` 表被 `TRUNCATE` 了，其他表都正常。
> 只把這張表從昨天的 dump 還原回來。
>
> **參考解答**：
> ```bash
> pg_restore -l /backup/casedb-20260827.dump | grep -i attachments > /tmp/toc.list
> cat /tmp/toc.list
> ```
> ```text
> 231; 1259 16502 TABLE public attachments app_rw
> 2918; 0 16502 TABLE DATA public attachments app_rw
> 3044; 2606 16511 CONSTRAINT public attachments attachments_pkey app_rw
> ```
> ★★★★ **不要直接 `-d casedb` 灌回正式庫** —— 若表結構在昨天之後改過，
> 你會拿到舊結構或直接失敗。先進暫存庫確認：
> ```bash
> createdb casedb_tmp
> pg_restore -L /tmp/toc.list -d casedb_tmp /backup/casedb-20260827.dump
> psql -d casedb_tmp -c "SELECT count(*) FROM attachments;"
> ```
> ```text
>  count
> -------
>  12844
> ```
> 確認筆數合理後，用 `\copy` 搬過去（比整表 restore 安全，因為不動 DDL）：
> ```bash
> psql -d casedb_tmp -c "\copy attachments TO '/tmp/att.csv' CSV"
> psql -d casedb   -c "\copy attachments FROM '/tmp/att.csv' CSV"
> psql -d casedb   -c "SELECT setval(pg_get_serial_sequence('attachments','id'),
>                                    (SELECT max(id) FROM attachments));"
> ```
> ★★★★ 最後那句 `setval` 極容易被忘記。序列沒重設的話，
> 下一筆 INSERT 會撞主鍵，症狀是**還原當下沒事、幾小時後應用開始噴重複鍵錯誤**。
> 用完 `dropdb casedb_tmp` 並 `shred -u /tmp/att.csv`（含個資）。

> [!question]- 練習 3：算出你的 WAL 最少要留多久
> **題目**：basebackup 每週日 02:00 一次、保留 5 週；dump 每日保留 14 天。
> WAL 歸檔至少要留幾天？寫出你的輪替指令並說明風險。
>
> **參考解答**：
> **答案是 ≥ 35 天，而且要往上加安全邊際到 38～40 天。**
>
> 推導：★★★★★ **WAL 的用途是「從某份 basebackup 往前推進到任意時間點」**，
> 所以你保留的**最舊那份 basebackup（35 天前）之後的所有 WAL 都必須在**。
> 少一段，那份 basebackup 就退化成「只能還原到 35 天前那一刻」的死檔。
>
> 安全邊際的理由：① basebackup 是 02:00 開始、可能跑到 03:30，起始 WAL 在 02:00；
> ② 輪替腳本自己可能失敗一兩天；③ 時區與 `mtime` 的邊界誤差。
>
> ```bash
> # ★★★★ 正確做法：以「最舊那份仍保留的 basebackup」為基準，不是以天數為基準
> OLDEST=$(ls -1d /var/backups/postgresql/base/2* | head -1)
> WAL=$(grep -oE '[0-9A-F]{24}' "$OLDEST/backup_manifest" | head -1)
> pg_archivecleanup /srv/pgwal/archive "$WAL"
> ```
> ★★★★★ **絕對不要用 `find /srv/pgwal/archive -mtime +35 -delete`**。
> 它是以檔案時間為準，跟你的 basebackup 保留策略沒有任何關聯 ——
> 某週 basebackup 失敗、你以為還有 5 份，實際上最舊那 4 份的 WAL 鏈早就被切斷了，
> 而**這件事在你需要還原之前完全不會有任何徵兆**。

---

## 小測驗

Q1. 承辦誤下了一句沒有 `WHERE` 的 `UPDATE`。在 MySQL 你可以用 `mysqlbinlog -vv` 讀出舊值直接補回去。為什麼在 PostgreSQL 這條路完全不存在？你的唯一選項是什麼？

Q2. 這串指令有幾個問題？`PGPASSWORD=S3cret pg_dump -h db01 -U backup casedb > /backup/casedb.sql`（至少講四點）

Q3. 你設好了 `restore_command` 與 `recovery_target_time`，啟動後資料庫正常上線、沒有任何錯誤，但資料停在基礎備份那一刻。最可能漏了什麼？

Q4. `archive_command` 連續失敗三天，但監控沒有任何告警、使用者也沒抱怨。第四天會發生什麼事？請講出具體的錯誤訊息與後果。

Q5. `recovery_target_time = '2026-08-26 15:46:30'` 為什麼是錯的寫法？

Q6. 你在正式庫旁邊開了一套 PITR「時光機」叢集來救資料。為什麼一定要在它的設定裡加 `archive_mode = off`？

Q7. 還原到新機後，`pg_restore` 從頭到尾噴 `ERROR: role "app_rw" does not exist`。原因是什麼？備份腳本該補什麼？

Q8. 你的輪替腳本寫 `find /srv/pgwal/archive -mtime +35 -delete`。為什麼這是一顆定時炸彈？

Q9. `pg_verifybackup` 回報 `backup successfully verified`。可以據此向稽核說「我們的備份可以還原」嗎？

Q10. 這行指令會發生什麼事？`sudo rm -rf /var/lib/postgresql/16/main/pg_wal/*`（磁碟已經 100% 滿、資料庫已經 PANIC 停止）

> [!question]- 測驗答案
> **Q1.** 因為 **★★★★★ binlog 是邏輯日誌、WAL 是實體日誌**，兩者記的東西層級不同。
> MySQL 的 ROW 格式 binlog 記的是「這一列的每個欄位，改前是什麼、改後是什麼」，
> 所以 `mysqlbinlog --base64-output=DECODE-ROWS -vv` 印得出 `@1=100231 @3='張OO'`。
> PostgreSQL 的 WAL 記的是「檔案 16421 的第 5138 個 block，第 27 格的 tuple 標記為死、
> 在第 91 格寫入新 tuple」—— **裡面沒有任何欄位語意**，你就算把 WAL 逐 byte 讀完
> 也還原不出「那筆案件原本的 status 是什麼」。
> `pg_waldump` 能解出來的也是這種實體描述，在事故現場毫無幫助。
> **唯一選項**：拿基礎備份 + WAL 做 PITR，重放到誤操作前一秒，
> 得到**一整套當時的資料庫**，再用 SQL 從那套庫把正確的值 JOIN 回正式庫。
> 這就是為什麼「PostgreSQL 沒開 WAL 歸檔 ＝ 沒有救資料的能力」。
> 見「為什麼 PostgreSQL 救資料一定要還原一整套」與「完整實戰範例」。
>
> **Q2.** 至少五個問題：
> ① **★★★★★ `PGPASSWORD` 在環境變數裡**。同機任何帳號
> `cat /proc/<pid>/environ` 就拿到密碼，備份跑多久就曝露多久。改用 `.pgpass`（0600）。
> ② **★★★★ 沒有 `-Fc`**。純文字格式**不能挑物件還原**、不能 `-j` 平行還原，
> 50 GB 的庫還原要 5 小時而不是 1 小時。
> ③ **★★★★ 用 `>` 重導向而不是 `--file=`**。`pg_dump` 中途失敗時 shell 已經建好檔案，
> 你會拿到一個**大小看起來很正常的半截檔**，而且 exit code 藏在 pipeline 裡。
> ④ **★★★★★ 沒有 `pg_dumpall --globals-only`**。角色沒備份，還原時整片
> `role does not exist`（見 Q7）。
> ⑤ 還有：沒有 `--lock-wait-timeout`（碰到 DDL 會無聲卡住幾小時）、
> 輸出未加密（一份完整個資明文落地）、沒有備份 `/etc/postgresql/`。
> 見「`pg_dump`：每個旗標為什麼要加」。
>
> **Q3.** **★★★★★ 漏了 `touch $PGDATA/recovery.signal`。**
> PostgreSQL 判斷「要不要進入歸檔復原模式」看的是**這個檔案存不存在**，
> 不是看你有沒有寫 `recovery_target_*`。沒有這個檔，它把資料目錄當成一般啟動，
> 只做崩潰復原，**把你所有 `recovery_target_*` 參數完全忽略**，然後正常上線。
> **最惡劣的是它不會報錯**，你會以為還原成功。
> 驗證方式：日誌第一行必須看到
> `LOG: starting point-in-time recovery to 2026-08-26 15:46:30+08`。
> 沒有這一行就是沒進 PITR，停掉、重新展開備份、建 `recovery.signal` 再來。
> ★★★ 另一個可能：你把設定寫進 `/etc/postgresql/.../recovery.conf` ——
> **PG12 起已經沒有 `recovery.conf` 了**，那個檔會被完全忽略。
> 見 PITR 流程步驟【6】。
>
> **Q4.** 第四天磁碟會被 `pg_wal` 塞滿，然後：
> ```text
> PANIC:  could not write to file "pg_wal/xlogtemp.31544": No space left on device
> LOG:  server process (PID 31544) was terminated by signal 6: Aborted
> ```
> **整個資料庫當場停止服務**，而且因為磁碟是滿的，**你連重新啟動都啟不起來**。
> 機制：`archive_command` 失敗時 PostgreSQL **不會拒絕寫入、不會降級、不會警告使用者**，
> 它只是把歸檔不掉的 WAL 段全部留在 `pg_wal/`，16 MB 一段一直堆。
> 中等寫入量的機關系統一天堆 20～60 GB 很常見。
> **★★★★★ 更糟的是這三天你的 PITR 能力已經是零**，若這期間發生誤刪，
> 你只能還原到三天前。
> 所以 `pg_stat_archiver.failed_count`（看**增量**）與 `pg_wal` 目錄大小
> **必須進監控告警**。見〈開啟 WAL 歸檔〉的 danger callout 與排查步驟【4】。
>
> **Q5.** 因為**沒有帶時區偏移**。這個字串會用伺服器的 `TimeZone` 參數解讀，
> 而**還原目標機非常常見是 UTC**（雲端映像、容器映像、最小化安裝的預設值）。
> 結果就是 ★★★★★ **你以為停在 15:46:30，實際停在 23:46:30**，
> 誤操作根本沒被排除掉，你辛苦還原兩小時，資料還是壞的。
> 正確寫法：`recovery_target_time = '2026-08-26 15:46:30+08'`。
> ★★★ 驗證：復原完成後看日誌那行
> `recovery stopping before commit of transaction 88412, time 2026-08-26 15:47:02.881+08`，
> 時間必須落在你預期的範圍。
> ★★★ 相關但不同的一個坑：機器時間本身不準（NTP 沒同步），
> 那你連「誤操作發生在幾點」都不知道，見 [[28-時間同步NTP與chrony]]。
>
> **Q6.** 因為時光機叢集完成 PITR 並 promote 之後，**timeline 會從 1 前進到 2**。
> 若它的 `archive_mode` 是 `on`，它會開始把 **timeline 2 的 WAL 與
> `00000002.history` 寫進你正式庫的歸檔目錄**。
> **★★★★★ 後果**：歸檔目錄裡混了兩條互不相容的歷史。
> 之後你要從正式庫（仍在 timeline 1）做 PITR 時，
> `recovery_target_timeline = 'latest'` 會把你帶到 timeline 2 ——
> 也就是那台臨時叢集的資料 —— 或是在重放時撞上對不上的 WAL 而失敗。
> 你會在事故現場多出一個沒人想得通的問題。
> ★★★ 同樣理由，演練叢集也要改 `port`，避免搶佔 5432。
> 見「完整實戰範例」步驟【3】與 `pg-pitr-drill.sh`。
>
> **Q7.** 因為 **`pg_dump` 的範圍只有「一個 database 裡面的物件」**，
> 角色（role）、表空間、資料庫層級設定屬於**叢集層級的全域物件**，
> `pg_dump` 完全不碰。所以每一句 `ALTER TABLE ... OWNER TO app_rw` 都找不到那個角色。
> **要補的是 `pg_dumpall --globals-only`**，而且還原順序是
> **先 `psql -f globals.sql postgres`，再 `pg_restore`** —— 反過來沒有用。
> ★★★★★ 這個檔含有**所有帳號的 SCRAM 密碼雜湊**，機敏度比 dump 本身還高，
> 落地必須立刻加密（本篇腳本用 `age` 加密後 `shred -u` 明文）。
> ★★★ 驗證備份有效：`grep -c '^CREATE ROLE' globals.sql` 要 > 0；
> 腳本裡就有這一行檢查，因為「檔案存在但內容是空的」是真實發生過的事。
> 見「`pg_dumpall --globals-only`」與常見錯誤表第 4 列。
>
> **Q8.** 因為它**以檔案時間為準，跟你的 basebackup 保留策略沒有任何關聯**。
> ★★★★★ WAL 的唯一用途是「從某份 basebackup 往前推進」，
> 所以判斷基準必須是「**最舊那份仍保留的 basebackup 的起始 WAL**」。
> **爆炸情境**：你保留 5 週 basebackup、WAL 留 35 天，看起來剛好。
> 但某週日 basebackup 因為磁碟滿而失敗，你的最舊備份變成 42 天前的那份 ——
> 它需要的 WAL 早在一週前就被 `-mtime +35` 刪光了。
> **那份 basebackup 從此只能還原到 42 天前那一刻**，中間全部接不起來。
> ★★★★★ 而這件事**在你需要還原之前完全不會有任何徵兆**，
> 監控看不出來、腳本 exit 0、檔案都在。
> 正解是用 `pg_archivecleanup` 搭配最舊 basebackup 的 `backup_manifest`
> 推算出安全的清理起點，找不到參照時**寧可不清**。見練習 3 與 `rotate()` 函式。
>
> **Q9.** **不可以。** `pg_verifybackup` 比對的是 `backup_manifest` 裡的
> 檔案清單與 checksum，它只能證明**備份沒有在複製或搬運途中損壞**。
> **通過卻完全不能用的情況**：
> ① 備份的是一套本來就有問題的資料庫（例如索引早就損毀）；
> ② 檔案完好，但目標機缺 `postgis` 之類的擴充套件，還原起來就是不能用；
> ③ 檔案完好，但 WAL 鏈斷了，只能還原到基礎備份那一刻；
> ④ 全部都對，但還原花了 6 小時，而服務水準承諾是 2 小時 —— 技術成功、業務失敗。
> ★★★★★ 要能對稽核說「備份可以還原」，必須做到 **L4：在獨立叢集實際還原起來、
> 比對每張表的列數、比對角色數、量到真實 RTO、留下書面演練報告**。
> 這正是 `pg-pitr-drill.sh` 每月自動產出的東西。
> 見「還原演練：本篇的核心」的 L1～L5 表。
>
> **Q10.** ★★★★★ **這是把「服務中斷」升級成「永久資料遺失」的一行指令。**
> `pg_wal/` 裡放的是**已經回報給應用「交易成功」、但資料檔還沒寫入的交易**。
> 資料庫啟動時要靠重放這些 WAL 才能把它們補進資料檔。刪掉之後：
> ```text
> PANIC:  could not open file "pg_wal/000000010000000300000091": No such file or directory
> ```
> 資料庫**仍然起不來**（你的問題一點都沒解決），而且現在連還原路徑都變窄了 ——
> 你只能回頭找備份，而剛才刪掉的是備份裡沒有的最新交易。
> **正確順序**：① 先從**別的地方**空出磁碟（清 `/var/log`、刪舊 dump、擴 LV，
> 見 [[15-磁碟分割與掛載]]）讓資料庫能啟動；
> ② 起來之後查 `pg_replication_slots` 有沒有 `active = f` 的 slot 在扣留 WAL，有就 drop；
> ③ 修好 `archive_command`；
> ④ 等 `failed_count` 停止增加、積壓補送完，才用 `pg_archivecleanup` 清。
> 見排查步驟【4】與〈安全性注意事項〉。

## 延伸閱讀

- [[04-PostgreSQL-設定檔與pg_hba]] —— `archive_mode` 要 restart、`archive_command` 只要 reload，這個差別與 `pg_settings.context` 的判讀方式在那篇講得最完整；備份角色的 `replication` 認證條目也在那裡
- [[05-MySQL-備份與還原]] —— 同一件事在 MySQL 怎麼做。**特別建議對照 binlog PITR 與本篇 WAL PITR 的差異**，那是兩套資料庫在維運上最大的分歧點
- [[07-PostgreSQL-複寫與高可用]] —— 本篇建立的基礎備份與 WAL 歸檔，正好就是搭建 standby 的材料；也解釋為什麼「有 standby 不等於有備份」
- [[03-備份策略與還原演練]] —— 3-2-1 原則、異地與不可變備份、restic / borg 的操作、演練制度的一般性做法，本篇不重複的部分都在那裡
- [[08-PostgreSQL-安全強化]] —— 備份檔的加密、金鑰保管、稽核軌跡要跟整體強化措施一起規劃
- [[03-系統監控與告警]] —— 把 `pg_stat_archiver.failed_count`、`pg_wal` 大小、備份腳本 exit code 接上告警的實作
- [[03-範例-Nuxt與PostgreSQL]] —— 實際專案裡這套備份怎麼放進部署流程
- PostgreSQL 官方文件：連續歸檔與 PITR <https://www.postgresql.org/docs/17/continuous-archiving.html>
- PostgreSQL 官方文件：`pg_dump` <https://www.postgresql.org/docs/17/app-pgdump.html>
- PostgreSQL 官方文件：`pg_basebackup` <https://www.postgresql.org/docs/17/app-pgbasebackup.html>
