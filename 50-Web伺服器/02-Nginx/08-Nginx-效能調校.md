---
title: "Nginx 效能調校"
desc: "worker 與連線數、gzip/brotli、HTTP/2 與 HTTP/3、限流與逾時"
aliases: [worker, http2, brotli]
tags: [服務/nginx, 主題/效能]
category: Web伺服器
difficulty: 專家
status: 待撰寫
distro: [ubuntu, rhel]
prerequisites: ["[[05-Nginx-靜態資源與快取]]"]
updated: 2026-08-27
---

# Nginx 效能調校

> [!abstract] 這篇你會學到
> - 依機器規格調出合理的 worker 設定
> - 用壓縮與新協定改善載入時間
> - 用 limit_req 擋住暴衝流量

## 前置知識

- [[05-Nginx-靜態資源與快取]]

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

## 延伸閱讀

- [[04-效能瓶頸排查方法論]]
- [[09-Nginx-安全設定]]
