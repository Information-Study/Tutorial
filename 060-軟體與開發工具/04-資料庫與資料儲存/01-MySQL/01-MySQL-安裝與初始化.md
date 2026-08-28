---
title: "MySQL 安裝與初始化"
desc: "版本選型、安裝與非互動加固、auth_socket、utf8mb4 與時區、datadir 搬遷與 AppArmor、交付前驗收腳本"
aliases: [mysql安裝, mysql_secure_installation, utf8mb4, auth_socket, datadir, mysqld.cnf, mysql8]
tags: [群組/軟體與開發工具, 服務/mysql, 主題/安裝]
category: 資料庫與資料儲存
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[14-套件管理]]", "[[17-systemd服務管理]]"]
updated: 2026-08-28
---

# MySQL 安裝與初始化

> [!abstract] 這篇你會學到
> - 用「**三年後還有沒有安全更新**」這個判準，在 Ubuntu 內建 8.0 / Oracle 官方套件庫 8.4 LTS / RHEL 系 MariaDB 之間**做出可以寫進交付文件的版本選型**
> - 把一台乾淨的 Ubuntu 24.04 在一小時內變成**可以直接交給 Laravel 專案用**的 MySQL：安裝 → 加固 → 字元集 → 時區 → 建庫建帳號
> - ★★★★ 搞懂 **`root@localhost` 的 `auth_socket`**：為什麼 `sudo mysql` 不用密碼、為什麼 `mysql -u root -p` 打死都進不去、**改成密碼認證會弄壞哪些排程**
> - ★★★★ 在**建庫的那一秒**就把 **utf8mb4 與定序**決定對 —— 這件事事後補救的代價是重匯整個資料庫，而已經變成 `????` 的中文與 emoji **救不回來**
> - ★★★★ 把 **datadir 搬到獨立磁碟**，而且**記得改 AppArmor**（RHEL 是 SELinux）—— 忘了這步服務起不來，而錯誤訊息完全不會提到 AppArmor
> - 寫出一支 **`mysql-postinstall-check.sh`**，輸出可以直接貼進交付單的驗收結果，並附**改壞了怎麼回去**的回滾步驟

## 前置知識

- [[14-套件管理]] — apt / dnf 的套件庫、`purge` 與 `remove` 的差別
- [[17-systemd服務管理]] — `systemctl`、drop-in 覆寫、`journalctl -u`
- [[15-磁碟分割與掛載]] — 資料要搬到獨立磁碟或 LVM 時需要
- [[28-時間同步NTP與chrony]] — 資料庫時間對不上的源頭多半在這裡
- [[01-部署共通觀念]] — 這台機器在整個部署流程裡的位置

---

## 觀念說明

### MySQL 在 LXMP 裡的位置

本手冊的主軸 LXMP 是四件套：**L**inux + Ng**X**（Nginx／Apache2）+ **M**ySQL + **P**HP。
MySQL 是唯一一個**壞掉不能重裝了事**的元件 —— Nginx 設定錯了改回來就好，PHP 版本裝錯了重裝就好，
但資料庫一旦資料被寫壞、字元集選錯、時間存錯，**損傷是累積且不可逆的**。

```text
  使用者 → Nginx(443) ──fastcgi──→ PHP-FPM ──PDO──→ MySQL 8.x
                                                     socket: /var/run/mysqld/mysqld.sock（本機、不走網路）
                                                     tcp   : 127.0.0.1:3306
                                                        ↓
                                            datadir  /var/lib/mysql 或 /data/mysql（獨立磁碟）
                                                        ↓
                                                  每日備份（第 05 篇）
```

★★★★ **本篇做的每一個決定，都會鎖住未來三年的維護成本**。下面這張表是本篇存在的理由：

| 裝完當下的決定 | 選錯的後果 | 事後補救成本 |
| --- | --- | --- |
| **版本／來源** ★★★ | 兩年後沒有安全更新，或備份工具不支援 | 跨大版本升級，需停機與完整回歸測試 |
| **字元集與定序** ★★★★★ | 中文、emoji 存成 `????`；dump 匯不進別台 | **已損毀的資料救不回來**，其餘要重匯整庫 |
| **時區** ★★★★ | 稽核紀錄時間差 8 小時，事故調查失效 | 歷史資料的時間語意已經混亂，只能靠人工比對 |
| **datadir 位置** ★★★ | 系統碟爆滿 → MySQL 直接停機 | 要停機搬移，而且卡在 AppArmor／SELinux |
| **root 認證方式** ★★★★ | 備份排程與自動化腳本全部連不上 | 要改動所有排程，且密碼已散落在腳本裡 |
| **加固有沒有做** ★★★★★ | 匿名帳號、test 庫、root 可遠端 → 資安通報 | 通常是被掃到才知道 |

> [!note] 這篇不談什麼
> 權限與 `GRANT` 設計 → [[02-MySQL-使用者與權限]]；參數調校 → [[04-MySQL-設定檔與調校]]；
> TLS 與稽核 → [[07-MySQL-安全強化]]；備份 → [[05-MySQL-備份與還原]]。本篇只負責**把地基打對**。

---

### ★★★★ 版本選型：判準是「三年後還有沒有安全更新」

Oracle 從 8.0 之後改成 **LTS ＋ Innovation 雙軌**：LTS 有 **5 年 Premier ＋ 3 年 Extended**，
Innovation 只支援到下一個小版本出來為止 —— 機關系統壽命動輒五到八年，
**Innovation 版在機關環境等於不能用**。以下為 **2026-08 查詢的結果**，佈建前務必自己再確認一次：

| 路線 | 目前版本 | 安全更新到 | 適用情境 | 建議 |
| --- | --- | --- | --- | --- |
| **Ubuntu 24.04 內建 `mysql-server`** | 8.0.44+ | 上游 2026-04 已 EOL，但 **Canonical 在 24.04 生命週期內持續 backport**（標準支援至 2029-04，Pro/ESM 至 2034-04） | 機關現況主流、要走發行版整體支援 | ★★★ **可用**，但要在文件中寫明「安全更新來自 Ubuntu 而非 Oracle」 |
| **Ubuntu 26.04 內建 `mysql-server`** | 8.4 LTS | 隨發行版 | 2026 之後的新建案 | ★★★★ **新機首選** |
| **Oracle APT 套件庫 `mysql-8.4`** | 8.4.x LTS | Premier 2029-04-30／Extended 2032-04-30 | 要跟上游同版號、要用 Oracle 的工具鏈 | ★★★★ **長壽命專案首選** |
| **Oracle APT 套件庫 `mysql-9.7`** | 9.7.x LTS（2026-04 釋出） | Premier 2034-04-21 | 新開發、可接受較新的行為變更 | ★★ 先確認 ORM／備份工具支援 |
| Oracle APT 套件庫 Innovation 系列 | 9.x 非 LTS | 到下一個小版本為止 | 開發測試 | ★★★★ **機關正式環境不要用** |
| **RHEL 系預設 `mariadb-server`** | 10.11／11.8 模組 | 隨 RHEL 支援（RHEL 9 約至 2032） | 機關的 RHEL 標配 | ★★★ 能用，但**不是 MySQL**，見下方對照 |

```bash
# ★★ 自己查一次，不要相信任何文件裡寫死的小版本號（支援週期 https://endoflife.date/mysql）
apt-cache policy mysql-server
```

```text
mysql-server:
  已安裝：(無)
  候選：  8.0.44-0ubuntu0.24.04.1        # ★★★ 這行才是你實際會裝到的版本
```

> [!warning] ★★★ 版本選型會連帶決定第 05、06 篇能用哪些工具
> - **8.0 → 8.4 的兩個關鍵行為變更**：`mysql_native_password` 在 **8.4 預設不啟用**（9.x 直接移除），
>   舊的 PHP client、舊的報表工具、舊的監控 agent 會突然連不上，錯誤是
>   `Authentication plugin 'mysql_native_password' cannot be loaded`。
> - **備份工具**：Percona XtraBackup 有嚴格的版本對應（8.0 的 XtraBackup 不能備份 8.4）。
>   選版本時**先確認你打算用的備份工具支援它**，見 [[05-MySQL-備份與還原]]。
> - **複寫**：8.4 之後的複寫語法改用 `SOURCE`／`REPLICA` 系列關鍵字，
>   舊的 `MASTER`／`SLAVE` 語法已移除，見 [[06-MySQL-主從複寫]]。

> [!info]- MariaDB 對照：機關的 RHEL 主機十之八九是這個
> RHEL／Rocky／AlmaLinux 的 `dnf install mysql-server` 與 `mariadb-server` **是兩個不同的東西**，
> 而機關既有主機上跑的多半是後者。差異中會咬人的：
>
> | 項目 | MySQL 8.x | MariaDB 10.11 / 11.8 |
> | --- | --- | --- |
> | 預設字元集 | `utf8mb4`（8.0 起） | **10.11 仍是 `latin1`**；★★★★ **11.8 才改為 `utf8mb4`** |
> | 預設定序 | `utf8mb4_0900_ai_ci` | 10.11：`latin1_swedish_ci`；11.8：`utf8mb4_uca1400_ai_ci` |
> | `utf8mb4_0900_ai_ci` | 有 | **★★★★ 完全沒有** —— MySQL 的 dump 匯入會 `ERROR 1273` |
> | root 認證 | `auth_socket`（Debian 系打包） | `unix_socket` 外掛（名稱不同、概念相同） |
> | 加固腳本 | `mysql_secure_installation` | `mariadb-secure-installation` |
> | 服務名 | `mysqld`（RHEL）／`mysql`（Ubuntu） | `mariadb`（`mysqld` 是 alias） |
> | 用戶端 | `mysql` | `mariadb`（`mysql` 是相容連結） |
>
> ★★★★ **不要假設「反正都是 SQL」**。定序不同會讓唯一索引的判定不同，
> 預設字元集不同會讓「同一份建表 SQL 在兩台跑出不同結果」。
> 接手既有機器的第一件事永遠是：
> ```bash
> mysql -e "SELECT VERSION(); SHOW VARIABLES LIKE 'character_set_server';"
> ```

---

### 套件名、服務名、路徑對照

★★★ 這張表是本篇最常被回頭查的一張。**Ubuntu 與 RHEL 幾乎每一項都不同**。

| 項目 | Ubuntu / Debian（主線） | RHEL 系（Rocky / AlmaLinux） |
| --- | --- | --- |
| 套件名 | `mysql-server`（依賴 `mysql-server-8.0`） | `mysql-server`（dnf 模組）／`mariadb-server` |
| **服務名** ★★★ | **`mysql.service`** | **`mysqld.service`** |
| 資料目錄 `datadir` | `/var/lib/mysql` | `/var/lib/mysql` |
| **主設定檔** | `/etc/mysql/my.cnf`（只放 `!includedir`） | `/etc/my.cnf` |
| **實際要改的檔** ★★★ | **`/etc/mysql/mysql.conf.d/mysqld.cnf`** | `/etc/my.cnf.d/` 下自建 `.cnf` |
| 自訂設定建議位置 | `/etc/mysql/mysql.conf.d/99-<專案>.cnf` | `/etc/my.cnf.d/99-<專案>.cnf` |
| 錯誤日誌 | `/var/log/mysql/error.log` | `/var/log/mysql/mysqld.log` |
| socket | `/var/run/mysqld/mysqld.sock` | `/var/lib/mysql/mysql.sock` |
| PID | `/var/run/mysqld/mysqld.pid` | `/var/run/mysqld/mysqld.pid` |
| **強制存取控制** ★★★★ | **AppArmor**：`/etc/apparmor.d/usr.sbin.mysqld` | **SELinux**：`mysqld_t` / `mysqld_db_t` |
| 維護帳號 | **`debian-sys-maint`** + `/etc/mysql/debian.cnf` | 無 |
| root 初始認證 | `auth_socket`（免密碼、僅本機 root） | **空密碼**，必須立刻加固 |

設定檔的**載入順序**（後讀的覆蓋先讀的）：

```bash
# ★★ 查出實際的讀取順序，不要背
mysqld --verbose --help 2>/dev/null | head -20 | grep -A2 'Default options'
```

預期輸出：

```text
Default options are read from the following files in the given order:
/etc/my.cnf /etc/mysql/my.cnf ~/.my.cnf
```

而 Ubuntu 的 `/etc/mysql/my.cnf` 內容是：

```ini
!includedir /etc/mysql/conf.d/
!includedir /etc/mysql/mysql.conf.d/
```

★★★ 兩個結論：
① **`mysql.conf.d/` 在 `conf.d/` 之後讀，所以它會贏**；
② 同一個目錄內**依檔名字母序**讀取，所以自訂檔用 `99-` 開頭最保險。
參數本身的意義留給 [[04-MySQL-設定檔與調校]]，路徑速查見 [[03-設定檔路徑速查]]。

---

## 環境準備與安裝

### 安裝前的三件事

```bash
lsb_release -ds && uname -m          # 【1】OS 版本與架構
df -h / /var /data 2>/dev/null       # 【2】★★★ 資料庫最怕系統碟被塞爆
timedatectl                          # 【3】★★★★ 時間錯，稽核紀錄就是錯的
```

```text
Ubuntu 24.04.3 LTS
x86_64
/dev/sda2        48G  6.2G   40G   14% /
/dev/sdb1       500G   28K  475G    1% /data      # ★★★ 有獨立資料碟就用它當 datadir
               Local time: 四 2026-08-28 09:14:22 CST
                Time zone: Asia/Taipei (CST, +0800)
System clock synchronized: yes            # ★★★★ 這行是 no 就先處理 NTP
```

### 安裝 MySQL Server

```bash
sudo apt update
sudo apt install -y mysql-server
```

預期輸出（尾段）：

```text
Setting up mysql-server-8.0 (8.0.44-0ubuntu0.24.04.1) ...
update-alternatives: using /etc/mysql/my.cnf.fallback to provide /etc/mysql/my.cnf (my.cnf) in auto mode
Created symlink /etc/systemd/system/multi-user.target.wants/mysql.service → /usr/lib/systemd/system/mysql.service
Setting up mysql-server (8.0.44-0ubuntu0.24.04.1) ...
```

