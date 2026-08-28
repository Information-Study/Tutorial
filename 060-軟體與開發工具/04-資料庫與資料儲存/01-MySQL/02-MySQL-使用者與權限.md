---
title: "MySQL 使用者與權限"
desc: "user@host 比對規則、最小權限帳號設計、ROLE、密碼生命週期與可交稽核的權限盤點"
aliases: [grant, user, privilege, CREATE USER, SHOW GRANTS, mysql.user, role, login-path]
tags: [群組/軟體與開發工具, 服務/mysql, 主題/權限]
category: 資料庫與資料儲存
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[01-MySQL-安裝與初始化]]", "[[09-使用者與群組管理]]"]
updated: 2026-08-28
---

# MySQL 使用者與權限

> [!abstract] 這篇你會學到
> - **★★★★ 徹底搞懂 `'u'@'localhost'` 與 `'u'@'127.0.0.1'` 是【兩個不同的帳號】** —— 這是「密碼明明對卻 Access denied」的頭號成因，也是 Laravel `.env` 的 `DB_HOST` 一改就全站掛掉的原因
> - 用 `SELECT user, host, plugin FROM mysql.user;` **一眼看出誰的 host 開了 `%`、誰還在用匿名帳號**
> - **設計出四組角色帳號（app / readonly / backup / repl）**，本章第 05、06 篇會直接沿用
> - 用 **MySQL 8 的 ROLE** 管理多系統環境，不再一個一個 `GRANT`
> - 用 `~/.my.cnf` 與 `mysql_config_editor` **讓密碼不出現在 `ps` 與 shell history**
> - 產出一份**可以直接交給稽核的權限盤點 CSV**（危險權限、空密碼、超過 90 天未改密碼）
> - **變更權限前先存回滾腳本**，改完立刻用該帳號實測讀與寫

## 前置知識

- [[01-MySQL-安裝與初始化]] —— 已經有一台跑起來的 MySQL，知道 `mysql_secure_installation` 做了什麼
- [[03-SQL基礎操作]] —— 會用 `SELECT` 與 `WHERE`（本篇的稽核查詢全是 SQL）
- [[09-使用者與群組管理]] —— Linux 的 user / group 觀念；MySQL 帳號跟 OS 帳號**完全無關**（除了 socket 認證那一個例外）
- [[02-密碼與帳號管理實務]] —— 機關的密碼原則與離職帳號清理流程

---

## 觀念說明

### ★★★★ MySQL 的「帳號」不是一個名字，是一對值

99% 的 MySQL 權限問題，根源都在這張圖：

```text
      MySQL 的帳號 = 使用者名稱 + 來源主機（兩欄合起來才是一個帳號）
      ┌────────────┬──────────────┐
      │    user    │     host     │   ← mysql.user 表的【複合主鍵】
      └────────────┴──────────────┘

  'appuser'@'localhost'    ← 走 unix socket：/var/run/mysqld/mysqld.sock
  'appuser'@'127.0.0.1'    ← 走 TCP：IPv4 loopback
  'appuser'@'::1'          ← 走 TCP：IPv6 loopback
  'appuser'@'10.0.1.25'    ← 走 TCP：指定 IP
  'appuser'@'10.0.1.%'     ← 走 TCP：整個網段
  'appuser'@'%'            ← 任何來源            ★★★★ 危險

  ★★★★ 上面是【六個完全獨立的帳號】
        各自有各自的密碼、各自的權限、各自的認證外掛。
        改了其中一個的密碼，另外五個完全不受影響。
```

在 mysql client 與 PHP 的世界裡，這條規則長這樣：

```text
  mysql -u appuser -p                    → host 部分是 localhost（走 socket）
  mysql -u appuser -p -h localhost       → 一樣走 socket             ★★★ 注意
  mysql -u appuser -p -h 127.0.0.1       → 走 TCP，比對 '...'@'127.0.0.1'
  mysql -u appuser -p --protocol=TCP     → 強制 TCP，即使 -h localhost

  Laravel .env:
    DB_HOST=localhost   → PDO 走 unix socket → 比對 'appuser'@'localhost'
    DB_HOST=127.0.0.1   → PDO 走 TCP        → 比對 'appuser'@'127.0.0.1'
  ★★★★ 這兩行的差別，等於換了一個帳號。
```

> [!danger] 這一點漏掉的後果
> 你在 staging 用 `DB_HOST=localhost` 測得好好的，上正式機把 `.env` 抄過去，
> 運維為了統一改成 `127.0.0.1`，網站立刻 500：
> `SQLSTATE[HY000] [1045] Access denied for user 'appuser'@'localhost'`。
> 密碼一個字都沒錯 —— 錯的是**那個帳號根本不存在**。
> 相關設定見 [[02-Laravel-Nginx與PHP-FPM設定]] 與 [[02-PHP-FPM設定與Pool調校]]。

### 帳號比對的優先順序

一個連線進來，MySQL 不是「找到符合的就用」，而是**在 `mysql.user` 排序後由上往下取第一個符合的**：

```text
  排序規則（實務上記這兩條就夠）：
    1. host 欄位【越精確的越前面】：
         具體 IP / 主機名  >  帶萬用字元的  >  '%'
         '10.0.1.25'  >  '10.0.1.%'  >  '10.0.%.%'  >  '%'
    2. host 相同時，user 欄位【非空的排在空字串前面】
         'appuser'  >  ''（匿名帳號）
       ★★★ 但 host 較精確的匿名帳號，會贏過 host 較鬆的具名帳號
```

這條規則會咬人的地方：

```text
  mysql.user 裡有兩筆：
    ''       @ 'localhost'    ← 殘存的匿名帳號（舊版安裝留下）
    'appuser'@ '%'            ← 你新建的應用帳號

  從本機執行 mysql -u appuser -p
    → host 部分是 'localhost'
    → 'localhost' 比 '%' 精確 → ★★★★ 先比對到【匿名帳號】
    → 匿名帳號密碼是空的 → 你輸入的密碼被判定錯誤
    → ERROR 1045 (28000): Access denied for user 'appuser'@'localhost'

  你會盯著密碼看半小時，然後懷疑人生。
```

### 權限的五層粒度

```text
  ┌─────────────────────────────────────────────────────────┐
  │ 全域    GRANT ... ON *.*        → mysql.user          │  ★★★★ 最危險
  │  ┌──────────────────────────────────────────────────┐  │
  │  │ 資料庫  GRANT ... ON app_db.*   → mysql.db        │  │  ★ 應用帳號的正確層級
  │  │  ┌───────────────────────────────────────────┐   │  │
  │  │  │ 表     ON app_db.orders  → tables_priv     │   │  │
  │  │  │  ┌────────────────────────────────────┐    │   │  │
  │  │  │  │ 欄位 ON app_db.staff(name,dept)     │    │   │  │  ★★ 個資遮蔽用
  │  │  │  │      → columns_priv                 │    │   │  │
  │  │  │  └────────────────────────────────────┘    │   │  │
  │  │  │ 常式   ON PROCEDURE app_db.p_stat          │   │  │
  │  │  │      → procs_priv                          │   │  │
  │  │  └───────────────────────────────────────────┘   │  │
  │  └──────────────────────────────────────────────────┘  │
  └─────────────────────────────────────────────────────────┘
        MySQL 8 另有【動態權限】：mysql.global_grants
        （BACKUP_ADMIN、REPLICATION_APPLIER、SYSTEM_VARIABLES_ADMIN…）
```

**授權時往下走一層，出事時的損失就小一個數量級。**

| 你給的權限 | 網頁被 SQL injection 打穿後，攻擊者能做什麼 | 星級 |
| --- | --- | --- |
| `ALL PRIVILEGES ON *.*` + `GRANT OPTION` | 讀寫**所有資料庫**、建新帳號、`FILE` 讀 `/etc/passwd`、寫 webshell | ★★★★★ |
| `ALL PRIVILEGES ON app_db.*` | 毀掉整個 app_db（`DROP DATABASE`），但碰不到其他系統 | ★★★★ |
| `SELECT,INSERT,UPDATE,DELETE ON app_db.*` | 竄改與竊取 app_db 資料，**但無法 DROP TABLE、無法讀檔** | ★★★ |
| `SELECT ON app_db.*` | 只能讀 | ★★ |

> [!note] 本篇的界線
> - **憑證與 `REQUIRE SSL` / `REQUIRE X509`**：只在角色設計時提一句，實作在 [[07-MySQL-安全強化]]
> - **`bind-address` 收斂、稽核日誌方案**：全部在 [[07-MySQL-安全強化]]
> - **backup 帳號怎麼跑備份**：在 [[05-MySQL-備份與還原]]
> - **repl 帳號怎麼建複寫**：在 [[06-MySQL-主從複寫]]
> - **`SELECT` / `JOIN` 語法本身**：在 [[03-SQL基礎操作]]

---

## 基礎操作

### 先看清楚現況：帳號盤點的第一條指令

```bash
sudo mysql -e "SELECT user, host, plugin, account_locked, password_expired FROM mysql.user ORDER BY user, host;"
```

預期輸出：

```text
+------------------+-----------+-----------------------+---------------+------------------+
| user             | host      | plugin                | account_locked| password_expired |
+------------------+-----------+-----------------------+---------------+------------------+
|                  | localhost | mysql_native_password | N             | N                |  # ★★★★ 匿名帳號，必須刪
| appuser          | %         | caching_sha2_password | N             | N                |  # ★★★★ host=% 危險
| debian-sys-maint | localhost | caching_sha2_password | N             | N                |  # ★ Debian/Ubuntu 維護帳號，勿刪
| mysql.infoschema | localhost | caching_sha2_password | Y             | N                |  # ★ 系統保留，鎖定是正常的
| mysql.session    | localhost | caching_sha2_password | Y             | N                |
| mysql.sys        | localhost | caching_sha2_password | Y             | N                |
| root             | %         | caching_sha2_password | N             | N                |  # ★★★★★ root 開 % ＝ 資料庫裸奔
| root             | localhost | auth_socket           | N             | N                |
+------------------+-----------+-----------------------+---------------+------------------+
```

**這張表要看四欄**：`host` 有沒有 `%`、`user` 有沒有空字串、`plugin` 是不是舊外掛、`account_locked` 該鎖的有沒有鎖。

### ★★★★ 診斷神器：`CURRENT_USER()` 與 `USER()`

被 Access denied 折磨時，第一個要跑的不是改密碼，是這一行：

```bash
mysql -u appuser -p -h 127.0.0.1 -e "SELECT USER() AS '你送出的', CURRENT_USER() AS '實際比對到的';"
```

預期輸出：

```text
+---------------------+------------------+
| 你送出的            | 實際比對到的     |
+---------------------+------------------+
| appuser@localhost   | appuser@%        |   # ★★★★ 兩者不同 → 你其實在用 'appuser'@'%' 這個帳號
+---------------------+------------------+
```

```text
  USER()          = 你「宣稱」的身分（連線端 IP 反解後的樣子）
  CURRENT_USER()  = MySQL 依比對規則「實際套用權限」的帳號   ★★★★

  兩者不同是常態，不是錯誤 —— 但你必須知道自己實際在哪個帳號底下。
  排錯時：SHOW GRANTS; 顯示的永遠是 CURRENT_USER() 的權限。
```

### 建立帳號：`CREATE USER`

```sql
-- ★ 明確指定認證外掛，不要靠預設值（不同版本預設不同）
CREATE USER 'appuser'@'localhost'
  IDENTIFIED WITH caching_sha2_password BY 'Ch4nge-Me-Now!2026';
```

預期輸出：

```text
Query OK, 0 rows affected (0.02 sec)
```

驗證（**每建一個帳號都要跑這兩行**）：

```bash
sudo mysql -e "SELECT user, host, plugin FROM mysql.user WHERE user='appuser';"
sudo mysql -e "SHOW GRANTS FOR 'appuser'@'localhost';"
```

預期輸出：

```text
+---------+-----------+-----------------------+
| user    | host      | plugin                |
+---------+-----------+-----------------------+
| appuser | localhost | caching_sha2_password |
+---------+-----------+-----------------------+

+-------------------------------------------------+
| Grants for appuser@localhost                    |
+-------------------------------------------------+
| GRANT USAGE ON *.* TO `appuser`@`localhost`     |   # ★ USAGE ＝【沒有任何權限】，只是能登入
+-------------------------------------------------+
```

> [!tip] `USAGE` 不是權限
> 看到 `GRANT USAGE ON *.*` 不要以為授權失敗。`USAGE` 是「帳號存在、可以登入、但什麼都不能做」的佔位權限。
> `REVOKE ALL` 之後剩下的也是它。**一個帳號如果只有 `USAGE`，代表授權那一步漏掉了。**

其他常用寫法：

```sql
-- 冪等：腳本裡一律加 IF NOT EXISTS，重跑不會炸
CREATE USER IF NOT EXISTS 'appuser'@'127.0.0.1' IDENTIFIED BY 'Ch4nge-Me-Now!2026';

-- ★★ 限制來源網段（比 % 好，但仍不如具體 IP）
CREATE USER 'appuser'@'10.0.1.%' IDENTIFIED BY 'Ch4nge-Me-Now!2026';

-- ★★★ 用 OS 帳號認證，完全沒有密碼可外洩（只能本機 socket）
CREATE USER 'deployer'@'localhost' IDENTIFIED WITH auth_socket;
```

`auth_socket` 的意思是：**Linux 上的 `deployer` 這個 OS 使用者**（且必須從本機 socket 連線）才登得進來，密碼欄是空的但不可用密碼登入。這是排程腳本最安全的做法之一，缺點是不能跨機器用。

### ★★★★ 認證外掛相容性 —— 舊系統遷移最會出事的一關

