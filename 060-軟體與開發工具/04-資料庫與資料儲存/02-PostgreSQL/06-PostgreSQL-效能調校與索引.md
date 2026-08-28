---
title: "PostgreSQL 效能調校與索引"
desc: "shared_buffers 與 work_mem 的記憶體預算、EXPLAIN (ANALYZE, BUFFERS) 判讀、六種索引選型、CREATE INDEX CONCURRENTLY 與 autovacuum 膨脹防治"
aliases: [explain, vacuum, index, autovacuum, shared_buffers, work_mem, pg_stat_statements, CREATE INDEX CONCURRENTLY]
tags: [群組/軟體與開發工具, 服務/postgresql, 主題/效能]
category: 資料庫與資料儲存
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[04-PostgreSQL-設定檔與pg_hba]]", "[[03-psql-操作與常用指令]]", "[[03-SQL基礎操作]]"]
updated: 2026-08-28
---

# PostgreSQL 效能調校與索引

> [!abstract] 這篇你會學到
> - 為一台 LXMP 共存機**算出一張 PostgreSQL 記憶體預算表**，並說得出 `work_mem` 為什麼**不能**用「乘以 max_connections」這個 MySQL 思路去估
> - 讀懂 `EXPLAIN (ANALYZE, BUFFERS)` 的輸出：**估計列數 vs 實際列數差幾倍**、`Rows Removed by Filter`、`Buffers: shared read` 各代表哪一種病
> - 從 B-tree／GIN／GiST／BRIN／Hash／SP-GiST 六種索引裡**挑對那一種**，並會用部分索引、`INCLUDE` 覆蓋索引與運算式索引把巨大索引縮小
> - ★★★★ 在**線上營運中的資料表**建索引而不鎖死全站 —— `CREATE INDEX CONCURRENTLY` 的三個陷阱（不能在交易區塊內、失敗留下 `INVALID` 索引、會被長交易卡住）
> - ★★★★★ 看懂 table bloat 與 **XID wraparound**：為什麼「autovacuum 追不上」最後會讓整個資料庫**拒絕寫入**，以及在還來得及的時候怎麼救
> - 用 `pg_stat_statements` 撈出 Top 10 慢查詢，並用一支 `pg-tune-check.sh` 驗收調校結果、**改壞了 3 步內回滾**

## 前置知識

- [[04-PostgreSQL-設定檔與pg_hba]] —— ★★★★ **本篇只講「該設成多少」，「設定檔在哪、改完 reload 還是 restart」全部在那一篇**，不重述
- [[03-psql-操作與常用指令]] —— `\d`、`\di+`、`\timing`、`\x` 這些本篇會一直用到
- [[03-SQL基礎操作]] —— ★★★ **SQL 語法與索引的基本概念在那一篇**，本篇假設你已經知道什麼叫 JOIN、什麼叫 WHERE
- [[04-MySQL-設定檔與調校]] —— 對照組。同一件事（編記憶體預算、抓慢查詢）在 MySQL 怎麼做
- [[04-效能瓶頸排查方法論]] —— ★★★ **先確定瓶頸真的在資料庫**再打開這一篇
- [[01-htop-操作與判讀]] —— 看 RSS 與 swap 的基本功

---

## 觀念說明

### PostgreSQL 與 MySQL 的效能問題「長得不一樣」

如果你的手上有 MySQL 的經驗，先把這張表看完再往下讀。**兩套資料庫的痛點根本不在同一個地方**：

| 議題 | MySQL / InnoDB | PostgreSQL | 差異的後果 |
| --- | --- | --- | --- |
| 主要快取 | `innodb_buffer_pool_size`，通常吃 RAM 的 **70~80%** | `shared_buffers`，只吃 RAM 的 **25%** | ★★★★ 照抄 MySQL 的比例會**變慢**，見下一節 |
| 排序／雜湊記憶體 | `sort_buffer_size`，**每連線一份** | `work_mem`，**每個執行計畫節點一份** | ★★★★ 最壞情況的算法完全不同 |
| 舊版本資料 | 存在 undo log／rollback segment，**表本身不會膨脹** | ★★★★★ 舊版本 **就躺在資料表裡**，靠 VACUUM 回收 | PostgreSQL 有 **bloat（膨脹）** 這個 MySQL 沒有的病 |
| 交易 ID | 64-bit，不會用完 | ★★★★★ 32-bit，**會繞回**（wraparound） | 追不上就整庫拒絕寫入，MySQL 沒有這個問題 |
| 統計值更新 | InnoDB 自動抽樣，可設 persistent | 靠 **ANALYZE**（autovacuum 順便做） | 統計值過期 → 計畫選錯 → 一夜之間變慢 |
| 慢查詢入口 | `slow_query_log` + `mysqldumpslow` | `pg_stat_statements` + `log_min_duration_statement` | ★★★ PostgreSQL 的 `pg_stat_statements` 要 **restart** 才裝得起來 |
| 找出計畫 | `EXPLAIN FORMAT=JSON` | `EXPLAIN (ANALYZE, BUFFERS)` | PostgreSQL 的 `BUFFERS` 資訊比 MySQL 豐富得多 |

> [!note] 一句話總結
> **MySQL 的效能調校在「記憶體」，PostgreSQL 的效能調校在「維護」。**
> 一台調得差不多的 PostgreSQL，八成的線上事故不是參數設錯，
> 是 ★★★★★ **autovacuum 追不上** 或 ★★★★ **少了一個索引**。

### PostgreSQL 是「雙層快取」，不是單層

這是最多人從 MySQL 轉過來時踩的第一個坑。

```text
         ┌───────────────────── 應用（Laravel / Nuxt）─────────────────┐
                                       │
                                       ▼
  ┌──────────────────────── postgres 行程 ────────────────────────────┐
  │                                                                   │
  │   ① shared_buffers   （預設 128 MB，建議 RAM 的 25%）             │
  │      ████████████                                                 │
  │      PostgreSQL 自己管理的共享緩衝區                               │
  │      ★★★ 命中 → 完全不碰 OS，最快                                 │
  └───────────────────────────────│───────────────────────────────────┘
                                  │ miss
                                  ▼
  ┌──────────────────── Linux OS page cache ──────────────────────────┐
  │      ████████████████████████████████                             │
  │      ★★★★ PostgreSQL 【不繞過】OS 快取（沒有 O_DIRECT）           │
  │      這一層通常比 shared_buffers 大得多                            │
  └───────────────────────────────│───────────────────────────────────┘
                                  │ miss
                                  ▼
                            實體磁碟 I/O（慢 100~1000 倍）
```

所以：

- ★★★★ **把 `shared_buffers` 設成 RAM 的 80% 會讓效能變差**。因為同一份資料會在
  `shared_buffers` 和 OS page cache 裡各存一份（double buffering），
  你付了兩倍記憶體卻沒有兩倍效果，而且留給 OS 的餘裕被吃掉，**排序與連線用的記憶體反而不夠**。
- ★★★ `effective_cache_size` **不配置任何記憶體**，它只是告訴查詢規劃器
  「你估計整台機器大約有多少 RAM 可以拿來當資料快取」。設得太小 → 規劃器以為讀磁碟很貴 →
  **不敢用索引，改用全表掃描**。這是「明明有索引卻不走索引」的常見原因之一。

### MVCC 與膨脹：PostgreSQL 特有的病

```text
  UPDATE users SET email='new@x.tw' WHERE id=7;

  之前：                          之後：
  ┌──────────────────┐            ┌──────────────────┐
  │ id=7 email=old   │            │ id=7 email=old   │ ← 舊版本【還在表裡】
  │                  │    ──►     │   xmax=1234      │   dead tuple（死行）
  │                  │            ├──────────────────┤
  │                  │            │ id=7 email=new   │ ← 新版本，接在後面
  └──────────────────┘            └──────────────────┘

  ★★★★★ PostgreSQL 的 UPDATE 是【寫一筆新的 + 標記舊的死掉】，不是就地修改。
         DELETE 也只是標記，空間【不會自己還給作業系統】。

  回收這些死行的，只有 VACUUM。
  VACUUM 跑不動 → 死行越積越多 → 表越來越大 → 每次全表掃描讀更多頁
                → 更慢 → 更容易逾時 → 更多長交易 → VACUUM 更跑不動  ★★★★★ 惡性循環
```

> [!danger] ★★★★★ 膨脹失控的三個階段（機關常見的「這台越來越慢」）
> ```
> 【階段一】表大小是實際資料的 1.5 倍 → 查詢慢 30%，還沒人抱怨
> 【階段二】表大小是實際資料的 5 倍   → 索引也跟著膨脹，記憶體吃不下熱資料
>                                       尖峰時全站間歇性逾時
> 【階段三】age(datfrozenxid) 逼近 2 億 → autovacuum 全力搶救，I/O 打滿
>          再逼近 21 億 → 【整個資料庫拒絕接受任何寫入】
>            ERROR: database is not accepting commands that assign new
>            transaction IDs to avoid wraparound data loss in database "app"
> ```
> 階段三只能停機、進單使用者模式做 `VACUUM`，**視資料量可能要數小時**。
> ★★★★★ **這是可以完全避免的事故**，代價只是把 `n_dead_tup` 與 `age(datfrozenxid)` 接進監控。

### 調校的三個階段（順序不能顛倒）

| 階段 | 做什麼 | 為什麼是這個順序 |
| --- | --- | --- |
| **【1】不要死掉** ★★★★ | 編記憶體預算、限制 `max_connections`、確認不會 OOM | 穩定 > 快。會被 OOM killer 殺掉的快沒有意義 |
| **【2】不要膨脹** ★★★★★ | autovacuum 調得追得上、監控 `n_dead_tup` 與 XID age | PostgreSQL 專屬。這一步跳過，前後兩步做再好都會被吃掉 |
| **【3】不要慢** ★★★★ | `pg_stat_statements` 抓 Top 10 → `EXPLAIN (ANALYZE, BUFFERS)` → 補索引 | **一條沒有索引的查詢，比任何參數都傷** |

> [!tip] ★★★ 參數調校的天花板比你想的低
> 把 `shared_buffers` 從 128 MB 調到 4 GB，通常帶來**數倍**改善；
> 幫一條全表掃描的查詢加上對的索引，常常是**數百倍到數千倍**。
> 所以做完階段【1】【2】保命之後，**直接跳去階段【3】**，別在參數上鑽牛角尖。

---

## 基礎設定

### 先確認「實際值」，不是你以為的值

★★★★ 調校的第一個習慣：**永遠不要相信設定檔**。設定檔可能被 `ALTER SYSTEM`
（`postgresql.auto.conf`）覆蓋、可能改完沒 reload、可能被 `ALTER DATABASE` 或
`ALTER ROLE` 的單獨設定蓋掉。唯一的真相是資料庫自己說的。

```bash
sudo -u postgres psql -c "SELECT name, setting, unit, source, pending_restart
  FROM pg_settings
  WHERE name IN ('shared_buffers','work_mem','maintenance_work_mem',
                 'effective_cache_size','max_connections','random_page_cost');"
```

預期輸出：

```text
         name         | setting | unit |       source       | pending_restart
----------------------+---------+------+--------------------+-----------------
 effective_cache_size | 524288  | 8kB  | configuration file | f
 max_connections      | 100     |      | default            | f    # ★★★ default = 沒人改過
 maintenance_work_mem | 65536   | kB   | default            | f
 random_page_cost     | 4       |      | default            | f
 shared_buffers       | 16384   | 8kB  | configuration file | t    # ★★★★ t = 改了但還沒重啟！
 work_mem             | 4096    | kB   | default            | f
```

三個必看的欄位：

| 欄位 | 意義 | 星級 |
| --- | --- | --- |
| `setting` + `unit` | ★★★ **`shared_buffers` 的單位是 8 kB 的頁數，不是 MB**。`16384 × 8 kB = 128 MB` | ★★★ |
| `source` | 值從哪來：`default` / `configuration file` / `database` / `user` / `session` | ★★★ |
| `pending_restart` | ★★★★ **`t` 代表設定檔已改但還沒重啟，現在跑的是舊值** | ★★★★ |

要人看得懂的單位，用 `pg_size_pretty()`：

```bash
sudo -u postgres psql -c "SELECT name, setting::bigint * 8192 AS bytes,
  pg_size_pretty(setting::bigint * 8192) AS pretty
  FROM pg_settings WHERE name IN ('shared_buffers','wal_buffers','effective_cache_size');"
```

預期輸出：

```text
         name         |   bytes    | pretty
----------------------+------------+---------
 effective_cache_size | 4294967296 | 4096 MB
 shared_buffers       |  134217728 | 128 MB   # ★★★★ 還是原廠預設，一定要改
 wal_buffers          |    4194304 | 4096 kB
```

> [!warning] ★★★★ `SHOW shared_buffers;` 會騙你嗎？
> 不會，`SHOW` 顯示的是**目前執行中的值**，跟 `pg_settings.setting` 一致。
> 會騙你的是 `postgresql.conf` —— 那只是「下次啟動想要的值」。
> **驗收永遠用 `pg_settings`，因為只有它有 `pending_restart` 這一欄。**

### 記憶體預算表（本節的核心產出）

一台 8 GB 的 LXMP 共存機（Nginx + PHP-FPM + PostgreSQL + Redis），預算這樣編：

```text
┌─────────────────────── 8192 MB 實體記憶體 ────────────────────────┐
│                                                                   │
│  OS + 保留            1024 MB   ★★★★ 不能省，OOM killer 就住這   │
│  Nginx                  96 MB                                     │
│  Redis (maxmemory)     256 MB                                     │
│  PHP-FPM  40 × 48 MB  1920 MB   ← 見 [[02-PHP-FPM設定與Pool調校]] │
│  ────────────────────────────                                     │
│  剩給 PostgreSQL      4896 MB                                     │
│                                                                   │
│  其中：                                                            │
│    shared_buffers               2048 MB  （全機 RAM 的 25%）      │
│    每連線基礎開銷  60 × 8 MB     480 MB  ★★★ 連線本身就要錢      │
│    work_mem 保留區              1024 MB  ★★★★ 見下方算法          │
│    maintenance_work_mem × 4      512 MB  （3 autovacuum + 1 手動） │
│    wal_buffers + 其他            ~64 MB                            │
│  ────────────────────────────                                     │
│    小計                        ~4128 MB   餘裕 768 MB  ✅          │
│                                                                   │
│  effective_cache_size = 5 GB  ★★★ 這一項【不佔任何記憶體】        │
│                               它只是給規劃器看的數字               │
└───────────────────────────────────────────────────────────────────┘
```

