---
title: "JavaScript 非同步與 API"
desc: "Promise、async/await、fetch 錯誤處理，以及 CORS 是伺服器端的問題"
aliases: [Promise, async, await, fetch, CORS]
tags: [群組/系統及工具開發, 開發/前端, 主題/非同步]
category: 前端基礎
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[03-JavaScript基礎]]"]
updated: 2026-08-28
---

# JavaScript 非同步與 API

> [!abstract] 這篇你會學到
> - 為什麼「非同步」是必要的，以及事件迴圈怎麼運作
> - 用 `async` / `await` 寫出看起來像同步的非同步程式
> - ★★★★ `fetch` **不會**因為 404/500 而 reject —— 這是最多人踩的坑
> - 逾時、重試、取消請求的正確寫法
> - ★★★★ **CORS 是伺服器端的設定問題**，前端怎麼改都沒用（附 Nginx 設定）

## 前置知識

- [[03-JavaScript基礎]] —— 函式、箭頭函式、物件
- [[07-瀏覽器開發者工具]] —— 這篇的排錯全靠 Network 分頁
- 知道 HTTP 狀態碼的大致分類（2xx 成功 / 3xx 轉址 / 4xx 用戶端錯 / 5xx 伺服器錯）

---

## 觀念說明

### 為什麼需要非同步

JavaScript 在瀏覽器裡**只有一條執行緒**。如果向 API 要資料時整條執行緒停住等回應，
畫面會完全凍結 —— 按鈕點不動、捲軸拉不動。所以凡是「要等」的事情
（網路請求、讀檔、計時器）都設計成非同步：**先登記，等好了再回頭處理**。

```
同步（會凍結）                    非同步（不會凍結）
發出請求                          發出請求 ────┐
  ⏳ 等 800ms（畫面死掉）            繼續處理其他事  │
收到回應                          （畫面能動）    │
繼續                              收到回應 ←──────┘
                                  處理回應
```

### 事件迴圈：兩個佇列的優先權 ★★★

```javascript
console.log('1');
setTimeout(() => console.log('2'), 0);      // 巨集任務（macrotask）
Promise.resolve().then(() => console.log('3'));  // 微任務（microtask）
console.log('4');
```

輸出順序是 **`1 4 3 2`**，不是 `1 2 3 4`。規則：

```
同步程式碼跑完
   ↓
清空「微任務」佇列（Promise 的 .then / await 之後）  ← ★★★ 優先
   ↓
執行一個「巨集任務」（setTimeout / 事件回呼）
   ↓
再清空微任務…（如此循環）
```

★★★ `setTimeout(fn, 0)` **不是「立刻執行」**，是「等同步程式碼與所有微任務都跑完再執行」。
知道這件事，就能理解為什麼有時候 `console.log` 印出來的值跟你在 Elements 看到的畫面對不上。

### Promise 的三個狀態

```
pending（等待中）
   ├─→ fulfilled（成功）→ .then(值)      / await 回傳值
   └─→ rejected（失敗） → .catch(錯誤)   / await 丟出例外
```

★★★★ **狀態一旦改變就不可逆**，一個 Promise 只會成功或失敗一次。

---

## 基礎操作

### `async` / `await` 是預設寫法

```javascript
// ✗ 舊寫法：巢狀 .then，難讀難除錯
function 取得主機() {
  return fetch('/api/hosts')
    .then(res => res.json())
    .then(data => {
      console.log(data);
      return data;
    })
    .catch(err => console.error(err));
}

// ✓ 現在的寫法：async/await
async function 取得主機() {
  try {
    const res  = await fetch('/api/hosts');
    const data = await res.json();
    console.log(data);
    return data;
  } catch (err) {
    console.error('取得主機清單失敗：', err);
    throw err;                 // ★★★ 不要吞掉錯誤，讓呼叫端也知道
  }
}
```

三條規則：

| 規則 | 說明 |
| --- | --- |
| ★★★★ `await` 只能寫在 `async` 函式裡 | 例外：`type="module"` 的頂層可以直接用 |
| ★★★★ `async` 函式**一定回傳 Promise** | 就算 `return 5`，拿到的也是 `Promise<5>` |
| ★★★ 錯誤用 `try/catch` 接 | 沒接就會變成 `Uncaught (in promise)` |

```javascript
// ★★★ 最常見的初學錯誤：忘記 await
const 資料 = 取得主機();
console.log(資料);          // Promise { <pending> }  ← 不是資料！
console.log(資料.length);   // undefined

const 資料2 = await 取得主機();   // ✓
```

### fetch 的致命細節 ★★★★★

```javascript
const res = await fetch('/api/hosts');
const data = await res.json();     // ★★★★★ 這樣寫是錯的
```

> [!danger] fetch 不會因為 404 或 500 而 reject
> `fetch` 只有在**網路層失敗**時才 reject（DNS 查不到、連線被拒、CORS 被擋、請求被中止）。
> 伺服器回 404、500、502 都算「請求成功送達並收到回應」，`fetch` 會正常 resolve。
> 於是程式繼續往下跑 `res.json()`，去解析那個 HTML 錯誤頁，得到：
> `SyntaxError: Unexpected token '<', "<!DOCTYPE"... is not valid JSON`
> —— **這個錯誤訊息的真正原因，往往是上游 502，跟 JSON 一點關係都沒有。**

