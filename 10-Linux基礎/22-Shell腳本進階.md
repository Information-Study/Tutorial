---
title: "Shell 腳本進階"
desc: "函式、陣列、trap、錯誤處理與可維護腳本的寫法"
aliases: [trap, set -e, 錯誤處理, 鎖檔, 冪等]
tags: [linux/基礎, 主題/shell]
category: Linux基礎
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[21-Shell腳本入門]]"]
updated: 2026-08-27
---

# Shell 腳本進階

> [!abstract] 這篇你會學到
> - 摸清 `set -e` 的**六個不會觸發的例外**，不再被它的「不一致」嚇到
> - 用 `trap` 做清理與回滾，讓腳本不管怎麼死都不留殘骸
> - 寫出**冪等**（重跑 N 次結果一樣）的腳本——這是能放進自動化的門檻
> - 用鎖檔防重疊、用 `timeout` 防卡死、用 `xargs -P` 安全平行化
> - 用 `bash -x` 與 `PS4` 精準除錯，並建立可維護腳本的結構慣例

## 前置知識

- [[21-Shell腳本入門]]

---

## 觀念說明

### 維運腳本與一次性腳本的差別

| | 一次性腳本 | 維運腳本 |
| --- | --- | --- |
| 誰執行 | 你，看著它跑 | cron / systemd / 同事，**沒人在看** |
| 失敗時 | 你會發現 | **必須自己偵測、自己通知、自己收拾** |
| 重跑 | 很少 | 經常（重試、排程、災後） |
| 環境 | 你的 shell | 極簡且不可預測（見 [[20-環境變數與設定檔]]） |

本篇的所有技巧都圍繞一件事：**讓腳本在沒人看的情況下也能正確、安全地失敗**。

---

## `set -e` 的真相

`set -e` 讓失敗的指令中止腳本，但它有**明確定義的例外**，
不知道這些就會覺得它「時靈時不靈」。

### 不會觸發 `-e` 的六種情況

```bash
set -e

# 1. 條件式裡的指令
if grep -q x file; then :; fi        # grep 失敗不會中止 ✓ 合理

# 2. && 或 || 左邊的指令
grep -q x file && echo found         # grep 失敗不會中止 ✓ 合理
grep -q x file || true               # 標準的「允許失敗」寫法

# 3. 管線中非最後一段（除非 pipefail）
false | true                         # 不中止 → 所以要 set -o pipefail

# 4. 函式被用在條件式裡時，函式「內部」的 -e 整個失效！
check() { false; echo "還在跑"; }
if check; then :; fi                 # 印出「還在跑」——函式內的 false 沒中止它

# 5. 指令替換在非賦值語境
echo "$(false)"                      # 不中止（bash < 4.4 連賦值都不中止）

# 6. 算式結果為 0
((count++))                          # count 原本是 0 → 算式值 0 → 回傳 1 → 中止！
```

> [!danger] 第 4 點是最陰險的
> ```bash
> set -e
> deploy() {
>     rsync -a src/ dst/               # 失敗了……
>     systemctl restart app            # 但仍會執行！
> }
> if deploy; then echo "OK"; fi       # 因為 deploy 在 if 裡，內部 -e 全失效
> ```
> 你以為 `rsync` 失敗會停下，實際上重啟了一個沒部署完的服務。
>
> 解法：**函式裡的關鍵步驟自己判斷**，不要依賴 `-e`：
> ```bash
> deploy() {
>     rsync -a src/ dst/ || return 1
>     systemctl restart app || return 1
> }
> ```

> [!danger] 第 6 點會讓計數器炸掉腳本
> ```bash
> set -e
> n=0
> ((n++))          # 後綴 ++ 回傳「舊值」0 → 算式為假 → 退出碼 1 → 腳本死
> echo "到不了這裡"
> ```
> 三種寫法都安全：
> ```bash
> ((n++)) || true
> n=$((n + 1))
> ((++n))           # 前綴 ++ 回傳新值 1（但 n 從 -1 開始時仍會炸）
> ```

### 結論：`-e` 是安全網，不是錯誤處理

```bash
set -euo pipefail          # 一定要開，它擋住「忘記檢查」的情況

# 但關鍵步驟仍要明確處理
cp -a "$src" "$dst" || { log "複製失敗"; exit 1; }
```

> [!tip] 需要暫時關閉時用區塊
> ```bash
> set +e
> some_command_that_may_fail
> rc=$?
> set -e
> if (( rc != 0 )); then ...; fi
> ```

