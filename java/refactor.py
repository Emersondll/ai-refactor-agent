"""
refactor.py — Localização: java/refactor.py

CORRIGIDO:
  - Ao rejeitar por validator, reencaminha o código inválido + motivo
    de volta ao call_ai para que o modelo corrija especificamente o problema.
  - Máximo de MAX_VALIDATOR_RETRIES ciclos de correção antes de desistir.
"""

import os
import re
import json
import time
from datetime import datetime

from core.logger import log
from core.live_state import update as _live
from core.utils import read_file, write_file
from core.reporter import PhaseReporter
from core.execution_logger import ExecutionLogger
from ai.model import call_ai, call_ai_with_correction
from java.validator import is_valid_java, validate_package_matches_path
from java.compiler import maven_test, maven_test_with_coverage
from java.scope_reducer import (
    is_large_file,
    extract_class_header,
    get_processable_methods,
    build_method_context,
    extract_refactored_method,
    replace_method_in_file,
)


LARGE_FILE_THRESHOLD    = 100
MAX_FILE_LINES          = 500
MAX_VALIDATOR_RETRIES   = 3    # tentativas de correção após rejeição do validator
MAX_BUILD_FAILURES      = 3    # falhas de build acumuladas antes de pular o arquivo
MAX_TEST_FILE_TIMEOUT_S = 1200  # 20 min máximo por arquivo de teste — escala com TIMEOUT_TEST(300s) × (MAX_VALIDATOR_RETRIES+1)

_REASON_NO_CHANGE = "no_change"  # sinal: modelo confirmou que não há alterações

# Common method name prefixes — short getters/setters that could be typos are recoverable.
# Only long unique method names that can't be matched anywhere are flagged irrecoverable.
_COMMON_GETTER_PREFIXES = ("get", "is", "set", "has", "find", "to", "of", "from")

# Ultra-common JavaBean / Object method names — so generic that any class might have them.
# Even if a specific class doesn't, the LLM is likely just confused, not hallucinating.
_UBIQUITOUS_METHOD_NAMES = frozenset({
    "getName", "getValue", "getType", "getId", "getKey", "getDate",
    "setName", "setValue", "setType", "setId", "setKey", "setDate",
    "isValid", "isActive", "isEnabled", "isEmpty", "toString", "hashCode",
    "equals", "compareTo", "size", "length",
})

# P2: métodos de assertion JUnit 5 — ausência = falta de static import, não método inexistente
_JUNIT_ASSERTION_METHODS = frozenset({
    "assertTrue", "assertFalse", "assertEquals", "assertNotEquals",
    "assertNull", "assertNotNull", "assertThrows", "assertDoesNotThrow",
    "assertArrayEquals", "assertIterableEquals", "assertLinesMatch",
    "assertTimeout", "assertTimeoutPreemptively", "fail",
    "assertSame", "assertNotSame", "assertAll",
})

# S1/S2: mapa de tipos JDK que LLMs frequentemente usam sem importar
_JDK_IMPORT_MAP: dict[str, str] = {
    "BigDecimal":    "import java.math.BigDecimal;",
    "BigInteger":    "import java.math.BigInteger;",
    "LocalDate":     "import java.time.LocalDate;",
    "LocalDateTime": "import java.time.LocalDateTime;",
    "LocalTime":     "import java.time.LocalTime;",
    "ZonedDateTime": "import java.time.ZonedDateTime;",
    "OffsetDateTime":"import java.time.OffsetDateTime;",
    "Instant":       "import java.time.Instant;",
    "Duration":      "import java.time.Duration;",
    "Period":        "import java.time.Period;",
    "Timestamp":     "import java.sql.Timestamp;",
    "Date":          "import java.util.Date;",
    "UUID":          "import java.util.UUID;",
    "ArrayList":     "import java.util.ArrayList;",
    "LinkedList":    "import java.util.LinkedList;",
    "HashMap":       "import java.util.HashMap;",
    "LinkedHashMap": "import java.util.LinkedHashMap;",
    "HashSet":       "import java.util.HashSet;",
    "LinkedHashSet": "import java.util.LinkedHashSet;",
    "Collections":   "import java.util.Collections;",
    "Arrays":        "import java.util.Arrays;",
    "Optional":      "import java.util.Optional;",
    "Objects":       "import java.util.Objects;",
    "Stream":        "import java.util.stream.Stream;",
    "Collectors":    "import java.util.stream.Collectors;",
    "AtomicInteger": "import java.util.concurrent.atomic.AtomicInteger;",
    "AtomicLong":    "import java.util.concurrent.atomic.AtomicLong;",
}


def build_project_imports(repo_path: str) -> dict[str, str]:
    """Scan src/main/java/ under repo_path and return {ShortName: "import full.path.ShortName;"}.

    Only PUBLIC classes/enums/interfaces/records are exported (a test
    cannot reference a package-private type from a different package).

    Name collision policy: last-seen wins. Document as known limitation.
    Returns {} if src/main/java/ doesn't exist.
    """
    main_java = os.path.join(repo_path, "src", "main", "java")
    if not os.path.isdir(main_java):
        return {}

    result: dict[str, str] = {}
    decl_re = re.compile(
        r'public\s+(?:(?:final|abstract|sealed|non-sealed|static)\s+)*'
        r'(?:class|interface|enum|record|@interface)\s+(\w+)',
        re.MULTILINE,
    )
    pkg_re = re.compile(r'^package\s+([\w.]+)\s*;', re.MULTILINE)

    for root, _, files in os.walk(main_java):
        for fname in files:
            if not fname.endswith(".java"):
                continue
            full = os.path.join(root, fname)
            try:
                with open(full, encoding="utf-8") as f:
                    src = f.read()
            except Exception:
                continue
            pkg_m = pkg_re.search(src)
            if not pkg_m:
                continue
            pkg = pkg_m.group(1)
            for m in decl_re.finditer(src):
                short = m.group(1)
                result[short] = f"import {pkg}.{short};"
    return result


def _auto_inject_missing_imports(
    test_code: str,
    prod_imports: list[str],
    project_imports: dict[str, str] | None = None,
) -> str:
    """
    S1: Após geração LLM, injeta deterministicamente imports ausentes no teste.
    Cruza nomes de classe usados no código com prod_imports (do fonte de produção),
    _JDK_IMPORT_MAP e project_imports (mapa project-wide, Opção 6).
    Não envolve LLM — é uma correção estrutural pura.
    """
    # Monta mapa nome-curto → import completo a partir dos imports de produção
    prod_map: dict[str, str] = {}
    for imp in prod_imports:
        m = re.match(r'import\s+([\w.]+);', imp)
        if m:
            short = m.group(1).split(".")[-1]
            prod_map[short] = imp

    # Coleta imports que já existem no teste gerado
    existing_imports = set(re.findall(r'^import\s+[\w.*]+;', test_code, re.MULTILINE))
    existing_short: set[str] = set()
    for imp in existing_imports:
        m = re.match(r'import\s+([\w.]+(?:\.\*)?);', imp)
        if m:
            existing_short.add(m.group(1).split(".")[-1])

    # Detecta todos os nomes CamelCase usados no corpo do teste
    used_classes = set(re.findall(r'\b([A-Z][a-zA-Z0-9]+)\b', test_code))

    to_inject: list[str] = []
    for cls in sorted(used_classes):
        if cls in existing_short:
            continue
        if cls in prod_map:
            to_inject.append(prod_map[cls])
        elif cls in _JDK_IMPORT_MAP:
            to_inject.append(_JDK_IMPORT_MAP[cls])
        elif project_imports and cls in project_imports:
            to_inject.append(project_imports[cls])

    # P2b: se o teste usa métodos de assertion JUnit sem import static, injeta deterministicamente
    _STATIC_JUNIT = "import static org.junit.jupiter.api.Assertions.*;"
    if _STATIC_JUNIT not in test_code:
        _assertion_pat = r'\b(?:' + '|'.join(_JUNIT_ASSERTION_METHODS) + r')\s*\('
        if re.search(_assertion_pat, test_code):
            to_inject.append(_STATIC_JUNIT)

    if not to_inject:
        return test_code

    # Injeta após o último import existente — ou após o package se não há imports
    # — ou no topo do arquivo se não há nem package nem imports (ex.: snippets de teste)
    last_import = None
    for m in re.finditer(r'^import\s+[\w.*]+;', test_code, re.MULTILINE):
        last_import = m
    if last_import:
        pos = last_import.end()
        return test_code[:pos] + "\n" + "\n".join(sorted(set(to_inject))) + test_code[pos:]
    pkg = re.search(r'^package\s+[\w.]+;', test_code, re.MULTILINE)
    if pkg:
        pos = pkg.end()
        return test_code[:pos] + "\n\n" + "\n".join(sorted(set(to_inject))) + test_code[pos:]
    # Fallback: nenhum package nem import — prepend ao topo
    return "\n".join(sorted(set(to_inject))) + "\n" + test_code


# ---------------------------------------------------------------------------
# Constructor-call validator — deterministic pre-Maven fix (Fix F)
# ---------------------------------------------------------------------------

_STRING_SAMPLES    = ['"sampleA"', '"sampleB"', '"sampleC"', '"sampleD"', '"sampleE"', '"sampleF"']
_BIGDECIMAL_SAMPLES = ['new BigDecimal("100.00")', 'new BigDecimal("250.50")']


def _ctor_sample_value(java_type: str) -> str | None:
    """Return a sample literal for a Java type, or None if unsupported."""
    base = re.sub(r'<[^>]+>', '', java_type.strip()).strip()
    table = {
        "String":        '"sampleA"',
        "BigDecimal":    'new BigDecimal("100.00")',
        "BigInteger":    'BigInteger.valueOf(100)',
        "Timestamp":     'Timestamp.valueOf("2023-01-15 10:00:00")',
        "long":          '1L',
        "Long":          '1L',
        "int":           '1',
        "Integer":       '1',
        "double":        '1.0',
        "Double":        '1.0',
        "boolean":       'true',
        "Boolean":       'true',
        "LocalDate":     'LocalDate.of(2023, 1, 15)',
        "LocalDateTime": 'LocalDateTime.of(2023, 1, 15, 10, 0)',
    }
    return table.get(base)


def _ctor_sample_value_at(java_type: str, position: int, used_counts: dict) -> str | None:
    """Sample value picked by arg position (0-based) for String, and by occurrence for BigDecimal."""
    t = re.sub(r'<[^>]+>', '', java_type.strip()).strip()
    if t == "String":
        # Use the absolute arg position so each arg slot gets a distinct label
        return _STRING_SAMPLES[position % len(_STRING_SAMPLES)]
    if t == "BigDecimal":
        i = used_counts.setdefault("BigDecimal", 0)
        used_counts["BigDecimal"] = i + 1
        return _BIGDECIMAL_SAMPLES[i % len(_BIGDECIMAL_SAMPLES)]
    return _ctor_sample_value(java_type)


def _parse_constructor_hints(dep_context: str) -> dict:
    """Parse // CONSTRUCTOR CALL: lines from dep_context.

    Returns {ClassName: [Type1, Type2, ...]} for each hint found.
    """
    result: dict = {}
    if not dep_context:
        return result
    for m in re.finditer(
        r'//\s*CONSTRUCTOR\s+CALL:\s*new\s+(\w+)\s*\(([^)]*)\)',
        dep_context,
    ):
        cls = m.group(1)
        params_raw = m.group(2).strip()
        if not params_raw:
            result[cls] = []
            continue
        types: list = []
        for part in params_raw.split(","):
            part = part.strip()
            if not part:
                continue
            tokens = part.split()
            if len(tokens) >= 2:
                types.append(tokens[-2])
            else:
                types.append(tokens[0])
        result[cls] = types
    return result


def _split_top_level_args(args_str: str) -> list:
    """Split a comma-separated argument list respecting balanced ( ), < >, and strings."""
    if not args_str.strip():
        return []
    args: list = []
    depth_paren = 0
    depth_angle = 0
    in_string = False
    string_char = ""
    current: list = []
    i = 0
    while i < len(args_str):
        c = args_str[i]
        if in_string:
            current.append(c)
            if c == "\\" and i + 1 < len(args_str):
                current.append(args_str[i + 1])
                i += 2
                continue
            if c == string_char:
                in_string = False
            i += 1
            continue
        if c in ('"', "'"):
            in_string = True
            string_char = c
            current.append(c)
        elif c == "(":
            depth_paren += 1
            current.append(c)
        elif c == ")":
            depth_paren -= 1
            current.append(c)
        elif c == "<":
            depth_angle += 1
            current.append(c)
        elif c == ">":
            depth_angle -= 1
            current.append(c)
        elif c == "," and depth_paren == 0 and depth_angle == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(c)
        i += 1
    if current:
        args.append("".join(current).strip())
    return [a for a in args if a]


