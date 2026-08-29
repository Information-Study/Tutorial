---
title: "TWGCB Linux AD 網域導入"
desc: "Linux 加入 AD 網域後，哪些基準項目改由網域集中控管"
aliases: [TWGCB, GCB, 政府組態基準]
tags: [群組/資訊安全, 安全/twgcb, 主題/合規]
category: TWGCB政府組態基準
difficulty: 專家
status: 待撰寫
distro: [ubuntu, rhel]
baseline_version: "TWGCB-01-014 v1.2 / TWGCB-01-008 v1.3 / TWGCB-01-012 v1.2（撰寫前需重新確認）"
prerequisites: ["[[090-06-04-guide-TWGCB-Linux本機導入]]"]
updated: 2026-08-27
---

# TWGCB Linux AD 網域導入

> [!abstract] 這篇你會學到
> - 用 realmd／SSSD／Kerberos 把 Linux 主機加入 AD 網域
> - 分辨哪些 GCB 項目該由 AD 控管、哪些仍須本機設定
> - 處理網域密碼原則與本機 pam_pwquality 的重疊與衝突
> - 規劃網域與本機兩層設定的分工與稽核方式

> [!warning] 動筆前必做
> 到 <https://www.nccst.nat.gov.tw/GCB> 確認最新基準編號與版本，
> 更新本篇 frontmatter 的 `baseline_version` 欄位。

## 前置知識

- [[090-06-04-guide-TWGCB-Linux本機導入]]

## 觀念說明

<!-- TODO: 待撰寫 -->

## 逐步說明

<!-- TODO: 待撰寫 -->

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> <!-- TODO: 待撰寫 — TWGCB-01-008 / 01-012 與 Ubuntu 基準的項目差異 -->

## 完整實戰範例

<!-- TODO: 待撰寫 -->

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
|  |  |  |

## 檢查清單

- [ ] <!-- TODO: 待撰寫 -->

## 練習題

> [!question]- 練習 1
> <!-- TODO: 待撰寫 -->

## 小測驗

<!-- 最多 10 題，針對關鍵細節與易錯觀念 -->

Q1. 
Q2. 
Q3. 

> [!question]- 測驗答案
> **Q1.** 
> **Q2.** 
> **Q3.** 

## 延伸閱讀

- [[090-06-06-guide-TWGCB-Linux大量派送]]
- [[020-01-09-cmd-Linux-使用者與群組管理]]
- 政府組態基準（GCB）官方頁面：<https://www.nccst.nat.gov.tw/GCB>
- 國家資通安全研究院：<https://www.nics.nat.gov.tw/core_business/cybersecurity_defense/GCB/>
