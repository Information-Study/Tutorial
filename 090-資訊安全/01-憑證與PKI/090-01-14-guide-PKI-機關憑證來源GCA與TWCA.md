---
title: "機關憑證來源：GCA 與 TWCA"
desc: "機關憑證的四條來源怎麼選、GPKI 與商業 CA 的申請流程骨架、沒有 ACME 時的續期因應"
aliases: [GCA, GPKI, TWCA, 政府憑證管理中心, 機關憑證, 政府憑證]
tags: [群組/資訊安全, 主題/PKI, 主題/憑證]
category: 憑證與PKI
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[090-01-03-guide-PKI-向CA申請憑證]]"]
updated: 2026-09-03
---

# 機關憑證來源：GCA 與 TWCA

> [!warning] 未實機驗證
> 本篇寫的是**流程結構與技術銜接**：怎麼判斷該走哪一條來源、每個階段技術人員要做什麼、
> 拿到憑證後怎麼組鏈與部署、沒有自動化時怎麼靠制度補。
>
> ★★★★★ 本篇**刻意不寫**任何申請表單編號、作業天數、費用金額、網址路徑、
> 承辦窗口與憑證類別代碼。這些會隨主管機關的公告與作業要點改版，
> 寫死在手冊裡只會害人照著過期的資訊送件、退件、然後憑證到期。
>
> 實際的表單、應備文件、作業時程與收件窗口，**一律以主管機關現行公告與作業要點為準**，
> 並請洽**貴機關資訊室的憑證管理窗口**或**憑證管理中心**確認。
> 動筆申請前先問到人，比讀完這篇更重要。

---

## 這篇你會學到

> [!abstract] 學習目標
> - ★★★★★ 用一棵決策樹判斷「這個服務的憑證該從哪裡來」——先問誰會連它
> - ★★★★ 機關憑證四條來源（GPKI 體系 / 商業 CA / ACME 免費 CA / 自建 CA）的差異與適用場景
> - ★★★ GPKI 體系裡伺服器憑證、人員憑證、機關憑證的**用途差異**（概念層，不涉類別代碼）
> - ★★★★ 申請流程的五階段骨架，以及每一階段**要準備什麼類型的東西**
> - ★★★★★ 產 CSR 是技術人員唯一完全掌控的一步，私鑰**絕不可**交給任何人
> - ★★★★ 拿憑證時一定要一併拿到**完整憑證鏈**，少了中繼憑證會讓部分裝置驗不過
> - ★★★★ GPKI 體系多半沒有 ACME ⇒ 手動續期，但憑證效期正在縮短，該怎麼制度性因應
> - ★★★ 一張可以直接抄去用的**憑證清冊表格範本**
> - ★★★ 一台對內機關系統從盤點到換憑證完成的全程實戰

---

## 前置知識

- [[090-01-01-guide-PKI-PKI與憑證基礎]]（信任鏈、CA、根憑證的基本概念）
- [[090-01-02-guide-PKI-CSR產生與req設定檔]]（本篇的核心技術動作）
- [[090-01-03-guide-PKI-向CA申請憑證]]（商業 CA 與 ACME 的一般流程）
- [[090-01-04-guide-PKI-CN與SAN設定與瀏覽器相容性]]（SAN 漏網域是最常見的重來原因）
- [[090-01-12-guide-PKI-憑證生命週期管理]]（清冊、監控、續期制度）

會用到 `openssl` 指令；Ubuntu/Debian 與 RHEL 系皆內建，指令相同。

---

## 觀念說明

### ★★★★ 一句話先講完

> [!note] 本篇的核心判斷
> **憑證要從哪裡來，取決於「誰會用瀏覽器或用戶端連這個服務」，
> 而不是取決於這台機器放在哪裡、也不是取決於哪個來源比較便宜或比較好申請。**
>
> 一般民眾會連 ⇒ 必須是**公開信任**的 CA。
> 只有內部同仁會連、且信任派送得到 ⇒ 內部信任鏈可行。
> 跨機關系統介接 ⇒ 通常由**對方機關或主辦機關**指定體系，先問，不要自己決定。

### ★★★ 機關的憑證從哪裡來：四條路

機關手上的伺服器憑證，來源基本上就這四條。四條路可以**並存**，
同一個機關不同服務走不同來源是正常的，不是管理失序。

| 來源 | 是什麼 | 機關裡典型的樣子 |
| --- | --- | --- |
| ★★★★ **政府憑證管理中心（GPKI 體系）** | 政府公開金鑰基礎建設下的憑證管理中心體系，簽發給機關與公務用途 | 對內系統、跨機關介接、需要與公務身分綁定的應用 |
| ★★★★ **TWCA 等商業 CA** | 根憑證已預載於主流瀏覽器／作業系統信任庫的商業憑證機構 | 對外的機關官網、民眾服務系統、線上申辦入口 |
| ★★★ **Let's Encrypt 等 ACME 免費 CA** | 用 ACME 協定自動驗證網域控制權並自動簽發、自動續期 | 對外的資訊型網站、測試站、非機敏的輔助服務 |
| ★★ **自建 CA** | 機關自己架的根 CA／中繼 CA，只在自己派送信任的範圍內有效 | 內部管理介面、監控面板、設備管理頁、機器對機器 |

### ★★★★★ 四條路的完整比較表

這張表是本節的重點，**選型爭議發生時把這張表拿出來對就好**。

| 比較欄位 | GPKI 體系 | TWCA 等商業 CA | ACME 免費 CA | 自建 CA |
| --- | --- | --- | --- | --- |
| **信任範圍** | 政府體系內廣泛受信；一般民眾裝置**不必然**預裝該體系根憑證 | ★★★★ 主流瀏覽器／OS 預載，全球公開信任 | ★★★★ 主流瀏覽器／OS 預載，全球公開信任 | ★ 只在你**主動派送根憑證**的裝置上有效 |
| **適用系統** | 對內公務系統、跨機關介接、與公務身分綁定的應用 | 對外官網、民眾服務、線上申辦 | 對外資訊網站、測試站、輔助服務 | 內部管理介面、監控、設備頁、內部 API |
| **申請流程複雜度** | ★★★★ 高：需機關行政程序、用印、身分審驗 | ★★★ 中：需組織身分文件與網域控制權驗證 | ★ 低：全自動，只驗網域控制權 | ★ 低：自己簽，但要自己承擔 CA 責任 |
| **效期** | 依現行作業規定，通常**明顯長於**公開信任 CA 的上限 | ★★★ 受瀏覽器論壇規範壓縮，逐年縮短 | ★★★ 短（設計上就短，因為靠自動化） | 自訂，但**不建議**簽超長 |
| **自動化可行性** | ★★★★★ 多半**沒有** ACME，實務上是人工續期 | ★★ 部分 CA 提供 ACME 或 API，需確認方案是否支援 | ★★★★★ 天生為自動化設計 | ★★★★ 完全可自動化（自己寫腳本／用內部 CA 工具） |
| **費用性質** | 依主管機關作業規定辦理，多屬公務體系內部程序 | 屬**採購**性質，需編列預算與走採購流程 | 無授權費用，成本在自動化的維運工時 | 無授權費用，成本在 CA 的建置與長期維護 |
| **機關常見用途** | 公文系統、內部入口、跨機關資料交換 | 官網、線上申辦、對民眾的 API | 資訊公開頁、活動網站、非機敏子網域 | 監控面板、備援管理頁、內部微服務 |
| **憑證撤銷** | 依體系規定申請撤銷，需行政程序 | 向 CA 提出撤銷申請 | ACME 指令即可撤銷 | 自己維護 CRL／OCSP（★★ 常被忽略） |
| **失敗代價** | 到期沒續 ⇒ 對內系統全面告警、公文流程停擺 | 到期沒續 ⇒ 民眾看到紅色警告，可能上新聞 | 自動化壞掉才會到期 | 到期或信任沒派送 ⇒ 內部全紅，同仁習慣性略過警告 ★★★★ |

> [!warning] ★★★★ 表格裡「效期」那一列是本篇最重要的張力
> 一邊是 GPKI 體系**沒有 ACME、只能人工續期**，
> 另一邊是整個產業的憑證效期**正在快速縮短**。
> 這兩件事撞在一起，就是機關未來幾年最容易出的憑證事故。
> 詳見〈進階應用〉的〈與自動化的落差〉。

### ★★★★★ 公開信任與內部信任的差別

這是所有選型爭議的根。很多人把「憑證有效」和「瀏覽器不跳警告」當成同一件事，其實不是。

> [!note] 兩個獨立的條件
> 一張憑證讓瀏覽器安心顯示鎖頭，需要**同時**滿足：
>
> 1. **憑證本身有效**：沒過期、網域對得上（SAN 命中）、沒被撤銷、簽章驗得過
> 2. ★★★★★ **驗證者的信任庫裡有這條鏈的根**——這條完全取決於**對方的電腦**，不是你的伺服器
>
> 第 2 點就是「公開信任」的全部意義：
> 公開信任 CA 的根，**已經預先躺在全世界的瀏覽器與作業系統裡**，你什麼都不用做。
> 內部信任鏈的根，**必須由你派送到每一台會連的裝置**——
> 你派不到的裝置（民眾的手機、外部廠商的筆電、別的機關的伺服器），就是驗不過。

判斷「這條路可不可行」的唯一提問：

```text
會連這個服務的裝置，我有沒有辦法把根憑證裝進去？
  有  → 內部信任鏈可行（GPKI 體系或自建 CA）
  沒有 → 只能用公開信任的 CA
```

派送方法見 [[090-01-09-guide-PKI-根憑證派送與信任]]。

### ★★★ GPKI 體系是什麼

GPKI（政府公開金鑰基礎建設）是政府體系自己的一整套 PKI，
和商業 CA 一樣有根 CA、下級（中繼）CA、憑證政策、憑證作業實務基準、撤銷機制。
差別在**信任的來源**：商業 CA 的信任來自瀏覽器廠商的內建，
GPKI 的信任來自**政府體系的規範與根憑證派送**。

> [!note] ★★★ 你需要記住的三件事
> 1. 它是**多層的**：根 CA → 下級 CA → 你的憑證。你拿到的憑證**不是**直接由根簽的，
>    所以**一定會有中繼憑證**要一起裝（見〈階段四〉）。
> 2. 它的**信任要靠派送**：一般民眾的手機不必然裝了這條鏈的根，
>    所以對民眾服務通常不會單用它。
> 3. 它的**申請是行政程序**：需要機關用印、身分審驗、有承辦窗口，
>    ★★★★ 不是技術人員自己在終端機敲幾行就能拿到的東西。

> [!warning] ★★★★★ 體系內的實際名稱、層級數、憑證政策與作業要點
> 各憑證管理中心的**正式名稱、隸屬關係、可申請的憑證種類與應備文件**，
> 一律**依主管機關現行公告與作業要點為準**。
> 本篇不列這些名稱與代碼，因為它們會改，而改了之後照抄手冊的人會送錯件。
> 請向貴機關資訊室的憑證管理窗口索取**現行版本**的作業說明。

### ★★★★ GPKI 體系的憑證類型：用途差異（概念層）

體系裡不是只有「網站憑證」一種。實務上會遇到三大類，**用途完全不同、不可互換**。
以下只講**用途概念**，不寫類別代碼、不寫申請條件。

| 類型 | 綁定的主體 | 回答的問題 | 典型用途 |
| --- | --- | --- | --- |
| ★★★★ **伺服器憑證** | 一個**網域名稱／主機** | 「我連到的這台主機，真的是那個網域嗎？」 | HTTPS、TLS 加密、伺服器身分證明 |
| ★★★★ **人員憑證**（自然人／工商等以個人或組織身分為主體者） | 一個**人**或一個**營利／非營利組織** | 「操作的這個人／這家單位，真的是他嗎？」 | 線上申辦身分驗證、電子簽章、登入公務系統 |
| ★★★ **機關憑證** | 一個**機關**（作為法人主體） | 「送出這份資料的，真的是這個機關嗎？」 | 機關對機關的資料交換簽章、系統介接的身分 |

> [!danger] ★★★★★ 最常見的類型誤用
> **拿人員憑證去裝 HTTPS，或拿伺服器憑證去做人員身分驗證。**
>
> 這兩者的主體、金鑰用途（Key Usage / Extended Key Usage）、
> 憑證內容欄位都不一樣。裝上去可能「看起來」能載入，
> 但瀏覽器會因為 EKU 不含 `TLS Web Server Authentication` 而拒絕，
> 或是驗證流程根本對不上主體。
>
> 申請前把**用途**寫清楚給窗口：
> 「這是給某某網域的 HTTPS 用的伺服器憑證」，不要只說「我要一張憑證」。