★★★★ **`work_mem` 的最壞情況算法跟 MySQL 完全不同**，這是本篇最容易被誤解的一點：

```text
MySQL 的 sort_buffer_size：  最壞 = sort_buffer_size × max_connections
                             （每條連線最多一份，好算）

PostgreSQL 的 work_mem：     最壞 = work_mem × (每個查詢的排序/雜湊節點數)
                                        × (1 + max_parallel_workers_per_gather)
                                        × 並發查詢數
                             ★★★★ 一個 5-way JOIN + GROUP BY + ORDER BY 的查詢
                                   可能同時開【8 個以上】work_mem！
```

實務上的判斷準則：

| 情境 | `work_mem` 建議 | 星級 |
| --- | --- | --- |
| 一般 OLTP（Laravel／Nuxt 後端） | `RAM 的 25% ÷ max_connections ÷ 4`，8 GB / 100 連線約 **8~16 MB** | ★★★★ |
| 報表／月結批次 | **不要調全域**，在該 session 裡 `SET work_mem = '256MB';` | ★★★★ |
| 已知有大量 `Sort` 落到磁碟 | 先看 `EXPLAIN` 的 `Sort Method: external merge Disk: NNNkB`，調到剛好蓋過去 | ★★★ |

> [!tip] ★★★★ 報表查詢不要調全域 `work_mem`
> ```sql
> -- 只影響這一條連線，離線就恢復，最壞情況可控
> SET LOCAL work_mem = '256MB';
> SELECT ... 巨大的月結報表 ...;
> ```
> `SET LOCAL` 只在**目前交易**內有效，交易結束自動還原 —— 比 `SET` 更安全。

### 一份可以照抄的起手式設定

★★★★ **不要直接改 `postgresql.conf`**（`apt upgrade` 會問你要不要覆蓋），
用 `conf.d` 的獨立檔案。做法與理由見 [[04-PostgreSQL-設定檔與pg_hba]]，這裡只放值。

```bash
sudo tee /etc/postgresql/16/main/conf.d/zz-tuning.conf > /dev/null <<'EOF'
# ============================================================
# zz-tuning.conf — 8 GB LXMP 共存機（PostgreSQL 16/17）
# 修改者：資訊室  日期：2026-08-28
# ★★★★ 每次改這一份都要在 git 留紀錄，並跑 pg-tune-check.sh 驗收
# ============================================================

# ---- 連線 ----
max_connections = 100                 # ★★★★ 改這一項要 restart
superuser_reserved_connections = 3    # 留給 DBA 救火用

# ---- 記憶體 ----
shared_buffers = 2GB                  # ★★★★ RAM 的 25%，改這一項要 restart
effective_cache_size = 5GB            # ★★★ 只給規劃器看，不配置記憶體
work_mem = 12MB                       # ★★★★ 每個排序/雜湊節點一份，不是每連線
maintenance_work_mem = 512MB          # VACUUM / CREATE INDEX 用
autovacuum_work_mem = -1              # -1 = 沿用 maintenance_work_mem

# ---- 磁碟成本（SSD/NVMe）----
random_page_cost = 1.1                # ★★★★ 預設 4.0 是給機械硬碟的，SSD 要調
seq_page_cost = 1.0
effective_io_concurrency = 200        # ★★★ SSD 建議 200；PG16/17 預設只有 1
maintenance_io_concurrency = 200

# ---- WAL 與 checkpoint ----
wal_compression = lz4                 # ★★★ 減少 WAL 量，CPU 成本很低
min_wal_size = 1GB
max_wal_size = 4GB                    # ★★★ 太小會逼出頻繁 checkpoint，I/O 尖刺
checkpoint_timeout = 15min
checkpoint_completion_target = 0.9

# ---- 平行查詢 ----
max_worker_processes = 4              # ★★★ 通常設成 CPU 核心數，restart
max_parallel_workers = 4
max_parallel_workers_per_gather = 2
max_parallel_maintenance_workers = 2  # CREATE INDEX 會用到

# ---- 統計與規劃 ----
default_statistics_target = 100       # 欄位資料很偏斜時個別調到 500~1000
track_io_timing = on                  # ★★★★ EXPLAIN (BUFFERS) 的 I/O 時間靠它

# ---- autovacuum（★★★★★ PostgreSQL 最重要的一段）----
autovacuum = on                       # ★★★★★ 永遠不要關
autovacuum_max_workers = 3            # 改這一項要 restart
autovacuum_naptime = 30s
autovacuum_vacuum_scale_factor = 0.05    # 預設 0.2 對大表太鬆
autovacuum_vacuum_threshold = 50
autovacuum_analyze_scale_factor = 0.02   # 預設 0.1
autovacuum_vacuum_cost_delay = 2ms
autovacuum_vacuum_cost_limit = 1000      # ★★★★ 預設 -1（=200），SSD 上太保守
log_autovacuum_min_duration = 250ms      # ★★★ 讓 autovacuum 留下軌跡

# ---- 慢查詢日誌 ----
log_min_duration_statement = 1000     # ★★★★ 超過 1 秒就記，別設 0
log_lock_waits = on
log_temp_files = 10MB                 # ★★★ work_mem 不夠時會在這裡留線索
log_checkpoints = on
EOF
```

套用（哪些要 reload、哪些要 restart，見下一段）：

```bash
sudo -u postgres /usr/lib/postgresql/16/bin/postgres \
  -D /var/lib/postgresql/16/main -C shared_buffers   # 先語法驗證
sudo systemctl restart postgresql@16-main
```

預期輸出：

```text
2GB
```

> [!warning] ★★★★ 這些參數改完必須 **restart**，reload 沒有用
> `shared_buffers`、`max_connections`、`max_worker_processes`、`autovacuum_max_workers`、
> `wal_buffers`、`huge_pages`、`shared_preload_libraries`。
> 判斷方式不是背誦，是查：
> ```bash
> sudo -u postgres psql -c "SELECT name, context FROM pg_settings
>   WHERE name IN ('shared_buffers','work_mem','autovacuum_naptime');"
> ```
> ```text
>        name        |  context
> -------------------+------------
>  autovacuum_naptime| sighup     # ★ reload 就好
>  shared_buffers    | postmaster # ★★★★ 一定要 restart
>  work_mem          | user       # ★ 連 SET 都可以，立即生效
> ```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ★★★ 三個差異，抄錯路徑會找不到檔案：
>
> ```bash
> # 路徑：RHEL 系沒有 /etc/postgresql/，設定檔就在資料目錄裡
> /var/lib/pgsql/16/data/postgresql.conf
> /var/lib/pgsql/16/data/conf.d/            # ★★★ 這個目錄【要自己建】並在主檔加 include_dir
>
> # 服務名（PGDG 套件庫）
> sudo systemctl restart postgresql-16
> sudo systemctl reload  postgresql-16
>
> # 執行檔
> /usr/pgsql-16/bin/postgres  -D /var/lib/pgsql/16/data -C shared_buffers
> ```
>
> ★★★★ RHEL 系預設 **SELinux 是 enforcing**。把資料目錄或 WAL 歸檔目錄搬到
> `/data` 這種非標準位置，`postgres` 會啟動失敗且錯誤訊息看起來像權限問題：
> ```bash
> sudo semanage fcontext -a -t postgresql_db_t "/data/pgdata(/.*)?"
> sudo restorecon -Rv /data/pgdata
> sudo ausearch -m avc -ts recent | tail   # ★★★ 確認有沒有被 SELinux 擋
> ```
>
> ★★★ 主檔要自己加上這一行才會讀 `conf.d/`：
> ```ini
> include_dir = 'conf.d'
> ```

---

## 進階設定與調校

### 一、★★★★ 讀懂 `EXPLAIN (ANALYZE, BUFFERS)`

這是本篇最重要的技能。**沒有它，補索引就是猜。**

```bash
sudo -u postgres psql -d appdb -c "EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
  SELECT o.id, o.total, u.email
  FROM orders o JOIN users u ON u.id = o.user_id
  WHERE o.created_at >= '2026-08-01' AND o.status = 'paid'
  ORDER BY o.total DESC LIMIT 20;"
```

一份「有病」的輸出長這樣：

```text
 Limit  (cost=48219.3..48219.4 rows=20 width=44)
        (actual time=2841.115..2841.121 rows=20 loops=1)
   Buffers: shared hit=1204 read=38116                       # ★★★★ read 很大 = 真的去讀磁碟
   ->  Sort  (cost=48219.3..48283.9 rows=25840 width=44)
             (actual time=2841.113..2841.116 rows=20 loops=1)
         Sort Key: o.total DESC
         Sort Method: external merge  Disk: 31048kB          # ★★★★ 排序爆掉落磁碟
         ->  Hash Join  (cost=1204.0..47532.1 rows=25840 width=44)
                        (actual time=18.221..2795.410 rows=24918 loops=1)
               Hash Cond: (o.user_id = u.id)
               ->  Seq Scan on public.orders o               # ★★★★★ 全表掃描
                     (cost=0..45118.0 rows=25840 width=24)
                     (actual time=0.041..2701.882 rows=24918 loops=1)
                     Filter: ((o.created_at >= '2026-08-01') AND (o.status='paid'))
                     Rows Removed by Filter: 3175082         # ★★★★★ 掃了 320 萬列丟掉 317 萬
                     Buffers: shared read=37904
 Planning Time: 0.412 ms
 Execution Time: 2843.980 ms                                 # ★★★★ 2.8 秒
```

**判讀順序（由內而外，先看最深的節點）**：

| 看什麼 | 健康 | 有病 | 星級 |
| --- | --- | --- | --- |
| `Seq Scan` + 巨大的 `Rows Removed by Filter` | 小表全掃沒關係 | ★★★★★ **這裡缺索引**，本例就是 | ★★★★★ |
| `rows=` 估計 vs `actual rows=` | 差在 **10 倍以內** | ★★★★ 差 **100 倍以上 → 統計值過期**，跑 `ANALYZE` | ★★★★ |
| `Sort Method` | `quicksort  Memory: NNkB` | ★★★★ `external merge  Disk: NNkB` → `work_mem` 不夠 | ★★★★ |
| `Buffers: shared hit / read` | `hit` 佔絕大多數 | ★★★ `read` 很大 → `shared_buffers` 太小或資料真的太大 | ★★★ |
| `loops=N` | `N=1` | ★★★ `N` 很大且內層有 Seq Scan → **N+1 型災難** | ★★★ |
| `Execution Time` vs `Planning Time` | 執行遠大於規劃 | ★★ 規劃時間也很久 → 表／分割區太多、統計值太細 | ★★ |

★★★★ **`Rows Removed by Filter` 是 PostgreSQL 送給你的答案卡**：
它明白告訴你「我讀了 320 萬列，只有 2.5 萬列有用」。這就是索引該補的地方。

補上索引之後：

```bash
sudo -u postgres psql -d appdb -c \
  "CREATE INDEX CONCURRENTLY idx_orders_status_created
   ON orders (status, created_at DESC) WHERE status = 'paid';"
sudo -u postgres psql -d appdb -c "ANALYZE orders;"
```

再跑一次同一條 `EXPLAIN`：

```text
 Limit  (actual time=14.702..14.711 rows=20 loops=1)
   Buffers: shared hit=812 read=96                            # ★★★ read 從 38116 掉到 96
   ->  Sort  (actual time=14.700..14.705 rows=20 loops=1)
         Sort Method: top-N heapsort  Memory: 27kB            # ★★★ 不再落磁碟
         ->  Nested Loop  (actual time=0.083..11.940 rows=24918 loops=1)
               ->  Index Scan using idx_orders_status_created on orders o
                     Index Cond: (created_at >= '2026-08-01')
                     Rows Removed by Filter: 0                # ★★★★ 0 = 索引選得對
 Execution Time: 14.930 ms                                    # 2844 ms → 15 ms（190 倍）
```

> [!tip] ★★★ 三個很好用的 EXPLAIN 選項
> ```sql
> EXPLAIN (ANALYZE, BUFFERS, SETTINGS)   SELECT ...;  -- SETTINGS：列出【被改過】的規劃參數
> EXPLAIN (GENERIC_PLAN)                 SELECT ... WHERE id = $1;  -- 不執行，看預備語句的計畫
> EXPLAIN (ANALYZE, SERIALIZE)           SELECT ...;  -- PG17+：把「轉成傳輸格式」的成本也算進來
> ```
> ★★★★ `EXPLAIN ANALYZE` 對 `UPDATE` / `DELETE` **會真的執行**。要試，包在交易裡：
> ```sql
> BEGIN; EXPLAIN (ANALYZE, BUFFERS) DELETE FROM orders WHERE id < 100; ROLLBACK;
> ```

### 二、★★★★ 六種索引，怎麼挑

| 索引 | 支援的運算子 | 典型用途 | 大小 | 星級 |
| --- | --- | --- | --- | --- |
| **B-tree**（預設） | `= < <= > >= BETWEEN IN`、`LIKE 'abc%'`、`ORDER BY` | ★★★★ **95% 的情況用這個** | 中 | ★★★★ |
| **Hash** | 只有 `=` | 超長字串的等值比對 | 小 | ★★ |
| **GIN** | `@>`、`?`、全文檢索、`jsonb`、陣列 | ★★★★ `jsonb` 欄位、全文檢索 | 大、建得慢 | ★★★★ |
| **GiST** | 幾何、範圍型別、`&&` 重疊 | 地理資料、時段不重疊約束 | 中 | ★★★ |
| **SP-GiST** | 非平衡結構、IP 前綴、四元樹 | `inet` 網段查詢、電話前綴 | 中 | ★★ |
| **BRIN** | 範圍摘要 | ★★★★ **超大表 + 欄位值與實體順序相關**（時序日誌） | 極小 | ★★★★ |

★★★★ **BRIN 是機關維運最被低估的索引**。一張三年份的 `access_log`（8 億列、420 GB），
`created_at` 幾乎完全按時間順序寫入：

```bash
sudo -u postgres psql -d appdb -c \
  "CREATE INDEX idx_log_ts_brin ON access_log USING brin (created_at) WITH (pages_per_range = 64);"
sudo -u postgres psql -d appdb -c \
  "SELECT pg_size_pretty(pg_relation_size('idx_log_ts_brin')) AS brin_size;"
```

預期輸出：

```text
 brin_size
-----------
 1128 kB      # ★★★★ B-tree 建同一欄要 17 GB，BRIN 只要 1 MB
```

