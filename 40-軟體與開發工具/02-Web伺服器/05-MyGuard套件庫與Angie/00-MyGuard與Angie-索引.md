---
title: "MyGuard 套件庫與 Angie"
desc: "強化版 NGINX 與 Angie：autocert、http-shield、cache-turbo 等自製模組的實務應用"
aliases: []
tags: [群組/軟體與開發工具, 索引, 服務/myguard]
category: Web伺服器
type: MOC
status: 完成
updated: 2026-08-28
---

# MyGuard 套件庫與 Angie

> [!abstract] 本章導覽
> - `deb.myguard.nl` 是 myguard-labs 維護的第三方 Debian／Ubuntu APT 套件庫，
>   提供**強化版 NGINX 與 Angie**：mainline、HTTP/3 (QUIC)、kTLS、Brotli、
>   Zstandard、ModSecurity v3、Lua／NJS，加上 100 多個動態模組，每日重建
> - 它**不是**端點防護代理，也**不是** NGINX 官方套件庫
> - 對本手冊影響最大的是 `autocert`（免 certbot 的自動憑證）與
>   `http-shield`（輕量攻擊攔截）兩個自製模組
> - 讀完 [[00-Nginx-索引]] 的 01～09 再讀本章，才能判斷哪些功能真的需要

> [!warning] 未實機驗證
> 本章多數內容尚未在正式環境驗證，動筆與導入前請先到
> <https://deb.myguard.nl/how-to-use/> 確認當前的套件庫路徑、金鑰與支援的 codename。

> [!info] 範圍界線
> myguard-labs 的**郵件相關套件**（Mailstrix、rspamd 外掛、ViMbAdmin）
> **不納入本手冊** —— 已確定不涵蓋郵件伺服器主題。

## 篇章列表

| # | 篇章 | 難度 | 說明 |
| --- | --- | --- | --- |
| 01 | [[01-MyGuard套件庫介紹]] | 入門 | 強化版 NGINX 與 Angie 的第三方 APT 套件庫，以及它解決了什麼問題 |
| 02 | [[02-Angie伺服器入門]] | 進階 | NGINX 的 fork：內建 ACME、RESTful API、動態 upstream 與監控主控台 |
| 03 | [[03-autocert自動憑證模組]] | 進階 | NGINX 內建的 ACME 客戶端，一行設定取代 certbot 與 cron |
| 04 | [[04-http-shield攻擊攔截]] | 進階 | 編譯進去的攻擊特徵攔截，SQLi、Log4Shell、Shellshock 的低誤判防線 |
| 05 | [[05-error-abuse與sentinel]] | 專家 | 錯誤率限流與信譽評分：擋掉掃描器、爬蟲與 AI 抓取 |
| 06 | [[06-cache-turbo與壓縮模組]] | 進階 | 內建邊緣快取、回應精簡與 Brotli/Zstd 壓縮 |
| 07 | [[07-動態模組管理]] | 進階 | 100 多個動態模組的載入、順序與相依性處理 |
| 08 | [[08-MyGuard實戰組合]] | 專家 | 把 autocert、http-shield、cache-turbo 組成一套完整的正式環境設定 |

## 建議閱讀順序

- 01 先弄清楚 MyGuard 是什麼、值不值得引入第三方套件庫。
- 03 `autocert` 與 04 `http-shield` 是最有實務價值的兩篇，可以單獨採用。
- 08 是把前面所有模組組成一份可上線設定的總結。

## 相關章節

- [[00-Nginx-索引]]
- [[00-Web伺服器-索引]]