檢查一張憑證到底是哪一類，最快的方法是看 EKU：

```bash
openssl x509 -in cert.pem -noout -text | grep -A2 "Extended Key Usage"
```

伺服器憑證預期輸出：

```text
            X509v3 Extended Key Usage:
                TLS Web Server Authentication, TLS Web Client Authentication
```

★★★ 如果這裡出現的是 `E-mail Protection`、`Code Signing`、
或只有 `TLS Web Client Authentication`，那它就**不是**拿來裝 HTTPS 的。

### ★★★ TWCA 等商業 CA 在機關的定位

TWCA（台灣網路認證公司）是在台灣營運的商業憑證機構之一，
其根憑證屬於**公開信任**體系——已預載於主流瀏覽器與作業系統的信任庫。
機關的對外服務常見走這一條。

> [!tip] ★★★ 為什麼對外服務常走商業 CA 而不是免費 ACME
> 不是技術理由，多半是**行政與稽核理由**：
> - 招標文件／履約規格書明列要用「經認證之憑證機構」核發之憑證
> - 需要 OV／EV 等級——憑證裡要載明**機關全名**，而不只是網域
> - 需要有廠商可問責、有客服窗口、有保險條款
> - 上級或稽核單位要求提供憑證申請與核發的紙本佐證
>
> ★★★★ 如果你的專案有以上任何一條，**先確認採購文件怎麼寫**，
> 再決定能不能用免費 CA。這是被退件的常見原因。

> [!note] ★★ DV / OV / EV 的差別，一句話
> - **DV**：只驗你控制這個網域 —— ACME 免費 CA 幾乎都是這一級
> - **OV**：另外驗這個組織真的存在、真的是你 —— 憑證主體會出現機關名稱
> - **EV**：更嚴格的組織審驗 —— 現代瀏覽器已不再給特殊的綠色標示
>
> ★★★ **加密強度三者完全相同**。差別只在「憑證裡宣稱了什麼」與「審驗多嚴」。
> 有人以為 EV 比較安全所以連線比較快、加密比較強，這是錯的。

### ★★★ ACME 免費 CA：什麼情況可用、什麼情況機關不接受

| 情況 | 可不可用 | 原因 |
| --- | --- | --- |
| 對外的資訊公開網站、活動網頁 | ★★★★ 很適合 | 公開信任、全自動、零人工續期 |
| 對外測試站、預備環境 | ★★★★ 很適合 | 短效期反而是優點 |
| 內網主機但走 DNS-01 驗證 | ★★★ 可行 | 見 [[090-01-03-guide-PKI-向CA申請憑證]] 的 DNS-01 一節 |
| 採購文件要求 OV／載明機關名稱 | ★ 不行 | ACME 免費 CA 多為 DV，憑證主體不含組織名稱 |
| 跨機關介接，對方指定 GPKI 體系 | ★ 不行 | 對方的驗證端只認指定體系 |
| 機關資安規範明列憑證來源 | ★ 依規範 | ★★★★ 先查規範再動手，不要事後補救 |
| 主機完全無法對外連線、也無法改 DNS | ★ 不行 | ACME 兩種驗證方式都需要對外可達性 |

> [!warning] ★★★★ 機關拒絕 ACME 的理由通常不是技術
> 常見的三個真實理由：
> 1. **採購或規範文件寫死了**憑證來源或等級
> 2. **稽核要有紙本佐證**，而全自動流程沒有申請單可附
> 3. **承辦習慣**——「以前都這樣申請」
>
> 第 3 個是可以溝通的，前兩個不行。溝通前先把 1、2 排除。

### ★★ 自建 CA 的定位

自建 CA 見 [[090-01-06-guide-PKI-自建根CA]] 與 [[090-01-07-guide-PKI-自建中繼CA與憑證鏈]]。
它不是「省錢的憑證」，它是**另一套要你自己維護一輩子的 PKI**。

> [!tip] ★★★ 什麼情況才該自建
> **全部**符合才自建：
> - 使用者裝置**完全**在你的管理範圍（能派送根憑證）
> - 憑證數量多到人工申請會累死（幾十張以上，或機器對機器頻繁簽發）
> - 有明確的內部用途：內部 API mTLS、監控面板、設備管理頁
> - ★★★★ 你**有能力也有人力**長期維護根金鑰的保管、CRL 發布與交接
>
> 只要「使用者裝置不完全可控」或「沒人接手維護」，就不要自建。
> 少數幾張內部憑證，走 GPKI 體系或商業 CA 通常比自建划算。

---

## 安裝或基礎操作

### ★★★★★ 決策樹：先問「誰會連這個服務」

這一節是本篇最有價值的部分。**每次要生憑證前，把這棵樹跑一遍。**

```text
Q0. 上級規範、採購文件或介接對方，有沒有指定憑證來源或等級？
    有 ─────────────────────────────────────────► 照指定的走，本樹結束
    沒有 ↓

Q1. 誰會用瀏覽器／用戶端連這個服務？

  ├─ (A) 一般民眾、外部廠商、不特定人
  │      ⇒ ★★★★★ 必須是「公開信任」的 CA
  │      ├─ 採購文件要求 OV／載明機關名稱？
  │      │    是 ─► 商業 CA（如 TWCA 等），走採購與組織審驗
  │      │    否 ↓
  │      ├─ 主機能對外連線 或 能改 DNS TXT？
  │      │    能 ─► ★★★★ ACME 免費 CA（自動續期，強烈建議）
  │      │    不能 ─► 商業 CA，人工簽發後手動部署
  │      └─（無論走哪條）★★★ 一律要有到期監控
  │
  ├─ (B) 只有機關內部同仁（裝置由資訊室管理）
  │      ⇒ 內部信任鏈可行
  │      ├─ 這個系統是公務系統，或需與公務身分／跨機關流程銜接？
  │      │    是 ─► ★★★★ GPKI 體系（走機關行政程序申請）
  │      │    否 ↓
  │      ├─ 這類憑證會不會很多張、或機器對機器？
  │      │    會 ─► 自建 CA（可自動化）
  │      │    不會 ─► GPKI 體系 或 商業 CA（少量時人工也還能管）
  │      └─ ★★★★ 前提檢查：根憑證真的派送得到每一台裝置嗎？
  │           派不到（BYOD、外包人員自帶筆電）─► 退回 (A) 用公開信任 CA
  │
  ├─ (C) 別的機關的系統會來介接（機器對機器）
  │      ⇒ ★★★★★ 先問對方的驗證端認哪一條鏈，不要自己決定
  │      ├─ 對方指定體系 ─► 照對方指定
  │      ├─ 對方只驗公開信任 ─► 公開信任 CA
  │      └─ 對方願意匯入你的根 ─► 自建或 GPKI 皆可，但要留書面協議
  │
  └─ (D) 只有機器連機器，且兩端都是你管的
         ⇒ ★★★ 自建 CA 最省事，可完全自動化，效期可短
         （內部 API mTLS、監控 agent、備份節點互連）
```

### ★★★★ 決策樹的四個典型結論

| 服務範例 | 誰會連 | 結論 | 續期方式 |
| --- | --- | --- | --- |
| 機關官網、線上申辦入口 | 一般民眾 | ★★★★ 公開信任 CA（商業或 ACME，視採購文件） | 能 ACME 就 ACME |
| 內部公文系統、員工入口 | 內部同仁 | ★★★★ GPKI 體系 | ★★★★★ 人工，需制度補 |
| 跨機關資料交換介接端點 | 他機關系統 | 依對方指定，通常 GPKI 體系 | 人工，需雙方協調時程 |
| 監控面板、交換器管理頁 | 資訊室自己 | ★★★ 自建 CA | 腳本自動 |

### ★★★★ 三個最常見的誤判

> [!danger] 誤判一：「這台在內網，所以用自建憑證就好」
> 錯的原因：**內網不等於使用者裝置可控**。
> 內網的服務也可能被外包廠商的筆電、同仁的私人手機、
> 或委外維護商連。這些裝置你派不到根憑證。
>
> ★★★★ 正確的提問不是「機器在哪」，是「**連的人的裝置在誰手上**」。

> [!danger] 誤判二：「反正瀏覽器會跳警告，教同仁按繼續就好」
> 這是機關資安最惡質的一種債。
> 一旦同仁**習慣**在憑證警告畫面按「繼續前往」，
> 你就永久失去了偵測中間人攻擊的能力——真的被攻擊時，畫面長得一模一樣。
>
> ★★★★★ 憑證警告必須是**零容忍**的。要嘛把信任派送好，要嘛換公開信任 CA。

> [!danger] 誤判三：「這張憑證還有兩年，不用管」
> 效期長 ≠ 安全。效期長只是**把問題推到未來的自己身上**，
> 而未來的自己很可能已經調職了。
> ★★★★ 憑證一拿到就要**當天**進清冊、當天設監控告警。詳見〈進階應用〉。

### ★★★★ 申請流程的骨架：五個階段

> [!warning] 這是**流程結構**，不是某個特定體系的操作手冊
> 各體系與各 CA 的細節不同。實際的表單、應備文件、送件方式與作業時程，
> **一律依主管機關現行公告與作業要點、或該 CA 的現行說明為準**。
> 這裡只保證一件事：**這五個階段一定都存在，且順序不能顛倒。**

```text
階段一：事前確認   ── 誰是窗口？申請哪一類？涵蓋哪些網域？
階段二：產生 CSR   ── ★★★★★ 技術人員唯一完全掌控的一步
階段三：送件與審驗 ── 行政程序：機關用印、身分驗證
階段四：取得憑證   ── ★★★★ 一定要一併取得完整憑證鏈
階段五：部署與驗證 ── 組鏈、裝上去、實測、進清冊
```

### 階段一：事前確認 ★★★

在敲任何指令之前，先把這五題問清楚。**問不到答案就不要往下走**，
因為階段二產出的 CSR 內容取決於這些答案，答錯就得整個重來。

| 要確認的事 | 該問誰 | 為什麼重要 |
| --- | --- | --- |
| ★★★★ 本機關的**憑證管理窗口**是誰 | 資訊室主管、前任承辦 | 沒有窗口，後面每一步都會卡 |
| ★★★ 這個服務**該申請哪一類**憑證 | 憑證管理窗口 | 類型錯了整份重送（見前述類型差異） |
| ★★★★★ 憑證要涵蓋**哪些網域名稱** | 系統負責人＋自己盤點 | 漏一個 SAN 就要重來（見下） |
| ★★★ 這一類憑證的**現行應備文件與作業時程** | 憑證管理窗口／管理中心 | ★★★★ 決定你要提前多久啟動 |
| ★★★ 憑證**核發後怎麼交付**給你（格式、管道） | 憑證管理窗口 | 影響階段四要準備什麼 |

> [!danger] ★★★★★ 網域盤點是最容易漏、代價最高的一步
> 一張憑證只對它 SAN 裡列出的名稱有效。**漏掉一個，那個名稱就是紅字**，
> 而且 GPKI 體系與商業 CA 都**不能事後追加**——只能重新申請，重跑一次行政程序。
>
> 盤點時務必想到這些**容易漏**的名稱：
> - `www.` 與不帶 `www.` 的裸網域（★★★★ 兩個都要）
> - 舊網址（有沒有還在用的舊網域在 301 導過來？那台也要憑證）
> - 內部 DNS 名稱（同仁習慣用 `系統代號.內網後綴` 連進來）
> - ★★★ 主機的 FQDN（監控與健康檢查常常打的是 FQDN 而不是服務網域）
> - 測試／預備環境的名稱（要不要包進同一張？通常**不要**，分開比較乾淨）
> - 其他機關介接時**寫在他們設定檔裡**的那個名稱 ★★★★

實際盤一遍現況的指令：

```bash
# 這台伺服器上，Nginx 設定了哪些 server_name
grep -rhE "^\s*server_name" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null \
  | tr -s ' ' | sed 's/^ *//; s/;$//' | sort -u
```

預期輸出：

```text
server_name gov-portal.example.gov.tw www.gov-portal.example.gov.tw
server_name portal-old.example.gov.tw
```

```bash
# 目前線上那張憑證，SAN 到底涵蓋了什麼（續期時用來比對，避免漏）
openssl s_client -connect gov-portal.example.gov.tw:443 \
  -servername gov-portal.example.gov.tw </dev/null 2>/dev/null \
  | openssl x509 -noout -ext subjectAltName
```

預期輸出：

```text
X509v3 Subject Alternative Name:
    DNS:gov-portal.example.gov.tw, DNS:www.gov-portal.example.gov.tw
```

★★★★ 把這兩份輸出**對起來**，差集就是你漏掉的名稱。

