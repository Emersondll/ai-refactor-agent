"""
prompt.py — ai/prompt.py

SOUL: personalidade e princípios carregados de soul.md (raiz do projeto).
BASE_CONSTRAINTS: regras técnicas e formato de output obrigatório.

build_prompt(): compõe SOUL + BASE_CONSTRAINTS + phase delta + dep_context.
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


def _build_task(mode: str, file_name: str, dep_context: str = "") -> str:
    if mode == "test":
        source_name = file_name.replace("Test.java", ".java") if file_name.endswith("Test.java") else file_name
        enum_constraints = _extract_enum_constraints(dep_context)
        if enum_constraints:
            enum_rule = (
                "5. ENUMS — CRITICAL RULE: Use ONLY the enum values listed below. "
                "NEVER invent, guess, or use values not listed here — it will cause a compilation error.\n"
                f"{enum_constraints}\n"
            )
        else:
            enum_rule = (
                "5. ENUMS — CRITICAL RULE: Use ONLY enum values that appear explicitly "
                "in the DEPENDENCY CONTEXT (under '// Class: ...' sections). "
                "NEVER invent or assume enum values. If the enum is not in the context, "
                "use only the first constant declared in the source class.\n"
            )
        return (
            f"Write the test class '{file_name}' (JUnit 5 + Mockito) to test '{source_name}'.\n"
            f"The generated Java class name MUST be exactly '{file_name.replace('.java', '')}'.\n"
            "TECHNICAL GUIDELINES:\n"
            "1. PACKAGE: Use exactly the same package as the original class.\n"
            "2. IMPORTS: Explicitly import Mockito (@Mock, @InjectMocks, Mockito.when), "
            "JUnit 5 (@Test, @BeforeEach, Assertions) and ALL dependencies.\n"
            "3. MOCKS: Use @InjectMocks on the class under test and @Mock on its dependencies.\n"
            "4. INTEGRITY: Verify the original class signatures. "
            "Do NOT call methods that do not exist.\n"
            + enum_rule
            + "6. COVERAGE: Include happy path, edge cases, and error/exception scenarios.\n"
            "7. JAVA RECORDS: When instantiating ANY record in the test — both the class under test "
            "and dependencies used as arguments (e.g. request objects, DTOs) — "
            "ALWAYS use the canonical constructor with ALL declared arguments. "
            "NEVER use an empty constructor or omit fields. Check the record declaration in the "
            "DEPENDENCY CONTEXT to get the arguments in the correct order.\n"
            "8. CONTROLLERS (@RestController): "
            "NEVER use @SpringBootTest, @WebMvcTest, @AutoConfigureMockMvc or MockMvc — "
            "these start the full Spring context and cause failures. "
            "Use ONLY @ExtendWith(MockitoExtension.class). "
            "Declare the controller as '@InjectMocks MyController controller;' — Mockito will inject @Mock dependencies automatically via field injection. "
            "DO NOT call 'new MyController()' manually when @InjectMocks is present. "
            "Call controller methods directly: 'controller.someMethod(arg)'. "
            "If a method returns ResponseEntity, the HTTP status comes from the ResponseEntity (e.g. ok()=200), "
            "NOT from the class-level @ResponseStatus annotation.\n"
            "9. FIDELITY: Test only what the code currently does. Do not add behaviour that does not exist yet."
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
    parts += [
        BASE_CONSTRAINTS,
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
