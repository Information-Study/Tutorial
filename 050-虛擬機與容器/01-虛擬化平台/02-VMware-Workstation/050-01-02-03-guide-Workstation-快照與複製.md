---
title: "快照與複製"
desc: "快照的差異磁碟鏈原理與效能代價、為什麼快照不是備份、連結複製與完整複製的取捨，以及用範本量產實驗機的標準流程"
aliases: [Snapshot, 快照管理員, Linked Clone, Full Clone, 連結複製, 完整複製, 差異磁碟]
tags: [群組/虛擬機與容器, 主題/虛擬化, 主題/VMware]
category: 虛擬機與容器
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]]"]
updated: 2026-09-02
---

# 快照與複製

> [!warning] 未實機驗證
> 本篇的選單路徑與畫面文字**以 VMware Workstation 17 Pro 為例**，其他版本的選單位置、
> 對話框文字可能不同。**連結複製（Linked Clone）是 Pro 專屬功能**，Player 沒有；
> 觀念與代價分析在任何版本都適用。

> [!abstract] 這篇你會學到
> - 快照的實際運作方式：**差異磁碟鏈**，以及它對讀寫效能的具體代價 ★★★★
> - ★★★★★ **快照不是備份** —— 說清楚為什麼，以及誤把它當備份會怎麼死
> - 快照管理員的完整操作：拍、回復、刪除、刪除全部、分支 ★★★
> - ★★★★ 快照鏈太長會發生什麼事，以及該在什麼時機清理
> - 連結複製與完整複製的差別、磁碟佔用比較、各自適用場合 ★★★★
> - ★★★★★ **用範本 + 連結複製快速開出多台實驗機**——本手冊各章實驗環境的標準建法
> - 複製後一定要改的四樣東西：hostname、machine-id、SSH host key、靜態 IP ★★★★

## 前置知識

- [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]]
- [[050-01-02-01-svc-Workstation-安裝與授權]]
- [[050-01-01-02-guide-虛擬化-虛擬化底層技術]]

---

## 觀念說明

### ★★★★ 快照到底做了什麼

一般人的直覺是：「快照 = 把 VM 現在的樣子存起來一份」。**這個直覺是錯的**，
而且錯得很有殺傷力。

實際發生的事情是：**Workstation 把原本的虛擬磁碟凍結成唯讀，
然後開一個新的空白差異磁碟，之後所有的寫入都寫到新的那個檔案裡**。

```text
拍快照之前：
    ┌──────────────────┐
    │  base.vmdk       │  ← VM 讀也讀這裡、寫也寫這裡
    │  (讀寫)          │
    └──────────────────┘

拍快照之後：
    ┌──────────────────┐
    │  base.vmdk       │  ← 凍結成唯讀，內容永遠停在拍快照那一刻
    │  (唯讀)          │
    └────────┬─────────┘
             │
    ┌────────▼─────────┐
    │ base-000001.vmdk │  ← 新的差異磁碟，之後所有寫入都到這裡
    │  (讀寫)          │
    └──────────────────┘
```

再拍第二個快照：

```text
    base.vmdk           (唯讀)
        │
    base-000001.vmdk    (唯讀，凍結在第二次拍快照那一刻)
        │
    base-000002.vmdk    (讀寫，現在用的)
```

這叫**差異磁碟鏈（delta disk chain）**，也叫 redo log。

> [!note] ★★★★ 讀取的時候發生什麼事
> 客體要讀某個磁碟區塊時，Workstation 會**從鏈的最上層往下找**：
>
> 1. `base-000002.vmdk` 有這個區塊嗎？有就回傳
> 2. 沒有 → `base-000001.vmdk` 有嗎？有就回傳
> 3. 還是沒有 → 回 `base.vmdk` 拿
>
> **鏈越長，最壞情況要查的層數越多**。這就是效能代價的來源。

### ★★★★ 效能代價：具體是哪些

| 代價 | 說明 | 嚴重度 |
| --- | --- | --- |
| 讀取放大 | 每次讀取最壞要走完整條鏈 | ★★★ |
| 寫入放大（首次寫入某區塊）| 要先從下層讀出整個區塊，改完再寫到差異磁碟（copy-on-write）| ★★★★ |
| 隨機 I/O 惡化 | 資料散落在多個檔案，主機端的循序讀取優勢消失 | ★★★★ |
| 主機磁碟空間 | 每個差異磁碟只會長不會縮，**改動越多長越大** | ★★★★ |
| 記憶體快照的額外開銷 | 含記憶體的快照要另外寫一份等同 VM 記憶體大小的檔案 | ★★★ |
| 部分功能被鎖住 | 有快照時不能擴充虛擬磁碟、不能做某些設定變更 | ★★★ |

實測的感受大概是：

```text
無快照            基準效能
1 個快照          幾乎感覺不出來（日常使用可接受）★★
3 個快照          開始感覺 I/O 變慢，開機時間變長 ★★★
5 個以上快照      明顯遲鈍，大量寫入時特別糟 ★★★★
10 個以上         不可用，且主機空間可能被吃掉數十 GB ★★★★★
```

> [!warning] ★★★★ 快照的空間會長到超乎想像
> 一台宣告 40 GB、實際用 5 GB 的 VM，在它上面拍一個快照，然後跑
> `sudo apt upgrade`（改動大量檔案），差異磁碟可能就長到好幾 GB。
> 再跑一次 `dd` 寫個大檔又刪掉，差異磁碟**還是不會縮**。
>
> 我看過的實際慘況：一台原本 20 GB 的 VM，掛了 8 個快照放了半年，
> 整個資料夾長到 180 GB。★★★★

### ★★★★★ 快照不是備份

這是本篇最重要的一段。請把它讀完。

**快照不是備份。快照不是備份。快照不是備份。**

#### 理由一：快照與原始磁碟在同一個地方，同一個檔案系統上

備份的第一原則是「和原始資料分開放」。快照的差異磁碟就躺在
`base.vmdk` 旁邊，同一個資料夾、同一顆實體磁碟。

```text
D:\VMs\lab-ubuntu-base\
    lab-ubuntu-base.vmdk            ← 原始磁碟
    lab-ubuntu-base-000001.vmdk     ← 快照的差異磁碟
    lab-ubuntu-base-000002.vmdk     ← 又一個
```

**這顆 SSD 掛了，原始磁碟和所有快照一起沒了。** ★★★★★
勒索軟體加密了這個資料夾，原始磁碟和所有快照一起被加密。
你不小心把資料夾刪了，全部一起消失。

備份必須在**另一個實體裝置**上，最好還在**另一個地點**。快照完全不符合。

#### 理由二：快照依賴原始磁碟，它本身不完整

快照的差異磁碟**只有差異**。沒有 `base.vmdk`，那些 `-000001.vmdk`
就是一堆無法解讀的碎片。

備份的定義是「可以獨立還原出完整資料」。快照做不到。★★★★★

#### 理由三：鏈上任何一環壞掉，整條鏈全毀

差異磁碟鏈是**串聯**的。`-000001.vmdk` 損壞，那麼建立在它之上的
`-000002.vmdk`、`-000003.vmdk` 全部失效，而且**回不到 `base` 也回不到最新狀態**
（因為最新狀態依賴中間那一環）。

一個真實的失敗模式：磁碟空間不足導致差異磁碟寫入失敗 → 鏈損毀 → 整台 VM 報廢。★★★★★

#### 理由四：快照會過期，備份不會

快照留半年，你回復下去得到的是半年前的系統，中間半年的所有資料**全部消失**。
而且很多人根本不記得那個快照是什麼時候拍的、當時是什麼狀態。

備份有版本、有保留策略、有還原點清單。★★★★

#### 理由五：VMware 官方自己就這樣講

VMware 的文件與知識庫一貫的立場是：快照是**短期**的還原點，
用於「做一個有風險的變更之前」的保險，用完就刪。
不是長期保存機制，更不是備份方案。★★★★

#### 那什麼才是備份

| 方式 | 是不是備份 | 說明 |
| --- | --- | --- |
| 快照 ★★★★★ | **不是** | 短期還原點，用完即刪 |
| 完整複製（Full Clone）到同一顆磁碟 ★★ | 勉強算「副本」 | 磁碟掛了一起死 |
| 完整複製到**另一顆實體磁碟** ★★★ | 是（陽春版） | 沒有版本管理 |
| 匯出 OVF／OVA 到外接儲存 ★★★ | 是 | 可攜、獨立、完整 |
| 客體內用備份軟體備到遠端 ★★★★ | 是（最正規） | 有版本、有保留策略 |
| 3-2-1 原則：3 份、2 種媒體、1 份異地 ★★★★★ | 是（標準答案） | 機關環境的要求 |

> [!danger] ★★★★★ 「我有快照所以不用備份」是災難的起手式
> 這句話在機關的事故報告裡出現過太多次。
> 快照能救的是「我剛剛改壞了設定」，救不了「磁碟壞了」「機器被偷了」
> 「勒索軟體」「不小心刪掉整個資料夾」。
>
> 正確心態：**快照是安全帶，備份是保險。兩個都要有，而且不能互相取代。**

### ★★★★ 快照該用在什麼時候

快照有它非常好用的場合，就是**短期、可預期、要能立刻回頭的變更**。