**正確寫法：一律先檢查 `res.ok`**

```javascript
async function 取得JSON(網址, 選項 = {}) {
  const res = await fetch(網址, 選項);

  if (!res.ok) {                                  // ★★★★ 這行是關鍵
    // 盡量把伺服器的錯誤訊息帶出來，方便排錯
    const 內文 = await res.text().catch(() => '');
    throw new Error(`HTTP ${res.status} ${res.statusText} — ${內文.slice(0, 200)}`);
  }

  // ★★★ 有些端點成功時回 204 No Content，沒有 body
  if (res.status === 204) return null;

  // ★★★ 再確認一次 Content-Type，擋掉「200 但回 HTML」的情況
  const 型別 = res.headers.get('content-type') ?? '';
  if (!型別.includes('application/json')) {
    throw new Error(`預期 JSON，實際收到 ${型別}`);
  }

  return res.json();
}
```

### 送出資料

```javascript
// POST JSON
await 取得JSON('/api/hosts', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },   // ★★★ 少了這行，後端可能收不到
  body: JSON.stringify({ 名稱: 'web03', ip: '10.0.1.13' }),
});

// 表單（含檔案上傳）
const fd = new FormData(document.querySelector('#f'));
await fetch('/api/upload', { method: 'POST', body: fd });
// ★★★★ 用 FormData 時「不要」自己設 Content-Type，
//        瀏覽器要自動加上 multipart 的 boundary，手動設會壞掉

// 查詢字串（★★★ 用 URLSearchParams，不要自己接字串）
const qs = new URLSearchParams({ q: 'web 01', status: 'up' });
await fetch(`/api/hosts?${qs}`);     // /api/hosts?q=web+01&status=up
```

### 帶 Cookie

```javascript
// 同源請求預設會帶 cookie；跨來源必須明講
await fetch('https://api.example.tw/me', {
  credentials: 'include',      // ★★★ 跨來源要帶 cookie 時必加
});
```

★★★★ 搭配這個時，伺服器端的 CORS 設定**不能用 `Access-Control-Allow-Origin: *`**，
必須回明確的來源，且要加 `Access-Control-Allow-Credentials: true`。詳見下方 CORS 段落。

---

## 進階應用

### 逾時：`AbortController` ★★★★

`fetch` **沒有內建逾時**。網路卡住時它會一直等下去，使用者看到轉圈圈轉到天荒地老。

```javascript
async function 有逾時的fetch(網址, 選項 = {}, 毫秒 = 8000) {
  const ctrl = new AbortController();
  const 計時 = setTimeout(() => ctrl.abort(), 毫秒);
  try {
    return await fetch(網址, { ...選項, signal: ctrl.signal });
  } catch (e) {
    if (e.name === 'AbortError') throw new Error(`逾時 ${毫秒}ms：${網址}`);
    throw e;
  } finally {
    clearTimeout(計時);          // ★★★ 一定要清，否則計時器堆積
  }
}
```

同一個 `AbortController` 也可以用來**取消上一次請求** —— 即時搜尋必備：

```javascript
let 前一次;
搜尋框.addEventListener('input', async (e) => {
  前一次?.abort();                       // ★★★ 取消還在飛的舊請求
  前一次 = new AbortController();
  try {
    const r = await fetch(`/api/search?q=${encodeURIComponent(e.target.value)}`,
                          { signal: 前一次.signal });
    繪製(await r.json());
  } catch (err) {
    if (err.name !== 'AbortError') console.error(err);   // 取消不算錯誤
  }
});
```

> [!warning] 不取消舊請求會發生什麼
> ★★★★ **競態條件（race condition）**：使用者輸入 `web`，三個請求依序送出
> （`w`、`we`、`web`），但 `we` 的回應比 `web` 晚到，畫面最後顯示的是 `we` 的結果。
> 這種 bug 在本機測試不會出現，一上線就冒出來。

### 並行 vs 串行 ★★★★

```javascript
// ✗ 串行：總共等 3 秒
const a = await fetch('/api/a');    // 1s
const b = await fetch('/api/b');    // 1s
const c = await fetch('/api/c');    // 1s

// ✓ 並行：總共等 1 秒
const [a, b, c] = await Promise.all([
  fetch('/api/a'), fetch('/api/b'), fetch('/api/c'),
]);
```

★★★ 只有在「後一個請求需要前一個的結果」時才該串行。

**四個 Promise 組合函式**：

| 函式 | 行為 | 何時用 |
| --- | --- | --- |
| `Promise.all` | 全部成功才成功，**一個失敗就整組失敗** | ★★★ 缺一不可的資料 |
| `Promise.allSettled` | 等全部結束，回報每個的成敗 | ★★★★ 儀表板：一台掛了其他照樣顯示 |
| `Promise.race` | 最先結束的（成功或失敗）勝出 | 逾時競賽 |
| `Promise.any` | 最先**成功**的勝出 | 多個鏡像站取最快 |

