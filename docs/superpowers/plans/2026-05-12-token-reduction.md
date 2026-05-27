# Token Reduction — Cache Layer + Prompt Decomposition

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce 55–65% of token consumption by adding a dep-context cache keyed by file hash, per-run phase skip, prompt decomposition (BASE_CONSTRAINTS + phase delta), and conditional polish per phase.

**Architecture:** New module `memory/cache.py` with `Cache` class (dep context on disk by hash, phase tracking in memory per run, project dict in memory + disk). `ai/prompt.py` refactored with `BASE_CONSTRAINTS` as a constant + `build_prompt()` receiving `dep_context` separately. `_polish_result()` in `model.py` conditioned to the set `{07_solid, 08_architecture, 09_patterns}`. `java/context.py` and `java/refactor.py` injected with the `Cache` object. `main.py` fixed (recursive phase loading bug + argument order bug) and integrated with `Cache`.

**Tech Stack:** Python 3.12, hashlib (stdlib), json (stdlib), os (stdlib), pytest (dev)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `memory/__init__.py` | Create | Makes `memory` a package |
| `memory/cache.py` | Create | Central cache engine (disk + memory) |
| `tests/__init__.py` | Create | Makes `tests` a package |
| `tests/memory/__init__.py` | Create | Test sub-package |
| `tests/memory/test_cache.py` | Create | Cache tests |
| `tests/ai/__init__.py` | Create | Test sub-package |
| `tests/ai/test_prompt.py` | Create | prompt.py tests |
| `tests/java/__init__.py` | Create | Test sub-package |
| `tests/java/test_context.py` | Create | context.py tests |
| `ai/prompt.py` | Modify | BASE_CONSTRAINTS + dep_context param |
| `ai/model.py` | Modify | _polish_result() conditional + dep_context param |
| `java/context.py` | Modify | Cache-first + compact header |
| `java/refactor.py` | Modify | Phase skip + cache propagation |
| `phases/solid/07_solid.md` | Modify | Remove duplicate rules |
| `phases/solid/08_architecture.md` | Modify | Remove duplicate rules |
| `phases/solid/09_patterns.md` | Modify | Remove duplicate rules |
| `phases/clean/10_clean_code.md` | Modify | Remove duplicate rules |
| `phases/doc/01_javadoc.md` | Modify | Remove duplicate rules |
| `phases/struct/04_nomenclature.md` | Modify | Remove duplicate rules |
| `main.py` | Modify | Fix 2 bugs + integrate Cache |
| `.gitignore` | Modify | Add `.refactor_cache/` |

---

## Task 1: `memory/cache.py` — Central Cache Engine

**Files:**
- Create: `memory/__init__.py`
- Create: `memory/cache.py`
- Create: `tests/__init__.py`
- Create: `tests/memory/__init__.py`
- Create: `tests/memory/test_cache.py`

- [ ] **Step 1.1: Install pytest**

```bash
pip install pytest
```

Expected: `Successfully installed pytest-X.X.X`

- [ ] **Step 1.2: Create directory structure**

```bash
mkdir -p memory tests/memory tests/ai tests/java
touch memory/__init__.py tests/__init__.py tests/memory/__init__.py tests/ai/__init__.py tests/java/__init__.py
```

- [ ] **Step 1.3: Write `Cache` tests (TDD — should FAIL now)**

Create `tests/memory/test_cache.py`:

```python
import os
import pytest
from memory.cache import Cache, sha12


# --- sha12 ---

def test_sha12_returns_12_char_hex():
    result = sha12("some content")
    assert len(result) == 12
    assert all(c in "0123456789abcdef" for c in result)

def test_sha12_deterministic():
    assert sha12("abc") == sha12("abc")

def test_sha12_different_inputs_differ():
    assert sha12("abc") != sha12("xyz")


# --- dep_context ---

def test_dep_context_miss_returns_none(tmp_path):
    c = Cache(str(tmp_path))
    assert c.get_dep_context("nonexistent") is None

def test_dep_context_round_trip(tmp_path):
    c = Cache(str(tmp_path))
    c.set_dep_context("abc123", "// some context")
    assert c.get_dep_context("abc123") == "// some context"

def test_dep_context_persists_across_instances(tmp_path):
    Cache(str(tmp_path)).set_dep_context("abc123", "// persisted")
    assert Cache(str(tmp_path)).get_dep_context("abc123") == "// persisted"

def test_dep_context_empty_string_round_trip(tmp_path):
    c = Cache(str(tmp_path))
    c.set_dep_context("empty", "")
    assert c.get_dep_context("empty") == ""


# --- phase tracking ---

def test_phase_done_false_initially(tmp_path):
    c = Cache(str(tmp_path))
    assert c.is_phase_done("/some/File.java", "01_javadoc") is False

def test_phase_done_after_mark(tmp_path):
    c = Cache(str(tmp_path))
    c.mark_phase_done("/some/File.java", "01_javadoc")
    assert c.is_phase_done("/some/File.java", "01_javadoc") is True

def test_phase_done_other_phase_still_false(tmp_path):
    c = Cache(str(tmp_path))
    c.mark_phase_done("/some/File.java", "01_javadoc")
    assert c.is_phase_done("/some/File.java", "04_nomenclature") is False

def test_phase_done_other_file_still_false(tmp_path):
    c = Cache(str(tmp_path))
    c.mark_phase_done("/some/FileA.java", "01_javadoc")
    assert c.is_phase_done("/some/FileB.java", "01_javadoc") is False

def test_phase_tracking_is_per_run(tmp_path):
    # New instance = zeroed memory
    Cache(str(tmp_path)).mark_phase_done("/some/File.java", "01_javadoc")
    assert Cache(str(tmp_path)).is_phase_done("/some/File.java", "01_javadoc") is False


# --- project dict ---

def test_project_dict_miss_returns_none(tmp_path):
    assert Cache(str(tmp_path)).get_project_dict() is None

def test_project_dict_round_trip(tmp_path):
    c = Cache(str(tmp_path))
    c.set_project_dict("- CustomerService (com.ex.CustomerService)")
    assert c.get_project_dict() == "- CustomerService (com.ex.CustomerService)"

def test_project_dict_in_memory_after_set(tmp_path):
    c = Cache(str(tmp_path))
    c.set_project_dict("- MyClass")
    # Second call on same instance uses in-memory (no disk hit)
    assert c.get_project_dict() == "- MyClass"

def test_project_dict_persists_across_instances(tmp_path):
    Cache(str(tmp_path)).set_project_dict("- MyClass (com.ex.MyClass)")
    assert Cache(str(tmp_path)).get_project_dict() == "- MyClass (com.ex.MyClass)"
```

