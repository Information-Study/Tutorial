---
title: "Git 進階技巧"
desc: "stash、worktree、bisect、hooks、submodule 與大檔案處理"
aliases: [git stash, git worktree, git bisect, git hooks, submodule, LFS]
tags: [群組/軟體與開發工具, 工具/git, 主題/版本控制]
category: 常用工具
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[05-Git-回復與重寫歷史]]"]
updated: 2026-08-28
---

# Git 進階技巧

> [!abstract] 這篇你會學到
> - 用 **stash** 在多任務間快速切換而不弄丟修改
> - 用 **worktree** 同時開多個工作目錄（比 stash 更好用）
> - 用 **bisect** 二分定位「是哪個提交造成的」
> - 用 **hooks** 自動化檢查（提交前掃機密、驗證設定檔語法）
> - 處理 **submodule** 與 **大檔案（LFS）**
> - 各種**實用的排查技巧**

## 前置知識

- [[05-Git-回復與重寫歷史]] — reset、revert、reflog
- [[03-Git-分支與合併]] — 分支與 rebase

---

## `git stash`：暫存工作進度

> [!tip] 典型情境
> ```
> 你正在改 A 功能，改到一半 →
>   突然有緊急的 bug 要修 →
>     但工作區很亂，不想提交半成品 →
>       【git stash】把修改收起來 →
>         修完 bug →
>           【git stash pop】拿回來繼續
> ```

```bash
# ===== 基本操作 =====
$ git stash                              # 暫存（不含未追蹤的檔案）
$ git stash push -m "改到一半的 API 設定"  # ★ 加訊息（強烈建議）
$ git stash -u                           # ★ 含未追蹤的檔案
$ git stash -a                           # 含被 gitignore 忽略的（少用）

# ===== 只暫存部分 =====
$ git stash push -m "只存這個" nginx.conf php.ini    # 指定檔案
$ git stash push -p                      # ★ 互動式挑選（同 add -p）
$ git stash push --staged                # 只暫存「已 add」的部分（Git 2.35+）

# ===== 查看 =====
$ git stash list
stash@{0}: On main: 改到一半的 API 設定
stash@{1}: On feature/x: WIP on feature/x: a1b2c3d 上一個提交

$ git stash show                         # 摘要
$ git stash show -p                      # ★ 完整 diff
$ git stash show -p stash@{1}

# ===== 取回 =====
$ git stash pop                          # 取回最新的並【刪除】
$ git stash apply                        # 取回但【保留】stash ★ 較安全
$ git stash apply stash@{2}              # 取回特定的
$ git stash pop --index                  # 連暫存區狀態也還原

# ===== 刪除 =====
$ git stash drop stash@{0}
$ git stash clear                        # ★★ 全部刪除（危險）

# ===== 從 stash 建立分支（★ 衝突時很好用）=====
$ git stash branch feature/繼續做 stash@{0}
# → 從 stash 建立時的提交建立新分支，套用 stash，並刪除它
```

> [!warning] stash 的三個陷阱
> **一、`git stash` 預設不含未追蹤的檔案**
> ```bash
> $ git stash            # 新建的檔案還留在工作區
> $ git stash -u         # ★ 才會一起收起來
> ```
> 這常導致「切換分支後看到不該存在的檔案」。
>
> **二、stash 是「一疊」，容易堆積**
> ```bash
> $ git stash list
> stash@{0}: WIP on main: ...
> stash@{1}: WIP on main: ...
> stash@{2}: WIP on feature: ...
> ...                              ← 三個月前的，完全忘記是什麼
> ```
> **對策：一律用 `git stash push -m "訊息"`。**
>
> **三、stash 不會推送到遠端**
> stash 是**純本地的**，重灌電腦就沒了。
> **長期保存請用分支或提交。**

> [!tip] `pop` vs `apply`
> ```
> pop   = apply + drop      套用成功就刪掉
> apply = 只套用，stash 保留
>
> ★ 建議：不確定會不會有衝突時，先用 apply
>   確認沒問題再 git stash drop
> ```
> **因為 `pop` 遇到衝突時，stash 不會被刪除，
> 但如果你此時處理不當，可能會搞混狀態。**

---

## `git worktree`：多個工作目錄

> [!tip] 比 stash 更好的多任務方案
> **stash 的問題**：你只有一個工作目錄，切換時要收拾東西。
>
> **worktree**：**同一個 repo，多個工作目錄，各自在不同的分支上。**

```bash
# ===== 建立一個新的工作目錄 =====
$ git worktree add ../myproject-hotfix hotfix/1567
Preparing worktree (new branch 'hotfix/1567')
HEAD is now at a1b2c3d ...

$ ls ..
myproject/            ← 原本的（在 feature 分支）
myproject-hotfix/     ← 新的（在 hotfix 分支）

# ===== 建立並同時建立新分支 =====
$ git worktree add -b hotfix/1567 ../myproject-hotfix v1.2.0

# ===== 從特定提交建立（detached）=====
$ git worktree add --detach ../myproject-v1 v1.0.0

# ===== 查看 =====
$ git worktree list
/home/user/myproject          a1b2c3d [feature/api]
/home/user/myproject-hotfix   d4e5f6g [hotfix/1567]

# ===== 移除 =====
$ git worktree remove ../myproject-hotfix
$ git worktree prune                     # 清理已刪除目錄的記錄
```

> [!tip] worktree 的實用場景
> ```
> ① 【緊急修正】不用打斷手上的工作
>    主目錄繼續開發 feature，另開一個目錄做 hotfix
>
> ② 【同時跑兩個版本做比對】
>    git worktree add ../v1 v1.0.0
>    git worktree add ../v2 v2.0.0
>    → 兩邊同時跑起來比較行為差異
>
> ③ 【邊看舊版邊寫新版】
>    不用一直切換分支
>
> ④ 【CI 或建置時】
>    在獨立的 worktree 建置，不影響開發目錄
>
> ⑤ 【審查別人的 PR】
>    git worktree add ../review pr-branch
>    → 不用清理自己的工作區
> ```
>
> **共用的東西**：所有 worktree **共用同一個 `.git`（物件資料庫）**，
> 所以**不會佔用兩倍空間**，提交也是共通的。