```javascript
// 儀表板情境：五台主機分開查，掛掉的顯示錯誤，其餘照常
const 結果 = await Promise.allSettled(主機.map(h => 取得JSON(`/api/host/${h}`)));
結果.forEach((r, i) => {
  if (r.status === 'fulfilled') 繪製(主機[i], r.value);
  else                          繪製錯誤(主機[i], r.reason.message);
});
```

### 重試與指數退避 ★★★

```javascript
const 睡 = (ms) => new Promise(r => setTimeout(r, ms));

async function 重試(fn, { 次數 = 3, 起始延遲 = 500 } = {}) {
  let 最後錯誤;
  for (let i = 0; i < 次數; i++) {
    try {
      return await fn();
    } catch (e) {
      最後錯誤 = e;
      // ★★★★ 只重試「可能會好」的錯誤，4xx 重試幾次都一樣
      const 碼 = Number(String(e.message).match(/HTTP (\d{3})/)?.[1]);
      if (碼 && 碼 >= 400 && 碼 < 500 && 碼 !== 429) throw e;
      if (i < 次數 - 1) {
        const 等 = 起始延遲 * 2 ** i;      // 500 → 1000 → 2000
        console.warn(`第 ${i + 1} 次失敗，${等}ms 後重試：${e.message}`);
        await 睡(等);
      }
    }
  }
  throw 最後錯誤;
}
```

> [!tip] 哪些該重試
> ★★★★ **可重試**：連線失敗、逾時、429（太多請求）、502/503/504（上游暫時不可用）
> **不可重試**：400（參數錯）、401/403（權限）、404（不存在）、422（驗證失敗）
> —— 這些重試一百次結果都一樣，只是徒增伺服器負擔。
> 另外 **POST 要特別小心**：重試可能造成重複建立資料，除非後端有做冪等（idempotency key）。

---

## 完整實戰範例

### 一支可重用的 API 客戶端 + 主機儀表板

延續 [[03-JavaScript基礎]] 的主機清單，這次改成真的向後端要資料。

**`/var/www/dashboard/js/api.js`**

```javascript
// ── API 客戶端：逾時、錯誤訊息、重試、JSON 檢查一次做好 ──────────
const 預設逾時 = 8000;

export class ApiError extends Error {
  constructor(狀態碼, 訊息, 內文) {
    super(訊息);
    this.name = 'ApiError';
    this.status = 狀態碼;      // ★★★ 讓呼叫端可以依狀態碼分流處理
    this.body = 內文;
  }
}

export async function api(路徑, { 逾時 = 預設逾時, ...選項 } = {}) {
  const ctrl = new AbortController();
  const 計時 = setTimeout(() => ctrl.abort(), 逾時);

  try {
    const res = await fetch(路徑, {
      credentials: 'same-origin',
      signal: ctrl.signal,
      ...選項,
      headers: {
        'Accept': 'application/json',
        ...(選項.body && !(選項.body instanceof FormData)
            ? { 'Content-Type': 'application/json' } : {}),
        ...選項.headers,
      },
    });

    const 型別 = res.headers.get('content-type') ?? '';
    const 內文 = 型別.includes('application/json')
      ? await res.json().catch(() => null)
      : await res.text();

    if (!res.ok) {
      // ★★★★ 把後端的錯誤訊息帶出來，不要只丟「請求失敗」
      const 訊息 = (內文 && 內文.message) || `HTTP ${res.status} ${res.statusText}`;
      throw new ApiError(res.status, 訊息, 內文);
    }
    return 內文;

  } catch (e) {
    if (e.name === 'AbortError') throw new ApiError(0, `逾時 ${逾時}ms：${路徑}`);
    if (e instanceof ApiError) throw e;
    // ★★★ TypeError: Failed to fetch → 網路不通或 CORS 被擋
    throw new ApiError(0, `連線失敗：${路徑}（檢查網路、URL、CORS）`, null);
  } finally {
    clearTimeout(計時);
  }
}

export const get  = (p, o)    => api(p, { ...o, method: 'GET' });
export const post = (p, d, o) => api(p, { ...o, method: 'POST', body: JSON.stringify(d) });
```

**`/var/www/dashboard/js/app.js`**

