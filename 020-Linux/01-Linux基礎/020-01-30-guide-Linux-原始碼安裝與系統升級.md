---
title: "原始碼安裝與系統升級"
desc: "從原始碼編譯安裝到 /usr/local 的正確做法、checkinstall/stow 管理，以及大版本升級（do-release-upgrade、leapp）的完整流程"
aliases: [configure, make install, checkinstall, stow, do-release-upgrade, leapp, 大版本升級, 系統升級]
tags: [群組/Linux, linux/基礎, 主題/套件, 主題/升級]
category: Linux基礎
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[020-01-14-guide-Linux-套件管理]]", "[[020-01-25-guide-Linux-開機流程與GRUB救援]]"]
updated: 2026-08-29
---

# 原始碼安裝與系統升級

> [!abstract] 這篇你會學到
> - ★★★ 什麼時候該從原始碼裝、什麼時候絕對不該——以及**原始碼安裝的三個代價**
> - ★★★ `./configure --prefix=/usr/local` 的意義，與讓套件管理員知道你裝了什麼的方法（`checkinstall`、`stow`）
> - ★★★ 安全地移除原始碼安裝的東西（`make uninstall` 經常不存在）
> - ★★★★★ 大版本升級（Ubuntu 22.04→24.04、RHEL 8→9）的**前置檢查、執行、驗證、回退**完整流程
> - ★★★★ 判斷「原地升級」與「重建遷移」哪個風險較低

## 前置知識

- [[020-01-14-guide-Linux-套件管理]]
- [[020-01-25-guide-Linux-開機流程與GRUB救援]]

---

## 第一部分：從原始碼安裝

### 什麼時候才需要

| 情況 | 該做的 |
| --- | --- |
| 套件庫有，版本夠用 | **用套件庫**，沒有討論空間 |
| 套件庫版本太舊 | 先找**官方上游套件庫**或 PPA（見 [[020-01-14-guide-Linux-套件管理]]） |
| 需要特定編譯選項（Nginx 加模組） | 找有提供該模組的套件庫（如 [[060-02-02-00-idx-Nginx]] 的強化版）；真的沒有才自己編 |
| 上游只提供原始碼 | 原始碼安裝，**但要用 checkinstall 或 stow 管理** |
| 要打修補／改程式碼 | 原始碼安裝 |

> [!danger] ★★★★ 原始碼安裝的三個代價
> 1. ★★★★ **不會收到安全更新**——套件管理員不知道它存在，`apt upgrade` 不會碰它。
>    你自己要追蹤 CVE、自己重編。多數人不會，於是它變成一個永久的漏洞。
> 2. **無法乾淨移除**——`make install` 把檔案撒到 `/usr/local/{bin,lib,share,include,etc}`，
>    很多專案沒有 `make uninstall`。
> 3. **與套件版本衝突**——裝到 `/usr` 會覆蓋套件檔案；裝到 `/usr/local` 則 PATH 順序決定誰贏，容易「明明升級了還跑到舊版」。
>
> 這三點是「能用套件就用套件」的理由，不是偏見。

### 標準流程：configure → make → install

```bash
# 0. 編譯工具鏈
sudo apt install -y build-essential pkg-config      # RHEL: dnf groupinstall "Development Tools"

# 1. 取得原始碼並驗證                        ★★★★ 這一步跳過＝用 root 編譯來路不明的程式碼
wget https://example.org/foo-1.2.3.tar.gz{,.asc}
gpg --verify foo-1.2.3.tar.gz.asc foo-1.2.3.tar.gz   # 或 sha256sum -c ★★★★ 沒有 Good signature 就停手
tar xzf foo-1.2.3.tar.gz && cd foo-1.2.3

# 2. 看說明！每個專案不同（有的專案根本不是 autotools）
less README* INSTALL*
./configure --help | less

# 3. 設定（決定裝到哪、開哪些功能）          ★★★★ --prefix 決定日後能不能乾淨移除
./configure --prefix=/usr/local --sysconfdir=/etc/foo --with-openssl

# 4. 編譯（-j 用所有核心）
make -j"$(nproc)"

# 5. 測試（有的話）—— 跑得過再裝，省下事後排錯
make check   # 或 make test

# 6. 安裝——先看會裝哪些檔案                 ★★★ make -n 是乾跑，先看再裝
make -n install | grep -E 'install|cp ' | head -30
sudo make install
```

### `--prefix` 決定一切 ★★★★

```
--prefix=/usr/local      ← 預設，正確                          ★★★
    /usr/local/bin/foo
    /usr/local/lib/libfoo.so
    /usr/local/share/man/man1/foo.1
    /usr/local/etc/foo.conf         ← 除非另指定 --sysconfdir
--prefix=/usr            ← ✗ 會與套件管理員打架                 ★★★★
--prefix=/opt/foo        ← 自成一包，好移除但要自己加 PATH
```

> [!tip] ★★★ `/usr/local` 已經在 PATH 且優先於 `/usr`
> ```bash
> echo $PATH | tr ':' '\n' | head -3
> ```
> ```
> /usr/local/sbin
> /usr/local/bin        ← 在 /usr/bin 前面
> /usr/sbin
> ```
> 所以裝到 `/usr/local/bin/nginx` 會**遮住** `/usr/sbin/nginx`——
> 這是設計，但也是「以為在跑套件版其實在跑自編版」的來源。
> `type -a nginx` 永遠列出所有同名的（見 [[020-01-20-guide-Linux-環境變數與設定檔]]）。

### `configure` 失敗：缺 `-dev` 套件

```
checking for OpenSSL... no
configure: error: OpenSSL library not found
```

編譯需要**標頭檔**，在 `-dev`（Debian）/ `-devel`（RHEL）套件裡：

```bash
sudo apt install -y libssl-dev libpcre2-dev zlib1g-dev
# RHEL: sudo dnf install -y openssl-devel pcre2-devel zlib-devel
```

```bash
# 找哪個套件提供某個標頭檔
sudo apt install -y apt-file && sudo apt-file update
apt-file search openssl/ssl.h
# RHEL: dnf provides '*/openssl/ssl.h'
```

> [!tip] ★★★ 用 `apt build-dep` 一次裝齊
> 如果套件庫裡有同名套件（只是版本舊），可以直接借它的建置相依：
> ```bash
> sudo apt build-dep nginx        # 需要 sources.list 有 deb-src
> ```
> 然後再編你要的新版。

### 共享函式庫：`ldconfig`

裝到 `/usr/local/lib` 的 `.so` 執行時找不到：

```
error while loading shared libraries: libfoo.so.1: cannot open shared object file
```

```bash
ldd /usr/local/bin/foo | grep 'not found'  # ★★★ 先看到底缺哪一個 .so
sudo ldconfig                              # 重建快取（/usr/local/lib 預設已在 /etc/ld.so.conf.d/）
ldconfig -p | grep libfoo                  # 快取裡有了才算數
```

自訂路徑（如 `/opt/foo/lib`）要加：

