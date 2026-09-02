---
title: "Linux 基礎"
desc: "全書的地基：從什麼是 Linux 一路到會寫維運腳本"
aliases: []
tags: [群組/Linux, 索引, linux/基礎]
category: Linux基礎
type: MOC
status: 完成
updated: 2026-08-27
---

# Linux 基礎

> [!abstract] 本章導覽
> - 全書的地基：從什麼是 Linux 一路到會寫維運腳本
> - 每一篇都可以在自己的練習機上照著打
> - 主線為 Ubuntu／Debian，各篇附 RHEL 系對照

## 篇章列表

| # | 篇章 | 難度 | 說明 |
| --- | --- | --- | --- |
| 020 | [[020-01-01-guide-Linux-Linux是什麼與發行版選擇]] | 入門 | 從核心與發行版的關係出發，說明該選哪個發行版當學習與正式環境 |
| 020 | [[020-01-02-guide-Linux-實驗環境準備與初次登入]] | 入門 | 用 WSL2、虛擬機或 VPS 建出可以安心亂玩的練習環境 |
| 020 | [[020-01-03-cmd-Linux-終端機與Shell入門]] | 入門 | 認識提示字元、指令結構、Tab 補完、歷史紀錄與求助方式 |
| 020 | [[020-01-04-cmd-Linux-檔案系統與目錄結構]] | 入門 | 走一遍 / 底下每個目錄的用途，建立「東西該放哪」的直覺 |
| 020 | [[020-01-05-cmd-Linux-路徑導覽與檔案操作]] | 入門 | ls cd pwd cp mv rm mkdir touch ln 的完整用法與陷阱 |
| 020 | [[020-01-06-cmd-Linux-檢視檔案內容]] | 入門 | cat less head tail watch 與即時追蹤日誌的方法 |
| 020 | [[020-01-07-cmd-Linux-尋找檔案與內容]] | 入門 | find 依條件找檔案、grep 找內容，以及兩者的組合技 |
| 020 | [[020-01-08-cmd-Linux-檔案權限與擁有者]] | 入門 | rwx 權限模型、數字與符號表示法、umask、特殊權限與 ACL |
| 020 | [[020-01-09-cmd-Linux-使用者與群組管理]] | 入門 | 建立使用者與群組、密碼政策、sudo 授權與 /etc/passwd 結構 |
| 020 | [[020-01-10-cmd-Linux-程序管理與訊號]] | 入門 | ps top kill nice 與前景背景工作、訊號種類的實際差別 |
| 020 | [[020-01-11-cmd-Linux-輸入輸出重導向與管線]] | 入門 | stdin/stdout/stderr、> >> 2>&1、管線與 tee 的組合 |
| 020 | [[020-01-12-cmd-Linux-文字處理三劍客]] | 進階 | grep 找、sed 改、awk 算，加上 cut/sort/uniq/tr 與 diff/patch 比對 |
| 020 | [[020-01-13-cmd-Linux-壓縮與封存]] | 入門 | tar 的參數邏輯、各種壓縮格式取捨與備份打包實務 |
| 020 | [[020-01-14-guide-Linux-套件管理]] | 入門 | apt 與 dnf 的安裝、升級、搜尋、移除，以及第三方套件庫的加法 |
| 020 | [[020-01-15-cmd-Linux-磁碟分割與掛載]] | 進階 | df du lsblk mount fstab 與 LVM 的基本操作 |
| 020 | [[020-01-16-cmd-Linux-網路基礎指令]] | 入門 | ip、nmcli、netplan、ss、ping、dig、curl、wget 與網路設定檔位置 |
| 020 | [[020-01-17-cmd-Linux-systemd服務管理]] | 入門 | systemctl 操作、unit 檔結構與自訂服務的寫法 |
| 020 | [[020-01-18-guide-Linux-排程工作]] | 入門 | crontab 語法、systemd timer 與 at，以及排程失敗的常見原因 |
| 020 | [[020-01-19-guide-Linux-日誌系統]] | 入門 | journalctl 查詢技巧、傳統 syslog 檔案與 logrotate 輪替設定 |
| 020 | [[020-01-20-guide-Linux-環境變數與設定檔]] | 入門 | PATH、環境變數作用域與 bashrc/profile 的載入順序 |
| 020 | [[020-01-21-cmd-Linux-Shell腳本入門]] | 入門 | 變數、條件、迴圈與參數處理，寫出第一個實用腳本 |
| 020 | [[020-01-22-guide-Linux-Shell腳本進階]] | 進階 | 函式、陣列、trap、錯誤處理與可維護腳本的寫法 |
| 020 | [[020-01-23-guide-Linux-Linux常見疑難排解]] | 進階 | 磁碟滿、開不了機、服務起不來、權限錯誤的系統化排查流程 |
| 020 | [[020-01-24-guide-進階儲存-ZFS與Btrfs]] | 專家 | ZFS 的 pool/vdev/dataset 與 Btrfs 的子卷快照，含備份、校驗與調校 |
| 020 | [[020-01-25-guide-Linux-開機流程與GRUB救援]] | 進階 | BIOS/UEFI → GRUB → 核心 → initramfs → systemd target 的完整鏈，與各階段的救援方法 |
| 020 | [[020-01-26-guide-Linux-核心模組與sysctl調校]] | 進階 | lsmod/modprobe 模組管理、sysctl 伺服器調校參數、ulimit 與 limits.conf、cgroup 資源控制 |
| 020 | [[020-01-27-cmd-Linux-硬體資訊與裝置管理]] | 入門 | lscpu/dmidecode/lspci/lsusb/sensors/smartctl 查硬體，udev 規則與裝置命名，盤點腳本 |
| 020 | [[020-01-28-cmd-Linux-時間同步NTP與chrony]] | 入門 | timesyncd 與 chrony 的選擇與設定、對內提供 NTP、AD/Kerberos 的時間要求、漂移監控 |
| 020 | [[020-01-29-guide-Linux-網路儲存與軟體RAID]] | 進階 | NFS 與 CIFS/SMB 的掛載與伺服器端設定、autofs 自動掛載、mdadm 軟體 RAID、磁碟配額 |
| 020 | [[020-01-30-guide-Linux-原始碼安裝與系統升級]] | 進階 | 從原始碼編譯安裝到 /usr/local 的正確做法、checkinstall/stow 管理，以及大版本升級（do-release-upgrade、leapp）的完整流程 |
| 020 | [[020-01-98-trouble-Linux-常見故障排除]] | 進階 | 依症狀查的故障排除索引：判斷分流、處置步驟與一頁式急救卡，原理連回原文 |
| 020 | [[020-01-99-exam-Linux-總結小考]] | 進階 | 涵蓋 Linux 基礎全章的 100 題總複習：是非 50 題、選擇 50 題，附詳解與原文連結 |

## 建議閱讀順序

- **完全新手**：01 → 05 依序讀完，不要跳。
- **有點基礎**：從 08 檔案權限開始，補齊 10、11、12、17 這四篇最常用的。
- **只想快速上手維運**：04 → 08 → 10 → 14 → 17 → 19 → 23。
- **儲存進階**：15 磁碟分割與掛載讀完後，需要 ZFS／Btrfs 快照與校驗再進 24。
- **總整理**：23 疑難排解把前面所有工具串成排錯流程，建議最後讀並反覆回來查。

## 相關章節

- [[000-00-idx-索引-首頁]]
- [[000-01-idx-索引-學習路徑]]
