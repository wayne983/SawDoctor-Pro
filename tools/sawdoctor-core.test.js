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


const completeInput = {
  material: 'steel',
  materialLabel: '鋼材／型鋼',
  issues: ['切割偏斜'],
  cutDirection: '橫切',
  rpm: '1500',
  diameter: '355',
  kerf: '2.0',
  teeth: '110',
  brand: '測試品牌',
  thickness: '10',
  cutLength: '500',
  bladeType: 'tct'
};

const completeAssessment = core.buildAssessment(completeInput);
for (const suppliedLabel of ['RPM', '外徑', '切幅', '目前品牌', '工件尺寸', '切割長度']) {
  assert.ok(
    completeAssessment.followUpQuestions.every((item) => !item.includes(suppliedLabel)),
    `completed input should not ask for supplied ${suppliedLabel}`
  );
}

const missingRpmAssessment = core.buildAssessment({...completeInput, rpm: ''});
assert.ok(
  missingRpmAssessment.followUpQuestions.some((item) => item.includes('RPM')),
  'missing RPM should remain as a follow-up question'
);
assert.ok(
  missingRpmAssessment.followUpQuestions.every((item) => !item.includes('外徑')),
  'missing RPM should not re-ask for supplied blade diameter'
);


const metalSafetyInput = {
  ...completeInput,
  issues: ['暫無困擾'],
  cutDirection: '橫切',
  material: 'steel',
  bladeType: 'tct',
  diameter: '355'
};

const rpm1800 = core.buildAssessment({...metalSafetyInput, rpm: '1800'});
assert.notEqual(rpm1800.level, 'danger', '1800 RPM should not be danger solely due to RPM');
assert.ok(
  !(rpm1800.safetyWarnings ?? []).some((item) => item.includes('立即停機')),
  '1800 RPM should not receive an overspeed stop warning'
);

const rpm1801 = core.buildAssessment({...metalSafetyInput, rpm: '1801'});
assert.equal(rpm1801.level, 'danger', '1801 RPM should be danger for phi355 TCT metal cutting');
assert.equal(rpm1801.requiresHumanReview, true, 'overspeed should require human review');
assert.ok(
  rpm1801.safetyWarnings.some((item) => item.includes('立即停機') && item.includes('1800 RPM')),
  'overspeed warning should state immediate stop and the 1800 RPM upper bound'
);

const rpm1299 = core.buildAssessment({...metalSafetyInput, rpm: '1299'});
assert.notEqual(rpm1299.level, 'danger', '1299 RPM should not be danger solely due to RPM');
assert.equal(rpm1299.requiresHumanReview, true, 'below-range RPM should require human review');
assert.ok(
  rpm1299.safetyWarnings.some((item) => item.includes('低於') && item.includes('1300 RPM')),
  'below-range warning should state the 1300 RPM lower bound'
);

for (const outsideScope of [
  {...metalSafetyInput, bladeType: 'hss', rpm: '3000'},
  {...metalSafetyInput, diameter: '305', rpm: '3000'}
]) {
  const result = core.buildAssessment(outsideScope);
  assert.ok(
    !(result.safetyWarnings ?? []).some((item) => item.includes('1300～1800 RPM')),
    'HSS and non-phi355 blades should not inherit the fixed RPM range'
  );
}

for (const machineModel of ['高速砂輪切斷機', '角磨機']) {
  const result = core.buildAssessment({...metalSafetyInput, machineModel});
  assert.equal(result.level, 'danger', `${machineModel} with TCT should be danger`);
  assert.ok(
    result.safetyWarnings.some((item) => item.includes('不得安裝 TCT 齒狀鋸片') && item.includes('斷齒飛散')),
    `${machineModel} warning should name the TCT and flying-tooth hazard`
  );
}


const grinderAssessment = core.buildAssessment({...metalSafetyInput, machineModel: '高速砂輪切斷機'});
const grinderMessage = core.buildLineMessage({...metalSafetyInput, machineModel: '高速砂輪切斷機'}, grinderAssessment);
assert.ok(
  grinderMessage.includes('安全警示：') && grinderMessage.includes('斷齒飛散'),
  'LINE inquiry summary should carry the safety warning to the doctor'
);

