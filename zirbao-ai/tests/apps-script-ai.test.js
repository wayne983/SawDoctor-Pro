const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const repoRoot = path.resolve(__dirname, '..', '..');
const appsRoot = path.join(repoRoot, 'apps-script', 'zirbao-ai');

function validOpenAiResponse() {
  return JSON.stringify({
    output: [{
      type: 'message',
      content: [{
        type: 'output_text',
        text: JSON.stringify({
          mode: 'answer',
          message: '依您描述，我先整理鋁管切割的初步方向。',
          followUpQuestions: ['請提供鋁管壁厚。'],
          cards: [{ id: 'product-aluminum-355-610' }]
        })
      }]
    }]
  });
}

function loadAppsScript(properties, responseBody) {
  const fetchCalls = [];
  const context = {
    console,
    JSON,
    Array,
    Object,
    String,
    RegExp,
    PropertiesService: { getScriptProperties: () => ({ getProperty: (key) => properties[key] || '' }) },
    UrlFetchApp: {
      fetch: (url, options) => {
        fetchCalls.push({ url, ...options });
        return { getResponseCode: () => 200, getContentText: () => responseBody || validOpenAiResponse() };
      }
    },
    HtmlService: {
      XFrameOptionsMode: { ALLOWALL: 'ALLOWALL' },
      createHtmlOutput: (html) => ({ setXFrameOptionsMode: () => ({ html }) })
    }
  };
  vm.createContext(context);
  ['Core.gs', 'Knowledge.gs', 'Code.gs'].forEach((file) => vm.runInContext(fs.readFileSync(path.join(appsRoot, file), 'utf8'), context, { filename: file }));
  context.fetchCalls = fetchCalls;
  return context;
}

test('danger reply does not call OpenAI', () => {
  const context = loadAppsScript({ OPENAI_API_KEY: 'test-key' });
  const result = context.ZirbaoAiBackend.answer_({ requestId: 'r-1', question: '鋸片裂紋而且劇烈震動', history: [] });
  assert.equal(result.ok, true);
  assert.equal(result.reply.mode, 'danger');
  assert.equal(context.fetchCalls.length, 0);
});

test('missing API key returns a safe unavailable message', () => {
  const context = loadAppsScript({});
  const result = context.ZirbaoAiBackend.answer_({ requestId: 'r-2', question: '切鋁管有毛邊', history: [] });
  assert.equal(result.ok, false);
  assert.match(result.reply.message, /無法取得 AI 回覆/);
});

test('general question sends only retrieved approved knowledge to Responses API', () => {
  const context = loadAppsScript({ OPENAI_API_KEY: 'test-key' });
  const result = context.ZirbaoAiBackend.answer_({ requestId: 'r-3', question: '14 吋切斷機裁切薄壁鋁管', history: [] });
  const request = JSON.parse(context.fetchCalls[0].payload);
  assert.equal(request.model, 'gpt-5-mini');
  assert.match(JSON.stringify(request), /product-aluminum-355-610/);
  assert.doesNotMatch(JSON.stringify(request), /OPENAI_API_KEY/);
  assert.equal(result.reply.cards[0].url, 'https://www.hawer-knife.com/ProductDetails.asp?produid=19');
});

test('callback output targets only the public GitHub Pages origin', () => {
  const context = loadAppsScript({ OPENAI_API_KEY: 'test-key' });
  const output = context.ZirbaoAiBackend.callbackOutput_({ type: 'zirbao-ai-reply', requestId: 'r-4', ok: true });
  assert.match(output.html, /https:\/\/wayne983\.github\.io/);
  assert.doesNotMatch(output.html, /test-key/);
});
