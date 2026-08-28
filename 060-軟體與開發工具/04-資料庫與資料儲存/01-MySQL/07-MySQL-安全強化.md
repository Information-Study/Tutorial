---
title: "MySQL 安全強化"
desc: "監聽面收斂、帳號與權限盤點、以自建 CA 強制 TLS、靜態加密、稽核日誌替代方案，並產出可交稽核的符合性報告"
aliases: [MySQL hardening, bind-address, require_secure_transport, mysql-hardening-check, MySQL 加固]
tags: [群組/軟體與開發工具, 服務/mysql, 安全/資料庫, 主題/稽核, 主題/個資保護]
category: 資料庫與資料儲存
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[02-MySQL-使用者與權限]]", "[[04-MySQL-設定檔與調校]]", "[[08-用自建CA簽發伺服器憑證]]"]
updated: 2026-08-28
---

# MySQL 安全強化

> [!abstract] 這篇你會學到
> - 從**外部主機**實際驗證你的 MySQL 到底有沒有對外開放，包含幾乎每次都被忘記的 **33060（X Protocol）**
> - 把監聽面收斂到 `bind-address` + 防火牆白名單，跨機管理改走 SSH 隧道，並準備好**改錯時的回復路徑**
> - ★★★★ 換掉 MySQL 8 開機時自動產生的**自簽憑證**，用機關自建 CA 簽發資料庫憑證，分階段切到 `require_secure_transport=ON` 而**不中斷任何應用**
> - 盤點並收斂 `FILE` / `PROCESS` / `GRANT OPTION` 這類高風險權限，處理 `host='%'` 與離職帳號
> - ★★★★ 在**社群版沒有官方稽核外掛**的前提下，選一個真的做得到的稽核方案，並知道它記不到什麼
> - ★★★★★ 判斷「拿正式庫 dump 餵測試環境／交給廠商」在個資法下是什麼性質，以及正確的去識別化流程
> - 用一支 `mysql-hardening-check.sh` 產出**整改前後對照表**，直接貼進稽核回覆

## 前置知識

- [[02-MySQL-使用者與權限]] — 本篇只做**盤點與收斂**，`CREATE USER` / `GRANT` 的語法與角色設計在那一篇
- [[04-MySQL-設定檔與調校]] — `my.cnf` 的載入順序、drop-in 目錄、`SET PERSIST` 的行為
- [[08-用自建CA簽發伺服器憑證]] — 本篇會直接用機關內部 CA 簽出資料庫憑證，CA 的建置流程不在這裡重寫
- [[02-防火牆-ufw基礎與實務]] — 防火牆規則語法引用該篇，本篇只講「資料庫該放行給誰」
- [[05-SSH-隧道與埠轉發]] — 跨機管理資料庫的正確姿勢

> [!tip] 這篇不重複的內容
> - 備份的排程、加密與**還原演練**在 [[05-MySQL-備份與還原]]；本篇只講「備份檔本身是一份個資資產」這一面。
> - 複寫連線的建置在 [[06-MySQL-主從複寫]]；本篇給憑證面的完整做法，但不重寫複寫設定。
> - TWGCB 基準文件本身的解讀在 [[01-TWGCB概念與法規要求]]；本篇只講「資料庫主機怎麼對應」。
> - Wazuh 規則怎麼寫在 [[05-Wazuh-日誌蒐集與解析]]；本篇只講「要送什麼過去、要告警什麼」。

---

## 觀念說明

### 資料庫的攻擊面分層

```text
┌──────────────────────────────────────────────────────────────────┐
│ ① 網路層   誰連得到 3306 / 33060 / 33062                          │
│            bind-address、mysqlx、防火牆、SSH 隧道                  │  ← 收斂這層 CP 值最高
├──────────────────────────────────────────────────────────────────┤
│ ② 認證層   連得到之後，誰能登入                                    │
│            帳號 host 限制、密碼政策、帳號鎖定、caching_sha2         │
├──────────────────────────────────────────────────────────────────┤
│ ③ 授權層   登入之後能碰到什麼                                      │
│            最小權限、FILE/PROCESS/GRANT OPTION、一庫一帳號          │
├──────────────────────────────────────────────────────────────────┤
│ ④ 傳輸層   線上的封包能不能被看、能不能被冒充                       │
│            TLS 憑證、require_secure_transport、VERIFY_IDENTITY     │  ← ★★★★ 最容易「以為做了」
├──────────────────────────────────────────────────────────────────┤
│ ⑤ 靜態層   磁碟被搬走 / 備份檔被複製時，資料還讀不讀得出來           │
│            表空間加密、備份檔加密、LUKS                             │
├──────────────────────────────────────────────────────────────────┤
│ ⑥ 稽核層   出事之後查不查得出來                                    │
│            連線紀錄、DML 軌跡、error log、集中日誌與告警            │  ← ★★★★ 社群版最弱的一環
├──────────────────────────────────────────────────────────────────┤
│ ⑦ OS 層    mysqld 這個行程本身被壓在多小的範圍裡                    │
│            檔案權限、AppArmor/SELinux、local_infile、secure_file_priv│
└──────────────────────────────────────────────────────────────────┘
```

### 社群版做得到什麼、做不到什麼（誠實的能力邊界）

機關採購常寫「資料庫應具備稽核功能」，然後買了社群版。動筆規劃前先把這張表看完：

| 能力 | MySQL 8 社群版 | 企業版 | 社群版的替代做法 |
| --- | --- | --- | --- |
| TLS 傳輸加密 | ✅ 完整 | ✅ | — |
| InnoDB 表空間加密 | ✅（`component_keyring_file`） | ✅（另有 HSM/KMS keyring） | — |
| 密碼政策 / 帳號鎖定 | ✅（`validate_password` component） | ✅ | — |
| 連線失敗延遲 | ✅（`CONNECTION_CONTROL` plugin） | ✅ | — |
| **稽核日誌** | ❌ **沒有官方外掛** | ✅ MySQL Enterprise Audit | ★★★★ Percona Audit Log／`init_connect`／binlog + error log 送 SIEM |
| 資料遮罩（Data Masking） | ❌ | ✅ | 自寫遮罩 SQL / 檢視表 |
| 防火牆（MySQL Enterprise Firewall） | ❌ | ✅ | 前端 WAF + 最小權限 |
| 透明資料庫加密接 HSM | ❌ | ✅ | 檔案型 keyring + 金鑰另行保管 |

> [!danger] ★★★★ 稽核功能不是「之後再補」的東西
> 事故發生的那一刻，你只能用**事發前就已經在記的東西**去回答「誰撈了什麼」。
> 社群版沒有官方 audit plugin 這件事，**必須在系統上線前就決定替代方案**，
> 不然稽核回覆表上「存取軌跡」那一欄只能寫「無」。

---

## 環境準備與攻擊面自查

動任何設定之前，先把**現況**量出來。沒有整改前的基線，稽核回覆表就寫不出「整改前 / 整改後」。

### ★★★★★ 第一步：你的資料庫在不在網路上

先在**資料庫主機本機**看監聽狀態：

```bash
sudo ss -lntp | grep -E 'mysqld|3306|33060|33062'
```

**危險**的輸出長這樣：

```text
LISTEN 0  151  0.0.0.0:3306   0.0.0.0:*  users:(("mysqld",pid=1183,fd=23))   # ★★★★★ 所有介面
LISTEN 0  70   0.0.0.0:33060  0.0.0.0:*  users:(("mysqld",pid=1183,fd=35))   # ★★★★ X Protocol 也開著
```

**安全**的輸出長這樣：

```text
LISTEN 0  151  127.0.0.1:3306   0.0.0.0:*  users:(("mysqld",pid=1183,fd=23))
LISTEN 0  151  10.10.20.11:3306 0.0.0.0:*  users:(("mysqld",pid=1183,fd=24))  # ★ 只綁內網介面
```

> [!warning] ★★★ 33060 幾乎每次都被忘記
> MySQL 8 預設載入 **X Plugin**，額外開一個 **33060/tcp**（X Protocol）。
> 上游 MySQL 的 `mysqlx_bind_address` 預設是 `*` —— 你把 `bind-address` 改成內網位址、
> 以為收好了，33060 還在對外聽。
>
> 稽核掃描報表上出現「33060 未知服務對外開放」的案子，九成是這個。
> 另外 **33062** 是 `admin_port`（管理介面），只有你設了 `admin_address` 才會出現。

### 從外部主機驗證（這一步不能省）

本機看到的是「綁在哪」，外部看到的才是「連不連得到」。★★★ **只掃你自己機關的 IP，
而且依機關規定事前取得書面同意**，不要對外部位址做這件事。

```bash
# 在另一台主機（例如辦公網段的維運筆電）執行
nmap -Pn -p 3306,33060,33062 db01.example.gov.tw
```

**收好了**的預期輸出：

```text
PORT      STATE    SERVICE
3306/tcp  filtered mysql          # ★ filtered = 封包被防火牆吃掉，正確
33060/tcp filtered mysqlx
33062/tcp filtered unknown
```

**沒收好**的輸出：

```text
PORT      STATE SERVICE VERSION
3306/tcp  open  mysql   MySQL 8.0.39-0ubuntu0.22.04.1   # ★★★★★ 版本都被讀出來了
33060/tcp open  mysqlx
```

再用真的客戶端試一次，這比 `nmap` 更有說服力：

```bash
mysql -h db01.example.gov.tw -u root -p --connect-timeout=5
```

| 你看到的訊息 | 代表什麼 | 星級 |
| --- | --- | --- |
| `ERROR 2003 (HY000): Can't connect to MySQL server on 'db01' (110)` | 逾時，**防火牆擋住了**，這是你要的 | ★ |
| `ERROR 2003 ... (111)` | 連線被拒，**埠沒人聽**（或被 REJECT），也可以接受 | ★ |
| `ERROR 1045 (28000): Access denied for user 'root'@'10.20.1.5'` | ★★★★ **埠是通的**，只是密碼錯 —— 攻擊者可以慢慢猜 | ★★★★ |
| `ERROR 1130 (HY000): Host '10.20.1.5' is not allowed to connect` | ★★★★ **埠是通的**，只是帳號 host 限制擋了 —— 撐住你的是帳號設定，不是網路 | ★★★★ |

> [!danger] ★★★★ 1045 與 1130 都不是「安全」
> 很多人看到 `Access denied` 就安心了。實際上這代表**TCP 三次握手成功、MySQL 願意跟你講話**。
> 攻擊者現在可以：讀版本橫幅去找已知漏洞、對 `root` 做密碼噴灑、觸發你的連線資源。
> **正確答案只有逾時或連線被拒。**

> [!tip] ★★★ 為什麼「有人真的會掃到你」
> 網路空間搜尋引擎（Shodan、Censys、FOFA 這類）持續全網掃描並索引服務橫幅，
> 用 `port:3306 product:MySQL` 就能列出一整批對外的資料庫。
> 你不需要被針對，**只要對外開著就會被編進去**，通常在上線後幾小時內。
>
> 自查方式：在那些網站查**你自己機關的對外 IP 網段**（多數提供免費查詢），
> 這比你自己掃更貼近攻擊者看到的畫面。

### 收斂監聽面

Ubuntu / Debian 的設定檔在 `/etc/mysql/mysql.conf.d/mysqld.cnf`。★★★ **不要直接改它**，
套件升級會提示衝突；用 drop-in：

```bash
sudo tee /etc/mysql/mysql.conf.d/99-hardening.cnf >/dev/null <<'EOF'
[mysqld]
# ── ① 網路層 ────────────────────────────────────────────────
# ★★★★ 同機應用（LXMP 單機）就只綁 loopback
bind-address            = 127.0.0.1
# 跨機時改成「loopback + 內網介面」，MySQL 8.0.13+ 支援逗號分隔多位址
# bind-address          = 127.0.0.1,10.10.20.11

# ★★★★ X Protocol：用不到就整個關掉（比綁位址更乾淨）
mysqlx                  = OFF
# 若真的有 MySQL Shell / X DevAPI 需求，改成綁 loopback 而不是關閉：
# mysqlx_bind_address   = 127.0.0.1
# mysqlx_port           = 33060

# ★★★ 保留一條救生管道：管理介面只聽 loopback（8.0.14+）
admin_address           = 127.0.0.1
admin_port              = 33062

# ★★★ 不做 DNS 反解：避免被偽造的 PTR 記錄騙過 host 比對，順便省掉 DNS 抖動造成的連線變慢
skip_name_resolve       = ON
EOF

sudo systemctl restart mysql
```

驗證：

```bash
sudo ss -lntp | grep mysqld
```

預期輸出：

```text
LISTEN 0 151 127.0.0.1:3306  0.0.0.0:* users:(("mysqld",pid=2214,fd=23))
LISTEN 0 151 127.0.0.1:33062 0.0.0.0:* users:(("mysqld",pid=2214,fd=25))   # ★ 只剩這兩個，33060 消失
```

> [!danger] ★★★★ `skip_name_resolve=ON` 會讓「用主機名寫的帳號」立刻失效
> 如果你有 `'app'@'app01.example.gov.tw'` 這種帳號，開了這個參數之後**它永遠登不進來**，
> 因為 MySQL 不再把來源 IP 反解成名字。
>
> **開之前先查**：
> ```sql
> SELECT user, host FROM mysql.user
> WHERE host NOT REGEXP '^[0-9./]+$' AND host NOT IN ('localhost','%','::1');
> ```
> 有結果就先把那些帳號改成 IP 或網段形式（`10.10.20.%`），再開這個參數。

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> # 設定檔主檔是 /etc/my.cnf，drop-in 目錄是 /etc/my.cnf.d/
> $ sudo vi /etc/my.cnf.d/99-hardening.cnf     # 內容同上
> $ sudo systemctl restart mysqld              # ★★★ 服務名是 mysqld，不是 mysql
>
> # 防火牆是 firewalld
> $ sudo firewall-cmd --permanent --new-zone=dbaccess 2>/dev/null || true
> $ sudo firewall-cmd --permanent --zone=dbaccess --add-source=10.10.20.21/32
> $ sudo firewall-cmd --permanent --zone=dbaccess --add-port=3306/tcp
> $ sudo firewall-cmd --reload
> $ sudo firewall-cmd --list-all-zones | grep -A6 dbaccess
> ```
> ★★★★ RHEL 系還有 **SELinux**：若你把 `datadir` 搬到 `/data/mysql`，
> 必須 `semanage fcontext -a -t mysqld_db_t "/data/mysql(/.*)?" && restorecon -Rv /data/mysql`，
> **不是** `setenforce 0`。詳見 [[07-SELinux與AppArmor]]。
>
> 換非標準埠（例如 3307）也要先 `semanage port -a -t mysqld_port_t -p tcp 3307`，
> 否則 mysqld 起不來，error log 只會寫 `Can't start server: Bind on TCP/IP port: Permission denied`。

