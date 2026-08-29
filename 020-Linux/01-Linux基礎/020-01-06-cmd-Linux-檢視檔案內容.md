---
title: "檢視檔案內容"
desc: "cat less head tail watch 與即時追蹤日誌的方法"
aliases: [cat, less, head, tail, tail -f]
tags: [群組/Linux, linux/基礎, 主題/檔案操作]
category: Linux基礎
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[020-01-05-cmd-Linux-路徑導覽與檔案操作]]"]
updated: 2026-08-29
---

# 檢視檔案內容

> [!abstract] 這篇你會學到
> - ★★ 依檔案大小與用途選對工具，不要再用 `cat` 開 2GB 的日誌
> - ★★★ 把 `less` 用熟——它是你查日誌時最常待的地方
> - ★★★★ 分清楚 `tail -f` 與 `tail -F`，避免日誌輪替後追蹤失效——追錯了會讓你在事故現場誤判「系統很安靜」
> - ★★ 直接讀壓縮過的日誌，不用先解壓縮
> - ★★ 用 `watch` 觀察會變動的輸出
> - ★★★★★ 知道存取日誌裡可能躺著明文 token 與個資，整份外流出去就是資安事件

## 前置知識

- [[020-01-05-cmd-Linux-路徑導覽與檔案操作]]

---

## 觀念說明

### 選對工具

| 情境 | 工具 | 理由 |
| --- | --- | --- |
| ★ 小檔案（幾十行） | `cat` | 一次全印，最快 |
| ★★★ 大檔案、要翻閱搜尋 | **`less`** | 分頁、可搜尋、不佔記憶體 |
| ★ 極簡環境沒有 `less` | `more` | 功能少但幾乎一定存在 |
| ★ 只看開頭 | `head` | 看設定檔前幾行、CSV 標題 |
| ★★★ 只看結尾 | `tail` | **看日誌最新內容** |
| ★★★★ 即時追蹤 | `tail -F` | 日誌一有新行就顯示 |
| ★★ 壓縮檔 | `zcat` `zless` `zgrep` | 不用先解壓縮 |
| ★★ 週期性重跑指令 | `watch` | 觀察數值變化 |
| ★★★ systemd 服務日誌 | `journalctl` | 見 [[020-01-19-guide-Linux-日誌系統]] |

> [!danger] ★★★ 不要 `cat` 大檔案
> `cat access.log` 在一個 2GB 的日誌上會把終端機刷爆，
> 而且中斷（`Ctrl+C`）之前你什麼也做不了。
> **超過幾百行就用 `less`。**
>
> 更糟的是 `cat` 二進位檔案——終端機會收到控制字元變成亂碼。
> 真的發生了就執行 `reset` 修復。
>
> ★★★ 事故當下你在跟時間賽跑。多花三十秒等終端機吐完 2GB，
> 或被亂碼逼到得重開一條連線，都是本來可以不用付的代價。

---

## 基礎操作

### ★★ `cat`：串接與輸出

`cat` 的名字來自 **concatenate**（串接），它的本意是把多個檔案接起來：

```bash
cat file1.txt file2.txt > combined.txt   # ★★★★ 輸出檔名不可與來源同名，`>` 會先把檔案清空
```

常用選項：

```bash
cat -n file.txt        # ★ 顯示行號
cat -b file.txt        # ★ 顯示行號，但跳過空行
cat -A file.txt        # ★★★ 顯示所有看不見的字元 —— 排查設定檔的第一招
cat -s file.txt        # ★ 連續空行壓縮成一行
```

**`cat -A` 是排查「看起來一樣卻不能動」的利器**：

```bash
printf 'server_name example.com;\t \r\n' > test.conf
cat -A test.conf       # ★★★ 把 Tab、CR、行尾空白全部逼出來
```

```
server_name example.com;^I $^M$
```

| 符號 | 代表 |
| --- | --- |
| ★ `$` | 行尾（Unix 換行 LF） |
| ★★★★ `^M$` | **Windows 換行 CRLF** ← 最常見的問題 |
| ★★ `^I` | Tab 字元 |
| ★★★ 行尾的空白 | 出現在 `$` 之前 |

> [!tip] ★★★★ 設定檔「明明沒錯卻讀不到」多半是 CRLF
> 在 Windows 編輯過的設定檔或腳本，換行是 `\r\n`。
> Linux 會把 `\r` 當成內容的一部分，於是：
> - ★★★★ 腳本報錯 `bad interpreter: /bin/bash^M`（排程腳本半夜靜靜失敗就是這樣來的）
> - ★★★★ 設定值變成 `example.com\r`，比對永遠失敗
>
> 檢查與修復：
> ```bash
> file script.sh                    # ★★★ 一眼看出 "with CRLF line terminators"
> sudo apt install -y dos2unix
> dos2unix script.sh
> # 或用 sed
> sed -i 's/\r$//' script.sh
> ```

> [!tip] ★★ 別做 UUOC（Useless Use of Cat）
> ```bash
> cat file.txt | grep error      # ✗ 多開一個程序
> grep error file.txt            # ✓ 直接讀
> grep error < file.txt          # ✓ 也可以
> ```
> 不是效能問題（差異很小），而是**多一層管線就多一層可能出錯的地方**，
> 而且 `grep` 直接讀檔案時能顯示檔名、支援 `-r` 遞迴等功能。

