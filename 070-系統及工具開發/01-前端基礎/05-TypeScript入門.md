---
title: "TypeScript 入門"
desc: "型別標註、介面、tsconfig 與在既有 JS 專案漸進導入"
aliases: [TS, tsconfig, 型別]
tags: [群組/系統及工具開發, 開發/前端, 主題/TypeScript]
category: 前端基礎
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[03-JavaScript基礎]]", "[[04-JavaScript非同步與API]]"]
updated: 2026-08-28
---

# TypeScript 入門

> [!abstract] 這篇你會學到
> - TypeScript 到底解決什麼問題（把 [[03-JavaScript基礎]] 的四個陷阱擋在上線前）
> - ★★★★ **型別只存在於編譯期，執行期完全不存在** —— 這是最重要的一句話
> - 常用型別標註、`interface` 與 `type` 的分工
> - `tsconfig.json` 裡真正該在意的六個選項
> - ★★★★ 在既有 JS 專案**漸進導入**的四階段路線，不必一次全改
> - 建置錯誤（`tsc` 紅字）的判讀與排查

## 前置知識

- [[03-JavaScript基礎]] —— TS 是 JS 的超集合，先會 JS 才有意義
- [[04-JavaScript非同步與API]] —— `Promise<T>` 的型別會用到
- [[06-前端建置工具與套件管理]] —— TS 幾乎都跟 Vite / npm 一起出現

---

## 觀念說明

### TypeScript 解決什麼問題

回顧 [[03-JavaScript基礎]] 提到的陷阱，在 JS 裡它們全都要等**執行到那一行**才爆炸：

```javascript
const 逾時 = 設定.timeout || 30;      // timeout 是 0 就被換掉 → 上線才發現
const 名稱 = 資料.host.name;          // host 是 null → 使用者按下去才 crash
主機清單.sort((a, b) => a.load - b.load);   // load 其實叫 cpu_load → NaN 排序
```

TypeScript 讓這些在**存檔的當下**就變成紅波浪線：

```typescript
interface Host { name: string; ip: string; cpu_load: number; status: 'up' | 'down'; }

const 主機: Host[] = await get('/api/hosts');
主機.sort((a, b) => a.load - b.load);
//                    ~~~~
// ✗ Property 'load' does not exist on type 'Host'. Did you mean 'cpu_load'?
```

> [!note] 一句話定義
> **TypeScript = JavaScript + 型別標註 + 一個編譯期檢查器。**
> 副檔名 `.ts`，編譯（transpile）後產生純 `.js` 給瀏覽器執行。
> 任何合法的 JS 都是合法的 TS —— 把 `.js` 改名成 `.ts` 就能開始用。

### ★★★★ 型別在執行期完全不存在

這是最多人誤解的一點：

```typescript
function 處理(n: number) {
  console.log(n * 2);
}
```

編譯後的 `.js` 是：

```javascript
function 處理(n) {
  console.log(n * 2);
}
```

★★★★★ **型別標註被整個刪掉了。** 這代表：

| 誤解 | 事實 |
| --- | --- |
| 「有 TS 就不用驗證 API 回傳的資料」 | ✗ 後端回什麼 TS 完全管不到，那只是你**宣稱**的型別 |
| 「有 TS 就不用檢查使用者輸入」 | ✗ 執行期沒有任何型別檢查 |
| 「TS 會讓程式變慢」 | ✗ 產出的 JS 跟手寫的一樣，零執行期成本 |
| 「TS 能防 XSS / SQL injection」 | ✗ 完全無關，資安該做的一樣都不能少 |

```typescript
// ★★★★ 這行是在「說謊」，TS 相信你，但後端可能回完全不同的東西
const 主機 = await res.json() as Host[];
```

`res.json()` 的型別是 `any`（TS 不知道後端會回什麼），
用 `as` 斷言只是叫編譯器閉嘴。**真正的防線是執行期驗證**（見下方進階段落）。

### 編譯期 vs 執行期的分工

```
撰寫時 ── tsc 檢查型別 ─→ 抓出：拼錯屬性名、型別不符、可能是 null、少傳參數
             ↓ 通過
編譯 ── 移除所有型別 ─→ 純 JS
             ↓
執行期 ── 你自己寫的驗證 ─→ 抓出：API 回傳格式變了、使用者亂填、外部資料有誤
```

★★★★ 兩道防線缺一不可。TS 管「我自己的程式碼有沒有寫錯」，
執行期驗證管「外面進來的資料對不對」。

---

## 基礎操作

### 環境準備

```bash
# 專案內安裝（★★★ 不要裝全域，版本要跟著專案走）
npm install --save-dev typescript

# 產生預設設定檔
npx tsc --init

# 只做型別檢查、不產出檔案（★★★★ CI 與 pre-commit 用這個）
npx tsc --noEmit

# 監看模式，存檔即檢查
npx tsc --noEmit --watch
```

驗證安裝：

```bash
npx tsc --version
# 預期輸出：Version 5.x.x
```