---

## `trap`：不管怎麼死都要收拾

`trap` 註冊「收到訊號或事件時執行的程式碼」。

```bash
trap '指令' 訊號或事件...
```

| 事件 | 觸發時機 |
| --- | --- |
| **`EXIT`** | **腳本結束（正常、`exit`、被 `-e` 中止都算）** |
| `ERR` | 任一指令失敗（配合 `-e` 用） |
| `INT` | Ctrl+C |
| `TERM` | `kill` 預設訊號 |
| `HUP` | 終端機斷線 |
| `RETURN` | 函式或 source 結束 |
| `DEBUG` | 每個指令執行前（除錯用） |

### 模式一：暫存檔清理

```bash
#!/usr/bin/env bash
set -euo pipefail

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT        # 不管怎麼結束都會清

# ……用 $tmpdir 做事……
# 中途 exit 1、被 -e 中止、Ctrl+C，tmpdir 都會被清掉
```

> [!tip] `trap` 要在建立資源**之後立刻**註冊
> ```bash
> tmpdir=$(mktemp -d)
> trap 'rm -rf "$tmpdir"' EXIT     # ← 緊接著這行
> ```
> 中間隔了會失敗的指令，那個指令失敗時 trap 還沒註冊，暫存目錄就留下來了。

> [!warning] trap 字串用單引號
> ```bash
> trap "rm -rf $tmpdir" EXIT    # ✗ 雙引號：註冊時就展開了，之後 tmpdir 變了也不跟
> trap 'rm -rf "$tmpdir"' EXIT  # ✓ 單引號：執行 trap 時才展開
> ```
> 而且雙引號版本在 `tmpdir` 為空時會變成 `rm -rf`（雖然無害，但這種模式在別處會出事）。

### 模式二：錯誤時報告位置

```bash
#!/usr/bin/env bash
set -euo pipefail

on_error() {
    local rc=$? line=$1
    echo "❌ 第 $line 行失敗（退出碼 $rc）：${BASH_COMMAND}" >&2
    # 這裡可以送告警
}
trap 'on_error $LINENO' ERR
```

```
❌ 第 23 行失敗（退出碼 1）：rsync -a /src/ /dst/
```

### 模式三：回滾

```bash
#!/usr/bin/env bash
set -euo pipefail

CONF=/etc/nginx/nginx.conf
BAK="$CONF.bak-$$"

rollback() {
    local rc=$?
    if (( rc != 0 )) && [[ -f "$BAK" ]]; then
        echo "⚠ 失敗，還原設定" >&2
        cp -a "$BAK" "$CONF"
        systemctl reload nginx || true
    fi
    rm -f "$BAK"
    exit "$rc"                       # 保留原本的退出碼
}
trap rollback EXIT

cp -a "$CONF" "$BAK"
sed -i 's/worker_connections 768/worker_connections 4096/' "$CONF"
nginx -t                             # 失敗 → -e 中止 → EXIT trap 還原
systemctl reload nginx
echo "✓ 完成"
```

> [!tip] EXIT trap 裡的 `$?` 是腳本的退出碼
> 第一行就要 `local rc=$?` 存起來，後面任何指令都會覆蓋它。
> 最後 `exit "$rc"` 把原本的碼傳回去，呼叫者（cron、systemd）才知道失敗了。

### 模式四：優雅處理中斷

```bash
cleanup() {
    echo "收到中斷，正在停止背景工作……" >&2
    kill "${bg_pid:-}" 2>/dev/null || true
    wait "${bg_pid:-}" 2>/dev/null || true
    exit 130                         # 128 + 2 (SIGINT) 的慣例
}
trap cleanup INT TERM

long_task &
bg_pid=$!
wait "$bg_pid"
```

沒有這段，Ctrl+C 只殺掉腳本，`long_task` 會變成孤兒繼續跑
（見 [[10-程序管理與訊號]]）。

---

## 冪等：重跑不會壞

**冪等**（idempotent）= 執行一次和執行十次的結果相同。
這是腳本能進自動化的門檻——排程重試、災後重跑、同事誤按兩次都不會出事。