`tac` 是 `cat` 反過來（反向輸出）：

```bash
tac /var/log/syslog | head -20     # ★★ 看最後 20 行，但由新到舊排列
```

### ★★★ `less`：查日誌的主場

```bash
less /var/log/nginx/access.log
```

**必記的操作**：

| 按鍵 | 作用 |
| --- | --- |
| ★ `空白` / `f` | 下一頁 |
| ★★ `b` | 上一頁 |
| ★ `j` / `k` | 下一行 / 上一行（同 Vim） |
| ★★ `g` / `G` | 跳到檔頭 / 檔尾 |
| ★★★ `/關鍵字` | 向下搜尋 |
| ★★ `?關鍵字` | 向上搜尋 |
| ★★★ `n` / `N` | 下一個 / 上一個比對 |
| ★★★ `&關鍵字` | **只顯示含關鍵字的行**（過濾！） |
| ★★ `-N` | 切換行號顯示 |
| ★★ `-S` | 切換長行截斷（不換行） |
| ★★★★ `F` | **進入追蹤模式**（等同 `tail -f`），`Ctrl+C` 離開 |
| ★ `v` | 用 `$EDITOR` 開啟目前檔案 |
| ★ `q` | 離開 |

> [!tip] ★★★ `&` 過濾功能幾乎沒人知道，但超好用
> 在 `less` 裡按 `&` 然後輸入 `500`，畫面就只剩下含 `500` 的行。
> 再按 `&` 輸入空字串就取消過濾。
>
> 這比退出去重打 `grep 500 access.log | less` 快得多，
> 而且可以反覆切換不同條件。

> [!tip] ★★★ `less` 的 `F` 模式比 `tail -f` 好用
> `tail -f` 只能一直往下看。`less` 的 `F` 模式可以：
> 1. 按 `F` 開始追蹤
> 2. 看到可疑的東西按 `Ctrl+C` 停下來
> 3. 往回翻、搜尋、過濾
> 4. 再按 `F` 繼續追蹤
>
> ```bash
> less +F /var/log/nginx/error.log    # ★★★★ 直接以追蹤模式開啟，而且它會處理輪替
> ```

長行處理（access log 常常一行很長）：

```bash
less -S /var/log/nginx/access.log    # ★★ 不換行，用 → ← 左右捲動
```

顯示彩色輸出：

```bash
journalctl -u nginx | less -R        # ★★ -R 保留 ANSI 色碼
```

> [!tip] ★★★ 設定 `LESS` 環境變數一勞永逸
> 在 `~/.bashrc` 加上：
> ```bash
> export LESS='-R -i -M -j5'
> ```
> | 選項 | 作用 |
> | --- | --- |
> | ★★ `-R` | 保留顏色 |
> | ★★★ `-i` | 搜尋時忽略大小寫（除非你輸入大寫） |
> | ★★ `-M` | 顯示更詳細的狀態列（行號、百分比） |
> | ★★★ `-j5` | 搜尋命中時，把該行顯示在第 5 行而非最上方（看得到上下文） |
>
> 設定之後，`man`、`git log`、`systemctl status` 都會跟著變好用，
> 因為它們預設都用 `less` 當分頁器。

### ★ `more`：最低限度的分頁器

`more` 是比 `less` 更古老的分頁器，功能少很多，但**在極簡環境裡可能只有它**。

```bash
more /var/log/syslog     # ★★ 大日誌不要這樣做，某些實作會整份讀進記憶體
more -10 file.txt        # ★ 一次顯示 10 行
cat file.txt | more      # ★ 也能接管線
```

| 按鍵 | 作用 |
| --- | --- |
| ★ `空白` | 下一頁 |
| ★ `Enter` | 下一行 |
| ★★ `/關鍵字` | 向下搜尋 |
| ★ `n` | 下一個比對 |
| ★ `v` | 用 `$EDITOR` 開啟 |
| ★ `q` | 離開 |

`more` 與 `less` 的差別：

| | `more` | `less` |
| --- | --- | --- |
| ★★ 向上翻頁 | **舊版不行**（GNU 版可用 `b`） | ✅ `b`、`k`、`↑` |
| ★★★ 讀取方式 | 可能整份讀進記憶體 | **邊看邊讀，開 10GB 也秒開** |
| ★★ 到檔尾 | **自動離開** | 停在原地等你按 `q` |
| ★★★ 追蹤模式 | ❌ | ✅ `F` |
| ★★ 過濾 | ❌ | ✅ `&關鍵字` |
| ★★ 何處可見 | 幾乎所有系統，含最小容器映像 | 需要 `less` 套件 |

> [!tip] ★ 「less is more」這句話的由來
> `less` 的名字就是在調侃 `more`：它能做的比 `more` 更多。
> **日常一律用 `less`**，只有在容器或救援環境裡發現沒有 `less` 時才退回 `more`。
>
> 確認手上有什麼：
> ```bash
> command -v less more most 2>/dev/null
> ```

> [!warning] ★★ `more` 到檔尾會自動離開，內容就消失了
> 在小檔案上 `more` 會直接把內容印完然後結束，等同 `cat`。
> 想停在檔尾檢視就必須用 `less`。
>
> 另外 `more` 在某些實作上會把整個檔案讀進記憶體，
> **對超大日誌檔不要用 `more`**。

