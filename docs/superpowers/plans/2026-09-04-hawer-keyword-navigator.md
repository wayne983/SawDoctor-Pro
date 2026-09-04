# HAWER 官網關鍵字導覽助手 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一份可直接貼進 HAWER 官網全站自訂程式碼區的右下角關鍵字導覽助手，將訪客導向相關既有頁面。

**Architecture:** 交付品是一份自包含 HTML 片段，內嵌 CSS 與 JavaScript。JavaScript 先以可測試的純函式把輸入轉成結構化結果，再由 DOM 層渲染對話框與結果；站內頁面資料全部集中在 `PAGE_INDEX`，不使用 API、資料庫或外部腳本。

**Tech Stack:** 原生 HTML、CSS、ES2020 JavaScript、Node.js 內建 `node:test` 與 `node:vm`；零外部依賴。

**Spec:** `docs/superpowers/specs/2026-09-04-hawer-keyword-navigator-design.md`

## Global Constraints

- 交付品必須是單一、自包含、可貼入全站頁尾自訂 HTML／程式碼區的 HTML 檔。
- 不使用 API 金鑰、第三方腳本、資料庫、追蹤或提問內容儲存。
- 使用繁體中文，且不修改、刪除或取代既有官網頁面。
- 結果最多三筆；固定索引 URL 必須為 HTTPS 絕對網址。
- 警示詞為 `裂紋`、`裂痕`、`缺齒`、`掉齒`、`變形`、`劇烈震動`、`異常震動`、`冒煙`、`火花`。
- 警示詞只能顯示停機與真人確認的導引，不得確診、開處方或保證改善。
- 所有元件 CSS class 與 id 均以 `hawer-ai-` 為前綴。
- 不改動工作區任何既有、未追蹤或與本功能無關的檔案。

---

## File Structure

- `website-widget/hawer-keyword-navigator.embed.html` — 唯一給後台貼上的交付品；包含樣式、搜尋核心、頁面索引與 DOM 元件。
- `website-widget/tests/hawer-keyword-navigator.test.js` — 從交付 HTML 擷取內嵌 script，在無 DOM 的 Node VM 中測試真正的搜尋 API，再以字串檢查 HTML 的安全與可近用性契約。
- `website-widget/README.md` — 後台安裝、發布前／後驗證與日後更新 `PAGE_INDEX` 的操作手冊。

## Shared Interfaces

在 `hawer-keyword-navigator.embed.html` 的 script 中定義並於無 DOM 環境匯出：

```js
const HAWERKeywordNavigator = {
  PAGE_INDEX,
  DANGER_KEYWORDS,
  normalizeText(value),
  search(query, pages = PAGE_INDEX, limit = 3),
  findExistingSiteLink(labels, anchors)
};
```

`search` 回傳：

```js
{
  query: '正規化後的查詢',
  isEmpty: false,
  isDanger: false,
  guidance: '保守繁體中文導引',
  results: [{ id, title, url, summary, matchedKeywords, score }]
}
```

`findExistingSiteLink` 接收文字標籤陣列與 `<a>` 元素陣列，回傳首個符合文字、且 `href` 是 HTTPS 的現有站內網址；找不到時回傳空字串。它用於讓「線上詢價／聯絡我們」跟隨官網目前導覽列，而不猜測未驗證路徑。

### Task 1: 建立可測試的頁面索引與搜尋核心

**Files:**
- Create: `website-widget/hawer-keyword-navigator.embed.html`
- Create: `website-widget/tests/hawer-keyword-navigator.test.js`

**Interfaces:**
- Produces: `HAWERKeywordNavigator.normalizeText()` 與 `HAWERKeywordNavigator.search()`；Task 2 以其回傳的 `guidance`、`isDanger` 與 `results` 渲染。
- Produces: `PAGE_INDEX` 中的醫學誌、研磨維修、診療、鋁用大外徑、鋁合金、型鋼、木工塑料、WIKUS、FAQ 九筆 HTTPS 固定頁面。

- [ ] **Step 1: 寫入會失敗的搜尋核心測試**