```bash
echo "/opt/foo/lib" | sudo tee /etc/ld.so.conf.d/foo.conf
sudo ldconfig
```

> [!warning] ★★★★ 不要用 `LD_LIBRARY_PATH` 當永久解法
> 它是除錯用的環境變數，放進 `.bashrc` 或 systemd 會造成安全與相依混亂。
> 用 `ld.so.conf.d`。
> ★★★★ 具體風險：它讓「任何可寫目錄裡的同名 `.so`」搶在系統函式庫之前被載入，
> 服務又常以高權限執行 —— 這就是典型的函式庫劫持路徑。

### 讓系統知道你裝了什麼：三種做法 ★★★★

#### 做法一：`checkinstall`——把 `make install` 變成 .deb

```bash
sudo apt install -y checkinstall
cd foo-1.2.3
./configure --prefix=/usr/local && make -j"$(nproc)"
sudo checkinstall --pkgname=foo --pkgversion=1.2.3 --default   # ★★★★ 取代 make install，不要兩個都跑
```

```
Done. The new package has been installed and saved to
/home/mike/foo-1.2.3/foo_1.2.3-1_amd64.deb
You can remove it from your system anytime using: dpkg -r foo
```

之後 `dpkg -l foo`、`dpkg -L foo`、`sudo apt remove foo` 都能用，
**可以乾淨移除、可以複製到其他機器安裝**。

> [!tip] ★★★ checkinstall 是最省事的折衷
> 它監看 `make install` 寫了哪些檔案並打成套件。缺點是不處理相依宣告
> （套件不知道自己需要 libssl），且專案維護不太活躍。
> 對「偶爾裝一兩個工具」足夠；要正式分發就寫真正的 debian/ 打包。

#### 做法二：`stow`——每個軟體一個目錄，用符號連結「啟用」

```bash
sudo apt install -y stow
./configure --prefix=/usr/local/stow/foo-1.2.3   # ★★★★ 關鍵在這行：prefix 指到 stow 目錄，不是 /usr/local
make -j"$(nproc)" && sudo make install
cd /usr/local/stow
sudo stow foo-1.2.3            # 在 /usr/local/{bin,lib,...} 建符號連結
ls -l /usr/local/bin/foo       # -> ../stow/foo-1.2.3/bin/foo（確認是連結不是實體檔）
```

```bash
# 升級：裝新版到旁邊，切換連結
sudo stow -D foo-1.2.3         # 移除舊連結
sudo stow foo-1.3.0            # 啟用新版 ★★★ 切換就是重建連結，秒級且可逆
# 移除：
sudo stow -D foo-1.3.0 && sudo rm -rf /usr/local/stow/foo-1.3.0   # ★★★ 先 -D 再刪，順序反了會留下斷掉的連結
```

> [!tip] ★★★ stow 讓「多版本並存、秒級切換、乾淨移除」變簡單
> 每個版本自成一個目錄，`/usr/local` 裡只有符號連結。
> 這與 [[020-01-05-cmd-Linux-路徑導覽與檔案操作]] 的零停機部署是同一個思路。

#### 做法三：`--prefix=/opt/foo` 自成一包 ★★

```bash
./configure --prefix=/opt/foo-1.2.3
sudo make install
sudo ln -sfn /opt/foo-1.2.3 /opt/foo    # ★★★ -n 很重要，否則會把連結建到目錄裡面去
echo 'export PATH="/opt/foo/bin:$PATH"' | sudo tee /etc/profile.d/foo.sh   # 只對登入 shell 生效，systemd 服務讀不到
echo "/opt/foo/lib" | sudo tee /etc/ld.so.conf.d/foo.conf && sudo ldconfig
```

移除就是 `rm -rf /opt/foo-1.2.3` 加上那兩個設定檔。

### 移除原始碼安裝的東西

```bash
# 1. 有 make uninstall 就用（要在同版本的原始碼目錄）★★★ 版本或 --prefix 不一致會刪錯東西
cd foo-1.2.3 && sudo make uninstall

# 2. 沒有：用當時的安裝紀錄
sudo make -n install 2>/dev/null | grep -oE '/usr/local/[^ ]+' | sort -u    # 推算會裝哪些
# 或安裝時就先記錄
sudo make install 2>&1 | tee /root/foo-install.log

# 3. 都沒有：依時間找 ★★ 只是推測，刪之前一定要逐檔看過
sudo find /usr/local -newer /root/before-install-marker -type f
```

> [!tip] ★★★ 安裝前留個時間標記
> ```bash
> touch /root/before-install-marker
> sudo make install
> sudo find /usr/local -newer /root/before-install-marker -type f > /root/foo-files.txt
> ```
> 之後要移除就 `xargs rm < /root/foo-files.txt`。
> ★★★★ 動手前先 `xargs ls -l < /root/foo-files.txt` 看一遍 —— 這份清單是用時間戳推出來的，
> 同時間被其他程序改到的檔案也會混進去，直接餵給 `rm` 等於拿推測結果做不可逆操作。
> 這是「沒用 checkinstall/stow」時的最低保障。

### 自編軟體的維護義務 ★★★★

```bash
# ★★★★ 記錄：裝了什麼、哪個版本、為什麼、怎麼編的（沒有這份紀錄＝沒人知道要更新它）
sudo tee -a /usr/local/share/doc/LOCAL-INSTALLS.md > /dev/null <<'DOC'
## foo 1.2.3 — 2026-08-27 — mike
- 原因：套件庫只有 1.0，需要 1.2 的 --with-openssl 功能
- 來源：https://example.org/foo-1.2.3.tar.gz（sha256: ...）
- 編譯：./configure --prefix=/usr/local/stow/foo-1.2.3 --with-openssl
- 管理：stow
- 安全公告追蹤：https://example.org/security（每月維護檢查）   # ★★★★★ 少了這行，它就是一個沒人管的長期漏洞
DOC
```

> [!warning] ★★★★ 自編的東西要列入每月維護
> 把 `LOCAL-INSTALLS.md` 的每一項對照上游安全公告，是 [[100-02-04-guide-維運-每月維護作業]] 的項目。
> 做不到這件事，就不該用原始碼安裝。

---

## 第二部分：系統大版本升級

### 原地升級 vs 重建遷移 ★★★★

| | 原地升級（in-place） | 重建遷移（rebuild） |
| --- | --- | --- |
| 做法 | `do-release-upgrade` / `leapp` | 裝新機、搬服務與資料、切換 |
| 停機 | 升級期間（30 分～數小時） | 切換瞬間（可接近零） |
| ★★★★★ 風險 | **中高**：舊設定殘留、第三方套件庫不相容、半途失敗 | 低：舊機器完整保留可回切 |
| 乾淨度 | 帶著多年累積的殘渣 | 乾淨 |
| ★★★★ 適合 | 單純的機器、有快照、可接受停機 | 正式服務、複雜環境、跨兩個以上大版本 |