| 非冪等 ✗ | 冪等 ✓ |
| --- | --- |
| `mkdir /data` | `mkdir -p /data` |
| `useradd app` | `id app &>/dev/null \|\| useradd app` |
| `echo "x" >> /etc/conf` | `grep -qxF "x" /etc/conf \|\| echo "x" >> /etc/conf` |
| `ln -s a b` | `ln -sfn a b` |
| `apt install x` | `dpkg -s x &>/dev/null \|\| apt-get install -y x` |
| `systemctl enable x` | 本身就冪等 ✓ |
| `mv a b` | `[[ -e a ]] && mv a b` |
| `sed -i 's/old/new/'` | `grep -q new f \|\| sed -i 's/old/new/' f` |

```bash
# 冪等地確保一行設定存在
ensure_line() {
    local line="$1" file="$2"
    grep -qxF -- "$line" "$file" 2>/dev/null || echo "$line" >> "$file"
}
ensure_line "vm.swappiness=10" /etc/sysctl.d/99-custom.conf

# 冪等地確保設定值（存在就改，不存在就加）
ensure_kv() {
    local key="$1" val="$2" file="$3"
    if grep -qE "^\s*#?\s*${key}\b" "$file"; then
        sed -i -E "s|^\s*#?\s*${key}\b.*|${key} ${val}|" "$file"
    else
        echo "${key} ${val}" >> "$file"
    fi
}
ensure_kv PermitRootLogin no /etc/ssh/sshd_config
```

> [!tip] 冪等的思考方式：「確保狀態」而不是「執行動作」
> 不要想「建立目錄」，想「確保目錄存在」；
> 不要想「加一行」，想「確保那一行在」。
> 這也是 Ansible 等組態管理工具的核心思想——見 [[06-TWGCB-Linux大量派送]]。

---

## 鎖檔：防止重疊執行

排程腳本跑超過間隔、或有人手動又跑一次，會出現兩份同時執行。

```bash
#!/usr/bin/env bash
set -euo pipefail

LOCK="/var/lock/$(basename "$0").lock"
exec 9>"$LOCK"
if ! flock -n 9; then
    echo "另一個實例正在執行，退出" >&2
    exit 0                           # 用 0：這不是錯誤，是預期行為
fi
# 鎖會在腳本結束（fd 9 關閉）時自動釋放，不需手動 rm
```

| 寫法 | 行為 |
| --- | --- |
| `flock -n 9` | 拿不到就立刻失敗（**排程用這個**） |
| `flock -w 30 9` | 最多等 30 秒 |
| `flock 9` | 一直等 |

> [!warning] 不要用「檢查 PID 檔存在」當鎖
> ```bash
> [[ -f /var/run/x.pid ]] && exit    # ✗
> ```
> 上次腳本被 `kill -9` 沒清掉 PID 檔，之後永遠不會再跑。
> `flock` 綁的是**檔案描述符**，程序死了核心會自動釋放，沒有殘留問題。
> 在 [[18-排程工作]] 也提到用 `flock -n lockfile cmd` 從 cron 端包住。

---

## 逾時與平行

### `timeout`：防止卡死

```bash
timeout 30 curl -sS https://slow.example.com/api
timeout -s KILL 60 ./stubborn-task.sh        # 30 秒後送 TERM，仍不死就 KILL
timeout -k 10 60 ./task.sh                   # 60 秒 TERM，再 10 秒後 KILL
echo $?                                      # 124 = 逾時
```

> [!tip] 網路操作與外部指令一律包 `timeout`
> cron 裡一支卡住的腳本會累積成幾十個殭屍程序，
> 而你要等到磁碟或 PID 用完才會發現。**沒有逾時的網路呼叫是定時炸彈。**

### 安全的平行執行

```bash
# 簡單：& 與 wait
for host in web01 web02 web03; do
    ssh "$host" 'apt-get update -qq' &
done
wait                                         # 等全部結束
echo "退出碼：$?"                            # 只反映最後一個 wait 到的

# 收集每個工作的退出碼
pids=()
for host in web01 web02 web03; do
    ssh "$host" uptime > "/tmp/out-$host" 2>&1 &
    pids+=($!)
done
fail=0
for pid in "${pids[@]}"; do wait "$pid" || ((fail++)) || true; done
echo "失敗 $fail 個"
```

```bash
# 控制並行數：xargs -P
printf '%s\n' web01 web02 web03 web04 web05 \
  | xargs -P 3 -I{} sh -c 'ssh {} uptime > /tmp/out-{} 2>&1'

# 或用 GNU parallel（需安裝）
parallel -j 3 'ssh {} uptime' ::: web01 web02 web03
```