### 階段二：產生 CSR ★★★★★

> [!note] ★★★★★ 這是整個流程裡，技術人員**唯一完全掌控**的一步
> 前面是行政確認、後面是行政審驗與交付，
> 只有這一步的品質**完全由你決定**，而且它決定了憑證能不能用。
>
> 完整做法見 [[090-01-02-guide-PKI-CSR產生與req設定檔]]，
> SAN 與瀏覽器相容性見 [[090-01-04-guide-PKI-CN與SAN設定與瀏覽器相容性]]。
> 這裡只講**送件情境下**必須注意的事。

> [!danger] ★★★★★ 私鑰絕對不可以交給任何人
> **包括：承辦人、廠商、系統整合商、憑證管理中心、你的主管、你自己 email 給自己。**
>
> - 申請憑證**只需要 CSR**。CSR 裡沒有私鑰，只有公鑰與你填的識別資訊。
> - ★★★★★ 如果任何人跟你要私鑰（`.key`、`.pem` 私鑰檔、`.pfx` 含私鑰的包），
>   **拒絕，並回報**。正常的憑證申請流程不會需要私鑰。
> - ★★★★★ 如果任何人「幫你」產好金鑰對再把私鑰給你，
>   那把私鑰就**已經不可信**了——你無法證明它沒有第二份。
>   這種情況要求重新自己產、重新送 CSR。
> - ★★★★ 更不要把私鑰貼在 email、公文附件、通訊軟體、共用資料夾、
>   或任何雲端硬碟。私鑰只該存在於**它要服務的那台主機上**。
>
> 例外只有一種：機關有**正式的金鑰託管（key escrow）制度**、
> 有加密保管流程與存取紀錄。這種制度存在與否請向資訊室確認；
> 沒有明文制度就當作沒有。

產 CSR 的標準做法（設定檔式，避免互動式漏 SAN）：

```bash
mkdir -p /etc/ssl/csr && cd /etc/ssl/csr
cat > gov-portal.req.txt <<'EOF'
[ req ]
default_bits       = 3072
prompt             = no
default_md         = sha256
distinguished_name = dn
req_extensions     = req_ext

[ dn ]
C  = TW
ST = Taipei
L  = Taipei
O  = Example Government Agency
OU = Information Division
CN = gov-portal.example.gov.tw

[ req_ext ]
subjectAltName = @alt_names

[ alt_names ]
DNS.1 = gov-portal.example.gov.tw
DNS.2 = www.gov-portal.example.gov.tw
DNS.3 = portal-old.example.gov.tw
EOF

openssl req -new -newkey rsa:3072 -nodes \
  -keyout gov-portal.key \
  -out gov-portal.csr \
  -config gov-portal.req.txt

chmod 600 gov-portal.key
```

預期輸出：

```text
Generating a RSA private key
.........................+++++
..................+++++
writing new private key to 'gov-portal.key'
-----
```

★★★★★ **送出前一定要驗**：

```bash
openssl req -in gov-portal.csr -noout -text | \
  grep -A6 "Subject:\|Subject Alternative Name"
```

預期輸出：

```text
        Subject: C = TW, ST = Taipei, L = Taipei, O = Example Government Agency, OU = Information Division, CN = gov-portal.example.gov.tw
        Attributes:
            Requested Extensions:
                X509v3 Subject Alternative Name:
                    DNS:gov-portal.example.gov.tw, DNS:www.gov-portal.example.gov.tw, DNS:portal-old.example.gov.tw
```

> [!warning] ★★★★ 送件前的五項自檢
> 1. `Subject` 的 `O` 是否為**機關的正式全名**（★★★★ 與公文用印的名稱一致，不是簡稱）
> 2. `CN` 是否為主要網域，且**同一個名稱也出現在 SAN 裡**（★★★★ 現代瀏覽器只看 SAN）
> 3. SAN 是否**涵蓋階段一盤點出的每一個名稱**，一個都不能漏
> 4. 金鑰長度與演算法是否符合機關規範（RSA 3072 是穩健的預設）
> 5. ★★★★★ 私鑰檔權限是否 `600`、擁有者是否正確、**是否已備份到安全處**

備份私鑰（同時是**唯一**可以複製它的正當理由）：

```bash
install -d -m 700 /root/cert-backup
cp -p /etc/ssl/csr/gov-portal.key /root/cert-backup/gov-portal.key.$(date +%F)
ls -l /root/cert-backup/
```

預期輸出：

```text
-rw------- 1 root root 2455 Sep  3 10:12 gov-portal.key.2026-09-03
```

★★★ 這份備份要跟著機關的機敏資料保管規定走，不要放共用區。

### 階段三：送件與審驗 ★★★

這一段**是行政程序，不是技術程序**。技術人員的工作是把材料備齊、交給窗口，
然後**追進度**。

> [!note] ★★★ 這個階段通常會需要準備的東西「類型」
> 具體是哪一份文件、幾份、要不要正本，**依主管機關現行公告與作業要點為準**。
> 常見的類型是：
>
> - **需要機關用印的申請書**（由承辦人依現行表單填寫、陳核、用印）
> - **申請單位的身分與職務證明**（證明送件的人有資格代表機關申請）
> - ★★★★ **你產出的 CSR 檔案**（純文字，`-----BEGIN CERTIFICATE REQUEST-----` 開頭）
> - **網域使用權的說明或證明**（證明這個網域確實屬於本機關）
> - **服務用途說明**（這張憑證要裝在哪個系統、對誰服務）
>
> ★★★★★ 這份清單**不包含私鑰**。任何情況下都不包含。

> [!tip] ★★★ 技術人員在這一段該做的三件事
> 1. **把 CSR 用純文字交付**——不要壓縮、不要轉 Word、不要截圖。
>    ★★★ 貼進 Word 會被自動換行與智慧引號破壞，CA 端會解析失敗。
> 2. **留一份送件紀錄**：什麼時候送的、送了哪一份 CSR（存 SHA-256 指紋）、窗口是誰。
> 3. ★★★★ **設一個提醒**追進度。行政程序沒人追就會停在某一格。

記下送出去的 CSR 指紋，日後可比對回來的憑證是不是對應這一份：

```bash
openssl req -in gov-portal.csr -noout -pubkey | openssl sha256
```

預期輸出：

```text
SHA2-256(stdin)= 3f9c1ab8e0d47a2c5b6e8f0139ad72c4e5b81f60c93a7d2e4f8b0c1a6d5e93f27
```

★★★ 把這串連同送件日期寫進清冊的備註欄。

### 階段四：取得憑證與中繼憑證 ★★★★★

> [!danger] ★★★★★ 這一階段最常出事：只拿到自己的憑證，沒拿到中繼憑證
> 憑證核發下來時，你至少要拿到**兩樣東西**：
>
> 1. **你的伺服器憑證**（end-entity certificate，也叫 leaf）
> 2. ★★★★★ **中繼憑證**（intermediate CA certificate，可能不只一張）
>
> 只裝第 1 樣，後果是：
> - **你自己的電腦看起來正常**（因為瀏覽器可能快取過中繼憑證，或會自動抓取）
> - ★★★★ **別人的裝置驗不過**——尤其是手機 App、Java 用戶端、
>   `curl`、`wget`、老舊瀏覽器、其他機關的介接程式
> - 這是最惡劣的一種錯誤：**你測起來是好的，別人是壞的**，而回報進來時你重現不出來
>
> 憑證鏈的原理見 [[090-01-07-guide-PKI-自建中繼CA與憑證鏈]]。

★★★★ 拿到憑證時，一定要問窗口的三句話：

```text
1.「請問除了伺服器憑證，中繼憑證（intermediate CA）要去哪裡下載？」
2.「這條鏈總共有幾層？中繼憑證有幾張？」
3.「有沒有提供已經串好的 fullchain 檔？」
```

拿到檔案後，**先驗再裝**：

```bash
# 這是不是我送的那份 CSR 對應的憑證？（比對公鑰指紋）
openssl x509 -in gov-portal.crt -noout -pubkey | openssl sha256
openssl req  -in gov-portal.csr -noout -pubkey | openssl sha256
```

★★★★ 兩行輸出**必須完全相同**。不同就代表這張憑證不是配你手上這把私鑰的，
裝上去 Nginx 會直接拒絕啟動。

```bash
# 憑證本身的基本資訊
openssl x509 -in gov-portal.crt -noout -subject -issuer -dates
```

預期輸出：

```text
subject=C = TW, O = Example Government Agency, CN = gov-portal.example.gov.tw
issuer=C = TW, O = <簽發它的下級 CA 名稱>, CN = <簽發它的下級 CA 名稱>
notBefore=Sep  3 00:00:00 2026 GMT
notAfter=Sep  3 23:59:59 2027 GMT
```

★★★★ 看 `issuer`：**如果 issuer 不等於 subject，就代表它不是自簽，
那就一定有上層——你必須拿到那一張（或那幾張）中繼憑證。**

組鏈（★★★ 順序是關鍵）：

```bash
# fullchain 的順序：伺服器憑證在最前，中繼由下而上，根憑證不放
cat gov-portal.crt intermediate.crt > gov-portal.fullchain.crt

# 若有兩層中繼（issuer 鏈更深）
# cat gov-portal.crt intermediate2.crt intermediate1.crt > gov-portal.fullchain.crt
```

> [!warning] ★★★★ 根憑證**不要**放進 fullchain
> 放進去不會壞，但會讓每次交握多傳一張沒用的憑證。
> 驗證端本來就必須自己有根憑證才會信任——你傳過去的那張它根本不會採信。

驗證鏈完整（★★★★★ 這一步不做完不要部署）：

```bash
openssl verify -CAfile root.crt -untrusted intermediate.crt gov-portal.crt
```

預期輸出：

```text
gov-portal.crt: OK
```

失敗會長這樣：

```text
CN = gov-portal.example.gov.tw
error 20 at 0 depth lookup: unable to get local issuer certificate
error gov-portal.crt: verification failed
```

★★★★ 出現 `error 20` 就是**中繼憑證缺了或給錯了**，回去跟窗口要。

### 階段五：部署與驗證 ★★★

部署到各服務的完整做法見 [[090-01-10-guide-PKI-憑證部署到各服務]]，
格式轉換（PEM／DER／PFX／JKS）見 [[090-01-11-guide-PKI-憑證格式轉換與檢視工具]]。

> [!tip] ★★★★ 部署後的驗證，一定要從**別台機器**做
> 在伺服器本機用 `curl https://localhost` 測，會因為本機信任庫、
> `/etc/hosts`、或 SNI 沒帶對而**測不出真正的問題**。
> 至少要從另一台主機、以及一台沒進過這個系統的裝置各測一次。

---

## 進階應用

### ★★★★★ 與自動化的落差：GPKI 體系沒有 ACME

這是本篇最需要機關正視的結構性問題。

> [!danger] ★★★★★ 兩股力量正在對撞
> **力量一：憑證效期正在縮短。**
> 公開信任憑證的最長效期，過去十幾年一路從數年壓到一年出頭，
> 而且業界方向明確——**只會更短，不會回頭**。
> 詳見 [[090-01-12-guide-PKI-憑證生命週期管理]] 的〈為什麼手動續期已經不可行〉。
>
> **力量二：GPKI 體系的申請是行政程序，多半沒有 ACME。**
> 這代表每一次續期都要：找窗口 → 產 CSR → 用印送件 → 等審驗 → 取件 → 部署。
> 這個流程**不能自動化**，而且它的耗時**不由你控制**。
>
> ★★★★★ 對撞的結果：**續期的頻率變高，但每次續期的人工成本不變。**
> 三年一次的行政程序，變成一年一次、甚至更頻繁時，
> 沒有制度支撐的機關就會開始漏續，然後在某個週一早上全系統紅字。

> [!warning] ★★★★ 一句要記住的話
> 商業 CA 與 ACME 的世界，靠**自動化**解決效期縮短。
> GPKI 體系的世界，只能靠**制度**解決。
> 沒有制度，就只剩下運氣。

### ★★★★★ 機關該怎麼因應：五件事

沒有 ACME 不代表束手無策。以下五件事，**每一件都不需要 CA 端配合**，
全部可以由資訊室自己做到。

#### 一、建立憑證清冊 ★★★★★

★★★★★ **沒有清冊，其他四件事全部做不到。** 詳見下一節。

#### 二、到期監控與分級告警 ★★★★

清冊只是靜態資料，會過時。**監控是主動的**，直接去連服務、讀真正在線上的那張憑證。

告警要**分級**，而且第一級要**早得離譜**——因為行政程序耗時不由你控制：