| 場合 | 該不該用快照 | 說明 |
| --- | --- | --- |
| 做一個有風險的設定變更前 ★★★★ | **該** | 改壞了三秒回復 |
| 升級套件／核心前 ★★★★ | **該** | 升級失敗回得去 |
| 教學示範，每次都要從同一個狀態開始 ★★★★ | **該** | 這是快照最好的用途 |
| 測試安裝腳本，要反覆重跑 ★★★★ | **該** | 比重灌快一百倍 |
| 建立乾淨範本的還原點 ★★★★★ | **該** | 本手冊的標準做法 |
| 「留著以防萬一」放好幾個月 ★★★★ | **不該** | 這是最常見的誤用 |
| 當成備份 ★★★★★ | **絕對不該** | 見上一節 |
| 正式營運環境長期掛著 ★★★★★ | **絕對不該** | 效能與空間雙殺 |

### ★★★ 含記憶體的快照

拍快照時有一個核取方塊：**Snapshot the virtual machine's memory**。

| | 勾（含記憶體）★★★ | 不勾（只有磁碟）★★★ |
| --- | --- | --- |
| VM 開機中可以拍 | 可以 | 可以（但狀態不一致，見下）|
| 回復後的狀態 | **回到拍的那一瞬間，程式還在跑** | 相當於「硬斷電後重開機」|
| 額外檔案 | `.vmsn` 含記憶體，大小約等於 VM 記憶體 | `.vmsn` 很小 |
| 拍攝耗時 | 4 GB 記憶體約要寫 4 GB 到磁碟，數十秒 | 幾秒 |
| 適合 | 要保留執行中狀態的示範 | 範本、變更前的還原點 |

> [!warning] ★★★★ 開機中拍「不含記憶體」的快照，回復後等於硬斷電
> 客體的檔案系統快取還沒 flush 到磁碟，回復後開機會跑檔案系統檢查，
> 資料庫可能需要 crash recovery。
>
> **最乾淨的做法：VM 完全關機後再拍快照。** 這樣拍出來的狀態一定是一致的，
> 而且不含記憶體、檔案小、回復快。本手冊的範本快照一律這樣做。★★★★★

### ★★★★ 快照鏈太長的後果與清理時機

#### 後果

```text
症狀進程：

階段 1（1～2 個快照）
  └─ 幾乎無感

階段 2（3～4 個快照）
  ├─ 開機時間變長
  ├─ apt upgrade 明顯變慢
  └─ 主機資料夾開始變胖

階段 3（5～8 個快照）
  ├─ 隨機 I/O 顯著惡化，資料庫測試結果不可信 ★★★★
  ├─ 主機磁碟被吃掉數十 GB
  ├─ 想擴充虛擬磁碟時發現按鈕是灰的 ★★★
  └─ 你已經記不得每個快照是什麼

階段 4（10 個以上，或掛了好幾個月）
  ├─ VM 遲鈍到難以使用 ★★★★
  ├─ 主機空間可能爆掉 → 差異磁碟寫入失敗 → 鏈損毀 ★★★★★
  └─ 刪除快照（合併）本身要花很久，而且要有足夠的暫存空間 ★★★★
```

#### 清理時機的判斷準則

| 觸發條件 | 動作 |
| --- | --- |
| 變更做完並驗證正常 ★★★★ | **立刻刪掉變更前的快照** |
| 快照數量 ≥ 3 ★★★ | 檢視並刪掉不需要的 |
| 任何快照存在超過 2 週 ★★★★ | 檢討：還需要嗎？不需要就刪 |
| VM 資料夾大小 > 宣告磁碟大小 ★★★★ | 快照吃掉的，該清 |
| 主機剩餘空間 < 20% ★★★★★ | 立刻清，不然差異磁碟寫爆會毀 VM |
| 要擴充虛擬磁碟 ★★★ | 必須全部刪光 |
| 要做效能測試 ★★★★ | 必須全部刪光，不然數據不可信 |

> [!danger] ★★★★★ 清理快照前先確認主機有足夠空間
> 「刪除快照」實際上是**把差異磁碟的內容合併回下層**，這個過程需要工作空間。
> 主機空間不足時合併會失敗，**而且可能讓鏈處於半合併的損毀狀態**。
>
> 動手前先看主機剩餘空間，至少要有「所有差異磁碟總和」那麼多的餘裕。

### ★★★★ 複製：連結複製 vs 完整複製

Workstation Pro 的 **VM → Manage → Clone…** 提供兩種複製。

#### 完整複製（Full Clone）

把來源 VM 的所有磁碟資料**實際複製一份**，產生一台完全獨立的新 VM。

```text
lab-ubuntu-base/                lab-web-01/
  base.vmdk  (5 GB) ──複製──▶   lab-web-01.vmdk (5 GB)

兩者之後完全無關，刪掉來源不影響複本
```

#### 連結複製（Linked Clone）

新 VM **不複製資料**，而是把來源 VM 的某個快照當成唯讀基礎，
自己只放一個差異磁碟。

```text
lab-ubuntu-base/
  base.vmdk (5 GB, 唯讀)
  base-000001.vmdk (快照 clean-base, 唯讀)
        ▲              ▲
        │              │
        │              └──────────────┐
        │                             │
  lab-web-01/                   lab-web-02/
    差異磁碟 (200 MB)             差異磁碟 (200 MB)
```

**三台機器加起來只佔約 5.4 GB**，而不是 15 GB。★★★★

#### 完整比較

| 項目 | 連結複製 ★★★★ | 完整複製 ★★★ |
| --- | --- | --- |
| 建立速度 | **數秒** | 數分鐘（看磁碟大小） |
| 初始磁碟佔用 | 幾百 MB | 等同來源的實際用量 |
| 需要 Pro 版 | **是** | 否（Player 也能手動複製資料夾） |
| 依賴來源 VM ★★★★★ | **完全依賴，來源刪了複本全死** | 不依賴 |
| 來源可以移動嗎 ★★★★ | **不行**，路徑一變全斷 | 隨便搬 |
| 效能 | 略差（多一層鏈） | 原生 |
| 可以匯出給別人嗎 ★★★★ | **不行**（缺基礎磁碟） | 可以 |
| 適合 | **短期大量實驗機** | 要長期保留、要搬走、要獨立的機器 |

> [!danger] ★★★★★ 連結複製的來源 VM 絕對不能刪、不能搬、不能改
> 這是連結複製最大的陷阱。你建了五台連結複製的實驗機，
> 半年後覺得 `lab-ubuntu-base` 佔空間就把它刪了——**五台實驗機全部同時報廢**，
> 而且開機時只會看到：
>
> ```text
> Cannot open the disk 'D:\VMs\lab-ubuntu-base\lab-ubuntu-base-000001.vmdk'
> or one of the snapshot disks it depends on.
> ```
>
> 同樣的，把來源資料夾**改名或搬到別的磁碟**，效果一樣是全毀
> （可以手動改 `.vmdk` 描述檔裡的路徑救回來，但很麻煩）。
>
> 應對：範本資料夾命名清楚（`lab-ubuntu-base`）、放在固定位置、
> **在 VM 的 Notes 裡註明「此 VM 為多台連結複製的基礎，不可刪除或移動」**。

> [!note] ★★★★ 連結複製對來源快照的要求
> 連結複製必須基於**來源 VM 的某個快照**（不能基於「當前狀態」）。
> 如果來源沒有快照，Workstation 會在複製時自動幫你建一個。
>
> 而且**那個被依賴的快照從此不能刪**——刪它等於抽掉複本的地基。
> 快照管理員會擋下來並提示該快照正被連結複製使用。★★★★

#### 該選哪一個

| 需求 | 選擇 |
| --- | --- |
| 練 Linux 指令，開三台，用完就丟 ★★★★ | **連結複製** |
| 一次要開五台做網路實驗 ★★★★ | **連結複製** |
| 要跑效能測試，數據要準 ★★★★ | **完整複製**（連結有額外開銷） |
| 要匯出給同事、要拿到別台電腦 ★★★★ | **完整複製** |
| 要長期保留超過三個月 ★★★ | **完整複製** |
| 主機磁碟很緊 ★★★★ | **連結複製** |
| 這台會變成新的範本 ★★★ | **完整複製** |

### ★★★★★ 本手冊的實驗環境建法

把前面所有觀念組合起來，就是本手冊各章實驗環境的標準流程：

```text
第一次（只做一次）
  ┌────────────────────────────────────────────┐
  │ 1. 按 02 篇建出 lab-ubuntu-base            │
  │ 2. 更新、裝 open-vm-tools、開 SSH          │
  │ 3. 清理痕跡（apt clean、清日誌、清 history）│
  │ 4. 完全關機                                 │
  │ 5. 拍快照 clean-base（不含記憶體）★★★★★  │
  │ 6. 之後永遠不再開這台機器                   │
  └────────────────────────────────────────────┘

每次要做實驗（重複 N 次）
  ┌────────────────────────────────────────────┐
  │ 1. 從 clean-base 做連結複製 → lab-xxx      │
  │ 2. 開機，改 hostname / machine-id /         │
  │    SSH host key / 靜態 IP  ★★★★           │
  │ 3. 立刻拍一個 fresh 快照（做實驗的起點）    │
  │ 4. 做實驗，弄壞了就回 fresh                 │
  │ 5. 該章做完 → 刪掉整台 lab-xxx             │
  └────────────────────────────────────────────┘
```

這樣做的好處：

| 好處 | 說明 |
| --- | --- |
| 空間省 ★★★★ | 五台實驗機只多佔 1～2 GB |
| 開機器只要幾秒 ★★★★ | 不用等複製 |
| 範本永遠乾淨 ★★★★★ | 每一章都從相同的起點開始 |
| 弄壞了成本近乎零 ★★★★ | 回快照或直接砍掉重開 |

