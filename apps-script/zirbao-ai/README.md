# 鋸寶 AI 對話後端

此目錄可直接複製到使用者新建的 Google Apps Script「鋸寶 AI 對話後端」專案。

- `Code.gs`：安全處理提問、危險分流、OpenAI Responses API 呼叫與 iframe 回呼。
- `Core.gs`：文字正規化、知識檢索、網址驗證與模型回覆清洗。
- `Knowledge.gs`：已核准的客戶版知識快照，由 `tools/export-zirbao-ai-knowledge.js` 從 `zirbao-ai/knowledge/approved-knowledge.json` 產生。
- `appsscript.json`：僅要求外部 HTTP 請求權限。

完整操作請看 [DEPLOY.md](DEPLOY.md)。
