const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(
  path.join(__dirname, '..', 'hawer-keyword-navigator.embed.html'),
  'utf8'
);
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const sandbox = { module: { exports: {} }, exports: {} };
vm.runInNewContext(script, sandbox);
const { HAWERKeywordNavigator } = sandbox.module.exports;

test('鋁棒切割導向大外徑鋁用頁面', () => {
  const result = HAWERKeywordNavigator.search('鋁棒切割');

  assert.equal(result.results[0].id, 'aluminum-large');
});

test('研磨關鍵字導向研磨維修', () => {
  const result = HAWERKeywordNavigator.search('鋸片研磨');

  assert.equal(result.results[0].id, 'repair');
});

test('危險詞優先顯示停機與診療導流', () => {
  const result = HAWERKeywordNavigator.search('鋸片裂紋而且劇烈震動');

  assert.equal(result.isDanger, true);
  assert.equal(result.results[0].id, 'diagnosis');
  assert.match(result.guidance, /停機檢查/);
});
