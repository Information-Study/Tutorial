---
title: "Git 遠端協作"
desc: "fetch 與 pull 的差別、多 remote 管理、SSH 金鑰與 PR 流程"
aliases: [git remote, git fetch, git pull, git push, Pull Request, upstream]
tags: [群組/軟體與開發工具, 工具/git, 主題/版本控制]
category: 常用工具
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[03-Git-分支與合併]]", "[[02-SSH-金鑰認證與ssh-agent]]"]
updated: 2026-08-28
---

# Git 遠端協作

> [!abstract] 這篇你會學到
> - 理解 **`fetch` 與 `pull` 的差別**（以及為什麼建議先 fetch）
> - 設定 **SSH 金鑰**連線 GitHub／GitLab（含多帳號）
> - 設定與切換**多個 remote**（origin / upstream / 自架伺服器）
> - 走完一次完整的 **Pull Request 協作流程**
> - 理解**追蹤分支（upstream）**與 `git push -u` 的意義
> - **在伺服器上安全地 clone 私有 repo**（部署金鑰）

## 前置知識

- [[03-Git-分支與合併]] — 分支與合併
- [[02-SSH-金鑰認證與ssh-agent]] — SSH 金鑰

---

## 觀念說明

### 遠端（remote）是什麼

> [!note] remote 只是「一個網址的別名」
> ```bash
> $ git remote -v
> origin  git@github.com:org/project.git (fetch)
> origin  git@github.com:org/project.git (push)
> ```
> **`origin` 不是特殊關鍵字**，只是 `git clone` 時的預設命名。
> 你可以叫它任何名字，也可以同時有很多個。

### 本地分支 vs 遠端追蹤分支

```mermaid
graph LR
    subgraph Local["你的電腦"]
        A["main<br/>（本地分支）"]
        B["origin/main<br/>（遠端追蹤分支）"]
    end
    subgraph Remote["GitHub"]
        C["main"]
    end
    C -->|"git fetch"| B
    B -->|"git merge"| A
    A -->|"git push"| C
```

| 名稱 | 是什麼 | 你能直接改它嗎 |
| --- | --- | --- |
| **`main`** | **本地分支** | ✅ 可以 commit |
| **`origin/main`** | **遠端追蹤分支**（你上次 fetch 時遠端的樣子） | ❌ **唯讀，由 fetch 更新** |
| 遠端的 `main` | GitHub 上真正的分支 | 透過 push 更新 |

> [!danger] `origin/main` 不是即時的
> **它只反映「你上次 `git fetch` 時遠端的狀態」。**
>
> ```bash
> $ git log origin/main -1        # ← 這可能是三天前的資訊
> $ git fetch                     # ← 更新它
> $ git log origin/main -1        # ← 現在才是最新的
> ```
>
> **這就是為什麼「明明 push 了但別人看不到」或
> 「明明遠端有更新但我看不到」的原因** ——
> 你沒有 fetch。

### fetch vs pull

```mermaid
graph LR
    A["git fetch"] -->|"更新 origin/main"| B["你可以先看看<br/>遠端改了什麼"]
    B --> C["git merge origin/main<br/>或 git rebase origin/main"]
    D["git pull"] -->|"fetch + merge<br/>一次做完"| E["直接改變你的工作區"]
```

| | **`git fetch`** | **`git pull`** |
| --- | --- | --- |
| 做什麼 | **只下載，更新 `origin/*`** | **fetch + merge（或 rebase）** |
| 動到工作區嗎 | **❌ 完全不動** | ✅ 會改變你的檔案 |
| 安全性 | **絕對安全** | 可能產生衝突或非預期的合併 |
| 建議 | **先 fetch 看一下** | 確定沒問題再 pull |

> [!tip] 建議的安全流程
> ```bash
> # ① 先看看遠端有什麼變化（不動工作區）
> $ git fetch
>
> # ② 看差異
> $ git log HEAD..origin/main --oneline    # 遠端有、我沒有的
> $ git log origin/main..HEAD --oneline    # 我有、遠端沒有的
> $ git diff HEAD origin/main              # 內容差異
>
> # ③ 確認沒問題再合併
> $ git merge origin/main
> # 或
> $ git rebase origin/main
> ```
>
> **`git pull` 適合「你確定遠端只有別人正常的提交」時使用。**

```bash
# ===== pull 的行為設定 =====
$ git config --global pull.rebase true    # ★ 建議：用 rebase 而非 merge
$ git config --global pull.ff only        # 或：只允許 fast-forward，否則報錯

# ===== 常用的 fetch 選項 =====
$ git fetch                        # 預設 remote（origin）
$ git fetch --all                  # 所有 remote
$ git fetch --prune                # ★ 清除遠端已刪除的分支參照
$ git fetch --tags                 # 同時取得標籤
$ git fetch origin main            # 只取特定分支

# 設成預設每次 fetch 都 prune
$ git config --global fetch.prune true
```

---

## 設定 SSH 連線