> [!warning] worktree 的限制
> ```
> ① 【同一個分支不能同時被兩個 worktree 檢出】
>    $ git worktree add ../x main
>    fatal: 'main' is already checked out at '/home/user/myproject'
>
> ② 【每個 worktree 需要自己的 node_modules / vendor】
>    （它們通常在 .gitignore 中，不會共用）
>
> ③ 【.env 等被忽略的檔案要自己複製過去】
> ```

---

## `git bisect`：二分定位問題提交

> [!tip] 情境
> **「上個月還好好的，現在壞了，但中間有 200 個提交。」**
>
> bisect 用二分法，**7～8 次測試就能從 200 個提交中找出兇手**。

```bash
# ===== 【1】開始 =====
$ git bisect start

# ===== 【2】標記已知的好與壞 =====
$ git bisect bad                    # 目前這個版本是壞的
$ git bisect bad v1.2.0             # 或指定
$ git bisect good v1.1.0            # 這個版本是好的

Bisecting: 98 revisions left to test after this (roughly 7 steps)
[a1b2c3d] feat: 某個提交

# ===== 【3】測試 Git 挑出來的版本，回報結果 =====
$ ...測試...
$ git bisect good         # 這個版本沒問題
# 或
$ git bisect bad          # 這個版本有問題
# 或
$ git bisect skip         # 這個版本無法測試（例如編譯不過）

# ===== 【4】重複，直到找出兇手 =====
a1b2c3d is the first bad commit
commit a1b2c3d
Author: 王小明 <wang@example.gov.tw>
Date:   2026-08-15

    perf(nginx): 調整 worker_connections

 nginx/nginx.conf | 2 +-

# ===== 【5】結束 =====
$ git bisect reset        # ★ 回到原本的分支
```

### 自動化 bisect

> [!tip] 有測試腳本的話可以全自動
> ```bash
> # 測試腳本：exit 0 = 好，exit 1-127（除了 125）= 壞，125 = 跳過
> $ cat > /tmp/test.sh <<'EOF'
> #!/usr/bin/env bash
> # 檢查 nginx 設定是否能通過語法檢查
> sudo nginx -t -c "$(pwd)/nginx/nginx.conf" 2>/dev/null || exit 1
> # 檢查特定的設定值
> grep -q "worker_connections 4096" nginx/nginx.conf || exit 1
> exit 0
> EOF
> $ chmod +x /tmp/test.sh
>
> $ git bisect start HEAD v1.1.0    # bad good
> $ git bisect run /tmp/test.sh     # ★ 全自動找出兇手
> ...
> a1b2c3d is the first bad commit
> $ git bisect reset
> ```

```bash
# ===== 其他選項 =====
$ git bisect log                    # 查看 bisect 的過程
$ git bisect log > /tmp/bisect.log
$ git bisect replay /tmp/bisect.log # 重播（做錯了想重來）

# ===== 自訂術語（不一定是 good/bad）=====
$ git bisect start --term-old=fast --term-new=slow
$ git bisect slow
$ git bisect fast v1.1.0
```

> [!warning] bisect 的前提
> ```
> ① 【每個提交都要能執行／測試】
>    → 如果中間有一堆「壞掉的」提交，會很痛苦
>    → 這就是為什麼「每個提交都應該是可運作的」
>
> ② 【問題要能穩定重現】
>    → 間歇性的問題無法用 bisect
>
> ③ 【測試要夠快】
>    → 每次測試 30 分鐘 × 8 次 = 4 小時
> ```

---

## `git hooks`：自動化

> [!note] hooks 是什麼
> **在 Git 執行特定動作時自動觸發的腳本。**
>
> 位置：`.git/hooks/`（**不會進版控**）

| Hook | 觸發時機 | 常見用途 |
| --- | --- | --- |
| **`pre-commit`** | commit 前 | **掃描機密、格式檢查、語法驗證** |
| `prepare-commit-msg` | 準備訊息時 | 自動填入分支名或單號 |
| **`commit-msg`** | 訊息寫完後 | **檢查訊息格式** |
| `post-commit` | commit 後 | 通知 |
| **`pre-push`** | push 前 | **跑測試、阻止推到受保護分支** |
| `pre-rebase` | rebase 前 | 阻止 rebase 已發布的分支 |
| `post-merge` | merge 後 | 自動安裝相依套件 |
| `post-checkout` | 切換分支後 | 提示需要重新安裝套件 |
| **`post-receive`** | **伺服器端**收到 push 後 | **自動部署**（見 08 篇） |

### 實用的 hooks

```bash
# ═══════════ pre-commit：掃描機密 + 驗證設定檔 ═══════════
$ cat > .git/hooks/pre-commit <<'EOF'
#!/usr/bin/env bash
set -e
FAILED=0

# ---------- 【1】掃描機密 ----------
if command -v gitleaks >/dev/null 2>&1; then
  if ! gitleaks protect --staged --redact -v 2>/dev/null; then
    echo "❌ 偵測到疑似機密資訊"
    FAILED=1
  fi
fi

# ---------- 【2】阻止大檔案 ----------
MAX_KB=1024
while IFS= read -r f; do
  [ -f "$f" ] || continue
  size=$(du -k "$f" | cut -f1)
  if [ "$size" -gt "$MAX_KB" ]; then
    echo "❌ 檔案過大：$f (${size}KB > ${MAX_KB}KB)"
    echo "   考慮使用 Git LFS 或加入 .gitignore"
    FAILED=1
  fi
done < <(git diff --cached --name-only --diff-filter=ACM)

# ---------- 【3】驗證 Nginx 設定語法 ----------
if git diff --cached --name-only | grep -q '\.conf$'; then
  if command -v nginx >/dev/null 2>&1; then
    if ! sudo nginx -t 2>/dev/null; then
      echo "⚠ Nginx 設定語法檢查失敗（請確認）"
    fi
  fi
fi

# ---------- 【4】驗證 YAML / JSON ----------
while IFS= read -r f; do
  case "$f" in
    *.yml|*.yaml)
      python3 -c "import yaml,sys; yaml.safe_load(open('$f'))" 2>/dev/null || {
        echo "❌ YAML 語法錯誤：$f"; FAILED=1; }
      ;;
    *.json)
      python3 -m json.tool "$f" >/dev/null 2>&1 || {
        echo "❌ JSON 語法錯誤：$f"; FAILED=1; }
      ;;
  esac
done < <(git diff --cached --name-only --diff-filter=ACM)

# ---------- 【5】偵測殘留的衝突標記 ----------
if git diff --cached | grep -qE '^\+(<<<<<<<|=======|>>>>>>>)'; then
  echo "❌ 偵測到殘留的合併衝突標記"
  FAILED=1
fi

# ---------- 【6】偵測除錯用的程式碼 ----------
if git diff --cached | grep -qiE '^\+.*(var_dump|dd\(|console\.log|debugger|TODO: *REMOVE)'; then
  echo "⚠ 偵測到可能的除錯程式碼，請確認"
fi

[ "$FAILED" -eq 0 ] || {
  echo ""
  echo "提交已阻止。確認為誤判時可用：git commit --no-verify"
  exit 1
}
EOF
$ chmod +x .git/hooks/pre-commit
```

