---
title: "Linux 基礎 總結小考"
desc: "涵蓋 Linux 基礎全章的 100 題總複習：是非 50 題、選擇 50 題，附詳解與原文連結"
aliases: [Linux 基礎總複習, Linux 基礎小考]
tags: [群組/Linux, 主題/總結小考]
category: Linux基礎
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: []
updated: 2026-09-02
---

# Linux 基礎 總結小考

> [!abstract] 使用說明
> **題數與配分**：是非題 50 題（Q1～Q50）＋選擇題 50 題（Q51～Q100），每題 1 分，滿分 100 分。
> 全章三十篇平均分布，每篇 3～4 題。
>
> **建議作答方式**
> - 一次做完 100 題，**不查資料、不開終端機**，預計 70～90 分鐘。
> - 題目考的是**理解與易錯觀念**，不是背指令。看到「這行指令會發生什麼」「該先查哪裡」
>   時，先在腦中把整條因果講一遍再選。
> - 是非題答錯不扣分，但**錯的敘述都是現場真的有人這樣講**，答錯的那幾題請務必回原文確認。
>
> **及格標準與補讀建議**
>
> | 分數 | 判定 | 建議 |
> | --- | --- | --- |
> | **90 分以上** | 可以獨立負責一台正式機的日常維運 | 把錯的那幾題對應的原文段落重讀一次即可；接著往 [[020-01-24-guide-進階儲存-ZFS與Btrfs]]、[[020-01-26-guide-Linux-核心模組與sysctl調校]] 與 [[020-02-01-99-exam-SSH-總結小考]] 前進 |
> | **75～89 分** | 日常操作沒問題，但**改設定與救援會出事** | 重讀 [[020-01-22-guide-Linux-Shell腳本進階]] 的〈`set -e` 的真相〉、[[020-01-17-cmd-Linux-systemd服務管理]] 的〈進階用法：寫一個自訂服務〉與 [[020-01-15-cmd-Linux-磁碟分割與掛載]] 的 fstab 段落，並在測試機把 fstab 寫錯一次、救回來一次 |
> | **60～74 分** | 觀念有明顯缺口 | 依錯題分布補：權限與帳號看 [[020-01-08-cmd-Linux-檔案權限與擁有者]] 與 [[020-01-09-cmd-Linux-使用者與群組管理]]、排錯方法看 [[020-01-23-guide-Linux-Linux常見疑難排解]]、排程與日誌看 [[020-01-18-guide-Linux-排程工作]] 與 [[020-01-19-guide-Linux-日誌系統]] |
> | **60 分以下** | 尚不建議單獨動正式機 | 從 [[020-01-00-idx-Linux基礎]] 的篇章順序重走一遍，每篇的「完整實戰範例」都在測試機做過再回來；先把 [[020-01-02-guide-Linux-實驗環境準備與初次登入]] 的練習環境與快照建起來 |
>
> **★★★★ 答案在下方兩個摺疊區塊裡，先自己作答完再展開。** 直接看答案的複習效果接近零 ——
> 這一章的每一個陷阱，都是有人在正式機上踩過才寫進來的。

## 是非題（50 題）

Q1. 要判斷手上這台機器屬於 Debian 系還是 RHEL 系，只讀 `/etc/os-release` 的 `ID` 就夠了，`ID_LIKE` 只是給人看的補充說明。

Q2. 在 `/etc/apt/sources.list.d/` 加第三方套件庫時，`Suites:` 要填的是發行版代號（如 `noble`）而不是版本號 `24.04`；填錯的典型症狀是 `apt update` 說找不到 Release 檔。

Q3. `usermod -G docker mike` 與 `usermod -aG docker mike` 只是寫法習慣不同，兩者都會把 mike 加進 docker 群組並保留他原有的附加群組。

Q4. 從快照或範本 clone 出來的第二台機器，SSH 主機指紋會跟第一台一模一樣，因為 `/etc/ssh/ssh_host_*` 隨著映像被一起複製了。

Q5. 執行 `ls *.txt` 時，是 `ls` 自己去比對目錄下有哪些 `.txt` 檔案。

Q6. `$?` 只保留最後一個執行完的指令的退出碼，中間插一行 `echo` 就會把它蓋掉，所以要判斷就立刻判斷、或先存進一個變數。

Q7. 執行自己寫的腳本要打 `./script.sh`，是因為目前目錄 `.` 不在 `$PATH` 裡；這是刻意的安全設計，把 `.` 加進 `PATH` 會讓別人在 `/tmp` 放一個假的 `ls` 就騙得到你。

Q8. `cp -a src dest/` 與 `rsync -a src/ dest/` 一樣，結尾那個斜線在兩個指令裡的意義是相同的。

Q9. 零停機部署要用 `ln -sfn` 而不是 `ln -sf`：`current` 已經是指向目錄的符號連結時，`ln -sf` 會把新連結建到 `current/` 裡面去，而且第一次部署看起來正常、第二次才出錯。

Q10. `tail -f` 與 `tail -F` 在日誌輪替之後的行為相同，兩者都會自動跟到新產生的檔案。

Q11. `find /var/log -mtime 1` 找的是「一天之內」被修改過的檔案。

Q12. `find . -type f -size +100` 沒有寫單位時，`100` 指的是 100 個 512 位元組的區塊，不是 100 MB。

Q13. 一個權限是 `444` 的唯讀檔案，只要放在一個所有人可寫的目錄裡，一般使用者仍然刪得掉它。

Q14. 要修好一個被 `chmod -R 777` 過的網站目錄，直接跑 `chmod -R u=rwX,g=rX,o=` 就能把檔案的執行權限拿掉、只留目錄的 `x`。

Q15. 廠商工程師離職時，執行 `usermod -L vendor01` 把密碼鎖起來，就能確保他再也登不進來。

Q16. `/etc/sudoers.d/` 底下的檔案名稱不能包含 `.`，取名 `10-deploy.conf` 會被完全忽略，而且不會有任何錯誤訊息。

Q17. `ps aux` 的 `%CPU` 是「自程序啟動以來的平均值」，一支跑了十小時、只在最初十分鐘吃滿 CPU 的程序在這裡會顯示得很低。

Q18. 一個處於 `D`（不可中斷睡眠）狀態的程序，用 `kill -9` 一定殺得掉，因為 SIGKILL 無法被程序攔截。

Q19. `cmd 2>&1 > file` 與 `cmd > file 2>&1` 的效果相同，只是順序寫法不一樣。

Q20. `comm` 比對兩個檔案時，如果輸入沒有先排序，它會給出錯誤的結果，而且不一定會報錯。

Q21. `echo "a   b   c" | cut -d' ' -f2` 會得到 `b`，因為 `cut` 會把連續的空白視為一個分隔符號。

Q22. `gzip file` 與 `zstd file` 的預設行為剛好相反：gzip 會刪掉原檔，zstd 會保留原檔。

Q23. `tar` 的 `--exclude` 若寫在目標路徑後面會直接報錯，所以不必擔心把順序寫反。

Q24. `dpkg -L` 是「查這個檔案屬於哪個套件」，`dpkg -S` 是「列出這個套件裝了哪些檔案」。

Q25. `apt upgrade` 遇到「必須先移除某個套件才能升級」的情況會跳過該套件，要照做得用 `apt full-upgrade`（舊稱 `dist-upgrade`）。

Q26. ext4 的 inode 數量在格式化當下就固定了，用完只能備份、重建、還原；XFS 是動態配置，所以不會有這個問題。

Q27. XFS 檔案系統可以線上擴大，也可以在卸載之後用 `xfs_shrink` 縮小。

Q28. `ping` 得通才代表主機活著，`ping` 不通就可以判定對方主機掛了。

Q29. 腳本裡的 `curl` 沒有加 `-f` 時，就算伺服器回 404，`curl` 的退出碼仍然是 0，錯誤頁面會被當成正確檔案存下來。

Q30. `systemctl start nginx` 之後測試都正常，就代表這台機器重開機後 nginx 會自動起來。

Q31. `After=postgresql.service` 只管啟動順序、`Requires=postgresql.service` 只管相依關係，兩者彼此獨立，只寫其中一個都可能出問題。

Q32. crontab 的 `0 0 13 * 5` 表示「每個月 13 號、而且那天是星期五」才執行。

Q33. `/etc/cron.daily/` 底下放的是可執行腳本而不是 crontab 格式，而且檔名不能含 `.`，取名 `cleanup.sh` 會被 `run-parts` 直接忽略。

Q34. Ubuntu 預設 `Storage=auto`，在 `/var/log/journal` 不存在時 journal 只寫在記憶體，重開機後 `journalctl -b -1` 什麼都查不到。

Q35. 在腳本裡 `export FOO=bar` 之後，回到呼叫它的那個 shell 執行 `echo $FOO` 也會看到 `bar`。

Q36. `/etc/environment` 是由 PAM 解析的、不是 shell 腳本，所以裡面寫 `PATH=$PATH:/opt/bin` 不會展開變數。

Q37. Ubuntu 的 `/bin/sh` 是 dash，所以 shebang 寫 `#!/bin/sh` 的腳本用了 `[[ ]]` 或陣列會壞掉，而同一支腳本在 RHEL 上卻正常。

Q38. 只要腳本開頭寫了 `set -e`，函式 `deploy()` 裡的 rsync 失敗就一定會讓整支腳本停下來，不會繼續執行後面的 `systemctl restart`。

Q39. 排程腳本用 `flock -n` 搶不到鎖時應該以退出碼 0 結束，因為「上一輪還在跑所以這一輪不跑」是預期行為，不是錯誤。

Q40. 懷疑主機被入侵時，最該優先注意的是 `auth.log` 裡大量的 `Failed password`；`Accepted` 那幾行代表登入成功，通常不必特別看。

Q41. `zpool create tank /dev/sdb /dev/sdc` 建出來的是一個有條帶效能的 RAID0，任一顆磁碟壞掉只會遺失那顆上面的資料。

Q42. ZFS 開 `dedup=on` 需要去重表常駐記憶體，每 TB 資料約需 5 GB RAM，而且事後把 dedup 關掉也救不回已經造成的效能問題。

Q43. 開機停在 `grub rescue>` 與停在 `emergency mode` 是同一類問題，兩種都應該先去檢查 `/etc/fstab`。

Q44. `/boot` 滿了導致 `update-initramfs` 失敗時，正確處置是用 `apt autoremove --purge` 清舊核心，而不是手動 `rm /boot/vmlinuz-*`。

Q45. 在 `/etc/security/limits.conf` 把 `nofile` 調大之後，systemd 啟動的服務也會跟著吃到這個新上限。

Q46. 記憶體有幾條、每條多大、還剩幾個空插槽，`free -h` 與 `/proc/meminfo` 都看不出來，只有 `dmidecode` 讀得到。

Q47. `ethtool -S eth0` 看到 `crc_errors` 是 12345，就足以判定這條線正在掉封包、要立刻換線。

Q48. `chronyc sources` 的 `Reach` 是八進位，`377` 代表最近八次查詢全部成功；`Reach 377` 但該來源被標成 `^x` 時，問題出在對方的時間而不是網路。

Q49. NFS 掛載用預設的 `hard`，伺服器離線時存取該目錄的程序會卡在 `D` 狀態、連 `kill -9` 都殺不掉；改成 `soft` 雖然不會卡住，但寫入中途逾時可能靜默遺失資料。

Q50. 自行編譯安裝到 `/usr/local` 的 Nginx，弱點掃描報告仍然照得出它的 CVE，因為掃描器會直接掃描實際的執行檔。

