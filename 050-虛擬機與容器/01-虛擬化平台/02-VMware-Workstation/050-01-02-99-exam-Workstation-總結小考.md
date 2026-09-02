---
title: "VMware Workstation 總結小考"
desc: "涵蓋 VMware Workstation 全章六篇的 100 題總複習：是非 50 題、選擇 50 題，附詳解與原文連結"
aliases: [Workstation 總複習, Workstation 小考, VMware Workstation 測驗]
tags: [群組/虛擬機與容器, 主題/總結小考]
category: VMware Workstation
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: []
updated: 2026-09-02
---

# VMware Workstation 總結小考

> [!abstract] 使用說明
> **題數與配分**：是非題 50 題（Q1～Q50）＋選擇題 50 題（Q51～Q100），每題 1 分，滿分 100 分。
>
> **各篇題數分布**
>
> | 來源篇章 | 題數 |
> | --- | --- |
> | [[050-01-02-01-svc-Workstation-安裝與授權]] | 15 |
> | [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] | 20 |
> | [[050-01-02-03-guide-Workstation-快照與複製]] | 20 |
> | [[050-01-02-04-guide-Workstation-網路模式]] | 20 |
> | [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] | 12 |
> | [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] | 13 |
>
> **建議作答方式**
> - 一次做完 100 題，**不查資料、不開 Workstation**，預計 70～90 分鐘。
> - 題目考的是**理解與易錯觀念**，不是背選單位置。看到「這個模式通不通」
>   「這行指令會發生什麼」時，先在腦中把封包路徑或檔案關係走一遍再作答。
> - ★★★★★ 網路那 20 題有一半是**可達性判斷**。答不出來就回去把可達性矩陣重看一次，
>   那張表是整章最常被查的一張。
> - 是非題答錯不扣分，但**錯的敘述都是現場真的有人這樣講**，答錯的請務必回原文確認。
>
> **及格標準與補讀建議**
>
> | 分數 | 判定 | 建議 |
> | --- | --- | --- |
> | **90 分以上** | 可以獨立用 Workstation 搭建與維護整套實驗環境 | 把錯的那幾題對應段落重讀即可；接著往 [[050-01-03-07-svc-PVE-叢集與高可用]] 前進，開始做巢狀 PVE |
> | **75～89 分** | 日常使用沒問題，但**出事的時候會把小問題弄成大問題** | 重點重讀 [[050-01-02-03-guide-Workstation-快照與複製]] 的〈快照不是備份〉與〈複製後一定要改的四樣東西〉、[[050-01-02-04-guide-Workstation-網路模式]] 的〈可達性矩陣〉，並把 [[050-01-02-98-trouble-Workstation-常見故障排除]] 的一頁式急救卡看熟 |
> | **60～74 分** | 觀念有明顯缺口 | 依錯題分布補：主機層看 [[050-01-02-01-svc-Workstation-安裝與授權]]、資源配置看 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]]、Tools 與時間看 [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] |
> | **60 分以下** | 尚不建議自己搭實驗環境給別人用 | 從 [[050-01-02-00-idx-Workstation-VMware-Workstation]] 的篇章順序重走一遍，每篇的「完整實戰範例」都親手做過再回來作答 |
>
> **★★★★ 答案在下方兩個摺疊區塊裡，先自己作答完再展開。** 直接看答案的複習效果接近零 ——
> 這一章的每一個陷阱，都是有人真的把 VM 弄壞過才寫進來的。

## 是非題（50 題）

Q1. 在 Windows 上啟用 WSL 2 會透過「虛擬機器平台」拉起 Hyper-V 層，因此它和 Hyper-V 角色一樣會和 Workstation 搶硬體虛擬化。

Q2. 要在 Windows 上徹底關掉 Hyper-V 層，只要把 Hyper-V 角色停用就夠了，不需要再動 `bcdedit`。

Q3. Workstation Player 也有快照管理員與複製精靈，只是選單位置和 Pro 不同。

Q4. 較新版 Workstation 可以在 Hyper-V 存在時以共存模式運作，VM 開得起來，但效能明顯較差，而且巢狀虛擬化通常不可用或極不穩。

Q5. Linux 主機升級核心之後，Workstation 的 `vmmon`／`vmnet` 模組要重新編譯，否則會出現 `Could not open /dev/vmmon`。

Q6. 在開啟 Secure Boot 的 Linux 主機上，只要 `vmware-modconfig` 編譯成功，模組就一定會被載入。

Q7. 機關配發、受網域 GPO 管控的電腦，只要技術上關得掉 Credential Guard，維運人員就可以自行關閉以便安裝 Workstation。

Q8. `Get-ComputerInfo -Property "HyperVisorPresent"` 回傳 `True`，代表主機上目前有 Hypervisor 佔著硬體虛擬化。

Q9. 動態成長的虛擬磁碟，在 Guest 裡刪掉 10 GB 檔案之後，主機上的 `.vmdk` 也會跟著縮小 10 GB。

Q10. 把虛擬磁碟分割成多個檔案之後，其中一片損壞只會影響那一片的資料，其餘部分仍可讀取。

Q11. 分割成多檔的唯一實際意義，是繞過檔案系統的單檔大小限制（例如 FAT32 的 4 GB），以及讓備份工具比較好處理。

Q12. 作業系統裝好之後，把 VM 的韌體型別從 UEFI 改成 BIOS 只是換一種開機方式，系統照樣開得起來。

Q13. UEFI 對應 GPT 分割表，BIOS（Legacy）對應 MBR，而 MBR 的單一分割區上限是 2 TB。

Q14. 一台有快照的 VM，Settings → Hard Disk 的 `Expand` 按鈕會是灰色的。

Q15. 虛擬磁碟擴充只要在 Workstation 的 Settings 裡把容量調大，Guest 裡 `df` 立刻就會看到變大。

Q16. 用 Ubuntu Server 安裝程式的 guided LVM 選項裝完，根邏輯磁區通常只拿到磁碟的一部分空間，需要自己 `lvextend` 才會用滿。

Q17. 虛擬磁碟類型選 NVMe 一定比 SCSI 好，因為效能較高，而且所有安裝程式都認得。

Q18. 把 VM 資料夾放在 OneDrive／Dropbox 的同步範圍內是可以的，同步軟體只會在檔案不變時才上傳。

Q19. 快照是一種備份，只要有快照，主機硬碟壞掉也救得回來。

Q20. 快照的差異磁碟和基礎磁碟放在同一個資料夾、同一顆碟，所以它們會一起壞、一起遺失。

Q21. 連結複製出來的 VM 可以直接 `File → Export to OVF` 匯出，帶到另一台電腦使用。

Q22. 連結複製完全依賴來源 VM，來源被刪除、改名或搬移之後，複本會報 `Cannot open the disk ... or one of the snapshot disks it depends on`。

Q23. 完整複製的建立時間比連結複製長，而且初始佔用空間大致等同來源 VM 的實際用量。

Q24. 刪除快照的動作實際上是把差異磁碟合併回基礎磁碟，做完之後那個還原點就永久消失了。

Q25. 刪除快照時 VM 卡住很久看似當機，應該立刻強制關閉電源以免它把主機拖垮。

Q26. 在 VM 開機中拍、而且沒有勾「記憶體」的快照，回復之後對 Guest 而言等同於一次硬斷電。

Q27. 從範本複製出一台新 VM 之後，只要把 hostname 改掉就不會和來源機器打架。

Q28. Workstation Player 沒有 Clone 功能，但可以用手動複製整個 VM 資料夾的方式達到等同完整複製的效果。

Q29. NAT 模式下，主機自己也連不進 VM，一定要先設埠轉發才行。

Q30. NAT 模式下，「主機以外的其他電腦」要連進 VM 裡的服務，必須設 NAT 埠轉發。

Q31. Host-only 模式的 VM 連得到主機，但連不到外網，所以不能直接 `apt update`。

Q32. LAN Segment 是四種做法裡隔離程度最高的，連主機都碰不到它，而且沒有 DHCP。

Q33. 一台在 VMnet1 的 VM 和一台在 VMnet8 的 VM，預設情況下互相 ping 得到。

Q34. NAT 網段裡 `192.168.x.1` 是預設閘道，Netplan 的 `via` 應該填這個位址。

Q35. NAT 網段裡 `192.168.x.254` 是 DHCP 伺服器，而預設動態範圍是 `.128`–`.254`，設固定 IP 時應該避開。

Q36. Bridged 模式在無線網卡上常常拿不到 IP，典型原因是無線 AP 只允許一個 MAC，或有 802.1X 認證。

Q37. NAT 埠轉發的規則指向 VM 的 IP，所以 VM 用 DHCP 也沒關係，Workstation 會自動追蹤 IP 變化。

