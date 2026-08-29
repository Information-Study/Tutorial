---
title: "screen 快速上手"
desc: "舊系統與序列埠連線的必備工具，與 tmux 的取捨"
aliases: [screen, GNU screen, 序列埠, console, minicom]
tags: [群組/軟體與開發工具, 主題/終端機, 主題/screen]
category: 常用工具
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[060-01-05-01-guide-tmux-工作階段管理]]"]
updated: 2026-08-28
---

# screen 快速上手

> [!abstract] 這篇你會學到
> - **★★★ 什麼時候該用 screen 而不是 tmux**
> - 基本操作與快捷鍵（**★★ 對照 tmux**）
> - **★★★★ 序列埠連線**（網路設備 console、UPS、伺服器 BMC）
> - `.screenrc` 的實用設定
> - **★★ 多人共用與唯讀模式**
> - **★★★ 日誌記錄**（`-L`）

## 前置知識

- [[060-01-05-01-guide-tmux-工作階段管理]] — **★★★ 概念完全相通**，先讀那篇

---

## ★★★ 什麼時候用 screen

```
★★★★ 一般情況下 tmux 比 screen 好用，但這四種情況要用 screen：

  ① ★★★★ 【舊系統上只有 screen】
     → CentOS 6/7、老舊的嵌入式 Linux、某些網路設備的 shell
     → ★★★ 客戶或機關的老機器不一定能裝新套件

  ② ★★★★ 【序列埠連線】← ★ 最重要的理由
     → 連交換器/路由器的 console 埠
     → 連 UPS、伺服器的 BMC/iLO 序列埠
     → ★★★ screen /dev/ttyUSB0 9600 一行就通
     → tmux 沒有這個功能（★ 要另外裝 minicom / picocom）

  ③ ★★ 【極簡環境】
     → 救援模式、initramfs、容器
     → ★ screen 的相依比 tmux 少

  ④ ★★ 【已經習慣的人 / 既有的作業程序】
     → 機關的 SOP 寫的是 screen

★★★ 反過來說，這些情況用 tmux：
  · 分割視窗（★★★ tmux 好用太多）
  · 複製模式與搜尋
  · 設定檔的可讀性
  · ★★ 新環境、自己能決定的
```

---

## 安裝

```bash
$ sudo apt install -y screen
$ screen -v
Screen version 4.09.01 (GNU) 20-Aug-23
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> $ sudo dnf install -y screen
> #   ★★ RHEL 8+ 需要 EPEL
> $ sudo dnf install -y epel-release && sudo dnf install -y screen
> ```

---

## ★★★ 基本操作

### 命令列

```bash
# ═══ ★★★★ 最常用的四個 ═══
$ screen -S migrate            # ★★★ 建立具名 session
$ screen -ls                   # ★★★ 列出
$ screen -r migrate            # ★★★ 接回
$ screen -X -S migrate quit    # 刪除

# ★★ 其他
$ screen                       # ★ 匿名（★ 不建議）
$ screen -dmS backup ./run.sh  # ★★★ 建立並在背景執行（★ 腳本常用）
$ screen -r                    # ★ 接回唯一的一個
$ screen -x migrate            # ★★★ 多人同時 attach（★ 不會踢掉別人）
$ screen -d -r migrate         # ★★★ 強制接回（★ 踢掉別的連線）
$ screen -R migrate            # ★★ 有就接回，沒有就建立
$ screen -wipe                 # ★★ 清掉 dead 的 session
```

```bash
$ screen -ls
There are screens on:
	12345.migrate	(2026/08/28 17:20:11)	(Detached)
	12890.deploy	(2026/08/28 16:05:33)	(Attached)
	13001.old	(2026/08/27 09:11:02)	(Dead ???)     # ★★ 用 -wipe 清掉
3 Sockets in /run/screen/S-admin.
```

```
★★★★ 狀態的意義：
  (Detached)   ★★★ 沒有人接著，程式繼續跑
  (Attached)   ★★ 有人正在使用
  (Dead ???)   ★★ 異常結束的殘骸 → screen -wipe 清掉
  (Multi, attached) ★★ 多人同時接著
```

### ★★★ 快捷鍵（前綴鍵 `Ctrl+a`）

| 按鍵（`C-a` 之後） | 作用 | **tmux 對照** |
| --- | --- | --- |
| **`d`** | **★★★★ detach** | 同 |
| **`c`** | **★★★ 新建 window** | 同 |
| **`n`** / **`p`** | 下 / 上一個 window | 同 |
| **`0`~`9`** | 跳到第 N 個 | 同 |
| **`"`** | **★★★ 列出 window 選擇** | tmux 是 `w` |
| **`A`** | **★★ 重新命名 window** | tmux 是 `,` |
| **`k`** | 關閉 window | tmux 是 `&` |
| **`S`** | **★★ 水平分割**（上下） | tmux 是 `"` |
| **`\|`** | **★★ 垂直分割**（左右） | tmux 是 `%` |
| **`Tab`** | **★★★ 切換分割區** | tmux 是方向鍵 |
| **`X`** | 關閉目前的分割區 | tmux 是 `x` |
| **`Q`** | 只留目前的分割區 | |
| **`Esc`** | **★★★ 進入複製/捲動模式** | tmux 是 `[` |
| **`]`** | 貼上 | 同 |
| **`H`** | **★★★ 開啟/關閉日誌記錄** | tmux 沒有 |
| **`C-a`** | 送出真正的 `C-a`（★ 回到行首） | 同 |
| **`?`** | 說明 | 同 |
| **`:`** | 指令模式 | 同 |

