# Implementation Plan — Post-R7 Improvements

**Generated:** 2026-05-15  
**Based on:** Run R7 (2026-05-14 22:30 → 2026-05-15 00:07)

---

## R7 Executive Summary

| Metric | Value |
|---|---|
| Total duration | 1h37min |
| Initial coverage | 72.51% |
| Post-generation coverage | 92.12% |
| Final coverage | **92.57%** ✅ (target: 90%) |
| Files started | 10 |
| Accepted | 8 (80%) |
| Reverted | **2 (20%)** |
| Time wasted on reverted | ~46 min (50% of total time) |
| LLM phases executed (09–14) | **ZERO** — pipeline stopped before |

---

## Failures Documented in R7

### Failure 1 — TransactionControllerTest.java
**Duration:** 22:52 → 23:13 = **21 min** | **3 repairs, 3 distinct errors**

| Repair | Error | Root cause |
|---|---|---|
| 1 | `cannot find symbol: Hamcrest` + wrong constructor | Import hallucination + record without args |
| 2 | `package com.example.model does not exist` | **Package hallucination** — gemma4 invented `com.example.*` |
| 3 | `reached end of file while parsing` / `try without catch` | **Truncated output** — `num_predict: 4096` exceeded |

**Category returned by `_categorize_build_error`:** generic (does not recognize truncation)  
**Result:** reverted — file does not exist in the project

---

### Failure 2 — MerchantCategoryCodesServiceImplTest.java
**Duration:** 23:32 → 23:55 = **23 min** | **3 repairs**

**Terminal error:**
```
IMPORT ERROR: Class 'class MerchantRepository' not found.
location: class com.example.service.MerchantServiceTest
```

**Root cause:**  
Double package hallucination: the LLM generated the file as `com.example.service.MerchantServiceTest`  
instead of `com.caju.transactionauthorizer.service.impl.MerchantCategoryCodesServiceImplTest`.  
The repair prompt does not reinforce the correct package and class.

---

## Structural Root Cause — Why Repairs Fail

The current repair loop has an architectural problem: **each repair attempt starts with the original code**, not with the code from the previous attempt that almost worked. The error history goes into the prompt, but:

1. The LLM ignores prior errors and introduces different bugs
2. Without an explicit package anchor in the repair prompt, the LLM "forgets" the correct package
3. Large files truncate silently — the validator only detects this after Maven

---

## Implementation Plan (Decreasing Priority)

### M1 — New `TRUNCATED_OUTPUT` category in `_categorize_build_error`
**Priority:** 🔴 CRITICAL  
**File:** `java/refactor.py` → function `_categorize_build_error()`  
**Trigger:** `"reached end of file while parsing"` OR `"'try' without 'catch'"` in Maven output  
**Position:** Insert BEFORE the generic fallback (last line)

**Repair instruction to return:**
```python
return (
    "TRUNCATED OUTPUT: Your previous code was cut off before completion.\n"
    "DO NOT rewrite the entire file.\n"
    "ONLY add the missing closing braces `}`, catch/finally blocks, and semicolons "
    "to complete what was already written.\n"
    "Count open `{` vs closed `}` in your previous output and close the difference."
)
```

**Expected impact:** avoids 1 repair cycle with a generic error, directs the model to fix only the end of the file.

---

### M2 — `num_predict: 8192` for `test` mode
**Priority:** 🔴 CRITICAL  
**File:** `ai/model.py` → function `call_model()`  
**Change:** add parameter `num_predict: int = 4096` and pass `8192` when `mode == "test"`  

**How the pipeline passes the mode:**  
`_run_pipeline()` receives `mode` but `call_model()` does not receive it. The chain is:  
`call_ai(mode)` → `_run_pipeline(mode)` → `_try_local_agent()` → `call_model()`

**Solution:** add `num_predict` as a parameter in `call_model` and `_try_local_agent`. In `_run_pipeline`, detect `mode == "test"` and pass `num_predict=8192`.

