---
title: "KVM 與 libvirt 常見故障排除"
desc: "依症狀查的 KVM／libvirt 故障排除索引：判斷分流、編號排查步驟與一頁式急救卡，原理回連原文"
aliases: [KVM 故障排除, libvirt 排錯, virsh 排錯手冊, KVM 疑難排解]
tags: [群組/虛擬機與容器, 主題/故障排除]
category: KVM與libvirt
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: []
updated: 2026-09-02
---

# KVM 與 libvirt 常見故障排除

> [!warning] 未實機驗證
> 本篇整理自本章五篇教學的排錯段落與現場常見情境。指令與訊息以 Ubuntu 24.04 LTS
> ＋ libvirt 10.x 的行為為準，**尚未在實體伺服器逐條驗證**。
> 不同發行版、不同 libvirt 版本的訊息文字與預設值可能不同，
> 照做之前請先在測試機確認，正式環境動手前務必先備份 domain XML 與磁碟。

> [!abstract] 怎麼用這份手冊
> - 依「你看到什麼症狀」查，不是依「這屬於什麼技術」查
> - 找到症狀 → 看判斷分流 → 照編號步驟做 → 想懂原理再點進原文
> - ★★★★★ 緊急時直接看下面的「一頁式急救卡」
> - ★★★★★ 本手冊**不重講原理**。每個情境結尾的「原理詳見」就是原文入口
> - ★★★★★ 動手之前先問自己三句話：
>   1. **我現在連到哪個 URI？**（`virsh uri`）—— 一半的「VM 不見了」是這個問題
>   2. **我要下的這個指令，是關機、斷電，還是刪除？**（`shutdown` / `destroy` / `undefine`）
>   3. **這台主機我還有第二條路進得來嗎？**（改網路之前一定要問）

---

## 一頁式急救卡

出事時來不及讀長文，先跑這幾個。★★★★★ **由上而下、看到異常就停下來往對應情境走**。

```bash
# ─── 黃金 60 秒：一分鐘掌握 KVM 主機狀況 ────────────────────────
# 【1】我連到哪個世界？（★★★★★ 投報率最高的一行）
virsh uri
#   qemu:///session → 你在使用者模式，伺服器的 VM 都在 system，走情境二

# 【2】有哪些 VM、誰是暫態的、誰沒設自動啟動
virsh list --all
virsh list --all --title 2>/dev/null | head
for v in $(virsh list --all --name); do
  printf '%-16s state=%-10s persistent=%-4s autostart=%s\n' "$v" \
    "$(virsh domstate "$v")" \
    "$(virsh dominfo "$v" | awk -F': *' '/Persistent/{print $2}')" \
    "$(virsh dominfo "$v" | awk -F': *' '/Autostart/{print $2}')"
done
#   Persistent: no  → ★★★★★ 暫態 domain，主機重開就永久消失，走情境四【3】
#   Autostart: disable → 主機重開不會自己起來，走情境十六

# 【3】hypervisor 這一層還活著嗎
ls -l /dev/kvm; lsmod | grep '^kvm'; sudo virt-host-validate qemu | head -6
#   /dev/kvm 不存在 → 情境一
#   QEMU: Checking for hardware virtualization : FAIL → 情境一

# 【4】管理層的守護行程是哪一種架構、有沒有起來
systemctl list-units --no-pager 'virt*' 'libvirt*' | head -20
#   找不到 libvirtd.service → 這台是模組化架構，要管 virtqemud，走情境一【4】

# 【5】VM 是真的用硬體加速，還是掉回軟體模擬
ps -ef | grep -o '\-accel [a-z]*' | sort -u
virsh list --name | while read -r v; do
  [ -n "$v" ] && echo "$v: $(virsh dumpxml "$v" | grep -o "domain type='[a-z]*'")"
done
#   accel tcg / domain type='qemu' → ★★★★★ 沒有硬體加速，慢十倍，走情境十五

# 【6】儲存池與磁碟鏈
virsh pool-list --all --details
#   State: inactive → 情境六
qemu-img info --backing-chain /var/lib/libvirt/images/<disk>.qcow2
#   Could not open backing file → ★★★★★ 鏈斷了，走情境七

# 【7】網路
virsh net-list --all
ip -br addr; ip route
#   default 網路 inactive → VM 拿不到 IP，走情境九

# 【8】真正的錯誤訊息在哪裡（★★★★★ VM 開不起來第一站）
sudo tail -40 /var/log/libvirt/qemu/<vm>.log
sudo journalctl -u virtqemud -u libvirtd --since '30 min ago' --no-pager | tail -40
sudo dmesg -T | grep -iE 'apparmor|avc|kvm' | tail -20

# ─── 動手改之前的三道保命符 ────────────────────────────────────
virsh dumpxml <vm> > ~/xmlbak/<vm>-$(date +%F-%H%M).xml   # ① 一定先存定義
virsh dominfo <vm> && virsh domblklist <vm>                # ② 確認打的是哪一台、動到哪顆磁碟
# ③ 要改網路？先確認 IPMI／實體 console／第二張網卡至少有一個能用
```

> [!tip] ★★★★★ 三句話版本
> ① 先跑 `virsh uri` 與 `virsh list --all` —— **一半的 KVM 疑難案件在這兩行就結案**。
> ② VM 開不起來就去看 `/var/log/libvirt/qemu/<vm>.log`，不要憑猜的改 XML。
> ③ 動任何破壞性指令之前先 `dumpxml` 存一份，動網路之前先確認有第二條路進來。

---

## 快速索引（依症狀）

| 症狀（你會看到的） | 最可能的原因 | 先下這個指令 | 原理詳見 |
| --- | --- | --- | --- |
| ★★★★★ `virsh list --all` 一片空白，但 virt-manager 裡明明有 VM | 連到 `qemu:///session`，VM 定義在 `qemu:///system` | `virsh uri` | [[050-01-04-02-svc-KVM-安裝與virt-manager]] |
| ★★★★★ `/dev/kvm does not exist` | 模組沒載入，或 CPU／BIOS／巢狀環境沒開虛擬化 | `kvm-ok; lsmod \| grep '^kvm'` | [[050-01-04-02-svc-KVM-安裝與virt-manager]] |
| ★★★★★ `Failed to connect socket ... Permission denied` | 加了 `libvirt` 群組但**沒有重新登入** | `id -nG; id -nG $USER` | [[050-01-04-02-svc-KVM-安裝與virt-manager]] |
| ★★★★★ 打了 `virsh destroy` 服務就中斷了 | `destroy` 是**強制斷電不是刪除** | `virsh domstate <vm>` | [[050-01-04-03-cmd-KVM-virsh指令實務]] |
| ★★★★★ 主機重開機後某台 VM 永遠消失 | 用 `virsh create` 開的**暫態 domain** | `virsh dominfo <vm> \| grep Persistent` | [[050-01-04-03-cmd-KVM-virsh指令實務]] |
| ★★★★★ `undefine` 之後磁碟空間沒釋放 | `undefine` 預設**不刪磁碟** | `virsh domblklist <vm>`（刪之前） | [[050-01-04-03-cmd-KVM-virsh指令實務]] |
| ★★★★★ 改完 `br0` 之後 SSH 再也連不上 | 實體網卡 IP 搬到 br0 途中設定寫錯 | IPMI／console 進去 `ip -br addr` | [[050-01-04-04-guide-KVM-儲存池與網路]] |
| ★★★★★ `Could not open backing file: No such file` | base 映像被移動／改名／刪掉 | `qemu-img info --backing-chain <disk>` | [[050-01-04-05-guide-KVM-自動化與範本]] |
| ★★★★★ 複製出來的三台 VM 拿到同一個 IP | 範本沒清 `machine-id` | `cat /etc/machine-id`（三台比對） | [[050-01-04-05-guide-KVM-自動化與範本]] |
| ★★★★★ VM 慢到不能用，開機要五分鐘 | 掉回 TCG 純軟體模擬 | `virsh dumpxml <vm> \| grep "domain type"` | [[050-01-04-01-guide-KVM-KVM與libvirt架構]] |
| ★★★★★ `Failed to get "write" lock` | **同一顆磁碟被兩個 QEMU 開著** | `sudo lsof <disk>.qcow2` | [[050-01-04-04-guide-KVM-儲存池與網路]] |
| ★★★★ `Could not open '...': Permission denied`，但檔案權限看起來沒問題 | AppArmor（Ubuntu）／SELinux（RHEL）擋住自訂路徑 | `sudo dmesg -T \| grep -iE 'apparmor\|avc'` | [[050-01-04-02-svc-KVM-安裝與virt-manager]] |
| ★★★★ `systemctl restart libvirtd` 說找不到這個 unit | 這台是模組化架構，沒有 `libvirtd` | `systemctl list-units 'virt*'` | [[050-01-04-01-guide-KVM-KVM與libvirt架構]] |
| ★★★★ 改了 `/etc/libvirt/qemu/<vm>.xml` 完全沒生效 | 直接編輯 XML 檔無效 | `virsh edit <vm>` | [[050-01-04-01-guide-KVM-KVM與libvirt架構]] |
| ★★★★ 改了 XML 完整重開機還是沒生效 | 有 **managedsave** 狀態 | `virsh dominfo <vm> \| grep 'Managed save'` | [[050-01-04-03-cmd-KVM-virsh指令實務]] |
| ★★★★ 主機重開後 pool 變 `inactive`、找不到磁碟 | 忘了 `pool-autostart` | `virsh pool-list --all` | [[050-01-04-04-guide-KVM-儲存池與網路]] |
| ★★★★ `vol-list` 看不到剛 `cp` 進去的 ISO | libvirt 沒重新掃描 | `virsh pool-refresh <pool>` | [[050-01-04-04-guide-KVM-儲存池與網路]] |
| ★★★★ VM 拿不到 IP | `default` 網路沒啟動 / 橋接接錯 / 交換器擋 MAC | `virsh net-list --all` | [[050-01-04-04-guide-KVM-儲存池與網路]] |
| ★★★★ `revert to external snapshot not supported yet` | 那是**外部快照**，`snapshot-revert` 不支援 | `virsh snapshot-info <vm> <snap>` | [[050-01-04-03-cmd-KVM-virsh指令實務]] |
| ★★★★ 刪了 overlay 檔之後 VM 開不起來 | 磁碟鏈斷了，資料在 overlay 裡 | `qemu-img info --backing-chain` | [[050-01-04-03-cmd-KVM-virsh指令實務]] |
| ★★★★ VM 開機了但主機名稱還是 `ubuntu`、IP 沒設 | cloud-init 沒讀到 seed ISO | `virsh domblklist <vm>` | [[050-01-04-05-guide-KVM-自動化與範本]] |
| ★★★★ 改了 `user-data` 重開機沒生效 | `instance-id` 沒變，cloud-init 認為做過了 | `cloud-init status --long`（客體內） | [[050-01-04-05-guide-KVM-自動化與範本]] |
| ★★★★ 遷移過去目標主機重開機 VM 就消失 | 沒加 `--persistent` | `virsh dominfo <vm> \| grep Persistent`（目的端） | [[050-01-04-03-cmd-KVM-virsh指令實務]] |
| ★★★★ 遷移過去客體立刻崩潰 | `host-passthrough` ＋ 兩台 CPU 指令集不同 | `virsh dumpxml <vm> \| grep -A2 '<cpu'` | [[050-01-04-03-cmd-KVM-virsh指令實務]] |
| ★★★★ qcow2 越來越大，VM 裡明明刪了東西 | 沒開 `discard='unmap'`／沒跑 `fstrim` | `qemu-img info <disk>` | [[050-01-04-04-guide-KVM-儲存池與網路]] |
| ★★★★ 主機磁碟滿了，但每台 VM 的容量加起來沒那麼多 | qcow2 精簡配置**超賣**，加上快照 | `du -sh /var/lib/libvirt/images/` | [[050-01-04-04-guide-KVM-儲存池與網路]] |
| ★★★★ 主機重開機後所有 VM 都沒起來 | 沒設 autostart | `virsh list --autostart --all` | [[050-01-04-03-cmd-KVM-virsh指令實務]] |
| ★★★ `virsh console` 連上去一片空白 | 客體沒把輸出導到序列埠 | `virsh dumpxml <vm> \| grep -A2 console` | [[050-01-04-03-cmd-KVM-virsh指令實務]] |
| ★★★ `virsh console` 退不出來 | 用了 `Ctrl+C`（會傳給客體） | 退出鍵是 **`Ctrl + ]`** | [[050-01-04-03-cmd-KVM-virsh指令實務]] |
| ★★★ `virsh shutdown` 完全沒反應 | 客體沒裝 `qemu-guest-agent`，ACPI 被忽略 | `virsh domstate <vm>` | [[050-01-04-03-cmd-KVM-virsh指令實務]] |
| ★★★ 在 PVE 主機上 `virsh list` 看不到任何 VM | PVE **不用 libvirt** | `qm list` | [[050-01-04-01-guide-KVM-KVM與libvirt架構]] |
| ★★★ 磁碟在客體裡是 `sda` 不是 `vda`、網路很慢 | 沒用 VirtIO | `virsh domblklist <vm>; virsh domiflist <vm>` | [[050-01-04-02-svc-KVM-安裝與virt-manager]] |

---

## 依情境展開

### ★★★★★ 情境一：裝不起來、`/dev/kvm` 不存在、VM 開不了

**現象**：三種訊息，代表**卡在硬體虛擬化鏈的不同層**，處理方向完全不同。

```text
（A）$ kvm-ok
     INFO: Your CPU does not support KVM extensions
     KVM acceleration can NOT be used              ★★★★★ CPU 旗標根本沒有

（B）$ kvm-ok
     INFO: KVM is disabled by your BIOS
     HINT: Enter your BIOS setup and enable Virtualization Technology (VT)
                                                   ★★★★★ 旗標在，但被韌體關掉

（C）$ virsh start web01
     error: Failed to start domain 'web01'
     error: ... Could not access KVM kernel module: No such file or directory
                                                   ★★★★ 模組沒載入／裝置檔不在
```

**判斷分流**：由下往上四層，**一層一層確認，不要跳**。

```text
① CPU 旗標有嗎        grep -c -E '(vmx|svm)' /proc/cpuinfo   → 0 就是走【1】
② 模組載入了嗎        lsmod | grep '^kvm'                     → 沒有走【2】
③ /dev/kvm 在嗎、權限對嗎  ls -l /dev/kvm                     → 不對走【3】
④ 管理層起來了嗎      systemctl list-units 'virt*' 'libvirt*' → 走【4】
```

**處置步驟**：

【1】★★★★★ **CPU 旗標是 0**：這一層沒解決，後面全部沒意義。先分辨你在哪種機器上。

```bash
grep -c -E '(vmx|svm)' /proc/cpuinfo
```

```text
0
```

| 你的環境 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 實體伺服器 | BIOS/UEFI 的 `Intel VT-x` / `AMD-V (SVM)` 沒開 | 進 BIOS 打開，**存檔後完整斷電再開機**（有些主機板 `reboot` 不會重新套用） |
| ★★★★★ VMware Workstation 裡的 VM（本手冊實驗環境） | 沒勾巢狀虛擬化 | **關機**後 Settings → Processors → 勾 `Virtualize Intel VT-x/EPT or AMD-V/RVI`；見 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] |
| ★★★★ PVE 上的 VM | 沒開巢狀 | 主機 `cat /sys/module/kvm_intel/parameters/nested` 要是 `Y`；VM 的 CPU type 設 `host` |
| ★★★★ 雲端 VM | 供應商沒提供巢狀虛擬化 | 換支援的機型，或改用容器 |
| ★★★ 真的很舊的 CPU | 硬體不支援 | 只能換機器；用 TCG 模擬跑得動但慢十倍以上 |

> [!warning] ★★★★ BIOS 改完一定要「完整斷電」再開
> 只按 `reboot` 有機會不重新初始化 CPU 的虛擬化功能。
> 遠端機器請用 IPMI 下 power off → power on，不要只下 reset。

【2】★★★★ **旗標有但模組沒載入**：先看核心到底說了什麼。

```bash
lsmod | grep '^kvm'
```

