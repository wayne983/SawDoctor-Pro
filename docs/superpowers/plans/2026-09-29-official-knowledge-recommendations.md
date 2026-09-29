# Official Knowledge Recommendations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 勝榆 to aluminum-machine brands, clarify the free-text blade-brand field, and show up to three relevant official HAWER knowledge links after the preliminary assessment.

**Architecture:** Keep the existing single-page architecture in `index.html`. Add a curated immutable article catalog and a pure `getKnowledgeRecommendations(input)` selector to `SawDoctorCore`, then render its results in a dedicated card beneath the assessment and product recommendation. Preserve all registration, Email, LINE, and backend interfaces.

**Tech Stack:** Static HTML/CSS, vanilla JavaScript, Node.js assertion tests, GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-09-29-official-knowledge-recommendations-design.md`

## Global Constraints

- Do not fetch or scrape the HAWER website at customer runtime.
- Show no more than three unique official article URLs.
- Keep danger messaging and official LINE human review ahead of selling; product recommendations remain hidden for danger assessments.
- Keep `brand` as the existing optional free-text field and do not change backend, spreadsheet, registration, or Email schemas.
- Preserve all existing registration, dual-recipient Email, and LINE behavior.
- Use only verified `https://www.hawer-knife.com/` URLs from the spec.

## Review Focus

- Multiple selected issues that map to the same URL must render that article once; Task 1 tests deduplication.
- Material-specific cases must outrank general articles without excluding useful general articles; Task 1 tests aluminum and plastic ordering.
- A fresh assessment must fully replace earlier recommendations; Task 2 tests render clearing and replacement.
- Danger assessments must not surface product sales and may only surface explicitly safety-eligible reading; Tasks 1 and 2 test both gates.
- Long Traditional-Chinese titles on narrow screens must wrap without horizontal overflow; Task 2 tests the responsive CSS contract.

---

### Task 1: Curated Recommendation Selector and Aluminum Brand

**Files:**
- Modify: `index.html` (`machineBrandsByType`, core catalog, core selector, core export)
- Modify: `tools/sawdoctor-core.test.js`

**Interfaces:**
- Consumes: `normalizeSelection(values)`, `classifyRisk(issues)`, and quick-input fields `{material, issues, cutDirection}`.
- Produces: `getKnowledgeRecommendations(input = {}) -> ReadonlyArray<{id, source, title, url, reason}>` and the updated `machineBrandsForType('鋁用')` result.

- [ ] **Step 1: Write failing tests for the aluminum brand and selector contract**

Add assertions that:

- `machineBrandsForType('鋁用')` returns `日意、鋒和、冠盛、和和、慶祥、合濟、中勝、昱帆、勝榆、其他` in that order.
- `getKnowledgeRecommendations({material:'aluminum', issues:['毛邊多','黏屑塞齒']})` returns three unique official URLs, with the aluminum clogging article before general articles.
- Plastic毛邊 includes the PVC case before general fallback content.
- Repeated issue matches never duplicate a URL and never exceed three results.
- Empty or unsupported issues return an empty frozen-compatible array.
- `發燙冒煙` returns only the three-article whitelist from the spec; `噪音震動` returns only its separate three-article whitelist. A danger issue combined with another issue never adds a non-whitelisted article.

- [ ] **Step 2: Run the core test and verify the new assertions fail**

Run: `node tools/sawdoctor-core.test.js`

Expected: FAIL because `勝榆` and `getKnowledgeRecommendations` are not present.

- [ ] **Step 3: Add the curated article catalog**

In `index.html`, define an immutable catalog matching the exact titles, URLs, issues, materials, reasons, table-order priority, and danger whitelist in the spec. Keep the catalog inside the `sawdoctor-core` closure and do not expose mutable catalog objects.

- [ ] **Step 4: Implement the selector**

Implement `getKnowledgeRecommendations(input = {})` in `index.html`. Normalize issues, score issue overlap plus material specificity, filter danger results by explicit safety eligibility, sort deterministically, deduplicate by URL, limit to three, clone returned items, and export the function on `globalThis.SawDoctorCore`.

- [ ] **Step 5: Add 勝榆 to the aluminum machine list**

Insert `勝榆` between `昱帆` and `其他` in `machineBrandsByType['鋁用']`.

- [ ] **Step 6: Run the core test and verify it passes**

Run: `node tools/sawdoctor-core.test.js`

Expected: `SawDoctorCore diagnosis tests passed`.

- [ ] **Step 7: Commit the core behavior**

```bash
git add index.html tools/sawdoctor-core.test.js
git commit -m "feat: add official knowledge recommendation logic"
```

