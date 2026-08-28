---
title: "現代 CLI 工具集"
desc: "fzf、ripgrep、fd、bat、jq、eza、delta 等替代工具"
aliases: [fzf, ripgrep, rg, fd, bat, jq, eza, exa, delta, yq, duf, zoxide]
tags: [群組/軟體與開發工具, 主題/終端機, 主題/CLI]
category: 常用工具
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[03-Bash與Zsh效率設定]]"]
updated: 2026-08-28
---

# 現代 CLI 工具集

> [!abstract] 這篇你會學到
> - **★★★★ `fzf`** —— 模糊搜尋，改變工作流的一個工具
> - **★★★★ `ripgrep`（rg）** —— 比 grep 快 10 倍
> - **★★★ `fd`** —— 比 find 好用的檔案搜尋
> - **★★★★ `jq` / `yq`** —— JSON / YAML 處理（★ API 排查必備）
> - `bat` / `eza` / `delta` / `duf` / `zoxide`
> - **★★★ 伺服器上該裝哪些**（與該保留的傳統工具）
> - **★★★ 安裝方式與供應鏈風險**

## 前置知識

- [[03-Bash與Zsh效率設定]] — shell 設定
- [[12-文字處理三劍客]] — grep / sed / awk 的基礎

---

## ★★★ 該裝哪些

```
★★★★ 判斷原則：

  【★★★ 一定要會傳統工具】
    grep / find / sed / awk / less
    → ★★★★ 救援模式、剛裝好的機器、容器內【只有這些】
    → ★★★ 依賴現代工具的人在關鍵時刻不會用

  【★★★ 伺服器上值得裝的（★ 少數幾個）】
    jq       ★★★★ JSON 處理（★ 幾乎是必需品）
    ripgrep  ★★★ 大量日誌搜尋時快很多
    → ★★ 這兩個都在官方套件庫，有安全更新

  【★★ 工作機隨便裝】
    fzf / fd / bat / eza / delta / zoxide / duf / dust

★★★★ 不建議在正式伺服器裝的：
  · 需要從 GitHub 下載 binary 的（★ 沒有安全更新）
  · ★★★ 會改變預設行為的（★ alias ls='eza' 讓腳本行為不一致）
  · ★★ 團隊其他人不會用的（交接困難）
```

```bash
# ═══ ★★★ Ubuntu 24.04 的官方套件庫已有 ═══
$ sudo apt install -y jq ripgrep fd-find bat fzf duf
#   ★★ 注意：Debian/Ubuntu 的執行檔名稱不同
$ which fdfind batcat
/usr/bin/fdfind
/usr/bin/batcat
#   ★★★ 建立連結
$ mkdir -p ~/.local/bin
$ ln -sf "$(command -v fdfind)" ~/.local/bin/fd
$ ln -sf "$(command -v batcat)" ~/.local/bin/bat

# ★★ eza（ls 的替代，Ubuntu 24.04+ 有）
$ sudo apt install -y eza
# ★ 或用 cargo
$ cargo install eza

# ★★ 其他（★ 從 GitHub，注意驗證）
$ sudo apt install -y git-delta      # ★ Ubuntu 24.04+
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> $ sudo dnf install -y epel-release
> $ sudo dnf install -y jq ripgrep fd-find bat fzf
> #   ★★ RHEL 的執行檔名稱是正常的（fd / bat）
> $ which fd bat
> /usr/bin/fd
> /usr/bin/bat
> ```

> [!danger] 從 GitHub 下載 binary 的風險 ★★★
> ```
> ★★★ 很多現代 CLI 工具的安裝方式是：
>   curl -L https://github.com/.../releases/.../tool.tar.gz | tar xz
>
> ★★★★ 三個問題：
>   ① 【沒有安全更新】
>      → 套件庫的版本會隨系統更新拿到修補
>      → ★★★ 手動下載的放三年沒人會提醒你有漏洞
>   ② 【沒有簽章驗證】
>      → APT/DNF 自動驗證 GPG 簽章
>      → ★★ 手動下載頂多比對一個 SHA256
>   ③ ★★★ 【無法追溯】
>      → dpkg -S 查不到來源，稽核時說不清楚
>
> ★★★ 正確做法：
>   ① ★★★★ 優先用官方套件庫（apt / dnf）
>   ② 一定要手動下載時：驗證 checksum + 記錄來源與版本
>   ③ ★★ 正式伺服器上盡量不裝
> ```

---

## ★★★★ fzf —— 模糊搜尋

```bash
$ sudo apt install -y fzf
$ fzf --version
0.44.1
```

```bash
# ═══ ★★★ 啟用 shell 整合 ═══
# Ubuntu 的套件
$ cat >> ~/.bashrc <<'EOF'
# ★★★★ fzf 快捷鍵與補全
[ -f /usr/share/doc/fzf/examples/key-bindings.bash ] && \
  . /usr/share/doc/fzf/examples/key-bindings.bash
[ -f /usr/share/bash-completion/completions/fzf ] && \
  . /usr/share/bash-completion/completions/fzf

# ★★★ 預設選項
export FZF_DEFAULT_OPTS='
  --height 60% --layout=reverse --border=rounded
  --info=inline --multi
  --bind "ctrl-/:toggle-preview"
  --bind "ctrl-a:select-all"
  --bind "ctrl-y:execute-silent(echo {+} | xclip -sel clip)"
  --preview-window=right:50%:wrap'

# ★★ 用 fd 當預設搜尋（★ 比 find 快且尊重 .gitignore）
if command -v fdfind >/dev/null; then
  export FZF_DEFAULT_COMMAND='fdfind --type f --hidden --follow --exclude .git'
  export FZF_CTRL_T_COMMAND="$FZF_DEFAULT_COMMAND"
  export FZF_ALT_C_COMMAND='fdfind --type d --hidden --exclude .git'
fi

# ★★★ 預覽
export FZF_CTRL_T_OPTS="--preview 'batcat -n --color=always --line-range :200 {} 2>/dev/null || cat {}'"
export FZF_CTRL_R_OPTS="--preview 'echo {}' --preview-window down:3:hidden:wrap --bind '?:toggle-preview'"
export FZF_ALT_C_OPTS="--preview 'ls -la --color=always {} | head -50'"
EOF
$ source ~/.bashrc
```

```
★★★★ 三個內建快捷鍵（★ 這才是 fzf 的價值）：

  ★★★★ Ctrl+R    搜尋歷史指令
    → 比原本的 C-r 好用太多（★ 模糊比對、可以看到多個結果）

  ★★★ Ctrl+T     插入檔案路徑
    → 打 vim 然後按 C-t → 選檔案 → 路徑自動插入

  ★★★ Alt+C      切換目錄
    → 模糊搜尋子目錄並 cd 過去

★★★ 模糊比對的語法：
  abc        模糊比對（a...b...c）
  'abc       ★★ 完全比對（引號開頭）
  ^abc       開頭是 abc
  abc$       結尾是 abc
  !abc       ★★ 不包含 abc
  abc | def  ★ 包含 abc 或 def
```

