"""
java/llm_runner.py — Runner LLM por arquivo para fases de refatoração semântica.

Contrato idêntico ao community_runner: recebe skill_config + repo_path,
retorna (changed: bool, diff: str).

Fluxo por arquivo:
  1. cache hit → skip
  2. pré-filtro (detect_pattern) → skip se não é candidato
  3. get_dependency_context
  4. call_ai com rules da skill
  5. sem mudança → skip
  6. write_file → mvn compile -q → revert se falhar
  7. marca cache se aceito
"""

import os
import re

from core.logger import log
from core.live_state import update as _live
from core.utils import read_file, write_file, run_cmd, load_skill
from ai.model import call_ai
from java.refactor import get_java_files
from java.compiler import ENV_WRAPPER


def run_skill(skill_config: dict, repo_path: str, cache=None, exec_logger=None) -> tuple[bool, str]:
    # Despacha para o runner método a método quando configurado
    if skill_config.get("method_level") or skill_config.get("class_level"):
        from java.method_runner import run_method_skill
        return run_method_skill(skill_config, repo_path, cache=cache, exec_logger=exec_logger)

    skill_id   = skill_config.get("skill", "unknown")
    min_lines  = skill_config.get("min_lines", 0)
    rules      = _load_rules(skill_config)

    if not rules:
        log(f"[LLMRunner] Nenhuma regra encontrada para '{skill_id}'", "ERR")
        return False, ""

    java_files   = get_java_files(repo_path, tests=False)
    any_changed  = False

    _live(active_skill=skill_id, current_file="")
    log(f"[LLMRunner] {skill_id}: {len(java_files)} arquivos candidatos")

    for file_path in java_files:
        file_name = os.path.basename(file_path)

        if cache and cache.is_phase_done(file_path, skill_id):
            continue

        code = read_file(file_path)
        if not code:
            continue

        if min_lines and len(code.splitlines()) < min_lines:
            if cache:
                cache.mark_phase_done(file_path, skill_id)
            continue

        if _is_structural_type(code, file_path):
            if cache:
                cache.mark_phase_done(file_path, skill_id)
            if exec_logger:
                exec_logger.log_file_skipped(skill_id, file_name, "no_business_logic")
            continue

        if not _needs_refactoring(code, skill_config):
            if cache:
                cache.mark_phase_done(file_path, skill_id)
            if exec_logger:
                exec_logger.log_file_skipped(skill_id, file_name, "pattern_not_found")
            continue

        log(f"  [{skill_id}] processando {file_name}...")
        _live(active_skill=skill_id, current_model="", current_file=file_name)
        if exec_logger:
            exec_logger.log_file_processing(skill_id, file_name, "java", "refactor")

        skip_dep = skill_config.get("skip_dep_context", False)
        dep_context = "" if skip_dep else _get_dep_context(code, repo_path, cache)

        new_code = call_ai(
            code, rules, "refactor", file_name,
            file_path=file_path,
            phase=skill_id,
            dep_context=dep_context,
            max_agent=skill_config.get("max_agent"),
        )

        if not new_code or new_code.strip() == code.strip():
            log(f"  [{skill_id}] {file_name} — sem alteração")
            if cache:
                cache.mark_phase_done(file_path, skill_id)
            if exec_logger:
                exec_logger.log_file_skipped(skill_id, file_name, "no_change")
            continue

        write_file(file_path, new_code)

        if _mvn_compile(repo_path):
            log(f"  [{skill_id}] {file_name} — aceito ✓", "OK")
            any_changed = True
            if cache:
                cache.mark_phase_done(file_path, skill_id)
            if exec_logger:
                exec_logger.log_file_accepted(skill_id, file_name, "+refactor")
        else:
            log(f"  [{skill_id}] {file_name} — compile falhou, revertendo", "WARN")
            run_cmd(f'git checkout -- "{file_path}"', cwd=repo_path)
            if exec_logger:
                exec_logger.log_file_reverted(skill_id, file_name, "compile_failed")

        _live(active_skill="")

    diff = _get_diff(repo_path)
    return any_changed, diff


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _load_rules(skill_config: dict) -> str:
    """Carrega regras do yml (inline) ou do SKILL.md referenciado."""
    rules = skill_config.get("rules", "")
    if rules:
        return rules

    skill_name = skill_config.get("skill_name", "") or skill_config.get("skill", "")
    section    = skill_config.get("skill_section", "LLM INSTRUCTIONS")

    if skill_name:
        loaded = load_skill(skill_name, section=section)
        if loaded:
            return loaded

    return ""


