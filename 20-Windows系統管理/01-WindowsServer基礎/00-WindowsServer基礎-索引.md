---
title: "Windows Server 基礎"
desc: "版本授權、安裝初始設定、角色功能、PowerShell 與更新管理"
aliases: []
tags: [群組/Windows, 索引, windows/server]
category: Windows系統管理
type: MOC
status: 完成
updated: 2026-08-27
---

# Windows Server 基礎

> [!abstract] 本章導覽
> - 從安裝一台乾淨的 Windows Server 到可以承載角色的完整流程
> - PowerShell 是後續所有自動化的基礎
> - 更新管理決定了長期的安全狀態

## 篇章列表

| # | 篇章 | 難度 | 說明 |
| --- | --- | --- | --- |
| 01 | [[01-WindowsServer版本與授權]] | 入門 | 版本差異、CAL 與桌面體驗 vs Server Core |
| 02 | [[02-WindowsServer安裝與初始設定]] | 入門 | 安裝、命名、IP、時區、遠端桌面與初始加固 |
| 03 | [[03-伺服器管理員與角色功能]] | 入門 | 角色安裝、功能相依與多伺服器管理 |
| 04 | [[04-PowerShell基礎與遠端管理]] | 進階 | Cmdlet 結構、管線、WinRM 與 Invoke-Command |
| 05 | [[05-Windows更新管理]] | 進階 | 更新環、WSUS 概覽、重開機視窗與 GPO 搭配 |

## 建議閱讀順序

- 01 → 02 先把機器建起來。
- 03 安裝需要的角色（AD、WDS 等）。
- 04 PowerShell 建議儘早學，後面章節大量使用。

## 相關章節

- [[00-首頁]]
- [[01-學習路徑]]
