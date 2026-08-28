---
title: "PostgreSQL 安裝與初始化"
desc: "版本選型與 PGDG 套件庫、cluster/database/schema 四層模型、peer 認證、locale 與 encoding 一次定死、pg_createcluster 搬 datadir、交付前驗收腳本"
aliases: [postgres, postgresql安裝, initdb, pg_createcluster, pg_lsclusters, pgdg, peer認證, PGDATA]
tags: [群組/軟體與開發工具, 服務/postgresql, 主題/安裝]
category: 資料庫與資料儲存
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[14-套件管理]]", "[[17-systemd服務管理]]", "[[01-MySQL-安裝與初始化]]"]
updated: 2026-08-28
---

# PostgreSQL 安裝與初始化

> [!abstract] 這篇你會學到
> - 用「**這台機器要活幾年**」這個判準，在 Ubuntu 內建版與 **PGDG 官方套件庫**之間做出可以寫進交付文件的版本選型，並且**指定大版本**安裝而不是聽 apt 決定
> - 把 cluster / database / schema / role **四層模型**一次講清楚 —— 這是 MySQL 出身的人在 PostgreSQL 上撞牆的第一個地方
> - ★★★★ 搞懂 **peer 認證**：為什麼 `psql -U postgres` 在你自己的帳號下必然失敗、為什麼 `sudo -u postgres psql` 才對、以及 `FATAL: role "root" does not exist` 到底在講什麼
> - ★★★★★ 在 **initdb 執行的那一秒**把 **encoding、locale provider、定序、data checksums** 決定對 —— 這四項**建完就不能改**，要改只能重建 cluster 並重灌資料
> - ★★★★ 用 **`pg_createcluster`** 把 datadir 搬到獨立磁碟（RHEL 是改 `PGDATA` 與 SELinux），而且知道**同一台機器可以同時跑兩個大版本**時，埠號是怎麼分配的
> - 寫出一支 **`pg-provision.sh`** 佈建腳本與 **`pg-postinstall-check.sh`** 驗收腳本，輸出可以直接貼進交付單，並附**改壞了怎麼回去**的回滾步驟

## 前置知識

- [[14-套件管理]] — apt / dnf 的第三方套件庫、`purge` 與 `remove` 的差別
- [[17-systemd服務管理]] — `systemctl`、template unit（`postgresql@17-main.service` 這種寫法）、`journalctl -u`
- [[15-磁碟分割與掛載]] — datadir 要放獨立磁碟或 LVM 時需要
- [[28-時間同步NTP與chrony]] — 資料庫時間對不上，稽核紀錄就沒有價值
- [[01-MySQL-安裝與初始化]] — ★★★ 本篇大量與它對照。先讀過那篇，這篇會快一倍
- [[01-部署共通觀念]] — 這台機器在整個部署流程裡的位置

---

## 觀念說明

### 機關環境為什麼會冒出 PostgreSQL

本手冊主軸 LXMP 用的是 MySQL，但你遲早會在機關裡遇到 PostgreSQL，通常來自這三個地方：

```text
  ① 採購來的套裝系統          GIS（PostGIS）、開源 ERP、Zabbix、Keycloak、Gitea
                              → 廠商規格書直接寫「需 PostgreSQL 14 以上」

  ② AI / 向量檢索             pgvector 擴充；或與 Qdrant 並存做 metadata 儲存
                              → 見 03-Qdrant 那一章

  ③ 新開發專案                Laravel / Nuxt 團隊選 PostgreSQL 當預設
                              → 見 03-範例-Nuxt與PostgreSQL
```

★★★★ 這三種來源的共同點是：**版本是別人決定的，你只能配合**。
所以本篇第一個重點不是「怎麼裝」，是**「怎麼裝到指定的那個大版本」** ——
`apt install postgresql` 會裝到發行版當下的預設版本，而那通常**不是**規格書要的版本。

---

### ★★★★★ 四層模型：cluster / database / schema / role

MySQL 出身的人在 PostgreSQL 上第一個撞牆點就是這裡。MySQL 的 `database` 幾乎等於一個資料夾，
跨庫查詢 `SELECT * FROM a.t1 JOIN b.t2` 是家常便飯；**PostgreSQL 不行**。

```text
┌─────────────────────────────────────────────────────────────────────┐
│ cluster（叢集）  = 一個 postgres 主行程 + 一個 datadir + 一個埠      │
│   /var/lib/postgresql/17/main   listen 5432                         │
│                                                                     │
│   ├── role（角色）★ 全 cluster 共用，不屬於任何 database             │
│   │     postgres / appuser / bkpuser / readonly                     │
│   │                                                                 │
│   ├── database: postgres     ← 管理用的預設庫，不要拿來放業務資料    │
│   ├── database: template0    ★★★ 唯讀樣板，救命用，不要動           │
│   ├── database: template1    ← CREATE DATABASE 的預設來源           │
│   └── database: appdb        ← 你的業務庫
│         ├── schema: public   ← 預設 schema
│         ├── schema: audit    ← 稽核表放這裡
│         └── schema: reporting
└─────────────────────────────────────────────────────────────────────┘
```

| 概念 | MySQL 的對應物 | ★ 差在哪裡（會咬人的地方） |
| --- | --- | --- |
| **cluster** | 沒有對應物 | ★★★★ MySQL 一個 instance 一個埠；PostgreSQL 也是，但 **Debian 系可以同機跑多個 cluster**，埠自動從 5432 往上排 |
| **database** | `database` | ★★★★ **不能跨 database 查詢**。要跨就得用 `dblink`／`postgres_fdw`，或一開始就設計成同庫不同 schema |
| **schema** | ≈ MySQL 的 `database` | ★★★★ MySQL 的「庫」在 PostgreSQL 通常應該對到 **schema**，不是 database |
| **role** | `user` | ★★★ PostgreSQL 的 role **可以當使用者也可以當群組**，且**屬於 cluster 不屬於 database** |
| 連線目標 | `mysql -u u -p` 進去再 `USE db` | ★★★★ **連線時就必須指定 database**，沒有 `USE` 這種指令（psql 用 `\c` 是重新連線） |

> [!warning] ★★★★ 遷移時最常見的設計錯誤
> 把 MySQL 的十個 database 一對一搬成 PostgreSQL 的十個 database，
> 然後才發現報表要跨庫 JOIN —— 這時候只剩兩條路：**全部重來變成 schema**，或是裝 `postgres_fdw` 硬撐。
> ★★★★ 規劃時的判準很簡單：**「這些資料以後會不會被一起查？」會，就放同一個 database 的不同 schema。**

---

### ★★★★★ 裝完當下的六個決定，會鎖住未來三年

這張表是本篇存在的理由。**打勾的那三項在 `initdb` 執行之後就不能改了**，要改只能重建 cluster。

| 裝完當下的決定 | 建完還能不能改 | 選錯的後果 |
| --- | --- | --- |
| **版本／來源** ★★★ | 能（但要 `pg_upgrade`／dump-restore） | 兩年後沒有安全更新，或廠商系統不支援 |
| **encoding（字元集）** ★★★★★ | **不能** | 中文變亂碼；`SQL_ASCII` 的庫連 `\copy` 出來都是垃圾。只能整庫重匯 |
| **locale / 定序** ★★★★★ | **不能**（PG 15+ 可用 ICU 在 database 層繞過） | 中文排序錯亂、`LIKE 'abc%'` 不吃索引 |
| **data checksums** ★★★★ | **不能**（要 `pg_checksums` 離線開啟） | 磁碟默默壞了你不會知道，備份把壞資料一起備走 |
| **datadir 位置** ★★★ | 能（要停機搬） | 系統碟爆滿 → ★★★★★ **PostgreSQL 會 PANIC 停機** |
| **認證方式（pg_hba）** ★★★★ | 能（reload 即可） | trust 留著 = 任何人都能當 superuser，資安通報等級 |

> [!note] 這篇不談什麼
> `pg_hba.conf` 的比對順序與各認證方式細節 → [[04-PostgreSQL-設定檔與pg_hba]]（★★★★ 那篇才是重頭戲）；
> 角色與權限設計 → [[02-PostgreSQL-角色與權限]]；psql 操作 → [[03-psql-操作與常用指令]]；
> SQL 語法 → [[03-SQL基礎操作]]（**PostgreSQL 的 SQL 不重講，那篇通用**）；
> 備份與 PITR → [[05-PostgreSQL-備份與還原]]。**本篇只負責把地基打對。**

---

### ★★★★ 版本選型：判準是「規格書寫什麼」＋「這台要活幾年」

PostgreSQL 社群政策很單純：**每個大版本支援 5 年**，每年 9 月出一個新大版本，
11 月的第二個星期四統一淘汰最舊的那一版。以下是 **2026-08 查詢的結果**，佈建前務必自己再確認：

| 大版本 | 釋出 | 社群支援到 | 適用情境 | 建議 |
| --- | --- | --- | --- | --- |
| **18** | 2025-09 | 2030-11 | 新建案、Ubuntu 26.04 內建 | ★★★★ **2026 之後的新機首選**；★★★ 注意 `initdb` **預設開啟 data checksums** |
| **17** | 2024-09 | 2029-11 | 目前最穩的主流選擇 | ★★★★ **本篇主線**。生態（擴充、備份工具、監控）支援最完整 |
| **16** | 2023-09 | 2028-11 | **Ubuntu 24.04 內建版** | ★★★ 不想加第三方套件庫就用它，但要在文件寫明「2028 到期」 |
| **15** | 2022-10 | 2027-11 | 既有系統 | ★★ 新建案不要選 |
| **14** | 2021-09 | **2026-11-12** | 既有系統 | ★★★★★ **三個月後就沒有安全更新**，接手到這種機器要立刻排升級 |
| 13 以下 | — | 已 EOL | — | ★★★★★ 已無安全更新，屬於資安缺失，必須列管 |

```bash
# ★★ 自己查一次，不要相信任何文件裡寫死的版本號
apt-cache policy postgresql postgresql-17
```

預期輸出（Ubuntu 24.04，尚未加 PGDG 套件庫）：

```text
postgresql:
  已安裝：(無)
  候選：  16+257build1.1              # ★★★ 這行才是 apt install postgresql 會裝到的東西
postgresql-17:
  已安裝：(無)
  候選：  (無)                        # ★★★★ 沒有 PGDG 套件庫，就裝不到 17
```

★★★★ **兩個結論**：
① `apt install postgresql` 在 Ubuntu 24.04 上會給你 **16**，在 26.04 上會給你 **18** ——
   **同一行指令在兩台機器裝出不同大版本**，這是交付事故的常見來源；
② 要指定版本就**必須加 PGDG 官方套件庫**，並且永遠寫 `postgresql-17` 而不是 `postgresql`。

> [!tip] ★★★ 兩條路線怎麼選（寫進交付文件的說法）
> - **內建版（`postgresql`）**：安全更新走 Ubuntu 的 SRU 流程，跟系統整體支援綁在一起，
>   `unattended-upgrades` 直接涵蓋。適合「這台就是要跟著 OS 生命週期走」的機關標準機。
> - **PGDG（`postgresql-17`）**：跟上游同版號，小版本更新最快，**多版本可並存**，
>   `pg_upgrade` 跨版本升級的工具鏈完整。適合有指定版本需求、或壽命長於 OS 的專案。
> - ★★★★ **不要混用**：同一台機器同時裝了內建版與 PGDG 版，`apt` 的版本比較會讓你在某次
>   `apt upgrade` 時被無聲換版。真的要並存，請用 pinning 並在文件中寫明。

---

### 套件名、服務名、路徑對照

★★★★ 這張表是本篇最常被回頭查的一張。**Debian 系與 RHEL 系在 PostgreSQL 上的差異，比 MySQL 大得多** ——
Debian 系有一整套 `postgresql-common` 的 cluster 管理工具，RHEL 系完全沒有。

| 項目 | Ubuntu / Debian（主線） | RHEL 系（Rocky / AlmaLinux，PGDG） |
| --- | --- | --- |
| 套件名 | `postgresql-17`、`postgresql-client-17` | `postgresql17-server`、`postgresql17` |
| **服務名** ★★★★ | `postgresql.service`（**空殼**）＋ **`postgresql@17-main.service`**（真正的） | **`postgresql-17.service`** |
| **設定檔目錄** ★★★★ | **`/etc/postgresql/17/main/`**（**與資料分開**） | **`/var/lib/pgsql/17/data/`**（**在 datadir 裡面**） |
| 資料目錄 | `/var/lib/postgresql/17/main` | `/var/lib/pgsql/17/data` |
| 主設定檔 | `/etc/postgresql/17/main/postgresql.conf` | `/var/lib/pgsql/17/data/postgresql.conf` |
| 認證設定 | `/etc/postgresql/17/main/pg_hba.conf` | `/var/lib/pgsql/17/data/pg_hba.conf` |
| 日誌 | `/var/log/postgresql/postgresql-17-main.log` | `/var/lib/pgsql/17/data/log/postgresql-*.log` |
| socket | `/var/run/postgresql/.s.PGSQL.5432` | `/var/run/postgresql/`（PGDG 另建 `/tmp` 相容連結） |
| 執行檔 | `/usr/lib/postgresql/17/bin/`（**不在 PATH**） | `/usr/pgsql-17/bin/`（**不在 PATH**） |
| **cluster 管理工具** ★★★★ | **`pg_lsclusters` / `pg_createcluster` / `pg_ctlcluster` / `pg_dropcluster` / `pg_conftool`** | **完全沒有**，只能自己 `initdb` |
| 初始化時機 | **裝完自動建好 `main` cluster 並啟動** | **裝完不會初始化**，要手動 `postgresql-17-setup initdb` |
| 強制存取控制 | AppArmor（PostgreSQL 預設無強制 profile） | ★★★★ **SELinux**：`postgresql_db_t`，搬 datadir 必踩 |
| 作業系統帳號 | `postgres`（`/var/lib/postgresql`） | `postgres`（`/var/lib/pgsql`） |

