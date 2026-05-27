# Design: Cache Layer + Prompt Decomposition (Option B)

**Date:** 2026-05-12  
**Status:** Approved  
**Objective:** Reduce 55–65% of the agent's token consumption without reducing refactoring quality  
**Scope:** Java projects of 50–200 files running via local Ollama

---

## Context

The current agent suffers from high token consumption for three main reasons:

1. `_polish_result()` in `model.py` doubles consumption on most successful calls (every non-ultimate call fires a second call to the 14B model)
2. `get_dependency_context()` in `java/context.py` runs a complete `os.walk()` of the project per file per phase, with no caching (1200 walks for 100 files × 12 phases)
3. Prompts contain ~400 tokens of identical constants repeated on every call, and phase `.md` files repeat rules already present in the base template

There is no change detection between phases: unmodified files are reprocessed by all subsequent phases.

---

## Target Architecture

```
ai-refactor-agent/
├── memory/                         ← NEW module
│   ├── __init__.py
│   ├── cache.py                    # Cache engine: hash → JSON on disk
│   ├── summaries.py                # Reads/writes class summaries
│   └── project_dict.py             # Project dictionary singleton
│
├── ai/
│   ├── prompt.py                   # MODIFIED: BASE_CONSTRAINTS + build_prompt()
│   └── model.py                    # MODIFIED: _polish_result() conditional
│
├── java/
│   ├── context.py                  # MODIFIED: cache-first, fallback to generation
│   └── refactor.py                 # MODIFIED: skip by hash, injects cache
│
├── phases/
│   ├── _base_rules.md              ← NEW: global rules (read once per run)
│   └── {category}/*.md             # Phase delta only (shorter files)
│
└── .refactor_cache/                ← GENERATED at runtime (in .gitignore)
    └── {repo_hash}/
        ├── dict.json               # Persisted project dictionary
        └── classes/
            └── {file_hash}.json    # Summary + compact dep_context per file
```

### Unchanged components

`scope_reducer.py`, `validator.py`, `compiler.py`, `flow.py`, `impact.py`, `agent_router.py`, `sanitizer.py` (java/), all rollback/revert logic, `call_ai_with_correction()`, main structure of `main.py`.

---

## Component 1: `memory/cache.py`

**Responsibility:** Persist and retrieve cache entries indexed by file content hash.

**Cache key:** `sha256(file_content.encode()).hexdigest()[:12]` — deterministic, no path or timestamp dependency.

**`repo_hash`** (root directory name of the cache): `sha256(os.path.abspath(repo_path).encode()).hexdigest()[:8]`

**Shared helper function** (in `memory/cache.py`, imported where needed):
```python
import hashlib

def _sha(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:12]
```

**Entry schema on disk** (`.refactor_cache/{repo_hash}/classes/{file_hash}.json`):

```json
{
  "file_path": "src/main/java/com/ex/CustomerService.java",
  "file_hash": "a3f9c12b4e8d",
  "class_name": "CustomerService",
  "dep_context": "// SUGGESTED IMPORT: ...\n// Class: ...",
  "processed_phases": ["01_javadoc", "04_nomenclature"],
  "last_output_hash": "b7e2a09f",
  "generated_at": "2026-05-12T14:30:00"
}
```

**Public API:**

```python
class Cache:
    def __init__(self, repo_path: str): ...

    # Per-file entries (summary + phases)
    def get(self, file_path: str) -> dict | None: ...
    def set(self, file_path: str, data: dict) -> None: ...

    # Dep context indexed by file_hash
    def get_dep_context(self, file_hash: str) -> str | None: ...
    def set_dep_context(self, file_hash: str, context: str) -> None: ...

    # Phase control per file
    def mark_phase_done(self, file_path: str, phase_name: str,
                        output_hash: str) -> None: ...
    def is_phase_done(self, file_path: str, phase_name: str,
                      current_hash: str) -> bool: ...

    # Persisted project dictionary
    def load_dict(self) -> str | None: ...
    def save_dict(self, content: str) -> None: ...
```

**`is_phase_done` logic:** Returns `True` only if `phase_name` is in `processed_phases` AND the hash of the current file content matches the `last_output_hash` stored. This ensures that reverted files (rollback) are not considered processed.

---

## Component 2: `memory/project_dict.py`

**Responsibility:** Project dictionary singleton — built once per run, persisted to disk between runs of the same repo.

```python
_DICT_CACHE: str | None = None

def get_project_dictionary(repo_path: str, cache: Cache) -> str:
    global _DICT_CACHE
    if _DICT_CACHE is not None:
        return _DICT_CACHE
    # Try to read from disk
    persisted = cache.load_dict()
    if persisted:
        _DICT_CACHE = persisted
        return _DICT_CACHE
    # Generate and persist
    _DICT_CACHE = _build_dict(repo_path)
    cache.save_dict(_DICT_CACHE)
    return _DICT_CACHE

def reset():
    global _DICT_CACHE
    _DICT_CACHE = None
```

`reset()` is called in `main.py` when starting a new run (new repo or new execution).

---

## Component 3: `ai/prompt.py` — BASE + PHASE_DELTA

**Problem:** ~400 tokens of constants (constraints, output format, example) repeated on every call.

**Solution:** Separate into global constant + composition function.