### ★★ `head` 與 `tail`

```bash
head file.txt              # ★ 前 10 行
head -n 20 file.txt        # ★★ 前 20 行
head -20 file.txt          # ★ 同上（簡寫）
head -c 100 file.bin       # ★★★ 前 100 位元組，探二進位檔的安全做法

tail file.txt              # ★ 後 10 行
tail -n 50 file.txt        # ★★★ 後 50 行，查日誌最常用
tail -n +100 file.txt      # ★★ 從第 100 行開始到結尾（注意有 +）
```

> [!tip] ★★ `tail -n +N` 是跳過標頭的標準做法
> ```bash
> tail -n +2 data.csv       # 跳過 CSV 標題列
> ```

**組合起來取中間某段**：

```bash
sed -n '100,120p' file.txt          # ★★★ 第 100～120 行（推薦）
head -120 file.txt | tail -21       # ★ 同樣結果
```

### ★★★★ `tail -f` vs `tail -F`（重要）

```bash
tail -f /var/log/nginx/access.log     # ★★★★ 追蹤這個「檔案描述符」—— 輪替後就啞了
tail -F /var/log/nginx/access.log     # ★★★★ 追蹤這個「檔名」—— 一律用這個
```

差別在**日誌輪替發生的時候**：

| | `-f` | `-F` |
| --- | --- | --- |
| ★★★ 追蹤對象 | 開啟時的那個 inode | 檔案名稱 |
| ★★★★ 輪替後 | **繼續看舊檔案，永遠不再有新內容** | 自動重新開啟新檔案 |
| ★★★ 檔案暫時不存在 | 報錯結束 | 等待它出現 |

```mermaid
sequenceDiagram
    participant T as tail
    participant F as access.log (inode 100)
    participant N as access.log (inode 200)
    T->>F: -f 開啟並追蹤 inode 100
    Note over F,N: logrotate 執行：<br/>access.log → access.log.1<br/>建立新的 access.log
    F-->>T: -f 仍看著 inode 100（已改名為 .1，不再有新內容）
    N-->>T: -F 偵測到檔名對應的 inode 變了，重新開啟
```

> [!warning] ★★★★ 用 `-f` 追日誌追了半小時卻沒動靜，多半是這個原因
> 半夜輪替之後 `tail -f` 就啞了，你以為系統很安靜，其實日誌一直在寫。
>
> **養成一律用 `-F` 的習慣**，它沒有任何缺點。
> 或者用 `less +F`（它也會處理輪替）。
>
> ★★★★ 這件事的代價不是「少看幾行日誌」，而是**在事故排除的當下做出錯誤結論**：
> 你回報「錯誤已經停了」，其實它一直在噴，只是你手上那條 `tail -f` 早就跟現實脫節。

同時追蹤多個檔案：

```bash
tail -F /var/log/nginx/{access,error}.log
```

```
==> /var/log/nginx/access.log <==
203.0.113.5 - - [27/Aug/2026:10:22:01 +0800] "GET / HTTP/1.1" 200 1234

==> /var/log/nginx/error.log <==
2026/08/27 10:22:03 [error] 891#891: *12 open() "/var/www/x" failed
```

搭配 `grep` 即時過濾：

```bash
tail -F /var/log/nginx/access.log | grep --line-buffered " 50[0-9] "   # ★★★ --line-buffered 不能省
```

> [!warning] ★★★ 管線裡的 `grep` 要加 `--line-buffered`
> 沒加的話 `grep` 會把輸出緩衝到 4KB 才吐出來，
> 你會覺得「怎麼都沒反應」，然後突然一次噴出一大堆。
> `--line-buffered` 讓它逐行輸出。
>
> ★★★ 同理，`awk` 用 `fflush()`、`sed` 用 `-u`（unbuffered）；通用解法是 `stdbuf -oL <指令>`。

### ★★ 直接讀壓縮檔

輪替後的日誌通常是 `.gz`。不用解壓縮：

```bash
zcat  /var/log/nginx/access.log.2.gz              # ★★ 等同 cat
zless /var/log/nginx/access.log.2.gz              # ★★★ 等同 less
zgrep "500" /var/log/nginx/access.log.*.gz        # ★★★ 等同 grep，可用萬用字元
```

> [!tip] ★★★ 跨越輪替檔案搜尋
> 要在「所有歷史日誌」裡找東西：
> ```bash
> # 同時處理未壓縮與壓縮的
> zgrep -h "203.0.113.5" /var/log/nginx/access.log*
> ```
> `zgrep` 對未壓縮檔案也能正常運作，所以一個 glob 就搞定。
> `-h` 是不顯示檔名（多檔搜尋時預設會顯示）。

其他壓縮格式有對應工具：`bzcat`/`bzless`/`bzgrep`（bz2）、
`xzcat`/`xzless`/`xzgrep`（xz）、`zstdcat`/`zstdgrep`（zstd）。

### ★★ `watch`：週期性重跑

```bash
watch -n 2 'df -h /'                    # ★★ 每 2 秒重跑一次
watch -d 'ss -tn state established'     # ★★★ -d 高亮變動的部分
watch -n 1 -d 'systemctl status nginx | head -20'
```

