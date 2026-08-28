---
title: "MySQL 備份與還原"
desc: "mysqldump 旗標逐一拆解、binlog 時間點還原（PITR）、三種真實還原情境與可交稽核的還原演練"
aliases: [mysqldump, binlog, PITR, XtraBackup, mysqlbinlog, 時間點還原, 還原演練]
tags: [群組/軟體與開發工具, 服務/mysql, 主題/備份, 主題/還原, 主題/LXMP]
category: 資料庫與資料儲存
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[02-MySQL-使用者與權限]]", "[[04-MySQL-設定檔與調校]]", "[[03-備份策略與還原演練]]"]
updated: 2026-08-28
---

# MySQL 備份與還原

> [!abstract] 這篇你會學到
> - **★★★★★ 做完一次真正的還原演練** —— 獨立主機還原、比對表數與列數、量到實際 RTO、產出交得出去的演練紀錄。**沒有演練過的備份不算備份**，這是全篇唯一的主張
> - 用**三層備份選型表**決定你這台該用 mysqldump、XtraBackup 還是快照，以及三者怎麼疊起來
> - **★★★★ 用 binlog 做時間點還原（PITR）**：定位那句誤操作的 position，重放到「前一個交易」
> - 走完三種真實還原情境：**誤刪一批資料**、**時間點還原**、**整機重建**
> - 寫出可排程的 `mysql-backup.sh`（加密 + 異地 + 輪替 + flock + **失敗告警**）與 `mysql-restore-drill.sh`
> - **★★★★ 知道為什麼熱狀態下 `cp -a /var/lib/mysql` 拿到的是一份開機就報 corruption 的垃圾**

## 前置知識

- [[02-MySQL-使用者與權限]] —— 本篇直接沿用該篇建立的 `backup` 帳號，不重複 GRANT 語句
- [[04-MySQL-設定檔與調校]] —— binlog 參數要寫進 `my.cnf`，設定檔位置與載入順序看那篇
- [[03-備份策略與還原演練]] —— 3-2-1 原則、RPO / RTO 的一般性定義、restic / borg 的操作、勒索軟體不可變備份的通論，**全部在那篇**。本篇只講「MySQL 這個資料庫要怎麼做」
- [[03-SQL基礎操作]] —— 比對步驟會用到 `COUNT(*)` 與 `CHECKSUM TABLE`

---

## 觀念說明

### 你手上其實有三條防線 ★★★★

```text
   每日 02:00 ──▶ ① 全備份 mysqldump / XtraBackup   RPO ≤ 24h，RTO 數十分鐘～數小時
   持續     ──▶ ② binlog 歸檔（每 5 分鐘送異地）     RPO ≤ 5 分，★★★★ PITR 的命脈
   每小時   ──▶ ③ LVM / ZFS 快照（同機，短鎖窗口）   RTO 最短，★★ 同機不算異地

   ✗ replica 不是備份 —— 誤 DELETE 會在 0.1 秒內同步過去。
     複寫解決「主機掛掉」，不解決「人做錯事」。建置見 [[06-MySQL-主從複寫]]。
```

**三層缺一不可的理由很現實**：只有 ① 你就只能回到昨天凌晨，今天一整天的案件全沒了；
只有 ②③ 而 binlog 跟資料同碟，那顆碟壞掉時 binlog 陪葬，PITR 變成空話。

### 三種備份方式的選型表 ★★★★

| 面向 | **mysqldump**（邏輯） | **mydumper**（邏輯・平行） | **★★ XtraBackup**（實體） | **LVM / ZFS 快照** | **binlog** |
| --- | --- | --- | --- | --- | --- |
| 產出 | `.sql` 文字 | 每表一檔 | InnoDB 資料檔本身 | 檔案系統時間點 | 交易事件流 |
| **備份耗時**（50 GB） | ★★★ 40～90 分 | ★★ 10～20 分 | ★ 8～15 分 | ★ 秒級 | 幾乎不佔時間 |
| **★★★★ 還原 RTO**（50 GB） | ★★★★ **3～8 小時**（重建索引） | ★★★ 1～3 小時 | ★ **15～30 分** | ★ 分鐘級 | 視重放量 |
| 只還原一張表 | ★★★ **可以** | ★★★ **可以** | ✗ 很麻煩 | ✗ | ★★ 可以（有坑） |
| 跨大版本 / 跨引擎 | ★★★ **可以** | ★★★ 可以 | ✗ **版本必須對應** | ✗ | 部分 |
| 備份時鎖庫 | ★★ `--single-transaction` 幾乎不鎖 | 幾乎不鎖 | ★ 幾乎不鎖 | ★★★ **有 FTWRL 鎖窗口** | 無 |
| 佔用空間 | 小（壓縮剩約 1/8） | 小 | ★★ 大（≈ 原尺寸） | 增量 COW | 小但持續 |
| **★★★★ 資料量門檻** | **≤ 50 GB 舒服，100 GB 以上痛苦** | ≤ 300 GB | **100 GB 以上務必用它** | 任何大小 | 任何大小 |

> [!tip] 一句話選型 ★★★
> **50 GB 以內的機關業務系統 → `mysqldump --single-transaction` + binlog 歸檔就夠了，
> 而且還原最單純、最不會出錯。** 超過 100 GB 或還原要求一小時內 →
> XtraBackup 當主力、mysqldump 當「單表救援」的備胎，兩種都留。

### ★★★★★ 為什麼不能直接 `cp` / `rsync` `/var/lib/mysql`

```text
   記憶體 Buffer Pool                   磁碟 /var/lib/mysql
   page#42 [已改，未寫回] ── ✗ ──▶ case_records.ibd  [10:00:00 的舊狀態]
   page#77 [已改，未寫回] ── ✗ ──▶ #innodb_redo      [10:00:03，LSN 已前進]
   進行中交易的 undo 半途狀態 ─ ✗ ─▶ undo_001         [10:00:07]

   ★★★★★ 三份東西互相對不上 → InnoDB 崩潰復原判定損毀，直接 abort：
      [ERROR] InnoDB: Database page corruption on disk
      [ERROR] InnoDB: Page ... log sequence number is in the future!
```

**什麼情況下複製資料目錄才算有效備份**（滿足其一）：

| 做法 | 為什麼有效 | 代價 |
| --- | --- | --- |
| ★★ **停機後**複製（stop → 等 `Shutdown complete` → cp） | 乾淨關機會把 dirty page 全刷回、redo 收尾 | 服務中斷 |
| ★★★ **快照 + `FLUSH TABLES WITH READ LOCK`** | 鎖住寫入取得一致點 → 拍快照 → 立刻解鎖 | 數百毫秒到數秒鎖窗口 |
| ★★★ **XtraBackup** | 一邊複製資料檔一邊追 redo，`--prepare` 把 redo 套回去 | 要裝、版本要對應 |

> [!danger] ★★★★★ 最危險的是「它看起來成功了」
> `rsync -a /var/lib/mysql /backup/` 會**正常結束、exit code 0、大小也對**。
> 你會以為有備份。**要到真正需要還原的那一天**，copy 回去啟動 mysqld，
> 才發現滿滿的 `InnoDB: Database page corruption`，而那時正式庫已經沒了。
> **這種備份的價值是零，但它會讓你以為價值是一百。**

### binlog 與 redo 的分工

```text
   應用 UPDATE ──▶ InnoDB 改資料 ──▶ redo log（崩潰復原用，循環覆寫，你碰不到）
                              └──▶ ★★★★ binlog（交易事件流，PITR 用這個）

   binlog.000137（ROW 格式）
   ├─ at 4523104  Anonymous_GTID          ← ★★★★★ PITR 的 --stop-position 設這裡
   ├─ at 4523183  Query  BEGIN
   ├─ at 4523341  Delete_rows             ← 誤操作就是這句
   └─ at 4523991  Xid = 88412  COMMIT
```

---

## 環境準備與安裝

### 【0】先確認版本，不要憑印象寫旗標 ★★★

```bash
mysqld --version
mysqldump --help | grep -E '^\s*--(source|master)-data'
```

預期輸出：

```text
/usr/sbin/mysqld  Ver 8.0.43-0ubuntu0.24.04.1 for Linux on x86_64 ((Ubuntu))
  --source-data[=#]   This causes the binary log position and filename to be
  --master-data[=#]   This is a deprecated alias for --source-data.    # ★ 舊名還在但已棄用
```

> [!note] 版本事實（依 MySQL 官方手冊查證，2026-08）★★★
> - **`--source-data` 從 MySQL 8.0.26 開始提供**；**8.0.26 之前只有 `--master-data`**。
>   兩者**效果完全相同**，`--master-data` 現在是 deprecated alias，官方明說未來會移除。
> - 同批改名的還有 `--dump-slave` → `--dump-replica`、`--delete-master-logs` →
>   `--delete-source-logs`、`--include-master-host-port` → `--include-source-host-port`。
> - **Ubuntu 24.04 LTS 內建 MySQL 8.0.x（≥ 8.0.36），`--source-data` 可直接用。**
> - ★★ 腳本要跨版本相容就用上面那行 `grep` 自動判斷，本篇的 `mysql-backup.sh` 就是這樣寫的。

### 【1】備份帳號需要哪些權限、為什麼

帳號在 [[02-MySQL-使用者與權限]] 已建好，這裡只列「備份這件事真正需要什麼」。

| 權限 | 為什麼需要 | 星級 |
| --- | --- | --- |
| `SELECT` / `SHOW VIEW` | 讀資料；沒有 `SHOW VIEW` 就 dump 不出 VIEW 定義 | ★★ |
| `TRIGGER` / `EVENT` | 配合 `--triggers` / `--events`。**機關系統常把日結掛在 EVENT 上** | ★★★ |
| `LOCK TABLES` | 不用 `--single-transaction` 時才需要 | ★ |
| `PROCESS` | **★★★ MySQL 8.0.21 起，沒加 `--no-tablespaces` 就需要**，缺了直接失敗 | ★★★ |
| `RELOAD`（或 `FLUSH_TABLES`） | `--source-data` 需要；**8.0.32 起 `--single-transaction` 搭 `gtid_mode=ON` 也需要** | ★★★ |
| `REPLICATION CLIENT` | `--source-data` 要跑 `SHOW MASTER STATUS` 取得 binlog 座標 | ★★★ |

```bash
mysql --login-path=backup -e "SHOW GRANTS FOR CURRENT_USER()\G"
```

預期輸出：

```text
Grants for backup@localhost: GRANT SELECT, RELOAD, PROCESS, LOCK TABLES,
  REPLICATION CLIENT, SHOW VIEW, EVENT, TRIGGER ON *.* TO `backup`@`localhost`
```

★★★ 看到 `ON *.*` 而不是 `ON appdb.*` 是正確的 —— `RELOAD` / `PROCESS` /
`REPLICATION CLIENT` 本來就是全域權限，**沒辦法只給一個資料庫**。
這也是備份帳號不能隨便給人用的原因。

### 【2】★★★★ 憑證：絕對不要把密碼寫在指令列

```bash
# ★★★★★ 絕對不要這樣做
mysqldump -u backup -pMyS3cret appdb > appdb.sql
```

理由具體到可以復現 —— 備份跑的那 40 分鐘內，任何登入這台的低權限帳號執行：

```bash
ps auxww | grep mysqldump
```

預期輸出：

```text
root  31544  9.1  0.4 ... mysqldump -u backup -pMyS3cret appdb   # ★★★★★ 密碼全文
```

再加上 `~/.bash_history`、systemd 的 `ExecStart` 日誌、監控系統抓的 process list ——
**這是內部人取得資料庫憑證最省力的一條路，不需要任何漏洞。**

**正解一：`mysql_config_editor`**

```bash
mysql_config_editor set --login-path=backup --host=localhost --user=backup --password
ls -l ~/.mylogin.cnf
```

預期輸出：

```text
Enter password:                                                  # ★ 互動輸入，不回顯
-rw------- 1 root root 216 Aug 28 09:14 /root/.mylogin.cnf       # ★★★ 必須是 600
```

之後所有指令用 `--login-path=backup`，指令列上不會出現任何密碼。

> [!warning] `.mylogin.cnf` 不是加密，是混淆 ★★★
> MySQL 官方明說它只是 obfuscation，拿到檔案的人可以還原出密碼。
> **權限 600、屬主 root、不要跟備份檔一起送異地、不要進 git。**
> 金鑰保管制度見 [[03-機密管理與金鑰保護]]。

**正解二：`--defaults-file`（跨主機部署比較好管理）**

```bash
sudo install -m 600 -o root -g root /dev/null /etc/mysql/backup.cnf
printf '[client]\nuser = backup\npassword = 換成真的密碼\nhost = localhost\n' \
  | sudo tee /etc/mysql/backup.cnf > /dev/null
# ★★★ --defaults-file 必須是【第一個】參數，放後面會被忽略且【不報錯】
sudo mysqldump --defaults-file=/etc/mysql/backup.cnf appdb > /dev/null && echo OK
```

預期輸出：`OK`

### 【3】★★★★ binlog：PITR 的命脈

編輯 `/etc/mysql/mysql.conf.d/mysqld.cnf`：

```ini
[mysqld]
server_id                    = 1
log_bin                      = /var/log/mysql/binlog/binlog
# ★★★★ 放在【與 /var/lib/mysql 不同的實體磁碟】。同碟 = 資料碟壞掉時 binlog 陪葬 = 沒有 PITR。

binlog_format                = ROW
# ★★★★ 必須 ROW。STATEMENT 重放遇到 NOW()、RAND()、UUID() 會產生【和當初不一樣的結果】。

binlog_row_image             = FULL
# ★★★ FULL 才會記錄「被刪那一列的所有欄位值」——情境一「把資料撈回來」靠這個。

binlog_expire_logs_seconds   = 1209600
# = 14 天（MySQL 8.0 / 8.4 預設 2592000 即 30 天）。
# ★★★★ 必須 >「全備份間隔 + 你發現問題所需的時間」，否則全備與 binlog 之間會斷鏈。

sync_binlog                  = 1
# ★★★ 1 = 每次提交都 fsync，主機瞬斷不掉 binlog，效能代價約 5～15%。正式業務庫用 1。

gtid_mode                    = ON
enforce_gtid_consistency     = ON
```

