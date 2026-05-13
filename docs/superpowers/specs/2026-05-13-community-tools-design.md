# Design Spec — Community Tools Refactoring Engine

**Date:** 2026-05-13  
**Status:** Approved  
**Scope:** Replace LLM-as-author with deterministic community tools (OpenRewrite + Google Java Format). LLM acts only as reviewer (APPROVE/REJECT), never writes Java code.

---

## Problem

The current flow sends Java files to a local LLM (qwen2.5-coder:14b) which rewrites them according to rules in `.md` files. This causes:

- LLM ignores rules (`@Document` converted to record despite explicit prohibition)
- Non-deterministic output — same file, different result each run
- Retry loops — failed changes not cached, planner retries infinitely
- Slow — 30s+ per file, hundreds of files
- Build breaks from hallucinated code

## Solution — Approach 1: Tool-First with LLM Review Gate

Community tools execute changes deterministically. LLM only reads the resulting diff and approves or rejects it. LLM never writes Java code.

---

## Architecture

```
Planner (Ollama local — qwen2.5-coder:14b)
    ↓ selects skill_id
Skill Config Loader
    ↓ loads phases/configs/<skill>.yml
Community Runner
    ├── OpenRewrite  →  mvn rewrite:run  →  modifies files in-place
    └── Google Java Format  →  gjf --replace  →  formats files in-place
    ↓ git diff --unified=5
LLM Reviewer (qwen2.5-coder:14b)
    ↓ diff + review_criteria → APPROVE | REJECT | SKIP
    ├── APPROVE  →  maven_test()  →  OK: keep  |  FAIL: git checkout
    └── REJECT   →  git checkout (revert all tool changes)
```

---

## Skill Catalog

8 deterministic skills replacing the previous 24 LLM-based skills:

| skill_id | Tool | Recipes / Command |
|---|---|---|
| `format` | Google Java Format | `google-java-format --replace **/*.java` |
| `final-keywords` | OpenRewrite | `FinalizeLocalVariables`, `FinalizeMethodArguments` |
| `clean-imports` | OpenRewrite | `RemoveUnusedImports`, `OrderImports` |
| `naming-conventions` | OpenRewrite | `MethodNameCasing`, `FieldNameCasing`, `LocalVariableNameCasing` |
| `simplify-code` | OpenRewrite | `SimplifyBooleanExpression`, `SimplifyBooleanReturn`, `UnnecessaryParentheses` |
| `dead-code` | OpenRewrite | `RemoveUnusedLocalVariables`, `RemoveUnusedImports` |
| `modernize-syntax` | OpenRewrite | `UseDiamondOperator`, `UseStringIsEmpty`, `NoDoubleBraceInitialization` |
| `static-analysis` | OpenRewrite | Full `rewrite-static-analysis` suite |

**Reactive skills (unchanged):** `fix-build`, `skip-file`, `done`

---

## File Structure

### New files

```
java/
  community_runner.py       # runs OpenRewrite or GJF, returns (changed: bool, diff: str)
  llm_reviewer.py           # sends diff + criteria to LLM, returns APPROVE|REJECT|SKIP

phases/
  configs/
    format.yml
    final-keywords.yml
    clean-imports.yml
    naming-conventions.yml
    simplify-code.yml
    dead-code.yml
    modernize-syntax.yml
    static-analysis.yml
```

### Modified files

```
agent/skill_catalog.py    # _PHASE_SKILLS → points to .yml configs
agent/loop.py             # dispatches to community_runner + llm_reviewer
main.py                   # fixed pipeline iterates .yml configs
config.py                 # add GJF_PATH (default: google-java-format)
```

### Removed / deprecated

```
phases/community/         # all 12 .md files — replaced by .yml configs
phases/doc/               # all 3 .md files — replaced by .yml configs
phases/solid/             # all 3 .md files — replaced by .yml configs
phases/struct/            # all 3 .md files — replaced by .yml configs
phases/clean/             # .md files — replaced by .yml configs
phases/claude/            # .md files — replaced by .yml configs
```

---

## Skill Config Format (.yml)

```yaml
skill: final-keywords
description: Adiciona final a variáveis locais e parâmetros não reatribuídos
tool: openrewrite                          # openrewrite | google-java-format
artifact_coordinates:
  - org.openrewrite.recipe:rewrite-static-analysis:RELEASE
recipes:
  - org.openrewrite.staticanalysis.FinalizeLocalVariables
  - org.openrewrite.staticanalysis.FinalizeMethodArguments
review_criteria: |
  O diff deve APENAS adicionar 'final' a variáveis locais e parâmetros
  de método onde o valor nunca é reatribuído.
  REJEITE se: lógica alterada, métodos adicionados/removidos,
  ou qualquer mudança além de inserção de 'final'.
```

