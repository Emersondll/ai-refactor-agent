# Community Tools Refactoring Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace LLM-as-author with deterministic community tools (OpenRewrite + Google Java Format), with the LLM acting only as diff reviewer (APPROVE/REJECT), never writing Java code.

**Architecture:** Community tools execute changes deterministically on the whole repo. The resulting `git diff` is sent to a local LLM which responds APPROVE or REJECT. APPROVE triggers `maven_test()`; any failure reverts via `git restore .`. Both the agent loop and fixed pipeline use this same flow.

**Tech Stack:** Python 3.11+, PyYAML 6.0.1, OpenRewrite via Maven plugin, Google Java Format CLI, Ollama (qwen2.5-coder:14b), `concurrent.futures` for timeout.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `phases/configs/01_clean-imports.yml` | Skill config for clean-imports |
| Create | `phases/configs/02_format.yml` | Skill config for google-java-format |
| Create | `phases/configs/03_final-keywords.yml` | Skill config for final-keywords |
| Create | `phases/configs/04_naming-conventions.yml` | Skill config for naming-conventions |
| Create | `phases/configs/05_dead-code.yml` | Skill config for dead-code |
| Create | `phases/configs/06_simplify-code.yml` | Skill config for simplify-code |
| Create | `phases/configs/07_modernize-syntax.yml` | Skill config for modernize-syntax |
| Create | `phases/configs/08_static-analysis.yml` | Skill config for static-analysis |
| Create | `java/community_runner.py` | Runs OpenRewrite/GJF, returns (changed, diff) |
| Create | `java/llm_reviewer.py` | Sends diff+criteria to LLM, returns APPROVE/REJECT/SKIP |
| Create | `tests/java/test_community_runner.py` | Tests for community_runner |
| Create | `tests/java/test_llm_reviewer.py` | Tests for llm_reviewer |
| Modify | `config.py` | Add GJF_PATH env var |
| Modify | `agent/skill_catalog.py` | Replace 24-skill .md registry with 8-skill .yml registry |
| Modify | `tests/agent/test_skill_catalog.py` | Update to verify .yml loading |
| Modify | `agent/loop.py` | Replace refactor_file() dispatch with run_skill() + review_diff() |
| Modify | `main.py` | Fixed pipeline iterates phases/configs/*.yml |
| Delete | `phases/doc/`, `phases/struct/`, `phases/solid/`, `phases/clean/`, `phases/claude/`, `phases/community/` | All replaced by .yml configs |

---

## Task 1: Add GJF_PATH to config.py

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Add GJF_PATH to config.py**

Open `config.py` and add after the `OLLAMA_BASE_URL` line:

```python
# ---------------------------------------------------------------------------
# Community Tools
# ---------------------------------------------------------------------------
GJF_PATH = os.getenv("GJF_PATH", "google-java-format")
```

- [ ] **Step 2: Verify config loads cleanly**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent" && python3 -c "from config import GJF_PATH; print('GJF_PATH:', GJF_PATH)"
```

Expected output:
```
GJF_PATH: google-java-format
```

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "feat: add GJF_PATH config var for Google Java Format binary"
```

---

## Task 2: Create 8 Skill Config YAML Files

**Files:**
- Create: `phases/configs/01_clean-imports.yml` through `08_static-analysis.yml`

- [ ] **Step 1: Create the configs directory**

```bash
mkdir -p "/home/emerson/Área de trabalho/ai-refactor-agent/phases/configs"
```

- [ ] **Step 2: Create `phases/configs/01_clean-imports.yml`**

```yaml
skill: clean-imports
description: Remove imports não utilizados e ordena imports alfabeticamente
tool: openrewrite
artifact_coordinates: []
recipes:
  - org.openrewrite.java.RemoveUnusedImports
  - org.openrewrite.java.OrderImports
review_criteria: |
  O diff deve APENAS remover linhas de import não utilizadas e reordenar imports.
  REJEITE se: qualquer linha de código Java além de imports foi alterada,
  ou se imports necessários foram removidos.
```

- [ ] **Step 3: Create `phases/configs/02_format.yml`**

```yaml
skill: format
description: Aplica Google Java Format para formatação consistente
tool: google-java-format
review_criteria: |
  O diff deve APENAS ajustar formatação (indentação, espaços, quebras de linha).
  REJEITE se: qualquer lógica, estrutura ou conteúdo semântico foi alterado.
```

- [ ] **Step 4: Create `phases/configs/03_final-keywords.yml`**

```yaml
skill: final-keywords
description: Adiciona final a variáveis locais e parâmetros não reatribuídos
tool: openrewrite
artifact_coordinates:
  - org.openrewrite.recipe:rewrite-static-analysis:RELEASE
recipes:
  - org.openrewrite.staticanalysis.FinalizeLocalVariables
  - org.openrewrite.staticanalysis.FinalizeMethodArguments
review_criteria: |
  O diff deve APENAS adicionar 'final' a variáveis locais e parâmetros de método
  onde o valor nunca é reatribuído após a declaração.
  REJEITE se: lógica alterada, métodos adicionados ou removidos,
  ou qualquer mudança além da inserção da palavra-chave 'final'.
```

- [ ] **Step 5: Create `phases/configs/04_naming-conventions.yml`**

```yaml
skill: naming-conventions
description: Renomeia identificadores para seguir convenções Java (camelCase/PascalCase)
tool: openrewrite
artifact_coordinates:
  - org.openrewrite.recipe:rewrite-static-analysis:RELEASE
recipes:
  - org.openrewrite.staticanalysis.MethodNameCasing
  - org.openrewrite.staticanalysis.LocalVariableNameCasing
review_criteria: |
  O diff deve APENAS renomear métodos ou variáveis que violam convenções Java.
  Nomes de campos e tipos não devem ser alterados por esta skill.
  REJEITE se: lógica alterada, ou qualquer rename que possa quebrar API pública.
```

- [ ] **Step 6: Create `phases/configs/05_dead-code.yml`**

```yaml
skill: dead-code
description: Remove variáveis locais não utilizadas e imports duplicados
tool: openrewrite
artifact_coordinates:
  - org.openrewrite.recipe:rewrite-static-analysis:RELEASE
recipes:
  - org.openrewrite.staticanalysis.RemoveUnusedLocalVariables
  - org.openrewrite.java.RemoveUnusedImports
review_criteria: |
  O diff deve APENAS remover variáveis locais declaradas mas nunca lidas,
  e imports redundantes.
  REJEITE se: campos de instância removidos, métodos removidos,
  ou qualquer lógica de fluxo alterada.
```

- [ ] **Step 7: Create `phases/configs/06_simplify-code.yml`**

```yaml
skill: simplify-code
description: Simplifica expressões booleanas e remove parênteses desnecessários
tool: openrewrite
artifact_coordinates:
  - org.openrewrite.recipe:rewrite-static-analysis:RELEASE
recipes:
  - org.openrewrite.staticanalysis.SimplifyBooleanExpression
  - org.openrewrite.staticanalysis.SimplifyBooleanReturn
  - org.openrewrite.staticanalysis.UnnecessaryParentheses
review_criteria: |
  O diff deve APENAS simplificar expressões booleanas redundantes (ex: x == true → x),
  simplificar retornos booleanos (ex: if (x) return true; else return false; → return x;)
  e remover parênteses supérfluos.
  REJEITE se: lógica ou resultado de qualquer expressão for alterado.
```

- [ ] **Step 8: Create `phases/configs/07_modernize-syntax.yml`**

```yaml
skill: modernize-syntax
description: Moderniza sintaxe para padrões Java 17+ (diamond operator, String.isEmpty, etc.)
tool: openrewrite
artifact_coordinates:
  - org.openrewrite.recipe:rewrite-static-analysis:RELEASE
recipes:
  - org.openrewrite.staticanalysis.UseDiamondOperator
  - org.openrewrite.staticanalysis.UseStringIsEmpty
  - org.openrewrite.staticanalysis.NoDoubleBraceInitialization
review_criteria: |
  O diff deve APENAS substituir sintaxe verbosa por equivalentes modernos:
  - new ArrayList<String>() → new ArrayList<>()
  - str.length() == 0 → str.isEmpty()
  - Remover double brace initialization
  REJEITE se: qualquer comportamento em runtime puder ser alterado.
```

- [ ] **Step 9: Create `phases/configs/08_static-analysis.yml`**

```yaml
skill: static-analysis
description: Suite completa de análise estática OpenRewrite (CommonStaticAnalysis)
tool: openrewrite
artifact_coordinates:
  - org.openrewrite.recipe:rewrite-static-analysis:RELEASE
recipes:
  - org.openrewrite.staticanalysis.CommonStaticAnalysis
review_criteria: |
  O diff deve apenas aplicar correções de análise estática conhecidas e seguras.
  REJEITE se: lógica de negócio alterada, métodos removidos, ou mudanças em
  anotações Spring/JPA/Hibernate.
```

- [ ] **Step 10: Verify all 8 yml files are valid YAML**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent" && python3 -c "
import yaml, glob
files = sorted(glob.glob('phases/configs/*.yml'))
for f in files:
    with open(f) as fh:
        cfg = yaml.safe_load(fh)
    print(f, '->', cfg['skill'], '/', cfg['tool'])
print(f'Total: {len(files)} configs')
"
```

Expected output (8 lines + total):
```
phases/configs/01_clean-imports.yml -> clean-imports / openrewrite
phases/configs/02_format.yml -> format / google-java-format
phases/configs/03_final-keywords.yml -> final-keywords / openrewrite
phases/configs/04_naming-conventions.yml -> naming-conventions / openrewrite
phases/configs/05_dead-code.yml -> dead-code / openrewrite
phases/configs/06_simplify-code.yml -> simplify-code / openrewrite
phases/configs/07_modernize-syntax.yml -> modernize-syntax / openrewrite
phases/configs/08_static-analysis.yml -> static-analysis / openrewrite
Total: 8 configs
```

- [ ] **Step 11: Commit**

```bash
git add phases/configs/
git commit -m "feat: add 8 deterministic skill configs (OpenRewrite + GJF)"
```

---

## Task 3: Create `java/community_runner.py`

**Files:**
- Create: `java/community_runner.py`
- Create: `tests/java/test_community_runner.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/java/test_community_runner.py`:

```python
import pytest
from unittest.mock import patch, call


def test_run_skill_openrewrite_returns_changed_true_when_diff_nonempty():
    config = {
        "tool": "openrewrite",
        "artifact_coordinates": ["org.openrewrite.recipe:rewrite-static-analysis:RELEASE"],
        "recipes": ["org.openrewrite.staticanalysis.FinalizeLocalVariables"],
    }
    diff_output = "diff --git a/Foo.java b/Foo.java\n+final int x = 1;"
    with patch("java.community_runner.run_cmd") as mock_run:
        mock_run.side_effect = [
            (0, "", ""),           # _run_openrewrite
            (0, diff_output, ""),  # _get_diff
        ]
        from java.community_runner import run_skill
        changed, diff = run_skill(config, "/repo")
    assert changed is True
    assert "final int x" in diff


def test_run_skill_openrewrite_returns_changed_false_when_diff_empty():
    config = {
        "tool": "openrewrite",
        "artifact_coordinates": [],
        "recipes": ["org.openrewrite.java.RemoveUnusedImports"],
    }
    with patch("java.community_runner.run_cmd") as mock_run:
        mock_run.side_effect = [
            (0, "", ""),  # _run_openrewrite
            (0, "", ""),  # _get_diff (empty diff)
        ]
        from java.community_runner import run_skill
        changed, diff = run_skill(config, "/repo")
    assert changed is False
    assert diff == ""


def test_run_skill_gjf_returns_changed_true_when_diff_nonempty(tmp_path):
    config = {"tool": "google-java-format"}
    java_file = tmp_path / "src" / "main" / "java" / "Foo.java"
    java_file.parent.mkdir(parents=True)
    java_file.write_text("class Foo {}")

    diff_output = "diff --git a/Foo.java b/Foo.java\n-class Foo{}\n+class Foo {}"
    with patch("java.community_runner.run_cmd") as mock_run:
        mock_run.side_effect = [
            (0, "", ""),           # _run_google_java_format
            (0, diff_output, ""),  # _get_diff
        ]
        from java.community_runner import run_skill
        changed, diff = run_skill(config, str(tmp_path))
    assert changed is True


def test_run_skill_unknown_tool_returns_changed_false():
    config = {"tool": "unknown-tool"}
    from java.community_runner import run_skill
    changed, diff = run_skill(config, "/repo")
    assert changed is False
    assert diff == ""


def test_run_openrewrite_includes_artifact_coords_in_cmd():
    with patch("java.community_runner.run_cmd") as mock_run:
        mock_run.return_value = (0, "", "")
        from java.community_runner import _run_openrewrite
        _run_openrewrite(
            "/repo",
            ["org.openrewrite.recipe:rewrite-static-analysis:RELEASE"],
            ["org.openrewrite.staticanalysis.FinalizeLocalVariables"],
        )
    cmd_used = mock_run.call_args[0][0]
    assert "rewrite.recipeArtifactCoordinates" in cmd_used
    assert "rewrite-static-analysis" in cmd_used
    assert "FinalizeLocalVariables" in cmd_used


def test_run_openrewrite_omits_artifact_coords_when_empty():
    with patch("java.community_runner.run_cmd") as mock_run:
        mock_run.return_value = (0, "", "")
        from java.community_runner import _run_openrewrite
        _run_openrewrite("/repo", [], ["org.openrewrite.java.RemoveUnusedImports"])
    cmd_used = mock_run.call_args[0][0]
    assert "recipeArtifactCoordinates" not in cmd_used
    assert "RemoveUnusedImports" in cmd_used


def test_get_diff_returns_stdout_on_success():
    with patch("java.community_runner.run_cmd") as mock_run:
        mock_run.return_value = (0, "some diff output", "")
        from java.community_runner import _get_diff
        result = _get_diff("/repo")
    assert result == "some diff output"


def test_get_diff_returns_empty_string_on_failure():
    with patch("java.community_runner.run_cmd") as mock_run:
        mock_run.return_value = (1, "", "error")
        from java.community_runner import _get_diff
        result = _get_diff("/repo")
    assert result == ""
```

- [ ] **Step 2: Run tests to confirm they all fail**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent" && python3 -m pytest tests/java/test_community_runner.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'java.community_runner'`

- [ ] **Step 3: Create `java/community_runner.py`**

```python
import os
from core.logger import log
from core.utils import run_cmd
from java.compiler import ENV_WRAPPER
from config import GJF_PATH


def run_skill(skill_config: dict, repo_path: str) -> tuple[bool, str]:
    tool = skill_config.get("tool", "")
    if tool == "openrewrite":
        _run_openrewrite(
            repo_path,
            skill_config.get("artifact_coordinates", []),
            skill_config.get("recipes", []),
        )
    elif tool == "google-java-format":
        _run_google_java_format(repo_path)
    else:
        log(f"[CommunityRunner] Unknown tool: {tool}", "WARN")
        return False, ""
    diff = _get_diff(repo_path)
    return bool(diff.strip()), diff


def _run_openrewrite(repo_path: str, artifact_coordinates: list, recipes: list) -> None:
    active = ",".join(recipes)
    mvn_cmd = (
        f"mvn -U org.openrewrite.maven:rewrite-maven-plugin:run"
        f" -Drewrite.activeRecipes={active}"
    )
    if artifact_coordinates:
        coords = ",".join(artifact_coordinates)
        mvn_cmd += f" -Drewrite.recipeArtifactCoordinates={coords}"
    full_cmd = ENV_WRAPPER.format(mvn_cmd)
    code, out, err = run_cmd(full_cmd, cwd=repo_path)
    if code != 0:
        log(f"[CommunityRunner] OpenRewrite exited {code}: {err[:200]}", "WARN")


def _run_google_java_format(repo_path: str) -> None:
    java_dir = os.path.join(repo_path, "src", "main", "java")
    java_files = [
        os.path.join(root, f)
        for root, _, files in os.walk(java_dir)
        for f in files
        if f.endswith(".java")
    ]
    if not java_files:
        log("[CommunityRunner] No .java files found for GJF", "WARN")
        return
    files_arg = " ".join(f'"{p}"' for p in java_files)
    code, out, err = run_cmd(f"{GJF_PATH} --replace {files_arg}", cwd=repo_path)
    if code != 0:
        log(f"[CommunityRunner] GJF exited {code}: {err[:200]}", "WARN")


def _get_diff(repo_path: str) -> str:
    code, out, _ = run_cmd("git diff --unified=5", cwd=repo_path)
    return out if code == 0 else ""
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent" && python3 -m pytest tests/java/test_community_runner.py -v
```

Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add java/community_runner.py tests/java/test_community_runner.py
git commit -m "feat: add community_runner — runs OpenRewrite/GJF, returns (changed, diff)"
```

---

## Task 4: Create `java/llm_reviewer.py`

**Files:**
- Create: `java/llm_reviewer.py`
- Create: `tests/java/test_llm_reviewer.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/java/test_llm_reviewer.py`:

```python
import pytest
from unittest.mock import patch


def test_review_diff_skip_when_diff_is_empty():
    from java.llm_reviewer import review_diff
    result = review_diff("", "some criteria", "model-name")
    assert result == "SKIP"


def test_review_diff_skip_when_diff_is_whitespace_only():
    from java.llm_reviewer import review_diff
    result = review_diff("   \n  ", "some criteria", "model-name")
    assert result == "SKIP"


def test_review_diff_returns_approve():
    with patch("java.llm_reviewer.call_model") as mock:
        mock.return_value = ("APPROVE: diff only adds final keywords", False)
        from java.llm_reviewer import review_diff
        result = review_diff("diff content here", "criteria text", "model-name")
    assert result == "APPROVE"


def test_review_diff_returns_reject():
    with patch("java.llm_reviewer.call_model") as mock:
        mock.return_value = ("REJECT: logic was changed", False)
        from java.llm_reviewer import review_diff
        result = review_diff("diff content here", "criteria text", "model-name")
    assert result == "REJECT"


def test_review_diff_approves_on_unparseable_response():
    with patch("java.llm_reviewer.call_model") as mock:
        mock.return_value = ("I think this looks fine but I cannot decide", False)
        from java.llm_reviewer import review_diff
        result = review_diff("diff content here", "criteria text", "model-name")
    assert result == "APPROVE"


def test_review_diff_approves_when_model_returns_none():
    with patch("java.llm_reviewer.call_model") as mock:
        mock.return_value = (None, False)
        from java.llm_reviewer import review_diff
        result = review_diff("diff content here", "criteria text", "model-name")
    assert result == "APPROVE"


def test_review_diff_case_insensitive_approve():
    with patch("java.llm_reviewer.call_model") as mock:
        mock.return_value = ("approve: looks good", False)
        from java.llm_reviewer import review_diff
        result = review_diff("diff", "criteria", "model")
    assert result == "APPROVE"


def test_build_prompt_includes_criteria_and_diff():
    from java.llm_reviewer import _build_prompt
    prompt = _build_prompt("MY_DIFF_CONTENT", "MY_CRITERIA")
    assert "MY_DIFF_CONTENT" in prompt
    assert "MY_CRITERIA" in prompt
    assert "APPROVE" in prompt
    assert "REJECT" in prompt
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent" && python3 -m pytest tests/java/test_llm_reviewer.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'java.llm_reviewer'`

- [ ] **Step 3: Create `java/llm_reviewer.py`**

```python
import concurrent.futures
from typing import Literal
from core.logger import log
from ai.model import call_model

_REVIEWER_TIMEOUT_S = 60


def review_diff(diff: str, criteria: str, model: str) -> Literal["APPROVE", "REJECT", "SKIP"]:
    if not diff.strip():
        return "SKIP"
    prompt = _build_prompt(diff, criteria)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(call_model, model, prompt, 0.1)
        try:
            response, _ = future.result(timeout=_REVIEWER_TIMEOUT_S)
        except concurrent.futures.TimeoutError:
            log("[Reviewer] LLM timeout after 60s — auto-APPROVE", "WARN")
            return "APPROVE"
    if not response:
        return "APPROVE"
    first_word = response.strip().split(":")[0].strip().upper()
    if first_word in ("APPROVE", "REJECT"):
        return first_word
    log(f"[Reviewer] Unparseable response '{response[:60]}' — auto-APPROVE", "WARN")
    return "APPROVE"


def _build_prompt(diff: str, criteria: str) -> str:
    return (
        "Você é um revisor de código Java. Analise o diff abaixo.\n\n"
        f"CRITÉRIOS DE APROVAÇÃO:\n{criteria}\n\n"
        f"DIFF:\n{diff}\n\n"
        "Responda APENAS com uma das opções:\n"
        "APPROVE: <motivo em 1 linha>\n"
        "REJECT: <motivo em 1 linha>"
    )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent" && python3 -m pytest tests/java/test_llm_reviewer.py -v
```

Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add java/llm_reviewer.py tests/java/test_llm_reviewer.py
git commit -m "feat: add llm_reviewer — reviews git diff, returns APPROVE/REJECT/SKIP"
```

---

## Task 5: Update `agent/skill_catalog.py`

**Files:**
- Modify: `agent/skill_catalog.py`
- Modify: `tests/agent/test_skill_catalog.py`

- [ ] **Step 1: Write updated failing tests**

Replace the contents of `tests/agent/test_skill_catalog.py`:

```python
import pytest
import yaml


def test_load_skill_config_returns_dict_for_known_skill(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    configs_dir = tmp_path / "phases" / "configs"
    configs_dir.mkdir(parents=True)
    cfg = {
        "skill": "final-keywords",
        "tool": "openrewrite",
        "artifact_coordinates": ["org.openrewrite.recipe:rewrite-static-analysis:RELEASE"],
        "recipes": ["org.openrewrite.staticanalysis.FinalizeLocalVariables"],
        "review_criteria": "Only add final.",
    }
    (configs_dir / "03_final-keywords.yml").write_text(yaml.dump(cfg))

    import importlib
    import agent.skill_catalog as sc
    importlib.reload(sc)
    result = sc.load_skill_config("final-keywords")
    assert result is not None
    assert result["tool"] == "openrewrite"
    assert result["skill"] == "final-keywords"


def test_load_skill_config_returns_none_for_unknown_skill():
    from agent.skill_catalog import load_skill_config
    assert load_skill_config("nonexistent-skill") is None


def test_is_reactive_true_for_fix_build():
    from agent.skill_catalog import is_reactive
    assert is_reactive("fix-build") is True


def test_is_reactive_false_for_phase_skill():
    from agent.skill_catalog import is_reactive
    assert is_reactive("final-keywords") is False


def test_is_terminal_true_for_done():
    from agent.skill_catalog import is_terminal
    assert is_terminal("done") is True


def test_is_terminal_false_for_others():
    from agent.skill_catalog import is_terminal
    assert is_terminal("final-keywords") is False
    assert is_terminal("fix-build") is False


def test_all_phase_skill_ids_returns_8_skills():
    from agent.skill_catalog import all_phase_skill_ids
    ids = all_phase_skill_ids()
    assert "clean-imports" in ids
    assert "final-keywords" in ids
    assert "static-analysis" in ids
    assert len(ids) == 8


def test_catalog_for_prompt_contains_all_skills():
    from agent.skill_catalog import catalog_for_prompt, SKILL_DESCRIPTIONS
    prompt = catalog_for_prompt()
    for skill_id in SKILL_DESCRIPTIONS:
        assert skill_id in prompt
```

- [ ] **Step 2: Run tests to confirm they fail on new assertions**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent" && python3 -m pytest tests/agent/test_skill_catalog.py -v 2>&1 | tail -20
```

Expected: Several tests FAIL (e.g., `load_skill_config` not found, `len(ids) == 8` fails).

- [ ] **Step 3: Replace `agent/skill_catalog.py` with the new implementation**

```python
import os
import yaml

_PHASE_SKILLS: dict[str, str] = {
    "clean-imports":      "phases/configs/01_clean-imports.yml",
    "format":             "phases/configs/02_format.yml",
    "final-keywords":     "phases/configs/03_final-keywords.yml",
    "naming-conventions": "phases/configs/04_naming-conventions.yml",
    "dead-code":          "phases/configs/05_dead-code.yml",
    "simplify-code":      "phases/configs/06_simplify-code.yml",
    "modernize-syntax":   "phases/configs/07_modernize-syntax.yml",
    "static-analysis":    "phases/configs/08_static-analysis.yml",
}

_REACTIVE_SKILLS: set[str] = {"fix-build", "skip-file", "analyze-state"}

SKILL_DESCRIPTIONS: dict[str, str] = {
    "clean-imports":      "Remove unused imports and sort remaining imports alphabetically",
    "format":             "Apply Google Java Format for consistent whitespace and indentation",
    "final-keywords":     "Add final to local variables and method parameters never reassigned",
    "naming-conventions": "Rename methods and local variables to Java camelCase convention",
    "dead-code":          "Remove unused local variables and redundant imports",
    "simplify-code":      "Simplify boolean expressions, returns, and unnecessary parentheses",
    "modernize-syntax":   "Modernize to Java 17+ idioms: diamond operator, isEmpty, no double-brace",
    "static-analysis":    "Run full OpenRewrite CommonStaticAnalysis suite",
    "fix-build":          "REACTIVE: Attempt to repair current build failure (only when red)",
    "skip-file":          "REACTIVE: Mark file as unprocessable this run",
    "done":               "TERMINAL: No more improvements available — stop the loop",
}


def load_skill_config(skill_id: str) -> dict | None:
    yml_path = _PHASE_SKILLS.get(skill_id)
    if not yml_path:
        return None
    if not os.path.exists(yml_path):
        return None
    with open(yml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


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

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent" && python3 -m pytest tests/agent/test_skill_catalog.py -v
```

Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/skill_catalog.py tests/agent/test_skill_catalog.py
git commit -m "refactor: skill_catalog now loads .yml configs — 24 LLM skills → 8 tool skills"
```

---

## Task 6: Update `agent/loop.py`

**Files:**
- Modify: `agent/loop.py`

- [ ] **Step 1: Replace the contents of `agent/loop.py`**

Replace the entire file with:

```python
import os
from core.logger import log
from core.utils import run_cmd
from core.execution_logger import ExecutionLogger
from core.reporter import PhaseReporter
from java.compiler import maven_test
from java.community_runner import run_skill
from java.llm_reviewer import review_diff
from agent.observation import build_observation
from agent.planner import call_planner
from agent.skill_catalog import load_skill_config, is_reactive, is_terminal
from config import AGENT_MAX_CYCLES, MODEL_SOLID


def run_agent_loop(repo_path: str, reporter: PhaseReporter,
                   exec_logger: ExecutionLogger, cache, semantic_mem) -> None:
    cycle = 0
    consecutive_no_progress = 0
    build_ok = True
    last_build_error: str | None = None

    log("=" * 60, "PHASE")
    log("AGENT MODE — Plan-then-Execute Loop (Community Tools)", "PHASE")
    log(f"Max cycles: {AGENT_MAX_CYCLES}", "PHASE")
    log("=" * 60, "PHASE")

    while cycle < AGENT_MAX_CYCLES:
        log(f"\n[Cycle {cycle + 1}/{AGENT_MAX_CYCLES}] Building observation...", "PHASE")
        observation = build_observation(
            repo_path, cache, cycle + 1, AGENT_MAX_CYCLES,
            build_ok=build_ok, last_build_error=last_build_error,
        )

        log(f"[Cycle {cycle + 1}] Calling planner...", "PHASE")
        plan = call_planner(observation)
        cycle += 1

        if not plan:
            log("[Agent] Empty plan — exiting", "WARN")
            break

        actions_accepted = 0
        build_broke_this_cycle = False

        for action in plan:
            skill  = action.get("skill", "")
            reason = action.get("reason", "")

            log(f"  → [{skill}] : {reason}")

            if is_terminal(skill):
                log("[Agent] Declared done — no more improvements available.", "OK")
                return

            if skill == "skip-file":
                log(f"  [Agent] skip-file: {reason}", "WARN")
                continue

            if skill == "fix-build":
                build_ok, _ = maven_test(repo_path)
                if build_ok:
                    last_build_error = None
                    actions_accepted += 1
                continue

            if skill == "analyze-state":
                continue

            skill_config = load_skill_config(skill)
            if skill_config is None:
                log(f"  [Agent] Unknown or missing skill '{skill}' — skipping", "WARN")
                continue

            changed, diff = run_skill(skill_config, repo_path)
            if not changed:
                log(f"  [Agent] [{skill}] no changes — skipping", "INFO")
                cache.mark_phase_done(skill)
                continue

            verdict = review_diff(diff, skill_config.get("review_criteria", ""), MODEL_SOLID)
            log(f"  [Agent] [{skill}] reviewer: {verdict}")

            if verdict == "REJECT":
                _git_restore(repo_path)
                cache.mark_phase_done(skill)
                log(f"  [Agent] [{skill}] reverted (REJECT)", "WARN")
                continue

            actions_accepted += 1
            build_ok, build_output = maven_test(repo_path)
            if not build_ok:
                last_build_error = _extract_errors(build_output)
                log(f"  [Agent] Build broke after [{skill}] — reverting", "WARN")
                _git_restore(repo_path)
                build_broke_this_cycle = True
                break
            else:
                last_build_error = None
                cache.mark_phase_done(skill)
                log(f"  [Agent] [{skill}] accepted and committed to build", "OK")

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


def _git_restore(repo_path: str) -> None:
    run_cmd("git restore .", cwd=repo_path)


def _extract_errors(build_output: str) -> str:
    lines = [l for l in build_output.splitlines() if "[ERROR]" in l]
    return "\n".join(lines[:10])
```

- [ ] **Step 2: Verify the module imports correctly**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent" && python3 -c "from agent.loop import run_agent_loop; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Run the agent test suite**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent" && python3 -m pytest tests/agent/ -v 2>&1 | tail -20
```

Expected: All tests in `tests/agent/` pass.

- [ ] **Step 4: Commit**

```bash
git add agent/loop.py
git commit -m "refactor: loop.py dispatches to community_runner + llm_reviewer (no LLM authoring)"
```

---

## Task 7: Update `config.py` and `main.py` (Fixed Pipeline)

**Files:**
- Modify: `main.py`

Note: `config.py` was already updated in Task 1.

- [ ] **Step 1: Update the fixed pipeline block in `main.py`**

Find the `else:` branch of `if USE_AGENT_MODE:` (lines 120–134 of current `main.py`) and replace it:

Old code to replace:
```python
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

New code:
```python
    else:
        log("Modo Pipeline fixo (USE_AGENT_MODE=false).", "PHASE")
        import glob as _glob
        import yaml as _yaml
        from java.community_runner import run_skill as _run_skill
        from java.llm_reviewer import review_diff as _review_diff
        from java.compiler import maven_test as _maven_test
        from core.utils import run_cmd as _run_cmd
        from config import MODEL_SOLID as _MODEL_SOLID

        configs_dir = os.path.join(BASE_DIR, "phases", "configs")
        config_paths = sorted(_glob.glob(os.path.join(configs_dir, "*.yml")))

        if not config_paths:
            log(f"Nenhum config .yml encontrado em {configs_dir}", "ERR")
            return

        for config_path in config_paths:
            with open(config_path, "r", encoding="utf-8") as _f:
                skill_config = _yaml.safe_load(_f)
            skill_id = skill_config.get("skill", os.path.basename(config_path))
            log(f"Iniciando Skill: {skill_id}", "PHASE")
            exec_logger.log_phase_start(skill_id, f"Community tool: {skill_id}")

            changed, diff = _run_skill(skill_config, repo_path)
            if not changed:
                log(f"  [{skill_id}] sem alterações — pulando", "OK")
                cache.mark_phase_done(skill_id)
                continue

            verdict = _review_diff(diff, skill_config.get("review_criteria", ""), _MODEL_SOLID)
            log(f"  [{skill_id}] revisor: {verdict}")

            if verdict == "REJECT":
                _run_cmd("git restore .", cwd=repo_path)
                cache.mark_phase_done(skill_id)
                log(f"  [{skill_id}] revertido (REJECT)", "WARN")
                continue

            build_ok, build_output = _maven_test(repo_path)
            if not build_ok:
                log(f"  [{skill_id}] build quebrado após APPROVE — revertendo", "WARN")
                _run_cmd("git restore .", cwd=repo_path)
            else:
                cache.mark_phase_done(skill_id)
                log(f"  [{skill_id}] aceito ✓", "OK")
```

Also update the import at the top of `main.py` — remove unused imports. Find this line:
```python
from java.refactor import refactor_file, generate_tests, get_java_files, get_failed_tracker
```

Replace with:
```python
from java.refactor import generate_tests, get_java_files, get_failed_tracker
```

And add `BASE_DIR` to the config import:
```python
from config import PHASES_DIR, REPOS_DIR, LOGS_DIR, USE_AGENT_MODE, BASE_DIR
```

- [ ] **Step 2: Verify main.py imports cleanly**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent" && python3 -c "import main; print('OK')"
```

Expected: `OK` (no import errors)

- [ ] **Step 3: Run the full test suite to check for regressions**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent" && python3 -m pytest tests/ -v 2>&1 | tail -30
```

Expected: All existing tests pass. Fix any import errors that surface.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "refactor: fixed pipeline iterates phases/configs/*.yml via community tools"
```

---

## Task 8: Cleanup — Remove Old Phase .md Files

**Files:**
- Delete: all contents of `phases/doc/`, `phases/struct/`, `phases/solid/`, `phases/clean/`, `phases/claude/`, `phases/community/`

- [ ] **Step 1: Verify nothing in the codebase still references the old .md paths**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent" && grep -r "phases/doc\|phases/struct\|phases/solid\|phases/clean\|phases/claude\|phases/community" --include="*.py" .
```

Expected: No output (zero references). If any references exist, fix them before deleting.

- [ ] **Step 2: Delete the old phase directories**

```bash
rm -rf "/home/emerson/Área de trabalho/ai-refactor-agent/phases/doc"
rm -rf "/home/emerson/Área de trabalho/ai-refactor-agent/phases/struct"
rm -rf "/home/emerson/Área de trabalho/ai-refactor-agent/phases/solid"
rm -rf "/home/emerson/Área de trabalho/ai-refactor-agent/phases/clean"
rm -rf "/home/emerson/Área de trabalho/ai-refactor-agent/phases/claude"
rm -rf "/home/emerson/Área de trabalho/ai-refactor-agent/phases/community"
```

- [ ] **Step 3: Verify only phases/configs/ remains**

```bash
ls "/home/emerson/Área de trabalho/ai-refactor-agent/phases/"
```

Expected:
```
configs
```

- [ ] **Step 4: Run the full test suite one final time**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent" && python3 -m pytest tests/ -v 2>&1 | tail -30
```

Expected: All tests pass. No failures.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: remove old phases/*.md files — replaced by phases/configs/*.yml"
```

---

## Self-Review Checklist

- [x] **Spec coverage:**
  - `community_runner.py` → Task 3 ✓
  - `llm_reviewer.py` → Task 4 ✓
  - 8 yml configs → Task 2 ✓
  - `skill_catalog.py` update → Task 5 ✓
  - `loop.py` update → Task 6 ✓
  - `main.py` fixed pipeline → Task 7 ✓
  - `config.py` GJF_PATH → Task 1 ✓
  - Old phases/ removal → Task 8 ✓
  - Tests: `test_community_runner.py`, `test_llm_reviewer.py`, `test_skill_catalog.py` ✓
  - Error handling table from spec → all handled in loop.py and community_runner.py ✓
  - `git restore .` (not `git checkout`) → Task 6 uses `_git_restore()` ✓
  - `cache.mark_phase_done(skill_id)` on REJECT → Task 6 ✓
  - Execution order (clean-imports first) → yml numeric prefixes (01-08) ✓

- [x] **No placeholders:** All steps contain complete code.

- [x] **Type consistency:** `run_skill` returns `tuple[bool, str]` in Task 3 and is consumed as such in Tasks 6 and 7. `review_diff` returns `Literal["APPROVE","REJECT","SKIP"]` consistently across Tasks 4, 6, 7.
