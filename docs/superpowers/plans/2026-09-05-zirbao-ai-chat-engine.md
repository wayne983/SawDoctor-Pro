# 鋸寶 AI 對話引擎 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 GitHub Pages 的鋸寶 AI 透過 Google Apps Script 安全呼叫 OpenAI，依已核准知識庫與官網 FAQ 產生可追溯的聊天式初步導引。

**Architecture:** 將知識整理為版本控制的 JSON，並由匯出工具產生 Apps Script 可直接貼入的 `Knowledge.gs`。前端透過隱藏 iframe 與表單 POST 呼叫 Apps Script，後端先執行危險分流與關鍵字檢索，再將受限的知識內容送到 OpenAI Responses API；只接受固定 JSON 回覆並重新驗證官網連結。

**Tech Stack:** 靜態 HTML/CSS/JavaScript、Node.js 內建 `node:test`、Google Apps Script V8、OpenAI Responses API、GitHub Pages。

**Spec:** `docs/superpowers/specs/2026-09-05-zirbao-ai-chat-engine-design.md`

## Global Constraints

- 使用繁體中文；客戶版只能呈現初步導引，不能確診、保證改善或捏造 RPM、進給、尺寸、齒數、規格與加工結果。
- 僅納入已核准或已驗證的診斷知識、已公開官網 FAQ／鋸片醫學誌／商品資料；排除 `09_待整理資料`、待真人確認案例、客戶資訊與報價。
- 出現裂紋、連續缺齒、明顯變形、劇烈震動、冒煙或火花時，前後端都必須停止模型呼叫、不顯示商品卡，並導向 LINE 真人確認。
- `OPENAI_API_KEY` 僅存在使用者新建的 Apps Script「鋸寶 AI 對話後端」的指令碼屬性，絕不寫入 Git、HTML、JavaScript、README、測試輸出或聊天紀錄。
- 所有商品連結必須是 `https://www.hawer-knife.com/`；模型輸出的未知網址一律捨棄。
- 前端聊天記錄只存在目前分頁的 JavaScript 記憶體；不得寫入 Local Storage、Cookie、Spreadsheet 或資料庫。

---

### Task 1: 建立已核准知識包與可重複匯出工具

**Files:**
- Create: `zirbao-ai/knowledge/approved-knowledge.json`
- Create: `tools/export-zirbao-ai-knowledge.js`
- Create: `apps-script/zirbao-ai/Knowledge.gs`
- Create: `zirbao-ai/tests/knowledge-export.test.js`

**Interfaces:**
- Consumes: `zirbao-ai/knowledge/approved-knowledge.json`
- Produces: `apps-script/zirbao-ai/Knowledge.gs` 中的 `var ZIRBAO_APPROVED_KNOWLEDGE = [...]`。
- Produces: 知識條目 `{ id, status, kind, title, summary, keywords, followUpQuestions, sourceUrl, sourceLabel, reviewedAt }`。

- [ ] **Step 1: 寫入失敗測試，要求知識包只含核准資料與官方網址**

```js
test('approved knowledge only contains approved records and trusted HAWER URLs', () => {
  const records = JSON.parse(fs.readFileSync(knowledgePath, 'utf8'));
  assert.ok(records.length >= 10);
  for (const record of records) {
    assert.equal(record.status, 'approved');
    assert.match(record.sourceUrl, /^https:\/\/www\.hawer-knife\.com\//);
    assert.ok(record.keywords.length > 0);
    assert.ok(record.followUpQuestions.length > 0);
  }
});
```

- [ ] **Step 2: 執行測試，確認因檔案不存在而失敗**

Run: `node --test zirbao-ai/tests/knowledge-export.test.js`

Expected: FAIL，錯誤指出找不到 `approved-knowledge.json`。

- [ ] **Step 3: 建立核准知識 JSON**

建立至少 10 筆精簡、可追溯紀錄：