def _fix_constructor_calls(test_code: str, dep_context: str) -> str:
    """For each `new ClassName(args)` in test_code, if the dep_context hint shows
    a different arg count, rewrite with deterministic sample values per type.

    Returns the (possibly modified) test_code. Pure Python — runs before Maven.
    Only rewrites when expected count != actual count AND all required types
    are supported by the sample-value table. Otherwise leaves the call alone.
    """
    hints = _parse_constructor_hints(dep_context)
    if not hints:
        return test_code

    out_parts: list = []
    i = 0
    while i < len(test_code):
        m = re.search(r'new\s+(\w+)\s*\(', test_code[i:])
        if not m:
            out_parts.append(test_code[i:])
            break
        # Append everything before the match
        out_parts.append(test_code[i : i + m.start()])
        class_name = m.group(1)
        # Find balanced closing paren
        start = i + m.end()  # position right after `new X(`
        depth = 1
        in_str = False
        sc = ""
        j = start
        while j < len(test_code) and depth > 0:
            c = test_code[j]
            if in_str:
                if c == "\\" and j + 1 < len(test_code):
                    j += 2
                    continue
                if c == sc:
                    in_str = False
            elif c in ('"', "'"):
                in_str = True
                sc = c
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            j += 1
        if depth != 0:
            # Unbalanced — bail on this match, emit what we found and move on
            out_parts.append(test_code[i + m.start() : start])
            i = start
            continue
        args_str = test_code[start : j - 1]
        full_call = test_code[i + m.start() : j]
        if class_name not in hints:
            out_parts.append(full_call)
        else:
            expected_types = hints[class_name]
            actual_args = _split_top_level_args(args_str)
            if len(actual_args) == len(expected_types):
                out_parts.append(full_call)  # count matches — leave alone
            else:
                used_counts: dict = {}
                sample_args: list = []
                supported = True
                for t in expected_types:
                    v = _ctor_sample_value_at(t, len(sample_args), used_counts)
                    if v is None:
                        supported = False
                        break
                    sample_args.append(v)
                if supported:
                    out_parts.append(f"new {class_name}({', '.join(sample_args)})")
                else:
                    out_parts.append(full_call)  # unsupported type — leave alone
        i = j
    return "".join(out_parts)


def _is_irrecoverable_hallucination(
    repair_hint: str,
    prod_imports: list[str],
    test_code: str = "",
    project_imports: dict[str, str] | None = None,
) -> bool:
    """Return True when the repair hint indicates a hallucination that no retry
    can fix — the LLM referenced a method or class that does not exist anywhere
    findable, and no deterministic injector (S1, S2, P2 static import) can help.

    Conservative: returns False whenever we are uncertain.
    """
    if not repair_hint:
        return False

    # Build the set of class short-names known to exist
    known_classes: set[str] = set(_JDK_IMPORT_MAP.keys())
    for imp in prod_imports or []:
        m = re.match(r'import\s+(?:static\s+)?([\w.]+)(?:\.\*)?;', imp)
        if m:
            known_classes.add(m.group(1).split(".")[-1])
    # JUnit + Mockito + Spring test classes that S1/S2 don't currently inject but
    # are clearly recoverable (the LLM typically just forgot the import).
    known_classes.update({
        "Test", "BeforeEach", "AfterEach", "BeforeAll", "AfterAll",
        "Mock", "InjectMocks", "MockitoExtension", "ExtendWith",
        "Assertions", "MockMvc", "ResponseEntity",
    })

    # CASE A: IMPORT ERROR with a hallucinated class
    # Hint looks like: "IMPORT ERROR: Class 'FooBar' not found" or "Class `FooBar` is missing its import"
    m = re.search(r"IMPORT\s+ERROR:.*?[Cc]lass\s+['`](\w+)['`]", repair_hint, re.DOTALL)
    if m:
        cls = m.group(1)
        # If the class IS findable somewhere (JDK map, prod imports, common JUnit), recoverable
        if cls in known_classes:
            return False
        # If it's a "STATIC IMPORT ERROR" (handled by P2/S2 injection), recoverable
        if "STATIC IMPORT" in repair_hint:
            return False
        # Not findable AND not a deterministic-injection case → irrecoverable
        return True

    # CASE B: METHOD ERROR with a missing method name
    # Hint: "METHOD ERROR: You called 'method <name>(...)'"
    m = re.search(r"METHOD\s+ERROR:.*?method\s+(\w+)\s*\(", repair_hint, re.DOTALL)
    if m:
        method = m.group(1)
        # Ultra-common JavaBean names are always treated as recoverable typos.
        if method in _UBIQUITOUS_METHOD_NAMES:
            return False
        # JUnit assertion methods → static import case (P2 handles)
        if "STATIC IMPORT" in repair_hint:
            return False
        # Very short method names (≤ 5 chars, e.g. "get", "set") — too ambiguous to flag.
        if len(method) <= 5:
            return False
        # Long unique-looking method name (≥ 6 chars) not in the ubiquitous set → irrecoverable
        return True

    # CASE C (Opção 9): PACKAGE ERROR + test_code scan for unknown class references.
    # Only relevant when we have test_code to inspect.
    if "PACKAGE ERROR" in repair_hint and test_code:
        # Reuse the known-classes set used by IMPORT ERROR detection above
        # (rebuild here to avoid coupling — small cost)
        _known_local: set[str] = set(_JDK_IMPORT_MAP.keys())
        for imp in prod_imports or []:
            m = re.match(r'import\s+(?:static\s+)?([\w.]+)(?:\.\*)?;', imp)
            if m:
                _known_local.add(m.group(1).split(".")[-1])
        _known_local.update({
            "Test", "BeforeEach", "AfterEach", "BeforeAll", "AfterAll",
            "Mock", "InjectMocks", "MockitoExtension", "ExtendWith",
            "Assertions", "MockMvc", "ResponseEntity", "HttpStatus",
            "MediaType", "HttpHeaders", "Mockito",
        })
        if project_imports:
            _known_local.update(project_imports.keys())

        # Find Class.MEMBER references — Class starts with uppercase, followed by .UPPER or .method
        # Skip generic-like patterns by requiring the dot to be followed by an identifier (not <)
        for cls in set(re.findall(r'\b([A-Z][A-Za-z0-9]+)\.\w', test_code)):
            if cls not in _known_local:
                return True

    # All other error categories (ASSERTION, TYPE MISMATCH, CONSTRUCTOR, RECORD, etc.) → recoverable
    return False