> [!tip] ★★★★★ 有快照或是 VM 才考慮原地升級
> 實體機、無法快照、跑著重要服務、或距今兩個以上大版本（18.04→24.04）——
> **重建遷移**幾乎總是比較安全。原地升級的「省事」經常在失敗時加倍奉還。
> 而且重建遷移讓你有機會實踐 [[020-02-03-01-svc-標準化-新機建置標準流程]]。

### 前置檢查清單（兩種發行版通用）★★★★★

```bash
# ── 1. 現況記錄 ───────────────────────────────────── ★★★★
#    沒有這份紀錄，升級後你無法回答「本來有什麼、現在少了什麼」
. /etc/os-release; echo "$PRETTY_NAME"; uname -r
apt-mark showmanual > /root/pre-upgrade-manual-packages.txt       # 手動裝的套件 ★★★
dpkg-query -W -f='${Package}\t${Version}\n' > /root/pre-upgrade-all.txt
systemctl list-unit-files --state=enabled > /root/pre-upgrade-services.txt   # ★★★★ 升級後要 diff 這份
ss -tlnp > /root/pre-upgrade-ports.txt                     # ★★★★ 埠不見＝服務沒起來
sudo tar czpf /root/pre-upgrade-etc.tar.gz /etc            # 整個 /etc ★★★★★ 設定選錯時唯一的救命稻草

# ── 2. 第三方套件庫：升級的頭號殺手 ──────────────────── ★★★★★
ls /etc/apt/sources.list.d/
apt-cache policy | grep -E '^ [0-9]+ ' | grep -v ubuntu.com | awk '{print $2}' | sort -u
# 每一個都要確認：新版本有沒有對應的 codename？沒有就先停用 ★★★★★

# ── 3. 自編／非套件管理的東西 ────────────────────────── ★★★★
cat /usr/local/share/doc/LOCAL-INSTALLS.md 2>/dev/null
ls /usr/local/bin /opt
dkms status                                                # DKMS 模組要支援新核心 ★★★★ ZFS 沒跟上＝資料碟掛不起來

# ── 4. 空間 ─────────────────────────────────────────── ★★★
df -h / /boot /var                                         # 根至少留 5～10GB ★★★★ 升到一半沒空間會停在半套件狀態
sudo apt clean; sudo apt autoremove --purge

# ── 5. 系統健康 ─────────────────────────────────────── ★★★★
sudo apt update && sudo apt full-upgrade -y                # 先把現版更新到最新 ★★★★ 帶著待處理的更新去升級必炸
sudo dpkg --configure -a; sudo apt --fix-broken install
systemctl --failed                                         # ★★★★ 應為空；升級前就壞的服務升級後只會更壞
sudo find /etc -name '*.dpkg-dist' -o -name '*.dpkg-old'   # 先處理完（見 14 篇）

# ── 6. 備份與快照 ───────────────────────────────────── ★★★★★
# VM：拍快照。實體機：完整備份且驗證過還原（見 03-備份策略與還原演練）
# ★★★★★ 「有備份」不算數，「還原過而且成功」才算數 —— 這是唯一的回退路徑

# ── 7. 存取保障 ─────────────────────────────────────── ★★★★
# 確認主控台（IPMI/PVE console）可用——升級中 SSH 可能中斷 ★★★★★ 沒有主控台就等於沒有救援管道
# 在 tmux 裡執行——見 01-tmux-工作階段管理 ★★★★★ 不在 tmux 裡，SSH 一斷升級程序就跟著死
```

> [!danger] ★★★★★ 第 2 項是升級失敗的頭號原因
> 第三方套件庫（PPA、docker、nodesource、php ondrej…）在新 codename 上可能還沒有套件，
> 或提供的版本與新系統的相依衝突。`do-release-upgrade` 會自動停用它們，
> 但**升級後你要一個一個重新啟用並確認**——這是升級後「服務版本莫名變了」的來源。
> ★★★★ 最糟的情況不是服務起不來（那你馬上會發現），而是它「起來了但退回發行版舊版」，
> 資料庫或 PHP 就這樣默默換了一個版本在跑。

### Ubuntu：`do-release-upgrade` ★★★★

```bash
# LTS → 下一個 LTS（22.04 → 24.04）；預設只在新 LTS 的 .1 版釋出後才提供
cat /etc/update-manager/release-upgrades          # Prompt=lts
sudo apt install -y update-manager-core

tmux new -s upgrade                               # ★★★★★ 一定在 tmux 裡
sudo do-release-upgrade                           # 互動式 ★★★★ 全程要有人看著，它會停下來問你
# sudo do-release-upgrade -d                      # ★★★★ 強制升到開發中/剛釋出的版本（不建議正式環境）
```

過程中會問：

| 提示 | 建議 |
| --- | --- |
| ★★★ 第三方來源已停用 | 記下清單，升級後逐一處理 |
| ★★ 是否移除過時套件 | 先看清單，通常 `y` |
| ★★★★★ **設定檔衝突（`sshd_config`、`nginx.conf`…）** | **`N`（保留你的）**，之後用 `.dpkg-dist` 比對合併；**絕對不要**對 `sshd_config` 選「安裝套件版本」否則可能鎖死 |
| ★★★ 重新啟動服務 | `Yes` |
| ★★ 重開機 | 完成後 `y` |

> [!warning] ★★★★ 升級中 SSH 斷線怎麼辦
> `do-release-upgrade` 透過 SSH 執行時會在 **1022 埠**開一個備援 sshd。
> 斷線後 `ssh -p 1022 host`，`tmux attach -t upgrade` 接回。
> ★★★★★ 這就是為什麼要在 tmux 裡跑，且防火牆要暫時放行 1022。
> ★★★★ 1022 是**臨時**的救援通道，升級與驗證做完務必收掉，別讓它變成一個沒人記得的對外埠。

### RHEL 系：`leapp` ★★★★

RHEL/Rocky/Alma 8→9 用 `leapp`，**先預檢再升級**：

```bash
sudo dnf install -y leapp-upgrade                 # Rocky/Alma 另需 elevate 套件庫
sudo leapp preupgrade                             # ★★★★★ 只檢查，不動系統 —— 一定要先跑這個
less /var/log/leapp/leapp-report.txt              # ★★★★★ 逐條看：inhibitor 必須先解決
```

```
Risk Factor: high (inhibitor)
Title: Possible problems with remote login using root account
Summary: ... PermitRootLogin ...
Remediation: [hint] ...
```

```bash
# 依報告處理（常見：PermitRootLogin 明確設定、移除不相容套件、答覆問題）★★★★
sudo leapp answer --section remove_pam_pkcs11_module_check.confirm=True   # ★★★ answer 等於簽名負責，看懂再答
sudo leapp preupgrade                             # ★★★★ 重跑到沒有 inhibitor
sudo leapp upgrade                                # ★★★★ 執行（此時仍未真的換版）
sudo reboot                                       # ★★★★★ 進入升級 initramfs，會跑很久；這段全程沒有 SSH，只能看主控台
```

> [!tip] ★★★★ `leapp preupgrade` 的報告就是你的 to-do list
> `inhibitor` 不解決就不會讓你升；`high` 應該處理；`medium/low` 看情況。
> 比 Ubuntu 的流程嚴謹，但也意味著前置工作更多。