```
★★★★ 最重要的三個（和 tmux 一樣）：

  C-a d     ★★★★ detach
  C-a Esc   ★★★ 捲動歷史（★ tmux 是 C-b [）
  C-a "     ★★★ 選 window

★★★ screen 的分割是【比較弱】的：
  · 分割後新的區塊是【空的】，要按 C-a c 才有 shell
  · ★★ tmux 分割後直接就是 shell
  · ★★★ 沒有 tmux 的 zoom（全螢幕切換）
  → ★★★★ 要分割視窗的話，用 tmux
```

---

## ★★★★ 序列埠連線（screen 的殺手級功能）

```
★★★★ 這是 screen 無可取代的用途：

  · 交換器 / 路由器的 console 埠（★★★ Cisco、Juniper）
  · 伺服器的 BMC / iLO / iDRAC 序列埠
  · UPS 的管理埠
  · 嵌入式設備、開發板
  · ★★ 虛擬機的序列 console
```

```bash
# ═══ ★★★★ 基本用法 ═══
$ sudo screen /dev/ttyUSB0 9600
#                 ↑          ↑
#          ★★★ 裝置      ★★★ 鮑率（baud rate）

# ★★★ 完整參數（8N1 是最常見的設定）
$ sudo screen /dev/ttyUSB0 9600,cs8,-parenb,-cstopb,-hupcl
#   cs8       8 個資料位元
#   -parenb   無同位檢查（no parity）
#   -cstopb   1 個停止位元
#   ★★★ -hupcl  離開時不要掛斷（★ 避免重設連線的設備）

# ★★★★ 離開序列埠連線
#   C-a k     關閉 window（★ 會問 y/n）
#   C-a \     結束整個 screen
#   ★★★ C-a d 只是 detach，序列埠還被佔用著！
```

```bash
# ═══ ★★★ 找出裝置 ═══
$ ls -l /dev/ttyUSB* /dev/ttyACM* /dev/ttyS* 2>/dev/null
crw-rw---- 1 root dialout 188, 0 Aug 28 17:30 /dev/ttyUSB0

# ★★★ 插上 USB 轉序列埠線之後看核心訊息
$ sudo dmesg | tail -10
[12345.678] usb 1-2: new full-speed USB device number 5
[12345.789] usb 1-2: Product: USB-Serial Controller
[12345.890] ch341-uart converter now attached to ttyUSB0    # ★★★ 就是它
#   ★★ 常見的晶片：ch341 / pl2303 / ftdi_sio / cp210x

# ★★ 用 udev 查詳細資訊
$ udevadm info -q property -n /dev/ttyUSB0 | grep -E 'ID_VENDOR|ID_MODEL|ID_SERIAL'
ID_VENDOR=1a86
ID_MODEL=USB_Serial
ID_SERIAL_SHORT=...

# ★★★★ 權限問題（★ 最常見的坑）
$ sudo screen /dev/ttyUSB0 9600
Cannot access line '/dev/ttyUSB0'
#   ★★★ 需要 dialout 群組
$ sudo usermod -aG dialout "$USER"
$ newgrp dialout          # ★★ 或重新登入
$ groups | grep dialout
$ screen /dev/ttyUSB0 9600    # ★★★ 不用 sudo 了

# ★★★ 裝置被佔用
$ sudo screen /dev/ttyUSB0 9600
#   → 沒反應 / 顯示 [screen is terminating]
$ sudo lsof /dev/ttyUSB0
COMMAND   PID  USER  FD  TYPE DEVICE  NAME
screen  12345 admin  5u  CHR  188,0   /dev/ttyUSB0     # ★★★ 有另一個 screen
$ sudo fuser -k /dev/ttyUSB0     # ★★ 強制釋放
$ screen -wipe                    # ★★ 清掉 dead session
```

```
★★★★ 常見設備的鮑率：

  Cisco 交換器/路由器      9600     ★★★ 最常見
  Juniper                  9600
  HP/Aruba                 9600
  伺服器 BMC/iLO/iDRAC     115200   ★★★ 通常是這個
  Raspberry Pi             115200
  Arduino                  9600 / 115200
  UPS（APC）               2400 / 9600
  某些工業設備             19200 / 38400

★★★ 不確定的話：
  ① 看設備的手冊或機殼上的標示
  ② ★★ 從 9600 開始試，再試 115200
  ③ ★★★ 鮑率錯的症狀：畫面出現【隨機的亂碼】
     → 不是完全沒東西，而是「有東西但看不懂」
  ④ ★★ 完全沒東西 → 線接錯 / 設備沒開 / 要按 Enter 喚醒
```

```bash
# ═══ ★★★ 完整的 Cisco 交換器 console 連線 ═══
$ sudo usermod -aG dialout "$USER" && newgrp dialout

# ★★★ 開啟日誌記錄（★ 保存設定過程）
$ screen -L -Logfile "/var/log/console/sw01-$(date +%F-%H%M).log" \
    /dev/ttyUSB0 9600
#   -L              ★★★ 啟用記錄
#   -Logfile        ★★ 指定檔名（screen 4.06+）

# ★ 舊版 screen 用 screenlog.N
$ cd /var/log/console && sudo screen -L /dev/ttyUSB0 9600

#   ★★ 按幾次 Enter 喚醒
Switch>
Switch> enable
Switch# show version
Switch# show running-config

#   ★★★★ 離開：C-a k 然後按 y
#   ★★★ 不要用 C-a d（★ 序列埠會一直被佔用）

$ cat /var/log/console/sw01-2026-08-28-1730.log
```

