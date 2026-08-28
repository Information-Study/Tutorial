---
title: "TWGCB Linux 大量派送"
desc: "用 Ansible 把基準設定 playbook 化並依角色分群套用"
aliases: [TWGCB, GCB, 政府組態基準]
tags: [群組/資訊安全, 安全/twgcb, 主題/合規]
category: TWGCB政府組態基準
difficulty: 專家
status: 待撰寫
distro: [ubuntu, rhel]
baseline_version: "TWGCB-01-014 v1.2 / TWGCB-01-008 v1.3 / TWGCB-01-012 v1.2（撰寫前需重新確認）"
prerequisites: ["[[04-TWGCB-Linux本機導入]]"]
updated: 2026-08-27
---

# TWGCB Linux 大量派送

> [!abstract] 這篇你會學到
> - 把逐項設定寫成冪等的 Ansible playbook
> - 依伺服器角色分群套用不同的例外
> - 把基準版本與 playbook 一起納入版本控制
> - 規劃變更視窗與回退流程

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

- [[07-TWGCB-Linux檢測與符合性報告]]
- [[06-部署自動化]]
- 政府組態基準（GCB）官方頁面：<https://www.nccst.nat.gov.tw/GCB>
- 國家資通安全研究院：<https://www.nics.nat.gov.tw/core_business/cybersecurity_defense/GCB/>
