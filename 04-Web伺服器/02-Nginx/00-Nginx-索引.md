---
title: "Nginx"
desc: "從安裝到效能調校與安全設定的九篇完整教學"
aliases: []
tags: [索引, 服務/nginx]
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
| 01 | [[01-Nginx-安裝與目錄結構]] | 入門 | 安裝、服務控制、設定檔目錄與 sites-available 慣例 |
| 02 | [[02-Nginx-設定語法與虛擬主機]] | 入門 | context 階層、指令繼承、server_name 比對與多站台共存 |
| 03 | [[03-Nginx-location與rewrite]] | 進階 | location 比對優先序、try_files、rewrite 與 return 的正確用法 |
| 04 | [[04-Nginx-反向代理與負載平衡]] | 進階 | proxy_pass、標頭轉發、upstream 演算法、健康檢查與 WebSocket |
| 05 | [[05-Nginx-靜態資源與快取]] | 進階 | 靜態檔服務、瀏覽器快取標頭與 proxy_cache 反向代理快取 |
| 06 | [[06-Nginx-HTTPS與Certbot]] | 入門 | 申請憑證、自動續期、HTTP 轉址與現代 TLS 設定 |
| 07 | [[07-Nginx-日誌與除錯]] | 進階 | 自訂 log_format、error_log 等級與常見錯誤碼的判讀 |
| 08 | [[08-Nginx-效能調校]] | 專家 | worker 與連線數、gzip/brotli、HTTP/2 與 HTTP/3、限流與逾時 |
| 09 | [[09-Nginx-安全設定]] | 進階 | 安全標頭、隱藏版本、限制方法與路徑、防盜連與基本防護 |

## 建議閱讀順序

- 01 → 03 打好設定檔基礎，特別是 location 那篇。
- 04 反向代理與 06 HTTPS 是實務上使用頻率最高的兩篇。
- 上線前務必讀完 09 安全設定。

## 相關章節

- [[00-首頁]]
- [[01-學習路徑]]
