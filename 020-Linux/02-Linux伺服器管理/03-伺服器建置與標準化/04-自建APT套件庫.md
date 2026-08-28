---
title: "自建 APT 套件庫"
desc: "把內部設定與根憑證打包成 deb，用 reprepro 建庫、GPG 簽章治理、內網分發與 aptly 版本凍結回退"
aliases: [reprepro, aptly, dpkg-deb, APT-Repository, 內部套件庫, deb打包]
tags: [群組/Linux, linux/伺服器, 主題/建置標準化]
category: 伺服器建置與標準化
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[03-第三方APT套件庫實務]]", "[[14-套件管理]]", "[[02-基準設定與範本化]]"]
updated: 2026-08-28
---

# 自建 APT 套件庫

> [!abstract] 這篇你會學到
> - 判斷**什麼時候值得自建套件庫、什麼時候不值得**（附成本比較，別為了三台機器蓋一座庫）
> - 用 `dpkg-deb` 把**機關根 CA 憑證**與**基準設定**打包成可 `apt install` 的 deb
> - ★★★★ 寫出**冪等**的 `postinst` / `postrm` —— 升級時舊套件的 `postrm` 會再跑一次，寫錯會把剛裝好的檔案刪掉
> - 用 **reprepro** 建立簽章庫、用 **Nginx** 發布、用 **deb822 + pinning** 讓幾十台機器自動接上
> - ★★★★★ 規劃**簽章私鑰的保管與輪替** —— 私鑰放錯地方等於把「推任意套件到全機關」的權限送人
> - 用 **aptly snapshot + publish switch** 做版本凍結，出事時**一行指令讓全機關回退**

## 前置知識

- [[03-第三方APT套件庫實務]] — 本篇是它的反面：那篇教你怎麼**安全地消費**別人的庫，這篇教你怎麼**當供應方**。`signed-by`、pinning 的基本語法與第三方庫的風險評估都在那篇，本篇不重複
- [[14-套件管理]] — `apt update` / `apt-cache policy` / dpkg 狀態機的日常操作
- [[02-基準設定與範本化]] — 本篇要打包的 `org-baseline-config` 就是那篇產出的基準設定
- [[06-自建根CA]] 與 [[09-根憑證派送與信任]] — 本篇只負責**把已經簽好的根憑證裝進 deb**，CA 的建立與簽發不在這裡
- [[08-檔案權限與擁有者]] — deb 內的檔案權限就是安裝後的權限，打包時錯了裝上去也錯
- 會寫基本的 POSIX shell（維護腳本用 `/bin/sh`，不是 bash）

> [!warning] 未實機驗證的部分
> 本篇的 `dpkg-deb`、`reprepro`、`gpg`、`apt` 流程依 Ubuntu 24.04 LTS（noble）撰寫。
> **aptly 的鏡像與 `publish switch` 段落僅依官方文件撰寫，未在本手冊環境完整跑過完整上游鏡像**
> （鏡像 Ubuntu 主庫需要數百 GB 磁碟）。實作前請對照 <https://www.aptly.info/doc/> 確認你安裝的版本。

---

## 觀念說明

### 一個 APT 套件庫其實只是「一堆檔案 + 一個簽章」

沒有 daemon、沒有資料庫服務、沒有 API。客戶端跑 `apt update` 時做的事情就這四步：

```text
                    ┌──────────────────────────────────────────┐
  客戶端 apt update │  ① GET /dists/noble/InRelease            │
                    │     └─ 內含各 Packages 檔的 SHA256       │
                    │     └─ ★★★★ 整份被 GPG clearsign 包住   │
                    │  ② 用 Signed-By 指定的公鑰驗簽           │
                    │     └─ 驗不過 → 整個庫直接不採用         │
                    │  ③ GET /dists/noble/main/binary-amd64/   │
                    │        Packages.gz  → 比對 SHA256        │
                    │  ④ apt install 時                        │
                    │     GET /pool/main/o/org-ca-.../*.deb    │
                    │     └─ 比對 Packages 裡的 SHA256         │
                    └──────────────────────────────────────────┘
                                      ↓
             整條信任鏈的根 = 你那把 GPG 私鑰
```

★★★★★ **推論很殘酷：誰拿到簽章私鑰，誰就能對全機關的每一台機器推送任意套件，而且每一台都會安靜地接受。**
套件庫的安全性 100% 押在私鑰保管上，跟你的 Nginx 設定多嚴格沒關係。這是本篇最重要的一句話。

### 目錄長什麼樣

```text
/srv/apt/
├── conf/                       ★★★★ 絕不可對外（含簽章設定）
│   ├── distributions           ← 定義 codename、元件、用哪把金鑰簽
│   └── options                 ← reprepro 預設參數
├── db/                         ★★★★ 絕不可對外（reprepro 的內部資料庫）
│   ├── checksums.db
│   ├── packages.db
│   └── references.db
├── dists/                      ← 對外，reprepro 自動產生
│   └── noble/
│       ├── InRelease           ← ★ clearsign（簽章與內容同一檔，現代 apt 用這個）
│       ├── Release             ← 純文字
│       ├── Release.gpg         ← 分離式簽章（舊 apt 用）
│       └── main/
│           └── binary-amd64/
│               ├── Packages
│               ├── Packages.gz
│               └── Release
└── pool/                       ← 對外，實際的 .deb 檔
    └── main/
        └── o/org-ca-certificates/
            └── org-ca-certificates_1.0.0_all.deb
```

`dists/` 是**索引**，`pool/` 是**貨**。所有 codename 共用同一個 pool，所以同一個 deb 同時掛在 noble 與 jammy 下不會存兩份。

### ★★★ 什麼時候值得自建

| 情境 | 值得？ | 為什麼 |
| --- | --- | --- |
| ★★★ **派送機關根 CA 憑證到 40 台機器**，以後憑證換了要能一次換掉 | **值得** | 有版本、有升級路徑、有移除路徑；新機器裝完基準設定就自動有憑證 |
| ★★★ **封閉網段 / 離線機房**，機器連不到 archive.ubuntu.com | **值得** | 內部庫是唯一的套件來源；順便鏡像上游 |
| ★★★★ **版本凍結**：要求 40 台機器在同一次維護窗口看到「完全相同的一組套件」 | **值得** | 用 aptly snapshot 才做得到可重現部署；否則今天裝跟明天裝的機器版本不同 |
| ★ 有三台機器，要放一支監控腳本 | **不值得** | `rsync` 或一個 Ansible playbook 五分鐘搞定，蓋庫的維護成本遠大於收益 |
| ★ 只是要讓大家裝某個開源工具的新版 | **不值得** | 上游多半已有官方 APT 庫，走 [[03-第三方APT套件庫實務]] 的流程評估後直接用 |

**成本比較（40 台機器、每季更新一次內部設定的機關情境）**：

| 做法 | 建置成本 | 每次更新成本 | 可回退 | 稽核軌跡 | 新機器自動吃到 |
| --- | --- | --- | --- | --- | --- |
| `scp` / `rsync` 手動派送 | 0 | ★★★ 高（要確認 40 台都成功） | ✗ 靠備份 | ✗ 靠人記 | ✗ |
| Ansible playbook | 中 | 低 | △ 重跑舊版 playbook | △ 看有沒有存 log | △ 要記得跑 |
| ★★★ **自建 APT 庫** | **高**（本篇全部內容） | **極低**（`repo-publish` 一次） | ✓ 版本號 + snapshot | ✓ `dpkg -l` + 庫的 log | ✓ `apt upgrade` 自動 |

> [!tip] 判斷準則：一句話
> **「這東西以後會不會需要『升級』與『移除』？」**
> 會 → 打包成 deb。只是丟一次就不管了 → 用 [[05-自動化佈建入門]] 的 Ansible 派送就好。
> 套件管理器的價值在於**狀態管理**（裝了什麼版本、誰依賴誰、移除要清什麼），不在於「傳檔案」。

### deb 套件解剖

一個 `.deb` 其實是 `ar` 歸檔，裡面固定三個成員：

```bash
ar t /var/cache/apt/archives/curl_8.5.0-2ubuntu10.6_amd64.deb
```

預期輸出：

```text
debian-binary          # ★ 內容只有 "2.0\n"，格式版本
control.tar.zst        # ★★★ 中繼資料 + 維護腳本（Ubuntu 24.04 用 zstd，Debian 多為 .xz）
data.tar.zst           # ★★★ 真正要裝到檔案系統的檔案，路徑從 / 起算
```

打包時你要準備的目錄長這樣 —— **`DEBIAN/` 以外的部分，就是安裝後檔案系統的樣子**：

```text
build/org-ca-certificates/
├── DEBIAN/                              ★ 大寫，會變成 control.tar
│   ├── control                          0644
│   ├── conffiles                        0644（可選）
│   ├── postinst                         ★★★★ 0755，不是 0755 dpkg 會拒裝
│   └── postrm                           ★★★★ 0755
└── usr/local/share/ca-certificates/     ← 完全照 FHS，裝完就在這個路徑
    └── org-root-ca.crt                  0644
```

★★★ **檔案佈局必須照 FHS**。把東西丟到 `/opt/mystuff/` 或 `/root/` 不是不行，但：
`update-ca-certificates` 只掃 `/usr/local/share/ca-certificates/`，放錯地方 postinst 再怎麼跑憑證都不會生效。
其他常見位置：可執行檔 `/usr/local/bin`（本地打包）或 `/usr/bin`（正式套件）、設定 `/etc/<pkg>/`、
systemd unit `/lib/systemd/system/`、文件 `/usr/share/doc/<pkg>/`。

### DEBIAN/control 各欄位的實際影響

| 欄位 | 必填 | 寫錯會怎樣 |
| --- | --- | --- |
| `Package` | ✓ | ★★★★ 這是**唯一識別碼**，改了等於變成另一個套件，舊的不會被取代 → 兩份憑證同時存在 |
| `Version` | ✓ | ★★★★ 決定升級方向，見下一節。比舊版小 → `apt upgrade` 完全不會動它 |
| `Architecture` | ✓ | `all` = 與架構無關（設定檔、憑證、腳本）；`amd64` = 只裝在 amd64。★★★ 寫 `amd64` 但 reprepro 的 `Architectures` 沒列 → 匯入被拒 |
| `Maintainer` | ✓ | 格式必須 `姓名 <email>`。★ 寫成純 email，lintian 會報 `maintainer-address-malformed`，但 dpkg 照裝 |
| `Description` | ✓ | 第一行是摘要，後續行**必須以一個空格縮排**。★★ 空的長描述會被 lintian 抓 `extended-description-is-empty` |
| `Depends` | | ★★★★ 真正的相依。`postinst` 裡呼叫 `update-ca-certificates` 就必須 `Depends: ca-certificates`，否則在最小化安裝的機器上 postinst 會失敗 → 套件卡在 `iF` 半安裝狀態 |
| `Pre-Depends` | | ★★★ 比 `Depends` 更早滿足（`preinst` 執行前）。非必要不要用 |
| `Section` / `Priority` | | 只影響分類顯示，`Section: admin`、`Priority: optional` 填了就對 |
| `Conflicts` / `Replaces` / `Provides` | | ★★★ 取代舊的自製套件時要成套寫，否則兩個套件搶同一個檔案，dpkg 直接報 `trying to overwrite` |
| `Installed-Size` | | 單位 KB，只給 apt 估算用。不填也能裝 |

### conffiles：升級時保留使用者修改的唯一機制

`DEBIAN/conffiles` 每行一個**絕對路徑**（Policy 規定只能是 `/etc` 底下的檔案）：

```text
/etc/org-baseline/sysctl-hardening.conf
/etc/org-baseline/journald.conf
```

宣告成 conffile 之後，升級時 dpkg 會比對三方雜湊（原始版、目前版、新版）：

| 使用者改過？ | 新版有變？ | dpkg 行為 |
| --- | --- | --- |
| 沒改 | 有變 | ★ 直接換成新版，不吭聲 |
| 改過 | 沒變 | ★ 保留使用者的版本 |
| 改過 | 有變 | ★★★ **互動詢問** keep / replace / diff；非互動時看 `--force-conf*`，預設保留舊的並留下 `.dpkg-dist` |

```bash
# 非互動升級時明確指定策略（★★★ 派送時一定要指定，不然可能卡住等輸入）
sudo apt-get -y -o Dpkg::Options::="--force-confold" \
                -o Dpkg::Options::="--force-confdef" upgrade
```

> [!danger] ★★★★ conffiles 必須在「第一版」就宣告
> 如果 v1.0.0 沒把 `/etc/org-baseline/x.conf` 列進 `conffiles`，v1.1.0 才補上，
> 那麼**升到 v1.1.0 的那一次，dpkg 會把使用者的修改直接覆蓋掉**（因為它沒有原始雜湊可比對）。
> 這不會有任何警告，你只會在事後收到「我改的設定不見了」的申告。
> **打包前先想清楚哪些檔案是使用者可以改的，一次列全。**

### ★★★★ 維護腳本的執行時機（背下這張表）

這是自製 deb 最常炸的地方。dpkg 呼叫的腳本與參數：

| 事件 | 執行順序 | 腳本與參數 |
| --- | --- | --- |
| **首次安裝** | 1 | `new-preinst install` |
| | 2 | 解開 data.tar |
| | 3 | ★ `new-postinst configure`（`$2` 為**空**） |
| **升級** | 1 | `old-prerm upgrade <新版本>` |
| | 2 | `new-preinst upgrade <舊版本>` |
| | 3 | 解開新的 data.tar（新檔案已經在磁碟上了） |
| | 4 | ★★★★★ **`old-postrm upgrade <新版本>`** ← 舊套件的 postrm！ |
| | 5 | dpkg 處理 conffiles |
| | 6 | `new-postinst configure <舊版本>`（`$2` = 舊版號） |
| **移除** | 1 | `prerm remove` |
| | 2 | 刪除檔案（**conffiles 保留**） |
| | 3 | `postrm remove` |
| **清除 purge** | 1 | `postrm purge`（刪 conffiles 與殘留狀態） |

> [!danger] ★★★★★ 升級第 4 步是最容易炸的地方
> 升級時，**舊套件的 `postrm` 會以 `upgrade` 參數被呼叫，而且是在新檔案已經解開之後**。
> 如果你的 `postrm` 這樣寫：
>
> ```sh
> #!/bin/sh
> rm -f /usr/local/share/ca-certificates/org-root-ca.crt   # ❌ 沒有 case 判斷
> update-ca-certificates --fresh
> ```
>
> 那麼從 v1.0.0 升到 v1.1.0 時，**它會把 v1.1.0 剛解開的新憑證刪掉**，
> 然後 `postinst configure` 再去跑 `update-ca-certificates`，結果是
> **全機關的根憑證信任在一次「例行升級」後集體消失** ——
> 內部 HTTPS 服務、`curl`、`git clone`、Java 應用全部開始噴憑證錯誤。
>
> **正確寫法一定要 `case "$1" in` 分流**，見下方「基礎設定」段的完整範例。

**冪等（idempotent）的意思**：同一支腳本被跑第二次、第三次，結果必須跟跑第一次一樣。
除了升級會重跑之外，`dpkg --configure -a`、`apt --fix-broken install` 都會再跑一次 `postinst`。

```sh
mkdir /etc/org-baseline                     # ❌ 第二次跑會失敗（File exists）→ postinst 非 0 → 套件半安裝
mkdir -p /etc/org-baseline                  # ✅ 冪等
echo "x" >> /etc/sysctl.conf                # ❌ 每跑一次多一行
grep -q '^x$' /etc/sysctl.conf || echo "x" >> /etc/sysctl.conf   # ✅ 冪等
useradd svcuser                             # ❌ 第二次 exit 9
getent passwd svcuser >/dev/null || useradd -r -s /usr/sbin/nologin svcuser   # ✅
```

### ★★★ 版本號規則與陷阱

完整格式：`[epoch:]upstream_version[-debian_revision]`