```text
（沒有輸出）
```

```bash
sudo modprobe kvm_intel        # AMD 平台用 kvm_amd
sudo dmesg -T | grep -i kvm | tail -10
```

| `dmesg` 訊息 | 意思 | 解法 |
| --- | --- | --- |
| ★★★★★ `kvm: disabled by bios` | 韌體關著 | 回到【1】 |
| ★★★★ `kvm: no hardware support` | 這一層看不到旗標（多半是巢狀沒開） | 回到【1】 |
| ★★★ `kvm_intel: Nested Virtualization enabled` | 正常 | 繼續往下 |
| ★★★ 完全沒有 kvm 相關訊息 | 模組被 blacklist，或核心是自訂編譯的 | `grep -r kvm /etc/modprobe.d/`；換官方核心 |

★★★★ 確認模組會在開機時自己載入：

```bash
lsmod | grep '^kvm'
```

```text
kvm_intel             376832  0
kvm                  1146880  1 kvm_intel
irqbypass              12288  1 kvm
```

【3】★★★★★ **`/dev/kvm` 權限不對**：這是 `Could not access KVM kernel module: Permission denied` 的來源。

```bash
ls -l /dev/kvm
```

```text
crw-rw---- 1 root kvm 10, 232 Sep  2 09:12 /dev/kvm
```

| 你看到的 | 判定 | 處置 |
| --- | --- | --- |
| ★★★★★ `crw-rw---- root kvm` | 正確 | 檢查 QEMU 執行身分（Ubuntu `libvirt-qemu`、RHEL `qemu`）在不在 `kvm` 群組 |
| ★★★★★ `crw-rw-rw-`（666） | **有人為了省事放寬權限** | 恢復 `sudo chmod 660 /dev/kvm`，走群組授權 |
| ★★★★ 擁有者不是 `root:kvm` | udev 規則被改過 | `ls /etc/udev/rules.d/ | grep -i kvm`；移除自訂規則後重開機 |
| ★★★★ 檔案不存在 | 模組沒載入 | 回到【2】 |

```bash
id libvirt-qemu                 # Ubuntu / Debian
```

```text
uid=64055(libvirt-qemu) gid=108(kvm) groups=108(kvm)
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> - QEMU 的執行身分是 **`qemu`** 不是 `libvirt-qemu`：`id qemu`
> - 沒有 `kvm-ok` 指令（`cpu-checker` 是 Debian 系的），改用：
>   ```bash
>   lscpu | grep -i virtualization
>   sudo virt-host-validate qemu
>   ```
> - 套件名稱是 `qemu-kvm`、`libvirt`、`libvirt-client`、`virt-install`、`qemu-img`
> - SELinux 取代 AppArmor，權限問題看 `sudo ausearch -m avc -ts recent`

【4】★★★★ **hypervisor 這層都好，但連不上管理層**：先確認這台是哪一種守護行程架構。

```bash
systemctl list-units --no-pager 'virt*' 'libvirt*'
```

```text
  virtlogd.service          loaded active running Virtual machine log manager
  virtnetworkd.service      loaded active running Virtual network daemon
  virtqemud.service         loaded active running Virtualization qemu daemon
  virtstoraged.service      loaded active running Virtualization storage daemon
```

| 你看到的 | 架構 | 該操作的單元 |
| --- | --- | --- |
| ★★★★★ 有 `virtqemud`、沒有 `libvirtd` | 模組化（新） | `systemctl restart virtqemud`；網路是 `virtnetworkd`、儲存是 `virtstoraged` |
| ★★★★ 只有 `libvirtd` | 傳統單一 daemon | `systemctl restart libvirtd` |
| ★★★★ 兩個都有 | 過渡期 | 以實際 `active` 的那個為準，**不要兩個一起啟用** |
| ★★★★ 什麼都沒有 | 套件沒裝完整 | Ubuntu 補 `libvirt-daemon-system`；RHEL 補 `libvirt` |

★★★★ 訊息 `Failed to connect socket to '/var/run/libvirt/libvirt-sock': No such file or directory`
在模組化主機上是**正常的** —— 它找的是舊 socket，實際的 socket 是
`/run/libvirt/virtqemud-sock`。啟用對應的 `.socket` 單元：

```bash
sudo systemctl enable --now virtqemud.socket virtnetworkd.socket virtstoraged.socket
virsh -c qemu:///system list --all
```

**可能原因總表**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `kvm-ok` 說 CPU 不支援，但這是新機器 | 巢狀虛擬化沒開（在 VMware／PVE 裡） | 上一層 hypervisor 勾巢狀，**必須關機才能改** |
| ★★★★★ `KVM is disabled by your BIOS` | 韌體選項關著 | 進 BIOS 開啟後完整斷電再開 |
| ★★★★ `/dev/kvm does not exist` | 模組沒載入 | `modprobe kvm_intel` / `kvm_amd`，看 `dmesg` |
| ★★★★★ `Could not access KVM kernel module: Permission denied` | QEMU 執行身分沒有 `/dev/kvm` 權限 | 確認 `root:kvm 660`、`libvirt-qemu` 在 `kvm` 群組，重啟 `virtqemud` |
| ★★★★ `Unit libvirtd.service could not be found` | 模組化架構 | 改用 `virtqemud` |
| ★★★★ `virt-host-validate` 的 IOMMU 顯示 WARN | BIOS 沒開 VT-d／AMD-Vi | **只影響 PCI 直通**，一般用途可忽略，不要為它重開機 |
| ★★★ 安裝完 `virsh` 但沒有 `virt-install` | Ubuntu 的 `virtinst` 是獨立套件 | `sudo apt install virtinst` |

**原理詳見**：[[050-01-04-02-svc-KVM-安裝與virt-manager]] 的〈步驟 0：先確認硬體支援〉、
[[050-01-04-01-guide-KVM-KVM與libvirt架構]] 的〈KVM：核心裡的那一層，只管 CPU 與記憶體〉
與〈libvirtd → virtqemud：守護行程的模組化演進〉。

---

### ★★★★★ 情境二：加了 `libvirt` 群組還是不能用

**現象**：

```bash
virsh -c qemu:///system list --all
```

```text
error: failed to connect to the hypervisor
error: Failed to connect socket to '/var/run/libvirt/virtqemud-sock': Permission denied
```

你明明已經跑過 `sudo usermod -aG libvirt $USER` 了。

**判斷分流**：★★★★★ 關鍵是分辨「**檔案裡的群組**」與「**目前這個 shell 的群組**」。

```bash
id -nG $USER        # 檔案（/etc/group）裡寫的：帶參數
id -nG              # 目前這個 shell 真正持有的：不帶參數
```

```text
ops adm cdrom sudo dip plugdev libvirt kvm      ← 檔案裡有 libvirt
ops adm cdrom sudo dip plugdev                  ← 目前 shell 沒有 ★★★★★ 就是這個
```

```text
兩行一致，但仍 Permission denied  → 走【3】（不是群組問題）
兩行不一致                        → 走【1】（★★★★★ 九成是這個）
檔案裡就沒有 libvirt              → 走【2】
```

**處置步驟**：

【1】★★★★★ **重新登入**。群組成員資格是在**登入的那一刻**寫進程序憑證的，
之後改 `/etc/group` 不會回頭修改已經在跑的 shell。

```bash
exit                 # 或 logout；SSH 就是斷線重連
# 重新登入後
id -nG | tr ' ' '\n' | grep -x libvirt
```

```text
libvirt
```

★★★★ `newgrp libvirt` **只影響它開出來的那個子 shell**，開新分頁就沒了，
所以「`newgrp` 之後可以、開新視窗又不行」是完全預期的行為，不是 bug。

> [!warning] ★★★★ 圖形桌面要登出整個桌面工作階段
> 只關掉終端機視窗不夠 —— 你的終端機是桌面 session 的子程序，繼承的是舊憑證。
> 桌面環境請完整登出再登入（或直接重開機最快）。

【2】★★★★ **檔案裡就沒有**：`usermod` 打錯了（最常見是漏掉 `-a`）。

```bash
sudo usermod -aG libvirt,kvm "$USER"
id -nG "$USER"
```

> [!danger] ★★★★★ `usermod -G` 沒有 `-a` 會**清掉所有其他附加群組**
> `sudo usermod -G libvirt ops` 會讓 ops 只剩 `libvirt` 一個附加群組 ——
> `sudo` 也會一起不見。**永遠寫 `-aG`**。
> 真的做錯了：用另一個 root session 或 console 把群組補回去
> （`sudo usermod -aG sudo,adm,libvirt,kvm ops`）。相關細節見
> [[020-01-09-cmd-Linux-使用者與群組管理]]。

【3】★★★★ **群組沒問題但還是被拒**：改查 socket 本身與 polkit。

```bash
ls -l /run/libvirt/virtqemud-sock
```

```text
srwxrwx--- 1 root libvirt 0 Sep  2 09:12 /run/libvirt/virtqemud-sock
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ socket 的群組不是 `libvirt` | `/etc/libvirt/libvirtd.conf`（或 `qemu.conf`）的 `unix_sock_group` 被改過 | 改回 `unix_sock_group = "libvirt"`，重啟守護行程 |
| ★★★★ socket 檔根本不存在 | `.socket` 單元沒啟用 | `sudo systemctl enable --now virtqemud.socket` |
| ★★★ 用 `sudo virsh` 可以、一般身分不行 | 就是群組問題 | 回到【1】 |
| ★★★ 桌面上會跳出密碼視窗 | polkit 在問，不是錯誤 | 加入 `libvirt` 群組後就不會問 |

**可能原因總表**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `Permission denied` 連 socket | 加了群組沒重新登入 | 登出再登入；比對 `id -nG` 與 `id -nG $USER` |
| ★★★★ `newgrp` 之後可以、開新分頁不行 | `newgrp` 只影響該子 shell | 登出重新登入 |
| ★★★★ 只有 root 能用 | 使用者不在 `libvirt` 群組 | `usermod -aG libvirt,kvm $USER` |
| ★★★★★ 加群組後 `sudo` 不能用了 | 用了 `usermod -G` 沒加 `-a` | 從 console 以 root 把群組補回 |
| ★★★ `virt-manager` 一直跳認證視窗 | polkit 規則 | 加入 `libvirt` 群組 |

> [!danger] ★★★★★ `libvirt` 群組 ≈ 這台機器的 root
> 群組成員可以建一台 VM，把主機的 `/dev/sda` 整顆掛進去讀寫，**完全繞過檔案權限**。
> 它不是「比較安全的低權限群組」。機關環境請把成員名單當**特權帳號清單**管理，
> 定期稽核、離職立刻移除。

**原理詳見**：[[050-01-04-02-svc-KVM-安裝與virt-manager]] 的
〈`libvirt` 群組與權限：為什麼加了群組還要重新登入〉與〈步驟 3：加入群組並重新登入〉。

---

### ★★★★★ 情境三：`virsh list` 是空的 —— VM 到底去哪了

**現象**：

```bash
virsh list --all
```

```text
 Id   Name   State
--------------------
```

一片空白。但你昨天才用 `virt-manager` 建了三台，`ps` 也看得到 QEMU 程序在跑。

**判斷分流**：★★★★★ 這是 KVM 最常見、也最讓人崩潰的問題。
`qemu:///system` 與 `qemu:///session` 是**兩個完全獨立、互相看不見的世界**。

```bash
virsh uri
```

```text
qemu:///session          ← ★★★★★ 你在使用者模式，伺服器的 VM 在 system
```

```text
virsh uri 回 qemu:///session，而 VM 是在伺服器上建的  → 走【1】
virsh uri 回 qemu:///system，但 virt-manager 有 VM     → 走【2】
兩邊都空，但 ps 看得到 qemu-system 程序               → 走【3】
virsh list 空但 virsh list --all 有                    → 走【4】（不是故障）
在 PVE 主機上執行                                      → 走【5】
```

**處置步驟**：

【1】★★★★★ **切到 system 模式**。伺服器維運**一律用 `qemu:///system`**。

```bash
virsh -c qemu:///system list --all
```

```text
 Id   Name    State
-----------------------
 1    web01   running
 -    db01    shut off
```

固定下來，不要每次都打：

```bash
echo 'export LIBVIRT_DEFAULT_URI=qemu:///system' >> ~/.bashrc
source ~/.bashrc
virsh uri
```

```text
qemu:///system
```

| 差異 | `qemu:///system` | `qemu:///session` |
| --- | --- | --- |
| ★★★★★ VM 定義存在哪 | `/etc/libvirt/qemu/` | `~/.config/libvirt/qemu/` |
| ★★★★★ 磁碟預設放哪 | `/var/lib/libvirt/images/` | `~/.local/share/libvirt/images/` |
| ★★★★★ 能不能用 `virbr0` NAT | 可以 | **不行**（要 root 建 bridge 與 TAP） |
| ★★★★★ 能不能開機自動啟動 | 可以 | **不行**（使用者沒登入就沒 daemon） |
| ★★★★ QEMU 執行身分 | `libvirt-qemu` / `qemu` | 就是你自己這個帳號 |

【2】★★★★ **反過來**：`virsh` 在 system，`virt-manager` 卻連著 session。
在 virt-manager 的連線清單上看每一條連線的 URI（`File → Add Connection` 裡也看得到），
把 session 那條的 VM 用「dumpxml → 改路徑 → define 到 system」搬過去，或直接重建。

```bash
# 先把 session 裡的定義撈出來
virsh -c qemu:///session dumpxml lab01 > /tmp/lab01.xml
# 磁碟路徑要改成 system 讀得到的位置，再 define
sudo cp ~/.local/share/libvirt/images/lab01.qcow2 /var/lib/libvirt/images/
sudo sed -i 's#/home/[^<]*/lab01.qcow2#/var/lib/libvirt/images/lab01.qcow2#' /tmp/lab01.xml
sudo virsh -c qemu:///system define /tmp/lab01.xml
```

【3】★★★ **有 QEMU 程序卻沒有任何 libvirt 定義**：那些程序不是 libvirt 管的
（有人手動跑 `qemu-system-x86_64`，或這台是 PVE）。

```bash
pgrep -a -f 'qemu-system' | head
```

★★★★ 從命令列裡的 `-name guest=<名稱>` 可以認出是誰。
**不要直接 `kill -9`** —— 那等於對那台 VM 拔插頭。

【4】★★★ `virsh list` **只顯示執行中的** VM，關機的要 `--all` 才看得到。這不是故障。

【5】★★★★ **這台是 Proxmox VE**：PVE 底層確實是 KVM／QEMU，但**它不用 libvirt**，
VM 定義在 `/etc/pve/qemu-server/<vmid>.conf`，管理指令是 `qm`。

```bash
qm list
```

> [!danger] ★★★★★ 不要在 PVE 主機上安裝 libvirt
> libvirt 會建立自己的 `virbr0` 與一整組 NAT 防火牆規則，
> 跟 PVE 的 `vmbr0` 與內建防火牆互相打架，症狀是「網路開始出怪事」而且極難查。
> 誤裝了要完整移除：
> ```bash
> sudo systemctl disable --now libvirtd virtqemud virtnetworkd 2>/dev/null
> sudo apt purge libvirt-daemon-system
> sudo reboot          # 重開後確認 virbr0 消失
> ip -br link | grep virbr0
> ```

**可能原因總表**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `virsh list --all` 空白但 virt-manager 有 VM | URI 不同（session vs system） | `virsh uri` 確認；設 `LIBVIRT_DEFAULT_URI=qemu:///system` |
| ★★★★★ 一般身分空白、`sudo virsh` 有 | 一般身分落到 session、root 落到 system | 同上 |
| ★★★★ 建好的 VM 沒辦法開機自動啟動 | 建在 session 模式 | 搬到 system 模式重新 define |
| ★★★★ session 模式的 VM 連不到 `virbr0` | session 不支援 NAT 網路 | 改用 system 模式 |
| ★★★ `virsh list` 少了關機的 VM | `list` 只列 running | 加 `--all` |
| ★★★★ PVE 上 `virsh list` 空的 | PVE 不用 libvirt | 用 `qm list` |

