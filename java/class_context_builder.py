"""
java/class_builder.py — Builds class representations for LLM prompts.

Three operations:
1. build_method_context  — class skeleton + full target method
2. compress_done_methods — replaces already-refactored bodies with /* [refactored] */
3. merge_method          — recomposes the original file with the LLM-updated method
"""

import re
from java.method_extractor import MethodDef, extract_methods


# ---------------------------------------------------------------------------
# 1. Context for individual method refactoring
# ---------------------------------------------------------------------------

def build_method_context(code: str, target: MethodDef, flow_context: str = "") -> str:
    """
    Returns a context prompt for the LLM to refactor only the target method:

        [IMPORTS & CLASS DECLARATION]
        [FIELDS]
        [OTHER METHODS — signatures only]
        [TARGET METHOD — full body]
        [FLOW CONTEXT — optional]

    The LLM must return ONLY the modified target method (not the full class).
    """
    skeleton = _build_class_skeleton(code, target)
    parts = [skeleton]

    if flow_context:
        parts.append(
            "### FLOW CONTEXT\n"
            f"{flow_context}\n"
            "Use this context to understand the business semantics of the method.\n"
        )

    parts.append(
        "### TARGET METHOD (refactor ONLY this method — return ONLY the method, not the full class)\n"
        f"```java\n{target.full_text}\n```"
    )

    return "\n\n".join(parts)


def _build_class_skeleton(code: str, target: MethodDef) -> str:
    """Extracts imports, class declaration, fields, and signatures of other methods."""
    lines = code.splitlines()
    all_methods = extract_methods(code)

    # Lines belonging to a method other than the target → show signature only
    method_line_ranges: list[tuple[int, int, MethodDef]] = []
    for m in all_methods:
        if m.cache_key != target.cache_key:
            method_line_ranges.append((m.start_line, m.end_line, m))

    skeleton_lines: list[str] = []
    i = 1  # 1-indexed
    for line in lines:
        # Check if this line falls inside a non-target method
        in_other_method = False
        for start, end, m in method_line_ranges:
            if start <= i <= end:
                in_other_method = True
                # Emit only the first line (signature) of the method, then skip the rest
                if i == start:
                    sig_line = m.annotations + [m.signature + " { /* ... */ }"]
                    skeleton_lines.append("    " + " ".join(sig_line))
                break
        if not in_other_method:
            skeleton_lines.append(line)
        i += 1

    return (
        "### CLASS SKELETON (other methods shown as signatures only)\n```java\n"
        + "\n".join(skeleton_lines) + "\n```"
    )


# ---------------------------------------------------------------------------
# 2. Compressor — for phases that still need the full class (e.g. solid-dip)
# ---------------------------------------------------------------------------

def compress_done_methods(code: str, done_keys: set[str]) -> str:
    """
    Replaces the body of methods whose keys are in done_keys with /* [refactored] */,
    reducing prompt size.
    """
    if not done_keys:
        return code

    lines = code.splitlines()
    methods = extract_methods(code)
    replacements: list[tuple[int, int, str]] = []  # (start_line, end_line, replacement_text)

    for m in methods:
        if m.cache_key in done_keys:
            # Linha de fechamento reduzida
            ann = "\n".join("    " + a for a in m.annotations)
            compressed = (
                (ann + "\n" if m.annotations else "") +
                f"    {m.signature} {{ /* [refactored] */ }}"
            )
            replacements.append((m.start_line, m.end_line, compressed))

    if not replacements:
        return code

    # Apply replacements bottom-up to avoid shifting line indices
    replacements.sort(key=lambda x: x[0], reverse=True)
    result = lines[:]

    for start, end, replacement in replacements:
        result[start - 1: end] = replacement.splitlines()

    return "\n".join(result)


# ---------------------------------------------------------------------------
# 3. Merge — recomposes the file with the LLM-updated method
# ---------------------------------------------------------------------------

def merge_method(original_code: str, original_method: MethodDef,
                 new_method_text: str) -> str:
    """
    Replaces the original method with the LLM-returned text.
    Preserves all other lines of the file intact.
    """
    new_method_text = _clean_llm_method(new_method_text)
    if not new_method_text:
        return original_code

    lines = original_code.splitlines()
    start = original_method.start_line - 1  # 0-indexed
    end   = original_method.end_line        # exclusive

    # Preserve the original indentation
    indent = _detect_indent(lines[start] if start < len(lines) else "")
    new_lines = [
        (indent + l if l.strip() and not l.startswith(indent) else l)
        for l in new_method_text.splitlines()
    ]

    result = lines[:start] + new_lines + lines[end:]
    return "\n".join(result)


def _clean_llm_method(text: str) -> str:
    """Removes markdown code fences and any text before/after the method."""
    text = re.sub(r'```(?:java)?\n?', '', text).strip()

    # If the LLM returned the full class, extract only the target method
    if re.search(r'\bclass\s+\w+', text):
        methods = extract_methods(text)
        if methods:
            # Return the first non-constructor method, or the constructor if that's all there is
            non_ctors = [m for m in methods if not m.is_constructor]
            return (non_ctors[0] if non_ctors else methods[0]).full_text

    return text


def _detect_indent(line: str) -> str:
    """Detects the indentation prefix of a line."""
    return re.match(r'^(\s*)', line).group(1)


# ---------------------------------------------------------------------------
# Utility: extracts the method text from the LLM response
# ---------------------------------------------------------------------------

def extract_method_from_response(response: str) -> str:
    """
    Extracts the method block from the LLM response.
    The LLM may return: just the method, method in a markdown fence, or the full class.
    """
    fence_match = re.search(r'```(?:java)?\n(.*?)```', response, re.DOTALL)
    if fence_match:
        candidate = fence_match.group(1).strip()
        # If it's a class, extract the method
        if re.search(r'\bclass\s+\w+', candidate):
            methods = extract_methods(candidate)
            if methods:
                non_ctors = [m for m in methods if not m.is_constructor]
                return (non_ctors[0] if non_ctors else methods[0]).full_text
        return candidate

    # No fence — try to detect method directly
    return _clean_llm_method(response)
