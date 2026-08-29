---
title: "系統服務與排程 總結小考"
desc: "涵蓋系統服務與排程全章的 100 題總複習：是非 50 題、選擇 50 題，附詳解與原文連結"
aliases: [系統服務與排程總複習, 系統服務與排程小考]
tags: [群組/Linux, 主題/總結小考]
category: 系統服務與排程
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: []
updated: 2026-08-29
---

# 系統服務與排程 總結小考

> [!abstract] 使用說明
> - **題數**：100 題。是非題 50 題（Q1～Q50）、選擇題 50 題（Q51～Q100）。
>   五篇教材各出 20 題（是非 10、選擇 10），題號採輪流分配，作答時不會連續踩同一篇。
> - **建議作答方式**：一次寫完 100 題再對答案，全程**不要開教材**。
>   建議 60 分鐘內完成；寫的時候把「為什麼」在心裡默唸一次，
>   答得出答案卻說不出理由的，跟猜對沒有兩樣。
> - **本章的考點不是背指令**，而是**判讀與因果**：
>   「這個情境下會發生什麼」「看到這個錯誤該先查哪裡」「這行指令會造成什麼後果」。
>   所以錯的敘述都是現場真的有人這樣講、這樣做過的誤解。
> - **及格標準與補讀建議**
>
> | 分數 | 判定 | 接下來做什麼 |
> | --- | --- | --- |
> | **90 分以上** | 可以獨立負責一台正式機的服務與排程治理 | 把答錯的那幾題對應的原文段落再讀一次即可；接著去做每一篇的「驗收檢查表」，在測試機真的跑一遍 |
> | **75～89 分** | 觀念大致正確，但踩得到坑 | 重讀答錯篇章的**常見錯誤與排錯**與**速查表**兩節；特別把「排查步驟」照順序走一次 |
> | **60～74 分** | 只停在「會用」，還沒到「可靠」 | 整章從 [[020-02-02-01-svc-systemd-unit撰寫實戰]] 依序重讀，重點放在每一篇的 danger／warning callout —— 那些就是出題來源 |
> | **60 分以下** | 基礎不足 | 先回 [[020-01-17-cmd-Linux-systemd服務管理]] 與 [[020-01-18-guide-Linux-排程工作]] 把 systemctl 與 cron 語法補齊，再回來重考 |
>
> - ★★★★ **答案在摺疊區塊裡**（`測驗答案` 那兩個 callout）。
>   請先自己作答完再展開，偷看等於白考。

---

## 是非題（50 題）

Q1. `[Unit]` 只要寫 `After=network-online.target`，開機時 `network-online.target` 就一定會被拉起來，服務也就一定等得到 IP。

Q2. `Persistent=true` 寫在只有 `OnBootSec=` 與 `OnUnitActiveSec=` 的 timer 上，關機期間錯過的那幾次開機後會補跑。

Q3. `journalctl -u cron` 裡那行 `CMD (...)`，只能證明 cron 有 fork 一個程序去執行這串字，不能證明指令存在、成功或跑完。

Q4. 用 `kill <pid>` 測 `Restart=on-failure`、發現服務沒有重啟，代表這個設定沒有生效，應該改成 `Restart=always`。

Q5. 一般使用者打的 `pm2 list` 與 `sudo pm2 list`，操作的是同一份程序清單。

Q6. 只要在 unit 寫 `RuntimeDirectory=collector`，systemd 每次啟動前都會自動建好 `/run/collector`、設好擁有者與權限，停止時再自動刪除。

Q7. `systemctl list-timers --all` 會列出這台機器上所有的 timer，包含「檔案存在但沒有 enable」的那些。

Q8. `/etc/cron.d/` 底下的檔案是「五欄時間 + 指令」，格式與使用者 crontab 完全相同。

Q9. `StartLimitIntervalSec=` 與 `StartLimitBurst=` 應該寫在 `[Unit]` 區段，不是 `[Service]`。

Q10. `pm2 startup` 產生的 unit 是 `Type=forking`，systemd 判定「啟動成功」的依據是 PM2 God Daemon，而不是你的應用。

Q11. 在 drop-in 檔裡直接寫一行 `ExecStart=/usr/local/nginx/sbin/nginx`，就會取代原本套件 unit 的 `ExecStart=`。

Q12. timer 與被觸發的 service 不同名時，必須在 `[Timer]` 區段寫 `Unit=` 明確指定。

Q13. 在 crontab 的指令欄裡，第一個未跳脫的 `%` 之後的內容會被當成標準輸入，而且之後每個 `%` 都會變成換行字元。

Q14. 只要在 unit 設了 `WatchdogSec=30s`，服務假死時就會被自動重新拉起來。

Q15. PM2 的 `kill_timeout` 預設值只有 1600 毫秒。

Q16. 寫了 `Requires=mysql.service` + `After=mysql.service` 之後，`systemctl restart mysql` 會把依賴它的 worker 一起停掉，而且 worker 不會自己回來。

Q17. 雲端主機的 image 預設時區多半是 `Etc/UTC`，此時 `OnCalendar=*-*-* 03:00:00` 實際上是台北時間上午 11 點才跑。

Q18. 用 `>>` 直接把新排程附加到 `/var/spool/cron/crontabs/<user>`，Debian／Ubuntu 的 cron 會立刻重新載入並開始執行。

Q19. 服務一直重啟、但每次都勉強起得來（從來沒進過 failed）時，`OnFailure=` 一樣會被觸發，所以還是會有人收到告警。

Q20. 架構 A（`pm2 startup` 的產物）下把 `OnFailure=` 掛在 `pm2-<user>.service` 上，即使應用全部 errored 也幾乎不會被觸發。

Q21. `ExecStartPre=` 任何一行以非 0 退出（且沒有 `-` 前綴）時，`ExecStop=` 會被跳過，只有 `ExecStopPost=` 會執行。

Q22. `systemctl --user` 建立的 timer，在該使用者登出之後仍會繼續按時執行，除非有人手動停掉它。

Q23. 在 Debian／Ubuntu 上，`/etc/cron.d/backup.cron` 這個檔名會讓整個檔案被 cron 忽略。

Q24. `Restart=always` 是最安全的預設值，不確定該選哪個模式時就選它準沒錯。

Q25. 架構 A 下，Node 應用自己的 stdout 會進 journald，所以機關的日誌集中蒐集平台收得到應用層錯誤。

Q26. `systemctl cat` 的輸出就是 systemd 實際採用的值，排錯時可以拿它當最終仲裁。

Q27. 把一支 cron 遷成 timer 時，應該先把新 timer 開起來觀察幾天，確認沒問題再去關掉舊的 crontab 那一行。

Q28. 把 flock 的鎖檔放在兩台主機共用的 NFS 目錄上，就能達成跨主機互斥。

Q29. `systemctl reset-failed <unit>` 會清掉該 unit 的 rate limit 計數，`NRestarts` 也會跟著歸零。

Q30. PM2 服務改設定後，只要 `systemctl restart` 通過就算驗收完成，不必真的重開機。

Q31. 把密碼寫在 unit 的 `Environment=` 裡，任何本機使用者都能用 `systemctl show -p Environment` 讀到，完全不需要 sudo。

Q32. `AccuracySec=` 預設是 1 分鐘，所以一支設定 03:00 的 timer 在 03:00:42 才觸發是正常的，不是故障。

Q33. 服務帳號套用「180 天強制換密碼」政策後，密碼一過期，該帳號的 cron 工作會在 PAM 的 account 階段被直接拒跑。

Q34. liveness 健康檢查應該連資料庫連不連得上也一起檢查，檢查失敗就重啟服務。

Q35. 在跑 Node 應用的 unit 裡加上 `MemoryDenyWriteExecute=yes`，是一個值得推薦的加固設定。

Q36. template unit 用 `systemctl start laravel-worker@mail` 就能跑起來，不 enable 也沒關係，反正重開機後還是會自己回來。

Q37. `/etc/cron.d/` 底下的排程完全不會出現在任何使用者的 `crontab -l` 輸出裡。

Q38. `cmd 2>&1 | logger -t x` 這條管線的退出碼是 logger 的（永遠 0），所以後面接 `|| alert.sh` 永遠不會觸發。

Q39. `StartLimitAction=reboot-force` 能讓服務更可靠，建議正式機的重要服務都加上。

Q40. `sudo -u ops pm2 list` 會去讀 `/home/ops/.pm2`，所以拿它盤點 ops 的 PM2 程序是正確的。

Q41. `network.target` 已到達，代表這台機器至少已經有一張網卡拿到 IP。

Q42. `at` 佇列（`atq`）也是排程來源之一，接手主機時必須一併盤點。

Q43. `timeout` 的退出碼 124 代表指令是被逾時強制中止的，應該與「業務失敗」分開處理。

Q44. `RestartSec=30` 搭配 `StartLimitIntervalSec=10`、`StartLimitBurst=5`，服務崩潰迴圈時會很快撞到上限而進入 failed。

Q45. `ps -eo user,args | grep 'God Daemon'` 的結果應該只有一行；出現兩行以上就是待處理的問題。

Q46. `ProtectSystem=strict` 造成服務寫不進 `/var/lib/app` 時，正確的處置是把它改成 `ProtectSystem=no`。

Q47. 被 timer 觸發的那個 service，應該保留 `[Install]` 區段，這樣才能被正確 enable。

Q48. `@reboot` 的執行時機是 cron 服務啟動的那一刻，不保證網路已可用、也不保證 NFS 已經掛好。

Q49. `Type=oneshot` 的服務不接受 `Restart=always` 與 `Restart=on-success`。

Q50. `$PM2_HOME/dump.pm2` 只有 2 bytes 時，內容是 `[]`，重開機後 `pm2 resurrect` 會還原出 0 個應用。

