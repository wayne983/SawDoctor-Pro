# 鋸寶 AI GitHub 測試站 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 建立可部署到 GitHub Pages 的獨立鋸寶 AI 測試站，提供安全的初步鋸片導引、官網連結與官方 LINE 真人確認。

**Architecture:** 新增獨立 zirbao-ai 靜態網站，不改現有檔案。app.js 同時提供可測試的回覆引擎與瀏覽器 UI；前端只使用受控的 HAWER HTTPS 產品索引，不含 API 金鑰或資料寫入。

**Tech Stack:** HTML5、CSS3、原生 JavaScript、Node.js 內建 node:test、GitHub Pages。

**Spec:** docs/superpowers/specs/2026-09-05-zirbao-ai-github-test-design.md

## Global Constraints

- 交付固定為 GitHub Pages 的 /zirbao-ai/ 靜態路徑，不覆蓋既有首頁。
- 所有客戶可見文字使用繁體中文。
- 禁止在前端儲存模型 API 金鑰、客戶資料、照片、Google Sheet 或 NAS 資料。
- 不得從單一症狀直接確診或保證規格適用。
- 裂紋、缺齒、明顯變形、劇烈震動、冒煙與火花只顯示停機與真人確認導流。
- 官網導流只接受 https://www.hawer-knife.com；LINE 固定為 https://line.me/ti/p/%40drhawer。
- 桌面與 390px 寬度均不得出現水平捲軸。

---

## File Structure

- zirbao-ai/index.html：頁面結構與無障礙標籤。
- zirbao-ai/styles.css：藍白品牌視覺與響應式版型。
- zirbao-ai/app.js：產品索引、回覆規則與 UI 初始化。
- zirbao-ai/assets/zirbao-mascot.png：透明背景鋸寶測試素材。
- zirbao-ai/tests/zirbao-ai.test.js：Node 自動測試。
- zirbao-ai/README.md：預覽與 GitHub Pages／NAS 搬遷說明。

### Task 1: 建立安全導引引擎

**Files:**
- Create: zirbao-ai/app.js
- Create: zirbao-ai/tests/zirbao-ai.test.js

**Interfaces:**
- Produces: ZirbaoGuide.answer(query) 回傳 mode、message、questions、cards 與 lineUrl。
- Produces: ZirbaoGuide.isTrustedHawerUrl(value) 回傳布林值。

- [ ] **Step 1: 寫出危險訊號的失敗測試**

~~~js
test('危險問題只回傳停機與真人確認，不推薦產品', () => {
  const reply = ZirbaoGuide.answer('鋁管切到一半鋸片裂紋又劇烈震動');
  assert.equal(reply.mode, 'danger');
  assert.equal(reply.cards.length, 0);
  assert.match(reply.message, /先停機/);
  assert.equal(reply.lineUrl, 'https://line.me/ti/p/%40drhawer');
});
~~~

- [ ] **Step 2: 執行測試確認失敗**

Run: node --test zirbao-ai/tests/zirbao-ai.test.js  
Expected: FAIL，因為 app.js 與 ZirbaoGuide 尚未存在。

- [ ] **Step 3: 實作最小安全規則與受控產品索引**

~~~js
const LINE_DOCTOR_URL = 'https://line.me/ti/p/%40drhawer';
const DANGER_KEYWORDS = ['裂紋', '缺齒', '變形', '劇烈震動', '冒煙', '火花'];

function answer(query) {
  const normalized = normalizeText(query);
  if (!normalized) return { mode: 'empty', cards: [] };
  if (DANGER_KEYWORDS.some((word) => normalized.includes(word))) {
    return { mode: 'danger', cards: [], lineUrl: LINE_DOCTOR_URL };
  }
  return { mode: 'guide', cards: findMatches(normalized), lineUrl: LINE_DOCTOR_URL };
}
~~~

- [ ] **Step 4: 加入一般、空白與網址安全測試**

~~~js
test('鋁棒切割導向本站鋁棒頁並補問機台條件', () => {
  const reply = ZirbaoGuide.answer('我要切鋁棒');
  assert.equal(reply.mode, 'guide');
  assert.equal(reply.cards[0].url, 'https://www.hawer-knife.com/ProductDetails.asp?produid=187');
  assert.match(reply.questions.join(' '), /機台/);
});

test('非 HAWER HTTPS 網址不通過驗證', () => {
  assert.equal(ZirbaoGuide.isTrustedHawerUrl('https://example.com'), false);
  assert.equal(ZirbaoGuide.isTrustedHawerUrl('http://www.hawer-knife.com/FAQ.asp'), false);
});
~~~

- [ ] **Step 5: 執行測試並提交**

Run: node --test zirbao-ai/tests/zirbao-ai.test.js  
Expected: PASS。

~~~bash
git add zirbao-ai/app.js zirbao-ai/tests/zirbao-ai.test.js
git commit -m "feat: add zirbao guide engine"
~~~

### Task 2: 製作鋸寶測試素材

**Files:**
- Create: zirbao-ai/assets/zirbao-mascot.png

**Interfaces:**
- Produces: 透明背景 PNG，供 img.zirbao-mascot 使用。

- [ ] **Step 1: 生成透明背景鋸寶測試素材**

使用影像生成工具，提示詞如下：

~~~text
Original cute industrial sawblade doctor mascot for HAWER testing: round friendly character with a silver circular sawblade halo, blue headband, white lab coat, navy blue work suit, small stethoscope, warm smile and waving hand. Clean premium Taiwanese industrial brand illustration, soft 3D toy-like rendering, transparent background, no text, no logos, no watermark.
~~~

- [ ] **Step 2: 視覺檢查並提交素材**

驗證透明背景、無文字、無第三方商標且形象友善；若不符合，重新生成一次。