> [!warning] ★★★★ BRIN 的前提：**實體順序必須與欄位值相關**
> 如果這張表經常 `UPDATE` 或資料是亂序插入的，BRIN 的效果會**趨近於零**（每個 range 的
> min/max 都涵蓋全部值 → 等於全表掃描）。判斷方法：
> ```bash
> sudo -u postgres psql -d appdb -c \
>   "SELECT attname, correlation FROM pg_stats WHERE tablename='access_log' AND attname='created_at';"
> ```
> ```text
>   attname   | correlation
> ------------+-------------
>  created_at |    0.999871   # ★★★★ 接近 1 或 -1 → BRIN 有效；接近 0 → 不要用
> ```

### 三、把索引變小：部分索引、覆蓋索引、運算式索引

**（1）部分索引 —— 只索引你真的會查的那一小塊** ★★★★

```sql
-- 只有 5% 的訂單是 pending，但所有查詢都在找 pending
CREATE INDEX CONCURRENTLY idx_orders_pending
  ON orders (created_at DESC)
  WHERE status = 'pending';
```

```bash
sudo -u postgres psql -d appdb -c \
  "SELECT indexrelname, pg_size_pretty(pg_relation_size(indexrelid)) sz
   FROM pg_stat_user_indexes WHERE relname='orders' ORDER BY 2;"
```

預期輸出：

```text
        indexrelname         |   sz
-----------------------------+---------
 idx_orders_pending          | 3416 kB    # ★★★★ 部分索引
 idx_orders_status_created   | 68 MB      # 全量索引，20 倍大
```

★★★ 陷阱：**查詢的 `WHERE` 必須「蘊含」索引的 `WHERE`**，規劃器才敢用。
`WHERE status = 'pending'` 可以；`WHERE status = ANY($1)` 綁定參數時**通常不行**。

**（2）覆蓋索引 `INCLUDE` —— 換到 Index Only Scan** ★★★

```sql
CREATE INDEX CONCURRENTLY idx_users_email_cover
  ON users (email) INCLUDE (id, name, created_at);
```

`INCLUDE` 的欄位**不參與排序，只存在葉節點**，所以索引比多欄索引小，
但查詢只要這幾欄就能走 `Index Only Scan`，完全不回表：

```text
 Index Only Scan using idx_users_email_cover on users
   Index Cond: (email = 'a@x.tw')
   Heap Fetches: 0            # ★★★★ 0 代表真的沒回表；很大代表 VACUUM 跑不夠
```

> [!warning] ★★★★ `Heap Fetches` 不是 0，代表 visibility map 不夠新
> Index Only Scan 靠 visibility map 判斷「這一頁全部可見」。
> **VACUUM 才會更新 visibility map**。所以看到 `Heap Fetches` 很大，
> 不是索引的問題，是 ★★★★ **autovacuum 追不上**，回去看第六節。

**（3）運算式索引 —— 讓函式呼叫也能走索引** ★★★

```sql
-- 應用寫的是 WHERE lower(email) = lower($1)，普通索引【完全用不到】
CREATE INDEX CONCURRENTLY idx_users_email_lower ON users (lower(email));
```

★★★★ 建完運算式索引**一定要跑 `ANALYZE`** —— 運算式的統計值是獨立蒐集的，
不跑的話規劃器對它的選擇率一無所知，估計會嚴重失準。

**（4）多欄索引的欄位順序** ★★★★

```text
索引 (a, b, c) 能支援的 WHERE：
  ✅ a = ?                      ✅ a = ? AND b = ?      ✅ a = ? AND b = ? AND c = ?
  ✅ a = ? AND c = ?（c 只能當 filter，不是 index cond）
  ❌ b = ?                      ❌ c = ?                ❌ b = ? AND c = ?

★★★★ 準則：【等值條件在前，範圍條件在後，排序欄位最後】
         WHERE status='paid' AND created_at > X ORDER BY total DESC
         → 索引 (status, created_at DESC, total DESC)
```

### 四、★★★★★ `CREATE INDEX CONCURRENTLY`：線上建索引的唯一正解

```text
普通 CREATE INDEX：
  取得 SHARE lock → ★★★★★ 【封鎖所有 INSERT / UPDATE / DELETE】直到建完
  一張 50 GB 的表可能鎖 20 分鐘 → 全站寫入停擺 → Laravel 佇列爆掉

CREATE INDEX CONCURRENTLY：
  掃兩次表 + 等待現有交易結束 → 只取 SHARE UPDATE EXCLUSIVE
  ★★★ 讀寫都不擋，代價是慢 2~3 倍
```

★★★★ 正式環境**只准用 `CONCURRENTLY`**，但它有三個陷阱：

```bash
# 陷阱一：不能在交易區塊內執行
sudo -u postgres psql -d appdb -c "BEGIN; CREATE INDEX CONCURRENTLY i1 ON t(a); COMMIT;"
```

預期輸出：

```text
ERROR:  CREATE INDEX CONCURRENTLY cannot run inside a transaction block
```

★★★ 所以**不能放進 Laravel migration 的預設交易裡**，要在 migration 內設
`public $withinTransaction = false;`（見 [[04-Laravel-Eloquent與資料庫]]）。

```bash
# 陷阱二：失敗會留下 INVALID 索引，它【佔空間、拖慢寫入、但完全不會被查詢使用】
sudo -u postgres psql -d appdb -c \
  "SELECT c.relname, pg_size_pretty(pg_relation_size(c.oid)) sz
   FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
   WHERE NOT i.indisvalid;"
```

預期輸出：

```text
          relname           |   sz
----------------------------+--------
 idx_orders_status_created  | 41 MB    # ★★★★ 這是垃圾，必須手動清掉
```

```bash
sudo -u postgres psql -d appdb -c "DROP INDEX CONCURRENTLY idx_orders_status_created;"
```

★★★★ **陷阱三：會被長交易卡住**。`CONCURRENTLY` 必須等到「所有在它開始前就存在的交易」
全部結束。有一條開了三小時忘記 commit 的交易，你的建索引就卡三小時：

```bash
sudo -u postgres psql -c \
  "SELECT pid, state, now()-xact_start AS xact_age, left(query,60) q
   FROM pg_stat_activity
   WHERE state <> 'idle' AND xact_start IS NOT NULL
   ORDER BY xact_start LIMIT 5;"
```

預期輸出：

```text
  pid  |        state        |    xact_age     |                q
-------+---------------------+-----------------+----------------------------------
 21883 | idle in transaction | 03:12:44.918203 | SELECT * FROM users WHERE id = 7
 30112 | active              | 00:04:01.220118 | CREATE INDEX CONCURRENTLY ...
```

```text
★★★★★ 看到 idle in transaction 且 xact_age 很大 = 【全部 VACUUM 與建索引的頭號殺手】
      解法：① 應用端修好（連線池沒 commit、例外沒 rollback）
            ② 設 idle_in_transaction_session_timeout = '10min' 讓資料庫自己收
```

看建索引進度（PG12+）：

```bash
sudo -u postgres psql -c \
  "SELECT phase, blocks_done, blocks_total,
          round(100.0*blocks_done/NULLIF(blocks_total,0),1) pct
   FROM pg_stat_progress_create_index;"
```

預期輸出：

```text
              phase              | blocks_done | blocks_total | pct
---------------------------------+-------------+--------------+------
 building index: scanning table  |      412880 |      1204118 | 34.3
```

### 五、★★★★ `pg_stat_statements`：找出爛查詢的唯一入口

★★★★ 這是 **`shared_preload_libraries`，必須 restart**，不能 reload：

```bash
echo "shared_preload_libraries = 'pg_stat_statements'
compute_query_id = on
pg_stat_statements.max = 5000
pg_stat_statements.track = top" | \
  sudo tee -a /etc/postgresql/16/main/conf.d/zz-tuning.conf
sudo systemctl restart postgresql@16-main
sudo -u postgres psql -d appdb -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;"
```

預期輸出：

```text
CREATE EXTENSION
```

撈 Top 10（**依總時間排序，不是依單次最慢**）：

```bash
sudo -u postgres psql -d appdb -x -c "
SELECT round(total_exec_time::numeric,0) AS total_ms,
       calls,
       round(mean_exec_time::numeric,2)  AS mean_ms,
       rows,
       round(100.0*shared_blks_hit/NULLIF(shared_blks_hit+shared_blks_read,0),1) AS hit_pct,
       left(query, 90) AS query
FROM pg_stat_statements
WHERE query NOT LIKE '%pg_stat_statements%'
ORDER BY total_exec_time DESC LIMIT 10;"
```

預期輸出：

```text
-[ RECORD 1 ]---------------------------------------------------------------
total_ms | 4182991
calls    | 1471                     # ★★★★ 呼叫 1471 次，平均 2.8 秒 → 這是元凶
mean_ms  | 2843.64
rows     | 29420
hit_pct  | 3.1                      # ★★★★ 命中率 3%，幾乎全部去讀磁碟
query    | SELECT o.id, o.total, u.email FROM orders o JOIN users u ON u.id = $1 ...
-[ RECORD 2 ]---------------------------------------------------------------
total_ms | 891204
calls    | 2884102                  # ★★★ 單次只有 0.3 ms，但呼叫 288 萬次
mean_ms  | 0.31
query    | SELECT * FROM settings WHERE key = $1
```

> [!tip] ★★★★ 兩種完全不同的病，處方也不同
> - **RECORD 1（次數少、單次慢）** → 補索引、改寫 SQL。翻本篇第一、二節。
> - **RECORD 2（單次快、次數爆炸）** → ★★★★ 這是**應用層的 N+1 查詢**，
>   資料庫這邊怎麼調都沒用。回去做 eager loading 或把它丟進 Redis，
>   見 [[04-Laravel-Eloquent與資料庫]] 與 [[04-Redis快取入門]]。

重置統計（每次調校前先歸零，才知道這次改了有沒有效）：

```bash
sudo -u postgres psql -d appdb -c "SELECT pg_stat_statements_reset();"
```

### 六、★★★★★ autovacuum 與膨脹：PostgreSQL 的生死線

**先量出膨脹有多嚴重**：

```bash
sudo -u postgres psql -d appdb -c "
SELECT relname,
       n_live_tup, n_dead_tup,
       round(100.0*n_dead_tup/NULLIF(n_live_tup+n_dead_tup,0),1) AS dead_pct,
       pg_size_pretty(pg_total_relation_size(relid)) AS total,
       last_autovacuum, autovacuum_count
FROM pg_stat_user_tables
WHERE n_dead_tup > 1000
ORDER BY n_dead_tup DESC LIMIT 10;"
```

預期輸出：

```text
   relname    | n_live_tup | n_dead_tup | dead_pct | total  |    last_autovacuum     | autovacuum_count
--------------+------------+------------+----------+--------+------------------------+------------------
 sessions     |      41203 |    8814022 |     99.5 | 12 GB  |                        |                0
 orders       |    3200000 |     418803 |     11.6 | 6142 MB| 2026-08-28 03:11:40+08 |              214
 audit_logs   |   88104223 |      41022 |      0.0 | 210 GB | 2026-08-28 01:02:11+08 |               12
```

```text
判讀：
  ★★★★★ sessions：dead_pct 99.5% 且 last_autovacuum 是空的、autovacuum_count = 0
         → autovacuum 【從來沒跑過這張表】。12 GB 裡面 99% 是垃圾。
         幾乎一定是：① 有長交易卡住  ② 這張表被 ALTER TABLE ... SET (autovacuum_enabled=false)
  ★★★ orders：11.6% 可接受，autovacuum 有在跑
  ★ audit_logs：只進不出的日誌表，dead 幾乎是 0，正常
```

**檢查是不是被關掉了**：

```bash
sudo -u postgres psql -d appdb -c \
  "SELECT relname, reloptions FROM pg_class WHERE relname IN ('sessions','orders');"
```

預期輸出：

```text
 relname  |            reloptions
----------+-----------------------------------
 sessions | {autovacuum_enabled=false}         # ★★★★★ 找到了，有人關掉它
 orders   |
```

```bash
sudo -u postgres psql -d appdb -c "ALTER TABLE sessions SET (autovacuum_enabled = true);"
```

**autovacuum 的觸發公式**（★★★★ 一定要記起來）：

```text
  觸發 VACUUM 的門檻
    = autovacuum_vacuum_threshold + autovacuum_vacuum_scale_factor × 表的列數
    = 50 + 0.2 × n_live_tup                          （原廠預設）

  ★★★★ 對一張 5000 萬列的表：50 + 0.2 × 50,000,000 = 【1000 萬列死行才開始 VACUUM】
        這就是為什麼「大表一定膨脹」—— 預設值是為小表設計的。
```

★★★★ 解法：**對大表個別下降 scale_factor**，不要動全域：

```bash
sudo -u postgres psql -d appdb -c "
ALTER TABLE orders SET (
  autovacuum_vacuum_scale_factor  = 0.01,   -- 1% 就跑
  autovacuum_vacuum_threshold     = 5000,
  autovacuum_analyze_scale_factor = 0.005,
  autovacuum_vacuum_cost_limit    = 2000    -- 這張表的 VACUUM 跑快一點
);"
sudo -u postgres psql -d appdb -c "SELECT relname, reloptions FROM pg_class WHERE relname='orders';"
```

預期輸出：

```text
 relname |                                    reloptions
---------+-----------------------------------------------------------------------------
 orders  | {autovacuum_vacuum_scale_factor=0.01,autovacuum_vacuum_threshold=5000,...}
```

**★★★★★ XID wraparound：每天都要看的一個數字**

```bash
sudo -u postgres psql -c "
SELECT datname, age(datfrozenxid) AS xid_age,
       round(100.0*age(datfrozenxid)/2100000000, 2) AS pct_to_wraparound
FROM pg_database ORDER BY 2 DESC;"
```

預期輸出：

```text
  datname  |  xid_age  | pct_to_wraparound
-----------+-----------+-------------------
 appdb     | 148920114 |              7.09   # ★★ 健康
 postgres  |  12048221 |              0.57
```

```text
判斷準則（★★★★★ 直接抄進監控告警，見 [[03-系統監控與告警]]）：
  xid_age <  2 億（autovacuum_freeze_max_age）  → ★ 正常
  xid_age >  6 億                                → ★★★ 警告：autovacuum 明顯追不上
  xid_age > 15 億                                → ★★★★ 嚴重：立刻找長交易與 replication slot
  xid_age > 20.6 億（剩 4000 萬）                → ★★★★★ 資料庫開始噴 WARNING
  xid_age > 21 億（剩 300 萬）                   → ★★★★★ 【拒絕所有寫入】，只能停機搶救
```

★★★★★ **XID 前進不了，只有四個原因**，發生事故時照這個順序查：