> [!warning] ★★★★ `systemctl start postgresql` 成功不代表資料庫起來了
> Ubuntu 的 `postgresql.service` 是一個 **`Type=oneshot` 的空殼**，它只負責把各個 cluster 的
> `postgresql@<ver>-<cluster>.service` 拉起來。**即使底下的 cluster 全部啟動失敗，
> `systemctl status postgresql` 還是可能顯示 `active (exited)`。**
> ★★★★ **判斷資料庫到底有沒有活著，一律看 `pg_lsclusters` 的 `Status` 欄**，不要看 `systemctl status postgresql`。

---

### ★★★ MySQL 使用者的速成對照

| 你在 MySQL 做的事 | PostgreSQL 的對應做法 |
| --- | --- |
| `sudo mysql`（auth_socket） | ★★★★ `sudo -u postgres psql`（**peer** 認證，概念相同） |
| `mysql -u root -p` | `psql -U postgres -h 127.0.0.1`（**要先設密碼並改 pg_hba**） |
| `SHOW DATABASES;` | `\l` |
| `USE db;` | ★★★★ `\c db`（**是重新連線**，不是切換） |
| `SHOW TABLES;` | `\dt` |
| `SHOW VARIABLES LIKE 'x';` | `SHOW x;` 或 `SELECT * FROM pg_settings WHERE name='x';` |
| `SET GLOBAL x = y;` | ★★★ `ALTER SYSTEM SET x = y;` ＋ reload（**會寫進 `postgresql.auto.conf`**） |
| `my.cnf` | `postgresql.conf` ＋ `postgresql.auto.conf` ＋ `conf.d/` |
| `mysql.user` 表 | `pg_roles` / `pg_authid` |
| 沒有對應 | ★★★★ **`pg_hba.conf`** —— MySQL 把 host 條件寫在帳號裡，PostgreSQL 拆成獨立的比對檔 |
| `mysql_secure_installation` | ★★★★ **沒有對應工具**，加固要自己做（本篇「安全性注意事項」） |

---

## 環境準備與安裝

### 安裝前的三件事

```bash
lsb_release -ds && uname -m           # 【1】OS 版本與架構
df -h / /var /data 2>/dev/null        # 【2】★★★★ pg_wal 寫滿 = 資料庫 PANIC 停機
timedatectl                           # 【3】★★★★ 時間錯，稽核紀錄就是錯的
locale                                # 【4】★★★★★ initdb 會直接沿用這裡的值
```

預期輸出：

```text
Ubuntu 24.04.3 LTS
x86_64
/dev/sda2        48G  6.2G   40G   14% /
/dev/sdb1       500G   28K  475G    1% /data       # ★★★ 有獨立資料碟就用它當 datadir
               Local time: 五 2026-08-28 09:14:22 CST
                Time zone: Asia/Taipei (CST, +0800)
System clock synchronized: yes                     # ★★★★ 這行是 no 就先處理 NTP
LANG=en_US.UTF-8                                   # ★★★★★ 這行決定 initdb 的 locale
LC_ALL=
```

> [!danger] ★★★★★ `locale` 輸出裡出現 `POSIX`、`C`、或空值時不要往下裝
> Debian 系的 `pg_createcluster` 會**沿用當下 shell 的 locale** 來 `initdb`。
> 如果你是用 `ssh` 帶著客戶端 locale 連進去（`SendEnv LANG LC_*`），或機器根本沒產生任何 UTF-8 locale，
> 就會建出一個 **`SQL_ASCII` 或 `C` 的 cluster**，中文從此存進去是亂碼，而且**建完不能改**。
> 先修好再裝：
> ```bash
> sudo locale-gen en_US.UTF-8 zh_TW.UTF-8
> sudo update-locale LANG=en_US.UTF-8
> ```
> ★★★ 本篇的佈建腳本一律**明確帶 `--locale` 與 `-E UTF8`**，不依賴環境變數。

---

### 路線 A：Ubuntu 內建版（最省事，版本由 OS 決定）

```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
```

★★★ `postgresql-contrib` 提供 `pg_stat_statements`、`pgcrypto`、`postgres_fdw` 等官方擴充，
**幾乎一定會用到，一起裝**。裝完 Debian 系會**自動建好一個叫 `main` 的 cluster 並啟動**：

```bash
pg_lsclusters
```

預期輸出：

```text
Ver Cluster Port Status Owner    Data directory              Log file
16  main    5432 online postgres /var/lib/postgresql/16/main /var/log/postgresql/postgresql-16-main.log
```

★★★★ **`Status` 欄是 `online` 才算真的起來**。其他可能值：`down`（沒起來）、
`online,recovery`（正在做 recovery 或是 standby）。

---

### 路線 B：PGDG 官方套件庫（指定大版本，本篇主線）

**官方提供的自動化做法**（會自動判斷 codename、寫入 deb822 格式的來源檔）：

```bash
sudo apt install -y postgresql-common
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh
```

腳本會問一次要不要繼續，按 Enter 即可。預期輸出（節錄）：

```text
This script will enable the PostgreSQL APT repository on apt.postgresql.org on
your system. The distribution codename used will be noble-pgdg.
Press Enter to continue, or Ctrl-C to abort.
...
Reading package lists... Done
```

> [!tip] ★★★ 不能對外連網、或要寫進自動化腳本時的手動做法
> 這是官方文件的 deb822 寫法，**金鑰放在 `/usr/share/postgresql-common/pgdg/` 而不是 `/etc/apt/keyrings/`**，
> 這樣 `pgdg-keyring` 套件才能接手輪替金鑰：
> ```bash
> sudo apt install -y curl ca-certificates
> sudo install -d /usr/share/postgresql-common/pgdg
> sudo curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
>   https://www.postgresql.org/media/keys/ACCC4CF8.asc
>
> . /etc/os-release                                  # ★★ 取得 codename，例如 noble
> sudo tee /etc/apt/sources.list.d/pgdg.sources >/dev/null <<EOF
> Types: deb
> URIs: https://apt.postgresql.org/pub/repos/apt
> Suites: ${VERSION_CODENAME}-pgdg
> Components: main
> Signed-By: /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
> EOF
> sudo apt update
> ```
> ★★★ 金鑰指紋是 `B97B 0AFC AA1A 47F0 44F2  44A0 7FCC 7D46 ACCC 4CF8`（key id `ACCC4CF8`），
> 離線環境請自行核對。第三方套件庫的通用管理原則見 [[14-套件管理]]。

裝**指定大版本**：

```bash
sudo apt install -y postgresql-17 postgresql-contrib-17 postgresql-client-17
```

驗證：

```bash
pg_lsclusters
psql --version
sudo -u postgres psql -c 'SELECT version();'
```

預期輸出：

```text
Ver Cluster Port Status Owner    Data directory              Log file
17  main    5432 online postgres /var/lib/postgresql/17/main /var/log/postgresql/postgresql-17-main.log

psql (PostgreSQL) 17.6 (Ubuntu 17.6-1.pgdg24.04+1)      # ★★★ pgdg 字樣代表來源正確

                                       version
-------------------------------------------------------------------------------------
 PostgreSQL 17.6 (Ubuntu 17.6-1.pgdg24.04+1) on x86_64-pc-linux-gnu, compiled by ...
```

> [!warning] ★★★★ 如果原本已經裝過內建版，現在會有**兩個 cluster**
> ```text
> Ver Cluster Port Status Owner    Data directory
> 16  main    5432 online postgres /var/lib/postgresql/16/main     # ★★★★ 佔著 5432
> 17  main    5433 online postgres /var/lib/postgresql/17/main     # ★★★★ 被推到 5433
> ```
> 於是你 `psql` 連上去、`SELECT version()` 顯示 16，明明剛裝了 17 —— 因為 **`psql` 預設連 5432**。
> 處置方式見下方「多版本並存」。★★★★ **交付前一定要確認應用程式連的是哪一個埠。**

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> RHEL 系**沒有 `postgresql-common` 那套 cluster 工具**，流程完全不同：套件庫 → 停用系統模組 →
> 安裝 → **手動初始化** → 啟動。少了「手動初始化」這步，服務會起不來。
>
> ```bash
> # 【1】加入 PGDG 套件庫（EL9 / x86_64）
> sudo dnf install -y https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm
>
> # 【2】★★★★ 停用系統內建的 postgresql 模組，否則 dnf 會優先給你 AppStream 的版本
> sudo dnf -qy module disable postgresql
>
> # 【3】安裝指定大版本
> sudo dnf install -y postgresql17-server postgresql17-contrib
>
> # 【4】★★★★ 手動初始化（Ubuntu 是自動做掉的，這裡不做就沒有 datadir）
> sudo /usr/pgsql-17/bin/postgresql-17-setup initdb
>
> # 【5】啟動並設定開機自啟
> sudo systemctl enable --now postgresql-17
> ```
>
> ★★★★ **要指定 encoding / locale，必須在第【4】步之前設環境變數**，因為 `postgresql-17-setup`
> 不吃 `--locale` 參數：
> ```bash
> sudo PGSETUP_INITDB_OPTIONS="-E UTF8 --locale=en_US.UTF-8 --data-checksums" \
>   /usr/pgsql-17/bin/postgresql-17-setup initdb
> ```
>
> | 差異項 | 說明 |
> | --- | --- |
> | 設定檔位置 ★★★★ | 在 **datadir 裡面**（`/var/lib/pgsql/17/data/postgresql.conf`），不是 `/etc` |
> | 執行檔 ★★★ | `/usr/pgsql-17/bin/`，**不在 PATH**。要用 `psql` 得自己加或用完整路徑 |
> | 預設 pg_hba ★★★ | 版本間有差（`ident` / `md5` / `scram-sha-256`），**開檔確認，不要假設** |
> | 搬 datadir ★★★★ | 要改 systemd drop-in 的 `Environment=PGDATA=...`，**而且要處理 SELinux** |
> | 多版本並存 | 可以（`postgresql16-server` 與 `postgresql17-server` 並存），但埠要自己在 `postgresql.conf` 改 |
>
> ★★★ 兩系差異的通盤整理見 [[01-Ubuntu與RHEL差異總表]]。

---

### ★★★★ peer 認證：`psql -U postgres` 為什麼一定失敗

這是 PostgreSQL 新手卡最久的地方，對應 MySQL 的 `auth_socket`（見 [[01-MySQL-安裝與初始化]]）。

Debian 系裝完後的 `pg_hba.conf` 前幾行長這樣：

```bash
sudo grep -vE '^\s*#|^\s*$' /etc/postgresql/17/main/pg_hba.conf
```

預期輸出：

```text
local   all             postgres                                peer
local   all             all                                     peer
host    all             all             127.0.0.1/32            scram-sha-256
host    all             all             ::1/128                 scram-sha-256
```

★★★★ **`peer` 的規則只有一句話：連線端的作業系統使用者名稱，必須等於你要登入的資料庫角色名稱。**
它**完全不檢查密碼**。所以：

```bash
# ★ 情境 A：你的 OS 帳號是 ops
psql -U postgres
```

```text
psql: error: connection to server on socket "/var/run/postgresql/.s.PGSQL.5432" failed:
FATAL:  Peer authentication failed for user "postgres"     # ★★★★ OS 是 ops，要登入 postgres，對不上
```

```bash
# ★ 情境 B：切成 postgres 這個 OS 帳號再連（★★★★ 正確做法）
sudo -u postgres psql
```

```text
psql (17.6 (Ubuntu 17.6-1.pgdg24.04+1))
Type "help" for help.

postgres=#                                                  # ★★★ 提示符尾巴是 # 代表是 superuser
```

```bash
# ★ 情境 C：直接用 sudo（OS 身分變成 root）
sudo psql
```

```text
psql: error: connection to server on socket "/var/run/postgresql/.s.PGSQL.5432" failed:
FATAL:  role "root" does not exist                          # ★★★★ peer 過了！但 root 這個角色不存在
```

★★★★ **`Peer authentication failed` 與 `role ... does not exist` 是兩個完全不同的階段**：
前者是「身分對不上」，後者是「身分對上了，但資料庫裡沒有這個角色」。
判斷口訣：**看到 `role ... does not exist`，代表 peer 已經通過，問題在角色不存在。**

```bash
# ★★★ 補充：psql 在不指定資料庫時，預設連「與角色同名的 database」
sudo -u postgres psql -U appuser
```

```text
psql: error: FATAL:  database "appuser" does not exist       # ★★★ 不是密碼問題，是沒帶 -d
```

正確寫法是 `psql -U appuser -d appdb`。認證方式的完整比較（trust / peer / scram-sha-256 / mdz / cert）
與 `pg_hba.conf` 的**比對順序**，是 [[04-PostgreSQL-設定檔與pg_hba]] 的主題，本篇只讓你能連進去。

---

### 第一次登入的健康檢查清單

★★★★ 接手任何一台 PostgreSQL，這一段是標準開場。三分鐘內產出現況摘要：

```bash
sudo -u postgres psql <<'SQL'
SELECT version();
SHOW data_directory;
SHOW config_file;
SHOW hba_file;
SHOW listen_addresses;
SHOW port;
SHOW password_encryption;
SHOW data_checksums;
SHOW timezone;
SELECT datname, pg_encoding_to_char(encoding) AS enc, datcollate, datctype
  FROM pg_database ORDER BY 1;
SELECT rolname, rolsuper, rolcanlogin FROM pg_roles WHERE rolcanlogin ORDER BY 1;
SQL
```

預期輸出（節錄，這是一台**設定正確**的機器）：

