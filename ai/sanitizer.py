import re
from core.utils import force_safe_encoding


# ---------------------------------------------------------------------------
# Invalid character cleanup
# ---------------------------------------------------------------------------

def sanitize_java_code(code: str) -> str:
    code = re.sub(r'\x1B\[[0-?]*[ -/]*[@-~]', '', code)
    code = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', code)
    code = code.replace('\ufeff', '').replace('\u200b', '')
    return code.strip()


# ---------------------------------------------------------------------------
# HTML entities → caracteres reais
# ---------------------------------------------------------------------------

def unescape_html_entities(code: str) -> str:
    """Models sometimes encode < and > as HTML entities inside generics.

    Ex: JpaRepository&lt;Balance, Long&gt;  →  JpaRepository<Balance, Long>
    """
    code = code.replace('&lt;',  '<')
    code = code.replace('&gt;',  '>')
    code = code.replace('&amp;', '&')
    code = code.replace('&apos;', "'")
    code = code.replace('&quot;', '"')
    return code


# ---------------------------------------------------------------------------
# Reconstruct truncated package/import lines
# ---------------------------------------------------------------------------

def fix_package_import_lines(code: str) -> str:
    """Fixes unintended line breaks in package/import declarations.

    Detected patterns:
      1. import without ; at end followed by continuation with .
         import com.example.service    →  import com.example.service.impl;
         .impl;

      2. import without ; followed by standalone ;
         import com.example.Foo        →  import com.example.Foo;
         ;

      3. Truncated import followed by an "orphan" package line (no import keyword):
         import ...MerchantCategoryCodesDocumen;     ← truncated by the model
         com...MerchantCategoryCodesDocument;        ← continuation without "import"

         Fix: replace the truncated import with the complete orphan line.
    """
    # Detect lines that look like a Java package but have no "import" prefix
    _ORPHAN_PKG = re.compile(r'^[a-z][a-zA-Z0-9_]*(\.[a-zA-Z0-9_]+)+;?$')

    lines  = code.splitlines()
    result = []
    i      = 0

    while i < len(lines):
        line     = lines[i]
        stripped = line.strip()

        is_pkg_or_import = (
            stripped.startswith("package ")
            or stripped.startswith("import ")
        )

        if is_pkg_or_import and not stripped.endswith(";"):
            # Cases 1 and 2: merge with following lines
            combined = stripped
            while i + 1 < len(lines):
                nxt = lines[i + 1].strip()
                if nxt in (";", "") or nxt.startswith("."):
                    i += 1
                    if nxt == ";":
                        combined += ";"
                        break
                    elif nxt.startswith("."):
                        combined += nxt
                        if combined.endswith(";"):
                            break
                else:
                    break

            if not combined.endswith(";"):
                combined += ";"
            result.append(combined)

        elif not is_pkg_or_import and _ORPHAN_PKG.match(stripped) and stripped:
            # Case 3: orphan package line after an import
            if result and result[-1].startswith("import "):
                # Replace the previous import (possibly truncated) with this
                # one, which is the more complete form
                fixed = "import " + stripped
                if not fixed.endswith(";"):
                    fixed += ";"
                result[-1] = fixed
                # Do not append the orphan line — it replaces the previous one
            else:
                # Loose line without an import context — prefix with import
                fixed = "import " + stripped
                if not fixed.endswith(";"):
                    fixed += ";"
                result.append(fixed)

        else:
            result.append(line)

        i += 1

    return "\n".join(result)


# ---------------------------------------------------------------------------
# Reconstitui generics quebrados entre linhas
# ---------------------------------------------------------------------------

def _count_open_generics(line: str) -> int:
    """Count unclosed generic brackets on a line, ignoring comparison operators.

    A '<' is treated as a generic opener only when preceded by a word character
    or ')' AND followed (after optional whitespace) by an uppercase letter or '?'.
    This excludes comparisons like '< 0', '< someVar', and shift operators.
    """
    depth = 0
    for i, c in enumerate(line):
        if c == '<':
            prev = line[i - 1] if i > 0 else ''
            if prev.isalnum() or prev in ('_', ')'):
                ahead = line[i + 1:].lstrip()
                if ahead and (ahead[0].isupper() or ahead[0] == '?'):
                    depth += 1
        elif c == '>':
            depth = max(0, depth - 1)
    return depth