> [!question]- 是非題詳解（Q1～Q50）
> **Q1. ✗**
> ★★★★ 只判 `ID` 會把 Linux Mint（`ID=linuxmint`、`ID_LIKE="ubuntu debian"`）判成「不支援」。
> 判斷式要寫成 `case "$ID $ID_LIKE"`，把家族一起吃進來。
> 只有 Debian 本尊與 RHEL 本尊沒有 `ID_LIKE`，因為它們就是源頭。
> → 詳見 [[020-01-01-guide-Linux-Linux是什麼與發行版選擇]] 的〈逐步說明：查出手上這台機器是什麼〉
>
> **Q2. ○**
> ★★★★ 這是加第三方庫最常見的第一個坑。Debian 系用 codename（`noble`、`jammy`），
> 不是 `24.04`；RHEL 系則沒有 codename 概念，用 `el8`／`el9`（來自 `PLATFORM_ID`）。
> 腳本裡取值用 `$VERSION_CODENAME`。
> → 詳見 [[020-01-01-guide-Linux-Linux是什麼與發行版選擇]] 的〈觀念說明〉
>
> **Q3. ✗**
> ★★★★★ `-G` 是**取代**整份附加群組清單，`-aG` 才是追加。少打一個 `a`，sudo、adm、docker
> 全部無聲消失，最糟的情況是把自己踢出 sudo 群組。這個指令沒有任何警告。
> → 詳見 [[020-01-02-guide-Linux-實驗環境準備與初次登入]] 的〈完整實戰範例：新機第一次登入的六件事〉
>
> **Q4. ○**
> ★★★★ 快照與映像會把 `/etc/ssh/ssh_host_*` 一起帶走，於是十台機器共用同一把主機私鑰。
> Clone 之後必做：`rm -f /etc/ssh/ssh_host_*` → `ssh-keygen -A` → 重啟 sshd。
> 同一個道理，快照檔本身含 `/etc/shadow` 與私鑰，不能丟雲端硬碟、不能 commit 進 git。
> → 詳見 [[020-01-02-guide-Linux-實驗環境準備與初次登入]] 的〈常見錯誤與排錯〉
>
> **Q5. ✗**
> ★★★★★ 萬用字元是 **Shell 展開的**，`ls` 從來沒看過 `*.txt`，它收到的是展開後的檔名清單。
> 想親眼看到就跑 `echo *.txt`。這個觀念直接連到 `rm -rf $DIR/*` 在 `$DIR` 為空時
> 變成 `rm -rf /*` 的災難，所以腳本要 `set -u`。
> → 詳見 [[020-01-03-cmd-Linux-終端機與Shell入門]] 的〈觀念說明〉
>
> **Q6. ○**
> ★★★★ 這是腳本裡最常見的靜默錯誤來源：`cmd; echo "done"; if [ $? -ne 0 ]` 檢查的
> 其實是 `echo` 的退出碼，永遠是 0。要嘛立刻判斷，要嘛 `rc=$?` 先存起來。
> → 詳見 [[020-01-03-cmd-Linux-終端機與Shell入門]] 的〈進階用法：用 `man` 自己找答案〉
>
> **Q7. ○**
> ★★★★★ `.` 不在 `PATH` 是設計而不是不方便。把它加進去，任何能寫入你會 `cd` 進去的目錄
> 的人都能讓你執行他的程式。這也是 TWGCB／CIS 的檢查項目。
> → 詳見 [[020-01-04-cmd-Linux-檔案系統與目錄結構]] 的〈進階用法：路徑的寫法〉
>
> **Q8. ✗**
> ★★★★ **只有 `rsync` 的尾斜線有意義**。`cp -a src dest/` 與 `cp -a src/ dest/` 結果相同
> （都產生 `dest/src/...`），但 `rsync -a src/ dest/` 只搬「內容」變成 `dest/...`。
> 把 rsync 的直覺套到 cp 上不會出事，反過來套就會多一層或少一層目錄。
> → 詳見 [[020-01-05-cmd-Linux-路徑導覽與檔案操作]] 的〈基礎操作〉
>
> **Q9. ○**
> ★★★★★ `-n`（`--no-dereference`）不能少。這個坑最陰險的地方是「第一次部署正常、
> 第二次才錯」，症狀是「你以為上線了，其實線上還是舊版」。
> `ln -sfn` 底層是 `rename()`，是原子操作；「先刪舊連結再建新的」中間那幾毫秒會 404。
> → 詳見 [[020-01-05-cmd-Linux-路徑導覽與檔案操作]] 的〈完整實戰範例：用符號連結做零停機部署〉
>
> **Q10. ✗**
> ★★★★★ `-f` 追的是「開啟時的那個 inode」，輪替後它繼續看舊檔案、永遠不再有新內容；
> `-F` 追的是檔名，會自動重開、檔案暫時不存在也會等。一律用 `-F`（或 `less +F`）。
> 真正的代價不是少看幾行，而是在事故當下做出「錯誤已經停了」的錯誤結論。
> → 詳見 [[020-01-06-cmd-Linux-檢視檔案內容]] 的〈基礎操作〉
>
> **Q11. ✗**
> ★★★★ `-mtime n` 是「剛好 n 天前」，也就是 24～48 小時之間那一格。
> 「一天內」要寫 `-mtime -1`，「超過兩天」是 `-mtime +1`。少一個正負號，
> 清理腳本刪掉的就是完全不同的一批檔案。
> → 詳見 [[020-01-07-cmd-Linux-尋找檔案與內容]] 的〈基礎操作〉
>
> **Q12. ○**
> ★★★ `-size` 不寫單位預設是 512 位元組區塊，`+100` 等於「大於 51200 位元組」。
> 要 100 MB 得寫 `-size +100M`。同一段裡的 `-perm` 也有三種寫法：`644` 完全等於、
> `-644` 至少包含（稽核用這個）、`/644` 任一符合。
> → 詳見 [[020-01-07-cmd-Linux-尋找檔案與內容]] 的〈基礎操作〉
>
> **Q13. ○**
> ★★★★★ 刪除是「修改目錄」的行為，看的是**目錄的 `w`**，跟檔案本身權限無關。
> 這正是 `/tmp` 需要 sticky bit（`drwxrwxrwt`）的理由：目錄人人可寫，但只有檔案擁有者
> 才刪得掉自己的檔案。把重要檔案設成 444 當保護，是完全無效的做法。
> → 詳見 [[020-01-08-cmd-Linux-檔案權限與擁有者]] 的〈觀念說明〉
>
> **Q14. ✗**
> ★★★★ 大寫 `X` 的規則是「只在已經是目錄、或本來就有任一 x 時才加」。從 777 的狀態
> 修復時所有檔案本來就有 x，`X` 會**全部保留**，等於沒修到。
> 正確做法是先 `find -type f -exec chmod 640 {} +` 全清，再挑選性把該執行的加回來。
> → 詳見 [[020-01-08-cmd-Linux-檔案權限與擁有者]] 的〈基礎操作〉
>
> **Q15. ✗**
> ★★★★★ `usermod -L` 只鎖密碼，**完全不影響 SSH 金鑰登入**。完整停用要四件事一起做：
> 鎖密碼、shell 改 nologin、設帳號到期日（`chage -E` / `usermod -e 1`）、
> 清掉或改名 `~/.ssh/authorized_keys`。只做第一件等於沒做。
> → 詳見 [[020-01-09-cmd-Linux-使用者與群組管理]] 的〈完整實戰範例〉
>
> **Q16. ○**
> ★★★★ 這條規則跟 `/etc/cron.d/` 一模一樣：檔名含 `.` 直接被忽略，安靜地不生效。
> 另外權限必須是 `440`，數字前綴控制載入順序。編輯 sudoers 一律用 `visudo`，
> 因為改壞會形成「不能用 sudo 修 sudo」的死鎖。
> → 詳見 [[020-01-09-cmd-Linux-使用者與群組管理]] 的〈進階用法：sudo 授權〉
>
> **Q17. ○**
> ★★★★ 這是「`ps` 說 CPU 不高，可是 `top` 明明看到它吃滿」的原因。`ps` 的 `%CPU`
> 是自啟動以來的平均，要看即時值請用 `top`／`htop`。
> 同一段還有一組常被誤讀的欄位：`VSZ` 是虛擬記憶體（很大不用緊張），實體佔用看 `RSS`。
> → 詳見 [[020-01-10-cmd-Linux-程序管理與訊號]] 的〈基礎操作〉
>
> **Q18. ✗**
> ★★★★★ `D` 狀態的程序正在等核心完成 I/O，在完成之前**不接受任何訊號**，SIGKILL 也一樣。
> 常見原因是磁碟故障或 NFS 失聯，用 `wchan` 看卡在哪個核心函式。
> 更麻煩的是這種機器連關機都可能卡住。「SIGKILL 無法被攔截」是對的，
> 但它得先被送達才談得上攔截。
> → 詳見 [[020-01-10-cmd-Linux-程序管理與訊號]] 的〈基礎操作〉
>
> **Q19. ✗**
> ★★★★★ 重導向由左到右執行，`2>&1` 的意思是「把 fd 2 複製到 fd 1 **當下**指向的地方」，
> 不是「跟著 fd 1 一起變」。`cmd 2>&1 > file` 的結果是 stderr 留在終端機、stdout 進檔案。
> 記法：先決定 1 去哪，再叫 2 跟著。
> → 詳見 [[020-01-11-cmd-Linux-輸入輸出重導向與管線]] 的〈基礎操作〉
>
> **Q20. ○**
> ★★★★★ 「安靜地給錯答案」比報錯危險得多。你會據此下結論「兩台機器的套件一樣」，
> 然後往完全錯誤的方向查一整個下午。`comm` 要求兩邊都排序過，養成 `comm <(sort a) <(sort b)`
> 的習慣。
> → 詳見 [[020-01-12-cmd-Linux-文字處理三劍客]] 的〈檔案比對：`diff`、`patch`、`cmp`、`comm`〉
>
> **Q21. ✗**
> ★★★★ `cut` **不會**合併連續分隔符號，這題會得到空字串。而且它不報錯 ——
> 監控腳本因此永遠讀到空值、永遠不告警。處理 `ls -l`、`ps`、`df` 這類以空白對齊的
> 輸出一律用 `awk`。
> → 詳見 [[020-01-12-cmd-Linux-文字處理三劍客]] 的〈進階用法：管線裡的黏著劑〉
>
> **Q22. ○**
> ★★★ 這是實務上真的會咬人的一個小差異：`gzip`／`xz` 預設刪原檔（`-k` 保留），
> `zstd` 預設保留原檔（`--rm` 才刪）。備份腳本從 gzip 換成 zstd 之後磁碟莫名長大，
> 多半就是這個原因。
> → 詳見 [[020-01-13-cmd-Linux-壓縮與封存]] 的〈基礎操作〉
>
> **Q23. ✗**
> ★★★★ GNU tar 依序處理參數，`--exclude` 寫在目標之後就不生效，而且**完全不報錯**，
> 只是備份莫名變大。同一段的姊妹坑是 `f` 必須放在選項最後：`tar cfz backup.tar.gz`
> 會把 `z` 當成檔名。
> → 詳見 [[020-01-13-cmd-Linux-壓縮與封存]] 的〈基礎操作〉
>
> **Q24. ✗**
> ★★★★ 方向剛好相反：`dpkg -L <套件>` 是「這個套件裝了哪些檔案」，
> `dpkg -S <檔案>` 是「這個檔案屬於哪個套件」。RHEL 對應是 `rpm -ql` 與 `rpm -qf`。
> 記法：`-L` 是 List files、`-S` 是 Search which package。
> → 詳見 [[020-01-14-guide-Linux-套件管理]] 的〈Debian / Ubuntu：`apt`〉
>
> **Q25. ○**
> ★★★★ `upgrade` 遇到「要移除東西才升得動」的套件會**跳過**，於是你以為升完了，
> 其實有幾個套件一直停在舊版。`full-upgrade` 會照做，但正式環境請先用 `-s` 模擬看清單。
> 另外 `apt update` 只下載清單、不升級任何東西，兩者不能少做一步。
> → 詳見 [[020-01-14-guide-Linux-套件管理]] 的〈Debian / Ubuntu：`apt`〉
>
> **Q26. ○**
> ★★★★ 這是選檔案系統時真正會影響長期維運的差別之一。ext4 預設每 16 KB 一個 inode，
> 被 PHP session、郵件佇列、Docker overlay2 這類海量小檔吃光之後，
> 沒有線上擴充的方法。`df -h` 有空間卻寫不進去，就去看 `df -i`。
> → 詳見 [[020-01-15-cmd-Linux-磁碟分割與掛載]] 的〈基礎操作〉
>
> **Q27. ✗**
> ★★★★★ **XFS 只能擴大不能縮小，沒有 `xfs_shrink` 這個指令，未來也不會有。**
> 要縮小只能 `xfsdump` → `lvreduce` → `mkfs.xfs` → `xfsrestore`。
> 所以規劃 XFS 容量要保守；ext4 可以縮，但順序不能錯：
> `umount` → `e2fsck -f` → `resize2fs` → `lvreduce`，反了就毀掉檔案系統。
> → 詳見 [[020-01-15-cmd-Linux-磁碟分割與掛載]] 的〈基礎操作〉
>
> **Q28. ✗**
> ★★★★ 很多機器與防火牆預設擋 ICMP，`ping` 不通完全不能推論主機狀態。
> 要測就測那個埠：`nc -zv host port`，沒有 nc 時用
> `timeout 3 bash -c '</dev/tcp/host/port'`。
> → 詳見 [[020-01-16-cmd-Linux-網路基礎指令]] 的〈基礎操作〉
>
> **Q29. ○**
> ★★★★★ 這是自動化腳本最常見的靜默失敗之一：`curl` 認為「我成功地把伺服器的回應下載下來了」，
> 至於那是 404 頁面不是它的事。腳本標準組合是 `curl -fsSL`。
> → 詳見 [[020-01-16-cmd-Linux-網路基礎指令]] 的〈`curl` 與 `wget`〉
>
> **Q30. ✗**
> ★★★★★ `start` 是現在啟動、`enable` 是開機自啟，兩件事完全獨立。
> 「裝好、start 了、測試正常，重開機後服務沒起來」就是漏了 enable。
> 永遠用 `systemctl enable --now`。另外 Debian 系裝完套件會自動 enable 並 start，
> RHEL 系不會 —— 跨系統照抄 SOP 時特別容易中。
> → 詳見 [[020-01-17-cmd-Linux-systemd服務管理]] 的〈基礎操作〉
>
> **Q31. ○**
> ★★★★ 只寫 `Requires=` 兩者可能同時啟動，你的服務會因為連不上資料庫而失敗；
> 只寫 `After=` 則對方沒起來時你也照跑。兩個都要寫。
> 還有一個常見錯誤：`After=network.target` 只代表網路子系統起來了、可能還沒拿到 IP，
> 需要連外要用 `network-online.target`，而且**必須同時寫 `Wants=network-online.target`**。
> → 詳見 [[020-01-17-cmd-Linux-systemd服務管理]] 的〈進階用法：寫一個自訂服務〉
>
> **Q32. ✗**
> ★★★★★ 「日」與「星期」同時指定時是 **OR** 不是 AND：這行是「每月 13 號**或**每個週五」
> 都跑。cron 不會報錯，只會多跑，而且多跑的那幾天你未必會注意到。
> 只有其中一欄是 `*` 時才是直覺的意思。
> → 詳見 [[020-01-18-guide-Linux-排程工作]] 的〈cron〉
>
> **Q33. ○**
> ★★★★ 兩個坑一起：`cron.daily` 收的是可執行腳本（把五欄時間運算式寫進去只會得到錯誤），
> 而且 `run-parts` 會忽略含 `.` 的檔名。用 `run-parts --test /etc/cron.daily` 確認
> 你的腳本有被列出來 —— 沒列出來就是永遠不會跑。
> → 詳見 [[020-01-18-guide-Linux-排程工作]] 的〈cron〉
>
> **Q34. ○**
> ★★★★★ 「最需要日誌的時候是空的」。啟用持久化要三步：`mkdir -p /var/log/journal` →
> `systemd-tmpfiles --create --prefix /var/log/journal` → 重啟 `systemd-journald`，
> 不是改個設定檔就好。RHEL 系則預設已經持久化。
> → 詳見 [[020-01-19-guide-Linux-日誌系統]] 的〈journalctl〉
>
> **Q35. ✗**
> ★★★★★ 環境變數**只往下傳、永遠不會往上傳**。腳本是子程序，它 export 的東西隨著
> 它結束一起消失。要讓設定留在目前這個 shell，只能 `source`（`.`）。
> 判讀依據是 `declare -p VAR`：`declare -x` 才代表已 export。
> → 詳見 [[020-01-20-guide-Linux-環境變數與設定檔]] 的〈觀念說明〉
>
> **Q36. ○**
> ★★★★ `/etc/environment` 由 PAM 解析，不支援變數展開、不支援 `export`、不支援指令替換，
> 只能寫完整的 `KEY=value`。要用到展開就得放 `/etc/profile.d/*.sh`。
> 另外提醒：不要直接改 `/etc/profile`，升級時會被覆蓋或產生 `.dpkg-dist` 衝突。
> → 詳見 [[020-01-20-guide-Linux-環境變數與設定檔]] 的〈PATH 管理〉
>
> **Q37. ○**
> ★★★★★ 這是「在我機器上會動」的經典成因。Ubuntu 的 `/bin/sh` 是 dash，
> 不支援 `[[ ]]`、陣列、`function`、`<<<`、`${var//x/y}`；RHEL 的 `/bin/sh` 就是 bash。
> 一律寫 `#!/usr/bin/env bash`。
> → 詳見 [[020-01-21-cmd-Linux-Shell腳本入門]] 的〈觀念說明〉
>
> **Q38. ✗**
> ★★★★★ 這是 `set -e` 六種不觸發情境裡最陰險的一種：**函式被用在條件式裡時，
> 它內部的 `-e` 整個失效**。`if deploy; then ...` 會讓 rsync 失敗後照樣往下跑，
> 重啟一個沒部署完的服務。解法是函式內關鍵步驟自己 `|| return 1`。
> `-e` 是安全網，不是錯誤處理。
> → 詳見 [[020-01-22-guide-Linux-Shell腳本進階]] 的〈`set -e` 的真相〉
>
> **Q39. ○**
> ★★★★ 拿不到鎖時 `exit 0` 是正確的，否則監控會被「每小時一次的假失敗」洗到麻痺。
> 另外鎖要綁在 fd 上（`exec 9>"$LOCK"; flock -n 9`），程序死掉自動釋放；
> 用「檢查 PID 檔存在」當鎖，`kill -9` 之後殘留檔會讓腳本**永遠不再執行**。
> → 詳見 [[020-01-22-guide-Linux-Shell腳本進階]] 的〈鎖檔：防止重疊執行〉
>
> **Q40. ✗**
> ★★★★★ 剛好相反。滿滿的 `Failed password` 只是網際網路的背景噪音，
> 真正該找的是**不該成功的 `Accepted`** —— 陌生來源 IP、非上班時間、
> 不該有互動登入的服務帳號。其他入侵徵兆還有 `debsums -c`／`rpm -Va` 顯示二進位被改、
> 日誌有空窗。
> → 詳見 [[020-01-23-guide-Linux-Linux常見疑難排解]] 的〈安全性注意事項〉
>
> **Q41. ✗**
> ★★★★★ 這行建出來的是**兩個沒有冗餘的單磁碟 vdev**，不是效能導向的條帶。
> ZFS 的規則是「任一 vdev 全毀 = 整個 pool 毀」，所以任一顆壞掉，
> **連另一顆上的資料也一起沒了**。要條帶就明確用 mirror 或 raidz。
> → 詳見 [[020-01-24-guide-進階儲存-ZFS與Btrfs]] 的〈觀念說明〉
>
> **Q42. ○**
> ★★★★ `dedup=on` 幾乎永遠是錯的選擇：去重表要常駐記憶體，不足時效能災難性崩潰，
> 而且關掉也救不回來（既有的去重表還在）。現代做法是 `compression=zstd`，
> 幾乎沒有代價還能省空間。
> → 詳見 [[020-01-24-guide-進階儲存-ZFS與Btrfs]] 的〈ZFS 操作〉
>
> **Q43. ✗**
> ★★★★★ 畫面就是分層依據：`grub rescue>` 是第②層（GRUB 找不到 `/boot/grub`），
> `emergency mode` 是第⑤層（systemd 起來了，八成是 fstab）。
> 看到 `grub rescue>` 去查 fstab、看到 `emergency mode` 去重裝 GRUB，
> 都是把三十分鐘變成三小時的典型。
> → 詳見 [[020-01-25-guide-Linux-開機流程與GRUB救援]] 的〈觀念說明〉
>
> **Q44. ○**
> ★★★★★ 手動 `rm /boot/vmlinuz-*` 會讓套件資料庫與現實不一致，`update-grub` 仍列出
> 已刪核心、下次升級直接失敗。而且 `uname -r` 那一顆絕對不能刪。
> 還有一個時間點的提醒：`update-initramfs: failed` 當下 initramfs 只寫了一半，
> **這時不要重開機**，清完空間要 `update-initramfs -u -k all` 再 `update-grub`。
> → 詳見 [[020-01-25-guide-Linux-開機流程與GRUB救援]] 的〈核心管理〉
>
> **Q45. ✗**
> ★★★★★ `limits.conf` 由 **PAM 在登入時**套用，而 systemd 啟動的服務根本不經過 PAM，
> 所以完全無效。這是「調了沒效」的頭號原因。服務要在 unit 檔寫 `LimitNOFILE=`。
> 唯一可靠的驗證方式是 `cat /proc/PID/limits`，不要相信設定檔。
> → 詳見 [[020-01-26-guide-Linux-核心模組與sysctl調校]] 的〈程序資源限制：三層架構〉
>
> **Q46. ○**
> ★★★ `free`／`/proc/meminfo` 只知道總量，`dmidecode` 讀的是主機板的 DMI／SMBIOS 表，
> 才有插槽數、每條容量、Type／Speed／Part Number 與 `dmidecode -t 16` 的最大容量。
> 這也是硬體盤點腳本一定要 root 的原因。
> → 詳見 [[020-01-27-cmd-Linux-硬體資訊與裝置管理]] 的〈基礎操作〉
>
> **Q47. ✗**
> ★★★★ 判準是**兩次之間有沒有增加**，不是絕對值。數字固定不動只是開機以來的歷史累積，
> 還在長才代表線材／接頭／光模組正在掉封包。少了這一步，很容易把舊帳當成新故障，
> 換了線問題還在。
> → 詳見 [[020-01-27-cmd-Linux-硬體資訊與裝置管理]] 的〈基礎操作〉
>
> **Q48. ○**
> ★★★★ `Reach` 是判斷「網路層 vs 時間層」的分水嶺：`Reach 0` 是根本沒收到回應
> （DNS 或 UDP 123 被擋），`Reach 377` 但標 `^x`（falseticker）是對方的時間真的錯了。
> 另外要記得 `^*` 是目前採用的來源，全表沒有 `^*` 就代表根本沒在同步。
> → 詳見 [[020-01-28-cmd-Linux-時間同步NTP與chrony]] 的〈基礎操作〉
>
> **Q49. ○**
> ★★★★ 這是 NFS 最重要的取捨。`hard` 保證資料完整但會卡死程序，`soft` 不卡但
> **寫入中途逾時會靜默遺失資料**，所以只用在唯讀或不重要的掛載。
> 最佳組合是 `hard` + `x-systemd.automount`（用到才掛，伺服器不在時只影響正在用的人）。
> 卡住時的救援順序是 `umount -f`，不行再 `umount -l`。
> → 詳見 [[020-01-29-guide-Linux-網路儲存與軟體RAID]] 的〈NFS〉
>
> **Q50. ✗**
> ★★★★★ 掃描器讀的是**套件清單**，不是實際執行檔。裝在 `/usr/local` 的自編版本
> 套件管理員根本不知道它存在，於是 `apt upgrade` 說「系統已是最新」、
> 弱點掃描報告乾乾淨淨，而它帶著三年份 CVE 對外服務。
> 至少要用 `checkinstall` 打成套件，讓它出現在 `dpkg -l` 裡。
> → 詳見 [[020-01-30-guide-Linux-原始碼安裝與系統升級]] 的〈安全性注意事項〉