```javascript
import { get, ApiError } from './api.js';

const $ = (s) => document.querySelector(s);
const 主機群 = ['web01', 'web02', 'db01', 'db02', 'bak01'];

function 卡片(主機, 狀態, 內容) {
  const el = document.createElement('div');
  el.className = `card ${狀態}`;
  const h = document.createElement('h3');
  h.textContent = 主機;                        // ★★★★ textContent，不用 innerHTML
  const p = document.createElement('p');
  p.textContent = 內容;
  el.append(h, p);
  return el;
}

async function 更新() {
  $('#status').textContent = '查詢中…';
  const 容器 = $('#grid');
  容器.replaceChildren();

  // ★★★★ allSettled：一台掛了不影響其他台顯示
  const 結果 = await Promise.allSettled(
    主機群.map(h => get(`/api/host/${encodeURIComponent(h)}`, { 逾時: 5000 }))
  );

  let 異常 = 0;
  結果.forEach((r, i) => {
    const 主機 = 主機群[i];
    if (r.status === 'fulfilled') {
      const d = r.value;
      容器.append(卡片(主機, d.load > 4 ? 'warn' : 'ok',
                       `負載 ${d.load.toFixed(2)}　記憶體 ${d.mem_pct}%　執行 ${d.uptime}`));
    } else {
      異常++;
      const e = r.reason;
      // ★★★ 依狀態碼給出不同的提示，而不是一律「失敗」
      const 說明 =
        e.status === 0   ? '連不上（網路或服務停止）' :
        e.status === 401 ? '未登入或憑證過期' :
        e.status === 404 ? '此主機未在監控清單中' :
        e.status >= 500  ? `監控服務異常（${e.status}）` :
                           e.message;
      容器.append(卡片(主機, 'down', 說明));
      console.error(`[${主機}]`, e);
    }
  });

  const 時間 = new Date().toLocaleTimeString('zh-TW');
  $('#status').textContent = `更新於 ${時間}　異常 ${異常} / ${主機群.length} 台`;
}

// 首次載入 + 每 30 秒自動更新
更新();
let 計時器 = setInterval(更新, 30_000);

// ★★★ 分頁切到背景時暫停輪詢，回來時立刻更新一次
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    clearInterval(計時器);
  } else {
    更新();
    計時器 = setInterval(更新, 30_000);
  }
});

$('#refresh').addEventListener('click', 更新);
```

**`index.html` 掛載**

```html
<script type="module" src="/js/app.js"></script>
```

★★★ 用了 `type="module"`，所以**必須透過 HTTP 提供**，不能雙擊開檔。

**驗證步驟**

```bash
# 1. 語法檢查（不執行）
node --check js/api.js && node --check js/app.js
# 預期：沒有輸出即為通過

# 2. 起本機伺服器
python3 -m http.server 8080 --directory /var/www/dashboard

# 3. 確認 API 本身正常（先排除前端問題）
curl -s -o /dev/null -w '%{http_code} %{content_type} %{time_total}s\n' \
     http://localhost/api/host/web01
# 預期：200 application/json 0.043s
```

| 檢查項 | 預期 | 不符時看哪裡 |
| --- | --- | --- |
| 五張卡片都出現 | ✓ | Network 分頁，看哪個請求紅色 |
| 停掉 web02 的 agent | 該卡片顯示「連不上」，**其他四張正常** | 若全部消失 → 誤用了 `Promise.all` |
| 切到別的分頁 3 分鐘 | Network 沒有新請求 | `visibilitychange` 沒生效 |
| Console | ★★★★ 除了刻意的 `console.error` 外沒有紅字 | 逐條對照下方錯誤表 |

---

## CORS：這是伺服器端的問題 ★★★★★

```
Access to fetch at 'https://api.example.tw/hosts' from origin
'https://dash.example.tw' has been blocked by CORS policy:
No 'Access-Control-Allow-Origin' header is present on the requested resource.
```

> [!danger] 先講結論
> ★★★★★ **CORS 不可能靠改前端程式碼解決。**
> 網路上教你「加 `mode: 'no-cors'`」的答案是錯的 —— 那會讓你拿到一個
> 讀不到內容的 opaque 回應，看起來沒報錯但什麼都拿不到，更難查。
> 唯一的解法是**伺服器端回應正確的標頭**，或**改成同源請求**。

### 什麼算「跨來源」

來源 = **協定 + 網域 + 埠**，三者任一不同就是跨來源：

| 從 | 到 | 跨來源？ |
| --- | --- | --- |
| `https://a.tw` | `https://a.tw/api` | 否 |
| `https://a.tw` | `http://a.tw` | ★ 是（協定不同） |
| `https://a.tw` | `https://api.a.tw` | ★ 是（子網域也算） |
| `https://a.tw` | `https://a.tw:8080` | ★ 是（埠不同） |

### 預檢請求（preflight）

★★★ 「簡單請求」直接送出；不簡單的會先送一個 `OPTIONS` 問伺服器同不同意。
以下任一條件成立就會觸發預檢：

- 方法不是 GET / HEAD / POST
- `Content-Type` 是 `application/json`（★★★★ 這條最常中）
- 有自訂標頭（如 `Authorization`、`X-Requested-With`）

在 Network 分頁會看到**兩個請求**：一個 `OPTIONS`、一個真正的請求。
如果 `OPTIONS` 就 404 或 405，代表伺服器沒處理預檢。

### 三種解法

**解法一：同源代理（★★★★ 最推薦）**

讓前端與 API 走同一個網域，由 Nginx 轉發 —— 沒有跨來源，就沒有 CORS。

