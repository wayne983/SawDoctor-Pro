const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const corePath = path.join(__dirname, '..', 'apps-script', 'Core.gs');
const source = fs.readFileSync(corePath, 'utf8');
const context = {};
vm.createContext(context);
vm.runInContext(source, context);

const backend = context.SawDoctorBackendCore;
assert.ok(backend, 'Apps Script core should export SawDoctorBackendCore');

const manifest = JSON.parse(fs.readFileSync(
  path.join(__dirname, '..', 'apps-script', 'appsscript.json'),
  'utf8'
));
assert.deepEqual(
  manifest.webapp,
  {executeAs: 'USER_DEPLOYING', access: 'ANYONE_ANONYMOUS'},
  'Apps Script deployment must remain accessible to anonymous website visitors'
);

assert.equal(backend.formatRegistrationNumber_('20260729', 1), 'SD-20260729-001');
assert.equal(backend.formatRegistrationNumber_('20260729', 23), 'SD-20260729-023');

assert.deepEqual(
  Array.from(backend.validateInquiry_({name: '', phone: '', consent: false})),
  ['姓名不可空白', '聯絡電話不可空白', '尚未同意問診資料使用', '送出識別碼不可空白', '鋸片作動方式不可空白']
);

assert.deepEqual(
  Array.from(backend.validateInquiry_({
    name: '劉家維',
    phone: '+886922345816',
    consent: true,
    requestId: 'request-001',
    sawAction: '由上而下（下壓式切削）'
  })),
  []
);

const subject = backend.buildEmailSubject_(
  {company: '維翊貿易有限公司', name: '劉家維'},
  'SD-20260729-001'
);
assert.equal(subject, '[鋸片醫生初診單] SD-20260729-001｜維翊貿易有限公司｜劉家維');

const consultation = backend.buildConsultationText_(
  {
    name: '劉家維',
    company: '維翊貿易有限公司',
    phone: '+886922345816',
    materialLabel: '不鏽鋼',
    issues: ['壽命短', '尺寸不符合／切不到'],
    cutDirection: '橫切',
    sawAction: '由下而上（昇降式切削）',
    machineType: '鋁用',
    machineBrand: '其他',
    machineBrandOther: '測試機械',
    machineModel: 'CUSTOM-01',
    rpm: '1950',
    diameter: '255',
    kerf: '2.4',
    teeth: '120',
    brand: '測試品牌',
    bladeTypeLabel: 'TCT 鎢鋼鋸片',
    thickness: '3',
    cutLength: '800',
    frequency: '每天 1～4 小時',
    largerBladeFit: 'unknown',
    clearanceMm: '',
    note: '尺寸不足'
  },
  {
    title: '已完成鋸片醫生初步問診',
    safetyWarnings: ['安全提醒'],
    causes: ['可能原因'],
    followUpQuestions: ['補問項目']
  },
  {number: 'SD-20260729-001', registeredAt: '2026-07-29 14:30:00'}
);

for (const expected of [
  '掛號編號：SD-20260729-001',
  '掛號日期：2026-07-29 14:30:00',
  '切削材料：不鏽鋼',
  '主要困擾：壽命短、尺寸不符合／切不到',
  '鋸片作動方式：由下而上（昇降式切削）',
  '機台種類：鋁用',
  '機台轉速：1950 RPM',
  '鋸片規格：外徑 255mm／切幅 2.4mm／120 齒',
  '能否安裝更大尺寸鋸片：不確定',
  '鋸片外圍最小剩餘空間：未提供',
  '鋸片醫生希望您能提供：',
  '請補傳機台、工件、鋸片、切面'
]) {
  assert.ok(consultation.includes(expected), `consultation should include ${expected}`);
}
assert.equal(
  (consultation.match(/【鋸片醫生初步問診】/g) ?? []).length,
  1,
  'consultation block should appear exactly once'
);
assert.ok(consultation.includes('設備品牌：測試機械'));
assert.ok(consultation.includes('設備型號：CUSTOM-01'));
assert.equal((consultation.match(/設備品牌：/g) ?? []).length, 1);
assert.equal((consultation.match(/設備型號：/g) ?? []).length, 1);
assert.equal((consultation.match(/機台種類：/g) ?? []).length, 1);
assert.equal(backend.machineBrand_({machineBrand: '日意'}), '日意');
assert.equal(backend.machineBrand_({machineBrand: '不確定'}), '不確定');
assert.equal(
  backend.machineBrand_({machineBrand: '其他', machineBrandOther: ''}),
  '其他（未填名稱）'
);

console.log('SawDoctor backend core tests passed');
