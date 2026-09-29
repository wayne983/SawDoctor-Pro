const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.resolve(__dirname, '..');
const inputPath = path.join(repoRoot, 'zirbao-ai', 'knowledge', 'approved-knowledge.json');
const outputPath = path.join(repoRoot, 'apps-script', 'zirbao-ai', 'Knowledge.gs');
const trustedPrefix = 'https://www.hawer-knife.com/';

function validateRecord(record) {
  if (!record || record.status !== 'approved') throw new Error('知識條目必須為 approved');
  if (!String(record.sourceUrl || '').startsWith(trustedPrefix)) throw new Error('知識條目必須使用 HAWER HTTPS 網址');
  if (!Array.isArray(record.keywords) || !record.keywords.length) throw new Error('知識條目缺少 keywords');
  if (!Array.isArray(record.followUpQuestions) || !record.followUpQuestions.length) throw new Error('知識條目缺少 followUpQuestions');
  if (JSON.stringify(record).toLowerCase().includes('<script')) throw new Error('知識條目含有不允許的 script 文字');
}

function exportKnowledge() {
  const records = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
  if (!Array.isArray(records) || records.length < 10) throw new Error('核准知識至少需要 10 筆');
  records.forEach(validateRecord);
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, `var ZIRBAO_APPROVED_KNOWLEDGE = ${JSON.stringify(records, null, 2)};\n`, 'utf8');
}

exportKnowledge();