```nginx
server {
    listen 443 ssl;
    server_name dash.example.tw;

    root /var/www/dashboard;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # ★★★★ 前端呼叫 /api/… 就等於同源，完全不需要 CORS 設定
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

這個做法還順手解決了 cookie 的 SameSite 問題與 token 存放問題，
機關內部系統幾乎都該這樣做。

**解法二：伺服器端開 CORS**

```nginx
location /api/ {
    # ★★★★ 正式環境不要用 *，要指定明確來源
    set $cors_origin "";
    if ($http_origin ~* ^https://(dash|admin)\.example\.tw$) {
        set $cors_origin $http_origin;
    }

    add_header Access-Control-Allow-Origin      $cors_origin      always;
    add_header Access-Control-Allow-Credentials true              always;
    add_header Vary                             Origin            always;   # ★★★ 別漏，否則快取會串錯來源

    # 預檢：直接回 204，不要往後端送
    if ($request_method = OPTIONS) {
        add_header Access-Control-Allow-Methods "GET, POST, PUT, PATCH, DELETE, OPTIONS" always;
        add_header Access-Control-Allow-Headers "Authorization, Content-Type, X-Requested-With" always;
        add_header Access-Control-Max-Age       86400 always;
        add_header Content-Length               0;
        return 204;
    }

    proxy_pass http://127.0.0.1:8000/;
}
```

> [!warning] 三個常犯的錯
> 1. ★★★★ `Access-Control-Allow-Origin: *` 搭配 `credentials: 'include'` —— 瀏覽器會直接拒絕，
>    必須回明確來源
> 2. ★★★ 漏了 `always` —— 預設 `add_header` 只在 2xx/3xx 加，
>    錯誤回應（如 500）就沒有 CORS 標頭，你會看到「CORS 錯誤」而看不到真正的 500
> 3. ★★★ 漏了 `Vary: Origin` —— 有 CDN 或反向代理快取時，A 來源的回應會被餵給 B 來源

**解法三：本機開發用 Vite 代理**

```javascript
// vite.config.js
export default {
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
};
```

★★★ 這**只在開發伺服器有效**，`npm run build` 之後的產物沒有代理。
正式環境還是要用解法一或二。詳見 [[06-前端建置工具與套件管理]]。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `Unexpected token '<', "<!DOCTYPE"...` | 伺服器回 HTML（404/502/登入頁），程式當 JSON 解析 | 加 `if (!res.ok) throw` 與 Content-Type 檢查；到 Network 看實際回應 |
| ★★★★★ `blocked by CORS policy` | 伺服器沒回 `Access-Control-Allow-Origin` | 伺服器端處理，見上節。**不要**用 `mode: 'no-cors'` |
| ★★★★ `TypeError: Failed to fetch` | 網路不通 / URL 錯 / 被 CORS 預檢擋 / 憑證無效 | Network 看請求有沒有真的送出；`curl -v` 從主機端測一次 |
| ★★★★ 拿到 `Promise { <pending> }` | 忘記 `await` | 加 `await`，且外層函式要是 `async` |
| ★★★★ `Uncaught (in promise) ...` | 非同步錯誤沒有 `.catch` / `try-catch` | 每個 `await` 鏈都要有錯誤出口 |
| ★★★★ 即時搜尋顯示舊的結果 | 競態條件，慢的回應後到 | 用 `AbortController` 取消前一次請求 |
| ★★★ 上傳檔案後端收不到 | 用 FormData 卻自己設了 `Content-Type` | 刪掉那行，讓瀏覽器自動加 boundary |
| ★★★ 跨網域請求沒帶 cookie | 沒設 `credentials: 'include'`，或伺服器缺 `Allow-Credentials` | 兩邊都要設；`SameSite=None; Secure` |
| ★★★ 401 之後整頁壞掉 | token 過期沒處理 | 攔截 401 → 導向登入頁或刷新 token |
| ★★ 頁面在背景時仍狂送請求 | 沒處理 `visibilitychange` | 見實戰範例的輪詢暫停 |
| ★★ `await` 寫在迴圈裡很慢 | 串行執行 | 改 `Promise.all` / `allSettled` |

### 排查步驟

**【1】先確認 API 本身是好的（把前端排除在外）**

```bash
curl -s -o /dev/null -w 'code=%{http_code} type=%{content_type} time=%{time_total}s\n' \
     -H 'Accept: application/json' \
     https://api.example.tw/hosts
# 預期：code=200 type=application/json time=0.05s
```

★★★★ 如果這裡就不對，前端怎麼改都沒用 —— 問題在後端或 Nginx。

**【2】看 Network 分頁的三件事**

```
1. 請求有沒有出現？    沒有 → JS 根本沒執行到（看 Console 有沒有更早的紅字）
2. 狀態碼是多少？      0 或 (failed) → 網路層問題（CORS、DNS、憑證）
3. Response 分頁長怎樣？ 是 HTML 就代表回了錯誤頁，不是 JSON
```

**【3】CORS 專用：確認是不是預檢掛掉**

Network 分頁把 Method 欄打開，找有沒有 `OPTIONS` 請求：

```bash
# 從命令列模擬預檢
curl -i -X OPTIONS https://api.example.tw/hosts \
     -H 'Origin: https://dash.example.tw' \
     -H 'Access-Control-Request-Method: POST' \
     -H 'Access-Control-Request-Headers: content-type'