> [!info]- MariaDB 差異（RHEL 系預設常是 MariaDB）
> 機關的 RHEL 8/9 主機 `dnf install mysql-server` 裝到的往往是 **MariaDB**，不是 Oracle MySQL。
> 本篇多數觀念相通，但這些**不一樣**：
> - MariaDB **沒有 X Plugin**，不會有 33060，也沒有 `mysqlx*` 變數
> - 沒有 `require_secure_transport`；等效做法是**帳號層** `REQUIRE SSL` 或 `REQUIRE X509`
> - 沒有 `admin_address` / `admin_port` 管理介面
> - ★★★★ **有官方稽核外掛** `server_audit`（`INSTALL SONAME 'server_audit'`），
>   這點比 MySQL 社群版強，稽核方案可以直接用它
> - 表空間加密用 `plugin-load-add=file_key_management`，不是 keyring component
> - 密碼政策用 `simple_password_check` / `cracklib_password_check`，不是 `validate_password` component
>
> 先確認你在跟誰講話：
> ```bash
> $ mysql --version
> mysql  Ver 15.1 Distrib 10.11.8-MariaDB, for Linux (x86_64)   # ★ 這是 MariaDB
> ```

### 防火牆白名單

監聽面收好之後，防火牆是第二道。規則語法見 [[02-防火牆-ufw基礎與實務]]，
這裡只講「資料庫該放行給誰」：

```bash
# ★★★★ 預設拒絕，只放行明確的應用主機
sudo ufw default deny incoming
sudo ufw allow from 10.10.20.21 to any port 3306 proto tcp comment 'app01 -> mysql'
sudo ufw allow from 10.10.20.22 to any port 3306 proto tcp comment 'app02 -> mysql'
# ★★★ 監控主機只需要 exporter 的埠，不要順手放行 3306
sudo ufw status numbered
```

預期輸出：

```text
Status: active
     To                Action      From
     --                ------      ----
[ 1] 3306/tcp          ALLOW IN    10.10.20.21   # app01 -> mysql
[ 2] 3306/tcp          ALLOW IN    10.10.20.22   # app02 -> mysql
[ 3] 22/tcp            ALLOW IN    10.10.9.0/24  # ops jumphost
```

> [!danger] ★★★★★ 絕對不要出現這一列
> ```text
> [ 4] 3306/tcp          ALLOW IN    Anywhere
> ```
> `ufw allow 3306/tcp`（沒有 `from`）就是這個結果。
> 有人為了「讓廠商連進來測」加了這條，然後忘了刪 —— 這是最常見的事故起點。
>
> 廠商要連資料庫，正確做法是 **SSH 隧道**，不是開防火牆。

### 跨機管理走 SSH 隧道

維運人員要用 GUI 工具（DBeaver、MySQL Workbench）連正式庫時，**不要**為此開放 3306：

```bash
# ★★★ 127.0.0.1:3306 是在「遠端主機上」解析的，所以資料庫可以只綁 loopback
ssh -N -L 13306:127.0.0.1:3306 ops@db01.example.gov.tw
```

另開一個終端機：

```bash
mysql -h 127.0.0.1 -P 13306 -u ops -p
```

預期輸出：

```text
Welcome to the MySQL monitor.  Commands end with ; or \g.
Your MySQL connection id is 4821
Server version: 8.0.39-0ubuntu0.22.04.1 (Ubuntu)
```

> [!tip] ★★★ 隧道的兩個常見錯誤
> - 寫成 `-L 13306:db01:3306` —— 這會讓 SSH 主機**再連一次 db01 的對外位址**，
>   等於繞回你剛封起來的那條路。目的位址一定寫 `127.0.0.1`。
> - 用 `-L 0.0.0.0:13306:...` 讓同事共用你的隧道 —— 等於在你的筆電上開了一個
>   **無認證的資料庫代理**。要共用請各自開自己的隧道。
>
> 完整說明見 [[05-SSH-隧道與埠轉發]]。

---

## 進階設定與調校

### 帳號面盤點與收斂

`CREATE USER` / `GRANT` 的語法在 [[02-MySQL-使用者與權限]]，這裡做的是**已上線系統的收尾**：
把兩年來累積的帳號攤開來看。

#### 一次把全部帳號攤平

```sql
SELECT user, host, plugin,
       account_locked                                  AS locked,
       password_expired                                AS expired,
       password_last_changed                           AS last_pw,
       IF(authentication_string='','★★★★★ 空密碼','ok') AS pw_state
FROM mysql.user
ORDER BY (host='%') DESC, host, user;
```

預期輸出（★★★★ 這是一台**沒收過**的機器的典型長相）：

```text
+------------------+-----------+-----------------------+--------+---------+---------------------+---------------+
| user             | host      | plugin                | locked | expired | last_pw             | pw_state      |
+------------------+-----------+-----------------------+--------+---------+---------------------+---------------+
| app_rw           | %         | mysql_native_password | N      | N       | 2024-03-11 10:22:41 | ok            |  ★★★★ 任意來源
| vendor_tmp       | %         | mysql_native_password | N      | N       | 2024-07-02 15:48:03 | ok            |  ★★★★★ 廠商臨時帳號還在
| root             | %         | caching_sha2_password | N      | N       | 2024-03-11 09:55:12 | ok            |  ★★★★★ root 對外
|                  | localhost | mysql_native_password | N      | N       | NULL                | ★★★★★ 空密碼 |  匿名帳號
| debian-sys-maint | localhost | caching_sha2_password | N      | N       | 2024-03-11 09:54:02 | ok            |
| mysql.session    | localhost | caching_sha2_password | Y      | N       | 2024-03-11 09:54:01 | ok            |  ★ 系統保留，locked=Y 正常
| root             | localhost | auth_socket           | N      | N       | NULL                | ok            |  ★ 這個是對的
+------------------+-----------+-----------------------+--------+---------+---------------------+---------------+
```

> [!note] ★ `mysql.session` / `mysql.sys` / `mysql.infoschema` 不要動
> 這三個是 MySQL 內部保留帳號，`account_locked=Y` 是**正常且必須**的狀態。
> 有人「清理帳號」把它們刪掉，結果 `sys` schema 的檢視表全爆、升級時卡住。

#### 該處理的四類帳號

```sql
-- ① ★★★★★ 匿名帳號（user='' 代表任何使用者名都能登入）
SELECT user, host FROM mysql.user WHERE user='';
DROP USER ''@'localhost';
-- 若有 ''@'<主機名'> 也一併刪

-- ② ★★★★★ 空密碼帳號
SELECT user, host FROM mysql.user WHERE authentication_string='';

-- ③ ★★★★ root 只留 localhost
SELECT user, host FROM mysql.user WHERE user='root';
DROP USER 'root'@'%';           -- ★★★★★ 確認 localhost 那個進得去再刪

-- ④ ★★★★ 所有 host='%' 的帳號，逐一問「它真的需要從任何地方連嗎」
SELECT user, host FROM mysql.user WHERE host='%';
```

`host='%'` 的帳號**不要直接刪**，先改成明確網段，再觀察一週有沒有應用報錯：

```sql
-- ★★★ RENAME USER 會保留該帳號所有權限，比「刪掉再建」安全得多
RENAME USER 'app_rw'@'%' TO 'app_rw'@'10.10.20.%';
FLUSH PRIVILEGES;
SHOW GRANTS FOR 'app_rw'@'10.10.20.%';
```

預期輸出：

```text
+---------------------------------------------------------------------------+
| Grants for app_rw@10.10.20.%                                              |
+---------------------------------------------------------------------------+
| GRANT USAGE ON *.* TO `app_rw`@`10.10.20.%`                               |
| GRANT SELECT, INSERT, UPDATE, DELETE ON `appdb`.* TO `app_rw`@`10.10.20.%`|
+---------------------------------------------------------------------------+
```

> [!danger] ★★★★ `RENAME USER` 會讓現有連線繼續活著、新連線立刻改判
> 應用如果用連線池（Laravel + PHP-FPM 常見持久連線、PM2 下的 Node 連線池），
> **舊連線不會斷，所以你當下看不到錯誤**，等到深夜連線重建才爆。
>
> 改完一定要主動驗證，不要等應用回報：
> ```bash
> $ mysql -h 10.10.20.11 -u app_rw -p -e 'SELECT 1' appdb   # 從 app01 執行
> ```

#### test 資料庫與 `mysql_secure_installation`

```sql
SHOW DATABASES LIKE 'test';
SELECT * FROM mysql.db WHERE db LIKE 'test%';   -- ★★★ 這張表裡的萬用授權才是真問題
```

`mysql.db` 若有 `test` / `test\_%` 的列，代表**任何帳號都能在 test 庫建表寫資料**，
攻擊者拿來當落腳點：

```sql
DROP DATABASE IF EXISTS test;
DELETE FROM mysql.db WHERE db IN ('test','test\\_%');
FLUSH PRIVILEGES;
```

新機器可以直接跑：

```bash
sudo mysql_secure_installation
```

> [!warning] ★★★ `mysql_secure_installation` 做得到與做不到
> 它處理：root 密碼、匿名帳號、root 遠端登入、test 資料庫、重載權限。
> 它**完全不碰**：`bind-address`、TLS、稽核、`local_infile`、`secure_file_priv`、防火牆。
> 跑完它不等於加固完成，只等於做完了本節的一小半。

#### ★★★ 高風險權限清單

這些權限給出去，等於把「資料庫的邊界」擴大到整台主機：

| 權限 | 星級 | 拿到之後能做什麼 |
| --- | --- | --- |
| `FILE` | ★★★★★ | `LOAD DATA INFILE '/etc/passwd'` 讀任何 mysqld 讀得到的檔；`SELECT ... INTO OUTFILE` 寫檔（配上網站根目錄就是 webshell） |
| `GRANT OPTION` | ★★★★★ | 把自己的權限發給別人 —— **權限收斂從此失效** |
| `SUPER` / `SYSTEM_VARIABLES_ADMIN` | ★★★★ | 改 `secure_file_priv`、`general_log`、關掉 binlog，等於關掉你的稽核 |
| `PROCESS` | ★★★★ | `SHOW PROCESSLIST` 看得到**別人正在跑的完整 SQL**，包含 `WHERE id_no='A123456789'` 這種查詢裡的身分證字號 |
| `SHUTDOWN` | ★★★ | 一行 `SHUTDOWN;` 服務中斷 |
| `CREATE USER` | ★★★ | 自建後門帳號 |
| `RELOAD` | ★★ | `FLUSH` 系列，含 `FLUSH LOGS` 輪掉你的證據 |
| `CONNECTION_ADMIN` | ★★★ | 繞過 `max_connections` 限制，★★★ **也繞過 `init_connect`**（見稽核那節） |
| `BACKUP_ADMIN` / `REPLICATION SLAVE` | ★★★ | 有辦法把整份資料複製走 |

盤點指令：

```sql
SELECT GRANTEE, PRIVILEGE_TYPE, IS_GRANTABLE
FROM information_schema.USER_PRIVILEGES
WHERE PRIVILEGE_TYPE IN ('FILE','SUPER','PROCESS','SHUTDOWN','RELOAD','CREATE USER',
                         'SYSTEM_VARIABLES_ADMIN','CONNECTION_ADMIN','BACKUP_ADMIN',
                         'REPLICATION SLAVE','AUDIT_ADMIN')
   OR IS_GRANTABLE = 'YES'
ORDER BY GRANTEE, PRIVILEGE_TYPE;
```

預期輸出（**乾淨**的機器只剩系統帳號與一個管理帳號）：

```text
+----------------------------+------------------------+--------------+
| GRANTEE                    | PRIVILEGE_TYPE         | IS_GRANTABLE |
+----------------------------+------------------------+--------------+
| 'root'@'localhost'         | FILE                   | YES          |  ★ 預期內
| 'mysql.session'@'localhost'| SUPER                  | NO           |  ★ 系統保留
| 'app_rw'@'10.10.20.%'      | FILE                   | NO           |  ★★★★★ 這個要拔掉
+----------------------------+------------------------+--------------+
```

拔掉：

```sql
REVOKE FILE ON *.* FROM 'app_rw'@'10.10.20.%';
FLUSH PRIVILEGES;
SHOW GRANTS FOR 'app_rw'@'10.10.20.%';   -- ★ 確認 GRANT USAGE 那行不再帶 FILE
```

#### 密碼政策與帳號鎖定

```sql
-- ★★★ 8.0 用 component，不是舊的 validate_password plugin
INSTALL COMPONENT 'file://component_validate_password';

SET PERSIST validate_password.policy             = 'STRONG';   -- 需含特殊字元與字典檢查
SET PERSIST validate_password.length             = 14;
SET PERSIST validate_password.mixed_case_count   = 1;
SET PERSIST validate_password.number_count       = 1;
SET PERSIST validate_password.special_char_count = 1;
SET PERSIST validate_password.check_user_name    = ON;         -- ★★★ 不准用帳號名當密碼

-- 全域密碼生命週期
SET PERSIST default_password_lifetime = 0;      -- ★★★ 見下方說明，機關情境常設 0
SET PERSIST password_history          = 5;      -- 不得重複最近 5 次
SET PERSIST password_reuse_interval   = 365;    -- 一年內不得重複
SET PERSIST password_require_current  = ON;     -- 改密碼要先驗舊密碼

SHOW VARIABLES LIKE 'validate_password.%';
```

預期輸出（節錄，★★★ `policy` 與 `length` 是稽核最常問的兩項）：

```text
| validate_password.check_user_name    | ON     |
| validate_password.length             | 14     |
| validate_password.policy             | STRONG |
```

> [!danger] ★★★★ `default_password_lifetime` 設成 90 會讓應用在半夜掛掉
> 這個參數對**所有帳號**生效，包含 `app_rw` 這種應用帳號。
> 密碼到期後，應用連進來會收到：
> ```text
> ERROR 1820 (HY000): You must reset your password using ALTER USER before executing this statement.
> ```
> 而且是**全部應用同時**發生。
>
> 正確做法：全域設 `0`（不過期），**只對人用帳號**個別設定：
> ```sql
> ALTER USER 'ops_alice'@'10.10.9.%' PASSWORD EXPIRE INTERVAL 90 DAY;
> ALTER USER 'app_rw'@'10.10.20.%'   PASSWORD EXPIRE NEVER;   -- ★★★ 明確標註
> ```
> 應用帳號的輪換靠**排程與變更管理**去做，不要靠資料庫踢人。

帳號鎖定（MySQL 8.0.19+）與連線失敗延遲：

```sql
-- 人用帳號：連續 5 次失敗鎖 1 天
ALTER USER 'ops_alice'@'10.10.9.%' FAILED_LOGIN_ATTEMPTS 5 PASSWORD_LOCK_TIME 1;

-- ★★★★ 應用帳號千萬不要設鎖定：一次設定檔打錯就把正式服務鎖死
ALTER USER 'app_rw'@'10.10.20.%' FAILED_LOGIN_ATTEMPTS 0;
```