> [!tip] 為什麼用 SSH 而不是 HTTPS
> | | HTTPS | **SSH** |
> | --- | --- | --- |
> | 認證 | 帳號 + **Personal Access Token** | **金鑰對** |
> | 每次 push 要輸入嗎 | 要（除非用 credential helper） | **不用** |
> | Token 過期 | 會（要重新產生） | 金鑰不會過期 |
> | 防火牆友善 | ✅（443 埠） | ⚠️（22 埠可能被擋） |
> | **伺服器自動化** | 要存 Token（有風險） | **用部署金鑰，可設唯讀** |
>
> **開發用 SSH，防火牆嚴格的環境用 HTTPS + Token。**

```bash
# ===== 【1】產生金鑰（★ 用 ed25519，不要用 RSA）=====
$ ssh-keygen -t ed25519 -C "wang@example.gov.tw" -f ~/.ssh/id_ed25519_github
Generating public/private ed25519 key pair.
Enter passphrase (empty for no passphrase):    # ★ 建議設定 passphrase

# ===== 【2】加入 ssh-agent（避免每次輸入 passphrase）=====
$ eval "$(ssh-agent -s)"
$ ssh-add ~/.ssh/id_ed25519_github

# ===== 【3】複製公鑰 =====
$ cat ~/.ssh/id_ed25519_github.pub
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... wang@example.gov.tw

# ===== 【4】貼到平台 =====
# GitHub: Settings → SSH and GPG keys → New SSH key
# GitLab: Preferences → SSH Keys

# ===== 【5】測試 =====
$ ssh -T git@github.com
Hi username! You've successfully authenticated, but GitHub does not provide shell access.

$ ssh -T git@gitlab.com
Welcome to GitLab, @username!
```

### 多帳號設定

> [!warning] 常見情境：同一台電腦要用公務與私人兩個 GitHub 帳號
> **問題**：SSH 預設只會用 `~/.ssh/id_ed25519`，
> 無法區分要用哪把金鑰。

```
# ~/.ssh/config
# ===== 公務帳號 =====
Host github-work
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_work
    IdentitiesOnly yes

# ===== 私人帳號 =====
Host github-personal
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_personal
    IdentitiesOnly yes

# ===== 自架 GitLab（非標準埠）=====
Host gitlab-internal
    HostName gitlab.example.gov.tw
    User git
    Port 2222
    IdentityFile ~/.ssh/id_ed25519_internal
    IdentitiesOnly yes
```

```bash
$ chmod 600 ~/.ssh/config

# ===== 使用：把 github.com 換成你定義的 Host =====
$ git clone git@github-work:company/project.git
$ git clone git@github-personal:myname/hobby.git

# ===== 既有 repo 改 URL =====
$ git remote set-url origin git@github-work:company/project.git

# ===== 測試 =====
$ ssh -T git@github-work
$ ssh -T git@github-personal
```

> [!tip] 搭配 `includeIf` 自動切換身分
> 見 [[01-Git-觀念與初次設定]]：
> ```ini
> # ~/.gitconfig
> [includeIf "gitdir:~/work/"]
>     path = ~/.gitconfig-work
> ```
> ```ini
> # ~/.gitconfig-work
> [user]
>     email = wang@company.com
> [core]
>     sshCommand = "ssh -i ~/.ssh/id_ed25519_work -o IdentitiesOnly=yes"
> ```
> **這樣連 remote URL 都不用改**，
> 只要 repo 放在 `~/work/` 底下就會自動用對的金鑰與信箱。

---

## 管理 remote

```bash
# ===== 查看 =====
$ git remote -v
$ git remote show origin           # ★ 詳細資訊（含分支對應關係）

# ===== 新增 =====
$ git remote add upstream https://github.com/original/project.git
$ git remote add backup git@gitlab.example.gov.tw:mirror/project.git

# ===== 修改 =====
$ git remote set-url origin git@github.com:org/project.git
$ git remote rename origin github
$ git remote remove backup

# ===== 一次推到多個 remote（備援用）=====
$ git remote set-url --add --push origin git@github.com:org/project.git
$ git remote set-url --add --push origin git@gitlab.internal:mirror/project.git
$ git push origin main             # ★ 同時推到兩個地方
```

> [!tip] 典型的 remote 配置
> ```
> 【一般專案】
>   origin      → 你的主要遠端
>
> 【Fork 別人的專案】
>   origin      → 你 fork 出來的 repo（你有寫入權）
>   upstream    → 原始專案（唯讀，用來同步更新）
>
> 【機關內部 + 備援】
>   origin      → 內部 GitLab
>   backup      → 異地的鏡像
> ```

---

## push 與追蹤分支

```bash
# ===== 第一次推送新分支 =====
$ git push -u origin feature/api
# -u = --set-upstream，建立「本地分支 ↔ 遠端分支」的對應關係

# 之後就可以直接：
$ git push
$ git pull

# ===== 自動設定 upstream（★ 建議設定）=====
$ git config --global push.autoSetupRemote true
# 之後第一次 push 也不用加 -u
```

