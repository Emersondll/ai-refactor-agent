# Agent Loop — Design Spec

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform the fixed-phase pipeline into a real agent — Claude reasons about what to do, Ollama executes it — using a Plan-then-Execute loop with replanning on build failure.

**Architecture:** `agent/` package with four modules (observation, planner, skill_catalog, loop). `main.py` routes to the agent loop when `USE_AGENT_MODE=true`. All existing `refactor_file()` and build infrastructure remains unchanged.

**Tech Stack:** Claude API (planner brain), Ollama (execution), existing `java/refactor.py`, `java/compiler.py`, `memory/cache.py`, `memory/semantic_memory.py`.

---

## Motivation

The current pipeline runs every phase on every file in a fixed alphabetical order — regardless of what the project actually needs. A file that already has clean code still goes through `10_clean_code.md`. A file with a critical SOLID violation waits behind 6 earlier phases.

A real agent observes the project state, reasons about the highest-value action, and iterates until it declares done or hits a budget ceiling. This is the difference between a script and an agent.

---

## Constraints

- `USE_AGENT_MODE=false` by default — existing pipeline is the fallback, zero regressions
- Claude is called only for planning decisions, never for Java code generation (Ollama does that)
- All existing skills (`refactor_file`, `maven_test`, `call_ai_with_correction`, etc.) are reused unchanged
- Tests are generated **before** the agent loop starts, locking the behavioral contract
- The agent loop terminates when: Claude declares `done`, `AGENT_MAX_CYCLES` is reached, or 3 consecutive replanning cycles produce no accepted changes

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `agent/__init__.py` | Create | Package marker |
| `agent/observation.py` | Create | Collect project state → structured dict for Claude |
| `agent/planner.py` | Create | Call Claude API → parse JSON plan |
| `agent/skill_catalog.py` | Create | Registry: skill name → phase file path or reactive handler |
| `agent/loop.py` | Create | Main agent loop: observe → plan → execute → replan |
| `config.py` | Modify | Add `USE_AGENT_MODE`, `AGENT_MAX_CYCLES` flags |
| `main.py` | Modify | Route to `agent/loop.py` when `USE_AGENT_MODE=true` |
| `tests/agent/test_observation.py` | Create | Unit tests for observation module |
| `tests/agent/test_planner.py` | Create | Unit tests for planner (mocked Claude) |
| `tests/agent/test_skill_catalog.py` | Create | Unit tests for catalog resolution |

---

## Skill Catalog

The catalog is the agent's action menu. Claude receives the skill list with descriptions at each planning call. Skills fall into three types:

### Phase Skills (existing `.md` files)

| Skill ID | Source File | Description |
|---|---|---|
| `javadoc` | `phases/doc/01_javadoc.md` | Add Javadoc to all public methods and classes |
| `final-keywords` | `phases/doc/02_final_keywords.md` | Add `final` to parameters and local variables |
| `documentation` | `phases/doc/03_documentation.md` | Improve inline comments and class-level docs |
| `nomenclature` | `phases/struct/04_nomenclature.md` | Rename identifiers to Java naming conventions |
| `structure` | `phases/struct/05_structure.md` | Reorganize member order (fields → constructors → methods) |
| `tracking` | `phases/struct/06_tracking.md` | Add correlation/tracing infrastructure |
| `solid` | `phases/solid/07_solid.md` | Apply SRP, OCP, LSP, ISP, DIP |
| `architecture` | `phases/solid/08_architecture.md` | Fix layering violations (controller→service→repository) |
| `patterns` | `phases/solid/09_patterns.md` | Apply GoF design patterns where appropriate |
| `clean-code` | `phases/clean/10_clean_code.md` | Reduce cyclomatic complexity, extract methods |
| `unit-tests` | `phases/claude/11_unit_tests.md` | Generate JUnit 5 + Mockito unit tests |
| `integration-tests` | `phases/claude/12_integration_tests.md` | Generate Spring Boot integration tests |

### Community Skills (well-known refactoring patterns)

These are new phase files to be created under `phases/community/`. Each encodes a named technique from the refactoring literature.