建立 `website-widget/tests/hawer-keyword-navigator.test.js`，以 Node VM 載入交付 HTML 中唯一的 `<script>`，並先測試尚不存在的 API：

```js
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html = fs.readFileSync(new URL('../hawer-keyword-navigator.embed.html', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const sandbox = { module: { exports: {} }, exports: {} };
vm.runInNewContext(script, sandbox);
const { HAWERKeywordNavigator } = sandbox.module.exports;

test('鋁棒切割導向大外徑鋁用頁面', () => {
  const result = HAWERKeywordNavigator.search('鋁棒切割');
  assert.equal(result.results[0].id, 'aluminum-large');
});

test('研磨關鍵字導向研磨維修', () => {
  const result = HAWERKeywordNavigator.search('鋸片研磨');
  assert.equal(result.results[0].id, 'repair');
});

test('危險詞優先顯示停機與診療導流', () => {
  const result = HAWERKeywordNavigator.search('鋸片裂紋而且劇烈震動');
  assert.equal(result.isDanger, true);
  assert.equal(result.results[0].id, 'diagnosis');
  assert.match(result.guidance, /停機檢查/);
});
```

- [ ] **Step 2: 執行測試，確認因交付檔與 API 尚未建立而失敗**

Run: `node --test website-widget/tests/hawer-keyword-navigator.test.js`

Expected: FAIL，錯誤為找不到 `hawer-keyword-navigator.embed.html` 或無法取得 `HAWERKeywordNavigator`；不得因測試語法錯誤而失敗。

- [ ] **Step 3: 實作最小可用搜尋核心與固定頁面索引**

建立唯一的 `website-widget/hawer-keyword-navigator.embed.html`。先加入空的 `#hawer-ai-root`，再加入一個 `<script>`。在 script 內建立下列九筆 `PAGE_INDEX` 項目，各筆都有 `id`、`title`、`url`、`summary`、`keywords`、`priority`：

```js
const PAGE_INDEX = [
  { id: 'journal', url: 'https://www.hawer-knife.com/Product_sCats.asp?productscatid=541163996242' },
  { id: 'repair', url: 'https://www.hawer-knife.com/Product_sCats.asp?productscatid=288508731574' },
  { id: 'diagnosis', url: 'https://www.hawer-knife.com/Product_sCats.asp?productscatid=833957866333' },
  { id: 'aluminum-large', url: 'https://www.hawer-knife.com/ProductDetails.asp?produid=187' },
  { id: 'aluminum', url: 'https://www.hawer-knife.com/ProductDetails.asp?produid=19' },
  { id: 'steel', url: 'https://www.hawer-knife.com/ProductDetails.asp?produid=192' },
  { id: 'wood-plastic', url: 'https://www.hawer-knife.com/ProductDetails.asp?produid=1' },
  { id: 'wikus', url: 'https://www.hawer-knife.com/Product_sCats.asp?productscatid=060581710153' },
  { id: 'faq', url: 'https://www.hawer-knife.com/FAQ.asp' }
];
```

實作 `normalizeText`：將非字串轉成空字串、`trim()`、`toLowerCase()`、全形空白換成半形空白、連續空白壓縮成一格。實作 `search`：空白輸入回傳 `isEmpty: true` 與空 `results`；每個關鍵字以 `includes()` 命中正規化查詢計 10 分，完整片語命中額外計 10 分，最後以分數、priority、原陣列順序排序並切前三筆。含任一警示詞時將診療項目移至第一筆並回傳固定安全導引。以 `module.exports = { HAWERKeywordNavigator }` 匯出；若 `document` 不存在，不得初始化 UI。

- [ ] **Step 4: 執行核心測試，確認通過**

Run: `node --test website-widget/tests/hawer-keyword-navigator.test.js`

Expected: PASS，三個測試全部通過。

- [ ] **Step 5: 提交搜尋核心**

```bash
git add website-widget/hawer-keyword-navigator.embed.html website-widget/tests/hawer-keyword-navigator.test.js
git commit -m "feat: add HAWER keyword search core"
```