```bash
# ===== 查看追蹤關係 =====
$ git branch -vv
* main            a1b2c3d [origin/main] 最新提交訊息
  feature/api     d4e5f6g [origin/feature/api: ahead 2] 提交訊息
  local-only      g7h8i9j 提交訊息                    ← 沒有 [] = 沒有上游

# ===== 手動設定／變更上游 =====
$ git branch --set-upstream-to=origin/main main
$ git branch --unset-upstream

# ===== 推送到不同名稱的遠端分支 =====
$ git push origin 本地分支名:遠端分支名

# ===== 刪除遠端分支 =====
$ git push origin --delete feature/api
$ git push origin :feature/api          # 舊語法（推送「空的」到該分支）
```

> [!tip] `ahead` / `behind` 的意義
> ```bash
> $ git status -sb
> ## main...origin/main [ahead 2, behind 3]
>                        │         └─ 遠端有 3 個提交我沒有 → 要 pull
>                        └─ 我有 2 個提交遠端沒有 → 要 push
> ```
>
> **同時 ahead 又 behind = 分岔了**，
> 直接 push 會被拒絕，要先整合（merge 或 rebase）。

---

## Pull Request 協作流程

```mermaid
graph LR
    A["① fork / clone"] --> B["② 建立分支"]
    B --> C["③ 開發並提交"]
    C --> D["④ 同步 upstream"]
    D --> E["⑤ push 到自己的 remote"]
    E --> F["⑥ 建立 PR"]
    F --> G["⑦ 審查與修改"]
    G --> H["⑧ 合併"]
    H --> I["⑨ 清理分支"]
```

### 完整流程（Fork 模式）

```bash
# ========== 【1】Fork（在 GitHub 網頁上點 Fork）==========

# ========== 【2】Clone 自己的 fork ==========
$ git clone git@github.com:myname/project.git
$ cd project

# ========== 【3】加入 upstream（原始專案）==========
$ git remote add upstream https://github.com/original/project.git
$ git remote -v
origin    git@github.com:myname/project.git (fetch/push)
upstream  https://github.com/original/project.git (fetch/push)

# ★ 防止誤推到 upstream
$ git remote set-url --push upstream DISABLED

# ========== 【4】建立功能分支 ==========
$ git fetch upstream
$ git switch -c feature/1234-新功能 upstream/main

# ========== 【5】開發 ==========
$ vim ...
$ git add -p
$ git commit -m "feat: 新增 XXX 功能"

# ========== 【6】★ 同步 upstream 的最新變更 ==========
$ git fetch upstream
$ git rebase upstream/main
# 有衝突 → 解決 → git add → git rebase --continue

# ========== 【7】整理提交歷史 ==========
$ git log --oneline upstream/main..HEAD
$ git rebase -i upstream/main            # 把 wip 之類的 fixup 掉

# ========== 【8】推送到自己的 fork ==========
$ git push -u origin feature/1234-新功能
# rebase 之後要強制推送（★ 用 with-lease）
$ git push --force-with-lease

# ========== 【9】在 GitHub 上建立 PR ==========
# 或用 gh CLI：
$ gh pr create --base main --head feature/1234-新功能 \
    --title "feat: 新增 XXX 功能" \
    --body "## 變更說明
...

## 測試方式
...

Closes #1234"

# ========== 【10】依審查意見修改 ==========
$ vim ...
$ git commit --fixup <要修正的提交>
$ git rebase -i --autosquash upstream/main
$ git push --force-with-lease

# ========== 【11】合併後清理 ==========
$ git switch main
$ git fetch upstream
$ git reset --hard upstream/main         # 本地 main 對齊 upstream
$ git push origin main                   # 更新自己的 fork
$ git branch -d feature/1234-新功能
$ git push origin --delete feature/1234-新功能
```

### 團隊內部模式（不 fork，直接推分支）

```bash
# ===== 大多數機關內部專案用這種 =====
$ git clone git@gitlab.example.gov.tw:team/project.git
$ cd project

$ git switch -c feature/1234-新功能
$ ...開發...
$ git push -u origin feature/1234-新功能

# 在 GitLab 上建立 Merge Request
$ glab mr create --source-branch feature/1234-新功能 \
    --target-branch main --title "feat: 新增 XXX" --fill
```

### gh CLI 常用指令

```bash
# ===== 安裝 =====
$ sudo mkdir -p -m 755 /etc/apt/keyrings
$ wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg | \
    sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null
$ sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
$ echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | \
    sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
$ sudo apt update && sudo apt install -y gh

# ===== 登入 =====
$ gh auth login
$ gh auth setup-git          # ★ 讓 git 用 gh 的認證

# ===== PR 操作 =====
$ gh pr create --fill                 # 用最後的 commit 訊息當標題與內文
$ gh pr list
$ gh pr view 123
$ gh pr checkout 123                  # ★ 把別人的 PR 抓下來測試
$ gh pr diff 123
$ gh pr review 123 --approve
$ gh pr review 123 --request-changes -b "請補上測試"
$ gh pr merge 123 --squash --delete-branch

# ===== Issue =====
$ gh issue list
$ gh issue create --title "..." --body "..."

# ===== Repo =====
$ gh repo clone org/project
$ gh repo view --web
```