> [!tip] 實際專案通常不用 tsc 編譯
> Vite、esbuild、swc 會直接把 `.ts` 的型別**剝掉**再打包，速度快很多，
> 但它們**不做型別檢查**。所以正確組合是：
> **Vite 負責建置 + `tsc --noEmit` 負責檢查**，兩者分工。
> 這也是為什麼有時候「網頁跑得起來但 CI 卻紅了」。

### 基本型別

```typescript
// 基本型別（★★★ 通常不用寫，TS 會自動推論）
const 名稱: string = 'web01';
const 埠: number = 443;
const 啟用: boolean = true;
const 標籤: string[] = ['prod', 'web'];
const 座標: [number, number] = [25.03, 121.56];      // tuple：固定長度與型別

// ✓ 更好：讓 TS 自己推論
const 名稱2 = 'web01';        // 型別自動是 string
let 計數 = 0;                 // number

// 函式
function 檢查(碼: number): boolean {
  return 碼 >= 200 && 碼 < 300;
}

// 箭頭函式
const 格式化 = (主機: string, 上線: boolean): string =>
  `${上線 ? '✓' : '✗'} ${主機}`;

// 可選參數與預設值
function 連線(位址: string, 埠: number = 443, 逾時?: number) { /* … */ }
//                                            ^^^^^ 型別是 number | undefined

// 沒有回傳值
function 記錄(訊息: string): void { console.log(訊息); }
```

### 聯合型別與字面值型別 ★★★★

這是 TS 最實用的功能之一：

```typescript
type 狀態 = 'up' | 'down' | 'maintenance';       // 只能是這三個字串之一

let s: 狀態 = 'up';
s = 'UP';
// ✗ Type '"UP"' is not assignable to type '狀態'.   ← 大小寫打錯當場抓到

// 聯合型別
function 處理識別(id: string | number) {
  if (typeof id === 'string') {
    return id.toUpperCase();      // ★★★ 這個區塊裡 TS 知道 id 是 string
  }
  return id.toFixed(0);           // 這裡知道是 number
}
```

★★★★ 上面這種「用 `typeof` 把範圍縮小」叫**型別窄化（narrowing）**，
是寫 TS 的核心技巧，比記型別語法重要得多。

### `interface` 與 `type`

```typescript
// interface：描述物件的形狀（★★★ 描述資料結構優先用這個）
interface Host {
  name: string;
  ip: string;
  cpu_load: number;
  status: 'up' | 'down';
  tags?: string[];               // ★★★ 問號 = 可選，型別是 string[] | undefined
  readonly id: number;           // 唯讀，指派後不能改
}

// 繼承
interface DatabaseHost extends Host {
  engine: 'mysql' | 'postgresql';
  replica_of?: string;
}

// type：任何型別的別名，能力比 interface 廣
type 狀態 = 'up' | 'down';
type 識別 = string | number;
type 主機對照 = Record<string, Host>;        // { [key: string]: Host }
type 唯讀主機 = Readonly<Host>;
type 部分主機 = Partial<Host>;               // 所有欄位都變可選（★★★ 更新 API 常用）
type 名稱與IP = Pick<Host, 'name' | 'ip'>;   // 只取兩個欄位
type 無ID = Omit<Host, 'id'>;                // 排除某欄位（★★★ 新增 API 常用）
```

| 該用哪個 | 建議 |
| --- | --- |
| 描述 API 回傳的物件、元件 props | ★★★ `interface`（可被擴充、錯誤訊息較好讀） |
| 聯合型別、函式型別、工具型別 | ★★★ `type`（`interface` 做不到） |
| 團隊沒有共識時 | 挑一個寫進規範，一致性比選哪個重要 |

### 泛型：一次就好 ★★★

```typescript
// 沒有泛型：每種資料都要寫一支
async function 取得主機(): Promise<Host[]> { /* … */ }
async function 取得使用者(): Promise<User[]> { /* … */ }

// 有泛型：一支通吃
async function get<T>(路徑: string): Promise<T> {
  const res = await fetch(路徑);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

const 主機 = await get<Host[]>('/api/hosts');    // 主機 的型別是 Host[]
const 我 = await get<User>('/api/me');           // 我 的型別是 User
```

★★ `<T>` 讀作「呼叫的時候才決定的型別」。入門階段會**用**泛型就夠了，
不必急著自己設計複雜的泛型。

### 處理 `null` 與 `undefined` ★★★★

`strictNullChecks` 開啟後（`strict: true` 已包含），TS 會強迫你處理空值：

```typescript
const el = document.querySelector('#app');
// el 的型別是 Element | null

el.textContent = 'x';
// ✗ 'el' is possibly 'null'.

// ✓ 三種正確做法
if (el) el.textContent = 'x';                    // ★★★★ 最推薦：明確處理
el?.setAttribute('data-ok', '1');                // 可選鏈
const el2 = document.querySelector('#app')!;     // ★★ 非空斷言，「我保證不是 null」

// ★★★★ 特別注意 querySelector 的泛型版本
const 輸入 = document.querySelector<HTMLInputElement>('#q');
輸入?.value;                                     // 有 .value，一般的 Element 沒有
```

