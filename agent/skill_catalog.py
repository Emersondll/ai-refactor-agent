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