| Skill ID | Source | Description |
|---|---|---|
| `extract-method` | Fowler — Refactoring #1 | Break methods > 20 lines into named sub-methods |
| `guard-clause` | Clean Code — Martin | Replace nested if/else with early return (guard clauses) |
| `replace-magic-number` | Fowler | Replace inline literals with named constants |
| `introduce-parameter-object` | Fowler | Group ≥ 3 related parameters into a value object / record |
| `decompose-conditional` | Fowler | Extract complex boolean conditions into named methods |
| `null-to-optional` | Effective Java — Bloch | Replace nullable returns with `Optional<T>` |
| `loop-to-stream` | Effective Java | Replace imperative loops with Stream API equivalents |
| `record-migration` | Java 16+ | Replace simple data-holder classes with `record` |
| `builder-pattern` | GoF | Introduce Builder for classes with > 4 constructor params |
| `strategy-pattern` | GoF | Replace conditional dispatch (if/switch on type) with Strategy |
| `dead-code-elimination` | Universal | Remove unused fields, methods, imports, and unreachable blocks |
| `encapsulate-field` | Fowler | Make public fields private; add getters/setters only where needed |

### Reactive Skills (agent infrastructure)

| Skill ID | Handler | Description |
|---|---|---|
| `fix-build` | `agent/loop.py` | Call `call_ai_with_correction()` targeting the failing file |
| `skip-file` | `agent/loop.py` | Mark file in `failed_files.json`; do not retry this run |
| `analyze-state` | `agent/loop.py` | Force a full observation refresh (used after major changes) |
| `done` | `agent/loop.py` | Terminate the loop — agent declares no improvements remain |

---

## Observation Format

`agent/observation.py` builds this dict at the start of each planning cycle. Claude receives it serialized as JSON inside the planning prompt.

```json
{
  "project": "card-transaction-authorizer",
  "build": "green",
  "cycle": 2,
  "max_cycles": 20,
  "files": [
    {
      "name": "TransactionController.java",
      "path": "src/main/java/.../TransactionController.java",
      "lines": 87,
      "phases_applied": ["javadoc", "nomenclature"],
      "phases_pending": ["solid", "architecture", "clean-code"],
      "community_skills_applied": [],
      "build_failures": 0,
      "last_result": "accepted"
    },
    {
      "name": "BalanceServiceImpl.java",
      "path": "src/main/java/.../BalanceServiceImpl.java",
      "lines": 134,
      "phases_applied": ["javadoc"],
      "phases_pending": ["solid", "architecture"],
      "community_skills_applied": ["extract-method"],
      "build_failures": 2,
      "last_result": "build_failed"
    }
  ],
  "failed_files": ["TransactionServiceImpl.java"],
  "last_build_error": null,
  "skills_available": ["solid", "architecture", "extract-method", "guard-clause", "fix-build", "skip-file", "done"]
}
```

**Data sources:**
- `cache.is_phase_done(file, phase)` → `phases_applied`
- `failed_files.json` → `build_failures`, `last_result`, `failed_files`
- `maven_test()` → `build`, `last_build_error`
- `get_java_files()` → file list with line counts

The observation is always fresh — never cached between cycles.

---

## Plan Format

Claude returns a JSON object with an ordered list of actions. The executor runs them top-to-bottom.

```json
{
  "reasoning": "TransactionController has SOLID and architecture violations. BalanceServiceImpl has repeated build failures — skipping. extract-method applicable to large methods in MerchantServiceImpl.",
  "plan": [
    {"skill": "solid",          "file": "TransactionController.java", "reason": "SOLID not yet applied"},
    {"skill": "architecture",   "file": "TransactionController.java", "reason": "layer violations likely after SOLID"},
    {"skill": "extract-method", "file": "MerchantServiceImpl.java",   "reason": "134 lines, high complexity"},
    {"skill": "guard-clause",   "file": "MerchantServiceImpl.java",   "reason": "nested conditionals visible in context"},
    {"skill": "skip-file",      "file": "BalanceServiceImpl.java",    "reason": "2 build failures — not safe this cycle"},
    {"skill": "done",           "file": null,                         "reason": "no more high-value improvements available"}
  ]
}
```

**Rules enforced by the parser:**
- `done` must be the last action if present
- `fix-build` requires `"build": "red"` in the observation
- Each (skill, file) pair is unique within a plan (no duplicates)
- Max 10 actions per plan (controlled by the planning prompt)

---

## Planning Prompt

`agent/planner.py` builds the Claude prompt as:

```
{soul.md content}

You are acting as a refactoring agent planner. You do NOT write Java code.
Your job is to decide WHAT to refactor and in WHAT ORDER.

## Current Project State
{observation as JSON}

## Skill Catalog
{skill_id}: {description}
...

## Rules
- Prioritize files with 0 build_failures over files with failures
- Apply phase skills in logical dependency order (javadoc before solid, solid before patterns)
- Community skills can be applied in any order after core phases
- Include "done" only when no file has pending high-value skills
- Return valid JSON only — no markdown, no explanation outside the JSON

## Response Format
{"reasoning": "...", "plan": [...]}
```

---

## Agent Loop (`agent/loop.py`)

```
run_agent_loop(repo_path, reporter, exec_logger, cache, semantic_mem):

  1. Generate tests (existing flow — locks behavioral contract)
  2. cycle = 0
  3. consecutive_no_progress = 0

  4. LOOP:
     a. observation = build_observation(repo_path, cache, cycle, max_cycles)
     b. plan = call_planner(observation)          # Claude API call
     c. cycle += 1
     d. actions_accepted = 0

     e. FOR action IN plan:
        IF action.skill == "done": EXIT LOOP (clean)
        IF action.skill == "fix-build": run fix-build handler
        IF action.skill == "skip-file": run skip-file handler
        ELSE: refactor_file(file, skill_rules, repo_path, phase_path, ...)
              IF accepted: actions_accepted += 1
              IF build red after action: BREAK inner loop → go to step f

     f. IF build red:
        consecutive_no_progress += 1
        IF consecutive_no_progress >= 3: EXIT LOOP (stuck)
        add build_error to observation context
        CONTINUE (replan next cycle with build error in observation)
     ELSE:
        IF actions_accepted == 0: consecutive_no_progress += 1
        ELSE: consecutive_no_progress = 0

     g. IF cycle >= max_cycles: EXIT LOOP (budget)

  5. Sanitization → Final validation → Commit+push (existing flow)
```

---

## Replanning Trigger

Replanning happens automatically — there is no separate "replan" call. The loop always collects a fresh observation before calling the planner. The observation includes `last_build_error` when the build is red. Claude sees the error and adjusts the plan accordingly (typically: `fix-build` or `skip-file` for the offending file).

This means replanning costs exactly 1 additional Claude API call per build failure — not a special code path.

---

## Termination Conditions

| Condition | Exit type | Action |
|---|---|---|
| Claude returns `done` in plan | Clean | Log "Agent declared done" |
| `cycle >= AGENT_MAX_CYCLES` | Budget | Log "Max cycles reached" |
| `consecutive_no_progress >= 3` | Stuck | Log "No progress in 3 cycles — exiting" |

After any exit, the existing post-loop flow runs: sanitization, final `maven_test()`, coverage check, `commit_and_push()`.

---

## Configuration

New flags in `config.py` (opt-in, all disabled by default):

```python
USE_AGENT_MODE   = os.getenv("USE_AGENT_MODE",   "false").lower() == "true"
AGENT_MAX_CYCLES = int(os.getenv("AGENT_MAX_CYCLES", "20"))
```

---

## Community Phase Files to Create

Each file goes in `phases/community/` and follows the same format as existing phase files (rules written for the LLM).

Files to create:
- `phases/community/extract_method.md`
- `phases/community/guard_clause.md`
- `phases/community/replace_magic_number.md`
- `phases/community/introduce_parameter_object.md`
- `phases/community/decompose_conditional.md`
- `phases/community/null_to_optional.md`
- `phases/community/loop_to_stream.md`
- `phases/community/record_migration.md`
- `phases/community/builder_pattern.md`
- `phases/community/strategy_pattern.md`
- `phases/community/dead_code_elimination.md`
- `phases/community/encapsulate_field.md`

---

## Testing Strategy

- `test_observation.py` — mock `cache`, `failed_files.json`, `maven_test()` → assert observation dict shape
- `test_planner.py` — mock `call_claude()` → assert plan is parsed correctly; assert invalid JSON is handled gracefully
- `test_skill_catalog.py` — assert every skill ID resolves to a file path or handler; assert no missing phase files

No integration tests — the agent loop itself is tested by running against the real repo.

---

## What Does NOT Change

- `java/refactor.py` — untouched
- `java/compiler.py` — untouched
- `ai/model.py` — untouched
- `memory/cache.py` — untouched
- `phases/` existing files — untouched
- `main.py` fallback path (`USE_AGENT_MODE=false`) — untouched
- Dashboard — continues to work (execution_logger events are the same)
