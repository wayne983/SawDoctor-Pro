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

test('iframe transport accepts the Apps Script sandbox subdomain callback', async () => {
  let messageHandler;
  const frame = { name: 'zirbao-ai-frame' };
  const documentRef = {
    getElementById: () => frame,
    createElement: () => ({ style: {}, append() {}, remove() {}, submit() {} }),
    body: { append() {} }
  };
  const windowRef = {
    addEventListener: (type, handler) => { if (type === 'message') messageHandler = handler; },
    setTimeout: () => 1,
    clearTimeout: () => {}
  };
  const transport = ZirbaoClient.createIframeTransport(documentRef, windowRef);
  const pending = transport({ requestId: 'sandbox-callback' }, 'https://script.google.com/macros/s/example/exec');
  messageHandler({
    origin: 'https://n-example-script.googleusercontent.com',
    data: { type: 'zirbao-ai-reply', requestId: 'sandbox-callback', ok: true, reply: {} }
  });
  const reply = await Promise.race([
    pending,
    new Promise((resolve) => setTimeout(() => resolve(null), 20))
  ]);
  assert.ok(reply);
  assert.equal(reply.ok, true);
});

test('iframe transport accepts an opaque Apps Script sandbox callback only for the pending request', async () => {
  let messageHandler;
  const frame = { name: 'zirbao-ai-frame' };
  const documentRef = {
    getElementById: () => frame,
    createElement: () => ({ style: {}, append() {}, remove() {}, submit() {} }),
    body: { append() {} }
  };
  const windowRef = {
    addEventListener: (type, handler) => { if (type === 'message') messageHandler = handler; },
    setTimeout: () => 1,
    clearTimeout: () => {}
  };
  const transport = ZirbaoClient.createIframeTransport(documentRef, windowRef);
  const pending = transport({ requestId: 'opaque-callback' }, 'https://script.google.com/macros/s/example/exec');
  messageHandler({
    origin: 'null',
    data: { type: 'zirbao-ai-reply', requestId: 'other-request', ok: true, reply: {} }
  });
  messageHandler({
    origin: 'null',
    data: { type: 'zirbao-ai-reply', requestId: 'opaque-callback', ok: true, reply: {} }
  });
  const reply = await Promise.race([
    pending,
    new Promise((resolve) => setTimeout(() => resolve(null), 20))
  ]);
  assert.ok(reply);
  assert.equal(reply.ok, true);
});
