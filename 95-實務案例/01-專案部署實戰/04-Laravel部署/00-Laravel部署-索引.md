---
title: "Laravel 部署"
desc: "從環境需求到正式環境安全檢查表的七篇"
aliases: []
tags: [群組/實務案例, 索引, 部署/laravel]
category: 專案部署實戰
type: MOC
status: 完成
updated: 2026-08-27
---

# Laravel 部署

> [!abstract] 本章導覽
> - 從環境需求到正式環境安全檢查表的七篇
> - 佇列、排程與 Supervisor 是正式環境最容易漏掉的部分
> - Filament 與 Nova 兩個主流後台各有一篇專門教學

## 篇章列表

| # | 篇章 | 難度 | 說明 |
| --- | --- | --- | --- |
| 01 | [[01-Laravel-環境需求與安裝]] | 進階 | PHP 擴充、Composer、MySQL 與 Redis 的準備，以及從 GitHub 專案首次部署 |
| 02 | [[02-Laravel-Nginx與PHP-FPM設定]] | 專家 | 完整的 server block、FPM pool 調校、PathInfo 防護與 HTTPS 三件套 |
| 03 | [[03-Laravel-佇列排程與Supervisor]] | 專家 | queue:work 的正確用法、Supervisor 設定、排程 cron 與部署時的重啟 |
| 04 | [[04-Laravel-快取最佳化與部署流程]] | 專家 | config/route/view 快取、OPcache、Octane 與零停機部署腳本 |
| 05 | [[05-Laravel-Filament部署]] | 專家 | Filament v3/v4 的正式環境部署、資產發布、權限控管與效能調校 |
| 06 | [[06-Laravel-Nova部署]] | 專家 | Nova 授權金鑰、auth.json 管理、CI/CD 整合與資產發布 |
| 07 | [[07-Laravel-正式環境安全檢查表]] | 專家 | 上線前的完整檢查清單：設定、權限、標頭、依賴與一鍵稽核腳本 |

## 建議閱讀順序

- 01 → 02 先讓站台跑起來。
- 03 → 04 補齊背景作業與部署流程。
- 用到後台時再讀 05 或 06。
- 上線前務必逐項對完 07 檢查表。

## 相關章節

- [[00-首頁]]
- [[01-學習路徑]]
