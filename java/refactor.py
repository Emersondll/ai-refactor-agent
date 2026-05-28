"""
refactor.py — Location: java/refactor.py

Fixed:
  - When validator rejects output, the invalid code + reason are fed back
    to call_ai so the model can fix the specific problem.
  - Maximum of MAX_VALIDATOR_RETRIES correction cycles before giving up.
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
from java.output_validator import is_valid_java, validate_package_matches_path
from java.maven_build import maven_test, maven_test_with_coverage
from java.large_file_processor import (
    is_large_file,
    extract_class_header,
    get_processable_methods,
    build_method_context,
    extract_refactored_method,
    replace_method_in_file,
)


LARGE_FILE_THRESHOLD    = 100
MAX_FILE_LINES          = 500
MAX_VALIDATOR_RETRIES   = 3    # correction attempts after validator rejection
MAX_BUILD_FAILURES      = 3    # accumulated build failures before skipping the file
MAX_TEST_FILE_TIMEOUT_S = 1200  # 20 min max per test file — scales with TIMEOUT_TEST(300s) × (MAX_VALIDATOR_RETRIES+1)

_REASON_NO_CHANGE = "no_change"  # signal: model confirmed there are no changes

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

# P2: JUnit 5 assertion methods — absence means missing static import, not a non-existent method
_JUNIT_ASSERTION_METHODS = frozenset({
    "assertTrue", "assertFalse", "assertEquals", "assertNotEquals",
    "assertNull", "assertNotNull", "assertThrows", "assertDoesNotThrow",
    "assertArrayEquals", "assertIterableEquals", "assertLinesMatch",
    "assertTimeout", "assertTimeoutPreemptively", "fail",
    "assertSame", "assertNotSame", "assertAll",
})

# S1/S2: map of JDK types that LLMs frequently use without importing
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
    S1: After LLM generation, deterministically injects missing imports into the test.
    Cross-references class names used in the code with prod_imports (from the production source),
    _JDK_IMPORT_MAP, and project_imports (project-wide map, Option 6).
    Does not involve the LLM — it is a pure structural correction.
    """
    # Build short-name → full import map from production imports
    prod_map: dict[str, str] = {}
    for imp in prod_imports:
        m = re.match(r'import\s+([\w.]+);', imp)
        if m:
            short = m.group(1).split(".")[-1]
            prod_map[short] = imp

    # Collect imports already present in the generated test
    existing_imports = set(re.findall(r'^import\s+[\w.*]+;', test_code, re.MULTILINE))
    existing_short: set[str] = set()
    for imp in existing_imports:
        m = re.match(r'import\s+([\w.]+(?:\.\*)?);', imp)
        if m:
            existing_short.add(m.group(1).split(".")[-1])

    # Detect all CamelCase names used in the test body
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

    # P2b: if the test uses JUnit assertion methods without static import, inject deterministically
    _STATIC_JUNIT = "import static org.junit.jupiter.api.Assertions.*;"
    if _STATIC_JUNIT not in test_code:
        _assertion_pat = r'\b(?:' + '|'.join(_JUNIT_ASSERTION_METHODS) + r')\s*\('
        if re.search(_assertion_pat, test_code):
            to_inject.append(_STATIC_JUNIT)

    if not to_inject:
        return test_code

    # Inject after the last existing import — or after the package if no imports exist
    # — or at the top of the file if there is neither package nor imports (e.g. test snippets)
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
    # Fallback: no package or import found — prepend to top
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
                        # N1: try resolving as an enum from dep_context
                        from java.data_holder_test_gen import _extract_enum_constants
                        consts = _extract_enum_constants(dep_context, t)
                        if consts:
                            v = f"{t}.{consts[0]}"
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

    # CASE C (Option 9): PACKAGE ERROR + test_code scan for unknown class references.
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
    """Analyzes the Maven error and returns a targeted repair instruction."""
    out = output.lower()

    # F: IllegalArgumentException with Timestamp format message (java.sql.Timestamp.valueOf)
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

    # M1: private method or field called from outside — LLM violated encapsulation.
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

    # Record constructor error (detect BEFORE cannot find symbol)
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

    # D: No-arg constructor call on a class that requires parameters (non-record)
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

    # Hallucinated enum or variable error
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
                    # P2a: JUnit assertion method missing → missing static import, not a non-existent method
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
                    # S2: look up exact import in production imports map or JDK map
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

    # Non-existent package
    if "package" in out and "does not exist" in out:
        return (
            "PACKAGE ERROR: An import points to a package that does not exist.\n"
            "Use only classes from the project — check the DEPENDENCY CONTEXT for the correct imports."
        )

    # Assertion error (wrong expected value)
    if "assertionerror" in out or "expected:" in out:
        for line in output.splitlines():
            if "expected:" in line or "but was:" in line:
                detail = line.strip()

                # G1: extract expected/actual directly from Maven error — surgical instruction
                # Covers both BigDecimal (50.00 vs 5.00) and any other mismatch
                _m_vals = re.search(
                    r'expected:\s*<([^>]*)>\s*but was:\s*<([^>]*)>', detail
                )
                if _m_vals:
                    _expected_in_test = _m_vals.group(1)
                    _actual_from_code = _m_vals.group(2)

                    # F4: null vs empty string — special case with method replacement instruction
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

                    # N5: HTTP status mismatch — Maven format <NNN NAME> on both sides.
                    # Must fire BEFORE G1 general so HTTP pairs get the ResponseEntity context.
                    _http_pattern = re.search(
                        r'expected:\s*<(\d{3})\s+(\w+)>\s*but was:\s*<(\d{3})\s+(\w+)>',
                        detail,
                    )
                    if _http_pattern:
                        exp_code, exp_name = _http_pattern.group(1), _http_pattern.group(2)
                        act_code, act_name = _http_pattern.group(3), _http_pattern.group(4)
                        return (
                            f"HTTP STATUS MISMATCH:\n"
                            f"  Your test expects: <{exp_code} {exp_name}>\n"
                            f"  Actual response:   <{act_code} {act_name}>\n\n"
                            "ROOT CAUSE: When a Spring controller returns ResponseEntity, "
                            "Spring IGNORES @ResponseStatus — the actual status comes from "
                            "the ResponseEntity call itself (e.g. .ok() → 200, .status(N) → N).\n\n"
                            "SURGICAL FIX — change ONLY the failing assertion:\n"
                            f"  REPLACE: assertEquals(HttpStatus.{exp_name}, response.getStatusCode())\n"
                            f"  WITH:    assertEquals(HttpStatus.{act_name}, response.getStatusCode())\n"
                            "If you used .value() or raw int, swap "
                            f"{exp_code} for {act_code}. ONE LINE CHANGE — no other code modifications."
                        )

                    # S1: actual is null — specific instruction for assertNull()
                    # Avoids ambiguity: LLM must not use assertEquals("null", ...) or assertEquals(null, ...)
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

                    # General case: replace only the expected value
                    # S2: null disambiguation note at end — prevents confusion if actual comes as "null"
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

                # No extractable pattern — generic fallback
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

    # Spring context (SpringBootTest/WebMvcTest are forbidden)
    if "springboottest" in out or "applicationcontext" in out or "webmvctest" in out:
        return (
            "SPRING CONTEXT ERROR: You used @SpringBootTest or @WebMvcTest — this is FORBIDDEN.\n"
            "Use ONLY @ExtendWith(MockitoExtension.class) with new ClassName() and @Mock/@InjectMocks."
        )

    # NullPointerException without configured mock
    if "nullpointerexception" in out:
        return (
            "NULLPOINTEREXCEPTION ERROR: A dependency was not mocked correctly.\n"
            "Make sure all @Mock fields are configured with Mockito.when(...) before the method call."
        )

    # Incompatible type in mock return or assertion
    # E + Option 2: incompatible-types numeric/big-number coercions
    # Order matters — check more specific patterns first.
    if "incompatible types" in out:
        # E (preserved): BigDecimal passed where Long is expected (e.g. version field)
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

        # Option 2 (new): int/short/byte → Long literal (must add L suffix)
        if re.search(r'incompatible types:\s*(int|short|byte)\s+cannot be converted to\s+(?:java\.lang\.)?Long', output, re.IGNORECASE):
            return (
                "TYPE CONVERSION ERROR: An int/short/byte literal cannot be auto-converted to Long.\n"
                "  CORRECT: 1L  or  Long.valueOf(1)\n"
                "  WRONG:   1   ← raw int — Java will NOT auto-widen to Long in this context\n"
                "Find the int literal on the line indicated by the error and add the L suffix (e.g. 1 → 1L)."
            )

        # Option 2 (new): int/double/short/byte/float → BigDecimal
        if re.search(r'incompatible types:\s*(int|short|byte|double|float)\s+cannot be converted to\s+(?:java\.math\.)?BigDecimal', output, re.IGNORECASE):
            return (
                "TYPE CONVERSION ERROR: A numeric primitive cannot be auto-converted to BigDecimal.\n"
                "  CORRECT: new BigDecimal(\"100.00\")  or  BigDecimal.valueOf(100)\n"
                "  WRONG:   100      ← raw int/double — no implicit conversion\n"
                "Find the literal on the line indicated by the error and wrap it in new BigDecimal(...) or BigDecimal.valueOf(...)."
            )

        # A: String literal passed where BigDecimal is expected
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

    # Method cannot be applied (wrong arguments)
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

    # MockMvc without Spring context (forbidden without @WebMvcTest)
    if "mockmvc" in out:
        return (
            "MOCKMVC ERROR: MockMvc requires Spring context (@WebMvcTest) which is FORBIDDEN.\n"
            "Instead: instantiate the controller directly with new ControllerClass().\n"
            "Use @Mock for the service and @InjectMocks for the controller."
        )

    # Constructor not found (non-record)
    if "constructor" in out and ("no suitable" in out or "cannot find" in out):
        return (
            "CONSTRUCTOR ERROR: No suitable constructor found.\n"
            "Check the class declaration in DEPENDENCY CONTEXT — use the exact constructor args declared.\n"
            "For records, use the CONSTRUCTOR CALL hint in the DEPENDENCY CONTEXT section."
        )

    # Mockito — unnecessary stub (strict stubbing)
    if "unnecessarystubbingexception" in out:
        return (
            "MOCKITO STRICT ERROR: You declared a mock stub (when/thenReturn) that was never called.\n"
            "Remove all Mockito.when(...) stubs that are not used by any @Test method.\n"
            "Only stub what each test actually invokes."
        )

    # Mockito — verification failed (method was never called)
    if "wantedbutnotinvoked" in out or "wanted but not invoked" in out:
        return (
            "MOCKITO VERIFY ERROR: verify() expected a method call that never happened.\n"
            "Either remove the verify() or fix the test so the method is actually called."
        )

    # Mockito — when() without a real method call inside
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

    # Public class with name different from the file (class Foo in Bar.java)
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

    # Output truncated by token limit (reached end of file / try without catch)
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
     "Pure JPA interface (complex generics)"),
    (re.compile(r'@SpringBootApplication'),
     "Spring Boot main class"),
    (re.compile(r'public\s+interface\b'),
     "Pure interface (no logic)"),
    (re.compile(r'(?m)^\s*[A-Z][A-Z_0-9]+\s*\([^)]+\)\s*[,;]'),
     "Enum with parameterized constructor"),
]

