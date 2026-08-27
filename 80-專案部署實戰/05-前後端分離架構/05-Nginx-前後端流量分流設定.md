---
title: "Nginx 前後端流量分流設定"
desc: "同一網域下把 / 給前端、/api 給後端的完整 Nginx 設定與優先序陷阱"
aliases: [location, proxy, api]
tags: [部署/前後端分離, 主題/部署]
category: 專案部署實戰
difficulty: 專家
status: 待撰寫
distro: [ubuntu, rhel]
prerequisites: ["[[04-Nginx-反向代理與負載平衡]]"]
updated: 2026-08-27
---

# Nginx 前後端流量分流設定

> [!abstract] 這篇你會學到
> - 寫出不會互相覆蓋的 location 規則
> - 同時支援 SPA 路由與 API 代理
> - 統一處理 HTTPS 與安全標頭

## 前置知識

- [[04-Nginx-反向代理與負載平衡]]

## 觀念說明

<!-- TODO: 待撰寫 — 這個服務在整體架構中的位置 -->

## 環境準備與安裝

```bash
# TODO: 待撰寫
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> # TODO: 待撰寫（dnf / 套件庫 / 服務名 / 設定檔路徑差異）
> ```

## 基礎設定

<!-- TODO: 待撰寫 — 最小可運作設定，逐段解釋 -->

## 進階設定與調校

<!-- TODO: 待撰寫 -->

## 完整實戰範例

<!-- TODO: 待撰寫 — 完整設定檔另存於 `_設定檔範例/` 並在此引用 -->

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
|  |  |  |

## 安全性注意事項

> [!warning] 注意
> <!-- TODO: 待撰寫 -->

## 速查表

| 指令 / 設定項 | 說明 | 範例 |
| --- | --- | --- |
|  |  |  |

## 練習題

> [!question]- 練習 1
> <!-- TODO: 待撰寫 -->

## 小測驗

<!-- 最多 10 題，針對關鍵細節與易錯觀念 -->

Q1. 
Q2. 
Q3. 

> [!question]- 測驗答案
> **Q1.** 
> **Q2.** 
> **Q3.** 

## 延伸閱讀

- [[03-Nginx-location與rewrite]]
- [[06-Vue-Laravel完整部署實戰]]
