---
title: "OpenWebUI"
desc: "給 Ollama 一個好用的網頁介面與知識庫能力"
aliases: []
tags: [索引, 服務/openwebui]
category: AI服務
type: MOC
status: 完成
updated: 2026-08-27
---

# OpenWebUI

> [!abstract] 本章導覽
> - 給 Ollama 一個好用的網頁介面與知識庫能力
> - 本章以不依賴 Docker 的原生安裝為主線
> - RAG 知識庫篇串接 Qdrant，是整章的重點

## 篇章列表

| # | 篇章 | 難度 | 說明 |
| --- | --- | --- | --- |
| 01 | [[01-OpenWebUI-原生安裝與systemd]] | 進階 | 以 venv 原生安裝、資料目錄規劃與 systemd 託管 |
| 02 | [[02-OpenWebUI-連接模型服務]] | 進階 | 連接本地 Ollama 與外部 OpenAI 相容 API 的設定方式 |
| 03 | [[03-OpenWebUI-使用者管理與權限]] | 進階 | 註冊控制、角色權限、模型存取限制與群組管理 |
| 04 | [[04-OpenWebUI-RAG與知識庫]] | 專家 | 文件上傳、嵌入模型選擇、切塊策略與接上 Qdrant |
| 05 | [[05-OpenWebUI-反向代理與HTTPS]] | 進階 | Nginx 反代設定、WebSocket 轉發、上傳大小與 HTTPS |

## 建議閱讀順序

- 01 → 02 先跑起來並連上模型。
- 對外開放前務必完成 03 權限與 05 反向代理加 HTTPS。
- 04 RAG 建議在讀完 Qdrant 章節後再進。

## 相關章節

- [[00-首頁]]
- [[01-學習路徑]]
