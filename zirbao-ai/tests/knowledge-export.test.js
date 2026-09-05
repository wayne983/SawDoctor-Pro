const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const repoRoot = path.resolve(__dirname, '..', '..');
const knowledgePath = path.join(repoRoot, 'zirbao-ai', 'knowledge', 'approved-knowledge.json');
const exporterPath = path.join(repoRoot, 'tools', 'export-zirbao-ai-knowledge.js');
const outputPath = path.join(repoRoot, 'apps-script', 'zirbao-ai', 'Knowledge.gs');

test('approved knowledge only contains approved records and trusted HAWER URLs', () => {
  const records = JSON.parse(fs.readFileSync(knowledgePath, 'utf8'));
  assert.ok(records.length >= 10);
  for (const record of records) {
    assert.equal(record.status, 'approved');
    assert.match(record.sourceUrl, /^https:\/\/www\.hawer-knife\.com\//);
    assert.ok(Array.isArray(record.keywords) && record.keywords.length > 0);
    assert.ok(Array.isArray(record.followUpQuestions) && record.followUpQuestions.length > 0);
  }
});

test('knowledge exporter creates a valid Apps Script literal without unsafe characters', () => {
  execFileSync(process.execPath, [exporterPath], { cwd: repoRoot });
  const generated = fs.readFileSync(outputPath, 'utf8');
  assert.match(generated, /^var ZIRBAO_APPROVED_KNOWLEDGE = /);
  assert.doesNotMatch(generated, /<\/script/i);
  const literal = generated
    .replace(/^var ZIRBAO_APPROVED_KNOWLEDGE = /, '')
    .replace(/;\s*$/, '');
  assert.ok(JSON.parse(literal).length >= 10);
});