**原理詳見**：[[050-01-04-02-svc-KVM-安裝與virt-manager]] 的
〈`qemu:///system` 與 `qemu:///session`：先搞懂再安裝〉、
[[050-01-04-01-guide-KVM-KVM與libvirt架構]] 的〈PVE 與 KVM 的關係〉。

---

### ★★★★★ 情境四：`virsh` 誤操作 —— destroy、create、undefine

**現象**：三個指令的名字和你以為的意思都不一樣，而且**每一個都會造成實際損害**。

```text
（A）打了 virsh destroy web01，以為是「刪掉這台」
     → 實際是【立即拔插頭】，服務中斷、客體檔案系統可能損毀    ★★★★★

（B）用 virsh create vm.xml 開機，主機重開之後這台 VM 永遠消失
     → create 建的是【暫態 domain】，沒有寫進 /etc/libvirt/qemu/  ★★★★★

（C）打了 virsh undefine web01，磁碟空間完全沒釋放
     → undefine 只刪【定義】，磁碟預設保留                      ★★★★★
```

**判斷分流**：★★★★★ 先把這張表背起來，尤其是同時管 PVE 的人。

| 你想做的事 | libvirt | Proxmox VE |
| --- | --- | --- |
| 優雅關機 | `virsh shutdown` | `qm shutdown` |
| **強制斷電** | **`virsh destroy`** | **`qm stop`** |
| **刪除 VM** | **`virsh undefine`** | **`qm destroy`** |

★★★★★ 注意 `destroy` 這個字在兩邊的意思**完全相反**：
libvirt 的 `destroy` 是斷電、PVE 的 `qm destroy` 是刪除。
同時管兩個平台的人最容易在這裡出事。

**處置步驟**：

【1】★★★★★ **已經 `destroy` 下去了**：VM 是被拔插頭，不是被刪。定義還在，資料多半也在。

```bash
virsh domstate web01
```

```text
shut off
```

```bash
virsh start web01
virsh console web01           # 退出是 Ctrl + ]
```

進客體之後**一定要檢查檔案系統與應用**：

```bash
# 客體內
journalctl -b -p err --no-pager | head -30
sudo dmesg -T | grep -iE 'ext4|xfs|error|recovery' | tail -20
systemctl --failed
```

| 你看到的 | 意思 | 處置 |
| --- | --- | --- |
| ★★★ `EXT4-fs: recovery complete` | journal 回放成功，一般沒事 | 觀察即可 |
| ★★★★ `EXT4-fs error` / `XFS: Corruption` | 檔案系統受損 | 單機救援模式跑 `fsck`／`xfs_repair`；先備份磁碟檔 |
| ★★★★★ 資料庫起不來、`InnoDB: Database page corruption` | 資料頁損毀 | 從備份還原，不要硬修 |

★★★★★ 正確的關機順序永遠是：`shutdown` →（等）→ 逾時才 `destroy`。

```bash
virsh shutdown web01
for i in $(seq 1 60); do
  [ "$(virsh domstate web01)" = "shut off" ] && break
  sleep 2
done
if [ "$(virsh domstate web01)" != "shut off" ]; then
  echo "警告：web01 逾時未關機，執行強制斷電" >&2
  virsh destroy web01
fi
```

【2】★★★★★ **`shutdown` 完全沒反應**：客體沒有在處理 ACPI 電源鍵訊號。

```bash
virsh shutdown web01
virsh domstate web01
```

```text
running                    ← 五分鐘後還是 running
```

| 原因 | 判斷 | 解法 |
| --- | --- | --- |
| ★★★★★ 客體沒裝 `qemu-guest-agent` | `virsh domifaddr <vm> --source agent` 也失敗 | 客體 `sudo apt install -y qemu-guest-agent && sudo systemctl enable --now qemu-guest-agent`；XML 要有 `org.qemu.guest_agent.0` 的 channel |
| ★★★★ 客體卡在某個關機任務 | `virsh console` 進去看畫面停在哪 | 處理那個服務；`systemd` 逾時設定見 [[020-01-17-cmd-Linux-systemd服務管理]] |
| ★★★★ 客體是 Windows 且有未存檔的對話框 | 主控台看得到 | 進去處理，或裝 QEMU guest agent |
| ★★★ 客體根本當掉了 | `virsh console` 無回應 | 只能 `destroy` |

裝好 agent 之後可以改用 agent 模式關機（比 ACPI 可靠）：

```bash
virsh shutdown web01 --mode agent
```

【3】★★★★★ **VM 重開機後永遠消失了**：那是 `virsh create` 開出來的**暫態 domain**。

```bash
virsh dominfo web01 | grep -E 'Persistent|Autostart'
```

```text
Persistent:     no          ← ★★★★★ 危險：主機重開就消失，而且沒有任何警告
Autostart:      no
```

★★★★★ **還在跑的時候可以救**（轉成 persistent）：

```bash
virsh dumpxml web01 > /tmp/web01.xml
virsh define /tmp/web01.xml
virsh dominfo web01 | grep Persistent
```

```text
Persistent:     yes
```

★★★★★ **已經重開機了就沒救了** —— 定義沒寫進磁碟，只能重建。
磁碟檔如果還在（`/var/lib/libvirt/images/`），資料還在，重新寫一份 XML `define` 回去即可。

★★★★★ 正確做法永遠是 `define` ＋ `start`，不要用 `create`：

| 指令 | 做什麼 | 結果 |
| --- | --- | --- |
| `virsh define <file>.xml` ★★★★★ | 只註冊定義，不啟動 | persistent domain，寫進 `/etc/libvirt/qemu/` |
| `virsh start <name>` ★★★★★ | 啟動已註冊的 | 正常 |
| ⚠️ `virsh create <file>.xml` ★★★★★ | **直接啟動但不註冊** | **暫態，關掉就消失，維運勿用** |

定期稽核，把暫態 domain 抓出來：

```bash
for v in $(virsh list --name); do
  p=$(virsh dominfo "$v" | awk -F': *' '/Persistent/{print $2}')
  [ "$p" = "no" ] && echo "★ 暫態 domain：$v"
done
```

【4】★★★★★ **`undefine` 之後空間沒釋放**：這是設計如此，`undefine` 只刪定義。

```bash
sudo du -sh /var/lib/libvirt/images/*.qcow2
```

```text
42G  /var/lib/libvirt/images/old01.qcow2      ← 定義已經刪了，磁碟還在
```

★★★★★ **刪之前的正確順序**：

```bash
# ① 先看清楚這台有哪些磁碟（★★★★★ 一定要先做這一步）
virsh domblklist old01
```

```text
 Target   Source
--------------------------------------------------
 vda      /var/lib/libvirt/images/old01.qcow2
 vdb      /srv/vmstore/shared-data.qcow2          ← ★★★★★ 這顆是共用的！
```

```bash
# ② 確認沒有別台在用那顆共用磁碟
for v in $(virsh list --all --name); do
  virsh domblklist "$v" | grep -q shared-data && echo "$v 也在用 shared-data"
done
# ③ 確認之後才刪
virsh undefine old01 --remove-all-storage
```

> [!danger] ★★★★★ `virsh undefine --remove-all-storage` 沒有回收桶
> 它會刪掉這台 VM 定義裡**所有**的磁碟檔，包含你掛給它的共用資料碟。
> 「先 `domblklist` 看清楚，再刪」是唯一的保護。
> 重要 VM 刪除前先把 XML 與磁碟另外備份一份。

其他 `undefine` 會遇到的狀況：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ `cannot undefine domain with nvram` | UEFI 客體有 NVRAM 檔 | `virsh undefine <name> --nvram` |
| ★★★★ `Requested operation is not valid: cannot undefine active domain` | VM 還在跑 | 先 `shutdown`；或用 `undefine` 保留執行中（會變成暫態，★★★★ 不建議） |
| ★★★ 有快照時 undefine 失敗 | 快照 metadata 還在 | `virsh snapshot-delete <vm> <snap> --metadata` 清完再刪 |
| ★★★ 已經 undefine 但磁碟要刪 | 定義沒了，`--remove-all-storage` 用不上 | 手動 `sudo rm /var/lib/libvirt/images/<name>.qcow2`（★★★★ 確認過再刪） |

**可能原因總表**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `destroy` 造成服務中斷 | `destroy` 是強制斷電不是刪除 | 開機後檢查客體檔案系統；改用 `shutdown` ＋ 逾時判斷 |
| ★★★★★ 主機重開後 VM 永久消失 | `create` 建的暫態 domain | 一律 `define` ＋ `start`；還在跑的 `dumpxml` 後 `define` 轉正 |
| ★★★★★ `undefine` 之後空間沒釋放 | 預設不刪磁碟 | 先 `domblklist`，再 `undefine --remove-all-storage` |
| ★★★★ 誤刪了共用資料碟 | `--remove-all-storage` 刪掉所有掛載的磁碟 | 只能從備份還原；刪前一定要 `domblklist` |
| ★★★★ 腳本用 domain Id 結果錯亂 | **Id 每次啟動都會變** | 腳本一律用名稱或 UUID |
| ★★★ 大量 VM 同時 shutdown 造成主機卡死 | 全部同時寫入磁碟 | 加間隔逐台關，或用 `virsh managedsave` |

**原理詳見**：[[050-01-04-03-cmd-KVM-virsh指令實務]] 的
〈生命週期指令：這一節請看兩次〉、〈先搞清楚四個狀態，才不會下錯指令〉
與〈`virsh` 與 PVE `qm` 完整對照表〉。

---

### ★★★★ 情境五：VM 開不起來 —— 從 log 反推

**現象**：`virsh start` 失敗，訊息通常只有一行，真正的原因在 log 裡。

```bash
virsh start web01
```

```text
error: Failed to start domain 'web01'
error: internal error: process exited while connecting to monitor: ...
```

**判斷分流**：★★★★★ **第一件事永遠是看 VM 自己的 log**，不是猜。

```bash
sudo tail -40 /var/log/libvirt/qemu/web01.log
```

```text
Permission denied              → 走【1】（AppArmor / SELinux / 檔案權限）
Failed to get "write" lock     → 走【2】（磁碟被兩個 QEMU 開著）
No such file or directory      → 走【3】（路徑錯／backing file 不見）
Could not access KVM kernel module → 回情境一
unsupported configuration / XML error → 走【4】
（log 是空的、連檔案都沒有）    → 走【5】
```

**處置步驟**：

【1】★★★★★ **`Permission denied` 但 `ls -l` 看起來完全正常**：這是強制存取控制擋的。

```bash
sudo dmesg -T | grep -iE 'apparmor|DENIED' | tail -10
```

```text
[Wed Sep  2 09:41:03 2026] audit: type=1400 apparmor="DENIED" operation="open"
  profile="libvirt-8f2a...-web01" name="/srv/vmstore/web01.qcow2" ...
```

| 情況 | 解法 |
| --- | --- |
| ★★★★★ 磁碟放在自訂路徑（`/srv/vmstore` 這類） | **把那個目錄定義成 libvirt pool** —— `virt-aa-helper` 只會替 pool 內的路徑自動加規則 |
| ★★★★ ISO 放在家目錄 | 移到 `/var/lib/libvirt/images/`；另外確認家目錄的 `others` 有 `x`（`chmod o+x /home/ops`） |
| ★★★★ 檔案擁有者不對 | `sudo chown libvirt-qemu:kvm /srv/vmstore/*.qcow2`（RHEL 是 `qemu:qemu`） |

```bash
sudo virsh pool-define-as vmstore dir --target /srv/vmstore
sudo virsh pool-build vmstore
sudo virsh pool-start vmstore
sudo virsh pool-autostart vmstore
sudo virsh start web01
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> RHEL 系是 SELinux，訊息在 audit log 裡而不是 `dmesg`：
> ```bash
> sudo ausearch -m avc -ts recent | tail -20
> ```
> 自訂路徑要打對 label（需要 `policycoreutils-python-utils` 套件）：
> ```bash
> sudo semanage fcontext -a -t virt_image_t "/srv/vmstore(/.*)?"
> sudo restorecon -Rv /srv/vmstore
> ls -Z /srv/vmstore
> ```
> 期望看到 `system_u:object_r:virt_image_t:s0`。

> [!danger] ★★★★★ 不要用 `aa-complain` / `setenforce 0` 來「解決」這個問題
> libvirt 的 **sVirt** 會替每台 VM 產生獨立的安全標籤，
> 目的是**讓 A 台 VM 的 QEMU 程序無法讀取 B 台 VM 的磁碟檔**。
> 關掉它等於拆掉 VM 之間最後一道隔離 —— 一台被打下來就全部一起淪陷。
> 正確做法是**加規則**（定義 pool 或打 SELinux label），不是關防護。

【2】★★★★★ **`Failed to get "write" lock`**：同一顆磁碟被兩個 QEMU 開著。

```bash
sudo lsof /srv/vmstore/web01.qcow2
```

```text
COMMAND     PID        USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
qemu-syst 12844 libvirt-qemu   35u   REG  253,1 12884901888  ... web01.qcow2
```

| 誰在用 | 常見原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 另一台 VM 的 QEMU | 兩份定義指到同一個磁碟（複製 XML 忘了改路徑） | `virsh dumpxml` 逐台檢查 `<source file=`；把重複的那台改掉 |
| ★★★★ `qemu-img` 程序 | 你在 VM 執行中跑了 `qemu-img convert`／`resize` | 等它跑完；★★★★★ **`qemu-img` 的大前提是 VM 必須關機** |
| ★★★★ 遷移殘留 | 遷移中斷，來源端還握著磁碟 | 來源端確認 VM 狀態，必要時 `virsh destroy` |

> [!danger] ★★★★★ 不要用 `--force-share` 硬繞過這個鎖
> 那個鎖是在保護你 —— 兩個 QEMU 同時寫同一顆 qcow2 會**直接毀掉檔案系統**，
> 而且損毀是靜默的，你會在幾天後才發現資料錯亂。

【3】★★★★ **`No such file or directory`**：路徑不對，或 backing file 不見了。
走情境七。

【4】★★★★ **XML 不合法**：

```text
error: unsupported configuration: ...
error: XML error: ...
```

```bash
virsh edit web01           # 存檔時它會驗證；有錯會問 Try again? [y,n,i,f,?]
```

★★★★★ **永遠選 `y` 回去改，絕對不要選 `i`（強制接受）** ——
`i` 會存進一個 libvirt 不接受的設定，之後 VM 可能開不起來、或安全設定失效。

★★★★★ 另外：**直接編輯 `/etc/libvirt/qemu/web01.xml` 是無效的**。
守護行程記憶體裡有一份定義，會在下次寫入時把你的修改覆蓋掉。一律用 `virsh edit`。

【5】★★★ **log 檔根本不存在**：QEMU 還沒被啟動就失敗了，錯誤在守護行程層。

```bash
sudo journalctl -u virtqemud --since '10 min ago' --no-pager | tail -30
```

**可能原因總表**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `Could not open '...': Permission denied` | AppArmor／SELinux 擋自訂路徑 | 把目錄定義成 pool；RHEL 打 `virt_image_t` label |
| ★★★★★ `Failed to get "write" lock` | 磁碟被兩個 QEMU 開著 | `lsof` 找出誰在用；**不要 `--force-share`** |
| ★★★★★ `Could not open backing file` | base 映像被移動／刪除 | 放回原絕對路徑；或 `qemu-img rebase -u -F qcow2 -b <新路徑>` |
| ★★★★ `Could not access KVM kernel module` | `/dev/kvm` 權限或模組問題 | 見情境一 |
| ★★★★ `unsupported configuration` | XML 值不合法（機型、CPU model、裝置） | `virsh edit` 修；不要選 `i` |
| ★★★★ 改了 XML 卻沒生效 | 直接編輯了檔案 | 一律 `virsh edit` |
| ★★★★ 改了 XML、完整停機再開還是沒生效 | 有 **managedsave** 狀態，是從記憶體映像恢復的 | `virsh dominfo` 看 `Managed save: yes`；`virsh managedsave-remove <vm>` 後再 `start` |
| ★★★ `virsh reboot` 之後硬體變更沒套用 | `reboot` 不重建 QEMU 程序 | `shutdown` → `start`（完整停機再開機） |

**原理詳見**：[[050-01-04-01-guide-KVM-KVM與libvirt架構]] 的〈domain XML：設定的唯一真相來源〉、
[[050-01-04-03-cmd-KVM-virsh指令實務]] 的〈改設定的三種方法〉。

---

### ★★★★ 情境六：儲存池 inactive、volume 找不到

**現象**：主機重開機後 `virt-manager` 說找不到磁碟，或 `vol-list` 看不到你剛複製進去的檔案。

```bash
virsh pool-list --all --details
```

```text
 Name      State      Autostart   Persistent   Capacity   Allocation   Available
