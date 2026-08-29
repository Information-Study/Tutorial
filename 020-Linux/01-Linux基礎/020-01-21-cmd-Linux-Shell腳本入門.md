---
title: "Shell 腳本入門"
desc: "變數、條件、迴圈與參數處理，寫出第一個實用腳本"
aliases: [bash script, shebang, shell腳本]
tags: [群組/Linux, linux/基礎, 主題/shell]
category: Linux基礎
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[020-01-20-guide-Linux-環境變數與設定檔]]"]
updated: 2026-08-29
---

# Shell 腳本入門

> [!abstract] 這篇你會學到
> - 從 shebang 開始寫出正確、可執行的腳本，並知道 `#!/bin/sh` 與 `#!/bin/bash` 的差別 ★★★
> - 用**引號**與 `[[ ]]` 避開 80% 的新手 bug（空白、空值、萬用字元） ★★★★★
> - 條件、迴圈、函式與參數處理的正確寫法，特別是 **`"$@"` 與 `$*` 的差別** ★★★
> - 用 `shellcheck` 在執行前抓出錯誤——這比任何教學都能提升你的腳本品質 ★★★
> - 寫出一個完整的、可放進 cron 的維運腳本 ★★

## 前置知識

- [[020-01-20-guide-Linux-環境變數與設定檔]]
- [[020-01-11-cmd-Linux-輸入輸出重導向與管線]]

---

## 觀念說明

### ★★ 腳本就是「把你在終端機打的指令存成檔案」

任何在終端機能跑的指令，寫進檔案就是腳本。差別只在：
腳本**不會有人在旁邊按 Enter 確認**，所以錯誤處理要自己寫。

```bash
cat > hello.sh <<'SCRIPT'
#!/usr/bin/env bash
echo "Hello, $(whoami)! 今天是 $(date +%F)"
SCRIPT
chmod +x hello.sh                # ★★★ 沒有執行權限，執行時會得到 Permission denied
./hello.sh                       # ★★★ 必須有 ./，直接打 hello.sh 會 command not found
```

```
Hello, mike! 今天是 2026-08-27
```

★★★ 三件事缺一不可：**shebang**（第一行）、**執行權限**（`chmod +x`）、
**用路徑執行**（`./`，原因見 [[020-01-04-cmd-Linux-檔案系統與目錄結構]]）。

### ★★★★ shebang：`#!/bin/sh` 還是 `#!/bin/bash`

| 寫法 | 意義 | 何時用 |
| --- | --- | --- |
| ★★★ `#!/bin/sh` | POSIX shell（Ubuntu 上是 **dash**，不是 bash） | 需要極高可攜性、只用 POSIX 語法 |
| ★★ `#!/bin/bash` | 明確指定 bash | 一般 Linux 腳本 |
| ★★★★ **`#!/usr/bin/env bash`** | 從 PATH 找 bash | **建議寫法**，跨平台（macOS 的 bash 不在 /bin） |

> [!danger] `#!/bin/sh` 在 Ubuntu 上不是 bash ★★★★
> ```bash
> ls -l /bin/sh
> ```
> ```
> lrwxrwxrwx 1 root root 4 ... /bin/sh -> dash
> ```
> dash 是精簡的 POSIX shell，**不支援** `[[ ]]`、陣列、`function`、
> `<<<`、`${var//x/y}` 等 bash 語法。
>
> 症狀是這種讓人一頭霧水的錯誤：
> ```
> ./script.sh: 5: [[: not found
> ./script.sh: 8: Syntax error: "(" unexpected
> ```
> ★★★★ **用了 bash 語法就寫 `#!/usr/bin/env bash`。** RHEL 的 `/bin/sh` 是 bash，
> 所以同一支腳本在 RHEL 正常、在 Ubuntu 壞掉——這是跨發行版最常見的坑。

### ★★★ 執行方式的差別

```bash
./script.sh          # ★★ 子程序執行，依 shebang 選直譯器
bash script.sh       # ★★ 子程序執行，強制用 bash（不需執行權限）
source script.sh     # ★★★ 在「目前的」shell 執行（變數會留下來）
. script.sh          # ★ 同 source
```

見 [[020-01-20-guide-Linux-環境變數與設定檔]]——只有 `source` 能把變數帶回目前 shell。

---

## 基礎操作

### ★★★ 變數

```bash
name="Mike"                  # ★★★ ✗ 等號兩邊不能有空白：name = "Mike" 會錯
count=42
today=$(date +%F)            # ★★ 指令替換（用 $()，不要用反引號）
files=$(ls /etc | wc -l)

echo "$name"                 # ★★★★★ 一律加雙引號
echo "${name}_backup"        # ★★ 接其他文字時用大括號
echo '$name'                 # ★ 單引號：完全照字面
```

