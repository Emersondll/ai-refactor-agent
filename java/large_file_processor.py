"""
java/large_file_processor.py — Reduces processing scope for large files.

Problem solved:
  Files > MAX_FILE_LINES were skipped entirely because 7b models
  truncate context — code came out incomplete or corrupted.

Solution:
  Instead of skipping the file, process it method by method:
    1. Extract the class header (package, imports, fields, constructors)
    2. Extract each method individually
    3. Build a minimal context: header + 1 method at a time
    4. Send that reduced context to the model (< 50 lines in general)
    5. Extract only the refactored method from the response
    6. Replace the method in the original file
    7. Repeat for all methods

Benefits:
  - Files of 200+ lines are now processed
  - 7b models receive a small context (high output quality)
  - Each method is validated individually before being accepted
"""

import re
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class JavaMethod:
    """Represents a method extracted from a Java class."""
    name: str             # method name (e.g. performTransaction)
    signature: str        # full signature (e.g. public void doX(String s))
    full_text: str        # full method text including annotations
    start_line: int       # start line (0-indexed)
    end_line: int         # end line (0-indexed, inclusive)


@dataclass
class ClassHeader:
    """Class header: everything before the first method."""
    text: str             # full header text
    end_line: int         # last line of the header (0-indexed)


# ---------------------------------------------------------------------------
# Detection regexes
# ---------------------------------------------------------------------------

# Detects method start: modifiers + return type + name + parentheses
_METHOD_START = re.compile(
    r'^(\s*)'                                          # indentation
    r'(?:(?:\/\*\*[\s\S]*?\*\/\s*)?)?'               # optional javadoc
    r'(?:@\w+(?:\([^)]*\))?\s*\n\s*)*'               # annotations
    r'(?:public|protected|private|static|final|'
    r'abstract|synchronized|native|\s)+'              # modifiers
    r'[\w<>\[\],\s?]+\s+'                             # return type
    r'(\w+)\s*\(',                                    # method name
    re.MULTILINE,
)

# Detects whether a line is the start of a method (simple, line by line)
_METHOD_LINE = re.compile(
    r'^\s*(?:@\w+(?:\([^)]*\))?\s*)*'
    r'(?:(?:public|protected|private|static|final|abstract|synchronized)\s+)+'
    r'(?:[\w<>\[\],]+\s+)+'
    r'\w+\s*\([^)]*\)\s*(?:throws\s+[\w\s,]+)?\s*\{'
)

# Detects whether a line is a bare annotation
_ANNOTATION_LINE = re.compile(r'^\s*@\w+')


# ---------------------------------------------------------------------------
# Header extraction
# ---------------------------------------------------------------------------

def extract_class_header(code: str) -> ClassHeader:
    """
    Extracts everything before the first method: package, imports, class
    annotations, class declaration, fields, and simple constructors.

    Heuristic: the header ends on the line before the first
    non-constructor method.
    """
    lines = code.splitlines()
    
    # Find the first public/private method with a body
    for i, line in enumerate(lines):
        if _METHOD_LINE.match(line):
            # Return everything up to this line as the header
            # (preserves the blank line before the method)
            end = max(0, i - 1)
            return ClassHeader(
                text='\n'.join(lines[:i]),
                end_line=end,
            )
    
    # No method found — return the entire file as the header
    return ClassHeader(text=code, end_line=len(lines) - 1)


# ---------------------------------------------------------------------------
# Method extraction
# ---------------------------------------------------------------------------

def extract_methods(code: str) -> list[JavaMethod]:
    """
    Extracts all methods from a Java class using brace counting.

    Each method includes its annotations and Javadoc immediately above it.
    """
    lines = code.splitlines()
    methods: list[JavaMethod] = []
    i = 0

    while i < len(lines):
        # Check whether this line (and possible annotation lines above) marks a method start
        if _is_method_start(lines, i):
            # Go back to include annotations and Javadoc above the method
            method_start = _find_annotation_start(lines, i)

            # Advance to find the opening brace
            brace_line = i
            while brace_line < len(lines) and '{' not in lines[brace_line]:
                brace_line += 1

            if brace_line >= len(lines):
                i += 1
                continue

            # Balance braces to find the end of the method
            depth = 0
            j = brace_line
            while j < len(lines):
                depth += lines[j].count('{') - lines[j].count('}')
                if depth == 0:
                    # End of method found
                    full_text = '\n'.join(lines[method_start:j + 1])
                    name = _extract_method_name(lines[i])
                    signature = lines[i].strip()

                    methods.append(JavaMethod(
                        name=name,
                        signature=signature,
                        full_text=full_text,
                        start_line=method_start,
                        end_line=j,
                    ))
                    i = j + 1
                    break
                j += 1
            else:
                i += 1
        else:
            i += 1

    return methods