| # | 原因 | 檢查指令 |
| --- | --- | --- |
| 1 | 長交易 / `idle in transaction` | `SELECT pid, age(backend_xmin), now()-xact_start FROM pg_stat_activity ORDER BY 2 DESC NULLS LAST LIMIT 5;` |
| 2 | 廢棄的 replication slot | `SELECT slot_name, active, age(xmin), age(catalog_xmin) FROM pg_replication_slots;` |
| 3 | 未完成的 prepared transaction | `SELECT gid, prepared, age(transaction) FROM pg_prepared_xacts;` |
| 4 | autovacuum 被關掉或跑太慢 | `SHOW autovacuum;` 與 `SELECT * FROM pg_stat_progress_vacuum;` |

★★★★ 廢棄的 replication slot 是機關最常見的第 2 名 —— 副本機退役了、slot 忘了刪，
主機的 WAL 與 XID 就永遠卡在那一天（相關設定見 [[07-PostgreSQL-複寫與高可用]]）：

```bash
sudo -u postgres psql -c "SELECT pg_drop_replication_slot('old_replica_slot');"
```

**手動搶救膨脹的三種手段**：

| 手段 | 鎖 | 回收空間給 OS | 適用 | 星級 |
| --- | --- | --- | --- | --- |
| `VACUUM (VERBOSE, ANALYZE) t;` | 不擋讀寫 | ❌ 只是標記可重用 | 日常 | ★★ |
| `VACUUM FULL t;` | ★★★★★ **ACCESS EXCLUSIVE，全站卡住** | ✅ | **只能在停機時段** | ★★★★★ |
| `pg_repack -t t -d appdb` | 只在最後一瞬間短暫鎖 | ✅ | ★★★★ 線上重整的正解 | ★★★★ |

> [!danger] ★★★★★ 絕對不要在營運時段對大表跑 `VACUUM FULL`
> 它會取得 `ACCESS EXCLUSIVE` 鎖，**連 `SELECT` 都會被擋住**，
> 而且需要**與原表等量的額外磁碟空間**來重建。
> 一張 12 GB 的表 `VACUUM FULL` 可能鎖 15 分鐘以上 → 全站 502。
> 線上要重整就用 `pg_repack`（`sudo apt install -y postgresql-16-repack`），
> 或安排停機時段並先確認磁碟餘裕：
> ```bash
> df -h /var/lib/postgresql   # ★★★★ 剩餘空間必須 > 要處理的表的大小
> ```

### 七、★★★ checkpoint 與 WAL

```bash
sudo -u postgres psql -c "SELECT * FROM pg_stat_checkpointer;"   # PG 17+
```

預期輸出：

```text
 num_timed | num_requested | write_time | sync_time | buffers_written |    stats_reset
-----------+---------------+------------+-----------+-----------------+-------------------
      1204 |           388 |  418820112 |    204118 |        18841203 | 2026-08-01 00:00:00
```

```text
★★★★ 判斷準則：num_requested / (num_timed + num_requested) 應該 < 10%
      本例 388/1592 = 24% → 【max_wal_size 太小】，checkpoint 被 WAL 量逼出來
      解法：把 max_wal_size 從 1GB 提到 4GB~8GB，checkpoint_timeout 提到 15min
      代價：★★★ 崩潰復原時間變長、資料目錄下 pg_wal/ 會變大，要確認磁碟夠
```

> [!warning] ★★★★ PG 16 與 PG 17 的統計檢視不一樣
> `pg_stat_checkpointer` 是 **PG 17 才有**的檢視。
> 在 **PG 16 以下**，checkpoint 的數字在 `pg_stat_bgwriter` 裡，欄位名也不同：
> ```bash
> # PG 16：
> sudo -u postgres psql -c "SELECT checkpoints_timed, checkpoints_req,
>   checkpoint_write_time, buffers_checkpoint, buffers_backend FROM pg_stat_bgwriter;"
> ```
> ★★★ 監控腳本跨版本部署時，這裡是最常見的「腳本在新機器上跑不起來」原因。

### 八、★★★ 統計值與規劃器

```bash
sudo -u postgres psql -d appdb -c \
  "SELECT relname, n_mod_since_analyze, last_analyze, last_autoanalyze
   FROM pg_stat_user_tables WHERE n_mod_since_analyze > 10000 ORDER BY 2 DESC LIMIT 5;"
```

預期輸出：

```text
 relname | n_mod_since_analyze |      last_analyze      |    last_autoanalyze
---------+---------------------+------------------------+------------------------
 orders  |             1882041 |                        | 2026-07-14 02:11:08+08  # ★★★★ 一個多月沒更新
```

★★★★ 統計值過期的典型症狀是 `EXPLAIN` 裡 **`rows=` 與 `actual rows=` 差 100 倍以上**，
規劃器因此選了 Nested Loop 去跑 300 萬列。修法：

```bash
sudo -u postgres psql -d appdb -c "ANALYZE VERBOSE orders;"
```

預期輸出：

```text
INFO:  analyzing "public.orders"
INFO:  "orders": scanned 30000 of 786432 pages, containing 3200114 live rows and 418803 dead rows;
       30000 rows in sample, 3200114 estimated total rows
ANALYZE
```

★★★ 欄位值很偏斜（例如 99% 的 `status` 都是 `paid`）時，提高該欄位的取樣精度：

```bash
sudo -u postgres psql -d appdb -c \
  "ALTER TABLE orders ALTER COLUMN status SET STATISTICS 1000; ANALYZE orders (status);"
```

★★★ 兩個欄位有**相關性**時（`city` 與 `zipcode`），規劃器預設假設它們獨立，估計會低到離譜。
用擴充統計值告訴它：

```bash
sudo -u postgres psql -d appdb -c \
  "CREATE STATISTICS st_addr (dependencies, ndistinct) ON city, zipcode FROM addresses;
   ANALYZE addresses;"
```

### 九、★★★★ 連線數與 PgBouncer

★★★★★ **PostgreSQL 的每一條連線是一個獨立的作業系統行程**（不是 MySQL 的執行緒）。
所以連線本身就很貴 —— 每條約 5~10 MB RSS，而且連線數一多，
`snapshot` 的成本會呈非線性上升。

```text
  ★★★★ 判斷準則：max_connections 超過 (CPU 核心數 × 4) 之後，
        再加連線【只會讓每一條都變慢】，總吞吐不會增加。

  4 核心機器 → 合理上限約 100（含保留），實際同時活躍的應該只有 10~20 條。
```

看目前水位：

```bash
sudo -u postgres psql -c "
SELECT state, count(*) FROM pg_stat_activity GROUP BY state ORDER BY 2 DESC;
SELECT count(*) AS total, current_setting('max_connections') AS max FROM pg_stat_activity;"
```

預期輸出：

```text
        state        | count
---------------------+-------
 idle                |    72     # ★★★ 大量 idle = 應用端連線池沒回收
 active              |     6
 idle in transaction |     3     # ★★★★ 這三條在阻擋 VACUUM
```

★★★★ 應用端（PHP-FPM 40 個 worker + Laravel 佇列 + 排程）加起來很容易破 100。
正解不是調大 `max_connections`，是**在中間放 PgBouncer**：

```bash
sudo apt install -y pgbouncer
sudo tee /etc/pgbouncer/pgbouncer.ini > /dev/null <<'EOF'
[databases]
appdb = host=127.0.0.1 port=5432 dbname=appdb

[pgbouncer]
listen_addr = 127.0.0.1
listen_port = 6432
auth_type = scram-sha-256          # ★★★★ 與 pg_hba 的設定要一致
auth_file = /etc/pgbouncer/userlist.txt
pool_mode = transaction            # ★★★★ Laravel/Nuxt 用這個；見下方警告
max_client_conn = 1000             # 應用可以連進來的數量
default_pool_size = 20             # ★★★★ 真正連到 PostgreSQL 的只有 20 條
reserve_pool_size = 5
server_idle_timeout = 60
EOF
sudo systemctl enable --now pgbouncer
psql "postgresql://appuser@127.0.0.1:6432/appdb" -c "SELECT 1;"
```

預期輸出：

```text
 ?column?
----------
        1
```

> [!danger] ★★★★ `pool_mode = transaction` 會讓這些功能壞掉
> transaction pooling 下，**同一條應用連線的兩個查詢可能落在不同的後端連線**，所以：
> ```
> ❌ 預備語句（PDO 的 emulate=false）     → 要在 DSN 加 ?prepares=false 或用 PgBouncer 1.21+ 的 prepared statement 支援
> ❌ session 層級的 SET（含 SET work_mem）→ 改用 SET LOCAL（綁在交易內）
> ❌ LISTEN / NOTIFY                       → 完全不能用
> ❌ 顧問鎖 pg_advisory_lock（session 版） → 改用 pg_advisory_xact_lock
> ❌ 暫存表 CREATE TEMP TABLE              → 下一個查詢可能看不到
> ```
> ★★★★ 上線前先確認應用有沒有用到這些，否則會出現「十次有一次失敗」的鬼故事。

### 十、★★★★ 改設定的安全流程（六步，一步都不能跳）

```text
【1】記錄現況    pg-tune-check.sh > /var/backups/pgtune/before-$(date +%F).txt
【2】備份設定    cp conf.d/zz-tuning.conf conf.d/zz-tuning.conf.$(date +%F)
【3】一次只改一類（記憶體 / autovacuum / WAL），不要一次改十項
【4】語法驗證    postgres -D <datadir> -C <param>     ← 不會啟動服務
【5】套用        reload 優先；必須 restart 的排在維護時段
【6】驗收        pg-tune-check.sh 比對 before/after，並看 pg_settings.pending_restart
```

★★★★ **回滾只有一種正確做法**：刪掉 `zz-tuning.conf`、放回備份、reload/restart。
不要靠記憶「我剛剛好像改了什麼」。

---

## 完整實戰範例

### 情境

機關的請購系統（Laravel + Nuxt + PostgreSQL 16，Ubuntu 22.04，8 GB RAM / 4 核 / NVMe）。
上線 14 個月後，使用者回報：

- 早上 9:00~10:00 送單列表要轉 5~15 秒，偶爾 502
- 資料目錄從 3 GB 長到 21 GB，但 `SELECT count(*)` 顯示資料只有約 400 萬列
- 昨晚 `journalctl` 出現 `WARNING: database "appdb" must be vacuumed within 39,918,203 transactions`

★★★★★ 最後那一行代表**距離資料庫拒絕寫入只剩約 4000 萬個交易**。這是最高優先事項。

### 第一步：蒐證（不要急著改任何東西）

```bash
sudo -u postgres psql -c "SELECT datname, age(datfrozenxid) FROM pg_database ORDER BY 2 DESC;"
sudo -u postgres psql -c "SELECT pid, state, now()-xact_start AS xact_age, left(query,50)
  FROM pg_stat_activity WHERE xact_start IS NOT NULL ORDER BY xact_start LIMIT 5;"
sudo -u postgres psql -c "SELECT slot_name, active, age(xmin) FROM pg_replication_slots;"
```

預期輸出：

```text
 datname |  age(datfrozenxid)
---------+---------------------
 appdb   |          2060081797     # ★★★★★ 20.6 億，剩不到 4000 萬

  pid  |        state        |   xact_age    |  left
-------+---------------------+---------------+--------------------
  9182 | idle in transaction | 128 days ...  | SELECT * FROM pg_...

 slot_name    | active | age(xmin)
--------------+--------+------------
 replica_2024 | f      | 2059912004   # ★★★★★ 廢棄的 slot，卡了兩年
```

**兩個元凶都找到了**：一條開了 128 天的交易，加上一個 2024 年退役副本留下的 slot。

### 第二步：解除 XID 卡住的根因（最高優先）

```bash
# ★★★★ 先確認 9182 真的是廢棄連線（看 backend_start 與來源 IP）
sudo -u postgres psql -c \
  "SELECT pid, usename, client_addr, backend_start, state FROM pg_stat_activity WHERE pid=9182;"
sudo -u postgres psql -c "SELECT pg_terminate_backend(9182);"

# ★★★★★ 刪 slot 前必須確認那台副本真的退役了，否則會讓還在用的副本永久失聯
sudo -u postgres psql -c "SELECT pg_drop_replication_slot('replica_2024');"

# 讓 XID 前進：對整個資料庫做 freeze
sudo -u postgres vacuumdb --all --freeze --jobs=2 --analyze --verbose 2>&1 | tail -5
```

預期輸出：

```text
 pg_terminate_backend
----------------------
 t
 pg_drop_replication_slot
--------------------------

INFO:  vacuuming "appdb.public.orders"
vacuumdb: vacuuming database "appdb"
```

```bash
sudo -u postgres psql -c "SELECT datname, age(datfrozenxid) FROM pg_database ORDER BY 2 DESC;"
```

預期輸出：

```text
 datname |  age
---------+---------
 appdb   | 1204118     # ★★★★ 從 20.6 億掉到 120 萬，警報解除
```

### 第三步：驗收腳本