| 版本 | 預設認證外掛 | `mysql_native_password` 狀態 | 星級 |
| --- | --- | --- | --- |
| MySQL 5.7 | `mysql_native_password` | 預設值 | ★ |
| MySQL 8.0 | `caching_sha2_password` | 仍可用；8.0.34 起標示 deprecated（啟動時出現警告） | ★★★ |
| MySQL 8.4 LTS | `caching_sha2_password` | **預設關閉**，需 `mysql_native_password=ON` 才載入 | ★★★★ |
| MySQL 9.x | `caching_sha2_password` | **已移除**，無法再啟用 | ★★★★ |
| MariaDB 10.4+ | `mysql_native_password` / `unix_socket` | 原生支援；**不支援 `caching_sha2_password`** | ★★★★ |

典型症狀：

```text
  # 舊 PHP / 舊 GUI 工具連 MySQL 8：
  SQLSTATE[HY000] [2054] The server requested authentication method unknown to the client

  # MariaDB client 連 MySQL 8：
  ERROR 2059 (HY000): Authentication plugin 'caching_sha2_password' cannot be loaded

  # MySQL 8.4 上執行舊的 CREATE USER ... IDENTIFIED WITH mysql_native_password：
  ERROR 1524 (HY000): Plugin 'mysql_native_password' is not loaded
```

先確認你的版本與外掛實際狀態：

```bash
mysql -e "SELECT VERSION();"
mysql -e "SELECT PLUGIN_NAME, PLUGIN_STATUS FROM information_schema.plugins WHERE PLUGIN_NAME LIKE '%password%';"
```

預期輸出（MySQL 8.0，`mysql_native_password` 仍在）：

```text
+-----------+
| VERSION() |
+-----------+
| 8.0.42-0ubuntu0.24.04.1 |
+-----------+

+-----------------------+---------------+
| PLUGIN_NAME           | PLUGIN_STATUS |
+-----------------------+---------------+
| mysql_native_password | ACTIVE        |   # ★★★ ACTIVE 才能用它建帳號
| sha256_password       | ACTIVE        |
| caching_sha2_password | ACTIVE        |
+-----------------------+---------------+
```

> [!warning]- ★★★★ 退回 `mysql_native_password` 的做法與代價（請以你安裝的版本為準）
> **只有在無法升級用戶端驅動時才這樣做，而且要當成技術債排入汰換。**
>
> 單一帳號退回（在該外掛仍 ACTIVE 的版本上）：
> ```sql
> ALTER USER 'legacyapp'@'10.0.1.%'
>   IDENTIFIED WITH mysql_native_password BY 'Legacy-Pass!2026';
> ```
>
> MySQL 8.4 需要先在設定檔載入外掛（**改完要重啟，且未來升級 9.x 會失效**）：
> ```ini
> ; /etc/mysql/mysql.conf.d/mysqld.cnf
> [mysqld]
> mysql_native_password=ON
> ```
>
> ★★★ 伺服器端的「預設外掛」設定項在不同版本叫法不同（舊版 `default_authentication_plugin`，
> 較新版本改用 `authentication_policy`），**動手前請以你安裝版本的官方手冊為準**，
> 不要照抄網路上的舊設定，寫錯會導致 MySQL 起不來。改設定前先備份設定檔：
> ```bash
> sudo cp -a /etc/mysql/mysql.conf.d/mysqld.cnf /etc/mysql/mysql.conf.d/mysqld.cnf.$(date +%F)
> ```
> 相關設定檔說明見 [[04-MySQL-設定檔與調校]]。

> [!tip] 優先修用戶端，不要降伺服器
> - PHP：7.4 以後的 mysqlnd 對 `caching_sha2_password` 支援穩定；7.1 以前不支援。
>   若卡在舊 PHP，正解是升 PHP（見 [[02-PHP-FPM設定與Pool調校]]），不是降 MySQL 安全性。
> - `caching_sha2_password` 走 TCP 且**未加密**時，首次認證需要伺服器公鑰。
>   用戶端加 `--get-server-public-key`（或先建立 TLS 連線）即可，這不是 bug。

### GRANT 粒度階梯：實際操作

```sql
-- 【第 1 階】全域 —— ★★★★★ 應用帳號【永遠不要】用這一階
GRANT ALL PRIVILEGES ON *.* TO 'x'@'%' WITH GRANT OPTION;   -- 反面教材，不要執行

-- 【第 2 階】資料庫層 —— ★ 應用帳號的正確位置
GRANT SELECT, INSERT, UPDATE, DELETE ON `app_db`.* TO 'appuser'@'localhost';

-- 【第 3 階】表層 —— 報表帳號只需要看兩張表時
GRANT SELECT ON `app_db`.`orders` TO 'report'@'10.0.1.%';
GRANT SELECT ON `app_db`.`products` TO 'report'@'10.0.1.%';

-- 【第 4 階】欄位層 —— ★★★ 個資最小揭露：讓對方看得到姓名部門，看不到身分證號
GRANT SELECT (id, name, dept) ON `app_db`.`staff` TO 'report'@'10.0.1.%';

-- 【第 5 階】常式 —— 只准呼叫特定 stored procedure
GRANT EXECUTE ON PROCEDURE `app_db`.`p_monthly_stat` TO 'report'@'10.0.1.%';
```

驗證：

```bash
mysql -e "SHOW GRANTS FOR 'report'@'10.0.1.%';"
```

預期輸出：

```text
+---------------------------------------------------------------------------------+
| Grants for report@10.0.1.%                                                       |
+---------------------------------------------------------------------------------+
| GRANT USAGE ON *.* TO `report`@`10.0.1.%`                                        |
| GRANT SELECT ON `app_db`.`orders` TO `report`@`10.0.1.%`                          |
| GRANT SELECT ON `app_db`.`products` TO `report`@`10.0.1.%`                        |
| GRANT SELECT (`id`, `name`, `dept`) ON `app_db`.`staff` TO `report`@`10.0.1.%`    |
| GRANT EXECUTE ON PROCEDURE `app_db`.`p_monthly_stat` TO `report`@`10.0.1.%`       |
+---------------------------------------------------------------------------------+
```

### ★★★★ 應用帳號到底需要哪些權限

| 情境 | 需要的權限 | 說明 | 星級 |
| --- | --- | --- | --- |
| 只跑查詢與寫入（正常上線後） | `SELECT, INSERT, UPDATE, DELETE` | **99% 的 Web 應用日常只需要這四個** | ★★★★ |
| 需要跑 migration（Laravel `php artisan migrate`） | 上面四個 ＋ `CREATE, ALTER, INDEX, DROP, REFERENCES` | ★★★ 只在部署視窗開放，部署完收回 | ★★★ |
| 用到 `TRUNCATE` | 需要 `DROP` | `TRUNCATE` 被歸類在 DROP 權限 | ★★ |
| 用到暫存表 | `CREATE TEMPORARY TABLES` | 報表類常見 | ★★ |
| 用到 view | `CREATE VIEW, SHOW VIEW` | | ★ |
| 用到 trigger | `TRIGGER` | | ★ |
| 應用內建鎖表邏輯 | `LOCK TABLES` | 大多數 ORM 用不到 | ★ |
| Laravel queue / schedule | 同「只跑查詢與寫入」 | 見 [[03-Laravel-佇列排程與Supervisor]] | ★★ |

> [!danger] ★★★★★ 為什麼永遠不給 `ALL PRIVILEGES ON *.*` 與 `GRANT OPTION`
> ```text
> ALL PRIVILEGES ON *.* 包含：
>   FILE          → SELECT ... INTO OUTFILE '/var/www/html/shell.php'  ← 直接寫 webshell
>                 → LOAD_FILE('/etc/shadow')                            ← 讀系統檔
>   SUPER / 動態權限 → 關掉 binlog、改全域變數、砍別人的連線
>   CREATE USER   → 自己開一個 root 等級後門帳號
>   DROP          → DROP DATABASE 其他系統的資料庫
> GRANT OPTION  → 把上面全部再轉授給任何人   ★★★★★ 權限失控的起點
>
> 一個網頁程式的 SQL injection，配上這組權限 = 整台伺服器淪陷，不只是資料庫。
> ```

### 動手做一次：證明 localhost 與 127.0.0.1 是兩個帳號

**【實驗】** 建兩個同名不同 host 的帳號，給不同權限：

```sql
CREATE DATABASE IF NOT EXISTS demo_db CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE USER IF NOT EXISTS 'demo'@'localhost' IDENTIFIED BY 'Demo-Sock!2026';
CREATE USER IF NOT EXISTS 'demo'@'127.0.0.1' IDENTIFIED BY 'Demo-Tcp!2026';

GRANT SELECT, INSERT ON demo_db.* TO 'demo'@'localhost';
GRANT SELECT          ON demo_db.* TO 'demo'@'127.0.0.1';
```

```bash
# 走 socket：密碼要用 socket 那組
mysql -u demo -p'Demo-Sock!2026' -e "SELECT CURRENT_USER(); SHOW GRANTS;"
```

預期輸出：

```text
+----------------+
| CURRENT_USER() |
+----------------+
| demo@localhost |
+----------------+
| GRANT SELECT, INSERT ON `demo_db`.* TO `demo`@`localhost` |
```

```bash
# 走 TCP：同一組密碼會被拒絕
mysql -u demo -p'Demo-Sock!2026' -h 127.0.0.1 -e "SELECT 1;"
```

預期輸出：

```text
ERROR 1045 (28000): Access denied for user 'demo'@'localhost' (using password: YES)
# ★★★★ 注意訊息裡的 host 是 localhost —— 那是「反解後的來源」，不代表你比對到 localhost 帳號
```

```bash
# 用 TCP 那組密碼才會過，而且只有 SELECT
mysql -u demo -p'Demo-Tcp!2026' -h 127.0.0.1 -e "SELECT CURRENT_USER(); SHOW GRANTS;"
```

預期輸出：

```text
+----------------+
| CURRENT_USER() |
+----------------+
| demo@127.0.0.1 |
+----------------+
| GRANT SELECT ON `demo_db`.* TO `demo`@`127.0.0.1` |
```

實驗完記得清掉：

```sql
DROP USER 'demo'@'localhost', 'demo'@'127.0.0.1';
DROP DATABASE demo_db;
```

> [!tip] ★★★ 實務結論
> **在 `.env` / 設定檔裡固定用 `127.0.0.1`，並且只建 `'user'@'127.0.0.1'` 這一個帳號。**
> 理由：
> 1. 行為明確，不會因為 socket 檔位置變動而失效
> 2. 容器化（見 [[03-Vue-Docker部署]] 的同類情境）遷移時語意一致
> 3. 「只存在一個帳號」本身就消滅了比對優先順序的坑
>
> 若刻意選 socket（效能略好、不經 TCP stack），就**只建 `localhost` 那一個**，兩者不要並存。

### 清掉匿名帳號與多餘的 root

```bash
sudo mysql -e "SELECT user, host FROM mysql.user WHERE user='' OR (user='root' AND host<>'localhost');"
```

預期輸出（有問題的機器）：

```text
+------+-----------+
| user | host      |
+------+-----------+
|      | localhost |
| root | %         |
+------+-----------+
```

```sql
-- ★★★★ 匿名帳號一律刪
DROP USER IF EXISTS ''@'localhost';
DROP USER IF EXISTS ''@'%';

-- ★★★★★ root 只保留 localhost；遠端 root 一律移除
DROP USER IF EXISTS 'root'@'%';
```

驗證（**應該回傳 0 列**）：

```bash
sudo mysql -e "SELECT COUNT(*) AS 危險帳號數 FROM mysql.user WHERE user='' OR (user='root' AND host<>'localhost');"
```

```text
+----------------+
| 危險帳號數     |
+----------------+
|              0 |
+----------------+
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> # 服務名稱與設定檔
> sudo systemctl status mysqld          # Oracle MySQL 套件
> sudo systemctl status mariadb         # ★★★ RHEL 預設倉庫給的是 MariaDB，機關最常見
> /etc/my.cnf.d/                        # 設定檔目錄（不是 /etc/mysql/mysql.conf.d/）
> /var/lib/mysql/mysql.sock             # socket 路徑（Ubuntu 是 /var/run/mysqld/mysqld.sock）
>
> # ★★★ RHEL 系的 root 沒有 auth_socket，初次登入要用初始密碼
> sudo grep 'temporary password' /var/log/mysqld.log
>
> # SELinux：MySQL 要讀寫非預設目錄（例如另掛的資料碟）時
> sudo semanage fcontext -a -t mysqld_db_t "/data/mysql(/.*)?"
> sudo restorecon -Rv /data/mysql
> sudo ausearch -m avc -ts recent | grep mysqld
> ```
> ★★★★ **RHEL 系請務必先 `SELECT VERSION();` 確認你面對的是 MySQL 還是 MariaDB**，
> 兩者的權限語法有實質差異（見下方 MariaDB 對照）。

---

## 進階應用

### ★★★★ 四組角色帳號：一次設計完，本章其他篇直接沿用

```text
  ┌──────────┬────────────────────┬──────────────────┬────────────────────────┐
  │ 帳號      │ 用途                │ 來源 host        │ 誰會用到                │
  ├──────────┼────────────────────┼──────────────────┼────────────────────────┤
  │ app_*    │ 應用讀寫            │ 127.0.0.1 或內網  │ Laravel / PHP-FPM       │
  │ ro_*     │ 報表、稽核查詢       │ 內網網段          │ BI、稽核人員、監控        │
  │ backup   │ 邏輯與物理備份       │ localhost         │ 05-備份與還原            │
  │ repl     │ 主從複寫            │ 從機 IP（限內網）   │ 06-主從複寫              │
  └──────────┴────────────────────┴──────────────────┴────────────────────────┘
  ★★★★ 命名帶系統別（app_hr、app_doc、ro_hr…），出事時看連線數就知道是哪個系統。
```

#### 1) `app_hr` —— 應用讀寫帳號