★★ Debian 系的打包會**自動啟動並設為開機自啟**，安裝完當下資料庫就已經在跑了。

```bash
systemctl status mysql --no-pager
```

```text
● mysql.service - MySQL Community Server
     Loaded: loaded (/usr/lib/systemd/system/mysql.service; enabled; preset: enabled)
     Active: active (running) since Thu 2026-08-28 09:16:41 CST; 12s ago     # ★★★ 看這行
   Main PID: 4821 (mysqld)
     Status: "Server is operational"                                          # ★★ 這句才代表真的可服務
      Tasks: 38 (limit: 9451)
     Memory: 366.1M
```

```bash
mysql --version
```

```text
mysql  Ver 8.0.44-0ubuntu0.24.04.1 for Linux on x86_64 ((Ubuntu))
```

```bash
# ★★★★ 確認監聽位址：預設就是 127.0.0.1，這是對的，不要改成 0.0.0.0
ss -lntp | grep 3306
```

```text
LISTEN 0  151  127.0.0.1:3306  0.0.0.0:*  users:(("mysqld",pid=4821,fd=23))
```

看到 `0.0.0.0:3306` 代表**資料庫暴露在網路上**，這在機關環境是資安缺失。
要開放遠端連線的正確做法（限定來源、走 TLS、搭配防火牆）見 [[07-MySQL-安全強化]] 與 [[02-防火牆-ufw基礎與實務]]。

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> # ═══ ① 先看有哪些模組串流可用（★★★ 版本由模組決定，不是由套件名）═══
> $ sudo dnf module list mysql
> Name   Stream   Profiles          Summary
> mysql  8.0      client, server    MySQL Module
> mysql  8.4      client, server    MySQL Module
>
> # ═══ ② 選定版本 ═══
> $ sudo dnf module reset mysql -y
> $ sudo dnf module enable mysql:8.4 -y
>
> # ═══ ③ 安裝 ═══
> $ sudo dnf install -y mysql-server
>
> # ═══ ④ ★★★★ RHEL 不會自動啟動、也不會設開機自啟 ═══
> $ sudo systemctl enable --now mysqld
> $ sudo systemctl status mysqld
> ```
> ★★★★ **RHEL 的 root 是空密碼、不是 `auth_socket`** —— 安裝完成到你跑完加固之前，
> 這台機器上**任何一個本機使用者**都可以 `mysql -u root` 直接進去。
> 安裝後的第一個指令就該是 `mysql_secure_installation`。
>
> ★★★ 其他差異：服務名 `mysqld`、錯誤日誌 `/var/log/mysql/mysqld.log`、
> socket 在 `/var/lib/mysql/mysql.sock`（很多 PHP 設定檔預設寫 `/var/run/mysqld/mysqld.sock`，
> 在 RHEL 上會直接連不上，要改 `pdo_mysql.default_socket`）。

> [!info]- 改用 Oracle 官方 APT 套件庫（要 8.4 LTS 或 9.7 LTS 時）
> ```bash
> # ① 到 https://dev.mysql.com/downloads/repo/apt/ 取得當前的 mysql-apt-config 版本號
> $ curl -fsSLO https://dev.mysql.com/get/mysql-apt-config_<版本>_all.deb
>
> # ② ★★★ 安裝時會跳出選單，選 MySQL Server & Cluster → mysql-8.4-lts
> $ sudo dpkg -i mysql-apt-config_<版本>_all.deb
> $ sudo apt update
> $ sudo apt install -y mysql-server
>
> # ③ 事後要換系列（例如 8.4 → 9.7）
> $ sudo dpkg-reconfigure mysql-apt-config && sudo apt update
> ```
> ★★★★ **Oracle 版與 Ubuntu 版的打包不同**：
> Oracle 版的 `root@localhost` 是 **`caching_sha2_password` 加隨機初始密碼**（寫在 `/var/log/mysql/error.log` 的
> `A temporary password is generated for root@localhost:` 那行），**不是 `auth_socket`**；
> 也**沒有 `debian-sys-maint` 帳號**。用 Ubuntu 版寫的自動化腳本搬到 Oracle 版會全部失效。
>
> ★★★ 兩個套件庫**不要混用**。已經裝了 Ubuntu 版又加 Oracle 套件庫，
> apt 會嘗試跨來源升級，失敗時常常停在資料目錄升級到一半的狀態。

---

### ★★★★ root@localhost 與 auth_socket

這是 Ubuntu 上的 MySQL 最讓人困惑的一件事，也是自動化腳本最常炸掉的地方。

```bash
sudo mysql -e "SELECT user, host, plugin FROM mysql.user ORDER BY user;"
```

預期輸出（Ubuntu 24.04 剛裝完）：

```text
+------------------+-----------+-----------------------+
| user             | host      | plugin                |
+------------------+-----------+-----------------------+
| debian-sys-maint | localhost | caching_sha2_password |   # ★★★ 套件維護專用，不要動
| mysql.infoschema | localhost | caching_sha2_password |   # 系統保留帳號（已鎖定）
| mysql.session    | localhost | caching_sha2_password |
| mysql.sys        | localhost | caching_sha2_password |
| root             | localhost | auth_socket           |   # ★★★★ 重點在這行
+------------------+-----------+-----------------------+
```

**`auth_socket` 到底做了什麼**：它完全不看密碼，而是透過 Unix domain socket 取得
連線端的作業系統 uid，再把它換成使用者名稱，**要求 OS 使用者名稱 = MySQL 帳號名稱**。

```text
  你在 shell 是誰                    MySQL 判定
  ─────────────────────────────────────────────────────────
  sudo mysql        → OS uid=0(root) → 名稱 root  → 對上 root@localhost  ✔ 進得去
  mysql -u root -p  → OS uid=1000(ops) → 名稱 ops → 對不上 root          ✘ ERROR 1698
  （密碼打對打錯完全沒差，因為根本沒在比密碼）
```

```bash
# 一般使用者的實際結果
mysql -u root -p
```

```text
Enter password:
ERROR 1698 (28000): Access denied for user 'root'@'localhost'    # ★★★★ 看到 1698 就是 auth_socket
```

★★★ **分辨兩個錯誤碼**：`ERROR 1698` 是「認證外掛不接受密碼」，`ERROR 1045` 才是「密碼真的錯」。
看到 1698 卻一直在試密碼，是最常見的浪費時間方式。

#### 要不要改成 caching_sha2_password？

```sql
-- ★★★★ 這行會把 root 從 auth_socket 換成密碼認證，影響是全機的
ALTER USER 'root'@'localhost' IDENTIFIED WITH caching_sha2_password BY '<強密碼>';
FLUSH PRIVILEGES;
```

| 面向 | 保留 `auth_socket`（**建議**） | 改成密碼認證 |
| --- | --- | --- |
| 誰能用 root | ★★★★ **只有能 `sudo` 的人**，權責與 OS 一致 | 任何拿到密碼的人，包含拿到腳本的人 |
| 密碼外洩風險 | ★★★★ **沒有密碼可以外洩** | 密碼會出現在腳本、cron、shell history、備份檔 |
| `sudo mysql` | 免密碼可用 | ★★★ **壞掉**，要改成 `mysql -u root -p` |
| 既有備份／監控排程 | 不受影響 | ★★★★ **全部要改**，漏一個就是備份靜默失敗 |
| 遠端使用 root | 兩者都不行（root 只有 localhost 帳號） | 同左（除非你再開遠端帳號，**不要**） |
| 個資法／稽核情境 | ★★★★ 操作可追溯到 OS 帳號（`sudo` 有日誌） | 只知道「有人用了 root 密碼」 |

★★★★ **本手冊的建議：不要改。** 需要非互動存取（備份、監控、報表）時，
**另外建立專用帳號並只給必要權限**，不要動 root：

```sql
-- ★★★ 備份專用帳號的最小權限（細節見第 02、05 篇）
CREATE USER 'bkpuser'@'localhost' IDENTIFIED BY '<強密碼>';
GRANT SELECT, RELOAD, PROCESS, LOCK TABLES, REPLICATION CLIENT, SHOW VIEW, EVENT, TRIGGER
  ON *.* TO 'bkpuser'@'localhost';
```

密碼要放在**檔案而不是指令列**：

```bash
# ★★★ 方法 A：~/.my.cnf（權限一定要 600，否則等於公開）
sudo install -m 600 /dev/null /root/.my.cnf
sudo tee /root/.my.cnf >/dev/null <<'EOF'
[client]
user = bkpuser
password = "把密碼放這裡"
EOF

# ★★ 方法 B：login-path（mysql_config_editor）
mysql_config_editor set --login-path=bkp --host=localhost --user=bkpuser --password
mysql --login-path=bkp -e "SELECT 1;"
```

> [!warning] ★★★ `mysql_config_editor` 是**混淆**不是加密
> `~/.mylogin.cnf` 只是把密碼做了可逆的變形，拿到檔案的人可以還原。
> 它解決的是「密碼出現在 `ps aux` 與 shell history」的問題，**不是「檔案被偷走」的問題**。
> 檔案權限與備份加密仍然要做，見 [[04-備份災難復原與入侵應變]]。

#### ★★★ `debian-sys-maint` 與 `/etc/mysql/debian.cnf` 不能刪

```bash
sudo cat /etc/mysql/debian.cnf
```

```text
[client]
host     = localhost
user     = debian-sys-maint
password = xxxxxxxxxxxxxxxx        # ★★ 安裝時隨機產生
socket   = /var/run/mysqld/mysqld.sock
```

```bash
ls -l /etc/mysql/debian.cnf
```

```text
-rw------- 1 root root 316  8月 28 09:16 /etc/mysql/debian.cnf     # ★★★ 600 root:root 是正確狀態
```

這個帳號是**套件維護腳本專用**：`apt upgrade` 時的資料字典升級、logrotate 的 flush logs、
以及部分 `mysql-server` 的 postinst 動作都靠它。

★★★★ **後果**：
- 把 `debian-sys-maint` 帳號 `DROP USER` 掉 → 下次 `apt upgrade mysql-server` **中途失敗**，
  dpkg 卡在 half-configured，而錯誤訊息只會說「無法連線」。
- 只改了 MySQL 裡的密碼、沒同步改 `debian.cnf`（或反過來）→ 一樣的結果。
  真的要改，兩邊必須一起改：

```bash
# ★★ 正確的改法（兩邊同步）
NEWPW="$(openssl rand -base64 24)"
sudo mysql -e "ALTER USER 'debian-sys-maint'@'localhost' IDENTIFIED BY '${NEWPW}';"
sudo sed -i "s|^password *=.*|password = ${NEWPW}|" /etc/mysql/debian.cnf
sudo mysql --defaults-file=/etc/mysql/debian.cnf -e "SELECT 1;"   # 驗證
```

---

### mysql_secure_installation 逐題解說

```bash
sudo mysql_secure_installation
```

| 題目 | 建議答案 | ★ | 選錯的後果 |
| --- | --- | --- | --- |
| `Setup VALIDATE PASSWORD component?` | **y**，強度選 **1（MEDIUM）** | ★★★ | 選 `n` → 之後任何人都能建 `123456` 的帳號；選 `2 (STRONG)` 但沒放字典檔 → 實際效果約等於 MEDIUM，卻會擋掉應用程式自動產生的密碼 |
| `Change the password for root?` | **n**（Ubuntu，root 是 `auth_socket`） | ★★★★ | 在 Ubuntu 上答 y 可能把 root 換成密碼認證，**`sudo mysql` 與所有排程一起壞掉**；RHEL 上則**必須**答 y |
| `Remove anonymous users?` | **y** | ★★★★ | 保留 → 任何本機使用者不用帳號密碼就能連進來，且能操作 `test` 與 `test_%` 開頭的所有資料庫 |
| `Disallow root login remotely?` | **y** | ★★★★★ | 保留 → root 可從網路登入，這是機關資安檢測必掃的項目 |
| `Remove test database and access to it?` | **y** | ★★★ | 保留 → `mysql.db` 裡對 `test` 與 `test\_%` 的萬用授權還在，**任何帳號都能在這些庫裡寫東西** |
| `Reload privilege tables now?` | **y** | ★★ | 不 reload → 上面做的權限變更要等重啟才生效，中間這段是空窗期 |

★★★ **`VALIDATE PASSWORD` 三個等級的實際規則**：

| 等級 | 規則 | 適用 |
| --- | --- | --- |
| `0 LOW` | 長度 ≥ 8 | ★ 只擋得住最懶的密碼 |
| `1 MEDIUM` | 長度 ≥ 8 ＋ 數字 ＋ 大小寫 ＋ 特殊字元 | ★★★ **機關建議：MEDIUM ＋ 長度拉到 12** |
| `2 STRONG` | MEDIUM ＋ 比對字典檔 | ★★ 需自備 `validate_password.dictionary_file`，否則等同 MEDIUM |

```sql
-- ★★ 調整長度（MEDIUM + 12 碼）
SET GLOBAL validate_password.policy = MEDIUM;
SET GLOBAL validate_password.length = 12;
SHOW VARIABLES LIKE 'validate_password%';
```

```text
| validate_password.length             | 12     |
| validate_password.policy             | MEDIUM |
| validate_password.special_char_count | 1      |
```

★★★ `SET GLOBAL` **重開機就沒了**，要持久化必須寫進設定檔：

```ini
# /etc/mysql/mysql.conf.d/99-hardening.cnf
[mysqld]
validate_password.policy = MEDIUM
validate_password.length = 12
```

#### ★★★★ 非互動式的等效 SQL（自動化佈建用）

`mysql_secure_installation` 是互動式的，不適合放進 Ansible 或建置腳本。
下面這段是**等效且可重複執行**的版本：

```sql
-- /root/mysql-harden.sql  ★★★ 這段可以重複跑，不會因為東西已經不在而失敗
-- ① 移除匿名帳號
DROP USER IF EXISTS ''@'localhost';
DROP USER IF EXISTS ''@'%';