Q38. 要在自訂 VMnet 上練習架設 DHCP 伺服器時，必須先在虛擬網路編輯器把該網段的 `Use local DHCP service` 取消勾選，否則兩個 DHCP 會打架。

Q39. Windows Guest 也可以改裝 open-vm-tools，效果和 Linux 一樣，還能跟著系統更新。

Q40. Linux Guest 的建議做法是安裝發行版套件庫裡的 `open-vm-tools`，而不是掛 ISO 安裝原廠 VMware Tools。

Q41. 在 Workstation 裡設好共享資料夾之後，Linux Guest 的 `/mnt/hgfs` 會由 open-vm-tools 自動掛載，不需要另外處理。

Q42. 把 HGFS 共享寫進 `/etc/fstab` 時，檔案系統型別要寫 `fuse.vmhgfs-fuse`，寫成舊的 `vmhgfs` 會得到 `unknown filesystem type`。

Q43. HGFS 走的是 TCP/IP，所以 VM 網路不通的時候共享資料夾也一定不能用。

Q44. 跑完 `vmware-toolbox-cmd timesync disable` 之後，VMware Tools 就完全不會再改 Guest 的時間了。

Q45. 主機上所有執行中 VM 的 vCPU 總和，應該不超過主機的實體核心數，而且計算時不把超執行緒算進去。

Q46. 給 VM 配 16 GB 記憶體但它只用 2 GB 時，Workstation 會把沒用到的 14 GB 還給主機，所以配多一點沒有壞處。

Q47. 要在 VM 裡跑 KVM 或 Proxmox VE，`.vmx` 裡必須有 `vhv.enable = "TRUE"`，對應 GUI 的 `Virtualize Intel VT-x/EPT or AMD-V/RVI`。

Q48. 手動編輯 `.vmx` 時，VM 只要處於 Suspend 狀態就可以改，存檔後設定會生效。

Q49. 只要在主機端跑 `vmware-vdiskmanager -k`，就能把動態成長磁碟裡的垃圾空間縮回來，不需要在 Guest 裡做任何事。

Q50. 磁碟壓縮的前提是 VM 完全關機、而且沒有任何快照，否則壓縮選單會是灰色的或直接失敗。

