---
title: "KVM 與 libvirt"
desc: "Linux 原生虛擬化：libvirt 架構、virsh 實務，以及它跟 PVE 的關係"
aliases: []
tags: [群組/虛擬機與容器, 索引, 主題/虛擬化]
category: KVM與libvirt
type: MOC
status: 完成
updated: 2026-09-02
---

# KVM 與 libvirt

> [!abstract] 本章導覽
> - PVE 底層就是 KVM，看懂這章等於看懂 PVE 的引擎
> - 沒有 PVE 的環境（單台 Linux 伺服器要跑幾台 VM）就用這章
> - virsh 是純指令操作，適合寫進自動化腳本

## 篇章列表

| # | 篇章 | 難度 | 說明 |
| --- | --- | --- | --- |
| 050 | [[050-01-04-01-guide-KVM-KVM與libvirt架構]] | 進階 | KVM 核心模組、QEMU 模擬器、libvirt 管理層三者的分工與界線，libvirtd 到 virtqemud 的演進，domain XML 的角色，以及 PVE 底層與 KVM 的真正關係 |
| 050 | [[050-01-04-02-svc-KVM-安裝與virt-manager]] | 進階 | 硬體支援檢查與巢狀虛擬化、套件安裝（Ubuntu 與 RHEL）、libvirt 群組與權限為什麼要重新登入、system 與 session 模式的差別，以及用 virt-manager 建出第一台 VM |
| 050 | [[050-01-04-03-cmd-KVM-virsh指令實務]] | 進階 | virsh 完整生命週期指令、destroy 為什麼不是刪除、dumpxml 與 edit 改設定、內部與外部快照的差別、console 連線與退出、線上遷移，以及 virsh 與 qm 的對照表 |
| 050 | [[050-01-04-04-guide-KVM-儲存池與網路]] | 進階 | libvirt storage pool 的 dir／logical／netfs／zfs 四種型式與 virsh pool-* 完整流程、qcow2 與 raw 的取捨與 qemu-img 實務、預設 NAT 網路 virbr0 的封包路徑、用 Netplan 建 br0 做橋接網路（含不要把自己鎖在門外的做法）與隔離網路 |
| 050 | [[050-01-04-05-guide-KVM-自動化與範本]] | 專家 | virt-install 完整參數與非互動安裝、cloud image ＋ cloud-init（cloud-localds seed ISO）量產虛擬機、用 virt-sysprep／virt-customize 做範本、virt-clone 與 backing file 連結複製、一支腳本開出三台已設好主機名稱與固定 IP 的 Ubuntu VM |
| 050 | [[050-01-04-98-trouble-KVM-常見故障排除]] | 進階 | 依症狀查的 KVM／libvirt 故障排除索引：判斷分流、編號排查步驟與一頁式急救卡，原理回連原文 |
| 050 | [[050-01-04-99-exam-KVM-總結小考]] | 進階 | 涵蓋 KVM 與 libvirt 全章的 100 題總複習：是非 50 題、選擇 50 題，附詳解與原文連結 |

## 建議閱讀順序

## 相關章節

- [[050-01-00-idx-虛擬化平台]]
- [[050-00-idx-虛擬機與容器-總覽]]