# Patterns that apply only in structural phases (SOLID, architecture, etc.)
_STRUCTURAL_PHASE_KEYWORDS = {
    "solid", "architecture", "patterns", "clean_code",
    "tracking", "nomenclature", "structure", "final_keywords",
    # community skills — @Document/@Entity must not be converted/restructured
    "community", "record_migration", "builder_pattern", "dead_code",
    "introduce_parameter", "strategy_pattern", "encapsulate_field",
}
_SKIP_FOR_STRUCTURAL = [
    (re.compile(r'@Document\b'), "@Document — MongoDB data holder"),
    (re.compile(r'@Entity\b'),   "@Entity — JPA data holder"),
    (re.compile(r'@Table\b'),    "@Table — JPA data holder"),
]


# ---------------------------------------------------------------------------
# Solution 5 — Failure registry
# ---------------------------------------------------------------------------

_PERMANENT_SKIP_THRESHOLD = 3  # consecutive failed runs → permanent skip


def _threshold_for(phase: str) -> int:
    """Return the permanent_skip threshold for a phase.
    Env var MAX_FAILS_<phase> overrides the default. Invalid values fall back."""
    raw = os.environ.get(f"MAX_FAILS_{phase}", "")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return _PERMANENT_SKIP_THRESHOLD

# P1: stack_trace patterns that indicate an already-fixed pipeline bug.
# permanent_skip entries whose stack_trace contains any of these patterns are
# automatically removed in reset(), allowing a new generation cycle.
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
        # Do not duplicate within the same run
        if any(e["file"] == file_path and e["phase"] == phase and not e.get("prev_run")
               for e in self._entries):
            return
        # Inherit accumulated fail_count from previous runs (prev_run or permanent_skip)
        prior_count = self._get_prior_fail_count(file_path, phase)
        entry = {
            "file": file_path, "phase": phase, "reason": reason,
            "timestamp": datetime.now().isoformat(), "retried": False,
            "fail_count": prior_count + 1,
        }
        if stack_trace:
            entry["stack_trace"] = stack_trace[-800:]
        # Promote to permanent_skip if threshold reached
        if entry["fail_count"] >= _threshold_for(phase):
            entry["permanent_skip"] = True
            # Remove previous prev_run entries — permanent_skip is the only needed record
            self._entries = [
                e for e in self._entries
                if not (e["file"] == file_path and e["phase"] == phase and e.get("prev_run"))
            ]
            # M7: enriched diagnostic log
            haystack = (stack_trace or "") + " " + (reason or "")
            try:
                from java.fix_metadata import get_fixes
                _fixes = get_fixes()
            except Exception:
                _fixes = []
            compatible_fix_ids = [
                f.get("id", "?")
                for f in _fixes
                if any(p in haystack for p in f.get("patterns", []))
            ]
            # First-failure timestamp: the earliest existing entry for this (file, phase)
            same_key = [
                e for e in self._entries
                if e["file"] == file_path and e["phase"] == phase
            ]
            first_ts = min(
                (e.get("timestamp", "") for e in same_key if e.get("timestamp")),
                default=entry["timestamp"],
            )
            unmatched_patterns = [
                p for p in _AUTO_EXPIRE_STACK_PATTERNS if p not in haystack
            ]

            log(
                f"  → {os.path.basename(file_path)}: PERMANENT SKIP "
                f"({entry['fail_count']} consecutive failures)",
                "WARN",
            )
            log(f"     · Reason: {reason[:120]}", "WARN")
            log(f"     · First failure: {first_ts}", "WARN")
            if compatible_fix_ids:
                log(
                    f"     · Fix candidates (fix_metadata): {', '.join(compatible_fix_ids)} "
                    f"— consider FORCE_RETRY={os.path.basename(file_path)}",
                    "INFO",
                )
            else:
                log(
                    f"     · No fix in fix_metadata.json covers this pattern. "
                    f"Unapplied _AUTO_EXPIRE patterns: {unmatched_patterns[:3]}",
                    "WARN",
                )
        self._entries.append(entry)
        self._save()
        log(f"  → failed_files.json: {os.path.basename(file_path)}", "WARN")

    def _get_prior_fail_count(self, file_path: str, phase: str) -> int:
        """Sums fail_count of all previous entries (prev_run + permanent_skip)."""
        return sum(
            e.get("fail_count", 1)
            for e in self._entries
            if e["file"] == file_path and e["phase"] == phase
            and (e.get("prev_run") or e.get("permanent_skip"))
        )

    def is_permanent_skip(self, file_path: str, phase: str) -> bool:
        """Returns True if this file should be permanently skipped.

        Honors FORCE_RETRY from .env — files whose basename appears in the list
        are NOT skipped, even if marked permanent_skip in failed_files.json.
        """
        from config import FORCE_RETRY as _FORCE_RETRY
        if os.path.basename(file_path) in _FORCE_RETRY:
            return False
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
        """Counts real build failures (excludes 'identical code' and semantic skips)."""
        return sum(
            1 for e in self._entries
            if e["file"] == file_path
            and ("build failed" in e.get("reason", "") or "build quebrou" in e.get("reason", ""))
        )

    def __len__(self) -> int:
        return len(self._entries)

    def reset(self) -> None:
        """Marks current entries as prev_run. Expires permanent entries from already-fixed bugs."""
        kept = []
        for e in self._entries:
            if e.get("permanent_skip"):
                # P1: if stack_trace matches a fixed-bug pattern, remove the block
                st = (e.get("stack_trace") or "") + " " + (e.get("reason") or "")
                expired_pat = next(
                    (p for p in _AUTO_EXPIRE_STACK_PATTERNS if p in st), None
                )
                if expired_pat:
                    log(
                        f"  → {os.path.basename(e['file'])}: permanent_skip expired "
                        f"(fixed bug detected: '{expired_pat}')",
                        "INFO",
                    )
                    continue  # discard — file will be reprocessed from scratch
                kept.append(e)
            elif not e.get("prev_run"):
                e["prev_run"] = True
                kept.append(e)
            # prev_run entries already counted are discarded
        self._entries = kept

        # M3: also consult fix_metadata.json for auto-expire
        try:
            from java.fix_metadata import find_entries_to_expire
            metadata_expire = set(find_entries_to_expire(self._entries))
            if metadata_expire:
                before = len(self._entries)
                self._entries = [
                    e for e in self._entries
                    if e["file"] not in metadata_expire
                    or not e.get("permanent_skip")
                ]
                removed = before - len(self._entries)
                if removed:
                    log(f"  → {removed} entries auto-expired via fix_metadata.json", "OK")
        except Exception as exc:
            log(f"  → fix_metadata check skipped: {exc}", "WARN")

        # M8: long-term safety net — auto-purge permanent_skip older than MAX_SKIP_AGE_DAYS.
        # Disabled when MAX_SKIP_AGE_DAYS <= 0.
        try:
            from config import MAX_SKIP_AGE_DAYS as _MAX_AGE
            if _MAX_AGE > 0:
                from datetime import datetime as _dt, timedelta as _td
                _cutoff = _dt.now() - _td(days=_MAX_AGE)
                before = len(self._entries)
                kept: list[dict] = []
                for e in self._entries:
                    if not e.get("permanent_skip"):
                        kept.append(e)
                        continue
                    ts_raw = e.get("timestamp")
                    if not ts_raw:
                        kept.append(e)  # no timestamp → can't purge safely
                        continue
                    try:
                        ts = _dt.fromisoformat(ts_raw)
                    except Exception:
                        kept.append(e)
                        continue
                    if ts < _cutoff:
                        # Entry is older than the cutoff — purge
                        continue
                    kept.append(e)
                self._entries = kept
                removed = before - len(self._entries)
                if removed:
                    log(
                        f"  → {removed} permanent_skip entries auto-purged "
                        f"(>{_MAX_AGE} days old)",
                        "OK",
                    )
        except Exception as exc:
            log(f"  → M8 age-purge skipped: {exc}", "WARN")

        self._save()

    def clear_permanent_skips(self, file_path: str | None = None) -> int:
        """Removes permanent_skip from a specific file (or all files). Returns count."""
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
                # N7: detect object toString (contains brackets, equals, parens) — these
                # are NOT String values. Quoting them as String literals creates a
                # type-mismatch assertion that fails WORSE than the original null check.
                # Use assertNotNull(expr) — only certainty we have is "not null".
                if re.search(r'[\[\]=()]', actual):
                    new_call = f'assertNotNull({expr})'
                else:
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