```bash
# ═══ ★★★★ 實用的 fzf 函式（放進 ~/.bashrc）═══

# ★★★★ 互動式選擇並編輯檔案
fe() {
  local f
  f=$(fzf --preview 'batcat -n --color=always {} 2>/dev/null || cat {}') || return
  ${EDITOR:-vim} "$f"
}

# ★★★★ 互動式 kill 程序
fkill() {
  local pid
  pid=$(ps -eo pid,user,pcpu,pmem,etime,comm --sort=-pcpu | sed 1d | \
        fzf -m --header='選擇要結束的程序（Tab 多選）' | awk '{print $1}')
  [ -n "$pid" ] || return
  echo "$pid" | xargs -r kill -"${1:-TERM}"
  echo "★ 已送出 SIG${1:-TERM} 給: $pid"
}

# ★★★★ 互動式管理 systemd 服務
fsvc() {
  local svc action
  svc=$(systemctl list-units --type=service --all --no-legend --no-pager | \
        awk '{print $1}' | fzf --header='選擇服務' \
        --preview 'systemctl status {} --no-pager -n 15 2>&1 | head -25') || return
  action=$(printf 'status\nrestart\nreload\nstop\nstart\nenable\ndisable\njournal' | \
           fzf --header="對 $svc 執行") || return
  case "$action" in
    journal) sudo journalctl -u "$svc" -n 100 --no-pager | less ;;
    status)  systemctl status "$svc" --no-pager ;;
    *)       echo "★★ sudo systemctl $action $svc"
             read -rp "確定嗎？[y/N] " a
             [ "$a" = y ] && sudo systemctl "$action" "$svc" ;;
  esac
}

# ★★★ 互動式選擇 git 分支
fbr() {
  local br
  br=$(git branch -a --sort=-committerdate | sed 's/^..//;s#remotes/origin/##' | \
       awk '!seen[$0]++' | \
       fzf --preview 'git log --oneline --graph --color=always -20 {}') || return
  git checkout "$br"
}

# ★★★★ 互動式瀏覽日誌
flog() {
  local f
  f=$(sudo find /var/log -type f \( -name '*.log' -o -name 'syslog*' -o -name 'messages*' \) \
        2>/dev/null | fzf --preview 'sudo tail -50 {}') || return
  sudo less +G "$f"
}

# ★★★ 從 nginx access log 選 IP 並查詳情
fip() {
  local ip log="${1:-/var/log/nginx/access.log}"
  ip=$(sudo awk '{print $1}' "$log" | sort | uniq -c | sort -rn | \
       fzf --header='選擇 IP' | awk '{print $2}') || return
  echo "═══ $ip ═══"
  sudo grep -c "^$ip " "$log" | sed 's/^/請求數: /'
  echo "── 最常存取的 URL ──"
  sudo awk -v ip="$ip" '$1==ip {print $7}' "$log" | sort | uniq -c | sort -rn | head -10
  echo "── 狀態碼分布 ──"
  sudo awk -v ip="$ip" '$1==ip {print $9}' "$log" | sort | uniq -c | sort -rn
  echo "── 反解 ──"
  dig +short -x "$ip" 2>/dev/null || echo "（無）"
}

# ★★★ 選擇 SSH 主機
fssh() {
  local h
  h=$(awk '/^Host / && $2 !~ /\*/ {print $2}' ~/.ssh/config 2>/dev/null | \
      fzf --header='選擇主機') || return
  ssh "$h"
}
```

---

## ★★★★ ripgrep（rg）

```bash
$ sudo apt install -y ripgrep
$ rg --version
ripgrep 14.1.0
```

```
★★★★ 比 grep 快的三個原因：
  ① ★★★ 用 Rust 寫的，正規表示式引擎更快
  ② ★★★★ 【預設遞迴】而且【自動跳過 .gitignore 的檔案】
     → 不會浪費時間掃 node_modules / vendor / .git
  ③ ★★★ 平行處理多個檔案

★★★ 實測：在一個含 node_modules 的專案搜尋
  grep -rn "pattern" .     → 12.4 秒
  rg "pattern"             → 0.3 秒        ★★★★ 40 倍
```

```bash
# ═══ ★★★ 基本用法 ═══
$ rg "error"                        # ★★★ 遞迴搜尋目前目錄
$ rg -i "error"                     # 忽略大小寫
$ rg -w "error"                     # ★★ 完整單字
$ rg -F "a.b.c"                     # ★★ 固定字串（不當正規表示式）
$ rg -n "error"                     # ★ 顯示行號（★ 預設就有）
$ rg -C 3 "error"                   # ★★★ 前後 3 行
$ rg -A 5 -B 2 "error"              # ★★ 後 5 行、前 2 行
$ rg -l "error"                     # ★★ 只列出檔名
$ rg -c "error"                     # ★★ 每個檔案的符合次數
$ rg -v "debug"                     # 反向
$ rg --stats "error"                # ★★ 統計

# ═══ ★★★ 檔案類型過濾（★ 非常好用）═══
$ rg -t php "function"              # ★★★ 只搜 PHP
$ rg -t js -t ts "console.log"      # ★★ 多種類型
$ rg -T test "TODO"                 # ★★ 排除 test 類型
$ rg --type-list | head -20         # ★ 支援的類型
$ rg -g '*.conf' "listen"           # ★★★ 用 glob
$ rg -g '!vendor/*' -g '!node_modules/*' "pattern"

# ═══ ★★★ 搜尋範圍 ═══
$ rg "error" /var/log               # 指定目錄
$ rg -u "error"                     # ★★ 不理會 .gitignore（-uu 連隱藏檔）
$ rg -uuu "error"                   # ★★★ 全部都搜（含二進位）
$ rg --hidden "error"               # ★★ 搜尋隱藏檔
$ rg --no-ignore "error"
$ rg -z "error" /var/log/           # ★★★★ 搜尋壓縮檔（.gz .bz2 .xz）

# ═══ ★★★ 輸出格式 ═══
$ rg --json "error" | jq -r 'select(.type=="match") | .data.lines.text'
$ rg --files                        # ★★ 列出會被搜尋的檔案
$ rg --files | rg "\.conf$"         # ★★ 找檔名
$ rg -o "user_id=\d+"               # ★★★ 只輸出符合的部分
$ rg -r 'ID=$1' 'user_id=(\d+)'     # ★★ 取代（★ 只顯示不改檔案）
$ rg --passthru -r 'REDACTED' 'password=\S+' file.log   # ★★★ 遮蔽

# ═══ ★★★★ 多行搜尋 ═══
$ rg -U "server \{[\s\S]*?listen 443" /etc/nginx/
$ rg --multiline --multiline-dotall "BEGIN CERT[\s\S]*?END CERT" /etc/ssl/
```