---

## 完整實戰範例

### 在伺服器上部署私有 repo

> [!danger] 不要在伺服器上放你的個人 SSH 金鑰
> **如果伺服器被入侵，攻擊者就取得了你所有 repo 的寫入權。**

```bash
# ========== 方式一：Deploy Key（★ 推薦，可設唯讀）==========
# 【1】在伺服器上產生「專用於這個 repo」的金鑰
$ sudo -u www-data ssh-keygen -t ed25519 -N "" \
    -f /var/www/.ssh/deploy_myproject \
    -C "deploy@web01-myproject"

$ sudo cat /var/www/.ssh/deploy_myproject.pub

# 【2】在 GitHub 上加入 Deploy Key
#    Repo → Settings → Deploy keys → Add deploy key
#    ★★ 【不要】勾選 "Allow write access"（除非真的需要）

# 【3】設定 SSH config
$ sudo -u www-data tee /var/www/.ssh/config > /dev/null <<'EOF'
Host github-myproject
    HostName github.com
    User git
    IdentityFile /var/www/.ssh/deploy_myproject
    IdentitiesOnly yes
    StrictHostKeyChecking yes
EOF
$ sudo chmod 600 /var/www/.ssh/config /var/www/.ssh/deploy_myproject
$ sudo chown -R www-data:www-data /var/www/.ssh

# 【4】先接受 host key（避免第一次連線卡住）
$ sudo -u www-data ssh-keyscan github.com >> /var/www/.ssh/known_hosts

# 【5】Clone
$ sudo -u www-data git clone git@github-myproject:org/myproject.git /var/www/myproject

# 【6】測試更新
$ cd /var/www/myproject
$ sudo -u www-data git pull
```

```bash
# ========== 方式二：HTTPS + Token（防火牆只開 443 時）==========
# 【1】在 GitHub 產生 Fine-grained Personal Access Token
#     Settings → Developer settings → Personal access tokens
#     ★ 只給【這一個 repo】的【Contents: Read-only】權限
#     ★ 設定到期日

# 【2】用 credential store（★ 檔案權限要設好）
$ sudo -u www-data git config --global credential.helper \
    'store --file=/var/www/.git-credentials'
$ echo "https://x-access-token:ghp_xxxxx@github.com" | \
    sudo -u www-data tee /var/www/.git-credentials
$ sudo chmod 600 /var/www/.git-credentials

# 【3】Clone
$ sudo -u www-data git clone https://github.com/org/myproject.git /var/www/myproject
```

> [!warning] Token 存在檔案裡是有風險的
> **`--file` 的 credential store 是明文的。**
>
> **更好的做法**：
> - 用 **Deploy Key**（金鑰有 passphrase 保護，且可限唯讀）
> - 用 **CI/CD 的 secrets**（不落地到伺服器）
> - 用**機密管理系統**（Vault）動態取得
>
> 見 [[03-機密管理與金鑰保護]]。

### 從 GitHub 專案部署到伺服器

```bash
#!/usr/bin/env bash
# /usr/local/sbin/deploy-from-git.sh
# 從 GitHub 拉取指定版本並部署
set -euo pipefail

REPO_DIR="/var/www/myproject"
BRANCH="${1:-main}"
DEPLOY_USER="www-data"

echo "═══ 部署開始 $(date '+%F %T') ═══"

cd "$REPO_DIR"

# 【1】記錄目前版本（用於回退）
BEFORE=$(sudo -u "$DEPLOY_USER" git rev-parse HEAD)
echo "目前版本：$BEFORE"

# 【2】確認工作區乾淨（正式環境不該有本機修改）
if ! sudo -u "$DEPLOY_USER" git diff --quiet; then
  echo "❌ 工作區有未提交的變更，請先處理："
  sudo -u "$DEPLOY_USER" git status -s
  exit 1
fi

# 【3】拉取
sudo -u "$DEPLOY_USER" git fetch origin --tags
sudo -u "$DEPLOY_USER" git checkout "$BRANCH"
sudo -u "$DEPLOY_USER" git reset --hard "origin/$BRANCH"

AFTER=$(sudo -u "$DEPLOY_USER" git rev-parse HEAD)
echo "新版本：  $AFTER"

if [ "$BEFORE" = "$AFTER" ]; then
  echo "沒有新的變更，結束。"
  exit 0
fi

# 【4】顯示這次部署包含哪些變更
echo -e "\n【本次變更】"
sudo -u "$DEPLOY_USER" git log --oneline "$BEFORE..$AFTER"

# 【5】依專案類型執行後續動作（見 85 章）
# composer install --no-dev --optimize-autoloader
# npm ci && npm run build
# php artisan migrate --force
# php artisan config:cache

echo -e "\n═══ 部署完成 ═══"
echo "回退指令：sudo -u $DEPLOY_USER git -C $REPO_DIR reset --hard $BEFORE"
```

