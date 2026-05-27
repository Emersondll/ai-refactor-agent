# Execution Evidence — R7

**Start:** 2026-05-14T22:30:17  
**Branch:** refactor/ai-agent-automation  
**Initial coverage:** 72.51%

---

## Checkpoint 1 — 23:12 (42 min)

### Phase: initial_coverage_fix

| File | Status | Time | Observation |
|---|---|---|---|
| BalanceDocumentTest.java | ✅ ACCEPTED | 9 min | model cold start |
| MerchantDocumentTest.java | ✅ ACCEPTED | 4 min | — |
| TransactionDocumentTest.java | ✅ ACCEPTED | 4:27 min | — |
| MerchantCategoryCodesDocumentTest.java | ✅ ACCEPTED | 4:13 min | Enum hallucination fix ✓ |
| TransactionControllerTest.java | ❌ REVERTED | 21:11 min | 3 repairs — 3 distinct errors |
| TransactionCodeModelTest.java | ⚠️ under repair | — | ASSERTION ERROR |

---

### Detailed analysis: TransactionControllerTest.java

The LLM generated 3 different versions with 3 distinct bugs — it does not learn between attempts:

| Repair | Error | Root cause |
|---|---|---|
| 1 (22:56) | `cannot find symbol: Hamcrest` + `constructor TransactionModel wrong args` | Non-existent import + record with wrong args |
| 2 (23:04) | `package com.example.model does not exist` | **Package hallucination** — gemma4 invented `com.example.*` instead of `com.caju.*` |
| 3 (23:13) | `reached end of file` + `try without catch` | **Truncated output** — output exceeded `num_predict: 4096` |

**Pattern:** each repair starts from scratch with no memory of what was tried before. The error history exists in the prompt, but the LLM ignores it and introduces new bugs.

---

### Detailed analysis: TransactionCodeModelTest.java

```
testEdgeCaseEmptyCode:52 expected: <true> but was: <false>
```

**Cause:** The LLM generated a test that assumes `isEmpty()` returns `true` for empty code, but the implementation returns `false`. The LLM tested the DESIRED behavior, not the ACTUAL one. The `java-tdd-unit-test` skill has a rule "test only current behavior" but it is ignored in edge cases.

---

## Improvement Plan Identified

### M1 — New `TRUNCATED_OUTPUT` category in `_categorize_build_error` ⚡ CRITICAL
- **Trigger:** `reached end of file while parsing` OR `'try' without 'catch'`
- **Repair instruction:** `"The previous output was TRUNCATED before completion. Complete the file: add the missing catch/finally block and ALL closing braces needed. Do NOT rewrite — only close what is open."`
- **File:** `java/refactor.py` → `_categorize_build_error()`

### M2 — Increase `num_predict` for test mode ⚡ CRITICAL
- **Cause:** `call_model()` uses `num_predict: 4096` for all modes. Large test files exceed the limit
- **Fix:** add `num_predict` parameter to `call_model()`, `test` mode → `8192`
- **File:** `ai/model.py`

### M3 — Inject explicit package into repair prompt ⚡ CRITICAL
- **Cause:** in repair 2, gemma4 hallucinated `com.example.model` instead of `com.caju.transactionauthorizer`. The repair prompt does not reinforce the correct package
- **Fix:** in `_build_validator_correction_prompt()`, inject `"MANDATORY: package declaration MUST be exactly: package com.caju.transactionauthorizer.controller;"` extracted from the original file
- **File:** `ai/model.py` → `_build_validator_correction_prompt()`

### M4 — Assertion error: reinforce "test current behavior" in repair ⚡ IMPORTANT
- **Cause:** the `ASSERTION ERROR` category instructs the LLM to fix the expected value, but does not make it clear that it must mentally execute the code to discover the actual value
- **Fix:** add to the repair instruction: `"Run the method mentally with the test input and use the ACTUAL return value as the expected value. Do NOT guess what 'should' happen."`
- **File:** `java/refactor.py` → `_categorize_build_error()`

### M5 — Early truncated output detection in `clean_output` (PREVENTIVE)
- **Fix:** after extracting the java block, count `{` vs `}` — if unbalanced, reject before Maven
- **File:** `ai/sanitizer.py`

### M6 — Persistence of recurring failures between runs (PERFORMANCE)
- **Observation:** TransactionControllerTest fails in 100% of runs (R1→R7) — 21 min burned per run
- **Fix:** `failed_files.json` should not clear `permanent_skip` entries on `reset()`. After 3 consecutive runs, skip automatically
- **File:** `java/refactor.py` → `FailedFilesTracker`

---

## Checkpoint 2 — 00:07 (Pipeline Completed)

### Pipeline R7 — COMPLETE

| Phase | Start | End | Status |
|---|---|---|---|
| HEALTH_CHECK | 22:30 | 22:30 | ✅ |
| AUDIT_COVERAGE (72.51%) | 22:30 | 22:30 | ⚠️ below 90% |
| initial_coverage_fix | 22:30 | 00:04 | 8 accepted, 2 reverted |
| SANITIZATION | 00:06 | 00:07 | ✅ |
| FINAL_VALIDATION | 00:07 | 00:07 | ✅ 92.57% |
| COMMIT_PUSH | 00:07 | — | ✅ |

**Coverage:** 72.51% → 92.12% (post-generation) → **92.57%** (final) ✅

### Confirmed Failures

| File | Time | Terminal cause |
|---|---|---|
| TransactionControllerTest.java | 21 min | `reached end of file` — truncated output (num_predict: 4096) |
| MerchantCategoryCodesServiceImplTest.java | 23 min | Package hallucination (`com.example.service` instead of `com.caju.*`) |

### Critical observation
Phases 09–14 (semantic LLM refactoring) **were not executed** — the pipeline was only in the coverage phase (generate_tests). The 6 refactoring skills are still awaiting their first real test.

---

*Monitoring ended. See `implementation_plan.md` for next steps.*
