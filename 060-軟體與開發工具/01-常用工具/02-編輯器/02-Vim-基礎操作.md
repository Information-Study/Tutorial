---
title: "Vim 基礎操作"
desc: "模式概念、移動、編輯、存檔離開，救援模式的必備技能"
aliases: [vim, vi, Vim 入門, 怎麼離開 vim]
tags: [群組/軟體與開發工具, 主題/編輯器, 主題/vim]
category: 常用工具
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[03-終端機與Shell入門]]"]
updated: 2026-08-28
---

# Vim 基礎操作

> [!abstract] 這篇你會學到
> - **★★★★ 怎麼離開 vim**（最重要的一件事）
> - **模式**的概念 —— vim 與所有其他編輯器最大的不同
> - 移動、編輯、刪除、複製貼上、復原
> - **★★★ 「運算元 + 動作」的組合語法**（vim 真正的威力）
> - 搜尋、取代、跳行
> - `vi` / `vim` / `vim-tiny` 的差別與救援模式
> - **★★ swap 檔與 crash recovery**

## 前置知識

- [[03-終端機與Shell入門]] — 終端機的基本操作
- [[01-Nano-快速上手]] — 比較好上手的選擇

---

## ★★★★ 先學會離開

```
★★★★ 這是最多人卡住的地方。三個情境：

  ① 【存檔並離開】
     Esc  :wq   Enter          ← ★ w=write, q=quit
     Esc  ZZ                   ← ★ 同上（大寫兩個 Z，不用冒號）

  ② 【不存檔強制離開】（★ 改壞了想放棄）
     Esc  :q!   Enter          ← ★★★ 驚嘆號 = 強制

  ③ 【只是想看，沒改任何東西】
     Esc  :q    Enter

★★★ 先按 Esc 的理由：
  不知道自己在哪個模式時，【Esc 一定會回到 Normal 模式】
  → ★ 多按幾下也沒關係
  → ★ 有些設定會嗶一聲，正常

★★ 常見的卡住訊息：
  E37: No write since last change (add ! to override)
     → ★ 有未存的修改。要存就 :wq，不要就 :q!

  E45: 'readonly' option is set (add ! to override)
     → ★ 檔案唯讀。:w! 強制存（★ 但沒權限還是不行）
     → ★★ 忘記 sudo 時用：:w !sudo tee % > /dev/null
```

> [!danger] `:x` 與 `:wq` 的差別 ★★
> ```
> :wq   → ★★ 【一定會寫入】，即使檔案沒有任何修改
>          → ★★★ 會更新 mtime（修改時間）
>          → ★ 有些監控/備份系統會因此誤判「檔案改過了」
>
> :x    → ★ 【只有真的改過才寫入】
> ZZ    → ★ 同 :x
>
> ★★ 實務建議：養成用 :x 或 ZZ 的習慣
>   → 只是進去看一眼的話，檔案時間不會被動到
> ```

---

## 觀念說明：模式 ★★★

```
★★★ vim 與其他編輯器最大的不同：【它有模式】

  ┌──────────────────────────────────────────────┐
  │  Normal（普通模式）★★★ ← 預設，也是「家」    │
  │    · 按鍵是【指令】不是輸入文字               │
  │    · dd 刪一行、yy 複製、p 貼上               │
  │    · ★ 任何時候按 Esc 都回到這裡              │
  └──────────────────────────────────────────────┘
        │ i a o I A O                    ▲
        ▼                                │ Esc
  ┌──────────────────────────────────────────────┐
  │  Insert（插入模式）                           │
  │    · 打字就是打字（★ 跟一般編輯器一樣）        │
  │    · 左下角顯示 -- INSERT --                  │
  └──────────────────────────────────────────────┘

  Normal ─ v V Ctrl+v ─► Visual（視覺模式，選取文字）
  Normal ─ : ──────────► Command-line（指令模式，:w :q :s）
  Normal ─ R ──────────► Replace（取代模式，覆蓋輸入）

★★★ 新手最大的困惑：
  「我一開始打字為什麼沒反應/畫面亂跳？」
  → ★ 因為 vim 開啟時是 Normal 模式，按鍵被當成【指令】
  → ★★ 要先按 i 進入 Insert 模式才能打字
```

```
★★ 怎麼知道自己在哪個模式？

  左下角：
    -- INSERT --        Insert 模式
    -- VISUAL --        Visual 模式
    -- VISUAL LINE --   Visual 行模式
    -- REPLACE --       Replace 模式
    （什麼都沒有）       ★ Normal 模式

  ★ 有些 vim 沒開 showmode，在 ~/.vimrc 加：
    set showmode
    set ruler           # ★ 右下角顯示行號/欄號
```

### `vi` / `vim` / `vim-tiny` ★★

```
★★ 在 Linux 上「vi」通常是【指向 vim 的連結】，但不一定：

  vi          → ★ POSIX 定義的原始編輯器
                ★★ RHEL 最小安裝只有這個
                ★ 沒有語法高亮、沒有多層 undo、方向鍵可能不能用

  vim-tiny    → ★★ Ubuntu 最小安裝的預設
                ★★★ 「vim」指令存在，但功能被閹割
                → 沒有語法高亮、沒有 visual 模式、方向鍵在 Insert 模式會亂跳

  vim         → ★ 完整版

★★★ 檢查你裝的是哪個：
```

