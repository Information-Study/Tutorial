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
| 050 | [[050-01-03-07-svc-PVE-叢集與高可用]] | 專家 | corosync 與 pmxcfs 的運作、Quorum 與腦裂的成因、兩節點 QDevice 解法、線上與離線遷移的前提、HA 群組與 watchdog fencing、節點失聯時的正確處置順序、叢集拆除與節點移除 |
| 050 | [[050-01-03-08-guide-PVE-使用者權限與API]] | 進階 | Realm 認證來源、路徑式 ACL 的繼承模型、內建角色與權限對照、API Token 與權限分離、pvesh 與 REST API 實作、雙因素驗證、AD/LDAP 整合與常見卡關點 |
| 050 | [[050-01-03-09-svc-PVE-監控與資源調校]] | 專家 | 內建 RRD 圖表怎麼判讀、IO delay 的真正意義、外接 InfluxDB/Prometheus、CPU 記憶體儲存各自的超配準則、balloon 與 KSM 的實際行為、CPU type 與遷移的取捨、磁碟快取模式與資料安全、IO thread 與 SCSI 控制器 |
| 050 | [[050-01-03-10-guide-PVE-硬體直通與GPU]] | 專家 | IOMMU 原理與群組限制、vfio-pci 綁定與黑名單、PCIe passthrough 完整步驟、GPU 直通給 AI 服務，以及直通換來的可用性代價 |
| 050 | [[050-01-03-11-svc-PVE-升級與維護]] | 進階 | 套件庫選擇與小版本更新、大版本升級的檢查工具與完整步驟、叢集節點升級順序與維護模式、憑證更新，以及日常維護清單 |
| 050 | [[050-01-03-12-guide-PVE-故障排除]] | 專家 | 依症狀查 PVE 本身的服務與叢集層故障：開不了機、後台連不上、儲存滿、Quorum 掉了、遷移失敗、VM 與 LXC 起不來、備份失敗、憑證過期 |
| 050 | [[050-01-03-13-guide-PVE-建立練習環境]] | 入門 | 用 PVE 快速建出本手冊各章需要的多機實驗環境：實驗網段與 VLAN 規劃、Ubuntu cloud-init 範本、一鍵開出 LXMP 全套機器、快照當還原點、LXC 省資源技巧與清理重建腳本 |

## 建議閱讀順序

## 相關章節

- [[050-01-00-idx-虛擬化平台]]
- [[050-00-idx-虛擬機與容器-總覽]]
