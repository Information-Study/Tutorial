---
title: "SQL 基礎操作"
desc: "維運視角的 SQL：安全改資料、交易與鎖、JOIN 陷阱、EXPLAIN 判讀與索引失效排查"
aliases: [sql, select, join, explain, safe-updates, only_full_group_by, mysql-client]
tags: [群組/軟體與開發工具, 服務/mysql, 主題/sql, 主題/效能]
category: 資料庫與資料儲存
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[060-04-01-01-svc-MySQL-安裝與初始化]]", "[[060-04-01-02-cmd-MySQL-使用者與權限]]"]
updated: 2026-08-28
---

# SQL 基礎操作

> [!abstract] 這篇你會學到
> - 把 `mysql` client 調成**正式機不會下錯指令**的樣子（`prompt` 加 `[PROD]` 標記、`\G`、`pager`、`--safe-updates`）
> - 用一組真實的 `users` / `orders` 資料，把 **SELECT / WHERE / ORDER BY / LIMIT 與 NULL 的三值邏輯陷阱**一次弄懂
> - ★★★★ **安全地手改一筆資料**：先寫成 SELECT 驗列數 → `BEGIN` → 看 `Rows matched/Changed` → `COMMIT` 或 `ROLLBACK`
> - 看懂 **JOIN 四種形式的輸出差異**，以及 `LEFT JOIN` 被 `WHERE` 退化成 `INNER JOIN` 的經典錯誤
> - ★★★★ 判讀 **`EXPLAIN` 的 `type` / `key` / `rows` / `Extra`**，並認出**讓索引失效的三種寫法**
> - 找出**誰卡住誰**（`sys.innodb_lock_waits`）、正確地 `KILL`，以及正式環境 `ALTER TABLE` 的風險評估

## 前置知識

- [[060-04-01-01-svc-MySQL-安裝與初始化]] — 服務起得來、`mysql` client 連得上，本篇才有得下手
- [[060-04-01-02-cmd-MySQL-使用者與權限]] — 本篇一律用**唯讀帳號**先查，要改資料才換帳號
- [[010-01-14-guide-計概-資料庫是什麼]] — 表、列、欄、主鍵這些名詞的白話說明
- [[100-02-10-guide-維運-故障排除方法論]] — 「先確認問題範圍再動手」的通用流程，本篇是它在資料庫上的實作

> [!warning] 關於本篇的輸出範例
> 所有 `EXPLAIN` 的 `rows`、`filtered` 與 `EXPLAIN ANALYZE` 的耗時數字，
> 都來自一組**示範資料**（`appdb` 小表 + 312 萬列的正式複本）。
> 你在自己環境跑出來的數字一定不同 —— **要看的是欄位的「性質」（`type` 是不是 `ALL`、
> `Extra` 有沒有 `Using filesort`），不是背數字。**

---

## 觀念說明

### 開發者的 SQL 與維運人員的 SQL 不是同一件事

```text
開發者寫 SQL 的目標               維運人員下 SQL 的目標
──────────────────────           ──────────────────────
把功能做出來                      使用者說「系統很慢」→ 找出是哪一句 SQL 慢
資料模型設計得漂亮                使用者說「資料不見了」→ 查得出來還在不在
ORM 幫我產生查詢                  開發交來一句 SQL 說「這個沒辦法改」→ 看懂問題在哪
本機資料 100 筆                   ★★★★ 正式機 312 萬筆，按下 Enter 就回不去
```

**這篇的核心問題只有一個：在正式環境的終端機前面，你敢不敢按下 Enter。**

敢按的前提是三件事：

```text
1. 我知道這一句會影響幾列        → 先寫成 SELECT COUNT(*) 驗證
2. 我知道按錯了怎麼退回          → BEGIN … ROLLBACK / 備份 + binlog
3. 我知道這一句會不會拖垮服務    → EXPLAIN 看 type 與 rows
```

三件事任何一件答不出來，**就不要按**。

### 一句 SELECT 在 MySQL 內部走過哪些關卡

```text
  client（你的終端機）
     │  ① 送出 SQL 文字
     ▼
  ┌──────────────────────────────────────────────┐
  │ Server 層                                    │
  │  ② Parser    語法檢查    → 錯了給 ERROR 1064 │
  │  ③ 權限檢查              → 錯了給 ERROR 1142 │
  │  ④ Optimizer 選執行計畫  → ★★★★ EXPLAIN 看的就是這一步 │
  │       ├ 有沒有可用的索引？                   │
  │       ├ 估計要掃幾列？（靠統計值）           │
  │       └ 要不要排序 / 建暫存表？              │
  └──────────────────────┬───────────────────────┘
                         │ ⑤ 呼叫儲存引擎讀列
                         ▼
  ┌──────────────────────────────────────────────┐
  │ InnoDB 儲存引擎                              │
  │  ⑥ Buffer Pool 有沒有？沒有就去讀磁碟        │
  │  ⑦ 加鎖（UPDATE/DELETE/SELECT … FOR UPDATE） │
  │  ⑧ 寫 undo log / redo log（可以 ROLLBACK 的原因）│
  └──────────────────────────────────────────────┘
```

維運人員要動的只有 ④ 與 ⑦ 這兩格：

| 使用者說的話 | 實際在問哪一格 | 本篇對應段落 |
| --- | --- | --- |
| ★★★★「查詢頁面變好慢」 | ④ 優化器沒走到索引 | `EXPLAIN` 判讀、索引失效三種寫法 |
| ★★★★「整個系統都轉圈圈」 | ⑦ 有人開了交易忘了 COMMIT | 交易與鎖、`sys.innodb_lock_waits` |
| ★★★「這筆資料要幫我改一下」 | ⑦ + ⑧ | 改資料的安全流程 |
| ★★★「升級後一堆頁面壞掉」 | ② + ④ `sql_mode` | `ONLY_FULL_GROUP_BY` |
| ★★ 「要一份報表」 | ④ | 資料匯出給機關報表 |

### 資料庫理論最少必要的一段

正規化、ACID 的完整定義不在本篇範圍（見 [[010-01-14-guide-計概-資料庫是什麼]]），
維運上只要記住這張對照：

| 名詞 | 一句話 | 壞掉會怎樣 |
| --- | --- | --- |
| **交易（transaction）** | 一串操作，要嘛全成功要嘛全退回 | ★★★★ 忘了 `COMMIT` → 鎖沒放 → 全站卡住 |
| **原子性（A）** | `ROLLBACK` 能整批退回 | 這是你敢按 Enter 的保險 |
| **隔離（I）** | 別人看不到你未 `COMMIT` 的資料 | ★★★ 但**鎖看得到** —— 別人會卡住 |
| **持久性（D）** | `COMMIT` 之後斷電也還在 | `COMMIT` 之後就**不能再 `ROLLBACK`** |
| **索引** | 資料的目錄 | ★★★★ 沒走到 → 全表掃 → 12 秒 |

> [!note] 唯一要背的一句
> **`COMMIT` 之前你有後悔的權利，`COMMIT` 之後只剩備份可以救。**
> 備份與時間點還原見 [[060-04-01-05-svc-MySQL-備份與還原]]。

---

## 基礎操作

### 連線：三個不要

```bash
mysql -h 127.0.0.1 -u ops_ro -p appdb
```

預期輸出：

```text
Enter password:                                     # ★★★ 密碼在這裡輸入，不寫在指令列
Welcome to the MySQL monitor.  Commands end with ; or \g.
Your MySQL connection id is 4127
Server version: 8.0.42-0ubuntu0.24.04.1 (Ubuntu)
mysql>
```

| ★ | 不要這樣做 | 為什麼 |
| --- | --- | --- |
| ★★★★★ | `mysql -u root -pP@ssw0rd` | **密碼會留在 `~/.bash_history` 與 `ps aux`**，同機任何使用者 `ps` 都看得到 |
| ★★★★ | 日常用 `root` 連 | 查資料用唯讀帳號就夠，見 [[060-04-01-02-cmd-MySQL-使用者與權限]] |
| ★★★ | `-h localhost` 混用 `-h 127.0.0.1` | `localhost` 走 unix socket、`127.0.0.1` 走 TCP，**權限授權的主機字串不同**，會出現「明明有授權卻連不上」 |

驗證密碼真的沒外洩：

```bash
ps -eo args | grep -c '[m]ysql .*-p[^ ]'
```

預期輸出：

```text
0                                                   # ★★★ 一定要是 0
```

### `~/.my.cnf`：★★★ 把提示字元改成「不會下錯機器」的樣子

正式機最常見的事故不是指令寫錯，是**在正式機的視窗下了測試機的指令**。
`mysql` client 的 `prompt` 可以把主機名寫進提示字元：

```ini
# ═══════════ ~/.my.cnf（權限一定要 600）═══════════
[client]
user     = ops_ro
host     = 127.0.0.1
port     = 3306

[mysql]
# ★★★★ 提示字元帶出「使用者@主機 [資料庫]」，正式機再加醒目標記
prompt   = "\\u@\\h [PROD] [\\d]> "

# ★★★ 寬表自動用直式輸出比較好讀時，手動下 \\G；這裡先把分頁器設好
pager    = less -SFX

# ★★ 每次連線都保護：沒有 WHERE 的 UPDATE/DELETE 直接擋下（下一節詳述）
safe-updates

# ★★ 連線斷掉自動重連（長時間開著的維運視窗很有用）
reconnect

# ★ 顯示每句的執行時間
show-warnings
```

```bash
chmod 600 ~/.my.cnf
```

連線後的提示字元：

```text
ops_ro@db-prod-01 [PROD] [appdb]>
```

> [!danger] ★★★★ 這一行是最便宜的保險
> 有人在測試機視窗下 `DELETE FROM orders;`，沒事；
> 同一句貼到**沒有標記的正式機視窗**，就是資安事件。
> **提示字元帶主機名的成本是 30 秒，事故的成本是幾天。**

`prompt` 常用的跳脫序列（寫在 `~/.my.cnf` 裡要寫成 `\\u`，在 client 內互動下 `prompt` 指令則寫 `\u`）：

| 序列 | 意義 | ★ |
| --- | --- | --- |
| `\u` | 使用者名稱 | ★★ |
| `\h` | 連線的主機 | ★★★★ |
| `\d` | 目前的資料庫 | ★★★ |
| `\p` | 連接埠 | ★★ |
| `\R \m` | 24 小時制的時 / 分 | ★★ 對照慢查詢日誌時間很有用 |
| `\c` | 這個連線裡的第幾句 | ★ |

臨時改（不動設定檔）：

```text
mysql> prompt \u@\h [\R:\m] [\d]>
PROMPT set to '\u@\h [\R:\m] [\d]> '
ops_ro@db-prod-01 [14:07] [appdb]>
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> sudo dnf install -y mysql          # ★ 只裝 client，不裝 server 用這個
> sudo dnf install -y mysql-server   # server
> sudo systemctl enable --now mysqld
> ```
> ★★★ 差異點：
> - 設定檔主檔是 `/etc/my.cnf`，附加設定放 `/etc/my.cnf.d/*.cnf`；
>   **不是** Ubuntu 的 `/etc/mysql/mysql.conf.d/`。
> - 資料目錄一樣是 `/var/lib/mysql`，但 **SELinux 會擋非標準路徑** ——
>   改 `datadir` 或 `secure_file_priv` 要一併 `semanage fcontext` 標記。
> - ★★★★ **RHEL 8/9 的 `dnf install mysql` 在很多機關環境會裝到 MariaDB**
>   （模組化預設），下面另有 MariaDB 對照。先用 `mysql --version` 確認你連的是誰。

> [!info]- MariaDB 差異（機關 RHEL 環境很常見）
> ```bash
> mysql --version
> # mysql  Ver 15.1 Distrib 10.11.x-MariaDB, for Linux (x86_64)   ← ★★★★ 這是 MariaDB
> ```
> 本篇多數內容通用，但這幾點**不一樣**：
>
> | 項目 | MySQL 8.0 | MariaDB 10.11 / 11.x |
> | --- | --- | --- |
> | ★★★★ `ONLY_FULL_GROUP_BY` | **預設開啟** | **預設關閉**（`sql_mode` 不含它） |
> | ★★★ `EXPLAIN ANALYZE` | 8.0.18+ 支援 | 用 `ANALYZE SELECT …`（語法不同） |
> | ★★★ `sys.innodb_lock_waits` | 有 | 用 `information_schema.INNODB_LOCK_WAITS` |
> | ★★ 函式索引 | 8.0.13+ `((DATE(col)))` | 改用虛擬欄位 + 索引 |
> | ★★ 預設 collation | `utf8mb4_0900_ai_ci` | `utf8mb4_general_ci` / `uca1400_ai_ci` |
> | ★★★ `ALGORITHM=INSTANT` | 8.0.12+ | 11.x 才較完整，10.x 支援有限 |
>
> ★★★★ **從 MariaDB 匯出、匯入 MySQL 8 之後，原本能跑的 GROUP BY 會整批報 1055。**
> 這是機關系統轉換最常炸的一項，見下方 `ONLY_FULL_GROUP_BY` 段落。

### 四種一定要會的 client 用法

**（1）`\G` 直式輸出 —— 欄位多的表用橫式根本看不了**

```sql
SELECT * FROM users WHERE id = 1\G
```

預期輸出：

```text
*************************** 1. row ***************************
           id: 1
      account: a.chen
         name: 陳雅婷
         dept: 資訊室
        phone: 0912-345-678
       status: 1
last_login_at: 2026-08-27 10:12:00
   created_at: 2026-01-05 09:00:00
1 row in set (0.00 sec)
```

★★★ `\G` 取代結尾的分號，**不要寫成 `… ;\G`**（會多跑一次）。

**（2）`-e` 一次性查詢 —— 可以塞進腳本與 cron**

```bash
mysql -u ops_ro appdb -e "SELECT COUNT(*) AS n FROM orders;"
```

預期輸出：

```text
+----+
| n  |
+----+
| 10 |
+----+
```

**（3）`source` 執行 SQL 檔 —— ★★★★ 正式機不要貼多行 SQL**

```bash
cat > /tmp/fix-order-4210.sql <<'SQL'
BEGIN;
SELECT id, order_no, status FROM orders WHERE order_no = 'ORD-20260812-0005' FOR UPDATE;
UPDATE orders SET status = 'cancelled' WHERE order_no = 'ORD-20260812-0005';
SELECT ROW_COUNT() AS affected;
SQL
```

```text
mysql> source /tmp/fix-order-4210.sql
```

預期輸出：

```text
Query OK, 0 rows affected (0.00 sec)
+------+-------------------+---------+
| id   | order_no          | status  |
+------+-------------------+---------+
|    5 | ORD-20260812-0005 | pending |
+------+-------------------+---------+
1 row in set (0.00 sec)

Query OK, 1 row affected (0.00 sec)
Rows matched: 1  Changed: 1  Warnings: 0        # ★★★★ 看這一行再決定 COMMIT
+----------+
| affected |
+----------+
|        1 |
+----------+
```

> [!danger] ★★★★ 為什麼不要在正式機直接貼多行 SQL
> 終端機貼上時可能被**截斷**（tmux/SSH 緩衝區、換行符處理），
> 一句 `UPDATE orders SET status='x' WHERE id=5;` 被截成 `UPDATE orders SET status='x';`
> —— **整張表被改**。寫成檔案 + `source` 就沒有這個風險，而且檔案本身就是稽核軌跡。
> 注意上面刻意**沒有把 `COMMIT` 寫進檔案**：讓你看完 `Rows matched` 再手動決定。

**（4）`pager` 分頁器 —— 寬表不要讓它自動換行**

```text
mysql> pager less -SFX
PAGER set to 'less -SFX'
mysql> SELECT * FROM orders;
```

| 旗標 | 作用 | ★ |
| --- | --- | --- |
| `-S` | **不折行**，寬表用左右鍵捲動 | ★★★ 最重要的一個 |
| `-F` | 內容不到一頁就直接印出不進分頁 | ★★ |
| `-X` | 離開時不清畫面（結果留在 scrollback） | ★★★ 要截圖給開發時很有用 |

關掉分頁器（要複製貼上時）：

```text
mysql> nopager
PAGER set to stdout
```

### 建立本篇貫穿用的示範資料

```sql
CREATE DATABASE IF NOT EXISTS appdb
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE appdb;

CREATE TABLE users (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  account       VARCHAR(64)     NOT NULL,
  name          VARCHAR(64)     NOT NULL,
  dept          VARCHAR(32)         NULL,          -- ★★★ 刻意允許 NULL
  phone         VARCHAR(20)         NULL,          -- ★★★ 刻意允許 NULL
  status        TINYINT         NOT NULL DEFAULT 1,
  last_login_at DATETIME            NULL,
  created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_account (account),
  KEY idx_dept (dept)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE orders (
  id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  order_no   VARCHAR(32)     NOT NULL,             -- ★★★★ 字串主鍵，後面示範隱式轉換
  user_id    BIGINT UNSIGNED     NULL,             -- ★★★ 允許 NULL：孤兒訂單
  amount     DECIMAL(10,2)   NOT NULL DEFAULT 0.00,
  status     VARCHAR(16)     NOT NULL DEFAULT 'pending',
  created_at DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_order_no (order_no),
  KEY idx_user_id (user_id),
  KEY idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO users (account, name, dept, phone, status, last_login_at, created_at) VALUES
 ('a.chen','陳雅婷','資訊室','0912-345-678',1,'2026-08-27 10:12:00','2026-01-05 09:00:00'),
 ('b.lin', '林建宏','資訊室','0922-111-222',1,'2026-08-20 09:03:11','2026-01-05 09:00:00'),
 ('c.wang','王思涵','人事室',NULL,          1, NULL,                '2026-02-11 13:20:00'),
 ('d.hsu', '許家豪','主計室','0933-888-999',0,'2026-06-01 14:22:47','2026-02-11 13:20:00'),
 ('e.tsai','蔡孟儒', NULL,   '0955-000-111',1,'2026-08-28 08:41:02','2026-03-02 10:05:00'),
 ('f.kuo', '郭俊良','資訊室',NULL,          1,'2026-08-26 17:55:30','2026-03-02 10:05:00'),
 ('g.yeh', '葉宜靜','人事室','0977-222-333',1, NULL,                '2026-05-19 16:40:00'),
 ('h.chang','張立文','政風室','0988-444-555',0,'2026-03-15 11:09:00','2026-05-19 16:40:00');

INSERT INTO orders (order_no, user_id, amount, status, created_at) VALUES
 ('ORD-20260801-0001',    1,  1200.00,'paid',     '2026-08-01 09:15:00'),
 ('ORD-20260801-0002',    1,   350.50,'paid',     '2026-08-01 14:40:12'),
 ('ORD-20260805-0003',    2,  8800.00,'paid',     '2026-08-05 10:02:33'),
 ('ORD-20260810-0004',    2,   150.00,'cancelled','2026-08-10 16:20:00'),
 ('ORD-20260812-0005',    4,  2400.00,'pending',  '2026-08-12 11:11:11'),
 ('ORD-20260818-0006',    5,    99.00,'paid',     '2026-08-18 08:30:45'),
 ('ORD-20260820-0007',    5, 15000.00,'paid',     '2026-08-20 19:05:20'),
 ('ORD-20260825-0008',    6,   780.00,'refunded', '2026-08-25 13:47:00'),
 ('ORD-20260827-0009',    1,    60.00,'pending',  '2026-08-27 22:10:05'),
 ('ORD-20260828-0010', NULL,   500.00,'pending',  '2026-08-28 07:00:00');
```