def _maven_output_got_worse(old_out: str, new_out: str) -> bool:
    """Compare two Maven outputs and return True if the new one is WORSE than the old.

    Heuristics:
      - new has MORE [ERROR] lines that reference an error type than old → worse
      - new contains a class of error (compile error, type mismatch) that wasn't in old → worse
      - new is empty (test passed) → NOT worse
      - new has same/fewer error indicators → NOT worse
    """
    if not new_out.strip():
        return False  # patch made it pass — clearly not worse
    if not old_out.strip():
        return bool(new_out.strip())  # nothing → something = worse by definition

    def _signature(out: str) -> tuple[int, set]:
        # Count distinct error markers and capture error-type signatures
        lines = [l for l in out.splitlines() if "[ERROR]" in l and "<<<" not in l]
        # Strip line numbers, file paths, and variable values to compare error CATEGORIES
        import re as _re
        sigs: set = set()
        for l in lines:
            # Normalize: drop file paths, line:col, and angle-bracket values
            s = _re.sub(r'/[\w/.\-]+\.java', '<path>', l)
            s = _re.sub(r':\[\d+,\d+\]', '<loc>', s)
            s = _re.sub(r':\d+', '<line>', s)
            s = _re.sub(r'<[^>]*>', '<val>', s)
            sigs.add(s.strip())
        return len(lines), sigs

    old_count, old_sigs = _signature(old_out)
    new_count, new_sigs = _signature(new_out)

    # 1) more error LINES → worse
    if new_count > old_count:
        return True
    # 2) new error CATEGORIES that weren't there before → worse
    new_categories = new_sigs - old_sigs
    if new_categories:
        return True
    return False


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def should_skip(file_path: str, code: str, phase: str = "") -> tuple[bool, str]:
    if len(code.splitlines()) > MAX_FILE_LINES:
        return True, f"File too large ({len(code.splitlines())} lines)"
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
# Generation + validation cycle with correction
# ---------------------------------------------------------------------------