- [ ] **Step 1.4: Run tests to confirm FAIL**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent"
python -m pytest tests/memory/test_cache.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'memory.cache'`

- [ ] **Step 1.5: Implement `memory/cache.py`**

```python
"""
memory/cache.py — Cache engine for token reduction.

Dep context: persists to disk by file content hash.
Phase tracking: in memory per run (zeroed on each new instance).
Project dict: in memory + disk for reuse between runs.
"""

import hashlib
import os
from typing import Optional


def sha12(content: str) -> str:
    """SHA-256 hash truncated to 12 chars — used as cache key."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


class Cache:
    def __init__(self, repo_path: str):
        repo_abs = os.path.abspath(repo_path)
        repo_key = hashlib.sha256(repo_abs.encode()).hexdigest()[:8]
        self._base = os.path.join(repo_abs, ".refactor_cache", repo_key)
        self._dep_dir = os.path.join(self._base, "dep_ctx")
        os.makedirs(self._dep_dir, exist_ok=True)

        # In-memory: zeroed on each run (new instance)
        self._phase_done: dict[str, set[str]] = {}
        self._project_dict: Optional[str] = None

    # --- Dep context (disk, keyed by file content hash) ---

    def get_dep_context(self, file_hash: str) -> Optional[str]:
        path = os.path.join(self._dep_dir, f"{file_hash}.txt")
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return f.read()
            except OSError:
                return None
        return None

    def set_dep_context(self, file_hash: str, context: str) -> None:
        path = os.path.join(self._dep_dir, f"{file_hash}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(context)

    # --- Phase tracking (in-memory per run) ---

    def is_phase_done(self, file_path: str, phase_name: str) -> bool:
        return phase_name in self._phase_done.get(file_path, set())

    def mark_phase_done(self, file_path: str, phase_name: str) -> None:
        self._phase_done.setdefault(file_path, set()).add(phase_name)

    # --- Project dictionary (in-memory + disk) ---

    def get_project_dict(self) -> Optional[str]:
        if self._project_dict is not None:
            return self._project_dict
        path = os.path.join(self._base, "dict.txt")
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self._project_dict = f.read()
            except OSError:
                pass
        return self._project_dict

    def set_project_dict(self, content: str) -> None:
        self._project_dict = content
        path = os.path.join(self._base, "dict.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError:
            pass
```

- [ ] **Step 1.6: Run tests to confirm PASS**

```bash
python -m pytest tests/memory/test_cache.py -v
```

Expected: `17 passed`

- [ ] **Step 1.7: Commit**

```bash
git add memory/__init__.py memory/cache.py tests/__init__.py tests/memory/__init__.py tests/memory/test_cache.py tests/ai/__init__.py tests/java/__init__.py
git commit -m "feat: add memory/cache.py — dep context + phase tracking + project dict"
```

---

## Task 2: `ai/prompt.py` — BASE_CONSTRAINTS + separate dep_context

**Files:**
- Modify: `ai/prompt.py`
- Create: `tests/ai/test_prompt.py`

- [ ] **Step 2.1: Write tests (TDD — should FAIL before the change)**

Create `tests/ai/test_prompt.py`:

```python
from ai.prompt import build_prompt, BASE_CONSTRAINTS


def test_base_constraints_is_string():
    assert isinstance(BASE_CONSTRAINTS, str)
    assert len(BASE_CONSTRAINTS) > 0

def test_base_constraints_in_every_prompt():
    prompt = build_prompt("public class A {}", "# Rule\n- Do X", "refactor", "A.java")
    assert "PRESERVE the package declaration" in prompt
    assert "TECHNICAL CONSTRAINTS" in prompt

def test_no_java_example_block_in_prompt():
    prompt = build_prompt("public class A {}", "# Rule\n- Do X", "refactor", "A.java")
    # Java example was removed — only the SOURCE FILE to process should have ```java
    count = prompt.count("```java")
    assert count == 1, f"Expected 1 java block (source), but found {count}"

def test_phase_delta_appears_in_prompt():
    prompt = build_prompt("public class A {}", "# SOLID\n- Apply DIP", "refactor", "A.java")
    assert "Apply DIP" in prompt

def test_dep_context_included_when_provided():
    dep = "// SUGGESTED IMPORT: import com.ex.Service;\n// Class: com.ex.Service"
    prompt = build_prompt("public class A {}", "# Rule", "refactor", "A.java", dep_context=dep)
    assert "DEPENDENCY CONTEXT" in prompt
    assert "SUGGESTED IMPORT" in prompt

def test_dep_context_absent_when_empty():
    prompt = build_prompt("public class A {}", "# Rule", "refactor", "A.java", dep_context="")
    assert "DEPENDENCY CONTEXT" not in prompt

def test_test_mode_task_different_from_refactor():
    p_refactor = build_prompt("public class A {}", "# Rule", "refactor", "A.java")
    p_test = build_prompt("public class A {}", "# Rule", "test", "A.java")
    assert "testes unitários" in p_test or "JUnit" in p_test
    assert p_refactor != p_test

def test_source_file_appears_at_end():
    code = "public class MyClass { }"
    prompt = build_prompt(code, "# Rule", "refactor", "MyClass.java")
    assert prompt.endswith("```") or code in prompt
    assert prompt.index("SOURCE FILE") > prompt.index("PHASE RULES")
```

- [ ] **Step 2.2: Run tests to confirm FAIL**

```bash
python -m pytest tests/ai/test_prompt.py -v 2>&1 | head -30
```

Expected: several FAILED (BASE_CONSTRAINTS does not exist, dep_context does not exist)

- [ ] **Step 2.3: Replace entire `ai/prompt.py`**

```python
"""
prompt.py — ai/prompt.py