> [!warning] `!` 非空斷言是「請編譯器閉嘴」
> ★★★★ 它不做任何檢查，寫錯了就是執行期的 `Cannot read properties of null`。
> 只在你**確實能保證**（例如那個元素寫死在 HTML 裡）時使用，
> 而且最好加註解說明為什麼保證得了。團隊規範可以用 ESLint 的
> `@typescript-eslint/no-non-null-assertion` 直接禁用。

---

## 進階應用

### `any` / `unknown` / `never` ★★★★

```typescript
let a: any;         // ★★★★ 關掉所有檢查，等於放棄 TS。能不用就不用
let u: unknown;     // ★★★ 「還不知道是什麼」，用之前必須先窄化
let n: never;       // 不可能發生的型別

// any 的危害：錯誤會被放行，還會傳染
const 資料: any = await res.json();
資料.notExist.deep.crash;        // TS 一聲不吭，執行期直接爆炸

// unknown 是安全版本
const 資料2: unknown = await res.json();
資料2.name;
// ✗ '資料2' is of type 'unknown'.  ← 逼你先檢查
if (typeof 資料2 === 'object' && 資料2 !== null && 'name' in 資料2) {
  console.log(資料2.name);       // ✓ 窄化後才能用
}
```

★★★★ **原則**：想寫 `any` 時先問「能不能用 `unknown`」。
`any` 唯一合理的用途是**遷移期的臨時逃生口**，且要留 `// TODO` 註記。

`never` 的實用場景 —— **窮舉檢查**：

```typescript
type 狀態 = 'up' | 'down' | 'maintenance';

function 顏色(s: 狀態): string {
  switch (s) {
    case 'up':          return 'green';
    case 'down':        return 'red';
    case 'maintenance': return 'orange';
    default:
      const _窮舉: never = s;      // ★★★★ 日後新增狀態卻忘了處理，這行會編譯失敗
      throw new Error(`未處理的狀態：${s}`);
  }
}
```

### 執行期驗證：補上 TS 管不到的那一半 ★★★★

```typescript
// ✗ 危險：as 只是宣稱，後端改了欄位你完全不會知道
const 主機 = await res.json() as Host[];

// ✓ 手寫型別守衛（type guard）
function 是Host(x: unknown): x is Host {
  return (
    typeof x === 'object' && x !== null &&
    typeof (x as Host).name === 'string' &&
    typeof (x as Host).ip === 'string' &&
    typeof (x as Host).cpu_load === 'number' &&
    ['up', 'down'].includes((x as Host).status)
  );
}

const 原始: unknown = await res.json();
if (!Array.isArray(原始) || !原始.every(是Host)) {
  throw new Error('API 回傳格式不符預期（後端是不是改欄位了？）');
}
const 主機: Host[] = 原始;      // ★★★ 到這裡才是真的安全
```

★★★ 專案規模大了之後改用 **Zod** 之類的驗證函式庫，一份 schema 同時產生型別與執行期檢查：

```typescript
import { z } from 'zod';

const HostSchema = z.object({
  name: z.string(),
  ip: z.string().ip(),
  cpu_load: z.number().nonnegative(),
  status: z.enum(['up', 'down']),
});
type Host = z.infer<typeof HostSchema>;          // ★★★★ 型別自動產生，不會與驗證脫節

const 主機 = z.array(HostSchema).parse(await res.json());   // 不符就丟例外
```

> [!tip] 什麼時候值得引入驗證
> ★★★ 資料來源**不在你控制範圍內**時：外部 API、使用者上傳的檔案、
> `localStorage` 讀回來的舊資料、URL 參數。
> 自家後端且有共用型別定義時，可以先用 `as` 撐著。

### `tsconfig.json` 真正要在意的選項

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",

    "strict": true,

    "noUncheckedIndexedAccess": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,

    "skipLibCheck": true,
    "esModuleInterop": true,
    "forceConsistentCasingInFileNames": true,

    "noEmit": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"]
  },
  "include": ["src/**/*.ts", "src/**/*.d.ts"],
  "exclude": ["node_modules", "dist"]
}
```

| 選項 | 作用 | 星級 |
| --- | --- | --- |
| `strict: true` | 一次開啟所有嚴格檢查（含 `strictNullChecks`、`noImplicitAny`） | ★★★★★ 一定要開 |
| `noUncheckedIndexedAccess` | `arr[0]` 的型別變成 `T \| undefined` —— 逼你處理陣列越界 | ★★★★ 少數人開，但很值得 |
| `forceConsistentCasingInFileNames` | 大小寫不一致的 import 直接報錯 | ★★★★ **Windows 開發、Linux 部署必開**，否則本機好好的、上線 404 |
| `skipLibCheck` | 跳過 `node_modules` 的型別檢查 | ★★★ 開了省很多時間 |
| `noEmit` | 只檢查不產檔（建置交給 Vite） | ★★★ 搭配打包工具時 |
| `noUnusedLocals` / `noUnusedParameters` | 未使用的變數視為錯誤 | ★★ 清潔度，也可交給 ESLint |

> [!danger] `forceConsistentCasingInFileNames` 為什麼是 ★★★★
> Windows 與 macOS 的檔案系統預設**不分大小寫**，Linux **分**。
> 寫成 `import Host from './models/host'` 但檔名其實是 `Host.ts`，
> 開發機完全正常、部署到 Linux 伺服器就變成模組找不到。
> 這是「本機沒事、上線壞掉」的經典成因之一。

### 在既有 JS 專案漸進導入 ★★★★

**不要一次全部改成 `.ts`。** 四階段路線：

**階段一：只開檢查，不改副檔名**

```json
{
  "compilerOptions": {
    "allowJs": true,
    "checkJs": true,            // ★★★ 用 JSDoc 對 .js 做型別檢查
    "noEmit": true,
    "strict": false             // 先寬鬆，避免一開就幾千個錯
  },
  "include": ["src/**/*"]
}
```

```javascript
// app.js —— 不改副檔名，用 JSDoc 標型別
/**
 * @param {string} 主機
 * @param {number} [逾時]
 * @returns {Promise<{name: string, load: number}>}
 */
