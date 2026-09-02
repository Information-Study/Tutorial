---
title: "PVE 使用者權限與 API"
desc: "Realm 認證來源、路徑式 ACL 的繼承模型、內建角色與權限對照、API Token 與權限分離、pvesh 與 REST API 實作、雙因素驗證、AD/LDAP 整合與常見卡關點"
aliases: [pveum, pvesh, PVEAPIToken, ACL, Realm, API Token, privsep, TOTP, LDAP 整合, AD 整合]
tags: [群組/虛擬機與容器, 虛擬化/pve, 主題/虛擬化]
category: 虛擬化平台
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[050-01-03-01-svc-PVE-安裝與初始設定]]", "[[050-01-03-03-guide-PVE-虛擬機管理]]", "[[020-01-09-cmd-Linux-使用者與群組管理]]"]
updated: 2026-09-02
---

# PVE 使用者權限與 API

> [!abstract] 這篇你會學到
> - PVE 的四種 **Realm（認證來源）**：`pam`、`pve`、`ldap`、`ad`，以及各自的適用場景
> - ★★★★ **路徑式 ACL 的繼承模型** —— 權限掛在「路徑」上，不是掛在物件上
> - 內建角色（`PVEVMUser`／`PVEVMAdmin`／`PVEAuditor`…）到底各給了什麼權限
> - 怎麼**自訂角色**，做出真正的最小權限
> - ★★★★★ **API Token 與權限分離（privilege separation）** —— 為什麼 `privsep=1` 才是正解
> - `pvesh` 與 REST API 實作，含 **curl 的兩種認證方式**（Token 與 Ticket）
> - **雙因素驗證（TOTP／WebAuthn／Recovery Key）** 的設定與救援
> - ★★★★ **AD／LDAP 整合的完整步驟，以及六個最常卡住的地方**
> - ★★★★★ **完整實戰**：做出一個「只能備份、不能刪 VM」的 API Token，並用 curl 實測到 403

> [!warning] 未實機驗證
> 本篇**以 Proxmox VE 8 為例**（`pveum`、`pvesh`、`/api2/json`、`/etc/pve/user.cfg`）。
>
> ★★★★★ **角色所含的權限項目、API 路徑、`pveum` 參數會隨版本增減**，
> 動手前請以你節點上的
> `pveum role list`、`pveum --help`、`man pveum`、`pvesh usage <path> -v` 為準。
>
> ★★★★★ 文中的 **Token secret、UUID、網域名稱、DN 都是示意值**，
> 不要照抄。所有 curl 範例都假設你已把 `pve1.lab.local` 換成你的節點。

---

## 前置知識

- [[050-01-03-01-svc-PVE-安裝與初始設定]] — ★★★★ 第一次登入用的是 `root@pam`
- [[050-01-03-03-guide-PVE-虛擬機管理]] — 要先知道 VMID、pool 這些概念
- [[020-01-09-cmd-Linux-使用者與群組管理]] — ★★★★ **`pam` realm 的使用者其實就是 Linux 帳號**
- [[030-01-02-01-guide-AD-AD概念與網域架構]] — AD 整合前要懂 DN、OU、網域結構
- [[030-01-02-03-guide-AD-使用者與群組管理AD]] — AD 端的使用者與群組怎麼組織
- [[090-01-01-guide-PKI-PKI與憑證基礎]] — ★★★★ LDAPS 憑證驗證卡關時要回頭看這篇
- [[020-02-01-04-svc-sshd-伺服器端設定]] — 管理介面的整體防護

---

## 觀念說明

### 一、PVE 的認證與授權是兩件事 ★★★★★

```
┌───────────────────────────────────────────────────────────────┐
│  認證（Authentication）：你是誰？                              │
│    由 Realm 決定 → pam / pve / ldap / ad / openid             │
│    ★★★★ 使用者識別一律是 <使用者名>@<realm>                    │
│    例：root@pam   ops@pve   wang@corp                          │
├───────────────────────────────────────────────────────────────┤
│  授權（Authorization）：你能做什麼？                           │
│    ★★★★★ 由 ACL 決定 → （路徑, 使用者/群組/Token, 角色）       │
│    例：/vms/101 + ops@pve + PVEVMUser + propagate              │
│    ★★★★★ 跟你從哪個 Realm 來完全無關                           │
└───────────────────────────────────────────────────────────────┘
```

★★★★★ **這是初學者最大的誤解來源**：
「我把 AD 帳號同步進來了，為什麼還是什麼都看不到？」
—— 因為**同步只完成了認證，授權要另外給**。

### 二、四種 Realm ★★★★★

| Realm | 型態 | 認證來源 | 適用 | 重要度 |
| --- | --- | --- | --- | --- |
| ★★★★★ `pam` | 內建，不可刪 | ★★★★★ **節點上的 Linux 帳號**（`/etc/passwd` + PAM） | `root@pam` 是唯一的超級管理員 | ★★★★★ |
| ★★★★★ `pve` | 內建，不可刪 | ★★★★★ **PVE 自己的帳號資料庫**（`/etc/pve/user.cfg`，密碼在 `/etc/pve/priv/shadow.cfg`） | 給人用的日常管理帳號、自動化帳號 | ★★★★★ |
| ★★★★ `ldap` | 需建立 | 標準 LDAP 目錄（OpenLDAP、389DS…） | 已有 LDAP 的環境 | ★★★★ |
| ★★★★★ `ad` | 需建立 | ★★★★★ **Microsoft Active Directory** | 機關／企業最常見 | ★★★★★ |
| ★★★ `openid` | 需建立 | OpenID Connect（Keycloak、Entra ID…） | 有 SSO 的環境 | ★★★ |

> [!danger] ★★★★★ `root@pam` 的三件事
> 1. ★★★★★ **它是唯一擁有「無條件全權」的帳號** —— 不受 ACL 限制，連 `NoAccess` 都擋不住
> 2. ★★★★★ **它的密碼就是 Linux root 的密碼** —— 改 Web UI 密碼等於改 SSH 密碼
> 3. ★★★★★ **叢集裡任何一個節點的 root，就是全叢集的 root**
>
> ★★★★★ **日常管理絕對不要用 `root@pam`**。
> 建立 `pve` realm 的個人帳號並給予適當角色，
> 把 `root@pam` 當成「只在緊急救援時使用、且一定要開 2FA」的帳號。

★★★ **`pam` realm 的細節**：使用者必須先在 Linux 層存在。

```bash
# 先建 Linux 帳號
adduser opsuser
# 再在 PVE 註冊這個 pam 使用者
pveum user add opsuser@pam --comment "維運人員"
```

★★★★ 但實務上**不建議**用 `pam` 給一般管理員 ——
因為它同時給了對方 **SSH 登入節點的能力**，權限範圍遠大於你想給的。
★★★★★ **一般管理員用 `pve` realm。**

### 三、路徑式 ACL：PVE 權限模型的核心 ★★★★★

PVE 把所有可管理的東西排成**一棵樹**，權限授予在樹上的某個路徑，
★★★★★ **並可選擇是否往下繼承（propagate）**。

```
/                                    ★★★★★ 根，給這裡等於給全部
├── /access                          使用者、群組、Realm 管理
│   ├── /access/groups
│   ├── /access/realm/<realm>
│   └── /access/users/<userid>
├── /nodes                           節點層級操作
│   ├── /nodes/pve1                  ★★★★ shell、服務、更新、硬體
│   ├── /nodes/pve2
│   └── /nodes/pve3
├── /pool/<poolid>                   ★★★★★ 資源池 —— 最好用的授權單位
├── /sdn/zones/<zone>                SDN
├── /storage                         儲存
│   ├── /storage/local
│   ├── /storage/local-lvm
│   └── /storage/nfs-backup
└── /vms                             ★★★★ 所有 VM 與 CT
    ├── /vms/101
    ├── /vms/102
    └── /vms/201
```

**一條 ACL = 四個要素** ★★★★★：

```
路徑        誰                    角色           要不要往下繼承
/vms/101    ops@pve               PVEVMUser      propagate=1
/pool/dev   @developers（群組）    PVEVMAdmin     propagate=1
/storage    monitor@pve           PVEAuditor     propagate=1
```

```bash
pveum acl list
```

```text
┌──────────────┬──────────────────┬───────────┬───────────────┐
│ path         │ user/group/token │ propagate │ role          │
╞══════════════╪══════════════════╪═══════════╪═══════════════╡
│ /pool/dev    │ @developers      │         1 │ PVEVMAdmin    │
├──────────────┼──────────────────┼───────────┼───────────────┤
│ /storage     │ monitor@pve      │         1 │ PVEAuditor    │
├──────────────┼──────────────────┼───────────┼───────────────┤
│ /vms/101     │ ops@pve          │         1 │ PVEVMUser     │
└──────────────┴──────────────────┴───────────┴───────────────┘
```

### 四、繼承規則：三條你必須背下來的規則 ★★★★★

> [!note] ★★★★★ 規則一：propagate=1 時，權限往下傳給所有子路徑
> 在 `/vms` 給 `PVEVMUser` 且 `propagate=1`
> → 對 `/vms/101`、`/vms/102`、`/vms/201`… **全部**都有 `PVEVMUser`。
>
> `propagate=0` 則**只對那個路徑本身生效**，子路徑沒有。

> [!danger] ★★★★★ 規則二：更「深」的路徑會覆蓋更「淺」的路徑
> ```
> /vms        ops@pve  PVEVMAdmin  propagate=1     ← 全部 VM 都能管
> /vms/999    ops@pve  NoAccess    propagate=1     ← 但 999 這台看不到
> ```
> ★★★★★ **深度優先，不是聯集。**
> `/vms/999` 上的設定完全取代了從 `/vms` 繼承下來的那份。
>
> ★★★★★ 這是「**用 `NoAccess` 挖洞**」的做法 ——
> 想排除少數幾台 VM 時很好用，但也是**最容易讓人算錯權限**的地方。

> [!warning] ★★★★ 規則三：同一路徑上的多個角色會取聯集
> 同一個路徑上，如果使用者本人有 `PVEVMUser`，
> 而他所屬的群組有 `PVEVMAdmin`，
> ★★★★ **他實際擁有的是兩者權限的聯集**。
>
> ★★★★★ 但注意：**不同深度**之間是**覆蓋**（規則二），
> **同一深度**才是聯集。這兩者混在一起最容易算錯。

**權限判斷流程** ★★★★★：

```
使用者要對 /vms/101 做 VM.PowerMgmt
   │
   ├─ 是 root@pam 嗎？ → 是 → ★★★★★ 直接放行（不查 ACL）
   │
   ├─ 從最深的路徑往上找第一個有設定的層級：
   │     /vms/101 有嗎？ → 有 → ★★★★★ 用它，不再往上找
   │                     → 沒有 → 看 /vms（propagate=1 才算）
   │                     → 沒有 → 看 /（propagate=1 才算）
   │
   ├─ 把該層級上「這個使用者」+「他所屬群組」的角色取聯集
   │
   └─ 聯集裡有 VM.PowerMgmt 嗎？ → 有 → 放行；沒有 → 403
```

### 五、資源池（Pool）：實務上最好用的授權單位 ★★★★★

一台一台 VM 給權限，管理成本會爆炸。**Pool 是解法。**

```
/pool/prod        ← 正式環境的 VM 都丟進來
   ├── VM 101
   ├── VM 102
   └── storage nfs-prod

/pool/dev         ← 開發環境
   ├── VM 201
   └── CT 301
```

```bash
pveum pool add prod --comment "正式環境"
pveum pool modify prod --vms 101,102 --storage nfs-prod
pveum acl modify /pool/prod --groups ops --roles PVEVMAdmin
```

★★★★★ **好處**：新的 VM 只要「加入 pool」，權限自動就有了，
不用每次都改 ACL。**這是 PVE 授權管理的最佳實務。**

### 六、內建角色對照 ★★★★★

```bash
pveum role list
```

★★★★★ **常用的九個**：