### Task 2: 加入右下角元件、動態聯絡導流與可近用性

**Files:**
- Modify: `website-widget/hawer-keyword-navigator.embed.html`
- Modify: `website-widget/tests/hawer-keyword-navigator.test.js`

**Interfaces:**
- Consumes: Task 1 的 `HAWERKeywordNavigator.search()` 與 `findExistingSiteLink()`。
- Produces: 全站右下角 `#hawer-ai-launcher`、`#hawer-ai-panel`、輸入與結果 DOM；Task 3 以其提供安裝與人工驗證說明。

- [ ] **Step 1: 寫入會失敗的元件與安全契約測試**

在同一個測試檔新增：

```js
test('交付片段含有全站可近用的浮動元件與零外部腳本', () => {
  assert.match(html, /id="hawer-ai-launcher"/);
  assert.match(html, /aria-expanded="false"/);
  assert.match(html, /id="hawer-ai-panel"/);
  assert.match(html, /aria-controls="hawer-ai-panel"/);
  assert.doesNotMatch(html, /<script[^>]+src=/i);
});

test('索引固定 URL 都是 HTTPS，且結果不超過三筆', () => {
  for (const page of HAWERKeywordNavigator.PAGE_INDEX) {
    assert.match(page.url, /^https:\/\//);
  }
  assert.ok(HAWERKeywordNavigator.search('鋁 鋼 木工 研磨 診療').results.length <= 3);
});
```

- [ ] **Step 2: 執行測試，確認元件契約尚未滿足而失敗**

Run: `node --test website-widget/tests/hawer-keyword-navigator.test.js`

Expected: FAIL，因找不到 `hawer-ai-launcher` 或 ARIA 屬性；既有核心測試仍通過。

- [ ] **Step 3: 實作元件與動態聯絡導流**

在交付檔加入內嵌 CSS 與下列 HTML：

```html
<div id="hawer-ai-root">
  <button id="hawer-ai-launcher" type="button" aria-expanded="false" aria-controls="hawer-ai-panel">AI 提問</button>
  <section id="hawer-ai-panel" role="dialog" aria-modal="false" aria-labelledby="hawer-ai-title" hidden>
    <button id="hawer-ai-close" type="button" aria-label="關閉 AI 提問">×</button>
    <h2 id="hawer-ai-title">找產品、服務或相關文章</h2>
    <label for="hawer-ai-query">請輸入關鍵字</label>
    <input id="hawer-ai-query" type="search" autocomplete="off" placeholder="例如：鋁棒、研磨、切面毛邊">
    <button id="hawer-ai-submit" type="button">查詢</button>
    <div id="hawer-ai-results" aria-live="polite"></div>
  </section>
</div>
```

寫入 CSS：桌面面板固定於右下角且在按鈕上方；在 `max-width: 600px` 時面板寬度為 `calc(100vw - 32px)`；結果區最大高度可捲動；所有 selector 都以 `#hawer-ai-root` 或 `.hawer-ai-` 開頭。

DOM 初始化只在 `document` 存在時執行：

1. 以 `click` 與 `keydown` 連接開關、Enter 查詢與 Esc 關閉；開啟時焦點進到輸入框，關閉時回到 launcher。
2. 呼叫 `search(input.value)`，將 `guidance` 與結果卡以 `document.createElement` 及 `textContent` 建立，禁止將使用者輸入寫入 `innerHTML`。
3. 無結果時呼叫 `findExistingSiteLink(['線上詢價', '聯絡我們', '連絡我們'], Array.from(document.querySelectorAll('a')))`；找到後建立一張「聯絡我們協助確認」結果卡，找不到時只顯示安全說明。
4. 警示結果保留 `search` 的固定停機提示，並同樣以現有導覽列取得的詢價／聯絡網址補上一張聯絡卡。
5. 結果連結使用 `target="_blank"` 與 `rel="noopener"`。

- [ ] **Step 4: 執行完整測試，確認通過**

Run: `node --test website-widget/tests/hawer-keyword-navigator.test.js`

Expected: PASS，所有核心與 HTML 契約測試通過。

