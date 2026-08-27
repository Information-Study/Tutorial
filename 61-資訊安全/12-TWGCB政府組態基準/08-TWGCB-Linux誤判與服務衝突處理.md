---
title: "TWGCB Linux 誤判與服務衝突處理"
desc: "套用基準後服務異常的排查，以及與本手冊其他設定的衝突調和"
aliases: [TWGCB, GCB, 政府組態基準]
tags: [群組/資訊安全, 安全/twgcb, 主題/合規]
category: 資訊安全
difficulty: 專家
status: 待撰寫
distro: [ubuntu, rhel]
baseline_version: "TWGCB-01-014 v1.2 / TWGCB-01-008 v1.3 / TWGCB-01-012 v1.2（撰寫前需重新確認）"
prerequisites: ["[[04-TWGCB-Linux本機導入]]"]
updated: 2026-08-27
---

# TWGCB Linux 誤判與服務衝突處理

> [!abstract] 這篇你會學到
> - 建立「套用後服務壞掉」的固定排查順序
> - 處理 SSH、sudo、檔案權限、核心參數造成的常見異常
> - 調和基準要求與 Nginx／資料庫／容器的實際需求
> - 判斷什麼時候該申請豁免而不是硬改

> [!warning] 動筆前必做
> 到 <https://www.nccst.nat.gov.tw/GCB> 確認最新基準編號與版本，
> 更新本篇 frontmatter 的 `baseline_version` 欄位。

## 前置知識

- [[04-TWGCB-Linux本機導入]]

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

- [[23-Linux常見疑難排解]]
- [[07-TWGCB-Linux檢測與符合性報告]]
- [[07-SELinux與AppArmor]]
- 政府組態基準（GCB）官方頁面：<https://www.nccst.nat.gov.tw/GCB>
- 國家資通安全研究院：<https://www.nics.nat.gov.tw/core_business/cybersecurity_defense/GCB/>