> [!question]- 是非題答案（Q1～Q50）
> **Q1. ○**
> ★★★★★ 這是 Windows 主機上最常被忽略的一項。WSL2 靠「虛擬機器平台
> （Virtual Machine Platform）」運作，而那個功能就會啟用 Hyper-V 層。
> Docker Desktop 的 WSL2 後端也是同一條路徑。
> → 詳見 [[050-01-02-01-svc-Workstation-安裝與授權]] 的〈與 Hyper-V／WSL2 共存〉
>
> **Q2. ✗**
> ★★★★★ 三件事都要做才算數：停用 `Microsoft-Hyper-V-All`、停用
> `VirtualMachinePlatform`、`bcdedit /set hypervisorlaunchtype off`，然後**重開機**。
> 少任何一項，`HyperVisorPresent` 都可能還是 `True`。
> → 詳見 [[050-01-02-01-svc-Workstation-安裝與授權]] 的〈與 Hyper-V／WSL2 共存〉
>
> **Q3. ✗**
> ★★★★ 「找不到快照／複製選單」的標準答案就是「你裝到的是 Player 不是 Pro」。
> Player 沒有這兩個功能，不是藏在別的地方。
> → 詳見 [[050-01-02-01-svc-Workstation-安裝與授權]] 的〈Workstation 產品線：Pro 與 Player〉
>
> **Q4. ○**
> ★★★★★ 共存模式是「Workstation 變成 Hyper-V 之上的客人」。
> 能開輕量 VM，但本手冊後面要跑 PVE／KVM，所以建議走「關掉 Hyper-V 層」那條路。
> → 詳見 [[050-01-02-01-svc-Workstation-安裝與授權]] 的〈與 Hyper-V／WSL2 共存〉
>
> **Q5. ○**
> ★★★★ 這是 Linux 主機每次核心升級都要處理的事：
> `sudo vmware-modconfig --console --install-all`，Secure Boot 環境還要重新簽章。
> → 詳見 [[050-01-02-01-svc-Workstation-安裝與授權]] 的〈Linux 主機：安裝步驟〉
>
> **Q6. ✗**
> ★★★★★ 編得過不等於載得進去。Secure Boot 會拒絕未簽章模組，
> `dmesg` 會出現 `Loading of unsigned module is rejected`。
> 解法是 `sign-file` 簽章＋`mokutil --import`，**優先簽章而不是關 Secure Boot**。
> → 詳見 [[050-01-02-01-svc-Workstation-安裝與授權]] 的〈常見錯誤與排錯〉
>
> **Q7. ✗**
> ★★★★★ Credential Guard 是防止憑證竊取（如 pass-the-hash）的機制，
> 在受管控的機關電腦上關閉它可能違反內部資安基準。
> 正確做法是**申請一台專用實驗主機**，而不是把日常辦公機的防護關掉。
> → 詳見 [[050-01-02-01-svc-Workstation-安裝與授權]] 的〈安全性注意事項〉
>
> **Q8. ○**
> ★★★★★ 這一句是 Windows 主機排錯的分水嶺：`True` 就先去關 Hyper-V 層，
> 不要浪費時間查別的。巢狀虛擬化的第一個前提也是它必須為 `False`。
> → 詳見 [[050-01-02-01-svc-Workstation-安裝與授權]] 的〈速查表〉
>
> **Q9. ✗**
> ★★★★★ 動態磁碟**只會長，不會自動縮**。Guest 刪檔只是把區塊標記成可用，
> `.vmdk` 完全不知道。這是「主機磁碟莫名被吃光」最常見的原因之一。
> → 詳見 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] 的〈虛擬磁碟：兩組互相獨立的選擇〉
>
> **Q10. ✗**
> ★★★ 分割不等於容錯。分成 20 片、壞掉一片，整顆虛擬磁碟一樣讀不回來。
> → 詳見 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] 的〈虛擬磁碟：兩組互相獨立的選擇〉
>
> **Q11. ○**
> ★★★★ 就是這兩個理由。主機是 NTFS／ext4／APFS 而且不打算搬機時，
> 用單一檔案反而少一層對應、效能略好。
> → 詳見 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] 的〈虛擬磁碟：兩組互相獨立的選擇〉
>
> **Q12. ✗**
> ★★★★★ 開機載入器（GRUB／Windows Boot Manager）是**按照韌體型別安裝**的。
> 改過去就會停在 `Operating System not found` 或掉進 UEFI Shell。改回去才會好。
> → 詳見 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] 的〈UEFI 還是 BIOS〉
>
> **Q13. ○**
> ★★★ 這也是本手冊主線選 UEFI 的理由之一：GPT 沒有 2 TB 限制，
> 也沒有主分割區只能四個的限制。
> → 詳見 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] 的〈UEFI 還是 BIOS〉
>
> **Q14. ○**
> ★★★★ 有快照就不能擴充，必須先在快照管理員 Delete All Snapshots（會合併回主磁碟）。
> 同樣的限制也套用在磁碟壓縮與匯出 OVF 上。
> → 詳見 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] 的〈擴充磁碟的完整兩層流程〉
>
> **Q15. ✗**
> ★★★★ 擴充是**兩層**的事：Workstation 那一層把虛擬磁碟變大，
> Guest 那一層還要 `growpart` → `pvresize` → `lvextend` → `resize2fs`／`xfs_growfs`。
> 少做第二層，`df` 當然不會變。
> → 詳見 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] 的〈擴充磁碟的完整兩層流程〉
>
> **Q16. ○**
> ★★★★ 典型症狀是裝完 `df -h /` 只有約 19 GB。
> 補救：`sudo lvextend -l +100%FREE /dev/ubuntu-vg/ubuntu-lv && sudo resize2fs …`。
> → 詳見 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] 的〈常見錯誤與排錯〉
>
> **Q17. ✗**
> ★★★ NVMe 效能較好，但**部分較舊的 Linux 發行版與 Windows 安裝程式認不到 NVMe**，
> 會卡在「找不到磁碟」。要裝舊系統時選 **SCSI** 最不會出事。
> → 詳見 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] 的〈控制器與虛擬裝置型別〉
>
> **Q18. ✗**
> ★★★★ `.vmdk` 是一直在變動的大檔，同步軟體會不斷開檔上傳，
> 典型症狀是偶爾出現 `.lck` 相關的鎖檔錯誤。
> **把整個 VM 資料夾搬出同步範圍，並在同步軟體排除該路徑。**
> → 詳見 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] 的〈常見錯誤與排錯〉
>
> **Q19. ✗**
> ★★★★★ 這是整章最重要的一句話。快照和基礎磁碟放在同一顆碟，
> **磁碟壞掉時 base 與所有快照一起沒**。重要的 VM 要複製到另一顆碟或外部儲存。
> → 詳見 [[050-01-02-03-guide-Workstation-快照與複製]] 的〈快照不是備份〉
>
> **Q20. ○**
> ★★★★★ 同上一題的另一面。快照「和原始資料分開存放？否」「可以獨立還原？否」
> 「磁碟壞了救得回來？不行」—— 這三個「否」就是它不能當備份的全部理由。
> → 詳見 [[050-01-02-03-guide-Workstation-快照與複製]] 的〈快照不是備份〉
>
> **Q21. ✗**
> ★★★★ 連結複製**不能匯出**，因為它沒有完整的磁碟資料。
> 要匯出得先轉成完整複製，而且要先 Delete All Snapshots。
> → 詳見 [[050-01-02-03-guide-Workstation-快照與複製]] 的〈複製：連結複製 vs 完整複製〉
>
> **Q22. ○**
> ★★★★★ 複本的 `.vmdk` 描述檔裡記著 `parentFileNameHint`，指向來源的路徑與檔名。
> 來源一動就斷。解法是把來源還原到原路徑原名稱，或手動改那個欄位。
> → 詳見 [[050-01-02-03-guide-Workstation-快照與複製]] 的〈常見錯誤與排錯〉
>
> **Q23. ○**
> ★★★★ 連結複製是「秒建、初始幾百 MB、完全依賴來源」；
> 完整複製是「分鐘、佔用等同來源用量、不依賴來源、可搬走可匯出」。
> → 詳見 [[050-01-02-03-guide-Workstation-快照與複製]] 的〈複製：連結複製 vs 完整複製〉
>
> **Q24. ○**
> ★★★★★ 「刪快照」聽起來像是清垃圾，其實是**合併**。合併完那個還原點就沒了，
> 而且合併需要額外空間、可能跑很久。
> → 詳見 [[050-01-02-03-guide-Workstation-快照與複製]] 的〈刪除快照〉
>
> **Q25. ✗**
> ★★★★★ 剛好相反：**不要強制關閉、不要斷電，讓它跑完**。
> delta 檔案很大時就是要跑那麼久，中斷合併會讓 VM 開不起來。
> 正確的預防是不要讓快照鏈長成那樣。
> → 詳見 [[050-01-02-03-guide-Workstation-快照與複製]] 的〈快照鏈太長的後果與清理時機〉
>
> **Q26. ○**
> ★★★★ 沒含記憶體的快照只記錄磁碟狀態，回復等同硬斷電，
> 資料庫可能因此損毀要跑修復。要避免就**關機後再拍**，或拍的時候勾記憶體。
> → 詳見 [[050-01-02-03-guide-Workstation-快照與複製]] 的〈含記憶體的快照〉
>
> **Q27. ✗**
> ★★★★★ 要改**四樣**：hostname、machine-id、SSH host key、靜態 IP。
> 少改 machine-id 會讓 DHCP 發同一個 IP 給兩台；
> 少改 host key 會讓兩台的 SSH 指紋一模一樣。
> → 詳見 [[050-01-02-03-guide-Workstation-快照與複製]] 的〈複製後一定要改的四樣東西〉
>
> **Q28. ○**
> ★★★ Player 沒有 Clone 精靈，但關機後手動複製整個資料夾就是完整複製。
> 只是複製後的四項識別碼一樣要自己改。
> → 詳見 [[050-01-02-03-guide-Workstation-快照與複製]] 的〈常見錯誤與排錯〉
>
> **Q29. ✗**
> ★★★★★ 這是可達性矩陣裡最容易搞混的一格。
> **主機身上有一張 VMnet8 網卡，跟 VM 在同一個網段，可以直接連進去。**
> 埠轉發是給「主機以外的機器」用的。
> → 詳見 [[050-01-02-04-guide-Workstation-網路模式]] 的〈可達性矩陣〉
>
> **Q30. ○**
> ★★★★★ 這才是埠轉發的用途。而且要通還得再過一關：**主機的防火牆**。
> → 詳見 [[050-01-02-04-guide-Workstation-網路模式]] 的〈NAT 埠轉發〉
>
> **Q31. ○**
> ★★★★ Host-only 的定義就是「關在房間裡，只跟主機講話」，
> `VM → 外網` 那一格是 ✗。要裝套件就得改模式或走主機轉送。
> → 詳見 [[050-01-02-04-guide-Workstation-網路模式]] 的〈Host-only（僅限主機）〉
>
> **Q32. ○**
> ★★★★★ LAN Segment 連 `VM ↔ 主機` 都是 ✗，也沒有 DHCP（必須手設固定 IP）。
> 分析惡意程式、跑可疑檔案要用的就是它，不是 Host-only。
> → 詳見 [[050-01-02-04-guide-Workstation-網路模式]] 的〈自訂 VMnet 與 LAN Segment〉
>
> **Q33. ✗**
> ★★★★★ **不同 VMnet 之間預設不通**，就像插在兩台沒有互連的交換器上。
> 要通只有一個辦法：放一台有兩張網卡的 VM 當路由器。
> → 詳見 [[050-01-02-04-guide-Workstation-網路模式]] 的〈可達性矩陣〉
>
> **Q34. ✗**
> ★★★★★ `.1` 是**主機的 VMnet8 網卡**，不是閘道。閘道與 DNS 轉送是 `.2`。
> 「ping 得到主機卻上不了網」十次有九次就是這個錯。
> → 詳見 [[050-01-02-04-guide-Workstation-網路模式]] 的〈查出目前的 NAT 網段是什麼〉
>
> **Q35. ○**
> ★★★★ 三個固定位址背起來：`.1` 主機網卡、`.2` 閘道＋DNS、`.254` DHCP。
> 設固定 IP 建議用 `.10`–`.99`，避開動態範圍。
> → 詳見 [[050-01-02-04-guide-Workstation-網路模式]] 的〈NAT 網段三個固定位址〉
>
> **Q36. ○**
> ★★★★★ 無線環境下 Bridged 幾乎不可靠，**改用 NAT 是唯一穩定的做法**。
> 更嚴重的版本是有線環境的埠安全把埠 `err-disable`，連主機都跟著斷網。
> → 詳見 [[050-01-02-04-guide-Workstation-網路模式]] 的〈常見錯誤與排錯〉
>
> **Q37. ✗**
> ★★★★★ **埠轉發的前提是 VM 固定 IP。** VM 用 DHCP，重開機換了 IP，
> 規則就指到一個空位址上，症狀是主機 `curl 127.0.0.1:8080` 完全不通。
> → 詳見 [[050-01-02-04-guide-Workstation-網路模式]] 的〈NAT 埠轉發〉
>
> **Q38. ○**
> ★★★★★ 不關的話 VMware 的 DHCP 會搶答，你自己架的那台永遠發不出 IP。
> 位置在虛擬網路編輯器 → 選該 VMnet → 取消 `Use local DHCP service`。
> → 詳見 [[050-01-02-04-guide-Workstation-網路模式]] 的〈常見錯誤與排錯〉
>
> **Q39. ✗**
> ★★★★★ open-vm-tools **不提供 Windows 版**。Windows Guest 只能裝原廠 VMware Tools，
> 沒有第二個選擇。方向剛好和 Linux 相反。
> → 詳見 [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] 的〈VMware Tools 與 open-vm-tools 的差別〉
>
> **Q40. ○**
> ★★★★★ 理由是模組已經進入 Linux 主線核心，**跟著核心一起更新，不會編不過**，
> 而且 `apt upgrade` 就順便更新了。誤裝原廠版的典型後果是升級核心後網路卡消失。
> → 詳見 [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] 的〈VMware Tools 與 open-vm-tools 的差別〉
>
> **Q41. ✗**
> ★★★★★ open-vm-tools 走的是使用者空間的 `vmhgfs-fuse`，**不會自動掛載**。
> 舊版的 `vmhgfs` 核心模組才會。「共享設好了但 `/mnt/hgfs` 是空的」就是這個原因。
> → 詳見 [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] 的〈HGFS：共享資料夾到底怎麼運作〉
>
> **Q42. ○**
> ★★★★★ 而且那一行一定要加 `nofail`，否則掛不起來時整台會停在
> `Give root password for maintenance:`。寫完務必先 `sudo mount -a` 驗一次。
> → 詳見 [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] 的〈共享資料夾：Linux Guest 端與 `/mnt/hgfs`〉
>
> **Q43. ✗**
> ★★★★ HGFS 走的是 Host 與 Guest 之間的 **VMCI 通道**，不走 TCP/IP。
> 所以 VM 網路完全不通時共享資料夾照樣能用 —— 這在進去救網路設定時特別有用。
> → 詳見 [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] 的〈HGFS：共享資料夾到底怎麼運作〉
>
> **Q44. ✗**
> ★★★★★ 這一步幾乎所有教學都漏掉：`timesync disable` 只關掉**週期性**同步，
> 「恢復暫停」「還原快照」「Tools 啟動」這些**事件觸發**的一次性校時仍然會做。
> 要全關必須在 `.vmx` 補上那六個 `time.synchronize.*` 參數。
> → 詳見 [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] 的〈時間同步的坑〉
>
> **Q45. ○**
> ★★★★★ 超過之後 Hypervisor 要排隊調度（co-scheduling），**反而變慢**。
> 這也是「配 8 vCPU 比 2 vCPU 還慢」的原因。
> → 詳見 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] 的〈CPU 配置準則〉
>
> **Q46. ✗**
> ★★★★★ Workstation 預設會**盡量把 VM 記憶體放進主機實體 RAM**，配多少大致就佔多少。
> 配到主機只剩 1～2 GB，Windows 會開始 swap，**整台電腦（連滑鼠）一起卡**。
> 給主機留 4～6 GB 是硬底線。
> → 詳見 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] 的〈記憶體配置準則〉
>
> **Q47. ○**
> ★★★★★ GUI 位置是 `VM → Settings → Processors → Virtualization engine`。
> 但它只是三個前提之一：Host 的 `HyperVisorPresent` 要是 `False`、
> CPU 要支援 EPT／RVI、虛擬硬體版本要夠新。
> → 詳見 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] 的〈巢狀虛擬化〉
>
> **Q48. ✗**
> ★★★★ 必須**完全關機**，不是 Suspend。Workstation 關閉時會把記憶體裡的設定寫回 `.vmx`，
> 把你的修改蓋掉。典型症狀是「改了 `.vmx` 但重開後設定不見了」。
> → 詳見 [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] 的〈常見錯誤與排錯〉
>
> **Q49. ✗**
> ★★★★★ **只做 Host 端壓縮沒有用**，因為 Host 分不出哪些區塊是垃圾。
> 必須先在 Guest 裡把可用空間寫成 0（`vmware-toolbox-cmd disk shrink /`），
> Host 才認得出來，再跑 `vmware-vdiskmanager -k`。
> → 詳見 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] 的〈磁碟膨脹與壓縮〉
>
> **Q50. ○**
> ★★★★★ 有快照或沒完全關機，壓縮選單就是灰的。
> 要壓縮就得先 Delete All Snapshots —— 而那是**不可逆**的，做之前先確認不再需要那些還原點，
> 並完整複製一份 VM 目錄。
> → 詳見 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] 的〈磁碟膨脹與壓縮〉

