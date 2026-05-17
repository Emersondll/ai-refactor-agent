"""
java/method_runner.py — Runner LLM método a método.

Fluxo por arquivo:
  1. Extrai todos os métodos do arquivo
  2. Para cada método não processado:
     a. Verifica se precisa de refatoração (_needs_method_refactoring)
     b. Monta contexto: esqueleto da classe + método alvo + contexto do fluxo
     c. Chama LLM — instrui a devolver APENAS o método modificado
     d. Extrai o método da resposta e faz merge no arquivo
     e. mvn compile — aceita ou reverte
     f. Marca método no cache
  3. Para fases que precisam da classe inteira (ex: solid-dip):
     comprime os métodos já feitos e envia a classe condensada

Integração:
  Chamado por llm_runner quando skill_config tem 'method_level: true'.
  Para skill_config com 'method_level: false' (solid-dip), usa class_compressor.
"""

import os
import re

from core.logger import log
from core.live_state import update as _live
from core.utils import read_file, write_file, run_cmd, load_skill
from ai.model import call_ai
from java.refactor import get_java_files
from java.compiler import ENV_WRAPPER
from java.method_extractor import extract_methods, MethodDef
from java.class_builder import (
    build_method_context,
    compress_done_methods,
    merge_method,
    extract_method_from_response,
)


def run_method_skill(skill_config: dict, repo_path: str,
                     cache=None, exec_logger=None) -> tuple[bool, str]:
    """
    Runner método a método. Usado por llm_runner quando method_level=true.
    Retorna (any_changed, diff).
    """
    skill_id         = skill_config.get("skill", "unknown")
    rules            = _load_rules(skill_config)
    class_level      = skill_config.get("class_level", False)
    skip_compression = skill_config.get("skip_compression", False)

    if not rules:
        log(f"[MethodRunner] Nenhuma regra para '{skill_id}'", "ERR")
        return False, ""

    java_files  = get_java_files(repo_path, tests=False)
    any_changed = False

    _live(active_skill=skill_id, current_file="")
    log(f"[MethodRunner] {skill_id}: {len(java_files)} arquivos candidatos")

    for file_path in java_files:
        file_name = os.path.basename(file_path)

        # Skip arquivo inteiro já processado em todas as fases relevantes
        if cache and cache.is_phase_done(file_path, skill_id):
            continue

        code = read_file(file_path)
        if not code:
            continue

        from java.llm_runner import _is_structural_type
        if _is_structural_type(code, file_path):
            if cache:
                cache.mark_phase_done(file_path, skill_id)
            if exec_logger:
                exec_logger.log_file_skipped(skill_id, file_name, "no_business_logic")
            continue

        if class_level:
            changed = _run_class_level(
                file_path, file_name, code, rules, skill_id,
                repo_path, cache, exec_logger,
                skip_compression=skip_compression,
            )
        else:
            # Fase method-level: itera método a método
            changed = _run_method_level(
                file_path, file_name, code, rules, skill_id,
                repo_path, cache, exec_logger,
                skill_config=skill_config,
            )

        if changed:
            any_changed = True

    diff = _get_diff(repo_path)
    return any_changed, diff


# ---------------------------------------------------------------------------
# Refatoração método a método
# ---------------------------------------------------------------------------

