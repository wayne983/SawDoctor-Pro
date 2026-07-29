const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');

assert.match(
  html,
  /appendList\(panel,'安全警示',result\.safetyWarnings\)/,
  'assessment should render safety warnings'
);
assert.match(
  html,
  /if\(result\.requiresHumanReview\)\{[\s\S]*?assessment-registration-button[\s\S]*?#advanced-section/,
  'human-review assessment should route to registration before LINE'
);
assert.match(
  html,
  /補充資料並完成掛號/,
  'human-review action should explain the registration step'
);
assert.match(
  html,
  /result\.ok===true&&result\.registrationNumber/,
  'registration success should require an acknowledged backend number'
);


assert.match(html, /<div class="intake-column">/, 'intake cards should have a mobile-order wrapper');
assert.match(
  html,
  /@media\(max-width:820px\)\{[\s\S]*?\.layout\{display:flex;flex-direction:column\}[\s\S]*?\.intake-column\{display:contents\}[\s\S]*?\.intake-column>\.card:first-child\{order:1\}[\s\S]*?\.result-column\{position:static;order:2\}[\s\S]*?\.advanced-card\{order:3\}[\s\S]*?\.line-card\{order:4\}/,
  'mobile flow should show quick form, assessment, advanced form, then LINE actions'
);

assert.match(
  html,
  /renderAssessment\(assessment\);if\(assessment\.level==='danger'\)renderRecommendation\(null\)/,
  'danger assessment should hide product recommendations'
);

const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
assert.equal(scripts.length, 2, 'page should contain the core and application scripts');
scripts.forEach((script, index) => assert.doesNotThrow(
  () => new vm.Script(script[1]),
  `script ${index + 1} should have valid JavaScript syntax`
));

assert.match(
  html,
  /\.assessment-registration-button\{width:100%;margin-top:16px\}/,
  'assessment registration button should be full-width and clearly separated'
);

assert.match(html, /data-issue="尺寸不符合／切不到"/, 'size issue choice should be available');
assert.match(html, /id="larger-blade-fit"/, 'larger-blade fit field should be available');
assert.match(html, /id="clearance-mm"/, 'minimum clearance field should be available');
assert.match(html, /鋸片醫生希望您能提供/, 'follow-up heading should use SawDoctor wording');
assert.match(html, /請追加補充/, 'missing-data heading should request an addition');
assert.match(
  html,
  /assessment-panel'\)\.scrollIntoView\(\{behavior:'smooth',block:'start'\}\)/,
  'quick assessment should scroll to the top of the diagnosis card'
);

for (const copy of [
  '您已成功掛號',
  '掛號號碼',
  '複製掛號編號',
  '醫生會親自為您診斷',
  '掛號尚未完成，資料未確認寄出'
]) {
  assert.ok(html.includes(copy), `registration UI should include ${copy}`);
}
assert.doesNotMatch(html, /id="message-preview"/, 'customer page should not display full consultation text');
assert.match(html, /id="registration-number"/, 'success card should expose the registration number');
assert.match(html, /id="copy-registration"/, 'success card should include a registration-copy button');
assert.match(html, /function createRequestId\(\)/, 'submission should create an idempotency key');
assert.match(html, /event\.source!==submissionFrame\.contentWindow/, 'callback should be bound to its submission iframe');
assert.match(html, /event\.data\.requestId!==requestId/, 'callback should match the expected request ID');
assert.match(html, /field\.value=JSON\.stringify\(\{\.\.\.payload,requestId\}\)/, 'submission should send the request ID with the payload');
console.log('SawDoctor UI tests passed');