```bash
$ vim --version | head -2
VIM - Vi IMproved 9.1 (2024 Jan 02, compiled ...)
Included patches: 1-16

$ readlink -f "$(which vi)"
/usr/bin/vim.basic                # ★ 完整版
/usr/bin/vim.tiny                 # ★★ 閹割版

$ vim --version | grep -o '\-vimscript\|+vimscript'
$ dpkg -l | grep -E '^ii +vim'    # Ubuntu

# ★★ 裝完整版
$ sudo apt install -y vim         # Ubuntu
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> $ sudo dnf install -y vim-enhanced      # ★★ 注意套件名不是 vim
> $ rpm -q vim-minimal vim-enhanced
>
> # ★★★ RHEL 最小安裝只有 vim-minimal（就是 vi）
> #   → 救援時只能用它 → ★ 所以最基本的操作一定要會
> ```

> [!warning] vim-tiny 的方向鍵問題 ★★
> ```
> ★★ 症狀：在 Insert 模式按方向鍵，畫面出現 A B C D 而不是移動
>
> ★★ 原因：vim-tiny 沒有開 nocompatible，方向鍵的跳脫序列被當成
>          「Esc + A」→ Esc 離開 Insert 模式，A 進入行尾插入
>
> ★★★ 解法：
>   ① ★ 裝完整版 vim
>   ② ★ 建 ~/.vimrc 加一行：set nocompatible
>      （★★ 只要 ~/.vimrc 存在，vim 就會自動 nocompatible）
>   ③ ★ 用 hjkl 移動（★ 反正 Normal 模式才是正途）
> ```

---

## 基礎操作

### 進入 Insert 模式的六種方式 ★★

| 鍵 | 進入位置 | 記法 |
| --- | --- | --- |
| **`i`** | 游標**前** | **i**nsert |
| **`a`** | 游標**後** | **a**ppend ★ 最常用 |
| **`I`** | **行首**（第一個非空白字元） | 大寫 = 行的層級 |
| **`A`** | **行尾** | ★★ 很常用 |
| **`o`** | **下方開新行** | **o**pen ★★ 很常用 |
| **`O`** | **上方開新行** | |

```
★★ 實例：要在一行的結尾加東西

  ✗ 慢：按 i → 用方向鍵移到行尾 → 打字
  ✓ ★★ 快：按 A → 直接在行尾，開始打字

★★ 要在下面加一行：
  ✓ 按 o → 自動開新行並進入 Insert 模式
```

### 移動（Normal 模式）★★★

```
★★★ 基本四方向（★ 手不用離開打字區）

        k  ↑
   h ←     → l
        j  ↓

★ 記法：j 長得像向下的箭頭；h 在左邊、l 在右邊
```

| 鍵 | 作用 |
| --- | --- |
| `h` `j` `k` `l` | 左 下 上 右 |
| **`w`** | **下一個字的開頭**（word） |
| **`b`** | **上一個字的開頭**（back） |
| `e` | 這個字的結尾（end） |
| `W` `B` `E` | 同上，但**用空白分隔**（★ 忽略標點） |
| **`0`** | **行首**（第 0 欄） |
| **`^`** | **行首第一個非空白字元** |
| **`$`** | **行尾** |
| **`gg`** | **★★ 檔案開頭** |
| **`G`** | **★★ 檔案結尾** |
| **`25G`** 或 **`:25`** | **★★★ 跳到第 25 行** |
| `Ctrl+f` / `Ctrl+b` | 下一頁 / 上一頁 |
| `Ctrl+d` / `Ctrl+u` | 下半頁 / 上半頁 |
| **`%`** | **★★ 跳到配對的括號**（`{}` `()` `[]`） |
| `H` `M` `L` | 螢幕的上 / 中 / 下 |
| `zz` | ★ 把目前行置中 |
| **`Ctrl+o`** | **★★ 跳回上一個位置** |
| `Ctrl+i` | 跳回下一個位置 |
| `` ` ` `` | ★ 跳回上次跳躍前的位置 |

```
★★★ 排錯時最常用的組合：

$ sudo nginx -t
nginx: [emerg] unknown directive "prox_pass" ... /etc/nginx/sites-enabled/app:24

$ sudo vim +24 /etc/nginx/sites-enabled/app     # ★ 開檔就跳到 24 行
  → 或在 vim 內：:24  或  24G

★★ % 檢查括號配對（★ nginx / json / 程式碼超好用）
  游標放在 { 上 → 按 % → 跳到對應的 }
  → ★★ 沒跳 = 括號沒配對！
```

### 編輯與刪除 ★★★

| 鍵 | 作用 |
| --- | --- |
| **`x`** | 刪除游標處的字元 |
| `X` | 刪除游標**前**的字元 |
| **`dd`** | **★★★ 刪除整行**（★ 同時放進暫存器 = 剪下） |
| **`5dd`** | **★★ 刪除 5 行** |
| **`D`** | 從游標刪到行尾（= `d$`） |
| **`dw`** | 刪除一個字 |
| **`yy`** | **★★★ 複製整行**（yank） |
| `3yy` | 複製 3 行 |
| **`p`** | **★★★ 貼在游標後 / 下一行** |
| `P` | 貼在游標前 / 上一行 |
| **`u`** | **★★★ 復原**（undo，可連按多次） |
| **`Ctrl+r`** | **★★★ 重做**（redo） |
| **`.`** | **★★★★ 重複上一個修改指令** |
| `J` | 把下一行接到這一行（join） |
| `r<字元>` | 取代單一字元 |
| `cw` | 刪除一個字並進入 Insert（change） |
| `cc` / `S` | 刪除整行內容並進入 Insert |
| **`~`** | 切換大小寫 |
| `>>` / `<<` | ★ 縮排 / 反縮排 |