async function 查詢(主機, 逾時) { /* … */ }
```

★★★ 這一步不動任何建置流程，就能抓到一批拼錯與傳錯參數。

**階段二：新檔案一律用 `.ts`**

舊檔案不動，只要求新增的檔案是 TS。`allowJs: true` 讓兩者共存。

**階段三：由外而內轉換**

轉換順序：**工具函式 → 型別定義 → API 層 → 元件 → 進入點**。
先轉被最多地方引用的檔案，效益最大。

```bash
# 一次轉一個檔案，轉完立刻檢查
git mv src/utils/format.js src/utils/format.ts
npx tsc --noEmit
```

**階段四：逐步收緊**

```jsonc
// 一次開一個，把錯誤清完再開下一個
"noImplicitAny": true,      // 先開這個
"strictNullChecks": true,   // 再開這個（通常錯誤最多）
"strict": true              // 最後
```

> [!tip] 遷移期的兩個實用技巧
> ★★★ **`// @ts-expect-error`**：暫時忽略某一行的錯誤，
> 而且**當那行不再有錯時它自己會報錯**，逼你回來清掉 ——
> 比 `// @ts-ignore` 好，後者會永遠沉默。
> ★★★ 第三方套件沒有型別時：`npm i -D @types/套件名`，
> 找不到就自己寫一個 `src/types/套件名.d.ts`：
> ```typescript
> declare module '沒型別的套件' {
>   export function doThing(x: string): void;
> }
> ```

---

## 完整實戰範例

把 [[04-JavaScript非同步與API]] 的 API 客戶端改寫成 TypeScript。

**`src/types.ts`**

```typescript
export type HostStatus = 'up' | 'down' | 'maintenance';

export interface Host {
  readonly id: number;
  name: string;
  ip: string;
  role: string;
  cpu_load: number;
  mem_pct: number;
  status: HostStatus;
  tags?: string[];
}

// 新增時不需要 id（由後端產生）
export type HostCreate = Omit<Host, 'id'>;
// 更新時所有欄位都可選
export type HostUpdate = Partial<HostCreate>;

export interface ApiErrorBody {
  message: string;
  code?: string;
}
```

**`src/api.ts`**

```typescript
import type { ApiErrorBody } from './types';

export class ApiError extends Error {
  constructor(
    public readonly status: number,      // ★★★ 建構子參數屬性，省一堆 this.x = x
    message: string,
    public readonly body: unknown = null,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

interface ApiOptions extends RequestInit {
  timeoutMs?: number;
}

export async function api<T>(路徑: string, 選項: ApiOptions = {}): Promise<T> {
  const { timeoutMs = 8000, ...init } = 選項;
  const ctrl = new AbortController();
  const 計時 = setTimeout(() => ctrl.abort(), timeoutMs);

  try {
    const res = await fetch(路徑, {
      credentials: 'same-origin',
      signal: ctrl.signal,
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init.body && !(init.body instanceof FormData)
          ? { 'Content-Type': 'application/json' }
          : {}),
        ...init.headers,
      },
    });

    const 型別 = res.headers.get('content-type') ?? '';
    const 內文: unknown = 型別.includes('application/json')
      ? await res.json().catch(() => null)
      : await res.text();

    if (!res.ok) {
      // ★★★ 用 unknown + 窄化，不用 any
      const 訊息 =
        typeof 內文 === 'object' && 內文 !== null && 'message' in 內文
          ? String((內文 as ApiErrorBody).message)
          : `HTTP ${res.status} ${res.statusText}`;
      throw new ApiError(res.status, 訊息, 內文);
    }
    return 內文 as T;                    // ★★ 邊界處的斷言，下面用守衛補強

  } catch (e) {
    if (e instanceof ApiError) throw e;
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw new ApiError(0, `逾時 ${timeoutMs}ms：${路徑}`);
    }
    throw new ApiError(0, `連線失敗：${路徑}`);
  } finally {
    clearTimeout(計時);
  }
}

export const get  = <T>(p: string, o?: ApiOptions) =>
  api<T>(p, { ...o, method: 'GET' });

export const post = <T>(p: string, d: unknown, o?: ApiOptions) =>
  api<T>(p, { ...o, method: 'POST', body: JSON.stringify(d) });
```