## 選擇題（50 題）

Q51. 你接手一台不確定是什麼系統的機器，要寫一支跨發行版腳本判斷該用 `apt-get` 還是 `dnf`。下列做法最穩健的是？
(A) 跑 `uname -a`，輸出裡有 Ubuntu 字樣就用 apt (B) 讀 `/etc/os-release` 並用 `case "$ID $ID_LIKE"` 判斷家族，認不出來就明確以非 0 退出 (C) 用 `lsb_release -i` 判斷，這是最標準的做法 (D) 先試 `apt-get`，失敗再退回 `dnf`

Q52. 一台對外的 VPS 上要動 sshd 與防火牆設定。最重要的前置準備是？
(A) 先把 `PermitRootLogin` 改成 yes 以免失聯 (B) 先把防火牆整個關掉，改完再開回來 (C) 先把 SSH 改到高位埠，攻擊者就找不到管理埠了 (D) 先確認自己會用該 VPS 的主控台（VNC／Serial Console／Recovery Mode），並全程保留一條已連線的 session 不關

Q53. 目錄裡有一個檔名剛好叫 `-rf` 的檔案要刪掉。正確做法是？
(A) `rm -rf` (B) `rm "-rf"` (C) `rm -- -rf` (D) `rm \-rf`

Q54. 備份腳本要在暫存區產生一個 20 GB 的封存檔，而這台機器的 `/tmp` 是 tmpfs。最可能發生什麼、該怎麼處理？
(A) 沒問題，`/tmp` 本來就是給暫存檔用的 (B) 20 GB 會直接吃進記憶體、可能觸發 OOM；動手前先 `df -h /tmp` 確認，改用 `/var/tmp` 或專用資料磁碟 (C) 只會報磁碟已滿，重跑一次就好 (D) 只是重開機後檔案會消失，改成 `/tmp/keep/` 即可

Q55. `df -h` 顯示 `/var` 只用了 40%，服務卻一直回報 `No space left on device`。下一步最該做什麼？
(A) 查 `df -i` 看 inode 是不是用光，並用 `lsof +L1` 找已刪除但仍被程序持有的檔案 (B) 繼續用 `du -sh` 找大檔案 (C) 直接擴充 LVM (D) 重開機讓核心重新計算可用空間

Q56. 要把 `/etc/nginx/` 備份到 `/backup/`，還原之後服務要能直接跑起來。應該用哪一個？
(A) `cp -r /etc/nginx /backup/` (B) `mv /etc/nginx /backup/` (C) `cp -a /etc/nginx /backup/` (D) `cp -R --preserve=timestamps /etc/nginx /backup/`

Q57. 事故當下你開著 `tail -f /var/log/nginx/error.log` 盯了十分鐘，一行新訊息都沒有，於是回報「錯誤已經停了」。這個結論最可能錯在哪？
(A) error log 本來就不會即時寫入 (B) 期間日誌被輪替，`tail -f` 抱著舊的 inode 繼續看，新內容全寫進新檔案了 (C) `tail` 需要 root 權限才看得到內容 (D) 應該用 `cat` 才看得到最新內容