```text
        1.2.3-1~noble1
        │     │ │
        │     │ └── 發行版後綴：★★★ 「~」排序小於「什麼都沒有」
        │     │      → 1.2.3-1~noble1  <  1.2.3-1  <  1.2.3-1ubuntu1
        │     │      這正是 backport 的慣例：讓官方版本永遠贏過你的移植版
        │     └──── Debian revision：上游沒變、只有打包改了就 +1
        └────────── upstream version：套件本身的版本
```

**自製內部套件的建議規則**：

| 用途 | 建議版本號 | 理由 |
| --- | --- | --- |
| ★★★ 純內部套件（`org-*`） | `1.0.0` → `1.1.0`（**不加 revision**） | 沒有「上游」，加 `-1` 只是徒增困擾 |
| ★★★ 重新打包上游套件 | `1.2.3-1org1` | 排序 > 官方 `1.2.3-1`，官方出 `-2` 時又會贏回來 |
| ★★★ 移植新版到舊發行版 | `1.2.3-1~noble1` | 排序 < 官方，官方一有正式版就自動接手 |
| ★ 每日建置 | `1.0.0+git20260828.a1b2c3d` | `+` 排序大於空字串，比 `~` 安全 |

**用 `dpkg --compare-versions` 驗證，不要用直覺**：

```bash
for pair in "1.2.3-1~noble1 1.2.3-1" "1.2.3-1 1.2.3-1ubuntu1" "1.10 1.9" "1.0.0+git1 1.0.0"; do
  set -- $pair
  if dpkg --compare-versions "$1" lt "$2"; then echo "$1  <  $2"; else echo "$1  >=  $2"; fi
done
```

預期輸出：

```text
1.2.3-1~noble1  <  1.2.3-1
1.2.3-1  <  1.2.3-1ubuntu1
1.10  >=  1.9              # ★★★ 1.10 > 1.9，版本號不是小數！
1.0.0+git1  >=  1.0.0
```

> [!danger] ★★★★ epoch 加上去就拿不掉
> `Version: 1:1.0.0` 裡的 `1:` 是 epoch。它的排序**壓過所有沒有 epoch 的版本**：
> `1:0.1` > `99.0`。
>
> 它只有一個正當用途：**上游改了版本號命名規則導致新版排序反而變小**
> （例如上游從 `20260101` 改成 `2.0`）。
>
> **加上之後就永遠拿不掉**，因為 `1:2.0` → `2.0` 在 dpkg 眼中是**降版**，
> `apt upgrade` 不會執行，你得跑遍每一台機器手動 `apt install --allow-downgrades`。
> epoch 也不會出現在 `.deb` 檔名裡（`dpkg-name` 會把 `:` 編碼成 `%3a`），
> 光看檔案根本看不出來，排查時很容易漏掉。
>
> **結論：一開始就把版本號規則想清楚，不要用 epoch 補救。**

---

## 環境準備與安裝

### 主機規劃：★★★★★ 兩台，不是一台

```text
 ┌────────────────────────────┐        ┌──────────────────────────────┐
 │  簽章／建置機 build01      │        │  發布機 apt.example.gov.tw   │
 │  ★★★★★ 不對外開任何服務   │ rsync  │  ★ 只跑 Nginx，只有靜態檔    │
 │  ─────────────────────     │ ─────▶ │  ────────────────────────    │
 │  GPG 私鑰（passphrase）    │  單向   │  /srv/apt/dists/             │
 │  reprepro conf/ db/        │        │  /srv/apt/pool/              │
 │  dpkg-deb 打包             │        │  ★★★★ 沒有私鑰、沒有 db/    │
 └────────────────────────────┘        └──────────────────────────────┘
                                                    │ HTTPS
                                        ┌───────────┴───────────┐
                                        ▼                       ▼
                                   40 台受管機器           新機建置流程
```

★★★★★ **簽章私鑰絕對不能放在對外提供服務的那台機器上。**
發布機是唯一暴露在網路上的元件，一旦被打下來，攻擊者拿到私鑰就能簽出任意套件推給全機關 ——
而且每一台客戶端都會驗簽通過、安靜地安裝，`apt` 不會有任何警告。
把 reprepro 跑在只有維運人員能登入的建置機上，用 `rsync` 單向推出去，成本幾乎是零，卻消掉最大的風險。

**資源估算**：

| 用途 | CPU / RAM | 磁碟 | 備註 |
| --- | --- | --- | --- |
| ★ 只放內部套件（十幾個 deb） | 1 vCPU / 1 GB | 20 GB | reprepro 幾乎不吃資源 |
| ★★★ 加上鏡像上游（`-filter` 限定必要套件） | 2 vCPU / 4 GB | 100~300 GB | 看 filter 範圍 |
| ★★★★ 完整鏡像 noble main+universe amd64 | 4 vCPU / 8 GB | **1.5 TB 以上** | 每保留一份 snapshot 只多存差異，但仍需大量空間 |

### 安裝

```bash
sudo apt update
sudo apt install -y reprepro dpkg-dev lintian gnupg2 rsync
reprepro --version
```

預期輸出：

```text
reprepro: This is reprepro version 5.3.1.        # ★ Ubuntu 24.04 noble 的版本
```

需要鏡像上游或做版本凍結時再裝 aptly（在 universe 元件）：

```bash
sudo apt install -y aptly
aptly version
```

預期輸出：