> [!tip] `.` 是 vim 最強的一個鍵 ★★★★
> ```
> ★★★★ 「.」重複上一次的【修改】動作
>
> 情境：要把五個地方的 8080 改成 3000
>   ① /8080  Enter          ← 搜尋
>   ② cw3000  Esc           ← ★ 改第一個
>   ③ n                     ← 找下一個
>   ④ .                     ← ★★★★ 重複「改成 3000」
>   ⑤ n . n . n .           ← 一直重複
>
> ★★ 比 :%s/8080/3000/g 好的地方：
>   → 你可以【逐一決定】要不要改（跳過就只按 n）
> ```

### ★★★ 運算元 + 動作（vim 真正的威力）

```
★★★★ vim 的指令是【組合】出來的，不是背下來的：

     [次數] 運算元 [次數] 動作/範圍

  運算元（operator）：
    d  刪除（delete）
    y  複製（yank）
    c  修改（change，刪除後進入 Insert）
    >  縮排      <  反縮排      gu 轉小寫   gU 轉大寫

  動作（motion）：
    w  到下一個字       $  到行尾        }  到下一個段落
    b  到上一個字       0  到行首        G  到檔尾
    e  到字尾          %  到配對括號     ip 整個段落

★★★ 組合出來就是：
    dw    刪除一個字
    d$    刪到行尾
    d}    刪到段落結尾
    dG    ★★ 刪到檔案結尾
    dgg   ★★ 刪到檔案開頭
    3dw   刪除三個字
    y$    複製到行尾
    c%    ★ 修改到配對的括號（★ 改整個 {} 區塊）
    >}    縮排到段落結尾
```

```
★★★ 文字物件（text object）—— 更精準的範圍

     i = inner（不含邊界）      a = around（含邊界）

  di"   ★★ 刪除【引號內】的內容            "hello" → ""
  da"   刪除【連引號】                     "hello" → （空）
  ci"   ★★★ 修改引號內的內容（超常用）
  di(   刪除括號內的內容
  ci{   ★★ 修改大括號內的內容
  dit   ★ 刪除 HTML 標籤內的內容（tag）
  dap   刪除整個段落（含空行）
  diw   刪除游標所在的字

★★★ 實例：改 nginx 設定
    proxy_pass http://127.0.0.1:8080;
                    ↑ 游標在這
    ci"  → 但沒有引號…

    server_name "old.example.com";
                     ↑ 游標在引號內任何位置
    ci"  → ★★ 引號內清空並進入 Insert → 直接打新的
```

### 搜尋與取代 ★★★

```
★★ 搜尋
  /pattern   Enter      向下搜尋
  ?pattern   Enter      向上搜尋
  n                     ★ 下一個
  N                     ★ 上一個
  *                     ★★ 搜尋游標所在的字（向下）
  #                     ★ 同上（向上）

  :noh                  ★★ 清掉搜尋的高亮（★ 很常用）
```

```
★★★ 取代（:s 指令）

  :s/舊/新/             這一行的【第一個】
  :s/舊/新/g            ★ 這一行的【全部】
  :%s/舊/新/g           ★★★ 【整個檔案】的全部
  :%s/舊/新/gc          ★★★★ 整個檔案，【每一個都問】(confirm)
  :10,20s/舊/新/g       ★ 第 10~20 行
  :.,$s/舊/新/g         ★ 從目前行到檔尾
  :'<,'>s/舊/新/g       ★ 在 Visual 模式選取的範圍（★ 選好按 : 會自動帶入）

  ★ 旗標：
    g  全部（不只第一個）
    c  ★★ 逐一確認
    i  忽略大小寫
    I  區分大小寫
```

```
★★ :%s/.../gc 的確認選項：
  y  換這個        n  跳過
  a  ★ 全部換（All）
  q  離開          l  換這個然後離開（last）
  Ctrl+e / Ctrl+y  捲動畫面看上下文
```

> [!tip] 分隔符號可以換 ★★
> ```
> ★★ 要取代含斜線的路徑時，用 / 當分隔符很痛苦：
>   :%s/\/var\/www\/old/\/var\/www\/new/g     ← ★ 反斜線地獄
>
> ★★★ 換一個分隔符（vim 接受任何非字母的字元）：
>   :%s#/var/www/old#/var/www/new#g           ← ★ 清楚多了
>   :%s|/var/www/old|/var/www/new|g
>   :%s,/var/www/old,/var/www/new,g
>
> ★ sed 也是一樣的規則（見 [[12-文字處理三劍客]]）
> ```

### Visual 模式 ★★

```
★★ 三種選取模式：

  v         字元選取
  V         ★★★ 【整行】選取（★ 最常用）
  Ctrl+v    ★★ 【區塊】選取（column mode）

★★ 選好之後可以：
  d / x     刪除
  y         複製
  >  <      縮排 / 反縮排（★ 可連按 . 重複）
  =         ★ 自動排版縮排
  :         ★★ 帶入 '<,'> 範圍，接著打 s/a/b/g
  u / U     轉小/大寫
  gq        ★ 依 textwidth 重排段落
```

```
★★★ Ctrl+v 區塊選取的殺手級用法：把 10 行同時註解掉

  ① 游標移到第一行行首
  ② Ctrl+v            → -- VISUAL BLOCK --
  ③ 按 9j             → 向下選 9 行（★ 只選了每行的第 1 欄）
  ④ 按 I（大寫）       → 進入 Insert
  ⑤ 打 #
  ⑥ ★★★ 按 Esc       → 【所有選取的行都加上了 #】

★★ 取消註解：
  ① Ctrl+v → 9j → l（選第一欄）→ x
```

---

## 完整實戰範例：修 nginx 設定