```

預期回應必須包含：

```
HTTP/2 204
access-control-allow-origin: https://dash.example.tw
access-control-allow-methods: GET, POST, PUT, PATCH, DELETE, OPTIONS
access-control-allow-headers: Authorization, Content-Type, X-Requested-With
```

★★★ 少任何一行，對應的請求就會被擋。

**【4】確認錯誤回應也有 CORS 標頭**

```bash
curl -i https://api.example.tw/不存在 -H 'Origin: https://dash.example.tw' | head -12
```

★★★★ 如果 404 回應**沒有** `access-control-allow-origin`，
瀏覽器會報 CORS 錯誤，你就永遠看不到真正的 404。Nginx 要加 `always`。

**【5】用 Console 直接測一發**

```javascript
// 貼進 Console，繞過整個前端程式碼
const r = await fetch('/api/hosts');
console.log(r.status, r.headers.get('content-type'));
console.log(await r.text());
```

---

## 安全性注意事項

> [!danger] 非同步請求特有的四個風險
> 1. ★★★★★ **不要把 API 金鑰放前端**（見 [[03-JavaScript基礎]]）——
>    Network 分頁的請求標頭會原封不動顯示出來
> 2. ★★★★ **不要用 `innerHTML` 塞 API 回來的資料**，即使來源是自家後端
>    —— 資料庫裡的內容可能是使用者填的
> 3. ★★★★ **URL 參數一律 `encodeURIComponent()`**，否則使用者輸入 `&admin=1` 就能竄改查詢
> 4. ★★★ **錯誤訊息不要原樣顯示給使用者** —— 後端的例外訊息可能洩漏路徑、SQL、版本

```javascript
// ✗ 危險：使用者輸入的 & # ? 會破壞 URL 結構
fetch(`/api/search?q=${輸入}`);