```
Every 2.0s: df -h /                              lab01: Wed Aug 27 10:35:12 2026

Filesystem      Size  Used Avail Use% Mounted on
/dev/sda2        50G   12G   36G  25% /
```

> [!tip] ★★ `watch` 的三個實用場景
> 1. **監看磁碟被填滿的速度**：`watch -n 5 'df -h /var'`
> 2. **等待服務啟動**：`watch -n 1 'ss -tlnp | grep :443'`
> 3. **觀察備份進度**：`watch -n 10 'du -sh /backup/current'`
>
> ★★★ 記得指令要用引號包起來，否則 `|` 會被 Shell 先解讀掉。

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> `cat`、`less`、`head`、`tail` 完全相同。差異只有：
> - ★★ **`watch` 可能沒安裝**（屬於 `procps-ng` 套件）：
>   ```bash
>   sudo dnf install -y procps-ng
>   ```
> - ★★★★ 日誌路徑不同：認證日誌在 `/var/log/secure` 而不是 `/var/log/auth.log`——查登入失敗時找錯檔案會以為「沒人在攻擊」
> - ★★★ RHEL 系預設更依賴 `journalctl`，很多服務不寫獨立的檔案日誌：
>   ```bash
>   journalctl -u nginx -f          # 等同 tail -F
>   journalctl -u nginx --since "10 minutes ago"
>   ```
> - ★★ `dos2unix` 需要先安裝：`sudo dnf install -y dos2unix`

---

## 完整實戰範例：網站突然變慢，從日誌下手

```bash
# ★★ 1. 先看最近有沒有錯誤
sudo tail -n 50 /var/log/nginx/error.log
```

```
2026/08/27 10:41:02 [error] 891#891: *8821 upstream timed out (110: Connection
timed out) while reading response header from upstream, client: 203.0.113.77,
server: example.com, request: "GET /api/report HTTP/1.1",
upstream: "fastcgi://unix:/run/php/php8.3-fpm.sock:", host: "example.com"
```

```bash
# ★★★ 2. 開追蹤模式即時觀察，看還在不在發生
sudo less +F /var/log/nginx/error.log
# （按 Ctrl+C 停下來翻閱，按 F 繼續）
```

```bash
# ★★★★ 3. 統計最近 1000 筆請求的狀態碼分布（量化，不要只看幾行就下結論）
sudo tail -n 1000 /var/log/nginx/access.log | awk '{print $9}' | sort | uniq -c | sort -rn
```

```
    812 200
    103 304
     67 504      ← 大量閘道逾時
     18 404
```

```bash
# ★★★★ 4. 找出是哪個路徑在逾時
sudo tail -n 5000 /var/log/nginx/access.log | awk '$9 == 504 {print $7}' | sort | uniq -c | sort -rn | head
```

```
     61 /api/report
      6 /api/export
```

```bash
# ★★★ 5. 這個問題什麼時候開始的？往歷史日誌找
sudo zgrep -h " 504 " /var/log/nginx/access.log* | awk '{print $4}' | cut -c2-15 | sort | uniq -c
```

```
      3 27/Aug/2026:09
     47 27/Aug/2026:10
     94 27/Aug/2026:11
```

```bash
# ★★★ 6. 對照 PHP-FPM 的日誌
sudo tail -n 100 /var/log/php8.3-fpm.log
sudo journalctl -u php8.3-fpm --since "1 hour ago" | less
```