> [!danger] 序列埠的三個注意事項 ★★★
> ```
> ① ★★★★ C-a d 只是 detach，序列埠【仍被佔用】
>    → 別人接不上、你自己也接不上第二次
>    → ★★★ 要用 C-a k（關 window）或 C-a \（結束 screen）
>    → ★★ 忘記的話：screen -ls 找出來 → screen -X -S <id> quit
>
> ② ★★★ -hupcl 的重要性
>    → 預設離開時會【掛斷（hangup）】序列埠
>    → ★★★★ 有些設備收到 hangup 會【重新啟動或斷開連線】
>    → 加 -hupcl 避免
>
> ③ ★★★ 序列埠 console 的內容常常是【敏感的】
>    → 交換器的 running-config（★★ 含密碼雜湊、SNMP community）
>    → BMC 的登入過程
>    → ★★★★ 日誌檔要 chmod 600 並妥善保管
> ```

```bash
# ★★ 其他序列埠工具（★ 各有優點）
$ sudo apt install -y picocom minicom
$ sudo picocom -b 9600 /dev/ttyUSB0        # ★★★ 比 screen 好用
#   離開：C-a C-x
$ sudo minicom -D /dev/ttyUSB0 -b 9600     # ★★ 有選單介面
#   離開：C-a x

# ★★★ 三者的比較
#   screen   ★★ 幾乎都有裝，但離開方式容易搞錯
#   picocom  ★★★ 輕量、離開明確、有 --imap 等實用選項
#   minicom  ★★ 功能多（★ 檔案傳輸、腳本），但設定較複雜
```

---

## ★★★ 日誌記錄

```bash
# ═══ ★★★ screen 內建的記錄功能（★ tmux 沒有）═══
$ screen -L -Logfile /var/log/screen-$(date +%F).log -S work

# ★ 在 screen 內切換
#   C-a H     ★★★ 開啟/關閉記錄

# ★★ 舊版（4.06 之前）
$ cd /var/log/screen && screen -L
#   → 產生 screenlog.0, screenlog.1...

# ★★★ 設定檔中指定
$ cat >> ~/.screenrc <<'EOF'
logfile /var/log/screen/%Y%m%d-%n.log
logfile flush 1                  # ★★ 每秒 flush（★ 避免遺失）
deflog on                        # ★★★ 預設開啟記錄
EOF
```

```
★★★ 記錄功能的實務價值：

  ① ★★★★ 交換器/路由器的設定過程存證
     → 「誰在什麼時候改了什麼」
     → ★★★ 機關的稽核要求

  ② ★★★ 長時間操作的完整輸出
     → 遷移、備份、韌體更新

  ③ ★★ 教學與交接
     → 完整的操作過程

★★★ 注意：
  · 記錄會包含【所有輸出】，含密碼提示與敏感資料
  · ★★★★ chmod 600，並有保存期限
  · ★★ 有些終端機控制碼會被記進去（★ 用 col -b 清理）
```

```bash
# ★★ 清理記錄中的控制碼
$ col -b < screenlog.0 > clean.log
$ sed -e 's/\x1b\[[0-9;]*[a-zA-Z]//g' -e 's/\r$//' screenlog.0 > clean.log

# ★★★ 檢查記錄中有沒有敏感資料
$ grep -iE 'password|secret|community|enable.*secret|key' clean.log | head
$ sudo chmod 600 /var/log/console/*.log
```

---

## .screenrc ★★

```bash
$ vim ~/.screenrc
```

```bash
# ~/.screenrc —— 實用設定

# ═══ ★★★ 基本 ═══
startup_message off              # ★★★ 不顯示開場訊息
defscrollback 50000              # ★★★ 歷史行數（★ 預設只有 100！）
vbell off                        # ★★ 關掉視覺鈴聲
bell_msg ""
autodetach on                    # ★★★ 斷線時自動 detach（★ 預設就是 on）
defutf8 on                       # ★★ UTF-8
defencoding utf8
altscreen on                     # ★★ 支援 vim/less 的替代畫面
term screen-256color             # ★★★ 256 色
nonblock on                      # ★★ 一個 window 卡住不影響其他
msgwait 2

# ═══ ★★★ 狀態列 ═══
hardstatus alwayslastline
hardstatus string '%{= kG}[%{G}%H%{g}][%= %{= kw}%?%-Lw%?%{r}(%{W}%n*%f%t%?(%u)%?%{r})%{w}%?%+Lw%?%?%= %{g}][%{Y}%l%{g}][%{B}%Y-%m-%d %{W}%c %{g}]'
#   ★★ 顯示：主機名 | window 列表 | load | 日期時間

# ═══ ★★ 捲動與複製 ═══
# ★★★ 讓滑鼠滾輪可以捲動
termcapinfo xterm* ti@:te@
defbce on

# ═══ ★★ 日誌 ═══
logfile /var/log/screen/%H-%Y%m%d-%n.log
logfile flush 1
# deflog on                      # ★ 需要時再開

# ═══ ★★ 快捷鍵 ═══
# ★★ 前綴鍵改成 C-o（★ 避免和 bash 的 C-a 行首衝突）
# escape ^Oo

# ★★ C-a a 送出真正的 C-a
bind a
bindkey ^a

# ★★ 用 F 鍵切換 window
bindkey -k k1 select 1
bindkey -k k2 select 2
bindkey -k k3 select 3

# ★★ 重新載入設定
bind r source ~/.screenrc

# ═══ ★★ 開機時的預設 window ═══
# screen -t logs 1 tail -f /var/log/nginx/error.log
# screen -t htop 2 htop
# screen -t work 3
```