> [!danger] 變數永遠加雙引號，這是 bash 的第一守則 ★★★★★
> ```bash
> file="my report.txt"
> cat $file        # ★★★ ✗ 被切成 cat my report.txt → 兩個檔案
> cat "$file"      # ✓
>
> dir=""
> rm -rf $dir/*    # ★★★★★ ✗ 變成 rm -rf /*
> rm -rf "${dir:?}"/*   # ★★★★ ✓ 空值就報錯停下
> ```
> ★★★★ 不加引號的三種災難：**空白被切開、空值消失、`*` 被展開**。
> 唯一不需要引號的情況是你**刻意**要它被切開（例如 `$@` 的特殊處理，見下方）。

**字串操作**（不用開 `sed`）：

```bash
path="/var/log/nginx/access.log"
echo "${path##*/}"           # ★★★ access.log        （去掉最長的 */ 前綴 = basename）
echo "${path%/*}"            # ★★★ /var/log/nginx    （去掉最短的 /* 後綴 = dirname）
echo "${path%.log}"          # /var/log/nginx/access
echo "${path/log/LOG}"       # 取代第一個
echo "${path//log/LOG}"      # ★★ 取代全部
echo "${#path}"              # 長度
echo "${path:0:4}"           # 子字串 /var
echo "${name^^}"             # 大寫
echo "${name,,}"             # 小寫
```

| 語法 | 記法 |
| --- | --- |
| ★★★ `${v#pat}` / `${v##pat}` | `#` 在鍵盤左邊 → 從**前面**刪（一個 = 最短，兩個 = 最長） |
| ★★★ `${v%pat}` / `${v%%pat}` | `%` 在右邊 → 從**後面**刪 |

**預設值**（在 [[020-01-20-guide-Linux-環境變數與設定檔]] 詳述）：

```bash
port="${PORT:-8080}"              # ★★ 沒設就用 8080
target="${1:?用法: $0 <目標>}"    # ★★★ 沒給參數就報錯退出
```

### ★★★ 條件判斷

```bash
if [[ -f "$file" ]]; then
    echo "是檔案"
elif [[ -d "$file" ]]; then
    echo "是目錄"
else
    echo "不存在"
fi
```

> [!tip] 一律用 `[[ ]]`，不要用 `[ ]` ★★★★
> `[[ ]]` 是 bash 關鍵字，`[ ]` 是舊的 `test` 指令。`[[ ]]` 的優勢：
> - ★★★ 變數**不會**被切詞：`[[ -f $file ]]` 空白也安全（但還是建議加引號）
> - ★★ 支援 `&&`、`||`、`=~`（正規表示式）、`<`（字串比較）
> - ★★★ 空變數不會造成語法錯誤
>
> ```bash
> [ $var = "x" ]      # ★★★ var 為空時 → [ = "x" ] → 語法錯誤
> [[ $var = "x" ]]    # ★★ 正常運作
> ```
> ★★★ 只有在寫 `#!/bin/sh` 的 POSIX 腳本時才用 `[ ]`。

常用測試：

| 測試 | 意義 |
| --- | --- |
| ★★★ `-f` / `-d` / `-e` | 是檔案 / 是目錄 / 存在 |
| ★★ `-r` / `-w` / `-x` | 可讀 / 可寫 / 可執行 |
| ★★ `-s` | 存在且非空 |
| ★ `-L` | 是符號連結 |
| ★★★ `-z "$s"` / `-n "$s"` | 字串為空 / 非空 |
| ★★★ `"$a" == "$b"` / `!=` | 字串相等 / 不等 |
| ★★★ `"$s" == pat*` | 萬用字元比對（**右邊不加引號**） |
| ★★★ `"$s" =~ ^[0-9]+$` | 正規表示式（**右邊不加引號**） |
| ★★★ `-eq -ne -lt -le -gt -ge` | 整數比較 |
| ★ `f1 -nt f2` / `-ot` | 檔案較新 / 較舊 |

```bash
# ★★ 數字比較用 (( ))，更直覺
if (( count > 10 && count < 100 )); then echo "範圍內"; fi

# ★★★ 檔案測試組合
[[ -f "$conf" && -r "$conf" ]] || { echo "設定檔不可讀" >&2; exit 1; }

# ★★★ 正規表示式並擷取群組
if [[ "$ip" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
    echo "第一段：${BASH_REMATCH[1]}"
fi
```

> [!warning] `=` 與 `-eq` 不能混用 ★★★
> ```bash
> [[ "10" -eq "10.0" ]]     # ★★★ 錯誤：-eq 只吃整數
> [[ "10" == "010" ]]       # ★★ false：字串比較
> (( 10 == 010 ))           # ★★★★ 注意 010 是八進位 = 8！
> ```
> ★★★ 字串用 `==`，整數用 `-eq` 或 `(( ))`。

**`case`**：多分支比 `if-elif` 乾淨 ★★

