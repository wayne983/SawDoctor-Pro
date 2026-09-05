const assert = require('node:assert/strict');
const test = require('node:test');

const ZirbaoClient = require('../zirbao-client.js');

function fallbackReply(question) {
  return {
    mode: 'guide', message: `本機導覽：${question}`, followUpQuestions: [],
    cards: [{ title: '官方頁', summary: '摘要', url: 'https://www.hawer-knife.com/FAQ.asp' }],
    lineUrl: 'https://line.me/ti/p/%40drhawer'
  };
}

test('client uses local guide when no Apps Script endpoint is configured', async () => {
  const client = ZirbaoClient.createClient({ endpoint: '' }, fallbackReply);
  const reply = await client.sendQuestion('鋁管 355');
  assert.equal(reply.source, 'local-fallback');
  assert.match(reply.cards[0].url, /hawer-knife\.com/);
});

test('client accepts a matching Apps Script callback and renders trusted cards', async () => {
  const client = ZirbaoClient.createClient(
    { endpoint: 'https://script.google.com/macros/s/example/exec' },
    fallbackReply,
    async (payload) => ({
      type: 'zirbao-ai-reply', requestId: payload.requestId, ok: true,
      reply: {
        mode: 'answer', message: '<b>不可以插入 HTML</b>', followUpQuestions: [],
        cards: [
          { title: '官方頁', summary: '摘要', url: 'https://www.hawer-knife.com/FAQ.asp' },
          { title: '外部頁', summary: '不應顯示', url: 'https://example.com/' }
        ],
        lineUrl: 'https://line.me/ti/p/%40drhawer'
      }
    })
  );
  const reply = await client.sendQuestion('切鋁管有毛邊');
  assert.equal(reply.source, 'ai');
  assert.equal(reply.message, '<b>不可以插入 HTML</b>');
  assert.equal(reply.cards.length, 1);
  assert.match(reply.cards[0].url, /^https:\/\/www\.hawer-knife\.com\//);
});

test('client never requests AI for dangerous question', async () => {
  let called = false;
  const client = ZirbaoClient.createClient(
    { endpoint: 'https://script.google.com/macros/s/example/exec' }, fallbackReply,
    async () => { called = true; return {}; },
    () => true,
    () => ({ mode: 'danger', message: '先停機檢查', followUpQuestions: [], cards: [], lineUrl: 'https://line.me/ti/p/%40drhawer' })
  );
  const reply = await client.sendQuestion('鋸片裂紋');
  assert.equal(reply.source, 'local-safety');
  assert.equal(called, false);
});