```json
[
  {
    "id": "product-aluminum-355-610",
    "status": "approved",
    "kind": "product",
    "title": "φ355~610 鋁合金用鋸片",
    "summary": "適用鋁管、鋁板、鋁棒、鋁擠型、鋁錠與銅件的官方產品頁；實際規格仍須確認機台與材料條件。",
    "keywords": ["鋁管", "鋁板", "鋁棒", "鋁擠型", "鋁錠", "銅件", "355", "610", "14 吋"],
    "followUpQuestions": ["請提供材料外徑、壁厚或厚度。", "請提供機台型號、主軸轉速與現有鋸片規格。"],
    "sourceUrl": "https://www.hawer-knife.com/ProductDetails.asp?produid=19",
    "sourceLabel": "HAWER 鋁合金用圓鋸片",
    "reviewedAt": "2026-09-05"
  }
]
```

其餘紀錄分別涵蓋鋁棒／鋁胚、型鋼冷熱切、研磨維修、木工塑料、刀痕、震動、波紋／魚鱗紋、齒數、燒焦與斷齒。FAQ 摘要必須使用改寫，不複製整段官網文字；知識卡保留資料不足時的追問與真人確認語句。

- [ ] **Step 4: 寫入匯出工具的失敗測試**

```js
test('knowledge exporter creates a valid Apps Script literal without unsafe characters', () => {
  execFileSync(process.execPath, [exporterPath], { cwd: repoRoot });
  const generated = fs.readFileSync(outputPath, 'utf8');
  assert.match(generated, /^var ZIRBAO_APPROVED_KNOWLEDGE = /);
  assert.doesNotMatch(generated, /<\/script/i);
  const literal = generated
    .replace(/^var ZIRBAO_APPROVED_KNOWLEDGE = /, '')
    .replace(/;\s*$/, '');
  assert.ok(JSON.parse(literal).length >= 10);
});
```

- [ ] **Step 5: 執行測試，確認因匯出工具不存在而失敗**

Run: `node --test zirbao-ai/tests/knowledge-export.test.js`

Expected: FAIL，錯誤指出找不到 `tools/export-zirbao-ai-knowledge.js`。

- [ ] **Step 6: 實作匯出工具並產生 `Knowledge.gs`**

工具讀取 JSON、驗證每筆 `status === 'approved'`、驗證網址主機、拒絕 `<script`，接著產生：

```js
var ZIRBAO_APPROVED_KNOWLEDGE = [
  {
    "id": "product-aluminum-355-610",
    "status": "approved"
  }
];
```

工具在驗證失敗時以非零結束碼中止，且不得覆寫來源 JSON。

- [ ] **Step 7: 執行知識測試確認通過**

Run: `node --test zirbao-ai/tests/knowledge-export.test.js`

Expected: PASS。

- [ ] **Step 8: 提交知識包與匯出工具**

```powershell
git add zirbao-ai/knowledge/approved-knowledge.json tools/export-zirbao-ai-knowledge.js apps-script/zirbao-ai/Knowledge.gs zirbao-ai/tests/knowledge-export.test.js
git commit -m "feat: add approved zirbao knowledge pack"
```

### Task 2: 建立共用的安全檢索與回覆清洗核心

**Files:**
- Create: `zirbao-ai/zirbao-core.js`
- Create: `zirbao-ai/tests/zirbao-core.test.js`
- Create: `apps-script/zirbao-ai/Core.gs`

**Interfaces:**
- Consumes: `question: string`、`knowledge: KnowledgeRecord[]`、`candidateReply: object`。
- Produces: `ZirbaoCore.normalizeText(value)`、`isDangerous(question)`、`retrieve(question, knowledge)`、`validateRequest(payload)`、`sanitizeModelReply(candidate, knowledge)`。
- Produces: 後端可直接使用的 `ZirbaoAiCore`，函式名稱與行為等同 Node 核心。

- [ ] **Step 1: 寫入危險分流的失敗測試**

