---
title: "scp 與 sftp 傳輸"
desc: "SSH 檔案傳輸、跳板機、受限帳號與權限保留"
aliases: [scp, sftp, sshfs, 檔案傳輸, chroot, SFTP 帳號]
tags: [群組/軟體與開發工具, 主題/檔案傳輸, 主題/ssh]
category: 常用工具
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[020-02-01-02-cmd-SSH-金鑰認證與ssh-agent]]"]
updated: 2026-08-28
---

# scp 與 sftp 傳輸

> [!abstract] 這篇你會學到
> - **★★★★ `scp` 已被官方標示為過時**，為什麼、該用什麼
> - `scp` / `sftp` / `rsync` 的取捨
> - **★★★ 透過跳板機傳檔**
> - **★★★ 權限、時間戳、符號連結的保留**
> - **★★★★ 建立受限的 SFTP 帳號**（chroot，不能登入 shell）
> - 批次傳輸與腳本化
> - **★★★ 傳輸的安全考量**

## 前置知識

- [[020-02-01-02-cmd-SSH-金鑰認證與ssh-agent]] — SSH 金鑰
- [[020-02-01-03-svc-SSH-客戶端設定檔]] — `~/.ssh/config`

---

## ★★★★ scp 已經過時

```
★★★★ OpenSSH 8.8（2021）的公告：

  「scp 協定已過時、缺乏彈性且不易修正。
    我們建議使用更現代的協定，如 sftp 或 rsync。」

★★★ 三個問題：

  ① ★★★★ 【協定本身的設計缺陷】
     → scp 依賴遠端 shell 展開萬用字元
     → ★★★★ 惡意的伺服器可以讓 scp 寫入非預期的檔案
       （CVE-2018-20685、CVE-2019-6111 等）

  ② ★★★ 【沒有進度可靠性】
     → 中斷無法續傳
     → 大檔案傳一半失敗要從頭來

  ③ ★★ 【功能有限】
     → 不能只傳有變更的
     → 不能排除檔案
     → 不能限速（★ 只有 -l）

★★★★ OpenSSH 9.0（2022）起：
  scp 【預設改用 SFTP 協定】
  → ★★★ 行為有些微差異（見下方「相容性」）
  → ★ 但指令介面維持不變

★★★ 該用什麼：
  · 傳一兩個檔案，圖方便       → ★★ scp 還是可以（★ 新版已安全）
  · ★★★★ 同步目錄、大量檔案、要續傳  → rsync
  · ★★★ 互動式瀏覽、給非技術人員   → sftp
  · ★★ 掛載成本機目錄            → sshfs（★ 慢）
```

---

## scp ★★

```bash
# ═══ ★★★ 基本用法 ═══
$ scp file.txt user@host:/path/           # ★★★ 上傳
$ scp user@host:/path/file.txt ./         # ★★★ 下載
$ scp -r dir/ user@host:/path/            # ★★ 遞迴目錄
$ scp file.txt host:                      # ★★ 傳到家目錄（★ 冒號不能省）

# ★★★ 常用選項
$ scp -P 2222 file.txt host:/path/        # ★★★ 埠（★ 大寫 P！ssh 是小寫 p）
$ scp -i ~/.ssh/id_ed25519 file host:     # 指定金鑰
$ scp -p file.txt host:/path/             # ★★★ 保留時間戳與權限
$ scp -C file.txt host:/path/             # ★★ 壓縮傳輸
$ scp -l 8192 bigfile host:/path/         # ★★ 限速（Kbit/s）
$ scp -q file.txt host:/path/             # 安靜模式
$ scp -v file.txt host:/path/             # ★★★ 除錯

# ★★ 兩台遠端主機之間（★ 預設會經過本機）
$ scp host1:/path/file host2:/path/
$ scp -3 host1:/path/file host2:/path/    # ★★ 明確經過本機（★ 新版預設）
$ scp -R host1:/path/file host2:/path/    # ★★ 直接遠端到遠端（★ 需要 agent forwarding）
```

> [!danger] `-P` 和 `-p` 千萬不要搞混 ★★★
> ```
> ★★★★ scp 的大小寫 P 意義完全不同：
>
>   scp -P 2222 file host:/path/     ★★★ 大寫 P = 【連接埠】
>   scp -p file host:/path/          ★★★ 小寫 p = 【保留時間戳與權限】
>
> ★★★ 而 ssh 剛好相反：
>   ssh -p 2222 host                 ★★ ssh 用【小寫 p】表示埠
>
> ★★★★ 這是很經典的踩雷點
>   → 用 ~/.ssh/config 設定埠就不會有這個問題
> ```

```bash
# ═══ ★★★★ 用 ~/.ssh/config 避免打一長串 ═══
$ cat >> ~/.ssh/config <<'EOF'
Host app
    HostName app.internal.example.gov.tw
    User deploy
    Port 2222
    IdentityFile ~/.ssh/id_ed25519_deploy
    IdentitiesOnly yes
EOF
$ chmod 600 ~/.ssh/config

$ scp file.txt app:/var/www/          # ★★★ 埠與金鑰都自動套用
$ ssh app
```

### ★★★ 路徑與空白的處理

```bash
# ★★★★ 檔名有空白時要【跳脫兩次】
$ scp "local file.txt" host:"/path/with space/"
#   ★★★ 錯誤！遠端的 shell 會把 space/ 當成另一個參數

$ scp "local file.txt" host:"/path/with\ space/"      # ★★ 正確
$ scp "local file.txt" 'host:"/path/with space/"'     # ★★★ 或這樣
$ scp "local file.txt" host:'/path/with\ space/'

#   ★★★★ 原因：遠端路徑會被【遠端的 shell 再解析一次】
#     → 本機的引號被 scp 吃掉
#     → 遠端看到的是沒有引號的路徑

# ★★★ 更安全的做法：用 rsync（不會有這個問題）
$ rsync -av "local file.txt" "host:/path/with space/"

# ★★ 萬用字元
$ scp host:'/var/log/nginx/*.log' ./       # ★★★ 引號讓遠端展開
$ scp host:/var/log/nginx/\*.log ./        # ★★ 或跳脫
#   ★★★ 不加引號的話本機的 shell 會先展開 → 找不到本機的檔案
```

### ★★ OpenSSH 9.0+ 的相容性