def fix_broken_generics(code: str) -> str:
    """Reconstructs generic type declarations broken across lines by the model.

    The model often breaks lines inside a <...> block:
      public interface Foo extends JpaRepository<Balance,
                                                 Long> {

    or without the space:
      JpaRepository<Balance,\\nLong>

    This step joins lines whenever a line ends with a comma inside an open
    generics context (< opened without a matching >).
    """
    lines  = code.splitlines()
    result = []
    i      = 0

    while i < len(lines):
        line = lines[i]

        open_generics = _count_open_generics(line)

        while open_generics > 0 and i + 1 < len(lines):
            i   += 1
            nxt  = lines[i].strip()
            line = line.rstrip() + ' ' + nxt
            # Recount the fully merged line so nested generics are handled correctly
            open_generics = _count_open_generics(line)

        result.append(line)
        i += 1

    return "\n".join(result)


# ---------------------------------------------------------------------------
# Minor fixes for glued tokens
# ---------------------------------------------------------------------------

def fix_common_syntax_issues(code: str) -> str:
    code = re.sub(r'(\w)(public\s|class\s|interface\s|enum\s)', r'\1\n\2', code)
    return code


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------

def clean_output(text: str) -> str | None:
    if not text:
        return None

    text = force_safe_encoding(text)

    m = re.search(r"```java\s*([\s\S]*?)```", text)
    if m:
        return _finalize(m.group(1))

    m = re.search(r"```[\w]*\s*([\s\S]*?)```", text)
    if m:
        return _finalize(m.group(1))

    m = re.search(
        r"^(package\s+[\w.]+|import\s+[\w.]+|/\*\*?"
        r"|public\s+(?:class|interface|enum|record|@interface)"
        r"|class\s+\w|interface\s+\w|enum\s+\w)",
        text, re.MULTILINE,
    )
    if m:
        return _finalize(text[m.start():])

    return None


def _is_brace_balanced(code: str) -> bool:
    """Rejects truncated output before Maven — counts { vs } outside strings/comments."""
    depth = 0
    in_string = False
    in_char = False
    in_line_comment = False
    in_block_comment = False
    i = 0
    while i < len(code):
        c = code[i]
        if in_line_comment:
            if c == '\n':
                in_line_comment = False
        elif in_block_comment:
            if c == '*' and i + 1 < len(code) and code[i + 1] == '/':
                in_block_comment = False
                i += 1
        elif in_string:
            if c == '\\':
                i += 1
            elif c == '"':
                in_string = False
        elif in_char:
            if c == '\\':
                i += 1
            elif c == "'":
                in_char = False
        else:
            if c == '/' and i + 1 < len(code) and code[i + 1] == '/':
                in_line_comment = True
                i += 1
            elif c == '/' and i + 1 < len(code) and code[i + 1] == '*':
                in_block_comment = True
                i += 1
            elif c == '"':
                in_string = True
            elif c == "'":
                in_char = True
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
        i += 1
    return depth == 0


_MAX_LINE_LEN = 500


def _has_collapsed_line(code: str) -> bool:
    """Returns True if any non-blank line exceeds _MAX_LINE_LEN characters.

    A collapsed output (multiple statements merged onto one line by
    fix_broken_generics or similar) will exceed this threshold and should be
    rejected so the pipeline retries rather than committing broken formatting.
    """
    return any(len(line) > _MAX_LINE_LEN for line in code.splitlines() if line.strip())


def _finalize(code: str) -> str | None:
    code = sanitize_java_code(code)
    code = unescape_html_entities(code)
    code = fix_package_import_lines(code)
    code = fix_broken_generics(code)
    code = fix_common_syntax_issues(code)
    code = _fix_missing_semicolons(code)
    if not code.strip():
        return None
    if not _is_brace_balanced(code):
        return None  # truncated output — reject before Maven
    if _has_collapsed_line(code):
        return None  # collapsed lines — reject before Maven
    return code.strip()


def _fix_missing_semicolons(code: str) -> str:
    lines = code.splitlines()
    refined = []
    # Skill to fix missing semicolons in obvious locations
    needs_semicolon = re.compile(r'^\s*(return|throw|import|package|int|String|boolean|long|float|double)\b(?!.*;\s*$).*[^;{}]\s*$')
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.endswith((";", "{", "}", ",", "(", ")", ":")):
            refined.append(line)
        elif needs_semicolon.match(line):
            refined.append(line + ";")
        else:
            refined.append(line)
    return "\n".join(refined)