Q58. 承上題，你想確認這個猜測。哪一個指令最能直接給出鐵證？
(A) `ls -l /var/log/nginx/` (B) `journalctl -u nginx` (C) `df -h /var` (D) `ls -l /proc/$(pgrep -x tail)/fd`，看箭頭是不是指向 `.1` 或標著 `(deleted)`

Q59. 稽核要求列出整台機器上所有 setuid 檔案，且不要走進 `/proc`、`/sys` 與 NFS 掛載點。下列哪一條最恰當？
(A) `find / -xdev -type f -perm -4000` (B) `find / -type f -perm 4000` (C) `find / -xdev -type f -perm /4000 -delete` (D) `find / -name "*suid*"`

Q60. 使用者回報網站 403，你檢查 `/var/www/example.com/public/index.php` 是 `644 www-data:www-data`，看起來完全正常。最該做的下一步是？
(A) `chmod 777 index.php` (B) 重啟 Nginx (C) `namei -l /var/www/example.com/public/index.php`，逐層檢查路徑上每一層目錄有沒有 `x` (D) 把 `www-data` 加進 `sudo` 群組

Q61. 部署帳號產生的 `.env` 目前是 `600 deploy:deploy`，以 `www-data` 執行的 PHP-FPM 讀不到。最合適的處置是？
(A) `chmod 644 .env` (B) `chown www-data:www-data .env` 並維持 600 (C) 把 `www-data` 加進 `deploy` 群組並 `chmod 660` (D) 改成 `640 deploy:www-data`，或機密不放檔案、改用 systemd 的 `EnvironmentFile=` 提供

Q62. 帳號稽核時發現 `/etc/passwd` 裡有一行 `backdoor:x:0:0::/home/backdoor:/bin/bash`。這代表什麼、處理優先序如何？
(A) UID 0 等於完整 root 權限，名字不重要，應列為最高優先並視為潛在入侵事件 (B) 只是家目錄設錯，改一下就好 (C) 只要把 shell 改成 nologin 就沒有風險 (D) GID 0 才危險，UID 0 只是個編號

Q63. 要給部署人員一條 sudo 規則，只讓他重啟自家服務。下列哪個寫法最不容易被拿去提權？
(A) `deploy ALL=(ALL) NOPASSWD: /usr/bin/systemctl *` (B) `deploy ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart myapp.service` (C) `deploy ALL=(ALL) NOPASSWD: /usr/bin/find` (D) `deploy ALL=(ALL) NOPASSWD: /usr/bin/vi /etc/systemd/system/myapp.service`

Q64. 某服務半夜莫名消失，日誌裡沒有正常關閉的訊息，`systemctl status` 顯示 `Killed`。第一個該做什麼？
(A) 加大 `Restart=always` 的重試次數 (B) 檢查磁碟空間 (C) `dmesg -T | grep -i -E "out of memory|oom.kill"`，確認是不是 OOM Killer (D) 重新安裝該服務

Q65. 一台 8 核心的機器 load average 是 8.0，但 `top` 的 `%Cpu(s)` 顯示 `id` 很高。最可能的原因是？
(A) load average 壞掉了，不用理它 (B) CPU 剛好滿載，屬於正常 (C) 記憶體不足導致大量 swap (D) 有一批程序卡在 `D` 狀態等 I/O（磁碟或 NFS），Linux 的 load 把它們算了進去

Q66. 備份腳本寫成 `mysqldump db | gzip > backup.sql.gz`，`mysqldump` 因為密碼錯誤失敗了。實際會發生什麼？
(A) gzip 壓縮空輸入，產生一個約 20 bytes 的合法 `.gz`，整條管線退出碼 0，腳本回報「備份成功」 (B) 整條管線回傳非 0，腳本會停下來 (C) gzip 偵測到來源失敗，會刪掉輸出檔 (D) 會產生 0 bytes 的檔案，一眼就看得出來

Q67. 你不是 root，要把一行設定寫進 `/etc/sysctl.d/99-tune.conf`。下列哪個做得到？
(A) `sudo echo "net.core.somaxconn = 4096" > /etc/sysctl.d/99-tune.conf` (B) `sudo cat "net.core.somaxconn = 4096" > /etc/sysctl.d/99-tune.conf` (C) `echo "net.core.somaxconn = 4096" | sudo tee /etc/sysctl.d/99-tune.conf` (D) `echo "net.core.somaxconn = 4096" > sudo /etc/sysctl.d/99-tune.conf`

Q68. 監控腳本從 `df -h` 取使用率，寫成 `df -h | grep /data | cut -d' ' -f5`，結果永遠是空字串，而且從來不告警。最準確的診斷是？
(A) `df` 的輸出格式在新版改過了 (B) `cut` 不會合併連續空白，以空白對齊的輸出應該改用 `awk` (C) `grep` 應該加 `-F` (D) 應該用 `df -H` 而不是 `-h`

Q69. 要用 sed 批次修改二十台機器的 `sshd_config`。下列流程何者最安全？
(A) 直接 `sed -i` 改完後全部 `systemctl restart ssh` (B) 用 `sed -i` 改完再用 `diff` 比對就好 (C) 寫成 `sed -i ... && systemctl reload ssh` 一行搞定 (D) 先不加 `-i` 看結果 → 加 `-i.bak` 執行 → `sshd -t` 驗證 → 最後一步 reload 留給人做

Q70. 備份要還原到一台新機器，兩台的帳號 UID 不保證一致。要讓檔案落到正確的擁有者，正確做法是？
(A) 建立與還原兩邊都要加 `--numeric-owner`，少一邊都不算數 (B) 只要還原時加 `--numeric-owner` 就好 (C) 用 `-p` 保留權限就會連擁有者一起處理 (D) 還原後統一 `chown -R root:root`

Q71. 加了某個第三方 APT 套件庫之後，`apt upgrade` 把系統原本的套件換成了該庫的版本。最適當的處置是？
(A) 把該套件 `apt-mark hold` 起來就好 (B) 移除該套件庫，改用原始碼編譯 (C) 在 `/etc/apt/preferences.d/` 做 pinning：把該來源整體壓到 100，只把真正需要的套件提到 700 (D) 在 sources 檔加上 `[trusted=yes]`

Q72. 系統升級後在 `/etc/` 底下發現一個 `.rpmsave` 檔。這代表什麼？
(A) 新版設定檔被存起來，你改過的版本仍然生效 (B) 只是備份，沒有任何影響 (C) 升級失敗，新設定檔沒有被寫入 (D) 你沒有改過這個檔案，新版直接覆蓋、舊版被存起來，服務已經在用新的預設值跑

Q73. 要在 `/etc/fstab` 幫一顆新資料磁碟加一行。下列哪個組合最能避免「重開機後遠端連不上」？
(A) 用 `/dev/sdb1` 當裝置、選項寫 `defaults` (B) 用 UUID 當裝置、選項加 `nofail`，改完在重開機前跑 `findmnt --verify --verbose` (C) 用 `/dev/sdb1`、fsck 欄位填 1 (D) 用 UUID、選項寫 `defaults,ro`

Q74. `du -sh /data` 加總只有 20 GB，但 `df -h` 顯示該掛載點用掉 200 GB。最可能的兩個原因是？
(A) 檔案被刪除但程序仍持有（`lsof +L1` 可查），或有東西掛載上去把原目錄的內容遮住了 (B) `du` 算錯了，改用 `du -b` (C) inode 用光了 (D) 檔案系統需要 fsck

Q75. 網站連不上，你已確認介面有 IP、預設路由存在、ping 得到閘道、ping 得到 8.8.8.8，但 `ping www.example.com` 失敗。問題落在哪一層？
(A) 實體層，去查網路線 (B) 路由，去查 `ip route` (C) DNS 解析 (D) 防火牆擋了 80 埠

Q76. 要遠端改一台 Ubuntu 伺服器的靜態 IP。下列做法最安全？
(A) 改完 netplan 直接 `netplan apply` (B) 用 `ip addr add` 設好就不用寫設定檔 (C) 先把舊 IP 刪掉再加新的 (D) 改完用 `netplan try`，套用後有倒數，沒按 Enter 確認就自動還原

Q77. 你在 `/usr/lib/systemd/system/nginx.service` 裡直接加了 `MemoryMax=2G`，套件升級後這個設定不見了。正確做法是？
(A) 改用 `/etc/init.d/` 的舊式腳本 (B) 用 `systemctl edit nginx` 建立 drop-in，落在 `/etc/systemd/system/nginx.service.d/` (C) 把檔案 `chattr +i` 鎖起來 (D) 每次升級後再手動加回去

Q78. 自訂 unit 啟動失敗，`systemctl status` 顯示 `status=203/EXEC`。最可能的原因是？
(A) `ExecStart` 指的執行檔不存在或沒有執行權限（常見於沒寫絕對路徑） (B) `WorkingDirectory` 不存在 (C) `User=` 指定的帳號不存在 (D) 相依的服務還沒起來

Q79. 你在 `/etc/cron.d/` 放了一個檔案叫 `backup.cron`，內容是 `0 3 * * * /usr/local/bin/backup.sh`，排程從來沒跑過，也沒有任何錯誤訊息。最可能的原因是？
(A) 時間欄位寫錯了 (B) 檔案權限要改成 777 (C) 需要 `systemctl restart cron` 才會被讀到 (D) 檔名含 `.` 會被忽略，而且 `/etc/cron.d/` 的格式比使用者 crontab 多一個「使用者」欄位

Q80. 憑證續期排程改用 systemd timer，機器可能在排定時間處於關機狀態，而全機房有五十台要同時跑。該用哪組設定？
(A) `OnCalendar=daily` 搭配 `Restart=always` (B) `OnUnitActiveSec=` 搭配 `StartLimitBurst=` (C) `Persistent=true` 搭配 `RandomizedDelaySec=` (D) 在 `.service` 上 `systemctl enable`

Q81. logrotate 把 `access.log` 改名成 `access.log.1` 之後，新的 `access.log` 一直是 0 bytes，磁碟卻持續被吃掉。最正確的解讀與處置是？
(A) logrotate 壞了，重裝套件 (B) 服務仍握著舊 inode 的檔案描述符在寫；`postrotate` 沒有送出該服務要的訊號或 reload，要去查該服務的文件確認 (C) 直接 `rm access.log.1` 釋放空間 (D) 把 `rotate` 的數字調大

Q82. logrotate 設定裡 `size 100M` 與 `maxsize 500M` 的差別是？
(A) `size` 取代時間條件（只看大小），`maxsize` 是搭配時間條件（時間到「或」超過大小） (B) 兩者同義，只是單位寫法不同 (C) `size` 是上限、`maxsize` 是下限 (D) `maxsize` 只在 `copytruncate` 模式下有效

Q83. 使用者反映「SSH 登入之後 alias 和自訂 PATH 全部消失」，`su - user` 也一樣。最可能的原因是？
(A) `~/.bashrc` 被刪掉了 (B) 登入 shell 被改成 dash (C) `/etc/profile` 的權限不對 (D) 有人建了 `~/.bash_profile`，bash 找登入設定檔時找到第一個就停，`~/.profile`（連帶載入 `.bashrc` 的那段）不再被讀

Q84. 腳本用迴圈逐行讀檔並累計計數，跑完之後計數器永遠是 0。最可能的原因是？
(A) 忘了寫 `IFS=` (B) 忘了寫 `-r` (C) 用了 `cat file | while read ...`，管線讓迴圈在子 shell 裡跑，變數改不到外面 (D) 檔案最後一行沒有換行

Q85. 腳本執行時報 `bad interpreter: /bin/bash^M: No such file or directory`。原因與解法是？
(A) bash 沒安裝，`apt install bash` (B) 檔案是 CRLF 換行（在 Windows 編輯過），用 `dos2unix` 或 `sed -i 's/\r$//'` 修正 (C) shebang 一定要寫 `#!/usr/bin/env bash` 才行 (D) 腳本沒有執行權限，`chmod +x` 即可

Q86. 腳本開頭是 `set -euo pipefail`，中間有一行 `((count++))`，在 count 為 0 的那一輪腳本突然結束。原因是？
(A) 後綴 `((count++))` 回傳的是舊值 0，算式為假使退出碼變成 1，在 `set -e` 下中止腳本 (B) `count` 沒有初始化 (C) 是 `pipefail` 造成的 (D) bash 的算術展開不支援 `++`

Q87. 正式機出現「服務還活著但明顯變慢」。下列處置何者最恰當？
(A) 立刻 `systemctl restart`，先恢復再說 (B) 先 `chmod 777` 排除權限因素 (C) 先重開機看看會不會好 (D) 先看再動：保全現況與證據、一次只改一件事，避免把「變慢」變成「已經死了」

Q88. 遠端主機要重開機前，下列哪一組準備最完整？
(A) 先 `sync` 再 `reboot` (B) 先跑 `fsck -y` 確保檔案系統乾淨 (C) 保全揮發性證據（`ps auxf`、`ss -tanp`、`lsof +L1`、`dmesg -T`）＋確認開得回來（`findmnt --verify`、`/boot` 空間、核心檔存在）＋確認有退路（Console／IPMI／快照）＋通知 (D) 先 `setenforce 0` 排除 SELinux 影響