def _categorize_build_error(output: str, prod_imports: list | None = None) -> str:
    """Analisa o erro Maven e retorna instrução de reparo direcionada."""
    out = output.lower()

    # F: IllegalArgumentException com mensagem de formato Timestamp (java.sql.Timestamp.valueOf)
    if "illegalargument" in out and "timestamp format" in out:
        return (
            "TIMESTAMP FORMAT ERROR: java.sql.Timestamp.valueOf() received an invalid format string.\n"
            "The format MUST be exactly: \"yyyy-mm-dd hh:mm:ss\" (space between date and time, NOT 'T').\n\n"
            "FIND in your @BeforeEach or test body every occurrence of:\n"
            "  Timestamp.valueOf(\"...T...\")   ← WRONG — 'T' is ISO-8601, not SQL format\n"
            "REPLACE with:\n"
            "  Timestamp.valueOf(\"2023-01-15 10:00:00\")   ← CORRECT — space, not T\n\n"
            "ONE CHANGE ONLY — do NOT modify any other code. Do NOT change assertions, imports, or class structure.\n"
        )

    # M1: método ou campo privado chamado de fora — LLM violou encapsulamento.
    # Maven: "<member>(<types>) has private access in <FQN>"
    if "has private access" in out:
        # Extract member name (works for methods and fields)
        m = re.search(r'(\w+)\s*\([^)]*\)\s*has private access', output)
        if m:
            member = m.group(1) + "()"
        else:
            m = re.search(r'(\w+)\s+has private access', output)
            member = m.group(1) if m else "the called member"
        return (
            f"PRIVATE METHOD ACCESS ERROR: Your test called `{member}` directly, "
            f"but it is declared `private` in the source class.\n"
            "RULE: tests can only call `public`, `protected`, or package-private members.\n"
            f"FIX: REMOVE the call to `{member}` from the test. If you need to verify the "
            "behavior of the private method, find the PUBLIC method in the source class "
            "that invokes it internally and call THAT public method — the private logic "
            "will execute as part of the public call's side effects.\n"
            "Look in DEPENDENCY CONTEXT for public method signatures of this class."
        )

    # Erro de construtor de record (detectar ANTES de cannot find symbol)
    if "constructor" in out and "in record" in out and "cannot be applied" in out:
        for line in output.splitlines():
            if "required:" in line:
                args = line.split("required:")[-1].strip()
                return (
                    f"RECORD CONSTRUCTOR ERROR: Constructor called without required arguments.\n"
                    f"Required argument types: {args}\n\n"
                    "FIX: Look in the DEPENDENCY CONTEXT section for the line:\n"
                    "  // CONSTRUCTOR CALL: new RecordName(param1, param2, ...)\n"
                    "Copy that EXACT call as your instantiation template — use the real param names shown there.\n"
                    "NEVER use an empty constructor for records — records have no default no-arg constructor."
                )
        return (
            "RECORD CONSTRUCTOR ERROR: The record constructor was called incorrectly.\n"
            "Look in the DEPENDENCY CONTEXT for the line '// CONSTRUCTOR CALL: new ...' "
            "and use that EXACT call — pass ALL declared fields in order."
        )

    # D: Construtor sem argumentos em classe que exige parâmetros (não-record)
    if "constructor" in out and "cannot be applied" in out and "found:" in out:
        required, found = "", ""
        for line in output.splitlines():
            if "required:" in line and not required:
                required = line.split("required:")[-1].strip()
            if "found:" in line and not found:
                found = line.split("found:")[-1].strip()
        if required:
            return (
                f"CONSTRUCTOR ERROR: You called the constructor with wrong arguments.\n"
                f"  Required: {required}\n"
                f"  Found:    {found or 'no arguments'}\n\n"
                "FIX: Look in the DEPENDENCY CONTEXT section for the line:\n"
                "  // CONSTRUCTOR CALL: new ClassName(param1, param2, ...)\n"
                "Use that EXACT call — pass ALL required arguments in the shown order.\n"
                "NEVER call a constructor with no arguments if the class requires them."
            )
        return (
            "CONSTRUCTOR ERROR: Constructor called with wrong argument count or types.\n"
            "Look in the DEPENDENCY CONTEXT for the '// CONSTRUCTOR CALL:' hint "
            "and use that EXACT instantiation — pass all required arguments."
        )

    # Erro de enum/variável inventada
    if "cannot find symbol" in out:
        for line in output.splitlines():
            if "symbol:" in line:
                sym = line.split("symbol:")[-1].strip()
                if "variable" in sym:
                    return (
                        f"ENUM/VARIABLE ERROR: You used '{sym}' which DOES NOT EXIST in the class.\n"
                        "Use ONLY the values declared in the DEPENDENCY CONTEXT section of the prompt.\n"
                        "Replace it with the correct value listed under 'ALLOWED ENUM VALUES'."
                    )
                if "method" in sym:
                    # P2a: JUnit assertion method ausente → falta import static, não método inexistente
                    _method_name_m = re.search(r'\bmethod\s+(\w+)\s*\(', sym)
                    if _method_name_m and _method_name_m.group(1) in _JUNIT_ASSERTION_METHODS:
                        return (
                            "STATIC IMPORT ERROR: JUnit 5 assertion method not found in scope.\n"
                            "ADD THIS LINE to your import block (copy verbatim):\n"
                            "  import static org.junit.jupiter.api.Assertions.*;\n"
                            "This makes assertTrue(), assertFalse(), assertEquals(), assertNull(), etc. available.\n"
                            "Do NOT call Assertions.assertTrue() explicitly — use the static form directly.\n"
                            "Do NOT change any other code — ONE import line addition only."
                        )
                    return (
                        f"METHOD ERROR: You called '{sym}' which DOES NOT EXIST in the class.\n"
                        "Check the exact signatures of the source class and use only real methods."
                    )
                if "class" in sym:
                    cls_name = sym.replace("class", "").strip()
                    # S2: busca import exato no mapa de imports de produção ou JDK
                    if prod_imports:
                        for imp in prod_imports:
                            m = re.match(r'import\s+([\w.]+);', imp)
                            if m and m.group(1).split(".")[-1] == cls_name:
                                return (
                                    f"IMPORT ERROR: Class `{cls_name}` is missing its import.\n"
                                    f"ADD THIS EXACT LINE to your import block (copy verbatim):\n"
                                    f"  {imp}\n"
                                    "Do NOT modify this import in any way."
                                )
                    if cls_name in _JDK_IMPORT_MAP:
                        jdk_imp = _JDK_IMPORT_MAP[cls_name]
                        return (
                            f"IMPORT ERROR: Class `{cls_name}` is missing its import.\n"
                            f"ADD THIS EXACT LINE to your import block (copy verbatim):\n"
                            f"  {jdk_imp}\n"
                            "Do NOT modify this import in any way."
                        )
                    return (
                        f"IMPORT ERROR: Class '{sym}' not found.\n"
                        "Add the correct import. Use only classes that exist in the project."
                    )
        return (
            "ERROR 'cannot find symbol': A referenced symbol does not exist.\n"
            "Check enum values, methods and imports — use only what is declared in the source class."
        )

    # Package inexistente
    if "package" in out and "does not exist" in out:
        return (
            "PACKAGE ERROR: An import points to a package that does not exist.\n"
            "Use only classes from the project — check the DEPENDENCY CONTEXT for the correct imports."
        )

    # Erro de asserção (valor esperado errado)
    if "assertionerror" in out or "expected:" in out:
        for line in output.splitlines():
            if "expected:" in line or "but was:" in line:
                detail = line.strip()

                # G1: extrai expected/actual direto do erro Maven — instrução cirúrgica
                # Cobre tanto BigDecimal (50.00 vs 5.00) quanto qualquer outro mismatch
                _m_vals = re.search(
                    r'expected:\s*<([^>]*)>\s*but was:\s*<([^>]*)>', detail
                )
                if _m_vals:
                    _expected_in_test = _m_vals.group(1)
                    _actual_from_code = _m_vals.group(2)

                    # F4: null vs empty string — caso especial com instrução de substituição de método
                    if _expected_in_test == "null" and _actual_from_code == "":
                        return (
                            "ASSERTION WRONG EXPECTED VALUE:\n"
                            "  Your test expects: <null>\n"
                            "  Actual return value: <\"\"> (empty string)\n\n"
                            "SURGICAL FIX — change ONLY the assertion:\n"
                            "  REPLACE assertNull(...) with assertEquals(\"\", result) "
                            "or assertTrue(result.isEmpty()).\n"
                            "  Do NOT change inputs, method calls, imports, or any other code.\n"
                            "  ONE change only."
                        )

                    # S4: test expects null (assertNull) but actual is a real non-null value
                    # Mirror of S1: setUp/constructor already initialized the field.
                    # G1 general is ambiguous here because "null" is in the method name assertNull().
                    if _expected_in_test == "null" and _actual_from_code and _actual_from_code != "null":
                        return (
                            f"ASSERTION WRONG EXPECTED VALUE:\n"
                            f"  Your test used assertNull() but the actual return value is:"
                            f" <{_actual_from_code}>\n\n"
                            f"ROOT CAUSE: setUp() or the constructor already initialized this field"
                            f" to '{_actual_from_code}'.\n"
                            "  assertNull() fails because the field is NOT null"
                            " — it was set by the constructor.\n\n"
                            "SURGICAL FIX — change ONLY the failing assertNull line:\n"
                            f"  REPLACE: assertNull(expression)\n"
                            f"  WITH:    assertEquals(\"{_actual_from_code}\", expression)\n"
                            "  Do NOT modify setUp(), constructor calls, other assertions,"
                            " imports, or any other code.\n"
                            "  ONE LINE CHANGE — nothing else."
                        )

                    # S1: actual é null — instrução específica para assertNull()
                    # Evita ambiguidade: LLM não deve usar assertEquals("null", ...) nem assertEquals(null, ...)
                    if _actual_from_code == "null":
                        return (
                            f"ASSERTION WRONG EXPECTED VALUE:\n"
                            f"  Your test expects: <{_expected_in_test}>\n"
                            f"  Actual return value: <null> (Java null reference)\n\n"
                            "SURGICAL FIX — change ONLY the assertion:\n"
                            f"  REPLACE the assertion containing '{_expected_in_test}' "
                            "with assertNull(expression).\n"
                            "  NEVER use assertEquals(\"null\", ...) — that compares a String, not null.\n"
                            "  NEVER use assertEquals(null, ...) — use assertNull() instead.\n"
                            "  Do NOT change inputs, method calls, imports, or any other code.\n"
                            "  ONE LINE CHANGE — nothing else."
                        )

                    # Caso geral: substitui apenas o valor esperado
                    # S2: nota de desambiguação para null ao final — previne confusão se actual vier como "null"
                    return (
                        f"ASSERTION WRONG EXPECTED VALUE:\n"
                        f"  Your test expects: <{_expected_in_test}>\n"
                        f"  Actual return value: <{_actual_from_code}>\n\n"
                        f"SURGICAL FIX — change ONLY the expected value in the assertion:\n"
                        f"  Find the assertion containing '{_expected_in_test}' "
                        f"and replace it with '{_actual_from_code}'.\n"
                        f"  Do NOT modify inputs, method calls, imports, or any other code.\n"
                        f"  ONE LINE CHANGE — nothing else.\n"
                        "NOTE: if the actual value is Java's null, use assertNull(...) — "
                        "NEVER assertEquals(\"null\", ...) which compares a String."
                    )

                # Sem padrão extraível — fallback genérico
                return (
                    f"ASSERTION ERROR: The expected value in the test is wrong.\n"
                    f"Detail: {detail}\n"
                    "Fix assertEquals/assertThat to match what the method ACTUALLY returns.\n"
                    "Do NOT guess what 'should' happen — test current behavior, not desired behavior."
                )
        return (
            "ASSERTION ERROR: Expected value in the test differs from the actual method return.\n"
            "Run the method mentally step by step with the test input.\n"
            "Use the actual computed result as the expected value."
        )

    # Spring context (SpringBootTest/WebMvcTest proibidos)
    if "springboottest" in out or "applicationcontext" in out or "webmvctest" in out:
        return (
            "SPRING CONTEXT ERROR: You used @SpringBootTest or @WebMvcTest — this is FORBIDDEN.\n"
            "Use ONLY @ExtendWith(MockitoExtension.class) with new ClassName() and @Mock/@InjectMocks."
        )

    # NullPointerException sem mock configurado
    if "nullpointerexception" in out:
        return (
            "NULLPOINTEREXCEPTION ERROR: A dependency was not mocked correctly.\n"
            "Make sure all @Mock fields are configured with Mockito.when(...) before the method call."
        )

    # Tipo incompatível no retorno do mock ou assertion
    # E + Opção 2: incompatible-types numeric/big-number coercions
    # Order matters — check more specific patterns first.
    if "incompatible types" in out:
        # E (preserved): BigDecimal passado onde Long é esperado (ex: campo version)
        if "bigdecimal" in out and "long" in out:
            return (
                "TYPE MISMATCH — Long field: You passed a BigDecimal where Long is required.\n"
                "REPLACE the BigDecimal value with a Long literal.\n"
                "  WRONG:   new BigDecimal(\"1\")  /  new BigDecimal(1)\n"
                "  CORRECT: 1L  or  Long.valueOf(1)\n"
                "Check the CONSTRUCTOR CALL hint in DEPENDENCY CONTEXT — "
                "the parameter typed as 'Long' must receive a long integer, not a decimal.\n"
                "Apply to ALL Long parameters in constructors and method calls."
            )

        # Opção 2 (new): int/short/byte → Long literal (must add L suffix)
        if re.search(r'incompatible types:\s*(int|short|byte)\s+cannot be converted to\s+(?:java\.lang\.)?Long', output, re.IGNORECASE):
            return (
                "TYPE CONVERSION ERROR: An int/short/byte literal cannot be auto-converted to Long.\n"
                "  CORRECT: 1L  or  Long.valueOf(1)\n"
                "  WRONG:   1   ← raw int — Java will NOT auto-widen to Long in this context\n"
                "Find the int literal on the line indicated by the error and add the L suffix (e.g. 1 → 1L)."
            )

        # Opção 2 (new): int/double/short/byte/float → BigDecimal
        if re.search(r'incompatible types:\s*(int|short|byte|double|float)\s+cannot be converted to\s+(?:java\.math\.)?BigDecimal', output, re.IGNORECASE):
            return (
                "TYPE CONVERSION ERROR: A numeric primitive cannot be auto-converted to BigDecimal.\n"
                "  CORRECT: new BigDecimal(\"100.00\")  or  BigDecimal.valueOf(100)\n"
                "  WRONG:   100      ← raw int/double — no implicit conversion\n"
                "Find the literal on the line indicated by the error and wrap it in new BigDecimal(...) or BigDecimal.valueOf(...)."
            )

        # A: String literal passado onde BigDecimal é esperado
        if "string" in out and "bigdecimal" in out:
            return (
                "TYPE MISMATCH — BigDecimal: You passed a String literal where BigDecimal is required.\n"
                "REPLACE every string literal with new BigDecimal(\"value\").\n"
                "  WRONG:   someMethod(\"100.00\")  /  new Foo(\"50.00\")\n"
                "  CORRECT: someMethod(new BigDecimal(\"100.00\"))  /  new Foo(new BigDecimal(\"50.00\"))\n"
                "Apply this fix to ALL BigDecimal parameters in constructors and method calls."
            )

        # Generic fallback (preserved) — covers any other incompatible-types case
        for line in output.splitlines():
            if "incompatible types" in line.lower():
                return (
                    f"TYPE MISMATCH ERROR: {line.strip()}\n"
                    "Check that mock return values match the exact return type of the method.\n"
                    "For ResponseEntity<X>, mock the service to return X (not ResponseEntity)."
                )
        return (
            "TYPE MISMATCH ERROR: A value or mock return has an incompatible type.\n"
            "Check exact return types in DEPENDENCY CONTEXT and align assertions/mocks."
        )

    # Método não pode ser aplicado (argumentos errados)
    if "method" in out and ("cannot be applied" in out or "not applicable" in out):
        for line in output.splitlines():
            if "cannot be applied" in line.lower() or "not applicable" in line.lower():
                return (
                    f"METHOD CALL ERROR: {line.strip()}\n"
                    "Check the exact method signature in DEPENDENCY CONTEXT — wrong argument count or type."
                )
        return (
            "METHOD CALL ERROR: A method was called with wrong arguments.\n"
            "Check the method signatures in DEPENDENCY CONTEXT and fix argument types/count."
        )

    # MockMvc sem contexto Spring (proibido sem @WebMvcTest)
    if "mockmvc" in out:
        return (
            "MOCKMVC ERROR: MockMvc requires Spring context (@WebMvcTest) which is FORBIDDEN.\n"
            "Instead: instantiate the controller directly with new ControllerClass().\n"
            "Use @Mock for the service and @InjectMocks for the controller."
        )

    # Construtor não encontrado (não-record)
    if "constructor" in out and ("no suitable" in out or "cannot find" in out):
        return (
            "CONSTRUCTOR ERROR: No suitable constructor found.\n"
            "Check the class declaration in DEPENDENCY CONTEXT — use the exact constructor args declared.\n"
            "For records, use the CONSTRUCTOR CALL hint in the DEPENDENCY CONTEXT section."
        )

    # Mockito — stub desnecessário (strict stubbing)
    if "unnecessarystubbingexception" in out:
        return (
            "MOCKITO STRICT ERROR: You declared a mock stub (when/thenReturn) that was never called.\n"
            "Remove all Mockito.when(...) stubs that are not used by any @Test method.\n"
            "Only stub what each test actually invokes."
        )

    # Mockito — verificação falhou (método não foi chamado)
    if "wantedbutnotinvoked" in out or "wanted but not invoked" in out:
        return (
            "MOCKITO VERIFY ERROR: verify() expected a method call that never happened.\n"
            "Either remove the verify() or fix the test so the method is actually called."
        )

    # Mockito — when() sem chamada de método real dentro
    if "missingmethodinvocationexception" in out or "missing method invocation" in out:
        return (
            "MOCKITO WHEN ERROR: when() must wrap a real method call on a mock.\n"
            "Pattern: when(mockObj.realMethod(args)).thenReturn(value).\n"
            "Do NOT call when() on a concrete object or a spy without a method."
        )

    # Mockito — cannot mock final/sealed class
    if "cannot mock" in out or "cannot spy" in out:
        return (
            "MOCKITO MOCK TYPE ERROR: This class cannot be mocked (final, sealed, or primitive).\n"
            "Use the real object instead of a mock, or wrap it in an interface."
        )

    # Mockito — argument matchers mixed with raw values
    if "invaliduseofmatchersexception" in out or "invalid use of argument matchers" in out:
        return (
            "MOCKITO MATCHER ERROR: Cannot mix argument matchers (any(), eq()) with raw values.\n"
            "Either use matchers for ALL arguments or raw values for ALL arguments.\n"
            "Example: when(mock.method(any(), eq(\"value\"))).thenReturn(x)  — ALL matchers."
        )

    # Classe pública com nome diferente do arquivo (class Foo in Bar.java)
    if "should be declared in a file named" in out:
        m = re.search(
            r'class (\w+) is public, should be declared in a file named (\w+\.java)',
            output,
        )
        if m:
            wrong_cls, correct_file = m.group(1), m.group(2)
            correct_cls = correct_file.replace(".java", "")
            return (
                f"CLASS NAME CRITICAL ERROR: You declared `public class {wrong_cls}` "
                f"but the file is `{correct_file}`.\n"
                f"RENAME the class to EXACTLY: `public class {correct_cls} {{`\n"
                "Java law: the public class name MUST equal the filename. No exceptions.\n"
                "Do NOT abbreviate, shorten, or change it in any way."
            )

    # Output truncado pelo limite de tokens (reached end of file / try without catch)
    if "reached end of file while parsing" in out or (
        "'try' without 'catch'" in out and "reached end of file" in out
    ):
        return (
            "TRUNCATED OUTPUT: Your previous code was cut off before completion.\n"
            "DO NOT rewrite the entire file.\n"
            "Count the open `{` braces vs closed `}` braces in your previous output "
            "and add ONLY the missing closing braces `}`, catch/finally blocks, "
            "and semicolons needed to complete the file.\n"
            "Start your output from the last complete line of the previous attempt."
        )

    return (
        "COMPILATION/EXECUTION ERROR: Analyze the stack trace below and fix the code.\n"
        "Do NOT change business logic — fix only what the error points to."
    )