> [!tip] 完整的部署流程見 [[00-部署實戰-索引]]
> 這裡只示範 Git 的部分，
> 實際的 LXMP 專案部署（含 Composer、npm、migration、
> 權限設定、零停機切換）在 85 章有完整說明。

### 同步 fork 的 upstream

```bash
#!/usr/bin/env bash
# 把 fork 的 main 對齊 upstream
set -euo pipefail

git fetch upstream
git switch main

# 方式 A：完全對齊（★ 會丟棄本地 main 的修改）
git reset --hard upstream/main
git push --force-with-lease origin main

# 方式 B：保守合併（本地 main 有自己的提交時）
# git merge upstream/main
# git push origin main
```

```bash
# ===== 用 gh CLI 一行搞定 =====
$ gh repo sync myname/project --source original/project
```

---

## 常見錯誤與排錯

| 現象／錯誤 | 原因 | 解法 |
| --- | --- | --- |
| **`Permission denied (publickey)`** | SSH 金鑰沒設定或沒加入 agent | `ssh -T git@github.com` 測試；`ssh-add -l` 確認；檢查 `~/.ssh/config` |
| **`Updates were rejected`** | 遠端有你沒有的提交（behind） | `git fetch` → `git rebase origin/main` → 再 push |
| push 被拒絕（rebase 後） | 歷史被改寫 | **個人分支**用 `--force-with-lease`；共用分支不要 rebase |
| **明明 push 了但別人看不到** | 對方沒 `git fetch` | 對方執行 `git fetch` 或 `git pull` |
| **`origin/main` 是舊的** | `origin/*` 只在 fetch 時更新 | `git fetch` |
| `git pull` 產生一堆 merge commit | 預設用 merge | `git config --global pull.rebase true` |
| **同時 ahead 又 behind** | 本地與遠端分岔了 | 先 `git rebase origin/main` 或 `git merge origin/main` |
| 遠端刪了分支但本地還看得到 | 沒有 prune | `git fetch --prune`；設 `fetch.prune true` |
| **多帳號時用錯金鑰** | SSH 預設只用一把 | `~/.ssh/config` 定義多個 Host + `IdentitiesOnly yes` |
| **推錯 remote（推到 upstream）** | 沒有防護 | `git remote set-url --push upstream DISABLED` |
| 伺服器上 clone 卡住 | 沒有接受 host key | `ssh-keyscan github.com >> ~/.ssh/known_hosts` |
| **伺服器被入侵，所有 repo 都被改** | 放了個人 SSH 金鑰 | **改用唯讀的 Deploy Key** |
| Token 過期導致部署失敗 | PAT 有到期日 | 設定到期提醒；或改用 Deploy Key（不過期） |
| `git push` 每次都要輸入密碼 | 用 HTTPS 且沒設 credential helper | 改用 SSH，或 `gh auth setup-git` |
| **部署時工作區有本機修改被覆蓋** | 直接 `git pull` | 部署腳本先 `git diff --quiet` 檢查 |

---

## 安全性注意事項

> [!danger] 伺服器上的 Git 憑證是高價值目標
> **攻擊者入侵伺服器後，第一件事之一就是找 Git 憑證。**
>
> **他能取得的**：
> ```bash
> ~/.ssh/id_*                    # SSH 私鑰
> ~/.git-credentials             # 【明文的 HTTPS Token】
> ~/.config/gh/hosts.yml         # gh CLI 的 Token
> .git/config                    # 【可能含嵌入 URL 的 Token】
> ```
>
> **防護**：
> ```
> ① 【用 Deploy Key，且設為唯讀】
> ② 【一個 repo 一把金鑰】（不要共用）
> ③ 金鑰檔權限 600，擁有者是服務帳號
> ④ 【不要在伺服器上放個人的 SSH 金鑰】
> ⑤ Token 用 fine-grained 且【限定單一 repo + 唯讀】
> ⑥ 設定到期日並追蹤
> ⑦ 【伺服器被入侵時，立刻撤銷該金鑰/Token】
> ```

> [!warning] `.git/config` 中的 URL 可能含有 Token
> ```bash
> # ❌ 危險：Token 直接嵌在 URL 裡
> $ git clone https://ghp_xxxxx@github.com/org/repo.git
> $ cat .git/config
> [remote "origin"]
>     url = https://ghp_xxxxx@github.com/org/repo.git    ← 明文！
>
> # 這個 .git/config 可能會：
> #   · 被備份出去
> #   · 被 rsync 到其他地方
> #   · 【被打包進 Docker 映像】
> #   · 出現在容器的層裡（即使後來刪掉）
> ```
>
> **檢查**：
> ```bash
> $ grep -r 'ghp_\|glpat-\|@github.com\|@gitlab' \
>     --include='config' /var/www/*/.git/ 2>/dev/null
> ```

