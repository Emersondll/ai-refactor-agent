# Agent Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed-phase pipeline with a real agent loop — Claude plans batches of actions, Ollama executes them, the loop replans on build failure and stops when Claude declares done or budget is exhausted.

**Architecture:** New `agent/` package with four modules (skill_catalog, observation, planner, loop). `main.py` routes to `agent/loop.py` when `USE_AGENT_MODE=true`; the existing pipeline is the fallback. All existing `refactor_file()`, `maven_test()`, and build infrastructure are reused unchanged.

**Tech Stack:** Claude API (planner), Ollama (Java refactoring executor), `anthropic` SDK, existing `java/refactor.py`, `java/compiler.py`, `memory/cache.py`, `memory/semantic_memory.py`.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `config.py` | Modify | Add `USE_AGENT_MODE`, `AGENT_MAX_CYCLES` flags |
| `phases/community/*.md` | Create (12 files) | Community skill rules for the LLM |
| `agent/__init__.py` | Create | Package marker |
| `agent/skill_catalog.py` | Create | Registry: skill ID → phase file path + descriptions |
| `agent/observation.py` | Create | Collect project state → dict for Claude |
| `agent/planner.py` | Create | Call Claude API, parse JSON plan |
| `agent/loop.py` | Create | Main agent loop: observe → plan → execute → replan |
| `main.py` | Modify | Route to agent loop when `USE_AGENT_MODE=true` |
| `tests/agent/__init__.py` | Create | Test package marker |
| `tests/agent/test_skill_catalog.py` | Create | Unit tests for catalog resolution |
| `tests/agent/test_observation.py` | Create | Unit tests for observation builder |
| `tests/agent/test_planner.py` | Create | Unit tests for planner (mocked Claude) |

---

## Task 1: Config Flags

**Files:**
- Modify: `config.py`

- [ ] **Step 1.1: Add flags to config.py**

Open `config.py` and after the `OLLAMA_BASE_URL` line add:

```python
# ---------------------------------------------------------------------------
# Agent Loop (disabled by default — enable via .env)
# ---------------------------------------------------------------------------
USE_AGENT_MODE   = os.getenv("USE_AGENT_MODE",   "false").lower() == "true"
AGENT_MAX_CYCLES = int(os.getenv("AGENT_MAX_CYCLES", "20"))
```

- [ ] **Step 1.2: Verify**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent"
.venv/bin/python -c "from config import USE_AGENT_MODE, AGENT_MAX_CYCLES; print(USE_AGENT_MODE, AGENT_MAX_CYCLES)"
```

Expected: `False 20`

- [ ] **Step 1.3: Commit**

```bash
git add config.py
git commit -m "feat: add USE_AGENT_MODE and AGENT_MAX_CYCLES config flags"
```

---

## Task 2: Community Phase Files

**Files:**
- Create: `phases/community/` (12 `.md` files)

- [ ] **Step 2.1: Create directory**

```bash
mkdir -p "/home/emerson/Área de trabalho/ai-refactor-agent/phases/community"
```

- [ ] **Step 2.2: Create `phases/community/extract_method.md`**

```markdown
# Community Skill — Extract Method (Fowler)

Break long methods into smaller, named sub-methods.

## What you MUST do

- If a method has more than 20 lines, identify logical blocks inside it and extract each into a private method with a descriptive name.
- The extracted method name must describe WHAT it does, not HOW (e.g. `validateTransaction()` not `doCheck()`).
- The original method becomes an orchestration of the extracted methods.
- Do NOT change the public signature of the original method.
- Do NOT extract if the method is already ≤ 20 lines — return the file unchanged.

## What you MUST NOT do

- Do NOT create new classes.
- Do NOT change method visibility (private stays private, public stays public).
- Do NOT extract a block that references more than 3 local variables — it would require too many parameters.
```

- [ ] **Step 2.3: Create `phases/community/guard_clause.md`**

```markdown
# Community Skill — Guard Clause (Clean Code)

Replace nested conditionals with early returns to reduce nesting depth.

## What you MUST do

- Identify methods with if/else blocks nested more than 2 levels deep.
- Invert the condition at each nesting level and return (or throw) early.
- The "happy path" should be the last non-guarded code in the method.
- Example transformation:
  BEFORE: `if (valid) { if (hasBalance) { process(); } }`
  AFTER: `if (!valid) return; if (!hasBalance) return; process();`

## What you MUST NOT do

- Do NOT change method signatures or return types.
- Do NOT introduce new exception types not already used in the file.
- Do NOT apply if the method already has max 2 nesting levels — return unchanged.
```

- [ ] **Step 2.4: Create `phases/community/replace_magic_number.md`**

```markdown
# Community Skill — Replace Magic Number (Fowler)

Replace inline numeric or string literals with named constants.

## What you MUST do

- Identify numeric or string literals that appear more than once OR whose meaning is not self-evident.
- Declare them as `private static final` constants at the top of the class, before constructors.
- Name constants in UPPER_SNAKE_CASE that express the business meaning (e.g. `MAX_RETRY_ATTEMPTS`, `DEFAULT_TIMEOUT_SECONDS`).
- Replace all occurrences of the literal with the constant name.

## What you MUST NOT do

- Do NOT extract `0`, `1`, `-1`, `true`, `false` — these are universally understood.
- Do NOT extract literals that only appear once AND are self-evident in context.
- Do NOT change method signatures or class structure.
```

- [ ] **Step 2.5: Create `phases/community/introduce_parameter_object.md`**

```markdown
# Community Skill — Introduce Parameter Object (Fowler)

