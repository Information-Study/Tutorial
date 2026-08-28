---
title: "Apache"
desc: "Apache 的完整教學，特別標註與 Nginx 思維不同之處"
aliases: []
tags: [群組/軟體與開發工具, 索引, 服務/apache]
category: Web伺服器
type: MOC
status: 完成
updated: 2026-08-27
---

# Apache

> [!abstract] 本章導覽
> - Apache 的完整教學，特別標註與 Nginx 思維不同之處
> - Ubuntu 與 RHEL 兩系的目錄結構差異極大，第一篇會講清楚
> - 與 PHP 的整合方式是 Apache 最常見的使用情境

## 篇章列表

| # | 篇章 | 難度 | 說明 |
| --- | --- | --- | --- |
| 01 | [[01-Apache-安裝與目錄結構]] | 入門 | Debian 系與 RHEL 系截然不同的目錄配置，以及 a2en* 系列工具 |
| 02 | [[02-Apache-VirtualHost設定]] | 進階 | ServerName 比對、Directory 區塊、Alias 與 Require 存取控制 |
| 03 | [[03-Apache-模組與MPM]] | 專家 | prefork / worker / event 三種 MPM 的差異、選擇與調校，以及模組管理 |
| 04 | [[04-Apache-htaccess與Rewrite]] | 進階 | mod_rewrite 的規則語法、旗標、條件，以及 .htaccess 的效能與安全取捨 |
| 05 | [[05-Apache-HTTPS設定]] | 入門 | mod_ssl 設定、Certbot 申請與續期、SNI 與 OCSP Stapling |
| 06 | [[06-Apache-與PHP整合]] | 進階 | mod_php 與 PHP-FPM 的差異、遷移流程，以及多版本 PHP 共存 |
| 07 | [[07-Apache-安全與效能]] | 進階 | 安全加固清單、壓縮與快取、逾時與限流，以及上線前的完整驗證 |

## 建議閱讀順序

- 01 → 02 建立基本站台。
- 要跑 PHP 的話直接接 03 → 06。
- .htaccess 只在需要時讀，並注意它的效能代價。

## 相關章節

- [[00-首頁]]
- [[01-學習路徑]]