| 角色 | 大致能做什麼 | 典型對象 | 重要度 |
| --- | --- | --- | --- |
| ★★★★★ `Administrator` | ★★★★★ **全部**（等同 root，但仍受 ACL 路徑限制） | 虛擬化管理員 | ★★★★★ |
| ★★★★ `NoAccess` | ★★★★★ **什麼都不行** —— 用來在繼承樹上挖洞 | 排除特定資源 | ★★★★★ |
| ★★★★★ `PVEAuditor` | ★★★★★ **唯讀** —— 看得到但改不了 | ★★★★★ **監控系統、稽核人員、主管** | ★★★★★ |
| ★★★★★ `PVEVMUser` | 開關機、開 console、看設定、做備份 | ★★★★★ **一般使用者、專案人員** | ★★★★★ |
| ★★★★ `PVEVMAdmin` | VM 的全部操作（含改設定、快照、遷移） | 系統管理員 | ★★★★ |
| ★★★★ `PVEDatastoreUser` | 在儲存上配置空間、看內容 | 需要傳 ISO／建磁碟的人 | ★★★★ |
| ★★★★ `PVEDatastoreAdmin` | 儲存的完整管理 | 儲存管理員 | ★★★ |
| ★★★ `PVEPoolAdmin` | 管理資源池成員 | 專案負責人 | ★★★ |
| ★★★★ `PVESysAdmin` | ★★★★★ **節點層級**：主控台、Syslog、系統設定 | ★★★★★ **權限很大，慎給** | ★★★★★ |
| ★★★ `PVEUserAdmin` | 管理使用者與群組 | 帳號管理員 | ★★★★ |
| ★★★ `PVETemplateUser` | 使用範本 | 只需從範本開機器的人 | ★★★ |

> [!warning] ★★★★★ `PVEVMUser` 裡有 `VM.Console`
> 給了 `PVEVMUser` 就等於**給了進入該 VM 作業系統主控台的能力**。
> 對方在 console 裡做什麼，PVE 完全管不到。
> ★★★★★ **只想讓人「看看狀態」的話，給 `PVEAuditor`，不要給 `PVEVMUser`。**

★★★★★ **權限項目（privileges）** —— 自訂角色時要挑的積木：

| 分類 | 常見權限項 | 意義 | 重要度 |
| --- | --- | --- | --- |
| VM | `VM.Audit` | ★★★★ 看得到這台 VM 與它的設定 | ★★★★★ |
| VM | `VM.PowerMgmt` | 開機／關機／重開 | ★★★★★ |
| VM | `VM.Console` | ★★★★★ **進入 guest 主控台** | ★★★★★ |
| VM | `VM.Config.Disk` / `.Network` / `.CPU` / `.Memory` / `.Options` / `.HWType` / `.CDROM` / `.Cloudinit` | 改各類設定 | ★★★★ |
| VM | ★★★★ `VM.Backup` | **做備份與還原** | ★★★★★ |
| VM | `VM.Snapshot` / `VM.Snapshot.Rollback` | 快照／回復快照 | ★★★★ |
| VM | ★★★★★ `VM.Allocate` | **建立與刪除 VM** | ★★★★★ |
| VM | `VM.Clone` | 複製 | ★★★★ |
| VM | `VM.Migrate` | 遷移 | ★★★★ |
| VM | `VM.Monitor` | ★★★★★ **QEMU monitor 主控台**，等同繞過一切 | ★★★★★ |
| 儲存 | `Datastore.Audit` | 看儲存 | ★★★★ |
| 儲存 | `Datastore.AllocateSpace` | ★★★★ **在儲存上配置空間**（建磁碟、寫備份要靠它） | ★★★★★ |
| 儲存 | `Datastore.Allocate` | ★★★★★ **建立／刪除儲存定義本身** | ★★★★★ |
| 儲存 | `Datastore.AllocateTemplate` | 上傳 ISO／範本 | ★★★★ |
| 系統 | `Sys.Audit` | 看節點狀態、設定、叢集資訊 | ★★★★ |
| 系統 | ★★★★★ `Sys.Console` | **節點的 root shell** | ★★★★★ |
| 系統 | `Sys.Modify` | 改節點設定（網路等） | ★★★★★ |
| 系統 | `Sys.PowerMgmt` | 節點開關機 | ★★★★★ |
| 系統 | `Sys.Syslog` | 讀系統日誌 | ★★★★ |
| 權限 | ★★★★★ `Permissions.Modify` | **修改 ACL** —— 給了等於給全部 | ★★★★★ |
| 使用者 | `User.Modify` / `Group.Allocate` / `Realm.AllocateUser` | 帳號管理 | ★★★★ |
| 池 | `Pool.Allocate` / `Pool.Audit` | 資源池管理 | ★★★ |

> [!danger] ★★★★★ 三個「給了就等於給全部」的權限
> | 權限 | 為什麼等於全權 |
> | --- | --- |
> | ★★★★★ `Permissions.Modify` | 他可以把自己升成 `Administrator` |
> | ★★★★★ `Sys.Console` | 他可以在節點上開 root shell，直接改任何東西 |
> | ★★★★★ `VM.Monitor` | QEMU monitor 可以做遠超過「管理一台 VM」的事 |
>
> ★★★★ 另外 `Datastore.Allocate`（不是 `AllocateSpace`）也很危險 ——
> 他可以刪掉整個儲存定義。

### 七、API Token 與權限分離 ★★★★★

自動化腳本、監控系統、備份工具**不應該拿密碼**。它們該拿 **API Token**。

```
Token 的完整識別：  <使用者>@<realm>!<tokenid>
                    backup@pve!nightly

Token 的秘密值：    只在建立當下顯示一次 ★★★★★
                    a1b2c3d4-5e6f-7a8b-9c0d-1e2f3a4b5c6d
```

★★★★★ **`privsep`（privilege separation，權限分離）是最重要的旗標**：

| `privsep` | 行為 | 何時用 | 重要度 |
| --- | --- | --- | --- |
| ★★★★★ `1`（**建議預設**） | ★★★★★ **Token 有自己獨立的 ACL**；實際權限 = 使用者權限 **∩** Token 權限 | ★★★★★ **幾乎所有情況** | ★★★★★ |
| ★★★ `0` | ★★★★★ **Token 完全繼承使用者的全部權限** | 只有在你確定使用者本身就是最小權限時 | ★★★★★ |

```
privsep=1 的效果：

  使用者 backup@pve 的權限   ┌─────────────────────┐
                             │ VM.Audit  VM.Backup │
                             │ Datastore.*         │
                             └──────────┬──────────┘
                                        │ 交集 ∩
  Token backup@pve!nightly  ┌───────────┴─────────┐
                            │ VM.Audit  VM.Backup │
                            └───────────┬─────────┘
                                        ▼
              ★★★★★ Token 實際能做的：VM.Audit + VM.Backup
```

> [!danger] ★★★★★ `privsep=1` 建立後「什麼權限都沒有」是正常的
> 這是最多人卡住的地方：
> 建好 Token、curl 打過去卻只看到空清單或 403。
> ★★★★★ **因為 `privsep=1` 的 Token 需要「另外」用 `pveum acl modify --tokens` 授權。**
> 只給使用者授權是不夠的（那只是交集的其中一半）。

> [!danger] ★★★★★ Token secret 只顯示一次
> 建立時的輸出裡那串 UUID，**關掉視窗就再也看不到**。
> 弄丟只能刪掉重建。
> ★★★★★ **建立當下就存進密碼管理系統**，不要貼在聊天室或寫進 git。

★★★★ **Token 的另一個好處：可以個別撤銷**。
腳本外洩時，刪掉那個 Token 就好，**不用改使用者密碼、不影響其他自動化**。

### 八、API 的兩種認證方式 ★★★★

| 方式 | Header | 適用 | 重要度 |
| --- | --- | --- | --- |
| ★★★★★ **API Token** | `Authorization: PVEAPIToken=USER@REALM!TOKEN=SECRET` | ★★★★★ **腳本、自動化、監控** —— 無狀態，不會過期 | ★★★★★ |
| ★★★★ **Ticket（登入票）** | Cookie `PVEAuthCookie=<ticket>` + Header `CSRFPreventionToken` | Web UI 本身；需要模擬互動登入時 | ★★★★ |

★★★★★ **寫入類請求（POST／PUT／DELETE）用 Ticket 時，一定要帶 `CSRFPreventionToken`**，
否則會 401。用 API Token 則**不需要** CSRF token。

---

## 安裝或基礎操作

### 1. 看目前有誰 ★★★★

```bash
pveum user list
```

```text
┌──────────────┬─────────┬─────────┬────────┬──────┬────────┬───────────┐
│ userid       │ comment │ email   │ enable │ expi │ firstn │ lastname  │
╞══════════════╪═════════╪═════════╪════════╪══════╪════════╪═══════════╡
│ root@pam     │         │         │      1 │    0 │        │           │
└──────────────┴─────────┴─────────┴────────┴──────┴────────┴───────────┘
```

```bash
pveum group list
pveum role list
pveum acl list
```

```bash
# 看自己現在的權限（★★★★★ 排查權限問題的第一個指令）
pveum user permissions ops@pve
```

```text
┌────────────┬────────────────────────┬────────────┐
│ path       │ permission             │ propagate  │
╞════════════╪════════════════════════╪════════════╡
│ /pool/dev  │ VM.Audit               │          1 │
│ /pool/dev  │ VM.Console             │          1 │
│ /pool/dev  │ VM.PowerMgmt           │          1 │
└────────────┴────────────────────────┴────────────┘
```

★★★★★ **這個指令會把繼承算完之後的「最終有效權限」列出來**，
比自己用腦袋推 ACL 樹可靠得多。**排查權限問題一律先跑這個。**

### 2. 建立群組與使用者 ★★★★★

```bash
# ★★★★★ 先建群組 —— 權限給群組，不要給個人
pveum group add ops --comment "虛擬化維運組"
pveum group add auditors --comment "稽核唯讀"
```

```bash
pveum user add wang@pve --comment "王小明" --email wang@example.gov.tw --groups ops
```

```bash
# 設定密碼（互動輸入）
pveum passwd wang@pve
```

```text
Enter new password: ****
Retype new password: ****
```

```bash
pveum user list
```

```text
┌──────────────┬──────────┬────────────────────┬────────┐
│ userid       │ comment  │ email              │ enable │
╞══════════════╪══════════╪════════════════════╪════════╡
│ root@pam     │          │                    │      1 │
│ wang@pve     │ 王小明   │ wang@example.gov.tw│      1 │
└──────────────┴──────────┴────────────────────┴────────┘
```

★★★★ **停用而不刪除**（人員離職／留職停薪時的正確做法）：

```bash
pveum user modify wang@pve --enable 0
```

★★★★ **設定到期日**（廠商臨時帳號一定要用）：

```bash
# expire 是 UNIX timestamp，0 = 永不過期
pveum user modify vendor@pve --expire $(date -d "2026-12-31" +%s)
```

### 3. 授權 ★★★★★

```bash
# 給群組唯讀全叢集
pveum acl modify / --groups auditors --roles PVEAuditor --propagate 1
```

```bash
# 給 ops 群組管理 dev 資源池
pveum pool add dev --comment "開發環境"
pveum acl modify /pool/dev --groups ops --roles PVEVMAdmin --propagate 1
```

```bash
# ★★★★ 在繼承樹上挖洞：ops 管得了 dev，但不准碰 VM 299
pveum acl modify /vms/299 --groups ops --roles NoAccess --propagate 1
```

```bash
pveum acl list
```

```text
┌────────────┬──────────────────┬───────────┬─────────────┐
│ path       │ user/group/token │ propagate │ role        │
╞════════════╪══════════════════╪═══════════╪═════════════╡
│ /          │ @auditors        │         1 │ PVEAuditor  │
│ /pool/dev  │ @ops             │         1 │ PVEVMAdmin  │
│ /vms/299   │ @ops             │         1 │ NoAccess    │
└────────────┴──────────────────┴───────────┴─────────────┘
```

```bash
# ★★★★ 撤銷授權（--delete 1）
pveum acl modify /vms/299 --groups ops --roles NoAccess --delete 1
```

### 4. 自訂角色 ★★★★★

內建角色常常「多給了一點」。要真正的最小權限就自訂：

```bash
pveum role add PVEPowerOnly --privs "VM.Audit,VM.PowerMgmt"
```

```bash
pveum role list | grep PVEPowerOnly
```

