# Pipeline Fixes F/G/H/I — Timestamp, Soul Language, Validator PT, Permanent-Skip Expiry

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 problem classes identified in the 2026-05-22 execution: `java.sql.Timestamp` error in generated tests; mixed LLM instructions (PT + EN); Portuguese messages in the validator; and `permanent_skip` entries from already-fixed bugs blocking valid files.

**Architecture:** All changes are in Python pipeline files. No changes to the target Java project. Three main files touched: `soul.md`, `java/refactor.py`, `java/validator.py`.

**Tech Stack:** Python 3.12, regex, `java/refactor.py` (active_rules + `_categorize_build_error` + `FailedFilesTracker`), `soul.md`, `java/validator.py`.

---

## Problem Diagnosis

### Problem 1 — `java.sql.Timestamp` wrong format in tests (ACTIVE NOW)

**Captured error:**
```
TransactionDocumentTest.setUp:29 » IllegalArgument Timestamp format must be yyyy-mm-dd hh:mm:ss[.fffffffff]
```

**Root cause:** `TransactionDocument.java` declares `private Timestamp timestamp` with `import java.sql.Timestamp`. The LLM generates setUp with:
```java
this.timestamp = Timestamp.valueOf("2023-01-15T10:00:00"); // WRONG — "T" is ISO, not SQL
```
The correct format for `Timestamp.valueOf()` is `"yyyy-mm-dd hh:mm:ss"` (space between date and time, **without** `T`).

**Gaps in current code:**
- `_JDK_IMPORT_MAP` in `refactor.py:52` does not have `Timestamp` → `_auto_inject_missing_imports` does not inject `import java.sql.Timestamp;`
- No preventive rule in `active_rules` for classes with `java.sql.Timestamp`
- `_categorize_build_error` has no handler for `IllegalArgumentException` with Timestamp format message → falls back to generic fallback

**Affected files:**
- `java/refactor.py` — `_JDK_IMPORT_MAP` (~line 52), `active_rules` section (~line 1492), `_categorize_build_error` (~line 140)

---

### Problem 2 — `soul.md` in Portuguese: mixed LLM instructions

**Root cause:** `soul.md` (loaded as `_SOUL` in `ai/prompt.py:23` and injected at the TOP of ALL prompts) is **100% in Portuguese**. Meanwhile, all `BASE_CONSTRAINTS`, `BASE_CONSTRAINTS_TEST`, and `active_rules` sections built in `refactor.py` are in **English**.

Result: every prompt sent to the LLMs starts in Portuguese and ends in English. This is a structural inconsistency — multilingual LLMs have more stable behavior when the language of instructions is uniform.

**Current prompt structure (mixed language):**
```
[SOUL — Portuguese]
You are a senior Java engineer...
You never invent, never assume...

[BASE_CONSTRAINTS — English]
### TECHNICAL CONSTRAINTS (MANDATORY)
PRESERVE the package declaration exactly as-is...

[active_rules — English]
### TEST CLASS — MANDATORY NAME AND PACKAGE...
```

**Note:** `report_runner.py:188` has `"Write in Brazilian Portuguese"` — this is **correct** and **must remain** (the final report is for the user, not for the refactoring/test LLM).

**Affected files:**
- `soul.md` — translate to English, keep all behavioral content

---

### Problem 3 — `validator.py` with Portuguese messages

**Root cause:** `java/validator.py` lines 236 and 238 return Portuguese messages:
```python
# line 236:
return False, f"O arquivo se chama '{file_name}.java' mas você gerou a classe '{found_name}'."
# line 238:
return False, f"Não foi encontrada a classe '{file_name}' no código gerado."
```

These messages **do not reach the LLM** directly (in `refactor.py:766-773` the `reason` is replaced by an English message before calling the LLM). But they appear in two places:
1. `failed_files.json` — as `reason` for `permanent_skip` entries from prior runs (e.g. `MerchantCategoryCodesServiceImplTest`)
2. Internal diagnostic logs when called from other paths

**Affected files:**
- `java/validator.py` — lines 236 and 238

---

### Problem 4 — `permanent_skip` entries from already-fixed bugs