```sql
CREATE USER IF NOT EXISTS 'app_hr'@'127.0.0.1'
  IDENTIFIED WITH caching_sha2_password BY 'REPLACE-WITH-GENERATED-PASSWORD'
  PASSWORD EXPIRE INTERVAL 180 DAY
  FAILED_LOGIN_ATTEMPTS 8 PASSWORD_LOCK_TIME 1;

-- ★★★★ 日常只給這四個
GRANT SELECT, INSERT, UPDATE, DELETE ON `hr_db`.* TO 'app_hr'@'127.0.0.1';
```

部署視窗要跑 migration 時**臨時**加上，跑完立刻收回：

```sql
-- 部署前
GRANT CREATE, ALTER, INDEX, DROP, REFERENCES ON `hr_db`.* TO 'app_hr'@'127.0.0.1';
-- 部署後（★★★ 這行常被忘記，要寫進部署腳本，見 [[06-部署自動化]]）
REVOKE CREATE, ALTER, INDEX, DROP, REFERENCES ON `hr_db`.* FROM 'app_hr'@'127.0.0.1';
```

驗證（用該帳號**實際連線**跑一次讀與寫）：

```bash
mysql -u app_hr -p -h 127.0.0.1 hr_db -e "SELECT 1 AS 讀測試;"
mysql -u app_hr -p -h 127.0.0.1 hr_db -e "CREATE TABLE _t(i INT);"
```

預期輸出：

```text
+----------+
| 讀測試   |
+----------+
|        1 |
+----------+

ERROR 1142 (42000): CREATE command denied to user 'app_hr'@'localhost' for table '_t'
# ★★★★ 看到這個錯誤代表【設定正確】—— 應用帳號本來就不該能建表
```

#### 2) `ro_hr` —— 唯讀報表與稽核帳號

```sql
CREATE USER IF NOT EXISTS 'ro_hr'@'10.0.1.%'
  IDENTIFIED WITH caching_sha2_password BY 'REPLACE-WITH-GENERATED-PASSWORD'
  PASSWORD EXPIRE INTERVAL 90 DAY;

GRANT SELECT ON `hr_db`.* TO 'ro_hr'@'10.0.1.%';

-- ★★★ 唯讀帳號一定要限流，避免一支報表 SQL 把正式庫拖垮
ALTER USER 'ro_hr'@'10.0.1.%' WITH MAX_USER_CONNECTIONS 5 MAX_QUERIES_PER_HOUR 20000;
```

驗證：

```bash
mysql -u ro_hr -p -h 10.0.1.10 hr_db -e "UPDATE staff SET dept='X' LIMIT 1;"
```

```text
ERROR 1142 (42000): UPDATE command denied to user 'ro_hr'@'10.0.1.20' for table 'staff'
# ★★ 寫入被擋 = 正確
```

> [!warning] ★★★ 唯讀帳號不等於「可以給廠商」
> `SELECT ON hr_db.*` 讀得到全部個資。要給外部人員時請降到**欄位層**：
> ```sql
> REVOKE SELECT ON `hr_db`.* FROM 'ro_vendor'@'10.0.9.%';
> GRANT SELECT (id, name, dept) ON `hr_db`.`staff` TO 'ro_vendor'@'10.0.9.%';
> ```
> 個資揭露範圍的判斷原則見 [[09-資安稽核與符合性檢核]]。

#### 3) `backup` —— 備份帳號（[[05-MySQL-備份與還原]] 會直接用）

```sql
CREATE USER IF NOT EXISTS 'backup'@'localhost'
  IDENTIFIED WITH caching_sha2_password BY 'REPLACE-WITH-GENERATED-PASSWORD';

-- ★★★★ 這一組是 mysqldump / mydumper 的最小集合，少一個就會在某種情境下失敗
GRANT SELECT, LOCK TABLES, RELOAD, PROCESS, REPLICATION CLIENT,
      SHOW VIEW, EVENT, TRIGGER
  ON *.* TO 'backup'@'localhost';
```

每個權限為什麼需要：

| 權限 | 沒有它會發生什麼 | 星級 |
| --- | --- | --- |
| `SELECT` | 什麼都 dump 不出來 | ★★★★ |
| `LOCK TABLES` | `--lock-tables`（MyISAM）失敗 | ★★★ |
| `RELOAD` | `--single-transaction --master-data` 需要 `FLUSH TABLES WITH READ LOCK`，會 `Access denied` | ★★★★ |
| `PROCESS` | 看不到其他連線；某些 InnoDB 資訊取不到 | ★★★ |
| `REPLICATION CLIENT` | 抓不到 binlog 位置／GTID，備份無法當複寫起點 | ★★★★ |
| `SHOW VIEW` | dump 出來的 view 定義是空的 | ★★★ |
| `EVENT` | `--events` 匯不出排程事件 | ★★ |
| `TRIGGER` | trigger 全部遺失，還原後資料邏輯壞掉 | ★★★★ |

> [!note] MySQL 8 的動態權限
> 若你使用 `mysqlbackup` / clone plugin 之類的物理備份，另需動態權限：
> ```sql
> GRANT BACKUP_ADMIN ON *.* TO 'backup'@'localhost';
> ```
> 動態權限存在 `mysql.global_grants`，不在 `mysql.user`，稽核查詢兩張表都要撈。

驗證：

```bash
sudo -u root mysqldump --login-path=backup --single-transaction --routines --triggers --events \
  --databases hr_db > /dev/null && echo "backup 帳號權限足夠"
```

預期輸出：

```text
backup 帳號權限足夠
```

若少 `RELOAD`，會看到：

```text
mysqldump: Couldn't execute 'FLUSH TABLES': Access denied; you need (at least one of)
the RELOAD privilege(s) for this operation (1227)
```

#### 4) `repl` —— 複寫帳號（[[06-MySQL-主從複寫]] 會直接用）

```sql
-- ★★★★ host 必須寫【從機的實際 IP】，絕對不要用 %
CREATE USER IF NOT EXISTS 'repl'@'10.0.1.31'
  IDENTIFIED WITH caching_sha2_password BY 'REPLACE-WITH-GENERATED-PASSWORD';

GRANT REPLICATION SLAVE ON *.* TO 'repl'@'10.0.1.31';
```

```text
  ★★★ repl 帳號只需要 REPLICATION SLAVE 一個權限。
     不需要 SELECT（複寫讀的是 binlog，不是資料表）
     不需要 SUPER
     多給的每一個權限，都是從機被入侵後橫向移動到主機的路。
  ★★★ 這組帳號之後要在 07 篇加上 REQUIRE SSL，複寫流量預設是明文的。
```

驗證：

```bash
mysql -u repl -p -h 10.0.1.30 -e "SHOW GRANTS;"
```

```text
+---------------------------------------------------+
| Grants for repl@10.0.1.31                          |
+---------------------------------------------------+
| GRANT REPLICATION SLAVE ON *.* TO `repl`@`10.0.1.31` |
+---------------------------------------------------+
```

### MySQL 8 的 ROLE：多系統環境的正解

一台機關的 DB 上跑八套系統、每套三個帳號 = 24 個帳號。逐一 `GRANT` 的問題不是麻煩，是**下次加一張表時你不知道要補哪 24 條**。

```sql
-- ★ 角色也是 user@host 結構，慣例用 '%' 並鎖定（角色不該能登入）
CREATE ROLE IF NOT EXISTS 'r_hr_rw', 'r_hr_ro', 'r_hr_migrate';

GRANT SELECT, INSERT, UPDATE, DELETE               ON `hr_db`.* TO 'r_hr_rw';
GRANT SELECT                                        ON `hr_db`.* TO 'r_hr_ro';
GRANT CREATE, ALTER, INDEX, DROP, REFERENCES        ON `hr_db`.* TO 'r_hr_migrate';

-- 帳號只掛角色，不直接 GRANT
GRANT 'r_hr_rw' TO 'app_hr'@'127.0.0.1';
GRANT 'r_hr_ro' TO 'ro_hr'@'10.0.1.%';

-- ★★★★ 這一步最常被漏掉：角色授予後【預設是未啟用】的
SET DEFAULT ROLE ALL TO 'app_hr'@'127.0.0.1', 'ro_hr'@'10.0.1.%';
```

漏掉 `SET DEFAULT ROLE` 的症狀：

```bash
mysql -u app_hr -p -h 127.0.0.1 -e "SELECT CURRENT_ROLE(); SHOW GRANTS;"
```

```text
+----------------+
| CURRENT_ROLE() |
+----------------+
| NONE           |          # ★★★★ NONE = 角色沒生效，帳號等於只有 USAGE
+----------------+
| GRANT USAGE ON *.* TO `app_hr`@`127.0.0.1`        |
| GRANT `r_hr_rw`@`%` TO `app_hr`@`127.0.0.1`       |   # 有授予，但沒啟用
```

看「某帳號實際擁有的全部權限」要加 `USING`：

```bash
mysql -e "SHOW GRANTS FOR 'app_hr'@'127.0.0.1' USING 'r_hr_rw';"
```

全域一次啟用（省掉每個帳號設 default role）：

```ini
; /etc/mysql/mysql.conf.d/mysqld.cnf
[mysqld]
activate_all_roles_on_login = ON      ; ★★★ 所有已授予的角色登入即生效
```

```bash
sudo systemctl restart mysql
mysql -e "SHOW VARIABLES LIKE 'activate_all_roles_on_login';"
```

```text
+-----------------------------+-------+
| Variable_name               | Value |
+-----------------------------+-------+
| activate_all_roles_on_login | ON    |
+-----------------------------+-------+
```

> [!warning] ★★★ `activate_all_roles_on_login = ON` 的副作用
> 「臨時授予 migrate 角色、平常不啟用」這種安全設計會失效 —— 授予即生效。
> 機關多系統環境**建議關閉此參數**，改用 `SET DEFAULT ROLE` 精確控制，
> 部署腳本裡用 `SET ROLE 'r_hr_migrate';` 在單一 session 內臨時提權。

> [!info]- ★★★★ MariaDB 的 ROLE 語法差異（RHEL 預設常是 MariaDB）
> ```sql
> -- MariaDB 的角色【沒有 host 部分】
> CREATE ROLE r_hr_rw;                       -- 不是 'r_hr_rw'@'%'
> GRANT SELECT, INSERT, UPDATE, DELETE ON hr_db.* TO r_hr_rw;
> GRANT r_hr_rw TO 'app_hr'@'127.0.0.1';
>
> -- ★★★★ MariaDB 的 SET DEFAULT ROLE 只能指定【一個】角色，沒有 ALL
> SET DEFAULT ROLE r_hr_rw FOR 'app_hr'@'127.0.0.1';
>
> -- ★★★ MariaDB 沒有 activate_all_roles_on_login 這個變數
> -- ★★★ MariaDB 10.4+ 帳號實際存在 mysql.global_priv，mysql.user 只是 view
> --      稽核腳本若要寫入 mysql.user 會失敗，一律改用 CREATE/ALTER/GRANT 語句
> ```
> 其他差異：MariaDB 不支援 `caching_sha2_password`；密碼過期政策與
> `FAILED_LOGIN_ATTEMPTS` 的支援程度依版本而異，**請以 `SELECT VERSION();` 對照官方文件**。

### 密碼與帳號生命週期

#### `validate_password` 元件

```sql
INSTALL COMPONENT 'file://component_validate_password';
```

```bash
mysql -e "SHOW VARIABLES LIKE 'validate_password%';"
```

預期輸出：

```text
+--------------------------------------+--------+
| Variable_name                        | Value  |
+--------------------------------------+--------+
| validate_password.check_user_name    | ON     |
| validate_password.dictionary_file    |        |
| validate_password.length             | 8      |
| validate_password.mixed_case_count   | 1      |
| validate_password.number_count       | 1      |
| validate_password.policy             | MEDIUM |
| validate_password.special_char_count | 1      |
+--------------------------------------+--------+
```

| 等級 | 實際檢查的規則 | 星級 |
| --- | --- | --- |
| `LOW` (0) | **只檢查長度**（預設 8） | ★ 不足以應付機關密碼原則 |
| `MEDIUM` (1，預設) | 長度 ＋ 至少 1 數字、1 大寫、1 小寫、1 特殊符號 | ★★★ |
| `STRONG` (2) | MEDIUM ＋ **長度 4 以上的子字串不得命中字典檔** | ★★★★ 需自備 `dictionary_file` |

機關常見設定（對應密碼原則 12 碼以上）：

```ini
; /etc/mysql/mysql.conf.d/mysqld.cnf
[mysqld]
validate_password.policy              = STRONG
validate_password.length              = 12
validate_password.number_count        = 1
validate_password.mixed_case_count    = 1
validate_password.special_char_count  = 1
validate_password.check_user_name     = ON        ; ★★★ 禁止密碼含帳號名
validate_password.dictionary_file     = /etc/mysql/weak-passwords.txt
```

驗證（**故意用弱密碼確認擋得住**）：

```bash
mysql -e "CREATE USER 'weaktest'@'localhost' IDENTIFIED BY 'password123';"
```

```text
ERROR 1819 (HY000): Your password does not satisfy the current policy requirements
# ★★★ 看到這行代表政策生效
```

#### 過期、鎖定、歷史

```sql
-- 密碼 90 天到期（機關常見）
ALTER USER 'ro_hr'@'10.0.1.%' PASSWORD EXPIRE INTERVAL 90 DAY;

-- ★★★ 暴力破解防護：連續 5 次錯密碼鎖 1 天
ALTER USER 'ro_hr'@'10.0.1.%' FAILED_LOGIN_ATTEMPTS 5 PASSWORD_LOCK_TIME 1;

-- 禁止重複使用最近 5 組密碼 / 365 天內用過的密碼
ALTER USER 'ro_hr'@'10.0.1.%' PASSWORD HISTORY 5 PASSWORD REUSE INTERVAL 365 DAY;

-- 改密碼時必須提供舊密碼
ALTER USER 'ro_hr'@'10.0.1.%' PASSWORD REQUIRE CURRENT;

-- 立刻要求下次登入改密碼（新進人員／重設後）
ALTER USER 'ro_hr'@'10.0.1.%' PASSWORD EXPIRE;

-- 離職／異動：先鎖不刪（保留稽核軌跡與 ownership）
ALTER USER 'ro_hr'@'10.0.1.%' ACCOUNT LOCK;

-- 誤鎖或觀察期滿後解鎖
ALTER USER 'ro_hr'@'10.0.1.%' ACCOUNT UNLOCK;
```