BASE_CONSTRAINTS: global constant with technical rules and output format.
  Sent on every call — do not modify to avoid breaking the output format.

build_prompt(): composes BASE_CONSTRAINTS + phase delta + dep_context separately.
  dep_context is placed in its own section for easy identification.
"""


BASE_CONSTRAINTS = """\
You are a senior Java engineer.

### TECHNICAL CONSTRAINTS (MANDATORY)
PRESERVE the package declaration exactly as-is.
PRESERVE all existing import statements.
ADD import statements for any NEW type you introduce in the code.
  Check [DEPENDENCY CONTEXT] below for '// SUGGESTED IMPORT' hints.
PRESERVE method signatures (name, parameters, return type).
PRESERVE class-level annotations.
DO NOT create new classes — work within the existing file only.
DO NOT introduce external dependencies not already in the project.
DO NOT modify Spring Boot main class structure.
DO NOT change public API or method signatures.
DO NOT modify existing test code.

### OUTPUT FORMAT (MANDATORY)
Return ONLY the complete Java source file.
Return exactly ONE code block in ```java format.
NO explanations, NO markdown outside the code block.
NO ANSI or invisible characters.\
"""


def _build_task(mode: str, file_name: str) -> str:
    if mode == "test":
        return (
            f"Write comprehensive unit tests with JUnit 5 + Mockito for class '{file_name}'.\n"
            "TECHNICAL GUIDELINES:\n"
            "1. PACKAGE: Use exactly the same package as the original class.\n"
            "2. IMPORTS: Explicitly import Mockito (@Mock, @InjectMocks, Mockito.when), "
            "JUnit 5 (@Test, @BeforeEach, Assertions) and ALL dependencies.\n"
            "3. MOCKS: Use @InjectMocks on the class under test and @Mock on its dependencies.\n"
            "4. INTEGRITY: Verify the original class signatures. "
            "Do not call non-existent methods.\n"
            "5. COVERAGE: Include happy path, edge cases, and error/exception scenarios.\n"
            "6. JAVA RECORDS: If you find 'record', use the canonical constructor (with all arguments).\n"
            "7. FIDELITY: Test only what the code currently does."
        )
    return (
        f"Refactor {file_name} applying the rules below.\n"
        "Preserve existing behavior. Apply only the rules relevant to this file."
    )


def build_prompt(code: str, phase_delta: str, mode: str, file_name: str,
                 dep_context: str = "") -> str:
    """
    Assembles the complete prompt for the model.

    Args:
        code: Java source code of the file to process.
        phase_delta: Phase-specific rules (only what is exclusive to this phase).
        mode: 'refactor' or 'test'.
        file_name: Java file name (e.g. CustomerService.java).
        dep_context: Compact dependency context (optional).
    """
    parts = [
        BASE_CONSTRAINTS,
        f"\n### PHASE RULES\n{phase_delta.strip()}",
        f"\n### TASK\n{_build_task(mode, file_name)}",
    ]
    if dep_context and dep_context.strip():
        parts.append(f"\n### DEPENDENCY CONTEXT\n{dep_context.strip()}")
    parts.append(f"\n### SOURCE FILE TO PROCESS\n```java\n{code}\n```")
    return "\n".join(parts)
```

- [ ] **Step 2.4: Run tests to confirm PASS**

```bash
python -m pytest tests/ai/test_prompt.py -v
```

Expected: `8 passed`

- [ ] **Step 2.5: Commit**

```bash
git add ai/prompt.py tests/ai/test_prompt.py
git commit -m "refactor: decompose prompt into BASE_CONSTRAINTS + phase delta, add dep_context param"
```

---

## Task 3: `ai/model.py` — Conditional `_polish_result()` + dep_context

**Files:**
- Modify: `ai/model.py`

> No unit tests for `_run_pipeline()` since it requires deep Ollama mocks.
> Verification is done by inspecting logs in a real execution (Task 7).

- [ ] **Step 3.1: Add `PHASES_REQUIRING_POLISH` and update `_run_pipeline()`**