Q89. 你手上有一個三顆磁碟組成的 raidz1，想再加一顆 4TB 進去擴充容量。實際會發生什麼？
(A) `zpool add tank /dev/sde` 會直接把它併進那個 raidz1 (B) RAIDZ vdev 的磁碟數在建立時就固定，`zpool add` 會報 `mismatched replication level`；只能加一整組完整 vdev、逐顆 replace 換大碟，或備份重建 (C) 加進去之後跑一次 `zpool scrub` 就會重新平衡 (D) 要先 `zpool offline` 一顆再加進去

Q90. 一台跑 MySQL 的 ZFS 主機記憶體一直被吃光，最後 OOM Killer 砍掉資料庫。最可能的原因與處置是？
(A) ARC 預設可用到實體記憶體的 50%、釋放速度不一定跟得上，應明確設定 `zfs_arc_max` (B) `recordsize` 太小，調成 128K (C) 開啟 `sync=disabled` 以減少記憶體使用 (D) 開啟 `dedup=on` 以減少重複資料

Q91. 遠端伺服器要升核心，跑一趟機房很麻煩。下列哪個流程最能保住退路？
(A) 升完直接 reboot，出事再叫機房 (B) 只要在 `GRUB_CMDLINE_LINUX_DEFAULT` 加參數就好 (C) 直接編輯 `/boot/grub/grub.cfg` 把新核心排到第一個 (D) 先確認 `/boot` 空間與舊核心還在，用 `grub-set-default` 把預設固定在舊核心，再用 `grub-reboot` 指定「只有下一次」試新核心

Q92. 資安基準要求停用某個核心模組。在 `/etc/modprobe.d/` 裡只寫 `blacklist foo` 夠不夠？
(A) 夠，`blacklist` 就是完全禁用 (B) 不夠，還要再 `rmmod foo` 一次 (C) 不夠，`blacklist` 只阻止「自動」載入，手動 `modprobe foo` 或被其他模組依賴時仍會載入；要真正禁用得寫 `install foo /bin/false` (D) 這一行應該改寫在 `/etc/modules-load.d/`

Q93. 服務一直報 `Too many open files`。下列敘述何者正確？
(A) 一定是 `fs.file-max` 太小，直接調大 (B) 幾乎都不是全系統的 `fs.file-max`，而是單一程序的 `nofile`；而 `limits.conf` 對 systemd 服務無效，要在 unit 檔設 `LimitNOFILE=`，並用 `cat /proc/PID/limits` 驗證 (C) 要調的是 `fs.inotify.max_user_watches` (D) 要調的是 `net.core.somaxconn`

Q94. 機櫃裡要換掉一顆故障磁碟。下列哪個做法最不會拔錯？
(A) 用序號認人（`lsblk -o NAME,SERIAL` 或 `/dev/disk/by-id/`），並用 `ledctl locate=` 把該碟的燈點亮 (B) 依 `lsblk` 顯示的 `/dev/sdb` 找到第二個碟位拔掉 (C) 先關機，再依 SATA 埠順序推算 (D) 拔一顆看哪個陣列降級，錯了再插回去

Q95. 一台跑著資料庫的正式機時間快了 40 秒。最恰當的處置是？
(A) 用 `date -s` 直接把時間往回調 40 秒 (B) 重開機讓 RTC 重新校時 (C) 停掉 chrony 之後手動改，改完不必再啟動 (D) 用 `chronyc makestep`，或讓 chrony 以 slew 慢慢追；`date -s` 往回跳會讓資料庫時間戳倒置，而且 chrony 下一輪還會改回去，應用會看到兩次跳動

Q96. Linux 主機加入 AD 網域後常出現 `Clock skew too great`。最直接的原因與處置是？
(A) DNS 沒設好，去改 `/etc/resolv.conf` (B) 憑證過期，重新申請 (C) Kerberos 預設只容忍 5 分鐘時間差；chrony 應指向 DC 或與 DC 相同的內部 NTP，「大家對同一個時間」比「對得準」更重要 (D) 要把 `RTC in local TZ` 設成 `yes`

Q97. 有人把 NFS 分享設成 `no_root_squash` 好讓備份程式運作。這造成什麼風險？
(A) 只是效能較差，沒有安全風險 (B) 客戶端的 root 等同伺服器的 root，可在分享目錄裡建立 setuid root 的檔案，只要有人執行就提權；若非開不可，客戶端掛載要加 `nosuid,nodev` (C) 只會讓檔案擁有者顯示成 nobody (D) 會讓 NFSv4 的 idmapd 失效

Q98. 一組 mdadm RAID 1 建好用了半年，某天發現兩顆碟都壞了、資料全沒。最可能被跳過的是哪一步？
(A) 沒有啟用 `mdmonitor` 與 `MAILADDR`／`PROGRAM` 告警，第一顆壞掉時沒人知道，撐到第二顆壞才發現 (B) 建立時沒有等初次 resync 完成 (C) 沒有把 `mdadm --detail --scan` 寫進 `mdadm.conf` (D) 沒有跑 `update-initramfs -u`

Q99. 三年前自編的 Nginx 裝在 `/usr/local`，`apt upgrade` 一直說系統已是最新，弱點掃描報告也乾淨。下列敘述何者正確？
(A) 自編版本本來就比較安全 (B) 掃描器設定錯誤，改設定就會掃到 (C) 只要 `/usr/local/bin` 排在 PATH 前面就沒有問題 (D) 套件管理員與掃描器讀的是套件清單，`/usr/local` 底下的東西它們根本不知道存在，於是它帶著三年份 CVE 對外服務而所有自動化報表都說沒問題

Q100. `do-release-upgrade` 過程中問你要不要換成套件提供的新版 `sshd_config`。該怎麼選、為什麼？
(A) 選安裝套件版本（Y），設定最新最安全 (B) 先按 D 看差異，然後選 Y 就對了 (C) 選保留自己的版本（N），之後再用 `.dpkg-dist` 比對合併；選套件版可能改掉 Port 或認證方式而把自己鎖死 (D) 中斷升級，改成重建遷移

