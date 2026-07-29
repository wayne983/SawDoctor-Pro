const SHEET_NAME = 'HAWER 鋸片問診記錄';

function doPost(e) {
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    let sheet = ss.getSheetByName(SHEET_NAME);
    
    // 如果工作表不存在就建立，並加入標題列
    if (!sheet) {
      sheet = ss.insertSheet(SHEET_NAME);
      sheet.appendRow([
        '時間',
        '姓名',
        '公司',
        '電話',
        '機台轉速(RPM)',
        '鋸片外徑(mm)',
        '切幅(mm)',
        '齒數(T)',
        '品牌',
        '切削材料',
        '切削厚度(mm)',
        '切削性質',
        '切割方向',
        '使用頻率',
        '使用困擾',
        '補充說明',
        'AI診斷結果',
        '嚴重程度'
      ]);
      sheet.setFrozenRows(1);
      sheet.getRange(1,1,1,18).setBackground('#1D9E75').setFontColor('#ffffff').setFontWeight('bold');
    }
    
    const data = JSON.parse(e.postData.contents);
    
    sheet.appendRow([
      new Date(),
      data.name || '',
      data.company || '',
      data.phone || '',
      data.rpm || '',
      data.dia || '',
      data.kerf || '',
      data.teeth || '',
      data.brand || '',
      data.material || '',
      data.thickness || '',
      data.shapes || '',
      data.cuts || '',
      data.frequency || '',
      data.issues || '',
      data.note || '',
      data.diagTitle || '',
      data.severity || ''
    ]);
    
    return ContentService
      .createTextOutput(JSON.stringify({status:'ok'}))
      .setMimeType(ContentService.MimeType.JSON);
      
  } catch(err) {
    return ContentService
      .createTextOutput(JSON.stringify({status:'error', message: err.toString()}))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  return ContentService
    .createTextOutput(JSON.stringify({status:'ok', message:'HAWER 問診系統運作中'}))
    .setMimeType(ContentService.MimeType.JSON);
}