**`src/hosts.ts`** —— 加上執行期守衛

```typescript
import { get } from './api';
import type { Host, HostStatus } from './types';

const 合法狀態: readonly HostStatus[] = ['up', 'down', 'maintenance'] as const;

function 是Host(x: unknown): x is Host {
  if (typeof x !== 'object' || x === null) return false;
  const h = x as Record<string, unknown>;
  return (
    typeof h.id === 'number' &&
    typeof h.name === 'string' &&
    typeof h.ip === 'string' &&
    typeof h.cpu_load === 'number' &&
    typeof h.mem_pct === 'number' &&
    合法狀態.includes(h.status as HostStatus)
  );
}

export async function 取得主機清單(): Promise<Host[]> {
  const 原始 = await get<unknown>('/api/hosts');
  if (!Array.isArray(原始)) {
    throw new Error('API 回傳的不是陣列');
  }
  const 壞的 = 原始.filter(x => !是Host(x));
  if (壞的.length > 0) {
    // ★★★★ 印出第一筆壞資料，比只說「格式錯誤」好查十倍
    console.error('不符預期的資料：', 壞的[0]);
    throw new Error(`${壞的.length} 筆主機資料格式不符（後端欄位是不是改了？）`);
  }
  return 原始 as Host[];
}

export function 依負載排序(主機: readonly Host[]): Host[] {
  return [...主機].sort((a, b) => b.cpu_load - a.cpu_load);   // ★★★ 複製後再排
}

export function 異常主機(主機: readonly Host[]): Host[] {
  return 主機.filter(h => h.status !== 'up');
}
```

**驗證流程**

```bash
# 1. 型別檢查（★★★★ 這是主要防線）
npx tsc --noEmit
# 預期：沒有輸出即為通過

# 2. 故意製造一個錯誤來確認檢查真的有跑
echo 'const x: number = "字串";' > src/_test.ts
npx tsc --noEmit
# 預期輸出：
# src/_test.ts:1:7 - error TS2322: Type 'string' is not assignable to type 'number'.
rm src/_test.ts

# 3. 建置
npm run build

# 4. 確認產出裡沒有型別殘留（TS 型別應該完全消失）
grep -r ': Host\[\]' dist/ ; echo "退出碼 $? （1 = 沒找到，正確）"
```

**加進 CI 與 pre-commit**

```json
// package.json
{
  "scripts": {
    "typecheck": "tsc --noEmit",
    "build": "vite build",
    "ci": "npm run typecheck && npm run build"
  }
}
```