> [!question]- 選擇題詳解（Q51～Q100）
> **Q51. (B)**
> ★★★★ 判 `ID` 之外一定要吃進 `ID_LIKE`，否則 Mint、Pop!\_OS 這類衍生發行版全部被判成
> 「不支援」。更重要的是最後半句：**認不出來要明確失敗**，不要 fallback 成 apt ——
> 在 Rocky 上亂跑 apt 會裝出一堆錯東西。
> (A) 錯：`uname` 是核心提供的資訊，與發行版無關，Ubuntu 上跑也不會出現 "Ubuntu"。
> (C) 錯：`lsb_release` 好讀但最小安裝與容器常常沒裝，腳本不該依賴它。
> (D) 錯：試錯法會在半途留下不完整的狀態，而且失敗訊息很難判讀。
> → 詳見 [[020-01-01-guide-Linux-Linux是什麼與發行版選擇]] 的〈完整實戰範例：寫一個跨發行版的環境偵測腳本〉
>
> **Q52. (D)**
> ★★★★★ 這一題只有一個核心：**動門鎖之前先確認你有另一把鑰匙。** 主控台是把自己鎖在
> 門外時唯一的救命通道，而「保留一條已連線的 session、用另一個終端機開新連線測試通過
> 才關舊的」是改 sshd 的鐵則。
> (A) 錯：開 root 直登是把一個小風險換成一個大風險。
> (B) 錯：關防火牆的空窗期就是被掃到的時候。
> (C) 錯：換埠只是減少雜訊，不是安全措施，稽核上也不能寫成「提升安全性」。
> → 詳見 [[020-01-02-guide-Linux-實驗環境準備與初次登入]] 的〈逐步說明〉
>
> **Q53. (C)**
> ★★★★ `--` 的意思是「選項到此為止，後面都是參數」，這是唯一乾淨的解法。
> (A) 錯：這正是災難本身 —— `-rf` 被當成選項，後面沒有目標，或更糟地刪到別的東西。
> (B) 錯：引號只影響 Shell 的切詞，`rm` 拿到的仍是以 `-` 開頭的字串，照樣當選項。
> (D) 錯：反斜線同理，跳脫的是 Shell 不是 `rm` 的參數解析。
> 另一個等效寫法是給它相對路徑 `./-rf`。
> → 詳見 [[020-01-03-cmd-Linux-終端機與Shell入門]] 的〈觀念說明〉
>
> **Q54. (B)**
> ★★★★ tmpfs 的 `/tmp` 吃的是記憶體，20 GB 封存檔會直接把機器打掛。
> 順帶記住另一組差別：`/tmp` 重開機清空，`/var/tmp` 重開機**保留**。
> (A) 錯：這正是沒先確認就下判斷的典型。
> (C) 錯：吃光記憶體的後果是 OOM Killer 砍掉別的服務，不是「重跑一次就好」。
> (D) 錯：問題不在檔案會不會消失，而在它根本不該進記憶體。
> → 詳見 [[020-01-04-cmd-Linux-檔案系統與目錄結構]] 的〈逐步說明：走一遍根目錄〉
>
> **Q55. (A)**
> ★★★★★ `df -h` 有空間卻寫不進去，永遠先分兩路：inode 用光（`df -i`），
> 或檔案被刪但仍被程序開著（`lsof +L1`）。後者的處置是 `truncate -s 0` 或 reload 服務，
> 不是 `rm`。
> (B) 錯：`du` 找的是「還存在的大檔」，這兩種情況它都看不到。
> (C) 錯：inode 用完時擴充空間完全沒有幫助。
> (D) 錯：重開機會清掉現場證據，而且 inode 問題重開機也不會好。
> → 詳見 [[020-01-04-cmd-Linux-檔案系統與目錄結構]] 的〈常見錯誤與排錯〉
>
> **Q56. (C)**
> ★★★★ `cp -a` 等於 `-dR --preserve=all`，保留權限、擁有者、時間戳記、符號連結、ACL
> 與 SELinux 標籤。**備份一律用 `-a`**。
> (A) 錯：`cp -r` 會把權限與擁有者變成執行者的、時間變成現在，還原後服務起不來就是這樣來的。
> (B) 錯：`mv` 是搬走不是備份，原地就沒有設定檔了。
> (D) 錯：只保留時間戳記，權限與擁有者照樣跑掉。
> → 詳見 [[020-01-05-cmd-Linux-路徑導覽與檔案操作]] 的〈基礎操作〉
>
> **Q57. (B)**
> ★★★★★ `tail -f` 追的是 inode，輪替後它抱著 `error.log.1` 繼續看，你面前那個「安靜」
> 是假的。這題的真正代價不是少看幾行，而是**在事故當下做出錯誤結論**。
> 一律用 `tail -F` 或 `less +F`。
> (A) 錯：error log 是即時寫入的。
> (C) 錯：權限不足會直接報 Permission denied，不是安靜。
> (D) 錯：`cat` 只會印出當下那個檔案的內容，同樣是舊檔。
> → 詳見 [[020-01-06-cmd-Linux-檢視檔案內容]] 的〈基礎操作〉
>
> **Q58. (D)**
> ★★★★ 看那條 `tail` 程序實際開著哪個檔案描述符，是最直接的物證：箭頭指向 `.1`
> 或標著 `(deleted)` 就結案。相關的還有 `lsof /var/log/nginx/access.log.1` ——
> 如果 COMMAND 是服務本身，那就是 logrotate 的 `postrotate` 沒送訊號。
> (A) 錯：看得到檔案清單，但看不出你的 `tail` 抓著哪一個。
> (B) 錯：Nginx 的存取日誌不在 journal 裡。
> (C) 錯：磁碟空間是另一個獨立問題（雖然也值得順手看一眼）。
> → 詳見 [[020-01-06-cmd-Linux-檢視檔案內容]] 的〈常見錯誤與排錯〉
>
> **Q59. (A)**
> ★★★★ 兩個關鍵：`-xdev` 不跨檔案系統（避免走進 `/proc`、`/sys` 與 NFS），
> `-perm -4000` 是「至少包含這些位元」——稽核就是要用這個。
> 正常結果只該有 sudo、su、passwd、mount、ping 等少數幾個，出現在 `/tmp`、`/home`、
> `/var/tmp` 就是入侵跡象。做法是存一份基準清單定期 diff。
> (B) 錯：`-perm 4000` 是**完全等於**，會漏掉 `4755` 這種實際存在的檔案，而且沒有 `-xdev`。
> (C) 錯：稽核指令加 `-delete` 是把盤點變成破壞。
> (D) 錯：setuid 是權限位元，跟檔名毫無關係。
> → 詳見 [[020-01-07-cmd-Linux-尋找檔案與內容]] 的〈安全性注意事項〉
>
> **Q60. (C)**
> ★★★★★ 「Nginx 讀不到檔案／回 403」十次有八次是**路徑上某一層目錄少了 `x`**，
> 檔案本身的權限再漂亮也沒用。`namei -l` 一次把整條路徑每一層攤開來看。
> 驗證則永遠用 `sudo -u www-data` 實測，不要憑「看起來應該可以」下判斷。
> (A) 錯：777 可能剛好蓋過問題，但等於把整個目錄開放給機器上每個帳號，而且多半沒解到目錄那層。
> (B) 錯：權限問題重啟不會好。
> (D) 錯：`www-data` 是服務帳號，加進 sudo 群組是嚴重的錯誤授權。
> → 詳見 [[020-01-08-cmd-Linux-檔案權限與擁有者]] 的〈觀念說明〉
>
> **Q61. (D)**
> ★★★★ `640 deploy:www-data` 讓 deploy 可讀寫、www-data 可讀、其他人完全看不到，
> 這是最小權限的標準寫法。更好的做法是機密根本不落地成檔案，改用 systemd `EnvironmentFile=`
> （注意要用 `EnvironmentFile=` 而不是 `Environment=`，後者會被 `systemctl show` 印出來）。
> (A) 錯：**絕不能** `chmod 644 .env` —— 資料庫密碼與 API 金鑰對機器上每個帳號公開。
> (B) 錯：這樣改成 www-data 專屬，deploy 自己反而寫不了，部署會壞。
> (C) 錯：把 www-data 加進 deploy 群組，等於讓 Web 服務讀得到 deploy 的所有檔案，範圍過大。
> → 詳見 [[020-01-08-cmd-Linux-檔案權限與擁有者]] 的〈完整實戰範例：Web 服務的正確權限模型〉
>
> **Q62. (A)**
> ★★★★★ 系統認的是 UID 不是名稱，UID 0 就是 root，叫什麼名字完全不重要。
> 稽核指令是 `awk -F: '$3 == 0 {print $1}' /etc/passwd`，正常只該輸出 `root`。
> 帳號稽核的處理優先序是：**UID 0 → 空密碼 → 危險 sudo 規則 → 其他**，前三項應視為潛在入侵事件。
> (B) 錯：家目錄是這一行裡最不重要的欄位。
> (C) 錯：nologin／`/bin/false` 都擋不住 `sudo -u`，而且 UID 0 的問題完全沒解決。
> (D) 錯：UID 0 才是權限來源，GID 0 只是主要群組。
> → 詳見 [[020-01-09-cmd-Linux-使用者與群組管理]] 的〈觀念說明〉
>
> **Q63. (B)**
> ★★★★★ sudo 授權要寫**完整指令與完整參數**，一個萬用字元就等於送出 root。
> 授權前的習慣動作是去 GTFOBins 查一下那個指令能不能逃逸成 shell。
> (A) 錯：`systemctl *` 可以停掉防火牆、可以 `systemctl edit` 改別的 unit，等同 root。
> (C) 錯：`find` 有 `-exec`，可以執行任意指令。
> (D) 錯：`vi` 可以 `:!sh` 直接開一個 root shell。
> → 詳見 [[020-01-09-cmd-Linux-使用者與群組管理]] 的〈進階用法：sudo 授權〉
>
> **Q64. (C)**
> ★★★★★ 「半夜消失、日誌沒有正常關閉訊息、status 顯示 Killed」是 OOM Killer 的
> 標準指紋，第一個動作就是去 `dmesg` 找那行紀錄。
> 判讀時還要分清楚 `Memory cgroup out of memory`（只是這個服務超過 `MemoryMax=`）
> 與全系統的 `Out of memory`（整台機器不夠用），兩者的處置完全不同。
> (A) 錯：重啟得更快只會讓它更快被殺一次，根因沒解。
> (B) 錯：磁碟滿的症狀是寫入失敗，不是被 Killed。
> (D) 錯：重灌無助於記憶體不足。
> → 詳見 [[020-01-10-cmd-Linux-程序管理與訊號]] 的〈進階用法：前景、背景與斷線存活〉
>
> **Q65. (D)**
> ★★★★ Linux 的 load average **包含等待 I/O 的 `D` 狀態程序**，這跟其他 Unix 不同。
> 所以 load 高不一定是 CPU 忙，要看 `%Cpu(s)` 的 `wa` 欄位與 `ps` 裡的 `D` 狀態來區分。
> `wa` 持續大於 10% 就代表磁碟是瓶頸。
> (A) 錯：load average 沒壞，是你把它當成純 CPU 指標。
> (B) 錯：CPU 真的滿載時 `id` 會接近 0。
> (C) 錯：swap 造成的問題會反映在 `si`／`so` 與 `wa`，而且題目沒給這個線索。
> → 詳見 [[020-01-10-cmd-Linux-程序管理與訊號]] 的〈基礎操作〉
>
> **Q66. (A)**
> ★★★★★ 這是備份腳本靜默失敗的頭號原因：管線的退出碼預設只反映**最後一個指令**，
> gzip 開開心心壓縮了「空的輸入」，回傳 0，你的腳本回報「備份成功」，
> 直到需要還原那天才發現。
> 所有腳本開頭都該有 `set -euo pipefail`，事後也可以用 `${PIPESTATUS[@]}` 查每一段的退出碼。
> 更進一步的防線是備份腳本自己驗證產物（大小、檔案數、內容特徵）。
> (B) 錯：沒有 `pipefail` 時不會。
> (C) 錯：gzip 完全不知道上游是誰、發生了什麼。
> (D) 錯：`.gz` 的檔頭與結尾讓空輸入也有約 20 bytes，不是 0，一眼未必看得出來。
> → 詳見 [[020-01-11-cmd-Linux-輸入輸出重導向與管線]] 的〈基礎操作〉
>
> **Q67. (C)**
> ★★★★★ 重導向是**由 Shell 執行的，而 Shell 是以你的身分在跑**，sudo 只提升了後面
> 那個 `echo`。`tee` 之所以可行，是因為 `tee` 本身是以 root 執行、由它去開檔案寫入。
> (A) 錯：這是最經典的誤解，一定失敗，錯誤訊息還是 Permission denied 讓人更困惑。
> (B) 錯：`cat` 的參數是檔名不是內容，而且重導向的問題一模一樣。
> (D) 錯：語法不成立，`sudo` 被當成輸出檔名。
> → 詳見 [[020-01-11-cmd-Linux-輸入輸出重導向與管線]] 的〈基礎操作〉
>
> **Q68. (B)**
> ★★★★★ `cut` 不合併連續分隔符號，而 `df -h` 的欄位是用空白對齊的，所以取到的是空字串。
> 最陰險的是**它不報錯**：監控腳本永遠讀到空值、永遠不告警，磁碟真的滿的那天也是安靜的。
> 處理 `ls -l`、`ps`、`df` 這類輸出一律用 `awk`。
> (A) 錯：格式沒改，是解析方式選錯了。
> (C) 錯：`-F` 是把樣式當字面字串，跟欄位切割無關。
> (D) 錯：`-H` 只是換成 1000 進位，欄位排版一樣。
> → 詳見 [[020-01-12-cmd-Linux-文字處理三劍客]] 的〈進階用法：管線裡的黏著劑〉
>
> **Q69. (D)**
> ★★★★★ 三個習慣缺一不可：**先不加 `-i` 看結果**、`-i.bak` 留退路、**用服務自己的
> 檢查工具驗證**。而批次操作的最後一步 reload 要留給人 —— 改壞 SSH 會把自己鎖在門外，
> 而且錯誤會被放大二十倍，連「還有一台正常的可以比對」都沒有。
> (A) 錯：跳過驗證直接 restart 二十台，是把可修復事件變成全面失聯。
> (B) 錯：`sed -i` 已經寫進去了，事後 diff 只是知道自己改壞了什麼。
> (C) 錯：`&&` 讓改與 reload 變成同一個動作，等於沒有人工關卡。
> → 詳見 [[020-01-12-cmd-Linux-文字處理三劍客]] 的〈基礎操作〉
>
> **Q70. (A)**
> ★★★★ 沒有 `--numeric-owner` 時 tar 存的是**使用者名稱**，還原機器上同名帳號若是
> 不同 UID，檔案就被交給錯的人。這個選項在建立與還原兩邊都要加，少一邊都不算數。
> RHEL 系還要記得加 `--selinux`，忘了的補救是 `restorecon -Rv`。
> (B) 錯：建立時沒存數字，還原時也變不出來。
> (C) 錯：`-p` 是權限位元，跟擁有者的對應無關。
> (D) 錯：全部 root 會讓需要以服務帳號寫入的目錄整組壞掉。
> → 詳見 [[020-01-13-cmd-Linux-壓縮與封存]] 的〈基礎操作〉
>
> **Q71. (C)**
> ★★★★ 第三方庫的套件預設優先度同樣是 500，版本較新就贏過官方，於是系統套件被無聲替換。
> 正解是 pinning：`Package: *` 對該來源壓到 100（只在未安裝時考慮），
> 只把真正要的套件提到 700。優先度規則要背：`<0` 永不安裝、`100` 只在未安裝時考慮、
> `500` 預設、`>500` 優先於預設來源、`>1000` 允許降級。
> (A) 錯：hold 只擋住那一個套件，下一個被替換的還是會發生。
> (B) 錯：自編安裝會脫離套件管理與安全更新，是更大的問題。
> (D) 錯：`[trusted=yes]` 是關掉簽章驗證，而套件的安裝腳本是以 root 執行的。
> → 詳見 [[020-01-14-guide-Linux-套件管理]] 的〈Debian / Ubuntu：`apt`〉
>
> **Q72. (D)**
> ★★★★★ 方向要記牢：`.rpmnew`／`.dpkg-dist` 是**新版被存起來、你的版本仍生效**；
> `.rpmsave`／`.dpkg-old` 是**舊版被存起來、新版已經生效**。後者更危險，
> 因為服務已經在用預設值跑，而且沒有任何提示。
> 升級後固定要跑 `find /etc -name "*.rpmnew" -o -name "*.rpmsave"` 檢查一遍。
> (A) 錯：那是 `.rpmnew` 的意思。
> (B) 錯：它代表你的設定已經被換掉了，影響很大。
> (C) 錯：升級成功才會產生這個檔。
> → 詳見 [[020-01-14-guide-Linux-套件管理]] 的〈完整實戰範例〉
>
> **Q73. (B)**
> ★★★★★ 三個要素：UUID（裝置名稱會因為加磁碟、換 SATA 埠、VM 調整而改變）、
> `nofail`（掛不上就跳過，非根分割區一律要加）、以及**重開機前**跑
> `findmnt --verify --verbose`。遠端伺服器進 emergency mode 等於完全連不上。
> 想再保險一點可以加 `x-systemd.device-timeout=10`，避免開機卡在等裝置。
> (A) 錯：兩個要素都缺，是最典型的「重開機後回不來」寫法。
> (C) 錯：裝置名不穩定，而且 fsck 欄位填 1 是根分割區的用法。
> (D) 錯：UUID 對了但沒有 `nofail`，磁碟一旦掛不上就進 emergency mode。
> → 詳見 [[020-01-15-cmd-Linux-磁碟分割與掛載]] 的〈基礎操作〉
>
> **Q74. (A)**
> ★★★★ 兩個經典成因：幽靈檔案（`lsof +L1` 會看到 `NLINK` 為 0、標著 `(deleted)`），
> 以及掛載遮住原目錄——被遮住的資料仍佔用底下那個檔案系統的空間，`du /data` 卻看不到，
> 查法是 `mount --bind /` 到別處再 `du`。
> 幽靈檔案的處置是 reload 服務，或 `truncate -s 0 /proc/PID/fd/N` 清空而不重啟。
> (B) 錯：`du -b` 只是換單位，看不到已刪除或被遮住的東西。
> (C) 錯：inode 用光的症狀是「有空間卻寫不進去」，不是 `du` 與 `df` 對不起來。
> (D) 錯：這不是檔案系統損壞的徵兆。
> → 詳見 [[020-01-15-cmd-Linux-磁碟分割與掛載]] 的〈觀念說明〉
>
> **Q75. (C)**
> ★★★★ 七層排查的價值就在這裡：**第 4 步通、第 5 步不通＝純 DNS 問題**，一句話就縮小範圍。
> 接下來要看的是 `resolvectl status`（現代 Ubuntu 上 `/etc/resolv.conf` 只是指向
> systemd-resolved 的符號連結、會被覆蓋，`127.0.0.53` 只是本機 stub），
> 以及 `/etc/hosts` 有沒有測試時留下來忘了拿掉的那一行。
> (A)(B) 錯：這兩層已經在第 1～3 步排除了。
> (D) 錯：那是第 6 步的事，還沒走到。
> → 詳見 [[020-01-16-cmd-Linux-網路基礎指令]] 的〈完整實戰範例：「網站連不上」的完整排查〉
>
> **Q76. (D)**
> ★★★★★ `netplan try` 是遠端改網路唯一該用的指令：套用後倒數，沒按 Enter 確認就自動還原。
> RHEL 沒有這個功能，等效做法是先用 `at now + 5 minutes` 排一個「還原成 DHCP」的保險，
> 連得回來再 `atrm` 取消 —— 順序不能顛倒。
> 另外 netplan 的 YAML 只吃空白不吃 Tab，縮排錯誤可能完全不生效而且不一定報錯。
> (A) 錯：設錯直接失聯，只能去機房或用主控台。
> (B) 錯：`ip addr add` 不會持久化，重開機就沒了（不過它是設定檔寫壞時的救援手段）。
> (C) 錯：先刪舊 IP 的那一瞬間你就斷線了。
> → 詳見 [[020-01-16-cmd-Linux-網路基礎指令]] 的〈網路設定：`netplan` 與 `nmcli`〉
>
> **Q77. (B)**
> ★★★★★ `/usr/lib/systemd/system/` 是套件的地盤，改了會在升級時被**無聲無息地覆蓋**。
> Unit 檔的優先度由高到低是 `/etc/systemd/system/` → `/run/systemd/system/` →
> `/usr/lib/systemd/system/`，所以覆寫要放 `/etc/`。
> 用 `systemctl edit` 產生 drop-in（只改你要的那幾行），要整份改寫才用 `--full`，
> 要移除所有覆寫用 `systemctl revert`。改完記得 `daemon-reload`。
> (A) 錯：退回 SysV 腳本是往回走，而且 systemd 仍會產生相容 unit。
> (C) 錯：`chattr +i` 會讓套件升級直接失敗，把小問題變成大問題。
> (D) 錯：這等於把「會被忘記的事」排進未來每一次升級。
> → 詳見 [[020-01-17-cmd-Linux-systemd服務管理]] 的〈進階用法：寫一個自訂服務〉
>
> **Q78. (A)**
> ★★★★ systemd 的失敗碼是有語意的，背起來可以省很多時間：
> `203/EXEC` 執行檔不存在或沒有執行權限（`ExecStart` 一定要用絕對路徑）、
> `200/CHDIR` `WorkingDirectory` 不存在、`217/USER` `User=` 的帳號不存在、
> `209/STDOUT` 日誌輸出路徑有問題、`1/FAILURE` 程式自己退出。
> (B)(C) 錯：那是 `200/CHDIR` 與 `217/USER`。
> (D) 錯：相依沒起來的表現是啟動順序問題，不會是 203。
> → 詳見 [[020-01-17-cmd-Linux-systemd服務管理]] 的〈常見錯誤與排錯〉
>
> **Q79. (D)**
> ★★★★★ 兩個坑同時中，而且兩個都**完全沒有錯誤訊息**：`/etc/cron.d/` 忽略含 `.` 的檔名
> （規則同 `sudoers.d`），而系統 crontab 比使用者 crontab 多一個「使用者」欄位 ——
> 少寫那一欄，cron 會把 `/usr/local/bin/backup.sh` 當成使用者名稱，整行不執行。
> 正確內容應該是 `0 3 * * * root /usr/local/bin/backup.sh`，檔名改成 `backup`。
> (A) 錯：時間欄位本身沒問題。
> (B) 錯：權限過寬反而會讓 cron 拒絕執行，應該是 644 且屬 root。
> (C) 錯：`/etc/cron.d/` 的變更不需要重啟 cron。
> → 詳見 [[020-01-18-guide-Linux-排程工作]] 的〈cron〉
>
> **Q80. (C)**
> ★★★★★ `Persistent=true` 解決「關機錯過就永遠錯過」——憑證續期漏一次就是全站憑證過期；
> `RandomizedDelaySec=` 解決驚群效應，讓五十台不要同時 03:00 打爆備份伺服器
> （每台的延遲依 machine-id 固定，不會每次亂跳）。
> 還要記得 `enable` 的是 **`.timer` 不是 `.service`**，enable 錯邊的結果是
> 「現在立刻跑一次並嘗試常駐，之後再也不會跑」。
> (A) 錯：`Restart=` 是服務崩潰後的重啟策略，跟排程無關。
> (B) 錯：`OnUnitActiveSec` 是從上次執行完成起算的間隔，不處理錯過補跑。
> (D) 錯：這正是 enable 錯邊的那個錯誤做法。
> → 詳見 [[020-01-18-guide-Linux-排程工作]] 的〈systemd timer〉
>
> **Q81. (B)**
> ★★★★★ logrotate 只是把檔案**改名**，服務握著的是 inode，所以它繼續往舊檔案寫，
> 新建的 `access.log` 永遠是 0 bytes，而磁碟被那個「看不到的」舊檔吃掉。
> 修法是讓 `postrotate` 送出**該服務要的**訊號 —— 每個服務不一樣（rsyslog 用 `HUP`），
> 一定要查該服務的文件，不要照抄別人的設定。
> 能用 `postrotate` 就不要用 `copytruncate`，後者會遺失複製與清空之間寫入的那幾行，
> 大檔還要雙倍空間。
> (A) 錯：logrotate 做的事完全正確，缺的是通知服務。
> (C) 錯：`rm` 不會釋放空間（服務還開著它），要用 `truncate -s 0`；而且刪掉等於毀掉稽核軌跡。
> (D) 錯：調 `rotate` 只影響保留幾份，跟這個症狀無關。
> → 詳見 [[020-01-19-guide-Linux-日誌系統]] 的〈logrotate〉
>
> **Q82. (A)**
> ★★★ 這兩個關鍵字最容易被當成同義詞。`size` 是**取代**時間條件（只看大小，
> 寫了它 `daily`／`weekly` 就不作用），`maxsize` 是**搭配**時間條件（時間到「或」
> 提早超過大小就輪替）。突發流量會把日誌灌大的服務，通常要的是 `maxsize`。
> (B)(C)(D) 都錯：不是同義詞、不是上下限關係，也與 `copytruncate` 無關。
> → 詳見 [[020-01-19-guide-Linux-日誌系統]] 的〈logrotate〉
>
> **Q83. (D)**
> ★★★★★ bash 找登入設定檔的順序是 `~/.bash_profile` → `~/.bash_login` → `~/.profile`，
> **找到第一個就停**。Ubuntu 的 `~/.profile` 裡有載入 `~/.bashrc` 的判斷，
> 所以一旦 `.bash_profile` 出現，那整條鏈就斷了。
> 解法是在 `.bash_profile` 裡補上 `[ -f ~/.profile ] && . ~/.profile`，或乾脆刪掉它。
> (A) 錯：檔案還在，只是沒被讀到。
> (B) 錯：換成 dash 的症狀是語法錯誤，不是設定消失。
> (C) 錯：權限問題會有錯誤訊息，而且 `/etc/profile` 影響的是全機。
> → 詳見 [[020-01-20-guide-Linux-環境變數與設定檔]] 的〈載入順序：改哪個檔案才會生效〉
>
> **Q84. (C)**
> ★★★★★ 管線的每一段都在**子 shell** 裡執行，迴圈裡改的變數在外面看不到，
> 所以計數器永遠是初始值。正解是改成重導向：`while read ...; done < file`。
> 逐行讀檔的完整寫法是 `while IFS= read -r line; do ...; done < "$file"` ——
> `IFS=` 保留行首行尾空白、`-r` 不把 `\` 當跳脫、重導向避免子 shell，三者缺一不可。
> (A)(B) 錯：這兩個會造成內容失真（空白被吃、跳脫被解讀），但不會讓計數歸零。
> (D) 錯：最後一行沒換行最多少讀一行，不會是 0。
> → 詳見 [[020-01-21-cmd-Linux-Shell腳本入門]] 的〈基礎操作〉
>
> **Q85. (B)**
> ★★★★ 訊息裡那個 `^M` 就是答案：檔案是 CRLF，核心找的直譯器變成 `/bin/bash\r`，
> 當然不存在。用 `file` 一眼看出 "with CRLF line terminators"。
> 同一個根因也會造成「設定值明明對卻比對不到」（值變成 `example.com\r`）。
> (A) 錯：bash 在，錯的是它後面那個看不見的字元。
> (C) 錯：`#!/usr/bin/env bash` 是好習慣（跨平台），但 CRLF 存在時它一樣會壞。
> (D) 錯：沒有執行權限的訊息是 `Permission denied`。
> → 詳見 [[020-01-21-cmd-Linux-Shell腳本入門]] 的〈常見錯誤與排錯〉
>
> **Q86. (A)**
> ★★★★★ 後綴 `++` 回傳的是**舊值**，count 為 0 時整個算式為假，退出碼 1，
> `set -e` 就把腳本收掉了 —— 而且這一行看起來完全無害，是最難自己看出來的一種。
> 三種安全寫法：`((count++)) || true`、`count=$((count+1))`、或前綴 `((++count))`
> （但 count 從 -1 開始時 `++count` 一樣會炸）。
> (B) 錯：`set -u` 才會抓未初始化，而且症狀是 unbound variable。
> (C) 錯：`pipefail` 只影響管線。
> (D) 錯：bash 支援 `++`，問題出在它的回傳值語意。
> → 詳見 [[020-01-22-guide-Linux-Shell腳本進階]] 的〈`set -e` 的真相〉
>
> **Q87. (D)**
> ★★★★★ 排錯四原則的第一條就是「先看再動」：亂改會破壞證據，也常常把一個問題變成兩個。
> 「還活著但變慢」的最大風險，就是被你一個 restart 變成「已經死了」——
> 而重啟之後所有現場證據（記憶體狀態、連線、程序樹）也一起消失了。
> 真的死掉時才反過來：先恢復服務，再從保全下來的證據找根因。
> (A) 錯：這是「排錯本身的錯誤」清單裡的第一項。
> (B) 錯：`chmod 777` 從來不是排除法，它只會製造資安問題。
> (C) 錯：重開機是最後手段，而且要先做「重開機前清單」。
> → 詳見 [[020-01-23-guide-Linux-Linux常見疑難排解]] 的〈觀念說明〉
>
> **Q88. (C)**
> ★★★★★ 重開機前清單有四塊，缺一不可：**保全揮發性證據**（重開就沒了）、
> **確認開得回來**（`findmnt --verify`、`/boot` 空間、enabled 的服務、`vmlinuz` 還在）、
> **確認有退路**（Console／IPMI／快照）、**通知**。
> 遠端主機重開不回來就是一次到機房的行程，而證據沒保全就等於這次故障白發生。
> (A) 錯：只做了最表面的一件事。
> (B) 錯：對已掛載的檔案系統跑 `fsck` 會造成嚴重損壞，而 `-y` 對損壞磁碟更是危險。
> (D) 錯：`setenforce 0` 是排查手段而不是重開機準備，而且很容易忘了開回來。
> → 詳見 [[020-01-23-guide-Linux-Linux常見疑難排解]] 的〈重開機前清單〉
>
> **Q89. (B)**
> ★★★★★ 這是 ZFS 三個「建立後就改不掉」的決定之一（另兩個是 `ashift` 與 vdev 的冗餘型式）。
> RAIDZ vdev 的磁碟數建立時固定，`zpool add` 只能加**一整組完整 vdev**。
> 三個實際選項：加一整組 vdev、逐顆 `replace` 換成大磁碟（**全部換完容量才增加**）、
> 或備份重建。需要彈性擴充的場景一開始就該用 mirror。
> (A) 錯：會報 `mismatched replication level`；就算用 `-f` 硬加，也是加成一個沒有冗餘的
> 單磁碟 vdev，任一 vdev 全毀等於整個 pool 毀。
> (C) 錯：`scrub` 是校驗資料，不會重新配置佈局。
> (D) 錯：`offline` 只是把磁碟標記離線，跟擴充無關。
> → 詳見 [[020-01-24-guide-進階儲存-ZFS與Btrfs]] 的〈觀念說明〉
>
> **Q90. (A)**
> ★★★★★ ZFS 的 ARC 預設可以用到實體記憶體的 50%，而且釋放速度不一定跟得上突發需求，
> 結果就是 OOM Killer 挑「最大的」殺 —— 通常正是你的資料庫。
> 處置是明確設 `zfs_arc_max`（寫進 `/etc/modprobe.d/zfs.conf`，之後
> `update-initramfs -u` 並重開機才會生效）。
> (B) 錯：`recordsize` 影響寫入放大與效能，不影響 ARC 上限；而且 MySQL InnoDB 該調成 16K，
> 128K 反而造成八倍寫入放大。
> (C) 錯：`sync=disabled` 會讓資料庫以為落盤其實還在記憶體，斷電就是交易遺失，是更糟的選擇。
> (D) 錯：`dedup=on` 要的記憶體更多（每 TB 約 5 GB），是把火加大。
> → 詳見 [[020-01-24-guide-進階儲存-ZFS與Btrfs]] 的〈ZFS 操作〉
>
> **Q91. (D)**
> ★★★★★ 關鍵在 `grub-reboot` 與 `grub-set-default` 的分工：前者是「**只有下一次**」，
> 後者才是永久預設。把預設固定在已知可開的舊核心、用 `grub-reboot` 試新核心，
> 新核心開不起來時只要斷電重開就自動回到舊核心 —— 這是遠端升核心唯一安全的姿勢。
> 另外要先確認 `/boot` 有空間，以及舊核心還在（`uname -r` 那顆絕不能刪）。
> (A) 錯：沒有退路。
> (B) 錯：那是加開機參數，跟選哪顆核心無關。
> (C) 錯：`grub.cfg` 是產生檔，下次核心更新就被覆蓋。
> → 詳見 [[020-01-25-guide-Linux-開機流程與GRUB救援]] 的〈GRUB2〉
>
> **Q92. (C)**
> ★★★★★ `blacklist` 只阻止**自動**載入 —— 手動 `modprobe foo` 照樣載入，
> 被其他模組依賴時也會被拉起來。資安基準（TWGCB／CIS）要停用檔案系統或協定模組時，
> 必須用 `install foo /bin/false` 才是真正禁用。
> 順帶記住持久化的分工：`/etc/modules-load.d/` 是「開機載入哪些模組」，
> `/etc/modprobe.d/` 是「模組參數與封鎖」，兩者不能混。
> (A) 錯：這正是稽核最常抓到的誤解。
> (B) 錯：`rmmod` 只影響當下，重開機就回來了。
> (D) 錯：`modules-load.d` 是叫它載入，方向完全相反。
> → 詳見 [[020-01-26-guide-Linux-核心模組與sysctl調校]] 的〈核心模組〉
>
> **Q93. (B)**
> ★★★★★ 兩層要分清楚：`fs.file-max` 是全系統上限（現代預設百萬級，幾乎不會是元凶），
> `nofile` 是單一程序的限制。先看 `/proc/sys/fs/file-nr` 第一欄離上限多遠再決定調哪一層。
> 而 `limits.conf` 由 PAM 在登入時套用，**對 systemd 服務完全無效**，要在 unit 檔寫
> `LimitNOFILE=`。驗證只認 `cat /proc/PID/limits`，不要相信設定檔。
> (A) 錯：調錯層，改完問題照舊。
> (C) 錯：`max_user_watches` 對應的是 `ENOSPC`（IDE／同步工具報磁碟沒滿卻沒空間）。
> (D) 錯：`somaxconn` 是 accept 佇列長度，症狀是連線被丟棄不是 open files。
> → 詳見 [[020-01-26-guide-Linux-核心模組與sysctl調校]] 的〈程序資源限制：三層架構〉
>
> **Q94. (A)**
> ★★★★★ `sdX` 是依偵測順序配發的，重開機、換 HBA、多插一顆碟都會位移 ——
> 憑 `/dev/sdX` 拔碟是本篇「做下去就回不去」清單裡的第一項。
> 一律用序號認人，再用 `ledctl locate=`（需 ledmon）把燈點亮確認。
> 另外提醒：硬體 RAID 的成員碟根本不會出現在 `lsblk`，要用 `storcli64`／`perccli64`／`ssacli`。
> (B) 錯：這正是拔錯碟的標準劇本；RAID 1 拔錯那顆等於兩顆都沒了。
> (C) 錯：埠順序與裝置名的對應本來就不保證。
> (D) 錯：試誤法在有冗餘的陣列上就是在賭第二次故障。
> → 詳見 [[020-01-27-cmd-Linux-硬體資訊與裝置管理]] 的〈安全性注意事項〉
>
> **Q95. (D)**
> ★★★★★ 這是本篇唯一「做了就救不回來」的動作：時間往回跳會讓資料庫時間戳倒置、
> cron 重跑或跳過、日誌無法排序。而且 `date -s` 完全不通知 chrony，
> chrony 下一輪還會改回去，應用會看到**兩次**跳動。
> 要立刻校正就用 `chronyc makestep`；真的要手動控制就先 `systemctl stop chrony`，
> 兩者不要混用。
> (A) 錯：正是題目要避免的那個動作。
> (B) 錯：重開機不會校時，而且 40 秒的偏差重開後依舊。
> (C) 錯：停掉之後不啟動，機器就永久失去時間同步了。
> → 詳見 [[020-01-28-cmd-Linux-時間同步NTP與chrony]] 的〈安全性注意事項〉
>
> **Q96. (C)**
> ★★★★ Kerberos 預設容忍 5 分鐘，超過就整個網域登入一起失敗。
> 重點在最後那句：**「與 DC 對同一個時間」比「對得準」更重要** ——
> chrony 要指向 DC 或指向與 DC 相同的內部 NTP 來源。
> 更廣義的教訓是：時間錯會偽裝成別的問題（憑證 not yet valid、TOTP 一直錯、
> 日誌時間線兜不攏），遇到解釋不通的認證問題先看 `timedatectl`。
> (A)(B) 錯：訊息已經明講是 clock skew，不是名稱解析或憑證。
> (D) 錯：`RTC in local TZ` 伺服器應為 `no`，設成 `yes` 反而會差一整個時區。
> → 詳見 [[020-01-28-cmd-Linux-時間同步NTP與chrony]] 的〈進階用法〉
>
> **Q97. (B)**
> ★★★★★ `root_squash`（預設）把客戶端 root 映射成 `nobody`，關掉它等於把伺服器的 root
> 送給任何能連上的客戶端 —— 對方可以在你的分享目錄裡放一個 setuid root 的執行檔，
> 等著誰去執行。
> 更根本的問題是 NFSv3 的 `AUTH_SYS` 只是「相信客戶端聲稱的 UID」，
> 所以**防火牆限制來源網段不是選配**；高安全需求要用 NFSv4 + Kerberos（`sec=krb5p`）。
> (A) 錯：這是權限模型問題，跟效能無關。
> (C) 錯：那是開著 `root_squash` 時的正常現象。
> (D) 錯：idmapd 的名稱對應是另一回事（要求兩端設同一個 `Domain`）。
> → 詳見 [[020-01-29-guide-Linux-網路儲存與軟體RAID]] 的〈NFS〉
>
> **Q98. (A)**
> ★★★★★ **沒有監控的 RAID 等於沒有 RAID。** 一顆壞了沒人知道，跑幾個月第二顆壞才發現，
> 是最常見的資料遺失劇本。要 `systemctl enable --now mdmonitor` 並設好
> `MAILADDR`／`PROGRAM`，而且要用 `mdadm --monitor --scan --test --oneshot` 實際驗證 ——
> 沒收到通知就等於沒監控。
> 順帶提醒：RAID 不是備份，它不保護誤刪、勒索軟體、檔案系統損壞或火災水災。
> (B) 錯：resync 期間可用但沒有冗餘，不過那是建立當天的風險，不是半年後。
> (C) 錯：漏掉會讓裝置名變 `/dev/md127` 而掛不上，是可見的錯誤，不會讓資料悄悄消失。
> (D) 錯：那影響的是「根在 RAID 上時開不了機」。
> → 詳見 [[020-01-29-guide-Linux-網路儲存與軟體RAID]] 的〈mdadm 軟體 RAID〉
>
> **Q99. (D)**
> ★★★★★ 這是原始碼安裝最真實的代價：套件管理員不知道它存在，所以不會有安全更新；
> 弱點掃描器讀的也是套件清單，所以報告永遠乾淨。
> 三年份 CVE 對外服務，而所有自動化報表都說沒問題 —— 這比「有已知風險」危險得多。
> 最低限度的補救是用 `checkinstall` 打成 .deb，讓它至少出現在 `dpkg -l` 裡；
> 更好的是自建套件庫。
> (A) 錯：沒有任何理由讓自編版本更安全，反而少了發行版的安全 backport。
> (B) 錯：掃描器沒設定錯，它就是這樣運作的。
> (C) 錯：PATH 順序決定的是「跑到哪一個」，跟有沒有被納入更新管理無關 ——
> 而且 `/usr/local/bin` 排在前面正是「以為在跑套件版、其實在跑自編版」的來源。
> → 詳見 [[020-01-30-guide-Linux-原始碼安裝與系統升級]] 的〈安全性注意事項〉
>
> **Q100. (C)**
> ★★★★★ 設定檔衝突一律先選 **`N`（保留自己的）**，升級完再用 `.dpkg-dist` 逐項比對合併。
> `sshd_config` 尤其不能讓套件版覆蓋 —— Port、`PermitRootLogin`、認證方式一改，
> 你當下那條連線斷掉就再也連不回來。
> 補充兩個同章的保命細節：`do-release-upgrade` 透過 SSH 執行時會在 **1022 埠**開備援 sshd
> （前提是防火牆放行，而且驗證完務必收掉）；RHEL 的 leapp **沒有**這種備援。
> (A) 錯：這是最快把自己鎖在門外的選擇。
> (B) 錯：看差異是好習慣，但看完仍選 Y 就白看了。
> (D) 錯：中斷一個進行到一半的 `do-release-upgrade` 比走完它更危險；
> 該在升級**之前**就決定原地升級或重建遷移。
> → 詳見 [[020-01-30-guide-Linux-原始碼安裝與系統升級]] 的〈第二部分：系統大版本升級〉

