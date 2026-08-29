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
> - 讀完 [[060-02-02-00-idx-Nginx]] 的 01～09 再讀本章，才能判斷哪些功能真的需要

> [!warning] 未實機驗證
> 本章多數內容尚未在正式環境驗證，動筆與導入前請先到
> <https://deb.myguard.nl/how-to-use/> 確認當前的套件庫路徑、金鑰與支援的 codename。

> [!info] 範圍界線
> myguard-labs 的**郵件相關套件**（Mailstrix、rspamd 外掛、ViMbAdmin）
> **不納入本手冊** —— 已確定不涵蓋郵件伺服器主題。

## 篇章列表

| # | 篇章 | 難度 | 說明 |
| --- | --- | --- | --- |
| 060 | [[060-02-05-01-guide-MyGuard-MyGuard套件庫介紹]] | 入門 | 強化版 NGINX 與 Angie 的第三方 APT 套件庫，以及它解決了什麼問題 |
| 060 | [[060-02-05-02-guide-MyGuard-Angie伺服器入門]] | 進階 | NGINX 的 fork：內建 ACME、RESTful API、動態 upstream 與監控主控台 |
| 060 | [[060-02-05-03-guide-MyGuard-autocert自動憑證模組]] | 進階 | NGINX 內建的 ACME 客戶端，一行設定取代 certbot 與 cron |
| 060 | [[060-02-05-04-guide-http-shield攻擊攔截]] | 進階 | 編譯進去的攻擊特徵攔截，SQLi、Log4Shell、Shellshock 的低誤判防線 |
| 060 | [[060-02-05-05-guide-error-abuse與sentinel]] | 專家 | 錯誤率限流與信譽評分：擋掉掃描器、爬蟲與 AI 抓取 |
| 060 | [[060-02-05-06-guide-cache-turbo與壓縮模組]] | 進階 | 內建邊緣快取、回應精簡與 Brotli/Zstd 壓縮 |
| 060 | [[060-02-05-07-guide-MyGuard-動態模組管理]] | 進階 | load_module 的順序、模組相依、版本綁定與升級策略 |
| 060 | [[060-02-05-08-guide-MyGuard-MyGuard實戰組合]] | 專家 | 從零建置一台整合 autocert、shield、cache-turbo 的 LXMP 伺服器 |

## 建議閱讀順序

- 01 先弄清楚 MyGuard 是什麼、值不值得引入第三方套件庫。
- 03 `autocert` 與 04 `http-shield` 是最有實務價值的兩篇，可以單獨採用。
- 08 是把前面所有模組組成一份可上線設定的總結。

## 相關章節

- [[060-02-02-00-idx-Nginx]]
- [[060-02-00-idx-Web伺服器]]