**Current state of `logs/failed_files.json`:**

| File | Phase | Reason/Stack | Bug fixed by |
|---------|------|-------------|------------------|
| `BalanceServiceImplTest.java` | `initial_coverage_fix` | `"actual and formal argument lists differ in length"` | Fix **A** (CONSTRUCTOR CALL with types) |
| `MerchantCategoryCodesServiceImplTest.java` | `initial_coverage_fix` | `"INTEGRITY ERROR: O arquivo se chama..."` | Fix **B** (expected_class in repair loop) |
| `TransactionServiceImpl.java` | `solid-dip` | `compile_failed` | Investigation needed (not a test file) |

**Root cause:** `_AUTO_EXPIRE_STACK_PATTERNS` in `refactor.py:508` only contains `"com.example"`. The `reset()` method checks only the `stack_trace` field. Entries without `stack_trace` (like `MerchantCategoryCodesServiceImplTest`) never expire.

**Gaps:**
1. Pattern for constructor mismatch missing (`"actual and formal argument lists differ in length"`)
2. Pattern for Portuguese integrity error missing (`"O arquivo se chama"`)
3. `reset()` checks only `stack_trace`, not `reason`

**Affected files:**
- `java/refactor.py` — `_AUTO_EXPIRE_STACK_PATTERNS` (~line 508) and `reset()` method in `FailedFilesTracker` (~line 600)

---

## File Map

| File | Change |
|---------|---------|
| `soul.md` | Translate PT → EN (Task 2) |
| `java/refactor.py` | 4 changes: `_JDK_IMPORT_MAP` + Timestamp preventive rule + `_categorize_build_error` handler + `_AUTO_EXPIRE_STACK_PATTERNS` + `reset()` |
| `java/validator.py` | 2 Portuguese messages → English (Task 3) |

---

## Task 1: Fixes for `java.sql.Timestamp` (Problem 1)

**Files:**
- Modify: `java/refactor.py:52-78` (`_JDK_IMPORT_MAP`)
- Modify: `java/refactor.py:1490-1500` (BigDecimal block in `active_rules` section)
- Modify: `java/refactor.py:140-240` (`_categorize_build_error`)

### Fix 1a — Add `Timestamp` to `_JDK_IMPORT_MAP`

- [ ] **Step 1: Locate the `_JDK_IMPORT_MAP` block**

Open `java/refactor.py` and locate the dict starting at ~line 52:
```python
_JDK_IMPORT_MAP: dict[str, str] = {
    "BigDecimal":    "import java.math.BigDecimal;",
    ...
}
```

- [ ] **Step 2: Add `Timestamp` entry**

Insert immediately after the `"Period"` entry:
```python
    "Timestamp":     "import java.sql.Timestamp;",
    "Date":          "import java.util.Date;",
```
**Reason:** `_auto_inject_missing_imports` consults this map. Without the entry, tests with `Timestamp` are missing the import and generation fails even before the wrong format manifests.

- [ ] **Step 3: Verify no unit tests are broken by this addition**

Run (with venv activated, Java 22):
```bash
cd /home/emerson/Área\ de\ trabalho/ai-refactor-agent && python -m pytest tests/ -q -k "import" 2>&1 | tail -20
```
Expected: zero failures related to the import map.

---

### Fix 1b — Preventive rule in `active_rules`

- [ ] **Step 4: Locate the BigDecimal rule block in `active_rules`**

In `java/refactor.py`, locate the block starting with (~ line 1491):
```python
        # C: preventive rule — when the production class declares BigDecimal fields
        if re.search(r'\bBigDecimal\b', original):
            active_rules += (
                "\n\n### BIGDECIMAL CONSTRUCTION (MANDATORY — VIOLATION CAUSES COMPILE FAILURE)\n"
                ...
            )
```

- [ ] **Step 5: Add `java.sql.Timestamp` rule block IMMEDIATELY AFTER the BigDecimal block**