---

## 安裝或基礎操作

### ★★★★ 拍一個快照

**方法一：選單**

```text
VM → Snapshot → Take Snapshot...
```

**方法二：工具列**：相機圖示。

對話框：

```text
Take Snapshot

Name:         before-nginx-install

Description:  安裝 Nginx 之前的乾淨狀態
              2026-09-02 10:30
              系統已更新至最新

[ ] Snapshot the virtual machine's memory      ← 關機時不會出現此選項

              [ Take Snapshot ]  [ Cancel ]
```

> [!tip] ★★★★ 快照命名要能讓三個月後的你看懂
> 壞的命名：`snapshot1`、`test`、`123`、`備份`
> 好的命名：`before-nginx-install`、`clean-base-20260902`、`after-cert-setup`
>
> **Description 一定要填**，寫清楚：什麼時候拍的、當時系統是什麼狀態、
> 為什麼拍這個快照。三個月後你會感謝自己。★★★★

拍完之後，看虛擬機資料夾：

```powershell
Get-ChildItem D:\VMs\lab-web-01 | Select-Object Name, Length
```

預期輸出：

```text
Name                             Length
----                             ------
lab-web-01-000001.vmdk              327
lab-web-01-000001-s001.vmdk    67108864
lab-web-01.nvram                   8684
lab-web-01.vmdk                     365
lab-web-01.vmsd                     512
lab-web-01.vmsn                   32768
lab-web-01.vmx                     2891
```

`-000001` 就是新產生的差異磁碟，`.vmsd` 是快照的中繼資料，`.vmsn` 是狀態檔。★★★

### ★★★★ 快照管理員

```text
VM → Snapshot → Snapshot Manager...
```

或 `Ctrl+M`。畫面大致是一棵樹：

```text
┌─────────────────────────────────────────────────┐
│  Snapshot Manager - lab-web-01                  │
│                                                 │
│   ┌──────────────┐                              │
│   │ clean-base   │                              │
│   └──────┬───────┘                              │
│          │                                      │
│   ┌──────▼──────────────┐                       │
│   │ before-nginx-install│                       │
│   └──────┬──────────────┘                       │
│          │                                      │
│   ┌──────▼───────┐                              │
│   │ You Are Here │  ← 目前狀態                  │
│   └──────────────┘                              │
│                                                 │
│  [Go To] [Clone] [Delete] [Delete All] [AutoProtect] [Close] │
└─────────────────────────────────────────────────┘
```

| 按鈕 | 作用 | 注意 |
| --- | --- | --- |
| **Go To** ★★★★★ | 回復到選中的快照 | **當前未存的狀態會消失** |
| **Clone** ★★★ | 從這個快照做複製 | 連結複製的入口 |
| **Delete** ★★★★ | 刪除快照（合併回下層） | 資料不會丟，但要時間與空間 |
| **Delete All** ★★★★ | 刪除所有快照 | 全部合併，VM 回到單一磁碟 |
| **AutoProtect** ★★★ | 自動定時拍快照 | 見下方警告 |

### ★★★★★ 回復到快照（Go To）

選中快照，按 **Go To**。會跳出確認：

```text
The current state of the virtual machine will be lost unless you save
it in a new snapshot. Do you want to take a snapshot of the current
state before restoring?

[ Take Snapshot ]   [ Discard ]   [ Cancel ]
```

> [!danger] ★★★★★ Go To 會丟掉「拍快照之後到現在」的所有改動
> 你在快照之後裝的軟體、改的設定、寫的檔案、存的資料，**全部消失**，
> 而且**不可復原**。
>
> 這個對話框給你三個選擇：
> - **Take Snapshot**：先把當前狀態存成新快照再回復（安全，但快照數量會增加）
> - **Discard**：丟掉當前狀態直接回復（快，但不可逆）
> - **Cancel**：算了
>
> 不確定的時候一律先 Take Snapshot。★★★★★

回復後，快照樹會變成：

```text
   clean-base
       │
   before-nginx-install
       │
   ┌───┴────────────────┐
   │                    │
You Are Here      （原本的分支，如果選了 Take Snapshot 才會留著）
```

回到某個中間快照再繼續改，會產生**分支**。分支很方便（可以比較兩種做法），
但也會讓樹變得複雜、鏈變長，**不建議超過兩層分支**。★★★

### ★★★★ 刪除快照

選中快照，按 **Delete**。

> [!note] ★★★★ 「刪除快照」不會丟掉資料
> 這是最常被誤解的地方。刪除快照的實際動作是**把該快照之上的差異合併回它下層**，
> 然後移除那一層。你**目前看到的系統狀態完全不變**。
>
> 你失去的只是「回到那個時間點的能力」，不是資料本身。★★★★
>
> 唯一例外：如果你選中的是「當前狀態的祖先」而且你**先 Go To 到更早的快照**，
> 那當然是另一回事。單純的 Delete 不會動到當前狀態。

刪除過程會顯示進度：

```text
Consolidating snapshot for 'lab-web-01'...   45%
```

合併的時間取決於差異磁碟的大小，幾 GB 的差異可能要幾分鐘。

> [!danger] ★★★★★ 合併中不要斷電、不要強制關掉 Workstation
> 合併是對磁碟檔的實際改寫。中途被打斷會讓磁碟鏈處於不一致狀態，
> 最壞的情況是整台 VM 開不起來。
>
> 主機要重開、要關機，**先等合併跑完**。

**Delete All** 會把所有快照一次合併掉，VM 回到單一磁碟的乾淨狀態。
做效能測試前、要擴充磁碟前，用這個。

### ★★★ AutoProtect：自動快照

快照管理員裡有 **AutoProtect** 分頁：

```text
[ ] Enable AutoProtect

Interval:              [ Hourly  v ]
Maximum AutoProtect snapshots to keep:  [ 3  v ]

Estimated maximum disk usage: 12.4 GB
```

它會定時自動拍快照，保留最近 N 個。

> [!warning] ★★★★ AutoProtect 的三個問題
> 1. **它會持續消耗主機磁碟空間**，而且對話框的估計值常常低估 ★★★★
> 2. 它拍快照的那一刻 VM 會短暫停頓，正在做的事情可能受影響 ★★★
> 3. **它一樣不是備份**——所有問題都在同一顆磁碟上 ★★★★★
>
> 本手冊的立場：**實驗環境不要開 AutoProtect**。
> 你需要的是自己決定「在什麼時候」拍快照，而不是機器每小時亂拍。

### ★★★★ 完整複製（Full Clone）

**來源 VM 必須是關機狀態。**

```text
VM → Manage → Clone...
```

精靈：

**頁 1：複製來源**

```text
Clone from:
  (•) The current state in the virtual machine
  ( ) An existing snapshot (powered off only):
      [ clean-base  v ]
```

**頁 2：複製類型**

```text
( ) Create a linked clone
(•) Create a full clone
```

**頁 3：名稱與位置**

```text
Virtual machine name:  lab-web-fullclone
Location:              D:\VMs\lab-web-fullclone
```

按 Finish，開始複製。畫面顯示：

```text
Cloning virtual machine...   68%
```

完成後兩台完全獨立。

### ★★★★★ 連結複製（Linked Clone）

**來源 VM 必須是關機狀態，而且要有快照。**

```text
VM → Manage → Clone...
```

**頁 1：複製來源** —— 選快照

```text
Clone from:
  ( ) The current state in the virtual machine
  (•) An existing snapshot (powered off only):
      [ clean-base  v ]           ← 選你的乾淨快照
```

**頁 2：複製類型**

```text
(•) Create a linked clone

    A linked clone is a reference to the original virtual machine and
    requires less disk space to store. However, it cannot run without
    access to the original virtual machine.

( ) Create a full clone
```

**頁 3：名稱與位置**

```text
Virtual machine name:  lab-web-01
Location:              D:\VMs\lab-web-01
```

按 Finish。**幾秒鐘就完成**。

驗證磁碟佔用：

```powershell
Get-ChildItem D:\VMs\lab-web-01 -Recurse |
  Measure-Object -Property Length -Sum |
  Select-Object @{n='MB';e={[math]::Round($_.Sum/1MB,1)}}
```

預期輸出：

```text
   MB
   --
 76.3
```

**76 MB**，而來源實際佔用約 5 GB。這就是連結複製的價值。★★★★★

> [!warning] ★★★★ 連結複製會在來源 VM 上留下痕跡
> 建立連結複製時，Workstation 會在來源 VM 加上一個標記，
> 之後你在快照管理員刪那個被依賴的快照時會被擋下：
>
> ```text
> This snapshot cannot be deleted because it is being used by one or
> more linked clones.
> ```
>
> 這是保護機制，是好事。★★★

---

## 進階應用

### ★★★★★ 複製後一定要改的四樣東西

從範本複製出來的機器，**在網路上和來源是「同一台」**——一樣的 hostname、
一樣的 machine-id、一樣的 SSH 主機金鑰、一樣的靜態 IP。
兩台同時開機會出各種怪事。

| 項目 | 不改的後果 | 嚴重度 |
| --- | --- | --- |
| hostname | 日誌、監控分不清是哪一台；prompt 看起來都一樣會操作錯機器 | ★★★ |
| `/etc/machine-id` | systemd-networkd 用它產生 DHCP client identifier，**多台互搶同一個 IP** | ★★★★ |
| SSH host key | 所有機器指紋相同，**中間人偵測失效**；SSH client 的 known_hosts 也會混亂 | ★★★★ |
| 靜態 IP | **IP 衝突**，兩台都不通 | ★★★★★ |