// ✓ 正確
fetch(`/api/search?q=${encodeURIComponent(輸入)}`);
// 或用 URLSearchParams（會自動編碼）
fetch(`/api/search?${new URLSearchParams({ q: 輸入 })}`);
```

**錯誤訊息的兩層處理 ★★★**

```javascript
catch (e) {
  console.error(e);                              // 完整訊息 → Console（給工程師）
  顯示提示('查詢失敗，請稍後再試（代碼 ' + e.status + '）');   // 簡化訊息 → 畫面（給使用者）
}
```

**其他**

- ★★★ **`Content-Security-Policy` 的 `connect-src`** 可以限制 JS 只能連指定網域，
  是防止資料被外送的有效手段
- ★★★ **正式環境關掉除錯輸出**：`console.log(回應)` 可能把整包個資印在 Console
- ★★ **輪詢間隔別太短** —— 5 秒一次、100 個使用者就是每秒 20 個請求打在你的 API 上

---

## 速查表

### fetch

| 寫法 | 說明 | 星級 |
| --- | --- | --- |
| `if (!res.ok) throw ...` | ★★★★ 每次 fetch 之後必寫 | ★★★★★ |
| `res.status` / `res.statusText` | 狀態碼 | ★★★★ |
| `res.headers.get('content-type')` | 確認真的是 JSON | ★★★ |
| `res.json()` / `res.text()` / `res.blob()` | 解析回應（**只能讀一次**） | ★★★ |
| `credentials: 'include'` | 跨來源帶 cookie | ★★★ |
| `signal: ctrl.signal` | 配合 AbortController 做逾時／取消 | ★★★★ |
| `new URLSearchParams(obj)` | 安全組查詢字串 | ★★★ |
| `encodeURIComponent(x)` | 編碼單一參數值 | ★★★★ |

### Promise 組合

| 函式 | 一個失敗時 | 典型用途 |
| --- | --- | --- |
| `Promise.all` | ★★★ 整組失敗 | 缺一不可 |
| `Promise.allSettled` | 其餘照常回報 | ★★★★ 儀表板 |
| `Promise.race` | 最先結束者勝 | 逾時競賽 |
| `Promise.any` | 最先成功者勝 | 多鏡像取最快 |

### 排錯指令

| 指令 | 用途 |
| --- | --- |
| `curl -s -o /dev/null -w '%{http_code} %{content_type} %{time_total}\n' URL` | 快速確認 API 狀態 |
| `curl -i -X OPTIONS URL -H 'Origin: …' -H 'Access-Control-Request-Method: POST'` | ★★★★ 模擬 CORS 預檢 |
| `curl -i URL -H 'Origin: …'` | 看回應有沒有 CORS 標頭 |
| `node --check app.js` | 語法檢查 |
| F12 → Network → Fetch/XHR | 只看 API 請求 |
| Network → 右鍵 → Copy as cURL | ★★★★ 把瀏覽器的請求原封不動搬到終端機重現 |

---

## 練習題

> [!question]- 練習 1：把「靜默失敗」找出來
> 以下程式在 API 回 500 時，畫面會顯示什麼？為什麼使用者只看到空白？
> ```javascript
> async function 載入() {
>   const res = await fetch('/api/hosts');
>   const data = await res.json();
>   繪製(data);
> }
> 載入();
> ```
>
> **參考解答**：500 時 `res.ok` 是 false 但 `fetch` 不 reject，
> 程式繼續執行 `res.json()`，解析 HTML 錯誤頁失敗，丟出 `SyntaxError`。
> 因為沒有 `try/catch`，錯誤變成 `Uncaught (in promise)` 停在 Console，
> `繪製()` 從未被呼叫 → 畫面空白。使用者以為「沒資料」，實際上是伺服器掛了。
> 修法：加 `if (!res.ok) throw new Error(...)` 與 `try/catch`，並在 catch 裡顯示錯誤提示。

> [!question]- 練習 2：把串行改成並行並量測
> 把三個依序的 `await fetch` 改成 `Promise.all`，用 `performance.now()` 量前後差異。
>
> **提示**：
> ```javascript
> const t = performance.now();
> // …
> console.log(`耗時 ${(performance.now() - t).toFixed(0)}ms`);
> ```
> 在 Network 分頁把節流設成 "Slow 4G" 更容易看出差別。

> [!question]- 練習 3：設計一個 CORS 排查流程
> 同事說「前端接不到 API，是 CORS 問題」。寫出你會依序做的五個檢查動作。
>
> **參考解答**：
> ① `curl` 直打 API 確認它本身正常（排除後端掛掉被誤判成 CORS）；
> ② Network 分頁確認請求有沒有送出、狀態碼是不是 0；
> ③ 看有沒有 `OPTIONS` 預檢請求、它回什麼；
> ④ `curl -i -X OPTIONS` 檢查三個 `Access-Control-Allow-*` 標頭是否齊全；
> ⑤ 檢查錯誤回應（如 404/500）有沒有 CORS 標頭（Nginx 的 `always`）——
> 這一步最常被漏，會讓真正的錯誤被 CORS 訊息蓋掉。
> 最後評估是否改用同源代理，一次解決所有問題。

---

## 小測驗

Q1. `console.log('1'); setTimeout(()=>console.log('2'),0); Promise.resolve().then(()=>console.log('3')); console.log('4');` 的輸出順序是什麼？

Q2. API 回 500 時，`await fetch(url)` 會丟出例外嗎？

Q3. 承上，如果不檢查 `res.ok` 就呼叫 `res.json()`，你最可能在 Console 看到哪一句錯誤？

Q4. `const a = 取得資料(); console.log(a.length);` 印出 `undefined`，最可能的原因是什麼？

Q5. 儀表板要查五台主機，其中一台已關機。該用 `Promise.all` 還是 `Promise.allSettled`？為什麼？

Q6. `fetch` 的逾時要怎麼做？

Q7. 即時搜尋框顯示的結果總是慢一拍、對不上目前輸入，成因與解法是什麼？

Q8. 前端出現 `blocked by CORS policy`，能不能靠改前端程式碼解決？

Q9. Nginx 的 CORS 設定裡，`add_header ... always` 的 `always` 漏掉會有什麼後果？

Q10. 用 `FormData` 上傳檔案時，為什麼不能自己設 `Content-Type: multipart/form-data`？

> [!question]- 測驗答案
> **Q1.** `1 4 3 2`。
> ★★★ 執行順序是：先跑完所有**同步**程式碼（印 1、印 4），
> 接著清空**微任務**佇列（Promise 的 `.then` → 印 3），
> 最後才執行**巨集任務**（`setTimeout` → 印 2）。
> 關鍵觀念：`setTimeout(fn, 0)` 不是「立刻執行」，而是「排到巨集任務佇列最後」，
> 所有微任務都會比它先跑。見〈事件迴圈〉。
>
> **Q2.** ★★★★★ **不會。** 這是 `fetch` 最違反直覺、也最多人踩的設計。
> `fetch` 只在**網路層**失敗時 reject：DNS 查不到、連線被拒、CORS 被擋、請求被 abort、憑證無效。
> 伺服器回 404、500、502 都代表「請求成功送達且收到回應」，所以 Promise 是 **fulfilled**。
> 因此每一次 `fetch` 之後都必須自己寫 `if (!res.ok) throw ...`。
> （這也是 axios 等函式庫比較好用的原因之一 —— 它們預設會把 4xx/5xx 當成錯誤。）
>
> **Q3.** `SyntaxError: Unexpected token '<', "<!DOCTYPE"... is not valid JSON`。
> ★★★★ 因為 500 時伺服器回的是 HTML 錯誤頁，`res.json()` 從第一個字元 `<` 就解析失敗。
> **這個錯誤訊息極具誤導性** —— 它讓人以為是 JSON 格式問題，
> 實際原因是上游 502／登入頁／404。看到這句話的正確反應是：
> 到 Network 分頁點開那個請求的 Response 看它到底回了什麼。
>
> **Q4.** ★★★★ **忘記 `await`**。`async` 函式**一定回傳 Promise**，
> 所以 `a` 是一個 `Promise { <pending> }` 物件，Promise 沒有 `.length` 屬性，
> 讀到就是 `undefined`（而且不會報錯，所以特別難查）。
> 修法：`const a = await 取得資料();`，並確保外層函式標了 `async`
> （或該檔案是 `type="module"` 可用頂層 await）。
> 快速判斷法：`console.log(a)` 看到 `Promise { <pending> }` 就是漏了 await。
>
> **Q5.** 用 **`Promise.allSettled`**。
> ★★★★ `Promise.all` 是「全有全無」—— 只要有一個 reject，整組立刻失敗，
> 那台關機的主機會害其餘四台的資料也顯示不出來，這在儀表板情境完全不能接受。
> `allSettled` 會等全部結束，回傳每個項目的 `{status, value|reason}`，
> 讓你把成功的畫出來、失敗的顯示錯誤原因。
> 反過來說，「缺一不可」的情境（例如同時要拿使用者資料與權限才能渲染畫面）才適合 `all`。
>
> **Q6.** `fetch` **沒有內建逾時**，要用 `AbortController`：
> ```javascript
> const ctrl = new AbortController();
> const t = setTimeout(() => ctrl.abort(), 8000);
> try   { return await fetch(url, { signal: ctrl.signal }); }
> catch (e) { if (e.name === 'AbortError') throw new Error('逾時'); throw e; }
> finally { clearTimeout(t); }
> ```
> ★★★ 兩個容易漏的細節：`finally` 裡一定要 `clearTimeout`（否則計時器累積），
> 以及要用 `e.name === 'AbortError'` 區分「逾時」與「真的網路錯誤」，
> 否則錯誤訊息會誤導排查方向。
>
> **Q7.** 成因是**競態條件**：每打一個字就送一個請求，
> 而回應到達的順序不保證與送出順序相同 —— 較早送出的 `we` 可能比 `web` 晚回來，
> 於是畫面最後被舊結果覆蓋。
> ★★★★ 解法是在送出新請求前先 `abort()` 掉前一個：
> ```javascript
> 前一次?.abort();
> 前一次 = new AbortController();
> ```
> 並在 catch 裡忽略 `AbortError`（那是預期行為，不是錯誤）。
> 通常再加上 debounce（停止輸入 300ms 才送）會更省資源。
> 這種 bug 在本機低延遲環境幾乎不會重現，一定要用 Network 的節流功能測。
>
> **Q8.** ★★★★★ **不能。** CORS 是**瀏覽器**依據**伺服器回應標頭**執行的安全機制，
> 前端沒有任何方式可以繞過（能繞過就失去意義了）。
> 網路上常見的 `mode: 'no-cors'` 是**錯誤答案** —— 它會讓你拿到一個 opaque 回應：
> 狀態碼永遠是 0、body 讀不到，看起來「不報錯了」但什麼資料都拿不到，反而更難查。
> 正確做法只有兩個：**①（首選）改成同源** —— 用 Nginx 把 `/api/` 反向代理到後端，
> 前端呼叫相對路徑，根本不會跨來源；**②** 請後端／Nginx 回正確的
> `Access-Control-Allow-Origin` 等標頭。
>
> **Q9.** ★★★ Nginx 的 `add_header` 預設**只在回應碼是 2xx / 3xx（以及 204、304 等）時才加**。
> 漏掉 `always`，錯誤回應（400、401、404、500、502…）就不會帶 CORS 標頭，
> 瀏覽器因此把它報成 CORS 錯誤，**真正的狀態碼與錯誤訊息被完全遮蔽**。
> 症狀是：「明明後端有回 401，前端卻只看到 CORS 錯誤」。
> 所以 CORS 相關的 `add_header` 一律要補 `always`。
>
> **Q10.** ★★★★ 因為 `multipart/form-data` 的標頭必須附帶一段隨機的 **boundary** 字串
> （例如 `multipart/form-data; boundary=----WebKitFormBoundaryAbc123`），
> 用來分隔各個欄位與檔案內容。這段 boundary 是瀏覽器在組請求主體時**自己產生**的，
> 手動設定 `Content-Type` 會覆蓋掉瀏覽器要加的完整值、遺失 boundary，
> 後端解析器就找不到分隔符，結果是「收到請求但欄位全空」。
> 正確做法：用 FormData 時**完全不要碰 `Content-Type`**，交給瀏覽器。

---

## 延伸閱讀

- [[03-JavaScript基礎]] —— 函式、型別、DOM 與 XSS
- [[07-瀏覽器開發者工具]] —— Network 分頁的完整用法、Copy as cURL
- [[06-前端建置工具與套件管理]] —— Vite 開發代理與環境變數
- [[01-Vue-建置與Nginx靜態部署]] —— SPA 的 API 代理實作
- MDN 使用 Fetch：<https://developer.mozilla.org/zh-TW/docs/Web/API/Fetch_API/Using_Fetch>
- MDN CORS：<https://developer.mozilla.org/zh-TW/docs/Web/HTTP/CORS>