```js
test('dangerous question bypasses retrieval and returns only stop guidance', () => {
  const result = ZirbaoCore.createSafetyReply('切割時劇烈震動又有火花');
  assert.equal(result.mode, 'danger');
  assert.deepEqual(result.cards, []);
  assert.match(result.message, /先停機檢查/);
});
```

- [ ] **Step 2: 執行測試，確認因核心不存在而失敗**

Run: `node --test zirbao-ai/tests/zirbao-core.test.js`

Expected: FAIL，錯誤指出 `zirbao-core.js` 或 `createSafetyReply` 不存在。

- [ ] **Step 3: 實作核心的危險詞、文字正規化與網址驗證**

使用固定危險詞：`裂紋`、`裂痕`、`缺齒`、`掉齒`、`連續缺齒`、`變形`、`劇烈震動`、`異常震動`、`冒煙`、`火花`。所有 `sourceUrl` 與卡片 URL 必須通過 `https://www.hawer-knife.com/` 驗證；LINE 網址只由固定常數提供。

- [ ] **Step 4: 新增檢索與 14 吋薄壁鋁管失敗測試**

```js
test('retrieval finds aluminum product knowledge for 14 inch thin-wall aluminum tube', () => {
  const cards = ZirbaoCore.retrieve('14 吋切斷機切薄壁鋁管', knowledge);
  assert.equal(cards[0].id, 'product-aluminum-355-610');
  assert.match(cards[0].sourceUrl, /produid=19/);
});

test('the assistant summary asks for missing conditions instead of inventing 120T', () => {
  const reply = ZirbaoCore.fallbackReply('14 吋切斷機切薄壁鋁管', knowledge);
  assert.match(reply.message, /初步方向/);
  assert.doesNotMatch(reply.message, /120T/);
  assert.ok(reply.followUpQuestions.some((item) => /壁厚/.test(item)));
});
```

- [ ] **Step 5: 執行測試，確認檢索函式尚未實作而失敗**

Run: `node --test zirbao-ai/tests/zirbao-core.test.js`

Expected: FAIL，錯誤指出 `retrieve` 或 `fallbackReply` 不存在。

- [ ] **Step 6: 實作檢索、payload 驗證與模型 JSON 清洗**

檢索以正規化後的 `keywords`、`title`、`summary` 計分，取最多 5 筆。`validateRequest` 限制 question 1,000 字元、history 6 則、每則 1,000 字元。`sanitizeModelReply` 只接受：

```js
{
  mode: 'answer',
  message: '純文字',
  followUpQuestions: ['問題'],
  cards: [{ id: 'knowledge-record-id' }]
}
```

它必須把卡片 `id` 對回知識包中的官方條目，不信任模型提供的 URL 或摘要。

- [ ] **Step 7: 新增並執行模型清洗測試**

```js
test('sanitizer drops model supplied external URLs and resolves known card ids', () => {
  const reply = ZirbaoCore.sanitizeModelReply({
    mode: 'answer',
    message: '先確認條件。',
    followUpQuestions: ['請提供壁厚。'],
    cards: [
      { id: 'product-aluminum-355-610', url: 'https://example.com/' },
      { id: 'not-known' }
    ]
  }, knowledge);
  assert.equal(reply.cards.length, 1);
  assert.match(reply.cards[0].url, /^https:\/\/www\.hawer-knife\.com\//);
});
```

Run: `node --test zirbao-ai/tests/zirbao-core.test.js`

Expected: PASS。

- [ ] **Step 8: 複製同等核心至 Apps Script 並提交**

`Core.gs` 不使用 `require`、箭頭函式或 Node API；以 `var ZirbaoAiCore = (function () { ... })();` 提供同名函式。以 `node` 的 `vm` 載入 `Core.gs` 進行相同關鍵行為測試。

```powershell
git add zirbao-ai/zirbao-core.js zirbao-ai/tests/zirbao-core.test.js apps-script/zirbao-ai/Core.gs
git commit -m "feat: add zirbao safety and retrieval core"
```