```text
│ PVEPowerOnly     │ VM.Audit,VM.PowerMgmt                    │
```

```bash
# 修改角色（★★★★★ --privs 是「整組取代」，不是追加）
pveum role modify PVEPowerOnly --privs "VM.Audit,VM.PowerMgmt,VM.Console"
```

> [!warning] ★★★★★ `pveum role modify --privs` 會整組覆蓋
> 想「加一個權限」時，必須把**原本的權限全部重打一次**再加上新的。
> 只打新的那一個，舊的會全部消失。
> ★★★★★ **改之前先 `pveum role list` 抄下現有的清單。**

```bash
pveum role delete PVEPowerOnly
```

### 5. 建立 API Token ★★★★★

```bash
# ★★★★★ privsep=1（預設就是 1，但建議明確寫出來）
pveum user token add backup@pve nightly --privsep 1 --comment "每晚備份腳本"
```

```text
┌──────────────┬──────────────────────────────────────┐
│ key          │ value                                │
╞══════════════╪══════════════════════════════════════╡
│ full-tokenid │ backup@pve!nightly                   │
├──────────────┼──────────────────────────────────────┤
│ info         │ {"comment":"每晚備份腳本","privsep":1}│
├──────────────┼──────────────────────────────────────┤
│ value        │ 3f7c9a12-4b8e-4c1d-9f2a-6e5d8b0c7a13 │
└──────────────┴──────────────────────────────────────┘
```

★★★★★ **`value` 那一行就是 secret，只會出現這一次。**

```bash
pveum user token list backup@pve
```

```text
┌─────────┬─────────┬───────────────────┬─────────┐
│ tokenid │ comment │ expire            │ privsep │
╞═════════╪═════════╪═══════════════════╪═════════╡
│ nightly │ 每晚... │                 0 │       1 │
└─────────┴─────────┴───────────────────┴─────────┘
```

```bash
# ★★★★★ privsep=1 的 Token 一定要另外授權
pveum acl modify /vms --tokens 'backup@pve!nightly' --roles PVEBackup --propagate 1
```

```bash
# 看 Token 的有效權限
pveum user token permissions backup@pve nightly
```

```bash
# 撤銷
pveum user token remove backup@pve nightly
```

### 6. `pvesh`：在節點上直接打 API ★★★★★

`pvesh` 是 API 的命令列前端，**用的是本機 root 權限**，
非常適合用來「先確認 API 路徑與參數長什麼樣」。

```bash
pvesh get /nodes
```

```text
┌──────┬────────┬───────┬───────────┬────────┬───────────┬────────┬────────────┐
│ node │ status │ cpu   │ maxcpu    │ mem    │ maxmem    │ uptime │ ssl_finger │
╞══════╪════════╪═══════╪═══════════╪════════╪═══════════╪════════╪════════════╡
│ pve1 │ online │ 3.2%  │        16 │ 12.4G  │     62.7G │ 452301 │ AB:CD:...  │
│ pve2 │ online │ 1.8%  │        16 │  8.1G  │     62.7G │ 451890 │ 12:34:...  │
└──────┴────────┴───────┴───────────┴────────┴───────────┴────────┴────────────┘
```

```bash
# ★★★★★ 最實用的一個：一次看到全叢集所有資源
pvesh get /cluster/resources --output-format json-pretty
```

```json
[
   {
      "cpu" : 0.0213,
      "disk" : 0,
      "id" : "qemu/101",
      "maxcpu" : 2,
      "maxdisk" : 34359738368,
      "maxmem" : 4294967296,
      "mem" : 1073741824,
      "name" : "web01",
      "node" : "pve1",
      "status" : "running",
      "template" : 0,
      "type" : "qemu",
      "uptime" : 84210,
      "vmid" : 101
   }
]
```

```bash
# 查某個路徑支援哪些操作與參數（★★★★★ 寫腳本前必跑）
pvesh usage /nodes/{node}/qemu/{vmid}/status/start -v
```

```text
USAGE: pvesh create /nodes/{node}/qemu/{vmid}/status/start [OPTIONS]

  Start virtual machine.

  <node>      string
              The cluster node name.
  <vmid>      integer (100 - N)
              The (unique) ID of the VM.
  --timeout   integer (0 - N)   (optional)
              Wait maximal timeout seconds.
  ...
```

| `pvesh` 動作 | 對應 HTTP | 用途 | 重要度 |
| --- | --- | --- | --- |
| ★★★★★ `pvesh get <path>` | `GET` | 讀取 | ★★★★★ |
| ★★★★ `pvesh create <path>` | `POST` | 建立／執行動作 | ★★★★★ |
| ★★★★ `pvesh set <path>` | `PUT` | 修改 | ★★★★ |
| ★★★★ `pvesh delete <path>` | `DELETE` | 刪除 | ★★★★★ |
| ★★★★ `pvesh ls <path>` | — | 列出子路徑 | ★★★★ |
| ★★★★★ `pvesh usage <path> -v` | — | **查參數** | ★★★★★ |

```bash
pvesh ls /nodes/pve1
```

```text
Dr---  apt
Dr---  ceph
Dr---  disks
Dr---  lxc
Dr---  network
Dr---  qemu
Dr---  storage
-r---  status
...
```

```bash
# 啟動一台 VM
pvesh create /nodes/pve1/qemu/101/status/start
```

```text
UPID:pve1:00001A2B:0123ABCD:66D5F1A0:qmstart:101:root@pam:
```

★★★★ **回傳的 `UPID` 是工作編號**，可以拿去查進度：

```bash
pvesh get /nodes/pve1/tasks/UPID:pve1:00001A2B:0123ABCD:66D5F1A0:qmstart:101:root@pam:/status
```

```text
┌────────────┬──────────────────────────────────────────────┐
│ key        │ value                                        │
╞════════════╪══════════════════════════════════════════════╡
│ exitstatus │ OK                                           │
│ status     │ stopped                                      │
│ type       │ qmstart                                      │
└────────────┴──────────────────────────────────────────────┘
```

### 7. 用 curl 打 REST API ★★★★★

**API 端點**：`https://<節點>:8006/api2/json/<路徑>`

**方式 A：API Token（推薦）** ★★★★★

```bash
export PVE_HOST="https://pve1.lab.local:8006"
export PVE_TOKEN="PVEAPIToken=backup@pve!nightly=3f7c9a12-4b8e-4c1d-9f2a-6e5d8b0c7a13"

curl -sS -H "Authorization: $PVE_TOKEN" \
  "$PVE_HOST/api2/json/version"
```

```json
{"data":{"release":"8.x","repoid":"xxxxxxxx","version":"8.x.x"}}
```

```bash
# 加 jq 好讀
curl -sS -H "Authorization: $PVE_TOKEN" \
  "$PVE_HOST/api2/json/cluster/resources?type=vm" | jq -r \
  '.data[] | "\(.vmid)\t\(.name)\t\(.node)\t\(.status)"'
```

```text
101	web01	pve1	running
102	db01	pve1	running
201	logsrv	pve2	running
```

**方式 B：Ticket 登入** ★★★★

```bash
# 1. 取得 ticket 與 CSRF token
curl -sS -k -d "username=wang@pve&password=SuperSecret" \
  "$PVE_HOST/api2/json/access/ticket" | jq .
```

```json
{
  "data": {
    "CSRFPreventionToken": "66D5F1A0:ExAmPlEcSrFtOkEn",
    "ticket": "PVE:wang@pve:66D5F1A0::AbCdEf...==",
    "username": "wang@pve"
  }
}
```

```bash
TICKET=$(curl -sS -k -d "username=wang@pve&password=SuperSecret" \
  "$PVE_HOST/api2/json/access/ticket" | jq -r '.data.ticket')
CSRF=$(curl -sS -k -d "username=wang@pve&password=SuperSecret" \
  "$PVE_HOST/api2/json/access/ticket" | jq -r '.data.CSRFPreventionToken')

# 2. GET 只要 cookie
curl -sS -k -b "PVEAuthCookie=$TICKET" "$PVE_HOST/api2/json/nodes" | jq .

# 3. ★★★★★ 寫入類請求一定要帶 CSRFPreventionToken
curl -sS -k -b "PVEAuthCookie=$TICKET" \
  -H "CSRFPreventionToken: $CSRF" \
  -X POST "$PVE_HOST/api2/json/nodes/pve1/qemu/101/status/start"
```

> [!warning] ★★★★★ 不要習慣性加 `-k`
> `-k` 是「不驗證伺服器憑證」。在正式環境用它，
> 等於**放棄了防中間人攻擊的保護** —— 你的 Token secret 可能被攔截。
>
> ★★★★★ **正解**：給 PVE 換上受信任的憑證（見 [[090-01-10-guide-PKI-憑證部署到各服務]]），
> 或把自建 CA 的根憑證裝進呼叫端的信任區
> （見 [[090-01-09-guide-PKI-根憑證派送與信任]]），然後**把 `-k` 拿掉**。

★★★★ **HTTP 狀態碼對照**：

| 狀態 | 意義 | 常見原因 | 重要度 |
| --- | --- | --- | --- |
| `200` | 成功 | — | ★★★ |
| ★★★★★ `401` | **認證失敗** | Token 格式錯、secret 打錯、ticket 過期、缺 CSRF token | ★★★★★ |
| ★★★★★ `403` | ★★★★★ **認證成功但權限不足** | ACL 沒給、`privsep=1` 忘記授權給 Token | ★★★★★ |
| `404` | 路徑不存在 | 路徑打錯、VMID 不存在 | ★★★★ |
| `500` | 伺服器端錯誤 | 參數不合法、叢集無 Quorum | ★★★★ |
| `595/596/599` | ★★★★ PVE 內部代理錯誤（跨節點轉發失敗） | 目標節點離線 | ★★★★ |

★★★★★ **401 跟 403 要分清楚**：
401 = 「你是誰我不認識」→ 查 Token／密碼；
403 = 「認識你，但你不能做這件事」→ 查 ACL。

---

## 進階應用

### 一、雙因素驗證（2FA） ★★★★★

| 型態 | 說明 | 適用 | 重要度 |
| --- | --- | --- | --- |
| ★★★★★ `totp` | Google Authenticator／Microsoft Authenticator 之類的 6 位數 | ★★★★★ **最通用，建議全面採用** | ★★★★★ |
| ★★★★ `webauthn` | 實體安全金鑰（YubiKey）或平台驗證器 | 高權限帳號 | ★★★★ |
| ★★★ `yubico` | Yubico OTP 驗證伺服器 | 已有 Yubico 基礎建設 | ★★★ |
| ★★★★★ `recovery` | ★★★★★ **一次性救援碼** —— **一定要一起產生並離線保管** | 所有開了 2FA 的帳號 | ★★★★★ |

**在 Web UI 設定**（一般使用者自己做）：
`右上角使用者選單 → TFA` 或 `Datacenter → Permissions → Two Factor`。

**命令列查看與刪除**（管理員救援用）：

```bash
pveum user tfa list
```

```text
┌──────────────┬──────────┬──────────────────────────────────────┐
│ userid       │ type     │ id                                   │
╞══════════════╪══════════╪══════════════════════════════════════╡
│ wang@pve     │ totp     │ 3f2a...                              │
│ wang@pve     │ recovery │ 8c1b...                              │
└──────────────┴──────────┴──────────────────────────────────────┘
```

```bash
# ★★★★★ 使用者手機掉了、救援碼也用光時的解法：刪掉他的 TFA
pveum user tfa delete wang@pve
```

> [!danger] ★★★★★ `root@pam` 開了 2FA 又弄丟驗證器怎麼辦
> 這是**最容易把自己鎖在門外**的情況。
> ★★★★★ **開 2FA 的當下就要做的三件事**：
> 1. **同時產生 recovery key**，列印出來鎖進保險櫃
> 2. 確認你**還有 SSH／IPMI／實體主控台**可以進節點
>    （2FA 只擋 Web UI／API，不擋 SSH）
> 3. 至少有**兩個**擁有 `Administrator` 的帳號
>
> 真的鎖住時，從 SSH 進節點執行 `pveum user tfa delete root@pam`。
> ★★★★★ **所以「SSH 的保護」跟 2FA 一樣重要** —— 見 [[020-02-01-07-svc-SSH-安全強化]]。