```bash
sudo install -d -m 750 -o mysql -g mysql /var/log/mysql/binlog
sudo systemctl restart mysql
mysql --login-path=backup -e "
SELECT VARIABLE_NAME, VARIABLE_VALUE FROM performance_schema.global_variables
WHERE VARIABLE_NAME IN ('log_bin','binlog_format','binlog_row_image',
  'binlog_expire_logs_seconds','sync_binlog','gtid_mode');"
```

預期輸出：

```text
+----------------------------+----------------+
| binlog_expire_logs_seconds | 1209600        |   # ★★★★ 不能小於全備間隔＋發現時間
| binlog_format              | ROW            |   # ★★★★ 必須 ROW
| binlog_row_image           | FULL           |
| gtid_mode                  | ON             |
| log_bin                    | ON             |   # ★ MySQL 8.0 起預設就是 ON
| sync_binlog                | 1              |
+----------------------------+----------------+
```

```bash
# ★★★ 確認 binlog 真的在另一顆磁碟（不是只是另一個目錄）
df -h /var/lib/mysql /var/log/mysql/binlog | awk '{print $1, $6}'
```

預期輸出：

```text
/dev/mapper/vg0-data   /var/lib/mysql
/dev/mapper/vg1-binlog /var/log/mysql/binlog     # ★★★★ 不同 Filesystem 才算數
```

兩行是**同一個 Filesystem** → 你現在沒有 PITR 能力，先把這件事排進工單。

### 【4】備份目錄佈局

```bash
sudo install -d -m 700 -o root -g root /var/backups/mysql/{full,binlog,drill,logs}
```

★★★ `700` 不是龜毛 —— 這底下每一個檔案都是**整個機關的個資全集**，
`755` 等於讓機器上任何帳號都能 `cp` 走一份。

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> sudo dnf install -y mysql-server mysql
> sudo systemctl enable --now mysqld          # ★★★ 服務名是 mysqld，不是 mysql
>
> # ★★★ 設定檔位置：Ubuntu 是 /etc/mysql/mysql.conf.d/mysqld.cnf
> #     RHEL 是 /etc/my.cnf 或 /etc/my.cnf.d/*.cnf
> sudo vi /etc/my.cnf.d/binlog.cnf
>
> # ★★★★ SELinux：binlog 換到非預設路徑後 mysqld 會被擋，
> #      症狀是啟動失敗、journalctl 出現 Permission denied，但 ls -l 看起來完全正確。
> sudo dnf install -y policycoreutils-python-utils
> sudo semanage fcontext -a -t mysqld_db_t "/var/log/mysql/binlog(/.*)?"
> sudo restorecon -Rv /var/log/mysql/binlog
> sudo ausearch -m AVC -ts recent | tail      # ★★ 有 denied 就是 SELinux
> ```
> ★★★ 其餘 mysqldump / mysqlbinlog 旗標與 Ubuntu **完全相同**，後續指令可直接沿用。

> [!info]- MariaDB 對照（機關的 RHEL 常常預設裝的是這個）
> `dnf install mariadb-server` 裝到的是 MariaDB，**不是 MySQL**。會咬人的差異：
>
> | 項目 | MySQL 8.x | MariaDB 10.6+ / 11.x |
> | --- | --- | --- |
> | dump 指令 | `mysqldump` | **`mariadb-dump`**（`mysqldump` 只是相容軟連結） |
> | binlog 工具 | `mysqlbinlog` | `mariadb-binlog` |
> | binlog 座標旗標 | **`--source-data`**（8.0.26+） | ★★★ **只有 `--master-data`** |
> | 實體備份 | Percona XtraBackup | ★★★ **`mariabackup`**（PXB 8.x **不支援** MariaDB） |
> | 匯出帳號權限 | 得自己跑 `SHOW GRANTS` 迴圈 | ★★ 內建 **`mariadb-dump --system=users`** |
> | binlog 保留 | `binlog_expire_logs_seconds` | 舊版是 `expire_logs_days` |
> | GTID | `UUID:序號` | ★★★ **完全不同的格式**（`domain-server-seq`），互不相容 |
>
> ★★★★ **最要命的一點：MySQL 的 dump 大多能灌進 MariaDB，
> 但 MariaDB 的 dump 灌回 MySQL 常常失敗**（`ROW_FORMAT`、`utf8mb3` 別名、`mariadb_schema` 註記）。
> **接手一台機器的第一件事是 `mysqld --version` 看清楚它到底是誰。**

---

## 進階應用

### mysqldump：每一個旗標為什麼要加 ★★★★

```bash
sudo mysqldump --login-path=backup \
  --single-transaction --source-data=2 --flush-logs \
  --routines --triggers --events \
  --set-gtid-purged=COMMENTED \
  --hex-blob --default-character-set=utf8mb4 \
  --no-tablespaces --quick \
  --databases appdb > /var/backups/mysql/full/appdb-20260828T020000.sql
```

| 旗標 | 不加的後果 | 星級 |
| --- | --- | --- |
| `--single-transaction` | **會用 `LOCK TABLES` 鎖全庫**，備份 40 分鐘＝服務卡 40 分鐘 | ★★★ |
| `--source-data=2` | dump 裡**沒有 binlog 座標** → 不知道從哪個 position 重放 → **PITR 直接沒了** | ★★★★ |
| `--flush-logs` | binlog 不會在備份點切檔，重放要在舊檔中間找起點，麻煩又易錯 | ★★ |
| `--routines` | **預存程序與函式全部不見**，還原後應用報 `PROCEDURE ... does not exist` | ★★★★ |
| `--triggers` | 觸發器不見（預設其實是開的，**但寫出來讓下一個人看得懂**） | ★★ |
| `--events` | **排程事件不見**。日結、月報常掛在 EVENT 上，「沒人發現，直到月底報表是空的」 | ★★★★ |
| `--set-gtid-purged=COMMENTED` | 預設 `AUTO` 會塞一句**改寫目標主機 `gtid_purged`** 的語句，灌進演練機會炸 | ★★★ |
| `--hex-blob` | BLOB / BINARY 遇到編碼轉換會**靜默損毀二進位資料**（附件、簽章檔） | ★★★ |
| `--default-character-set=utf8mb4` | 中文與 emoji 變 `?`，**還原完才發現，而且無法回頭** | ★★★★ |
| `--no-tablespaces` | 8.0.21 起沒加就需要 `PROCESS` 權限，缺了整個備份失敗 | ★★★ |
| `--quick` | 大表整張載入記憶體 → mysqldump 被 OOM killer 砍掉 | ★★ |
| `--databases appdb` | 不加就**不會產生 `CREATE DATABASE`**，還原到空機器第一步就失敗 | ★★★ |

> [!warning] ★★★ `--single-transaction` 的兩個致命限制
> **① 只對 InnoDB 有效。** 官方原文是「only InnoDB tables are dumped in a consistent state」——
> 庫裡若還有 MyISAM 或 MEMORY 表，**那幾張表在備份期間仍會變動**。先確認：
> ```bash
> mysql --login-path=backup -e "
> SELECT TABLE_SCHEMA, TABLE_NAME, ENGINE FROM information_schema.TABLES
> WHERE ENGINE NOT IN ('InnoDB') AND TABLE_SCHEMA NOT IN
>   ('mysql','information_schema','performance_schema','sys');"
> ```
> 預期輸出（乾淨的環境）：`Empty set (0.01 sec)`
>
> **② 備份期間若有 DDL，一致性一樣會被破壞。** 官方明列會出事的語句：
> **`ALTER TABLE` / `CREATE TABLE` / `DROP TABLE` / `RENAME TABLE` / `TRUNCATE TABLE`**。
> consistent read **不隔離**這些語句，結果是 `SELECT` 讀到錯的內容或整個備份失敗。
> **所以備份時段要跟 Laravel 的 `php artisan migrate` 排開**（見 [[06-Vue-Laravel完整部署實戰]]）。

> [!note] `--set-gtid-purged` 該選哪個值 ★★★
> `AUTO`（預設，GTID 有開就寫入）／`ON`（一定寫入，沒開 GTID 就報錯）／`OFF`（完全不寫）／
> **`COMMENTED`（8.0.17 起，寫入但整句註解掉）**。
> ★★★ **還原演練、灌進暫存庫、遷移到已有資料的主機 —— 一律用 `COMMENTED`。**
> 選 `AUTO`／`ON` 灌進既有主機會撞到
> `ERROR 1840 (HY000): @@GLOBAL.GTID_PURGED can only be set when @@GLOBAL.GTID_EXECUTED is empty.`
> —— 還原到一半停住，這是演練時最常撞到的牆。

### 壓縮、加密、串流到異地 ★★★★

```bash
# ★★ 一條 pipeline 完成：dump → 壓縮 → 加密，中間【不落地未加密的暫存檔】
sudo mysqldump --login-path=backup --single-transaction --source-data=2 \
     --routines --triggers --events --set-gtid-purged=COMMENTED \
     --hex-blob --default-character-set=utf8mb4 --no-tablespaces --quick \
     --databases appdb \
  | gzip -6 \
  | gpg --batch --yes --trust-model always --recipient backup@example.gov.tw --encrypt \
  > /var/backups/mysql/full/appdb-20260828T020000.sql.gz.gpg
ls -lh /var/backups/mysql/full/appdb-20260828T020000.sql.gz.gpg
```

預期輸出：

```text
-rw------- 1 root root 1.4G Aug 28 02:41 appdb-20260828T020000.sql.gz.gpg
```

```bash
# ★★★ 備份主機只匯入【公鑰】，私鑰留在離線的金鑰保管機
sudo gpg --list-keys backup@example.gov.tw
```

預期輸出：

```text
pub   ed25519 2026-01-15 [SC]
      3F2A9C7D8B1E4A6F0D2C5B8E7A4F1C9D3E6B2A80
uid           [ unknown] MySQL Backup <backup@example.gov.tw>
sub   cv25519 2026-01-15 [E]
```

★★★★ `sec`（私鑰）**不應該**出現在這台的輸出裡。出現了就是設定錯了 ——
備份主機被打下來時，攻擊者就能直接解開所有歷史備份。

> [!danger] ★★★★ 沒加密的 dump 檔 = 一次個資外洩事件
> 一份 `appdb.sql` 裡有全部承辦人姓名、身分證字號、聯絡電話、案件內容。
> 它被 rsync 到異地、放進 NAS、被誰接手時複製到隨身碟 —— **每一次移動都是一次外洩風險**。
> **一律加密**（`gpg` 或 `age`），而且 **★★★★ 金鑰不可以跟備份放在同一台、同一顆碟**：
> 勒索軟體加密整台 NAS 的時候，你的解密金鑰也一起被加密了。
> 制度面見 [[03-機密管理與金鑰保護]]，法規面見 [[07-台灣資安法規與個資法]]。

> [!warning] ★★★★ pipeline 會吞掉失敗
> `mysqldump | gzip | gpg > out` 的 exit code **是最後一個指令的**。
> mysqldump 在第 900 秒斷線失敗，gzip 與 gpg 照樣把「半截內容」處理完並 exit 0，
> **你得到一個看起來很正常、其實少了一半資料的加密檔**。
> 解法是 `set -o pipefail` ＋ 檢查 `PIPESTATUS`（本篇腳本已含），期待 `0 0 0`。

### 備份驗證：「檔案存在」不是驗證 ★★★★

| 層級 | 做法 | 能發現什麼 | 星級 |
| --- | --- | --- | --- |
| L0 | 檔案存在、大小 > 0 | 幾乎什麼都發現不了 | ★ |
| L1 | `gpg -d \| gzip -t` | 傳輸截斷、磁碟壞塊 | ★★ |
| L2 | 檔尾有 `-- Dump completed` | **mysqldump 中途死掉** | ★★★ |
| L3 | 還原到暫存庫 + 表數比對 | schema 缺漏 | ★★★★ |
| **L4** | **還原 + 列數比對 + `CHECKSUM TABLE`** | **內容真的對不對** | ★★★★★ |

```bash
F=/var/backups/mysql/full/appdb-20260828T020000.sql.gz.gpg
gpg --quiet --decrypt "$F" | gzip -t && echo "gzip OK"          # L1
gpg --quiet --decrypt "$F" | zcat | tail -1                     # L2
gpg --quiet --decrypt "$F" | zcat | grep -m1 'SOURCE_LOG_POS'   # 取 PITR 起點
```

預期輸出：

```text
gzip OK
-- Dump completed on 2026-08-28  2:41:07        # ★★★★ 沒這行 = 備份不完整，不要留
-- CHANGE REPLICATION SOURCE TO SOURCE_LOG_FILE='binlog.000137', SOURCE_LOG_POS=451062;
```

★★★★ **把最後那兩個值抄進當天的備份日誌。** 事故當下你要回答的第一個問題就是
「全備份對應到哪個 binlog 的哪個位置」，沒有它，PITR 只能靠猜時間。

### binlog 歸檔：讓 binlog 活得比資料碟久 ★★★★

**做法 A：`mysqlbinlog --raw --stop-never`（準即時，推薦）**

```bash
sudo -u mysql mysqlbinlog --read-from-remote-server \
  --host=127.0.0.1 --login-path=backup \
  --raw --stop-never --result-file=/var/backups/mysql/binlog/ binlog.000137
```

這個行程**不會結束**，會像 replica 一樣持續把新事件寫進本機檔案。
★★★ 用 systemd 服務跑它、`Restart=always`，再用 [[02-rsync-同步與備份]] 每 5 分鐘同步異地。

**做法 B：定時 `FLUSH BINARY LOGS` + 複製已封檔的（簡單、RPO 較差）**

```bash
mysql --login-path=backup -e "FLUSH BINARY LOGS;"
rsync -a --ignore-existing --exclude='*.index' \
  /var/log/mysql/binlog/ backup@nas.internal.example.gov.tw:/srv/backup/mysql/binlog/
```

★★★ **只複製「已封檔」的 binlog**，正在寫的那個複製過去是半截的；
`--ignore-existing` 就是避免把遠端已完整的檔案覆蓋成半截。
★★★★ **不要用 `PURGE BINARY LOGS` 手動清，除非確定歸檔已成功推到異地** —— PITR 鏈會斷在那裡。

### PITR：在 binlog 裡找到那句誤操作 ★★★★★

目標：**找出「誤操作那個交易的起始 position」，重放到它之前。**

**【1】用時間窗口 + 解碼 ROW 事件把它撈出來**

```bash
sudo mysqlbinlog --no-defaults --base64-output=DECODE-ROWS --verbose --verbose \
  --start-datetime="2026-08-26 13:00:00" --stop-datetime="2026-08-26 15:00:00" \
  /var/log/mysql/binlog/binlog.000137 \
  | grep -n -B 12 'DELETE FROM `appdb`.`case_records`' | head -20