| 剩餘天數 | 告警等級 | 該做的事 |
| --- | --- | --- |
| ★★★★ 90 天 | 提醒 | 啟動申請：確認窗口、確認網域清單有沒有變 |
| ★★★★ 60 天 | 注意 | CSR 應該已產出並送件；沒送就要追原因 |
| ★★★★★ 30 天 | 警告 | 送件必須已完成並在審驗中，主管應知情 |
| ★★★★★ 14 天 | 嚴重 | 視為事故前兆，每日追進度，準備應變方案 |
| ★★★★★ 7 天 | 緊急 | 上報主管，啟動應變（見下） |

> [!tip] ★★★ 為什麼第一級要拉到 90 天
> 因為你控制不了行政程序的長度。用印要陳核、承辦可能休假、
> 審驗可能要補件、補件又要再陳核一次。
> ★★★★ 把**你不能控制的部分**用時間緩衝包起來，這是唯一的辦法。
> 具體提前多久最合適，取決於貴機關的行政程序實際耗時——
> **第一次跑完之後把真實天數記下來**，下次照那個數字加一半當緩衝。

一支不依賴清冊、直接掃線上憑證的檢查腳本：

```bash
#!/usr/bin/env bash
# /usr/local/bin/cert-expiry-check.sh
# 讀一份 host:port 清單，回報每個端點的憑證剩餘天數
set -uo pipefail

LIST="${1:-/etc/cert-inventory/endpoints.txt}"
WARN_DAYS="${2:-90}"
now=$(date +%s)
rc=0

printf "%-45s %-12s %-8s %s\n" "端點" "到期日" "剩餘天" "狀態"
printf '%s\n' "--------------------------------------------------------------------------------"

while read -r line; do
  [[ -z "$line" || "$line" =~ ^# ]] && continue
  host="${line%%:*}"; port="${line##*:}"; [[ "$host" == "$port" ]] && port=443

  end=$(echo | openssl s_client -connect "${host}:${port}" -servername "$host" 2>/dev/null \
        | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)

  if [[ -z "$end" ]]; then
    printf "%-45s %-12s %-8s %s\n" "$host:$port" "-" "-" "無法取得（連不上或未啟用 TLS）"
    rc=2; continue
  fi

  end_ts=$(date -d "$end" +%s 2>/dev/null) || { echo "$host 日期解析失敗"; rc=2; continue; }
  days=$(( (end_ts - now) / 86400 ))

  if   (( days < 0 ));           then status="★★★★★ 已過期"; rc=2
  elif (( days <= 7 ));          then status="★★★★★ 緊急";   rc=2
  elif (( days <= 14 ));         then status="★★★★★ 嚴重";   rc=2
  elif (( days <= 30 ));         then status="★★★★ 警告";    rc=1
  elif (( days <= 60 ));         then status="★★★ 注意";     rc=1
  elif (( days <= WARN_DAYS ));  then status="★★ 提醒";      rc=1
  else                                status="正常"
  fi

  printf "%-45s %-12s %-8s %s\n" "$host:$port" "$(date -d "$end" +%F)" "$days" "$status"
done < "$LIST"

exit $rc
```

端點清單：

```bash
cat > /etc/cert-inventory/endpoints.txt <<'EOF'
# 機關憑證端點清單（一行一個 host 或 host:port）
gov-portal.example.gov.tw:443
doc.example.gov.tw:443
api-exchange.example.gov.tw:8443
monitor.internal.example.gov.tw:443
EOF

bash /usr/local/bin/cert-expiry-check.sh
```

預期輸出：

```text
端點                                          到期日       剩餘天  狀態
--------------------------------------------------------------------------------
gov-portal.example.gov.tw:443                 2027-09-03   365      正常
doc.example.gov.tw:443                        2026-10-20   47       ★★★ 注意
api-exchange.example.gov.tw:8443              2026-09-19   16       ★★★★ 警告
monitor.internal.example.gov.tw:443           2026-09-08   5        ★★★★★ 緊急
```

排程（每天早上跑，有問題才寄信）：

```bash
cat > /etc/cron.d/cert-expiry <<'EOF'
MAILTO=isd-cert@example.gov.tw
30 8 * * * root /usr/local/bin/cert-expiry-check.sh || true
EOF
```

★★★ `|| true` 是為了讓非零離開碼不會讓 cron 重試，但輸出仍會寄出。
整合到監控系統的做法見 [[090-01-12-guide-PKI-憑證生命週期管理]]。

#### 三、提前啟動申請，並把「行政耗時」量測下來 ★★★★

> [!tip] ★★★★ 第一次做的人一定要做的事：記錄真實時間
> 在清冊備註欄記四個時間點：
> `CSR 產出日` → `送件日` → `核發日` → `部署完成日`
>
> 跑過一輪之後你就有了**貴機關的真實行政耗時**。
> 這個數字比任何手冊上的天數都準，因為它是你自己機關量出來的。
> ★★★★ 下一次的告警閾值，就設成「真實耗時 × 1.5」。

#### 四、把能改 ACME 的服務改掉 ★★★★

★★★★ **減少人工續期的張數，是最有效的降風險手段。**
每少一張人工憑證，就少一次可能漏掉的機會。

| 服務類型 | 能不能改 ACME | 判斷依據 |
| --- | --- | --- |
| 對外資訊型網站、活動頁 | ★★★★ 可以 | 沒有 OV 要求、沒有體系指定 |
| 對外測試／預備環境 | ★★★★ 可以 | 短效期無妨，自動續期最適合 |
| 內部服務但網域是對外可解析的 | ★★★ 可以（DNS-01） | 不需主機對外可達，只需能改 DNS TXT |
| 對民眾的申辦系統 | ★★ 看採購文件 | 若要求 OV／載明機關名稱則不行 |
| 跨機關介接端點 | ★ 通常不行 | 對方驗證端可能綁定特定體系 |
| 需與公務身分綁定的系統 | ★ 不行 | 用途本身就要求 GPKI 體系 |

> [!warning] ★★★★ 改 ACME 前必做的兩件事
> 1. **查機關的資安規範與採購文件**，確認沒有明列憑證來源限制
> 2. **知會憑證管理窗口**——不要靜悄悄地改。
>    ★★★ 稽核時「這張憑證怎麼來的」答不出來，比憑證過期更麻煩。

ACME 的實際做法見 [[090-01-03-guide-PKI-向CA申請憑證]]。

#### 五、應變方案：真的來不及時怎麼辦 ★★★★

> [!danger] ★★★★★ 先講不能做的
> **不要**為了趕時間，把對民眾的服務換成自簽憑證或內部 CA 憑證。
> 民眾裝置沒有你的根，結果是整片紅色警告，比服務降級更難看，
> 而且會被截圖。
>
> **不要**為了趕時間，把 HTTPS 關掉改回 HTTP。這是資安事件。

真的來不及時，依服務對象決定：

| 服務對象 | 可行的應變 |
| --- | --- |
| ★★★ 只有內部同仁 | 短期用內部 CA 簽一張過渡（★★★ 前提：根憑證已派送），同時繼續跑正式申請 |
| ★★★★ 一般民眾 | 若採購文件允許，改走 ACME 免費 CA **暫時**頂住，正式憑證下來再換回 |
| ★★★★★ 跨機關介接 | ★★★★★ 立刻通知對方機關窗口，協商暫時的例外處理，不要單方面換憑證 |

★★★★ 無論走哪一條，事後都要寫**事件檢討**，並回頭修正告警閾值。

### ★★★★★ 憑證清冊該記什麼

這張表可以直接抄去用。**一個服務一列，不要合併。**

| 欄位 | 說明 | 為什麼要 |
| --- | --- | --- |
| **服務名稱** | 系統的正式名稱（與公文一致） | ★★★ 交接時能對得上 |
| **網域名稱（含全部 SAN）** | 這張憑證涵蓋的**每一個**名稱 | ★★★★★ 續期時照這欄產 CSR，不會漏 |
| **憑證來源 CA** | GPKI 體系／商業 CA／ACME／自建，寫明是哪一個 | ★★★★ 決定續期要走哪條路 |
| **憑證類型** | 伺服器憑證等（★ 用途，不寫代碼） | ★★★ 避免續期時申請錯類型 |
| **申請日／核發日** | 兩個日期都記 | ★★★★ 兩者相減就是真實行政耗時 |
| **到期日** | 憑證的 notAfter | ★★★★★ 監控的依據 |
| **負責人** | 承辦人姓名與分機（★★ 不是「資訊室」這種答案） | ★★★★ 人異動時要更新 |
| **續期方式** | 「人工／走機關行政程序」或「ACME 自動」 | ★★★★ 決定要不要納入人工排程 |
| **中繼憑證位置** | 中繼憑證檔案放在哪、從哪下載 | ★★★★★ 續期時最常找不到的東西 |
| **私鑰位置** | ★★★★ 只寫**路徑**，絕不寫內容 | 交接必要 |
| **部署主機與服務** | 哪台機器、哪個服務（Nginx/Apache/Tomcat…） | ★★★ 一張憑證常裝在多台 |
| **備註** | CSR 公鑰指紋、窗口聯絡方式、上次的坑 | ★★★ 下一個人會感謝你 |

填好的樣子：

| 服務名稱 | 網域（含 SAN） | 來源 CA | 申請日 | 核發日 | 到期日 | 負責人 | 續期方式 | 中繼憑證位置 | 私鑰路徑 | 部署主機/服務 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 機關對外入口 | `gov-portal.example.gov.tw`, `www.gov-portal.example.gov.tw` | 商業 CA | 2026-06-01 | 2026-06-18 | 2027-06-18 | 王小明 #1234 | ★★★★ 人工 | `/etc/ssl/chain/commercial-int.crt` | `/etc/ssl/private/portal.key` | web01 / Nginx |
| 內部公文系統 | `doc.example.gov.tw` | GPKI 體系 | 2026-05-10 | 2026-06-02 | 2027-05-31 | 李小華 #1250 | ★★★★★ 人工（行政） | `/etc/ssl/chain/gpki-int.crt` | `/etc/ssl/private/doc.key` | app02 / Tomcat |
| 資訊公開頁 | `open.example.gov.tw` | ACME 免費 CA | — | 2026-08-20 | 2026-11-18 | 王小明 #1234 | ★★★★ 自動 | fullchain 自帶 | `/etc/letsencrypt/live/open…/privkey.pem` | web01 / Nginx |
| 監控面板 | `monitor.internal.example.gov.tw` | 自建 CA | — | 2026-07-01 | 2027-07-01 | 李小華 #1250 | ★★★ 腳本自動 | `/etc/ssl/chain/internal-int.crt` | `/etc/ssl/private/monitor.key` | mon01 / Nginx |

> [!tip] ★★★ 清冊要放哪裡、用什麼格式
> - 機關的表單範本目錄 `_表單範本/` 底下已有多種維運表單的 Word 檔，
>   憑證清冊如果要走**正式表單**（要簽核、要存查），就照那個目錄的慣例做一份 Word 版。
> - ★★★★ 但**同時**要有一份**機器可讀**的版本（CSV 或 YAML），
>   讓監控腳本能直接吃。只有 Word 版的清冊，監控就永遠是人工的。
> - 兩份要有**單一事實來源**：建議以 CSV 為主，Word 版由 CSV 產生或定期同步。

機器可讀版：

```bash
cat > /etc/cert-inventory/inventory.csv <<'EOF'
service,domains,ca_source,applied,issued,expires,owner,renew_mode,chain_path,key_path,host_service
機關對外入口,"gov-portal.example.gov.tw;www.gov-portal.example.gov.tw",商業CA,2026-06-01,2026-06-18,2027-06-18,王小明#1234,manual,/etc/ssl/chain/commercial-int.crt,/etc/ssl/private/portal.key,web01/nginx
內部公文系統,"doc.example.gov.tw",GPKI,2026-05-10,2026-06-02,2027-05-31,李小華#1250,manual,/etc/ssl/chain/gpki-int.crt,/etc/ssl/private/doc.key,app02/tomcat
資訊公開頁,"open.example.gov.tw",ACME,,2026-08-20,2026-11-18,王小明#1234,auto,,/etc/letsencrypt/live/open/privkey.pem,web01/nginx
EOF
chmod 640 /etc/cert-inventory/inventory.csv
```

★★★★ 從清冊挑出**人工續期且 120 天內到期**的項目：

```bash
awk -F, 'NR>1 && $8=="manual" { print $6"\t"$1"\t"$7 }' /etc/cert-inventory/inventory.csv \
  | sort | while IFS=$'\t' read -r exp svc owner; do
      d=$(( ( $(date -d "$exp" +%s) - $(date +%s) ) / 86400 ))
      (( d <= 120 )) && printf "%s  剩 %s 天  %s（%s）\n" "$exp" "$d" "$svc" "$owner"
    done
```