> [!danger] 不要把 `.git` 目錄部署到 Web 根目錄
> ```bash
> # ❌ 常見的錯誤部署方式
> $ git clone repo.git /var/www/html
> # → https://網站/.git/config 可以被下載
> # → 攻擊者還原【全部原始碼與歷史】（可能含曾經 commit 的密碼）
> ```
>
> **檢查**：
> ```bash
> $ curl -sI https://你的網站/.git/config | head -1
> HTTP/2 200          ← ⚠⚠ 有問題！
> ```
>
> **三種正確做法**：
> ```
> ① 【web root 指向子目錄】（如 Laravel 的 public/）
>    → .git 在上一層，Web 碰不到
> ② 【Nginx/Apache 明確拒絕】
>    location ~ /\.(git|svn|hg|env) { deny all; return 404; }
> ③ 【部署時用 git archive 匯出，不含 .git】
>    git archive --format=tar HEAD | tar -x -C /var/www/html
> ```

> [!tip] 保護重要分支（平台端設定）
> ```
> GitHub: Settings → Branches → Add branch protection rule
> GitLab: Settings → Repository → Protected branches
>
> □ 【禁止 force push】
> □ 【禁止刪除】
> □ 【要求 PR/MR 才能合併】
> □ 要求至少 N 位審查者
> □ 【要求 CI 通過】
> □ 要求分支為最新
> □ 【對管理員也套用】
> □ 【要求簽章提交】（進階）
> ```
>
> **這些是防止「一個誤操作毀掉整個歷史」最有效的方法。**

> [!warning] Commit 簽章（進階但值得）
> **問題**：任何人都可以偽造 commit 的作者。
> ```bash
> $ git config user.name "系統管理員"
> $ git config user.email "admin@example.gov.tw"
> $ git commit -m "後門"      # ← 看起來就是管理員做的
> ```
>
> **解法：用 GPG 或 SSH 金鑰簽章**
> ```bash
> # 用 SSH 金鑰簽章（比 GPG 簡單，Git 2.34+）
> $ git config --global gpg.format ssh
> $ git config --global user.signingkey ~/.ssh/id_ed25519.pub
> $ git config --global commit.gpgsign true
> $ git config --global tag.gpgsign true
>
> # 把公鑰加到 GitHub 的 "Signing Key"
> # 之後 commit 會顯示 Verified 標記
>
> # 驗證
> $ git log --show-signature -1
> ```

---

## 速查表

### 本地 vs 遠端追蹤分支

```
main         本地分支（可 commit）
origin/main  遠端追蹤分支（唯讀，【只在 fetch 時更新】）
遠端的 main  GitHub 上真正的分支（透過 push 更新）

★「明明 push 了但看不到」= 對方沒 fetch
★「明明遠端有更新但我看不到」= 你沒 fetch
```

### fetch vs pull

| | fetch | pull |
| --- | --- | --- |
| 做什麼 | **只下載，更新 origin/\*** | fetch + merge/rebase |
| 動工作區 | **❌ 不動** | ✅ 會動 |
| 安全 | **絕對安全** | 可能衝突 |

```bash
# 安全流程
git fetch
git log HEAD..origin/main --oneline    # 遠端有我沒有的
git log origin/main..HEAD --oneline    # 我有遠端沒有的
git rebase origin/main
```

### SSH 設定

```bash
ssh-keygen -t ed25519 -C "你的信箱" -f ~/.ssh/id_ed25519_github
ssh-add ~/.ssh/id_ed25519_github
cat ~/.ssh/id_ed25519_github.pub       # 貼到平台
ssh -T git@github.com                  # 測試
```

### 多帳號 `~/.ssh/config`

```
Host github-work
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_work
    IdentitiesOnly yes        # ★ 必要

用法：git clone git@github-work:org/repo.git
```

### remote 管理

```bash
git remote -v                          git remote show origin
git remote add upstream <url>
git remote set-url origin <url>
git remote set-url --push upstream DISABLED    # ★ 防誤推
git remote set-url --add --push origin <url2>  # 一次推多處
```

### 追蹤分支

```bash
git push -u origin <分支>              # 首次推送並建立追蹤
git config --global push.autoSetupRemote true   # ★ 之後免加 -u
git branch -vv                         # 查看追蹤關係
git push origin --delete <分支>        # 刪除遠端分支

## main...origin/main [ahead 2, behind 3]
   ahead=我有遠端沒有 → push；behind=遠端有我沒有 → pull
   ★ 同時 ahead+behind = 分岔了，要先整合
```

### PR 流程（Fork 模式）

```
fork → clone → 【加 upstream】→ 建分支（從 upstream/main）
→ 開發 → 【fetch upstream + rebase】→ 整理提交
→ push 到 origin → 建 PR → 依審查修改 → 合併 → 清理
```

### gh CLI

| 目的 | 指令 |
| --- | --- |
| 登入 | `gh auth login` + `gh auth setup-git` |
| 建 PR | `gh pr create --fill` |
| **測試別人的 PR** | **`gh pr checkout <號碼>`** |
| 審查 | `gh pr review <號碼> --approve` |
| 合併 | `gh pr merge <號碼> --squash --delete-branch` |
| 同步 fork | `gh repo sync <你的> --source <原始>` |

### 伺服器部署的憑證