```text
aptly version: 1.5.0            # ★ 版本依你的發行版而異，功能以 aptly help 為準
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> RPM 世界的對應物件完全不同，但概念一模一樣：
>
> | APT 世界 | RPM 世界 |
> | --- | --- |
> | `dpkg-deb --build` | `rpmbuild -bb xxx.spec` |
> | `DEBIAN/control` | `.spec` 檔的 `Name/Version/Release/Requires` |
> | `postinst` / `postrm` | `%post` / `%postun`（★★★ 參數是 `$1` = 安裝後剩幾份，升級時 `%postun` 收到 `1`） |
> | `conffiles` | `%config(noreplace)` |
> | reprepro / aptly | `createrepo_c` |
> | `InRelease` GPG 簽章 | `repomd.xml.asc` + `rpm --addsign` **逐一簽每個 rpm** |
> | `/etc/apt/sources.list.d/*.sources` | `/etc/yum.repos.d/*.repo` |
>
> ```bash
> sudo dnf install -y createrepo_c rpm-sign rpmdevtools
> rpmdev-setuptree
>
> # 建庫
> sudo mkdir -p /srv/yum/el9/x86_64
> sudo cp *.rpm /srv/yum/el9/x86_64/
> sudo createrepo_c /srv/yum/el9/x86_64/
>
> # ★★★★ RPM 是「簽每一個套件」，不是只簽索引 —— 私鑰治理的要求一樣嚴格
> rpm --define "_gpg_name apt-signing@example.gov.tw" --addsign /srv/yum/el9/x86_64/*.rpm
> gpg --detach-sign --armor /srv/yum/el9/x86_64/repodata/repomd.xml
>
> # 客戶端
> sudo rpm --import https://apt.example.gov.tw/org-archive-keyring.asc
> ```
>
> ★★★ RHEL 系的 `gpgcheck=1` 與 `repo_gpgcheck=1` 是**兩件事**：前者驗每個 rpm，後者驗索引，
> 兩個都要開才等於 APT 的預設安全等級。

### ★★★★★ 產生簽章金鑰（在簽章機上做）

```bash
# ★★★★ 用專屬的 GNUPGHOME，不要跟個人金鑰混在一起
export GNUPGHOME=/root/.gnupg-aptsign
sudo install -d -m 0700 "$GNUPGHOME"

cat > /tmp/keyparams <<'EOF'
Key-Type: RSA
Key-Length: 4096
Key-Usage: sign
Name-Real: Example Gov Internal APT Archive
Name-Email: apt-signing@example.gov.tw
Name-Comment: internal use only
Expire-Date: 2y
%ask-passphrase
%commit
EOF

sudo GNUPGHOME="$GNUPGHOME" gpg --batch --full-generate-key /tmp/keyparams
shred -u /tmp/keyparams
```

預期輸出：

```text
gpg: key A1B2C3D4E5F60718 marked as ultimately trusted
gpg: revocation certificate stored as
     '/root/.gnupg-aptsign/openpgp-revocs.d/9F8E7D6C5B4A392817260514A1B2C3D4E5F60718.rev'
```

★★★ **設計說明**：

| 決定 | 選擇 | 理由 |
| --- | --- | --- |
| 用途 | ★★★★ `Key-Usage: sign` 只有簽章 | 套件庫不需要加密子鑰，少一個攻擊面 |
| 長度 | RSA 4096 | 相容性最好；ed25519 更快但極舊的 apt 不支援 |
| 有效期 | ★★★ **2 年**，不要 `0`（永不過期） | 有效期是逼你定期輪替的鬧鐘。過期的金鑰仍可**驗證**已有簽章，但不能簽新的 |
| passphrase | ★★★★ **一定要設**，存在密碼保管系統 | 私鑰檔被複製走時，多一層阻擋 |

**匯出公鑰與備份私鑰**：

```bash
FPR=$(sudo GNUPGHOME=/root/.gnupg-aptsign gpg --list-keys --with-colons \
        apt-signing@example.gov.tw | awk -F: '/^fpr:/{print $10; exit}')
echo "$FPR"
```

預期輸出：

```text
9F8E7D6C5B4A392817260514A1B2C3D4E5F60718
```

```bash
# ① 公鑰（ASCII armored，要發給每一台客戶端）
sudo GNUPGHOME=/root/.gnupg-aptsign gpg --armor --export "$FPR" \
     | sudo tee /srv/apt/org-archive-keyring.asc >/dev/null

# ② ★★★★★ 私鑰備份 → 加密後放離線媒體（保險箱／離線隨身碟），不要放在任何連網主機
sudo GNUPGHOME=/root/.gnupg-aptsign gpg --armor --export-secret-keys "$FPR" \
     > /root/apt-signing-private.asc
gpg --symmetric --cipher-algo AES256 /root/apt-signing-private.asc
shred -u /root/apt-signing-private.asc
# → /root/apt-signing-private.asc.gpg 複製到離線媒體後，也要 shred 掉本機這份

# ③ ★★★★ 撤銷憑證：GnuPG 2.1+ 已自動產生，一併離線保存
sudo cp /root/.gnupg-aptsign/openpgp-revocs.d/"$FPR".rev /mnt/offline-usb/
```

> [!danger] ★★★★★ 撤銷憑證要「事先」產生並離線保存
> 撤銷憑證的用途是：**私鑰外洩、或私鑰遺失時，昭告所有人這把金鑰作廢**。
> 弔詭的是產生撤銷憑證需要私鑰 —— 所以**私鑰遺失之後就再也產不出來了**。
> GnuPG 2.1 以後會在建金鑰時自動放一份在 `openpgp-revocs.d/`，
> **你要做的是把它跟私鑰備份分開存到離線媒體**，並記進機關的金鑰清冊。
> 沒有撤銷憑證，一旦出事你只能靠「逐台改設定」來止血，40 台機器就是 40 次人工作業。

### reprepro 與 aptly 選型

| 面向 | **reprepro** | **aptly** |
| --- | --- | --- |
| 每個套件保留版本數 | ★★★ **只有一個**（最新） | 多個，且可任意組合成 snapshot |
| 設定複雜度 | 低（一個 `conf/distributions`） | 中（CLI 狀態機，要理解 repo/mirror/snapshot/publish 四層） |
| 鏡像上游 | △ 有 `Update` 機制但難用 | ★★★★ **強項**，`mirror` + `-filter` |
| 版本凍結 / 快照 | ✗ | ★★★★★ **`snapshot` + `publish switch`** |
| 回退 | ★★★ 要 `remove` 後重新 `includedeb` 舊 deb | ★★★★★ 一行 `publish switch` 切回舊快照 |
| 磁碟用量 | 小 | 大（保留多版本） |
| 適合 | **自己打包的內部套件** | **上游鏡像、離線環境、版本凍結** |

> [!tip] ★★★ 明確建議：兩個都用，各司其職
> - **內部套件（`org-*`）→ reprepro**：設定五行、行為好預測，你本來就只需要最新版
> - **上游鏡像與版本凍結 → aptly**：snapshot 是「可重現部署」唯一實用的做法
>
> 客戶端上兩個庫並存完全沒問題，`/etc/apt/sources.list.d/` 放兩個 `.sources` 檔即可。

---

## 基礎設定：打包與建庫

### 打包第一個內部套件：org-ca-certificates

目標：把機關根 CA 憑證裝到 `/usr/local/share/ca-certificates/`，安裝時自動信任、移除時自動撤銷信任。

```bash
export PKG=org-ca-certificates VER=1.0.0
export BUILD="$HOME/build/${PKG}_${VER}"

mkdir -p "$BUILD/DEBIAN" "$BUILD/usr/local/share/ca-certificates" \
         "$BUILD/usr/share/doc/$PKG"

# 放入根憑證（來自 [[06-自建根CA]] 的產出）
cp /srv/pki/org-root-ca.crt "$BUILD/usr/local/share/ca-certificates/org-root-ca.crt"
```

> [!danger] ★★★★ 副檔名一定要是 `.crt`，內容一定要是 PEM
> `update-ca-certificates` 只處理 `/usr/local/share/ca-certificates/` 底下**副檔名為 `.crt`**、
> 且**內容是 PEM 格式**的檔案。放 `.pem`、`.cer` 或 DER 二進位檔會被**安靜地忽略** ——
> 套件裝得成功、`postinst` 也回傳 0，但憑證根本沒生效，你要到別人回報
> `curl: (60) SSL certificate problem` 才會發現。
>
> ```bash
> # ★★★ 打包前先驗，一秒的事
> openssl x509 -in /srv/pki/org-root-ca.crt -noout -subject -dates
> # 看得到 subject= ... 就是 PEM；報 "unable to load certificate" 就是 DER，要先轉：
> # openssl x509 -inform DER -in x.cer -out org-root-ca.crt
> ```

**DEBIAN/control**：

```bash
cat > "$BUILD/DEBIAN/control" <<EOF
Package: $PKG
Version: $VER
Section: admin
Priority: optional
Architecture: all
Depends: ca-certificates, openssl
Maintainer: 資訊室套件維護 <it-pkg@example.gov.tw>
Homepage: https://apt.example.gov.tw/
Description: Example Gov 機關根 CA 憑證
 安裝本機關自簽根 CA 憑證到系統信任存放區，
 讓 curl、git、wget、OpenSSL 應用可以驗證內部 HTTPS 服務。
 .
 憑證安裝於 /usr/local/share/ca-certificates/org-root-ca.crt，
 由 update-ca-certificates 併入 /etc/ssl/certs/ca-certificates.crt。
EOF
```

★★★ 三個容易錯的細節：
`Architecture: all`（憑證跟 CPU 架構無關）；
`Depends: ca-certificates`（postinst 要用 `update-ca-certificates`，不宣告就會在最小化安裝的機器上失敗）；
Description 續行**每行開頭一個空格**，段落之間用單獨一行 ` .`（空格加點）。

**DEBIAN/postinst** — ★★★★ 冪等 + `case` 分流：

```bash
cat > "$BUILD/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e

case "$1" in
    configure)
        # ★★★★ 冪等：不論首次安裝、升級、還是 dpkg --configure -a 重跑，結果都一樣
        if command -v update-ca-certificates >/dev/null 2>&1; then
            update-ca-certificates >/dev/null
        else
            echo "org-ca-certificates: 找不到 update-ca-certificates，憑證未生效" >&2
            exit 1                                    # ★★★ 該失敗就失敗，不要靜默略過
        fi

        # ★★ 自我驗證：確認憑證真的進了信任存放區
        if ! openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt \
             /usr/local/share/ca-certificates/org-root-ca.crt >/dev/null 2>&1; then
            echo "org-ca-certificates: 警告 —— 憑證未出現在 ca-certificates.crt" >&2
        fi

        # $2 有值代表這是升級（$2 = 舊版本號），首次安裝時為空
        if [ -n "${2:-}" ]; then
            logger -t org-ca-certificates "已從 $2 升級"
        fi
        ;;

    abort-upgrade|abort-remove|abort-deconfigure)
        # ★★★ 回滾情境，什麼都不做但必須成功結束
        ;;

    *)
        echo "postinst 收到未知參數 '$1'" >&2
        exit 1
        ;;
esac

exit 0
EOF
chmod 0755 "$BUILD/DEBIAN/postinst"          # ★★★★ 不是 0755 → dpkg 報 unable to execute
```

**DEBIAN/postrm** — ★★★★★ 這支寫錯會刪掉剛裝好的新憑證：

```bash
cat > "$BUILD/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e

case "$1" in
    remove|purge)
        # ★★★★ 只有真的在移除時才刪
        rm -f /usr/local/share/ca-certificates/org-root-ca.crt
        if command -v update-ca-certificates >/dev/null 2>&1; then
            # --fresh 會重建整個 ca-certificates.crt，把已刪除的憑證清掉
            update-ca-certificates --fresh >/dev/null 2>&1 || true
        fi
        ;;

    upgrade|failed-upgrade|abort-install|abort-upgrade|disappear)
        # ★★★★★ 升級時「舊版的 postrm」會以 upgrade 被呼叫，
        #        而且此時「新版的檔案已經解開在磁碟上了」。
        #        這裡若去 rm 憑證，等於把新裝好的憑證刪掉 → 全機關信任鏈斷裂。
        #        什麼都不要做。
        ;;

    *)
        echo "postrm 收到未知參數 '$1'" >&2
        exit 1
        ;;
esac

exit 0
EOF
chmod 0755 "$BUILD/DEBIAN/postrm"
```

**建置與檢查**：

```bash
# ★★★ --root-owner-group：把所有檔案的擁有者設為 root:root
#     不加的話，deb 內會記錄你目前的 uid/gid（例如 1000:1000），
#     裝到別台機器上檔案就變成某個不相干使用者所有
dpkg-deb --root-owner-group --build "$BUILD" "$HOME/build/"
```

預期輸出：

```text
dpkg-deb: building package 'org-ca-certificates' in '/root/build/org-ca-certificates_1.0.0_all.deb'.
```

```bash
DEB="$HOME/build/${PKG}_${VER}_all.deb"

# 看 control（★ 先確認版本與相依）
dpkg-deb -I "$DEB"
```

預期輸出：

```text
 new Debian package, version 2.0.
 size 4826 bytes: control archive=612 bytes.
     499 bytes,    13 lines      control
     712 bytes,    28 lines   *  postinst             #!/bin/sh
     628 bytes,    24 lines   *  postrm               #!/bin/sh
 Package: org-ca-certificates
 Version: 1.0.0
 Architecture: all
 Depends: ca-certificates, openssl
 ...
```

★★★ `postinst` / `postrm` 前面的 `*` 代表可執行位元有設好。**沒有 `*` 就是 chmod 忘了。**

```bash
# 看內容（★★★★ 確認路徑與權限，這就是裝上去的樣子）
dpkg-deb -c "$DEB"
```

預期輸出：

```text
drwxr-xr-x root/root         0 2026-08-28 10:12 ./usr/
drwxr-xr-x root/root         0 2026-08-28 10:12 ./usr/local/share/ca-certificates/
-rw-r--r-- root/root      1428 2026-08-28 10:12 ./usr/local/share/ca-certificates/org-root-ca.crt
```

★★★★ 看 `root/root`。若出現 `1000/1000`，就是漏了 `--root-owner-group`，**重新打包**。

```bash
lintian -i --no-tag-display-limit "$DEB" || true
```

預期輸出（內部套件常見、可接受的 tag）：

```text
W: org-ca-certificates: no-copyright-file
W: org-ca-certificates: no-changelog usr/share/doc/org-ca-certificates/changelog.gz
E: org-ca-certificates: wrong-file-owner-uid-or-gid ... 1000/1000     # ★★★★ 這個一定要修
```

> [!tip] ★★ 內部套件不必追求 lintian 零警告
> `no-copyright-file`、`no-changelog`、`binary-without-manpage` 這類是給**要進 Debian 官方庫**的
> 套件用的標準，內部套件可以接受。但 **`E:`（error）級別一定要清乾淨**，
> 尤其 `wrong-file-owner-uid-or-gid`、`control-file-has-bad-permissions`、
> `maintainer-script-lacks-debhelper-token` 之外的執行權限問題。
> 建議在發布腳本裡用 `lintian --fail-on error` 當作閘門。

**安裝驗證（先在測試機上做）**：

```bash
sudo dpkg -i "$DEB"
```

預期輸出：

```text
Selecting previously unselected package org-ca-certificates.
Preparing to unpack .../org-ca-certificates_1.0.0_all.deb ...
Unpacking org-ca-certificates (1.0.0) ...
Setting up org-ca-certificates (1.0.0) ...
Updating certificates in /etc/ssl/certs...
1 added, 0 removed; done.                      # ★★★ 看到 "1 added" 才算成功
Running hooks in /etc/ca-certificates/update.d...
done.
```

```bash
# ★★★★ 真正的驗證不是 dpkg -l，是「憑證有沒有實際生效」
openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt \
  /usr/local/share/ca-certificates/org-root-ca.crt
```

預期輸出：

```text
/usr/local/share/ca-certificates/org-root-ca.crt: OK
```

```bash
# 拿一個用內部 CA 簽的服務端點實測（★ 這才是使用者真正在意的）
curl -sS -o /dev/null -w '%{http_code} %{ssl_verify_result}\n' https://intra.example.gov.tw/
```

預期輸出：

```text
200 0                     # ★ ssl_verify_result 為 0 才代表驗證通過
```

### 建立 reprepro 套件庫

```bash
sudo install -d -m 0755 /srv/apt
sudo install -d -m 0700 /srv/apt/conf /srv/apt/db      # ★★★★ 0700，這兩個目錄絕不可對外
```

**conf/distributions**：

```bash
sudo tee /srv/apt/conf/distributions >/dev/null <<EOF
Origin: ExampleGov
Label: Example Gov Internal
Codename: noble
Suite: stable
Version: 24.04
Architectures: amd64 arm64 all source
Components: main restricted
UDebComponents: main
Description: Example Gov 內部套件庫（Ubuntu 24.04 noble）
SignWith: $FPR
ValidFor: 14d
Contents: . .gz
EOF
```

| 欄位 | 作用 | ★ 踩雷點 |
| --- | --- | --- |
| `Origin` | 顯示名稱，**也是 apt pinning 的 `origin` 依據** | ★★★ 改了 Origin，客戶端 `apt update` 會報 `changed its 'Origin' value`，必須手動確認才繼續 |
| `Label` | 純顯示 | ★ 同上，改了會觸發確認 |
| `Codename` | 客戶端 `Suites:` 要填的值 | ★★★★ 客戶端寫 `Suites: stable` 但這裡 `Codename: noble` → apt 報 `Conflicting distribution` |
| `Suite` | 別名（`stable`、`testing`） | ★★ 可省略；填了就等於多一個可用名稱 |
| `Architectures` | 允許匯入的架構 | ★★★★ **一定要含 `all`**，否則 `Architecture: all` 的套件匯入被拒 |
| `Components` | 元件（`main`、`restricted`…） | ★★★ 客戶端 `Components:` 要對得上，寫錯只會安靜地什麼都抓不到 |
| `SignWith` | 簽章金鑰指紋 | ★★★★★ 有這行才會產生 `InRelease`；沒有的話客戶端要 `[trusted=yes]`（**等於關掉驗簽，禁止**） |
| `ValidFor` | `Release` 的 `Valid-Until` 距今多久 | ★★★★ 設了就必須定期 `reprepro export`，否則客戶端會報 `Release file has expired`；離線庫可省略 |
| `Contents` | 產生 `Contents-*.gz`（`apt-file` 用） | ★ 內部庫可省 |

**conf/options**：

```bash
sudo tee /srv/apt/conf/options >/dev/null <<'EOF'
basedir /srv/apt
verbose
ask-passphrase
EOF
```

★★★ `ask-passphrase` 會在簽章時提示輸入 passphrase。要在腳本裡自動化，就在建置機上設定
`gpg-agent` 的快取時間（`~/.gnupg/gpg-agent.conf` 的 `default-cache-ttl`），
**不要把 passphrase 寫進腳本或環境變數**。

**匯入套件**：

```bash
sudo reprepro -b /srv/apt includedeb noble "$DEB"
```

預期輸出：

```text
Exporting indices...
```

（reprepro 成功時**話很少**。沒有輸出通常就是成功了。）

```bash
sudo reprepro -b /srv/apt list noble
```

預期輸出：

```text
noble|main|amd64: org-ca-certificates 1.0.0
noble|main|arm64: org-ca-certificates 1.0.0
```

★★★ `Architecture: all` 的套件會出現在**每個**架構的清單裡，這是正常的。

```bash
# 驗證 InRelease 真的被簽了（★★★★ 這是客戶端能不能用的唯一判準）
gpg --verify /srv/apt/dists/noble/InRelease
```

預期輸出：

```text
gpg: Signature made Fri 28 Aug 2026 10:31:07 AM CST
gpg:                using RSA key 9F8E7D6C5B4A392817260514A1B2C3D4E5F60718
gpg: Good signature from "Example Gov Internal APT Archive ..." [ultimate]
```

**其他日常指令**：

```bash
# 移除某個套件（★★★ reprepro 只會從索引移除，pool 裡的檔案要另外清）
sudo reprepro -b /srv/apt remove noble org-ca-certificates

# ★★★ 清掉 pool 中已無人引用的檔案（磁碟回收的關鍵）
sudo reprepro -b /srv/apt deleteunreferenced

# 一致性檢查（索引與 pool 是否對得上）
sudo reprepro -b /srv/apt check
sudo reprepro -b /srv/apt checkpool

# 手動重新產生並簽章索引（★★★★ ValidFor 快到期時要跑這個）
sudo reprepro -b /srv/apt export noble

# 條件查詢
sudo reprepro -b /srv/apt listfilter noble 'Package (== org-ca-certificates)'
```

> [!warning] ★★★ reprepro 每個 codename 只保留一個版本
> `includedeb` 匯入 v1.1.0 之後，**v1.0.0 就從索引消失了**（pool 裡的檔案要 `deleteunreferenced` 才真的刪）。
> 這代表：
> - 你不能同時提供新舊版讓客戶端選 → 客戶端無法用 `apt install pkg=1.0.0` 降版
> - **回退的做法是「重新 `includedeb` 舊版的 deb 檔」**，所以**每個發布過的 deb 都要留檔**
> - 需要保留多版本或做真正的快照回退，就用 aptly（見下一節）

---

## 進階設定與調校

### 用 Nginx 發布（關鍵片段）

完整的 Nginx 設定語法見 [[02-Nginx-設定語法與虛擬主機]] 與 [[06-Nginx-HTTPS與Certbot]]，
這裡只給套件庫**特有**的四個決定：

```nginx
server {
    listen 443 ssl;
    http2 on;
    server_name apt.example.gov.tw;
    root /srv/apt;

    ssl_certificate     /etc/ssl/certs/apt.example.gov.tw.fullchain.pem;
    ssl_certificate_key /etc/ssl/private/apt.example.gov.tw.key;

    # ★★★★★ ① 絕不可對外的目錄 —— conf/ 洩漏簽章設定，db/ 是內部資料庫
    location ~ ^/(conf|db|incoming|logs|tmp)/ {
        deny all;
        return 404;                       # ★ 回 404 不回 403，不告訴掃描者這裡有東西
    }

    # ★★ ② autoindex：apt 本身不需要目錄列表（它靠 Release/Packages 找檔案）
    #    開著方便人工排查，代價是把整個內部套件清單攤在瀏覽器上
    #    → 內網且已做存取控制：可以開；跨機關或有 DMZ：關掉
    autoindex off;

    # ★★★ ③ 索引檔不可快取，deb 檔可以長快取（★ 因為檔名含版本，內容永不改變）
    location ~ ^/dists/ {
        add_header Cache-Control "no-cache, must-revalidate" always;
    }
    location ~ ^/pool/.*\.deb$ {
        add_header Cache-Control "public, max-age=31536000, immutable" always;
    }

    # ★★★★ ④ 存取控制：內網 IP 白名單（最簡單、最不會出錯）
    allow 10.20.0.0/16;
    allow 10.30.0.0/16;
    deny  all;

    access_log /var/log/nginx/apt.access.log;
}

# ★★★ HTTP 一律轉 HTTPS
server {
    listen 80;
    server_name apt.example.gov.tw;
    return 301 https://$host$request_uri;
}
```

> [!tip] ★★★ HTTPS 對套件庫其實不是為了防竄改
> 套件的完整性已經由 **GPG 簽章**保證了 —— 就算走 HTTP 被中間人改了 deb，客戶端驗簽也會失敗。
> HTTPS 的價值在於：
> - **保密性**：不讓路徑上的人看到你裝了哪些套件（可以推斷出你跑什麼服務、什麼版本 → 攻擊面情報）
> - **可用性**：擋掉透明代理／快取設備亂快取索引造成的 `Hash Sum mismatch`
> - **稽核要求**：TWGCB 與多數機關資安規範要求內部服務一律 TLS
>
> ★★★★ **但反過來絕對不成立：有 HTTPS 不代表可以省掉 GPG 簽章。**
> 千萬不要為了省事在客戶端寫 `[trusted=yes]`，那等於整條信任鏈只剩「Nginx 沒被入侵」這一個假設。

**若要用帳密而非 IP 限制**（例如機器散布在多個網段）：

```nginx
    auth_basic           "Example Gov APT";
    auth_basic_user_file /etc/nginx/apt.htpasswd;
```

客戶端則寫在 `/etc/apt/auth.conf.d/`（**不要**把帳密寫在 URL 裡）：

```bash
sudo install -d -m 0700 /etc/apt/auth.conf.d
sudo tee /etc/apt/auth.conf.d/org-apt.conf >/dev/null <<'EOF'
machine apt.example.gov.tw
login apt-client
password 你的密碼
EOF
sudo chmod 0600 /etc/apt/auth.conf.d/org-apt.conf      # ★★★★ 必須 600
sudo chown root:root /etc/apt/auth.conf.d/org-apt.conf
```

> [!danger] ★★★★ `/etc/apt/auth.conf.d/*` 權限必須 0600 root:root
> 這個檔案是**明文密碼**。預設 `umask 022` 建立出來的是 0644 ——
> **機器上任何一個本機使用者、任何一個以非 root 身分執行的網頁應用（`www-data`）都讀得到**。
> 一旦外洩，攻擊者就能下載你的全部內部套件（含基準設定，等於拿到你的安全組態藍圖）。
>
> ```bash
> # ★★★ 定期稽核（可放進巡檢腳本）
> find /etc/apt/auth.conf.d -type f ! -perm 600 -printf '%m %u:%g %p\n'
> # 有輸出就是有問題，應為空
> ```
>
> 相關：把這個檔案放進 `org-baseline-config` 這種**會發給所有人**的套件是嚴重錯誤 ——
> 帳密會隨著 deb 散布到每一台機器，而且留在 `/var/cache/apt/archives/` 裡。

### 客戶端接入的標準做法

★★★ 這一步**應該寫進 [[01-新機建置標準流程]] 的基準設定**，不要靠人工加。
`signed-by` 與 pinning 的完整語法與風險說明在 [[03-第三方APT套件庫實務]]，這裡只講內部庫的差異。

`/etc/apt/sources.list.d/org-internal.sources`（deb822，內嵌金鑰）：

```text
X-Repolib-Name: Example Gov Internal
Types: deb
URIs: https://apt.example.gov.tw/
Suites: noble
Components: main restricted
Architectures: amd64
Signed-By:
 -----BEGIN PGP PUBLIC KEY BLOCK-----
 .
 mQINBGjR8VwBEADQ7f2K9pXhV3mYc8sN1oJqB4uL6wT0aZ9dR5eF7gH2iK3lM4nP
 5qS6tU7vW8xY9zA0bC1dE2fG3hI4jK5lM6nO7pQ8rS9tU0vW1xY2zA3bC4dE5fG6
 -----END PGP PUBLIC KEY BLOCK-----
```

★★★ 兩個格式細節（寫錯 apt 會安靜地當成沒設定）：
**金鑰每一行前面要有一個空格**；金鑰區塊內的**空行要寫成一個空格加一個點 ` .`**。

> [!tip] ★★ 內嵌金鑰 vs 獨立 keyring 檔
> - **內嵌**：一個檔案就是全部，適合用 Ansible 或 cloud-init 派送。缺點是換金鑰要重寫這個檔
> - **獨立**（`Signed-By: /etc/apt/keyrings/org-apt.asc`）：金鑰輪替時只換 keyring 檔，`.sources` 不動
>
> ★★★ **要做金鑰輪替就選獨立 keyring**，因為輪替期需要「新舊金鑰並存」，
> 獨立檔案可以直接放兩把公鑰（apt 支援一個 keyring 內含多把金鑰），內嵌則要小心處理格式。
> 本篇的實戰範例走內嵌（步驟少），輪替流程則以獨立 keyring 說明。

**★★★ 內部庫是少數應該把 Pin-Priority 設高於官方的情境**：

`/etc/apt/preferences.d/org-internal.pref`：

```text
# ★★★ 讓內部庫的套件永遠優先，即使版本比官方舊
Package: *
Pin: origin apt.example.gov.tw
Pin-Priority: 1001
```

| 優先度 | 行為 | 用在哪 |
| --- | --- | --- |
| 100 | 只有「已安裝」才是這個值 | — |
| 500 | ★ 一般庫的預設 | 官方庫 |
| 990 | 目標發行版 | `apt -t noble-backports` |
| 1000 | ★★★ 高優先，但**仍不允許降版** | 大多數第三方庫該用的上限 |
| **1001** | ★★★★ **允許降版**，強制使用這個庫的版本 | **內部庫**、以及需要凍結版本的場合 |

**為什麼內部庫可以設到 1001？**
因為 `org-*` 這些套件官方庫根本沒有，pinning 對它們毫無影響 ——
真正的用意是：**當你在內部庫重新打包了某個上游套件（例如凍結某個 PHP 版本），
要確保它不會被官方的新版蓋掉**。1000 做不到這件事（1000 不允許降版），1001 可以。

> [!danger] ★★★ 1001 的風險：安全更新也會被壓下去
> `Pin-Priority: 1001` 對整個庫的**所有**套件生效。如果哪天有人不小心把一個舊版的 `openssl`
> 匯進內部庫，那**全機關的 openssl 都會被降版並停在那個舊版**，官方的安全更新永遠裝不上去，
> 而且 `apt upgrade` 不會有任何警告。
>
> **三個必要的配套**：
> 1. ★★★★ **縮小 pin 的範圍**，不要用 `Package: *`：
>    ```text
>    Package: org-*
>    Pin: origin apt.example.gov.tw
>    Pin-Priority: 1001
>
>    Package: *
>    Pin: origin apt.example.gov.tw
>    Pin-Priority: 500
>    ```
> 2. ★★★ **每一個超過 1000 的 pin 都要在變更單裡記錄理由、影響範圍與預計解除時間**
> 3. ★★★ 定期用 `apt-cache policy <套件>` 稽核，確認沒有預期外的套件來自內部庫

**驗證客戶端設定**：

```bash
sudo apt update
apt-cache policy org-ca-certificates
```

預期輸出：

```text
org-ca-certificates:
  Installed: 1.0.0
  Candidate: 1.0.0
  Version table:
 *** 1.0.0 1001                                          # ★★★ 看這個 1001
        1001 https://apt.example.gov.tw noble/main amd64 Packages
        100 /var/lib/dpkg/status
```

```bash
# ★★★★ 確認整體優先度沒有誤傷官方庫
apt-cache policy | head -20
```

### ★★★★ 用 aptly 做版本凍結與快速回退

「所有機器同一時間看到同一組套件」是可重現部署的前提。
沒有這件事，你今天裝的機器跟下週裝的機器套件版本就不同，出問題時無從比較。

```bash
# ★ 設定 aptly 的根目錄
sudo tee /etc/aptly.conf >/dev/null <<'EOF'
{
  "rootDir": "/srv/aptly",
  "downloadConcurrency": 4,
  "architectures": ["amd64"],
  "gpgDisableSign": false
}
EOF
```

```bash
# ① 建鏡像（★★★★ 一定要用 -filter，否則 universe 完整鏡像超過 1.5 TB）
sudo aptly mirror create \
  -architectures=amd64 \
  -filter='nginx | php8.3-fpm | mysql-server | Priority (required) | Priority (important)' \
  -filter-with-deps \
  ubuntu-noble-main http://archive.ubuntu.com/ubuntu/ noble main restricted

# ② 抓下來
sudo aptly mirror update ubuntu-noble-main
```

預期輸出：

```text
Downloading & parsing package files...
Building download queue...
Download queue: 1284 items (2.31 GiB)
...
Mirror `ubuntu-noble-main` has been successfully updated.
```

```bash
# ③ ★★★★★ 做快照 —— 這一刻的套件組合被永久凍結，之後上游怎麼變都不影響
sudo aptly snapshot create noble-2026Q3 from mirror ubuntu-noble-main

# ④ 發布
sudo aptly publish snapshot -distribution=noble -component=main \
     -gpg-key="$FPR" noble-2026Q3 internal
```

預期輸出：

```text
Snapshot noble-2026Q3 has been successfully published.
Please setup your webserver to serve directory '/srv/aptly/public/internal' ...
```

```bash
sudo aptly snapshot list
sudo aptly publish list
```

預期輸出：

```text
List of snapshots:
 * [noble-2026Q2]: Snapshot from mirror [ubuntu-noble-main]
 * [noble-2026Q3]: Snapshot from mirror [ubuntu-noble-main]

Published repositories:
  * internal/noble [amd64] publishes {main: [noble-2026Q3]}
```

**季度更新流程**：

```bash
sudo aptly mirror update ubuntu-noble-main
sudo aptly snapshot create noble-2026Q4 from mirror ubuntu-noble-main

# ★★★ 上線前先看差異，這是變更單該附的東西
sudo aptly snapshot diff noble-2026Q3 noble-2026Q4 | head -40
```

預期輸出：

```text
  Package                    noble-2026Q3      noble-2026Q4
- nginx-core_1.24.0-2ubuntu7.1_amd64             -
+ nginx-core_1.24.0-2ubuntu7.3_amd64             -
...
```

```bash
# ★★★★★ 切換（客戶端 URL 完全不變，下次 apt update 就吃到新的一組）
sudo aptly publish switch noble internal noble-2026Q4
```

預期輸出：

```text
Loading packages...
Generating metadata files and linking package files...
Finalizing metadata files...
Signing file 'Release' with gpg, please enter your passphrase when prompted:
Publish for snapshot internal/noble [amd64] publishes {main: [noble-2026Q4]} has been successfully switched to new snapshot.
```

> [!tip] ★★★★★ 這是最快的全機關回退手段
> 升級後發現某個套件把服務弄壞了，你有兩個選擇：
>
> | 做法 | 耗時 | 風險 |
> | --- | --- | --- |
> | 逐台 `apt install pkg=舊版` + `apt-mark hold` | ★★★★ 40 台 × 5 分鐘 = **3 小時**，還會漏掉 | 漏掉的機器版本不一致，之後更難查 |
> | ★★★★★ `aptly publish switch noble internal noble-2026Q3` | **不到 1 分鐘** | 客戶端下次 `apt update` 即回到舊組合 |
>
> ★★★ **但要注意**：`publish switch` 只改變「客戶端看得到什麼版本」，
> **不會自動把已經升級的機器降回去**。已升級的機器要跑：
> ```bash
> sudo apt update
> sudo apt install --allow-downgrades nginx-core=1.24.0-2ubuntu7.1
> ```
> 所以標準流程是：**先 `publish switch` 止血（避免更多機器踩到），再處理已升級的機器。**
> ★★★ 保留最近 4 個 snapshot，超過的用 `aptly snapshot drop` + `aptly db cleanup` 回收空間。

### ★★★★ 簽章金鑰輪替流程

金鑰有效期到了、或懷疑外洩時，**絕對不能直接換一把就完事** ——
那會讓所有客戶端在 `apt update` 時報 `NO_PUBKEY`，等於全機關套件更新停擺。
正確順序是**四階段，新舊並存**：

```text
 T0 ─────────── T0+2週 ─────────── T0+4週 ─────────── T0+6週
 │              │                  │                  │
 【1】產新金鑰   【2】派送新公鑰     【3】切換簽章       【4】移除舊公鑰
 只在簽章機     舊金鑰仍在簽        改 SignWith        確認 100% 覆蓋後
 尚未使用       keyring 含兩把      客戶端已有新公鑰    才移除舊的
                客戶端無感          仍可驗證           
```

```bash
# 【1】產生新金鑰（別動舊的）
sudo GNUPGHOME=/root/.gnupg-aptsign gpg --batch --full-generate-key /tmp/keyparams-2028
NEW_FPR=... ; OLD_FPR=9F8E7D6C5B4A392817260514A1B2C3D4E5F60718

# 【2】★★★★ 把「兩把公鑰」合成一個 keyring，透過 org-apt-keyring 套件派送
sudo GNUPGHOME=/root/.gnupg-aptsign gpg --armor --export "$OLD_FPR" "$NEW_FPR" \
     > build/org-apt-keyring_2.0.0/etc/apt/keyrings/org-apt.asc
# → 打包成 org-apt-keyring 2.0.0，用「舊金鑰」簽章匯入庫中，客戶端照常 apt upgrade 拿到

# ★★★★★ 閘門：確認每一台都拿到 2.0.0 才能進下一步
#   （用 [[03-系統監控與告警]] 的資產清單比對，或直接掃）
for h in $(cat /etc/org/hosts.txt); do
  printf '%-24s ' "$h"
  ssh "$h" 'dpkg-query -W -f="${Version}\n" org-apt-keyring 2>/dev/null || echo MISSING'
done | grep -v ' 2\.0\.0$'          # ★ 這裡必須沒有任何輸出

# 【3】切換簽章金鑰
sudo sed -i "s/^SignWith: .*/SignWith: $NEW_FPR/" /srv/apt/conf/distributions
sudo reprepro -b /srv/apt export noble
gpg --verify /srv/apt/dists/noble/InRelease      # ★ 確認顯示 NEW_FPR