## 選擇題（50 題）

Q51. Windows 主機上開 VM 跳出 `VMware Workstation and Hyper-V are not compatible.`。下列哪一組處置最完整？
(A) 只在控制台停用 Hyper-V 角色 (B) 重灌 Workstation (C) 停用 Hyper-V 角色與虛擬機器平台、`bcdedit /set hypervisorlaunchtype off`，然後重開機並用 `HyperVisorPresent` 驗證 (D) 把 VM 的記憶體調小

Q52. 一台從沒裝過 Hyper-V 管理員的開發機，`HyperVisorPresent` 卻是 `True`。最可能的元凶是？
(A) 防毒軟體 (B) WSL 2 或 Docker Desktop 帶起來的「虛擬機器平台」，以及核心隔離的記憶體完整性 (C) Workstation 自己 (D) 主機的 BIOS 版本太舊

Q53. Linux 主機上 `vmware-modconfig` 顯示編譯成功，但 `lsmod` 看不到 `vmmon`。該先查什麼？
(A) `/etc/fstab` (B) `dmesg` 有沒有 `Loading of unsigned module is rejected`，也就是 Secure Boot 拒絕未簽章模組 (C) 磁碟空間 (D) 重裝 Workstation

Q54. 機關配發的筆電由網域 GPO 強制啟用 Credential Guard，關掉之後重開機又變回 `True`。最恰當的做法是？
(A) 寫一個排程每次開機都關掉它 (B) 改用破解版 Workstation (C) 這是政策層問題，找資安單位處理，或申請一台專用實驗主機 (D) 改用 Player 就不會有這個問題

Q55. 同事說他的 Workstation 裡「找不到快照和複製的選單」。最可能的原因是？
(A) 選單被隱藏了 (B) 授權過期 (C) 他裝的是 Workstation Player，這兩個功能只有 Pro 才有 (D) VM 版本太舊

Q56. Windows 主機上 VM 開機跳出「無法連線到虛擬機」或權限錯誤。最先該檢查什麼？
(A) `VMware Authorization Service`（`VMAuthdService`）是否啟動 (B) 主機防火牆 (C) VM 的記憶體設定 (D) 網路模式

Q57. 開發人員一定要保留 WSL2 與 Docker Desktop，同時又想用 Workstation。下列敘述何者正確？
(A) 兩者完全不能共存 (B) 可以走共存模式，VM 開得起來但效能較差，且巢狀虛擬化通常不可用，所以做不了本手冊的 PVE／KVM 章節 (C) 共存模式效能和原生一樣 (D) 只要 CPU 夠強就沒有差別

Q58. 自訂精靈在磁碟頁同時問「Allocate all disk space now」與「Split virtual disk into multiple files」。下列敘述何者正確？
(A) 這是同一個選項的兩種寫法 (B) 這是兩個互相獨立的選擇：前者決定預先配置或動態成長，後者決定單檔或分割 (C) 勾了前者就不能勾後者 (D) 分割一定要搭配預先配置

Q59. 你要把一台實驗 VM 拷到 exFAT 隨身碟帶去別的辦公室。建立磁碟時該怎麼選？
(A) 單一檔案，效能較好 (B) 預先配置＋單一檔案 (C) 分割成多個檔案，才不會撞到單檔大小限制 (D) 怎麼選都可以，複製時會自動切割

Q60. 一台裝好的 Ubuntu VM 昨天還開得起來，你今天改過設定之後開機顯示 `Operating System not found`。最該先看哪裡？
(A) 網路設定 (B) 記憶體大小 (C) Settings → Options → Advanced 的韌體型別是不是被從 UEFI 改成 BIOS（或反過來） (D) CPU 核心數

Q61. 新建的 VM 開機停在 `UEFI Interactive Shell` 的 `Shell>` 提示。最可能的原因是？
(A) CPU 不支援虛擬化 (B) 找不到可開機媒體：ISO 沒掛，或 CD/DVD 沒勾 `Connect at power on` (C) 記憶體不足 (D) 磁碟類型選錯

Q62. Ubuntu Server 裝完之後 `df -h /` 只顯示約 19 GB，但你明明配了 40 GB。正確處置是？
(A) 重灌並取消 LVM (B) 擴大虛擬磁碟到 80 GB (C) `sudo lvextend -l +100%FREE /dev/ubuntu-vg/ubuntu-lv` 之後 `sudo resize2fs …`，把剩下的空間吃滿 (D) 這是正常的，不用處理

Q63. 執行 `sudo growpart /dev/sda2` 得到 `FAILED: /dev/sda2: does not exist`。原因是？
(A) 分割區真的不存在 (B) 需要先卸載該分割區 (C) 參數格式錯了，應該是「磁碟 空格 分割號」，寫成 `sudo growpart /dev/sda 2` (D) `growpart` 不支援 GPT

Q64. Settings → Hard Disk 的 `Expand` 是灰色的。原因與處置是？
(A) VM 開機中，關機即可 (B) 磁碟是預先配置型，不能擴充 (C) 這台 VM 有快照，必須先 Delete All Snapshots 才能擴充 (D) 需要 Pro 版才有這個功能

Q65. 你在 Workstation 把虛擬磁碟從 40 GB 擴到 80 GB，開機後 Guest 的 `df` 完全沒變。為什麼？
(A) 需要重開機兩次 (B) 擴充是兩層的事，Guest 端還要 `growpart` → `lvextend` → `resize2fs`／`xfs_growfs` (C) 擴充失敗了 (D) 要先做快照

Q66. 你透過 SSH 遠端改 VM 的 Netplan，`netplan apply` 之後就斷線連不回去。下列做法最正確？
(A) 重開 VM 就會好 (B) 從 Workstation 的主控台視窗登入修正，而且下次改網路一律用 `netplan try`（沒確認會自動還原） (C) 刪掉 VM 重建 (D) 改用 DHCP 就不會有這個問題