★★★★ **在 Realm 層強制要求 2FA**（`Datacenter → Realms → 編輯 → TFA`），
可以讓整個 realm 的使用者非設不可。

### 二、AD 整合 ★★★★★

**前置條件**（★★★★★ 這五項先確認，可以省掉九成的卡關）：

| # | 條件 | 驗證方式 | 重要度 |
| --- | --- | --- | --- |
| 1 | ★★★★★ **PVE 節點的 DNS 指向 AD DC** | `dig SRV _ldap._tcp.corp.local` | ★★★★★ |
| 2 | ★★★★★ **時間同步**（Kerberos／LDAP 對時間敏感） | `timedatectl` | ★★★★★ |
| 3 | ★★★★★ **有一個 bind 用的服務帳號**（唯讀即可） | AD 端建立 | ★★★★★ |
| 4 | ★★★★ **知道 Base DN** | `dsquery` 或 AD 使用者及電腦 | ★★★★ |
| 5 | ★★★★★ **要用 LDAPS 的話，DC 的憑證鏈要能被 PVE 驗證** | 見下方 | ★★★★★ |

```bash
# 條件 1 驗證
dig +short SRV _ldap._tcp.corp.local
```

```text
0 100 389 dc01.corp.local.
0 100 389 dc02.corp.local.
```

```bash
# 從 PVE 直接測 LDAP 連線（★★★★★ 建 realm 之前先測這個）
apt install -y ldap-utils
ldapsearch -x -H ldaps://dc01.corp.local:636 \
  -D "CN=pve-bind,OU=Service,DC=corp,DC=local" -W \
  -b "DC=corp,DC=local" "(sAMAccountName=wang)" dn
```

```text
Enter LDAP Password: ****
# extended LDIF
...
dn: CN=王小明,OU=Users,DC=corp,DC=local
```

★★★★★ **`ldapsearch` 通了，PVE 的 realm 才有可能通。**
`ldapsearch` 不通就先別去動 PVE 設定 —— 問題在網路、DNS 或憑證。

**建立 AD realm**：

```bash
pveum realm add corp \
  --type ad \
  --domain corp.local \
  --server1 dc01.corp.local \
  --server2 dc02.corp.local \
  --secure 1 \
  --port 636 \
  --bind-dn "CN=pve-bind,OU=Service,DC=corp,DC=local" \
  --comment "公司 AD"
```

```bash
# 存 bind 帳號的密碼
pveum realm modify corp --password
```

```bash
pveum realm list
```

```text
┌────────┬──────┬─────────┬──────────┐
│ realm  │ type │ comment │ tfa      │
╞════════╪══════╪═════════╪══════════╡
│ corp   │ ad   │ 公司 AD │          │
│ pam    │ pam  │ Linux P │          │
│ pve    │ pve  │ Proxmox │          │
└────────┴──────┴─────────┴──────────┘
```

**LDAPS 憑證驗證** ★★★★★：

```bash
# 把 AD 的根 CA 憑證放進去
mkdir -p /etc/pve/priv/realm-ca
cp corp-root-ca.crt /usr/local/share/ca-certificates/corp-root-ca.crt
update-ca-certificates
```

```text
Updating certificates in /etc/ssl/certs...
1 added, 0 removed; done.
```

```bash
pveum realm modify corp --verify 1
```

> [!danger] ★★★★★ 不要用 `--verify 0` 當作解法
> 看到憑證錯誤就把驗證關掉，等於**用明文 LDAP 的安全等級**跑 LDAPS ——
> 中間人可以攔截你的 bind 帳號密碼與整份使用者清單。
>
> ★★★★★ **正確做法是把 AD 的根 CA 裝進 PVE 的信任區**（上面那三行）。
> 見 [[090-01-09-guide-PKI-根憑證派送與信任]]。

**同步使用者** ★★★★★：

```bash
# ★★★★★ 第一次一定要先 dry-run，看它會做什麼
pveum realm sync corp --dry-run 1
```

```text
starting sync for realm corp
dry run: would add user 'wang@corp'
dry run: would add user 'lee@corp'
dry run: would add group 'vm-admins@corp'
sync completed (dry run)
```

```bash
# 正式同步
pveum realm sync corp --scope both --enable-new 0
```

```text
starting sync for realm corp
adding user 'wang@corp'
adding user 'lee@corp'
adding group 'vm-admins@corp'
sync completed
```

| 參數 | 意義 | 重要度 |
| --- | --- | --- |
| ★★★★★ `--dry-run 1` | **只看不做** —— 第一次一定要跑 | ★★★★★ |
| ★★★★ `--scope users` / `groups` / `both` | 同步範圍 | ★★★★ |
| ★★★★★ `--enable-new 0` | ★★★★★ **新同步進來的使用者預設「停用」** —— 避免整個 AD 的人一次全部能登入 | ★★★★★ |
| ★★★★ `--remove-vanished` | 處理 AD 端已刪除的帳號（謹慎使用） | ★★★★ |

> [!danger] ★★★★★ `--enable-new 1` 加上同步整個網域 = 全公司都能登入你的虛擬化平台
> 就算他們沒有任何 ACL（登入後看不到東西），
> ★★★★★ **這仍然是一個嚴重的攻擊面** ——
> 任何一個 AD 帳號被盜，攻擊者就能打你的 PVE API。
>
> ★★★★★ **正解**：
> 1. `--enable-new 0`，管理員手動啟用需要的人
> 2. **或**在 realm 設定裡用 filter 只同步特定 OU／群組的成員
> 3. **或**在 Realm 層強制 2FA

★★★★ **設定排程同步**（Web UI：`Datacenter → Realms → 選 realm → Sync Options`；
或建立 realm sync job）。同步只更新帳號存在與否，**不會動 ACL**。

**授權給 AD 群組** ★★★★★：

```bash
# ★★★★★ 同步進來的 AD 群組，名稱一樣要帶 @realm
pveum acl modify /pool/prod --groups 'vm-admins@corp' --roles PVEVMAdmin --propagate 1
```

★★★★★ **這一步才是「AD 使用者真的能用 PVE」的關鍵。**
同步只做認證，授權永遠要在 PVE 這邊給。

> [!info]- OpenLDAP（`--type ldap`）對照
> AD 型態很多欄位有預設值，OpenLDAP 要自己填清楚：
> ```bash
> pveum realm add ldapdir \
>   --type ldap \
>   --server1 ldap01.lab.local \
>   --port 636 --secure 1 \
>   --base-dn "dc=lab,dc=local" \
>   --user-attr uid \
>   --bind-dn "cn=readonly,dc=lab,dc=local"
> pveum realm modify ldapdir --password
> ```
> | 差異 | AD (`ad`) | OpenLDAP (`ldap`) |
> | --- | --- | --- |
> | 必填 | `--domain` | ★★★★ `--base-dn`、`--user-attr` |
> | 使用者屬性 | 預設 `sAMAccountName` | ★★★★ 通常是 `uid` |
> | 群組同步 | 依 AD 群組物件 | 依 `--group-classes`／`--group-filter` |
>
> ★★★★ 兩者共通：**都要處理 LDAPS 憑證、都要另外給 ACL**。

### 三、AD／LDAP 六個最常卡住的地方 ★★★★★

| # | 卡關現象 | 真正原因 | 解法 | 重要度 |
| --- | --- | --- | --- | --- |
| 1 | 登入頁選了 realm 但一直 `authentication failure` | ★★★★ 使用者名稱格式不對（打了 `CORP\wang` 或完整 UPN） | ★★★★★ **只填 `wang`，realm 由下拉選單決定** | ★★★★★ |
| 2 | `Connection error` / `Can't contact LDAP server` | DNS 解析不到 DC，或防火牆擋 636/389 | ★★★★ `dig`、`nc -zv dc01.corp.local 636` | ★★★★★ |
| 3 | ★★★★★ **憑證驗證失敗** | DC 憑證由內部 CA 簽發，PVE 不信任 | ★★★★★ 把根 CA 放進 `/usr/local/share/ca-certificates/` 並 `update-ca-certificates`；**不要用 `--verify 0`** | ★★★★★ |
| 4 | ★★★★★ **同步成功，使用者能登入但「什麼都看不到」** | ★★★★★ **只做了認證，沒給 ACL** | ★★★★★ `pveum acl modify /pool/xxx --users 'wang@corp' --roles ...` | ★★★★★ |
| 5 | 同步不到任何使用者／群組 | Base DN 寫錯、bind 帳號權限不足、filter 過嚴 | ★★★★ 先用 `ldapsearch` 用同一組 DN 驗證得到結果 | ★★★★★ |
| 6 | ★★★★ 同步隔天全部失效、或間歇性登入失敗 | ★★★★★ **時間偏移**、或只設一台 DC 而它剛好重開 | ★★★★★ `timedatectl set-ntp true`；設定 `--server2` 備援 DC | ★★★★★ |

### 四、實用的 API 自動化片段 ★★★★

```bash
#!/bin/bash
# 用 API Token 列出所有停機的 VM（★★★★ 可以排進每日巡檢）
set -euo pipefail

PVE_HOST="https://pve1.lab.local:8006"
PVE_TOKEN="PVEAPIToken=monitor@pve!checker=<secret>"

curl -sS --fail \
  -H "Authorization: $PVE_TOKEN" \
  "$PVE_HOST/api2/json/cluster/resources?type=vm" \
| jq -r '.data[] | select(.template != 1) | select(.status != "running")
         | "\(.node)\t\(.vmid)\t\(.name)\t\(.status)"'
```

```text
pve2	205	test-old	stopped
pve3	310	archive	stopped
```

```bash
#!/bin/bash
# 用 API 觸發一次備份並等待完成 ★★★★
set -euo pipefail
PVE_HOST="https://pve1.lab.local:8006"
PVE_TOKEN="PVEAPIToken=backup@pve!nightly=<secret>"
NODE="pve1"; VMID=101; STORAGE="nfs-backup"

UPID=$(curl -sS --fail -H "Authorization: $PVE_TOKEN" \
  -X POST \
  --data-urlencode "vmid=${VMID}" \
  --data-urlencode "storage=${STORAGE}" \
  --data-urlencode "mode=snapshot" \
  --data-urlencode "compress=zstd" \
  "$PVE_HOST/api2/json/nodes/${NODE}/vzdump" | jq -r '.data')

echo "任務已送出：$UPID"

while true; do
  ST=$(curl -sS --fail -H "Authorization: $PVE_TOKEN" \
    --get --data-urlencode "upid=${UPID}" \
    "$PVE_HOST/api2/json/nodes/${NODE}/tasks/${UPID}/status")
  RUNNING=$(echo "$ST" | jq -r '.data.status')
  [ "$RUNNING" != "running" ] && break
  sleep 10
done

echo "$ST" | jq -r '"結果：\(.data.exitstatus)"'
```

```text
任務已送出：UPID:pve1:00002F3A:0456BCDE:66D5F2B0:vzdump:101:backup@pve!nightly:
結果：OK
```

★★★★ **`--data-urlencode` 很重要** —— 參數裡有中文或特殊字元時，
不用它會送出壞掉的請求。

### 五、稽核：誰做了什麼 ★★★★★

```bash
# 叢集層的工作紀錄（★★★★★ 每次事故都要看）
pvesh get /cluster/tasks --output-format json-pretty | jq -r \
  '.[] | "\(.starttime)\t\(.node)\t\(.user)\t\(.type)\t\(.id)\t\(.status // "running")"' | head
```

```text
1756789012	pve1	backup@pve!nightly	vzdump	101	OK
1756788800	pve1	wang@pve	        qmstart	101	OK
1756788010	pve1	root@pam	        qmdestroy 205	OK
```

★★★★★ **`user` 欄位會顯示到 Token 層級**（`backup@pve!nightly`），
這正是「每個自動化用獨立 Token」的價值：**出事時查得到是哪個腳本做的**。

```bash
# 認證失敗紀錄
journalctl -u pveproxy --since "1 day ago" | grep -i "authentication failure"
```

```text
pveproxy[2201]: authentication failure; rhost=203.0.113.55 user=admin@pve msg=invalid credentials
pveproxy[2201]: authentication failure; rhost=203.0.113.55 user=root@pam msg=invalid credentials
```