#### 一次做完的腳本

在**新複製出來的機器上**（用 Workstation 主控台，不要用 SSH——會斷線）執行：

```bash
#!/usr/bin/env bash
# rename-clone.sh — 從範本複製出來後的初始化
# 用法：sudo bash rename-clone.sh <新hostname> <新IP最後一段>
set -euo pipefail

NEW_HOST="${1:?用法: sudo bash rename-clone.sh <hostname> <ip最後一段>}"
NEW_OCTET="${2:?用法: sudo bash rename-clone.sh <hostname> <ip最後一段>}"

# 網段與閘道（依你的 NAT 網段調整）
SUBNET="192.168.152"
GATEWAY="${SUBNET}.2"
IFACE="ens33"

echo "==> 1/5 設定 hostname 為 ${NEW_HOST}"
hostnamectl set-hostname "${NEW_HOST}"
sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t${NEW_HOST}/" /etc/hosts

echo "==> 2/5 重新產生 machine-id"
rm -f /etc/machine-id /var/lib/dbus/machine-id
systemd-machine-id-setup
ln -sf /etc/machine-id /var/lib/dbus/machine-id

echo "==> 3/5 重新產生 SSH 主機金鑰"
rm -f /etc/ssh/ssh_host_*
ssh-keygen -A
systemctl restart ssh

echo "==> 4/5 設定靜態 IP 為 ${SUBNET}.${NEW_OCTET}"
cat > /etc/netplan/01-static.yaml <<EOF
network:
  version: 2
  renderer: networkd
  ethernets:
    ${IFACE}:
      dhcp4: false
      addresses:
        - ${SUBNET}.${NEW_OCTET}/24
      routes:
        - to: default
          via: ${GATEWAY}
      nameservers:
        addresses: [${GATEWAY}, 1.1.1.1]
EOF
chmod 600 /etc/netplan/01-static.yaml
netplan generate

echo "==> 5/5 清除日誌與歷史"
journalctl --rotate
journalctl --vacuum-time=1s
: > /root/.bash_history || true

echo
echo "完成。請執行 'sudo reboot' 讓所有設定生效。"
echo "新位址：${SUBNET}.${NEW_OCTET}   新主機名：${NEW_HOST}"
```

用法：

```bash
sudo bash rename-clone.sh lab-web-01 51
sudo reboot
```

重開機後驗證：

```bash
hostnamectl | head -2
cat /etc/machine-id
ip -4 addr show ens33 | grep inet
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

預期輸出：

```text
 Static hostname: lab-web-01
       Icon name: computer-vm

7f3a9c2e5b184d6ea1c8f0d3b7e2a941

    inet 192.168.152.51/24 brd 192.168.152.255 scope global ens33

256 SHA256:kQ8v...省略... root@lab-web-01 (ED25519)
```

**把每一台的指紋都記下來**，和來源那台的指紋比對，確認不同。★★★★

> [!tip] ★★★ 把這個腳本放進範本裡
> 在建立 `lab-ubuntu-base` 範本時就把 `rename-clone.sh` 放到
> `/usr/local/sbin/rename-clone.sh` 並 `chmod +x`，
> 之後每台複製出來的機器開機第一件事就是跑它。
>
> 注意：**腳本內容不含任何機密**（沒有密碼、沒有金鑰），所以放進範本是安全的。

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> RHEL 系的差異：
>
> - 網路設定用 **NetworkManager**，不是 netplan：
>
>   ```bash
>   sudo nmcli con mod ens160 ipv4.method manual \
>       ipv4.addresses 192.168.152.51/24 \
>       ipv4.gateway 192.168.152.2 \
>       ipv4.dns "192.168.152.2 1.1.1.1"
>   sudo nmcli con up ens160
>   ```
>
>   ★★★ 注意 RHEL 9 的預設介面名稱常是 `ens160` 而非 `ens33`，
>   先用 `nmcli device status` 確認。
>
> - 沒有 `netplan try` 這種自動回復機制。要安全操作可以先排一個「五分鐘後還原」的定時工作：
>
>   ```bash
>   sudo bash -c 'echo "nmcli con up ens160-backup" | at now + 5 minutes'
>   ```
>
>   確認新設定可用後再 `atrm` 取消。★★★★
>
> - `machine-id`、SSH host key 的處理**完全相同**（`systemd-machine-id-setup`、`ssh-keygen -A`）。
> - hostname 也是 `hostnamectl set-hostname`。
> - 清日誌一樣用 `journalctl --vacuum-time=1s`。

### ★★★★ 用範本量產多台實驗機

假設某一章需要三台機器（一台 Nginx、一台 MySQL、一台客戶端）。

```text
lab-ubuntu-base (關機，有 clean-base 快照)
    │
    ├─ 連結複製 → lab-web-01     192.168.152.51
    ├─ 連結複製 → lab-db-01      192.168.152.52
    └─ 連結複製 → lab-client-01  192.168.152.53
```

流程：

```text
對每一台重複：
  1. VM → Manage → Clone → 選 clean-base 快照 → Linked clone
  2. 命名（lab-web-01）、位置（D:\VMs\lab-web-01）
  3. Finish（幾秒完成）
  4. 開機，主控台登入
  5. sudo bash /usr/local/sbin/rename-clone.sh lab-web-01 51
  6. sudo reboot
  7. 從主機 ssh labadmin@192.168.152.51 確認連得進去
  8. VM → Snapshot → Take Snapshot → 命名 fresh
```

第 8 步的 `fresh` 快照很重要：**這是你做實驗的起點**。
弄壞了 Go To 回 `fresh`，三秒回到剛複製好的乾淨狀態，
不用重新複製、不用重跑改名腳本。★★★★

> [!warning] ★★★★ 注意此時的磁碟鏈已經有三層
> ```text
> lab-ubuntu-base.vmdk           (唯讀，範本基礎)
>     └─ clean-base 差異磁碟      (唯讀，範本快照)
>         └─ lab-web-01 差異磁碟  (連結複製自己的)
>             └─ fresh 差異磁碟   (實驗機的還原點)
> ```
>
> 四層鏈，讀取最壞要查四層。**日常操作感覺不出來，但不要在上面再疊五個快照**。
> 要做效能測試就改用完整複製。★★★★

### ★★★ 磁碟佔用的實際比較

同樣是三台實驗機：

| 做法 | 磁碟佔用 | 建立時間 |
| --- | --- | --- |
| 各自從 ISO 裝一遍 ★ | 3 × 5 GB = 15 GB | 3 × 20 分鐘 = 60 分鐘 |
| 完整複製 × 3 ★★★ | 5 + 3 × 5 = 20 GB | 3 × 3 分鐘 = 9 分鐘 |
| **連結複製 × 3** ★★★★★ | 5 + 3 × 0.1 = **5.3 GB** | 3 × 10 秒 = **30 秒** |

實際驗證：

```powershell
"lab-ubuntu-base","lab-web-01","lab-db-01","lab-client-01" | ForEach-Object {
    $p = "D:\VMs\$_"
    $sum = (Get-ChildItem $p -Recurse -File | Measure-Object Length -Sum).Sum
    [PSCustomObject]@{ VM = $_; GB = [math]::Round($sum/1GB, 2) }
}
```

預期輸出：

```text
VM              GB
--              --
lab-ubuntu-base 5.12
lab-web-01      0.08
lab-db-01       0.08
lab-client-01   0.08
```

### ★★★ 用完整複製把某台實驗機「畢業」成新範本

有時候你做完某章實驗，覺得那台機器的狀態值得留下來當新範本
（例如「已經裝好完整 LXMP 環境的機器」）。

**不能直接拿連結複製的機器當新範本**——它依賴來源，複雜度會失控。
正確做法是把它**完整複製**成一台獨立的機器：

```text
1. lab-web-01 關機
2. VM → Manage → Clone → The current state → Create a full clone
3. 命名 lab-lxmp-base，放到 D:\VMs\lab-lxmp-base
4. 開機，跑清理（apt clean、清日誌、清 history、清設定檔裡的測試資料）
5. 關機
6. 拍快照 clean-lxmp
7. 之後從這台做連結複製
```

新範本產生後，`lab-web-01` 就可以刪掉了。★★★

### ★★★ 匯出成 OVF：真正可攜的一份

要把 VM 交給同事、或存到外接硬碟當備份，用 OVF/OVA 匯出。

```text
File → Export to OVF...
```

或用命令列工具 `ovftool`（隨 Workstation 安裝，路徑見
[[050-01-02-01-svc-Workstation-安裝與授權]]）：

```bash
ovftool /home/user/VMs/lab-ubuntu-base/lab-ubuntu-base.vmx \
        /mnt/backup/lab-ubuntu-base.ova