> [!warning] 平行時的輸出會交錯
> 多個背景工作同時寫 stdout 會混成一團。**每個工作寫自己的檔案**，
> 結束後再合併——上面的範例就是這樣做。

---

## 除錯

```bash
bash -n script.sh                # 只檢查語法，不執行
bash -x script.sh                # 印出每一行實際執行的指令（含變數展開後的值）
bash -v script.sh                # 印出原始碼（展開前）
```

```bash
# 只對某一段開啟追蹤
set -x
problematic_function
set +x
```

> [!tip] 設定 `PS4` 讓 `-x` 的輸出帶行號與函式名
> ```bash
> export PS4='+ ${BASH_SOURCE##*/}:${LINENO}:${FUNCNAME[0]:-main}: '
> bash -x script.sh
> ```
> ```
> + deploy.sh:23:deploy: rsync -a /src/ /dst/
> + deploy.sh:24:deploy: systemctl reload nginx
> ```
> 比預設的 `+ rsync ...` 好讀太多，特別是幾百行的腳本。

```bash
# 中途檢查變數狀態
declare -p var1 var2 >&2

# 「執行到這裡了嗎」
echo "DEBUG: 到達檢查點 A，count=$count" >&2

# 不執行只顯示（dry-run 模式）
run() { if $DRY_RUN; then echo "[dry] $*"; else "$@"; fi; }
run rsync -a src/ dst/
```

> [!tip] 每支維運腳本都該有 `--dry-run`
> 上面的 `run()` 包裝函式讓所有「會改變狀態」的指令都經過它，
> 加一個旗標就能預覽整個流程會做什麼。
> 這在 [[08-變更管理流程]] 是「變更前驗證」的基本手段。

---

## 可維護的腳本結構

```bash
#!/usr/bin/env bash
#
# deploy.sh — 部署應用到指定環境
#
# 用法: deploy.sh [-n] [-e 環境] <版本>
# 依賴: git rsync systemctl
# 作者/日期: ops team, 2026-08
#
set -euo pipefail

# ── 常數與預設值 ─────────────────────────────────
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly APP_DIR=/var/www/app
readonly LOCK="/var/lock/deploy.lock"
DRY_RUN=false
ENV=production

# ── 工具函式 ─────────────────────────────────────
log()  { printf '[%s] %s\n' "$(date '+%F %T')" "$*" >&2; }
die()  { log "ERROR: $*"; exit 1; }
run()  { if $DRY_RUN; then log "[dry] $*"; else "$@"; fi; }
usage() { sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; }   # 直接印檔頭註解

# ── 清理與錯誤處理 ───────────────────────────────
cleanup() { local rc=$?; rm -rf "${tmpdir:-}"; exit "$rc"; }
trap cleanup EXIT
trap 'die "第 $LINENO 行失敗: $BASH_COMMAND"' ERR

# ── 參數解析 ─────────────────────────────────────
while getopts ":ne:h" opt; do
    case "$opt" in
        n) DRY_RUN=true ;;
        e) ENV="$OPTARG" ;;
        h) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done
shift $((OPTIND - 1))
version="${1:?$(usage)}"

# ── 前置檢查 ─────────────────────────────────────
preflight() {
    for cmd in git rsync systemctl; do
        command -v "$cmd" >/dev/null || die "缺少 $cmd"
    done
    (( EUID == 0 )) || die "需要 root"
    exec 9>"$LOCK"; flock -n 9 || die "另一個部署正在進行"
    tmpdir=$(mktemp -d)
}

# ── 主要步驟：每個都是獨立函式 ────────────────────
fetch()   { log "取得 $version"; run git -C "$tmpdir" clone -q --branch "$version" --depth 1 repo-url . ; }
build()   { log "建置"; run make -C "$tmpdir" build; }
install() { log "安裝到 $APP_DIR"; run rsync -a --delete "$tmpdir/dist/" "$APP_DIR/"; }
reload()  { log "重載服務"; run systemctl reload app; }
verify()  { log "驗證"; run curl -fsS --max-time 10 http://127.0.0.1/health >/dev/null; }

# ── 主流程 ───────────────────────────────────────
main() {
    preflight
    fetch; build; install; reload; verify
    log "✓ $version 已部署到 $ENV"
}
main "$@"
```