------------------------------------------------------------------------------
 default   running    yes         yes          458.00 GiB  120.00 GiB   338.00 GiB
 vmstore   inactive   no          yes          -           -            -
```

**判斷分流**：

```text
State: inactive               → 走【1】
State: running 但 vol-list 少檔案 → 走【2】
pool-build 失敗（logical/fs）  → 走【3】
netfs pool 開機後才 inactive   → 走【4】
```

**處置步驟**：

【1】★★★★ **pool 是 inactive**：先啟動，再設自動啟動（★★★★ 這一步最常被忘記）。

```bash
sudo virsh pool-start vmstore
sudo virsh pool-autostart vmstore
virsh pool-list --all --details
```

```text
 Name      State     Autostart   Persistent
--------------------------------------------
 vmstore   running   yes         yes
```

★★★★ 一次把所有 pool 都設好：

```bash
for p in $(virsh pool-list --all --name); do
  sudo virsh pool-autostart "$p"
done
```

【2】★★★★ **檔案在目錄裡但 `vol-list` 看不到**：libvirt 快取了目錄內容，要重新掃描。

```bash
sudo cp ubuntu-24.04.iso /srv/vmstore/
virsh vol-list vmstore
```

```text
 Name              Path
------------------------------------------
 web01.qcow2       /srv/vmstore/web01.qcow2
```

```bash
sudo virsh pool-refresh vmstore
virsh vol-list vmstore
```

```text
 Name                  Path
--------------------------------------------------
 ubuntu-24.04.iso      /srv/vmstore/ubuntu-24.04.iso
 web01.qcow2           /srv/vmstore/web01.qcow2
```

★★★★ 這也是 virt-manager 裡「明明放進去了但選單看不到」的答案 ——
在 pool 的介面上按重新整理，或先在 CLI 跑 `pool-refresh`。

【3】★★★ **`pool-build` 失敗**：

| 訊息 | 原因 | 解法 |
| --- | --- | --- |
| ★★★ `Device /dev/sdc is already in use` | logical pool 的 `pool-build` 要**空的**裝置 | 已經有 VG 就**跳過 `pool-build`**，直接 `pool-start` |
| ★★★ `cannot open volume group` | VG 名稱打錯 | `sudo vgs` 對照 |
| ★★★★ dir pool 的 target 目錄不存在 | 沒建目錄 | `pool-build` 會建；或手動 `mkdir -p` |

> [!danger] ★★★★★ `pool-build` 對 `logical` 與 `fs` 型式會**格式化裝置**
> 對一顆已經有資料的磁碟跑 `pool-build`，資料會直接消失。
> 動手前務必 `lsblk -f` 確認那顆磁碟是空的。dir 型式只是建目錄，相對安全。

【4】★★★ **NFS（netfs）pool 開機後 inactive**：libvirt 啟動時 NFS 伺服器還沒就緒。

```bash
sudo systemctl status virtstoraged
showmount -e 10.0.0.30
```

| 情況 | 解法 |
| --- | --- |
| ★★★ NAS 開機比主機慢 | 把 NFS 掛載寫進 `/etc/fstab` 並加 `_netdev`，pool 用 `dir` 型式指向掛載點 |
| ★★★ 網路還沒起來 | 確認 `systemd-networkd-wait-online` 有生效 |
| ★★★★ NAS 重啟後 VM 全部卡死不回應 | 這是 NFS `hard` 掛載的**正確行為**（在等伺服器回來）。把 NAS 救回來，VM 通常會自己恢復。**不要為此改成 `soft`**，那會真的損毀檔案系統 |

**刪除 pool 的正確順序**（★★★★★ 兩個指令意思完全不同）：

| 指令 | 做什麼 | 危險度 |
| --- | --- | --- |
| `virsh pool-destroy <pool>` | **停止** pool（不刪內容） | ★★ 安全，名字很嚇人而已 |
| `virsh pool-undefine <pool>` | 刪掉 pool 的**定義**（不刪內容） | ★★★ |
| ⚠️ `virsh pool-delete <pool>` | **刪掉 pool 的內容** | ★★★★★ **不可逆** |

> [!danger] ★★★★★ `virsh pool-delete` 會刪掉整個 pool 的內容
> 對 dir pool 而言就是把 target 目錄下的東西清掉 —— 你所有 VM 的磁碟。
> 正常的「移除 pool」流程只需要 `pool-destroy` ＋ `pool-undefine`，
> **磁碟檔會原封不動留在目錄裡**。
> 除非你真的要連資料一起銷毀，否則永遠不要打 `pool-delete`。

**可能原因總表**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ 主機重開後 pool inactive | 忘了 `pool-autostart` | `virsh pool-start` ＋ `pool-autostart` |
| ★★★★ 剛放進去的 ISO/磁碟看不到 | libvirt 沒重新掃描 | `virsh pool-refresh <pool>` |
| ★★★ `Failed to build pool` + `already in use` | logical pool 的裝置已有 VG | 跳過 `pool-build`，直接 `pool-start` |
| ★★★★ netfs pool 開機後 inactive | NFS 伺服器還沒就緒 | 改用 fstab ＋ `_netdev` ＋ dir pool |
| ★★★★★ `pool-delete` 之後磁碟全沒了 | `pool-delete` 刪的是內容 | 從備份還原；平時只用 `pool-destroy` ＋ `pool-undefine` |
| ★★★ `vol-delete` 刪錯磁碟 | volume 沒有回收桶 | 從備份還原；刪前用 `virsh domblklist` 確認沒人在用 |

**原理詳見**：[[050-01-04-04-guide-KVM-儲存池與網路]] 的
〈libvirt 的儲存模型：pool 與 volume〉、〈pool 的生命週期指令〉與〈四種 pool 型式怎麼選〉。

---

### ★★★★ 情境七：空間算錯、qcow2 一直長大、backing file 鏈斷掉

**現象**：三種不同的空間問題，常被混在一起講。

```text
（A）主機磁碟滿了，但每台 VM 分配的容量加起來遠小於實體容量
     → ★★★★★ qcow2 精簡配置【超賣】，實際用量會一路長到分配上限

（B）VM 裡刪了 30 GB 的檔案，主機上的 qcow2 卻一點都沒變小
     → ★★★★ 沒有 discard/TRIM 傳遞

（C）error: Could not open backing file: No such file or directory
     → ★★★★★ 連結複製的 base 映像被移動、改名或刪掉
```

**判斷分流**：

```bash
# 先問三個數字
qemu-img info /var/lib/libvirt/images/web01.qcow2
```

```text
image: /var/lib/libvirt/images/web01.qcow2
file format: qcow2
virtual size: 40 GiB (42949672960 bytes)        ← 客體看到的大小（分配上限）
disk size: 12.4 GiB                             ← ★★★★★ 主機上真正佔的空間
cluster_size: 65536
```

```text
所有 VM 的 virtual size 加總 > 實體容量 → 走【1】（超賣）
disk size 一直長大，客體卻沒增加資料   → 走【2】
backing file 相關錯誤                  → 走【3】
disk size 遠大於客體用量且有快照       → 走【4】
```

**處置步驟**：

【1】★★★★★ **精簡配置超賣**：先算出真實的曝險。

```bash
# 分配上限總和（客體以為自己有多少）
sudo sh -c 'for f in /var/lib/libvirt/images/*.qcow2; do
  qemu-img info "$f" | awk -F"[ (]" "/virtual size/{print \$4}"
done' | paste -sd+ | bc
# 實際佔用（主機真正被吃掉多少）
sudo du -sch /var/lib/libvirt/images/*.qcow2 | tail -1
df -h /var/lib/libvirt/images
```

★★★★★ **算一次給自己看**：

| 項目 | 數字 |
| --- | --- |
| 實體儲存 | 500 GB |
| 5 台 VM 各分配 100 GB（virtual size） | 500 GB |
| 目前實際用量（disk size 加總） | 140 GB |
| **超賣比率** | 100%（分配 = 實體） |
| **危險點** | 當實際用量加總逼近 500 GB 時，**所有 VM 同時寫入失敗** |

★★★★★ 精簡配置的災難模式是「**一起死**」：磁碟寫滿的那一刻，
所有 qcow2 都無法再配置新 cluster，**每一台 VM 的檔案系統同時進入唯讀或損毀**。
而客體自己看到的 `df` 還顯示有空間，完全不會事先警告。

處置：

```bash
# 立即：找出誰長最快，先把非必要的資料搬走
sudo du -sh /var/lib/libvirt/images/* | sort -h | tail
# 短期：把某台的磁碟搬到別的儲存，或壓縮 qcow2（見【2】）
# 長期：加監控門檻，pool 使用率 80% 就告警
virsh pool-info default
```

> [!warning] ★★★★★ 監控要監控「主機的 df」，不是客體的 df
> 客體的 `df` 對主機空間一無所知。監控設定見
> [[100-01-03-guide-日誌-系統監控與告警]]，門檻建議設在 **75% 就告警、85% 就處理**，
> 因為 qcow2 增長速度不是線性的。

【2】★★★★ **qcow2 只長不縮**：需要 discard 一路傳到主機。

```bash
virsh dumpxml web01 | grep -A3 "<driver name='qemu'"
```

```text
<driver name='qemu' type='qcow2'/>          ← 沒有 discard='unmap'
```

修正（★★★★ 要完整停機再開機才生效）：

```bash
virsh edit web01
```

```xml
<driver name='qemu' type='qcow2' discard='unmap'/>
```

```bash
virsh shutdown web01 && virsh start web01
# 客體內
sudo fstrim -av
```

```text
/: 18.2 GiB (19542016000 bytes) trimmed on /dev/vda2
```

★★★★ 已經長得很大的檔案，用重寫的方式壓回去（**VM 必須關機**）：

```bash
virsh shutdown web01
qemu-img convert -p -O qcow2 /var/lib/libvirt/images/web01.qcow2 /var/lib/libvirt/images/web01-new.qcow2
qemu-img info /var/lib/libvirt/images/web01-new.qcow2
sudo mv /var/lib/libvirt/images/web01-new.qcow2 /var/lib/libvirt/images/web01.qcow2
sudo chown libvirt-qemu:kvm /var/lib/libvirt/images/web01.qcow2
virsh start web01
```

【3】★★★★★ **backing file 鏈斷掉**：連結複製（linked clone）的 base 不見了。

```bash
qemu-img info --backing-chain /var/lib/libvirt/images/lab-web01.qcow2
```

```text
image: /var/lib/libvirt/images/lab-web01.qcow2
file format: qcow2
virtual size: 20 GiB
disk size: 1.2 GiB
backing file: /var/lib/libvirt/images/base/ubuntu-24.04-base.qcow2
qemu-img: Could not open backing file: Could not open
  '/var/lib/libvirt/images/base/ubuntu-24.04-base.qcow2': No such file or directory
```

| 情況 | 解法 |
| --- | --- |
| ★★★★★ base 被移動或改名 | 放回**原本的絕對路徑**（最安全）；或改指向：`qemu-img rebase -u -F qcow2 -b /新路徑/base.qcow2 lab-web01.qcow2` |
| ★★★★★ base 被刪掉且沒備份 | **無解**，overlay 裡只有差異資料。從備份還原 base，或重建 VM |
| ★★★★ base 被改寫過（有人拿它開了 VM） | 所有 overlay 全部資料錯亂 | base 必須設**唯讀**：`sudo chmod 0444 base.qcow2` |
| ★★★ `Backing file specified without backing format` | 新版 qemu 要求明示格式 | 建立時加 `-F qcow2` |

> [!danger] ★★★★★ base 映像是所有連結複製 VM 的單點
> base 被刪、被改、被寫入，**所有基於它的 VM 一起壞掉**。三個保護措施：
> ```bash
> sudo chmod 0444 /var/lib/libvirt/images/base/ubuntu-24.04-base.qcow2   # 唯讀
> sudo chattr +i /var/lib/libvirt/images/base/ubuntu-24.04-base.qcow2    # 不可修改
> sha256sum /var/lib/libvirt/images/base/*.qcow2 > /var/lib/libvirt/images/base/SHA256SUMS
> ```
> 而且 base 要**單獨備份**，不要跟 overlay 混在一起。

★★★★ 想把 overlay 變成獨立的完整磁碟（脫離 base）：

```bash
virsh shutdown lab-web01
qemu-img convert -p -O qcow2 lab-web01.qcow2 lab-web01-full.qcow2
qemu-img info --backing-chain lab-web01-full.qcow2   # 應該只剩一層，沒有 backing file
```

【4】★★★★ **快照吃掉空間**：見情境十。

**可能原因總表**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 主機磁碟滿，客體 `df` 卻看起來很空 | qcow2 精簡配置超賣 | 監控主機 `df`；門檻 75% 告警 |
| ★★★★★ 磁碟滿的當下所有 VM 一起壞 | 精簡配置的共同失效 | 事前控制超賣比率；重要 VM 用 raw 或預配置 |
| ★★★★ qcow2 只長不縮 | 沒有 `discard='unmap'` 或沒跑 `fstrim` | 改 XML ＋ 完整重開 ＋ 客體 `fstrim -av` |
| ★★★★★ `Could not open backing file` | base 被移動／刪除 | 放回原路徑或 `qemu-img rebase -u` |
| ★★★★ 刪了 base 之後一堆 VM 全掛 | 連結複製共用 base | 從備份還原 base；平時 base 設唯讀 ＋ `chattr +i` |
| ★★★★ `qemu-img resize` 之後客體容量沒變 | 磁碟變大 ≠ 分割區與檔案系統變大 | 客體 `growpart /dev/vda 1` ＋ `resize2fs /dev/vda1`（XFS 用 `xfs_growfs /`） |
| ★★★★ `qemu-img` 對執行中的 VM 操作 | 會造成資料損毀 | ★★★★★ **`qemu-img` 的大前提是 VM 必須關機** |

**原理詳見**：[[050-01-04-04-guide-KVM-儲存池與網路]] 的〈qcow2 與 raw 的取捨〉
與〈qemu-img 六件事〉、[[050-01-04-05-guide-KVM-自動化與範本]] 的〈backing file 連結複製〉。

---

### ★★★★★ 情境八：改 bridge 之後主機失聯

**現象**：你在遠端 SSH 上跑了 `netplan apply`（或改了網路設定），**畫面就停住了，再也沒有回來**。

> [!danger] ★★★★★ 這一節請在動手之前讀，不要出事了才讀
> 建 `br0` 的過程中，**實體網卡的 IP 會被搬到 `br0` 上**。
> 中間有一小段主機沒有 IP；設定寫錯的話就是**永久沒有 IP**。
> 動手前這五件事一件都不能少：
>
> **1. 確認有備援連線** —— IPMI／iDRAC／iLO、實體 console、
>    或**第二張網卡**設一個獨立管理 IP（這次不動它）。
>
> **2. 備份現有設定**
>    ```bash
>    sudo cp -a /etc/netplan /root/netplan-backup-$(date +%F-%H%M)
>    ls -d /root/netplan-backup-*
>    ```
>
> **3. ★★★★★ 排一個「五分鐘後自動還原」的保險**
>    ```bash
>    sudo apt install -y at
>    echo 'cp -a /root/netplan-backup-*/. /etc/netplan/ && netplan apply' \
>      | sudo at now + 5 minutes
>    atq
>    ```
>    確認新設定沒問題之後**記得取消**：`sudo atrm <job 編號>`
>
> **4. 在 `tmux` 裡操作** —— SSH 斷掉時指令不會被砍到一半
>    ```bash
>    tmux new -s netfix
>    ```
>
> **5. 不要一次改兩件事** —— 建橋接就只建橋接，不要順便換網段、順便改 DNS。

**判斷分流**：

```text
還連得上，只是 VM 不通         → 走【3】
完全連不上，但排了 at 保險      → 等 5 分鐘，自動還原
完全連不上，沒排保險，有 IPMI   → 走【1】
完全連不上，沒排保險，沒 IPMI   → 走【2】（跑一趟機房）
netplan try 也救不回來          → 走【1】
```

**處置步驟**：

【1】★★★★★ **從 IPMI／實體 console 進去，直接還原備份**。

```bash
# console 上以 root 登入後
ls -d /root/netplan-backup-*
sudo cp -a /root/netplan-backup-2026-09-02-1042/. /etc/netplan/
sudo netplan apply
ip -br addr
```

```text
lo               UNKNOWN        127.0.0.1/8
enp1s0           UP             192.168.10.20/24
```

★★★★ 確認 SSH 回來了再繼續研究哪裡寫錯：

```bash
ip route
ss -tlnp | grep :22
```

【2】★★★★ **沒有備份也沒有 IPMI**：在 console 上手動把 IP 設回去，先救連線。

```bash
sudo ip link set br0 down 2>/dev/null
sudo ip addr flush dev enp1s0
sudo ip addr add 192.168.10.20/24 dev enp1s0
sudo ip link set enp1s0 up
sudo ip route add default via 192.168.10.254
ping -c2 192.168.10.254
```

★★★★ 這只是**這一次**能用，重開機就沒了。連線回來之後再好好把 netplan 寫對。

【3】★★★★ **主機自己通，但橋接的 VM 不通**：一層一層查。

```bash
ip -br addr
```

```text
enp1s0           UP             （沒有 IP，正確）
br0              UP             192.168.10.20/24
vnet0            UNKNOWN        （VM 的 TAP）
```

```bash
bridge link show master br0
```

```text
2: enp1s0: <BROADCAST,MULTICAST,UP,LOWER_UP> master br0 state forwarding
5: vnet0: <BROADCAST,MULTICAST,UP,LOWER_UP> master br0 state forwarding
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ `enp1s0` 還有 IP、主機上不了網 | 實體網卡的 `dhcp4` 忘了設 `false`，兩邊搶路由 | netplan 裡 `enp1s0` 要 `dhcp4: false, dhcp6: false` |
| ★★★★ `ip route` 的 default 走 `enp1s0` 不是 `br0` | 路由寫在錯的介面上 | 把 `routes: to: default` 放在 `br0` 底下 |
| ★★★★ `bridge link` 看不到 `enp1s0` | 沒有加進 bridge | netplan 的 `bridges.br0.interfaces` 要包含它 |
| ★★★ VM 接上 `br0` 但拿不到 IP | 交換器埠設 access ＋ port-security 只允許一個 MAC | 交換器端放寬 MAC 數量（見 [[040-01-08-guide-Juniper-埠設定與安全]]）；或給 VM 固定 IP |
| ★★★ VM 通別台、就是連不到主機 | 用了 **macvtap**，這是它的先天限制 | 改用 `br0` 橋接 |
| ★★★ 時通時不通、大量重傳 | 交換器 STP 收斂延遲；或 MTU 不一致 | 交換器埠設 edge port；主機與 VM 的 MTU 對齊 |