Q67. 要在 VM 裡裝一套比較舊的作業系統，安裝程式一直說「找不到磁碟」。最可能的原因與處置是？
(A) 磁碟容量太大，調小即可 (B) 虛擬磁碟類型是 NVMe，舊安裝程式沒有驅動；改用 SCSI 重建虛擬機 (C) 要先在 BIOS 開 AHCI (D) ISO 檔損毀

Q68. 關於「快照」與「備份」，下列敘述何者正確？
(A) 快照可以取代備份，因為隨時可以回復 (B) 快照和基礎磁碟放在同一顆碟、無法獨立還原、也沒有保留策略，磁碟壞掉就一起沒；備份才是分開存放、可獨立還原的一份 (C) 兩者差別只在速度 (D) 快照有版本與保留策略，比備份更方便

Q69. 主機碟快滿了，你發現某台 VM 的資料夾裡有 `-000001.vmdk` 一路排到 `-000009.vmdk`。正確處置是？
(A) 直接刪掉 `-000001` 到 `-000008`，只留最後一個 (B) 開快照管理員檢視這些快照、確認不需要之後 Delete（合併回 base），並確保合併過程中主機有足夠空間 (C) 把這些檔案搬到別的資料夾 (D) 對 `.vmdk` 做壓縮就會變小

Q70. 你要用同一台 VM 跑磁碟效能測試，測出來的數據卻忽高忽低。最可能的原因是？
(A) 測試工具有問題 (B) 記憶體太小 (C) 這台 VM 有快照，讀寫要走差異磁碟鏈；測試前應該 Delete All Snapshots 或改用完整複製 (D) vCPU 太多

Q71. 複製精靈裡 `Create a linked clone` 是灰色的。原因是？
(A) 沒有 Pro 授權 (B) 來源 VM 沒有任何快照，或你選了 `The current state`；先關機拍一個快照，複製時選 `An existing snapshot` (C) 主機空間不足 (D) 來源 VM 太大

Q72. 一台連結複製出來的 VM 突然開不起來，訊息是 `Cannot open the disk ... or one of the snapshot disks it depends on`。最可能發生了什麼？
(A) 主機記憶體不足 (B) 網路模式被改了 (C) 來源 VM 被刪除、改名或搬移了，連結複製完全依賴它 (D) VMware Tools 過期

Q73. 兩台從同一個範本複製出來的 Ubuntu VM，一起開機時 DHCP 一直發同一個 IP 給它們。最可能的原因是？
(A) DHCP 伺服器壞了 (B) 兩台的 `/etc/machine-id` 相同，被當成 DHCP client identifier，伺服器認為是同一台 (C) 兩台的 hostname 相同 (D) VMnet8 的位址池太小

Q74. 你發現兩台複製出來的機器 SSH 主機指紋一模一樣。最正確的處置是？
(A) 這是正常的，不用處理 (B) 改 hostname 就會變 (C) `sudo rm -f /etc/ssh/ssh_host_* && sudo ssh-keygen -A && sudo systemctl restart ssh`，讓每台各自產生自己的 host key (D) 重灌其中一台

Q75. 連到一台剛重建的實驗機，SSH 報 `REMOTE HOST IDENTIFICATION HAS CHANGED!`。正確的解讀是？
(A) 一定被入侵了，立刻斷網 (B) 這個 IP 換了一台機器，host key 當然不同；確認是自己重建的之後 `ssh-keygen -R <IP>` 清掉舊記錄再連 (C) SSH 服務壞了 (D) 要把 `StrictHostKeyChecking` 永久關掉

Q76. 你想把一台調好的實驗機交給同事，讓他在自己的電腦上使用。該怎麼做？
(A) 做一個連結複製給他 (B) 把快照檔案傳給他 (C) 先 Delete All Snapshots，再做完整複製或 `File → Export to OVF`；連結複製不能搬也不能匯出 (D) 把 `.vmx` 傳給他就好

Q77. 刪除一個很大的快照時，VM 卡住超過十分鐘看似當機。正確做法是？
(A) 立刻強制關閉電源，避免拖垮主機 (B) 這是 delta 檔案在合併回 base，不要強制關閉、不要斷電，讓它跑完；並確保主機有足夠空間 (C) 直接刪掉 VM 資料夾重來 (D) 重啟 `VMAuthdService`

Q78. 一台 NAT 模式的 VM 上跑著 Nginx（監聽 `0.0.0.0:80`），VM 的 IP 是 `192.168.100.50`。你在**主機**的瀏覽器打 `http://192.168.100.50` —— 通不通？
(A) 不通，NAT 一定要先設埠轉發 (B) 通，主機身上有一張 VMnet8 網卡與 VM 同網段，可以直接連 (C) 只有設了 Host-only 才通 (D) 要看主機防火牆有沒有開 80

Q79. 同一台 NAT 模式的 VM，換成**同事的電腦**連 `http://192.168.100.50` —— 通不通？該怎麼辦？
(A) 通，NAT 會自動轉發 (B) 不通；要在虛擬網路編輯器設 NAT 埠轉發，並且在主機防火牆放行該埠，同時 VM 必須是固定 IP (C) 不通，只能改成 Bridged (D) 通，只要同事和你在同一個網段

Q80. 一台 Host-only 模式的 VM，執行 `sudo apt update` —— 會發生什麼？
(A) 正常更新 (B) 失敗，Host-only 的 `VM → 外網` 是不通的 (C) 要先設埠轉發 (D) 要先關掉 VMware DHCP

Q81. 兩台 VM 都掛在同一個 LAN Segment 上。下列敘述何者正確？
(A) 兩台互通，但都連不到主機、也連不到外網，而且該網段沒有 DHCP，要手設固定 IP (B) 兩台互通，也連得到主機 (C) 兩台不互通 (D) 和 Host-only 完全一樣

Q82. VM-A 在 VMnet1（Host-only）、VM-B 在 VMnet8（NAT），兩台都在同一台主機上。VM-A `ping` VM-B —— 通不通？
(A) 通，同一台主機上的 VM 一定互通 (B) 不通；不同 VMnet 之間預設不通，就像插在兩台沒互連的交換器上，要通得放一台雙網卡的 router VM (C) 通，但要先關防火牆 (D) 要看主機的路由表

Q83. NAT 模式的 VM `ping` 得到 `192.168.100.1` 卻上不了網。最可能的原因是？
(A) DNS 設錯 (B) 網路卡沒 Connected (C) 預設閘道被設成 `.1`（主機的 VMnet8 網卡）而不是 `.2`（NAT 裝置） (D) VMware NAT Service 沒跑

Q84. VM 裡 `ping 1.1.1.1` 通，但 `apt update` 失敗。該往哪個方向查？
(A) 預設路由 (B) 網路模式 (C) 純 DNS 問題：檢查 `nameservers` 是否有設（NAT 下可用 `.2`），用 `getent hosts` 與 `resolvectl status` 確認 (D) 主機防火牆

Q85. 在機關辦公室把 VM 改成 Bridged 之後，不只 VM 沒網路，連主機自己都斷網了。最可能的原因與第一動作是？
(A) 網路線鬆了，重插 (B) 交換器的埠安全偵測到第二個 MAC 把埠 `err-disable`；立刻改回 NAT，並請網管重新啟用該埠 (C) DHCP 位址池滿了，等一下就好 (D) 主機網卡驅動壞了，重裝驅動

Q86. 埠轉發規則設好了，但主機上 `curl 127.0.0.1:8080` 完全不通。最可能的原因是？
(A) 虛擬網路編輯器要重開 (B) VM 用 DHCP，重開機後 IP 變了，轉發規則指到一個空位址；埠轉發的前提是 VM 固定 IP (C) 需要重開主機 (D) NAT 不支援埠轉發

Q87. VM 裡 `curl 127.0.0.1` 拿得到網頁，但從主機連就不通。該先下哪個指令？
(A) `ip route` (B) `ping` 主機 (C) `ss -tlnp | grep ':80'`，確認服務是監聽 `0.0.0.0` 還是只監聽 `127.0.0.1` (D) `systemctl restart networking`

Q88. Linux Guest 裡 `/mnt/hgfs` 存在但完全是空的，Host 端共享資料夾也確定設好了。原因與處置是？
(A) 共享資料夾壞了，重設一次 (B) open-vm-tools 走 FUSE，不會自動掛載；要 `sudo vmhgfs-fuse .host:/ /mnt/hgfs -o allow_other`，再寫進 `/etc/fstab` (C) 要重裝 VMware Tools (D) 要重開機才會出現

Q89. 在 Guest 裡跑 `vmware-hgfsclient` 完全沒有輸出。這代表什麼？
(A) open-vm-tools 壞了 (B) `/mnt/hgfs` 沒建 (C) Host 端的共享資料夾是 Disabled，或根本沒 Add 任何一個共享 (D) FUSE 沒開 `user_allow_other`