> [!tip] 這個結構的每個部分都有理由
> | 部分 | 為什麼 |
> | --- | --- |
> | 檔頭註解 + `usage` 直接印它 | 說明只寫一次，不會不同步 |
> | `readonly` 常數 | 防止被意外改寫 |
> | `die()` / `log()` / `run()` | 三個函式讓主流程讀起來像文件 |
> | 步驟各自一個函式 | 可單獨測試、可跳過、可重排 |
> | `main "$@"` 放最後 | 函式都定義好才執行；可 `source` 進來測試個別函式 |
> | `ERR` trap 帶行號 | 失敗時立刻知道在哪 |

> [!warning] 什麼時候該放棄 bash
> 出現以下任一情況，換 Python（或其他語言）會省很多力氣：
> - 需要處理 JSON / YAML / XML（`jq` 撐一下，但複雜就不行）
> - 需要真正的資料結構（巢狀陣列、物件）
> - 超過 300 行
> - 需要單元測試
> - 錯誤處理的程式碼比正常邏輯還多
>
> bash 的強項是**黏合現有指令**；邏輯一複雜就是它的弱項。

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> 全部相同。唯一差異是 `flock`、`timeout` 都在 `util-linux` / `coreutils`，
> 兩系預設都有；`parallel` 需要 EPEL。

---

## 完整實戰範例：安全的設定檔批次變更

對多台機器套用 sshd 設定變更，含試跑、鎖、逾時、回滾、平行、彙整。

```bash
#!/usr/bin/env bash
#
# harden-sshd-fleet.sh — 批次套用 sshd 加固並可回滾
# 用法: harden-sshd-fleet.sh [-n] [-j 並行數] <主機清單檔>
#
set -euo pipefail

readonly REMOTE_SCRIPT='
set -euo pipefail
CONF=/etc/ssh/sshd_config
BAK="$CONF.bak-$(date +%F-%H%M)"
cp -a "$CONF" "$BAK"
rollback() { [[ $? -ne 0 ]] && { cp -a "$BAK" "$CONF"; systemctl reload ssh 2>/dev/null || systemctl reload sshd; echo "ROLLED_BACK"; }; }
trap rollback EXIT
ensure() { grep -qE "^\s*#?\s*$1\b" "$CONF" && sed -i -E "s|^\s*#?\s*$1\b.*|$1 $2|" "$CONF" || echo "$1 $2" >> "$CONF"; }
ensure PermitRootLogin no
ensure PasswordAuthentication no
ensure MaxAuthTries 3
sshd -t
systemctl reload ssh 2>/dev/null || systemctl reload sshd
echo "APPLIED"
'

DRY_RUN=false; JOBS=4
while getopts ":nj:h" opt; do
    case "$opt" in
        n) DRY_RUN=true ;; j) JOBS="$OPTARG" ;;
        h) sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) exit 2 ;;
    esac
done
shift $((OPTIND-1))
list="${1:?需要主機清單檔}"

outdir=$(mktemp -d); trap 'rm -rf "$outdir"' EXIT

apply_one() {
    local host="$1"
    if $DRY_RUN; then
        echo "[dry] 會對 $host 套用" > "$outdir/$host"; return 0
    fi
    timeout 60 ssh -o BatchMode=yes -o ConnectTimeout=5 "$host" \
        "sudo bash -s" <<< "$REMOTE_SCRIPT" > "$outdir/$host" 2>&1
}
export -f apply_one; export outdir DRY_RUN REMOTE_SCRIPT

grep -vE '^\s*(#|$)' "$list" | xargs -P "$JOBS" -I{} bash -c 'apply_one "$@"' _ {}

echo "════ 結果 ════"
ok=0; bad=0
for f in "$outdir"/*; do
    host=$(basename "$f")
    if grep -q APPLIED "$f" || $DRY_RUN; then
        printf '✓ %-15s %s\n' "$host" "$(tail -1 "$f")"; ((ok++)) || true
    else
        printf '✗ %-15s %s\n' "$host" "$(tail -1 "$f")"; ((bad++)) || true
    fi
done
echo "成功 $ok，失敗 $bad"
(( bad == 0 ))
```

