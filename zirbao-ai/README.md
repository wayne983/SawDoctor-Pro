# 鋸寶 AI GitHub 測試站

這是獨立的靜態測試網站，不會修改既有鋸片醫生系統或舊 HAWER 官網。

`config.js` 的 `endpoint` 為空時，鋸寶維持本機關鍵字導覽；填入已部署的 Google Apps Script `/exec` 網址後，才會以聊天方式呼叫 AI。API key 僅存放在 Apps Script 的 `OPENAI_API_KEY` 指令碼屬性，絕不可寫入此目錄或 GitHub。

## 功能範圍

- 鋸寶吉祥物與藍白對話式介面。
- 依材料、用途與常見困擾導向 HAWER 官網產品或服務。
- 裂紋、缺齒、變形、劇烈震動、冒煙或火花時，僅提示先停機並轉真人確認。
- 「交給 LINE 鋸片醫生確認」開啟官方 LINE 帳號。

這是初步導引，不會保證特定規格適用，也不會取代真人技師判斷。

## 本機預覽

在專案根目錄執行：

```powershell
python -m http.server 8080 --directory zirbao-ai
```

然後開啟 <http://localhost:8080/>。

## 自動測試

```powershell
node --test zirbao-ai/tests/*.test.js
```

## GitHub Pages 測試

當 `zirbao-ai` 資料夾合併到 GitHub Pages 發布分支後，測試路徑為：

`https://wayne983.github.io/SawDoctor-Pro/zirbao-ai/`

先檢視測試分支，再經確認後才合併至發布分支；不需要將 API 金鑰加入 GitHub。

## 搬遷至 NAS 正式站

確認介面與導引內容後，可將整個 `zirbao-ai` 資料夾上傳至 NAS 的 HTTPS 網域。正式連線應透過網域、HTTPS 憑證與反向代理或安全通道提供服務，不應直接公開 NAS 管理介面。

已建立的 Apps Script 後端部署步驟請看 [`../apps-script/zirbao-ai/DEPLOY.md`](../apps-script/zirbao-ai/DEPLOY.md)。不要把模型金鑰或客戶對話資料放進靜態前端。
