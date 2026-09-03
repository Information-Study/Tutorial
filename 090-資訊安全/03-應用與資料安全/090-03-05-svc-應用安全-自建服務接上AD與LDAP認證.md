---
title: "自建服務接上AD與LDAP認證"
desc: "讓 Wazuh、Grafana、PVE 與自建系統共用網域帳號，做到離職即停權"
aliases: [LDAP, AD認證, ldapsearch, Grafana LDAP, PVE Realm, 集中認證]
tags: [群組/資訊安全, 安全/應用資料, 主題/身分認證]
category: 資訊安全
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[030-01-02-01-guide-AD-AD概念與網域架構]]", "[[090-05-07-guide-資安設備-身分存取管理IAM與MFA]]", "[[090-03-01-guide-應用安全-TLS憑證與HTTPS實務]]"]
updated: 2026-09-03
---

# 自建服務接上AD與LDAP認證

> [!abstract] 這篇你會學到
> - ★★★★★ 為什麼「每套系統一組帳號」是**稽核最常開的缺失**，而集中認證是唯一可持續的解
> - 三種整合深度（**直接接 LDAP／AD**、**SSO**、**自架 IdP**）各自的代價與適用場景
> - LDAP 的基礎名詞：**DN／CN／OU／DC、bind DN、search base、filter**，只講到「能設定」的程度
> - ★★★★★ 一套**所有系統通用的五步整合流程**，學會一次就會全部
> - 用 `ldapsearch` 在命令列**先把連線與 filter 驗證出來**，再去碰任何系統的設定檔
> - **Grafana**、**Proxmox VE**、**自建 PHP 系統**的完整設定與驗證
> - ★★★★★ 為什麼**一定要走 LDAPS／STARTTLS**、bind 帳號為什麼**絕不能用 Domain Admin**
> - 離職流程的閉環：AD 停用之後，**已經登入的 session** 怎麼辦
> - 本機備援帳號：AD 掛掉的時候，你還進不進得去

## 前置知識

- [[030-01-02-01-guide-AD-AD概念與網域架構]] — 網域、OU、群組的基本結構
- [[030-01-02-03-guide-AD-使用者與群組管理AD]] — 建立服務帳號與安全群組
- [[090-05-07-guide-資安設備-身分存取管理IAM與MFA]] — IAM、SSO、MFA 的分工與帳號生命週期
- [[090-03-01-guide-應用安全-TLS憑證與HTTPS實務]] — LDAPS 憑證驗證會用到的觀念
- [[020-02-03-08-svc-標準化-集中式帳號整合SSSD與加入AD網域]] — 讓 **Linux 主機本身**吃 AD 帳號（本篇談的是**應用程式**吃 AD 帳號，兩者互補）
- [[020-01-09-cmd-Linux-使用者與群組管理]] — 本機帳號與群組的觀念

---

## 觀念說明

### ★★★★★ 先問一個問題：同仁離職，你確定每一套都停權了嗎

一個中型機關的資訊室，手上大概會有這些會登入的東西：

| 系統 | 帳號從哪來 | 誰在管 |
| --- | --- | --- |
| Windows 網域（AD） | AD | 人事異動單一到就處理 |
| Wazuh Dashboard | 系統內建帳號 | 建置的人自己記得 |
| Grafana | 系統內建帳號 | 誰要看就開一個 |
| Proxmox VE | `pve` realm 內建帳號 | 虛擬化負責人 |
| GitLab／Gitea | 系統內建帳號 | 開發窗口 |
| 自建的差勤／表單系統 | 資料庫裡的 `users` 表 | 廠商建的，沒人動過 |
| 網管交換器 | 本機帳號 | 網路負責人 |
| NAS | 本機帳號 | 誰要放檔案就開一個 |

同仁 A 離職那天，人事送異動單過來，你在 AD 上把帳號停用了。

**然後呢？**

- Wazuh 裡的 `alice` 還在，密碼還是那個。
- Grafana 裡的 `alice` 還在。
- PVE 裡的 `alice@pve` 還在，而且是 `PVEVMAdmin`。
- 自建系統的 `users` 表裡 `alice` 的 `is_active = 1`。

> [!danger] ★★★★★ 這就是稽核最常開的缺失
> 稽核委員的問法通常是這一句：
>
> > 「請提供近一年離職人員清單，並示範這些帳號在**各資訊系統**上已停用。」
>
> 「各資訊系統」四個字是重點。只證明 AD 停用了**不算過**。
> 而只要系統數量超過五套、負責人超過兩個，
> **靠人工逐一停權就一定會漏** —— 這不是紀律問題，是流程設計問題。
>
> 相關的稽核要求與佐證方式見 [[090-07-09-guide-資安實踐-資安稽核與符合性檢核]]。

### ★★★★★ 唯一可持續的解：讓帳號只有一份

把上面那張表改成這樣：

```text
              ┌──────────────────────────┐
              │   Active Directory       │  ← 帳號只存在這裡
              │   （唯一的真實來源）      │
              └────────────┬─────────────┘
                           │ LDAPS / 636
        ┌──────────┬───────┼───────┬──────────┐
        ▼          ▼       ▼       ▼          ▼
     Grafana    PVE     Wazuh   GitLab    自建系統
    （不存密碼）（不存密碼）（不存密碼）（不存密碼）（不存密碼）
```

**AD 停用 alice → 下一次 alice 想登入任何一套系統，bind 就失敗 → 全部進不去。**

一個動作，全面生效。這就是「離職即停權」真正能做到的方式。

> [!note] ★★★ 集中認證不等於集中授權
> LDAP 整合解決的是「**你是誰**」（Authentication）。
> 「**你能做什麼**」（Authorization）還是各系統自己決定 ——
> 只是判斷依據從「系統內建的角色欄位」換成了「**你在 AD 的哪個群組**」。
>
> 所以整合完之後，**AD 群組就變成了權限的控制面板**：
> 把 alice 從 `GG-Grafana-Admins` 移出去，她在 Grafana 就自動降級。

### 三種整合深度

不是所有情境都該用同一種做法。★★★★ 這張表是選型的核心：

| | 直接接 LDAP／AD | SSO（SAML／OIDC） | 自架 IdP（Keycloak 等） |
| --- | --- | --- | --- |
| **做法** | 每個系統各自填 AD 連線設定 | 系統轉址到 IdP 登入，拿 token 回來 | 先架一台 IdP，再讓系統接 IdP |
| **要不要另外架東西** | ★ **不用** | 要有 IdP（Entra ID、AD FS…） | ★★★★ 要，而且要自己養 |
| **使用者體驗** | 每套都要輸入一次帳密（帳密相同） | ★★★ 登入一次，處處通行 | 同 SSO |
| **能不能套 MFA** | ★★ 不行（除非系統自己支援） | ★★★★ **可以，MFA 在 IdP 上做一次** | 可以 |
| **密碼有沒有經過應用程式** | ★★★★ **有**（應用程式拿得到明文再去 bind） | ★★★★ **沒有**（只在 IdP 輸入） | 沒有 |
| **舊系統支不支援** | ★★★ 支援度最高，連老舊 PHP 系統都能接 | 要系統本身支援 SAML／OIDC | 同 SSO |
| **設定工作量** | 每套一次，N 套就 N 次 | 每套一次 + IdP 一次 | 每套一次 + IdP 建置與維運 |
| **適合誰** | ★★★★★ **機關內部系統，最常見的起點** | 已經有 Entra ID／AD FS 的環境 | 系統多到不適合逐一接 LDAP |

> [!tip] ★★★★ 機關的務實建議
> **先把「直接接 LDAP／AD」做完。**
>
> 它不需要新增任何伺服器、不需要新的授權、不需要改動 AD 架構，
> 而且**立刻就把「離職即停權」這個缺失補起來**。
>
> 等到系統數量真的多到讓你受不了（大概 15 套以上），
> 或者主管要求「所有系統都要 MFA」的時候，再往 SSO 走。
>
> 順序錯了會很痛：先花三個月架 IdP，結果一半的老系統根本不支援 OIDC，
> 最後還是要回頭一套一套接 LDAP。

> [!info]- ★★★ 自架 IdP（Keycloak）的代價 —— 想清楚再做
> Keycloak 是很好的開源 IdP，支援 SAML 2.0、OIDC、使用者聯邦（可以把 AD 當後端），
> 也能自己做 MFA、自訂登入頁、細緻的角色對應。
>
> 但是**架起來只是開始**，你同時買下了這些責任：
>
> | 責任 | 具體是什麼 |
> | --- | --- |
> | ★★★★★ **單點故障** | IdP 掛掉 = **所有接了它的系統全部無法登入**。比任何單一系統掛掉都嚴重 |
> | ★★★★★ **皇冠寶石** | 它握有所有系統的登入權。被打下來 = 全機關淪陷，攻擊價值遠高於任何一套業務系統 |
> | ★★★★ **高可用** | 為了不變成單點，要做叢集、要做資料庫 HA、要做負載平衡 |
> | ★★★★ **備份與還原** | Realm 設定、client secret、使用者聯邦設定都要備份，而且要**演練過還原** |
> | ★★★ **版本升級** | Keycloak 版本推進快，major 版本之間設定與 API 常有變動，升級要測 |
> | ★★★ **憑證管理** | IdP 的簽章憑證到期會讓所有 SSO 一起失效 |
>
> **判準**：如果你沒有人力承擔上面六項，就**不要自架 IdP**。
> 直接接 LDAP 雖然土，但它沒有單點故障 —— AD 掛掉的時候你本來就什麼都做不了了。
>
> 更完整的 SSO／IdP 討論見 [[090-05-07-guide-資安設備-身分存取管理IAM與MFA]]。

### ★★★ LDAP 基礎：只講到能設定的程度

LDAP（Lightweight Directory Access Protocol）是一個**目錄查詢協定**。
AD 是微軟的目錄服務，**對外就是講 LDAP**。所以「接 AD」跟「接 LDAP」設定起來幾乎一樣。

目錄長得像一棵樹，每個節點都有一個唯一的路徑，叫做 **DN（Distinguished Name）**：

```text
DC=example,DC=local                          ← 網域根（Domain Component）
├── OU=Users                                 ← 組織單位（Organizational Unit）
│   ├── OU=資訊室
│   │   └── CN=王小明                        ← 一個使用者物件（Common Name）
│   └── OU=人事室
├── OU=Groups
│   ├── CN=GG-Grafana-Admins                 ← 一個安全群組
│   └── CN=GG-PVE-Operators
└── OU=Service Accounts
    └── CN=svc-ldap-readonly                 ← 我們等下要用的唯讀 bind 帳號
```

王小明的完整 DN 是：

```text
CN=王小明,OU=資訊室,OU=Users,DC=example,DC=local
```

★★★ 讀法是**由內而外、由葉到根**，跟檔案路徑相反。

| 縮寫 | 全名 | 在 AD 裡代表 | 範例 |
| --- | --- | --- | --- |
| **DC** | Domain Component | 網域的一段。`example.local` = `DC=example,DC=local` | `DC=example,DC=local` |
| **OU** | Organizational Unit | 組織單位（可以套 GPO 的資料夾） | `OU=資訊室` |
| **CN** | Common Name | 物件本身的名字 | `CN=王小明` |
| **DN** | Distinguished Name | 完整路徑，全目錄唯一 | `CN=王小明,OU=Users,DC=example,DC=local` |

#### 設定畫面上一定會問你的四件事

| 欄位 | 意思 | ★ 常見值 |
| --- | --- | --- |
| **Server／Host** | 網域控制站的位址與埠 | `dc01.example.local:636` |
| ★★★★ **Bind DN + Bind Password** | 「我用誰的身分去問這個目錄」。**這是一個唯讀服務帳號，不是使用者自己的帳號** | `CN=svc-ldap-readonly,OU=Service Accounts,DC=example,DC=local` |
| ★★★ **Search Base（Base DN）** | 「從哪一層開始往下找」。**設太深會找不到人，設在根最保險** | `DC=example,DC=local` |
| ★★★★ **User Filter** | 「怎樣算是一個可以登入的使用者」 | `(sAMAccountName=%s)` |

> [!note] ★★★★ 為什麼需要 bind 帳號
> LDAP 目錄**不開放匿名查詢**（AD 預設就不開）。
> 系統要先「以某個身分登入目錄」才能查得到王小明的 DN，
> 查到之後**再用王小明的 DN 加上他輸入的密碼做第二次 bind** —— 這次 bind 成功，就代表密碼正確。
>
> 所以完整的驗證流程是**兩次 bind**：
>
> ```text
> 1. 系統 → 用 svc-ldap-readonly bind → 成功
> 2. 系統 → 查 (sAMAccountName=alice) → 得到 CN=王小明,OU=...,DC=example,DC=local
> 3. 系統 → 用那個 DN + 使用者剛剛輸入的密碼 bind → 成功 = 密碼正確
> 4. 系統 → 讀 memberOf → 決定給什麼角色
> ```
>
> 看懂這四步，後面所有系統的設定畫面你都看得懂了。