```text
 PostgreSQL 17.6 (Ubuntu 17.6-1.pgdg24.04+1) on x86_64-pc-linux-gnu ...
 data_directory | /var/lib/postgresql/17/main
 config_file    | /etc/postgresql/17/main/postgresql.conf
 hba_file       | /etc/postgresql/17/main/pg_hba.conf
 listen_addresses | localhost                 # ★★★★ 是 * 就要檢查防火牆與是否真的需要
 port             | 5432
 password_encryption | scram-sha-256          # ★★★★ 是 md5 就是資安缺失，見安全性章節
 data_checksums      | on                     # ★★★ off 代表磁碟壞了不會被發現
 TimeZone            | Asia/Taipei

  datname  | enc  | datcollate  |  datctype
-----------+------+-------------+-------------
 postgres  | UTF8 | en_US.UTF-8 | en_US.UTF-8   # ★★★★★ 這欄是 SQL_ASCII 就是重大問題
 template0 | UTF8 | en_US.UTF-8 | en_US.UTF-8
 template1 | UTF8 | en_US.UTF-8 | en_US.UTF-8
```

| 檢查項 | 看到什麼要警覺 | 星級 |
| --- | --- | --- |
| `pg_encoding_to_char(encoding)` | **`SQL_ASCII`** → 資料已經在累積損傷，且**不能線上修** | ★★★★★ |
| `datcollate` | `C` / `POSIX` → 中文排序會是位元組序 | ★★★★ |
| `password_encryption` | `md5` → 弱雜湊，PG 14 起預設已是 scram | ★★★★ |
| `data_checksums` | `off` → 靜默資料損毀不會被偵測 | ★★★ |
| `listen_addresses` | `*` 且防火牆沒收斂 → 資料庫直接暴露 | ★★★★★ |
| `rolsuper` 為 `t` 的帳號數 | 超過 `postgres` 一個 → 權限失控 | ★★★★ |

---

## 基礎設定

### ★★★★★ encoding、locale、定序 —— initdb 那一秒定死

PostgreSQL 有**三個獨立**的「文字相關設定」，很多人把它們混為一談：

```text
  ┌─ encoding（字元集）──── 位元組怎麼編碼。UTF8 / SQL_ASCII / EUC_TW
  │     ★★★★★ database 建完不能改。錯了 → 中文亂碼
  │
  ├─ locale provider ────── 誰來決定排序規則。libc（預設）/ icu（PG15+）/ builtin（PG17+）
  │     ★★★★ cluster 建完不能改預設值，但 PG15+ 可在 CREATE DATABASE 時個別指定
  │
  └─ LC_COLLATE / LC_CTYPE  實際的排序與字元分類規則。en_US.UTF-8 / C / zh_TW.UTF-8
        ★★★★ 影響 ORDER BY 的結果、以及 LIKE 'abc%' 能不能吃索引
```

| 選擇 | 中文排序 | `LIKE 'abc%'` 走索引 | 建議 |
| --- | --- | --- | --- |
| `--locale=C`（`libc`） | 按 Unicode 碼位，**中文順序無意義** | ★★★ **可以**（預設就吃 B-tree） | 純機器資料、log 表可以 |
| `--locale=en_US.UTF-8`（`libc`） | 英文正確、中文≈碼位序 | ★★★ 需 `text_pattern_ops` 索引 | ★★★★ **通用建議值** |
| `--locale=zh_TW.UTF-8`（`libc`） | 依 glibc 規則 | 同上 | ★★ glibc 版本一升級，排序可能變 → 索引需 `REINDEX` |
| `--locale-provider=icu --icu-locale=zh-TW` | ★★★★ 正確且**版本可控** | 需 `text_pattern_ops` | ★★★★ 有中文排序需求就選這個 |
| `--locale-provider=builtin --builtin-locale=C.UTF-8` | 碼位序 | ★★★ 可以 | ★★★ PG17+，效能最好、跨機器最一致 |

> [!danger] ★★★★★ glibc 升級會讓 libc 定序悄悄改變
> 這是 PostgreSQL 最惡名昭彰的坑：作業系統大版本升級（例如 Ubuntu 22.04 → 24.04）換了 glibc，
> **libc 的定序規則跟著變**，於是既有的 B-tree 索引順序與新規則對不上。
> 症狀是**唯一索引擋不住重複值**、`WHERE` 查不到明明存在的資料 —— 而且**沒有任何錯誤訊息**。
> ★★★★ 兩個處置：
> ① 跨 OS 大版本升級後**一律 `REINDEX DATABASE`**（或至少 reindex 所有 text 欄位的索引）；
> ② 新建案改用 **ICU** 或 **builtin** provider，把定序版本鎖在資料庫裡而不是 OS 裡。
> PG 15+ 會在 `pg_database.datcollversion` 記錄定序版本，不符時啟動日誌會出現
> `WARNING: database "appdb" has a collation version mismatch`。**看到這行不要忽略。**

★★★ 檢查目前 cluster 的設定：

```bash
sudo -u postgres psql -c "\l"
```

預期輸出（PG 17，欄位依版本略有不同）：

```text
   Name    |  Owner   | Encoding | Locale Provider |   Collate   |    Ctype    | Access privileges
-----------+----------+----------+-----------------+-------------+-------------+-------------------
 postgres  | postgres | UTF8     | libc            | en_US.UTF-8 | en_US.UTF-8 |
 template0 | postgres | UTF8     | libc            | en_US.UTF-8 | en_US.UTF-8 | =c/postgres ...
 template1 | postgres | UTF8     | libc            | en_US.UTF-8 | en_US.UTF-8 | =c/postgres ...
```

> [!tip] ★★★★ 建錯了怎麼救（依嚴重度排序）
> 1. **只有某個 database 建錯** → `pg_dump` 出來，`DROP DATABASE`，
>    用 `CREATE DATABASE appdb ENCODING 'UTF8' TEMPLATE template0 LOCALE 'en_US.UTF-8';` 重建再匯回。
>    ★★★ **`TEMPLATE template0` 這句不能省** —— 從 `template1` 複製時不允許改 encoding。
> 2. **整個 cluster 建錯**（`template0` 也是 `SQL_ASCII`） → 只能**重建 cluster**。
>    Debian 系：`pg_dropcluster 17 main --stop` 後重新 `pg_createcluster`（★★★★★ 會刪掉全部資料，先備份）。
> 3. **資料已經以錯誤的 encoding 寫進去** → ★★★★★ **無法自動修**。`SQL_ASCII` 的庫連
>    「這串位元組原本是什麼編碼」都沒有記錄，只能靠人工逐表判斷。**這就是為什麼要在裝的時候就對。**

---

### 監聽位址、埠與連線數

Debian 系請用 `pg_conftool` 改設定，它會處理引號與註解，比 `sed` 安全：

```bash
sudo pg_conftool 17 main show listen_addresses
sudo pg_conftool 17 main set listen_addresses "'localhost'"
sudo pg_conftool 17 main show port
```

預期輸出：

```text
listen_addresses = localhost
port = 5432
```

★★★★ **預設就是 `localhost`，這是正確的預設值，不要為了「先讓它連得上」改成 `'*'`。**
應用程式與資料庫同機時走 socket 即可；真要跨機，做法見 [[08-PostgreSQL-安全強化]] 與
[[02-防火牆-ufw基礎與實務]]，**先開防火牆白名單再改 `listen_addresses`**，順序不能反。

| 參數 | 預設 | 改了要 reload 還是 restart | 說明 |
| --- | --- | --- | --- |
| `listen_addresses` | `localhost` | ★★★★ **restart** | `postmaster` context，reload 無效 |
| `port` | `5432` | ★★★★ **restart** | 同上 |
| `max_connections` | `100` | ★★★★ **restart** | 同上；且 standby 的值不能小於 primary |
| `password_encryption` | `scram-sha-256` | ★★ reload | 改了**只影響之後設定的密碼**，舊密碼要重設才會轉換 |
| `log_min_duration_statement` | `-1` | ★★ reload | 慢查詢紀錄，見 [[06-PostgreSQL-效能調校與索引]] |
| `timezone` | `Etc/UTC` 或系統值 | ★★ reload | 見下一節 |

★★★ 怎麼知道某個參數要 reload 還是 restart？**不要背，用查的**：

```bash
sudo -u postgres psql -c \
  "SELECT name, setting, context FROM pg_settings WHERE name IN ('listen_addresses','port','max_connections','timezone');"
```

```text
      name       |  setting  |  context
-----------------+-----------+------------
 listen_addresses | localhost | postmaster   # ★★★★ postmaster = 一定要 restart
 max_connections  | 100       | postmaster
 port             | 5432      | postmaster
 timezone         | Asia/Taipei | user       # ★★ user = 連 reload 都不用，下次連線生效
```

`context` 的意義：`internal`（編譯時決定，不能改）、**`postmaster`（要 restart）**、
**`sighup`（reload 即可）**、`superuser` / `user`（線上就能改）。
★★★★ 這一欄是「改完要不要重啟」的唯一權威來源。

套用設定：

```bash
sudo pg_ctlcluster 17 main reload      # ★★ sighup 類參數
sudo pg_ctlcluster 17 main restart     # ★★★★ postmaster 類參數，會斷線
```

---

### 時區

```bash
sudo pg_conftool 17 main set timezone "'Asia/Taipei'"
sudo pg_conftool 17 main set log_timezone "'Asia/Taipei'"
sudo pg_ctlcluster 17 main reload
sudo -u postgres psql -c "SHOW timezone; SELECT now();"
```

預期輸出：

```text
  TimeZone
-------------
 Asia/Taipei

              now
-------------------------------
 2026-08-28 09:41:12.882+08     # ★★★ 尾巴的 +08 代表時區有生效
```

> [!warning] ★★★★ `timestamp` 與 `timestamptz` 的差別比 MySQL 更關鍵
> - `timestamp`（無時區）：**只是一串數字**，存進去什麼就是什麼，改時區不會位移，
>   但也代表「這筆是幾點」永遠說不清楚。
> - `timestamptz`（有時區）：★★★★ **內部一律以 UTC 儲存**，輸出時依連線的 `TimeZone` 轉換。
>
> ★★★★ **稽核紀錄、事件時間一律用 `timestamptz`**。用 `timestamp` 存事故時間，
> 等到要跟防火牆日誌對時間軸時，你會發現無法判斷那到底是本地時間還是 UTC。
> 這比 MySQL 的 `DATETIME` vs `TIMESTAMP` 更值得注意，因為 PostgreSQL 的 `timestamptz`
> **不會**因為改 `timezone` 參數就整批位移（MySQL 的 `TIMESTAMP` 會）。

---

### 建立第一個資料庫與應用角色

★★★ 這裡只做「能跑起來」的最小設定，權限收斂交給 [[02-PostgreSQL-角色與權限]]。

```bash
DBPASS="$(openssl rand -base64 18)"          # ★★★ 不要自己想密碼
echo "產生的密碼：${DBPASS}"                  # ★★★★ 記下來，等下要寫進 .env

sudo -u postgres psql <<SQL
CREATE ROLE appuser WITH LOGIN PASSWORD '${DBPASS}';
CREATE DATABASE appdb OWNER appuser ENCODING 'UTF8' TEMPLATE template0 LC_COLLATE 'en_US.UTF-8' LC_CTYPE 'en_US.UTF-8';
REVOKE ALL ON DATABASE appdb FROM PUBLIC;
GRANT CONNECT ON DATABASE appdb TO appuser;
SQL
```

預期輸出：

```text
CREATE ROLE
CREATE DATABASE
REVOKE
GRANT
```

> [!danger] ★★★★ `REVOKE ALL ON DATABASE ... FROM PUBLIC` 這行不能省
> PostgreSQL 的預設是**任何能登入的角色都可以連進任何 database**，而且 PG 15 以前
> **`public` schema 對所有人可寫**。也就是說，一個只該讀 A 庫的報表帳號，
> 預設就能連進 B 庫並在 `public` 建表。
> ★★★ PG 15 起 `public` schema 的預設寫入權限已經移除，但 `CONNECT` 權限仍然是全開的。
> 完整的權限收斂流程見 [[02-PostgreSQL-角色與權限]]。

驗證這個帳號真的能用（★★★ **一定要用 TCP 測，不要只用 socket**）：

```bash
PGPASSWORD="${DBPASS}" psql -h 127.0.0.1 -U appuser -d appdb -c '\conninfo'
```

預期輸出：

```text
You are connected to database "appdb" as user "appuser" on host "127.0.0.1"
at port "5432".                                     # ★★★ 看到這行代表 pg_hba 的 host 那列有生效
```

★★★ `PGPASSWORD` 會出現在行程列表與 shell history，**只在測試時用**。
正式做法是 `~/.pgpass`（權限必須 `600`，否則會被靜默忽略）：

```bash
echo "127.0.0.1:5432:appdb:appuser:${DBPASS}" >> ~/.pgpass
chmod 600 ~/.pgpass
psql -h 127.0.0.1 -U appuser -d appdb -c 'SELECT current_database();'
```

```text
 current_database
------------------
 appdb
```

---

## 進階設定與調校

### ★★★★ 用 `pg_createcluster` 把 datadir 建在獨立磁碟

系統碟被 WAL 塞爆會讓 PostgreSQL **PANIC 並停機**（比 MySQL 的唯讀更嚴重），所以有獨立資料碟就一定要用。
★★★★ **正確做法是「刪掉自動建的 cluster、重新建一個」，不是先建再搬** ——
只要資料庫還是空的，重建永遠比搬移安全。

```bash
# 【1】確認自動建的 cluster 是空的（★★★★★ 有資料就不能走這條路，改走下面的搬移）
sudo -u postgres psql -c \
  "SELECT datname, pg_size_pretty(pg_database_size(datname)) FROM pg_database;"
```

```text
  datname  | pg_size_pretty
-----------+----------------
 postgres  | 7717 kB
 template1 | 7565 kB
 template0 | 7429 kB          # ★★★ 只有這三個系統庫，代表可以安全重建
```