Locate the block in `ai/model.py` starting with `def _run_pipeline(` (line ~211) and replace:

```python
# Constant at top of file, after imports:
PHASES_REQUIRING_POLISH: frozenset[str] = frozenset({
    "07_solid", "08_architecture", "09_patterns"
})
```

Inside `_run_pipeline()`, replace:

```python
# BEFORE (line ~250):
if agent != "ultimate" and MODEL_SOLID and MODEL_SOLID not in _OOM_MODELS:
    log(f"  [Skill: Critical] Requesting technical review from {MODEL_SOLID}...")
    result = _polish_result(result, prompt, MODEL_SOLID)
```

with:

```python
# AFTER:
phase_name = phase.split("/")[-1].replace(".md", "") if phase else ""
needs_polish = (
    agent != "ultimate"
    and phase_name in PHASES_REQUIRING_POLISH
    and MODEL_SOLID
    and MODEL_SOLID not in _OOM_MODELS
)
if needs_polish:
    log(f"  [Critical] Reviewing with {MODEL_SOLID} (structural phase: {phase_name})...")
    result = _polish_result(result, prompt, MODEL_SOLID)
```

- [ ] **Step 3.2: Update `call_ai()` to accept and forward `dep_context`**

Replace the `call_ai()` function (line ~299):

```python
# BEFORE:
def call_ai(code: str, rules: str, mode: str, file_name: str,
            file_path: str = "", phase: str = "") -> str | None:
    """Main entry point — generates code from phase rules."""
    prompt = build_prompt(code, rules, mode, file_name)
    return _run_pipeline(prompt, code, file_path, file_name, mode, phase)
```

with:

```python
# AFTER:
def call_ai(code: str, rules: str, mode: str, file_name: str,
            file_path: str = "", phase: str = "",
            dep_context: str = "") -> str | None:
    """Main entry point — generates code from phase rules."""
    prompt = build_prompt(code, rules, mode, file_name, dep_context=dep_context)
    return _run_pipeline(prompt, code, file_path, file_name, mode, phase)
```

- [ ] **Step 3.3: Verify imports are not broken**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent"
python -c "from ai.model import call_ai, PHASES_REQUIRING_POLISH; print('OK', PHASES_REQUIRING_POLISH)"
```

Expected: `OK frozenset({'07_solid', '08_architecture', '09_patterns'})`

- [ ] **Step 3.4: Run all accumulated tests**

```bash
python -m pytest tests/ -v
```

Expected: all passing (Task 1 and Task 2 tests must remain PASS)

- [ ] **Step 3.5: Commit**

```bash
git add ai/model.py
git commit -m "refactor: make _polish_result() conditional on SOLID/Architecture phases only"
```

---

## Task 4: `java/context.py` — Cache-First + Compact Header

**Files:**
- Modify: `java/context.py`
- Create: `tests/java/test_context.py`

- [ ] **Step 4.1: Write tests (TDD — should FAIL now)**

Create `tests/java/test_context.py`:

```python
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from memory.cache import Cache


def make_cache(tmp_path):
    return Cache(str(tmp_path))


# --- _extract_simplified_header ---

def test_header_includes_public_method_signature():
    from java.context import _extract_simplified_header
    code = """\
package com.ex;
public class MyService {
    private String name;
    public String getName() {
        return name;
    }
    private void helper() {}
}"""
    header = _extract_simplified_header(code, "com.ex.MyService")
    assert "getName()" in header
    assert "private String name" not in header    # private fields excluded
    assert "helper" not in header                 # private methods excluded

def test_header_excludes_private_fields():
    from java.context import _extract_simplified_header
    code = """\
package com.ex;
public class OrderService {
    private final OrderRepository repo;
    private int count;
    public void save(Order o) { repo.save(o); }
}"""
    header = _extract_simplified_header(code, "com.ex.OrderService")
    assert "private final OrderRepository" not in header
    assert "private int count" not in header

def test_header_includes_class_declaration():
    from java.context import _extract_simplified_header
    code = "package com.ex;\npublic class Foo {\n    public void run() {}\n}"
    header = _extract_simplified_header(code, "com.ex.Foo")
    assert "class Foo" in header or "Foo" in header


# --- get_dependency_context cache behavior ---

def test_dep_context_cache_hit_avoids_rebuild(tmp_path):
    from java.context import get_dependency_context
    from memory.cache import sha12

    cache = make_cache(tmp_path)
    file_code = "package com.ex;\nimport com.ex.MyDep;\npublic class A {}"
    file_hash = sha12(file_code)

    # Pre-populate cache
    cached_value = "// CACHED CONTEXT"
    cache.set_dep_context(file_hash, cached_value)

    # get_dependency_context should return the cached value WITHOUT doing os.walk
    with patch("java.context._build_dep_context") as mock_build:
        result = get_dependency_context(file_code, "/any/repo", cache=cache)
        mock_build.assert_not_called()
    assert result == cached_value

def test_dep_context_cache_miss_calls_build_and_stores(tmp_path):
    from java.context import get_dependency_context
    from memory.cache import sha12

    cache = make_cache(tmp_path)
    file_code = "package com.ex;\npublic class B {}"
    file_hash = sha12(file_code)

    with patch("java.context._build_dep_context", return_value="// BUILT") as mock_build:
        result = get_dependency_context(file_code, "/any/repo", cache=cache)
        mock_build.assert_called_once()

    assert result == "// BUILT"
    # Should have been stored
    assert cache.get_dep_context(file_hash) == "// BUILT"