預期輸出：

```text
2027-05-31  剩 270 天  內部公文系統（李小華#1250）
```

（此例都還很遠，實際跑時會列出該啟動申請的項目。）

### ★★★ 分層管理策略

不要試圖讓所有憑證都走同一條路。**分層管理**比統一管理務實：

| 層 | 服務性質 | 來源 | 管理密度 |
| --- | --- | --- | --- |
| ★★★★★ 第一層 | 對民眾、對外機關、公文流程 | 公開信任 CA 或 GPKI | 進清冊、90 天告警、有應變方案、有主管知情 |
| ★★★ 第二層 | 對內同仁使用的一般系統 | GPKI 或商業 CA | 進清冊、60 天告警 |
| ★★ 第三層 | 純內部管理介面、機器對機器 | 自建 CA | 進清冊、腳本自動續期、30 天告警 |

★★★★ 分層的意義是：**把有限的人工注意力，放在漏掉會出事的那一層。**

### ★★★ 交接與人員異動

> [!danger] ★★★★★ 機關憑證管理最大的單點故障是「人」
> 承辦調職、外包合約到期、原本知道窗口是誰的人退休——
> 這些比技術問題更常造成憑證過期。
>
> 交接時**必須**移交的四樣：
> 1. ★★★★★ **清冊本身**（含每一列的負責人已更新）
> 2. ★★★★ **憑證管理窗口是誰**、怎麼聯絡
> 3. ★★★★★ **私鑰的存放位置與存取方式**（★ 不是把私鑰印出來給人）
> 4. ★★★ **上一次申請的實際耗時與踩到的坑**

---

## 完整實戰範例

**情境**：機關內部公文系統 `doc.example.gov.tw`，跑在 `app02` 上的 Nginx，
憑證由 GPKI 體系簽發，剩 78 天到期。承辦人剛接手，前任沒留清冊。
從零開始把這張憑證換掉，並把制度補上。

> [!warning] 行政程序的部分寫「要準備什麼、要找誰」
> 步驟 3 是行政程序，本篇不寫表單編號與天數。
> 實際應備文件與時程**依主管機關現行公告與作業要點為準**。
> 其餘每一步都是可以照著敲的指令。

### 步驟 0：盤點現況 ★★★★

先搞清楚現在線上到底是什麼。

```bash
# 0-1 線上這張憑證的完整資訊
echo | openssl s_client -connect doc.example.gov.tw:443 \
  -servername doc.example.gov.tw 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
```

預期輸出：

```text
subject=C = TW, O = Example Government Agency, CN = doc.example.gov.tw
issuer=C = TW, O = <上層 CA 名稱>, CN = <上層 CA 名稱>
notBefore=Nov 20 00:00:00 2025 GMT
notAfter=Nov 20 23:59:59 2026 GMT
X509v3 Subject Alternative Name:
    DNS:doc.example.gov.tw
```

```bash
# 0-2 鏈完不完整？（★★★★ 這一步常常就發現舊憑證其實也裝錯了）
echo | openssl s_client -connect doc.example.gov.tw:443 \
  -servername doc.example.gov.tw -showcerts 2>/dev/null \
  | grep -c "BEGIN CERTIFICATE"
```

預期輸出：

```text
2
```

★★★★ `1` 代表伺服器只送了自己那張，**中繼憑證沒裝**——這是既有的隱患，
這次換憑證要一併修掉。`2` 以上代表有送中繼。

```bash
# 0-3 這台機器上，Nginx 設定用了哪些名稱與哪些憑證檔
grep -rhE "server_name|ssl_certificate" /etc/nginx/sites-enabled/ | sed 's/^\s*//'
```

預期輸出：

```text
server_name doc.example.gov.tw;
ssl_certificate     /etc/ssl/certs/doc.crt;
ssl_certificate_key /etc/ssl/private/doc.key;
```

★★★★ 注意這裡用的是 `doc.crt` 而不是 fullchain——搭配 0-2 的結果，
確認舊部署漏了中繼憑證。

```bash
# 0-4 同仁實際上是用哪些名稱連進來？問系統負責人 + 看存取紀錄
awk '{print $1}' /var/log/nginx/access.log | head -1 >/dev/null   # 佔位，實務看 Host 欄
grep -oP 'Host: \K[^\r]+' /var/log/nginx/access.log 2>/dev/null | sort | uniq -c | sort -rn | head
```

（★★★ 若 log format 沒記 Host，就直接問系統負責人與各單位。）

假設盤點結果是：同仁除了 `doc.example.gov.tw`，還有人用內網名稱
`doc.internal.example.gov.tw` 連。**這個名稱舊憑證沒有涵蓋**，
所以那些人一直在按「繼續前往」。★★★★★ 這次要一併加進 SAN。

### 步驟 1：決策 ★★★

跑一遍決策樹：

```text
Q0. 有沒有指定來源？ → 這是公文系統，機關規範指定走 GPKI 體系  → 照指定的走
```

結論：**續申請 GPKI 體系的伺服器憑證，SAN 要包含兩個名稱。**

★★★ 同時記下：`doc.internal.example.gov.tw` 是內網名稱，
確認 GPKI 體系**是否受理**這種內部名稱——這一題要問窗口，
如果不受理，就要改用其他方案（例如內網名稱另外由自建 CA 簽）。
**在階段一問清楚，不要送件後才知道。**

### 步驟 2：產生 CSR ★★★★★

```bash
install -d -m 700 /etc/ssl/csr
cd /etc/ssl/csr

cat > doc.req.txt <<'EOF'
[ req ]
default_bits       = 3072
prompt             = no
default_md         = sha256
distinguished_name = dn
req_extensions     = req_ext

[ dn ]
C  = TW
ST = Taipei
L  = Taipei
O  = Example Government Agency
OU = Information Division
CN = doc.example.gov.tw

[ req_ext ]
subjectAltName = @alt_names

[ alt_names ]
DNS.1 = doc.example.gov.tw
DNS.2 = doc.internal.example.gov.tw
EOF

openssl req -new -newkey rsa:3072 -nodes \
  -keyout doc-2026.key -out doc-2026.csr -config doc.req.txt

chmod 600 doc-2026.key
```

預期輸出：

```text
Generating a RSA private key
....................+++++
...............+++++
writing new private key to 'doc-2026.key'
-----
```

> [!tip] ★★★ 為什麼檔名帶年份
> 續期時新舊憑證會**同時存在一段時間**。
> 用 `doc-2026.key` 這種命名，換上去出問題時可以立刻切回舊的，
> 而不會因為覆蓋了 `doc.key` 而無路可退。

★★★★★ 送件前驗：

```bash
openssl req -in doc-2026.csr -noout -verify
openssl req -in doc-2026.csr -noout -subject -reqopt no_pubkey -text | \
  grep -A4 "Subject:\|Subject Alternative Name"
```

預期輸出：

```text
Certificate request self-signature verify OK
subject=C = TW, ST = Taipei, L = Taipei, O = Example Government Agency, OU = Information Division, CN = doc.example.gov.tw
                X509v3 Subject Alternative Name:
                    DNS:doc.example.gov.tw, DNS:doc.internal.example.gov.tw
```

記下公鑰指紋與備份私鑰：

```bash
openssl req -in doc-2026.csr -noout -pubkey | openssl sha256 | tee /root/cert-backup/doc-2026.csr.fp
install -d -m 700 /root/cert-backup
cp -p doc-2026.key /root/cert-backup/
```

預期輸出：

```text
SHA2-256(stdin)= a71f3c9e08b6d245ef1a7c3d90b284e6f5c07a1d3b8e926f04c5a71e3d8b96f2
```

### 步驟 3：送件與審驗（行政程序）★★★

> [!note] ★★★★ 這一步你**不敲指令**，你準備材料與找人
>
> **要找誰**：貴機關資訊室的**憑證管理窗口**。
> 不知道是誰，就問資訊室主管或前任承辦；再不行就從機關的公文系統
> 查上一次申請憑證的簽辦紀錄，那份公文上會有承辦人。
>
> **要準備什麼類型的東西**（★★★★★ 實際清單依現行公告與作業要點為準）：
> - 需要**機關用印的申請書**（依現行表單填寫、陳核、用印）
> - 申請人的**身分與職務證明**
> - ★★★★ 你剛產出的 **`doc-2026.csr`**，以**純文字**交付
> - **網域使用權**的相關說明
> - **用途說明**：這張憑證要裝在 `app02` 的內部公文系統，供機關同仁使用
>
> **★★★★★ 不要交付的東西**：`doc-2026.key`。任何情況、任何人要，都不給。
>
> **要問清楚的三件事**：
> 1. 這次的**應備文件現行版本**是哪一份、要幾份
> 2. ★★★★★ 送件後**大約多久**會核發（記下來，這是你未來的告警基準）
> 3. ★★★★★ 核發時**中繼憑證**要去哪裡拿

CSR 的純文字交付，用這個方式確認沒被破壞：

```bash
cat doc-2026.csr
```

預期輸出（開頭與結尾必須完全長這樣）：

```text
-----BEGIN CERTIFICATE REQUEST-----
MIIC3TCCAcUCAQAwgZcxCzAJBgNVBAYTAlRXMQ8wDQYDVQQIDAZUYWlwZWkxDzAN
... 中略 ...
5nJ2fQhTt9wq0Yc7mR4LxK1vHqZ0dA==
-----END CERTIFICATE REQUEST-----
```

★★★ 送出去之後，把送件日寫進清冊，並設一個「一週後追進度」的提醒。

### 步驟 4：取得憑證與中繼憑證 ★★★★★

假設核發後拿到 `doc-2026.crt`，並依窗口指示下載到中繼憑證 `gpki-int.crt`
與根憑證 `gpki-root.crt`。

```bash
cd /etc/ssl/csr
ls -l doc-2026.crt gpki-int.crt gpki-root.crt
```

預期輸出：

```text
-rw-r--r-- 1 root root 1854 Sep  3 11:02 doc-2026.crt
-rw-r--r-- 1 root root 1621 Sep  3 11:02 gpki-int.crt
-rw-r--r-- 1 root root 1428 Sep  3 11:02 gpki-root.crt
```

**4-1 確認憑證配得上私鑰**（★★★★★ 最重要的一項檢查）：

```bash
openssl x509 -in doc-2026.crt   -noout -pubkey | openssl sha256
openssl pkey -in doc-2026.key   -pubout        | openssl sha256
```

預期輸出（兩行必須一模一樣）：

```text
SHA2-256(stdin)= a71f3c9e08b6d245ef1a7c3d90b284e6f5c07a1d3b8e926f04c5a71e3d8b96f2
SHA2-256(stdin)= a71f3c9e08b6d245ef1a7c3d90b284e6f5c07a1d3b8e926f04c5a71e3d8b96f2
```

**4-2 確認 SAN 真的都在裡面**（★★★★ CA 有可能沒照單全收）：

```bash
openssl x509 -in doc-2026.crt -noout -ext subjectAltName
```

預期輸出：

```text
X509v3 Subject Alternative Name:
    DNS:doc.example.gov.tw, DNS:doc.internal.example.gov.tw
```

★★★★★ 如果內網名稱**不見了**，代表 CA 沒受理那個名稱。
現在發現還來得及規劃替代方案；部署後才發現就是一次事故。

**4-3 確認 EKU 是伺服器憑證**：

```bash
openssl x509 -in doc-2026.crt -noout -ext extendedKeyUsage
```

預期輸出：

```text
X509v3 Extended Key Usage:
    TLS Web Server Authentication, TLS Web Client Authentication
```

**4-4 驗證鏈完整** ★★★★★：

```bash
openssl verify -CAfile gpki-root.crt -untrusted gpki-int.crt doc-2026.crt
```

預期輸出：

```text
doc-2026.crt: OK
```

**4-5 確認中繼憑證真的是這張憑證的簽發者**（避免拿錯中繼）：

```bash
openssl x509 -in doc-2026.crt -noout -issuer
openssl x509 -in gpki-int.crt -noout -subject
```

★★★★ 上一行的 `issuer` 必須等於下一行的 `subject`。不相等就是拿錯中繼憑證了。

### 步驟 5：組鏈 ★★★★

```bash
cat doc-2026.crt gpki-int.crt > doc-2026.fullchain.crt

# 確認裡面剛好兩張，順序是 leaf 在前
grep -c "BEGIN CERTIFICATE" doc-2026.fullchain.crt
openssl crl2pkcs7 -nocrl -certfile doc-2026.fullchain.crt \
  | openssl pkcs7 -print_certs -noout
```

預期輸出：