_SKIP_PATTERNS = [
    (re.compile(r'extends\s+\w*Repository\w*\s*<'),
     "Interface JPA pura (generics complexos)"),
    (re.compile(r'@SpringBootApplication'),
     "Classe main Spring Boot"),
    (re.compile(r'public\s+interface\b'),
     "Interface pura (sem lógica)"),
    (re.compile(r'(?m)^\s*[A-Z][A-Z_0-9]+\s*\([^)]+\)\s*[,;]'),
     "Enum com construtor parametrizado"),
]

# Padrões que só se aplicam em fases estruturais (SOLID, arquitetura, etc.)
_STRUCTURAL_PHASE_KEYWORDS = {
    "solid", "architecture", "patterns", "clean_code",
    "tracking", "nomenclature", "structure", "final_keywords",
    # community skills — @Document/@Entity não devem ser convertidas/reestruturadas
    "community", "record_migration", "builder_pattern", "dead_code",
    "introduce_parameter", "strategy_pattern", "encapsulate_field",
}
_SKIP_FOR_STRUCTURAL = [
    (re.compile(r'@Document\b'), "@Document — holder de dados MongoDB"),
    (re.compile(r'@Entity\b'),   "@Entity — holder de dados JPA"),
    (re.compile(r'@Table\b'),    "@Table — holder de dados JPA"),
]


# ---------------------------------------------------------------------------
# Solução 5 — Registro de falhas
# ---------------------------------------------------------------------------

_PERMANENT_SKIP_THRESHOLD = 3  # runs consecutivos com falha → skip permanente

# P1: padrões no stack_trace que indicam um bug já corrigido no pipeline.
# Entradas permanent_skip cujo stack_trace contenha algum destes padrões são
# automaticamente removidas em reset(), permitindo novo ciclo de geração.
_AUTO_EXPIRE_STACK_PATTERNS = [
    "com.example",              # F2 Package Guard: package hallucination no longer possible
    "actual and formal argument lists differ in length",  # Fix A: CONSTRUCTOR CALL hint now includes types
    "O arquivo se chama",       # Fix B/H: old Portuguese integrity error — impossible after fix B
]


class FailedFilesTracker:
    def __init__(self, logs_dir: str = "logs"):
        self._path   = os.path.join(logs_dir, "failed_files.json")
        self._entries: list[dict] = []
        os.makedirs(logs_dir, exist_ok=True)
        if os.path.exists(self._path):
            try:
                with open(self._path) as f:
                    self._entries = json.load(f)
            except Exception:
                self._entries = []

    def record(self, file_path: str, phase: str, reason: str,
               stack_trace: str = "") -> None:
        key = (file_path, phase)
        # Não duplicar dentro do mesmo run
        if any(e["file"] == file_path and e["phase"] == phase and not e.get("prev_run")
               for e in self._entries):
            return
        # Herdar fail_count acumulado de runs anteriores (prev_run ou permanent_skip)
        prior_count = self._get_prior_fail_count(file_path, phase)
        entry = {
            "file": file_path, "phase": phase, "reason": reason,
            "timestamp": datetime.now().isoformat(), "retried": False,
            "fail_count": prior_count + 1,
        }
        if stack_trace:
            entry["stack_trace"] = stack_trace[-800:]
        # Promover a permanent_skip se atingiu o threshold
        if entry["fail_count"] >= _PERMANENT_SKIP_THRESHOLD:
            entry["permanent_skip"] = True
            # Remove entradas prev_run anteriores — permanent_skip é o único registro necessário
            self._entries = [
                e for e in self._entries
                if not (e["file"] == file_path and e["phase"] == phase and e.get("prev_run"))
            ]
            log(
                f"  → {os.path.basename(file_path)}: SKIP PERMANENTE "
                f"({entry['fail_count']} falhas consecutivas)",
                "WARN",
            )
        self._entries.append(entry)
        self._save()
        log(f"  → failed_files.json: {os.path.basename(file_path)}", "WARN")

    def _get_prior_fail_count(self, file_path: str, phase: str) -> int:
        """Soma fail_count de todas as entradas anteriores (prev_run + permanent_skip)."""
        return sum(
            e.get("fail_count", 1)
            for e in self._entries
            if e["file"] == file_path and e["phase"] == phase
            and (e.get("prev_run") or e.get("permanent_skip"))
        )

    def is_permanent_skip(self, file_path: str, phase: str) -> bool:
        """Retorna True se este arquivo deve ser pulado permanentemente."""
        return any(
            e.get("permanent_skip")
            for e in self._entries
            if e["file"] == file_path and e["phase"] == phase
        )

    def _save(self):
        with open(self._path, "w") as f:
            json.dump(self._entries, f, indent=2, ensure_ascii=False)

    def get_pending(self) -> list[dict]:
        return [e for e in self._entries if not e["retried"]]

    def mark_retried(self, file_path: str, phase: str):
        for e in self._entries:
            if e["file"] == file_path and e["phase"] == phase:
                e["retried"] = True
        self._save()

    def get_build_failure_count(self, file_path: str) -> int:
        """Conta falhas de build reais (exclui 'código idêntico' e skips semânticos)."""
        return sum(
            1 for e in self._entries
            if e["file"] == file_path and "build quebrou" in e.get("reason", "")
        )

    def __len__(self) -> int:
        return len(self._entries)

    def reset(self) -> None:
        """Marca entradas atuais como prev_run. Expira permanentes de bugs já corrigidos."""
        kept = []
        for e in self._entries:
            if e.get("permanent_skip"):
                # P1: se o stack_trace bate com padrão de bug corrigido, remove o bloqueio
                st = (e.get("stack_trace") or "") + " " + (e.get("reason") or "")
                expired_pat = next(
                    (p for p in _AUTO_EXPIRE_STACK_PATTERNS if p in st), None
                )
                if expired_pat:
                    log(
                        f"  → {os.path.basename(e['file'])}: permanent_skip expirado "
                        f"(bug corrigido detectado: '{expired_pat}')",
                        "INFO",
                    )
                    continue  # descarta — arquivo será reprocessado do zero
                kept.append(e)
            elif not e.get("prev_run"):
                e["prev_run"] = True
                kept.append(e)
            # prev_run já contados são descartados
        self._entries = kept
        self._save()

    def clear_permanent_skips(self, file_path: str | None = None) -> int:
        """Remove permanent_skip de um arquivo específico (ou de todos). Retorna count."""
        before = len(self._entries)
        if file_path:
            self._entries = [
                e for e in self._entries
                if not (e["file"] == file_path and e.get("permanent_skip"))
            ]
        else:
            self._entries = [e for e in self._entries if not e.get("permanent_skip")]
        removed = before - len(self._entries)
        if removed:
            self._save()
        return removed


_failed_tracker: FailedFilesTracker | None = None


def get_failed_tracker(logs_dir: str = "logs") -> FailedFilesTracker:
    global _failed_tracker
    if _failed_tracker is None:
        _failed_tracker = FailedFilesTracker(logs_dir)
    return _failed_tracker


# ---------------------------------------------------------------------------
# Surgical patch — deterministic one-line assertion fix
# ---------------------------------------------------------------------------

def _try_surgical_patch(test_code: str, maven_output: str) -> str | None:
    """
    Apply a one-line Python patch for assertion failures whose fix is deterministic.
    Returns the patched file or None if the case isn't covered.

    Covers three cases (mirrors S1/S4/G1 of _categorize_build_error):
      1. expected=<null>, actual=<value> → assertNull(expr) → assertEquals("value", expr)
      2. expected=<value>, actual=<null> → assertEquals(value, expr) → assertNull(expr)
      3. both non-null, simple literal mismatch → replace expected with actual on that line

    Maven line numbers can be slightly off (±3 lines); we search a small window around
    the reported line to find the relevant assertion.
    """
    line_match = re.search(r'(\w+)\.\w+:(\d+)\s+expected:\s*<([^>]*)>\s*but was:\s*<([^>]*)>',
                            maven_output)
    if not line_match:
        return None
    line_no = int(line_match.group(2))
    expected = line_match.group(3)
    actual   = line_match.group(4)

    lines = test_code.splitlines()
    if line_no < 1 or line_no > len(lines):
        return None

    _WINDOW = 3  # Maven line numbers can be off by a few lines

    def _candidate_indices() -> list[int]:
        """Return 0-based line indices to try, starting from the reported line."""
        result = []
        for offset in range(0, _WINDOW + 1):
            for delta in ([0] if offset == 0 else [offset, -offset]):
                idx = line_no - 1 + delta
                if 0 <= idx < len(lines) and idx not in result:
                    result.append(idx)
        return result

    # Case 1: expected null, actual non-null and non-"null" → assertNull → assertEquals
    if expected == "null" and actual and actual != "null":
        _pat = re.compile(r'assertNull\s*\(\s*([^)]+)\s*\)')
        for idx in _candidate_indices():
            m = _pat.search(lines[idx])
            if m:
                expr = m.group(1).strip()
                new_call = f'assertEquals("{actual}", {expr})'
                lines[idx] = lines[idx].replace(m.group(0), new_call, 1)
                return "\n".join(lines) + ("\n" if test_code.endswith("\n") else "")
        return None

    # Case 2: expected non-null, actual is null → assertEquals(X, expr) → assertNull(expr)
    if actual == "null" and expected and expected != "null":
        _pat = re.compile(r'assertEquals\s*\(\s*[^,]+,\s*([^)]+)\s*\)')
        for idx in _candidate_indices():
            m = _pat.search(lines[idx])
            if m:
                expr = m.group(1).strip()
                new_call = f'assertNull({expr})'
                lines[idx] = lines[idx].replace(m.group(0), new_call, 1)
                return "\n".join(lines) + ("\n" if test_code.endswith("\n") else "")
        return None

    # Case 3: simple literal mismatch — replace expected with actual ON THAT LINE ONLY
    if expected and actual and expected != "null" and actual != "null":
        # Word-boundary replace to avoid "5" -> "50" turning "50" into "500"
        _pat = re.compile(r'(?<![\w.])' + re.escape(expected) + r'(?![\w.])')
        for idx in _candidate_indices():
            if _pat.search(lines[idx]):
                new_line = _pat.sub(actual, lines[idx], count=1)
                if new_line != lines[idx]:
                    lines[idx] = new_line
                    return "\n".join(lines) + ("\n" if test_code.endswith("\n") else "")
        return None

    return None


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

def should_skip(file_path: str, code: str, phase: str = "") -> tuple[bool, str]:
    if len(code.splitlines()) > MAX_FILE_LINES:
        return True, f"Arquivo muito grande ({len(code.splitlines())} linhas)"
    for pattern, reason in _SKIP_PATTERNS:
        if pattern.search(code):
            return True, reason
    phase_lower = phase.lower() if phase else ""
    if any(kw in phase_lower for kw in _STRUCTURAL_PHASE_KEYWORDS):
        for pattern, reason in _SKIP_FOR_STRUCTURAL:
            if pattern.search(code):
                return True, reason
    return False, ""


def _mode_for(file_path: str) -> str:
    return "test" if "/test/" in file_path.replace("\\", "/") else "refactor"


def get_java_files(repo_path: str, tests: bool = False) -> list[str]:
    files = []
    for root, _, fs in os.walk(repo_path):
        if "target" in root.replace("\\", "/").split("/"):
            continue
        for f in fs:
            if not f.endswith(".java"):
                continue
            full       = os.path.join(root, f)
            normalized = full.replace("\\", "/")
            in_test    = "/test/" in normalized
            if tests and in_test:
                files.append(full)
            elif not tests and not in_test:
                files.append(full)
    return files