#### AD 常用屬性

| 屬性 | 內容 | 用途 |
| --- | --- | --- |
| ★★★★ `sAMAccountName` | `alice`（登入名，不含網域） | **最常拿來當使用者名稱** |
| `userPrincipalName` | `alice@example.local` | UPN 格式登入，也常用 |
| `cn` | `王小明` | 顯示名稱（AD 裡常是中文） |
| `displayName` | `王小明` | 顯示名稱 |
| `givenName` / `sn` | 名 / 姓 | 拆開的姓名 |
| `mail` | `alice@example.gov.tw` | 告警通知會用到 |
| ★★★★ `memberOf` | 這個人所屬群組的 DN 清單 | **角色對應的依據** |
| ★★★ `userAccountControl` | 帳號旗標的位元集合 | 判斷帳號是否已停用 |
| `distinguishedName` | 自己的 DN | — |

#### ★★★★ 群組成員資格的兩種表達方式

這是換系統時最容易踩到的坑：**同一件事，目錄有兩種記法。**

| 記法 | 意思 | 誰在用 | 設定時怎麼填 |
| --- | --- | --- | --- |
| ★★★★ **`memberOf`（從人看群組）** | 使用者物件上有一個 `memberOf` 屬性，列出他屬於哪些群組 | **AD 預設就有**；OpenLDAP 要載入 `memberof` overlay | 只要指定 `member_of = "memberOf"`，不需要另外搜群組 |
| ★★★ **`member`（從群組看人）** | 群組物件上有 `member` 屬性，列出成員的 DN | 傳統 OpenLDAP、部分目錄服務 | 要另外設定 **group search base 與 group filter**，讓系統反查 |

> [!warning] ★★★ 為什麼你會在設定檔裡同時看到兩組欄位
> 以 Grafana 為例，`ldap.toml` 同時有 `member_of` 與 `group_search_filter` 兩套機制：
>
> - 接 **AD** → 用 `member_of = "memberOf"` 就好，**不要**填 group search 那一組。
> - 接 **沒有 memberof overlay 的 OpenLDAP** → `memberOf` 是空的，
>   必須改用 `group_search_base_dns` + `group_search_filter` 讓 Grafana 反查。
>
> 「使用者找得到、群組永遠對不上」十次有八次是這裡搞混了。

> [!tip] ★★★ AD 的兩個特殊比對 OID
> AD 支援兩個很實用的擴充比對規則，寫在 filter 裡：
>
> | OID | 作用 | 範例 |
> | --- | --- | --- |
> | `1.2.840.113556.1.4.803` | 位元 AND。用來測 `userAccountControl` 的旗標 | `(!(userAccountControl:1.2.840.113556.1.4.803:=2))` = **排除已停用帳號** |
> | `1.2.840.113556.1.4.1941` | 鏈式比對（LDAP_MATCHING_RULE_IN_CHAIN） | `(memberOf:1.2.840.113556.1.4.1941:=CN=GG-All,OU=Groups,DC=example,DC=local)` = **含巢狀群組**的成員 |
>
> 第二個很重要：★★★★ **`memberOf` 預設不含巢狀群組**。
> 如果 alice 在 `GG-資訊室`，而 `GG-資訊室` 是 `GG-Grafana-Admins` 的成員，
> 用一般的 `(memberOf=CN=GG-Grafana-Admins,...)` 是**找不到 alice 的**。
>
> 這兩個 OID 只有 AD 支援，OpenLDAP 沒有。

### AD／LDAP 的連接埠

| 埠 | 協定 | 加密 | 用途 |
| --- | --- | --- | --- |
| 389 | LDAP | ★★★★★ **明文**（除非用 STARTTLS 升級） | 一般查詢 |
| 389 | LDAP + STARTTLS | ★★★★ 有（先明文連線再升級） | 一般查詢，較新的做法 |
| ★★★★ **636** | LDAPS | ★★★★ **有**（連線一開始就是 TLS） | 一般查詢，**本篇主線** |
| 3268 | Global Catalog | 明文 | 跨網域查詢（多網域樹系才需要） |
| ★★★ 3269 | Global Catalog over SSL | 有 | 跨網域查詢，加密版 |

> [!danger] ★★★★★ 389 明文 LDAP 等於把網域密碼送上網路
> 用 389 且沒有 STARTTLS 的時候：
>
> - bind 帳號的密碼是**明文**在網路上傳。
> - **使用者輸入的網域密碼也是明文**（第二次 bind）。
>
> 在同一個 VLAN 上抓包就全部拿到了 —— 而且拿到的是**網域密碼**，
> 不是某一套系統的密碼。一個抓包就等於拿到 AD 帳號。
>
> **本篇所有範例一律使用 636（LDAPS）或 389 + STARTTLS，沒有例外。**

---

## 安裝或基礎操作

### ★★★★★ 通用五步流程：學會一次就會全部

不管你要接的是 Grafana、PVE、Wazuh、GitLab 還是廠商寫的 PHP 系統，
流程都是**同樣這五步**。設定畫面長得不一樣，要填的東西完全一樣。

```text
第 1 步  取得連線資訊與一個唯讀 bind 帳號
   ↓
第 2 步  ★★★★★ 用 ldapsearch 在命令列驗證（跳過這步，後面每個系統都在瞎猜）
   ↓
第 3 步  在系統裡設定 server / base DN / bind DN / bind password
   ↓
第 4 步  設定使用者 filter 與屬性對應（username / email / name）
   ↓
第 5 步  設定群組對應到系統角色
```

### 第 1 步：跟 AD 管理員要什麼

★★★ 用這張表去要，一次要齊，不要來回三趟：

| 要的東西 | 範例值 | 備註 |
| --- | --- | --- |
| 網域名稱（FQDN） | `example.local` | |
| DC 主機名稱（至少兩台） | `dc01.example.local`、`dc02.example.local` | ★★★ 要兩台，單台是單點 |
| DC 的 IP | `10.10.1.11`、`10.10.1.12` | 用來排查 DNS 問題 |
| LDAPS 埠 | `636` | ★★★★ 確認 DC 上**真的有開**（見下方） |
| Base DN | `DC=example,DC=local` | |
| ★★★★ 唯讀 bind 帳號 DN | `CN=svc-ldap-readonly,OU=Service Accounts,DC=example,DC=local` | **專用、唯讀、非 Domain Admin** |
| bind 密碼 | （另外用安全管道給） | 見 [[090-03-03-guide-應用安全-機密管理與金鑰保護]] |
| ★★★★ DC 憑證的簽發 CA 憑證 | `enterprise-root-ca.crt` | 驗證 LDAPS 用，見 [[090-01-09-guide-PKI-根憑證派送與信任]] |
| 要用的群組 DN | `CN=GG-Grafana-Admins,OU=Groups,DC=example,DC=local` | 每個系統各一組 |

> [!tip] ★★★★ 建立 bind 帳號的規格（給 AD 管理員的說明）
> 在 AD 上建立這個帳號時：
>
> - 放在 `OU=Service Accounts`，跟一般使用者分開，方便盤點。
> - **不加入任何權限群組**。`Domain Users` 預設就有讀取目錄的權限，**這樣就夠了**。
> - 勾選「密碼永久有效」，但**登記在密碼輪替清冊裡**，一年換一次。
> - 描述欄寫清楚：`LDAP 唯讀查詢用 / 供 Grafana,PVE,Wazuh / 資訊室 分機1234`。
> - ★★★ 帳號名稱用 `svc-` 開頭，一眼看得出是服務帳號。
>
> AD 端的帳號建立步驟見 [[030-01-02-03-guide-AD-使用者與群組管理AD]]。

### 第 2 步：★★★★★ 用 ldapsearch 先驗證

**這一步是整篇最重要的一步。**

在你去動 Grafana 或 PVE 的設定檔之前，先在命令列上把「連得上、bind 得了、找得到人、看得到群組」
四件事一項一項確認完。這樣做的理由很簡單：

> [!danger] ★★★★★ 跳過 ldapsearch 的下場
> Grafana 登入失敗只會給你一句 `Invalid username or password`。
> 它**不會告訴你**是：DNS 解不到 DC、防火牆擋 636、憑證不被信任、
> bind 密碼錯、base DN 太深、filter 寫錯、還是使用者真的打錯密碼。
>
> 七種可能，一個訊息。你會在設定檔上盲改一整個下午。
>
> `ldapsearch` 每一種錯誤都給你**不同的、明確的**訊息。
> **先在命令列把它跑通，再去填任何設定檔。**