```bash
$ mkdir -p /var/log/screen && chmod 700 /var/log/screen

# ★★ 套用（★ 需要新開 session，或在 screen 內 C-a : source ~/.screenrc）
$ screen -S test
```

> [!warning] `defscrollback` 一定要調 ★★★
> ```
> ★★★★ screen 的預設 scrollback 只有【100 行】！
>   → ★★ 捲一下就沒了
>   → tmux 預設是 2000（也不夠，但好一點）
>
> ★★★ 一定要設：
>   defscrollback 50000
>
> ★★ 記憶體考量：
>   50000 行 × 80 字元 × window 數
>   → ★ 一個 window 約 4MB，不算多
> ```

---

## ★★ 多人共用

```bash
# ═══ ★★★ 同一個使用者 ═══
#   A：
$ screen -S pair
#   B：
$ screen -x pair                 # ★★★ -x = 同時 attach（★ 不會踢掉 A）

#   ★★ 對照：
$ screen -r pair                 # ★ 如果已經有人接著會失敗
$ screen -d -r pair              # ★★★ 強制踢掉別人再接（★ 會中斷對方）

# ═══ ★★ 不同使用者 ═══
#   ★★★ 需要 setuid（★ 有安全考量）
$ sudo chmod u+s /usr/bin/screen
$ sudo chmod 755 /run/screen

#   A（建立者）在 screen 內：
#   C-a :multiuser on
#   C-a :acladd bob                    # ★★ 允許 bob
#   C-a :aclchg bob -w "#"             # ★★★ 唯讀（★ 只能看不能打）
#   C-a :aclchg bob +w "#"             # ★★ 給予寫入權

#   B：
$ screen -x alice/pair

# ★★ 查目前的 ACL
#   C-a :displays
```

> [!danger] `chmod u+s /usr/bin/screen` 的風險 ★★★
> ```
> ★★★★ setuid 讓 screen 以 root 權限執行
>   → 歷史上 screen 有過多個提權漏洞（★ CVE-2017-5618 等）
>   → ★★★ 現代發行版預設【不設 setuid】
>
> ★★★ 替代方案（更安全）：
>   ① ★★★ 用 tmux 的 socket 共用
>      $ tmux -S /tmp/pair.sock new -s pair
>      $ chmod 770 /tmp/pair.sock && chgrp devteam /tmp/pair.sock
>   ② ★★ 用 tmate（專為配對設計）
>   ③ ★★ 用螢幕分享（Teams / Zoom）
>   ④ ★ 用 asciinema 錄製後分享
>
> ★★★★ 機關環境建議不要開 setuid
> ```

---

## 完整實戰範例：交換器設定與存證

```bash
# ═══ ★★★【1】準備 ═══
$ sudo mkdir -p /var/log/console && sudo chmod 700 /var/log/console
$ sudo usermod -aG dialout "$USER" && newgrp dialout

# ★★★ 確認裝置
$ ls -l /dev/ttyUSB*
crw-rw---- 1 root dialout 188, 0 Aug 28 17:30 /dev/ttyUSB0
$ sudo dmesg | tail -3 | grep -i tty
[12345.890] ch341-uart converter now attached to ttyUSB0

# ★★ 確認沒有別人在用
$ sudo lsof /dev/ttyUSB0 2>/dev/null || echo "★ 沒有人佔用"
$ screen -ls

# ═══ ★★★★【2】連線並記錄 ═══
$ LOG="/var/log/console/sw-core-01-$(date +%F-%H%M%S).log"
$ screen -L -Logfile "$LOG" /dev/ttyUSB0 9600,cs8,-parenb,-cstopb,-hupcl

#   ★★ 按 Enter 幾次
Switch>

# ═══ 【3】操作 ═══
Switch> enable
Password: ********
Switch# terminal length 0                # ★★★ 不要分頁（★ 方便記錄）
Switch# show version
Switch# show running-config
Switch# show vlan brief
Switch# show interfaces status

#   ★★★ 設定前先備份
Switch# copy running-config startup-config
Switch# show archive

#   設定
Switch# configure terminal
Switch(config)# vlan 100
Switch(config-vlan)# name Servers
Switch(config-vlan)# exit
Switch(config)# interface GigabitEthernet1/0/10
Switch(config-if)# switchport mode access
Switch(config-if)# switchport access vlan 100
Switch(config-if)# no shutdown
Switch(config-if)# end

#   ★★★ 驗證
Switch# show vlan id 100
Switch# show interfaces GigabitEthernet1/0/10 switchport

#   ★★★★ 存檔
Switch# copy running-config startup-config
Building configuration...
[OK]

# ═══ ★★★★【4】離開（★ 不要用 C-a d）═══
#   C-a k  → 按 y
#   ★★★ 或 C-a \ → 按 y

# ═══ ★★★【5】處理記錄 ═══
$ ls -lh "$LOG"
-rw-r--r-- 1 admin admin 48K Aug 28 17:45 /var/log/console/sw-core-01-...log

# ★★ 清理控制碼
$ col -b < "$LOG" | sed 's/\r$//' > "${LOG%.log}-clean.log"

# ★★★★ 檢查敏感資料
$ grep -inE 'password|secret|community|snmp-server|key ' "${LOG%.log}-clean.log" | head
142:enable secret 5 $1$abc$defghijk...       # ★★★★ 密碼雜湊！
289:snmp-server community public RO           # ★★★★ community string！

# ★★★ 遮蔽後才能分享
$ sed -E 's/(secret|password) [0-9] \S+/\1 <REDACTED>/gI;
          s/(community) \S+/\1 <REDACTED>/gI' \
    "${LOG%.log}-clean.log" > "${LOG%.log}-safe.log"

# ★★★★ 權限與稽核
$ sudo chmod 600 "$LOG" "${LOG%.log}-clean.log"
$ sudo chown root:adm /var/log/console/*.log
$ echo "$(date -Is) | $(whoami) | sw-core-01 | VLAN 100 建立 + Gi1/0/10 設定 | $LOG" \
    | sudo tee -a /var/log/console/CHANGE.log

# ★★ 保存期限
$ sudo tee /etc/cron.d/console-log-cleanup >/dev/null <<'EOF'
0 3 * * 0 root find /var/log/console -name '*.log' -mtime +365 -exec shred -u {} \;
EOF
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **`Cannot access line`** ★★★ | 沒有 dialout 群組 | **`usermod -aG dialout $USER`** + 重新登入 |
| **序列埠沒反應** ★★★ | 鮑率錯／線接錯／設備沒開 | 按 Enter；試 9600 / 115200 |
| **序列埠出現亂碼** ★★★★ | **鮑率不對** | 試其他鮑率；確認 8N1 |
| **序列埠被佔用** ★★★ | 另一個 screen 沒關 | `lsof /dev/ttyUSB0`；`screen -wipe` |
| **`C-a d` 後接不回來** ★★★ | 序列埠仍被佔用 | **用 `C-a k` 或 `C-a \`** 而不是 `d` |
| **捲不到之前的輸出** ★★★★ | **預設只有 100 行** | **`defscrollback 50000`** |
| **`There is no screen to be resumed`** ★★ | session 已結束 | `screen -ls`；`screen -wipe` |
| **`Attached` 接不上** ★★ | 別人正在用 | `screen -x`（共用）或 `-d -r`（踢掉） |
| **`(Dead ???)`** ★★ | 異常結束的殘骸 | **`screen -wipe`** |
| **`C-a` 和 bash 的行首衝突** ★★★ | 前綴鍵相同 | `C-a a` 送出真正的 `C-a`；或改前綴鍵 |
| **中文亂碼** ★★ | 編碼 | `screen -U`；`defutf8 on` |
| **vim 顏色不對** ★★ | TERM | `term screen-256color` |

### 排查

```bash
# 【1】★★★ session 狀態
$ screen -ls
$ screen -wipe
$ ls -l /run/screen/S-$(whoami)/