> [!question]- 是非題詳解（Q1～Q50）
> **Q1. ✗**
> `After=` 只決定**順序**，不決定**強度** —— 它的語意是「如果 X 也要啟動，那我排在它後面」。
> 沒有人要求啟動 X 時，`After=` 等於白寫。★★★★ 必須同時寫 `Wants=network-online.target`。
> 而且還有第二半：`systemd-networkd-wait-online.service`（NM 環境是 `NetworkManager-wait-online.service`）
> 要真的 enable，否則 target 會「秒到達」。這就是「重開機掛掉、手動 start 就正常」的頭號成因。
> → 詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]
>
> **Q2. ✗**
> `Persistent=` **只對 `OnCalendar=` 有效**（`man 5 systemd.timer` 明文）。
> 寫在 monotonic timer（`OnBootSec=`／`OnUnitActiveSec=`）上不會報錯、`systemd-analyze verify` 也不會抱怨，
> ★★★ 但完全沒有補跑效果 —— 開機後就是從 `OnBootSec=` 重新起算，漏掉的那幾次永遠不存在。
> 補跑的依據是 `/var/lib/systemd/timers/stamp-*.timer` 的 mtime，只有 realtime timer 才會產生。
> → 詳見 [[020-02-02-02-cmd-systemd-timer與cron選型]]
>
> **Q3. ○**
> ★★★★ 這是本章最重要的一句話。cron 管到「指令被叫起來」為止，之後它不在乎也不知道。
> 腳本第一行就 `command not found` 退出，syslog 長得跟成功時**一模一樣**。
> 所以「`systemctl status cron` 是 active」與「有 CMD 那一行」都不能當成「排程有成功」的證據。
> 要知道結果，只能靠腳本自己記錄，或改用 timer 的 `systemctl show -p Result`。
> → 詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]
>
> **Q4. ✗**
> ★★★★★ 全機關最普遍的測試方法誤解。`kill` 預設送 **SIGTERM，而 SIGTERM 屬於「乾淨退出」**，
> `on-failure` 遇到乾淨退出本來就不重啟 —— 設定是對的，測試方法錯了。
> 改成 `always` 的代價是：從此連「設定檔寫錯就退出」也會被無限重啟，第一層防線從保護變成放大器。
> 正確的注入方式是 `systemctl kill -s SIGKILL <unit>`。
> → 詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]
>
> **Q5. ✗**
> ★★★★★ `pm2` 與 `sudo pm2` 靠 `$HOME` 推導出**兩個不同的 `PM2_HOME`**（`/home/ops/.pm2` 與 `/root/.pm2`），
> 是兩套完全獨立的 daemon 與程序清單。連 `sudo -u ops pm2 list` 都不會換 `$HOME`，一樣讀到 `/root/.pm2`。
> 這就是「systemctl status 綠燈、整個前台卻不見」的根源：unit 指向 A，實際在服務的應用存在 B。
> 唯一安全的用法是 `sudo -iu <user> pm2 ...` 或明寫 `PM2_HOME=... pm2 ...`。
> → 詳見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]
>
> **Q6. ○**
> `RuntimeDirectory=` 由 systemd 在每次啟動前建立、把擁有者設成 `User=`／`Group=`、
> 停止時自動刪除（除非 `RuntimeDirectoryPreserve=`），並把絕對路徑塞進 `$RUNTIME_DIRECTORY` 給程式用。
> ★★★★ 反例是自己 `mkdir /run/collector` —— `/run` 是 tmpfs，重開機就空了，
> 服務寫不出 PID 檔／socket，於是「上線那天正常、三個月後停電重開就永久起不來」。
> → 詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]
>
> **Q7. ✗**
> `list-timers --all` 只列出**已載入**的 timer。只 `start` 沒 `enable` 的 timer 在本次開機期間看得到，
> ★★★★ 重開機後整支消失，連 `--all` 都看不到，因為它根本沒被載入。
> 要抓這種要用 `systemctl list-unit-files --type=timer`（檔案層），
> 或用 `comm -13` 比對「active 但沒 enabled」的清單 —— 那一行印出東西就是待處理項目。
> → 詳見 [[020-02-02-02-cmd-systemd-timer與cron選型]]
>
> **Q8. ✗**
> ★★★★ `/etc/crontab` 與 `/etc/cron.d/*` 是**六欄**：五欄時間 + **執行身分** + 指令。
> 少寫使用者欄的後果不是報錯，而是 cron 把指令路徑當成使用者名稱去查 `/etc/passwd`，
> 查不到就整行放棄，syslog 只在**存檔後一分鐘內**留下一行 `bad username`。
> 隔天才去看排程時間點的日誌，會什麼都找不到，很容易誤判成時間設定問題。
> → 詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]
>
> **Q9. ○**
> systemd 229 起這兩個指令屬於 `[Unit]`。★★★★ 寫錯區段不會報錯，只會安靜失效：
> 實測 `StartLimitIntervalSec=` 放在 `[Service]` 只有一行 `Unknown key` 警告，
> `StartLimitBurst=` 則**連警告都沒有**。於是你以為設了「五分鐘五次」，實際生效的是預設的「10 秒五次」。
> 唯一可靠的驗證是 `systemctl show -p StartLimitIntervalUSec,StartLimitBurst` 看生效值。
> → 詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]
>
> **Q10. ○**
> `Type=forking` 的判定是「父程序退出 + `PIDFile` 出現且 pid 活著」，而那個 pid 是 PM2 God Daemon。
> ★★★★ 所以 `pm2 resurrect` 還原出 0 個應用也算「啟動成功」，兩個 worker 全部 errored 時
> `systemctl status` 依然是 `active (running)`。**不能拿 `systemctl is-active` 當監控依據。**
> 補救是加健康檢查 timer 打應用端點，長期解是遷到架構 B（unit 直接跑 `pm2-runtime`）。
> → 詳見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]
>
> **Q11. ✗**
> ★★★★ `ExecStart=` 是 **list 型**指令，drop-in 裡直接寫是**追加**不是取代。
> `Type=simple`／`exec`／`notify` 會直接被拒載（`Loaded: bad-setting`，錯誤只在 `daemon-reload` 當下閃過一次）；
> `Type=oneshot` 更陰險 —— 不報錯，兩條依序執行，於是遷移做了兩次。
> 正解是先寫一行空的 `ExecStart=` 把清單歸零；驗證用 `systemctl show -p ExecStart` 看只有一個 `path=`。
> → 詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]
>
> **Q12. ○**
> 同名時可省略（`foo.timer` 預設觸發 `foo.service`），不同名就一定要寫 `Unit=`。
> ★★★ 而且 `Unit=` 拼錯時，`daemon-reload` 完全不會報錯 —— 要等觸發那一刻才在 journal 留下
> `Unit xxx.service not found.`。所以寫完一定要用 `systemctl show <timer> -p Unit` 確認一次。
> 這也是「`journalctl -u X.service` 一片空白但 `list-timers` 顯示每天都有 LAST」的成因：你查錯 unit 名了。
> → 詳見 [[020-02-02-02-cmd-systemd-timer與cron選型]]
>
> **Q13. ○**
> `man 5 crontab` 明文規定。所以 `tar czf /backup/db-$(date +%F).tar.gz /var/lib/mysql` 在 crontab 裡
> 會被截成 `tar czf /backup/db-$(date +`，後面全部變成 stdin。
> ★★★★ 最可怕的是它可能「成功」建出一個空檔案然後 exit 0 —— 沒有錯誤、監控全綠，直到要還原那天。
> 修法可以跳脫成 `\%`，但正解是**把整段搬進腳本**，crontab 指令欄只留一個絕對路徑加參數。
> → 詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]
>
> **Q14. ✗**
> ★★★★ watchdog 只負責「殺」，不負責「復活」。逾時後 systemd 送 `WatchdogSignal=`（預設 SIGABRT），
> 之後走 `Restart=` 矩陣的「watchdog 逾時」那一列；`Restart=no` 就是**就地停機**。
> 結果是：本來只是「服務很慢」，設了 watchdog 之後變成「服務完全消失」，比不設更糟。
> 另一個前提是主程序真的送得到 `WATCHDOG=1`；心跳由子程序送的話要 `NotifyAccess=all`。
> → 詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]
>
> **Q15. ○**
> ★★★★ 1600 毫秒對任何有 graceful shutdown 的 Node 應用都遠遠不夠（實測 T_app 通常 3～15 秒）。
> 這是「每次部署都有零星 502、資料庫寫入不完整」最常見的漏設項。
> 建議值是 `kill_timeout: 30000`，並讓 systemd 的 `TimeoutStopSec=45` 大於它，
> 三層關係必須是：T_app ≤ `kill_timeout` ≤ `TimeoutStopSec`。
> → 詳見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]
>
> **Q16. ○**
> ★★★ `Requires=` 的傳播是**停止**，不是重啟。資料庫做維護 `systemctl restart mysql`，
> 依賴它的 5 個 worker 會被一起停掉，維護窗口結束後沒有人記得把它們拉回來，郵件靜靜堆積三天。
> 通則是**預設用 `Wants=` + `After=`**，把「連不上就重試」的責任交給應用與 `Restart=on-failure`。
> 只有「對方不在我就絕對不該存在」（綁定某個 VPN 介面、LUKS 裝置）才用 `Requires=`／`BindsTo=`。
> → 詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]
>
> **Q17. ○**
> ★★★★ realtime timer 依**系統時區**計算 `OnCalendar=`。你照文件寫 03:00 想避開尖峰，
> 實際是上午 11 點開始跑重量級備份，正好打在業務尖峰上。
> 判斷方式：`systemd-analyze calendar '*-*-* 03:00:00'` 的 `Next elapse` 與 `(in UTC)` 兩行**相同**，
> 就代表這台是 UTC。解法優先選 `timedatectl set-timezone Asia/Taipei`；時區後綴寫法要看 systemd 版本。
> → 詳見 [[020-02-02-02-cmd-systemd-timer與cron選型]]
>
> **Q18. ✗**
> ★★★ Debian／Ubuntu 的 cron 是靠 **spool 目錄的 mtime** 判斷有沒有人改過。
> `>>` 只改到檔案 mtime，目錄 mtime 沒變，cron 就不會重新載入 ——
> 結果是 `crontab -l` 看得到新排程，但它**永遠不會執行**，直到有人用 `crontab` 指令改過或 cron 重啟。
> 這種「看得到、不會跑」最難查。正解永遠是 `crontab <file>`；RHEL 的 cronie 用 inotify 沒這問題。
> → 詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]
>
> **Q19. ✗**
> ★★★★ `OnFailure=` **只在 unit 進入 failed 時觸發**。一直重啟但每次都勉強起得來的服務，
> 從沒進過 failed，所以永遠不告警 —— 這是本章最大的一個洞。
> 成因通常是 `RestartSec` 大於 `StartLimitIntervalSec`，永遠撞不到上限。
> 補法有兩個：把三個參數調到「撞得到上限」，再加一支比 `NRestarts` **差值**的巡檢 timer。
> → 詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]
>
> **Q20. ○**
> 架構 A 下 `pm2-<user>.service` 監看的是 God Daemon，而 daemon 本身很少死。
> ★★★★ 所以掛在它身上的 `Restart=on-failure` 只會重啟 daemon、`OnFailure=` 幾乎不會觸發。
> 架構 A 下唯一可靠、真的能發現「應用死了」的一層，是**打應用健康端點的健康檢查 timer**，
> 而且 `OnFailure=` 要掛在那支健康檢查 unit 上才有意義。
> → 詳見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]
>
> **Q21. ○**
> ★★★ 啟動階段失敗時 systemd 會**跳過 `ExecStop=`**，只跑 `ExecStopPost=`。
> 所以清理邏輯（刪 lock 檔、清暫存）一定要放在 `ExecStopPost=`，放 `ExecStop=` 就有可能不執行。
> 相關規則還有：多行 `ExecStartPre=` 依序執行、任一行非 0 就整個啟動失敗；
> 想讓某一行「失敗也無所謂」就加 `-` 前綴。
> → 詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]
>
> **Q22. ✗**
> ★★★★ 這是機關「排程默默停掉數月」的典型劇本。使用者最後一個 session 結束的那一刻，
> systemd 收掉他的 user manager，所有 `--user` timer 一起被殺 ——
> 沒有錯誤、沒有日誌、system 層的 `systemctl list-timers` 完全正常。
> 過渡期可以 `loginctl enable-linger`，但正解是改寫成 system timer 用 `User=` 指定身分：
> 業務排程的存活不能依賴某個自然人的登入狀態。
> → 詳見 [[020-02-02-02-cmd-systemd-timer與cron選型]]
>
> **Q23. ○**
> ★★★★ Debian／Ubuntu 的 cron 對 `/etc/cron.d/` 只允許 `[A-Za-z0-9_-]`，含 `.` 一律忽略整檔。
> 但 RHEL 的 cronie 只擋開頭 `.`／`#` 與結尾 `~`／`.rpm*`，`backup.cron` **會執行** ——
> 所以同一份 Ansible playbook 在 RHEL 正常、搬到 Ubuntu 就整檔失效。
> 一律用不含點的檔名兩邊都安全。另外兩個讓整檔被忽略的原因是：權限不是 644 root、檔尾少換行。
> → 詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]
>
> **Q24. ✗**
> ★★★★ `always` 連「乾淨退出」都重啟，等於把「設定檔錯誤就退出」變成無限迴圈：
> 每 100 毫秒重啟一次、把 journal 灌爆、把 CPU 吃滿，並且掩蓋真正的錯誤。
> 官方對長時間執行的網路服務推薦的是 `on-failure`，而且 `systemctl stop` 不會被它打回來。
> 真正該記的預設是：`Restart=on-failure` + `RestartSec=10` + `[Unit]` 的 `300`／`5` + `OnFailure=`。
> → 詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]
>
> **Q25. ✗**
> ★★★ 架構 A 下只有 God Daemon 自己的訊息（`PM2 log: App [x] online`）進 journal；
> worker 的 stdout 被 PM2 攔到 `$PM2_HOME/logs/<name>-out.log`，集中蒐集根本收不到。
> 於是稽核問「上週三 14:20 那次 5xx 的應用日誌在哪」，答案是「在某台機器某個家目錄的檔案裡」。
> 裝 `pm2-logrotate` 解決的是磁碟不是可見性；真正的解法是架構 B／C 讓 stdout 直接進 journald。
> → 詳見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]
>
> **Q26. ✗**
> ★★★★ `systemctl cat` 只是把檔案接起來給你看，證明的是「你寫了什麼」；
> `systemctl show <unit> -p <屬性>` 才是「systemd 收下了什麼」，那才是最終仲裁。
> 兩者會不一致的典型情境：drop-in 沒清空造成兩條 `ExecStart=`、`StartLimitBurst=` 寫錯區段被靜靜忽略。
> 排錯順序記成：`cat` 看來源與合併結果 → `show` 看生效值 → 兩者對不上就去找 drop-in。
> → 詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]
>
> **Q27. ✗**
> ★★★★ 順序反了就會「兩邊都在跑」。「先開新的觀察幾天」聽起來穩健，實際是最常見的遷移事故：
> 資料拋轉讓對方機關收到兩份被退件、增量備份鏈斷裂、有 flock 的工作被跳過一次看起來正常、帳務算兩次。
> 標準八步裡【6】先停舊 cron 一定要在【7】enable 新 timer 之前，
> 中間空窗一個週期是可以接受的；真的不能空窗就手動 `systemctl start <name>.service` 補一次。
> → 詳見 [[020-02-02-02-cmd-systemd-timer與cron選型]]
>
> **Q28. ✗**
> ★★★★ NFS 上 `flock()` 是被模擬成 fcntl byte-range lock，而掛載選項 `nolock`、`local_lock=all`
> 會讓它變成**純本機鎖** —— 兩台主機各自都拿得到鎖，同時對同一份資料寫入。
> CIFS 更糟，語意隨伺服器實作而異。檢查方式是 `findmnt -t nfs,nfs4,cifs -o TARGET,OPTIONS`。
> 正解是鎖放本機 `/run/lock/`，跨主機互斥改用資料庫 advisory lock，或架構上只讓一台跑。
> → 詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]
>
> **Q29. ○**
> `reset-failed` 會 flush 該 unit 的 rate limit 計數，也會把 `NRestarts` 歸零。
> ★★★★ 這正是「修好根因之後 `systemctl start` 仍一直回 `Job for x.service failed`」的解法，
> 而錯誤訊息跟原因完全無關，值班人員很容易卡在這裡，所以要寫進部署腳本與交接文件。
> ★★★ 副作用是巡檢不能比 `NRestarts` 的絕對值 —— 每次維護後基準都會漂移，必須比差值。
> → 詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]
>
> **Q30. ✗**
> ★★★★ `systemctl restart` 通過**不代表**開機會成功，兩者的差異剛好涵蓋四類最難查的問題：
> `PM2_HOME`／dump 不一致（daemon 還在，沿用記憶體中的清單）、PATH／node 路徑錯、
> 掛載相依尚未就緒、啟動順序、以及 `systemctl enable` 漏做 —— restart 一個都測不出來。
> 「不敢重開機」的機器就是「不知道能不能開起來」的機器，要照變更管理的節奏申請維護窗做完整驗收。
> → 詳見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]
>
> **Q31. ○**
> ★★★★★ `systemctl show <unit> -p Environment` 不需要 sudo、不需要讀檔權限，
> 而且 unit 檔本身預設 0644 全機可讀，`ps aux` 還會把指令列參數整串印出來。
> 這些內容會被監控與 `journalctl` 一起蒐走，形成長期保存的外洩，個資法下屬於「未採取適當安全措施」。
> 正解是 `EnvironmentFile=`（640 root:服務帳號），`systemctl show` 只會顯示檔案路徑；
> 更嚴謹用 `LoadCredential=`／`systemd-creds`。已經寫過的密碼一律視為外洩並更換。
> → 詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]
>
> **Q32. ○**
> `AccuracySec=` 預設 1min（systemd 為了省電會把附近的喚醒合併），再疊上 `RandomizedDelaySec=`
> 就會出現 03:00:42 才跑。★★★ 這不是故障，是設計。
> 反過來說，如果對方系統只收 09:00:00～09:00:05 的封包，就必須 `AccuracySec=1s` 且不設隨機延遲；
> 而 60 台主機打同一個目標時則要反過來設 `RandomizedDelaySec=1800`。兩種需求剛好相反，不要抄錯。
> → 詳見 [[020-02-02-02-cmd-systemd-timer與cron選型]]
>
> **Q33. ○**
> ★★★★ 這是機關環境的第一名。cron 執行前會走 `/etc/pam.d/cron` 的 account 階段，
> `pam_unix` 檢查 `/etc/shadow` 的到期欄位，過期就直接拒跑，syslog 留下
> `account has expired` 或 `Authentication token is no longer valid`。
> 症狀是「資安政策上路半年後，所有服務帳號的排程在同一個週末集體停擺，而且沒人收到通知」。
> 正解：服務帳號 `chage -M -1 -E -1`，並用 `passwd -l` 鎖住密碼登入。
> → 詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]
>
> **Q34. ✗**
> ★★★★ 那是 readiness（深檢查），**只該驅動告警，絕對不要驅動重啟**。
> 資料庫做三十分鐘維護時，所有前端每分鐘被重啟一次，每次重啟又建立一批新連線，
> connection 風暴讓資料庫更起不來 —— 你親手把「一個服務不可用」升級成「全站雪崩」。
> liveness 要用淺檢查（程序活著嗎、埠有回應嗎），並且要有重啟預算與維護旗標。
> → 詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]
>
> **Q35. ✗**
> ★★★ Node 的 V8 JIT 需要同時可寫又可執行的記憶體頁，加了這行的症狀是服務啟動後立刻
> `SIGSEGV` 或 `Failed to allocate executable memory`。開了 JIT 的 PHP 8 也一樣。
> 對這類服務就把這一行拿掉，**其餘沙箱選項照留** —— 不要因為一項不能用就整組放棄。
> 這也是「加了沙箱後 Node 直接 crash」在排錯表裡的標準答案。
> → 詳見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]
>
> **Q36. ✗**
> ★★★★ `start` 與 `enable` 是兩件事。template unit 的坑在於「上線當天三個都在跑、測試全過」，
> 但只 enable 了 `default`，**重開機後只有 default 回來**，另外兩條 queue 從此沒人處理。
> 沒有錯誤日誌、沒有 alert，只有使用者三天後問「為什麼沒收到通知信」。
> 上線前固定檢查 `ls /etc/systemd/system/multi-user.target.wants/ | grep '^app@'`，數量要對得上。
> → 詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]
>
> **Q37. ○**
> ★★★★ `crontab -l` 只列出「你當下這個身分」的使用者 crontab。
> 它看不到 `/etc/cron.d/`、看不到 `/etc/crontab`、看不到別的使用者的 crontab、
> 看不到任何 systemd timer，也看不到 Laravel `schedule:run` 那一行背後的三十個工作。
> 「只跑 `crontab -l` 就回報這台沒有排程」，等於把未來的每一次事故都變成考古題。
> → 詳見 [[020-02-02-02-cmd-systemd-timer與cron選型]]
>
> **Q38. ○**
> ★★★★ 管線的退出碼是最後一個指令的，`logger` 永遠成功，所以 `||` 永遠不觸發，
> 連 cron 的 `-L 15` 記錄到的 `FAILED (exit status N)` 都會變成 0。
> 三種正解：①（最推薦）讓腳本自己 logger、自己判斷、自己通報，crontab 行保持乾淨；
> ② 導到專屬 log 檔不經管線；③ 一定要用管線就 `SHELL=/bin/bash` 並 `set -o pipefail`。
> → 詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]
>
> **Q39. ✗**
> ★★★★★ 一台主機通常跑不只一個系統。申辦系統的 worker 撞上限就整台重開，
> 同一台上的公文系統、報表系統、資料庫全部一起斷線 —— 一個系統拖垮五個系統。
> `reboot-force` 不做正常關機程序，有檔案系統損毀與資料遺失風險；
> 而若根因是設定檔錯誤，重開機修不好它，你會得到**無限重開機迴圈**，只能靠帶外管理救。
> 一般伺服器一律留在預設 `none`，靠 `OnFailure=` 叫人來看。
> → 詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]
>
> **Q40. ✗**
> ★★★ `sudo -u ops` **不會**重設 `$HOME`（除非 sudoers 有 `always_set_home`），
> 所以它會去讀 `/root/.pm2` 然後回報「空的」，害你誤判成「這台沒有 PM2 程序」。
> 正確寫法是 `sudo -iu ops pm2 list`（會換 HOME），或最明確的 `PM2_HOME=/home/ops/.pm2 pm2 list`。
> 全機器只准有一個 `PM2_HOME`，並且在 unit 裡寫**絕對路徑**，不要靠 `$HOME` 推導。
> → 詳見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]
>
> **Q41. ✗**
> ★★★★ `network.target` 的語意只是「網路**子系統**已經啟動」（那個 daemon 起來了），
> 不代表任何一張網卡拿到 IP。綁定特定位址的服務會得到 `Cannot assign requested address`。
> 要等到真的可用必須 `After=` + `Wants=network-online.target`，而且對應的 wait-online 服務要 enable。
> 再往上一階：`network-online.target` 也只保證有 IP，不保證 DNS 解得開（那要 `nss-lookup.target`）。
> → 詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]
>
> **Q42. ○**
> 八個排程來源之一。★★★ 現場常見的是「前手排的臨時還原」躺在佇列裡一年沒拆，
> 到期那天會把現在的設定檔蓋回一年前的版本。
> 盤點時用 `sudo atq` 看有沒有東西、`sudo at -c <id>` 看它到底要做什麼，
> **一律要問清楚才決定 `atrm`**，不要看到不認識就刪。
> → 詳見 [[020-02-02-02-cmd-systemd-timer與cron選型]]
>
> **Q43. ○**
> ★★★★ 退出碼分類是生產級排程的必備元素：0 成功／1 業務失敗／2 環境失敗／
> 75 被跳過或暫時性／124 逾時被砍。監控端才有辦法決定「要不要叫人半夜起床」。
> 而且 `timeout` 要寫成 `--signal=TERM --kill-after=30s`，沒有 `--kill-after` 就可能還是卡住；
> 也**不要**加 `--preserve-status`，那會讓你失去 124 這個訊號。
> → 詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]
>
> **Q44. ✗**
> ★★★★ 剛好相反：30 秒才重啟一次，10 秒的滑動窗口內永遠只有 1 次啟動，**永遠撞不到上限**，
> 於是無限重啟 —— 一夜 2880 次、把 journal 灌爆 `/var`，而且因為沒進 failed，`OnFailure=` 不觸發。
> 臨界條件大致是 `RestartSec × (Burst − 1) < StartLimitIntervalSec`（實際還要加上服務從啟動到死掉的時間）。
> 機關建議基準是 `RestartSec=10` / `StartLimitIntervalSec=300` / `Burst=5`：五分鐘五次不行就放棄並告警。
> → 詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]
>
> **Q45. ○**
> ★★★★★ 出現兩行代表有兩套獨立的程序清單並存（多半是某次 `sudo pm2 list` 讓 PM2 自己又啟了一個）。
> 兩種結局都很難查：第二份搶不到埠就一直 `errored`（但服務其實是好的，沒人發現）；
> 第二份搶到了埠，對外服務的就變成**舊版本的程式碼** —— 部署明明成功、頁面卻沒更新。
> 巡檢時 `ps -eo user,args | grep -c 'God Daemon'` 的結果必須是 1。
> → 詳見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]
>
> **Q46. ✗**
> ★★★ 那是「臨時處置變成永久設定」的典型，一行就退回沒有保護的狀態。
> 正解是把「這個服務該寫哪裡」講清楚：用 `StateDirectory=`（它會自動加進可寫清單）、
> `LogsDirectory=`、`ReadWritePaths=` 明確開放最小範圍。
> 找出它想寫哪裡的手法是 `journalctl -u <unit> | grep -iE 'read-only|permission denied'`。
> → 詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]
>
> **Q47. ✗**
> ★★★★ 剛好相反：被 timer 觸發的 service **不要**有 `[Install]` 區段。
> 有 `[Install]` 就可能被誤 `enable`，變成「開機跑一次 + timer 再跑一次」。
> 需要 `[Install] WantedBy=timers.target` 的是 **timer 本身** —— 少了它 `enable` 會失敗，
> 錯誤訊息是 `The unit files have no installation config`，而 `is-enabled` 會回 `static`。
> → 詳見 [[020-02-02-02-cmd-systemd-timer與cron選型]]
>
> **Q48. ○**
> `systemctl show cron -p After` 裡**沒有** `network-online.target`、`mysql.service`、`nfs-client.target`。
> ★★★★ 最嚴重的後果是：NFS 還沒掛載，腳本對著空目錄做 `rsync --delete`，把遠端資料刪光。
> 而且 `@reboot` 在容器常見的 BusyBox crond 上根本不支援 —— `crontab -l` 看得到，它就是不會執行。
> 正式環境的正解是寫成 systemd unit，用 `Requires=<mount>`、`After=network-online.target` 宣告相依。
> → 詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]
>
> **Q49. ○**
> `systemd.service(5)` 明文：oneshot 服務在乾淨退出時永遠不會被重啟，
> 所以 `always` 與 `on-success` 對它是被拒絕的（`on-failure` 則可以）。
> ★★★ 這對本章很重要：健康檢查、巡檢、timer 觸發的工作都是 oneshot，
> **它們的重試要靠 timer 的下一次觸發，不是靠 `Restart=`**。
> → 詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]
>
> **Q50. ○**
> ★★★★★ 2 bytes 就是 `[]`。`dump.pm2` 是「當下狀態的**快照**」不是「設定檔」，
> `pm2 resurrect` 開機時讀的就是它 —— 空的就還原出 0 個應用，而 `systemctl status` 依然綠燈。
> 診斷時一併看 `stat -c '%y %s' $PM2_HOME/dump.pm2`，時間戳停在三年前也是同一類問題。
> 根本解是架構 B：unit 直接寫死要跑哪一份 ecosystem，`pm2 save` 這個會忘記的步驟從流程裡消失。
> → 詳見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]

