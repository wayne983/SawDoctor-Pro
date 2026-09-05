# 鋸寶 AI 對話引擎設計

## 目標

將 GitHub Pages 上的「鋸寶 AI」從關鍵字導覽升級為聊天式初步問診助手。它必須只引用已核准的鋸片醫生知識與 HAWER 官網公開 FAQ／商品資料；回答採用白話繁體中文，提供相關官方連結，並在資料不足或安全警訊時交由真人技師確認。

第一版的交付範圍是文字聊天、知識檢索、官網商品卡、LINE 轉交與 Google Apps Script 安全後端。它不是自動下單、正式診斷、保證選型或自動更新官網內容的系統。

## 資料邊界

### 可供客戶回答的資料

1. 專案根目錄 `02_症狀資料庫`、`03_材料資料庫`、`04_原因資料庫`、`05_AI追問題庫`、`06_案例資料庫`、`07_解決方案` 中，明確標示為「已核准收錄」或「已驗證」的 Markdown 文件。
2. `06_案例資料庫` 中已匿名化、且狀態不是「待真人確認」的案例；目前 `ST-0001` 因仍待真人確認，不進入客戶版知識。
3. HAWER 官網的公開 [常見問題 Q&A](https://www.hawer-knife.com/FAQ.asp)、鋸片醫學誌與既有產品頁；每一筆 FAQ 或商品知識都保留標題、摘要、原始 HTTPS URL、關鍵字與擷取日期。

### 不得供客戶自動引用的資料

1. `09_待整理資料` 的任何檔案。
2. 標示「待整理」、「待確認」、「待真人確認」或「已停用」的資料。
3. 含客戶識別、報價、聯絡方式或未匿名附件的內容。
4. 只有單一症狀、但沒有材料／機台／參數條件的推論。

## 架構

```text
訪客瀏覽器（GitHub Pages）
  └─ 隱藏表單 POST + iframe 回呼
       └─ Google Apps Script Web App
            ├─ 讀取 OPENAI_API_KEY 指令碼屬性
            ├─ 從 approved-knowledge.json 檢索前幾筆資料
            ├─ 呼叫 OpenAI Responses API
            └─ postMessage 回 GitHub Pages
                  └─ 顯示聊天回覆、官方商品卡與 LINE 連結
```

GitHub Pages 不持有 API 金鑰，也不直接呼叫 OpenAI。Apps Script 使用 `PropertiesService.getScriptProperties()` 讀取 `OPENAI_API_KEY`，以 `UrlFetchApp` 向 Responses API 呼叫 `gpt-5-mini`。模型的輸出必須符合固定 JSON 結構，以避免前端插入未信任 HTML。

因 Google Apps Script 的跨網域限制，前端採用受控的 form POST 到隱藏 iframe；Apps Script 回傳只含 JSON 的 `postMessage`，且只允許 `https://wayne983.github.io` 作為父頁來源。這延續既有鋸片醫生掛號系統的跨網域安全模式。

## 知識整理與檢索

### 可版本控制的知識包

新增 `zirbao-ai/knowledge/approved-knowledge.json`。每筆資料具備下列欄位：

```json
{
  "id": "faq-鋁材切割刀痕",
  "status": "approved",
  "kind": "faq",
  "title": "為什麼鋁材切割會出現刀痕？",
  "summary": "刀痕可能與鋸片、機台精度、參數、夾持和材料條件相關。",
  "keywords": ["鋁材", "刀痕", "切面"],
  "followUpQuestions": ["請提供材料厚度、機台型號與轉速。"],
  "sourceUrl": "https://www.hawer-knife.com/FAQ.asp",
  "sourceLabel": "HAWER 常見問題 Q&A",
  "reviewedAt": "2026-09-05"
}
```

這個 JSON 是客戶版的唯一知識來源。新知識先由本機 Markdown 或官方 FAQ 整理成候選紀錄，再經人工確認後才可把 `status` 設為 `approved` 並納入檔案。

### 檢索方式

Apps Script 對使用者問題與每筆 `keywords`、`title`、`summary` 做 Unicode 正規化與關鍵字計分，只傳送前 5 筆符合資料給模型。若沒有可用資料，模型不得自行補出產品規格，改為說明缺少資料並詢問材料、尺寸／厚度、機台、轉速與目前症狀。

產品卡只可取自 `sourceUrl` 為 `https://www.hawer-knife.com/` 網域的知識紀錄；後端再次驗證 URL，避免模型回傳其他網站或任意連結。

## 對話與安全規則

### 一般回答

系統提示詞要求鋸寶：

- 以溫暖、精簡的繁體中文對話。
- 先重述已知條件，再說明 2 至 4 個「可能」的影響方向，區分鋸片、機台、參數、材料、操作或潤滑。
- 只根據被提供的知識說明；未提供的 RPM、進給、材質、尺寸、齒數、規格與加工結果，必須明說待補充。
- 不使用「一定」、「保證」或「只要更換某規格就會改善」等語句。
- 回傳 1 至 3 筆相關官方資料卡與 1 至 3 個最重要的補問。

### 14 吋薄壁鋁管範例

如果提問同時包含「14 吋」、「薄壁」、「鋁管」，鋸寶可解釋 14 吋通常對應約 355 mm 的外徑方向，並說明薄壁材料需同時看管徑、管厚、夾持、轉速與進刀；它只能在知識包有核准的 `355 × 3.2 × 120T` 規格時才列出該規格，且必須標示為「初步方向，請由真人技師確認內徑與機台條件」。若知識包沒有該核准規格，它只能提供鋁合金用圓鋸片官方卡與補問，不能捏造數字。

### 危險分流

裂紋、連續缺齒、明顯變形、劇烈震動、冒煙或火花一旦出現，後端不呼叫模型、不顯示商品卡。它固定回覆「先停機檢查」，提示保留異常照片並轉到 LINE 鋸片醫生。此規則必須在前端與後端各執行一次。

## 後端介面

Apps Script 接收：

```json
{
  "requestId": "uuid",
  "question": "我有一台 14 吋切斷機，主要裁切薄壁鋁管，有沒有推薦？",
  "history": [
    {"role": "user", "text": "先前的提問"},
    {"role": "assistant", "text": "先前的回答"}
  ]
}
```

它回傳：

```json
{
  "type": "zirbao-ai-reply",
  "requestId": "uuid",
  "ok": true,
  "reply": {
    "mode": "answer",
    "message": "文字回覆，只允許純文字。",
    "followUpQuestions": ["請提供鋁管外徑與壁厚。"],
    "cards": [
      {
        "title": "φ355~610 鋁合金用鋸片",
        "summary": "官方產品頁說明。",
        "url": "https://www.hawer-knife.com/ProductDetails.asp?produid=19"
      }
    ],
    "lineUrl": "https://line.me/ti/p/%40drhawer"
  }
}
```

每次請求的 `question` 上限為 1,000 字元、`history` 最多 6 則、每則最多 1,000 字元。後端驗證 `requestId`、資料型別與字數；超出時回傳可理解的錯誤訊息，不呼叫 OpenAI。後端不把提問內容、API 金鑰或完整模型原始回應寫入公開 GitHub 檔案。

## 前端行為

`zirbao-ai/app.js` 保留現在的本機關鍵字導覽，作為後端未設定、網路錯誤或 Apps Script 拒絕請求時的安全備援。當 `config.js` 內有已部署的 Web App URL 時，送出按鈕改為呼叫後端；畫面顯示「鋸寶正在整理資料…」，收到合法回覆後以 `textContent` 渲染文字、補問與安全網址卡片。

LINE 按鈕保留原網址；危險分流與後端失敗時會加強顯示。聊天紀錄只保留在該瀏覽器分頁的記憶體，不寫入 Local Storage、Cookie 或資料庫。

## 錯誤與隱私

- `OPENAI_API_KEY` 缺少、OpenAI 回傳錯誤或 Apps Script 超時時，前端顯示「目前無法取得 AI 回覆，您可先查看相關頁面或交給 LINE 鋸片醫生確認。」
- 模型回傳非預期 JSON、未核准連結或超長文字時，後端改回安全備援文字與 LINE 連結。
- 不收集姓名、電話、公司、照片或報價；若訪客要真人協助，讓他自行點入既有 LINE 流程。

## 測試與驗收

1. 以 Node.js 測試純函式：文字正規化、危險判斷、知識檢索、受信任 URL 驗證、後端 payload 驗證及模型 JSON 清洗。
2. 測試「鋁管、355」會帶出鋁合金官方產品卡；「14 吋薄壁鋁管」會問管徑、管厚與機台條件，不捏造未核准規格。
3. 測試「裂紋、劇烈震動」不會呼叫 OpenAI，且不顯示商品卡。
4. 測試 Apps Script 的 callback 只對 `https://wayne983.github.io` 送 `postMessage`，不把金鑰或原始錯誤輸出給瀏覽器。
5. 以沒有 API key 的本機模式確認既有關鍵字導覽仍可用；以 Apps Script Test deployment 驗證一般問題、危險問題、網路錯誤與 LINE 轉交。
6. 合併前執行 `node --test zirbao-ai/tests/*.test.js`、`git diff --check`，並在 GitHub Pages 實際輸入一般問題與危險問題驗證。

## 上線流程

1. 將 Apps Script 後端的 `Code.gs`、`Knowledge.gs` 與 `appsscript.json` 貼入新建的「鋸寶 AI 對話後端」專案；`OPENAI_API_KEY` 已存在於其指令碼屬性。
2. 將 Apps Script 部署為 Web App，執行身分選擇部署者，存取權設定為任何人；取得 `/exec` URL。
3. 將 `/exec` URL 填入 GitHub Pages 的 `zirbao-ai/config.js`，合併後由 GitHub Pages 發布。
4. 以真實訪客頁測試上述驗收案例；確認沒有 API 金鑰出現在網頁原始碼或 Git 儲存庫。
5. 只在測試通過後，把舊官網的「問鋸寶 AI」連結正式導到 GitHub Pages 頁面。

## 非目標

- 不將 API key 放入前端、GitHub、LINE 或聊天訊息。
- 不讓模型自行瀏覽網路、直接下單、修改官網、寄送訊息或建立正式診斷單。
- 不把未審核的候選知識、自動爬到的新網頁內容或含客戶資料的案例直接放入客戶版回答。