```bash
# 【2】★★★★★ 刪掉自動建的 cluster（不可逆，會刪除 datadir 全部內容）
sudo pg_dropcluster 17 main --stop

# 【3】準備新的資料目錄
sudo mkdir -p /data/pgsql/17/main
sudo chown -R postgres:postgres /data/pgsql
sudo chmod 700 /data/pgsql/17/main          # ★★★★ 不是 700 的話 postgres 會拒絕啟動

# 【4】用明確參數重建（★★★ 不依賴環境變數的 locale）
sudo pg_createcluster 17 main \
  --datadir=/data/pgsql/17/main \
  --port=5432 \
  --locale=en_US.UTF-8 \
  --encoding=UTF8 \
  --start \
  -- --data-checksums
```

預期輸出：

```text
Creating new PostgreSQL cluster 17/main ...
/usr/lib/postgresql/17/bin/initdb -D /data/pgsql/17/main --auth-local peer --auth-host scram-sha-256 --data-checksums
The files belonging to this database system will be owned by user "postgres".
...
Ver Cluster Port Status Owner    Data directory        Log file
17  main    5432 online postgres /data/pgsql/17/main   /var/log/postgresql/postgresql-17-main.log
```

★★★★ **`--` 後面的參數會原封不動傳給 `initdb`**。這是加 `--data-checksums`、
`--locale-provider=icu --icu-locale=zh-TW` 這類 `pg_createcluster` 本身沒有的選項的唯一辦法。

驗證：

```bash
sudo -u postgres psql -c "SHOW data_directory; SHOW data_checksums;"
```

```text
    data_directory
---------------------
 /data/pgsql/17/main

 data_checksums
----------------
 on                   # ★★★ PG 17 要自己加 --data-checksums；PG 18 起 initdb 預設就是 on
```

> [!tip] ★★★ data checksums 的取捨
> 開啟後每次讀取 page 都會驗證 checksum，**CPU 成本一般在 2% 以內**，換來的是「磁碟默默寫壞資料時
> 會直接報 `ERROR: invalid page in block ...` 而不是回傳垃圾」。
> ★★★★ 機關的資料庫**一律建議開啟** —— 沒有 checksum 的靜默損毀，會被每天的備份忠實地備份下去，
> 等你發現時三個月的備份全是壞的。
> 已經建好但沒開的 cluster，可以**離線**用 `pg_checksums --enable -D <datadir>` 補開
> （PG 12+，★★★★ 必須完全停機且乾淨關閉，大庫要跑很久，請排維護時段）。

> [!info]- RHEL 系搬 datadir 的做法（沒有 pg_createcluster）
> ```bash
> # 【1】停服務
> sudo systemctl stop postgresql-17
>
> # 【2】搬資料（保留 ACL 與 SELinux 標籤）
> sudo rsync -aXAH /var/lib/pgsql/17/data/ /data/pgsql/17/data/
> sudo chown -R postgres:postgres /data/pgsql
> sudo chmod 700 /data/pgsql/17/data
>
> # 【3】★★★★ 用 systemd drop-in 覆寫 PGDATA，不要直接改 /usr/lib/systemd 下的 unit
> sudo systemctl edit postgresql-17
> ```
> 內容：
> ```ini
> [Service]
> Environment=PGDATA=/data/pgsql/17/data
> ```
> ```bash
> # 【4】★★★★★ SELinux：不做這步服務起不來，而錯誤訊息完全不會提到 SELinux
> sudo semanage fcontext -a -t postgresql_db_t "/data/pgsql(/.*)?"
> sudo restorecon -Rv /data/pgsql
>
> # 【5】啟動並驗證
> sudo systemctl daemon-reload && sudo systemctl start postgresql-17
> sudo -u postgres /usr/pgsql-17/bin/psql -c 'SHOW data_directory;'
> ```
> ★★★★ 起不來時第一個查的是 `sudo ausearch -m AVC -ts recent`，看有沒有 `denied` 紀錄。
> 這與 [[01-MySQL-安裝與初始化]] 裡 AppArmor 的坑是同一類問題，只是換成 SELinux。

---

### ★★★ 多版本、多 cluster 並存

Debian 系最好用的特性：同機可以同時跑好幾個版本，**互不干擾**。

```bash
sudo pg_createcluster 16 legacy --port=5433 --start
pg_lsclusters
```

```text
Ver Cluster Port Status Owner    Data directory                Log file
16  legacy  5433 online postgres /var/lib/postgresql/16/legacy /var/log/postgresql/postgresql-16-legacy.log
17  main    5432 online postgres /data/pgsql/17/main           /var/log/postgresql/postgresql-17-main.log
```

★★★★ **連錯埠是這個特性最大的副作用**。三個保命習慣：

```bash
# 【1】永遠明確指定埠
psql -h 127.0.0.1 -p 5433 -U postgres -c 'SELECT version();'

# 【2】用環境變數鎖定，避免手滑
export PGPORT=5432 PGHOST=/var/run/postgresql

# 【3】★★★ 用 --cluster 指定（postgresql-common 的用戶端包裝）
psql --cluster 16/legacy -c 'SELECT version();'
```

```text
 PostgreSQL 16.10 (Ubuntu 16.10-1.pgdg24.04+1) on x86_64-pc-linux-gnu ...
```

★★★★ **交付前一定要把「應用程式連的是哪個 cluster、哪個埠」寫進交付文件**，
並且在 `.env` 裡明確寫 `DB_PORT`，不要依賴預設值。

停用暫時不需要的 cluster（保留資料但不開機自啟）：

```bash
sudo pg_ctlcluster 16 legacy stop
sudo pg_conftool 16 legacy set --pgcontrol start.conf manual 2>/dev/null || \
  echo "manual" | sudo tee /etc/postgresql/16/legacy/start.conf
```

★★★ `start.conf` 的三個值：`auto`（開機自啟）、`manual`（只能手動）、`disabled`（連手動都擋）。

---

### ★★★★★ 把自己鎖在門外時的救援

情境：你改 `pg_hba.conf` 想收緊，結果把 `local all postgres peer` 那行也刪了，
現在 `sudo -u postgres psql` 也進不去，而且 reload 已經套用。

```text
psql: error: connection to server on socket "/var/run/postgresql/.s.PGSQL.5432" failed:
FATAL:  no pg_hba.conf entry for host "[local]", user "postgres", database "postgres", no encryption
```

★★★★ **關鍵事實：`pg_hba.conf` 是純文字檔，而你有 root。** 所以永遠救得回來：

```bash
# 【1】備份現況（★★★ 先留證，事後要寫報告）
sudo cp /etc/postgresql/17/main/pg_hba.conf /root/pg_hba.conf.broken.$(date +%F_%H%M)

# 【2】把 local peer 那行加回最上面
sudo sed -i '1i local   all   postgres   peer' /etc/postgresql/17/main/pg_hba.conf

# 【3】reload（★★★ pg_hba 只要 reload，不用 restart，服務不會斷）
sudo pg_ctlcluster 17 main reload

# 【4】驗證
sudo -u postgres psql -c 'SELECT current_user;'
```

```text
 current_user
--------------
 postgres
```

> [!danger] ★★★★★ 絕對不要用 `trust` 當救援手段
> 網路上很多文章教你「把 `pg_hba.conf` 全部改成 `trust` 就進得去了」。
> `trust` 的意思是**任何連得到這個埠的人，都可以用任何角色登入，包括 superuser，不需要密碼**。
> 如果同時 `listen_addresses` 是 `*`，那**整個網段的人都是你的資料庫管理員**。
> ★★★★★ 而最常見的事故不是被入侵，是**「改成 trust 之後忘了改回來」** ——
> 半年後資安掃描把它掃出來，變成通報案件。
> 正確做法就是上面的第【2】步：**只加回 `local ... peer` 那一行**，不動其他。
> 各認證方式的差異見 [[04-PostgreSQL-設定檔與pg_hba]]。

★★★ `postgres` 角色的密碼忘了（但 peer 還通）：

```bash
sudo -u postgres psql -c "ALTER ROLE postgres PASSWORD '$(openssl rand -base64 18)';"
```

★★★★ 注意這行密碼會進 shell history 與 `pg_stat_activity`。更安全的做法是用 `psql` 的 `\password`：

```bash
sudo -u postgres psql
```

```text
postgres=# \password postgres
Enter new password for user "postgres":            # ★★★ 不回顯、不進 history、不進 SQL log
Enter it again:
postgres=# \q
```

---

### 解除安裝與重裝的陷阱

★★★★ 與 MySQL 一樣：**`purge` 不會刪資料目錄**。

```bash
sudo apt purge -y postgresql-17 postgresql-client-17
ls /var/lib/postgresql/17/ /etc/postgresql/17/ 2>/dev/null
```

```text
main                    # ★★★★ 資料還在，重裝後 pg_lsclusters 會把舊 cluster 找回來
main
```

★★★★★ 這在交付情境是**重大問題**：你以為「重裝過所以是乾淨的」，實際上舊的角色、舊的密碼、
舊的 `pg_hba.conf`（可能含 `trust`）全部還在。**重裝前一定要檢查**：

```bash
# 正確的完全移除順序（★★★★★ 不可逆，執行前先備份）
sudo pg_dropcluster 17 main --stop        # 【1】先刪 cluster（會刪 datadir 與 /etc 設定）
sudo apt purge -y 'postgresql-17*'        # 【2】再移除套件
sudo rm -rf /var/lib/postgresql /etc/postgresql /etc/postgresql-common   # 【3】收尾
```

> [!warning] ★★★ `postgres` 這個 OS 帳號不會被刪
> `apt purge` 不會刪掉 `postgres` 使用者與 `/var/lib/postgresql` 的家目錄，
> 裡面可能有 `.psql_history`（★★★★ **含你打過的所有 SQL，包括 `ALTER ROLE ... PASSWORD`**）
> 與 `.pgpass`。**機器要退役或轉手前，這兩個檔案必須清掉**，見「安全性注意事項」。

---

## 完整實戰範例

### 情境

新交付一台 Ubuntu 24.04 虛擬機，要求：

| 需求 | 值 |
| --- | --- |
| PostgreSQL 大版本 | **17**（規格書指定，來源必須是 PGDG） |
| 資料目錄 | `/data/pgsql/17/main`（獨立磁碟掛在 `/data`） |
| encoding / locale | `UTF8` / `en_US.UTF-8` |
| data checksums | 開啟 |
| 監聽 | 只有 `localhost`，埠 `5432` |
| 業務庫 / 角色 | `appdb` / `appuser`（隨機密碼） |
| 時區 | `Asia/Taipei` |
| 交付要求 | ★★★★ 要有**可重複執行**的佈建腳本、**驗收輸出**、**回滾步驟** |

### 佈建腳本

```bash
sudo install -m 0755 /dev/null /usr/local/bin/pg-provision.sh
sudo nano /usr/local/bin/pg-provision.sh
```

