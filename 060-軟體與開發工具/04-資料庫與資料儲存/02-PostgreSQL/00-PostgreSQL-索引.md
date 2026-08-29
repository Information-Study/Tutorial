---
title: "PostgreSQL"
desc: "八篇涵蓋安裝、權限、設定、備份、調校、複寫與安全"
aliases: []
tags: [群組/軟體與開發工具, 索引, 服務/postgresql]
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
| 01 | [[01-PostgreSQL-安裝與初始化]] | 入門 | 版本選型與 PGDG 套件庫、cluster/database/schema 四層模型、peer 認證、locale 與 encoding 一次定死、pg_createcluster 搬 datadir、交付前驗收腳本 |
| 02 | [[02-PostgreSQL-角色與權限]] | 進階 | role 統一模型、五道權限關卡、public schema 風險、ALTER DEFAULT PRIVILEGES 與可交稽核的權限盤點 |
| 03 | [[03-psql-操作與常用指令]] | 入門 | 把 psql 當維運操作台：連線來源判讀、反斜線指令盤點、ON_ERROR_STOP 腳本模式與可回滾的改資料流程 |
| 04 | [[04-PostgreSQL-設定檔與pg_hba]] | 進階 | 四道關卡的錯誤訊息判讀、pg_hba 第一條命中即定案的比對順序、md5 轉 scram 遷移、reload 與 restart 的判準 |
| 05 | [[05-PostgreSQL-備份與還原]] | 進階 | pg_dump/pg_restore 旗標拆解、WAL 歸檔與 PITR 時間點還原、可交稽核的還原演練腳本 |
| 06 | [[06-PostgreSQL-效能調校與索引]] | 專家 | shared_buffers 與 work_mem 的記憶體預算、EXPLAIN (ANALYZE, BUFFERS) 判讀、六種索引選型、CREATE INDEX CONCURRENTLY 與 autovacuum 膨脹防治 |
| 07 | [[07-PostgreSQL-複寫與高可用]] | 專家 | 用 WAL 串流複寫建起可維運的 PostgreSQL 主備：延遲判讀、複寫槽爆磁碟的防呆、pg_rewind 降級與零雙寫切換 |
| 08 | [[08-PostgreSQL-安全強化]] | 專家 | 收斂 listen_addresses 與 pg_hba、md5 換 scram-sha-256、用自建 CA 強制 hostssl、收乾 PUBLIC 權限、以 pgaudit 建立稽核軌跡，並產出可交稽核的符合性報告 |

## 建議閱讀順序

- 01 → 02 → 03 → 04 是能讓應用連上的最小路徑。
- 05 備份與還原務必實際演練。
- 06 效能調校建議搭配效能瓶頸排查方法論一起讀。

## 相關章節

- [[00-首頁]]
- [[01-學習路徑]]