```

預期輸出（節錄）：

```text
1841-# at 4523104
1842-#260826 14:37:09 server id 1  end_log_pos 4523183  GTID  last_committed=8823
1843-SET @@SESSION.GTID_NEXT= 'a1b2c3d4-...-000000000001:99213'/*!*/;
1844-# at 4523183                            ← ★★★★★ 交易起點（BEGIN 之前）
1846-BEGIN
1858:### DELETE FROM `appdb`.`case_records`  ← ★★★★ 找到了
1860-###   @1=100231
1861-###   @2='114-A-0231'                   # ★★★ binlog_row_image=FULL 才看得到欄位值
```

★★★★ **`--base64-output=DECODE-ROWS -vv` 是把 ROW 事件翻成人看得懂的唯一方法**，
不加只會看到一堆 base64。★★★ 印出來的 `### DELETE ...` 是**註解不是可執行 SQL**，別直接複製執行。

**【2】確認交易邊界**

```bash
sudo mysqlbinlog --no-defaults --start-position=4523104 --stop-position=4524100 \
  /var/log/mysql/binlog/binlog.000137 | grep -E '^# at |Xid|GTID|BEGIN|COMMIT'
```

預期輸出：

```text
# at 4523104
#260826 14:37:09 ... GTID ...
# at 4523183
BEGIN
# at 4523991
#260826 14:37:11 server id 1  end_log_pos 4524022  Xid = 88412
COMMIT/*!*/;
```

**★★★★★ 所以 PITR 的停止點是 `--stop-position=4523104`** —— **交易起點，不是 COMMIT 之後**。
停在 `4524022` 等於把誤刪也重放了一遍，整件事白做。

**【3】重放**

```bash
# ★★★ --skip-gtids：不汙染目標主機的 gtid_executed，否則之後真正的複寫會亂掉。
# ★★★ --disable-log-bin：重放產生的變更不再寫進目標主機自己的 binlog。
sudo mysqlbinlog --no-defaults --skip-gtids --disable-log-bin \
  --start-position=451062 --stop-position=4523104 \
  /var/backups/mysql/binlog/binlog.000137 \
  | mysql --login-path=restore appdb_recover
echo "exit=$?"
```

預期輸出：`exit=0`

> [!warning] ★★★ `--database=appdb` 的過濾有坑
> 在 **ROW 格式**下過濾還算可靠，但在 **STATEMENT 格式**下它是靠「語句當時的預設資料庫」判斷，
> `UPDATE otherdb.t SET ...` 這種跨庫語句會被**錯誤地保留或錯誤地丟棄**。
> 這是 `binlog_format=ROW` 不可妥協的另一個理由。

> [!note] GTID 模式下的差異 ★★★★
> ```bash
> sudo mysqlbinlog --no-defaults --exclude-gtids='a1b2c3d4-...-000000000001:99213' \
>   /var/backups/mysql/binlog/binlog.000137 | mysql --login-path=restore appdb_recover
> ```
> ★★★★ **這是 GTID 的殺手級用途：把「那一個交易」精準挖掉，前後的正常交易全部保留。**
> 用 position 做不到（position 是連續區間）。代價是要先在【1】的輸出裡把
> `SET @@SESSION.GTID_NEXT=` 那個 GTID 抄出來。

### Percona XtraBackup 快速入門（100 GB 以上的主力）

> [!warning] 未實機驗證
> 本節依 Percona 官方文件撰寫，本手冊沒有百 GB 級的實機環境可驗證還原時間。
> 實作前請對照你手上的 MySQL 版本與 Percona 官方文件。

★★★ **版本必須對應**：XtraBackup 8.0 系列備份 MySQL 8.0.x；XtraBackup 8.4 系列備份
MySQL 8.4，且**不支援** MySQL 8.0 或 9.x。版本錯配的症狀是備份跑得出來、
`--prepare` 或啟動時才失敗 —— 又是一個「要到還原那天才發現」的坑。

```bash
# ① backup
sudo xtrabackup --backup --login-path=backup --target-dir=/var/backups/mysql/xtra/2026-08-28
# ② prepare ★★★★ 把 redo 套用回去——這一步就是「cp 做不到的事」，沒 prepare 的備份不能用
sudo xtrabackup --prepare --target-dir=/var/backups/mysql/xtra/2026-08-28
# ③ copy-back
sudo systemctl stop mysql
sudo rm -rf /var/lib/mysql/*                    # ★★★★★ 不可逆，做之前先確認你在哪台機器
sudo xtrabackup --copy-back --target-dir=/var/backups/mysql/xtra/2026-08-28
sudo chown -R mysql:mysql /var/lib/mysql        # ★★★ 忘了這行 mysqld 會起不來
sudo systemctl start mysql
cat /var/backups/mysql/xtra/2026-08-28/xtrabackup_binlog_info
```

預期輸出：

```text
xtrabackup: Transaction log of lsn (48219336) to (48219336) was copied.
260828 02:18:44 completed OK!          # ★★★★ 沒有 completed OK! 就是失敗
binlog.000137	451062	a1b2c3d4-...:1-99212   # ★★★★ PITR 起點，XtraBackup 幫你記好了
```

**分工建議 ★★★**：XtraBackup 每日一次當「整庫救援」，mysqldump 每日一次當
「單表救援 + 跨版本保險」。兩者都留，磁碟成本遠低於「還原不了」的成本。

### LVM / ZFS 快照 + 一致點

```bash
# ★★★ 鎖窗口要盡可能短：一個 session 拿鎖，另一個拍快照，然後立刻解鎖
mysql --login-path=backup -e "FLUSH TABLES WITH READ LOCK; SELECT SLEEP(10);" &
sleep 1
sudo lvcreate --size 20G --snapshot --name mysqldata-snap /dev/vg0/data
wait
```

預期輸出：`Logical volume "mysqldata-snap" created.`

> [!danger] ★★★★ FTWRL 是全域讀鎖，不是「輕輕碰一下」
> 它會**等待所有進行中的長查詢結束**才拿得到鎖。有一句跑了 5 分鐘的報表 SQL，
> 你的「短暫鎖窗口」就是 5 分鐘的**全站寫入停擺**。先確認：
> ```bash
> mysql --login-path=backup -e "
> SELECT ID, USER, TIME, LEFT(INFO,60) FROM information_schema.PROCESSLIST
> WHERE COMMAND != 'Sleep' AND TIME > 5 ORDER BY TIME DESC;"
> ```
> 預期輸出 `Empty set` 才可以動手。ZFS 的 `zfs snapshot` 同理。
> 檔案系統快照本身見 [[24-進階儲存-ZFS與Btrfs]] 與 [[15-磁碟分割與掛載]]。

★★ **快照是同機的，不算異地備份**。它擋得住「誤 DROP TABLE」，
擋不住「機房淹水」或「整台被勒索軟體加密」—— 它是**縮短 RTO 的工具**，不是備份策略的全部。

### ★★★★★ 還原演練：本篇的核心

> [!danger] 這一段如果你只讀一段，就讀這段
> **備份的價值不在備份那一刻，在還原那一刻。**
> 而「還原能不能成功」有太多變數：dump 檔壞了、gpg 私鑰不在手上、目標主機版本不同、
> `gtid_purged` 卡住、磁碟不夠大、還原要 6 小時但主管以為是 30 分鐘 ——
> **這些全部只有真的做一次才會知道。★★★★★ 沒有演練過的備份不算備份。**

**演練要回答的五個問題**（每季至少一次，每次都要留紀錄）：

| # | 問題 | 怎麼量 | 星級 |
| --- | --- | --- | --- |
| 1 | 備份檔**解得開**嗎？ | `gpg -d \| gzip -t` | ★★★ |
| 2 | 它**灌得進去**嗎？ | 還原到 drill 庫，看 exit code | ★★★★ |
| 3 | 灌進去的**東西對嗎**？ | 表數 / 關鍵表列數 / `CHECKSUM TABLE` | ★★★★★ |
| 4 | **要多久**？ | 計時，這才是真正的 RTO | ★★★★ |
| 5 | **誰做得出來**？ | 換一個人照文件做一次 | ★★★★ |

第 5 點最常被忽略：**只有你一個人會還原，等於這個機關的 RTO 是「你的請假天數」。**

```bash
# ★★★ 用容器起一台版本相同的 MySQL 當演練標靶，不要用正式主機
docker run -d --name mysql-drill -e MYSQL_ROOT_PASSWORD="$(openssl rand -base64 24)" \
  -v /var/backups/mysql/drill:/drill mysql:8.0.43
docker exec mysql-drill mysqladmin --version
```

預期輸出：

```text
mysqladmin  Ver 8.0.43 for Linux on x86_64 (MySQL Community Server - GPL)
```

★★★★ tag 寫 `latest` 是演練的常見自欺：演練用 8.4、正式庫是 8.0，
**你驗證的是一個你根本沒有的環境**。容器操作見 [[01-容器概念與Docker安裝]]。

**演練紀錄表（要交稽核的，欄位固定）**：

| 欄位 | 範例值 | 為什麼稽核要看 |
| --- | --- | --- |
| 演練日期 / 演練人員 / **覆核人員** | 2026-08-28 / 王○○ / 李○○ | ★★★ 責任歸屬，**不能自己演練自己簽** |
| 備份檔名與產生時間 | `appdb-20260827T020000.sql.gz.gpg` / 08-27 02:00 | 可追溯、對照 RPO |
| **實際 RTO** | **00:41:22** | ★★★★ 這是唯一有意義的 RTO |
| 表數 期望/實得 | 128 / 128 | ★★★★ |
| 關鍵表列數 期望/實得 | `case_records` 1,284,003 / 1,284,003 | ★★★★★ |
| CHECKSUM 比對 | 全數相符 | ★★★★ |
| **發現問題** | gpg 私鑰不在備援機，臨時取得花了 12 分鐘 | ★★★★ **這一欄才是演練的產出** |
| 改善措施與期限 | 私鑰離線副本入保管箱，2026-09-05 前 | 下次演練要驗收 |

★★★★ **「發現問題」欄寫「無」的演練，通常是沒有認真做。**
第一次演練幾乎一定會撞到東西 —— 那正是你想在「不是事故當天」撞到的。

### 三種還原情境

**情境一：誤 DELETE 了一批資料 ★★★★★**

> [!danger] ★★★★ 絕對不要把備份直接覆蓋回正式庫
> 承辦 14:37 誤刪 3000 筆案件，你 15:10 拿昨天的全備份 `mysql appdb < backup.sql` ——
> **14:37 到 15:10 之間其他 20 位同仁正常建立、修改的所有資料，全部被抹掉。**
> 你把一件「刪了 3000 筆」的事故，升級成「全機關半天的工作消失」的事故，
> **而且第二次是你造成的，還沒有備份可以救。**

```text
   正式庫 appdb（照常運作，不要動）
     ① 立刻凍結那張表的寫入，保全現場
   備援機／容器
     ② 還原昨天全備份 ──▶ appdb_recover
     ③ 重放 binlog 到「誤操作前一個交易」
     ④ appdb_recover 裡就有那 3000 筆的完整內容
   ⑤ 只把那 3000 筆 INSERT 回正式庫（不覆蓋任何其他東西）
   ⑥ 比對筆數、解除凍結、記錄時間軸
```

**情境二：PITR 時間點還原（整庫回到某一秒）★★★★**

適用於「災難是全庫性的」：跑錯 migration 把整批表結構改壞、被寫入大量垃圾資料、
應用有 bug 連續三小時寫錯值。做法是「還原全備份 → 重放 binlog 到誤操作前一秒」。
★★★ 這種還原**會丟掉該時間點之後的所有正常交易**，
決定做之前要先確認「那之後的資料是不是本來就沒價值」。不確定就走情境一。

**情境三：整台機器毀掉 ★★★★**

```text
【1】新機安裝【完全相同】的 MySQL 版本   ★★★★ 8.0.43 就是 8.0.43
【2】套用相同的 my.cnf（含 innodb_data_file_path 等啟動就檢查的參數）
【3】還原資料
【4】還原帳號與權限  ← ★★★ 這一步有取捨，見下
【5】應用連線驗證 →【6】服務恢復檢查表
```

> [!warning] ★★★ `mysql` 系統庫要不要一起還原
> **不要直接把來源機的 `mysql` schema 灌到新機**：
> ① MySQL 8.0 的 data dictionary 是 InnoDB 表，跨小版本灌容易出怪事；
> ② 你會把來源機**所有帳號、包含已離職人員的帳號**原封不動搬過去；
> ③ 新機的 `root@localhost`、`mysql.session`、`mysql.sys` 會被蓋掉，嚴重時**新機直接無法登入**。
>
> **替代做法：另外備份 `SHOW GRANTS` 的輸出**，每天跟全備份一起跑：
> ```bash
> mysql --login-path=backup -N -B -e "
>   SELECT CONCAT('SHOW GRANTS FOR ', QUOTE(user), '@', QUOTE(host), ';')
>   FROM mysql.user WHERE user NOT LIKE 'mysql.%' AND user <> 'root';" \
> | mysql --login-path=backup -N -B | sed 's/$/;/' > /var/backups/mysql/full/grants.sql
> ```
> 預期輸出（檔案內容節錄）：
> ```text
> GRANT SELECT, INSERT, UPDATE, DELETE ON `appdb`.* TO `appuser`@`10.10.20.%`;
> ```
> ★★★ 這份檔案**是人看得懂的**，還原時可以先審一遍再決定哪些帳號要重建 ——
> 這正是災難重建時**順手清掉離職帳號**的最佳時機。
> ★★ 注意它**不含密碼**（`SHOW GRANTS` 不輸出密碼雜湊），
> 應用帳號密碼要從 `.env` 或機密管理系統取得。MariaDB 有捷徑：`mariadb-dump --system=users`。

**服務恢復檢查表**：

