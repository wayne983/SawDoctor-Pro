# Machine Type and Brand Options Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional machine-type selection with the approved category-specific brand lists and preserve the selection through diagnosis, LINE, email and registration storage.

**Architecture:** Keep the static single-page frontend and Apps Script backend. Add a pure `machineBrandsForType(type)` mapping to the existing browser core, drive the dependent brand select from that mapping, and append `machineType` to existing payload and persistence paths without changing required-field validation or technical diagnosis rules.

**Tech Stack:** HTML/CSS/vanilla JavaScript, Google Apps Script, Node.js built-in test harnesses.

**Spec:** `docs/superpowers/specs/2026-09-01-machine-type-brand-options-design.md`

## Global Constraints

- Machine type, brand and model remain optional for diagnosis and registration.
- Brand lists and spelling must exactly match the approved Traditional Chinese design.
- UI displays `其它`; payload retains `其他` for existing compatibility.
- Changing machine type clears stale brand and other-brand values.
- No machine selection may infer or overwrite RPM, diameter, kerf, teeth or capacity.
- Spreadsheet history must not move; append `機台種類` as the final column.
- Preserve Apps Script anonymous web-app access in `appsscript.json`.

---

### Task 1: Add machine-type domain behavior

**Files:**
- Modify: `tools/sawdoctor-core.test.js`
- Modify: `index.html`

**Interfaces:**
- Consumes: `machineType` string.
- Produces: `machineBrandsForType(type) -> string[]`; machine-type-aware follow-ups and LINE summary.

- [ ] Write literal tests for all four approved brand lists, an empty unknown list, completed/missing machine-type follow-ups, and the LINE `機台種類` line.
- [ ] Run `node tools/sawdoctor-core.test.js`; verify failure because `machineBrandsForType` is absent.
- [ ] Add the frozen mapping, exported lookup function, follow-up rule and LINE summary line.
- [ ] Run `node tools/sawdoctor-core.test.js`; verify pass.

### Task 2: Add dependent optional selects

**Files:**
- Modify: `tools/sawdoctor-ui.test.js`
- Modify: `index.html`

**Interfaces:**
- Consumes: `machineBrandsForType()` from Task 1.
- Produces: `#machine-type`, dependent `#machine-brand`, existing `#machine-brand-other`, and payload `machineType`.

- [ ] Add UI tests for the machine-type field, four categories, dependent-brand synchronization, stale-value clearing, `其它` display with `其他` value, and payload collection.
- [ ] Run `node tools/sawdoctor-ui.test.js`; verify expected failure.
- [ ] Add the optional machine-type select and `syncMachineBrandOptions()`; populate brands with `Option`, clear stale values, and reuse `syncMachineBrandOther()`.
- [ ] Add `machineType` to `collectAdvancedInput()` without changing validation.
- [ ] Run UI and core tests; verify pass.

### Task 3: Persist machine type in the backend

**Files:**
- Modify: `tools/sawdoctor-backend.test.js`
- Modify: `tools/sawdoctor-registration.test.js`
- Modify: `apps-script/Core.gs`
- Modify: `apps-script/Code.gs`

**Interfaces:**
- Consumes: `payload.machineType`.
- Produces: Email `機台種類` line and final spreadsheet `機台種類` column.

- [ ] Add backend test proving Email includes exactly one `機台種類` line.
- [ ] Add registration tests proving the final header/value are `機台種類`/selected type and all older indexes stay fixed.
- [ ] Run both tests; verify failures because backend persistence is absent.
- [ ] Add the Email line, append the header, repair only the missing final header, and append payload value to new rows.
- [ ] Run backend and registration tests; verify pass.

### Task 4: Verify and publish

**Files:**
- Modify only if verification exposes a defect.

**Interfaces:**
- Produces: merged GitHub Pages frontend and updated existing Apps Script deployment.

- [ ] Run all four Node test suites and `git diff --check`.
- [ ] Verify embedded JavaScript syntax and confirm no assignment writes machine choices into RPM/specification fields.
- [ ] Verify UTF-8 without BOM and inspect the mobile layout locally where browser tooling permits.
- [ ] Review the diff, commit, push, merge to `main`, and verify the GitHub Pages source contains the new machine-type control.
- [ ] Deploy `Code.gs`, `Core.gs`, and the preserved `appsscript.json` to the existing Apps Script deployment; verify anonymous POST validation remains reachable.