```

預期輸出：

```text
Opening VMX source: /home/user/VMs/lab-ubuntu-base/lab-ubuntu-base.vmx
Opening OVA target: /mnt/backup/lab-ubuntu-base.ova
Writing OVA package: /mnt/backup/lab-ubuntu-base.ova
Transfer Completed
Completed successfully
```

> [!warning] ★★★★ 匯出 OVF 之前要先刪光快照
> 有快照的 VM 匯出時 `ovftool` 會報錯或只匯出當前狀態，
> 而且結果常常不如預期。**先 Delete All Snapshots，再匯出**。
>
> 也不能匯出連結複製的 VM（缺基礎磁碟），必須先做完整複製。★★★★

> [!tip] ★★★★ OVA 放到外接硬碟才算備份
> 匯出到 `D:\backup\`（同一顆磁碟）不算備份。
> 匯出到外接硬碟、NAS、或機關的備份儲存，那才是。
> 符合 3-2-1 原則的做法是：本機一份、NAS 一份、離線媒體一份。

---

## 完整實戰範例

### 情境

你已經按 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]]
建好 `lab-ubuntu-base`（Ubuntu Server 24.04，NAT，靜態 IP `192.168.152.50`，
帳號 `labadmin`，已裝 open-vm-tools 與 SSH）。

現在要為「Nginx 反向代理實驗」準備環境：**兩台機器**，
一台當 Web 伺服器（`lab-web-01`，`.51`），一台當後端應用（`lab-app-01`，`.52`）。
全部用連結複製，並且要能互相 ping 得到、主機也連得到。

### 步驟 1：把改名腳本放進範本 ★★★★

先開機 `lab-ubuntu-base`（這是最後一次動它）：

```bash
sudo tee /usr/local/sbin/rename-clone.sh > /dev/null <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
NEW_HOST="${1:?用法: sudo bash rename-clone.sh <hostname> <ip最後一段>}"
NEW_OCTET="${2:?用法: sudo bash rename-clone.sh <hostname> <ip最後一段>}"
SUBNET="192.168.152"
GATEWAY="${SUBNET}.2"
IFACE="ens33"

echo "==> 1/5 hostname -> ${NEW_HOST}"
hostnamectl set-hostname "${NEW_HOST}"
sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t${NEW_HOST}/" /etc/hosts

echo "==> 2/5 machine-id"
rm -f /etc/machine-id /var/lib/dbus/machine-id
systemd-machine-id-setup
ln -sf /etc/machine-id /var/lib/dbus/machine-id

echo "==> 3/5 SSH host keys"
rm -f /etc/ssh/ssh_host_*
ssh-keygen -A
systemctl restart ssh

echo "==> 4/5 static IP -> ${SUBNET}.${NEW_OCTET}"
cat > /etc/netplan/01-static.yaml <<EOF
network:
  version: 2
  renderer: networkd
  ethernets:
    ${IFACE}:
      dhcp4: false
      addresses:
        - ${SUBNET}.${NEW_OCTET}/24
      routes:
        - to: default
          via: ${GATEWAY}
      nameservers:
        addresses: [${GATEWAY}, 1.1.1.1]
EOF
chmod 600 /etc/netplan/01-static.yaml
netplan generate

echo "==> 5/5 清日誌"
journalctl --rotate
journalctl --vacuum-time=1s

echo "完成，請 sudo reboot"
SCRIPT

sudo chmod +x /usr/local/sbin/rename-clone.sh
```

驗證：

```bash
ls -l /usr/local/sbin/rename-clone.sh
bash -n /usr/local/sbin/rename-clone.sh && echo "語法 OK"
```

預期輸出：

```text
-rwxr-xr-x 1 root root 1187 Sep  2 11:02 /usr/local/sbin/rename-clone.sh
語法 OK
```

### 步驟 2：清理範本並關機 ★★★★

```bash
sudo apt clean
sudo apt autoremove -y
sudo journalctl --rotate
sudo journalctl --vacuum-time=1s
history -c && cat /dev/null > ~/.bash_history
sudo shutdown -h now
```

### 步驟 3：拍乾淨快照 ★★★★★

等 Workstation 顯示 VM 已關機。

```text
VM → Snapshot → Take Snapshot...

Name:         clean-base
Description:  Ubuntu Server 24.04.3 LTS
              更新至 2026-09-02
              已裝 open-vm-tools + 常用工具
              已放 /usr/local/sbin/rename-clone.sh
              未安裝任何服務
              帳號 labadmin，靜態 IP 192.168.152.50

[ Take Snapshot ]
```

確認快照存在：

```text
VM → Snapshot → Snapshot Manager
```

應該看到 `clean-base` 底下接著 `You Are Here`。

在 VM 的 Notes 欄位（VM → Settings → Options → General → Notes）寫上：

```text
【範本，請勿刪除或移動】
此 VM 為多台連結複製的基礎磁碟來源。
刪除或搬移此資料夾會導致所有連結複製的 VM 全部無法開機。
```

### 步驟 4：連結複製第一台 ★★★★★

```text
VM → Manage → Clone...

頁 1  Clone from:  (•) An existing snapshot: [ clean-base ]
頁 2  (•) Create a linked clone
頁 3  Name:     lab-web-01
      Location: D:\VMs\lab-web-01

[ Finish ]
```

幾秒完成。確認：

```powershell
Get-ChildItem D:\VMs\lab-web-01 -Recurse -File |
  Measure-Object Length -Sum |
  Select-Object @{n='MB';e={[math]::Round($_.Sum/1MB,1)}}
```

預期輸出：

```text
   MB
   --
 78.4
```

### 步驟 5：初始化第一台 ★★★★

開機 `lab-web-01`。**用 Workstation 主控台登入，不要用 SSH**——
腳本會改 IP，SSH 會斷。

```bash
sudo bash /usr/local/sbin/rename-clone.sh lab-web-01 51
```

預期輸出：

```text
==> 1/5 hostname -> lab-web-01
==> 2/5 machine-id
Initializing machine ID from random generator.
==> 3/5 SSH host keys
ssh-keygen: generating new host keys: RSA ECDSA ED25519
==> 4/5 static IP -> 192.168.152.51
==> 5/5 清日誌
Vacuuming done, freed 0B of archived journals...
完成，請 sudo reboot
```

```bash
sudo reboot
```

重開後驗證：

```bash
hostnamectl | grep -E 'hostname|Machine ID'
ip -4 addr show ens33 | grep inet
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub | awk '{print $2}'
```

預期輸出：

```text
 Static hostname: lab-web-01
      Machine ID: c81f4a2d90b7436e8f13a5c206d7e9b4

    inet 192.168.152.51/24 brd 192.168.152.255 scope global ens33

SHA256:vT2p...省略...
```

### 步驟 6：連結複製第二台並初始化 ★★★★

回到 `lab-ubuntu-base`（仍然關機），重複步驟 4～5：

```text
Clone from clean-base → Linked clone → lab-app-01 → D:\VMs\lab-app-01
```

開機後：

```bash
sudo bash /usr/local/sbin/rename-clone.sh lab-app-01 52
sudo reboot
```

### 步驟 7：驗證兩台的識別碼確實不同 ★★★★

在 `lab-web-01` 上：

```bash
cat /etc/machine-id
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub | awk '{print $2}'
```

在 `lab-app-01` 上跑同樣兩行。**兩台的輸出必須完全不同**。

如果相同，代表改名腳本沒跑成功，要重跑。★★★★

### 步驟 8：驗證網路連通 ★★★★

在 `lab-web-01`：

```bash
ping -c 2 192.168.152.52     # 對方 VM
ping -c 2 192.168.152.2      # NAT 閘道
ping -c 2 1.1.1.1            # 外網
```

預期三個都通：

```text
PING 192.168.152.52 (192.168.152.52) 56(84) bytes of data.
64 bytes from 192.168.152.52: icmp_seq=1 ttl=64 time=0.418 ms
64 bytes from 192.168.152.52: icmp_seq=2 ttl=64 time=0.395 ms
--- 192.168.152.52 ping statistics ---
2 packets transmitted, 2 received, 0% packet loss, time 1001ms
```

在**主機**上：

```powershell
ssh labadmin@192.168.152.51 hostname
ssh labadmin@192.168.152.52 hostname
```

預期輸出：

```text
lab-web-01
lab-app-01
```

> [!tip] ★★★ 主機的 known_hosts 可能要清
> 如果你之前連過 `192.168.152.51` 而那時是別台機器，會看到：
>
> ```text
> WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!
> ```
>
> 這正是 SSH host key 有正確重新產生的證明（防中間人機制在運作）。清掉舊記錄：
>
> ```bash
> ssh-keygen -R 192.168.152.51
> ```

### 步驟 9：為兩台各拍 `fresh` 快照 ★★★★★

兩台都關機（`sudo shutdown -h now`），然後各自：

```text
VM → Snapshot → Take Snapshot...
Name:         fresh
Description:  剛完成 clone + rename，尚未安裝任何服務
              可從此點重新開始 Nginx 實驗
```

### 步驟 10：檢視整個磁碟鏈 ★★★

```powershell
"lab-ubuntu-base","lab-web-01","lab-app-01" | ForEach-Object {
    $sum = (Get-ChildItem "D:\VMs\$_" -Recurse -File | Measure-Object Length -Sum).Sum
    [PSCustomObject]@{ VM=$_; GB=[math]::Round($sum/1GB,2) }
}
```

預期輸出：

```text
VM              GB
--              --
lab-ubuntu-base 5.14
lab-web-01      0.21
lab-app-01      0.19
```

**兩台實驗機加起來只多佔 0.4 GB**。如果用完整複製，會是 10 GB。★★★★★

### 完成確認

- [ ] `lab-ubuntu-base` 關機、有 `clean-base` 快照、Notes 有警告文字 ★★★★★
- [ ] `lab-web-01` 與 `lab-app-01` 都是連結複製，各佔不到 300 MB ★★★★
- [ ] 兩台的 hostname 不同 ★★★
- [ ] 兩台的 `/etc/machine-id` 不同 ★★★★
- [ ] 兩台的 SSH host key 指紋不同 ★★★★
- [ ] 兩台的 IP 分別是 `.51` 與 `.52`，互相 ping 得通 ★★★★
- [ ] 主機能 SSH 連入兩台 ★★★★
- [ ] 兩台各有一個 `fresh` 快照 ★★★★
- [ ] 每台的快照數量都是 1（不要一開始就疊很多）★★★

### 實驗做完之後

該章實驗結束時：

```text
選項 A（最乾淨）：整台刪掉
  VM → Manage → Delete from Disk
  → 這會刪掉 lab-web-01 資料夾，範本完全不受影響 ★★★★