★★★★ 安全地套用 netplan（**永遠先 `try` 再 `apply`**）：

```bash
sudo netplan generate       # 只驗語法，不套用
sudo netplan try            # 套用，120 秒沒按 Enter 自動回滾
```

★★★★★ 但要知道 **`netplan try` 不是萬靈丹**：
設定牽涉太廣時它可能回滾不完全，而且如果你 SSH 進來的**就是被改的那條線**，
回滾期間你也連不上、按不了 Enter。所以 `at` 那道保險還是要排。

**可能原因總表**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `netplan apply` 之後完全失聯 | IP 搬移途中設定有誤 | IPMI／console 進去還原備份；平時排 `at` 保險 |
| ★★★★★ `netplan try` 也沒把我救回來 | 回滾不完全，或改的就是你連線那條 | 同上；不要只依賴 `try` |
| ★★★★ br0 起來但主機上不了網 | 實體網卡 `dhcp4` 沒設 false，或閘道打錯 | `ip -br addr` ＋ `ip route` 對照 |
| ★★★★ 改了 `50-cloud-init.yaml` 重開後被還原 | cloud-init 會覆寫它 | 新增編號更大的檔案（如 `99-kvm-bridge.yaml`） |
| ★★★★ VM 橋接後拿不到 IP | 交換器 port-security 限一個 MAC | 交換器端放寬；或固定 IP |
| ★★★ VM 連不到主機 | macvtap 的限制 | 改用 br0 |

> [!danger] ★★★★★ 橋接 = VM 直接暴露在你的實體網段上
> 一台被打下來的 VM 可以直接掃描、攻擊同網段的印表機、NAS、其他伺服器。
> **不要把實驗 VM 橋接到辦公網段** —— 用 VLAN 切出實驗網段
> （見 [[040-01-03-guide-網路設備-VLAN概念與規劃]]）。
> 另外主機的 `ufw` 預設**不會過濾橋接封包**，橋接的 VM 只受它自己的防火牆保護。

**原理詳見**：[[050-01-04-04-guide-KVM-儲存池與網路]] 的
〈橋接網路完整設定（Netplan 建 br0）〉與〈網路模型總覽〉。

---

### ★★★★★ 情境九：VM 拿不到 IP、`virbr0` 沒起來

**現象**：VM 開起來了，但 `ip a` 沒有 IP，或者 `virsh domifaddr` 查不到。

**判斷分流**：★★★★★ 由下往上五層，一層一層確認。

```text
① libvirt 網路啟動了嗎    virsh net-list --all         → inactive 走【1】
② 主機上有 virbr0 嗎       ip -br addr | grep virbr0    → 沒有走【1】
③ dnsmasq 在跑嗎           pgrep -a dnsmasq             → 沒有走【2】
④ VM 接到哪個網路          virsh domiflist <vm>         → 接錯走【3】
⑤ 客體自己的網路設定       virsh console 進去看          → 走【4】
```

**處置步驟**：

【1】★★★★ **`default` 網路沒啟動**：

```bash
virsh net-list --all
```

```text
 Name      State      Autostart   Persistent
----------------------------------------------
 default   inactive   no          yes
```

```bash
sudo virsh net-start default
sudo virsh net-autostart default
ip -br addr | grep virbr0
```

```text
virbr0           UP             192.168.122.1/24
```

★★★★ 啟動失敗時最常見的訊息：

```text
error: Failed to start network default
error: internal error: Failed to apply firewall rules
```

| 原因 | 判斷 | 解法 |
| --- | --- | --- |
| ★★★★★ 有腳本跑了 `iptables -F` | `sudo iptables -S \| grep LIBVIRT` 沒東西 | 重啟守護行程讓 libvirt 重建：`sudo systemctl restart virtnetworkd`（傳統架構是 `libvirtd`） |
| ★★★★ nftables／iptables 後端衝突 | `sudo nft list ruleset \| head` | 統一後端；重啟守護行程 |
| ★★★★ `virbr0` 的網段跟實體網段撞了 | `ip route` 有兩條 192.168.122.0/24 | `virsh net-edit default` 換一個網段 |
| ★★★ 另一個 dnsmasq 佔用了 53 埠 | `ss -ulnp \| grep :53` | 停掉衝突的服務，或改設定 |

> [!danger] ★★★★ 不要手動 `iptables -F`
> 這會把 libvirt 插的 `LIBVIRT_*` 規則一起清掉，VM 的 NAT 立刻壞掉；
> 更糟的是主機的轉送規則變成沒有限制。要清規則請重啟 libvirt 的網路守護行程讓它重建。

【2】★★★ **dnsmasq 沒跑**（NAT 網路的 DHCP 是它發的）：

```bash
pgrep -a dnsmasq
```

```text
1842 /usr/sbin/dnsmasq --conf-file=/var/lib/libvirt/dnsmasq/default.conf ...
```

```bash
# 看發過哪些租約
virsh net-dhcp-leases default
sudo cat /var/lib/libvirt/dnsmasq/virbr0.status
```

★★★ `/var/lib/libvirt/dnsmasq/*.conf` 是**自動產生的，不要手改** ——
要改設定用 `virsh net-edit default`，改完 `net-destroy` ＋ `net-start`（★★★★ 會斷 VM 網路）。

【3】★★★★ **VM 接錯網路**：

```bash
virsh domiflist web01
```

```text
 Interface   Type      Source    Model    MAC
------------------------------------------------------------------
 vnet0       network   default   virtio   52:54:00:3a:1b:9c
```

| Source | 意思 | 拿得到 IP 嗎 |
| --- | --- | --- |
| `default` ★★★★ | libvirt NAT | 有（由 dnsmasq 發） |
| `br0` ★★★★ | 橋接到實體網段 | 由**實體網段的 DHCP** 發，網段沒 DHCP 就沒有 |
| `isolated` ★★★ | 隔離網路 | 有 DHCP 就有，但完全出不去（設計如此） |
| 空白／不存在 ★★★★ | 網路定義被刪了 | 沒有 |

★★★ 改網路（要完整停機再開機才穩）：

```bash
virsh shutdown web01
virsh edit web01          # 改 <source network='default'/> 或 <source bridge='br0'/>
virsh start web01
```

【4】★★★★ **主機這層都對，客體自己沒設好**：

```bash
virsh console web01       # 退出是 Ctrl + ]
```

```bash
# 客體內
ip -br addr
sudo systemctl status systemd-networkd
sudo netplan status 2>/dev/null || cat /etc/netplan/*.yaml
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `network-config` 寫死 `enp1s0`，實際是 `ens3` | 網卡名稱依匯流排而定，會變 | cloud-init 的 `network-config` 改用 `match: macaddress:` ＋ `set-name:`，並在 `virt-install` 指定同一個 `mac=` |
| ★★★★ 客體是靜態 IP 但打錯閘道 | 設定問題 | 主控台進去改 |
| ★★★★ 客體網卡是 `sda`/`e1000` 這種模擬裝置 | 沒用 VirtIO | 改成 `virtio`（見情境十五） |
| ★★★ DHCP 有發但客體沒續約 | 租約狀態異常 | 客體 `sudo dhclient -r && sudo dhclient` |

★★★★ 查 VM 的 IP 有三種來源，**橋接網路一定要用 agent 或 arp**：

```bash
virsh domifaddr web01                   # 預設查 virbr0 的 DHCP 租約，橋接查不到
virsh domifaddr web01 --source agent    # 需要客體裝 qemu-guest-agent（★★★★ 最準）
virsh domifaddr web01 --source arp      # 查主機的 ARP 表
```

**可能原因總表**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ `default` 網路 inactive | 忘了 `net-autostart` | `net-start` ＋ `net-autostart` |
| ★★★★ `Failed to apply firewall rules` | 有人 `iptables -F` 清掉了 libvirt 規則 | 重啟 `virtnetworkd`／`libvirtd` 讓它重建 |
| ★★★★ `virsh domifaddr` 查不到 IP | 預設只查 virbr0 租約 | 加 `--source agent` 或 `--source arp` |
| ★★★★★ 客體網卡名稱對不上 | `network-config` 寫死了介面名 | 用 `match: macaddress:` ＋ `set-name:` |
| ★★★★ `net-update` 改完 DHCP 保留重開就沒了 | 沒帶 `--config` | `virsh net-update <net> ... --live --config` |
| ★★★ 改了 DHCP 範圍 VM 還拿舊 IP | 網路沒重啟，或租約沒到期 | `net-destroy` ＋ `net-start`（會斷線）；客體 `dhclient -r && dhclient` |

**原理詳見**：[[050-01-04-04-guide-KVM-儲存池與網路]] 的
〈預設 NAT 網路 `virbr0` 的封包路徑〉、〈網路的基本操作：virsh net-*〉
與〈DHCP 固定配發：讓 VM 每次都拿到同一個 IP〉。

---

### ★★★★ 情境十：快照踩雷 —— 內部與外部搞混

**現象**：

```bash
virsh snapshot-revert web01 before-upgrade
```

```text
error: unsupported configuration: revert to external snapshot not supported yet
```

**判斷分流**：★★★★★ 先確認你手上這個快照是哪一種。

```bash
virsh snapshot-list web01
virsh snapshot-info web01 before-upgrade
```

```text
Name:           before-upgrade
Domain:         web01
Current:        no
State:          shutoff
Location:       external          ← ★★★★★ 這一行是關鍵
Parent:         -
Children:       0
```

| Location | 型式 | 特性 |
| --- | --- | --- |
| ★★★★★ `internal` | 內部快照 | 存在 qcow2 檔案內部；**只支援 qcow2**；`snapshot-revert` 可用；raw 不支援 |
| ★★★★★ `external` | 外部快照 | 原檔變成唯讀 base，新寫入進 overlay；**`snapshot-revert` 不支援**；適合線上備份 |

```text
Location: external 且要 revert   → 走【1】
internal snapshots not supported with format 'raw' → 走【2】
刪了 overlay 檔 VM 開不起來      → 走【3】
blockcommit 卡住不動             → 走【4】
快照太多、VM 越來越慢            → 走【5】
```

**處置步驟**：

【1】★★★★★ **外部快照不能 revert**。三條路：

| 做法 | 說明 | 風險 |
| --- | --- | --- |
| ★★★★★ 事前就用內部快照 | 不加 `--disk-only` 就是內部快照 | 需要 qcow2；快照期間 VM 有短暫停頓 |
| ★★★★ 手動把磁碟指回 base | 關機 → `virsh edit` 把 `<source file=>` 改回 base → 刪 overlay → 清 metadata | ★★★★★ overlay 裡的資料**全部丟掉**，確認過再做 |
| ★★★ 升級 libvirt | 新版本對外部快照的支援在演進 | ★★★★★ **一定要先在測試機驗證**，不要在正式環境賭 |

手動回到 base 的完整流程（★★★★ 確認 overlay 的資料真的不要了再做）：

```bash
virsh shutdown web01
virsh domblklist web01
```

```text
 Target   Source
------------------------------------------------------
 vda      /var/lib/libvirt/images/web01.before-upgrade