def _test_path_for(main_file: str, repo_path: str) -> str | None:
    normalized = main_file.replace("\\", "/")
    if "/main/" not in normalized:
        return None
    test_path = normalized.replace("/main/", "/test/")
    base, _   = os.path.splitext(test_path)
    return base + "Test.java"


# ---------------------------------------------------------------------------
# Ciclo de geração + validação com correção
# ---------------------------------------------------------------------------

def _generate_and_validate(original: str, rules: str, mode: str,
                             file_name: str, file_path: str,
                             phase: str = "",
                             cache=None,
                             semantic_mem=None) -> tuple[str | None, str]:
    """
    Chama a IA e valida o resultado com injeção de contexto de dependências.
    dep_context é obtido do cache ou gerado, e passado separado para build_prompt.
    """
    from java.context import get_dependency_context

    dep_context = ""
    root = file_path
    try:
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
                "\n\n[CONTEXTO DE TESTE] O teste abaixo valida esta classe. "
                "Sua refatoração DEVE garantir que ele continue passando:\n\n"
                f"```java\n{test_code}\n```"
            )
            log("  [Contexto] Teste unitário injetado.", "OK")
    except Exception:
        pass

    phase_delta = rules + test_context

    if semantic_mem is not None:
        mem_context = semantic_mem.search(f"{phase} {file_name}")
        if mem_context:
            phase_delta = phase_delta + f"\n\n[APRENDIZADOS ANTERIORES]:\n{mem_context}"

    new_code = call_ai(original, phase_delta, mode, file_name,
                       file_path=file_path, phase=phase,
                       dep_context=dep_context)

    if not new_code:
        return None, "IA não gerou código"

    # Melhoria 1: código idêntico = modelo confirmou que não há mudanças necessárias
    if new_code.strip() == original.strip():
        return None, _REASON_NO_CHANGE

    valid, reason = is_valid_java(original, new_code)
    if valid:
        # Skill: Validador de Integridade de Nome
        from java.validator import validate_class_name_matches_file
        is_name_ok, name_error = validate_class_name_matches_file(new_code, file_path)
        if not is_name_ok:
            # B: constrói mensagem de reparo específica com o nome errado E o nome correto
            _expected_cls = file_name.replace(".java", "")
            _generated_cls_m = re.search(r'(?:public\s+)?(?:class|interface|record|enum)\s+(\w+)', new_code)
            _generated_cls = _generated_cls_m.group(1) if _generated_cls_m else "UNKNOWN"
            reason = (
                f"CLASS NAME CRITICAL ERROR: You wrote 'class {_generated_cls}' "
                f"but the EXACT required name is '{_expected_cls}'.\n"
                f"CHANGE the class declaration to: public class {_expected_cls}\n"
                "Do NOT abbreviate, shorten, or remove any part of the name — "
                f"copy EXACTLY '{_expected_cls}' character by character.\n"
                "This is a hard requirement: the class name MUST equal the filename."
            )
        else:
            # Melhoria 2: Validação de package
            is_pkg_ok, pkg_error = validate_package_matches_path(new_code, file_path)
            if not is_pkg_ok:
                reason = f"PACKAGE ERROR: {pkg_error}"
            else:
                return new_code, ""

    log(f"  Validator rejeitou: {reason} — tentando correção", "WARN")

    from core.utils import load_skill as _ls
    _refactor_repair = _ls("java-repair-guide", section="LLM INSTRUCTIONS") or ""
    _live(active_skill="java-repair-guide")

    # Ciclos de correção
    rejected_code = new_code
    for attempt in range(1, MAX_VALIDATOR_RETRIES + 1):
        log(f"  Correção validator {attempt}/{MAX_VALIDATOR_RETRIES}: {reason[:60]}")
        repair_reason = f"{_refactor_repair}\n\n{reason}".strip() if _refactor_repair else reason

        corrected = call_ai_with_correction(
            original      = original,
            rules         = phase_delta,
            mode          = mode,
            file_name     = file_name,
            file_path     = file_path,
            bad_output    = rejected_code,
            error_reason  = repair_reason,
            phase         = phase,
            dep_context   = dep_context,
        )

        if not corrected:
            log(f"  Correção {attempt}: sem resposta", "WARN")
            break

        if corrected and corrected.strip() == original.strip():
            return None, _REASON_NO_CHANGE

        valid, reason = is_valid_java(original, corrected)
        if valid:
            from java.validator import validate_class_name_matches_file
            is_name_ok, name_error = validate_class_name_matches_file(corrected, file_path)
            if not is_name_ok:
                _expected_cls2 = file_name.replace(".java", "")
                _gen_cls_m2 = re.search(r'(?:public\s+)?(?:class|interface|record|enum)\s+(\w+)', corrected)
                _gen_cls2 = _gen_cls_m2.group(1) if _gen_cls_m2 else "UNKNOWN"
                reason = (
                    f"CLASS NAME CRITICAL ERROR: You STILL wrote 'class {_gen_cls2}' "
                    f"but the EXACT required name is '{_expected_cls2}'.\n"
                    f"CHANGE the class declaration to: public class {_expected_cls2}\n"
                    "Do NOT abbreviate under any circumstances — "
                    f"copy EXACTLY '{_expected_cls2}' every single character."
                )
            else:
                is_pkg_ok, pkg_error = validate_package_matches_path(corrected, file_path)
                if not is_pkg_ok:
                    reason = f"PACKAGE ERROR: {pkg_error}"
                else:
                    log(f"  Correção {attempt}: aceita ✓", "OK")
                    return corrected, ""

        log(f"  Correção {attempt}: ainda rejeitado — {reason}", "WARN")
        rejected_code = corrected

    return None, reason


# ---------------------------------------------------------------------------
# Refatoração — arquivo inteiro
# ---------------------------------------------------------------------------

def _refactor_whole_file(file: str, original: str, rules: str,
                          repo_path: str, phase: str,
                          reporter: PhaseReporter,
                          exec_logger: ExecutionLogger | None,
                          cache=None,
                          semantic_mem=None) -> bool:
    file_name = os.path.basename(file)
    mode      = _mode_for(file)

    new_code, reason = _generate_and_validate(
        original, rules, mode, file_name, file, phase=phase, cache=cache,
        semantic_mem=semantic_mem,
    )

    if not new_code:
        if reason == _REASON_NO_CHANGE:
            log(f"  {file_name}: modelo confirmou que não há alterações necessárias", "OK")
            if exec_logger:
                exec_logger.log_file_skipped(phase, file_name, "Não necessita alterações")
            reporter.record_skipped(phase, file_name, "Não necessita alterações")
            return False
        log(f"  {file_name}: falhou — {reason}", "WARN")
        get_failed_tracker().record(file, phase, reason)
        if exec_logger:
            exec_logger.log_ai_failure(phase, file_name, "all-agents", reason)
        if "não gerou" in reason:
            reporter.record_skipped(phase, file_name, reason)
        else:
            reporter.record_rejected(phase, file_name, reason)
        return False

    write_file(file, new_code)
    success, build_output = maven_test(repo_path)

    if not success:
        log(f"  {file_name}: Build falhou. Analisando impacto global...", "WARN")
        
        # Skill: Detecção de Impacto em Cascata
        if "cannot find symbol" in build_output or "does not override" in build_output:
            _live(active_skill="Sincronia Contextual")
            log("  [Impacto Detectado] Mudança de contrato detectada. Tentando sincronização contextual...", "PHASE")
            _attempt_global_sync(build_output, repo_path, rules, phase, new_code)
            success, build_output = maven_test(repo_path)
            if success:
                log(f"  {file_name}: Sincronização global restaurou o build! ✓", "OK")

    if not success:
        log(f"  {file_name}: Build persiste com erro. Ativando Diagnóstico de Precisão...", "WARN")
        
        # Skill: Identificação de Culpado Transversal
        # Se o erro for em OUTRO arquivo (ex: interface que sumiu), tentamos restaurar/corrigir o outro arquivo.
        culprit_match = re.search(r'([/\\].*\.java):\[\d+', build_output)
        if culprit_match:
            culprit_path = culprit_match.group(1)
            culprit_name = os.path.basename(culprit_path)
            if culprit_name != file_name:
                log(f"  [Auto-Cura] O culpado parece ser {culprit_name}. Tentando reparo de emergência...", "PHASE")
                # Se o erro for "does not contain class" ou "should be declared in file", é erro estrutural
                if "should be declared in a file" in build_output or "does not contain class" in build_output:
                    # Tenta restaurar o arquivo da interface/culpado para o estado estável
                    run_command(f"git checkout -- \"{culprit_path}\"", repo_path)
                    log(f"  [Auto-Cura] {culprit_name} restaurado para estado estável do Git.", "OK")
                    success, build_output = maven_test(repo_path)
                    if success: return True # Resolvido restaurando o culpado
        
        # Skill: Raio-X de Erros (Continua para o arquivo atual)
        _live(active_skill="Raio-X de Erros")
        error_diagnostics = []
        raw_error_lines = [l for l in build_output.splitlines() if "[ERROR]" in l and ".java:[" in l][:5]
        
        for err_line in raw_error_lines:
            # Regex melhorado para suportar espaços no caminho: /caminho/com espaço/Arquivo.java:[linha,coluna]
            m = re.search(r'([/\\].*\.java):\[(\d+)', err_line)
            if m:
                fpath, lnum = m.group(1), int(m.group(2))
                try:
                    code_snippet = _get_line_from_file(fpath, lnum)
                    diag = f"Erro em {os.path.basename(fpath)} L{lnum}: {code_snippet.strip()}\n      -> {err_line.split('] ', 1)[-1]}"
                    error_diagnostics.append(diag)
                    log(f"  [Raio-X] {diag}", "ERR")
                except: pass

        error_summary = "\n".join(error_diagnostics) or "\n".join(build_output.splitlines()[:5])
        
        # Skill: Registro de Diagnóstico para análise posterior
        exec_logger.log_detailed_diagnostic(phase, file_name, build_output, error_diagnostics)

        # Skill: Reforço de Import com Dicionário Global
        _live(active_skill="Project Dictionary")
        if "cannot find symbol" in error_summary:
            from java.dictionary import build_project_dictionary
            proj_map = None
            if cache is not None:
                proj_map = cache.get_project_dict()
            if proj_map is None:
                proj_map = build_project_dictionary(repo_path)
                if cache is not None:
                    cache.set_project_dict(proj_map)
            error_summary += f"\n\n{proj_map}\n\nDICA: Use o mapa acima para adicionar o IMPORT correto."
        
        corrected_code = call_ai_with_correction(
            original     = original,
            rules        = rules,
            mode         = mode,
            file_name    = file_name,
            file_path    = file,
            bad_output   = new_code,
            error_reason = f"Falha de Compilação Maven:\n{error_summary}",
            phase        = phase
        )

        _live(active_skill="Auto-Cura")
        if corrected_code:
            write_file(file, corrected_code)
            success, _ = maven_test(repo_path)
            if success:
                log(f"  {file_name}: Auto-Cura bem sucedida! ✓", "OK")
                new_code = corrected_code
            else:
                log(f"  {file_name}: Auto-Cura falhou.", "ERR")
                write_file(file, original)
                get_failed_tracker().record(file, phase, "build quebrou (auto-cura falhou)")
                return False
        else:
            write_file(file, original)
            log(f"  {file_name} REVERTIDO: build quebrou e IA não corrigiu", "WARN")
            get_failed_tracker().record(file, phase, "build quebrou")
            return False

    reporter.record_changed(phase, file_name, file, original, new_code)
    if exec_logger:
        exec_logger.log_file_accepted(phase, file_name, "+refactor")
    log(f"  {file_name} REFATORADO ✓", "OK")
    return True


# ---------------------------------------------------------------------------
# Refatoração — método a método
# ---------------------------------------------------------------------------

