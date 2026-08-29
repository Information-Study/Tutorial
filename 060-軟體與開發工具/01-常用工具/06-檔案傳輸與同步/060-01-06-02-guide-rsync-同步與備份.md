---
title: "rsync 同步與備份"
desc: "增量同步、排除規則、硬連結快照與 rsync daemon"
aliases: [rsync, 增量備份, 同步, --delete, 硬連結快照]
tags: [群組/軟體與開發工具, 主題/檔案傳輸, 主題/備份]
category: 常用工具
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[060-01-06-01-guide-傳輸-scp與sftp傳輸]]"]
updated: 2026-08-28
---

# rsync 同步與備份

> [!abstract] 這篇你會學到
> - **★★★★ 結尾斜線的意義**（最經典的踩雷點）
> - `-a` 到底包含什麼、什麼時候不夠
> - **★★★★ `--delete` 的危險**與安全的用法
> - **★★★ 排除規則**的完整語法與優先順序
> - **★★★★ `--link-dest` 硬連結快照**（空間省 90% 的備份）
> - 頻寬控制、斷點續傳、`--partial`
> - rsync daemon 與 SSH 模式的取捨
> - **★★★ 安全：限制 rsync 的 SSH 金鑰**

## 前置知識

- [[060-01-06-01-guide-傳輸-scp與sftp傳輸]] — SSH 傳輸基礎
- [[020-01-08-cmd-Linux-檔案權限與擁有者]] — 權限模型

---

## ★★★★ 結尾斜線

```
★★★★ 這是 rsync 最經典、也最容易出錯的一點：

  rsync -av /src/  /dst/        ← ★★★ 來源【有】斜線
    → 把 /src 【裡面的東西】複製到 /dst/
    → 結果：/dst/file1  /dst/file2

  rsync -av /src   /dst/        ← ★★★★ 來源【沒有】斜線
    → 把 /src 【這個目錄本身】複製到 /dst/
    → 結果：/dst/src/file1  /dst/src/file2
                  ↑ ★★★★ 多了一層！

★★★ 記法：
  「來源結尾有斜線 = 只要內容」
  「來源結尾沒斜線 = 連目錄一起」

★★ 目標端的斜線【不影響結果】（但習慣上都加）
```

```bash
# ═══ ★★★★ 實測 ═══
$ mkdir -p /tmp/src /tmp/dst1 /tmp/dst2
$ touch /tmp/src/a.txt /tmp/src/b.txt

$ rsync -av /tmp/src/ /tmp/dst1/
$ find /tmp/dst1
/tmp/dst1
/tmp/dst1/a.txt                    # ★★★ 直接在 dst1 底下
/tmp/dst1/b.txt

$ rsync -av /tmp/src /tmp/dst2/
$ find /tmp/dst2
/tmp/dst2
/tmp/dst2/src                      # ★★★★ 多了一層 src/
/tmp/dst2/src/a.txt
/tmp/dst2/src/b.txt
```

> [!danger] 斜線 + `--delete` 的災難 ★★★★
> ```
> ★★★★ 情境：想同步 /var/www/app 到備份機
>
>   $ rsync -av --delete /var/www/app /backup/app/
>                                  ↑ ★★★★ 忘了斜線
>
>   → 結果變成 /backup/app/app/...
>   → ★★★ 而 --delete 會【刪掉 /backup/app/ 底下原本的東西】
>   → ★★★★ 舊的備份全部消失，只剩一個 app/ 子目錄
>
> ★★★★ 三個防護：
>   ① ★★★★ 【一定要先 --dry-run】
>      $ rsync -avn --delete /var/www/app/ /backup/app/
>   ② ★★★ 寫腳本時用變數並確保結尾有斜線
>      SRC="${SRC%/}/"        # ★★ 去掉再加，確保只有一個
>   ③ ★★ --delete 一律搭配 --backup 或 --max-delete
> ```

---

## `-a` 包含什麼 ★★★

```
★★★★ -a（--archive）= -rlptgoD

  -r  ★★★ recursive        遞迴
  -l  ★★★ links            保留符號連結（★ 複製連結本身）
  -p  ★★★ perms            保留權限模式
  -t  ★★★ times            保留修改時間（★ 增量比對的關鍵！）
  -g  ★★ group             保留群組
  -o  ★★ owner             保留擁有者（★ 需要 root）
  -D  = --devices --specials  裝置檔與特殊檔（★ 需要 root）

★★★★ -a 【不包含】的（要另外加）：
  -A  ★★★ --acls           ACL
  -X  ★★★ --xattrs         擴充屬性（★ SELinux 標籤在這裡）
  -H  ★★★ --hard-links     硬連結
  -S  ★★ --sparse          稀疏檔案（★ 虛擬機映像檔很重要）
  --numeric-ids  ★★★★ 用數字 UID/GID（★ 跨機器必加）
  -z  ★★ --compress        壓縮傳輸
```

```bash
# ═══ ★★★★ 完整保留的標準寫法 ═══
$ sudo rsync -avAXH --numeric-ids --sparse /src/ /dst/

# ★★★ 跨機器
$ sudo rsync -avAXH --numeric-ids -e ssh /src/ backup:/dst/

# ★★ 常用的日常寫法
$ rsync -avz --progress /src/ backup:/dst/

# ★★★ 為什麼要 --numeric-ids
$ rsync -av /src/ backup:/dst/
#   → ★★★ rsync 會用【使用者名稱】對應
#   → ★★★★ 兩台機器的 uid 1001 可能是不同的人！
#     A 機的 www-data 是 33，B 機是 82
#   → ★★★ --numeric-ids 直接用數字，不做名稱對應
```

> [!tip] `-t`（保留時間戳）為什麼是關鍵 ★★★★
> ```
> ★★★★ rsync 判斷「檔案是否需要傳輸」的預設方式：
>   【比對 大小 + 修改時間】
>
>   → ★★★ 沒有 -t 的話，每次傳完目標的 mtime 都是「現在」
>   → ★★★★ 下次執行時所有檔案都被認為「不一樣」→ 【全部重傳】
>   → ★★ 增量同步完全失效
>
> ★★★ 所以 -a（含 -t）幾乎是必加的
>
> ★★ 其他比對方式：
>   --checksum / -c    ★★★ 用 MD5 比對內容（★ 慢但最準確）
>   --size-only        ★★ 只比大小（★ 適合來源的 mtime 不可靠時）
>   --ignore-times / -I  ★ 一律傳輸（★ 不比對）
>   --update / -u      ★★★ 只在來源比目標新時才傳（★ 不會覆蓋較新的）
> ```

---

## ★★★★ `--delete` 的正確用法

```
★★★★ --delete 讓目標端【完全鏡像】來源：
  → 來源沒有的檔案，目標端【會被刪除】

★★★ 四個變體：
  --delete            ★★★ 傳輸中刪除（★ 預設是 --delete-during）
  --delete-before     ★★ 傳輸前先刪（★ 目標空間吃緊時）
  --delete-after      ★★ 傳輸完才刪（★ 較安全）
  --delete-delay      傳輸中記錄，最後才刪
  --delete-excluded   ★★★★ 連【被排除的檔案】也刪掉（★ 很危險）

★★★★ 安全網：
  --max-delete=N      ★★★★ 超過 N 個要刪就中止（★ 強烈建議）
  --backup --backup-dir=DIR   ★★★ 刪除前先搬到備份目錄
  --dry-run / -n      ★★★★ 先看會發生什麼
```