# 【4】兩週後、確認無異常，才移除舊公鑰（重打 keyring 3.0.0 只含新金鑰）
```

> [!danger] ★★★★★ 私鑰外洩時的緊急程序不一樣
> 上面是「計畫性輪替」。**懷疑私鑰外洩時沒有六週可以慢慢走**：
> 1. **立刻**在庫主機上停掉 Nginx 或封鎖來源（阻止攻擊者推送簽好的惡意套件）
> 2. 發布撤銷憑證，通知所有相關人員
> 3. ★★★★ 用**帶外通道**（不經過套件庫本身，例如 Ansible／人工）強制派送新 keyring
> 4. 清查 `/var/log/nginx/apt.access.log` 與 `pool/` 的檔案 mtime，找出有無被塞入的套件
> 5. ★★★★ 全機關比對 `dpkg -V`（驗證已安裝檔案的雜湊）與 `debsums -c`
> 6. 事後檢討並記入資安事件簿，銜接 [[03-弱點與修補管理流程]]

### 庫的維運

| 項目 | 做法 | 星級 |
| --- | --- | --- |
| **磁碟空間** | `df -h /srv/apt`；月排程跑 `reprepro deleteunreferenced` 與 `aptly db cleanup` | ★★★ 空間滿了 `includedeb` 會失敗並可能留下不一致的 db |
| **備份三件事** | ① `pool/` 的 deb ② **簽章私鑰（離線）** ③ `conf/`。★★★ `db/` 可由前三者重建，不必備份 | ★★★★ 少了②整個庫要重來一次並重新派送金鑰 |
| **Release 過期監控** | 監控 `dists/*/Release` 的 `Valid-Until`，剩 3 天告警 | ★★★★ 過期後全機關 `apt update` 直接失敗 |
| **索引一致性** | 週排程 `reprepro check && reprepro checkpool` | ★★★ 不一致時客戶端報 `Hash Sum mismatch` |
| **存取紀錄** | `access_log` 保留至少 6 個月，供稽核與事件追查 | ★★★ 也是「哪些機器沒在更新」的最好資料來源 |
| **與修補流程銜接** | 上游釋出安全更新 → aptly `mirror update` + `snapshot` + `diff` 附進變更單 → 測試環境 → `publish switch` | ★★★★ 見 [[03-弱點與修補管理流程]] |

**Release 過期監控腳本**（放進 [[18-排程工作]] 的每日排程）：

```bash
#!/usr/bin/env bash
# /usr/local/sbin/apt-repo-expiry-check
set -euo pipefail
THRESHOLD_DAYS=3
rc=0
for rel in /srv/apt/dists/*/Release; do
    valid=$(awk -F': ' '/^Valid-Until:/{print $2}' "$rel")
    [ -n "$valid" ] || continue                      # ★ 沒設 ValidFor 就跳過
    left=$(( ( $(date -d "$valid" +%s) - $(date +%s) ) / 86400 ))
    printf '%-40s 剩 %3d 天\n' "$rel" "$left"
    if [ "$left" -lt "$THRESHOLD_DAYS" ]; then
        logger -t apt-repo -p daemon.err "★★★★ $rel 將於 ${left} 天後過期"
        rc=1
    fi
done
exit $rc
```

預期輸出：

```text
/srv/apt/dists/noble/Release             剩  12 天
```

---

## 完整實戰範例

### 情境

在內網建一台 `apt.example.gov.tw`（Ubuntu 24.04 + reprepro + Nginx），
派送兩個內部套件到 40 台受管機器：

| 套件 | 內容 | 為什麼要打包 |
| --- | --- | --- |
| `org-ca-certificates` | 機關根 CA 憑證 | ★★★★ 憑證換發時要能一次換掉全機關 |
| `org-baseline-config` | [[02-基準設定與範本化]] 的基準設定（sysctl、journald、SSH 提示） | ★★★ 有 conffiles，使用者可微調且升級時保留 |

架構：**建置機 `build01`（含私鑰）→ rsync → 發布機 `apt.example.gov.tw`（只有 Nginx）**。

### 【1】發布機：安裝與目錄

```bash
# ── 在 apt.example.gov.tw 上 ──
sudo apt update && sudo apt install -y nginx rsync
sudo install -d -m 0755 -o www-data -g www-data /srv/apt-public
sudo install -d -m 0700 /home/aptsync/.ssh
sudo useradd -r -m -d /home/aptsync -s /bin/bash aptsync 2>/dev/null || true
sudo chown -R aptsync:aptsync /srv/apt-public

# ★★★★ 只允許 build01 用金鑰登入這個帳號，且限制只能跑 rsync
sudo tee /home/aptsync/.ssh/authorized_keys >/dev/null <<'EOF'
command="rrsync -wo /srv/apt-public",no-agent-forwarding,no-port-forwarding,no-pty,no-X11-forwarding ssh-ed25519 AAAAC3Nza... build01-aptsync
EOF
sudo chown -R aptsync:aptsync /home/aptsync/.ssh
sudo chmod 600 /home/aptsync/.ssh/authorized_keys
```

```bash
nginx -t
```

預期輸出：

```text
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

### 【2】建置機：GPG 金鑰

依「環境準備與安裝」段落產生金鑰，並確認：

```bash
sudo GNUPGHOME=/root/.gnupg-aptsign gpg --list-secret-keys --keyid-format=long
```

預期輸出：

