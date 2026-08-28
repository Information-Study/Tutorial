---
title: "ComfyUI"
desc: "節點式影像生成：從部署到工作流程設計"
aliases: []
tags: [群組/AI人工智慧, 服務/comfyui, 主題/影像生成, 索引]
category: ComfyUI
type: MOC
status: 完成
updated: 2026-08-28
---

# ComfyUI

> [!abstract] 本章導覽
> - 地端執行的影像生成介面，資料不外流
> - 涵蓋 GPU 環境、模型管理、工作流程設計與 API 串接
> - 含與 OpenWebUI 整合，在對話中直接生圖
> - 需要 NVIDIA GPU 與足夠的 VRAM

## 篇章列表

| # | 篇章 | 難度 | 說明 |
| --- | --- | --- | --- |
| 01 | [[01-ComfyUI概論與環境需求]] | 入門 | 它是什麼、與其他工具的差異、GPU 與 VRAM 需求 |
| 02 | [[02-ComfyUI安裝與部署]] | 進階 | 原生安裝與 Docker 部署、CUDA 環境確認 |
| 03 | [[03-ComfyUI模型管理]] | 進階 | Checkpoint、LoRA、VAE、ControlNet 的取得與擺放 |
| 04 | [[04-ComfyUI工作流程基礎]] | 入門 | 節點、連線、取樣器參數與第一張圖 |
| 05 | [[05-ComfyUI進階工作流程]] | 進階 | 圖生圖、Inpaint、ControlNet、放大與批次 |
| 06 | [[06-ComfyUI自訂節點與擴充]] | 進階 | ComfyUI-Manager、擴充安裝與風險評估 |
| 07 | [[07-ComfyUI-API與程式化呼叫]] | 專家 | 用 API 執行工作流程與取得結果 |
| 08 | [[08-ComfyUI與OpenWebUI整合]] | 專家 | 在對話介面中直接生成影像 |
| 09 | [[09-ComfyUI維運與安全]] | 專家 | 反向代理、認證、資源限制與稽核 |

## 建議閱讀順序

- 要架起來 → 01 → 02 → 03
- 要開始生圖 → 04 → 05
- 要串接其他系統 → 07 → 08
- 要上多人環境 → 06 → 09

## 相關章節

- [[00-首頁]]