```bash
# ═══ ★★★★ 安全的 --delete 流程 ═══

# ★★★★【1】一定要先 dry-run
$ rsync -avn --delete --stats /var/www/app/ backup:/srv/backup/app/
sending incremental file list
deleting old/cache/file1.tmp
deleting old/cache/file2.tmp
./
public/build/app-a1b2c3.js

Number of files: 12,840
Number of deleted files: 2                   # ★★★★ 只刪 2 個 → 合理
Number of regular files transferred: 3

# ★★★★【2】加上安全網
$ rsync -av --delete --max-delete=100 \
    --backup --backup-dir="/srv/backup/deleted/$(date +%F-%H%M%S)" \
    /var/www/app/ backup:/srv/backup/app/
#   ★★★★ --max-delete=100：要刪超過 100 個就中止（★ 防止來源被誤刪時連鎖）
#   ★★★ --backup-dir：刪掉的東西先搬到那裡（★ 可以救回來）

# ★★★ 超過限制時的行為
$ rsync -av --delete --max-delete=10 /src/ /dst/
rsync warning: some files vanished before they could be transferred
rsync error: --max-delete limit exceeded (28) at main.c(1330)
#   ★★★★ 中止，什麼都不會刪 → 讓你去檢查為什麼

# ★★★★【3】--delete-excluded 的陷阱
$ rsync -av --delete --exclude='logs/' /src/ /dst/
#   ★★★ logs/ 被排除 → 目標端的 logs/ 【保留不動】

$ rsync -av --delete-excluded --exclude='logs/' /src/ /dst/
#   ★★★★ 目標端的 logs/ 【會被刪除】！
#   → ★★★ 只有在你確定要清乾淨時才用
```

---

## ★★★ 排除規則

```bash
# ═══ ★★★ 基本 ═══
$ rsync -av --exclude='*.log' /src/ /dst/
$ rsync -av --exclude='node_modules/' --exclude='vendor/' /src/ /dst/
$ rsync -av --exclude-from=/etc/rsync-exclude.txt /src/ /dst/

# ★★★ 包含優先（★ 順序很重要）
$ rsync -av --include='*.conf' --exclude='*' /src/ /dst/
#   ★★★★ 只傳 .conf（★ include 要在 exclude 之前）

# ★★★ 只傳特定目錄下的特定檔案
$ rsync -av \
    --include='*/' \
    --include='*.conf' \
    --exclude='*' \
    /etc/ /backup/etc-conf/
#   ★★★ --include='*/' 讓 rsync 進入所有目錄（★ 否則遞迴會停在第一層）
```

```
★★★★ 規則的比對順序（★ 這是最容易搞錯的）：

  ① 規則【由上到下】比對
  ② ★★★★ 【第一個符合的規則決定結果】，後面的不再看
  ③ 對每一層目錄都會比對

★★★ 所以：
  --include='*.conf' --exclude='*'      ★★★ 正確（先包含再排除全部）
  --exclude='*' --include='*.conf'      ★★★★ 錯誤（全部被排除了）

★★★ 遞迴的陷阱：
  --include='*.conf' --exclude='*'
  → ★★★★ 目錄本身也符合 '*' 而被排除
  → rsync 不會進入目錄 → 找不到裡面的 .conf
  → ★★★ 一定要加 --include='*/'
```

```bash
# ═══ ★★★ 模式語法 ═══
```

| 模式 | 意義 |
| --- | --- |
| `*.log` | 任何 `.log` 檔（**★ 不跨目錄分隔符**） |
| `**.log` | **★★ 跨目錄的比對** |
| `/logs/` | **★★★ 只比對根目錄的 logs/**（開頭斜線 = 相對於傳輸的根） |
| `logs/` | **★★ 任何一層的 logs/ 目錄** |
| `logs` | 任何一層名為 logs 的檔案或目錄 |
| `dir/**` | **★★ dir 底下的所有東西**（但保留 dir 本身） |
| `- pattern` | 在 filter 檔案中表示排除 |
| `+ pattern` | 在 filter 檔案中表示包含 |

```bash
# ═══ ★★★ 實用的排除檔案 ═══
$ sudo tee /etc/rsync-exclude-web.txt >/dev/null <<'EOF'
# ★★★ 版本控制
.git/
.svn/
.hg/

# ★★★★ 相依套件（★ 應該重新安裝而不是同步）
node_modules/
vendor/
.venv/
__pycache__/
*.pyc

# ★★★ 建置產物
dist/
build/
public/build/
public/hot
*.map

# ★★★★ 執行時期的檔案
storage/logs/
storage/framework/cache/
storage/framework/sessions/
storage/framework/views/
bootstrap/cache/*.php

# ★★★★ 機密（★ 絕對不要同步）
.env
.env.*
auth.json
*.pem
*.key
id_rsa*
id_ed25519*

# ★★ 暫存
*.tmp
*.swp
*.swo
*~
.DS_Store
Thumbs.db
core
core.*

# ★★ 大型的日誌
*.log
*.log.[0-9]*
*.gz
EOF

$ rsync -av --exclude-from=/etc/rsync-exclude-web.txt \
    /var/www/app/ backup:/srv/backup/app/

# ═══ ★★★ 用 --filter 做更複雜的規則 ═══
$ rsync -av \
    --filter='+ /config/' \
    --filter='+ /config/**' \
    --filter='- /storage/logs/**' \
    --filter='+ /storage/' \
    --filter='+ /storage/**' \
    --filter='- *' \
    /var/www/app/ /backup/

# ★★★ 讓每個目錄可以有自己的規則檔
$ rsync -av --filter='dir-merge /.rsync-filter' /src/ /dst/
$ cat /src/subdir/.rsync-filter
- *.tmp
+ important.tmp
```

---

## ★★★★ `--link-dest` 硬連結快照

```
★★★★ 這是 rsync 最強大的功能，也是 Time Machine 式備份的原理：

  ★★★ 原理：
    對於【沒有變更】的檔案，不複製內容，
    而是在新的快照中【建立指向舊快照的硬連結】
    → ★★★★ 同一份資料只佔一次空間
    → ★★★ 但每個快照看起來都是【完整的目錄樹】

  ★★★ 效果：
    每天一個快照，保留 30 天
    → 資料 100GB，每天變動 1GB
    → 傳統做法：100GB × 30 = 3TB
    → ★★★★ 硬連結快照：100GB + 1GB × 29 ≈ 129GB
    → ★★★★ 省了 95% 的空間
```

```bash
#!/usr/bin/env bash
# ★★★★ /usr/local/bin/snapshot-backup —— 硬連結快照備份
set -euo pipefail

SRC="${1:?用法: snapshot-backup <來源> <備份根目錄> [保留天數]}"
BACKUP_ROOT="${2:?}"
KEEP="${3:-30}"

SRC="${SRC%/}/"                        # ★★★ 確保結尾有斜線
TS=$(date +%Y-%m-%d-%H%M%S)
NEW="$BACKUP_ROOT/$TS"
LATEST="$BACKUP_ROOT/latest"

mkdir -p "$BACKUP_ROOT"

echo "═══ 快照備份 $SRC → $NEW ═══"

# ═══ ★★★★ 建立快照 ═══
LINK_OPT=()
if [ -d "$LATEST" ]; then
    LINK_OPT=(--link-dest="$(readlink -f "$LATEST")")
    echo "  ★★★ 以 $(basename "$(readlink -f "$LATEST")") 為基準做增量"
else
    echo "  ★ 第一次備份（完整）"
fi

rsync -aAXH --numeric-ids --sparse \
      --delete --delete-excluded \
      --exclude-from=/etc/rsync-exclude-web.txt \
      --stats --human-readable \
      "${LINK_OPT[@]}" \
      "$SRC" "$NEW.incomplete/"
#   ★★★★ 先寫到 .incomplete，成功才改名 → 避免不完整的快照

mv "$NEW.incomplete" "$NEW"
ln -sfn "$TS" "$BACKUP_ROOT/latest.tmp"
mv -Tf "$BACKUP_ROOT/latest.tmp" "$LATEST"      # ★★★ 原子切換
echo "  ★ 快照完成: $NEW"

# ═══ ★★★ 空間報告 ═══
echo -e "\n【空間使用】"
echo "  本次快照的【表面】大小: $(du -sh "$NEW" 2>/dev/null | cut -f1)"
echo "  本次快照的【實際】增量: $(du -sh --exclude-from=/dev/null \
    $(ls -1dt "$BACKUP_ROOT"/2*/ 2>/dev/null | head -2 | tail -1) "$NEW" 2>/dev/null | \
    tail -1 | cut -f1 || echo '?')"