選項 B（要留著）：回復到 fresh 並刪掉其他快照
  Snapshot Manager → Go To: fresh
  → 再把 fresh 之後產生的快照 Delete
```

> [!danger] ★★★★★ 刪 VM 時看清楚刪的是哪一台
> `VM → Manage → Delete from Disk` 是**不可逆的檔案刪除**。
> 選錯成 `lab-ubuntu-base`，你的範本和所有連結複製的機器同時報廢。
>
> 刪之前先看標題列上的 VM 名稱，念一遍再按。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| 連結複製的 VM 開機報 `Cannot open the disk ... or one of the snapshot disks it depends on` ★★★★★ | 來源 VM 被刪除、改名或搬移 | 把來源資料夾還原到原路徑與原名稱；或手動編輯複本的 `.vmdk` 描述檔修正 `parentFileNameHint` 路徑 |
| 快照管理員裡 Delete 某個快照被擋，訊息提到 linked clones ★★★ | 該快照正被連結複製依賴 | 先刪掉所有依賴它的連結複製 VM，或把那些 VM 轉成完整複製 |
| Settings → Hard Disk 的 Expand 是灰色 ★★★★ | VM 有快照 | Snapshot Manager → Delete All Snapshots，再擴充 |
| 刪除快照跑到一半失敗，VM 開不起來 ★★★★★ | 合併過程被中斷，或主機空間不足 | 先清出主機空間；看 VM 資料夾內 `.log` 找錯誤；嚴重時只能從備份還原 |
| 主機磁碟莫名被吃光 ★★★★ | 快照差異磁碟持續成長；動態磁碟只長不縮 | 刪掉不需要的快照；壓實磁碟見 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] |
| 兩台複製出來的機器搶同一個 IP ★★★★ | `machine-id` 相同，DHCP client identifier 撞在一起 | 在其中一台跑 `systemd-machine-id-setup` 重新產生後重開機 |
| SSH 連新機器報 `REMOTE HOST IDENTIFICATION HAS CHANGED` ★★★ | 該 IP 之前是別台機器（host key 不同）——這是正常且正確的 | `ssh-keygen -R <IP>` 清掉舊記錄再連 |
| 兩台機器 SSH 指紋一模一樣 ★★★★ | 複製後沒有重新產生 SSH host key | `sudo rm -f /etc/ssh/ssh_host_* && sudo ssh-keygen -A && sudo systemctl restart ssh` |
| VM 越用越慢，開機要好幾分鐘 ★★★★ | 快照鏈太長 | Snapshot Manager 檢視數量，Delete All 合併回單一磁碟 |
| 效能測試數據忽高忽低不可信 ★★★★ | 有快照，讀寫要走差異磁碟鏈 | 測試前一定 Delete All Snapshots，或改用完整複製 |
| `Clone` 選項是灰色或整個選單沒有 ★★★ | VM 開機中；或使用的是 Workstation Player（無此功能） | 先關機；Player 沒有 Clone，改用手動複製整個資料夾（等同完整複製） |
| Clone 精靈裡 `Create a linked clone` 是灰色 ★★★ | 來源 VM 沒有任何快照，或選了 `The current state` | 先關機拍一個快照，複製時選 `An existing snapshot` |
| 完整複製之後兩台一起開機，網路都不通 ★★★★ | 兩台 IP 相同造成衝突 | 其中一台改 IP；用 `arping` 或 `ip neigh` 確認衝突 |
| 匯出 OVF 失敗或內容不符預期 ★★★★ | VM 有快照，或這是連結複製的 VM | 先 Delete All Snapshots；連結複製要先轉成完整複製 |
| `Take Snapshot` 很慢、跑了好幾分鐘 ★★★ | 勾了 `Snapshot the virtual machine's memory`，要寫入等同記憶體大小的檔案 | 關機後再拍，或不要勾記憶體選項 |
| 回復快照後資料庫損毀、要跑修復 ★★★★ | 開機中拍的快照沒含記憶體，回復等同硬斷電 | 拍快照前先關機；或拍快照時勾記憶體 |
| Go To 之後發現重要檔案不見了 ★★★★★ | 回復會丟掉快照之後的所有改動，且不可逆 | 無解，只能從備份還原。**下次回復前先 Take Snapshot 保住當前狀態** |
| VM 資料夾裡有一堆 `-000001` 到 `-000009` 的 vmdk ★★★★ | 累積了九個快照 | Snapshot Manager 檢視並 Delete All |
| 刪掉一台複製機後，範本也開不起來 ★★★ | 誤刪的其實是範本；或範本的快照被刪 | 檢查 `.vmsd` 與 `.vmdk` 是否完整；從備份還原 |
| AutoProtect 把主機空間吃光 ★★★★ | 自動快照持續累積 | Snapshot Manager → AutoProtect 分頁取消勾選，並手動刪掉已產生的自動快照 |

---

## 安全性注意事項

### ★★★★★ 快照不能取代備份（再說一次）

機關的資通安全稽核會問「你的備份機制是什麼」。回答「我有快照」**不會過**，
而且應該不會過——理由前面列了五條。

機關環境的最低要求：

| 層級 | 要求 |
| --- | --- |
| 快照 ★★★ | 變更前的短期還原點，用完即刪 |
| 本機副本 ★★★ | 完整複製或 OVA，放在另一顆磁碟 |
| 異地備份 ★★★★★ | NAS／備份主機／離線媒體，符合 3-2-1 |
| 還原演練 ★★★★★ | **定期實際還原一次**，沒演練過的備份等於沒有備份 |

### ★★★★ 範本裡不能有任何機密

範本會被複製 N 次，每一份都帶著範本裡的所有東西。

| 絕對不能放進範本 | 原因 |
| --- | --- |
| SSH 私鑰（`~/.ssh/id_*`）★★★★★ | 每台複本都能登入同樣的目標 |
| 伺服器憑證私鑰 ★★★★★ | 私鑰擴散 = 憑證形同作廢 |
| API 金鑰、資料庫密碼 ★★★★★ | 一台被入侵，全部曝光 |
| 機關實際資料 ★★★★★ | 個資外洩風險 |
| `.bash_history` 裡含密碼的指令 ★★★★ | 明文密碼躺在每一份複本裡 |
| 已認證的雲端 CLI 憑證（`~/.aws`、`~/.azure`）★★★★★ | 同上 |

清理指令（拍範本快照前跑）：

```bash
sudo find /home /root -name 'id_*' -o -name 'known_hosts' 2>/dev/null
sudo rm -f /root/.bash_history /home/*/.bash_history
sudo rm -rf /root/.aws /root/.azure /home/*/.aws /home/*/.azure
history -c
```

### ★★★★ SSH host key 重複的資安意義

SSH 的中間人防護機制，靠的是「這台主機的公鑰指紋和我上次看到的一樣」。

如果你的十台機器共用同一組 host key：

1. 客戶端無法分辨連到的是哪一台 ★★★★
2. 任何一台被入侵並竊走私鑰，攻擊者可以**冒充其他九台** ★★★★★
3. 客戶端的 `known_hosts` 永遠不會示警，即使真的被中間人攔截 ★★★★★

所以「複製後重新產生 host key」不是潔癖，是資安要求。★★★★

### ★★★ machine-id 也可能洩漏資訊

`/etc/machine-id` 會被一些應用程式用來當作機器識別碼，
甚至被拿來當某些加密操作的種子。多台共用同一個值時：

- 日誌集中收集端分不清來源，事件調查時無法定位是哪一台 ★★★★
- 某些軟體的授權綁定會出錯 ★★
- systemd-networkd 的 DHCP client identifier 相同 → IP 互搶 ★★★★

### ★★★★ 連結複製不適合放機密資料

連結複製的 VM 依賴範本的基礎磁碟。這代表：

- 你「刪掉」某台實驗機時，**它寫在基礎磁碟上的資料並沒有被刪**
  （基礎磁碟本來就是唯讀共用的，但概念上你要清楚資料的邊界在哪）★★★
- 多台複本共用同一份基礎磁碟，**如果基礎磁碟裡有機密，等於所有複本都有** ★★★★
- 要交出去、要銷毀的機器，必須是完整複製，而且銷毀要處理到基礎磁碟層 ★★★★

機關環境的原則：**處理實際業務資料的機器，不要用連結複製。** ★★★★

### ★★★ 快照裡也留著你以為刪掉的東西

你在 VM 裡刪掉一個機密檔案，然後想「刪掉了就沒事了」。
但如果那個檔案是在**拍快照之前**就存在的，它還躺在唯讀的基礎磁碟裡。
回復到那個快照，檔案就回來了。★★★★

要真正清除，必須**刪掉包含該檔案的所有快照**（合併掉），
或者更徹底：把那台 VM 整個銷毀。

