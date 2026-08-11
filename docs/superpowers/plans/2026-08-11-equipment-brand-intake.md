# Equipment Brand Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured equipment-brand and free-text model intake for 日意、冠盛、慶祥、其他 and 不確定, and carry the data through diagnosis follow-ups, email, spreadsheet registration and LINE summary without introducing unverified machine specifications.

**Architecture:** Keep the current single-file frontend and Apps Script backend. Add a pure `machineBrandLabel()` formatter to the browser diagnosis core, collect `machineBrand`, `machineBrandOther` and `machineModel` separately in the application layer, and add a matching backend formatter. Preserve existing spreadsheet columns by appending one new `設備品牌` column at the end and repairing only the missing final header on existing sheets.

**Tech Stack:** Static HTML/CSS/JavaScript, Google Apps Script, Node.js built-in `assert`, `vm` and `fs` test harnesses.

## Global Constraints

- Equipment-brand choices are exactly: empty prompt, 日意, 冠盛, 慶祥, 其他, 不確定.
- `machineModel` remains free text; no model catalogue is introduced in this change.
- No equipment brand may auto-fill or infer RPM, blade diameter, bore, kerf, teeth or cutting capacity.
- Unknown or unverified equipment data must remain empty and go to human review.
- Existing safety logic, diagnosis rules, registration numbering, two-recipient email delivery and official LINE URL remain unchanged.
- Existing spreadsheet columns and historical rows must not move.
- User-facing copy remains Traditional Chinese and uses the 鋸片醫生 consultation tone.
- Preserve UTF-8 without BOM and finish with `git diff --check`.

---

### Task 1: Add equipment-brand semantics to the diagnosis core

**Files:**
- Modify: `index.html:141-158,184-267,286-288`
- Test: `tools/sawdoctor-core.test.js`

**Interfaces:**
- Consumes: `input.machineBrand`, `input.machineBrandOther`, `input.machineModel` strings.
- Produces: `machineBrandLabel(input) -> string`, exported on `globalThis.SawDoctorCore`; brand/model-aware `assessment.followUpQuestions`; `buildLineMessage()` containing separate equipment brand and model lines.

- [ ] **Step 1: Write failing core tests for brand formatting and follow-up filtering**

Append these assertions before the final log line in `tools/sawdoctor-core.test.js`:

```js
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
```

- [ ] **Step 2: Run the core test and verify the new assertions fail**

Run:

```powershell
node tools/sawdoctor-core.test.js
```

Expected: FAIL because `core.machineBrandLabel` does not exist.

- [ ] **Step 3: Implement the pure equipment-brand formatter**

Add beside `bladeTypeLabel()` in `index.html`:

```js
function machineBrandLabel(input={}){
  const brand=String(input.machineBrand??'').trim();
  const other=String(input.machineBrandOther??'').trim();
  if(brand==='其他')return other||'其他（未填名稱）';
  return brand||'未提供';
}
```

Export `machineBrandLabel` from `SawDoctorCore` in the existing frozen export object.

- [ ] **Step 4: Add conditional brand and model follow-ups**

At the start of `collectKnowledge()` after its local arrays are declared, add:

```js
const machineBrand=String(input.machineBrand??'').trim();
const machineBrandOther=String(input.machineBrandOther??'').trim();
const machineModel=String(input.machineModel??'').trim();
if(!machineBrand){
  followUpQuestions.push('設備品牌；若不確定可選不確定並補拍機台銘牌');
}else if(machineBrand==='其他'&&!machineBrandOther){
  followUpQuestions.push('其他設備品牌名稱');
}
if(!machineModel)followUpQuestions.push('設備型號；若不確定請補拍機台銘牌');
```

Do not add `machineBrand` to `requiresHumanReview` and do not modify numeric fields.

- [ ] **Step 5: Carry separate brand and model lines into the LINE summary**

In `buildLineMessage()`, replace the current `機台型號` line with:

```js
`設備品牌：${machineBrandLabel(input)}`,
`設備型號：${String(input.machineModel??'').trim()||'未提供'}`,
```

- [ ] **Step 6: Run core tests and verify they pass**

Run:

```powershell
node tools/sawdoctor-core.test.js
```

Expected: `SawDoctorCore diagnosis tests passed`.

- [ ] **Step 7: Commit the core behavior**

```powershell
git add -- index.html tools/sawdoctor-core.test.js
git commit -m "feat: add equipment brand diagnosis intake"
```

---

### Task 2: Add accessible brand controls and application data collection