---

## 選擇題（50 題）

Q51. 一支自寫服務「重開機後 failed，你上去手動 `systemctl start` 就完全正常」。最該先查的是什麼？
(A) 應用程式本身有 bug，先看程式碼 (B) 磁碟空間不足 (C) `[Unit]` 只寫了 `After=X` 沒寫 `Wants=X`，開機時 X 根本沒被拉起來 (D) `systemctl enable` 沒做

Q52. `systemctl list-timers --all` 顯示某支 timer 的 `NEXT` 欄是 `n/a`，這代表什麼？
(A) 它已經不會再觸發了（timer 停止，或運算式已無下一次） (B) 它剛建立，還沒到第一次觸發時間 (C) 它現在正在執行中 (D) 它每次都準時，所以不需要顯示

Q53. `/etc/cron.d/data-sync` 存好之後，排程時間到了完全沒動靜，`journalctl --since "02:00"` 也什麼都查不到。下一步最該做什麼？
(A) 檢查腳本語法有沒有錯 (B) 重開機讓 cron 重讀設定 (C) 把 `MAILTO` 設起來以便收到錯誤信 (D) 看**存檔後那一分鐘**的 `journalctl -u cron`，找 `bad username`／`BAD FILE MODE`／`Missing newline`

Q54. 某服務 `systemctl status` 顯示 `active (running)`，但 `systemctl show -p NRestarts` 是 2873，`ActiveEnterTimestamp` 是幾秒鐘前。最可能的原因是？
(A) 服務很健康，只是剛部署完 (B) `RestartSec` 大於 `StartLimitIntervalSec`，永遠撞不到上限，於是無限重啟 (C) 已經撞到 StartLimit 進了 failed (D) 沒有設 `WatchdogSec=`