```bash
$ ssh -V
OpenSSH_9.6p1 Ubuntu-3ubuntu13.5, OpenSSL 3.0.13

# ★★★ 9.0+ 預設用 SFTP 協定，有幾個行為差異：
#   ① ★★ 遠端不再展開萬用字元的方式不同
#   ② ★★★ 某些舊伺服器可能不支援
#   ③ ★★ 目錄複製的細節略有差異

# ★★★ 強制用舊的 scp 協定（★ 相容舊伺服器）
$ scp -O file.txt host:/path/         # ★★★ 大寫 O = 用舊協定
$ scp -s file.txt host:/path/         # ★★ 明確用 SFTP 協定（預設）

# ★★ 症狀：連舊系統時出現
$ scp file.txt oldhost:/tmp/
subsystem request failed on channel 0
scp: Connection closed
#   ★★★ 舊伺服器沒有啟用 sftp subsystem → 用 -O
$ scp -O file.txt oldhost:/tmp/
```

---

## sftp ★★★

```bash
# ═══ ★★★ 互動模式 ═══
$ sftp app
Connected to app.
sftp> pwd                             # ★★ 遠端目前目錄
sftp> lpwd                            # ★★★ 本機目前目錄（l 開頭 = local）
sftp> ls -la
sftp> lls                             # ★★ 本機的 ls
sftp> cd /var/www
sftp> lcd ~/Downloads                 # ★★ 切換本機目錄
sftp> get file.txt                    # ★★★ 下載
sftp> get -r dir/                     # ★★ 遞迴下載
sftp> get -P file.txt                 # ★★ 保留權限
sftp> put local.txt                   # ★★★ 上傳
sftp> put -r localdir/                # 遞迴上傳
sftp> mkdir newdir
sftp> rm file.txt
sftp> rename old.txt new.txt
sftp> chmod 640 file.txt              # ★★ 改權限
sftp> df -h                           # ★★ 遠端磁碟空間
sftp> !ls                             # ★★★ 執行本機指令
sftp> bye

# ═══ ★★★ 批次模式（★ 腳本用）═══
$ sftp -b - app <<'EOF'
cd /var/www/uploads
lcd /tmp/staging
put report.pdf
chmod 640 report.pdf
ls -l report.pdf
bye
EOF

# ★★ 從檔案讀指令
$ cat > /tmp/sftp-batch.txt <<'EOF'
cd /var/www/uploads
put /tmp/report.pdf
bye
EOF
$ sftp -b /tmp/sftp-batch.txt app

# ★★★ 遇到錯誤就停止（★ 預設會繼續）
$ sftp -b - app <<'EOF'
cd /nonexistent
put file.txt
EOF
#   ★★★ 預設：cd 失敗後仍會嘗試 put
#   ★★ 加 - 前綴表示「這一行失敗也繼續」
#   ★★★★ 不加就是失敗即停止（sftp -b 的預設）

# ★★ 常用選項
$ sftp -P 2222 host                   # ★★★ 埠（★ 也是大寫 P）
$ sftp -i ~/.ssh/key host
$ sftp -o "StrictHostKeyChecking=yes" host
$ sftp -r host                        # ★ 遞迴（新版）
```

> [!tip] sftp 的優點 ★★★
> ```
> ★★★ 相對於 scp：
>   ① ★★★ 【互動式瀏覽】—— 可以先 ls 看看再決定傳什麼
>   ② ★★★ 【可以做檔案管理】—— mkdir / rm / rename / chmod
>   ③ ★★★★ 【協定設計較好】—— 沒有 scp 的萬用字元問題
>   ④ ★★ 【支援續傳】—— reget / reput
>   ⑤ ★★★ 【可以給非技術人員用】—— FileZilla、WinSCP 都用 SFTP
>
> ★★ 續傳：
>   sftp> reget bigfile.iso        # ★★ 續傳下載
>   sftp> reput bigfile.iso        # ★★ 續傳上傳
>
> ★★★ 但要同步大量檔案還是 rsync 好
> ```

---

## ★★★ 透過跳板機

```bash
# ═══ ★★★★ ProxyJump（推薦）═══
$ cat >> ~/.ssh/config <<'EOF'
Host bastion
    HostName bastion.example.gov.tw
    Port 2222
    User jumpuser
    IdentityFile ~/.ssh/id_ed25519_bastion
    IdentitiesOnly yes

Host app-internal
    HostName 10.10.20.31
    User deploy
    IdentityFile ~/.ssh/id_ed25519_deploy
    IdentitiesOnly yes
    ProxyJump bastion              # ★★★★ 關鍵
    ServerAliveInterval 30
    ControlMaster auto             # ★★★ 連線重用（★ 大幅加快多次傳輸）
    ControlPath ~/.ssh/cm-%r@%h:%p
    ControlPersist 10m
EOF

# ★★★ 之後 scp / sftp / rsync 都自動走跳板
$ scp file.txt app-internal:/var/www/
$ sftp app-internal
$ rsync -av dir/ app-internal:/var/www/

# ═══ ★★ 命令列指定 ═══
$ scp -o ProxyJump=bastion file.txt deploy@10.10.20.31:/var/www/
$ scp -J bastion file.txt deploy@10.10.20.31:/var/www/       # ★★ 縮寫
$ sftp -J bastion deploy@10.10.20.31

# ★ 舊版 OpenSSH（< 7.3）用 ProxyCommand
$ scp -o 'ProxyCommand ssh -W %h:%p bastion' file.txt deploy@10.10.20.31:/tmp/
```

> [!danger] 不要用 agent forwarding ★★★★
> ```
> ★★★★ 常見的錯誤做法：
>   $ ssh -A bastion
>   $ scp file.txt 10.10.20.31:/tmp/      # 在跳板機上執行
>
> ★★★★ 風險：
>   → -A 把你的 SSH agent socket 轉發到跳板機
>   → ★★★ 跳板機上的 root（或任何能讀 $SSH_AUTH_SOCK 的程序）
>     可以【冒用你的金鑰】連到任何信任你的機器
>   → ★★ 跳板機通常是多人共用、對外暴露的機器
>
> ★★★★ 正確做法：ProxyJump
>   → 認證在【你本機】完成
>   → 跳板機只是轉發加密流量，看不到也用不了你的金鑰
>
> ★★ 全域停用：
>   # ~/.ssh/config
>   Host *
>       ForwardAgent no
> ```

---

## ★★★ 權限與屬性的保留

