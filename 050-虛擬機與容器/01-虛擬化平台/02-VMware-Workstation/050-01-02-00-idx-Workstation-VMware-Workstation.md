---
title: "VMware Workstation"
desc: "桌機端虛擬化主線：安裝、建立虛擬機、快照、網路模式與效能調校"
aliases: []
tags: [群組/虛擬機與容器, 索引, 主題/虛擬化]
category: VMware Workstation
type: MOC
status: 完成
updated: 2026-09-02
---

# VMware Workstation

> [!abstract] 本章導覽
> - 本手冊的桌機端虛擬化主線，用來建各章需要的實驗環境
> - ★★★★ 網路模式（NAT／Bridged／Host-only）是最常搞錯的地方
> - 快照不是備份，第 03 篇會說清楚兩者的界線

## 篇章列表

| # | 篇章 | 難度 | 說明 |
| --- | --- | --- | --- |
| 050 | [[050-01-02-01-svc-Workstation-安裝與授權]] | 入門 | Windows 與 Linux 兩邊的 Workstation 安裝步驟、Hyper-V／WSL2 共存衝突的解法、Player 與 Pro 的差別 |
| 050 | [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] | 入門 | 從新增虛擬機精靈到 Ubuntu Server 裝好上線的完整流程，含 CPU／記憶體／磁碟該給多少的判斷準則、磁碟類型與韌體選擇 |
| 050 | [[050-01-02-03-guide-Workstation-快照與複製]] | 進階 | 快照的差異磁碟鏈原理與效能代價、為什麼快照不是備份、連結複製與完整複製的取捨，以及用範本量產實驗機的標準流程 |
| 050 | [[050-01-02-04-guide-Workstation-網路模式]] | 進階 | NAT／Bridged／Host-only／自訂網段的差別與實驗環境選法 |
| 050 | [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] | 入門 | VMware Tools 與 open-vm-tools 的差異、Windows／Linux 兩邊的安裝、共享資料夾與 /mnt/hgfs 自動掛載、剪貼簿拖放，以及時間同步的坑 |
| 050 | [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] | 進階 | CPU 與記憶體配置準則、虛擬磁碟型式與壓縮、關閉不需要的虛擬裝置、巢狀虛擬化的開啟與驗證，以及完整的常見錯誤排錯表 |

## 建議閱讀順序

## 相關章節

- [[050-01-00-idx-虛擬化平台]]
- [[050-00-idx-虛擬機與容器-總覽]]