Q55. `systemctl status pm2-ops` 是綠燈，但網站對外一直回 502。最直接的成因是什麼？
(A) `Type=forking` + `PIDFile` 監看的是 PM2 God Daemon，worker 全部 `errored` 也不影響判定 (B) Nginx 反向代理設定錯誤 (C) 3000 埠被別的程序佔用 (D) PM2 版本太舊需要升級

Q56. 要用 drop-in 換掉套件 unit 的 `ExecStart=`，正確寫法是？
(A) 直接寫一行新的 `ExecStart=` 就會取代舊的 (B) 用 `systemctl edit --runtime` 才會生效 (C) 直接編輯 `/usr/lib/systemd/system/` 底下的原檔 (D) 先寫一行空的 `ExecStart=` 把清單歸零，再寫新值

Q57. 全機關 60 台同一份 image 佈署的主機都在 02:00 向同一台內部 mirror 抓套件，被資安設備判定成 DDoS。最恰當的處理是？
(A) 把 `AccuracySec=` 設成 `1s` 讓它更準時 (B) 加 `RandomizedDelaySec=1800`，必要時搭 `FixedRandomDelay=true` (C) 每台人工改成不同的分鐘數 (D) 全部改回用 cron 執行

Q58. 一支排程「從某天起再也沒跑過」，而且沒有任何錯誤訊息。最該先查什麼？
(A) `chage -l` 看帳號有沒有到期 (B) `timedatectl` 看時區有沒有被改過 (C) `fuser -v <鎖檔>` 看有沒有卡死的舊程序一直佔著 flock (D) 檢查 rsyslog 有沒有把 cron 濾掉

Q59. 要驗證 `Restart=on-failure` 真的會在服務崩潰時把它拉起來，正確的故障注入方式是？
(A) `systemctl kill -s SIGKILL <unit>` (B) `kill <pid>` (C) `systemctl stop <unit>` (D) `systemctl restart <unit>`

Q60. PM2 情境下三個停機逾時必須成立的關係是？
(A) `TimeoutStopSec` ≤ `kill_timeout` ≤ T_app (B) `kill_timeout` ≤ T_app ≤ `TimeoutStopSec` (C) 三者互不相干，各自設合理值即可 (D) T_app ≤ `kill_timeout` ≤ `TimeoutStopSec`

Q61. 服務要把資料寫到 NFS 掛載的 `/srv/share/uploads`，避免「掛載還沒完成就啟動而把檔案寫進被蓋住的本機空目錄」，最正確的做法是？
(A) `After=network.target` (B) `RequiresMountsFor=/srv/share/uploads` (C) `ExecStartPre=/bin/sleep 30` (D) `Requires=network-online.target`

Q62. 前手用自己帳號設的 `systemctl --user` timer 在他離職後默默停了數月。機關環境最正確的長期解法是？
(A) `loginctl enable-linger <user>` 就夠了 (B) 請該員定期回來 SSH 登入維持 session (C) 改寫成 system timer，用 `User=` 指定執行身分 (D) 改成 `@reboot` 的 cron

Q63. 下列哪一種寫法可以讓監控端分辨「這一輪被鎖跳過（正常）」與「這一輪真的執行失敗」？
(A) `flock -n -E 75` (B) `flock -n` (C) `flock -w 60` (D) `flock`（不加任何參數）

Q64. 委外的 Java 服務沒有原始碼，你想處理它偶爾「假死」的問題。正確做法是？
(A) 設 `WatchdogSec=30s` 讓 systemd 監看它 (B) 設 `Restart=always` (C) 開啟 `RuntimeWatchdogSec=` 硬體 watchdog (D) 用健康檢查 timer 從外面打 `/healthz`

Q65. `ps -eo user,args | grep 'God Daemon'` 出現兩行，`PM2_HOME` 分別是 `/home/ops/.pm2` 與 `/root/.pm2`。最可能的後果是？
(A) 只是多用一點記憶體，實務上無害 (B) systemd 會自動把兩份合併成一份 (C) 兩套獨立清單並存，對外服務的可能是舊版本，出現「部署成功但頁面沒更新」 (D) PM2 會偵測到衝突並拒絕啟動

Q66. Laravel worker 收到 SIGTERM 後會把手上那筆最長 5 分鐘的報表 job 做完再退出。`TimeoutStopSec=` 該怎麼設？
(A) 設成 ≥ 單筆 job 最長執行時間 + 緩衝（例如 360） (B) 保持預設 90s 就好 (C) 設成 30s 讓部署快一點 (D) 設 `SendSIGKILL=no` 讓它永遠不被砍

Q67. `systemd-analyze calendar --base-time='2026-01-28' --iterations=4 '*-*-29 04:00:00'` 這個指令的用途是？
(A) 讓 timer 立刻觸發一次做測試 (B) 驗證運算式在跨月底／閏年這種邊界會不會整個月被跳過 (C) 檢查 timer 有沒有 enable (D) 檢查系統時區設定是否正確

Q68. 下列哪一個是「這一行該從 crontab 搬進腳本」的判斷訊號？
(A) 指令是一個絕對路徑加幾個參數 (B) 這一行有指定執行使用者 (C) 時間欄用了 `*/15` 這種語法 (D) 指令欄出現 `%`、`|`、`&&`、`$(...)` 或引號

Q69. 某服務因為設定檔語法錯誤，每次都以 exit 78 結束。最恰當的處置是？
(A) 設 `Restart=always` 讓它一直重試 (B) 設 `SuccessExitStatus=78` 把它視為成功 (C) 設 `RestartPreventExitStatus=78`，直接進 failed 讓 `OnFailure=` 立刻叫人 (D) 設 `RestartSec=1` 加快恢復速度

Q70. 機關正式機上跑 Node 服務，本章建議的架構預設答案是？
(A) 架構 B：自寫 unit 跑 `pm2-runtime` (B) 架構 A：`pm2 startup` 的產物 (C) 架構 C：純 systemd template unit (D) 不用任何程序管理器，直接 `nohup` 背景執行

Q71. 想在「不落檔、不重啟正式服務」的前提下，試跑一組 unit 屬性（`User=`、`EnvironmentFile=`、`ProtectSystem=`）看會不會爆，最合適的工具是？
(A) `systemctl edit --full` 改完再 restart (B) `systemd-delta` (C) `systemctl daemon-reload` (D) `systemd-run --unit=trial --collect --property=... <指令>`

Q72. 選型決策樹裡「失敗需不需要有人知道」這一題，正確的問法是？
(A) 這支排程重不重要 (B) 這支失敗一整個月都沒人知道，會怎樣 (C) 這支要跑多久 (D) 這支是誰寫的