### Task 3: 實作 Apps Script 的 OpenAI 安全後端

**Files:**
- Create: `apps-script/zirbao-ai/Code.gs`
- Create: `apps-script/zirbao-ai/appsscript.json`
- Create: `apps-script/zirbao-ai/README.md`
- Create: `zirbao-ai/tests/apps-script-ai.test.js`

**Interfaces:**
- Consumes: 表單欄位 `payload`，內容為 `{ requestId, question, history }` JSON。
- Produces: `doPost(e)` 的 HTML `postMessage` 回呼 `{ type: 'zirbao-ai-reply', requestId, ok, reply }`。
- Requires: Apps Script 指令碼屬性 `OPENAI_API_KEY`。

- [ ] **Step 1: 寫入後端失敗測試，驗證缺少 key 和危險問題不會呼叫 UrlFetchApp**

```js
test('danger reply does not call OpenAI', () => {
  const context = loadAppsScript({ OPENAI_API_KEY: 'test-key' });
  const result = context.ZirbaoAiBackend.answer_({
    requestId: 'r-1',
    question: '鋸片裂紋而且劇烈震動',
    history: []
  });
  assert.equal(result.ok, true);
  assert.equal(result.reply.mode, 'danger');
  assert.equal(context.fetchCalls.length, 0);
});

test('missing API key returns a safe unavailable message', () => {
  const context = loadAppsScript({});
  const result = context.ZirbaoAiBackend.answer_({ requestId: 'r-2', question: '切鋁管有毛邊', history: [] });
  assert.equal(result.ok, false);
  assert.match(result.reply.message, /無法取得 AI 回覆/);
});
```

- [ ] **Step 2: 執行測試，確認因後端檔案不存在而失敗**

Run: `node --test zirbao-ai/tests/apps-script-ai.test.js`

Expected: FAIL，錯誤指出找不到 `apps-script/zirbao-ai/Code.gs`。

- [ ] **Step 3: 實作 request 驗證、危險短路與 API key 讀取**

`answer_` 先執行 `ZirbaoAiCore.validateRequest` 和 `createSafetyReply`。若 `OPENAI_API_KEY` 不存在、危險、輸入無效或沒有相關資料，回傳安全的結構化回覆；只有一般問題才使用 `UrlFetchApp.fetch`。

- [ ] **Step 4: 寫入 OpenAI 請求與回覆清洗失敗測試**

```js
test('general question sends only retrieved approved knowledge to Responses API', () => {
  const context = loadAppsScript({ OPENAI_API_KEY: 'test-key' }, validOpenAiResponse);
  const result = context.ZirbaoAiBackend.answer_({
    requestId: 'r-3', question: '14 吋切斷機裁切薄壁鋁管', history: []
  });
  const request = JSON.parse(context.fetchCalls[0].payload);
  assert.equal(request.model, 'gpt-5-mini');
  assert.match(JSON.stringify(request), /product-aluminum-355-610/);
  assert.doesNotMatch(JSON.stringify(request), /OPENAI_API_KEY/);
  assert.equal(result.reply.cards[0].url, 'https://www.hawer-knife.com/ProductDetails.asp?produid=19');
});
```

- [ ] **Step 5: 執行測試，確認尚未呼叫 Responses API 而失敗**

Run: `node --test zirbao-ai/tests/apps-script-ai.test.js`

Expected: FAIL，錯誤指出 `UrlFetchApp.fetch` 未被呼叫或無法取得產品卡。

- [ ] **Step 6: 實作 Responses API 呼叫與固定回覆格式**

透過 `https://api.openai.com/v1/responses` 發送 `POST`、`Authorization: Bearer <key>`、`Content-Type: application/json`，並設定：