**Expected impact:** eliminates truncations in test files with 80–150 lines.

---

### M3 — Inject package and class name into repair prompt
**Priority:** 🔴 CRITICAL  
**File:** `ai/model.py` → `_build_validator_correction_prompt()`  
**Change:** receive `original_code: str` as an additional parameter and extract the package via regex.

**Logic to add:**
```python
import re
pkg_match = re.search(r'^(package\s+[\w.]+;)', original_code, re.MULTILINE)
package_line = pkg_match.group(1) if pkg_match else ""

class_match = re.search(r'(?:public\s+)?(?:class|interface|record|enum)\s+(\w+)', original_code)
class_name = class_match.group(1) if class_match else ""
```

**Text to inject at the top of the correction prompt:**
```
### MANDATORY CONSTRAINTS (non-negotiable)
- Package MUST be exactly: {package_line}
- Class name MUST be exactly: {class_name}
- Do NOT use com.example.*, com.test.*, or any invented package.
```

**Expected impact:** eliminates the package hallucination that caused repair 2 in both failures.

---

### M4 — Reinforce ASSERTION ERROR instruction
**Priority:** 🟡 IMPORTANT  
**File:** `java/refactor.py` → `_categorize_build_error()` → `assertionerror` block  
**Change:** add explicit line about "running mentally":

```python
return (
    f"ASSERTION ERROR: The expected value in the test is wrong.\n"
    f"Detail: {line.strip()}\n"
    "Run the method mentally with the test input to find the ACTUAL return value.\n"
    "Fix assertEquals/assertThat to match what the method ACTUALLY returns NOW.\n"
    "Do NOT guess what 'should' happen — test current behavior, not desired behavior."
)
```

---

### M5 — Early truncated output detection in `clean_output`
**Priority:** 🟡 IMPORTANT  
**File:** `ai/sanitizer.py` → `_finalize()`  
**Change:** after extracting the java block, verify brace balance:

```python
def _is_balanced(code: str) -> bool:
    open_b = code.count('{')
    close_b = code.count('}')
    return open_b == close_b

# At the end of _finalize(), before the return:
if not _is_balanced(code):
    return None  # reject truncated output before Maven
```

**Expected impact:** detects truncation **before** calling `mvn compile`, saving 30–60s per attempt.

---

### M6 — Permanent skip persistence between runs
**Priority:** 🟢 PERFORMANCE  
**File:** `java/refactor.py` → `FailedFilesTracker`  
**Rule:** if a file has been reverted in 3+ consecutive runs, add flag `permanent_skip: true`.  
**In `reset()`:** clear only entries without `permanent_skip: true`.  
**In `generate_tests()`/`_refactor_whole_file()`:** check `is_permanent_skip(file_path)` before processing.

**JSON structure:**
```json
{
  "file": "...TransactionControllerTest.java",
  "permanent_skip": true,
  "skip_reason": "3 consecutive runs without success",
  "fail_count": 7
}
```

**Expected impact:** saves 21 min per run on TransactionControllerTest (7 runs × 21 min = **147 min wasted so far**).

---

## Additional Root Cause — TransactionController (Field Injection)

`TransactionController` uses `@Autowired private TransactionService service` (field injection).  
This makes the test without Spring context **impossible to write elegantly** — there is no public constructor with injection.

**Impact:** the LLM generates MockMvc or Spring context (@WebMvcTest) because it is the only "natural" way out, but the skill prohibits both. Result: guaranteed failure loop.

**Structural solution:** phase 11 (SOLID DIP) converts field injection → constructor injection.  
But the test phase comes BEFORE refactoring. **The current pipeline order is the problem.**

**Proposal M7 — New intelligent skip option by architecture type:**  
If the test file depends on a production file with field injection (`@Autowired` without a constructor), mark it as `deferred_skip` and process AFTER phase 11.

---