```python
BASE_CONSTRAINTS = """\
You are a senior Java engineer.

### TECHNICAL CONSTRAINTS (MANDATORY)
PRESERVE the package declaration exactly as-is.
PRESERVE all existing import statements.
ADD import statements for any NEW type you introduce in the code.
  Check [DEPENDENCY CONTEXT] for '// SUGGESTED IMPORT' hints.
PRESERVE method signatures (name, parameters, return type).
PRESERVE class-level annotations.
DO NOT introduce external dependencies not already in the project.
DO NOT modify Spring Boot main class structure.

### OUTPUT FORMAT (MANDATORY)
Return ONLY the complete Java source file.
Return exactly ONE code block in ```java format.
NO explanations, NO markdown outside the code block.
NO ANSI or invisible characters.\
"""

def build_prompt(code: str, phase_delta: str, mode: str,
                 file_name: str, dep_context: str = "") -> str:
    task = _build_task(mode, file_name)
    parts = [
        BASE_CONSTRAINTS,
        f"\n### PHASE RULES\n{phase_delta.strip()}",
        f"\n### TASK\n{task}",
    ]
    if dep_context:
        parts.append(f"\n### DEPENDENCY CONTEXT\n{dep_context}")
    parts.append(f"\n### SOURCE FILE TO PROCESS\n```java\n{code}\n```")
    return "\n".join(parts)
```

The Java output example is **removed** — 7B/14B models trained on Java already know the ```` ```java ``` ```` format. The example added ~80 tokens with no measurable gain.

### Phase files: BASE_RULES + DELTA

New file: `phases/_base_rules.md` — contains rules that repeat across all phases (do not create new classes, preserve public signatures, do not modify tests, etc.). Loaded once per run in `main.py`.

Each existing phase `.md` is reduced to contain only:
- Specific objective of the phase
- Exclusive rules
- BEFORE/AFTER examples only if strictly necessary for the phase

Target: each phase reduced from 200–300 tokens to 80–150 tokens.

---

## Component 4: `java/context.py` — Cache-First

**Problem:** `get_dependency_context()` does a full project walk per file per phase.

**Solution:** Cache-first with fallback to generation.

```python
def get_dependency_context(file_code: str, repo_path: str,
                           cache: Cache) -> str:
    file_hash = _sha(file_code)
    cached = cache.get_dep_context(file_hash)
    if cached is not None:
        return cached
    context = _build_dep_context(file_code, repo_path)
    cache.set_dep_context(file_hash, context)
    return context
```

Additionally, `_extract_simplified_header()` is optimized: removes private fields, internal comments, retains only public/protected method signatures. Reduces dep_context from ~400 tokens per dependency to ~80–120 tokens.

---

## Component 5: `model.py` — Conditional `_polish_result()`

**Problem:** Every non-ultimate call fires a second call to the 14B model.

**Solution:** Polishing only on structurally critical phases.

```python
PHASES_REQUIRING_POLISH = {"07_solid", "08_architecture", "09_patterns"}

# In _run_pipeline():
phase_name = phase.split("/")[-1].replace(".md", "")
needs_polish = agent != "ultimate" and phase_name in PHASES_REQUIRING_POLISH
if needs_polish and MODEL_SOLID not in _OOM_MODELS:
    result = _polish_result(result, prompt, MODEL_SOLID)
```

Documentation phases (01–03), nomenclature (04–06), clean code (10), and tests (11–12) are deterministic — they do not require review from the heavy model.

---

## Component 6: `java/refactor.py` — Phase Skip

**Problem:** Subsequent phases reprocess files that were not modified.

**Solution:** Check cache before each processing.

```python
def refactor_file(file: str, rules: str, repo_path: str, phase: str,
                  reporter: PhaseReporter,
                  exec_logger: ExecutionLogger | None = None,
                  cache: Cache | None = None) -> bool:
    file_name = os.path.basename(file)
    original = read_file(file)

    if cache:
        phase_name = phase.split("/")[-1].replace(".md", "")
        current_hash = _sha(original)
        if cache.is_phase_done(file, phase_name, current_hash):
            log(f"  {file_name}: cache hit — phase {phase_name} already applied", "OK")
            reporter.record_skipped(phase, file_name, "cache hit")
            return False  # no change needed

    # ... rest of the flow unchanged
```

After acceptance (build ok), `cache.mark_phase_done(file, phase_name, sha(new_code))` is called.

---

## Integration in `main.py`

Only 4 new lines at initialization:

```python
from memory.cache import Cache
from memory.project_dict import reset as reset_dict

# Right after defining repo_path:
cache = Cache(repo_path)
reset_dict()
```

The `cache` object is passed to `refactor_file()` and `get_dependency_context()`.

---

## `.gitignore`

Add:
```
.refactor_cache/
```

---

## Token Reduction Estimate

| Optimization | Estimated reduction |
|---|---|
| Conditional `_polish_result()` | ~35–40% |
| Dep context cache + compact format | ~15–20% |
| Phase skip per file | ~10–15% |
| Phase delta (shorter phases) | ~8–12% |
| Project dictionary singleton | ~3–5% |
| **Combined total** | **~55–65%** |

---

## Success Criteria

- Target Java project build continues passing after refactoring
- No new broken dependency files
- Logs show "cache hit" on subsequent phases for unmodified files
- Measurable reduction in model calls (countable via logs)
- `_polish_result()` called only on phases 07, 08, 09

---

## Out of Scope

- Embeddings / vector search
- SQLite or database
- Rewriting the main pipeline (SCAN → REDUCE → SUMMARIZE → PLAN → REFACTOR → VALIDATE)
- Changing `scope_reducer.py`, `validator.py`, `compiler.py`
- New interface or new CLI