```text
sec   rsa4096/A1B2C3D4E5F60718 2026-08-28 [S] [expires: 2028-08-27]
      9F8E7D6C5B4A392817260514A1B2C3D4E5F60718
uid                 [ultimate] Example Gov Internal APT Archive (internal use only) <apt-signing@example.gov.tw>
```

★★★ `[S]` 代表只有簽章用途、`[expires: ...]` 有到期日 —— 兩項都對才往下走。
私鑰備份與撤銷憑證已複製到離線媒體並登記在金鑰清冊。

### 【3】打包兩個 deb

`org-ca-certificates` 見前一節。`org-baseline-config` 的差異在於**有 conffiles**：

```bash
export PKG2=org-baseline-config VER2=1.0.0
export B2="$HOME/build/${PKG2}_${VER2}"
mkdir -p "$B2/DEBIAN" "$B2/etc/org-baseline" "$B2/usr/share/doc/$PKG2"

cat > "$B2/etc/org-baseline/sysctl-hardening.conf" <<'EOF'
# Example Gov 基準設定 —— 可依機器用途調整，升級時你的修改會被保留
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.tcp_syncookies = 1
kernel.kptr_restrict = 2
fs.protected_hardlinks = 1
fs.protected_symlinks = 1
EOF

# ★★★★ 一次列全所有使用者可能會改的檔案，之後才補會覆蓋掉使用者的修改
cat > "$B2/DEBIAN/conffiles" <<'EOF'
/etc/org-baseline/sysctl-hardening.conf
EOF

cat > "$B2/DEBIAN/control" <<EOF
Package: $PKG2
Version: $VER2
Section: admin
Priority: optional
Architecture: all
Depends: procps
Maintainer: 資訊室套件維護 <it-pkg@example.gov.tw>
Description: Example Gov 伺服器基準設定
 佈署機關統一的核心參數強化設定，並在安裝時套用。
 .
 設定檔標記為 conffile，本機修改在升級時會被保留。
EOF

cat > "$B2/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
CONF=/etc/org-baseline/sysctl-hardening.conf
LINK=/etc/sysctl.d/60-org-baseline.conf

case "$1" in
    configure)
        # ★★★★ 冪等：ln -sf 重複執行結果相同；先確認來源存在
        [ -f "$CONF" ] || { echo "$CONF 不存在，安裝異常" >&2; exit 1; }
        ln -sf "$CONF" "$LINK"

        # ★★★ 套用設定；容器內 sysctl 可能失敗，不因此讓整包安裝失敗
        if ! sysctl --system >/dev/null 2>&1; then
            echo "org-baseline-config: sysctl --system 部分失敗（容器環境屬正常）" >&2
        fi
        ;;
    abort-upgrade|abort-remove|abort-deconfigure) ;;
    *) echo "postinst 收到未知參數 '$1'" >&2; exit 1 ;;
esac
exit 0
EOF

cat > "$B2/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
case "$1" in
    remove|purge)
        rm -f /etc/sysctl.d/60-org-baseline.conf
        # ★★ purge 時才清掉 conffile 留下的目錄
        [ "$1" = purge ] && rm -rf /etc/org-baseline
        sysctl --system >/dev/null 2>&1 || true
        ;;
    upgrade|failed-upgrade|abort-install|abort-upgrade|disappear)
        # ★★★★★ 升級時不做事（否則會刪掉新版剛建好的 symlink）
        ;;
    *) echo "postrm 收到未知參數 '$1'" >&2; exit 1 ;;
esac
exit 0
EOF

chmod 0755 "$B2/DEBIAN/postinst" "$B2/DEBIAN/postrm"
```

### 【4】~【8】核心腳本 `/usr/local/sbin/repo-publish`

這支腳本把「打包 → lintian → 版本檢查 → 匯入簽章 → 驗證 → 發布 → 記錄」串成一次操作，
**任何一步失敗都會自動回滾**。

```bash
#!/usr/bin/env bash
# /usr/local/sbin/repo-publish  ——  內部 APT 套件庫發布工具
# 用法：repo-publish <建置目錄> [codename]
#   例：repo-publish /root/build/org-ca-certificates_1.1.0 noble
set -euo pipefail

# ════════════════════════ 設定 ════════════════════════
REPO_BASE=/srv/apt
CODENAME="${2:-noble}"
ARCHIVE_DIR=/srv/apt-archive            # ★★★★ 每個發布過的 deb 都留檔，回退時要用
PUBLISH_HOST=aptsync@apt.example.gov.tw
PUBLISH_PATH=/srv/apt-public
LOGFILE=/var/log/repo-publish.log
export GNUPGHOME=/root/.gnupg-aptsign

BUILD_DIR="${1:?用法: $0 <建置目錄> [codename]}"
BUILD_DIR="${BUILD_DIR%/}"

DEB=""                                   # 供 trap 使用
DB_BACKUP=""
IMPORTED=0

log() { printf '%s  %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOGFILE"; }
die() { log "✗✗ 失敗：$*"; exit 1; }

# ════════════════════ 失敗自動回滾 ════════════════════
rollback() {
    local rc=$?
    [ "$rc" -eq 0 ] && return 0
    log "★★★★ 偵測到失敗（exit=$rc），開始回滾"
    if [ "$IMPORTED" -eq 1 ] && [ -n "$PKG_NAME" ]; then
        log "  → 從 $CODENAME 移除 $PKG_NAME"
        reprepro -b "$REPO_BASE" remove "$CODENAME" "$PKG_NAME" || true
    fi
    if [ -n "$DB_BACKUP" ] && [ -d "$DB_BACKUP" ]; then
        log "  → 還原 reprepro db（來自 $DB_BACKUP）"
        rm -rf "$REPO_BASE/db"
        cp -a "$DB_BACKUP" "$REPO_BASE/db"
        reprepro -b "$REPO_BASE" export "$CODENAME" || true
    fi
    log "  → 回滾完成。★ 尚未 rsync 到發布機，客戶端不受影響"
    exit "$rc"
}
trap rollback EXIT

# ═══════════════ 【0】前置檢查 ═══════════════
log "═══ repo-publish 開始：$BUILD_DIR → $CODENAME ═══"
[ "$(id -u)" -eq 0 ]      || die "必須以 root 執行"
[ -d "$BUILD_DIR/DEBIAN" ] || die "$BUILD_DIR/DEBIAN 不存在，這不是建置目錄"
for c in dpkg-deb lintian reprepro gpg rsync; do
    command -v "$c" >/dev/null || die "缺少指令 $c"
done
[ -f "$REPO_BASE/conf/distributions" ] || die "找不到 $REPO_BASE/conf/distributions"
mkdir -p "$ARCHIVE_DIR"

PKG_NAME=$(awk -F': ' '/^Package:/{print $2; exit}'      "$BUILD_DIR/DEBIAN/control")
PKG_VER=$(awk  -F': ' '/^Version:/{print $2; exit}'      "$BUILD_DIR/DEBIAN/control")
PKG_ARCH=$(awk -F': ' '/^Architecture:/{print $2; exit}' "$BUILD_DIR/DEBIAN/control")
[ -n "$PKG_NAME" ] && [ -n "$PKG_VER" ] && [ -n "$PKG_ARCH" ] \
    || die "control 缺少 Package / Version / Architecture"
log "套件：$PKG_NAME  版本：$PKG_VER  架構：$PKG_ARCH"

# ═══════════════ 【1】★★★★ 版本必須遞增 ═══════════════
OLD_VER=$(reprepro -b "$REPO_BASE" list "$CODENAME" "$PKG_NAME" 2>/dev/null \
          | awk '{print $NF}' | sort -u | head -1 || true)
if [ -n "$OLD_VER" ]; then
    log "庫中現有版本：$OLD_VER"
    if dpkg --compare-versions "$PKG_VER" le "$OLD_VER"; then
        die "新版本 $PKG_VER 不大於庫中的 $OLD_VER —— 客戶端不會升級，中止"
    fi
    log "  ✓ $PKG_VER > $OLD_VER"
else
    log "  ✓ 首次發布"
fi

# ═══════════════ 【2】維護腳本檢查 ═══════════════
for s in preinst postinst prerm postrm; do
    f="$BUILD_DIR/DEBIAN/$s"
    [ -f "$f" ] || continue
    [ -x "$f" ] || die "$s 沒有執行權限（chmod 0755）"
    sh -n "$f"  || die "$s 語法錯誤"
    # ★★★★ 沒有 case 分流的 postrm 是最危險的 bug，直接擋下來
    if [ "$s" = postrm ] && ! grep -q 'case "\$1"' "$f"; then
        die "postrm 沒有 case \"\$1\" 分流 —— 升級時會刪掉新版檔案"
    fi
    log "  ✓ $s 檢查通過"
done
if [ -f "$BUILD_DIR/DEBIAN/conffiles" ]; then
    while read -r cf; do
        [ -z "$cf" ] && continue
        case "$cf" in
            /etc/*) [ -f "${BUILD_DIR}${cf}" ] || die "conffiles 列了 $cf 但檔案不存在" ;;
            *)      die "conffiles 只能列 /etc 底下的路徑，但看到 $cf" ;;
        esac
    done < "$BUILD_DIR/DEBIAN/conffiles"
    log "  ✓ conffiles 檢查通過"
fi

# ═══════════════ 【3】打包 ═══════════════
DEB="$ARCHIVE_DIR/${PKG_NAME}_${PKG_VER}_${PKG_ARCH}.deb"
[ -f "$DEB" ] && die "$DEB 已存在 —— 同版本號重複發布，請提升版本"
dpkg-deb --root-owner-group --build "$BUILD_DIR" "$DEB" >/dev/null \
    || die "dpkg-deb 打包失敗"
log "  ✓ 已產生 $DEB ($(du -h "$DEB" | cut -f1))"

# ★★★★ 確認擁有者是 root:root
if dpkg-deb -c "$DEB" | awk '{print $2}' | grep -qv '^root/root$'; then
    die "deb 內有非 root:root 的檔案 —— 漏了 --root-owner-group"
fi
log "  ✓ 檔案擁有者皆為 root:root"

# ═══════════════ 【4】lintian 閘門 ═══════════════
if ! lintian --fail-on error --no-tag-display-limit "$DEB"; then
    die "lintian 回報 error 級問題"
fi
log "  ✓ lintian 通過（warning 已列出，可接受）"

# ═══════════════ 【5】備份 db 後匯入並簽章 ═══════════════
DB_BACKUP="/var/backups/reprepro-db-$(date +%Y%m%d-%H%M%S)"
cp -a "$REPO_BASE/db" "$DB_BACKUP"
log "  ✓ reprepro db 已備份到 $DB_BACKUP"

reprepro -b "$REPO_BASE" includedeb "$CODENAME" "$DEB" || die "reprepro includedeb 失敗"
IMPORTED=1
log "  ✓ 已匯入 $CODENAME"

# ═══════════════ 【6】驗證簽章與索引 ═══════════════
INREL="$REPO_BASE/dists/$CODENAME/InRelease"
[ -f "$INREL" ] || die "沒有產生 InRelease —— 檢查 conf/distributions 的 SignWith"
gpg --verify "$INREL" 2>&1 | grep -q '^gpg: Good signature' \
    || die "InRelease 簽章驗證失敗"
log "  ✓ InRelease 簽章有效"

reprepro -b "$REPO_BASE" check "$CODENAME"     || die "reprepro check 失敗"
reprepro -b "$REPO_BASE" checkpool             || die "reprepro checkpool 失敗"
reprepro -b "$REPO_BASE" list "$CODENAME" "$PKG_NAME" | grep -q "$PKG_VER" \
    || die "索引中找不到 $PKG_NAME $PKG_VER"
log "  ✓ 索引一致性檢查通過"

# ═══════════════ 【7】發布到對外主機 ═══════════════
# ★★★ --delete 但排除 conf/db —— 它們本來就不該出現在發布機上
rsync -a --delete --exclude='/conf/' --exclude='/db/' --exclude='/incoming/' \
      "$REPO_BASE/dists" "$REPO_BASE/pool" "$REPO_BASE/org-archive-keyring.asc" \
      "${PUBLISH_HOST}:${PUBLISH_PATH}/" || die "rsync 到發布機失敗"
log "  ✓ 已同步到 $PUBLISH_HOST"

# ═══════════════ 【8】從客戶端視角驗證 ═══════════════
TMPD=$(mktemp -d); trap 'rm -rf "$TMPD"' RETURN
mkdir -p "$TMPD/lists/partial" "$TMPD/etc/preferences.d" "$TMPD/etc/sources.list.d"
cat > "$TMPD/etc/sources.list.d/verify.sources" <<VEOF
Types: deb
URIs: https://apt.example.gov.tw/
Suites: $CODENAME
Components: main
Architectures: amd64
Signed-By: /srv/apt/org-archive-keyring.asc
VEOF

if apt-get update \
     -o Dir::Etc::sourcelist=/dev/null \
     -o Dir::Etc::sourceparts="$TMPD/etc/sources.list.d" \
     -o Dir::State::lists="$TMPD/lists" \
     -o Dir::Etc::preferencesparts="$TMPD/etc/preferences.d" \
     -o Acquire::Languages=none >"$TMPD/out" 2>&1; then
    log "  ✓ 外部驗證：apt update 成功（驗簽通過）"
else
    sed 's/^/      /' "$TMPD/out" | tee -a "$LOGFILE"
    die "外部驗證失敗 —— 客戶端會拿不到這個庫"
fi

grep -h "^Package: $PKG_NAME\$" -A2 "$TMPD"/lists/*Packages 2>/dev/null \
    | grep -q "^Version: $PKG_VER\$" \
    || log "  ⚠ 外部索引中未確認到 $PKG_VER（可能是快取，稍後再測）"

# ═══════════════ 完成 ═══════════════
trap - EXIT
log "✓✓ 發布完成：$PKG_NAME $PKG_VER → $CODENAME"
log "   回退方式：reprepro -b $REPO_BASE remove $CODENAME $PKG_NAME"
log "             reprepro -b $REPO_BASE includedeb $CODENAME $ARCHIVE_DIR/${PKG_NAME}_${OLD_VER}_${PKG_ARCH}.deb"
log "   舊 db 備份：$DB_BACKUP（確認無誤後可刪）"
exit 0
```

執行：

```bash
sudo chmod 0755 /usr/local/sbin/repo-publish
sudo /usr/local/sbin/repo-publish /root/build/org-ca-certificates_1.0.0 noble
```

預期輸出：

```text
2026-08-28 10:44:12  ═══ repo-publish 開始：/root/build/org-ca-certificates_1.0.0 → noble ═══
2026-08-28 10:44:12  套件：org-ca-certificates  版本：1.0.0  架構：all
2026-08-28 10:44:12    ✓ 首次發布
2026-08-28 10:44:12    ✓ postinst 檢查通過
2026-08-28 10:44:12    ✓ postrm 檢查通過
2026-08-28 10:44:13    ✓ 已產生 /srv/apt-archive/org-ca-certificates_1.0.0_all.deb (5.2K)
2026-08-28 10:44:13    ✓ 檔案擁有者皆為 root:root
2026-08-28 10:44:15    ✓ lintian 通過（warning 已列出，可接受）
2026-08-28 10:44:15    ✓ reprepro db 已備份到 /var/backups/reprepro-db-20260828-104415
2026-08-28 10:44:17    ✓ 已匯入 noble
2026-08-28 10:44:17    ✓ InRelease 簽章有效
2026-08-28 10:44:18    ✓ 索引一致性檢查通過
2026-08-28 10:44:20    ✓ 已同步到 aptsync@apt.example.gov.tw
2026-08-28 10:44:22    ✓ 外部驗證：apt update 成功（驗簽通過）
2026-08-28 10:44:22  ✓✓ 發布完成：org-ca-certificates 1.0.0 → noble
```

### 【6】客戶端接入與驗證