```bash
# ═══════════ commit-msg：檢查訊息格式 ═══════════
$ cat > .git/hooks/commit-msg <<'EOF'
#!/usr/bin/env bash
MSG_FILE="$1"
FIRST_LINE=$(head -1 "$MSG_FILE")

# 允許 merge / revert / fixup
case "$FIRST_LINE" in
  Merge*|Revert*|fixup!*|squash!*) exit 0 ;;
esac

PATTERN='^(feat|fix|docs|style|refactor|perf|test|chore|ci|build|revert)(\([a-zA-Z0-9_/-]+\))?!?: .{1,72}$'

if ! echo "$FIRST_LINE" | grep -qE "$PATTERN"; then
  cat <<'MSG'
❌ Commit 訊息格式不符

正確格式：
  <類型>(<範圍>): <簡短描述>

類型：feat fix docs style refactor perf test chore ci build revert

範例：
  feat(nginx): 新增 API 反向代理設定
  fix(php): 修正檔案上傳大小限制未生效
  chore: 更新相依套件版本

規則：
  · 標題不超過 72 字元
  · 使用祈使句（「新增」而非「新增了」）
MSG
  echo ""
  echo "你寫的是：$FIRST_LINE"
  exit 1
fi
EOF
$ chmod +x .git/hooks/commit-msg
```

```bash
# ═══════════ pre-push：阻止推到受保護分支 + 跑測試 ═══════════
$ cat > .git/hooks/pre-push <<'EOF'
#!/usr/bin/env bash
PROTECTED="main master production"
REMOTE="$1"

while read -r local_ref local_sha remote_ref remote_sha; do
  branch="${remote_ref#refs/heads/}"

  # 【1】阻止直接推到受保護分支
  for p in $PROTECTED; do
    if [ "$branch" = "$p" ]; then
      echo "❌ 禁止直接推送到受保護分支：$branch"
      echo "   請透過 Pull Request 合併"
      echo "   確定要推送請用：git push --no-verify"
      exit 1
    fi
  done

  # 【2】阻止推送含 WIP 的提交
  if [ "$local_sha" != "0000000000000000000000000000000000000000" ]; then
    if git log --format=%s "$remote_sha..$local_sha" 2>/dev/null | grep -qiE '^(wip|fixup!|squash!)'; then
      echo "❌ 有未整理的 WIP/fixup 提交，請先執行："
      echo "   git rebase -i --autosquash origin/main"
      exit 1
    fi
  fi
done

# 【3】跑測試（如果有）
if [ -f "package.json" ] && grep -q '"test"' package.json; then
  npm test || { echo "❌ 測試未通過"; exit 1; }
fi
EOF
$ chmod +x .git/hooks/pre-push
```

```bash
# ═══════════ post-merge：自動安裝相依套件 ═══════════
$ cat > .git/hooks/post-merge <<'EOF'
#!/usr/bin/env bash
changed() { git diff-tree -r --name-only ORIG_HEAD HEAD | grep -q "^$1$"; }

changed "composer.lock"     && echo "→ composer.lock 有變更，執行 composer install" && composer install
changed "package-lock.json" && echo "→ package-lock.json 有變更，執行 npm ci" && npm ci
changed ".env.example"      && echo "⚠ .env.example 有變更，請確認你的 .env 是否需要更新"
EOF
$ chmod +x .git/hooks/post-merge
```

### 用 pre-commit 框架管理（★ 推薦）

> [!danger] `.git/hooks/` 不會進版控
> **這代表**：
> - 新成員 clone 之後**沒有任何 hooks**
> - 每個人的 hooks 可能不一樣
> - 無法統一維護
>
> **解法一：`core.hooksPath`**
> ```bash
> $ mkdir -p .githooks
> $ mv .git/hooks/pre-commit .githooks/
> $ git config core.hooksPath .githooks    # 每個人 clone 後要執行一次
> $ git add .githooks && git commit -m "chore: 加入共用的 git hooks"
> ```
>
> **解法二：pre-commit 框架（★ 更好）**

```yaml
# .pre-commit-config.yaml（進版控，團隊共用）
repos:
  # ===== 機密掃描 =====
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks:
      - id: gitleaks

  # ===== 通用檢查 =====
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: check-added-large-files
        args: ['--maxkb=1024']
      - id: detect-private-key          # ★ 偵測私鑰
      - id: check-merge-conflict        # 殘留的衝突標記
      - id: check-yaml
      - id: check-json
      - id: check-xml
      - id: end-of-file-fixer
      - id: trailing-whitespace
      - id: mixed-line-ending
        args: ['--fix=lf']
      - id: no-commit-to-branch
        args: ['--branch', 'main', '--branch', 'master']

  # ===== Shell 腳本檢查 =====
  - repo: https://github.com/koalaman/shellcheck-precommit
    rev: v0.9.0
    hooks:
      - id: shellcheck

  # ===== commit 訊息格式 =====
  - repo: https://github.com/compilerla/conventional-pre-commit
    rev: v3.0.0
    hooks:
      - id: conventional-pre-commit
        stages: [commit-msg]
```

