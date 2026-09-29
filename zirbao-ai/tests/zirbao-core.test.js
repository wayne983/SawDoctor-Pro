const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const ZirbaoCore = require('../zirbao-core.js');
const knowledge = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'knowledge', 'approved-knowledge.json'), 'utf8'));

test('dangerous question bypasses retrieval and returns only stop guidance', () => {
  const result = ZirbaoCore.createSafetyReply('切割時劇烈震動又有火花');
  assert.equal(result.mode, 'danger');
  assert.deepEqual(result.cards, []);
  assert.match(result.message, /先停機檢查/);
});

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

test('不鏽鋼方管已給尺寸但缺機台與轉速時，提供初步方向並導向診療填寫', () => {
  const reply = ZirbaoCore.fallbackReply('請問鋸不鏽鋼方管 50*50*2mm 推薦', knowledge);
  assert.match(reply.message, /高速鋼鋸片/);
  assert.match(reply.message, /14 吋鐵工鋸片/);
  assert.ok(reply.followUpQuestions.some((item) => /機台/.test(item)));
  assert.ok(reply.followUpQuestions.some((item) => /轉速|RPM/.test(item)));
  assert.equal(reply.needsDiagnosis, true);
  assert.match(reply.diagnosisUrl, /productscatid=833957866333/);
});

test('機台與轉速已提供時不強制導向診療填寫', () => {
  const reply = ZirbaoCore.fallbackReply('不鏽鋼方管 50*50*2mm，使用冷鋸機，主軸轉速 120 RPM', knowledge);
  assert.equal(reply.needsDiagnosis, false);
  assert.equal(reply.diagnosisUrl, '');
});

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

test('request validation rejects excessive history and unsafe payload types', () => {
  const result = ZirbaoCore.validateRequest({
    requestId: 'r-1', question: '切鋁管', history: new Array(7).fill({ role: 'user', text: 'x' })
  });
  assert.equal(result.ok, false);
  assert.match(result.error, /歷史/);
});