```sql
-- 全域的暴力破解減速（對所有帳號生效，不會鎖死）
INSTALL PLUGIN CONNECTION_CONTROL SONAME 'connection_control.so';
INSTALL PLUGIN CONNECTION_CONTROL_FAILED_LOGIN_ATTEMPTS SONAME 'connection_control.so';

SET PERSIST connection_control_failed_connections_threshold = 3;
SET PERSIST connection_control_min_connection_delay         = 1000;    -- 1 秒起跳
SET PERSIST connection_control_max_connection_delay         = 60000;   -- 最多 60 秒

SELECT * FROM information_schema.CONNECTION_CONTROL_FAILED_LOGIN_ATTEMPTS;
```

預期輸出（有人在猜密碼時）：

```text
+---------------------------+-----------------+
| USERHOST                  | FAILED_ATTEMPTS |
+---------------------------+-----------------+
| 'root'@'10.20.1.5'        |              47 |   ★★★★ 這一列就是告警來源
+---------------------------+-----------------+
```

> [!tip] ★★★ 為什麼延遲比鎖定好
> 鎖定（`FAILED_LOGIN_ATTEMPTS`）可以被拿來做**阻斷服務**：攻擊者只要拿你的應用帳號名
> 亂猜 5 次，就把正式服務鎖了。
> `CONNECTION_CONTROL` 的遞增延遲不會鎖死任何人，但把猜密碼的速度從每秒數百次壓到每分鐘一次。
> **人用帳號兩個都上，應用帳號只上延遲。**

#### 離職與異動的定期清查

離職與異動清查最關鍵的問題是「**這個帳號還有人在用嗎**」。★★★★ MySQL 沒有 `last_login` 欄位，
要靠 Performance Schema 的連線統計（自上次重啟以來）：

```sql
SELECT USER, HOST, CURRENT_CONNECTIONS, TOTAL_CONNECTIONS
FROM performance_schema.accounts
WHERE USER IS NOT NULL
ORDER BY TOTAL_CONNECTIONS ASC;
```

預期輸出：

```text
+------------+-------------+---------------------+-------------------+
| USER       | HOST        | CURRENT_CONNECTIONS | TOTAL_CONNECTIONS |
+------------+-------------+---------------------+-------------------+
| vendor_tmp | 10.20.1.%   |                   0 |                 0 |  ★★★★ 開機到現在沒用過 → 刪
| ops_bob    | 10.10.9.%   |                   0 |                 0 |  ★★★★ 人已離職 → 刪
| app_rw     | 10.10.20.%  |                  12 |             48213 |  ★ 活躍
+------------+-------------+---------------------+-------------------+
```

> [!warning] ★★★ 這張表在服務重啟後歸零
> `performance_schema.accounts` 統計的是**自 mysqld 啟動以來**。
> 剛重啟過就拿它判斷「沒人用」會誤刪。
> 做法：先 `ALTER USER ... ACCOUNT LOCK` 觀察兩週，沒人抱怨再 `DROP USER`。
> 鎖定比刪除好回復，而且被鎖的帳號嘗試登入時 error log 會留下紀錄。

```sql
ALTER USER 'ops_bob'@'10.10.9.%' ACCOUNT LOCK;   -- 第 1 步：鎖，觀察兩週
-- 兩週後
DROP USER 'ops_bob'@'10.10.9.%';                 -- 第 2 步：刪
```

### ★★★★ 傳輸加密：從「有加密」到「真的安全」

#### 先看看你現在用的是什麼憑證

MySQL 8 第一次啟動時，若沒有指定憑證，會**自動產生一組自簽憑證**放進 `datadir`
（`auto_generate_certs` 預設 ON）。所以幾乎每一台 MySQL 8 都「有 TLS」：

```bash
sudo ls -l /var/lib/mysql/*.pem
```

預期輸出：

```text
-rw-r--r-- 1 mysql mysql 1112 Mar 11  2024 ca.pem
-rw------- 1 mysql mysql 1676 Mar 11  2024 ca-key.pem
-rw-r--r-- 1 mysql mysql 1112 Mar 11  2024 client-cert.pem
-rw------- 1 mysql mysql 1676 Mar 11  2024 client-key.pem
-rw-r--r-- 1 mysql mysql 1112 Mar 11  2024 server-cert.pem
-rw------- 1 mysql mysql 1676 Mar 11  2024 server-key.pem
```

```bash
sudo openssl x509 -in /var/lib/mysql/server-cert.pem -noout -subject -issuer -dates -ext subjectAltName
```

預期輸出：

```text
subject=CN = MySQL_Server_8.0.39_Auto_Generated_Server_Certificate
issuer=CN = MySQL_Server_8.0.39_Auto_Generated_CA_Certificate
notBefore=Mar 11 09:54:03 2024 GMT
notAfter=Mar  9 09:54:03 2034 GMT
# ★★★★ 沒有 subjectAltName、CN 不是主機名、簽發者是本機自己產的 CA
```

> [!danger] ★★★★ 「有加密」不等於「安全」——自動自簽憑證的三個問題
> 1. **CN 不是主機名，也沒有 SAN**：客戶端根本無法用 `VERIFY_IDENTITY` 驗證「我連的是不是 db01」。
> 2. **簽發者是每台機器自己產的 CA**：客戶端沒有可信任的共同根，只能選擇「不驗證」。
> 3. 因此實務上大家都用預設的 `--ssl-mode=PREFERRED` —— **封包是加密的，但對方是誰不知道**。
>
> 攻擊者在同網段做 ARP 欺騙、架一台假的 MySQL，客戶端會**一樣顯示加密連線成功**，
> 然後把帳號密碼與查詢送給攻擊者。這就是典型的中間人攻擊。
>
> **加密解決竊聽，驗證解決冒充。只做前者等於只做一半。**

#### 用機關自建 CA 簽發資料庫憑證

CA 的建置與 `openssl ca` 的操作在 [[08-用自建CA簽發伺服器憑證]]，這裡只列資料庫這一張憑證的
**特殊要求**：

```bash
# 在 CA 主機上：產生資料庫伺服器的金鑰與 CSR
sudo openssl req -newkey rsa:2048 -nodes \
  -keyout db01.key -out db01.csr \
  -subj "/C=TW/O=Example Agency/OU=IT/CN=db01.example.gov.tw"

# ★★★★ SAN 一定要同時包含「主機名」與「應用連線字串裡實際用的位址」
sudo tee db01-san.cnf >/dev/null <<'EOF'
subjectAltName = DNS:db01.example.gov.tw, DNS:db01, IP:10.10.20.11, IP:127.0.0.1
extendedKeyUsage = serverAuth
keyUsage = digitalSignature, keyEncipherment
EOF

sudo openssl x509 -req -in db01.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out db01.crt -days 825 -sha256 -extfile db01-san.cnf
```

> [!warning] ★★★★★ SAN 沒寫 IP，`VERIFY_IDENTITY` 就一定失敗
> Laravel 的 `.env` 常寫 `DB_HOST=10.10.20.11`（IP），而憑證只有 `DNS:db01.example.gov.tw`。
> 客戶端拿 IP 去比對 SAN，比不到 → 連線被拒：
> ```text
> ERROR 2026 (HY000): SSL connection error: Failed to verify the server certificate
> ```
> **憑證裡的 SAN 必須涵蓋應用設定檔裡實際寫的每一個位址。**
> 寫了 `IP:127.0.0.1` 是為了同機的 PHP-FPM 走 TCP loopback 時也能驗證。
>
> 有效期建議 **825 天以內**（多數客戶端與掃描工具的上限）。
> 憑證輪換與到期監控見 [[12-憑證生命週期管理]]。

部署到資料庫主機：

```bash
sudo install -d -o mysql -g mysql -m 750 /etc/mysql/ssl
sudo install -o mysql -g mysql -m 644 ca.crt  /etc/mysql/ssl/ca.pem
sudo install -o mysql -g mysql -m 644 db01.crt /etc/mysql/ssl/server-cert.pem
sudo install -o mysql -g mysql -m 600 db01.key /etc/mysql/ssl/server-key.pem   # ★★★★ 私鑰 600
sudo ls -l /etc/mysql/ssl/
```

預期輸出：

```text
-rw-r--r-- 1 mysql mysql 1509 Aug 29 09:41 ca.pem
-rw-r--r-- 1 mysql mysql 1424 Aug 29 09:41 server-cert.pem
-rw------- 1 mysql mysql 1704 Aug 29 09:41 server-key.pem       # ★ 只有 mysql 讀得到
```

> [!danger] ★★★★ AppArmor 會擋掉 `/etc/mysql/ssl/`
> Ubuntu 的 `usr.sbin.mysqld` profile 沒有涵蓋自訂路徑時，mysqld 起不來，
> `journalctl -u mysql` 會看到 `Permission denied`，但 `ls -l` 看起來權限完全正確。
>
> 加規則而不是關掉 AppArmor：
> ```bash
> $ sudo tee /etc/apparmor.d/local/usr.sbin.mysqld >/dev/null <<'EOF'
> /etc/mysql/ssl/ r,
> /etc/mysql/ssl/** r,
> EOF
> $ sudo apparmor_parser -r /etc/apparmor.d/usr.sbin.mysqld
> $ sudo aa-status | grep mysqld
> ```
> 預期輸出：`/usr/sbin/mysqld` 出現在 **enforce mode** 清單裡。
> 詳見 [[07-SELinux與AppArmor]]。

寫進設定：

```ini
# /etc/mysql/mysql.conf.d/99-hardening.cnf 續
[mysqld]
# ── ④ 傳輸層 ────────────────────────────────────────────────
ssl_ca                  = /etc/mysql/ssl/ca.pem
ssl_cert                = /etc/mysql/ssl/server-cert.pem
ssl_key                 = /etc/mysql/ssl/server-key.pem

# ★★★ 8.0.28 起 TLSv1 / TLSv1.1 已移除，明寫只留 1.2 / 1.3
tls_version             = TLSv1.2,TLSv1.3

# ★★★★★ 這一行先「不要開」，見下方分階段切換
# require_secure_transport = ON
```

★★★ 換憑證**不需要重啟服務**（MySQL 8.0.16+），現有連線也不會斷：

```sql
ALTER INSTANCE RELOAD TLS;
```

預期輸出：

```text
Query OK, 0 rows affected (0.01 sec)
```

驗證新憑證真的載入了：

```bash
openssl s_client -connect 127.0.0.1:3306 -starttls mysql </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -issuer -ext subjectAltName
```

預期輸出：

```text
subject=C = TW, O = Example Agency, OU = IT, CN = db01.example.gov.tw
issuer=C = TW, O = Example Agency, OU = IT, CN = Example Agency Internal CA
X509v3 Subject Alternative Name:
    DNS:db01.example.gov.tw, DNS:db01, IP Address:10.10.20.11, IP Address:127.0.0.1
```

> [!tip] ★★★ `openssl s_client -starttls mysql` 是查 MySQL TLS 的神器
> MySQL 的握手不是一開始就 TLS（先送明文的伺服器問候，再升級），
> 所以**不加 `-starttls mysql` 會直接失敗**，很多人因此以為 MySQL 沒開 TLS。

#### 分階段切成強制加密（不中斷服務的順序）

★★★★★ **直接開 `require_secure_transport=ON` 是最容易造成全站中斷的一步。**
正確順序是「先看清楚誰還沒加密，再強制」：

**階段 0：看現在有多少連線是明文的**

```sql
SELECT t.PROCESSLIST_USER AS user, t.PROCESSLIST_HOST AS host,
       MAX(IF(s.VARIABLE_NAME='Ssl_version', s.VARIABLE_VALUE, NULL)) AS tls_ver,
       MAX(IF(s.VARIABLE_NAME='Ssl_cipher',  s.VARIABLE_VALUE, NULL)) AS cipher,
       COUNT(DISTINCT t.PROCESSLIST_ID) AS conns
FROM performance_schema.threads t
JOIN performance_schema.status_by_thread s ON s.THREAD_ID = t.THREAD_ID
WHERE t.PROCESSLIST_ID IS NOT NULL
GROUP BY t.PROCESSLIST_USER, t.PROCESSLIST_HOST
ORDER BY tls_ver, user;
```

預期輸出：

```text
+---------+-------------+---------+------------------------+-------+
| user    | host        | tls_ver | cipher                 | conns |
+---------+-------------+---------+------------------------+-------+
| app_rw  | 10.10.20.21 |         |                        |    12 |  ★★★★★ 空白 = 明文
| report  | 10.10.20.33 |         |                        |     2 |  ★★★★★ 明文
| ops_ali | 10.10.9.14  | TLSv1.3 | TLS_AES_256_GCM_SHA384 |     1 |  ★ 已加密
+---------+-------------+---------+------------------------+-------+
```

★★★★ **這張表是整個切換作業的核心。** 空白的那幾列就是「開了強制加密會立刻死掉」的應用。
在它們全部變成 TLSv1.2/1.3 之前，不要進入階段 3。

**階段 1：把 CA 憑證發給每一個客戶端，改連線參數**

```bash
# 應用主機上
sudo install -d -m 755 /etc/ssl/agency
sudo install -m 644 ca.crt /etc/ssl/agency/ca.pem
```

Laravel / PDO（`config/database.php`）：

```php
'mysql' => [
    'driver'   => 'mysql',
    'host'     => env('DB_HOST', '10.10.20.11'),
    // …
    'options'  => extension_loaded('pdo_mysql') ? array_filter([
        // ★★★★ 帶 CA 才驗證得了伺服器身分
        PDO::MYSQL_ATTR_SSL_CA => env('MYSQL_ATTR_SSL_CA', '/etc/ssl/agency/ca.pem'),
        // ★★★★ 這一個沒設成 true，帶了 CA 也可能不驗證主機名
        PDO::MYSQL_ATTR_SSL_VERIFY_SERVER_CERT => true,
        // ★★★★ 關掉多語句：注入成功也很難串第二段 SQL
        PDO::MYSQL_ATTR_MULTI_STATEMENTS => false,
        // ★★★★ 用真正的 prepared statement，不要 client 端模擬
        PDO::ATTR_EMULATE_PREPARES => false,
    ]) : [],
],
```

```bash
# .env
MYSQL_ATTR_SSL_CA=/etc/ssl/agency/ca.pem
```

> [!warning] ★★★ `array_filter` 會把 `false` 濾掉
> `PDO::MYSQL_ATTR_SSL_VERIFY_SERVER_CERT => false` 寫在 `array_filter` 裡會被**整個移除**，
> 變成走驅動預設值。要關驗證（不建議）請把它移出 `array_filter`。
>
> 另外，`PDO::MYSQL_ATTR_SSL_VERIFY_SERVER_CERT` 在不同 PHP 版本與 mysqlnd／libmysqlclient
> 建置下的預設值不一致。★★★ **不要相信預設，一律明寫，然後用下一段的方式實測。**
> PHP 端的其他安全參數見 [[06-PHP-安全設定]]。

Laravel 端實測（不要只看設定檔）：

```bash
php artisan tinker --execute="dump(DB::select('SHOW STATUS LIKE \"Ssl_cipher\"'));"
```

預期輸出：

```text
array:1 [
  0 => {#123
    +"Variable_name": "Ssl_cipher"
    +"Value": "TLS_AES_256_GCM_SHA384"      # ★ 空字串就代表還是明文
  }
]
```