### ★★★ 刪除 VM 檔案的正確方式

`VM → Manage → Delete from Disk` 只是一般的檔案刪除，
磁碟上的資料區塊還在，用還原軟體撈得回來。

處理過機密資料的 VM 要銷毀時：

```bash
# Linux 主機，對整個 VM 資料夾覆寫刪除
shred -vzu -n 1 /home/user/VMs/lab-secret/*.vmdk
rm -rf /home/user/VMs/lab-secret
```

> [!warning] ★★★ SSD 上 `shred` 的效果有限
> SSD 有寫入平均（wear leveling）與過度配置，`shred` 覆寫的不一定是原本的實體區塊。
> SSD 上比較可靠的做法是**全碟加密**（BitLocker／LUKS）——
> 銷毀時只要丟掉金鑰，資料就等同不可讀。★★★★

---

## 速查表

### 快照操作

| 動作 | 路徑 |
| --- | --- |
| 拍快照 | VM → Snapshot → Take Snapshot |
| 快照管理員 | VM → Snapshot → Snapshot Manager（`Ctrl+M`） |
| 回到上一個快照 | VM → Snapshot → Revert to Snapshot |
| 回復到指定快照 | Snapshot Manager → 選取 → Go To |
| 刪除單一快照 | Snapshot Manager → 選取 → Delete |
| 刪除全部快照 | Snapshot Manager → Delete All |
| 自動快照設定 | Snapshot Manager → AutoProtect 分頁 |

### 複製操作

| 動作 | 路徑 |
| --- | --- |
| 複製精靈（需關機） | VM → Manage → Clone |
| 從快照做連結複製 | Clone → An existing snapshot → Create a linked clone |
| 完整複製 | Clone → Create a full clone |
| 刪除 VM 檔案 | VM → Manage → Delete from Disk ★★★★★ |
| 匯出 OVF/OVA | File → Export to OVF |

### 快照 vs 備份

| 問題 | 快照 | 備份 |
| --- | --- | --- |
| 和原始資料分開存放？ | 否 ★★★★★ | 是 |
| 可以獨立還原？ | 否（依賴基礎磁碟） | 是 |
| 磁碟壞了救得回來？ | **不行** ★★★★★ | 可以 |
| 有版本與保留策略？ | 沒有 | 有 |
| 適合長期保存？ | 不適合 | 適合 |
| 拍攝／建立速度 | 秒 | 分鐘～小時 |
| 效能影響 | 有，且累積 ★★★★ | 無（備份完成後） |

### 連結複製 vs 完整複製

| 項目 | 連結複製 | 完整複製 |
| --- | --- | --- |
| 需要 Pro 版 | 是 | 否 |
| 建立時間 | 秒 | 分鐘 |
| 初始佔用 | 幾百 MB | 等同來源用量 |
| 依賴來源 | **完全依賴** ★★★★★ | 不依賴 |
| 來源可移動 | 否 | 是 |
| 可匯出 | 否 | 是 |
| 效能 | 略差 | 原生 |
| 適合 | 短期大量實驗機 | 長期／要搬走／效能測試 |

### 複製後必改四項

| 項目 | 指令 |
| --- | --- |
| hostname | `sudo hostnamectl set-hostname <新名>`＋改 `/etc/hosts` |
| machine-id | `sudo rm /etc/machine-id /var/lib/dbus/machine-id && sudo systemd-machine-id-setup` |
| SSH host key | `sudo rm -f /etc/ssh/ssh_host_* && sudo ssh-keygen -A && sudo systemctl restart ssh` |
| 靜態 IP | 改 `/etc/netplan/01-static.yaml` → `sudo netplan try` |

### 驗證指令

| 目的 | 指令 | 期望 |
| --- | --- | --- |
| 看 hostname | `hostnamectl` | 新名稱 |
| 看 machine-id | `cat /etc/machine-id` | 每台不同 |
| 看 SSH 指紋 | `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` | 每台不同 |
| 看 IP | `ip -4 addr show ens33` | 各自的位址 |
| 清主機 known_hosts | `ssh-keygen -R <IP>` | — |
| 看 VM 佔用（Windows）| `Get-ChildItem <path> -Recurse -File \| Measure-Object Length -Sum` | 連結複製應很小 |
| 看 VM 佔用（Linux）| `du -sh <VM資料夾>` | 同上 |

### 快照相關檔案

| 檔案 | 內容 |
| --- | --- |
| `<vm>-000001.vmdk` | 第一個快照的差異磁碟描述檔 |
| `<vm>-000001-s001.vmdk` | 差異磁碟的實際資料片段 |
| `<vm>.vmsd` | 快照樹的中繼資料（名稱、描述、關係） |
| `<vm>-Snapshot1.vmsn` | 快照狀態檔（勾記憶體時會很大） |
| `<vm>.vmem` | 執行中 VM 的記憶體對應檔 |

### 清理時機

| 條件 | 動作 |
| --- | --- |
| 變更驗證完成 | 立刻刪變更前的快照 |
| 快照 ≥ 3 個 | 檢視並清理 |
| 快照存在 > 2 週 | 檢討是否還需要 |
| 主機剩餘空間 < 20% | 立刻清 ★★★★★ |
| 要擴充虛擬磁碟 | 必須全刪 |
| 要做效能測試 | 必須全刪 |
| 要匯出 OVF | 必須全刪 |

---

## 練習題

> [!question]- 練習 1：親眼看見差異磁碟長出來
> 對一台實驗機拍快照，然後在客體裡寫一個 1 GB 的檔案，觀察主機端檔案大小變化；
> 再把檔案刪掉，再觀察一次。
>
> ---
> **解答**
>
> ```powershell
> # 拍快照前
> Get-ChildItem D:\VMs\lab-web-01 -Recurse -File | Measure-Object Length -Sum
> ```
>
> 拍快照（VM → Snapshot → Take Snapshot，命名 `test-delta`），然後在客體裡：
>
> ```bash
> dd if=/dev/urandom of=~/big.bin bs=1M count=1024 status=progress
> sync
> ```
>
> 回主機再量一次，差異磁碟會多出約 **1 GB**。
>
> 然後在客體裡：
>
> ```bash
> rm ~/big.bin
> sync
> ```
>
> 回主機第三次量測——**大小不會縮回去**。★★★★
>
> 結論：
> 1. 快照的差異磁碟隨改動量成長 ★★★
> 2. **刪檔不會讓它縮小**，這是「主機空間莫名被吃光」的主因 ★★★★
> 3. 唯一能回收的方法是刪掉快照（合併）
>
> 收尾：Snapshot Manager → Delete All。

> [!question]- 練習 2：測量快照鏈對效能的影響
> 在同一台 VM 上，分別在「無快照」與「疊了 5 個快照」的狀態下跑同樣的磁碟測試，比較數據。
>
> ---
> **解答**
>
> 測試指令（在客體裡）：
>
> ```bash
> # 寫入測試
> sync; dd if=/dev/zero of=~/test.bin bs=1M count=512 conv=fdatasync
> rm ~/test.bin
> ```
>
> 記下 `dd` 回報的速度，例如：
>
> ```text
> 536870912 bytes (537 MB, 512 MiB) copied, 3.21 s, 167 MB/s
> ```
>
> 然後連續拍五個快照（每拍一個就 `sudo apt install -y <某個套件>` 製造一點差異），
> 再跑同樣的測試。
>
> 預期結果：**寫入速度下降**，下降幅度視主機磁碟而定
> （NVMe SSD 上可能只降 10～20%，機械硬碟上可能腰斬）。★★★★
>
> 重點結論：**效能測試前一定要 Delete All Snapshots**，
> 不然數據不能拿來當基準。★★★★

> [!question]- 練習 3：故意觸發連結複製的斷鏈
> 建一台連結複製的 VM，關掉它，把來源 VM 的資料夾**改名**，然後開機看看發生什麼；
> 再改回來驗證能否救回。
>
> ---
> **解答**
>
> ```powershell
> Rename-Item D:\VMs\lab-ubuntu-base D:\VMs\lab-ubuntu-base-OLD
> ```
>
> 開機連結複製的 VM，會看到：
>
> ```text
> Cannot open the disk 'D:\VMs\lab-ubuntu-base\lab-ubuntu-base-000001.vmdk'
> or one of the snapshot disks it depends on.
>
> Reason: The system cannot find the file specified.
> ```
>
> 改回原名：
>
> ```powershell
> Rename-Item D:\VMs\lab-ubuntu-base-OLD D:\VMs\lab-ubuntu-base
> ```
>
> 再開機就正常了。
>
> 教訓：**連結複製的來源不能改名、不能搬移、不能刪除**。★★★★★
> 順便看一下複本的 `.vmdk` 描述檔（純文字，可用記事本開）：
>
> ```text
> parentFileNameHint="D:\VMs\lab-ubuntu-base\lab-ubuntu-base-000001.vmdk"
> ```
>
> 路徑就是寫死在這裡的。真的搬移了，可以手動改這行救回來，但很麻煩。