> [!tip] 這裡用到的每個進階技巧
> | 技巧 | 出現在 |
> | --- | --- |
> | 遠端腳本用 `trap ... EXIT` 自動回滾 | `REMOTE_SCRIPT` 內 |
> | 冪等的 `ensure()` | 設定可重複套用 |
> | `sshd -t` 失敗 → `-e` 中止 → trap 回滾 | 設定壞了不會鎖死自己 |
> | `timeout 60` + `BatchMode=yes` | 不會有一台卡住整批 |
> | `xargs -P` + 每台獨立輸出檔 | 平行但輸出不交錯 |
> | `export -f` | 讓 `xargs` 開的子 shell 看得到函式 |
> | `-n` 試跑 | 先看會動哪些機器 |
> | 退出碼反映整體 | 可接告警 |
>
> 注意 `reload` 而非 `restart`——現有連線不中斷，
> 而且遠端腳本自己帶回滾，就算設定壞了也不會失聯。
> 這仍然是「有風險的批次操作」，先在一台試（見 [[08-變更管理流程]]）。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| `set -e` 沒攔住函式內的失敗 | 函式用在 `if` / `&&` / `\|\|` 中，內部 `-e` 失效 | 函式內關鍵步驟自行 `\|\| return 1` |
| `((n++))` 讓腳本死掉 | 算式回傳 0 觸發 `-e` | `((n++)) \|\| true` 或 `n=$((n+1))` |
| trap 的清理沒執行 | trap 註冊在資源建立前就失敗；或用了 `kill -9` | 建立後立刻註冊；`-9` 無法攔截是設計 |
| trap 裡 `$?` 不是預期值 | 被前面的指令覆蓋 | 第一行 `local rc=$?` |
| trap 用雙引號變數沒更新 | 註冊時就展開 | 用單引號 |
| 排程重疊執行 | 沒鎖 | `flock -n` |
| 用 PID 檔當鎖，之後永遠不跑 | 殘留檔 | 改用 `flock`（fd 綁定，自動釋放） |
| 腳本卡住不結束 | 網路呼叫沒逾時 | `timeout` |
| 平行輸出混在一起 | 共用 stdout | 各寫各的檔再合併 |
| `xargs -P` 說 function not found | 子 shell 看不到函式 | `export -f func` |
| 重跑腳本第二次失敗 | 非冪等（`mkdir` 無 `-p`、重複附加行） | 改寫成「確保狀態」 |
| `bash -x` 輸出看不出在哪 | 預設 `PS4` 太簡略 | `PS4='+ ${BASH_SOURCE##*/}:${LINENO}: '` |
| `local` 吞掉了退出碼 | `local v=$(cmd)` 的 `$?` 是 `local` 的 | 分兩行：`local v; v=$(cmd)` |

> [!warning] `local v=$(cmd)` 會吃掉 cmd 的退出碼
> ```bash
> f() { local out=$(false); echo "rc=$?"; }   # rc=0！因為 $? 是 local 指令的
> f() { local out; out=$(false); echo "rc=$?"; }   # rc=1 ✓
> ```
> shellcheck 會提醒（SC2155）。在 `set -e` 下這代表失敗被靜默吞掉。

---

## 安全性注意事項

> [!danger] `export -f` 與 `xargs bash -c` 的注入風險
> ```bash
> xargs -I{} bash -c "process {}"        # ✗ {} 直接拼進字串，檔名含 ; 就被執行
> xargs -I{} bash -c 'process "$@"' _ {} # ✓ 當參數傳，不經字串拼接
> ```
> 本篇範例都用第二種。

> [!warning] trap 裡不要做會失敗的事
> EXIT trap 中的指令失敗（在 `-e` 下）會讓 trap 中途停止，後面的清理沒做。
> 清理指令加 `|| true`，或在 trap 開頭 `set +e`。

> [!tip] 有回滾的變更才叫變更
> 本篇兩個回滾範例的共同點：**先備份、再改、驗證失敗就還原**。
> 沒有還原路徑的自動化，等於把「失敗」變成「災難」。
> 把回滾寫進腳本，而不是寫進事後檢討。

---

## 速查表

### set -e 例外

| 情況 | -e 觸發？ |
| --- | --- |
| `if cmd` / `while cmd` | ❌ |
| `cmd && x` / `cmd \|\| x` 的 cmd | ❌ |
| 管線非最後一段 | ❌（除非 pipefail） |
| **在條件式中呼叫的函式，其內部** | **❌ 全失效** |
| `((expr))` 結果為 0 | ✅ 會中止 |
| `local v=$(fail)` | ❌ 被 local 吃掉 |

### trap