> [!tip] ★★★★ 這個流程的邏輯
> **最新錯誤 → 即時觀察 → 量化統計 → 定位範圍 → 追溯起點 → 對照上下游**。
>
> 關鍵是第 3、4 步的「量化」——不要只看幾行日誌就下結論。
> `awk` + `sort` + `uniq -c` + `sort -rn` 這個組合會在
> [[020-01-12-cmd-Linux-文字處理三劍客]] 詳細說明，先把它當成固定招式記起來。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ `tail -f` 追了很久沒新內容，但服務明明有流量 | 日誌輪替後仍追著舊 inode | 改用 `tail -F` 或 `less +F` |
| ★★★ `tail -F ... \| grep x` 沒有即時輸出 | `grep` 輸出緩衝 | 加 `--line-buffered` |
| ★★★ `cat` 之後終端機變亂碼 | 讀了二進位檔 | 執行 `reset`；先用 `file` 確認類型 |
| ★★★ `Permission denied` 讀不到日誌 | 日誌權限通常是 `640 root:adm` | 用 `sudo`，或把自己加入 `adm` 群組 |
| ★★★★ 設定檔看起來正常卻不生效 | CRLF 換行或行尾空白 | `cat -A` 檢查；`dos2unix` 修復 |
| ★★ `less` 裡顏色變成 `ESC[0;31m` 亂碼 | 沒有 `-R` | `less -R` 或設 `export LESS='-R'` |
| ★★★ 日誌檔太大，`grep` 跑很久 | 全檔掃描 | 先用 `tail -n 100000` 限縮範圍，或用 `zgrep` 對特定輪替檔 |
| ★★ `watch 'cmd \| grep x'` 沒作用 | 沒加引號，管線被 Shell 解讀 | 指令用單引號包起來 |
| ★★ 開啟壓縮日誌是亂碼 | 用了 `cat` 而非 `zcat` | 用 `zcat` / `zless` / `zgrep` |
| ★★★★★ `cat a.log b.log > a.log` 之後 `a.log` 原本的內容不見了 | Shell 在 `cat` 執行前就先把輸出檔截斷成 0 位元組 | 沒有 undo，只能從備份或 `.1` 輪替檔救回；**輸出一律導到新檔名** |
| ★★★★ 磁碟滿了，`rm` 掉大日誌但 `df` 空間沒還回來 | 服務仍開著該檔案，inode 未釋放（`lsof` 會看到 `(deleted)`） | `truncate -s 0 <日誌>` 或 `logrotate -f`；已刪掉的只能重啟該服務 |
| ★★★★ `tail -F` 突然重印一大批舊資料 | 檔案被 `> file` 截斷（truncate），`tail` 從頭重讀 | 正常行為（會印 `file truncated`）；治本是讓應用改走 `logrotate` |
| ★★★ `journalctl -f` 看得到內容，`tail -F` 的檔案卻是空的 | 服務只寫 journal，沒有獨立檔案日誌（RHEL 系常見） | 改用 `journalctl -u <服務> -f` |
| ★★★ `zgrep` 對某個 `.gz` 沒輸出也不報錯 | 實際不是 gzip，只是副檔名寫成 `.gz` | `file access.log.2.gz` 確認真實格式，改用 `xzgrep` / `zstdgrep` |
| ★★★ 在 `less` 裡搜尋不到明明存在的字串 | 大小寫不符，或該行還沒被讀進來 | 先按 `G` 讓 `less` 讀到檔尾再搜；或設 `export LESS='-i'` |
| ★★★ `less` 開日誌卡住不動，游標一直閃 | 檔案在 NFS／慢速掛載點上，或它其實是個 FIFO／裝置檔 | `Ctrl+C` 後先 `file` 與 `stat` 確認；網路儲存見 [[020-01-29-guide-Linux-網路儲存與軟體RAID]] |
| ★★★★ 日誌時間戳記跟你手上的時鐘差好幾小時 | 時區設定不同或 NTP 沒同步，導致比對事故時間點時全錯 | `date`、`timedatectl`；見 [[020-01-28-cmd-Linux-時間同步NTP與chrony]] |

### 排查步驟

「日誌查不到東西」十之八九不是日誌沒寫，而是你**看錯檔案、看錯時間，或看的其實是一個
已經跟現實脫節的 inode**。照順序查，不要跳號。

**【1】確認這個服務把日誌寫到哪裡、最後一次寫是什麼時候**

```bash
sudo ls -l --time-style=+%m-%d\ %H:%M /var/log/nginx/
```

預期輸出：

```text
-rw-r----- 1 www-data adm 18234567 08-29 10:41 access.log      # ★★★ 時間是不是「剛剛」
-rw-r----- 1 www-data adm   120943 08-29 10:40 error.log
-rw-r----- 1 www-data adm  3410221 08-28 00:00 access.log.1    # 昨天輪替出去的
-rw-r----- 1 www-data adm   881234 08-27 00:00 access.log.2.gz
```

- 時間停在昨天或更早 → 日誌根本沒在成長，往【2】。
- 目錄裡只有 `.gz` 沒有現行檔 → 輪替後服務沒重開檔案，直接跳【4】。

**【2】確認檔案真的還在長大**

```bash
stat -c '%s' /var/log/nginx/access.log; sleep 10; stat -c '%s' /var/log/nginx/access.log
```

```text
18234567
18239104        # ★★★ 兩個數字要不一樣
```

兩次一模一樣代表沒有新內容寫入：可能真的沒流量，也可能服務改寫到 journal（往【5】），
或磁碟已滿寫不進去（往【6】）。

**【3】確認你追的是不是同一個 inode（`-f` 的經典陷阱）**

```bash
ls -li /var/log/nginx/access.log
ls -l /proc/$(pgrep -x tail | head -1)/fd 2>/dev/null | grep -i log
```

```text
1310721 -rw-r----- 1 www-data adm 18239104 Aug 29 10:41 /var/log/nginx/access.log
lrwx------ 1 ops ops 64 Aug 29 10:42 3 -> /var/log/nginx/access.log.1
```

★★★★ 箭頭指向 `.1`（或後面掛著 `(deleted)`）就是鐵證：你那條 `tail -f` 抱著舊檔案，
畫面再安靜也不代表系統安靜。`Ctrl+C` 重開，改用 `tail -F`。

**【4】確認輪替之後服務有沒有重新開檔**

```bash
sudo lsof /var/log/nginx/access.log.1
```

```text
COMMAND  PID     USER  FD  TYPE DEVICE     SIZE/OFF    NODE NAME
nginx   1204 www-data   5w  REG    8,2      3410221 1310722 /var/log/nginx/access.log.1
```

- 有輸出，而且 COMMAND 是**服務本身** → ★★★★ logrotate 的 `postrotate` 沒送出訊號／沒 reload，
  新的請求全部寫進舊檔案，現行 `access.log` 會永遠是 0 位元組。修法見
  [[020-01-19-guide-Linux-日誌系統]]。