| # | 檢查項 | 指令 | 預期結果 |
| --- | --- | --- | --- |
| 1 | mysqld 起來了 | `systemctl is-active mysql` | `active` |
| 2 | 無 InnoDB 錯誤 | `journalctl -u mysql -p err -n 50` | 無 `corruption` / `crash` |
| 3 | 表數對 | `SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='appdb'` | 與紀錄相同 |
| 4 | 關鍵表列數對 | `SELECT COUNT(*) FROM appdb.case_records` | 與紀錄相同 |
| 5 | 預存程序在 | `... FROM information_schema.ROUTINES ...` | > 0 |
| 6 | ★★★ 排程事件在 | `... FROM information_schema.EVENTS ...` | 與紀錄相同 |
| 7 | 應用連得上 | `php artisan tinker --execute="DB::select('select 1');"` | 無例外 |
| 8 | ★★★★ 新的備份跑得起來 | 手動跑一次 `mysql-backup.sh` | `completed OK` |

★★★★ 第 8 項最常被忘記：**服務恢復了但備份沒恢復，
你正處在「下一次事故沒有底牌」的狀態。**

### 排程實務

```ini
# /etc/systemd/system/mysql-backup.service
[Unit]
Description=MySQL full backup
After=mysql.service
Requires=mysql.service
[Service]
Type=oneshot
ExecStart=/usr/local/bin/mysql-backup.sh
User=root
Nice=10
IOSchedulingClass=idle          # ★★★ 讓備份的 I/O 讓路給正式流量
```

```ini
# /etc/systemd/system/mysql-backup.timer
[Timer]
OnCalendar=*-*-* 02:00:00
RandomizedDelaySec=600          # ★★ 多台主機錯開，避免同時打爆 NAS 與網路
Persistent=true                 # ★★★ 機器當時關機的話，開機後補跑
[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now mysql-backup.timer
systemctl list-timers mysql-backup.timer --no-pager
```

預期輸出：

```text
NEXT                        LEFT     LAST PASSED UNIT               ACTIVATES
Sat 2026-08-29 02:04:31 CST 11h left n/a  n/a    mysql-backup.timer mysql-backup.service
```

★★★ **systemd timer 比 cron 好在三點**：`Persistent=true` 會補跑、失敗有 journal 可查、
`IOSchedulingClass` 可以限流。完整比較見 [[02-systemd-timer與cron選型]]。

> [!tip] ★★★ 備份會汙染 buffer pool
> mysqldump 把整個資料庫掃一遍，會把 **buffer pool 裡原本熱的頁全部擠掉**。
> 症狀是**備份結束後一到兩小時應用明顯變慢**（查詢從記憶體命中變成打磁碟）。三種緩解：
> ① 排在真正的離峰（機關通常 02:00～04:00）；② `--single-transaction` 搭 `--quick`；
> ③ ★★ 大庫改用 XtraBackup —— 它讀的是**資料檔本身**，完全不經過 buffer pool。
> buffer pool 調校見 [[04-MySQL-設定檔與調校]]。

**保留策略（GFS：日 7 + 週 4 + 月 12）**：★★★ 實務上用**檔名分艙**比用 `find -mtime` 湊條件可靠得多。
本篇腳本備份時就寫進 `full/daily/`、`full/weekly/`、`full/monthly/` 三個目錄，
各自獨立輪替，邏輯一眼看得懂，也不會因為某天 `find` 條件寫錯就把月備份刪掉。

---

## 完整實戰範例

### 情境：某機關業務系統，週三下午的一句 DELETE

```text
   2026-08-26（三）14:37  承辦在正式庫執行 DELETE FROM case_records WHERE ...
                          WHERE 條件寫錯（實際變成全表），刪掉當年度 3,000 筆案件
   2026-08-26（三）15:02  科員發現查不到案件，通報資訊室
```

### 【1】立刻凍結寫入、保全現場（15:05）★★★★

```bash
# ★★★★ 第一優先不是「開始還原」，是「不要讓情況繼續變壞」
sudo -u www-data php /var/www/appdb/artisan down --render="errors::503"
# 應用改不動時的手段：直接收回寫入權限
mysql --login-path=admin -e "
REVOKE INSERT, UPDATE, DELETE ON appdb.* FROM 'appuser'@'10.10.20.%'; FLUSH PRIVILEGES;"
# ★★★★ 立刻切一個 binlog 並複製一份到安全處——不能讓它因容量或保留期被輪掉
mysql --login-path=backup -e "FLUSH BINARY LOGS;"
sudo install -d -m 700 /var/backups/mysql/incident-20260826
sudo cp -a /var/log/mysql/binlog/binlog.00013* /var/backups/mysql/incident-20260826/
```

預期輸出：

```text
INFO  Application is now in maintenance mode.
```

★★★ 用 `cp -a` 而不是 `mv`：**現場要保持原狀**，
之後若涉及行政責任或資安事件通報，原始檔案要留著。通報流程見 [[04-備份災難復原與入侵應變]]。

### 【2】確認底牌：全備份與 binlog 完整性（15:08）

```bash
F=$(ls -1t /var/backups/mysql/full/daily/*.sql.gz.gpg | head -1); echo "$F"
gpg --quiet --decrypt "$F" | zcat | tail -1
gpg --quiet --decrypt "$F" | zcat | grep -m1 'SOURCE_LOG_FILE'
```

預期輸出：

```text
/var/backups/mysql/full/daily/appdb-20260826T020000.sql.gz.gpg    # ★ 今天凌晨的，很好
-- Dump completed on 2026-08-26  2:41:07                          # ★★★★ 完整
-- CHANGE REPLICATION SOURCE TO SOURCE_LOG_FILE='binlog.000137', SOURCE_LOG_POS=451062;
```

★★★★ **RPO 已經確定**：全備份是 02:41、binlog 完整 → 理論上可以還原到 14:37:08 那一秒，資料零損失。

### 【3】在備援機還原全備份到 `appdb_recover`（15:12～15:48）

```bash
mysql --login-path=restore -e "
CREATE DATABASE appdb_recover CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"

time ( gpg --quiet --decrypt "$F" | zcat \
  | grep -v '^CREATE DATABASE' \
  | sed 's/^USE `appdb`;/USE `appdb_recover`;/' \
  | mysql --login-path=restore appdb_recover )
```

預期輸出：

```text
real	36m11.482s          # ★★★★ 這就是你的實際 RTO，記下來
user	4m02.113s
```

★★★★ 那兩行 `grep -v` / `sed` 不是裝飾 —— `--databases` 產生的 dump 裡有
`CREATE DATABASE appdb` 與 `USE appdb`，**不處理就會灌回正式庫的 appdb**，
在事故現場這是會讓事情變得無法挽回的一步。

### 【4】重放 binlog 到誤操作的前一個交易（15:50）

依前面「PITR」那節找出 position（此例為 `4523104`），然後：

```bash
sudo mysqlbinlog --no-defaults --skip-gtids --disable-log-bin \
  --start-position=451062 --stop-position=4523104 \
  /var/backups/mysql/incident-20260826/binlog.000137 \
  | sed 's/^USE `appdb`/USE `appdb_recover`/' \
  | mysql --login-path=restore appdb_recover
mysql --login-path=restore -e "SELECT COUNT(*) AS n FROM appdb_recover.case_records;"
```

預期輸出：

```text
+---------+
| n       |
+---------+
| 1284003 |          # ★★★★ 誤刪【之前】的完整筆數
+---------+
```

### 【5】只把那 3000 筆撈回正式庫（16:05）★★★★★

```bash
# ★★★ 先看清楚差集有多少——不要憑感覺就開始寫入
mysql --login-path=admin -e "
SELECT COUNT(*) AS missing FROM appdb_recover.case_records r
LEFT JOIN appdb.case_records p ON p.id = r.id WHERE p.id IS NULL;"
```

預期輸出：

```text
+---------+
| missing |
+---------+
|    3000 |          # ★★★★ 數字對得上才往下走；對不上就停下來重新確認範圍
+---------+
```

```bash
# ★★★★ 正式寫入前，先對【正式庫】再備一份——這是回滾的唯一憑藉
sudo /usr/local/bin/mysql-backup.sh --tag pre-recover --skip-remote

# ★★★ 用交易包起來，錯了可以 ROLLBACK（第一次請用互動式 mysql 逐句執行）
mysql --login-path=admin appdb
```

```sql
START TRANSACTION;
INSERT INTO case_records
SELECT * FROM appdb_recover.case_records r
WHERE NOT EXISTS (SELECT 1 FROM appdb.case_records p WHERE p.id = r.id);
SELECT ROW_COUNT() AS inserted;
-- ★★★★ 不是 3000 就打 ROLLBACK; 不要打 COMMIT;
COMMIT;
```

預期輸出：

```text
+----------+
| inserted |
+----------+
|     3000 |
+----------+
```

### 【6】驗證與解除凍結（16:20）

```bash
mysql --login-path=admin -e "
SELECT COUNT(*) AS total FROM appdb.case_records;
SELECT COUNT(*) AS y2026 FROM appdb.case_records WHERE YEAR(created_at)=2026;"
```

預期輸出：

```text
+---------+
| total   |
+---------+
| 1284847 |     # ★★ 1284003（誤刪前）＋ 事故後其他人正常新增的 844 筆，兩者都在
+---------+
| y2026   |
|    3000 |
```

★★★★★ **這行輸出就是「情境一做對了」的證據**：誤刪的 3000 筆回來了，
**而且事故後其他同仁的 844 筆正常交易一筆都沒少**。
如果當初直接拿備份覆蓋，這裡會是 `1284003`，那 844 筆永遠消失。

```bash
mysql --login-path=admin -e "
GRANT INSERT, UPDATE, DELETE ON appdb.* TO 'appuser'@'10.10.20.%'; FLUSH PRIVILEGES;"
sudo -u www-data php /var/www/appdb/artisan up
# ★★★★ 清掉救援庫，它是一份完整的個資，不能留著
mysql --login-path=restore -e "DROP DATABASE appdb_recover;"
```

預期輸出：`INFO  Application is now live.`

### 【7】事故時間軸與改善項

| 時間 | 事件 | 備註 |
| --- | --- | --- |
| 14:37:09 | 誤執行 DELETE | binlog.000137 pos 4523183 |
| 15:02 | 使用者通報 | ★★★ **發現延遲 25 分鐘** —— 改善項 |
| 15:05 / 15:08 | 凍結寫入、保全 binlog／確認備份完整 | |
| 15:12–15:48 | 還原全備份到 appdb_recover | **36 分鐘（RTO 主要成本）** |
| 15:50–16:12 | binlog 重放 + 差集比對 + INSERT 回正式庫 | 3000 筆 |
| 16:20 | 驗證通過、服務恢復 | **RPO = 0 筆；RTO = 1 小時 18 分** ★★★★ |

| # | 問題 | 改善 | 期限 |
| --- | --- | --- | --- |
| 1 | 誤操作到發現隔了 25 分 | ★★★ 對 `case_records` 加「單次刪除 > 100 筆」告警 | 09-15 |
| 2 | 承辦有正式庫 DELETE 權限 | ★★★★ 收回直連權限改走應用，見 [[07-MySQL-安全強化]] | 09-30 |
| 3 | 還原花 36 分（50 GB 邏輯備份） | ★★ 評估 XtraBackup 縮短 RTO | 10-31 |
| 4 | 事發時才第一次跑 PITR | ★★★★★ 排入季度演練 | 每季 |

### 交付物一：`/usr/local/bin/mysql-backup.sh`