```python
        # F (Timestamp): preventive rule — when the class uses java.sql.Timestamp
        # Timestamp.valueOf() requires format "yyyy-mm-dd hh:mm:ss" (space, not ISO T).
        if re.search(r'\bjava\.sql\.Timestamp\b', original) or \
           (re.search(r'\bTimestamp\b', original) and 'import java.sql.Timestamp' in original):
            active_rules += (
                "\n\n### JAVA SQL TIMESTAMP CONSTRUCTION (MANDATORY — VIOLATION CAUSES RUNTIME FAILURE)\n"
                "This class uses java.sql.Timestamp. For ALL test values involving Timestamp:\n"
                "  CORRECT: Timestamp.valueOf(\"2023-01-15 10:00:00\")  ← space between date and time\n"
                "  WRONG:   Timestamp.valueOf(\"2023-01-15T10:00:00\")  ← T is ISO format, NOT SQL format\n"
                "  WRONG:   new Timestamp(longValue)  ← use valueOf() with string for readability\n"
                "The format MUST be exactly: \"yyyy-mm-dd hh:mm:ss\" or \"yyyy-mm-dd hh:mm:ss.nnnnnnnnn\"\n"
                "NEVER use ISO-8601 format (with 'T') — it throws IllegalArgumentException at runtime.\n"
                "ALWAYS add: import java.sql.Timestamp;\n"
            )
```

- [ ] **Step 6: Verify detection works for `TransactionDocument.java`**

Quick manual test in Python REPL:
```python
import re
original = open("repos/card-transaction-authorizer/src/main/java/com/caju/transactionauthorizer/document/TransactionDocument.java").read()
print(bool(re.search(r'\bjava\.sql\.Timestamp\b', original)))
# Expected: False  (the import is java.sql.Timestamp but without the package in the body)
print('import java.sql.Timestamp' in original)
# Expected: True
print(bool(re.search(r'\bTimestamp\b', original)))
# Expected: True
```
Expected result: the condition `re.search(r'\bTimestamp\b', original) and 'import java.sql.Timestamp' in original` is `True` → rule injected.

---

### Fix 1c — Handler in `_categorize_build_error`

- [ ] **Step 7: Locate the start of `_categorize_build_error`**

In `java/refactor.py`, function `_categorize_build_error` (~line 140). Locate the first `if` block:
```python
    # Record constructor error (detect BEFORE cannot find symbol)
    if "constructor" in out and "in record" in out ...
```

- [ ] **Step 8: Insert `IllegalArgumentException` + Timestamp handler BEFORE the first `if` block**

The handler must be the FIRST checked since `IllegalArgumentException` can co-occur with other strings:
```python
    # F: IllegalArgumentException with Timestamp format message
    if "illegalargument" in out and "timestamp format" in out:
        return (
            "TIMESTAMP FORMAT ERROR: java.sql.Timestamp.valueOf() received an invalid format string.\n"
            "The format MUST be exactly: \"yyyy-mm-dd hh:mm:ss\" (space between date and time, NOT 'T').\n\n"
            "FIND in your @BeforeEach or test body every occurrence of:\n"
            "  Timestamp.valueOf(\"...T...\")   ← WRONG — 'T' is ISO-8601, not SQL format\n"
            "REPLACE with:\n"
            "  Timestamp.valueOf(\"2023-01-15 10:00:00\")   ← CORRECT — space, not T\n\n"
            "ONE CHANGE ONLY — do NOT modify any other code. Do NOT change assertions, imports, or class structure.\n"
        )
```

- [ ] **Step 9: Verify the handler is positioned BEFORE the `if "constructor" in out...` block**

Read the first 10 lines of the function after insertion to confirm the order.

- [ ] **Step 10: Commit**

```bash
cd /home/emerson/Área\ de\ trabalho/ai-refactor-agent
git add java/refactor.py
git commit -m "fix: F — java.sql.Timestamp import, preventive rule, and repair handler

_JDK_IMPORT_MAP: add Timestamp → import java.sql.Timestamp
active_rules: inject JAVA SQL TIMESTAMP CONSTRUCTION rule when class imports Timestamp
_categorize_build_error: add handler for IllegalArgument + Timestamp format error

Resolves: TransactionDocumentTest.setUp:29 » IllegalArgument Timestamp format

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Translate `soul.md` to English (Problem 2)

**Files:**
- Modify: `soul.md` (project root)

**Context:** `soul.md` is loaded once in `ai/prompt.py:23` as `_SOUL` and injected at the start of ALL prompts (refactoring and test generation). Any LLM receiving a prompt from the pipeline reads the soul first. Having the soul in Portuguese while everything else is in English creates language ambiguity for the model.

**Critical rule:** Do NOT add ` ```java ` blocks to soul.md — it would break the `test_no_java_example_block_in_prompt` test. Keep only prose text.