命令列客戶端：

```bash
mysql --ssl-mode=VERIFY_IDENTITY --ssl-ca=/etc/ssl/agency/ca.pem \
      -h db01.example.gov.tw -u app_rw -p appdb -e "\s" | grep -i ssl
```

預期輸出：

```text
SSL:			Cipher in use is TLS_AES_256_GCM_SHA384
```

| `--ssl-mode` | 加密 | 驗證 CA | 驗證主機名 | 評語 |
| --- | --- | --- | --- | --- |
| `DISABLED` | ✗ | ✗ | ✗ | ★★★★★ 明文，禁用 |
| `PREFERRED`（**預設**） | 通常有 | ✗ | ✗ | ★★★★ **假的安全感**，可被中間人 |
| `REQUIRED` | ✓ | ✗ | ✗ | ★★★ 擋竊聽，擋不了冒充 |
| `VERIFY_CA` | ✓ | ✓ | ✗ | ★★ 可接受（來源位址固定時） |
| `VERIFY_IDENTITY` | ✓ | ✓ | ✓ | ★ **目標狀態** |

**階段 2：帳號層先要求加密（可逐帳號、可隨時退回）**

```sql
ALTER USER 'app_rw'@'10.10.20.%' REQUIRE SSL;     -- 只要 TLS
-- 更嚴：要求客戶端也出示由同一 CA 簽的憑證（雙向 TLS）
-- ALTER USER 'repl'@'10.10.20.%' REQUIRE X509;
FLUSH PRIVILEGES;
SHOW CREATE USER 'app_rw'@'10.10.20.%'\G
```

預期輸出：

```text
CREATE USER `app_rw`@`10.10.20.%` IDENTIFIED WITH 'caching_sha2_password'
  REQUIRE SSL PASSWORD EXPIRE NEVER ...
```

★★★★ 這一步的好處是**影響範圍可控**：一次改一個帳號，出事只影響那個應用，
而且回退只要 `ALTER USER ... REQUIRE NONE;`。

**階段 3：階段 0 的查詢已經沒有空白列了，才開全域強制**

```sql
SET GLOBAL require_secure_transport = ON;      -- ★★★ 先用 GLOBAL，不要 PERSIST
SELECT @@GLOBAL.require_secure_transport;
```

預期輸出：

```text
+-----------------------------------+
| @@GLOBAL.require_secure_transport |
+-----------------------------------+
|                                 1 |
+-----------------------------------+
```

觀察 30 分鐘～一個上班日，確認 error log 沒有大量：

```text
[Note] [MY-010914] [Server] Aborted connection 8812 to db: 'appdb' user: 'app_rw'
       host: '10.10.20.21' (Connections using insecure transport are prohibited
       while --require_secure_transport=ON.)
```

沒問題再落地：

```sql
SET PERSIST require_secure_transport = ON;     -- ★ 這才會寫進 mysqld-auto.cnf，重啟後留著
```

> [!danger] ★★★★★ 為什麼「先 GLOBAL、後 PERSIST」很重要
> `SET GLOBAL` 只改記憶體 —— 一旦出事，**重啟服務就恢復原狀**，這是你最後的保險。
> `SET PERSIST` 會寫入 `/var/lib/mysql/mysqld-auto.cnf`，重啟也還在。
> 先驗證再落地，中間這段觀察期就是你的安全網。
>
> 要移除 persist 的值：
> ```sql
> RESET PERSIST require_secure_transport;
> ```

> [!info]- Unix socket 不受 TLS 設定影響 —— 這是你的救生艇
> `require_secure_transport=ON` **只管 TCP 連線**。從資料庫主機本機走 Unix socket 進去
> （`sudo mysql`，走 `auth_socket`）**永遠不需要 TLS、永遠連得進去**。
>
> ★★★★★ 記住這件事：不管 TLS 設定怎麼壞掉，只要你能 SSH 到資料庫主機，
> 一行 `sudo mysql -e "SET GLOBAL require_secure_transport=OFF;"` 就能救回全部應用。
> 這是本篇實戰範例回滾段落的核心。

### 靜態資料保護：三層各擋什麼

| 威脅 | 表空間加密 | 備份檔加密 | LUKS 全碟加密 |
| --- | --- | --- | --- |
| 硬碟送修 / 退役未消磁 | ✅ | — | ✅ |
| 整台伺服器被搬走（**關機狀態**） | ✅ | — | ✅ |
| 伺服器**開機中**被入侵取得 root | ❌ | ❌ | ❌ |
| 備份檔被複製到 NAS 外流 | ❌ ★★★★ | ✅ | ❌ |
| 有合法帳號的人撈資料 | ❌ | ❌ | ❌ |

#### InnoDB 表空間加密（keyring component）

★★★ MySQL 8.0.24 起改用 **component**；舊的 `keyring_file` plugin 在 8.0.34 已棄用、8.4 移除。
component 必須用 **manifest 檔**載入，不能用 `INSTALL COMPONENT`：

```bash
sudo install -d -o mysql -g mysql -m 750 /var/lib/mysql-keyring

# ① manifest：與 mysqld 執行檔同目錄，檔名固定為 mysqld.my
sudo tee /usr/sbin/mysqld.my >/dev/null <<'EOF'
{ "components": "file://component_keyring_file" }
EOF

# ② component 設定：放在 plugin_dir，檔名固定
sudo tee /usr/lib/mysql/plugin/component_keyring_file.cnf >/dev/null <<'EOF'
{ "path": "/var/lib/mysql-keyring/component_keyring_file", "read_only": false }
EOF

sudo systemctl restart mysql
mysql -e "SELECT * FROM performance_schema.keyring_component_status;"
```

預期輸出：

```text
+---------------------+---------------------------------------------------+
| STATUS_KEY          | STATUS_VALUE                                      |
+---------------------+---------------------------------------------------+
| Component_name      | component_keyring_file                            |
| Author              | Oracle Corporation                                |
| Data_file           | /var/lib/mysql-keyring/component_keyring_file     |
| Status              | Active                                            |   # ★ 要看到 Active
+---------------------+---------------------------------------------------+
```

啟用與驗證：

```sql
SET PERSIST default_table_encryption = ON;      -- 之後新建的表預設加密
ALTER TABLE appdb.members ENCRYPTION = 'Y';     -- ★★★ 會重建整張表，大表要抓維護窗口
SELECT NAME, ENCRYPTION FROM information_schema.INNODB_TABLESPACES WHERE NAME LIKE 'appdb/%';
```

預期輸出：

```text
+------------------+------------+
| NAME             | ENCRYPTION |
+------------------+------------+
| appdb/members    | Y          |
| appdb/logs       | N          |     ★★★ 舊表不會自動轉，要逐一 ALTER
+------------------+------------+
```

> [!danger] ★★★★★ 金鑰檔遺失 = 資料永久回不來
> `/var/lib/mysql-keyring/component_keyring_file` 只是一個**普通檔案**。
> 它不見了，加密表空間就**永遠**打不開 —— 沒有救援程序、沒有原廠後門、備份也救不了
> （備份的是密文）。
>
> 三條硬規則：
> 1. ★★★★★ 金鑰檔要**獨立於資料庫備份**另外備份，而且**不能跟資料備份放在同一個地方**
>    （放一起的話，備份媒體被偷就兩個都拿到，加密等於白做）。
> 2. ★★★★ 金鑰要有**書面保管程序**：誰持有、放哪、多久檢查一次可還原。
> 3. ★★★★ 每季做一次「拿金鑰副本 + 資料備份，在乾淨主機還原成功」的演練 ——
>    見 [[05-MySQL-備份與還原]] 與 [[03-機密管理與金鑰保護]]。
>
> 定期輪換主金鑰（重加密所有表空間金鑰，很快）：
> ```sql
> ALTER INSTANCE ROTATE INNODB MASTER KEY;
> ```
> ★★★★ 輪換後**立刻重新備份金鑰檔**，否則舊副本救不回新資料。

### ★★★★ 稽核日誌：社群版的現實與可行方案

MySQL 社群版**沒有官方 audit plugin**（MySQL Enterprise Audit 是企業版功能）。
不要在稽核回覆表上寫「已啟用資料庫稽核」然後其實什麼都沒開。可行的替代方案：

| 方案 | 記得到 | 記不到 | 代價 / 星級 |
| --- | --- | --- | --- |
| **Percona Audit Log Plugin** | 連線、所有 SQL 陳述、帳號、來源 IP，JSON/XML/CSV | — | ★★★ 需與 server 版本相符的 `.so`；混搭 Oracle MySQL 屬非官方組合，**升級前必測** |
| **MariaDB `server_audit`** | 同上 | — | ★★★ 只推薦在 **MariaDB** 上用；MySQL 8 相容性不保證 |
| **`general_log`** | 全部 SQL | — | ★★★★★ **只能短期開**，見下方警告 |
| **`init_connect`** | 每次連線的帳號、來源、時間 | ★★★ 執行了什麼 SQL；**有 `CONNECTION_ADMIN` 的帳號會跳過** | ★★ 幾乎零成本 |
| **binlog（`ROW` 格式）** | 所有 **DML 變更**的前後值 | ★★★★ **SELECT 完全不記** —— 個資「被查詢」的軌跡拿不到 | ★★ 本來就該開 |
| **error log + 連線紀錄送 SIEM** | 登入失敗、被拒連線、啟停、TLS 錯誤 | 查詢內容 | ★ **最務實的起點** |

#### 最務實的組合：連線紀錄表 + error log 送集中日誌

```sql
CREATE DATABASE IF NOT EXISTS auditdb;
CREATE TABLE auditdb.conn_log (
  id        BIGINT AUTO_INCREMENT PRIMARY KEY,
  ts        DATETIME     NOT NULL,
  usr       VARCHAR(288) NOT NULL,   -- USER() 含來源，最長 32+255+1
  cur_usr   VARCHAR(288) NOT NULL,   -- CURRENT_USER() 是實際比對到的帳號
  conn_id   BIGINT       NOT NULL,
  KEY idx_ts (ts), KEY idx_usr (usr(64))
) ENGINE=InnoDB;

-- ★★★ 這張表要讓所有人寫得進去，否則連線會被 init_connect 打斷
GRANT INSERT ON auditdb.conn_log TO 'app_rw'@'10.10.20.%';

SET PERSIST init_connect =
  'INSERT INTO auditdb.conn_log(ts,usr,cur_usr,conn_id)
   VALUES(NOW(),USER(),CURRENT_USER(),CONNECTION_ID());';
```

驗證：

```sql
SELECT ts, usr, cur_usr FROM auditdb.conn_log ORDER BY id DESC LIMIT 3;
```

預期輸出：

```text
+---------------------+---------------------------+------------------------+
| ts                  | usr                       | cur_usr                |
+---------------------+---------------------------+------------------------+
| 2026-08-29 10:14:52 | app_rw@10.10.20.21        | app_rw@10.10.20.%      |
| 2026-08-29 10:14:31 | ops_alice@10.10.9.14      | ops_alice@10.10.9.%    |
+---------------------+---------------------------+------------------------+
```

> [!danger] ★★★★ `init_connect` 的三個陷阱
> 1. **有 `CONNECTION_ADMIN`（或舊的 `SUPER`）的帳號完全跳過 `init_connect`** ——
>    所以管理員的連線**不會被記錄**。這正好是稽核最想看的那些人，要另外用 error log 補。
> 2. 語句失敗會讓**連線直接被拒**。改 `init_connect` 前先在測試機驗；改壞了用 `sudo mysql`
>    （socket + root 有 `CONNECTION_ADMIN`，會跳過）進去 `SET GLOBAL init_connect='';` 救回。
> 3. ★★★ `conn_log` 會無限成長，要排程清理：
>    ```sql
>    DELETE FROM auditdb.conn_log WHERE ts < NOW() - INTERVAL 180 DAY;
>    ```
>    保存期限依機關規定（資安法相關的日誌常要求至少 6 個月）。

```ini
# error log 落成獨立檔並提高詳細度，方便送 Wazuh
[mysqld]
log_error            = /var/log/mysql/error.log
log_error_verbosity  = 3        # ★★★ 3 才會記 Note 級的 Aborted connection / Access denied
log_error_services   = log_filter_internal; log_sink_internal
log_timestamps       = SYSTEM   # ★★ 預設 UTC，跟系統其他日誌對不起來
```

要送 Wazuh 監看的四類事件（規則寫法見 [[05-Wazuh-日誌蒐集與解析]]，
日誌管線見 [[09-日誌集中與SIEM]]）：

| 事件 | 樣態 | 星級 |
| --- | --- | --- |
| 重複登入失敗 | `Access denied for user` 同來源 5 分鐘 > 10 次 | ★★★★ |
| 明文連線嘗試 | `Connections using insecure transport are prohibited` | ★★★★ |
| 新帳號建立 / 權限異動 | binlog 出現 `CREATE USER` / `GRANT` | ★★★★★ |
| 非上班時間的大量查詢 | `conn_log` 在 02:00 出現人用帳號 | ★★★ |

> [!warning] ★★★★★ `general_log` 是最後手段，不是稽核方案
> ```sql
> SET GLOBAL general_log = ON;    -- ★★★ 只在排查特定問題時開，開完立刻關
> ```
> 三個原因：
> 1. **爆量**：中等流量的系統一天可以寫掉數十 GB，磁碟滿了資料庫直接停。
> 2. ★★★★★ **它會把個資寫成明文**：`SELECT * FROM members WHERE id_no='A123456789'`
>    原封不動寫進去。MySQL 會改寫含密碼的陳述，但**不會**改寫 `WHERE` 裡的身分證字號。
>    這個日誌檔本身就變成一份需要納管的個資檔案。
> 3. **效能**：每一個查詢都同步寫檔。
>
> 真的要開：限時、限檔案權限 `600`、事後 `shred -u` 刪除，並在變更紀錄留下開關時間。

### OS 與檔案系統層

```bash
sudo stat -c '%a %U:%G %n' /var/lib/mysql /etc/mysql/my.cnf \
     /etc/mysql/mysql.conf.d/mysqld.cnf /etc/mysql/ssl/server-key.pem \
     /root/.my.cnf /var/log/mysql 2>/dev/null
```

預期輸出（**期望值**）：

```text
750 mysql:mysql /var/lib/mysql                        # ★★★ 其他使用者不得進入
644 root:root   /etc/mysql/my.cnf
644 root:root   /etc/mysql/mysql.conf.d/mysqld.cnf
600 mysql:mysql /etc/mysql/ssl/server-key.pem         # ★★★★ 私鑰
600 root:root   /root/.my.cnf                         # ★★★★ 含密碼的檔一律 600
750 mysql:adm   /var/log/mysql
```

找出所有含密碼又權限過鬆的檔：

```bash
sudo find /etc /root /home -maxdepth 3 -name '.my.cnf' -o -name 'my.cnf' -o -name '.mylogin.cnf' \
  2>/dev/null | while read -r f; do
    p=$(stat -c '%a' "$f")
    [[ "$p" != "600" ]] && echo "★★★★ $f 權限 $p，應為 600"
  done
```