```bash
# ═══ ★★★ scp 的保留能力有限 ═══
$ scp -p file.txt host:/path/
#   -p 保留：★★ 修改時間、存取時間、權限模式
#   ★★★★ 但【不保留】：擁有者、群組、ACL、擴充屬性、符號連結

# ★★★ 驗證
$ ls -l --time-style=full-iso file.txt
-rw-r--r-- 1 admin admin 1024 2026-08-20 10:00:00.000000000 +0800 file.txt
$ scp -p file.txt app:/tmp/
$ ssh app 'ls -l --time-style=full-iso /tmp/file.txt'
-rw-r--r-- 1 deploy deploy 1024 2026-08-20 10:00:00.000000000 +0800 /tmp/file.txt
#                    ↑
#   ★★★ 時間和權限保留了，但【擁有者變成遠端的使用者】

# ═══ ★★★★ 需要完整保留時：用 tar over ssh ═══
$ tar -czf - -C /src . | ssh app 'sudo tar -xzf - -C /dst'
#   ★★★ 保留：權限、擁有者（需要 root）、時間戳、符號連結、硬連結

# ★★★ 加上 ACL 與擴充屬性
$ sudo tar --acls --xattrs --numeric-owner -czf - -C /src . | \
    ssh app 'sudo tar --acls --xattrs --numeric-owner -xzf - -C /dst'
#   ★★ --numeric-owner：用 UID/GID 而不是名稱（★ 兩邊的使用者名稱可能不同）

# ★★ 顯示進度
$ tar -czf - -C /src . | pv | ssh app 'sudo tar -xzf - -C /dst'
$ sudo apt install -y pv

# ═══ ★★★★ 或直接用 rsync（★ 最推薦）═══
$ sudo rsync -avAXH --numeric-ids /src/ app:/dst/
#   -a  ★★★ archive（= -rlptgoD）
#   -A  ★★ ACL
#   -X  ★★ 擴充屬性
#   -H  ★★ 硬連結
#   --numeric-ids  ★★★ 用數字 UID/GID
```

```
★★★★ 三種方式的比較：

  ┌──────────┬─────────┬──────────────┬────────────┐
  │          │ scp -p  │ tar over ssh │ ★★★ rsync  │
  ├──────────┼─────────┼──────────────┼────────────┤
  │ 權限模式  │  ✓      │  ✓           │  ✓         │
  │ 時間戳    │  ✓      │  ✓           │  ✓         │
  │ ★★ 擁有者 │  ✗      │  ✓（需 root）│  ✓（需 root）│
  │ 符號連結  │  ✗（跟隨）│ ✓           │  ✓         │
  │ 硬連結    │  ✗      │  ✓           │  ✓（-H）   │
  │ ★★ ACL   │  ✗      │  ✓（--acls） │  ✓（-A）   │
  │ 擴充屬性  │  ✗      │  ✓（--xattrs）│ ✓（-X）   │
  │ ★★★★ 增量 │  ✗      │  ✗           │  ✓         │
  │ ★★★ 續傳  │  ✗      │  ✗           │  ✓         │
  │ 排除檔案  │  ✗      │  ✓（--exclude）│ ✓        │
  └──────────┴─────────┴──────────────┴────────────┘

★★★★ 結論：除了「傳一兩個檔案」，其他都用 rsync
```

---

## ★★★★ 建立受限的 SFTP 帳號

```
★★★★ 情境：
  · 廠商要上傳檔案，但【不能給 shell 存取】
  · 使用者要交換資料，但【只能看到自己的目錄】
  · 稽核要求「最小權限」
```

```bash
#!/usr/bin/env bash
# ★★★★ /usr/local/bin/create-sftp-user —— 建立受限的 SFTP 帳號
set -euo pipefail

USERNAME="${1:?用法: create-sftp-user <帳號> [根目錄]}"
CHROOT_BASE="${2:-/srv/sftp}"
CHROOT="$CHROOT_BASE/$USERNAME"

echo "═══ 建立 SFTP 帳號: $USERNAME ═══"

# ═══ ★★★【1】建立群組 ═══
sudo groupadd -f sftpusers

# ═══ ★★★【2】建立使用者（★ 不給 shell）═══
if id "$USERNAME" &>/dev/null; then
    echo "  ★★ 使用者已存在"
else
    sudo useradd -m -d "$CHROOT" -s /usr/sbin/nologin -G sftpusers "$USERNAME"
    #                                    ↑
    #   ★★★★ nologin = 無法登入 shell，但 SFTP 仍可用
    echo "  ★ 使用者已建立"
fi

# ═══ ★★★★【3】chroot 目錄的權限（★ 這是最容易錯的地方）═══
#   ★★★★ chroot 的根目錄【必須】由 root 擁有且【不可被群組/其他人寫入】
sudo mkdir -p "$CHROOT"
sudo chown root:root "$CHROOT"
sudo chmod 755 "$CHROOT"
echo "  ★★★ chroot 根目錄: root:root 755"

#   ★★★ 使用者可寫的子目錄
for d in upload download; do
    sudo mkdir -p "$CHROOT/$d"
    sudo chown "$USERNAME:sftpusers" "$CHROOT/$d"
    sudo chmod 750 "$CHROOT/$d"
done
echo "  ★ 已建立 upload/ 與 download/"

# ═══ ★★★【4】sshd 設定 ═══
if ! sudo grep -q 'Match Group sftpusers' /etc/ssh/sshd_config.d/*.conf \
       /etc/ssh/sshd_config 2>/dev/null; then
    sudo tee /etc/ssh/sshd_config.d/60-sftp.conf >/dev/null <<EOF
# ★★★★ 受限的 SFTP 帳號
Subsystem sftp internal-sftp

Match Group sftpusers
    ChrootDirectory %h
    ForceCommand internal-sftp -u 0027 -l INFO
    AllowTcpForwarding no
    AllowAgentForwarding no
    X11Forwarding no
    PermitTunnel no
    PermitTTY no
    AuthenticationMethods publickey
EOF
    echo "  ★★★ sshd 設定已建立"
fi
#   ★★★★ Subsystem 一定要用 internal-sftp（不是 /usr/lib/openssh/sftp-server）
#     → chroot 之後找不到外部的 sftp-server 執行檔

# ═══ ★★★【5】金鑰認證 ═══
sudo mkdir -p "$CHROOT/.ssh"
sudo touch "$CHROOT/.ssh/authorized_keys"
sudo chown -R "$USERNAME:$USERNAME" "$CHROOT/.ssh"
sudo chmod 700 "$CHROOT/.ssh"
sudo chmod 600 "$CHROOT/.ssh/authorized_keys"
echo "  ★★ 請把公鑰加入: $CHROOT/.ssh/authorized_keys"

#   ★★★★ 注意：chroot 之後 sshd 讀 authorized_keys 是在 chroot 【之前】
#     → 所以路徑是真實路徑，不是 chroot 內的路徑

# ═══ ★★【6】驗證與重載 ═══
sudo sshd -t && echo "  ★ sshd 設定語法正確"
sudo systemctl reload ssh
echo "  ★ sshd 已重載"

echo ""
echo "★★★ 驗證方式："
echo "  sudo -u $USERNAME whoami                 # ★ 應該失敗（nologin）"
echo "  ssh $USERNAME@localhost                  # ★★ 應該被拒絕"
echo "  sftp -i key $USERNAME@localhost          # ★★★ 應該成功"
echo "  sftp> pwd                                # ★★★ 應該顯示 /"
```