- [ ] **Step 1: Translate `soul.md` to English keeping 100% of the content**

Replace the `soul.md` file with the version below (same sections, same rules, same tone, in English):

```markdown
# SOUL — Java Refactoring Agent Identity

You are a senior Java engineer with 15 years of experience in high-availability critical systems.
Your specialty is surgical refactoring: improving code without ever altering its external behavior.

---

## Who you are

You are methodical, conservative, and precise.
You never invent, never assume, never guess.
You read code as a contract — each method is a promise to its caller.

You were trained on the principles of:
- Robert C. Martin (Clean Code, SOLID)
- Martin Fowler (Refactoring)
- Joshua Bloch (Effective Java)

---

## What you NEVER do

1. **Never change the package name.** The package is tied to the physical path of the file in the Maven project. Changing the package breaks the build for the entire project.

2. **Never invent imports.** If a symbol does not exist in the original code, do not add it unless you are absolutely certain the dependency exists on the classpath.

3. **Never remove business logic.** You may reorganize, rename, extract — but never delete functional behavior.

4. **Never change public signatures without necessity.** Renaming or altering the parameters of a public method breaks all callers.

5. **Never add annotations that did not exist.** `@Version`, `@Transactional`, `@Cacheable` have runtime behavioral implications.

6. **Never convert an interface to a class or vice versa.** These are immutable architectural contracts in this context.

---

## How you decide what to change

Before changing anything, you ask yourself:
- Does this change make the code more readable WITHOUT altering behavior?
- Can this change break something in another file that depends on this one?
- Is the file already good enough for this rule? If so, return it EXACTLY as received.

If the file already satisfies the rule for this phase, return the code **identical to the original**.
This is not a failure — it is the correct diagnosis of already well-written code.

---

## Code style you produce

- Methods with ≤ 30 lines
- Maximum 3 levels of nesting
- Prefer early return over deep else
- Names that need no comments
- No `System.out.println` — only SLF4J
- No silenced exceptions with empty catch

---

## Mandatory response format

You respond ALWAYS with the complete Java file inside a single code block delimited by triple-backtick java.
Never explain what changed. Never add comments outside the code.
Never truncate the file with "// rest of code..." or similar.
The file you return replaces the original file — it must be 100% complete and compilable.
```

- [ ] **Step 2: Verify no java block in new soul.md**

```bash
grep -c '```java' /home/emerson/Área\ de\ trabalho/ai-refactor-agent/soul.md
```
Expected: `0`

- [ ] **Step 3: Verify soul is still loaded correctly**

```bash
cd /home/emerson/Área\ de\ trabalho/ai-refactor-agent
python -c "
from ai.prompt import _SOUL
assert len(_SOUL) > 100, 'soul is empty'
assert 'never invent' in _SOUL.lower() or 'Never invent' in _SOUL, 'content missing'
assert 'Você' not in _SOUL, 'Portuguese still present'
print('OK:', len(_SOUL), 'chars, language: EN')
"
```
Expected: `OK: NNN chars, language: EN`

- [ ] **Step 4: Run prompt-related tests**

```bash
cd /home/emerson/Área\ de\ trabalho/ai-refactor-agent
python -m pytest tests/ -q -k "prompt or soul" 2>&1 | tail -20
```
Expected: all passing, especially `test_no_java_example_block_in_prompt`.

- [ ] **Step 5: Commit**

```bash
git add soul.md
git commit -m "fix: G — translate soul.md from Portuguese to English

Unifies prompt language: all LLM instructions now consistently in English.
Content unchanged — identical behavioral rules, same structure, EN wording.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Translate Portuguese messages in `validator.py` (Problem 3)

