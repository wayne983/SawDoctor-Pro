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
assert.match(html, /data-issue="切割抖動"/, 'cutting jitter choice should be available');
assert.doesNotMatch(html, /data-issue="暫無困擾"/, 'no-problem choice should be removed');
assert.doesNotMatch(html, /data-cut="不確定"/, 'uncertain cut direction should be removed');
assert.match(html, /fieldset[^>]*aria-labelledby="saw-action-label"/);
for (const action of [
  '由上而下（下壓式切削）',
  '由下而上（昇降式切削）',
  '左右／前後切割（行進式切削）'
]) {
  assert.ok(html.includes(`data-saw-action="${action}"`), `saw action choices should include ${action}`);
}
assert.match(html, /sawAction:selected\(sawActionButtons,'aria-checked'\)\[0\]\?\?''/);
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
  '請進到診間看診',
  '進入官方 LINE 診間看診',
  '掛號尚未完成，資料未確認寄出'
]) {
  assert.ok(html.includes(copy), `registration UI should include ${copy}`);
}
assert.doesNotMatch(html, /id="message-preview"/, 'customer page should not display full consultation text');
assert.match(html, /id="registration-number"/, 'success card should expose the registration number');
assert.match(html, /id="copy-registration"/, 'success card should include a registration-copy button');
assert.match(html, /function createRequestId\(\)/, 'submission should create an idempotency key');
assert.match(html, /function isTrustedRegistrationOrigin\(origin\)/, 'callback should validate the Google Apps Script message origin');
assert.doesNotMatch(html, /event\.source!==submissionFrame\.contentWindow/, 'nested Apps Script callbacks should not be rejected by the outer iframe source');
assert.match(html, /event\.data\.requestId!==requestId/, 'callback should match the expected request ID');
assert.match(html, /field\.value=JSON\.stringify\(\{\.\.\.payload,requestId\}\)/, 'submission should send the request ID with the payload');
assert.match(html, /id="machine-type" name="machineType"/);
for (const type of ['木工圓鋸機', '鋁用', '鐵工', '電動木工']) {
  assert.ok(html.includes(`<option value="${type}">${type}</option>`), `machine type list should include ${type}`);
}
assert.match(html, /id="machine-brand" name="machineBrand" disabled/);
assert.match(html, /id="machine-brand-other-field"[^>]*hidden/);
assert.match(html, /id="machine-brand-other" name="machineBrandOther"/);
assert.match(html, /id="machine-model" name="machineModel"/);
assert.match(
  html,
  /<label for="brand">鋸片品牌（自行填寫）<\/label><input id="brand" name="brand">/,
  'blade brand should remain a free-text field with clearer copy'
);
assert.match(html, /machineType:\$\('machine-type'\)\.value/);
assert.match(html, /machineBrand:\$\('machine-brand'\)\.value/);
assert.match(
  html,
  /machineBrandOther:\$\('machine-brand'\)\.value==='其他'\?\$\('machine-brand-other'\)\.value\.trim\(\):''/
);
assert.match(html, /function syncMachineBrandOther\(\)/);
assert.match(html, /function syncMachineBrandOptions\(\)/);
assert.match(html, /brandSelect\.disabled=!machineType/);
assert.match(html, /brandSelect\.replaceChildren\(new Option\('請先選擇機台種類',''\)\)/);
assert.match(html, /new Option\(brand==='其他'\?'其它':brand,brand\)/);
assert.match(html, /brandSelect\.value=''/, 'changing machine type should clear a stale brand');
assert.match(html, /otherField\.hidden=!isOther/);
assert.match(html, /if\(!isOther\)otherInput\.value=''/);

assert.match(
  html,
  /<section class="knowledge-recommendations" id="knowledge-recommendations"[^>]*hidden>[\s\S]*?鋸片醫生延伸閱讀[\s\S]*?id="knowledge-list"/,
  'the result column should include a hidden official-reading section'
);
assert.match(
  html,
  /function renderKnowledgeRecommendations\(recommendations=\[\]\)\{[\s\S]*?list\.replaceChildren\(\)[\s\S]*?if\(!Array\.isArray\(recommendations\)\|\|!recommendations\.length\)\{card\.hidden=true;return\}/,
  'rendering should clear stale articles and hide an empty card'
);
assert.match(html, /link\.target='_blank';link\.rel='noopener'/, 'official articles should open safely in a new tab');
assert.match(html, /link\.textContent='查看官網文章'/, 'official article links should have meaningful copy');
assert.match(
  html,
  /function invalidateQuickState\(\)[\s\S]*?renderRecommendation\(null\);renderKnowledgeRecommendations\(\[\]\)/,
  'changing quick answers should clear product and reading recommendations'
);
assert.match(
  html,
  /renderRecommendation\(core\.getProductRecommendation\(quickState\)\);renderKnowledgeRecommendations\(core\.getKnowledgeRecommendations\(quickState\)\)/,
  'quick assessment should render both product and official-reading recommendations'
);
assert.match(
  html,
  /const dangerFromIssues=core\.classifyRisk\(input\.issues\)==='danger'/,
  'advanced submission should distinguish issue danger from machine-only danger'
);
assert.match(
  html,
  /renderRecommendation\(assessment\.level==='danger'\?null:core\.getProductRecommendation\(input\)\)/,
  'each advanced submission should hide or restore the product card from current assessment state'
);
assert.match(
  html,
  /renderKnowledgeRecommendations\(assessment\.level==='danger'&&!dangerFromIssues\?\[\]:core\.getKnowledgeRecommendations\(input\)\)/,
  'issue danger should retain whitelisted reading while machine-only danger clears unrelated reading'
);
assert.match(html, /\.knowledge-title\{[^}]*overflow-wrap:anywhere/, 'long article titles should wrap on narrow screens');
assert.match(
  html,
  /@media\(max-width:820px\)\{[\s\S]*?\.knowledge-link\{width:100%/,
  'official-reading links should be full width on mobile'
);
console.log('SawDoctor UI tests passed');