> [!question]- 練習 4：比較兩種複製的空間與時間
> 從同一個快照分別做一台連結複製與一台完整複製，記錄建立時間與磁碟佔用。
>
> ---
> **解答**
>
> ```powershell
> # 建立前記時，建立後量測
> "lab-linked","lab-full" | ForEach-Object {
>     $sum = (Get-ChildItem "D:\VMs\$_" -Recurse -File | Measure-Object Length -Sum).Sum
>     [PSCustomObject]@{ VM=$_; MB=[math]::Round($sum/1MB,1) }
> }
> ```
>
> 典型結果（來源實際用量約 5 GB）：
>
> ```text
> VM         MB
> --         --
> lab-linked  78.4
> lab-full  5137.2
> ```
>
> 時間：連結複製約 5～10 秒，完整複製約 2～5 分鐘（NVMe SSD）。
>
> 差距約 **65 倍空間、20 倍時間**。★★★★
> 但完整複製換來的是「獨立、可搬、可匯出」——選哪個要看用途。

> [!question]- 練習 5：驗證複製後的識別碼確實有換掉
> 建兩台連結複製的機器，一台跑改名腳本一台不跑，比較兩者與範本的三個識別碼。
>
> ---
> **解答**
>
> 在三台（範本、跑過腳本的、沒跑的）上各執行：
>
> ```bash
> echo "hostname : $(hostname)"
> echo "machine-id: $(cat /etc/machine-id)"
> echo "ssh-fp   : $(ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub | awk '{print $2}')"
> ```
>
> 預期：
>
> ```text
> 範本            lab-ubuntu-base / 7f3a...941 / SHA256:kQ8v...
> 跑過腳本的      lab-web-01      / c81f...9b4 / SHA256:vT2p...   ← 全部不同
> 沒跑腳本的      lab-ubuntu-base / 7f3a...941 / SHA256:kQ8v...   ← 全部相同
> ```
>
> 把「沒跑腳本的」那台和範本同時開機（範本要改成 DHCP 才看得出效果），
> 觀察 IP 是否互搶。★★★★
>
> 資安意義：SSH 指紋相同代表**中間人偵測完全失效**。★★★★★

> [!question]- 練習 6：實作「畢業成新範本」的流程
> 把一台裝好 Nginx 的連結複製機器，轉成一個獨立的新範本 `lab-nginx-base`。
>
> ---
> **解答**
>
> ```text
> 1. lab-web-01 關機
> 2. VM → Manage → Clone → The current state → Create a full clone
> 3. 名稱 lab-nginx-base，位置 D:\VMs\lab-nginx-base
> 4. 開機，跑清理：
> ```
>
> ```bash
> sudo systemctl stop nginx
> sudo apt clean && sudo apt autoremove -y
> sudo rm -f /var/log/nginx/*.log
> sudo journalctl --rotate && sudo journalctl --vacuum-time=1s
> sudo rm -f /etc/ssh/ssh_host_*      # 讓下次複製時重新產生
> history -c && cat /dev/null > ~/.bash_history
> sudo shutdown -h now
> ```
>
> ```text
> 5. 拍快照 clean-nginx，Description 寫清楚裝了什麼版本
> 6. VM Notes 註明「範本，勿刪勿搬」
> 7. 原本的 lab-web-01 可以刪掉了
> ```
>
> **為什麼要用完整複製**：如果直接拿連結複製的機器當新範本，
> 它自己還依賴 `lab-ubuntu-base`，鏈會變成四層以上，而且 `lab-ubuntu-base`
> 從此更不能動。完整複製切斷依賴，新範本是獨立的。★★★★

---

## 小測驗

Q1. 用一句話說明「拍快照」在磁碟層面實際做了什麼事。

Q2. 是非題：刪除快照會讓 VM 回到拍快照時的狀態，之後的改動會消失。

Q3. 列出至少三個「快照不是備份」的理由。

Q4. 這個操作會發生什麼事？
```text
Snapshot Manager → 選取「三週前的快照」→ Go To → Discard
```

Q5. 選擇題：一台連結複製的 VM 開機時報 `Cannot open the disk ... or one of the snapshot disks it depends on`。最可能的原因是？
（A）快照太多　（B）來源 VM 被刪除、改名或搬移　（C）磁碟空間不足　（D）沒裝 VMware Tools

Q6. 為什麼在 Workstation 裡「要擴充虛擬磁碟就必須先刪光快照」？

Q7. 從同一個範本連結複製出五台機器，如果都不改 `/etc/machine-id`，最可能出現什麼網路症狀？為什麼？

Q8. 是非題：連結複製的 VM 可以直接用 `File → Export to OVF` 匯出給同事使用。

Q9. 你要做磁碟效能測試，比較 ext4 與 XFS 的寫入速度。在動手之前，關於快照你必須先做什麼？為什麼？

Q10. 範本 `lab-ubuntu-base` 佔 5 GB，你要開三台實驗機。分別用「完整複製」與「連結複製」，總磁碟佔用各是多少？各自的主要風險是什麼？

> [!question]- 測驗答案
> **Q1.** 把原本的虛擬磁碟**凍結成唯讀**，另外開一個空白的**差異磁碟**，之後所有寫入都寫到差異磁碟裡；讀取時從鏈的最上層往下找。它沒有「複製一份資料」。★★★★（見「觀念說明 → 快照到底做了什麼」）
>
> **Q2.** **錯。** 那是 **Go To（回復）**的行為。**Delete（刪除快照）**是把差異合併回下層並移除那一層，**你目前看到的系統狀態完全不變**，只是失去「回到那個時間點的能力」。這是最常被誤解的地方。★★★★（見「刪除快照」）
>
> **Q3.** 任舉三個：（1）快照和原始磁碟在同一個資料夾、同一顆磁碟上，磁碟壞了一起死；（2）差異磁碟只有差異，**離開基礎磁碟就無法解讀**，不能獨立還原；（3）鏈是串聯的，中間任何一環損毀整條鏈全毀；（4）快照會過期，回復下去中間的資料全丟；（5）沒有版本管理與保留策略。★★★★★（見「快照不是備份」）
>
> **Q4.** 系統會**立刻回到三週前的狀態**，這三週內安裝的軟體、修改的設定、產生的資料**全部消失且不可復原**（`Discard` 表示放棄保存當前狀態）。安全做法是選 `Take Snapshot` 先把當前狀態存起來再回復。★★★★★（見「回復到快照」）
>
> **Q5.** **（B）**。連結複製把來源 VM 的快照磁碟路徑寫死在自己的 `.vmdk` 描述檔的 `parentFileNameHint` 裡，來源被刪、改名或搬移就找不到基礎磁碟。解法是把來源還原到原路徑原名稱。★★★★★（見「連結複製」警告與排錯表）
>
> **Q6.** 因為有快照時，磁碟資料**分散在整條差異磁碟鏈上**，基礎磁碟是唯讀且被鏈上層依賴的。改變基礎磁碟的大小會破壞鏈的一致性，所以 Workstation 直接把 Expand 按鈕鎖成灰色。做法是 Delete All Snapshots 合併回單一磁碟後再擴充。★★★★（見「事後調整硬體」與排錯表）
>
> **Q7.** **多台機器互搶同一個 IP**（或拿到相同位址）。因為 systemd-networkd 用 `/etc/machine-id` 來產生 DHCP client identifier，五台送出去的識別碼一模一樣，DHCP 伺服器認為它們是同一台，於是重複配發同一個位址。此外日誌集中收集端也分不清事件來自哪一台。★★★★（見「複製後一定要改的四樣東西」）
>
> **Q8.** **錯。** 連結複製的 VM **不包含基礎磁碟資料**，匯出的結果對方拿去開不起來。必須先把它做一次**完整複製**，並且刪光快照，才能匯出成可用的 OVF/OVA。★★★★（見「匯出成 OVF」與比較表）
>
> **Q9.** 必須先 **Delete All Snapshots**（或改用完整複製的乾淨 VM）。因為有快照時每次讀取最壞要走完整條差異磁碟鏈，首次寫入某區塊還要 copy-on-write，**測出來的數據反映的是快照鏈的開銷，不是檔案系統的差異**，結論不可信。★★★★（見「效能代價」與「清理時機」）
>
> **Q10.** 完整複製：5 + 3 × 5 = **20 GB**；連結複製：5 + 3 × 約 0.1 = **約 5.3 GB**。主要風險——完整複製：佔空間大、建立慢，但機器彼此獨立沒有連鎖風險；連結複製：**三台全部依賴範本，範本被刪／改名／搬移就三台同時報廢**，而且不能匯出、效能略差。★★★★（見「磁碟佔用的實際比較」與「連結複製 vs 完整複製」）

---

## 延伸閱讀

- [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] — 建出本篇要複製的那台範本
- [[050-01-02-01-svc-Workstation-安裝與授權]] — Pro 與 Player 的功能差異（連結複製是 Pro 專屬）
- [[050-01-02-04-guide-Workstation-網路模式]] — 多台複本要互通時的網路設計
- [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] — Tools 對關機與時間同步的影響
- [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] — 磁碟壓實與 I/O 瓶頸排查
- [[050-01-01-02-guide-虛擬化-虛擬化底層技術]] — copy-on-write 與差異磁碟的底層原理
- [[050-01-03-06-svc-PVE-備份與還原]] — Proxmox VE 的備份機制，對照「什麼才是真正的備份」
- [[050-01-03-03-guide-PVE-虛擬機管理]] — PVE 的快照與範本機制對照
- [[020-02-01-07-svc-SSH-安全強化]] — SSH host key 與中間人防護的完整說明
- [[020-02-03-02-ref-標準化-基準設定與範本化]] — 把範本流程制度化成機關的建置基準
- [[020-02-03-01-svc-標準化-新機建置標準流程]] — 新機上線的標準檢核
- [[020-01-19-guide-Linux-日誌系統]] — journald 清理與集中收集