```bash
# ═══ ★★★★ 維運實戰 ═══

# ★★★ 在所有設定檔中找某個設定
$ rg -g '*.conf' -g '*.cnf' -g '*.ini' 'max_connections' /etc/

# ★★★★ 找出所有硬編碼的密碼（★ 資安稽核）
$ rg -i --no-heading \
    'password\s*=\s*["\x27][^"\x27]{4,}|api[_-]?key\s*=|secret\s*=\s*["\x27]' \
    /var/www/app/current/app /var/www/app/current/config

# ★★★★ 掃描危險函式
$ rg -t php --no-heading '\b(eval|exec|shell_exec|system|passthru|proc_open)\s*\(' \
    /var/www/app/current/app

# ★★★ 找出 config/ 以外用 env() 的
$ rg -t php --no-heading 'env\(' /var/www/app/current/app /var/www/app/current/routes

# ★★★ 在壓縮的日誌中搜尋
$ rg -z '203\.0\.113\.45' /var/log/nginx/
$ rg -z --stats '500 ' /var/log/nginx/access.log*

# ★★★★ 找出 5xx 錯誤並統計
$ rg -z -o '" (5\d{2}) ' /var/log/nginx/access.log* -r '$1' | \
    sort | uniq -c | sort -rn

# ★★★ 搭配 fzf 互動搜尋
rgf() {
  local file line
  read -r file line <<< "$(rg --line-number --no-heading --color=always "$1" 2>/dev/null | \
    fzf --ansi --delimiter : \
        --preview 'batcat --color=always --highlight-line {2} {1} 2>/dev/null' \
        --preview-window '+{2}-/2' | awk -F: '{print $1, $2}')"
  [ -n "$file" ] && ${EDITOR:-vim} "+$line" "$file"
}
```

> [!warning] rg 預設會跳過檔案 ★★★
> ```
> ★★★★ rg 預設會跳過：
>   · .gitignore 中列出的
>   · .ignore / .rgignore 中列出的
>   · ★★★ 隱藏檔（. 開頭）
>   · ★★★ 二進位檔案
>   · 符號連結
>
> ★★★★ 這在【搜尋設定檔或日誌】時會踩雷：
>   $ rg "password" /etc/           # ★★★ 可能漏掉 /etc/.hidden
>   $ rg "error" /var/log/          # ★★★★ 漏掉 .gz 的舊日誌
>
> ★★★ 解法：
>   -u     不理會 .gitignore
>   -uu    再加上搜尋隱藏檔
>   -uuu   ★★★ 連二進位也搜
>   --hidden        搜尋隱藏檔
>   ★★★★ -z        搜尋壓縮檔（.gz/.bz2/.xz/.zst）
>   -L     跟隨符號連結
>
> ★★ 建議在 ~/.bashrc 加：
>   alias rgl='rg -uu -z --hidden'     # ★★★ 搜日誌用
> ```

---

## ★★★★ jq / yq

```bash
$ sudo apt install -y jq
$ jq --version
jq-1.7.1

# ★★ yq（YAML 處理）
$ sudo snap install yq
# ★ 或
$ sudo wget -qO /usr/local/bin/yq \
    https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64
$ sudo chmod +x /usr/local/bin/yq
```

```bash
# ═══ ★★★ jq 基本 ═══
$ curl -s https://api.example.gov.tw/users | jq .           # ★★★ 格式化
$ echo '{"a":1}' | jq .a                                    # 取欄位
$ jq -r '.name' data.json                                   # ★★★ -r = 不要引號
$ jq '.users[]' data.json                                   # 陣列展開
$ jq '.users[0].name' data.json
$ jq '.users | length' data.json                            # ★★ 長度
$ jq 'keys' data.json                                       # ★★ 所有的 key
$ jq -c '.' data.json                                       # ★★ 壓成一行

# ═══ ★★★ 過濾與轉換 ═══
$ jq '.users[] | select(.active == true)' data.json         # ★★★ 篩選
$ jq '.users[] | select(.age > 30) | .name' data.json
$ jq '.users | map(.name)' data.json                        # ★★ map
$ jq '.users | group_by(.dept)' data.json                   # ★★ 分組
$ jq '.users | sort_by(.age) | reverse' data.json           # ★★ 排序
$ jq '[.users[] | {name, email}]' data.json                 # ★★★ 挑選欄位
$ jq '.users | map(select(.role=="admin")) | length' data.json

# ═══ ★★★★ 轉成 CSV / TSV ═══
$ jq -r '.users[] | [.id, .name, .email] | @csv' data.json
$ jq -r '.users[] | [.id, .name] | @tsv' data.json
$ jq -r '(.users[0] | keys_unsorted), (.users[] | to_entries | map(.value)) | @csv' data.json

# ═══ ★★ 建構 JSON ═══
$ jq -n --arg n "測試" --argjson a 30 '{name:$n, age:$a}'
$ jq -n --arg ts "$(date -Is)" --arg h "$(hostname)" \
    '{timestamp:$ts, host:$h, status:"ok"}'

# ═══ ★★★ 錯誤處理 ═══
$ jq -e '.status == "ok"' response.json && echo "★ OK" || echo "★★ 失敗"
#   ★★★ -e：依結果設定 exit code（★ 腳本中很有用）
$ jq '.missing // "預設值"' data.json                        # ★★ 預設值
$ jq '.a?.b?' data.json                                      # ★★ 安全存取
$ jq 'try .a.b catch "錯誤"' data.json
```