- 沒有輸出 → 服務端正常，回到【3】檢查是你的 `tail` 抱錯檔。

**【5】確認這個服務是不是根本不寫檔案日誌**

```bash
journalctl -u nginx --since "10 minutes ago" --no-pager | tail -5
```

看得到內容、但 `/var/log/` 底下的檔案是空的 → ★★★ 這是 RHEL 系與容器化環境的常態，
以後查這個服務就用 `journalctl -u <服務> -f`，不要再 `tail` 檔案。

**【6】確認不是權限或磁碟把你擋在外面**

```bash
id; df -h /var/log; ls -l /var/log/nginx/error.log
```

```text
uid=1000(ops) gid=1000(ops) groups=1000(ops),4(adm)     # ★★★ 沒有 adm 就只能 sudo
Filesystem      Size  Used Avail Use% Mounted on
/dev/sda3        20G   20G     0 100% /var                # ★★★★ 100% = 日誌寫不進去
-rw-r----- 1 www-data adm 120943 Aug 29 10:40 error.log
```

★★★★ `Use% 100%` 是最容易誤判的一種「安靜」：服務還活著、還在回應請求，
但日誌一個字也寫不進去，於是你查不到任何錯誤。先清空間（`truncate -s 0`，**不要 `rm`**），
再回頭查原本的問題。空間規劃見 [[020-01-15-cmd-Linux-磁碟分割與掛載]]。

**【7】確認是不是你的過濾條件把輸出吃掉了**

```bash
tail -F /var/log/nginx/access.log | grep " 500 "                 # ★★★ 可能十幾秒才吐一次
tail -F /var/log/nginx/access.log | grep --line-buffered " 500 " # ★★★ 逐行輸出
tail -F /var/log/nginx/access.log | stdbuf -oL grep " 500 "      # ★★ 通用解法
```

三種都試過仍然沒有輸出，就把 `grep` 拿掉直接看原始輸出——多數時候是**樣式寫錯**
（例如日誌欄位之間不是單一空格），不是緩衝問題。

---

## 安全性注意事項

> [!warning] ★★★★★ 日誌裡可能有敏感資料
> Web 存取日誌會記錄完整 URL，如果應用把 token 放在 query string
> （`?api_key=xxx`），那它就明文躺在 `/var/log/nginx/access.log` 裡。
>
> - ★★★★ 檢查你的日誌有沒有這種內容
> - ★★★★★ 分享日誌給廠商或貼到論壇前**務必去識別化**
> - ★★★★ 日誌權限應該是 `640 root:adm`，不要放寬
>
> ```bash
> # 快速檢查有沒有疑似金鑰的參數
> sudo grep -oE '(token|key|password|secret)=[^&" ]*' /var/log/nginx/access.log | head
> ```

> [!warning] ★★★ 不要用 `sudo cat` 讀不明來源的檔案
> 二進位內容送進終端機可能包含控制序列。
> 雖然現代終端機大多已修補，但用 `less`（會跳脫控制字元）比 `cat` 安全。
>
> 先確認檔案類型：
> ```bash
> file /path/to/unknown
> ```

> [!danger] ★★★★★ 三件絕對不要做的事
> 1. **不要把原始日誌整份丟給廠商、貼上論壇或外部 AI 服務。**
>    access log 一行就含來源 IP、完整 URL（可能夾帶 `?token=`）、User-Agent、Referer。
>    這些在個資法下屬於個人資料，外流即為資安事件，而且**追得到是哪個帳號送出去的**。
>    真的要給，先過一輪去識別化：
>    ```bash
>    sudo awk '{$1="x.x.x.x"; print}' /var/log/nginx/access.log \
>      | sed -E 's/(token|key|password|secret)=[^&" ]*/\1=REDACTED/g' > /root/access-clean.log
>    ```
> 2. **不要用 `chmod 644` 或 `chmod o+r` 「解決」讀不到日誌的問題。**
>    正解是把人加進 `adm` 群組。放寬成人人可讀之後，任何一個被入侵的低權限服務帳號
>    都能把全站存取紀錄整份讀走——這正是攻擊者橫向移動時第一個翻的東西。
> 3. **不要為了排錯把日誌複製到網站根目錄。**
>    `cp access.log /var/www/html/` 這種「暫時放一下」等於把日誌開放給整個網際網路下載，
>    而且你一定會忘記刪。要複製就放 `/root/` 底下，結案後 `shred -u` 刪除。

> [!danger] ★★★★ 日誌是稽核軌跡，不要用編輯器打開它
> 1. ★★★ 用 `vim` 開 2GB 的 access.log 會**整份讀進記憶體**，小型 VM 直接被 OOM Killer 收掉。
> 2. ★★★★ 多數編輯器存檔是「寫新檔再改名」，**inode 一換，正在 `tail -f` 的人看不到新內容，
>    服務本身也可能繼續寫進那個已經改名的舊 inode**。
> 3. ★★★★★ 稽核上，被編輯過的日誌等於失去證據力。資安事件調查與 TWGCB 稽核都會看這一點，
>    「我只是想刪掉幾行測試資料」在報告上寫不出來。
>
> 要看就用 `less`，要抽片段就 `sed -n` / `grep` **導到新檔**，永遠不要原地改：
>
> ```bash
> sudo sed -n '/29\/Aug\/2026:10:4/p' /var/log/nginx/access.log > /root/incident-1041.log
> ```