```bash
$ pip install --user pre-commit
$ pre-commit install                    # 安裝 pre-commit hook
$ pre-commit install --hook-type commit-msg
$ pre-commit run --all-files            # 對現有檔案跑一次
$ pre-commit autoupdate                 # 更新 hook 版本
```

> [!warning] hooks 可以被 `--no-verify` 略過
> ```bash
> $ git commit --no-verify -m "..."
> $ git push --no-verify
> ```
>
> **所以 hooks 是「幫助」不是「強制」。**
>
> **真正的強制要在伺服器端**：
> - 平台的**分支保護規則**
> - **CI 檢查**（PR 必須通過才能合併）
> - 伺服器端的 **pre-receive hook**（自架 Git 時）

---

## Submodule 與 Subtree

> [!warning] submodule 是進階功能，容易踩坑
> **先問：你真的需要它嗎？**
> ```
> 多數情況下，更好的替代方案是：
>   · 套件管理器（Composer、npm）
>   · Monorepo
>   · git subtree
> ```

```bash
# ===== 新增 submodule =====
$ git submodule add https://github.com/org/lib.git vendor/lib
$ git commit -m "chore: 新增 lib submodule"

# ===== Clone 含 submodule 的 repo（★ 最常踩的坑）=====
$ git clone --recurse-submodules <url>          # ★ 一次到位
# 或已經 clone 了：
$ git submodule update --init --recursive

# ===== 更新 submodule 到最新 =====
$ git submodule update --remote vendor/lib
$ git add vendor/lib && git commit -m "chore: 更新 lib 至最新版"

# ===== 在所有 submodule 執行指令 =====
$ git submodule foreach 'git checkout main && git pull'

# ===== 移除 =====
$ git submodule deinit -f vendor/lib
$ git rm -f vendor/lib
$ rm -rf .git/modules/vendor/lib

# ===== 設定：pull 時自動更新 submodule =====
$ git config --global submodule.recurse true
```

> [!danger] submodule 的常見陷阱
> ```
> ① 【clone 後 submodule 目錄是空的】
>    → 忘了 --recurse-submodules
>
> ② 【submodule 停在 detached HEAD】
>    → 這是正常的（它被固定在某個提交）
>    → 要改動的話要先 git checkout main
>
> ③ 【忘記提交 submodule 的指標更新】
>    → 你更新了 submodule 但沒 commit 主 repo
>    → 別人 clone 下來還是舊版
>
> ④ 【CI/部署時忘記初始化】
>    → 建置失敗，找不到檔案
>
> ⑤ 【submodule 的 URL 用了 SSH，但 CI 只有 HTTPS 憑證】
>    → 用 .gitmodules 的 URL 改寫或 insteadOf
> ```

```bash
# ===== git subtree（替代方案，較無痛）=====
$ git subtree add --prefix=vendor/lib https://github.com/org/lib.git main --squash
$ git subtree pull --prefix=vendor/lib https://github.com/org/lib.git main --squash

# 優點：clone 的人【不需要做任何特殊處理】
# 缺點：主 repo 會包含 lib 的完整內容
```

---

## 大檔案：Git LFS

> [!danger] Git 不適合存大型二進位檔案
> ```
> Git 的每個版本都存完整內容（雖然會壓縮）
>   → 一個 100MB 的檔案改了 10 次
>     → repo 變成 1GB
>       → 【clone 極慢，且所有人都要下載】
>       → 【而且無法刪除（在歷史裡）】
> ```

```bash
# ===== 安裝 =====
$ sudo apt install -y git-lfs
$ git lfs install                        # 每個使用者執行一次

# ===== 追蹤特定類型 =====
$ git lfs track "*.psd"
$ git lfs track "*.zip"
$ git lfs track "*.mp4"
$ git lfs track "assets/videos/**"

# ★ .gitattributes 會被建立，【必須 commit】
$ git add .gitattributes
$ git commit -m "chore: 設定 Git LFS 追蹤大型檔案"

# ===== 之後正常使用 =====
$ git add big-file.psd
$ git commit -m "feat: 新增設計稿"
$ git push

# ===== 查看 =====
$ git lfs ls-files
$ git lfs track                          # 目前追蹤的樣式
$ git lfs env

# ===== 只下載需要的（節省空間）=====
$ git lfs pull --include="assets/current/*"
$ GIT_LFS_SKIP_SMUDGE=1 git clone <url>  # clone 時不下載 LFS 檔案
```

> [!warning] LFS 的注意事項
> ```
> ① 【必須在加入檔案「之前」設定 track】
>    已經 commit 的檔案要用 git lfs migrate
>
> ② 【伺服器端要支援 LFS】
>    GitHub/GitLab 支援，但【有流量與空間配額】
>
> ③ 【所有協作者都要安裝 git-lfs】
>    否則他們拿到的是指標檔案而非實際內容
>
> ④ 【CI/部署環境也要裝】
> ```

```bash
# ===== 把既有的大檔案遷移到 LFS =====
$ git lfs migrate import --include="*.psd" --everything
# ⚠ 這會【改寫歷史】，見 [[05-Git-回復與重寫歷史]]
```

---

## 其他實用技巧

### 找出 repo 中最大的檔案

```bash
# ===== 找出歷史中最大的物件 =====
$ git rev-list --objects --all |
  git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' |
  awk '/^blob/ {print substr($0, 6)}' |
  sort -k2 -nr | head -20 |
  numfmt --field=2 --to=iec-i --suffix=B --padding=8

a1b2c3d...   45MiB  assets/video.mp4
d4e5f6g...   12MiB  docs/manual.pdf

# ===== repo 大小分析 =====
$ git count-objects -vH
count: 234
size: 1.2 MiB
in-pack: 15678
size-pack: 456.7 MiB          ← 實際佔用
```

### 清理與最佳化

```bash
$ git gc                       # 垃圾回收
$ git gc --aggressive --prune=now    # 徹底清理（慢）
$ git repack -Ad               # 重新打包
$ git prune                    # 刪除孤立物件

# ===== 淺層化既有的 clone（節省空間）=====
$ git fetch --depth=1
$ git reflog expire --expire=now --all
$ git gc --prune=now --aggressive
```

### 忽略「不想追蹤的本地修改」