```
① 【Deploy Key，設唯讀】← 推薦
② 一個 repo 一把金鑰
③ 權限 600，擁有者是服務帳號
④ 【不要放個人 SSH 金鑰】
⑤ Token 用 fine-grained，限單一 repo + 唯讀 + 設到期日
⑥ 伺服器被入侵 → 【立刻撤銷】
```

### `.git` 不能進 Web 根目錄

```
檢查：curl -sI https://網站/.git/config | head -1
應為 403 或 404，若是 200 → ⚠⚠

三種正確做法：
① web root 指向子目錄（Laravel 的 public/）
② Nginx: location ~ /\.(git|env) { deny all; return 404; }
③ git archive 匯出（不含 .git）
```

### 分支保護（平台端）

```
□ 禁止 force push    □ 禁止刪除
□ 要求 PR 才能合併   □ 要求審查者
□ 要求 CI 通過       □ 【對管理員也套用】
```

### SSH 金鑰簽章 commit

```bash
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519.pub
git config --global commit.gpgsign true
git log --show-signature -1
```

---

## 練習題

> [!question]- 練習 1：理解 origin/main 的「快照」性質
> 兩台機器（或兩個 clone）做實驗：
> 1. A 機器 push 一個新提交
> 2. **B 機器不 fetch，執行 `git log origin/main -1`** —— 看得到嗎？
> 3. B 執行 `git fetch`，再看一次
> 4. **B 執行 `git status -sb`**，顯示什麼？
> 5. `git log HEAD..origin/main --oneline` 顯示什麼？
> 6. 現在 B 也做一個提交，`git status -sb` 又顯示什麼？

> [!question]- 練習 2：設定多帳號 SSH
> 1. 產生兩把金鑰（work / personal）
> 2. 寫好 `~/.ssh/config`，**記得加 `IdentitiesOnly yes`**
> 3. `ssh -T git@github-work` 與 `ssh -T git@github-personal` 都測試
> 4. **故意拿掉 `IdentitiesOnly yes`，觀察會發生什麼**
>    （提示：SSH 會依序嘗試所有金鑰，可能用錯把）
> 5. 搭配 `includeIf` 設定，讓 `~/work/` 底下自動用工作身分
> 6. 驗證：在兩個目錄下分別 `git config user.email`

> [!question]- 練習 3：在測試機上安全地部署私有 repo
> ⚠️ 用測試機與測試 repo。
> 1. 產生一把**專用的 Deploy Key**
> 2. 加到 GitHub 的 Deploy Keys，**不要勾寫入權限**
> 3. 設定 `~/.ssh/config` 與 `known_hosts`
> 4. 用服務帳號（如 `www-data`）clone
> 5. **測試：能 pull 嗎？能 push 嗎？**（應該 pull 可以、push 被拒）
> 6. **檢查 `.git/config` 有沒有洩漏憑證**
> 7. **從外部 `curl -I https://你的網站/.git/config`** —— 回傳什麼？
> 8. 如果是 200，設定 Nginx 擋掉，再測一次

---

## 小測驗

Q1. **`main`、`origin/main`、遠端的 `main` 三者有什麼不同**？哪一個是唯讀的？

Q2. **為什麼會發生「明明 push 了但別人看不到」**？

Q3. **`git fetch` 與 `git pull` 的四個差異是什麼？建議的安全流程是什麼**？

Q4. `git status -sb` 顯示 `[ahead 2, behind 3]` 是什麼意思？**同時 ahead 又 behind 代表什麼，該怎麼處理**？

Q5. **多帳號 SSH 設定中，`IdentitiesOnly yes` 為什麼必要**？

Q6. `git push -u` 的 `-u` 做了什麼？有什麼設定可以讓它自動化？

Q7. **在伺服器上部署私有 repo 時，為什麼不能放個人的 SSH 金鑰？正確做法有哪六項**？

Q8. **`.git` 目錄被部署到 Web 根目錄有什麼風險？三種正確做法是什麼**？

Q9. **分支保護該設定哪六項？為什麼「對管理員也套用」很重要**？

Q10. **為什麼要簽章 commit？不簽章有什麼風險**？