★★★ 最後一筆 `user_id` 是 `NULL` —— **來源系統寫入失敗留下的孤兒訂單**。
真實環境一定會有這種資料，本篇的 JOIN 與 NULL 段落全靠它示範。

### SELECT / WHERE / ORDER BY / LIMIT

```sql
SELECT id, name, dept, last_login_at
FROM users
WHERE status = 1
ORDER BY last_login_at DESC
LIMIT 5;
```

預期輸出：

```text
+----+-----------+-----------+---------------------+
| id | name      | dept      | last_login_at       |
+----+-----------+-----------+---------------------+
|  5 | 蔡孟儒    | NULL      | 2026-08-28 08:41:02 |
|  1 | 陳雅婷    | 資訊室    | 2026-08-27 10:12:00 |
|  6 | 郭俊良    | 資訊室    | 2026-08-26 17:55:30 |
|  2 | 林建宏    | 資訊室    | 2026-08-20 09:03:11 |
|  3 | 王思涵    | 人事室    | NULL                |
+----+-----------+-----------+---------------------+
5 rows in set (0.00 sec)
```

★★★ 注意 `NULL` 在 `ORDER BY … DESC` 被排到**最後**（`ASC` 則排最前）。
MySQL 把 `NULL` 當成比任何值都小。報表要 NULL 排前面就 `ORDER BY col IS NULL DESC, col`。

| ★ | 維運上一定要養成的習慣 | 理由 |
| --- | --- | --- |
| ★★★★ | **正式機查詢一律先加 `LIMIT`** | 沒 LIMIT 的 `SELECT *` 撈 312 萬列，記憶體與網路一起爆 |
| ★★★★ | **不要 `SELECT *`，列出要的欄位** | 少讀欄位才可能走到**覆蓋索引**，也避免把個資撈出來 |
| ★★★ | `ORDER BY` 的欄位盡量有索引 | 否則 `Extra` 出現 `Using filesort` |
| ★★★ | 大表分頁不要用 `LIMIT 100000, 20` | MySQL 要先掃過前 10 萬列再丟掉，用「上一頁最後一個 id」往下接 |

深分頁的正確寫法：

```sql
-- ❌ 慢：要掃 100020 列
SELECT id, order_no FROM orders ORDER BY id LIMIT 100000, 20;

-- ✅ 快：直接從索引定位（seek method）
SELECT id, order_no FROM orders WHERE id > 100000 ORDER BY id LIMIT 20;
```

### ★★★★ NULL 的三值邏輯：這是「資料明明在卻查不到」的頭號原因