- [ ] **Step 5: 提交元件**

```bash
git add website-widget/hawer-keyword-navigator.embed.html website-widget/tests/hawer-keyword-navigator.test.js
git commit -m "feat: add HAWER floating keyword navigator"
```

### Task 3: 建立後台安裝手冊與完成端對端驗證

**Files:**
- Create: `website-widget/README.md`
- Modify: `website-widget/tests/hawer-keyword-navigator.test.js`

**Interfaces:**
- Consumes: Task 2 的唯一交付檔與 Node 測試命令。
- Produces: 使用者可照做的全站安裝、發布前後驗證與關鍵字維護流程。

- [ ] **Step 1: 寫入會失敗的手冊完整性測試**

在測試檔加入：

```js
test('安裝手冊包含全站貼上、發布前後驗證與維護指引', () => {
  const readme = fs.readFileSync(new URL('../README.md', import.meta.url), 'utf8');
  assert.match(readme, /全站/);
  assert.match(readme, /發布前/);
  assert.match(readme, /發布後/);
  assert.match(readme, /PAGE_INDEX/);
  assert.match(readme, /裂紋/);
});
```

- [ ] **Step 2: 執行測試，確認因手冊不存在而失敗**

Run: `node --test website-widget/tests/hawer-keyword-navigator.test.js`

Expected: FAIL，錯誤為找不到 `website-widget/README.md`；前述搜尋與元件測試維持通過。

- [ ] **Step 3: 撰寫後台安裝與驗證手冊**

建立 `website-widget/README.md`，用繁體中文包含下列精確內容：

1. 備份後台現有全站頁尾自訂程式碼。
2. 將 `hawer-keyword-navigator.embed.html` 的完整內容貼入一次，儲存／發布，且不可每個頁面重複貼上。
3. 發布前在本機執行 `node --test website-widget/tests/hawer-keyword-navigator.test.js` 與 `git diff --check -- website-widget`。
4. 發布後以桌面與 390px 寬度開啟首頁、產品頁與醫學誌；驗證按鈕、開關、Enter、Esc、`鋁棒切割`、`鋸片研磨`、`切面毛邊`、`裂紋 劇烈震動`、無結果等情境。
5. 明示警示情境應只有「先停機檢查／真人技師確認」與導流，不應出現確診或保證語句。
6. 更新時只調整 `PAGE_INDEX` 項目的 `title`、`url`、`summary`、`keywords`、`priority`，並重跑測試。
7. 若網站後台不支援全站插入，停止發布並要求維護商協助提供全站頁尾程式碼區；不以逐頁重複貼上取代。

- [ ] **Step 4: 執行所有自動與格式驗證**

Run:

```bash
node --test website-widget/tests/hawer-keyword-navigator.test.js
git diff --check -- website-widget
```

Expected: 測試全數 PASS；格式檢查 exit code 0 且無輸出。

- [ ] **Step 5: 提交文件與驗證紀錄**

```bash
git add website-widget/README.md website-widget/tests/hawer-keyword-navigator.test.js
git commit -m "docs: add HAWER navigator installation guide"
```

## Plan Self-Review

### Spec coverage

- 右下角、全站單一插入、繁體中文與手機版：Task 2。
- 人工維護的頁面索引與最多三筆結果：Task 1。
- 不用 API、追蹤、資料庫與外部腳本：全域限制，Task 1 與 Task 2 的實作契約。
- 空白、無結果與現有詢價／聯絡導流：Task 1 與 Task 2。
- 危險詞停機與真人確認邊界：Task 1、Task 2、Task 3。
- 鍵盤與 ARIA 可近用性：Task 2。
- 測試優先、桌面／390px 手動檢查、後台安裝步驟：三個 Task 分別覆蓋。

### Placeholder scan

已檢查本文件，沒有占位符、延後項目或未定義的泛稱錯誤處理。

### Interface consistency

所有後續任務均使用 Task 1 定義的 `HAWERKeywordNavigator.search()`、`PAGE_INDEX` 與 `findExistingSiteLink()`；結果欄位、DOM id 與檔案路徑一致。