```bash
case "$1" in
    start)          systemctl start myapp ;;
    stop)           systemctl stop myapp ;;
    restart|reload) systemctl "$1" myapp ;;
    -h|--help)      usage; exit 0 ;;
    *)              echo "未知指令：$1" >&2; exit 1 ;;   # ★★★ 一定要有 * 分支，否則打錯字會靜默通過
esac
```

### ★★★ 迴圈

```bash
# ★★★ 逐檔處理（用 glob，不要 parse ls）
for f in /var/log/*.log; do
    [[ -e "$f" ]] || continue        # ★★★ glob 沒比對到時 $f 會是字面 "*.log"
    echo "處理 $f"
done

# 數字範圍
for i in {1..5}; do echo "$i"; done
for (( i=0; i<5; i++ )); do echo "$i"; done

# ★★★★ 逐行讀檔（正確寫法）
while IFS= read -r line; do
    echo "行：$line"
done < /etc/hosts

# ★★★ 讀指令輸出
while IFS= read -r host; do
    ping -c1 -W1 "$host" &>/dev/null && echo "$host 通" || echo "$host 不通"
done < <(awk '{print $1}' hosts.txt)

# ★★ 陣列
servers=(web01 web02 db01)
for s in "${servers[@]}"; do ssh "$s" uptime; done
echo "共 ${#servers[@]} 台"
```

> [!danger] 逐行讀檔的三個必要條件 ★★★★
> ```bash
> while IFS= read -r line; do ... done < file
> ```
> - ★★ **`IFS=`** — 保留行首行尾的空白
> - ★★★ **`-r`** — 不要把 `\` 當跳脫字元（路徑含 `\` 時會壞）
> - ★★★★ **`< file`** 而不是 `cat file | while` — 管線會開子 shell，
>   迴圈裡設的變數在迴圈外**看不到**
>
> ```bash
> count=0
> cat file | while read -r l; do ((count++)); done
> echo "$count"          # ★★★★ 0！子 shell 的變數消失了
>
> while read -r l; do ((count++)); done < file
> echo "$count"          # ★★ 正確
> ```

> [!warning] 不要用 `for line in $(cat file)` ★★★
> 它用空白切詞而不是換行，一行「hello world」會變成兩次迴圈。
> ★★★ 而且會展開萬用字元。**一律用 `while read`。**

### ★★★ 函式

```bash
log() {
    echo "[$(date '+%F %T')] $*" >&2      # ★★★ 日誌寫到 stderr，不污染 stdout
}

check_root() {
    if (( EUID != 0 )); then
        log "需要 root 權限"
        return 1
    fi
}

backup_file() {
    local src="$1"                         # ★★★ local：不污染全域
    local dst="${2:-$src.bak}"
    [[ -f "$src" ]] || { log "找不到 $src"; return 1; }
    cp -a "$src" "$dst" && log "已備份 $src → $dst"
}

check_root || exit 1
backup_file /etc/nginx/nginx.conf
```

> [!tip] 函式的三個習慣 ★★★
> 1. ★★ **參數一律先存成 `local` 變數**——可讀性與防止污染
> 2. ★★★ **回傳值用 `return`（0～255 的狀態碼），資料用 `echo`**：
>    ```bash
>    get_ip() { hostname -I | awk '{print $1}'; }
>    ip=$(get_ip)
>    ```
> 3. ★★★ **日誌走 stderr**（`>&2`），這樣 `result=$(func)` 只會抓到真正的資料

### ★★★★ 參數處理

```bash
echo "腳本名稱：$0"
echo "第一個參數：$1，第二個：$2"
echo "參數個數：$#"
echo "所有參數：$@"
echo "上一個指令的退出碼：$?"   # ★★★ $? 只反映「上一個」指令，要用就先存起來
echo "目前 PID：$$"
```

> [!danger] `"$@"` 與 `"$*"` 的差別會咬人 ★★★★
> | 寫法 | 展開結果 | 用途 |
> | --- | --- | --- |
> | ★★★★ **`"$@"`** | `"a" "b c" "d"`（**保留每個參數的邊界**） | **轉傳參數給其他指令，幾乎永遠用這個** |
> | ★★ `"$*"` | `"a b c d"`（合併成一個字串） | 只有要組成一行訊息時 |
> | ★★★ `$@` / `$*` 不加引號 | 全部重新切詞 | ✗ 不要用 |
>
> ```bash
> wrapper() { rsync -a "$@"; }          # ★★★★ ✓ "my dir/" 完整傳過去
> wrapper() { rsync -a $*; }            # ★★★★ ✗ 被切成 my 和 dir/
> ```

**`shift` 與簡單的選項解析**：

```bash
#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<USAGE
用法: $0 [-n] [-t 目標] 檔案...
  -n        試跑，不實際執行
  -t 目標   備份目的地（預設 /backup）
USAGE
}

dry_run=false
target=/backup