```bash
#!/usr/bin/env bash
# pg-provision.sh — PostgreSQL 17 標準佈建（Ubuntu 24.04 / PGDG）
# 用法：
#   sudo pg-provision.sh            正常佈建
#   sudo pg-provision.sh --rollback 回滾到佈建前（★★★★★ 會刪除 cluster 與資料）
set -euo pipefail

PGVER="${PGVER:-17}"
CLUSTER="${CLUSTER:-main}"
PGDATA_BASE="${PGDATA_BASE:-/data/pgsql}"
PGDATA="${PGDATA_BASE}/${PGVER}/${CLUSTER}"
DBNAME="${DBNAME:-appdb}"
DBUSER="${DBUSER:-appuser}"
PGLOCALE="${PGLOCALE:-en_US.UTF-8}"
PGPORT_WANT="${PGPORT_WANT:-5432}"
SECRET_FILE="/root/${DBNAME}-db.env"
STAMP="$(date +%F_%H%M%S)"

log()  { printf '\033[1;34m[%s]\033[0m %s\n' "$(date +%T)" "$*"; }
ok()   { printf '\033[1;32m  OK\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[FATAL]\033[0m %s\n' "$*" >&2; exit 1; }

# ── 0. 前置檢查 ────────────────────────────────────────────────
preflight() {
  log "前置檢查"
  [[ $EUID -eq 0 ]] || die "請用 sudo 執行"
  [[ -r /etc/os-release ]] || die "找不到 /etc/os-release"
  . /etc/os-release
  [[ "${ID}" == "ubuntu" || "${ID}" == "debian" ]] || die "本腳本只支援 Ubuntu/Debian，偵測到 ${ID}"

  # ★★★★ locale 必須存在，否則 initdb 會建出 C 或 SQL_ASCII 的 cluster
  if ! locale -a 2>/dev/null | grep -qiE "^${PGLOCALE//-/}$|^${PGLOCALE}$|^en_US\.utf8$"; then
    log "產生 locale ${PGLOCALE}"
    locale-gen "${PGLOCALE}" >/dev/null
    update-locale LANG="${PGLOCALE}"
  fi
  ok "locale ${PGLOCALE} 可用"

  # ★★★★ 資料碟空間：低於 20G 直接擋下，不要等 PANIC 才發現
  local avail
  avail=$(df -BG --output=avail "$(dirname "${PGDATA_BASE}")" 2>/dev/null | tail -1 | tr -dc '0-9')
  [[ -n "${avail}" ]] || die "無法判讀 $(dirname "${PGDATA_BASE}") 的可用空間"
  (( avail >= 20 )) || die "可用空間僅 ${avail}G，低於 20G 門檻，請先擴充磁碟"
  ok "可用空間 ${avail}G"

  # ★★★ 時間同步：稽核紀錄的前提
  timedatectl show -p NTPSynchronized --value | grep -q '^yes$' \
    || log "警告：NTP 尚未同步，稽核時間可能不可信（見 28-時間同步NTP與chrony）"
}

# ── 1. PGDG 套件庫 ─────────────────────────────────────────────
add_repo() {
  log "設定 PGDG 套件庫"
  if [[ -f /etc/apt/sources.list.d/pgdg.sources || -f /etc/apt/sources.list.d/pgdg.list ]]; then
    ok "套件庫已存在，略過"
    return
  fi
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postgresql-common curl ca-certificates
  # ★★★ -y 讓官方腳本不互動
  /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
  ok "PGDG 套件庫已加入"
}

# ── 2. 安裝套件 ────────────────────────────────────────────────
install_pkg() {
  log "安裝 postgresql-${PGVER}"
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    "postgresql-${PGVER}" "postgresql-client-${PGVER}" "postgresql-contrib-${PGVER}"
  dpkg -l "postgresql-${PGVER}" | grep -q '^ii' || die "postgresql-${PGVER} 安裝失敗"
  ok "$(psql --version)"
}

# ── 3. 重建 cluster 到獨立磁碟 ─────────────────────────────────
recreate_cluster() {
  log "重建 cluster ${PGVER}/${CLUSTER} → ${PGDATA}"

  if pg_lsclusters -h | awk '{print $1"/"$2}' | grep -qx "${PGVER}/${CLUSTER}"; then
    local cur_dir
    cur_dir="$(pg_lsclusters -h | awk -v v="${PGVER}" -v c="${CLUSTER}" '$1==v && $2==c {print $6}')"
    if [[ "${cur_dir}" == "${PGDATA}" ]]; then
      ok "cluster 已在正確位置，略過重建"
      return
    fi
    # ★★★★★ 只有在確認沒有使用者資料時才敢刪
    local userdb
    userdb=$(su - postgres -c "psql -tAq -p $(pg_lsclusters -h | awk -v v=${PGVER} -v c=${CLUSTER} '$1==v&&$2==c{print $3}') \
      -c \"SELECT count(*) FROM pg_database WHERE datname NOT IN ('postgres','template0','template1');\"" 2>/dev/null || echo "ERR")
    [[ "${userdb}" == "0" ]] || die "cluster ${PGVER}/${CLUSTER} 內有 ${userdb} 個使用者資料庫，拒絕自動刪除。請先備份並手動處理"
    log "刪除空的舊 cluster（原路徑 ${cur_dir}）"
    pg_dropcluster "${PGVER}" "${CLUSTER}" --stop
  fi

  install -d -o postgres -g postgres -m 0700 "${PGDATA}"
  chown -R postgres:postgres "${PGDATA_BASE}"

  pg_createcluster "${PGVER}" "${CLUSTER}" \
    --datadir="${PGDATA}" \
    --port="${PGPORT_WANT}" \
    --locale="${PGLOCALE}" \
    --encoding=UTF8 \
    --start \
    -- --data-checksums \
    || die "pg_createcluster 失敗，請看 /var/log/postgresql/"
  ok "cluster 已建立並啟動"
}

# ── 4. 基礎設定 ────────────────────────────────────────────────
tune_conf() {
  log "套用基礎設定"
  local C="/etc/postgresql/${PGVER}/${CLUSTER}"
  cp -a "${C}/postgresql.conf" "${C}/postgresql.conf.bak.${STAMP}"
  cp -a "${C}/pg_hba.conf"     "${C}/pg_hba.conf.bak.${STAMP}"

  pg_conftool "${PGVER}" "${CLUSTER}" set listen_addresses "'localhost'"
  pg_conftool "${PGVER}" "${CLUSTER}" set timezone "'Asia/Taipei'"
  pg_conftool "${PGVER}" "${CLUSTER}" set log_timezone "'Asia/Taipei'"
  pg_conftool "${PGVER}" "${CLUSTER}" set password_encryption "'scram-sha-256'"
  pg_conftool "${PGVER}" "${CLUSTER}" set log_line_prefix "'%m [%p] %q%u@%d '"
  pg_conftool "${PGVER}" "${CLUSTER}" set log_min_duration_statement 1000   # ★★ 1 秒以上記慢查詢

  pg_ctlcluster "${PGVER}" "${CLUSTER}" restart   # ★★★★ listen_addresses 是 postmaster context
  ok "設定已套用並重啟"
}

# ── 5. 建庫建角色 ──────────────────────────────────────────────
create_db() {
  log "建立 ${DBNAME} / ${DBUSER}"
  local exists
  exists=$(su - postgres -c "psql -tAqc \"SELECT 1 FROM pg_database WHERE datname='${DBNAME}'\"")
  if [[ "${exists}" == "1" ]]; then
    ok "${DBNAME} 已存在，略過（不覆寫既有資料）"
    return
  fi

  local pw; pw="$(openssl rand -base64 18)"
  su - postgres -c "psql -v ON_ERROR_STOP=1" <<SQL || die "建立資料庫失敗"
CREATE ROLE ${DBUSER} WITH LOGIN PASSWORD '${pw}';
CREATE DATABASE ${DBNAME} OWNER ${DBUSER} ENCODING 'UTF8' TEMPLATE template0
  LC_COLLATE '${PGLOCALE}' LC_CTYPE '${PGLOCALE}';
REVOKE ALL ON DATABASE ${DBNAME} FROM PUBLIC;
GRANT CONNECT ON DATABASE ${DBNAME} TO ${DBUSER};
SQL

  # ★★★★ 密碼寫進 600 的檔案，不要留在 stdout 或 history
  umask 077
  cat > "${SECRET_FILE}" <<EOF
DB_CONNECTION=pgsql
DB_HOST=127.0.0.1
DB_PORT=${PGPORT_WANT}
DB_DATABASE=${DBNAME}
DB_USERNAME=${DBUSER}
DB_PASSWORD=${pw}
EOF
  chmod 600 "${SECRET_FILE}"
  ok "憑證已寫入 ${SECRET_FILE}（權限 600）"
}

# ── 6. 驗證 ────────────────────────────────────────────────────
verify() {
  log "驗證"
  local st
  st="$(pg_lsclusters -h | awk -v v="${PGVER}" -v c="${CLUSTER}" '$1==v && $2==c {print $4}')"
  [[ "${st}" == "online" ]] || die "cluster 狀態為 ${st:-不存在}，佈建失敗"

  su - postgres -c "psql -tAq" <<'SQL'
SELECT 'encoding=' || pg_encoding_to_char(encoding) FROM pg_database WHERE datname='template1';
SELECT 'checksums=' || setting FROM pg_settings WHERE name='data_checksums';
SELECT 'listen=' || setting FROM pg_settings WHERE name='listen_addresses';
SELECT 'pwenc=' || setting FROM pg_settings WHERE name='password_encryption';
SQL

  # ★★★ 用 TCP 實際登入一次，確認 pg_hba 與密碼真的可用
  ( set -a; . "${SECRET_FILE}"; set +a
    PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" \
      -U "${DB_USERNAME}" -d "${DB_DATABASE}" -tAqc 'SELECT current_database()' ) \
    || die "應用帳號 TCP 登入失敗，請檢查 pg_hba.conf"
  ok "應用帳號可正常連線"
}

# ── 回滾 ───────────────────────────────────────────────────────
rollback() {
  log "★★★★★ 回滾：將刪除 cluster ${PGVER}/${CLUSTER} 與其全部資料"
  read -r -p "確認請輸入 DELETE：" a
  [[ "${a}" == "DELETE" ]] || die "已取消"
  if pg_lsclusters -h | awk '{print $1"/"$2}' | grep -qx "${PGVER}/${CLUSTER}"; then
    log "先做一份保險 dump 到 /root/"
    su - postgres -c "pg_dumpall -p ${PGPORT_WANT}" > "/root/pg-rollback-dump-${STAMP}.sql" || true
    pg_dropcluster "${PGVER}" "${CLUSTER}" --stop
  fi
  apt-get purge -y -qq "postgresql-${PGVER}" "postgresql-client-${PGVER}" "postgresql-contrib-${PGVER}" || true
  rm -f "${SECRET_FILE}"
  ok "已回滾。保險 dump 在 /root/pg-rollback-dump-${STAMP}.sql"
}

main() {
  if [[ "${1:-}" == "--rollback" ]]; then rollback; exit 0; fi
  preflight
  add_repo
  install_pkg
  recreate_cluster
  tune_conf
  create_db
  verify
  log "完成。憑證：${SECRET_FILE}；設定備份後綴：.bak.${STAMP}"
}
main "$@"
```

### 驗收腳本

★★★ 這一支不改任何東西，只輸出可以貼進交付單的結果。

```bash
sudo install -m 0755 /dev/null /usr/local/bin/pg-postinstall-check.sh
sudo nano /usr/local/bin/pg-postinstall-check.sh
```

```bash
#!/usr/bin/env bash
# pg-postinstall-check.sh — PostgreSQL 交付前驗收（唯讀，不做任何變更）
set -uo pipefail
PGVER="${PGVER:-17}"; CLUSTER="${CLUSTER:-main}"
FAIL=0
chk() { # chk "項目" "實際值" "期望值(regex)" "星級"
  local name="$1" got="$2" want="$3" star="$4"
  if [[ "${got}" =~ ${want} ]]; then
    printf '  [ PASS ] %-28s %s\n' "${name}" "${got}"
  else
    printf '  [ FAIL ] %-28s 實際=%s 期望=%s  %s\n' "${name}" "${got:-<空>}" "${want}" "${star}"
    FAIL=$((FAIL+1))
  fi
}
q() { su - postgres -c "psql -tAqc \"$1\"" 2>/dev/null | tr -d ' '; }

echo "=== PostgreSQL 驗收 $(date '+%F %T') / $(hostname) ==="
chk "cluster 狀態"        "$(pg_lsclusters -h | awk -v v=$PGVER -v c=$CLUSTER '$1==v&&$2==c{print $4}')" '^online$'        '★★★★★'
chk "版本"                "$(q 'SHOW server_version')"                    "^${PGVER}\."                                   '★★★'
chk "encoding"            "$(q "SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname='template1'")" '^UTF8$' '★★★★★'
chk "collate"             "$(q "SELECT datcollate FROM pg_database WHERE datname='template1'")" '^(en_US|C)\.(UTF-8|utf8)$' '★★★★'
chk "data_checksums"      "$(q 'SHOW data_checksums')"                    '^on$'                                         '★★★'
chk "listen_addresses"    "$(q 'SHOW listen_addresses')"                  '^(localhost|127\.0\.0\.1)$'                    '★★★★★'
chk "password_encryption" "$(q 'SHOW password_encryption')"               '^scram-sha-256$'                               '★★★★'
chk "timezone"            "$(q 'SHOW timezone')"                          '^Asia/Taipei$'                                 '★★★'
chk "trust 認證列數"      "$(grep -cE '^[^#]*[[:space:]]trust([[:space:]]|$)' /etc/postgresql/$PGVER/$CLUSTER/pg_hba.conf)" '^0$' '★★★★★'
chk "superuser 帳號數"    "$(q 'SELECT count(*) FROM pg_roles WHERE rolsuper')"  '^1$'                                    '★★★★'
chk "空密碼可登入帳號"    "$(q 'SELECT count(*) FROM pg_authid WHERE rolcanlogin AND rolpassword IS NULL')" '^[01]$'      '★★★★'
chk "datadir 非系統碟"    "$(df --output=target "$(q 'SHOW data_directory')" | tail -1)" '^/data'                        '★★★'
chk "datadir 權限"        "$(stat -c '%a %U' "$(q 'SHOW data_directory')")" '^700 postgres$'                              '★★★★'
chk "NTP 同步"            "$(timedatectl show -p NTPSynchronized --value)" '^yes$'                                        '★★★'
echo "--- 磁碟 ---"; df -h "$(q 'SHOW data_directory')" | tail -1
echo "--- 連線 ---"; ss -lntp 2>/dev/null | grep -E ':(5432|5433)' || echo "  未監聽 TCP（純 socket，符合最小暴露原則）"
echo
[[ ${FAIL} -eq 0 ]] && echo "驗收通過（0 項不符）" || { echo "★★★★ 有 ${FAIL} 項不符，不可交付"; exit 1; }
```

### 執行

```bash
sudo /usr/local/bin/pg-provision.sh
```

預期輸出（節錄）：

```text
[09:20:01] 前置檢查
  OK locale en_US.UTF-8 可用
  OK 可用空間 475G
[09:20:03] 設定 PGDG 套件庫
  OK PGDG 套件庫已加入
[09:21:14] 安裝 postgresql-17
  OK psql (PostgreSQL) 17.6 (Ubuntu 17.6-1.pgdg24.04+1)
[09:21:40] 重建 cluster 17/main → /data/pgsql/17/main
  OK cluster 已建立並啟動
[09:21:58] 套用基礎設定
  OK 設定已套用並重啟
[09:22:03] 建立 appdb / appuser
  OK 憑證已寫入 /root/appdb-db.env（權限 600）
[09:22:05] 驗證
encoding=UTF8
checksums=on
listen=localhost
pwenc=scram-sha-256
  OK 應用帳號可正常連線
[09:22:06] 完成。憑證：/root/appdb-db.env；設定備份後綴：.bak.2026-08-28_092001
```

```bash
sudo /usr/local/bin/pg-postinstall-check.sh
```

```text
=== PostgreSQL 驗收 2026-08-28 09:23:11 / db01 ===
  [ PASS ] cluster 狀態                 online
  [ PASS ] 版本                         17.6
  [ PASS ] encoding                     UTF8
  [ PASS ] collate                      en_US.UTF-8
  [ PASS ] data_checksums               on
  [ PASS ] listen_addresses             localhost
  [ PASS ] password_encryption          scram-sha-256
  [ PASS ] timezone                     Asia/Taipei
  [ PASS ] trust 認證列數               0
  [ PASS ] superuser 帳號數             1
  [ PASS ] 空密碼可登入帳號             0
  [ PASS ] datadir 非系統碟             /data
  [ PASS ] datadir 權限                 700 postgres
  [ PASS ] NTP 同步                     yes
--- 磁碟 ---
/dev/sdb1       500G  152M  475G   1% /data
--- 連線 ---
LISTEN 0  200  127.0.0.1:5432  0.0.0.0:*  users:(("postgres",pid=8812,fd=6))

驗收通過（0 項不符）
```

### 回滾