### 升級後驗證 ★★★★

```bash
. /etc/os-release; echo "$PRETTY_NAME"; uname -r   # ★★★ 版本與核心都要對
systemctl --failed                                 # ★★★★★ 第一個要看的，非空就先處理
comm -23 <(sort /root/pre-upgrade-services.txt) <(systemctl list-unit-files --state=enabled | sort) | head   # ★★★★ 少了哪些服務
diff <(awk '{print $4}' /root/pre-upgrade-ports.txt | sort -u) <(ss -tlnp | awk '{print $4}' | sort -u)     # ★★★★ 埠有無變化
sudo find /etc -name '*.dpkg-dist' -o -name '*.dpkg-old' -o -name '*.rpmnew' -o -name '*.rpmsave'   # ★★★★ 逐一合併
apt list --upgradable 2>/dev/null | head           # 升級後再跑一次 apt upgrade
dkms status                                        # ★★★★ 模組都 installed
sudo journalctl -b -p err --no-pager | head -30    # 開機錯誤一次看完

# 第三方套件庫：一個一個改 codename 後重新啟用
ls /etc/apt/sources.list.d/*.distUpgrade 2>/dev/null   # do-release-upgrade 備份的舊來源
# 應用層驗證：網站、資料庫、排程各跑一次
```

> [!warning] ★★★★ 升級後最常出事的四個地方
> 1. ★★★★ **PHP / Python / Node 版本跳級**——應用程式不相容（Ubuntu 22.04→24.04 是 PHP 8.1→8.3）
> 2. ★★★★ **第三方套件庫被停用**——服務退回發行版內建的舊版或更新版
> 3. ★★★★★ **設定檔格式改變**——Nginx、MySQL、sshd 的新版預設值不同（`.dpkg-dist` 要看）
> 4. ★★★ **Python 2 / 舊函式庫消失**——自寫腳本或舊工具壞掉
>
> 每一項都要在測試機先跑過。

### 回退 ★★★★★

| 情況 | 回退方式 |
| --- | --- |
| ★★★★★ VM 有快照 | **還原快照**，唯一乾淨的方式 |
| ★★★★ 實體機有完整備份 | 重灌舊版 + 還原備份 |
| ★★★★ 升級中途失敗、系統還開得起來 | `apt --fix-broken install; dpkg --configure -a` 嘗試完成，**不要試圖降級** |
| ★★★★★ 開不起來 | GRUB 選舊核心；Live 環境 chroot（見 [[020-01-25-guide-Linux-開機流程與GRUB救援]]） |

> [!danger] ★★★★★ Linux 沒有「降級」這回事
> `apt` 與 `dnf` 都**不支援**把整個系統從新版降回舊版。
> 升級前沒快照／備份 = 沒有回退路徑。這是決定「原地升級 vs 重建」時最重要的考量。

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
>
> | 項目 | Ubuntu | RHEL 系 |
> | --- | --- | --- |
> | 編譯工具鏈 | `build-essential` | `dnf groupinstall "Development Tools"` |
> | 標頭檔套件 | `libxxx-dev` | `xxx-devel` |
> | 找標頭檔套件 | `apt-file search` | `dnf provides '*/檔案'` |
> | 借建置相依 | `apt build-dep X` | `dnf builddep X` |
> | checkinstall | 可用 | 可用（EPEL），或 `rpmbuild` |
> | ★★★★ 大版本升級 | `do-release-upgrade` | **`leapp`**（8→9） |
> | ★★★★ 預檢 | 無獨立步驟 | **`leapp preupgrade`** |
> | ★★★★★ 升級中備援 SSH | 1022 埠 | 無（重開機進 initramfs 升級，全程需主控台） |
> | ★★★★ 升級後檢查檔 | `.dpkg-dist` / `.dpkg-old` | `.rpmnew` / `.rpmsave` |
> | ★★★ 模組流（PHP 版本） | 第三方庫 | `dnf module` 要 reset 重設 |
>
> Rocky/Alma 的 leapp 需要 ELevate 專案的套件庫：
> ```bash
> sudo dnf install -y https://repo.almalinux.org/elevate/elevate-release-latest-el8.noarch.rpm
> sudo dnf install -y leapp-upgrade leapp-data-rocky   # 或 leapp-data-almalinux
> ```

---

## 完整實戰範例：Ubuntu 22.04 → 24.04 原地升級（VM）

```bash
# ═══ D-1：前置 ═══                        ★★★★★ 這一段做完才有資格按下升級
tmux new -s upgrade                       # ★★★★★
sudo apt update && sudo apt full-upgrade -y && sudo apt autoremove --purge -y
sudo dpkg --configure -a; systemctl --failed      # ★★★★ 兩個都要乾淨
mkdir -p /root/upgrade-$(date +%F) && cd "$_"
apt-mark showmanual > manual.txt; systemctl list-unit-files --state=enabled > services.txt
ss -tlnp > ports.txt; sudo tar czpf etc.tar.gz /etc          # ★★★★★
apt-cache policy | grep -E '^ [0-9]+ ' | grep -v ubuntu.com | awk '{print $2}' | sort -u > third-party.txt
cat third-party.txt                       # ★★★★★ 逐一確認 noble 有沒有支援
sudo find /etc -name '*.dpkg-*'           # ★★★ 先清乾淨
df -h /; sudo apt clean
# → 拍 VM 快照「before-24.04」            ★★★★★ 沒拍到這張快照就不要往下走

# ═══ D-Day：升級 ═══
sudo ufw allow 1022/tcp                   # ★★★★ 備援 sshd
sudo do-release-upgrade
# 設定檔衝突一律 N（保留），記下哪些檔案  ★★★★★
# 完成後 reboot

# ═══ D-Day：驗證 ═══
tmux new -s post
. /etc/os-release; echo "$VERSION"        # 24.04 ★★★
systemctl --failed                        # ★★★★★
comm -23 <(sort /root/upgrade-*/services.txt) <(systemctl list-unit-files --state=enabled | sort)
sudo find /etc -name '*.dpkg-dist' | while read -r f; do echo "== $f"; sudo diff -u "${f%.dpkg-dist}" "$f" | head -40; done
# 逐一決定合併

# 第三方庫：改 codename 重新啟用
sudo sed -i 's/jammy/noble/g' /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources 2>/dev/null
# ★★★★ 這個 sed 是「已經確認上游有 noble」之後才做的動作，不是先改再說；
#      上游沒有 noble 就把該來源留在停用狀態，硬改只會讓 apt update 一直噴錯
for f in /etc/apt/sources.list.d/*.distUpgrade; do sudo mv "$f" "${f%.distUpgrade}"; done 2>/dev/null
sudo apt update 2>&1 | grep -iE 'err|warn'    # ★★★★ 哪個庫還不支援 noble
apt policy nginx php8.3-fpm mysql-server        # ★★★★★ 版本與來源是否如預期

# 應用驗證
curl -sS -o /dev/null -w '%{http_code}\n' https://localhost/   # ★★★★ 期望 200/301，不是 502
sudo -u www-data php -v; mysql --version        # ★★★★
sudo ufw delete allow 1022/tcp                  # ★★★★ 救援埠用完就收
sudo apt autoremove --purge -y

# ═══ D+7：穩定一週後刪快照，更新文件 ═══
```