-- ② 禁止 root 遠端（Ubuntu 預設本來就沒有這些帳號，保險起見）
DROP USER IF EXISTS 'root'@'%';
DROP USER IF EXISTS 'root'@'::1';

-- ③ 移除 test 資料庫與它的萬用授權
DROP DATABASE IF EXISTS test;
DELETE FROM mysql.db WHERE Db = 'test' OR Db LIKE 'test\_%';

-- ④ 啟用密碼強度檢查（元件只需安裝一次，重跑會報已存在，用 IF NOT EXISTS 形式的檢查避開）
-- INSTALL COMPONENT 'file://component_validate_password';

FLUSH PRIVILEGES;
```

```bash
sudo mysql < /root/mysql-harden.sql
```

驗證（**每一項都要是空的**）：

```bash
sudo mysql -e "
SELECT user, host FROM mysql.user WHERE user = '';
SELECT user, host FROM mysql.user WHERE user = 'root' AND host <> 'localhost';
SHOW DATABASES LIKE 'test';
SELECT * FROM mysql.db WHERE Db LIKE 'test%';"
```

```text
（四個查詢全部沒有輸出 = 加固完成）      # ★★★★ 有任何一行輸出就是沒清乾淨
```

> [!warning] ★★★ 不要用 `DELETE FROM mysql.user` 刪帳號
> MySQL 8 把帳號資訊放在記憶體中的權限快取，**直接 `DELETE` 資料表不會同步快取**，
> 會出現「帳號在表裡已經不見了，卻還是登得進來」的詭異狀態。
> 一律用 `DROP USER`。只有 `mysql.db` 這種授權表在移除 `test` 授權時才需要 `DELETE`，
> 而且後面一定要接 `FLUSH PRIVILEGES`。

> [!info]- `mysql_secure_installation --use-default` 可以嗎？
> 這個旗標會用預設答案跑完全部題目、不做互動，但**它不設 root 密碼**，
> 而且各版本對「預設答案」的定義不完全一致。
> ★★★ 自動化佈建請用上面那段明確的 SQL —— **你要能在交付文件上寫出「我做了哪五件事」**，
> 而不是「我跑了一個帶預設值的腳本」。

---

## 基礎設定

### ★★★★ 字元集與定序：這一節決定資料會不會壞

#### `utf8` 是 3-byte 的假貨

```text
  MySQL 的 "utf8"  = utf8mb3 = 每字元最多 3 bytes
                     ↑ 已棄用，只是為了相容而保留的別名
  真正的 UTF-8      = utf8mb4 = 每字元最多 4 bytes

  3 bytes 放不下的東西：
    emoji            😀 🇹🇼 ✅          → 全部
    罕用中文（擴充B） 𠀋 𡈽 𠮷           → 姓名欄位真的會遇到
```

**存進 `utf8mb3` 欄位會發生什麼**：

```sql
-- 嚴格模式（MySQL 8 預設）：直接拒絕，資料沒進去
INSERT INTO t (name) VALUES ('王小明 😀');
```

```text
ERROR 1366 (HY000): Incorrect string value: '\xF0\x9F\x98\x80' for column 'name' at row 1
```

★★★★★ 但如果有人把 `sql_mode` 放寬、或是欄位是 `latin1`，就**不會報錯**，
資料會被靜默寫成 `????` —— **原始 bytes 已經丟失，事後無論如何都救不回來**。
這是本篇唯一一個「做錯就沒有補救辦法」的項目。

#### 定序怎麼選

| 定序 | 出處 | 特性 | 建議 |
| --- | --- | --- | --- |
| `utf8mb4_0900_ai_ci` | **MySQL 8 預設** | UCA 9.0.0，準確且較快；**MariaDB 與 MySQL 5.7 沒有** | ★★★★ **只在 MySQL 8+ 的封閉環境用** |
| `utf8mb4_unicode_ci` | MySQL 5.x 起、MariaDB 也有 | UCA 4.0.0，稍慢但**跨版本通用** | ★★★★ **要與 MariaDB／舊版互通就用它** |
| `utf8mb4_general_ci` | 舊專案常見 | 不是真正的 UCA，排序不準 | ★★ 新專案不要用 |
| `utf8mb4_bin` | — | 區分大小寫與腔調 | ★★ 帳號、雜湊值欄位可考慮 |

★★★★ **選錯定序最痛的一刻是搬家的時候**：

```bash
# 從 MySQL 8 匯出，想匯進 MariaDB 或 5.7
mysql -u root mariadb_host < dump.sql
```

```text
ERROR 1273 (HY000) at line 25: Unknown collation: 'utf8mb4_0900_ai_ci'
```

```bash
# ★★★ 急救：把 dump 裡的定序換掉（僅限應急，正確做法是一開始就選對）
sed -i -e 's/utf8mb4_0900_ai_ci/utf8mb4_unicode_ci/g' \
       -e 's/CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci/CHARSET=utf8mb4/g' dump.sql
```

★★★ **定序還會改變資料的正確性**，不只是排序：
`utf8mb4_0900_ai_ci` 的 `ai`（accent-insensitive）與 `ci`（case-insensitive）
會讓 `'a' = 'A'`、`'e' = 'é'`，所以 **`UNIQUE` 索引會把它們視為重複**。
帳號欄位若不想讓 `Admin` 與 `admin` 撞號，要單獨指定 `utf8mb4_bin` 或 `utf8mb4_0900_as_cs`。

#### 索引長度 3072 bytes 與 Laravel 的 191

```text
  InnoDB 單一索引的 key prefix 上限
    DYNAMIC / COMPRESSED row format（MySQL 8 預設）  → 3072 bytes → utf8mb4 可索引 768 字元
    COMPACT / REDUNDANT（舊、或 5.6 未開 large_prefix）→  767 bytes → utf8mb4 可索引 191 字元
                                                                        ↑ Laravel 191 的由來
```

```text
SQLSTATE[42000]: Syntax error or access violation: 1071
Specified key was too long; max key length is 767 bytes
```

看到這個錯誤時的判斷：

```sql
SELECT @@innodb_default_row_format;
```

```text
+-----------------------------+
| @@innodb_default_row_format |
+-----------------------------+
| dynamic                     |     # ★★★ 是 dynamic 就不需要 191 這個 workaround
+-----------------------------+
```

★★★ **在 MySQL 8 上，Laravel 的 `Schema::defaultStringLength(191)` 已經沒有必要**。
留著它的代價是所有 `string` 欄位被砍到 191 字元 —— email、URL、檔名欄位會爆。
新專案請把 `app/Providers/AppServiceProvider.php` 裡那行拿掉；
既有專案要拿掉前先確認資料表的 row format，見 [[04-Laravel-Eloquent與資料庫]]。

#### 正確的做法：三個層次都要對

```ini
# /etc/mysql/mysql.conf.d/99-charset.cnf   ★★★★ ① 伺服器層
[mysqld]
character-set-server = utf8mb4
collation-server     = utf8mb4_0900_ai_ci

[client]
default-character-set = utf8mb4

[mysql]
default-character-set = utf8mb4
```

```sql
-- ★★★★ ② 建庫的當下就指定，不要靠繼承
CREATE DATABASE appdb
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;
```

```php
// ★★★★ ③ 連線層：伺服器對了但連線用 latin1，一樣是亂碼
// Laravel .env
// DB_CHARSET=utf8mb4
// DB_COLLATION=utf8mb4_0900_ai_ci
$pdo = new PDO('mysql:host=127.0.0.1;dbname=appdb;charset=utf8mb4', $user, $pass);
```

驗證：

```bash
sudo mysql -e "SHOW VARIABLES LIKE 'character\_set\_%'; SHOW VARIABLES LIKE 'collation%';"
```

```text
| character_set_client     | utf8mb4            |
| character_set_connection | utf8mb4            |
| character_set_database   | utf8mb4            |
| character_set_filesystem | binary             |   # ★ 這個是 binary 才正常
| character_set_results    | utf8mb4            |
| character_set_server     | utf8mb4            |   # ★★★★ 這行是 latin1 就要立刻處理
| character_set_system     | utf8mb3            |   # ★ 系統資料表，正常
| collation_server         | utf8mb4_0900_ai_ci |
```

> [!danger] ★★★★★ 事後才改字元集的代價
> - `ALTER DATABASE ... CHARACTER SET utf8mb4` **只改「之後才建立的表」的預設值**，既有表原封不動。
> - 既有表要逐張 `ALTER TABLE t CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;`，
>   這會**重建整張表**：大表要數十分鐘、佔用等量磁碟、期間效能明顯下降。
> - 如果原本是 `latin1` 卻塞進了 UTF-8 bytes（雙重編碼），直接 `CONVERT` 會**把亂碼變成正式亂碼**，
>   正確做法是 `mysqldump --default-character-set=latin1` 匯出後改標頭再匯入。
> - **已經變成 `????` 的資料，任何方法都救不回來。**
>   所以這一節要在建庫的那一秒做對，不是「上線後再說」。

---

### ★★★★ 時區：稽核紀錄對不上的源頭

```bash
sudo mysql -e "SELECT @@global.time_zone, @@session.time_zone, NOW(), UTC_TIMESTAMP();"
```

```text
+--------------------+---------------------+---------------------+---------------------+
| @@global.time_zone | @@session.time_zone | NOW()               | UTC_TIMESTAMP()     |
+--------------------+---------------------+---------------------+---------------------+
| SYSTEM             | SYSTEM              | 2026-08-28 09:31:07 | 2026-08-28 01:31:07 |
+--------------------+---------------------+---------------------+---------------------+
```

`SYSTEM` 代表「跟著作業系統的 `/etc/localtime`」。★★★ 問題是它**跟著 OS 變**：
有人改了主機時區、或容器裡的 OS 時區是 UTC 而主機是 CST，資料庫的時間語意就跟著漂移。

#### `'+08:00'` 還是 `'Asia/Taipei'`？

```sql
SET GLOBAL time_zone = 'Asia/Taipei';
```

```text
ERROR 1298 (HY000): Unknown or incorrect time zone: 'Asia/Taipei'     # ★★★★ 沒匯時區表就會這樣
```

要用具名時區，必須先把系統的 zoneinfo 匯進 `mysql` 資料庫：

```bash
sudo mysql_tzinfo_to_sql /usr/share/zoneinfo | sudo mysql -u root mysql
```

```text
Warning: Unable to load '/usr/share/zoneinfo/iso3166.tab' as time zone. Skipping it.
Warning: Unable to load '/usr/share/zoneinfo/leap-seconds.list' as time zone. Skipping it.
Warning: Unable to load '/usr/share/zoneinfo/zone.tab' as time zone. Skipping it.
```

★★ 這幾行 Warning 是正常的（那三個檔案不是時區資料）。驗證：

```bash
sudo mysql -e "SELECT COUNT(*) AS zones FROM mysql.time_zone_name;"
```

```text
+-------+
| zones |
+-------+
|  1780 |          # ★★★ 是 0 就代表沒匯進去
+-------+
```

| 寫法 | 需要時區表 | 處理日光節約 | 建議 |
| --- | --- | --- | --- |
| `SYSTEM`（預設） | 否 | 跟著 OS | ★★ 單機可接受，容器／多機環境會漂移 |
| **`'+08:00'`** | **否** | ★★★ **不會**（台灣沒有 DST，實務上沒差） | ★★★★ **機關單一時區系統的首選：最單純、最不會被 OS 影響** |
| `'Asia/Taipei'` | **是** | 會 | ★★★ 有跨國需求、或未來可能有 DST 地區時用 |

```ini
# /etc/mysql/mysql.conf.d/99-timezone.cnf
[mysqld]
default-time-zone = '+08:00'
```

```bash
sudo systemctl restart mysql
sudo mysql -e "SELECT @@global.time_zone, NOW();"
```

```text
+--------------------+---------------------+
| @@global.time_zone | NOW()               |
+--------------------+---------------------+
| +08:00             | 2026-08-28 09:35:12 |
+--------------------+---------------------+
```

#### ★★★★ TIMESTAMP 與 DATETIME 的差別（改時區前一定要懂）

```text
  DATETIME   → 存什麼就是什麼，不做時區轉換
               改 time_zone 之後，讀出來的值【不變】

  TIMESTAMP  → 寫入時依 session time_zone 轉成 UTC 存，讀出時再轉回來
               改 time_zone 之後，讀出來的值【整批位移】
```

★★★★ 這就是「我只是改了個時區設定，結果所有歷史紀錄的時間都跑掉了」的成因。
一個系統上線後**不要再改 `time_zone`**；真的要改，先確認哪些欄位是 `TIMESTAMP`：

```sql
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'appdb' AND data_type IN ('timestamp','datetime')
ORDER BY table_name;
```

#### ★★★★ 與 Laravel `APP_TIMEZONE` 對不上的實際案例

```text
  設定：MySQL default-time-zone = '+08:00'
        Laravel .env  APP_TIMEZONE = UTC（Laravel 預設）

  流程：使用者 09:00 送出申請
          → Laravel 的 now() 產生 UTC 01:00
            → 寫進 DATETIME 欄位 → 資料庫裡是 01:00
              → 維運人員用 SELECT ... WHERE created_at >= NOW() - INTERVAL 1 HOUR 查
                → NOW() 回 09:00（+08:00）→ 查不到剛剛那筆
                  → 稽核報表少一天的資料，而且沒有人會發現
```

★★★★ **兩種一致的做法，選一種、寫進交付文件、不要混用**：

| 做法 | MySQL | Laravel | 特性 |
| --- | --- | --- | --- |
| **全站台北時間** | `default-time-zone = '+08:00'` | `APP_TIMEZONE=Asia/Taipei` | ★★★★ 直觀，`SELECT` 出來就是人看得懂的時間；機關系統建議 |
| **全站 UTC** | `default-time-zone = '+00:00'` | `APP_TIMEZONE=UTC` | ★★★ 跨時區正確，但每次查資料都要換算 |

不管選哪一種，**主機的 NTP 都必須是同步的**：

```bash
timedatectl show -p NTPSynchronized --value
```

```text
yes          # ★★★★ 是 no 的話上面所有設定都沒有意義，去看 [[28-時間同步NTP與chrony]]
```

---

### 第一次登入的健康檢查清單

★★★ 這六條是「裝完之後、交付之前」的最小驗證，每一條都要對。

```sql
-- 【1】~【4】一次查完
SELECT VERSION() AS ver, @@datadir AS datadir,
       @@character_set_server AS charset, @@collation_server AS coll,
       @@global.time_zone AS tz;
