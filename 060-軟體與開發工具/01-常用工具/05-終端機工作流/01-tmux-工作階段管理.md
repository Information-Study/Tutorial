---
title: "tmux 工作階段管理"
desc: "斷線不中斷、分割視窗、多人協作與設定檔"
aliases: [tmux, session, 工作階段, 斷線, detach]
tags: [群組/軟體與開發工具, 主題/終端機, 主題/tmux]
category: 常用工具
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[03-終端機與Shell入門]]"]
updated: 2026-08-28
---

# tmux 工作階段管理

> [!abstract] 這篇你會學到
> - **★★★★ 為什麼維運人員一定要用 tmux**（斷線不中斷）
> - session / window / pane 的三層結構
> - **★★★ 前綴鍵**與必背的快捷鍵
> - 分割視窗、複製模式、同步輸入
> - **★★★ 一份實用的 `.tmux.conf`**
> - **★★ 多人共用同一個 session**（教學與交接）
> - **★★★ tmux vs nohup vs systemd** 的取捨

## 前置知識

- [[03-終端機與Shell入門]] — 終端機基礎
- [[10-程序管理與訊號]] — 程序與訊號

---

## ★★★★ 為什麼一定要用

```
★★★★ 情境：SSH 到伺服器跑一個 30 分鐘的資料庫遷移

  【沒有 tmux】
    $ php artisan migrate
    ...跑到一半...
    → ★★★ 網路斷線 / 筆電休眠 / VPN 重連
    → ★★★★ SSH 連線中斷 → 【SIGHUP 送給所有子程序】
    → ★★★★ migrate 被殺掉 → 【資料庫停在一半的狀態】
    → ★★★ 而且你不知道跑到哪裡了

  【★★★ 有 tmux】
    $ tmux new -s migrate
    $ php artisan migrate
    → 斷線
    → ★★★★ tmux server 還在跑，程序完全不受影響
    → 重新連線後：
    $ tmux attach -t migrate
    → ★★★ 一切都在，包括完整的輸出

★★★★ 三個一定要用 tmux 的場景：
  ① 任何超過 30 秒的操作（migrate、備份、編譯、大量複製）
  ② ★★★ 改網路設定 / 防火牆（★ 斷線也還有救）
  ③ ★★ 需要同時開多個視窗的排查
```

---

## 安裝

```bash
$ sudo apt install -y tmux
$ tmux -V
tmux 3.4
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> $ sudo dnf install -y tmux
> ```

---

## ★★★ 三層結構

```
★★★★ tmux 的三層概念（★ 搞懂這個就會用了）：

  ┌─────────────────────────────────────────────────────┐
  │ ★★★ tmux server（背景常駐的程序）                    │
  │                                                      │
  │  ┌─────────────────────────────────────────────┐    │
  │  │ ★★★ session「migrate」                       │    │
  │  │   ★★ 可以 detach（離開）而不中斷               │    │
  │  │                                              │    │
  │  │  ┌──────────────┐ ┌──────────────┐          │    │
  │  │  │ ★★ window 0  │ │ ★★ window 1  │          │    │
  │  │  │  「logs」     │ │  「db」       │          │    │
  │  │  │              │ │              │          │    │
  │  │  │ ┌──┬───────┐ │ │ ┌──────────┐ │          │    │
  │  │  │ │★ │ pane  │ │ │ │  pane    │ │          │    │
  │  │  │ │p │  1    │ │ │ │          │ │          │    │
  │  │  │ │0 │       │ │ │ └──────────┘ │          │    │
  │  │  │ └──┴───────┘ │ │              │          │    │
  │  │  └──────────────┘ └──────────────┘          │    │
  │  └─────────────────────────────────────────────┘    │
  │                                                      │
  │  ┌─────────────────────────────────────────────┐    │
  │  │ session「deploy」...                         │    │
  │  └─────────────────────────────────────────────┘    │
  └─────────────────────────────────────────────────────┘

  ★★★ session = 一個「工作情境」（★ 一個專案、一次維護）
  ★★  window  = 一個分頁（★ 一個任務）
  ★   pane    = 分割的區塊（★ 同時看多個輸出）
```

---

## ★★★ 基本操作

### 從命令列

```bash
# ═══ ★★★★ 最常用的四個 ═══
$ tmux new -s migrate          # ★★★ 建立具名 session
$ tmux ls                      # ★★★ 列出所有 session
$ tmux attach -t migrate       # ★★★ 接回（★ 或 tmux a -t migrate）
$ tmux kill-session -t migrate # 刪除

# ★★ 其他
$ tmux                         # ★ 建立匿名 session（★ 不建議，難找）
$ tmux new -s db -d            # ★★ 建立但不進去（背景）
$ tmux attach                  # ★ 接回最近的
$ tmux a                       # ★★ 縮寫
$ tmux ls -F '#{session_name}: #{session_windows} windows'
$ tmux kill-server             # ★★★ 殺掉所有（★ 小心！）

# ★★★ 在 session 內建立新視窗並執行指令
$ tmux new-session -d -s backup 'bash /usr/local/bin/backup.sh'
$ tmux send-keys -t backup 'echo hello' Enter
```

```bash
$ tmux ls
migrate: 3 windows (created Thu Aug 28 16:50:11 2026)
deploy: 1 windows (created Thu Aug 28 15:20:33 2026) (attached)
#                                                      ↑ ★★ 目前接著的
```

### ★★★★ 前綴鍵

```
★★★★ tmux 的所有快捷鍵都要先按【前綴鍵】

  預設前綴鍵 = Ctrl + b        （★ 文件寫成 C-b 或 prefix）

  ★★★ 用法：先按 Ctrl+b 放開，再按功能鍵

  例：分割視窗
    ① 按 Ctrl + b（放開）
    ② 按 %

★★★ 很多人改成 Ctrl + a（★ 和 screen 一致，左手比較好按）
  → 見下方 .tmux.conf
```

### ★★★ 必背的快捷鍵