# 【2】★★★ 序列埠
$ ls -l /dev/ttyUSB* /dev/ttyACM* /dev/ttyS*
$ sudo dmesg | grep -i -E 'tty|usb.*serial' | tail -10
$ groups | grep -o dialout
$ sudo lsof /dev/ttyUSB0
$ sudo fuser -v /dev/ttyUSB0

# 【3】★★ 序列埠參數
$ stty -F /dev/ttyUSB0 -a | head -3
speed 9600 baud; rows 0; columns 0; line = 0;
$ sudo stty -F /dev/ttyUSB0 9600 cs8 -parenb -cstopb -hupcl   # ★★ 手動設定

# 【4】★★ 測試序列埠有沒有資料
$ sudo cat /dev/ttyUSB0            # ★★ 應該會看到設備的輸出
$ echo -e "\r" | sudo tee /dev/ttyUSB0    # ★★ 送一個 Enter

# 【5】★ 設定與版本
$ screen -v
$ screen -Q echo '$STY' 2>/dev/null
$ echo "$STY"                       # ★★ 在 screen 內會有值

# 【6】★★ 日誌
$ ls -lt /var/log/screen/ /var/log/console/ 2>/dev/null | head
```

---

## 安全性注意事項

> [!danger] 四個要點 ★★★
> ```
> ① ★★★★ 序列埠 console 的記錄含高度敏感資料
>      → 交換器的 running-config（★ 密碼雜湊、SNMP community、
>        VPN 預共享金鑰、RADIUS 密鑰）
>      → BMC 的登入過程
>      → ★★★★ chmod 600、限制存放位置、有保存期限與銷毀程序
>
> ② ★★★ 不要開 screen 的 setuid
>      → 歷史上有多個提權漏洞
>      → ★★ 共用改用 tmux 的 socket 或 tmate
>
> ③ ★★★ detach 的 session 保留了已認證的狀態
>      → 交換器的 enable 模式、已登入的 BMC
>      → ★★★★ 誰能 attach = 誰能操作那台設備
>      → ★ 用完就結束，不要長期 detach 著
>
> ④ ★★ 實體的 console 埠本身就是風險
>      → ★★★ 拿到 console 線 = 可以做密碼回復
>      → ★★ 機櫃要上鎖；console server 要有認證
> ```

```bash
# ★★★ 檢查 setuid
$ ls -l /usr/bin/screen
-rwxr-xr-x 1 root root 476448 ... /usr/bin/screen     # ★★★ 沒有 s，正確
-rwsr-xr-x 1 root root 476448 ... /usr/bin/screen     # ★★★★ 有 setuid，風險

$ sudo chmod u-s /usr/bin/screen     # ★★ 移除

# ★★★★ 序列埠記錄的保護
$ sudo install -d -m 700 -o root -g adm /var/log/console
$ sudo find /var/log/console -type f -exec chmod 600 {} \;