```bash
$ sudo install -m750 create-sftp-user.sh /usr/local/bin/create-sftp-user
$ sudo create-sftp-user vendor01

# ★★★ 加入公鑰
$ sudo tee -a /srv/sftp/vendor01/.ssh/authorized_keys < vendor01.pub

# ═══ ★★★★ 驗證 ═══
$ ssh vendor01@localhost
This service allows sftp connections only.       # ★★★ 正確被拒絕

$ sftp vendor01@localhost
sftp> pwd
Remote working directory: /                       # ★★★★ 看到的根是 chroot
sftp> ls
download  upload
sftp> cd /etc                                     # ★★★ 試圖跳出
Couldn't stat remote file: No such file or directory   # ★★★★ 出不去
sftp> put test.txt upload/
sftp> put test.txt /                               # ★★★ 根目錄不可寫
Couldn't write to remote file "/test.txt": Permission denied

# ★★★ 從外部確認看不到系統
$ sudo ls -la /srv/sftp/vendor01/
drwxr-xr-x 4 root     root       4096 Aug 28 18:00 .          # ★★★★ root 擁有
drwx------ 2 vendor01 vendor01   4096 Aug 28 18:00 .ssh
drwxr-x--- 2 vendor01 sftpusers  4096 Aug 28 18:00 download
drwxr-x--- 2 vendor01 sftpusers  4096 Aug 28 18:00 upload
```

> [!danger] chroot 的權限規則 ★★★★
> ```
> ★★★★ ChrootDirectory 指定的目錄【以及它的所有上層目錄】
>       必須符合：
>   ① 【由 root 擁有】
>   ② ★★★ 【不可被群組或其他人寫入】（★ 最多 755）
>
> ★★★★ 違反的話 sshd 會拒絕連線：
>   $ sudo tail -5 /var/log/auth.log
>   fatal: bad ownership or modes for chroot directory "/srv/sftp/vendor01"
>
> ★★★ 常見錯誤：
>   ✗ chown vendor01:vendor01 /srv/sftp/vendor01     ← ★★★★ 錯！
>   ✗ chmod 775 /srv/sftp/vendor01                    ← ★★★ 群組可寫，錯
>   ✓ chown root:root  + chmod 755                    ← ★★★★ 正確
>
> ★★★ 所以使用者【不能寫入 chroot 的根目錄】
>   → ★★ 一定要建立由使用者擁有的子目錄（upload/ download/）
>
> ★★★ 檢查整條路徑：
>   $ namei -l /srv/sftp/vendor01
>   f: /srv/sftp/vendor01
>   drwxr-xr-x root root /
>   drwxr-xr-x root root srv
>   drwxr-xr-x root root sftp
>   drwxr-xr-x root root vendor01        # ★★★★ 每一層都要 root 擁有
> ```

```bash
# ★★★ ForceCommand 的 umask
ForceCommand internal-sftp -u 0027
#   ★★ -u 0027 → 上傳的檔案權限是 640、目錄是 750
#   ★★★ 讓 web server 的群組能讀，但其他人不行

# ★★ 記錄 SFTP 的操作（★ 稽核）
ForceCommand internal-sftp -u 0027 -l INFO
$ sudo grep 'internal-sftp' /var/log/auth.log | tail
Aug 28 18:05:11 srv internal-sftp[12345]: session opened for local user vendor01 from [203.0.113.45]
Aug 28 18:05:20 srv internal-sftp[12345]: open "/upload/report.pdf" flags WRITE,CREATE,TRUNCATE mode 0666
Aug 28 18:05:21 srv internal-sftp[12345]: close "/upload/report.pdf" bytes read 0 written 482104

# ★★★ 更詳細
ForceCommand internal-sftp -u 0027 -l VERBOSE

# ★★ 限制頻寬（★ 需要在防火牆或 tc 層做）
$ sudo tc qdisc add dev ens18 root tbf rate 10mbit burst 32kbit latency 400ms
```

---

## 完整實戰範例：安全的檔案交換流程

```bash
#!/usr/bin/env bash
# ★★★ /usr/local/bin/secure-transfer —— 帶驗證的檔案傳輸
set -euo pipefail

SRC="${1:?用法: secure-transfer <本機檔案> <目標> [遠端路徑]}"
DEST="${2:?}"
RPATH="${3:-/tmp}"

[ -f "$SRC" ] || { echo "★★ 檔案不存在: $SRC"; exit 1; }

BASENAME=$(basename "$SRC")
SIZE=$(stat -c%s "$SRC")
echo "═══ 傳輸 $BASENAME ($(numfmt --to=iec "$SIZE")) → $DEST:$RPATH ═══"

# ═══ ★★★【1】傳輸前的檢查 ═══
echo -e "\n【1】前置檢查"
#   ★★★ 敏感內容掃描
if file "$SRC" | grep -qiE 'text|json|xml|script'; then
    if grep -qiE 'BEGIN.*PRIVATE KEY|password\s*=|api[_-]?key\s*=|AKIA[0-9A-Z]{16}' "$SRC"; then
        echo "  ★★★★ 警告：檔案中可能含有敏感資料！"
        grep -inE 'BEGIN.*PRIVATE KEY|password\s*=|api[_-]?key\s*=' "$SRC" | head -3 | sed 's/^/    /'
        read -rp "  仍要繼續嗎？[y/N] " a
        [ "$a" = y ] || exit 1
    else
        echo "  ★ 敏感資料掃描通過"
    fi
fi

#   ★★★ 遠端空間
AVAIL=$(ssh "$DEST" "df -B1 --output=avail '$RPATH' 2>/dev/null | tail -1" || echo 0)
if [ "$AVAIL" -lt "$((SIZE * 2))" ]; then
    echo "  ★★★★ 遠端空間不足（需要 $(numfmt --to=iec $((SIZE*2)))，可用 $(numfmt --to=iec "$AVAIL")）"
    exit 1
fi
echo "  ★ 遠端空間充足: $(numfmt --to=iec "$AVAIL")"

# ═══ ★★★★【2】計算來源的雜湊 ═══
echo -e "\n【2】★★★ 計算雜湊"
LOCAL_HASH=$(sha256sum "$SRC" | awk '{print $1}')
echo "  本機: $LOCAL_HASH"

# ═══ ★★★【3】傳輸 ═══
echo -e "\n【3】傳輸中..."
if command -v rsync >/dev/null; then
    #   ★★★★ rsync 較好：可續傳、有進度、保留屬性
    rsync -avP --partial --chmod=F640 "$SRC" "$DEST:$RPATH/"
else
    scp -p "$SRC" "$DEST:$RPATH/"
fi

# ═══ ★★★★【4】驗證完整性 ═══
echo -e "\n【4】★★★★ 驗證完整性"
REMOTE_HASH=$(ssh "$DEST" "sha256sum '$RPATH/$BASENAME'" | awk '{print $1}')
echo "  遠端: $REMOTE_HASH"

if [ "$LOCAL_HASH" = "$REMOTE_HASH" ]; then
    echo "  ★★★ 雜湊一致，傳輸完整"
else
    echo "  ★★★★ 雜湊不符！傳輸可能損毀"
    echo "  本機: $LOCAL_HASH"
    echo "  遠端: $REMOTE_HASH"
    exit 1
fi

# ═══ ★★【5】設定權限 ═══
echo -e "\n【5】設定權限"
ssh "$DEST" "chmod 640 '$RPATH/$BASENAME' && ls -l '$RPATH/$BASENAME'"

# ═══ ★★【6】記錄 ═══
echo "$(date -Is)|$(whoami)@$(hostname)|$BASENAME|$SIZE|$LOCAL_HASH|$DEST:$RPATH" \
    >> ~/.transfer.log
echo -e "\n★ 完成"
```