#### 驗收檢查表：每一項都要親手看過再簽 ★★★★

這張表就是變更單的「完成證明」。**任何一項打不了勾，就不要刪快照。**

| # | 檢查項 | 指令 | 通過標準 | 星級 |
| --- | --- | --- | --- | --- |
| 1 | 版本真的換了 | `. /etc/os-release; echo $VERSION_ID` | 顯示 `24.04` | ★★★ |
| 2 | 沒有失敗的 unit | `systemctl --failed` | `0 loaded units listed` | ★★★★★ |
| 3 | 服務數量沒短少 | `comm -23` 比對 `services.txt` | 輸出為空，或每一筆都能說明原因 | ★★★★ |
| 4 | 監聽埠沒短少 | `ss -tlnp` 比對 `ports.txt` | 對外服務的埠全部回來 | ★★★★★ |
| 5 | 設定檔差異都處理完 | `find /etc -name '*.dpkg-dist'` | 每個檔都已比對並刪除 `.dpkg-dist` | ★★★★ |
| 6 | 套件來源與版本如預期 | `apt policy <關鍵套件>` | 來源與版本號與升級計畫一致 | ★★★★ |
| 7 | DKMS 模組都建好 | `dkms status` | 全部 `installed`，沒有 `broken` | ★★★★ |
| 8 | 資料掛載點都在 | `df -h; mount \| grep <資料碟>` | 容量與掛載點與升級前相同 | ★★★★★ |
| 9 | 應用真的能用 | 實際打一次首頁／登入／寫入 | 業務流程走得完，不是只有 200 | ★★★★★ |
| 10 | 救援埠已收回 | `ss -tlnp \| grep 1022` | 沒有輸出 | ★★★★ |
| 11 | 排程有跑 | `journalctl -u cron -S -1h`／`systemctl list-timers` | 升級後至少跑過一輪且無錯 | ★★★ |
| 12 | 備份任務正常 | 手動觸發一次備份並確認產物 | 有新的備份檔且大小合理 | ★★★★★ |

> [!danger] ★★★★★ 第 12 項最容易被跳過，後果也最大
> 備份代理常常是自編或第三方套件庫來的，升級後最容易默默死掉。
> 它壞掉不會有人抱怨 —— 直到你需要還原的那一天，才發現最近一份備份停在升級前。
> **升級當天就手動跑一次備份並確認產物**，不要等排程。

> [!tip] ★★★★ PHP 版本跳級的處理
> 22.04 的 PHP 8.1 → 24.04 的 8.3。升級後 `php8.1-fpm` 套件消失、
> Nginx 的 `fastcgi_pass unix:/run/php/php8.1-fpm.sock` 指向不存在的 socket → 502。
> 用 ondrej PPA 固定版本（[[060-03-01-01-guide-PHP-安裝與多版本管理]]），或在升級前先在測試機確認應用相容 8.3。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★ `configure: error: X not found` | 缺 `-dev`/`-devel` 標頭檔 | `apt-file search` / `dnf provides` 找套件 |
| ★★ `make: *** No targets` | 沒先 `./configure`，或專案用 cmake/meson | 讀 README |
| ★★★ 裝了新版還是跑舊版 | PATH 順序或 hash 快取 | `type -a X`；`hash -r`；確認 prefix |
| ★★★ `cannot open shared object file` | 函式庫路徑未登記 | `sudo ldconfig`；自訂路徑加 `ld.so.conf.d` |
| ★★★ `make uninstall` 不存在 | 專案沒提供 | 用安裝紀錄／時間標記手動刪；下次用 checkinstall/stow |
| ★★★ 套件升級後自編版本被覆蓋 | 裝到 `/usr` | 一律 `/usr/local` 或 `/opt` |
| ★★ `do-release-upgrade` 說沒有新版 | 新 LTS 的 .1 尚未釋出，或 `Prompt=never` | 等 .1；檢查 `/etc/update-manager/release-upgrades` |
| ★★★ 升級中 SSH 斷線 | 正常現象 | `ssh -p 1022`，`tmux attach` |
| ★★★★ 升級後某服務版本變了 | 第三方庫被停用，退回發行版版本 | 改 codename 重新啟用，`apt policy` 確認 |
| ★★★★ 升級後 502 | PHP 版本跳級、socket 路徑變 | 改 Nginx 設定或固定 PHP 版本 |
| ★★★★★ 升級後 SSH 連不上 | 設定檔衝突時選了套件版本 | 主控台進去還原 `sshd_config`（`/etc` 備份） |
| ★★★ `leapp` 報 inhibitor | 必須先解決的阻礙 | 依 `leapp-report.txt` 逐條處理 |
| ★★★★ 升級後 ZFS/NVIDIA 消失 | DKMS 未為新核心建置 | `dkms autoinstall`；確認 headers |
| ★★★★★ 想降回舊版 | 不支援 | 只能還原快照／備份 |
| ★★★★ 升級停在一半、`apt` 從此不能用 | dpkg 資料庫留在半設定狀態 | 見下方排查流程 B |
| ★★★★ `/boot` 空間不足，新核心裝不上 | 舊核心堆積 | 清舊核心後 `apt --fix-broken install`，見流程 B【5】 |
| ★★★ 自編服務升級後開機不啟動 | unit 檔在 `/usr/local`，或被 `.dpkg-dist` 蓋掉 | `systemctl cat` 看實際路徑，見流程 A【5】 |

### 排查流程 A：自編軟體「裝好了，跑的卻不是它」 ★★★★

症狀是「`make install` 明明成功，`foo --version` 卻還是舊版」或「服務起不來」。
**照順序做，不要跳**——每一步都在排除一種可能，跳過就會在錯的地方猜。

**【1】確認 shell 到底執行到哪一個檔案 ★★★★**

```bash
hash -r                      # ★★★★ 先清掉 shell 記住的舊路徑，這一步最常被忘記
type -a nginx
```

預期輸出：

```text
nginx is /usr/local/sbin/nginx     # ★★★ 你自編的，排在前面
nginx is /usr/sbin/nginx           # 套件版
```

只印出一行套件版的路徑，代表 `--prefix` 根本沒裝到你以為的地方，直接跳到【6】。

**【2】確認這個檔案是誰裝的 ★★★**

```bash
dpkg -S /usr/local/sbin/nginx        # RHEL: rpm -qf /usr/local/sbin/nginx
```

預期輸出：

```text
dpkg-query: no path found matching pattern /usr/local/sbin/nginx
```

★★★ 這句「no path found」是**正常且正確**的——它證明這個檔案不歸套件管理員管，
也就證明 `apt upgrade` 永遠不會更新它。反過來說，如果它回報屬於某個套件，
表示你把東西裝進了套件的地盤（`--prefix=/usr`），下次套件升級就會被蓋掉。

