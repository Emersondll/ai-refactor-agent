"""
java/validator.py — LLM output validator for generated Java code.

Applied fixes:
  1. Expanded is_modern_java — covers more Java 14+ patterns to eliminate
     false positives from javalang 0.13.0.
  2. Error context logging — on syntax rejection, logs the surrounding lines
     for immediate diagnosis.
"""

import os
import re
import javalang
from core.logger import log


_JAVA_DECL = re.compile(r'\b(class|interface|enum|record)\s+\w+', re.MULTILINE)
_DECL_NAME = re.compile(r'\b(?:class|interface|enum|record)\s+(\w+)', re.MULTILINE)

# ---------------------------------------------------------------------------
# Fix 1 — Extend is_modern_java
#
# Previously covered: record, case ->, """, sealed
# Now also covers:
#   - var (Java 10+)
#   - yield (switch expression Java 13+)
#   - instanceof with pattern matching (Java 16+): instanceof String s
#   - @interface (custom annotations — javalang sometimes rejects them)
#   - text block with variable indentation
#   - non-sealed (Java 17+)
#   - permits (Java 17+)
# ---------------------------------------------------------------------------

_MODERN_JAVA_HINTS = [
    # Java 16+ — record class
    re.compile(r'\brecord\s+\w+\s*[(<]'),

    # Java 14+ — switch expression com arrow
    re.compile(r'\bcase\b[^:]*->'),

    # Java 15+ — text block
    re.compile(r'"""'),

    # Java 17+ — sealed e non-sealed
    re.compile(r'\b(?:sealed|non-sealed)\s+(?:class|interface)'),
    re.compile(r'\bpermits\s+\w'),

    # Java 10+ — var local variable
    re.compile(r'\bvar\s+\w+\s*='),

    # Java 16+ — pattern matching instanceof
    re.compile(r'\binstanceof\s+\w+\s+\w+'),

    # Java 13+ — yield em switch
    re.compile(r'\byield\s+'),

    # Annotation declarations (javalang sometimes rejects @interface)
    re.compile(r'public\s+@interface\s+\w+'),
]


def is_modern_java(code: str) -> bool:
    """Detects Java 10+ features that javalang 0.13.0 does not support."""
    for pattern in _MODERN_JAVA_HINTS:
        if pattern.search(code):
            return True
    return False


def extract_type_name(code: str) -> str | None:
    m = _DECL_NAME.search(code)
    return m.group(1) if m else None


def has_invalid_imports(code: str) -> bool:
    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith("import "):
            if any(x in stripped for x in ["..", "springforg", "utijava"]):
                return True
    return False


# ---------------------------------------------------------------------------
# Fix 3 — Log error context snippet
#
# javalang returns JavaSyntaxError with position (line, column).
# On rejection, extract and log the 3 lines around the error
# for immediate diagnosis without having to open the file.
# ---------------------------------------------------------------------------

def _log_syntax_context(code: str, error: Exception) -> None:
    """Logs the lines surrounding a syntax error for immediate diagnosis."""
    lines = code.splitlines()
    error_line = None

    # javalang exposes the position via .position or by parsing the message
    if hasattr(error, 'position') and error.position:
        try:
            error_line = int(error.position[0]) - 1  # 0-indexed
        except (TypeError, IndexError):
            pass

    if error_line is None:
        # Try to extract line number from the error string
        m = re.search(r'line\s+(\d+)', str(error), re.IGNORECASE)
        if m:
            error_line = int(m.group(1)) - 1

    if error_line is not None and 0 <= error_line < len(lines):
        start = max(0, error_line - 2)
        end   = min(len(lines), error_line + 3)
        log("  Error context:", "WARN")
        for i in range(start, end):
            marker = ">>>" if i == error_line else "   "
            log(f"  {marker} L{i+1:3}: {lines[i]}", "WARN")
    else:
        # No position available — log the first lines of the rejected code
        log("  First lines of rejected code:", "WARN")
        for i, line in enumerate(lines[:8]):
            log(f"    L{i+1:3}: {line}", "WARN")


