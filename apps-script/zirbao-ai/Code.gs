var ZirbaoAiBackend = (function () {
  var CONFIG = Object.freeze({
    allowedParentOrigin: 'https://wayne983.github.io',
    lineUrl: 'https://line.me/ti/p/%40drhawer',
    model: 'gpt-5-mini',
    endpoint: 'https://api.openai.com/v1/responses'
  });

  function unavailableReply_(detail) {
    return {
      mode: 'unavailable',
      message: detail || '目前無法取得 AI 回覆，您可先查看相關頁面或交給 LINE 鋸片醫生確認。',
      followUpQuestions: ['請提供材料、尺寸／厚度、機台與目前遇到的狀況。'],
      cards: [],
      lineUrl: CONFIG.lineUrl,
      needsDiagnosis: true,
      diagnosisUrl: ZirbaoAiCore.DIAGNOSIS_URL
    };
  }

  function safeResult_(requestId, reply, ok) {
    return { type: 'zirbao-ai-reply', requestId: String(requestId || ''), ok: ok !== false, reply: reply };
  }

  function approvedContext_(question) {
    return ZirbaoAiCore.retrieve(question, ZIRBAO_APPROVED_KNOWLEDGE).map(function (record) {
      return {
        id: record.id,
        status: record.status,
        title: record.title,
        summary: record.summary,
        keywords: record.keywords,
        followUpQuestions: record.followUpQuestions,
        sourceUrl: record.sourceUrl
      };
    });
  }

  function instructions_() {
    return [
      '你是 HAWER 鋸片醫生的鋸寶 AI 小助手，使用繁體中文，以親切、精簡的對話回答。',
      '只可依照本次提供的「核准知識」說明，不可使用未提供的產品規格、數值或網址。',
      '先重述已知條件；資訊不足時，列出 1 至 3 個最重要的補問。',
      '若使用者已提供材料與尺寸，絕不可再問同一資料；應先給可供技師評估的鋸片方向，再只補問機台型式、主軸 RPM 與現有鋸片規格。',
      '不鏽鋼方管已提供尺寸但缺機台或 RPM 時，可說高速鋼鋸片或 14 吋鐵工鋸片屬於待評估方向；必須說明是否適用取決於機台、可裝尺寸與轉速，不可直接指定規格。',
      '不可根據單一症狀確診；將可能影響分成鋸片、機台、參數、材料、操作或潤滑方向。',
      '不可說保證、一定、必定改善；不可自行編造 RPM、進給、尺寸、齒數、齒型或規格。',
      '卡片只能填入核准知識中的 id；不要輸出 URL、HTML、Markdown 或任何其他欄位。',
      '若使用者提到 14 吋薄壁鋁管，只能說 14 吋通常是約 355 mm 的方向，仍需確認內徑、管徑、壁厚、機台與轉速；沒有核准規格時不得寫出 120T 或其他規格。',
      '回覆必須完全符合指定 JSON schema。'
    ].join('\n');
  }

  function responseSchema_() {
    return {
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
    };
  }

  function extractOutputText_(body) {
    var parsed = JSON.parse(body);
    var output = Array.isArray(parsed.output) ? parsed.output : [];
    for (var index = 0; index < output.length; index += 1) {
      var content = Array.isArray(output[index].content) ? output[index].content : [];
      for (var contentIndex = 0; contentIndex < content.length; contentIndex += 1) {
        if (content[contentIndex].type === 'output_text' && content[contentIndex].text) return content[contentIndex].text;
      }
    }
    throw new Error('OpenAI 回覆缺少文字內容');
  }

  function callOpenAi_(payload, context) {
    var history = (payload.history || []).map(function (item) {
      return { role: item.role, content: item.text };
    });
    history.push({
      role: 'user',
      content: '使用者問題：' + payload.question + '\n\n核准知識：\n' + JSON.stringify(context)
    });
    var request = {
      model: CONFIG.model,
      store: false,
      instructions: instructions_(),
      input: history,
      text: { format: responseSchema_() }
    };
    var apiKey = PropertiesService.getScriptProperties().getProperty('OPENAI_API_KEY');
    if (!apiKey) throw new Error('缺少 OPENAI_API_KEY');
    var response = UrlFetchApp.fetch(CONFIG.endpoint, {
      method: 'post',
      contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + apiKey },
      payload: JSON.stringify(request),
      muteHttpExceptions: true
    });
    if (response.getResponseCode() < 200 || response.getResponseCode() >= 300) throw new Error('OpenAI 請求未成功');
    return JSON.parse(extractOutputText_(response.getContentText()));
  }

  function answer_(payload) {
    var validation = ZirbaoAiCore.validateRequest(payload);
    if (!validation.ok) return safeResult_(payload && payload.requestId, unavailableReply_(validation.error), false);
    if (ZirbaoAiCore.isDangerous(payload.question)) return safeResult_(payload.requestId, ZirbaoAiCore.createSafetyReply(), true);
    var context = approvedContext_(payload.question);
    if (!context.length) return safeResult_(payload.requestId, ZirbaoAiCore.fallbackReply(payload.question, ZIRBAO_APPROVED_KNOWLEDGE), true);
    if (!PropertiesService.getScriptProperties().getProperty('OPENAI_API_KEY')) return safeResult_(payload.requestId, unavailableReply_(), false);
    try {
      var candidate = callOpenAi_(payload, context);
      return safeResult_(payload.requestId, ZirbaoAiCore.sanitizeModelReply(candidate, context, ZirbaoAiCore.needsDiagnosis(payload.question)), true);
    } catch (error) {
      return safeResult_(payload.requestId, unavailableReply_(), false);
    }
  }

  function callbackOutput_(result) {
    var json = JSON.stringify(result).replace(/</g, '\\u003c');
    return HtmlService.createHtmlOutput('<script>top.postMessage(' + json + ',' + JSON.stringify(CONFIG.allowedParentOrigin) + ');</script>')
      .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
  }

  function doPost(e) {
    var payload;
    try {
      payload = JSON.parse(e && e.parameter ? e.parameter.payload || '{}' : '{}');
    } catch (error) {
      return callbackOutput_(safeResult_('', unavailableReply_('提問資料格式錯誤'), false));
    }
    return callbackOutput_(answer_(payload));
  }

  return Object.freeze({ answer_: answer_, callbackOutput_: callbackOutput_, doPost: doPost });
})();

function doPost(e) {
  return ZirbaoAiBackend.doPost(e);
}