**Files:**
- Modify: `index.html:22-45,81-94,293-340`
- Test: `tools/sawdoctor-ui.test.js`

**Interfaces:**
- Consumes: the `machineBrandLabel()` core function from Task 1.
- Produces: DOM controls `#machine-brand`, `#machine-brand-other-field`, `#machine-brand-other`, `#machine-model`; `collectAdvancedInput()` returns all three machine properties.

- [ ] **Step 1: Write failing UI structure and behavior assertions**

Append these checks to `tools/sawdoctor-ui.test.js`:

```js
for (const copy of ['日意', '冠盛', '慶祥', '其他', '不確定']) {
  assert.ok(html.includes(`<option value="${copy}">${copy}</option>`), `brand list should include ${copy}`);
}
assert.match(html, /id="machine-brand" name="machineBrand"/);
assert.match(html, /id="machine-brand-other-field"[^>]*hidden/);
assert.match(html, /id="machine-brand-other" name="machineBrandOther"/);
assert.match(html, /id="machine-model" name="machineModel"/);
assert.match(
  html,
  /machineBrand:\$\('machine-brand'\)\.value/
);
assert.match(
  html,
  /machineBrandOther:\$\('machine-brand'\)\.value==='其他'\?\$\('machine-brand-other'\)\.value\.trim\(\):''/
);
assert.match(html, /function syncMachineBrandOther\(\)/);
assert.match(html, /otherField\.hidden=!isOther/);
assert.match(html, /if\(!isOther\)otherInput\.value=''/);
```

- [ ] **Step 2: Run the UI test and verify it fails**

Run:

```powershell
node tools/sawdoctor-ui.test.js
```

Expected: FAIL because `#machine-brand` is absent.

- [ ] **Step 3: Replace the combined machine field with structured controls**

Replace the current phone/machine row with a phone-only row followed by:

```html
<div class="field-grid">
  <div class="field">
    <label for="machine-brand">設備品牌</label>
    <select id="machine-brand" name="machineBrand">
      <option value="">請選擇…</option>
      <option value="日意">日意</option>
      <option value="冠盛">冠盛</option>
      <option value="慶祥">慶祥</option>
      <option value="其他">其他</option>
      <option value="不確定">不確定</option>
    </select>
  </div>
  <div class="field" id="machine-brand-other-field" hidden>
    <label for="machine-brand-other">其他設備品牌</label>
    <input id="machine-brand-other" name="machineBrandOther" autocomplete="off">
  </div>
</div>
<div class="field">
  <label for="machine-model">設備型號</label>
  <input id="machine-model" name="machineModel" autocomplete="off">
</div>
```

Keep these controls before RPM so the mobile reading order is brand, other brand when applicable, model, RPM.

- [ ] **Step 4: Add deterministic other-brand visibility behavior**

Add in the app script after the material listener:

```js
function syncMachineBrandOther(){
  const isOther=$('machine-brand').value==='其他';
  const otherField=$('machine-brand-other-field');
  const otherInput=$('machine-brand-other');
  otherField.hidden=!isOther;
  if(!isOther)otherInput.value='';
}
$('machine-brand').addEventListener('change',syncMachineBrandOther);
syncMachineBrandOther();
```

The native `hidden` attribute removes the hidden control from keyboard and screen-reader traversal.

- [ ] **Step 5: Extend advanced input collection without touching numeric values**

Add these properties to `collectAdvancedInput()` before `machineModel`:

```js
machineBrand:$('machine-brand').value,
machineBrandOther:$('machine-brand').value==='其他'?$('machine-brand-other').value.trim():'',
```

Do not add any event that writes to `rpm`, `diameter`, `kerf`, `teeth` or `clearanceMm`.

- [ ] **Step 6: Run UI and core tests**

Run:

```powershell
node tools/sawdoctor-ui.test.js
node tools/sawdoctor-core.test.js
```

Expected: both print their existing pass messages.

- [ ] **Step 7: Commit the form changes**

```powershell
git add -- index.html tools/sawdoctor-ui.test.js
git commit -m "feat: collect equipment brand and model"
```

---

### Task 3: Add equipment brand to the emailed initial consultation

**Files:**
- Modify: `apps-script/Core.gs:4-102`
- Test: `tools/sawdoctor-backend.test.js`

**Interfaces:**
- Consumes: `payload.machineBrand`, `payload.machineBrandOther`, `payload.machineModel`.
- Produces: backend `machineBrand_(payload) -> string`; consultation text containing one `設備品牌` and one `設備型號` line.

- [ ] **Step 1: Write failing backend formatting tests**