被鎖住時的錯誤訊息：

```text
ERROR 3955 (HY000): Access denied for user 'ro_hr'@'10.0.1.20'.
Account is blocked for 1 day(s) (1 day(s) remaining) due to 5 consecutive failed logins.
```

```text
ERROR 3118 (HY000): Access denied for user 'ro_hr'@'10.0.1.20'. Account is locked.
```

> [!tip] ★★★ 離職帳號的正確處理順序
> ```text
> 【1】ACCOUNT LOCK          ← 立即阻斷，可逆
> 【2】通知系統管理者確認無排程／應用在用（觀察 7~30 天）
> 【3】匯出 SHOW GRANTS 存檔（稽核佐證）
> 【4】DROP USER             ← 確認無影響後才刪
> ```
> 直接 `DROP USER` 的風險：某支半夜的排程腳本用著它，你要三天後才會發現。
> 帳號生命週期的機關規範見 [[02-密碼與帳號管理實務]]。

### ★★★ 密碼不要進 shell history 與 `ps` 輸出

```bash
# ★★★★★ 絕對不要這樣寫在腳本或 crontab 裡
mysqldump -u backup -p'S3cret!' hr_db > /backup/hr.sql
```

原因：

```bash
# 任何一個登入本機的使用者都看得到
ps -ef | grep mysqldump
```

```text
root  21874  21870  0 03:00 ?  00:00:00 mysqldump -u backup -pS3cret! hr_db
                                                            ^^^^^^^^^ ★★★★★ 明文密碼
```

```bash
grep -n 'mysql' ~/.bash_history | tail -3
```

```text
412:mysql -u root -pRootPass2026! -e "show databases;"     # ★★★★ 留在檔案裡
```

**做法一：`~/.my.cnf`（最通用）**

```bash
umask 077
cat > /root/.my.cnf <<'EOF'
[client]
user = backup
password = "S3cret-Backup!2026"

[mysqldump]
user = backup
password = "S3cret-Backup!2026"
EOF
chmod 600 /root/.my.cnf
ls -l /root/.my.cnf
```

預期輸出：

```text
-rw------- 1 root root 118 Aug 28 09:14 /root/.my.cnf
# ★★★★ 一定要是 600；644 等於把 DB 密碼公開給機器上每個帳號
```

```bash
mysql -e "SELECT CURRENT_USER();"   # 不必再打 -u -p
```

**做法二：`mysql_config_editor`（多組憑證時較清爽）**

```bash
mysql_config_editor set --login-path=backup --host=localhost --user=backup --password
# 互動式輸入密碼，不進 history
```

```bash
mysql_config_editor print --all
```

預期輸出：

```text
[backup]
user = backup
password = *****
host = localhost
```

```bash
mysqldump --login-path=backup --single-transaction hr_db > /backup/hr.sql
ps -ef | grep mysqldump
```

```text
root  22013  22009  0 03:00 ?  00:00:00 mysqldump --login-path=backup --single-transaction hr_db
# ★★★ 命令列上沒有密碼了
```

> [!danger] ★★★★ `mysql_config_editor` 的限制：這是【混淆】不是加密
> `~/.mylogin.cnf` **不是加密檔，只是混淆** —— 解密所需的金鑰就在檔案裡，
> 官方手冊明說「不足以嚇阻有心人」。它解決的是「密碼出現在 `ps` 與 history」，
> **不能**解決「有 root 或該帳號權限的人取得密碼」。
> 因此：
> - `~/.mylogin.cnf` 與 `~/.my.cnf` 都必須 `chmod 600`，且**只放在該用途的帳號家目錄**
> - 備份這台機器時要把它視為機密資料（見 [[03-機密管理與金鑰保護]]）
> - 真正的隔離手段是**降權**：讓那把憑證只能做備份，不能做別的

**為什麼 `MYSQL_PWD` 仍不理想**

```bash
export MYSQL_PWD='S3cret!'
mysqldump -u backup hr_db > /backup/hr.sql
```

```text
  看似安全（ps 的 args 欄看不到），但：
  ★★★ /proc/<pid>/environ 讀得到 —— 同 UID 的任何程序都可以
  ★★★ 子程序會繼承這個變數，範圍失控
  ★★★ 官方手冊明列為「不安全，不建議使用」
  → 排程腳本一律用 --login-path 或 --defaults-file，不要用 MYSQL_PWD。
```

**crontab 的正確寫法**

```bash
# /etc/cron.d/mysql-backup
# ★★★ 用 login-path，不出現任何密碼
0 3 * * * root /usr/bin/mysqldump --login-path=backup --single-transaction \
  --routines --triggers --events --databases hr_db | \
  gzip > /backup/hr_db-$(date +\%F).sql.gz
```

實際的備份策略、保留週期與**還原演練**在 [[05-MySQL-備份與還原]] 與 [[03-備份策略與還原演練]]。

### 撤銷與變更

```sql
-- 精確撤銷：REVOKE 的權限清單要跟 GRANT 時一致
REVOKE INSERT, UPDATE, DELETE ON `hr_db`.* FROM 'app_hr'@'127.0.0.1';

-- 全部撤銷（帳號仍在，剩 USAGE）
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'app_hr'@'127.0.0.1';

-- 撤銷角色
REVOKE 'r_hr_rw' FROM 'app_hr'@'127.0.0.1';

-- ★★★ 換來源 host（例如應用從 localhost 改走 TCP），不必重建帳號
RENAME USER 'app_hr'@'localhost' TO 'app_hr'@'127.0.0.1';

-- 刪除
DROP USER IF EXISTS 'app_hr'@'127.0.0.1';
```

> [!warning] ★★★ `RENAME USER` 保留權限，`DROP` + `CREATE` 不會
> `RENAME USER` 會把 `mysql.db`、`tables_priv`、`columns_priv` 裡的紀錄一起搬過去。
> 用 `DROP USER` 再 `CREATE USER`，權限**全部歸零**，而且你多半忘了先存 `SHOW GRANTS`。

#### 什麼時候真的需要 `FLUSH PRIVILEGES`

```text
  ★★★★ 用 CREATE USER / ALTER USER / GRANT / REVOKE / DROP USER
        → 【不需要】FLUSH PRIVILEGES，MySQL 會自動同步記憶體中的授權表

  ★★★★ 直接 UPDATE mysql.user / INSERT INTO mysql.db 這種改表的做法
        → 【必須】FLUSH PRIVILEGES，否則改了等於沒改
        → 但這種做法本身就【不建議】：MySQL 8 的密碼欄位格式與動態權限
          都不該手動改，改壞了帳號會直接登不進去

  結論：正常操作永遠用 SQL 語句，就永遠不需要 FLUSH PRIVILEGES。
        看到教學叫你 UPDATE mysql.user，那是 MySQL 5.x 時代的做法。
```

#### 誤刪帳號後應用全斷的快速復原

```text
  現象：DROP USER 之後，網站立刻 500，日誌狂噴 Access denied
  ★★★★★ 這是最需要「事前準備」的場景 —— 事後才想備份就來不及了
```

```bash
# 【前提】改權限前有跑過快照（下一節的腳本會自動產生）
ls -l /var/backups/mysql-grants/
```

```text
-rw------- 1 root root 4821 Aug 28 09:00 grants-2026-08-28T09-00-00.sql
```

```bash
# 復原：快照就是一份可直接執行的 SQL
sudo mysql < /var/backups/mysql-grants/grants-2026-08-28T09-00-00.sql
sudo mysql -e "SHOW GRANTS FOR 'app_hr'@'127.0.0.1';"
```

> [!danger] ★★★★★ 沒有快照時的最後手段：`--skip-grant-tables`
> ```bash
> sudo systemctl stop mysql
> sudo mysqld_safe --skip-grant-tables --skip-networking &
> ```
> 這段期間**任何人不需密碼就能以任意身分連進來**，所以：
> 1. 一定要加 `--skip-networking`（只開 socket）
> 2. 事前把該機器的 3306 在防火牆上關掉
> 3. 修完立刻 `systemctl restart mysql` 回到正常模式
> 4. 事後檢查 `SHOW GRANTS` 與稽核日誌，確認這段空窗沒有異常連線
>
> 這是**不得已**的作業，必須留下變更紀錄與主管核可。

### 權限變更的變更管理

```text
  改權限的四個步驟（★★★★ 缺一不可）：
  【1】改前快照：SHOW GRANTS → 存成 .sql，這就是你的回滾腳本
  【2】改動本身：用 SQL 語句，不改表；一次一個帳號
  【3】用【該帳號本人】實際連線，跑一次讀與一次寫
  【4】留紀錄：誰改的、為什麼改、核可單號 —— 稽核時會問
```

---

## 完整實戰範例

### 情境

> 你接手一套已上線三年的機關系統。開發廠商早就結案，現況是：
> **八個子系統的 `.env` 全部填 `DB_USERNAME=root`**，`root` 的 host 是 `%`，
> 密碼三年沒換，備份腳本的 crontab 裡有明文密碼。
> 下個月要資安稽核。你要在**不中斷服務**的前提下整改。

整改路線：

```text
  【階段 0】盤點：mysql-grant-audit.sh → 風險分級 CSV ＋ 回滾快照
  【階段 1】建帳號：依系統別建 app_* / ro_* / backup / repl 與對應 ROLE
  【階段 2】切換：逐一改應用連線字串，改一個驗一個（不要一次全改）
  【階段 3】收斂：root 只剩 localhost、刪匿名帳號、停用遠端 root
  【階段 4】驗收：整改前後對照表逐項打勾，CSV 交稽核
```

### 階段 0：盤點腳本

```bash
sudo install -d -m 0700 /var/backups/mysql-grants
sudo install -d -m 0750 /var/log/mysql-audit
sudo vi /usr/local/bin/mysql-grant-audit.sh
sudo chmod 700 /usr/local/bin/mysql-grant-audit.sh
```

