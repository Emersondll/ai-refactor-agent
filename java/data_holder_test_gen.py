"""
data_holder_test_gen.py — Deterministic JUnit 5 test generator for pure data-holder classes
(@Document / @Entity / POJOs with only fields + constructor + getters/setters).

No LLM involved — produces perfect, reproducible tests without a repair loop.
"""

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Supported types table: type → (import_stmt | None, sample_A, sample_B)
# ---------------------------------------------------------------------------
_SUPPORTED_TYPES: dict[str, tuple[Optional[str], str, str]] = {
    "String":        (None,                              '"sampleA"',                                  '"sampleB"'),
    "BigDecimal":    ("import java.math.BigDecimal;",    'new BigDecimal("100.00")',                   'new BigDecimal("250.50")'),
    "BigInteger":    ("import java.math.BigInteger;",    'BigInteger.valueOf(100)',                    'BigInteger.valueOf(250)'),
    "Timestamp":     ("import java.sql.Timestamp;",      'Timestamp.valueOf("2023-01-15 10:00:00")',   'Timestamp.valueOf("2024-06-20 14:30:00")'),
    "long":          (None,                              '1L',                                         '2L'),
    "Long":          (None,                              '1L',                                         '2L'),
    "int":           (None,                              '1',                                          '2'),
    "Integer":       (None,                              '1',                                          '2'),
    "double":        (None,                              '1.0',                                        '2.0'),
    "Double":        (None,                              '1.0',                                        '2.0'),
    "boolean":       (None,                              'true',                                       'false'),
    "Boolean":       (None,                              'true',                                       'false'),
    "LocalDate":     ("import java.time.LocalDate;",     'LocalDate.of(2023, 1, 15)',                  'LocalDate.of(2024, 6, 20)'),
    "LocalDateTime": ("import java.time.LocalDateTime;", 'LocalDateTime.of(2023, 1, 15, 10, 0)',       'LocalDateTime.of(2024, 6, 20, 14, 30)'),
}


# ---------------------------------------------------------------------------
# Enum constant extractor
# ---------------------------------------------------------------------------

def _extract_enum_constants(dep_context: str, enum_name: str) -> list[str]:
    """Parse a `public enum <enum_name> { ... }` block from dep_context and return
    the list of constant names (in declaration order). Empty list if not found.

    Handles both bare constants (`RED, GREEN`) and constructor-arg constants
    (`APPROVED("00"), INSUFFICIENT_FUNDS("51")`).
    """
    if not dep_context or not enum_name:
        return []
    # Match `enum <Name> { body }` — body extends to the next `}` at depth 0
    pattern = re.compile(
        r'\benum\s+' + re.escape(enum_name) + r'\s*\{([^}]*)\}',
        re.DOTALL,
    )
    m = pattern.search(dep_context)
    if not m:
        return []
    body = m.group(1)
    # Stop at the first `;` (separates constants from methods/fields in an enum body)
    body = body.split(";", 1)[0]
    constants: list[str] = []
    for raw in body.split(","):
        token = raw.strip()
        if not token:
            continue
        # Strip constructor args: `APPROVED("00")` → `APPROVED`
        const_m = re.match(r'^([A-Z][A-Z0-9_]*)\s*(?:\(.*?\))?', token, re.DOTALL)
        if const_m:
            constants.append(const_m.group(1))
    return constants


# ---------------------------------------------------------------------------
# Helper regexes
# ---------------------------------------------------------------------------

# Captures class declaration (not interface, enum, or record)
_CLASS_DECL_RE = re.compile(
    r'(?:public\s+)?(?:final\s+)?(?:abstract\s+)?class\s+(\w+)',
    re.MULTILINE,
)

# Rejects if it contains an interface/enum/record declaration
_NOT_CLASS_RE = re.compile(
    r'\b(?:interface|enum|record)\s+\w+',
    re.MULTILINE,
)