Extend the consultation fixture in `tools/sawdoctor-backend.test.js` with:

```js
machineBrand: '其他',
machineBrandOther: '測試機械',
machineModel: 'CUSTOM-01',
```

Add these assertions after `consultation` is built:

```js
assert.ok(consultation.includes('設備品牌：測試機械'));
assert.ok(consultation.includes('設備型號：CUSTOM-01'));
assert.equal((consultation.match(/設備品牌：/g) ?? []).length, 1);
assert.equal((consultation.match(/設備型號：/g) ?? []).length, 1);
```

Add a direct formatter case by exporting `machineBrand_` for tests:

```js
assert.equal(backend.machineBrand_({machineBrand: '日意'}), '日意');
assert.equal(backend.machineBrand_({machineBrand: '不確定'}), '不確定');
assert.equal(
  backend.machineBrand_({machineBrand: '其他', machineBrandOther: ''}),
  '其他（未填名稱）'
);
```

- [ ] **Step 2: Run the backend test and verify it fails**

Run:

```powershell
node tools/sawdoctor-backend.test.js
```

Expected: FAIL because `backend.machineBrand_` does not exist.

- [ ] **Step 3: Implement the backend formatter and email lines**

Add to `apps-script/Core.gs`:

```js
function machineBrand_(payload) {
  payload = payload || {};
  var brand = text_(payload.machineBrand, '');
  var other = text_(payload.machineBrandOther, '');
  if (brand === '其他') return other || '其他（未填名稱）';
  return brand || '未提供';
}
```

Replace `機台型號` in `buildConsultationText_()` with:

```js
'設備品牌：' + machineBrand_(payload),
'設備型號：' + text_(payload.machineModel),
```

Expose `machineBrand_` in the frozen test interface.

- [ ] **Step 4: Run backend tests**

Run:

```powershell
node tools/sawdoctor-backend.test.js
```

Expected: `SawDoctor backend formatting tests passed`.

- [ ] **Step 5: Commit the email formatting**

```powershell
git add -- apps-script/Core.gs tools/sawdoctor-backend.test.js
git commit -m "feat: include equipment brand in consultation email"
```

---

### Task 4: Append a backward-compatible spreadsheet brand column

**Files:**
- Modify: `apps-script/Code.gs:9-112`
- Test: `tools/sawdoctor-registration.test.js`

**Interfaces:**
- Consumes: `SawDoctorBackendCore.machineBrand_(payload)` from Task 3.
- Produces: `ensureRegistrationHeaders_(sheet)`; final header `設備品牌`; appended registration rows with the brand value in the final cell while all existing cell indexes remain stable.

- [ ] **Step 1: Extend the Apps Script sheet stub and write failing migration tests**

Update the existing `getRange()` stub in `tools/sawdoctor-registration.test.js` so it supports both reading and writing:

```js
getRange(row, column) {
  return {
    getValue: () => this.rows[row - 1]?.[column - 1] ?? '',
    setValue: (value) => {
      while (this.rows.length < row) this.rows.push([]);
      this.rows[row - 1][column - 1] = value;
    }
  };
},
```

Add `machineBrand: '冠盛'` to the successful registration payload. Then assert:

```js
assert.equal(sheet.rows[0].at(-1), '設備品牌');
assert.equal(sheet.rows[1].at(-1), '冠盛');
assert.equal(sheet.rows[0][10], '機台轉速', 'existing headers must not move');
assert.equal(sheet.rows[1][9], '測試機台', 'existing model data must not move');
```

Create a pre-existing sheet fixture and test the repair helper directly:

```js
const oldSheet = new FakeSheet('舊初診單');
const oldHeaders = Array.from(context.REGISTRATION_HEADERS).slice(0, -1);
oldSheet.appendRow(oldHeaders);
context.ensureRegistrationHeaders_(oldSheet);
assert.deepEqual(oldSheet.rows[0].slice(0, oldHeaders.length), oldHeaders);
assert.equal(oldSheet.rows[0].length, oldHeaders.length + 1);
assert.equal(oldSheet.rows[0].at(-1), '設備品牌');
```

- [ ] **Step 2: Run registration tests and verify they fail**

Run:

```powershell
node tools/sawdoctor-registration.test.js
```

Expected: FAIL because the last header and row value are not `設備品牌` and `冠盛`.

- [ ] **Step 3: Add the final header and repair helper**

Append `'設備品牌'` after `'狀態'` in `REGISTRATION_HEADERS`. Add:

```js
function ensureRegistrationHeaders_(sheet) {
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(REGISTRATION_HEADERS);
    return;
  }
  var brandColumn = REGISTRATION_HEADERS.length;
  var current = String(sheet.getRange(1, brandColumn).getValue() || '').trim();
  if (!current) sheet.getRange(1, brandColumn).setValue('設備品牌');
}
```

Call `ensureRegistrationHeaders_(sheet)` from `getOrCreateSheet_()` instead of only appending headers to an empty sheet. This operation writes only the new final header cell and never inserts a column.

- [ ] **Step 4: Append the brand after the existing status value**

At the end of the array in `appendRegistration_()`, change:

```js
'SENDING'
```

to:

```js
'SENDING',
SawDoctorBackendCore.machineBrand_(payload)
```

Replace `updateRegistrationStatus_()` with the explicit status-header index so the new final brand column is never overwritten:

```js
function updateRegistrationStatus_(sheet, rowNumber, status) {
  var statusColumn = REGISTRATION_HEADERS.indexOf('狀態') + 1;
  sheet.getRange(rowNumber, statusColumn).setValue(status);
}
```

Add a registration assertion that `sheet.rows[1].at(-2)` equals `SENT` after successful email delivery.

- [ ] **Step 5: Run backend and registration tests**

Run:

```powershell
node tools/sawdoctor-backend.test.js
node tools/sawdoctor-registration.test.js
```

Expected: both print their pass messages and duplicate `requestId` still sends only one email.

- [ ] **Step 6: Commit spreadsheet compatibility**

```powershell
git add -- apps-script/Code.gs tools/sawdoctor-registration.test.js
git commit -m "feat: store equipment brand with registrations"
```

---

### Task 5: Run full regression and mobile browser verification

**Files:**
- Modify only if verification reveals a defect: `index.html`, `apps-script/Core.gs`, `apps-script/Code.gs`, `tools/*.test.js`

**Interfaces:**
- Consumes: all deliverables from Tasks 1–4.
- Produces: verified static page and Apps Script source ready for the existing deployment process.

- [ ] **Step 1: Run the complete automated suite**

Run:

```powershell
node tools/sawdoctor-core.test.js
node tools/sawdoctor-ui.test.js
node tools/sawdoctor-backend.test.js
node tools/sawdoctor-registration.test.js
```

Expected: all four scripts print their pass messages with exit code 0.

- [ ] **Step 2: Verify source boundaries and syntax**

Run:

```powershell
rg -n "machineBrand|machineBrandOther|設備品牌|設備型號" index.html apps-script tools
rg -n --pcre2 "\$\('(rpm|diameter|kerf|teeth)'\)\.value\s*=" index.html
git diff --check
```

Expected: brand properties appear only in collection, formatting, follow-up and persistence paths; the assignment search has no output; `git diff --check` has no output.

- [ ] **Step 3: Verify UTF-8 without BOM**

Run:

```powershell
$paths=@('index.html','apps-script\Core.gs','apps-script\Code.gs'); foreach($path in $paths){$bytes=[System.IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $path)); $bom=($bytes.Length -ge 3)-and $bytes[0]-eq 239-and $bytes[1]-eq 187-and $bytes[2]-eq 191; "$path BOM=$bom"}
```

Expected: every file reports `BOM=False`.

- [ ] **Step 4: Perform desktop and mobile interaction checks in the local page**

Use the in-app browser at desktop width and a mobile viewport near 390 px. Verify:

1. Brand options are exactly the approved five values plus the empty prompt.
2. Selecting 其他 reveals the other-brand field; entering text and switching to 日意 clears and hides it.
3. Entering brand and model, then submitting a valid consultation, does not show either field under 「鋸片醫生希望您能提供」.
4. Leaving brand and model empty shows both precise follow-ups but still allows initial diagnosis and registration after required contact/consent fields are supplied.
5. Selecting 不確定 does not ask for brand again; an empty model still asks for model or machine-nameplate photo.
6. Changing brand never changes RPM, diameter, kerf, teeth or other technical inputs.
7. At mobile width there is no horizontal overflow and the reading order remains diagnosis, additional information, registration/LINE handoff.

- [ ] **Step 5: Re-run the complete suite after any browser-found fix**

Run the four Node test commands from Step 1 and `git diff --check` again.

Expected: all pass; no whitespace errors.

- [ ] **Step 6: Commit verification fixes if any exist**

```powershell
git add -- index.html apps-script/Core.gs apps-script/Code.gs tools
git commit -m "test: verify equipment brand intake"
```

If `git status --short` is empty after verification, do not create an empty commit.