def _refactor_by_method(file: str, original: str, rules: str,
                         repo_path: str, phase: str,
                         reporter: PhaseReporter,
                         exec_logger: ExecutionLogger | None,
                         cache=None,
                         semantic_mem=None) -> bool:
    file_name = os.path.basename(file)
    mode      = _mode_for(file)

    header  = extract_class_header(original)
    methods = get_processable_methods(original)

    if not methods:
        log(f"  {file_name}: nenhum método extraível — tentando arquivo inteiro")
        return _refactor_whole_file(file, original, rules, repo_path, phase,
                                    reporter, exec_logger, cache=cache,
                                    semantic_mem=semantic_mem)

    log(f"  {file_name}: {len(methods)} métodos a processar")

    current_code    = original
    methods_changed = 0
    methods_failed  = 0

    for method in methods:
        log(f"    → {method.name}() [{len(method.full_text.splitlines())}L]")

        context = build_method_context(header, method)

        ai_response, reason = _generate_and_validate(
            original     = context,
            rules        = rules,
            mode         = mode,
            file_name    = file_name,
            file_path    = file,
            phase        = phase,
            cache        = cache,
            semantic_mem = semantic_mem,
        )

        if not ai_response:
            log(f"      {method.name}: {reason}", "WARN")
            methods_failed += 1
            continue

        new_method_text = extract_refactored_method(ai_response, method)

        if not new_method_text:
            log(f"      {method.name}: método não encontrado na resposta", "WARN")
            methods_failed += 1
            continue

        if new_method_text.strip() == method.full_text.strip():
            log(f"      {method.name}: sem alteração")
            continue

        updated_code = replace_method_in_file(current_code, method, new_method_text)
        valid_full, reason_full = is_valid_java(current_code, updated_code)
        if not valid_full:
            log(f"      {method.name}: inválido após substituição: {reason_full}", "WARN")
            methods_failed += 1
            continue

        current_code = updated_code
        methods_changed += 1
        log(f"      {method.name}: OK ✓")

    if methods_changed == 0:
        if methods_failed > 0:
            get_failed_tracker().record(
                file, phase, f"todos os {methods_failed} métodos falharam"
            )
        log(f"  {file_name}: nenhum método alterado", "WARN")
        reporter.record_skipped(phase, file_name, "nenhum método alterado")
        return False

    write_file(file, current_code)
    success, build_out = maven_test(repo_path)

    if not success:
        write_file(file, original)
        log(f"  {file_name} REVERTIDO após {methods_changed} métodos", "WARN")
        get_failed_tracker().record(file, phase, "build quebrou após refatoração")
        if exec_logger:
            exec_logger.log_file_reverted(phase, file_name, error_type=_categorize_build_error(build_out)[:80])
        reporter.record_build_failed(phase, file_name)
        return False

    reporter.record_changed(phase, file_name, file, original, current_code)
    if exec_logger:
        exec_logger.log_file_accepted(phase, file_name, f"+{methods_changed}methods")
    log(f"  {file_name} REFATORADO ✓ ({methods_changed} métodos)", "OK")
    return True


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

def refactor_file(file: str, rules: str, repo_path: str,
                  phase: str, reporter: PhaseReporter,
                  exec_logger: ExecutionLogger | None = None,
                  cache=None,
                  semantic_mem=None) -> bool:
    file_name = os.path.basename(file)

    # Phase skip: se já processamos este arquivo nesta fase neste run, pula
    if cache is not None:
        phase_name = phase.split("/")[-1].replace(".md", "")
        if cache.is_phase_done(file, phase_name):
            log(f"  {file_name}: cache hit — {phase_name} já aplicada neste run", "OK")
            reporter.record_skipped(phase, file_name, f"cache: {phase_name} já aplicada")
            return False

    # Melhoria 4: pular arquivos com histórico de falhas de build repetidas
    build_fails = get_failed_tracker().get_build_failure_count(file)
    if build_fails >= MAX_BUILD_FAILURES:
        log(f"  {file_name}: {build_fails}x build quebrou em fases anteriores — pulando", "WARN")
        if exec_logger:
            exec_logger.log_file_skipped(phase, file_name,
                                         f"Histórico: {build_fails}x build quebrou")
        reporter.record_skipped(phase, file_name,
                                f"Histórico de falhas ({build_fails}x build quebrou)")
        return False

    log(f"Processando [{_mode_for(file)}]: {file_name}")

    if exec_logger:
        exec_logger.log_file_processing(phase, file_name, "unknown", "unknown")

    original = read_file(file)

    # Melhoria 3: passa phase para considerar padrões de skip por fase
    skip, reason = should_skip(file, original, phase)
    if skip:
        log(f"  {file_name} PULADO: {reason}", "WARN")
        if exec_logger:
            exec_logger.log_file_skipped(phase, file_name, reason)
        reporter.record_skipped(phase, file_name, reason)
        return False

    if is_large_file(original, LARGE_FILE_THRESHOLD):
        log(f"  {file_name}: arquivo grande → processamento por método")
        success = _refactor_by_method(file, original, rules, repo_path, phase,
                                      reporter, exec_logger, cache=cache,
                                      semantic_mem=semantic_mem)
    else:
        success = _refactor_whole_file(file, original, rules, repo_path, phase,
                                       reporter, exec_logger, cache=cache,
                                       semantic_mem=semantic_mem)

    if semantic_mem is not None:
        phase_label = phase.split("/")[-1].replace(".md", "")
        file_type   = "test" if "/test/" in file.replace("\\", "/") else "src"
        if success:
            semantic_mem.store(
                f"SUCCESS: phase={phase_label} file={file_name} type={file_type} — refactoring accepted and build passed"
            )
        else:
            semantic_mem.store(
                f"FAILURE: phase={phase_label} file={file_name} type={file_type} — refactoring rejected or build failed"
            )

    if cache is not None:
        phase_name = phase.split("/")[-1].replace(".md", "")
        cache.mark_phase_done(file, phase_name)

    return success


# ---------------------------------------------------------------------------
# M7 — Detecção de field injection sem construtor (deferred skip)
# ---------------------------------------------------------------------------

_RE_AUTOWIRED_FIELD = re.compile(
    r'@Autowired\s+(?:private\s+)?(?:final\s+)?(?:\w+)\s+\w+\s*;',
    re.MULTILINE,
)
_RE_EXPLICIT_CONSTRUCTOR = re.compile(
    r'(?:public|protected)\s+\w+\s*\([^)]+\)\s*\{',
    re.MULTILINE,
)


def _has_field_injection_without_constructor(code: str) -> bool:
    """Detecta classes com @Autowired em campo mas sem construtor explícito.
    Essas classes não podem ser testadas unitariamente sem Spring context
    até que a fase 11 (SOLID DIP) converta para constructor injection."""
    has_field_injection = bool(_RE_AUTOWIRED_FIELD.search(code))
    has_constructor = bool(_RE_EXPLICIT_CONSTRUCTOR.search(code))
    return has_field_injection and not has_constructor


# ---------------------------------------------------------------------------
# M8 — Extração de setup de teste existente para reuso no complement
# ---------------------------------------------------------------------------

_RE_MOCK_FIELD   = re.compile(r'@Mock\b.*?\n\s+\w[\w<>, ]*\s+\w+\s*;', re.DOTALL)
_RE_INJECT_FIELD = re.compile(r'@InjectMocks\b.*?\n\s+\w[\w<>, ]*\s+\w+\s*;', re.DOTALL)
_RE_SPY_FIELD    = re.compile(r'@Spy\b.*?\n\s+\w[\w<>, ]*\s+\w+\s*;', re.DOTALL)
_RE_FIELD_DECL   = re.compile(r'(?:private|protected)\s+(?:final\s+)?[\w<>, ]+\s+(\w+)\s*(?:=|;)', re.MULTILINE)

# Todas as anotações de ciclo de vida JUnit 4 e JUnit 5
_LIFECYCLE_ANNOTATIONS = [
    "@BeforeAll",   # JUnit 5 — estático, executa uma vez antes de todos os testes
    "@BeforeEach",  # JUnit 5 — executa antes de cada @Test
    "@AfterEach",   # JUnit 5 — executa após cada @Test
    "@AfterAll",    # JUnit 5 — estático, executa uma vez após todos os testes
    "@Before",      # JUnit 4 — equivalente a @BeforeEach
    "@After",       # JUnit 4 — equivalente a @AfterEach
    "@BeforeClass", # JUnit 4 — equivalente a @BeforeAll
    "@AfterClass",  # JUnit 4 — equivalente a @AfterAll
]

def _build_lifecycle_pattern(annotation: str) -> re.Pattern:
    """Regex que captura método anotado com qualquer anotação de ciclo de vida."""
    ann = re.escape(annotation)
    return re.compile(
        ann + r'\s+(?:(?:public|protected|static|void|\s)+\w+\s*\([^)]*\)\s*\{)'
        r'(?:[^{}]|\{[^{}]*\})*\}',
        re.DOTALL,
    )

_LIFECYCLE_RE: dict[str, re.Pattern] = {
    ann: _build_lifecycle_pattern(ann) for ann in _LIFECYCLE_ANNOTATIONS
}


def _extract_test_setup(existing_test: str) -> str:
    """Extrai mocks, injects, spies, métodos de ciclo de vida e campos do teste existente.

    Retorna um bloco estruturado para injetar no prompt de complementação (M8),
    indicando ao LLM exatamente o que já existe e o que é READ-ONLY."""
    sections: list[str] = []

    # --- Campos de mock / injeção ---
    mocks   = _RE_MOCK_FIELD.findall(existing_test)
    injects = _RE_INJECT_FIELD.findall(existing_test)
    spies   = _RE_SPY_FIELD.findall(existing_test)
    fields  = _RE_FIELD_DECL.findall(existing_test)

    if mocks or injects or spies:
        decls = "\n".join(f"    {d.strip()}" for d in mocks + injects + spies)
        sections.append(f"ALREADY DECLARED FIELDS (DO NOT redeclare these):\n{decls}")

    if fields:
        sections.append(
            f"ALL FIELD NAMES IN THE CLASS: {', '.join(fields)}\n"
            "  → Use these exact names in new tests — never create new field declarations."
        )

    # --- Métodos de ciclo de vida existentes ---
    found_lifecycle: list[tuple[str, str]] = []
    for ann in _LIFECYCLE_ANNOTATIONS:
        matches = _LIFECYCLE_RE[ann].findall(existing_test)
        for m in matches:
            found_lifecycle.append((ann, m.strip()))

    if found_lifecycle:
        lifecycle_lines: list[str] = []
        present_annotations = {ann for ann, _ in found_lifecycle}

        for ann, body in found_lifecycle:
            lifecycle_lines.append(
                f"{ann} (READ-ONLY — already present, DO NOT add another {ann}):\n"
                f"  {body[:300]}{'...' if len(body) > 300 else ''}"
            )

        # Regra dinâmica: lista só as anotações AUSENTES como permitidas
        absent = [a for a in _LIFECYCLE_ANNOTATIONS if a not in present_annotations]
        absent_note = (
            f"  → Lifecycle annotations NOT YET present (allowed to create if truly needed): "
            f"{', '.join(absent)}"
        ) if absent else "  → All common lifecycle annotations are already present."

        sections.append(
            "EXISTING LIFECYCLE METHODS (READ-ONLY — see rules below):\n"
            + "\n\n".join(lifecycle_lines)
            + f"\n\n{absent_note}"
        )

    if not sections:
        return ""

    return (
        "\n### EXISTING TEST SETUP — MUST REUSE, NEVER REDECLARE\n"
        + "\n\n".join(sections)
        + "\n"
    )


# ---------------------------------------------------------------------------
# Geração de testes
# ---------------------------------------------------------------------------