```bash
# ═══ ★★★★ 維運實戰 ═══

# ★★★ 檢查 API 健康
$ curl -s https://app.example.gov.tw/api/health | \
    jq -e '.status == "ok" and .db == "ok"' >/dev/null && echo "★ 健康" || echo "★★★ 異常"

# ★★★★ 從 Docker 取出資訊
$ docker inspect app | jq -r '.[0].State | "狀態: \(.Status)  OOMKilled: \(.OOMKilled)  重啟: \(.RestartCount)"'
$ docker inspect app | jq -r '.[0].NetworkSettings.Networks | keys[]'
$ docker inspect app | jq -r '.[0].Config.Env[]' | grep -v PASSWORD

# ★★★ 所有容器的資源
$ docker stats --no-stream --format '{{json .}}' | \
    jq -sr '.[] | [.Name, .CPUPerc, .MemUsage] | @tsv' | column -t

# ★★★★ 解析 nginx 的 JSON 日誌
$ sudo tail -1000 /var/log/nginx/access.json.log | \
    jq -r 'select(.status >= 500) | "\(.time) \(.status) \(.uri) rt=\(.request_time)"'

$ sudo tail -10000 /var/log/nginx/access.json.log | \
    jq -sr 'group_by(.uri) | map({uri: .[0].uri, count: length,
            avg_rt: (map(.request_time|tonumber) | add / length)}) |
            sort_by(-.avg_rt) | .[:10] |
            .[] | "\(.avg_rt * 1000 | floor)ms  \(.count)次  \(.uri)"'

# ★★★ systemd 的 JSON 輸出
$ systemctl list-units --type=service --output=json | \
    jq -r '.[] | select(.active != "active") | "\(.unit)  \(.active)/\(.sub)"'
$ journalctl -u nginx -n 50 -o json | \
    jq -r '"\(.__REALTIME_TIMESTAMP|tonumber/1000000|todate) \(.MESSAGE)"'

# ★★★ Kubernetes
$ kubectl get pods -o json | \
    jq -r '.items[] | select(.status.phase != "Running") |
           "\(.metadata.namespace)/\(.metadata.name)  \(.status.phase)"'

# ═══ ★★★ yq（YAML）═══
$ yq '.services.web.image' docker-compose.yml
$ yq -i '.services.web.image = "nginx:1.25"' docker-compose.yml   # ★★★ 就地修改
$ yq -o=json '.' config.yml                                        # ★★ YAML → JSON
$ yq -P '.' config.json                                            # ★★ JSON → YAML
$ yq '.services | keys' docker-compose.yml
$ yq 'explode(.)' config.yml                                       # ★★ 展開 anchor

# ★★★★ 驗證 YAML 語法（★ 部署前必做）
$ yq '.' docker-compose.yml >/dev/null && echo "★ 語法正確" || echo "★★★ 語法錯誤"
$ python3 -c 'import yaml,sys; yaml.safe_load(open(sys.argv[1]))' docker-compose.yml
```

---

## 其他工具 ★★

### bat（cat 的替代）

```bash
$ batcat file.conf                  # ★★ 語法高亮 + 行號
$ batcat -n -r 100:150 large.log    # ★★ 指定行範圍
$ batcat -p file.txt                # ★★ 純輸出（★ 無裝飾，可以接管線）
$ batcat --style=plain,numbers f.conf
$ batcat -A f.conf                  # ★★ 顯示不可見字元（★ 像 cat -A）
$ batcat --diff f.conf              # ★ 顯示 git 差異

# ★★ 當 man 的 pager
$ export MANPAGER="sh -c 'col -bx | batcat -l man -p'"

# ★★★ 注意：接管線時要用 -p 或 --style=plain
$ batcat -p f.json | jq .           # ★★ 不加 -p 會有裝飾字元
```

### eza（ls 的替代）

```bash
$ eza -la --git --icons --group-directories-first
$ eza -T -L 2 --git-ignore          # ★★ 樹狀（★ 取代 tree）
$ eza -la --sort=modified --reverse # ★★ 依修改時間
$ eza -la --total-size              # ★★ 目錄顯示總大小
$ eza -l --time-style=long-iso

# ★★★ 但不要 alias ls='eza'
#   → ★★★★ 腳本中的 ls 行為會不一致
#   → ★★ 用不同的名稱：alias l='eza -la --git'
```

### delta（git diff 的替代）

```bash
$ git config --global core.pager delta
$ git config --global interactive.diffFilter 'delta --color-only'
$ git config --global delta.navigate true
$ git config --global delta.side-by-side true
$ git config --global delta.line-numbers true
$ git config --global merge.conflictStyle zdiff3

# ★★ 一般的 diff 也能用
$ diff -u a.conf b.conf | delta
```

### zoxide（cd 的替代）

```bash
$ sudo apt install -y zoxide
$ cat >> ~/.bashrc <<'EOF'
eval "$(zoxide init bash)"
EOF

$ z app          # ★★★ 跳到最常用的含 "app" 的目錄
$ zi             # ★★ 用 fzf 互動選擇
$ z -            # 上一個目錄
$ zoxide query -l | head    # ★ 看記錄
```

### duf / dust

```bash
$ duf                        # ★★ df 的替代（★ 表格清楚）
$ duf --only local
$ duf --hide-fs tmpfs,devtmpfs

$ dust -d 2 /var             # ★★ du 的替代（★ 視覺化）
$ dust -r -n 20 /var/log
```

### 其他

```bash
$ sudo apt install -y httpie hyperfine tldr procs sd

$ http GET https://api.example.gov.tw/users Accept:application/json   # ★★ curl 替代
$ hyperfine 'grep -r pattern .' 'rg pattern'                          # ★★ 效能比較
$ tldr tar                                                             # ★★★ 精簡的用法範例
$ procs --tree nginx                                                   # ★ ps 替代
$ sd 'old' 'new' file.txt                                              # ★★ sed 的簡化替代
```

---

## 完整實戰範例：用現代工具排查