```bash
#!/usr/bin/env bash
# mysql-backup.sh — 全備份 + binlog 歸檔 + 加密 + 異地 + 輪替
# ★★★★ 設計原則：任何一步失敗都要【大聲失敗】並告警，絕不安靜地產生半截備份
set -euo pipefail

LOGIN_PATH="backup"; DBS=("appdb"); BASE="/var/backups/mysql"
GPG_RECIPIENT="backup@example.gov.tw"
REMOTE="backup@nas.internal.example.gov.tw:/srv/backup/mysql"
SSH_KEY="/root/.ssh/id_ed25519_backup"
ALERT_WEBHOOK="${MYSQL_BACKUP_WEBHOOK:-}"       # ★★★★ 沒設就會在 preflight 擋下來
ALERT_MAIL="isec@example.gov.tw"
KEEP_DAILY=7; KEEP_WEEKLY=4; KEEP_MONTHLY=12
LOCK="/var/lock/mysql-backup.lock"
TS="$(date +%Y%m%dT%H%M%S)"; LOG="${BASE}/logs/backup-${TS}.log"
TAG=""; SKIP_REMOTE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) TAG="-$2"; shift 2 ;;
    --skip-remote) SKIP_REMOTE=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

log() { printf '[%s] %s\n' "$(date +'%F %T')" "$*" | tee -a "$LOG"; }
die() { log "★★★★ FAILED: $*"; alert "MySQL 備份失敗" "$*"; exit 1; }

alert() {
  # ★★★★ 備份腳本失敗沒有告警 = 沒有備份。告警要送到【人真的會看到】的地方，
  #      不是只寫進沒人讀的 log 檔。兩條管道互為備援（webhook 服務本身也會掛）。
  local subject="$1" body="$2" host; host="$(hostname -f)"
  if [[ -n "$ALERT_WEBHOOK" ]]; then
    curl -fsS -m 15 -X POST -H 'Content-Type: application/json' \
      -d "$(printf '{"text":"[%s] %s\\n%s"}' "$host" "$subject" "$body")" \
      "$ALERT_WEBHOOK" || log "★★★ webhook 告警本身也失敗了"
  fi
  printf '%s\n\n主機: %s\n日誌: %s\n' "$body" "$host" "$LOG" \
    | mail -s "[$host] $subject" "$ALERT_MAIL" 2>/dev/null || log "★★★ mail 告警失敗"
}

# ★★★ 非正常結束都要告警——包含被 OOM 砍掉、磁碟寫滿這類不會走到 die() 的情況
trap 'rc=$?; [[ $rc -ne 0 ]] && alert "MySQL 備份異常結束" "exit=$rc 見 $LOG"' EXIT

preflight() {
  log "=== preflight ==="
  [[ $EUID -eq 0 ]] || die "必須以 root 執行"
  [[ -n "$ALERT_WEBHOOK" || -x "$(command -v mail)" ]] \
    || die "★★★★ 沒有任何可用的告警管道，拒絕執行（失敗會沒人知道）"
  command -v mysqldump >/dev/null || die "找不到 mysqldump"
  command -v gpg >/dev/null       || die "找不到 gpg"
  mysqladmin --login-path="$LOGIN_PATH" ping >/dev/null 2>&1 || die "連不上 MySQL"
  gpg --list-keys "$GPG_RECIPIENT" >/dev/null 2>&1 || die "找不到公鑰 $GPG_RECIPIENT"

  # ★★★ 版本自適應：8.0.26 以後是 --source-data，之前只有 --master-data
  if mysqldump --help 2>/dev/null | grep -q -- '--source-data'; then
    BINLOG_POS_OPT="--source-data=2"
  else
    BINLOG_POS_OPT="--master-data=2"
  fi
  log "binlog 座標旗標: $BINLOG_POS_OPT"

  # ★★★ 非 InnoDB 的表會讓 --single-transaction 失去一致性保證
  local nonidb
  nonidb=$(mysql --login-path="$LOGIN_PATH" -N -B -e "
    SELECT COUNT(*) FROM information_schema.TABLES
    WHERE ENGINE NOT IN ('InnoDB') AND ENGINE IS NOT NULL
      AND TABLE_SCHEMA NOT IN ('mysql','information_schema','performance_schema','sys');")
  [[ "$nonidb" -eq 0 ]] || log "★★★ 警告：有 $nonidb 張非 InnoDB 表，本次不保證其一致性"

  # ★★★ 空間：壓縮後通常剩 12～15%，抓 40% 留三倍餘裕
  local need avail
  need=$(mysql --login-path="$LOGIN_PATH" -N -B -e "
    SELECT CEIL(SUM(data_length+index_length)*0.4/1024/1024) FROM information_schema.TABLES
    WHERE TABLE_SCHEMA IN ('${DBS[0]}');")
  avail=$(df -Pm "$BASE" | awk 'NR==2{print $4}')
  [[ "$avail" -gt "$need" ]] || die "空間不足：需要約 ${need}MB，只剩 ${avail}MB"
  log "空間檢查 OK（需要約 ${need}MB / 可用 ${avail}MB）"
}

pick_bucket() {
  local dom dow; dom=$(date +%d); dow=$(date +%u)
  if   [[ "$dom" == "01" ]]; then BUCKET=monthly
  elif [[ "$dow" == "7"  ]]; then BUCKET=weekly
  else                            BUCKET=daily; fi
  install -d -m 700 "${BASE}/full/${BUCKET}"
  log "本次進 ${BUCKET} 艙"
}

do_dump() {
  log "=== dump ==="
  local db out t0 t1
  for db in "${DBS[@]}"; do
    out="${BASE}/full/${BUCKET}/${db}-${TS}${TAG}.sql.gz.gpg"
    t0=$(date +%s); set -o pipefail
    mysqldump --login-path="$LOGIN_PATH" \
      --single-transaction $BINLOG_POS_OPT --flush-logs \
      --routines --triggers --events --set-gtid-purged=COMMENTED \
      --hex-blob --default-character-set=utf8mb4 --no-tablespaces --quick \
      --databases "$db" 2>>"$LOG" \
      | gzip -6 \
      | gpg --batch --yes --trust-model always --recipient "$GPG_RECIPIENT" --encrypt \
      > "$out" || die "dump pipeline 失敗（PIPESTATUS=${PIPESTATUS[*]}）"
    chmod 600 "$out"; t1=$(date +%s)
    log "已產生 $out（$(( t1 - t0 )) 秒，$(du -h "$out" | cut -f1)）"
    DUMPS+=("$out")
  done
}

# ★★★★ 這一段不能省：沒有驗證的備份跟沒有備份是同一件事
verify() {
  log "=== verify ==="
  local f pos
  for f in "${DUMPS[@]}"; do
    gpg --quiet --batch --decrypt "$f" 2>/dev/null | gzip -t \
      || die "★★★★ $f gzip 完整性檢查失敗"
    gpg --quiet --batch --decrypt "$f" 2>/dev/null | zcat | tail -5 \
      | grep -q -- '-- Dump completed' \
      || die "★★★★ $f 檔尾沒有 'Dump completed'，mysqldump 中途死了"
    pos=$(gpg --quiet --batch --decrypt "$f" 2>/dev/null | zcat \
          | grep -m1 -E 'CHANGE (REPLICATION SOURCE|MASTER) TO' || true)
    [[ -n "$pos" ]] || die "★★★★ $f 沒有 binlog 座標，這份備份無法做 PITR"
    log "驗證通過：$(basename "$f")　座標：$pos"
  done
}

dump_grants() {
  log "=== grants ==="
  local g="${BASE}/full/${BUCKET}/grants-${TS}${TAG}.sql"
  mysql --login-path="$LOGIN_PATH" -N -B -e "
    SELECT CONCAT('SHOW GRANTS FOR ', QUOTE(user), '@', QUOTE(host), ';')
    FROM mysql.user WHERE user NOT LIKE 'mysql.%';" \
  | mysql --login-path="$LOGIN_PATH" -N -B | sed 's/$/;/' > "$g" || die "匯出 GRANT 失敗"
  chmod 600 "$g"; log "已匯出 $(wc -l < "$g") 條 GRANT → $g"
}

archive_binlog() {
  log "=== binlog ==="
  local src cur
  src="$(dirname "$(mysql --login-path="$LOGIN_PATH" -N -B -e 'SELECT @@log_bin_basename;')")"
  cur=$(mysql --login-path="$LOGIN_PATH" -N -B -e "SHOW BINARY LOGS;" | tail -1 | awk '{print $1}')
  # ★★★ 只複製「已封檔」的 binlog；正在寫的那個複製過去是半截的
  find "$src" -maxdepth 1 -type f -name 'binlog.[0-9]*' ! -name "$cur" -print0 \
    | xargs -0 -r cp -an -t "${BASE}/binlog/" || die "binlog 歸檔失敗"
  log "binlog 歸檔完成（跳過使用中的 $cur）"
}

push_remote() {
  [[ $SKIP_REMOTE -eq 1 ]] && { log "略過異地傳送"; return 0; }
  log "=== remote ==="
  rsync -a --partial --timeout=120 \
    -e "ssh -i $SSH_KEY -o BatchMode=yes -o StrictHostKeyChecking=yes" \
    "${BASE}/full/" "${BASE}/binlog/" "${REMOTE}/" >>"$LOG" 2>&1 \
    || die "異地傳送失敗（NAS 是否可達？金鑰是否正確？）"
  log "異地傳送完成 → $REMOTE"
}

rotate() {
  log "=== rotate ==="
  local b dir keep
  for b in daily:$KEEP_DAILY weekly:$KEEP_WEEKLY monthly:$KEEP_MONTHLY; do
    dir="${BASE}/full/${b%%:*}"; keep="${b##*:}"; [[ -d "$dir" ]] || continue
    # ★★★ 分艙後這裡的邏輯簡單到不會寫錯，比用 find -mtime 湊條件安全得多
    ls -1t "$dir"/*.sql.gz.gpg 2>/dev/null | tail -n "+$((keep+1))" \
      | while read -r old; do log "刪除過期：$old"; rm -f "$old"; done
  done
  # ★★★★ binlog 至少留 14 天，且必須 >「全備間隔 + 發現問題的時間」
  find "${BASE}/binlog" -type f -name 'binlog.[0-9]*' -mtime +14 -print -delete \
    | sed 's/^/刪除過期 binlog: /' | tee -a "$LOG"
}

main() {
  install -d -m 700 "${BASE}"/{full,binlog,drill,logs}
  DUMPS=(); log "########## MySQL 備份開始 ${TS} ##########"
  preflight; pick_bucket; do_dump; verify; dump_grants; archive_binlog; push_remote; rotate
  log "########## 完成 completed OK ##########"
  # ★★★ 成功心跳：只有失敗才通知的話，「腳本整個沒被執行」是完全靜默的。
  #     監控端設「超過 26 小時沒收到心跳就告警」。
  [[ -n "$ALERT_WEBHOOK" ]] && curl -fsS -m 10 -X POST -H 'Content-Type: application/json' \
    -d "$(printf '{"text":"[%s] MySQL 備份成功 %s"}' "$(hostname -f)" "$TS")" \
    "$ALERT_WEBHOOK" >/dev/null || true
}

# ★★★★ flock：避免上一次還沒跑完就又被 timer 叫起來，
#      兩個 mysqldump 同時跑會互搶 I/O，也可能把磁碟寫爆
exec 9>"$LOCK"
flock -n 9 || { echo "另一個備份仍在執行，本次跳過" >&2; exit 0; }
main "$@"
```

**回滾方式 ★★★**：這支腳本**只寫入備份目錄，不動任何正式資料**。「回滾」指兩件事 ——
① 誤刪了備份：從 `$REMOTE` 用 `rsync` 拉回來；
② 誤把 `--tag pre-recover` 的臨時備份混進輪替：那些檔名帶 tag，
可能被算進保留數量，手動 `rm` 掉帶 tag 的檔案即可。

### 交付物二：`/usr/local/bin/mysql-restore-drill.sh`

```bash
#!/usr/bin/env bash
# mysql-restore-drill.sh — 自動還原演練：還原 → 比對 → 計時 → 產出演練紀錄
# ★★★★★ 這支腳本的存在，就是「我們的備份可以還原」這句話的唯一證據
set -euo pipefail

BACKUP_FILE="${1:?用法: mysql-restore-drill.sh <備份檔.sql.gz.gpg> [期望表數]}"
EXPECT_TABLES="${2:-}"
DRILL_LOGIN="restore"                 # ★★★ 指向【演練主機/容器】，絕不能指向正式庫
DRILL_DB="drill_$(date +%Y%m%d_%H%M%S)"
SRC_LOGIN="backup"; SRC_DB="appdb"
REPORT_DIR="/var/backups/mysql/drill"
REPORT="${REPORT_DIR}/drill-$(date +%Y%m%d-%H%M%S).md"
KEY_TABLES=("case_records" "attachments" "users")

log() { printf '[%s] %s\n' "$(date +'%F %T')" "$*"; }
die() { log "★★★★ 演練失敗：$*"; finish_report "失敗" "$*"; exit 1; }

# ★★★★★ 安全閘：login-path 指錯目標是還原演練最危險的失誤——
#        你以為在演練，實際上正在把昨天的備份灌進正式庫。
guard() {
  local host; host=$(mysql --login-path="$DRILL_LOGIN" -N -B -e "SELECT @@hostname;")
  log "演練標靶主機：$host"
  [[ "$host" != "$(hostname -s)" ]] \
    || grep -q '^DRILL_HOST_OK=1$' /etc/mysql/drill.conf 2>/dev/null \
    || die "★★★★★ 標靶看起來是正式主機（$host）。要在本機演練請建立 /etc/mysql/drill.conf 寫入 DRILL_HOST_OK=1"
  [[ "$DRILL_DB" == drill_* ]] || die "演練資料庫名必須以 drill_ 開頭"
}

capture_expect() {
  log "=== 取得期望值 ==="
  EXP_TABLES="${EXPECT_TABLES:-$(mysql --login-path="$SRC_LOGIN" -N -B -e "
    SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='$SRC_DB';")}"
  EXP_ROUTINES=$(mysql --login-path="$SRC_LOGIN" -N -B -e "
    SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA='$SRC_DB';")
  EXP_EVENTS=$(mysql --login-path="$SRC_LOGIN" -N -B -e "
    SELECT COUNT(*) FROM information_schema.EVENTS WHERE EVENT_SCHEMA='$SRC_DB';")
  declare -gA EXP_ROWS EXP_CKSUM
  local t
  for t in "${KEY_TABLES[@]}"; do
    EXP_ROWS[$t]=$(mysql --login-path="$SRC_LOGIN" -N -B \
      -e "SELECT COUNT(*) FROM \`$SRC_DB\`.\`$t\`;" 2>/dev/null || echo "N/A")
    EXP_CKSUM[$t]=$(mysql --login-path="$SRC_LOGIN" -N -B \
      -e "CHECKSUM TABLE \`$SRC_DB\`.\`$t\`;" 2>/dev/null | awk '{print $2}' || echo "N/A")
  done
  log "期望：表 $EXP_TABLES／程序 $EXP_ROUTINES／事件 $EXP_EVENTS"
}

verify_file() {                       # L1 + L2
  log "=== L1/L2 檔案完整性 ==="
  [[ -r "$BACKUP_FILE" ]] || die "讀不到 $BACKUP_FILE"
  gpg --quiet --batch --decrypt "$BACKUP_FILE" 2>/dev/null | gzip -t \
    || die "gzip 完整性檢查失敗（檔案損毀或私鑰不對）"
  gpg --quiet --batch --decrypt "$BACKUP_FILE" 2>/dev/null | zcat | tail -5 \
    | grep -q -- '-- Dump completed' || die "檔尾缺少 'Dump completed'"
  BINLOG_POS=$(gpg --quiet --batch --decrypt "$BACKUP_FILE" 2>/dev/null | zcat \
    | grep -m1 -E 'CHANGE (REPLICATION SOURCE|MASTER) TO' || echo "（無）")
  log "L1/L2 通過；binlog 座標：$BINLOG_POS"
}

do_restore() {                        # L3：真的灌一次，並計時
  log "=== L3 還原到 $DRILL_DB ==="
  mysql --login-path="$DRILL_LOGIN" -e \
    "CREATE DATABASE \`$DRILL_DB\` CHARACTER SET utf8mb4;" || die "建立演練庫失敗"
  local t0 t1; t0=$(date +%s); set -o pipefail
  gpg --quiet --batch --decrypt "$BACKUP_FILE" 2>/dev/null | zcat \
    | grep -v '^CREATE DATABASE' \
    | sed "s/^USE \`$SRC_DB\`;/USE \`$DRILL_DB\`;/" \
    | mysql --login-path="$DRILL_LOGIN" "$DRILL_DB" \
    || die "還原失敗（PIPESTATUS=${PIPESTATUS[*]}）"
  t1=$(date +%s); RTO=$(( t1 - t0 ))
  log "★★★★ 實際 RTO：${RTO} 秒（$(printf '%02d:%02d:%02d' $((RTO/3600)) $((RTO%3600/60)) $((RTO%60))))"
}

compare() {                           # L4：內容真的對不對
  log "=== L4 比對 ==="
  RESULT_LINES=(); local got t ok=1
  chk() {  # 名稱 期望 實得 失敗註記
    if [[ "$3" == "$2" ]]; then RESULT_LINES+=("| $1 | $2 | $3 | ✔ |")
    else RESULT_LINES+=("| $1 | $2 | $3 | ✘ $4 |"); ok=0; fi
  }
  got=$(mysql --login-path="$DRILL_LOGIN" -N -B -e "
    SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='$DRILL_DB';")
  chk "表數" "$EXP_TABLES" "$got" ""
  got=$(mysql --login-path="$DRILL_LOGIN" -N -B -e "
    SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA='$DRILL_DB';")
  chk "預存程序" "$EXP_ROUTINES" "$got" "★★★★ 少了 --routines"
  got=$(mysql --login-path="$DRILL_LOGIN" -N -B -e "
    SELECT COUNT(*) FROM information_schema.EVENTS WHERE EVENT_SCHEMA='$DRILL_DB';")
  chk "排程事件" "$EXP_EVENTS" "$got" "★★★★ 少了 --events"

  for t in "${KEY_TABLES[@]}"; do
    got=$(mysql --login-path="$DRILL_LOGIN" -N -B \
      -e "SELECT COUNT(*) FROM \`$DRILL_DB\`.\`$t\`;" 2>/dev/null || echo "N/A")
    chk "$t 列數" "${EXP_ROWS[$t]}" "$got" "★★★★★"
    # ★★★ CHECKSUM TABLE 對 InnoDB 是【即時全表掃描】，大表很慢；
    #     而且不同 MySQL 版本／row_format 之間【不保證相同】——
    #     只有演練機與正式庫同版本時，這個比對才有意義。
    got=$(mysql --login-path="$DRILL_LOGIN" -N -B \
      -e "CHECKSUM TABLE \`$DRILL_DB\`.\`$t\`;" 2>/dev/null | awk '{print $2}' || echo "N/A")
    [[ "$got" == "${EXP_CKSUM[$t]}" ]] \
      && RESULT_LINES+=("| $t CHECKSUM | ${EXP_CKSUM[$t]} | $got | ✔ |") \
      || RESULT_LINES+=("| $t CHECKSUM | ${EXP_CKSUM[$t]} | $got | ⚠ 版本不同時可能正常 |")
  done
  OVERALL=$([[ $ok -eq 1 ]] && echo "通過" || echo "★★★★ 未通過")
}

finish_report() {                     # 產出交稽核用的演練紀錄
  local status="${1:-$OVERALL}" note="${2:-}"
  install -d -m 700 "$REPORT_DIR"
  {
    echo "# MySQL 還原演練紀錄"; echo
    echo "| 項目 | 內容 |"; echo "| --- | --- |"
    echo "| 演練日期 | $(date +'%F %T %Z') |"
    echo "| 演練人員 | ${DRILL_OPERATOR:-$(id -un)} |"
    echo "| 覆核人員 | （待簽，★★★★ 不得與演練人員同一人） |"
    echo "| 備份檔 | $(basename "$BACKUP_FILE")（$(du -h "$BACKUP_FILE" 2>/dev/null | cut -f1)） |"
    echo "| binlog 座標 | ${BINLOG_POS:-N/A} |"
    echo "| 演練標靶 | login-path=$DRILL_LOGIN / db=$DRILL_DB |"
    echo "| **實際 RTO** | **${RTO:-N/A} 秒** |"
    echo "| **整體結果** | **$status** |"; echo
    echo "## 比對明細"; echo
    echo "| 檢查項 | 期望 | 實得 | 結果 |"; echo "| --- | --- | --- | --- |"
    printf '%s\n' "${RESULT_LINES[@]:-| （未執行到比對） | | | |}"; echo
    echo "## 發現問題"; echo
    echo "- ${note:-（請填寫，寫「無」通常代表沒有認真做）}"; echo
    echo "## 改善措施與期限"; echo; echo "- "
  } > "$REPORT"
  log "演練紀錄：$REPORT"
}

# ★★★★ 演練庫是一份完整的個資，用完【一定】要刪
cleanup() {
  mysql --login-path="$DRILL_LOGIN" -e "DROP DATABASE IF EXISTS \`$DRILL_DB\`;" \
    && log "已清除演練庫 $DRILL_DB" \
    || log "★★★★ 清除演練庫失敗，請立刻手動 DROP DATABASE $DRILL_DB"
}
trap cleanup EXIT

guard; capture_expect; verify_file; do_restore; compare; finish_report
log "########## 演練完成：$OVERALL ##########"
[[ "$OVERALL" == "通過" ]] || exit 1
```

