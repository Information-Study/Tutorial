---
title: "Proxmox VE"
desc: "機房端虛擬化主線：從安裝、儲存、VM/LXC 到叢集、備份與硬體直通"
aliases: []
tags: [群組/虛擬機與容器, 索引, 主題/虛擬化]
category: Proxmox VE
type: MOC
status: 完成
updated: 2026-09-02
---

# Proxmox VE

> [!abstract] 本章導覽
> - 本手冊的機房端虛擬化主線，13 篇涵蓋單機到叢集的完整生命週期
> - 01～04 是最小可用路徑：裝起來、配好儲存、開出第一台 VM
> - ★★★★ 備份（06）與叢集 Quorum（07）是正式環境最容易出事的兩處

## 篇章列表

| # | 篇章 | 難度 | 說明 |
| --- | --- | --- | --- |
| 050 | [[050-01-03-01-svc-PVE-安裝與初始設定]] | 入門 | 從硬體規劃、ISO 寫入、安裝精靈的 ext4/ZFS 分水嶺，到 no-subscription 套件庫切換、時區 NTP 與安裝後檢查清單的完整流程 |
| 050 | [[050-01-03-02-guide-PVE-儲存設定]] | 進階 | PVE 各種儲存類型的差異與能放什麼內容、Thin Provisioning 超賣的風險、加掛 NFS/iSCSI/ZFS 的完整步驟，以及空間規劃與爆滿時的處理 |
| 050 | [[050-01-03-03-guide-PVE-虛擬機管理]] | 入門 | 建立 VM 的每一個選項該怎麼選、VirtIO 驅動與 Windows guest、CPU type 與遷移的關係、磁碟快取模式，以及做出一個複製即用的 cloud-init 範本 |
| 050 | [[050-01-03-04-guide-PVE-LXC容器管理]] | 進階 | LXC 與 VM 的取捨、特權與非特權容器的安全差異、範本下載、資源限制、bind mount 的 UID 對應、在 LXC 裡跑 Docker 的注意事項與備份遷移 |
| 050 | [[050-01-03-05-guide-PVE-網路設定]] | 進階 | Linux Bridge 與 /etc/network/interfaces、VLAN aware bridge 對接交換器 Trunk、Bond（LACP／active-backup）與交換器端對應設定、多網段規劃、三層防火牆與 SDN 概覽 |
| 050 | [[050-01-03-06-svc-PVE-備份與還原]] | 進階 | vzdump 三種模式的一致性差異、GFS 世代保留與排程、壓縮與加密、備份到 NFS 與 PBS、還原到新 VMID 與單檔還原的完整演練 |
| 050 | [[050-01-03-07-svc-PVE-叢集與高可用]] | 專家 | Cluster、Quorum、HA 群組與線上遷移 |
| 050 | [[050-01-03-08-guide-PVE-使用者權限與API]] | 進階 | Realm、角色權限、API Token 與 AD/LDAP 整合 |
| 050 | [[050-01-03-09-svc-PVE-監控與資源調校]] | 專家 | 資源超配、balloon、CPU type 與磁碟快取模式 |
| 050 | [[050-01-03-10-guide-PVE-硬體直通與GPU]] | 專家 | IOMMU、PCIe passthrough 與 GPU 給 AI 服務 |
| 050 | [[050-01-03-11-svc-PVE-升級與維護]] | 進階 | 大版本升級、節點維護模式與憑證更新 |
| 050 | [[050-01-03-12-guide-PVE-故障排除]] | 專家 | 開不了機、儲存滿、叢集失聯與遷移失敗 |
| 050 | [[050-01-03-13-guide-PVE-建立練習環境]] | 入門 | 用 PVE 快速建出本手冊需要的多機實驗環境 |

## 建議閱讀順序

## 相關章節

- [[050-01-00-idx-虛擬化平台]]
- [[050-00-idx-虛擬機與容器-總覽]]
