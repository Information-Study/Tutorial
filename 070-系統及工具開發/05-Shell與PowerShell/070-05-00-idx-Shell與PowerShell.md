---
title: "Shell與PowerShell"
desc: "Bash 與 PowerShell：兩大平台的自動化腳本"
aliases: []
tags: [群組/系統及工具開發, 開發/腳本, 索引]
category: Shell與PowerShell
type: MOC
status: 完成
updated: 2026-08-28
---

# Shell與PowerShell

> [!abstract] 本章導覽
> - Linux 用 Bash、Windows 用 PowerShell，維運人員兩邊都要會
> - 重點在「寫得安全、寫得可維護」而不只是「能跑」
> - 含 shellcheck 與 PSScriptAnalyzer 等靜態檢查工具

## 篇章列表

| # | 篇章 | 難度 | 說明 |
| --- | --- | --- | --- |
| 070 | [[070-05-01-guide-Shell-Bash腳本結構與安全預設]] | 進階 | set -euo pipefail、引號與退出碼 |
| 070 | [[070-05-02-guide-Shell-Bash參數處理與函式]] | 進階 | getopts、函式、陣列與關聯陣列 |
| 070 | [[070-05-03-guide-Shell-Bash除錯與靜態檢查]] | 進階 | set -x、shellcheck 與常見陷阱 |
| 070 | [[070-05-04-guide-Shell-PowerShell基礎與物件管線]] | 入門 | Cmdlet、物件管線與 PSProvider |
| 070 | [[070-05-05-guide-Shell-PowerShell腳本與模組]] | 進階 | 函式、參數、錯誤處理與模組化 |
| 070 | [[070-05-06-cmd-Shell-PowerShell遠端管理與AD操作]] | 進階 | WinRM、Invoke-Command 與 AD 模組 |
| 070 | [[070-05-07-guide-Shell-Bash與PowerShell對照]] | 進階 | 同樣的任務兩種寫法的速查對照 |

## 建議閱讀順序

- Linux 維運 → 01 → 02 → 03
- Windows 維運 → 04 → 05 → 06
- 兩邊都做 → 全部，並注意 07 的對照表

## 相關章節

- [[070-00-idx-系統及工具開發總覽]]
- [[000-00-idx-索引-首頁]]
