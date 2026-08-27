---
title: "Nginx"
desc: "從安裝到效能調校與安全設定的九篇完整教學"
aliases: []
tags: [群組/軟體與開發工具, 索引, 服務/nginx]
category: Web伺服器
type: MOC
status: 完成
updated: 2026-08-27
---

# Nginx

> [!abstract] 本章導覽
> - 從安裝到效能調校與安全設定的九篇完整教學
> - 01 到 03 是基本功，04 到 06 是最常用的實戰能力
> - 07 到 09 處理除錯、效能與安全，屬於正式環境必修

## 篇章列表

| # | 篇章 | 難度 | 說明 |
| --- | --- | --- | --- |
| 01 | [[01-Nginx-安裝與目錄結構]] | 入門 | 三種安裝來源、目錄配置慣例，以及第一次啟動就該做對的設定 |
| 02 | [[02-Nginx-設定語法與虛擬主機]] | 進階 | 指令、區塊、繼承規則，以及 server_name 的比對順序 |
| 03 | [[03-Nginx-location與rewrite]] | 進階 | location 的六種比對修飾符、優先順序，以及 try_files / rewrite / return 的正確用法 |
| 04 | [[04-Nginx-反向代理與負載平衡]] | 進階 | proxy_pass 的斜線規則、標頭轉發、upstream 演算法、健康檢查與 WebSocket |
| 05 | [[05-Nginx-靜態資源與快取]] | 進階 | expires、Cache-Control、ETag、gzip/brotli 壓縮與 proxy_cache 反向代理快取 |
| 06 | [[06-Nginx-HTTPS與Certbot]] | 入門 | TLS 設定、Let's Encrypt 憑證申請與自動續期、HSTS 與 OCSP Stapling |
| 07 | [[07-Nginx-日誌與除錯]] | 進階 | 自訂 log_format、error_log 等級判讀、慢請求分析與系統化排錯流程 |
| 08 | [[08-Nginx-效能調校]] | 專家 | worker 與連線數、核心參數、HTTP/2 與 HTTP/3、限流與逾時的完整調校 |
| 09 | [[09-Nginx-安全設定]] | 進階 | 安全標頭、隱藏版本、路徑與方法限制、防盜連、IP 封鎖與上線前檢查清單 |

## 建議閱讀順序

- 01 → 03 打好設定檔基礎，特別是 location 那篇。
- 04 反向代理與 06 HTTPS 是實務上使用頻率最高的兩篇。
- 上線前務必讀完 09 安全設定。

## 相關章節

- [[00-首頁]]
- [[01-學習路徑]]
