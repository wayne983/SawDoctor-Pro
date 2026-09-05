const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const { ZirbaoGuide } = require('../app.js');

test('危險問題只回傳停機與真人確認，不推薦產品', () => {
  const reply = ZirbaoGuide.answer('鋁管切到一半鋸片裂紋又劇烈震動');

  assert.equal(reply.mode, 'danger');
  assert.equal(reply.cards.length, 0);
  assert.match(reply.message, /先停機/);
  assert.equal(reply.lineUrl, 'https://line.me/ti/p/%40drhawer');
});

test('鋁棒切割導向本站鋁棒頁並補問機台條件', () => {
  const reply = ZirbaoGuide.answer('我要切鋁棒');

  assert.equal(reply.mode, 'guide');
  assert.equal(reply.cards[0].url, 'https://www.hawer-knife.com/ProductDetails.asp?produid=187');
  assert.match(reply.questions.join(' '), /機台/);
});

test('空白問題要求補充條件且不推薦產品', () => {
  const reply = ZirbaoGuide.answer('   ');

  assert.equal(reply.mode, 'empty');
  assert.equal(reply.cards.length, 0);
  assert.match(reply.questions.join(' '), /材料/);
});

test('非 HAWER HTTPS 網址不通過驗證', () => {
  assert.equal(ZirbaoGuide.isTrustedHawerUrl('https://example.com'), false);
  assert.equal(ZirbaoGuide.isTrustedHawerUrl('http://www.hawer-knife.com/FAQ.asp'), false);
  assert.equal(ZirbaoGuide.isTrustedHawerUrl('https://www.hawer-knife.com/FAQ.asp'), true);
});

test('HTML 包含對話窗、快速問題、輸入欄與 LINE 入口', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');

  assert.match(html, /id="zirbao-chat"/);
  assert.match(html, /data-zirbao-shortcut="如何選擇鋸片？"/);
  assert.match(html, /id="zirbao-query"/);
  assert.match(html, /id="zirbao-line"/);
  assert.match(html, /<script src="config\.js"><\/script>/);
  assert.match(html, /id="zirbao-ai-frame"/);
  assert.match(html, /zirbao-client\.js/);
});

test('HTML 使用去背後的可愛鋸寶素材，不使用測試版吉祥物', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');

  assert.match(html, /assets\/zirbao-mascot-official-cutout\.png/);
  assert.doesNotMatch(html, /assets\/zirbao-mascot\.png/);
});

test('前端只用文字節點渲染，且不包含 API Key', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
  assert.match(source, /textContent/);
  assert.doesNotMatch(source, /OPENAI_API_KEY/);
});

test('README 說明本機預覽、GitHub Pages 路徑與 NAS 搬遷', () => {
  const readme = fs.readFileSync(path.join(__dirname, '..', 'README.md'), 'utf8');

  assert.match(readme, /python -m http.server/);
  assert.match(readme, /\/zirbao-ai\//);
  assert.match(readme, /NAS/);
});