| 按鍵（`C-b` 之後） | 作用 |
| --- | --- |
| **`d`** | **★★★★ detach（離開但不中斷）** |
| **`c`** | **★★★ 新建 window** |
| **`n`** / **`p`** | 下一個 / 上一個 window |
| **`0`~`9`** | **★★ 跳到第 N 個 window** |
| **`w`** | **★★★ 列出所有 window 選擇** |
| **`,`** | **★★ 重新命名 window** |
| **`&`** | 關閉 window（★ 會問） |
| **`%`** | **★★★ 垂直分割**（左右） |
| **`"`** | **★★★ 水平分割**（上下） |
| **`方向鍵`** | **★★★ 切換 pane** |
| **`o`** | 循環切換 pane |
| **`z`** | **★★★★ pane 全螢幕切換**（超好用） |
| **`x`** | 關閉 pane |
| **`空白`** | ★★ 切換版面配置 |
| **`{`** / **`}`** | 移動 pane 位置 |
| **`C-方向鍵`** | ★★ 調整 pane 大小 |
| **`[`** | **★★★ 進入複製模式**（捲動歷史） |
| **`]`** | 貼上 |
| **`s`** | **★★★ 列出所有 session 切換** |
| **`$`** | 重新命名 session |
| **`t`** | 顯示時鐘 |
| **`?`** | **★★ 顯示所有快捷鍵** |
| **`:`** | **★★★ 進入指令模式** |

```
★★★★ 最重要的三個：

  C-b d     ★★★★ detach —— 離開但程式繼續跑
  C-b [     ★★★ 複製模式 —— 往上捲看之前的輸出
  C-b z     ★★★★ 全螢幕切換 —— 暫時把一個 pane 放大
```

> [!danger] `Ctrl+b d` vs `exit` ★★★
> ```
> ★★★★ C-b d（detach）
>   → 離開 tmux，★★★ 但 session 和裡面的程式【繼續跑】
>   → 可以再 attach 回來
>
> ★★★ exit / C-d
>   → ★★★★ 結束目前的 shell
>   → pane 關閉 → window 沒 pane 了就關閉
>   → ★★★ 最後一個 window 關掉 → 【session 消失】
>   → ★★★★ 裡面跑的程式【被殺掉】
>
> ★★★ 記法：要走人用 d，要結束用 exit
> ```

---

## 複製模式 ★★★

```
★★★★ 為什麼需要：
  · ★★★ tmux 攔截了滑鼠滾輪 → 直接滾動不會捲歷史
  · 要複製輸出給別人看
  · 要搜尋之前的輸出

★★★ 進入：C-b [
  → 左上角出現 [0/2847]（★ 目前位置/總行數）
```

```
★★★ 複製模式的操作（★ vi 模式）：

  ↑↓ / k j       上下移動
  C-u / C-d      半頁
  C-b / C-f      整頁
  g / G          ★★ 頂端 / 底部
  ★★★ /pattern   向下搜尋
  ★★★ ?pattern   向上搜尋
  n / N          下一個 / 上一個
  ★★★ 空白       開始選取
  ★★★ Enter      複製並離開
  q / Esc        離開

★★ emacs 模式（預設）：
  C-Space 開始選取，M-w 複製
  → ★★★ 建議在 .tmux.conf 設 setw -g mode-keys vi
```

```bash
# ★★★ 把 tmux 的緩衝區存成檔案（★ 保存排查記錄）
$ tmux capture-pane -pS -3000 > /tmp/output.txt
#   -p   輸出到 stdout
#   ★★★ -S -3000  從往前 3000 行開始

# ★★ 指定 pane
$ tmux capture-pane -t migrate:1.0 -pS - > /tmp/full.txt
#   ★★ -S - = 全部歷史

# ★★ 列出 tmux 的貼上緩衝區
$ tmux list-buffers
$ tmux show-buffer
$ tmux save-buffer /tmp/buf.txt

# ★★★ 開啟即時記錄（★ 排查時很有用）
#   C-b : 然後輸入
#   pipe-pane -o 'cat >> /tmp/tmux-#S-#I-#P.log'
```

---

## ★★★ 一份實用的 .tmux.conf

```bash
$ vim ~/.tmux.conf
```

```tmux
# ~/.tmux.conf —— 維運用設定

# ═══ ★★★ 前綴鍵改成 Ctrl+a ═══
unbind C-b
set -g prefix C-a
bind C-a send-prefix          # ★★ 按兩次送出真正的 C-a（★ 回到行首）

# ═══ ★★★ 基本 ═══
set -g mouse on               # ★★★ 滑鼠可捲動、選 pane、調大小
set -g history-limit 50000    # ★★★ 歷史行數（★ 預設只有 2000）
set -g base-index 1           # ★★ window 從 1 開始（★ 鍵盤好按）
setw -g pane-base-index 1
set -g renumber-windows on    # ★★ 關掉視窗後重新編號
set -sg escape-time 10        # ★★★ 減少 Esc 延遲（★ vim 使用者必設）
set -g display-time 2000      # 訊息顯示時間
set -g focus-events on
set -g set-titles on
set -g set-titles-string '#S:#I.#P #W'

# ★★★ 支援真彩色（★ 讓 vim/btop 顏色正常）
set -g default-terminal "tmux-256color"
set -ga terminal-overrides ",*256col*:Tc"
set -ga terminal-overrides ",xterm-256color:Tc"

# ═══ ★★★ 複製模式用 vi ═══
setw -g mode-keys vi
bind -T copy-mode-vi v send -X begin-selection
bind -T copy-mode-vi y send -X copy-selection-and-cancel
bind -T copy-mode-vi Escape send -X cancel

# ★★ 系統剪貼簿（★ 需要 xclip 或 wl-copy）
if-shell 'command -v xclip' \
  'bind -T copy-mode-vi y send -X copy-pipe-and-cancel "xclip -sel clip -i"'
# ★★ WSL
if-shell '[ -n "$WSL_DISTRO_NAME" ]' \
  'bind -T copy-mode-vi y send -X copy-pipe-and-cancel "clip.exe"'

# ═══ ★★★ 分割視窗（★ 記號更直覺，且保持目前路徑）═══
bind | split-window -h -c "#{pane_current_path}"
bind - split-window -v -c "#{pane_current_path}"
bind c new-window -c "#{pane_current_path}"
unbind '"'
unbind %

# ═══ ★★★ pane 切換（vim 風格，不用前綴鍵）═══
bind -n M-h select-pane -L    # ★★ Alt+h/j/k/l
bind -n M-j select-pane -D
bind -n M-k select-pane -U
bind -n M-l select-pane -R

# ★★ 調整大小（★ 可重複按）
bind -r H resize-pane -L 5
bind -r J resize-pane -D 5
bind -r K resize-pane -U 5
bind -r L resize-pane -R 5

# ★★ window 切換
bind -n M-1 select-window -t 1
bind -n M-2 select-window -t 2
bind -n M-3 select-window -t 3
bind -r C-h previous-window
bind -r C-l next-window

# ═══ ★★★ 重載設定 ═══
bind r source-file ~/.tmux.conf \; display "★ 設定已重載"

# ═══ ★★★★ 同步輸入（★ 多台機器同時操作）═══
bind S setw synchronize-panes \; \
  display "同步輸入: #{?pane_synchronized,★★★ 開,關}"

# ═══ ★★ 狀態列 ═══
set -g status-interval 5
set -g status-position bottom
set -g status-justify left
set -g status-style 'bg=colour234 fg=colour137'

set -g status-left-length 40
set -g status-left '#[fg=colour233,bg=colour245,bold] #S #[default] '

set -g status-right-length 80
set -g status-right '#[fg=colour233,bg=colour241] #(uptime | grep -oP "load average: \\K.*" | cut -d, -f1) #[fg=colour233,bg=colour245,bold] %m-%d %H:%M '

setw -g window-status-current-style 'fg=colour1 bg=colour238 bold'
setw -g window-status-current-format ' #I#[fg=colour249]:#[fg=colour255]#W#[fg=colour249]#F '
setw -g window-status-format ' #I#[fg=colour237]:#[fg=colour250]#W#[fg=colour244]#F '

# ★★★ 同步輸入時狀態列變紅（★ 避免誤操作）
set -g status-style '#{?pane_synchronized,bg=colour160 fg=colour255,bg=colour234 fg=colour137}'

# ═══ ★★ pane 邊框 ═══
set -g pane-border-style 'fg=colour238'
set -g pane-active-border-style 'fg=colour208'
set -g pane-border-status top
set -g pane-border-format ' #P: #{pane_current_command} '

# ═══ ★★ 活動通知 ═══
setw -g monitor-activity on
set -g visual-activity off
set -g bell-action none
```