```bash
# ── 在受管機器上（實際應由 [[02-基準設定與範本化]] 的範本派送）──
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://apt.example.gov.tw/org-archive-keyring.asc \
  | sudo tee /etc/apt/keyrings/org-apt.asc >/dev/null

# ★★★★ 首次取得公鑰時務必核對指紋（帶外確認，不要只信 HTTPS）
gpg --show-keys --with-fingerprint /etc/apt/keyrings/org-apt.asc
```

預期輸出：

```text
pub   rsa4096 2026-08-28 [S] [expires: 2028-08-27]
      9F8E 7D6C 5B4A 3928 1726  0514 A1B2 C3D4 E5F6 0718     # ★★★★ 跟金鑰清冊逐字比對
uid                      Example Gov Internal APT Archive ...
```

```bash
sudo tee /etc/apt/sources.list.d/org-internal.sources >/dev/null <<'EOF'
X-Repolib-Name: Example Gov Internal
Types: deb
URIs: https://apt.example.gov.tw/
Suites: noble
Components: main restricted
Architectures: amd64
Signed-By: /etc/apt/keyrings/org-apt.asc
EOF

sudo tee /etc/apt/preferences.d/org-internal.pref >/dev/null <<'EOF'
Package: org-*
Pin: origin apt.example.gov.tw
Pin-Priority: 1001

Package: *
Pin: origin apt.example.gov.tw
Pin-Priority: 500
EOF

sudo apt update && sudo apt install -y org-ca-certificates org-baseline-config
```

預期輸出：

```text
Get:5 https://apt.example.gov.tw noble InRelease [2,417 B]
Get:6 https://apt.example.gov.tw noble/main amd64 Packages [612 B]
...
Setting up org-ca-certificates (1.0.0) ...
Updating certificates in /etc/ssl/certs...
1 added, 0 removed; done.
Setting up org-baseline-config (1.0.0) ...
```

```bash
# ★★★★ 三項驗證，缺一不可
openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt \
  /usr/local/share/ca-certificates/org-root-ca.crt
sysctl net.ipv4.tcp_syncookies
apt-cache policy org-ca-certificates | sed -n '4p'
```

預期輸出：

```text
/usr/local/share/ca-certificates/org-root-ca.crt: OK
net.ipv4.tcp_syncookies = 1
 *** 1.0.0 1001
```

### 【7】改版測試：確認 conffiles 保留本機修改

```bash
# ── 在客戶端故意修改設定 ──
sudo sed -i 's/^kernel.kptr_restrict = 2/kernel.kptr_restrict = 1/' \
     /etc/org-baseline/sysctl-hardening.conf

# ── 在建置機發 1.1.0（新增一行 net.ipv4.conf.all.send_redirects = 0）──
sudo sed -i 's/^Version: .*/Version: 1.1.0/' \
     /root/build/org-baseline-config_1.0.0/DEBIAN/control
sudo mv /root/build/org-baseline-config_{1.0.0,1.1.0}
sudo /usr/local/sbin/repo-publish /root/build/org-baseline-config_1.1.0 noble

# ── 客戶端升級（★★★ 非互動，明確指定保留本機版本）──
sudo apt update
sudo apt-get -y -o Dpkg::Options::="--force-confold" upgrade org-baseline-config
```

預期輸出：

```text
Setting up org-baseline-config (1.1.0) ...
Configuration file '/etc/org-baseline/sysctl-hardening.conf'
 ==> Modified (by you or by a script) since installation.
 ==> Package distributor has shipped an updated version.
   Keeping old config file as you requested.          # ★★★ 就是要看到這行
```

```bash
grep kptr_restrict /etc/org-baseline/sysctl-hardening.conf
ls -l /etc/org-baseline/
```

預期輸出：

```text
kernel.kptr_restrict = 1                              # ★★★★ 本機修改保住了
-rw-r--r-- 1 root root  312 2026-08-28 11:02 sysctl-hardening.conf
-rw-r--r-- 1 root root  356 2026-08-28 11:05 sysctl-hardening.conf.dpkg-dist   # ★ 新版放這裡
```

★★★ `.dpkg-dist` 是套件提供的新版本。維運人員應該定期用 `diff` 檢視並手動合併，
不然幾次升級之後你的機器就跟基準設定越差越遠。

```bash
find /etc -name '*.dpkg-dist' -o -name '*.dpkg-new' | while read -r f; do
    echo "── $f"; diff -u "${f%.dpkg-*}" "$f" || true
done
```

### 【8】回滾

```bash
# ── 方式 A：reprepro（適用內部套件）──
sudo reprepro -b /srv/apt remove noble org-baseline-config
sudo reprepro -b /srv/apt includedeb noble \
     /srv/apt-archive/org-baseline-config_1.0.0_all.deb
sudo rsync -a --delete --exclude='/conf/' --exclude='/db/' \
     /srv/apt/dists /srv/apt/pool aptsync@apt.example.gov.tw:/srv/apt-public/

# ★★★ 客戶端已升級的要主動降版（publish/remove 不會自動降）
sudo apt update
sudo apt install --allow-downgrades org-baseline-config=1.0.0

# ── 方式 B：aptly（適用上游鏡像／版本凍結）──
sudo aptly publish switch noble internal noble-2026Q3
```

預期輸出：

```text
Publish for snapshot internal/noble [amd64] publishes {main: [noble-2026Q3]}
has been successfully switched to new snapshot.
```

### 驗收檢查表

| # | 檢查項 | 指令 | 預期結果 | 星級 |
| --- | --- | --- | --- | --- |
| 1 | 簽章私鑰**不在**發布機上 | `ssh apt.example.gov.tw 'ls -R /home/*/.gnupg /root/.gnupg 2>&1'` | `No such file or directory` | ★★★★★ |
| 2 | 私鑰備份與撤銷憑證已離線保存並登記 | 人工核對金鑰清冊 | 兩份皆在保險箱，有簽收紀錄 | ★★★★★ |
| 3 | `conf/` 與 `db/` 未對外 | `curl -sI https://apt.example.gov.tw/conf/distributions` | `HTTP/2 404` | ★★★★★ |
| 4 | `InRelease` 簽章有效 | `gpg --verify /srv/apt/dists/noble/InRelease` | `Good signature from ...` | ★★★★ |
| 5 | 公鑰指紋與清冊一致 | `gpg --show-keys --with-fingerprint /etc/apt/keyrings/org-apt.asc` | 指紋逐字相符 | ★★★★ |
| 6 | 客戶端 `apt update` 無 GPG 警告 | `sudo apt update 2>&1 \| grep -i 'gpg\|NO_PUBKEY'` | 無輸出 | ★★★★ |
| 7 | pinning 範圍正確（未誤傷官方庫） | `apt-cache policy \| grep -B1 1001` | 只有 `apt.example.gov.tw` | ★★★★ |
| 8 | 根憑證真的生效 | `openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt /usr/local/share/ca-certificates/org-root-ca.crt` | `OK` | ★★★★ |
| 9 | 內部 HTTPS 服務可驗證 | `curl -sSo /dev/null -w '%{ssl_verify_result}\n' https://intra.example.gov.tw/` | `0` | ★★★★ |
| 10 | `postrm` 有 `case` 分流 | `dpkg-deb --ctrl-tarfile x.deb \| tar -xO ./postrm \| grep 'case "$1"'` | 有匹配 | ★★★★ |
| 11 | deb 內檔案為 `root:root` | `dpkg-deb -c x.deb \| awk '{print $2}' \| sort -u` | 只有 `root/root` | ★★★ |
| 12 | conffiles 升級後保留本機修改 | 依【7】測試 | `Keeping old config file` | ★★★ |
| 13 | `auth.conf.d` 權限 600 | `find /etc/apt/auth.conf.d -type f ! -perm 600` | 無輸出 | ★★★★ |
| 14 | `Release` 未接近過期 | `/usr/local/sbin/apt-repo-expiry-check` | 剩餘天數 > 3 | ★★★★ |
| 15 | 每個發布版本都有留檔 | `ls /srv/apt-archive/` | 含所有歷史版本 | ★★★ |
| 16 | 索引與 pool 一致 | `reprepro -b /srv/apt check && reprepro -b /srv/apt checkpool` | 無輸出 | ★★★ |
| 17 | 磁碟餘量充足 | `df -h /srv/apt \| tail -1` | 使用率 < 80% | ★★ |
| 18 | 回滾程序已實測 | 依【8】演練一次 | 客戶端降回舊版成功 | ★★★★ |

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ **升級後全機關內部 HTTPS 全部憑證錯誤** | `postrm` 沒有 `case "$1"` 分流，升級時舊版 postrm 以 `upgrade` 被呼叫，刪掉了新版剛解開的憑證 | 修正 postrm（見「維護腳本執行時機」），發新版；受影響機器 `apt install --reinstall org-ca-certificates` |
| ★★★★★ **客戶端 `apt update` 報 `NO_PUBKEY`，全機關更新停擺** | 換了簽章金鑰但沒有先派送新公鑰 | 立即用 aptly `publish switch` 或改回舊 `SignWith` 重新 `export`；之後照四階段輪替流程 |
| ★★★★ `Release file for ... is expired` / `is not valid yet` | `ValidFor` 到期沒重新 export；或**客戶端時鐘不準** | `reprepro -b /srv/apt export noble`；客戶端 `timedatectl status` 確認 NTP 同步 |
| ★★★★ **裝了套件但憑證沒生效**（`dpkg -l` 顯示 `ii`） | 檔案副檔名不是 `.crt`，或內容是 DER 不是 PEM，`update-ca-certificates` 靜默忽略 | `openssl x509 -in ... -noout -subject` 驗格式；用 `-inform DER` 轉檔後重新打包 |
| ★★★★ `apt upgrade` 完全不動新發布的套件 | 新版本號**不大於**舊版（例如 `1.10` 之後發 `1.9`，或誤加 `~`） | `dpkg --compare-versions` 驗證；提高版本號重發 |
| ★★★★ **官方安全更新裝不上去** | `Pin-Priority: 1001` 配 `Package: *`，內部庫的舊版套件壓過官方 | 把 pin 縮到 `Package: org-*`；`apt-cache policy <套件>` 逐一稽核 |
| ★★★ `E: Conflicting distribution: ... (expected stable but got noble)` | 客戶端 `Suites:` 與 `conf/distributions` 的 `Codename`/`Suite` 不符 | 兩邊統一；`curl -s https://.../dists/noble/Release \| head` 看實際值 |
| ★★★ `Hash Sum mismatch` | 中間有透明代理／CDN 快取了舊索引；或 rsync 到一半 | Nginx 對 `dists/` 加 `Cache-Control: no-cache`；rsync 改用 `--delay-updates`；客戶端 `rm -rf /var/lib/apt/lists/*` |
| ★★★ `The repository ... is not signed` | `conf/distributions` 缺 `SignWith`，只產生了 `Release` 沒有 `InRelease` | 補 `SignWith: <指紋>` 後 `reprepro export`。★★★★ **不要用 `[trusted=yes]` 繞過** |
| ★★★ `reprepro: Error ... unknown architecture 'all'` | `conf/distributions` 的 `Architectures` 沒列 `all` | 加上 `all`，然後 `reprepro export` |
| ★★★ `dpkg: error processing ...: subprocess installed post-installation script returned error exit status 1` | postinst 非冪等（`mkdir` 已存在、`useradd` 重複），或相依未宣告 | `dpkg --configure -a` 看完整訊息；修正腳本並補 `Depends:` |
| ★★★ `unable to execute .../postinst (Permission denied)` | 維護腳本沒有執行位元 | `chmod 0755 DEBIAN/postinst` 重新打包；`dpkg-deb -I` 看檔名前有沒有 `*` |
| ★★★ `trying to overwrite '/etc/x.conf', which is also in package Y` | 兩個套件裝同一個檔案，缺 `Conflicts`/`Replaces` | 在新套件的 control 加 `Conflicts: Y` + `Replaces: Y` |
| ★★★ **使用者說「我改的設定升級後不見了」** | 該檔案沒列在 `conffiles`（或第一版沒列、後來才補） | 補進 conffiles 並發新版；已被覆蓋的只能從備份還原 |
| ★★★ 客戶端 `403 Forbidden` 抓不到 deb | Nginx `deny` 規則太寬（誤擋 `pool/`），或 basic auth 憑證沒設 | `tail /var/log/nginx/apt.access.log`；檢查 `/etc/apt/auth.conf.d/` 權限與內容 |
| ★★★ `/srv/apt` 磁碟滿了 | 舊版本 deb 留在 pool、aptly snapshot 累積 | `reprepro deleteunreferenced`；`aptly snapshot drop` + `aptly db cleanup` |
| ★★ `N: Skipping acquire of configured file 'main/binary-i386/Packages'` | 客戶端 `Architectures:` 含庫裡沒有的架構 | 在 `.sources` 明確寫 `Architectures: amd64`（本來就該寫） |
| ★★ `apt update` 提示 `Repository ... changed its 'Origin' value` | 改了 `conf/distributions` 的 `Origin` 或 `Label` | 客戶端跑一次 `apt update --allow-releaseinfo-change`；★★★ 別隨便改這兩個欄位，pinning 靠它 |

### 排查步驟

遇到「客戶端裝不到 / 裝錯版本」時，**由外而內**依序走，不要跳。

**【1】確認庫本身的索引是對的（在建置機上）**

```bash
sudo reprepro -b /srv/apt list noble org-ca-certificates
```

預期輸出：

```text
noble|main|amd64: org-ca-certificates 1.1.0
```

看到期待的版本 → 問題在**發布或客戶端**，往【2】。
沒有輸出 → 問題在**匯入**，回去看 `repo-publish` 的日誌 `/var/log/repo-publish.log`。

**【2】確認 rsync 真的把新索引推出去了（從外部抓）**

```bash
curl -s https://apt.example.gov.tw/dists/noble/InRelease | head -12
```

預期輸出：

```text
-----BEGIN PGP SIGNED MESSAGE-----
Hash: SHA512

Origin: ExampleGov
Codename: noble
Date: Fri, 28 Aug 2026 11:05:12 UTC
Valid-Until: Fri, 11 Sep 2026 11:05:12 UTC      # ★★★★ 看這行有沒有過期
```

`Date` 是舊的 → **rsync 沒跑或失敗**，看 `repo-publish` 日誌的步驟【7】。
`Valid-Until` 已過 → 跑 `reprepro export` 後重新同步。
`404` → Nginx 的 `root` 或 `location` 設錯，看 `/var/log/nginx/apt.error.log`。

**【3】確認外部拿到的 Packages 含目標版本**

```bash
curl -s https://apt.example.gov.tw/dists/noble/main/binary-amd64/Packages.gz \
  | gunzip | grep -A3 '^Package: org-ca-certificates$'
```

預期輸出：

```text
Package: org-ca-certificates
Version: 1.1.0
Architecture: all
```

版本是舊的 → 索引沒更新（回【2】）。
完全找不到 → `Components` 或 `Architectures` 不符，比對 `conf/distributions`。

**【4】驗簽（用客戶端手上的那把公鑰驗，不是用建置機的）**

```bash
curl -s https://apt.example.gov.tw/dists/noble/InRelease -o /tmp/InRelease
gpgv --keyring <(gpg --dearmor < /etc/apt/keyrings/org-apt.asc) /tmp/InRelease
```

預期輸出：

```text
gpgv: Signature made Fri 28 Aug 2026 11:05:12 AM UTC
gpgv: Good signature from "Example Gov Internal APT Archive ..."
```

`Can't check signature: No public key` → **客戶端的公鑰不對或不是最新的**（金鑰輪替沒做完）。
`BAD signature` → 檔案在傳輸中被改動或 rsync 傳到一半，重新同步。

**【5】客戶端的 apt 到底看到什麼**

```bash
sudo apt update
apt-cache policy org-ca-certificates
```

預期輸出：

```text
org-ca-certificates:
  Installed: 1.0.0
  Candidate: 1.1.0                                # ★★★ Candidate 是新版就對了
  Version table:
     1.1.0 1001
        1001 https://apt.example.gov.tw noble/main amd64 Packages
 *** 1.0.0 1001
        100 /var/lib/dpkg/status
```