## 延伸閱讀

- [[020-01-00-idx-Linux基礎]] —— 本章索引與篇章順序，錯題較多時從這裡重走一遍
- [[020-01-01-guide-Linux-Linux是什麼與發行版選擇]] —— 發行版家族判斷、codename 與支援週期
- [[020-01-02-guide-Linux-實驗環境準備與初次登入]] —— 練習環境、快照與新機六件事
- [[020-01-03-cmd-Linux-終端機與Shell入門]] —— Shell 展開、引號、歷史與 `man` 的用法
- [[020-01-04-cmd-Linux-檔案系統與目錄結構]] —— 每個目錄的用途、`/tmp` 與 sticky bit
- [[020-01-05-cmd-Linux-路徑導覽與檔案操作]] —— inode、`cp -a`、`ln -sfn` 與零停機部署
- [[020-01-06-cmd-Linux-檢視檔案內容]] —— `tail -F`、`less +F`、緩衝與日誌安全
- [[020-01-07-cmd-Linux-尋找檔案與內容]] —— `find` 的條件與動作、`xargs -0`、setuid 稽核
- [[020-01-08-cmd-Linux-檔案權限與擁有者]] —— 權限鏈、umask、特殊權限與 ACL
- [[020-01-09-cmd-Linux-使用者與群組管理]] —— UID 語意、帳號生命週期與 sudo 授權
- [[020-01-10-cmd-Linux-程序管理與訊號]] —— 訊號、`D` 與 `Z` 狀態、load 判讀與 OOM Killer
- [[020-01-11-cmd-Linux-輸入輸出重導向與管線]] —— fd、`2>&1` 順序、`pipefail` 與 `tee`
- [[020-01-12-cmd-Linux-文字處理三劍客]] —— grep／sed／awk 分工與批次改設定的安全流程
- [[020-01-13-cmd-Linux-壓縮與封存]] —— tar 選項順序、`--numeric-owner` 與備份驗證
- [[020-01-14-guide-Linux-套件管理]] —— apt／dnf、簽章與 keyring、pinning、升級保留檔
- [[020-01-15-cmd-Linux-磁碟分割與掛載]] —— 三種「磁碟滿了」、fstab 與 LVM 實務
- [[020-01-16-cmd-Linux-網路基礎指令]] —— 七層排查、netplan／nmcli 與 `curl -fsSL`
- [[020-01-17-cmd-Linux-systemd服務管理]] —— unit 優先度、drop-in、`Type=` 與資源限制
- [[020-01-18-guide-Linux-排程工作]] —— cron 的五個坑與 systemd timer 的三個獨有能力
- [[020-01-19-guide-Linux-日誌系統]] —— journal 持久化、logrotate 與日誌保留規範
- [[020-01-20-guide-Linux-環境變數與設定檔]] —— 載入順序、PATH 管理與機密不該放的位置
- [[020-01-21-cmd-Linux-Shell腳本入門]] —— shebang、引號、測試式與退出碼慣例
- [[020-01-22-guide-Linux-Shell腳本進階]] —— `set -e` 的真相、trap、冪等與鎖檔
- [[020-01-23-guide-Linux-Linux常見疑難排解]] —— 十大故障類型、重開機前清單與停手時機
- [[020-01-24-guide-進階儲存-ZFS與Btrfs]] —— vdev 佈局、ARC、快照與 send/recv
- [[020-01-25-guide-Linux-開機流程與GRUB救援]] —— 五階段分層、核心管理與 chroot 修復
- [[020-01-26-guide-Linux-核心模組與sysctl調校]] —— 模組封鎖、sysctl 載入順序與三層限制
- [[020-01-27-cmd-Linux-硬體資訊與裝置管理]] —— dmidecode、ethtool、udev 與換碟安全
- [[020-01-28-cmd-Linux-時間同步NTP與chrony]] —— slew 與 step、chronyc 判讀與 AD 時間差
- [[020-01-29-guide-Linux-網路儲存與軟體RAID]] —— NFS／SMB 掛載選項、mdadm 與監控
- [[020-01-30-guide-Linux-原始碼安裝與系統升級]] —— prefix 選擇、checkinstall 與大版本升級
- [[020-02-01-99-exam-SSH-總結小考]] —— 下一章的總複習，接著考 SSH 與遠端管理
- [[020-00-idx-Linux-總覽]] —— 回到本群組索引
