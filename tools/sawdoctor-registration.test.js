const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class FakeSheet {
  constructor(name) {
    this.name = name;
    this.rows = [];
  }
  getLastRow() {
    return this.rows.length;
  }
  appendRow(row) {
    this.rows.push(Array.from(row));
  }
  getRange(row, column) {
    return {
      getValue: () => this.rows[row - 1]?.[column - 1] ?? '',
      setValue: (value) => {
        while (this.rows.length < row) this.rows.push([]);
        this.rows[row - 1][column - 1] = value;
      }
    };
  }
}

class FakeSpreadsheet {
  constructor(id) {
    this.id = id;
    this.sheets = new Map();
  }
  getId() {
    return this.id;
  }
  getSheetByName(name) {
    return this.sheets.get(name) ?? null;
  }
  insertSheet(name) {
    const sheet = new FakeSheet(name);
    this.sheets.set(name, sheet);
    return sheet;
  }
}

const properties = new Map();
const spreadsheet = new FakeSpreadsheet('sheet-001');
const sentMail = [];
let failMail = false;
let lockDepth = 0;

const context = {
  console,
  JSON,
  Object,
  Array,
  String,
  Number,
  Date,
  Math,
  LockService: {
    getScriptLock() {
      return {
        waitLock() {
          assert.equal(lockDepth, 0, 'script lock should not be re-entered');
          lockDepth += 1;
        },
        releaseLock() {
          lockDepth -= 1;
        }
      };
    }
  },
  PropertiesService: {
    getScriptProperties() {
      return {
        getProperty(key) {
          return properties.get(key) ?? null;
        },
        setProperty(key, value) {
          properties.set(key, String(value));
        }
      };
    }
  },
  SpreadsheetApp: {
    create() {
      return spreadsheet;
    },
    openById(id) {
      assert.equal(id, spreadsheet.id);
      return spreadsheet;
    }
  },
  MailApp: {
    sendEmail(message) {
      sentMail.push({...message});
      if (failMail) throw new Error('mail unavailable');
    }
  },
  Utilities: {
    formatDate(date, timezone, format) {
      assert.equal(timezone, 'Asia/Taipei');
      const shifted = new Date(date.getTime() + 8 * 60 * 60 * 1000);
      const iso = shifted.toISOString();
      if (format === 'yyyyMMdd') return iso.slice(0, 10).replaceAll('-', '');
      if (format === 'yyyy-MM-dd HH:mm:ss') return iso.slice(0, 19).replace('T', ' ');
      throw new Error(`unexpected format ${format}`);
    }
  },
  HtmlService: {
    XFrameOptionsMode: {ALLOWALL: 'ALLOWALL'},
    createHtmlOutput(content) {
      return {
        content,
        mode: '',
        setXFrameOptionsMode(mode) {
          this.mode = mode;
          return this;
        }
      };
    }
  }
};

vm.createContext(context);
for (const file of ['Core.gs', 'Code.gs']) {
  const source = fs.readFileSync(path.join(__dirname, '..', 'apps-script', file), 'utf8');
  vm.runInContext(source, context, {filename: file});
}
context.nowProvider_ = () => new Date('2026-07-29T06:30:00.000Z');

function makePayload(requestId) {
  return {
    requestId,
    name: '劉家維',
    company: '維翊貿易有限公司',
    phone: '+886922345816',
    consent: true,
    materialLabel: '不鏽鋼',
    issues: ['壽命短', '切割偏斜'],
    cutDirection: '橫切',
    sawAction: '左右／前後切割（行進式切削）',
    machineBrand: '冠盛',
    machineModel: '測試機台',
    rpm: '1950',
    diameter: '255',
    kerf: '2.4',
    teeth: '120',
    bladeTypeLabel: 'TCT 鎢鋼鋸片',
    thickness: '3',
    assessment: {
      title: '已完成鋸片醫生初步問診',
      safetyWarnings: ['安全提醒'],
      causes: ['可能原因'],
      followUpQuestions: ['目前鋸片品牌']
    }
  };
}

const oldSheet = new FakeSheet('舊初診單');
const oldHeaders = Array.from(context.REGISTRATION_HEADERS).slice(0, -1);
oldSheet.appendRow(oldHeaders);
context.ensureRegistrationHeaders_(oldSheet);
assert.deepEqual(oldSheet.rows[0].slice(0, oldHeaders.length), oldHeaders);
assert.equal(oldSheet.rows[0].length, oldHeaders.length + 1);
assert.equal(oldSheet.rows[0].at(-1), '鋸片作動方式');

const first = context.registerInquiry_(makePayload('request-001'));
assert.equal(first.ok, true);
assert.equal(first.registrationNumber, 'SD-20260729-001');
assert.equal(first.registeredAt, '2026-07-29 14:30:00');
assert.equal(sentMail.length, 1);
assert.deepEqual(
  sentMail[0].to.split(','),
  ['sales@hawer-knife.com', 'wayne983@gmail.com']
);
assert.ok(sentMail[0].subject.includes('SD-20260729-001'));

const sheet = spreadsheet.getSheetByName('初診單');
assert.ok(sheet, 'registration sheet should exist');
assert.equal(sheet.rows.length, 2, 'sheet should contain one header and one registration');
assert.equal(sheet.rows[1][0], 'SD-20260729-001');
assert.equal(sheet.rows[0].at(-2), '設備品牌');
assert.equal(sheet.rows[1].at(-2), '冠盛');
assert.equal(sheet.rows[0].at(-1), '鋸片作動方式');
assert.equal(sheet.rows[1].at(-1), '左右／前後切割（行進式切削）');
assert.equal(sheet.rows[0][10], '機台轉速', 'existing headers must not move');
assert.equal(sheet.rows[1][9], '測試機台', 'existing model data must not move');
assert.equal(sheet.rows[1].at(-3), 'SENT');

const duplicate = context.registerInquiry_(makePayload('request-001'));
assert.equal(duplicate.ok, true);
assert.equal(duplicate.registrationNumber, first.registrationNumber);
assert.equal(sentMail.length, 1, 'duplicate successful request should not send another email');
assert.equal(sheet.rows.length, 2, 'duplicate successful request should not append another row');

failMail = true;
const failed = context.registerInquiry_(makePayload('request-002'));
assert.equal(failed.ok, false);
assert.equal(failed.registrationNumber, '');
assert.equal(sentMail.length, 2, 'failed delivery should make only one mail attempt');
assert.equal(sheet.rows.length, 3, 'failed delivery should remain traceable in the sheet');
assert.equal(sheet.rows[2].at(-3), 'FAILED');
assert.equal(sheet.rows[2].at(-2), '冠盛');
assert.equal(sheet.rows[2].at(-1), '左右／前後切割（行進式切削）');

failMail = false;
const failedRetry = context.registerInquiry_(makePayload('request-002'));
assert.equal(failedRetry.ok, false);
assert.equal(sentMail.length, 2, 'failed request retry must not risk duplicate email');
assert.equal(sheet.rows.length, 3, 'failed request retry must not append another row');

const output = context.doPost({
  parameter: {payload: JSON.stringify(makePayload('request-003'))}
});
assert.equal(output.mode, 'ALLOWALL');
assert.ok(output.content.includes('top.postMessage'));
assert.ok(!output.content.includes('parent.postMessage'));
assert.ok(output.content.includes('https://wayne983.github.io'));
assert.ok(output.content.includes('request-003'));

console.log('SawDoctor registration orchestration tests passed');