Q73. `/etc/crontab` 預設 `SHELL=/bin/sh`，而 Ubuntu 的 `/bin/sh` 是 dash。下列哪一個寫法會出問題？
(A) `/usr/local/bin/x.sh` (B) `cmd >> /var/log/x.log 2>&1` (C) `cmd &> /var/log/x.log` (D) `cmd`

Q74. 一般網路服務的自動復原，本章給的機關建議基準是？
(A) `RestartSec=10` / `StartLimitIntervalSec=300` / `StartLimitBurst=5` (B) 保持預設 `RestartSec=100ms` / `10s` / `5` (C) `RestartSec=30` / `StartLimitIntervalSec=10` / `StartLimitBurst=5` (D) `Restart=always` 且不設 StartLimit

Q75. unit 裡寫的是 `PM2_HOME=/home/ops/.pm2`，但 `/proc/<監聽 3000 埠的 pid>/environ` 顯示 `PM2_HOME=/root/.pm2`。這代表什麼？
(A) 沒關係，PM2 會自動同步兩邊 (B) unit 設定不生效，但服務一切正常 (C) 這是 PM2 的已知 bug，升級即可 (D) 對外服務的是另一個 daemon；重開機後 systemd 起的那份會 resurrect 出 0 個應用

Q76. 哪一種 `Type=` 能讓 systemd 抓到「設定檔錯、埠被佔用、資料庫連不上」這類啟動失敗？
(A) `simple` (B) `notify` (C) `forking` (D) `exec`

Q77. `systemctl is-enabled X.timer` 回傳 `static`，代表？
(A) 這個 unit 檔沒有 `[Install]` 區段 (B) 已經正確啟用，開機會自己起來 (C) 它被 `mask` 了 (D) 檔案不存在

Q78. 排程手動跑得動、cron 跑就 `command not found`。最能重現問題的做法是？
(A) `sudo bash /usr/local/bin/x.sh` (B) 重開機之後再跑一次 (C) `sudo -u <u> env -i PATH=/usr/bin:/bin HOME=... bash -c '/usr/local/bin/x.sh'` (D) 把腳本補上執行位元再跑

Q79. 告警腳本裡的哪一個設計，是為了避免「資料庫掛掉時三十個服務同時 failed，於是發出三十封告警」？
(A) `set -euo pipefail` (B) 用 `systemd-escape -u` 還原跳脫過的 unit 名 (C) `TimeoutStartSec=30` (D) 用時間戳做五分鐘去重（`DEDUP_SEC`）

Q80. 部署腳本裡寫 `pm2 restart nuxt-app` 而不走 systemd，最主要的壞處是？
(A) 執行速度比較慢 (B) systemd 完全不知情：`ActiveEnterTimestamp` 失真、版本追蹤查不到，而且沒 `pm2 save` 時 dump 仍是舊的 (C) 會造成記憶體洩漏 (D) PM2 會拒絕執行這個指令

Q81. 服務加了 `ProtectHome=yes` 之後讀不到程式碼，因為程式碼部署在 `/home/deploy/app`。最正確的處置是？
(A) 把程式碼搬到 `/srv` 或 `/opt`；真的不能搬才降成 `ProtectHome=read-only` (B) 改成 `ProtectHome=no` (C) 改成 `User=root` (D) 加上 `PrivateTmp=no`

Q82. 把 cron 那一行（含 `|` 與 `>`）原封不動貼進 `ExecStart=`，會發生什麼？
(A) 一切正常，systemd 會自動用 shell 執行 (B) `daemon-reload` 當下就會報錯拒絕載入 (C) systemd 不經過 shell，`|`、`>`、`&&` 全被當成參數傳給第一個執行檔 (D) 只有萬用字元會失效，管線仍然正常

Q83. 下列哪一行 crontab 最符合「cron 只負責什麼時候呼叫誰，記錄與通報是腳本的責任」？
(A) `0 2 * * * u /usr/local/bin/x.sh >/dev/null 2>&1` (B) `0 2 * * * u /usr/bin/timeout --signal=TERM --kill-after=30s 45m /usr/local/bin/x.sh` (C) `0 2 * * * u /usr/local/bin/x.sh 2>&1 | logger -t x || alert.sh` (D) `0 2 * * * u /usr/local/bin/x.sh &`

Q84. 設了 `WatchdogSec=30s` 之後，服務每 30 秒被 SIGABRT 一次然後就停在那裡。最可能的兩個原因是？
(A) 時區錯誤與 NTP 沒同步 (B) `AccuracySec=` 設得太小 (C) journal 磁碟滿了 (D) 應用根本沒送 `WATCHDOG=1`，而且 `Restart=` 是 `no`／沒設

Q85. 在架構 A（`pm2 startup` 產物）之下，唯一可靠、真的能發現「應用死了」的一層是？
(A) 打應用健康端點的健康檢查 timer (B) `systemctl is-active pm2-ops` (C) `pm2 list | grep online` (D) unit 上的 `Restart=on-failure`

Q86. `ExecStartPre=+/srv/www/app/scripts/pre-start.sh` 這樣寫的風險是？
(A) 只是執行效能比較差 (B) 沙箱會把它擋下來，所以不會有事 (C) 任何能寫入那支腳本的人（CI、deploy key、廠商帳號），等下一次 `systemctl restart` 就取得 root 執行權 (D) 服務會起不來

Q87. 遷移八步中，為什麼【6】先停舊 cron 一定要在【7】enable 新 timer 之前？
(A) 只是慣例，順序其實無所謂 (B) systemd 會拒絕與 cron 同時存在 (C) cron 會鎖住 timer 的觸發 (D) 兩邊同時開會造成資料拋轉兩份、增量備份鏈斷裂、帳務算兩次

Q88. 導入 TWGCB／CIS 基準時建立了 `/etc/cron.allow` 只放 root，當晚所有服務帳號的排程全部停止。最直接的成因是？
(A) `cron.allow` 一存在，`cron.deny` 完全失效，清單外的帳號不能使用「使用者 crontab」 (B) `cron.deny` 沒有一併刪除 (C) cron 服務被基準腳本停掉了 (D) SELinux 把 cron 擋住了

Q89. 根因已經修好，但 `systemctl start x.service` 一直回 `Job for x.service failed`。下一步該做什麼？
(A) 重開機 (B) `systemctl reset-failed <unit>` 之後再 `start` (C) `systemctl daemon-reload` (D) `systemctl unmask <unit>`

Q90. `systemctl stop pm2-ops` 之後 `is-active` 回 `inactive`，但 3000 埠仍被佔用，`cat /proc/<pid>/cgroup` 顯示 `user@1000.service`。這代表？
(A) unit 的 `ExecStop=` 沒殺乾淨，要調大 `TimeoutStopSec` (B) 埠被完全無關的服務佔用 (C) 那個程序是有人在 SSH session 手動起的，不在 unit 的 cgroup 內，`systemctl stop` 殺不到 (D) `KillMode=` 應該改成 `process`

Q91. 「重開機後只有一條 queue 在跑，另外兩條靜默堆積，三天後使用者才反映沒收到通知信」，最可能的原因是？
(A) MySQL 開機時沒起來 (B) 記憶體不足被 OOM killer 殺掉 (C) 磁碟已滿 (D) template unit 只 `enable` 了一個實例，其他兩個當初只是 `start` 過

Q92. 下列哪一個是「刻意留在 cron、不遷 timer」的合理理由（可寫進盤點表備註欄）？
(A) 容器內沒有 systemd／套件自帶升級會被覆蓋／第三方廠商合約維護 (B) cron 執行速度比較快 (C) 團隊比較熟 cron 語法 (D) timer 不支援每分鐘執行

Q93. `tail -c1 /etc/cron.d/data-sync | xxd` 沒有輸出 `0a`，代表？
(A) 檔案是空的 (B) 檔尾少了換行字元，這一檔會被 cron 整個忽略 (C) 檔案編碼不是 UTF-8 (D) 檔案權限不是 644

Q94. 下列哪一個設定在「一台跑五個系統」的機關共用主機上幾乎永遠是錯的？
(A) `Restart=on-failure` (B) `RestartSec=10` (C) `StartLimitAction=reboot-force` (D) `OnFailure=alert@%n.service`

Q95. 從架構 A 遷到架構 B（unit 直接跑 `pm2-runtime`），最主要的收益是？
(A) 可以用到更多 CPU 核心 (B) 不再需要安裝 Node (C) 部署速度更快 (D) 應用日誌走 journal、狀態反映真實應用，稽核可見性與日誌集中一次補上

Q96. 稽核問「這台機器上哪些 unit 被動過手腳」，最能一次盤點的指令是？
(A) `systemd-delta --type=extended,overridden` (B) `systemctl list-units` (C) `systemd-analyze blame` (D) `journalctl -b`

Q97. `journalctl -t CRON` 出現 `(CRON) info (No MTA installed, discarding output)`，這代表什麼？
(A) cron 服務故障，需要重新安裝 (B) 這一次排程沒有被觸發 (C) 這台機器上所有 cron 工作的輸出與錯誤訊息全部被丟棄，`MAILTO=` 設了也沒用 (D) 只有 root 的排程輸出會被丟棄

Q98. 測試機從快照還原之後，「中間那一整段時間的排程全部沒有補跑」。原因是？
(A) cron 服務在還原後沒有啟動 (B) 時間跳躍超過 3 小時被視為時鐘校正，cron 不補跑 (C) crontab 檔案在還原過程損毀 (D) 帳號剛好在這段期間到期

Q99. 為什麼 `NRestarts` 巡檢要比「差值」而不是絕對值？
(A) 差值計算比較省 CPU (B) 絕對值會溢位 (C) systemd 不提供絕對值 (D) `reset-failed` 與重新 `start` 都會讓 `NRestarts` 歸零，比絕對值會讓基準不斷漂移

Q100. 改了 `ecosystem.config.cjs` 並 `pm2 reload` 之後忘了 `pm2 save`，重開機會發生什麼？
(A) 會用新設定啟動，`pm2 save` 只是額外備份 (B) `pm2 resurrect` 讀到舊快照，跑回舊的埠、舊的 instances、舊的環境變數 (C) 服務完全不會啟動 (D) PM2 會在開機時報錯並停止