### 驗收檢查表

| # | 檢查項 | 指令 | 預期結果 | 星級 |
| --- | --- | --- | --- | --- |
| 1 | binlog 已開且為 ROW | `SELECT @@log_bin, @@binlog_format;` | `1  ROW` | ★★★★ |
| 2 | binlog 與資料不同碟 | `df -h /var/lib/mysql /var/log/mysql/binlog` | 兩個不同 Filesystem | ★★★★ |
| 3 | binlog 保留期夠 | `SELECT @@binlog_expire_logs_seconds;` | ≥ 1209600 | ★★★★ |
| 4 | 備份帳號權限齊全 | `SHOW GRANTS FOR CURRENT_USER()` | 含 `PROCESS`、`RELOAD`、`REPLICATION CLIENT` | ★★★ |
| 5 | 指令列沒有密碼 | 備份期間 `ps auxww \| grep -c '\-p[^ ]'` | `0` | ★★★★ |
| 6 | 備份檔權限 600 | `find /var/backups/mysql -type f ! -perm 600` | 無輸出 | ★★★★ |
| 7 | 備份已加密 | `file appdb-*.sql.gz.gpg` | `PGP ... encrypted data` | ★★★★ |
| 8 | 備份主機沒有私鑰 | `gpg --list-secret-keys` | 無 `backup@` 的 `sec` | ★★★★★ |
| 9 | 檔尾完整 | `... \| zcat \| tail -1` | `-- Dump completed on ...` | ★★★★ |
| 10 | 有 binlog 座標 | `... \| grep 'SOURCE_LOG_POS'` | 有一行 | ★★★★ |
| 11 | 異地副本存在 | `ssh nas 'ls -lt /srv/backup/mysql/full/daily \| head -3'` | 今天的檔案 | ★★★★ |
| 12 | timer 有排 | `systemctl list-timers mysql-backup.timer` | 有下次執行時間 | ★★★ |
| 13 | ★★★★ 失敗會告警 | 故意 `chmod 000` 備份目錄再跑一次 | 收到告警訊息 | ★★★★ |
| 14 | ★★★★★ 演練通過 | `mysql-restore-drill.sh <最新備份>` | `演練完成：通過` | ★★★★★ |
| 15 | 演練庫已清掉 | `SHOW DATABASES LIKE 'drill_%'` | `Empty set` | ★★★★ |

★★★★ 第 13 項是最多人略過、也最有價值的一項：
**「告警管道本身壞掉」與「備份壞掉」在後果上完全一樣，而前者更常發生。**

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **★★★★★ 還原後 mysqld 起不來，`InnoDB: Database page corruption` / `log sequence number is in the future`** | 熱狀態下 `cp` / `rsync` 資料目錄，dirty page 與 redo 對不上 | 這份備份救不回來。改用 mysqldump、XtraBackup（含 `--prepare`），或停機後複製 |
| **★★★★★ 還原到一半停住：`ERROR 1840 (HY000): @@GLOBAL.GTID_PURGED can only be set when @@GLOBAL.GTID_EXECUTED is empty`** | dump 用了 `--set-gtid-purged=AUTO/ON`，灌進已有 GTID 的主機 | 備份時改 `COMMENTED`；已產生的檔案可 `sed 's/^SET @@GLOBAL.GTID_PURGED/-- &/'` |
| **★★★★ 還原完應用報 `PROCEDURE appdb.sp_xxx does not exist`，或月報是空的** | 備份沒加 `--routines` / `--events` | 加旗標重備；用 `information_schema.ROUTINES` / `.EVENTS` 比對數量（演練腳本已含） |
| **★★★★ 要做 PITR 才發現 binlog 只剩兩天** | `binlog_expire_logs_seconds` 小於「全備間隔＋發現時間」 | 調到 ≥ 14 天並確認容量；同時歸檔到異地 |
| **★★★★ 資料碟壞掉，binlog 也一起沒了** | binlog 與 `/var/lib/mysql` 同一顆磁碟 | `log_bin` 指到另一顆碟，並用 `--raw --stop-never` 持續歸檔異地 |
| **★★★★ mysqldump 失敗：`Access denied; you need (at least one of) the PROCESS privilege`** | 8.0.21 起沒加 `--no-tablespaces` 就需要 `PROCESS` | 加 `--no-tablespaces`，或授予備份帳號 `PROCESS` |
| **★★★★ 備份腳本從三週前就在失敗，沒人發現** | 沒有失敗告警，日誌沒人讀 | 加告警（webhook + mail）＋**成功心跳**；監控接法見 [[03-系統監控與告警]] |
| **★★★ 備份檔比平常小很多，但 exit code 是 0** | pipeline 中 mysqldump 死掉，gzip / gpg 照樣 exit 0 | `set -o pipefail` ＋ 檢查 `PIPESTATUS` ＋ 驗 `-- Dump completed` |
| **★★★ 還原後中文變 `?` 或 `????`** | 沒有 `--default-character-set=utf8mb4`，或還原端 client 編碼不對 | 兩端都指定 `utf8mb4`；已損壞的資料無法還原，只能重備 |
| **★★★ 備份中途 `Lost connection to MySQL server during query`** | 大表超過逾時或 `max_allowed_packet` | 加 `--quick`、調高 `net_write_timeout`，或改用 mydumper / XtraBackup |
| **★★★ 加了 `--single-transaction` 資料還是不一致** | 備份期間跑了 `ALTER TABLE` / `TRUNCATE`（DDL 不受 consistent read 保護），或庫裡有 MyISAM | 備份時段與 migration 排開；MyISAM 轉 InnoDB |
| **★★★ 備份結束後一到兩小時應用明顯變慢** | 備份把 buffer pool 的熱頁擠掉了 | 排到真正的離峰；大庫改用 XtraBackup（不經過 buffer pool） |
| **★★★ `FLUSH TABLES WITH READ LOCK` 卡住，全站寫入停擺數分鐘** | 有長查詢還沒結束，FTWRL 要等它 | 先查 `PROCESSLIST` 確認無長交易再拿鎖；設 `lock_wait_timeout` |
| **★★★ XtraBackup 備份成功但 `--prepare` 或啟動失敗** | PXB 版本與 MySQL 大版本不對應 | 換成對應版本重備；升級 MySQL 時記得一起升 PXB |
| **★★ 兩個備份同時在跑，磁碟寫爆** | timer 週期短於備份耗時，沒有互斥 | 用 `flock -n`（本篇腳本已含） |
| **★★ rsync 到 NAS 的 binlog 是半截的** | 複製了正在寫入的那個 binlog | 只複製已封檔的（腳本用 `! -name "$cur"` 排除） |

### 排查步驟

**【1】備份到底有沒有跑、跑成功了嗎**

```bash
systemctl list-timers mysql-backup.timer --no-pager
sudo journalctl -u mysql-backup.service --since '3 days ago' --no-pager | tail -20
```

預期輸出（成功）：

```text
Aug 28 02:04:31 db01 systemd[1]: Starting MySQL full backup...
Aug 28 02:41:09 db01 mysql-backup.sh[31544]: [2026-08-28 02:41:09] ########## 完成 completed OK ##########
Aug 28 02:41:09 db01 systemd[1]: mysql-backup.service: Succeeded.
```

- `Succeeded` 且有 `completed OK` → 備份流程本身沒問題，往【3】驗內容。
- `Failed with result 'exit-code'` → 往【2】看失敗在哪一段。
- **完全沒有這個 unit 的紀錄** → timer 根本沒啟用（`systemctl enable --now`），
  或機器那段時間關機而 `Persistent=true` 沒設。

**【2】失敗在哪一段**

```bash
tail -40 "$(ls -1t /var/backups/mysql/logs/backup-*.log | head -1)"
```

預期輸出（範例）：

```text
[2026-08-28 02:04:33] === preflight ===
[2026-08-28 02:04:34] binlog 座標旗標: --source-data=2
[2026-08-28 02:04:35] ★★★★ FAILED: 空間不足：需要約 21400MB，只剩 8300MB
```

- 停在 `preflight` → 環境問題（空間、連線、金鑰），不是備份邏輯壞掉。
- `dump pipeline 失敗（PIPESTATUS=1 0 0）` → **第一個是 mysqldump**，
  看同一個 log 裡 mysqldump 自己吐的 stderr（權限？連線斷？大表逾時？）。
- `PIPESTATUS=0 0 2` → 第三個是 gpg，通常是**找不到公鑰**或 keyring 權限不對。
- 停在 `verify` → 備份跑完但內容不完整，最常見是磁碟寫滿或被 OOM 砍掉，
  查 `dmesg -T | grep -i 'killed process'`。

**【3】備份內容對不對（不要相信檔案大小）**

```bash
F=$(ls -1t /var/backups/mysql/full/daily/*.sql.gz.gpg | head -1)
gpg --quiet --decrypt "$F" | zcat | tail -1
gpg --quiet --decrypt "$F" | zcat | grep -c '^CREATE TABLE'
gpg --quiet --decrypt "$F" | zcat | grep -m1 'SOURCE_LOG_POS'
```

預期輸出：

```text
-- Dump completed on 2026-08-28  2:41:07
128
-- CHANGE REPLICATION SOURCE TO SOURCE_LOG_FILE='binlog.000137', SOURCE_LOG_POS=451062;
```

- 沒有 `Dump completed` → **這份備份不完整，不要留、也不要對外說「有備份」**。
- `CREATE TABLE` 數量與正式庫對不上 → 檢查是否有表被 `--ignore-table` 排除，
  或備份帳號對某些表沒有 `SELECT`。
- 沒有 `SOURCE_LOG_POS` → **這份備份無法做 PITR**，檢查 `--source-data` 旗標與 `RELOAD` 權限。

**【4】binlog 鏈是不是連得起來**

```bash
mysql --login-path=backup -e "SHOW BINARY LOGS;" | tail -3
ls -1 /var/backups/mysql/binlog/binlog.[0-9]* | sed 's/.*\.//' | sort -n | sed -n '1p;$p'
```

