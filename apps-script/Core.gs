var SawDoctorBackendCore = (function () {
  'use strict';

  function text_(value, fallback) {
    var text = String(value == null ? '' : value).trim();
    return text || (fallback !== undefined ? fallback : '未提供');
  }

  function validateInquiry_(payload) {
    payload = payload || {};
    var errors = [];
    if (!text_(payload.name, '')) errors.push('姓名不可空白');
    if (!text_(payload.phone, '')) errors.push('聯絡電話不可空白');
    if (payload.consent !== true) errors.push('尚未同意問診資料使用');
    if (!text_(payload.requestId, '')) errors.push('送出識別碼不可空白');
    return errors;
  }

  function formatRegistrationNumber_(dateKey, sequence) {
    return 'SD-' + String(dateKey) + '-' + String(sequence).padStart(3, '0');
  }

  function buildEmailSubject_(payload, registrationNumber) {
    payload = payload || {};
    return '[鋸片醫生初診單] ' + registrationNumber + '｜' +
      text_(payload.company, '未提供公司') + '｜' +
      text_(payload.name, '未提供姓名');
  }

  function numberedList_(items) {
    if (!Array.isArray(items) || !items.length) return '無';
    return items.map(function (item, index) {
      return (index + 1) + '. ' + item;
    }).join('\n');
  }

  function bladeType_(payload) {
    if (payload.bladeTypeLabel) return text_(payload.bladeTypeLabel);
    return {
      tct: 'TCT 鎢鋼鋸片',
      hss: 'HSS 高速鋼鋸片',
      unknown: '不確定'
    }[payload.bladeType] || '未提供';
  }

  function fitLabel_(value) {
    return {yes: '可以', no: '不可以', unknown: '不確定'}[value] || '未提供';
  }

  function machineBrand_(payload) {
    payload = payload || {};
    var brand = text_(payload.machineBrand, '');
    var other = text_(payload.machineBrandOther, '');
    if (brand === '其他') return other || '其他（未填名稱）';
    return brand || '未提供';
  }

  function specification_(payload) {
    var parts = [
      payload.diameter ? '外徑 ' + payload.diameter + 'mm' : '',
      payload.kerf ? '切幅 ' + payload.kerf + 'mm' : '',
      payload.teeth ? payload.teeth + ' 齒' : ''
    ].filter(Boolean);
    return parts.join('／') || '未提供';
  }

  function buildConsultationText_(payload, assessment, registration) {
    payload = payload || {};
    assessment = assessment || {};
    registration = registration || {};
    var issues = Array.isArray(payload.issues)
      ? payload.issues.join('、')
      : text_(payload.issues);

    return [
      '【鋸片醫生初步問診】',
      '掛號編號：' + text_(registration.number),
      '掛號日期：' + text_(registration.registeredAt),
      '姓名：' + text_(payload.name),
      '公司：' + text_(payload.company),
      '電話：' + text_(payload.phone),
      '切削材料：' + text_(payload.materialLabel || payload.material),
      '主要困擾：' + issues,
      '切割方向：' + text_(payload.cutDirection),
      '設備品牌：' + machineBrand_(payload),
      '設備型號：' + text_(payload.machineModel),
      '機台轉速：' + (payload.rpm ? payload.rpm + ' RPM' : '未提供'),
      '鋸片規格：' + specification_(payload),
      '目前品牌：' + text_(payload.brand),
      '鋸片類型：' + bladeType_(payload),
      '工件厚度：' + (payload.thickness ? payload.thickness + 'mm' : '未提供'),
      '單次切割長度：' + (payload.cutLength ? payload.cutLength + 'mm' : '未提供'),
      '使用頻率：' + text_(payload.frequency),
      '能否安裝更大尺寸鋸片：' + fitLabel_(payload.largerBladeFit),
      '鋸片外圍最小剩餘空間：' + (payload.clearanceMm ? payload.clearanceMm + ' mm' : '未提供'),
      '補充說明：' + text_(payload.note),
      '初步評估：' + text_(assessment.title),
      '安全警示：\n' + numberedList_(assessment.safetyWarnings),
      '可能原因：\n' + numberedList_(assessment.causes || assessment.possibleCauses),
      '鋸片醫生希望您能提供：\n' + numberedList_(assessment.followUpQuestions),
      '請鋸片醫生依實際條件進一步確認。',
      '請補傳機台、工件、鋸片、切面；尺寸不確定時請加拍主軸、護罩及周圍空間。'
    ].join('\n');
  }

  return Object.freeze({
    validateInquiry_: validateInquiry_,
    formatRegistrationNumber_: formatRegistrationNumber_,
    buildEmailSubject_: buildEmailSubject_,
    machineBrand_: machineBrand_,
    buildConsultationText_: buildConsultationText_
  });
})();