```bash
# ===== 情境：設定檔要在版控中，但本機的修改不想提交 =====
$ git update-index --skip-worktree config/local.php
$ git update-index --no-skip-worktree config/local.php    # 取消

# 查看被標記的檔案
$ git ls-files -v | grep '^S'

# ⚠ --assume-unchanged 是給「效能最佳化」用的，
#   不要拿來做這件事（Git 可能在某些操作時忽略它）
```

> [!tip] 更好的做法
> ```
> ❌ 把 config.php 放版控 + skip-worktree
> ✅ 【config.php.example 放版控，config.php 加入 .gitignore】
> ✅ 或用環境變數（.env）
> ```
> `skip-worktree` 是**權宜之計**，容易造成混亂。

### 搜尋

```bash
# ===== 在目前的工作區搜尋 =====
$ git grep "worker_connections"
$ git grep -n "worker_connections"           # 顯示行號
$ git grep -i --heading --break "gzip"       # 分組顯示

# ===== 在特定版本搜尋 =====
$ git grep "gzip" v1.0.0
$ git grep "gzip" $(git rev-list --all)      # ★ 搜尋整個歷史

# ===== 找出「引入或刪除某段內容」的提交 =====
$ git log -S "gzip on" --oneline
$ git log -G "worker_.*" --oneline           # 正規表示式

# ===== 找出某個檔案何時被刪除 =====
$ git log --diff-filter=D --oneline -- path/to/deleted-file
$ git show <該提交>^:path/to/deleted-file    # 取回內容
```

### 統計

```bash
# ===== 各作者的提交數 =====
$ git shortlog -sn
   142  王小明
    89  李大同
    34  陳小美

$ git shortlog -sn --since="2026-01-01"

# ===== 各作者的行數變更 =====
$ git log --author="王小明" --pretty=tformat: --numstat |
  awk '{add+=$1; del+=$2} END {printf "新增 %d 行，刪除 %d 行\n", add, del}'

# ===== 最常被修改的檔案（可能是問題熱點）=====
$ git log --pretty=format: --name-only | sort | uniq -c | sort -rn | head -20
    89 nginx/nginx.conf
    45 php/php.ini

# ===== 提交時間分布 =====
$ git log --format=%ad --date=format:'%H' | sort | uniq -c | sort -k2
```

---

## 完整實戰範例

### 用 bisect 找出「網站變慢」的元兇

```bash
# ========== 【1】準備測試腳本 ==========
$ cat > /tmp/perf-test.sh <<'EOF'
#!/usr/bin/env bash
# 部署目前的設定並測試回應時間
sudo cp nginx/nginx.conf /etc/nginx/nginx.conf
sudo nginx -t 2>/dev/null || exit 125    # 125 = 跳過這個提交
sudo nginx -s reload
sleep 2

# 測 10 次取平均
total=0
for i in $(seq 10); do
  t=$(curl -o /dev/null -s -w '%{time_total}' https://example.gov.tw/)
  total=$(echo "$total + $t" | bc)
done
avg=$(echo "scale=3; $total / 10" | bc)
echo "平均回應時間：${avg}s"

# 超過 1 秒視為「壞」
(( $(echo "$avg > 1.0" | bc -l) )) && exit 1 || exit 0
EOF
$ chmod +x /tmp/perf-test.sh

# ========== 【2】自動 bisect ==========
$ git bisect start HEAD v1.1.0          # HEAD=壞, v1.1.0=好
$ git bisect run /tmp/perf-test.sh

running /tmp/perf-test.sh
平均回應時間：0.234s
Bisecting: 49 revisions left to test after this (roughly 6 steps)
...
a1b2c3d is the first bad commit
commit a1b2c3d
    perf(nginx): 調整 worker_connections 為 128

 nginx/nginx.conf | 2 +-

# ========== 【3】結束並修正 ==========
$ git bisect reset
$ git show a1b2c3d                       # 看看它改了什麼
```

### 用 worktree 處理緊急修正

```bash
# ========== 情境：正在開發 feature，突然要修正式環境的 bug ==========

# 【1】不用 stash，直接開一個新的工作目錄
$ git worktree add -b hotfix/1567 ../myproject-hotfix v1.2.0
Preparing worktree (new branch 'hotfix/1567')

# 【2】切過去處理
$ cd ../myproject-hotfix
$ cp ../myproject/.env .                 # 複製被忽略的設定檔
$ vim nginx/nginx.conf
$ sudo nginx -t
$ git commit -am "fix(nginx): 調高 proxy_read_timeout（#1567）"
$ git push -u origin hotfix/1567

# 【3】打標籤並部署
$ git tag -s v1.2.1 -m "hotfix: 修正登入逾時（#1567）"
$ git push --follow-tags
$ ssh web01 'sudo /usr/local/sbin/deploy.sh v1.2.1'

# 【4】合併回 main
$ cd ../myproject
$ git switch main && git pull
$ git merge --no-ff hotfix/1567
$ git push

# 【5】清理
$ git worktree remove ../myproject-hotfix
$ git branch -d hotfix/1567
$ git push origin --delete hotfix/1567

# ★ 全程你的 feature 分支工作區【完全沒有被動到】
```

### 建立團隊共用的 hooks

```bash
# ========== 【1】在 repo 中建立 .githooks 目錄 ==========
$ mkdir -p .githooks

$ cat > .githooks/pre-commit <<'EOF'
#!/usr/bin/env bash
# 團隊共用的 pre-commit 檢查
exec .githooks/lib/check-secrets.sh
EOF

$ mkdir -p .githooks/lib
$ cat > .githooks/lib/check-secrets.sh <<'EOF'
#!/usr/bin/env bash
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks protect --staged --redact -v || {
    echo "❌ 偵測到疑似機密"; exit 1; }
else
  echo "⚠ 未安裝 gitleaks，跳過機密掃描"
  echo "  安裝方式：見 README.md"
fi
EOF

$ chmod +x .githooks/pre-commit .githooks/lib/*.sh
$ git add .githooks
$ git commit -m "chore: 加入團隊共用的 git hooks"

# ========== 【2】在 README 中說明 ==========
$ cat >> README.md <<'EOF'

## 開發環境設定

Clone 之後請執行一次：

```bash
git config core.hooksPath .githooks
```

這會啟用團隊共用的 Git hooks（機密掃描、格式檢查）。
EOF

# ========== 【3】用 post-checkout 自動提醒 ==========
# ⚠ 但這個 hook 本身也在 .git/hooks，第一次 clone 時還沒有…
# → 所以還是要靠 README 或 setup 腳本
```

