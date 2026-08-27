---
title: "Windows 系統管理"
desc: "Windows Server、Active Directory、群組原則、WDS 部署與故障排除"
aliases: []
tags: [索引, windows]
category: Windows系統管理
type: MOC
status: 完成
updated: 2026-08-27
---

# Windows 系統管理

> [!abstract] 本章導覽
> - 涵蓋 Windows 伺服器環境的建置、集中管理與大量部署
> - 以 GUI 操作步驟為主、PowerShell 指令為輔，兩者並陳
> - AD 與 GPO 是核心，WDS 處理大量佈建，故障排除獨立成章

## 子分類

| 分類 | 內容 |
| --- | --- |
| [[00-WindowsServer基礎-索引]] | 版本授權、安裝初始設定、角色功能、PowerShell 與更新管理 |
| [[00-ActiveDirectory-索引]] | 網域架構規劃、DC 建置、帳號群組管理、備份還原與安全強化 |
| [[00-群組原則-索引]] | GPO 運作原理、建立連結、常用原則、軟體派送與疑難排解 |
| [[00-WDS-索引]] | 用 PXE 網路開機大量部署 Windows 電腦 |
| [[00-Windows故障排除-索引]] | 開機、效能、網路、設定檔與事件記錄的排查 |

## 建議閱讀順序

- **建立網域環境**：Windows Server 基礎 → Active Directory → 群組原則。
- **大量部署電腦**：WDS 系統部署（需先有 AD 與 DHCP）。
- **日常維運**：Windows 故障排除。
- **合規要求**：搭配 [[00-TWGCB-索引]] 的 Windows 基準。

## 相關章節

- [[00-首頁]]
- [[01-學習路徑]]