# Getter: public T getX() { return field; }  ou  public boolean isX() { return field; }
# Body MUST be exactly: return <one_identifier>;  — no ternary, operators, or calls.
_GETTER_RE = re.compile(
    r'public\s+\S+\s+(?:get|is)(\w+)\s*\(\s*\)\s*\{\s*return\s+\w+\s*;\s*\}',
    re.MULTILINE | re.DOTALL,
)

# Setter: public void setX(T v) { this.field = v; }
# Body MUST be exactly: this.<field> = <param>;  — both sides bare identifiers.
_SETTER_RE = re.compile(
    r'public\s+void\s+set(\w+)\s*\(\s*\S+\s+\w+\s*\)\s*\{\s*this\.\w+\s*=\s*\w+\s*;\s*\}',
    re.MULTILINE | re.DOTALL,
)

# Constructor: public ClassName(...)
_CTOR_RE = re.compile(
    r'public\s+(\w+)\s*\(([^)]*)\)\s*\{([^}]*)\}',
    re.MULTILINE | re.DOTALL,
)

# Generic method pattern (to detect non-getter/setter/ctor/eq/hc/ts methods)
_METHOD_RE = re.compile(
    r'(?:public|protected|private)\s+(?:static\s+)?(?:final\s+)?\S+\s+(\w+)\s*\([^)]*\)\s*\{',
    re.MULTILINE,
)

# Field declaration: private T fieldName;
_FIELD_RE = re.compile(
    r'private\s+(\w+)\s+(\w+)\s*;',
    re.MULTILINE,
)

# Package declaration
_PACKAGE_RE = re.compile(r'^\s*package\s+([\w.]+)\s*;', re.MULTILINE)


# ---------------------------------------------------------------------------
# is_pure_data_holder
# ---------------------------------------------------------------------------

def is_pure_data_holder(code: str) -> bool:
    """
    Returns True only if ``code`` declares a class (not interface/enum/record)
    whose ALL methods are: getter, setter, constructor, or equals/hashCode/toString.
    Any other logic → False. Parsing ambiguity → False (conservative).
    """
    # Must have a class declaration
    if not _CLASS_DECL_RE.search(code):
        return False

    # Must not be interface, enum, or record
    if _NOT_CLASS_RE.search(code):
        return False

    # Determine the class name
    cls_match = _CLASS_DECL_RE.search(code)
    if not cls_match:
        return False
    class_name = cls_match.group(1)

    # Extract the class body (everything between the opening { and the final })
    try:
        class_body = _extract_class_body(code, class_name)
    except Exception:
        return False

    if class_body is None:
        return False

    # Find all methods declared in the body
    # A "method" is any block with access modifier + type + name + parentheses + braces
    methods = _METHOD_RE.findall(class_body)

    # Allowed method names
    allowed_names = {"equals", "hashCode", "toString"}

    # Build getter and setter name sets
    getter_names = {m.group(1).lower() for m in _GETTER_RE.finditer(class_body)}
    setter_names = {m.group(1).lower() for m in _SETTER_RE.finditer(class_body)}
    ctor_names   = {class_name}

    for method_name in methods:
        name_lower = method_name.lower()
        if method_name in ctor_names:
            continue
        if method_name in allowed_names:
            continue
        # Getter: getXxx or isXxx → suffix lowercase in getter_names
        if method_name.startswith("get") and name_lower[3:] in getter_names:
            continue
        if method_name.startswith("is") and name_lower[2:] in getter_names:
            continue
        # Setter
        if method_name.startswith("set") and name_lower[3:] in setter_names:
            continue
        # No rule covered it — method with other logic
        return False

    # If no methods found, it may be just fields → still a data holder
    # but only if it has at least one constructor (to be testable)
    ctor_matches = [m for m in _CTOR_RE.finditer(class_body) if m.group(1) == class_name]
    if not ctor_matches:
        return False

    return True