def _generate_and_validate(original: str, rules: str, mode: str,
                             file_name: str, file_path: str,
                             phase: str = "",
                             cache=None,
                             semantic_mem=None) -> tuple[str | None, str]:
    """
    Calls the AI and validates the result with dependency context injection.
    dep_context is retrieved from cache or generated, and passed separately to build_prompt.
    """
    from java.dep_context import get_dependency_context

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
                "\n\n[TEST CONTEXT] The test below validates this class. "
                "Your refactoring MUST ensure it keeps passing:\n\n"
                f"```java\n{test_code}\n```"
            )
            log("  [Context] Unit test injected.", "OK")
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
        return None, "AI did not generate code"

    # Improvement 1: identical code = model confirmed no changes needed
    if new_code.strip() == original.strip():
        return None, _REASON_NO_CHANGE

    valid, reason = is_valid_java(original, new_code)
    if valid:
        # Skill: Class Name Integrity Validator
        from java.output_validator import validate_class_name_matches_file
        is_name_ok, name_error = validate_class_name_matches_file(new_code, file_path)
        if not is_name_ok:
            # B: build specific repair message with both the wrong name AND the correct name
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
            # Improvement 2: Package validation
            is_pkg_ok, pkg_error = validate_package_matches_path(new_code, file_path)
            if not is_pkg_ok:
                reason = f"PACKAGE ERROR: {pkg_error}"
            else:
                return new_code, ""

    log(f"  Validator rejected: {reason} — attempting correction", "WARN")

    from core.utils import load_skill as _ls
    _refactor_repair = _ls("java-repair-guide", section="LLM INSTRUCTIONS") or ""
    _live(active_skill="java-repair-guide")

    # Correction cycles
    rejected_code = new_code
    for attempt in range(1, MAX_VALIDATOR_RETRIES + 1):
        log(f"  Validator correction {attempt}/{MAX_VALIDATOR_RETRIES}: {reason[:60]}")
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
            log(f"  Correction {attempt}: no response", "WARN")
            break

        if corrected and corrected.strip() == original.strip():
            return None, _REASON_NO_CHANGE

        valid, reason = is_valid_java(original, corrected)
        if valid:
            from java.output_validator import validate_class_name_matches_file
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
                    log(f"  Correction {attempt}: accepted ✓", "OK")
                    return corrected, ""

        log(f"  Correction {attempt}: still rejected — {reason}", "WARN")
        rejected_code = corrected

    return None, reason


# ---------------------------------------------------------------------------
# Refactoring — whole file
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
            log(f"  {file_name}: model confirmed no changes are needed", "OK")
            if exec_logger:
                exec_logger.log_file_skipped(phase, file_name, "No changes needed")
            reporter.record_skipped(phase, file_name, "No changes needed")
            return False
        log(f"  {file_name}: failed — {reason}", "WARN")
        get_failed_tracker().record(file, phase, reason)
        if exec_logger:
            exec_logger.log_ai_failure(phase, file_name, "all-agents", reason)
        if "did not generate" in reason:
            reporter.record_skipped(phase, file_name, reason)
        else:
            reporter.record_rejected(phase, file_name, reason)
        return False

    write_file(file, new_code)
    success, build_output = maven_test(repo_path)

    if not success:
        log(f"  {file_name}: Build failed. Analyzing global impact...", "WARN")

        # Cascade impact detection
        if "cannot find symbol" in build_output or "does not override" in build_output:
            _live(active_skill="ContextualSync")
            log("  [Impact Detected] Contract change detected. Attempting contextual sync...", "PHASE")
            _attempt_global_sync(build_output, repo_path, rules, phase, new_code)
            success, build_output = maven_test(repo_path)
            if success:
                log(f"  {file_name}: Global sync restored the build! ✓", "OK")

    if not success:
        log(f"  {file_name}: Build persists with error. Activating Precision Diagnostics...", "WARN")

        # Cross-file culprit identification
        # If the error is in ANOTHER file (e.g. a missing interface), try to restore/fix that file.
        culprit_match = re.search(r'([/\\].*\.java):\[\d+', build_output)
        if culprit_match:
            culprit_path = culprit_match.group(1)
            culprit_name = os.path.basename(culprit_path)
            if culprit_name != file_name:
                log(f"  [Auto-Heal] Culprit seems to be {culprit_name}. Attempting emergency repair...", "PHASE")
                # If the error is "does not contain class" or "should be declared in file" — structural error
                if "should be declared in a file" in build_output or "does not contain class" in build_output:
                    # Try to restore the interface/culprit file to a stable state
                    run_command(f"git checkout -- \"{culprit_path}\"", repo_path)
                    log(f"  [Auto-Heal] {culprit_name} restored to stable Git state.", "OK")
                    success, build_output = maven_test(repo_path)
                    if success: return True  # resolved by restoring the culprit

        # Error X-Ray (continues for the current file)
        _live(active_skill="ErrorXRay")
        error_diagnostics = []
        raw_error_lines = [l for l in build_output.splitlines() if "[ERROR]" in l and ".java:[" in l][:5]

        for err_line in raw_error_lines:
            # Improved regex to support paths with spaces: /path/with space/File.java:[line,col]
            m = re.search(r'([/\\].*\.java):\[(\d+)', err_line)
            if m:
                fpath, lnum = m.group(1), int(m.group(2))
                try:
                    code_snippet = _get_line_from_file(fpath, lnum)
                    diag = f"Error in {os.path.basename(fpath)} L{lnum}: {code_snippet.strip()}\n      -> {err_line.split('] ', 1)[-1]}"
                    error_diagnostics.append(diag)
                    log(f"  [XRay] {diag}", "ERR")
                except: pass

        error_summary = "\n".join(error_diagnostics) or "\n".join(build_output.splitlines()[:5])

        # Log diagnostic for later analysis
        exec_logger.log_detailed_diagnostic(phase, file_name, build_output, error_diagnostics)

        # Import reinforcement with global dictionary
        _live(active_skill="Project Dictionary")
        if "cannot find symbol" in error_summary:
            from java.java_keywords import build_project_dictionary
            proj_map = None
            if cache is not None:
                proj_map = cache.get_project_dict()
            if proj_map is None:
                proj_map = build_project_dictionary(repo_path)
                if cache is not None:
                    cache.set_project_dict(proj_map)
            error_summary += f"\n\n{proj_map}\n\nHINT: Use the map above to add the correct IMPORT."

        corrected_code = call_ai_with_correction(
            original     = original,
            rules        = rules,
            mode         = mode,
            file_name    = file_name,
            file_path    = file,
            bad_output   = new_code,
            error_reason = f"Maven Compilation Failure:\n{error_summary}",
            phase        = phase
        )

        _live(active_skill="AutoHeal")
        if corrected_code:
            write_file(file, corrected_code)
            success, _ = maven_test(repo_path)
            if success:
                log(f"  {file_name}: Auto-heal succeeded! ✓", "OK")
                new_code = corrected_code
            else:
                log(f"  {file_name}: Auto-heal failed.", "ERR")
                write_file(file, original)
                get_failed_tracker().record(file, phase, "build failed (auto-heal failed)")
                return False
        else:
            write_file(file, original)
            log(f"  {file_name} REVERTED: build broke and AI did not fix it", "WARN")
            get_failed_tracker().record(file, phase, "build failed")
            return False

    reporter.record_changed(phase, file_name, file, original, new_code)
    if exec_logger:
        exec_logger.log_file_accepted(phase, file_name, "+refactor")
    log(f"  {file_name} REFACTORED ✓", "OK")
    return True