```bash
# ========== 更好的做法：提供 setup 腳本 ==========
$ cat > setup.sh <<'EOF'
#!/usr/bin/env bash
set -e
echo "設定開發環境…"

git config core.hooksPath .githooks
echo "✓ 已啟用共用 hooks"

command -v gitleaks >/dev/null || \
  echo "⚠ 請安裝 gitleaks：https://github.com/gitleaks/gitleaks"

[ -f .env ] || { cp .env.example .env; echo "✓ 已建立 .env（請填入設定）"; }

echo "完成！"
EOF
$ chmod +x setup.sh
```

---

## 常見錯誤與排錯

| 現象／錯誤 | 原因 | 解法 |
| --- | --- | --- |
| **stash 後新檔案還在** | `git stash` 預設不含未追蹤檔案 | **`git stash -u`** |
| stash 堆積成山不知道是什麼 | 沒寫訊息 | **一律 `git stash push -m "訊息"`** |
| **stash 弄丟了** | stash 是純本地的 | 長期保存用**分支或提交**；`git fsck` 可能找得回 |
| `git stash pop` 有衝突後狀態混亂 | pop 遇衝突不會刪 stash | 用 **`apply`** 較安全；或 `git stash branch` |
| **worktree 說分支已被檢出** | 同一分支不能被兩個 worktree 檢出 | 用不同分支，或 `--detach` |
| worktree 目錄缺 `.env` / `node_modules` | 它們在 gitignore 中 | 手動複製或重新安裝 |
| **bisect 中間的提交跑不起來** | 有壞掉的提交 | `git bisect skip`；根本解是「每個提交都可運作」 |
| bisect 找錯了 | 測試不穩定或標記錯誤 | `git bisect log` 檢視；`git bisect replay` 重來 |
| **hooks 對新成員無效** | `.git/hooks` 不進版控 | **`core.hooksPath`** 或 **pre-commit 框架** |
| hooks 被 `--no-verify` 略過 | hooks 是本地的 | **真正的強制在伺服器端**（分支保護 + CI） |
| **submodule clone 後是空的** | 忘了 `--recurse-submodules` | `git submodule update --init --recursive` |
| submodule 在 detached HEAD | 正常現象 | 要改動先 `git -C <submodule> switch main` |
| **更新 submodule 但別人拿到舊版** | 忘記提交主 repo 的指標 | `git add <submodule路徑> && git commit` |
| **repo 越來越大，clone 很慢** | 有大型二進位檔案 | 找出大檔案；改用 **LFS**；`git lfs migrate` |
| LFS 檔案下載下來是文字指標 | 沒裝 git-lfs | `git lfs install && git lfs pull` |
| `skip-worktree` 造成混亂 | 它是權宜之計 | 改用 `.example` 檔案 + `.gitignore` |

---

## 安全性注意事項

> [!danger] hooks 是「協助」不是「強制」
> ```
> git commit --no-verify     → 略過 pre-commit / commit-msg
> git push --no-verify       → 略過 pre-push
> ```
>
> **所以絕對不要把 hooks 當作唯一的安全防線。**
>
> **真正的強制必須在伺服器端**：
> | 層級 | 機制 |
> | --- | --- |
> | 本地 | hooks（**方便，但可略過**） |
> | **平台** | **分支保護、Tag protection、必要的 CI 檢查** |
> | **CI** | **機密掃描、測試、程式碼檢查**（PR 必須通過） |
> | **自架 Git** | **`pre-receive` hook**（伺服器端，無法略過） |

> [!warning] hooks 本身也是攻擊面
> ```
> 攻擊情境：
>   攻擊者取得 repo 的寫入權
>     → 修改 .githooks/pre-commit（如果用 core.hooksPath）
>       → 【所有開發者執行 git commit 時就會執行惡意程式碼】
> ```
>
> **防護**：
> - **hooks 的變更也要經過 code review**
> - 用 **pre-commit 框架**（hook 從固定版本的外部 repo 拉取，
>   且 `rev` 是固定的雜湊或標籤）
> - **不要執行來路不明的 repo 的 hooks**
>   （clone 陌生的 repo 後，先看看有沒有設定 `core.hooksPath`）

> [!danger] `git clone` 陌生 repo 的風險
> ```bash
> # ★ clone 本身通常是安全的，但之後的操作可能不是
> $ git clone https://github.com/unknown/repo.git
> $ cd repo
> $ ls .githooks/          # ← 先看看有沒有 hooks
> $ cat .git/config        # ← 看有沒有可疑的設定
> $ cat .gitattributes     # ← filter 可能執行指令
>
> # 特別注意：
> #   · core.fsmonitor 可以設定為執行任意指令
> #   · .gitattributes 的 filter 屬性
> #   · 建置腳本（package.json 的 scripts、Makefile）
> ```
>
> **在容器或隔離環境中檢視不信任的 repo。**

> [!tip] 用 hooks 強化安全（正面用途）
> ```bash
> # pre-commit：擋掉機密
> gitleaks protect --staged
>
> # pre-commit：擋掉私鑰
> git diff --cached --name-only | xargs -r grep -l "PRIVATE KEY" && exit 1
>
> # pre-push：擋掉推到正式分支
> [ "$branch" = "production" ] && exit 1
>
> # commit-msg：要求單號（稽核追溯）
> grep -qE '#[0-9]+' "$1" || { echo "訊息需包含單號"; exit 1; }
> ```

---

## 速查表

### stash

```bash
git stash push -m "訊息"        # ★ 一定要寫訊息
git stash -u                    # ★ 含未追蹤的檔案
git stash push -p               # 互動式挑選
git stash list
git stash show -p [stash@{n}]
git stash apply                 # ★ 較安全（保留 stash）
git stash pop                   # 取回並刪除
git stash branch <名> stash@{n} # 從 stash 建分支（衝突時好用）
git stash drop / clear
★ stash 是純本地的，不會推送到遠端
```