**【3】確認動態函式庫都找得到 ★★★★**

```bash
ldd /usr/local/sbin/nginx | grep -i 'not found'
```

預期輸出（正常時什麼都不印）：

```text
	libpcre2-8.so.0 => not found     # ★★★★ 有輸出就是這裡卡住，程式根本起不來
```

```bash
sudo ldconfig && ldconfig -p | grep libpcre2-8
```

```text
	libpcre2-8.so.0 (libc6,x86-64) => /usr/local/lib/libpcre2-8.so.0
```

**【4】確認編譯選項真的帶進去了 ★★★**

```bash
/usr/local/sbin/nginx -V 2>&1 | tr ' ' '\n' | grep -- '--with'
```

```text
--with-http_ssl_module
--with-http_v2_module
```

少了你要的模組，代表 `./configure` 當時就沒過——回去看 `config.log`，
不要重跑 `make install` 想「再裝一次就好」。

**【5】確認 systemd 服務指到哪一個執行檔 ★★★★**

`systemd` 不讀你的 `PATH`，也不讀 `/etc/profile.d/`。**在終端機跑得起來不代表服務跑得起來。**

```bash
systemctl cat nginx | grep -E '^(ExecStart|EnvironmentFile)'
```

```text
ExecStart=/usr/sbin/nginx -g 'daemon on; master_process on;'   # ★★★★ 指的是套件版，不是你編的
```

```bash
sudo systemctl edit nginx        # 用 drop-in 覆寫，不要直接改 /lib/systemd/system 底下的檔
```

```ini
[Service]
ExecStart=
ExecStart=/usr/local/sbin/nginx -g 'daemon on; master_process on;'
```

★★★★ `ExecStart=` 空一行再寫新值是必要的——不清空的話 systemd 會當成「兩個
ExecStart 依序執行」而不是取代。改完 `sudo systemctl daemon-reload` 再 `restart`。

**【6】以上都對還是不對，回頭驗安裝位置 ★★★**

```bash
grep -m1 'prefix' config.log            # 當初 configure 的參數
sudo find /usr/local /opt -name 'nginx' -newer /root/before-install-marker 2>/dev/null
```

找不到任何新檔案，就是 `make install` 其實失敗了（或裝到了另一個 prefix），
而你只看了 `make` 的輸出沒看 `install` 的。

### 排查流程 B：升級停在一半，`apt` 從此不能用 ★★★★★

`do-release-upgrade` 中途斷線、斷電、或空間不足時，系統會停在
「一部分套件是新版、一部分是舊版、dpkg 資料庫是半設定狀態」。
**這是最危險的狀態：系統還開得起來，但任何一次 `apt install` 都可能讓它更糟。**

> [!danger] ★★★★★ 這個階段的第一原則：不要嘗試降級、不要 `rm` dpkg 的檔案
> `dpkg --force-*` 系列與手動刪 `/var/lib/dpkg/info/` 底下的檔案，
> 是把「可修復」變成「只能重灌」的最短路徑。有快照就直接還原快照，
> 下面的流程是**沒有快照時**的補救，不是快照的替代品。

**【1】先確認升級程序停在哪一階段 ★★★★**

```bash
sudo tail -40 /var/log/dist-upgrade/main.log      # RHEL: /var/log/leapp/
```

```text
2026-08-29 10:41:22,331 DEBUG Installing 'libc6' ...
2026-08-29 10:43:05,904 ERROR pm_error: dpkg: error processing package php8.1-fpm
```

★★★★ 這一行決定後面怎麼做：卡在 `libc6` 之類的核心套件要格外小心，
卡在單一應用套件（如上例的 `php8.1-fpm`）通常可以繞過。

**【2】列出所有不正常的套件 ★★★★★**

```bash
dpkg -l | grep -v '^ii' | grep -E '^[a-z]{2}'
```

```text
iU  php8.1-fpm     8.1.2-1ubuntu2   amd64   已解開但未設定       # ★★★★ 要 configure
iF  libfoo1        1.2-3            amd64   設定失敗             # ★★★★ 要看 postinst 為什麼失敗
rc  old-package    0.9-1            amd64   已移除、設定檔還在   # ★ 無害
```

★★★★★ 第一欄兩個字母：第一個是「期望狀態」，第二個是「實際狀態」。
只有 `ii` 是正常的，`rc` 無害，**其餘每一個都要處理完才能繼續升級**。

**【3】讓 dpkg 把沒做完的設定做完 ★★★★**

```bash
sudo dpkg --configure -a
```

```text
Setting up php8.1-fpm (8.1.2-1ubuntu2) ...
Setting up libfoo1 (1.2-3) ...
```

★★★★ 有錯誤訊息就**逐條讀**，多半是設定檔語法、目錄權限、或相依的服務起不來。
先修那個根因，再回來重跑這行；不要直接跳到 `--force`。

**【4】補齊被打斷的相依關係 ★★★★**

```bash
sudo apt --fix-broken install
sudo apt update && sudo apt full-upgrade
```

```text
0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.   # ★★★★ 這行才算收工
```

**【5】空間不足是最常見的根因，尤其 `/boot` ★★★★**

```bash
df -h / /boot /var
```

```text
Filesystem      Size  Used Avail Use% Mounted on
/dev/sda2       472M  461M     0 100% /boot        # ★★★★ 100% = 新核心裝不進去
```

```bash
sudo apt clean                                     # 先清最安全的
dpkg -l 'linux-image-*' | awk '/^ii/{print $2}'    # 列出所有核心
uname -r                                           # ★★★★★ 目前跑的這顆絕對不能刪
sudo apt remove --purge linux-image-5.15.0-71-generic   # 只刪確定沒在用的舊核心
sudo apt --fix-broken install
```

> [!danger] ★★★★★ 刪核心前一定要先 `uname -r`
> 刪掉正在執行的那顆核心，或把 `/boot` 裡最後一顆可開機的核心刪掉，
> 機器下次重開就進不了系統，只能用 Live 環境救（見
> [[020-01-25-guide-Linux-開機流程與GRUB救援]]）。**至少保留兩顆能開機的核心。**

**【6】把升級跑完 ★★★★**

```bash
tmux new -s upgrade-resume        # ★★★★ 一樣要在 tmux 裡
sudo do-release-upgrade
```

★★★ 如果它回報「已經是最新版」但 `/etc/os-release` 還是舊版，代表套件換了但版本識別
沒更新完，此時走 `sudo apt full-upgrade` 把剩下的套件收完，再檢查 `/etc/os-release`。

**【7】修不回來就停手 ★★★★★**

★★★★★ 花超過一個維護窗口還沒修好，就**還原快照或重建**。
在半升級狀態的機器上繼續試，只會讓「可還原」的時間窗一直縮短，
而且期間跑在上面的服務隨時可能出現無法解釋的行為。

---

## 安全性注意事項