### Task 2: Recommendation UI, Blade-Brand Copy, and Mobile Layout

**Files:**
- Modify: `index.html` (markup, CSS, application rendering, quick-state reset)
- Modify: `tools/sawdoctor-ui.test.js`

**Interfaces:**
- Consumes: `core.getKnowledgeRecommendations(quickState)` from Task 1.
- Produces: `renderKnowledgeRecommendations(recommendations)` that clears stale content, hides an empty card, and safely creates article elements with DOM APIs.

- [ ] **Step 1: Write failing UI contract tests**

Add assertions that:

- The label reads `鋸片品牌（自行填寫）` and the input remains `id="brand" name="brand"`.
- The page contains a hidden `knowledge-recommendations` section titled `鋸片醫生延伸閱讀`.
- `renderKnowledgeRecommendations()` uses `replaceChildren()` before rendering and hides the card for an empty list.
- Each generated link uses `target="_blank"`, `rel="noopener"`, and the copy `查看官網文章`.
- `invalidateQuickState()` clears both product and knowledge recommendations.
- Quick-form submission calls the selector and renderer after the assessment.
- Danger submission clears product recommendations and renders only the selector's danger-safe results.
- Responsive CSS allows card titles and links to wrap and keeps the new card in the result column after the diagnosis.

- [ ] **Step 2: Run the UI test and verify the new assertions fail**

Run: `node tools/sawdoctor-ui.test.js`

Expected: FAIL because the new knowledge section and renderer do not exist.

- [ ] **Step 3: Add semantic recommendation markup and responsive styles**

Add one hidden knowledge container after the existing product card. Style a single-column list of article cards with source label, wrapping title, reason, and full-width mobile link. Do not insert raw HTML from the catalog.

- [ ] **Step 4: Implement rendering and state updates**

Implement `renderKnowledgeRecommendations(recommendations)`. Call it with an empty array from `invalidateQuickState()`, and with `core.getKnowledgeRecommendations(quickState)` after each valid quick assessment. Keep assessment scrolling behavior unchanged.

- [ ] **Step 5: Clarify the blade-brand label**

Change only the visible label to `鋸片品牌（自行填寫）`; preserve the existing input ID, name, optional behavior, payload field, and follow-up logic.

- [ ] **Step 6: Run the UI and core tests and verify they pass**

Run:

```bash
node tools/sawdoctor-ui.test.js
node tools/sawdoctor-core.test.js
```

Expected: both scripts print their `passed` messages.

- [ ] **Step 7: Commit the UI behavior**

```bash
git add index.html tools/sawdoctor-ui.test.js
git commit -m "feat: show official reading recommendations"
```

### Task 3: Regression, Link Verification, Review, and GitHub Pages Release

**Files:**
- Modify only if verification exposes a defect: `index.html`, `tools/*.test.js`

**Interfaces:**
- Consumes: completed branch behavior from Tasks 1 and 2.
- Produces: a tested branch merged to `main` and a verified GitHub Pages deployment.

- [ ] **Step 1: Run the complete local regression suite**

Run:

```bash
node tools/sawdoctor-core.test.js
node tools/sawdoctor-ui.test.js
node tools/sawdoctor-backend.test.js
node tools/sawdoctor-registration.test.js
git diff --check origin/main...HEAD
```

Expected: all four tests pass and `git diff --check` has no output.

- [ ] **Step 2: Verify every configured official URL**

Perform read-only HTTP checks for each configured `hawer-knife.com` URL. Require a successful page response and confirm the expected title text where the legacy site exposes it. Remove or correct broken links before release.

- [ ] **Step 3: Perform whole-branch review**

Review the diff against the spec with emphasis on safe DOM construction, danger gating, deterministic ordering, mobile layout, and unchanged registration/backend contracts. Fix findings with focused tests and commit each correction.

- [ ] **Step 4: Publish through the existing GitHub workflow**

Push `codex/content-recommendations`, create a pull request, attach it to the task, merge only after checks pass, and confirm GitHub Pages is serving the merged `main` revision.

- [ ] **Step 5: Verify the public page**

On `https://wayne983.github.io/SawDoctor-Pro/`, confirm:

- 鋁用設備品牌 includes 勝榆.
- The blade-brand label says 自行填寫.
- A representative aluminum multi-issue assessment shows at most three unique official articles.
- A danger scenario still hides product recommendations and preserves the stop/LINE flow.
- Mobile layout has no horizontal overflow.

- [ ] **Step 6: Record final evidence**

Report the merged commit, public URL, exact test outputs, deployment evidence level, and any article URL that could not be independently verified.