```bash
#!/usr/bin/env bash
# /usr/local/bin/mysql-grant-audit.sh
# MySQL 帳號與權限盤點 —— 產出風險分級 CSV 與可回滾的 SHOW GRANTS 快照
# 用法：mysql-grant-audit.sh [--login-path=NAME] [--dry-run] [--out DIR]
set -euo pipefail

LOGIN_PATH="${LOGIN_PATH:-}"          # ★★★ 不接受命令列密碼，只用 login-path 或 ~/.my.cnf
DRY_RUN=0
OUT_DIR="/var/backups/mysql-grants"
STALE_DAYS=90                          # ★★★ 超過幾天沒改密碼算風險
TS="$(date +%FT%H-%M-%S)"

die()  { echo "[ERROR] $*" >&2; exit 1; }
info() { echo "[ $(date +%T) ] $*"; }
step() { echo; echo "═══ $* ═══"; }

# ── 參數解析 ──────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --login-path=*) LOGIN_PATH="${1#*=}" ;;
    --dry-run)      DRY_RUN=1 ;;
    --out)          shift; OUT_DIR="${1:-}" ;;
    --stale-days)   shift; STALE_DAYS="${1:-90}" ;;
    -h|--help)      sed -n '2,6p' "$0"; exit 0 ;;
    *)              die "未知參數：$1" ;;
  esac
  shift
done

MYSQL_ARGS=(-N -B)                    # -N 不要標題列、-B 用 tab 分隔（好解析）
[[ -n "$LOGIN_PATH" ]] && MYSQL_ARGS=(--login-path="$LOGIN_PATH" "${MYSQL_ARGS[@]}")

q() { mysql "${MYSQL_ARGS[@]}" -e "$1"; }

# ── 前置檢查 ──────────────────────────────────────────────
step "前置檢查"
command -v mysql >/dev/null 2>&1 || die "找不到 mysql client"
q "SELECT 1" >/dev/null 2>&1 || die "無法連線 MySQL；請確認 --login-path 或 ~/.my.cnf（chmod 600）"

SERVER_VER="$(q "SELECT VERSION();")"
info "伺服器版本：$SERVER_VER"
case "$SERVER_VER" in
  *MariaDB*) info "★★★ 偵測到 MariaDB —— 部分欄位（password_last_changed 等）語意不同，請人工複核" ;;
esac

if [[ $DRY_RUN -eq 1 ]]; then
  info "★ dry-run 模式：只顯示會執行的查詢，不寫出任何檔案"
else
  install -d -m 0700 "$OUT_DIR" || die "無法建立輸出目錄 $OUT_DIR"
fi

CSV="$OUT_DIR/account-risk-$TS.csv"
SNAP="$OUT_DIR/grants-$TS.sql"

# ── 1. 帳號清單 ───────────────────────────────────────────
step "1. 盤點帳號"
ACCOUNTS="$(q "
  SELECT CONCAT(user,'\t',host,'\t',plugin,'\t',account_locked,'\t',
                password_expired,'\t',IFNULL(password_last_changed,''),'\t',
                IFNULL(DATEDIFF(NOW(), password_last_changed),-1))
  FROM mysql.user ORDER BY user, host;")"
info "共 $(echo "$ACCOUNTS" | grep -c . || true) 個帳號"

# ── 2. 危險權限（靜態 + 動態）─────────────────────────────
step "2. 掃描危險權限"
DANGER="$(q "
  SELECT CONCAT(grantee,'|',privilege_type)
  FROM information_schema.user_privileges
  WHERE privilege_type IN
    ('SUPER','FILE','SHUTDOWN','PROCESS','CREATE USER','GRANT OPTION','RELOAD');")"

# ★★★ MySQL 8 的動態權限不在 information_schema.user_privileges，要另外撈
DYN="$(q "
  SELECT CONCAT('''',user,'''@''',host,'''','|',priv)
  FROM mysql.global_grants
  WHERE priv IN ('SYSTEM_VARIABLES_ADMIN','CONNECTION_ADMIN','ROLE_ADMIN',
                 'BACKUP_ADMIN','PERSIST_RO_VARIABLES_ADMIN','SET_USER_ID');" 2>/dev/null || true)"

# ── 3. 產出 CSV ───────────────────────────────────────────
step "3. 產出風險分級 CSV"
emit_csv() {
  echo "帳號,來源host,認證外掛,已鎖定,密碼已過期,最後改密碼,距今天數,危險權限,風險等級,建議動作"
  while IFS=$'\t' read -r u h plug locked expired changed days; do
    [[ -z "${u:-}" && -z "${h:-}" ]] && continue
    local_grantee="'${u}'@'${h}'"
    danger="$(printf '%s\n%s\n' "$DANGER" "$DYN" \
      | grep -F "$local_grantee|" | cut -d'|' -f2 | paste -sd';' - || true)"

    score=0
    action=""
    [[ "$h" == "%" ]]                       && { score=$((score+40)); action="${action}收斂host;"; }
    [[ -z "$u" ]]                           && { score=$((score+50)); action="${action}刪除匿名帳號;"; }
    [[ "$u" == "root" && "$h" != "localhost" ]] && { score=$((score+50)); action="${action}移除遠端root;"; }
    [[ -n "$danger" ]]                      && { score=$((score+25)); action="${action}檢討高權限;"; }
    [[ "$plug" == "mysql_native_password" ]] && { score=$((score+10)); action="${action}評估改caching_sha2;"; }
    [[ "$days" =~ ^[0-9]+$ && "$days" -gt "$STALE_DAYS" ]] && \
                                               { score=$((score+15)); action="${action}逾期未改密碼;"; }
    [[ "$days" == "-1" ]]                   && { score=$((score+5));  action="${action}無改密碼紀錄;"; }

    if   [[ $score -ge 50 ]]; then level="高"
    elif [[ $score -ge 25 ]]; then level="中"
    elif [[ $score -gt 0  ]]; then level="低"
    else level="正常"; action="無"
    fi

    echo "\"$u\",\"$h\",\"$plug\",\"$locked\",\"$expired\",\"$changed\",\"$days\",\"${danger:-無}\",\"$level\",\"${action:-無}\""
  done <<< "$ACCOUNTS"
}

# ── 4. 回滾快照 ───────────────────────────────────────────
step "4. 產生回滾快照（SHOW GRANTS）"
emit_snapshot() {
  echo "-- MySQL 權限快照 $TS（來源：$(hostname -f 2>/dev/null || hostname)）"
  echo "-- ★★★★ 這是整改前的狀態，可直接 mysql < 本檔 還原授權"
  while IFS=$'\t' read -r u h _rest; do
    [[ -z "${u:-}" && -z "${h:-}" ]] && continue
    echo "-- ── '${u}'@'${h}' ──"
    mysql "${MYSQL_ARGS[@]}" -e "SHOW GRANTS FOR '${u}'@'${h}';" 2>/dev/null \
      | sed 's/$/;/' || echo "-- (無法讀取，可能是已鎖定的系統帳號)"
  done <<< "$ACCOUNTS"
}

if [[ $DRY_RUN -eq 1 ]]; then
  info "★ dry-run：以下是【會】寫入 $CSV 的前 10 列"
  emit_csv | head -10
  info "★ dry-run：以下是【會】寫入 $SNAP 的前 10 行"
  emit_snapshot | head -10
  exit 0
fi

umask 077
emit_csv      > "$CSV"      || die "寫入 CSV 失敗"
emit_snapshot > "$SNAP"     || die "寫入快照失敗"
chmod 600 "$CSV" "$SNAP"

# ── 5. 摘要 ───────────────────────────────────────────────
step "5. 摘要"
HIGH=$(awk -F'","' 'NR>1 && $9=="高"{c++} END{print c+0}' "$CSV")
MID=$(awk  -F'","' 'NR>1 && $9=="中"{c++} END{print c+0}' "$CSV")
echo "  風險【高】：$HIGH 個帳號"
echo "  風險【中】：$MID 個帳號"
echo "  CSV ：$CSV"
echo "  快照：$SNAP   ← ★★★★ 整改前務必確認這個檔案存在且不是 0 bytes"
[[ -s "$SNAP" ]] || die "快照是空的，不要開始整改"
[[ $HIGH -gt 0 ]] && echo "  ★★★★ 有高風險帳號，請依 CSV 的『建議動作』欄逐項處理"
exit 0
```

先跑 dry-run：

```bash
sudo /usr/local/bin/mysql-grant-audit.sh --dry-run
```

預期輸出：

```text
═══ 前置檢查 ═══
[ 09:14:02 ] 伺服器版本：8.0.42-0ubuntu0.24.04.1
[ 09:14:02 ] ★ dry-run 模式：只顯示會執行的查詢，不寫出任何檔案

═══ 1. 盤點帳號 ═══
[ 09:14:02 ] 共 11 個帳號
...
帳號,來源host,認證外掛,已鎖定,密碼已過期,最後改密碼,距今天數,危險權限,風險等級,建議動作
"","localhost","mysql_native_password","N","N","2023-04-11 10:02:11","1235","無","高","刪除匿名帳號;逾期未改密碼;"
"root","%","caching_sha2_password","N","N","2023-04-11 10:02:11","1235","SUPER;FILE;GRANT OPTION","高","收斂host;移除遠端root;檢討高權限;逾期未改密碼;"
```

正式執行：

```bash
sudo /usr/local/bin/mysql-grant-audit.sh --login-path=admin
```

```text
═══ 5. 摘要 ═══
  風險【高】：3 個帳號
  風險【中】：2 個帳號
  CSV ：/var/backups/mysql-grants/account-risk-2026-08-28T09-20-11.csv
  快照：/var/backups/mysql-grants/grants-2026-08-28T09-20-11.sql   ← ★★★★ 整改前務必確認這個檔案存在且不是 0 bytes
  ★★★★ 有高風險帳號，請依 CSV 的『建議動作』欄逐項處理
```

### 階段 1：建立帳號與角色

把整改語句寫成檔案（而不是手打），才有變更紀錄：

```bash
sudo vi /root/remediation-2026-08-28.sql
```

```sql
-- /root/remediation-2026-08-28.sql
-- 機關系統 DB 帳號整改 —— 核可單號 IT-2026-0812
-- ★★★★ 執行前確認 /var/backups/mysql-grants/grants-*.sql 已產出

-- ═══ 角色 ═══
CREATE ROLE IF NOT EXISTS 'r_hr_rw','r_hr_ro','r_doc_rw','r_doc_ro';
GRANT SELECT, INSERT, UPDATE, DELETE ON `hr_db`.*  TO 'r_hr_rw';
GRANT SELECT                         ON `hr_db`.*  TO 'r_hr_ro';
GRANT SELECT, INSERT, UPDATE, DELETE ON `doc_db`.* TO 'r_doc_rw';
GRANT SELECT                         ON `doc_db`.* TO 'r_doc_ro';

-- ═══ 應用帳號 ═══
CREATE USER IF NOT EXISTS 'app_hr'@'127.0.0.1'
  IDENTIFIED WITH caching_sha2_password BY 'PLACEHOLDER-HR'
  PASSWORD EXPIRE INTERVAL 180 DAY FAILED_LOGIN_ATTEMPTS 8 PASSWORD_LOCK_TIME 1;
CREATE USER IF NOT EXISTS 'app_doc'@'127.0.0.1'
  IDENTIFIED WITH caching_sha2_password BY 'PLACEHOLDER-DOC'
  PASSWORD EXPIRE INTERVAL 180 DAY FAILED_LOGIN_ATTEMPTS 8 PASSWORD_LOCK_TIME 1;
GRANT 'r_hr_rw'  TO 'app_hr'@'127.0.0.1';
GRANT 'r_doc_rw' TO 'app_doc'@'127.0.0.1';
SET DEFAULT ROLE ALL TO 'app_hr'@'127.0.0.1', 'app_doc'@'127.0.0.1';

-- ═══ 唯讀帳號 ═══
CREATE USER IF NOT EXISTS 'ro_audit'@'10.0.1.%'
  IDENTIFIED WITH caching_sha2_password BY 'PLACEHOLDER-RO'
  PASSWORD EXPIRE INTERVAL 90 DAY;
GRANT 'r_hr_ro','r_doc_ro' TO 'ro_audit'@'10.0.1.%';
SET DEFAULT ROLE ALL TO 'ro_audit'@'10.0.1.%';
ALTER USER 'ro_audit'@'10.0.1.%' WITH MAX_USER_CONNECTIONS 5 MAX_QUERIES_PER_HOUR 20000;

-- ═══ 備份帳號 ═══
CREATE USER IF NOT EXISTS 'backup'@'localhost'
  IDENTIFIED WITH caching_sha2_password BY 'PLACEHOLDER-BK';
GRANT SELECT, LOCK TABLES, RELOAD, PROCESS, REPLICATION CLIENT,
      SHOW VIEW, EVENT, TRIGGER ON *.* TO 'backup'@'localhost';

-- ═══ 複寫帳號 ═══
CREATE USER IF NOT EXISTS 'repl'@'10.0.1.31'
  IDENTIFIED WITH caching_sha2_password BY 'PLACEHOLDER-REPL';
GRANT REPLICATION SLAVE ON *.* TO 'repl'@'10.0.1.31';
```

產生密碼並替換 placeholder（**密碼不要出現在 history**）：

```bash
for k in HR DOC RO BK REPL; do
  P="$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-20)Aa1!"
  sudo sed -i "s|PLACEHOLDER-$k|$P|" /root/remediation-2026-08-28.sql
  echo "$k 密碼已產生（請立即存入密碼保管系統）"
done
sudo chmod 600 /root/remediation-2026-08-28.sql
```

執行：

```bash
sudo mysql < /root/remediation-2026-08-28.sql && echo "整改語句執行完成"
```

```text
整改語句執行完成
```

### 階段 2：逐一切換應用並驗證

```bash
# 【每個系統做一次，不要一次全改】
sudo cp -a /var/www/hr/.env /var/www/hr/.env.bak-$(date +%F)     # ★★★★ 回滾用
sudo sed -i 's/^DB_HOST=.*/DB_HOST=127.0.0.1/'   /var/www/hr/.env
sudo sed -i 's/^DB_USERNAME=.*/DB_USERNAME=app_hr/' /var/www/hr/.env
sudo sed -i 's/^DB_PASSWORD=.*/DB_PASSWORD=<新密碼>/' /var/www/hr/.env

# 先用該帳號【手動】連一次，確定連得上再重載服務
mysql -u app_hr -p -h 127.0.0.1 hr_db -e "SELECT COUNT(*) FROM staff;"
```

```text
+----------+
| COUNT(*) |
+----------+
|      412 |
+----------+
```

```bash
# Laravel 清設定快取後重載 PHP-FPM
sudo -u www-data php /var/www/hr/artisan config:clear
sudo systemctl reload php8.3-fpm
curl -sS -o /dev/null -w '%{http_code}\n' https://hr.example.gov.tw/health
```

```text
200
```

失敗時的回滾：

```bash
sudo cp -a /var/www/hr/.env.bak-2026-08-28 /var/www/hr/.env
sudo -u www-data php /var/www/hr/artisan config:clear
sudo systemctl reload php8.3-fpm
```

### 階段 3：收斂 root

**八個系統全部切換並穩定運行 7 天後**才做這一步：

```bash
# 先確認沒有任何連線還在用 root
sudo mysql -e "SELECT user, host, db, COUNT(*) AS 連線數 FROM information_schema.processlist GROUP BY user, host, db;"
```

```text
+---------+----------------+--------+--------+
| user    | host           | db     | 連線數 |
+---------+----------------+--------+--------+
| app_hr  | 127.0.0.1:5210 | hr_db  |     12 |
| app_doc | 127.0.0.1:5344 | doc_db |      8 |
| root    | localhost      | NULL   |      1 |   # ★ 只剩你自己這一條，可以收了
+---------+----------------+--------+--------+
```

```sql
DROP USER IF EXISTS 'root'@'%';
DROP USER IF EXISTS ''@'localhost';
DROP USER IF EXISTS ''@'%';
ALTER USER 'root'@'localhost' IDENTIFIED BY '<新的高強度密碼>';
```

`bind-address` 收斂與防火牆規則屬於 [[07-MySQL-安全強化]]，這裡不重複。

### 驗收檢查表

| # | 檢查項 | 指令 | 預期結果 | 星級 |
| --- | --- | --- | --- | --- |
| 1 | 無匿名帳號 | `mysql -e "SELECT COUNT(*) FROM mysql.user WHERE user='';"` | `0` | ★★★★ |
| 2 | root 只在 localhost | `mysql -e "SELECT host FROM mysql.user WHERE user='root';"` | 只有 `localhost` | ★★★★★ |
| 3 | 無 host=% 的應用帳號 | `mysql -e "SELECT user FROM mysql.user WHERE host='%';"` | 空（或僅角色） | ★★★★ |
| 4 | 應用帳號無 DROP 權限 | `mysql -e "SHOW GRANTS FOR 'app_hr'@'127.0.0.1';"` | 只見 `SELECT,INSERT,UPDATE,DELETE` | ★★★★ |
| 5 | 應用帳號角色已啟用 | `mysql -u app_hr -p -h 127.0.0.1 -e "SELECT CURRENT_ROLE();"` | 非 `NONE` | ★★★★ |
| 6 | 唯讀帳號寫入被擋 | `mysql -u ro_audit -p -h 10.0.1.10 hr_db -e "UPDATE staff SET dept='X' LIMIT 1;"` | `ERROR 1142` | ★★★ |
| 7 | backup 帳號可完整 dump | `mysqldump --login-path=backup --single-transaction --routines --triggers --events --databases hr_db > /dev/null` | 無錯誤 | ★★★★ |
| 8 | repl 帳號僅一項權限 | `mysql -e "SHOW GRANTS FOR 'repl'@'10.0.1.31';"` | 僅 `REPLICATION SLAVE` | ★★★ |
| 9 | 排程無明文密碼 | `sudo grep -rEn -- "-p[^ ]" /etc/cron.d/ /etc/cron.daily/` | 無結果 | ★★★★ |
| 10 | 憑證檔權限正確 | `stat -c '%a %n' /root/.my.cnf /root/.mylogin.cnf` | `600` | ★★★★ |
| 11 | 密碼政策生效 | `mysql -e "CREATE USER 'wk'@'localhost' IDENTIFIED BY 'password123';"` | `ERROR 1819` | ★★★ |
| 12 | 回滾快照存在且非空 | `ls -l /var/backups/mysql-grants/grants-*.sql` | 檔案大小 > 0 | ★★★★★ |
| 13 | 八個系統健康檢查 | `for h in hr doc ...; do curl -o /dev/null -w "%{http_code} " https://$h.example.gov.tw/health; done` | 全部 `200` | ★★★★ |
| 14 | 整改後重跑盤點 | `sudo /usr/local/bin/mysql-grant-audit.sh` | 高風險 = 0 | ★★★★ |