```bash
sudo /usr/local/bin/pg-provision.sh --rollback
```

```text
[09:31:02] ★★★★★ 回滾：將刪除 cluster 17/main 與其全部資料
確認請輸入 DELETE：DELETE
[09:31:09] 先做一份保險 dump 到 /root/
  OK 已回滾。保險 dump 在 /root/pg-rollback-dump-2026-08-28_093102.sql
```

★★★★ 回滾腳本**先 dump 再刪**，即使操作者按錯也還有一份完整的 `pg_dumpall`。
正式環境的備份策略請走 [[05-PostgreSQL-備份與還原]]，本腳本的 dump 只是保命網，不是備份。

### 驗收檢查表

| # | 檢查項 | 指令 | 預期結果 | 星級 |
| --- | --- | --- | --- | --- |
| 1 | cluster 上線 | `pg_lsclusters` | `Status` 為 `online` | ★★★★★ |
| 2 | 版本正確 | `psql --version` | `17.x`，且字串含 `pgdg` | ★★★ |
| 3 | 來源正確 | `apt-cache policy postgresql-17` | 來源是 `apt.postgresql.org` | ★★★ |
| 4 | encoding | `SELECT pg_encoding_to_char(encoding) FROM pg_database` | 全部 `UTF8` | ★★★★★ |
| 5 | 定序 | `SHOW lc_collate;` | `en_US.UTF-8`（或約定值） | ★★★★ |
| 6 | checksums | `SHOW data_checksums;` | `on` | ★★★ |
| 7 | datadir 位置 | `SHOW data_directory;` | `/data/pgsql/17/main` | ★★★ |
| 8 | datadir 權限 | `stat -c '%a %U' <datadir>` | `700 postgres` | ★★★★ |
| 9 | 監聽範圍 | `ss -lntp \| grep 5432` | 只有 `127.0.0.1:5432` | ★★★★★ |
| 10 | 認證方式 | `grep -v '^#' pg_hba.conf` | **沒有任何 `trust`** | ★★★★★ |
| 11 | 密碼雜湊 | `SHOW password_encryption;` | `scram-sha-256` | ★★★★ |
| 12 | superuser 數量 | `SELECT count(*) FROM pg_roles WHERE rolsuper` | `1` | ★★★★ |
| 13 | 業務帳號可連 | `psql -h 127.0.0.1 -U appuser -d appdb` | 連得上且**只能連 appdb** | ★★★★ |
| 14 | 時區 | `SHOW timezone;` | `Asia/Taipei` | ★★★ |
| 15 | 開機自啟 | `cat /etc/postgresql/17/main/start.conf` | `auto` | ★★★★ |
| 16 | 日誌有內容 | `tail /var/log/postgresql/postgresql-17-main.log` | 有 `database system is ready` | ★★★ |
| 17 | **還原演練** | 見 [[05-PostgreSQL-備份與還原]] | ★★★★★ **沒演練過的備份不算數** | ★★★★★ |
| 18 | 憑證檔權限 | `stat -c '%a' /root/appdb-db.env` | `600` | ★★★★ |

---

## 常見錯誤與排錯

| 現象／錯誤 | 原因 | 解法 |
| --- | --- | --- |
| **`FATAL: Peer authentication failed for user "postgres"`** ★★★★ | `peer` 要求 OS 使用者名稱 = 角色名稱，你現在不是 `postgres` | `sudo -u postgres psql`；**不要改成 `trust`** |
| **`FATAL: role "root" does not exist`** ★★★★ | 用 `sudo psql`，OS 身分是 `root`，peer 通過但無此角色 | 加 `-u postgres`，或明確 `psql -U postgres -d postgres` |
| **`FATAL: database "ops" does not exist`** ★★★ | psql 預設連「與角色同名的 database」 | 補 `-d appdb`；或替該角色建同名庫 |
| **`connection to server on socket "/var/run/postgresql/.s.PGSQL.5432" failed: No such file or directory`** ★★★★ | 服務根本沒起來，或連錯埠 | `pg_lsclusters` 看 `Status`；不是 `online` 就看日誌 |
| **`FATAL: no pg_hba.conf entry for host "10.x.x.x", user "appuser", database "appdb", no encryption`** ★★★★ | `pg_hba.conf` 沒有涵蓋這個來源網段 | 加一列 `host appdb appuser 10.x.x.0/24 scram-sha-256` 後 **reload**；見 [[04-PostgreSQL-設定檔與pg_hba]] |
| **`psql: error: connection to server at "10.x.x.x", port 5432 failed: Connection refused`** ★★★ | `listen_addresses=localhost`（正常）或防火牆擋住 | 先確認真的需要遠端；要開就先加防火牆白名單再改參數並 **restart** |
| **`initdb: error: invalid locale settings; check LANG and LC_* environment variables`** ★★★★ | 系統沒產生該 locale，或 ssh 帶進來的 locale 不存在 | `locale-gen en_US.UTF-8`；★★★ 佈建腳本一律明確帶 `--locale` |
| **`Error: The locale requested by the environment is invalid`（pg_createcluster）** ★★★★ | 同上，`pg_createcluster` 沿用當下 shell 的 locale | 同上；或 `LC_ALL=en_US.UTF-8 pg_createcluster ...` |
| **`ERROR: new encoding (UTF8) is incompatible with the encoding of the template database (SQL_ASCII)`** ★★★★★ | 從 `template1` 複製時不能換 encoding | `CREATE DATABASE ... TEMPLATE template0 ENCODING 'UTF8'`；若 `template0` 也是 `SQL_ASCII` 則**必須重建 cluster** |
| **中文存進去查出來是亂碼，但沒有任何錯誤** ★★★★★ | cluster 是 `SQL_ASCII`，PostgreSQL 不做任何轉碼檢查 | **已損毀的資料無法自動修**；重建 cluster 為 UTF8 後重匯，並逐表人工確認 |
| **`systemctl status postgresql` 顯示 `active (exited)`，但連不上** ★★★★ | `postgresql.service` 是 oneshot 空殼，底下的 cluster 沒起來 | ★★★★ 一律改看 `pg_lsclusters` 與 `systemctl status postgresql@17-main` |
| **`psql` 連上去版本是 16，但明明剛裝 17** ★★★★ | 兩個 cluster 並存，17 被推到 5433 | `pg_lsclusters` 確認埠；用 `-p` 或 `--cluster 17/main` 明確指定 |
| **`FATAL: the database system is starting up`** ★★★ | 上次是非正常關機，正在做 crash recovery | 等它跑完；看日誌的 `redo starts at` 判斷進度，**不要重複 restart** |
| **`could not open directory "...": Permission denied` / 啟動即失敗** ★★★★ | datadir 權限不是 `700 postgres:postgres` | `chown -R postgres:postgres`＋`chmod 700`；RHEL 另查 SELinux `ausearch -m AVC` |
| **`PANIC: could not write to file "pg_wal/xlogtemp.xxx": No space left on device`** ★★★★★ | WAL 所在磁碟寫滿，資料庫直接停機 | 緊急：清 `log/` 或擴充磁碟後啟動；根治：datadir 移獨立碟＋監控，見 [[03-系統監控與告警]] |
| **`FATAL: sorry, too many clients already`** ★★★ | 連線數超過 `max_connections` | 短期調大並 **restart**；長期上連線池，見 [[06-PostgreSQL-效能調校與索引]] |
| **`WARNING: database "appdb" has a collation version mismatch`** ★★★★ | OS 升級換了 glibc，定序規則變了 | `REINDEX DATABASE appdb;` 後 `ALTER DATABASE appdb REFRESH COLLATION VERSION;` |
| **`apt purge` 後重裝，舊角色與舊 `pg_hba.conf` 全在** ★★★★ | `purge` 不刪 `/var/lib/postgresql` 與 `/etc/postgresql` | 重裝前 `pg_lsclusters` 檢查；確認資料歸屬後 `pg_dropcluster` 再 purge |
| **`ALTER SYSTEM SET` 改了參數但沒生效** ★★★ | 該參數是 `postmaster` context，只 reload 不夠 | 查 `pg_settings.context`；是 `postmaster` 就要 `restart` |

### 排查步驟

**【1】cluster 到底有沒有起來（★★★★ 不要看 `systemctl status postgresql`）**

```bash
pg_lsclusters
```

```text
Ver Cluster Port Status Owner    Data directory       Log file
17  main    5432 down   postgres /data/pgsql/17/main  /var/log/postgresql/postgresql-17-main.log
```

看到 `down` → 往【2】；看到 `online` 但連不上 → 跳到【5】；
看到有兩列且埠不同 → 你可能連錯 cluster，跳到【6】。

**【2】看 PostgreSQL 自己的日誌（比 systemd 詳細得多）**

```bash
sudo tail -30 /var/log/postgresql/postgresql-17-main.log
```

```text
2026-08-28 09:44:02.118 CST [9120] FATAL:  data directory "/data/pgsql/17/main" has invalid permissions
2026-08-28 09:44:02.118 CST [9120] DETAIL:  Permissions should be u=rwx (0700) or u=rwx,g=rx (0750).
```

- `invalid permissions` / `Permission denied` → 往【3】
- `could not bind IPv4 address` / `Address already in use` → 往【4】
- `unrecognized configuration parameter` / `syntax error in file` → 往【7】
- 日誌**完全是空的** → 往【8】（多半是 systemd 層就失敗了）

**【3】權限與擁有者**

```bash
sudo stat -c '%a %U:%G %n' /data/pgsql/17/main
```

```text
755 postgres:postgres /data/pgsql/17/main      # ★★★★ 必須是 700 或 750，755 會被拒絕
```

```bash
sudo chmod 700 /data/pgsql/17/main
sudo chown -R postgres:postgres /data/pgsql
sudo pg_ctlcluster 17 main start
```

RHEL 系權限看起來正常卻仍失敗 → **一定是 SELinux**：

```bash
sudo ausearch -m AVC -ts recent | tail -5
```

```text
type=AVC msg=audit(...): avc:  denied  { read } for  pid=9120 comm="postgres"
  name="data" dev="sdb1" ino=12 scontext=system_u:system_r:postgresql_t:s0
  tcontext=unconfined_u:object_r:default_t:s0 tclass=dir       # ★★★★ tcontext 應該是 postgresql_db_t
```

**【4】埠被佔用**

```bash
sudo ss -lntp | grep -E ':543[0-9]'
```

```text
LISTEN 0 200 127.0.0.1:5432 0.0.0.0:* users:(("postgres",pid=7701,fd=6))   # ★★★ 是另一個 cluster 佔著
```

```bash
pg_lsclusters        # 確認 5432 是誰的
```

處置：把新 cluster 改用別的埠（`pg_conftool 17 main set port 5433` 後 restart），
或先停掉舊 cluster。★★★★ **不要 `kill -9` 那個 pid**，那是另一個正在服務的資料庫。

**【5】起來了但連不上：分辨 socket 問題還是認證問題**

```bash
sudo -u postgres psql -c 'SELECT 1'
```

- 成功 → **本機沒問題，是 pg_hba 或網路層**，往【6】
- `Peer authentication failed` → 你不是 `postgres` 這個 OS 帳號，補 `sudo -u postgres`
- `No such file or directory` → socket 不存在，回【1】確認真的 online

**【6】確認你連的是哪一個 cluster**

```bash
psql -h 127.0.0.1 -p 5432 -U postgres -c "SELECT version(), current_setting('data_directory');"
```

```text
 PostgreSQL 16.10 ... | /var/lib/postgresql/16/main    # ★★★★ 果然連到舊的 16
```

★★★ 這一步是「明明裝了 17 卻是 16」的標準解法。確認後在 `.env`／連線字串裡寫死正確的 `-p`。

**【7】設定檔語法錯**

```bash
sudo -u postgres /usr/lib/postgresql/17/bin/postgres \
  -D /data/pgsql/17/main -c config_file=/etc/postgresql/17/main/postgresql.conf 2>&1 | head -5
```

```text
2026-08-28 09:51:30.221 CST [9333] FATAL:  configuration file "/etc/postgresql/17/main/postgresql.conf"
  contains errors                                      # ★★★ 前面幾行會指出是第幾行
2026-08-28 09:51:30.221 CST [9333] LOG:  syntax error in file ".../postgresql.conf" line 64, near token "'"
```

★★★★ 這招是「前台啟動看錯誤」。跑完記得 Ctrl-C，不要讓它以前台身分持續跑。
`ALTER SYSTEM` 寫壞的話，問題會在 `postgresql.auto.conf`，**那個檔不要手改，用
`ALTER SYSTEM RESET <param>;`**，真的進不去才手動編輯。

**【8】日誌是空的：往 systemd 找**

```bash
sudo journalctl -u postgresql@17-main -n 30 --no-pager
```

```text
pg_ctlcluster[9410]: Error: /data/pgsql/17/main is not accessible or does not exist
systemd[1]: postgresql@17-main.service: Failed with result 'exit-code'.
```

★★★★ 記住 unit 名稱是 **`postgresql@<版本>-<cluster>`**，查 `postgresql.service` 什麼都看不到。

**【9】確認資料本身沒壞（開了 checksums 才有意義）**

```bash
sudo -u postgres psql -d appdb -c "SELECT count(*) FROM pg_stat_database WHERE checksum_failures > 0;"
```

```text
 count
-------
     0                # ★★★★ 大於 0 代表磁碟層已經在壞資料，立刻停止寫入並啟動還原程序
```

---

## 安全性注意事項