def test_dep_context_no_cache_calls_build_directly(tmp_path):
    from java.context import get_dependency_context

    with patch("java.context._build_dep_context", return_value="// NO CACHE") as mock_build:
        result = get_dependency_context("public class C {}", "/any/repo", cache=None)
        mock_build.assert_called_once()
    assert result == "// NO CACHE"
```

- [ ] **Step 4.2: Run tests to confirm FAIL**

```bash
python -m pytest tests/java/test_context.py -v 2>&1 | head -20
```

Expected: FAILED — functions `_build_dep_context` and `cache=` signature do not exist yet

- [ ] **Step 4.3: Replace entire `java/context.py`**

```python
"""
java/context.py — Location: java/context.py

Cache-first: if dep_context for this file is already cached (by hash),
returns immediately without doing os.walk on the project.

_build_dep_context: original generation logic (renamed from internal function).
_extract_simplified_header: optimized to emit only public/protected method
  signatures — removes private fields and comments.
"""

import os
import re
from core.utils import read_file
from memory.cache import sha12


def get_dependency_context(file_code: str, repo_path: str,
                           cache=None) -> str:
    """
    Returns dependency context for the file.
    Cache-first: uses file content hash as key.
    """
    if cache is not None:
        file_hash = sha12(file_code)
        cached = cache.get_dep_context(file_hash)
        if cached is not None:
            return cached

    context = _build_dep_context(file_code, repo_path)

    if cache is not None:
        cache.set_dep_context(sha12(file_code), context)

    return context


def _build_dep_context(file_code: str, repo_path: str) -> str:
    """Generates dependency context by scanning the project (without cache)."""
    package_match = re.search(r'^package\s+([\w.]+);', file_code, re.MULTILINE)
    target_package = package_match.group(1) if package_match else "unknown"

    all_potential_classes = re.findall(r'\b([A-Z]\w+)\b', file_code)
    imports = re.findall(r'^import\s+([\w.]+);', file_code, re.MULTILINE)
    short_imports = {imp.split('.')[-1]: imp for imp in imports}

    context_parts = [f"// TARGET_CLASS_PACKAGE: {target_package}"]
    processed_classes = set()

    for cls_name, full_imp in short_imports.items():
        if not full_imp.startswith("com."):
            continue
        processed_classes.add(cls_name)
        _add_context_for_class(full_imp, repo_path, context_parts)

    for cls_name in all_potential_classes:
        if cls_name in processed_classes or len(cls_name) < 3:
            continue
        if cls_name in {"String", "Long", "Integer", "BigDecimal", "List",
                        "Map", "Optional", "Set", "Boolean", "Double",
                        "Object", "Override", "Autowired", "Service",
                        "Repository", "Controller", "Entity", "Component"}:
            continue
        found_path = _find_class_file(cls_name, repo_path)
        if found_path:
            rel = os.path.relpath(found_path,
                                  os.path.join(repo_path, "src", "main", "java"))
            full_pkg = rel.replace("/", ".").replace(".java", "")
            _add_context_for_class(full_pkg, repo_path, context_parts)
            processed_classes.add(cls_name)

    if len(context_parts) <= 1:
        return ""

    return "\n--- DEPENDENCY CONTEXT (SIGNATURES) ---\n" + "\n".join(context_parts)


def _add_context_for_class(full_imp: str, repo_path: str,
                            context_parts: list) -> None:
    parts = full_imp.split('.')
    potential_path = os.path.join(repo_path, "src", "main", "java",
                                  *parts) + ".java"
    if os.path.exists(potential_path):
        dep_code = read_file(potential_path)
        header = _extract_simplified_header(dep_code, full_imp)
        context_parts.append(f"// SUGGESTED IMPORT: import {full_imp};")
        context_parts.append(header)


def _find_class_file(class_name: str, repo_path: str) -> str | None:
    main_java = os.path.join(repo_path, "src", "main", "java")
    for root, _, files in os.walk(main_java):
        if f"{class_name}.java" in files:
            return os.path.join(root, f"{class_name}.java")
    return None


def _extract_simplified_header(code: str, full_name: str) -> str:
    """
    Extracts only public/protected method signatures.
    Removes: private fields, comments, imports, method bodies.
    Goal: ~80-120 tokens per dependency (vs ~400 tokens before).
    """
    lines = code.splitlines()
    header_lines = []
    class_def_found = False

    for line in lines:
        stripped = line.strip()

        if not stripped:
            continue
        if stripped.startswith(('//', '/*', '*', 'import ', 'package ')):
            if stripped.startswith('package '):
                header_lines.append(stripped)
            continue

        if any(kw in stripped for kw in ('class ', 'interface ', 'enum ', 'record ')):
            class_def_found = True
            decl = stripped.split('{')[0].strip()
            header_lines.append(decl + " {")
            continue

        if not class_def_found:
            continue

        # Only public/protected members with parentheses (methods)
        if ('public ' in stripped or 'protected ' in stripped) and '(' in stripped:
            signature = stripped.split('{')[0].strip()
            if not signature.endswith(';'):
                signature += ";"
            header_lines.append("    " + signature)

    header_lines.append("}")
    return f"// Class: {full_name}\n" + "\n".join(header_lines)