```ini
# /etc/mysql/mysql.conf.d/99-hardening.cnf 續
[mysqld]
# ── ⑦ OS 層 ────────────────────────────────────────────────
local_infile      = OFF                      # ★★★★ 見下方
secure_file_priv  = /var/lib/mysql-files     # ★★★ 或設 NULL 完全禁止匯入匯出
```

> [!danger] ★★★★ `local_infile` 的風險方向跟你想的相反
> `LOAD DATA LOCAL INFILE` 的檔案是**由客戶端讀取後送給伺服器**。
> 協定允許**伺服器主動要求客戶端送任意檔案** —— 所以一台被入侵或惡意的 MySQL 伺服器，
> 可以在你用 `mysql` 或 PHP 連上去時，讀走**你這台客戶端主機**上的
> `/etc/passwd`、`~/.ssh/id_rsa`、`.env`。
>
> MySQL 8 伺服器端預設已是 `OFF`，但**客戶端**也要關：
> - `mysql` CLI：預設關閉，不要加 `--local-infile=1`
> - PHP：`mysqli.allow_local_infile = Off`（php.ini）、PDO 不要設 `PDO::MYSQL_ATTR_LOCAL_INFILE`
>
> 驗證：
> ```bash
> $ mysql -Nse "SELECT @@GLOBAL.local_infile;"
> 0
> ```

`secure_file_priv` 的三種值：`NULL`（完全禁止，最嚴）／某個目錄（限制在該目錄）／
**空字串（★★★★★ 無限制，配上 `FILE` 權限就是任意檔案讀寫）**。

```bash
mysql -Nse "SELECT IFNULL(@@GLOBAL.secure_file_priv,'NULL');"
```

預期輸出：`/var/lib/mysql-files/` 或 `NULL`。得到**空白**就是最危險的狀態。

> [!info]- `symbolic-links` 這個選項不用再寫了
> 很多舊教學（含 CentOS 7 時代的 `my.cnf`）叫你加 `symbolic-links=0`。
> MySQL **8.0.2 起這個選項已棄用，而且預設就是關閉**，繼續寫只會在 error log 得到：
> ```text
> [Warning] [MY-011070] [Server] 'Disabling symbolic links using --skip-symbolic-links
> (or equivalent) is the default. Consider not using this option as it' is deprecated.
> ```
> ★★ 直接從設定檔移除。

### 應用層與資料庫的分工

SQL injection 是**應用的問題**，但 DBA 可以讓「注入成功」的傷害降到最低：

| DBA 能做的 | 效果 | 星級 |
| --- | --- | --- |
| 一庫一帳號，`GRANT ... ON appdb.*` 而非 `*.*` | 注入成功也只碰得到那一個庫，碰不到 `mysql.user` | ★★★★★ |
| 不給 `FILE` | 拿不到 `LOAD_FILE('/etc/passwd')`，也寫不出 webshell | ★★★★★ |
| 不給 DDL（`DROP` / `ALTER` / `CREATE`） | 擋掉 `DROP TABLE` 型的破壞 | ★★★★ |
| 應用端關閉多語句 | 注入點很難串出第二段 `; DROP ...` | ★★★★ |
| 唯讀報表另開帳號只給 `SELECT` | 報表系統被打穿也改不了資料 | ★★★ |
| 前端擋 WAF | 常見注入樣態在進到 PHP 之前就被擋 | ★★★ |

異常查詢樣態的監看（不需要額外工具）：

```sql
-- ★★★ 出現「新的、掃全表的、回傳列數異常大的」查詢指紋
SELECT DIGEST_TEXT, COUNT_STAR, SUM_ROWS_SENT, SUM_NO_INDEX_USED, LAST_SEEN
FROM performance_schema.events_statements_summary_by_digest
WHERE SUM_ROWS_SENT > 100000 OR SUM_NO_INDEX_USED > 0
ORDER BY SUM_ROWS_SENT DESC LIMIT 10;
```

一次撈走十萬列的 `SELECT * FROM members` 出現在這張表上，通常就是拖庫的樣子。
WAF 的部分見 [[04-Web應用防火牆WAF]]，應用端的注入防護見 [[02-應用層安全]]
與 [[04-Laravel-Eloquent與資料庫]]。

---

## 完整實戰範例

**情境**：`db01.example.gov.tw`，Ubuntu 22.04 + MySQL 8.0.39，跑一套 Laravel + Nuxt 的
民眾服務系統（LXMP，見 [[02-範例-Laravel完整堆疊]]），**已上線兩年**，
兩週後接受機關資安稽核。`members` 表有 12 萬筆含身分證字號的個資。

**整改前基線**（跑完檢查腳本得到）：`bind-address=0.0.0.0`、三個 `host='%'` 帳號、
未強制加密、無任何稽核紀錄、`local_infile=ON`。

### 步驟 0：加固檢查腳本

```bash
sudo tee /usr/local/bin/mysql-hardening-check.sh >/dev/null <<'SCRIPT'
#!/usr/bin/env bash
# mysql-hardening-check.sh — MySQL 安全組態健檢，輸出可直接貼進稽核回覆的表格
# 用法： sudo mysql-hardening-check.sh [--markdown] [--out <檔案>]
# 離開碼： 0=全通過  1=有中風險  2=有高風險  3=執行錯誤
set -euo pipefail
IFS=$'\n\t'

MODE="text"; OUT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --markdown) MODE="markdown"; shift ;;
    --out)      OUT="${2:-}"; [[ -n "$OUT" ]] || { echo "--out 需要檔名" >&2; exit 3; }; shift 2 ;;
    *)          echo "未知參數：$1" >&2; exit 3 ;;
  esac
done

command -v mysql >/dev/null || { echo "找不到 mysql 客戶端" >&2; exit 3; }
MY=(mysql --protocol=SOCKET --batch --skip-column-names --connect-timeout=5)
"${MY[@]}" -e 'SELECT 1' >/dev/null 2>&1 || {
  echo "無法以 socket 連線 MySQL（請用 sudo 執行，或確認服務是否在跑）" >&2; exit 3; }

ROWS=(); HIGH=0; MED=0; PASS=0
q()  { "${MY[@]}" -e "$1" 2>/dev/null || true; }
gv() { q "SELECT IFNULL(@@GLOBAL.$1,'NULL');"; }

# add <項目> <目前值> <期望值> <風險> <佐證指令>
add() {
  local item="$1" cur="$2" want="$3" risk="$4" ev="$5" verdict
  if [[ "$cur" == "$want" ]]; then verdict="通過"; PASS=$((PASS+1))
  else
    verdict="未通過"
    case "$risk" in 高) HIGH=$((HIGH+1)) ;; 中) MED=$((MED+1)) ;; esac
  fi
  ROWS+=("${item}|${cur}|${want}|${risk}|${verdict}|${ev}")
}

# ── ① 網路層 ───────────────────────────────────────────────
BA=$(gv bind_address)
[[ "$BA" == "127.0.0.1" || "$BA" == "::1" || "$BA" =~ ^10\.|^172\.|^192\.168\. ]] \
  && BAV="$BA" || BAV="$BA"
add "bind_address 未綁定全部介面" "$BA" "127.0.0.1" "高" 'mysql -Nse "SELECT @@GLOBAL.bind_address"'
MX=$(q "SELECT IF(COUNT(*)>0,'ON','OFF') FROM information_schema.PLUGINS WHERE PLUGIN_NAME='mysqlx' AND PLUGIN_STATUS='ACTIVE';")
add "X Plugin (33060) 已停用" "${MX:-OFF}" "OFF" "高" "ss -lntp | grep 33060"
EXP=$(ss -lntH "sport = :3306" 2>/dev/null | grep -c '0\.0\.0\.0:3306\|\*:3306' || true)
add "3306 未監聽於 0.0.0.0" "$([[ ${EXP:-0} -eq 0 ]] && echo yes || echo no)" "yes" "高" "ss -lntp | grep 3306"
add "skip_name_resolve" "$(gv skip_name_resolve)" "1" "低" 'mysql -Nse "SELECT @@GLOBAL.skip_name_resolve"'

# ── ② 認證層 ───────────────────────────────────────────────
add "無匿名帳號" "$(q "SELECT COUNT(*) FROM mysql.user WHERE user='';")" "0" "高" \
    "SELECT user,host FROM mysql.user WHERE user=''"
add "無空密碼帳號" "$(q "SELECT COUNT(*) FROM mysql.user WHERE authentication_string='' AND plugin NOT IN ('auth_socket');")" "0" "高" \
    "SELECT user,host FROM mysql.user WHERE authentication_string=''"
add "root 僅限 localhost" "$(q "SELECT COUNT(*) FROM mysql.user WHERE user='root' AND host NOT IN ('localhost','127.0.0.1','::1');")" "0" "高" \
    "SELECT user,host FROM mysql.user WHERE user='root'"
add "無 host='%' 帳號" "$(q "SELECT COUNT(*) FROM mysql.user WHERE host='%';")" "0" "高" \
    "SELECT user,host FROM mysql.user WHERE host='%'"
add "無 test 資料庫授權" "$(q "SELECT COUNT(*) FROM mysql.db WHERE db LIKE 'test%';")" "0" "中" \
    "SELECT * FROM mysql.db WHERE db LIKE 'test%'"
VP=$(q "SELECT COUNT(*) FROM information_schema.COMPONENTS WHERE COMPONENT_URN LIKE '%validate_password%';")
add "已啟用密碼強度檢查" "$([[ "${VP:-0}" -gt 0 ]] && echo yes || echo no)" "yes" "中" \
    "SHOW VARIABLES LIKE 'validate_password.%'"

# ── ③ 授權層 ───────────────────────────────────────────────
add "無非系統帳號持有 FILE" "$(q "SELECT COUNT(*) FROM information_schema.USER_PRIVILEGES WHERE PRIVILEGE_TYPE='FILE' AND GRANTEE NOT LIKE '%root%' AND GRANTEE NOT LIKE '%mysql.%';")" "0" "高" \
    "SELECT GRANTEE FROM information_schema.USER_PRIVILEGES WHERE PRIVILEGE_TYPE='FILE'"
add "無非系統帳號持有 GRANT OPTION" "$(q "SELECT COUNT(*) FROM information_schema.USER_PRIVILEGES WHERE IS_GRANTABLE='YES' AND GRANTEE NOT LIKE '%root%' AND GRANTEE NOT LIKE '%mysql.%';")" "0" "高" \
    "SELECT GRANTEE FROM information_schema.USER_PRIVILEGES WHERE IS_GRANTABLE='YES'"
add "無非系統帳號持有 PROCESS" "$(q "SELECT COUNT(*) FROM information_schema.USER_PRIVILEGES WHERE PRIVILEGE_TYPE='PROCESS' AND GRANTEE NOT LIKE '%root%' AND GRANTEE NOT LIKE '%mysql.%';")" "0" "中" \
    "SELECT GRANTEE FROM information_schema.USER_PRIVILEGES WHERE PRIVILEGE_TYPE='PROCESS'"

# ── ④ 傳輸層 ───────────────────────────────────────────────
add "強制加密連線" "$(gv require_secure_transport)" "1" "高" \
    'mysql -Nse "SELECT @@GLOBAL.require_secure_transport"'
CERT=$(gv ssl_cert)
SELFGEN="no"
if [[ -n "$CERT" && "$CERT" != "NULL" ]]; then
  P="$CERT"; [[ "$P" != /* ]] && P="$(gv datadir)${CERT}"
  if [[ -r "$P" ]] && openssl x509 -in "$P" -noout -subject 2>/dev/null | grep -q 'Auto_Generated'; then
    SELFGEN="yes"
  fi
fi
add "未使用自動產生的自簽憑證" "$([[ "$SELFGEN" == "no" ]] && echo yes || echo no)" "yes" "高" \
    "openssl x509 -in <ssl_cert> -noout -subject -issuer"
add "TLS 版本僅 1.2/1.3" "$(gv tls_version)" "TLSv1.2,TLSv1.3" "中" \
    'mysql -Nse "SELECT @@GLOBAL.tls_version"'
add "無明文連線中" "$(q "SELECT COUNT(DISTINCT t.PROCESSLIST_ID) FROM performance_schema.threads t JOIN performance_schema.status_by_thread s ON s.THREAD_ID=t.THREAD_ID WHERE t.PROCESSLIST_ID IS NOT NULL AND s.VARIABLE_NAME='Ssl_cipher' AND s.VARIABLE_VALUE='';")" "0" "高" \
    "見本篇「階段 0」查詢"

# ── ⑥ 稽核層 ───────────────────────────────────────────────
AUD=$(q "SELECT COUNT(*) FROM information_schema.PLUGINS WHERE PLUGIN_NAME LIKE '%audit%' AND PLUGIN_STATUS='ACTIVE';")
IC=$(gv init_connect)
add "有稽核機制（外掛或 init_connect）" "$([[ "${AUD:-0}" -gt 0 || -n "${IC//NULL/}" ]] && echo yes || echo no)" "yes" "高" \
    "SHOW PLUGINS; SELECT @@GLOBAL.init_connect"
add "general_log 未誤開" "$(gv general_log)" "0" "中" 'mysql -Nse "SELECT @@GLOBAL.general_log"'
add "binlog 已開啟" "$(gv log_bin)" "1" "中" 'mysql -Nse "SELECT @@GLOBAL.log_bin"'
add "error log 詳細度足夠" "$(gv log_error_verbosity)" "3" "低" 'mysql -Nse "SELECT @@GLOBAL.log_error_verbosity"'

# ── ⑦ OS 層 ────────────────────────────────────────────────
add "local_infile 關閉" "$(gv local_infile)" "0" "高" 'mysql -Nse "SELECT @@GLOBAL.local_infile"'
SFP=$(gv secure_file_priv)
add "secure_file_priv 有限制" "$([[ -n "${SFP//NULL/}" || "$SFP" == "NULL" ]] && echo yes || echo no)" "yes" "高" \
    'mysql -Nse "SELECT @@GLOBAL.secure_file_priv"'
DD=$(gv datadir)
add "datadir 權限 750 mysql:mysql" "$(stat -c '%a %U:%G' "$DD" 2>/dev/null || echo unknown)" "750 mysql:mysql" "中" \
    "stat -c '%a %U:%G' $DD"
LOOSE=0
for f in /root/.my.cnf /etc/mysql/my.cnf.d/*.cnf /etc/mysql/mysql.conf.d/*.cnf; do
  [[ -f "$f" ]] || continue
  grep -qi '^[[:space:]]*password' "$f" 2>/dev/null || continue
  [[ "$(stat -c '%a' "$f")" == "600" ]] || LOOSE=$((LOOSE+1))
done
add "含密碼設定檔權限 600" "$LOOSE" "0" "高" "find /etc/mysql /root -name '*.cnf' -exec stat -c '%a %n' {} +"
AA=$(aa-status 2>/dev/null | grep -c 'mysqld' || true)
add "AppArmor/SELinux 保護中" "$([[ "${AA:-0}" -gt 0 ]] && echo yes || echo no)" "yes" "中" \
    "aa-status | grep mysqld   # RHEL: sestatus"

# ── 輸出 ───────────────────────────────────────────────────
emit() {
  if [[ "$MODE" == "markdown" ]]; then
    echo "| 檢查項目 | 目前值 | 期望值 | 風險 | 結果 | 佐證指令 |"
    echo "| --- | --- | --- | --- | --- | --- |"
    for r in "${ROWS[@]}"; do IFS='|' read -r a b c d e f <<<"$r"; echo "| $a | \`$b\` | \`$c\` | $d | $e | \`$f\` |"; done
  else
    printf '%-34s %-22s %-18s %-4s %-6s\n' "檢查項目" "目前值" "期望值" "風險" "結果"
    printf '%.0s-' {1..92}; echo
    for r in "${ROWS[@]}"; do IFS='|' read -r a b c d e f <<<"$r"; printf '%-34s %-22s %-18s %-4s %-6s\n' "$a" "$b" "$c" "$d" "$e"; done
  fi
  echo
  echo "統計：通過 ${PASS} ／ 高風險未通過 ${HIGH} ／ 中風險未通過 ${MED}"
  echo "產出時間：$(date '+%F %T %Z')　主機：$(hostname -f)　版本：$(mysql --version | awk '{print $3,$4,$5}')"
}

if [[ -n "$OUT" ]]; then
  emit > "$OUT"; chmod 600 "$OUT"; echo "已寫入 $OUT（權限 600）"
else
  emit
fi

[[ $HIGH -gt 0 ]] && exit 2
[[ $MED  -gt 0 ]] && exit 1
exit 0
SCRIPT
sudo chmod 750 /usr/local/bin/mysql-hardening-check.sh
sudo bash -n /usr/local/bin/mysql-hardening-check.sh && echo "語法檢查通過"
```

