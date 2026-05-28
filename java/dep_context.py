"""
java/context.py — Dependency context builder for LLM prompts.

Cache-first: if dep_context for this file is already cached (by content hash),
returns immediately without walking the project.

_build_dep_context: core generation logic.
_extract_simplified_header: emits only public/protected method signatures —
  strips private fields and comments.
"""

import os
import re
from core.utils import read_file
from memory.cache import sha12


def get_dependency_context(file_code: str, repo_path: str,
                           cache=None) -> str:
    """Returns dependency context for the file. Cache-first by content hash."""
    if cache is not None:
        file_hash = sha12(file_code)
        cached = cache.get_dep_context(file_hash)
        if cached is not None:
            return cached

    from config import USE_RAG_CONTEXT
    if USE_RAG_CONTEXT:
        from java.rag_context import get_rag_context
        context = get_rag_context(file_code, repo_path)
    else:
        context = _build_dep_context(file_code, repo_path)

    if cache is not None:
        cache.set_dep_context(sha12(file_code), context)

    return context


def _build_dep_context(file_code: str, repo_path: str) -> str:
    """Generates dependency context by walking the project (no cache)."""
    package_match = re.search(r'^package\s+([\w.]+);', file_code, re.MULTILINE)
    target_package = package_match.group(1) if package_match else "unknown"

    all_potential_classes = re.findall(r'\b([A-Z]\w+)\b', file_code)
    imports = re.findall(r'^import\s+([\w.]+);', file_code, re.MULTILINE)
    short_imports = {imp.split('.')[-1]: imp for imp in imports}

    context_parts = [f"// TARGET_CLASS_PACKAGE: {target_package}"]
    processed_classes = set()

    for cls_name, full_imp in short_imports.items():
        if not full_imp.startswith("com."):
            continue
        processed_classes.add(cls_name)
        _add_context_for_class(full_imp, repo_path, context_parts)

    for cls_name in all_potential_classes:
        if cls_name in processed_classes or len(cls_name) < 3:
            continue
        if cls_name in {"String", "Long", "Integer", "BigDecimal", "List",
                        "Map", "Optional", "Set", "Boolean", "Double",
                        "Object", "Override", "Autowired", "Service",
                        "Repository", "Controller", "Entity", "Component"}:
            continue
        found_path = _find_class_file(cls_name, repo_path)
        if found_path:
            rel = os.path.relpath(found_path,
                                  os.path.join(repo_path, "src", "main", "java"))
            full_pkg = rel.replace("/", ".").replace(".java", "")
            _add_context_for_class(full_pkg, repo_path, context_parts)
            processed_classes.add(cls_name)

    if len(context_parts) <= 1:
        return ""

    return "\n--- DEPENDENCY CONTEXT (SIGNATURES) ---\n" + "\n".join(context_parts)


def _add_context_for_class(full_imp: str, repo_path: str,
                            context_parts: list) -> None:
    parts = full_imp.split('.')
    potential_path = os.path.join(repo_path, "src", "main", "java",
                                  *parts) + ".java"
    if os.path.exists(potential_path):
        dep_code = read_file(potential_path)
        header = _extract_simplified_header(dep_code, full_imp)
        context_parts.append(f"// SUGGESTED IMPORT: import {full_imp};")
        context_parts.append(header)


def _find_class_file(class_name: str, repo_path: str) -> str | None:
    main_java = os.path.join(repo_path, "src", "main", "java")
    for root, _, files in os.walk(main_java):
        if f"{class_name}.java" in files:
            return os.path.join(root, f"{class_name}.java")
    return None