### worktree（比 stash 更好的多任務方案）

```bash
git worktree add ../dir <分支>
git worktree add -b <新分支> ../dir <起點>
git worktree add --detach ../dir <tag>
git worktree list
git worktree remove ../dir
git worktree prune

★ 共用同一個 .git，不佔兩倍空間
★ 同一分支不能被兩個 worktree 檢出
★ .env / node_modules 要自己準備
```

### bisect

```bash
git bisect start
git bisect bad [rev]            # 壞的
git bisect good <rev>           # 好的
# ...測試...  git bisect good / bad / skip
git bisect reset                # ★ 結束

# 自動化（腳本 exit 0=好, 1-127(除125)=壞, 125=跳過）
git bisect start HEAD v1.1.0
git bisect run /tmp/test.sh
```

### 常用 hooks

| Hook | 時機 | 用途 |
| --- | --- | --- |
| **pre-commit** | commit 前 | **機密掃描、語法驗證、大檔案** |
| **commit-msg** | 訊息寫完 | **格式檢查** |
| **pre-push** | push 前 | **擋受保護分支、跑測試** |
| post-merge | merge 後 | 自動安裝相依套件 |
| **post-receive** | 伺服器收到 push | **自動部署** |

### hooks 的版控問題

```
❌ .git/hooks/ 【不會進版控】→ 新成員沒有
✅ git config core.hooksPath .githooks   （要手動執行一次）
✅ 【pre-commit 框架】（.pre-commit-config.yaml 進版控）★ 推薦
★ hooks 可被 --no-verify 略過 → 【真正的強制在伺服器端】
```

### submodule

```bash
git clone --recurse-submodules <url>      # ★ 最常忘記
git submodule update --init --recursive   # 補救
git submodule update --remote <path>      # 更新到最新
git submodule foreach 'git pull'
git config --global submodule.recurse true

★ 替代方案：套件管理器 / monorepo / git subtree
```

### Git LFS

```bash
git lfs install
git lfs track "*.psd"
git add .gitattributes           # ★ 必須 commit
git lfs ls-files
GIT_LFS_SKIP_SMUDGE=1 git clone <url>    # 不下載 LFS 內容

★ 必須在 commit「之前」設定 track
★ 所有協作者與 CI 都要裝 git-lfs
```

### 排查技巧

| 目的 | 指令 |
| --- | --- |
| 找最大的檔案 | `git rev-list --objects --all \| git cat-file --batch-check=...` |
| repo 大小 | `git count-objects -vH` |
| **搜尋整個歷史** | `git grep "字串" $(git rev-list --all)` |
| **誰引入了這段** | `git log -S "內容"` |
| 檔案何時被刪 | `git log --diff-filter=D -- <path>` |
| 取回已刪的檔案 | `git show <提交>^:<path>` |
| 提交統計 | `git shortlog -sn` |
| **最常改的檔案** | `git log --pretty=format: --name-only \| sort \| uniq -c \| sort -rn` |

### 安全提醒

```
□ hooks 可被略過 → 【伺服器端才是強制】
□ 【hooks 的變更也要 code review】（否則是攻擊面）
□ clone 陌生 repo 後【先看 .githooks / .git/config / .gitattributes】
□ 在隔離環境檢視不信任的 repo
```

---

## 練習題

> [!question]- 練習 1：stash vs worktree
> 模擬「開發到一半要處理緊急事項」：
> 1. **用 stash 的做法**：改一半 → `git stash -u` → 切分支 → 修 → 切回 → `git stash pop`
> 2. **用 worktree 的做法**：`git worktree add -b hotfix ../proj-hotfix` → 在新目錄修
> 3. **比較兩者的體驗**：哪個比較不會出錯？
> 4. worktree 的新目錄缺少什麼？（提示：`.env`、`node_modules`）
> 5. `git worktree list` 與 `du -sh .git ../proj-hotfix/.git` —— 空間佔用如何？

> [!question]- 練習 2：用 bisect 找兇手
> 1. 建立一個 repo，做 20 個提交
> 2. 在**第 8 個提交**故意引入一個「bug」
>    （例如在檔案中寫入 `BROKEN`）
> 3. 寫一個測試腳本：`grep -q BROKEN file.txt && exit 1 || exit 0`
> 4. `git bisect start HEAD <第1個提交>`
> 5. **`git bisect run /tmp/test.sh`** —— 幾次就找到了？
> 6. `git bisect log` 看它測試了哪些提交
> 7. 手動再做一次（不用 run），體會二分法的過程

> [!question]- 練習 3：建立你的 pre-commit 防護
> 1. 安裝 gitleaks 與 pre-commit 框架
> 2. 建立 `.pre-commit-config.yaml`，至少包含：
>    - gitleaks（機密掃描）
>    - detect-private-key
>    - check-added-large-files
>    - check-merge-conflict
>    - conventional-pre-commit（訊息格式）
> 3. `pre-commit install && pre-commit install --hook-type commit-msg`
> 4. **測試**：
>    - 試著 commit 一個含 `AWS_SECRET_KEY=AKIA...` 的檔案
>    - 試著 commit 一個 2MB 的檔案
>    - 試著用 `update` 當 commit 訊息
> 5. **每一項都被擋下來了嗎？**
> 6. 試試 `git commit --no-verify` —— **會怎樣？這說明了什麼？**

---

## 小測驗

Q1. **`git stash` 的三個陷阱是什麼**？

Q2. **`git stash pop` 與 `apply` 的差別是什麼？建議用哪個**？

Q3. **worktree 相對於 stash 的優勢是什麼？它有哪三個限制**？

Q4. **`git bisect` 解決什麼問題？它的三個前提是什麼**？

Q5. bisect 自動化時，測試腳本的 exit code 各代表什麼？

Q6. **常用的五個 hooks 各在什麼時機觸發、有什麼用途**？

Q7. **`.git/hooks/` 的最大問題是什麼？有哪兩種解法**？

Q8. **為什麼說「hooks 是協助不是強制」？真正的強制應該在哪裡**？

Q9. **submodule 的五個常見陷阱是什麼**？