```js
{
  model: 'gpt-5-mini',
  store: false,
  text: {
    format: {
      type: 'json_schema',
      name: 'zirbao_reply',
      strict: true,
      schema: {
        type: 'object',
        additionalProperties: false,
        required: ['mode', 'message', 'followUpQuestions', 'cards'],
        properties: {
          mode: { type: 'string', enum: ['answer'] },
          message: { type: 'string' },
          followUpQuestions: { type: 'array', items: { type: 'string' }, maxItems: 3 },
          cards: {
            type: 'array',
            items: {
              type: 'object',
              additionalProperties: false,
              required: ['id'],
              properties: { id: { type: 'string' } }
            },
            maxItems: 3
          }
        }
      }
    }
  }
```

系統指示必須含本計畫的安全規則、禁止捏造規格、2 至 4 個可能原因、資料不足時補問與卡片 ID 限制。用 `muteHttpExceptions: true` 解析失敗；所有失敗只回傳使用者可理解的安全文字，伺服器日誌不得記錄 key。

- [ ] **Step 7: 實作安全 callback 與設定檔**

`callbackOutput_` 必須以 `HtmlService` 產生：

```js
<script>top.postMessage({"type":"zirbao-ai-reply"},"https://wayne983.github.io");</script>
```

JSON 先將 `<` 替換為 `\\u003c`。`appsscript.json` 使用 V8、`ANYONE_ANONYMOUS`、`script.external_request` scope 與必要的外部請求權限；不申請 Spreadsheet、Mail 或 Drive scope。

- [ ] **Step 8: 執行後端測試與提交**

Run: `node --test zirbao-ai/tests/apps-script-ai.test.js`

Expected: PASS。

```powershell
git add apps-script/zirbao-ai/Code.gs apps-script/zirbao-ai/Core.gs apps-script/zirbao-ai/Knowledge.gs apps-script/zirbao-ai/appsscript.json apps-script/zirbao-ai/README.md zirbao-ai/tests/apps-script-ai.test.js
git commit -m "feat: add zirbao apps script ai backend"
```

### Task 4: 將鋸寶頁面改為聊天式後端用戶端並保留安全備援

**Files:**
- Create: `zirbao-ai/config.js`
- Modify: `zirbao-ai/index.html`
- Modify: `zirbao-ai/app.js`
- Modify: `zirbao-ai/styles.css`
- Modify: `zirbao-ai/tests/zirbao-ai.test.js`
- Create: `zirbao-ai/tests/zirbao-client.test.js`

**Interfaces:**
- Consumes: `window.ZIRBAO_AI_CONFIG = { endpoint: '' }` 與 iframe `postMessage` 回覆。
- Produces: `ZirbaoClient.sendQuestion(question)`、`ZirbaoClient.handleBackendReply(event)` 和安全的 DOM 回覆。
- Fallback: endpoint 為空、逾時或回覆無效時呼叫既有 `ZirbaoGuide.answer(question)`。

- [ ] **Step 1: 寫入失敗測試，驗證 endpoint 空白會維持關鍵字備援**

```js
test('client uses local guide when no Apps Script endpoint is configured', async () => {
  const client = createClient({ endpoint: '' });
  const reply = await client.sendQuestion('鋁管 355');
  assert.equal(reply.source, 'local-fallback');
  assert.match(reply.cards[0].url, /hawer-knife\.com/);
});
```

- [ ] **Step 2: 執行測試，確認 `createClient` 尚未存在而失敗**

Run: `node --test zirbao-ai/tests/zirbao-client.test.js`

Expected: FAIL，錯誤指出 `createClient` 不存在。

- [ ] **Step 3: 建立公開但不含秘密的 config 檔與 iframe 送出器**

`config.js` 的初始內容為：

```js
window.ZIRBAO_AI_CONFIG = Object.freeze({ endpoint: '' });
```

`index.html` 先載入 `config.js` 再載入 `app.js`，並新增命名的隱藏 iframe。`app.js` 使用 form POST 將 JSON 放入 `payload` 欄位，等待最多 20 秒的 `message`；只接受 `event.origin === 'https://script.google.com'` 或 Google Apps Script 導向來源、且 requestId 相同的回覆。若 timeout 或資料不合法，回到既有的本機關鍵字導覽。