> [!tip] ★★★ 把自己加入 `adm` 群組，日常查日誌不用 sudo
> ```bash
> sudo usermod -aG adm mike     # 重新登入後生效
> tail -F /var/log/nginx/error.log    # 不用 sudo 了
> ```
> ★★★ 這比到處用 `sudo` 好——**降低你使用 root 權限的頻率**，
> 也就降低誤操作的機會。RHEL 系的對應群組也是 `adm`。

---

## 速查表

### 檢視

| 指令 | 說明 |
| --- | --- |
| ★★★ `cat -n` / `-A` / `-s` | 行號 / 顯示不可見字元 / 壓縮空行 |
| ★ `tac file` | 反向輸出 |
| ★★★ `less file` | 分頁檢視（大檔案首選） |
| ★★★★ `less +F file` | 以追蹤模式開啟 |
| ★★ `less -S file` | 長行不換行 |
| ★★ `less -R` | 保留顏色 |
| ★ `more file` | 最低限度分頁器（到檔尾自動離開） |
| ★★ `head -n N` / `head -c N` | 前 N 行 / 前 N 位元組 |
| ★★★ `tail -n N` | 後 N 行 |
| ★★ `tail -n +N` | 從第 N 行到結尾（跳過標頭） |
| ★★★★ `tail -F file` | **即時追蹤（處理輪替）** |
| ★★ `sed -n '10,20p'` | 第 10～20 行 |

### `less` 內部操作

| 按鍵 | 作用 |
| --- | --- |
| ★★★ `/` `?` `n` `N` | 向下搜尋 / 向上搜尋 / 下一個 / 上一個 |
| ★★★ `&關鍵字` | **只顯示比對的行（過濾）** |
| ★★ `g` / `G` | 檔頭 / 檔尾 |
| ★★★★ `F` | 追蹤模式（`Ctrl+C` 離開） |
| ★★ `-N` / `-S` | 切換行號 / 切換長行截斷 |
| ★ `v` | 用編輯器開啟 |
| ★ `q` | 離開 |

### 壓縮檔

| 指令 | 對應 |
| --- | --- |
| ★★★ `zcat` `zless` `zgrep` | gzip（`.gz`） |
| ★★ `bzcat` `bzless` `bzgrep` | bzip2（`.bz2`） |
| ★★ `xzcat` `xzless` `xzgrep` | xz（`.xz`） |
| ★★ `zstdcat` `zstdgrep` | zstd（`.zst`） |

### 其他

| 指令 | 說明 |
| --- | --- |
| ★★ `watch -n 2 -d 'cmd'` | 每 2 秒重跑並高亮變動 |
| ★★★ `file <檔案>` | 判斷檔案類型（`cat` 之前先問它） |
| ★★★★ `dos2unix <檔案>` | 修復 CRLF 換行 |
| ★★★ `journalctl -u <服務> -f` | 追蹤 systemd 服務日誌 |
| ★★★★ `truncate -s 0 <日誌>` | 清空日誌但保留 inode（磁碟滿時的正解，不要 `rm`） |

---

## 練習題

> [!question]- 練習 1：親眼看到 `-f` 與 `-F` 的差別
> 模擬日誌輪替，觀察兩者行為：
> ```bash
> cd /tmp && echo "line 1" > app.log
>
> # 終端機 A
> tail -f /tmp/app.log
> # 終端機 B
> tail -F /tmp/app.log
>
> # 終端機 C：模擬 logrotate
> echo "line 2" >> /tmp/app.log        # 兩邊都會顯示
> mv /tmp/app.log /tmp/app.log.1       # 輪替
> echo "line 3" > /tmp/app.log         # 新檔案
> ```
>
> **解答**
>
> - 終端機 A（`-f`）：顯示 `line 2` 之後就**再也沒有新內容**，
>   因為它仍握著已改名的 `app.log.1` 的 inode。
> - 終端機 B（`-F`）：會顯示
>   ```
>   tail: /tmp/app.log: file truncated
>   line 3
>   ```
>   它偵測到檔名對應到新的 inode，自動重新開啟。
>
> ★★★★ 這就是為什麼**一律用 `-F`**。

> [!question]- 練習 2：找出佔用最多流量的來源 IP
> 用 `/var/log/nginx/access.log`（沒有的話用任何有 IP 的日誌），
> 找出請求數最多的前 5 個 IP，並統計它們各自的狀態碼分布。
>
> **解答**
>
> ```bash
> # 前 5 名 IP
> sudo awk '{print $1}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -5
> ```
>
> ```
>   4821 203.0.113.77
>   1092 198.51.100.4
>    877 203.0.113.5
> ```
>
> ```bash
> # 看第一名的狀態碼分布
> sudo awk '$1 == "203.0.113.77" {print $9}' /var/log/nginx/access.log \
>   | sort | uniq -c | sort -rn
> ```
>
> ```
>   4102 404
>    719 200
> ```
>
> ★★★★ 大量 404 加上單一來源高請求量，是**掃描或爆破**的典型特徵。
> 處理方式見 [[090-02-05-guide-防護-Fail2ban入侵防護]] 與 [[060-02-02-09-guide-Nginx-安全設定]]。
>
> 想涵蓋所有歷史日誌就把 `awk` 換成先 `zcat`：
> ```bash
> sudo zcat -f /var/log/nginx/access.log* | awk '{print $1}' | sort | uniq -c | sort -rn | head
> ```
> （`zcat -f` 對未壓縮檔案也能運作）