#### 安裝

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install -y ldap-utils
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> sudo dnf install -y openldap-clients
> ```
> 指令與參數完全相同，只是套件名不一樣。

驗證安裝：

```bash
ldapsearch -VV
```

預期輸出（版本號會不同）：

```text
ldapsearch: @(#) $OpenLDAP: ldapsearch 2.5.18 (Jun 27 2024 00:00:00) $
        (LDAP library: OpenLDAP 20518)
```

#### 2-1 先確認 DNS 與埠通

```bash
# DC 名稱解得到嗎
dig +short dc01.example.local
```

```text
10.10.1.11
```

```bash
# 636 通不通（3 秒逾時，避免卡住）
timeout 3 bash -c 'cat < /dev/null > /dev/tcp/dc01.example.local/636' && echo "636 OK" || echo "636 不通"
```

```text
636 OK
```

★★★ 如果 DNS 解不到，先看 [[060-01-04-06-guide-dig-與DNS排查]]；
如果埠不通，那是防火牆或 DC 上沒有啟用 LDAPS，**不要往下做**。

#### 2-2 ★★★★ 檢查 DC 的 LDAPS 憑證

```bash
openssl s_client -connect dc01.example.local:636 -showcerts </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
```

預期輸出：

```text
subject=CN = dc01.example.local
issuer=DC = local, DC = example, CN = example-CA
notBefore=Jan 15 08:12:33 2026 GMT
notAfter=Jan 15 08:12:33 2027 GMT
X509v3 Subject Alternative Name:
    DNS:dc01.example.local
```

★★★★ 三件事要看：

1. `subject` 或 SAN 裡**必須有你連線用的那個名稱**（`dc01.example.local`）。
   如果你用 IP 連，SAN 裡沒有那個 IP，憑證驗證一定失敗。
2. `notAfter` **還沒到期**。DC 憑證過期會讓所有系統的 LDAPS 一起壞掉。
3. `issuer` 是哪一家 CA —— 那家的根憑證要裝進你的機器信任區。

憑證檢視與格式轉換的細節見 [[090-01-11-guide-PKI-憑證格式轉換與檢視工具]]。

#### 2-3 讓本機信任企業 CA

```bash
# 把 AD 企業 CA 的根憑證放進系統信任區（Ubuntu / Debian）
sudo cp enterprise-root-ca.crt /usr/local/share/ca-certificates/example-ca.crt
sudo update-ca-certificates
```

```text
Updating certificates in /etc/ssl/certs...
1 added, 0 removed; done.
Running hooks in /etc/ca-certificates/update.d...
done.
```

★★★ 再設定 OpenLDAP 客戶端要用哪個 CA 檔（`/etc/ldap/ldap.conf`）：

```ini
# /etc/ldap/ldap.conf
TLS_CACERT  /etc/ssl/certs/ca-certificates.crt
TLS_REQCERT demand
```

`TLS_REQCERT demand` 代表**憑證驗不過就拒絕連線**，這是正確的設定。

> [!danger] ★★★★★ 不要用 `TLS_REQCERT never` 當作解法
> 網路上一堆文章教你憑證有問題就設 `TLS_REQCERT never` 或 `allow`。
> 那等於**關掉憑證驗證** —— 加密還在，但你不知道對面是不是真的 DC，
> 中間人可以直接冒充 DC 收下你的網域密碼。
>
> 憑證驗不過，正確的做法是**把 CA 裝好**或**把連線名稱改成憑證上有的那個**。
> 只有在**臨時排查**的時候可以用 `-o TLS_REQCERT=never` 加在單一次指令上，
> 確認完馬上改回來，**絕不寫進設定檔**。

#### 2-4 ★★★★★ 測試 bind

```bash
ldapsearch -x -LLL \
  -H ldaps://dc01.example.local:636 \
  -D "CN=svc-ldap-readonly,OU=Service Accounts,DC=example,DC=local" \
  -W \
  -b "DC=example,DC=local" \
  -s base "(objectClass=*)" defaultNamingContext
```

參數逐一說明：

| 參數 | 意思 |
| --- | --- |
| `-x` | 用 simple 認證（不用 SASL／Kerberos） |
| `-LLL` | 輸出乾淨的 LDIF，不要註解與版本行 |
| `-H` | 伺服器 URI。`ldaps://` = 636 加密；`ldap://` = 389 |
| ★★★★ `-D` | **bind DN** |
| ★★★★ `-W` | **互動式輸入密碼**（用 `-w 密碼` 會留在 shell history，不要用） |
| `-b` | search base |
| `-s base` | 搜尋範圍只看 base 這一個節點本身（`base` / `one` / `sub`，預設 `sub`） |

輸入密碼後，預期輸出：

```text
Enter LDAP Password:
dn:
defaultNamingContext: DC=example,DC=local
```

★★★★ 看到 `defaultNamingContext` 就代表：**DNS 通了、TLS 建立了、憑證驗過了、bind 成功了**。
四關一次過。

> [!warning] ★★★ 用 STARTTLS 的寫法
> 如果環境只開 389 + STARTTLS，把 `-H` 換成 `ldap://` 並加上 `-ZZ`：
>
> ```bash
> ldapsearch -x -LLL -ZZ -H ldap://dc01.example.local:389 \
>   -D "CN=svc-ldap-readonly,OU=Service Accounts,DC=example,DC=local" -W \
>   -b "DC=example,DC=local" -s base "(objectClass=*)" defaultNamingContext
> ```
>
> ★★★★ `-ZZ`（大寫兩個 Z）代表「**STARTTLS 一定要成功，失敗就中止**」。
> 小寫或單一個 `-Z` 是「試著升級，失敗就用明文繼續」—— **不要用單一個 `-Z`**。

#### 2-5 ★★★★★ 把 filter 調到剛好

先找一個人：

```bash
ldapsearch -x -LLL \
  -H ldaps://dc01.example.local:636 \
  -D "CN=svc-ldap-readonly,OU=Service Accounts,DC=example,DC=local" -W \
  -b "DC=example,DC=local" \
  "(sAMAccountName=alice)" \
  dn sAMAccountName userPrincipalName mail displayName memberOf
```

預期輸出：

```text
Enter LDAP Password:
dn: CN=王小明,OU=資訊室,OU=Users,DC=example,DC=local
sAMAccountName: alice
userPrincipalName: alice@example.local
mail: alice@example.gov.tw
displayName: 王小明
memberOf: CN=GG-Grafana-Admins,OU=Groups,DC=example,DC=local
memberOf: CN=GG-PVE-Operators,OU=Groups,DC=example,DC=local
memberOf: CN=Domain Users,CN=Users,DC=example,DC=local
```

★★★★★ **這一段輸出就是你後面所有設定檔要填的內容來源**：

- `dn` 的尾巴 → 你的 base DN 可以設多深
- `sAMAccountName` → username 屬性
- `mail` → email 屬性
- `displayName` → 顯示名稱屬性
- `memberOf` 那幾行 → **群組對應要填的 DN，直接複製貼上，不要自己打**

> [!tip] ★★★★ 群組 DN 一定要複製，不要手打
> `CN=GG-Grafana-Admins,OU=Groups,DC=example,DC=local`
> 跟
> `CN=GG-Grafana-Admins,OU=Group,DC=example,DC=local`
> 只差一個 `s`，設定檔不會報錯，登入也會成功，
> **只是永遠對應不到 Admin 角色**。這是「群組對應沒生效」排名第一的原因。

#### 2-6 常用 filter 寫法

| 目的 | Filter |
| --- | --- |
| 找一個人（登入用） | `(sAMAccountName=alice)` |
| 用 UPN 找 | `(userPrincipalName=alice@example.local)` |
| ★★★ 只找「使用者」不找電腦 | `(&(objectClass=user)(objectCategory=person)(sAMAccountName=alice))` |
| ★★★★ **排除已停用的帳號** | `(&(objectCategory=person)(!(userAccountControl:1.2.840.113556.1.4.803:=2))(sAMAccountName=alice))` |
| 某個群組的直接成員 | `(memberOf=CN=GG-Grafana-Admins,OU=Groups,DC=example,DC=local)` |
| ★★★★ 某個群組的成員（**含巢狀**） | `(memberOf:1.2.840.113556.1.4.1941:=CN=GG-Grafana-Admins,OU=Groups,DC=example,DC=local)` |
| 列出某個 OU 底下所有人 | `-b "OU=資訊室,OU=Users,DC=example,DC=local" "(objectCategory=person)"` |

★★★ filter 語法是**前綴式**：`(&(A)(B))` 是 A AND B、`(|(A)(B))` 是 A OR B、`(!(A))` 是 NOT A。

驗證「排除停用帳號」真的有效（★★★★ 這一招之後會用到）：

```bash
# 找一個已知已停用的帳號，加上排除條件之後應該找不到
ldapsearch -x -LLL -H ldaps://dc01.example.local:636 \
  -D "CN=svc-ldap-readonly,OU=Service Accounts,DC=example,DC=local" -W \
  -b "DC=example,DC=local" \
  "(&(sAMAccountName=bob)(!(userAccountControl:1.2.840.113556.1.4.803:=2)))" dn
```

如果 bob 已停用，預期輸出是**空的**（只有密碼提示，沒有任何 `dn:` 行）。

#### 2-7 ★★★★ 最後：模擬使用者自己 bind

```bash
# 用「使用者的 DN + 使用者的密碼」bind，這就是系統驗證密碼的方式
ldapsearch -x -LLL -H ldaps://dc01.example.local:636 \
  -D "CN=王小明,OU=資訊室,OU=Users,DC=example,DC=local" -W \
  -b "DC=example,DC=local" -s base "(objectClass=*)" dn
```

密碼正確：

```text
Enter LDAP Password:
dn: DC=example,DC=local
```

密碼錯誤：

```text
Enter LDAP Password:
ldap_bind: Invalid credentials (49)
        additional info: 80090308: LdapErr: DSID-0C09056A, comment:
        AcceptSecurityContext error, data 52e, v4563
```

> [!tip] ★★★★★ AD 的錯誤碼 `data XXX` 是排錯神器
> `Invalid credentials (49)` 後面那串 `data 52e` 才是真正的原因。
> 常見的幾個：
>
> | 代碼 | 意思 |
> | --- | --- |
> | `data 525` | 使用者不存在 |
> | ★★★★ `data 52e` | **帳號存在，密碼錯誤** |
> | `data 530` | 不在允許的登入時段 |
> | `data 531` | 不在允許登入的工作站 |
> | `data 532` | ★★★ **密碼過期** |
> | ★★★★ `data 533` | **帳號已停用** ← 離職停權之後就是看到這個 |
> | `data 701` | 帳號已到期 |
> | ★★★ `data 773` | **使用者必須變更密碼**（下次登入需變更密碼被勾選） |
> | `data 775` | 帳號被鎖定 |
>
> 看到 `data 533` 代表你的停權真的生效了。這在驗收離職流程時很好用。

---

## 進階應用

### 範例一：Grafana 接上 AD

Grafana 的 LDAP 設定分成兩個檔案：`grafana.ini` 開開關，`ldap.toml` 放細節。

#### 3-1 開啟 LDAP 驗證

編輯 `/etc/grafana/grafana.ini`：

```ini
[auth.ldap]
enabled = true
config_file = /etc/grafana/ldap.toml
# ★★★ allow_sign_up = true 代表「AD 驗證通過的人，Grafana 沒有這個帳號就自動建立」
# 設成 false 的話，使用者必須先在 Grafana 裡存在才能登入
allow_sign_up = true
```

同時★★★★ 建議把本機登入表單留著（備援帳號要用）：

```ini
[auth]
disable_login_form = false
```

#### 3-2 `ldap.toml` 完整設定

```toml
# /etc/grafana/ldap.toml

[[servers]]
# ★★★ 兩台 DC 用空白分隔，Grafana 會依序嘗試
host = "dc01.example.local dc02.example.local"
port = 636
use_ssl = true
start_tls = false
# ★★★★★ 一定要 false。true 等於不驗證 DC 憑證
ssl_skip_verify = false
root_ca_cert = "/etc/ssl/certs/ca-certificates.crt"

# ★★★★ 唯讀 bind 帳號
bind_dn = "CN=svc-ldap-readonly,OU=Service Accounts,DC=example,DC=local"
bind_password = "換成真正的密碼"

# ★★★★ %s 會被替換成使用者輸入的登入名
# 這裡順便排除已停用帳號，讓停權立刻生效
search_filter = "(&(objectCategory=person)(sAMAccountName=%s)(!(userAccountControl:1.2.840.113556.1.4.803:=2)))"
search_base_dns = ["DC=example,DC=local"]

# 屬性對應：左邊是 Grafana 的欄位，右邊是 AD 的屬性名
[servers.attributes]
name     = "givenName"
surname  = "sn"
username = "sAMAccountName"
member_of = "memberOf"
email    = "mail"

# ★★★★ 群組對應：由上而下比對，第一個命中就採用，所以順序很重要
[[servers.group_mappings]]
group_dn = "CN=GG-Grafana-Admins,OU=Groups,DC=example,DC=local"
org_role = "Admin"
grafana_admin = true

[[servers.group_mappings]]
group_dn = "CN=GG-Grafana-Editors,OU=Groups,DC=example,DC=local"
org_role = "Editor"

# ★★★ 萬用比對放最後：不在上面任何群組的人只給 Viewer
[[servers.group_mappings]]
group_dn = "*"
org_role = "Viewer"
```

★★★★ 三個必踩的重點：

| 項目 | 說明 |
| --- | --- |
| `search_filter` 裡的 `%s` | Grafana 用 `%s` 當使用者輸入的佔位符，**不是 `{0}` 也不是 `%u`** |
| `group_mappings` 的順序 | **由上而下，第一個命中就停**。`group_dn = "*"` 一定放最後，放前面會讓所有人變 Viewer |
| `org_role` 的值 | 只能是 `Admin` / `Editor` / `Viewer`（以及較新版本的 `None`），大小寫要對 |

#### 3-3 保護設定檔權限

★★★★ `ldap.toml` 裡有明文的 bind 密碼：

```bash
sudo chown root:grafana /etc/grafana/ldap.toml
sudo chmod 640 /etc/grafana/ldap.toml
ls -l /etc/grafana/ldap.toml
```

```text
-rw-r----- 1 root grafana 1284 Sep  3 10:22 /etc/grafana/ldap.toml
```

> [!tip] ★★★ 不想把密碼寫死在檔案裡
> Grafana 支援用環境變數插值：把 `bind_password` 寫成 `"$__env{GF_LDAP_BIND_PW}"`，
> 再用 systemd drop-in 或 `EnvironmentFile` 帶入。
> 機密管理的做法見 [[090-03-03-guide-應用安全-機密管理與金鑰保護]]。

#### 3-4 套用與驗證

```bash
sudo systemctl restart grafana-server
sudo systemctl is-active grafana-server
```

```text
active
```

★★★★ Grafana 有內建的 LDAP 偵錯頁，這是驗證的最好工具：

> 用**本機 admin 帳號**登入 → 左側 **Administration → Authentication → LDAP**
> （或直接開 `https://grafana.example.local/admin/ldap`）
> → 在 **Test user mapping** 輸入 `alice` → **Run**

它會直接把「找到的 DN、抓到的屬性、命中了哪一條 group mapping、最後得到什麼角色」全部列出來。
★★★★★ **這一頁比任何 log 都好用**，因為它不需要使用者密碼就能測出屬性與群組對應。

看不夠的話，把日誌調成 debug：

```ini
[log]
level = debug
```

```bash
sudo systemctl restart grafana-server
sudo tail -f /var/log/grafana/grafana.log | grep -i ldap
```

排查完記得改回 `level = info`（★★★ debug 會把大量目錄查詢內容寫進日誌）。

> [!warning] ★★★ LDAP 背景同步是 Enterprise 功能
> Grafana OSS 版的 LDAP 群組對應是**在使用者登入時才重新計算**的。
> 「使用者已經登入著，我把他從 AD 群組移除，他的角色會不會馬上降級？」
> —— **不會**，要等他下次登入。
>
> 定時把 LDAP 群組同步回 Grafana 的 `active_sync_enabled` / `sync_cron`
> 屬於 Grafana Enterprise。OSS 版請改用 session 逾時來縮短暴露時間（見下方「離職閉環」）。

Grafana 本身的操作見 [[100-01-09-guide-Grafana-儀表板與Alertmanager通知]]。

### 範例二：Proxmox VE 接上 AD

PVE 的概念是 **Realm（認證領域）**：一個 realm 就是一個帳號來源。
PVE 內建兩個 realm：`pam`（Linux 本機帳號）與 `pve`（PVE 自己的帳號資料庫）。
我們要加第三個：`ad-example`。

#### 4-1 GUI 設定（★★★★ 建議走這條）

> **Datacenter → Permissions → Realms → Add → Active Directory Server**
>
> | 欄位 | 填入 |
> | --- | --- |
> | Realm | `ad-example` |
> | Domain | `example.local` |
> | Server | `dc01.example.local` |
> | Fallback Server | `dc02.example.local` |
> | Mode | ★★★★ `LDAPS`（或 `STARTTLS`），**不要選 `LDAP`** |
> | Port | `636` |
> | ★★★★ Verify Certificate | **勾選** |
> | Default | 不勾（★★★★ 見下方 danger） |
>
> **Sync Options** 分頁：
>
> | 欄位 | 填入 |
> | --- | --- |
> | Bind User | `CN=svc-ldap-readonly,OU=Service Accounts,DC=example,DC=local` |
> | Bind Password | （bind 密碼） |
> | Base DN | `DC=example,DC=local` |
> | User Attribute | `sAMAccountName` |
> | Scope | `users` 或 `both` |

★★★★ 勾了 Verify Certificate 之後，PVE 必須信任 DC 憑證的 CA。
把企業 CA 的根憑證放進 PVE 的信任區：

```bash
# 在每一台 PVE 節點上執行
cp enterprise-root-ca.crt /usr/local/share/ca-certificates/example-ca.crt
update-ca-certificates
```

```text
Updating certificates in /etc/ssl/certs...
1 added, 0 removed; done.
```

#### 4-2 CLI 設定

```bash
pveum realm add ad-example \
  --type ad \
  --domain example.local \
  --server1 dc01.example.local \
  --server2 dc02.example.local \
  --port 636 \
  --mode ldaps \
  --base-dn "DC=example,DC=local" \
  --bind-dn "CN=svc-ldap-readonly,OU=Service Accounts,DC=example,DC=local" \
  --user-attr sAMAccountName \
  --comment "AD 網域認證（唯讀 bind）"
```

bind 密碼另外設定（★★★ 不放在指令列，避免進入 shell history）：

```bash
pveum realm modify ad-example --password
```

檢視結果：

```bash
pveum realm list
```

```text
┌────────────┬──────┬─────────┬──────────────────────────────┐
│ realm      │ type │ comment │ ...                          │
├────────────┼──────┼─────────┼──────────────────────────────┤
│ ad-example │ ad   │ AD 網域認證（唯讀 bind）              │
│ pam        │ pam  │ Linux PAM standard authentication    │
│ pve        │ pve  │ Proxmox VE authentication server     │
└────────────┴──────┴─────────┴──────────────────────────────┘
```

> [!warning] ★★★ 未實機驗證
> `pveum realm add` 的旗標在 PVE 版本之間有調整過
> （例如 `--secure` 與較新的 `--mode` 並存、同步旗標在 PVE 7 與 8 之間改過名）。
> **以你手上那台的 `pveum realm add --help` 為準**：
>
> ```bash
> pveum realm add --help
> pveum realm sync --help
> ```
>
> 上面的 GUI 欄位表在各版本是一致的，所以**不確定的話走 GUI**。

#### 4-3 同步使用者與群組

```bash
# 先做一次不寫入的預覽（dry run）
pveum realm sync ad-example --dry-run 1
```

確認清單沒問題再真的同步：

```bash
pveum realm sync ad-example --scope both --enable-new 0
```

★★★★ `--enable-new 0` 的意思是「**同步進來的新帳號預設是停用的**」。
這很重要：你不會希望整個網域幾百個帳號一次全部變成 PVE 的可登入帳號。
同步進來之後，你**只手動啟用該給權限的那幾個**。

檢視同步結果：

```bash
pveum user list --enabled 1
```

#### 4-4 給權限

PVE 的權限是 `路徑 + 群組／使用者 + 角色` 三件一組。

```bash
# 把 AD 同步進來的群組指派為整個 Datacenter 的管理員
pveum acl modify / --group 'GG-PVE-Admins-ad-example' --role Administrator

# 只給某個 Pool 的虛擬機操作權
pveum acl modify /pool/資訊室 --group 'GG-PVE-Operators-ad-example' --role PVEVMAdmin

# 檢視
pveum acl list
```

> [!warning] ★★★ 同步進來的群組名稱格式
> PVE 同步 LDAP 群組時，群組名稱會**加上 realm 後綴**（`<群組名>-<realm>`）。
> 實際名稱請用 `pveum group list` 確認再貼進 `pveum acl modify`，**不要憑記憶打**。
>
> PVE 權限模型、角色清單與 API Token 的細節見 [[050-01-03-08-guide-PVE-使用者權限與API]]。

#### 4-5 登入測試

登入頁的 **Realm** 下拉選單選 `ad-example`，帳號輸入 `alice`（不用打網域），密碼是網域密碼。

★★★★ 登入失敗時，看 PVE 的認證日誌：

```bash
journalctl -u pvedaemon -n 50 --no-pager | grep -i auth
```

```text
Sep 03 10:44:12 pve01 pvedaemon[1234]: authentication failure; rhost=10.10.5.20
  user=alice@ad-example msg=Invalid credentials
```

### 範例三：★★★ 自建 PHP 系統的通用做法

廠商寫的、或自己維護的老系統，通常帳號是存在資料庫的 `users` 表裡。
改成吃 AD 其實只要動**驗證那一段**，其他都不用改。

#### 5-1 安裝 PHP LDAP 擴充

```bash
sudo apt install -y php8.3-ldap
php -m | grep -i ldap
```

```text
ldap
```

```bash
sudo systemctl reload php8.3-fpm
```

PHP-FPM 的設定見 [[060-03-01-02-guide-PHP-FPM設定與Pool調校]]。

#### 5-2 ★★★★ 驗證函式

```php
<?php
/**
 * 以 AD 驗證帳號密碼，成功回傳使用者屬性陣列，失敗回傳 null。
 */
function ad_authenticate(string $username, string $password): ?array
{
    // ★★★★★ 第一道防線：空密碼一定要擋。
    // LDAP 規格允許「unauthenticated bind」—— 給了 DN 但密碼是空字串時，
    // 伺服器會回傳「成功」，但那代表匿名連線，不代表密碼正確。
    // 少了這三行，任何人輸入任意帳號 + 空密碼就登入成功。
    if ($password === '' || $username === '') {
        return null;
    }

    $host     = 'ldaps://dc01.example.local:636';
    $baseDn   = 'DC=example,DC=local';
    $bindDn   = 'CN=svc-ldap-readonly,OU=Service Accounts,DC=example,DC=local';
    $bindPw   = getenv('AD_BIND_PASSWORD');   // ★★★ 不要寫死在原始碼

    $ds = ldap_connect($host);
    if ($ds === false) {
        return null;
    }
    ldap_set_option($ds, LDAP_OPT_PROTOCOL_VERSION, 3);
    // ★★★ AD 會回傳 referral，不關掉的話搜尋常常拿不到結果
    ldap_set_option($ds, LDAP_OPT_REFERRALS, 0);
    ldap_set_option($ds, LDAP_OPT_NETWORK_TIMEOUT, 5);

    // 第一次 bind：用唯讀服務帳號
    if (!@ldap_bind($ds, $bindDn, $bindPw)) {
        error_log('AD bind 失敗：' . ldap_error($ds));
        ldap_unbind($ds);
        return null;
    }

    // ★★★★★ 一定要跳脫使用者輸入，否則是 LDAP injection
    // 例如有人輸入 alice)(objectClass=* 就能改寫整個 filter
    $safe   = ldap_escape($username, '', LDAP_ESCAPE_FILTER);
    $filter = "(&(objectCategory=person)(sAMAccountName={$safe})"
            . "(!(userAccountControl:1.2.840.113556.1.4.803:=2)))";

    $res = ldap_search($ds, $baseDn, $filter,
        ['dn', 'samaccountname', 'displayname', 'mail', 'memberof']);
    if ($res === false || ldap_count_entries($ds, $res) !== 1) {
        ldap_unbind($ds);
        return null;          // 找不到人，或找到多筆（filter 太寬）
    }

    $entry  = ldap_first_entry($ds, $res);
    $userDn = ldap_get_dn($ds, $entry);

    // ★★★★ 第二次 bind：用「使用者的 DN + 使用者輸入的密碼」
    // 這一次 bind 成功，才代表密碼正確
    if (!@ldap_bind($ds, $userDn, $password)) {
        ldap_unbind($ds);
        return null;
    }

    $attrs  = ldap_get_attributes($ds, $entry);
    $groups = [];
    if (isset($attrs['memberOf'])) {
        for ($i = 0; $i < $attrs['memberOf']['count']; $i++) {
            $groups[] = $attrs['memberOf'][$i];
        }
    }
    ldap_unbind($ds);

    return [
        'username' => $username,
        'dn'       => $userDn,
        'name'     => $attrs['displayName'][0] ?? $username,
        'email'    => $attrs['mail'][0] ?? null,
        'groups'   => $groups,
    ];
}
```

> [!danger] ★★★★★ 這段程式碼裡有兩個一定會被稽核抓的地雷
> 1. **空密碼 bind**：LDAP 的 unauthenticated bind 會回傳成功。
>    不擋空密碼 = **任何人輸入任意帳號就能登入**。這是實際發生過的重大漏洞。
> 2. **LDAP injection**：使用者輸入不經 `ldap_escape()` 直接串進 filter，
>    攻擊者可以送 `*)(objectClass=*` 改寫查詢邏輯，繞過條件或撈出整個目錄。
>
> 兩件事各只要一行，但少了任何一行，這套系統就不該上線。
> 相關的輸入驗證觀念見 [[090-03-02-guide-應用安全-應用層安全]]。

#### 5-3 群組對應到系統角色

```php
<?php
/** 把 AD 群組 DN 對應到系統角色，取最高的那一個。 */
function map_role(array $groupDns): string
{
    // ★★★ 這張表就是「AD 群組 = 權限控制面板」的實作
    $map = [
        'CN=GG-差勤系統-管理員,OU=Groups,DC=example,DC=local' => 'admin',
        'CN=GG-差勤系統-人事,OU=Groups,DC=example,DC=local'   => 'hr',
        'CN=GG-全體同仁,OU=Groups,DC=example,DC=local'        => 'user',
    ];
    $rank = ['admin' => 3, 'hr' => 2, 'user' => 1];

    $best = null;
    foreach ($groupDns as $dn) {
        // ★★★ AD 回傳的 DN 大小寫可能與你設定的不同，一律轉小寫比對
        foreach ($map as $groupDn => $role) {
            if (strcasecmp($dn, $groupDn) === 0) {
                if ($best === null || $rank[$role] > $rank[$best]) {
                    $best = $role;
                }
            }
        }
    }
    return $best ?? 'denied';     // ★★★★ 預設拒絕，不是預設放行
}
```

★★★★ 最後一行是關鍵：**沒有命中任何群組就是 `denied`**。
如果寫成預設 `user`，那全網域每一個人都能登入你的系統。

#### 5-4 ★★★ 本機帳號怎麼辦

把資料庫的 `users` 表留著，但加一個 `auth_source` 欄位：

```sql
ALTER TABLE users ADD COLUMN auth_source VARCHAR(10) NOT NULL DEFAULT 'ad';
-- 'ad'    = 走 AD 驗證，password_hash 欄位不使用
-- 'local' = 走本機密碼（★★★★ 只留給備援帳號）
```

登入流程改成：先查 `auth_source`，是 `ad` 就走 `ad_authenticate()`，
是 `local` 就走原本的 `password_verify()`。

★★★★ 這樣一來，AD 掛掉的時候，你還可以用本機備援帳號進去。

### 範例四：其他常見系統的對應位置

| 系統 | 設定位置 | 備註 |
| --- | --- | --- |
| **Wazuh Dashboard** | Indexer 的 security 外掛設定（`/etc/wazuh-indexer/opensearch-security/` 底下的 `config.yml` 定義 authc／authz domain，`roles_mapping.yml` 做角色對應），改完要跑 `securityadmin` 工具套用 | ★★ 見 [[090-08-01-svc-Wazuh-Wazuh架構與安裝]] |
| **GitLab** | `/etc/gitlab/gitlab.rb` 的 `gitlab_rails['ldap_servers']`，改完 `gitlab-ctl reconfigure` | 群組同步部分功能屬付費版 |
| **Zabbix** | GUI：Users → Authentication → LDAP settings | 見 [[100-01-10-svc-Zabbix-架構安裝與主機納管]] |
| **Nextcloud／NAS** | 管理介面的 LDAP／AD 整合外掛 | 概念完全相同 |
| **Linux 主機本身（SSH 登入）** | ★★★★ 這是**不同的東西**，用 SSSD 或 realmd | 見 [[020-02-03-08-svc-標準化-集中式帳號整合SSSD與加入AD網域]] |

> [!warning] ★★★ 未實機驗證
> Wazuh／OpenSearch security 外掛的設定檔路徑與 `securityadmin` 套用步驟
> 隨版本變動較大，請以你安裝的版本的官方文件為準，
> 上表僅供定位「該去哪裡找」。

### ★★★★ 離職流程的閉環：已登入的 session 呢

這是很多人做完 LDAP 整合之後**沒想到的破口**。

```text
14:00  人事送離職單
14:05  AD 停用 alice          ← 你以為做完了
14:06  alice 想登入 Grafana → bind 失敗 → 進不去   ✓
14:06  alice 的瀏覽器分頁還開著 Grafana → ★★★★ 還在，session 沒過期
```

**停用 AD 帳號只擋住「新的登入」，擋不住「已經拿到的 session」。**

| 系統 | session 怎麼控制 | 建議設定 |
| --- | --- | --- |
| **Grafana** | `grafana.ini` 的 `[auth]` 區段 | 見下方 |
| **PVE** | ticket 有效期（預設 2 小時）。★★★★ 立即生效的做法是**在 PVE 上把該使用者停用或刪除** | `pveum user modify alice@ad-example --enable 0` |
| **自建系統** | PHP session 的 `gc_maxlifetime` 與自己的閒置逾時 | 見下方 |

Grafana 的 session 設定：

```ini
[auth]
# ★★★ 閒置多久之後 session 失效
login_maximum_inactive_lifetime_duration = 8h
# ★★★★ 不管有沒有在用，最長多久一定要重新登入
login_maximum_lifetime_duration = 1d
# token 輪替間隔
token_rotation_interval_minutes = 10
```

★★★★ `login_maximum_lifetime_duration` 設成 `1d`，代表**最糟情況下，離職者的存取權在 24 小時內一定會斷**。
設成預設的 30 天就太久了。

自建系統的 PHP session：

```ini
; /etc/php/8.3/fpm/php.ini
session.gc_maxlifetime = 28800   ; 8 小時
session.cookie_httponly = 1
session.cookie_secure = 1
session.cookie_samesite = Lax
```

> [!danger] ★★★★★ 完整的離職 checklist 必須包含「踢掉現有 session」
> 光是「AD 停用」不算完成。標準流程應該是：
>
> 1. AD 停用帳號（不是刪除 —— 刪除會讓稽核追不到歷史）。
> 2. ★★★★ **在關鍵系統上主動撤銷 session**：
>    - PVE：`pveum user modify alice@ad-example --enable 0`
>    - Grafana：Server Admin → Users → 該使用者 → **Force logout from all devices**
>    - 自建系統：把該使用者的 session 記錄從 session store 刪掉
> 3. 收回 VPN、API Token、SSH 金鑰（★★★★ **這些不走 LDAP，AD 停用擋不住**）。
> 4. 留存紀錄：誰在什麼時候停用了什麼，稽核要看。
>
> 第 3 點特別容易漏。**API Token 與 SSH 公開金鑰是獨立於 AD 的憑據**，
> 見 [[090-07-02-guide-資安實踐-密碼與帳號管理實務]] 與 [[090-02-06-guide-防護-遠端存取安全]]。

---

## 完整實戰範例

**情境**：機關內有一台 Grafana（`grafana.example.local`）與一台 Proxmox VE（`pve01.example.local`），
兩套各有一組本機帳號。要把它們都接上同一個 AD（`example.local`），
並且**實測「AD 停用之後真的進不去」**。

### 步驟 0：環境與前置

| 項目 | 值 |
| --- | --- |
| 網域 | `example.local` |
| DC | `dc01.example.local`（10.10.1.11）、`dc02.example.local`（10.10.1.12） |
| Grafana | `grafana.example.local`，Ubuntu 24.04，Grafana OSS |
| PVE | `pve01.example.local`，PVE 8 |
| 測試帳號 | `alice`（在 `GG-Grafana-Admins` 與 `GG-PVE-Operators`）、`bob`（等一下要停用） |
| bind 帳號 | `svc-ldap-readonly` |

### 步驟 1：AD 端準備（請 AD 管理員做）

```powershell
# 在 DC 上（PowerShell，需 ActiveDirectory 模組）
# 1. 建立唯讀 bind 服務帳號
New-ADUser -Name "svc-ldap-readonly" `
  -SamAccountName "svc-ldap-readonly" `
  -Path "OU=Service Accounts,DC=example,DC=local" `
  -AccountPassword (Read-Host -AsSecureString "bind 密碼") `
  -Enabled $true `
  -PasswordNeverExpires $true `
  -Description "LDAP 唯讀查詢 / Grafana,PVE / 資訊室分機1234"

# 2. 建立權限群組
New-ADGroup -Name "GG-Grafana-Admins"  -GroupScope Global -GroupCategory Security -Path "OU=Groups,DC=example,DC=local"
New-ADGroup -Name "GG-Grafana-Editors" -GroupScope Global -GroupCategory Security -Path "OU=Groups,DC=example,DC=local"
New-ADGroup -Name "GG-PVE-Operators"   -GroupScope Global -GroupCategory Security -Path "OU=Groups,DC=example,DC=local"

# 3. 把測試帳號加進去
Add-ADGroupMember -Identity "GG-Grafana-Admins" -Members alice
Add-ADGroupMember -Identity "GG-PVE-Operators"  -Members alice
Add-ADGroupMember -Identity "GG-Grafana-Editors" -Members bob
```

★★★★ **不要**把 `svc-ldap-readonly` 加進任何權限群組。`Domain Users` 的預設讀取權限就夠了。

### 步驟 2：★★★★★ 在 Grafana 主機上先用 ldapsearch 驗證

```bash
sudo apt update && sudo apt install -y ldap-utils
```

匯入企業 CA：

```bash
sudo cp enterprise-root-ca.crt /usr/local/share/ca-certificates/example-ca.crt
sudo update-ca-certificates
```

```text
Updating certificates in /etc/ssl/certs...
1 added, 0 removed; done.
```

設定客戶端：

```bash
sudo tee -a /etc/ldap/ldap.conf >/dev/null <<'EOF'
TLS_CACERT  /etc/ssl/certs/ca-certificates.crt
TLS_REQCERT demand
EOF
```

測 bind：

```bash
ldapsearch -x -LLL -H ldaps://dc01.example.local:636 \
  -D "CN=svc-ldap-readonly,OU=Service Accounts,DC=example,DC=local" -W \
  -b "DC=example,DC=local" -s base "(objectClass=*)" defaultNamingContext
```

```text
Enter LDAP Password:
dn:
defaultNamingContext: DC=example,DC=local
```

✓ **第一關過**：DNS、TCP 636、TLS、憑證驗證、bind 全部正常。

測 filter 與屬性：

```bash
ldapsearch -x -LLL -H ldaps://dc01.example.local:636 \
  -D "CN=svc-ldap-readonly,OU=Service Accounts,DC=example,DC=local" -W \
  -b "DC=example,DC=local" \
  "(&(objectCategory=person)(sAMAccountName=alice)(!(userAccountControl:1.2.840.113556.1.4.803:=2)))" \
  dn sAMAccountName givenName sn mail memberOf
```

```text
Enter LDAP Password:
dn: CN=王小明,OU=資訊室,OU=Users,DC=example,DC=local
sAMAccountName: alice
givenName: 小明
sn: 王
mail: alice@example.gov.tw
memberOf: CN=GG-Grafana-Admins,OU=Groups,DC=example,DC=local
memberOf: CN=GG-PVE-Operators,OU=Groups,DC=example,DC=local
memberOf: CN=Domain Users,CN=Users,DC=example,DC=local
```

✓ **第二關過**。★★★★★ 把那兩行群組 DN **選取複製起來**，等一下直接貼進設定檔。

### 步驟 3：設定 Grafana

```bash
sudo cp /etc/grafana/grafana.ini /etc/grafana/grafana.ini.bak.$(date +%F)
sudo cp /etc/grafana/ldap.toml   /etc/grafana/ldap.toml.bak.$(date +%F)
```

```bash
sudo tee /etc/grafana/ldap.toml >/dev/null <<'EOF'
[[servers]]
host = "dc01.example.local dc02.example.local"
port = 636
use_ssl = true
start_tls = false
ssl_skip_verify = false
root_ca_cert = "/etc/ssl/certs/ca-certificates.crt"

bind_dn = "CN=svc-ldap-readonly,OU=Service Accounts,DC=example,DC=local"
bind_password = "換成真正的密碼"

search_filter = "(&(objectCategory=person)(sAMAccountName=%s)(!(userAccountControl:1.2.840.113556.1.4.803:=2)))"
search_base_dns = ["DC=example,DC=local"]

[servers.attributes]
name      = "givenName"
surname   = "sn"
username  = "sAMAccountName"
member_of = "memberOf"
email     = "mail"

[[servers.group_mappings]]
group_dn = "CN=GG-Grafana-Admins,OU=Groups,DC=example,DC=local"
org_role = "Admin"
grafana_admin = true

[[servers.group_mappings]]
group_dn = "CN=GG-Grafana-Editors,OU=Groups,DC=example,DC=local"
org_role = "Editor"

[[servers.group_mappings]]
group_dn = "*"
org_role = "Viewer"
EOF

sudo chown root:grafana /etc/grafana/ldap.toml
sudo chmod 640 /etc/grafana/ldap.toml
```

開啟 LDAP：

```bash
sudo sed -n '/^\[auth.ldap\]/,/^\[/p' /etc/grafana/grafana.ini
```

編輯後應為：

```ini
[auth.ldap]
enabled = true
config_file = /etc/grafana/ldap.toml
allow_sign_up = true
```

重啟並確認：

```bash
sudo systemctl restart grafana-server
sudo systemctl is-active grafana-server
sudo journalctl -u grafana-server -n 20 --no-pager | grep -i ldap
```

```text
active
logger=ldap t=2026-09-03T10:52:11 level=info msg="LDAP enabled, reading config file" file=/etc/grafana/ldap.toml
```

### 步驟 4：用 Grafana 的 LDAP 偵錯頁驗證對應

用**本機 admin** 登入 → `https://grafana.example.local/admin/ldap` →
**Test user mapping** 輸入 `alice` → **Run**。

預期看到：

```text
Mapping information
  Username : alice
  Name     : 小明 王
  Email    : alice@example.gov.tw
  Login    : alice

LDAP groups
  CN=GG-Grafana-Admins,OU=Groups,DC=example,DC=local   →  Admin
  CN=GG-PVE-Operators,OU=Groups,DC=example,DC=local    →  (no match)
  CN=Domain Users,CN=Users,DC=example,DC=local         →  (no match)
```

✓ **第三關過**：alice 會拿到 `Admin`。

### 步驟 5：實際登入測試

登出 → 用 `alice` + 網域密碼登入。

右上角頭像 → 應顯示「小明 王」，左側選單有 **Administration**（代表是 Admin）。

```bash
# 從日誌確認是走 LDAP 進來的
sudo journalctl -u grafana-server -n 50 --no-pager | grep -i "alice"
```

```text
logger=authn.service level=info msg="Successful Login" User=alice@example.gov.tw
```

### 步驟 6：設定 PVE

```bash
# 在 pve01 上匯入企業 CA
cp enterprise-root-ca.crt /usr/local/share/ca-certificates/example-ca.crt
update-ca-certificates
```

GUI：**Datacenter → Permissions → Realms → Add → Active Directory Server**，
依「範例二」的欄位表填入，Mode 選 **LDAPS**、勾選 **Verify Certificate**，
Sync Options 填 bind 帳號與 Base DN。

同步：

```bash
pveum realm sync ad-example --dry-run 1        # 先預覽
pveum realm sync ad-example --scope both --enable-new 0
pveum group list | grep -i PVE-Operators
```

```text
GG-PVE-Operators-ad-example
```

啟用 alice 並給權限：

```bash
pveum user modify alice@ad-example --enable 1
pveum acl modify /pool/資訊室 --group 'GG-PVE-Operators-ad-example' --role PVEVMAdmin
pveum acl list
```

```text
┌──────────────┬─────────────────────────────┬─────────────┬────────┐
│ path         │ ugid                        │ role        │ type   │
├──────────────┼─────────────────────────────┼─────────────┼────────┤
│ /pool/資訊室 │ GG-PVE-Operators-ad-example │ PVEVMAdmin  │ group  │
└──────────────┴─────────────────────────────┴─────────────┴────────┘
```

登入頁 Realm 選 `ad-example`、帳號 `alice`、密碼是網域密碼 → 應該只看得到「資訊室」這個 Pool 的 VM。

✓ **第四關過**。

### 步驟 7：★★★★★ 停用帳號，確認真的進不去

這一步是整個實戰的重點 —— **沒有驗證過的停權流程等於沒有停權流程**。

```powershell
# 在 DC 上停用 bob
Disable-ADAccount -Identity bob
Get-ADUser bob -Properties Enabled | Select-Object SamAccountName, Enabled
```

```text
SamAccountName Enabled
-------------- -------
bob              False
```

**7-1 用 ldapsearch 確認停用旗標**：

```bash
ldapsearch -x -LLL -H ldaps://dc01.example.local:636 \
  -D "CN=svc-ldap-readonly,OU=Service Accounts,DC=example,DC=local" -W \
  -b "DC=example,DC=local" "(sAMAccountName=bob)" userAccountControl
```

```text
Enter LDAP Password:
dn: CN=李大華,OU=人事室,OU=Users,DC=example,DC=local
userAccountControl: 514
```

★★★ `514` = `512`（NORMAL_ACCOUNT）+ `2`（ACCOUNTDISABLE）。第 2 個位元亮了 = 已停用。

**7-2 確認 filter 已經濾掉他**：

```bash
ldapsearch -x -LLL -H ldaps://dc01.example.local:636 \
  -D "CN=svc-ldap-readonly,OU=Service Accounts,DC=example,DC=local" -W \
  -b "DC=example,DC=local" \
  "(&(objectCategory=person)(sAMAccountName=bob)(!(userAccountControl:1.2.840.113556.1.4.803:=2)))" dn
```

```text
Enter LDAP Password:
```

★★★★ **完全沒有輸出** —— 這正是我們要的：Grafana 用同一個 filter，所以它也找不到 bob。

**7-3 直接測 bind**：

```bash
ldapsearch -x -LLL -H ldaps://dc01.example.local:636 \
  -D "CN=李大華,OU=人事室,OU=Users,DC=example,DC=local" -W \
  -b "DC=example,DC=local" -s base "(objectClass=*)" dn
```

```text
Enter LDAP Password:
ldap_bind: Invalid credentials (49)
        additional info: 80090308: LdapErr: DSID-0C09056A, comment:
        AcceptSecurityContext error, data 533, v4563
```

★★★★★ `data 533` = **帳號已停用**。就算密碼正確也 bind 不了。

**7-4 到 Grafana 與 PVE 實際登入**：

- Grafana 輸入 `bob` + 正確密碼 → `Invalid username or password`。✓
- PVE 選 `ad-example`、輸入 `bob` + 正確密碼 → `authentication failure`。✓

**7-5 ★★★★ 處理已存在的 session**：

如果 bob 停用前正登入著 Grafana：

> Server Admin → Users → bob → **Force logout from all devices**

PVE 端：

```bash
pveum user modify bob@ad-example --enable 0
```

**7-6 留下佐證**：

```bash
# 產出一份「離職帳號在各系統的狀態」證明，稽核要看的就是這個
{
  echo "=== 停權驗證報告  $(date '+%F %T') ==="
  echo "[AD] userAccountControl:"
  ldapsearch -x -LLL -H ldaps://dc01.example.local:636 \
    -D "CN=svc-ldap-readonly,OU=Service Accounts,DC=example,DC=local" -y /root/.ldapbind \
    -b "DC=example,DC=local" "(sAMAccountName=bob)" userAccountControl
  echo "[PVE] 帳號狀態:"
  pveum user list | grep -i bob
} | tee /var/log/offboarding-bob-$(date +%F).log
```

★★★ `-y /root/.ldapbind` 是從檔案讀密碼（檔案要 `chmod 600`），
腳本裡用這個，**不要用 `-w 明文密碼`**。

### 步驟 8：★★★★★ 建立本機備援帳號（不可省略）

> [!danger] ★★★★★ 現在停下來想一件事：如果 AD 掛了呢
> 你剛剛把 Grafana 和 PVE 的登入都交給了 AD。
>
> 那麼當 DC 掛掉、網路斷線、或憑證過期的時候 ——
> **你連進去看發生什麼事都做不到。**
>
> 而 AD 掛掉這件事，往往正是你最需要進 PVE 看虛擬機狀態的時候
> （因為 DC 就是跑在那台 PVE 上的 VM）。這是真實會發生的死鎖。

必須保留的備援：

| 系統 | 備援帳號 | 怎麼做 |
| --- | --- | --- |
| **PVE** | ★★★★★ `root@pam` | **絕對不要停用**。密碼寫進封緘信封或密碼保險箱 |
| **Grafana** | 本機 `admin` | `grafana.ini` 的 `disable_login_form = false` 要保持，讓本機登入表單還在 |
| **自建系統** | `auth_source = 'local'` 的一個帳號 | 見「範例三 5-4」 |
| **Linux 主機** | ★★★★ 一個本機 sudo 帳號 + SSH 金鑰 | 主機若用 SSSD 接 AD，AD 掛了也登不進去 |

備援帳號的管理規則（★★★★ 這幾條要寫進維運文件）：

1. **強密碼，20 字元以上，隨機產生**，跟任何其他系統不共用。
2. **密封保管**：封緘信封鎖進保險箱，或存在離線的密碼管理器。
3. ★★★★ **開啟告警**：這個帳號一登入就發通知。平常不該有人用它。
4. **每半年輪替一次**，並且記錄輪替日期。
5. **交接時列入交接清單**。

驗證備援可用（★★★ 每季做一次）：

```bash
# 模擬 AD 不可用：暫時把 DC 的名稱指向黑洞
echo "127.0.0.1 dc01.example.local dc02.example.local" | sudo tee -a /etc/hosts

# 這時候 alice 應該登不進去，但本機 admin 應該可以
# 測完立刻還原
sudo sed -i '/dc01.example.local dc02.example.local/d' /etc/hosts
```

> [!warning] ★★★★ 這個測試會讓該主機的 AD 登入短暫失效
> 請在**維護時段**做，並事先通知。做完務必確認 `/etc/hosts` 已還原：
> ```bash
> grep -c "dc01.example.local" /etc/hosts     # 應該是 0
> ```

### 步驟 9：收尾清單

| 檢查 | 指令／位置 | 通過標準 |
| --- | --- | --- |
| Grafana LDAP 生效 | `/admin/ldap` 頁 Test user mapping | 角色對應正確 |
| PVE realm 生效 | 登入頁能選 `ad-example` 並登入成功 | 只看得到該看的資源 |
| ★★★★ 停用帳號登不進 | 用已停用帳號實測 | 兩套都失敗 |
| ★★★★ 走的是 LDAPS | `ss -tnp \| grep 636` | 只有 636，沒有 389 |
| ★★★★★ 備援帳號可用 | 實測本機 admin / `root@pam` | 登得進去 |
| 設定檔權限 | `ls -l /etc/grafana/ldap.toml` | `640 root:grafana` |
| 設定檔已備份 | `ls /etc/grafana/*.bak.*` | 有備份 |
| session 逾時已設 | `grep login_maximum /etc/grafana/grafana.ini` | 有設且不超過 1 天 |

確認 LDAPS：

```bash
sudo ss -tnp | grep -E ':(389|636)'
```

```text
ESTAB 0 0 10.10.5.30:51422 10.10.1.11:636 users:(("grafana",pid=1183,fd=17))
```

★★★★ 只看到 `636`，沒有 `389` —— 沒有明文外洩。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ `ldap_bind: Invalid credentials (49) ... data 52e` | bind 帳號**密碼錯**，或 bind DN 打錯 | 用 `ldapsearch -D ... -W` 逐字重打。DN 從 `Get-ADUser svc-ldap-readonly -Properties DistinguishedName` 複製 |
| ★★★★ `ldap_bind: Invalid credentials (49) ... data 533` | **帳號已停用** | 這是預期行為（離職停權生效）。若是 bind 帳號自己被停用，請 AD 管理員重新啟用 |
| `... data 532` / `data 773` | bind 帳號**密碼過期**或被勾「下次登入須變更密碼」 | 服務帳號要設「密碼永久有效」並取消變更旗標 |
| ★★★★ `ldap_sasl_bind(SIMPLE): Can't contact LDAP server (-1)` | DNS 解不到、防火牆擋、DC 沒開 LDAPS | 依序測：`dig +short dc01...`、`timeout 3 bash -c 'cat < /dev/null > /dev/tcp/dc01.../636'`、`openssl s_client -connect dc01...:636` |
| ★★★★★ `ldap_sasl_bind(SIMPLE): ... (-1)` 且 `openssl s_client` 顯示 `verify error:num=19` 或 `num=21` | **DC 憑證的 CA 不被本機信任** | 匯入企業 CA 根憑證 → `update-ca-certificates`。**不要**改成 `TLS_REQCERT never` |
| `openssl s_client` 顯示 `verify error:num=62: Hostname mismatch` | 用 **IP 連線**但憑證 SAN 只有主機名 | 改用 FQDN 連線，或請 AD 管理員重簽含 IP SAN 的憑證 |
| ★★★★ 憑證某天突然驗不過，前一天還好好的 | **DC 憑證過期** | `openssl s_client ... \| openssl x509 -noout -dates` 確認 `notAfter`。把 DC 憑證納入到期監控 |
| ★★★★★ **ldapsearch 找得到人，但系統登入失敗** | 系統設定檔裡的 base DN／filter／屬性名與你測試時用的**不一致** | 把設定檔的 filter 原封不動貼回 `ldapsearch` 跑一次。差一個字元就會這樣 |
| ★★★★ **登入成功但角色永遠是 Viewer**（群組對應沒生效） | ① 群組 DN 打錯（`OU=Group` vs `OU=Groups`）② `group_dn = "*"` 那條放在前面 ③ 該群組是**巢狀**的 | ① 從 `ldapsearch ... memberOf` 的輸出**複製** DN ② 萬用比對放最後 ③ 改用 `1.2.840.113556.1.4.1941` 鏈式比對，或把使用者直接加進目標群組 |
| ★★★ 群組對應在 OpenLDAP 上完全沒作用 | OpenLDAP **沒有載入 `memberof` overlay**，使用者物件上沒有 `memberOf` 屬性 | 改用 `group_search_base_dns` + `group_search_filter` 從群組端反查，或請目錄管理員載入 overlay |
| ★★★ 搜尋回傳 `Referral (10)` 或結果是空的 | AD 回傳 referral，客戶端跟著跑失敗 | 程式端設 `LDAP_OPT_REFERRALS = 0`；命令列在 base DN 下搜尋而非在 `CN=Configuration` 等分割區 |
| ★★★ `Operations error (1) ... 000004DC` | **匿名查詢被拒**（沒帶 `-D` / bind DN，或忘了帶 `-x`） | 一定要帶 `-x -D ... -W` |
| ★★★★ 找到多筆而登入失敗 | filter 太寬（例如只寫 `(cn=%s)`，中文姓名重複） | 改用 `sAMAccountName` 或 `userPrincipalName`，並加 `(objectCategory=person)` |
| ★★★★★ **任何帳號輸入空密碼都能登入自建系統** | **unauthenticated bind** —— 程式沒擋空密碼 | 在呼叫 `ldap_bind()` 之前先擋 `$password === ''`。這是重大漏洞，發現要立刻修 |
| ★★★★ 有人用 `alice)(objectClass=*` 之類的輸入撈到不該看的資料 | **LDAP injection** —— 使用者輸入沒跳脫 | 一律用 `ldap_escape($v, '', LDAP_ESCAPE_FILTER)`（或對應語言的跳脫函式） |
| ★★★★★ **DC 掛掉之後所有人（包含你）都登不進去** | 只設了一台 DC，且沒有本機備援帳號 | ① 設定 `server2` / Fallback Server ② **保留本機備援帳號**（PVE `root@pam`、Grafana 本機 admin）③ 定期演練 |
| ★★★ AD 停用了，但使用者的瀏覽器分頁還能用 | 停用只擋新登入，**擋不住既有 session** | 縮短 `login_maximum_lifetime_duration`；離職流程加入「強制登出所有裝置」 |
| ★★★★ 離職者仍能用 API Token／SSH 金鑰存取 | **這些憑據不經過 LDAP** | 離職 checklist 必須包含撤銷 API Token、SSH 公開金鑰、VPN 憑證 |
| ★★ PVE 同步後群組名稱找不到 | 同步進來的群組帶 realm 後綴 | `pveum group list` 查實際名稱再貼進 `pveum acl modify` |
| ★★★ 中文姓名在系統裡顯示成亂碼 | 屬性對應抓了 `cn` 且傳輸／顯示編碼處理不當 | 顯示名稱改抓 `displayName`；確認系統與資料庫都是 UTF-8 |

### ★★★★ 排錯的固定順序

遇到「登入失敗」不要亂改設定檔，照這個順序切：

```text
1. DNS 解得到 DC 嗎？              dig +short dc01.example.local
2. 636 通嗎？                      timeout 3 bash -c 'cat < /dev/null > /dev/tcp/dc01.example.local/636'
3. TLS 建得起來、憑證驗得過嗎？    openssl s_client -connect dc01.example.local:636
4. bind 帳號能 bind 嗎？           ldapsearch -x -D "<bindDN>" -W -b ... -s base
5. filter 找得到那個人嗎？         ldapsearch ... "(sAMAccountName=alice)"
6. 使用者自己 bind 得了嗎？        ldapsearch -x -D "<userDN>" -W -b ... -s base
7. 群組 DN 跟設定檔一字不差嗎？    diff 一下
8. 系統的日誌怎麼說？              journalctl / grafana.log
```

★★★★★ **前六步都在命令列做，不碰任何系統設定檔。**
哪一步失敗，問題就在那一步，不會誤判。

---

## 安全性注意事項

> [!danger] ★★★★★ 一、絕對不要用 Domain Admin 當 bind 帳號
> 這是機關最常犯的錯，理由通常是「用 Administrator 比較不會有權限問題」。
>
> 後果：
>
> | 風險 | 說明 |
> | --- | --- |
> | **明文密碼躺在檔案裡** | `ldap.toml`、`gitlab.rb`、PHP 設定檔裡是**明文**。任何能讀那個檔的人就拿到 Domain Admin |
> | **攻擊面暴增** | 打下那台 Grafana ≒ 打下整個網域。一台低價值主機變成通往 AD 的直達車 |
> | **備份也外洩** | 設定檔會被備份，備份檔往往權限更鬆 |
> | **無法輪替** | Domain Admin 密碼一換，所有系統一起壞掉，於是沒人敢換 |
>
> **正確做法**：一個 `svc-` 開頭的專用帳號，只在 `Domain Users`，
> 除了讀目錄什麼都不能做。就算外洩，攻擊者拿到的只是「能讀目錄」。
>
> AD 端的權限強化見 [[030-01-02-08-guide-AD-AD安全強化]]。

> [!danger] ★★★★★ 二、一定要 LDAPS 或 STARTTLS
> 用 389 明文的時候，網路上傳的是**使用者的網域密碼**，
> 不是某一套系統的密碼。一次抓包 = 一批 AD 帳號。
>
> 檢查全機關有沒有人偷偷用明文：
>
> ```bash
> # 在每一台有接 LDAP 的主機上跑
> sudo ss -tnp | grep ':389 '
> ```
>
> 有輸出就代表**有系統在用明文 LDAP**，立刻處理。
>
> 而且**加密還不夠，憑證要驗**：`ssl_skip_verify = false`、`TLS_REQCERT demand`、
> PVE 勾 Verify Certificate。不驗證憑證的 TLS 擋不住中間人。

> [!warning] ★★★★ 三、bind 帳號的管理
> | 規則 | 為什麼 |
> | --- | --- |
> | **唯讀** | 它只需要讀目錄。給寫入權限沒有任何好處 |
> | **專用** | 不要跟其他用途共用。共用的帳號沒辦法在出事時定位 |
> | ★★★ **每個系統一個更好** | 如果人力允許，Grafana、PVE、Wazuh 各一個 bind 帳號，出事時能從 AD 日誌看出是哪一套被打 |
> | **密碼可輪替** | 登記在密碼清冊，一年至少換一次。換的時候要有清單知道要改哪幾個檔 |
> | ★★★ **監控它的登入來源** | bind 帳號只該從你已知的那幾台伺服器連進來。從別的 IP 出現 = 密碼外洩 |
>
> 密碼與服務帳號的制度面見 [[090-07-02-guide-資安實踐-密碼與帳號管理實務]]。

> [!danger] ★★★★★ 四、本機備援帳號是必要的，不是懶惰
> 把認證全部集中到 AD 之後，**AD 就變成了單點故障**。
>
> 而 DC 常常就跑在你要管理的那台 PVE 上 —— 於是：
> **PVE 出問題 → DC 掛了 → 你用 AD 帳號登不進 PVE → 修不了 PVE → DC 起不來。**
>
> 這個死鎖唯一的解是：**PVE 的 `root@pam` 永遠留著、密碼放在保險箱裡。**
>
> 同樣的道理適用於 Grafana 的本機 admin、Linux 主機的本機 sudo 帳號。
> 這些帳號要：強密碼、密封保管、登入即告警、每半年輪替、每季演練一次。

> [!warning] ★★★★ 五、設定檔裡的明文密碼
> `ldap.toml`、`gitlab.rb`、PVE 的 realm 設定裡都有 bind 密碼。
>
> - **權限收緊**：`chmod 640`，owner `root`，group 是服務的執行帳號。
> - ★★★★ **不要進版本控制**。`.gitignore` 要包含這些檔案，
>   而且要確認**歷史紀錄裡也沒有**（曾經 commit 過就等於外洩了）。
> - 能用環境變數或 secret 管理就用，見 [[090-03-03-guide-應用安全-機密管理與金鑰保護]]。
> - **備份檔也要保護**：`ldap.toml.bak` 常常是 `644`。

> [!warning] ★★★★ 六、filter 一定要排除停用帳號
> 有些系統（例如 SSSD 的預設設定）會自己判斷 `userAccountControl`，
> 但**大多數應用程式不會**。
>
> 如果你的 filter 只寫 `(sAMAccountName=%s)`，
> 那麼「AD 停用」能不能擋住登入，就完全取決於**該系統會不會自己檢查**。
>
> ★★★★★ **不要賭。自己在 filter 裡加上排除條件**：
>
> ```text
> (!(userAccountControl:1.2.840.113556.1.4.803:=2))
> ```
>
> 這樣不管系統聰不聰明，停用的帳號都**查不到**，自然登不進去。

> [!warning] ★★★ 七、預設拒絕，不是預設放行
> `group_dn = "*"` 對應到 `Viewer` 看起來很方便，
> 但它的實際意義是「**全網域每一個人都能登入這套系統**」。
>
> 如果這套系統有敏感資料（例如監控儀表板會顯示內網拓撲與主機名稱），
> 應該把萬用那條拿掉，改成「不在指定群組就不給角色」。
>
> 自建系統的 `map_role()` 也一樣：找不到對應群組要回 `denied`，不是 `user`。

> [!tip] ★★★ 八、LDAP 整合不等於有 MFA
> 接了 AD 之後，登入用的還是「帳號 + 密碼」一個因素。
> 密碼外洩，所有接了 AD 的系統一起淪陷 —— **集中認證同時集中了風險**。
>
> 要加 MFA，路徑是往 SSO／IdP 走（MFA 在 IdP 上做一次，所有系統受惠）。
> 這正是「三種整合深度」那張表裡 SSO 的最大價值。見 [[090-05-07-guide-資安設備-身分存取管理IAM與MFA]]。

> [!warning] ★★★ 九、留下稽核佐證
> 做完整合之後，稽核會問「你怎麼證明離職帳號在各系統都失效了」。
> 準備好這三份：
>
> 1. **系統清冊**：哪些系統接了 AD、哪些沒接（沒接的要說明為什麼與補償措施）。
> 2. **停權驗證紀錄**：像「步驟 7」那樣，實際用停用帳號測試的截圖與日誌。
> 3. **例外清單**：本機備援帳號有哪些、誰保管、上次輪替日期。
>
> 見 [[090-07-09-guide-資安實踐-資安稽核與符合性檢核]]。

---

## 速查表

### ldapsearch 常用參數

| 參數 | 說明 |
| --- | --- |
| `-x` | ★★★★ simple 認證（不用 SASL）。**幾乎一定要加** |
| `-H ldaps://host:636` | ★★★★ 加密連線（LDAPS） |
| `-H ldap://host:389 -ZZ` | ★★★★ 明文埠 + **強制** STARTTLS |
| `-D "<bind DN>"` | bind DN |
| `-W` | ★★★★ 互動輸入密碼（**不要用 `-w 明文`**） |
| `-y <檔案>` | ★★★ 從檔案讀密碼（腳本用，檔案 `chmod 600`） |
| `-b "<base DN>"` | 搜尋起點 |
| `-s base\|one\|sub` | 搜尋深度（預設 `sub`） |
| `-LLL` | 乾淨的 LDIF 輸出 |
| `-o TLS_REQCERT=never` | ★★★ **僅供臨時排查**，不要寫進設定檔 |
| `-VV` | 顯示版本 |

### 常用 filter

| 目的 | 寫法 |
| --- | --- |
| 找一個人 | `(sAMAccountName=alice)` |
| 只找人不找電腦 | `(&(objectCategory=person)(sAMAccountName=alice))` |
| ★★★★ 排除停用帳號 | `(!(userAccountControl:1.2.840.113556.1.4.803:=2))` |
| 群組直接成員 | `(memberOf=CN=GG-X,OU=Groups,DC=example,DC=local)` |
| ★★★★ 群組成員含巢狀 | `(memberOf:1.2.840.113556.1.4.1941:=CN=GG-X,OU=Groups,DC=example,DC=local)` |
| AND / OR / NOT | `(&(A)(B))` / `(\|(A)(B))` / `(!(A))` |

### AD bind 錯誤碼

| `data` | 意思 |
| --- | --- |
| `525` | 使用者不存在 |
| ★★★★ `52e` | 密碼錯誤 |
| `530` / `531` | 不在允許的時段／工作站 |
| ★★★ `532` | 密碼過期 |
| ★★★★ `533` | **帳號已停用** |
| `701` | 帳號到期 |
| ★★★ `773` | 必須變更密碼 |
| `775` | 帳號鎖定 |

### 檔案與路徑

| 路徑 | 用途 |
| --- | --- |
| `/etc/ldap/ldap.conf` | OpenLDAP 客戶端設定（Debian 系） |
| `/etc/openldap/ldap.conf` | 同上（RHEL 系） |
| `/usr/local/share/ca-certificates/` | ★★★★ 放企業 CA，之後跑 `update-ca-certificates` |
| `/etc/grafana/grafana.ini` | Grafana 主設定（`[auth.ldap]`） |
| ★★★★ `/etc/grafana/ldap.toml` | Grafana LDAP 細節，**含明文密碼，`chmod 640`** |
| `/var/log/grafana/grafana.log` | Grafana 日誌 |
| `/etc/pve/domains.cfg` | PVE realm 設定（★★★ 用 `pveum` 或 GUI 改，不要直接編輯） |

### 常用指令

| 指令 | 用途 |
| --- | --- |
| `sudo apt install ldap-utils` | 安裝 ldapsearch（Debian 系） |
| `sudo dnf install openldap-clients` | 同上（RHEL 系） |
| `sudo update-ca-certificates` | 套用新加入的 CA |
| `openssl s_client -connect dc01:636 -showcerts` | ★★★★ 看 DC 憑證 |
| `sudo systemctl restart grafana-server` | 套用 Grafana 設定 |
| `pveum realm list` / `add` / `modify` / `sync` | PVE realm 管理 |
| `pveum user list` / `pveum group list` | ★★★ 查同步進來的實際名稱 |
| `pveum acl modify <path> --group <g> --role <r>` | PVE 授權 |
| ★★★★ `sudo ss -tnp \| grep -E ':(389\|636)'` | **確認沒有明文 LDAP** |
| `journalctl -u pvedaemon \| grep -i auth` | PVE 認證日誌 |
| `php -m \| grep ldap` | 確認 PHP LDAP 擴充已載入 |

### 埠對照

| 埠 | 用途 | 加密 |
| --- | --- | --- |
| 389 | LDAP | ★★★★★ 無（除非 STARTTLS） |
| ★★★★ 636 | LDAPS | 有 |
| 3268 | Global Catalog | 無 |
| 3269 | Global Catalog SSL | 有 |

---

## 練習題

> [!question]- 練習 1：把連線資訊完整驗證出來（★★★★★ 必做）
> 在一台 Ubuntu 上安裝 `ldap-utils`，對你環境的 DC 完成以下五件事，
> 每一步都要貼出實際輸出：
>
> 1. `dig` 解出 DC 的 IP。
> 2. 確認 636 通。
> 3. `openssl s_client` 看出憑證的 subject、SAN 與到期日。
> 4. 匯入企業 CA 之後，`ldapsearch -s base` 成功取得 `defaultNamingContext`。
> 5. 用 filter 查出一個測試帳號的 `dn`、`sAMAccountName`、`mail`、`memberOf`。
>
> **通過標準**：第 4、5 步都成功，而且**沒有用到 `TLS_REQCERT never`**。
>
> **提示**：第 3 步如果 SAN 裡沒有你連線用的名稱，先解決這個再往下。

> [!question]- 練習 2：寫出「排除停用帳號」的 filter 並驗證
> 1. 找一個（或請 AD 管理員暫時建立一個）已停用的測試帳號。
> 2. 先用 `(sAMAccountName=<帳號>)` 查 `userAccountControl`，算出停用位元。
> 3. 加上 `(!(userAccountControl:1.2.840.113556.1.4.803:=2))` 再查一次。
>
> **通過標準**：第 2 步查得到、第 3 步查不到（輸出為空）。
>
> **延伸**：把該帳號重新啟用，確認第 3 步又查得到了。

> [!question]- 練習 3：Grafana 接上 AD 並驗證群組對應
> 1. 建立兩個 AD 群組，分別對應 Grafana 的 `Admin` 與 `Editor`。
> 2. 完成 `ldap.toml`，注意 `group_dn = "*"` 要放最後。
> 3. 用 `/admin/ldap` 的 Test user mapping 驗證兩個測試帳號分別拿到正確角色。
> 4. 把其中一個帳號從 Admin 群組移到 Editor 群組，**重新登入**確認角色變了。
>
> **通過標準**：第 3、4 步都符合預期。
>
> ★★★ **思考題**：第 4 步為什麼一定要「重新登入」才會生效？

> [!question]- 練習 4：驗證離職停權的完整閉環
> 挑一個測試帳號，在 AD 停用它，然後逐項驗證：
>
> | 項目 | 預期結果 |
> | --- | --- |
> | `ldapsearch` bind | `data 533` |
> | 加了排除條件的 filter | 查不到 |
> | Grafana 登入 | 失敗 |
> | PVE 登入 | 失敗 |
> | 停用前已登入的 Grafana 分頁 | ？ |
>
> **通過標準**：前四項都符合，並且**寫出最後一項的觀察結果與你的處理方式**。

> [!question]- 練習 5：★★★★★ 備援帳號演練
> 在**維護時段**，用 `/etc/hosts` 把 DC 名稱指向 `127.0.0.1`，模擬 AD 不可用：
>
> 1. 確認 AD 帳號登不進 Grafana。
> 2. 確認本機 `admin` 登得進 Grafana。
> 3. 確認 `root@pam` 登得進 PVE。
> 4. 還原 `/etc/hosts` 並確認 AD 登入恢復。
>
> **通過標準**：第 2、3 步成功；第 4 步之後 `grep -c dc01 /etc/hosts` 回傳 `0`。
>
> **產出**：寫成一份演練紀錄，包含日期、參與人、每一步的結果與還原確認。

> [!question]- 練習 6：檢查自建系統的兩個地雷
> 找一套你手上會接 AD 的自建系統（或用「範例三」的程式碼），檢查：
>
> 1. **空密碼**：輸入一個存在的帳號 + 空密碼，會不會登入成功？
> 2. **LDAP injection**：輸入 `alice)(objectClass=*` 當帳號，會發生什麼？
>
> **通過標準**：兩者都被正確擋下（回傳認證失敗，而不是成功或錯誤訊息外洩目錄結構）。
>
> ★★★★★ 如果第 1 項真的登入成功了，**這是重大漏洞，當天就要修**。

---

## 小測驗

Q1. 一個機關有 Wazuh、Grafana、PVE、GitLab 與自建系統各一套帳號。
為什麼「稽核最常開的缺失」是離職停權？集中認證怎麼從根本解決這件事？

Q2. 三種整合深度（直接接 LDAP／SSO／自架 IdP）之中，
**只有哪一種能把 MFA 做在一個地方讓所有系統受惠**？為什麼另外一種做不到？

Q3. 自架 Keycloak 之類的 IdP，你同時買下了哪兩個最嚴重的責任？

Q4. 把 `CN=王小明,OU=資訊室,OU=Users,DC=example,DC=local` 拆開，
說明 DC、OU、CN 各代表什麼，以及這串該由哪一端開始讀。

Q5. LDAP 認證為什麼需要**兩次 bind**？第一次和第二次各自用誰的身分？

Q6. `memberOf` 與 `member` 兩種群組表達方式差在哪？
接 AD 該用哪一種？接一個沒有 `memberof` overlay 的 OpenLDAP 呢？

Q7. 這行指令會發生什麼事，你從輸出能確認哪四件事？

```bash
ldapsearch -x -LLL -H ldaps://dc01.example.local:636 \
  -D "CN=svc-ldap-readonly,OU=Service Accounts,DC=example,DC=local" -W \
  -b "DC=example,DC=local" -s base "(objectClass=*)" defaultNamingContext
```

Q8. 是非題並說明理由：
「LDAPS 憑證驗不過的時候，把 `ssl_skip_verify` 設成 `true` 是可接受的暫時解法。」

Q9. 為什麼**絕對不能**拿 Domain Admin 當 bind 帳號？至少講三個具體後果。

Q10. AD 上停用了 alice，但她的瀏覽器還開著 Grafana 分頁而且還能用。
這是什麼原因？完整的離職流程還必須做哪三件事？

> [!question]- 測驗答案
> **Q1.** 因為稽核問的是「離職帳號在**各資訊系統**都已停用」，
> 只證明 AD 停用**不算過**。系統一多、負責人一分散，人工逐一停權**必然會漏**，
> 這是流程設計問題不是紀律問題。
> 集中認證讓**帳號只有一份**（在 AD），各系統都不存密碼、每次登入都回頭問 AD；
> AD 一停用，下一次任何系統的 bind 都會失敗 —— **一個動作全面生效**。
> → 見「觀念說明 / 先問一個問題」與「唯一可持續的解」。
>
> **Q2.** 只有 **SSO（含自架 IdP）** 做得到 —— 因為登入動作發生在 IdP 上，
> MFA 在 IdP 設一次，所有轉址過來的系統都受惠，而且**使用者密碼不會經過應用程式**。
> **直接接 LDAP** 做不到，因為每個系統各自收下密碼再去 bind，
> MFA 得由每套系統自己實作；而且應用程式拿得到明文密碼。
> → 見「三種整合深度」表格。
>
> **Q3.** ①★★★★★ **單點故障**：IdP 掛掉等於所有接它的系統一起無法登入；
> ②★★★★★ **皇冠寶石**：它握有全部系統的登入權，被打下來就是全機關淪陷。
> 另外還有高可用、備份還原演練、版本升級、簽章憑證到期管理四項持續成本。
> **沒有人力承擔這些就不要自架 IdP。**
> → 見「自架 IdP（Keycloak）的代價」摺疊區塊。
>
> **Q4.** `DC` = Domain Component，網域的一段（`example.local` 拆成 `DC=example,DC=local`）；
> `OU` = Organizational Unit，組織單位；`CN` = Common Name，物件本身的名字。
> ★★★ 讀法是**由內而外、由葉到根**（先 CN 再一層層往上到 DC），跟檔案路徑方向相反。
> → 見「LDAP 基礎」的目錄樹。
>
> **Q5.** 因為 AD 不開放匿名查詢，系統必須先有身分才能查目錄。
> **第一次 bind 用唯讀服務帳號**（`svc-ldap-readonly`），目的是**查出使用者的 DN**；
> **第二次 bind 用「查到的使用者 DN + 使用者剛剛輸入的密碼」**，
> 這次 bind 成功才代表**密碼正確**。
> → 見「為什麼需要 bind 帳號」的四步流程。
>
> **Q6.** `memberOf` 是**從人看群組**（使用者物件上列出所屬群組），
> `member` 是**從群組看人**（群組物件上列出成員 DN）。
> 接 **AD** 用 `memberOf`（AD 預設就有），設 `member_of = "memberOf"` 即可；
> 接**沒有 memberof overlay 的 OpenLDAP** 時 `memberOf` 是空的，
> 必須改用 `group_search_base_dns` + `group_search_filter` 從群組端反查。
> ★★★ 「使用者找得到但群組永遠對不上」十次有八次是這裡搞混。
> → 見「群組成員資格的兩種表達方式」。
>
> **Q7.** 它以 `svc-ldap-readonly` 的身分透過 LDAPS（636）連上 `dc01`，
> 只讀 base DN 這一個節點的 `defaultNamingContext` 屬性。
> 成功輸出代表四件事同時成立：①**DNS 解得到 DC** ②**TCP 636 通**
> ③**TLS 建立且憑證驗證通過** ④**bind 帳號與密碼正確**。
> ★★★★★ 這一行是所有 LDAP 整合的第一道檢查點。
> → 見「第 2 步 2-4 測試 bind」。
>
> **Q8.** **非。** `ssl_skip_verify = true` 等於關掉憑證驗證 ——
> 連線仍然加密，但**你不知道對面是不是真的 DC**，
> 中間人可以冒充 DC 並收下使用者的**網域密碼**。
> 憑證驗不過的正確解法是：**把企業 CA 根憑證匯入信任區**，
> 或**改用憑證 SAN 上真的有的那個名稱連線**。
> 只有臨時排查時可以在單一次指令上加 `-o TLS_REQCERT=never`，**絕不寫進設定檔**。
> → 見「2-3 讓本機信任企業 CA」的 danger 區塊與「安全性注意事項」第二條。
>
> **Q9.** ①**明文密碼躺在檔案裡**（`ldap.toml` 等是明文），能讀那個檔就等於拿到 Domain Admin；
> ②**攻擊面暴增**，打下一台低價值的 Grafana 就等於打下整個網域；
> ③**備份也外洩**，設定檔備份的權限往往更鬆；
> ④**無法輪替**，密碼一換所有系統一起壞，於是永遠不敢換。
> 正確做法是一個只在 `Domain Users` 的 `svc-` 專用唯讀帳號。
> → 見「安全性注意事項」第一條。
>
> **Q10.** 因為**停用 AD 帳號只擋住「新的登入」，擋不住「已經發出的 session／ticket」**。
> 完整流程還要：①**主動撤銷 session**（Grafana 的 Force logout from all devices、
> `pveum user modify bob@ad-example --enable 0`）；
> ②**縮短 session 上限**（`login_maximum_lifetime_duration` 設 1 天而不是預設的 30 天）；
> ③★★★★ **撤銷不走 LDAP 的憑據** —— API Token、SSH 公開金鑰、VPN 憑證，
> 這些 AD 停用完全擋不住，最容易漏。
> → 見「離職流程的閉環」與實戰「步驟 7-5」。

---

## 延伸閱讀

- [[030-01-02-01-guide-AD-AD概念與網域架構]] — 網域、OU、群組的結構
- [[030-01-02-03-guide-AD-使用者與群組管理AD]] — 建立服務帳號與安全群組
- [[030-01-02-08-guide-AD-AD安全強化]] — 特權帳號保護與 LDAP 簽章要求
- [[020-02-03-08-svc-標準化-集中式帳號整合SSSD與加入AD網域]] — 讓 **Linux 主機本身**吃 AD 帳號
- [[050-01-03-08-guide-PVE-使用者權限與API]] — PVE 的權限模型、角色與 API Token
- [[100-01-09-guide-Grafana-儀表板與Alertmanager通知]] — Grafana 本身的操作
- [[090-05-07-guide-資安設備-身分存取管理IAM與MFA]] — SSO、MFA、PAM 與帳號生命週期
- [[090-07-02-guide-資安實踐-密碼與帳號管理實務]] — 服務帳號與密碼輪替制度
- [[090-03-03-guide-應用安全-機密管理與金鑰保護]] — bind 密碼不要寫死在設定檔
- [[090-03-01-guide-應用安全-TLS憑證與HTTPS實務]] — LDAPS 憑證驗證的底層觀念
- [[090-01-09-guide-PKI-根憑證派送與信任]] — 把企業 CA 派送到各主機
- [[090-01-11-guide-PKI-憑證格式轉換與檢視工具]] — 檢視 DC 憑證
- [[090-03-02-guide-應用安全-應用層安全]] — LDAP injection 與輸入驗證
- [[090-02-06-guide-防護-遠端存取安全]] — SSH 金鑰、VPN 這些不走 LDAP 的憑據
- [[090-07-09-guide-資安實踐-資安稽核與符合性檢核]] — 停權佐證怎麼準備
- [[090-03-06-guide-應用安全-委外系統上線前資安檢測]] — 驗收廠商系統時怎麼檢查它的認證設計
- [[000-00-idx-索引-首頁]]