```bash
# ★★ 套用
$ tmux source-file ~/.tmux.conf
#   ★ 或在 tmux 內按 C-a r（★ 如果已經設好）

# ★★ 驗證設定
$ tmux show-options -g | grep -E 'prefix|mouse|history-limit'
prefix C-a
mouse on
history-limit 50000
```

> [!tip] `escape-time` 為什麼要設 ★★★
> ```
> ★★★ tmux 預設 escape-time 是 500ms
>   → 按 Esc 之後會【等 500ms】看是不是跳脫序列的開頭
>   → ★★★★ 在 vim 裡按 Esc 離開 Insert 模式會有明顯延遲
>
> ★★ 設 set -sg escape-time 10（10ms）
>   → ★★★ vim 立刻回應
>   → ★ 注意是 -sg（server 層級的全域）
> ```

---

## ★★ 實用技巧

### ★★★★ 同步輸入（多機操作）

```bash
# ═══ ★★★ 情境：同時對 4 台機器執行相同指令 ═══
$ tmux new -s cluster
#   C-a |  分割成兩個
#   C-a -  各再分割一次 → 4 個 pane

#   在每個 pane 分別 SSH
$ ssh web01     # pane 1
$ ssh web02     # pane 2
$ ssh web03     # pane 3
$ ssh web04     # pane 4

#   ★★★★ 開啟同步（C-a S，或 C-a : setw synchronize-panes）
#   → ★★★ 狀態列變紅色
#   → 現在打的每一個字都會送到【所有 pane】

$ sudo systemctl status nginx    # ★★★ 四台同時執行
$ uptime

#   ★★★★ 用完一定要關掉！（再按一次 C-a S）
```

> [!danger] 同步輸入的風險 ★★★★
> ```
> ★★★★ 忘記關掉同步 = 在四台機器上同時執行危險指令
>
>   $ sudo rm -rf /var/www/old      ← ★★★★ 四台一起刪
>   $ sudo systemctl stop nginx     ← ★★★★ 服務全掛
>
> ★★★ 三個防護：
>   ① ★★★★ 狀態列變色（上面的設定檔已包含）
>   ② ★★ 用完立刻關
>   ③ ★★★ 只用於【唯讀的查詢指令】
>      → 修改類的操作用 Ansible / 逐台執行
> ```

```bash
# ★★★ 更好的做法：用腳本而不是同步輸入
$ for h in web01 web02 web03 web04; do
    printf "═══ %s ═══\n" "$h"
    ssh "$h" 'systemctl is-active nginx; uptime'
  done

# ★★ 或用 tmux 腳本產生
$ cat > /usr/local/bin/tmux-cluster <<'EOF'
#!/usr/bin/env bash
# ★★ 用法: tmux-cluster web01 web02 web03 web04
S="cluster-$$"
tmux new-session -d -s "$S" "ssh $1"
shift
for h in "$@"; do
    tmux split-window -t "$S" "ssh $h"
    tmux select-layout -t "$S" tiled
done
tmux attach -t "$S"
EOF
$ sudo install -m755 /usr/local/bin/tmux-cluster /usr/local/bin/tmux-cluster
```

### ★★ 多人共用 session

```bash
# ═══ ★★★ 情境：教學、交接、共同排查 ═══

# ★★ 方法一：同一個使用者（★ 最簡單）
#   A 建立
$ tmux new -s shared
#   B 用同一個帳號 SSH 進來後
$ tmux attach -t shared
#   → ★★★ 兩人看到同一個畫面，都可以打字

# ★★ 視窗大小不同時，畫面會被限制在較小的那個
#   → ★★★ 讓兩人獨立切換 window：
$ tmux new-session -t shared -s shared-b     # ★★ 共用 window 但獨立 session

# ★★★ 唯讀模式（★ 讓對方只能看不能打）
$ tmux attach -t shared -r

# ★★ 方法二：不同使用者（★ 用 socket）
#   A：
$ tmux -S /tmp/shared-sock new -s pair
$ chmod 770 /tmp/shared-sock
$ sudo chgrp devteam /tmp/shared-sock
#   B（同群組）：
$ tmux -S /tmp/shared-sock attach -t pair
```