```

```text
+-------------------------+--------------+---------+--------------------+--------+
| ver                     | datadir      | charset | coll               | tz     |
+-------------------------+--------------+---------+--------------------+--------+
| 8.0.44-0ubuntu0.24.04.1 | /data/mysql/ | utf8mb4 | utf8mb4_0900_ai_ci | +08:00 |
+-------------------------+--------------+---------+--------------------+--------+
```

★★★★ 逐欄判讀：`ver` 出現 5.7 → 裝到舊套件庫；`datadir` 還在 `/var/lib/mysql` → 搬移沒成功；
`charset` 是 `latin1` 或 `utf8mb3` → **立刻停下來處理，不要開始寫資料**；
`coll` 與規劃不符 → 未來匯到 MariaDB 會失敗；`tz` 還是 `SYSTEM` → `99-timezone.cnf` 沒生效。

```sql
-- 【5】儲存引擎
SHOW ENGINES;
```

```text
+--------------------+---------+----------------------------------------------+
| Engine             | Support | Comment                                      |
+--------------------+---------+----------------------------------------------+
| InnoDB             | DEFAULT | Supports transactions, row-level locking ... |   # ★★★★ 必須是 DEFAULT
| MyISAM             | YES     | MyISAM storage engine                        |   # ★★★ 不要用來放業務資料
| MEMORY             | YES     | Hash based, stored in memory                 |
+--------------------+---------+----------------------------------------------+
```

★★★★ **`InnoDB` 不是 `DEFAULT` 的後果**：新建的表會落到 MyISAM，
**沒有交易、沒有 crash recovery、鎖是整張表** —— 斷電就是資料損毀。

```sql
-- 【6】嚴格模式（決定「壞資料會被擋下還是被靜默截斷」）
SELECT @@sql_mode;
```

```text
| ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,
  ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION |
```

★★★★ `STRICT_TRANS_TABLES` 必須在。拿掉它，超長的字串會被**靜默截斷**、
放不進去的字元會變成 `????`，而應用程式完全不會收到錯誤。
有些舊系統會要求關閉 `ONLY_FULL_GROUP_BY`，**只關那一項**，不要整個 `sql_mode` 清空。

---

### 建立第一個資料庫與應用帳號

```sql
-- ★★★ 建庫：字元集與定序【一定】要明寫，不要靠繼承
CREATE DATABASE appdb
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

-- ★★★★ 應用帳號只綁 localhost，且只授這一個庫
CREATE USER 'appuser'@'localhost' IDENTIFIED BY '<用 openssl rand 產生的強密碼>';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
  ON appdb.* TO 'appuser'@'localhost';