### 步驟 1：取得整改前基線

```bash
# ★★★ 報告目錄含帳號清單，權限收緊到 750
sudo install -d -m 750 -o root -g root /var/log/db-audit
sudo mysql-hardening-check.sh --out /var/log/db-audit/before_$(date +%F).txt
sudo cat /var/log/db-audit/before_$(date +%F).txt
```

預期輸出（節錄）：

```text
檢查項目                           目前值                 期望值             風險 結果
--------------------------------------------------------------------------------------------
bind_address 未綁定全部介面        0.0.0.0                127.0.0.1          高   未通過
X Plugin (33060) 已停用            ON                     OFF                高   未通過
無 host='%' 帳號                   3                      0                  高   未通過
強制加密連線                       0                      1                  高   未通過
未使用自動產生的自簽憑證           no                     yes                高   未通過
有稽核機制（外掛或 init_connect）  no                     yes                高   未通過
local_infile 關閉                  1                      0                  高   未通過
...
統計：通過 9 ／ 高風險未通過 8 ／ 中風險未通過 3
```

★★★ 這份輸出**原封不動存檔**，就是稽核回覆表的「整改前」欄位來源。

### 步驟 2～6：整改順序

順序不能亂，每一步都是「改 → 驗證 → 才做下一步」：

| 步驟 | 動作 | 驗證方式 | 回滾 |
| --- | --- | --- | --- |
| **2** | 收監聽面：`bind-address=127.0.0.1,10.10.20.11`、`mysqlx=OFF`、ufw 白名單 | 從外部 `nmap -Pn -p 3306,33060` 得到 `filtered` | 刪 drop-in 檔重啟 |
| **3** | 換憑證：自建 CA 簽發 → `ALTER INSTANCE RELOAD TLS` | `openssl s_client -starttls mysql` 看到機關 CA | 換回 `.bak` 再 RELOAD |
| **4** | 客戶端帶 CA、逐帳號 `REQUIRE SSL` | 階段 0 查詢的空白列歸零 | `ALTER USER ... REQUIRE NONE` |
| **5** | 全域 `SET GLOBAL require_secure_transport=ON`，觀察一個上班日後 `SET PERSIST` | error log 無 `insecure transport` | `SET GLOBAL ...=OFF`（socket 進去） |
| **6** | 權限收斂、`local_infile=OFF`、`init_connect` 稽核、error log 送 Wazuh | 再跑一次腳本 | 個別回復 |

```bash
# 步驟 2 的外部驗證（在辦公網段的維運筆電執行）
nmap -Pn -p 3306,33060,33062 db01.example.gov.tw
```

預期輸出：

```text
PORT      STATE    SERVICE
3306/tcp  filtered mysql
33060/tcp filtered mysqlx
33062/tcp filtered unknown
```

```bash
# 步驟 3 的憑證備份（★★★★ 換之前一定先留退路）
sudo cp -a /etc/mysql/ssl /etc/mysql/ssl.bak.$(date +%F)
sudo ls -d /etc/mysql/ssl.bak.*
```

### ★★★★★ 回滾：憑證換錯，全部應用瞬間連不上

**症狀**：`ALTER INSTANCE RELOAD TLS` 之後或重啟之後，所有應用同時報
`SSL connection error` / `Can't connect`，前台白畫面。

**五分鐘復原程序**（照順序做，不要跳）：

```bash
# 【0】SSH 進資料庫主機。★★★★★ 記住：Unix socket 不受 TLS 影響，你一定進得去
ssh ops@db01.example.gov.tw
sudo mysql -e "SELECT 1;"          # 預期輸出：1 → 資料庫本身活著，問題只在 TLS

# 【1】先讓服務恢復（30 秒內），細節之後再查
sudo mysql -e "SET GLOBAL require_secure_transport = OFF;"
sudo mysql -Nse "SELECT @@GLOBAL.require_secure_transport;"      # 預期輸出：0
# → 客戶端會退回 PREFERRED，馬上連得上。★★★ 這是「先止血」，不是終點

# 【2】把憑證換回備份
sudo rm -rf /etc/mysql/ssl
sudo cp -a /etc/mysql/ssl.bak.2026-08-29 /etc/mysql/ssl
sudo mysql -e "ALTER INSTANCE RELOAD TLS;"                       # 預期輸出：Query OK
sudo mysql -Nse "SHOW STATUS LIKE 'Ssl_cipher';" || true

# 【3】若 mysqld 根本起不來（憑證壞 + require_secure_transport=ON 會導致啟動失敗）
sudo tail -20 /var/log/mysql/error.log
#   看到 Failed to set up SSL / Server SSL context ... 就用臨時 drop-in 蓋掉
sudo tee /etc/mysql/mysql.conf.d/00-rescue.cnf >/dev/null <<'EOF'
[mysqld]
require_secure_transport = OFF
ssl_ca   =
ssl_cert =
ssl_key  =
EOF
sudo systemctl start mysql
sudo systemctl is-active mysql                                   # 預期輸出：active

# 【4】若 SET PERSIST 已經寫進去了，要清掉
sudo mysql -e "RESET PERSIST require_secure_transport;"
sudo grep -c require_secure_transport /var/lib/mysql/mysqld-auto.cnf   # 預期輸出：0

# 【5】服務恢復後，回到測試機重做憑證，確認 SAN 涵蓋所有連線位址再上線
#      修好後移除 00-rescue.cnf 並重啟
sudo rm /etc/mysql/mysql.conf.d/00-rescue.cnf
```

> [!danger] ★★★★★ 回滾時最容易犯的錯
> - **去改客戶端**：十幾台應用主機一台一台改，二十分鐘過去服務還是掛的。
>   **一律先在資料庫端止血**（步驟【1】一行指令），這才是最快的路。
> - **直接重啟 mysqld 想「重置一下」**：如果 `require_secure_transport=ON` 已經 PERSIST
>   而憑證是壞的，★★★★★ **重啟之後 mysqld 會起不來**，從「連不上」變成「服務全死」。
>   先做【1】，確定不需要重啟再說。
> - **關掉 AppArmor 排除問題**：改用 `/etc/apparmor.d/local/` 加規則。

### 驗收檢查表

| # | 檢查項 | 指令 | 預期結果 |
| --- | --- | --- | --- |
| 1 | 僅監聽內網與 loopback | `sudo ss -lntp \| grep mysqld` | 只有 `127.0.0.1:3306`、`10.10.20.11:3306` |
| 2 | ★★★★ 33060 已消失 | `sudo ss -lntp \| grep 33060` | 無輸出 |
| 3 | ★★★★ 外部連不上 | `nmap -Pn -p 3306,33060 db01…` | 兩個都 `filtered` |
| 4 | 憑證由機關 CA 簽發 | `openssl s_client -connect …:3306 -starttls mysql` | issuer 是 Example Agency Internal CA |
| 5 | ★★★★ SAN 涵蓋 IP 與主機名 | `openssl x509 … -ext subjectAltName` | 含 `DNS:db01…` 與 `IP:10.10.20.11` |
| 6 | 強制加密已生效 | `mysql -Nse "SELECT @@GLOBAL.require_secure_transport"` | `1` |
| 7 | ★★★★★ 無明文連線 | 「階段 0」查詢 | 沒有 `tls_ver` 空白的列 |
| 8 | 應用實際走 TLS | `php artisan tinker --execute=…Ssl_cipher…` | 非空字串 |
| 9 | 無 `host='%'` 帳號 | `SELECT COUNT(*) FROM mysql.user WHERE host='%'` | `0` |
| 10 | ★★★★ 應用帳號無 FILE | `SHOW GRANTS FOR 'app_rw'@'10.10.20.%'` | 只有 `appdb.*` 的 DML |
| 11 | `local_infile` 關閉 | `mysql -Nse "SELECT @@GLOBAL.local_infile"` | `0` |
| 12 | 連線稽核有紀錄 | `SELECT COUNT(*) FROM auditdb.conn_log WHERE ts>NOW()-INTERVAL 1 HOUR` | `> 0` |
| 13 | Wazuh 收得到 error log | Wazuh Dashboard 搜 `location:/var/log/mysql/error.log` | 有事件 |
| 14 | 高風險項目歸零 | `sudo mysql-hardening-check.sh; echo $?` | `0` |
| 15 | ★★★★ 回滾路徑可用 | `sudo mysql -e "SELECT 1"` | `1`（socket 永遠通） |

### 產出稽核回覆

```bash
sudo mysql-hardening-check.sh --markdown --out /var/log/db-audit/after_$(date +%F).md
```

預期輸出：

```text
已寫入 /var/log/db-audit/after_2026-08-29.md（權限 600）
```

整改前後對照（真實案例的樣子）：

| 項目 | 整改前 | 整改後 | 佐證 |
| --- | --- | --- | --- |
| 監聽介面 | `0.0.0.0`，33060 對外 | `127.0.0.1,10.10.20.11`，X Plugin 停用 | 外部 nmap 全 `filtered` |
| 遠端可連帳號 | 3 個 `'%'`（含 `vendor_tmp`） | 0 個，全部限 `10.10.20.%` | `mysql.user` 查詢 |
| 傳輸加密 | 自動自簽、`PREFERRED` | 機關 CA、`require_secure_transport=ON` | `s_client` 輸出 |
| 稽核軌跡 | 無 | `conn_log` + error log 送 Wazuh，保存 180 天 | Wazuh 事件截圖 |
| `local_infile` | ON | OFF | 變數查詢 |
| 高風險未通過項 | 8 | 0 | 腳本離開碼 `0` |

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 改完 `require_secure_transport=ON` 後**全部應用同時**連不上，前台白畫面 | 還有客戶端沒帶 CA／仍用 `DISABLED` | `sudo mysql -e "SET GLOBAL require_secure_transport=OFF"` 先止血，回到「階段 0」查詢確認空白列歸零再開 |
| ★★★★★ 資安通報說你的資料庫被列在網路空間搜尋引擎上 | `bind-address=0.0.0.0` + 防火牆放行 `Anywhere` | 立即 `ufw delete` 該規則 → 收 `bind-address` → **假設已外洩**，查 `conn_log` 與 error log 的外部來源，啟動應變流程 |
| ★★★★ `ERROR 2026 (HY000): SSL connection error: Failed to verify the server certificate` | 憑證 SAN 沒涵蓋應用實際連的位址（常是只寫 DNS、應用用 IP） | `openssl x509 -ext subjectAltName` 確認 → 重簽含 `IP:` 的憑證 → `ALTER INSTANCE RELOAD TLS` |
| ★★★★ `ERROR 1130: Host 'x' is not allowed to connect` | 帳號 host 不符（常見於剛開 `skip_name_resolve` 或剛 `RENAME USER`） | `SELECT user,host FROM mysql.user WHERE user='app_rw'`；把主機名形式改成網段形式 |
| ★★★★ mysqld 重啟後起不來，error log 只寫 `Permission denied`，但 `ls -l` 權限正確 | AppArmor（Ubuntu）／SELinux（RHEL）擋住新路徑 | `sudo dmesg \| grep -i apparmor` 或 `ausearch -m avc -ts recent`；到 `/etc/apparmor.d/local/` 加規則，**不要** `aa-complain` |
| ★★★★ 深夜應用突然大量 `ERROR 1820: You must reset your password` | `default_password_lifetime` 對應用帳號生效 | `SET PERSIST default_password_lifetime=0`，人用帳號改用 `ALTER USER … PASSWORD EXPIRE INTERVAL 90 DAY` |
| ★★★★ 所有新連線被拒，錯誤訊息指向一段 SQL | `init_connect` 的語句失敗（表被刪、權限沒給） | `sudo mysql`（socket + `CONNECTION_ADMIN` 會跳過 `init_connect`）進去 `SET GLOBAL init_connect=''` |
| ★★★★ 磁碟被寫滿，資料庫停止寫入 | `general_log` 被開著忘了關 | `SET GLOBAL general_log=OFF`；`shred -u` 刪掉日誌（★★★ 內含個資）；補上磁碟告警 |
| ★★★ `openssl s_client -connect db01:3306` 直接失敗，以為沒開 TLS | MySQL 是先明文問候再升級 | 加 `-starttls mysql` |
| ★★★ `ALTER INSTANCE RELOAD TLS` 回 `ERROR 3852: Failed to update the Server TLS context` | 新憑證與私鑰不成對，或 mysql 讀不到檔 | `openssl x509 -noout -modulus -in cert \| md5sum` 與 `openssl rsa -noout -modulus -in key \| md5sum` 比對；★★★ 失敗時**舊 context 仍在用**，服務不會中斷 |
| ★★★ 改了 `mysqlx_bind_address` 沒生效，33060 還在 | 這個變數**不是動態的** | 寫進設定檔後 `systemctl restart mysql`；用不到就直接 `mysqlx = OFF` |
| ★★★ `SET PERSIST` 改的值重啟後又跑掉 | `mysqld-auto.cnf` 被同名的 drop-in 檔覆蓋（讀取順序在後） | `SELECT * FROM performance_schema.persisted_variables`；統一在 drop-in 管理，或 `RESET PERSIST <var>` |
| ★★★ 表空間加密開了，但 `mysqldump` 出來的檔還是明文 | 表空間加密只保護磁碟上的檔案 | 備份另外加密，見 [[05-MySQL-備份與還原]] |
| ★★ 健檢腳本回報 `datadir 權限 unknown` | 腳本不是用 `sudo` 跑，`stat` 讀不到 | 一律 `sudo mysql-hardening-check.sh` |