**Files:**
- Modify: `java/validator.py:236` and `java/validator.py:238`

- [ ] **Step 1: Locate and replace the two messages in `validate_class_name_matches_file`**

File: `java/validator.py`

**Line 236** — replace:
```python
        return False, f"O arquivo se chama '{file_name}.java' mas você gerou a classe '{found_name}'."
```
With:
```python
        return False, f"File is named '{file_name}.java' but generated class is '{found_name}'."
```

**Line 238** — replace:
```python
    return False, f"Não foi encontrada a classe '{file_name}' no código gerado."
```
With:
```python
    return False, f"Class '{file_name}' not found in the generated code."
```

- [ ] **Step 2: Verify new messages follow the pattern of other validator messages**

Confirm that `check_syntax` still uses English messages (`"Syntax error:"`, `"Parse failed:"`).

- [ ] **Step 3: Run validator tests**

```bash
cd /home/emerson/Área\ de\ trabalho/ai-refactor-agent
python -m pytest tests/ -q -k "validator or class_name or package" 2>&1 | tail -20
```
Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add java/validator.py
git commit -m "fix: H — translate Portuguese error messages in validator.py to English

Lines 236 and 238 of validate_class_name_matches_file() now return English.
These messages appear in failed_files.json; translating maintains log consistency.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Expire `permanent_skip` entries from already-fixed bugs (Problem 4)

**Files:**
- Modify: `java/refactor.py:508-510` (`_AUTO_EXPIRE_STACK_PATTERNS`)
- Modify: `java/refactor.py` — `reset()` method in `FailedFilesTracker` (~line 600)

**Context of blocked files:**

| File | Field with detectable pattern | Fixed by |
|---------|-----------------------------|-------------------|
| `BalanceServiceImplTest.java` | `stack_trace`: `"actual and formal argument lists differ in length"` | Fix A (CONSTRUCTOR CALL with types) |
| `MerchantCategoryCodesServiceImplTest.java` | `reason`: `"O arquivo se chama"` (Portuguese message — impossible after fix B) | Fix B (expected_class in repair loop) |

**Note on `TransactionServiceImpl.java`:** It is in `solid-dip`, not in test generation. It is a complex production file. **Do not add** auto-expire for generic `compile_failed` — that would be dangerous. This file deserves a separate manual investigation.

### Fix 4a — Expand `_AUTO_EXPIRE_STACK_PATTERNS` and cover `reason` field

- [ ] **Step 1: Locate `_AUTO_EXPIRE_STACK_PATTERNS`**

In `java/refactor.py`, locate (~line 508):
```python
_AUTO_EXPIRE_STACK_PATTERNS = [
    "com.example",  # F2 Package Guard: LLM wrote wrong package; fixed deterministically
]
```

- [ ] **Step 2: Add new patterns**

Replace with:
```python
_AUTO_EXPIRE_STACK_PATTERNS = [
    "com.example",              # F2 Package Guard: package hallucination no longer possible
    "actual and formal argument lists differ in length",  # Fix A: CONSTRUCTOR CALL hint now includes types
    "O arquivo se chama",       # Fix B/H: old Portuguese integrity error — impossible after fix B
]
```

- [ ] **Step 3: Locate the `reset()` method in `FailedFilesTracker`**

Locate the block that checks `permanent_skip` (~ line 600):
```python
for entry in ...:
    if entry.get("permanent_skip"):
        st = entry.get("stack_trace", "")
        if next((p for p in _AUTO_EXPIRE_STACK_PATTERNS if p in st), None):
            ...
```

- [ ] **Step 4: Extend the check to include the `reason` field**

The `MerchantCategoryCodesServiceImplTest` file has the pattern in `reason`, not in `stack_trace`. Replace the line:
```python
        st = entry.get("stack_trace", "")
```
With:
```python
        st = (entry.get("stack_trace") or "") + " " + (entry.get("reason") or "")
```
This one-line change ensures patterns are checked in both fields, without changing any other logic.

- [ ] **Step 5: Verify behavior with a manual test**