```

```bash
# 先備份 overlay，萬一判斷錯還有救
sudo cp -a /var/lib/libvirt/images/web01.before-upgrade /var/backup/
virsh edit web01           # 把 <source file=> 改回 /var/lib/libvirt/images/web01.qcow2
virsh snapshot-delete web01 before-upgrade --metadata
virsh start web01
```

【2】★★★★ **`internal snapshots are not supported with format 'raw'`**：
內部快照只支援 qcow2。

```bash
virsh shutdown web01
qemu-img info /var/lib/libvirt/images/web01.raw
qemu-img convert -p -O qcow2 /var/lib/libvirt/images/web01.raw /var/lib/libvirt/images/web01.qcow2
virsh edit web01           # <driver ... type='qcow2'/>，<source file=> 改成 .qcow2
virsh start web01
```

★★★ 或者接受它，改用外部快照做備份（外部快照對 raw 是可以的）。

【3】★★★★★ **刪了 overlay 之後 VM 開不起來**：

```text
error: Failed to start domain 'web01'
error: Cannot access storage file '/var/lib/libvirt/images/web01.snap1': No such file
```

★★★★★ **這是無解的** —— 建立外部快照之後，**所有新寫入都在 overlay 裡**，
base 停留在快照當下。刪掉 overlay 等於刪掉快照之後的所有資料。

只能：

1. 從備份還原
2. 若接受回到快照當下的狀態：`virsh edit` 把磁碟指回 base，`snapshot-delete --metadata` 清乾淨

★★★★★ **正確的清理順序永遠是先合併再刪**：

```bash
virsh blockcommit web01 vda --active --pivot --verbose
```

```text
Block commit: [100 %]
Successfully pivoted
```

```bash
virsh domblklist web01           # 確認已經指回 base
qemu-img info --backing-chain /var/lib/libvirt/images/web01.qcow2
# 確認之後才刪 overlay
sudo rm /var/lib/libvirt/images/web01.snap1
virsh snapshot-delete web01 snap1 --metadata
```

【4】★★★ **`blockcommit` 卡住不動**：

```bash
virsh blockjob web01 vda --info
```

```text
Block Commit: [ 23 %]
```

| 情況 | 解法 |
| --- | --- |
| ★★★ 磁碟 I/O 忙碌 | 加 `--verbose` 看進度；改到離峰時段做 |
| ★★★ VM 寫入量太大，追不上 | 降低寫入量；或先 `virsh suspend` 讓它停一下（服務會中斷） |
| ★★★ 真的要取消 | `virsh blockjob web01 vda --abort`（★★★★ overlay 還在，資料不會掉） |

【5】★★★★ **快照鏈太長，VM 越來越慢**：每次讀取都要沿著鏈往上追。

```bash
qemu-img info --backing-chain /var/lib/libvirt/images/web01.qcow2 | grep -c '^image:'
```

```text
7                     ← ★★★★ 七層鏈，每次讀 miss 都要往上查七層
```

★★★★★ **快照不是備份**：

| 為什麼不能當備份 | 說明 |
| --- | --- |
| ★★★★★ 同一顆硬碟 | 硬碟壞了，快照跟原磁碟一起沒 |
| ★★★★★ 會拖慢效能 | 鏈越長讀取越慢，空間也越吃 |
| ★★★★ 含記憶體的快照有機敏資料 | 內部快照可能存了完整記憶體，裡面有明文密碼、金鑰、session token |

★★★ 快照的正確定位是「**短期回復點**」—— 升級前建、驗證完就合併刪掉，
不要放超過幾天。真正的備份要異地、要能還原驗證（見
[[050-01-03-06-svc-PVE-備份與還原]] 的備份原則，KVM 環境概念相同）。

**可能原因總表**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `revert to external snapshot not supported yet` | 那是外部快照 | 事前改用內部快照；或手動把磁碟指回 base |
| ★★★★ `internal snapshots are not supported with format 'raw'` | 內部快照只支援 qcow2 | `qemu-img convert -O qcow2`；或改用外部快照 |
| ★★★★★ 刪了 overlay 之後 VM 開不起來 | 磁碟鏈斷了，資料在 overlay 裡 | **無解，只能還原備份**；正確做法是先 `blockcommit --pivot` |
| ★★★ `blockcommit` 卡住 | I/O 忙碌或寫入量大 | 離峰做；必要時 `blockjob --abort` |
| ★★★★ 快照做完 VM 變很慢 | 快照鏈太長 | 定期合併清理；不要把快照當備份留著 |
| ★★★ `snapshot-delete` 失敗但快照要清 | metadata 與檔案不一致 | `--metadata` 只清 libvirt 的記錄，檔案要另外處理 |

**原理詳見**：[[050-01-04-03-cmd-KVM-virsh指令實務]] 的
〈快照：內部與外部的差別〉與〈外部快照與 `blockcommit`（備份用法）〉。

---

### ★★★★ 情境十一：cloud-init 沒生效

**現象**：VM 開起來了，但**主機名稱還是 `ubuntu`、IP 沒設、SSH 金鑰也沒進去**。

**判斷分流**：★★★★★ 三個最常見的原因，各有明確的檢查點。

```bash
# 主機端
virsh domblklist web01
```

```text
 Target   Source
------------------------------------------------------
 vda      /var/lib/libvirt/images/web01.qcow2
 sda      /var/lib/libvirt/images/seed/web01-seed.iso     ← 這一行不在就是【1】
```

```text
沒有 seed ISO 掛上去           → 走【1】
掛了但 label 不對              → 走【2】
第一行不是 #cloud-config        → 走【3】
改了 user-data 重開沒生效       → 走【4】
network-config 沒作用           → 走【5】
```

**處置步驟**：

【1】★★★★★ **seed ISO 沒掛**：`virt-install` 少了 `--disk .../seed.iso,device=cdrom`，
或事後 `virsh edit` 把它拿掉了。

```bash
virsh shutdown web01
virsh attach-disk web01 /var/lib/libvirt/images/seed/web01-seed.iso sda \
  --type cdrom --mode readonly --config
virsh start web01
```

【2】★★★★★ **ISO 的 volume label 不是 `cidata`**：cloud-init 就是靠這個 label 找設定來源。

```bash
isoinfo -d -i /var/lib/libvirt/images/seed/web01-seed.iso | grep -i 'volume id'
```

```text
Volume id: cidata
```

不是 `cidata` 就重做（`genisoimage`／`mkisofs` 的 `-volid cidata` **不能少**）：

```bash
genisoimage -output web01-seed.iso -volid cidata -joliet -rock user-data meta-data network-config
isoinfo -d -i web01-seed.iso | grep -i 'volume id'
```

★★★★ 用 `cloud-localds` 更不容易出錯（它會自己設好 label）：

```bash
cloud-localds -N network-config web01-seed.iso user-data meta-data
```

【3】★★★★★ **`user-data` 第一行不是 `#cloud-config`**：整份會被安靜地忽略。

```bash
head -1 user-data | cat -A
```

```text
#cloud-config$              ← 正確
```

```text
M-oM-;M-?#cloud-config$     ← ★★★★★ 有 BOM，會被忽略
$                           ← ★★★★★ 第一行是空白，會被忽略
```

| 問題 | 檢查 | 解法 |
| --- | --- | --- |
| ★★★★★ 有 BOM | `cat -A` 看到 `M-oM-;M-?` | `sed -i '1s/^\xEF\xBB\xBF//' user-data` |
| ★★★★★ 前面有空白行 | `cat -A` 第一行是 `$` | 刪掉開頭空白行 |
| ★★★★ CRLF 行尾 | `file user-data` 說 CRLF | `dos2unix user-data` |
| ★★★★ YAML 縮排錯 | `cloud-init schema` | 在客體內 `sudo cloud-init schema --system` |

★★★★ 在客體內看真正的錯誤：

```bash
sudo cloud-init status --long
```

```text
status: error
```

```bash
sudo cloud-init schema --system
sudo tail -80 /var/log/cloud-init-output.log
sudo grep -iE 'warn|error|traceback' /var/log/cloud-init.log | tail -20
```

【4】★★★★★ **改了 `user-data` 重開機沒生效**：這是 cloud-init 的設計 ——
它**只在「第一次開機」對一個新的 instance 執行**。判斷「是不是新 instance」靠的是
`meta-data` 裡的 `instance-id`。

```bash
# 客體內
cat /var/lib/cloud/data/instance-id
```

```text
iid-web01-001
```

兩種解法：

```bash
# 做法 A（主機端）：換一個新的 instance-id 重做 seed ISO
sed -i 's/^instance-id:.*/instance-id: iid-web01-002/' meta-data
cloud-localds -N network-config web01-seed.iso user-data meta-data
virsh shutdown web01 && virsh start web01
```

```bash
# 做法 B（客體內）：清掉狀態讓它重跑一次
sudo cloud-init clean --logs
sudo reboot
```

★★★★★ **這也是「VM 複製出來設定卻沒重跑」的根因** ——
複製時 `instance-id` 也被複製了，cloud-init 認為「這台已經設定過」。

【5】★★★★★ **`network-config` 沒作用**：多半是網卡名稱寫死了。

```bash
# 客體內看實際的網卡名稱
ip -br link
```

```text
lo               UNKNOWN        00:00:00:00:00:00
ens3             UP             52:54:00:3a:1b:9c        ← 你的 network-config 寫的是 enp1s0
```

★★★★★ 正確寫法是**用 MAC 比對再改名**，不要賭介面名：

```yaml
version: 2
ethernets:
  primary:
    match:
      macaddress: "52:54:00:3a:1b:9c"
    set-name: eth0
    addresses: [192.168.10.51/24]
    routes:
      - to: default
        via: 192.168.10.254
    nameservers:
      addresses: [192.168.10.10, 1.1.1.1]
```

並在 `virt-install` 指定同一個 MAC：

```bash
--network bridge=br0,model=virtio,mac=52:54:00:3a:1b:9c
```

**可能原因總表**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 主機名稱／IP 完全沒設 | seed ISO 沒掛，或 label 不是 `cidata` | `virsh domblklist` 確認；`isoinfo -d` 看 volume id |
| ★★★★★ `user-data` 整份被忽略 | 第一行不是 `#cloud-config`（BOM／空白行） | `head -1 user-data \| cat -A` |
| ★★★★★ 改了設定重開沒生效 | `instance-id` 沒變 | 換新的 `instance-id`；或客體 `cloud-init clean --logs` ＋ reboot |
| ★★★★ `cloud-init status` 是 `error` | YAML 縮排或 `runcmd` 寫法錯 | `cloud-init schema --system`；看 `/var/log/cloud-init-output.log` |
| ★★★★★ 網路設定沒套用 | `network-config` 寫死介面名 | 改用 `match: macaddress:` ＋ `set-name:` |
| ★★★ 設定只跑第一次，之後想每次都跑 | cloud-init 的模組有 frequency 之分 | 需要每次執行的用 `cloud_final_modules` 加 `always`；或改用 systemd unit |

**原理詳見**：[[050-01-04-05-guide-KVM-自動化與範本]] 的
〈cloud-init 是什麼、它什麼時候動作〉、〈seed ISO 是怎麼回事〉
與〈cloud-init 三個檔案怎麼寫〉。

---

### ★★★★ 情境十二：範本沒清乾淨 —— 三台 VM 拿到同一個 IP

**現象**：從同一個範本複製出三台，結果它們**輪流搶同一個 IP**，或者 SSH 進去
發現三台的 host key 一模一樣。

**判斷分流**：

```bash
# 在三台 VM 上分別跑，比對輸出
cat /etc/machine-id
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
hostname
```

```text
三台 machine-id 相同     → 走【1】（★★★★★ 這是 IP 相同的根因）
三台 host key 相同       → 走【2】（★★★★★ 資安問題）
主機名稱相同             → 走【3】
```

**處置步驟**：

【1】★★★★★ **`machine-id` 相同**：現代的 DHCP client（systemd-networkd、
NetworkManager）預設用 machine-id 衍生 DUID／client-id 去要 IP，
三台送出一樣的識別碼，DHCP 伺服器就發同一個 IP 給它們。

已經開出來的機器，**每一台**都要跑：

```bash
sudo truncate -s 0 /etc/machine-id
sudo rm -f /var/lib/dbus/machine-id
sudo reboot
```

重開後確認：

```bash
cat /etc/machine-id
```

```text
7c1e4a2f9b3d4e5a8f6c0b1d2e3f4a5b        ← 三台應該各不相同
```

★★★★★ **`truncate -s 0` 不是 `rm`** —— 檔案必須存在但是空的，systemd 才會在
下次開機重新產生。直接 `rm /etc/machine-id` 有些系統會開機失敗。

【2】★★★★★ **SSH host key 相同**：這是嚴重的資安問題 ——
整個網段的機器共用一把 host key，中間人攻擊的偵測機制**直接失效**
（你連到假的伺服器，指紋一樣，SSH 不會警告）。