```bash
sudo tee /usr/local/bin/pg-tune-check.sh > /dev/null <<'SCRIPT'
#!/usr/bin/env bash
# ============================================================
# pg-tune-check.sh — PostgreSQL 調校驗收與健康檢查
# 用法：pg-tune-check.sh [資料庫名，預設 appdb]
# 離開碼：0 全數通過 / 1 有警告 / 2 有嚴重問題（★★★★ 可接進監控）
# ============================================================
set -euo pipefail

DB="${1:-appdb}"
PSQL=(sudo -u postgres psql -X -q -A -t -d "$DB")
RC=0

fail() { printf '  [嚴重] ★★★★★ %s\n' "$1"; RC=2; }
warn() { printf '  [警告] ★★★   %s\n' "$1"; [[ $RC -lt 1 ]] && RC=1 || true; }
ok()   { printf '  [通過] %s\n' "$1"; }
sec()  { printf '\n=== %s ===\n' "$1"; }

q() { "${PSQL[@]}" -c "$1" 2>/dev/null || { echo "PSQL_FAIL"; return 0; }; }

# ---------- 0. 連得上嗎 ----------
sec "0. 連線"
if [[ "$(q 'SELECT 1;')" != "1" ]]; then
  fail "無法連線到資料庫 $DB —— 後續檢查全部略過"
  exit 2
fi
ok "已連線到 $DB（$(q 'SELECT version();' | cut -c1-40)）"

# ---------- 1. 待重啟的設定 ----------
sec "1. 設定一致性"
PENDING="$(q "SELECT string_agg(name,', ') FROM pg_settings WHERE pending_restart;")"
if [[ -n "$PENDING" ]]; then
  fail "以下參數已改但【尚未重啟生效】：$PENDING"
else
  ok "沒有待重啟的參數"
fi

# ---------- 2. 記憶體預算 ----------
sec "2. 記憶體"
TOTAL_MB=$(awk '/MemTotal/{printf "%d", $2/1024}' /proc/meminfo)
SB_MB=$(q "SELECT (setting::bigint*8192/1024/1024) FROM pg_settings WHERE name='shared_buffers';")
WM_MB=$(q "SELECT (setting::bigint/1024) FROM pg_settings WHERE name='work_mem';")
MC=$(q "SELECT setting FROM pg_settings WHERE name='max_connections';")
printf '  實體記憶體 %s MB / shared_buffers %s MB / work_mem %s MB / max_connections %s\n' \
  "$TOTAL_MB" "$SB_MB" "$WM_MB" "$MC"

SB_PCT=$(( SB_MB * 100 / TOTAL_MB ))
if   [[ $SB_PCT -lt 15 ]]; then warn "shared_buffers 只佔 ${SB_PCT}%，建議 25%"
elif [[ $SB_PCT -gt 40 ]]; then fail "shared_buffers 佔 ${SB_PCT}%，雙層快取重複，且易 OOM"
else ok "shared_buffers 佔 ${SB_PCT}%（合理區間 15~40%）"; fi

WORST=$(( SB_MB + WM_MB * MC * 2 + MC * 8 ))
printf '  粗估最壞記憶體 = %s MB（shared_buffers + work_mem×conn×2 + conn×8MB）\n' "$WORST"
[[ $WORST -gt $TOTAL_MB ]] && fail "最壞情況 ${WORST} MB > 實體 ${TOTAL_MB} MB，OOM 風險" \
                           || ok "最壞情況在實體記憶體之內"

# ---------- 3. XID wraparound（★★★★★ 最重要）----------
sec "3. XID wraparound"
XID=$(q "SELECT max(age(datfrozenxid)) FROM pg_database;")
printf '  最大 age(datfrozenxid) = %s（上限 2,100,000,000）\n' "$XID"
if   [[ $XID -gt 1500000000 ]]; then fail "XID age 已達 $XID，立刻查長交易與 replication slot"
elif [[ $XID -gt 600000000  ]]; then warn "XID age 為 $XID，autovacuum 可能追不上"
else ok "XID age 健康"; fi

# ---------- 4. 長交易與 idle in transaction ----------
sec "4. 長交易"
LONGTX=$(q "SELECT count(*) FROM pg_stat_activity
            WHERE xact_start IS NOT NULL AND now()-xact_start > interval '10 min';")
IIT=$(q "SELECT count(*) FROM pg_stat_activity WHERE state='idle in transaction';")
[[ ${LONGTX:-0} -gt 0 ]] && fail "有 $LONGTX 條交易超過 10 分鐘（會擋住所有 VACUUM）" \
                         || ok "沒有超過 10 分鐘的交易"
[[ ${IIT:-0} -gt 3 ]] && warn "有 $IIT 條 idle in transaction，檢查應用端連線池" \
                      || ok "idle in transaction 數量正常（$IIT）"

# ---------- 5. 廢棄 replication slot ----------
sec "5. Replication slot"
DEAD=$(q "SELECT count(*) FROM pg_replication_slots WHERE NOT active;")
[[ ${DEAD:-0} -gt 0 ]] && fail "有 $DEAD 個 inactive slot，會永久卡住 WAL 與 XID" \
                       || ok "沒有 inactive slot"

# ---------- 6. 膨脹 ----------
sec "6. 膨脹（dead tuple）"
q "SELECT relname||' dead='||n_dead_tup||' ('||
     round(100.0*n_dead_tup/NULLIF(n_live_tup+n_dead_tup,0),1)||'%) size='||
     pg_size_pretty(pg_total_relation_size(relid))
   FROM pg_stat_user_tables
   WHERE n_dead_tup > 10000
     AND n_dead_tup > 0.2*(n_live_tup+n_dead_tup)
   ORDER BY n_dead_tup DESC LIMIT 5;" | while read -r line; do
     [[ -n "$line" ]] && warn "膨脹超過 20%：$line"
   done
BLOATED=$(q "SELECT count(*) FROM pg_stat_user_tables
             WHERE n_dead_tup > 10000 AND n_dead_tup > 0.2*(n_live_tup+n_dead_tup);")
[[ ${BLOATED:-0} -eq 0 ]] && ok "沒有膨脹超過 20% 的大表" || RC=$(( RC < 1 ? 1 : RC ))

# ---------- 7. 快取命中率 ----------
sec "7. 快取命中率"
HIT=$(q "SELECT round(100.0*sum(blks_hit)/NULLIF(sum(blks_hit)+sum(blks_read),0),2)
         FROM pg_stat_database WHERE datname='$DB';")
printf '  shared_buffers 命中率 = %s%%\n' "$HIT"
awk -v h="${HIT:-0}" 'BEGIN{ exit !(h < 95) }' \
  && warn "命中率低於 95%，考慮加大 shared_buffers 或檢查是否有全表掃描" \
  || ok "命中率 ${HIT}%"

# ---------- 8. 沒被用到的索引 ----------
sec "8. 未使用索引"
q "SELECT indexrelname||' on '||relname||' ('||
     pg_size_pretty(pg_relation_size(indexrelid))||', idx_scan=0)'
   FROM pg_stat_user_indexes s
   JOIN pg_index i ON i.indexrelid = s.indexrelid
   WHERE s.idx_scan = 0 AND NOT i.indisunique AND NOT i.indisprimary
     AND pg_relation_size(s.indexrelid) > 10*1024*1024
   ORDER BY pg_relation_size(s.indexrelid) DESC LIMIT 5;" | while read -r line; do
     [[ -n "$line" ]] && warn "索引從未被使用：$line"
   done

# ---------- 9. INVALID 索引 ----------
sec "9. INVALID 索引"
INV=$(q "SELECT count(*) FROM pg_index WHERE NOT indisvalid;")
[[ ${INV:-0} -gt 0 ]] && warn "有 $INV 個 INVALID 索引（CONCURRENTLY 失敗殘留），請 DROP INDEX CONCURRENTLY" \
                      || ok "沒有 INVALID 索引"

# ---------- 10. checkpoint 壓力 ----------
sec "10. checkpoint"
PGVER=$(q "SELECT current_setting('server_version_num')::int;")
if [[ ${PGVER:-0} -ge 170000 ]]; then
  REQ=$(q "SELECT round(100.0*num_requested/NULLIF(num_timed+num_requested,0),1) FROM pg_stat_checkpointer;")
else
  REQ=$(q "SELECT round(100.0*checkpoints_req/NULLIF(checkpoints_timed+checkpoints_req,0),1) FROM pg_stat_bgwriter;")
fi
printf '  被 WAL 量逼出來的 checkpoint 佔比 = %s%%\n' "${REQ:-n/a}"
awk -v r="${REQ:-0}" 'BEGIN{ exit !(r > 10) }' \
  && warn "requested checkpoint 超過 10%，建議加大 max_wal_size" \
  || ok "checkpoint 節奏正常"

printf '\n============================================\n'
case $RC in
  0) printf '結果：全數通過 ✅\n' ;;
  1) printf '結果：有警告，請安排處理 ⚠\n' ;;
  2) printf '結果：★★★★★ 有嚴重問題，請立即處理 ❌\n' ;;
esac
exit $RC
SCRIPT

sudo chmod 750 /usr/local/bin/pg-tune-check.sh
sudo /usr/local/bin/pg-tune-check.sh appdb
```

預期輸出（處理前）：

```text
=== 0. 連線 ===
  [通過] 已連線到 appdb（PostgreSQL 16.4 (Ubuntu 16.4-0ubun）

=== 1. 設定一致性 ===
  [通過] 沒有待重啟的參數

=== 2. 記憶體 ===
  實體記憶體 7924 MB / shared_buffers 128 MB / work_mem 4 MB / max_connections 100
  [警告] ★★★   shared_buffers 只佔 1%，建議 25%
  [通過] 最壞情況在實體記憶體之內

=== 3. XID wraparound ===
  最大 age(datfrozenxid) = 2060081797（上限 2,100,000,000）
  [嚴重] ★★★★★ XID age 已達 2060081797，立刻查長交易與 replication slot

=== 5. Replication slot ===
  [嚴重] ★★★★★ 有 1 個 inactive slot，會永久卡住 WAL 與 XID

=== 7. 快取命中率 ===
  shared_buffers 命中率 = 61.20%
  [警告] ★★★   命中率低於 95%，考慮加大 shared_buffers 或檢查是否有全表掃描

結果：★★★★★ 有嚴重問題，請立即處理 ❌
```

### 第四步：套用調校並補索引

```bash
# 記錄現況（★★★★ 這一步就是你的回滾依據）
sudo mkdir -p /var/backups/pgtune
sudo -u postgres psql -Atc \
  "SELECT name||'='||setting FROM pg_settings WHERE source <> 'default' ORDER BY name;" \
  | sudo tee /var/backups/pgtune/settings-before-$(date +%F).txt > /dev/null

# 套用本篇「基礎設定」那一份 zz-tuning.conf，然後 restart
sudo systemctl restart postgresql@16-main
sudo -u postgres psql -c "SELECT pg_is_in_recovery(), pg_postmaster_start_time();"
```

預期輸出：

```text
 pg_is_in_recovery |     pg_postmaster_start_time
-------------------+-------------------------------
 f                 | 2026-08-28 22:41:07.118204+08
```

```bash
# 線上補索引（★★★★ 一定要 CONCURRENTLY，且不要包在交易裡）
sudo -u postgres psql -d appdb -c \
  "CREATE INDEX CONCURRENTLY idx_orders_status_created
   ON orders (status, created_at DESC);"
sudo -u postgres psql -d appdb -c "ANALYZE orders;"

# ★★★★ 立刻確認索引是 valid 的
sudo -u postgres psql -d appdb -Atc \
  "SELECT indisvalid FROM pg_index WHERE indexrelid='idx_orders_status_created'::regclass;"
```

預期輸出：

```text
CREATE INDEX
ANALYZE
t                                # ★★★★ t = valid；f 的話要 DROP INDEX CONCURRENTLY 重來
```

### 第五步：驗收檢查表

| # | 檢查項 | 指令 | 預期結果 | 星級 |
| --- | --- | --- | --- | --- |
| 1 | 服務起得來 | `systemctl is-active postgresql@16-main` | `active` | ★★★★ |
| 2 | 沒有待重啟參數 | `psql -Atc "SELECT count(*) FROM pg_settings WHERE pending_restart;"` | `0` | ★★★★ |
| 3 | shared_buffers 生效 | `psql -Atc "SHOW shared_buffers;"` | `2GB` | ★★★★ |
| 4 | XID age 回到安全區 | `psql -Atc "SELECT max(age(datfrozenxid)) FROM pg_database;"` | `< 200000000` | ★★★★★ |
| 5 | 沒有 inactive slot | `psql -Atc "SELECT count(*) FROM pg_replication_slots WHERE NOT active;"` | `0` | ★★★★★ |
| 6 | 沒有長交易 | `psql -Atc "SELECT count(*) FROM pg_stat_activity WHERE now()-xact_start > '10 min';"` | `0` | ★★★★ |
| 7 | 索引 valid | `psql -Atc "SELECT count(*) FROM pg_index WHERE NOT indisvalid;"` | `0` | ★★★★ |
| 8 | 目標查詢變快 | `psql -c "EXPLAIN (ANALYZE) SELECT ...;"` | `Execution Time < 50 ms` | ★★★★ |
| 9 | 命中率 | `psql -Atc "SELECT round(100.0*sum(blks_hit)/(sum(blks_hit)+sum(blks_read)),1) FROM pg_stat_database;"` | `> 95` | ★★★ |
| 10 | 全套驗收 | `pg-tune-check.sh appdb; echo $?` | `0` | ★★★★ |
| 11 | 應用端可用 | `curl -s -o /dev/null -w '%{http_code}\n' https://app.gov.tw/orders` | `200` | ★★★★ |
| 12 | 備份仍正常 | 見 [[05-PostgreSQL-備份與還原]] 的還原演練 | 演練通過 | ★★★★★ |

### 第六步：回滾（★★★★ 三步之內回到原狀）

```bash
# 【1】移除本次調校
sudo mv /etc/postgresql/16/main/conf.d/zz-tuning.conf /root/zz-tuning.conf.rollback-$(date +%F)

# 【2】重啟（shared_buffers 這類 postmaster 參數只能 restart）
sudo systemctl restart postgresql@16-main

# 【3】比對是否回到 before 快照
sudo -u postgres psql -Atc \
  "SELECT name||'='||setting FROM pg_settings WHERE source <> 'default' ORDER BY name;" \
  > /tmp/settings-after.txt
diff /var/backups/pgtune/settings-before-$(date +%F).txt /tmp/settings-after.txt && echo "★★★★ 已完全回滾"
```

預期輸出：

```text
★★★★ 已完全回滾
```