> [!danger] ★★★★★ 絕對禁止的事項
> - **`pg_hba.conf` 裡出現 `trust`**：任何連得到該埠的人都能以**任何角色**登入，包含 superuser，
>   不需要密碼。配上 `listen_addresses='*'`，等於把整個資料庫送人。
>   ★★★★★ 最常見的事故不是被入侵，是**「臨時改成 trust 忘了改回來」**。
> - **`listen_addresses='*'` 而防火牆沒有白名單**：資料庫 5432 直接暴露在網段上，
>   會被自動化掃描器持續嘗試 `postgres` 帳號密碼。
> - **`ALTER ROLE x PASSWORD 'xxx'` 寫在指令列**：密碼會同時進入
>   ① shell history、② `ps` 的行程列表、③ `pg_stat_activity`、④ 若開了 statement log 就進日誌檔。
>   ★★★★ 用 `psql` 的 `\password` 代替。
> - **把 `postgres` superuser 的密碼給應用程式用**：一次 SQL injection 就等於整台機器失守
>   （superuser 可以用 `COPY ... FROM PROGRAM` 執行系統指令）。
> - **`password_encryption = md5`**：MD5 已被視為不足，PG 14 起預設是 `scram-sha-256`。
>   改成 `scram-sha-256` 之後**舊密碼不會自動轉換**，必須逐一 `\password` 重設。
> - **機器退役／轉手前不清 `/var/lib/postgresql/.psql_history` 與 `.pgpass`**：
>   ★★★★★ 前者含你打過的所有 SQL（包括含個資的 `WHERE id_no = ...`），後者是明文密碼。

**機關情境的具體要求：**

| 要求 | 本篇對應做法 | 星級 |
| --- | --- | --- |
| **最小權限** | 業務帳號不是 superuser、不是 database owner 以外的角色；`REVOKE ALL ... FROM PUBLIC` | ★★★★ |
| **稽核軌跡** | `log_line_prefix` 帶 `%m [%p] %u@%d`，日誌集中收；見 [[02-日誌集中與輪替]] | ★★★★ |
| **時間正確** | `timedatectl` 同步 + `log_timezone='Asia/Taipei'`；時間錯的稽核紀錄在調查時沒有證據力 | ★★★★ |
| **個資保護** | 含個資的欄位不要進 `log_min_duration_statement` 的參數紀錄；備份檔加密。見 [[07-台灣資安法規與個資法]] | ★★★★★ |
| **帳號可歸屬** | ★★★ 每個維運人員用自己的角色，**不共用 `postgres`**；`peer` 讓 `sudo -u postgres` 留下 sudo log | ★★★★ |
| **版本在支援期內** | 本篇「版本選型」表；PG 14 在 2026-11 到期，14 以下已是缺失 | ★★★★ |

★★★ 本篇只做到「不留明顯破口」。TLS 連線、`pgaudit`、資料列層安全（RLS）、
連線加密強制（`hostssl`）這些是 [[08-PostgreSQL-安全強化]] 的範圍。

> [!tip] ★★★ 交付前的三行自查
> ```bash
> grep -nE '^[^#]*[[:space:]]trust([[:space:]]|$)' /etc/postgresql/*/*/pg_hba.conf   # 必須沒有輸出
> sudo -u postgres psql -tAc "SELECT rolname FROM pg_roles WHERE rolsuper"           # 應只有 postgres
> ss -lntp | grep 5432                                                               # 應只有 127.0.0.1
> ```

---

## 速查表

### 服務與 cluster 管理（Debian 系）

| 指令 | 說明 | 星級 |
| --- | --- | --- |
| `pg_lsclusters` | ★★★★ **判斷資料庫死活的唯一標準**，看 `Status` 欄 | ★★★★ |
| `pg_ctlcluster 17 main start\|stop\|restart\|reload` | 啟停單一 cluster | ★★★★ |
| `pg_ctlcluster 17 main stop -m fast` | 快速停止（中斷現有連線），預設是 `smart`（等連線結束） | ★★★ |
| `pg_createcluster 17 main --datadir=X --locale=Y -- --data-checksums` | 建 cluster，`--` 後的參數傳給 `initdb` | ★★★★ |
| `pg_dropcluster 17 main --stop` | ★★★★★ **刪除 cluster 與全部資料，不可逆** | ★★★★★ |
| `pg_conftool 17 main show\|set <param>` | 安全地讀寫 `postgresql.conf` | ★★★ |
| `pg_upgradecluster 16 main` | 跨大版本升級（會建新 cluster） | ★★★★ |
| `systemctl status postgresql@17-main` | ★★★ 真正的 unit 名稱 | ★★★ |

### psql 內建指令

| 指令 | 說明 | 星級 |
| --- | --- | --- |
| `\l` / `\l+` | 列資料庫（含 encoding、collate） | ★★★★ |
| `\c <db>` | 切換資料庫（★★★ 實際上是重新連線） | ★★★★ |
| `\dt` / `\dn` / `\du` | 列表 / schema / 角色 | ★★★ |
| `\conninfo` | ★★★★ 我現在到底連到哪台、哪個庫、哪個埠 | ★★★★ |
| `\password [role]` | ★★★★ 改密碼且不留痕跡 | ★★★★ |
| `\x` | 直式顯示，寬表必備 | ★★ |
| `\timing` | 顯示執行時間 | ★★ |
| `\q` | 離開 | ★ |

### 一定要記的 SQL 查詢

| SQL | 用途 | 星級 |
| --- | --- | --- |
| `SHOW data_directory; SHOW config_file; SHOW hba_file;` | ★★★★ 接手機器第一件事：**設定檔到底在哪** | ★★★★ |
| `SELECT * FROM pg_settings WHERE name='x';` | 看參數值與 **`context`（要不要 restart）** | ★★★★ |
| `SELECT datname, pg_encoding_to_char(encoding), datcollate FROM pg_database;` | ★★★★★ 檢查 encoding 是否為 UTF8 | ★★★★★ |
| `SELECT rolname, rolsuper FROM pg_roles;` | 找出所有 superuser | ★★★★ |
| `SELECT pg_size_pretty(pg_database_size('appdb'));` | 資料庫大小 | ★★★ |
| `SELECT pg_reload_conf();` | 不用 sudo 也能 reload（需 superuser） | ★★★ |
| `ALTER SYSTEM SET x = y;` | 寫進 `postgresql.auto.conf`，★★★ **不要手改那個檔** | ★★★ |
| `ALTER SYSTEM RESET x;` | 撤銷上一行 | ★★★ |

### 檔案路徑（Ubuntu / RHEL）

| 用途 | Ubuntu | RHEL（PGDG） | 星級 |
| --- | --- | --- | --- |
| 主設定檔 | `/etc/postgresql/17/main/postgresql.conf` | `/var/lib/pgsql/17/data/postgresql.conf` | ★★★★ |
| 認證設定 | `/etc/postgresql/17/main/pg_hba.conf` | `/var/lib/pgsql/17/data/pg_hba.conf` | ★★★★ |
| `ALTER SYSTEM` 寫入處 | `<datadir>/postgresql.auto.conf` | 同左 | ★★★ |
| 資料目錄 | `/var/lib/postgresql/17/main` | `/var/lib/pgsql/17/data` | ★★★★ |
| WAL | `<datadir>/pg_wal/` | 同左 | ★★★★ |
| 日誌 | `/var/log/postgresql/postgresql-17-main.log` | `<datadir>/log/` | ★★★★ |
| socket | `/var/run/postgresql/` | `/var/run/postgresql/` | ★★★ |
| 執行檔 | `/usr/lib/postgresql/17/bin/` | `/usr/pgsql-17/bin/` | ★★★ |
| 開機自啟開關 | `/etc/postgresql/17/main/start.conf` | `systemctl enable postgresql-17` | ★★★ |

### 判斷準則

| 問題 | 判準 | 星級 |
| --- | --- | --- |
| 資料庫活著嗎 | `pg_lsclusters` 的 `Status` 是 `online` | ★★★★★ |
| 改完要 reload 還是 restart | `pg_settings.context`：`sighup`→reload、`postmaster`→restart | ★★★★ |
| 這個 encoding 能不能救 | `template0` 也是 `SQL_ASCII` → 只能重建 cluster | ★★★★★ |
| 連不上是誰的問題 | `sudo -u postgres psql` 成功 → 問題在 pg_hba 或網路 | ★★★★ |
| 該用 database 還是 schema | 「這些資料以後會不會一起查」→ 會就用 schema | ★★★★ |
| 版本還能不能用 | 釋出年份 + 5 年 > 今天 | ★★★★ |

---

## 練習題

> [!question]- 練習 1：五分鐘產出一台接手機器的現況摘要
> 你接手一台不明狀態的 PostgreSQL 主機，請在五分鐘內回答：
> 有幾個 cluster、各是什麼版本與埠、encoding 與 collate、有沒有 `trust`、
> 有幾個 superuser、datadir 在哪、磁碟剩多少、`password_encryption` 是什麼。
>
> **參考解答**
> ```bash
> pg_lsclusters
> for d in /etc/postgresql/*/*/; do
>   echo "== $d"; grep -vE '^\s*#|^\s*$' "$d/pg_hba.conf"
> done
> sudo -u postgres psql <<'SQL'
> SHOW server_version; SHOW data_directory; SHOW listen_addresses; SHOW password_encryption;
> SELECT datname, pg_encoding_to_char(encoding) enc, datcollate,
>        pg_size_pretty(pg_database_size(datname)) sz FROM pg_database ORDER BY 1;
> SELECT rolname, rolsuper, rolcanlogin FROM pg_roles WHERE rolcanlogin ORDER BY 1;
> SQL
> df -h "$(sudo -u postgres psql -tAc 'SHOW data_directory')"
> ss -lntp | grep -E ':543[0-9]'
> ```
> ★★★★ 判讀重點：
> ① `enc` 是 `SQL_ASCII` → 這台已經在累積資料損傷，先確認有沒有中文資料；
> ② `pg_hba.conf` 出現 `trust` → **立刻記錄為資安缺失並排入處理**，但先確認關掉後誰會斷線；
> ③ superuser 超過一個 → 追出是誰、什麼時候建的；
> ④ 兩個 cluster 都 online → 確認應用程式連的是哪一個埠。
> 這八項就是驗收檢查表的濃縮版，也是接手任何 PostgreSQL 的標準開場。

> [!question]- 練習 2：故意建錯 encoding，然後體會「救不回來」
> 在測試機上用 `pg_createcluster 17 broken --port=5440 --encoding=SQL_ASCII --locale=C --start`
> 建一個 cluster，塞一筆中文資料進去，再嘗試把它改成 UTF8。記錄下你在每一步看到的錯誤。
>
> **參考解答**
> 1. 建完後 `psql -p 5440 -c "\l"` 會看到 `Encoding` 是 `SQL_ASCII`。
> 2. 塞資料：`CREATE TABLE t(a text); INSERT INTO t VALUES ('資訊室');` —— **不會有任何錯誤**，
>    這正是 `SQL_ASCII` 最危險的地方：它把 bytes 原封不動存下來，不做任何驗證。
> 3. 試圖修：`CREATE DATABASE fix ENCODING 'UTF8' TEMPLATE template1;` →
>    ```text
>    ERROR:  new encoding (UTF8) is incompatible with the encoding of the template database (SQL_ASCII)
>    HINT:  Use the same encoding as in the template database, or use template0 as template.
>    ```
>    改用 `TEMPLATE template0` 也一樣失敗，**因為整個 cluster 的 `template0` 就是 `SQL_ASCII`**。
> 4. ★★★★★ 結論：**只能 `pg_dropcluster 17 broken --stop` 重建**。
>    如果那些 bytes 原本是 UTF-8 編碼的，`pg_dump` 出來後用 `iconv` 還有機會救；
>    如果是混了 Big5 與 UTF-8（機關的舊系統很常見），**就是逐筆人工判斷**。
> 5. 清理：`sudo pg_dropcluster 17 broken --stop`。

> [!question]- 練習 3：把自己鎖在門外再救回來
> 在測試機上把 `pg_hba.conf` 的所有 `local` 行註解掉、reload，
> 確認 `sudo -u postgres psql` 真的進不去；然後在**不使用 `trust`** 的前提下救回來，
> 並寫出「如果這是正式機，我會在什麼時間點做什麼」的處置流程。
>
> **參考解答**
> 1. 註解 + reload 後：
>    ```text
>    psql: error: FATAL:  no pg_hba.conf entry for host "[local]", user "postgres",
>      database "postgres", no encryption
>    ```
>    ★★★ 注意**現有連線不會被踢掉** —— `pg_hba.conf` 只在**建立新連線**時比對。
>    如果你還有一個開著的 psql session，可以直接在裡面 `SELECT pg_reload_conf();`。
> 2. 救援（有 root 就一定救得回來）：
>    ```bash
>    sudo cp /etc/postgresql/17/main/pg_hba.conf /root/pg_hba.broken.$(date +%F_%H%M)
>    sudo sed -i '1i local   all   postgres   peer' /etc/postgresql/17/main/pg_hba.conf
>    sudo pg_ctlcluster 17 main reload
>    sudo -u postgres psql -c 'SELECT current_user;'
>    ```
> 3. ★★★★ 正式機的處置流程：
>    ① 先確認**現有應用連線是否還活著**（`pg_hba` 只影響新連線，所以通常還活著，你有時間）；
>    ② 立刻用還開著的連線或 root 改檔，**只加回必要的那一行**；
>    ③ reload（**不要 restart**，restart 會把還活著的連線全部踢掉）；
>    ④ 事後寫變更紀錄：改了什麼、為什麼失敗、備份檔在哪。
> 4. ★★★★★ 這題真正要學會的是：**改 `pg_hba.conf` 之前先開一個 psql session 不要關**，
>    那就是你的逃生門。

---

## 小測驗

Q1. `sudo psql` 得到 `FATAL: role "root" does not exist`，而 `psql -U postgres` 得到 `FATAL: Peer authentication failed for user "postgres"`。這兩個錯誤發生在認證流程的哪個階段？各自該怎麼修？

Q2. `systemctl status postgresql` 顯示 `active (exited)`，但應用程式連不上資料庫。為什麼會這樣？你該改看什麼？

Q3. 同事在 Ubuntu 24.04 與 Ubuntu 26.04 上都執行 `sudo apt install -y postgresql`，然後回報「兩台行為不一樣」。最可能的原因是什麼？交付文件裡應該怎麼寫才不會再發生？

