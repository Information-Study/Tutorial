---
title: "Nuxt 部署"
desc: "Nuxt 的渲染模式決定了部署方式，第一篇先做選型"
aliases: []
tags: [群組/實務案例, 索引, 部署/nuxt]
category: 專案部署實戰
type: MOC
status: 完成
updated: 2026-08-27
---

# Nuxt 部署

> [!abstract] 本章導覽
> - Nuxt 的渲染模式決定了部署方式，第一篇先做選型
> - SSR 路線以 PM2 託管 Nitro 伺服器為主線
> - Nginx 反代篇處理靜態資源直出與頁面快取

## 篇章列表

| # | 篇章 | 難度 | 說明 |
| --- | --- | --- | --- |
| 01 | [[01-Nuxt-渲染模式與部署選型]] | 進階 | SSR／SSG／ISR／SPA 四種模式的差異、Nitro preset 與選型決策 |
| 02 | [[02-Nuxt-SSR與PM2部署]] | 進階 | 用 PM2 或 systemd 管理 Nuxt SSR 程序、cluster、零停機重載與記憶體監控 |
| 03 | [[03-Nuxt-Nginx反向代理與快取]] | 專家 | SSR 前面的 Nginx 設定、靜態資源直送、proxy_cache 微快取與繞過規則 |
| 04 | [[04-Nuxt-Docker部署]] | 專家 | 多階段建置 Nitro 產物並以非 root 執行的映像 |

## 建議閱讀順序

- 01 選型先讀，再決定往下走哪條路。
- **SSR**：02 → 03。
- **容器化**：04。
- 搭配 Laravel API 時接續前後端分離架構章節。

## 相關章節

- [[00-首頁]]
- [[01-學習路徑]]