```

- [ ] **Step 4.4: Run tests to confirm PASS**

```bash
python -m pytest tests/java/test_context.py -v
```

Expected: `9 passed`

- [ ] **Step 4.5: Run all accumulated tests**

```bash
python -m pytest tests/ -v
```

Expected: all passing

- [ ] **Step 4.6: Commit**

```bash
git add java/context.py tests/java/test_context.py
git commit -m "refactor: cache-first dep context with compact header extraction"
```

---

## Task 5: `java/refactor.py` — Phase Skip + Cache Propagation

**Files:**
- Modify: `java/refactor.py`

> Unit tests for `refactor_file()` require deep mocks of maven and AI.
> Verification by real execution in Task 7 (integration test).

- [ ] **Step 5.1: Update `_generate_and_validate()` to receive `cache` and pass `dep_context` separately**

Replace the `_generate_and_validate()` function (starts at line ~149):

```python
def _generate_and_validate(original: str, rules: str, mode: str,
                             file_name: str, file_path: str,
                             phase: str = "",
                             cache=None) -> tuple[str | None, str]:
    """
    Calls the AI and validates the result with dependency context injection.
    dep_context is obtained from cache or generated, and passed separately to build_prompt.
    """
    from java.context import get_dependency_context

    dep_context = ""
    try:
        root = file_path
        while root != "/" and not os.path.exists(os.path.join(root, "pom.xml")):
            root = os.path.dirname(root)
        if os.path.exists(os.path.join(root, "pom.xml")):
            dep_context = get_dependency_context(original, root, cache=cache)
    except Exception:
        pass

    test_context = ""
    try:
        test_file = _test_path_for(file_path, root)
        if test_file and os.path.exists(test_file):
            from core.utils import read_file as _read
            test_code = _read(test_file)
            test_context = (
                "\n\n[TEST CONTEXT] The test below validates this class. "
                "Your refactoring MUST ensure it keeps passing:\n\n"
                f"```java\n{test_code}\n```"
            )
            log("  [Context] Unit test injected.", "OK")
    except Exception:
        pass

    phase_delta = rules + test_context

    new_code = call_ai(original, phase_delta, mode, file_name,
                       file_path=file_path, phase=phase,
                       dep_context=dep_context)

    if not new_code:
        return None, "AI did not generate code"

    valid, reason = is_valid_java(original, new_code)
    if valid:
        from java.validator import validate_class_name_matches_file
        is_name_ok, name_error = validate_class_name_matches_file(new_code, file_path)
        if is_name_ok:
            return new_code, ""
        reason = f"INTEGRITY ERROR: {name_error}"

    log(f"  Validator rejected: {reason} — attempting correction", "WARN")

    rejected_code = new_code
    for attempt in range(1, MAX_VALIDATOR_RETRIES + 1):
        log(f"  Validator correction {attempt}/{MAX_VALIDATOR_RETRIES}: {reason[:60]}")
        corrected = call_ai_with_correction(
            original=original, rules=phase_delta, mode=mode,
            file_name=file_name, file_path=file_path,
            bad_output=rejected_code, error_reason=reason, phase=phase
        )
        if not corrected:
            log(f"  Correction {attempt}: no response", "WARN")
            break
        valid, reason = is_valid_java(original, corrected)
        if valid:
            from java.validator import validate_class_name_matches_file
            is_name_ok, name_error = validate_class_name_matches_file(corrected, file_path)
            if is_name_ok:
                log(f"  Correction {attempt}: accepted ✓", "OK")
                return corrected, ""
            reason = (f"INTEGRITY ERROR: {name_error}. "
                      f"The class name must be '{file_name.replace('.java','')}'.")
        log(f"  Correction {attempt}: still rejected — {reason}", "WARN")
        rejected_code = corrected

    return None, reason
```

- [ ] **Step 5.2: Update signatures of `_refactor_whole_file()` and `_refactor_by_method()`**

In `_refactor_whole_file()`, change only the signature line and the `_generate_and_validate()` call:

```python
# Signature: add cache=None at the end
def _refactor_whole_file(file: str, original: str, rules: str,
                          repo_path: str, phase: str,
                          reporter: PhaseReporter,
                          exec_logger: ExecutionLogger | None,
                          cache=None) -> bool:
    file_name = os.path.basename(file)
    mode = _mode_for(file)

    # Change this call to include cache=cache
    new_code, reason = _generate_and_validate(
        original, rules, mode, file_name, file, phase=phase, cache=cache
    )
    # THE REST OF THE FUNCTION (_refactor_whole_file) STAYS EXACTLY THE SAME
    # (validation, write_file, maven_test, _attempt_global_sync, etc.)
```

In `_refactor_by_method()`, change only the signature and calls to `_generate_and_validate()`:

```python
# Signature: add cache=None at the end
def _refactor_by_method(file: str, original: str, rules: str,
                         repo_path: str, phase: str,
                         reporter: PhaseReporter,
                         exec_logger: ExecutionLogger | None,
                         cache=None) -> bool:
    file_name = os.path.basename(file)
    mode = _mode_for(file)

    header = extract_class_header(original)
    methods = get_processable_methods(original)

    if not methods:
        log(f"  {file_name}: no extractable methods — trying whole file")
        return _refactor_whole_file(file, original, rules, repo_path, phase,
                                    reporter, exec_logger, cache=cache)

    log(f"  {file_name}: {len(methods)} methods to process")
    current_code = original
    methods_changed = 0
    methods_failed = 0

    for method in methods:
        log(f"    → {method.name}() [{len(method.full_text.splitlines())}L]")
        context = build_method_context(header, method)

        # Change this call to include cache=cache
        ai_response, reason = _generate_and_validate(
            original=context, rules=rules, mode=mode,
            file_name=file_name, file_path=file,
            phase=phase, cache=cache,
        )
        # THE REST OF THE LOOP (extract_refactored_method, replace_method_in_file, etc.)
        # STAYS EXACTLY THE SAME as the original code

    # THE REMAINDER OF THE FUNCTION (_refactor_by_method) STAYS EXACTLY THE SAME