- [ ] **Step 4: 寫入成功 callback 的失敗測試**

```js
test('client accepts a matching Apps Script callback and renders only text and trusted cards', async () => {
  const client = createClient({ endpoint: 'https://script.google.com/macros/s/example/exec' });
  const pending = client.sendQuestion('切鋁管有毛邊');
  client.handleBackendReply({
    origin: 'https://script.google.com',
    data: {
      type: 'zirbao-ai-reply', requestId: client.pendingRequestId(), ok: true,
      reply: { mode: 'answer', message: '<b>不可以插入 HTML</b>', followUpQuestions: [], cards: [{ title: '官方頁', summary: '摘要', url: 'https://www.hawer-knife.com/FAQ.asp' }] }
    }
  });
  const reply = await pending;
  assert.equal(reply.source, 'ai');
  assert.equal(reply.message, '<b>不可以插入 HTML</b>');
  assert.match(reply.cards[0].url, /^https:\/\/www\.hawer-knife\.com\//);
});
```

- [ ] **Step 5: 執行測試，確認 callback 行為尚未實作而失敗**

Run: `node --test zirbao-ai/tests/zirbao-client.test.js`

Expected: FAIL，錯誤指出 callback 未解析或回覆沒有 `source: 'ai'`。

- [ ] **Step 6: 實作聊天歷史、loading、回覆渲染與安全 UI**

最多保留 6 則歷史；前端只把文字交給 `textContent`，不得用 `innerHTML`。新增「鋸寶正在整理資料…」loading 狀態與送出期間的按鈕禁用；成功後顯示回覆、補問、卡片與 LINE，失敗時顯示本機導覽結果及「目前無法取得 AI 回覆」提示。危險詞在送出前直接以 `ZirbaoCore.createSafetyReply` 顯示，不建立 iframe 請求。

- [ ] **Step 7: 擴充既有結構測試並執行前端測試**

新增以下斷言：

```js
assert.match(html, /<script src="config\.js"><\/script>/);
assert.match(html, /zirbao-ai-frame/);
assert.match(appSource, /textContent/);
assert.doesNotMatch(appSource, /OPENAI_API_KEY/);
```

Run: `node --test zirbao-ai/tests/zirbao-ai.test.js zirbao-ai/tests/zirbao-client.test.js`

Expected: PASS。

- [ ] **Step 8: 提交前端聊天用戶端**

```powershell
git add zirbao-ai/config.js zirbao-ai/index.html zirbao-ai/app.js zirbao-ai/styles.css zirbao-ai/tests/zirbao-ai.test.js zirbao-ai/tests/zirbao-client.test.js
git commit -m "feat: connect zirbao chat client to ai backend"
```

### Task 5: 建立部署操作說明與完整驗證

**Files:**
- Modify: `zirbao-ai/README.md`
- Create: `apps-script/zirbao-ai/DEPLOY.md`
- Modify: `zirbao-ai/tests/knowledge-export.test.js`
- Modify: `zirbao-ai/tests/apps-script-ai.test.js`

**Interfaces:**
- Consumes: 使用者新建的「鋸寶 AI 對話後端」Apps Script 專案、已設定的 `OPENAI_API_KEY`。
- Produces: 可讓使用者貼上三個 `.gs` 檔後部署 `/exec` 的逐步操作，以及在 `config.js` 填入 endpoint 的明確位置。

- [ ] **Step 1: 寫入部署文件結構測試**

```js
test('deployment guide documents property, anonymous web app access, and endpoint configuration without exposing a key', () => {
  const guide = fs.readFileSync(deployGuidePath, 'utf8');
  assert.match(guide, /OPENAI_API_KEY/);
  assert.match(guide, /任何人/);
  assert.match(guide, /\/exec/);
  assert.doesNotMatch(guide, /sk-[A-Za-z0-9]/);
});
```