### ★★ 自動化與腳本

```bash
#!/usr/bin/env bash
# ★★★ /usr/local/bin/tmux-ops —— 建立標準的維運工作環境
S="ops"

tmux has-session -t "$S" 2>/dev/null && { tmux attach -t "$S"; exit; }

# ★★ window 1: 日誌
tmux new-session -d -s "$S" -n logs
tmux send-keys -t "$S:logs" 'sudo tail -f /var/log/nginx/error.log' C-m
tmux split-window -t "$S:logs" -v
tmux send-keys -t "$S:logs.2" 'sudo tail -f /var/log/php8.3-fpm.log' C-m
tmux split-window -t "$S:logs.1" -h
tmux send-keys -t "$S:logs.3" 'sudo tail -f /var/www/app/current/storage/logs/laravel-$(date +%F).log' C-m
tmux select-layout -t "$S:logs" tiled

# ★★ window 2: 監控
tmux new-window -t "$S" -n monitor
tmux send-keys -t "$S:monitor" 'htop' C-m
tmux split-window -t "$S:monitor" -h
tmux send-keys -t "$S:monitor.2" 'watch -n 5 "curl -s http://127.0.0.1/status?full | head -20"' C-m

# ★★ window 3: 工作
tmux new-window -t "$S" -n work -c /var/www/app/current

tmux select-window -t "$S:logs"
tmux attach -t "$S"
```

```bash
# ★★ 開機自動啟動（systemd user service）
$ mkdir -p ~/.config/systemd/user
$ cat > ~/.config/systemd/user/tmux-ops.service <<'EOF'
[Unit]
Description=tmux ops session
After=network.target

[Service]
Type=forking
ExecStart=/usr/bin/tmux new-session -d -s ops
ExecStop=/usr/bin/tmux kill-session -t ops
Restart=no

[Install]
WantedBy=default.target
EOF
$ systemctl --user enable --now tmux-ops
$ sudo loginctl enable-linger "$USER"     # ★★★ 登出後仍保留
```

---

## ★★★ tmux vs nohup vs systemd

| | **tmux / screen** | **nohup / disown** | **★★★ systemd** |
| --- | --- | --- | --- |
| 用途 | **★★★ 互動式的長時間工作** | ★★ 一次性的背景任務 | **★★★ 長期執行的服務** |
| **可以再接回來** | **★★★★ 是** | ✗ | ✗（★ 用 journalctl 看） |
| 開機自動啟動 | ★ 要另外設定 | ✗ | **★★★ 是** |
| **自動重啟** | ✗ | ✗ | **★★★ 是** |
| 資源限制 | ✗ | ✗ | **★★★ 是**（cgroup） |
| 日誌管理 | ★ 自己處理 | ★ 導向檔案 | **★★★ journald** |
| **適合正式服務** | **✗✗** | ✗✗ | **★★★★ 是** |

```bash
# ★★★ tmux —— 互動式、需要看輸出、可能要介入
$ tmux new -s migrate
$ php artisan migrate --force

# ★★ nohup —— 一次性、不需要互動
$ nohup ./long-backup.sh > /var/log/backup-$(date +%F).log 2>&1 &
$ disown                          # ★★ 從 shell 的 job table 移除
$ jobs                            # ★ 確認

# ★★★★ systemd —— 長期執行的服務（★ 正式環境唯一正解）
$ sudo tee /etc/systemd/system/myworker.service >/dev/null <<'EOF'
[Unit]
Description=My worker
After=network.target mysql.service

[Service]
Type=simple
User=deploy
WorkingDirectory=/var/www/app/current
ExecStart=/usr/bin/php artisan queue:work --tries=3
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
MemoryMax=512M

[Install]
WantedBy=multi-user.target
EOF
$ sudo systemctl enable --now myworker
$ journalctl -u myworker -f
```

> [!danger] 不要用 tmux 跑正式服務 ★★★★
> ```
> ★★★★ 常見的錯誤做法：
>   $ tmux new -s app
>   $ node server.js
>   $ C-a d
>   → 「這樣服務就一直跑著了」
>
> ★★★★ 三個嚴重問題：
>   ① 【機器重開機後不會自動啟動】
>      → ★★★ 半夜停電、核心更新重開 → 服務就消失了
>   ② 【程式崩潰不會自動重啟】
>      → ★★★ 沒有 Restart=always
>   ③ ★★★ 【沒有日誌管理、沒有資源限制】
>      → 日誌只在 tmux 的緩衝區裡，輪替一下就沒了
>      → 記憶體洩漏時沒有 MemoryMax 保護
>   ④ ★★ 【誰都不知道它在哪裡跑】
>      → 交接時新人找不到；systemctl status 看不到
>
> ★★★★ 正式服務一律用 systemd（見 [[17-systemd服務管理]]）
> ```

---

## 完整實戰範例：安全地執行資料庫遷移