```

- [ ] **Step 5.3: Update `refactor_file()` — phase skip + mark_phase_done**

Replace the complete `refactor_file()` function:

```python
def refactor_file(file: str, rules: str, repo_path: str,
                  phase: str, reporter: PhaseReporter,
                  exec_logger: ExecutionLogger | None = None,
                  cache=None) -> bool:
    file_name = os.path.basename(file)

    # Phase skip: if we already processed this file in this phase this run, skip
    if cache is not None:
        phase_name = phase.split("/")[-1].replace(".md", "")
        if cache.is_phase_done(file, phase_name):
            log(f"  {file_name}: cache hit — {phase_name} already applied this run", "OK")
            reporter.record_skipped(phase, file_name, f"cache: {phase_name} already applied")
            return False

    log(f"Processing [{_mode_for(file)}]: {file_name}")

    if exec_logger:
        exec_logger.log_file_processing(phase, file_name, "unknown", "unknown")

    original = read_file(file)

    skip, reason = should_skip(file, original)
    if skip:
        log(f"  {file_name} SKIPPED: {reason}", "WARN")
        if exec_logger:
            exec_logger.log_file_skipped(phase, file_name, reason)
        reporter.record_skipped(phase, file_name, reason)
        return False

    if is_large_file(original, LARGE_FILE_THRESHOLD):
        log(f"  {file_name}: large file → method-by-method processing")
        success = _refactor_by_method(file, original, rules, repo_path, phase,
                                      reporter, exec_logger, cache=cache)
    else:
        success = _refactor_whole_file(file, original, rules, repo_path, phase,
                                       reporter, exec_logger, cache=cache)

    if success and cache is not None:
        phase_name = phase.split("/")[-1].replace(".md", "")
        cache.mark_phase_done(file, phase_name)

    return success
```

- [ ] **Step 5.4: Update `build_project_dictionary` to use cache**

In `_refactor_whole_file()`, where the `build_project_dictionary(repo_path)` call is (inside the "cannot find symbol" block), replace:

```python
# BEFORE:
from java.dictionary import build_project_dictionary
proj_map = build_project_dictionary(repo_path)

# AFTER:
from java.dictionary import build_project_dictionary
proj_map = None
if cache is not None:
    proj_map = cache.get_project_dict()
if proj_map is None:
    proj_map = build_project_dictionary(repo_path)
    if cache is not None:
        cache.set_project_dict(proj_map)
```

- [ ] **Step 5.5: Verify imports are correct**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent"
python -c "from java.refactor import refactor_file; print('OK')"
```

Expected: `OK`

- [ ] **Step 5.6: Run all tests**

```bash
python -m pytest tests/ -v
```

Expected: all passing

- [ ] **Step 5.7: Commit**

```bash
git add java/refactor.py
git commit -m "refactor: add phase skip via Cache + separate dep_context from rules in refactor pipeline"
```

---

## Task 6: Phase Files — Remove Duplicate Rules

**Files:**
- Modify: `phases/solid/07_solid.md`
- Modify: `phases/solid/08_architecture.md`
- Modify: `phases/solid/09_patterns.md`
- Modify: `phases/clean/10_clean_code.md`
- Modify: `phases/doc/01_javadoc.md`
- Modify: `phases/struct/04_nomenclature.md`

> Global rules (do not create classes, preserve signatures, do not modify tests)
> were moved to `BASE_CONSTRAINTS` in `ai/prompt.py` — Task 2.
> Each phase should now contain ONLY what is exclusive to it.

- [ ] **Step 6.1: Check `phases/solid/09_patterns.md` (file not yet read)**

```bash
cat "/home/emerson/Área de trabalho/ai-refactor-agent/phases/solid/09_patterns.md"
cat "/home/emerson/Área de trabalho/ai-refactor-agent/phases/doc/02_final_keywords.md"
cat "/home/emerson/Área de trabalho/ai-refactor-agent/phases/doc/03_documentation.md"
cat "/home/emerson/Área de trabalho/ai-refactor-agent/phases/struct/05_structure.md"
cat "/home/emerson/Área de trabalho/ai-refactor-agent/phases/struct/06_tracking.md"
cat "/home/emerson/Área de trabalho/ai-refactor-agent/phases/claude/11_unit_tests.md"
cat "/home/emerson/Área de trabalho/ai-refactor-agent/phases/claude/12_integration_tests.md"
```

Read the content of each file before editing.

- [ ] **Step 6.2: Remove the duplicate final line from `phases/solid/07_solid.md`**

The last line `"Do not change public API or method signatures."` is now covered by `BASE_CONSTRAINTS`. Remove that line from the file.

- [ ] **Step 6.3: Remove the duplicate final line from `phases/solid/08_architecture.md`**

The last line `"Do not change method signatures, return types, or existing test code."` is covered by `BASE_CONSTRAINTS`. Remove.

- [ ] **Step 6.4: Remove the duplicate final line from `phases/clean/10_clean_code.md`**

The last line `"Do not change method signatures, return types, or public API."` is covered by `BASE_CONSTRAINTS`. Remove.

- [ ] **Step 6.5: Remove the duplicate line from `phases/doc/01_javadoc.md`**