★★★★★ **同一個來源 IP 連續嘗試不同帳號 = 暴力破解。**
搭配 Fail2ban（[[090-02-05-guide-防護-Fail2ban入侵防護]]）自動封鎖。

### 六、設定檔在哪 ★★★★

| 檔案 | 內容 | 重要度 |
| --- | --- | --- |
| ★★★★★ `/etc/pve/user.cfg` | 使用者、群組、資源池、Token、**ACL**（叢集共享） | ★★★★★ |
| ★★★★ `/etc/pve/domains.cfg` | Realm 定義 | ★★★★ |
| ★★★★★ `/etc/pve/priv/shadow.cfg` | `pve` realm 的密碼雜湊 | ★★★★★ |
| ★★★★★ `/etc/pve/priv/token.cfg` | ★★★★★ **API Token 的秘密值** | ★★★★★ |
| ★★★★ `/etc/pve/priv/tfa.cfg` | 2FA 設定 | ★★★★ |
| ★★★★ `/etc/pve/priv/realm.pw` 等 | LDAP／AD bind 密碼 | ★★★★★ |

```bash
cat /etc/pve/user.cfg
```

```text
user:root@pam:1:0::::::
user:wang@pve:1:0::王小明:wang@example.gov.tw:::
user:backup@pve:1:0:::::: 

group:ops:wang@pve::虛擬化維運組:
group:auditors:::稽核唯讀:

token:backup@pve!nightly:0:1:每晚備份腳本:

pool:prod::正式環境:101,102:nfs-prod:

acl:1:/pool/prod:@ops:PVEVMAdmin:
acl:1:/vms:backup@pve!nightly:PVEBackup:
acl:1:/:@auditors:PVEAuditor:
```

> [!danger] ★★★★★ `/etc/pve/priv/` 底下的東西等同密碼
> `token.cfg` 裡是**明文可用的 Token secret**，
> `shadow.cfg` 是密碼雜湊，`realm.pw` 是 AD bind 密碼。
> - ★★★★★ **這些檔案會被 `vzdump` 以外的節點備份帶走** —— 備份檔要當機密資料保管
> - ★★★★★ **不要把 `/etc/pve` 整包丟到不受保護的地方**（NAS 共用資料夾、git）
> - ★★★★ 權限應該是 root 專屬，不要去改

---

## 完整實戰範例

★★★★★ **目標**：做出一個「**只能備份、不能刪 VM**」的 API Token，
給每晚的備份腳本使用，並用 curl **實測到 403** 證明權限真的被擋住。

### 環境

| 項目 | 值 |
| --- | --- |
| 節點 | `pve1.lab.local`（PVE 8） |
| 備份儲存 | `nfs-backup` |
| 測試 VM | `101`（web01，執行中） |
| 要建立的使用者 | `backup@pve` |
| 要建立的 Token | `backup@pve!nightly` |
| 要建立的角色 | `PVEBackupOnly` |

### 步驟 1：規劃需要哪些權限 ★★★★★

★★★★★ **先想清楚「這個腳本到底要做什麼」，再反推權限。**

| 腳本要做的事 | 需要的權限 | 路徑 |
| --- | --- | --- |
| 看得到 VM 清單與狀態 | `VM.Audit` | `/vms` |
| 執行 `vzdump` | ★★★★★ `VM.Backup` | `/vms` |
| 把備份寫進儲存 | ★★★★★ `Datastore.AllocateSpace` | `/storage/nfs-backup` |
| 查詢備份儲存的內容與空間 | `Datastore.Audit` | `/storage/nfs-backup` |

★★★★★ **刻意不給的**：

| 不給 | 理由 |
| --- | --- |
| ★★★★★ `VM.Allocate` | **這個權限包含刪除 VM** |
| ★★★★★ `VM.Config.*` | 不需要改任何設定 |
| ★★★★★ `VM.PowerMgmt` | 備份不需要開關機（用 snapshot 模式） |
| ★★★★★ `Datastore.Allocate` | 這是「刪掉整個儲存定義」的權限 |
| ★★★★★ `Sys.*` | 完全不需要碰節點 |

### 步驟 2：建立自訂角色 ★★★★★

```bash
pveum role add PVEBackupOnly \
  --privs "VM.Audit,VM.Backup,Datastore.Audit,Datastore.AllocateSpace"
```

```bash
pveum role list | grep PVEBackupOnly
```

```text
│ PVEBackupOnly    │ Datastore.AllocateSpace,Datastore.Audit,VM.Audit,VM.Backup │
```

★★★★★ **確認清單裡沒有 `VM.Allocate`。**

### 步驟 3：建立專用使用者 ★★★★★

```bash
pveum user add backup@pve --comment "備份自動化專用（勿用於互動登入）"
```

```bash
# ★★★★ 不設密碼 —— 這個帳號只用 Token，不該能互動登入
pveum user list | grep backup
```

```text
│ backup@pve   │ 備份自動化專用（勿用於互動登入） │      │      1 │
```

> [!tip] ★★★★★ 為什麼要另外開一個使用者，而不是掛在自己帳號下
> 1. ★★★★★ **`privsep=1` 的實際權限是「使用者 ∩ Token」** ——
>    掛在管理員帳號下，交集永遠是 Token 那一份，看起來沒差；
>    但 ★★★★★ **如果哪天有人把 `privsep` 改成 0，Token 立刻變成管理員權限**
> 2. ★★★★★ 稽核紀錄看得出是「備份帳號」做的，不會混在人的操作裡
> 3. ★★★★ 人員離職刪帳號時，不會連帶弄掛自動化

### 步驟 4：給使用者授權 ★★★★★

```bash
pveum acl modify /vms --users backup@pve --roles PVEBackupOnly --propagate 1
pveum acl modify /storage/nfs-backup --users backup@pve --roles PVEBackupOnly --propagate 1
```

```bash
pveum user permissions backup@pve
```

```text
┌────────────────────────┬──────────────────────────┬───────────┐
│ path                   │ permission               │ propagate │
╞════════════════════════╪══════════════════════════╪═══════════╡
│ /storage/nfs-backup    │ Datastore.AllocateSpace  │         1 │
│ /storage/nfs-backup    │ Datastore.Audit          │         1 │
│ /vms                   │ VM.Audit                 │         1 │
│ /vms                   │ VM.Backup                │         1 │
└────────────────────────┴──────────────────────────┴───────────┘
```

### 步驟 5：建立 Token 並授權 ★★★★★

```bash
pveum user token add backup@pve nightly --privsep 1 --comment "每晚備份排程"
```

```text
┌──────────────┬──────────────────────────────────────┐
│ key          │ value                                │
╞══════════════╪══════════════════════════════════════╡
│ full-tokenid │ backup@pve!nightly                   │
│ info         │ {"comment":"每晚備份排程","privsep":1}│
│ value        │ 3f7c9a12-4b8e-4c1d-9f2a-6e5d8b0c7a13 │
└──────────────┴──────────────────────────────────────┘
```

★★★★★ **立刻把 `value` 存進密碼管理系統。**

```bash
# ★★★★★ 這一步最常被忘記：privsep=1 的 Token 要另外授權
pveum acl modify /vms --tokens 'backup@pve!nightly' \
  --roles PVEBackupOnly --propagate 1
pveum acl modify /storage/nfs-backup --tokens 'backup@pve!nightly' \
  --roles PVEBackupOnly --propagate 1
```

```bash
pveum user token permissions backup@pve nightly
```

```text
┌────────────────────────┬──────────────────────────┬───────────┐
│ path                   │ permission               │ propagate │
╞════════════════════════╪══════════════════════════╪═══════════╡
│ /storage/nfs-backup    │ Datastore.AllocateSpace  │         1 │
│ /storage/nfs-backup    │ Datastore.Audit          │         1 │
│ /vms                   │ VM.Audit                 │         1 │
│ /vms                   │ VM.Backup                │         1 │
└────────────────────────┴──────────────────────────┴───────────┘
```

★★★★★ **這個輸出就是「交集之後的最終權限」。空的就代表你漏了授權。**

### 步驟 6：curl 實測（一）—— 該能做的要能做 ★★★★★

```bash
export PVE_HOST="https://pve1.lab.local:8006"
export PVE_TOKEN="PVEAPIToken=backup@pve!nightly=3f7c9a12-4b8e-4c1d-9f2a-6e5d8b0c7a13"
```

```bash
# 6-1 讀 VM 清單（需要 VM.Audit）
curl -sS -w "\nHTTP:%{http_code}\n" \
  -H "Authorization: $PVE_TOKEN" \
  "$PVE_HOST/api2/json/cluster/resources?type=vm" | jq -r \
  '.data[]? | "\(.vmid)\t\(.name)\t\(.status)"' ; echo
```

```text
101	web01	running
102	db01	running

HTTP:200
```

```bash
# 6-2 讀備份儲存內容（需要 Datastore.Audit）
curl -sS -w "\nHTTP:%{http_code}\n" \
  -H "Authorization: $PVE_TOKEN" \
  "$PVE_HOST/api2/json/nodes/pve1/storage/nfs-backup/content"
```

```text
{"data":[{"volid":"nfs-backup:backup/vzdump-qemu-101-2026_09_01-02_05_11.vma.zst",...}]}
HTTP:200
```

```bash
# 6-3 ★★★★★ 觸發一次備份（需要 VM.Backup + Datastore.AllocateSpace）
curl -sS -w "\nHTTP:%{http_code}\n" \
  -H "Authorization: $PVE_TOKEN" \
  -X POST \
  --data-urlencode "vmid=101" \
  --data-urlencode "storage=nfs-backup" \
  --data-urlencode "mode=snapshot" \
  --data-urlencode "compress=zstd" \
  --data-urlencode "remove=0" \
  "$PVE_HOST/api2/json/nodes/pve1/vzdump"
```

```text
{"data":"UPID:pve1:00002F3A:0456BCDE:66D5F2B0:vzdump:101:backup@pve!nightly:"}
HTTP:200
```

★★★★★ **HTTP 200 + 拿到 UPID = 備份權限有效。**

### 步驟 7：curl 實測（二）—— 該擋的一定要擋 ★★★★★

```bash
# 7-1 ★★★★★ 嘗試刪除 VM 101（需要 VM.Allocate，我們沒給）
curl -sS -w "\nHTTP:%{http_code}\n" \
  -H "Authorization: $PVE_TOKEN" \
  -X DELETE \
  "$PVE_HOST/api2/json/nodes/pve1/qemu/101"
```

```text
{"data":null,"errors":{"permissions":"Permission check failed (/vms/101, VM.Allocate)"}}
HTTP:403
```

★★★★★ **這就是我們要看到的結果：403 + `Permission check failed (/vms/101, VM.Allocate)`。**
訊息還很貼心地告訴你「缺哪個路徑上的哪個權限」。

```bash
# 7-2 嘗試關掉 VM（需要 VM.PowerMgmt）
curl -sS -w "\nHTTP:%{http_code}\n" \
  -H "Authorization: $PVE_TOKEN" \
  -X POST \
  "$PVE_HOST/api2/json/nodes/pve1/qemu/101/status/stop"
```

```text
{"data":null,"errors":{"permissions":"Permission check failed (/vms/101, VM.PowerMgmt)"}}
HTTP:403
```

```bash
# 7-3 嘗試改 VM 設定（需要 VM.Config.Memory）
curl -sS -w "\nHTTP:%{http_code}\n" \
  -H "Authorization: $PVE_TOKEN" \
  -X PUT --data-urlencode "memory=8192" \
  "$PVE_HOST/api2/json/nodes/pve1/qemu/101/config"
```

```text
{"data":null,"errors":{"permissions":"Permission check failed (/vms/101, VM.Config.Memory)"}}
HTTP:403
```

```bash
# 7-4 嘗試進入節點 shell（需要 Sys.Console）
curl -sS -w "\nHTTP:%{http_code}\n" \
  -H "Authorization: $PVE_TOKEN" \
  -X POST \
  "$PVE_HOST/api2/json/nodes/pve1/termproxy"
```

```text
{"data":null,"errors":{"permissions":"Permission check failed (/nodes/pve1, Sys.Console)"}}
HTTP:403
```