> [!tip] ★★★ 索引要不要一起回滾？
> **通常不用。** 索引只會佔空間與略微拖慢寫入，不會讓服務起不來。
> 真的要移除，用 `DROP INDEX CONCURRENTLY idx_xxx;`（不擋線上讀寫），
> **不要**用 `DROP INDEX`（會取得 ACCESS EXCLUSIVE 鎖）。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `ERROR: database is not accepting commands that assign new transaction IDs` | XID wraparound 保護啟動，剩不到 300 萬個 XID | 停機 → 找出長交易／inactive slot 並清掉 → `vacuumdb --all --freeze`；根因不解決還會再犯 |
| ★★★★★ 資料目錄暴漲但 `count(*)` 沒變、`df` 快滿 | 表膨脹：autovacuum 被長交易或 inactive slot 卡住，死行回收不了 | 查 `pg_stat_activity` 與 `pg_replication_slots` → 解除卡點 → `VACUUM` 或停機 `pg_repack` |
| ★★★★★ 對大表跑 `VACUUM FULL`，全站 502 十幾分鐘 | `VACUUM FULL` 取 `ACCESS EXCLUSIVE` 鎖，連 `SELECT` 都擋 | 用 `pg_repack` 線上重整；`VACUUM FULL` 只能排維護時段，且要留等量磁碟 |
| ★★★★ `CREATE INDEX CONCURRENTLY` 跑了幾小時沒動靜 | 被一條 `idle in transaction` 的舊交易擋住（必須等它結束） | `pg_stat_activity` 找出 → `pg_terminate_backend(pid)` → 設 `idle_in_transaction_session_timeout` |
| ★★★★ 建好的索引查詢完全不用它 | ① 統計值過期 ② 部分索引的 `WHERE` 不匹配 ③ 欄位型別不同（`bigint` vs `text`）④ 用了 `lower()` 但索引是普通索引 | `ANALYZE`；`EXPLAIN` 看是否 `Seq Scan`；型別對齊或改建運算式索引 |
| ★★★★ 改了 `postgresql.conf` 但值沒變 | 被 `postgresql.auto.conf`（`ALTER SYSTEM`）覆蓋，或是 postmaster 參數只 reload 沒 restart | `SELECT name,source,sourcefile,pending_restart FROM pg_settings WHERE name='X';`；`ALTER SYSTEM RESET X;` |
| ★★★★ 半夜 OOM，`dmesg` 有 `Killed process (postgres)` | `shared_buffers` + `work_mem × 並發節點` + 連線行程超過實體記憶體 | 重算預算表（本篇「基礎設定」）；降 `work_mem`、降 `max_connections`、上 PgBouncer |
| ★★★★ 報表查詢突然變超慢，昨天還好好的 | 統計值過期後規劃器換了計畫（Index Scan → Seq Scan 或反過來） | `ANALYZE 表名;`；偏斜欄位 `SET STATISTICS 1000`；相關欄位建 `CREATE STATISTICS` |
| ★★★ `EXPLAIN` 出現 `Sort Method: external merge Disk: NNNkB` | `work_mem` 不足，排序落到磁碟 | 該 session `SET LOCAL work_mem='256MB'`；或加索引讓它根本不需要排序 |
| ★★★ `Index Only Scan` 但 `Heap Fetches` 很大 | visibility map 不夠新 —— VACUUM 沒跟上 | 對該表 `VACUUM 表名;`；下降該表的 `autovacuum_vacuum_scale_factor` |
| ★★★ `psql: FATAL: sorry, too many clients already` | 連線數打滿 `max_connections` | `superuser_reserved_connections` 保留的連線進去查 `pg_stat_activity`；上 PgBouncer 而不是無腦調大 |
| ★★★ 磁碟被 `/var/log/postgresql/` 寫爆 | `log_min_duration_statement = 0`（記錄每一條）或 `log_statement = all` | 改成 `1000`（1 秒）；設定 logrotate，見 [[02-日誌集中與輪替]] |
| ★★★ `pg_wal/` 目錄一直長大不會清 | inactive replication slot、`archive_command` 一直失敗、或 `wal_keep_size` 設太大 | `SELECT * FROM pg_stat_archiver;` 看 `last_failed_time`；清掉廢 slot |
| ★★★ 監控腳本在新機器上報 `relation "pg_stat_checkpointer" does not exist` | `pg_stat_checkpointer` 是 PG 17 才有；PG 16 在 `pg_stat_bgwriter` | 腳本用 `current_setting('server_version_num')::int` 分支（見驗收腳本第 10 段） |
| ★★★ `CREATE EXTENSION pg_stat_statements` 成功但查不到資料 | 沒加進 `shared_preload_libraries`，或加了沒 restart | `SHOW shared_preload_libraries;` 應含 `pg_stat_statements`；改完必須 **restart** |
| ★★ `pg_size_pretty(pg_relation_size(...))` 的數字比 `df` 小很多 | `pg_relation_size` 不含索引與 TOAST | 改用 `pg_total_relation_size()`；或用 `\dt+` / `\di+` |
| ★★ BRIN 索引建了但查詢一點都沒變快 | 欄位值與實體順序不相關（`correlation` 接近 0） | 查 `pg_stats.correlation`；不相關就改用 B-tree 或先 `CLUSTER` |

### 排查步驟

**【1】先確定「是不是資料庫的問題」**

```bash
uptime; free -m | head -2; iostat -x 1 3 2>/dev/null | tail -12
```

預期輸出：

```text
 09:41:02 up 128 days,  load average: 9.81, 7.44, 5.02
               total        used        free      shared  buff/cache   available
Mem:            7924        6902         198        2104         824         612
```

```text
判讀：
  · load 高 + available 很低 + swap 在動   → ★★★★ 記憶體問題，跳【2】
  · load 高 + %util 接近 100               → ★★★  I/O 問題，跳【5】
  · load 低但應用還是慢                     → ★★★  不是 DB，回 [[04-效能瓶頸排查方法論]]
```

**【2】確認有沒有被 OOM killer 動過手**

```bash
sudo dmesg -T | grep -iE 'killed process|out of memory' | tail -3
sudo -u postgres psql -Atc "SELECT pg_postmaster_start_time();"
```

預期輸出：

```text
[Fri Aug 28 03:14:22 2026] Out of memory: Killed process 1182 (postgres) total-vm:...
2026-08-28 03:14:41.882014+08
```

```text
看到 killed process (postgres) 且啟動時間就在後一秒
  → ★★★★ 記憶體超賣。直接去重算預算表（「基礎設定」那一節），不要再往下猜。
沒有紀錄、啟動時間很久以前 → 跳【3】
```

**【3】★★★★★ 看 XID 與膨脹（PostgreSQL 專屬，一定要查）**

```bash
sudo -u postgres psql -c "SELECT datname, age(datfrozenxid) FROM pg_database ORDER BY 2 DESC LIMIT 3;"
sudo -u postgres psql -d appdb -c \
  "SELECT relname, n_dead_tup, pg_size_pretty(pg_total_relation_size(relid)) sz
   FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 3;"
```

預期輸出：

```text
 datname |    age
---------+------------
 appdb   | 2060081797     # ★★★★★ 超過 15 億，最高優先，跳【4】

 relname  | n_dead_tup |   sz
----------+------------+---------
 sessions |    8814022 | 12 GB      # ★★★★ 膨脹，同樣跳【4】找卡點
```

```text
age > 15 億 或 n_dead_tup 佔比 > 50%  → ★★★★★ 跳【4】找卡住 VACUUM 的東西
兩者都健康                             → ★★★ 跳【6】找爛查詢
```

**【4】★★★★★ 找出卡住 VACUUM 的四個嫌犯（依序）**

```bash
sudo -u postgres psql -c "
SELECT pid, state, now()-xact_start AS xact_age, left(query,40) q
  FROM pg_stat_activity WHERE xact_start IS NOT NULL ORDER BY xact_start LIMIT 3;
SELECT slot_name, active, age(xmin) FROM pg_replication_slots;
SELECT gid, prepared FROM pg_prepared_xacts;
SHOW autovacuum;"
```

預期輸出：

```text
 pid  |        state        |    xact_age     |            q
------+---------------------+-----------------+-------------------------
 9182 | idle in transaction | 128 days 04:11  | SELECT * FROM pg_class

 slot_name    | active |  age(xmin)
--------------+--------+-------------
 replica_2024 | f      |  2059912004

 gid | prepared
-----+----------
(0 rows)

 autovacuum
------------
 on
```

```text
有 idle in transaction 且 xact_age 很大   → ★★★★★ 元凶 A：pg_terminate_backend(pid)
有 active = f 的 slot                     → ★★★★★ 元凶 B：確認副本退役後 pg_drop_replication_slot
pg_prepared_xacts 有資料                  → ★★★★  元凶 C：ROLLBACK PREPARED '<gid>'
autovacuum = off                          → ★★★★★ 元凶 D：打開它，並查是誰關的
四個都乾淨但還是膨脹                       → ★★★  autovacuum 太慢：調 cost_limit 與 scale_factor
```

**【5】I/O 打滿時，看是誰在讀**

```bash
sudo -u postgres psql -c "
SELECT pid, wait_event_type, wait_event, state, now()-query_start AS dur, left(query,50) q
  FROM pg_stat_activity WHERE state='active' ORDER BY query_start LIMIT 5;"
sudo -u postgres psql -c "SELECT * FROM pg_stat_progress_vacuum;"
```

預期輸出：

```text
  pid  | wait_event_type |  wait_event  | state  |   dur    |   q
-------+-----------------+--------------+--------+----------+---------------
 31402 | IO              | DataFileRead | active | 00:04:12 | SELECT o.id...

 pid  | datname | relid | phase              | heap_blks_total | heap_blks_scanned
------+---------+-------+--------------------+-----------------+-------------------
 4102 | appdb   | 16482 | scanning heap      |         1204118 |            418820
```

```text
wait_event = DataFileRead 且持續很久   → ★★★★ 全表掃描，跳【6】找那條 SQL
pg_stat_progress_vacuum 有列且 phase 一直不動 → ★★★★ VACUUM 在跑但被 cost_delay 綁住
                                                  調高 autovacuum_vacuum_cost_limit
wait_event_type = Lock                 → ★★★★ 是鎖不是 I/O，跳【7】
```

**【6】找出爛查詢**

```bash
sudo -u postgres psql -d appdb -Atc "
SELECT round(total_exec_time::numeric)||' ms | '||calls||' calls | '||
       round(mean_exec_time::numeric,1)||' ms avg | '||left(query,60)
FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 3;"
```

預期輸出：

```text
4182991 ms | 1471 calls | 2843.6 ms avg | SELECT o.id, o.total FROM orders o JOIN ...
891204 ms | 2884102 calls | 0.3 ms avg | SELECT * FROM settings WHERE key = $1
```

```text
mean 很大、calls 少     → ★★★★ 缺索引。把那條 SQL 拿去 EXPLAIN (ANALYZE, BUFFERS)
mean 很小、calls 爆炸   → ★★★★ 應用層 N+1，資料庫這邊調不動，回 [[04-Laravel-Eloquent與資料庫]]
pg_stat_statements 空的 → ★★★  沒 restart，或沒進 shared_preload_libraries
```

**【7】被鎖住時，找出鎖鏈的源頭**

```bash
sudo -u postgres psql -c "
SELECT blocked.pid AS blocked_pid, blocking.pid AS blocking_pid,
       left(blocked.query,30) AS blocked_q, left(blocking.query,30) AS blocking_q,
       now()-blocking.xact_start AS blocking_age
FROM pg_stat_activity blocked
JOIN LATERAL unnest(pg_blocking_pids(blocked.pid)) AS bp(pid) ON true
JOIN pg_stat_activity blocking ON blocking.pid = bp.pid
WHERE cardinality(pg_blocking_pids(blocked.pid)) > 0;"
```

預期輸出：

```text
 blocked_pid | blocking_pid |       blocked_q       |     blocking_q      | blocking_age
-------------+--------------+-----------------------+---------------------+--------------
       31488 |         9182 | UPDATE orders SET ... | idle                | 03:12:44
```

```text
★★★★ blocking_q 是 'idle' → 那條連線【開著交易但什麼都沒做】，是應用端的 bug
      緊急解法：SELECT pg_terminate_backend(9182);
      根本解法：設 idle_in_transaction_session_timeout = '10min'
```

**【8】確認調校真的有效（不要憑感覺）**

```bash
sudo -u postgres psql -d appdb -c "SELECT pg_stat_statements_reset();"
sleep 900   # 讓它累積 15 分鐘的真實流量
sudo /usr/local/bin/pg-tune-check.sh appdb; echo "離開碼=$?"
```

預期輸出：

```text
結果：全數通過 ✅
離開碼=0
```

---

## 安全性注意事項

> [!danger] ★★★★★ 絕對禁止的六件事
> 1. **在營運時段對大表下 `VACUUM FULL` 或 `REINDEX`（不加 CONCURRENTLY）** ——
>    取得 `ACCESS EXCLUSIVE` 鎖，`SELECT` 都被擋，等同計畫外停機。
> 2. **不先確認就 `pg_drop_replication_slot()`** —— 若那個 slot 屬於還在服役的副本，
>    副本會因為 WAL 被回收而**永久失聯，只能整台重建**。先看 `active` 與副本主機。
> 3. **關掉 `autovacuum`「因為它會吃 I/O」** —— ★★★★★ 這是通往 XID wraparound 的最短路徑，
>    結局是整個資料庫拒絕寫入。要降低影響請調 `autovacuum_vacuum_cost_delay/limit`，不是關掉。
> 4. **把 `log_min_duration_statement` 設成 `0` 並開 `log_statement = all`** ——
>    ★★★★★ SQL 全文會進日誌，`WHERE id_no = 'A123456789'` 這類**個人資料就直接落在
>    純文字日誌檔裡**，違反個資法第 27 條的安全維護義務。日誌又通常沒有加密、備份會複製一份。
> 5. **在 `EXPLAIN ANALYZE` 裡直接跑 `UPDATE` / `DELETE`** —— ★★★★ 它**會真的執行**。
>    要試一定包 `BEGIN; ... ROLLBACK;`。
> 6. **為了「先讓它跑起來」而給應用帳號 `SUPERUSER`** —— ★★★★★ superuser 可以讀寫伺服器
>    檔案系統、繞過所有 RLS 與 `pg_hba` 的邏輯限制。權限設計見 [[02-PostgreSQL-角色與權限]]。

★★★★ **機關情境要特別注意的三件事**：

| 議題 | 為什麼跟效能調校有關 | 做法 |
| --- | --- | --- |
| ★★★★★ 個資落入日誌 | 慢查詢日誌會記錄**含參數的完整 SQL** | `log_min_duration_statement >= 1000`；日誌目錄權限 `0700 postgres:postgres`；納入 logrotate 與保存期限政策 |
| ★★★★ 稽核軌跡 | 「誰在什麼時候改了什麼參數」要查得到 | `zz-tuning.conf` 納入 git 版控；`log_line_prefix` 帶上 `%m [%p] %q%u@%d`；`ALTER SYSTEM` 的異動會留在 `postgresql.auto.conf` |
| ★★★★ 最小權限 | 監控帳號常被便宜行事給了 superuser | 監控只需要 `pg_monitor` 這個內建角色：`GRANT pg_monitor TO monitoring;` —— 它就能讀 `pg_stat_*` 而**不能改資料** |

```bash
# ★★★★ 建立唯讀監控帳號的正確做法
sudo -u postgres psql -c "CREATE ROLE monitoring LOGIN PASSWORD 'ChangeMe!';"
sudo -u postgres psql -c "GRANT pg_monitor TO monitoring;"
sudo -u postgres psql -c "\du monitoring"
```

預期輸出：

```text
             List of roles
 Role name  | Attributes | Member of
------------+------------+--------------
 monitoring |            | {pg_monitor}    # ★★★★ 沒有 Superuser 字樣才是對的
```