Q90. 你把 HGFS 那一行寫進 `/etc/fstab` 但沒加 `nofail`，重開機後系統停在 `Give root password for maintenance:`。正確的救援順序是？
(A) 重灌 (B) 直接還原快照 (C) 在 maintenance shell 裡 `mount -o remount,rw /` → 編輯 `/etc/fstab` 補上 `nofail`（或先註解掉該行）→ `reboot` (D) 按 `Ctrl+D` 略過就好

Q91. 一台 Linux VM 升級核心之後開機就沒有網路卡。查下來發現前任同事曾經跑過 `vmware-install.pl`。正確處置是？
(A) 重新編譯核心 (B) `sudo /usr/bin/vmware-uninstall-tools.pl` 移除原廠 Tools，改裝 `open-vm-tools`，重開機 (C) 把網路卡型別改成 e1000 (D) 回退到舊核心就不用管了

Q92. 筆電闔上蓋子睡了一夜，早上打開發現 VM 的時間慢了八小時。最直接的原因與立即處置是？
(A) NTP 伺服器不通；換一台 NTP (B) 虛擬時鐘在 Host 睡眠期間停止推進；`sudo chronyc makestep` 立即校正，長期則設好 NTP (C) 時區設錯；`timedatectl set-timezone` (D) RTC 電池沒電；換主機板電池

Q93. 你已經跑過 `vmware-toolbox-cmd timesync disable`，但每次還原快照之後時間還是會被改掉。原因與處置是？
(A) 指令沒生效，再跑一次 (B) chrony 造成的，停掉 chrony (C) `timesync disable` 只關週期性同步，事件觸發的一次性校時仍開著；要在 `.vmx` 補上 `time.synchronize.restore = "FALSE"` 等六項，且改檔時 VM 必須完全關機 (D) 要把 Tools 移除

Q94. 一台 VM 從 2 vCPU 調成 8 vCPU 之後反而變慢，主機是 4 核心。最正確的解讀是？
(A) 記憶體不夠，要一起加 (B) vCPU 超過實體核心，Hypervisor 要排隊調度（co-scheduling 等待），反而變慢；應降回 2～4 vCPU，讓所有執行中 VM 的 vCPU 總和 ≤ 實體核心數 (C) Guest 沒裝 Tools (D) 磁碟太慢

Q95. 要在 Workstation 的 VM 裡跑 Proxmox VE。下列哪一組是必須成立的前提？
(A) 主機記憶體 64 GB 以上 (B) 使用 Bridged 網路 (C) 主機 `HyperVisorPresent` 為 `False`、CPU 支援 EPT（Intel）／RVI‑NPT（AMD）、VM 的虛擬硬體版本夠新 (D) 主機必須是 Linux

Q96. Guest 裡 `sudo kvm-ok` 顯示 `KVM acceleration can NOT be used`。最可能的兩個原因是？
(A) 記憶體太小、磁碟太小 (B) 沒勾 `Virtualize Intel VT-x/EPT`，或改 `.vmx` 時 VM 不是完全關機所以設定被蓋掉 (C) Guest 沒裝 open-vm-tools (D) 網路模式選錯

Q97. 要確認巢狀虛擬化真的生效，下列哪一組驗證最完整？
(A) 只看 Workstation 的勾選框有沒有勾 (B) 只看 `/dev/kvm` 存不存在 (C) `grep -c -E 'vmx|svm' /proc/cpuinfo` 等於 vCPU 數、`lscpu | grep -i virtual` 有 `VT-x`、`sudo kvm-ok` 顯示可用、`lsmod | grep kvm` 有 `kvm_intel`／`kvm_amd` (D) 在 VM 裡裝一台 PVE 看裝不裝得起來就好

Q98. Guest 裡 `df` 顯示只用了 8 GB，主機上的 `.vmdk` 卻已經 45 GB。正確的處置流程是？
(A) 直接在主機跑 `vmware-vdiskmanager -k` (B) 刪掉 `.vmdk` 重建 (C) 先在 Guest 清乾淨並歸零（`sudo vmware-toolbox-cmd disk shrink /`），完全關機、確認沒有快照之後，再在 Host 跑 `vmware-vdiskmanager -k` (D) 把磁碟改成預先配置

Q99. VM 執行到一半跳出「磁碟空間不足，虛擬機已暫停」，選項是 Retry 與 Abort。該怎麼做？
(A) 按 Abort，讓 VM 停下來比較安全 (B) 按 Retry 再說，不行就 Abort (C) 先到主機上清出空間，再回來按 Retry；按 Abort 等同對執行中的 Guest 硬斷電，檔案系統可能損壞 (D) 直接關掉 Workstation

Q100. 一台之前很順的 VM 突然變慢。下列哪一組是最有效率的排查順序？
(A) 先加 vCPU 和記憶體，不行再說 (B) 先重開機，不行再重灌 (C) 依序檢查：快照數量、主機碟剩餘空間、防毒是否在掃 VM 目錄、主機電源計畫是否切到省電、主機上是否有別人也在跑 VM (D) 先看 Guest 的 `top`，再決定要不要換一台主機