```bash
# 7-5 嘗試刪除備份檔（需要 Datastore.Allocate，我們只給了 AllocateSpace）
curl -sS -w "\nHTTP:%{http_code}\n" \
  -H "Authorization: $PVE_TOKEN" \
  -X DELETE \
  "$PVE_HOST/api2/json/nodes/pve1/storage/nfs-backup/content/nfs-backup:backup/vzdump-qemu-101-2026_09_01-02_05_11.vma.zst"
```

```text
{"data":null,"errors":{"permissions":"Permission check failed"}}
HTTP:403
```

### 步驟 8：把 Token 放進排程腳本 ★★★★★

```bash
# ★★★★★ secret 放在只有 root 讀得到的檔案，不要寫在腳本裡
install -m 0600 /dev/null /etc/pve-backup-token.env
cat > /etc/pve-backup-token.env <<'EOF'
PVE_HOST=https://pve1.lab.local:8006
PVE_TOKEN=PVEAPIToken=backup@pve!nightly=3f7c9a12-4b8e-4c1d-9f2a-6e5d8b0c7a13
EOF
chmod 0600 /etc/pve-backup-token.env
ls -l /etc/pve-backup-token.env
```

```text
-rw------- 1 root root 121 Sep  2 16:10 /etc/pve-backup-token.env
```

```bash
cat > /usr/local/sbin/pve-nightly-backup.sh <<'EOF'
#!/bin/bash
set -euo pipefail
source /etc/pve-backup-token.env

NODE="pve1"
STORAGE="nfs-backup"
VMIDS="101,102"

UPID=$(curl -sS --fail \
  -H "Authorization: ${PVE_TOKEN}" \
  -X POST \
  --data-urlencode "vmid=${VMIDS}" \
  --data-urlencode "storage=${STORAGE}" \
  --data-urlencode "mode=snapshot" \
  --data-urlencode "compress=zstd" \
  "${PVE_HOST}/api2/json/nodes/${NODE}/vzdump" | jq -r '.data')

logger -t pve-backup "submitted ${UPID}"

while :; do
  BODY=$(curl -sS --fail -H "Authorization: ${PVE_TOKEN}" \
    "${PVE_HOST}/api2/json/nodes/${NODE}/tasks/${UPID}/status")
  [ "$(echo "${BODY}" | jq -r '.data.status')" != "running" ] && break
  sleep 30
done

EXIT=$(echo "${BODY}" | jq -r '.data.exitstatus')
logger -t pve-backup "result ${EXIT}"
[ "${EXIT}" = "OK" ] || exit 1
EOF
chmod 0700 /usr/local/sbin/pve-nightly-backup.sh
```

```bash
/usr/local/sbin/pve-nightly-backup.sh; echo "exit=$?"
journalctl -t pve-backup -n 5
```

```text
exit=0
Sep 02 16:22:03 pve1 pve-backup[9021]: submitted UPID:pve1:0000...:vzdump:101:backup@pve!nightly:
Sep 02 16:31:44 pve1 pve-backup[9021]: result OK
```

### 步驟 9：驗收清單 ★★★★★

| # | 驗收項 | 指令 | 通過標準 |
| --- | --- | --- | --- |
| 1 | 角色不含 `VM.Allocate` | `pveum role list \| grep PVEBackupOnly` | 清單裡沒有 | 
| 2 | ★★★★★ Token 有效權限正確 | `pveum user token permissions backup@pve nightly` | 只有 4 個權限 |
| 3 | 讀 VM 清單成功 | curl GET `/cluster/resources` | HTTP 200 |
| 4 | ★★★★★ 觸發備份成功 | curl POST `/nodes/pve1/vzdump` | HTTP 200 + UPID |
| 5 | ★★★★★ **刪除 VM 被擋** | curl DELETE `/nodes/pve1/qemu/101` | ★★★★★ **HTTP 403** |
| 6 | ★★★★★ **關機被擋** | curl POST `.../status/stop` | HTTP 403 |
| 7 | ★★★★★ **改設定被擋** | curl PUT `.../config` | HTTP 403 |
| 8 | ★★★★★ **節點 shell 被擋** | curl POST `/nodes/pve1/termproxy` | HTTP 403 |
| 9 | secret 檔案權限 | `ls -l /etc/pve-backup-token.env` | `-rw-------` |
| 10 | ★★★★ 稽核紀錄看得到 Token | `pvesh get /cluster/tasks` | user 欄顯示 `backup@pve!nightly` |

★★★★★ **第 5～8 項全部都是 403，這個 Token 才算做對了。**
只驗證「能做的事」而不驗證「不能做的事」，等於沒有驗證。

---

## 常見錯誤與排錯

| # | 現象 | 原因 | 解法 | 重要度 |
| --- | --- | --- | --- | --- |
| 1 | ★★★★★ Token 建好了，API 回 **403** 或看到空清單 | ★★★★★ **`privsep=1` 的 Token 沒有另外授權** | ★★★★★ `pveum acl modify <path> --tokens 'user@realm!id' --roles <role>` | ★★★★★ |
| 2 | curl 回 `401 authentication failure` | Token 字串格式錯（少了 `PVEAPIToken=` 或 `!`） | ★★★★ 檢查格式：`PVEAPIToken=USER@REALM!TOKENID=SECRET` | ★★★★★ |
| 3 | Ticket 認證下 GET 正常、POST 回 401 | ★★★★★ **忘記帶 `CSRFPreventionToken`** | ★★★★★ 寫入請求加 `-H "CSRFPreventionToken: $CSRF"` | ★★★★★ |
| 4 | ★★★★★ **AD 使用者登入成功但畫面全空** | ★★★★★ 只做了同步（認證），沒給 ACL（授權） | ★★★★★ `pveum acl modify /pool/x --users 'wang@corp' --roles ...` | ★★★★★ |
| 5 | AD 登入 `authentication failure` | 使用者名稱填成 `CORP\wang` 或 UPN | ★★★★ **只填 `wang`**，realm 用下拉選單選 | ★★★★★ |
| 6 | `Can't contact LDAP server` | DNS 解析不到 DC、防火牆擋 636 | ★★★★ `dig`、`nc -zv dc01.corp.local 636` | ★★★★ |
| 7 | LDAPS 憑證錯誤 | DC 憑證由內部 CA 簽發，PVE 不信任 | ★★★★★ 把根 CA 放進 `/usr/local/share/ca-certificates/` 後 `update-ca-certificates`；**不要 `--verify 0`** | ★★★★★ |
| 8 | 同步不到任何人 | Base DN 錯、bind 帳號權限不足、filter 過嚴 | ★★★★ 先用 `ldapsearch` 同一組參數驗證 | ★★★★ |
| 9 | ★★★★★ 同步後**全公司**都能登入 | `--enable-new 1` + 同步整個網域 | ★★★★★ 改 `--enable-new 0`；或用 filter 限定 OU／群組 | ★★★★★ |
| 10 | 使用者「應該有權限但沒有」 | ★★★★★ 更深的路徑上有 `NoAccess` 覆蓋掉了 | ★★★★★ `pveum user permissions <user>` 看最終權限；`pveum acl list` 找覆蓋的那條 | ★★★★★ |
| 11 | 改了角色之後別的功能壞掉 | ★★★★★ `pveum role modify --privs` **是整組取代不是追加** | ★★★★★ 先 `pveum role list` 抄下現有清單，加上新的再一起送 | ★★★★★ |
| 12 | 使用者看得到 VM 卻開不了 console | 只有 `VM.Audit` 沒有 `VM.Console` | ★★★★ 加 `VM.Console`（★★★★ 但要先確認真的該給） | ★★★★ |
| 13 | 使用者能建 VM 但一直報磁碟建立失敗 | ★★★★ 有 `VM.Allocate` 但沒有 `Datastore.AllocateSpace` | ★★★★ 在對應 `/storage/<id>` 上補授權 | ★★★★ |
| 14 | ★★★★★ 弄丟 Token secret | ★★★★★ **只在建立時顯示一次** | ★★★★★ 只能刪掉重建：`pveum user token remove` 再 `add` | ★★★★★ |
| 15 | ★★★★★ 開了 2FA 之後被鎖在門外 | 驗證器遺失且沒留 recovery key | ★★★★★ 從 SSH 進節點：`pveum user tfa delete <user>` | ★★★★★ |
| 16 | 跨節點的 API 請求回 `596`／`599` | 目標節點離線或叢集無 Quorum | ★★★★ `pvecm status`；見 [[050-01-03-07-svc-PVE-叢集與高可用]] | ★★★★ |
| 17 | 刪不掉使用者，說還有相依 | 該使用者底下還有 Token 或是 pool 擁有者 | ★★★ 先 `pveum user token list` 刪 Token，再刪使用者 | ★★★ |
| 18 | 大量 `authentication failure` 日誌 | ★★★★★ 有人在暴力破解 | ★★★★★ 上 Fail2ban、限制管理介面來源 IP、強制 2FA | ★★★★★ |
| 19 | 腳本偶爾失敗，錯誤是 `500 ... no quorum` | 叢集當下沒有 Quorum | ★★★★ 修叢集，不是修腳本 | ★★★★ |
| 20 | Web UI 顯示某些選單灰掉、按了沒反應 | ★★★★ 權限不足，UI 只是把它藏起來 | ★★★★ `pveum user permissions` 對照該功能需要的權限 | ★★★★ |

### 權限問題的排查三步驟 ★★★★★

```
【1】★★★★★ 先問「錯誤是 401 還是 403」
      401 → 認證問題（Token／密碼／CSRF）
      403 → 授權問題（ACL）
          ★★★★★ 而且 403 的訊息會直接告訴你缺什麼：
          Permission check failed (/vms/101, VM.Allocate)
                                   ^^^^^^^^  ^^^^^^^^^^^^
                                   哪個路徑   哪個權限

【2】★★★★★ 跑 pveum user permissions <user>
      （Token 用 pveum user token permissions <user> <tokenid>）
      這會列出「繼承與覆蓋都算完之後」的最終權限
      → 缺的權限在不在清單裡？

【3】★★★★★ 缺的話，看 pveum acl list
      → 是「根本沒給」還是「被更深的路徑覆蓋掉了」？
      → 沒給：pveum acl modify 補上
      → 被覆蓋：找到那條 NoAccess 或更窄的角色，處理它
```

★★★★★ **Token 的話，第 2 步一定要用 `token permissions` 而不是 `user permissions`** ——
因為 `privsep=1` 時兩者是不同的。

---

## 安全性注意事項

> [!danger] ★★★★★ 最高風險清單
> | 做法 | 風險 | 重要度 |
> | --- | --- | --- |
> | 日常管理用 `root@pam` | ★★★★★ 沒有稽核軌跡、任何誤操作都不可擋 | ★★★★★ |
> | Token 用 `privsep=0` | ★★★★★ Token 外洩 = 該使用者的全部權限外洩 | ★★★★★ |
> | Token secret 寫在腳本裡並進 git | ★★★★★ **永久外洩** | ★★★★★ |
> | 給了 `Permissions.Modify` | ★★★★★ 對方可以自我提權成管理員 | ★★★★★ |
> | 給了 `Sys.Console` | ★★★★★ 等同節點 root shell | ★★★★★ |
> | LDAPS 用 `--verify 0` | ★★★★★ bind 密碼與使用者清單可被中間人竊取 | ★★★★★ |
> | AD 同步 `--enable-new 1` 且不限 OU | ★★★★★ 全公司帳號都成為攻擊面 | ★★★★★ |
> | 管理介面（8006）暴露在網際網路 | ★★★★★ 被持續掃描與暴力破解 | ★★★★★ |

### 一、最小權限的落實步驟 ★★★★★

```
1. ★★★★★ 先寫下「這個角色要做的事」的清單（不是「他是什麼職位」）
2. 反推每件事需要的權限項
3. 用 pveum role add 建自訂角色，只放那些權限
4. ★★★★★ 掛在 Pool 或群組上，不要掛在個人 + 個別 VM
5. ★★★★★ 用 curl 或實際登入「測試該擋的有沒有被擋」
6. 定期（每季）重新檢視 pveum acl list
```

★★★★ **第 5 步是最常被跳過的**，也是最重要的。
只驗證「能做的能做」不算驗證。

