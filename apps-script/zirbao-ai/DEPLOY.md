# 鋸寶 AI Apps Script 部署指南

本目錄提供新建「鋸寶 AI 對話後端」Google Apps Script 專案所需的後端程式。它與既有的鋸片醫生掛號系統分開，不會修改原本的問診或報價流程。

## 部署前確認

1. 在 Apps Script 專案的「專案設定」→「指令碼屬性」確認已有 `OPENAI_API_KEY`。
2. 該屬性的值是 OpenAI API key；不要把它貼進任何 `.gs`、HTML、GitHub、截圖或聊天訊息。
3. 在同一個 Apps Script 專案建立或覆蓋以下檔案：

   - `Code.gs`：複製本目錄的 `Code.gs` 全部內容。
   - `Core.gs`：複製本目錄的 `Core.gs` 全部內容。
   - `Knowledge.gs`：複製本目錄的 `Knowledge.gs` 全部內容。
   - `appsscript.json`：在 Apps Script「專案設定」勾選顯示 manifest 檔案後，將內容更新為本目錄版本。

## 發布 Web App

1. 按右上「部署」→「新增部署」。
2. 類型選「網頁應用程式」。
3. 「執行身分」選部署者本人。
4. 「誰可以存取」選**任何人**。
5. 按部署；第一次會要求授權外部 HTTP 要求，允許即可。
6. 複製部署完成畫面的「網頁應用程式」網址。它必須以 `/exec` 結尾，例如：

```text
https://script.google.com/macros/s/部署識別碼/exec
```

請只保存 `/exec` 網址；它不是 API key，可以提供給網站程式設定。

## 連到 GitHub Pages

打開儲存庫中的 `zirbao-ai/config.js`，把空字串改為 `/exec` 網址：

```js
window.ZIRBAO_AI_CONFIG = Object.freeze({
  endpoint: 'https://script.google.com/macros/s/部署識別碼/exec'
});
```

提交後，GitHub Pages 的 `https://wayne983.github.io/SawDoctor-Pro/zirbao-ai/` 就會改用 AI 聊天。`config.js` 不包含 API key。

## 驗收案例

1. 問「14 吋切斷機裁切薄壁鋁管，有沒有推薦？」：應得到聊天式初步方向、要求管徑／壁厚／機台條件，並附鋁合金官方產品卡；不應在未核准資料下宣稱特定齒數必定適用。
2. 問「鋸片裂紋又劇烈震動」：應立即顯示先停機檢查、LINE 真人確認，且沒有商品卡。
3. 問無關鍵字的問題：應請使用者補充材料、尺寸／厚度、機台與症狀，而非捏造回答。
4. 按「交給 LINE 鋸片醫生確認」：應開啟既有 LINE 官方連結。

## 回滾方式

若 Apps Script 尚未部署完成或 AI 回覆異常，把 `zirbao-ai/config.js` 的 `endpoint` 改回空字串：

```js
window.ZIRBAO_AI_CONFIG = Object.freeze({ endpoint: '' });
```

發布後鋸寶會立即回到原本的本機關鍵字導覽。不要因為回滾而刪除 `OPENAI_API_KEY`；除非您判斷金鑰可能外洩，才在 OpenAI Platform 撤銷並重新建立。