def _extract_simplified_header(code: str, full_name: str = "") -> str:
    """
    Extracts public/protected/package-private method signatures.
    For enums: preserves declared values to prevent LLM hallucination.
    For records: injects a CONSTRUCTOR CALL hint with real parameter names.
    Removes: private members, comments, imports, method bodies.
    Keeps: public, protected, package-private — accessible from same-package tests.
    """
    is_enum = bool(re.search(r'\benum\b', code))
    is_record = bool(re.search(r'\brecord\b', code))

    # Pre-extract constructor call hint — includes "Type name" so the LLM knows the
    # exact type of each parameter and doesn't confuse e.g. Long version with BigDecimal.
    constructor_hint = ""
    if is_record:
        name_match = re.search(r'\brecord\s+(\w+)\s*\(', code)
        if name_match:
            class_name = name_match.group(1)
            # Extract params using balanced paren reading — @JsonProperty("x") has an inner )
            start = name_match.end() - 1  # position of the opening '('
            depth, end = 0, start
            for i in range(start, len(code)):
                if code[i] == '(':
                    depth += 1
                elif code[i] == ')':
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            params_raw = code[start + 1:end].replace('\n', ' ')
            params = [p.strip() for p in params_raw.split(',') if p.strip()]
            typed_params = []
            for p in params:
                # Strip annotations and their arguments to isolate "Type name"
                clean = re.sub(r'@\w+(?:\([^)]*\))?\s*', '', p).strip()
                words = clean.split()
                if len(words) >= 2:
                    name = words[-1].rstrip(')')
                    typ  = words[-2].rstrip('>')  # ex.: List<String>
                    if name and name.isidentifier():
                        typed_params.append(f"{typ} {name}")
                elif words:
                    name = words[-1].rstrip(')')
                    if name and name.isidentifier():
                        typed_params.append(name)
            if typed_params:
                constructor_hint = (
                    f"    // CONSTRUCTOR CALL: new {class_name}("
                    + ", ".join(typed_params) + ")"
                )
    elif not is_enum:
        # Regular classes with explicit constructor also get the CONSTRUCTOR CALL hint.
        class_name_match = re.search(r'\bclass\s+(\w+)', code)
        if class_name_match:
            _cls = class_name_match.group(1)
            ctor_match = re.search(
                r'(?:public|protected)\s+' + re.escape(_cls) + r'\s*\(([^)]{3,})\)',
                code, re.DOTALL
            )
            if ctor_match:
                params_raw = ctor_match.group(1).replace('\n', ' ')
                params = [p.strip() for p in params_raw.split(',') if p.strip()]
                typed_params = []
                for p in params:
                    clean = re.sub(r'@\w+(?:\([^)]*\))?\s*', '', p).strip()
                    words = clean.split()
                    if len(words) >= 2:
                        name = words[-1].rstrip(')')
                        typ  = words[-2].rstrip(')')
                        if name and name.isidentifier():
                            typed_params.append(f"{typ} {name}")
                    elif words:
                        name = words[-1].rstrip(')')
                        if name and name.isidentifier():
                            typed_params.append(name)
                if typed_params:
                    constructor_hint = (
                        f"    // CONSTRUCTOR CALL: new {_cls}("
                        + ", ".join(typed_params) + ")"
                    )

    lines = code.splitlines()
    header_lines = []
    class_def_found = False
    in_enum_constants = False

    for line in lines:
        stripped = line.strip()

        if not stripped:
            continue
        if stripped.startswith(('//', '/*', '*', 'import ', 'package ')):
            if stripped.startswith('package '):
                header_lines.append(stripped)
            continue

        if any(kw in stripped for kw in ('class ', 'interface ', 'enum ', 'record ')):
            class_def_found = True
            decl = stripped.split('{')[0].strip()
            header_lines.append(decl + " {")
            if is_enum:
                in_enum_constants = True
            continue

        if not class_def_found:
            continue

        # Enum: include constants verbatim so the LLM does not invent values
        if is_enum and in_enum_constants:
            if re.match(r'^[A-Z][A-Z0-9_]+', stripped):
                header_lines.append("    " + stripped)
                if stripped.endswith(';'):
                    in_enum_constants = False
                continue
            # Line without a constant pattern ends the section
            if not stripped.startswith(('/', '*', '@')):
                in_enum_constants = False

        # Members with parentheses (methods): public, protected, package-private.
        # Skip private members (private static, private final, etc.)
        if re.match(r'private\b', stripped):
            continue
        if '(' in stripped:
            # Skip lines that are method calls or annotations, not declarations.
            # A method declaration starts with a modifier or return type followed by name(
            is_method_decl = bool(re.match(
                r'(?:(?:public|protected|static|abstract|synchronized|final|default)\s+)*'
                r'(?:[\w<>\[\]]+\s+)+\w+\s*\(',
                stripped
            ))
            if is_method_decl:
                signature = stripped.split('{')[0].strip()
                if not signature.endswith(';'):
                    signature += ";"
                header_lines.append("    " + signature)

    if constructor_hint:
        header_lines.append(constructor_hint)
    header_lines.append("}")
    return f"// Class: {full_name}\n" + "\n".join(header_lines)