```bash
#!/usr/bin/env bash
# ★★★ /usr/local/bin/logdig —— 用現代工具快速分析日誌
set -uo pipefail

LOG="${1:-/var/log/nginx/access.log}"
N="${2:-10}"

command -v rg >/dev/null || { echo "★★ 需要 ripgrep"; exit 1; }
command -v jq >/dev/null || { echo "★★ 需要 jq"; exit 1; }

echo "═══ 日誌分析: $LOG ═══"

# ═══ ★★★【1】基本統計 ═══
echo -e "\n【1】基本統計"
TOTAL=$(wc -l < "$LOG")
printf '  總請求數: %s\n' "$TOTAL"
printf '  時間範圍: %s ~ %s\n' \
  "$(head -1 "$LOG" | grep -oP '\[\K[^\]]+' || echo '?')" \
  "$(tail -1 "$LOG" | grep -oP '\[\K[^\]]+' || echo '?')"

# ═══ ★★★★【2】狀態碼分布 ═══
echo -e "\n【2】★★★ 狀態碼分布"
rg -o '" (\d{3}) ' "$LOG" -r '$1' | sort | uniq -c | sort -rn | \
  awk -v t="$TOTAL" '{printf "  %-5s %8d  (%.2f%%)", $2, $1, $1/t*100
    if ($2 ~ /^5/) printf "  ★★★★ 伺服器錯誤"
    else if ($2 ~ /^4/) printf "  ★★ 客戶端錯誤"
    print ""}'

# ═══ ★★★【3】Top IP ═══
echo -e "\n【3】★★★ Top $N 來源 IP"
rg -o '^\S+' "$LOG" | sort | uniq -c | sort -rn | head -"$N" | \
  awk -v t="$TOTAL" '{printf "  %-16s %8d  (%.2f%%)", $2, $1, $1/t*100
    if ($1/t > 0.2) printf "  ★★★★ 佔比異常高"
    print ""}'

# ═══ ★★★【4】Top URL ═══
echo -e "\n【4】Top $N URL"
rg -o '"(?:GET|POST|PUT|DELETE|HEAD|PATCH) (\S+)' "$LOG" -r '$1' | \
  sed 's/?.*//' | sort | uniq -c | sort -rn | head -"$N" | \
  awk '{printf "  %8d  %s\n", $1, $2}'

# ═══ ★★★★【5】最慢的 URL（★ 需要 log_format 有 rt=）═══
if rg -q 'rt=' "$LOG" 2>/dev/null; then
    echo -e "\n【5】★★★★ 最慢的 URL"
    awk 'match($0,/rt=([0-9.]+)/,m) && match($0,/"[A-Z]+ ([^ ?]+)/,u) {
        s[u[1]]+=m[1]; c[u[1]]++; if(m[1]>mx[u[1]]) mx[u[1]]=m[1]}
      END {for(k in s) printf "%.3f %.3f %d %s\n", s[k]/c[k], mx[k], c[k], k}' "$LOG" | \
      sort -rn | head -"$N" | \
      awk '{printf "  平均%7.3fs 最慢%7.3fs %6d次  %s", $1, $2, $3, $4
        if ($1 > 1) printf "   ★★★ 慢"
        print ""}'
else
    echo -e "\n【5】★★ log_format 沒有 rt=（建議加上 \$request_time）"
fi

# ═══ ★★★★【6】5xx 錯誤詳情 ═══
echo -e "\n【6】★★★★ 5xx 錯誤"
E5=$(rg -c '" 5\d{2} ' "$LOG" 2>/dev/null || echo 0)
printf '  總數: %s\n' "$E5"
if [ "$E5" -gt 0 ]; then
    echo "  ── 依 URL ──"
    rg '" 5\d{2} ' "$LOG" | rg -o '"[A-Z]+ ([^ ?]+)' -r '$1' | \
      sort | uniq -c | sort -rn | head -5 | awk '{printf "    %6d  %s\n", $1, $2}'
    echo "  ── 最近 3 筆 ──"
    rg '" 5\d{2} ' "$LOG" | tail -3 | cut -c1-150 | sed 's/^/    /'
fi

# ═══ ★★★【7】可疑的掃描行為 ═══
echo -e "\n【7】★★★ 可疑請求"
SUSPICIOUS='\.env|\.git/|wp-admin|wp-login|phpmyadmin|\.\./|/etc/passwd|eval\(|base64_decode|xmlrpc\.php|\.aws/'
SUSP=$(rg -ic "$SUSPICIOUS" "$LOG" 2>/dev/null || echo 0)
printf '  可疑請求數: %s\n' "$SUSP"
if [ "$SUSP" -gt 0 ]; then
    rg -i "$SUSPICIOUS" "$LOG" | rg -o '^\S+' | sort | uniq -c | sort -rn | head -5 | \
      awk '{printf "    ★★★ %-16s %d 次\n", $2, $1}'
    echo "  ── 掃描的路徑 ──"
    rg -i "$SUSPICIOUS" "$LOG" | rg -o '"[A-Z]+ ([^ ?]+)' -r '$1' | \
      sort | uniq -c | sort -rn | head -5 | awk '{printf "    %6d  %s\n", $1, $2}'
fi

# ═══ ★★【8】User-Agent ═══
echo -e "\n【8】Top 5 User-Agent"
rg -o '"[^"]*"$' "$LOG" | sort | uniq -c | sort -rn | head -5 | \
  cut -c1-110 | sed 's/^/  /'

# ═══ ★★★【9】每分鐘的請求量（找出峰值）═══
echo -e "\n【9】★★★ 請求量峰值（每分鐘）"
rg -o '\[\K[^\]]+' "$LOG" | cut -d: -f1-3 | uniq -c | sort -rn | head -5 | \
  awk '{printf "  %6d 次  %s\n", $1, $2" "$3}'

echo -e "\n★ 完成"
```

```bash
$ sudo install -m755 logdig.sh /usr/local/bin/logdig
$ sudo logdig /var/log/nginx/access.log 10

═══ 日誌分析: /var/log/nginx/access.log ═══

【2】★★★ 狀態碼分布
  200      84210  (94.21%)
  404       1240  (1.39%)  ★★ 客戶端錯誤
  500        892  (1.00%)  ★★★★ 伺服器錯誤
  502        124  (0.14%)  ★★★★ 伺服器錯誤

【3】★★★ Top 10 來源 IP
  203.0.113.45      48210  (53.93%)  ★★★★ 佔比異常高
  198.51.100.22      1240  (1.39%)

【7】★★★ 可疑請求
  可疑請求數: 2840
    ★★★ 203.0.113.45   2840 次
  ── 掃描的路徑 ──
     892  /.env
     620  /.git/config
     480  /wp-admin/
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **`fd`/`bat` 找不到指令** ★★★ | **Debian/Ubuntu 改了名稱** | 用 `fdfind`/`batcat`；建立連結 |
| **`rg` 找不到明明存在的東西** ★★★★ | **預設跳過 .gitignore/隱藏檔** | **`-uu`**；`--hidden`；**`-z`（壓縮檔）** |
| **`rg` 搜不到 .gz 的舊日誌** ★★★★ | 沒加 `-z` | **`rg -z`** |
| **`jq` 輸出有引號** ★★★ | 沒加 `-r` | **`jq -r`** |
| **`jq` 遇到 null 就錯** ★★★ | 欄位不存在 | `.a?`；`// "預設"`；`try ... catch` |
| **`bat` 接管線有亂碼** ★★★ | 裝飾字元 | **`bat -p`** 或 `--style=plain` |
| **`fzf` 的 C-r 沒生效** ★★★ | 沒載入 key-bindings | `source /usr/share/doc/fzf/examples/key-bindings.bash` |
| **`alias ls='eza'` 讓腳本壞掉** ★★★★ | **輸出格式不同** | **不要覆蓋標準指令**；用新名稱 |
| **從 GitHub 裝的工具沒更新** ★★★ | 沒有套件管理 | **優先用 apt/dnf** |
| **`jq` 處理大檔案很慢/OOM** ★★ | 一次載入全部 | `--stream`；先用 `rg` 過濾 |
| **`yq` 版本語法不同** ★★★ | mikefarah vs kislyuk | `yq --version` 確認 |

### 排查

```bash
# 【1】★★★ 確認實際的執行檔
$ command -v fd fdfind bat batcat rg jq eza 2>/dev/null
$ dpkg -S "$(command -v rg)" 2>/dev/null || echo "★★ 不是套件管理的"
$ rg --version; jq --version; fzf --version

# 【2】★★★★ rg 為什麼沒搜到
$ rg --debug "pattern" 2>&1 | grep -i ignor | head
$ rg --files | wc -l                 # ★★ 會被搜尋的檔案數
$ rg -uu --files | wc -l             # ★★★ 加了 -uu 之後
$ rg --no-ignore --hidden -z "pattern"

# 【3】★★ jq 的語法測試
$ echo '{"a":{"b":1}}' | jq '.a.b'
$ jq -n '1+1'
$ jq 'debug' data.json 2>&1 | head

# 【4】★★ fzf 的設定
$ echo "$FZF_DEFAULT_COMMAND"
$ echo "$FZF_DEFAULT_OPTS"
$ bind -p | grep -i fzf

# 【5】★★ 效能比較
$ hyperfine --warmup 2 'grep -rn "pattern" .' 'rg "pattern"'
$ time rg "pattern" > /dev/null
$ time grep -rn "pattern" . > /dev/null
```