```bash
$ sudo install -m755 secure-transfer.sh /usr/local/bin/secure-transfer
$ secure-transfer /tmp/report.pdf app /var/www/uploads

═══ 傳輸 report.pdf (2.4M) → app:/var/www/uploads ═══

【1】前置檢查
  ★ 敏感資料掃描通過
  ★ 遠端空間充足: 36G

【2】★★★ 計算雜湊
  本機: a1b2c3d4e5f6...

【3】傳輸中...
report.pdf
      2,458,624 100%   12.4MB/s    0:00:00 (xfr#1, to-chk=0/1)

【4】★★★★ 驗證完整性
  遠端: a1b2c3d4e5f6...
  ★★★ 雜湊一致，傳輸完整
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **`-P` / `-p` 搞混** ★★★ | scp 的大寫 P 是埠 | **用 `~/.ssh/config`** |
| **檔名有空白傳不過去** ★★★ | 遠端 shell 再解析一次 | 雙重跳脫；**改用 rsync** |
| **`subsystem request failed`** ★★★ | 舊伺服器沒有 sftp subsystem | **`scp -O`**（用舊協定） |
| **`Permission denied` 但金鑰對** ★★★ | 遠端目錄無寫入權 | `ssh host 'ls -ld /path'` |
| **傳完擁有者變了** ★★★ | scp 不保留擁有者 | **`rsync --numeric-ids`** 或 `tar over ssh` |
| **符號連結變成實際檔案** ★★★ | scp 會跟隨連結 | **rsync `-a`** 或 `tar` |
| **chroot 連不上** ★★★★ | **權限不對** | **root:root + 755**；`namei -l` 檢查每一層 |
| **chroot 內看不到 sftp-server** ★★★★ | 用了外部的 sftp-server | **`Subsystem sftp internal-sftp`** |
| **chroot 使用者不能上傳** ★★★★ | 根目錄不可寫（設計如此） | **建子目錄**並 chown 給使用者 |
| **大檔案傳一半斷掉** ★★★ | scp 不能續傳 | **`rsync --partial`**；`sftp reget` |
| **傳輸很慢** ★★ | 沒壓縮／加密開銷 | `-C`；換 cipher；用 rsync |
| **萬用字元展開錯誤** ★★★ | 本機先展開了 | **加引號**：`host:'/path/*.log'` |

### 排查

```bash
# 【1】★★★ 先確認 SSH 能連
$ ssh -v app 'echo OK' 2>&1 | tail -20

# 【2】★★★ scp 的詳細輸出
$ scp -v file.txt app:/tmp/ 2>&1 | grep -E 'debug1:|Sending|Sink'

# 【3】★★ 遠端的權限
$ ssh app 'ls -ld /var/www/uploads; id; df -h /var/www'

# 【4】★★★★ chroot 的權限鏈
$ namei -l /srv/sftp/vendor01
$ sudo tail -20 /var/log/auth.log | grep -i chroot

# 【5】★★★ sshd 的實際設定
$ sudo sshd -T | grep -iE 'subsystem|chroot|forcecommand'
$ sudo sshd -T -C user=vendor01 | grep -iE 'chroot|forcecommand|authenticationmethods'
#   ★★★★ -C 模擬特定使用者 → 看 Match 區塊有沒有生效

# 【6】★★ 傳輸速度測試
$ ssh app 'dd if=/dev/zero bs=1M count=100' | pv > /dev/null
$ scp -v file.txt app:/tmp/ 2>&1 | grep -i 'bytes/sec'

# 【7】★★ 加密演算法（★ 影響速度）
$ ssh -Q cipher
$ scp -c aes128-gcm@openssh.com file.txt app:/tmp/    # ★★ 通常最快
$ ssh -Q cipher | while read -r c; do
    printf "%-32s " "$c"
    ssh -c "$c" app 'dd if=/dev/zero bs=1M count=50 2>/dev/null' 2>/dev/null | \
      wc -c | numfmt --to=iec
  done
```

---

## 安全性注意事項

> [!danger] 五個要點 ★★★
> ```
> ① ★★★★ 不要用 agent forwarding（-A）
>      → 用 ProxyJump
>
> ② ★★★★ 傳輸前掃描敏感內容
>      → .env、私鑰、備份中的密碼
>      → ★★★ 一旦傳出去就不可逆
>
> ③ ★★★ 傳輸後驗證雜湊
>      → sha256sum 兩邊比對
>      → ★★ 大檔案傳輸尤其重要
>
> ④ ★★★★ SFTP 帳號一定要 chroot + nologin
>      → ★★★ 不能給 shell 存取
>      → ★★ AuthenticationMethods publickey（★ 不用密碼）
>
> ⑤ ★★★ 傳輸的檔案權限
>      → ★★★★ 上傳後的 .env 若是 644 → 同機器的人都讀得到
>      → ★★ 用 --chmod=F640 或 ForceCommand -u 0027
> ```

```bash
# ★★★★ 傳輸前的敏感內容掃描
$ scan_secrets() {
    local f="$1"
    grep -lE 'BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|
              AKIA[0-9A-Z]{16}|
              sk_live_[0-9a-zA-Z]{24,}|
              gh[pousr]_[A-Za-z0-9]{36}|
              password\s*=\s*["\x27][^"\x27]{4,}|
              DB_PASSWORD=' "$f" 2>/dev/null
  }
