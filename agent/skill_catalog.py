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
