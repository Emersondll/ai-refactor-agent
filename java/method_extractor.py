"""
java/method_extractor.py — Extracts individual methods from Java source code.

Uses brace counting (no AST parser). Supports:
- Instance and static methods
- Constructors
- Multi-line annotations
- Signatures with parameters spanning multiple lines
- Interface inheritance (default methods)
"""

import re
from dataclasses import dataclass, field


@dataclass
class MethodDef:
    signature: str          # "public Result process(Transaction t)"
    annotations: list[str]  # ["@Override", "@Transactional"]
    full_text: str          # annotations + signature + full body
    body: str               # content between { } (without the delimiters themselves)
    start_line: int         # 1-indexed, inclusive (first annotation or signature line)
    end_line: int           # 1-indexed, inclusive (line of the closing })
    is_constructor: bool = False

    @property
    def cache_key(self) -> str:
        """Unique cache key — normalizes whitespace in the signature."""
        return re.sub(r'\s+', ' ', self.signature.strip())


# Pattern that identifies the start of a method declaration
_METHOD_START = re.compile(
    r'^\s*'
    r'(?:(?:public|private|protected)\s+)?'
    r'(?:(?:static|final|synchronized|abstract|default|native)\s+)*'
    r'(?:[\w<>\[\],\s?]+\s+)'   # return type (includes generics)
    r'(\w+)\s*\('               # method name + (
)

# Annotation pattern
_ANNOTATION = re.compile(r'^\s*@\w+')

# Inner class/interface/enum declaration pattern
_INNER_TYPE = re.compile(
    r'^\s*(?:public|private|protected|static)?\s*'
    r'(?:static\s+)?(?:final\s+)?'
    r'(?:class|interface|enum|record)\s+\w+'
)

# Field pattern (instance variable declaration)
_FIELD = re.compile(
    r'^\s*(?:private|protected|public)?\s*'
    r'(?:static\s+)?(?:final\s+)?'
    r'[\w<>\[\],]+\s+\w+\s*(?:=|;)'
)


def extract_methods(code: str) -> list[MethodDef]:
    """
    Extracts all methods (including constructors) from a Java file.
    Ignores fields, inner type declarations, and static blocks.
    """
    lines = code.splitlines()
    methods: list[MethodDef] = []

    i = 0
    class_brace_depth = 0  # depth after the outer class opening {
    class_opened = False

    while i < len(lines):
        line = lines[i]

        # Detect opening of the main class (first { of class/record)
        if not class_opened:
            if re.search(r'(?:class|record|interface|enum)\s+\w+', line) and '{' in line:
                class_opened = True
                class_brace_depth = 1
            i += 1
            continue

        # Track depth inside the class
        # (to avoid inner class methods being confused with top-level)
        stripped = line.strip()

        # Skip blank lines and single-line comments
        if not stripped or stripped.startswith('//'):
            i += 1
            continue

        # Collect annotations before a potential method
        annotations: list[str] = []
        ann_start = i
        while i < len(lines) and _ANNOTATION.match(lines[i]):
            annotations.append(lines[i].strip())
            i += 1
        if i >= len(lines):
            break

        line = lines[i]

        # Ignore inner type declarations
        if _INNER_TYPE.match(line):
            # Advance past the { to adjust depth afterwards
            while i < len(lines) and '{' not in lines[i]:
                i += 1
            i += 1
            continue

        # Ignora campos
        if _FIELD.match(line) and '{' not in line:
            i += 1
            continue

        # Try to find the start of a method
        # The signature may span multiple lines up to the closing )
        sig_start = i
        sig_lines = []
        found_open_paren = False

        # Read until ) { or ; (abstract/interface method without body)
        temp_i = i
        paren_depth = 0
        sig_complete = False

        while temp_i < len(lines):
            sig_line = lines[temp_i]
            sig_lines.append(sig_line)

            for ch in sig_line:
                if ch == '(':
                    paren_depth += 1
                    found_open_paren = True
                elif ch == ')':
                    paren_depth -= 1
                    if paren_depth == 0 and found_open_paren:
                        sig_complete = True

            if sig_complete:
                break
            temp_i += 1

        if not sig_complete or not found_open_paren:
            i += 1
            continue

        # Verify it is actually a method signature (not an if/while/for/catch)
        first_sig_line = sig_lines[0].strip()
        if re.match(r'^(?:if|while|for|catch|switch|else)\s*\(', first_sig_line):
            i += 1
            continue

        # Verify it has a valid modifier or return type
        if not _METHOD_START.match(sig_lines[0]) and not re.match(
            r'^\s*(?:public|private|protected)?\s*\w+\s*\(', sig_lines[0]
        ):
            i = max(i + 1, ann_start + 1)
            continue

        # Build normalized signature — remove { and throws clause
        raw_sig = ' '.join(l.strip() for l in sig_lines)
        signature = re.sub(r'\s+', ' ', raw_sig).strip()
        signature = re.sub(r'\s+throws\s+[\w,\s]+', '', signature)
        signature = re.sub(r'\s*\{.*$', '', signature).strip()  # remove { and everything after it

        # Advance to the line containing the body opening {
        i = temp_i + 1
        # Abstract or interface method without body (ends with ;)
        after_paren = ' '.join(sig_lines).split(')')[-1].strip()
        if after_paren.lstrip().startswith(';') or re.search(r'\)\s*;', ' '.join(sig_lines)):
            continue  # method without body — skip

        # Encontra o { de abertura do corpo
        body_open_line = i - 1
        while body_open_line < len(lines) and '{' not in lines[body_open_line]:
            body_open_line += 1
        if body_open_line >= len(lines):
            continue

        # Collect the full body using brace counting
        brace_depth = 0
        body_lines: list[str] = []
        body_start_line = body_open_line
        j = body_open_line

        while j < len(lines):
            body_lines.append(lines[j])
            for ch in lines[j]:
                if ch == '{':
                    brace_depth += 1
                elif ch == '}':
                    brace_depth -= 1
                    if brace_depth == 0:
                        break
            if brace_depth == 0:
                break
            j += 1

        if brace_depth != 0:
            i = j + 1
            continue  # unbalanced braces — skip

        end_line = j
        full_text_lines = lines[ann_start:end_line + 1]
        full_text = '\n'.join(full_text_lines)

        # Extract body only (between the first { and the last })
        body_text = '\n'.join(body_lines)
        body_inner = re.sub(r'^[^{]*\{', '', body_text, count=1)
        body_inner = re.sub(r'\}[^}]*$', '', body_inner)

        # Detect if it is a constructor (class name, no return type)
        is_ctor = bool(re.match(r'^\s*(?:public|private|protected)?\s*[A-Z]\w*\s*\(', sig_lines[0]))

        methods.append(MethodDef(
            signature=signature,
            annotations=annotations,
            full_text=full_text,
            body=body_inner,
            start_line=ann_start + 1,   # 1-indexed
            end_line=end_line + 1,       # 1-indexed
            is_constructor=is_ctor,
        ))

        i = end_line + 1

    return methods


def method_signature_normalized(sig: str) -> str:
    """Normalizes a signature for use as a cache key."""
    return re.sub(r'\s+', ' ', sig.strip())