> [!tip] 交稽核的成品
> 整改**前**與**後**各跑一次 `mysql-grant-audit.sh`，兩份 CSV 並排就是最好的佐證：
> 「高風險帳號由 3 個降為 0，root 遠端連線已停用，八個子系統改為最小權限帳號」。
> 稽核佐證的整理方式見 [[09-資安稽核與符合性檢核]]。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **★★★★ `ERROR 1045 Access denied for user 'app'@'localhost' (using password: YES)`，密碼確定正確** | `.env` 用 `localhost` 走 socket，但你只建了 `'app'@'127.0.0.1'` | `.env` 改 `127.0.0.1`，或補建 `'app'@'localhost'`；先跑 `SELECT CURRENT_USER();` 確認 |
| **★★★★ 建了 `'app'@'%'`，本機卻連不上** | 殘存匿名帳號 `''@'localhost'` 比對優先 | `DROP USER ''@'localhost';` 後重試 |
| **★★★★ `ERROR 2059 Authentication plugin 'caching_sha2_password' cannot be loaded`** | 用戶端（舊 PHP、MariaDB client、舊 GUI）不支援 | 優先升級用戶端；不得已才 `ALTER USER ... IDENTIFIED WITH mysql_native_password`（8.4 需先載入外掛） |
| **★★★★ 授權了卻 `SHOW GRANTS` 只有 `USAGE`** | 用了 ROLE 但沒 `SET DEFAULT ROLE` | `SET DEFAULT ROLE ALL TO 'u'@'h';`，用 `SELECT CURRENT_ROLE();` 驗證 |
| **★★★★ `ERROR 1044 Access denied for user ... to database 'hr_db'`** | 帳號存在但**資料庫層**沒授權，或授權給了另一個 host | `SHOW GRANTS FOR CURRENT_USER();` 對照；注意反引號內的 host |
| **★★★ `mysqldump: Couldn't execute 'FLUSH TABLES': Access denied ... RELOAD privilege`** | backup 帳號少 `RELOAD` | `GRANT RELOAD ON *.* TO 'backup'@'localhost';` |
| **★★★ dump 出來的 view 是空定義、trigger 消失** | 少 `SHOW VIEW` / `TRIGGER` | 補齊本篇「backup 帳號」那一組八個權限 |
| **★★★ `ERROR 1819 Your password does not satisfy the current policy requirements`** | `validate_password` 政策擋下 | 依 `SHOW VARIABLES LIKE 'validate_password%';` 產生合規密碼，不要為此關掉政策 |
| **★★★ `ERROR 3955 Account is blocked for N day(s)`** | 連續錯密碼觸發 `FAILED_LOGIN_ATTEMPTS` | 排除密碼來源錯誤後 `ALTER USER 'u'@'h' ACCOUNT UNLOCK;`；先查是誰在暴力嘗試 |
| **★★★ `ERROR 3118 Account is locked`** | 帳號被 `ACCOUNT LOCK`（或系統保留帳號） | 確認是否為離職鎖定；`mysql.session` 等系統帳號**本來就該鎖著** |
| **★★★ `ERROR 1820 You must reset your password using ALTER USER`** | 密碼已過期 | `ALTER USER USER() IDENTIFIED BY '<新密碼>';`（用該帳號自己連線後執行） |
| **★★★ `REVOKE` 報 `ERROR 1141 There is no such grant defined`** | 撤銷的權限清單與當初 `GRANT` 的粒度不同（例如對 `db.*` 授權卻想從 `db.tbl` 撤銷） | 先 `SHOW GRANTS` 看實際粒度，照同一層級撤銷 |
| **★★★ `DROP USER` 後應用全斷、找不回原權限** | 沒有事前快照 | 從 `/var/backups/mysql-grants/grants-*.sql` 還原；沒有快照就只能重建（見「快速復原」） |
| **★★ 改了 `mysql.user` 表，重啟前都沒生效** | 直接改表需要 `FLUSH PRIVILEGES` | 改用 `ALTER USER` / `GRANT` 語句，就不需要 flush |
| **★★ 報表帳號一支 SQL 把正式庫拖垮** | 唯讀帳號沒有資源限制 | `ALTER USER ... WITH MAX_USER_CONNECTIONS 5 MAX_QUERIES_PER_HOUR 20000;` |
| **★★ `ps` 看得到 `-pXXXX` 明文密碼** | 排程腳本用命令列傳密碼 | 改用 `--login-path` 或 `--defaults-file`；`~/.my.cnf` 設 `chmod 600` |
| **★★ MariaDB 上 `SET DEFAULT ROLE ALL` 語法錯誤** | MariaDB 只支援單一預設角色 | `SET DEFAULT ROLE <單一角色> FOR 'u'@'h';` |
| **★★ 連線來源顯示成主機名而非 IP，比對不到 `10.0.1.%`** | 開了反解（DNS resolve） | `SELECT CURRENT_USER();` 看實際比對結果；必要時在 07 篇評估 `skip_name_resolve` |

### 排查步驟

**★★★★ 遇到 `Access denied` 一律照這個順序走，不要先改密碼。**

**【1】** 先看清楚錯誤訊息的三個線索

```bash
mysql -u app_hr -p -h 127.0.0.1 hr_db -e "SELECT 1;"
```

```text
ERROR 1045 (28000): Access denied for user 'app_hr'@'localhost' (using password: YES)
                                            ^^^^^^  ^^^^^^^^^      ^^^^^^^^^^^^^^^^^
                                            使用者   伺服器看到的來源   有沒有送密碼
```

- `using password: **NO**` → 密碼根本沒送出去（`.env` 空值、`-p` 後面接錯、設定檔沒讀到）
- `using password: **YES**` → 密碼有送，是**帳號不存在**或**密碼不對**
- 訊息裡的 host 是**伺服器端看到的來源**（可能是反解後的主機名），**不是**你比對到的帳號

**【2】** 用一個確定能登入的帳號，列出所有同名帳號

```bash
sudo mysql -e "SELECT user, host, plugin, account_locked, password_expired FROM mysql.user WHERE user='app_hr';"
```

```text
+--------+-----------+-----------------------+----------------+------------------+
| user   | host      | plugin                | account_locked | password_expired |
+--------+-----------+-----------------------+----------------+------------------+
| app_hr | localhost | caching_sha2_password | N              | N                |
+--------+-----------+-----------------------+----------------+------------------+
```

- **只有 `localhost` 一列，而你用 `-h 127.0.0.1`** → 問題在【第 3 步】，帳號不存在
- **有你要的那一列** → 跳到【第 5 步】
- **完全空的** → 帳號真的沒建，或建在別的名字

**【3】** 確認走的是 socket 還是 TCP

```bash
mysql -u app_hr -p -h 127.0.0.1 -e "SELECT USER(), CURRENT_USER(), @@socket;" 2>&1 | head -3
```

成功時：

```text
+-------------------+----------------+-----------------------------+
| USER()            | CURRENT_USER() | @@socket                    |
+-------------------+----------------+-----------------------------+
| app_hr@localhost  | app_hr@127.0.0.1 | /var/run/mysqld/mysqld.sock |
```

`CURRENT_USER()` 就是**真正生效的帳號**。若它跟你以為的不同，權限問題就解釋得通了。

**【4】** 若不確定連線方式，強制指定後再測一次

```bash
mysql -u app_hr -p --protocol=SOCKET -e "SELECT CURRENT_USER();"   # 強制 socket
mysql -u app_hr -p --protocol=TCP -h 127.0.0.1 -e "SELECT CURRENT_USER();"  # 強制 TCP
```

- **socket 成功、TCP 失敗** → 只有 `'app_hr'@'localhost'`；`.env` 改回 `localhost` 或補建 TCP 帳號
- **兩個都失敗** → 問題在密碼或認證外掛，往下走

**【5】** 檢查認證外掛與用戶端相容性

```bash
sudo mysql -e "SELECT user, host, plugin FROM mysql.user WHERE user='app_hr';"
php -r 'var_dump(extension_loaded("pdo_mysql"), PHP_VERSION);'
```

```text
| app_hr | 127.0.0.1 | caching_sha2_password |

bool(true)
string(6) "7.2.34"      # ★★★★ PHP 7.2 對 caching_sha2_password 有已知問題
```

- **PHP < 7.4 ＋ `caching_sha2_password`** → 先升 PHP；不得已才換外掛
- **錯誤是 `The server requested authentication method unknown to the client`** → 同上

**【6】** 檢查帳號是否被鎖或密碼過期

```bash
sudo mysql -e "SELECT user, host, account_locked, password_expired, password_last_changed, password_lifetime FROM mysql.user WHERE user='app_hr'\G"
```

```text
*************************** 1. row ***************************
                user: app_hr
                host: 127.0.0.1
      account_locked: N
    password_expired: Y          # ★★★ 密碼已過期，錯誤會是 1820 而不是 1045
password_last_changed: 2026-02-01 10:00:00
   password_lifetime: 180
```

**【7】** 帳號能登入但操作被拒 —— 看的是權限不是密碼

```bash
mysql -u app_hr -p -h 127.0.0.1 -e "SELECT CURRENT_USER(); SELECT CURRENT_ROLE(); SHOW GRANTS;"
```

```text
| app_hr@127.0.0.1 |
| NONE             |     # ★★★★ 角色沒啟用 → SET DEFAULT ROLE ALL
| GRANT USAGE ON *.* TO `app_hr`@`127.0.0.1` |
```

- `ERROR 1044`（database 層）→ 缺 `GRANT ... ON db.*`
- `ERROR 1142`（table 層）→ 缺該表的特定權限，訊息會直接寫出缺哪個指令

**【8】** 排除匿名帳號干擾

```bash
sudo mysql -e "SELECT CONCAT('''',user,'''@''',host,'''') AS 帳號 FROM mysql.user WHERE user='' ;"
```

```text
+-------------------+
| 帳號              |
+-------------------+
| ''@'localhost'    |     # ★★★★ 存在就是問題，刪掉
+-------------------+
```

**【9】** 以上都排除仍登不進去 —— 最後手段（需核可）

```bash
# ★★★★★ 這段期間資料庫沒有任何認證，務必加 --skip-networking
sudo systemctl stop mysql
sudo mysqld_safe --skip-grant-tables --skip-networking &
sudo mysql -e "FLUSH PRIVILEGES; ALTER USER 'app_hr'@'127.0.0.1' IDENTIFIED BY '<新密碼>';"
sudo systemctl restart mysql
```

修完後**必須**檢查這段空窗期的連線紀錄，並留下變更紀錄。若懷疑期間有異常存取，
走 [[04-備份災難復原與入侵應變]] 的應變流程。

---

## 安全性注意事項

> [!danger] ★★★★★ 絕對禁止：`GRANT ALL PRIVILEGES ON *.* TO 'app'@'%' WITH GRANT OPTION`
> 這一行同時犯了三個錯，任何一個都足以造成資安事件：
> 1. **`ALL ON *.*`** → 網頁的一個 SQL injection 就能 `SELECT ... INTO OUTFILE '/var/www/html/x.php'`
>    寫出 webshell，或 `LOAD_FILE('/etc/shadow')` 讀系統檔 —— **這已經不是資料庫外洩，是主機淪陷**
> 2. **`host = '%'`** → 配上對外監聽的 3306，資料庫**直接暴露在網際網路上**，
>    全球掃描器 24 小時在敲 3306 弱密碼
> 3. **`GRANT OPTION`** → 攻擊者建立自己的後門帳號，你改了密碼也沒用
>
> 正確做法：`GRANT SELECT, INSERT, UPDATE, DELETE ON app_db.* TO 'app'@'127.0.0.1';`

> [!danger] ★★★★★ 絕對禁止：排程腳本裡寫明文密碼
> ```bash
> mysqldump -u backup -pS3cret! hr_db > /backup/hr.sql     # 不要
> ```
> 這個密碼會出現在：`ps -ef` 的輸出（**機器上任何使用者都看得到**）、
> `~/.bash_history`、`/etc/cron.d/` 底下（常是 644）、系統備份、
> 甚至被監控 agent 採集後送到日誌平台。
> **內部人員取得 DB 憑證最容易的路徑就是這一條。**
> 一律改用 `--login-path` 或 `--defaults-file`，檔案 `chmod 600`。

> [!danger] ★★★★ 絕對禁止：把 `.env` 或含密碼的 SQL 檔 commit 進 git
> `DB_PASSWORD` 一旦進 git 歷史，改密碼是唯一解 —— 刪 commit 沒有用，
> 廠商的筆電、CI runner、fork 出去的 repo 全都有一份。
> `.gitignore` 加上 `.env`、`*.sql`、`.my.cnf`、`.mylogin.cnf`；
> 機密的正確存放方式見 [[03-機密管理與金鑰保護]]。