def _needs_refactoring(code: str, skill_config: dict) -> bool:
    """Pré-filtro: retorna False se o arquivo não tem o padrão alvo — evita chamada LLM desnecessária."""
    pattern_key = skill_config.get("detect_pattern", "")
    if not pattern_key:
        return True

    detectors = {
        "nested_if":        _has_nested_if,
        "long_method":      _has_long_method,
        "concrete_new":     _has_concrete_new,
        "controller_logic": _has_controller_logic,
    }
    detector = detectors.get(pattern_key)
    return detector(code) if detector else True


def _has_nested_if(code: str) -> bool:
    """True se algum método tem if aninhado com profundidade >= 3."""
    max_if_depth  = 0
    current_depth = 0
    brace_depth   = 0

    for line in code.splitlines():
        stripped = line.strip()
        if re.match(r'if\s*\(', stripped):
            current_depth += 1
            max_if_depth = max(max_if_depth, current_depth)
        brace_depth += stripped.count('{') - stripped.count('}')
        if brace_depth <= 0:
            current_depth = 0

    return max_if_depth >= 3


def _has_long_method(code: str) -> bool:
    """True se algum método tem mais de 30 linhas de corpo."""
    in_method   = False
    brace_depth = 0
    method_lines = 0

    for line in code.splitlines():
        stripped = line.strip()
        if not in_method:
            if re.match(
                r'(public|private|protected)\s[\w<>\[\],\s]+\s+\w+\s*\(',
                stripped,
            ) and '{' in stripped:
                in_method   = True
                brace_depth = stripped.count('{') - stripped.count('}')
                method_lines = 1
        else:
            method_lines += 1
            brace_depth  += stripped.count('{') - stripped.count('}')
            if brace_depth <= 0:
                if method_lines > 30:
                    return True
                in_method   = False
                method_lines = 0
                brace_depth  = 0

    return False


def _has_concrete_new(code: str) -> bool:
    """True se há instanciação direta de serviço/repositório/manager."""
    return bool(re.search(
        r'\bnew\s+[A-Z]\w*(Service|Repository|Manager|Handler|Processor|Impl)\s*\(',
        code,
    ))


def _has_controller_logic(code: str) -> bool:
    """True se é @RestController com padrões de lógica de negócio."""
    if '@RestController' not in code:
        return False
    return bool(re.search(r'(if\s*\(|for\s*\(|while\s*\(|\bswitch\s*\()', code))


def _is_structural_type(code: str, file_path: str = "") -> bool:
    """
    True para tipos sem lógica de negócio que não precisam de refatoração LLM:
    records, interfaces, entidades de persistência (@Document/@Entity) e DTOs.
    """
    # record ou interface — nenhum corpo de lógica
    if re.search(r'(?:public\s+)?(?:record|interface)\s+\w+', code):
        return True
    # entidade de persistência (MongoDB Document, JPA Entity/Table)
    if re.search(r'@(Document|Entity|Table)\b', code):
        return True
    # DTO por convenção de pacote ou sufixo de nome de arquivo
    fname = os.path.basename(file_path)
    if re.search(r'(?i)(Dto|DTO|Request|Response)\.java$', fname):
        return True
    if "/dto/" in file_path.replace("\\", "/"):
        return True
    return False


# mantém nome antigo como alias para não quebrar chamadas existentes
_is_record = _is_structural_type


def _get_dep_context(code: str, repo_path: str, cache) -> str:
    try:
        from java.context import get_dependency_context
        return get_dependency_context(code, repo_path, cache)
    except Exception:
        return ""


def _mvn_compile(repo_path: str) -> bool:
    cmd  = ENV_WRAPPER.format("mvn compile -q")
    code, _, _ = run_cmd(cmd, cwd=repo_path)
    return code == 0


def _get_diff(repo_path: str) -> str:
    code, out, _ = run_cmd("git diff --unified=5", cwd=repo_path)
    return out if code == 0 else ""