def _build_active_rules(
    original: str,
    _prod_imports: list[str],
    _self_import: str | None,
    _test_cls_name: str,
    _test_pkg: str,
    complement_mode: bool,
    rules: str,
) -> str:
    """Build the active_rules string for LLM-based test generation.

    Centralises all conditional rule blocks so they can be unit-tested independently.
    complement_mode path is NOT handled here — caller builds that branch directly.
    Returns the assembled rules string (non-complement path only).
    """
    _mandatory_prefix = (
        f"### TEST CLASS — MANDATORY NAME AND PACKAGE (HIGHEST PRIORITY — APPLY BEFORE ANYTHING ELSE)\n"
        f"- The test class declaration MUST be EXACTLY: `public class {_test_cls_name} {{`\n"
        f"- NEVER rename, shorten, or alter this class name in any way.\n"
    )
    if _test_pkg:
        _mandatory_prefix += (
            f"- The package declaration MUST be EXACTLY: `package {_test_pkg};`\n"
            f"- NEVER abbreviate `{_test_pkg}` — copy the FULL package path verbatim.\n"
            f"  (Common mistake: writing `{'.'.join(_test_pkg.split('.')[:3])}.*` instead of the full path)\n"
            f"- NEVER use com.example.*, com.test.*, com.demo.*, or any invented package.\n"
        )
    _mandatory_prefix += "\n\n"

    active_rules = _mandatory_prefix + rules

    # State mandatory-ness once globally — individual block titles omit the suffix.
    active_rules += (
        "\n\n### ALL `###` BLOCKS BELOW ARE MANDATORY — VIOLATION CAUSES BUILD OR RUNTIME FAILURE\n"
    )

    # C21: record semantics — only when class is a Java record
    if re.search(r'\brecord\s+\w+', original):
        active_rules += (
            "\n\n### JAVA RECORD SEMANTICS (the class under test is a Java record)\n"
            "Records auto-generate equals/hashCode based on all component fields, "
            "toString() returning 'ClassName[field=val]', "
            "and a canonical constructor requiring all declared fields — no default no-arg constructor exists.\n"
            "NEVER assert toString() returns only the raw value; NEVER call new RecordName() without all required arguments.\n"
            "Two records with the same field values are equal via assertEquals without extra setup.\n"
        )

    # Merged IMPORTS block: IMPORTS PRESENT + SELF-IMPORT + IMPORT PROHIBITION (blocks 5, 6, 12)
    if _prod_imports:
        _imports_block = (
            "\n\n### IMPORTS\n"
            "Use ONLY these import paths — do NOT hallucinate any other path for project types:\n"
            + "\n".join(_prod_imports) + "\n"
        )
        if _self_import:
            _imports_block += (
                f"SELF-IMPORT (always include this line in the test file):\n"
                f"  {_self_import}\n"
            )
        _imports_block += (
            "For project-specific types: derive paths ONLY from the list above.\n"
            "If a type is not listed and is not a standard JDK/Mockito/JUnit type, do NOT import it.\n"
        )
        active_rules += _imports_block

    # C: BigDecimal construction — prevents compile failure
    if re.search(r'\bBigDecimal\b', original):
        active_rules += (
            "\n\n### BIGDECIMAL CONSTRUCTION\n"
            "CORRECT: new BigDecimal(\"100.00\")  or  BigDecimal.valueOf(100)\n"
            "WRONG:   \"100.00\"  — String literal, incompatible type, will NOT compile.\n"
            "Apply to constructors, setters, method calls, and mock return values.\n"
        )

    # S4: setter/getter pattern — class has parameterized constructor
    if re.search(r'public\s+\w+\s*\([^)]{3,}\)', original):
        active_rules += (
            "\n\n### SETTER/GETTER TEST PATTERN\n"
            "setUp() initializes the object with NON-NULL values via the parameterized constructor.\n"
            "CORRECT: call setX(newValue), then assertEquals(newValue, object.getX())\n"
            "WRONG:   assertNull(object.getX()) before calling setX() — setUp already set a non-null value.\n"
        )

    # F: java.sql.Timestamp construction — prevents runtime failure
    if re.search(r'\bTimestamp\b', original) and 'import java.sql.Timestamp' in original:
        active_rules += (
            "\n\n### JAVA SQL TIMESTAMP CONSTRUCTION\n"
            "CORRECT: Timestamp.valueOf(\"2023-01-15 10:00:00\")  — space between date and time.\n"
            "WRONG:   Timestamp.valueOf(\"2023-01-15T10:00:00\")  — T is ISO format, NOT SQL format.\n"
            "Format MUST be \"yyyy-mm-dd hh:mm:ss\"; NEVER ISO-8601 (with 'T') — throws IllegalArgumentException.\n"
        )

    # C1: field injection via @Autowired — mock setup
    _autowired_fields = re.findall(
        r'@Autowired\s+(?:private\s+)?(\w[\w<>, ]*?\s+\w+)\s*;',
        original,
    )
    if _autowired_fields:
        _prod_import_map: dict[str, str] = {}
        for _imp in _prod_imports:
            _m = re.match(r'import\s+([\w.]+);', _imp)
            if _m:
                _prod_import_map[_m.group(1).split(".")[-1]] = _imp
        _mock_lines: list[str] = []
        for _field in _autowired_fields:
            _type_name = _field.split()[0]
            _mock_lines.append(f"  @Mock  {_field};")
            if "<" not in _type_name:
                _resolved = _prod_import_map.get(_type_name) or _JDK_IMPORT_MAP.get(_type_name)
                if _resolved:
                    _mock_lines.append(f"  // Required import: {_resolved}")
        active_rules += (
            "\n\n### FIELD INJECTION — MOCK SETUP\n"
            "Use @ExtendWith(MockitoExtension.class) + @InjectMocks for the class under test.\n"
            "Declare one @Mock per injected dependency:\n"
            + "\n".join(_mock_lines) + "\n"
            "@InjectMocks handles injection automatically — do NOT write a constructor or @BeforeEach that manually injects.\n"
        )

    # M2: @Document import for MongoDB
    if re.search(r'@Document\b', original):
        active_rules += (
            "\n\n### MONGODB @Document IMPORT\n"
            "MUST add to test file: import org.springframework.data.mongodb.core.mapping.Document;\n"
            "Do NOT omit it — the class will not compile without it.\n"
        )

    # S3: null assertions — prevents enum-vs-null failures
    active_rules += (
        "\n\n### NULL ASSERTIONS\n"
        "When input for a field is null, the method may return null — use assertNull(result.getField()).\n"
        "NEVER assertEquals(EnumValue, result.getField()) when input was null.\n"
        "NEVER invent a non-null expected value unless the production code explicitly defines a non-null default.\n"
    )

    return active_rules