> [!question]- 練習 3：抓出設定檔的隱形問題
> 建立一個含問題的設定檔並找出來：
> ```bash
> printf 'server_name  example.com; \r\nlisten\t80;\r\n' > /tmp/bad.conf
> ```
> 用什麼指令能看出它有什麼問題？怎麼修？
>
> **解答**
>
> ```bash
> file /tmp/bad.conf
> ```
> ```
> /tmp/bad.conf: ASCII text, with CRLF line terminators
> ```
>
> ```bash
> cat -A /tmp/bad.conf
> ```
> ```
> server_name  example.com; ^M$
> listen^I80;^M$
> ```
>
> 找到三個問題：
> 1. ★★★★ `^M$` → **CRLF 換行**（Windows 編輯過）
> 2. ★★★ 第一行 `;` 後面有**行尾空白**
> 3. ★ 第二行用了 **Tab**（`^I`）而非空白——多數設定檔可接受，但格式不一致
>
> 修復：
> ```bash
> dos2unix /tmp/bad.conf
> sed -i 's/[[:space:]]*$//' /tmp/bad.conf     # 去除行尾空白
> cat -A /tmp/bad.conf
> ```
> ```
> server_name  example.com;$
> listen^I80;$
> ```
>
> ★★★★ **這一招在排查「設定明明對卻不生效」時能省下好幾小時。**

---

## 小測驗

Q1. 為什麼不該用 `cat` 開大檔案？意外 `cat` 二進位檔造成亂碼後怎麼修？
Q2. `cat -A` 顯示 `^M$` 代表什麼？會造成什麼症狀？怎麼修？
Q3. `cat file | grep x` 為什麼被稱為 UUOC？正確寫法？
Q4. `less` 裡按 `&` 輸入關鍵字做什麼？`F` 做什麼？
Q5. `less` 的 `F` 模式比 `tail -f` 好在哪？
Q6. `tail -f` 與 `tail -F` 在日誌輪替後的行為差異？該一律用哪個？
Q7. `tail -F log | grep " 500 "` 為什麼沒有即時輸出？三種工具各自的解法？
Q8. 不解壓縮直接搜尋所有輪替後的 `.gz` 日誌，用什麼指令？
Q9. `more` 與 `less` 的三個關鍵差異？何時只能用 `more`？
Q10. 存取日誌可能含哪類敏感資料？分享前該做什麼？

> [!question]- 測驗答案
> **Q1.** ★★★ 會刷爆終端機且中斷前無法操作；二進位檔的控制字元會弄亂終端機，執行 `reset` 修復（見「選對工具」）。
> **Q2.** ★★★★ Windows 的 CRLF 換行；腳本報 `bad interpreter: /bin/bash^M`、設定值比對永遠失敗。`dos2unix` 或 `sed -i 's/\r$//'`。
> **Q3.** ★★ Useless Use of Cat：多開一個程序且失去 `grep` 直接讀檔的功能（顯示檔名、`-r`）。寫 `grep x file`。
> **Q4.** ★★★ `&` 只顯示含關鍵字的行（過濾）；`F` 進入追蹤模式，等同 `tail -f`。
> **Q5.** ★★★ 可以 `Ctrl+C` 停下來往回翻、搜尋、過濾，再按 `F` 繼續。
> **Q6.** ★★★★ `-f` 追蹤開啟時的 inode，輪替後永遠不再有新內容；`-F` 追蹤檔名，自動重開新檔。一律用 `-F`。
> **Q7.** ★★★ grep 在輸出非終端機時用 4KB 區塊緩衝。`grep --line-buffered`、`awk '{...; fflush()}'`、`sed -u`；通用解法 `stdbuf -oL`。
> **Q8.** ★★★ `zgrep -h "樣式" /var/log/nginx/access.log*`——`zgrep` 對未壓縮檔也能用。
> **Q9.** ★★ `more` 舊版不能往上翻、可能整份讀進記憶體、到檔尾自動離開；只有極簡容器或救援環境沒有 `less` 時才用。
> **Q10.** ★★★★★ query string 裡的 token/api_key、email、IP；分享前去識別化，日誌權限保持 `640 root:adm`。

---

## 延伸閱讀

- [[020-01-07-cmd-Linux-尋找檔案與內容]] — 用 `grep` 與 `find` 精準定位
- [[020-01-11-cmd-Linux-輸入輸出重導向與管線]] — 把這些工具串起來
- [[020-01-12-cmd-Linux-文字處理三劍客]] — `awk` 統計日誌的完整用法
- [[020-01-19-guide-Linux-日誌系統]] — `journalctl` 與 `logrotate`
- [[060-02-02-07-guide-Nginx-日誌與除錯]] — Nginx 日誌格式與判讀
- [[100-01-01-01-svc-GoAccess-安裝與基本使用]] — 把日誌變成視覺化報表