| 寫法 | 說明 |
| --- | --- |
| `trap 'rm -rf "$tmp"' EXIT` | **清理（單引號）** |
| `trap 'echo "第 $LINENO 行: $BASH_COMMAND"' ERR` | 報錯位置 |
| `trap cleanup INT TERM` | 處理中斷 |
| `trap - EXIT` | 移除 |
| 在 trap 內 `local rc=$?` 第一行 | 保留退出碼 |

### 防護

| 技巧 | 寫法 |
| --- | --- |
| 鎖 | `exec 9>"$LOCK"; flock -n 9 \|\| exit 0` |
| 逾時 | `timeout -k 10 60 cmd` |
| 暫存 | `tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT` |
| 試跑 | `run() { $DRY_RUN && echo "[dry] $*" \|\| "$@"; }` |
| 冪等加行 | `grep -qxF "$l" f \|\| echo "$l" >> f` |
| 冪等建立 | `mkdir -p` / `ln -sfn` / `id u \|\| useradd u` |

### 平行

| 寫法 | 說明 |
| --- | --- |
| `cmd & pids+=($!); wait "$pid"` | 手動控制 |
| `xargs -P N -I{} bash -c 'f "$@"' _ {}` | 限制並行數（需 `export -f f`） |
| `parallel -j N cmd ::: items` | GNU parallel |

### 除錯

| 指令 | 說明 |
| --- | --- |
| `bash -n` / `bash -x` | 語法 / 追蹤 |
| `PS4='+ ${BASH_SOURCE##*/}:${LINENO}: '` | 追蹤帶行號 |
| `set -x` … `set +x` | 局部追蹤 |
| `declare -p v` | 看變數 |
| `shellcheck` | 靜態檢查 |

---

## 練習題

> [!question]- 練習 1：證明 `set -e` 在函式裡失效
> 寫一支腳本示範「函式在 if 裡時內部 -e 失效」，再改成安全版本。
>
> **解答**
>
> ```bash
> cat > e-test.sh <<'S'
> #!/usr/bin/env bash
> set -e
> step() { false; echo "  ← false 之後還在跑！"; }
> echo "直接呼叫："; step || true   # 註：這裡也在 || 左邊，同樣失效
> echo "在 if 裡："; if step; then echo "  step 回報成功？"; fi
> S
> bash e-test.sh
> ```
> ```
> 直接呼叫：
>   ← false 之後還在跑！
> 在 if 裡：
>   ← false 之後還在跑！
>   step 回報成功？        ← 因為函式最後一行 echo 成功，退出碼是 0
> ```
> 兩個問題：內部沒中止、而且**函式回傳值變成最後一行的結果**。
> 安全版：
> ```bash
> step() { false || return 1; echo "到不了"; }
> if step; then echo "成功"; else echo "失敗 ✓"; fi
> ```
> **結論**：函式內每個關鍵指令自己 `|| return`，不依賴 `-e`。

> [!question]- 練習 2：實作帶回滾的設定變更
> 寫一支腳本修改 `/etc/hosts`（加一行），驗證失敗時自動還原，
> 並證明 Ctrl+C 或中途錯誤都會還原。
>
> **解答**
>
> ```bash
> cat > hosts-change.sh <<'S'
> #!/usr/bin/env bash
> set -euo pipefail
> F=/etc/hosts; B="$F.bak-$$"
> restore() { local rc=$?; (( rc != 0 )) && { cp -a "$B" "$F"; echo "已還原" >&2; }; rm -f "$B"; exit "$rc"; }
> trap restore EXIT
> cp -a "$F" "$B"
> echo "192.0.2.10 test.internal" >> "$F"
> echo "已修改，5 秒後驗證（此時按 Ctrl+C 測試還原）"; sleep 5
> getent hosts test.internal >/dev/null || { echo "驗證失敗"; exit 1; }
> echo "✓ 完成"
> S
> sudo bash hosts-change.sh          # 正常路徑
> sudo bash hosts-change.sh          # 期間按 Ctrl+C → 印「已還原」
> grep -c test.internal /etc/hosts   # 確認狀態
> ```
> 注意 `restore` 在 `rc == 0` 時只刪備份不還原，
> 而 Ctrl+C 讓 `sleep` 回傳 130 → `-e` 中止 → EXIT trap 看到非 0 → 還原。
> 實驗後記得把加的那行清掉（腳本冪等版可用 `ensure_line`）。