```bash
sudo rm -f /etc/ssh/ssh_host_*
sudo ssh-keygen -A
sudo systemctl restart ssh
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

★★★★ 反過來說，**VM 重建之後看到 `REMOTE HOST IDENTIFICATION HAS CHANGED!` 是正確行為**，
清掉舊指紋即可：

```bash
ssh-keygen -R 192.168.10.51
```

★★★★★ 但如果**不同的機器 host key 卻相同**，那才是嚴重問題，代表範本沒清乾淨。

【3】★★★ **主機名稱相同**：cloud-init 沒生效（走情境十一），
或範本沒清 `/etc/hostname`。

★★★★★ **正確做法是在做範本的時候就清乾淨**，不要事後一台一台補。

```bash
# 範本 VM 關機後（★★★★★ 一定要先關機）
virsh shutdown ubuntu-template
sudo virt-sysprep -d ubuntu-template
```

```text
[   0.0] Examining the guest ...
[  12.3] Performing "abrt-data" ...
[  12.4] Performing "bash-history" ...
[  13.1] Performing "machine-id" ...
[  13.2] Performing "ssh-hostkeys" ...
...
[  25.7] Finishing off
```

★★★★★ `virt-sysprep` 預設會清掉的重點（`--list-operations` 可看完整清單）：

| 清什麼 | 為什麼 |
| --- | --- |
| ★★★★★ `machine-id` | 不清 → 多台搶同一個 IP |
| ★★★★★ `ssh-hostkeys` | 不清 → 整批機器共用 host key，MITM 偵測失效 |
| ★★★★ `udev-persistent-net` | 不清 → 網卡名稱錯亂 |
| ★★★★ `logfiles` | 範本的日誌會被帶到每一台 |
| ★★★★ `bash-history`、`cloud-init` 狀態 | 前者可能有密碼，後者會讓 cloud-init 不再執行 |
| ★★★ `ssh-userdir` | 加 `--operations defaults,ssh-userdir` 才會清 `~/.ssh` |

> [!danger] ★★★★★ `virt-sysprep` 會就地修改磁碟，且不可逆
> `-d <domain>` 直接改那台 VM 的磁碟。**先確認 VM 已經 `shut off`**，
> 而且務必先複製一份原始映像：
> ```bash
> virsh domstate ubuntu-template          # 必須是 shut off
> sudo cp --reflink=auto /var/lib/libvirt/images/ubuntu-template.qcow2 \
>   /var/lib/libvirt/images/base/ubuntu-template-orig.qcow2
> ```
> 對執行中的 VM 跑 `virt-sysprep` 會損毀檔案系統。

★★★★ 沒有 `libguestfs` 的環境（或指令一直失敗），可以在範本 VM 內手動清：

```bash
# 在範本 VM 內執行，執行完立刻關機、不要再開起來
sudo cloud-init clean --logs --seed
sudo rm -f /etc/ssh/ssh_host_*
sudo truncate -s 0 /etc/machine-id
sudo rm -f /var/lib/dbus/machine-id
sudo rm -rf /var/lib/cloud/instances/* /var/log/journal/*
sudo truncate -s 0 ~/.bash_history /root/.bash_history
sudo rm -f /etc/netplan/50-cloud-init.yaml   # 若要讓 cloud-init 重新產生
history -c && sudo poweroff
```

**可能原因總表**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 多台 VM 拿到同一個 IP | 範本沒清 `machine-id` | 範本先 `virt-sysprep`；已開出來的逐台 `truncate -s 0 /etc/machine-id` ＋ 刪 dbus machine-id ＋ reboot |
| ★★★★★ 多台 VM 的 SSH host key 相同 | 範本沒清 host key | `rm /etc/ssh/ssh_host_*` ＋ `ssh-keygen -A` ＋ 重啟 sshd |
| ★★★★ `REMOTE HOST IDENTIFICATION HAS CHANGED` | VM 重建，host key 換了（**正確行為**） | `ssh-keygen -R <ip>` |
| ★★★★ 複製出來的機器 cloud-init 不跑 | `instance-id` 與 cloud-init 狀態一起被複製 | 範本清 `/var/lib/cloud/`；或換 `instance-id` |
| ★★★★ `libguestfs` 指令一律失敗 | 沒有 `/dev/kvm` 權限，或 kernel 映像不可讀 | `libguestfs-test-tool 2>&1 \| tail -20` 看原因；加進 `kvm` 群組；Debian 系試 `sudo chmod 0644 /boot/vmlinuz-*` |
| ★★★★ `virt-clone` 報 `must be paused or shutoff` | 來源 VM 還在跑 | `virsh shutdown` 等到 `shut off` 再複製 |
| ★★★★★ `virsh define` 報 `already exists with uuid` | XML 範本裡的 `<uuid>` 沒刪 | `sed -i '/<uuid>/d' tpl.xml`；`<mac address=>` 也要一併刪 |

**原理詳見**：[[050-01-04-05-guide-KVM-自動化與範本]] 的
〈「範本」到底要清掉什麼〉、〈virt-sysprep：一鍵把 VM 變成範本〉與〈手動清範本〉。

---

### ★★★★ 情境十三：遷移失敗

**現象**：`virsh migrate` 各式各樣的失敗，或者「遷過去了但出事了」。

**判斷分流**：★★★★★ 遷移有三個前提，缺一不可。

```text
① 共用儲存（兩端看得到同一個磁碟路徑）
② CPU 相容（目的端要支援來源端用到的指令集）
③ 網路相通（qemu+ssh 走得通、必要的埠開著）
```

```text
Unsafe migration: Migration without shared storage → 走【1】
目的端重開機 VM 就消失                              → 走【2】
遷過去客體立刻崩潰                                  → 走【3】
兩台主機上都有這台 VM 的定義                        → 走【4】
遷移中斷／一直不收斂                                → 走【5】
```

**處置步驟**：

【1】★★★★ **沒有共用儲存**：

```text
error: Unsafe migration: Migration without shared storage is unsafe
```

| 做法 | 指令 | 適用 |
| --- | --- | --- |
| ★★★★★ 建置共用儲存（正解） | NFS pool 或 iSCSI／SAN，兩端**路徑要一模一樣** | 正式環境 |
| ★★★★ 連磁碟一起搬 | `virsh migrate --live --persistent --copy-storage-all <vm> qemu+ssh://<host>/system` | 一次性搬遷，★★★ 很慢，大磁碟要算好時間 |
| ★★★ 關機搬 | `virsh shutdown` → `scp` 磁碟 → 目的端 `define` ＋ `start` | 可以停機的場合，最單純 |

★★★★ 檢查兩端路徑是否一致：

```bash
virsh domblklist web01
ssh dst-host 'ls -l /var/lib/libvirt/images/web01.qcow2'
```

【2】★★★★★ **目的端重開機 VM 就消失**：沒加 `--persistent`，遷過去的是暫態 domain。

```bash
# 目的端確認
ssh dst-host 'virsh dominfo web01 | grep Persistent'
```

```text
Persistent:     no          ← ★★★★★ 主機重開就永久消失
```

★★★★★ 還在跑的時候可以救：

```bash
ssh dst-host 'virsh dumpxml web01 > /tmp/web01.xml && virsh define /tmp/web01.xml'
```

★★★★★ 正確的遷移指令**永遠帶 `--persistent`**：

```bash
virsh migrate --live --persistent --verbose web01 qemu+ssh://dst-host/system
```

【3】★★★★★ **遷過去客體立刻崩潰**：CPU 指令集不相容。

```bash
virsh dumpxml web01 | grep -A3 '<cpu'
```

```text
<cpu mode='host-passthrough' check='none' migratable='on'/>
```

★★★★★ `host-passthrough` 把主機 CPU 的**完整指令集**暴露給客體。
客體（或裡面的程式）用了目的端沒有的指令，遷過去就是 `SIGILL` 當場崩潰。

| CPU mode | 效能 | 可遷移性 | 建議 |
| --- | --- | --- | --- |
| `host-passthrough` ★★★★ | 最好 | **差**（兩端 CPU 要一樣） | 單機、不遷移的場合 |
| `host-model` ★★★★★ | 很好 | 中等 | 一般叢集 |
| 具名 model（如 `Nehalem`、`Skylake-Server`）★★★★★ | 略低 | **最好** | ★★★★★ 混世代叢集，**以最舊的那台 CPU 為準** |

```bash
# 看目的端支援哪些 model
ssh dst-host 'virsh cpu-models x86_64 | head -20'
virsh shutdown web01
virsh edit web01
```

```xml
<cpu mode='custom' match='exact' check='partial'>
  <model fallback='allow'>Nehalem</model>
</cpu>
```

```bash
virsh start web01       # ★★★★ 改 CPU 一定要完整停機再開機，reboot 不算
```

【4】★★★★ **兩台主機上都有定義**：沒加 `--undefinesource`。

```bash
# 來源端手動清（★★★★★ 千萬不要帶 --remove-all-storage，磁碟是共用的！）
virsh undefine web01
```

> [!danger] ★★★★★ 遷移之後在來源端 `undefine --remove-all-storage` 會刪掉共用磁碟
> 共用儲存的意思就是**兩端指的是同一顆磁碟**。在來源端加 `--remove-all-storage`
> 會把正在目的端跑的那台 VM 的磁碟刪掉。
> 來源端清定義**只能用單純的 `virsh undefine`**。

【5】★★★ **遷移一直不收斂**（記憶體改動速度超過傳輸速度）：

```bash
virsh domjobinfo web01
```

```text
Job type:         Unbounded
Data processed:   42.318 GiB
Memory remaining: 3.201 GiB       ← 一直下不去
```

| 做法 | 指令 | 代價 |
| --- | --- | --- |
| ★★★★ 允許短暫暫停完成收尾 | `virsh migrate ... --timeout 300 --timeout-suspend` | 有幾秒到幾十秒的停頓 |
| ★★★ 開啟壓縮 | `--compressed` | 吃 CPU |
| ★★★ 自動收斂（節流客體 CPU） | `--auto-converge` | 客體會暫時變慢 |
| ★★★ 放棄，改成關機搬 | `virsh shutdown` ＋ 搬 | 有停機時間，但確定成功 |

**可能原因總表**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ `Migration without shared storage is unsafe` | 沒有共用儲存 | 建共用儲存；或 `--copy-storage-all`；或關機搬 |
| ★★★★★ 目的端重開機 VM 消失 | 沒加 `--persistent` | `virsh migrate --live --persistent` |
| ★★★★★ 遷過去客體立刻崩潰 | `host-passthrough` ＋ CPU 指令集不同 | 改具名 model 或 `host-model`，以最舊 CPU 為準，改完完整停機再開機 |
| ★★★★ 兩端都有定義 | 沒加 `--undefinesource` | 來源端 `virsh undefine`（**絕不加 `--remove-all-storage`**） |
| ★★★ 遷移不收斂 | 記憶體改動太快 | `--timeout-suspend`／`--auto-converge`；或關機搬 |
| ★★★★ `qemu+ssh` 連不上 | SSH 金鑰／known_hosts 問題 | 先手動 `ssh` 一次；`ssh-copy-id`；確認 `ssh-agent` 有載入金鑰 |
| ★★★ 遷移中資料在網路上明文傳輸 | 用了未加密的 TCP 遷移 | 一律走 `qemu+ssh://` |

**原理詳見**：[[050-01-04-03-cmd-KVM-virsh指令實務]] 的
〈遷移：`migrate --live`〉與〈沒有共用儲存的遷移〉。

---

### ★★★ 情境十四：`console` 連不上、退不出來

**現象**：

```bash
virsh console web01
```

```text
Connected to domain 'web01'
Escape character is ^] (Ctrl + ])

（然後就一片空白，按 Enter 也沒反應）
```

**判斷分流**：

```text
一片空白，按 Enter 沒反應        → 走【1】（客體端沒設序列主控台）
Cannot access console: Operation not permitted → 走【2】
連上了但退不出來                 → 走【3】
主機的 GUI 畫面也是黑的          → 走【4】
```

**處置步驟**：

【1】★★★★★ **`virsh console` 是接到虛擬序列埠的**，客體必須把輸出導過去。
主機端先確認 XML 有裝置：

```bash
virsh dumpxml web01 | grep -A3 '<console'
```

```xml
<console type='pty'>
  <target type='serial' port='0'/>
</console>
```

沒有就 `virsh edit` 補上（★★★★ 要完整停機再開機）。

★★★★★ 客體端才是重點（用 GUI 或 `virt-manager` 的圖形主控台進去做）：

```bash
# 客體內
sudo sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="console=tty1 console=ttyS0,115200n8"/' /etc/default/grub
sudo update-grub                 # RHEL 系：sudo grub2-mkconfig -o /boot/grub2/grub.cfg
sudo systemctl enable --now serial-getty@ttyS0.service
sudo reboot
```

回到主機端：

```bash
virsh console web01
```

```text
Connected to domain 'web01'
Escape character is ^] (Ctrl + ])

Ubuntu 24.04.1 LTS web01 ttyS0

web01 login:
```

★★★★★ **這個設定要在範本階段就做好**，不要等到 VM 網路壞掉、進不去的時候才想起來 ——
那時候你就沒有進去改設定的管道了。

【2】★★★ **`Operation not permitted`**：已經有另一個工作階段佔用主控台。

```bash
virsh console web01 --force        # 搶佔（會把對方踢掉）
```

或先找出是誰佔著：

```bash
ps -ef | grep 'virsh console'
who
```

【3】★★★★ **退不出來**：退出鍵是 **`Ctrl + ]`**，不是 `Ctrl + C`
（`Ctrl+C` 會被送進客體，你只是在客體裡送了 SIGINT）。

| 情況 | 做法 |
| --- | --- |
| ★★★★ 一般狀況 | `Ctrl + ]` |
| ★★★ 在 tmux 裡按了沒反應 | tmux 可能攔截了，先按 tmux prefix 再處理；或改用 `Ctrl+5`（部分終端等價） |
| ★★★ 透過 SSH 且鍵盤配置特殊 | 直接關掉那個終端視窗（不會影響 VM） |
| ★★★ 想改逃逸字元 | `virsh console web01 --devname serial0`；或用 `virsh -e <char> console` |

【4】★★★ **圖形主控台也是黑的**：那是客體開機就失敗，不是 console 問題 ——
去看 `/var/log/libvirt/qemu/web01.log`，走情境五。

**可能原因總表**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `console` 一片空白 | 客體沒把輸出導到序列埠 | 客體 GRUB 加 `console=ttyS0,115200n8` ＋ `serial-getty@ttyS0` |
| ★★★ XML 裡沒有 console 裝置 | 建 VM 時沒加 | `virsh edit` 補 `<console type='pty'>`，完整停機再開機 |
| ★★★★ 退不出來 | 用了 `Ctrl+C` | 退出鍵是 **`Ctrl + ]`** |
| ★★★ `Operation not permitted` | 已有其他 session 佔用 | 找出並關掉；或 `--force` |
| ★★★ 圖形主控台黑畫面 | 客體開機失敗 | 看 `/var/log/libvirt/qemu/<vm>.log` |
| ★★★ VNC 監聽在 0.0.0.0 | 預設值被改過 | ★★★★★ 保持 `listen=127.0.0.1`，透過 `ssh -L 5901:127.0.0.1:5900` 存取 |

**原理詳見**：[[050-01-04-03-cmd-KVM-virsh指令實務]] 的
〈`virsh console`：救命工具〉與〈讓 `virsh console` 真的有畫面（客體端設定）〉。

---

### ★★★ 情境十五：效能不如預期

**現象**：VM 慢、磁碟 I/O 差、網路吞吐上不去。

**判斷分流**：★★★★★ 第一件事永遠是先確認**有沒有硬體加速**，
其他調校在沒有加速的情況下全部沒有意義。

```bash
virsh dumpxml web01 | grep -o "domain type='[a-z]*'"
```

```text
domain type='qemu'          ← ★★★★★ 這是 TCG 純軟體模擬，慢十倍以上
```

```text
domain type='qemu' / -accel tcg   → 走【1】（★★★★★ 先解決這個）
type='kvm' 但磁碟是 sda           → 走【2】（VirtIO）
type='kvm'、VirtIO 也有，還是慢    → 走【3】（CPU model / 快取 / 主機層）
```

**處置步驟**：

【1】★★★★★ **掉回 TCG**：建立 VM 時 KVM 不可用（BIOS 沒開、巢狀沒開），libvirt 自動降級。
★★★★★ 這件事**沒有任何警告訊息**，很多人一路以為「主機不夠力」而盲目加硬體。

```bash
ps -ef | grep qemu-system | grep -o '\-accel [a-z]*'
```

```text
-accel tcg
```

先修好 KVM（走情境一），然後：

```bash
virsh shutdown web01
virsh edit web01           # <domain type='qemu'> 改成 <domain type='kvm'>
virsh start web01
virsh dumpxml web01 | grep -o "domain type='[a-z]*'"
```

```text
domain type='kvm'
```

★★★★ 上線前把這個檢查寫進 SOP：

```bash
for v in $(virsh list --all --name); do
  [ -z "$v" ] && continue
  t=$(virsh dumpxml "$v" | grep -o "domain type='[a-z]*'")
  echo "$v: $t" | grep -q "type='qemu'" && echo "★★★★★ $v 沒有硬體加速！"
done
```

【2】★★★★ **沒用 VirtIO**：模擬的 IDE/SATA 與 e1000 網卡效能差很多。

```bash
virsh domblklist web01
virsh domiflist web01
```

```text
 Target   Source
------------------------------------------
 sda      /var/lib/libvirt/images/web01.qcow2       ← ★★★★ sda = SATA/IDE，不是 VirtIO

 Interface   Type      Source    Model    MAC
--------------------------------------------------------
 vnet0       network   default   e1000    52:54:00:...  ← ★★★★ e1000 是模擬網卡
```

| 裝置 | 模擬（慢） | VirtIO（快） | 客體看到 |
| --- | --- | --- | --- |
| 磁碟 ★★★★★ | IDE / SATA | `virtio-blk` / `virtio-scsi` | `sda` → `vda` |
| 網卡 ★★★★★ | `e1000` / `rtl8139` | `virtio` | 名稱不變，吞吐差很多 |
| 記憶體 ★★★ | 無 | `virtio-balloon` | 讓主機看得到實際用量 |

> [!warning] ★★★★★ 已經裝好系統的 VM 改磁碟匯流排要小心
> 磁碟從 `sda` 變成 `vda` 之後，**`/etc/fstab` 若用裝置名稱就開不了機**。
> 動手前先進客體確認：
> ```bash
> cat /etc/fstab | grep -v '^#'
> ```
> 用 `UUID=` 就沒事；用 `/dev/sda1` 這種寫法就要先改成 UUID
> （`blkid` 查 UUID）再改匯流排。Windows 客體要先在原設定下安裝 VirtIO 驅動。

【3】★★★ **加速有、VirtIO 也有，還是慢**：往下三層找。

```bash
# 客體層：是不是客體自己在燒 CPU
virsh domstats web01 --vcpu --block --interface
# 主機層：找出是哪一台在燒
top -o %CPU -b -n1 | head -15
pgrep -a -f 'guest=' | head
```

| 症狀 | 可能原因 | 處置 |
| --- | --- | --- |
| ★★★★ 主機 load 很高但找不到兇手 | 某台 VM 的 vCPU 在燒 | `top` 找 `%CPU` 最高的 `qemu-system-x86_64`，用 `pgrep -a -f guest=` 對出是哪一台 |
| ★★★★ vCPU 總數遠大於實體核心 | 超賣造成 CPU steal | 客體內看 `vmstat 1` 的 `st` 欄位；降低超賣比 |
| ★★★★ 磁碟 I/O 慢 | 快取模式選錯 | `<driver ... cache='none' io='native'/>` 是伺服器常見選擇（★★★★ 依儲存型式而異，要實測） |
| ★★★★ CPU model 用了具名的舊 model | 缺少新指令集 | 不遷移的場合可改 `host-passthrough` |
| ★★★ 巢狀環境下極慢 | 巢狀虛擬化的本質限制 | 這是預期的；確認第一層 VM 的磁碟在 SSD 上，見 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] |
| ★★★ 記憶體不夠、主機開始 swap | 超賣記憶體 | ★★★★★ 記憶體超賣比 CPU 危險得多，主機 swap 會讓所有 VM 一起變慢；`free -h` 看 available |

★★★★ 記憶體的正確算法：

```bash
virsh dominfo web01 | grep -E 'Max memory|Used memory'
```

```text
Max memory:     4194304 KiB          ← 分配上限（客體看到的）
Used memory:    4194304 KiB          ← ★★★★ 這是分配上限，不是實際用量
```

★★★★ 想知道客體真正用了多少，要裝 balloon 驅動之後查：

```bash
virsh dommemstat web01
```

```text
actual 4194304
available 4051200
unused 2874112              ← 客體實際沒用到的
rss 2103296                 ← ★★★★ 主機端這個 QEMU 程序真正佔的實體記憶體
```

**可能原因總表**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ VM 慢十倍、開機要五分鐘 | 掉回 TCG 軟體模擬 | 修好 KVM，`virsh edit` 改 `type='kvm'`，完整停機再開機 |
| ★★★★ 磁碟在客體是 `sda`、I/O 慢 | 沒用 VirtIO | 改 `bus='virtio'`；★★★★★ 先確認 fstab 用 UUID |
| ★★★★ 網路吞吐上不去 | 網卡是 `e1000`/`rtl8139` | 改成 `virtio` |
| ★★★★ 主機 load 高但找不到兇手 | 某台 VM 在燒 CPU | `pgrep -a -f 'guest='` 對出名稱 |
| ★★★★ 客體 `vmstat` 的 `st` 很高 | vCPU 超賣，被搶 CPU | 降低超賣比或搬走 |
| ★★★★ 主機開始 swap | 記憶體超賣 | ★★★★★ 記憶體不要超賣；`free -h` 看 available |
| ★★★ `dominfo` 的 Used memory 與客體 `free` 對不起來 | 那是分配上限不是用量 | 裝 balloon 驅動後用 `virsh dommemstat` |

**原理詳見**：[[050-01-04-01-guide-KVM-KVM與libvirt架構]] 的
〈QEMU：一台 VM 就是一個程序〉、〈主機記憶體：VM 的記憶體到底怎麼算〉
與〈讀懂 QEMU 命令列：從 XML 反推實際參數〉。

---

### ★★★★ 情境十六：主機重開機後 VM 都沒起來

**現象**：主機維護重開機之後，服務全部沒回來，`virsh list` 是空的。

**判斷分流**：

```bash
virsh list --all
```

```text
 Id   Name    State
-----------------------
 -    web01   shut off
 -    db01    shut off
```

```text
定義還在，只是沒啟動      → 走【1】（autostart）
定義完全不見              → 回情境四【3】（暫態 domain）
虛擬網路也沒起來          → 走【2】
pool 是 inactive          → 回情境六【1】
```

**處置步驟**：

【1】★★★★★ **沒設 autostart**：

```bash
virsh dominfo web01 | grep Autostart
```

```text
Autostart:      disable
```

```bash
sudo virsh autostart web01
sudo virsh autostart db01
virsh list --all --autostart
```

★★★★ 一次全部設好（新機建置 SOP 的最後一步）：

```bash
for v in $(virsh list --all --name); do
  [ -n "$v" ] && sudo virsh autostart "$v"
done
virsh list --all --autostart
```

★★★★ autostart 實際上就是在 `/etc/libvirt/qemu/autostart/` 建一個符號連結：

```bash
ls -l /etc/libvirt/qemu/autostart/
```

```text
web01.xml -> /etc/libvirt/qemu/web01.xml
db01.xml  -> /etc/libvirt/qemu/db01.xml
```

【2】★★★★ **網路與儲存也要各自設 autostart**：VM 的 autostart 不會連帶啟動它們。

```bash
sudo virsh net-autostart default
for p in $(virsh pool-list --all --name); do sudo virsh pool-autostart "$p"; done
virsh net-list --all
virsh pool-list --all --details
```

★★★★ 開機順序有相依性：**pool 與 network 要先起來，VM 才起得來**。
libvirt 的守護行程會處理，但 NFS pool 這種依賴外部服務的要另外注意（見情境六【4】）。

【3】★★★★ **建立一份「重開機後檢查清單」**，維護前後各跑一次比對：

```bash
#!/usr/bin/env bash
# kvm-postboot-check.sh —— 主機重開機後的驗收
set -uo pipefail
export LIBVIRT_DEFAULT_URI=qemu:///system

echo "=== 儲存池 ==="
virsh pool-list --all --details

echo "=== 虛擬網路 ==="
virsh net-list --all

echo "=== VM 狀態 ==="
for v in $(virsh list --all --name); do
  [ -z "$v" ] && continue
  printf '%-16s state=%-10s persistent=%-4s autostart=%s\n' "$v" \
    "$(virsh domstate "$v")" \
    "$(virsh dominfo "$v" | awk -F': *' '/Persistent/{print $2}')" \
    "$(virsh dominfo "$v" | awk -F': *' '/Autostart/{print $2}')"
done

echo "=== 硬體加速 ==="
for v in $(virsh list --name); do
  [ -z "$v" ] && continue
  virsh dumpxml "$v" | grep -q "domain type='kvm'" \
    || echo "★★★★★ $v 沒有使用 KVM 加速"
done
```

**可能原因總表**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 重開機後 VM 都是 shut off | 沒設 autostart | 逐台 `virsh autostart`；納入建置 SOP |
| ★★★★★ 重開機後某台 VM 完全消失 | 暫態 domain（`virsh create` 開的） | 只能重建；平時用 `define` ＋ `start` |
| ★★★★ VM 起來了但網路不通 | `default` 網路沒 autostart | `virsh net-autostart default` |
| ★★★★ VM 起不來說找不到磁碟 | pool 沒 autostart | `virsh pool-autostart <pool>` |
| ★★★ NFS pool 的 VM 開機失敗 | NAS 還沒就緒 | fstab ＋ `_netdev` ＋ dir pool |

**原理詳見**：[[050-01-04-03-cmd-KVM-virsh指令實務]] 的〈自動啟動〉、
[[050-01-04-04-guide-KVM-儲存池與網路]] 的〈pool 的生命週期指令〉。

---

## 什麼時候該停手求援

> [!danger] ★★★★★ 以下情況請立刻停止操作 —— 繼續動手會讓災情擴大或無法回復

**【1】★★★★★ 你不確定手上這個指令是「關機」「斷電」還是「刪除」**：
`shutdown` / `destroy` / `undefine` 三個字在 libvirt 與 PVE 的意義**不一樣，而且部分相反**。
停下來，先 `virsh dominfo <name>` ＋ `virsh domblklist <name>` 確認你打的是哪一台、
會動到哪幾顆磁碟，再決定。這一步花三十秒，省下的是一整晚的還原作業。

**【2】★★★★★ 下一步是不可逆操作，而你手上沒有可還原的備份**：
`virsh undefine --remove-all-storage`、`virsh pool-delete`、`virsh vol-delete`、
`virt-sysprep -d`、`qemu-img convert` 覆寫、`rm *.qcow2`。
★★★★★ **libvirt 沒有回收桶**。停下來，先把磁碟與 XML 複製一份出去。

**【3】★★★★★ 磁碟鏈已經斷了，而你想「試試看能不能修」**：
`Could not open backing file` 之後最常見的災難是「反覆嘗試 `rebase` 把鏈接錯」，
把「還原得回來」變成「徹底報廢」。先 `cp -a` 保存現況，再慢慢想。

**【4】★★★★★ 你正在遠端改主機網路，而 IPMI／console 都沒有**：
`netplan apply` 一按下去就可能永久失聯，而且 `netplan try` 救不了所有情況。
停下來，先安排好備援連線或現場人員，再動手。半夜自己賭一把是事故報告裡的常客。

**【5】★★★★ 一台主機上有多台正式 VM，而你要動的是主機層的東西**
（核心升級、儲存搬遷、網路重構、libvirt 大版本升級）：
影響範圍是「全部的 VM」而不是一台。這種事要走變更管理流程
（[[100-02-08-guide-維運-變更管理流程]]），排維護時段、通知使用者、備好回退方案。

**【6】★★★★ 症狀是「所有 VM 同時出問題」**：
單機層面找答案只會浪費時間 —— 這通常是主機磁碟寫滿、記憶體耗盡、
儲存後端掉線或網路事件。先看主機的 `df -h`、`free -h`、`dmesg -T`，
確認不是共同根因再往單台 VM 追。

**【7】★★★★ 懷疑不是故障而是入侵**：VM 裡出現不認識的高 CPU 程序、
主機上多了沒人承認的 domain、`authorized_keys` 多了不明公鑰。
★★★★★ **不要 `destroy`、不要刪 VM、不要「順便清一清」** ——
記憶體內容是證據。VM 的記憶體可以完整保存下來：

```bash
virsh dump <name> /var/forensics/<name>-$(date +%F-%H%M).dump --memory-only
```

保存後依 [[090-07-04-guide-資安實踐-資安事件應變流程]] 通報。

**【8】★★★ 同一個問題試了超過三十分鐘，開始「隨便改改看」**：
隨機修改 XML 會製造新問題，讓單一故障變成多重故障，而且沒人知道你動過什麼。
停下來，把 `virsh dumpxml` 存一份、把做過的每個動作寫下來，找第二個人一起看。

---

## 症狀 → 章節 快速對照

★★★★ 找不到自己的症狀時，用這張表反查該讀哪一篇原文。

| 你遇到的事 | 本手冊情境 | 原理篇章 |
| --- | --- | --- |
| `/dev/kvm` 不存在、`kvm-ok` 失敗、BIOS／巢狀沒開 | 情境一【1】【2】 | [[050-01-04-02-svc-KVM-安裝與virt-manager]] |
| `Could not access KVM kernel module` | 情境一【3】 | [[050-01-04-02-svc-KVM-安裝與virt-manager]] |
| `libvirtd` 找不到、socket 連不上、模組化架構 | 情境一【4】 | [[050-01-04-01-guide-KVM-KVM與libvirt架構]] |
| 加了群組還是 Permission denied、`newgrp` 的限制 | 情境二 | [[050-01-04-02-svc-KVM-安裝與virt-manager]] |
| `virsh list` 空白、system 與 session 模式 | 情境三 | [[050-01-04-02-svc-KVM-安裝與virt-manager]] |
| PVE 上 `virsh` 沒用、不要在 PVE 裝 libvirt | 情境三【5】 | [[050-01-04-01-guide-KVM-KVM與libvirt架構]] |
| `destroy` 是斷電、`create` 是暫態、`undefine` 不刪磁碟 | 情境四 | [[050-01-04-03-cmd-KVM-virsh指令實務]] |
| `shutdown` 沒反應、guest agent | 情境四【2】 | [[050-01-04-03-cmd-KVM-virsh指令實務]] |
| VM 開不起來、AppArmor／SELinux、write lock | 情境五 | [[050-01-04-04-guide-KVM-儲存池與網路]] |
| 改 XML 沒生效、managedsave、`virsh edit` | 情境五【4】 | [[050-01-04-01-guide-KVM-KVM與libvirt架構]] |
| pool inactive、`pool-refresh`、`pool-delete` 的危險 | 情境六 | [[050-01-04-04-guide-KVM-儲存池與網路]] |
| qcow2 超賣、只長不縮、`discard='unmap'` | 情境七【1】【2】 | [[050-01-04-04-guide-KVM-儲存池與網路]] |
| backing file 鏈斷掉、`qemu-img rebase` | 情境七【3】 | [[050-01-04-05-guide-KVM-自動化與範本]] |
| 改 bridge 失聯、netplan 救援、`at` 保險 | 情境八 | [[050-01-04-04-guide-KVM-儲存池與網路]] |
| `virbr0` 沒起來、VM 拿不到 IP、`iptables -F` 的災難 | 情境九 | [[050-01-04-04-guide-KVM-儲存池與網路]] |
| 內部與外部快照、`blockcommit`、快照鏈太長 | 情境十 | [[050-01-04-03-cmd-KVM-virsh指令實務]] |
| cloud-init 沒生效、`instance-id`、seed ISO label | 情境十一 | [[050-01-04-05-guide-KVM-自動化與範本]] |
| `machine-id`、SSH host key、`virt-sysprep` | 情境十二 | [[050-01-04-05-guide-KVM-自動化與範本]] |
| 遷移失敗、`--persistent`、CPU model 不相容 | 情境十三 | [[050-01-04-03-cmd-KVM-virsh指令實務]] |
| `console` 空白、`Ctrl+]`、序列埠設定 | 情境十四 | [[050-01-04-03-cmd-KVM-virsh指令實務]] |
| TCG 降級、VirtIO、CPU 模式、記憶體算法 | 情境十五 | [[050-01-04-01-guide-KVM-KVM與libvirt架構]] |
| 重開機後 VM 沒起來、autostart | 情境十六 | [[050-01-04-03-cmd-KVM-virsh指令實務]] |
| 想知道整章架構與三層關係 | 全篇背景 | [[050-01-04-01-guide-KVM-KVM與libvirt架構]] |
| 想知道自動化量產怎麼做 | 情境十一、十二 | [[050-01-04-05-guide-KVM-自動化與範本]] |
| 巢狀虛擬化本身的限制與調校 | 情境一【1】、十五【3】 | [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] |
| 同樣的問題在 PVE 上怎麼處理 | 全篇對照 | [[050-01-03-98-trouble-PVE-常見故障排除]] |

---

## 延伸閱讀

**本章各篇（原理都在這裡，本手冊只做索引）**

- [[050-01-04-00-idx-KVM-KVM與libvirt]] —— 本章索引與建議閱讀順序
- [[050-01-04-01-guide-KVM-KVM與libvirt架構]] —— ★★★★★ 三層架構、domain XML、
  QEMU 程序模型、PVE 與 KVM 的關係（情境一、三、五、十五）
- [[050-01-04-02-svc-KVM-安裝與virt-manager]] —— ★★★★★ 硬體檢查、system 與 session、
  `libvirt` 群組、遠端管理（情境一、二、三）
- [[050-01-04-03-cmd-KVM-virsh指令實務]] —— ★★★★★ 生命週期六指令、快照、console、
  遷移、`virsh` ↔ `qm` 對照（情境四、十、十三、十四、十六）
- [[050-01-04-04-guide-KVM-儲存池與網路]] —— ★★★★★ pool/volume、qemu-img、
  橋接設定與救援（情境五、六、七、八、九）
- [[050-01-04-05-guide-KVM-自動化與範本]] —— ★★★★★ virt-install、cloud-init、
  virt-sysprep、backing file（情境七、十一、十二）
- [[050-01-04-99-exam-KVM-總結小考]] —— 讀完之後測驗自己有沒有真的懂

**同群組的對照與延伸**

- [[050-01-03-98-trouble-PVE-常見故障排除]] —— ★★★★★ PVE 的對應版本，
  兩份對著看最能看清「同樣是 KVM，管理層不同帶來什麼差異」
- [[050-01-03-03-guide-PVE-虛擬機管理]] —— `qm` 指令與 `virsh` 的完整對照
- [[050-01-03-05-guide-PVE-網路設定]] —— `vmbr0` 與 `br0` 的異同
- [[050-01-03-06-svc-PVE-備份與還原]] —— 備份策略（快照不是備份）
- [[050-01-02-98-trouble-Workstation-常見故障排除]] —— 第一層 hypervisor 的問題
- [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] —— 巢狀虛擬化的設定與限制
- [[050-01-01-98-trouble-虛擬化-常見故障排除]] —— 跨平台共通的虛擬化故障
- [[050-01-01-03-ref-虛擬化-五平台橫向對照]] —— 名詞在五個平台上分別叫什麼

**排錯時常一起用到的其他章節**

- [[020-01-98-trouble-Linux-常見故障排除]] —— 主機本身的問題（磁碟滿、服務起不來、OOM）
- [[020-01-17-cmd-Linux-systemd服務管理]] —— `virtqemud` 等 unit 的排查
- [[020-01-15-cmd-Linux-磁碟分割與掛載]] —— 主機儲存空間與掛載問題
- [[020-01-16-cmd-Linux-網路基礎指令]] —— 分層排查、`ip`、`ss`、netplan
- [[020-01-09-cmd-Linux-使用者與群組管理]] —— `libvirt` 群組成員的管理與稽核
- [[090-02-07-guide-防護-SELinux與AppArmor]] —— 權限全對卻被拒時的下一站
- [[090-07-04-guide-資安實踐-資安事件應變流程]] —— 判斷是「故障」還是「入侵」之後的流程
- [[100-01-03-guide-日誌-系統監控與告警]] —— 讓 pool 寫滿在爆炸前就被發現
- [[100-02-08-guide-維運-變更管理流程]] —— 動主機層之前要走的流程
- [[100-02-10-guide-維運-故障排除方法論]] —— 制度層面的排錯流程與記錄要求
- [[040-01-03-guide-網路設備-VLAN概念與規劃]] —— 橋接前先把實驗網段切出來
