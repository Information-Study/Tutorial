---
title: "PHP"
desc: "從多版本安裝到 FPM 調校與安全設定的六篇"
aliases: []
tags: [群組/軟體與開發工具, 索引, 服務/php]
category: 應用執行環境
type: MOC
status: 完成
updated: 2026-08-27
---

# PHP

> [!abstract] 本章導覽
> - 從多版本安裝到 FPM 調校與安全設定的六篇
> - PHP-FPM 那篇是排查 502 與效能問題的關鍵
> - 安全設定與 Laravel 部署章節緊密相關

## 篇章列表

| # | 篇章 | 難度 | 說明 |
| --- | --- | --- | --- |
| 01 | [[01-PHP-安裝與多版本管理]] | 入門 | ondrej PPA 與 Remi 套件庫、多版本共存、擴充套件安裝與版本切換 |
| 02 | [[02-PHP-FPM設定與Pool調校]] | 專家 | pm 模式選擇、max_children 計算、狀態頁判讀與慢請求分析 |
| 03 | [[03-PHP-ini重要參數]] | 進階 | 資源限制、錯誤處理、上傳、session 與安全參數的完整說明 |
| 04 | [[04-Composer-套件管理]] | 入門 | 安裝、lock 檔意義、正式環境安裝參數與私有套件庫認證 |
| 05 | [[05-PHP-OPcache與效能]] | 進階 | OPcache 原理、正式環境參數與部署後失效問題 |
| 06 | [[06-PHP-安全設定]] | 進階 | disable_functions、open_basedir、上傳限制與 session 安全 |

## 建議閱讀順序

- 01 → 02 → 03 是部署 PHP 應用的最小必要集合。
- Composer 在部署 Laravel 前務必讀完。
- OPcache 與安全設定屬於正式環境必修。

## 相關章節

- [[00-首頁]]
- [[01-學習路徑]]