> [!question]- 選擇題詳解（Q51～Q100）
> **Q51. (C)**
> ★★★★ 這是全章第一名的假象。手動 start 的當下 X 早就被別的東西帶起來了，所以「看起來正常」；
> 開機時沒有任何人要求啟動 X，`After=` 只是排序，等於白寫。正解是 `Wants=X` + `After=X` 一起寫。
> (A) 錯：症狀是「只有開機會失敗」，程式碼有 bug 不會挑時間；這個誤判會讓人追一整天。
> (B) 錯：磁碟不足會有明確的 `No space left on device`，而且手動 start 也一樣會失敗。
> (D) 錯：沒 enable 的話重開機後是 `inactive`，不會是 `failed`。
> → 詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]
>
> **Q52. (A)**
> ★★★★ `NEXT=n/a` 的語意就是「算不出下一次」：timer 已停止、被 disable，或運算式已無下一次
> （例如寫了過去的固定日期）。這一欄與 `LAST` 一起看就能回答八成的「排程沒跑」問題。
> (B) 錯：剛建立但還沒觸發過的表現是 `LAST=n/a`，`NEXT` 仍會有時間。
> (C) 錯：正在執行不會讓 NEXT 消失。(D) 錯：`NEXT` 是「下次觸發的絕對時間」，與準不準時無關。
> → 詳見 [[020-02-02-02-cmd-systemd-timer與cron選型]]
>
> **Q53. (D)**
> ★★★★ 關鍵在**時間點**：`bad username`、`BAD FILE MODE`、`Missing newline before EOF`
> 這些訊息是在 cron **讀取檔案**時（存檔後一分鐘內）留下的，不是在排程時間 02:00。
> 所以隔天早上從 02:00 開始找，會什麼都找不到，看起來像「時間設定問題」。
> (A) 錯：檔案根本沒被接受，腳本連被呼叫的機會都沒有。(B) 錯：重開機會讓證據更難找。
> (C) 錯：MAILTO 需要可用的 MTA，機關主機十有八九沒有，而且這裡的問題發生在載入階段。
> → 詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]
>
> **Q54. (B)**
> ★★★★ 這是「第二種安靜的死亡」：30 秒才重啟一次，10 秒的滑動窗口內永遠只有一次啟動，
> 所以永遠不會 failed、`OnFailure=` 不會觸發，而 `status` 看起來一直是 active。
> 佐證指令是 `journalctl -u <u> --since -1h | grep -c 'Scheduled restart job'`。
> (A) 錯：剛部署完 `NRestarts` 不會是 2873。(C) 錯：撞上限的狀態是 `failed (Result: start-limit-hit)`。
> (D) 錯：`WatchdogSec=` 與重啟次數無關，而且沒設 watchdog 也不會造成無限重啟。
> → 詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]
>
> **Q55. (A)**
> ★★★★ 架構 A 的招牌盲區：systemd 判定的是 daemon，不是應用。所以結論是
> **不能拿 `systemctl is-active` 當監控依據**，短期補健康檢查 timer、長期遷架構 B／C。
> (B) 錯：Nginx 設定錯是可能，但那要先排除「後端到底有沒有活著」才輪得到它。
> (C) 錯：埠被佔用時 PM2 會顯示 `EADDRINUSE`，而且 502 的成因是後端沒回應不是埠衝突。
> (D) 錯：版本新舊與「狀態判定監看誰」無關，那是 `Type=forking` 的結構問題。
> → 詳見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]
>
> **Q56. (D)**
> ★★★★ `ExecStart=` 是 list 型，直接寫是**追加**。`Type=simple`／`exec`／`notify` 會被拒載
> （`Loaded: bad-setting`），`Type=oneshot` 則不報錯、兩條依序執行。驗證用 `systemctl show -p ExecStart`。
> (A) 錯：這正是題目要考的誤解。(B) 錯：`--runtime` 寫到 `/run`，重開機消失，只適合臨時實驗。
> (C) 錯：那是套件目錄，下次升級會被無聲覆蓋，而且完全沒有稽核軌跡。
> 同一條規則也適用 `Environment=`、`After=`、`ReadWritePaths=`、`RuntimeDirectory=` 等所有 list 型指令。
> → 詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]
>
> **Q57. (B)**
> ★★★ 一行解決。`FixedRandomDelay=true`（systemd 247+）讓每台的偏移固定，排錯時可預測。
> 這種「看起來像資安事件的效能問題」最花時間，因為兩邊團隊會先吵一輪。
> (A) 錯：`AccuracySec=1s` 是反方向 —— 讓所有機器**更準時地同時**打過去，只會更慘。
> (C) 錯：60 台人工改，改完沒人維護，換 image 就打回原形，而且無法擴充。
> (D) 錯：改回 cron 不但沒有隨機延遲機制，還一併失去 `OnFailure=` 與資源上限。
> → 詳見 [[020-02-02-02-cmd-systemd-timer與cron選型]]
>
> **Q58. (C)**
> ★★★★ 典型因果鏈：rsync 對到掛掉的 NAS 卡在 `read()` → 程序永遠不結束 → 一直持有鎖 →
> 之後每一輪 `flock -n` 都拿不到鎖立刻退出 → 外觀就是「從那天之後再也沒跑」且完全沒有錯誤。
> 根治是補 `timeout --signal=TERM --kill-after=30s`，並把退出碼 124 當成必須通報。
> (A) 錯：帳號到期的特徵是「半年後集體停擺」，而且 journal 會有 PAM 訊息。
> (B) 錯：時區改變會讓所有排程**位移**，不是單一支停掉。(D) 錯：那只影響看不看得到日誌，不影響執行。
> → 詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]
>
> **Q59. (A)**
> ★★★★★ 用 `systemctl kill`（走 systemd，事件會正確記錄成 unit 的狀態）送 SIGKILL，
> 屬於「非乾淨訊號」那一列，`on-failure` 才會動作。假死要另外用 `kill -STOP` 測、
> 設定檔錯誤要用 `systemd-run /bin/sh -c 'exit 78'` 測，三種注入缺一不可。
> (B) 錯：`kill` 預設 SIGTERM 是乾淨退出，測出「沒重啟」是正確行為，卻常被誤判成設定壞掉。
> (C)(D) 錯：`systemctl stop`／`restart` 造成的結束**永遠不觸發自動重啟** —— systemd 自己弄死的不算掛。
> → 詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]
>
> **Q60. (D)**
> ★★★★ 由內而外：應用的 SIGTERM handler 要先做完（T_app），PM2 才砍 worker（`kill_timeout`），
> systemd 最後才補刀（`TimeoutStopSec`）。建議值 T_app ≤ 15s、`kill_timeout: 30000`、`TimeoutStopSec=45`。
> (A) 錯：完全顛倒，等於 systemd 先砍，應用連收尾的機會都沒有。
> (B) 錯：`kill_timeout` 比 T_app 小就會在應用收尾到一半時 SIGKILL，出現 502 與資料寫一半。
> (C) 錯：三者是同一條停機路徑上的三段逾時，對不齊就是每次部署都在硬砍連線。
> → 詳見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]
>
> **Q61. (B)**
> ★★★★ `RequiresMountsFor=` 一行會自動算出對應的 `.mount` unit 並加上 `Requires=` 與 `After=`。
> 搭配 fstab 的 `_netdev,x-systemd.automount,nofail`；改完 fstab 記得 `daemon-reload`，
> 否則會出現「fstab 明明改好了，卻說找不到 mount unit」。
> (A) 錯：`network.target` 連 IP 都不保證，更管不到掛載。
> (C) 錯：`sleep 30` 是賭運氣，而且會拖慢開機、`ExecStartPre` 的耗時還會算進後面 unit 的等待。
> (D) 錯：那只保證網路可用，NFS 掛載完成與否是另一件事（那是 `remote-fs.target`）。
> → 詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]
>
> **Q62. (C)**
> ★★★★ 業務排程的存活不能依賴某個自然人的登入狀態，這是機關環境的正解。
> 改成 system timer 之後，它出現在 `systemctl list-timers`、進 journal、可以掛 `OnFailure=`，
> 而且離職帳號停用也不影響。
> (A) 錯：`enable-linger` 只是過渡期止血，而且它本身有安全含意 —— 等於允許該帳號在未登入時常駐執行程序。
> (B) 錯：把服務可用性綁在人的行為上。(D) 錯：`@reboot` 不保證任何相依就緒，而且只在開機跑一次。
> → 詳見 [[020-02-02-02-cmd-systemd-timer與cron選型]]
>
> **Q63. (A)**
> ★★★★ `-E 75` 讓「拿不到鎖」以退出碼 75 離開，可以和「腳本自己 exit 1」明確分開。
> 沒有 `-E` 的話兩者都是 1，監控端無法分辨「今天沒跑因為上一輪還在跑（正常）」與「今天跑了但失敗」。
> (B) 錯：`-n` 本身正確（排程的預設值），但拿不到鎖時退出碼是 1，分不出來。
> (C) 錯：`-w 60` 是等待策略，退出碼一樣是 1；要分辨仍需搭 `-E`（可用不同值如 76）。
> (D) 錯：不加參數是**無限等待**，會累積出幾百個等待中的程序把記憶體吃光，幾乎不該用於 cron。
> → 詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]
>
> **Q64. (D)**
> ★★★★ 判斷準則就一句：**不能改程式碼就不要用 watchdog**。健康檢查 timer 從外面看，
> 不需要碰程式碼，而且要有三個設計：淺檢查（liveness）、重啟預算、維護旗標。
> (A) 錯：`WatchdogSec=` 需要應用主動送 `WATCHDOG=1`，沒送就是每 30 秒被 SIGABRT 一次。
> (B) 錯：假死時程序好好地在那裡，`Restart=` 永遠不會被觸發，設 `always` 也沒用。
> (C) 錯：硬體 watchdog 監看的是 PID 1／kernel，觸發後**直接硬重開整台機器**，完全不對症。
> → 詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]
>
> **Q65. (C)**
> ★★★ 兩種結局都很難查：搶不到埠的那份一直 `errored`（服務其實是好的，沒人發現）；
> 搶到埠的那份可能是舊程式碼，於是「部署明明成功、頁面卻沒更新」。
> 常見成因是有人打了一次 `sudo pm2 list` —— PM2 找不到 daemon 時會靜靜地自己啟一個。
> (A) 錯：問題不在記憶體，在於「兩套獨立清單，部署結果不可預測」。
> (B) 錯：兩個 daemon 各自獨立，沒有任何合併機制。(D) 錯：PM2 不會偵測，它只認自己的 `PM2_HOME`。
> → 詳見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]
>
> **Q66. (A)**
> ★★★★ 對齊規則是 `TimeoutStopSec ≥ 單筆 job 最長執行時間 + 30 秒緩衝`，
> 並且要與 `queue:work --timeout=` 一起看，再搭 `KillMode=mixed` 讓主程序自己優雅收子程序。
> (B) 錯：預設 90s 小於 5 分鐘，每次部署都會在第 90 秒 SIGKILL，job 做到一半、資料寫一半，
> 而且因為是 SIGKILL，Laravel 連把它退回 queue 的機會都沒有。
> (C) 錯：更短只會讓問題更嚴重。(D) 錯：`SendSIGKILL=no` 會讓服務卡在 `deactivating` 永遠停不掉。
> → 詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]
>
> **Q67. (B)**
> ★★★ 典型案例：`*-*-29` 的月結報表在二月整個月不會跑（二月沒有 29 號），
> 這種錯誤在正式環境要等到二月才爆，用 `--base-time` 十秒就驗出來。
> (A) 錯：`systemd-analyze calendar` 是純運算，完全不會觸發任何東西。
> (C) 錯：那要用 `systemctl is-enabled`，或看 `list-unit-files` 的檔案層狀態。
> (D) 錯：時區可以順便從 `Next elapse` 與 `(in UTC)` 兩行是否相同看出來，但那不是 `--base-time` 的用途。
> → 詳見 [[020-02-02-02-cmd-systemd-timer與cron選型]]
>
> **Q68. (D)**
> ★★★★ 判斷準則：**crontab 的指令欄應該只有「一個絕對路徑加幾個參數」**。
> 出現這些字元代表你正在依賴 shell 的行為，而 cron 的 shell 是 dash、`%` 又有特殊語意，
> 兩個坑疊在一起就是「終端機貼上跑得好好的，排程跑出空檔案」。
> (A) 錯：那正是**正確**的樣子，不需要搬。(B) 錯：使用者欄是 `/etc/cron.d` 的必要格式，與搬不搬無關。
> (C) 錯：`*/15` 是標準時間語法，完全沒有問題。
> → 詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]
>
> **Q69. (C)**
> ★★★★ 有一類失敗重啟一萬次結果都一樣：設定檔語法錯、憑證過期、資料庫帳密錯。
> 這些應該直接 failed 並告警，而不是浪費五分鐘做五次注定失敗的重啟。78 = `CONFIG`（BSD 慣例）。
> (A) 錯：`always` 會把它變成無限迴圈，灌爆 journal 並掩蓋真正的錯誤。
> (B) 錯：把設定檔錯誤當成功，等於服務壞了卻顯示一切正常，比不設更糟。
> (D) 錯：加快重試只是更快地失敗更多次。★★★ 另外千萬不要把 `1` 放進 `RestartPreventExitStatus=`，
> 絕大多數應用把任何錯誤都用 exit 1 表示，加了它等於把整層防線關掉。
> → 詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]
>
> **Q70. (A)**
> ★★★★ 架構 B 保留 cluster 與零停機 reload（PM2 說了算），把開機自啟、狀態判定、日誌、
> 停機逾時交還 systemd。遷移成本最低、收益最大，而且剛好補上機關稽核的兩條要求。
> (B) 錯：架構 A 同時違反「狀態要看得到」與「日誌要集中」，只適合開發／測試機或尚未遷移的既有系統。
> (C) 錯：架構 C 最乾淨，但要重寫部署與反向代理設定，適合單實例或高安全要求的場景，不是預設答案。
> (D) 錯：`nohup` 沒有任何自動復原、狀態與日誌，是最糟的選擇。
> → 詳見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]
>
> **Q71. (D)**
> ★★★★ `systemd-run` 可以把所有 unit 屬性用 `--property=` 帶進去，不落檔、不動到正式 unit；
> `--collect` 讓失敗的暫時 unit 自動清掉，不會留在 `systemctl --failed` 裡礙眼。
> 排錯時的二分法也靠它：先整組拿掉沙箱試跑，能跑就確定是沙箱問題，再逐項加回來。
> (A) 錯：`--full` 會落檔並取代整份 unit，而且要 restart 正式服務。
> (B) 錯：`systemd-delta` 是盤點被覆寫的 unit。(C) 錯：`daemon-reload` 只是重讀設定，不執行任何東西。
> → 詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]
>
> **Q72. (B)**
> ★★★ 大部分人第一直覺都回答「需要」，然後全部遷 timer，工程量爆炸。
> 換成這個問法之後答案就分得開：每日資料庫備份、憑證續期檢查、對外資料拋轉是「必須告警」；
> 清 `/var/tmp` 超過 30 天的檔案、每小時更新 motd 是「不用告警，留 cron 可以」。
> (A) 錯：「重不重要」太模糊，每個人的標準不同，也無法拿去回答稽核。
> (C) 錯：跑多久對應的是「會不會跑超過一個週期」那一題。(D) 錯：作者是誰與選型無關。
> → 詳見 [[020-02-02-02-cmd-systemd-timer與cron選型]]
>
> **Q73. (C)**
> ★★★ dash 不支援 `&>`，會被解析成 `cmd &`（背景執行）加上 `> /var/log/x.log`，行為完全不同 ——
> 排程「立刻結束」而工作在背景被 cron 收掉。同類還有 `[[ ]]`、`source`、`arr=(a b c)`。
> (A) 錯：呼叫一支有 `#!/usr/bin/env bash` 的腳本完全沒問題，這也是推薦寫法。
> (B) 錯：`>>` 與 `2>&1` 是 POSIX 語法，dash 完全支援。
> (D) 錯：單純執行一個指令沒有任何 shell 相容性問題。
> → 詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]
>
> **Q74. (A)**
> ★★★★ 意思是「五分鐘內重啟五次還不行就放棄、進 failed、觸發告警」，讓第三層防線接手。
> 這一組在 Ubuntu 22.04／RHEL 8（沒有 `RestartSteps=` 指數退避）也一樣適用。
> (B) 錯：預設 100ms／10s／5 撞上限只要不到 1 秒，短暫的資料庫抖動就會害它停整晚。
> (C) 錯：`RestartSec` 大於 interval 會永遠撞不到上限 → 無限重啟、journal 被灌爆且不告警。
> (D) 錯：`always` 連乾淨退出都重啟，不設 StartLimit 等於完全沒有收斂機制。
> → 詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]
>
> **Q75. (D)**
> ★★★★★ 事故劇本完整：unit 指向 A，實際在服務的應用存在 B（某次 `sudo pm2 start` 的產物）。
> 機器一重開，systemd 把 A 的 daemon 拉起來（status 綠燈），resurrect 出 0 個應用，前台整個不見。
> (A) 錯：兩個 `PM2_HOME` 是完全獨立的資料目錄，沒有任何同步機制。
> (B) 錯：現在正常只是因為 B 的 daemon 還活著；這是「還沒重開機」而不是「沒問題」。
> (C) 錯：這不是 bug，是 `PM2_HOME` 由 `$HOME` 推導的正常行為被誤用。
> → 詳見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]
>
> **Q76. (B)**
> ★★★★ `Type=notify` 的判定點是應用送出 `READY=1`，所以「起來了」真的等於「能接請求」——
> 設定檔錯、埠被佔用、資料庫連不上這些在啟動期間才會暴露的失敗全部抓得到。
> (A) 錯：`simple` 在 `fork()` 完成的瞬間就宣告成功，幾乎什麼都抓不到，
> 後面 `After=` 它的 Nginx 已經開始轉發而應用還沒 listen，就是 502 的來源。
> (D) 錯：`exec` 只保證 `execve()` 成功（抓得到執行檔不存在、權限不對、沙箱擋住），仍抓不到埠與 DB。
> (C) 錯：`forking` 判定的是「父程序退出 + PIDFile 出現」，精確度更低。
> → 詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]
>
> **Q77. (A)**
> ★★★ `static` 就是「沒有 `[Install]` 區段，所以無從 enable」。補上
> `[Install]` + `WantedBy=timers.target` 再 `daemon-reload` 才 enable 得起來。
> `is-enabled` 的輸出只有 `enabled` 是正確的，其他都要處理。
> (B) 錯：正確啟用會回 `enabled`。(C) 錯：被封鎖會回 `masked`，而且要先查清楚**誰為什麼 mask**。
> (D) 錯：檔案不存在會回 `not-found`。
> → 詳見 [[020-02-02-02-cmd-systemd-timer與cron選型]]
>
> **Q78. (C)**
> ★★★★ `env -i` 清掉所有環境變數再指定一組跟 cron 一樣的最小環境，這才是有效的重現。
> 手動跑成功、`env -i` 跑失敗 → 確診是環境差異（PATH、語系、缺變數），
> 修法是在腳本裡自己 `export PATH`，不要依賴外部環境。
> (A) 錯：你的 shell 有 `.bashrc` 給的 PATH、有完整的環境變數，是**無效的重現**。
> (B) 錯：重開機不會改變 cron 的環境。(D) 錯：`command not found`（127）與執行位元無關，那是 126。
> → 詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]
>
> **Q79. (D)**
> ★★★★ 資料庫掛掉時三十個相依服務會同時 failed，沒有去重就是三十封告警，
> 值班人員會直接把整個群組靜音 —— 那等於沒有告警。用時間戳檔案做五分鐘去重最省事。
> (A) 錯：`set -euo pipefail` 是 shell 的錯誤處理習慣，與告警數量無關。
> (B) 錯：`systemd-escape -u` 解決的是訊息裡出現 `\x2d` 這種可讀性問題。
> (C) 錯：`TimeoutStartSec=30` 是避免告警腳本卡住佔著 systemd 的 job，也不是去重。
> → 詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]
>
> **Q80. (B)**
> ★★★★ 稽核問「這台前台最後一次變更是什麼時候」，systemd 給的答案會是三個月前，完全錯的。
> 更嚴重的是 `pm2 restart` 之後若沒 `pm2 save`，dump 還是舊的，下次重開機就跑回舊設定。
> 修法是部署腳本一律走 systemd 介面（`systemctl reload pm2-ops` 或對自己的 unit 動作）。
> (A) 錯：速度不是重點，而且 `pm2 restart` 通常更快。
> (C) 錯：記憶體洩漏是應用層問題，與誰下指令無關。(D) 錯：PM2 完全不會拒絕，這正是它危險的地方。
> → 詳見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]
>
> **Q81. (A)**
> ★★★★ 正式環境的程式碼本來就不該放在個人家目錄底下 —— 那同時是可靠性問題（帳號被清就沒了）
> 與安全問題（個人檔案與生產服務混在一起）。搬家是根治，`read-only` 是不得已的折衷。
> (B) 錯：這是「臨時處置變成永久設定」的典型，一行退回沒有保護的狀態。
> (C) 錯：把權限問題用 root 蓋過去，等於把應用層漏洞升級成整機淪陷。
> (D) 錯：`PrivateTmp=` 管的是 `/tmp`，與 `/home` 讀不到完全無關。
> → 詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]
>
> **Q82. (C)**
> ★★★ 失敗訊息會很莫名其妙，例如 `mysqldump: Couldn't find table: "|"`。
> 兩個正解：包成腳本讓 unit 只叫腳本（推薦），或明確寫 `ExecStart=/bin/bash -c '...'`。
> ★★★ 對稱的坑是：`%` 在 unit 檔裡是 specifier，要寫 `%%`（跟 cron 裡寫 `\%` 是不同規則）。
> (A) 錯：systemd 執行 `ExecStart=` **不經過 shell**，這正是本題的考點。
> (B) 錯：`daemon-reload` 不會擋，要等服務啟動失敗才看得出來。(D) 錯：所有 shell 語法一律失效。
> → 詳見 [[020-02-02-02-cmd-systemd-timer與cron選型]]
>
> **Q83. (B)**
> ★★★★ crontab 那一行只有「什麼時候、用哪個身分、呼叫哪支腳本」，外加一層 `timeout` 保護；
> 記錄、退出碼分類、失敗通報全部是腳本自己的責任。`--kill-after` 不能省，否則可能還是卡住。
> (A) 錯：`>/dev/null 2>&1` 是全機關最常見的一行，也是備份失敗三個月沒人知道的唯一原因。
> (C) 錯：管線的退出碼是 logger 的（永遠 0），`||` 永遠不會觸發。
> (D) 錯：`&` 讓 cron 立刻收工，工作變成孤兒，逾時與鎖全部失效。
> → 詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]
>
> **Q84. (D)**
> ★★★★ 兩個前提缺一不可：應用要真的送 `WATCHDOG=1`（`Type=notify`／`WatchdogSec=` 下
> `NotifyAccess=` 隱含為 `main`，心跳由子程序送就要 `all`），以及 `Restart=` 要能涵蓋 watchdog 逾時。
> 症狀「每 30 秒準時觸發一次」本身就是「應用根本沒實作心跳」的鐵證。
> (A) 錯：watchdog 用的是 unit 啟動後的計時，與牆上時鐘、NTP 無關。
> (B) 錯：`AccuracySec=` 是 timer 的設定，跟 watchdog 無關。(C) 錯：journal 滿了不會產生 SIGABRT。
> → 詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]
>
> **Q85. (A)**
> ★★★★ 而且健康端點要**真的檢查下游**（DB 連得上、快取通得了），不能只回 200 OK；
> `OnFailure=` 也要掛在這支健康檢查 unit 上，掛在 `pm2-ops.service` 上等於沒掛。
> (B) 錯：架構 A 的 `is-active` 反映的是 God Daemon，worker 全掛也是綠燈。
> (C) 錯：`pm2 list` 顯示 `online` 只代表 Node 程序活著；event loop 卡死、DB pool 耗盡都還是 online。
> (D) 錯：`Restart=on-failure` 掛在 unit 上只會重啟 daemon，而 daemon 很少死。
> → 詳見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]
>
> **Q86. (C)**
> ★★★★★ `+` 前綴代表以**完整權限（root）**執行，而且 `User=`、capability 與檔案系統沙箱
> 對這一行全部不生效。`/srv/www/app/` 是部署流程會覆寫的目錄，等於開了一個 root 後門。
> 硬規則：`+` 指到的檔案必須 `root:root 0755`，且**路徑上每一層目錄**都不可被他人寫入（用 `namei -l` 逐層檢查）。
> (A) 錯：這是權限問題不是效能問題。(B) 錯：`+` 的作用正是**跳過**沙箱，所以擋不住。
> (D) 錯：它會跑得好好的 —— 正因為看起來一切正常，才更危險。需要 root 但想保留沙箱時用 `!` 而不是 `+`。
> → 詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]
>
> **Q87. (D)**
> ★★★★ 「先開新的觀察幾天」聽起來穩健，實際是最常見的遷移事故。
> 用了 `flock` 的工作更陰險：兩邊搶鎖，其中一次被跳過，**看起來正常，實際上少跑一次**。
> 正確順序是先停舊、再開新，中間空窗一個週期可以接受；真的不能空窗就手動補跑一次。
> (A) 錯：這是有明確後果的順序，不是慣例。(B) 錯：systemd 與 cron 互不知情，不會互相拒絕。
> (C) 錯：cron 與 timer 之間沒有任何鎖定機制，這正是會跑兩次的原因。
> → 詳見 [[020-02-02-02-cmd-systemd-timer與cron選型]]
>
> **Q88. (A)**
> ★★★★ `cron.allow` 一旦存在，`cron.deny` 就完全被忽略，只有清單內的人能用 `crontab`。
> 而且症狀很迷惑人：`crontab -l` 還看得到內容，它就是不會執行。
> 修法是把服務帳號加進 `cron.allow`，或把排程搬到不受此限制的 `/etc/cron.d/`（那是 root 寫的系統排程）。
> (B) 錯：`cron.deny` 存不存在都無所謂，allow 存在時它本來就失效。
> (C) 錯：服務被停掉的話**所有**排程都會停，包括系統維護類的。(D) 錯：SELinux 的表現是 AVC denied。
> → 詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]
>
> **Q89. (B)**
> ★★★★ `failed (Result: start-limit-hit)` 狀態下 systemd 會擋掉所有 `start`，
> 而錯誤訊息跟原因完全無關（只叫你去看 status），值班人員最容易卡在這裡。
> `reset-failed` 會 flush 這個 unit 的 rate limit 計數，之後才 start 得起來。這行要寫進部署腳本與交接文件。
> (A) 錯：重開機雖然也會清掉，但那是用大砲打小鳥，而且共用主機上不能說重開就重開。
> (C) 錯：`daemon-reload` 只重讀設定，不會清計數器。(D) 錯：`masked` 是另一種狀態，訊息也不同。
> → 詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]
>
> **Q90. (C)**
> ★★★★ 「狀態不準」與「停不乾淨」是兩個獨立的坑。cgroup 顯示 `user@1000.service`
> 就代表這個程序歸使用者 session 管，不在 unit 的 cgroup 內，`systemctl stop` 永遠殺不到它。
> 止血是手動清掉並 `loginctl disable-linger`，根治是禁止互動式 `pm2 start`（包成 wrapper 統一入口）。
> (A) 錯：`ExecStop` 沒殺乾淨的特徵是 `systemd-cgls -u` **看得到**那個 pid，而且 journal 有 `stop-sigterm timed out`。
> (B) 錯：`ss -lptn` 已經指出是 node。(D) 錯：`KillMode=process` 反而讓更多子程序逃出生命週期。
> → 詳見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]
>
> **Q91. (D)**
> ★★★★ 最安靜的一種故障：上線當天三個實例都在跑、測試全過，但只 `enable` 了一個，
> 重開機後另外兩條 queue 從此沒人處理 —— 沒有錯誤日誌、沒有 alert。
> 驗收方式是數 `multi-user.target.wants/` 底下的連結，或逐一比對 `is-active` 與 `is-enabled`。
> (A) 錯：MySQL 沒起來會讓三條 queue 一起出問題，不會只剩一條。
> (B) 錯：OOM 會在 journal 留下明確記錄。(C) 錯：磁碟滿了是全機性的症狀，不會只影響兩個實例。
> → 詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]
>
> **Q92. (A)**
> ★★★★ 這三個都是「技術上遷得動、但不該遷」的正當理由，要寫進盤點表的備註欄，
> 稽核問「為什麼這支還在 cron」時才答得出來。廠商維護那一項尤其重要：**先發文，不要先動手**。
> (B) 錯：cron 與 timer 的觸發成本差異在維運上完全可以忽略，這不是選型理由。
> (C) 錯：「大家比較熟」不是可辯護的理由，正確做法是把選型準則寫下來。
> (D) 錯：`OnCalendar=*:0/1` 或 `OnUnitActiveSec=1min` 都做得到每分鐘執行。
> → 詳見 [[020-02-02-02-cmd-systemd-timer與cron選型]]
>
> **Q93. (B)**
> ★★★★ syslog 會留下 `ERROR (Missing newline before EOF, this crontab file will be ignored)`，
> 但只在存檔後那一分鐘出現。這個坑特別陰險，因為用 `cat` 看檔案內容**完全正常**。
> 用 `printf '...\n'` 或 heredoc 產生檔案就不會有這問題。
> (A) 錯：空檔案 `tail -c1` 也沒有輸出，但那時 `stat` 的 size 會是 0，兩者可以分辨。
> (C) 錯：編碼問題不會表現成缺換行。(D) 錯：權限要用 `stat -c '%a %U:%G'` 檢查，是另一個獨立的檢查項。
> → 詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]
>
> **Q94. (C)**
> ★★★★★ 一支 worker 撞上限就強制重開整台機器，等於一個系統拖垮五個系統；
> `-force` 不做正常關機程序，有檔案系統損毀與資料遺失風險；根因是設定檔錯誤時還會變成無限重開機迴圈，
> 開機時間短到來不及 SSH，只能靠帶外管理救。一般伺服器一律留在預設 `none`。
> (A)(B) 錯：這兩個正是本章建議的基準設定。
> (D) 錯：`OnFailure=` 是第三層防線的核心，把失敗變成一則真的送得出去的告警。
> → 詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]
>
> **Q95. (D)**
> ★★★★ 這剛好對上機關稽核的兩條標配要求：狀態要能用 `systemctl status` 看到、日誌要進集中蒐集。
> `pm2-runtime` 是前景執行不 fork，systemd 直接監看它，應用全掛就會 failed 並觸發 `OnFailure=`。
> (A) 錯：cluster 多核心利用在架構 A 與 B 是一樣的，不是遷移的收益。
> (B) 錯：架構 B 仍然要 Node 與 PM2；「少一層相依」是架構 C 的優點。
> (C) 錯：部署速度與架構無關，反而因為改走 systemd 介面會多一兩個步驟。
> → 詳見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]
>
> **Q96. (A)**
> ★★★ `systemd-delta` 會列出所有 `[EXTENDED]`（drop-in）與 `[OVERRIDDEN]`（`/etc` 蓋掉套件檔）的 unit，
> 是交接與稽核必跑的一條。它的輸出應該納入每月巡檢紀錄，並與上次比對。
> (B) 錯：`list-units` 只列出目前載入的 unit 與狀態，看不出誰被覆寫過。
> (C) 錯：`systemd-analyze blame` 是開機耗時排名。(D) 錯：`journalctl -b` 是本次開機的日誌，不是組態盤點。
> → 詳見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]
>
> **Q97. (C)**
> ★★★★ 這一行是關鍵訊號：這台機器沒有可用的 MTA，所有 cron 工作的 stdout／stderr 全部進黑洞。
> 它本身就是「該遷 timer」的充分理由 —— cron 端的告警在機關主機上實務等於不存在。
> (A) 錯：cron 完全正常，這只是它在說「輸出沒地方送」。
> (B) 錯：能印出這一行就代表**已經觸發**了；旁邊那行 `CMD (...)` 就是證據。
> (D) 錯：沒有 MTA 是全機性的，不分使用者。
> → 詳見 [[020-02-02-02-cmd-systemd-timer與cron選型]]
>
> **Q98. (B)**
> ★★★★ `man 8 cron` 的規則：時間往前跳**小於 3 小時**時，被跳過那段有指定時分的工作會盡快補跑一次；
> 跳躍**超過 3 小時**則視為時鐘校正，**不補跑**。VM 從快照還原、新機第一次 NTP 大幅校時都會踩到。
> 佐證是 `journalctl -u chrony | grep 'stepped by'`，數字大於 10800 秒就確定。
> (A) 錯：cron 會隨開機正常啟動。(C) 錯：快照還原不會損毀檔案，而且損毀會有明確錯誤。
> (D) 錯：帳號到期是「從某天起全部停止」而不是「只有中間那段沒跑」。要能補跑就用 timer 的 `Persistent=true` 或 anacron。
> → 詳見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]
>
> **Q99. (D)**
> ★★★ 比絕對值的告警會在每次維護後基準漂移，然後你會開始「習慣性忽略」這個告警 —— 那就等於沒有。
> 比差值（例如 15 分鐘內新增 5 次就算風暴）才穩定；而且要處理「差值為負」的情況（歸零後直接跳過）。
> (A) 錯：兩者的計算成本差異可以忽略，理由是語意不是效能。
> (B) 錯：`NRestarts` 是計數器，實務上不會溢位。
> (C) 錯：`systemctl show -p NRestarts` 給的就是絕對值，問題在它會被歸零。
> → 詳見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]
>
> **Q100. (B)**
> ★★★★ `dump.pm2` 是「當下狀態的快照」不是「設定檔」，`pm2 resurrect` 開機時讀的就是它。
> 所以改完 ecosystem、`pm2 reload` 之後看起來一切正常，重開機才會爆 —— 這是最難聯想的一種。
> 驗證方法是把 `pm2 jlist` 與 `dump.pm2` 做 diff，放進部署腳本的驗收段。
> (A) 錯：`resurrect` 完全不會去讀 ecosystem，這是最關鍵的誤解。
> (C) 錯：它會啟動，只是啟動的是舊設定。(D) 錯：PM2 不會報錯，因為對它而言舊快照是合法的。
> ★★★★ 更徹底的解法是架構 B：unit 直接寫死要跑哪一份 ecosystem，`pm2 save` 這個步驟從流程裡消失。
> → 詳見 [[020-02-02-05-svc-systemd-PM2與systemd整合]]

---

## 延伸閱讀

- 本章索引：[[020-02-02-00-idx-systemd-系統服務與排程]]
- 五篇教材：
  - [[020-02-02-01-svc-systemd-unit撰寫實戰]] — 相依、目錄委派、template、drop-in、停機語意、沙箱
  - [[020-02-02-02-cmd-systemd-timer與cron選型]] — 八個排程來源盤點、選型決策樹、遷移八步
  - [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]] — 七道關卡、`%` 截斷、flock 與逾時、帳號類拒跑
  - [[020-02-02-04-svc-systemd-服務自動復原與看門狗]] — 三層防線、StartLimit 算術、watchdog、OnFailure
  - [[020-02-02-05-svc-systemd-PM2與systemd整合]] — `PM2_HOME` 一致性、四種衝突、三種架構選型
- 基礎補強：[[020-01-17-cmd-Linux-systemd服務管理]]、[[020-01-18-guide-Linux-排程工作]]、[[020-01-19-guide-Linux-日誌系統]]
- 上層索引：[[020-02-00-idx-Linux伺服器管理]]