> [!danger] ★★★★★ 原始碼一定要驗證來源
> `wget` 來的 tarball 要比對官方公布的 SHA256 或 GPG 簽章。
> 映像站被入侵、DNS 被劫持時，你編譯並以 root 安裝的就是後門。
>
> ★★★★★ 具體後果不是抽象的：`make install` 是以 root 執行的，
> 被動過手腳的 `Makefile` 可以在安裝階段新增使用者、寫入 `authorized_keys`、
> 埋 systemd timer。**這一切都發生在你「還沒開始用這個軟體」之前。**
> ★★★★ 只比對同一個網站上的 SHA256 是不夠的——站被入侵時檔案與雜湊值會一起被換掉；
> 要驗的是**簽章**，而且公鑰要從別的管道取得。

> [!danger] ★★★★★ 自編軟體沒有自動安全更新
> 這是原始碼安裝最大的長期風險。列入 `LOCAL-INSTALLS.md` 並每月對照上游公告，
> 做不到就用套件。
>
> ★★★★★ 真實的破口長這樣：三年前為了一個功能自編了 Nginx 裝在 `/usr/local`，
> 之後每次 `apt upgrade` 都顯示「系統已是最新」，弱點掃描報告也乾淨（掃描器讀的是套件清單）。
> **它就這樣帶著三年份的 CVE 對外服務，而所有自動化報表都說它沒問題。**
> ★★★★ `checkinstall` 至少讓它出現在 `dpkg -l` 裡，弱點掃描與資產盤點才看得到它。

> [!danger] ★★★★★ 升級中開的臨時通道，用完就要關
> `ufw allow 1022/tcp` 的備援 sshd、為了排錯暫時放行的資料庫埠、
> 為了裝套件暫時關掉的防火牆——這些都是「本來要收、後來忘了」的典型。
> ★★★★★ 一個沒人記得的 1022 埠，跑的是升級當下那版 sshd，
> 之後的安全更新不一定會讓它重啟。**收尾動作寫進變更單的檢查項，不要靠記憶。**

> [!warning] ★★★★ 升級是變更，要走變更管理
> 大版本升級影響整台機器的每個服務。事前的相容性測試、變更窗口、回退計畫、
> 事後驗證都要有（[[100-02-08-guide-維運-變更管理流程]]）。
> 「反正有快照」不是不做測試的理由——還原快照也是停機。
> ★★★★ 而且快照只還原這台機器：升級後這幾小時內寫進資料庫、收到的訂單、
> 上傳的檔案，還原快照後**全部消失**。快照能救系統，救不了資料。

> [!warning] ★★★★ 升級會改掉安全設定的預設值
> 新版本常見的變動：sshd 移除舊的金鑰交換與加密演算法、OpenSSL 提高預設安全等級、
> 防火牆或 `nftables` 後端更換。
> ★★★★ 兩個方向都要檢查：**變嚴**會讓舊設備或舊客戶端突然連不上；
> **變鬆**（例如你選了「安裝套件版本」而蓋掉自己強化過的設定）則是資安事件。
> 升級後把強化基準重跑一次驗證，不要假設設定還在。

> [!tip] ★★★ 升級是清理攻擊面的機會
> 升級後檢查 `apt-mark showmanual` 與 `systemctl list-unit-files --state=enabled`，
> 把多年累積、已經沒人用的套件與服務移除。重建遷移在這點上天生更乾淨。

---

## 速查表

### 原始碼安裝

| 指令 | 說明 |
| --- | --- |
| ★★ `apt install build-essential` / `dnf groupinstall "Development Tools"` | 工具鏈 |
| ★★★★★ `gpg --verify` / `sha256sum -c` | **驗證來源** |
| ★★ `./configure --help` | 看選項 |
| ★★★★ **`./configure --prefix=/usr/local`** | **裝到正確位置** |
| ★★ `make -j$(nproc)` / `make check` | 編譯 / 測試 |
| ★★★ `make -n install` | 預覽會裝哪些檔案 |
| ★★★ `apt-file search 檔案` / `dnf provides '*/檔案'` | 找缺的 dev 套件 |
| ★★★ `apt build-dep X` / `dnf builddep X` | 借建置相依 |
| ★★★ `sudo ldconfig` | 登記新函式庫 |
| ★★★★ `sudo checkinstall` | 取代 `make install`，產生可移除的套件 |
| ★★★ `stow X` / `stow -D X` | 啟用 / 停用 stow 管理的版本 |
| ★★★★ `type -a X` | 確認跑到哪個版本 |
| ★★★ `hash -r` | 清掉 shell 記住的舊路徑（換版後第一件事） |
| ★★★ `ldd 執行檔 \| grep 'not found'` | 找出缺哪個 `.so` |
| ★★★★ `systemctl cat 服務 \| grep ExecStart` | 確認服務跑的是哪個執行檔 |
| ★★★★ `dpkg -S 路徑` / `rpm -qf 路徑` | 這個檔案歸不歸套件管 |

### 系統升級 ★★★★★

| 步驟 | Ubuntu | RHEL 系 |
| --- | --- | --- |
| ★★★★ 記錄現況 | `apt-mark showmanual`、`dpkg-query -W`、`systemctl list-unit-files`、`ss -tlnp`、tar `/etc` | 同（`dnf history userinstalled`、`rpm -qa`） |
| ★★★★★ 清第三方庫 | `apt-cache policy` 找非 ubuntu.com | `dnf repolist` |
| ★★★★ 更新到最新 | `apt full-upgrade` | `dnf upgrade` |
| ★★★★★ 快照 | 必要 | 必要 |
| ★★★★★ 在 tmux 裡 | 必要 | 必要（RHEL 需主控台） |
| ★★★★ 預檢 | — | **`leapp preupgrade`** |
| ★★★★ 執行 | `do-release-upgrade` | `leapp upgrade` + reboot |
| ★★★★★ 設定檔衝突 | 選 N 保留，之後看 `.dpkg-dist` | 之後看 `.rpmnew` |
| ★★★★ 備援 SSH | 1022 埠 | — |
| ★★★★ 驗證 | `systemctl --failed`、服務／埠 diff、`.dpkg-dist`、`dkms status` | 同 |
| ★★★★★ 回退 | 還原快照 | 還原快照 |
| ★★★★ 卡在半升級 | `dpkg -l \| grep -v '^ii'` → `dpkg --configure -a` → `apt --fix-broken install` | 同（`rpm -Va`、`dnf distro-sync`） |
| ★★★★ 收尾 | 關掉 1022、刪快照（穩定一週後）、更新文件 | 同（無 1022） |

---

## 練習題