> [!question]- 練習 3：把一支腳本改成冪等並可平行
> 有一支腳本對每台主機執行「建立 `deploy` 使用者並放公鑰」。
> 把它改成可重跑、可平行、有逾時的版本。
>
> **解答**
>
> ```bash
> #!/usr/bin/env bash
> set -euo pipefail
> PUB=$(cat ~/.ssh/deploy.pub)
> REMOTE='
> set -euo pipefail
> id deploy &>/dev/null || useradd -m -s /bin/bash deploy          # 冪等
> install -d -m 700 -o deploy -g deploy /home/deploy/.ssh            # 冪等
> touch /home/deploy/.ssh/authorized_keys
> grep -qxF "$1" /home/deploy/.ssh/authorized_keys || echo "$1" >> /home/deploy/.ssh/authorized_keys
> chown deploy:deploy /home/deploy/.ssh/authorized_keys; chmod 600 /home/deploy/.ssh/authorized_keys
> echo OK
> '
> one() { timeout 30 ssh -o BatchMode=yes "$1" "sudo bash -s -- \"$2\"" <<< "$3" 2>&1 | tail -1 | sed "s/^/$1: /"; }
> export -f one; export REMOTE PUB
> xargs -a hosts.txt -P 4 -I{} bash -c 'one "$@"' _ {} "$PUB" "$REMOTE"
> ```
> 冪等的三處：`id || useradd`、`install -d`（已存在不報錯）、
> `grep -qxF || echo >>`（公鑰不重複）。
> 跑十次結果都一樣，任何一台失敗都不影響其他台，
> 且沒有一台能卡住超過 30 秒。

---

## 小測驗

Q1. `set -e` 在哪六種情況不會觸發？其中最陰險的是哪一種？
Q2. `set -e; n=0; ((n++))` 之後腳本為什麼死了？三種安全寫法？
Q3. `local v=$(false); echo $?` 印什麼？為什麼？
Q4. `trap "rm -rf $tmp" EXIT` 用雙引號有什麼問題？
Q5. trap 要在什麼時候註冊？太晚會怎樣？
Q6. EXIT trap 裡想保留腳本原本的退出碼，第一行要寫什麼？
Q7. 「冪等」是什麼？`echo "x" >> conf` 的冪等寫法？
Q8. 為什麼用 `flock` 綁檔案描述符比檢查 PID 檔好？
Q9. `xargs -P 4 -I{} bash -c 'f {}'` 有什麼安全問題？正確寫法？另外需要什麼才能呼叫函式？
Q10. 什麼情況該放棄 bash 改用 Python？

> [!question]- 測驗答案
> **Q1.** 條件式內、`&&`/`||` 左邊、管線非最後段、**函式用在條件式時其內部整個失效**、非賦值的指令替換、算式為 0（見「set -e 的真相」）。最陰險是函式內部失效。
> **Q2.** 後綴 `++` 回傳舊值 0，算式為假退出碼 1；`((n++)) || true`、`n=$((n+1))`、`((++n))`。
> **Q3.** `0`——`$?` 是 `local` 指令的退出碼，`false` 的失敗被吞掉；分兩行 `local v; v=$(false)`。
> **Q4.** 註冊時就展開，之後 `tmp` 變了也不跟，且為空時變成裸 `rm -rf`；用單引號。
> **Q5.** 建立資源後立刻註冊；中間有指令失敗時 trap 還沒註冊，資源殘留。
> **Q6.** `local rc=$?`，最後 `exit "$rc"`。
> **Q7.** 執行一次與十次結果相同；`grep -qxF "x" conf || echo "x" >> conf`。
> **Q8.** 程序死掉核心自動釋放 fd 鎖；PID 檔在 `kill -9` 後殘留，之後永遠不跑。
> **Q9.** `{}` 拼進字串，檔名含 `;` 就被執行；`bash -c 'f "$@"' _ {}` 當參數傳；並要 `export -f f`。
> **Q10.** 要處理 JSON/YAML、需要真正資料結構、超過 300 行、需要單元測試、錯誤處理比邏輯還多。

---

## 延伸閱讀

- [[21-Shell腳本入門]] — 基礎語法
- [[18-排程工作]] — 讓腳本自動執行、`flock` 從 cron 端包住
- [[10-程序管理與訊號]] — 訊號、背景工作與孤兒程序
- [[08-變更管理流程]] — 批次變更的流程與回退計畫
- [[06-TWGCB-Linux大量派送]] — 從腳本升級到 Ansible
- ShellCheck wiki：<https://www.shellcheck.net/wiki/>
- `help trap` / `help set` / `man 1 flock` / `man 1 timeout`