> [!warning] ★★★★ `pg_stat_statements` 本身就是一種資料外洩風險
> 它會保留**正規化後**的 SQL（常數被換成 `$1`），一般情況安全。
> 但 ★★★ 如果應用把值直接串進 SQL（沒有用預備語句），
> `pg_stat_statements` 裡就會出現 `WHERE id_no = 'A123456789'` 這種字串。
> 所以這張表**不要開放給一般使用者**：預設只有 superuser 與 `pg_read_all_stats` 看得到完整 query，
> 其他人看到的是 `<insufficient privilege>`。**不要為了方便 `GRANT SELECT` 給應用帳號。**

---

## 速查表

### 一定要背的十個檢查指令

| 指令 | 用途 | 星級 |
| --- | --- | --- |
| `SELECT max(age(datfrozenxid)) FROM pg_database;` | ★★★★★ XID wraparound 距離，每天看 | ★★★★★ |
| `SELECT slot_name, active, age(xmin) FROM pg_replication_slots;` | ★★★★★ 找廢棄 slot | ★★★★★ |
| `SELECT pid, now()-xact_start, state FROM pg_stat_activity ORDER BY xact_start;` | ★★★★ 找長交易 | ★★★★ |
| `SELECT relname, n_dead_tup FROM pg_stat_user_tables ORDER BY 2 DESC LIMIT 10;` | ★★★★ 找膨脹的表 | ★★★★ |
| `SELECT * FROM pg_stat_progress_vacuum;` | ★★★ 看 VACUUM 跑到哪 | ★★★ |
| `SELECT * FROM pg_stat_progress_create_index;` | ★★★ 看建索引進度 | ★★★ |
| `SELECT count(*) FROM pg_index WHERE NOT indisvalid;` | ★★★★ 找 INVALID 索引 | ★★★★ |
| `SELECT name,setting,source,pending_restart FROM pg_settings WHERE name='X';` | ★★★★ 確認實際值 | ★★★★ |
| `SELECT pg_blocking_pids(pid), pid FROM pg_stat_activity;` | ★★★★ 找鎖鏈源頭 | ★★★★ |
| `EXPLAIN (ANALYZE, BUFFERS) <SQL>;` | ★★★★ 慢查詢的答案卡 | ★★★★ |

### 記憶體參數

| 參數 | 預設 | 建議 | 生效方式 | 星級 |
| --- | --- | --- | --- | --- |
| `shared_buffers` | 128 MB | RAM × 25% | ★★★★ **restart** | ★★★★ |
| `effective_cache_size` | 4 GB | RAM × 50~75%（不佔記憶體） | reload | ★★★ |
| `work_mem` | 4 MB | 8~16 MB；報表用 `SET LOCAL` | 立即（`SET` 即可） | ★★★★ |
| `maintenance_work_mem` | 64 MB | 256 MB~1 GB | reload | ★★★ |
| `autovacuum_work_mem` | -1（沿用上者） | -1 或獨立設 | reload | ★★ |
| `max_connections` | 100 | ≤ CPU 核心 × 4，超過就上 PgBouncer | ★★★★ **restart** | ★★★★ |
| `huge_pages` | try | 大 `shared_buffers` 時設 `on` 並配 sysctl | ★★★ **restart** | ★★★ |

### I/O 與 WAL 參數

| 參數 | 預設（PG 16/17） | SSD 建議 | 星級 |
| --- | --- | --- | --- |
| `random_page_cost` | 4.0 | ★★★★ **1.1** | ★★★★ |
| `seq_page_cost` | 1.0 | 1.0（不動） | ★ |
| `effective_io_concurrency` | 1 | 200 | ★★★ |
| `maintenance_io_concurrency` | 10 | 200 | ★★ |
| `max_wal_size` | 1 GB | 4~8 GB（看 requested checkpoint 佔比） | ★★★ |
| `checkpoint_timeout` | 5 min | 15 min | ★★★ |
| `checkpoint_completion_target` | 0.9 | 0.9（不動） | ★ |
| `wal_compression` | off | `lz4` | ★★ |
| `track_io_timing` | off | ★★★★ **on**（先用 `pg_test_timing` 確認開銷小） | ★★★★ |

### autovacuum 參數

| 參數 | 預設 | 大表建議 | 星級 |
| --- | --- | --- | --- |
| `autovacuum` | on | ★★★★★ **永遠 on** | ★★★★★ |
| `autovacuum_vacuum_scale_factor` | 0.2 | 全域 0.05；大表個別 0.01 | ★★★★ |
| `autovacuum_vacuum_threshold` | 50 | 50~5000 | ★★ |
| `autovacuum_analyze_scale_factor` | 0.1 | 0.02 | ★★★ |
| `autovacuum_vacuum_insert_threshold` | 1000 | 只進不出的表可調大 | ★★ |
| `autovacuum_vacuum_cost_delay` | 2 ms | 1~2 ms | ★★★ |
| `autovacuum_vacuum_cost_limit` | -1（=200） | ★★★★ SSD 上 1000~3000 | ★★★★ |
| `autovacuum_naptime` | 1 min | 30 s | ★★ |
| `autovacuum_max_workers` | 3 | 3~5（★★★ **restart**） | ★★★ |
| `autovacuum_freeze_max_age` | 2 億 | 不建議亂動（★★★ **restart**） | ★★★ |
| `log_autovacuum_min_duration` | -1（不記） | `250ms`，留軌跡 | ★★★ |

### 判斷準則（門檻值，可直接接進監控）

| 指標 | 健康 | 警告 | 嚴重 |
| --- | --- | --- | --- |
| `age(datfrozenxid)` | < 2 億 | > 6 億 ★★★ | > 15 億 ★★★★★ |
| `n_dead_tup / (live+dead)` | < 10% | > 20% ★★★ | > 50% ★★★★ |
| shared_buffers 命中率 | > 99% | < 95% ★★★ | < 80% ★★★★ |
| requested checkpoint 佔比 | < 5% | > 10% ★★★ | > 30% ★★★★ |
| `idle in transaction` 最久 | < 1 min | > 10 min ★★★★ | > 1 h ★★★★★ |
| inactive replication slot 數 | 0 | — | ≥ 1 ★★★★★ |
| `Heap Fetches`（Index Only Scan） | 0 | 佔列數 > 10% ★★★ | > 50% ★★★★ |
| `pg_index WHERE NOT indisvalid` | 0 | — | ≥ 1 ★★★★ |

### 檔案與路徑（Ubuntu / Debian 主線）

| 路徑 | 內容 | 星級 |
| --- | --- | --- |
| `/etc/postgresql/16/main/postgresql.conf` | 發行版主設定檔，**不要直接改** | ★★★ |
| `/etc/postgresql/16/main/conf.d/zz-tuning.conf` | ★★★★ 你的調校檔，納入 git | ★★★★ |
| `/var/lib/postgresql/16/main/postgresql.auto.conf` | ★★★★ `ALTER SYSTEM` 寫的，優先度最高 | ★★★★ |
| `/var/lib/postgresql/16/main/pg_wal/` | WAL；一直長大就查 slot 與 archive | ★★★★ |
| `/var/log/postgresql/postgresql-16-main.log` | 慢查詢、checkpoint、autovacuum 都在這 | ★★★★ |
| `/usr/local/bin/pg-tune-check.sh` | 本篇的驗收腳本 | ★★★ |

---

## 練習題

> [!question]- 練習 1：把一張膨脹到 8 GB 的 sessions 表救回來（不停機）
> **題目**：`sessions` 表 `n_live_tup=42000`、`n_dead_tup=8800000`、實體大小 8 GB。
> 已確認沒有長交易也沒有 inactive slot。請在**不停機**的前提下把它縮回來，並讓它不再復發。
>
> **參考解答**：
> ```bash
> # 【1】先確認 autovacuum 沒有被個別關掉
> sudo -u postgres psql -d appdb -c "SELECT reloptions FROM pg_class WHERE relname='sessions';"
> #  → {autovacuum_enabled=false} 的話先打開：
> sudo -u postgres psql -d appdb -c "ALTER TABLE sessions SET (autovacuum_enabled=true);"
>
> # 【2】立刻手動 VACUUM（不擋讀寫），先把死行標記成可重用
> sudo -u postgres psql -d appdb -c "VACUUM (VERBOSE, ANALYZE) sessions;"
> #  ★★★ 這一步【不會】把空間還給作業系統，只是讓後續寫入重用這些空間
>
> # 【3】要真的縮小檔案，用 pg_repack（線上，只在最後瞬間短鎖）
> sudo apt install -y postgresql-16-repack
> sudo -u postgres psql -d appdb -c "CREATE EXTENSION IF NOT EXISTS pg_repack;"
> sudo -u postgres pg_repack -d appdb -t public.sessions --no-superuser-check
> #  ★★★★ 需要與原表【等量的暫時磁碟空間】，先跑 df -h 確認
>
> # 【4】防復發：這張表 UPDATE 極頻繁，把門檻壓低
> sudo -u postgres psql -d appdb -c "
>   ALTER TABLE sessions SET (
>     autovacuum_vacuum_scale_factor = 0.01,
>     autovacuum_vacuum_threshold    = 1000,
>     autovacuum_vacuum_cost_limit   = 2000,
>     fillfactor                     = 85    -- ★★★ 留空間給 HOT update，減少索引寫入
>   );"
>
> # 【5】驗收
> sudo -u postgres psql -d appdb -c "
>   SELECT relname, n_dead_tup, pg_size_pretty(pg_total_relation_size(relid))
>   FROM pg_stat_user_tables WHERE relname='sessions';"
> ```
> ★★★★ 為什麼不用 `VACUUM FULL`？因為題目要求**不停機**，
> `VACUUM FULL` 會鎖到連 `SELECT` 都不能跑。

> [!question]- 練習 2：判讀一份 EXPLAIN 並開出處方
> **題目**：以下輸出該怎麼修？
> ```text
> Nested Loop  (cost=0.42..8812.1 rows=1 width=48)
>              (actual time=0.812..14204.118 rows=48211 loops=1)
>   ->  Seq Scan on invoices i  (actual time=0.018..12.220 rows=48211 loops=1)
>   ->  Index Scan using items_pkey on items t
>         (actual time=0.281..0.293 rows=1 loops=48211)
>         Buffers: shared hit=192844 read=41208
> Execution Time: 14251.882 ms
> ```
>
> **參考解答**：
> ★★★★ 關鍵是外層 `rows=1` 但 `actual rows=48211` —— **估計差了 48211 倍**。
> 規劃器以為只會有一列，所以選了 Nested Loop（對每一列去內表查一次）。
> 實際有 4.8 萬列 → 內層跑了 `loops=48211` 次 → 40 幾萬個 buffer 存取。
>
> 處方（依序）：
> ```bash
> # 【1】最可能：統計值過期
> sudo -u postgres psql -d appdb -c "ANALYZE invoices; ANALYZE items;"
> #    重跑 EXPLAIN，若 rows= 變準、計畫換成 Hash Join，就結案
>
> # 【2】若欄位很偏斜，提高取樣精度
> sudo -u postgres psql -d appdb -c "
>   ALTER TABLE invoices ALTER COLUMN status SET STATISTICS 1000; ANALYZE invoices;"
>
> # 【3】若是兩個欄位有相關性（規劃器假設獨立 → 相乘後估成 1 列）
> sudo -u postgres psql -d appdb -c "
>   CREATE STATISTICS st_inv (dependencies, ndistinct) ON dept_id, status FROM invoices;
>   ANALYZE invoices;"
>
> # 【4】驗證（Nested Loop 應該換成 Hash Join，loops 變 1）
> sudo -u postgres psql -d appdb -c "EXPLAIN (ANALYZE, BUFFERS) <原 SQL>;"
> ```
> ★★★ **不要**用 `SET enable_nestloop = off;` 去硬壓 —— 那是治標，
> 而且會影響這條連線的所有查詢。根因是估計不準，要修的是統計值。

> [!question]- 練習 3：設計 orders 表的複合索引
> **題目**：Laravel 的送單列表固定跑這一條，`orders` 有 800 萬列，
> `status='paid'` 佔 92%、`dept_id` 有 40 個不同值：
> ```sql
> SELECT * FROM orders
> WHERE dept_id = ? AND status = 'paid' AND created_at >= ?
> ORDER BY created_at DESC LIMIT 50;
> ```
> 請設計索引並說明欄位順序的理由。
>
> **參考解答**：
> ```sql
> -- ★★★★ 順序原則：【等值在前、選擇性高的在前、範圍與排序在後】
> CREATE INDEX CONCURRENTLY idx_orders_dept_created
>   ON orders (dept_id, created_at DESC)
>   WHERE status = 'paid';
> ```
> 理由：
> 1. ★★★★ `status='paid'` 佔 92% —— **選擇性極差，放進索引欄位是浪費**。
>    改成**部分索引的 WHERE 條件**，等於免費過濾掉 8% 且完全不佔索引欄位空間。
> 2. `dept_id` 是等值條件、40 個值 → 選擇性好，放**第一個**。
> 3. `created_at DESC` 同時是範圍條件與排序欄位，放**最後**，
>    這樣 `ORDER BY created_at DESC LIMIT 50` 可以**直接沿索引取前 50 筆**，不需要排序節點。
>
> 驗收：
> ```bash
> sudo -u postgres psql -d appdb -c "ANALYZE orders;"
> sudo -u postgres psql -d appdb -c "EXPLAIN (ANALYZE, BUFFERS) SELECT ...;"
> ```
> ```text
> Limit (actual time=0.062..0.184 rows=50 loops=1)
>   ->  Index Scan using idx_orders_dept_created on orders
>         Index Cond: ((dept_id = 7) AND (created_at >= '2026-08-01'))
>   #  ★★★★ 看不到 Sort 節點 = 排序被索引順序吃掉了，這就是設計成功的標誌
> ```
> ★★★ 注意 `SELECT *` 讓 Index Only Scan 不可能發生。
> 若只需要少數欄位，可再加 `INCLUDE (id, total, user_id)` 換到 Index Only Scan。

---

## 小測驗

Q1. `SELECT setting FROM pg_settings WHERE name='shared_buffers';` 回傳 `16384`。這台機器的 `shared_buffers` 是多少 MB？你怎麼確認這個值**現在真的生效了**？

Q2. **是非題**：PostgreSQL 的 `shared_buffers` 應該像 MySQL 的 `innodb_buffer_pool_size` 一樣設成實體記憶體的 75%。請說明理由。

Q3. **「這行指令會發生什麼」**：正式環境的 `orders` 表有 5000 萬列，你在營運時段執行
`psql -c "CREATE INDEX idx_o ON orders(created_at);"`。

Q4. `EXPLAIN ANALYZE` 顯示某節點 `rows=1` 但 `actual rows=48211`，且計畫選了 Nested Loop。這代表什麼？你的前兩個動作是什麼？