```text
2
subject=C = TW, O = Example Government Agency, CN = doc.example.gov.tw
issuer=C = TW, O = <上層 CA 名稱>, CN = <上層 CA 名稱>

subject=C = TW, O = <上層 CA 名稱>, CN = <上層 CA 名稱>
issuer=C = TW, O = <根 CA 名稱>, CN = <根 CA 名稱>
```

★★★★ 讀法：**第一張的 issuer 等於第二張的 subject**，鏈就是接上的。

### 步驟 6：部署 ★★★

```bash
# 6-1 先備份現況（★★★★ 可回退是換憑證的基本要求）
install -d -m 700 /root/cert-backup/$(date +%F)
cp -p /etc/ssl/certs/doc.crt /etc/ssl/private/doc.key \
      /root/cert-backup/$(date +%F)/ 2>/dev/null
cp -p /etc/nginx/sites-enabled/doc.conf /root/cert-backup/$(date +%F)/

# 6-2 放上新檔
install -m 644 -o root -g root doc-2026.fullchain.crt /etc/ssl/certs/doc-2026.fullchain.crt
install -m 600 -o root -g root doc-2026.key           /etc/ssl/private/doc-2026.key
```

**6-3 改 Nginx 設定**（★★★★ 指向 fullchain，不是單張憑證）：

```nginx
server {
    listen 443 ssl;
    http2 on;
    server_name doc.example.gov.tw doc.internal.example.gov.tw;

    # ★★★★ 必須是 fullchain，只放 leaf 會讓部分用戶端驗不過
    ssl_certificate     /etc/ssl/certs/doc-2026.fullchain.crt;
    ssl_certificate_key /etc/ssl/private/doc-2026.key;

    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;

    # ...其餘設定不動...
}
```

★★★ 注意 `server_name` 也要一併加上新的內網名稱，否則 SAN 有、但 Nginx 不收。

```bash
# 6-4 語法檢查（★★★★★ 沒過就不要 reload）
nginx -t
```

預期輸出：

```text
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

```bash
# 6-5 平滑套用（reload 不中斷既有連線）
systemctl reload nginx
systemctl is-active nginx
```

預期輸出：

```text
active
```

其他服務（Apache／Tomcat／Java keystore）的做法見
[[090-01-10-guide-PKI-憑證部署到各服務]]；
需要轉成 PFX 或 JKS 時見 [[090-01-11-guide-PKI-憑證格式轉換與檢視工具]]。

### 步驟 7：部署後驗證 ★★★★★

> [!danger] ★★★★★ 從**別台機器**驗，不要在 app02 上驗
> 在本機驗會被本機信任庫與 `/etc/hosts` 誤導，測不出真正的問題。

```bash
# 7-1 從另一台主機：憑證換上去了嗎？
echo | openssl s_client -connect doc.example.gov.tw:443 \
  -servername doc.example.gov.tw 2>/dev/null \
  | openssl x509 -noout -dates -ext subjectAltName
```

預期輸出：

```text
notBefore=Sep  3 00:00:00 2026 GMT
notAfter=Sep  3 23:59:59 2027 GMT
X509v3 Subject Alternative Name:
    DNS:doc.example.gov.tw, DNS:doc.internal.example.gov.tw
```

```bash
# 7-2 ★★★★★ 鏈有沒有真的送出去（這是本次要修掉的舊隱患）
echo | openssl s_client -connect doc.example.gov.tw:443 \
  -servername doc.example.gov.tw -showcerts 2>/dev/null \
  | grep -c "BEGIN CERTIFICATE"
```

預期輸出：

```text
2
```

★★★★ 從 `1` 變成 `2`，代表中繼憑證這次有送出去了。

```bash
# 7-3 完整驗證（模擬一台裝了根憑證的用戶端）
echo | openssl s_client -connect doc.example.gov.tw:443 \
  -servername doc.example.gov.tw -CAfile /etc/ssl/csr/gpki-root.crt 2>/dev/null \
  | grep -E "Verify return code|Verification"
```

預期輸出：

```text
    Verification: OK
    Verify return code: 0 (ok)
```

```bash
# 7-4 內網名稱也要測（★★★★ 最容易忘記測的一個）
echo | openssl s_client -connect doc.internal.example.gov.tw:443 \
  -servername doc.internal.example.gov.tw -CAfile /etc/ssl/csr/gpki-root.crt 2>/dev/null \
  | grep -E "Verify return code"
```

預期輸出：

```text
    Verify return code: 0 (ok)
```

```bash
# 7-5 用 curl 模擬非瀏覽器用戶端（★★★★ 這種最容易因為缺鏈而失敗）
curl -sS -o /dev/null -w "HTTP %{http_code}\n" \
  --cacert /etc/ssl/csr/gpki-root.crt https://doc.example.gov.tw/
```

預期輸出：

```text
HTTP 200
```

★★★★ 如果這裡出現 `curl: (60) SSL certificate problem: unable to get local issuer certificate`，
就是鏈還是不完整，回步驟 5 重組。

**7-6 用真實裝置測一輪**（★★★ 指令測不出的部分）：

| 測試裝置 | 為什麼要測 |
| --- | --- |
| ★★★★ 一台**沒進過**這系統的公用電腦 | 排除快取造成的假象 |
| ★★★★ 一支手機（機關派發或同仁自用） | 行動裝置對缺鏈最不寬容 |
| ★★★ 一個跨機關介接的呼叫端（若有） | 對方的驗證庫可能不同 |

### 步驟 8：更新清冊與監控 ★★★★★

```bash
# 8-1 進清冊
cat >> /etc/cert-inventory/inventory.csv <<'EOF'
內部公文系統,"doc.example.gov.tw;doc.internal.example.gov.tw",GPKI,2026-06-17,2026-09-03,2027-09-03,李小華#1250,manual,/etc/ssl/csr/gpki-int.crt,/etc/ssl/private/doc-2026.key,app02/nginx
EOF

# 8-2 加進監控端點
printf 'doc.example.gov.tw:443\ndoc.internal.example.gov.tw:443\n' \
  >> /etc/cert-inventory/endpoints.txt

# 8-3 立刻跑一次確認監控看得到
bash /usr/local/bin/cert-expiry-check.sh
```

預期輸出（節錄）：

```text
doc.example.gov.tw:443                        2027-09-03   365      正常
doc.internal.example.gov.tw:443               2027-09-03   365      正常
```

★★★★★ **這次量到的行政耗時**：申請日 `2026-06-17` → 核發日 `2026-09-03`。
把這個真實數字寫進清冊備註，並據此把下次的第一級告警提前。

### 步驟 9：舊憑證與舊私鑰的處置 ★★★★

> [!warning] ★★★ 觀察期過了才刪
> 換完**不要立刻刪舊檔**。留一到兩週，確認沒有任何用戶端回報問題再處理。
> 期間出事可以立刻改回舊路徑然後 `nginx -t && systemctl reload nginx`。

觀察期過後：

```bash
# 9-1 確認線上跑的確實是新憑證
echo | openssl s_client -connect doc.example.gov.tw:443 \
  -servername doc.example.gov.tw 2>/dev/null \
  | openssl x509 -noout -enddate
```

預期輸出：

```text
notAfter=Sep  3 23:59:59 2027 GMT
```

```bash
# 9-2 舊私鑰安全刪除（★★★★ 不要只用 rm）
shred -u -n 3 /etc/ssl/private/doc.key
ls /etc/ssl/private/doc.key
```

預期輸出：

```text
ls: cannot access '/etc/ssl/private/doc.key': No such file or directory
```

★★★ 備份區的舊私鑰依機關的機敏資料保存規定處理，不要一律刪、也不要一律留。

**9-3 舊憑證要不要撤銷？**

| 情況 | 要不要申請撤銷 |
| --- | --- |
| 正常到期換新，舊私鑰從未外洩 | ★ 通常不需要，讓它自然過期即可 |
| ★★★★★ 私鑰曾外洩、或曾交給第三方 | **立刻申請撤銷**，並依機關規定通報 |
| ★★★★ 主機報廢／被入侵 | 申請撤銷 |
| ★★★ 機關名稱或網域變更 | 依窗口建議辦理 |

★★★★ 撤銷同樣是**行政程序**，要走窗口，流程與應備文件依現行作業要點為準。
撤銷的一般概念見 [[090-01-12-guide-PKI-憑證生命週期管理]]。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 自己電腦看正常，同仁手機／App 說「憑證不受信任」 | **中繼憑證沒裝**，伺服器只送了 leaf；瀏覽器會自己補抓，行動裝置與 App 不會 | `openssl s_client -showcerts` 數 `BEGIN CERTIFICATE` 若為 1，改用 fullchain 重新部署 |
| ★★★★ `curl: (60) SSL certificate problem: unable to get local issuer certificate` | 同上（缺鏈），或用戶端沒有該體系的根憑證 | 先確認伺服器送了完整鏈；仍失敗則是用戶端缺根，見 [[090-01-09-guide-PKI-根憑證派送與信任]] |
| ★★★★ `openssl verify` 回 `error 20 ... unable to get local issuer certificate` | 手上的中繼憑證缺了、或拿錯了不同的中繼 | 比對 leaf 的 `issuer` 與中繼的 `subject` 是否相同；不同就跟窗口重新索取 |
| ★★★★★ Nginx 啟動失敗 `SSL_CTX_use_PrivateKey_file(... ) failed ... key values mismatch` | 憑證與私鑰不是同一對（拿到別張憑證、或私鑰被覆蓋） | 比對 `openssl x509 -pubkey \| sha256` 與 `openssl pkey -pubout \| sha256`，不同就是配錯 |
| ★★★★★ 憑證核發回來，才發現漏了一個網域 | 階段一網域盤點沒做完整；SAN **無法事後追加** | 只能重新產 CSR、重跑行政程序。★★★★ 預防：盤點時對照 `server_name` 與線上憑證 SAN 的差集 |
| ★★★★ CSR 送出後被退件，說「資訊填錯」 | `O` 用了機關簡稱而非正式全名，或 `CN` 拼錯 | 依機關正式全名重產 CSR。★★★ 送件前拿去跟公文用印的名稱逐字對 |
| ★★★★★ 私鑰遺失（機器重灌、誤刪、沒備份） | 沒有把私鑰納入備份流程 | 憑證**作廢無用**，只能重新產金鑰、重產 CSR、重跑整個申請。★★★★★ 預防：產出當天就備份到安全處 |
| ★★★★★ 憑證過期前兩週才發現，行政程序來不及 | 沒有清冊、沒有告警，或告警閾值設太短（如 30 天） | 立刻走〈應變方案〉；事後把第一級告警拉到 90 天以上 |
| ★★★★ 有人（承辦或廠商）要求提供私鑰檔或 `.pfx` | 對申請流程的誤解，或社交工程 | ★★★★★ 拒絕並回報。申請只需要 CSR；若對方堅持，請他出示機關的金鑰託管制度依據 |
| ★★★★ 部署後某些舊裝置／老舊 Java 用戶端仍不信任 | 該裝置的信任庫沒有這條鏈的根，或裝置太舊不支援目前的簽章演算法 | 內部裝置：派送根憑證；外部裝置：改用公開信任 CA。★★★ 老舊裝置的相容性要在選型時就評估 |
| ★★★ 憑證裝上去了，但瀏覽器顯示網域不符 `NET::ERR_CERT_COMMON_NAME_INVALID` | 使用者用的名稱不在 SAN 裡（常見：內網名稱、裸網域 vs `www.`） | `openssl x509 -ext subjectAltName` 比對實際使用的名稱；缺就要重新申請 |
| ★★★★ 把人員憑證拿去裝 HTTPS，服務起不來或瀏覽器拒絕 | 憑證類型／EKU 不符，人員憑證沒有 `TLS Web Server Authentication` | 檢查 `openssl x509 -ext extendedKeyUsage`；重新申請**伺服器憑證** |
| ★★★ CSR 貼進 Word 或 email 後 CA 端解析失敗 | 智慧引號、自動換行、多餘空白破壞了 Base64 | ★★★ 一律以純文字檔（`.csr`）附件交付，不要貼在信件本文或文件裡 |
| ★★★ 換完憑證後監控還在報舊的到期日 | 監控讀的是清冊或本機檔案，不是線上端點 | 監控改成直接連 `host:port` 讀憑證（見〈到期監控〉腳本），清冊只當備查 |
| ★★★★ 承辦調職後沒人知道憑證怎麼申請、窗口是誰 | 交接沒有涵蓋憑證管理 | 把清冊、窗口、私鑰位置、真實行政耗時列為必交接項目 |
| ★★★ 同一張憑證裝在多台，只換了一台 | 清冊沒記「部署主機與服務」欄位 | 清冊補上該欄；換憑證時逐台驗證，不要只驗負載平衡後面的其中一台 |

### ★★★★ 排查順序

憑證有問題時，照這個順序查，不要跳：

```text
1. 憑證本身有效嗎？
   openssl x509 -in cert.pem -noout -dates
   → 過期了就是過期了，其他都不用查