echo "  所有快照總計: $(du -sh "$BACKUP_ROOT" 2>/dev/null | cut -f1)"
echo "  快照數量: $(ls -1d "$BACKUP_ROOT"/2*/ 2>/dev/null | wc -l)"

# ═══ ★★★ 清理舊快照 ═══
echo -e "\n【清理】保留最近 $KEEP 個"
ls -1dt "$BACKUP_ROOT"/2*/ 2>/dev/null | tail -n "+$((KEEP+1))" | while read -r old; do
    echo "  ★ 刪除 $(basename "$old")"
    rm -rf "$old"
done

# ═══ ★★★★ 驗證 ═══
echo -e "\n【驗證】"
[ -d "$NEW" ] || { echo "  ★★★★ 快照目錄不存在！"; exit 1; }
FILES=$(find "$NEW" -type f | wc -l)
echo "  檔案數: $FILES"
[ "$FILES" -gt 0 ] || { echo "  ★★★★ 快照是空的！"; exit 1; }
echo "  ★ 驗證通過"

echo "$(date -Is)|$SRC|$NEW|$FILES 檔案" >> "$BACKUP_ROOT/backup.log"
```

```bash
$ sudo install -m755 snapshot-backup.sh /usr/local/bin/snapshot-backup
$ sudo snapshot-backup /var/www/app /srv/backup/app 30

═══ 快照備份 /var/www/app/ → /srv/backup/app/2026-08-28-183011 ═══
  ★★★ 以 2026-08-27-183011 為基準做增量

Number of files: 24,810 (reg: 22,104, dir: 2,706)
Number of created files: 142
Number of regular files transferred: 142
Total file size: 2.84G bytes
Total transferred file size: 48.2M bytes         # ★★★★ 只傳了 48MB
Total bytes sent: 12.4M

  ★ 快照完成

【空間使用】
  本次快照的【表面】大小: 2.9G
  所有快照總計: 4.2G                              # ★★★★ 30 個快照只佔 4.2G！
  快照數量: 28
```

```bash
# ═══ ★★★★ 驗證硬連結真的生效 ═══
$ ls -li /srv/backup/app/2026-08-27-183011/composer.json \
         /srv/backup/app/2026-08-28-183011/composer.json
1234567 -rw-r--r-- 2 deploy www-data 1842 Aug 20 10:00 .../2026-08-27.../composer.json
1234567 -rw-r--r-- 2 deploy www-data 1842 Aug 20 10:00 .../2026-08-28.../composer.json
#  ↑                ↑
# ★★★★ inode 相同    ★★★ 連結數 = 2
#   → 同一份資料，只佔一次空間

# ★★★ 修改過的檔案 inode 就不同了
$ ls -li /srv/backup/app/2026-08-2{7,8}-183011/public/build/app.js
2345678 -rw-r--r-- 1 ... 2026-08-27.../app.js
2345999 -rw-r--r-- 1 ... 2026-08-28.../app.js      # ★★ 不同 inode

# ★★★ 統計真正的空間使用
$ du -sh /srv/backup/app/                 # ★★★ 所有快照的實際總和
4.2G
$ du -sh /srv/backup/app/2026-08-28-183011/   # ★★ 單一快照的表面大小
2.9G
$ du -sh --separate-dirs /srv/backup/app/2*/ | tail -3
```

> [!danger] 硬連結快照的四個限制 ★★★
> ```
> ① ★★★★ 【必須在同一個檔案系統】
>    → 硬連結不能跨檔案系統
>    → 備份目標和 --link-dest 要在同一個掛載點
>
> ② ★★★ 【不能防止檔案系統損毀】
>    → 所有快照共用同一份資料
>    → ★★★★ 磁碟壞了 = 全部快照一起沒
>    → ★★★ 必須搭配【異地備份】（3-2-1 原則）
>
> ③ ★★★ 【inode 消耗大】
>    → 每個快照的每個檔案都要一個目錄項
>    → ★★ 30 個快照 × 25000 個檔案 = 大量 inode
>    → ★★★ 用 df -i 監控
>
> ④ ★★ 【刪除舊快照可能很慢】
>    → rm -rf 一個快照要處理幾萬個硬連結
>    → ★ 考慮用 rsync --delete 到空目錄（更快）
>
> ★★★★ 更好的替代：ZFS / Btrfs 的原生快照
>    → 見 [[020-01-24-guide-進階儲存-ZFS與Btrfs]]
> ```

---

## 頻寬與續傳 ★★

```bash
# ═══ ★★★ 限速 ═══
$ rsync -av --bwlimit=5000 /src/ backup:/dst/       # ★★★ 5000 KB/s ≈ 5MB/s
$ rsync -av --bwlimit=1m /src/ backup:/dst/         # ★★ 1 MB/s（新版支援單位）
$ rsync -av --bwlimit=10m /src/ backup:/dst/

# ★★ 用 trickle（更精細的控制）
$ sudo apt install -y trickle
$ trickle -u 500 -d 1000 rsync -av /src/ backup:/dst/

# ═══ ★★★★ 續傳 ═══
$ rsync -avP /src/ backup:/dst/
#   ★★★★ -P = --partial --progress
#   --partial   ★★★ 保留傳一半的檔案，下次接續
#   --progress  ★★ 顯示進度

$ rsync -av --partial-dir=.rsync-partial /src/ backup:/dst/
#   ★★★ 把半成品放在專用目錄（★ 避免和正常檔案混淆）

$ rsync -av --append /src/ backup:/dst/
#   ★★ 只附加到現有檔案的結尾（★ 適合日誌，★★★ 但不驗證前面的部分）
$ rsync -av --append-verify /src/ backup:/dst/
#   ★★★ 附加但會驗證已存在的部分（★ 較安全）

# ═══ ★★ 逾時與重試 ═══
$ rsync -av --timeout=300 --contimeout=30 /src/ backup:/dst/
#   --timeout     ★★ I/O 閒置逾時
#   --contimeout  ★★ 連線逾時

# ★★★ 自動重試（★ 網路不穩時）
$ for i in 1 2 3 4 5; do
    rsync -avP --timeout=300 /src/ backup:/dst/ && break
    echo "★★ 第 $i 次失敗，10 秒後重試..."
    sleep 10
  done

# ═══ ★★ 效能調整 ═══
$ rsync -avz --compress-level=1 /src/ backup:/dst/    # ★★ 壓縮等級 0-9
$ rsync -av --skip-compress=gz/zip/jpg/mp4/iso /src/ backup:/dst/
#   ★★★ 已壓縮的檔案不要再壓（★ 浪費 CPU）

$ rsync -av --inplace /src/ backup:/dst/
#   ★★ 直接就地更新（★ 省空間，★★★ 但中斷會留下損毀的檔案）
#   → ★★★ 適合大型的 VM 映像檔（配合快照）

$ rsync -av --whole-file /src/ /mnt/local-dst/
#   ★★★ 本機到本機時停用差異演算法（★ 直接複製整個檔案更快）
#   → ★★ 網路傳輸【不要】用