# ---------------------------------------------------------------------------
# Refactoring — method by method
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
        log(f"  {file_name}: no extractable methods — trying whole file")
        return _refactor_whole_file(file, original, rules, repo_path, phase,
                                    reporter, exec_logger, cache=cache,
                                    semantic_mem=semantic_mem)

    log(f"  {file_name}: {len(methods)} methods to process")

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
            log(f"      {method.name}: method not found in response", "WARN")
            methods_failed += 1
            continue

        if new_method_text.strip() == method.full_text.strip():
            log(f"      {method.name}: no change")
            continue

        updated_code = replace_method_in_file(current_code, method, new_method_text)
        valid_full, reason_full = is_valid_java(current_code, updated_code)
        if not valid_full:
            log(f"      {method.name}: invalid after substitution: {reason_full}", "WARN")
            methods_failed += 1
            continue

        current_code = updated_code
        methods_changed += 1
        log(f"      {method.name}: OK ✓")

    if methods_changed == 0:
        if methods_failed > 0:
            get_failed_tracker().record(
                file, phase, f"all {methods_failed} methods failed"
            )
        log(f"  {file_name}: no methods changed", "WARN")
        reporter.record_skipped(phase, file_name, "no methods changed")
        return False

    write_file(file, current_code)
    success, build_out = maven_test(repo_path)

    if not success:
        write_file(file, original)
        log(f"  {file_name} REVERTED after {methods_changed} methods", "WARN")
        get_failed_tracker().record(file, phase, "build failed after refactoring")
        if exec_logger:
            exec_logger.log_file_reverted(phase, file_name, error_type=_categorize_build_error(build_out)[:80])
        reporter.record_build_failed(phase, file_name)
        return False

    reporter.record_changed(phase, file_name, file, original, current_code)
    if exec_logger:
        exec_logger.log_file_accepted(phase, file_name, f"+{methods_changed}methods")
    log(f"  {file_name} REFACTORED ✓ ({methods_changed} methods)", "OK")
    return True


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def refactor_file(file: str, rules: str, repo_path: str,
                  phase: str, reporter: PhaseReporter,
                  exec_logger: ExecutionLogger | None = None,
                  cache=None,
                  semantic_mem=None) -> bool:
    file_name = os.path.basename(file)

    # Phase skip: if this file was already processed in this phase this run, skip
    if cache is not None:
        phase_name = phase.split("/")[-1].replace(".md", "")
        if cache.is_phase_done(file, phase_name):
            log(f"  {file_name}: cache hit — {phase_name} already applied this run", "OK")
            reporter.record_skipped(phase, file_name, f"cache: {phase_name} already applied")
            return False

    # Improvement 4: skip files with repeated build failure history
    build_fails = get_failed_tracker().get_build_failure_count(file)
    if build_fails >= MAX_BUILD_FAILURES:
        log(f"  {file_name}: build failed {build_fails}x in prior phases — skipping", "WARN")
        if exec_logger:
            exec_logger.log_file_skipped(phase, file_name,
                                         f"History: build failed {build_fails}x")
        reporter.record_skipped(phase, file_name,
                                f"Failure history ({build_fails}x build failed)")
        return False

    log(f"Processing [{_mode_for(file)}]: {file_name}")

    if exec_logger:
        exec_logger.log_file_processing(phase, file_name, "unknown", "unknown")

    original = read_file(file)

    # Improvement 3: pass phase to consider phase-specific skip patterns
    skip, reason = should_skip(file, original, phase)
    if skip:
        log(f"  {file_name} SKIPPED: {reason}", "WARN")
        if exec_logger:
            exec_logger.log_file_skipped(phase, file_name, reason)
        reporter.record_skipped(phase, file_name, reason)
        return False

    if is_large_file(original, LARGE_FILE_THRESHOLD):
        log(f"  {file_name}: large file → method-by-method processing")
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
# M7 — Field injection without constructor detection (deferred skip)
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
    """Detects classes with @Autowired field injection but no explicit constructor.
    These classes cannot be unit-tested without Spring context
    until phase 11 (SOLID DIP) converts them to constructor injection."""
    has_field_injection = bool(_RE_AUTOWIRED_FIELD.search(code))
    has_constructor = bool(_RE_EXPLICIT_CONSTRUCTOR.search(code))
    return has_field_injection and not has_constructor


# ---------------------------------------------------------------------------
# M8 — Existing test setup extraction for reuse in complement
# ---------------------------------------------------------------------------

_RE_MOCK_FIELD   = re.compile(r'@Mock\b.*?\n\s+\w[\w<>, ]*\s+\w+\s*;', re.DOTALL)
_RE_INJECT_FIELD = re.compile(r'@InjectMocks\b.*?\n\s+\w[\w<>, ]*\s+\w+\s*;', re.DOTALL)
_RE_SPY_FIELD    = re.compile(r'@Spy\b.*?\n\s+\w[\w<>, ]*\s+\w+\s*;', re.DOTALL)
_RE_FIELD_DECL   = re.compile(r'(?:private|protected)\s+(?:final\s+)?[\w<>, ]+\s+(\w+)\s*(?:=|;)', re.MULTILINE)

# All JUnit 4 and JUnit 5 lifecycle annotations
_LIFECYCLE_ANNOTATIONS = [
    "@BeforeAll",   # JUnit 5 — static, runs once before all tests
    "@BeforeEach",  # JUnit 5 — runs before each @Test
    "@AfterEach",   # JUnit 5 — runs after each @Test
    "@AfterAll",    # JUnit 5 — static, runs once after all tests
    "@Before",      # JUnit 4 — equivalent to @BeforeEach
    "@After",       # JUnit 4 — equivalent to @AfterEach
    "@BeforeClass", # JUnit 4 — equivalent to @BeforeAll
    "@AfterClass",  # JUnit 4 — equivalent to @AfterAll
]

def _build_lifecycle_pattern(annotation: str) -> re.Pattern:
    """Regex that captures a method annotated with any lifecycle annotation."""
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
    """Extracts mocks, injects, spies, lifecycle methods, and fields from the existing test.

    Returns a structured block to inject into the complement prompt (M8),
    telling the LLM exactly what already exists and what is READ-ONLY."""
    sections: list[str] = []

    # --- Mock / injection fields ---
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

    # --- Existing lifecycle methods ---
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

        # Dynamic rule: list only ABSENT annotations as allowed
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
# Test generation
# ---------------------------------------------------------------------------

def _extract_private_method_names(code: str) -> list[str]:
    """Return the names of all private methods declared in the class source."""
    pattern = re.compile(
        r'^\s*private\s+(?:static\s+|final\s+|synchronized\s+)*'
        r'[\w<>\[\],?\s]+\s+(\w+)\s*\(',
        re.MULTILINE,
    )
    names: list[str] = []
    for m in pattern.finditer(code):
        name = m.group(1)
        # Skip if the captured name is a Java keyword (defensive — should not happen)
        if name not in names:
            names.append(name)
    return names