# ★★★ 檢查記錄中的敏感資料
$ for f in /var/log/console/*.log; do
    n=$(grep -icE 'secret|password|community|pre-shared|key [0-9]' "$f" 2>/dev/null || echo 0)
    [ "$n" -gt 0 ] && printf "★★★★ %s → %s 處敏感資料\n" "$(basename "$f")" "$n"
  done

# ★★★ 遮蔽腳本
$ cat > /usr/local/bin/redact-console <<'EOF'
#!/usr/bin/env bash
# ★★ 遮蔽 console 記錄中的敏感資料
sed -E '
  s/(enable )?(secret|password) [0-9] \S+/\1\2 <REDACTED>/gI
  s/(community) \S+/\1 <REDACTED>/gI
  s/(pre-shared-key|key-string) \S+/\1 <REDACTED>/gI
  s/(username \S+ .*(secret|password) [0-9]) \S+/\1 <REDACTED>/gI
  s/\$[0-9]\$[A-Za-z0-9./]{8,}/<HASH>/g
' "$@"
EOF
$ sudo install -m755 /usr/local/bin/redact-console /usr/local/bin/redact-console
$ redact-console /var/log/console/sw01.log > /tmp/safe.log

# ★★ 稽核：誰在跑 screen
$ ps -eo user,pid,etime,cmd | grep '[S]CREEN'
$ ls -l /run/screen/*/
$ sudo lsof /dev/ttyUSB* 2>/dev/null

# ★★★ 長期 detach 的 session 清理
$ screen -ls | grep Detached | awk '{print $1}' | while read -r s; do
    echo "★★ 檢查: $s"
  done
```

---

## 速查表

### ★★★★ 必背五個

```bash
screen -S 名稱          建立
screen -ls              列出
screen -r 名稱          接回
screen -x 名稱          ★★★ 共用（不踢人）
★★★★ C-a d             detach
```

### 快捷鍵（`C-a` 之後）

```
d  ★★★★ detach     c  新 window      "  ★★★ 選 window
n / p  下/上        0-9  跳            A  改名        k  關閉
S  水平分割         |  垂直分割        Tab 切換       X  關分割
★★★ Esc  捲動模式   ]  貼上            H  ★★★ 記錄開關
:  指令模式         ?  說明            C-a  送出真 C-a
```

### ★★★★ 序列埠

```bash
sudo screen /dev/ttyUSB0 9600
sudo screen /dev/ttyUSB0 9600,cs8,-parenb,-cstopb,-hupcl
sudo usermod -aG dialout $USER          # ★★★ 權限
sudo dmesg | grep -i tty                # ★★★ 找裝置
sudo lsof /dev/ttyUSB0                  # ★★★ 誰佔用

