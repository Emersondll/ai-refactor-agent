"""
java/class_builder.py — Constrói representações da classe para prompts LLM.

Três operações:
1. build_method_context  — esqueleto da classe + método alvo completo
2. compress_done_methods — substitui corpos já refatorados por /* [refactored] */
3. merge_method          — recompõe o arquivo original com o método atualizado pelo LLM
"""

import re
from java.method_extractor import MethodDef, extract_methods


# ---------------------------------------------------------------------------
# 1. Contexto para refatoração de método individual
# ---------------------------------------------------------------------------

def build_method_context(code: str, target: MethodDef, flow_context: str = "") -> str:
    """
    Retorna prompt de contexto para o LLM refatorar apenas o método alvo:

        [IMPORTS & CLASS DECLARATION]
        [FIELDS]
        [OTHER METHODS — signatures only]
        [TARGET METHOD — full body]
        [FLOW CONTEXT — optional]

    O LLM deve devolver APENAS o método alvo modificado (não a classe inteira).
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
    """Extrai imports, declaração de classe, campos e assinaturas dos demais métodos."""
    lines = code.splitlines()
    all_methods = extract_methods(code)

    # Linhas que pertencem a algum método (exceto o alvo) → mostrar só assinatura
    method_line_ranges: list[tuple[int, int, MethodDef]] = []
    for m in all_methods:
        if m.cache_key != target.cache_key:
            method_line_ranges.append((m.start_line, m.end_line, m))

    skeleton_lines: list[str] = []
    i = 1  # 1-indexed
    for line in lines:
        # Verifica se essa linha cai dentro de um método não-alvo
        in_other_method = False
        for start, end, m in method_line_ranges:
            if start <= i <= end:
                in_other_method = True
                # Emite apenas a primeira linha (assinatura) do método, depois pula o resto
                if i == start:
                    sig_line = m.annotations + [m.signature + " { /* ... */ }"]
                    skeleton_lines.append("    " + " ".join(sig_line))
                break
        if not in_other_method:
            skeleton_lines.append(line)
        i += 1

    return "### CLASS SKELETON (other methods shown as signatures only)\n```java\n" + \
           "\n".join(skeleton_lines) + "\n```"


# ---------------------------------------------------------------------------
# 2. Compressor — para fases que ainda precisam da classe (ex: solid-dip)
# ---------------------------------------------------------------------------

def compress_done_methods(code: str, done_keys: set[str]) -> str:
    """
    Substitui o corpo dos métodos cujas chaves estão em done_keys
    por /* [refactored] */, reduzindo o tamanho do prompt.
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

    # Aplica substituições de baixo para cima para não deslocar índices
    replacements.sort(key=lambda x: x[0], reverse=True)
    result = lines[:]

    for start, end, replacement in replacements:
        result[start - 1: end] = replacement.splitlines()

    return "\n".join(result)


# ---------------------------------------------------------------------------
# 3. Merge — recompõe o arquivo com o método atualizado pelo LLM
# ---------------------------------------------------------------------------

def merge_method(original_code: str, original_method: MethodDef,
                 new_method_text: str) -> str:
    """
    Substitui o método original pelo texto retornado pelo LLM.
    Preserva todo o resto do arquivo intacto.
    """
    new_method_text = _clean_llm_method(new_method_text)
    if not new_method_text:
        return original_code

    lines = original_code.splitlines()
    start = original_method.start_line - 1  # 0-indexed
    end   = original_method.end_line        # exclusive

    # Preserva a indentação original
    indent = _detect_indent(lines[start] if start < len(lines) else "")
    new_lines = [
        (indent + l if l.strip() and not l.startswith(indent) else l)
        for l in new_method_text.splitlines()
    ]

    result = lines[:start] + new_lines + lines[end:]
    return "\n".join(result)


def _clean_llm_method(text: str) -> str:
    """Remove markdown code fences e texto antes/depois do método."""
    # Remove ```java ... ``` ou ``` ... ```
    text = re.sub(r'```(?:java)?\n?', '', text).strip()

    # Se o LLM retornou a classe inteira, extrai apenas o método alvo
    if re.search(r'\bclass\s+\w+', text):
        methods = extract_methods(text)
        if methods:
            # Retorna o primeiro método não-construtor, ou o construtor se só houver isso
            non_ctors = [m for m in methods if not m.is_constructor]
            return (non_ctors[0] if non_ctors else methods[0]).full_text

    return text


def _detect_indent(line: str) -> str:
    """Detecta o prefixo de indentação de uma linha."""
    return re.match(r'^(\s*)', line).group(1)


# ---------------------------------------------------------------------------
# Utilitário: extrai o texto do método da resposta do LLM
# ---------------------------------------------------------------------------

def extract_method_from_response(response: str) -> str:
    """
    Extrai o bloco de método da resposta do LLM.
    O LLM pode retornar: só o método, método em markdown fence, ou classe inteira.
    """
    # Tenta extrair bloco java de markdown
    fence_match = re.search(r'```(?:java)?\n(.*?)```', response, re.DOTALL)
    if fence_match:
        candidate = fence_match.group(1).strip()
        # Se é uma classe, extrai o método
        if re.search(r'\bclass\s+\w+', candidate):
            methods = extract_methods(candidate)
            if methods:
                non_ctors = [m for m in methods if not m.is_constructor]
                return (non_ctors[0] if non_ctors else methods[0]).full_text
        return candidate

    # Sem fence — tenta detectar método diretamente
    return _clean_llm_method(response)
