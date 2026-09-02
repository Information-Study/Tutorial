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
| 050 | [[050-01-04-01-guide-KVM-KVM與libvirt架構]] | 進階 | KVM／QEMU／libvirt 三者的分工，以及和 PVE 的關係 |
| 050 | [[050-01-04-02-svc-KVM-安裝與virt-manager]] | 進階 | 套件安裝、權限群組、virt-manager 圖形化建立虛擬機 |
| 050 | [[050-01-04-03-cmd-KVM-virsh指令實務]] | 進階 | 定義、啟停、快照、遷移與 XML 編輯的完整指令流程 |
| 050 | [[050-01-04-04-guide-KVM-儲存池與網路]] | 進階 | storage pool 型式、qcow2 與 raw、NAT 與橋接網路設定 |
| 050 | [[050-01-04-05-guide-KVM-自動化與範本]] | 專家 | virt-install、cloud-init 與用腳本量產虛擬機 |

## 建議閱讀順序

## 相關章節

- [[050-01-00-idx-虛擬化平台]]
- [[050-00-idx-虛擬機與容器-總覽]]