$ scan_secrets /tmp/backup.sql && echo "★★★★ 含敏感資料，不要傳！"

# ★★★ 傳輸後驗證
$ LH=$(sha256sum file.tar.gz | awk '{print $1}')
$ scp file.tar.gz app:/tmp/
$ RH=$(ssh app 'sha256sum /tmp/file.tar.gz' | awk '{print $1}')
$ [ "$LH" = "$RH" ] && echo "★ 完整" || echo "★★★★ 損毀！"

# ★★★ 敏感檔案的傳輸：先加密
$ age -r age1abc... -o report.pdf.age report.pdf      # ★★ 用 age
$ scp report.pdf.age app:/tmp/
$ ssh app 'age -d -i ~/.age/key.txt -o /tmp/report.pdf /tmp/report.pdf.age'

# ★ 或用 gpg
$ gpg --encrypt --recipient admin@example.gov.tw report.pdf
$ scp report.pdf.gpg app:/tmp/

# ★★★★ SFTP 帳號的加固檢查
$ sudo sshd -T -C user=vendor01 | grep -iE \
    'chrootdirectory|forcecommand|allowtcpforwarding|permittty|authenticationmethods'
chrootdirectory /srv/sftp/vendor01
forcecommand internal-sftp -u 0027 -l INFO
allowtcpforwarding no                    # ★★★ 正確
permittty no                             # ★★★ 正確
authenticationmethods publickey          # ★★★ 正確

# ★★ 檢查 SFTP 帳號不能執行指令
$ sudo -u vendor01 -s 2>&1 | head -1
This account is currently not available.  # ★★★ nologin 生效

$ ssh -i vendor01.key vendor01@localhost 'id' 2>&1
This service allows sftp connections only.  # ★★★ ForceCommand 生效

# ★★★ 稽核 SFTP 活動
$ sudo grep 'internal-sftp' /var/log/auth.log | \
    awk '{print $1, $2, $3, $NF}' | tail -20
$ sudo grep -c 'session opened for local user vendor01' /var/log/auth.log

# ★★ 上傳目錄的病毒掃描（★ 廠商上傳的檔案）
$ sudo apt install -y clamav clamav-daemon
$ sudo freshclam
$ sudo clamscan -r --infected /srv/sftp/*/upload/
$ sudo tee /etc/cron.d/sftp-scan >/dev/null <<'EOF'
0 * * * * root clamscan -r --infected --move=/srv/quarantine /srv/sftp/*/upload/ 2>/dev/null | logger -t clamscan
EOF
```

---

## 速查表

### ★★★★ 選哪個

```
傳一兩個檔案          → scp（★ 新版已改用 SFTP 協定，安全）
★★★★ 同步目錄/大量/續傳 → rsync
互動式瀏覽/給非技術人員 → sftp（★ FileZilla/WinSCP）
完整保留屬性          → ★★★ rsync -aAXH 或 tar over ssh
掛載成本機目錄         → sshfs（★ 慢，不適合開發）
```

### scp

```bash
scp file host:/path/                  上傳
scp host:/path/file ./                下載
scp -r dir/ host:/path/               遞迴
★★★ scp -P 2222 ...                  大寫 P = 埠！
★★★ scp -p ...                       小寫 p = 保留時間戳權限
scp -O file host:/path/               ★★★ 用舊協定（相容舊伺服器）
scp host:'/var/log/*.log' ./          ★★★ 引號讓遠端展開
```

### sftp

```bash
sftp host
  pwd / lpwd    ls / lls    cd / lcd
  get -r dir/   put -r dir/
  reget / reput ★★ 續傳
  chmod 640 f   df -h       !cmd（本機指令）
sftp -b - host <<'EOF' ... EOF        # ★★★ 批次
```

### ★★★ 跳板機

```
# ~/.ssh/config
Host app-internal
    ProxyJump bastion          # ★★★★ 不要用 ssh -A
    ControlMaster auto         # ★★★ 連線重用
    ControlPath ~/.ssh/cm-%r@%h:%p
Host *
    ForwardAgent no            # ★★★ 安全
```

### ★★★★ 受限 SFTP 帳號

```
useradd -m -d /srv/sftp/u -s /usr/sbin/nologin -G sftpusers u
★★★★ chown root:root /srv/sftp/u && chmod 755   ← 根目錄必須 root 擁有
★★★ 使用者可寫的子目錄：chown u:sftpusers upload/

# sshd_config.d/60-sftp.conf
Subsystem sftp internal-sftp        # ★★★★ 一定要 internal
Match Group sftpusers
    ChrootDirectory %h
    ForceCommand internal-sftp -u 0027 -l INFO
    AllowTcpForwarding no
    PermitTTY no
    AuthenticationMethods publickey