```bash
# ═══【1】語法檢查發現錯誤 ═══
$ sudo nginx -t
nginx: [emerg] unexpected "}" in /etc/nginx/sites-enabled/app:38
nginx: configuration file /etc/nginx/nginx.conf test failed

# ═══【2】備份 ═══
$ sudo cp /etc/nginx/sites-enabled/app{,.bak-$(date +%F-%H%M)}

# ═══【3】開檔並跳到問題行 ═══
$ sudo vim +38 /etc/nginx/sites-enabled/app
```

```
★★★ 在 vim 內的操作：

【檢查括號配對】
  游標移到最上面的 server {  的 {
  按 %                     → ★ 應該跳到對應的 }
  → 沒跳或跳錯地方 = 括號有問題

【看行號】
  :set number              → ★ 顯示行號
  :set relativenumber      → ★★ 相對行號（★ 配合 5dd 這種指令超好用）

【找所有 location】
  /location                Enter
  n n n                    → 逐一檢視

【發現第 32 行少了一個 } —— 補上】
  :32                      → 跳到 32 行
  o                        → ★ 下方開新行並進 Insert
  }                        → 打字
  Esc                      → 回 Normal

【檢查縮排】
  gg=G                     → ★★ 全檔自動縮排
                             （★ gg 到檔頭，= 排版，G 到檔尾）

【存檔】
  :w                       → 存
  :x                       → 存並離開
```

```bash
# ═══【4】驗證 ═══
$ sudo nginx -t
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test successful

$ sudo systemctl reload nginx

# ═══ ★★ 改壞了的話 ═══
$ sudo cp /etc/nginx/sites-enabled/app.bak-2026-08-28-1530 \
          /etc/nginx/sites-enabled/app
$ sudo nginx -t
```

### ★★★ 忘記 sudo 的救場

```
★★★ 情境：$ vim /etc/hosts（忘了 sudo）
      改了半天，:w 時：

  E45: 'readonly' option is set (add ! to override)
  :w!
  "/etc/hosts" E212: Can't open file for writing

★★★★ 不用重來！在 vim 內執行：

  :w !sudo tee % > /dev/null

  ★ 拆解：
    :w !cmd    把緩衝區內容【透過 stdin 餵給外部指令】
    sudo tee % tee 把 stdin 寫到檔案（% = 目前檔名）
    > /dev/null 不要把內容再印回畫面

  → 輸入密碼 → 出現：
    W12: Warning: File "/etc/hosts" has changed and the buffer was
         changed in Vim as well
    [O]K, (L)oad File:

  → ★★ 按 O（檔案已經是你要的內容了）
  → 再 :q! 離開
```

---

## swap 檔與 crash recovery ★★

```
★★ vim 編輯時會產生 .filename.swp
  → SSH 斷線 / vim 被 kill / 機器當機時，未存的內容還在裡面

★★★ 下次開同一個檔案會看到：

  E325: ATTENTION
  Found a swap file by the name ".nginx.conf.swp"
     owned by: root   dated: Thu Aug 28 15:30:12 2026
    file name: /etc/nginx/nginx.conf
     modified: YES                    ← ★★★ 有未存的修改！
  ...
  Swap file ".nginx.conf.swp" already exists!
  [O]pen Read-Only, (E)dit anyway, (R)ecover, (D)elete it, (Q)uit, (A)bort:
```

```
★★★ 怎麼選：

  modified: YES  →  ★★★ 按 R（Recover）救回未存的內容
                    → 救回後【立刻 :w 存檔】
                    → 然後 :q 離開
                    → ★★ 再開一次，這次按 D 刪掉 swap 檔

  modified: no   →  ★ 通常是上次正常離開但 swap 沒清掉
                    → 按 D 刪掉

  ★★ 另一個人正在編輯（dated 是剛剛、程式還在跑）
     → ★★★ 按 O 唯讀開啟，不要 E
     → 兩個人同時改同一個檔 = 後存的蓋掉先存的
```

```bash
# ★★ 命令列直接救援
$ sudo vim -r /etc/nginx/nginx.conf
# → 開啟後 :w 存檔

# ★ 列出所有 swap 檔
$ sudo vim -r
Swap files found:
   In directory ~/:
1.    .nginx.conf.swp
          owned by: root   dated: Thu Aug 28 15:30:12 2026

# ★ 找出散落的 swap 檔
$ sudo find /etc /var/www -name '.*.sw[a-p]' 2>/dev/null

# ★★ 確認沒有 vim 還在跑再刪
$ ps aux | grep '[v]im'
$ sudo rm /etc/nginx/.nginx.conf.swp

# ★★ 把 swap 檔集中放（~/.vimrc）
$ mkdir -p ~/.vim/swap
$ echo 'set directory=~/.vim/swap//' >> ~/.vimrc
#   ★ 結尾兩個斜線 = 用完整路徑當檔名，避免不同目錄的同名檔衝突
```