> [!question]- 練習 1：用 stow 安裝並切換兩個版本
> 從原始碼裝一個小工具（如 `htop` 或 `tmux`）兩個版本到 stow，練習切換與移除。
>
> **解答**
>
> ```bash
> sudo apt install -y stow build-essential libncursesw5-dev
> for v in 3.3.0 3.4.0; do
>   wget -q https://github.com/htop-dev/htop/releases/download/$v/htop-$v.tar.xz
>   tar xf htop-$v.tar.xz && cd htop-$v
>   ./configure --prefix=/usr/local/stow/htop-$v >/dev/null && make -j"$(nproc)" >/dev/null && sudo make install >/dev/null
>   cd ..
> done
> cd /usr/local/stow && sudo stow htop-3.3.0 && htop --version
> sudo stow -D htop-3.3.0 && sudo stow htop-3.4.0 && htop --version
> type -a htop          # /usr/local/bin/htop 是符號連結，套件版（若有）在 /usr/bin
> sudo stow -D htop-3.4.0; sudo rm -rf /usr/local/stow/htop-*
> ```
> ★★★ 重點：`/usr/local/bin/htop` 只是連結，切換是原子的，移除不留殘骸。
> 注意 `type -a htop` 的輸出順序——這是驗收「切換有沒有真的生效」的方法。

> [!question]- 練習 2：模擬升級前置檢查並找出會失敗的項目
> 在一台裝了 PPA 與自編軟體的練習機上執行前置檢查清單，列出哪些項目會讓升級出問題。
>
> **解答**
>
> 執行「前置檢查清單」第 2、3 項：
> ```bash
> apt-cache policy | grep -E '^ [0-9]+ ' | grep -v ubuntu.com | awk '{print $2}' | sort -u
> ls /usr/local/bin /opt; dkms status
> ```
> 典型發現：`ppa.launchpadcontent.net/ondrej/php`（新 codename 要確認有支援）、
> `download.docker.com`（要改 codename）、`/usr/local/bin/nginx`（自編，會遮住套件版，升級後不會更新）、
> DKMS 的 zfs（新核心要重建）。
> ★★★★ 每一項寫進升級計畫的「處理方式」欄，這份清單就是變更申請的附件。
> ★★★★ 沒有這份清單，升級後你只會知道「有東西怪怪的」，說不出「少了哪一項」。

> [!question]- 練習 3：決定原地升級還是重建
> 三台機器：(a) 跑 Nginx+PHP 的 VM，22.04，有快照；(b) 實體檔案伺服器，20.04，10TB 資料，無法快照；(c) 18.04 的舊 Web 機。各該怎麼做？
>
> **解答**
>
> - **(a) 原地升級**：VM 有快照、單一大版本、服務單純。先在複製的 VM 試一次。
> - **(b) 重建遷移**：實體機無快照 = 沒回退路徑；10TB 資料用 rsync 預同步 + 切換時增量（[[060-01-06-02-guide-rsync-同步與備份]]），舊機保留到確認無誤。
> - **(c) 重建遷移**：18.04→24.04 跨三個 LTS，原地要升三次且每次都可能失敗；重建反而快且乾淨，順便清掉六年的殘渣。
>
> ★★★★★ 原則：**沒有回退路徑就不原地升級；跨兩個以上大版本就重建。**

---

## 小測驗

Q1. 原始碼安裝的三個代價？
Q2. `--prefix=/usr` 與 `--prefix=/usr/local` 各會發生什麼？
Q3. `configure: error: OpenSSL not found` 但系統明明有 OpenSSL，缺的是什麼？怎麼找？
Q4. checkinstall 與 stow 各解決什麼問題？各自的限制？
Q5. 裝到 `/usr/local/lib` 的函式庫執行時找不到，該做什麼？為什麼不用 `LD_LIBRARY_PATH`？
Q6. 原地升級與重建遷移怎麼選？兩個判斷準則？
Q7. 升級失敗的頭號原因是什麼？`do-release-upgrade` 對它做了什麼、之後你要做什麼？
Q8. 升級中設定檔衝突（特別是 `sshd_config`）該選哪個？為什麼？
Q9. `do-release-upgrade` 透過 SSH 執行時斷線怎麼接回？前提是什麼？
Q10. Linux 能「降級」回舊版嗎？這對升級前的準備意味著什麼？

> [!question]- 測驗答案
> **Q1.** ★★★★ 不會收到安全更新、無法乾淨移除（常沒 `make uninstall`）、與套件版本衝突（見「三個代價」）。
>   第一點是四星：它讓弱點掃描與資產盤點都看不到這個軟體。
> **Q2.** ★★★★ `/usr` 會覆蓋套件檔案並在升級時被蓋回；`/usr/local` 在 PATH 前面會遮住套件版（設計如此，但要用 `type -a` 確認）。
> **Q3.** ★★★ 缺標頭檔（`libssl-dev` / `openssl-devel`）；`apt-file search openssl/ssl.h` 或 `dnf provides '*/openssl/ssl.h'`。
> **Q4.** ★★★ checkinstall 把 `make install` 打成可移除的套件（不處理相依宣告）；stow 讓多版本並存與秒切換（要 `--prefix` 到 stow 目錄）。
> **Q5.** ★★★★ `sudo ldconfig`（自訂路徑先加 `ld.so.conf.d`）；`LD_LIBRARY_PATH` 是除錯用，永久設定會造成安全與相依混亂——它會讓可寫目錄裡的同名 `.so` 搶先被載入。
> **Q6.** ★★★★★ 沒有快照／回退路徑就不原地升級；跨兩個以上大版本就重建。VM 有快照且服務單純才原地。
> **Q7.** ★★★★★ 第三方套件庫在新 codename 不相容；升級程式會自動停用它們；升級後要逐一改 codename 重新啟用並 `apt policy` 確認版本。
> **Q8.** ★★★★★ 選 N 保留自己的，之後用 `.dpkg-dist` 比對合併；對 `sshd_config` 選套件版本可能改掉 Port/認證方式而鎖死自己。
> **Q9.** ★★★★ `ssh -p 1022 host` 再 `tmux attach`；前提是在 tmux 裡執行且防火牆放行 1022。驗證完要把 1022 收掉。
> **Q10.** ★★★★★ 不能，`apt`/`dnf` 都不支援整系統降級；所以快照或已驗證的完整備份是升級的前提，沒有就沒有回退路徑。
>   補一句：快照救得了系統，救不了升級後這段時間寫進去的資料。

---

## 延伸閱讀

- [[020-01-14-guide-Linux-套件管理]] — 第三方套件庫、pinning、`.dpkg-dist`
- [[020-01-25-guide-Linux-開機流程與GRUB救援]] — 升級後開不了機的處理
- [[020-01-20-guide-Linux-環境變數與設定檔]] — PATH 順序與 `type -a`
- [[020-01-04-cmd-Linux-檔案系統與目錄結構]] — `/usr/local` 與 `/opt` 的定位
- [[020-02-03-01-svc-標準化-新機建置標準流程]] — 重建遷移的標準流程
- [[100-02-08-guide-維運-變更管理流程]] — 升級的變更管理
- [[100-02-04-guide-維運-每月維護作業]] — 自編軟體的安全公告追蹤
- [[060-03-01-01-guide-PHP-安裝與多版本管理]] — 升級時 PHP 版本跳級的處理
- `./configure --help` / `man 8 stow` / `man 8 do-release-upgrade` / `man 1 leapp`