~~~bash
git add zirbao-ai/assets/zirbao-mascot.png
git commit -m "feat: add zirbao test mascot"
~~~

### Task 3: 實作單頁對話介面

**Files:**
- Create: zirbao-ai/index.html
- Create: zirbao-ai/styles.css
- Modify: zirbao-ai/app.js
- Modify: zirbao-ai/tests/zirbao-ai.test.js

**Interfaces:**
- Consumes: ZirbaoGuide.answer(query) 與 assets/zirbao-mascot.png。
- Produces: initializeZirbaoApp(documentRef)。

- [ ] **Step 1: 寫出 HTML 結構失敗測試**

~~~js
test('HTML 包含對話窗、快速問題、輸入欄與 LINE 入口', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
  assert.match(html, /id="zirbao-chat"/);
  assert.match(html, /data-zirbao-shortcut="如何選擇鋸片？"/);
  assert.match(html, /id="zirbao-query"/);
  assert.match(html, /id="zirbao-line"/);
});
~~~

- [ ] **Step 2: 執行測試確認失敗**

Run: node --test zirbao-ai/tests/zirbao-ai.test.js  
Expected: FAIL，因為 index.html 尚未建立。

- [ ] **Step 3: 建立無障礙頁面與回覆 UI**

~~~html
<main class="zirbao-page">
  <section class="zirbao-hero" aria-label="鋸寶 AI 助手">
    <img class="zirbao-mascot" src="assets/zirbao-mascot.png" alt="鋸寶，鋸片醫生的 AI 小助手">
    <section id="zirbao-chat" class="zirbao-chat" aria-live="polite"></section>
  </section>
</main>
<script src="app.js"></script>
~~~

- [ ] **Step 4: 綁定輸入、快速問題與 LINE 按鈕**

~~~js
function initializeZirbaoApp(documentRef) {
  const input = documentRef.getElementById('zirbao-query');
  documentRef.querySelectorAll('[data-zirbao-shortcut]').forEach((button) => {
    button.addEventListener('click', () => renderReply(button.dataset.zirbaoShortcut));
  });
  documentRef.getElementById('zirbao-send').addEventListener('click', () => renderReply(input.value));
}
~~~

- [ ] **Step 5: 建立 390px 響應式 CSS、測試與提交**

~~~css
@media (max-width: 600px) {
  .zirbao-page { padding: 16px; }
  .zirbao-hero { grid-template-columns: 1fr; }
  .zirbao-mascot { width: min(220px, 58vw); }
}
~~~

Run: node --test zirbao-ai/tests/zirbao-ai.test.js  
Expected: PASS。

~~~bash
git add zirbao-ai/index.html zirbao-ai/styles.css zirbao-ai/app.js zirbao-ai/tests/zirbao-ai.test.js
git commit -m "feat: add zirbao chat interface"
~~~

### Task 4: 預覽、文件與部署驗證

**Files:**
- Create: zirbao-ai/README.md
- Modify: zirbao-ai/tests/zirbao-ai.test.js

**Interfaces:**
- Consumes: 完成的靜態網站與 Node 測試。
- Produces: 可重複的本機預覽、GitHub Pages 與 NAS 搬遷指引。

- [ ] **Step 1: 寫出 README 失敗測試**

~~~js
test('README 說明本機預覽、GitHub Pages 路徑與 NAS 搬遷', () => {
  const readme = fs.readFileSync(path.join(__dirname, '..', 'README.md'), 'utf8');
  assert.match(readme, /python -m http.server/);
  assert.match(readme, /\\/zirbao-ai\\//);
  assert.match(readme, /NAS/);
});
~~~

- [ ] **Step 2: 執行測試確認失敗**

Run: node --test zirbao-ai/tests/zirbao-ai.test.js  
Expected: FAIL，因為 README.md 尚未建立。

- [ ] **Step 3: 撰寫預覽與搬遷說明**

~~~markdown
## 本機預覽

~~~powershell
cd zirbao-ai
python -m http.server 8080
~~~

GitHub Pages 測試路徑為 /zirbao-ai/；確認後可將整個資料夾搬至 NAS 的 HTTPS 網域。
~~~

- [ ] **Step 4: 執行完整驗證並提交**

Run: node --test zirbao-ai/tests/zirbao-ai.test.js  
Expected: PASS。

Run: git diff --check  
Expected: 無輸出。

~~~bash
git add zirbao-ai/README.md zirbao-ai/tests/zirbao-ai.test.js
git commit -m "docs: add zirbao preview guide"
~~~

- [ ] **Step 5: 視覺檢查桌面與 390px**

Run: python -m http.server 8080 --directory zirbao-ai  
Expected: 本機首頁可開啟。

驗證鋸寶、對話窗、四個快速問題、輸入按鈕、產品卡與 LINE 入口可見；390px 寬度無水平捲軸。

### Task 5: GitHub Pages 測試部署

**Files:**
- Modify: GitHub repository branch only；不新增金鑰或部署設定檔。

- [ ] **Step 1: 確認遠端與最後提交**

Run: git remote -v  
Expected: 顯示使用者的 GitHub repository。

Run: git log --oneline -1  
Expected: 顯示測試站最後提交。

- [ ] **Step 2: 推送測試分支，不修改 main**

Run: git push -u origin codex/zirbao-ai-github-test  
Expected: 分支可供檢視。

- [ ] **Step 3: 經使用者核可後才合併與發布**

Run: git switch main && git merge --no-ff codex/zirbao-ai-github-test  
Expected: 僅新增 zirbao-ai 與文件。

Run: git push origin main  
Expected: GitHub Pages 部署 https://wayne983.github.io/SawDoctor-Pro/zirbao-ai/。