> [!warning] swap 檔可能含敏感資料 ★★★
> ```
> ★★★ 編輯 .env、私鑰、密碼檔時，swap 檔裡有【完整的內容】
>   → 而且它可能留在【網站根目錄下】
>
> ★★★★ 真實的漏洞案例：
>   攻擊者猜檔名 → https://example.com/.env.swp
>   → ★★ nginx 把它當靜態檔案吐出來 → 資料庫密碼外洩
>
> ★★★ 三個防護：
>   ① Nginx 擋掉：
>      location ~ /\. { deny all; return 404; }
>      location ~ \.(swp|swo|bak|orig|save)$ { return 404; }
>   ② 編輯敏感檔案時停用 swap：
>      $ vim -n /path/to/.env          # ★ -n = no swap
>      $ vim -c 'set noswapfile' .env
>   ③ ★ swap 集中到 ~/.vim/swap（不會留在網站目錄）
> ```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **離不開 vim** ★★★★ | 不知道指令 | `Esc` → `:q!`（不存）／`:wq`（存） |
| **打字沒反應/畫面亂跳** ★★★ | 在 Normal 模式 | 按 `i` 進 Insert |
| **`E37: No write since last change`** ★★ | 有未存的修改 | `:wq` 或 `:q!` |
| **`E45: readonly`** ★★★ | 忘記 sudo | **`:w !sudo tee % > /dev/null`** |
| **`E325: ATTENTION` swap 檔** ★★★ | 上次沒正常離開 | `modified: YES` → **`R`** 救回；否則 `D` |
| **方向鍵印出 ABCD** ★★ | vim-tiny / compatible 模式 | 裝完整 vim；`set nocompatible` |
| **貼上的程式碼縮排階梯狀** ★★★ | autoindent | **`:set paste`** 再貼，貼完 `:set nopaste` |
| **搜尋高亮不消失** ★★ | hlsearch | **`:noh`** |
| **`Ctrl+s` 卡住** ★★ | 終端機 XOFF | `Ctrl+q`；`stty -ixon` |
| **中文變亂碼** ★★ | 編碼偵測 | `:e ++enc=utf-8`；`set encoding=utf-8` |
| `:wq` 後檔案沒變 ★ | 存到別的路徑 | `:pwd` 看目前目錄；`:f` 看檔名 |
| **改了 `.env` 後網站掛掉** ★★ | 存檔時檔案權限重置 | `ls -l .env`；`chmod 640` |

### ★★★ `:set paste` 是必學的

```
★★★ 症狀：貼上 20 行 Python，變成：

  def main():
      print("a")
          print("b")
              print("c")           ← ★★ 縮排一直疊加

★★ 原因：autoindent + 貼上被當成逐字輸入（跟 nano 一樣）

★★★ 解法：
  ① :set paste          → ★ 進入貼上模式（停用所有自動處理）
  ② i                   → 進 Insert（左下角顯示 -- INSERT (paste) --）
  ③ 貼上
  ④ Esc
  ⑤ ★★ :set nopaste     → ★ 一定要記得關掉！
                          （★ 不關的話自動縮排、縮寫都失效）

★★ 更好的做法（vim 8.2+ / neovim）：
  → 支援 bracketed paste，會自動偵測，不用 :set paste
  → ★ 加到 ~/.vimrc：set clipboard=unnamedplus（需要 +clipboard）

★★★ 最好的做法：不要用貼上
  $ scp file.py server:/path/       # ★ 直接傳檔
  $ cat > file.py <<'EOF' ... EOF   # ★ heredoc
```

### 排查

```bash
# 【1】★★ 確認是哪一個 vim
$ readlink -f "$(which vi)" "$(which vim)"
$ vim --version | head -1
$ vim --version | grep -E '^\s*[+-]clipboard|[+-]python3'

# 【2】★★ 目前生效的設定
#   在 vim 內：
#   :set                 → 列出非預設的設定
#   :set number?         → ★ 查單一設定的值
#   :verbose set paste?  → ★★ 顯示這個設定【在哪個檔案被設的】
#   :scriptnames         → ★ 列出載入的所有 vimscript

# 【3】★ 排除 vimrc 問題
$ vim -u NONE file.conf          # ★★ 完全不載入任何設定
$ vim -u ~/.vimrc.minimal file.conf

# 【4】★★ swap 檔
$ sudo vim -r                    # 列出
$ sudo find / -name '.*.sw[a-p]' -mmin -60 2>/dev/null

# 【5】★ 編碼與換行
#   在 vim 內：
#   :set fileencoding?    → utf-8
#   :set fileformat?      → unix（★ dos 表示 CRLF）
#   :set ff=unix          → ★★ 轉成 LF
#   :e ++enc=big5         → 用 big5 重新開啟

# 【6】★ 看不見的字元
#   :set list             → 顯示 Tab 為 ^I、行尾為 $
#   :set listchars=tab:▸\ ,trail:·,eol:¬
```

---

## 安全性注意事項

> [!danger] 四個要點 ★★★
> ```
> ① ★★★★ 不要把 vim 寫進 sudoers
>      webadmin ALL=(root) NOPASSWD: /usr/bin/vim /etc/nginx/*
>      → ★★★★ :!/bin/bash 直接開 root shell
>      → ★ 用 sudoedit（見 [[01-Nano-快速上手]]）
>
> ② ★★★ swap 檔會外洩敏感資料
>      → .env.swp 被 web server 吐出來 = 資料庫密碼外洩
>      → ★ Nginx 擋 /\. 與 .swp/.bak/.orig
>      → ★ 編輯敏感檔用 vim -n
>
> ③ ★★ modeline 是程式碼執行風險
>      → 檔案裡的 /* vim: set ... */ 會被 vim 執行
>      → ★ 歷史上有多個 CVE
>      → ★★ ~/.vimrc 加：set nomodeline
>
> ④ ★★ 不要載入來路不明的 .vimrc / 外掛
>      → vimscript 可以執行任意指令
>      → ★ 專案目錄的 .vimrc：set noexrc（★ 預設就是關的）
> ```