def _run_method_level(file_path: str, file_name: str, code: str,
                      rules: str, skill_id: str, repo_path: str,
                      cache, exec_logger, skill_config: dict) -> bool:
    """Itera sobre cada método do arquivo, refatorando individualmente."""
    # C1: controller-lean só deve rodar em classes @RestController
    if skill_config.get("detect_pattern") == "controller_logic" and "@RestController" not in code:
        if cache:
            cache.mark_phase_done(file_path, skill_id)
        if exec_logger:
            exec_logger.log_file_skipped(skill_id, file_name, "not_a_controller")
        return False

    methods = extract_methods(code)
    if not methods:
        if cache:
            cache.mark_phase_done(file_path, skill_id)
        return False

    detect_fn = _get_method_detector(skill_config.get("detect_pattern", ""))
    file_changed = False

    for method in methods:
        if method.is_constructor:
            continue  # construtores não são refatorados nessas fases

        # Cache em nível de método
        if cache and cache.is_method_done(file_path, method.cache_key, skill_id):
            continue

        # Pré-filtro: o método precisa do padrão alvo?
        if detect_fn and not detect_fn(method.body):
            if cache:
                cache.mark_method_done(file_path, method.cache_key, skill_id)
            continue

        log(f"  [{skill_id}] {file_name}::{method.cache_key[:60]}...")
        _live(active_skill=skill_id, current_file=f"{file_name}")

        if exec_logger:
            exec_logger.log_file_processing(skill_id, f"{file_name}::{_short_sig(method)}", "java", "refactor")

        # Lê o código atual do arquivo (pode ter sido modificado por métodos anteriores)
        current_code = read_file(file_path)
        current_methods = extract_methods(current_code)
        current_method = _find_method(current_methods, method.cache_key)
        if not current_method:
            # Método não encontrado após edições anteriores — pula
            if cache:
                cache.mark_method_done(file_path, method.cache_key, skill_id)
            continue

        # Monta prompt: esqueleto + método alvo
        method_context = build_method_context(current_code, current_method)
        method_rules = (
            f"{rules}\n\n"
            "### REFACTORING SCOPE\n"
            "Refactor ONLY the TARGET METHOD shown above.\n"
            "Return ONLY the refactored method (annotations + signature + body).\n"
            "Do NOT return the full class. Do NOT modify any other method.\n"
            "Do NOT change the method signature or return type.\n"
        )

        response = call_ai(
            current_method.full_text,
            method_rules,
            "refactor",
            file_name,
            file_path=file_path,
            phase=skill_id,
            dep_context=method_context,
            max_agent=skill_config.get("max_agent"),
        )

        if not response:
            if cache:
                cache.mark_method_done(file_path, method.cache_key, skill_id)
            continue

        new_method_text = extract_method_from_response(response)
        if not new_method_text or _normalize(new_method_text) == _normalize(current_method.full_text):
            log(f"  [{skill_id}] {file_name}::{_short_sig(method)} — sem alteração")
            if cache:
                cache.mark_method_done(file_path, method.cache_key, skill_id)
            continue

        # Merge: substitui apenas o método no arquivo
        updated_code = merge_method(current_code, current_method, new_method_text)
        write_file(file_path, updated_code)

        if _mvn_compile(repo_path):
            log(f"  [{skill_id}] {file_name}::{_short_sig(method)} — aceito ✓", "OK")
            file_changed = True
            if cache:
                cache.mark_method_done(file_path, method.cache_key, skill_id)
            if exec_logger:
                exec_logger.log_file_accepted(skill_id, f"{file_name}::{_short_sig(method)}", "+refactor")
        else:
            log(f"  [{skill_id}] {file_name}::{_short_sig(method)} — compile falhou, revertendo", "WARN")
            write_file(file_path, current_code)  # reverte para antes do merge
            if exec_logger:
                exec_logger.log_file_reverted(skill_id, f"{file_name}::{_short_sig(method)}", "compile_failed")

        _live(active_skill="")

    # Marca o arquivo como concluído quando todos os métodos foram avaliados
    if cache:
        cache.mark_phase_done(file_path, skill_id)

    return file_changed


# ---------------------------------------------------------------------------
# Refatoração class-level com compressão de métodos já feitos
# ---------------------------------------------------------------------------

