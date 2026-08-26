---
title: "PostgreSQL"
desc: "八篇涵蓋安裝、權限、設定、備份、調校、複寫與安全"
aliases: []
tags: [索引, 服務/postgresql]
category: 資料庫與資料儲存
type: MOC
status: 完成
updated: 2026-08-27
---

# PostgreSQL

> [!abstract] 本章導覽
> - 八篇涵蓋安裝、權限、設定、備份、調校、複寫與安全
> - pg_hba.conf 的認證比對是新手最常卡住的地方
> - PITR 時間點還原是 PostgreSQL 的一大優勢，值得學會

## 篇章列表

| # | 篇章 | 難度 | 說明 |
| --- | --- | --- | --- |
| 01 | [[01-PostgreSQL-安裝與初始化]] | 入門 | 官方套件庫安裝、叢集初始化、locale 與資料目錄 |
| 02 | [[02-PostgreSQL-角色與權限]] | 進階 | role 統一模型、資料庫與 schema 權限、預設權限設定 |
| 03 | [[03-psql-操作與常用指令]] | 入門 | psql 反斜線指令、連線方式與匯入匯出 |
| 04 | [[04-PostgreSQL-設定檔與pg_hba]] | 進階 | postgresql.conf 關鍵參數與 pg_hba.conf 的認證比對順序 |
| 05 | [[05-PostgreSQL-備份與還原]] | 進階 | pg_dump/pg_restore、基礎備份與 WAL 時間點還原 |
| 06 | [[06-PostgreSQL-效能調校與索引]] | 專家 | 記憶體參數、EXPLAIN ANALYZE、索引種類與 autovacuum |
| 07 | [[07-PostgreSQL-複寫與高可用]] | 專家 | 串流複寫、同步與非同步取捨、故障切換流程 |
| 08 | [[08-PostgreSQL-安全強化]] | 進階 | 監聽範圍、SSL 連線、密碼加密方式與稽核設定 |

## 建議閱讀順序

- 01 → 02 → 03 → 04 是能讓應用連上的最小路徑。
- 05 備份與還原務必實際演練。
- 06 效能調校建議搭配效能瓶頸排查方法論一起讀。

## 相關章節

- [[00-首頁]]
- [[01-學習路徑]]