```bash
# ★★ 安全設定（~/.vimrc）
$ cat >> ~/.vimrc <<'EOF'
set nomodeline                 " ★★ 停用 modeline（安全）
set noexrc                     " ★ 不載入目前目錄的 .vimrc
set directory=~/.vim/swap//    " ★★ swap 集中管理
set backupdir=~/.vim/backup//
set undodir=~/.vim/undo//
set viminfo='100,<50,s10,h,n~/.vim/viminfo
EOF
$ mkdir -p ~/.vim/{swap,backup,undo}
$ chmod 700 ~/.vim ~/.vim/{swap,backup,undo}

# ★★★ Nginx 擋編輯器殘留檔
$ sudo tee /etc/nginx/snippets/deny-editor-files.conf >/dev/null <<'EOF'
location ~ /\.            { deny all; return 404; }
location ~ \.(swp|swo|swn|bak|orig|save|rej|old|tmp)$ { return 404; }
location ~ ~$             { return 404; }
EOF
#   ★ 在 server 區塊 include snippets/deny-editor-files.conf;

# ★★ 驗證
$ curl -sko /dev/null -w '%{http_code}\n' https://example.gov.tw/.env.swp
404
```

---

## 速查表

### ★★★★ 離開

```
Esc :wq   存檔離開       Esc :x / ZZ  ★ 有改才寫入
Esc :q!   不存強制離開    Esc :q       沒改過就離開
Esc :w !sudo tee % > /dev/null    ★★★ 忘記 sudo 的救場
```

### 模式

```
i a I A o O    → Insert（★ A=行尾 o=下方開新行）
v V Ctrl+v     → Visual（★ V=整行 Ctrl+v=區塊）
:              → Command
Esc            → ★★★ 回 Normal（迷路時多按幾下）
```

### 移動

```
h j k l        左下上右
w b e          字的前後
0 ^ $          行首 / 首字 / 行尾
gg G  25G      ★★ 檔頭 / 檔尾 / 第 25 行
%              ★★ 配對括號
Ctrl+f/b       翻頁      Ctrl+o  ★★ 跳回上個位置
```

### 編輯

```
x  dd  5dd  D       刪除（★ dd=整行）
yy  3yy  p  P       複製貼上
u   Ctrl+r          ★★★ 復原 / 重做
.                   ★★★★ 重複上一個修改
J   >>  <<   ~      接行 / 縮排 / 大小寫
```

### ★★★ 運算元 + 動作

```
d/y/c + w/$/}/G/%     dw d$ dG y$ c%
di" ci" di( ci{ dit   ★★ 文字物件（i=內 a=含邊界）
```

### 搜尋取代

```
/pat  n  N  *  :noh
:%s/old/new/g         ★★ 全檔取代
:%s/old/new/gc        ★★★ 逐一確認
:%s#/a/b#/c/d#g       ★★ 換分隔符避免跳脫
:10,20s/old/new/g     ★ 指定範圍
```

### ★★★ 貼上

```
:set paste  →  i  →  貼  →  Esc  →  :set nopaste
★ 或直接用 scp / heredoc
```

### swap 救援

```
vim -r file           ★★ 救回未存的內容 → :w
vim -r                列出所有 swap
vim -n file           ★★ 編輯敏感檔（不產生 swap）
E325 → modified:YES → 按 R；no → 按 D；別人在編 → 按 O
```

### 實用設定

```vim
:set number relativenumber
:set list               " ★ 顯示 Tab 與行尾
:set ff=unix            " ★★ CRLF → LF
:noh                    " ★★ 清高亮
gg=G                    " ★★ 全檔自動縮排
:verbose set paste?     " ★★ 這個設定是誰設的
vim -u NONE f           " ★★ 不載入設定開檔
```

---

## 練習題

> [!question]- 練習 1：離開 vim ★★★
> 1. `vim /tmp/t.txt`，**不做任何事直接離開**
> 2. 進去打幾個字，**不存檔離開**
> 3. 打幾個字，**存檔離開**
> 4. `vim /etc/hosts`（**不加 sudo**），改一行，試著 `:w`
> 5. **用 `:w !sudo tee % > /dev/null` 救回來**
> 6. 出現 `[O]K, (L)oad File:` 時該按哪個？為什麼？

> [!question]- 練習 2：運算元 + 動作 ★★★
> 1. 建一個有巢狀 `{}` 的 nginx 設定檔
> 2. 游標放在 `{` 上按 `%` → 跳到哪？
> 3. **用 `d%` 刪掉整個區塊**，`u` 復原
> 4. 找一行有引號的，游標放引號內，**按 `ci"`**
> 5. **用 `dG` 刪到檔尾**，`u` 復原
> 6. **列出五個你自己組合出來的指令並說明**

> [!question]- 練習 3：`.` 與批次修改 ★★★
> 1. 建一個檔案，五處出現 `8080`
> 2. **用 `/8080` + `cw3000` + `n` + `.` 逐一修改**
> 3. `u` 全部復原
> 4. **用 `:%s/8080/3000/gc` 再做一次**
> 5. 兩種方法各適合什麼情境？
> 6. **用 `Ctrl+v` 把前五行都加上 `# `**

> [!question]- 練習 4：swap 救援 ★★★
> 1. `vim /tmp/test.txt`，打十行**但不存檔**
> 2. **在另一個視窗 `kill -9` 掉那個 vim**
> 3. 重新 `vim /tmp/test.txt` → **看到什麼訊息？**
> 4. `modified:` 是什麼？**按 R 之後內容回來了嗎？**
> 5. **存檔後再開一次** → 還有訊息嗎？該按什麼？
> 6. `sudo find / -name '.*.sw[a-p]'` 找找系統上有沒有殘留的