For `google-java-format` tool, `artifact_coordinates` and `recipes` are omitted.

---

## Module Specs

### `java/community_runner.py`

```
run_skill(skill_config: dict, repo_path: str) -> tuple[bool, str]
  # Returns (changed, diff)
  # changed=False → diff is empty → SKIP
  # changed=True  → diff contains tool output → pass to reviewer

_run_openrewrite(repo_path, artifact_coordinates, recipes) -> None
  # Runs: mvn -U org.openrewrite.maven:rewrite-maven-plugin:run
  #   -Drewrite.recipeArtifactCoordinates=<coords joined by comma>
  #   -Drewrite.activeRecipes=<recipes joined by comma>

_run_google_java_format(repo_path) -> None
  # Runs: google-java-format --replace on all .java files in src/main/java/

_get_diff(repo_path) -> str
  # Runs: git diff --unified=5
  # Returns empty string if no changes
```

### `java/llm_reviewer.py`

```
review_diff(diff: str, criteria: str, model: str) -> Literal["APPROVE", "REJECT", "SKIP"]
  # SKIP if diff is empty
  # Sends prompt to Ollama via call_model()
  # Parses first word of response: APPROVE or REJECT
  # Timeout fallback: returns APPROVE after 60s (non-blocking)

_build_prompt(diff, criteria) -> str
  # Constructs the review prompt
```

**Review prompt template:**
```
Você é um revisor de código Java. Analise o diff abaixo.

CRITÉRIOS DE APROVAÇÃO:
{criteria}

DIFF:
{diff}

Responda APENAS com uma das opções:
APPROVE: <motivo em 1 linha>
REJECT: <motivo em 1 linha>
```

### `agent/loop.py` — updated dispatch

```python
# Instead of: refactor_file(file_path, rules, ...)
# New flow:

config = load_skill_config(skill_id)          # loads .yml
changed, diff = run_skill(config, repo_path)  # runs tool
if not changed:
    cache.mark_phase_done(skill_id)
    continue

verdict = review_diff(diff, config["review_criteria"])
if verdict == "REJECT":
    git_restore(repo_path)           # git restore . — reverts all unstaged changes
    cache.mark_phase_done(skill_id)  # don't retry rejected skill
    continue

build_ok, _ = maven_test(repo_path)
if not build_ok:
    git_restore(repo_path)           # revert if build breaks after approve
```

### `main.py` — fixed pipeline updated

Fixed pipeline iterates `phases/configs/*.yml` instead of `phases/**/*.md`, calling the same `run_skill + review_diff + maven_test` flow.

---

## Error Handling

| Scenario | Action |
|---|---|
| OpenRewrite Maven download fails (first run) | Log WARN, skip skill, mark cache done |
| GJF binary not found | Log ERR, skip `format` skill |
| LLM reviewer timeout (>60s) | Auto-APPROVE, log WARN |
| LLM returns unparseable response | Auto-APPROVE (fail-safe) |
| `maven_test()` fails after APPROVE | `git checkout` to revert |
| Empty diff (tool found nothing to change) | SKIP, mark cache done, no LLM call |

---

## Execution Order (recommended)

Skills run in this order for best results:

1. `clean-imports` — remove noise before other tools run
2. `format` — establish baseline formatting
3. `final-keywords` — structural, safe
4. `naming-conventions` — rename identifiers
5. `dead-code` — remove unused after renames
6. `simplify-code` — simplify expressions
7. `modernize-syntax` — Java 17+ patterns
8. `static-analysis` — full suite last (catches remaining issues)

---

## Testing

New unit tests required:

- `tests/java/test_community_runner.py` — mock subprocess calls, verify diff extraction
- `tests/java/test_llm_reviewer.py` — mock `call_model`, verify APPROVE/REJECT parsing, timeout fallback
- `tests/agent/test_skill_catalog.py` — update to verify .yml loading (existing test updated)

---

## Out of Scope

- SOLID design, guard clause, decompose conditional — no community tool equivalent; removed from catalog
- Cross-file refactoring — OpenRewrite handles within-file only for safety
- Test file modification — OpenRewrite scoped to `src/main/java/` only