### 機關情境的四個要求

| 要求 | 本篇對應做法 | 星級 |
| --- | --- | --- |
| **最小權限** | 每個系統一組 `app_*`，只給 `SELECT,INSERT,UPDATE,DELETE ON <該系統的 db>.*`；migration 權限只在部署視窗開放 | ★★★★ |
| **個資最小揭露** | 對外部人員／報表帳號用**欄位層授權**，身分證號、住址等欄位不授權 | ★★★★ |
| **可稽核** | 每次權限變更前後各跑一次 `mysql-grant-audit.sh`，CSV 與 `SHOW GRANTS` 快照歸檔；離職帳號先 `ACCOUNT LOCK` 保留軌跡 | ★★★★ |
| **憑證保護** | 所有 DB 憑證存密碼保管系統，機器上只留 `chmod 600` 的 login-path；輪換週期與密碼原則一致 | ★★★ |

> [!warning] ★★★★ 這篇只做「誰能做什麼」，還有兩件事沒做
> 1. **連線加密**：本篇建立的帳號目前**都是明文傳輸**（含 `repl` 的複寫流量）。
>    `REQUIRE SSL` / `REQUIRE X509` 與憑證簽發在 [[07-MySQL-安全強化]]。
> 2. **稽核日誌**：MySQL 社群版沒有內建 audit log，需要方案選型；
>    「誰在什麼時候用哪個帳號做了什麼」也在 [[07-MySQL-安全強化]]。
>
> 政府組態基準（TWGCB）對資料庫帳號有相關要求，**條號與版本請以
> <https://www.nccst.nat.gov.tw/GCB> 上你所用 OS／版本的現行文件為準**，
> 不要引用二手整理的條號。對照方式見 [[08-系統強化與稽核]]。

> [!warning] ★★★ 備份檔本身就是完整的資料庫
> 你設計了完美的最小權限，但 `/backup/hr_db-2026-08-28.sql.gz` 是 `644`、
> 而且沒有加密 —— 那所有努力都白費。備份檔的權限、加密與異地保存見
> [[05-MySQL-備份與還原]] 與 [[04-備份災難復原與入侵應變]]。

---

## 速查表

### 帳號管理

| 指令 | 說明 | 星級 |
| --- | --- | --- |
| `CREATE USER IF NOT EXISTS 'u'@'h' IDENTIFIED WITH caching_sha2_password BY 'p';` | 建帳號，明確指定外掛 | ★★★★ |
| `ALTER USER 'u'@'h' IDENTIFIED BY 'p';` | 改密碼 | ★★★ |
| `ALTER USER USER() IDENTIFIED BY 'p';` | **改自己的**密碼（密碼過期時用） | ★★★ |
| `RENAME USER 'u'@'old' TO 'u'@'new';` | 換 host，**權限一併保留** | ★★★ |
| `DROP USER IF EXISTS 'u'@'h';` | 刪帳號 | ★★★ |
| `ALTER USER 'u'@'h' ACCOUNT LOCK / UNLOCK;` | 鎖定／解鎖（離職先鎖不刪） | ★★★★ |

### 授權與撤銷

| 指令 | 說明 | 星級 |
| --- | --- | --- |
| `GRANT SELECT,INSERT,UPDATE,DELETE ON db.* TO 'u'@'h';` | **應用帳號的標準授權** | ★★★★ |
| `GRANT SELECT (col1,col2) ON db.t TO 'u'@'h';` | 欄位層，個資最小揭露 | ★★★★ |
| `REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'u'@'h';` | 清空權限（帳號保留） | ★★★ |
| `SHOW GRANTS FOR 'u'@'h';` | 看授權（**變更前必存檔**） | ★★★★ |
| `SHOW GRANTS FOR 'u'@'h' USING 'role';` | 含角色的完整權限 | ★★★ |
| `SHOW GRANTS;` | 看自己（等同 `FOR CURRENT_USER()`） | ★★★ |
| `FLUSH PRIVILEGES;` | **只在直接改 mysql 表後才需要** | ★★ |

### 角色（MySQL 8）

| 指令 | 說明 | 星級 |
| --- | --- | --- |
| `CREATE ROLE 'r_app_rw';` | 建角色 | ★★★ |
| `GRANT 'r_app_rw' TO 'u'@'h';` | 授予角色 | ★★★ |
| `SET DEFAULT ROLE ALL TO 'u'@'h';` | **登入即啟用（漏了等於沒授權）** | ★★★★ |
| `SET ROLE 'r_migrate';` | 單一 session 內臨時提權 | ★★★ |
| `SELECT CURRENT_ROLE();` | 看目前生效的角色 | ★★★★ |

### 診斷

| 指令 | 說明 | 星級 |
| --- | --- | --- |
| `SELECT USER(), CURRENT_USER();` | **Access denied 的第一條指令** | ★★★★★ |
| `SELECT user, host, plugin FROM mysql.user ORDER BY user, host;` | 帳號全景 | ★★★★ |
| `SELECT user,host FROM mysql.user WHERE user='';` | 找匿名帳號 | ★★★★ |
| `SELECT user,host FROM mysql.user WHERE host='%';` | 找開放來源的帳號 | ★★★★ |
| `SELECT grantee,privilege_type FROM information_schema.user_privileges;` | 靜態權限總覽 | ★★★ |
| `SELECT user,host,priv FROM mysql.global_grants;` | **動態權限**（MySQL 8） | ★★★ |
| `SELECT user,host,db FROM information_schema.processlist;` | 誰正連著、用哪個帳號 | ★★★★ |
| `SELECT user,host,DATEDIFF(NOW(),password_last_changed) d FROM mysql.user HAVING d>90;` | 逾期未改密碼 | ★★★ |

### 檔案與路徑

| 路徑 | 用途 | 權限 | 星級 |
| --- | --- | --- | --- |
| `~/.my.cnf` | 用戶端預設帳密 | **600** | ★★★★ |
| `~/.mylogin.cnf` | `mysql_config_editor` 的 login-path（**混淆非加密**） | **600** | ★★★★ |
| `/etc/mysql/mysql.conf.d/mysqld.cnf` | Ubuntu 主設定檔 | 644 | ★★★ |
| `/etc/my.cnf.d/` | RHEL 系設定檔目錄 | 644 | ★★★ |
| `/var/run/mysqld/mysqld.sock` | Ubuntu socket | — | ★★★ |
| `/var/lib/mysql/mysql.sock` | RHEL 系 socket | — | ★★★ |
| `/var/backups/mysql-grants/` | 權限快照與稽核 CSV | **700** | ★★★★ |

### 判斷準則

| 問題 | 判斷 | 星級 |
| --- | --- | --- |
| `.env` 該填 `localhost` 還是 `127.0.0.1`？ | **選一種並只建那一個帳號**；預設建議 `127.0.0.1` | ★★★★ |
| 應用帳號要不要 `DROP`？ | 平常**不要**；只在部署視窗臨時給，跑完收回 | ★★★★ |
| host 要寫多細？ | 具體 IP > 網段 `10.0.1.%` > **絕不用 `%`** | ★★★★ |
| 帳號沒人用了要刪嗎？ | 先 `ACCOUNT LOCK` 觀察 7~30 天，確認無影響再 `DROP` | ★★★ |
| 要不要開 `activate_all_roles_on_login`？ | 多系統機關環境**建議關**，改用 `SET DEFAULT ROLE` 精確控制 | ★★★ |

---

## 練習題

> [!question]- 練習 1：重現並修好「密碼對卻 Access denied」
> **題目**：在測試機上刻意製造這個經典故障並修好它。
>
> **步驟**
> ```sql
> CREATE DATABASE IF NOT EXISTS lab_db;
> CREATE USER 'labapp'@'localhost' IDENTIFIED BY 'Lab-Pass!2026';
> GRANT SELECT, INSERT ON lab_db.* TO 'labapp'@'localhost';
> ```
> ```bash
> mysql -u labapp -p'Lab-Pass!2026' -h 127.0.0.1 lab_db -e "SELECT 1;"
> ```
>
> **參考解答**
> ```text
> 【故障】ERROR 1045 (28000): Access denied for user 'labapp'@'localhost' (using password: YES)
>
> 【診斷】
>   $ sudo mysql -e "SELECT user,host FROM mysql.user WHERE user='labapp';"
>   +--------+-----------+
>   | labapp | localhost |     ← 只有 localhost，沒有 127.0.0.1
>
>   ★★★★ 用 -h 127.0.0.1 走 TCP，比對的是 'labapp'@'127.0.0.1' —— 這個帳號不存在。
>   錯誤訊息裡寫 'labapp'@'localhost' 是【伺服器反解後看到的來源】，
>   不是「你比對到 localhost 帳號」，這一點最容易誤導人。
>
> 【修法 A】改用 socket（不指定 -h）
>   $ mysql -u labapp -p'Lab-Pass!2026' lab_db -e "SELECT CURRENT_USER();"
>   → labapp@localhost
>
> 【修法 B】補建 TCP 帳號（正式環境建議統一走這條）
>   CREATE USER 'labapp'@'127.0.0.1' IDENTIFIED BY 'Lab-Pass!2026';
>   GRANT SELECT, INSERT ON lab_db.* TO 'labapp'@'127.0.0.1';
>
> 【收尾】DROP USER 'labapp'@'localhost','labapp'@'127.0.0.1'; DROP DATABASE lab_db;
> ```

> [!question]- 練習 2：設計一個外部廠商的唯讀查詢帳號
> **題目**：廠商要查 `hr_db.staff` 做人力統計，但**不得看到身分證號 `id_no` 與住址 `addr`**。
> 廠商從 `10.0.9.0/24` 的跳板機連線。寫出完整語句與驗證方式。
>
> **參考解答**
> ```sql
> CREATE USER 'ro_vendor'@'10.0.9.%'
>   IDENTIFIED WITH caching_sha2_password BY '<產生的高強度密碼>'
>   PASSWORD EXPIRE INTERVAL 30 DAY          -- ★★★ 外部帳號週期要短
>   FAILED_LOGIN_ATTEMPTS 5 PASSWORD_LOCK_TIME 1;
>
> -- ★★★★ 欄位層授權：只給需要的欄，不給 SELECT ON hr_db.*
> GRANT SELECT (id, name, dept, hire_date) ON hr_db.staff TO 'ro_vendor'@'10.0.9.%';
>
> -- ★★★ 資源限制，避免拖垮正式庫
> ALTER USER 'ro_vendor'@'10.0.9.%' WITH MAX_USER_CONNECTIONS 2 MAX_QUERIES_PER_HOUR 2000;
> ```
> ```text
> 【驗證 1】能查授權欄位
>   $ mysql -u ro_vendor -p -h 10.0.1.10 hr_db -e "SELECT id,name,dept FROM staff LIMIT 1;"
>   → 正常回傳一列
>
> 【驗證 2】★★★★ 未授權欄位必須被擋
>   $ mysql -u ro_vendor -p -h 10.0.1.10 hr_db -e "SELECT id_no FROM staff LIMIT 1;"
>   → ERROR 1143 (42000): SELECT command denied to user 'ro_vendor'@'10.0.9.12'
>                          for column 'id_no' in table 'staff'
>
> 【驗證 3】SELECT * 也要被擋（很多人忘了測這個）
>   $ mysql -u ro_vendor -p -h 10.0.1.10 hr_db -e "SELECT * FROM staff LIMIT 1;"
>   → 同樣是 ERROR 1143 —— ★★★ 這證明欄位層授權真的擋得住
>
> 【收尾】合約結束當天 ACCOUNT LOCK，觀察期滿再 DROP USER，並留存 SHOW GRANTS 佐證。
> ```

> [!question]- 練習 3：把明文密碼的備份排程改成 login-path，並確認 `ps` 看不到
> **題目**：現有 crontab
> `0 3 * * * root mysqldump -u backup -pBk#2023 --all-databases > /backup/all.sql`
> 改成不含密碼的寫法，並實際驗證。
>
> **參考解答**
> ```bash
> # 【1】設定 login-path（互動輸入密碼，不進 history）
> sudo mysql_config_editor set --login-path=backup --host=localhost --user=backup --password
>
> # 【2】確認
> sudo mysql_config_editor print --all
> #   [backup]
> #   user = backup
> #   password = *****
> #   host = localhost
> sudo stat -c '%a %n' /root/.mylogin.cnf
> #   600 /root/.mylogin.cnf      ← ★★★★ 不是 600 的話 MySQL 會直接忽略它
>
> # 【3】改 crontab
> #   0 3 * * * root /usr/bin/mysqldump --login-path=backup --single-transaction \
> #     --routines --triggers --events --all-databases | gzip > /backup/all-$(date +\%F).sql.gz
>
> # 【4】★★★★ 實際驗證 ps 看不到密碼（開兩個終端）
> sudo mysqldump --login-path=backup --all-databases > /dev/null &
> ps -ef | grep [m]ysqldump
> #   root 30112 ... /usr/bin/mysqldump --login-path=backup --all-databases
> #   ★★★ 命令列上沒有任何密碼
>
> # 【5】舊密碼要當成已外洩處理
> #   它躺在 /etc/cron.d/（644）、bash_history、以及三年份的系統備份裡。
> #   ALTER USER 'backup'@'localhost' IDENTIFIED BY '<新密碼>'; 然後更新 login-path。
>
> # ★★★ 提醒：.mylogin.cnf 是【混淆】不是加密，取得 root 的人仍可還原密碼。
> #      真正的防線是這把憑證只有備份權限，不能建帳號、不能改資料。
> ```

---

## 小測驗

Q1. `'appuser'@'localhost'` 與 `'appuser'@'127.0.0.1'` 的關係是什麼？在 Laravel 的 `.env` 裡把 `DB_HOST` 從 `localhost` 改成 `127.0.0.1`，可能發生什麼事？