```python
# Simulate in Python REPL
import json, sys
sys.path.insert(0, '/home/emerson/Área de trabalho/ai-refactor-agent')
from java.refactor import _AUTO_EXPIRE_STACK_PATTERNS

entries = json.load(open('logs/failed_files.json'))
for e in entries:
    if e.get('permanent_skip'):
        st = (e.get('stack_trace') or '') + ' ' + (e.get('reason') or '')
        match = next((p for p in _AUTO_EXPIRE_STACK_PATTERNS if p in st), None)
        print(f"{e['file'].split('/')[-1]}: {'EXPIRES' if match else 'REMAINS'} ({match or 'no pattern'})")
```

Expected result:
```
TransactionServiceImpl.java: REMAINS (no pattern)
MerchantCategoryCodesServiceImplTest.java: EXPIRES (O arquivo se chama)
BalanceServiceImplTest.java: EXPIRES (actual and formal argument lists differ in length)
BalanceDocumentTest.java: REMAINS (no pattern)   # prev_run=True, not permanent_skip=True
```

- [ ] **Step 6: Run FailedFilesTracker-related tests**

```bash
cd /home/emerson/Área\ de\ trabalho/ai-refactor-agent
python -m pytest tests/ -q -k "failed_files or tracker or expire or skip" 2>&1 | tail -20
```
Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add java/refactor.py
git commit -m "fix: I — expand permanent_skip auto-expire to cover constructor mismatch and old PT integrity errors

_AUTO_EXPIRE_STACK_PATTERNS: add constructor mismatch pattern (fixed by A)
  and old Portuguese integrity error pattern (impossible after fix B/H).
reset(): check both stack_trace and reason fields — MerchantCategoryCodesServiceImplTest
  stores the expired pattern in reason, not in stack_trace.

BalanceServiceImplTest and MerchantCategoryCodesServiceImplTest will be retried
on the next run with fixes A and B active.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5 (Investigation): `TransactionServiceImpl.java` — solid-dip blocked

**Files:**
- Read: `repos/card-transaction-authorizer/src/main/java/.../TransactionServiceImpl.java`

This file is in `permanent_skip` with `solid-dip compile_failed`. It is not test generation — it is production refactoring. **Do not add auto-expire** without understanding the error.

- [ ] **Step 1: Read the current production file**

```bash
cat "repos/card-transaction-authorizer/src/main/java/com/caju/transactionauthorizer/service/impl/TransactionServiceImpl.java"
```

- [ ] **Step 2: Understand why solid-dip failed**

The `stack_trace` in `failed_files.json` only says `compile_failed`. To know the actual error, check `execution.log` from previous runs or run the solid-dip manually on this file in isolation.

- [ ] **Step 3: Decide the action**

Options:
- **A) Add to permanent blocklist** (`_BOOTSTRAP_RE` or `_SKIP_PATTERNS`) if the file has a structure that solid-dip cannot process (e.g. complex generics, multiple interfaces).
- **B) Fix the solid-dip bug** for this specific pattern.
- **C) Leave in `permanent_skip`** if the file is already well-structured and DIP is not needed.

This task does not generate its own commit — the result feeds the decision for an additional fix if necessary.

---

## Self-Review

**Spec coverage:**
- ✅ Problem 1 (Timestamp) → Task 1 (3 fixes: import map, preventive rule, repair handler)
- ✅ Problem 2 (soul Portuguese) → Task 2 (complete translation)
- ✅ Problem 3 (validator Portuguese) → Task 3 (2 messages)
- ✅ Problem 4 (permanent_skip) → Task 4 (patterns + reset() fix)
- ✅ TransactionServiceImpl → Task 5 (investigation)

**Placeholder scan:** no TODO/TBD present; all code blocks contain real code.

**Type consistency:** the `stack_trace` and `reason` fields in `failed_files.json` are strings; concatenation with `" "` is safe for the substring matching patterns used.

**Recommended execution order:** Task 1 → Task 2 → Task 3 → Task 4 → Task 5. Tasks 2 and 3 are independent and can be done in parallel. Task 4 depends on nothing (the patterns work regardless of the translation). Task 1 is the most urgent (active error now).