### M8 — Complementing existing tests with partial coverage
**Priority:** 🟡 IMPORTANT  
**File:** `java/refactor.py` → `generate_tests()`  
**Status:** to be implemented before R9

**Current problem:**  
The pipeline uses `if os.path.exists(test_path): continue` — completely ignores any test file that already exists, even if the class coverage is 30%. Classes like `TransactionServiceImpl` have an existing test (`TransactionServiceImplTest.java`) but probably do not cover all scenarios.

**Desired behavior:**  
If the test file already exists BUT the coverage of the corresponding production class is below the threshold (90%), the pipeline should **read the existing test** and **ask the LLM to add** the missing cases — without rewriting the existing ones.

**Technical implementation:**

```python
# In generate_tests(), replace the simple skip with:
if os.path.exists(test_path):
    # Check coverage for the specific class
    _, _, coverage, missed_lines = maven_test_with_coverage(repo_path, file_name)
    if coverage >= 90.0 or not missed_lines:
        continue  # coverage OK — no need to complement
    # Complement: pass existing test + uncovered lines
    existing_test = read_file(test_path)
    complement_rules = (
        f"{rules}\n\n"
        "### EXISTING TESTS (DO NOT MODIFY OR REMOVE)\n"
        f"```java\n{existing_test}\n```\n\n"
        "### UNCOVERED LINES\n"
        f"Lines not covered: {missed_lines}\n\n"
        "ADD new @Test methods to cover the uncovered lines above.\n"
        "NEVER remove or modify existing @Test methods.\n"
        "Return the COMPLETE file with all existing tests plus the new ones."
    )
    # Use complement_rules instead of rules for generation
```

**Risk:** medium — modifying existing tests may break assertions. Mitigation: the instruction "NEVER remove or modify existing @Test methods" + `mvn test` validation guarantees the pipeline reverts if something breaks.

**Expected impact:**  
- Raises coverage of already partially covered classes to ≥90%
- Eliminates the case where `generate_tests` ends without reaching the target because all classes already have tests (but partial)
- Especially relevant for `TransactionServiceImpl` (complex logic with MCC category switch)

---

## Recommended Implementation Sequence

```
M5 (detect truncated before Maven)     — lowest risk, no side effects
  ↓
M2 (num_predict 8192 for test)         — resolves truncation at the source
  ↓
M3 (package injection in repair prompt) — resolves package hallucination
  ↓
M1 (TRUNCATED_OUTPUT category)         — fallback when M2+M5 are not enough
  ↓
M4 (assertion error reinforcement)     — qualitative repair improvement
  ↓
M6 (persistent skip)                   — performance optimization
  ↓
M7 (deferred skip by field injection)  — long-term architectural improvement
  ↓
M8 (complementing existing tests)      — increases coverage of partially tested classes
```

---

## Expected Impact Estimate (R8)

| Metric | R7 current | R8 estimated |
|---|---|---|
| Acceptance rate | 80% (8/10) | ~90% (9/10) |
| Time wasted | ~46 min | ~10 min |
| Final coverage | 92.57% | ~95% |
| Files without test (reverted) | 2 | 0–1 |
| Estimated total time | 1h37min | ~1h10min |

---

## Files to Modify

| File | Improvements | Risk | Status |
|---|---|---|---|
| `java/refactor.py` | M1, M4 | Low — only adds new cases | ✅ Implemented |
| `ai/model.py` | M2, M3 | Medium — changes function signatures | ✅ Implemented |
| `ai/sanitizer.py` | M5 | Low — only rejects earlier | ✅ Implemented |
| `java/refactor.py` | M6 (FailedFilesTracker) | Medium — changes persistent state | ✅ Implemented |
| `java/refactor.py` | M7 (deferred field injection) | Low — conditional skip | ✅ Implemented |
| `java/refactor.py` | M8 (test complementation) | Medium — modifies existing tests | ✅ Implemented |

---

## Post-Implementation Validation Tests