# 驗證
namei -l /srv/sftp/u                     # ★★★ 每一層都要 root
sudo sshd -T -C user=u | grep chroot     # ★★★ Match 有生效嗎
```

### ★★★ 屬性保留

```
scp -p       時間戳 + 權限（★★ 不含擁有者/連結/ACL）
tar over ssh 全部（★ sudo tar --acls --xattrs --numeric-owner）
★★★★ rsync -aAXH --numeric-ids   全部 + 增量 + 續傳
```

### ★★★ 安全

```bash
# 傳前掃描
grep -lE 'BEGIN.*PRIVATE KEY|password\s*=|AKIA[0-9A-Z]{16}' file
# 傳後驗證
sha256sum file; ssh host 'sha256sum /path/file'
# 敏感檔案先加密
age -r <公鑰> -o f.age f
★★★★ 不要用 ssh -A；用 ProxyJump
```

---

## 練習題

> [!question]- 練習 1：基本傳輸 ★★
> 1. **用 `scp` 上傳和下載檔案**
> 2. **試 `scp -P` 和 `scp -p`** → 差別是什麼？
> 3. **傳一個檔名含空白的檔案** → 成功嗎？
> 4. **改用 rsync 傳同一個檔案** → 呢？
> 5. **傳一個符號連結** → 對面收到的是什麼？
> 6. **用 `rsync -a` 再試一次**

> [!question]- 練習 2：屬性保留 ★★★
> 1. **建一個目錄含：不同權限的檔案、符號連結、硬連結**
> 2. **用 `scp -rp` 傳過去，檢查對面的屬性**
> 3. **用 `tar over ssh` 傳，比較**
> 4. **用 `rsync -aAXH --numeric-ids` 傳，比較**
> 5. **擁有者保留了嗎？為什麼？**
> 6. **做一張三種方式的比較表**

> [!question]- 練習 3：受限 SFTP 帳號 ★★★★
> 1. **用腳本建立一個 SFTP 帳號**
> 2. **`ssh` 登入** → 被拒絕了嗎？
> 3. **`sftp` 登入，`pwd`** → 看到什麼？
> 4. **試著 `cd /etc`** → 出得去嗎？
> 5. **試著在根目錄 `put`** → 為什麼失敗？
> 6. **故意把 chroot 目錄 `chown` 給使用者** → 連得上嗎？看 `auth.log`

> [!question]- 練習 4：跳板機 ★★★
> 1. **設定 `ProxyJump` 並用 `scp` 傳檔**
> 2. **用 `ssh -A` + 在跳板機上 scp 做同樣的事**
> 3. **在跳板機上 `echo $SSH_AUTH_SOCK`** → 有值嗎？
> 4. **用那個 socket 連到第三台機器** → 成功嗎？
> 5. **這代表什麼風險？**
> 6. **加上 `ControlMaster` 後測傳輸速度**

> [!question]- 練習 5：安全傳輸 ★★★
> 1. **把 `secure-transfer` 腳本裝起來**
> 2. **傳一個含假密碼的檔案** → 有攔下來嗎？
> 3. **故意破壞傳輸（傳一半 Ctrl+C 再手動改檔案）** → 雜湊驗證抓到了嗎？
> 4. **用 `age` 加密後再傳**
> 5. **檢查上傳後的檔案權限**
> 6. **設定 SFTP 上傳目錄的病毒掃描 cron**

---

## 小測驗

Q1. **為什麼 OpenSSH 官方建議不要用 scp**？現在的狀況如何？

Q2. **`scp -P` 和 `scp -p` 的差別**？和 `ssh` 有什麼不一致？

Q3. **`scp -p` 保留哪些屬性？不保留哪些**？完整保留該用什麼？

Q4. **傳送檔名含空白的檔案為什麼會失敗**？

Q5. **`subsystem request failed on channel 0` 怎麼解決**？

Q6. **chroot 的根目錄權限有什麼硬性要求**？為什麼？

Q7. **chroot 之後為什麼一定要用 `internal-sftp`**？

Q8. **受限的 SFTP 帳號要設哪些選項**？（至少四個）

Q9. **為什麼不該用 `ssh -A` 而要用 `ProxyJump`**？

Q10. **傳輸大檔案後該做什麼驗證**？怎麼做？

> [!question]- 測驗答案
> **Q1.** **OpenSSH 8.8（2021）公告 scp 協定「已過時、缺乏彈性且不易修正」**。
> **三個問題**：
> ①**★★★★ 協定設計缺陷** —— scp 依賴**遠端 shell 展開萬用字元**，
> 惡意的伺服器可以回傳非預期的檔名讓 scp **寫入你沒要求的位置**
> （CVE-2018-20685、CVE-2019-6111）；
> ②**★★★ 不能續傳** —— 大檔案傳一半失敗要從頭來；
> ③**★★ 功能有限** —— 不能增量、不能排除檔案。
> **現在的狀況**：**OpenSSH 9.0（2022）起 scp 預設改用 SFTP 協定**，
> 上述的安全問題已經解決，**指令介面維持不變**。
> 所以現在用 scp 傳一兩個檔案是安全的，
> 但**同步目錄、大量檔案、需要續傳的場景還是要用 rsync**。
> 連舊伺服器時可能要加 **`-O`** 退回舊協定。
>
> **Q2.** **`scp -P 2222` 大寫 P = 指定連接埠**；
> **`scp -p` 小寫 p = 保留時間戳與權限模式**。
> **★★★ 和 ssh 剛好不一致** —— **`ssh -p 2222` 用的是小寫 p 表示埠**。
> 這是很經典的踩雷點：習慣 `ssh -p` 的人打 `scp -p 2222 file host:` 會失敗
> （2222 被當成檔名）。
> `sftp` 和 `scp` 一樣用大寫 P。
> **★★★★ 根本解法是用 `~/.ssh/config`**：
> ```
> Host app
>     HostName app.internal.example.gov.tw
>     Port 2222
>     User deploy
>     IdentityFile ~/.ssh/id_ed25519_deploy
> ```
> 之後 `scp file app:/path/`、`ssh app`、`rsync ... app:` 全部自動套用，
> 不用記大小寫，也不用每次打一長串。
>
> **Q3.** **`scp -p` 保留**：修改時間（mtime）、存取時間（atime）、
> **權限模式（mode bits）**。
> **★★★★ 不保留**：**擁有者與群組**（會變成遠端登入的使用者）、
> **符號連結**（會被跟隨並複製成實際檔案）、
> **硬連結**（變成獨立的檔案）、**ACL**、**擴充屬性（xattr）**、**稀疏檔案**。
> **完整保留有兩個做法**：
> ①**★★★★ rsync**（推薦）：
> ```bash
> sudo rsync -avAXH --numeric-ids /src/ app:/dst/
> # -a archive  -A ACL  -X xattr  -H 硬連結  --numeric-ids 用數字 UID
> ```
> ②**tar over ssh**：
> ```bash
> sudo tar --acls --xattrs --numeric-owner -czf - -C /src . | \
>   ssh app 'sudo tar --acls --xattrs --numeric-owner -xzf - -C /dst'
> ```
> **保留擁有者需要遠端有 root 權限**。
> `--numeric-ids`/`--numeric-owner` 很重要 —— 兩台機器的使用者名稱可能對應到不同的 UID。
>
> **Q4.** 因為 **遠端路徑會被「遠端的 shell」再解析一次**。
> 你在本機打的引號**被本機的 shell 吃掉了**，
> scp 把剩下的字串送到遠端，遠端的 shell 看到的是**沒有引號的路徑**，
> 於是把空白當成參數分隔符。
> ```bash
> scp "file.txt" host:"/path/with space/"    # ★★★ 失敗
> # 遠端看到：/path/with 和 space/ 兩個參數
> ```
> **兩個解法**：
> ```bash
> scp "file.txt" host:"/path/with\ space/"      # ★★ 跳脫給遠端看
> scp "file.txt" 'host:"/path/with space/"'     # ★★★ 引號留給遠端
> ```
> **★★★★ 最簡單的解法是用 rsync** ——
> 它不透過遠端 shell 解析路徑，直接寫就好：
> ```bash
> rsync -av "file.txt" "host:/path/with space/"
> ```
> 同理，萬用字元要加引號才會在遠端展開：`scp host:'/var/log/*.log' ./`。
>
> **Q5.** **★★★ 遠端伺服器沒有啟用 sftp subsystem**（通常是很舊的系統，
> 或 sshd_config 中把 `Subsystem sftp` 註解掉了）。
> **OpenSSH 9.0+ 的 scp 預設用 SFTP 協定**，所以會失敗。
> **解法**：
> ```bash
> scp -O file.txt oldhost:/tmp/       # ★★★ 大寫 O = 用舊的 scp 協定
> ```
> **另一個方向的解法**（如果你能改遠端）：
> ```bash
> # /etc/ssh/sshd_config
> Subsystem sftp /usr/lib/openssh/sftp-server
> # 或
> Subsystem sftp internal-sftp
> ```
> 然後 `sudo sshd -t && sudo systemctl reload ssh`。
> **注意 chroot 的場景一定要用 `internal-sftp`**（見 Q7）。
> 也可以完全繞過：`tar -czf - dir/ | ssh oldhost 'tar -xzf - -C /dst'`。
>
> **Q6.** **★★★★ `ChrootDirectory` 指定的目錄「以及它的所有上層目錄」
> 必須由 root 擁有，且不可被群組或其他人寫入（最多 755）**。
> **為什麼**：如果使用者能寫入 chroot 的根目錄或任何上層目錄，
> 他就能**建立符號連結或替換目錄結構來逃出 chroot**，
> 或是放置惡意的 `.ssh/authorized_keys`、共享函式庫等 ——
> **chroot 的安全保證就失效了**。
> **違反時 sshd 會直接拒絕連線**：
> ```
> fatal: bad ownership or modes for chroot directory "/srv/sftp/vendor01"
> ```
> **檢查整條路徑**：
> ```bash
> namei -l /srv/sftp/vendor01     # ★★★ 每一層都要看
> ```
> **★★★ 副作用：使用者無法寫入 chroot 的根目錄** ——
> 所以一定要**建立由使用者擁有的子目錄**（`upload/`、`download/`）
> 並 `chown user:sftpusers` + `chmod 750`。
>
> **Q7.** 因為 **chroot 之後，程序看到的根目錄就是 chroot 目錄，
> 找不到外部的 `/usr/lib/openssh/sftp-server` 執行檔**。
> ```
> Subsystem sftp /usr/lib/openssh/sftp-server   # ★★★★ chroot 後失效
> Subsystem sftp internal-sftp                   # ★★★ 正確
> ```
> **`internal-sftp` 是 sshd 內建的 SFTP 實作** ——
> 它在 sshd 的程序內執行，**不需要在 chroot 內有任何執行檔或函式庫**。
> 用外部的 sftp-server 的話，你得把執行檔、所有相依的 `.so`、
> `/dev/null`、`/dev/urandom` 全部複製進 chroot（非常麻煩且容易出錯）。
> **`ForceCommand` 也要用 `internal-sftp`**：
> ```
> ForceCommand internal-sftp -u 0027 -l INFO
> ```
> `-u 0027` 設定 umask（上傳的檔案是 640），`-l INFO` 記錄操作到 auth.log。
>
> **Q8.** **至少六個**：
> ①**`-s /usr/sbin/nologin`** —— 使用者無法登入 shell；
> ②**`ChrootDirectory %h`** —— 限制在自己的目錄內；
> ③**`ForceCommand internal-sftp -u 0027 -l INFO`** ——
> 強制只能用 SFTP、設定上傳權限、記錄操作；
> ④**`AllowTcpForwarding no`** —— **防止把 SFTP 帳號當成 SOCKS proxy 跳板**；
> ⑤**`PermitTTY no`** —— 不給終端機；
> ⑥**`AuthenticationMethods publickey`** —— 只允許金鑰認證，不用密碼。
> 另外 `AllowAgentForwarding no`、`X11Forwarding no`、`PermitTunnel no`。
> **全部放在 `Match Group sftpusers` 區塊內**，
> 並用 **`sudo sshd -T -C user=vendor01`** 驗證 Match 有生效
> （`-C` 可以模擬特定使用者查看最終設定）。
>
> **Q9.** **`ssh -A`（agent forwarding）把你本機的 SSH agent socket 轉發到跳板機**，
> 讓跳板機上的程序**可以使用你的私鑰進行認證**。
> **★★★★ 風險**：跳板機上的 root，
> 或任何能讀到 `$SSH_AUTH_SOCK` 的程序（包括被入侵後的惡意程式），
> **可以冒用你的身分連到任何信任你金鑰的機器**，而你不會知道。
> **跳板機通常是多人共用、對外暴露的機器 —— 正是最不該信任的地方**。
> **`ProxyJump`（`-J`）則是認證完全在你本機完成** ——
> 跳板機只負責**轉發加密的 TCP 流量**，它**看不到也用不了你的金鑰**。
> ```
> # ~/.ssh/config
> Host app-internal
>     ProxyJump bastion
> Host *
>     ForwardAgent no        # ★★★ 全域停用
> ```
> 設定好之後 `scp`、`sftp`、`rsync` 全部自動走跳板。
>
> **Q10.** **★★★★ 比對兩邊的 SHA256 雜湊**：
> ```bash
> LH=$(sha256sum file.tar.gz | awk '{print $1}')
> scp file.tar.gz app:/tmp/
> RH=$(ssh app 'sha256sum /tmp/file.tar.gz' | awk '{print $1}')
> [ "$LH" = "$RH" ] && echo "★ 完整" || echo "★★★★ 損毀！"
> ```
> **為什麼重要**：
> ①網路傳輸可能因為**中斷、磁碟寫入錯誤、記憶體問題**而損毀，
> 而 **scp 傳一半中斷不會告訴你檔案不完整**；
> ②**備份檔、資料庫 dump、韌體映像**損毀的後果很嚴重
> （還原時才發現就太晚了）；
> ③這也順便**驗證了沒有被中間人竄改**。
> **rsync 的優勢**：它**內建以區塊為單位的 checksum 驗證**，
> 加 `-c` 還會用完整的 checksum 比對而不是只看大小和時間戳。
> 大檔案建議一律用 `rsync -avP --partial`（可續傳 + 有進度）。

---

## 延伸閱讀

- [[060-01-06-02-guide-rsync-同步與備份]] — **★★★★ 大部分情況該用這個**
- [[020-02-01-02-cmd-SSH-金鑰認證與ssh-agent]] — 金鑰認證
- [[020-02-01-03-svc-SSH-客戶端設定檔]] — `ProxyJump` 與 `ControlMaster`
- [[020-02-01-07-svc-SSH-安全強化]] — sshd 的加固
- [[060-01-06-03-guide-傳輸-備份策略與還原演練]] — 備份的完整流程
- [[060-01-02-04-guide-編輯器-遠端編輯與VSCode-Remote]] — sshfs 與遠端編輯