def _extract_class_body(code: str, class_name: str) -> Optional[str]:
    """Extracts the content between braces of the class declaration."""
    # Locate `class ClassName` and walk forward to the opening brace
    pattern = re.compile(
        r'(?:public\s+)?(?:final\s+)?(?:abstract\s+)?class\s+' + re.escape(class_name) + r'\b[^{]*\{',
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(code)
    if not m:
        return None

    start = m.end()  # position right after '{'
    depth = 1
    i = start
    while i < len(code) and depth > 0:
        if code[i] == '{':
            depth += 1
        elif code[i] == '}':
            depth -= 1
        i += 1

    if depth != 0:
        return None  # unbalanced braces

    return code[start:i - 1]


# ---------------------------------------------------------------------------
# generate_data_holder_test
# ---------------------------------------------------------------------------

def generate_data_holder_test(
    code: str,
    test_class_name: str,
    test_package: str,
    dep_context: str = "",
) -> Optional[str]:
    """
    Generates the full Java source code of a JUnit 5 test for the data-holder class
    described in ``code``.

    Returns None if:
    - ``code`` is not a pure data holder;
    - any field/constructor parameter type is not in the supported-types table;
    - the only constructor is no-arg;
    - constructor parameters do not map 1:1 by name to fields with getters.
    """
    if not is_pure_data_holder(code):
        return None

    # --- Extract package and production class name
    pkg_match = _PACKAGE_RE.search(code)
    prod_package = pkg_match.group(1) if pkg_match else ""

    cls_match = _CLASS_DECL_RE.search(code)
    if not cls_match:
        return None
    class_name = cls_match.group(1)

    # --- Extract class body
    class_body = _extract_class_body(code, class_name)
    if class_body is None:
        return None

    # --- Extract fields: name → type
    fields: dict[str, str] = {}
    for m in _FIELD_RE.finditer(class_body):
        ftype, fname = m.group(1), m.group(2)
        fields[fname] = ftype

    # --- Locate constructor with arguments
    ctor_params: list[tuple[str, str]] = []  # [(type, name), ...]
    for m in _CTOR_RE.finditer(class_body):
        if m.group(1) != class_name:
            continue
        params_str = m.group(2).strip()
        if not params_str:
            continue  # no-arg — skip
        # Parse parameters: "Type name, Type name, ..."
        params = [p.strip() for p in params_str.split(",") if p.strip()]
        parsed = []
        for p in params:
            parts = p.split()
            if len(parts) < 2:
                return None  # ambiguous parsing
            ptype = parts[-2]
            pname = parts[-1]
            parsed.append((ptype, pname))
        if parsed:
            ctor_params = parsed
            break

    if not ctor_params:
        return None  # only no-arg constructor → not usefully testable

    # --- Resolve enum types from dep_context; build enum_samples map
    # For each type not in _SUPPORTED_TYPES, try to resolve via dep_context enum
    _enum_samples: dict[str, tuple[Optional[str], str, str]] = {}  # type → (import, sampleA, sampleB)
    _import_re = re.compile(r'^\s*import\s+([\w.]+\.' + r'(?:{type})' + r')\s*;', re.MULTILINE)
    for ptype, _ in ctor_params:
        if ptype in _SUPPORTED_TYPES:
            continue
        # Try to resolve as an enum from dep_context
        constants = _extract_enum_constants(dep_context, ptype)
        if not constants:
            return None  # unsupported type, no enum resolution → LLM fallback
        first_const = constants[0]
        sample_val = f"{ptype}.{first_const}"
        # Extract the import line from the production code
        import_pattern = re.compile(r'^\s*import\s+([\w.]+\.' + re.escape(ptype) + r')\s*;', re.MULTILINE)
        imp_m = import_pattern.search(code)
        if not imp_m:
            return None  # cannot find import for this enum type → safe-fail
        enum_import = f"import {imp_m.group(1)};"
        _enum_samples[ptype] = (enum_import, sample_val, sample_val)

    # --- Build getter map: field_name_lower → getter_method_name
    getter_map: dict[str, str] = {}
    for m in _GETTER_RE.finditer(class_body):
        suffix = m.group(1)  # "Id", "Name", etc.
        # Retrieve the return type to distinguish is/get
        full_match = m.group(0)
        if re.match(r'public\s+boolean\s+is', full_match):
            getter_method = "is" + suffix
        else:
            getter_method = "get" + suffix
        getter_map[suffix.lower()] = getter_method

    # --- Build setter map: field_name_lower → setter_method_name
    setter_map: dict[str, str] = {}
    for m in _SETTER_RE.finditer(class_body):
        suffix = m.group(1)
        setter_map[suffix.lower()] = "set" + suffix

    # --- Validate 1:1 mapping constructor → getter
    for ptype, pname in ctor_params:
        if pname.lower() not in getter_map:
            return None

    # --- Helper to get type info from either _SUPPORTED_TYPES or _enum_samples
    def _type_info(ptype: str) -> tuple[Optional[str], str, str]:
        if ptype in _SUPPORTED_TYPES:
            return _SUPPORTED_TYPES[ptype]
        return _enum_samples[ptype]

    # --- Collect required imports
    needed_imports: set[str] = set()
    for ptype, _ in ctor_params:
        imp, _, _ = _type_info(ptype)
        if imp:
            needed_imports.add(imp)

    # Imports for setter types (round-trip tests)
    for ptype, pname in ctor_params:
        pname_lower = pname.lower()
        if pname_lower in setter_map:
            imp, _, _ = _type_info(ptype)
            if imp:
                needed_imports.add(imp)

    # Import of the production class
    if prod_package:
        prod_import = f"import {prod_package}.{class_name};"
    else:
        prod_import = None

    # --- Build samples
    sample_a: dict[str, str] = {}
    sample_b: dict[str, str] = {}
    for ptype, pname in ctor_params:
        _, sa, sb = _type_info(ptype)
        sample_a[pname] = sa
        sample_b[pname] = sb

    # --- Build constructor argument list (sample A)
    ctor_args_a = ", ".join(sample_a[pname] for _, pname in ctor_params)

    # --- Generate constructor_shouldInitializeAllFields block
    assertions_lines = []
    for ptype, pname in ctor_params:
        getter_method = getter_map[pname.lower()]
        assertions_lines.append(
            f"        assertEquals({sample_a[pname]}, obj.{getter_method}());"
        )
    assertions_block = "\n".join(assertions_lines)

    constructor_test = (
        f"    @Test\n"
        f"    void constructor_shouldInitializeAllFields() {{\n"
        f"        {class_name} obj = new {class_name}({ctor_args_a});\n"
        f"{assertions_block}\n"
        f"    }}"
    )

    # --- Generate setter/getter round-trip tests (one per setter that has a matching getter)
    round_trip_tests = []
    for ptype, pname in ctor_params:
        pname_lower = pname.lower()
        if pname_lower not in setter_map:
            continue
        setter_method = setter_map[pname_lower]
        getter_method = getter_map[pname_lower]
        # Capitalize for test name: setId_getId_roundTrip
        cap = pname[0].upper() + pname[1:]
        test_method_name = f"set{cap}_get{cap}_roundTrip"
        sb = sample_b[pname]
        test_body = (
            f"    @Test\n"
            f"    void {test_method_name}() {{\n"
            f"        {class_name} obj = new {class_name}({ctor_args_a});\n"
            f"        obj.{setter_method}({sb});\n"
            f"        assertEquals({sb}, obj.{getter_method}());\n"
            f"    }}"
        )
        round_trip_tests.append(test_body)

    # --- Assemble the full file
    lines: list[str] = []

    # package
    lines.append(f"package {test_package};")
    lines.append("")

    # imports
    lines.append("import org.junit.jupiter.api.Test;")
    lines.append("import static org.junit.jupiter.api.Assertions.*;")

    # type imports (sorted)
    for imp in sorted(needed_imports):
        lines.append(imp)

    # production class import
    if prod_import:
        lines.append(prod_import)

    lines.append("")
    lines.append(f"class {test_class_name} {{")
    lines.append("")

    # constructor test
    lines.append(constructor_test)

    # round-trip tests
    for t in round_trip_tests:
        lines.append("")
        lines.append(t)

    lines.append("")
    lines.append("}")

    return "\n".join(lines) + "\n"