Before starting R8:
1. `sdk use java 22-open && cd repos/card-transaction-authorizer && mvn test -q` — confirm clean build
2. Verify that `failed_files.json` has been reset (only M6 may keep permanent entries)
3. Confirm that `live_state.json` is `{"active_skill": "", "current_model": "gemma4:latest"}`

---

## Failures Documented in R15 (2026-05-15)

> **Status (2026-05-15):** C21 and C22 implemented. C23 verified. C24-C26 implemented in the same session.

### Failure C21 — TransactionCodeModelTest.java (RECURRENCE)
**Time:** 18:15:00 → 18:34:57 = **19 min** | result: FILE_REVERTED  
**Terminal error:** `COMPILATION/EXECUTION ERROR` — exhausted 3 repairs without success  
**Confirmed root cause:** same pattern as R14 — gemma4 does not know that `TransactionCodeModel` is a Java `record`, generates:
- Incorrect equality assertions for `record` with empty string
- `toString()` assertions expecting `"ABC"` but `record` returns `TransactionCodeModel[code=ABC]`
- Eventually generates "implicitly declared classes" (Java 21 preview) — code without `package` + `class` declaration

**Impact:** 19 min wasted per run. With M1–M8 already implemented, this file still fails — indicates that the existing repairs do not know the semantics of `record`.

**Proposed fix (do not implement):**
Inject information into the test generation prompt that the target class is a `record`:
```
# In _build_test_prompt() — before calling call_ai():
if re.search(r'\brecord\s+\w+', production_code):
    extra = (
        "\n### JAVA RECORD SEMANTICS\n"
        "This class is a Java RECORD. Records auto-generate:\n"
        "- equals/hashCode based on all fields\n"
        "- toString() returning 'ClassName[field1=val1, field2=val2]'\n"
        "- An all-args canonical constructor\n"
        "NEVER assert toString() returns just the field value — it always includes the class name.\n"
    )
    rules += extra
```

---

### Failure C22 — TransactionModelTest.java (NEW)
**Time:** 18:34:57 → 19:01:58 = **27 min** | result: FILE_REVERTED  
**Terminal error:** `IMPORT ERROR: Class 'class TransactionModel' not found.`  
**Category returned:** IMPORT ERROR — 3 repair attempts, all failed  
**Root cause:** Package hallucination — same pattern as M3 (already implemented), but M3 injects the package into the **repair** prompt. The error persists because:
1. The LLM generated the initial file with the wrong package
2. The M3 repair injects the correct package, but the LLM hallucinates the import of the production class (`TransactionModel`) with a non-existent package
3. `TransactionModel` may also be a `record` — the LLM does not know the correct import

**Proposed fix (do not implement):**
In the **initial generation** prompt (not just the repair), inject the imports of the classes referenced in the production class:
```python
# In _build_test_prompt():
import_block = _extract_imports(production_code)  # extracts "import com.caju...."
rules += f"\n### REQUIRED IMPORTS (use these exactly)\n{import_block}\n"
```

---

### C23 — Cumulative time cost per file with 3 repairs (SYSTEMIC RISK)
**Observation:** In R15, just the two files above wasted **19 + 27 = 46 min** — identical to R7 and R14.  
M6 (persistent skip) is implemented — verify if it is being activated correctly for these files.  

**Pending diagnosis:** Check if `failed_files.json` after R15 marks these two files with `permanent_skip: true`.  
If not working, the cause may be that `reset()` clears entries between runs even with `permanent_skip`.

---

## Recommended Implementation Sequence (post-R15)

```
C21 (inject record semantics into generation prompt)   — resolves 100% of TransactionCodeModelTest errors
  ↓
C22 (inject production class imports into prompt)      — resolves import hallucination in TransactionModelTest
  ↓
C23 (verify if M6 permanent_skip is activating)        — diagnosis before implementing new logic
```

---

*Plan generated from analysis of `execution.jsonl`, `execution.log` and `failed_files.json` from R7.*  
*Section C21–C23 added after monitoring R15 on 2026-05-15.*