### 二、帳號生命週期 ★★★★

| 時機 | 動作 | 重要度 |
| --- | --- | --- |
| 新人到職 | 加入對應**群組**（不要個別授權） | ★★★★ |
| 職務調動 | 改群組成員，ACL 不用動 | ★★★★ |
| ★★★★★ **離職** | `pveum user modify <u> --enable 0` 先停用，確認無影響後再刪 | ★★★★★ |
| ★★★★★ **廠商臨時帳號** | ★★★★★ 一定要設 `--expire` | ★★★★★ |
| ★★★★ 每季 | 檢視 `pveum user list`、`pveum acl list`、`pveum user token list` | ★★★★★ |
| ★★★★ Token 輪替 | 半年至一年更換一次 secret | ★★★★ |

```bash
# ★★★★ 每季稽核用的一行指令
for u in $(pveum user list --output-format json | jq -r '.[].userid'); do
  echo "=== $u"; pveum user token list "$u" 2>/dev/null
done
```

### 三、保護管理介面本身 ★★★★★

- ★★★★★ **8006 埠不要對外開放**。用 VPN 或跳板機
- ★★★★ PVE 內建防火牆（Datacenter → Firewall）限制來源 IP：

```text
IN  ACCEPT  -source 10.0.99.0/24 -p tcp -dport 8006   # 只允許管理網段
IN  DROP    -p tcp -dport 8006
```

- ★★★★ 搭配 Fail2ban 擋暴力破解（[[090-02-05-guide-防護-Fail2ban入侵防護]]）
- ★★★★★ **換掉自簽憑證**，讓瀏覽器與腳本能真正驗證身分
  （[[090-01-10-guide-PKI-憑證部署到各服務]]）
- ★★★★★ **所有有 `Administrator` 的帳號一律開 2FA**

### 四、備份裡有機密 ★★★★★

★★★★★ `/etc/pve/priv/` 底下有 **Token secret 明文、密碼雜湊、AD bind 密碼**。
把 `/etc/pve` 做備份時：

- ★★★★★ **備份檔要當成機密資料保管**（加密、限制存取）
- ★★★★★ **不要放在 VM 也能讀到的共享目錄**
- ★★★★ 見 [[050-01-03-06-svc-PVE-備份與還原]] 的「節點設定備份」

### 五、稽核與留存 ★★★★

- ★★★★ `pvesh get /cluster/tasks` 的紀錄要**定期匯出留存**（機關通常要求半年至一年）
- ★★★★★ **每個自動化都用獨立 Token**，才能在事後查得出「是哪個腳本做的」
- ★★★★ 認證失敗日誌送到集中式日誌系統（[[100-01-02-guide-日誌-日誌集中與輪替]]）

---

## 速查表

### 使用者與群組

| 指令 | 說明 | 重要度 |
| --- | --- | --- |
| `pveum user list` | 列出使用者 | ★★★★ |
| `pveum user add <u>@<realm> --comment "" --groups g1` | 新增 | ★★★★★ |
| `pveum user modify <u> --enable 0` | ★★★★★ **停用（離職先做這個）** | ★★★★★ |
| `pveum user modify <u> --expire $(date -d "2026-12-31" +%s)` | ★★★★ 設到期日 | ★★★★ |
| `pveum passwd <u>` | 設定密碼 | ★★★★ |
| `pveum user delete <u>` | 刪除 | ★★★★ |
| `pveum group add <g> --comment ""` | 新增群組 | ★★★★★ |
| `pveum group modify <g> --members "a@pve,b@pve"` | 設定成員 | ★★★★ |
| ★★★★★ `pveum user permissions <u>` | **最終有效權限（排錯必用）** | ★★★★★ |

### 角色與 ACL

| 指令 | 說明 | 重要度 |
| --- | --- | --- |
| `pveum role list` | 列出角色與其權限 | ★★★★★ |
| `pveum role add <r> --privs "A,B,C"` | 自訂角色 | ★★★★★ |
| ★★★★★ `pveum role modify <r> --privs "..."` | **整組取代，不是追加** | ★★★★★ |
| `pveum acl list` | 列出所有 ACL | ★★★★★ |
| `pveum acl modify <path> --users <u> --roles <r> --propagate 1` | 授權給使用者 | ★★★★★ |
| `pveum acl modify <path> --groups <g> --roles <r>` | ★★★★★ **授權給群組（建議）** | ★★★★★ |
| `pveum acl modify <path> --tokens 'u@r!t' --roles <r>` | ★★★★★ **授權給 Token** | ★★★★★ |
| `pveum acl modify <path> ... --delete 1` | 撤銷 | ★★★★ |

### API Token

| 指令 | 說明 | 重要度 |
| --- | --- | --- |
| `pveum user token add <u> <id> --privsep 1` | ★★★★★ **建立（secret 只顯示一次）** | ★★★★★ |
| `pveum user token list <u>` | 列出 | ★★★★ |
| `pveum user token permissions <u> <id>` | ★★★★★ **Token 的有效權限** | ★★★★★ |
| `pveum user token remove <u> <id>` | ★★★★★ 撤銷 | ★★★★★ |

### Realm 與 2FA

| 指令 | 說明 | 重要度 |
| --- | --- | --- |
| `pveum realm list` | 列出 realm | ★★★★ |
| `pveum realm add <r> --type ad --domain corp.local --server1 dc01 --secure 1` | 建 AD realm | ★★★★★ |
| `pveum realm modify <r> --password` | 設定 bind 密碼 | ★★★★ |
| ★★★★★ `pveum realm sync <r> --dry-run 1` | **先看不做** | ★★★★★ |
| `pveum realm sync <r> --scope both --enable-new 0` | ★★★★★ 同步且新帳號預設停用 | ★★★★★ |
| `pveum user tfa list` | 列出 2FA 設定 | ★★★★ |
| ★★★★★ `pveum user tfa delete <u>` | **2FA 救援** | ★★★★★ |

### pvesh 與 API

| 用法 | 說明 | 重要度 |
| --- | --- | --- |
| `pvesh get /cluster/resources` | ★★★★★ 全叢集資源總覽 | ★★★★★ |
| `pvesh ls /nodes/<n>` | 列出子路徑 | ★★★★ |
| ★★★★★ `pvesh usage <path> -v` | **查參數（寫腳本前必跑）** | ★★★★★ |
| `pvesh create /nodes/<n>/qemu/<id>/status/start` | 啟動 VM | ★★★★ |
| `pvesh get /cluster/tasks` | ★★★★ 稽核紀錄 | ★★★★★ |
| API 端點 | `https://<node>:8006/api2/json/<path>` | ★★★★★ |
| Token header | ★★★★★ `Authorization: PVEAPIToken=U@R!T=SECRET` | ★★★★★ |
| Ticket cookie | `PVEAuthCookie=<ticket>` | ★★★★ |
| ★★★★★ Ticket 寫入 | **必帶** `CSRFPreventionToken: <csrf>` | ★★★★★ |

### HTTP 狀態碼

| 碼 | 意義 | 先查什麼 |
| --- | --- | --- |
| ★★★★★ 401 | 認證失敗 | Token 格式、密碼、CSRF |
| ★★★★★ 403 | 權限不足 | `pveum user permissions` / ACL |
| 404 | 路徑不存在 | 路徑與 VMID |
| 500 | 伺服器錯誤 | 參數、Quorum |
| 596/599 | 跨節點轉發失敗 | 目標節點是否在線 |

### 重要路徑

| 路徑 | 內容 |
| --- | --- |
| ★★★★★ `/etc/pve/user.cfg` | 使用者／群組／池／Token／ACL |
| `/etc/pve/domains.cfg` | Realm 定義 |
| ★★★★★ `/etc/pve/priv/token.cfg` | **Token secret（機密）** |
| ★★★★★ `/etc/pve/priv/shadow.cfg` | pve realm 密碼雜湊 |
| `/etc/pve/priv/tfa.cfg` | 2FA 設定 |

---

## 練習題

> [!question]- 練習 1：算出最終權限
> 給定以下 ACL：
> ```
> acl:1:/:@auditors:PVEAuditor:
> acl:1:/pool/dev:@dev:PVEVMAdmin:
> acl:1:/vms/305:@dev:NoAccess:
> ```
> 使用者 `chen@pve` 同時屬於 `auditors` 與 `dev`。
> VM 305 在 pool `dev` 裡。請問他對 VM 305 有什麼權限？對 VM 301（也在 dev 裡）呢？
>
> ---
> **參考答案**
> - **VM 301**：從 `/pool/dev` 繼承 `PVEVMAdmin`，再加上從 `/` 繼承的 `PVEAuditor`。
>   ★★★★ 同一路徑深度的角色取聯集，最終是 **`PVEVMAdmin` 的完整權限**。
> - **VM 305**：★★★★★ **`/vms/305` 是更深的路徑，會覆蓋掉繼承來的設定** ——
>   `@dev` 在這裡是 `NoAccess`。
>   ★★★★★ 但注意：他還屬於 `auditors`，而 `/vms/305` 上**沒有** `auditors` 的設定，
>   所以 `auditors` 那條走的是從 `/` 繼承的 `PVEAuditor`。
>   ★★★★★ **結論：他對 VM 305 仍有唯讀權限（來自 auditors），但沒有管理權限。**
>
> ★★★★★ **這題示範了為什麼要用 `pveum user permissions` 而不是用腦袋算。**

> [!question]- 練習 2：做一個「只能開關機」的角色
> 建立角色 `PVEOperator`，讓某個群組只能看到與開關 pool `prod` 裡的 VM，
> **不能**改設定、**不能**進 console、**不能**刪除。驗證你的設定。
>
> ---
> **參考答案**
> ```bash
> pveum role add PVEOperator --privs "VM.Audit,VM.PowerMgmt"
> pveum group add operators
> pveum acl modify /pool/prod --groups operators --roles PVEOperator --propagate 1
> pveum user add op1@pve --groups operators
> pveum passwd op1@pve
> pveum user permissions op1@pve
> ```
> ★★★★★ **驗證要包含「該擋的有沒有擋住」**：
> 用 op1 登入 Web UI，確認
> - 開關機按鈕**可用**
> - Console 按鈕**灰掉**（沒有 `VM.Console`）
> - Hardware / Options 頁籤**改不了**
> - 沒有刪除選項

> [!question]- 練習 3：完成「只能備份不能刪」的 Token
> 依「完整實戰範例」步驟 1～7 做一次，
> **必須做到步驟 7 的五個 403 都出現**才算完成。
>
> ---
> **參考答案**
> 關鍵三步：
> ```bash
> pveum role add PVEBackupOnly --privs "VM.Audit,VM.Backup,Datastore.Audit,Datastore.AllocateSpace"
> pveum user token add backup@pve nightly --privsep 1
> # ★★★★★ 最容易漏掉的一步
> pveum acl modify /vms --tokens 'backup@pve!nightly' --roles PVEBackupOnly --propagate 1
> ```
> 驗證：
> ```bash
> curl -sS -w "\nHTTP:%{http_code}\n" -H "Authorization: $PVE_TOKEN" \
>   -X DELETE "$PVE_HOST/api2/json/nodes/pve1/qemu/101"
> # 應該看到 HTTP:403 與 Permission check failed (/vms/101, VM.Allocate)
> ```
> ★★★★★ **如果 DELETE 回 200，代表你的角色多給了 `VM.Allocate`，回頭檢查。**

> [!question]- 練習 4：privsep 的差別
> 建立兩個 Token，一個 `--privsep 1` 一個 `--privsep 0`，
> 都掛在一個有 `PVEVMAdmin` 的使用者底下，**兩個都不另外授權**。
> 用 curl 各打一次 `/cluster/resources`，說明結果差異。
>
> ---
> **參考答案**
> - `privsep=1` 的 Token：★★★★★ **看到空清單或 403** ——
>   因為它有自己的 ACL（空的），交集之後是空的
> - `privsep=0` 的 Token：★★★★★ **看到所有 VM** ——
>   它完全繼承使用者的 `PVEVMAdmin`
>
> ★★★★★ **這就是為什麼 `privsep=1` 是安全的預設**：
> 忘記授權時，Token 是「什麼都不能做」而不是「什麼都能做」。