2. 名稱對得上嗎？
   openssl x509 -in cert.pem -noout -ext subjectAltName
   → 使用者輸入的名稱有沒有在裡面

3. 憑證配得上私鑰嗎？
   openssl x509 -in cert.pem -noout -pubkey | openssl sha256
   openssl pkey  -in key.pem  -pubout       | openssl sha256
   → 兩行必須相同

4. ★★★★★ 伺服器有送完整鏈嗎？（從別台機器）
   echo | openssl s_client -connect host:443 -servername host -showcerts 2>/dev/null \
     | grep -c "BEGIN CERTIFICATE"
   → 只有 1 就是缺中繼

5. 用戶端有這條鏈的根嗎？
   echo | openssl s_client -connect host:443 -servername host -CAfile root.crt
   → Verify return code: 0 才算過

6. 是不是憑證類型／EKU 不對？
   openssl x509 -in cert.pem -noout -ext extendedKeyUsage
   → 必須含 TLS Web Server Authentication
```

更完整的排查見 [[090-01-13-guide-PKI-憑證常見問題排查]]。

---

## 安全性注意事項

> [!danger] ★★★★★ 私鑰的六條紀律
> 1. 私鑰**只在它要服務的那台主機上產生**，不由別人代產
> 2. 私鑰**不交付任何人**——承辦、廠商、CA、主管、上級，都不給
> 3. 私鑰檔權限固定 `600`，擁有者 `root`（或服務專用帳號）
> 4. 私鑰**不進 git、不進共用資料夾、不進 email、不進通訊軟體**
> 5. 私鑰的備份存於**符合機關機敏資料保管規定**的位置，並有存取紀錄
> 6. ★★★★★ 私鑰一旦有外洩之虞，**立刻申請撤銷憑證**並依機關規定通報，
>    不要抱著「應該沒人拿到」的僥倖

> [!warning] ★★★★ 憑證警告零容忍
> 任何讓同仁「按繼續前往」才進得去的內部系統，都是**長期資安債**。
> 它訓練使用者忽略瀏覽器唯一的中間人攻擊警訊。
> 解法只有兩個：把根憑證派送好，或換成公開信任的 CA。
> **教同仁怎麼按過去，不是解法。**

> [!warning] ★★★★ 不要用「憑證來源」代替其他安全控制
> 一張 GPKI 體系或 OV 憑證，只證明了「這台主機是這個網域、屬於這個機關」。
> 它**不會**幫你擋 SQL Injection、不會修補弱點、不會取代 WAF、
> 不會讓過期的作業系統變安全。
> ★★★ 稽核時把「已使用政府憑證」當成資安成果來寫，是很常見的錯位。

> [!tip] ★★★ 金鑰演算法與長度
> - RSA 至少 2048 位元；★★★ 新申請建議 3072（在效能與強度間平衡）
> - ECDSA P-256 更快、憑證更小，但★★★ **先確認 CA 與所有用戶端都支援**，
>   機關環境常有老舊 Java 或設備不支援 EC
> - 簽章雜湊必須 SHA-256 以上，SHA-1 早已不可用

> [!warning] ★★★ 清冊本身是機敏資訊
> 憑證清冊記載了機關所有對外服務的網域、主機、私鑰路徑與負責人。
> ★★★★ 它**不該**放在人人可讀的共用槽。權限比照系統清冊管理，
> 並確保**私鑰路徑寫的是路徑，不是內容**。

> [!warning] ★★★ 跨機關介接時不要單方面換憑證
> 對方的驗證端可能釘選（pin）了你的憑證或中繼。
> ★★★★★ 換憑證前**先通知對方窗口並約定時間**，換完再一起驗證。
> 沒通知就換，斷的是兩個機關之間的資料交換。

> [!tip] ★★ 稽核佐證要留什麼
> - 申請與核發的**行政紀錄**（公文、簽核）
> - CSR 的**公鑰指紋**與產出日期
> - 部署後的**驗證輸出**（`Verify return code: 0`）截存
> - 清冊的**版本與更新紀錄**
>
> ★★★ 這些留下來，稽核問「這張憑證怎麼來的」時你答得出來。

---

## 速查表

### ★★★★★ 選型：先問誰會連

| 誰會連 | 用哪一條 |
| --- | --- |
| 一般民眾、不特定人 | ★★★★★ 公開信任 CA（商業 CA 或 ACME） |
| 只有內部同仁，裝置可控 | ★★★★ GPKI 體系（公務系統）或自建 CA（純內部工具） |
| 別的機關的系統 | ★★★★★ 先問對方認哪一條鏈，不要自己決定 |
| 只有機器對機器，兩端都你管 | ★★★ 自建 CA，可完全自動化 |
| 上級規範或採購文件有指定 | ★★★★★ 照指定的走，決策樹到此結束 |

### ★★★★ 四條來源速比

| | GPKI | 商業 CA | ACME | 自建 |
| --- | --- | --- | --- | --- |
| 公開信任 | ★ 否（需派送） | ★★★★ 是 | ★★★★ 是 | ★ 否 |
| 自動續期 | ★ 多半不行 | ★★ 部分可 | ★★★★ 天生支援 | ★★★★ 可 |
| 行政程序 | ★★★★ 重 | ★★★ 中（含採購） | ★ 無 | ★ 無 |
| 費用性質 | 依作業規定 | 採購 | 無授權費 | 無授權費 |

### ★★★★ 五階段流程

| 階段 | 做什麼 | 誰做 |
| --- | --- | --- |
| 一 事前確認 | 窗口、類型、網域清單、應備文件、交付方式 | 技術＋承辦 |
| 二 產 CSR | ★★★★★ 產金鑰與 CSR、驗證、備份私鑰 | **技術人員** |
| 三 送件審驗 | 機關用印申請書、身分證明、CSR（純文字） | 承辦 |
| 四 取得憑證 | ★★★★★ leaf **＋中繼憑證**，驗鏈 | 技術＋承辦 |
| 五 部署驗證 | 組 fullchain、部署、從別台機器驗、進清冊 | **技術人員** |

### ★★★★★ 送件前的五項自檢

| # | 檢查 |
| --- | --- |
| 1 | `O` 是機關**正式全名**，與用印名稱一致 |
| 2 | `CN` 正確，且同名也出現在 SAN 裡 |
| 3 | SAN 涵蓋**每一個**盤點到的名稱（裸網域、`www.`、內網名、舊網域） |
| 4 | 金鑰演算法與長度符合規範（RSA 3072 為穩健預設） |
| 5 | ★★★★★ 私鑰權限 `600`、已備份、**不交給任何人** |

### ★★★★★ 取得憑證後的五項檢查

```bash
# 1 配得上私鑰嗎（兩行必須相同）
openssl x509 -in cert.crt -noout -pubkey | openssl sha256
openssl pkey  -in key.key -pubout       | openssl sha256

# 2 SAN 全部都在嗎
openssl x509 -in cert.crt -noout -ext subjectAltName

# 3 是伺服器憑證嗎
openssl x509 -in cert.crt -noout -ext extendedKeyUsage

# 4 中繼憑證對嗎（上行 issuer 須等於下行 subject）
openssl x509 -in cert.crt -noout -issuer
openssl x509 -in int.crt  -noout -subject