> [!question]- 測驗答案
> **Q1.** **`main` 是本地分支**（你可以直接 commit）；
> **`origin/main` 是遠端追蹤分支**，
> 它記錄「**你上次 `git fetch` 時遠端的樣子**」，
> **是唯讀的**（只能透過 fetch 更新，不能直接 commit）；
> **遠端的 `main`** 是 GitHub/GitLab 上真正的分支，透過 push 更新。
>
> **Q2.** 因為 **`origin/main` 不是即時的，它只反映對方上次 fetch 時的狀態**。
> 你 push 之後，遠端確實更新了，
> 但**對方本地的 `origin/main` 還停留在他上次 fetch 的時間點**，
> 所以他看不到。
> 解法：**對方執行 `git fetch`（或 `git pull`）**。
> 同理，「明明遠端有更新但我看不到」也是因為你沒有 fetch。
>
> **Q3.** ①**做什麼**：fetch **只下載並更新 `origin/*`**；
> pull 是 **fetch + merge（或 rebase）**；
> ②**動工作區嗎**：fetch **完全不動**，pull **會改變你的檔案**；
> ③**安全性**：fetch **絕對安全**，pull 可能產生衝突或非預期的合併；
> ④**建議**：先 fetch 看一下，確定沒問題再合併。
> **安全流程**：`git fetch` →
> `git log HEAD..origin/main --oneline`（看遠端有我沒有的）→
> `git log origin/main..HEAD --oneline`（看我有遠端沒有的）→
> 確認後 `git rebase origin/main` 或 `git merge origin/main`。
>
> **Q4.** **`ahead 2`** = 我有 2 個提交是遠端沒有的（要 push）；
> **`behind 3`** = 遠端有 3 個提交是我沒有的（要 pull）。
> **同時 ahead 又 behind 代表「本地與遠端分岔了」** ——
> 你們各自在同一個分支上做了不同的提交。
> 這時**直接 push 會被拒絕**，
> 必須先整合：`git fetch` 之後
> `git rebase origin/main`（保持線性）
> 或 `git merge origin/main`（產生 merge commit），再 push。
>
> **Q5.** 因為**沒有它的話，SSH 會依序嘗試 agent 中與預設路徑的所有金鑰**，
> 可能在用到你指定的那把之前就先用了另一把 ——
> 結果是**用錯帳號**（例如用私人金鑰去存取公務 repo），
> 或因為嘗試次數過多被伺服器拒絕（`Too many authentication failures`）。
> `IdentitiesOnly yes` 強制**只使用該 Host 區塊中 `IdentityFile` 指定的金鑰**。
>
> **Q6.** `-u`（`--set-upstream`）建立「**本地分支 ↔ 遠端分支**」的
> **追蹤關係（upstream）**，
> 之後就可以直接用 `git push` / `git pull` 而不用每次指定 remote 與分支。
> 自動化設定：**`git config --global push.autoSetupRemote true`** ——
> 之後第一次 push 也不用加 `-u`。
>
> **Q7.** 因為**如果伺服器被入侵，攻擊者就取得了你「所有 repo」的寫入權**
> （個人金鑰通常對你參與的每一個專案都有權限）。
> 正確做法六項：
> ①**用 Deploy Key，且設為唯讀**（不勾 Allow write access）；
> ②**一個 repo 一把金鑰**（不要共用）；
> ③**金鑰檔權限 600，擁有者是服務帳號**；
> ④**不要在伺服器上放個人的 SSH 金鑰**；
> ⑤Token 若必須用，採 **fine-grained 且限定單一 repo + 唯讀 + 設到期日**；
> ⑥**伺服器被入侵時立刻撤銷該金鑰／Token**。
>
> **Q8.** 風險是：**`https://網站/.git/config` 可以被下載**，
> 攻擊者藉此**還原整個原始碼與完整歷史** ——
> 其中可能包含**曾經 commit 過的資料庫密碼、API 金鑰、內部架構**
> （即使後來刪掉，歷史裡還在）。
> **三種正確做法**：
> ①**把 web root 指向子目錄**（如 Laravel 的 `public/`），
> `.git` 在上一層 Web 碰不到；
> ②**Nginx/Apache 明確拒絕**：
> `location ~ /\.(git|svn|hg|env) { deny all; return 404; }`；
> ③**部署時用 `git archive` 匯出**，產出的內容不含 `.git`。
>
> **Q9.** ①**禁止 force push**；②**禁止刪除分支**；
> ③**要求 PR/MR 才能合併**；④**要求至少 N 位審查者核准**；
> ⑤**要求 CI 通過**；⑥**要求分支為最新**（合併前先同步）。
> **「對管理員也套用」很重要**，因為
> **管理員往往是最容易誤操作的人**（權限最大、最常在趕時間），
> 而且如果管理員可以繞過，那麼**攻擊者只要取得一個管理員帳號
> 就能繞過所有保護** ——
> 保護規則若對最高權限者無效，等於防護出現一個大洞。
>
> **Q10.** 因為**任何人都可以偽造 commit 的作者資訊** ——
> 只要 `git config user.name "系統管理員"` 加上對應的信箱，
> 做出來的 commit 看起來就像是管理員提交的。
> 不簽章的風險是：**無法證明某個提交真的是某人做的**，
> 事件調查時無法究責，
> 也**無法排除「攻擊者用你的名義植入後門」**。
> 用 SSH 金鑰簽章（Git 2.34+）設定很簡單：
> `gpg.format ssh` + `user.signingkey` + `commit.gpgsign true`，
> 平台上會顯示 **Verified** 標記。

---

## 延伸閱讀

- [[03-Git-分支與合併]] — 分支策略與衝突處理
- [[08-Git-伺服器端與自動部署]] — 自架 Git 遠端與 push 即部署
- [[09-Git-團隊規範與實戰情境]] — PR 規範與誤推處理
- [[02-SSH-金鑰認證與ssh-agent]] — SSH 金鑰的完整說明
- [[03-機密管理與金鑰保護]] — Token 與金鑰的安全存放
- [[00-部署實戰-索引]] — 從 Git 專案部署到正式環境
