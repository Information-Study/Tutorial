---
title: "PHP-FPM 設定與 Pool 調校"
desc: "pool 設定、pm 模式選擇、socket 權限與程序數估算"
aliases: [php-fpm, pool, pm]
tags: [群組/軟體與開發工具, 服務/php, 主題/效能]
category: 應用執行環境
difficulty: 進階
status: 待撰寫
distro: [ubuntu, rhel]
prerequisites: ["[[01-PHP-安裝與多版本管理]]"]
updated: 2026-08-27
---

# PHP-FPM 設定與 Pool 調校

> [!abstract] 這篇你會學到
> - 依記憶體算出合理的 max_children
> - 為每個站台開獨立 pool 與使用者
> - 排查 502 與 pool 耗盡

## 前置知識

- [[01-PHP-安裝與多版本管理]]

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

- [[06-Apache-與PHP整合]]
- [[02-Laravel-Nginx與PHP-FPM設定]]