```bash
# .git/hooks/pre-commit （記得 chmod +x）
#!/usr/bin/env bash
set -euo pipefail
echo "▶ 型別檢查…"
npm run --silent typecheck || {
  echo "✗ 型別檢查失敗，commit 中止"
  exit 1
}
echo "✓ 通過"
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ `TS2531: Object is possibly 'null'` | `querySelector` 等可能回 null | `if (el)` 判斷、`?.`、或確定時用 `!` |
| ★★★★ `TS2339: Property 'x' does not exist on type 'Y'` | 屬性名打錯，或型別定義沒跟上後端 | 對照 API 文件更新 interface；錯誤訊息常會提示正確名稱 |
| ★★★★ `TS2322: Type 'string' is not assignable to type 'number'` | 型別不符，常見於表單值忘了 `Number()` | `Number(input.value)` |
| ★★★★ `TS7006: Parameter 'x' implicitly has an 'any' type` | 開了 `noImplicitAny` 卻沒標型別 | 補上型別標註 |
| ★★★★ 本機建置成功、伺服器上模組找不到 | import 路徑大小寫不一致 | 開 `forceConsistentCasingInFileNames` |
| ★★★ `TS2307: Cannot find module 'xxx'` | 套件沒裝、或沒有型別定義 | `npm i xxx` + `npm i -D @types/xxx`；都沒有就自寫 `.d.ts` |
| ★★★ `TS18046: 'e' is of type 'unknown'` | `catch (e)` 的 e 在新版 TS 是 `unknown` | `if (e instanceof Error) e.message` |
| ★★★ 型別看起來對，執行期還是壞 | 用了 `as` 斷言但實際資料不符 | 加執行期守衛或 Zod |
| ★★★ Vite 跑得起來但 CI 紅 | Vite 只剝型別不檢查 | 這是正常分工，把 `tsc --noEmit` 加進 CI |
| ★★ 編輯器與 CLI 報的錯不一樣 | VSCode 用內建 TS 版本，專案用另一個 | VSCode：`TypeScript: Select TypeScript Version` → Use Workspace Version |
| ★★ `tsc` 慢到不能用 | 檢查了 `node_modules` | 開 `skipLibCheck: true`，設好 `exclude` |

### 排查步驟

**【1】確認用的是專案的 TS 版本**

```bash
npx tsc --version          # 專案版本
tsc --version 2>/dev/null  # 全域版本（如果有裝）
```

★★★ 兩者不同會造成「同事沒事我有事」。專案版本以 `package.json` 的
`devDependencies` 為準，全域的那份建議直接移除。

**【2】看完整錯誤，不要只看第一行**

```bash
npx tsc --noEmit --pretty
```

★★★ TS 的錯誤訊息常有多層（`Types of property 'x' are incompatible.` 之後才是真正原因），
最後一層通常才是關鍵。

**【3】把錯誤數量統計出來，決定先修哪一類**

```bash
npx tsc --noEmit 2>&1 | grep -oE 'error TS[0-9]+' | sort | uniq -c | sort -rn
# 範例輸出：
#      47 error TS2531      ← 先處理這類（null 檢查）
#      12 error TS7006
#       3 error TS2339
```

★★★★ 遷移既有專案時這招很有用 —— 一次解決一類錯誤，比逐檔亂修有效率得多。

**【4】確認檢查範圍對不對**

```bash
npx tsc --noEmit --listFiles | head -20      # 看它到底檢查了哪些檔
npx tsc --showConfig                          # 看最終生效的設定（含繼承來的）
```

**【5】型別對但執行期壞 → 找 `as` 與 `any`**

```bash
grep -rn ' as ' src/ --include='*.ts' | grep -v ' as const'
grep -rn ': any' src/ --include='*.ts'
```

★★★★ 這兩個是「TS 說沒問題但程式還是爆炸」的元兇。每一處都該問：
這裡的資料真的能保證是那個型別嗎？

---

## 安全性注意事項

> [!danger] 最重要的一句
> ★★★★★ **TypeScript 不提供任何執行期的安全保障。**
> 型別在編譯後全部消失，它擋不住惡意輸入、擋不住 XSS、擋不住 API 回傳異常資料。
> 把 TS 當成資安措施是危險的誤解。

| 誤以為 TS 能擋 | 實際上要做什麼 |
| --- | --- |
| API 回傳格式異常 | ★★★★ 執行期驗證（型別守衛 / Zod） |
| 使用者輸入惡意內容 | ★★★★ 後端驗證 + 前端用 `textContent` 而非 `innerHTML` |
| XSS | ★★★★★ 見 [[03-JavaScript基礎]] 安全性章節 |
| 越權存取 | ★★★★ 後端授權檢查，前端隱藏按鈕只是 UI |

**其他**

- ★★★★ **型別定義檔會被打包進產物**嗎？不會，但 **source map 會洩漏原始碼**。
  正式環境設 `build.sourcemap: false`，或只上傳給錯誤追蹤服務、不對外提供。
- ★★★ **`.d.ts` 裡不要寫內部主機名或 API 金鑰**（有人會把範例值寫在註解裡）。
- ★★★ **`@types/*` 也是第三方套件**，同樣受供應鏈攻擊影響。
  用 `npm audit`、`npm ci`（鎖定 lockfile）控管。見 [[06-前端建置工具與套件管理]]。
- ★★ **不要用 `as any` 繞過權限相關的型別錯誤** —— 那通常代表你在做不該做的事。

---

## 速查表

### 常用標註

| 寫法 | 意義 | 星級 |
| --- | --- | --- |
| `x: string \| number` | 聯合型別 | ★★★★ |
| `type S = 'up' \| 'down'` | 字面值型別，擋拼錯 | ★★★★ |
| `x?: T` | 可選，等同 `T \| undefined` | ★★★★ |
| `readonly x: T` | 唯讀屬性 | ★★ |
| `x!` | 非空斷言，慎用 | ★★★ |
| `x as T` | 型別斷言，不做檢查 | ★★★ |
| `as const` | 推論成字面值型別而非 string | ★★★ |
| `unknown` | 安全版的 any，用前要窄化 | ★★★★ |
| `any` | ★★★★ 放棄檢查，盡量不用 | ★★★★ |

### 工具型別

| 型別 | 作用 | 典型用途 |
| --- | --- | --- |
| `Partial<T>` | 全部欄位變可選 | ★★★ PATCH 更新 |
| `Omit<T, 'k'>` | 排除欄位 | ★★★ 新增時排除 id |
| `Pick<T, 'a'\|'b'>` | 只取部分欄位 | 清單顯示 |
| `Record<K, V>` | 字典 | `Record<string, Host>` |
| `Readonly<T>` | 全部唯讀 | 設定物件 |
| `ReturnType<typeof f>` | 取函式回傳型別 | 避免重複定義 |

### 指令

| 指令 | 用途 | 星級 |
| --- | --- | --- |
| `npx tsc --noEmit` | 只檢查不產檔 | ★★★★★ |
| `npx tsc --noEmit --watch` | 存檔即檢查 | ★★★ |
| `npx tsc --showConfig` | 看最終生效設定 | ★★★ |
| `npx tsc --noEmit --listFiles` | 看檢查了哪些檔 | ★★ |
| `npm i -D @types/xxx` | 補第三方型別 | ★★★ |
| `// @ts-expect-error` | 暫時忽略且會提醒清理 | ★★★ |

### `tsconfig` 六個重點

| 選項 | 建議值 | 星級 |
| --- | --- | --- |
| `strict` | `true` | ★★★★★ |
| `forceConsistentCasingInFileNames` | `true` | ★★★★ |
| `noUncheckedIndexedAccess` | `true` | ★★★★ |
| `skipLibCheck` | `true` | ★★★ |
| `noEmit` | `true`（搭配 Vite） | ★★★ |
| `allowJs` + `checkJs` | 遷移期 `true` | ★★★★ |

---

## 練習題

> [!question]- 練習 1：找出四個型別錯誤
> ```typescript
> interface Host { name: string; port: number; status: 'up' | 'down'; }
> const h: Host = { name: 'web01', port: '443', status: 'UP' };
> const el = document.querySelector('#q');
> console.log(el.value);
> ```
>
> **參考解答**：
> ① `port: '443'` 是字串，應為 `443`；
> ② `status: 'UP'` 大小寫錯，只能是 `'up'` 或 `'down'`；
> ③ `el` 型別是 `Element | null`，直接取屬性會報 possibly null；
> ④ 一般 `Element` 沒有 `.value`，要寫
> `document.querySelector<HTMLInputElement>('#q')` 才有。

> [!question]- 練習 2：把 JS 函式加上型別
> 把 [[03-JavaScript基礎]] 的 `取得顯示資料()` 加上完整型別標註（含參數與回傳值），
> 並用 `tsc --noEmit` 驗證。
>
> **提示**：先定義 `interface Host`，函式簽名寫成
> `function 取得顯示資料(清單: readonly Host[], 關鍵字: string, 只看異常: boolean): Host[]`。
> 用 `readonly` 表達「這個函式不會改動傳進來的陣列」。

> [!question]- 練習 3：規劃遷移計畫
> 一個 120 支 `.js` 檔的既有專案要導入 TS。寫出你的四階段計畫與每階段的驗收標準。
>
> **參考解答**：
> 階段一 `allowJs + checkJs + strict:false`，驗收＝`tsc --noEmit` 錯誤數有基準值並記錄下來；
> 階段二 新檔案一律 `.ts`，驗收＝pre-commit 擋下新的 `.js`；
> 階段三 由外而內轉換（工具 → 型別 → API → 元件 → 進入點），
> 驗收＝每轉一批錯誤數只減不增；
> 階段四 依序開 `noImplicitAny` → `strictNullChecks` → `strict`，
> 驗收＝每開一個都能清到 0 才開下一個。全程 `tsc --noEmit` 進 CI。

---

## 小測驗

Q1. TypeScript 的型別在瀏覽器執行時還存在嗎？這代表什麼？

Q2. `const 主機 = await res.json() as Host[];` 這行安全嗎？

Q3. `any` 與 `unknown` 差在哪？該優先用哪個？

Q4. `strict: true` 開啟後，`document.querySelector('#app').textContent = 'x'` 為什麼會報錯？有哪三種修法？

Q5. `interface` 與 `type` 各適合什麼場合？

Q6. `Partial<Host>` 與 `Omit<Host, 'id'>` 分別在什麼 API 情境用得到？

Q7. 為什麼 `forceConsistentCasingInFileNames` 對「Windows 開發、Linux 部署」的團隊特別重要？

Q8. Vite 建置成功但 CI 的型別檢查失敗，這是壞掉了嗎？

Q9. 既有 JS 專案要導入 TS，第一步該做什麼？為什麼不建議一次全改副檔名？

Q10. `// @ts-ignore` 與 `// @ts-expect-error` 差在哪？該用哪個？

> [!question]- 測驗答案
> **Q1.** ★★★★★ **不存在。** 所有型別標註在編譯（transpile）階段就被**完全移除**，
> 產出的 `.js` 跟手寫的純 JS 一模一樣。三個推論：
> ① TS **沒有任何執行期成本**，不會讓程式變慢；
> ② TS **無法驗證外部進來的資料** —— API 回什麼、使用者填什麼，它一概不知；
> ③ TS **不是資安措施**，擋不住 XSS、惡意輸入或越權。
> 所以「編譯期用 TS、執行期自己驗證」兩道防線缺一不可。
>
> **Q2.** ★★★★ **不安全。** `res.json()` 的回傳型別是 `any`（TS 不可能知道後端回什麼），
> `as Host[]` 只是**你向編譯器宣稱**它是這個型別，**不做任何檢查**。
> 後端某天把 `cpu_load` 改名成 `load`，TS 完全不會警告，
> 程式會在執行期得到 `undefined` 然後 NaN 或崩潰。
> 正確做法是加執行期守衛（`function 是Host(x: unknown): x is Host`）
> 或用 Zod 之類的驗證函式庫 —— 後者還能由 schema 自動推導型別，不會與驗證脫節。
>
> **Q3.** `any` 是「關掉所有檢查」，可以對它做任何操作，錯誤全部放行，
> 而且會**傳染**給下游變數；`unknown` 是「還不知道是什麼」，
> 在**窄化之前不能做任何操作**，逼你先用 `typeof`、`instanceof`、`in` 或型別守衛確認。
> ★★★★ **優先用 `unknown`**。實務原則：想寫 `any` 時先問「能不能改用 `unknown`」，
> 真的必須用 `any` 就留 `// TODO` 註記，並限縮在遷移期的臨時逃生口。
>
> **Q4.** 因為 `strict` 包含 `strictNullChecks`，`querySelector` 的回傳型別是
> `Element | null`，可能為 null 時不允許直接取屬性。三種修法：
> ① ★★★★ `if (el) el.textContent = 'x'` —— 最推薦，明確處理找不到的情況；
> ② `el?.setAttribute(...)` —— 可選鏈，找不到就靜靜跳過；
> ③ `document.querySelector('#app')!` —— 非空斷言，**等於請編譯器閉嘴**，
> 只在元素確實寫死在 HTML 裡時用，且最好加註解說明保證從何而來。
> 另外若要取 `.value`，還得寫成 `querySelector<HTMLInputElement>('#app')`。
>
> **Q5.** `interface` 適合**描述物件的形狀** —— API 回傳結構、元件 props、設定物件；
> 它可以被 `extends` 繼承、可以宣告合併，錯誤訊息也比較好讀。
> `type` 能力更廣，**聯合型別、字面值型別、函式型別、工具型別**只能用它
> （`type 狀態 = 'up' | 'down'` 用 `interface` 寫不出來）。
> ★★★ 實務建議：資料結構用 `interface`，其餘用 `type`；
> 但團隊一致性比選哪個更重要，挑一套寫進規範即可。
>
> **Q6.** `Partial<Host>` 讓所有欄位變可選，適合 **PATCH／更新 API** ——
> 呼叫端只傳想改的欄位。
> `Omit<Host, 'id'>` 排除 `id`，適合**新增（POST）API** ——
> id 由資料庫產生，前端不該也不能提供。
> ★★★ 這兩個工具型別讓你從一份 `Host` 定義衍生出所有變體，
> 不必手抄三份幾乎一樣的 interface（抄了就一定會有一份忘記同步）。
>
> **Q7.** ★★★★ 因為 Windows 與 macOS 的檔案系統**預設不分大小寫**，Linux **分**。
> 寫 `import x from './models/host'` 而實際檔名是 `Host.ts`，
> 在開發機能正常解析，部署到 Linux 伺服器就變成「模組找不到」或打包後 404。
> 這類問題的特徵是「本機完全正常、只有正式環境壞」，非常難查。
> 開啟這個選項後，大小寫不一致的 import 會在編譯期就直接報錯。
>
> **Q8.** ★★★ **不是壞掉，這是正常的分工。**
> Vite（底層是 esbuild／swc）為了速度，只把 `.ts` 的型別標註**剝掉**再打包，
> **完全不做型別檢查**。型別檢查是 `tsc --noEmit` 的職責。
> 所以標準組合是「Vite 負責建置 + `tsc --noEmit` 負責檢查」，
> 兩者都要放進 CI（`npm run typecheck && npm run build`）。
> 只靠 Vite 會讓型別錯誤一路溜到正式環境。
>
> **Q9.** 第一步是**只開檢查、不改副檔名**：在 `tsconfig.json` 設
> `allowJs: true`、`checkJs: true`、`noEmit: true`、`strict: false`，
> 用 JSDoc 註解替既有 `.js` 標型別。這樣不動任何建置流程就能抓出一批拼錯與傳錯參數。
> ★★★★ 不建議一次全改的原因：
> 開了 `strict` 的大型舊專案通常會噴出**數千個錯誤**，團隊看到就放棄了；
> 而且大規模改副檔名會產生巨大的 diff，讓 code review 失效、
> 也讓 `git blame` 與 hotfix 的 cherry-pick 變得困難。
> 正確節奏是四階段：開檢查 → 新檔用 TS → 由外而內轉換 → 逐步收緊嚴格度。
>
> **Q10.** 兩者都會忽略下一行的型別錯誤，但 **`@ts-expect-error` 在那行「沒有錯誤」時會反過來報錯**，
> 提醒你這個抑制註解已經多餘、可以刪掉了；`@ts-ignore` 則會永遠沉默。
> ★★★ **一律用 `@ts-expect-error`**，並在後面寫上原因與追蹤方式：
> ```typescript
> // @ts-expect-error 第三方套件型別待補，見 issue #123
> ```
> 這樣遷移期留下的技術債會自己冒出來提醒你清理，而不是無聲地累積下去。

---

## 延伸閱讀

- [[03-JavaScript基礎]] —— TS 要解決的那些 JS 陷阱
- [[04-JavaScript非同步與API]] —— 這篇改寫的 API 客戶端原型
- [[06-前端建置工具與套件管理]] —— Vite、npm 與供應鏈安全
- [[07-瀏覽器開發者工具]] —— source map 與線上除錯
- TypeScript 官方手冊：<https://www.typescriptlang.org/docs/handbook/intro.html>
- TypeScript for JS Programmers：<https://www.typescriptlang.org/docs/handbook/typescript-in-5-minutes.html>