def _fix_private_method_calls(test_code: str, prod_code: str) -> str:
    """Remove any @Test method in test_code that calls a private method of prod_code.

    Uses word-boundary regex to avoid false positives (e.g., `validate` should NOT
    match `validateAll`). Detection patterns:
      - `.{name}(` — instance call like `obj.privateMethod(...)` or `Class.privateMethod(`
      - `\\b{name}\\s*(` — bare call inside the test (rare; if the test extends the
        target class, it could call inherited members, but private isn't inherited)

    Returns the test_code with offending @Test methods removed. Other content
    (imports, fields, lifecycle methods, public @Tests) is preserved unchanged.
    """
    private_names = _extract_private_method_names(prod_code)
    if not private_names:
        return test_code

    # Build a regex that matches any call to one of the private names with word boundaries
    name_alt = "|".join(re.escape(n) for n in private_names)
    call_pattern = re.compile(rf'\.({name_alt})\s*\(|(?<![\w.])({name_alt})\s*\(')

    # Walk through @Test method blocks. For each, check if any line matches.
    lines = test_code.splitlines(keepends=True)
    out_lines: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Look for @Test on a line (may be preceded by other annotations)
        if re.match(r'^\s*@Test\b', line):
            # Find the bounds of this @Test method:
            # Start = current line (with annotations grouped)
            # We need to find the opening { and matching } of the method body
            ann_start = i
            # Find the next { which opens the body
            j = i
            while j < len(lines) and "{" not in lines[j]:
                j += 1
            if j >= len(lines):
                out_lines.append(line)
                i += 1
                continue
            # Now find the matching } using brace depth from this point onward
            brace_depth = 0
            method_end = j
            for k in range(j, len(lines)):
                for ch in lines[k]:
                    if ch == "{":
                        brace_depth += 1
                    elif ch == "}":
                        brace_depth -= 1
                        if brace_depth == 0:
                            method_end = k
                            break
                if brace_depth == 0:
                    break

            method_block = "".join(lines[ann_start : method_end + 1])
            if call_pattern.search(method_block):
                # Skip the whole method block — drop these lines from output
                # Also consume any trailing blank line for cleanliness
                i = method_end + 1
                if i < len(lines) and lines[i].strip() == "":
                    i += 1
                continue
            else:
                out_lines.extend(lines[ann_start : method_end + 1])
                i = method_end + 1
                continue

        out_lines.append(line)
        i += 1

    return "".join(out_lines)


def _parse_record_fields(params: str) -> list[str]:
    """Extract field names from a record component list, e.g. 'String code, int amount' → ['code', 'amount']."""
    fields = []
    for part in params.split(","):
        tokens = part.strip().split()
        if tokens:
            name = re.sub(r'[<>\[\]].*', '', tokens[-1]).strip()
            if name and name.isidentifier():
                fields.append(name)
    return fields