def check_syntax(code: str) -> tuple[bool, str]:
    """
    Attempts to validate syntax with javalang — result is indicative only.

    javalang 0.13.0 is unreliable:
      - Rejects Java 14+ (record, switch expression, var, yield, etc.)
      - Returns JavaSyntaxError with an EMPTY message for both real errors
        and constructs it does not understand
      - Cannot distinguish false positives from real errors

    Therefore:
      - Parse OK → positive signal, accept
      - Parse fails with empty message → accept (not reliable)
      - Parse fails with message + modern Java → accept
      - Parse fails with real message + classic Java → reject + log context

    Maven (mvn clean test) is the definitive syntax validator.
    javalang serves only as a fast pre-filter for gross errors.
    """
    try:
        javalang.parse.parse(code)
        return True, ""
    except javalang.parser.JavaSyntaxError as e:
        error_msg = str(e).strip()

        # Empty message = javalang cannot describe the problem → not reliable
        if not error_msg:
            return True, ""

        # Modern Java that javalang does not support
        if is_modern_java(code):
            return True, ""

        # Only case that rejects: descriptive message + classic Java
        _log_syntax_context(code, e)
        return False, f"Syntax error: {error_msg[:120]}"

    except Exception as e:
        # Any other exception without a message → accept
        if not str(e).strip() or is_modern_java(code):
            return True, ""
        return False, f"Parse failed: {type(e).__name__}: {str(e)[:80]}"


def is_valid_java(original: str, new: str) -> tuple[bool, str]:
    """Validation pipeline — structural checks only."""

    if not new or not new.strip():
        return False, "Empty code"

    if '\x1b' in new or '\u001b' in new:
        return False, "ANSI escape detected"

    if not _JAVA_DECL.search(new):
        return False, "No recognizable Java declaration"

    if has_invalid_imports(new):
        return False, "Import with typo"

    if new.count("{") != new.count("}"):
        return False, (
            f"Unbalanced braces: "
            f"{new.count('{')}x'{{' vs {new.count('}')}x'}}'"
        )

    ok, reason = check_syntax(new)
    if not ok:
        return False, reason

    return True, ""
def validate_package_matches_path(code: str, file_path: str) -> tuple[bool, str]:
    """
    Verifies that the declared package matches the actual file path.
    Prevents package hallucinations like 'com.example' instead of the real package.
    """
    pkg_match = re.search(r'^package\s+([\w.]+)\s*;', code, re.MULTILINE)
    if not pkg_match:
        return True, ""

    declared_pkg = pkg_match.group(1)
    norm = file_path.replace("\\", "/")

    for marker in ("/src/main/java/", "/src/test/java/"):
        if marker in norm:
            after_java = norm.split(marker)[-1]
            dir_part = "/".join(after_java.split("/")[:-1])
            expected_pkg = dir_part.replace("/", ".")
            if expected_pkg and declared_pkg != expected_pkg:
                return False, (
                    f"Package '{declared_pkg}' does not match file path "
                    f"(expected: '{expected_pkg}')"
                )
            return True, ""

    return True, ""


def validate_class_name_matches_file(code: str, file_path: str) -> tuple[bool, str]:
    """
    Verifies whether the generated code contains a class/interface/enum
    that matches the physical file name.
    """
    file_name = os.path.basename(file_path).replace(".java", "")
    pattern = rf'(?:public\s+)?(class|interface|enum|record)\s+({file_name})\b'
    
    if re.search(pattern, code):
        return True, ""
    
    any_class = re.search(r'(?:public\s+)?(class|interface|enum|record)\s+(\w+)', code)
    if any_class:
        found_name = any_class.group(2)
        return False, f"File is named '{file_name}.java' but generated class is '{found_name}'."

    return False, f"Class '{file_name}' not found in the generated code."