預期輸出：

```text
| binlog.000136 | 1073741 |
| binlog.000137 |  452399 |
000130
000137
```

★★★★ 判讀重點：**歸檔的編號區間必須「包住」最舊那份要保留的全備份所對應的座標，
而且中間不能跳號。** `000130`～`000137` 連續 → OK。
缺 `000134` → **那個時間點前後的 PITR 都做不了**，查歸檔服務那段時間是不是掛了。

**【5】PITR 前先確認事件真的在裡面**

```bash
sudo mysqlbinlog --no-defaults --base64-output=DECODE-ROWS -vv \
  --start-datetime="2026-08-26 14:30:00" --stop-datetime="2026-08-26 14:45:00" \
  /var/backups/mysql/binlog/binlog.000137 | grep -c '### DELETE FROM'
```

預期輸出：`3000`

- 數字對得上 → 這個 binlog 就是現場，可以往下定位 position。
- `0` → 時間窗口猜錯（機器時區？`SHOW VARIABLES LIKE 'time_zone'`；見
  [[28-時間同步NTP與chrony]]），或事件在別的 binlog 檔裡，往前一個檔找。
- 出現一堆 base64 而不是 `### DELETE` → **忘了加 `--base64-output=DECODE-ROWS -vv`**。

**【6】還原卡住或超級慢**

```bash
mysql --login-path=restore -e "SHOW PROCESSLIST;" | head -3
mysql --login-path=restore -e "
SELECT VARIABLE_NAME, VARIABLE_VALUE FROM performance_schema.global_variables
WHERE VARIABLE_NAME IN ('innodb_flush_log_at_trx_commit','sync_binlog');"
```

預期輸出：

```text
| 12 | restore | localhost | drill_2026 | Query | 88 | executing | INSERT INTO `case_records` ...
| innodb_flush_log_at_trx_commit | 1 |
| sync_binlog                    | 1 |
```

★★★ **演練機**（不是正式庫）可以把這兩個值暫時設 `0`，還原常常快兩三倍。
★★★★ **正式庫還原完務必改回 `1`** —— 忘了改回去等於「以後每次斷電都會掉資料」，
而且**不會有任何錯誤訊息提醒你**。

**【7】gpg 解不開**

```bash
gpg --list-secret-keys backup@example.gov.tw
gpg --quiet --decrypt "$F" > /dev/null
```

預期輸出（正常）：

```text
sec   ed25519 2026-01-15 [SC]
gpg: encrypted with cv25519 key, ID 8A3C1F92D4B7E605, created 2026-01-15
```

- `No secret key` → **私鑰不在這台**。這正是演練要提早發現的事：
  事故當天才發現「解密金鑰在離職同仁的筆電裡」就太遲了。
- `Inappropriate ioctl for device` → 需要 pinentry 但沒有 tty，
  腳本加 `--batch --pinentry-mode loopback --passphrase-file`（★★★ 密語檔權限 600）。

**【8】做任何還原前的最後一道：確認標靶不是正式庫**

```bash
mysql --login-path=restore -e "SELECT @@hostname, @@port, @@read_only;"
```

預期輸出：

```text
+------------+--------+-------------+
| @@hostname | @@port | @@read_only |
| db-drill01 |   3306 |           0 |
+------------+--------+-------------+
```

★★★★★ 看到的 `@@hostname` 是**正式庫的主機名** → **立刻停手**。
`login-path` 指錯目標是還原演練最危險的失誤：
你以為在演練，實際上正在把昨天的備份灌進正式庫。

---

## 安全性注意事項

> [!danger] ★★★★★ 絕對不可以做的事
> **① 把密碼寫在指令列** —— `mysqldump -u backup -pMyS3cret ...`
> 備份跑的那 40 分鐘內，機器上**任何**能執行 `ps` 的帳號都看得到完整密碼；
> 它同時會進 `~/.bash_history`、systemd 的 `ExecStart` 日誌、監控系統的 process 清單。
> **用 `--login-path` 或 600 權限的 `--defaults-file`。**
>
> **② 把未加密的 dump 檔留在磁碟上、或送到異地** ——
> 一份 `appdb.sql` 就是**整個機關的個資全集**（姓名、身分證字號、電話、案件內容）。
> 它經過的每一站都是一次外洩機會。**一律加密，而且備份主機上只放公鑰。**
>
> **③ 把解密金鑰跟備份放在同一台或同一顆碟** ——
> 勒索軟體加密整台 NAS 時，你的金鑰也一起被加密了。
> **離線副本 + 不可變（immutable / WORM）副本**，做法見 [[14-備份與抗勒索防護]]。
>
> **④ 備份目錄設成 755 或屬主不是 root** —— 等於**開放整台機器的所有帳號複製個資**。
> `find /var/backups/mysql -type f ! -perm 600` 必須無輸出。
>
> **⑤ 直接把正式庫備份灌進測試環境** ——
> 測試環境的帳號管理、網路隔離、日誌保存**都比正式環境鬆**，裝的卻是一模一樣的個資。
> **灌進去之前必須去識別化**（姓名代號化、身分證字號雜湊或遮罩、電話與地址置換、附件清空）。
> 手法見 [[08-資料防護DLP與加密]]。
>
> **⑥ 拿備份直接覆蓋正式庫來「救」誤刪的資料** ——
> 會把事故後其他人的正常交易一起抹掉，把一件事故變成兩件，
> **而第二件是你造成的，而且沒有備份可以救。** 走情境一的流程。
>
> **⑦ 用 `root` 帳號跑備份** —— 備份只需要讀取與少數全域權限，
> 用 `root` 等於讓一支排程腳本握有 `DROP DATABASE` 的能力。爆炸半徑差很多。

**機關情境要特別留意的四件事**：

| 面向 | 具體要求 | 星級 |
| --- | --- | --- |
| **個資保護** | 備份檔**靜態加密**、傳輸走加密通道（SSH / TLS）；備份也是個資檔案的一部分，適用個資法的安全維護義務。見 [[07-台灣資安法規與個資法]] | ★★★★ |
| **保留與銷毀** | 保留期限要**寫成規定**（日 7 / 週 4 / 月 12），到期**確實銷毀**並留銷毀紀錄；不能「硬碟還有空間就一直留」—— 留越久外洩面越大 | ★★★★ |
| **稽核軌跡** | 誰在何時**取用了備份檔**、誰執行了還原、演練紀錄與覆核簽章都要留存；備份主機的存取日誌接進 SIEM，見 [[09-日誌集中與SIEM]] | ★★★ |
| **最小權限** | 備份帳號只給表列的那幾項；還原用的 `restore` 帳號**只在演練期間開啟**，平時 `ACCOUNT LOCK` | ★★★ |

> [!warning] ★★★ 關於組態基準
> 資料庫的存取控制、連線加密、稽核日誌要對應機關採用的政府組態基準（TWGCB）。
> **各基準的實際條號與版本請以國家資通安全研究院／NCCST 公布的文件為準**，
> 本篇不引用任何條號以免誤導。實作見 [[07-MySQL-安全強化]] 與 [[08-系統強化與稽核]]。

---

## 速查表

### 備份指令

| 指令 | 用途 | 星級 |
| --- | --- | --- |
| `mysqldump --login-path=backup --single-transaction --source-data=2 --routines --triggers --events --databases appdb` | 標準全備份 | ★★★★ |
| `mysqldump ... --set-gtid-purged=COMMENTED` | 要灌進演練機或既有主機時**必加** | ★★★★ |
| `mysqldump ... --no-data --databases appdb` | 只備 schema（比對結構差異） | ★★ |
| `mysqldump ... --where="id > 1000" appdb t` | 只備部分列 | ★★ |
| `mysqldump --help \| grep -E -- '--(source\|master)-data'` | ★★★ 確認這台認得哪個旗標 | ★★★ |
| `xtrabackup --backup --target-dir=DIR` | 實體備份第一步 | ★★★ |
| `xtrabackup --prepare --target-dir=DIR` | ★★★★ 沒做這步的備份不能用 | ★★★★ |
| `xtrabackup --copy-back --target-dir=DIR` | 還原（資料目錄必須是空的） | ★★★ |
| `mysqlbinlog --read-from-remote-server --raw --stop-never` | binlog 準即時歸檔 | ★★★★ |

### 還原與 PITR 指令

| 指令 | 用途 | 星級 |
| --- | --- | --- |
| `gpg -d f.gpg \| zcat \| mysql --login-path=restore db` | 加密備份的還原 | ★★★ |
| `mysqlbinlog --base64-output=DECODE-ROWS -vv f` | ★★★★ 把 ROW 事件翻成人看得懂的 SQL | ★★★★ |
| `mysqlbinlog --start-datetime= --stop-datetime=` | 用時間框範圍（先粗找） | ★★★ |
| `mysqlbinlog --start-position= --stop-position=` | ★★★★ 用 position 精準框（實際重放用這個） | ★★★★ |
| `mysqlbinlog --skip-gtids` | 不汙染目標主機的 `gtid_executed` | ★★★★ |
| `mysqlbinlog --disable-log-bin` | 重放不寫進目標主機自己的 binlog | ★★★ |
| `mysqlbinlog --exclude-gtids='UUID:N'` | ★★★★ GTID 模式下**精準挖掉單一交易** | ★★★★ |

### 設定項

| 設定項 | 建議值 | 為什麼 | 星級 |
| --- | --- | --- | --- |
| `log_bin` | 指到**另一顆磁碟** | 同碟 = 沒有 PITR | ★★★★ |
| `binlog_format` | `ROW` | STATEMENT 重放結果會不一樣 | ★★★★ |
| `binlog_row_image` | `FULL` | 才撈得回被刪那一列的完整內容 | ★★★★ |
| `binlog_expire_logs_seconds` | `1209600`（14 天） | 必須 > 全備間隔＋發現時間；預設 2592000 | ★★★★ |
| `sync_binlog` | `1` | 斷電不掉 binlog（＝不掉 PITR 能力） | ★★★ |
| `gtid_mode` / `enforce_gtid_consistency` | `ON` / `ON` | `--exclude-gtids` 精準挖交易靠它 | ★★★ |
| `innodb_flush_log_at_trx_commit` | 正式 `1`；**演練機**可暫時 `0` | ★★★★ 演練調過的值不要帶回正式庫 | ★★★★ |

### 檔案與路徑

| 路徑 | 內容 | 權限 | 星級 |
| --- | --- | --- | --- |
| `/var/lib/mysql/` | 資料目錄（**不要熱複製**） | `700 mysql:mysql` | ★★★★★ |
| `/var/log/mysql/binlog/` | binlog（**另一顆碟**） | `750 mysql:mysql` | ★★★★ |
| `/var/backups/mysql/full/{daily,weekly,monthly}/` | 加密全備份 | `700 root:root` | ★★★★ |
| `/var/backups/mysql/binlog/` | binlog 歸檔 | `700 root:root` | ★★★★ |
| `/var/backups/mysql/drill/` | 演練紀錄 | `700 root:root` | ★★★ |
| `~/.mylogin.cnf` | login-path 憑證（**混淆非加密**） | `600 root:root` | ★★★★ |
| `xtrabackup_binlog_info` | XtraBackup 記下的 binlog 座標 | — | ★★★★ |

### 判斷準則

| 情況 | 該用哪個做法 | 星級 |
| --- | --- | --- |
| 資料 < 50 GB、要能只還原一張表 | mysqldump + binlog | ★★★ |
| 資料 > 100 GB、RTO 要 < 1 小時 | XtraBackup + binlog（mysqldump 當備胎） | ★★★★ |
| 誤刪一批資料，其他人還在正常使用 | ★★★★★ 情境一（還原到暫存庫，只撈回那批） | ★★★★★ |
| 整庫被搞壞（跑錯 migration） | 情境二（PITR 到誤操作前一秒） | ★★★★ |
| 機器毀了 | 情境三（同版本新機 + 還原 + GRANT 重建） | ★★★★ |
| 想「複製資料目錄就好」 | ★★★★★ 不行，除非停機或快照 + FTWRL | ★★★★★ |
| 想用 replica 當備份 | ★★★★ 不行，誤刪會同步過去 | ★★★★ |

---

## 練習題

> [!question]- 練習 1：找出這台主機「PITR 能力」的真實缺口
> **題目**：用五行以內的指令回答三個問題：① binlog 有沒有開、格式是什麼？
> ② binlog 跟資料在不在同一顆碟？③ 保留期多久、夠不夠？
>
> **參考解答**：
> ```bash
> mysql --login-path=backup -e "
> SELECT @@log_bin, @@binlog_format, @@binlog_row_image,
>        @@binlog_expire_logs_seconds/86400 AS keep_days, @@sync_binlog;"
> df -h /var/lib/mysql \
>   "$(dirname "$(mysql --login-path=backup -N -B -e 'SELECT @@log_bin_basename;')")" \
>   | awk '{print $1, $6}'
> ```
> 判讀：
> - `@@log_bin = 0` → **完全沒有 PITR 能力**，最高優先修。
> - `binlog_format` 不是 `ROW` → 重放結果可能與原本不同，PITR 不可信。
> - `binlog_row_image = MINIMAL` → ★★★ 可以 PITR，但**撈不回被刪那一列的完整欄位值**，
>   情境一會做不下去。
> - `df` 兩行是同一個 Filesystem → ★★★★ 資料碟壞掉時 binlog 陪葬，PITR 是紙上談兵。
> - `keep_days` 小於「全備間隔 + 你們平均多久發現異常」→ 全備與 binlog 之間有斷鏈。

> [!question]- 練習 2：做一次會失敗的演練
> **題目**：**故意**製造一份壞備份，確認你的驗證機制抓得到。
>
> **參考解答**：
> ```bash
> # ① 製造一份「中途死掉」的 dump
> mysqldump --login-path=backup --single-transaction --databases appdb \
>   | head -c 50000000 | gzip -6 \
>   | gpg --batch --yes --recipient backup@example.gov.tw --encrypt > /tmp/broken.sql.gz.gpg
> # ② L1 gzip 檢查——★★★ 這一關【可能會過】，因為串流前半段本身是合法的
> gpg -q -d /tmp/broken.sql.gz.gpg | gzip -t ; echo "gzip check exit=$?"
> # ③ L2 檔尾檢查——這一關一定會擋下來
> gpg -q -d /tmp/broken.sql.gz.gpg | zcat 2>/dev/null | tail -3 | grep -c 'Dump completed'
> ```
> 預期：③ 輸出 `0` → 驗證機制有效。
> **這題的重點是體會到「② 可能會過」**：只做 `gzip -t` 是不夠的，
> ★★★★ **`-- Dump completed` 這一行才是 mysqldump 有沒有正常跑完的憑據。**
> 最後跑一次 `mysql-restore-drill.sh /tmp/broken.sql.gz.gpg`，
> 確認它會失敗、會產出「失敗」的演練紀錄、而且**會把演練庫清掉**。