$ rsync -av -e 'ssh -c aes128-gcm@openssh.com -o Compression=no' /src/ backup:/dst/
#   ★★★ 用較快的加密演算法（★ 高速網路上差異明顯）
```

---

## rsync daemon ★★

```
★★★ 兩種模式：

  【★★★ SSH 模式】（★ 預設，推薦）
    rsync -av /src/ user@host:/dst/
    → ★★★ 加密、用 SSH 的認證
    → ★★ 有 SSH 的加密與壓縮開銷

  【★★ daemon 模式】
    rsync -av /src/ rsync://host/module/
    rsync -av /src/ host::module/
    → ★★★ 沒有加密（★ 除非走 SSH 隧道或 stunnel）
    → ★★★ 速度較快（沒有加密開銷）
    → ★★ 可以定義 module 與存取控制
    → ★★★★ 只適合【內網的可信環境】
```

```bash
# ═══ ★★ 設定 rsync daemon ═══
$ sudo tee /etc/rsyncd.conf >/dev/null <<'EOF'
uid = rsyncd
gid = rsyncd
use chroot = yes                    # ★★★ chroot 到 module 的 path
max connections = 10
pid file = /run/rsyncd.pid
lock file = /run/rsyncd.lock
log file = /var/log/rsyncd.log
timeout = 600
reverse lookup = no

# ★★★ 全域的存取控制
hosts allow = 10.10.20.0/24         # ★★★★ 一定要設
hosts deny = *

[backup]
    comment = 備份接收
    path = /srv/backup
    read only = no
    list = no                       # ★★ 不列在 module 清單中
    ★★★ auth users = backupuser
    ★★★ secrets file = /etc/rsyncd.secrets
    ★★ strict modes = yes
    incoming chmod = D750,F640      # ★★★ 上傳的權限
    hosts allow = 10.10.20.31

[public]
    comment = 唯讀的軟體庫
    path = /srv/mirror
    read only = yes
    list = yes
EOF

# ★★★★ 密碼檔（★ 權限一定要 600）
$ sudo tee /etc/rsyncd.secrets >/dev/null <<'EOF'
backupuser:很長的隨機密碼
EOF
$ sudo chmod 600 /etc/rsyncd.secrets
$ sudo chown root:root /etc/rsyncd.secrets

# ★★ 啟動
$ sudo useradd -r -s /usr/sbin/nologin rsyncd
$ sudo systemctl enable --now rsync
$ sudo ss -tlnp | grep :873
LISTEN 0 5 0.0.0.0:873 users:(("rsync",pid=12345,fd=3))

# ═══ ★★ 用戶端 ═══
$ rsync -av --list-only rsync://host/           # ★★ 列出 module
$ echo '很長的隨機密碼' | sudo tee /etc/rsync-backup.pass
$ sudo chmod 600 /etc/rsync-backup.pass
$ rsync -av --password-file=/etc/rsync-backup.pass \
    /var/www/app/ backupuser@10.10.20.50::backup/app/

# ═══ ★★★★ 走 SSH 隧道（★ 兼顧安全與速度）═══
$ ssh -f -N -L 8730:127.0.0.1:873 backup-server
$ rsync -av --password-file=/etc/rsync-backup.pass \
    --port=8730 /var/www/app/ backupuser@127.0.0.1::backup/app/
```

> [!danger] rsync daemon 的安全 ★★★★
> ```
> ★★★★ daemon 模式【預設沒有加密】
>   → 資料和密碼都是【明文傳輸】
>   → ★★★ 絕對不要在不可信的網路上使用
>   → ★★★★ 更不要對外開放 873 埠
>
> ★★★ 必要的設定：
>   ① ★★★★ hosts allow（★ 限制來源 IP）
>   ② ★★★ auth users + secrets file
>   ③ ★★★ use chroot = yes
>   ④ ★★ 只綁內網介面：address = 10.10.20.50
>   ⑤ ★★★ 防火牆只放行特定來源
>
> ★★★ 檢查有沒有對外開放：
>   $ sudo ss -tlnp | grep :873
>   LISTEN 0 5 0.0.0.0:873       ← ★★★★ 對外開放！
>   LISTEN 0 5 10.10.20.50:873   ← ★★★ 只綁內網，正確
>
> ★★★★ 建議：除非有明確的效能需求，一律用 SSH 模式
> ```

---

## 完整實戰範例：三層備份策略

```bash
#!/usr/bin/env bash
# ★★★★ /usr/local/bin/backup-tiers —— 3-2-1 備份策略
set -euo pipefail

SRC=/var/www/app
LOCAL_SNAP=/srv/backup/app          # ★ 第一層：本機快照
REMOTE=backup01                     # ★★ 第二層：內網備份機
OFFSITE=offsite01                   # ★★★ 第三層：異地
LOG=/var/log/backup.log
FAIL=0

log() { printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$LOG"; }

log "═══ 開始備份 $SRC ═══"

# ═══ ★★★★【0】備份前的一致性處理 ═══
log "【0】資料庫備份與應用一致性"
DB=$(grep '^DB_DATABASE=' "$SRC/current/.env" 2>/dev/null | cut -d= -f2- || echo "")
if [ -n "$DB" ]; then
    DU=$(grep '^DB_USERNAME=' "$SRC/current/.env" | cut -d= -f2-)
    DP=$(grep '^DB_PASSWORD=' "$SRC/current/.env" | cut -d= -f2-)
    mkdir -p "$SRC/shared/db-dump"
    MYSQL_PWD="$DP" mysqldump -h 127.0.0.1 -u "$DU" \
        --single-transaction --routines --triggers --no-tablespaces "$DB" | \
        gzip > "$SRC/shared/db-dump/$DB-$(date +%F).sql.gz"
    log "  ★ 資料庫已 dump"
    #   ★★★ 只保留最近 7 天的 dump
    find "$SRC/shared/db-dump" -name '*.sql.gz' -mtime +7 -delete
fi

# ═══ ★★★★【1】本機硬連結快照 ═══
log "【1】本機快照"
if /usr/local/bin/snapshot-backup "$SRC" "$LOCAL_SNAP" 30 >>"$LOG" 2>&1; then
    log "  ★ 本機快照完成"
else
    log "  ★★★★ 本機快照失敗"
    FAIL=$((FAIL+1))
fi

# ═══ ★★★【2】同步到內網備份機 ═══
log "【2】內網備份機"
if rsync -aAXH --numeric-ids --delete \
    --max-delete=500 \
    --backup --backup-dir="/srv/deleted/$(date +%F)" \
    --exclude-from=/etc/rsync-exclude-web.txt \
    --bwlimit=50m \
    --partial --timeout=600 \
    --stats \
    -e 'ssh -o BatchMode=yes -o ConnectTimeout=30' \
    "$LOCAL_SNAP/latest/" "$REMOTE:/srv/backup/app/" >>"$LOG" 2>&1; then
    log "  ★ 內網同步完成"
else
    log "  ★★★★ 內網同步失敗（exit=$?）"
    FAIL=$((FAIL+1))
fi

# ═══ ★★★【3】異地（★ 加密 + 限速 + 離峰）═══
log "【3】異地備份"
HOUR=$(date +%H)
if [ "$HOUR" -ge 1 ] && [ "$HOUR" -le 5 ]; then
    #   ★★★★ 異地備份前先加密
    TARBALL="/tmp/app-$(date +%F).tar.zst"
    tar --zstd -cf "$TARBALL" -C "$LOCAL_SNAP" latest/
    age -r "$(cat /etc/backup-age.pub)" -o "$TARBALL.age" "$TARBALL"
    shred -u "$TARBALL"

    if rsync -av --partial --bwlimit=10m --timeout=1800 \
        -e 'ssh -o BatchMode=yes' \
        "$TARBALL.age" "$OFFSITE:/srv/offsite/app/" >>"$LOG" 2>&1; then
        log "  ★ 異地備份完成"
        rm -f "$TARBALL.age"
    else
        log "  ★★★★ 異地備份失敗"
        FAIL=$((FAIL+1))
    fi
else
    log "  ★ 非離峰時段，跳過異地備份"
fi

# ═══ ★★★★【4】驗證（★ 這一步最常被省略，但最重要）═══
log "【4】★★★★ 驗證備份可用性"

#   ★★★ 本機快照
LATEST_FILES=$(find "$LOCAL_SNAP/latest/" -type f 2>/dev/null | wc -l)
SRC_FILES=$(find "$SRC/current/" -type f 2>/dev/null | wc -l)
log "  本機快照檔案數: $LATEST_FILES（來源 $SRC_FILES）"
[ "$LATEST_FILES" -gt $((SRC_FILES / 2)) ] || {
    log "  ★★★★ 快照檔案數異常偏低！"; FAIL=$((FAIL+1)); }

#   ★★★★ 抽樣比對雜湊
log "  ★★★ 抽樣比對 10 個檔案"
MISMATCH=0
find "$SRC/current/" -type f -name '*.php' 2>/dev/null | shuf -n 10 | \
  while read -r f; do
    rel="${f#$SRC/current/}"
    snap="$LOCAL_SNAP/latest/current/$rel"
    [ -f "$snap" ] || { echo "MISSING $rel"; continue; }
    a=$(sha256sum "$f" | awk '{print $1}')
    b=$(sha256sum "$snap" | awk '{print $1}')
    [ "$a" = "$b" ] || echo "MISMATCH $rel"
  done | tee -a "$LOG" | grep -q . && { log "  ★★★★ 有檔案不一致"; FAIL=$((FAIL+1)); } \
    || log "  ★ 抽樣比對通過"

#   ★★★ 遠端
REMOTE_FILES=$(ssh -o BatchMode=yes "$REMOTE" \
    "find /srv/backup/app -type f 2>/dev/null | wc -l" || echo 0)
log "  遠端檔案數: $REMOTE_FILES"
[ "$REMOTE_FILES" -gt $((SRC_FILES / 2)) ] || {
    log "  ★★★ 遠端檔案數異常"; FAIL=$((FAIL+1)); }

#   ★★★ 資料庫 dump 可以解壓嗎
if [ -n "$DB" ]; then
    LAST_DUMP=$(ls -1t "$SRC/shared/db-dump/"*.sql.gz 2>/dev/null | head -1)
    if [ -n "$LAST_DUMP" ] && gzip -t "$LAST_DUMP" 2>/dev/null; then
        SZ=$(stat -c%s "$LAST_DUMP")
        log "  ★ 資料庫 dump 完整（$(numfmt --to=iec "$SZ")）"
        [ "$SZ" -gt 1024 ] || { log "  ★★★★ dump 太小，可能失敗"; FAIL=$((FAIL+1)); }
    else
        log "  ★★★★ 資料庫 dump 損毀或不存在"
        FAIL=$((FAIL+1))
    fi
fi

# ═══ ★★★【5】空間監控 ═══
log "【5】空間"
df -h "$LOCAL_SNAP" | tail -1 | tee -a "$LOG"
USE=$(df --output=pcent "$LOCAL_SNAP" | tail -1 | tr -dc '0-9')
[ "$USE" -lt 85 ] || { log "  ★★★★ 備份磁碟使用率 ${USE}%"; FAIL=$((FAIL+1)); }
IUSE=$(df -i --output=ipcent "$LOCAL_SNAP" | tail -1 | tr -dc '0-9')
log "  inode 使用率: ${IUSE}%"
[ "$IUSE" -lt 85 ] || { log "  ★★★★ inode 使用率 ${IUSE}%（硬連結快照的常見問題）"; FAIL=$((FAIL+1)); }

# ═══ 【6】通知 ═══
if [ "$FAIL" -eq 0 ]; then
    log "═══ ★ 備份全部成功 ═══"
else
    log "═══ ★★★★ 備份有 $FAIL 項失敗 ═══"
    [ -n "${NOTIFY_WEBHOOK:-}" ] && curl -sf -X POST "$NOTIFY_WEBHOOK" \
        -H 'Content-Type: application/json' \
        -d "$(jq -n --arg h "$(hostname)" --arg n "$FAIL" \
              '{text: "❌ \($h) 備份失敗 \($n) 項，請檢查 /var/log/backup.log"}')" || true
fi
exit "$FAIL"
```

```bash
$ sudo install -m750 backup-tiers.sh /usr/local/bin/backup-tiers
$ sudo tee /etc/cron.d/backup >/dev/null <<'EOF'
NOTIFY_WEBHOOK=https://...
30 2 * * * root /usr/local/bin/backup-tiers 2>&1 | logger -t backup
EOF
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **多了一層目錄** ★★★★ | **來源結尾沒有斜線** | `rsync -av /src/ /dst/` |
| **每次都全部重傳** ★★★★ | **沒有 `-t`（時間戳）** | 用 **`-a`**；檢查兩邊時鐘 |
| **`--delete` 刪掉重要檔案** ★★★★ | 沒有 dry-run | **`-n` 先看**；`--max-delete`；`--backup-dir` |
| **排除規則沒生效** ★★★★ | **順序錯或缺 `--include='*/'`** | include 在 exclude 前；加 `*/` |
| **擁有者對不上** ★★★ | 名稱對應到不同 UID | **`--numeric-ids`** |
| **`--link-dest` 沒省空間** ★★★★ | **跨檔案系統**／路徑是相對的 | 同一個掛載點；用絕對路徑 |
| **inode 用完** ★★★ | 硬連結快照太多 | `df -i`；減少保留數；改用 ZFS/Btrfs |
| **`Permission denied`** ★★★ | 遠端權限 | 遠端用 `sudo rsync`；`--rsync-path='sudo rsync'` |
| **傳輸很慢** ★★★ | 加密/壓縮開銷 | `-e 'ssh -c aes128-gcm@openssh.com'`；`--skip-compress` |
| **中斷後從頭來** ★★★ | 沒有 `--partial` | **`-P`** |
| **SELinux 標籤沒保留** ★★★ | 缺 `-X` | `rsync -aX`；`restorecon -R` |
| **符號連結變實體檔** ★★ | 用了 `-L` | 用 `-a`（含 `-l`） |

### 排查

```bash
# 【1】★★★★ 一定要先 dry-run
$ rsync -avn --delete --stats /src/ /dst/ | tail -20

# 【2】★★★ 看排除規則怎麼比對的
$ rsync -avn --exclude-from=/etc/rsync-exclude.txt \
    --debug=FILTER /src/ /dst/ 2>&1 | head -30
$ rsync -avn --list-only --exclude='*.log' /src/ | head

# 【3】★★★ 為什麼這個檔案被傳了
$ rsync -avni /src/ /dst/ | head -20
>f.st...... file.txt
# ★★★ 第一欄：< 傳送 > 接收 c 建立 h 硬連結 . 無變化
# ★★★ 第二欄：f 檔案 d 目錄 L 連結
# ★★★★ 後面：s 大小不同 t 時間不同 p 權限 o 擁有者 g 群組

# 【4】★★★ 統計
$ rsync -av --stats /src/ /dst/ | tail -15
Number of files: 24,810
Number of created files: 142
Number of deleted files: 0
Total transferred file size: 48.2M bytes
Total bytes sent: 12.4M                    # ★★★ 實際的網路流量
speedup is 234.12                           # ★★★★ 增量的效率

# 【5】★★★★ 硬連結是否生效
$ ls -li /srv/backup/app/2026-08-2{7,8}*/composer.json
#   ★★★ inode 相同 = 硬連結成功
$ find /srv/backup/app/latest -links +1 | wc -l    # ★★ 有幾個是硬連結
$ du -sh /srv/backup/app/                          # ★★★ 實際總空間

# 【6】★★★ 空間與 inode
$ df -h /srv/backup
$ df -i /srv/backup                        # ★★★★ 硬連結快照要看這個

# 【7】★★ 時鐘同步（★ 影響增量比對）
$ date; ssh backup 'date'
$ timedatectl status | grep -E 'synchronized|NTP'
```

---

## 安全性注意事項

> [!danger] 五個要點 ★★★
> ```
> ① ★★★★ 排除機密檔案
>      → .env、私鑰、auth.json 不應該進備份（★ 或要加密）
>      → ★★★ 備份被入侵 = 所有憑證外洩
>
> ② ★★★★ 限制備份用的 SSH 金鑰
>      → ★★★ 用 command= 限制只能執行 rsync
>      → ★★ from= 限制來源 IP
>      → ★★★ 不要用有 sudo 權限的帳號
>
> ③ ★★★ 備份的權限
>      → ★★★★ 備份目錄 700，只有 root 能讀
>      → ★★ 備份含所有資料 = 最高機密
>
> ④ ★★★★ 異地備份要加密
>      → ★★★ 資料離開你的控制範圍
>      → age / gpg / restic
>
> ⑤ ★★★★ 定期做還原演練
>      → ★★★ 沒有驗證過的備份 = 沒有備份
>      → ★★ 至少每季一次
> ```

```bash
# ═══ ★★★★ 限制備份用的 SSH 金鑰 ═══
# 在【備份接收端】的 ~/.ssh/authorized_keys
$ cat >> /home/backup/.ssh/authorized_keys <<'EOF'
command="/usr/local/bin/rrsync -wo /srv/backup",restrict,from="10.10.20.31" ssh-ed25519 AAAA... backup@web01
EOF
#   ★★★★ command=      強制只能執行這個指令
#   ★★★ rrsync         OpenSSH 附的 rsync 包裝腳本（限制目錄）
#   ★★★ -wo            只允許寫入（write-only，★ 讀不出來）
#   ★★★ restrict       停用所有轉發、TTY、agent
#   ★★★ from=          限制來源 IP

# ★★ 找出 rrsync
$ ls /usr/share/doc/rsync/scripts/rrsync* /usr/bin/rrsync 2>/dev/null
$ sudo cp /usr/share/doc/rsync/scripts/rrsync /usr/local/bin/ 2>/dev/null
$ sudo chmod 755 /usr/local/bin/rrsync

# ★★★ 驗證限制生效
$ ssh -i ~/.ssh/backup_key backup@backup01 'ls /'
#   ★★★ 應該失敗或只執行 rrsync
$ rsync -av /var/www/app/ backup@backup01:/srv/backup/app/    # ★★ 應該成功
$ rsync -av backup@backup01:/etc/ /tmp/                        # ★★★★ 應該失敗（-wo）

# ═══ ★★★★ 備份中的機密掃描 ═══
$ sudo tee /usr/local/bin/check-backup-secrets >/dev/null <<'EOF'
#!/usr/bin/env bash
# ★★★ 檢查備份中有沒有不該存在的機密
DIR="${1:?}"
echo "═══ 掃描 $DIR ═══"
FOUND=0
while IFS= read -r f; do
    printf "★★★★ %s\n" "$f"
    FOUND=$((FOUND+1))
done < <(find "$DIR" \( -name '.env' -o -name '.env.*' -o -name 'auth.json' \
         -o -name 'id_rsa' -o -name 'id_ed25519' -o -name '*.pem' -o -name '*.key' \) \
         -type f 2>/dev/null)
if [ "$FOUND" -gt 0 ]; then
    echo "★★★★ 找到 $FOUND 個機密檔案！檢查 exclude 規則"
    exit 1
fi
echo "★ 沒有發現機密檔案"
EOF
$ sudo chmod +x /usr/local/bin/check-backup-secrets
$ sudo check-backup-secrets /srv/backup/app/latest

# ═══ ★★★ 備份目錄的權限 ═══
$ sudo chmod 700 /srv/backup
$ sudo chown root:root /srv/backup
$ ls -ld /srv/backup
drwx------ 5 root root 4096 Aug 28 18:30 /srv/backup

# ═══ ★★★★ 異地備份的加密 ═══
$ sudo apt install -y age
$ age-keygen -o /etc/backup-age.key
$ sudo chmod 600 /etc/backup-age.key
$ grep 'public key' /etc/backup-age.key | awk '{print $NF}' | \
    sudo tee /etc/backup-age.pub
#   ★★★★ 私鑰要【異地保存】（★ 不能只放在被備份的機器上！）

$ tar --zstd -cf - -C /srv/backup latest/ | \
    age -r "$(cat /etc/backup-age.pub)" -o /tmp/backup.tar.zst.age
$ rsync -av /tmp/backup.tar.zst.age offsite:/srv/offsite/

# ★★★ 還原
$ age -d -i /etc/backup-age.key -o /tmp/backup.tar.zst /tmp/backup.tar.zst.age
$ tar --zstd -xf /tmp/backup.tar.zst -C /restore/

# ═══ ★★★★ 還原演練（★ 每季一次）═══
$ sudo tee /usr/local/bin/restore-drill >/dev/null <<'EOF'
#!/usr/bin/env bash
# ★★★★ 還原演練：把備份還原到臨時目錄並驗證
set -euo pipefail
SNAP="${1:?用法: restore-drill <快照路徑>}"
TARGET=$(mktemp -d /tmp/restore-drill.XXXXXX)
trap 'rm -rf "$TARGET"' EXIT

echo "═══ 還原演練 $SNAP → $TARGET ═══"
time rsync -aAXH --numeric-ids "$SNAP/" "$TARGET/"

echo -e "\n【驗證】"
FILES=$(find "$TARGET" -type f | wc -l)
echo "  檔案數: $FILES"
[ "$FILES" -gt 0 ] || { echo "★★★★ 還原是空的"; exit 1; }

#   ★★★ 應用程式層的驗證
[ -f "$TARGET/current/artisan" ] && {
    php "$TARGET/current/artisan" --version && echo "  ★ artisan 可執行"
}
[ -f "$TARGET/current/composer.json" ] && {
    jq -e . "$TARGET/current/composer.json" >/dev/null && echo "  ★ composer.json 有效"
}

#   ★★★ 資料庫 dump
DUMP=$(find "$TARGET" -name '*.sql.gz' | head -1)
[ -n "$DUMP" ] && {
    gzip -t "$DUMP" && echo "  ★ 資料庫 dump 完整"
    zcat "$DUMP" | head -20 | grep -q 'MySQL dump' && echo "  ★ dump 格式正確"
}

echo -e "\n★ 還原演練通過"
echo "$(date -Is)|還原演練|$SNAP|$FILES 檔案|PASS" >> /var/log/restore-drill.log
EOF
$ sudo chmod +x /usr/local/bin/restore-drill
$ sudo restore-drill /srv/backup/app/latest
```

---

## 速查表

### ★★★★ 結尾斜線

```
rsync -av /src/ /dst/     ★★★ 內容 → dst/file
rsync -av /src  /dst/     ★★★★ 目錄 → dst/src/file（多一層！）
腳本中：SRC="${SRC%/}/"    確保只有一個斜線
```

### `-a` 的內容

```
-a = -rlptgoD（遞迴/連結/權限/時間/群組/擁有者/裝置）
★★★★ 不含：-A（ACL）-X（xattr）-H（硬連結）-S（稀疏）
完整保留：sudo rsync -aAXH --numeric-ids --sparse /src/ /dst/
★★★★ 跨機器一定要 --numeric-ids
```

### ★★★★ --delete 安全網

```bash
rsync -avn --delete /src/ /dst/          # ★★★★ 一定先 dry-run
--max-delete=100                          # ★★★★ 超過就中止
--backup --backup-dir=/srv/deleted/$(date +%F)   # ★★★ 刪前先搬
--delete-excluded                         # ★★★★ 危險！連排除的也刪
```

### ★★★ 排除規則

```bash
--exclude='*.log' --exclude='node_modules/'
--exclude-from=/etc/rsync-exclude.txt
--include='*/' --include='*.conf' --exclude='*'   # ★★★★ 只要 .conf
★★★★ 順序：第一個符合的決定；include 要在 exclude 前
★★★★ 遞迴要加 --include='*/'
```

### ★★★★ 硬連結快照

```bash
rsync -aAXH --numeric-ids --delete \
  --link-dest=/backup/2026-08-27 \
  /src/ /backup/2026-08-28/
# ★★★★ 限制：同一個檔案系統；不防檔案系統損毀；吃 inode
ls -li a/f b/f      # ★★★ inode 相同 = 硬連結成功
df -i               # ★★★★ 監控 inode
```

### 續傳與限速

```bash
-P                      # ★★★★ = --partial --progress
--partial-dir=.rsync-partial
--bwlimit=10m           # ★★★ 限速
--timeout=600 --contimeout=30
--skip-compress=gz/zip/jpg/mp4    # ★★ 已壓縮的不再壓
-e 'ssh -c aes128-gcm@openssh.com'  # ★★★ 快的加密演算法
```

### ★★★ 排錯

```bash
rsync -avn --stats /src/ /dst/        # ★★★★ dry-run
rsync -avni /src/ /dst/               # ★★★ 為什麼傳這個檔案
rsync -avn --debug=FILTER ...         # ★★★ 排除規則怎麼比對
rsync -av --stats ... | tail          # speedup 看增量效率
```

### ★★★★ 安全

```bash
# authorized_keys 限制備份金鑰
command="/usr/local/bin/rrsync -wo /srv/backup",restrict,from="10.10.20.31" ssh-ed25519 ...
chmod 700 /srv/backup                          # ★★★ 備份目錄
★★★★ exclude：.env / *.pem / *.key / auth.json
★★★★ 異地備份加密：age -r <公鑰>（私鑰要異地保存！）
★★★★ 每季做還原演練（沒驗證過的備份 = 沒有備份）
```

---

## 練習題

> [!question]- 練習 1：結尾斜線 ★★★★
> 1. **建立 `/tmp/src` 含幾個檔案**
> 2. **`rsync -av /tmp/src/ /tmp/dst1/`** → `find /tmp/dst1` 看結果
> 3. **`rsync -av /tmp/src /tmp/dst2/`** → 呢？
> 4. **在 dst2 加一個檔案，然後用不加斜線 + `--delete` 同步**
> 5. **原本的檔案怎麼了？**
> 6. **寫一個腳本用 `${SRC%/}/` 確保正確**

> [!question]- 練習 2：增量與時間戳 ★★★★
> 1. **`rsync -rv /src/ /dst/`（★ 注意是 -r 不是 -a）**
> 2. **再執行一次** → 有重傳嗎？為什麼？
> 3. **改用 `-a` 再測一次** → 呢？
> 4. **用 `--stats` 看 `speedup`**
> 5. **`touch` 一個檔案再同步** → 只傳那一個嗎？
> 6. **用 `-c`（checksum）比較速度**

> [!question]- 練習 3：排除規則 ★★★★
> 1. **建立含 `node_modules/`、`.env`、`*.log` 的測試目錄**
> 2. **用 `--exclude` 排除，`-n` 確認**
> 3. **試 `--include='*.conf' --exclude='*'`** → 有傳到子目錄的嗎？
> 4. **加上 `--include='*/'` 再試** → 呢？為什麼？
> 5. **把 include 和 exclude 順序對調** → 結果如何？
> 6. **用 `--debug=FILTER` 看比對過程**

> [!question]- 練習 4：硬連結快照 ★★★★
> 1. **用 `snapshot-backup` 做第一次備份**
> 2. **改一兩個檔案，再做一次**
> 3. **`du -sh` 每個快照** → 加起來多少？
> 4. **`du -sh` 整個備份根目錄** → 差多少？
> 5. **`ls -li` 比對沒改過的檔案** → inode 相同嗎？
> 6. **`df -i`** → inode 用了多少？做 30 次會怎樣？

> [!question]- 練習 5：安全與還原 ★★★★
> 1. **設定一個 `command="rrsync -wo ..."` 的備份金鑰**
> 2. **用它 rsync 上傳** → 成功嗎？
> 3. **用它 `ssh` 執行 `ls /`** → 呢？
> 4. **用它從遠端拉檔案** → 呢？為什麼？
> 5. **用 `age` 加密備份並還原**
> 6. **執行 `restore-drill` 並記錄結果**

---

## 小測驗

Q1. **`rsync -av /src/ /dst/` 和 `rsync -av /src /dst/` 的差別**？

Q2. **`-a` 包含哪些選項？不包含哪些重要的**？

Q3. **為什麼 `-t`（保留時間戳）是增量同步的關鍵**？

Q4. **跨機器同步為什麼一定要 `--numeric-ids`**？

Q5. **使用 `--delete` 的三個安全措施**？

Q6. **`--include='*.conf' --exclude='*'` 為什麼可能傳不到子目錄的檔案**？

Q7. **`--link-dest` 的原理與四個限制**？

Q8. **`rsync -avni` 的輸出 `>f.st......` 是什麼意思**？

Q9. **備份用的 SSH 金鑰該怎麼限制**？

Q10. **「沒有驗證過的備份 = 沒有備份」該怎麼做驗證**？

> [!question]- 測驗答案
> **Q1.** **★★★★ 來源結尾的斜線決定「複製內容」還是「連目錄一起複製」**。
> **`/src/`（有斜線）** = 把 `/src` **裡面的東西**複製到 `/dst/` →
> 結果是 `/dst/file1`、`/dst/file2`。
> **`/src`（沒斜線）** = 把 `/src` **這個目錄本身**複製過去 →
> 結果是 **`/dst/src/file1`**（多了一層）。
> **記法：「有斜線 = 只要內容」**。
> **目標端的斜線不影響結果**（但習慣上都加）。
> **★★★★ 這個錯誤配合 `--delete` 會造成災難** ——
> 忘記斜線導致資料進到 `/backup/app/app/`，
> 而 `--delete` 把 `/backup/app/` 底下**原本的備份全部刪光**。
> **防護**：腳本中用 `SRC="${SRC%/}/"`（去掉再加，確保只有一個），
> 而且**一定要先 `--dry-run`**。
>
> **Q2.** **`-a` = `-rlptgoD`**：
> `-r` 遞迴、**`-l` 保留符號連結**、`-p` 權限模式、
> **`-t` 修改時間**（增量比對的關鍵）、`-g` 群組、
> `-o` 擁有者（需 root）、`-D` 裝置與特殊檔（需 root）。
> **★★★★ 不包含但很重要的**：
> **`-A`（ACL）**、**`-X`（擴充屬性，SELinux 標籤在這裡）**、
> **`-H`（硬連結）**、`-S`（稀疏檔案，VM 映像很重要）、
> **`--numeric-ids`（用數字 UID/GID）**、`-z`（壓縮傳輸）。
> **完整保留的標準寫法**：
> ```bash
> sudo rsync -aAXH --numeric-ids --sparse /src/ /dst/
> ```
> 少了 `-X` 的話，SELinux 系統上還原後可能因為標籤錯誤而服務起不來
> （要另外跑 `restorecon -R`）。
>
> **Q3.** 因為 **rsync 判斷「檔案是否需要傳輸」的預設方式是「比對大小 + 修改時間」**。
> **沒有 `-t` 的話**，每次傳完目標端的 mtime 都會變成「現在」——
> **下次執行時所有檔案的時間都對不上，rsync 認為全部都變了 → 全部重傳**，
> 增量同步完全失效。
> 這在大型目錄上的差異是「傳 48MB」vs「傳 2.8GB」。
> **所以 `-a`（含 `-t`）幾乎是必加的**。
> **相關的比對方式**：
> `--checksum`/`-c`（用 MD5 比對內容，最準確但慢）、
> `--size-only`（只比大小，適合來源 mtime 不可靠時）、
> `--update`/`-u`（只在來源較新時才傳，不覆蓋目標端較新的檔案）。
> **也要注意兩台機器的時鐘要同步**（`timedatectl`）。
>
> **Q4.** 因為 **rsync 預設用「使用者名稱」做對應，而兩台機器的同一個名稱可能對應到不同的 UID**。
> 例如 A 機的 `www-data` 是 UID 33，B 機是 UID 82；
> 或是 B 機根本沒有 `www-data` 這個使用者。
> **後果**：還原時檔案的擁有者變成錯的 UID，
> **權限模型整個亂掉**（web server 讀不到自己的檔案，
> 或更糟 —— 檔案變成某個不相干使用者可寫）。
> **`--numeric-ids` 直接保存數字 UID/GID，不做名稱對應** ——
> 還原到同一台機器或相同的使用者配置時完全正確。
> ```bash
> sudo rsync -aAXH --numeric-ids /src/ backup:/dst/
> ```
> `tar` 的對應選項是 `--numeric-owner`。
> **注意保留擁有者需要遠端有 root 權限**（`--rsync-path='sudo rsync'`）。
>
> **Q5.** ①**★★★★ 先跑 `--dry-run`（`-n`）** ——
> 配合 `--stats` 看「Number of deleted files」是不是合理的數字；
> ②**★★★★ `--max-delete=N`** ——
> 要刪除的檔案超過 N 個就**中止整個作業，什麼都不刪**。
> 這能防止「來源端出問題（磁碟未掛載、目錄被誤刪）導致備份端跟著被清空」的災難：
> ```bash
> rsync -av --delete --max-delete=100 /src/ /dst/
> # rsync error: --max-delete limit exceeded (28)
> ```
> ③**★★★ `--backup --backup-dir=/srv/deleted/$(date +%F)`** ——
> 刪除的檔案先搬到備份目錄而不是直接消失，**可以救回來**。
> **另外要小心 `--delete-excluded`** ——
> 它會**連被 `--exclude` 排除的檔案也一起刪除**，
> 這常常不是你要的（例如目標端的 `logs/` 會被清空）。
>
> **Q6.** 因為 **目錄本身也符合 `'*'` 這個排除規則** ——
> rsync 比對到某個子目錄時，`--include='*.conf'` 不符合（目錄名沒有 `.conf`），
> 接著 `--exclude='*'` 符合 → **這個目錄被排除，rsync 不會進去**，
> 自然找不到裡面的 `.conf` 檔案。
> **★★★★ 解法：加上 `--include='*/'`**（讓所有目錄都被包含）：
> ```bash
> rsync -av --include='*/' --include='*.conf' --exclude='*' /etc/ /backup/
> ```
> **規則的比對順序**：由上到下，**第一個符合的規則決定結果**，後面不再看。
> 所以 `--include` 一定要在 `--exclude='*'` **之前**；
> 順序對調的話所有東西都會被排除。
> 除錯用 **`rsync -avn --debug=FILTER`** 可以看到每個檔案的比對過程。
>
> **Q7.** **原理**：對於**內容沒有變更**的檔案，
> rsync 不複製資料，而是在新快照中**建立指向 `--link-dest` 目錄中該檔案的硬連結** ——
> 同一份資料只佔一次磁碟空間，但**每個快照看起來都是完整的目錄樹**。
> 100GB 的資料每天變動 1GB，保留 30 天：
> 傳統要 3TB，**硬連結快照只要約 129GB（省 95%）**。
> **四個限制**：
> ①**★★★★ 必須在同一個檔案系統**（硬連結不能跨檔案系統）；
> ②**★★★ 不能防止檔案系統損毀** ——
> 所有快照共用同一份資料，**磁碟壞了全部一起沒**，
> 必須搭配**異地備份**（3-2-1 原則）；
> ③**★★★ 大量消耗 inode** —— 每個快照的每個檔案都要一個目錄項，
> 用 `df -i` 監控；
> ④**★★ 刪除舊快照很慢**（要處理幾萬個硬連結）。
> **更好的替代是 ZFS/Btrfs 的原生快照**。
>
> **Q8.** **`rsync -avni` 的 `-i`（`--itemize-changes`）逐項列出變更原因**，
> 格式是 11 個字元：
> ```
> >f.st......
> ││││││││││└─ 各屬性
> │││││└──────
> ││││└─ t: 時間戳不同
> │││└─ s: 大小不同
> ││└─ . : 這個屬性沒變
> │└─ f: 檔案（d 目錄、L 符號連結）
> └─ >: 傳送到遠端（< 接收、c 建立、h 硬連結、. 無變化、* 訊息）
> ```
> **`>f.st......` = 「傳送一個檔案，因為大小和時間戳都不同」**。
> 常見的還有：
> `>f+++++++++` = 新建的檔案（所有屬性都是新的）；
> `.f...p.....` = 只有權限改變（不傳內容）；
> `cd+++++++++` = 建立目錄；
> `*deleting` = 刪除。
> **這是排查「為什麼這個檔案又被傳了」最有效的工具**。
>
> **Q9.** **★★★★ 在接收端的 `~/.ssh/authorized_keys` 加上限制**：
> ```
> command="/usr/local/bin/rrsync -wo /srv/backup",restrict,from="10.10.20.31" ssh-ed25519 AAAA... backup@web01
> ```
> **四個限制**：
> ①**`command="..."`** —— **強制只能執行這個指令**，
> 使用者送來的任何指令都被忽略；
> ②**`rrsync -wo /srv/backup`** ——
> OpenSSH 附的 rsync 包裝腳本，**限制只能在指定目錄操作**，
> **`-wo` 是 write-only（只能寫入，不能讀出來）** ——
> 這樣即使備份來源被入侵，攻擊者也**無法從備份機拉回其他機器的資料**；
> ③**`restrict`** —— 停用所有轉發（TCP/agent/X11）、TTY、隧道；
> ④**`from="10.10.20.31"`** —— 限制來源 IP。
> **另外**：不要用有 sudo 權限的帳號做備份，
> 備份目錄權限 700，`rrsync` 要從 `/usr/share/doc/rsync/scripts/` 複製出來。
>
> **Q10.** **★★★★ 做「還原演練」—— 實際把備份還原出來並驗證可用性**。
> 只檢查「備份任務有沒有報錯」是不夠的 ——
> 常見的失敗是：備份成功但內容是空的、
> 資料庫 dump 因為權限問題只有錯誤訊息、
> 加密的備份沒有私鑰無法解開、快照因為 `--exclude` 太寬而少了關鍵檔案。
> **驗證的四個層次**：
> ①**★★ 數量檢查** —— 備份的檔案數和來源相比是否合理；
> ②**★★★ 抽樣雜湊比對** —— 隨機挑 10 個檔案比對 SHA256；
> ③**★★★★ 應用層驗證** ——
> `php artisan --version` 能執行嗎、`jq -e . composer.json` 有效嗎、
> `gzip -t dump.sql.gz` 完整嗎、dump 的大小合理嗎；
> ④**★★★★ 完整還原演練** ——
> 還原到臨時環境並實際啟動服務，**至少每季一次**，並記錄結果。
> **加密的異地備份特別要注意：私鑰必須異地保存**，
> 不能只放在被備份的那台機器上（機器沒了連備份都解不開）。

---

## 延伸閱讀

- [[060-01-06-01-guide-傳輸-scp與sftp傳輸]] — SSH 傳輸與受限帳號
- [[060-01-06-03-guide-傳輸-備份策略與還原演練]] — **★★★★ 3-2-1 原則與完整流程**
- [[020-01-24-guide-進階儲存-ZFS與Btrfs]] — 原生快照（比硬連結更好）
- [[090-03-04-guide-應用安全-備份災難復原與入侵應變]] — 災難復原
- [[020-01-08-cmd-Linux-檔案權限與擁有者]] — 權限與 ACL
- [[020-01-18-guide-Linux-排程工作]] — 排程備份