Group related parameters that always appear together into a Java record.

## What you MUST do

- Identify methods with 4 or more parameters where a logical subset always appears together.
- Extract that subset into a `record` declared as a nested `record` inside the same file (do NOT create a new file).
- Update the method signature to accept the record instead of the individual parameters.
- Update all call sites WITHIN THE SAME FILE only.

## What you MUST NOT do

- Do NOT modify call sites in other files — that would break the build.
- Do NOT create new top-level classes or files.
- Do NOT apply if the method has fewer than 4 parameters.
```

- [ ] **Step 2.6: Create `phases/community/decompose_conditional.md`**

```markdown
# Community Skill — Decompose Conditional (Fowler)

Extract complex boolean conditions into named predicate methods.

## What you MUST do

- Identify `if` conditions that have more than 2 clauses joined by `&&` or `||`.
- Extract the condition into a private method with a name that describes what it checks (e.g. `isEligibleForDiscount()`).
- The predicate method returns `boolean` and takes the same parameters the condition uses.

## What you MUST NOT do

- Do NOT decompose simple single-clause conditions.
- Do NOT change the observable behavior of the conditional logic.
- Do NOT create new classes.
```

- [ ] **Step 2.7: Create `phases/community/null_to_optional.md`**

```markdown
# Community Skill — Null to Optional (Effective Java)

Replace nullable return values with Optional<T>.

## What you MUST do

- Identify private or package-private methods that return a reference type and may return `null`.
- Change the return type from `T` to `Optional<T>`.
- Replace `return null` with `return Optional.empty()`.
- Wrap non-null returns: `return Optional.of(value)` or `return Optional.ofNullable(value)`.
- Update all call sites WITHIN THE SAME FILE to use `.orElse()`, `.orElseThrow()`, or `.isPresent()`.
- Add `import java.util.Optional;` if not already present.

## What you MUST NOT do

- Do NOT change PUBLIC method signatures — Optional on public APIs is controversial and may break callers.
- Do NOT apply to methods that return collections (use empty collection instead).
- Do NOT wrap primitives — use `OptionalInt`, `OptionalLong` only if already used in the file.
```

- [ ] **Step 2.8: Create `phases/community/loop_to_stream.md`**

```markdown
# Community Skill — Loop to Stream (Effective Java)

Replace imperative for/while loops with Stream API equivalents.

## What you MUST do

- Identify simple loops that: filter elements, map/transform elements, or collect into a list/set.
- Replace with `stream().filter().map().collect(Collectors.toList())` equivalents.
- Add `import java.util.stream.Collectors;` if not already present.

## What you MUST NOT do

- Do NOT convert loops that modify external state (side effects) — streams are not appropriate there.
- Do NOT convert loops with `break` or `continue` unless the logic maps cleanly to `filter()`.
- Do NOT convert loops that catch checked exceptions inside the body.
- Do NOT apply if the result is less readable than the original loop.
```

- [ ] **Step 2.9: Create `phases/community/record_migration.md`**

```markdown
# Community Skill — Record Migration (Java 16+)

Replace simple data-holder classes with Java records.

## What you MUST do

- Identify classes that: have only final private fields, a constructor that sets all fields, and only getters (no setters, no business logic).
- Convert them to `record` syntax: `public record ClassName(Type field1, Type field2) {}`.
- Records auto-generate constructor, getters (`field1()` not `getField1()`), `equals`, `hashCode`, `toString`.
- Update getter call sites WITHIN THE SAME FILE from `getField()` to `field()`.

## What you MUST NOT do

- Do NOT convert classes annotated with `@Entity`, `@Document`, `@Table` — JPA/MongoDB require mutable classes.
- Do NOT convert classes that have mutable state (non-final fields, setters).
- Do NOT convert classes with inheritance (`extends` something other than `Object`).
- Do NOT update getter call sites in other files — that would break callers.
```

- [ ] **Step 2.10: Create `phases/community/builder_pattern.md`**

```markdown
# Community Skill — Builder Pattern (GoF)

Introduce a Builder for classes with more than 4 constructor parameters.

## What you MUST do

- Identify classes with a constructor that has more than 4 parameters.
- Add a `public static Builder` nested class inside the same file.
- The Builder has one method per field (returning `this` for chaining) and a `build()` method.
- Keep the original constructor as-is (do NOT remove it) — the Builder calls it.

## What you MUST NOT do

- Do NOT remove the original constructor — callers in other files depend on it.
- Do NOT create a new file for the Builder.
- Do NOT apply if the class already has a Builder or uses Lombok `@Builder`.
```

- [ ] **Step 2.11: Create `phases/community/strategy_pattern.md`**

```markdown
# Community Skill — Strategy Pattern (GoF)

Replace type-based if/switch dispatch with Strategy interface.

## What you MUST do

- Identify methods that switch on a type field or enum to select behavior.
- Extract the varying behavior into a private interface (nested inside the same file).
- Create private static implementations (one per case) as anonymous classes or lambdas.
- Replace the if/switch with a Map lookup from type → strategy.

## What you MUST NOT do

- Do NOT create new top-level interfaces or classes — keep everything in the same file.
- Do NOT apply if there are only 2 cases — a simple if/else is more readable.
- Do NOT change the public method signature.
```

- [ ] **Step 2.12: Create `phases/community/dead_code_elimination.md`**

```markdown
# Community Skill — Dead Code Elimination