> [!question]- 練習 3：把「季度演練」變成一件跑得動的事
> **題目**：設計一個能在你們機關真的執行下去的季度還原演練機制，寫出排程方式、
> 標靶環境、通知對象、紀錄歸檔位置，以及**誰來覆核**。
>
> **參考解答**（一個可行的版本）：
> ```ini
> # /etc/systemd/system/mysql-restore-drill.timer
> [Timer]
> OnCalendar=Mon *-01,04,07,10-01..07 03:00:00   # ★ 每季第一個月的第一個週一
> Persistent=true
> ```
> - **標靶**：`docker run mysql:8.0.43`（★★★★ tag 與正式庫**完全一致**），跑完即銷毀。
> - **通知**：把 `drill-*.md` 摘要推到資訊室群組 + 寄給科長。
>   ★★★ **失敗要通知、成功也要通知** —— 成功通知的作用是「證明這件事真的有在跑」。
> - **紀錄歸檔**：`/var/backups/mysql/drill/` + 每季匯出進公文系統，
>   與 [[07-維護檢查表範本]] 的季度維護表併存。
> - **覆核**：★★★★ **執行人與覆核人不能是同一人**。覆核人要實際看三個數字：
>   實際 RTO、關鍵表列數是否相符、「發現問題」欄有沒有內容。
> - **輪值**：★★★★ 每次換一個人主刀，前一次的人當覆核。
>   這是唯一能確保「不是只有一個人會還原」的做法 ——
>   否則機關的實際 RTO 等於那個人的請假天數。

---

## 小測驗

Q1. 為什麼在 MySQL 執行中對 `/var/lib/mysql` 做 `rsync -a` 得到的東西不能拿來還原？請講出至少兩個具體機制。

Q2. 這行指令有什麼問題？`mysqldump -u backup -pS3cret --single-transaction appdb > /backup/appdb.sql`（至少三點）

Q3. 承辦誤刪 3000 筆案件，你手上有昨天的全備份。為什麼**不能**直接 `mysql appdb < backup.sql`？

Q4. `--single-transaction` 已經加了，為什麼備份期間還是可能拿到不一致的資料？

Q5. `binlog_expire_logs_seconds` 該怎麼決定？設太小的**具體**後果是什麼？

Q6. 要在 binlog 裡看到「被刪掉那一列的欄位值」，需要哪兩個條件同時成立？

Q7. PITR 時，`--stop-position` 應該設在誤操作交易的哪個位置？設錯會怎樣？

Q8. 演練腳本比對通過了「表數 128 / 128」，為什麼這還不足以說「備份可以還原」？

Q9. 整機重建時，為什麼不建議把來源機的 `mysql` 系統庫直接灌到新機？替代做法是什麼？

Q10. 你的備份腳本已經連續三週失敗，但沒有人知道。設計上少了哪兩樣東西？

> [!question]- 測驗答案
> **Q1.** 兩個機制，缺一都會讓備份無法還原：
> ① **★★★★★ dirty page 還在記憶體裡**。InnoDB 改資料是先改 buffer pool 裡的頁，
> 之後才由背景執行緒刷回磁碟 —— 你 `rsync` 到的 `.ibd` 檔是**舊的**。
> ② **redo / undo 與資料檔對不上時間點**。掃過 `case_records.ibd` 是 10:00:00 的狀態，
> 掃到 `#innodb_redo` 已經 10:00:03，掃到 undo 是 10:00:07，三者 LSN 互相矛盾。
> 啟動時崩潰復原會發現 `log sequence number is in the future` 或
> `Database page corruption`，直接 abort。
> **★★★★★ 最危險的是 `rsync` 會 exit 0**，你要到還原那天才知道備份是垃圾。
> 有效做法只有三種：停機後複製、快照 + FTWRL、XtraBackup（含 `--prepare`）。
> 見「為什麼不能 `cp` / `rsync` `/var/lib/mysql`」。
>
> **Q2.** 至少四個問題：
> ① **★★★★ 密碼在指令列**。備份期間任何帳號 `ps auxww | grep mysqldump` 就看得到，
> 還會進 `~/.bash_history`。改用 `--login-path=backup`。
> ② **★★★★ 沒有 `--source-data=2`** → dump 檔裡沒有 binlog 座標，
> **這份備份無法做 PITR**，你只能還原到備份那一刻，中間的交易全丟。
> ③ **★★★★ 沒有 `--routines --triggers --events`** →
> 預存程序、觸發器、排程事件全部不見。事件不見最陰險：應用不會報錯，
> 只是月底報表變成空的，可能好幾週沒人發現。
> ④ 還有 `--no-tablespaces`（8.0.21 起沒加要 `PROCESS` 權限）、
> `--default-character-set=utf8mb4`（中文變 `?`）、`--databases`（沒加就沒有
> `CREATE DATABASE`）、以及 **★★★★ 輸出未加密就是一份完整個資落地**。
>
> **Q3.** 因為 **★★★★ 那會把事故發生後其他人的正常交易一起抹掉**。
> 誤刪在 14:37，你 15:10 才動手 —— 這 33 分鐘裡另外 20 位同仁
> 正常建立、修改了 844 筆資料，直接覆蓋等於把它們全部刪掉，
> **而且它們沒有備份可以救**（昨天的備份裡當然沒有今天的資料）。
> **正確做法**：還原到**暫存庫** `appdb_recover` → 重放 binlog 到誤操作前 →
> 用 `LEFT JOIN ... WHERE p.id IS NULL` 算出差集、確認就是 3000 筆 →
> 用交易包起來只 `INSERT` 那 3000 筆回正式庫 → 驗證總數是 1284003 + 844。
> 見「情境一」與「完整實戰範例」。
>
> **Q4.** 兩個官方明列的限制：
> ① **★★★ 只對 InnoDB 有效**（官方原文「only InnoDB tables are dumped in a consistent
> state」）—— 庫裡若還有 MyISAM 或 MEMORY 表，**它們在備份期間仍會變動**。
> 先用 `information_schema.TABLES WHERE ENGINE NOT IN ('InnoDB')` 確認，預期 `Empty set`。
> ② **★★★ 備份期間的 DDL 會破壞一致性**。consistent read **不隔離**
> `ALTER TABLE` / `CREATE TABLE` / `DROP TABLE` / `RENAME TABLE` / `TRUNCATE TABLE`，
> 用在正在被 dump 的表上，會讓 `SELECT` 讀到錯誤內容或直接失敗。
> **實務含意：備份時段要跟 `php artisan migrate` 排開。**
>
> **Q5.** 公式是 **★★★★ 保留期 > 全備份間隔 ＋ 你發現問題所需的時間**。
> 每日全備 + 承辦最慢一週後才發現 → 至少 8 天，實務上設 14 天留安全邊際
> （MySQL 8.0 / 8.4 預設是 30 天）。
> **設太小的具體後果**：設成 2 天，全備份是 8/20 凌晨，你 8/26 才發現 8/21 有問題 ——
> 8/21 的 binlog 早被自動清掉，**全備份與問題時間點之間是一段永遠接不起來的空白**，
> 你只能還原到 8/20 凌晨，把 8/20 到 8/26 的所有資料丟掉。
> ★★★ 要一起做的是**歸檔到異地**：本機留 14 天、異地留更久，
> 否則磁碟壞掉時 binlog 一起沒了。
>
> **Q6.** 兩個條件同時成立：
> ① **`binlog_format = ROW`** —— STATEMENT 只記「那句 SQL 文字」，
> 沒有任何被影響的列的內容，撈不回來。
> ② **`binlog_row_image = FULL`** —— ★★★ 這個最容易被忽略。設 `MINIMAL` 時，
> `DELETE` 事件只記錄「足以定位那一列的最少欄位」（通常只有主鍵），
> 你會知道刪了哪些 id，**但不知道那些列原本的內容**，情境一直接做不下去。
> 驗證：`mysqlbinlog --base64-output=DECODE-ROWS -vv` 後應看得到
> `### @1=100231 / ### @2='114-A-0231' / ### @3=...` 一整排欄位值；
> 只看得到 `@1` 一個欄位就是 `MINIMAL`。
>
> **Q7.** 應設在 **★★★★★ 那個交易的「起點」**，也就是該交易的 GTID / `BEGIN` 事件
> 之前的那個 `# at` 值（範例中是 `4523104`）。
> **設錯的兩種後果**：① 設成 `COMMIT` 之後（範例中的 `4524022`）→
> **誤刪那個交易也被重放了一遍**，你辛苦還原完發現資料還是被刪掉，整件事白做；
> ② 設得太早 → 誤操作**之前**的一些正常交易也沒被重放，造成額外的資料遺失。
> 所以定位時一定要用 `grep -E '^# at |Xid|GTID|BEGIN|COMMIT'` **把交易邊界看清楚**。
> ★★★ GTID 模式下有更精準的替代方案：`--exclude-gtids='UUID:99213'`
> 直接挖掉那一個交易，前後的正常交易全部保留 —— 這是 position 做不到的。
>
> **Q8.** 因為表數只驗到 **schema 的骨架**，沒有驗到內容。
> **可能通過表數檢查卻完全不能用的情況**：
> ① 每張表都建起來了，但 `INSERT` 中途失敗，**資料只有一半**；
> ② 表數對，但 **預存程序 0 個、排程事件 0 個**（漏了 `--routines --events`）；
> ③ 表數與列數都對，但**中文全變成 `?`**（編碼問題）；
> ④ 全部都對，但**還原花了 6 小時**，而服務水準承諾是 2 小時 —— 技術成功、業務失敗。
> 所以要做到 **★★★★★ L4：列數比對 + `CHECKSUM TABLE` + 計時實際 RTO**。
> ★★★ 注意 `CHECKSUM TABLE` 對 InnoDB 是即時全表掃描（大表很慢），
> 而且**不同 MySQL 版本／row_format 之間不保證相同** ——
> 演練機的版本 tag 必須跟正式庫**完全一致**，否則這個比對會誤報。
>
> **Q9.** 三個理由：① MySQL 8.0 的 **data dictionary 是 InnoDB 表**，
> 跨小版本硬灌容易出怪狀況；② 你會**把來源機所有帳號原封不動搬過去，
> 包含已離職人員的帳號** —— 災難重建本來是清理帳號的最佳時機，直接灌等於錯過；
> ③ 新機的內建帳號（`root@localhost`、`mysql.session`、`mysql.sys`）會被蓋掉，
> ★★★ 嚴重時新機**直接無法登入**，你在災難現場又多一個災難。
> **替代做法**：每天跟全備份一起匯出 `SHOW GRANTS` 的結果 ——
> 用 `mysql.user` 產生 `SHOW GRANTS FOR ...;` 語句再餵回 `mysql` 執行，
> 得到一份**人看得懂、可以先審再用**的純文字 GRANT 清單。
> ★★ 它**不含密碼**（`SHOW GRANTS` 不輸出密碼雜湊），
> 應用帳號密碼要另外從機密管理系統取得。
> MariaDB 使用者有捷徑：`mariadb-dump --system=users`。
>
> **Q10.** 少了兩樣：
> ① **★★★★ 失敗告警**。腳本失敗只寫進 `/var/backups/mysql/logs/`，
> 而沒有人每天讀那個目錄。**備份腳本失敗沒有告警 = 沒有備份**，
> 而且通常要到「需要還原的那一天」才會發現。告警要送到人**真的會看到**的地方：
> 即時通訊群組 webhook + email，兩條管道互為備援（webhook 服務本身也會掛）。
> ② **★★★ 成功心跳（dead man's switch）**。只有失敗才通知的話，
> 「腳本整個沒被執行」（timer 沒啟用、機器關機、cron 被誰註解掉）
> 是**完全靜默**的 —— 沒有失敗，所以沒有告警。成功時也送一則訊息，
> 監控端設「超過 26 小時沒收到就告警」。
> ★★★★ 補充第三樣：**驗收檢查表第 13 項** —— 故意讓備份失敗一次
> （例如 `chmod 000` 備份目錄），確認告警真的收得到。
> **「告警管道壞掉」和「備份壞掉」後果一樣，而前者更常發生。**

---

## 延伸閱讀

- [[03-備份策略與還原演練]] —— 3-2-1 原則、RPO / RTO 的一般性定義、restic / borg 的操作、勒索軟體不可變備份的通論都在那篇，本篇刻意不重講
- [[04-備份災難復原與入侵應變]] —— 事故的通報流程、證據保全、對外說明；本篇的「保全 binlog」只是其中一步
- [[02-MySQL-使用者與權限]] —— 備份帳號 `backup` 與還原帳號 `restore` 的建立與 `ACCOUNT LOCK`
- [[06-MySQL-主從複寫]] —— 「複寫不是備份」的完整論證與 replica 建置；本篇的 binlog 設定是它的前置
- [[04-MySQL-設定檔與調校]] —— `my.cnf` 載入順序、buffer pool 與 `innodb_flush_log_at_trx_commit` 的取捨
- [[07-MySQL-安全強化]] —— 連線加密、最小權限、稽核日誌，與本篇的備份加密互補
- [[14-備份與抗勒索防護]] —— 不可變（immutable / WORM）副本與離線副本的實作
- [[02-systemd-timer與cron選型]] —— 為什麼備份排程建議用 timer 而不是 cron
- [[07-台灣資安法規與個資法]] —— 備份檔的保存、加密、銷毀在法規上的義務
- MySQL 官方手冊 mysqldump：<https://dev.mysql.com/doc/refman/8.0/en/mysqldump.html>
- MySQL 官方手冊 二進位日誌與 PITR：<https://dev.mysql.com/doc/refman/8.0/en/point-in-time-recovery-binlog.html>
- Percona XtraBackup 官方文件：<https://docs.percona.com/percona-xtrabackup/8.0/>