> [!question]- 選擇題答案（Q51～Q100）
> **Q51. (C)**
> ★★★★★ 三件事缺一不可，而且**一定要重開機再用 `HyperVisorPresent` 驗一次**。
> 只做 (A) 常常還是 `True`，因為虛擬機器平台或 VBS 還開著。
> (B) 錯：重灌不會改變硬體虛擬化被誰持有。(D) 錯：這是資源問題不是 Hypervisor 問題。
> → 詳見 [[050-01-02-01-svc-Workstation-安裝與授權]] 的〈與 Hyper-V／WSL2 共存〉
>
> **Q52. (B)**
> ★★★★★ 這兩個是「沒裝 Hyper-V 也會有 Hyper-V」的主因：
> WSL2／Docker Desktop 帶起的 `VirtualMachinePlatform`，以及新機預設可能開著的
> 核心隔離「記憶體完整性」（VBS）。
> (A)(C)(D) 都不會拉起 Hypervisor 層。
> → 詳見 [[050-01-02-01-svc-Workstation-安裝與授權]] 的〈與 Hyper-V／WSL2 共存〉
>
> **Q53. (B)**
> ★★★★★ 編得過不等於載得進去。Secure Boot 會明確在 `dmesg` 裡說它拒絕了未簽章模組。
> 解法優先是 `sign-file` 簽章＋`mokutil --import`，而不是關掉 Secure Boot。
> (A)(C)(D) 都不是這個症狀的成因。
> → 詳見 [[050-01-02-01-svc-Workstation-安裝與授權]] 的〈常見錯誤與排錯〉
>
> **Q54. (C)**
> ★★★★★ 「重開機後又變回 `True`」就是 GPO 在強制。這是政策層的事，
> 自行繞過可能違反內部資安基準。正確做法是申請專用實驗主機。
> (A) 錯：繞過管控本身就是問題。(B) 錯：破解版是機關資安事件的常見來源。
> (D) 錯：Player 一樣需要硬體虛擬化。
> → 詳見 [[050-01-02-01-svc-Workstation-安裝與授權]] 的〈安全性注意事項〉
>
> **Q55. (C)**
> ★★★★ 快照管理員與 Clone 精靈是 Pro 專屬。Player 使用者只能手動複製整個資料夾
> （等同完整複製），沒有快照可用。
> → 詳見 [[050-01-02-01-svc-Workstation-安裝與授權]] 的〈Workstation 產品線：Pro 與 Player〉
>
> **Q56. (A)**
> ★★★★ `VMAuthdService` 負責授權與 VM 存取，它沒起來就會跳權限相關錯誤。
> `Start-Service VMAuthdService` 並設為自動啟動。
> 相關的還有 `Transport (VMDB) error -14`，處理方式也是重啟這個服務。
> → 詳見 [[050-01-02-01-svc-Workstation-安裝與授權]] 的〈常見錯誤與排錯〉
>
> **Q57. (B)**
> ★★★★★ 共存模式的三個後果要記住：**可以開 VM、效能明顯較差、巢狀虛擬化通常不可用**。
> 因為本手冊後面要跑 PVE 與 KVM，所以建議關掉 Hyper-V 層。
> (A) 錯：較新版可以共存。(C)(D) 錯：共存模式的效能落差和 CPU 強弱無關。
> → 詳見 [[050-01-02-01-svc-Workstation-安裝與授權]] 的〈兩條路：共存，或關掉〉
>
> **Q58. (B)**
> ★★★★ 這兩個選項互相獨立，四種組合都合法。本手冊實驗環境建議
> **動態成長 + 分割**（建立快、佔用小、可搬到 exFAT）。
> → 詳見 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] 的〈虛擬磁碟：兩組互相獨立的選擇〉
>
> **Q59. (C)**
> ★★★★ FAT32 單檔上限 4 GB，單一檔案的 `.vmdk` 根本放不進去。
> 分割之後每片約 2 GB，就過得去。
> (A)(B) 錯：單一檔案正是放不進去的那一種。(D) 錯：複製時不會自動切割。
> → 詳見 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] 的〈虛擬磁碟：兩組互相獨立的選擇〉
>
> **Q60. (C)**
> ★★★★★ 「昨天還好、今天改過設定就 `Operating System not found`」幾乎都是韌體型別被改掉。
> 開機載入器是按韌體型別安裝的，改回原本那個就好。
> 建 VM 時把韌體型別記進 Notes 欄位可以省下很多時間。
> → 詳見 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] 的〈UEFI 還是 BIOS〉
>
> **Q61. (B)**
> ★★★★ UEFI 找不到任何可開機媒體就會掉進 Shell；有些情況會改成一直重試 PXE。
> 檢查 CD/DVD 的 `Connected` 與 `Connect at power on`，以及 ISO 路徑。
> → 詳見 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] 的〈常見錯誤與排錯〉
>
> **Q62. (C)**
> ★★★★ guided LVM 只配一部分空間給根 LV，剩下的留在 VG 裡。
> `lvextend -l +100%FREE` 之後再 `resize2fs`（XFS 用 `xfs_growfs`）就吃滿了。
> (B) 錯：磁碟不是不夠大，是沒配出去。
> → 詳見 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] 的〈常見錯誤與排錯〉
>
> **Q63. (C)**
> ★★★ `growpart` 的參數是分開的兩個：磁碟與分割編號。
> 寫成 `/dev/sda2` 它會當成一整個磁碟名稱去找，當然找不到。
> → 詳見 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] 的〈常見錯誤與排錯〉
>
> **Q64. (C)**
> ★★★★ 有快照就不能擴充。同樣的限制也套用在磁碟壓縮與匯出 OVF。
> 注意 Delete All Snapshots 是**不可逆**的，做之前先確認那些還原點不再需要。
> → 詳見 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] 的〈擴充磁碟的完整兩層流程〉
>
> **Q65. (B)**
> ★★★★ 這是最常見的「擴了卻沒變大」。Workstation 那一層只是把虛擬磁碟變大，
> Guest 裡的分割區與檔案系統還停在原本的大小。
> → 詳見 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] 的〈擴充磁碟的完整兩層流程〉
>
> **Q66. (B)**
> ★★★★★ VM 的好處就是有主控台這條退路 —— 遠端實體機沒有這個奢侈。
> 但正確習慣是一開始就用 `netplan try`：設錯不確認會自動還原，根本不會失聯。
> → 詳見 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] 的〈設定靜態 IP〉
>
> **Q67. (B)**
> ★★★ NVMe 效能好但舊安裝程式沒有驅動。要裝舊系統時 **SCSI 最保險**。
> Ubuntu 24.04 這類新系統則兩者皆可。
> → 詳見 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] 的〈控制器與虛擬裝置型別〉
>
> **Q68. (B)**
> ★★★★★ 這是整章最重要的觀念。三個關鍵差異：**分開存放、可獨立還原、有保留策略**，
> 快照三項全是「否」。快照的優點只有「快」，那不足以取代備份。
> → 詳見 [[050-01-02-03-guide-Workstation-快照與複製]] 的〈快照不是備份〉
>
> **Q69. (B)**
> ★★★★★ (A) 是本章最危險的錯誤答案：那些 `-00000N.vmdk` **每一個都是磁碟的一部分**，
> 手動刪掉整顆磁碟就報廢，而且救不回來。
> (C) 同理，搬走等於刪掉。(D) 錯：壓縮的前提是沒有快照。
> → 詳見 [[050-01-02-03-guide-Workstation-快照與複製]] 的〈快照鏈太長的後果與清理時機〉
>
> **Q70. (C)**
> ★★★★ 有快照時每次讀取都可能要往回問好幾層差異磁碟，數據自然不穩。
> 「要做效能測試 → 必須全刪快照」是清理時機表上明列的一條。
> → 詳見 [[050-01-02-03-guide-Workstation-快照與複製]] 的〈常見錯誤與排錯〉
>
> **Q71. (B)**
> ★★★ 連結複製的本質是「從某個快照分岔出去」，所以來源一定要先有快照，
> 而且要選 `An existing snapshot` 而不是 `The current state`。
> → 詳見 [[050-01-02-03-guide-Workstation-快照與複製]] 的〈連結複製（Linked Clone）〉
>
> **Q72. (C)**
> ★★★★★ 連結複製與來源共用基礎磁碟，複本的 `.vmdk` 描述檔記著來源的路徑與檔名。
> 來源被刪、改名或搬移，鏈就斷了。這也是連結複製「不能搬走、不能匯出」的原因。
> → 詳見 [[050-01-02-03-guide-Workstation-快照與複製]] 的〈常見錯誤與排錯〉
>
> **Q73. (B)**
> ★★★★★ 現代 Linux 拿 `machine-id` 當 DHCP client identifier。
> 兩台一樣，DHCP 就認為它們是同一台機器。
> 解法：`sudo rm /etc/machine-id /var/lib/dbus/machine-id && sudo systemd-machine-id-setup`，重開機。
> (C) 錯：hostname 相同只會讓日誌難分辨，不會造成 IP 衝突。
> → 詳見 [[050-01-02-03-guide-Workstation-快照與複製]] 的〈複製後一定要改的四樣東西〉
>
> **Q74. (C)**
> ★★★★ 兩台指紋一樣代表 SSH 的「你連到的是哪一台」保護失效，
> 中間人攻擊就分不出來了。這是複製後必改四項之一。
> → 詳見 [[050-01-02-03-guide-Workstation-快照與複製]] 的〈複製後一定要改的四樣東西〉
>
> **Q75. (B)**
> ★★★ 這個警告**通常是正常且正確的** —— SSH 在告訴你「這個 IP 換人了」。
> 確認是自己重建的機器之後 `ssh-keygen -R <IP>` 即可。
> (D) 錯：關掉 `StrictHostKeyChecking` 等於永久放棄這層保護。
> → 詳見 [[050-01-02-03-guide-Workstation-快照與複製]] 的〈常見錯誤與排錯〉
>
> **Q76. (C)**
> ★★★★ 連結複製不能搬也不能匯出，因為它沒有完整的磁碟資料。
> 要交給別人只能用完整複製或 OVF，而且兩者都要求先刪光快照。
> → 詳見 [[050-01-02-03-guide-Workstation-快照與複製]] 的〈匯出成 OVF〉
>
> **Q77. (B)**
> ★★★★★ 合併大 delta 就是會很久。強制關閉會讓合併中斷，VM 可能直接開不起來，
> 嚴重時只能從備份還原。真正的預防是不要讓快照鏈長成那樣。
> → 詳見 [[050-01-02-03-guide-Workstation-快照與複製]] 的〈常見錯誤與排錯〉
>
> **Q78. (B)**
> ★★★★★ 可達性矩陣裡最容易搞混的一格：**NAT 模式下「主機 → VM」是通的**。
> 主機身上有一張 VMnet8 網卡，和 VM 同網段，直接連即可。
> 這也是本手冊 90% 實驗用 NAT 的原因 —— 主機瀏覽器打 VM 的 IP 就通。
> → 詳見 [[050-01-02-04-guide-Workstation-網路模式]] 的〈可達性矩陣〉
>
> **Q79. (B)**
> ★★★★★ 「主機以外的機器」才需要埠轉發，而且要三層都通：
> 主機防火牆 → NAT 埠轉發規則 → Guest 防火牆與服務監聽 `0.0.0.0`。
> 加上前提：**VM 必須是固定 IP**。
> (C) 錯：Bridged 是最後才考慮的選項，機關網路上應該避免。
> → 詳見 [[050-01-02-04-guide-Workstation-網路模式]] 的〈NAT 埠轉發〉
>
> **Q80. (B)**
> ★★★★ Host-only 的 `VM → 外網` 是 ✗。它的定位是「不能連外但要跟主機交換檔案」。
> 要裝套件就改 NAT，或另外做轉送。
> → 詳見 [[050-01-02-04-guide-Workstation-網路模式]] 的〈可達性矩陣〉
>
> **Q81. (A)**
> ★★★★★ LAN Segment 是四種裡隔離最徹底的：同網段互通，
> 但 `VM ↔ 主機`、`VM → 外網`、`外網 → VM` 全部是 ✗，而且**沒有 DHCP**。
> (D) 錯：Host-only 連得到主機，LAN Segment 連不到 —— 這正是兩者最大的差別。
> → 詳見 [[050-01-02-04-guide-Workstation-網路模式]] 的〈自訂 VMnet 與 LAN Segment〉
>
> **Q82. (B)**
> ★★★★★ 不同 VMnet 之間預設不通。要通只有一個辦法：**一台雙網卡的 router VM**。
> 「明明都在同一台主機上卻 ping 不到」的標準答案就是這個。
> → 詳見 [[050-01-02-04-guide-Workstation-網路模式]] 的〈可達性矩陣〉
>
> **Q83. (C)**
> ★★★★★ `.1` 是主機的 VMnet8 網卡，不是閘道；`.2` 才是 NAT 裝置（兼 DNS 轉送）。
> 症狀就是「ping 得到主機但上不了網」。Netplan 的 `via` 改成 `.2` 即可。
> (D) 錯：NAT 服務沒跑的話連 `.1` 也不一定通得到，症狀不同。
> → 詳見 [[050-01-02-04-guide-Workstation-網路模式]] 的〈查出目前的 NAT 網段是什麼〉
>
> **Q84. (C)**
> ★★★★★ 「ping IP 通、用域名不通」是分辨網路層與 DNS 層的標準測法。
> 這時候不要再去查路由與防火牆。
> → 詳見 [[050-01-02-04-guide-Workstation-網路模式]] 的〈VM 內驗證四步〉
>
> **Q85. (B)**
> ★★★★★ 交換器的 port security 看到同一個埠冒出第二個 MAC，就把埠關掉，
> 於是主機也一起斷網。**第一動作是改回 NAT**，然後請網管恢復該埠。
> 這也是本手冊在機關網路上避免 Bridged 的主要理由。
> → 詳見 [[050-01-02-04-guide-Workstation-網路模式]] 的〈常見錯誤與排錯〉
>
> **Q86. (B)**
> ★★★★ 埠轉發規則寫的是一個固定的 VM IP。VM 用 DHCP 換了 IP，規則就失效。
> 先把 VM 設成固定 IP（避開動態範圍），再設轉發。
> → 詳見 [[050-01-02-04-guide-Workstation-網路模式]] 的〈常見錯誤與排錯〉
>
> **Q87. (C)**
> ★★★★★ `127.0.0.1` 通而外面不通，最典型的原因就是服務只監聽 loopback。
> `ss -tlnp` 一眼就能看出來，改設定監聽 `0.0.0.0` 或指定位址即可。
> → 詳見 [[050-01-02-04-guide-Workstation-網路模式]] 的〈VM 內驗證四步〉
>
> **Q88. (B)**
> ★★★★★ open-vm-tools 走使用者空間的 `vmhgfs-fuse`，**不會自動掛**。
> 舊版的 `vmhgfs` 核心模組才會自動掛好 `/mnt/hgfs`。
> 寫進 `fstab` 時型別要用 `fuse.vmhgfs-fuse`，並且**加上 `nofail`**。
> → 詳見 [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] 的〈共享資料夾：Linux Guest 端與 `/mnt/hgfs`〉
>
> **Q89. (C)**
> ★★★★★ `vmware-hgfsclient` 是問「Host 到底給了我哪些共享」。
> 完全沒輸出就代表 Host 端沒開或沒 Add，不必再在 Guest 裡查掛載。
> 處置：`VM → Settings → Options → Shared Folders` → `Always enabled` → `Add…`。
> → 詳見 [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] 的〈常見錯誤與排錯〉
>
> **Q90. (C)**
> ★★★★★ 掛不起來的檔案系統會讓 systemd 判定「本機檔案系統」失敗，整台停在維護模式。
> 根檔案系統此時是唯讀的，所以**一定要先 `mount -o remount,rw /`** 才改得動 fstab。
> (D) 錯：`Ctrl+D` 只會再跑一次同樣的失敗流程。
> → 詳見 [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] 的〈常見錯誤與排錯〉
>
> **Q91. (B)**
> ★★★★★ 原廠 Tools 會把自己的 `vmhgfs`、`vmxnet` 模組硬塞進系統，
> 換核心後編不過，開機就沒有網路卡。這正是本手冊堅持用 open-vm-tools 的理由。
> 移除要用它自己的 `vmware-uninstall-tools.pl`，不是 `apt remove`。
> → 詳見 [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] 的〈VMware Tools 與 open-vm-tools 的差別〉
>
> **Q92. (B)**
> ★★★★★ 虛擬機沒有真正的 RTC 晶片，時間靠 Hypervisor 模擬的中斷推算。
> Host 睡著時 VM 收不到中斷，醒來就慢了整整睡眠的時間。
> (D) 錯：主機板電池管的是實體機的 RTC，和虛擬時鐘無關。
> → 詳見 [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] 的〈時間同步的坑〉
>
> **Q93. (C)**
> ★★★★★ 這一步幾乎所有教學都漏掉。`time.synchronize.restore` 管的就是
> 「還原快照後」那一次校時，是六項裡最容易被忽略的一項。
> 而且改 `.vmx` 時 VM 必須**完全關機**，Suspend 狀態改了會被蓋掉。
> → 詳見 [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] 的〈時間同步的坑〉
>
> **Q94. (B)**
> ★★★★★ 「vCPU 配多一點比較快」是新手最常見的誤解之一。
> 超過實體核心數之後，Hypervisor 要等所有 vCPU 都能同時上場才排得動，
> CPU ready time 一高就整體變慢。
> → 詳見 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] 的〈CPU 配置準則〉
>
> **Q95. (C)**
> ★★★★★ 三個前提缺一不可，而且要**照順序驗**：
> 沒把 `HyperVisorPresent` 弄成 `False` 之前，後面每一步都會失敗。
> (A) 錯：記憶體是舒適度問題，不是前提（巢狀 PVE 建議 4 vCPU / 8 GB 以上）。
> (B)(D) 錯：與網路模式、主機作業系統無關。
> → 詳見 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] 的〈巢狀虛擬化〉
>
> **Q96. (B)**
> ★★★★★ 這兩個原因涵蓋絕大多數情況。第二個特別容易踩：
> 在 Suspend 狀態改 `.vmx`，Workstation 關閉時會把舊設定寫回去把你的修改蓋掉。
> → 詳見 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] 的〈巢狀虛擬化〉
>
> **Q97. (C)**
> ★★★★★ 四項一起看才可靠：CPU 旗標數、`lscpu` 的 `Virtualization`、`kvm-ok`、
> 以及 `kvm_intel`／`kvm_amd` 模組。RHEL 系可以改用 `virt-host-validate`。
> (A) 錯：勾了不代表生效。(D) 錯：裝得起來不代表有硬體加速，可能慢到不能用。
> → 詳見 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] 的〈巢狀虛擬化〉
>
> **Q98. (C)**
> ★★★★★ 順序不能反：**先 Guest 歸零，再 Host 壓縮**。
> 只做 (A) 幾乎不會變小，因為 Host 分不出哪些區塊是垃圾。
> 而且壓縮前提是完全關機＋沒有任何快照，壓縮前建議先完整複製一份 VM 目錄。
> (B) 是災難：刪 `.vmdk` 等於刪掉整台機器。
> → 詳見 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] 的〈磁碟膨脹與壓縮〉
>
> **Q99. (C)**
> ★★★★★ Workstation 是為了**保護資料**才暫停 VM 的。
> 按 Abort 等同硬斷電，Guest 檔案系統可能損壞。先清空間再 Retry 才是正解。
> → 詳見 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] 的〈常見錯誤與排錯〉
>
> **Q100. (C)**
> ★★★★★ 「之前都好好的」代表**有東西變了**，所以要找變化而不是先調參數。
> 這五項的順序也有意義：快照與空間最常見、成本也最低，最後才去看是不是資源被別人佔走。
> (A) 錯：加資源可能讓超配更嚴重、反而更慢。
> → 詳見 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] 的〈常見錯誤與排錯〉

## 延伸閱讀

- 本章索引：[[050-01-02-00-idx-Workstation-VMware-Workstation]]
- 依症狀查的排錯手冊：[[050-01-02-98-trouble-Workstation-常見故障排除]]
- 為什麼選 Workstation：[[050-01-01-01-guide-虛擬化-虛擬化概念與選型]]
- 下一站，把巢狀虛擬化用起來：[[050-01-03-07-svc-PVE-叢集與高可用]]
- Guest 是 Linux 時的完整排錯手冊：[[020-01-98-trouble-Linux-常見故障排除]]
- Guest 端的時間同步細節：[[020-01-28-cmd-Linux-時間同步NTP與chrony]]