def generate_tests(repo_path: str, phase: str, rules: str,
                   reporter: PhaseReporter,
                   exec_logger: ExecutionLogger | None = None) -> bool:
    from core.utils import load_skill as _load_skill
    _repair_strategy = _load_skill("java-tdd-unit-test", section="Repair Strategy") or (
        "Fix ONLY the error reported. Do NOT rewrite the test class. "
        "Preserve passing tests. Use only symbols from DEPENDENCY CONTEXT."
    )
    _live(active_skill="java-tdd-unit-test")

    any_changed = False
    main_files  = get_java_files(repo_path, tests=False)

    # Opção 6: project-wide import map, computed once per generate_tests call.
    _project_imports = build_project_imports(repo_path)

    for main_file in main_files:
        original  = read_file(main_file)
        file_name = os.path.basename(main_file)

        skip, _ = should_skip(main_file, original)
        if skip:
            continue

        # S2 (corrigido): pula apenas interfaces puras — @Document/@Entity ainda têm
        # getters/setters/construtores que precisam de cobertura de testes.
        # should_skip() já filtra interfaces JPA repositories e @SpringBootApplication.
        # Filtro adicional: interfaces não-repository (sem herança de Repository).
        if re.search(r'(?:public\s+)?interface\s+\w+', original) and \
                not re.search(r'extends\s+\w*Repository\w*\s*<', original):
            # Interface pura sem implementação — should_skip pode não ter capturado
            # (ex: service interfaces sem "Repository" no nome)
            continue

        test_path = _test_path_for(main_file, repo_path)
        if not test_path:
            continue

        test_name = os.path.basename(test_path)

        # M6: skip permanente — arquivo falhou em 3+ runs consecutivos
        if get_failed_tracker().is_permanent_skip(test_path, phase):
            log(f"  {test_name}: SKIP PERMANENTE (falhas recorrentes em runs anteriores)", "WARN")
            if exec_logger:
                exec_logger.log_file_skipped(phase, test_name, "permanent_skip")
            continue

        # M7: deferred skip — class de produção com field injection (@Autowired sem construtor)
        if _has_field_injection_without_constructor(original):
            # S5 (corrigido): desbloqueia se solid-dip nunca vai processar este arquivo.
            # Dois casos em que solid-dip não vai agir:
            #   a) permanent_skip: já tentou 3x e falhou
            #   b) no_new_instantiation: pré-filtro elimina antes do LLM (nunca acumula falhas)
            _dip_permanent   = get_failed_tracker().is_permanent_skip(main_file, "solid-dip")
            _dip_prefiltered = not bool(re.search(r'\bnew\s+[A-Z]\w+\s*\(', original))
            if _dip_permanent or _dip_prefiltered:
                log(
                    f"  {test_name}: solid-dip não aplicável "
                    f"({'permanent_skip' if _dip_permanent else 'no_new_instantiation'}) "
                    f"— gerando teste com @InjectMocks",
                    "WARN"
                )
                # Não dá continue — Mockito suporta field injection via @InjectMocks
            else:
                log(
                    f"  {test_name}: DEFERRED — field injection detectada "
                    f"(testar após fase 11 SOLID DIP)", "WARN"
                )
                if exec_logger:
                    exec_logger.log_file_skipped(phase, test_name, "deferred_field_injection")
                reporter.record_skipped(phase, test_name, "deferred: field injection sem construtor")
                continue

        # M8: complementação de testes existentes com cobertura parcial
        complement_mode   = False
        existing_test_code = ""
        existing_coverage  = 0.0

        if os.path.exists(test_path):
            _, _, existing_coverage, missed_existing = maven_test_with_coverage(repo_path, file_name)
            if existing_coverage >= 90.0 or not missed_existing:
                continue  # cobertura já adequada — nada a fazer
            complement_mode    = True
            existing_test_code = read_file(test_path)
            log(
                f"  Complementando: {test_name} "
                f"(cobertura atual {existing_coverage:.1f}% — linhas: {missed_existing})"
            )
        else:
            log(f"  Gerando teste: {test_name}")

        # Limpa modelos marcados como OOM entre arquivos para evitar cascade de falhas
        # Se Ollama estava fisicamente OOM, aguarda recuperação antes de continuar
        from ai.model import _OOM_MODELS, wait_for_ollama_recovery
        if _OOM_MODELS:
            _OOM_MODELS.clear()
            if not wait_for_ollama_recovery():
                log(f"  {test_name}: Ollama não recuperou — pulando", "WARN")
                get_failed_tracker().record(test_path, phase, "Ollama OOM — serviço não recuperou")
                if exec_logger:
                    exec_logger.log_ai_failure(phase, test_name, "ollama-oom", "Serviço não recuperou após cascade de OOM")
                reporter.record_skipped(phase, test_name, "Ollama OOM")
                continue
        else:
            _OOM_MODELS.clear()

        file_mode = "complement" if complement_mode else "new"
        if exec_logger:
            exec_logger.log_file_processing(phase, test_name, "test", file_mode)

        from java.context import get_dependency_context
        try:
            test_dep_context = get_dependency_context(original, repo_path)
        except Exception:
            test_dep_context = ""

        # C3: calcula restrição de nome/package ANTES de construir active_rules — inserida no INÍCIO
        _test_cls_name = test_name.replace(".java", "")
        _test_pkg = ""
        try:
            _norm_tp = test_path.replace("\\", "/")
            _java_idx = _norm_tp.find("/test/java/")
            if _java_idx >= 0:
                _pkg_path = _norm_tp[_java_idx + len("/test/java/"):]
                _pkg_path = "/".join(_pkg_path.split("/")[:-1])
                _test_pkg = _pkg_path.replace("/", ".")
        except Exception:
            pass

        # P0: data holders são testados deterministicamente — sem LLM, sem repair loop.
        if not complement_mode:
            from java.data_holder_test_gen import is_pure_data_holder, generate_data_holder_test
            if is_pure_data_holder(original):
                _dh_test = generate_data_holder_test(
                    original, test_name.replace(".java", ""), _test_pkg,
                    dep_context=test_dep_context,
                )
                if _dh_test:
                    os.makedirs(os.path.dirname(test_path), exist_ok=True)
                    write_file(test_path, _dh_test)
                    _dh_ok, _dh_out, _dh_cov, _ = maven_test_with_coverage(repo_path, file_name)
                    if _dh_ok:
                        log(f"  {test_name} CRIADO (determinístico, sem LLM) ✓", "OK")
                        reporter.record_changed(phase, test_name, test_path, "", _dh_test)
                        if exec_logger:
                            exec_logger.log_file_accepted(phase, test_name, "+test")
                            exec_logger.log_model_used(phase, test_name, "deterministic", "ACCEPTED")
                        any_changed = True
                        from git_utils.repo import commit_single_file
                        commit_single_file(repo_path, test_path,
                                            f"test: add {test_name} (deterministic)")
                        continue
                    log(f"  {test_name}: gerador determinístico falhou no build — fallback para LLM", "WARN")
                    os.remove(test_path)

        _prod_imports = re.findall(r'^import\s+[\w.]+;', original, re.MULTILINE)

        # F1: self-import — a classe sob teste não importa a si mesma, mas o teste precisa importá-la.
        # Derivamos o import exato do package da classe de produção + nome do arquivo.
        _prod_pkg_m = re.search(r'^package\s+([\w.]+);', original, re.MULTILINE)
        _prod_cls_name = file_name.replace(".java", "")
        _self_import: str | None = (
            f"import {_prod_pkg_m.group(1)}.{_prod_cls_name};" if _prod_pkg_m else None
        )
        # Lista ampliada para S1: prod_imports + self-import (garante que MerchantDocument,
        # TransactionController etc. sejam sempre injetados mesmo após reparos do LLM)
        _s1_imports = list(_prod_imports)
        if _self_import:
            _s1_imports.append(_self_import)

        # M8: regras de complementação — LLM recebe teste existente + setup explícito + lacunas
        if complement_mode:
            _mandatory_prefix = (
                f"### TEST CLASS — MANDATORY NAME AND PACKAGE (HIGHEST PRIORITY — APPLY BEFORE ANYTHING ELSE)\n"
                f"- The test class declaration MUST be EXACTLY: `public class {_test_cls_name} {{`\n"
                f"- NEVER rename, shorten, or alter this class name in any way.\n"
            )
            if _test_pkg:
                _mandatory_prefix += (
                    f"- The package declaration MUST be EXACTLY: `package {_test_pkg};`\n"
                    f"- NEVER abbreviate `{_test_pkg}` — copy the FULL package path verbatim.\n"
                    f"  (Common mistake: writing `{'.'.join(_test_pkg.split('.')[:3])}.*` instead of the full path)\n"
                    f"- NEVER use com.example.*, com.test.*, com.demo.*, or any invented package.\n"
                )
            _mandatory_prefix += "\n\n"
            setup_block = _extract_test_setup(existing_test_code)
            active_rules = (
                f"{_mandatory_prefix}{rules}\n\n"
                "### EXISTING TEST FILE (DO NOT MODIFY OR REMOVE ANY EXISTING TEST)\n"
                f"```java\n{existing_test_code}\n```\n"
                f"{setup_block}\n"
                "### TASK: COMPLEMENT — DO NOT REWRITE\n"
                f"Current coverage: {existing_coverage:.1f}% (target: 90%)\n"
                f"Uncovered lines: {missed_existing}\n\n"
                "ADD new @Test methods to cover the uncovered lines above.\n"
                "RULES for new tests (MANDATORY — violation causes compilation failure):\n"
                "  1. NEVER redeclare @Mock, @InjectMocks, @Spy, or any private field — they already exist.\n"
                "  2. Lifecycle methods (@BeforeEach, @AfterEach, @BeforeAll, @AfterAll, @Before, @After, etc.):\n"
                "     → If one ALREADY EXISTS (shown in EXISTING TEST SETUP): DO NOT add another of the same type.\n"
                "       The existing one already runs automatically — rely on it as-is.\n"
                "     → If extra per-test setup is needed beyond what already exists:\n"
                "         a) Initialize extra objects as LOCAL VARIABLES inside the @Test method.\n"
                "         b) OR create a private helper method called from the tests that need it.\n"
                "         c) NEVER modify or extend the body of an existing lifecycle method.\n"
                "     → If a lifecycle annotation is NOT YET present (shown as 'allowed to create'):\n"
                "         you MAY create it, but only if genuinely needed by multiple new tests.\n"
                "  3. Use ONLY the field names listed in EXISTING TEST SETUP — never declare new fields.\n"
                "  4. NEVER remove, rename, or modify any existing @Test method or its assertions.\n"
                "Return the COMPLETE test file: all existing content unchanged + new @Test methods at the end."
            )
        else:
            # Non-complement path: use consolidated helper
            active_rules = _build_active_rules(
                original       = original,
                _prod_imports  = _prod_imports,
                _self_import   = _self_import,
                _test_cls_name = _test_cls_name,
                _test_pkg      = _test_pkg,
                complement_mode = False,
                rules          = rules,
            )

        file_start_time = time.time()

        test_code, reason = _generate_and_validate(
            original  = original,
            rules     = active_rules,
            mode      = "test",
            file_name = test_name,
            file_path = test_path,
            phase     = phase,
        )

        if not test_code:
            log(f"  {test_name}: {reason}", "WARN")
            get_failed_tracker().record(test_path, phase, reason)
            if exec_logger:
                exec_logger.log_ai_failure(phase, test_name, "all-agents", reason)
            reporter.record_skipped(phase, test_name, reason)
            continue

        # S1: injeta imports ausentes antes de gravar no disco (inclui self-import via _s1_imports)
        test_code = _auto_inject_missing_imports(test_code, _s1_imports, project_imports=_project_imports)
        # Fix F: corrige chamadas de construtor com número errado de argumentos (pre-Maven)
        test_code = _fix_constructor_calls(test_code, test_dep_context)

        os.makedirs(os.path.dirname(test_path), exist_ok=True)
        write_file(test_path, test_code)

        success, combined_out, coverage, missed_lines = maven_test_with_coverage(repo_path, file_name)

        # M8: no modo complement, também passar o active_rules com o teste existente para os reparos

        # Ciclo de reparo estruturado — timeout já iniciado antes da geração
        timed_out = False
        timed_out = False
        error_history: list[str] = []  # acumula erros entre tentativas

        for attempt in range(MAX_VALIDATOR_RETRIES):
            elapsed = time.time() - file_start_time
            if elapsed > MAX_TEST_FILE_TIMEOUT_S:
                log(f"  [{test_name}] timeout de {MAX_TEST_FILE_TIMEOUT_S // 60}min atingido — encerrando reparos", "WARN")
                timed_out = True
                break

            if success and coverage >= 90.0:
                log(f"  [{test_name}] Cobertura atingida: {coverage:.2f}% ✓", "OK")
                break

            if not success:
                repair_hint = _categorize_build_error(combined_out, _prod_imports)
                if _is_irrecoverable_hallucination(
                    repair_hint, _prod_imports,
                    test_code=test_code,
                    project_imports=_project_imports,
                ):
                    log(
                        f"  [{test_name}] Falha irrecuperável detectada (alucinação de símbolo) — pulando reparos restantes",
                        "WARN",
                    )
                    break
                error_history.append(f"Attempt {attempt + 1}: {repair_hint}")
                log(f"  [{test_name}] Reparo {attempt + 1}/{MAX_VALIDATOR_RETRIES}: {repair_hint[:80]}...", "WARN")
                _patched = _try_surgical_patch(test_code, combined_out)
                if _patched is not None:
                    log(f"  [{test_name}] Patch cirúrgico aplicado — sem LLM", "OK")
                    write_file(test_path, _patched)
                    test_code = _patched
                    success, combined_out, coverage, missed_lines = \
                        maven_test_with_coverage(repo_path, file_name)
                    if success:
                        continue
                    # patch didn't fix it — fall through to LLM repair as normal
                history_block = (
                    f"REPAIR HISTORY (do NOT repeat these mistakes):\n"
                    + "\n".join(error_history) + "\n\n"
                ) if len(error_history) > 1 else ""
                error_msg = (
                    f"{_repair_strategy}\n\n"
                    f"{history_block}"
                    f"CURRENT ERROR: {repair_hint}\n\n"
                    f"MAVEN ERROR:\n{combined_out[-2000:]}"
                )
            else:
                log(f"  [{test_name}] Cobertura baixa: {coverage:.2f}%. Expandindo cobertura...", "WARN")
                error_msg = (
                    f"Tests passed but coverage is {coverage:.2f}% (minimum required: 90%).\n"
                    f"Add test methods to cover the following lines: {missed_lines}.\n"
                    "Do NOT remove existing tests — only add new @Test methods."
                )

            corrected_test = call_ai_with_correction(
                original=original, rules=active_rules, mode="test",
                file_name=test_name, file_path=test_path,
                bad_output=test_code, error_reason=error_msg, phase=phase,
                dep_context=test_dep_context,
            )

            if not corrected_test:
                log(f"  [{test_name}] LLM não gerou correção — encerrando reparos", "WARN")
                break

            # C2: valida nome da classe ANTES de escrever no disco
            _expected_cls = test_name.replace(".java", "")
            if f"class {_expected_cls}" not in corrected_test:
                _cls_found = re.search(r'(?:public\s+)?class\s+(\w+)', corrected_test)
                _found_name = _cls_found.group(1) if _cls_found else "UNKNOWN"
                combined_out = (
                    f"CLASS NAME CRITICAL ERROR: You generated `public class {_found_name}` "
                    f"but the file MUST be named `{_expected_cls}`.\n"
                    f"RENAME the class declaration to EXACTLY: `public class {_expected_cls} {{`\n"
                    "Java law: the public class name MUST equal the filename. No exceptions.\n"
                    "Do NOT abbreviate, shorten, or change the class name in any way.\n\n"
                ) + combined_out[-1000:]
                success = False
                continue  # não escreve o arquivo — força novo reparo com erro de classe

            # F2: valida package declaration ANTES de escrever no disco
            # O LLM pode preservar o nome da classe mas trocar o package (com.example.model etc.)
            if _test_pkg and f"package {_test_pkg};" not in corrected_test:
                _pkg_found = re.search(r'^package\s+([\w.]+);', corrected_test, re.MULTILINE)
                _found_pkg = _pkg_found.group(1) if _pkg_found else "UNKNOWN"
                combined_out = (
                    f"PACKAGE CRITICAL ERROR: You declared `package {_found_pkg};` "
                    f"but the file MUST use `package {_test_pkg};`.\n"
                    f"REPLACE the package declaration to EXACTLY: `package {_test_pkg};`\n"
                    f"NEVER abbreviate or invent a package — copy `{_test_pkg}` verbatim.\n"
                    f"Common mistake: writing `com.example.*` or shortened path instead of the full package.\n\n"
                ) + combined_out[-1000:]
                success = False
                continue  # não escreve o arquivo — força novo reparo com erro de package

            # S1: injeta imports ausentes no código corrigido antes de gravar (inclui self-import)
            corrected_test = _auto_inject_missing_imports(corrected_test, _s1_imports, project_imports=_project_imports)
            # Fix F: corrige chamadas de construtor com número errado de argumentos (pre-Maven)
            corrected_test = _fix_constructor_calls(corrected_test, test_dep_context)
            write_file(test_path, corrected_test)
            test_code = corrected_test
            success, combined_out, coverage, missed_lines = maven_test_with_coverage(repo_path, file_name)

        # Após todos os reparos: aceita se compilou, reverte se não
        if not success:
            timeout_note = " (timeout)" if timed_out else ""
            err_reason = f"build quebrou após {MAX_VALIDATOR_RETRIES} reparos{timeout_note}"
            final_error_type = _categorize_build_error(combined_out)[:150]
            if complement_mode:
                # M8: restaura teste original em vez de apagar
                write_file(test_path, existing_test_code)
                log(f"  {test_name}: {err_reason} — complementação revertida", "WARN")
            else:
                os.remove(test_path)
                log(f"  {test_name}: {err_reason} — arquivo removido", "WARN")
            get_failed_tracker().record(test_path, phase, err_reason,
                                        stack_trace=combined_out)
            if exec_logger:
                exec_logger.log_file_reverted(phase, test_name, error_type=final_error_type)
            reporter.record_build_failed(phase, test_name)
            continue

        from ai.model import get_last_model as _get_model
        change_type = "+complement" if complement_mode else "+test"
        action_label = "COMPLEMENTADO" if complement_mode else "CRIADO"
        reporter.record_changed(phase, test_name, test_path,
                                existing_test_code if complement_mode else "", test_code)
        if exec_logger:
            exec_logger.log_file_accepted(phase, test_name, change_type)
            exec_logger.log_model_used(phase, test_name, _get_model(), "ACCEPTED")
        log(f"  {test_name} {action_label} ✓", "OK")
        any_changed = True
        from git_utils.repo import commit_single_file
        commit_single_file(repo_path, test_path, f"test: add {test_name}")

    return any_changed
def _attempt_global_sync(build_output: str, repo_path: str, rules: str, phase: str, trigger_file_content: str):
    """
    Skill de Sincronia Contextual 2.0: Usa o código recém-refatorado como
    referência para consertar as dependências em outros arquivos.
    """
    error_lines = [l for l in build_output.splitlines() if "cannot find symbol" in l or "does not override" in l]
    
    for line in error_lines[:3]:
        symbol, failing_file_abs = _extract_missing_symbol_and_target(line)
        if not failing_file_abs: continue
        
        if not os.path.exists(failing_file_abs): continue
        
        failing_file_name = os.path.basename(failing_file_abs)
        failing_file_rel = os.path.relpath(failing_file_abs, repo_path)
        log(f"  [Sincronia] Corrigindo impacto em {failing_file_name} usando contrato atualizado...", "WARN")
        
        old_content = read_file(failing_file_abs)
        sync_prompt = (
            f"The file {failing_file_rel} broke after refactoring the original file.\n"
            f"REFERENCE CONTRACT (Updated code):\n{trigger_file_content}\n\n"
            f"INSTRUCTION: Update {failing_file_rel} to be COMPATIBLE with the Reference Contract above.\n"
            f"- If a method signature changed, update the call or implementation accordingly.\n"
            f"- NEVER convert Interfaces into Classes.\n"
            f"- Keep the original business logic.\n\n"
            f"CODE THAT NEEDS TO BE FIXED:\n{old_content}"
        )
        
        new_content = call_ai(old_content, sync_prompt, "sync_fix", failing_file_rel, phase=phase)
        if new_content and new_content != old_content:
            write_file(failing_file_abs, new_content)

def _extract_missing_symbol_and_target(maven_line: str) -> tuple[str | None, str | None]:
    """Extrai o nome do símbolo e o caminho absoluto da classe desfalcada do log do Maven."""
    # O maven_line geralmente vem no formato: [ERROR] /caminho/completo/Arquivo.java:[linha,coluna] erro...
    m = re.search(r'(/.*?\.java):', maven_line)
    file_path = m.group(1) if m else None
    
    symbol = None
    if "method" in maven_line:
        m_sym = re.search(r'method (\w+)\(', maven_line)
        symbol = m_sym.group(1) if m_sym else None
        
    return symbol, file_path

def _get_line_from_file(file_path: str, line_number: int) -> str:
    """Retorna uma linha específica de um arquivo."""
    with open(file_path, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f, 1):
            if i == line_number:
                return line
    return ""