Q5. **選擇題**：`work_mem = 16MB`、`max_connections = 100`。最壞情況 PostgreSQL 會用掉多少排序記憶體？
(A) 16 MB (B) 1.6 GB (C) 可能遠超過 1.6 GB (D) 與 `max_connections` 無關，固定 16 MB

Q6. `CREATE INDEX CONCURRENTLY` 執行三小時毫無進展，`pg_stat_progress_create_index` 的 `blocks_done` 不動。**該先查哪裡？**

Q7. 日誌出現 `WARNING: database "appdb" must be vacuumed within 39,918,203 transactions`。這代表什麼？在你去跑 `VACUUM` 之前，**必須先做的一件事**是什麼？為什麼？

Q8. `EXPLAIN` 顯示 `Index Only Scan` 但 `Heap Fetches: 1204882`。這是索引的問題嗎？該修哪裡？

Q9. **簡答**：你把一張 12 GB 的 `sessions` 表做了 `VACUUM`，`n_dead_tup` 歸零了，但 `df -h` 顯示磁碟一點都沒空出來。為什麼？要真的把空間還給作業系統有哪兩種做法，各自的代價是什麼？

Q10. **「看到這個錯誤該先查哪裡」**：`pg_wal/` 目錄從 2 GB 長到 180 GB，磁碟快滿了。請說出三個可能原因與對應的檢查指令，並說明**哪一個絕對不能用 `rm` 解決**。

> [!question]- 測驗答案
> **Q1.** **128 MB**。
> ★★★ `pg_settings.setting` 對 `shared_buffers` 的單位是 **8 kB 的頁數**，
> 所以 `16384 × 8 kB = 131072 kB = 128 MB` —— 而且這正好是**原廠預設值**，代表沒人調過。
> 確認「現在真的生效」要看兩個欄位：
> ```bash
> sudo -u postgres psql -c "SELECT name, setting, unit, source, pending_restart
>   FROM pg_settings WHERE name='shared_buffers';"
> ```
> ★★★★ `pending_restart = t` 就代表**設定檔已經改了，但跑的還是舊值**，
> 因為 `shared_buffers` 的 `context` 是 `postmaster`，只能 restart 不能 reload。
> `source` 欄位還會告訴你這個值是從 `default` / `configuration file` / `database` 哪裡來的。
> 見〈基礎設定：先確認「實際值」〉。
>
> **Q2.** **錯（是非題答「非」）**。★★★★
> PostgreSQL 是**雙層快取**：`shared_buffers` 沒命中會落到 **Linux page cache**，
> 而 PostgreSQL **不使用 O_DIRECT**，所以同一份資料會在兩層各存一份（double buffering）。
> 把 `shared_buffers` 設到 75%：
> ```
> ① 記憶體被重複佔用，實際能快取的資料【沒有變多】
> ② 留給 work_mem、連線行程、maintenance_work_mem 的餘裕被吃光
> ③ ★★★★★ 尖峰時 OOM killer 會殺掉 postgres → crash recovery → 全站 500
> ```
> 業界共識是 **RAM 的 25%**，另外用 `effective_cache_size`（RAM 的 50~75%）
> 告訴規劃器「整台機器大約有多少快取可用」—— 那一項**不配置任何記憶體**。
> 見〈觀念說明：PostgreSQL 是雙層快取〉。
>
> **Q3.** ★★★★★ **全站寫入停擺，直到索引建完為止。**
> 不加 `CONCURRENTLY` 的 `CREATE INDEX` 會取得該表的 `SHARE` 鎖 ——
> `SELECT` 還能跑，但**所有 `INSERT` / `UPDATE` / `DELETE` 全部被擋住排隊**。
> 5000 萬列的表可能要 10~30 分鐘：
> ```
> Laravel 的送單 API 全部逾時 → PHP-FPM worker 被佔滿 → Nginx 回 502
> 佇列 job 大量失敗 → 使用者重送 → 雪上加霜
> ```
> 正確做法：
> ```bash
> sudo -u postgres psql -d appdb -c "CREATE INDEX CONCURRENTLY idx_o ON orders(created_at);"
> sudo -u postgres psql -d appdb -Atc "SELECT indisvalid FROM pg_index WHERE indexrelid='idx_o'::regclass;"
> ```
> ★★★★ 而且**事後一定要確認 `indisvalid = t`**，因為 `CONCURRENTLY` 失敗會留下
> 佔空間又不被使用的 `INVALID` 索引。見〈進階設定與調校〉第四節。
>
> **Q4.** ★★★★ 這代表**規劃器的估計錯了 48211 倍**，不是索引的問題。
> 規劃器以為外層只回一列，所以選了 Nested Loop（「反正只查一次內表」）；
> 實際上外層有 4.8 萬列，於是內層被執行了 `loops=48211` 次，
> 每次都要走一趟索引 + 回表 → 幾十萬次 buffer 存取 → 14 秒。
> 前兩個動作：
> ```bash
> # 【1】更新統計值 —— 八成的估計失準都是這個
> sudo -u postgres psql -d appdb -c "ANALYZE invoices;"
> # 【2】確認多久沒 ANALYZE 過
> sudo -u postgres psql -d appdb -c "SELECT relname, n_mod_since_analyze, last_autoanalyze
>   FROM pg_stat_user_tables WHERE relname='invoices';"
> ```
> ★★★ 若 `ANALYZE` 後估計還是不準，才考慮 `SET STATISTICS 1000` 或
> `CREATE STATISTICS`（欄位相關性）。**不要**用 `enable_nestloop=off` 硬壓。
> 見〈進階設定與調校〉第一、八節與〈練習 2〉。
>
> **Q5.** **(C) 可能遠超過 1.6 GB**。★★★★
> 這是從 MySQL 轉過來最容易錯的一題。`work_mem` **不是每連線一份**，
> 而是**每個需要排序或雜湊的執行計畫節點各一份**：
> ```
> 最壞 = work_mem × (查詢內的 Sort/Hash/HashAgg 節點數)
>                 × (1 + max_parallel_workers_per_gather)
>                 × 並發查詢數
>
> 一條 5-way JOIN + GROUP BY + ORDER BY 的查詢，可能同時開 8 個 work_mem
>   → 16 MB × 8 × 3（含 2 個平行 worker）= 384 MB   【單一查詢】
> ```
> 對照 MySQL 的 `sort_buffer_size`，那才是真正的「乘以 max_connections」。
> ★★★★ 所以 PostgreSQL 的 `work_mem` 要保守設，需要大排序時用
> `SET LOCAL work_mem = '256MB';` 只影響那一筆交易。
> 見〈基礎設定：記憶體預算表〉。
>
> **Q6.** ★★★★ **先查有沒有長交易，不要查 I/O。**
> `CREATE INDEX CONCURRENTLY` 的設計是：必須等到「所有在它開始之前就存在的交易」
> 全部結束，才能進入下一個階段。一條開著沒 commit 的交易就能把它卡到天荒地老。
> ```bash
> sudo -u postgres psql -c "SELECT pid, state, now()-xact_start AS xact_age, left(query,50)
>   FROM pg_stat_activity WHERE xact_start IS NOT NULL ORDER BY xact_start LIMIT 5;"
> ```
> 看到 `state = idle in transaction` 且 `xact_age` 很大就是元凶：
> ```bash
> sudo -u postgres psql -c "SELECT pg_terminate_backend(9182);"
> ```
> ★★★★ 根本解法是在設定檔加 `idle_in_transaction_session_timeout = '10min'`，
> 讓資料庫自己回收 —— 這同時也是保護 autovacuum 的關鍵設定。
> 見〈進階設定與調校〉第四節與〈排查步驟【4】〉。
>
> **Q7.** ★★★★★ 這代表距離 **XID wraparound 保護啟動只剩約 4000 萬個交易**。
> 再往下走，PostgreSQL 會在剩約 300 萬時**拒絕所有會配發新交易 ID 的操作** ——
> 也就是**整個資料庫變成唯讀**，任何 INSERT/UPDATE/DELETE 都失敗。
>
> ★★★★★ **在跑 VACUUM 之前必須先做的一件事：找出並清掉「卡住 XID 前進」的東西。**
> ```bash
> sudo -u postgres psql -c "SELECT pid, state, now()-xact_start FROM pg_stat_activity
>   WHERE xact_start IS NOT NULL ORDER BY xact_start LIMIT 5;"
> sudo -u postgres psql -c "SELECT slot_name, active, age(xmin) FROM pg_replication_slots;"
> sudo -u postgres psql -c "SELECT gid, prepared FROM pg_prepared_xacts;"
> ```
> 原因很直接：**VACUUM 不能回收「比最舊的活躍交易還新」的資料列**。
> 只要那條 128 天的 `idle in transaction` 或那個 2024 年的 inactive slot 還在，
> 你 `VACUUM` 跑到天亮 `age(datfrozenxid)` 也不會下降一分。
> 清乾淨之後才跑 `vacuumdb --all --freeze --jobs=2`。
> 見〈進階設定與調校〉第六節與〈完整實戰範例〉第一、二步。
>
> **Q8.** ★★★★ **不是索引的問題，是 VACUUM 沒跟上。**
> `Index Only Scan` 之所以能「只讀索引不回表」，是靠 **visibility map** 判斷
> 「這個 heap page 上的所有列對所有交易都可見」。而 **visibility map 只有 VACUUM 會更新**。
> ```
> Heap Fetches = 0      → ★★★★ 完美，真的沒回表
> Heap Fetches 很大     → ★★★★ visibility map 過期，等於退化成普通 Index Scan
> ```
> 該修的地方：
> ```bash
> sudo -u postgres psql -d appdb -c "VACUUM (VERBOSE) orders;"     # 立刻救急
> sudo -u postgres psql -d appdb -c "
>   ALTER TABLE orders SET (autovacuum_vacuum_scale_factor = 0.01,
>                           autovacuum_vacuum_cost_limit   = 2000);"  # 防復發
> ```
> ★★★ 這題是 PostgreSQL「效能問題其實是維護問題」的經典案例。
> 見〈進階設定與調校〉第三、六節。
>
> **Q9.** 因為 ★★★★★ **`VACUUM` 只是把死行標記成「可重用」，不會把檔案縮小**。
> 那 12 GB 的空間變成表內部的可用空間（free space map），
> 後續的 `INSERT` / `UPDATE` 會優先塞進去，但**檔案本身不會還給作業系統**。
>
> 要真的縮小，兩種做法：
> ```
> ① VACUUM FULL sessions;
>    代價：★★★★★ ACCESS EXCLUSIVE 鎖 —— 連 SELECT 都被擋，12 GB 可能鎖 15 分鐘以上
>          而且需要【與原表等量的額外磁碟空間】重建，磁碟本來就快滿的話會直接失敗
>
> ② pg_repack -d appdb -t public.sessions
>    代價：★★★ 只在最後切換的一瞬間短暫鎖表，線上可做
>          但同樣需要等量暫時空間，且要先 CREATE EXTENSION pg_repack
> ```
> ★★★★ 機關營運環境的標準答案是 **②**，`VACUUM FULL` 只在有停機時段時使用。
> 做之前一定先 `df -h /var/lib/postgresql` 確認餘裕。
> 見〈進階設定與調校〉第六節與〈練習 1〉。
>
> **Q10.** 三個可能原因與檢查指令：
> ```bash
> # ①【最常見】inactive replication slot —— 副本退役了但 slot 沒刪
> sudo -u postgres psql -c "SELECT slot_name, active, age(xmin),
>   pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained
>   FROM pg_replication_slots;"
>
> # ② archive_command 一直失敗 —— WAL 歸檔不掉就不能回收
> sudo -u postgres psql -c "SELECT archived_count, failed_count, last_failed_wal,
>   last_failed_time FROM pg_stat_archiver;"
>
> # ③ max_wal_size / wal_keep_size 設太大，或 checkpoint 一直沒跑完
> sudo -u postgres psql -c "SELECT name, setting FROM pg_settings
>   WHERE name IN ('max_wal_size','wal_keep_size','checkpoint_timeout');"
> ```
> ★★★★★ **三個都絕對不能用 `rm` 解決 —— `pg_wal/` 底下的檔案永遠不可以手動刪除。**
> 刪掉還沒 checkpoint 的 WAL 會造成**資料庫無法啟動且資料永久損毀**，
> 只能從備份還原（見 [[05-PostgreSQL-備份與還原]]）。
> 正確順序是：先擴充磁碟或清別的目錄爭取時間 → 修好根因（刪廢 slot / 修 `archive_command`）
> → 手動 `CHECKPOINT;` → PostgreSQL 自己會回收。
> ★★★ 真的走投無路才用 `pg_archivecleanup`，而且必須先確認那些 WAL 已經歸檔成功。
> 見〈常見錯誤與排錯〉與〈排查步驟【4】〉。

---

## 延伸閱讀

- [[04-PostgreSQL-設定檔與pg_hba]] —— 本篇所有「改設定」的動作，reload/restart 的判斷依據都在那一篇
- [[05-PostgreSQL-備份與還原]] —— ★★★★★ 調校前先確認備份可還原；本篇提到的 WAL 與 slot 也是 PITR 的基礎
- [[07-PostgreSQL-複寫與高可用]] —— replication slot 的正確用法，以及副本退役時該怎麼收尾
- [[08-PostgreSQL-安全強化]] —— 慢查詢日誌的個資風險、稽核軌跡與最小權限的完整做法
- [[04-MySQL-設定檔與調校]] —— 對照組：同樣是編記憶體預算，MySQL 的算法為什麼不一樣
- [[03-SQL基礎操作]] —— 索引與 SQL 語法的基礎；本篇假設你已經讀過
- [[04-Laravel-Eloquent與資料庫]] —— N+1 查詢、eager loading，以及 migration 裡怎麼用 `CONCURRENTLY`
- [[04-效能瓶頸排查方法論]] —— 打開本篇之前，先用它確認瓶頸真的在資料庫
- [[03-系統監控與告警]] —— 把 `age(datfrozenxid)`、`n_dead_tup`、命中率接進告警的做法
- PostgreSQL 官方文件：<https://www.postgresql.org/docs/17/runtime-config-resource.html>
- PostgreSQL 官方文件（Routine Vacuuming）：<https://www.postgresql.org/docs/17/routine-vacuuming.html>
- PostgreSQL 官方文件（`pg_stat_statements`）：<https://www.postgresql.org/docs/17/pgstatstatements.html>
- PostgreSQL Wiki（效能調校）：<https://wiki.postgresql.org/wiki/Performance_Optimization>
