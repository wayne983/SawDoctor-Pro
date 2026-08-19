var CONFIG = Object.freeze({
  timezone: 'Asia/Taipei',
  recipients: 'sales@hawer-knife.com,wayne983@gmail.com',
  spreadsheetName: '鋸片醫生初診掛號',
  sheetName: '初診單',
  allowedParentOrigin: 'https://wayne983.github.io'
});

var REGISTRATION_HEADERS = Object.freeze([
  '掛號編號',
  '掛號日期',
  '送出識別碼',
  '姓名',
  '公司',
  '電話',
  '切削材料',
  '主要困擾',
  '切割方向',
  '機台型號',
  '機台轉速',
  '鋸片外徑',
  '切幅',
  '齒數',
  '鋸片品牌',
  '鋸片類型',
  '工件厚度',
  '切割長度',
  '使用頻率',
  '可否安裝更大鋸片',
  '剩餘空間 mm',
  '補充說明',
  '初步評估',
  '完整初診單',
  '狀態',
  '設備品牌',
  '鋸片作動方式'
]);

function nowProvider_() {
  return new Date();
}

function findRequest_(requestId) {
  var raw = PropertiesService.getScriptProperties().getProperty('REQ_' + requestId);
  return raw ? JSON.parse(raw) : null;
}

function saveRequest_(requestId, record) {
  PropertiesService.getScriptProperties().setProperty(
    'REQ_' + requestId,
    JSON.stringify(record)
  );
}

function nextRegistrationUnlocked_(now) {
  var properties = PropertiesService.getScriptProperties();
  var dateKey = Utilities.formatDate(now, CONFIG.timezone, 'yyyyMMdd');
  var key = 'SEQ_' + dateKey;
  var sequence = Number(properties.getProperty(key) || '0') + 1;
  properties.setProperty(key, String(sequence));
  return {
    number: SawDoctorBackendCore.formatRegistrationNumber_(dateKey, sequence),
    registeredAt: Utilities.formatDate(now, CONFIG.timezone, 'yyyy-MM-dd HH:mm:ss')
  };
}

function ensureRegistrationHeaders_(sheet) {
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(REGISTRATION_HEADERS);
    return;
  }
  ['設備品牌', '鋸片作動方式'].forEach(function (header) {
    var column = REGISTRATION_HEADERS.indexOf(header) + 1;
    var current = String(sheet.getRange(1, column).getValue() || '').trim();
    if (!current) sheet.getRange(1, column).setValue(header);
  });
}

function getOrCreateSheet_() {
  var properties = PropertiesService.getScriptProperties();
  var id = properties.getProperty('SPREADSHEET_ID');
  var spreadsheet;
  if (id) {
    spreadsheet = SpreadsheetApp.openById(id);
  } else {
    spreadsheet = SpreadsheetApp.create(CONFIG.spreadsheetName);
    properties.setProperty('SPREADSHEET_ID', spreadsheet.getId());
  }
  var sheet = spreadsheet.getSheetByName(CONFIG.sheetName);
  if (!sheet) sheet = spreadsheet.insertSheet(CONFIG.sheetName);
  ensureRegistrationHeaders_(sheet);
  return sheet;
}

function issueText_(issues) {
  return Array.isArray(issues) ? issues.join('、') : String(issues || '');
}

function appendRegistration_(sheet, payload, assessment, registration, consultationText) {
  sheet.appendRow([
    registration.number,
    registration.registeredAt,
    payload.requestId,
    payload.name || '',
    payload.company || '',
    payload.phone || '',
    payload.materialLabel || payload.material || '',
    issueText_(payload.issues),
    payload.cutDirection || '',
    payload.machineModel || '',
    payload.rpm || '',
    payload.diameter || '',
    payload.kerf || '',
    payload.teeth || '',
    payload.brand || '',
    payload.bladeTypeLabel || payload.bladeType || '',
    payload.thickness || '',
    payload.cutLength || '',
    payload.frequency || '',
    payload.largerBladeFit || '',
    payload.clearanceMm || '',
    payload.note || '',
    assessment.title || '',
    consultationText,
    'SENDING',
    SawDoctorBackendCore.machineBrand_(payload),
    payload.sawAction || ''
  ]);
  return sheet.getLastRow();
}

function updateRegistrationStatus_(sheet, rowNumber, status) {
  var statusColumn = REGISTRATION_HEADERS.indexOf('狀態') + 1;
  sheet.getRange(rowNumber, statusColumn).setValue(status);
}

function failureResult_(requestId, error) {
  return {
    ok: false,
    requestId: requestId || '',
    registrationNumber: '',
    registeredAt: '',
    error: String(error || '掛號尚未完成')
  };
}

function successResult_(requestId, record) {
  return {
    ok: true,
    requestId: requestId,
    registrationNumber: record.registrationNumber,
    registeredAt: record.registeredAt,
    error: ''
  };
}

function registerInquiry_(payload) {
  payload = payload || {};
  var errors = SawDoctorBackendCore.validateInquiry_(payload);
  if (errors.length) return failureResult_(payload.requestId, errors.join('；'));

  var lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    var existing = findRequest_(payload.requestId);
    if (existing) {
      if (existing.state === 'SENT') return successResult_(payload.requestId, existing);
      return failureResult_(payload.requestId, '此掛號正在處理或先前寄送失敗，請由鋸片醫生人工確認');
    }

    var registration = nextRegistrationUnlocked_(nowProvider_());
    var assessment = payload.assessment || {};
    var consultationText = SawDoctorBackendCore.buildConsultationText_(
      payload,
      assessment,
      registration
    );
    var subject = SawDoctorBackendCore.buildEmailSubject_(payload, registration.number);
    var sheet = getOrCreateSheet_();
    var rowNumber = appendRegistration_(
      sheet,
      payload,
      assessment,
      registration,
      consultationText
    );
    var record = {
      state: 'SENDING',
      registrationNumber: registration.number,
      registeredAt: registration.registeredAt,
      rowNumber: rowNumber
    };
    saveRequest_(payload.requestId, record);

    try {
      MailApp.sendEmail({
        to: CONFIG.recipients,
        subject: subject,
        body: consultationText
      });
      record.state = 'SENT';
      updateRegistrationStatus_(sheet, rowNumber, record.state);
      saveRequest_(payload.requestId, record);
      return successResult_(payload.requestId, record);
    } catch (mailError) {
      record.state = 'FAILED';
      record.error = String(mailError && mailError.message ? mailError.message : mailError);
      updateRegistrationStatus_(sheet, rowNumber, record.state);
      saveRequest_(payload.requestId, record);
      return failureResult_(payload.requestId, '初診單郵件未確認寄出');
    }
  } finally {
    lock.releaseLock();
  }
}

function callbackOutput_(result) {
  var json = JSON.stringify(result).replace(/</g, '\\u003c');
  var html = '<script>top.postMessage(' + json + ',' +
    JSON.stringify(CONFIG.allowedParentOrigin) + ');</script>';
  return HtmlService.createHtmlOutput(html)
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function doPost(e) {
  var payload;
  try {
    payload = JSON.parse(e && e.parameter ? e.parameter.payload || '{}' : '{}');
  } catch (error) {
    return callbackOutput_(failureResult_('', '問診資料格式錯誤'));
  }
  return callbackOutput_(registerInquiry_(payload));
}