while getopts ":nt:h" opt; do     # ★★★ 開頭的 : 讓缺參數時走 :) 分支，而不是印出系統預設錯誤
    case "$opt" in
        n) dry_run=true ;;
        t) target="$OPTARG" ;;
        h) usage; exit 0 ;;
        :) echo "選項 -$OPTARG 需要參數" >&2; exit 1 ;;
        \?) echo "未知選項 -$OPTARG" >&2; usage; exit 1 ;;
    esac
done
shift $((OPTIND - 1))          # ★★★ 移除已處理的選項，剩下的是位置參數

(( $# > 0 )) || { usage; exit 1; }

for f in "$@"; do
    if $dry_run; then
        echo "[試跑] 會備份 $f → $target"
    else
        cp -a "$f" "$target/"
    fi
done
```

```bash
./backup.sh -n -t /mnt/bak /etc/hosts "/var/www/my site"
```

> [!tip] `getopts` 只支援短選項 ★★
> `-n`、`-t 值` 可以，`--dry-run` 不行。需要長選項時：
> 簡單情況用 `case "$1" in --dry-run) ...; shift ;;` 手動迴圈；
> ★★ 複雜情況考慮改用 Python。**腳本超過 200 行或選項超過五個，
> 通常就該換語言了。**

### ★★★ 退出碼與錯誤處理

```bash
command && echo "成功" || echo "失敗"

if ! systemctl is-active --quiet nginx; then
    echo "nginx 沒在跑" >&2
    exit 1
fi

# ★★★ 自訂退出碼讓呼叫者能區分錯誤
[[ -f "$conf" ]] || exit 2        # ★★ 2 = 設定檔不存在
ping -c1 "$host" || exit 3        # ★★ 3 = 網路不通
```

| 退出碼 | 慣例 |
| --- | --- |
| ★★ `0` | 成功 |
| ★★ `1` | 一般錯誤 |
| ★★ `2` | 用法錯誤（參數不對） |
| ★★★ `126` | 找到檔案但無法執行（權限） |
| ★★★ `127` | 指令找不到 |
| ★★★ `128+N` | 被訊號 N 殺掉（`130` = Ctrl+C，`137` = SIGKILL） |

### ★★★★★ `set -euo pipefail`：每支腳本的第一行

```bash
#!/usr/bin/env bash
set -euo pipefail     # ★★★★★ 三個選項缺一不可
```

| 選項 | 作用 | 沒有它會怎樣 |
| --- | --- | --- |
| ★★★★ **`-e`** | 任何指令失敗就中止 | 失敗後繼續執行，用壞掉的狀態做下一步 |
| ★★★★★ **`-u`** | 用到未定義變數就報錯 | `rm -rf "$UNDEFINED"/*` 變成 `rm -rf /*` |
| ★★★★ **`-o pipefail`** | 管線中任一段失敗即視為失敗 | `mysqldump \| gzip` 的 dump 失敗被吞掉 |

詳細的陷阱與進階用法（`trap`、`-e` 在條件式中的例外）見 [[020-01-22-guide-Linux-Shell腳本進階]]。

> [!warning] `-e` 下「預期會失敗」的指令要明確處理 ★★★★
> ```bash
> set -e
> grep "pattern" file          # ★★★★ 找不到時 grep 回傳 1 → 腳本直接死掉
> grep "pattern" file || true  # ★★★ ✓ 允許失敗
> if grep -q "pattern" file; then ...; fi   # ★★★ ✓ 在條件式中不觸發 -e
> ```

---

## 進階用法：`shellcheck`

```bash
sudo apt install -y shellcheck           # ★★★ Ubuntu/Debian 的套件名全小寫
shellcheck script.sh                     # ★★★★ 寫完必跑，零警告才算完成
```

```
In script.sh line 12:
for f in $(ls *.log); do
         ^---------^ SC2045: Iterating over ls output is fragile. Use globs.

In script.sh line 15:
rm -rf $dir/*
       ^--^ SC2086: Double quote to prevent globbing and word splitting.
```

> [!tip] shellcheck 是寫 bash 最有價值的單一工具 ★★★★
> 它抓的每一條都附有編號（`SC2086`），去 <https://www.shellcheck.net/wiki/SC2086>
> ★★★★ 有完整解釋與正確寫法。**把它當成 bash 的老師**，
> 跑幾次之後你自然就不會再寫出那些錯誤。
>
> ★★★ 整合進編輯器（VSCode 的 ShellCheck 擴充）或 git pre-commit hook，
> 讓有問題的腳本進不了版本庫。

★★ 刻意忽略某條規則時要註明理由：

```bash
# shellcheck disable=SC2086  # ★★ 這裡刻意要切詞
cmd $flags
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照 ★★★
> bash 語法完全相同。差異：
> - ★★★★ RHEL 的 `/bin/sh` **就是 bash**（Ubuntu 是 dash），所以
>   「在 RHEL 能跑的 `#!/bin/sh` 腳本到 Ubuntu 壞掉」很常見——
>   一律寫 `#!/usr/bin/env bash` 就沒這問題
> - ★★★ `shellcheck`：`dnf install -y ShellCheck`（需 EPEL，注意大小寫）
> - ★★★ RHEL 最小安裝可能沒有 `bc`、`jq`，腳本依賴時要檢查

---

## 完整實戰範例：服務健康檢查腳本

★★★★ 一支可放進 cron 或 timer 的完整腳本，包含本篇所有要素：

```bash
#!/usr/bin/env bash
# ★★★★ healthcheck.sh — 檢查服務、磁碟、憑證，異常時告警
set -euo pipefail   # ★★★★★ 少了這行，任何一步失敗都會被忽略、繼續往下跑

# ── 設定（可被環境變數覆寫）────────────────────────
SERVICES="${SERVICES:-nginx php8.3-fpm mysql}"
DISK_WARN="${DISK_WARN:-85}"
CERT_DAYS="${CERT_DAYS:-14}"
DOMAIN="${DOMAIN:-example.com}"
ALERT_CMD="${ALERT_CMD:-logger -t healthcheck}"   # ★★★ 預設寫進 syslog

# ── 工具函式 ─────────────────────────────────────
log()   { echo "[$(date '+%F %T')] $*" >&2; }   # ★★★ 日誌走 stderr
alert() { log "ALERT: $*"; $ALERT_CMD "❌ $(hostname): $*"; }

usage() {
    cat <<USAGE
用法: $0 [-q] [-d 網域]
  -q       安靜模式，只輸出異常
  -d 網域  檢查該網域的憑證（預設 $DOMAIN）
環境變數: SERVICES DISK_WARN CERT_DAYS ALERT_CMD
USAGE
}

# ── 參數 ─────────────────────────────────────────
quiet=false
while getopts ":qd:h" opt; do
    case "$opt" in
        q) quiet=true ;;
        d) DOMAIN="$OPTARG" ;;
        h) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done

problems=0

# ── 1. 服務 ──────────────────────────────────────
for svc in $SERVICES; do   # ★★ 這裡刻意不加引號，要靠空白把清單切成多個服務名
    if systemctl is-active --quiet "$svc"; then
        $quiet || log "✓ $svc 執行中"
    else
        alert "服務 $svc 未執行"
        ((problems++)) || true   # ★★★★ set -e 下 ((0++)) 回傳 1 會中止腳本
    fi
done

# ── 2. 磁碟 ──────────────────────────────────────
while IFS= read -r line; do
    usage_pct=$(awk '{print $5}' <<< "$line" | tr -d '%')   # ★★ 去掉百分號才能做數字比較
    mount=$(awk '{print $6}' <<< "$line")
    if (( usage_pct >= DISK_WARN )); then
        alert "磁碟 $mount 使用率 ${usage_pct}%"
        ((problems++)) || true
    else
        $quiet || log "✓ $mount ${usage_pct}%"
    fi
done < <(df -P -x tmpfs -x devtmpfs -x squashfs | tail -n +2)   # ★★★ -P 保證單行輸出

# ── 3. 憑證到期 ───────────────────────────────────
if expiry=$(echo | timeout 5 openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" 2>/dev/null \
            | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2); then   # ★★★★ 網路操作一定要有 timeout
    expiry_ts=$(date -d "$expiry" +%s)
    days_left=$(( (expiry_ts - $(date +%s)) / 86400 ))
    if (( days_left < CERT_DAYS )); then   # ★★★★ 憑證過期＝全站白畫面
        alert "$DOMAIN 憑證 $days_left 天後到期"
        ((problems++)) || true
    else
        $quiet || log "✓ $DOMAIN 憑證還有 $days_left 天"
    fi
else
    alert "無法取得 $DOMAIN 的憑證"
    ((problems++)) || true
fi

# ── 結果 ─────────────────────────────────────────
if (( problems == 0 )); then
    $quiet || log "全部正常"
    exit 0   # ★★★ 正常結束回 0
else
    log "發現 $problems 個問題"
    exit 1   # ★★★ 有問題回非 0，cron 與 systemd 才判斷得出來
fi
```

```bash
chmod +x healthcheck.sh
shellcheck healthcheck.sh && echo "shellcheck 通過"   # ★★★★ 上線前必跑
./healthcheck.sh
./healthcheck.sh -q            # ★★★ 放進 cron 用這個
DISK_WARN=50 ./healthcheck.sh  # ★★ 用環境變數覆寫門檻
```

> [!tip] 這支腳本裡值得注意的設計 ★★★
> | 設計 | 理由 |
> | --- | --- |
> | ★★ 設定可被環境變數覆寫 | 同一支腳本適用不同機器 |
> | ★★★ 日誌走 stderr | 未來要 `$(...)` 抓輸出時不會混進日誌 |
> | ★★★★ `((problems++)) \|\| true` | `set -e` 下 `((0++))` 回傳 1 會中止腳本，這是必要的防護 |
> | ★★ `df -P -x tmpfs` | `-P` 保證單行輸出好解析；排除虛擬檔案系統 |
> | ★★★★ `timeout 5 openssl` | 網路操作一定要有逾時，否則 cron 裡會掛住 |
> | ★★★ 退出碼 0/1 | 讓 systemd 的 `OnFailure=` 能觸發（見 [[020-01-18-guide-Linux-排程工作]]） |

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ `[[: not found` / `Syntax error: "(" unexpected` | 用 `#!/bin/sh` 跑 bash 語法（Ubuntu 的 sh 是 dash） | 改 `#!/usr/bin/env bash` |
| ★★ `Permission denied` | 沒執行權限 | `chmod +x`，或 `bash script.sh` |
| ★★ `command not found` 但檔案存在 | 沒寫 `./` | `./script.sh` |
| ★★★★ `bad interpreter: No such file or directory` | **CRLF 換行**（Windows 編輯過） | `dos2unix`；見 [[020-01-06-cmd-Linux-檢視檔案內容]] |
| ★★ `name = "x"` 說 name: command not found | 等號旁有空白 | `name="x"` |
| ★★★★ 檔名含空白時只處理一半 | 變數沒加引號 | `"$var"` |
| ★★★ 迴圈裡設的變數外面是空的 | `cat \| while` 開了子 shell | `while ... done < file` |
| ★★★ `for line in $(cat f)` 一行變多行 | 用空白切詞 | `while IFS= read -r` |
| ★★★ glob 沒比對到時迴圈跑了一次字面 `*.log` | bash 預設行為 | 迴圈內 `[[ -e "$f" ]] \|\| continue`，或 `shopt -s nullglob` |
| ★★★★ `set -e` 下腳本莫名中止 | 某指令回傳非 0（如 `grep` 沒找到） | `cmd \|\| true` 或放進 `if` |
| ★★★ `$*` 把含空白的參數切壞 | 用錯 | `"$@"` |
| ★★★ `(( count++ ))` 在 `set -e` 下中止 | 值為 0 時算式回傳 1 | `((count++)) \|\| true` 或 `count=$((count+1))` |
| ★★ 數字比較說 integer expression expected | 用 `-eq` 比小數或字串 | 字串用 `==`，整數才用 `-eq` |
| ★★★★ 腳本在 cron 失敗 | 環境不同 | 見 [[020-01-18-guide-Linux-排程工作]]、[[020-01-20-guide-Linux-環境變數與設定檔]] |

---

## 安全性注意事項

> [!danger] 絕對不要把使用者輸入直接拼進指令 ★★★★★
> ```bash
> read -r name
> eval "ls $name"                # ★★★★★ ✗ 輸入 "; rm -rf /" 就完了
> bash -c "ls $name"             # ★★★★★ ✗ 同樣危險
> ls -- "$name"                  # ★★★★ ✓ 當成單一參數，且 -- 防止被當選項
> ```
> ★★★★★ `eval` 幾乎永遠不該出現在維運腳本裡。

> [!warning] 暫存檔用 `mktemp`，並在結束時清掉 ★★★★
> ```bash
> tmp=$(mktemp) || exit 1    # ★★★ 隨機檔名，權限 600
> trap 'rm -f "$tmp"' EXIT   # ★★★★ 腳本無論怎麼結束都會清掉
> ```
> ★★★★ 固定檔名（`/tmp/myscript.tmp`）有符號連結攻擊風險，
> 見 [[020-01-04-cmd-Linux-檔案系統與目錄結構]]。`trap` 的用法在 [[020-01-22-guide-Linux-Shell腳本進階]]。

> [!warning] 腳本的權限與擁有者 ★★★★★
> ★★★★★ 以 root 執行的腳本若可被其他人寫入，等於把 root 送出去。
> ```bash
> sudo install -m 755 -o root -g root script.sh /usr/local/bin/script   # ★★★★ 只有 root 能改
> ```
> 見 [[020-01-18-guide-Linux-排程工作]] 的排程腳本稽核。

> [!tip] 機密不寫進腳本 ★★★★
> 密碼、token 放 `EnvironmentFile` 或權限 600 的設定檔，腳本裡只讀取。
> ★★★★ 腳本會進版本控制、會被複製、會被 `cat` 給同事看。
> 見 [[090-03-03-guide-應用安全-機密管理與金鑰保護]]。

---

## 速查表

### ★★★★ 骨架

```bash
#!/usr/bin/env bash
set -euo pipefail   # ★★★★★ 必備
usage() { echo "用法: $0 ..."; }
log()   { echo "[$(date '+%F %T')] $*" >&2; }   # ★★★ 日誌走 stderr
main()  { ...; }
main "$@"   # ★★★★ 一定是 "$@"
```

### ★★★ 變數與字串

| 語法 | 說明 |
| --- | --- |
| ★★ `v="x"` / `v=$(cmd)` | 賦值 / 指令替換 |
| ★★★★★ `"$v"` / `"${v}_x"` | **永遠加引號** / 接文字用大括號 |
| ★★★ `${v:-def}` / `${v:?err}` | 預設值 / 未設報錯 |
| ★★★ `${v##*/}` / `${v%/*}` | basename / dirname |
| ★★ `${v/a/b}` / `${v//a/b}` | 取代第一個 / 全部 |
| ★★ `${#v}` / `${v:0:3}` | 長度 / 子字串 |

### ★★★ 條件與迴圈

| 語法 | 說明 |
| --- | --- |
| ★★★ `[[ -f "$f" ]]` | 檔案測試（用 `[[`，不用 `[`） |
| ★★★ `[[ "$a" == "$b" ]]` / `(( a > b ))` | 字串 / 整數 |
| ★★ `[[ "$s" =~ regex ]]` | 正規表示式，結果在 `BASH_REMATCH` |
| ★★ `case "$x" in a\|b) ;; *) ;; esac` | 多分支 |
| ★★★ `for f in *.log; do` | glob 迴圈 |
| ★★★★ `while IFS= read -r l; do ... done < f` | **逐行讀檔標準寫法** |
| ★★★ `for s in "${arr[@]}"` | 陣列迴圈 |

### ★★★ 函式與參數

| 語法 | 說明 |
| --- | --- |
| ★★ `f() { local x="$1"; ...; }` | 函式，參數存 local |
| ★★★ `return N` / `echo data` | 狀態碼 / 回傳資料 |
| ★★★★ **`"$@"`** | **轉傳所有參數（保留邊界）** |
| ★★ `$#` / `$0` / `$?` / `$$` | 參數數 / 腳本名 / 退出碼 / PID |
| ★★ `getopts ":nt:h" opt` | 短選項解析 |
| ★★★ `shift $((OPTIND-1))` | 移除已解析選項 |

### ★★★★ 工具

| 指令 | 說明 |
| --- | --- |
| ★★★★ **`shellcheck script.sh`** | **靜態檢查，必跑** |
| ★★ `bash -n script.sh` | 只檢查語法 |
| ★★★ `bash -x script.sh` | 逐行印出執行過程（除錯） |
| ★★★★ `mktemp` + `trap ... EXIT` | 安全暫存檔 |

---

## 練習題

> [!question]- 練習 1：修正一支問題腳本 ★★★★
> 下面這支腳本有至少五個問題，用 `shellcheck` 找出來並修正：
> ```bash
> #!/bin/sh
> DIR=$1
> for f in $(ls $DIR/*.log); do
>   if [ $(wc -l < $f) -gt 1000 ]; then
>     gzip $f
>   fi
> done
> echo done
> ```
>
> **解答**
>
> ```bash
> shellcheck bad.sh
> ```
> ★★★ 會列出 SC2045（parse ls）、SC2086（未加引號）×多處、SC2046。
> 此外還有 `#!/bin/sh` 卻可能用到 bash 語法、`$1` 未檢查、
> glob 無比對時的字面值問題。修正版：
> ```bash
> #!/usr/bin/env bash
> set -euo pipefail
>
> dir="${1:?用法: $0 <目錄>}"
> [[ -d "$dir" ]] || { echo "不是目錄：$dir" >&2; exit 2; }
>
> shopt -s nullglob                      # ★★★ glob 沒比對到就展開成空
> for f in "$dir"/*.log; do
>     lines=$(wc -l < "$f")
>     if (( lines > 1000 )); then
>         gzip "$f"
>         echo "已壓縮 $f（$lines 行）"
>     fi
> done
> echo "完成"
> ```
> 再跑一次 `shellcheck`，應該零警告。
> ★★★★ **養成習慣：寫完就 shellcheck，零警告才算完成。**

> [!question]- 練習 2：`"$@"` 與 `"$*"` 的實驗 ★★★
> 寫一支腳本印出它收到的每個參數（各自一行），
> 傳入 `a "b c" d`，比較四種寫法的輸出。
>
> **解答**
>
> ```bash
> cat > args.sh <<'S'
> #!/usr/bin/env bash
> echo '── "$@" ──'; for x in "$@"; do echo "[$x]"; done
> echo '── "$*" ──'; for x in "$*"; do echo "[$x]"; done
> echo '── $@ ──';   for x in $@;   do echo "[$x]"; done
> echo '── $* ──';   for x in $*;   do echo "[$x]"; done
> S
> chmod +x args.sh; ./args.sh a "b c" d
> ```
> ```
> ── "$@" ──
> [a]
> [b c]        ← 唯一保留了 "b c" 是一個參數的寫法
> [d]
> ── "$*" ──
> [a b c d]    ← 全黏成一個
> ── $@ ──
> [a]
> [b]          ← 被切開了
> [c]
> [d]
> ── $* ──
> [a]
> [b]
> [c]
> [d]
> ```
> ★★★★ **結論**：轉傳參數只有 `"$@"` 是對的。

> [!question]- 練習 3：寫一支批次連線檢查腳本 ★★★
> 給定一個主機清單檔（每行一個主機名），依序 SSH 上去執行 `uptime`，
> 連不上的要記錄下來，最後統計成功與失敗數。要求通過 shellcheck。
>
> **解答**
>
> ```bash
> #!/usr/bin/env bash
> set -euo pipefail
>
> list="${1:?用法: $0 <主機清單檔>}"
> [[ -r "$list" ]] || { echo "讀不到 $list" >&2; exit 2; }
>
> ok=0; fail=0; failed_hosts=()
>
> while IFS= read -r host; do
>     [[ -z "$host" || "$host" == \#* ]] && continue       # ★★ 跳過空行與註解
>     if out=$(ssh -o ConnectTimeout=5 -o BatchMode=yes "$host" uptime 2>&1); then
>         printf '%-20s %s\n' "$host" "$out"
>         ((ok++)) || true
>     else
>         printf '%-20s ✗ %s\n' "$host" "$out" >&2
>         failed_hosts+=("$host")
>         ((fail++)) || true
>     fi
> done < "$list"
>
> echo "──────────"
> echo "成功 $ok，失敗 $fail"
> (( fail == 0 )) || { printf '失敗清單：%s\n' "${failed_hosts[*]}"; exit 1; }
> ```
> ★★★★ 重點：`BatchMode=yes` 讓 SSH 在需要密碼時直接失敗而不是卡住等輸入
> （放進 cron 必備）；`ConnectTimeout` 避免單一主機拖死整個流程；
> 陣列收集失敗主機供事後處理；退出碼反映整體結果。
> 進一步的平行化與錯誤處理見 [[020-01-22-guide-Linux-Shell腳本進階]]。

---

## 小測驗

Q1. Ubuntu 上 `#!/bin/sh` 實際是哪個 shell？用了 `[[ ]]` 會怎樣？建議的 shebang？
Q2. `./script.sh`、`bash script.sh`、`source script.sh` 三者差別？
Q3. `name = "Mike"` 為什麼報 `name: command not found`？
Q4. 不加引號的變數有哪三種災難？
Q5. `[[ ]]` 比 `[ ]` 好在哪？何時才用 `[ ]`？
Q6. `cat file | while read l; do ((n++)); done; echo $n` 印什麼？為什麼？正確寫法？
Q7. `for line in $(cat file)` 的兩個問題？
Q8. `"$@"` 與 `"$*"` 差別？轉傳參數該用哪個？
Q9. `set -euo pipefail` 三個選項各擋什麼？
Q10. `set -e` 下 `grep pattern file` 找不到會怎樣？兩種處理？

> [!question]- 測驗答案
> **Q1.** ★★★★ dash；報 `[[: not found`；`#!/usr/bin/env bash`（見「shebang」）。
> **Q2.** ★★★ 前兩者在子程序執行（第二種不需執行權限、強制用 bash）；`source` 在目前 shell 執行，變數會留下。
> **Q3.** ★★ 等號兩邊不能有空白，shell 把 `name` 當指令執行。
> **Q4.** ★★★★★ 空白被切開、空值消失（`rm -rf $dir/*` 變 `/*`）、`*` 被展開。
> **Q5.** ★★★ 變數不切詞、空值不出語法錯誤、支援 `&&` `||` `=~`；只有寫 POSIX `#!/bin/sh` 腳本時才用 `[ ]`。
> **Q6.** ★★★★ `0`（或空）——管線開子 shell，迴圈內的變數消失；`while IFS= read -r l; do ...; done < file`。
> **Q7.** ★★★ 用空白切詞（一行「a b」變兩次）且會展開萬用字元；用 `while read`。
> **Q8.** ★★★★ `"$@"` 保留每個參數邊界，`"$*"` 合併成一個字串；轉傳用 `"$@"`。
> **Q9.** ★★★★★ `-e` 失敗即中止、`-u` 未定義變數報錯、`pipefail` 管線任一段失敗即失敗。
> **Q10.** ★★★★ 回傳 1 觸發 `-e` 腳本中止；`grep ... || true` 或放進 `if grep -q`。

---

## 延伸閱讀

- [[020-01-22-guide-Linux-Shell腳本進階]] — `trap`、錯誤處理、鎖檔、平行執行 ★★★★
- [[020-01-11-cmd-Linux-輸入輸出重導向與管線]] — 重導向與 `pipefail`
- [[020-01-12-cmd-Linux-文字處理三劍客]] — 在腳本中用 `awk`/`sed` 處理資料
- [[020-01-18-guide-Linux-排程工作]] — 讓腳本自動執行
- [[020-01-20-guide-Linux-環境變數與設定檔]] — 變數作用域與環境
- ShellCheck wiki：<https://www.shellcheck.net/wiki/>
- `man 1 bash` / `help [[` / `help getopts`