---

## 安全性注意事項

> [!danger] 四個要點 ★★★
> ```
> ① ★★★★ 不要用 curl | sh 安裝
>      → ★★★ 先下載、看過、驗證 checksum、再執行
>      → ★★★★ 優先用官方套件庫
>
> ② ★★★ 不要覆蓋標準指令的 alias
>      alias ls='eza'  alias cat='bat'  alias grep='rg'
>      → ★★★★ 腳本中的行為變得不可預測
>      → ★★★ 而且輸出格式不同 → awk/cut 的欄位對不上
>      → ★★ 用不同的名稱（l / b / rgl）
>
> ③ ★★★ fzf 的預覽會執行指令
>      → --preview 'cat {}' 對惡意檔名可能有問題
>      → ★★ 用 {} 而不是 {+} 時 fzf 會自動加引號
>
> ④ ★★★ jq 處理外部 JSON 時的注意
>      → ★★ 不要用 eval 或把 jq 輸出直接當指令執行
>      → ★★★ jq -r 的輸出可能含特殊字元
> ```

```bash
# ★★★ 安全的安裝流程
$ VER=14.1.0
$ curl -fsSL -O "https://github.com/BurntSushi/ripgrep/releases/download/$VER/ripgrep_${VER}-1_amd64.deb"
$ curl -fsSL -O "https://github.com/BurntSushi/ripgrep/releases/download/$VER/ripgrep_${VER}-1_amd64.deb.sha256"
$ sha256sum -c "ripgrep_${VER}-1_amd64.deb.sha256"
ripgrep_14.1.0-1_amd64.deb: OK          # ★★★ 一定要看到 OK
$ sudo dpkg -i "ripgrep_${VER}-1_amd64.deb"
#   ★★★ 用 .deb 而不是裸 binary → dpkg 能追溯

# ★★★ 記錄手動安裝的工具（★ 稽核用）
$ sudo tee -a /var/log/manual-installs.log <<EOF
$(date -Is) | ripgrep $VER | https://github.com/BurntSushi/ripgrep | sha256 verified | $(whoami)
EOF

# ★★★★ 檢查有沒有覆蓋標準指令
$ alias | grep -E "^alias (ls|cat|grep|find|df|du|ps|top)="
alias ls='ls --color=auto'              # ★ 這個 OK（只加選項）
alias cat='bat'                          # ★★★★ 危險！
alias grep='rg'                          # ★★★★ 危險！

# ★★★ 正確的做法
$ cat >> ~/.shell_aliases <<'EOF'
# ★★ 用新名稱，不覆蓋標準指令
alias l='eza -la --git --group-directories-first'
alias lt='eza -T -L 2'
alias b='batcat'
alias rgl='rg -uu -z --hidden'          # ★★★ 搜日誌用
alias jqc='jq -C .'
EOF

# ★★★ 驗證腳本中沒有依賴這些工具
$ rg -l 'eza|batcat|\brg\b|\bfd\b' /usr/local/bin/ 2>/dev/null
#   ★★★ 腳本應該用標準工具（★ 才能在任何機器上跑）

# ★★ 檢查手動安裝的 binary
$ for f in /usr/local/bin/*; do
    [ -f "$f" ] && ! dpkg -S "$f" >/dev/null 2>&1 && \
      printf "★★ 非套件管理: %-30s %s\n" "$(basename "$f")" "$(stat -c '%y' "$f" | cut -d' ' -f1)"
  done

# ★★★ fzf 的預覽安全性
$ export FZF_CTRL_T_OPTS="--preview 'batcat -n --color=always --line-range :200 -- {} 2>/dev/null'"
#   ★★ 加 -- 避免檔名被當成選項
```

---

## 速查表

### ★★★★ 該裝哪些

```
★★★ 伺服器上：jq（必需）、ripgrep（大量日誌）
★★ 工作機：fzf / fd / bat / eza / delta / zoxide
★★★★ 一定要會傳統工具：grep / find / sed / awk / less
      → 救援模式、容器內只有這些
★★★★ 不要 alias 覆蓋標準指令
```

### ★★★★ fzf

```
C-r    ★★★★ 搜尋歷史
C-t    ★★★ 插入檔案路徑
Alt-C  ★★★ 切換目錄

'abc   完全比對   ^abc 開頭   abc$ 結尾   !abc 排除
```

### ★★★★ ripgrep

```bash
rg "pattern"                # ★★★ 遞迴（自動跳過 .gitignore）
rg -t php "func"            # ★★★ 檔案類型
rg -g '*.conf' "listen"     # ★★★ glob
rg -C 3 "error"             # 前後 3 行
rg -o 'id=(\d+)' -r '$1'    # ★★★ 只輸出符合的部分

★★★★ 預設會跳過的：
  -u / -uu / -uuu    不理會 ignore 檔 / 隱藏檔 / 二進位
  --hidden           隱藏檔
  ★★★★ -z           壓縮檔（.gz/.bz2/.xz）← 搜舊日誌必加
alias rgl='rg -uu -z --hidden'
```

### ★★★★ jq

```bash
jq .                              格式化
jq -r '.name'                     ★★★ -r 不要引號
jq '.users[] | select(.a==true)'  ★★★ 篩選
jq -r '.[] | [.a,.b] | @csv'      ★★★ 轉 CSV
jq -e '.status=="ok"'             ★★★ 設定 exit code（腳本用）
jq '.a // "預設"'                  ★★ 預設值
jq '.a?'                          ★★ 安全存取
jq -n --arg k "$v" '{key:$k}'     ★★ 建構
```

### yq

```bash
yq '.services.web.image' docker-compose.yml
yq -i '.a.b = "new"' f.yml        # ★★★ 就地修改
yq -o=json '.' f.yml              # YAML → JSON
yq '.' f.yml >/dev/null           # ★★★ 語法驗證
```

### 其他

```bash
batcat -p f.json | jq .           # ★★ -p = 純輸出（接管線必加）
eza -T -L 2                       # 樹狀
duf / dust -d 2 /var              # df / du 替代
z app / zi                        # zoxide
hyperfine 'cmd1' 'cmd2'           # ★★ 效能比較
tldr tar                          # ★★★ 精簡範例
```

### ★★★ 安全

```bash
★★★★ 不要 curl | sh；先下載驗證 sha256
★★★ 優先用 apt/dnf（有安全更新與簽章）
★★★★ 不要 alias 覆蓋 ls/cat/grep（腳本會壞）
★★★ 腳本中用標準工具，不要依賴現代工具
```