`Candidate` 仍是舊版 → 快取沒更新，`sudo rm -rf /var/lib/apt/lists/* && sudo apt update`。
`Candidate: (none)` → 這台機器根本沒吃到這個庫，往【6】。

**【6】確認 sources 與 preferences 真的被讀進去**

```bash
apt-config dump | grep -i 'Dir::Etc::sourceparts\|Dir::Etc::preferences'
ls -l /etc/apt/sources.list.d/ /etc/apt/preferences.d/
apt-cache policy | grep -A2 'apt.example.gov.tw'
```

預期輸出：

```text
-rw-r--r-- 1 root root 268 Aug 28 10:50 /etc/apt/sources.list.d/org-internal.sources
 1001 https://apt.example.gov.tw/ noble/main amd64 Packages
     release o=ExampleGov,n=noble,c=main,b=amd64
```

★★★ `.sources` 的**副檔名寫錯成 `.list` 或 `.conf` 會被完全忽略**，這是最常見的低級錯誤。
`apt-cache policy` 看不到這個 URL 就是檔案沒被讀。

**【7】確認 pinning 沒有反效果**

```bash
apt-cache policy | grep -B2 -A2 '1001'
```

預期輸出：

```text
 1001 https://apt.example.gov.tw/ noble/main amd64 Packages
     release o=ExampleGov,n=noble,c=main,b=amd64
```

★★★★ 若這裡出現 `archive.ubuntu.com`，代表 pin 的比對條件寫錯（例如 `Pin: origin ""` 命中了本機檔案來源），
**官方安全更新可能已經被壓住**，立即修正並跑 `apt list --upgradable` 確認沒有漏掉的更新。

**【8】維護腳本層級的問題**

```bash
# 把 deb 拆開直接看腳本（★ 不用安裝就能檢查）
dpkg-deb --ctrl-tarfile /srv/apt-archive/org-ca-certificates_1.1.0_all.deb | tar -tv
dpkg-deb --ctrl-tarfile /srv/apt-archive/org-ca-certificates_1.1.0_all.deb | tar -xO ./postrm

# 在客戶端看安裝過程的完整輸出
sudo dpkg --configure -a
sudo journalctl -t org-ca-certificates -n 20
grep -E 'org-(ca-certificates|baseline-config)' /var/log/dpkg.log | tail -20
```

預期輸出：

```text
2026-08-28 11:07:31 upgrade org-ca-certificates:all 1.0.0 1.1.0
2026-08-28 11:07:31 status half-configured org-ca-certificates:all 1.0.0
2026-08-28 11:07:32 status unpacked org-ca-certificates:all 1.1.0
2026-08-28 11:07:33 status installed org-ca-certificates:all 1.1.0    # ★ 到 installed 才算完成
```

停在 `half-configured` 或 `half-installed` → postinst 失敗。
`unpacked` 之後就沒了 → 相依沒滿足，`apt --fix-broken install`。

---

## 安全性注意事項

> [!danger] ★★★★★ 簽章私鑰絕對不能放在對外提供服務的主機上
> 套件庫的整條信任鏈只靠一把私鑰。發布機是唯一暴露在網路上的元件 ——
> 它被打下來，攻擊者就能**簽出任意套件推送給全機關的每一台機器**，
> 而每一台客戶端都會驗簽通過、安靜地以 root 權限執行你的 `postinst`。
> 這等同於一次性的全域 RCE，而且 `apt` 不會留下任何異常。
>
> **必做**：
> - reprepro 與 GPG 私鑰只存在於**只有維運人員能登入**的建置機
> - 建置機到發布機用**單向 rsync**（發布機不能反向連建置機）
> - 發布機上的同步帳號用 `command="rrsync -wo /srv/apt-public"` 限制成只能寫入該目錄
> - 私鑰有 passphrase，備份加密後**離線**保存
> - ★★★★ 定期（至少每季）在發布機上執行 `ls -R /root/.gnupg /home/*/.gnupg` 確認沒有私鑰殘留

> [!danger] ★★★★★ 絕不要用 `[trusted=yes]` 或 `--allow-unauthenticated`
> ```bash
> # ❌ 這兩行都等於「我不驗簽了，誰給我什麼我都裝」
> deb [trusted=yes] https://apt.example.gov.tw/ noble main
> sudo apt-get install --allow-unauthenticated somepkg
> ```
> 建庫初期為了「先讓它跑起來」而暫時加上，然後**永遠忘了拿掉**，是實務上最常見的破口。
> 簽章壞掉的正確處理是**修好簽章**，不是關掉驗證。

> [!danger] ★★★★ `/etc/apt/auth.conf.d/*` 是明文密碼
> 權限不是 `0600 root:root` 就等於把庫的帳密送給機器上每一個本機使用者與每一個
> 以 `www-data` 執行的網頁程式。而且這個密碼通常對**所有機器**都一樣 ——
> 一台機器上的低權限 RCE 就變成整個內部套件庫的讀取權。
> 攻擊者拿到 `org-baseline-config` 等於拿到你的完整安全組態藍圖。
>
> 更好的做法：**用 IP 白名單而非帳密**；真的要帳密就每個網段一組，並排進定期輪換。

> [!danger] ★★★★ 不要把任何機密裝進 deb
> 憑證**私鑰**、資料庫密碼、API token、`auth.conf` 內容 —— 一個都不能放進套件。
> 原因：deb 會散布到每一台機器、留在 `/var/cache/apt/archives/`、
> 進備份、進 pool（可被任何有庫存取權的人下載）、而且**沒有任何存取控制**。
> 只放**公開的**東西：根憑證的**公鑰部分**、設定範本、腳本。
> 機密走 [[05-自動化佈建入門]] 的 Ansible Vault 或專門的秘密管理工具。

> [!warning] ★★★★ postinst 是以 root 執行的任意程式碼
> 這句話對「你的套件」和「別人的套件」同時成立。
> - 你這邊：任何能寫入建置目錄或能對庫 `includedeb` 的人，就能對全機關執行 root 指令。
>   **建置機的登入權限與 `sudo` 規則要當成最高等級的資產管理**，並開啟 `auditd` 記錄
>   （見 [[08-系統強化與稽核]]）。
> - 對外那邊：這也正是 [[03-第三方APT套件庫實務]] 強調第三方庫風險評估的原因。

> [!warning] ★★★ 機關情境的三個額外要求
> - **稽核軌跡**：`repo-publish` 的日誌、Nginx `access_log`、以及「誰批准發這個版本」的變更單，
>   三者要能對得起來。日誌保留期依機關規定（多數要求 6 個月以上），做法見 [[02-日誌集中與輪替]]
> - **最小權限**：`includeb` 的權限與「能登入建置機」的權限要分開；
>   發布是核可後的動作，不是任何一個維運人員隨時可做的事
> - **TWGCB 符合性**：內部庫派送的 `org-baseline-config` 就是基準組態的載體，
>   內容變更等同於組態變更，要走同一套核可與檢測流程（見 [[04-TWGCB-Linux本機導入]]）

> [!warning] ★★★ 庫本身也要納入備份與弱點管理
> - 備份三件事：`pool/`（deb 檔）、**簽章私鑰**、`conf/`。`db/` 可重建，不用備。做法見 [[03-備份策略與還原演練]]
> - 發布機是一台對外服務主機，**它自己也要打修補**。別讓「派送修補的機器」變成沒修補的那台
> - 內部庫延後了上游安全更新的到達時間（因為要先鏡像、測試、切換）——
>   ★★★★ 這個延遲要納入 [[03-弱點與修補管理流程]] 的 SLA，緊急修補要有繞過流程

---

## 速查表

### 打包

| 指令 | 說明 | 星級 |
| --- | --- | --- |
| `dpkg-deb --root-owner-group --build DIR OUT` | 打包，強制檔案為 root:root | ★★★★ 少 `--root-owner-group` 會裝出錯誤擁有者 |
| `dpkg-deb -I x.deb` | 看 control 與維護腳本清單 | ★★★ 腳本前有 `*` 才代表可執行 |
| `dpkg-deb -c x.deb` | 看檔案清單、權限、擁有者 | ★★★ 這就是安裝後的樣子 |
| `dpkg-deb --ctrl-tarfile x.deb \| tar -xO ./postrm` | 不安裝直接看維護腳本 | ★★★ 排查與稽核必備 |
| `dpkg-deb -x x.deb /tmp/d` | 解出 data 到目錄 | ★★ |
| `lintian --fail-on error x.deb` | 品質閘門 | ★★★ 內部套件只需清掉 error 級 |
| `dpkg --compare-versions A lt B` | 版本排序驗證（回傳 0 為真） | ★★★★ 發版前必跑 |
| `dpkg -V <pkg>` / `debsums -c` | 驗證已安裝檔案是否被竄改 | ★★★★ 資安事件時的關鍵工具 |

### reprepro

| 指令 | 說明 | 星級 |
| --- | --- | --- |
| `reprepro -b /srv/apt includedeb noble x.deb` | 匯入並重新簽章 | ★★★★ |
| `reprepro -b /srv/apt list noble [pkg]` | 列出索引內容 | ★★★ |
| `reprepro -b /srv/apt remove noble pkg` | 從索引移除 | ★★★ pool 檔案還在 |
| `reprepro -b /srv/apt deleteunreferenced` | 清掉無人引用的 pool 檔案 | ★★★ 磁碟回收 |
| `reprepro -b /srv/apt export noble` | 重新產生並簽章索引 | ★★★★ ValidFor 到期時用 |
| `reprepro -b /srv/apt check` / `checkpool` | 一致性檢查 | ★★★ 週排程 |
| `reprepro -b /srv/apt listfilter noble 'EXPR'` | 條件查詢 | ★★ |

### aptly

| 指令 | 說明 | 星級 |
| --- | --- | --- |
| `aptly mirror create -filter=... NAME URL DIST COMP` | 建立上游鏡像 | ★★★★ 一定要 `-filter`，否則吃掉 TB 級空間 |
| `aptly mirror update NAME` | 抓取上游 | ★★★ |
| `aptly snapshot create SNAP from mirror NAME` | ★★★★★ 凍結這一刻的套件組合 | ★★★★★ |
| `aptly snapshot diff A B` | 比較兩個快照 | ★★★★ 變更單的附件 |
| `aptly publish snapshot -gpg-key=FPR SNAP PREFIX` | 首次發布 | ★★★ |
| `aptly publish switch DIST PREFIX NEWSNAP` | ★★★★★ 一行切換／回退 | ★★★★★ |
| `aptly snapshot drop SNAP` + `aptly db cleanup` | 回收空間 | ★★★ 保留最近 4 個快照 |

### 檔案路徑

| 路徑 | 用途 | 星級 |
| --- | --- | --- |
| `/srv/apt/conf/distributions` | 庫定義（Codename / Components / SignWith） | ★★★★★ 絕不可對外 |
| `/srv/apt/db/` | reprepro 內部資料庫 | ★★★★★ 絕不可對外，可重建 |
| `/srv/apt/dists/<codename>/InRelease` | 簽章後的索引，客戶端第一個抓的檔案 | ★★★★ |
| `/srv/apt-archive/` | 所有發布過的 deb 留檔 | ★★★★ 回退的唯一依據 |
| `/etc/apt/sources.list.d/*.sources` | 客戶端庫定義（**副檔名必須 `.sources`**） | ★★★ |
| `/etc/apt/keyrings/*.asc` | 客戶端公鑰 | ★★★ |
| `/etc/apt/preferences.d/*.pref` | pinning | ★★★★ 錯了會壓住安全更新 |
| `/etc/apt/auth.conf.d/*` | 庫的帳密 | ★★★★ 必須 0600 root:root |
| `/var/log/dpkg.log` | 安裝／升級的完整軌跡 | ★★★ 排查維護腳本問題 |

### 判斷準則

| 情境 | 用什麼 | 星級 |
| --- | --- | --- |
| 內部設定／憑證，要能升級與移除 | ★★★ 打包成 deb + reprepro | ★★★ |
| 一次性丟一支腳本，三台機器 | Ansible / rsync，**不要建庫** | ★★ |
| 離線封閉網段 | aptly mirror（`-filter` 限縮） | ★★★★ |
| 要求所有機器版本完全一致 | ★★★★★ aptly snapshot + publish | ★★★★★ |
| 出事要在 5 分鐘內全機關回退 | ★★★★★ `aptly publish switch` | ★★★★★ |
| 要保留多個版本讓客戶端選 | aptly（reprepro 只留一個版本） | ★★★ |

---

## 練習題

> [!question]- 練習 1：親手重現「postrm 沒分流」的事故
> **★★★★ 在測試機或容器裡做，不要在正式機做。**
>
> 1. 打包 `org-test-cert` v1.0.0，`postrm` **故意**寫成沒有 `case` 分流：
>    ```sh
>    #!/bin/sh
>    set -e
>    rm -f /usr/local/share/ca-certificates/org-test.crt
>    update-ca-certificates --fresh >/dev/null
>    ```
> 2. `sudo dpkg -i` 安裝，確認 `openssl verify` 通過
> 3. 改版本為 1.1.0（憑證內容不變），重新打包並 `sudo dpkg -i` 升級
> 4. 再跑一次 `ls -l /usr/local/share/ca-certificates/` 與 `openssl verify`
> 5. 記錄你看到什麼
> 6. 修正 postrm 加上 `case "$1" in remove|purge) ... ;; upgrade|...) ;; esac`，重做步驟 3~4
>
> **參考解答**：
> 步驟 4 你會發現 `org-test.crt` **不見了** —— 明明只是升級。
> 原因是 dpkg 升級序列的第 4 步呼叫 `old-postrm upgrade 1.1.0`，
> 而此時新版的 `data.tar` 已經解開，憑證檔在磁碟上，於是被 `rm -f` 刪掉。
> 之後的 `new-postinst configure` 跑 `update-ca-certificates` 也救不回來（檔案已經沒了）。
> 修正後步驟 4 的 `openssl verify` 應回 `OK`，`ls` 看得到檔案。
> ★★★★ 這個練習的價值在於：**這種 bug 在「首次安裝」的測試中 100% 不會出現**，
> 只有實際做過一次升級才會暴露 —— 所以發版流程一定要包含「從舊版升級」的測試，
> 不能只測乾淨安裝。

> [!question]- 練習 2：驗證 pinning 沒有壓住官方安全更新
> 情境：你的 `/etc/apt/preferences.d/org-internal.pref` 寫的是 `Package: *` + `Pin-Priority: 1001`，
> 而某位同事不小心把一個舊版的 `curl` 匯進了內部庫。
>
> 1. 在測試機上模擬：找一個目前版本比官方舊的套件，打包成同名 deb 匯入內部庫
>    （或直接改 preferences 讓某個官方套件的 candidate 變成舊版）
> 2. 執行並記錄：
>    ```bash
>    apt-cache policy curl
>    apt list --upgradable
>    ```
> 3. 觀察 `Candidate` 是不是變成了內部庫的舊版
> 4. 把 pin 改成兩段式（`Package: org-*` 給 1001、`Package: *` 給 500），重測
> 5. 寫一支稽核腳本，列出所有 candidate 來自內部庫、但官方有更新版的套件
>
> **參考解答**：
> 步驟 3 會看到 `Candidate: 7.81.0-1` 之類的舊版，而且 `apt list --upgradable` **不會**列出 curl ——
> apt 認為「已經是最新的候選版本了」，沒有任何警告。這正是最危險的地方。
> 步驟 4 修正後，`Candidate` 應回到官方的最新版。
> 步驟 5 的稽核腳本核心：
> ```bash
> apt-cache policy $(dpkg-query -W -f='${Package}\n') 2>/dev/null | \
>   awk '/^[a-z0-9]/{p=$1} /^ \*\*\*/{v=$2} /apt.example.gov.tw/{print p, v}'
> ```
> ★★★★ 實務上建議把這支腳本排進每週檢查，並在變更單上要求「任何 Pin-Priority > 1000
> 的設定都必須記錄理由與預計解除時間」。