def _build_active_rules(
    original: str,
    _prod_imports: list[str],
    _self_import: str | None,
    _test_cls_name: str,
    _test_pkg: str,
    complement_mode: bool,
    rules: str,
    dep_context: str = "",
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

    # R1: record dependency accessors — when dep_context references record types used by the class
    # under test. Records expose fields via accessor methods named after the field (NOT getX()).
    # LLMs default to JavaBean convention (getX()) and hallucinate non-existent methods.
    if dep_context:
        _dep_records = re.findall(
            r'(?:public\s+)?record\s+(\w+)\s*\(([^)]*)\)', dep_context
        )
        if _dep_records:
            _record_lines: list[str] = []
            for _rec_name, _params in _dep_records:
                _fields = _parse_record_fields(_params)
                if _fields:
                    _accessors = ", ".join(f".{f}()" for f in _fields)
                    _record_lines.append(f"  {_rec_name}: {_accessors}")
            if _record_lines:
                active_rules += (
                    "\n\n### JAVA RECORD DEPENDENCIES — ACCESSOR SYNTAX (MANDATORY)\n"
                    "The following dependency classes are Java records. Record field accessors\n"
                    "use the field name directly — NOT the JavaBean getter convention:\n"
                    "  CORRECT: instance.fieldName()    ← record accessor (exists)\n"
                    "  WRONG:   instance.getFieldName() ← does NOT exist, will NOT compile\n"
                    "Accessors for records used in this class:\n"
                    + "\n".join(_record_lines) + "\n"
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

    # N4: Spring controller using ResponseEntity AND @ResponseStatus — annotation is ignored
    # by Spring when the return type is ResponseEntity. LLM keeps asserting against the
    # @ResponseStatus value and tests fail at runtime.
    if "@ResponseStatus" in original and "ResponseEntity" in original:
        active_rules += (
            "\n\n### SPRING RESPONSEENTITY + @ResponseStatus (MANDATORY)\n"
            "This controller declares @ResponseStatus AND returns ResponseEntity.\n"
            "Spring IGNORES @ResponseStatus when the return type is ResponseEntity —\n"
            "the actual HTTP status comes from the ResponseEntity itself.\n"
            "Examples:\n"
            "  return ResponseEntity.ok().body(x)        → 200 OK   (NOT @ResponseStatus value)\n"
            "  return ResponseEntity.status(201).body(x) → 201 CREATED\n"
            "When asserting status in tests, use the value from the ResponseEntity call\n"
            "(`.ok()` → 200, `.status(XYZ)` → XYZ), NOT the @ResponseStatus annotation.\n"
        )

    # N10: controller-null-input pattern — LLM frequently writes assertNull(response.getBody())
    # without mocking the service to return null. The body is whatever the service returned,
    # NOT null by default. Different from N4 (which is about @ResponseStatus being ignored).
    _is_restcontroller = "@RestController" in original
    _returns_response_entity = bool(re.search(
        r'public\s+(?:final\s+)?ResponseEntity\s*[<(]', original
    ))
    if _is_restcontroller and _returns_response_entity:
        active_rules += (
            "\n\n### CONTROLLER NULL-INPUT TEST PATTERN (MANDATORY)\n"
            "When writing a test where the controller method receives a null input "
            "(e.g. `controller.method(null)`):\n"
            "  - The response body is NOT null by default — it is whatever the underlying\n"
            "    service returns when called with null.\n"
            "  - SOLUTION 1: explicitly mock the service to return null for that case:\n"
            "      when(service.method(any())).thenReturn(null);\n"
            "      assertNull(response.getBody());\n"
            "  - SOLUTION 2: assert on the response STRUCTURE (status, presence) instead:\n"
            "      assertNotNull(response);\n"
            "      assertEquals(HttpStatus.OK, response.getStatusCode());\n"
            "  - NEVER: assertNull(response.getBody()) without first stubbing the service\n"
            "    to return null. The body will reflect what service.method(null) actually\n"
            "    returns (often a default object like TypeCode[field=null], not Java null)."
        )

    # N6: service-with-lookup-logic preventive — warns LLM that mocks may not
    # passthrough to the assertion when the method has transformation logic.
    _has_repo_call = re.search(
        r'\b\w*[Rr]epo\w*\.\s*find\w*\s*\(', original
    ) is not None
    _has_transform_logic = bool(re.search(
        r'\.\s*(orElse|orElseThrow|orElseGet|map|filter)\s*\(', original
    )) or bool(re.search(r'\bif\s*\(', original))
    if _has_repo_call and _has_transform_logic:
        active_rules += (
            "\n\n### SERVICE LOOKUP WITH TRANSFORMATION (MANDATORY)\n"
            "This class calls a repository AND has transformation/conditional logic\n"
            "(.orElse / .map / if / etc.) between the repository call and the return.\n"
            "WARNING: the value you stub into the mock may NOT be what the service\n"
            "returns — the transformation can change it (.orElse fallback, .map(...),\n"
            "if-branches, hardcoded defaults, etc.).\n"
            "Before writing an assertion, READ the method body carefully:\n"
            "  - What value does the mock return?\n"
            "  - What transformations are applied to that value?\n"
            "  - What is the FINAL value the method returns?\n"
            "Assert against the FINAL value, NOT the mocked seed value."
        )

    # S3: null assertions — prevents enum-vs-null failures
    active_rules += (
        "\n\n### NULL ASSERTIONS\n"
        "When input for a field is null, the method may return null — use assertNull(result.getField()).\n"
        "NEVER assertEquals(EnumValue, result.getField()) when input was null.\n"
        "NEVER invent a non-null expected value unless the production code explicitly defines a non-null default.\n"
    )

    # M12: private method prohibition — prevents `has private access` compile errors
    _private_methods = _extract_private_method_names(original)
    if _private_methods:
        active_rules += (
            "\n\n### PRIVATE METHODS — NEVER CALL\n"
            "The class under test declares these PRIVATE methods. They cannot be called "
            "from a test in any package (Java enforcement):\n"
            f"  {', '.join(_private_methods)}\n"
            "If you need to verify the behavior of any of these, find the PUBLIC method "
            "in the same class that invokes the private one internally and call that "
            "public method instead — the private logic runs as a side effect."
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

    # Option 6: project-wide import map, computed once per generate_tests call.
    _project_imports = build_project_imports(repo_path)

    for main_file in main_files:
        # N9: reset consecutive timeout counter for each new file
        from ai.model import reset_consecutive_timeouts as _reset_ct
        _reset_ct()
        original  = read_file(main_file)
        file_name = os.path.basename(main_file)

        skip, _ = should_skip(main_file, original)
        if skip:
            continue

        # S2 (fixed): skip only pure interfaces — @Document/@Entity still have
        # getters/setters/constructors that need test coverage.
        # should_skip() already filters JPA repository interfaces and @SpringBootApplication.
        # Additional filter: non-repository interfaces (no Repository inheritance).
        if re.search(r'(?:public\s+)?interface\s+\w+', original) and \
                not re.search(r'extends\s+\w*Repository\w*\s*<', original):
            # Pure interface without implementation — should_skip may not have caught it
            # (e.g. service interfaces without "Repository" in the name)
            continue

        test_path = _test_path_for(main_file, repo_path)
        if not test_path:
            continue

        test_name = os.path.basename(test_path)

        # M6: permanent skip — file failed in 3+ consecutive runs
        if get_failed_tracker().is_permanent_skip(test_path, phase):
            log(f"  {test_name}: PERMANENT SKIP (recurring failures in previous runs)", "WARN")
            if exec_logger:
                exec_logger.log_file_skipped(phase, test_name, "permanent_skip")
            continue

        # M7: deferred skip — production class with field injection (@Autowired without constructor)
        if _has_field_injection_without_constructor(original):
            # S5 (fixed): unblock if solid-dip will never process this file.
            # Two cases where solid-dip will not act:
            #   a) permanent_skip: already tried 3x and failed
            #   b) no_new_instantiation: pre-filter eliminates before LLM (never accumulates failures)
            _dip_permanent   = get_failed_tracker().is_permanent_skip(main_file, "solid-dip")
            _dip_prefiltered = not bool(re.search(r'\bnew\s+[A-Z]\w+\s*\(', original))
            if _dip_permanent or _dip_prefiltered:
                log(
                    f"  {test_name}: solid-dip not applicable "
                    f"({'permanent_skip' if _dip_permanent else 'no_new_instantiation'}) "
                    f"— generating test with @InjectMocks",
                    "WARN"
                )
                # Do not continue — Mockito supports field injection via @InjectMocks
            else:
                log(
                    f"  {test_name}: DEFERRED — field injection detected "
                    f"(test after phase 11 SOLID DIP)", "WARN"
                )
                if exec_logger:
                    exec_logger.log_file_skipped(phase, test_name, "deferred_field_injection")
                reporter.record_skipped(phase, test_name, "deferred: field injection without constructor")
                continue

        # M8: complementing existing tests with partial coverage
        complement_mode   = False
        existing_test_code = ""
        existing_coverage  = 0.0

        if os.path.exists(test_path):
            _, _, existing_coverage, missed_existing = maven_test_with_coverage(repo_path, file_name)
            if existing_coverage >= 90.0 or not missed_existing:
                continue  # coverage already adequate — nothing to do
            complement_mode    = True
            existing_test_code = read_file(test_path)
            log(
                f"  Complementing: {test_name} "
                f"(current coverage {existing_coverage:.1f}% — lines: {missed_existing})"
            )
        else:
            log(f"  Generating test: {test_name}")

        # Clear OOM-marked models between files to avoid cascade failures
        # If Ollama was physically OOM, wait for recovery before continuing
        from ai.model import _OOM_MODELS, wait_for_ollama_recovery
        if _OOM_MODELS:
            _OOM_MODELS.clear()
            if not wait_for_ollama_recovery():
                log(f"  {test_name}: Ollama did not recover — skipping", "WARN")
                get_failed_tracker().record(test_path, phase, "Ollama OOM — service did not recover")
                if exec_logger:
                    exec_logger.log_ai_failure(phase, test_name, "ollama-oom", "Service did not recover after OOM cascade")
                reporter.record_skipped(phase, test_name, "Ollama OOM")
                continue
        else:
            _OOM_MODELS.clear()

        file_mode = "complement" if complement_mode else "new"
        if exec_logger:
            exec_logger.log_file_processing(phase, test_name, "test", file_mode)

        from java.dep_context import get_dependency_context
        try:
            test_dep_context = get_dependency_context(original, repo_path)
        except Exception:
            test_dep_context = ""

        # C3: compute name/package constraint BEFORE building active_rules — inserted at the START
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

        # P0: data holders are tested deterministically — no LLM, no repair loop.
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
                        log(f"  {test_name} CREATED (deterministic, no LLM) ✓", "OK")
                        reporter.record_changed(phase, test_name, test_path, "", _dh_test)
                        if exec_logger:
                            exec_logger.log_file_accepted(phase, test_name, "+test")
                            exec_logger.log_model_used(phase, test_name, "deterministic", "ACCEPTED")
                        any_changed = True
                        from git_utils.repo import commit_single_file
                        commit_single_file(repo_path, test_path,
                                            f"test: add {test_name} (deterministic)")
                        continue
                    log(f"  {test_name}: deterministic generator failed build — falling back to LLM", "WARN")
                    os.remove(test_path)

        _prod_imports = re.findall(r'^import\s+[\w.]+;', original, re.MULTILINE)

        # F1: self-import — the class under test does not import itself, but the test needs to.
        # We derive the exact import from the production class package + filename.
        _prod_pkg_m = re.search(r'^package\s+([\w.]+);', original, re.MULTILINE)
        _prod_cls_name = file_name.replace(".java", "")
        _self_import: str | None = (
            f"import {_prod_pkg_m.group(1)}.{_prod_cls_name};" if _prod_pkg_m else None
        )
        # Expanded list for S1: prod_imports + self-import (ensures MerchantDocument,
        # TransactionController etc. are always injected even after LLM repairs)
        _s1_imports = list(_prod_imports)
        if _self_import:
            _s1_imports.append(_self_import)

        # M8: complement rules — LLM receives existing test + explicit setup + gaps
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
                dep_context    = test_dep_context,
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

        # Pre-write validator order:
        # 1) _fix_constructor_calls: may INTRODUCE new BigDecimal(...) / Timestamp.valueOf(...)
        #    when rewriting constructor calls with sample values from _TYPE_SAMPLES.
        # 2) _fix_private_method_calls: only removes invalid @Tests, does not add new types.
        # 3) _auto_inject_missing_imports (S1) MUST run LAST to see
        #    all types introduced by the previous steps and inject the imports.
        test_code = _fix_constructor_calls(test_code, test_dep_context)
        test_code = _fix_private_method_calls(test_code, original)
        test_code = _auto_inject_missing_imports(test_code, _s1_imports, project_imports=_project_imports)

        os.makedirs(os.path.dirname(test_path), exist_ok=True)
        write_file(test_path, test_code)

        success, combined_out, coverage, missed_lines = maven_test_with_coverage(repo_path, file_name)

        # M8: in complement mode, also pass active_rules with the existing test for repairs

        # Structured repair cycle — timeout already started before generation
        timed_out = False
        timed_out = False
        error_history: list[str] = []  # accumulates errors across attempts

        for attempt in range(MAX_VALIDATOR_RETRIES):
            elapsed = time.time() - file_start_time
            if elapsed > MAX_TEST_FILE_TIMEOUT_S:
                log(f"  [{test_name}] timeout de {MAX_TEST_FILE_TIMEOUT_S // 60}min atingido — encerrando reparos", "WARN")
                timed_out = True
                break

            if success and coverage >= 90.0:
                log(f"  [{test_name}] Coverage reached: {coverage:.2f}% ✓", "OK")
                break

            if not success:
                repair_hint = _categorize_build_error(combined_out, _prod_imports)
                if _is_irrecoverable_hallucination(
                    repair_hint, _prod_imports,
                    test_code=test_code,
                    project_imports=_project_imports,
                ):
                    log(
                        f"  [{test_name}] Irrecoverable failure detected (symbol hallucination) — skipping remaining repairs",
                        "WARN",
                    )
                    break
                error_history.append(f"Attempt {attempt + 1}: {repair_hint}")
                log(f"  [{test_name}] Repair {attempt + 1}/{MAX_VALIDATOR_RETRIES}: {repair_hint[:80]}...", "WARN")
                _patched = _try_surgical_patch(test_code, combined_out)
                if _patched is not None:
                    log(f"  [{test_name}] Surgical patch applied — no LLM", "OK")
                    _original_code = test_code
                    _original_out  = combined_out
                    write_file(test_path, _patched)
                    test_code = _patched
                    success, combined_out, coverage, missed_lines = \
                        maven_test_with_coverage(repo_path, file_name)
                    if success:
                        continue
                    # N8: patch didn't fix it AND made it worse → revert
                    if _maven_output_got_worse(_original_out, combined_out):
                        log(
                            f"  [{test_name}] Patch P4 made the build worse — reverting "
                            "to previous state before LLM repair", "WARN",
                        )
                        write_file(test_path, _original_code)
                        test_code = _original_code
                        combined_out = _original_out
                    # fall through to LLM repair as normal
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
                log(f"  [{test_name}] Low coverage: {coverage:.2f}%. Expanding coverage...", "WARN")
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
                log(f"  [{test_name}] LLM did not generate a correction — ending repairs", "WARN")
                break

            # C2: validate class name BEFORE writing to disk
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
                continue  # do not write the file — force new repair with class error

            # F2: validate package declaration BEFORE writing to disk
            # LLM may preserve the class name but swap the package (com.example.model etc.)
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
                continue  # do not write the file — force new repair with package error

            # Pre-write validator order (same as in the initial generation block):
            # _fix_constructor_calls may INTRODUCE new BigDecimal/Timestamp/Long,
            # so S1 (_auto_inject_missing_imports) must run LAST to
            # inject imports for the newly introduced types.
            corrected_test = _fix_constructor_calls(corrected_test, test_dep_context)
            corrected_test = _fix_private_method_calls(corrected_test, original)
            corrected_test = _auto_inject_missing_imports(corrected_test, _s1_imports, project_imports=_project_imports)
            write_file(test_path, corrected_test)
            test_code = corrected_test
            success, combined_out, coverage, missed_lines = maven_test_with_coverage(repo_path, file_name)

        # After all repairs: accept if built, revert if not
        if not success:
            timeout_note = " (timeout)" if timed_out else ""
            err_reason = f"build failed after {MAX_VALIDATOR_RETRIES} repairs{timeout_note}"
            final_error_type = _categorize_build_error(combined_out)[:150]
            if complement_mode:
                # M8: restore original test instead of deleting
                write_file(test_path, existing_test_code)
                log(f"  {test_name}: {err_reason} — complement reverted", "WARN")
            else:
                os.remove(test_path)
                log(f"  {test_name}: {err_reason} — file removed", "WARN")
            get_failed_tracker().record(test_path, phase, err_reason,
                                        stack_trace=combined_out)
            if exec_logger:
                exec_logger.log_file_reverted(phase, test_name, error_type=final_error_type)
            reporter.record_build_failed(phase, test_name)
            continue

        from ai.model import get_last_model as _get_model
        change_type = "+complement" if complement_mode else "+test"
        action_label = "COMPLEMENTED" if complement_mode else "CREATED"
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
    Contextual Sync 2.0: Uses the recently refactored code as a reference
    to fix dependencies in other files.
    """
    error_lines = [l for l in build_output.splitlines() if "cannot find symbol" in l or "does not override" in l]
    
    for line in error_lines[:3]:
        symbol, failing_file_abs = _extract_missing_symbol_and_target(line)
        if not failing_file_abs: continue
        
        if not os.path.exists(failing_file_abs): continue
        
        failing_file_name = os.path.basename(failing_file_abs)
        failing_file_rel = os.path.relpath(failing_file_abs, repo_path)
        log(f"  [Sync] Fixing impact in {failing_file_name} using updated contract...", "WARN")
        
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
    """Extracts the symbol name and absolute path of the broken class from the Maven log."""
    # maven_line usually comes in the format: [ERROR] /full/path/File.java:[line,col] error...
    m = re.search(r'(/.*?\.java):', maven_line)
    file_path = m.group(1) if m else None
    
    symbol = None
    if "method" in maven_line:
        m_sym = re.search(r'method (\w+)\(', maven_line)
        symbol = m_sym.group(1) if m_sym else None
        
    return symbol, file_path

def _get_line_from_file(file_path: str, line_number: int) -> str:
    """Returns a specific line from a file."""
    with open(file_path, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f, 1):
            if i == line_number:
                return line
    return ""