> [!question]- 練習 5：貼上與安全 ★★★
> 1. 複製一段 15 行的 Python，**直接貼進 vim** → 縮排如何？
> 2. `u` 復原，**`:set paste` 再貼一次** → 呢？
> 3. 記得 `:set nopaste`
> 4. **`vim /var/www/html/.env`，不存檔，另開視窗找 `.env.swp`**
> 5. **`curl http://localhost/.env.swp`** → 拿得到內容嗎？
> 6. **加上 Nginx 的擋檔規則再測一次**

---

## 小測驗

Q1. **不存檔強制離開 vim 的指令**？`:wq`、`:x`、`ZZ` 有什麼差別？

Q2. **剛開啟 vim 打字沒反應，為什麼**？怎麼辦？

Q3. **忘記加 `sudo` 就編輯了 `/etc/hosts`，改完存不了，怎麼救**？指令怎麼運作？

Q4. **`dw`、`d$`、`dG`、`di"` 各是什麼**？vim 的指令設計原則是什麼？

Q5. **`.` 這個鍵做什麼**？舉一個比 `:%s` 更適合用它的情境。

Q6. **貼上程式碼縮排變階梯狀，原因與解法**？

Q7. **開檔看到 `E325: ATTENTION` 與 swap 檔，`modified: YES` 時該按哪個**？

Q8. **`.env.swp` 為什麼是資安問題**？三個防護方式？

Q9. **`vim-tiny` 和完整 `vim` 差在哪**？怎麼確認自己裝的是哪個？

Q10. **為什麼 `~/.vimrc` 要加 `set nomodeline`**？

