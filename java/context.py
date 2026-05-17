"""
java/context.py — Localização: java/context.py

Cache-first: se dep_context para este arquivo já está em cache (por hash),
retorna imediatamente sem fazer os.walk no projeto.

_build_dep_context: lógica original de geração (renomeada de função interna).
_extract_simplified_header: otimizada para emitir apenas assinaturas
  de métodos públicos/protegidos — remove campos privados e comentários.
"""

import os
import re
from core.utils import read_file
from memory.cache import sha12


def get_dependency_context(file_code: str, repo_path: str,
                           cache=None) -> str:
    """
    Retorna contexto de dependências para o arquivo.
    Cache-first: usa hash do conteúdo do arquivo como chave.
    """
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
    """Gera contexto de dependências varrendo o projeto (sem cache)."""
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


def _extract_simplified_header(code: str, full_name: str) -> str:
    """
    Extrai assinaturas de métodos públicos/protegidos.
    Para enums, preserva os valores declarados para evitar alucinação do LLM.
    Para records, injeta CONSTRUCTOR CALL com nomes reais dos parâmetros.
    Remove: campos privados, comentários, imports, corpos de métodos.
    """
    is_enum = bool(re.search(r'\benum\b', code))
    is_record = bool(re.search(r'\brecord\b', code))

    # Pre-extract record constructor hint to avoid @JsonProperty confusion
    constructor_hint = ""
    if is_record:
        record_match = re.search(r'\brecord\s+(\w+)\s*\(([^)]+)\)', code, re.DOTALL)
        if record_match:
            class_name = record_match.group(1)
            params_raw = record_match.group(2).replace('\n', ' ')
            params = [p.strip() for p in params_raw.split(',') if p.strip()]
            param_names = []
            for p in params:
                words = p.split()
                if words:
                    last = words[-1].rstrip(')')
                    if last and last.isidentifier():
                        param_names.append(last)
            if param_names:
                constructor_hint = (
                    f"    // CONSTRUCTOR CALL: new {class_name}("
                    + ", ".join(param_names) + ")"
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

        # Enum: inclui constantes literalmente para o LLM não inventar valores
        if is_enum and in_enum_constants:
            if re.match(r'^[A-Z][A-Z0-9_]+', stripped):
                header_lines.append("    " + stripped)
                if stripped.endswith(';'):
                    in_enum_constants = False
                continue
            # Linha sem padrão de constante encerra a seção
            if not stripped.startswith(('/', '*', '@')):
                in_enum_constants = False

        # Apenas membros públicos/protegidos com parênteses (métodos)
        if ('public ' in stripped or 'protected ' in stripped) and '(' in stripped:
            signature = stripped.split('{')[0].strip()
            if not signature.endswith(';'):
                signature += ";"
            header_lines.append("    " + signature)

    if constructor_hint:
        header_lines.append(constructor_hint)
    header_lines.append("}")
    return f"// Class: {full_name}\n" + "\n".join(header_lines)