### 排查步驟

**【1】確認資料庫本身還活著（先分清楚是「服務死了」還是「連不上」）**

```bash
sudo systemctl is-active mysql && sudo mysql -e "SELECT 1;"
```

預期輸出：`active` 與 `1`。
★★★★ 兩個都正常 → 問題在**網路或 TLS**，往【2】。
`is-active` 是 `failed` → 服務起不來，直接跳【6】看 error log。

**【2】從資料庫主機本機連（排除網路與防火牆）**

```bash
mysql -h 127.0.0.1 -P 3306 -u app_rw -p appdb -e "SELECT 1;"
```

本機 TCP 通、遠端不通 → 問題在**防火牆或 bind-address**，往【3】。
本機 TCP 也不通、但 `sudo mysql`（socket）通 → 問題在 **TLS 或帳號**，往【4】。

**【3】確認監聽與防火牆**

```bash
sudo ss -lntp | grep mysqld
sudo ufw status verbose | grep 3306
```

`ss` 只看到 `127.0.0.1:3306` 而應用在別台 → `bind-address` 收太緊，加上內網位址。
`ss` 有內網位址但 ufw 沒有對應 `ALLOW` → 補白名單規則。

**【4】判斷是 TLS 還是帳號問題（看錯誤碼）**

| 錯誤 | 問題在 | 下一步 |
| --- | --- | --- |
| `2026 SSL connection error` | TLS | 【5】 |
| `1045 Access denied` | 密碼 | 重設密碼 |
| `1130 Host not allowed` | 帳號 host | `SELECT user,host FROM mysql.user` |
| `3159 Connections using insecure transport are prohibited` | 客戶端沒開加密 | 客戶端加 `--ssl-mode=VERIFY_CA --ssl-ca=…` |

**【5】驗證伺服器憑證**

```bash
openssl s_client -connect 127.0.0.1:3306 -starttls mysql </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
```

看到 `Auto_Generated` → 憑證根本沒換成功，檢查 `ssl_cert` 路徑與 AppArmor。
issuer 正確但客戶端仍失敗 → 比對 SAN 是否含應用用的位址；再確認客戶端的 `--ssl-ca`
指到**同一張** CA（`openssl x509 -noout -fingerprint -sha256` 兩邊比對）。

**【6】讀 error log（★★★★ 這一步不能跳）**

```bash
sudo tail -n 60 /var/log/mysql/error.log
sudo journalctl -u mysql -n 60 --no-pager
```

| 訊息片段 | 代表 |
| --- | --- |
| `Failed to set up SSL because of the following SSL library error` | 憑證／私鑰不成對或讀不到 |
| `Bind on TCP/IP port: Permission denied` | ★★★ SELinux 埠標籤（RHEL）或埠被占用 |
| `Access denied for user` 大量同來源 | 有人在猜密碼 → 查 `CONNECTION_CONTROL_FAILED_LOGIN_ATTEMPTS` |
| `Aborted connection … insecure transport are prohibited` | 還有客戶端沒加密，**不要**急著關掉強制，先找出是誰 |

**【7】找出還在用明文的是誰**

用「階段 0」那段 `performance_schema` 查詢，`tls_ver` 空白的列就是名單。
記下 `host` 欄，到那台主機改連線設定，改完再查一次確認消失。

**【8】確認整改沒有回頭**

```bash
sudo mysql-hardening-check.sh; echo "exit=$?"
```

預期輸出結尾：`統計：通過 23 ／ 高風險未通過 0 ／ 中風險未通過 0` 與 `exit=0`。
★★★ 把這支腳本排進每月的巡檢（cron 或 systemd timer），
組態飄移（有人臨時改了設定沒改回來）才抓得到。

---

## 安全性注意事項

> [!danger] 絕對不要做的事
> - ★★★★★ **`ufw allow 3306/tcp`（不帶 `from`）**：等於把資料庫掛上網際網路。
>   廠商要連請用 SSH 隧道，不要開防火牆。
> - ★★★★★ **把正式庫的 dump 直接還原到測試機、開發機，或交給廠商**：
>   這是**個資外洩**，不是「提供測試資料」。見下一段的正確流程。
> - ★★★★★ **`GRANT ALL PRIVILEGES ON *.* TO 'app'@'%'`**：
>   注入一次就等於整台主機失守（`FILE` 可寫 webshell、可讀 `/etc/shadow`）。
> - ★★★★★ **刪掉 keyring 金鑰檔或不備份它**：加密表空間永久打不開，備份也救不了。
> - ★★★★ **為了排除問題 `setenforce 0` / `aa-complain` / `ufw disable`**：
>   臨時關掉的東西沒有人會記得開回來，稽核時這一項直接不通過。
> - ★★★★ **長期開著 `general_log`**：它會把 `WHERE id_no='A123456789'` 原樣寫進檔案，
>   日誌檔本身變成一份未納管的個資檔案。
> - ★★★ **在 shell 裡寫 `mysql -uroot -pP@ssw0rd`**：密碼會進 `~/.bash_history`
>   與 `ps aux`，同機任何使用者都看得到。用 `--login-path` 或互動輸入。

### ★★★★ 個資法情境（機關必答題）

> [!warning] 條號請自行核對
> 以下法條僅供對話時定位，**請以全國法規資料庫的現行條文為準**；
> 通報窗口與時限依貴機關的主管機關函文與資安事件通報流程辦理。
> 完整說明見 [[07-台灣資安法規與個資法]]。

**五個動作，缺一項稽核就會問**：

| # | 動作 | 具體做法 | 星級 |
| --- | --- | --- | --- |
| 1 | **盤點哪些表是個資** | 建一份資料表清冊，標註欄位（姓名／身分證字號／電話／地址／病歷）、法定保存期限、負責科室 | ★★★★ |
| 2 | **存取可追溯** | `conn_log` + binlog + error log 送集中日誌，保存期限寫進文件 | ★★★★ |
| 3 | **測試／委外資料一律去識別化** | 見下方流程 | ★★★★★ |
| 4 | **備份與匯出檔的保存與銷毀** | 加密、限定保存期限、到期 `shred -u`，銷毀留紀錄 | ★★★★ |
| 5 | **外洩應變** | 事前寫好通報流程與聯絡窗口，事後查明範圍並通知當事人 | ★★★★★ |

盤點起手式：

```sql
SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, COLUMN_TYPE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA NOT IN ('mysql','sys','information_schema','performance_schema')
  AND (COLUMN_NAME REGEXP 'id_no|idno|ssn|uid_no|birth|phone|mobile|tel|addr|email|name'
       OR COLUMN_COMMENT REGEXP '身分證|生日|電話|地址|姓名')
ORDER BY TABLE_SCHEMA, TABLE_NAME;
```

預期輸出：

```text
+--------------+---------+-------------+--------------+
| TABLE_SCHEMA | TABLE_NAME | COLUMN_NAME | COLUMN_TYPE |
+--------------+---------+-------------+--------------+
| appdb        | members | id_no       | varchar(10)  |   ★★★★★ 身分證字號
| appdb        | members | mobile      | varchar(20)  |
| appdb        | members | address     | varchar(255) |
+--------------+---------+-------------+--------------+
```

#### ★★★★★ 交測試環境／廠商的正確流程

```text
正式庫 ──dump──▶ ①隔離的遮罩主機（不對外、不連測試網段）
                     │
                     ├─▶ ②還原 → ③執行遮罩 SQL → ④驗證無殘留
                     │
                     └──re-dump──▶ ⑤交付檔（仍要加密傳輸）──▶ 測試環境／廠商
                                        │
                                        └─▶ ⑥留下交付紀錄：誰、何時、什麼範圍、何時銷毀
```

```sql
-- ③ 遮罩（在遮罩主機上執行，★★★★ 絕對不要在正式庫跑）
UPDATE appdb.members SET
  name    = CONCAT(LEFT(name,1), '○○'),
  id_no   = CONCAT(LEFT(id_no,1), '*********'),
  mobile  = CONCAT('09', LPAD('', 8, '*')),
  email   = CONCAT('user', id, '@example.invalid'),
  address = '（已遮罩）',
  birth   = DATE_FORMAT(birth, '%Y-01-01');   -- ★★★ 只留年份，保留分析價值
```

```bash
# ④ 驗證無殘留：用身分證字號格式去掃交付檔
grep -ocE '[A-Z][12][0-9]{8}' masked.sql
```

預期輸出：`0`。
★★★★ 不是 0 就**不准交付** —— 通常是漏了某張關聯表（`member_logs`、`applications`）。

> [!danger] ★★★★★ 「廠商說他們會自己刪」不是控制措施
> 一旦未去識別化的正式資料離開你的管理範圍，就已經構成外洩，
> 之後對方刪不刪都不影響這個事實。**去識別化必須在資料離開之前完成。**
>
> 多數情況下廠商只需要**結構**，不需要資料：
> ```bash
> $ mysqldump --no-data --routines --triggers appdb > appdb-schema.sql
> ```
> 這是最安全、也最常被忽略的答案。

### TWGCB 對應：誠實的說法

> [!warning] ★★★ 不要編造基準條號
> TWGCB（政府組態基準）目前發布的基準**以作業系統、瀏覽器、網路設備與部分應用軟體為主**。
> 撰稿當下（2026-08）**無法確認**有針對 MySQL／MariaDB 的專屬基準文件。
>
> **動筆前你必須自己做這件事**：到 NCCST 的 GCB 專區
> <https://www.nccst.nat.gov.tw/GCB> 與「TWGCB-ID 對照表」確認：
> - 有對應資料庫的基準 → 把編號與版本寫進 frontmatter 的 `baseline_version`，逐項對應
> - 沒有 → 在文件裡明講「無對應 TWGCB 基準」，改用 **CIS MySQL Benchmark** 或機關自訂檢核表
>
> ★★★★★ **絕對不要在稽核回覆表上填一個查證不到的 TWGCB 編號。** 這比留空白嚴重得多。

**沒有資料庫基準時，資料庫主機仍然被 OS 層的 TWGCB 涵蓋**，把這幾類講清楚就能對應：

| OS 層 TWGCB 類別 | 在資料庫主機上怎麼落實 | 佐證 |
| --- | --- | --- |
| 帳號與密碼政策 | OS 帳號用 PAM；**資料庫帳號另用 `validate_password` component** 並在文件說明兩者分開 | `SHOW VARIABLES LIKE 'validate_password.%'` |
| 日誌與稽核 | `log_error_verbosity=3`、`conn_log`、binlog，全部送集中日誌並保存 ≥ 6 個月 | Wazuh 事件、輪替設定 |
| 檔案與目錄權限 | `datadir` 750、私鑰 600、含密碼設定檔 600 | `stat -c '%a %U:%G'` |
| 服務最小化 | 停用 X Plugin、關閉 `local_infile`、限制 `secure_file_priv` | 健檢腳本輸出 |
| 網路存取控制 | `bind-address` + ufw 白名單 + SSH 隧道 | 外部 nmap 結果 |
| 強制存取控制 | AppArmor／SELinux 維持 enforce | `aa-status` / `sestatus` |

導入與檢測流程見 [[01-TWGCB概念與法規要求]]、[[04-TWGCB-Linux本機導入]]
與 [[07-TWGCB-Linux檢測與符合性報告]]；符合性報告的組織方式見 [[09-資安稽核與符合性檢核]]
與 [[08-系統強化與稽核]]。

---

## 速查表

### 關鍵設定項

| 設定項 | 期望值 | 星級 | 備註 |
| --- | --- | --- | --- |
| `bind_address` | `127.0.0.1` 或 `127.0.0.1,<內網IP>` | ★★★★★ | 不是動態變數，要重啟 |
| `mysqlx` | `OFF` | ★★★★ | 用不到就關；要用改 `mysqlx_bind_address=127.0.0.1` |
| `require_secure_transport` | `ON` | ★★★★★ | 動態；先 `SET GLOBAL` 再 `SET PERSIST` |
| `tls_version` | `TLSv1.2,TLSv1.3` | ★★★ | 8.0.28 起 TLSv1/1.1 已移除 |
| `local_infile` | `OFF` | ★★★★ | 客戶端也要關 |
| `secure_file_priv` | `NULL` 或固定目錄 | ★★★★ | **空字串最危險** |
| `skip_name_resolve` | `ON` | ★★★ | 開之前先確認沒有用主機名寫的帳號 |
| `default_password_lifetime` | `0` | ★★★★ | 人用帳號個別設 `PASSWORD EXPIRE INTERVAL` |
| `log_error_verbosity` | `3` | ★★★ | 2 記不到 Note 級事件 |
| `general_log` | `OFF` | ★★★★ | 只在排查時短期開 |
| `admin_address` | `127.0.0.1` | ★★★ | 保留一條管理救生管道（33062） |

### 一行驗證指令

| 要驗證什麼 | 指令 | 星級 |
| --- | --- | --- |
| 監聽在哪 | `sudo ss -lntp \| grep mysqld` | ★★★★★ |
| 外部連不連得到 | `nmap -Pn -p 3306,33060 <host>` | ★★★★★ |
| 目前用哪張憑證 | `openssl s_client -connect 127.0.0.1:3306 -starttls mysql` | ★★★★ |
| 我這條連線加密了嗎 | `mysql … -e "\s" \| grep -i ssl` 或 `SHOW STATUS LIKE 'Ssl_cipher'` | ★★★★ |
| 誰還在用明文 | 「階段 0」的 `performance_schema` 查詢 | ★★★★★ |
| 有沒有 `'%'` 帳號 | `SELECT user,host FROM mysql.user WHERE host='%'` | ★★★★ |
| 誰有 FILE 權限 | `SELECT GRANTEE FROM information_schema.USER_PRIVILEGES WHERE PRIVILEGE_TYPE='FILE'` | ★★★★★ |
| 有人在猜密碼嗎 | `SELECT * FROM information_schema.CONNECTION_CONTROL_FAILED_LOGIN_ATTEMPTS` | ★★★★ |
| 整體健檢 | `sudo mysql-hardening-check.sh` | ★★★★ |

### 檔案路徑（Ubuntu 主線）

| 路徑 | 內容 | 權限 | 星級 |
| --- | --- | --- | --- |
| `/etc/mysql/mysql.conf.d/99-hardening.cnf` | 本篇所有加固設定 | 644 root:root | ★★★★ |
| `/var/lib/mysql/mysqld-auto.cnf` | `SET PERSIST` 寫入處 | 600 mysql:mysql | ★★★ |
| `/etc/mysql/ssl/server-key.pem` | 伺服器私鑰 | **600 mysql:mysql** | ★★★★★ |
| `/var/lib/mysql-keyring/component_keyring_file` | 表空間加密金鑰 | 600 mysql:mysql | ★★★★★ |
| `/usr/sbin/mysqld.my` | keyring component manifest | 644 root:root | ★★★ |
| `/var/log/mysql/error.log` | 錯誤與連線事件 | 640 mysql:adm | ★★★★ |
| `~/.mylogin.cnf` | 混淆過的登入資訊（**非加密**） | 600 | ★★★ |