const sizeIssueAssessment = core.buildAssessment({
  material: 'steel',
  issues: ['尺寸不符合／切不到'],
  cutDirection: '橫切',
  largerBladeFit: '',
  clearanceMm: ''
});
assert.ok(
  sizeIssueAssessment.causes.some((item) => item.includes('外徑') && item.includes('切深')),
  'size issue should explain blade diameter and cutting-depth constraints'
);
assert.ok(
  sizeIssueAssessment.followUpQuestions.some((item) => item.includes('更大尺寸')),
  'size issue should ask whether a larger blade fits'
);
assert.ok(
  sizeIssueAssessment.followUpQuestions.some((item) => item.includes('剩餘空間')),
  'size issue should ask for minimum machine clearance'
);

const unknownBladeFitAssessment = core.buildAssessment({
  material: 'steel',
  issues: ['尺寸不符合／切不到'],
  cutDirection: '橫切',
  largerBladeFit: 'unknown',
  clearanceMm: ''
});
assert.ok(
  unknownBladeFitAssessment.missing.some((item) => item.includes('護罩') && item.includes('照片')),
  'unknown fit should request blade, arbor, guard, and surrounding-space photos'
);

const completeBladeFitAssessment = core.buildAssessment({
  material: 'steel',
  issues: ['尺寸不符合／切不到'],
  cutDirection: '橫切',
  largerBladeFit: 'yes',
  clearanceMm: '18'
});
assert.ok(
  completeBladeFitAssessment.followUpQuestions.every((item) => !item.includes('更大尺寸')),
  'completed fit answer should not be asked again'
);
assert.ok(
  completeBladeFitAssessment.followUpQuestions.every((item) => !item.includes('剩餘空間')),
  'completed clearance should not be asked again'
);

assert.equal(core.machineBrandLabel({machineBrand: '日意'}), '日意');
assert.equal(
  core.machineBrandLabel({machineBrand: '其他', machineBrandOther: '測試機械'}),
  '測試機械'
);
assert.equal(
  core.machineBrandLabel({machineBrand: '其他', machineBrandOther: ''}),
  '其他（未填名稱）'
);
assert.equal(core.machineBrandLabel({machineBrand: '不確定'}), '不確定');
assert.equal(core.machineBrandLabel({}), '未提供');

const knownMachine = core.buildAssessment({
  ...completeInput,
  machineBrand: '冠盛',
  machineModel: 'KS-100'
});
assert.ok(
  knownMachine.followUpQuestions.every((item) => !item.includes('設備品牌')),
  'selected equipment brand should not be requested again'
);
assert.ok(
  knownMachine.followUpQuestions.every((item) => !item.includes('設備型號')),
  'provided equipment model should not be requested again'
);

const missingMachine = core.buildAssessment({...completeInput, machineBrand: '', machineModel: ''});
assert.ok(missingMachine.followUpQuestions.some((item) => item.includes('設備品牌')));
assert.ok(missingMachine.followUpQuestions.some((item) => item.includes('設備型號')));

const unnamedOtherMachine = core.buildAssessment({
  ...completeInput,
  machineBrand: '其他',
  machineBrandOther: '',
  machineModel: 'CUSTOM-01'
});
assert.ok(
  unnamedOtherMachine.followUpQuestions.some((item) => item.includes('其他設備品牌名稱'))
);
assert.ok(
  unnamedOtherMachine.followUpQuestions.every((item) => !item.includes('設備型號'))
);

const uncertainMachine = core.buildAssessment({
  ...completeInput,
  machineBrand: '不確定',
  machineModel: ''
});
assert.ok(
  uncertainMachine.followUpQuestions.every((item) => !item.startsWith('設備品牌'))
);
assert.ok(uncertainMachine.followUpQuestions.some((item) => item.includes('設備型號')));

const brandMessage = core.buildLineMessage({
  ...completeInput,
  machineBrand: '其他',
  machineBrandOther: '測試機械',
  machineModel: 'CUSTOM-01'
});
assert.ok(brandMessage.includes('設備品牌：測試機械'));
assert.ok(brandMessage.includes('設備型號：CUSTOM-01'));
console.log('SawDoctorCore diagnosis tests passed');
