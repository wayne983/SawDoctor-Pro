(function (global) {
  'use strict';

  var SITE_HOSTNAME = 'www.hawer-knife.com';
  var LINE_DOCTOR_URL = 'https://line.me/ti/p/%40drhawer';
  var DANGER_KEYWORDS = ['裂紋', '裂痕', '缺齒', '掉齒', '連續缺齒', '變形', '劇烈震動', '異常震動', '冒煙', '火花'];

  function text(value) {
    return typeof value === 'string' ? value.trim() : '';
  }

  function normalizeText(value) {
    return text(value).normalize('NFKC')
      .replace(/[，,。．、；;：:！？!?／/\\|()（）［］【】「」『』<>《》]+/g, ' ')
      .toLowerCase()
      .replace(/\s+/g, ' ')
      .trim();
  }

  function isTrustedHawerUrl(value) {
    try {
      var url = new URL(String(value));
      return url.protocol === 'https:' && url.hostname.toLowerCase() === SITE_HOSTNAME;
    } catch (error) {
      return false;
    }
  }

  function isDangerous(question) {
    var normalized = normalizeText(question);
    return DANGER_KEYWORDS.some(function (keyword) { return normalized.indexOf(normalizeText(keyword)) >= 0; });
  }

  function createSafetyReply() {
    return {
      mode: 'danger',
      message: '出現可能影響安全的異常時，請先停機檢查。此處僅能提供初步導引，請交由鋸片醫生真人技師確認。',
      followUpQuestions: ['請先停止機台運轉。', '請保留鋸片與異常位置照片供技師確認。'],
      cards: [],
      lineUrl: LINE_DOCTOR_URL
    };
  }

  function recordScore(question, record) {
    var normalized = normalizeText(question);
    var score = 0;
    var terms = (record.keywords || []).concat([record.title, record.summary]);
    terms.forEach(function (term) {
      var candidate = normalizeText(term);
      if (candidate && normalized.indexOf(candidate) >= 0) score += candidate === normalizeText(record.title) ? 3 : 1;
    });
    if (/14 ?吋/.test(normalized) && (record.keywords || []).some(function (keyword) { return normalizeText(keyword) === '14 吋' || normalizeText(keyword) === '14吋'; })) score += 2;
    return score;
  }

  function retrieve(question, knowledge) {
    if (!Array.isArray(knowledge)) return [];
    return knowledge
      .map(function (record, index) { return { record: record, index: index, score: recordScore(question, record) }; })
      .filter(function (item) { return item.record && item.record.status === 'approved' && isTrustedHawerUrl(item.record.sourceUrl) && item.score > 0; })
      .sort(function (left, right) { return right.score - left.score || left.index - right.index; })
      .slice(0, 5)
      .map(function (item) { return item.record; });
  }

  function cardsFromRecords(records) {
    return records.slice(0, 3).map(function (record) {
      return { id: record.id, title: record.title, summary: record.summary, url: record.sourceUrl };
    });
  }

  function fallbackReply(question, knowledge) {
    if (isDangerous(question)) return createSafetyReply();
    var records = retrieve(question, knowledge);
    var questions = records.flatMap(function (record) { return record.followUpQuestions || []; }).filter(Boolean).slice(0, 3);
    return {
      mode: 'guide',
      message: records.length
        ? '我先依您提供的條件整理初步方向；實際規格仍要確認材料、機台與現場條件，不能只憑一句話決定。'
        : '我還需要多一點資料，才能幫您縮小方向。請提供材料、尺寸或厚度、機台與目前遇到的狀況。',
      followUpQuestions: questions.length ? questions : ['請提供使用的機台、工件尺寸／厚度與切割用途。'],
      cards: cardsFromRecords(records),
      lineUrl: LINE_DOCTOR_URL
    };
  }

  function validateRequest(payload) {
    if (!payload || typeof payload !== 'object') return { ok: false, error: '提問資料格式錯誤' };
    if (!/^[A-Za-z0-9_-]{1,128}$/.test(String(payload.requestId || ''))) return { ok: false, error: '提問識別碼格式錯誤' };
    if (!text(payload.question) || text(payload.question).length > 1000) return { ok: false, error: '問題內容需介於 1 至 1000 字元' };
    if (payload.history !== undefined && !Array.isArray(payload.history)) return { ok: false, error: '歷史訊息格式錯誤' };
    if (Array.isArray(payload.history) && payload.history.length > 6) return { ok: false, error: '歷史訊息不可超過 6 則' };
    var invalidHistory = (payload.history || []).some(function (item) {
      return !item || (item.role !== 'user' && item.role !== 'assistant') || !text(item.text) || text(item.text).length > 1000;
    });
    return invalidHistory ? { ok: false, error: '歷史訊息內容格式錯誤' } : { ok: true };
  }

  function sanitizeModelReply(candidate, knowledge) {
    var byId = {};
    (knowledge || []).forEach(function (record) { if (record && record.status === 'approved' && isTrustedHawerUrl(record.sourceUrl)) byId[record.id] = record; });
    var rawCards = candidate && Array.isArray(candidate.cards) ? candidate.cards : [];
    var seen = {};
    var cards = rawCards.map(function (item) { return byId[item && item.id]; })
      .filter(function (record) { return record && !seen[record.id] && (seen[record.id] = true); })
      .slice(0, 3);
    var questions = candidate && Array.isArray(candidate.followUpQuestions) ? candidate.followUpQuestions : [];
    return {
      mode: 'answer',
      message: text(candidate && candidate.message).slice(0, 1800) || '我先幫您整理目前可確認的方向，仍需要補充條件才能進一步判斷。',
      followUpQuestions: questions.map(text).filter(Boolean).slice(0, 3),
      cards: cardsFromRecords(cards),
      lineUrl: LINE_DOCTOR_URL
    };
  }

  var api = Object.freeze({
    SITE_HOSTNAME: SITE_HOSTNAME,
    LINE_DOCTOR_URL: LINE_DOCTOR_URL,
    normalizeText: normalizeText,
    isTrustedHawerUrl: isTrustedHawerUrl,
    isDangerous: isDangerous,
    createSafetyReply: createSafetyReply,
    retrieve: retrieve,
    fallbackReply: fallbackReply,
    validateRequest: validateRequest,
    sanitizeModelReply: sanitizeModelReply
  });

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.ZirbaoCore = api;
})(typeof window !== 'undefined' ? window : globalThis);