def _is_method_start(lines: list[str], i: int) -> bool:
    """Returns True if line i is the start of a method declaration."""
    line = lines[i]
    # Ignore bare annotations
    if _ANNOTATION_LINE.match(line) and '(' not in line:
        return False
    return bool(_METHOD_LINE.match(line))


def _find_annotation_start(lines: list[str], i: int) -> int:
    """Go back from line i to include annotations and Javadoc."""
    start = i
    j = i - 1
    while j >= 0:
        stripped = lines[j].strip()
        if stripped.startswith('@') or stripped.startswith('*') or stripped.startswith('/*'):
            start = j
            j -= 1
        elif stripped == '':
            j -= 1
        else:
            break
    return start


def _extract_method_name(signature_line: str) -> str:
    """Extracts the method name from a signature line."""
    m = re.search(r'(\w+)\s*\(', signature_line)
    return m.group(1) if m else 'unknown'


# ---------------------------------------------------------------------------
# Reduced context building
# ---------------------------------------------------------------------------

def build_method_context(header: ClassHeader, method: JavaMethod,
                          close_class: bool = True) -> str:
    """
    Builds a minimal context for the model to process a single method.

    Structure:
        [class header — package, imports, declaration, fields]
        [target method only]
        [class closing: }]

    This ensures the model sees a syntactically complete Java file
    but with only 1 method to refactor — a much smaller context.
    """
    parts = [header.text.rstrip()]
    parts.append('')
    parts.append(method.full_text)
    if close_class:
        parts.append('}')
    return '\n'.join(parts)


# ---------------------------------------------------------------------------
# Extracting the refactored method from the AI response
# ---------------------------------------------------------------------------

def extract_refactored_method(ai_response: str, original_method: JavaMethod) -> str | None:
    """
    Extracts only the refactored method from the AI response.

    The AI receives a complete file (header + 1 method) and returns
    a complete file. We need to extract just the method back out.

    Strategy:
        1. Search for the method name in the response
        2. Balance braces from there
        3. Return only the method block
    """
    if not ai_response:
        return None

    lines = ai_response.splitlines()
    method_name = original_method.name

    # Find the line that declares the method by name
    method_line = None
    for i, line in enumerate(lines):
        if method_name + '(' in line and _METHOD_LINE.match(line):
            method_line = i
            break

    if method_line is None:
        # Try to find without the strict regex
        for i, line in enumerate(lines):
            if method_name + '(' in line and '{' in line:
                method_line = i
                break

    if method_line is None:
        return None

    # Go back to include annotations and Javadoc
    start = _find_annotation_start(lines, method_line)

    # Balance braces to extract the full block
    depth = 0
    found_open = False
    for j in range(method_line, len(lines)):
        depth += lines[j].count('{') - lines[j].count('}')
        if '{' in lines[j]:
            found_open = True
        if found_open and depth == 0:
            return '\n'.join(lines[start:j + 1])

    return None


# ---------------------------------------------------------------------------
# Replacing in the original file
# ---------------------------------------------------------------------------

def replace_method_in_file(original_code: str, method: JavaMethod,
                            new_method_text: str) -> str:
    """
    Replaces the original method with the refactored method in the full file.

    Preserves all other lines of the file intact.
    """
    lines = original_code.splitlines()
    new_lines = (
        lines[:method.start_line]
        + new_method_text.splitlines()
        + lines[method.end_line + 1:]
    )
    return '\n'.join(new_lines)


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------

def is_large_file(code: str, threshold: int = 100) -> bool:
    """
    Returns True if the file should be processed method by method.

    Threshold lower than MAX_FILE_LINES in refactor.py — processes
    files that were previously skipped (200 lines) as well as medium-sized
    files that 7b models handle poorly (100+ lines).
    """
    return len(code.splitlines()) >= threshold


def get_processable_methods(code: str) -> list[JavaMethod]:
    """
    Returns only the methods worth processing individually.
    Excludes: trivial getters/setters (< 5 lines), methods without a body.
    """
    all_methods = extract_methods(code)
    return [
        m for m in all_methods
        if len(m.full_text.splitlines()) >= 4   # exclude trivial 1-3 line methods
    ]