Remove unused code that adds noise and maintenance burden.

## What you MUST do

- Remove private methods that are never called within the class.
- Remove unused private fields that are declared but never read.
- Remove unused local variables inside methods.
- Remove unused import statements.
- Remove commented-out code blocks (// old code that was disabled).

## What you MUST NOT do

- Do NOT remove public or protected members — callers in other files may use them.
- Do NOT remove fields annotated with `@Autowired`, `@Value`, `@Mock`, `@InjectMocks`.
- Do NOT remove methods annotated with `@Bean`, `@Override`, `@EventListener`.
- When in doubt, leave it — a false positive here breaks the build.
```

- [ ] **Step 2.13: Create `phases/community/encapsulate_field.md`**

```markdown
# Community Skill — Encapsulate Field (Fowler)

Make public fields private and expose only necessary accessors.

## What you MUST do

- Identify fields declared as `public` (non-constant, non-static).
- Change them to `private`.
- Add a getter method if the field is read from outside the class.
- Add a setter method only if the field is written from outside the class.
- Getter naming: `getFieldName()` for objects, `isFieldName()` for booleans.

## What you MUST NOT do

- Do NOT encapsulate `public static final` constants — they are intentionally public.
- Do NOT add setters speculatively — only if there is evidence of external writes.
- Do NOT change fields annotated with `@JsonProperty` or `@SerializedName` — serialization frameworks access them directly.
```

- [ ] **Step 2.14: Verify all 12 files exist**

```bash
ls "/home/emerson/Área de trabalho/ai-refactor-agent/phases/community/"
```

Expected: 12 `.md` files listed.

- [ ] **Step 2.15: Commit**

```bash
git add phases/community/
git commit -m "feat: add 12 community skill phase files (Fowler, GoF, Clean Code, Effective Java)"
```

---

## Task 3: `agent/skill_catalog.py`

**Files:**
- Create: `agent/__init__.py`
- Create: `agent/skill_catalog.py`
- Create: `tests/agent/__init__.py`
- Create: `tests/agent/test_skill_catalog.py`

- [ ] **Step 3.1: Write failing tests**

Create `tests/agent/__init__.py` (empty) and `tests/agent/test_skill_catalog.py`:

```python
import pytest
from unittest.mock import patch
import os


def test_resolve_phase_file_returns_path_for_known_skill(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    phase_dir = tmp_path / "phases" / "solid"
    phase_dir.mkdir(parents=True)
    (phase_dir / "07_solid.md").write_text("# solid rules")

    from agent.skill_catalog import resolve_phase_file
    result = resolve_phase_file("solid")
    assert result is not None
    assert result.endswith("07_solid.md")


def test_resolve_phase_file_returns_none_for_unknown_skill():
    from agent.skill_catalog import resolve_phase_file
    assert resolve_phase_file("nonexistent-skill") is None


def test_is_reactive_true_for_fix_build():
    from agent.skill_catalog import is_reactive
    assert is_reactive("fix-build") is True


def test_is_reactive_false_for_phase_skill():
    from agent.skill_catalog import is_reactive
    assert is_reactive("solid") is False


def test_is_terminal_true_for_done():
    from agent.skill_catalog import is_terminal
    assert is_terminal("done") is True


def test_is_terminal_false_for_others():
    from agent.skill_catalog import is_terminal
    assert is_terminal("solid") is False
    assert is_terminal("fix-build") is False


def test_catalog_for_prompt_contains_all_skills():
    from agent.skill_catalog import catalog_for_prompt, SKILL_DESCRIPTIONS
    prompt = catalog_for_prompt()
    for skill_id in SKILL_DESCRIPTIONS:
        assert skill_id in prompt


def test_all_phase_skill_ids_returns_list():
    from agent.skill_catalog import all_phase_skill_ids
    ids = all_phase_skill_ids()
    assert "solid" in ids
    assert "extract-method" in ids
    assert len(ids) == 24  # 12 phase + 12 community
```

- [ ] **Step 3.2: Run tests — expect FAIL**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent"
.venv/bin/python -m pytest tests/agent/test_skill_catalog.py -v 2>&1 | head -15
```

Expected: `ModuleNotFoundError` for `agent.skill_catalog`.

- [ ] **Step 3.3: Create `agent/__init__.py`**

```bash
mkdir -p "/home/emerson/Área de trabalho/ai-refactor-agent/agent"
touch "/home/emerson/Área de trabalho/ai-refactor-agent/agent/__init__.py"
```

- [ ] **Step 3.4: Create `agent/skill_catalog.py`**

```python
"""
agent/skill_catalog.py — Registry of all skills the agent can invoke.

resolve_phase_file(skill_id): returns path to .md file or None.
is_reactive(skill_id): True for fix-build, skip-file, analyze-state.
is_terminal(skill_id): True for done.
catalog_for_prompt(): returns formatted string for the planning prompt.
"""

import os

_PHASE_SKILLS: dict[str, str] = {
    "javadoc":                    "phases/doc/01_javadoc.md",
    "final-keywords":             "phases/doc/02_final_keywords.md",
    "documentation":              "phases/doc/03_documentation.md",
    "nomenclature":               "phases/struct/04_nomenclature.md",
    "structure":                  "phases/struct/05_structure.md",
    "tracking":                   "phases/struct/06_tracking.md",
    "solid":                      "phases/solid/07_solid.md",
    "architecture":               "phases/solid/08_architecture.md",
    "patterns":                   "phases/solid/09_patterns.md",
    "clean-code":                 "phases/clean/10_clean_code.md",
    "unit-tests":                 "phases/claude/11_unit_tests.md",
    "integration-tests":          "phases/claude/12_integration_tests.md",
    "extract-method":             "phases/community/extract_method.md",
    "guard-clause":               "phases/community/guard_clause.md",
    "replace-magic-number":       "phases/community/replace_magic_number.md",
    "introduce-parameter-object": "phases/community/introduce_parameter_object.md",
    "decompose-conditional":      "phases/community/decompose_conditional.md",
    "null-to-optional":           "phases/community/null_to_optional.md",
    "loop-to-stream":             "phases/community/loop_to_stream.md",
    "record-migration":           "phases/community/record_migration.md",
    "builder-pattern":            "phases/community/builder_pattern.md",
    "strategy-pattern":           "phases/community/strategy_pattern.md",
    "dead-code-elimination":      "phases/community/dead_code_elimination.md",
    "encapsulate-field":          "phases/community/encapsulate_field.md",
}

_REACTIVE_SKILLS: set[str] = {"fix-build", "skip-file", "analyze-state"}

SKILL_DESCRIPTIONS: dict[str, str] = {
    "javadoc":                    "Add Javadoc to all public methods and classes",
    "final-keywords":             "Add final to parameters and local variables where safe",
    "documentation":              "Improve inline comments and class-level documentation",
    "nomenclature":               "Rename identifiers to Java naming conventions",
    "structure":                  "Reorganize member order: fields → constructors → public → private",
    "tracking":                   "Add correlation/tracing infrastructure (MDC, logging context)",
    "solid":                      "Apply SOLID principles: SRP, OCP, LSP, ISP, DIP",
    "architecture":               "Fix layering violations (controller→service→repository)",
    "patterns":                   "Apply GoF design patterns where they reduce complexity",
    "clean-code":                 "Reduce cyclomatic complexity, extract methods, remove duplication",
    "unit-tests":                 "Generate JUnit 5 + Mockito unit tests with ≥90% coverage",
    "integration-tests":          "Generate Spring Boot integration tests",
    "extract-method":             "[Fowler] Break methods >20 lines into named sub-methods",
    "guard-clause":               "[Clean Code] Replace nested if/else with early return guard clauses",
    "replace-magic-number":       "[Fowler] Replace inline literals with named constants",
    "introduce-parameter-object": "[Fowler] Group ≥4 related parameters into a record",
    "decompose-conditional":      "[Fowler] Extract complex boolean conditions into predicate methods",
    "null-to-optional":           "[Effective Java] Replace nullable returns with Optional<T>",
    "loop-to-stream":             "[Effective Java] Replace imperative loops with Stream API",
    "record-migration":           "[Java 16+] Replace simple data-holder classes with record",
    "builder-pattern":            "[GoF] Introduce Builder for classes with >4 constructor parameters",
    "strategy-pattern":           "[GoF] Replace if/switch on type with Strategy interface",
    "dead-code-elimination":      "Remove unused fields, methods, imports, commented-out blocks",
    "encapsulate-field":          "[Fowler] Make public fields private; add accessors only as needed",
    "fix-build":                  "REACTIVE: Attempt to repair current build failure (only when red)",
    "skip-file":                  "REACTIVE: Mark file as unprocessable this run",
    "done":                       "TERMINAL: No more improvements available — stop the loop",
}


def resolve_phase_file(skill_id: str) -> str | None:
    path = _PHASE_SKILLS.get(skill_id)
    if path and os.path.exists(path):
        return path
    return None


def is_reactive(skill_id: str) -> bool:
    return skill_id in _REACTIVE_SKILLS


def is_terminal(skill_id: str) -> bool:
    return skill_id == "done"


def all_phase_skill_ids() -> list[str]:
    return list(_PHASE_SKILLS.keys())


def catalog_for_prompt() -> str:
    return "\n".join(f"- {sid}: {desc}" for sid, desc in SKILL_DESCRIPTIONS.items())
```

- [ ] **Step 3.5: Run tests — expect PASS**

```bash
.venv/bin/python -m pytest tests/agent/test_skill_catalog.py -v
```

Expected: 8 passed.

- [ ] **Step 3.6: Commit**

```bash
git add agent/__init__.py agent/skill_catalog.py tests/agent/__init__.py tests/agent/test_skill_catalog.py
git commit -m "feat: add agent/skill_catalog — registry of 24 phase skills + 3 reactive skills"
```

---

## Task 4: `agent/observation.py`

**Files:**
- Create: `agent/observation.py`
- Create: `tests/agent/test_observation.py`

- [ ] **Step 4.1: Write failing tests**

Create `tests/agent/test_observation.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
import os


def _make_cache(phases_done: dict) -> MagicMock:
    cache = MagicMock()
    cache.is_phase_done.side_effect = lambda f, p: phases_done.get((f, p), False)
    return cache


def test_observation_has_required_keys(tmp_path):
    cache = _make_cache({})
    with patch("agent.observation.get_java_files", return_value=[]), \
         patch("agent.observation.get_failed_tracker") as mock_ft:
        mock_ft.return_value._entries = []
        mock_ft.return_value.get_build_failure_count.return_value = 0
        from agent.observation import build_observation
        obs = build_observation(str(tmp_path), cache, cycle=1, max_cycles=20)

    for key in ("project", "build", "cycle", "max_cycles", "files",
                "failed_files", "last_build_error", "skills_available"):
        assert key in obs, f"Missing key: {key}"


def test_observation_build_green_by_default(tmp_path):
    cache = _make_cache({})
    with patch("agent.observation.get_java_files", return_value=[]), \
         patch("agent.observation.get_failed_tracker") as mock_ft:
        mock_ft.return_value._entries = []
        mock_ft.return_value.get_build_failure_count.return_value = 0
        from agent.observation import build_observation
        obs = build_observation(str(tmp_path), cache, cycle=1, max_cycles=20, build_ok=True)

    assert obs["build"] == "green"


def test_observation_build_red_when_passed(tmp_path):
    cache = _make_cache({})
    with patch("agent.observation.get_java_files", return_value=[]), \
         patch("agent.observation.get_failed_tracker") as mock_ft:
        mock_ft.return_value._entries = []
        mock_ft.return_value.get_build_failure_count.return_value = 0
        from agent.observation import build_observation
        obs = build_observation(str(tmp_path), cache, cycle=2, max_cycles=20,
                                build_ok=False, last_build_error="[ERROR] cannot find symbol")

    assert obs["build"] == "red"
    assert "cannot find symbol" in obs["last_build_error"]


def test_observation_phases_applied_from_cache(tmp_path):
    java_file = tmp_path / "Foo.java"
    java_file.write_text("public class Foo {}")
    cache = _make_cache({(str(java_file), "solid"): True})
    with patch("agent.observation.get_failed_tracker") as mock_ft:
        mock_ft.return_value._entries = []
        mock_ft.return_value.get_build_failure_count.return_value = 0
        with patch("agent.observation.get_java_files", return_value=[str(java_file)]):
            from agent.observation import build_observation
            obs = build_observation(str(tmp_path), cache, cycle=1, max_cycles=20)

    assert len(obs["files"]) == 1
    assert "solid" in obs["files"][0]["phases_applied"]
    assert "solid" not in obs["files"][0]["phases_pending"]
```

- [ ] **Step 4.2: Run tests — expect FAIL**

```bash
.venv/bin/python -m pytest tests/agent/test_observation.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError` for `agent.observation`.

- [ ] **Step 4.3: Create `agent/observation.py`**

```python
"""
agent/observation.py — Collects project state into a structured dict for Claude.

build_observation(): reads cache, failed_tracker, and file system.
Does NOT call maven_test() — the loop passes build_ok as a parameter.
"""

import os
from java.refactor import get_java_files, get_failed_tracker
from agent.skill_catalog import all_phase_skill_ids, _PHASE_SKILLS, _REACTIVE_SKILLS


def build_observation(repo_path: str, cache, cycle: int, max_cycles: int,
                      build_ok: bool = True,
                      last_build_error: str | None = None) -> dict:
    java_files = get_java_files(repo_path)
    failed_tracker = get_failed_tracker()
    all_entries = failed_tracker._entries
    failed_paths: set[str] = {e["file"] for e in all_entries}
    all_skills = all_phase_skill_ids()

    files_data = []
    for f in java_files:
        phases_applied = [s for s in all_skills if cache.is_phase_done(f, s)]
        phases_pending  = [s for s in all_skills if s not in phases_applied]
        build_failures  = failed_tracker.get_build_failure_count(f)

        last_result = "pending"
        file_entries = [e for e in all_entries if e["file"] == f]
        if file_entries:
            last_reason = file_entries[-1].get("reason", "")
            last_result = "build_failed" if "build quebrou" in last_reason else "rejected"

        try:
            with open(f, encoding="utf-8") as fh:
                lines = sum(1 for _ in fh)
        except Exception:
            lines = 0

        files_data.append({
            "name": os.path.basename(f),
            "path": f,
            "lines": lines,
            "phases_applied": phases_applied,
            "phases_pending": phases_pending,
            "build_failures": build_failures,
            "last_result": last_result,
        })

    available_skills = (
        list(_PHASE_SKILLS.keys())
        + [s for s in _REACTIVE_SKILLS if s != "analyze-state"]
        + ["done"]
    )

    return {
        "project": os.path.basename(repo_path),
        "build": "green" if build_ok else "red",
        "cycle": cycle,
        "max_cycles": max_cycles,
        "files": files_data,
        "failed_files": [os.path.basename(p) for p in failed_paths],
        "last_build_error": last_build_error,
        "skills_available": available_skills,
    }
```

- [ ] **Step 4.4: Run tests — expect PASS**

```bash
.venv/bin/python -m pytest tests/agent/test_observation.py -v
```

Expected: 4 passed.

- [ ] **Step 4.5: Run full suite — no regressions**

```bash
.venv/bin/python -m pytest tests/ -v 2>&1 | tail -5
```

Expected: all previously passing tests still pass.

- [ ] **Step 4.6: Commit**

```bash
git add agent/observation.py tests/agent/test_observation.py
git commit -m "feat: add agent/observation — project state collector for planning prompt"
```

---

## Task 5: `agent/planner.py`

**Files:**
- Create: `agent/planner.py`
- Create: `tests/agent/test_planner.py`

- [ ] **Step 5.1: Write failing tests**

Create `tests/agent/test_planner.py`:

```python
import pytest
from unittest.mock import patch, MagicMock


def _mock_claude(response_text: str):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=response_text)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg
    return mock_client


def test_call_planner_returns_plan_list(monkeypatch):
    monkeypatch.setattr("agent.planner.CLAUDE_API_KEY", "fake-key")
    valid_response = '{"reasoning": "apply solid", "plan": [{"skill": "solid", "file": "Foo.java", "reason": "pending"}]}'
    with patch("agent.planner.anthropic.Anthropic", return_value=_mock_claude(valid_response)):
        from agent.planner import call_planner
        plan = call_planner({"build": "green", "files": [], "skills_available": []})
    assert isinstance(plan, list)
    assert plan[0]["skill"] == "solid"


def test_call_planner_handles_json_parse_error(monkeypatch):
    monkeypatch.setattr("agent.planner.CLAUDE_API_KEY", "fake-key")
    with patch("agent.planner.anthropic.Anthropic", return_value=_mock_claude("not json at all")):
        from agent.planner import call_planner
        plan = call_planner({"build": "green", "files": [], "skills_available": []})
    assert plan[0]["skill"] == "done"


def test_call_planner_handles_missing_api_key(monkeypatch):
    monkeypatch.setattr("agent.planner.CLAUDE_API_KEY", None)
    from agent.planner import call_planner
    plan = call_planner({"build": "green", "files": [], "skills_available": []})
    assert plan[0]["skill"] == "done"


def test_call_planner_strips_markdown_fences(monkeypatch):
    monkeypatch.setattr("agent.planner.CLAUDE_API_KEY", "fake-key")
    fenced = '```json\n{"reasoning": "r", "plan": [{"skill": "done", "file": null, "reason": "ok"}]}\n```'
    with patch("agent.planner.anthropic.Anthropic", return_value=_mock_claude(fenced)):
        from agent.planner import call_planner
        plan = call_planner({"build": "green", "files": [], "skills_available": []})
    assert plan[0]["skill"] == "done"
```

- [ ] **Step 5.2: Run tests — expect FAIL**

```bash
.venv/bin/python -m pytest tests/agent/test_planner.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError` for `agent.planner`.

- [ ] **Step 5.3: Create `agent/planner.py`**

```python
"""
agent/planner.py — Calls Claude API with project observation, returns ordered action plan.

call_planner(observation): → list[dict] with keys skill, file, reason.
Returns [{"skill": "done", ...}] on any error (fail-safe).
"""

import json
import os
import anthropic

from config import CLAUDE_API_KEY, CLAUDE_MODEL
from agent.skill_catalog import catalog_for_prompt
from core.utils import read_file
from core.logger import log

_PLANNER_SYSTEM = """\
You are a Java refactoring agent planner. You do NOT write Java code.
Your job is to decide WHAT to refactor and in WHAT ORDER.

Rules:
- Prioritize files with build_failures == 0 over files with failures
- Apply javadoc/nomenclature before solid/architecture before community skills
- Include "done" as the last action only when no file has meaningful pending skills
- "fix-build" is only valid when build field is "red"
- Maximum 10 actions per plan
- Each (skill, file) pair must appear only once in the plan
- Return valid JSON only — no markdown, no explanation outside the JSON object

Response format (strict JSON):
{"reasoning": "...", "plan": [{"skill": "...", "file": "filename.java or null", "reason": "..."}, ...]}
"""


def call_planner(observation: dict) -> list[dict]:
    if not CLAUDE_API_KEY:
        log("[Planner] ANTHROPIC_API_KEY not set — returning done", "ERR")
        return [{"skill": "done", "file": None, "reason": "no API key configured"}]

    soul = _load_soul()
    catalog = catalog_for_prompt()
    obs_json = json.dumps(observation, indent=2, ensure_ascii=False)

    prompt = (
        f"{soul}\n\n"
        "## Current Project State\n"
        f"{obs_json}\n\n"
        "## Available Skills\n"
        f"{catalog}\n\n"
        "Decide the next batch of refactoring actions. Return JSON only."
    )

    try:
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=_PLANNER_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()

        # Strip markdown code fences if model adds them
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        data = json.loads(raw)
        plan = data.get("plan", [])
        reasoning = data.get("reasoning", "")
        log(f"[Planner] {reasoning[:150]}")
        return plan

    except json.JSONDecodeError as e:
        log(f"[Planner] JSON parse error: {e}", "ERR")
        return [{"skill": "done", "file": None, "reason": "planner JSON parse error"}]
    except Exception as e:
        log(f"[Planner] Error: {e}", "ERR")
        return [{"skill": "done", "file": None, "reason": f"planner error: {e}"}]


def _load_soul() -> str:
    soul_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "soul.md"
    )
    try:
        return read_file(soul_path)
    except Exception:
        return ""
```

- [ ] **Step 5.4: Run tests — expect PASS**

```bash
.venv/bin/python -m pytest tests/agent/test_planner.py -v
```

Expected: 4 passed.

- [ ] **Step 5.5: Commit**

```bash
git add agent/planner.py tests/agent/test_planner.py
git commit -m "feat: add agent/planner — Claude API planner with JSON plan parsing"
```

---

## Task 6: `agent/loop.py`

**Files:**
- Create: `agent/loop.py`

No unit tests for the loop itself — it orchestrates too many live dependencies. Verified by integration run in Task 8.

- [ ] **Step 6.1: Create `agent/loop.py`**

```python
"""
agent/loop.py — Main agent loop: observe → plan → execute → replan.

run_agent_loop(): replaces the fixed phase loop in main.py when USE_AGENT_MODE=true.
Terminates when Claude returns "done", AGENT_MAX_CYCLES is reached,
or 3 consecutive cycles produce no accepted changes.
"""

import os
from core.logger import log
from core.utils import read_file
from core.execution_logger import ExecutionLogger
from core.reporter import PhaseReporter
from java.refactor import refactor_file, get_failed_tracker
from java.compiler import maven_test
from agent.observation import build_observation
from agent.planner import call_planner
from agent.skill_catalog import resolve_phase_file, is_reactive, is_terminal
from config import AGENT_MAX_CYCLES


def run_agent_loop(repo_path: str, reporter: PhaseReporter,
                   exec_logger: ExecutionLogger, cache, semantic_mem) -> None:
    cycle = 0
    consecutive_no_progress = 0
    build_ok = True
    last_build_error: str | None = None

    log("=" * 60, "PHASE")
    log("AGENT MODE — Plan-then-Execute Loop", "PHASE")
    log(f"Max cycles: {AGENT_MAX_CYCLES}", "PHASE")
    log("=" * 60, "PHASE")

    while cycle < AGENT_MAX_CYCLES:
        log(f"\n[Cycle {cycle + 1}/{AGENT_MAX_CYCLES}] Building observation...", "PHASE")
        observation = build_observation(
            repo_path, cache, cycle + 1, AGENT_MAX_CYCLES,
            build_ok=build_ok, last_build_error=last_build_error,
        )

        log(f"[Cycle {cycle + 1}] Calling planner (Claude)...", "PHASE")
        plan = call_planner(observation)
        cycle += 1

        if not plan:
            log("[Agent] Empty plan — exiting", "WARN")
            break

        actions_accepted = 0
        build_broke_this_cycle = False

        for action in plan:
            skill     = action.get("skill", "")
            file_name = action.get("file")
            reason    = action.get("reason", "")

            log(f"  → [{skill}] {file_name or '—'} : {reason}")

            if is_terminal(skill):
                log("[Agent] Declared done — no more improvements available.", "OK")
                return

            if skill == "skip-file":
                _handle_skip(file_name, repo_path, reason, exec_logger)
                continue

            if skill == "fix-build":
                build_ok, _ = maven_test(repo_path)
                if build_ok:
                    last_build_error = None
                    actions_accepted += 1
                continue

            if skill == "analyze-state":
                continue  # observation is always fresh on next cycle

            phase_file = resolve_phase_file(skill)
            if not phase_file:
                log(f"  [Agent] Unknown or missing skill '{skill}' — skipping", "WARN")
                continue

            file_path = _find_java_file(file_name, repo_path)
            if not file_path:
                log(f"  [Agent] '{file_name}' not found — skipping", "WARN")
                continue

            rules    = read_file(phase_file)
            accepted = refactor_file(
                file_path, rules, repo_path, phase_file,
                reporter, exec_logger, cache=cache, semantic_mem=semantic_mem,
            )

            if accepted:
                actions_accepted += 1
                build_ok, build_output = maven_test(repo_path)
                if not build_ok:
                    last_build_error = _extract_errors(build_output)
                    log(f"  [Agent] Build broke after [{skill}] {file_name} — replanning", "WARN")
                    build_broke_this_cycle = True
                    break
                else:
                    last_build_error = None

        # Progress accounting
        if build_broke_this_cycle or actions_accepted == 0:
            consecutive_no_progress += 1
        else:
            consecutive_no_progress = 0

        if consecutive_no_progress >= 3:
            log("[Agent] No progress in 3 consecutive cycles — exiting (stuck).", "WARN")
            break

        log(f"[Cycle {cycle}] Complete — {actions_accepted} action(s) accepted.", "OK")

    if cycle >= AGENT_MAX_CYCLES:
        log(f"[Agent] Budget exhausted ({AGENT_MAX_CYCLES} cycles).", "WARN")


def _find_java_file(file_name: str | None, repo_path: str) -> str | None:
    if not file_name:
        return None
    for root, _, files in os.walk(repo_path):
        if "target" in root.replace("\\", "/").split("/"):
            continue
        if file_name in files:
            return os.path.join(root, file_name)
    return None


def _handle_skip(file_name: str | None, repo_path: str, reason: str,
                  exec_logger: ExecutionLogger) -> None:
    file_path = _find_java_file(file_name, repo_path)
    if file_path:
        get_failed_tracker().record(file_path, "agent-skip", f"Agent: {reason}")
    if exec_logger and file_name:
        exec_logger.log_file_skipped("agent", file_name, reason)
    log(f"  [Agent] Skipped '{file_name}': {reason}", "WARN")


def _extract_errors(build_output: str) -> str:
    lines = [l for l in build_output.splitlines() if "[ERROR]" in l]
    return "\n".join(lines[:10])
```

- [ ] **Step 6.2: Verify import**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent"
.venv/bin/python -c "from agent.loop import run_agent_loop; print('OK')"
```

Expected: `OK`

- [ ] **Step 6.3: Commit**

```bash
git add agent/loop.py
git commit -m "feat: add agent/loop — Plan-then-Execute loop with replanning on build failure"
```

---

## Task 7: `main.py` — Routing

**Files:**
- Modify: `main.py`

- [ ] **Step 7.1: Add import and routing to main.py**

In `main.py`, add after the existing imports at the top:

```python
from config import USE_AGENT_MODE
```

Then find the block that starts the phase loop (around line 111):

```python
    # --- Fases de Refatoração (SOLID) ---
    phase_paths = sorted(
        os.path.join(root, fname)
        for root, _, files in os.walk(PHASES_DIR)
        for fname in files
        if fname.endswith(".md")
    )
    _all_java_files = get_java_files(repo_path)
    exec_logger.log_files_total(len(_all_java_files))
    exec_logger.log_files_queue([os.path.basename(f) for f in _all_java_files])

    for phase_path in phase_paths:
        phase_file = os.path.basename(phase_path)
        rules = read_file(phase_path)
        log(f"Iniciando Fase: {phase_file}", "PHASE")
        exec_logger.log_phase_start(phase_file, f"Iniciando {phase_file}")

        files = get_java_files(repo_path)
        for f_path in files:
            refactor_file(f_path, rules, repo_path, phase_path, reporter, exec_logger,
                          cache=cache, semantic_mem=semantic_mem)
```

Replace it with:

```python
    # --- Refatoração: Agent Loop ou Pipeline fixo ---
    _all_java_files = get_java_files(repo_path)
    exec_logger.log_files_total(len(_all_java_files))
    exec_logger.log_files_queue([os.path.basename(f) for f in _all_java_files])

    if USE_AGENT_MODE:
        log("Modo Agente ativado — Claude planeja, Ollama executa.", "PHASE")
        from agent.loop import run_agent_loop
        run_agent_loop(repo_path, reporter, exec_logger, cache, semantic_mem)
    else:
        log("Modo Pipeline fixo (USE_AGENT_MODE=false).", "PHASE")
        phase_paths = sorted(
            os.path.join(root, fname)
            for root, _, files in os.walk(PHASES_DIR)
            for fname in files
            if fname.endswith(".md")
        )
        for phase_path in phase_paths:
            phase_file = os.path.basename(phase_path)
            rules = read_file(phase_path)
            log(f"Iniciando Fase: {phase_file}", "PHASE")
            exec_logger.log_phase_start(phase_file, f"Iniciando {phase_file}")
            for f_path in get_java_files(repo_path):
                refactor_file(f_path, rules, repo_path, phase_path, reporter, exec_logger,
                              cache=cache, semantic_mem=semantic_mem)
```

- [ ] **Step 7.2: Verify import**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent"
.venv/bin/python -c "import main; print('imports OK')" 2>&1 | grep -v "^$"
```

Expected: `imports OK` (or only the `input()` prompt — no ImportError).

- [ ] **Step 7.3: Run full test suite**

```bash
.venv/bin/python -m pytest tests/ -v 2>&1 | tail -8
```

Expected: all tests passing (47 + new agent tests).

- [ ] **Step 7.4: Commit**

```bash
git add main.py
git commit -m "feat: route to agent/loop when USE_AGENT_MODE=true; keep fixed pipeline as fallback"
```

---

## Task 8: Final Verification

- [ ] **Step 8.1: Run complete test suite**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent"
.venv/bin/python -m pytest tests/ -v
```

Expected: all tests passing, 0 failed.

- [ ] **Step 8.2: Verify full import chain**

```bash
.venv/bin/python -c "
from agent.skill_catalog import resolve_phase_file, catalog_for_prompt
from agent.observation import build_observation
from agent.planner import call_planner
from agent.loop import run_agent_loop
print('All agent imports OK')
"
```

Expected: `All agent imports OK`

- [ ] **Step 8.3: Verify USE_AGENT_MODE=false leaves pipeline unchanged**

```bash
.venv/bin/python -c "
from config import USE_AGENT_MODE
assert not USE_AGENT_MODE, 'should be false by default'
print('Default: pipeline mode — OK')
"
```

Expected: `Default: pipeline mode — OK`

- [ ] **Step 8.4: Verify skill catalog covers all community phase files**

```bash
.venv/bin/python -c "
from agent.skill_catalog import _PHASE_SKILLS
import os
missing = []
for skill_id, path in _PHASE_SKILLS.items():
    if not os.path.exists(path):
        missing.append((skill_id, path))
if missing:
    for s, p in missing: print(f'MISSING: {s} -> {p}')
else:
    print(f'All {len(_PHASE_SKILLS)} phase files exist — OK')
"
```

Expected: `All 24 phase files exist — OK`

- [ ] **Step 8.5: Final commit**

```bash
git add .
git commit -m "feat: complete agent loop — Plan-then-Execute with Claude planner + 24-skill catalog

- agent/skill_catalog.py: 24 skills (12 phase + 12 community) + 3 reactive
- agent/observation.py: project state collector (cache, failed_files, build)
- agent/planner.py: Claude API planner with JSON plan parsing + fail-safe
- agent/loop.py: Plan-then-Execute loop with replanning on build failure
- main.py: routes to agent loop when USE_AGENT_MODE=true
- phases/community/: 12 new skill files (Fowler, GoF, Clean Code, Effective Java)
- Tests: all passing

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Enabling Agent Mode

Add to `.env` to activate:

```env
USE_AGENT_MODE=true
AGENT_MAX_CYCLES=20
```

Leave unset (or `false`) to keep the existing fixed-phase pipeline.