SQL 的比較不是「真/假」兩值，是「真/假/**未知**」三值。
`NULL` 參與任何比較的結果都是 **UNKNOWN**，而 `WHERE` 只收 TRUE。

```sql
SELECT id, name, dept FROM users WHERE dept = NULL;
```

預期輸出：

```text
Empty set (0.00 sec)                      # ★★★★ 永遠是空的，不會報錯，這才可怕
```

正確寫法：

```sql
SELECT id, name, dept FROM users WHERE dept IS NULL;
```

```text
+----+-----------+------+
| id | name      | dept |
+----+-----------+------+
|  5 | 蔡孟儒    | NULL |
+----+-----------+------+
1 row in set (0.00 sec)
```

**經典事故：`!=` 會偷偷漏掉 NULL**

```sql
SELECT id, name, dept FROM users WHERE dept != '資訊室';
```

```text
+----+-----------+-----------+
| id | name      | dept      |
+----+-----------+-----------+
|  3 | 王思涵    | 人事室    |
|  4 | 許家豪    | 主計室    |
|  7 | 葉宜靜    | 人事室    |
|  8 | 張立文    | 政風室    |
+----+-----------+-----------+
4 rows in set (0.00 sec)                  # ★★★★ 蔡孟儒（dept IS NULL）不見了
```

「不是資訊室的人」明明有 5 個，卻只回 4 個。正確：

```sql
SELECT id, name, dept FROM users
WHERE dept != '資訊室' OR dept IS NULL;
-- 或用 NULL 安全的等號：
SELECT id, name, dept FROM users WHERE NOT (dept <=> '資訊室');
```

**`NOT IN` + 子查詢有 NULL → 直接全空**

```sql
SELECT id, name FROM users
WHERE id NOT IN (SELECT user_id FROM orders);
```

```text
Empty set (0.00 sec)                      # ★★★★ 三個沒下單的人全部消失
```

原因：子查詢裡有一個 `NULL`（孤兒訂單），`id NOT IN (1,2,4,5,6,NULL)`
展開後含 `id <> NULL` = UNKNOWN，整條 `AND` 鏈永遠不會是 TRUE。

正確寫法（三選一，優先用 `NOT EXISTS`）：

```sql
-- ✅ 最穩：NOT EXISTS 不受 NULL 影響
SELECT u.id, u.name FROM users u
WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.user_id = u.id);

-- ✅ 或在子查詢過濾掉 NULL
SELECT id, name FROM users
WHERE id NOT IN (SELECT user_id FROM orders WHERE user_id IS NOT NULL);
```

```text
+----+-----------+
| id | name      |
+----+-----------+
|  3 | 王思涵    |
|  7 | 葉宜靜    |
|  8 | 張立文    |
+----+-----------+
3 rows in set (0.00 sec)
```

**`COUNT(*)` 與 `COUNT(欄位)` 差在 NULL**

```sql
SELECT COUNT(*)              AS 全部,
       COUNT(phone)          AS 有電話,
       COUNT(last_login_at)  AS 登入過,
       COUNT(DISTINCT dept)  AS 部門數
FROM users;
```

```text
+--------+-----------+--------+-----------+
| 全部   | 有電話    | 登入過 | 部門數    |
+--------+-----------+--------+-----------+
|      8 |         6 |      6 |         4 |
+--------+-----------+--------+-----------+
```

★★★ `COUNT(欄位)` **不算 NULL**，`COUNT(DISTINCT dept)` 也**不算 NULL**（所以是 4 不是 5）。
「使用者說報表人數對不上」十次有八次是這個。要總列數**永遠用 `COUNT(*)`**。

| 寫法 | 結果 | ★ |
| --- | --- | --- |
| `NULL = NULL` | `NULL`（不是 1） | ★★★★ |
| `NULL <=> NULL` | `1` | ★★★ NULL 安全等號 |
| `NULL + 1` | `NULL` | ★★★ 金額欄位有 NULL，加總就整個變 NULL |
| `SUM(amount)` 全 NULL 時 | `NULL`（不是 0） | ★★★ 報表用 `IFNULL(SUM(amount),0)` |
| `CONCAT('a', NULL)` | `NULL` | ★★ 用 `CONCAT_WS` 或 `COALESCE` |
| `'' = NULL` | `NULL` | ★★★ **空字串不等於 NULL**，這是兩種東西 |

### ★★★★ 改資料的安全流程（本篇最重要的一段）

使用者說「這筆訂單狀態要幫我改成取消」。**五個步驟，一步都不能跳。**

```text
【1】先寫成 SELECT，確認影響幾列
【2】BEGIN 開交易
【3】執行 UPDATE，看 Rows matched / Changed
【4】再 SELECT 一次確認結果
【5】對 → COMMIT；不對 → ROLLBACK
```

**【1】把 UPDATE 的 WHERE 原封不動搬到 SELECT**

```sql
SELECT COUNT(*) FROM orders WHERE order_no = 'ORD-20260812-0005';
```

```text
+----------+
| COUNT(*) |
+----------+
|        1 |
+----------+
```

★★★★ **看到 1 才往下走。** 看到 0 表示條件寫錯（訂單編號打錯）；
看到 3421 表示條件太寬 —— 這時候按下 `UPDATE` 就是事故。

**【2】關掉 autocommit 或直接 `BEGIN`**

```sql
SELECT @@autocommit;
```

```text
+--------------+
| @@autocommit |
+--------------+
|            1 |          # ★★★★ 預設是 1：每一句 UPDATE 執行完就【立刻落地】
+--------------+
```

```sql
BEGIN;
```

```text
Query OK, 0 rows affected (0.00 sec)     # ★★★ 從這一刻起，你有後悔的權利
```

**【3】執行，然後盯住 `Rows matched` 與 `Changed`**

```sql
UPDATE orders SET status = 'cancelled' WHERE order_no = 'ORD-20260812-0005';
```

```text
Query OK, 1 row affected (0.00 sec)
Rows matched: 1  Changed: 1  Warnings: 0
```

| 你看到 | 意思 | 該做什麼 |
| --- | --- | --- |
| `Rows matched: 1  Changed: 1` | 找到 1 列、改了 1 列 | ★★★★ 正常，往下走 |
| `Rows matched: 1  Changed: 0` | 找到了但**值本來就一樣** | ★★★ 通常不是問題，但要確認是不是條件抓錯人 |
| `Rows matched: 0  Changed: 0` | **完全沒找到** | ★★★ 條件寫錯，`ROLLBACK` 重來 |
| ★★★★★ `Rows matched: 3421` | **WHERE 沒生效或範圍太大** | **立刻 `ROLLBACK`**，不要猶豫 |

**【4】在同一個交易裡再看一次**

```sql
SELECT id, order_no, status, amount FROM orders WHERE order_no = 'ORD-20260812-0005';
```

```text
+----+-------------------+-----------+---------+
| id | order_no          | status    | amount  |
+----+-------------------+-----------+---------+
|  5 | ORD-20260812-0005 | cancelled | 2400.00 |
+----+-------------------+-----------+---------+
```

★★★ 這個 `SELECT` **只有你自己看得到新值**（隔離性）；其他連線還是看到 `pending`。

**【5】確認無誤才 COMMIT**

```sql
COMMIT;
```

```text
Query OK, 0 rows affected (0.01 sec)     # ★★★★ 這一刻之後就不能 ROLLBACK 了
```

改錯了的話：

```sql
ROLLBACK;
```

```text
Query OK, 0 rows affected (0.00 sec)     # ★★★ 資料回到 BEGIN 之前
```

> [!danger] ★★★★★ 全篇最高風險的一行
> ```sql
> UPDATE orders SET status = 'cancelled';     -- 沒有 WHERE
> DELETE FROM orders;                          -- 沒有 WHERE
> ```
> 在 `autocommit=1` 的情況下，**按下 Enter 的瞬間 312 萬列全部被改／被刪，
> 而且沒有任何確認提示**。唯一的救法是 [[060-04-01-05-svc-MySQL-備份與還原]] 的
> 「全備 + binlog 時間點還原」，而那需要停服務、需要數小時，而且期間新資料會遺失。
>
> **兩道護欄，兩道都要架：**
> 1. `--safe-updates`（下一段）—— 讓沒有 WHERE 的 UPDATE/DELETE 直接被伺服器擋下。
> 2. `BEGIN` 包起來 —— 讓按錯了還能 `ROLLBACK`。

### `--safe-updates`：讓沒有 WHERE 的 UPDATE 根本執行不了

```bash
mysql --safe-updates -u ops_rw appdb
```

連線時 client 會自動送出：

```sql
SET sql_safe_updates=1, sql_select_limit=1000, max_join_size=1000000;
```

實測：

```sql
UPDATE orders SET status = 'cancelled';
```

```text
ERROR 1175 (HY000): You are using safe update mode and you tried to update a table
without a WHERE that uses a KEY column.
```

★★★★ **這就是我們要的。** 想改一列，就得明確給出用到索引的條件：

```sql
UPDATE orders SET status = 'cancelled' WHERE id = 5;
```

```text
Query OK, 1 row affected (0.00 sec)
Rows matched: 1  Changed: 1  Warnings: 0
```

| `--safe-updates` 連帶設定 | 值 | 效果 | ★ |
| --- | --- | --- | --- |
| `sql_safe_updates` | `1` | ★★★★ UPDATE/DELETE 的 WHERE **必須用到 key 欄位**，或帶 `LIMIT` | ★★★★ |
| `sql_select_limit` | `1000` | ★★★ 沒寫 `LIMIT` 的 SELECT **自動只回 1000 列** | ★★★ |
| `max_join_size` | `1000000` | ★★★ 估計要檢查超過 100 萬列組合的多表查詢**直接報錯** | ★★★ |

> [!warning] ★★★ `sql_select_limit=1000` 會咬人
> 你查「這個月訂單」出來剛好 1000 筆，很容易以為就是 1000 筆。
> 真的要撈全部時**明確覆蓋掉**：
> ```sql
> SET SESSION sql_select_limit = DEFAULT;
> ```
> 或直接在 SQL 裡寫 `LIMIT 100000`。
> **不要因為被擋一次就把 `safe-updates` 從 `~/.my.cnf` 拿掉。**

臨時解除（僅限你確定要跑全表更新，例如資料修補作業）：

```sql
SET SESSION sql_safe_updates = 0;
BEGIN;                                   -- ★★★★ 解除保險就一定要開交易
UPDATE orders SET status = 'archived' WHERE created_at < '2025-01-01';
-- 看 Rows matched，確認後才 COMMIT
```

`safe-updates` 認可的三種 WHERE：

```sql
-- ✅ 用到主鍵或索引欄位的等值 / 範圍條件
UPDATE orders SET status='x' WHERE id = 5;
UPDATE orders SET status='x' WHERE created_at BETWEEN '2026-08-01' AND '2026-08-02';

-- ✅ 帶 LIMIT（分批修補資料很常用）
UPDATE orders SET status='x' WHERE status='pending' LIMIT 1000;

-- ❌ 條件欄位沒有索引 → 一樣被擋（因為會全表掃）
UPDATE orders SET status='x' WHERE amount > 10000;
-- ERROR 1175
```

---

## 進階應用

### 交易與鎖：★★★ 開了交易忘了 COMMIT，整個服務看起來像掛掉

這是維運現場最常見、也最容易誤判成「資料庫壞了」的狀況。

**現象重現**

連線 A（某個人開著 tmux 去吃飯了）：

```sql
BEGIN;
UPDATE orders SET status = 'paid' WHERE id = 5;
-- ★★★★ 然後就走了，沒有 COMMIT 也沒有 ROLLBACK
```

連線 B（線上服務）：

```sql
UPDATE orders SET status = 'refunded' WHERE id = 5;
```

```text
（游標停住 50 秒）
ERROR 1205 (HY000): Lock wait timeout exceeded; try restarting transaction
```

同時 `SHOW PROCESSLIST` 長這樣：

```sql
SHOW PROCESSLIST;
```

```text
+------+---------+-----------------+-------+---------+------+------------------------+------------------+
| Id   | User    | Host            | db    | Command | Time | State                  | Info             |
+------+---------+-----------------+-------+---------+------+------------------------+------------------+
| 4127 | ops_rw  | 10.1.2.30:51234 | appdb | Sleep   | 1820 |                        | NULL             |
| 4210 | app     | 10.1.2.40:44120 | appdb | Query   |   47 | updating               | UPDATE orders …  |
| 4211 | app     | 10.1.2.40:44121 | appdb | Query   |   45 | updating               | UPDATE orders …  |
| 4212 | app     | 10.1.2.40:44122 | appdb | Query   |   44 | updating               | UPDATE orders …  |
| 4213 | app     | 10.1.2.40:44123 | appdb | Query   |   42 | updating               | UPDATE orders …  |
+------+---------+-----------------+-------+---------+------+------------------------+------------------+
```

> [!note] ★★★★ 判讀關鍵
> **一堆 `Query` 卡在同一張表，而元凶是那個 `Command=Sleep` 但 `Time` 很大的連線。**
> 直覺會去 KILL 那些卡住的（`Time=47`），但它們是受害者 ——
> **真正要處理的是 `Sleep 1820` 的 4127**，它開著交易握著鎖在睡覺。

**找出誰擋住誰：`sys.innodb_lock_waits`**

```sql
SELECT waiting_pid, waiting_query, blocking_pid, blocking_query,
       wait_age, sql_kill_blocking_query
FROM sys.innodb_lock_waits\G
```

```text
*************************** 1. row ***************************
            waiting_pid: 4210
          waiting_query: UPDATE orders SET status = 'refunded' WHERE id = 5
           blocking_pid: 4127
         blocking_query: NULL                       # ★★★★ NULL = 它現在沒在跑 SQL，只是握著鎖
               wait_age: 00:00:47
sql_kill_blocking_query: KILL QUERY 4127            # ★★★ sys 直接把指令生給你
1 row in set (0.01 sec)
```

★★★★ `blocking_query` 是 `NULL` 就是鐵證：**那個連線沒在做事，只是忘了 COMMIT。**

**看那個交易到底開多久了**

```sql
SELECT trx_id, trx_state, trx_started,
       TIMESTAMPDIFF(SECOND, trx_started, NOW()) AS 開了幾秒,
       trx_mysql_thread_id AS pid, trx_rows_locked, trx_query
FROM information_schema.innodb_trx
ORDER BY trx_started\G
```

```text
*************************** 1. row ***************************
             trx_id: 4212883
          trx_state: RUNNING
        trx_started: 2026-08-28 13:42:11
        開了幾秒    : 1820                          # ★★★★ 超過 5 分鐘的交易一律當異常
                pid: 4127
    trx_rows_locked: 1
          trx_query: NULL
```

**`KILL` 的正確用法**

| 指令 | 作用 | 什麼時候用 | ★ |
| --- | --- | --- | --- |
| `KILL QUERY 4127` | 只中止**目前這一句**，連線與交易保留 | ★★★ 對付「跑了 20 分鐘的大查詢」 | ★★★ |
| `KILL 4127` / `KILL CONNECTION 4127` | **殺整條連線**，未完成的交易自動 `ROLLBACK` | ★★★★ 對付「忘了 COMMIT 的殭屍連線」 | ★★★★ |

```sql
KILL CONNECTION 4127;
```

```text
Query OK, 0 rows affected (0.00 sec)
```

被 KILL 的那一端會看到：

```text
ERROR 2013 (HY000): Lost connection to MySQL server during query
```

> [!danger] ★★★★ KILL 之前一定要先確認三件事
> 1. **這個 pid 是誰**：`SELECT * FROM performance_schema.processlist WHERE id=4127\G`
>    —— 看 `USER` / `HOST`。是人的維運視窗還是應用程式的連線池？
> 2. **它改了多少列**：`trx_rows_modified`。
>    ★★★★ 一個改了 200 萬列的交易被 KILL，InnoDB 要**回滾這 200 萬列**，
>    回滾期間磁碟 I/O 會更高、時間可能比原本執行還久，而且**不能中斷**。
> 3. **殺了誰會受影響**：如果是應用程式的連線，前台會看到 500。
>    先通知，不要無聲無息地殺。
>
> 對「忘了 COMMIT 的人類連線」（`trx_rows_modified` 很小）—— 放心殺。
> 對「跑到一半的大批次」—— **先找到人，不要直接殺。**

**相關參數（調整屬於 [[060-04-01-04-svc-MySQL-設定檔與調校]]，這裡只要看得懂）**

```sql
SELECT @@innodb_lock_wait_timeout AS 鎖等待秒數,
       @@wait_timeout             AS 閒置連線秒數,
       @@transaction_isolation    AS 隔離等級;
```

```text
+-----------------+-------------------+-----------------+
| 鎖等待秒數      | 閒置連線秒數      | 隔離等級        |
+-----------------+-------------------+-----------------+
|              50 |             28800 | REPEATABLE-READ |
+-----------------+-------------------+-----------------+
```

| 參數 | 預設 | 維運意義 | ★ |
| --- | --- | --- | --- |
| `innodb_lock_wait_timeout` | 50 秒 | 等鎖超過就丟 ERROR 1205。★★★ 調小 → 前台快點失敗；調大 → 卡更久 | ★★★ |
| `wait_timeout` | 28800 秒（8 小時） | ★★★★ 閒置連線 8 小時才斷 —— 這就是殭屍交易能活這麼久的原因 | ★★★★ |
| `transaction_isolation` | `REPEATABLE-READ` | MySQL 預設，比多數資料庫嚴格 | ★★ |

> [!tip] ★★★ 給人用的維運帳號設短一點的 timeout
> ```sql
> CREATE USER 'ops_rw'@'10.1.2.%' IDENTIFIED BY '…';
> ALTER USER 'ops_rw'@'10.1.2.%' WITH MAX_USER_CONNECTIONS 3;
> ```
> 再搭配 `~/.my.cnf` 裡的 `init-command`：
> ```ini
> [mysql]
> init-command = "SET SESSION wait_timeout=900, innodb_lock_wait_timeout=10"
> ```
> **人的視窗閒置 15 分鐘就斷線**，殭屍交易的最大傷害從 8 小時降到 15 分鐘。

**死鎖（Deadlock）是另一回事**

```text
ERROR 1213 (40001): Deadlock found when trying to get lock; try restarting transaction
```

★★★ 死鎖是 InnoDB **自動偵測並主動犧牲其中一個交易**，所以它會**立刻**回錯，不會卡 50 秒。
看細節：

```sql
SHOW ENGINE INNODB STATUS\G
```

```text
------------------------
LATEST DETECTED DEADLOCK
------------------------
2026-08-28 14:03:12 0x7f2a...
*** (1) TRANSACTION:
TRANSACTION 4212901, ACTIVE 3 sec starting index read
UPDATE orders SET status='paid' WHERE id=5
*** (2) TRANSACTION:
TRANSACTION 4212902, ACTIVE 2 sec starting index read
UPDATE orders SET status='paid' WHERE id=7
*** WE ROLL BACK TRANSACTION (2)               # ★★★ 被犧牲的是 (2)
```

死鎖的根因幾乎都是**兩支程式以相反順序鎖同一批列**，屬於應用端要修的問題
（見 [[070-03-04-guide-Laravel-Eloquent與資料庫]]），維運端能做的是：把上面這段抓下來交給開發。

### JOIN 四種形式：用同一組資料看差異

```text
users（8 人）                orders（10 筆）
 ├ 1 陳雅婷 ──────────┬──── ORD-…0001
 ├ 2 林建宏 ────┐     ├──── ORD-…0002
 ├ 3 王思涵 ✗   │     └──── ORD-…0009
 ├ 4 許家豪 ────┼─┐
 ├ 5 蔡孟儒 ────┼─┼─┐
 ├ 6 郭俊良 ────┼─┼─┼─┐
 ├ 7 葉宜靜 ✗   │ │ │ │
 └ 8 張立文 ✗   … … … …
                            ORD-…0010 (user_id NULL) ✗ 孤兒
```

**INNER JOIN —— 兩邊都有才出現（9 列）**

```sql
SELECT u.name, o.order_no, o.amount
FROM users u
INNER JOIN orders o ON o.user_id = u.id
ORDER BY u.id, o.id;
```

```text
+-----------+-------------------+----------+
| name      | order_no          | amount   |
+-----------+-------------------+----------+
| 陳雅婷    | ORD-20260801-0001 |  1200.00 |
| 陳雅婷    | ORD-20260801-0002 |   350.50 |
| 陳雅婷    | ORD-20260827-0009 |    60.00 |
| 林建宏    | ORD-20260805-0003 |  8800.00 |
| 林建宏    | ORD-20260810-0004 |   150.00 |
| 許家豪    | ORD-20260812-0005 |  2400.00 |
| 蔡孟儒    | ORD-20260818-0006 |    99.00 |
| 蔡孟儒    | ORD-20260820-0007 | 15000.00 |
| 郭俊良    | ORD-20260825-0008 |   780.00 |
+-----------+-------------------+----------+
9 rows in set (0.00 sec)                    # ★★★ 沒下單的 3 人與孤兒訂單都不見了
```

**LEFT JOIN —— 左表全留（12 列）**

```sql
SELECT u.name, o.order_no, o.amount
FROM users u
LEFT JOIN orders o ON o.user_id = u.id
ORDER BY u.id, o.id;
```

```text
… （前 9 列同上）…
| 葉宜靜    | NULL              |     NULL |
| 王思涵    | NULL              |     NULL |
| 張立文    | NULL              |     NULL |
+-----------+-------------------+----------+
12 rows in set (0.00 sec)                   # ★★★ 9 + 3 個沒下單的人
```

★★★ **「找出沒有下過單的使用者」的標準寫法**就是 LEFT JOIN 之後濾 NULL：

```sql
SELECT u.id, u.name FROM users u
LEFT JOIN orders o ON o.user_id = u.id
WHERE o.id IS NULL;
```

```text
+----+-----------+
| id | name      |
+----+-----------+
|  3 | 王思涵    |
|  7 | 葉宜靜    |
|  8 | 張立文    |
+----+-----------+
```

**RIGHT JOIN —— 右表全留（10 列），維運上最有用的是抓孤兒資料**

```sql
SELECT u.name, o.order_no, o.user_id
FROM users u
RIGHT JOIN orders o ON o.user_id = u.id
WHERE u.id IS NULL;
```

```text
+------+-------------------+---------+
| name | order_no          | user_id |
+------+-------------------+---------+
| NULL | ORD-20260828-0010 |    NULL |
+------+-------------------+---------+
1 row in set (0.00 sec)                     # ★★★ 抓到孤兒訂單
```

★★ 實務上大家習慣把表順序調過來寫成 LEFT JOIN，可讀性比較好；
`RIGHT JOIN` 混在多表查詢裡很容易看錯，**能改寫成 LEFT 就改寫**。

**SELF JOIN —— 同一張表跟自己接，找重複／找上下級**

```sql
-- 找出「同部門、同一天建立」的成對帳號（疑似重複建檔）
SELECT a.id AS id1, a.name AS name1, b.id AS id2, b.name AS name2, a.dept
FROM users a
JOIN users b
  ON a.dept = b.dept
 AND DATE(a.created_at) = DATE(b.created_at)
 AND a.id < b.id                              -- ★★★ 避免自己跟自己配、避免 A-B/B-A 重複
ORDER BY a.id;
```

```text
+-----+-----------+-----+-----------+-----------+
| id1 | name1     | id2 | name2     | dept      |
+-----+-----------+-----+-----------+-----------+
|   1 | 陳雅婷    |   2 | 林建宏    | 資訊室    |
+-----+-----------+-----+-----------+-----------+
1 row in set (0.00 sec)
```

★★★ `a.id < b.id` 是 SELF JOIN 的固定招式，忘了寫結果會是 3 倍列數。

### ★★★★ LEFT JOIN 被 WHERE 退化成 INNER JOIN

這是 JOIN 最經典的錯誤，「報表少了一堆人」十次有九次是它。

```sql
-- ❌ 想「列出所有使用者與他們已付款的訂單」
SELECT u.name, o.order_no, o.status
FROM users u
LEFT JOIN orders o ON o.user_id = u.id
WHERE o.status = 'paid';
```

```text
+-----------+-------------------+--------+
| name      | order_no          | status |
+-----------+-------------------+--------+
| 陳雅婷    | ORD-20260801-0001 | paid   |
| 陳雅婷    | ORD-20260801-0002 | paid   |
| 林建宏    | ORD-20260805-0003 | paid   |
| 蔡孟儒    | ORD-20260818-0006 | paid   |
| 蔡孟儒    | ORD-20260820-0007 | paid   |
+-----------+-------------------+--------+
5 rows in set (0.00 sec)                    # ★★★★ 沒下單的 3 人不見了
```

**為什麼？** LEFT JOIN 先產生 12 列（含 3 列右表全 NULL），
然後 `WHERE o.status = 'paid'` 拿去比對 —— `NULL = 'paid'` 是 UNKNOWN，
**那 3 列在 WHERE 這關被濾掉了**。結果等同 INNER JOIN。

```text
LEFT JOIN 產生 12 列
        │
        ▼  WHERE o.status='paid'
   NULL 列的 o.status 是 NULL
   NULL = 'paid' → UNKNOWN → 被濾掉
        │
        ▼
     5 列（= INNER JOIN 的結果）★★★★
```

**正確寫法：條件放進 `ON`**

```sql
SELECT u.name, o.order_no, o.status
FROM users u
LEFT JOIN orders o
       ON o.user_id = u.id
      AND o.status  = 'paid'                 -- ★★★★ 在 ON 裡，不在 WHERE
ORDER BY u.id;
```

```text
+-----------+-------------------+--------+
| name      | order_no          | status |
+-----------+-------------------+--------+
| 陳雅婷    | ORD-20260801-0001 | paid   |
| 陳雅婷    | ORD-20260801-0002 | paid   |
| 林建宏    | ORD-20260805-0003 | paid   |
| 王思涵    | NULL              | NULL   |
| 許家豪    | NULL              | NULL   |   ← 他有訂單但不是 paid，仍然列出
| 蔡孟儒    | ORD-20260818-0006 | paid   |
| 蔡孟儒    | ORD-20260820-0007 | paid   |
| 郭俊良    | NULL              | NULL   |
| 葉宜靜    | NULL              | NULL   |
| 張立文    | NULL              | NULL   |
+-----------+-------------------+--------+
10 rows in set (0.00 sec)                   # ★★★ 8 個人全部在，這才是要的
```

> [!tip] ★★★ 三秒判斷法
> **看到 `LEFT JOIN` 的同時，`WHERE` 裡出現右表的欄位（且不是 `IS NULL`）——
> 這句話已經退化成 `INNER JOIN` 了。**
> 例外只有一個：`WHERE o.id IS NULL`，那是刻意在找「沒配對到的列」。

### 聚合查詢與 ★★★★ `ONLY_FULL_GROUP_BY`

**正常的聚合**

```sql
SELECT u.dept,
       COUNT(*)                    AS 訂單數,
       COUNT(DISTINCT u.id)        AS 有下單人數,
       SUM(o.amount)               AS 總金額,
       ROUND(AVG(o.amount), 2)     AS 平均金額
FROM users u
JOIN orders o ON o.user_id = u.id
GROUP BY u.dept
HAVING SUM(o.amount) > 1000                 -- ★★★ HAVING 過濾「聚合後」的結果
ORDER BY 總金額 DESC;
```

```text
+-----------+-----------+-----------------+-----------+--------------+
| dept      | 訂單數    | 有下單人數      | 總金額    | 平均金額     |
+-----------+-----------+-----------------+-----------+--------------+
| NULL      |         2 |               1 |  15099.00 |      7549.50 |
| 資訊室    |         6 |               3 |  11190.50 |      1865.08 |
| 主計室    |         1 |               1 |   2400.00 |      2400.00 |
+-----------+-----------+-----------------+-----------+--------------+
3 rows in set (0.00 sec)
```

★★★ `GROUP BY` 會把 `NULL` **當成一組**（跟 `COUNT(DISTINCT)` 不算 NULL 剛好相反）。
報表裡出現一列 `dept = NULL` 通常代表**來源資料沒填部門**，要回報給業務單位補。

| 關鍵字 | 過濾時機 | 能不能用聚合函式 | ★ |
| --- | --- | --- | --- |
| `WHERE` | **分組前**，先篩掉列 | ❌ 不能用 `SUM()` | ★★★ 能放 WHERE 就放 WHERE，資料少走得快 |
| `HAVING` | **分組後**，篩掉整組 | ✅ 可以 | ★★★ |

**★★★★ MySQL 8 的 `ONLY_FULL_GROUP_BY`：舊系統升級後大量報錯的頭號原因**

```sql
SELECT @@sql_mode;
```

```text
+-------------------------------------------------------------------------------------------------------------------------+
| @@sql_mode                                                                                                              |
+-------------------------------------------------------------------------------------------------------------------------+
| ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION   |
+-------------------------------------------------------------------------------------------------------------------------+
```

★★★★ **`ONLY_FULL_GROUP_BY` 在 MySQL 5.7 起就是預設的一部分，8.0 依然保留。**
MariaDB 與很多舊系統的設定檔把它關掉了，所以「從 MariaDB / 舊 MySQL 搬到 MySQL 8」
會整批出現 1055。

```sql
SELECT dept, name, COUNT(*) FROM users GROUP BY dept;
```

```text
ERROR 1055 (42000): Expression #2 of SELECT list is not in GROUP BY clause and contains
nonaggregated column 'appdb.users.name' which is not functionally dependent on columns
in GROUP BY clause; this is incompatible with sql_mode=only_full_group_by
```

**為什麼要報這個錯（不是 MySQL 找麻煩）**

```text
GROUP BY dept 之後，「資訊室」這一組裡有 3 個 name
  陳雅婷 / 林建宏 / 郭俊良
你要 MySQL 印哪一個？
  → 舊版隨便挑一個（結果不確定，報表數字每次不一樣）★★★★
  → MySQL 8 直接報錯，逼你講清楚
```

**三種改法，用前兩種**

```sql
-- ✅ 改法 1：想要的是「代表值」就明確用聚合函式
SELECT dept, MAX(name) AS 範例姓名, COUNT(*) AS 人數
FROM users GROUP BY dept;

-- ✅ 改法 2：本來就該一起分組的就加進 GROUP BY
SELECT dept, status, COUNT(*) AS 人數
FROM users GROUP BY dept, status;

-- ⚠️ 改法 3：ANY_VALUE() —— 明確告訴 MySQL「我知道值不確定，隨便給一個」
SELECT dept, ANY_VALUE(name) AS 隨便一個, COUNT(*) FROM users GROUP BY dept;
```

改法 1 的輸出：

```text
+-----------+--------------+--------+
| dept      | 範例姓名     | 人數   |
+-----------+--------------+--------+
| NULL      | 蔡孟儒       |      1 |
| 人事室    | 王思涵       |      2 |
| 主計室    | 許家豪       |      1 |
| 政風室    | 張立文       |      1 |
| 資訊室    | 郭俊良       |      3 |
+-----------+--------------+--------+
```

> [!danger] ★★★★ 不要為了讓舊 SQL 跑起來就把 `ONLY_FULL_GROUP_BY` 關掉
> ```ini
> # ❌ 千萬不要這樣「修好」
> [mysqld]
> sql_mode = "STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION"
> ```
> 關掉之後那些 SQL 不會報錯了，但**回傳的值是「同組中隨便一列」**。
> 對機關報表的意義是：**同一份統計報表，今天跑跟明天跑數字可能不一樣**，
> 而且不會有任何警告。等有人發現時，錯誤的報表已經送出去了。
>
> **正確做法：改 SQL。** 用下面這招把所有出問題的查詢一次找出來，交給開發：
> ```bash
> # ★★★ 升級前，在測試複本上開著 error log 跑一輪回歸測試
> sudo grep -c '1055' /var/log/mysql/error.log
> ```
> 慢查詢日誌與錯誤日誌的開啟方式見 [[060-04-01-04-svc-MySQL-設定檔與調校]]。
>
> 真的因為時程壓力必須暫時關閉，**只在 session 層級關、只給那支程式**，
> 並開票追蹤：`SET SESSION sql_mode = ''`；**絕對不要寫進 `my.cnf` 全域生效。**

### 索引與 `EXPLAIN` 判讀

**`EXPLAIN` 的 `type` 欄位，由壞到好**

| `type` | 意思 | 判斷 | ★ |
| --- | --- | --- | --- |
| `ALL` | **全表掃描** | ★★★★ 大表出現這個就是問題 | ★★★★ |
| `index` | 掃**整個索引**（比 ALL 好一點點） | ★★★ 通常也是問題 | ★★★ |
| `range` | 索引**範圍**掃描 | ★★ 可接受，看 `rows` 大不大 | ★★★ |
| `ref` | 用**非唯一索引**等值查找 | ★ 好 | ★★ |
| `eq_ref` | 用**唯一索引/主鍵**等值查找（JOIN 時） | ★ 很好 | ★★ |
| `const` / `system` | 主鍵或唯一索引常數比對，**最多一列** | ★ 最好 | ★ |
| `NULL` | 根本不用讀表（例如 `WHERE 1=0`） | ★ 最好 | ★ |

**其他要盯的欄位**

| 欄位 | 意義 | 危險訊號 | ★ |
| --- | --- | --- | --- |
| `possible_keys` | 優化器**考慮過**的索引 | 是 `NULL` → 連候選都沒有 | ★★★ |
| `key` | **實際用的**索引 | ★★★★ `NULL` = 沒用索引 | ★★★★ |
| `key_len` | 用到索引的**前幾個位元組** | ★★★ 比預期短 → 複合索引只用了前面幾欄 | ★★★ |
| `rows` | 估計**要檢查**幾列 | ★★★★ 跟實際回傳列數差好幾個數量級 → 有問題 | ★★★★ |
| `filtered` | 過濾後剩下的百分比 | ★★★ 很低（如 `1.00`）表示白讀了 99% | ★★★ |
| `Extra` | 額外動作 | 見下表 | ★★★★ |

| `Extra` 內容 | 意義 | ★ |
| --- | --- | --- |
| `Using index` | ★ **覆蓋索引** —— 只讀索引不回表，最快 | ★★ 好消息 |
| `Using where` | 讀出來後還要再過濾 | ★ 常見，不一定是問題 |
| `Using filesort` | ★★★ **要額外排序**（不一定用到磁碟，名字誤導） | ★★★ |
| `Using temporary` | ★★★★ **要建暫存表**（GROUP BY / DISTINCT 常見） | ★★★★ |
| `Using index condition` | 索引條件下推（ICP），是好事 | ★ |
| `Using join buffer (hash join)` | JOIN 欄位沒索引，改用 hash join | ★★★ 大表要注意 |

**實際跑一次**

```sql
EXPLAIN SELECT id, order_no FROM orders WHERE user_id = 1\G
```

```text
*************************** 1. row ***************************
           id: 1
  select_type: SIMPLE
        table: orders
   partitions: NULL
         type: ref                     # ★ 用到非唯一索引
possible_keys: idx_user_id
          key: idx_user_id             # ★★★ 實際用了
      key_len: 9
          ref: const
         rows: 3
     filtered: 100.00
        Extra: NULL
```

`key_len: 9` 怎麼來的：`user_id` 是 `BIGINT UNSIGNED`（8 bytes）+ **允許 NULL 多 1 byte** = 9。
★★★ `key_len` 是判斷「複合索引用到第幾欄」的唯一依據，後面會用到。

**`EXPLAIN ANALYZE`：看實際耗時（MySQL 8.0.18+）**

```sql
EXPLAIN ANALYZE
SELECT id, order_no FROM orders WHERE user_id = 1\G
```

```text
*************************** 1. row ***************************
EXPLAIN: -> Index lookup on orders using idx_user_id (user_id=1)
   (cost=1.31 rows=3) (actual time=0.041..0.052 rows=3 loops=1)
```

| 讀法 | 說明 | ★ |
| --- | --- | --- |
| `cost=1.31 rows=3` | 優化器**估的** | ★★ |
| `actual time=0.041..0.052` | **實際**啟動時間..完成時間（毫秒） | ★★★★ |
| `rows=3 loops=1` | **實際**回傳列數、執行幾次 | ★★★★ |

★★★★ **估的 `rows` 與實際 `rows` 差很多（10 倍以上）就是統計值過期**，跑：

```sql
ANALYZE TABLE orders;
```

```text
+--------------+---------+----------+----------+
| Table        | Op      | Msg_type | Msg_text |
+--------------+---------+----------+----------+
| appdb.orders | analyze | status   | OK       |
+--------------+---------+----------+----------+
1 row in set (0.02 sec)
```

★★★ `ANALYZE TABLE` **只重算統計值，不重建資料，秒級完成，正式機可以跑**
（但會短暫拿 metadata 鎖，尖峰時段仍建議避開）。
它跟 `OPTIMIZE TABLE`（會重建整張表、鎖很久）**完全不是同一件事**。

### ★★★★ 索引失效的三種寫法

以下都在 312 萬列的 `orders` 正式複本上跑。

**（一）函式包住欄位 —— 最常見**

```sql
EXPLAIN SELECT COUNT(*) FROM orders WHERE DATE(created_at) = '2026-08-28'\G
```

```text
         type: ALL                     # ★★★★ 全表掃
possible_keys: NULL                    # ★★★★ 連候選索引都沒有
          key: NULL
      key_len: NULL
         rows: 3118422
     filtered: 100.00
        Extra: Using where
```

**原因**：索引存的是 `created_at` 的原值，`DATE(created_at)` 是**運算後的值**，
索引裡沒有這個東西，只能整張表算一遍。

**改寫成範圍條件：**

```sql
EXPLAIN SELECT COUNT(*) FROM orders
WHERE created_at >= '2026-08-28 00:00:00'
  AND created_at <  '2026-08-29 00:00:00'\G
```

```text
         type: range                   # ★★★ ALL → range
possible_keys: idx_created_at
          key: idx_created_at          # ★★★ 走到索引了
      key_len: 5
         rows: 1842
     filtered: 100.00
        Extra: Using where; Using index
```

★★★★ **`rows` 從 311 萬降到 1842，是 1700 倍的差距。** 這就是 12 秒與 0.3 秒的來源。

> [!tip] ★★★ 用 `< 隔天 00:00:00`，不要用 `BETWEEN … '2026-08-28 23:59:59'`
> `DATETIME(3)` 有毫秒精度時，`23:59:59.500` 會被漏掉。
> **半開區間 `>= 今天 AND < 明天` 永遠正確。**

> [!info]- 真的必須用函式時：函式索引（MySQL 8.0.13+）
> ```sql
> ALTER TABLE orders ADD INDEX idx_created_date ((DATE(created_at)));
> ```
> ★★★ 語法上**兩層括號不能少**（外層是索引欄位列表，內層是運算式）。
> 但這是下策 —— 多一個索引就多一份寫入成本與空間，
> **能改寫 SQL 就改寫 SQL**。MariaDB 沒有這個語法，要改用虛擬欄位 + 索引。

**（二）隱式型別轉換 —— 最陰險，因為 SQL 看起來完全正常**

`order_no` 是 `VARCHAR(32)`：

```sql
EXPLAIN SELECT id, amount FROM orders WHERE order_no = 20260801\G
```

```text
         type: ALL                     # ★★★★ 明明有 uk_order_no 唯一索引
possible_keys: uk_order_no
          key: NULL                    # ★★★★ 就是不用
         rows: 3118422
        Extra: Using where
```

```sql
SHOW WARNINGS;
```

```text
+---------+------+------------------------------------------------------------------+
| Level   | Code | Message                                                          |
+---------+------+------------------------------------------------------------------+
| Warning | 1292 | Truncated incorrect DOUBLE value: 'ORD-20260801-0001'             |
+---------+------+------------------------------------------------------------------+
```

**原因**：字串欄位跟數字比較時，MySQL 把**整欄字串都轉成數字**再比。
`'ORD-20260801-0001'` 轉成數字是 `0` —— 索引順序完全對不上，只能全表掃，
**而且結果通常是錯的**（所有以非數字開頭的訂單編號都變成 0，可能一次比中一堆）。

**改法：加引號就好。**

```sql
EXPLAIN SELECT id, amount FROM orders WHERE order_no = 'ORD-20260801-0001'\G
```

```text
         type: const                   # ★ 最好的 type
possible_keys: uk_order_no
          key: uk_order_no
      key_len: 130
         rows: 1
        Extra: NULL
```

> [!note] ★★★★ 反過來是安全的，方向很重要
> ```text
> VARCHAR 欄位 = 數字字面值   → ❌ 整欄轉數字，索引失效
> INT 欄位     = '5'（字串）  → ✅ 把字面值轉成數字，索引照用
> ```
> 所以「`WHERE id = '5'` 會不會有問題？」的答案是**不會**。
> 會出事的永遠是**字串欄位被拿去跟數字比**。
> 同樣的陷阱也發生在 **JOIN 兩表的欄位字元集/collation 不一致**時
> （`utf8mb4_general_ci` JOIN `utf8mb4_0900_ai_ci`）—— `Extra` 會出現
> `Using join buffer`，索引一樣用不到，要用 `ALTER TABLE … CONVERT TO` 統一。

**（三）複合索引不符最左前綴**

先建一個複合索引：

```sql
ALTER TABLE orders ADD INDEX idx_user_status_created (user_id, status, created_at);
```

```text
Query OK, 0 rows affected (18.42 sec)
Records: 0  Duplicates: 0  Warnings: 0
```

複合索引可以想成一本**依「使用者 → 狀態 → 時間」三層排序的電話簿**：

```text
idx_user_status_created (user_id, status, created_at)
   ├ user_id=1 ─┬ status='paid'      ─┬ 2026-08-01 09:15
   │            │                     └ 2026-08-01 14:40
   │            └ status='pending'    ─ 2026-08-27 22:10
   ├ user_id=2 …
   ★★★★ 你可以「從第一層開始連續往下查」，不能「跳過第一層」
```

| 查詢條件 | 用到幾欄 | `key_len` | ★ |
| --- | --- | --- | --- |
| `WHERE user_id=5` | 1 欄 | 9 | ★ 可用 |
| `WHERE user_id=5 AND status='paid'` | 2 欄 | 75 | ★ 可用 |
| `WHERE user_id=5 AND status='paid' AND created_at>'…'` | 3 欄 | 80 | ★ 最佳 |
| ★★★★ `WHERE status='paid'` | **0 欄** | — | **索引失效** |
| ★★★ `WHERE user_id=5 AND created_at>'…'` | **只有 1 欄** | 9 | 中間跳過 `status`，後面用不上 |
| ★★★ `WHERE user_id>3 AND status='paid'` | **只有 1 欄** | 9 | 第一欄是**範圍**，後面就停了 |

驗證「跳過第一欄」：

```sql
EXPLAIN SELECT id FROM orders WHERE status = 'paid'\G
```

```text
         type: ALL                     # ★★★★ 有 idx_user_status_created 也沒用
possible_keys: NULL
          key: NULL
         rows: 3118422
```

驗證「中間跳一欄」：

```sql
EXPLAIN SELECT id FROM orders
WHERE user_id = 5 AND created_at > '2026-08-01'\G
```

```text
         type: ref
          key: idx_user_status_created
      key_len: 9                       # ★★★ 只有 9（= user_id 一欄），created_at 沒用上
         rows: 41220
        Extra: Using where; Using index
```

★★★ **`key_len` 是唯一能看出「複合索引用到第幾欄」的欄位。**
預期 80 卻只有 9，就知道索引順序設計不對，該調整欄位順序或另建索引。

`key_len` 怎麼算（utf8mb4）：

```text
BIGINT UNSIGNED NULL   = 8 + 1(NULL 旗標)              = 9
VARCHAR(16) NOT NULL   = 16 × 4(utf8mb4) + 2(長度前綴) = 66
DATETIME NOT NULL      = 5
                                        累計：9 / 75 / 80
```

**索引設計原則（複合索引的欄位順序）**

| ★ | 原則 | 說明 |
| --- | --- | --- |
| ★★★★ | **等值條件的欄位放前面，範圍條件放最後** | 範圍條件後面的欄位用不到 |
| ★★★ | **選擇性高（不重複值多）的放前面** | `user_id` 比 `status` 好 |
| ★★★ | `ORDER BY` 的欄位可以接在後面 | 省掉 `Using filesort` |
| ★★★★ | **一張表的索引不要超過 5~6 個** | 每個索引都是寫入時的額外成本 |
| ★★★ | `(a, b)` 存在就不必再建 `(a)` | 用 `sys.schema_redundant_indexes` 找冗餘 |

```sql
SELECT * FROM sys.schema_redundant_indexes WHERE table_schema = 'appdb'\G
SELECT * FROM sys.schema_unused_indexes    WHERE object_schema = 'appdb';
```

★★★ `schema_unused_indexes` 要跑一段時間（至少一個完整的業務週期，含月結）才有意義，
**剛重啟的機器上看到的「未使用」全部不可信**。

### 結構檢視與盤點

**看一張表長什麼樣**

```sql
DESC users;
```

```text
+---------------+-----------------+------+-----+-------------------+-------------------+
| Field         | Type            | Null | Key | Default           | Extra             |
+---------------+-----------------+------+-----+-------------------+-------------------+
| id            | bigint unsigned | NO   | PRI | NULL              | auto_increment    |
| account       | varchar(64)     | NO   | UNI | NULL              |                   |
| name          | varchar(64)     | NO   |     | NULL              |                   |
| dept          | varchar(32)     | YES  | MUL | NULL              |                   |
| phone         | varchar(20)     | YES  |     | NULL              |                   |
| status        | tinyint         | NO   |     | 1                 |                   |
| last_login_at | datetime        | YES  |     | NULL              |                   |
| created_at    | datetime        | NO   |     | CURRENT_TIMESTAMP | DEFAULT_GENERATED |
+---------------+-----------------+------+-----+-------------------+-------------------+
```

★★★ `Key` 欄：`PRI`=主鍵、`UNI`=唯一索引、`MUL`=一般索引（可重複）。

**看完整定義（含索引、字元集、引擎）**

```sql
SHOW CREATE TABLE orders\G
```

```text
*************************** 1. row ***************************
       Table: orders
Create Table: CREATE TABLE `orders` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `order_no` varchar(32) NOT NULL,
  `user_id` bigint unsigned DEFAULT NULL,
  `amount` decimal(10,2) NOT NULL DEFAULT '0.00',
  `status` varchar(16) NOT NULL DEFAULT 'pending',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_order_no` (`order_no`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_created_at` (`created_at`),
  KEY `idx_user_status_created` (`user_id`,`status`,`created_at`)
) ENGINE=InnoDB AUTO_INCREMENT=3118423 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
```

★★★★ **改結構之前一定要先把這段存檔** —— 它就是回滾用的原始定義。

**看索引的選擇性**

```sql
SHOW INDEX FROM orders;
```

```text
+--------+------------+-------------------------+--------------+-------------+-------------+
| Table  | Non_unique | Key_name                | Seq_in_index | Column_name | Cardinality |
+--------+------------+-------------------------+--------------+-------------+-------------+
| orders |          0 | PRIMARY                 |            1 | id          |     3118422 |
| orders |          0 | uk_order_no             |            1 | order_no    |     3118422 |
| orders |          1 | idx_user_id             |            1 | user_id     |       75820 |
| orders |          1 | idx_created_at          |            1 | created_at  |     1622011 |
| orders |          1 | idx_user_status_created |            1 | user_id     |       75820 |
| orders |          1 | idx_user_status_created |            2 | status      |       78103 |
| orders |          1 | idx_user_status_created |            3 | created_at  |     3118422 |
+--------+------------+-------------------------+--------------+-------------+-------------+
```

| 欄位 | 判讀 | ★ |
| --- | --- | --- |
| `Cardinality` | 估計的**不重複值數量** | ★★★★ 相對總列數越接近 1 越好 |
| `Non_unique=0` | 唯一索引 | ★★ |
| `Seq_in_index` | 在複合索引裡的**第幾欄** | ★★★ 最左前綴看這個 |

★★★★ `Cardinality` 只有個位數（例如只有 `status` 四種值）的**單欄索引幾乎沒用** ——
掃索引再回表比直接全表掃還慢，優化器會直接忽略它。

**盤點：哪張表值得處理**

```sql
SET SESSION information_schema_stats_expiry = 0;   -- ★★★ 強制即時統計，不吃快取
SELECT table_name AS 資料表,
       table_rows AS 估計列數,
       ROUND(data_length/1024/1024, 1)  AS 資料MB,
       ROUND(index_length/1024/1024, 1) AS 索引MB,
       ROUND((data_length+index_length)/1024/1024, 1) AS 合計MB,
       ROUND(data_free/1024/1024, 1)    AS 可回收MB
FROM information_schema.tables
WHERE table_schema = 'appdb' AND table_type = 'BASE TABLE'
ORDER BY (data_length + index_length) DESC
LIMIT 10;
```

```text
+-----------+--------------+-----------+-----------+-----------+---------------+
| 資料表    | 估計列數     | 資料MB    | 索引MB    | 合計MB    | 可回收MB      |
+-----------+--------------+-----------+-----------+-----------+---------------+
| orders    |      3118422 |     412.0 |     198.5 |     610.5 |          22.0 |
| users     |         8203 |       1.5 |       0.4 |       1.9 |           0.0 |
+-----------+--------------+-----------+-----------+-----------+---------------+
```

> [!warning] ★★★ `table_rows` 對 InnoDB 是**估計值**
> 誤差 ±40% 都算正常，而且預設**快取 86400 秒**（`information_schema_stats_expiry`）。
> 要精確數字只能 `SELECT COUNT(*)`，但那在 312 萬列的表上要幾秒到幾十秒 ——
> **盤點用估計值就夠了，對帳才用 `COUNT(*)`。**

★★★ **索引大小超過資料大小的一半**（198.5 / 412.0 ≈ 48%）就要開始檢視是不是索引過多。

### ★★★ 正式環境的 DDL：`ALTER TABLE` 沒評估就下，等同計畫外停機

```sql
ALTER TABLE orders ADD INDEX idx_status (status);
```

在 312 萬列的表上，這一句可能跑 20 秒，也可能鎖住整張表 20 分鐘 —— 差別在演算法。

| `ALGORITHM` | 做什麼 | 耗時 | 期間能不能寫 | ★ |
| --- | --- | --- | --- | --- |
| `INSTANT` | ★ 只改 metadata（8.0.12+） | **毫秒** | ✅ 可以 | ★ 最好 |
| `INPLACE` | 就地重建索引，不複製整張表 | 分鐘級 | ✅ `LOCK=NONE` 時可以 | ★★ |
| `COPY` | ★★★★ **整張表複製一份再換掉** | **小時級** | ❌ **唯讀甚至完全鎖住** | ★★★★ 要避開 |

**★★★★ 正式機下 DDL 的固定流程**

**【1】先把原始定義存檔（回滾依據）**

```bash
mysql -u ops_ro appdb -e "SHOW CREATE TABLE orders\G" > /var/backups/ddl/orders.before.sql
```

**【2】先用 `ALGORITHM=INSTANT` 試，看它接不接受**

```sql
ALTER TABLE orders ADD INDEX idx_status (status), ALGORITHM=INSTANT;
```

```text
ERROR 1845 (0A000): ALGORITHM=INSTANT is not supported for this operation.
Try ALGORITHM=COPY/INPLACE.
```

★★★★ **這個錯誤是好消息**：MySQL 明確告訴你「這個操作做不到瞬間完成」，
而且**什麼都沒改**。加索引本來就不可能是 INSTANT，接著試 INPLACE。

**【3】用 `INPLACE` + `LOCK=NONE`，明確拒絕 COPY**

```sql
ALTER TABLE orders ADD INDEX idx_status (status), ALGORITHM=INPLACE, LOCK=NONE;
```

```text
Query OK, 0 rows affected (24.18 sec)
Records: 0  Duplicates: 0  Warnings: 0
```

> [!danger] ★★★★ `ALGORITHM=` 與 `LOCK=` 是**安全閥**，一定要明確寫出來
> 不寫的話 MySQL 會自己挑，某些操作（改欄位型別、改字元集、加全文索引）
> 會**默默降級成 `COPY`**，在 312 萬列的表上就是幾十分鐘的唯讀。
> **明確寫 `ALGORITHM=INPLACE, LOCK=NONE`：做不到時它會直接報錯而不是硬幹。**
> 報錯了才知道「這個操作必須排維護時段」。

**【4】`ALTER TABLE` 執行中怎麼觀察進度**

```sql
SELECT stage.event_name AS 階段,
       work_completed, work_estimated,
       ROUND(100 * work_completed / NULLIF(work_estimated,0), 1) AS 百分比
FROM performance_schema.events_stages_current stage
JOIN performance_schema.threads t USING (thread_id)
WHERE t.processlist_id = 4310;
```

```text
+----------------------------------------------+----------------+----------------+-----------+
| 階段                                         | work_completed | work_estimated | 百分比    |
+----------------------------------------------+----------------+----------------+-----------+
| stage/innodb/alter table (read PK and        |        1840000 |        3118422 |      59.0 |
| internal sort)                               |                |                |           |
+----------------------------------------------+----------------+----------------+-----------+
```

★★★ 需要 `performance_schema` 的 stage 事件已啟用（`setup_instruments` 裡的
`stage/innodb/alter%`），細節見 [[060-04-01-04-svc-MySQL-設定檔與調校]]。

**【5】回滾**

```sql
ALTER TABLE orders DROP INDEX idx_status, ALGORITHM=INPLACE, LOCK=NONE;
```

```text
Query OK, 0 rows affected (0.09 sec)      # ★★★ DROP INDEX 通常是秒級
```

★★★★ **加索引的回滾很便宜（DROP 很快），改欄位型別的回滾非常貴**（要再重建一次整張表）。
所以「加索引」可以在維護時段直接做，「改欄位型別」一定要先在複本演練並計時。

> [!tip] ★★★ 幾十分鐘的 DDL：`pt-online-schema-change`
> Percona Toolkit 的 `pt-online-schema-change` 用「建新表 + 觸發器同步 + 換名」的方式
> 做到幾乎不鎖表，代價是**磁碟要有一整份表的空間**、**期間寫入變慢**、
> **需要主鍵**、**和外鍵一起用要特別小心**。
> ```bash
> sudo apt install -y percona-toolkit
> pt-online-schema-change --alter "ADD INDEX idx_status (status)" \
>   D=appdb,t=orders --execute --dry-run
> ```
> ★★★★ **一定先 `--dry-run`**，確認沒問題再換 `--execute`。
> 有主從架構時還要加 `--max-lag`，避免把複寫延遲拉爆（見 [[060-04-01-06-svc-MySQL-主從複寫]]）。

### 資料匯出給機關報表

**（一）`mysql --batch` 產生 TSV —— ★★★ 最常用、限制最少**

```bash
mysql --batch --raw -u ops_ro appdb -e "
SELECT u.dept AS 部門, COUNT(*) AS 訂單數, SUM(o.amount) AS 總金額
FROM users u JOIN orders o ON o.user_id = u.id
GROUP BY u.dept ORDER BY 總金額 DESC;" > /var/reports/2026-08-orders.tsv
```

```bash
head -3 /var/reports/2026-08-orders.tsv
```

預期輸出：

```text
部門	訂單數	總金額
NULL	2	15099.00
資訊室	6	11190.50
```

| 旗標 | 作用 | ★ |
| --- | --- | --- |
| `--batch` / `-B` | ★★★ 用 **tab 分隔**、不畫框線 | ★★★ |
| `--raw` / `-r` | 不對特殊字元做 `\n` `\t` 跳脫 | ★★ 中文資料建議加 |
| `--skip-column-names` / `-N` | 不輸出標題列 | ★★ 要餵給後續腳本時用 |
| `--quick` | ★★★ **不把結果全部載入記憶體**，逐列輸出 | ★★★ 大匯出必加 |

轉成 Excel 吃得下的 CSV（★★★ 要 BOM，否則 Excel 開中文會亂碼）：

```bash
{ printf '\xEF\xBB\xBF'; \
  mysql --batch --raw --quick -u ops_ro appdb \
    -e "SELECT id,order_no,amount,status,created_at FROM orders WHERE created_at >= '2026-08-01' AND created_at < '2026-09-01';" \
  | sed 's/\t/,/g'; } > /var/reports/2026-08-orders.csv
```

★★★ 用 `sed` 換 tab 只在**資料本身不含逗號**時安全。
金額、狀態、日期沒問題，但**姓名、地址欄位一定要走真正的 CSV 產生器**
（例如把 SQL 結果丟給 `python3 -c` 用 `csv` 模組寫），否則欄位會錯位。

**（二）`SELECT … INTO OUTFILE` 與 `secure_file_priv`**

```sql
SELECT id, order_no, amount, status
INTO OUTFILE '/tmp/orders.csv'
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\n'
FROM orders WHERE created_at >= '2026-08-01';
```

```text
ERROR 1290 (HY000): The MySQL server is running with the --secure-file-priv option
so it cannot execute this statement
```

★★★★ **這是「為什麼常常寫不出去」的答案。** 先看允許的目錄：

```sql
SELECT @@secure_file_priv;
```

```text
+-----------------------+
| @@secure_file_priv    |
+-----------------------+
| /var/lib/mysql-files/ |
+-----------------------+
```

寫到允許的目錄就成功：

```sql
SELECT id, order_no, amount, status
INTO OUTFILE '/var/lib/mysql-files/orders-202608.csv'
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\n'
FROM orders WHERE created_at >= '2026-08-01' AND created_at < '2026-09-01';
```

```text
Query OK, 24118 rows affected (0.42 sec)
```

```bash
sudo ls -l /var/lib/mysql-files/orders-202608.csv
```

```text
-rw-rw-rw- 1 mysql mysql 1842019 Aug 28 15:02 /var/lib/mysql-files/orders-202608.csv
```

> [!danger] ★★★★★ `INTO OUTFILE` 產生的檔案是 `0666`，全機器的人都讀得到
> 上面 `-rw-rw-rw-` 不是筆誤 —— **MySQL 產生的匯出檔預設任何人可讀可寫**，
> 而且**擁有者是 `mysql`，你不能直接 `rm`**。
> 含個資的報表放在這裡，等同對同機所有帳號公開。
>
> **匯出含個資檔案的四條規矩：**
> ```bash
> # ★★★★ 1. 立刻搬到受控目錄並鎖權限
> sudo install -o report -g report -m 640 \
>      /var/lib/mysql-files/orders-202608.csv /var/reports/2026-08/
> sudo rm -f /var/lib/mysql-files/orders-202608.csv
>
> # ★★★★ 2. 要外送就先加密（不要用郵件夾帶明文）
> gpg --symmetric --cipher-algo AES256 /var/reports/2026-08/orders-202608.csv
>
> # ★★★ 3. 留下稽核紀錄：誰、什麼時候、匯了哪些欄位、給誰
> logger -t data-export "user=$USER rows=24118 dest=承辦-人事室 cols=id,order_no,amount,status"
>
> # ★★★ 4. 設保存期限，到期刪除
> sudo find /var/reports -type f -mtime +90 -delete
> ```
> 完整的個資與稽核要求見 [[060-04-01-07-svc-MySQL-安全強化]] 與 [[090-03-02-guide-應用安全-應用層安全]]。

| ★ | 兩種匯出方式怎麼選 | |
| --- | --- | --- |
| ★★★★ | **要給人的報表 → `mysql --batch`** | 檔案落在**你的權限**下，不經過 `mysql` 使用者，沒有 0666 問題 |
| ★★ | **要給資料庫再匯入的大檔 → `INTO OUTFILE`** | 速度較快，配合 `LOAD DATA INFILE` |
| ★★★★ | **備份 → 兩個都不對，用 `mysqldump`** | 見 [[060-04-01-05-svc-MySQL-備份與還原]] |

---

## 完整實戰範例

> **工單 #20260828-017**
> 「訂單查詢頁面原本 0.3 秒回應，這兩週變成 12 秒，使用者一直反映。
> 系統沒有改版，資料量從 210 萬成長到 312 萬。」
> 環境：Ubuntu 24.04 + MySQL 8.0.42 + PHP-FPM + Nginx（見 [[050-02-03-01-guide-範例-Nginx-PHP-MySQL]]）。

### 處理原則：★★★★ 一律在複本上分析，確認方案才回主庫執行

```text
db-prod-01（主庫）        db-replica-01（複本，read_only=ON）
   │                          │
   │ 只做：抓慢查詢日誌       │ 做全部的分析：EXPLAIN、試建索引、計時
   │ 最後：套用確認過的 DDL   │
```

### 【1】從慢查詢日誌撈出那一句

慢查詢日誌的開啟與 `pt-query-digest` 分析屬於 [[060-04-01-04-svc-MySQL-設定檔與調校]]，
這裡假設它已經開著，我們只是**使用結果**。

```bash
sudo tail -n 40 /var/log/mysql/mysql-slow.log
```

預期輸出：

```text
# Time: 2026-08-28T14:22:07.113402Z
# User@Host: app[app] @ web-01 [10.1.2.40]  Id: 88213
# Query_time: 12.418291  Lock_time: 0.000118  Rows_sent: 20  Rows_examined: 3118422
SET timestamp=1787059327;
SELECT o.id, o.order_no, o.amount, o.status, u.name
FROM orders o LEFT JOIN users u ON u.id = o.user_id
WHERE DATE(o.created_at) = '2026-08-28' AND o.status = 'paid'
ORDER BY o.created_at DESC LIMIT 20;
```

> [!note] ★★★★ 這三個數字就把問題講完了
> ```text
> Rows_sent:      20          ← 使用者只看到 20 列
> Rows_examined:  3118422     ← MySQL 卻讀了 311 萬列
> 比值 1 : 155921             ★★★★ 超過 1:1000 就是索引問題
> ```
> `Lock_time: 0.000118` 很小 → **不是鎖的問題，是掃描量的問題**。
> （如果 `Lock_time` 很大，那要走的是上面「交易與鎖」那條路。）

### 【2】在複本上 `EXPLAIN`

```bash
mysql -h db-replica-01 -u ops_ro appdb
```

```sql
EXPLAIN SELECT o.id, o.order_no, o.amount, o.status, u.name
FROM orders o LEFT JOIN users u ON u.id = o.user_id
WHERE DATE(o.created_at) = '2026-08-28' AND o.status = 'paid'
ORDER BY o.created_at DESC LIMIT 20\G
```

```text
*************************** 1. row ***************************
           id: 1
        table: o
         type: ALL                     # ★★★★ 全表掃
possible_keys: NULL                    # ★★★★ 一個候選索引都沒有
          key: NULL
         rows: 3118422
     filtered: 1.00                    # ★★★ 讀了 311 萬列只留下 1%
        Extra: Using where; Using filesort   # ★★★ 還要額外排序
*************************** 2. row ***************************
        table: u
         type: eq_ref
          key: PRIMARY
         rows: 1
```

**判讀**：

| 看到 | 代表 | ★ |
| --- | --- | --- |
| `type: ALL` + `possible_keys: NULL` | 條件寫法讓索引完全不可用 | ★★★★ |
| `filtered: 1.00` | 白讀 99% 的資料 | ★★★★ |
| `Using filesort` | 311 萬列還要排序 | ★★★ |
| 第 2 列 `eq_ref` | ★ JOIN `users` 沒問題，別去動它 | ★★ |

### 【3】找出根因

```sql
-- 條件一：DATE(o.created_at)  → ★★★★ 函式包住欄位，idx_created_at 用不到
-- 條件二：o.status = 'paid'   → 只有單欄索引的話選擇性太差（四種值）
-- 排序：  ORDER BY o.created_at DESC → 沒有可用的排序索引 → Using filesort
```

驗證假設：把函式拿掉單獨測一次。

```sql
EXPLAIN SELECT COUNT(*) FROM orders
WHERE created_at >= '2026-08-28' AND created_at < '2026-08-29'\G
```

```text
         type: range
          key: idx_created_at
         rows: 1842                    # ★★★★ 從 311 萬掉到 1842，根因確認
```

### 【4】設計改寫 + 索引

```sql
-- 改寫後的 SQL（交回開發）
SELECT o.id, o.order_no, o.amount, o.status, u.name
FROM orders o LEFT JOIN users u ON u.id = o.user_id
WHERE o.created_at >= '2026-08-28 00:00:00'
  AND o.created_at <  '2026-08-29 00:00:00'
  AND o.status = 'paid'
ORDER BY o.created_at DESC
LIMIT 20;
```

```sql
-- 建議的複合索引：等值條件在前、範圍兼排序在後
ALTER TABLE orders ADD INDEX idx_status_created (status, created_at);
```

★★★ 為什麼是 `(status, created_at)` 而不是 `(created_at, status)`：
`status` 是**等值**條件、`created_at` 是**範圍 + 排序**，
範圍條件後面的欄位用不到，所以範圍要放最後；而且 `created_at` 放在末端還能順便消掉
`Using filesort`。

### 【5】完整處理腳本

```bash
sudo tee /usr/local/bin/mysql-index-apply >/dev/null <<'EOF'
#!/usr/bin/env bash
# /usr/local/bin/mysql-index-apply
# 正式環境安全加索引：前置檢查 → 存檔 → 計時演練 → 套用 → 驗證 → 可回滾
# 用法： mysql-index-apply <db> <table> <index_name> "<欄位清單>"
# 例：   mysql-index-apply appdb orders idx_status_created "status, created_at"
set -euo pipefail

DB="${1:?用法: $0 <db> <table> <index_name> \"<cols>\"}"
TBL="${2:?缺少 table}"
IDX="${3:?缺少 index_name}"
COLS="${4:?缺少欄位清單}"

DEFAULTS="/etc/mysql/ops.cnf"          # ★★★★ 帳密只放這裡，chmod 600
BACKUP_DIR="/var/backups/ddl"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="/var/log/mysql-index-apply-${STAMP}.log"

mysql_q() { mysql --defaults-file="$DEFAULTS" -N -B "$DB" -e "$1"; }
say()     { printf '\n\033[1;36m═══ %s ═══\033[0m\n' "$*" | tee -a "$LOG"; }
die()     { printf '\033[1;31m✗ %s\033[0m\n' "$*" | tee -a "$LOG" >&2; exit 1; }
ok()      { printf '\033[1;32m✓ %s\033[0m\n' "$*" | tee -a "$LOG"; }

rollback() {
    say "回滾：移除 ${IDX}"
    mysql_q "ALTER TABLE \`${TBL}\` DROP INDEX \`${IDX}\`, ALGORITHM=INPLACE, LOCK=NONE;" \
        && ok "已移除 ${IDX}" || die "回滾失敗，請人工處理：ALTER TABLE ${TBL} DROP INDEX ${IDX};"
}
trap 'echo "★ 腳本異常中止（行 $LINENO）。若索引已建立，執行：mysql-index-apply-rollback" >&2' ERR

mkdir -p "$BACKUP_DIR"

# ── 【1】前置檢查 ───────────────────────────────────────────
say "【1】前置檢查"
[[ -r "$DEFAULTS" ]] || die "找不到 $DEFAULTS"
[[ "$(stat -c %a "$DEFAULTS")" == "600" ]] || die "$DEFAULTS 權限必須是 600（現在是 $(stat -c %a "$DEFAULTS")）"
command -v mysql >/dev/null || die "找不到 mysql client"

HOSTNAME_DB="$(mysql_q "SELECT @@hostname;")"
READONLY="$(mysql_q "SELECT @@read_only;")"
VERSION="$(mysql_q "SELECT VERSION();")"
ok "連到 ${HOSTNAME_DB}（MySQL ${VERSION}, read_only=${READONLY}）"

# ★★★★ 防呆：確認操作對象。複本上不該執行 DDL（會被複寫覆蓋或造成不一致）
if [[ "$READONLY" == "1" ]]; then
    die "這台是唯讀複本（read_only=1），DDL 要在主庫執行。"
fi
read -r -p "確認要在【${HOSTNAME_DB}】的 ${DB}.${TBL} 上建立索引？輸入主機名確認： " CONFIRM
[[ "$CONFIRM" == "$HOSTNAME_DB" ]] || die "確認字串不符，已中止。"

# ── 【2】存檔原始定義（回滾依據）──────────────────────────
say "【2】存檔原始表定義"
mysql --defaults-file="$DEFAULTS" "$DB" -e "SHOW CREATE TABLE \`${TBL}\`\G" \
    > "${BACKUP_DIR}/${DB}.${TBL}.${STAMP}.before.sql"
ok "已存 ${BACKUP_DIR}/${DB}.${TBL}.${STAMP}.before.sql"

# 索引已存在就不要重複建立
EXISTS="$(mysql_q "SELECT COUNT(*) FROM information_schema.statistics
                   WHERE table_schema='${DB}' AND table_name='${TBL}' AND index_name='${IDX}';")"
[[ "$EXISTS" == "0" ]] || die "索引 ${IDX} 已存在，不重複建立。"

# ── 【3】評估規模與影響 ─────────────────────────────────────
say "【3】評估規模"
mysql --defaults-file="$DEFAULTS" "$DB" -e "
SET SESSION information_schema_stats_expiry = 0;
SELECT table_rows AS 估計列數,
       ROUND(data_length/1024/1024,1)  AS 資料MB,
       ROUND(index_length/1024/1024,1) AS 索引MB
FROM information_schema.tables
WHERE table_schema='${DB}' AND table_name='${TBL}';" | tee -a "$LOG"

ROWS="$(mysql_q "SELECT IFNULL(table_rows,0) FROM information_schema.tables
                 WHERE table_schema='${DB}' AND table_name='${TBL}';")"
# ★★★ 粗估：每百萬列約 8 秒（依磁碟而異，複本演練的數字才準）
EST=$(( ROWS / 1000000 * 8 + 5 ))
ok "估計耗時約 ${EST} 秒（僅供參考，以複本演練為準）"

if (( ROWS > 10000000 )); then
    echo "★★★★ 超過一千萬列：建議改用 pt-online-schema-change 並排維護時段。"
    read -r -p "仍要繼續？(yes/no) " GO; [[ "$GO" == "yes" ]] || die "已中止。"
fi

# ── 【4】檢查是否有長交易擋著（DDL 會卡在 metadata lock）─────
say "【4】檢查長交易"
LONG_TRX="$(mysql_q "SELECT COUNT(*) FROM information_schema.innodb_trx
                     WHERE TIMESTAMPDIFF(SECOND, trx_started, NOW()) > 60;")"
if [[ "$LONG_TRX" != "0" ]]; then
    mysql --defaults-file="$DEFAULTS" -e "
    SELECT trx_mysql_thread_id AS pid,
           TIMESTAMPDIFF(SECOND, trx_started, NOW()) AS 秒,
           trx_rows_modified AS 已改列數, LEFT(IFNULL(trx_query,'(idle)'),60) AS 查詢
    FROM information_schema.innodb_trx
    WHERE TIMESTAMPDIFF(SECOND, trx_started, NOW()) > 60;" | tee -a "$LOG"
    die "★★★★ 有 ${LONG_TRX} 個超過 60 秒的交易。DDL 會卡在 metadata lock 並【連帶擋住所有新查詢】，先處理它們。"
fi
ok "沒有長交易"

# ── 【5】套用 ───────────────────────────────────────────────
say "【5】建立索引"
SQL="ALTER TABLE \`${TBL}\` ADD INDEX \`${IDX}\` (${COLS}), ALGORITHM=INPLACE, LOCK=NONE;"
echo "$SQL" | tee -a "$LOG"
START=$(date +%s)
if ! mysql --defaults-file="$DEFAULTS" "$DB" -e "$SQL" 2>&1 | tee -a "$LOG"; then
    die "★★★★ ALTER 失敗。若訊息是『ALGORITHM=INPLACE is not supported』，代表這個操作只能走 COPY —— 請排維護時段或改用 pt-online-schema-change，不要拿掉 ALGORITHM 子句硬跑。"
fi
ELAPSED=$(( $(date +%s) - START ))
ok "完成，實際耗時 ${ELAPSED} 秒"

# ── 【6】驗證 ───────────────────────────────────────────────
say "【6】驗證"
mysql --defaults-file="$DEFAULTS" "$DB" -e "SHOW INDEX FROM \`${TBL}\` WHERE Key_name='${IDX}';" | tee -a "$LOG"

VERIFIED="$(mysql_q "SELECT COUNT(*) FROM information_schema.statistics
                     WHERE table_schema='${DB}' AND table_name='${TBL}' AND index_name='${IDX}';")"
[[ "$VERIFIED" != "0" ]] || die "索引沒有建立成功。"

mysql --defaults-file="$DEFAULTS" "$DB" -e "ANALYZE TABLE \`${TBL}\`;" | tee -a "$LOG"
ok "統計值已更新"

mysql --defaults-file="$DEFAULTS" "$DB" -e "
SET SESSION information_schema_stats_expiry = 0;
SELECT ROUND(index_length/1024/1024,1) AS 索引MB_事後
FROM information_schema.tables WHERE table_schema='${DB}' AND table_name='${TBL}';" | tee -a "$LOG"

cat <<TIP | tee -a "$LOG"

★★★ 接下來請自行執行：
  1. 對照 EXPLAIN：type 應該從 ALL 變成 range/ref
  2. 觀察 24 小時的寫入延遲（每個索引都是 INSERT/UPDATE 的額外成本）
  3. 若反而變慢，回滾：
     mysql --defaults-file=${DEFAULTS} ${DB} \\
       -e "ALTER TABLE ${TBL} DROP INDEX ${IDX}, ALGORITHM=INPLACE, LOCK=NONE;"
  日誌：${LOG}
TIP
ok "全部完成"
EOF
sudo chmod 755 /usr/local/bin/mysql-index-apply
```

建立設定檔：

```bash
sudo tee /etc/mysql/ops.cnf >/dev/null <<'EOF'
[client]
user     = ops_ddl
password = 這裡放密碼
host     = 127.0.0.1
port     = 3306
EOF
sudo chmod 600 /etc/mysql/ops.cnf
sudo chown root:root /etc/mysql/ops.cnf
```

執行：

```bash
sudo /usr/local/bin/mysql-index-apply appdb orders idx_status_created "status, created_at"
```

預期輸出：

```text
═══ 【1】前置檢查 ═══
✓ 連到 db-prod-01（MySQL 8.0.42-0ubuntu0.24.04.1, read_only=0）
確認要在【db-prod-01】的 appdb.orders 上建立索引？輸入主機名確認： db-prod-01
═══ 【2】存檔原始表定義 ═══
✓ 已存 /var/backups/ddl/appdb.orders.20260828-152210.before.sql
═══ 【3】評估規模 ═══
估計列數	資料MB	索引MB
3118422	412.0	198.5
✓ 估計耗時約 29 秒（僅供參考，以複本演練為準）
═══ 【4】檢查長交易 ═══
✓ 沒有長交易
═══ 【5】建立索引 ═══
ALTER TABLE `orders` ADD INDEX `idx_status_created` (status, created_at), ALGORITHM=INPLACE, LOCK=NONE;
✓ 完成，實際耗時 31 秒
═══ 【6】驗證 ═══
Table	Non_unique	Key_name	Seq_in_index	Column_name	Cardinality
orders	1	idx_status_created	1	status	4
orders	1	idx_status_created	2	created_at	3118422
Table	Op	Msg_type	Msg_text
appdb.orders	analyze	status	OK
✓ 統計值已更新
索引MB_事後
241.8
✓ 全部完成
```

### 【6】改寫後對照 `EXPLAIN`

```sql
EXPLAIN SELECT o.id, o.order_no, o.amount, o.status, u.name
FROM orders o LEFT JOIN users u ON u.id = o.user_id
WHERE o.created_at >= '2026-08-28 00:00:00'
  AND o.created_at <  '2026-08-29 00:00:00'
  AND o.status = 'paid'
ORDER BY o.created_at DESC LIMIT 20\G
```

```text
*************************** 1. row ***************************
        table: o
         type: range                   # ★★★★ ALL → range
possible_keys: idx_created_at,idx_status_created
          key: idx_status_created      # ★★★ 用到新索引
      key_len: 71
         rows: 1102
     filtered: 100.00                  # ★★★ 從 1.00 變 100.00，不再白讀
        Extra: Using index condition   # ★★★ Using filesort 消失了
```

```sql
EXPLAIN ANALYZE SELECT o.id, o.order_no, o.amount, o.status, u.name
FROM orders o LEFT JOIN users u ON u.id = o.user_id
WHERE o.created_at >= '2026-08-28 00:00:00'
  AND o.created_at <  '2026-08-29 00:00:00'
  AND o.status = 'paid'
ORDER BY o.created_at DESC LIMIT 20\G
```

```text
EXPLAIN: -> Limit: 20 row(s)  (actual time=0.118..0.194 rows=20 loops=1)
    -> Nested loop left join  (cost=498.2 rows=1102) (actual time=0.116..0.190 rows=20 loops=1)
        -> Index range scan on o using idx_status_created over
           (status='paid' AND '2026-08-28 00:00:00' <= created_at < '2026-08-29 00:00:00'),
           reverse  (actual time=0.089..0.131 rows=20 loops=1)
        -> Single-row index lookup on u using PRIMARY (id=o.user_id)
           (actual time=0.002..0.002 rows=1 loops=20)
```

★★★★ **`actual time` 0.194 毫秒 vs 原本 12.4 秒。**

### 【7】確認新索引對寫入的影響

```sql
SET SESSION information_schema_stats_expiry = 0;
SELECT table_name, ROUND(data_length/1024/1024,1) AS 資料MB,
       ROUND(index_length/1024/1024,1) AS 索引MB,
       ROUND(index_length/data_length*100,1) AS 索引佔比百分比
FROM information_schema.tables WHERE table_schema='appdb' AND table_name='orders';
```

```text
+------------+-----------+-----------+---------------------+
| table_name | 資料MB    | 索引MB    | 索引佔比百分比      |
+------------+-----------+-----------+---------------------+
| orders     |     412.0 |     241.8 |                58.7 |
+------------+-----------+-----------+---------------------+
```

觀察寫入延遲（跑 24 小時再比對）：

```bash
mysql --defaults-file=/etc/mysql/ops.cnf -e "
SELECT VARIABLE_NAME, VARIABLE_VALUE FROM performance_schema.global_status
WHERE VARIABLE_NAME IN ('Innodb_rows_inserted','Innodb_rows_updated','Handler_write');"
```

```text
+----------------------+----------------+
| VARIABLE_NAME        | VARIABLE_VALUE |
+----------------------+----------------+
| Handler_write        | 88214003       |
| Innodb_rows_inserted | 3118422        |
| Innodb_rows_updated  | 1240811        |
+----------------------+----------------+
```

★★★ 索引佔比從 48% 升到 58.7%，`orders` 表是「寫多讀多」，這個代價可以接受。
如果索引佔比超過 100%（索引比資料還大），就該回頭刪掉沒在用的索引。

### 【8】★★★ 加了索引反而更慢時怎麼退回去

| 症狀 | 判斷 | 動作 |
| --- | --- | --- |
| ★★★ 查詢沒變快，`key` 還是舊索引 | 優化器選錯 | 先 `ANALYZE TABLE`；仍舊選錯用 `FORCE INDEX(idx_status_created)` 驗證，**確認是選擇問題再考慮改索引設計** |
| ★★★★ 寫入 TPS 明顯下降 | 索引太多 | 立刻回滾新索引，改用改寫 SQL 的方案 |
| ★★★ 磁碟空間吃緊 | 索引 + 重建暫存 | 回滾，並清掉 `data_free` |

回滾（腳本結尾也印了這一行）：

```bash
mysql --defaults-file=/etc/mysql/ops.cnf appdb \
  -e "ALTER TABLE orders DROP INDEX idx_status_created, ALGORITHM=INPLACE, LOCK=NONE;"
```

```text
（無輸出即成功）
```

```bash
mysql --defaults-file=/etc/mysql/ops.cnf appdb \
  -e "SHOW INDEX FROM orders WHERE Key_name='idx_status_created';"
```

```text
（無輸出 = 索引已移除）        # ★★★ 確認回滾成功
```

### 驗收檢查表

| # | 檢查項 | 指令 | 預期結果 | ★ |
| --- | --- | --- | --- | --- |
| 1 | 原始表定義已存檔 | `ls -l /var/backups/ddl/appdb.orders.*.before.sql` | 檔案存在且非空 | ★★★★ |
| 2 | 索引已建立 | `SHOW INDEX FROM orders WHERE Key_name='idx_status_created'` | 回傳 2 列（兩個欄位） | ★★★★ |
| 3 | `type` 不再是 `ALL` | `EXPLAIN <改寫後的 SQL>\G` | `type: range` | ★★★★ |
| 4 | `filtered` 接近 100 | 同上 | `filtered: 100.00` | ★★★ |
| 5 | `Using filesort` 消失 | 同上 | `Extra` 不含 filesort | ★★★ |
| 6 | 實際耗時 < 100ms | `EXPLAIN ANALYZE <SQL>\G` | `actual time` < 100 | ★★★★ |
| 7 | 慢查詢日誌不再出現這句 | `sudo grep -c 'DATE(o.created_at)' /var/log/mysql/mysql-slow.log` | 24 小時後數字不再增加 | ★★★★ |
| 8 | 索引佔比合理 | `information_schema.tables` 查詢 | `index_length < data_length` | ★★★ |
| 9 | 主從延遲沒有拉大 | `SHOW REPLICA STATUS\G` on 複本 | `Seconds_Behind_Source: 0` | ★★★★ |
| 10 | 統計值已更新 | `ANALYZE TABLE orders` | `Msg_text: OK` | ★★ |
| 11 | 回滾指令有記錄在工單 | 人工檢查 | 工單附 `DROP INDEX` 指令 | ★★★★ |
| 12 | 改寫後的 SQL 已交回開發 | 人工檢查 | 開發已改程式，不只靠索引撐 | ★★★ |

### 交回開發的「查詢優化紀錄」

```text
【查詢優化紀錄】工單 #20260828-017                   處理人：資訊室 / 2026-08-28

一、現象
   訂單查詢頁 12.4 秒（原 0.3 秒）。慢查詢日誌：
   Rows_sent=20  Rows_examined=3118422（比值 1:155921）

二、根因
   WHERE DATE(o.created_at) = '2026-08-28'
   → 函式包住索引欄位，idx_created_at 完全無法使用 → 全表掃描 311 萬列。
   次要：ORDER BY created_at 無索引可用，額外 Using filesort。

三、處理（已於 2026-08-28 15:22 完成，維護時段外，LOCK=NONE 未中斷服務）
   1. 新增索引 idx_status_created (status, created_at)   耗時 31 秒
   2. 建議 SQL 改寫（【需開發配合，尚未套用】）：
        WHERE o.created_at >= '2026-08-28 00:00:00'
          AND o.created_at <  '2026-08-29 00:00:00'
          AND o.status = 'paid'

四、效果
   EXPLAIN type:  ALL → range
   rows:          3118422 → 1102
   filtered:      1.00 → 100.00
   Extra:         Using where; Using filesort → Using index condition
   實測耗時:      12.418 秒 → 0.194 毫秒

五、後續
   ★★★★ 索引只是把傷害壓下來，SQL 沒改寫的話，日期一換到資料量更大的月份會再出問題。
   請開發於下次改版一併修正，並在程式碼審查加入規則：
   「WHERE 條件不得對索引欄位套用函式」。
   ★★★ 索引佔比由 48% 升至 58.7%，將持續觀察 7 天寫入延遲。
   回滾指令：ALTER TABLE orders DROP INDEX idx_status_created, ALGORITHM=INPLACE, LOCK=NONE;
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 執行 `UPDATE` 後 `Rows matched: 3118422`，整張表被改 | WHERE 漏寫、被終端機截斷，且 `autocommit=1` 立刻落地 | **立刻停止寫入**，依 [[060-04-01-05-svc-MySQL-備份與還原]] 做全備 + binlog 時間點還原。事前防：`--safe-updates` + `BEGIN` 包起來 |
| ★★★★ `ERROR 1055 … incompatible with sql_mode=only_full_group_by` | 舊系統（MariaDB / 5.x 設定）搬到 MySQL 8，SELECT 有非聚合欄位不在 GROUP BY | **改 SQL**：加聚合函式、補進 `GROUP BY`，或明確 `ANY_VALUE()`。★★★★ 不要改全域 `sql_mode` |
| ★★★★ `ERROR 1205 Lock wait timeout exceeded` | 有連線開了交易忘了 `COMMIT`，握著列鎖 | `SELECT * FROM sys.innodb_lock_waits\G` 找 `blocking_pid`（`blocking_query` 為 NULL 就是它），確認影響後 `KILL CONNECTION <pid>` |
| ★★★★ 查詢從 0.3 秒變 12 秒，程式沒改 | 資料量成長後索引失效（函式包欄位／型別轉換／不符最左前綴） | `EXPLAIN` 看 `type` 是不是 `ALL`、`key` 是不是 `NULL`，依「索引失效的三種寫法」改寫 |
| ★★★★ `ERROR 1290 … --secure-file-priv` | `INTO OUTFILE` 目標不在 `@@secure_file_priv` 允許的目錄 | 寫到 `/var/lib/mysql-files/`，或改用 `mysql --batch -e` 匯出（★★★★ 給人的報表建議一律用後者） |
| ★★★★ `ALTER TABLE` 下去之後全站卡住，連 `SELECT` 都不回 | DDL 卡在 metadata lock（有長交易擋著），後續所有查詢排在它後面 | `SHOW PROCESSLIST` 找 `Waiting for table metadata lock`；先 `KILL` 那個長交易；事前用腳本的【4】檢查 |
| ★★★★ `ALTER TABLE` 跑了 40 分鐘還沒完，磁碟暴增 | 沒寫 `ALGORITHM=`，MySQL 默默降級成 `COPY`，整張表複製一份 | 一律明確寫 `ALGORITHM=INPLACE, LOCK=NONE`；不支援時它會**報錯而不是硬幹**，這時改排維護時段或用 `pt-online-schema-change` |
| ★★★ `ERROR 1175 … safe update mode` | `--safe-updates` 生效，UPDATE/DELETE 的 WHERE 沒用到索引欄位 | 加上用到索引的條件或 `LIMIT n`。★★★ 真要全表更新才 `SET SESSION sql_safe_updates=0`，**並且一定要先 `BEGIN`** |
| ★★★ `SELECT` 結果永遠剛好 1000 筆 | `--safe-updates` 同時設了 `sql_select_limit=1000` | `SET SESSION sql_select_limit = DEFAULT;` 或明確寫 `LIMIT`。不要因此拿掉 `safe-updates` |
| ★★★ `LEFT JOIN` 的結果比預期少一大截 | `WHERE` 裡出現右表欄位條件，把 NULL 列濾掉，退化成 `INNER JOIN` | 條件搬進 `ON`；若刻意要找沒配對的列才用 `WHERE 右表.id IS NULL` |
| ★★★ 報表人數對不上，少了幾個人 | `COUNT(欄位)` / `COUNT(DISTINCT 欄位)` 不算 NULL；`!=` 也會漏掉 NULL | 總列數用 `COUNT(*)`；排除條件寫 `col != 'x' OR col IS NULL` 或 `NOT (col <=> 'x')` |
| ★★★ `NOT IN (子查詢)` 回傳空集合 | 子查詢結果含 `NULL`，比較變成 UNKNOWN | 改用 `NOT EXISTS`，或在子查詢加 `WHERE col IS NOT NULL` |
| ★★★ `ERROR 1213 Deadlock found` | 兩個交易以相反順序鎖同一批列 | `SHOW ENGINE INNODB STATUS\G` 抓 `LATEST DETECTED DEADLOCK` 段落交給開發；應用端要固定存取順序、縮短交易 |
| ★★★ 加了索引反而更慢 | 統計值過期讓優化器選錯索引，或索引選擇性太低（`Cardinality` 個位數） | 先 `ANALYZE TABLE`；用 `FORCE INDEX` 驗證是不是選擇問題；確定沒幫助就 `DROP INDEX` 退回 |
| ★★★ `ERROR 2013 Lost connection to MySQL server during query` | 大查詢超時被斷、被 `KILL`、或結果集超過 `max_allowed_packet` | 加 `LIMIT` 分批、加 `--quick` 逐列取回；確認不是被人 KILL（問一下） |
| ★★★ `ERROR 1064 … syntax error near` 但 SQL 明明是對的 | 多行 SQL 貼進終端機時被截斷 | ★★★★ 寫成檔案用 `source /path/x.sql` 執行，正式機不要貼多行 |
| ★★ `information_schema.tables` 的列數與實際差很多 | InnoDB 的 `table_rows` 是估計值，且統計快取 86400 秒 | `SET SESSION information_schema_stats_expiry = 0;` 取即時值；要精確就 `SELECT COUNT(*)` |
| ★★ 匯出的 CSV 用 Excel 開中文變亂碼 | 沒有 UTF-8 BOM | 匯出時先 `printf '\xEF\xBB\xBF'` 再接資料 |

### 排查步驟

情境：**使用者回報「系統很慢」，你只知道跟資料庫有關。**

**【1】先確認是「卡住」還是「慢」—— 這決定後面走哪條路**

```bash
mysql --defaults-file=/etc/mysql/ops.cnf -e "SHOW PROCESSLIST;" | head -20
```

預期輸出（情況 A）：

```text
Id     User    Host              db     Command  Time  State      Info
4127   ops_rw  10.1.2.30:51234   appdb  Sleep    1820             NULL
4210   app     10.1.2.40:44120   appdb  Query      47  updating   UPDATE orders …
4211   app     10.1.2.40:44121   appdb  Query      45  updating   UPDATE orders …
```

- **看到一堆 `updating` / `Waiting for …lock`，且有 `Sleep` 且 `Time` 很大的連線
  → 問題在鎖，跳到【2】。**
- **看到零星幾個 `Query` 且 `Time` 都在跑（`Sending data`、`Sorting result`）
  → 問題在查詢效率，跳到【4】。**
- **看到 `Command` 幾乎全是 `Sleep` 且數量逼近 `max_connections`
  → 是連線池問題，不是 SQL 問題，見 [[060-04-01-04-svc-MySQL-設定檔與調校]] 與 [[060-03-01-02-guide-PHP-FPM設定與Pool調校]]。**

**【2】鎖：找出誰擋住誰**

```bash
mysql --defaults-file=/etc/mysql/ops.cnf -e "
SELECT waiting_pid, blocking_pid, wait_age,
       LEFT(IFNULL(blocking_query,'(idle — 忘了 COMMIT)'),50) AS 元凶在做什麼
FROM sys.innodb_lock_waits;"
```

預期輸出：

```text
+-------------+--------------+----------+---------------------------------+
| waiting_pid | blocking_pid | wait_age | 元凶在做什麼                    |
+-------------+--------------+----------+---------------------------------+
|        4210 |         4127 | 00:00:47 | (idle — 忘了 COMMIT)            |
|        4211 |         4127 | 00:00:45 | (idle — 忘了 COMMIT)            |
+-------------+--------------+----------+---------------------------------+
```

- **`blocking_query` 是 `(idle)` → 有人開了交易忘了 COMMIT，跳到【3】。**
- **`blocking_query` 是一句真的在跑的大 UPDATE → 它不是忘記，是慢；
  先確認它改了幾列（`trx_rows_modified`）再決定要不要等它跑完。**

**【3】確認元凶身分再 KILL**

```bash
mysql --defaults-file=/etc/mysql/ops.cnf -e "
SELECT t.trx_mysql_thread_id AS pid, p.USER, p.HOST,
       TIMESTAMPDIFF(SECOND, t.trx_started, NOW()) AS 開了幾秒,
       t.trx_rows_locked AS 鎖了幾列, t.trx_rows_modified AS 改了幾列
FROM information_schema.innodb_trx t
JOIN performance_schema.processlist p ON p.ID = t.trx_mysql_thread_id;"
```

預期輸出：

```text
+------+--------+-----------------+--------------+--------------+--------------+
| pid  | USER   | HOST            | 開了幾秒     | 鎖了幾列     | 改了幾列     |
+------+--------+-----------------+--------------+--------------+--------------+
| 4127 | ops_rw | 10.1.2.30:51234 |         1820 |            1 |            1 |
+------+--------+-----------------+--------------+--------------+--------------+
```

- **`USER` 是人用的維運帳號、`改了幾列` 很小 → ★★★ 放心 `KILL CONNECTION 4127`。**
- **`USER` 是應用帳號、`改了幾列` 上萬 → ★★★★ 先找到人。KILL 之後的回滾可能比執行更久。**

```bash
mysql --defaults-file=/etc/mysql/ops.cnf -e "KILL CONNECTION 4127;"
mysql --defaults-file=/etc/mysql/ops.cnf -e "SELECT COUNT(*) AS 還在等的 FROM sys.innodb_lock_waits;"
```

```text
+-------------+
| 還在等的    |
+-------------+
|           0 |          # ★★★ 0 = 鎖已釋放，服務應該立刻恢復
+-------------+
```

**【4】慢：找出是哪一句**

```bash
sudo awk '/^# Query_time/{qt=$3} /^SELECT|^UPDATE|^DELETE/{if(qt>2) print qt" | "$0}' \
  /var/log/mysql/mysql-slow.log | sort -rn | head -5
```

預期輸出：

```text
12.418291 | SELECT o.id, o.order_no, o.amount, o.status, u.name
 8.220114 | SELECT COUNT(*) FROM orders WHERE DATE(created_at) = '2026-08-27'
 3.011882 | UPDATE orders SET status='paid' WHERE order_no = 20260805
```

- **有明確的慢 SQL → 跳到【5】。**
- **慢查詢日誌是空的 → 它可能沒開，或者問題不在單句 SQL（而是連線數、磁碟 I/O），
  轉去 [[060-01-03-04-guide-監控-效能瓶頸排查方法論]]。**

**【5】在複本上 `EXPLAIN`，確認是不是索引問題**

```bash
mysql -h db-replica-01 -u ops_ro appdb -e "EXPLAIN <把那句貼進來>\G"
```

- **`type: ALL` 且 `key: NULL` → ★★★★ 索引失效，跳到【6】。**
- **`type: range` 但 `rows` 幾百萬 → 條件範圍太寬，要跟業務確認能不能縮。**
- **`Extra: Using temporary; Using filesort` 且 `rows` 大 → GROUP BY / ORDER BY 沒索引。**
- **`type` 都很漂亮但還是慢 → 不是 SQL 問題，看磁碟與 buffer pool（[[060-04-01-04-svc-MySQL-設定檔與調校]]）。**

**【6】對照三種索引失效寫法**

```bash
mysql -h db-replica-01 -u ops_ro appdb -e "SHOW CREATE TABLE orders\G" | grep KEY
```

```text
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_order_no` (`order_no`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_created_at` (`created_at`)
```

逐項對照 WHERE 條件：

```text
索引欄位被函式包住？   DATE(created_at)、UPPER(name)、LEFT(order_no,3)  → ★★★★ 是
字串欄位跟數字比？     order_no = 20260805（沒引號）                    → ★★★★ 是
複合索引跳過第一欄？   WHERE status='paid' 但索引是 (user_id, status)   → ★★★★ 是
```

**【7】在複本上驗證改寫方案**

```bash
mysql -h db-replica-01 -u ops_ro appdb -e "EXPLAIN ANALYZE <改寫後的 SQL>\G"
```

```text
EXPLAIN: -> Limit: 20 row(s)  (actual time=0.118..0.194 rows=20 loops=1)
```

- **`actual time` 降到毫秒級 → 方案有效，跳到【8】。**
- **改寫後仍然慢 → 需要新索引，在複本上先建、計時，確認後才回主庫。**

**【8】回主庫套用，並留下紀錄**

```bash
sudo /usr/local/bin/mysql-index-apply appdb orders idx_status_created "status, created_at"
```

- **★★★★ 主庫套用完務必檢查主從延遲**（見 [[060-04-01-06-svc-MySQL-主從複寫]]）：

```bash
mysql -h db-replica-01 -u ops_ro -e "SHOW REPLICA STATUS\G" | grep -E 'Seconds_Behind|Last_Err'
```

```text
      Seconds_Behind_Source: 0
                 Last_Errno: 0
                 Last_Error:
```

★★★★ `Seconds_Behind_Source` 持續增加 → 複本正在重放 DDL，**這段期間讀取複本的
報表功能會拿到舊資料**，要先通知使用單位。

---

## 安全性注意事項

> [!danger] ★★★★★ 這幾件事在正式機做下去就是資安事件
> **1. 密碼寫在指令列**
> ```bash
> mysql -u root -pP@ssw0rd appdb          # ❌
> ```
> 同機任何使用者一個 `ps -ef` 就看得到；`~/.bash_history` 也留著。
> 用 `~/.my.cnf`（`chmod 600`）或 `--defaults-file`，並確認 `ps` 掃不到密碼。
>
> **2. `SELECT *` 把個資整批撈到終端機**
> ```sql
> SELECT * FROM users;                    -- ❌ 姓名、電話、身分證欄位全上螢幕
> ```
> 螢幕內容會留在 tmux scrollback、SSH client 的日誌、你的截圖。
> **只列出真正需要的欄位**，含個資的欄位要有正當理由才查。
>
> **3. 沒有 WHERE 的 `UPDATE` / `DELETE`**
> 見前面的專段。**這是本篇最高風險的一行。**
>
> **4. `INTO OUTFILE` 產生的 0666 檔案含個資，放著不管**
> ```bash
> -rw-rw-rw- 1 mysql mysql 1842019 /var/lib/mysql-files/orders-202608.csv
> ```
> 同機所有帳號可讀。匯出後**立刻**搬走、鎖權限、刪原檔。
>
> **5. 為了讓舊 SQL 跑起來而全域關掉 `ONLY_FULL_GROUP_BY`**
> 統計報表的數字會變成不確定值。對機關而言，**送出去的公文附表可能是錯的，
> 而且事後無法重現**。

### 機關情境的具體要求

| 要求面向 | 本篇對應做法 | ★ |
| --- | --- | --- |
| **最小權限** | 查詢一律用 `ops_ro`（只有 `SELECT`），要改資料才切 `ops_rw`，DDL 另有 `ops_ddl`。見 [[060-04-01-02-cmd-MySQL-使用者與權限]] | ★★★★ |
| **稽核軌跡** | 改資料一律寫成 `.sql` 檔用 `source` 執行，檔案存 `/var/backups/ddl/` 並列入工單附件；匯出用 `logger` 記錄「誰、何時、哪些欄位、給誰」 | ★★★★ |
| **個資最小揭露** | 報表 SQL 只列必要欄位；電話、身分證等欄位需去識別化時用 `CONCAT(LEFT(phone,4),'****',RIGHT(phone,3))` | ★★★★ |
| **傳輸加密** | 遠端連線一律走 TLS：`mysql --ssl-mode=REQUIRED`；驗證 `SHOW STATUS LIKE 'Ssl_cipher';` 不為空。設定見 [[060-04-01-07-svc-MySQL-安全強化]] | ★★★★ |
| **備份可還原** | 動任何 `UPDATE`/`DELETE`/`ALTER` 之前確認**昨天的備份還原演練是通過的**。見 [[060-04-01-05-svc-MySQL-備份與還原]] 與 [[090-03-04-guide-應用安全-備份災難復原與入侵應變]] | ★★★★★ |
| **保存期限** | 匯出的報表檔設 90 天自動刪除，不要無限期堆在 `/var/reports` | ★★★ |

驗證連線真的加密：

```sql
SHOW STATUS LIKE 'Ssl_cipher';
```

```text
+---------------+------------------------+
| Variable_name | Value                  |
+---------------+------------------------+
| Ssl_cipher    | TLS_AES_256_GCM_SHA384 |
+---------------+------------------------+
```

★★★★ 這裡是空字串就代表**你的 SQL 與查回來的個資是明文走網路的**。

> [!warning] ★★★ 關於政府組態基準（TWGCB）
> 資料庫相關的組態要求（連線加密、帳號最小權限、稽核日誌保存、備份加密）
> 請以 **NICS 發布的當期基準文件為準**，動筆設定前到
> <https://www.nccst.nat.gov.tw/GCB> 確認你的 OS 與資料庫版本對應到哪一份、哪一版。
> **本手冊不引用未經核對的條號**，請以你機關實際適用的版本為準。
> 資安面的完整要求見 [[060-04-01-07-svc-MySQL-安全強化]] 與 [[090-05-01-guide-資安設備-資安全景圖與縱深防禦]]。

**SQL injection 不在本篇範圍** —— 那是應用層要用參數化查詢解決的問題，
見 [[090-03-02-guide-應用安全-應用層安全]] 與 [[070-03-04-guide-Laravel-Eloquent與資料庫]]。
但維運端要知道：**慢查詢日誌裡出現 `' OR 1=1` 這類字串，就是被打了**，
應依 [[090-03-04-guide-應用安全-備份災難復原與入侵應變]] 啟動應變。

---

## 速查表

### client 常用旗標

| 旗標 | 用途 | ★ |
| --- | --- | --- |
| `-u <user> -p` | ★★★★ 密碼**互動輸入**，不接在旗標後面 | ★★★★ |
| `--defaults-file=/etc/mysql/ops.cnf` | 腳本用，設定檔 `chmod 600` | ★★★★ |
| `-e "SQL"` | 一次性查詢，跑完就退出 | ★★★ |
| `--batch` / `-B` | tab 分隔輸出，給腳本或匯出用 | ★★★ |
| `-N` | 不輸出標題列 | ★★ |
| `--quick` | 逐列取回，不吃光記憶體 | ★★★ 大查詢必加 |
| `--safe-updates` | ★★★★ 擋掉沒有 WHERE 的 UPDATE/DELETE | ★★★★ |
| `--ssl-mode=REQUIRED` | 強制 TLS，沒加密就拒絕連線 | ★★★★ |
| `-h 127.0.0.1` vs `-h localhost` | TCP vs unix socket，**授權的主機字串不同** | ★★★ |

### client 內互動指令

| 指令 | 作用 | ★ |
| --- | --- | --- |
| `\G`（取代 `;`） | 直式輸出，寬表必備 | ★★★★ |
| `source /path/x.sql` | 執行 SQL 檔，★★★★ 取代貼多行 | ★★★★ |
| `pager less -SFX` / `nopager` | 開／關分頁器 | ★★★ |
| `prompt \u@\h [\d]>` | 改提示字元 | ★★★★ |
| `system <shell 指令>` | 不離開 client 執行 shell | ★★ |
| `tee /tmp/session.log` / `notee` | 把整段操作記下來（★★★ 稽核好用） | ★★★ |
| `\c` | 放棄目前正在輸入的那句 | ★★★ 打錯時按這個 |

### 危險程度分級

| 動作 | 危險度 | 必要護欄 |
| --- | --- | --- |
| `SELECT`（有 LIMIT） | ★ | 無 |
| `SELECT`（無 LIMIT，大表） | ★★★ | `--quick` + `LIMIT` |
| `EXPLAIN` / `SHOW` / `DESC` | ★ | 無（不會動資料） |
| `ANALYZE TABLE` | ★★ | 避開尖峰 |
| `UPDATE` / `DELETE`（有 WHERE，已驗列數） | ★★★ | `BEGIN` + `Rows matched` 確認 |
| ★★★★★ `UPDATE` / `DELETE`（無 WHERE） | ★★★★★ | `--safe-updates` 直接擋下 |
| `ALTER TABLE`（`INPLACE, LOCK=NONE`） | ★★★ | 存 `SHOW CREATE TABLE` + 檢查長交易 |
| ★★★★ `ALTER TABLE`（降級成 `COPY`） | ★★★★ | 維護時段 + 複本演練 |
| `OPTIMIZE TABLE` | ★★★★ | 等同重建整表，**維護時段** |
| `TRUNCATE TABLE` | ★★★★★ | **不可 ROLLBACK**，等同 DROP + CREATE |
| `DROP TABLE` / `DROP DATABASE` | ★★★★★ | 先備份、再備份、四眼原則 |

### `EXPLAIN` 判讀速查

| 看到 | 判斷 | 下一步 |
| --- | --- | --- |
| ★★★★ `type: ALL` + `key: NULL` | 沒走索引 | 檢查三種失效寫法 |
| ★★★ `type: index` | 掃整個索引 | 多半也要改 |
| ★★ `type: range` + `rows` 小 | 正常 | 收工 |
| ★ `type: const` / `eq_ref` | 最佳 | 收工 |
| ★★★ `rows` 遠大於實際回傳列數 | 白讀太多 | 加條件或加索引 |
| ★★★ `filtered` 很小（< 10） | 讀了一堆然後丟掉 | 索引欄位順序不對 |
| ★★★★ `Extra: Using temporary` | 建了暫存表 | GROUP BY / DISTINCT 沒索引 |
| ★★★ `Extra: Using filesort` | 額外排序 | `ORDER BY` 欄位補進索引尾端 |
| ★ `Extra: Using index` | 覆蓋索引 | ★ 最好的情況 |
| ★★★ `key_len` 比預期短 | 複合索引只用到前幾欄 | 檢查最左前綴 |

### NULL 行為速查

| 運算 | 結果 | ★ |
| --- | --- | --- |
| `col = NULL` | 永遠不成立 → 用 `IS NULL` | ★★★★ |
| `col != 'x'` | ★★★ **漏掉 NULL 列** | ★★★★ |
| `NOT IN (含 NULL 的集合)` | ★★★★ **回空集合** | ★★★★ |
| `COUNT(col)` | 不算 NULL | ★★★ |
| `COUNT(*)` | 算全部 | ★★★ |
| `SUM(col)` 全 NULL | 回 `NULL` 不是 `0` | ★★★ |
| `ORDER BY col ASC` | NULL 排**最前** | ★★ |
| `GROUP BY col` | NULL 自成**一組** | ★★★ |
| `a <=> b` | NULL 安全等號 | ★★ |

### 檔案與路徑（Ubuntu 主線）

| 路徑 | 內容 | ★ |
| --- | --- | --- |
| `~/.my.cnf` | 個人 client 設定（`prompt`、`safe-updates`），**600** | ★★★★ |
| `/etc/mysql/mysql.conf.d/mysqld.cnf` | 伺服器設定主檔 | ★★★ |
| `/var/lib/mysql-files/` | `secure_file_priv` 預設目錄，★★★★ 產出檔是 0666 | ★★★★ |
| `/var/log/mysql/mysql-slow.log` | 慢查詢日誌（見 [[060-04-01-04-svc-MySQL-設定檔與調校]]） | ★★★★ |
| `/var/log/mysql/error.log` | 錯誤日誌，1055 這類錯誤在這裡 | ★★★ |
| `/var/backups/ddl/` | ★★★★ 本篇約定：DDL 前的 `SHOW CREATE TABLE` 存這裡 | ★★★★ |

### 排查用的一行指令

| 目的 | 指令 | ★ |
| --- | --- | --- |
| 誰在跑什麼 | `SHOW PROCESSLIST;` | ★★★★ |
| 誰擋住誰 | `SELECT * FROM sys.innodb_lock_waits\G` | ★★★★ |
| 開太久的交易 | `SELECT * FROM information_schema.innodb_trx\G` | ★★★★ |
| 中止一句 | `KILL QUERY <pid>;` | ★★★ |
| 殺掉連線（含 ROLLBACK） | `KILL CONNECTION <pid>;` | ★★★★ |
| 最近一次死鎖 | `SHOW ENGINE INNODB STATUS\G` | ★★★ |
| 表的大小 | `information_schema.tables` 查詢 | ★★★ |
| 沒在用的索引 | `SELECT * FROM sys.schema_unused_indexes;` | ★★★ |
| 冗餘索引 | `SELECT * FROM sys.schema_redundant_indexes\G` | ★★★ |
| 更新統計值 | `ANALYZE TABLE <表>;` | ★★★ |

---

## 練習題

> [!question]- 練習 1：把 `~/.my.cnf` 設成「正式機不會下錯指令」的樣子
> **題目**：在一台你有權限的測試機上，設定 `~/.my.cnf`，讓它同時做到：
> ① 提示字元顯示 `使用者@主機 [PROD] [資料庫]`；
> ② 連線自動啟用 `safe-updates`；
> ③ 寬表輸出不折行；
> ④ 閒置 15 分鐘自動斷線。
> 然後驗證「沒有 WHERE 的 UPDATE」真的被擋下來。
>
> ---
> **參考解答**
>
> ```ini
> # ~/.my.cnf
> [client]
> user = ops_ro
> host = 127.0.0.1
>
> [mysql]
> prompt       = "\\u@\\h [PROD] [\\d]> "
> pager        = less -SFX
> safe-updates
> init-command = "SET SESSION wait_timeout=900, innodb_lock_wait_timeout=10"
> ```
>
> ```bash
> chmod 600 ~/.my.cnf
> mysql appdb
> ```
>
> ```text
> ops_ro@db-test-01 [PROD] [appdb]>
> ```
>
> 驗證（要用有寫入權限的帳號）：
>
> ```sql
> UPDATE orders SET status = 'x';
> ```
>
> ```text
> ERROR 1175 (HY000): You are using safe update mode and you tried to update a table
> without a WHERE that uses a KEY column.
> ```
>
> ★★★★ 三個檢查點：`chmod 600`（否則密碼給全機看）、`prompt` 裡的跳脫要寫成 `\\u`
> （設定檔會做一層跳脫）、`init-command` 要用雙引號包起來。
> ★★★ 順便驗證 `SELECT * FROM orders;` 是不是只回 1000 列 —— 那是 `sql_select_limit`。

> [!question]- 練習 2：安全地把一筆訂單狀態改掉，中途故意改錯再退回
> **題目**：把 `ORD-20260812-0005` 的狀態從 `pending` 改成 `cancelled`。
> 過程中**故意先下一句錯的 UPDATE**（條件寫成 `status='pending'`，會影響多列），
> 用 `Rows matched` 發現不對後 `ROLLBACK`，再用正確條件重做並 `COMMIT`。
> 寫下每一步的輸出。
>
> ---
> **參考解答**
>
> ```sql
> -- 【1】先驗列數
> SELECT COUNT(*) FROM orders WHERE order_no = 'ORD-20260812-0005';
> -- 1  ★★★★ 看到 1 才往下
>
> -- 【2】開交易
> BEGIN;
>
> -- 【3】故意下錯的那一句
> UPDATE orders SET status = 'cancelled' WHERE status = 'pending';
> ```
> ```text
> Query OK, 3 rows affected (0.00 sec)
> Rows matched: 3  Changed: 3  Warnings: 0     ★★★★ 預期 1 卻是 3 → 條件錯了
> ```
> ```sql
> -- 【4】退回
> ROLLBACK;
>
> -- 【5】確認真的退回了
> SELECT order_no, status FROM orders WHERE status = 'pending';
> ```
> ```text
> +-------------------+---------+
> | order_no          | status  |
> +-------------------+---------+
> | ORD-20260812-0005 | pending |
> | ORD-20260827-0009 | pending |
> | ORD-20260828-0010 | pending |
> +-------------------+---------+       ★★★ 三筆都回來了
> ```
> ```sql
> -- 【6】正確重做
> BEGIN;
> UPDATE orders SET status = 'cancelled' WHERE order_no = 'ORD-20260812-0005';
> -- Rows matched: 1  Changed: 1        ★★★★ 這次對了
> SELECT order_no, status FROM orders WHERE order_no = 'ORD-20260812-0005';
> COMMIT;
> ```
>
> ★★★★ 這題的重點不是 SQL 語法，是**建立「看 `Rows matched` 才決定 COMMIT」的肌肉記憶**。
> 如果第 3 步沒有 `BEGIN`，`autocommit=1` 下那 3 列已經改掉了，只能靠備份救。

> [!question]- 練習 3：重現三種索引失效並各自改寫
> **題目**：在 `orders` 上分別重現「函式包住欄位」「隱式型別轉換」「不符最左前綴」
> 三種索引失效，每一種都給出「改寫前 EXPLAIN → 改寫後 EXPLAIN」的 `type` 與 `key` 對照。
> 表太小看不出差異的話，先灌 10 萬列測試資料。
>
> ---
> **參考解答**
>
> 灌資料（遞迴 CTE，MySQL 8 才有）：
>
> ```sql
> SET SESSION cte_max_recursion_depth = 200000;
> INSERT INTO orders (order_no, user_id, amount, status, created_at)
> WITH RECURSIVE seq(n) AS (
>   SELECT 1 UNION ALL SELECT n+1 FROM seq WHERE n < 100000
> )
> SELECT CONCAT('ORD-BULK-', LPAD(n,7,'0')),
>        1 + (n % 8),
>        ROUND(RAND()*10000, 2),
>        ELT(1 + (n % 4), 'paid','pending','cancelled','refunded'),
>        DATE_ADD('2026-01-01', INTERVAL (n % 240) DAY)
> FROM seq;
> ANALYZE TABLE orders;         -- ★★★ 灌完一定要更新統計值
> ```
>
> **（一）函式包住欄位**
>
> | | SQL | `type` | `key` | `rows` |
> | --- | --- | --- | --- | --- |
> | 前 | `WHERE DATE(created_at)='2026-03-01'` | `ALL` | `NULL` | 99512 |
> | 後 | `WHERE created_at>='2026-03-01' AND created_at<'2026-03-02'` | `range` | `idx_created_at` | 418 |
>
> **（二）隱式型別轉換**
>
> | | SQL | `type` | `key` |
> | --- | --- | --- | --- |
> | 前 | `WHERE order_no = 20260801` | `ALL` | `NULL`（★★★ 附 Warning 1292） |
> | 後 | `WHERE order_no = 'ORD-BULK-0000001'` | `const` | `uk_order_no` |
>
> **（三）不符最左前綴**（索引 `(user_id, status, created_at)`）
>
> | | SQL | `type` | `key_len` |
> | --- | --- | --- | --- |
> | 前 | `WHERE status='paid'` | `ALL` | — |
> | 後 | `WHERE user_id=3 AND status='paid'` | `ref` | 75 |
>
> ★★★★ 三個都要用 `EXPLAIN … \G` 看，重點在 `type` 與 `key`，
> 不要只看「感覺有沒有比較快」（小表跑起來都很快，看不出差異）。
> ★★★ 做完記得把測試資料刪掉：`DELETE FROM orders WHERE order_no LIKE 'ORD-BULK-%';`
> —— 而且這一句在 `safe-updates` 下會被擋（`LIKE` 不算 key 條件），
> 要加 `LIMIT` 分批刪，或用 `WHERE id > <起始id>`。

---

## 小測驗

Q1. **在正式機的 `mysql` client 裡，`prompt` 為什麼比任何監控工具都重要**？

Q2. **`SELECT * FROM users WHERE dept = NULL;` 會發生什麼事？為什麼特別危險**？

Q3. **執行 `UPDATE` 後看到 `Rows matched: 3421  Changed: 3421`，但你預期是 1 —— 
    此時你已經下了 `BEGIN`。請寫出接下來的三個動作**。

Q4. **`--safe-updates` 除了擋 UPDATE/DELETE，還會連帶改哪兩個變數？各造成什麼副作用**？

Q5. **`SHOW PROCESSLIST` 看到 20 個 `Query` 卡在 `updating`，還有一個
    `Command=Sleep, Time=1820`。該 KILL 哪一個？為什麼**？

Q6. **下面這句為什麼列不出「沒下過單的使用者」？怎麼改**？
    ```sql
    SELECT u.name FROM users u LEFT JOIN orders o ON o.user_id=u.id WHERE o.status='paid';
    ```

Q7. **舊系統升級到 MySQL 8 後大量查詢報 `ERROR 1055`。
    為什麼「在 `my.cnf` 拿掉 `ONLY_FULL_GROUP_BY`」是錯的解法**？

Q8. **`EXPLAIN` 顯示 `type: ref, key: idx_user_status_created, key_len: 9`，
    而該索引是 `(user_id, status, created_at)`。這代表什麼**？

Q9. **`ALTER TABLE orders ADD INDEX idx_x (status);` 這一句，
    在正式機下之前必須先做哪四件事**？

Q10. **`SELECT … INTO OUTFILE '/var/lib/mysql-files/x.csv'` 成功後，
     為什麼「還沒做完」**？

> [!question]- 測驗答案
> **Q1.** 因為監控工具告訴你「機器怎麼了」，`prompt` 告訴你「**你現在在哪台機器上**」。
> 正式機最常見的事故不是指令寫錯，是**在正式機視窗下了測試機的指令** ——
> 同樣一句 `DELETE FROM orders;` 在測試機沒事，在正式機是資安事件。
> ```ini
> [mysql]
> prompt = "\\u@\\h [PROD] [\\d]> "
> ```
> ```text
> ops_ro@db-prod-01 [PROD] [appdb]>
> ```
> ★★★★ `\h` 帶出主機名、`\d` 帶出資料庫，加上手動的 `[PROD]` 標記。
> 成本 30 秒，避免的事故成本是幾天的還原作業。
> 詳見「`~/.my.cnf`：把提示字元改成不會下錯機器的樣子」。
>
> **Q2.** 它會回 `Empty set`，**不會報錯**。
> SQL 用三值邏輯：`NULL = NULL` 的結果是 `UNKNOWN` 而不是 TRUE，
> 而 `WHERE` 只接受 TRUE，所以永遠沒有列符合。
> ★★★★ 危險在於**它不報錯**，你會以為「資料庫裡沒有這種資料」，
> 但實際上蔡孟儒的 `dept` 就是 `NULL`。
> ```sql
> SELECT * FROM users WHERE dept IS NULL;      -- ✅ 正確寫法
> ```
> 同一個陷阱還有三個變形：`col != 'x'` 會**漏掉 NULL 列**、
> `NOT IN (含 NULL 的子查詢)` 會**回空集合**、`COUNT(col)` **不算 NULL**。
> 見「NULL 的三值邏輯」與速查表的 NULL 行為表。
>
> **Q3.** 三個動作，順序不能換：
> ```sql
> -- 【1】立刻 ROLLBACK，不要猶豫、不要先去查是哪 3421 列
> ROLLBACK;
>
> -- 【2】確認真的退回了
> SELECT COUNT(*) FROM orders WHERE status = 'cancelled';
>
> -- 【3】把原本的 WHERE 搬到 SELECT，找出條件為什麼抓到 3421 列
> SELECT COUNT(*) FROM orders WHERE <原本那個 WHERE>;
> ```
> ★★★★ 關鍵是**先 ROLLBACK 再調查**。交易開著的期間，那 3421 列全部被鎖住，
> 線上服務只要碰到其中任何一列就會卡 50 秒然後拿到 ERROR 1205。
> 「先查清楚再決定」的每一秒，前台都在壞。
> 見「改資料的安全流程」步驟【3】的 `Rows matched` 判讀表。
>
> **Q4.** 連線時 client 送出的其實是三個設定：
> ```sql
> SET sql_safe_updates=1, sql_select_limit=1000, max_join_size=1000000;
> ```
> ★★★ **`sql_select_limit=1000`**：沒寫 `LIMIT` 的 `SELECT` 只回 1000 列。
> 副作用是**你查「這個月訂單」看到 1000 筆，很容易誤以為就是 1000 筆**。
> ★★★ **`max_join_size=1000000`**：優化器估計要檢查超過 100 萬列組合的多表查詢直接報錯。
> 副作用是大表 JOIN 會被擋。
> 兩個都可以臨時覆蓋：`SET SESSION sql_select_limit = DEFAULT;`，
> ★★★★ 但**不要因為被擋一次就把 `safe-updates` 從 `~/.my.cnf` 拿掉** ——
> 它擋下的那一次，可能就是整張表被改掉的那一次。
>
> **Q5.** ★★★★ **KILL 那個 `Sleep, Time=1820` 的連線**，不是那 20 個卡住的。
> 那 20 個是受害者；`Sleep` 表示它現在沒在執行任何 SQL，但 `Time=1820` 表示
> 它**開著一個交易握著列鎖睡了 30 分鐘**（有人 `BEGIN` 之後忘了 `COMMIT`）。
> 確認流程：
> ```sql
> SELECT waiting_pid, blocking_pid, blocking_query FROM sys.innodb_lock_waits\G
> -- blocking_query 是 NULL 就是鐵證：它沒在做事，只是握著鎖
> ```
> ★★★★ 用 `KILL CONNECTION`（不是 `KILL QUERY`）—— 因為要讓它的交易自動 `ROLLBACK`
> 把鎖放掉；`KILL QUERY` 只中止當下那一句，交易還在。
> KILL 之前先看 `trx_rows_modified`：很小就放心殺，上萬列就要先找到人
> （回滾可能比執行還久）。見「交易與鎖」段。
>
> **Q6.** 因為 `WHERE o.status='paid'` 把 LEFT JOIN 產生的 NULL 列全濾掉了 ——
> 沒下單的人在結果集裡 `o.status` 是 `NULL`，`NULL = 'paid'` 是 UNKNOWN，
> ★★★★ **這句話已經退化成 `INNER JOIN`**，而且它本來就不是在找「沒下單的人」。
> 兩種需求兩種改法：
> ```sql
> -- ① 要「所有人 + 他們的 paid 訂單」→ 條件搬進 ON
> SELECT u.name, o.order_no FROM users u
> LEFT JOIN orders o ON o.user_id = u.id AND o.status = 'paid';
>
> -- ② 要「沒下過單的人」→ 濾左表配不到的列
> SELECT u.name FROM users u
> LEFT JOIN orders o ON o.user_id = u.id WHERE o.id IS NULL;
> ```
> ★★★ 三秒判斷法：看到 `LEFT JOIN` 而 `WHERE` 裡有右表欄位（且不是 `IS NULL`），
> 這句就已經是 INNER JOIN 了。見「LEFT JOIN 被 WHERE 退化」段。
>
> **Q7.** 因為關掉之後那些 SQL **不會報錯，但會回傳「同組中隨便一列」的值**。
> ```sql
> SELECT dept, name, COUNT(*) FROM users GROUP BY dept;
> -- 「資訊室」這組有 3 個 name，MySQL 隨便挑一個給你
> ```
> ★★★★ 對機關報表的意義是：**同一份統計，今天跑跟明天跑數字可能不一樣，而且沒有警告**。
> 送出去的公文附表可能是錯的，事後也無法重現。
> 正確做法是**改 SQL**：
> ```sql
> SELECT dept, MAX(name) AS 範例姓名, COUNT(*) AS 人數 FROM users GROUP BY dept;
> SELECT dept, status, COUNT(*) FROM users GROUP BY dept, status;      -- 或補進 GROUP BY
> ```
> 真的因時程壓力必須暫時關，**只在 session 層級（`SET SESSION sql_mode=''`）、
> 只給那支程式、並開票追蹤**，絕不寫進 `my.cnf` 全域生效。
>
> **Q8.** `key_len: 9` 代表**只用到複合索引的第一欄 `user_id`**
> （`BIGINT UNSIGNED` 8 bytes + 允許 NULL 的 1 byte = 9）。
> 完整用到三欄應該是 `9 + 66 + 5 = 80`。
> ```text
> user_id        BIGINT UNSIGNED NULL  = 8 + 1  =  9
> status         VARCHAR(16) NOT NULL  = 16×4+2 = 66   （utf8mb4 每字 4 bytes + 2 bytes 長度前綴）
> created_at     DATETIME NOT NULL     =           5
> ```
> ★★★★ 表示查詢的 WHERE **中間跳過了 `status`**（例如
> `WHERE user_id=5 AND created_at > '…'`），或第一欄用的是範圍條件 ——
> 兩種情況後面的欄位都用不上。
> `key_len` 是唯一能看出「複合索引用到第幾欄」的欄位，
> **不要只看 `key` 有值就以為索引生效了**。見「複合索引不符最左前綴」段。
>
> **Q9.** 四件事，一件都不能少：
> ```bash
> # 【1】存原始定義（這就是回滾依據）
> mysql -u ops_ro appdb -e "SHOW CREATE TABLE orders\G" > /var/backups/ddl/orders.before.sql
> ```
> ```sql
> -- 【2】確認這台是主庫不是複本（複本上做 DDL 會造成複寫不一致）
> SELECT @@hostname, @@read_only;
>
> -- 【3】確認沒有長交易 —— DDL 會卡在 metadata lock，
> --      而 ★★★★ 卡住的 DDL 會【連帶擋住所有後續查詢】，等同全站停擺
> SELECT trx_mysql_thread_id, TIMESTAMPDIFF(SECOND, trx_started, NOW())
> FROM information_schema.innodb_trx WHERE TIMESTAMPDIFF(SECOND, trx_started, NOW()) > 60;
>
> -- 【4】明確寫出演算法與鎖等級，讓它做不到時【報錯而不是硬幹】
> ALTER TABLE orders ADD INDEX idx_x (status), ALGORITHM=INPLACE, LOCK=NONE;
> ```
> ★★★★ 第 4 點最常被省略。不寫 `ALGORITHM=` 時，某些操作會**默默降級成 `COPY`** ——
> 312 萬列的表複製一份，幾十分鐘唯讀，等同計畫外停機。
> 另外還要先在複本上跑一次計時。見「正式環境的 DDL」段。
>
> **Q10.** 因為 ★★★★★ **`INTO OUTFILE` 產生的檔案權限是 `0666`，擁有者是 `mysql`**：
> ```text
> -rw-rw-rw- 1 mysql mysql 1842019 Aug 28 15:02 /var/lib/mysql-files/orders-202608.csv
> ```
> 同機**任何帳號都讀得到**，含個資的報表等於對全機公開；
> 而且你不是擁有者，`rm` 還會被拒絕。四個收尾動作：
> ```bash
> sudo install -o report -g report -m 640 /var/lib/mysql-files/orders-202608.csv /var/reports/2026-08/
> sudo rm -f /var/lib/mysql-files/orders-202608.csv        # ★★★★ 一定要刪原檔
> gpg --symmetric --cipher-algo AES256 /var/reports/2026-08/orders-202608.csv
> logger -t data-export "user=$USER rows=24118 dest=人事室 cols=id,order_no,amount"
> ```
> ★★★★ 更好的做法是**給人的報表根本不要用 `INTO OUTFILE`**，改用
> `mysql --batch --quick -e "…" > /var/reports/x.tsv` ——
> 檔案直接落在你的權限與 umask 下，沒有 0666 問題。見「資料匯出給機關報表」段。

---

## 延伸閱讀

- [[060-04-01-01-svc-MySQL-安裝與初始化]] — 本篇所有指令的前提：服務起得來、client 連得上
- [[060-04-01-02-cmd-MySQL-使用者與權限]] — 把 `ops_ro` / `ops_rw` / `ops_ddl` 三種帳號建起來，這是最小權限的實作
- [[060-04-01-04-svc-MySQL-設定檔與調校]] — ★★★★ 慢查詢日誌的開啟、`pt-query-digest` 分析、buffer pool 與連線數；本篇「使用」慢查詢的結果，「怎麼產生」在這一篇
- [[060-04-01-05-svc-MySQL-備份與還原]] — ★★★★★ 本篇每一次「敢按 Enter」的底氣都來自這裡的**還原演練**，沒演練過的備份等於沒有備份
- [[060-04-01-06-svc-MySQL-主從複寫]] — 本篇一再強調「在複本上分析」，複本怎麼建、延遲怎麼看在這裡
- [[060-04-01-07-svc-MySQL-安全強化]] — 連線加密、稽核日誌、備份加密與機關個資情境的完整要求
- [[070-03-04-guide-Laravel-Eloquent與資料庫]] — 開發端怎麼避免 N+1、怎麼寫參數化查詢；本篇找出的問題最終要在這裡修
- [[060-01-03-04-guide-監控-效能瓶頸排查方法論]] — 當 `EXPLAIN` 都很漂亮卻還是慢時，往上一層看 CPU / 記憶體 / 磁碟
- [[090-03-04-guide-應用安全-備份災難復原與入侵應變]] — 資料被誤刪或疑似遭入侵時的應變流程
- MySQL 8.0 官方手冊 — 最佳化與索引：<https://dev.mysql.com/doc/refman/8.0/en/optimization.html>
- MySQL 8.0 官方手冊 — `EXPLAIN` 輸出格式：<https://dev.mysql.com/doc/refman/8.0/en/explain-output.html>
- MySQL 8.0 官方手冊 — InnoDB 與 Online DDL：<https://dev.mysql.com/doc/refman/8.0/en/innodb-online-ddl.html>
- MySQL 8.0 官方手冊 — `mysql` client 使用技巧（含 `--safe-updates`）：<https://dev.mysql.com/doc/refman/8.0/en/mysql-tips.html>