FLUSH PRIVILEGES;
```

```bash
# 驗證：用應用帳號實際連一次
mysql -u appuser -p appdb -e "SELECT DATABASE(), @@character_set_database, @@collation_database;"
```

```text
+------------+--------------------------+----------------------+
| DATABASE() | @@character_set_database | @@collation_database |
+------------+--------------------------+----------------------+
| appdb      | utf8mb4                  | utf8mb4_0900_ai_ci   |
+------------+--------------------------+----------------------+
```

★★★ **為什麼 `DROP` 也給了**：Laravel 的 `php artisan migrate:rollback` 需要它。
如果你的部署流程不做 rollback，就把 `DROP` 拿掉。
權限的完整設計、`%` 與 `localhost` 的差別、唯讀報表帳號怎麼開，全部在 [[02-MySQL-使用者與權限]]。

> [!warning] ★★★ `localhost` 與 `127.0.0.1` 在 MySQL 裡不是同義詞
> `mysql -h localhost` 走 **Unix socket**，`mysql -h 127.0.0.1` 走 **TCP**，
> 而 MySQL 的帳號 host 欄位是**分開比對**的。
> `'appuser'@'localhost'` 這個帳號**無法**用 `-h 127.0.0.1` 登入，錯誤是
> `ERROR 1045 (28000): Access denied for user 'appuser'@'localhost' (using password: YES)` ——
> 訊息看起來像密碼錯，其實是走錯通道。
> Laravel 的 `.env` 寫 `DB_HOST=127.0.0.1` 而帳號只開 `localhost`，就是這個症頭。

---

## 進階設定與調校

### ★★★★ 把 datadir 搬到獨立磁碟

機關交付的機器幾乎都是「系統碟小、資料另掛」。
把 `datadir` 留在 `/var/lib/mysql` 的下場是：某天 binlog 與資料把根分割區塞滿，
**MySQL 停止寫入、系統同時因為沒有空間而無法登入處理**。

前置：`/data` 已經是獨立磁碟或 LV 並且掛好了（見 [[15-磁碟分割與掛載]]）。

```bash
# ═══ 【1】停服務，確認真的停了 ═══
sudo systemctl stop mysql
systemctl is-active mysql
```

```text
inactive          # ★★★★ 不是 inactive 就不要往下做，複製到一半的資料庫是壞的
```

```bash
# ═══ 【2】複製資料（★★★ 尾端斜線與 -aX 都不能省）═══
sudo mkdir -p /data/mysql
sudo rsync -aX --info=progress2 /var/lib/mysql/ /data/mysql/
```

```text
      1,284,571,136  99%  184.22MB/s    0:00:06 (xfr#412, to-chk=0/419)
```

★★★ `-a` 才會保留擁有者、群組與權限（必須 `sudo` 執行才有效），
`-X` 保留 extended attributes（RHEL 的 SELinux 標籤靠它）。
**來源尾端的 `/` 代表「複製目錄內容」**，漏掉會變成 `/data/mysql/mysql/`。

```bash
# ═══ 【3】確認權限 ═══
sudo chown -R mysql:mysql /data/mysql && sudo chmod 750 /data/mysql
ls -ld /data/mysql
```

```text
drwxr-x--- 8 mysql mysql 4096  8月 28 09:52 /data/mysql
```

```bash
# ═══ 【4】改設定檔 ═══
sudo cp -a /etc/mysql/mysql.conf.d/mysqld.cnf /etc/mysql/mysql.conf.d/mysqld.cnf.bak
sudo sed -i 's|^datadir.*|datadir = /data/mysql|' /etc/mysql/mysql.conf.d/mysqld.cnf
grep -n '^datadir' /etc/mysql/mysql.conf.d/mysqld.cnf
```

```text
40:datadir = /data/mysql
```

```bash
# ═══ 【5】★★★★ AppArmor —— 這一步是本節存在的理由 ═══
sudo tee /etc/apparmor.d/local/usr.sbin.mysqld >/dev/null <<'EOF'
# 允許 MySQL 使用搬移後的資料目錄
/data/mysql/ r,
/data/mysql/** rwk,
EOF

sudo apparmor_parser -r /etc/apparmor.d/usr.sbin.mysqld
sudo aa-status | grep -A1 mysqld
```

```text
   /usr/sbin/mysqld          # ★★★ 出現在 "profiles are in enforce mode" 清單裡，且沒有錯誤
```

```bash
# ═══ 【6】驗證設定沒有語法錯，再啟動 ═══
sudo -u mysql mysqld --validate-config
echo "exit=$?"
```

```text
exit=0            # ★★★ 非 0 代表設定檔有問題，訊息會直接指出哪一行
```

```bash
sudo systemctl start mysql && sudo mysql -e "SELECT @@datadir;"
```

```text
| /data/mysql/ |         # ★★★★ 搬移成功
```

```bash
# ═══ 【7】★★★ 舊目錄先改名保留，不要立刻刪 ═══
sudo mv /var/lib/mysql /var/lib/mysql.old-$(date +%F)
sudo mkdir -p /var/lib/mysql && sudo chown mysql:mysql /var/lib/mysql
```

> [!danger] ★★★★ 忘了改 AppArmor 會發生什麼（這段值得背下來）
> 服務起不來，而 `ls -l` 看起來權限完全正常：
> ```text
> Job for mysql.service failed because the control process exited with error code.
> ```
> `/var/log/mysql/error.log`：
> ```text
> [ERROR] [MY-010457] [Server] --initialize specified but the data directory has files in it.
> [ERROR] [MY-012271] [InnoDB] The innodb_system data file 'ibdata1' must be writable
> [ERROR] [MY-011071] [Server] unknown variable ...
> ```
> ★★★★ **沒有任何一行提到 AppArmor**，所以人會一直去查權限、查 SELinux、查磁碟，卻查不到。
> 真正的證據在核心日誌：
> ```bash
> sudo journalctl -k --since "5 min ago" | grep -i denied
> ```
> ```text
> audit: type=1400 apparmor="DENIED" operation="open" profile="/usr/sbin/mysqld"
>        name="/data/mysql/ibdata1" pid=5312 comm="mysqld" requested_mask="rw" denied_mask="rw"
> ```
> **看到 `apparmor="DENIED"` 就結案了。**
> 臨時確認手法（★★★ 確認完一定要改回 enforce，不要留在 complain）：
> ```bash
> sudo aa-complain /usr/sbin/mysqld && sudo systemctl start mysql   # 能起來 → 確定是 AppArmor
> sudo aa-enforce  /usr/sbin/mysqld                                  # 立刻改回來，然後去補 local 規則
> ```
> ★★★ 規則一定要寫在 **`/etc/apparmor.d/local/usr.sbin.mysqld`**，
> 直接改 `/etc/apparmor.d/usr.sbin.mysqld` 會在下次 `apt upgrade` 時被套件覆蓋，
> 於是「上個月明明好好的，昨天更新完就起不來了」。AppArmor 本身見 [[07-SELinux與AppArmor]]。

> [!info]- Rocky / AlmaLinux（RHEL 系）：改 SELinux context
> ```bash
> # ① 停服務、複製、改權限（同主線，只是服務名是 mysqld）
> $ sudo systemctl stop mysqld
> $ sudo rsync -aX /var/lib/mysql/ /data/mysql/
> $ sudo chown -R mysql:mysql /data/mysql && sudo chmod 750 /data/mysql
>
> # ② 改設定
> $ sudo sed -i 's|^datadir=.*|datadir=/data/mysql|' /etc/my.cnf.d/mysql-server.cnf
>
> # ③ ★★★★ SELinux：登記型別後套用
> $ sudo dnf install -y policycoreutils-python-utils
> $ sudo semanage fcontext -a -t mysqld_db_t "/data/mysql(/.*)?"
> $ sudo restorecon -Rv /data/mysql
>
> # ④ 驗證標籤
> $ ls -lZd /data/mysql
> drwxr-x---. mysql mysql system_u:object_r:mysqld_db_t:s0 /data/mysql
> #                                        ↑★★★★ 必須是 mysqld_db_t，是 default_t 就會被擋
>
> $ sudo systemctl start mysqld
> ```
> ★★★★ 忘了這步的症狀與 AppArmor 一模一樣（Permission denied 但權限正常），
> 證據在 `sudo ausearch -m avc -ts recent` 或 `/var/log/audit/audit.log` 的 `avc: denied`。
> ★★★ **不要用 `setenforce 0` 當解法** —— 那是把整台機器的防護關掉來換一個服務啟動。

> [!warning] ★★★ systemd 也可能擋你
> Ubuntu 的 `mysql.service` 帶有 sandbox 設定，**`datadir` 放在被保護的路徑下一樣會失敗**
> （例如放到 `/home/` 下而 unit 有 `ProtectHome=true`）。搬之前先看一眼：
> ```bash
> systemctl cat mysql | grep -E 'Protect|ReadWrite|Private'
> ```
> 需要時用 drop-in 覆寫（**不要改 `/usr/lib/systemd/system/` 下的原檔**）：
> ```bash
> sudo systemctl edit mysql      # 內容：[Service] / ReadWritePaths=/data/mysql
> sudo systemctl daemon-reload
> ```
> 這也是為什麼**資料目錄建議放 `/data`、`/srv` 這類乾淨路徑**，不要放 `/home` 或 `/root`。

---

### 解除安裝與重裝的陷阱

```bash
sudo apt purge -y mysql-server mysql-server-8.0 mysql-client-8.0 mysql-common
sudo apt autoremove -y
ls -ld /var/lib/mysql
```

```text
drwxr-x--- 8 mysql mysql 4096  8月 28 09:52 /var/lib/mysql     # ★★★★ purge 之後它【還在】
```

★★★★ Debian 系的打包**刻意保留資料目錄**，這是為了避免誤刪資料。後果是：

```text
  「這是一台重裝過的乾淨機器」→ apt install mysql-server → 資料目錄還在 → MySQL 直接沿用
    → 舊資料庫、舊帳號、舊密碼、舊權限全部回來 → 交付文件寫「全新安裝」，實際帶著上個專案的個資與帳號
```

```bash
# ★★★ 檢查殘留（重裝前一定要做）
dpkg -l | grep -iE '^rc.*mysql'          # rc = 已移除但設定檔還在
sudo ls -l /var/lib/mysql /etc/mysql /var/log/mysql 2>/dev/null
sudo mysql -e "SHOW DATABASES;" 2>/dev/null && echo "★★★★ 舊資料庫還在！"
```

> [!danger] ★★★★★ 真的要清空前，先確認你不需要那些資料
> ```bash
> # 這三行不可逆，執行前務必先做一次完整備份並【驗證還原得回來】
> sudo systemctl stop mysql
> sudo rm -rf /var/lib/mysql /var/log/mysql /etc/mysql
> sudo apt purge -y 'mysql-*' && sudo apt autoremove -y
> ```
> 備份與**還原演練**（備份存在不等於還原得回來）見 [[05-MySQL-備份與還原]] 與 [[03-備份策略與還原演練]]。

---

### ★★★★★ root 密碼真的忘了：`--skip-grant-tables` 救援

先確認**你是不是真的需要它**：Ubuntu 上 root 是 `auth_socket`，`sudo mysql` 就進得去，
根本沒有「忘記密碼」這回事。真的需要救援的情境是 Oracle 套件庫版、RHEL 版，
或是有人把 root 改成了密碼認證又弄丟。

```bash
# ═══ 【1】★★★★★ 先切斷網路存取，救援期間資料庫【完全不設防】═══
sudo ufw deny 3306/tcp        # 或直接拔掉對外網路

# ═══ 【2】停服務 ═══
sudo systemctl stop mysql

# ═══ 【3】用 drop-in 覆寫啟動參數（★★★ 這個方法不依賴 mysqld_safe，各版本都適用）═══
sudo mkdir -p /etc/systemd/system/mysql.service.d
sudo tee /etc/systemd/system/mysql.service.d/rescue.conf >/dev/null <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/sbin/mysqld --skip-grant-tables --skip-networking
EOF
sudo systemctl daemon-reload
sudo systemctl start mysql
```

```bash
# ═══ 【4】進去改密碼（★★★ skip-grant-tables 下必須先 FLUSH PRIVILEGES 才能用 ALTER USER）═══
mysql -u root
```

```sql
FLUSH PRIVILEGES;
ALTER USER 'root'@'localhost' IDENTIFIED WITH auth_socket;
-- 或者：ALTER USER 'root'@'localhost' IDENTIFIED WITH caching_sha2_password BY '<新密碼>';
EXIT;
```

```bash
# ═══ 【5】★★★★ 立刻移除救援設定，不要留 ═══
sudo systemctl stop mysql
sudo rm -f /etc/systemd/system/mysql.service.d/rescue.conf
sudo rmdir --ignore-fail-on-non-empty /etc/systemd/system/mysql.service.d
sudo systemctl daemon-reload
sudo systemctl start mysql
sudo ufw delete deny 3306/tcp

# ═══ 【6】驗證恢復正常 ═══
systemctl show mysql -p ExecStart --value | head -1
sudo mysql -e "SELECT user, host, plugin FROM mysql.user WHERE user='root';"
```

> [!danger] ★★★★★ 救援期間這台機器等於沒有資料庫權限控管
> `--skip-grant-tables` 的意思是**完全不載入權限表**：任何能連上 MySQL 的人都是超級使用者，
> 可以讀走全部個資、可以 `DROP DATABASE`。
> MySQL 8 在啟用 `--skip-grant-tables` 時會自動一併啟用 `--skip-networking`，
> 但**不要依賴這個預設** —— 明確寫出來、同時關掉防火牆的 3306、
> 並且**把救援時間壓到最短**（目標五分鐘內）。
> 機關環境還要留一筆紀錄：誰、什麼時候、為什麼做了這次救援，見 [[04-備份災難復原與入侵應變]]。

---

## 完整實戰範例

**情境**：機關新採購的伺服器，Ubuntu 24.04 全新交付，要架設某業務系統的 Laravel 資料庫。
`/dev/sdb` 已掛在 `/data`。要求：MySQL 8、非互動加固、`datadir` 在 `/data/mysql`、
`utf8mb4` ＋ 台北時間、建立 `appdb` 與 `appuser`，並產出可貼進交付單的驗收結果。

### 佈建腳本

```bash
sudo install -m 700 /dev/null /usr/local/bin/mysql-bootstrap.sh
sudo vim /usr/local/bin/mysql-bootstrap.sh
```

```bash
#!/usr/bin/env bash
# /usr/local/bin/mysql-bootstrap.sh
# 用途：Ubuntu 22.04/24.04 全新機器的 MySQL 8 佈建（安裝 → 加固 → 搬 datadir → 字元集/時區 → 建庫）
# 用法：sudo mysql-bootstrap.sh /data/mysql appdb appuser
# ★★★★ 本腳本設計為【只在全新機器執行一次】。偵測到既有資料庫會中止。
set -euo pipefail

NEW_DATADIR="${1:-/data/mysql}"
DB_NAME="${2:-appdb}"
DB_USER="${3:-appuser}"
OLD_DATADIR="/var/lib/mysql"
CNF_DIR="/etc/mysql/mysql.conf.d"
STAMP="$(date +%F-%H%M%S)"
BACKUP_DIR="/root/mysql-bootstrap-${STAMP}"
LOG="/var/log/mysql-bootstrap-${STAMP}.log"

log()  { echo -e "\n═══ $* ═══" | tee -a "$LOG"; }
info() { echo "    $*" | tee -a "$LOG"; }
die()  { echo "✘ 失敗：$*" | tee -a "$LOG" >&2; echo "  回滾方式見腳本尾端說明" >&2; exit 1; }

# ── 0. 前置檢查 ───────────────────────────────────────────────
preflight() {
  log "0. 前置檢查"
  [[ $EUID -eq 0 ]] || die "必須用 root 執行"
  [[ -d "$(dirname "$NEW_DATADIR")" ]] || die "$(dirname "$NEW_DATADIR") 不存在，請先掛好資料碟"

  # ★★★★ 防呆：purge 沒刪乾淨的舊資料目錄
  if [[ -f "${OLD_DATADIR}/ibdata1" ]] && systemctl is-active --quiet mysql; then
    if mysql -N -e "SHOW DATABASES;" 2>/dev/null | grep -qvE '^(information_schema|performance_schema|mysql|sys)$'; then
      die "偵測到既有的使用者資料庫，這不是一台乾淨的機器。請先確認資料歸屬後手動處理。"
    fi
  fi

  local avail
  avail=$(df -BG --output=avail "$(dirname "$NEW_DATADIR")" | tail -1 | tr -dc '0-9')
  [[ "$avail" -ge 20 ]] || die "$(dirname "$NEW_DATADIR") 可用空間只有 ${avail}G，至少要 20G"

  timedatectl show -p NTPSynchronized --value | grep -q yes \
    || info "★★★★ 警告：NTP 未同步，時間相關的稽核紀錄會不可靠"
  info "OK：datadir=${NEW_DATADIR} db=${DB_NAME} user=${DB_USER} 可用空間=${avail}G"
}

# ── 1. 安裝 ───────────────────────────────────────────────────
install_mysql() {
  log "1. 安裝 mysql-server"
  if dpkg -s mysql-server >/dev/null 2>&1; then
    info "已安裝，跳過：$(mysql --version)"
  else
    DEBIAN_FRONTEND=noninteractive apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq mysql-server || die "apt 安裝失敗"
    info "已安裝：$(mysql --version)"
  fi
  systemctl is-active --quiet mysql || systemctl start mysql || die "MySQL 無法啟動"
}

# ── 2. 非互動加固 ─────────────────────────────────────────────
harden() {
  log "2. 加固（等效於 mysql_secure_installation）"
  mysql <<'SQL' || die "加固 SQL 執行失敗"
DROP USER IF EXISTS ''@'localhost';
DROP USER IF EXISTS ''@'%';
DROP USER IF EXISTS 'root'@'%';
DROP USER IF EXISTS 'root'@'::1';
DROP DATABASE IF EXISTS test;
DELETE FROM mysql.db WHERE Db = 'test' OR Db LIKE 'test\_%';
FLUSH PRIVILEGES;
SQL
  info "匿名帳號／root 遠端／test 庫：已移除"
}

# ── 3. 搬移 datadir（含 AppArmor）─────────────────────────────
move_datadir() {
  log "3. 搬移 datadir → ${NEW_DATADIR}"
  local cur; cur=$(mysql -N -B -e "SELECT @@datadir;" | sed 's:/*$::')
  if [[ "$cur" == "${NEW_DATADIR%/}" ]]; then info "已經在目標位置，跳過"; return 0; fi

  mkdir -p "$BACKUP_DIR"
  cp -a "${CNF_DIR}/mysqld.cnf" "${BACKUP_DIR}/mysqld.cnf"           # ★ 回滾用
  [[ -f /etc/apparmor.d/local/usr.sbin.mysqld ]] \
    && cp -a /etc/apparmor.d/local/usr.sbin.mysqld "${BACKUP_DIR}/apparmor.local"

  systemctl stop mysql
  [[ "$(systemctl is-active mysql)" == "inactive" ]] || die "MySQL 沒有真的停止，中止搬移"

  mkdir -p "$NEW_DATADIR"
  rsync -aX "${OLD_DATADIR}/" "${NEW_DATADIR}/" || die "rsync 失敗，原資料未動，直接 systemctl start mysql 即可回復"
  chown -R mysql:mysql "$NEW_DATADIR"
  chmod 750 "$NEW_DATADIR"

  sed -i "s|^datadir.*|datadir = ${NEW_DATADIR}|" "${CNF_DIR}/mysqld.cnf"

  # ★★★★ AppArmor：寫在 local/ 才不會被套件升級覆蓋
  cat > /etc/apparmor.d/local/usr.sbin.mysqld <<EOF
# mysql-bootstrap.sh 產生於 ${STAMP}
${NEW_DATADIR}/ r,
${NEW_DATADIR}/** rwk,
EOF
  apparmor_parser -r /etc/apparmor.d/usr.sbin.mysqld || die "AppArmor profile 重新載入失敗"
  info "AppArmor local 規則已套用"
}

# ── 4. 字元集與時區 ───────────────────────────────────────────
configure() {
  log "4. 字元集 utf8mb4 與時區 +08:00"
  cat > "${CNF_DIR}/99-project.cnf" <<'EOF'
# ★★★★ 本檔由 mysql-bootstrap.sh 產生；99- 開頭確保最後載入、覆蓋前面的設定
[mysqld]
character-set-server = utf8mb4
collation-server     = utf8mb4_0900_ai_ci
default-time-zone    = '+08:00'
bind-address         = 127.0.0.1
validate_password.policy = MEDIUM
validate_password.length = 12

[client]
default-character-set = utf8mb4

[mysql]
default-character-set = utf8mb4
EOF
  sudo -u mysql mysqld --validate-config || die "設定檔語法錯誤，請看上方訊息；回滾：rm ${CNF_DIR}/99-project.cnf"
  systemctl start mysql || die "MySQL 啟動失敗，先看 journalctl -u mysql -n 50 與 journalctl -k | grep DENIED"
  sleep 2
  mysql -e "SELECT 1;" >/dev/null || die "MySQL 起來了但無法連線"
  info "已套用並成功啟動"
}

# ── 5. 建庫與應用帳號 ─────────────────────────────────────────
create_db() {
  log "5. 建立 ${DB_NAME} 與 ${DB_USER}"
  local pw; pw="$(openssl rand -base64 18)"
  mysql <<SQL || die "建庫失敗"
CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${pw}';
ALTER USER '${DB_USER}'@'localhost' IDENTIFIED BY '${pw}';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
  ON \`${DB_NAME}\`.* TO '${DB_USER}'@'localhost';
FLUSH PRIVILEGES;
SQL
  umask 077
  printf 'DB_DATABASE=%s\nDB_USERNAME=%s\nDB_PASSWORD=%s\n' "$DB_NAME" "$DB_USER" "$pw" \
    > "${BACKUP_DIR:-/root}/db-credentials.txt" 2>/dev/null \
    || printf 'DB_PASSWORD=%s\n' "$pw" > /root/db-credentials.txt
  info "帳號密碼已寫入 ${BACKUP_DIR:-/root}/db-credentials.txt（600），★★★★ 交付後請立即安全傳遞並刪除"
}

main() {
  preflight; install_mysql; harden; move_datadir; configure; create_db
  log "完成，接著執行驗收：/usr/local/bin/mysql-postinstall-check.sh"
  info "設定備份在 ${BACKUP_DIR}，舊資料仍在 ${OLD_DATADIR}（確認一週後再刪）"
}
main "$@"

# ═══ 回滾方式 ═══════════════════════════════════════════════════
#  systemctl stop mysql
#  cp -a /root/mysql-bootstrap-<STAMP>/mysqld.cnf /etc/mysql/mysql.conf.d/mysqld.cnf
#  rm -f /etc/mysql/mysql.conf.d/99-project.cnf
#  rm -f /etc/apparmor.d/local/usr.sbin.mysqld   # 或還原 apparmor.local
#  apparmor_parser -r /etc/apparmor.d/usr.sbin.mysqld
#  systemctl start mysql        # 資料仍在 /var/lib/mysql，服務回到搬移前的狀態
```

### 驗收腳本

```bash
sudo install -m 755 /dev/null /usr/local/bin/mysql-postinstall-check.sh
sudo vim /usr/local/bin/mysql-postinstall-check.sh
```

```bash
#!/usr/bin/env bash
# /usr/local/bin/mysql-postinstall-check.sh
# 用途：MySQL 交付前驗收，輸出可直接貼進交付單
# 用法：sudo mysql-postinstall-check.sh [資料庫名]
# 離開碼：0 = 全數通過；1 = 有 FAIL
set -uo pipefail          # ★ 這裡刻意不用 -e，要把所有項目都跑完再統計

DB="${1:-appdb}"
FAIL=0; WARN=0
q() { mysql -N -B -e "$1" 2>/dev/null; }

ok()   { printf '  [ OK ] %-34s %s\n' "$1" "$2"; }
bad()  { printf '  [FAIL] %-34s %s\n' "$1" "$2"; FAIL=$((FAIL+1)); }
warn() { printf '  [WARN] %-34s %s\n' "$1" "$2"; WARN=$((WARN+1)); }
check(){ [[ "$2" == "$3" ]] && ok "$1" "$2" || bad "$1" "實際=$2 應為=$3"; }

echo "═══════════════════════════════════════════════════════════════"
echo " MySQL 交付驗收報告   主機：$(hostname)   時間：$(date '+%F %T %Z')"
echo "═══════════════════════════════════════════════════════════════"

mysql -e "SELECT 1;" >/dev/null 2>&1 || { echo "  [FAIL] 無法連線至 MySQL，後續檢查中止"; exit 1; }

echo "── 基本資訊 ──"
ok "版本"            "$(q 'SELECT VERSION();')"
ok "服務狀態"        "$(systemctl is-active mysql) / $(systemctl is-enabled mysql)"
ok "資料目錄"        "$(q 'SELECT @@datadir;')"
ok "資料目錄可用空間" "$(df -h "$(q 'SELECT @@datadir;')" | tail -1 | awk '{print $4}')"

echo "── 字元集與定序 ──"
check "character_set_server"  "$(q "SELECT @@character_set_server;")" "utf8mb4"
check "collation_server"      "$(q "SELECT @@collation_server;")"     "utf8mb4_0900_ai_ci"
if q "SHOW DATABASES;" | grep -qx "$DB"; then
  check "${DB} 字元集" \
    "$(q "SELECT default_character_set_name FROM information_schema.schemata WHERE schema_name='${DB}';")" "utf8mb4"
else
  warn "${DB} 資料庫" "不存在（若尚未建置屬正常）"
fi

echo "── 時區 ──"
TZ_NOW="$(q 'SELECT @@global.time_zone;')"
[[ "$TZ_NOW" == "SYSTEM" ]] && warn "global.time_zone" "SYSTEM（建議明確指定 +08:00）" \
                            || ok   "global.time_zone" "$TZ_NOW"
ok "資料庫目前時間"  "$(q 'SELECT NOW();')"
ok "作業系統時間"    "$(date '+%F %T')"
[[ "$(timedatectl show -p NTPSynchronized --value)" == "yes" ]] \
  && ok "NTP 同步" "yes" || bad "NTP 同步" "no（稽核時間不可信）"

echo "── 引擎與模式 ──"
check "InnoDB 為預設引擎" \
  "$(q "SELECT support FROM information_schema.engines WHERE engine='InnoDB';")" "DEFAULT"
q 'SELECT @@sql_mode;' | grep -q STRICT_TRANS_TABLES \
  && ok "STRICT_TRANS_TABLES" "已啟用" || bad "STRICT_TRANS_TABLES" "未啟用，壞資料會被靜默截斷"

echo "── 安全項目 ──"
BIND="$(q "SELECT @@bind_address;")"
[[ "$BIND" == "127.0.0.1" ]] && ok "bind-address" "$BIND" \
                             || warn "bind-address" "$BIND（非 127.0.0.1，確認是否刻意開放）"
check "匿名帳號數"     "$(q "SELECT COUNT(*) FROM mysql.user WHERE user='';")" "0"
check "root 遠端帳號數" "$(q "SELECT COUNT(*) FROM mysql.user WHERE user='root' AND host<>'localhost';")" "0"
check "test 資料庫"     "$(q "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name='test';")" "0"
check "test 殘留授權"   "$(q "SELECT COUNT(*) FROM mysql.db WHERE Db LIKE 'test%';")" "0"
check "無密碼帳號數"    "$(q "SELECT COUNT(*) FROM mysql.user WHERE authentication_string='' AND plugin NOT IN ('auth_socket','mysql_no_login');")" "0"
ok "root 認證方式"     "$(q "SELECT plugin FROM mysql.user WHERE user='root' AND host='localhost';")"
[[ -f /etc/mysql/debian.cnf ]] && ok "debian.cnf 權限" "$(stat -c '%a %U:%G' /etc/mysql/debian.cnf)" \
                               || warn "debian.cnf" "不存在（非 Ubuntu 打包時屬正常）"

echo "═══════════════════════════════════════════════════════════════"
if [[ $FAIL -eq 0 ]]; then
  echo " 結果：通過（WARN ${WARN} 項，需在交付單說明）"; exit 0
else
  echo " 結果：★★★★ 未通過 —— FAIL ${FAIL} 項、WARN ${WARN} 項，不可交付"; exit 1
fi
```

### 執行

```bash
sudo /usr/local/bin/mysql-bootstrap.sh /data/mysql appdb appuser
sudo /usr/local/bin/mysql-postinstall-check.sh appdb
```

預期輸出：

```text
═══════════════════════════════════════════════════════════════
 MySQL 交付驗收報告   主機：db01   時間：2026-08-28 10:24:11 CST
═══════════════════════════════════════════════════════════════
── 基本資訊 ──
  [ OK ] 版本                               8.0.44-0ubuntu0.24.04.1
  [ OK ] 服務狀態                           active / enabled
  [ OK ] 資料目錄                           /data/mysql/    （可用 473G）
── 字元集與定序 ──
  [ OK ] character_set_server               utf8mb4
  [ OK ] collation_server                   utf8mb4_0900_ai_ci
  [ OK ] appdb 字元集                       utf8mb4
── 時區 ──
  [ OK ] global.time_zone                   +08:00
  [ OK ] NTP 同步                           yes
── 引擎與模式 ──
  [ OK ] InnoDB 為預設引擎                  DEFAULT
  [ OK ] STRICT_TRANS_TABLES                已啟用
── 安全項目 ──
  [ OK ] bind-address                       127.0.0.1
  [ OK ] 匿名帳號數 / root 遠端 / test 庫   0 / 0 / 0
  [ OK ] test 殘留授權 / 無密碼帳號         0 / 0
  [ OK ] root 認證方式                      auth_socket
  [ OK ] debian.cnf 權限                    600 root:root
═══════════════════════════════════════════════════════════════
 結果：通過（WARN 0 項，需在交付單說明）
```

### 驗收檢查表

| # | 檢查項 | 指令 | 預期結果 | ★ |
| --- | --- | --- | --- | --- |
| 1 | 服務啟動且開機自啟 | `systemctl is-active mysql; systemctl is-enabled mysql` | `active` / `enabled` | ★★★ |
| 2 | 版本符合交付文件 | `mysql --version` | 與文件一致 | ★★ |
| 3 | **字元集** | `SELECT @@character_set_server;` | `utf8mb4` | ★★★★ |
| 4 | **定序** | `SELECT @@collation_server;` | `utf8mb4_0900_ai_ci` | ★★★★ |
| 5 | 目標庫字元集 | `information_schema.schemata` | `utf8mb4` | ★★★★ |
| 6 | **時區** | `SELECT @@global.time_zone;` | `+08:00`（非 `SYSTEM`） | ★★★★ |
| 7 | NTP 同步 | `timedatectl` | `synchronized: yes` | ★★★★ |
| 8 | **datadir 位置與空間** | `SELECT @@datadir;` ＋ `df -h` | `/data/mysql/`、可用 > 20G | ★★★ |
| 9 | **監聽位址** | `ss -lntp \| grep 3306` | `127.0.0.1:3306` | ★★★★ |
| 10 | InnoDB 為預設 | `SHOW ENGINES;` | `InnoDB DEFAULT` | ★★★★ |
| 11 | 嚴格模式 | `SELECT @@sql_mode;` | 含 `STRICT_TRANS_TABLES` | ★★★★ |
| 12 | 匿名帳號 | `mysql.user WHERE user=''` | 0 筆 | ★★★★ |
| 13 | root 遠端 | `mysql.user WHERE user='root' AND host<>'localhost'` | 0 筆 | ★★★★★ |
| 14 | test 庫與授權 | `SHOW DATABASES LIKE 'test'` | 0 筆 | ★★★ |
| 15 | 無密碼帳號 | `authentication_string=''` | 0 筆 | ★★★★★ |
| 16 | **AppArmor 正常** | `aa-status \| grep mysqld`、`journalctl -k \| grep DENIED` | enforce、無 DENIED | ★★★★ |
| 17 | **備份已排程且還原演練過** | 見 [[05-MySQL-備份與還原]] | 有還原演練紀錄 | ★★★★★ |

★★★★★ 第 17 項是交付單上最常被跳過、也最會出事的一項。
**沒有做過還原演練的備份，不能算數。**

---

## 常見錯誤與排錯

| 現象／錯誤 | 原因 | 解法 |
| --- | --- | --- |
| **`ERROR 1698 (28000): Access denied for user 'root'@'localhost'`** ★★★★ | root 是 `auth_socket`，密碼根本沒被檢查 | 用 `sudo mysql`；要非互動存取就另建專用帳號，不要改 root |
| **`ERROR 1273 (HY000): Unknown collation: 'utf8mb4_0900_ai_ci'`** ★★★★ | MySQL 8 的 dump 匯進 MariaDB 或 5.7 | 目標端無此定序；`sed` 換成 `utf8mb4_unicode_ci`，並檢討建庫時的定序選擇 |
| **中文、emoji 存進去變成 `????` 或全形問號** ★★★★★ | 欄位或連線是 `utf8mb3`／`latin1` | **已損毀的資料救不回來**；改欄位 `CONVERT TO CHARACTER SET utf8mb4` 並修正連線 charset |
| **搬完 datadir 後起不來，`Permission denied` 但 `ls -l` 權限正常** ★★★★ | AppArmor（RHEL 為 SELinux）沒放行新路徑 | `journalctl -k \| grep DENIED` 確認；補 `/etc/apparmor.d/local/usr.sbin.mysqld` 後 `apparmor_parser -r` |
| **`ERROR 1298 (HY000): Unknown or incorrect time zone: 'Asia/Taipei'`** ★★★★ | 沒匯入時區表 | `mysql_tzinfo_to_sql /usr/share/zoneinfo \| mysql -u root mysql`，或改用 `'+08:00'` |
| **稽核紀錄時間差 8 小時** ★★★★ | MySQL `time_zone` 與 `APP_TIMEZONE` 不一致 | 兩端統一；注意 `TIMESTAMP` 欄位在改時區後會整批位移 |
| **`Specified key was too long; max key length is 767 bytes`** ★★★ | 舊 row format 或沿用 Laravel 191 設定 | 確認 `innodb_default_row_format=dynamic`；MySQL 8 上移除 `defaultStringLength(191)` |
| **`ERROR 2002 (HY000): Can't connect to local MySQL server through socket`** ★★★ | 服務沒起來，或 socket 路徑與用戶端預期不同 | `systemctl status mysql`；RHEL 的 socket 在 `/var/lib/mysql/mysql.sock` |
| **`ERROR 2003 (HY000): Can't connect to MySQL server on '10.x.x.x' (111)`** ★★★ | `bind-address=127.0.0.1`（正常）或防火牆擋住 | 本機服務走 socket 即可；真要遠端請照 [[07-MySQL-安全強化]] 開，不要直接改 `0.0.0.0` |
| **`ERROR 1045 ... 'appuser'@'localhost' (using password: YES)` 但密碼確定沒錯** ★★★ | 帳號 host 不符：`-h localhost` 走 socket、`-h 127.0.0.1` 走 TCP | 建立對應 host 的帳號，或統一 `.env` 的 `DB_HOST` 寫法 |
| **`Your password does not satisfy the current policy requirements`** ★★★ | `VALIDATE PASSWORD` 元件生效中 | 改用符合規則的密碼（建議 `openssl rand -base64 18`），不要為了方便關掉檢查 |
| **`Job for mysql.service failed`，但 `error.log` 幾乎是空的** ★★★★ | 設定檔語法錯，mysqld 還沒開日誌就退出 | `sudo -u mysql mysqld --validate-config`；再看 `journalctl -u mysql -n 50` |
| **apt purge 後重裝，舊資料庫與舊帳號全在** ★★★ | `purge` 不刪 `/var/lib/mysql` | 重裝前 `ls /var/lib/mysql` 檢查；確認資料歸屬後再決定清除 |
| **`apt upgrade` 中途失敗，dpkg 卡住** ★★★ | `debian-sys-maint` 被刪或密碼與 `debian.cnf` 不同步 | 重建帳號並同步 `/etc/mysql/debian.cnf` 的密碼 |
| **啟動後幾秒又自己停掉，日誌有 `Cannot allocate memory`** ★★★ | `innodb_buffer_pool_size` 超過實體記憶體 | 先調小啟動，再依 [[04-MySQL-設定檔與調校]] 重新計算 |
| **磁碟滿了，MySQL 進入唯讀或直接停止** ★★★★ | binlog／資料在系統碟且沒設保留期 | 清 binlog、把 datadir 搬到獨立磁碟；設定 `binlog_expire_logs_seconds` |

### 排查步驟

**【1】服務到底有沒有起來**

```bash
systemctl status mysql --no-pager
```

```text
Active: failed (Result: exit-code) since Thu 2026-08-28 10:41:02 CST; 8s ago
Process: 6120 ExecStart=/usr/sbin/mysqld (code=exited, status=1/FAILURE)
```

看到 `failed` → 往【2】；看到 `active (running)` 但連不上 → 跳到【6】。

**【2】看 systemd 的紀錄（最快看到啟動失敗主因）**

```bash
sudo journalctl -u mysql -n 50 --no-pager
```

```text
mysqld[6120]: [ERROR] [MY-010119] [Server] Aborting
mysqld[6120]: [ERROR] [MY-013236] [Server] The designated data directory /data/mysql/ is unusable.
```

「`data directory ... is unusable`」→ 往【3】與【4】；
「`unknown variable`」→ 往【5】。

**【3】看 MySQL 自己的錯誤日誌（比 systemd 詳細）**

```bash
sudo tail -50 /var/log/mysql/error.log
```

```text
[ERROR] [MY-012271] [InnoDB] The innodb_system data file 'ibdata1' must be writable
[ERROR] [MY-012278] [InnoDB] The error means mysqld does not have the access rights to the directory.
```

★★★★ 這裡的 `access rights` 會**誤導你只去看檔案權限**。先確認權限：

```bash
ls -ld /data/mysql && sudo ls -l /data/mysql/ibdata1
```

```text
drwxr-x--- 8 mysql mysql     4096  8月 28 09:52 /data/mysql
-rw-r----- 1 mysql mysql 12582912  8月 28 09:52 /data/mysql/ibdata1
```

權限**看起來完全正常** → 幾乎可以確定是 MAC（AppArmor／SELinux），往【4】。

**【4】確認是不是 AppArmor 擋的**

```bash
sudo journalctl -k --since "10 min ago" | grep -i 'apparmor.*DENIED'
```

```text
audit: type=1400 apparmor="DENIED" operation="open" profile="/usr/sbin/mysqld"
       name="/data/mysql/ibdata1" pid=6120 comm="mysqld" requested_mask="rw" denied_mask="rw"
```

有輸出 → 補 `local/usr.sbin.mysqld` 規則並 `apparmor_parser -r`。
沒有輸出 → 檢查 systemd sandbox：

```bash
systemctl cat mysql | grep -E 'Protect|ReadWrite'
```

RHEL 系則改看：

```bash
sudo ausearch -m avc -ts recent | grep mysqld
```

**【5】確認設定檔本身沒有寫錯**

```bash
sudo -u mysql mysqld --validate-config; echo "exit=$?"
```

```text
2026-08-28T02:44:10.118Z 0 [ERROR] [MY-000067] [Server] unknown variable 'defaul-time-zone=+08:00'.
exit=1
```

★★★ 這支只驗證設定、**不會啟動服務**，是改完設定檔後啟動前的標準動作。
`exit=0` 但服務還是起不來 → 問題不在設定檔，回到【4】。

**【6】服務在跑但連不上：先分清是 socket 還是 TCP**

```bash
sudo ss -lntp | grep 3306 ; ls -l /var/run/mysqld/mysqld.sock
```

```text
LISTEN 0 151 127.0.0.1:3306 0.0.0.0:* users:(("mysqld",pid=6301,fd=23))
srwxrwxrwx 1 mysql mysql 0  8月 28 10:47 /var/run/mysqld/mysqld.sock
```

socket 檔不存在 → 服務其實沒完成啟動，回【2】。
socket 在但應用連不上 → 多半是 `.env` 用了 `127.0.0.1` 而帳號只開 `localhost`（或反之）。

**【7】確認帳號與 host 的組合真的存在**

```bash
sudo mysql -e "SELECT user, host, plugin FROM mysql.user WHERE user IN ('root','appuser');"
```

```text
+---------+-----------+-----------------------+
| user    | host      | plugin                |
+---------+-----------+-----------------------+
| appuser | localhost | caching_sha2_password |
| root    | localhost | auth_socket           |
+---------+-----------+-----------------------+
```

應用用 `127.0.0.1` 連但只有 `@'localhost'` → 就是它。

**【8】磁碟與記憶體（服務跑一跑自己掛掉時看這裡）**

```bash
df -h "$(sudo mysql -N -B -e 'SELECT @@datadir;')" ; free -h ; sudo journalctl -k | grep -i 'killed process'
```

```text
/dev/sdb1  500G  498G  1.2G  100% /data          # ★★★★ 磁碟滿了，MySQL 會拒絕寫入
...
kernel: Out of memory: Killed process 6301 (mysqld)   # ★★★ buffer pool 設太大
```

---

## 安全性注意事項

> [!danger] ★★★★★ 絕對不要做的事
> - **不要把 `bind-address` 改成 `0.0.0.0` 來「解決連不上」。**
>   這等於把整個資料庫（含全部個資）掛到網路上，掃描器數小時內就會找到它，
>   接著就是密碼暴力破解。要遠端存取請走 SSH tunnel 或限定來源 IP ＋ TLS，見 [[07-MySQL-安全強化]]。
> - **不要建立 `'root'@'%'` 或任何 `@'%'` 的高權限帳號。**
>   `%` 表示「從任何位址」，一旦密碼外洩就是全庫失守，而且事後查不出來源。
> - **不要用 `mysql -u root -pMyPassword` 這種寫法。**
>   密碼會出現在 `ps aux`（同機任何使用者都看得到）、shell history、
>   以及 cron 的郵件輸出裡。用 `~/.my.cnf`（600）或 `--login-path`。
> - **不要在正式機保留 `--skip-grant-tables` 的救援設定。**
>   期間資料庫完全沒有權限控管，任何連得上的人都能匯走整個資料庫。
> - **不要為了「先讓系統能跑」而關掉 `STRICT_TRANS_TABLES` 或整段清空 `sql_mode`。**
>   超長字串會被靜默截斷、無效日期會變成 `0000-00-00`，
>   而應用程式收不到任何錯誤 —— 這是最難查的資料損毀。
> - **不要用 `setenforce 0` 或 `aa-disable` 來換服務啟動。**
>   正確做法是補上該路徑的規則，五分鐘的事，別拿整台機器的防護去換。

★★★★ **機關情境的四個必辦事項**：

| 項目 | 本篇要做到的 | 延伸 |
| --- | --- | --- |
| **最小權限** | 應用帳號只綁 `localhost`、只授單一資料庫；root 維持 `auth_socket` | [[02-MySQL-使用者與權限]] |
| **傳輸加密** | 本機連線走 socket（不經網路）；跨機一律 TLS | [[07-MySQL-安全強化]] |
| **稽核軌跡** | 時區與 NTP 必須正確，否則日誌時間無法作為證據 | [[19-日誌系統]] |
| **備份加密** | 備份檔含全部個資，落地前就要加密，且要有還原演練 | [[05-MySQL-備份與還原]]、[[04-備份災難復原與入侵應變]] |

★★★★ **個資法角度的提醒**：`/var/lib/mysql`（或 `/data/mysql`）與 `mysqldump` 產出的檔案
**就是個資本體**。權限 750／600、不要放到會被 Web 伺服器讀到的路徑、
不要用 `scp` 明文丟到沒有加密的儲存空間、離職人員的帳號要一併清掉。

> [!warning] ★★★ 檔案權限的最低標準
> ```bash
> stat -c '%a %U:%G %n' /data/mysql /etc/mysql/debian.cnf /root/.my.cnf 2>/dev/null
> ```
> ```text
> 750 mysql:mysql /data/mysql
> 600 root:root /etc/mysql/debian.cnf
> 600 root:root /root/.my.cnf
> ```
> 任何一個變成 `644` 或 `755`，同機的其他使用者就能讀到密碼或資料檔。

---

## 速查表

### 服務與狀態

| 指令 | 說明 | ★ |
| --- | --- | --- |
| `sudo systemctl status mysql` | 服務狀態（RHEL 是 `mysqld`） | ★★ |
| `sudo systemctl restart mysql` | 改完設定檔後套用 | ★★ |
| `sudo journalctl -u mysql -n 50` | 啟動失敗的第一站 | ★★★★ |
| `sudo tail -50 /var/log/mysql/error.log` | MySQL 自己的日誌，比 systemd 詳細 | ★★★★ |
| `sudo -u mysql mysqld --validate-config` | **啟動前**驗證設定檔語法 | ★★★★ |
| `ss -lntp \| grep 3306` | 確認監聽位址（應為 `127.0.0.1`） | ★★★★ |
| `sudo aa-status \| grep mysqld` | AppArmor profile 是否在 enforce | ★★★ |
| `sudo journalctl -k \| grep DENIED` | 抓 AppArmor 阻擋紀錄 | ★★★★ |

### 第一次登入必查的 SQL

| SQL | 應該看到 | ★ |
| --- | --- | --- |
| `SELECT VERSION();` | 與交付文件一致 | ★★ |
| `SELECT @@datadir;` | 規劃的資料目錄 | ★★★ |
| `SELECT @@character_set_server;` | `utf8mb4` | ★★★★ |
| `SELECT @@collation_server;` | `utf8mb4_0900_ai_ci` | ★★★★ |
| `SELECT @@global.time_zone;` | `+08:00`（不是 `SYSTEM`） | ★★★★ |
| `SELECT @@sql_mode;` | 含 `STRICT_TRANS_TABLES` | ★★★★ |
| `SHOW ENGINES;` | InnoDB 為 `DEFAULT` | ★★★★ |
| `SELECT user,host,plugin FROM mysql.user;` | 無匿名、無 `@'%'` 的 root | ★★★★★ |

### 檔案路徑（Ubuntu / RHEL）

| 用途 | Ubuntu | RHEL | ★ |
| --- | --- | --- | --- |
| 要改的設定檔 | `/etc/mysql/mysql.conf.d/mysqld.cnf` | `/etc/my.cnf.d/*.cnf` | ★★★ |
| 自訂設定 | `/etc/mysql/mysql.conf.d/99-*.cnf` | `/etc/my.cnf.d/99-*.cnf` | ★★★ |
| 錯誤日誌 | `/var/log/mysql/error.log` | `/var/log/mysql/mysqld.log` | ★★★ |
| socket | `/var/run/mysqld/mysqld.sock` | `/var/lib/mysql/mysql.sock` | ★★★ |
| MAC 規則 | `/etc/apparmor.d/local/usr.sbin.mysqld` | `semanage fcontext`（`mysqld_db_t`） | ★★★★ |
| 維護帳號 | `/etc/mysql/debian.cnf`（600） | 無 | ★★★ |

### 判斷準則

| 看到 | 代表 | 該做什麼 | ★ |
| --- | --- | --- | --- |
| `ERROR 1698` | `auth_socket`，不是密碼錯 | 改用 `sudo mysql` | ★★★★ |
| `ERROR 1045` | 密碼或 host 組合真的錯 | 查 `mysql.user` 的 host 欄 | ★★★ |
| `ERROR 2002` | socket 連不上 → 服務沒起來 | 看 `systemctl status` | ★★★ |
| `ERROR 1273` | 目標端沒有這個定序 | 改用 `utf8mb4_unicode_ci` | ★★★★ |
| `ERROR 1298` | 時區表沒匯入 | `mysql_tzinfo_to_sql` 或改 `+08:00` | ★★★★ |
| 權限正常卻 `Permission denied` | AppArmor／SELinux | 查 `DENIED`／`avc` | ★★★★ |
| `character_set_server = latin1` | 建庫前沒設好 | 立刻停下來處理，不要開始寫資料 | ★★★★★ |

---

## 練習題

> [!question]- 練習 1：判讀一台接手的機器
> 你接手一台不明狀態的 MySQL 主機，請在**五分鐘內**產出一份現況摘要，
> 至少要回答：版本與來源、字元集與定序、時區、datadir 與剩餘空間、
> 有沒有匿名帳號與 `@'%'` 的高權限帳號、InnoDB 是不是預設引擎。
>
> **參考解答**
> ```bash
> mysql --version; dpkg -l | grep -E '^ii.*mysql-server' || rpm -qa | grep -i mysql
> sudo mysql -e "
> SELECT VERSION() AS ver, @@datadir AS datadir, @@global.time_zone AS tz,
>        @@character_set_server AS charset, @@collation_server AS coll, @@bind_address AS bind;
> SELECT user, host, plugin FROM mysql.user WHERE host <> 'localhost' OR user = '';
> SELECT engine, support FROM information_schema.engines WHERE support IN ('DEFAULT');
> "
> df -h "$(sudo mysql -N -B -e 'SELECT @@datadir;')"
> ss -lntp | grep 3306
> ```
> ★★★★ 判讀重點：
> ① `charset` 是 `latin1` → 這台已經在累積資料損傷，先確認欄位層級的字元集；
> ② `tz` 是 `SYSTEM` → 稽核時間不可靠，先查 `timedatectl`；
> ③ `mysql.user` 出現 `@'%'` → 資安缺失，立刻記錄並排入處理；
> ④ `bind` 是 `0.0.0.0` → 檢查防火牆與是否真的需要遠端。
> 這六項就是本篇驗收表的濃縮版，也是接手任何資料庫的標準開場。

> [!question]- 練習 2：把 datadir 搬到 `/data/mysql` 並驗證回滾可行
> 在測試機上把 `datadir` 搬到 `/data/mysql`，**故意先不改 AppArmor**，
> 記錄下錯誤訊息與你是怎麼定位到 AppArmor 的；接著修好、驗證成功，
> 再把整個變更**回滾**回 `/var/lib/mysql`，確認服務正常。
>
> **參考解答**
> 1. 停服務 → `rsync -aX /var/lib/mysql/ /data/mysql/` → `chown -R mysql:mysql` → 改 `mysqld.cnf`。
> 2. `systemctl start mysql` 失敗。`journalctl -u mysql -n 50` 顯示
>    `The designated data directory /data/mysql/ is unusable`，
>    `error.log` 說 `ibdata1 must be writable`，但 `ls -l` 權限正確。
> 3. ★★★★ 決定性證據：`sudo journalctl -k | grep DENIED` 出現
>    `apparmor="DENIED" ... name="/data/mysql/ibdata1"`。
> 4. 建立 `/etc/apparmor.d/local/usr.sbin.mysqld`（`/data/mysql/ r,` 與 `/data/mysql/** rwk,`），
>    `apparmor_parser -r /etc/apparmor.d/usr.sbin.mysqld`，重啟成功，
>    `SELECT @@datadir;` 回 `/data/mysql/`。
> 5. **回滾**：停服務 → 還原 `mysqld.cnf` 的 `datadir` → 刪除 local AppArmor 檔並 `apparmor_parser -r`
>    → 啟動 → `SELECT @@datadir;` 回 `/var/lib/mysql/`。
>    ★★★ 因為原目錄從頭到尾沒有被刪，回滾只是「改回設定」，這就是搬移時
>    **先改名保留舊目錄、一週後再刪**的價值。

> [!question]- 練習 3：字元集踩雷與救援判斷
> 在測試庫建兩張表，一張 `CHARACTER SET utf8mb3`、一張 `utf8mb4`，
> 各插入 `'王小明 😀'`，記錄兩者的結果差異。
> 接著把 `utf8mb3` 那張表 `CONVERT TO CHARACTER SET utf8mb4`，
> 回答：原本那筆資料救回來了嗎？為什麼？
>
> **參考解答**
> ```sql
> CREATE TABLE t3 (name VARCHAR(50)) CHARACTER SET utf8mb3;
> CREATE TABLE t4 (name VARCHAR(50)) CHARACTER SET utf8mb4;
> INSERT INTO t4 VALUES ('王小明 😀');   -- 成功
> INSERT INTO t3 VALUES ('王小明 😀');   -- ERROR 1366: Incorrect string value: '\xF0\x9F\x98\x80'
> ```
> ★★★★ 在 `STRICT_TRANS_TABLES` 下 `t3` 是**直接拒絕**，資料沒進去 —— 這其實是好事。
> 把 `sql_mode` 放寬（`SET SESSION sql_mode='';`）再插一次，會變成
> `王小明 ` 或 `王小明 ?`，**emoji 的 bytes 已經在寫入時被丟棄**。
> 之後 `ALTER TABLE t3 CONVERT TO CHARACTER SET utf8mb4;` 只是把**欄位定義**改成 utf8mb4，
> **已經丟失的 bytes 不會回來** —— 這就是本篇強調「建庫當下就要決定」的原因。
> ★★★★★ 結論：字元集錯誤造成的是**不可逆的資料損傷**，
> 唯一的補救是從損壞前的備份還原（所以請看 [[05-MySQL-備份與還原]]）。

---

## 小測驗

Q1. 在 Ubuntu 上 `mysql -u root -p` 得到 `ERROR 1698`，但 `sudo mysql` 可以進去。為什麼？如果改用正確密碼會成功嗎？

Q2. `ERROR 1698` 與 `ERROR 1045` 的差別是什麼？各自該往哪個方向查？

Q3. 為什麼本手冊建議**不要**把 `root@localhost` 改成 `caching_sha2_password`？如果一定要有非互動存取，正確做法是什麼？

Q4. `/etc/mysql/debian.cnf` 是什麼？把裡面的 `debian-sys-maint` 帳號刪掉會在什麼時候出事？

Q5. `utf8` 與 `utf8mb4` 差在哪？在 `STRICT_TRANS_TABLES` 開與關的情況下，把 emoji 存進 `utf8mb3` 欄位分別會發生什麼？

Q6. `utf8mb4_0900_ai_ci` 與 `utf8mb4_unicode_ci` 該怎麼選？選前者之後把 dump 匯進 MariaDB 會看到什麼錯誤？

Q7. Laravel 的 `Schema::defaultStringLength(191)` 是怎麼來的？在 MySQL 8 上還需要嗎？留著它有什麼代價？

Q8. `default-time-zone` 設 `'+08:00'` 和 `'Asia/Taipei'` 有什麼差別？後者要先做什麼？系統上線後改時區，`TIMESTAMP` 與 `DATETIME` 欄位分別會怎樣？

Q9. 搬完 `datadir` 之後服務起不來，`error.log` 說 `ibdata1 must be writable`，但 `ls -l` 顯示 `mysql:mysql` 且權限 640。你的下一個指令是什麼？為什麼規則要寫在 `local/` 底下？

Q10. `sudo apt purge mysql-server` 之後重新安裝，為什麼可能拿到「舊的資料庫與舊的 root 密碼」？這在交付情境下是什麼等級的問題？

> [!question]- 測驗答案
> **Q1.** 因為 Ubuntu 打包的 `root@localhost` 使用 **`auth_socket`** 認證外掛。
> 這個外掛**完全不檢查密碼**，它透過 Unix domain socket 取得連線端的作業系統 uid，
> 換成使用者名稱後要求「**OS 使用者名稱 = MySQL 帳號名稱**」。
> ```bash
> sudo mysql -e "SELECT user,host,plugin FROM mysql.user WHERE user='root';"
> # root | localhost | auth_socket
> ```
> `sudo mysql` 時 OS 身分是 `root`，對上 `root@localhost` → 通過；
> 一般使用者（例如 `ops`）打 `mysql -u root -p`，OS 身分是 `ops`，對不上 → 拒絕。
> ★★★★ **改用正確密碼也不會成功**，因為根本沒有在比對密碼 —— 這正是很多人卡住一小時的原因。
> 見「★★★★ root@localhost 與 auth_socket」。
>
> **Q2.** ★★★★ 這兩個錯誤碼指向完全不同的問題：
> - **`ERROR 1698 (28000)`**：認證外掛拒絕，**與密碼無關**。多半是 `auth_socket`／`unix_socket`。
>   → 往「你現在是哪個 OS 使用者」查，解法是 `sudo mysql` 或改用專用帳號。
> - **`ERROR 1045 (28000) ... (using password: YES)`**：帳號存在但認證失敗。
>   → 兩種可能：密碼真的錯，或**帳號的 host 部分對不上**。
> ```bash
> sudo mysql -e "SELECT user, host FROM mysql.user WHERE user='appuser';"
> ```
> 若只有 `appuser@localhost`，卻用 `-h 127.0.0.1` 連（走 TCP），就會是 1045。
> ★★★ 判斷口訣：**1698 查身分，1045 查 host 再查密碼**。
>
> **Q3.** 因為改了會產生**兩類連鎖損害**：
> ① **所有依賴 `sudo mysql` 的排程立刻失效** —— 備份腳本、監控採集、logrotate 的 flush，
> 而且失敗多半是靜默的（cron 的錯誤沒人看），等到要還原時才發現備份空了三個月。
> ② **密碼必須被存在某處** —— 腳本、cron、shell history、備份檔，
> 而 `auth_socket` 的優點正是「沒有密碼可以外洩，且權責跟著 `sudo` 走、有稽核軌跡」。
> ★★★★ 正確做法是**不動 root**，另建專用帳號並給最小權限：
> ```sql
> CREATE USER 'bkpuser'@'localhost' IDENTIFIED BY '<強密碼>';
> GRANT SELECT, RELOAD, PROCESS, LOCK TABLES, REPLICATION CLIENT, SHOW VIEW ON *.* TO 'bkpuser'@'localhost';
> ```
> 密碼放 `~/.my.cnf`（600）或 `--login-path`，不要寫在指令列。見 [[02-MySQL-使用者與權限]]。
>
> **Q4.** 它是 Debian／Ubuntu 打包專用的**維護帳號設定檔**，權限 `600 root:root`，
> 內含 `debian-sys-maint` 帳號的隨機密碼。套件升級時的資料字典升級、
> logrotate 的 flush logs、以及部分 postinst 動作都靠它連進 MySQL。
> ★★★★ **出事的時機是下一次 `apt upgrade`**：
> ```text
> dpkg: error processing package mysql-server-8.0 (--configure):
>  installed mysql-server-8.0 package post-installation script subprocess returned error exit status 1
> ```
> 錯誤訊息只會說「無法連線」，不會告訴你帳號被刪了，於是很難聯想。
> 同樣的症狀也會出現在「只改了 MySQL 裡的密碼、沒同步改 `debian.cnf`」的情況。
> 要改密碼**兩邊必須一起改**，見「`debian-sys-maint` 與 `/etc/mysql/debian.cnf` 不能刪」。
>
> **Q5.** MySQL 的 `utf8` 是 **`utf8mb3` 的別名，每字元最多 3 bytes**，
> 放不下 emoji 與部分罕用中文（Unicode 補充平面需要 4 bytes）；`utf8mb4` 才是完整的 UTF-8。
> - **`STRICT_TRANS_TABLES` 開啟（MySQL 8 預設）**：直接拒絕，資料沒進去 ——
>   ```text
>   ERROR 1366 (HY000): Incorrect string value: '\xF0\x9F\x98\x80' for column 'name' at row 1
>   ```
>   ★★★ 這其實是**好事**，因為錯誤會被應用程式看見。
> - **嚴格模式關閉**：★★★★★ **靜默截斷**，emoji 之後的內容被丟掉或變成 `?`，
>   應用程式收不到任何錯誤，你會在幾個月後才從使用者回報發現。
> 而且**原始 bytes 在寫入那一刻就已經丟失**，事後 `CONVERT TO CHARACTER SET utf8mb4` 也救不回來。
> 見「★★★★ 字元集與定序」。
>
> **Q6.** 判準是**「這份資料未來會不會被匯到 MariaDB 或 MySQL 5.7」**：
> - **封閉的 MySQL 8+ 環境** → `utf8mb4_0900_ai_ci`（UCA 9.0.0，較新且較快，MySQL 8 預設）。
> - **可能與 MariaDB／舊版互通** → `utf8mb4_unicode_ci`（UCA 4.0.0，兩邊都有）。
> 選了前者再匯進 MariaDB 會在建表那行直接中斷：
> ```text
> ERROR 1273 (HY000) at line 25: Unknown collation: 'utf8mb4_0900_ai_ci'
> ```
> ★★★★ 應急做法是 `sed -i 's/utf8mb4_0900_ai_ci/utf8mb4_unicode_ci/g' dump.sql`，
> 但要注意兩者的排序規則不同，唯一索引的判定可能因此改變。
> ★★★ 機關環境的 RHEL 主機預設是 MariaDB，所以「未來會不會搬到 MariaDB」不是假設性問題。
>
> **Q7.** 來自 **InnoDB 索引 key prefix 的 767 bytes 上限**：
> 舊的 `COMPACT`／`REDUNDANT` row format（或 MySQL 5.6 未開 `innodb_large_prefix`）限制 767 bytes，
> utf8mb4 每字元最多 4 bytes → `767 / 4 = 191`，所以 Laravel 早期把預設字串長度設成 191
> 來避開 `ERROR 1071: Specified key was too long`。
> ★★★ **MySQL 8 預設 `innodb_default_row_format = dynamic`，上限是 3072 bytes**（可索引 768 字元），
> ```sql
> SELECT @@innodb_default_row_format;   -- dynamic
> ```
> 所以**不再需要**這個 workaround。留著它的代價是所有 `string` 欄位被砍到 191 字元 ——
> email、URL、檔名、憑證序號欄位會不夠用，而且錯誤發生在使用者輸入時，很晚才被發現。
> 移除前先確認既有資料表的 row format，見 [[04-Laravel-Eloquent與資料庫]]。
>
> **Q8.** 差別在**要不要時區表**與**要不要處理日光節約**：
> - `'+08:00'` 是固定偏移，**不需要時區表**，不處理 DST。台灣沒有 DST，所以實務上最單純。
> - `'Asia/Taipei'` 是具名時區，**必須先匯入時區表**，否則：
>   ```text
>   ERROR 1298 (HY000): Unknown or incorrect time zone: 'Asia/Taipei'
>   ```
>   ```bash
>   sudo mysql_tzinfo_to_sql /usr/share/zoneinfo | sudo mysql -u root mysql
>   sudo mysql -e "SELECT COUNT(*) FROM mysql.time_zone_name;"   # 應該有一千多筆
>   ```
> ★★★★ **上線後改時區的後果**：`DATETIME` 存什麼就是什麼，讀出來**不變**；
> `TIMESTAMP` 寫入時轉成 UTC 存、讀出時再轉回來，所以**整批歷史資料看起來會位移**。
> 這就是「只是改了個設定，結果所有紀錄的時間都跑掉」的成因。見「★★★★ 時區」。
>
> **Q9.** 下一個指令是：
> ```bash
> sudo journalctl -k --since "10 min ago" | grep -i 'apparmor.*DENIED'
> ```
> ★★★★ 理由：**權限看起來正常卻 Permission denied**，這個組合幾乎必然是強制存取控制
> （Ubuntu 的 AppArmor、RHEL 的 SELinux）在擋。MySQL 的錯誤訊息完全不會提到 AppArmor，
> 只會說 `does not have the access rights`，所以人會一直在檔案權限上打轉。
> 預期會看到：
> ```text
> apparmor="DENIED" operation="open" profile="/usr/sbin/mysqld" name="/data/mysql/ibdata1"
> ```
> 解法是把規則寫進 **`/etc/apparmor.d/local/usr.sbin.mysqld`** 再 `apparmor_parser -r`。
> ★★★ **為什麼要寫在 `local/`**：直接改主 profile（`/etc/apparmor.d/usr.sbin.mysqld`）
> 會在下次 `apt upgrade` 被套件覆蓋，於是變成「上個月好好的，更新完就起不來」的間歇性事故；
> `local/` 是套件保證不會動的覆寫點。RHEL 對應動作是
> `semanage fcontext -a -t mysqld_db_t "/data/mysql(/.*)?"` 加 `restorecon -Rv`。
>
> **Q10.** 因為 **Debian 系的 `purge` 刻意不刪 `/var/lib/mysql`**（避免誤刪資料）：
> ```bash
> sudo apt purge -y mysql-server && ls -ld /var/lib/mysql
> # drwxr-x--- 8 mysql mysql 4096 ... /var/lib/mysql     ← 還在
> ```
> 重新安裝時 MySQL 發現資料目錄已初始化，就**直接沿用**，
> 於是舊的資料庫、舊的帳號、舊的密碼、舊的授權全部回來了。
> ★★★★★ **在交付情境下這是嚴重問題**：交付文件寫「全新安裝」，
> 實際上這台機器帶著**上一個專案的個資**與**不明帳號**，
> 前者是個資殘留、後者是未授權存取的入口，兩項都會在資安稽核時被開缺失。
> 防範方式就是本篇的驗收腳本 —— 交付前一定要跑一次
> `SHOW DATABASES;` 與 `SELECT user,host FROM mysql.user;` 並把結果附進交付單。

---

## 延伸閱讀

- [[02-MySQL-使用者與權限]] — 本篇只建了一個 `appuser`，權限設計、`%` 與 `localhost`、唯讀報表帳號在那篇
- [[04-MySQL-設定檔與調校]] — `my.cnf` 的參數（buffer pool、`max_connections`、慢查詢）與載入順序細節
- [[05-MySQL-備份與還原]] — ★★★★★ 本篇的驗收表第 17 項；**沒做過還原演練的備份不算數**
- [[07-MySQL-安全強化]] — `bind-address` 收斂、TLS 連線、稽核日誌、TWGCB 與個資法情境
- [[03-SQL基礎操作]] — 建完庫之後的第一批 SQL
- [[01-Laravel-環境需求與安裝]] — 這個資料庫要交給誰用：`.env` 的 `DB_*` 設定與 `migrate`
- [[01-範例-Nginx-PHP-MySQL]] — LXMP 四件套組起來的完整範例
- [[01-新機建置標準流程]] — 本篇的佈建與驗收腳本要掛進這份流程
- MySQL 8.4 官方安裝文件（APT）：<https://dev.mysql.com/doc/refman/8.4/en/linux-installation-apt-repo.html>
- MySQL 字元集與定序：<https://dev.mysql.com/doc/refman/8.4/en/charset.html>
- MySQL 支援週期查詢：<https://endoflife.date/mysql>