- [ ] **Step 2: 執行測試，確認部署指南不存在而失敗**

Run: `node --test zirbao-ai/tests/knowledge-export.test.js zirbao-ai/tests/apps-script-ai.test.js`

Expected: FAIL，錯誤指出找不到 `DEPLOY.md`。

- [ ] **Step 3: 撰寫部署與回滾指南**

文件須具體說明：

1. 在新 Apps Script 專案貼入 `Code.gs`、`Core.gs`、`Knowledge.gs`，並將 manifest 內容設為 `appsscript.json`。
2. 檢查 `OPENAI_API_KEY` 指令碼屬性存在，但不顯示值。
3. 部署為 Web app，執行身分為部署者，存取權為任何人；首次授權 `UrlFetchApp`。
4. 複製 `/exec` URL，將它填入 `zirbao-ai/config.js` 的 `endpoint` 字串，再提交 GitHub `main`。
5. 輸入四個測試案例：一般鋁管、14 吋薄壁鋁管、裂紋／劇烈震動、未命中關鍵字；確認 LINE 行為、商品卡與危險分流。
6. 失敗時把 `endpoint` 改回空字串並發布，前端立即回到既有關鍵字導覽；不必刪除 key。

- [ ] **Step 4: 執行完整自動測試與靜態檢查**

Run: `node --test zirbao-ai/tests/*.test.js; git diff --check`

Expected: 所有測試 PASS；格式檢查沒有輸出。

- [ ] **Step 5: 在本機啟動並手動驗證**

Run: `C:\Python313\python.exe -m http.server 8080 --directory zirbao-ai`

在 `http://localhost:8080/` 確認：endpoint 空白時可用關鍵字導覽、危險詞不發送請求、按鈕與卡片版面正常。

- [ ] **Step 6: 提交文件與驗證紀錄**

```powershell
git add zirbao-ai/README.md apps-script/zirbao-ai/DEPLOY.md zirbao-ai/tests/knowledge-export.test.js zirbao-ai/tests/apps-script-ai.test.js
git commit -m "docs: add zirbao ai deployment guide"
```

### Task 6: 使用者部署後的端對端驗收與公開發布

**Files:**
- Modify: `zirbao-ai/config.js`
- Test: `zirbao-ai/tests/*.test.js`

**Interfaces:**
- Consumes: 使用者提供的 Apps Script Web App `/exec` URL，該 URL 不含 API key。
- Produces: 連到實際 Apps Script 的 GitHub Pages 鋸寶頁面。

- [ ] **Step 1: 確認使用者已完成 Apps Script 部署並只提供 `/exec` URL**

接受格式：`https://script.google.com/macros/s/<deployment-id>/exec`。拒絕包含 `sk-`、`key` 或 query 中疑似秘密的 URL。

- [ ] **Step 2: 先在本機對 endpoint 做一般與危險情境測試**

一般問題：`14 吋切斷機裁切薄壁鋁管，有沒有推薦？`。預期是聊天式初步導引、補問管徑／壁厚／機台條件、附官方鋁合金產品卡，且不在沒有核准資料時聲稱 `120T`。

危險問題：`鋸片裂紋又劇烈震動`。預期不呼叫 OpenAI、無商品卡、顯示先停機與 LINE 真人確認。

- [ ] **Step 3: 寫入 endpoint 並重新執行所有測試**

將 `config.js` 的 endpoint 改為已驗證 URL；執行：

Run: `node --test zirbao-ai/tests/*.test.js; git diff --check`

Expected: PASS，且 diff 中不含 API key。

- [ ] **Step 4: 提交並合併發布**

```powershell
git add zirbao-ai/config.js
git commit -m "feat: configure zirbao ai endpoint"
git push origin codex/zirbao-ai-engine
```

在 code review 與使用者確認後，將此分支合併至 `main`，推送後確認 `https://wayne983.github.io/SawDoctor-Pro/zirbao-ai/` 回傳 200，並實際完成兩個端對端測試。
