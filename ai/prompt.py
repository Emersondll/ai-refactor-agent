"""
prompt.py — ai/prompt.py

SOUL: agent identity and principles loaded from soul.md at the project root.
BASE_CONSTRAINTS: technical rules and mandatory output format.

build_prompt(): composes SOUL + BASE_CONSTRAINTS + phase delta + dep_context.
"""

import os
import re


def _load_soul() -> str:
    soul_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "soul.md")
    try:
        with open(soul_path, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


_SOUL = _load_soul()


BASE_CONSTRAINTS = """\
### TECHNICAL CONSTRAINTS (MANDATORY)
PRESERVE the package declaration exactly as-is.
PRESERVE all existing import statements.
ADD import statements for any NEW type you introduce in the code.
  Check the dependency section below for '// SUGGESTED IMPORT' hints.
PRESERVE method signatures (name, parameters, return type).
PRESERVE class-level annotations.
DO NOT create new classes — work within the existing file only.
DO NOT introduce external dependencies not already in the project.
DO NOT modify Spring Boot main class structure.
DO NOT change public API or method signatures.
DO NOT modify existing test code.

### OUTPUT FORMAT (MANDATORY)
Return ONLY the complete Java source file.
Return exactly ONE java code block (triple-backtick java).
NO explanations, NO markdown outside the code block.
NO ANSI or invisible characters.\
"""

# P1: test-specific constraints — do not mix with refactoring rules.
# "PRESERVE all existing import statements" and "DO NOT modify existing test code" are semantically
# opposite to the goal of test generation (creating a brand new file from scratch).
BASE_CONSTRAINTS_TEST = """\
### TEST GENERATION CONSTRAINTS (MANDATORY)
You are writing a NEW Java test class from scratch — not editing an existing file.
DO NOT use @SpringBootTest, @WebMvcTest, @AutoConfigureMockMvc, or any Spring context loading.
DO NOT call private methods or access private fields of the class under test.
DO NOT create new production classes — only write the test class.
Include import statements for every type you use in the test.

### OUTPUT FORMAT (MANDATORY)
Return ONLY the complete Java test file.
Return exactly ONE java code block (triple-backtick java).
NO explanations, NO markdown outside the code block.
NO ANSI or invisible characters.\
"""


def _extract_enum_constraints(dep_context: str) -> str:
    """Parse dep_context for enum definitions and return explicit allowed values per enum."""
    if not dep_context:
        return ""

    constraints = []
    enum_pattern = re.compile(r'(?:public\s+)?enum\s+(\w+)\s*\{([^}]*)\}', re.DOTALL)
    for match in enum_pattern.finditer(dep_context):
        enum_name = match.group(1)
        enum_body = match.group(2)
        constants = []
        for line in enum_body.splitlines():
            stripped = line.strip()
            const_match = re.match(r'^([A-Z][A-Z0-9_]+)(?:\s*\(.*?\))?\s*[,;]?\s*(?://.*)?$', stripped)
            if const_match:
                constants.append(const_match.group(1))
        if constants:
            constraints.append(f"  {enum_name}: {', '.join(constants)}")

    if not constraints:
        return ""
    return (
        "ALLOWED ENUM VALUES — use ONLY these values. "
        "Any other value will cause a compilation error:\n" + "\n".join(constraints)
    )


_FALLBACK_TEST_RULES = """\
TECHNICAL GUIDELINES:
1. PACKAGE: Copy the package declaration verbatim from the source class.
2. IMPORTS: import org.junit.jupiter.api.Test; import org.junit.jupiter.api.extension.ExtendWith;
   import static org.junit.jupiter.api.Assertions.*; import org.mockito.Mock;
   import org.mockito.InjectMocks; import org.mockito.junit.jupiter.MockitoExtension;
3. MOCKS: @ExtendWith(MockitoExtension.class) on the class; @InjectMocks on the class under test; @Mock on each dependency.
4. INTEGRITY: Use ONLY methods and constructors declared in the source class.
5. COVERAGE: happy path, edge cases, exception scenarios.
6. JAVA RECORDS: ALWAYS use the canonical constructor with ALL declared fields — no empty constructor.
7. CONTROLLERS: NEVER @SpringBootTest/@WebMvcTest — use @ExtendWith(MockitoExtension.class) + @InjectMocks.
8. FIDELITY: Test only what the code currently does.\
"""


def _build_task(mode: str, file_name: str, dep_context: str = "") -> str:
    if mode == "test":
        # P2: test generation rules loaded from skill — not hardcoded.
        # Allows adjusting LLM behavior by editing SKILL.md without touching Python.
        from core.utils import load_skill as _ls
        _test_rules = _ls("java-tdd-unit-test", section="Test Generation Rules") or _FALLBACK_TEST_RULES

        source_name = file_name.replace("Test.java", ".java") if file_name.endswith("Test.java") else file_name
        enum_constraints = _extract_enum_constraints(dep_context)
        if enum_constraints:
            enum_rule = (
                "ENUMS — CRITICAL RULE: Use ONLY the enum values listed below. "
                "NEVER invent, guess, or use values not listed here — it will cause a compilation error.\n"
                f"{enum_constraints}\n"
            )
        else:
            enum_rule = (
                "ENUMS — CRITICAL RULE: Use ONLY enum values that appear explicitly "
                "in the DEPENDENCY CONTEXT. NEVER invent or assume enum values.\n"
            )
        return (
            f"Write the test class '{file_name}' (JUnit 5 + Mockito) to test '{source_name}'.\n"
            f"The generated Java class name MUST be exactly '{file_name.replace('.java', '')}'.\n\n"
            f"{_test_rules}\n\n"
            f"{enum_rule}"
        )
    from core.utils import load_skill as _ls
    _refactor_base = _ls("java-refactor-context", section="LLM INSTRUCTIONS")
    if _refactor_base:
        return _refactor_base + f"\nFile: {file_name}"
    return (
        f"Refactor {file_name} applying the rules below.\n"
        "Preserve existing behavior. Apply only the rules relevant to this file."
    )


def build_prompt(code: str, phase_delta: str, mode: str, file_name: str,
                 dep_context: str = "") -> str:
    parts = []
    if _SOUL:
        parts.append(_SOUL)
    # P1: BASE_CONSTRAINTS is for refactoring (PRESERVE imports, DO NOT modify tests).
    # For test generation we use BASE_CONSTRAINTS_TEST — semantically correct for creation.
    constraints = BASE_CONSTRAINTS_TEST if mode == "test" else BASE_CONSTRAINTS
    parts += [
        constraints,
        f"\n### PHASE RULES\n{phase_delta.strip()}",
        f"\n### TASK\n{_build_task(mode, file_name, dep_context)}",
    ]
    if dep_context and dep_context.strip():
        parts.append(f"\n### DEPENDENCY CONTEXT\n{dep_context.strip()}")

    from ai.context7_client import get_phase_docs
    live_docs = get_phase_docs(phase_delta)
    if live_docs:
        parts.append(f"\n### LIBRARY DOCUMENTATION (live)\n{live_docs}")

    parts.append(f"\n### SOURCE FILE TO PROCESS\n```java\n{code}\n```")
    return "\n".join(parts)