---

## 練習題

> [!question]- 練習 1：fzf ★★★
> 1. **安裝並啟用 shell 整合**
> 2. **按 `C-r`** → 和原本的差別？
> 3. **按 `C-t`** 選一個檔案
> 4. **設定 `FZF_CTRL_T_OPTS` 加上預覽**
> 5. **把 `fkill` 和 `fsvc` 函式加進 `.bashrc` 並測試**
> 6. **寫一個你自己的 fzf 函式**

> [!question]- 練習 2：ripgrep ★★★★
> 1. **在一個含 `node_modules` 的專案 `time grep -rn "x" .` 和 `time rg "x"`**
> 2. **差幾倍？**
> 3. **`rg "password" /etc/`** → 有搜到隱藏檔嗎？
> 4. **加 `-uu --hidden` 再試** → 呢？
> 5. **`rg "203.0.113" /var/log/nginx/`** → 有搜到 `.gz` 嗎？
> 6. **加 `-z` 再試**，並解釋為什麼預設不搜

> [!question]- 練習 3：jq ★★★★
> 1. **`curl -s <某個 API> | jq .`**
> 2. **用 `select()` 篩選出特定條件的項目**
> 3. **轉成 CSV（`@csv`）**
> 4. **`jq -e` 寫一個健康檢查，成功回 0 失敗回 1**
> 5. **`docker inspect` 的輸出取出 `OOMKilled` 和 `RestartCount`**
> 6. **處理一個欄位可能不存在的 JSON**（用 `//` 和 `?`）

> [!question]- 練習 4：實戰腳本 ★★★
> 1. **把 `logdig` 腳本裝起來**
> 2. 對你的 nginx access log 執行
> 3. **Top IP 有沒有異常高的？**
> 4. **有可疑請求嗎？掃了哪些路徑？**
> 5. **在 `log_format` 加上 `rt=$request_time` 再跑一次**
> 6. **加一個「每小時 5xx 趨勢」的區段**

> [!question]- 練習 5：安全 ★★★
> 1. **`alias | grep -E "^alias (ls|cat|grep)="`** → 有覆蓋嗎？
> 2. **設 `alias cat='batcat'`，然後跑一個用到 `cat` 的腳本** → 正常嗎？
> 3. **`cat f.json | jq .`** → 有亂碼嗎？為什麼？
> 4. **檢查 `/usr/local/bin` 中哪些不是套件管理的**
> 5. **用正確的方式安裝一個工具**（下載 + 驗證 sha256 + dpkg）
> 6. **檢查你的腳本有沒有依賴現代工具**

---

## 小測驗

Q1. **為什麼 `rg` 比 `grep -r` 快這麼多**？（三個原因）

Q2. **`rg` 搜不到明明存在的內容，四個可能原因**？

Q3. **在 `/var/log` 搜尋舊日誌時，`rg` 一定要加什麼參數**？

Q4. **Debian/Ubuntu 上 `fd` 和 `bat` 為什麼要用 `fdfind`/`batcat`**？

Q5. **`jq` 的 `-r` 和 `-e` 各做什麼**？

Q6. **`jq` 處理可能不存在的欄位，三種寫法**？

Q7. **為什麼不該 `alias cat='bat'` 或 `alias grep='rg'`**？

Q8. **`bat` 接管線時要加什麼參數**？為什麼？

Q9. **從 GitHub 下載 binary 有什麼風險**？正確做法？

Q10. **伺服器上值得裝哪些現代工具**？為什麼其他的不建議？

