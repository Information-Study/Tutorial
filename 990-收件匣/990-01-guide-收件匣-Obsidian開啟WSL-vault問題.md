---
title: "Obsidian 開啟 WSL vault 的 EISDIR 問題"
desc: "Windows 版 Obsidian 監看 \\\\wsl.localhost 路徑失敗的三種解法"
aliases: [EISDIR, Obsidian WSL]
tags: [群組/附錄, 收件匣, 工具/obsidian, 主題/wsl]
category: 收件匣
difficulty: 入門
status: 完成
distro: [ubuntu]
prerequisites: []
updated: 2026-08-27
---

# Obsidian 開啟 WSL vault 的 EISDIR 問題

> [!abstract] 問題
> Windows 版 Obsidian 開啟位於 WSL 內的 vault
> （`\\wsl.localhost\Ubuntu-26.04\home\...\tutorial`）時出現：
>
> ```
> Error: EISDIR: illegal operation on a directory,
> watch '\\wsl.localhost\Ubuntu-26.04\home\n126226695\tutorial\'
> ```

## 原因

這**不是 vault 內容的問題**。Windows 版 Obsidian（Electron）用
`fs.watch` 遞迴監看 vault 目錄，而 `\\wsl.localhost\` 是 WSL 透過
**9P 網路檔案系統**分享出來的路徑——Windows 的目錄變更通知 API
在這種網路路徑上不支援遞迴監看，Electron 便拋出 `EISDIR`。

三種解法，依推薦順序：

---

## 解法一（推薦）：把 WSL 路徑掛成磁碟機代號

多數回報中，把 `\\wsl.localhost\發行版` 對應成磁碟機代號後，
監看就能正常運作。**改動最小，先試這個。**

在 **PowerShell** 執行：

```powershell
net use Z: \\wsl.localhost\Ubuntu-26.04 /persistent:yes
```

然後在 Obsidian：

1. 左下角 vault 切換 →「開啟另一個儲存庫」→「開啟資料夾作為儲存庫」
2. 選 `Z:\home\n126226695\tutorial`
3. 把原本用 `\\wsl.localhost\...` 開的舊 vault 項目移除

> [!tip] 如果 `wsl.localhost` 無效
> 舊版 Windows 用 `\\wsl$\Ubuntu-26.04`：
> ```powershell
> net use Z: \\wsl$\Ubuntu-26.04 /persistent:yes
> ```

> [!warning] 這個方案的已知限制
> 9P 的 I/O 比原生慢，vault 大了之後開啟與搜尋會有感。
> 若掛了磁碟機代號仍出現同樣錯誤，直接用解法二。

---

## 解法二（體驗最好）：在 WSL 裡跑 Linux 版 Obsidian

本機已確認 **systemd、snap、WSLg 都可用**，可以直接跑 Linux GUI 程式，
視窗會出現在 Windows 桌面上。vault 走**原生 ext4**，
監看、效能、Git 整合全部正常。

在 **WSL 終端機**執行：

```bash
sudo snap install obsidian --classic
obsidian &
```

之後從 Obsidian 內開啟 `/home/n126226695/tutorial` 即可。

> [!tip] 加到 Windows 開始功能表
> WSLg 會自動把已安裝的 Linux GUI 程式加進開始功能表
> （名稱後面帶 `(Ubuntu-26.04)`），之後點那個捷徑就能開。

---

## 解法三：用 git 複製一份到 Windows 側

vault 本身是 git repo，可以在 Windows 放一份工作副本，
Windows Obsidian 開原生 NTFS 路徑（完全沒有 9P 問題），改動用 git 同步。

在 **PowerShell**：

```powershell
git clone \\wsl.localhost\Ubuntu-26.04\home\n126226695\tutorial C:\Users\<你的帳號>\tutorial
cd C:\Users\<你的帳號>\tutorial
git config core.quotepath false      # 中文檔名正常顯示
```

WSL 端的 repo **已設定** `receive.denyCurrentBranch=updateInstead`，
所以 Windows 側改完可以直接推回，WSL 的工作目錄會自動更新：

```powershell
git add -A ; git commit -m "docs: 筆記更新" ; git push
```

WSL 端改了東西則在 Windows 側 `git pull`。

> [!warning] 這個方案的代價
> 兩份副本要記得同步；兩邊同時改同一篇會產生衝突。
> 適合「主要在 Windows 讀寫、WSL 只負責腳本與版本控制」的用法。

---

## 快速判斷用哪個

| 情境 | 用 |
| --- | --- |
| 想馬上能用、不想裝東西 | **解法一**（磁碟機代號） |
| 長期使用、在意速度 | **解法二**（WSL 內跑 Obsidian） |
| 主要在 Windows 工作、熟 git | 解法三（clone 到 Windows） |

## 相關

- [[000-00-idx-索引-首頁]]
- 之後整理進 `11-工作站環境` 的 WSL 章節