Q10. **hooks 本身為什麼也是攻擊面？clone 陌生 repo 前該檢查什麼**？

> [!question]- 測驗答案
> **Q1.** ①**`git stash` 預設不含未追蹤的檔案** ——
> 新建的檔案還會留在工作區，常導致「切換分支後看到不該存在的檔案」，
> 要用 **`git stash -u`**；
> ②**stash 是「一疊」，容易堆積** ——
> 三個月後看到 `WIP on main` 完全不知道是什麼，
> 對策是**一律用 `git stash push -m "訊息"`**；
> ③**stash 不會推送到遠端** ——
> 它是**純本地的**，重灌電腦就沒了，長期保存要用分支或提交。
>
> **Q2.** **`pop` = `apply` + `drop`**（套用成功就把 stash 刪掉）；
> **`apply` 只套用，stash 保留**。
> **建議用 `apply`**，尤其是不確定會不會有衝突時 ——
> 因為 `pop` 遇到衝突時雖然不會刪除 stash，
> 但如果此時處理不當容易搞混狀態；
> 用 `apply` 確認沒問題後再 `git stash drop` 比較安全。
>
> **Q3.** **優勢**：stash 只有一個工作目錄，切換時要收拾東西；
> **worktree 讓同一個 repo 有多個工作目錄，各自在不同的分支上**，
> 可以**完全不動到手上的工作**就去處理別的事。
> 而且所有 worktree **共用同一個 `.git`**，不佔兩倍空間。
> **三個限制**：①**同一個分支不能同時被兩個 worktree 檢出**；
> ②**每個 worktree 需要自己的 `node_modules` / `vendor`**
> （它們在 gitignore 中不會共用）；
> ③**`.env` 等被忽略的檔案要自己複製過去**。
>
> **Q4.** 它解決「**上個月還好好的，現在壞了，但中間有幾百個提交，
> 不知道是哪一個造成的**」——
> 用**二分法**，7～8 次測試就能從 200 個提交中找出兇手。
> **三個前提**：①**每個提交都要能執行／測試**
> （中間有一堆壞掉的提交會很痛苦，這也是「每個提交都應該可運作」的理由）；
> ②**問題要能穩定重現**（間歇性的問題無法用 bisect）；
> ③**測試要夠快**（每次 30 分鐘 × 8 次 = 4 小時）。
>
> **Q5.** **`exit 0`** = 這個版本是**好的（good）**；
> **`exit 1`～`127`（除了 125）** = 這個版本是**壞的（bad）**；
> **`exit 125`** = **無法測試，跳過（skip）**
> （例如這個提交編譯不過、設定檔語法錯誤）。
> 使用方式：`git bisect start HEAD <good-rev>` 之後
> `git bisect run /tmp/test.sh`。
>
> **Q6.** **`pre-commit`**（commit 前）——
> 機密掃描、格式檢查、語法驗證、擋大檔案；
> **`commit-msg`**（訊息寫完後）——檢查訊息格式；
> **`pre-push`**（push 前）——跑測試、阻止推到受保護分支；
> **`post-merge`**（merge 後）——自動安裝相依套件；
> **`post-receive`**（**伺服器端**收到 push 後）——**自動部署**。
>
> **Q7.** 最大的問題是 **`.git/hooks/` 不會進版控** ——
> 新成員 clone 之後**沒有任何 hooks**，
> 每個人的 hooks 可能不一樣，也無法統一維護。
> **兩種解法**：
> ①**`git config core.hooksPath .githooks`** ——
> 把 hooks 放在會進版控的目錄，但**每個人 clone 後要手動執行一次**；
> ②**pre-commit 框架** ——
> `.pre-commit-config.yaml` 進版控，
> 執行 `pre-commit install` 即可，且 hook 版本可統一管理（推薦）。
>
> **Q8.** 因為 **`git commit --no-verify` 與 `git push --no-verify`
> 可以直接略過所有本地 hooks** ——
> 任何人只要加一個參數就繞過了。
> **真正的強制必須在伺服器端**：
> **平台的分支保護與 Tag protection**、
> **CI 檢查**（PR 必須通過才能合併）、
> 自架 Git 時的 **`pre-receive` hook**（在伺服器上執行，無法略過）。
> 本地 hooks 的價值在於「**早期發現、方便開發者**」，
> 而不是「防止惡意行為」。
>
> **Q9.** ①**clone 後 submodule 目錄是空的**
> （忘了 `--recurse-submodules`）；
> ②**submodule 停在 detached HEAD**（這是正常的，它被固定在某個提交）；
> ③**忘記提交 submodule 的指標更新**
> （你更新了 submodule 但沒 commit 主 repo，別人拿到的還是舊版）；
> ④**CI/部署時忘記初始化**（建置失敗，找不到檔案）；
> ⑤**submodule 的 URL 用了 SSH，但 CI 只有 HTTPS 憑證**。
>
> **Q10.** 因為**如果攻擊者取得 repo 的寫入權，
> 他可以修改 `.githooks/pre-commit`（若團隊使用 `core.hooksPath`），
> 那麼所有開發者執行 `git commit` 時就會執行惡意程式碼**。
> 防護：**hooks 的變更也要經過 code review**；
> 用 pre-commit 框架（hook 從固定版本的外部 repo 拉取）。
> **clone 陌生 repo 前後該檢查**：
> `ls .githooks/`（有沒有 hooks）、
> `cat .git/config`（有沒有可疑設定，如 `core.fsmonitor` 可執行任意指令）、
> `cat .gitattributes`（`filter` 屬性可能執行指令）、
> 以及建置腳本（`package.json` 的 scripts、Makefile）。
> **最安全的做法是在容器或隔離環境中檢視不信任的 repo。**

---

## 延伸閱讀

- [[05-Git-回復與重寫歷史]] — reflog、filter-repo
- [[08-Git-伺服器端與自動部署]] — 伺服器端 hooks 與自動部署
- [[09-Git-團隊規範與實戰情境]] — 團隊規範與意外處理
- [[03-Git-分支與合併]] — rebase 與衝突處理
- [[10-機密管理與金鑰保護]] — 機密掃描與存放
- [[04-效能瓶頸排查方法論]] — 效能問題的系統化排查
