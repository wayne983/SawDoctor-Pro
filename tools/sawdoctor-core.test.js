const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const htmlPath = path.join(__dirname, '..', 'index.html');
const html = fs.readFileSync(htmlPath, 'utf8');
const match = html.match(/<script id="sawdoctor-core">([\s\S]*?)<\/script>/);

assert.ok(match, 'index.html should include sawdoctor-core script');

const context = { globalThis: {} };
vm.createContext(context);
vm.runInContext(match[1], context);

const core = context.globalThis.SawDoctorCore;
assert.ok(core, 'SawDoctorCore should be exported');

const assessment = core.buildAssessment({
  material: 'steel',
  materialLabel: '鋼材／型鋼',
  issues: ['切割偏斜'],
  cutDirection: '縱切'
});

assert.equal(assessment.level, 'warning');
assert.ok(Array.isArray(assessment.possibleCauses), 'assessment should include possible causes');
assert.ok(assessment.possibleCauses.length >= 2, 'assessment should include at least two possible causes');
assert.ok(
  assessment.possibleCauses.some((item) => item.includes('鋸片剛性') || item.includes('側向受力')),
  'steel cutting drift should mention blade rigidity or lateral force'
);
assert.ok(Array.isArray(assessment.followUpQuestions), 'assessment should include follow-up questions');
assert.ok(
  assessment.followUpQuestions.some((item) => item.includes('RPM')) &&
  assessment.followUpQuestions.some((item) => item.includes('夾持')),
  'follow-up questions should ask for RPM and clamping'
);
assert.ok(
  assessment.disclaimer.includes('不直接確診') || assessment.disclaimer.includes('真人'),
  'disclaimer should keep diagnosis conservative'
);

console.log('SawDoctorCore diagnosis tests passed');