The last line `"Do not alter existing code — only add comments."` — keep, as it is specific to Javadoc (different behavior from other phases).

- [ ] **Step 6.6: Remove duplicate lines from `phases/struct/04_nomenclature.md`**

The lines `"Do NOT rename: public API methods..."` and `"Do NOT rename identifiers in other files"` are specific to this phase — keep. Check if there are other duplicates.

- [ ] **Step 6.7: Commit phases**

```bash
git add phases/
git commit -m "refactor: trim phase files — remove rules already in BASE_CONSTRAINTS"
```

---

## Task 7: `main.py` — Fix 2 Bugs + Cache Integration

**Files:**
- Modify: `main.py`
- Modify: `.gitignore`

This task fixes two critical bugs that prevent the agent from working:

- **Bug 1:** `os.listdir(PHASES_DIR)` returns subdirectory names (`['doc', 'solid', ...]`), none ending in `.md`, so `phases = []` and the loop never executes.
- **Bug 2:** `refactor_file(f_path, phase_file, rules, reporter, exec_logger)` — arguments in wrong order. The signature is `(file, rules, repo_path, phase, reporter, exec_logger)`.

- [ ] **Step 7.1: Add `.refactor_cache/` to `.gitignore`**

```bash
echo ".refactor_cache/" >> "/home/emerson/Área de trabalho/ai-refactor-agent/.gitignore"
```

- [ ] **Step 7.2: Replace the import block and `main()` function in `main.py`**

Locate and replace the import at the top:

```python
# BEFORE:
from git_utils.repo import clone_or_update, commit_and_push

# AFTER:
from git_utils.repo import clone_or_update, commit_and_push
from memory.cache import Cache
```

- [ ] **Step 7.3: Fix phase loading (Bug 1)**

Locate (line ~102):

```python
# BEFORE (BUG — not recursive):
phases = sorted([f for f in os.listdir(PHASES_DIR) if f.endswith(".md")])
for phase_file in phases:
    phase_path = os.path.join(PHASES_DIR, phase_file)
    rules = read_file(phase_path)
```

Replace with:

```python
# AFTER (recursive via os.walk):
phase_paths = []
for root, _, files in os.walk(PHASES_DIR):
    for f in sorted(files):
        if f.endswith(".md") and not f.startswith("_"):
            phase_paths.append(os.path.join(root, f))
phase_paths = sorted(phase_paths)  # ensures global numeric order

for phase_path in phase_paths:
    phase_file = os.path.basename(phase_path)
    rules = read_file(phase_path)
```

- [ ] **Step 7.4: Initialize Cache and fix the `refactor_file` call (Bug 2)**

Right after `repo_path` is defined (line ~72, after `log(f"Repository: {repo_path}", "OK")`), add:

```python
cache = Cache(repo_path)
```

Locate the phase loop and fix the call (Bug 2):

```python
# BEFORE (BUG — arguments out of order):
for f_path in files:
    refactor_file(f_path, phase_file, rules, reporter, exec_logger)

# AFTER (correct order + cache injected):
for f_path in files:
    refactor_file(f_path, rules, repo_path, phase_file,
                  reporter, exec_logger, cache=cache)
```

- [ ] **Step 7.5: Verify main.py imports**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent"
python -c "import main; print('imports OK')" 2>&1
```

Expected: `imports OK` (may fail due to `input()` but not due to ImportError)

- [ ] **Step 7.6: Run all tests**

```bash
python -m pytest tests/ -v
```

Expected: all passing

- [ ] **Step 7.7: Verify phases are loaded correctly**

```bash
python -c "
import os
PHASES_DIR = 'phases'
phase_paths = []
for root, _, files in os.walk(PHASES_DIR):
    for f in sorted(files):
        if f.endswith('.md') and not f.startswith('_'):
            phase_paths.append(os.path.join(root, f))
phase_paths = sorted(phase_paths)
for p in phase_paths:
    print(p)
"
```

Expected: list with 12 `.md` files in order:
```
phases/clean/10_clean_code.md
phases/claude/11_unit_tests.md
phases/claude/12_integration_tests.md
phases/doc/01_javadoc.md
phases/doc/02_final_keywords.md
phases/doc/03_documentation.md
phases/solid/07_solid.md
phases/solid/08_architecture.md
phases/solid/09_patterns.md
phases/struct/04_nomenclature.md
phases/struct/05_structure.md
phases/struct/06_tracking.md
```

- [ ] **Step 7.8: Final commit**

```bash
git add main.py .gitignore
git commit -m "fix: load phases recursively (bug 1), fix refactor_file arg order (bug 2), integrate Cache"
```

---

## Final Verification

- [ ] **Run all tests one last time**

```bash
python -m pytest tests/ -v --tb=short
```

Expected: all passing, zero failures

- [ ] **Verify cache dir is created on Cache import**

```bash
python -c "
from memory.cache import Cache
import tempfile, os
with tempfile.TemporaryDirectory() as d:
    c = Cache(d)
    c.set_dep_context('test', '// hello')
    assert c.get_dep_context('test') == '// hello'
    c.mark_phase_done('/file.java', '01_javadoc')
    assert c.is_phase_done('/file.java', '01_javadoc')
    assert not c.is_phase_done('/file.java', '07_solid')
    print('Cache: OK')
"
```

Expected: `Cache: OK`

- [ ] **Consolidation commit (if needed)**

```bash
git log --oneline -8
```

Confirm that commits are in correct order and messages make sense.