# 5 鏈驗得過嗎
openssl verify -CAfile root.crt -untrusted int.crt cert.crt
```

### ★★★★ 常用 openssl 一行指令

| 目的 | 指令 |
| --- | --- |
| 看憑證主體／簽發者／效期 | `openssl x509 -in c.crt -noout -subject -issuer -dates` |
| 看 SAN | `openssl x509 -in c.crt -noout -ext subjectAltName` |
| 看 EKU（判斷憑證類型） | `openssl x509 -in c.crt -noout -ext extendedKeyUsage` |
| 看 CSR 內容 | `openssl req -in c.csr -noout -text` |
| 驗 CSR 自簽章 | `openssl req -in c.csr -noout -verify` |
| 取憑證公鑰指紋 | `openssl x509 -in c.crt -noout -pubkey \| openssl sha256` |
| 取私鑰公鑰指紋 | `openssl pkey -in c.key -pubout \| openssl sha256` |
| 驗證鏈 | `openssl verify -CAfile root.crt -untrusted int.crt c.crt` |
| 列出 fullchain 內每一張 | `openssl crl2pkcs7 -nocrl -certfile fc.crt \| openssl pkcs7 -print_certs -noout` |
| ★★★★ 線上端點的憑證 | `echo \| openssl s_client -connect h:443 -servername h 2>/dev/null \| openssl x509 -noout -dates` |
| ★★★★★ 線上端點送了幾張憑證 | `echo \| openssl s_client -connect h:443 -servername h -showcerts 2>/dev/null \| grep -c "BEGIN CERT"` |
| 指定根憑證驗線上端點 | `echo \| openssl s_client -connect h:443 -servername h -CAfile root.crt 2>/dev/null \| grep "Verify return"` |
| 安全刪除舊私鑰 | `shred -u -n 3 old.key` |

### ★★★★ 告警閾值建議

| 剩餘天數 | 等級 | 動作 |
| --- | --- | --- |
| 90 | 提醒 | 啟動申請、重新盤點網域 |
| 60 | 注意 | CSR 已送件；沒送要追原因 |
| 30 | 警告 | 審驗中，主管知情 |
| 14 | 嚴重 | 每日追進度，備妥應變方案 |
| 7 | 緊急 | 上報主管，啟動應變 |

### ★★★★ 憑證清冊必要欄位

`服務名稱 / 網域含全部SAN / 來源CA / 憑證類型 / 申請日 / 核發日 / 到期日 /
負責人 / 續期方式 / 中繼憑證位置 / 私鑰路徑 / 部署主機與服務 / 備註`

### ★★★★★ 三條絕對不做

| # | 不做 |
| --- | --- |
| 1 | ★★★★★ 把私鑰交給任何人（含承辦、廠商、CA） |
| 2 | ★★★★★ 對民眾服務用自簽或內部 CA 憑證 |
| 3 | ★★★★★ 教同仁按「繼續前往」略過憑證警告 |

### ★★★ 什麼時候該申請撤銷

| 情況 | 撤銷？ |
| --- | --- |
| 正常到期換新 | ★ 不需要 |
| 私鑰外洩或曾交第三方 | ★★★★★ 立刻撤銷並通報 |
| 主機報廢／遭入侵 | ★★★★ 撤銷 |
| 機關名稱或網域變更 | ★★★ 依窗口建議 |

### ★★★ 相關篇章

| 想做的事 | 看哪篇 |
| --- | --- |
| 產 CSR 的完整做法 | [[090-01-02-guide-PKI-CSR產生與req設定檔]] |
| SAN 與瀏覽器相容性 | [[090-01-04-guide-PKI-CN與SAN設定與瀏覽器相容性]] |
| ACME 自動申請 | [[090-01-03-guide-PKI-向CA申請憑證]] |
| 自建 CA | [[090-01-06-guide-PKI-自建根CA]] |
| 憑證鏈的原理 | [[090-01-07-guide-PKI-自建中繼CA與憑證鏈]] |
| 根憑證派送 | [[090-01-09-guide-PKI-根憑證派送與信任]] |
| 部署到各服務 | [[090-01-10-guide-PKI-憑證部署到各服務]] |
| 格式轉換（PFX/JKS） | [[090-01-11-guide-PKI-憑證格式轉換與檢視工具]] |
| 清冊、監控、續期制度 | [[090-01-12-guide-PKI-憑證生命週期管理]] |
| 出問題怎麼查 | [[090-01-13-guide-PKI-憑證常見問題排查]] |

---

## 練習題

> [!question]- 練習 1：跑一遍決策樹
> 為以下四個服務各跑一次決策樹，寫出結論與理由：
> 1. 機關官網（民眾會連，採購文件未指定憑證等級）
> 2. 內部差勤系統（只有同仁連，裝置由資訊室管理）
> 3. 與 A 機關的資料交換 API（A 機關的系統會來呼叫）
> 4. Prometheus 監控面板（只有資訊室三個人會連）
>
> **參考答案**
> 1. 民眾會連 ⇒ 公開信任 CA。採購未指定 OV，且主機對外可達 ⇒ ★★★★ 優先選 ACME（自動續期）。
> 2. 只有同仁、裝置可控、屬公務系統 ⇒ ★★★★ GPKI 體系。★★★★ 但要先確認外包人員的自帶筆電是否也會連；會的話退回公開信任 CA。
> 3. ★★★★★ 先問 A 機關的驗證端認哪一條鏈，不要自己決定。通常會被指定 GPKI 體系。
> 4. 只有三個人、裝置完全可控、機器對機器性質 ⇒ ★★★ 自建 CA，可腳本自動續期。

> [!question]- 練習 2：盤點一台真實主機的網域差集
> 在一台有 HTTPS 的主機上：
> 1. 用 `grep` 抓出 Nginx（或 Apache）設定裡所有的 `server_name`
> 2. 用 `openssl s_client` 抓出線上憑證的 SAN
> 3. 算出**差集**——設定檔有、但憑證 SAN 沒有的名稱
>
> **參考答案**
> ```bash
> grep -rhE "^\s*server_name" /etc/nginx/sites-enabled/ \
>   | tr -s ' ' | sed 's/^ *server_name *//; s/;$//' | tr ' ' '\n' | sort -u > /tmp/cfg.txt
>
> echo | openssl s_client -connect example.gov.tw:443 -servername example.gov.tw 2>/dev/null \
>   | openssl x509 -noout -ext subjectAltName \
>   | grep -oP 'DNS:\K[^,]+' | tr -d ' ' | sort -u > /tmp/san.txt
>
> comm -23 /tmp/cfg.txt /tmp/san.txt
> ```
> ★★★★★ `comm -23` 印出來的每一行，都是使用者連進來會看到憑證警告的名稱。
> 下次申請時必須補進 SAN。

> [!question]- 練習 3：驗證鏈完整性
> 準備一張憑證、它的中繼與根，做三件事：
> 1. 用 `openssl verify` 驗鏈
> 2. **故意省略** `-untrusted`，觀察錯誤訊息
> 3. 組出 fullchain 並列出裡面每一張的 subject 與 issuer
>
> **參考答案**
> 1. `openssl verify -CAfile root.crt -untrusted int.crt leaf.crt` → `leaf.crt: OK`
> 2. `openssl verify -CAfile root.crt leaf.crt` →
>    `error 20 at 0 depth lookup: unable to get local issuer certificate`
>    ★★★★ 這正是伺服器少裝中繼憑證時，用戶端看到的同一個錯誤。
> 3. `cat leaf.crt int.crt > fc.crt && openssl crl2pkcs7 -nocrl -certfile fc.crt | openssl pkcs7 -print_certs -noout`
>    → 第一張的 issuer 應等於第二張的 subject。

> [!question]- 練習 4：建立最小可用的清冊與監控
> 為你負責的所有 HTTPS 服務：
> 1. 建一份 CSV 清冊（至少含服務、網域、來源 CA、到期日、負責人、續期方式）
> 2. 建一份 `endpoints.txt`
> 3. 跑本篇的 `cert-expiry-check.sh`，確認每一列都抓得到到期日
> 4. 設一個 cron，每天早上跑
>
> **參考答案**
> 重點在**第 3 步抓不到的那幾列**——那通常代表：
> 服務沒開 TLS、DNS 名稱寫錯、防火牆擋住監控主機、或這個服務其實已經下線沒人知道。
> ★★★★ 第一次跑監控最大的價值，就是找出這些「清冊上有、實際上不存在」的項目。

> [!question]- 練習 5：模擬缺中繼憑證的故障
> 在測試環境刻意把 Nginx 的 `ssl_certificate` 從 fullchain 改成只有 leaf，然後：
> 1. 用瀏覽器連——會不會跳警告？
> 2. 用 `curl --cacert root.crt` 連——結果如何？
> 3. 數一數 `s_client -showcerts` 送了幾張
>
> **參考答案**
> 1. ★★★★★ 瀏覽器**很可能仍然正常**（它會依 AIA 欄位自動抓中繼）——這就是這個 bug 難發現的原因。
> 2. `curl` **會失敗**：`SSL certificate problem: unable to get local issuer certificate`。
> 3. `grep -c "BEGIN CERTIFICATE"` 回 `1`。
>
> ★★★★★ 結論：**永遠不要用瀏覽器當作「鏈是否完整」的判準**，要用 `curl` 或 `s_client` 數張數。

> [!question]- 練習 6：估算你機關的行政耗時
> 找出上一次憑證申請的紀錄（公文系統、前任交接文件、或問窗口），
> 算出「送件日 → 核發日」實際幾天，然後回答：
> 1. 你現在的告警閾值夠不夠？
> 2. 如果憑證效期被砍半，你的流程撐不撐得住？
>
> **參考答案**
> 建議把第一級告警設成「實測耗時 × 1.5」，且**不低於 90 天**。
> 第 2 題如果答案是「撐不住」，那就要立刻做兩件事：
> ★★★★ 把能改 ACME 的服務改掉（減少人工張數），
> 以及把清冊與告警制度建起來（讓剩下的人工張數不會漏）。

---

## 小測驗

Q1. 判斷一個服務該用哪一種憑證來源時，**第一個**該問的問題是什麼？

Q2. 是非題：一台伺服器放在內網，所以用自建 CA 的憑證一定沒問題。

Q3. 這行指令回傳 `1`，代表什麼？
```bash
echo | openssl s_client -connect doc.example.gov.tw:443 -servername doc.example.gov.tw -showcerts 2>/dev/null | grep -c "BEGIN CERTIFICATE"
```

Q4. 憑證申請流程中，需要交給承辦或 CA 的是 CSR 還是私鑰？為什麼？

Q5. 選擇題：憑證核發回來後才發現漏了一個網域名稱，正確的處理是？
(A) 用 `openssl` 把該名稱加進憑證的 SAN
(B) 請 CA 幫忙在原憑證上追加
(C) 重新產 CSR 並重跑整個申請流程
(D) 在 Nginx 加一個 `server_name` 就好

Q6. 簡答：為什麼「瀏覽器看起來正常」不能證明憑證鏈部署正確？

Q7. 是非題：EV 憑證的加密強度比 DV 憑證高，所以機敏系統應該用 EV。

Q8. GPKI 體系與 ACME 免費 CA 在「續期」這件事上最大的結構性差異是什麼？這對機關造成什麼風險？

Q9. 這兩行輸出不相同，代表什麼問題？部署上去會發生什麼？
```bash
openssl x509 -in doc.crt -noout -pubkey | openssl sha256
openssl pkey  -in doc.key -pubout       | openssl sha256
```

Q10. 憑證清冊裡，為什麼「中繼憑證位置」與「申請日／核發日」這兩欄特別重要？

> [!question]- 測驗答案
> **Q1.** ★★★★★ **「誰會用瀏覽器或用戶端連這個服務？」**
> 不是問機器放在哪、不是問哪個來源比較便宜。因為信任成不成立取決於
> **連線者裝置的信任庫**，那是你唯一無法用伺服器設定改變的變數。
> → 見〈決策樹：先問「誰會連這個服務」〉
>
> **Q2.** ★★★★ **錯。** 內網不等於使用者裝置可控。外包廠商的筆電、
> 同仁的私人手機、委外維護商都可能連內網服務，而你派不到根憑證給它們。
> 正確的提問是「連的人的裝置在誰手上」。
> → 見〈三個最常見的誤判〉誤判一
>
> **Q3.** ★★★★★ 代表伺服器**只送了自己那張 leaf 憑證，沒送中繼憑證**。
> 症狀是瀏覽器可能正常（會自動補抓中繼），但手機 App、`curl`、Java 用戶端、
> 其他機關的介接程式會驗證失敗。解法是改用 fullchain 部署。
> → 見〈階段四：取得憑證與中繼憑證〉與〈步驟 7-2〉
>
> **Q4.** ★★★★★ **只交 CSR，絕不交私鑰。**
> CSR 裡只有公鑰與識別資訊，CA 簽的就是它；私鑰完全不需要離開主機。
> 任何人（承辦、廠商、CA）索取私鑰都應拒絕並回報——
> 私鑰一旦離開主機，你就無法證明沒有第二份存在。
> → 見〈階段二：產生 CSR〉的 danger callout
>
> **Q5.** ★★★★★ **(C)**。SAN 寫在憑證裡並被 CA 簽章保護，
> 任何事後修改都會讓簽章失效。(A)(B) 技術上不可能，
> (D) 只是讓 Nginx 收下請求，憑證仍然不含該名稱，使用者照樣看到警告。
> 這就是為什麼**階段一的網域盤點**是整個流程最不能省的一步。
> → 見〈階段一：事前確認〉與〈常見錯誤與排錯〉第 5 列
>
> **Q6.** ★★★★★ 因為現代瀏覽器會依憑證的 AIA 欄位**自動抓取缺失的中繼憑證**，
> 或使用先前快取過的中繼。所以伺服器少裝中繼時瀏覽器仍顯示正常，
> 但不會自動補抓的用戶端（手機 App、`curl`、Java、老舊裝置）全部失敗。
> 判準要用 `curl --cacert` 或數 `s_client -showcerts` 的憑證張數。
> → 見〈練習 5〉與〈階段四〉
>
> **Q7.** ★★★ **錯。** DV／OV／EV 的**加密強度完全相同**，
> 差別只在「憑證裡宣稱了什麼」與「CA 審驗多嚴」。
> 機敏系統該加強的是驗證嚴謹度、存取控制與弱點管理，不是憑證等級。
> → 見〈DV / OV / EV 的差別，一句話〉
>
> **Q8.** ★★★★★ ACME 是**自動續期**（機器做，零人工）；
> GPKI 體系多半**沒有 ACME**，每次續期都要走機關行政程序（找窗口、用印、審驗），
> 且耗時不由技術人員控制。
> 風險在於：憑證效期正在快速縮短，續期頻率變高，但每次的人工成本不變——
> 沒有清冊與告警制度的機關就會開始漏續，導致對內系統全面中斷。
> → 見〈與自動化的落差：GPKI 體系沒有 ACME〉
>
> **Q9.** ★★★★★ 代表**憑證與私鑰不是同一對**——可能拿到了別張憑證、
> 私鑰被覆蓋、或中途重產過金鑰。
> 部署上去 Nginx 會直接啟動失敗，錯誤訊息是
> `SSL_CTX_use_PrivateKey_file(...) failed ... key values mismatch`。
> ★★★★ 這項檢查要在**部署前**做，不要等 `nginx -t` 才發現。
> → 見〈步驟 4-1〉與〈常見錯誤與排錯〉第 4 列
>
> **Q10.** ★★★★
> **中繼憑證位置**：續期時最常找不到的就是它，而少了它會造成部分裝置驗證失敗——
> 記下來可以省掉一次跟窗口來回索取的時間。
> **申請日／核發日**：兩者相減就是**貴機關的真實行政耗時**，
> 這是設定告警閾值唯一可靠的依據——手冊上的天數都不如自己量出來的數字準。
> → 見〈憑證清冊該記什麼〉與〈提前啟動申請，並把「行政耗時」量測下來〉

---

## 延伸閱讀

- [[090-01-01-guide-PKI-PKI與憑證基礎]] —— 信任鏈與 CA 的基本概念
- [[090-01-02-guide-PKI-CSR產生與req設定檔]] —— 本篇階段二的完整做法
- [[090-01-03-guide-PKI-向CA申請憑證]] —— 商業 CA 與 ACME 的一般流程
- [[090-01-04-guide-PKI-CN與SAN設定與瀏覽器相容性]] —— SAN 怎麼寫才不會漏
- [[090-01-06-guide-PKI-自建根CA]] —— 什麼情況才該自建
- [[090-01-07-guide-PKI-自建中繼CA與憑證鏈]] —— 憑證鏈的原理與組法
- [[090-01-09-guide-PKI-根憑證派送與信任]] —— 內部信任鏈的必要配套
- [[090-01-10-guide-PKI-憑證部署到各服務]] —— Nginx／Apache／Tomcat 的部署
- [[090-01-11-guide-PKI-憑證格式轉換與檢視工具]] —— PEM／DER／PFX／JKS
- [[090-01-12-guide-PKI-憑證生命週期管理]] —— 清冊、監控、續期、撤銷與稽核
- [[090-01-13-guide-PKI-憑證常見問題排查]] —— 出事時的完整排查流程
- [[090-01-00-idx-PKI-憑證與PKI]] —— 本章索引

> [!warning] ★★★★★ 最後再說一次
> 本篇的表單、天數、費用、網址、窗口與憑證類別，
> **一律依主管機關現行公告與作業要點為準**。
> 動筆申請前，先找到貴機關資訊室的憑證管理窗口，拿到**現行版本**的作業說明。
> 這篇只保證流程結構與技術銜接是對的。