> [!question]- 練習 5：2FA 與救援
> 幫一個測試帳號設定 TOTP 並產生 recovery key，
> 然後模擬「驗證器遺失」，用 recovery key 登入一次，
> 最後用管理員身分把該帳號的 2FA 清掉。
>
> ---
> **參考答案**
> 1. Web UI 右上使用者選單 → TFA → 加入 TOTP，掃 QR code，輸入驗證碼
> 2. 再加一個 Recovery Keys，★★★★★ **把產生的一次性碼列印或存進保險櫃**
> 3. 登出，登入時在 2FA 欄位改用 recovery key（★★★★ 每個只能用一次）
> 4. 管理員清除：
>    ```bash
>    pveum user tfa list
>    pveum user tfa delete <user>@pve
>    ```
> ★★★★★ **重點認知**：`pveum user tfa delete` 要從 **SSH** 執行，
> 所以 SSH 的保護跟 2FA 一樣重要。

> [!question]- 練習 6：AD 整合前的連線驗證
> 在還沒建立 realm 之前，用 `ldapsearch` 驗證你能不能用 bind 帳號查到使用者。
> 說明如果這一步失敗，你會依序檢查哪四件事。
>
> ---
> **參考答案**
> ```bash
> apt install -y ldap-utils
> ldapsearch -x -H ldaps://dc01.corp.local:636 \
>   -D "CN=pve-bind,OU=Service,DC=corp,DC=local" -W \
>   -b "DC=corp,DC=local" "(sAMAccountName=wang)" dn
> ```
> 失敗時依序檢查：
> 1. ★★★★ **DNS**：`dig +short dc01.corp.local`、`dig SRV _ldap._tcp.corp.local`
> 2. ★★★★ **連通性**：`nc -zv dc01.corp.local 636`
> 3. ★★★★★ **憑證**：改用 `-H ldap://...:389` 測（純測試用），
>    如果 389 通而 636 不通 → 憑證信任問題 → 把根 CA 裝進 PVE
> 4. ★★★★ **DN 與密碼**：bind DN 字串、bind 帳號是否被鎖定、Base DN 是否正確
>
> ★★★★★ **`ldapsearch` 不通就不要去動 PVE 的 realm 設定** ——
> 問題不在 PVE。

---

## 小測驗

Q1. `root@pam` 和 `admin@pve` 都是 `Administrator`，兩者最大的差別是什麼？

Q2.（是非）在 `/vms` 給了 `propagate=1` 的 `PVEVMAdmin`，
再在 `/vms/305` 給同一個群組 `NoAccess`，該群組對 VM 305 就完全沒有任何權限。

Q3. 建立 API Token 時 `--privsep 1` 與 `--privsep 0` 差在哪？為什麼建議用 1？

Q4.（選擇）你建了 `privsep=1` 的 Token 並把使用者授權好了，但 curl 一直回 403。
最可能漏了什麼？
(A) 沒有帶 `CSRFPreventionToken`
(B) 沒有用 `pveum acl modify --tokens` 授權給 Token 本身
(C) Token 過期了
(D) 節點沒有 Quorum

Q5. 這兩個權限差在哪？給錯會怎樣？
`Datastore.AllocateSpace` 與 `Datastore.Allocate`

Q6.（簡答）AD 使用者同步進來了、也能登入，但登入後畫面一片空白。
原因是什麼？要怎麼解決？

Q7. 用 Ticket 認證時，`GET /nodes` 成功但 `POST .../status/start` 回 401，為什麼？

Q8. 這行指令的問題在哪？
`pveum role modify PVEBackupOnly --privs "VM.Snapshot"`

Q9.（情境）稽核要求「找出上週是誰刪掉了 VM 205」。你會用哪個指令？
輸出裡哪個欄位是關鍵？如果那是自動化做的，你怎麼知道是哪個腳本？

Q10.（情境）有人回報「LDAPS 憑證驗證失敗」，同事說「加 `--verify 0` 就好了」。
請說明為什麼不能這樣做，以及正確做法是什麼。

> [!question]- 測驗答案
> **A1.** ★★★★★ **`root@pam` 不受 ACL 限制** ——
> 它是無條件的超級使用者，連 `NoAccess` 都擋不住它。
> `admin@pve` 有 `Administrator` 角色，但**仍然受 ACL 路徑限制**：
> 如果只在 `/pool/dev` 給 `Administrator`，他就只能管 dev 池。
> 另外 `root@pam` 的密碼就是 Linux root 密碼，改一邊等於改兩邊。
> 見「四種 Realm」。
>
> **A2.** ★★★★★ **否（陷阱題）。**
> `/vms/305` 上的 `NoAccess` **只覆蓋掉「同一個主體」在較淺路徑上的設定**。
> 如果該使用者還透過**另一個群組**在 `/` 上有 `PVEAuditor`，
> 而 `/vms/305` 上沒有那個群組的設定，那條路徑仍然從 `/` 繼承。
> ★★★★★ **所以「完全沒有任何權限」不成立。**
> 排查一律用 `pveum user permissions`。見「繼承規則」與練習 1。
>
> **A3.** `privsep=1` → ★★★★★ **Token 有獨立的 ACL，實際權限 = 使用者權限 ∩ Token 權限**；
> `privsep=0` → ★★★★★ **Token 完全繼承使用者的全部權限**。
> 建議用 1 的理由：★★★★★ **失誤時的預設狀態是「什麼都不能做」而不是「什麼都能做」**，
> 而且 Token 外洩時損害被限制在 Token 自己的權限範圍內。
> 見「API Token 與權限分離」。
>
> **A4. (B)**。★★★★★ **`privsep=1` 的 Token 必須另外用
> `pveum acl modify <path> --tokens 'user@realm!id' --roles <role>` 授權。**
> 只授權給使用者只完成了交集的一半。
> (A) 只影響 Ticket 認證，用 API Token 不需要 CSRF token。
> 見排錯表第 1 列與實戰步驟 5。
>
> **A5.**
> - `Datastore.AllocateSpace` = ★★★★ **在儲存上配置空間**（建磁碟、寫備份）
> - ★★★★★ `Datastore.Allocate` = **建立與刪除「儲存定義本身」**
>
> ★★★★★ 給錯（給了 `Datastore.Allocate`）的後果：
> 對方可以**把整個儲存從 PVE 移除**，所有 VM 立刻找不到磁碟。
> 見「權限項目」表與「三個給了就等於給全部的權限」。
>
> **A6.** ★★★★★ **只完成了認證，沒有做授權。**
> Realm 同步只是把帳號建進 PVE（讓他登得進來），
> ★★★★★ **權限必須另外用 ACL 給**。
> 解法：
> ```bash
> pveum acl modify /pool/prod --groups 'vm-admins@corp' --roles PVEVMAdmin --propagate 1
> ```
> ★★★★ 建議授權給**同步進來的 AD 群組**而不是個別使用者，這樣 AD 端加人就自動生效。
> 見「AD 整合」與排錯表第 4 列。
>
> **A7.** ★★★★★ **Ticket 認證下，所有寫入類請求（POST／PUT／DELETE）
> 都必須額外帶 `CSRFPreventionToken` header。**
> GET 只需要 `PVEAuthCookie`，所以讀取正常、寫入 401。
> ★★★★ 改用 API Token 就沒有這個問題（Token 不需要 CSRF token）。
> 見「API 的兩種認證方式」。
>
> **A8.** ★★★★★ **`pveum role modify --privs` 是「整組取代」不是「追加」。**
> 這行會把 `PVEBackupOnly` 的權限**全部換成只剩 `VM.Snapshot`** ——
> 原本的 `VM.Audit`、`VM.Backup`、`Datastore.*` 全部消失，備份腳本立刻壞掉。
> ★★★★★ **正確做法**：先 `pveum role list` 抄下現有清單，
> 把舊的加上新的一起送：
> `pveum role modify PVEBackupOnly --privs "VM.Audit,VM.Backup,Datastore.Audit,Datastore.AllocateSpace,VM.Snapshot"`
> 見「自訂角色」警告與排錯表第 11 列。
>
> **A9.**
> ```bash
> pvesh get /cluster/tasks --output-format json-pretty | jq -r \
>   '.[] | select(.type=="qmdestroy") | "\(.starttime) \(.node) \(.user) \(.id)"'
> ```
> ★★★★★ **關鍵欄位是 `user`。**
> 如果是自動化做的，`user` 會顯示到 **Token 層級**（例如 `deploy@pve!ci-runner`），
> ★★★★★ **這正是「每個自動化用獨立 Token」的價值** ——
> 用同一個 Token 給五個腳本，出事時你分不出是哪一個。
> 見「稽核：誰做了什麼」。
>
> **A10.** ★★★★★ **`--verify 0` 等於放棄驗證伺服器身分**，
> 攻擊者可以用中間人攔截 LDAPS 連線，取得
> ★★★★★ **bind 帳號的密碼**與**整份使用者清單**，
> 甚至偽造認證結果。等於用明文 LDAP 的安全等級跑一個「看起來加密」的連線。
>
> ★★★★★ **正確做法**：把 AD 的根 CA 憑證裝進 PVE 的信任區：
> ```bash
> cp corp-root-ca.crt /usr/local/share/ca-certificates/corp-root-ca.crt
> update-ca-certificates
> pveum realm modify corp --verify 1
> ```
> 見「LDAPS 憑證驗證」與 [[090-01-09-guide-PKI-根憑證派送與信任]]。

---

## 延伸閱讀

### 本章其他篇

- [[050-01-03-01-svc-PVE-安裝與初始設定]] — ★★★★ 第一次登入與 root 密碼
- [[050-01-03-02-guide-PVE-儲存設定]] — `/storage/<id>` 這條 ACL 路徑對應什麼
- [[050-01-03-03-guide-PVE-虛擬機管理]] — VMID 與 pool 的概念
- [[050-01-03-06-svc-PVE-備份與還原]] — ★★★★★ **實戰範例的備份 API 對應的手動操作**
- [[050-01-03-07-svc-PVE-叢集與高可用]] — ★★★★ 叢集裡 `/etc/pve/user.cfg` 是共享的
- [[050-01-03-09-svc-PVE-監控與資源調校]] — ★★★★ 監控系統該用 `PVEAuditor` 的唯讀 Token
- [[050-01-03-11-svc-PVE-升級與維護]] — 升級前的帳號與 ACL 備份
- [[050-01-03-12-guide-PVE-故障排除]] — 綜合排錯

### 相關主題

- [[020-01-09-cmd-Linux-使用者與群組管理]] — ★★★★ `pam` realm 底層就是這個
- [[020-02-01-04-svc-sshd-伺服器端設定]] — ★★★★★ 2FA 救援靠 SSH，SSH 要顧好
- [[020-02-01-07-svc-SSH-安全強化]] — 管理管道的強化
- [[030-01-02-01-guide-AD-AD概念與網域架構]] — DN、OU、網域結構
- [[030-01-02-03-guide-AD-使用者與群組管理AD]] — AD 端的群組怎麼規劃
- [[030-01-02-08-guide-AD-AD安全強化]] — bind 服務帳號的保護
- [[090-01-09-guide-PKI-根憑證派送與信任]] — ★★★★★ **LDAPS 憑證卡關的正解**
- [[090-01-10-guide-PKI-憑證部署到各服務]] — 把 8006 換成受信任的憑證
- [[090-02-05-guide-防護-Fail2ban入侵防護]] — ★★★★ 擋暴力破解
- [[090-02-06-guide-防護-遠端存取安全]] — 管理介面不要對外
- [[100-01-02-guide-日誌-日誌集中與輪替]] — 認證日誌集中留存
- [[100-02-13-guide-維運-資產與授權管理]] — 帳號盤點納入資產管理

### 官方文件

- Proxmox VE 官方文件 `User Management` 章節 — ★★★★★ Realm、角色、ACL 的權威說明
- Proxmox VE API Viewer（節點上 `https://<node>:8006/pve-docs/api-viewer/`）
  — ★★★★★ **所有 API 路徑、參數與所需權限的完整清單**
- `man pveum`、`man pvesh`、`pveum --help`
- ★★★★★ `pvesh usage <path> -v` — **你這個版本實際支援的參數以此為準**