> [!question]- 測驗答案
> **Q1.** ①**★★★★ 預設遞迴且自動跳過 `.gitignore` 列出的檔案** ——
> 這是最大的差異。`grep -r` 會**老實地掃過 `node_modules`、`vendor`、`.git`**
> （動輒幾十萬個檔案），而 `rg` 直接跳過，
> 實測在含 `node_modules` 的專案上可以差到 **40 倍**；
> ②**★★★ 用 Rust 寫的，正規表示式引擎（regex crate）更快** ——
> 使用有限狀態機而非回溯，最壞情況的效能有保證；
> ③**★★★ 平行處理多個檔案** —— 現代多核心 CPU 全部用上，
> 而 `grep` 是單執行緒。
> 另外 rg 還會**自動偵測並跳過二進位檔案**，
> 以及使用記憶體映射（mmap）減少複製。
>
> **Q2.** ①**★★★★ `.gitignore` / `.ignore` 中列出的檔案被跳過** ——
> 用 **`-u`**（或 `--no-ignore`）；
> ②**★★★ 隱藏檔（`.` 開頭）預設不搜** ——
> 這在搜 `/etc` 或家目錄時很常踩，用 **`--hidden`** 或 `-uu`；
> ③**★★★★ 壓縮檔（`.gz`/`.bz2`/`.xz`）預設不搜** ——
> 搜輪替過的舊日誌時**一定要加 `-z`**；
> ④**★★ 二進位檔案預設跳過** —— 用 `-uuu` 或 `--text`。
> 另外符號連結預設不跟隨（用 `-L`）。
> **一次全開**：`rg -uuu --hidden -z -L "pattern"`。
> **建議設 alias**：`alias rgl='rg -uu -z --hidden'` 專門用來搜日誌與設定檔。
> **除錯**：`rg --debug "pattern" 2>&1 | grep -i ignor` 會告訴你哪些被跳過。
>
> **Q3.** **★★★★ `-z`（`--search-zip`）** ——
> 讓 rg 能搜尋 `.gz`、`.bz2`、`.xz`、`.zst`、`.lz4` 壓縮的檔案。
> ```bash
> rg -z '203\.0\.113\.45' /var/log/nginx/
> rg -z --stats '" 500 ' /var/log/nginx/access.log*
> ```
> **為什麼重要**：logrotate 會把舊日誌壓縮成 `access.log.2.gz`、
> `access.log.3.gz`…，**這些正是你排查「上禮拜的問題」時要看的**。
> 不加 `-z` 的話 rg 會**靜默跳過**（不會報錯），
> 你會以為「那段時間沒有這個錯誤」，得到完全錯誤的結論。
> 傳統做法是 `zgrep` 或 `zcat *.gz | grep`，
> 但 `rg -z` 一次搞定壓縮和未壓縮的檔案，而且快得多。
> 通常還要搭配 `-uu`（日誌目錄可能有 `.ignore` 或隱藏檔）。
>
> **Q4.** 因為 **Debian/Ubuntu 的套件庫中已經有其他套件用了 `fd` 和 `bat` 這兩個名稱**，
> 為了避免衝突，Debian 把它們改名為 **`fdfind`** 和 **`batcat`**。
> （`fd` 曾是 `fdclone` 的執行檔，`bat` 是 `bacula-console` 相關的。）
> **RHEL/Fedora 沒有這個問題**，執行檔就是 `fd` 和 `bat`。
> **解法**：
> ```bash
> mkdir -p ~/.local/bin
> ln -sf "$(command -v fdfind)" ~/.local/bin/fd
> ln -sf "$(command -v batcat)" ~/.local/bin/bat
> # ★ 確保 ~/.local/bin 在 PATH 中
> ```
> **注意**：寫腳本時**要用真正的執行檔名稱或做偵測**，
> 因為別台機器可能沒有你的符號連結：
> ```bash
> BAT=$(command -v batcat || command -v bat) || BAT=cat
> ```
>
> **Q5.** **`-r`（`--raw-output`）= 輸出字串時不加引號**。
> 預設 `jq '.name'` 會輸出 `"張三"`（含雙引號，因為那是合法的 JSON），
> 加 `-r` 才輸出 `張三` ——
> **要把結果餵給其他指令或存成變數時一定要加**：
> ```bash
> NAME=$(jq -r '.name' data.json)      # ★★★ 沒有 -r 會帶引號
> ```
> **`-e`（`--exit-status`）= 依結果設定 exit code** ——
> 結果為 `false` 或 `null` 時回傳 1，否則回傳 0（無輸出時回 4）。
> **這讓 jq 可以直接用在條件判斷**：
> ```bash
> curl -s .../health | jq -e '.status == "ok"' >/dev/null \
>   && echo "健康" || echo "★★★ 異常"
> ```
> 兩者常一起用：`jq -re '.token'`。
>
> **Q6.** ①**★★ `?` 安全存取運算子** ——
> `jq '.a?.b?'`，欄位不存在時回 `null` 而不是報錯
> （對非物件的值取欄位時特別有用）；
> ②**★★★ `//` 預設值運算子** ——
> `jq '.name // "未知"'`，值為 `null` 或 `false` 時使用預設值；
> ③**★★ `try ... catch`** ——
> `jq 'try .a.b catch "錯誤"'`，捕捉任何錯誤。
> **組合使用**：
> ```bash
> jq -r '.user?.email // "no-email"' data.json
> jq -r '[.items[]? | .name] | join(",")' data.json   # ★ 陣列可能不存在
> ```
> **常見錯誤**：`jq '.a.b'` 當 `.a` 是 `null` 時會噴
> `Cannot index null with "b"` 並讓整個腳本失敗 ——
> 處理外部 API 回應時**一定要用這些防護**。
>
> **Q7.** 因為 **這些工具的輸出格式與標準指令不同，會讓腳本行為不可預測**。
> **具體問題**：
> ①**★★★★ 輸出格式不同** —— `eza` 的欄位順序、`bat` 的行號與裝飾字元，
> 讓 `awk '{print $5}'`、`cut -d' ' -f3` 這類處理**取到錯的欄位**；
> ②**★★★ 顏色與控制字元** —— `bat` 預設加行號和邊框，
> `cat f.json | jq .` 會直接失敗（**要加 `-p`**）；
> ③**★★★ 選項不相容** —— `grep -P`、`ls -1`、`cat -A` 在替代工具上語意不同或不存在；
> ④**★★★★ 到別台機器就壞掉** —— 腳本假設有 `bat`，但正式機沒裝。
> **正確做法：用新名稱**：
> ```bash
> alias l='eza -la --git'
> alias b='batcat'
> alias rgl='rg -uu -z --hidden'
> ```
> 標準指令保持標準行為（`alias ls='ls --color=auto'` 這種只加選項的沒問題）。
>
> **Q8.** **★★★ 加 `-p`（`--plain`）或 `--style=plain`**。
> `bat` 預設會加上**行號、檔名標頭、Git 修改標記、左側邊框**，
> 這些在終端機看很棒，**但接管線時會變成垃圾字元**：
> ```bash
> batcat f.json | jq .            # ★★★★ 失敗（有行號和邊框）
> batcat -p f.json | jq .         # ★★ 正確
> ```
> **實際上 bat 有自動偵測** —— 當輸出不是 tty 時會自動切成 plain 模式，
> **但在某些情況（`--color=always`、某些版本）不會**，
> 所以**明確加 `-p` 比較保險**。
> 相關選項：`--style=plain,numbers`（只要行號）、
> `--color=never`（強制無色）、`-A` 顯示不可見字元（像 `cat -A`）。
> **腳本中建議直接用 `cat`**，bat 是給人看的。
>
> **Q9.** **三個風險**：
> ①**★★★★ 沒有安全更新** —— 套件庫的版本會隨系統更新自動拿到修補，
> **手動下載的 binary 放三年都不會有人提醒你有漏洞**；
> ②**★★★ 沒有簽章驗證** ——
> APT/DNF 會**自動驗證 GPG 簽章**（確認來自可信的維護者），
> 手動下載頂多比對一個 SHA256（而 checksum 檔案也可能被一起竄改）；
> ③**★★★ 無法追溯** —— `dpkg -S` 查不到來源，
> 稽核時說不清楚「這個 binary 哪來的、誰裝的、什麼版本」。
> **正確做法**：
> ①**★★★★ 優先用官方套件庫**（`apt install ripgrep`）；
> ②必須手動時**下載 `.deb`/`.rpm` 而不是裸 binary**（dpkg 能追溯）；
> ③**驗證 checksum** 並**記錄來源、版本、安裝者、日期**；
> ④**正式伺服器上盡量不裝**。
>
> **Q10.** **★★★ 伺服器上值得裝的只有兩個**：
> **`jq`** —— **幾乎是必需品**，
> 現代的 API、Docker、systemd、Kubernetes 全部輸出 JSON，
> 沒有 jq 就得用 grep/sed 硬拆（脆弱又難維護），
> 而且它在官方套件庫、體積小、無相依；
> **`ripgrep`** —— 在有大量日誌的機器上，
> 搜尋速度的差異是實質的（幾秒 vs 幾分鐘），也在官方套件庫。
> **其他不建議的理由**：
> ①**★★★★ 救援模式、剛裝好的機器、容器內只有傳統工具** ——
> 太依賴 fzf/eza 的人在最需要的時候反而不會用；
> ②**★★★ 多一個套件 = 多一個攻擊面與更新負擔**；
> ③**★★ 團隊其他人不會用，交接困難**；
> ④**★★★ 腳本若依賴這些工具，換台機器就跑不動**。
> **所以：傳統工具一定要熟，現代工具在工作機上隨便裝。**

---

## 延伸閱讀

- [[12-文字處理三劍客]] — **★★★★ grep / sed / awk 一定要會**
- [[03-Bash與Zsh效率設定]] — shell 設定與 alias
- [[07-尋找檔案與內容]] — `find` 與 `grep` 的完整用法
- [[05-curl-與HTTP除錯]] — 搭配 jq 處理 API 回應
- [[01-tmux-工作階段管理]] — 終端機工作流
- [[03-資源診斷工具集]] — 系統診斷工具