def _run_class_level(file_path: str, file_name: str, code: str,
                     rules: str, skill_id: str, repo_path: str,
                     cache, exec_logger, skip_compression: bool = False) -> bool:
    """
    Envia a classe ao LLM para refatoração estrutural (ex: solid-dip).
    skip_compression=True: envia o código original completo, sem compressão de métodos.
    skip_compression=False: comprime métodos já processados para reduzir tokens.
    """
    if skip_compression:
        payload = code
        log(f"  [{skill_id}] {file_name} — classe completa ({len(code.splitlines())} linhas, sem compressão)")
    else:
        done_keys: set[str] = set()
        if cache:
            for phase in ("guard-clauses", "controller-lean", "method-extraction"):
                done_keys |= cache.done_method_keys(file_path, phase)
        payload = compress_done_methods(code, done_keys)
        log(f"  [{skill_id}] {file_name} — classe comprimida ({len(payload.splitlines())} linhas vs {len(code.splitlines())} original)")

    _live(active_skill=skill_id, current_file=file_name)

    if exec_logger:
        exec_logger.log_file_processing(skill_id, file_name, "java", "refactor")

    new_code = call_ai(
        payload, rules, "refactor", file_name,
        file_path=file_path,
        phase=skill_id,
    )

    if not new_code or _normalize(new_code) == _normalize(payload):
        log(f"  [{skill_id}] {file_name} — sem alteração")
        if cache:
            cache.mark_phase_done(file_path, skill_id)
        # A3: emite evento rastreável para o dashboard mesmo quando não há mudança
        if exec_logger:
            exec_logger.log_file_skipped(skill_id, file_name, "no_change")
        return False

    write_file(file_path, new_code)

    # A1: repair loop — até MAX_RETRIES tentativas se compile falhar
    from config import MAX_RETRIES as _MAX_RETRIES
    from ai.model import call_ai_with_correction as _repair
    attempt = 0
    while not _mvn_compile(repo_path):
        attempt += 1
        _, stdout, stderr = run_cmd(ENV_WRAPPER.format("mvn compile -q"), cwd=repo_path)
        err_output = (stderr or stdout or "compile error").strip()

        if attempt > _MAX_RETRIES:
            log(f"  [{skill_id}] {file_name} — {attempt - 1} reparos esgotados, revertendo", "WARN")
            run_cmd(f'git checkout -- "{file_path}"', cwd=repo_path)
            if cache:
                cache.mark_phase_done(file_path, skill_id)
            if exec_logger:
                exec_logger.log_file_reverted(skill_id, file_name, "compile_failed")
            return False

        log(f"  [{skill_id}] {file_name} — compile falhou (tentativa {attempt}/{_MAX_RETRIES}), reparando...", "WARN")

        repaired = _repair(
            new_code, rules, "refactor", file_name,
            file_path=file_path,
            bad_output=new_code,
            error_reason=err_output,
            phase=skill_id,
        )
        if not repaired or _normalize(repaired) == _normalize(new_code):
            log(f"  [{skill_id}] {file_name} — reparo sem mudança, revertendo", "WARN")
            run_cmd(f'git checkout -- "{file_path}"', cwd=repo_path)
            if cache:
                cache.mark_phase_done(file_path, skill_id)
            if exec_logger:
                exec_logger.log_file_reverted(skill_id, file_name, "repair_no_change")
            return False
        new_code = repaired
        write_file(file_path, new_code)

    log(f"  [{skill_id}] {file_name} — aceito ✓", "OK")
    if cache:
        cache.mark_phase_done(file_path, skill_id)
    if exec_logger:
        exec_logger.log_file_accepted(skill_id, file_name, "+refactor")
    return True


# ---------------------------------------------------------------------------
# Detectores de padrão em nível de método
# ---------------------------------------------------------------------------

def _get_method_detector(pattern_key: str):
    """Retorna função de detecção para o padrão da skill, em nível de método."""
    detectors = {
        "nested_if":        _method_has_nested_if,
        "long_method":      _method_is_long,
        "controller_logic": _method_has_logic,
    }
    return detectors.get(pattern_key)


def _method_has_nested_if(body: str) -> bool:
    depth = 0
    max_depth = 0
    for line in body.splitlines():
        s = line.strip()
        if re.match(r'if\s*\(', s):
            depth += 1
            max_depth = max(max_depth, depth)
        depth -= s.count('}')
        depth = max(depth, 0)
    return max_depth >= 3


def _method_is_long(body: str) -> bool:
    return len([l for l in body.splitlines() if l.strip()]) > 30


def _method_has_logic(body: str) -> bool:
    return bool(re.search(r'(if\s*\(|for\s*\(|while\s*\(|\bswitch\s*\()', body))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_method(methods: list[MethodDef], cache_key: str) -> MethodDef | None:
    return next((m for m in methods if m.cache_key == cache_key), None)


def _short_sig(method: MethodDef) -> str:
    """Versão curta da assinatura para logs (até 60 chars)."""
    s = method.signature
    return s[:57] + "..." if len(s) > 60 else s


def _normalize(code: str) -> str:
    return re.sub(r'\s+', ' ', code.strip())


def _load_rules(skill_config: dict) -> str:
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


def _mvn_compile(repo_path: str) -> bool:
    cmd = ENV_WRAPPER.format("mvn compile -q")
    code, _, _ = run_cmd(cmd, cwd=repo_path)
    return code == 0


def _get_diff(repo_path: str) -> str:
    code, out, _ = run_cmd("git diff --unified=5", cwd=repo_path)
    return out if code == 0 else ""