★★★ 常見鮑率：Cisco/Juniper 9600、BMC/iLO 115200
★★★★ 離開用 C-a k 或 C-a \（不是 C-a d！）
★★★ 亂碼 = 鮑率錯；沒東西 = 線/電源/按 Enter
```

### ★★★ 記錄

```bash
screen -L -Logfile /var/log/console/sw01-$(date +%F).log /dev/ttyUSB0 9600
# C-a H 切換記錄
col -b < log | sed 's/\r$//' > clean.log       # ★★ 清控制碼
★★★★ chmod 600；檢查 secret/community 再分享
```

### ★★★ .screenrc 必設

```bash
startup_message off
★★★★ defscrollback 50000     # 預設只有 100 行！
defutf8 on
term screen-256color
autodetach on
altscreen on
```

### ★★★ screen vs tmux

```
用 screen：★★★★ 序列埠連線、舊系統只有它、極簡環境
用 tmux：  ★★★ 分割視窗、複製搜尋、新環境
★★★ 概念相通（session/window/detach），前綴鍵不同
```

---

## 練習題

> [!question]- 練習 1：基本操作 ★★
> 1. **`screen -S test`，跑一個 `while true; do date; sleep 2; done`**
> 2. **`C-a d` 離開，`screen -ls`** → 狀態是？
> 3. **`screen -r test`** → 程式還在嗎？
> 4. **開兩個終端機，都 `screen -x test`** → 兩邊同步嗎？
> 5. **一邊用 `screen -d -r test`** → 另一邊怎麼了？
> 6. **`C-a Esc` 往上捲** → 能捲多遠？設 `defscrollback` 後呢？

> [!question]- 練習 2：序列埠 ★★★★
> 1. **插上 USB 轉序列埠線，`dmesg | tail`** → 裝置是什麼？
> 2. **`ls -l /dev/ttyUSB0`** → 權限與群組？
> 3. **不加 sudo 執行 `screen /dev/ttyUSB0 9600`** → 成功嗎？
> 4. **加入 dialout 群組後再試**
> 5. **故意用錯誤的鮑率（115200 連 9600 的設備）** → 畫面長什麼樣？
> 6. **用 `C-a d` 離開後再連一次** → 連得上嗎？為什麼？

> [!question]- 練習 3：記錄 ★★★
> 1. **`screen -L -Logfile /tmp/t.log -S log`**
> 2. 執行幾個指令，`C-a d`
> 3. **`cat /tmp/t.log`** → 有控制碼嗎？
> 4. **用 `col -b` 清理**
> 5. **`C-a H` 切換記錄開關** → 中間的輸出有記進去嗎？
> 6. **寫一個檢查記錄中敏感資料的腳本**

> [!question]- 練習 4：.screenrc ★★
> 1. **建立 `~/.screenrc`，設 `defscrollback 50000`**
> 2. 加上狀態列設定
> 3. **`startup_message off`** → 有差嗎？
> 4. 設 `term screen-256color`，在 screen 內開 vim → 顏色正常嗎？
> 5. **對照 tmux 的 `.tmux.conf`，列出三個對應的設定**
> 6. **哪一個設定檔比較好讀？為什麼？**

> [!question]- 練習 5：安全 ★★★
> 1. **`ls -l /usr/bin/screen`** → 有 setuid 嗎？
> 2. 用序列埠連一台設備並記錄 `show running-config`
> 3. **`grep -iE 'secret|community' 記錄檔`** → 找到什麼？
> 4. **寫一個遮蔽腳本並套用**
> 5. **檢查記錄檔的權限** → 該是多少？
> 6. **設定一個保存期限的 cron**

---

## 小測驗

Q1. **什麼情況下該用 screen 而不是 tmux**？（至少三個）

Q2. **screen 連序列埠時，為什麼不能用 `C-a d` 離開**？該用什麼？

Q3. **序列埠出現亂碼和完全沒東西，分別代表什麼**？

Q4. **`Cannot access line '/dev/ttyUSB0'` 怎麼解決**？

Q5. **`screen -r`、`screen -x`、`screen -d -r` 的差別**？

Q6. **`defscrollback` 的預設值是多少**？為什麼一定要調？

Q7. **`-hupcl` 這個序列埠參數做什麼**？為什麼重要？

Q8. **為什麼不該對 screen 設 setuid**？共用該怎麼做？

Q9. **交換器 console 的記錄檔為什麼要特別保護**？裡面有什麼？

Q10. **screen 和 tmux 的 session 概念相同嗎**？快捷鍵有什麼對應關係？

> [!question]- 測驗答案
> **Q1.** **★★★★ 四個情況**：
> ①**序列埠連線** —— **這是最重要的理由**。
> `screen /dev/ttyUSB0 9600` 一行就能連交換器 console、
> BMC/iLO、UPS、開發板，**tmux 完全沒有這個功能**
> （要另外裝 minicom 或 picocom）；
> ②**★★★★ 舊系統上只有 screen** —— CentOS 6/7、
> 老舊的嵌入式 Linux、某些設備的內建 shell，
> 機關的老機器不一定能裝新套件；
> ③**★★ 極簡環境** —— 救援模式、initramfs、精簡的容器，
> screen 的相依比 tmux 少；
> ④**★★ 既有的作業程序** —— 機關的 SOP 寫的是 screen。
> **反過來**，分割視窗、複製模式與搜尋、設定檔可讀性都是 tmux 好得多，
> 新環境優先用 tmux。
>
> **Q2.** 因為 **`C-a d`（detach）只是離開畫面，screen session 仍在執行，
> 序列埠裝置仍被它佔用著**。
> 後果：**你自己和別人都連不上那個序列埠**，
> 而且如果忘記了，那個 session 可能佔用好幾天。
> **正確的離開方式**：
> **`C-a k`**（關閉 window，會問 y/n）或
> **`C-a \`**（結束整個 screen，會問 y/n）。
> **忘記了怎麼救**：
> ```bash
> screen -ls                       # 找出 session id
> screen -X -S 12345 quit          # ★★ 結束它
> sudo lsof /dev/ttyUSB0           # ★★★ 確認誰在佔用
> sudo fuser -k /dev/ttyUSB0       # ★★ 強制釋放
> screen -wipe                     # ★★ 清掉 dead session
> ```
>
> **Q3.** **★★★★ 出現亂碼 = 鮑率（baud rate）設錯了**。
> 序列埠有訊號進來，但你用錯誤的速率去解讀，
> 所以看到的是**隨機的、無意義的字元**。
> **解法**：試其他常見鮑率（**Cisco/Juniper 用 9600、
> BMC/iLO/iDRAC 通常是 115200**），
> 也要確認資料格式是 **8N1**（`cs8 -parenb -cstopb`）。
> **★★★ 完全沒有東西 = 訊號根本沒進來**，三個可能：
> ①**線接錯**（roll-over 線 vs 直通線、TX/RX 反接）；
> ②**設備沒開電源**或還在開機；
> ③**設備在等你先說話** —— **按幾次 Enter 喚醒它**（很常見）。
> 也可以用 `sudo cat /dev/ttyUSB0` 直接看有沒有原始資料進來。
>
> **Q4.** **★★★ 把使用者加進 `dialout` 群組**：
> ```bash
> ls -l /dev/ttyUSB0
> # crw-rw---- 1 root dialout 188, 0 ...   ★★ 群組是 dialout
> sudo usermod -aG dialout "$USER"
> newgrp dialout           # ★★ 或登出重新登入
> groups | grep dialout    # ★ 驗證
> screen /dev/ttyUSB0 9600 # ★★★ 不用 sudo 了
> ```
> **為什麼不直接用 `sudo`**：
> ①以 root 執行 screen 是不必要的風險；
> ②`sudo screen` 建立的 session 屬於 root，
> 之後要 attach 也得用 sudo，權限管理變亂；
> ③加入群組是**一次設定、長期有效**的正確做法。
> **注意 `newgrp` 或重新登入是必要的** ——
> 群組成員資格在登入時就決定了，`usermod` 之後現有的 session 不會生效。
> RHEL 系的群組名稱也是 `dialout`。
>
> **Q5.** **`screen -r 名稱`** = 接回一個 **Detached** 的 session；
> **如果已經有人 attach 著會失敗**（顯示 `There is a screen on... (Attached)`）。
> **`screen -x 名稱`** = **★★★ 同時 attach（multi-display）** ——
> 兩人看到同一個畫面、都可以打字，**不會踢掉對方**。
> 這是**配對操作、教學、交接**的正確做法。
> **`screen -d -r 名稱`** = **★★ 先強制 detach 別人，再自己接上** ——
> **會中斷對方的操作**，適合「自己的 session 因為斷線卡在 Attached 狀態」。
> **相關**：
> `screen -R` = 有就接回、沒有就建立（適合寫進 `.bashrc`）；
> `screen -wipe` = 清掉 `(Dead ???)` 的殘骸。
>
> **Q6.** **★★★★ 預設只有 100 行**（tmux 是 2000，也不夠但好一點）。
> 100 行大約是**一個終端機畫面的兩倍**，
> 執行任何有輸出的指令（`show running-config`、`docker logs`、編譯）
> **捲一下就沒了**，完全失去 scrollback 的意義。
> **一定要在 `~/.screenrc` 設**：
> ```bash
> defscrollback 50000
> ```
> **記憶體考量**：50000 行 × 每行約 80 字元 ≈ **每個 window 約 4MB**，
> 對現代機器完全不是負擔。
> **相關設定**：`altscreen on`（讓 vim/less 離開後畫面正確還原）、
> `nonblock on`（一個 window 卡住不影響其他）。
> tmux 的對應是 `set -g history-limit 50000`。
>
> **Q7.** **`-hupcl` 表示「離開時不要對序列埠送出掛斷（hangup）訊號」**。
> **預設行為（`hupcl`）是離開時掛斷** ——
> 這對數據機是合理的（掛掉電話），
> **但對網路設備是災難**：
> **★★★★ 有些交換器、路由器、BMC 收到 hangup 會重設 console 連線，
> 甚至讓你的 enable session 中斷、或觸發設備的重新啟動**。
> 你在設定到一半時離開一下，回來發現**設定沒存、session 斷了**。
> **完整的安全參數**：
> ```bash
> sudo screen /dev/ttyUSB0 9600,cs8,-parenb,-cstopb,-hupcl
> ```
> （8 資料位元、無同位、1 停止位元、不掛斷）。
> 也可以先用 `stty` 設定：`sudo stty -F /dev/ttyUSB0 9600 cs8 -parenb -cstopb -hupcl`。
>
> **Q8.** 因為 **setuid 讓 screen 以 root 權限執行**，
> 而 **screen 歷史上有過多個提權漏洞**
> （例如 CVE-2017-5618 就是利用 setuid 的 screen 建立任意檔案並提權到 root）。
> 現代發行版**預設不設 setuid** 就是這個原因。
> **共用 session 的安全替代方案**（由好到差）：
> ①**★★★ 用 tmux 的 socket 共用**：
> ```bash
> tmux -S /tmp/pair.sock new -s pair
> chmod 770 /tmp/pair.sock && sudo chgrp devteam /tmp/pair.sock
> ```
> ②**★★ tmate** —— 專為配對操作設計，有臨時的存取連結；
> ③**★★ 螢幕分享**（Teams / Zoom）—— 完全沒有系統權限的風險；
> ④**★ asciinema** —— 錄製後分享，適合教學而非即時協作。
> **檢查**：`ls -l /usr/bin/screen`，有 `s` 就是 setuid，
> 用 `sudo chmod u-s /usr/bin/screen` 移除。
>
> **Q9.** 因為 **交換器的 `show running-config` 輸出含大量機密**：
> **`enable secret 5 $1$...`**（管理員密碼的雜湊，可以離線破解）、
> **`snmp-server community public RO`**（SNMP community string，
> 拿到就能讀取甚至修改設備設定）、
> **VPN 的 pre-shared key**、**RADIUS/TACACS+ 的密鑰**、
> 完整的 VLAN 與 ACL 設計（**內部網路拓撲**）、
> 管理介面的 IP 與允許的來源網段。
> **一份 console 記錄等於整台設備的鑰匙加上網路地圖**。
> **保護措施**：
> `chmod 600`、放在 `/var/log/console`（權限 700）、
> **分享前用 sed 遮蔽**（`secret`/`community`/`key` 的值換成 `<REDACTED>`）、
> 設定保存期限並用 `shred -u` 銷毀、
> 記錄誰在什麼時候做了什麼變更（`CHANGE.log`）。
>
> **Q10.** **★★★ 概念完全相同**：
> 兩者都有 **session（可以 detach/attach 的工作階段）**、
> **window（分頁）**、以及分割區（screen 叫 region、tmux 叫 pane），
> 核心價值都是「**SSH 斷線時程式不會被 SIGHUP 殺掉**」。
> **快捷鍵對應**（screen 前綴 `C-a`、tmux 預設 `C-b`）：
> ```
> 功能          screen      tmux
> detach        C-a d       C-b d      ★★★★ 相同
> 新 window     C-a c       C-b c      相同
> 選 window     C-a "       C-b w      ★★ 不同
> 改名          C-a A       C-b ,      ★★ 不同
> 捲動/複製     C-a Esc     C-b [      ★★★ 不同
> 水平分割      C-a S       C-b "      ★★ 相反！
> 垂直分割      C-a |       C-b %      ★★ 不同
> 切換分割      C-a Tab     C-b 方向鍵  不同
> ```
> **最容易搞混的是分割** —— screen 的 `S` 是上下分割、`|` 是左右分割，
> 而 tmux 的 `"` 是上下、`%` 是左右。
> 很多人把 tmux 的前綴鍵改成 `C-a` 來統一（見 `.tmux.conf`）。

---

## 延伸閱讀

- [[060-01-05-01-guide-tmux-工作階段管理]] — **★★★ 概念相通，功能更強**
- [[020-01-17-cmd-Linux-systemd服務管理]] — 正式服務用 systemd，不要用 screen
- [[020-01-03-cmd-Linux-終端機與Shell入門]] — 終端機基礎
- [[020-01-27-cmd-Linux-硬體資訊與裝置管理]] — `/dev` 與裝置權限
- [[040-02-11-guide-機房-資訊設備盤點]] — console 記錄與變更管理
- [[060-01-05-04-guide-終端機-現代CLI工具集]] — 其他實用工具