Q2. （是非）`mysql.user` 裡只有 `'app'@'%'` 一個帳號，那麼從本機用 `mysql -u app -p` 一定連得上。

Q3. 你執行 `SHOW GRANTS FOR 'app_hr'@'127.0.0.1';`，輸出只有 `GRANT USAGE ON *.*`，但你確定剛剛授權過。最可能的原因是什麼？怎麼確認？

Q4. 這行指令會發生什麼事，為什麼不能用在正式環境？
```sql
GRANT ALL PRIVILEGES ON *.* TO 'web'@'%' IDENTIFIED BY 'p' WITH GRANT OPTION;
```

Q5. 備份帳號執行 `mysqldump --single-transaction --master-data=2` 時出現
`Access denied; you need (at least one of) the RELOAD privilege(s)`，缺哪個權限？完整的備份帳號權限組合有哪八個？

Q6. （選擇）以下哪一個情況**真的需要** `FLUSH PRIVILEGES`？
(A) 執行完 `GRANT SELECT ON db.* TO 'u'@'h';`
(B) 執行完 `CREATE USER 'u'@'h' IDENTIFIED BY 'p';`
(C) 直接 `UPDATE mysql.user SET host='%' WHERE user='u';`
(D) 執行完 `DROP USER 'u'@'h';`

Q7. 排程腳本寫 `mysqldump -u backup -pS3cret! db > /backup/db.sql` 有什麼具體風險？三種替代做法各自的優缺點是什麼？

Q8. 舊系統升級到 MySQL 8.4 後，PHP 端出現
`The server requested authentication method unknown to the client`。你的處理順序應該是什麼？為什麼「直接把伺服器改回 `mysql_native_password`」是最後選項？

Q9. 看到這個錯誤，你要先查哪裡？
`ERROR 3955 (HY000): Access denied for user 'ro_hr'@'10.0.1.20'. Account is blocked for 1 day(s) (1 day(s) remaining) due to 5 consecutive failed logins.`

Q10. 你要在正式機上把一個應用帳號的權限從 `ALL ON app_db.*` 縮成 `SELECT,INSERT,UPDATE,DELETE`。寫出完整的四個步驟，包含如果出事怎麼回滾。

> [!question]- 測驗答案
> **Q1.** ★★★★ **它們是兩個完全獨立的帳號**，`mysql.user` 的主鍵是 `(user, host)` 兩欄，
> 各自有各自的密碼、權限與認證外掛。
> `DB_HOST=localhost` 時 PDO 走 unix socket，比對 `'appuser'@'localhost'`；
> 改成 `127.0.0.1` 走 TCP，比對 `'appuser'@'127.0.0.1'`。
> 若後者不存在，全站立刻出現
> `SQLSTATE[HY000] [1045] Access denied for user 'appuser'@'localhost' (using password: YES)` ——
> 密碼一個字都沒錯，錯的是帳號不存在。
> 診斷指令：`mysql -u appuser -p -h 127.0.0.1 -e "SELECT USER(), CURRENT_USER();"`。
> 實務建議：**只選一種並且只建那一個帳號**，兩者並存反而製造比對優先順序的坑。
> 見「觀念說明 → MySQL 的帳號不是一個名字」與「動手做一次」。
>
> **Q2.** ★★★★ **錯。** 若 `mysql.user` 裡還留著匿名帳號 `''@'localhost'`，
> 比對規則是「host 越精確越優先」，`'localhost'` 比 `'%'` 精確，
> 所以你的連線會先撞上匿名帳號；匿名帳號密碼為空，你送的密碼被判定錯誤，
> 得到 `ERROR 1045 ... 'app'@'localhost'`。
> 檢查：`SELECT user,host FROM mysql.user WHERE user='';`
> 解法：`DROP USER ''@'localhost'; DROP USER ''@'%';`
> 這也是 `mysql_secure_installation` 會做的第一件事。
> 見「觀念說明 → 帳號比對的優先順序」與排查步驟【8】。
>
> **Q3.** ★★★★ 最可能是**用了 ROLE 但沒有 `SET DEFAULT ROLE`**。
> `GRANT 'r_hr_rw' TO 'app_hr'@'127.0.0.1';` 只是「授予」，
> MySQL 8 預設**不會**在登入時啟用角色，所以 `SHOW GRANTS` 只看得到 `USAGE` 與角色授予那一行。
> 確認：用該帳號連線後 `SELECT CURRENT_ROLE();`，回 `NONE` 就是這個原因。
> 修正：`SET DEFAULT ROLE ALL TO 'app_hr'@'127.0.0.1';`
> 另一種確認方式：`SHOW GRANTS FOR 'app_hr'@'127.0.0.1' USING 'r_hr_rw';`
> 次要可能：你授權時打的 host 是 `localhost` 而不是 `127.0.0.1`（又是同一個坑）。
> 另外提醒 `USAGE` 不是權限，它代表「能登入但什麼都不能做」。
> 見「進階應用 → MySQL 8 的 ROLE」。
>
> **Q4.** ★★★★★ 三個問題疊在一起：
> 1. `ALL ON *.*` 包含 `FILE`，攻擊者可 `SELECT ... INTO OUTFILE '/var/www/html/x.php'`
>    寫 webshell、`LOAD_FILE()` 讀系統檔 —— 從資料庫外洩升級成**主機淪陷**。
> 2. `host='%'` 配上對外監聽的 3306，等於把資料庫掛在網際網路上讓人爆破。
> 3. `WITH GRANT OPTION` 讓攻擊者自建後門帳號，你改密碼也擋不住。
> 補充：`GRANT ... IDENTIFIED BY` 這種「授權同時建帳號」的寫法在 MySQL 8 已移除，
> 執行會直接語法錯誤 —— 必須先 `CREATE USER` 再 `GRANT`。
> 正解：`GRANT SELECT,INSERT,UPDATE,DELETE ON app_db.* TO 'web'@'127.0.0.1';`
> 見「安全性注意事項」第一則 danger。
>
> **Q5.** ★★★★ 缺 `RELOAD`（`--single-transaction` 搭配取 binlog 位置時需要
> `FLUSH TABLES WITH READ LOCK`）。
> 完整八個：`SELECT, LOCK TABLES, RELOAD, PROCESS, REPLICATION CLIENT, SHOW VIEW, EVENT, TRIGGER`。
> ```sql
> GRANT SELECT, LOCK TABLES, RELOAD, PROCESS, REPLICATION CLIENT,
>       SHOW VIEW, EVENT, TRIGGER ON *.* TO 'backup'@'localhost';
> ```
> 少 `SHOW VIEW` → view 定義變空；少 `TRIGGER` → trigger 全部遺失，
> 還原後資料邏輯默默壞掉（★★★★ 這種最可怕，備份看起來是成功的）。
> 少 `REPLICATION CLIENT` → 抓不到 binlog 位置／GTID，這份備份不能當複寫起點。
> 物理備份另需動態權限 `BACKUP_ADMIN`。
> 見「進階應用 → backup 帳號」與 [[05-MySQL-備份與還原]]。
>
> **Q6.** ★★★ 答案是 **(C)**。
> `GRANT` / `REVOKE` / `CREATE USER` / `ALTER USER` / `DROP USER` 這些 SQL 語句，
> MySQL 會自動同步記憶體中的授權表，**不需要** `FLUSH PRIVILEGES`。
> 只有**直接 `UPDATE` / `INSERT` `mysql` 系統資料庫的表**才需要 flush，否則改了等於沒改。
> 但這種做法本身就不建議：MySQL 8 的密碼欄位格式與動態權限都不該手動改，
> 改壞了帳號會直接登不進去。
> 看到教學叫你 `UPDATE mysql.user`，那是 MySQL 5.x 時代的寫法。
> 見「進階應用 → 什麼時候真的需要 FLUSH PRIVILEGES」。
>
> **Q7.** ★★★★ 風險：密碼會出現在 `ps -ef` 的輸出（**機器上任何使用者都看得到**）、
> `~/.bash_history`、`/etc/cron.d/` 底下的檔案（常是 644）、以及所有系統備份裡。
> 這是內部人員取得 DB 憑證最容易的路徑。
> 三種替代：
> - `~/.my.cnf` + `chmod 600`：最通用，所有 mysql 系工具都吃；缺點是一個檔只方便放一組主要憑證。
> - `mysql_config_editor --login-path`：多組憑證清爽，`ps` 看不到；
>   ★★★★ 但 `.mylogin.cnf` 是**混淆不是加密**，官方明說擋不住有心人。
> - `MYSQL_PWD` 環境變數：★★★ **不建議** —— `/proc/<pid>/environ` 讀得到，
>   子程序會繼承，官方手冊列為不安全。
> 見「進階應用 → 密碼不要進 shell history 與 ps 輸出」。
>
> **Q8.** ★★★★ 處理順序：
> 【1】先確認事實：`SELECT VERSION();` 與
> `SELECT PLUGIN_NAME,PLUGIN_STATUS FROM information_schema.plugins WHERE PLUGIN_NAME LIKE '%password%';`
> 【2】確認用戶端版本：`php -r 'echo PHP_VERSION;'` —— PHP 7.4 以後 mysqlnd 對
> `caching_sha2_password` 支援穩定，7.1 以前不支援。
> 【3】**優先升級 PHP／驅動**，這是唯一能長期存活的解（MySQL 9.x 已完全移除
> `mysql_native_password`，退回的做法在下次升級時會再爆一次）。
> 【4】真的卡住才單一帳號退回：
> `ALTER USER 'legacy'@'10.0.1.%' IDENTIFIED WITH mysql_native_password BY '...';`
> MySQL 8.4 還要先在設定檔加 `mysql_native_password=ON` 並重啟。
> ★★★ 伺服器端「預設外掛」的設定項名稱在不同版本不同，請以你安裝版本的官方手冊為準。
> 見「基礎操作 → 認證外掛相容性」。
>
> **Q9.** ★★★ 這不是密碼錯誤，是**觸發了 `FAILED_LOGIN_ATTEMPTS` 的暫時鎖定**。
> 先查「是誰在錯」而不是急著解鎖：
> 【1】`SELECT user,host,db,command FROM information_schema.processlist;` 看有無異常來源。
> 【2】檢查 `10.0.1.20` 是哪台機器 —— 若是報表伺服器，八成是某支腳本存著舊密碼在重試。
> 【3】翻系統日誌（`/var/log/mysql/error.log`）確認嘗試頻率；
> 若來源不明或頻率極高，視為暴力破解事件，走 [[04-備份災難復原與入侵應變]]。
> 【4】排除原因後才解鎖：`ALTER USER 'ro_hr'@'10.0.1.%' ACCOUNT UNLOCK;`
> ★★★★ 直接解鎖而不查來源，等於把偵測到的攻擊訊號丟掉。
> 見「常見錯誤與排錯」與「密碼與帳號生命週期」。
>
> **Q10.** ★★★★ 四個步驟，缺一不可：
> 【1】**改前快照**（這份輸出就是回滾腳本，確認非空再繼續）：
> `sudo mysql -N -B -e "SHOW GRANTS FOR 'app_hr'@'127.0.0.1';" | sed 's/$/;/' > /var/backups/mysql-grants/app_hr-$(date +%FT%H%M).sql`
> 【2】**變更**（用 SQL 語句、一次一個帳號，不要直接改 mysql 表）：
> ```sql
> REVOKE ALL PRIVILEGES ON `app_db`.* FROM 'app_hr'@'127.0.0.1';
> GRANT SELECT, INSERT, UPDATE, DELETE ON `app_db`.* TO 'app_hr'@'127.0.0.1';
> ```
> 【3】**用該帳號本人實測讀與寫**（不是用 root 測）：
> `mysql -u app_hr -p -h 127.0.0.1 app_db -e "SELECT COUNT(*) FROM orders;"` 要成功，
> `... -e "CREATE TABLE _t(i INT);"` 要回 `ERROR 1142`；再打健康檢查端點確認 200。
> 【4】**回滾**：`sudo mysql < /var/backups/mysql-grants/app_hr-2026-08-28T0900.sql`
> ★★★ 並留下變更紀錄（誰改、為什麼、核可單號），稽核會問。
> 見「進階應用 → 權限變更的變更管理」與「完整實戰範例」。

---

## 延伸閱讀

- [[01-MySQL-安裝與初始化]] —— `mysql_secure_installation` 實際做了哪四件事，以及 root 的 `auth_socket` 從哪來
- [[07-MySQL-安全強化]] —— 本篇建立的帳號要在這裡加上 `REQUIRE SSL`、收斂 `bind-address`、開稽核日誌
- [[05-MySQL-備份與還原]] —— `backup` 帳號的實際用法、備份檔加密與**還原演練**
- [[06-MySQL-主從複寫]] —— `repl` 帳號怎麼接上複寫，以及為什麼它只需要一個權限
- [[04-MySQL-設定檔與調校]] —— `validate_password`、`activate_all_roles_on_login` 這些參數放哪個設定檔、怎麼安全地改
- [[02-Laravel-Nginx與PHP-FPM設定]] —— `.env` 的 `DB_HOST` / `DB_USERNAME` 與本篇帳號的對應
- [[02-密碼與帳號管理實務]] —— 機關的密碼原則、離職與異動帳號清理流程
- [[04-備份災難復原與入侵應變]] —— 憑證外洩或帳號被暴力破解後的應變步驟
- [[09-資安稽核與符合性檢核]] —— 盤點 CSV 要怎麼整理成稽核佐證
- MySQL 8.4 存取控制與權限：<https://dev.mysql.com/doc/refman/8.4/en/access-control.html>
- MySQL 密碼管理（過期、鎖定、歷史）：<https://dev.mysql.com/doc/refman/8.4/en/password-management.html>
- MySQL Roles：<https://dev.mysql.com/doc/refman/8.4/en/roles.html>
- `mysql_config_editor` 與 login-path：<https://dev.mysql.com/doc/refman/8.4/en/mysql-config-editor.html>