> [!info]- RHEL 系路徑對照
> | Ubuntu | RHEL |
> | --- | --- |
> | `/etc/mysql/mysql.conf.d/` | `/etc/my.cnf.d/` |
> | 服務名 `mysql` | 服務名 `mysqld`（MariaDB 為 `mariadb`） |
> | `/var/log/mysql/error.log` | `/var/log/mysqld.log` |
> | AppArmor `/etc/apparmor.d/local/` | SELinux `semanage fcontext` |
> | `ufw` | `firewalld` |

---

## 練習題

> [!question]- 練習 1：找出你這台機器的暴露面
> 在一台測試用的 MySQL 8 主機上，完成以下事情並把輸出貼進報告：
> 1. 用 `ss` 列出所有 mysqld 監聽的位址與埠
> 2. 從**另一台**主機用 `nmap` 掃 3306、33060、33062
> 3. 判斷這台機器目前屬於「安全」「僅內網暴露」還是「對外暴露」
>
> **參考解答**
> ```bash
> $ sudo ss -lntp | grep mysqld
> LISTEN 0 151 0.0.0.0:3306  0.0.0.0:* users:(("mysqld",pid=1183,fd=23))
> LISTEN 0 70  0.0.0.0:33060 0.0.0.0:* users:(("mysqld",pid=1183,fd=35))
>
> $ nmap -Pn -p 3306,33060,33062 192.168.56.20
> 3306/tcp  open  mysql
> 33060/tcp open  mysqlx
> ```
> 判定：**對外暴露**。★★★★ 兩個埠都 `open`，代表 `bind-address=0.0.0.0` 且防火牆沒擋。
> 處置順序：先補防火牆規則（立即見效），再改 `bind-address` 與 `mysqlx=OFF`（需重啟）。
> ★★★ 先防火牆後設定，因為防火牆不用重啟服務，能馬上止血。

> [!question]- 練習 2：分辨「有加密」與「安全」
> 在同一台 MySQL 上，分別用 `--ssl-mode=PREFERRED` 與 `--ssl-mode=VERIFY_IDENTITY`
> （帶自動產生的 `/var/lib/mysql/ca.pem`）連線。解釋兩者的結果差在哪、為什麼。
>
> **參考解答**
> ```bash
> $ mysql --ssl-mode=PREFERRED -h 127.0.0.1 -u ops -p -e "\s" | grep -i ssl
> SSL:  Cipher in use is TLS_AES_256_GCM_SHA384        # ★ 有加密
>
> $ mysql --ssl-mode=VERIFY_IDENTITY --ssl-ca=/var/lib/mysql/ca.pem \
>         -h 127.0.0.1 -u ops -p -e "SELECT 1"
> ERROR 2026 (HY000): SSL connection error: Failed to verify the server certificate
> ```
> 原因：★★★★ 自動產生的憑證 CN 是 `MySQL_Server_8.0.x_Auto_Generated_Server_Certificate`，
> 沒有 SAN，也不含主機名，所以主機名比對必定失敗。
> 這正好證明「PREFERRED 顯示已加密」**不代表你驗證過對方是誰** ——
> 中間人架一台假伺服器，PREFERRED 一樣會顯示加密成功。
> 解法是用機關 CA 重簽一張 SAN 涵蓋主機名與 IP 的憑證。

> [!question]- 練習 3：設計一份交給廠商的測試資料
> 廠商要一份 `members` 表的資料做介面測試（12 萬筆，含身分證字號、手機、地址）。
> 寫出你的完整流程與驗證方式。
>
> **參考解答**
> 1. ★★★★★ **先問廠商真的需要資料還是只需要結構**。多數情況 `mysqldump --no-data` 就夠。
> 2. 真的需要資料時：在**隔離主機**還原正式備份 → 執行遮罩 SQL（姓名留姓、身分證留首字、
>    手機與地址全遮、生日只留年份）→ 檢查所有關聯表（`member_logs`、`applications`）是否也遮了。
> 3. 驗證：`grep -ocE '[A-Z][12][0-9]{8}' masked.sql` 必須為 `0`；
>    另外抽 20 筆人工目視。★★★★ 不是 0 就不准交付。
> 4. 交付檔加密（`age` 或 `gpg`），密碼另管道傳遞。
> 5. ★★★★ 留下交付紀錄：交付對象、日期、資料範圍、約定銷毀日期、銷毀回覆。
> 6. 遮罩主機用完立即銷毀（`shred` 或整台 VM 刪除）。

---

## 小測驗

Q1. `nmap` 顯示 3306 是 `open`，但用 `mysql -h` 連過去得到 `ERROR 1130: Host is not allowed to connect`。這台機器算不算安全？為什麼？

Q2. MySQL 8 開機時會自動產生一組憑證。既然「已經有 TLS」，為什麼還要換成機關自建 CA 簽發的憑證？

Q3. 下面這行指令會發生什麼事？`sudo ufw allow 3306/tcp`

Q4. 你把 `bind-address` 從 `0.0.0.0` 改成 `127.0.0.1` 並重啟，但掃描報告仍指出「33060 對外開放」。哪裡漏了？

Q5. （是非）啟用 InnoDB 表空間加密之後，`mysqldump` 產生的備份檔也是加密的。

Q6. 你打算把 `default_password_lifetime` 設成 90 以符合「密碼每 90 天更換」的要求。這樣做有什麼風險？正確做法是什麼？

Q7. `--ssl-mode` 的 `REQUIRED` 與 `VERIFY_CA` 差在哪？哪一個擋得住中間人？

Q8. 你用 `init_connect` 記錄所有連線，但發現管理員 `ops_alice` 的連線完全沒有紀錄。為什麼？

Q9. 「這行指令會發生什麼」：`SET GLOBAL require_secure_transport = ON;` 在一台還有 12 條明文連線的正式資料庫上執行。

Q10. 稽核委員要求你填寫「資料庫已依 TWGCB-XX-XXX 完成組態設定」。你查不到對應 MySQL 的 TWGCB 基準編號。該怎麼回覆？

> [!question]- 測驗答案
> **Q1. 不安全。★★★★**
> `open` 代表 TCP 三次握手成功、MySQL 願意跟對方講話 —— 唯一擋住他的是**帳號的 host 限制**，
> 那是最後一道，不是第一道。攻擊者此時可以讀版本橫幅去找已知漏洞、對 `root` 做密碼噴灑、
> 用大量連線耗掉 `max_connections`。
> 唯二可接受的結果是逾時（`ERROR 2003 … (110)`）或連線被拒（`(111)`）。
> 處置：先 `ufw` 白名單止血（不用重啟），再收 `bind-address`。
> 見「從外部主機驗證」那張錯誤訊息對照表。
>
> **Q2. 因為自動憑證只能加密，不能驗證身分。★★★★**
> 自動產生的憑證：CN 是 `MySQL_Server_8.0.x_Auto_Generated_Server_Certificate`、
> **沒有 SAN**、簽發者是每台機器自己產的 CA。
> 客戶端沒有共同的信任根，也無法比對主機名，所以只能用 `--ssl-mode=PREFERRED`。
> 結果是：攻擊者在同網段做 ARP 欺騙、架一台假 MySQL，客戶端**一樣顯示連線已加密**，
> 然後把帳號密碼與查詢送給攻擊者。
> ★★★★ 加密解決竊聽，驗證解決冒充；只做前者等於只做一半。見「傳輸加密」開頭的 danger callout。
>
> **Q3. ★★★★★ 它會把 3306 對「任何來源」放行（`ALLOW IN Anywhere`）。**
> 沒有 `from` 子句的 `ufw allow` 就是全開。配上 `bind-address=0.0.0.0`，
> 你的資料庫在幾小時內就會被網路空間搜尋引擎索引到。
> 正確寫法是 `sudo ufw allow from 10.10.20.21 to any port 3306 proto tcp comment 'app01'`。
> 廠商要連請用 SSH 隧道，不要開防火牆規則。
> 檢查方式：`sudo ufw status numbered`，看到 `Anywhere` 就是紅燈。見「防火牆白名單」。
>
> **Q4. 漏了 X Plugin。★★★★**
> MySQL 8 預設載入 X Plugin，額外監聽 **33060/tcp**，它由 `mysqlx_bind_address` 控制，
> **不受 `bind_address` 影響**。這是稽核掃描最常出現的「未知服務」。
> 解法：用不到就 `mysqlx = OFF`；要用則 `mysqlx_bind_address = 127.0.0.1`。
> ★★★ 這兩個都不是動態變數，改完必須重啟服務。
> 驗證 `sudo ss -lntp | grep 33060` 應該沒有輸出。見「33060 幾乎每次都被忘記」。
>
> **Q5. 錯。★★★★**
> `mysqldump` 是透過**正常的資料庫連線**讀資料，讀到的是**解密後的明文**，
> 所以 dump 檔完全沒有被表空間加密保護。
> 表空間加密擋的是「整顆硬碟被搬走」「硬碟送修未消磁」；
> 備份檔外流要靠**備份檔本身加密**（`age` / `gpg`）。
> ★★★★ 這兩層擋不同的威脅，必須分開做、分開驗證。
> 見「靜態資料保護：三層各擋什麼」那張表與 [[05-MySQL-備份與還原]]。
>
> **Q6. 風險是應用會在半夜集體掛掉。★★★★**
> `default_password_lifetime` 對**所有帳號**生效，包含 `app_rw` 這種應用帳號。
> 到期後應用連進來會拿到 `ERROR 1820: You must reset your password using ALTER USER…`，
> 而且是**全部應用同時**發生，通常在深夜或連假。
> 正確做法：全域設 `0`，只對人用帳號個別設定
> `ALTER USER 'ops_alice'@'10.10.9.%' PASSWORD EXPIRE INTERVAL 90 DAY;`，
> 應用帳號明寫 `PASSWORD EXPIRE NEVER`，輪換靠變更管理排程做。
> 見「密碼政策與帳號鎖定」的 danger callout。
>
> **Q7. `REQUIRED` 只保證加密，`VERIFY_CA` 才會驗證伺服器憑證是不是你信任的 CA 簽的。★★★★**
> `REQUIRED` 的連線一定是 TLS，但**不檢查對方是誰** —— 中間人拿一張自簽憑證就能通過。
> `VERIFY_CA` 會用你給的 `--ssl-ca` 驗證憑證鏈，擋得住中間人；
> `VERIFY_IDENTITY` 再多驗一步主機名（比對 SAN），是目標狀態。
> ★★★ `VERIFY_CA` 以上都需要客戶端**實際拿到 CA 憑證檔**，所以 CA 憑證的派送是切換作業的前置工作。
> 見 `--ssl-mode` 那張對照表與 [[09-根憑證派送與信任]]。
>
> **Q8. 因為她的帳號有 `CONNECTION_ADMIN`（或舊的 `SUPER`）權限。★★★★**
> MySQL 的 `init_connect` **對持有 `CONNECTION_ADMIN` 的帳號不執行** ——
> 這個設計原本是為了避免管理員被壞掉的 `init_connect` 鎖在門外，
> 但副作用是**最需要被稽核的那些人剛好不會被記錄**。
> 補救方式：管理員的連線改從 error log（`log_error_verbosity=3`）與 SSH 登入紀錄比對，
> 或改用 Percona Audit Log Plugin 這類真正的稽核外掛。
> 這也是為什麼 `init_connect` 只能算「聊勝於無」的方案。見稽核那節的 danger callout。
>
> **Q9. 12 條明文連線不會被立刻切斷，但它們一旦重連就再也連不上。★★★★★**
> `require_secure_transport` 只在**建立新連線**時檢查，現有連線不受影響。
> 所以你當下看起來「什麼事都沒有」，直到連線池回收、PHP-FPM 重啟或深夜重連，
> 才會突然全站白畫面，error log 出現大量
> `Connections using insecure transport are prohibited while --require_secure_transport=ON`。
> 正確順序：先用「階段 0」的 `performance_schema` 查詢確認**沒有任何空白 `tls_ver` 的列**，
> 再開；而且先 `SET GLOBAL`（重啟即失效）觀察一個上班日，沒問題才 `SET PERSIST`。
> 出事時的止血：`sudo mysql -e "SET GLOBAL require_secure_transport=OFF"`（socket 永遠通得過）。
>
> **Q10. 誠實說明沒有對應基準，改用替代檢核並附證據。★★★★★**
> 絕對不要填一個查證不到的編號 —— 稽核一比對就是「陳述不實」，比留白嚴重得多。
> 建議回覆的寫法：
> 1. 說明 TWGCB 現行發布的基準以作業系統／瀏覽器／網路設備／部分應用軟體為主，
>    經查（附查詢日期與 GCB 網址）無對應 MySQL 之基準文件。
> 2. 改依 **CIS MySQL Benchmark**（或機關自訂檢核表）執行，附 `mysql-hardening-check.sh` 的
>    整改前後對照表當佐證。
> 3. 說明**資料庫主機的 OS 層仍完整套用 TWGCB**，並逐項對應帳號、日誌、檔案權限、
>    服務最小化、網路存取控制、強制存取控制六類。
> ★★★ 動筆前一定要自己上 <https://www.nccst.nat.gov.tw/GCB> 查一次現況，不要引用本篇的判斷當結論。
> 見「TWGCB 對應：誠實的說法」。

---

## 延伸閱讀

- [[02-MySQL-使用者與權限]] — 本篇只做盤點與收斂，帳號與角色的完整設計在那裡
- [[05-MySQL-備份與還原]] — 備份加密、保存期限與**還原演練**，本篇的第 5 層靠它落實
- [[04-備份災難復原與入侵應變]] — 資料庫被拖庫或勒索後的應變順序
- [[08-用自建CA簽發伺服器憑證]] — 本篇用到的資料庫憑證從哪來
- [[10-憑證部署到各服務]] — 同一張 CA 怎麼同時服務 Nginx、MySQL 與內部工具
- [[05-Wazuh-日誌蒐集與解析]] — 把 error log 與連線紀錄變成會告警的規則
- [[07-台灣資安法規與個資法]] — 個資盤點、通報時限與委外管理的法規面
- [[09-資安稽核與符合性檢核]] — 把本篇的健檢輸出組織成一份完整的符合性報告
- MySQL 8.0 Reference Manual — Security：<https://dev.mysql.com/doc/refman/8.0/en/security.html>
- MySQL 8.0 — Using Encrypted Connections：<https://dev.mysql.com/doc/refman/8.0/en/encrypted-connections.html>
- MySQL 8.0 — InnoDB Data-at-Rest Encryption：<https://dev.mysql.com/doc/refman/8.0/en/innodb-data-encryption.html>
- 政府組態基準（GCB）專區：<https://www.nccst.nat.gov.tw/GCB>