Q4. `initdb` 執行之後就不能改的三項設定是什麼？各自選錯的後果與補救成本是什麼？

Q5. `CREATE DATABASE appdb ENCODING 'UTF8';` 失敗，錯誤是 `new encoding (UTF8) is incompatible with the encoding of the template database`。修法是什麼？什麼情況下這個修法也救不了？

Q6. 你把 `listen_addresses` 從 `localhost` 改成 `'10.0.1.5'`，執行了 `pg_ctlcluster 17 main reload`，但遠端還是連不上，`ss -lntp` 顯示仍只監聽 `127.0.0.1`。為什麼？你要怎麼「用查的」而不是「用背的」得到答案？

Q7. 一台機器 `pg_lsclusters` 顯示 16/main 在 5432、17/main 在 5433。開發回報「連上去 `SELECT version()` 是 16」。給出三種讓連線明確指向 17 的做法。

Q8. 為什麼本手冊堅持「絕對不要用 `trust` 當救援手段」？如果 `pg_hba.conf` 改壞了進不去，正確的救援步驟是什麼？

Q9. Ubuntu 22.04 升級到 24.04 之後，某張表的唯一索引擋不住重複值，`WHERE name = '王小明'` 也查不到明明存在的資料，而且**沒有任何錯誤訊息**。最可能的原因是什麼？怎麼確認、怎麼修、怎麼從源頭避免？

Q10. `sudo apt purge postgresql-17` 之後重新安裝，為什麼可能拿到「舊的角色、舊的密碼、舊的 `pg_hba.conf`」？在交付情境下這是什麼等級的問題？完全乾淨移除的正確順序是什麼？

> [!question]- 測驗答案
> **Q1.** ★★★★ 這兩個錯誤在**認證流程的不同階段**：
> - **`Peer authentication failed`**：卡在 **pg_hba 的認證方法**這一步。`peer` 規則要求
>   「連線端的 OS 使用者名稱 = 要登入的角色名稱」，你的 OS 身分是 `ops`（或別的），
>   要登入 `postgres`，對不上就直接拒絕，**完全不看密碼**。
> - **`role "root" does not exist`**：★★★★ **peer 已經通過了**（OS 是 `root`，psql 預設也用 `root` 當角色名），
>   卡在下一步「這個角色在 cluster 裡不存在」。
>
> 修法都是同一個：
> ```bash
> sudo -u postgres psql        # 把 OS 身分切成 postgres，peer 才對得上
> ```
> ★★★ 判斷口訣：**`Peer authentication failed` 查「我現在是誰」，
> `role ... does not exist` 查「這個角色建了沒」。** 見「★★★★ peer 認證」一節。
>
> **Q2.** 因為 Ubuntu 的 `postgresql.service` 是一個 **`Type=oneshot` 的空殼**，
> 它的職責只是「把各個 cluster 的 `postgresql@<ver>-<cluster>.service` 拉起來」，
> 拉完自己就結束，狀態變成 `active (exited)`。
> ★★★★ **底下的 cluster 全部啟動失敗，它照樣顯示 `active (exited)`。**
> 正確的判斷方式有兩個：
> ```bash
> pg_lsclusters                              # ★★★★ 看 Status 欄，要是 online
> systemctl status postgresql@17-main        # ★★★ 真正的 unit
> sudo tail -30 /var/log/postgresql/postgresql-17-main.log
> ```
> ★★★ 這是 PostgreSQL 與 MySQL 最不一樣的維運習慣之一 ——
> MySQL 看 `systemctl status mysql` 就夠了，PostgreSQL 不行。見「套件名、服務名、路徑對照」。
>
> **Q3.** 因為 **`postgresql` 是一個 meta 套件，它指向的是「該發行版當下的預設大版本」**：
> Ubuntu 24.04 (noble) 給 **16**，Ubuntu 26.04 (resolute) 給 **18**。
> 同一行指令在兩台機器裝出**差兩個大版本**的資料庫，行為當然不一樣
> （例如 18 的 `initdb` 預設開 data checksums，16 預設不開）。
> ```bash
> apt-cache policy postgresql        # ★★★ 事前就能看出候選版本
> ```
> ★★★★ 交付文件的正確寫法：
> ① **永遠寫大版本明確的套件名**（`postgresql-17`），不要寫 `postgresql`；
> ② 註明來源是 PGDG 還是發行版內建；
> ③ 驗收表列一項「`psql --version` 必須是 17.x」。見「版本選型」與驗收檢查表第 2、3 項。
>
> **Q4.** ★★★★★ 三項是 **encoding、locale（定序）、data checksums**：
>
> | 項目 | 選錯後果 | 補救成本 |
> | --- | --- | --- |
> | **encoding** | 中文亂碼且**無錯誤訊息**（`SQL_ASCII` 不驗證） | 重建 cluster + 重匯；已壞的資料**救不回來** |
> | **locale / 定序** | 中文排序錯亂、glibc 升級後索引失效 | 可用 ICU 在 database 層繞過，否則重建 |
> | **data checksums** | 靜默資料損毀不會被偵測，備份把壞資料一起備走 | `pg_checksums --enable`，但**必須完全停機**，大庫要跑數小時 |
>
> ★★★★ 所以本篇的佈建腳本一律**明確帶 `-E UTF8 --locale=... -- --data-checksums`**，
> 而不是依賴 shell 的 `LANG`。見「裝完當下的六個決定」。
>
> **Q5.** 修法是加上 **`TEMPLATE template0`**：
> ```sql
> CREATE DATABASE appdb ENCODING 'UTF8' TEMPLATE template0
>   LC_COLLATE 'en_US.UTF-8' LC_CTYPE 'en_US.UTF-8';
> ```
> 原因：`CREATE DATABASE` 預設從 `template1` 複製，而**從既有樣板複製時不允許換 encoding**
> （樣板裡可能已經有該編碼的資料）。`template0` 是保證空白且唯讀的樣板，所以允許指定新 encoding。
> ★★★★★ **這個修法救不了的情況：整個 cluster 在 `initdb` 時就是 `SQL_ASCII`**，
> 那 `template0` 自己也是 `SQL_ASCII`，怎麼指定都沒用。這時只剩 `pg_dropcluster` 重建一途。
> 用這行確認：
> ```bash
> sudo -u postgres psql -c "SELECT datname, pg_encoding_to_char(encoding) FROM pg_database WHERE datname='template0';"
> ```
> 見「encoding、locale、定序」一節與練習 2。
>
> **Q6.** 因為 **`listen_addresses` 是 `postmaster` context 的參數，reload 對它無效，必須 restart**。
> ★★★★ 不要背哪些參數要重啟，**用查的**：
> ```bash
> sudo -u postgres psql -c "SELECT name, setting, context FROM pg_settings WHERE name='listen_addresses';"
> ```
> ```text
>       name       |  setting  |  context
> ------------------+-----------+------------
>  listen_addresses | 10.0.1.5  | postmaster     # ★★★★ postmaster = 一定要 restart
> ```
> `context` 的四個常見值：`internal`（不能改）、**`postmaster`（restart）**、
> **`sighup`（reload）**、`user`／`superuser`（線上即時生效）。
> ★★★ 另外提醒：改成對外監聽之前，**先確認防火牆白名單已經設好**，順序不能反，
> 見 [[02-防火牆-ufw基礎與實務]] 與 [[08-PostgreSQL-安全強化]]。
>
> **Q7.** 三種做法，★★★ 由臨時到正式：
> ```bash
> # ① 明確帶埠（臨時查驗最常用）
> psql -h 127.0.0.1 -p 5433 -U postgres -c 'SELECT version();'
>
> # ② 用 postgresql-common 的 --cluster 包裝（不用記埠號）
> psql --cluster 17/main -c 'SELECT version();'
>
> # ③ 環境變數鎖定整個 shell session
> export PGPORT=5433
> ```
> ★★★★ 但這三種都只是「查得到」，**正式的做法是把埠寫死在應用程式設定裡**
> （Laravel 的 `.env` 寫 `DB_PORT=5433`），而不是依賴預設值。
> 如果 16 已經沒有人用，更乾淨的做法是把它停掉並改 `start.conf` 為 `manual`，
> 讓 17 接手 5432。★★★★ **交付文件必須明確寫出「應用連的是哪個 cluster、哪個埠」**。
> 見「多版本、多 cluster 並存」與排查步驟【6】。
>
> **Q8.** 因為 `trust` 的語意是：**任何能連到這個埠的來源，都可以用任何角色登入
> （包含 superuser），不需要密碼**。而 PostgreSQL 的 superuser 可以用
> `COPY ... FROM PROGRAM` 執行作業系統指令 —— 等於整台機器失守。
> ★★★★★ 但真正的事故來源不是被入侵，是**「臨時改成 trust 之後忘了改回來」**，
> 半年後被資安掃描掃出來變成通報案件。
> 正確救援（★★★ 你有 root，`pg_hba.conf` 是純文字檔，一定救得回來）：
> ```bash
> sudo cp /etc/postgresql/17/main/pg_hba.conf /root/pg_hba.broken.$(date +%F_%H%M)
> sudo sed -i '1i local   all   postgres   peer' /etc/postgresql/17/main/pg_hba.conf
> sudo pg_ctlcluster 17 main reload      # ★★★ reload 就好，不要 restart（restart 會踢掉現有連線）
> ```
> **只加回 `local ... peer` 那一行**，不動其他規則。見「把自己鎖在門外時的救援」與練習 3。
>
> **Q9.** ★★★★★ 這是 **glibc 定序版本改變**造成的索引失效。
> OS 大版本升級換了 glibc，`libc` provider 的排序規則跟著變，
> 既有 B-tree 索引是用**舊規則**排的，查詢用**新規則**去二分搜尋，於是找不到 ——
> 而且因為索引結構本身沒壞，**不會有任何錯誤訊息**，唯一索引也就擋不住重複值。
> 確認（PG 15+ 會主動警告）：
> ```bash
> sudo -u postgres psql -c \
>   "SELECT datname, datcollversion FROM pg_database;"
> sudo grep -i 'collation version mismatch' /var/log/postgresql/postgresql-17-main.log
> ```
> 修：
> ```sql
> REINDEX DATABASE appdb;                              -- ★★★★ 先重建索引
> ALTER DATABASE appdb REFRESH COLLATION VERSION;      -- 再更新記錄的版本
> ```
> ★★★★ 源頭避免：新建案改用 **ICU**（`--locale-provider=icu`）或 **builtin**（PG17+），
> 把定序規則鎖在資料庫裡而不是 OS 裡；以及**跨 OS 大版本升級後一律排一次 REINDEX**。
> 見「glibc 升級會讓 libc 定序悄悄改變」。
>
> **Q10.** 因為 **`apt purge` 只移除套件，不會刪 `/var/lib/postgresql/`（資料）
> 與 `/etc/postgresql/`（設定）**。重裝 `postgresql-17` 之後，`postgresql-common`
> 會把留在原地的 cluster 目錄重新認回來，於是舊角色、舊密碼雜湊、
> 舊的 `pg_hba.conf`（★★★★★ 可能含 `trust`）全部復活。
> ★★★★★ **在交付情境這是重大問題**：你在報告上寫「已重新安裝，環境乾淨」，
> 實際上前一個廠商留下的帳號還在，這是稽核會直接開缺失的項目。
> 完全乾淨移除的正確順序（★★★★★ 不可逆，先備份）：
> ```bash
> sudo -u postgres pg_dumpall > /root/pre-purge-$(date +%F).sql   # 【0】先留一份
> sudo pg_dropcluster 17 main --stop                              # 【1】先刪 cluster（含 datadir 與 /etc）
> sudo apt purge -y 'postgresql-17*'                              # 【2】再移除套件
> sudo rm -rf /var/lib/postgresql /etc/postgresql /etc/postgresql-common  # 【3】收尾
> ```
> ★★★★ 另外別忘了 `/var/lib/postgresql/.psql_history` 與 `.pgpass` ——
> 機器轉手前這兩個檔一定要清。見「解除安裝與重裝的陷阱」與「安全性注意事項」。

---

## 延伸閱讀

- [[04-PostgreSQL-設定檔與pg_hba]] — ★★★★★ 本篇只讓你連得進去；**`pg_hba.conf` 的比對順序、
  trust／peer／scram-sha-256 的差異、改完 reload 還是 restart**，全部在那篇
- [[02-PostgreSQL-角色與權限]] — 本篇只建了一個 `appuser`；role 當群組用、`GRANT` 到 schema 層、
  唯讀報表帳號的完整設計在那篇
- [[03-psql-操作與常用指令]] — `\` 指令、`\copy`、`ON_ERROR_STOP`、批次腳本寫法
- [[05-PostgreSQL-備份與還原]] — ★★★★★ 驗收檢查表第 17 項；**PITR（WAL 歸檔 + 還原到時間點）
  與還原演練**，沒演練過的備份不算數
- [[06-PostgreSQL-效能調校與索引]] — `shared_buffers`／`work_mem` 怎麼算、`EXPLAIN` 怎麼看
- [[08-PostgreSQL-安全強化]] — TLS 連線、`pgaudit`、RLS、個資與稽核情境
- [[01-MySQL-安裝與初始化]] — ★★★ 同一件事在 MySQL 怎麼做；兩篇對照著看，差異會很清楚
- [[03-SQL基礎操作]] — 建完庫之後的第一批 SQL（**PostgreSQL 通用，本章不重講語法**）
- [[03-範例-Nuxt與PostgreSQL]] — 這個資料庫要交給誰用
- PostgreSQL 官方安裝文件（Ubuntu／PGDG）：<https://www.postgresql.org/download/linux/ubuntu/>
- PostgreSQL 版本支援政策：<https://www.postgresql.org/support/versioning/>
- `initdb` 與 locale 支援：<https://www.postgresql.org/docs/current/app-initdb.html>