> [!question]- 測驗答案
> **Q1.** **`:q!`** —— 驚嘆號代表「強制」，捨棄所有未存的修改直接離開。
> **三者的差別**：
> **`:wq`** = **★★ 一定會寫入**，即使檔案完全沒改過 ——
> 這會**更新檔案的 mtime**，有些監控或備份系統會因此誤判「設定檔被改了」，
> 也會讓 `find -mtime` 的稽核結果失真。
> **`:x`** = **只有真的改過才寫入**，沒改就等同 `:q`。
> **`ZZ`** = 和 `:x` 完全相同（不用打冒號，Normal 模式直接按兩下大寫 Z）。
> **★★ 實務建議養成用 `:x` 或 `ZZ`** ——
> 只是進去看一眼的話，檔案時間不會被動到。
>
> **Q2.** 因為 **vim 開啟時是 Normal 模式，按鍵被當成「指令」而不是文字輸入**。
> 這是 vim 與所有其他編輯器最大的不同 —— **它有模式**。
> 你打的 `dd` 會刪掉一行、`x` 會刪字元、`:` 會跳到指令列，
> 所以畫面才會看起來亂跳。
> **解法：按 `i` 進入 Insert 模式**（左下角出現 `-- INSERT --`）就能正常打字。
> 進入 Insert 的六個鍵各有用途：
> `i` 游標前、**`a` 游標後**、`I` 行首、**`A` 行尾**、
> **`o` 下方開新行**、`O` 上方開新行 —— 選對的那個可以省下一堆游標移動。
> 隨時按 **`Esc` 回到 Normal**（迷路時多按幾下都沒關係）。
>
> **Q3.** **在 vim 內執行**：
> ```
> :w !sudo tee % > /dev/null
> ```
> **不用重打，改的內容都保得住**。
> **拆解**：
> `:w !cmd` 是「把緩衝區的內容**透過 stdin 餵給外部指令**」（不是寫檔）；
> `sudo tee %` 用 root 權限把 stdin 寫進檔案，**`%` 是 vim 裡代表目前檔名**的變數；
> `> /dev/null` 是因為 `tee` 預設也會把內容印到 stdout，不丟掉的話畫面會被洗版。
> 執行後 vim 會提示
> `W12: Warning: File ... has changed ... [O]K, (L)oad File:` ——
> **★★ 按 `O`（OK）**，因為磁碟上的檔案已經就是你緩衝區的內容了，
> 按 `L` 反而會重新載入（結果一樣，但多此一舉）。然後 `:q!` 離開。
>
> **Q4.** `dw` = 刪除一個字；`d$` = 刪到行尾；
> **`dG` = 從目前行刪到檔案結尾**；
> **`di"` = 刪除引號內的內容**（不含引號本身）。
> **設計原則：★★★★ vim 的指令是「運算元 + 動作」組合出來的，不是背下來的**：
> ```
> 運算元：d 刪除 / y 複製 / c 修改 / > 縮排 / gU 轉大寫
> 動作：  w 一個字 / $ 行尾 / } 段落 / G 檔尾 / % 配對括號
> ```
> 學會 6 個運算元和 10 個動作，就等於會了 60 個指令。
> 再加上**文字物件**（`i` = inner 不含邊界、`a` = around 含邊界）：
> `ci"` 改引號內、`ci{` 改大括號內、`dit` 刪 HTML 標籤內、`diw` 刪一個字。
>
> **Q5.** **★★★★ `.` 重複上一次的「修改」動作**（不是移動，是修改）。
> **比 `:%s` 更適合的情境：需要逐一判斷要不要改的時候**。
> 例如檔案裡有 8 處 `8080`，但其中 3 處是註解或別的服務**不該動**：
> ```
> /8080  Enter      ← 搜尋
> cw3000  Esc       ← 改第一個
> n                 ← 找下一個 → 看一眼，要改
> .                 ← ★ 重複「改成 3000」
> n                 ← 下一個 → ★ 這個不該改，就只按 n 跳過
> n .  n .          ← 繼續
> ```
> `:%s/8080/3000/g` 會**全部無差別取代**；
> `:%s/8080/3000/gc` 雖然也能逐一確認，但 `.` 的方式更靈活
> （中途可以做別的事、可以搭配不同的修改指令）。
>
> **Q6.** **原因：autoindent 與貼上疊加**（跟 nano 完全一樣的問題）。
> 終端機的貼上等同於**逐字模擬鍵盤輸入**，vim 以為你在打字，
> 每次換行就自動補上前一行的縮排，而貼上的內容**本身也有縮排**，兩者相加。
> **解法**：
> ```
> :set paste        ★ 停用所有自動處理（左下角顯示 -- INSERT (paste) --）
> i → 貼上 → Esc
> :set nopaste      ★★ 一定要記得關掉！不關的話自動縮排、縮寫全失效
> ```
> **vim 8.2+ / neovim** 支援 bracketed paste，會自動偵測，通常不需要 `:set paste`。
> **★★★ 最好的做法是不要用貼上**：`scp` 傳檔，或用 heredoc
> `cat > f.py <<'EOF' ... EOF`（單引號的 EOF 表示不做變數展開）。
>
> **Q7.** **`modified: YES` 表示 swap 檔裡有「還沒存到磁碟的修改」→ ★★★ 按 `R`（Recover）**。
> 救回之後**立刻 `:w` 存檔**，再 `:q` 離開；
> **然後再開一次同一個檔案，這次按 `D` 刪掉 swap 檔**（否則每次開都會問）。
> **其他情況**：
> `modified: no` → 通常是上次沒正常離開但內容其實已存好 → 按 **`D`** 刪掉；
> **`dated` 顯示是剛剛、而且 `ps` 看得到有人的 vim 在跑** →
> **★★★ 按 `O` 唯讀開啟，絕對不要按 `E`** ——
> 兩個人同時編輯同一個檔案，後存的會**整個蓋掉**先存的。
> 命令列直接救援：`sudo vim -r /etc/nginx/nginx.conf`；
> `sudo vim -r`（不帶檔名）列出所有 swap 檔。
>
> **Q8.** 因為 **swap 檔含有檔案的完整內容**，
> 而且它預設**留在被編輯檔案的同一個目錄** ——
> 如果那是網站根目錄，`.env.swp` 就會被 web server 當成靜態檔案吐出來。
> **真實的攻擊**：`curl https://example.com/.env.swp` → **資料庫密碼、API 金鑰全部外洩**。
> `.bak`、`.orig`、`filename~`、`.save` 都是同類問題。
> **三個防護**：
> ①**★★★ web server 擋掉**：
> ```nginx
> location ~ /\.  { deny all; return 404; }
> location ~ \.(swp|swo|bak|orig|save|old)$ { return 404; }
> location ~ ~$   { return 404; }
> ```
> ②**編輯敏感檔案時不產生 swap**：`vim -n /path/to/.env`；
> ③**★★ swap 集中管理**：`set directory=~/.vim/swap//`
> （結尾兩個斜線 = 用完整路徑當檔名，避免同名衝突），
> 這樣就不會留在網站目錄裡。
>
> **Q9.** **`vim-tiny`（Ubuntu 最小安裝的預設）是功能被閹割的版本** ——
> 指令叫做 `vim` 但**沒有語法高亮、沒有 Visual 模式、沒有多層 undo**，
> 而且**方向鍵在 Insert 模式會印出 `A` `B` `C` `D`**
> （因為沒開 `nocompatible`，方向鍵的跳脫序列被拆成 `Esc` + 字母）。
> **確認方式**：
> ```bash
> readlink -f "$(which vi)"
> # /usr/bin/vim.basic   ★ 完整版
> # /usr/bin/vim.tiny    ★★ 閹割版
> vim --version | head -1
> ```
> **解法**：`sudo apt install vim`（RHEL 是 **`dnf install vim-enhanced`**，
> 套件名不一樣，最小安裝只有 `vim-minimal` 也就是 `vi`）。
> 臨時的權宜之計：**建一個 `~/.vimrc`**（哪怕是空的），
> 只要這個檔案存在 vim 就會自動進入 `nocompatible` 模式。
>
> **Q10.** 因為 **modeline 會讓 vim 執行「檔案內容裡指定的設定」**，
> 這等於**讓你打開的檔案控制你的編輯器行為**。
> modeline 長這樣（通常在檔案的前幾行或後幾行）：
> ```
> # vim: set ts=4 sw=4 et:
> ```
> **問題在於歷史上有多個 CVE** ——
> 精心構造的 modeline 可以繞過限制**執行任意指令**
> （例如 CVE-2019-12735 就是透過 modeline 的 `:source` 達成 RCE）。
> **只要你 `vim` 打開一個從網路下載、或別人給的檔案，就可能中招**，
> 對維運人員來說是很實際的風險（常常要看別人給的 log、設定檔）。
> **防護**：`~/.vimrc` 加上 **`set nomodeline`**。
> 同類的還有 `set noexrc`（不載入目前目錄的 `.vimrc`，預設就是關的），
> 以及不要隨便安裝來路不明的 vim 外掛（vimscript 可以執行任意指令）。

---

## 延伸閱讀

- [[03-Vim-進階與設定]] — `.vimrc`、外掛、多視窗、巨集
- [[01-Nano-快速上手]] — 比較好上手的選擇
- [[12-文字處理三劍客]] — 批次修改用 sed 更適合
- [[03-終端機與Shell入門]] — 終端機基礎
- [[25-開機流程與GRUB救援]] — 救援模式常常只有 `vi`
- [[04-遠端編輯與VSCode-Remote]] — 用 GUI 編輯遠端檔案
