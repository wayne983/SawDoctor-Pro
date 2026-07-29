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
  /if\(result\.requiresHumanReview\)\{[\s\S]*?assessment-line-button[\s\S]*?OFFICIAL_LINE_URL/,
  'human-review assessment should render a direct official LINE link'
);
assert.match(
  html,
  /前往官方 LINE 請鋸片醫生判讀/,
  'direct LINE link should explain the human diagnosis action'
);
assert.match(
  html,
  /if\(core\.canUnlockLine\(result\)\)revealLine/,
  'generated inquiry summary should remain gated by successful submission'
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
  /\.assessment-line-button\{width:100%;margin-top:16px\}/,
  'assessment LINE button should be full-width and clearly separated'
);
console.log('SawDoctor UI tests passed');
