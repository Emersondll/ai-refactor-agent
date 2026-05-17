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
    "guard-clauses":      "phases/configs/09_guard_clauses.yml",
    "method-extraction":  "phases/configs/10_method_extraction.yml",
    "solid-dip":          "phases/configs/11_solid_dip.yml",
    "controller-lean":    "phases/configs/12_controller_lean.yml",
    "flow-refactor":      "phases/configs/13_flow_refactor.yml",
    "dry-check":          "phases/configs/14_dry_check.yml",
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
    "guard-clauses":      "Replace nested if-else (depth >= 3) with early return guard clauses (LLM)",
    "method-extraction":  "Extract long methods (> 30 lines) into smaller focused private methods (LLM)",
    "solid-dip":          "Replace direct instantiation (new ConcreteX()) with constructor injection (LLM)",
    "controller-lean":    "Move business logic out of @RestController into service layer (LLM)",
    "flow-refactor":      "Refactor full endpoint flow: controller→service→repository chain (LLM)",
    "dry-check":          "Detect and extract duplicated code blocks to utility classes (LLM)",
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