> [!question]- 練習 3：完整走一次金鑰輪替
> 在兩台測試機（一台當建置機、一台當客戶端）上：
>
> 1. 建一個最小的 reprepro 庫，用金鑰 A 簽章，客戶端接上並成功 `apt update`
> 2. 產生金鑰 B（**不要動 A**）
> 3. 打包 `test-keyring` v2.0.0，內含 A + B 兩把公鑰，放到 `/etc/apt/keyrings/`，
>    **用金鑰 A 簽章**匯入庫中
> 4. 客戶端 `apt upgrade` 拿到 v2.0.0
> 5. 把 `conf/distributions` 的 `SignWith` 改成 B 的指紋，`reprepro export`
> 6. 客戶端 `apt update` —— **應該完全正常，沒有任何 GPG 警告**
> 7. 現在故意做錯：把 keyring 換成只有 B（v3.0.0），但在客戶端**先**移除 A、
>    再把庫改回用 A 簽章，觀察錯誤訊息
>
> **參考解答**：
> 步驟 6 之所以正常，是因為客戶端的 keyring 同時含 A 與 B，
> apt 只要**其中一把**能驗過就接受 —— 這就是「新舊並存期」的技術基礎。
> 步驟 7 你會看到：
> ```text
> W: GPG error: https://apt.test noble InRelease: The following signatures couldn't be
>    verified because the public key is not available: NO_PUBKEY A1B2C3D4E5F60718
> E: The repository 'https://apt.test noble InRelease' is not signed.
> ```
> 而且 **`apt update` 後這個庫的所有套件都消失了**（apt 直接不採用未驗證的庫）。
> ★★★★★ 這正是「先切簽章再派金鑰」會造成的全機關停擺 ——
> 順序反了就是事故。務必依「【1】產金鑰 →【2】派新公鑰並確認 100% 覆蓋 →
> 【3】切換簽章 →【4】移除舊公鑰」的順序。
> 恢復方式：把 `SignWith` 改回客戶端手上有的那把金鑰並 `reprepro export`。

---

## 小測驗

Q1. 升級一個自製 deb 時，dpkg 會呼叫**舊版本**的哪一支維護腳本？它以什麼參數被呼叫？在新檔案解開之前還是之後？

Q2. 下面這行 `postinst` 有什麼問題？會在什麼情況下爆炸？
```sh
mkdir /etc/org-baseline && cp /usr/share/org/default.conf /etc/org-baseline/
```

Q3. （是非）`Version: 1.2.3-1~noble1` 的排序**大於** `Version: 1.2.3-1`。

Q4. 你把簽章私鑰放在 `apt.example.gov.tw` 上，理由是「這樣 reprepro 跟 Nginx 在同一台比較好管」。請說明最壞情況會發生什麼。

Q5. 客戶端跑 `apt update` 出現 `NO_PUBKEY A1B2C3D4E5F60718`，且該庫的所有套件都消失了。最可能的原因是什麼？該先查哪裡？

Q6. `reprepro includedeb noble pkg_2.0.0_all.deb` 之後，客戶端還能不能用 `apt install pkg=1.0.0` 裝回舊版？為什麼？

Q7. 為什麼說「內部庫是少數應該把 `Pin-Priority` 設到 1001 的情境」？1000 和 1001 的差別是什麼？這樣做有什麼風險？

Q8. 你在 v1.0.0 忘了把 `/etc/org-baseline/x.conf` 列進 `DEBIAN/conffiles`，v1.1.0 才補上。升級到 v1.1.0 時使用者的修改會怎樣？

Q9. 這兩行指令分別會發生什麼事？差別在哪？
```bash
aptly publish switch noble internal noble-2026Q3
apt install --allow-downgrades nginx-core=1.24.0-2ubuntu7.1
```

Q10. `dpkg-deb -c org-tool_1.0.0_all.deb` 輸出裡出現 `-rwxr-xr-x 1000/1000 ... ./usr/local/bin/orgtool`。這代表什麼？裝上去會怎樣？怎麼修？

> [!question]- 測驗答案
> **Q1.** 呼叫的是**舊版本的 `postrm`**，參數為 `upgrade <新版本號>`，
> 而且是在**新檔案已經解開之後**（升級序列的第 4 步）。
> 完整順序是：`old-prerm upgrade 新版` → `new-preinst upgrade 舊版` → 解開新 data.tar →
> ★★★★★ `old-postrm upgrade 新版` → 處理 conffiles → `new-postinst configure 舊版`。
> 這是自製 deb 最常炸的地方：如果 `postrm` 沒有 `case "$1"` 分流就直接 `rm -f`，
> 它刪掉的是**新版剛裝好的檔案**。對 `org-ca-certificates` 來說，
> 後果是全機關的根憑證信任在一次例行升級後集體消失，內部 HTTPS、`git clone`、
> Java 應用全部開始噴憑證錯誤，而 `dpkg -l` 顯示套件狀態是完全正常的 `ii`。
> 詳見「觀念說明 → ★★★★ 維護腳本的執行時機」那張表。
>
> **Q2.** 兩個問題，都跟**冪等**有關：
> ① `mkdir` 在目錄已存在時回傳非 0，`set -e` 之下整支 postinst 失敗，
> 套件卡在 `half-configured`，`apt` 後續操作全部被擋住（`dpkg was interrupted`）。
> ② `&&` 讓 `cp` 只在 `mkdir` 成功時執行，所以升級時設定檔根本不會被更新。
> 爆炸時機：**任何一次升級**、`dpkg --configure -a`、`apt --fix-broken install` ——
> 也就是說「首次安裝的測試」100% 測不出來。
> 正確寫法：`mkdir -p /etc/org-baseline` 分行寫，且設定檔應該由 `data.tar` 直接帶入
> 並宣告為 conffile，不要在 postinst 裡 `cp`。★★★★
> 見「維護腳本的執行時機 → 冪等」。
>
> **Q3.** **錯（是非題答「非」）。** `~` 的排序**小於**「什麼都沒有」，所以
> `1.2.3-1~noble1` **<** `1.2.3-1` < `1.2.3-1ubuntu1`。
> 這是刻意設計的 backport 慣例：讓你的移植版排在官方正式版之前，
> 官方一旦發布正式版本，客戶端就會自動升級過去、把你的移植版換掉。
> 驗證方式不要靠記憶：
> ```bash
> dpkg --compare-versions "1.2.3-1~noble1" lt "1.2.3-1"; echo $?    # 0 = 真
> ```
> 順帶一提 `1.10 > 1.9`（版本號不是小數），`+` 的排序則大於空字串。★★★
> 見「觀念說明 → ★★★ 版本號規則與陷阱」。
>
> **Q5.** 最可能是**簽章金鑰換了，但新公鑰還沒派送到這台客戶端**
> （或輪替順序做反了：先切 `SignWith` 才派 keyring）。
> ★★★★★ 後果是這台機器完全拿不到內部庫的任何套件 —— apt 不是「警告後繼續」，
> 而是**直接不採用未驗證的庫**。
> 排查順序：
> 【1】先看庫端 `gpg --verify /srv/apt/dists/noble/InRelease` 用的是哪把金鑰；
> 【2】再看客戶端 `gpg --show-keys --with-fingerprint /etc/apt/keyrings/org-apt.asc`
> 有沒有那把；
> 【3】兩者不符就確認 keyring 套件版本 `dpkg -l org-apt-keyring`。
> 止血方式：把 `conf/distributions` 的 `SignWith` **改回客戶端手上有的那把**、
> `reprepro export` 重新同步，然後照四階段流程重做輪替。
> 見「常見錯誤與排錯」第 2 列與「★★★★ 簽章金鑰輪替流程」。
>
> **Q4.** 最壞情況是**一次性的全機關 root RCE**。
> 發布機是唯一暴露在網路上的元件，一旦被入侵（Nginx 漏洞、SSH 弱密碼、OS 未修補），
> 攻擊者拿到私鑰後可以：打包一個含惡意 `postinst` 的 deb → 用你的金鑰簽章 →
> 放進庫 → **全機關 40 台機器在下次 `apt upgrade` 時以 root 身分執行它**。
> 每一台的 `apt` 都會驗簽通過、不會有任何警告，`dpkg -l` 看起來也完全正常。
> ★★★★★ 正確做法是把 reprepro 與私鑰放在只有維運人員能登入的建置機，
> 用**單向 rsync** 推到發布機，發布機的同步帳號用
> `command="rrsync -wo /srv/apt-public"` 限制成只能寫入指定目錄。
> 成本幾乎為零，卻消掉整個架構最大的單點風險。
> 見「環境準備與安裝 → 主機規劃」與「安全性注意事項」第一個 danger。
>
> **Q6.** **不能。** ★★★ reprepro 每個 codename **只保留一個版本**，
> 匯入 2.0.0 之後 1.0.0 就從 `Packages` 索引消失了
> （pool 裡的檔案還在，但 `deleteunreferenced` 之後連檔案也會刪掉）。
> 客戶端 `apt install pkg=1.0.0` 會得到
> `E: Version '1.0.0' for 'pkg' was not found`。
> 這帶出兩個實務要求：
> ① ★★★★ **每一個發布過的 deb 都要留檔**（本篇放在 `/srv/apt-archive/`），
> 回退時要 `reprepro remove` 再 `includedeb` 舊檔；
> ② 需要真正的多版本保留與快速回退，就要用 aptly 的 snapshot 機制。
> 見「基礎設定 → reprepro 每個 codename 只保留一個版本」的 warning。
>
> **Q7.** 差別在**能不能降版**：`Pin-Priority` 在 1 到 1000 之間時，
> apt 只會在「候選版本比已安裝版本新」時才升級；**只有超過 1000（也就是 1001）
> 才允許降版**，也就是強制使用該庫的版本，即使它比官方舊。
> 內部庫需要 1001 的真正理由不是為了 `org-*`（官方庫根本沒有這些套件，pin 對它們沒作用），
> 而是**當你在內部庫重新打包了某個上游套件來凍結版本時**，
> 要確保官方的新版不會把它蓋掉。
> ★★★ 風險：`Package: *` + 1001 會讓**內部庫的所有套件**壓過官方，
> 包含安全更新 —— 如果有人不小心匯入一個舊版 `openssl`，全機關就會降版並卡在那裡，
> 而 `apt list --upgradable` 不會有任何提示。
> 配套：把 pin 縮成 `Package: org-*` 給 1001、`Package: *` 給 500；
> 每個超過 1000 的 pin 都要在變更單記錄理由與解除時間；定期用 `apt-cache policy` 稽核。
> 見「進階設定與調校 → 客戶端接入的標準做法」。
>
> **Q8.** ★★★★ **使用者的修改會在升到 v1.1.0 的那一次被直接覆蓋，而且沒有任何提示。**
> 原因：dpkg 判斷 conffile 要不要保留是靠「三方比對」——
> 原始版雜湊（安裝 v1.0.0 時記錄的）、目前磁碟上的版本、新版。
> v1.0.0 沒宣告成 conffile，所以 dpkg **沒有原始雜湊可比對**，
> 只能把它當成一般檔案處理 → 直接以新版覆蓋。
> 從 v1.1.0 之後（有了原始雜湊）才會正常詢問或保留。
> 這就是為什麼「**conffiles 必須在第一版就列全**」——
> 打包前要先想清楚哪些檔案是使用者可以改的。
> 補救只能靠備份還原（見 [[03-備份策略與還原演練]]），或事先公告這一次升級會重設設定檔。
> 見「觀念說明 → conffiles」的 danger callout。
>
> **Q9.** 兩行做的是**完全不同層次**的事：
> - `aptly publish switch noble internal noble-2026Q3`：改變**客戶端「看得到」什麼版本**。
>   把已發布的 `internal/noble` 底下的內容換成舊快照，客戶端下次 `apt update` 就會看到
>   2026Q3 那一組套件。★★★★★ 這是**止血**動作，不到一分鐘、影響全部機器，
>   但**不會**自動把已經升級的機器降回去。
> - `apt install --allow-downgrades nginx-core=1.24.0-2ubuntu7.1`：改變**這一台機器實際裝的版本**。
>   ★★★ 這是**修復**動作，要逐台執行，而且前提是那個版本在庫裡拿得到
>   （所以必須先做完上一行的 `publish switch`）。
> 正確流程：**先 `publish switch` 止血（避免更多機器踩到），再逐台降版**。
> 順序反了的話，你降完版的機器下次 `apt upgrade` 又會升回壞掉的版本。
> 見「進階設定與調校 → aptly 版本凍結」與「完整實戰範例【8】回滾」。
>
> **Q10.** `1000/1000` 是打包時**漏了 `--root-owner-group`**，
> dpkg-deb 把你當時的 uid/gid 記進了 `data.tar`。
> 裝到別台機器上，`/usr/local/bin/orgtool` 的擁有者會變成該機器上 uid 1000 的使用者
> —— 通常是第一個一般帳號。
> ★★★★ 後果是**權限提升漏洞**：那個使用者可以任意改寫這支以 root 執行的工具
> （若它被 cron 或 systemd 以 root 呼叫），等於本機提權。
> lintian 會抓到 `E: wrong-file-owner-uid-or-gid`，這是必須清掉的 error 級問題。
> 修法：重新打包時加 `--root-owner-group`：
> ```bash
> dpkg-deb --root-owner-group --build "$BUILD" out/
> dpkg-deb -c out/x.deb | awk '{print $2}' | sort -u    # ★ 應只有 root/root
> ```
> 本篇的 `repo-publish` 腳本在步驟【3】就把這項當成硬性閘門擋下來。
> 見「基礎設定 → 建置與檢查」與「驗收檢查表」第 11 項。

---

## 延伸閱讀

- [[03-第三方APT套件庫實務]] — 本篇的反面。`signed-by`、pinning 的完整語法、第三方庫的風險評估與撤除流程都在那裡，接第三方庫前先讀
- [[14-套件管理]] — `apt` / `dpkg` 的日常操作與狀態機；本篇的排錯大量用到 `apt-cache policy` 與 `dpkg.log`
- [[02-基準設定與範本化]] — 本篇打包的 `org-baseline-config` 就是那篇的產出，兩篇要一起看才完整
- [[01-新機建置標準流程]] — 內部庫的接入設定應該寫進新機 SOP，不是靠人工事後補
- [[05-自動化佈建入門]] — 判斷「這件事該打包成 deb 還是用 Ansible 派送」，以及帶外派送金鑰的做法
- [[09-根憑證派送與信任]] — 本篇只負責把根憑證裝進 deb；憑證怎麼被各種應用（Java、Node.js、瀏覽器）信任在那篇
- [[12-憑證生命週期管理]] — GPG 簽章金鑰的輪替節奏與 TLS 憑證的生命週期管理是同一套思維
- [[03-弱點與修補管理流程]] — 內部庫延後了安全更新的到達時間，這個延遲要納入修補 SLA 並設計緊急繞過流程
- [[01-MyGuard套件庫介紹]] — 一個真實第三方庫的樣貌，可以對照本篇看「別人是怎麼做的」
- [[03-備份策略與還原演練]] — 庫的備份三件事（pool、私鑰、conf）要納入既有備份制度

官方文件：

- Debian Policy Manual — Package maintainer scripts：<https://www.debian.org/doc/debian-policy/ch-maintainerscripts.html>
- Debian Policy Manual — Version 欄位語法：<https://www.debian.org/doc/debian-policy/ch-controlfields.html#version>
- reprepro 官方手冊：<https://salsa.debian.org/brlink/reprepro>
- aptly 文件（mirror / snapshot / publish）：<https://www.aptly.info/doc/>
- Debian Wiki — DebianRepository/Format（Release / InRelease 規格）：<https://wiki.debian.org/DebianRepository/Format>
- Ubuntu manpage — `sources.list(5)` deb822 格式：<https://manpages.ubuntu.com/manpages/noble/man5/sources.list.5.html>