```bash
# ═══ ★★★【1】建立 session ═══
$ tmux new -s migrate-$(date +%Y%m%d)
#   ★★ 加日期方便辨識

# ═══ ★★【2】分割成三個 pane ═══
#   C-a |     垂直分割
#   C-a -     再水平分割

#   ┌─────────────────┬──────────────┐
#   │                 │  ★ pane 2    │
#   │  ★★★ pane 1     │  監控         │
#   │  執行遷移        ├──────────────┤
#   │                 │  ★ pane 3    │
#   │                 │  日誌         │
#   └─────────────────┴──────────────┘

# ── pane 2：監控 ──
$ watch -n 5 'mysql -e "SHOW PROCESSLIST" 2>/dev/null | head -20; echo; \
              mysql -e "SHOW ENGINE INNODB STATUS\G" 2>/dev/null | \
              grep -A3 "LATEST DETECTED DEADLOCK" | head -5'

# ── pane 3：日誌 ──
$ sudo tail -f /var/log/mysql/error.log

# ── pane 1：★★★ 執行前的準備 ──
$ cd /var/www/app/current

#   ★★★ 備份
$ TS=$(date +%Y%m%d-%H%M%S)
$ DB=$(grep '^DB_DATABASE=' .env | cut -d= -f2-)
$ mysqldump --single-transaction --routines --triggers --no-tablespaces \
    "$DB" | gzip > "/backup/db/$DB-before-migrate-$TS.sql.gz"
$ ls -lh "/backup/db/$DB-before-migrate-$TS.sql.gz"
-rw-r--r-- 1 deploy deploy 842M ... $DB-before-migrate-20260828-170011.sql.gz

#   ★★★ 先看會執行什麼
$ php artisan migrate --pretend
Migrating: 2026_08_20_000001_add_index_to_orders
   ALTER TABLE orders ADD INDEX idx_created_at (created_at)

#   ★★★★ 大表的話先估時間
$ mysql -e "SELECT COUNT(*) FROM $DB.orders"
4820000
#   ★★ 482 萬列加索引，估計 5~15 分鐘

# ═══ ★★★★【3】開始記錄輸出 ═══
#   C-a : 然後輸入：
#   pipe-pane -o 'cat >> /tmp/migrate-#S-#I-#P.log'

# ═══ ★★★【4】執行 ═══
$ time php artisan migrate --force
Migrating: 2026_08_20_000001_add_index_to_orders

#   ★★★★ 這時候可以安心 C-a d 離開，去做別的事
#   → 網路斷線也不影響

# ═══ ★★【5】隨時回來看 ═══
$ tmux ls
migrate-20260828: 1 windows (created Thu Aug 28 17:00:11 2026)
$ tmux attach -t migrate-20260828

Migrated:  2026_08_20_000001_add_index_to_orders (482331.21ms)
real	8m2.341s

# ═══ ★★★【6】驗證 ═══
$ mysql -e "SHOW INDEX FROM $DB.orders" | grep created_at
orders	1	idx_created_at	1	created_at	A	4820000	...

$ mysql -e "EXPLAIN SELECT * FROM $DB.orders
            WHERE created_at BETWEEN '2026-08-01' AND '2026-08-28'\G" | \
    grep -E 'type|key|rows'
         type: range
          key: idx_created_at
         rows: 12400                    # ★★★★ 482 萬 → 1.2 萬

$ curl -sko /dev/null -w 'TTFB=%{time_starttransfer}s\n' \
    https://app.example.gov.tw/api/reports
TTFB=0.412s                             # ★★★ 12s → 0.4s

# ═══ ★★【7】保存記錄 ═══
$ tmux capture-pane -pS - > "/var/log/migrations/migrate-$TS.log"
$ cp /tmp/migrate-*.log "/var/log/migrations/"

# ═══ 【8】清理 ═══
$ exit                                  # 關掉各 pane
#   ★ 或 tmux kill-session -t migrate-20260828
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **滑鼠滾輪不能捲** ★★★ | 沒開 mouse | **`set -g mouse on`**；或 `C-b [` |
| **開了 mouse 後不能用終端機複製** ★★★ | tmux 攔截滑鼠 | **按住 Shift 再選取** |
| **vim 的 Esc 有延遲** ★★★ | `escape-time` 500ms | **`set -sg escape-time 10`** |
| **顏色不對 / vim 沒顏色** ★★★ | `TERM` 設定 | **`default-terminal "tmux-256color"`** + `terminal-overrides` |
| **`exit` 後 session 不見了** ★★★ | 那是正常的 | **用 `C-b d` detach** |
| **接不回來 `no sessions`** ★★★ | server 被殺／機器重開 | `tmux ls`；**正式服務用 systemd** |
| **往上捲不到之前的輸出** ★★★ | `history-limit` 太小 | **`set -g history-limit 50000`** |
| **同步輸入忘記關** ★★★★ | 沒有視覺提示 | **狀態列變色**；用完立刻關 |
| **巢狀 tmux（本機+遠端）** ★★★ | 前綴鍵衝突 | 遠端按兩次前綴；或用不同的前綴鍵 |
| **中文變亂碼** ★★ | locale / UTF-8 | `tmux -u`；`LANG=zh_TW.UTF-8` |
| **設定改了沒生效** ★★ | 沒重載 | `tmux source-file ~/.tmux.conf` |
| **視窗大小被限制** ★★ | 多人 attach | `tmux new-session -t` 共用 window |

### 排查

```bash
# 【1】★★ 目前的設定
$ tmux show-options -g | head -30
$ tmux show-options -g | grep -E 'prefix|mouse|history|escape'
$ tmux show-window-options -g

# 【2】★★ 快捷鍵綁定
$ tmux list-keys | grep -i split
$ tmux list-keys -T copy-mode-vi

# 【3】★★ session / window / pane
$ tmux ls
$ tmux list-windows -a
$ tmux list-panes -a -F '#{session_name}:#{window_index}.#{pane_index} #{pane_current_command}'

# 【4】★★★ TERM 與顏色
$ echo "$TERM"
tmux-256color                       # ★ tmux 內
$ tput colors
256
$ tmux info | grep -i term

# 【5】★ server 狀態
$ tmux info | head -20
$ ps -ef | grep [t]mux

# 【6】★★ 設定檔語法
$ tmux source-file ~/.tmux.conf
#   ★ 有錯會直接顯示行號

# 【7】★★ 巢狀 tmux 的判斷
$ echo "$TMUX"
/tmp/tmux-1000/default,12345,0      # ★★ 有值 = 已經在 tmux 裡
```

> [!tip] 巢狀 tmux 的處理 ★★★
> ```
> ★★★ 情境：本機開 tmux，SSH 到遠端又開 tmux
>   → ★★★★ 前綴鍵會被【本機的 tmux 攔截】
>
> ★★★ 三個解法：
>   ① ★★ 按兩次前綴鍵送給內層
>      C-a C-a d   →  detach 遠端的 tmux
>
>   ② ★★★ 遠端用不同的前綴鍵（★ 最清楚）
>      # 遠端的 ~/.tmux.conf
>      set -g prefix C-s
>
>   ③ ★★ 加一個切換鍵（本機的 .tmux.conf）
>      bind -T root F12 \
>        set prefix None \; set key-table off \; \
>        set status-style 'bg=colour238' \; \
>        refresh-client -S
>      bind -T off F12 \
>        set -u prefix \; set -u key-table \; \
>        set -u status-style \; refresh-client -S
>      → ★★★ 按 F12 讓外層 tmux「休眠」，所有按鍵直接給內層
> ```

---

## 安全性注意事項

> [!danger] 四個要點 ★★★
> ```
> ① ★★★★ tmux socket 的權限
>      → 預設在 /tmp/tmux-<uid>/，權限 700
>      → ★★★ 共用時 chmod 770 + 限定群組
>      → ★★★★ 絕對不要 chmod 777（★ 任何人都能接管你的 session）
>
> ② ★★★★ session 裡可能有已認證的狀態
>      → sudo 的時效、已登入的資料庫連線、SSH agent
>      → ★★★ 誰能 attach = 誰能用你的權限
>
> ③ ★★★ 緩衝區含歷史輸出
>      → ★★★★ 密碼、token、資料庫查詢結果
>      → ★★ 敏感操作後 C-b : clear-history
>
> ④ ★★ 不要用 root 跑長駐的 tmux
>      → ★★★ 留著一個 root shell 是很大的風險
>      → ★ 用一般使用者 + sudo
> ```

```bash
# ★★★ 檢查 socket 權限
$ ls -ld /tmp/tmux-$(id -u)/
drwx------ 2 admin admin 60 Aug 28 17:00 /tmp/tmux-1000/     # ★★★ 700 正確
$ ls -l /tmp/tmux-$(id -u)/
srw------- 1 admin admin 0 Aug 28 17:00 default

# ★★★★ 危險的設定
$ chmod 777 /tmp/tmux-1000/default     # ★★★★ 絕對不要！
#   → 任何使用者都能 tmux -S 該 socket attach
#   → ★★★ 等於拿到你的 shell

# ★★★ 共用時的正確做法
$ sudo groupadd -f devteam
$ sudo usermod -aG devteam alice
$ sudo usermod -aG devteam bob
$ tmux -S /tmp/pair.sock new -s pair -d
$ chmod 770 /tmp/pair.sock
$ sudo chgrp devteam /tmp/pair.sock
$ ls -l /tmp/pair.sock
srwxrwx--- 1 admin devteam 0 Aug 28 17:05 /tmp/pair.sock     # ★★★ 正確

# ★★★ 清除歷史（★ 敏感操作後）
#   在 tmux 內：C-a : clear-history
$ tmux clear-history -t ops:1.1
$ tmux clear-history -a                # ★★ 所有 pane

# ★★ 檢查有沒有留下敏感內容
$ tmux capture-pane -pS - | grep -iE 'password|token|secret|BEGIN.*PRIVATE'

# ★★★ 檢查誰在跑 tmux（★ 稽核）
$ ps -eo user,pid,etime,cmd | grep '[t]mux'
$ ls -l /tmp/tmux-*/
$ who
$ sudo lsof -U 2>/dev/null | grep tmux | head

# ★★ 長時間閒置自動 detach（★ 減少風險）
#   ~/.tmux.conf:
#   set -g lock-after-time 1800        # ★ 30 分鐘後鎖定
#   set -g lock-command "vlock"        # ★ 需要 apt install vlock
```

---

## 速查表

### ★★★★ 必背五個

```
tmux new -s 名稱         建立
tmux ls                  列出
tmux attach -t 名稱      接回
★★★★ C-b d              detach（★ 離開但不中斷）
★★★ C-b [               複製模式（★ 往上捲）
```

### 快捷鍵（`C-b` 之後）

```
d  ★★★★ detach       c  新 window     w  ★★ 選 window
%  垂直分割           "  水平分割      z  ★★★★ pane 全螢幕
方向鍵 切換 pane      x  關 pane       o  循環
[  ★★★ 複製模式      s  ★★ 選 session  ,  改名
:  ★★★ 指令模式      ?  說明
```

### ★★★ .tmux.conf 精華

```tmux
set -g prefix C-a                      # ★★★ 換前綴鍵
set -g mouse on                        # ★★★ 滑鼠
set -g history-limit 50000             # ★★★ 歷史（★ 預設只有 2000）
set -sg escape-time 10                 # ★★★ vim 的 Esc 延遲
set -g default-terminal "tmux-256color"
set -ga terminal-overrides ",*256col*:Tc"   # ★★★ 真彩色
setw -g mode-keys vi                   # ★★ 複製模式用 vi
set -g base-index 1
bind r source-file ~/.tmux.conf \; display "重載"
bind S setw synchronize-panes          # ★★★★ 同步輸入
```

### ★★★ 複製模式

```
C-b [        進入
/pattern     ★★★ 搜尋      n / N  下一個/上一個
空白         開始選取       Enter  複製
g / G        頂端 / 底部    q      離開
tmux capture-pane -pS -3000 > /tmp/out.txt    # ★★★ 存成檔案
```

### ★★★★ 選哪個工具

```
tmux      ★★★ 互動式、長時間、要看輸出、可能要介入
nohup     ★★ 一次性背景任務
★★★★ systemd  長期執行的服務（★ 正式環境唯一正解）
★★★★ 不要用 tmux 跑正式服務（重開機就沒了）
```

### ★★★ 同步輸入

```
C-a S          切換（★ 狀態列變紅）
★★★★ 用完立刻關！
★★★ 只用於唯讀查詢，修改類的用 Ansible
```

### ★★ 安全

```bash
ls -ld /tmp/tmux-$(id -u)/       # ★★★ 應該是 700
chmod 770 + chgrp devteam        # ★★★ 共用的正確做法
★★★★ 絕不 chmod 777
C-a : clear-history              # ★★ 敏感操作後清緩衝區
```

---

## 練習題

> [!question]- 練習 1：斷線測試 ★★★★
> 1. **`tmux new -s test` 然後跑 `while true; do date; sleep 2; done`**
> 2. **直接關掉終端機視窗**（模擬斷線）
> 3. 重新 SSH 進來，**`tmux ls`** → 還在嗎？
> 4. **`tmux attach -t test`** → 程式還在跑嗎？
> 5. **不用 tmux 重做一次** → 結果如何？
> 6. **用 `nohup` 再做一次** → 差別在哪？

> [!question]- 練習 2：分割與複製模式 ★★★
> 1. 建立 session，**分割成 4 個 pane**
> 2. 每個 pane 跑不同的指令（`htop` / `tail -f` / `watch`）
> 3. **用 `C-b z` 把其中一個放大再縮小**
> 4. **`C-b [` 進複製模式，用 `/` 搜尋**
> 5. **`tmux capture-pane -pS -1000 > /tmp/x.txt`** → 內容對嗎？
> 6. **設 `history-limit 50000` 後重測** → 能捲多遠？

> [!question]- 練習 3：.tmux.conf ★★★
> 1. **建立 `~/.tmux.conf`，改前綴鍵為 `C-a`**
> 2. 開啟 mouse、設 `history-limit`
> 3. **設 `escape-time 10`，在 tmux 裡開 vim 測 Esc 的延遲**
> 4. **設 `default-terminal` 和 `terminal-overrides`** → vim 顏色正常了嗎？
> 5. 加 `bind r source-file` 並測試
> 6. **`tmux show-options -g` 驗證所有設定**

> [!question]- 練習 4：同步輸入 ★★★★
> 1. 建立 4 個 pane，各 SSH 到不同的機器（或都連本機）
> 2. **開啟同步輸入（`C-a S`）**
> 3. **狀態列有變色嗎？**（沒有的話加上設定）
> 4. 執行 `uptime` → 四個都跑了嗎？
> 5. **關掉同步，再執行一次** → 呢？
> 6. **寫一個腳本用 `for` 迴圈做同樣的事**，比較兩種做法

> [!question]- 練習 5：tmux vs systemd ★★★★
> 1. **用 tmux 跑一個 `python3 -m http.server 8000`**
> 2. `C-a d` 離開，確認服務還在
> 3. **重開機**（或 `tmux kill-server`）→ 服務還在嗎？
> 4. **改用 systemd service 做同樣的事**
> 5. `systemctl restart` / 重開機 → 呢？
> 6. **列出三個 systemd 有而 tmux 沒有的功能**

---

## 小測驗

Q1. **為什麼維運人員一定要用 tmux**？舉一個具體的災難情境。

Q2. **`C-b d` 和 `exit` 的差別**？

Q3. **session / window / pane 的關係**？

Q4. **`set -sg escape-time 10` 解決什麼問題**？

Q5. **開了 `mouse on` 之後不能用終端機複製，怎麼辦**？

Q6. **為什麼不該用 tmux 跑正式服務**？（至少三個理由）

Q7. **同步輸入（`synchronize-panes`）有什麼風險**？三個防護？

Q8. **本機和遠端都開 tmux，前綴鍵衝突怎麼解**？

Q9. **`tmux capture-pane` 做什麼**？什麼時候用？

Q10. **共用 tmux session 時，socket 權限該怎麼設**？為什麼不能 777？

> [!question]- 測驗答案
> **Q1.** 因為 **SSH 連線中斷時，核心會對該連線的所有子程序送出 SIGHUP，把它們全部殺掉**。
> **具體災難**：你 SSH 到伺服器執行 `php artisan migrate`，
> 這個遷移要跑 8 分鐘（482 萬列的表加索引）——
> 跑到第 5 分鐘時**筆電休眠 / VPN 重連 / 網路抖動**，
> SSH 斷線 → migrate 被 SIGHUP 殺掉 →
> **★★★★ 資料庫停在一半的狀態**：
> 索引建到一半、`migrations` 表的紀錄不完整、
> 而且**你完全不知道跑到哪裡了**，要花更多時間去釐清和修復。
> **有 tmux 的話**：tmux server 是獨立的背景程序，
> SSH 斷線完全不影響它，重新連線 `tmux attach` 就能看到完整的過程與結果。
> **三個必用場景**：任何超過 30 秒的操作、
> **改網路或防火牆設定**（斷線也還有救）、需要多視窗的排查。
>
> **Q2.** **`C-b d`（detach）= 離開 tmux，但 session 和裡面的程式繼續跑**，
> 隨時可以 `tmux attach` 接回來。
> **`exit`（或 `C-d`）= 結束目前的 shell** ——
> 那個 pane 關閉；window 的最後一個 pane 關掉時 window 關閉；
> **session 的最後一個 window 關掉時，session 消失，裡面跑的程式被殺掉**。
> **記法：要走人用 `d`，要結束用 `exit`**。
> 這是新手最容易犯的錯 ——
> 習慣性地打 `exit` 想「離開」，結果把整個 session 連同執行中的工作都結束了。
> 補充：`tmux ls` 可以確認 session 是否還在；
> 如果不小心 `exit` 了，程式已經被殺掉，沒有辦法救回。
>
> **Q3.** **三層包含關係**：
> **session（工作階段）** = 一個「工作情境」，例如一次維護、一個專案 ——
> **這是可以 detach 和 attach 的單位**；
> **window（視窗）** = session 裡的一個分頁，通常對應一個任務
> （一個 window 放日誌、一個放監控、一個放工作）；
> **pane（窗格）** = window 內分割出來的區塊，讓你**同時看到多個輸出**。
> ```
> tmux server
>  └─ session "ops"
>      ├─ window 1 "logs"  ├─ pane 1 (nginx error.log)
>      │                   └─ pane 2 (laravel.log)
>      └─ window 2 "monitor" └─ pane 1 (htop)
> ```
> **實務上**：一個維護工作開一個 session，
> 用 window 分「日誌 / 監控 / 工作」，
> 在日誌 window 內用 pane 同時看三個 log。
>
> **Q4.** **★★★ 解決「在 tmux 裡用 vim，按 Esc 有明顯延遲」的問題**。
> tmux 的 `escape-time` **預設是 500 毫秒** ——
> 按下 Esc 之後，tmux 會**等 500ms 看後面有沒有跟著其他字元**，
> 因為方向鍵、功能鍵等都是以 Esc 開頭的跳脫序列（`ESC [ A` 是上鍵）。
> 這對 tmux 判斷按鍵是必要的，但**對 vim 使用者是災難** ——
> 每次按 Esc 離開 Insert 模式都要等半秒，用起來非常卡。
> **`set -sg escape-time 10`（10ms）** 幾乎消除延遲，
> 而現代終端機送出跳脫序列的速度遠快於 10ms，不會誤判。
> **注意是 `-sg`**（server 層級的全域選項），不是 `-g`。
> 這是幾乎所有 tmux 設定檔都會有的一行。
>
> **Q5.** **★★★ 按住 `Shift` 再用滑鼠選取**。
> 開啟 `set -g mouse on` 之後，tmux 會**攔截滑鼠事件**
> 用於捲動歷史、選擇 pane、調整 pane 大小 ——
> 終端機模擬器（Windows Terminal、iTerm、GNOME Terminal）
> 因此收不到滑鼠事件，原本的「選取即複製」就失效了。
> **按住 Shift 會讓終端機繞過應用程式，直接處理滑鼠** ——
> 這是大多數終端機的通用行為。
> **其他做法**：
> ①**用 tmux 的複製模式**（`C-b [` → 選取 → Enter），
> 搭配 `copy-pipe-and-cancel "xclip -sel clip -i"` 送到系統剪貼簿；
> ②`tmux capture-pane -pS -3000 > /tmp/out.txt` 存成檔案再處理；
> ③臨時關掉：`C-b : set -g mouse off`。
>
> **Q6.** **至少四個理由**：
> ①**★★★★ 機器重開機後不會自動啟動** ——
> 停電、核心更新自動重開、雲端主機遷移，**服務就這樣消失了**，
> 而且可能過很久才有人發現；
> ②**★★★ 程式崩潰不會自動重啟** ——
> systemd 有 `Restart=always` + `RestartSec`，tmux 什麼都沒有；
> ③**★★★ 沒有日誌管理** ——
> 輸出只在 tmux 的緩衝區裡，超過 `history-limit` 就沒了，
> 也沒有 journald 的輪替、查詢、時間篩選；
> ④**★★★ 沒有資源限制** —— systemd 可以設 `MemoryMax`、`CPUQuota`，
> 記憶體洩漏時有保護；
> ⑤**★★ 沒有人知道它在哪裡跑** ——
> `systemctl status` 看不到，交接時新人完全找不到，
> 也沒有依賴管理（`After=mysql.service`）。
> **正式服務一律用 systemd**。
>
> **Q7.** **★★★★ 風險：忘記關掉同步，在多台機器上同時執行了危險指令**。
> ```
> $ sudo rm -rf /var/www/old       ← ★★★★ 四台一起刪
> $ sudo systemctl stop nginx      ← ★★★★ 服務全掛
> ```
> **三個防護**：
> ①**★★★★ 狀態列變色** —— 在 `.tmux.conf` 設定同步時整條狀態列變紅：
> ```tmux
> set -g status-style '#{?pane_synchronized,bg=colour160 fg=colour255,bg=colour234}'
> ```
> ②**★★ 用完立刻關**（再按一次 `C-a S`），養成習慣；
> ③**★★★ 只用於唯讀的查詢指令**（`uptime`、`systemctl status`、`df -h`），
> **修改類的操作用 Ansible 或逐台執行** ——
> Ansible 有 dry-run、有冪等性、有執行記錄，比同步輸入安全得多。
> 更好的替代是寫一個 `for h in web01 web02; do ssh "$h" '...'; done` 迴圈。
>
> **Q8.** **前綴鍵會被外層（本機）的 tmux 攔截**，內層收不到。
> **三個解法**：
> ①**★★ 按兩次前綴鍵** —— `C-a C-a d` 會把第二個 `C-a` 送給內層，
> 這是最快的臨時做法（需要設定 `bind C-a send-prefix`）；
> ②**★★★ 遠端用不同的前綴鍵**（最清楚）——
> 遠端的 `~/.tmux.conf` 設 `set -g prefix C-s`，
> 這樣本機用 `C-a`、遠端用 `C-s`，完全不會混淆；
> ③**★★ 加一個「休眠」切換鍵** ——
> 在本機的 `.tmux.conf` 綁 F12，按下後外層 tmux 停用自己的前綴鍵
> （`set prefix None` + `set key-table off`）並改變狀態列顏色，
> 所有按鍵直接傳給內層，再按一次恢復。
> **判斷自己是否已在 tmux 裡**：`echo "$TMUX"`（有值就是）。
>
> **Q9.** **`tmux capture-pane` 把 pane 的內容（含歷史緩衝區）輸出出來**。
> ```bash
> tmux capture-pane -pS -3000 > /tmp/output.txt   # ★ 往前 3000 行
> tmux capture-pane -t ops:1.2 -pS - > /tmp/full.txt   # ★ 全部歷史
> ```
> `-p` 輸出到 stdout，`-S -3000` 指定起始行（負數表示往回數），
> `-S -` 表示全部歷史，`-t` 指定 pane。
> **什麼時候用**：
> ①**★★★ 保存排查記錄** ——
> 把一次故障排查的完整輸出存檔，寫進 incident 報告；
> ②**分享給同事** —— 比截圖好，可以搜尋和複製；
> ③**★★ 事後分析** —— 遷移或部署的完整輸出留檔。
> **相關**：`pipe-pane -o 'cat >> /tmp/log'` 可以**即時**把輸出寫進檔案
> （在 tmux 內按 `C-b :` 輸入），適合長時間的操作。
>
> **Q10.** **★★★ 設成 `770` 並指定群組**：
> ```bash
> tmux -S /tmp/pair.sock new -s pair -d
> chmod 770 /tmp/pair.sock
> sudo chgrp devteam /tmp/pair.sock
> ```
> 這樣**只有 `devteam` 群組的成員能 attach**。
> **★★★★ 為什麼不能 777**：
> tmux socket 是**進入你的 shell 的門** ——
> 任何能存取這個 socket 的使用者，
> 只要 `tmux -S /tmp/pair.sock attach` 就能**完全接管你的 session**，
> 那等於**拿到了你的 shell 和你的所有權限**。
> 更危險的是 session 裡可能有**已認證的狀態**：
> sudo 的時效內（15 分鐘免密碼）、已登入的資料庫連線、
> 轉發的 SSH agent、還沒清掉的 token。
> **同時要注意的**：`/tmp/tmux-<uid>/` 預設是 700（正確），
> 敏感操作後用 `C-b : clear-history` 清掉緩衝區
> （裡面可能有密碼、token、查詢結果），
> 以及**不要用 root 跑長駐的 tmux**。

---

## 延伸閱讀

- [[02-screen-快速上手]] — 另一個選擇（★ 舊系統上更常見）
- [[03-Bash與Zsh效率設定]] — shell 的效率設定
- [[17-systemd服務管理]] — **★★★★ 正式服務用這個，不要用 tmux**
- [[03-終端機與Shell入門]] — 終端機基礎
- [[04-遠端編輯與VSCode-Remote]] — 遠端工作流的另一種選擇
- [[03-Vim-進階與設定]] — tmux + vim 的組合
