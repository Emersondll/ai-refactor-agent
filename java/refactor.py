"""
refactor.py — Localização: java/refactor.py

CORRIGIDO:
  - Ao rejeitar por validator, reencaminha o código inválido + motivo
    de volta ao call_ai para que o modelo corrija especificamente o problema.
  - Máximo de MAX_VALIDATOR_RETRIES ciclos de correção antes de desistir.
"""

import os
import re
import json
from datetime import datetime

from core.logger import log
from core.utils import read_file, write_file
from core.reporter import PhaseReporter
from core.execution_logger import ExecutionLogger
from ai.model import call_ai, call_ai_with_correction
from java.validator import is_valid_java
from java.compiler import maven_test
from java.scope_reducer import (
    is_large_file,
    extract_class_header,
    get_processable_methods,
    build_method_context,
    extract_refactored_method,
    replace_method_in_file,
)


LARGE_FILE_THRESHOLD  = 100
MAX_FILE_LINES        = 500
MAX_VALIDATOR_RETRIES = 2   # tentativas de correção após rejeição do validator


_SKIP_PATTERNS = [
    (re.compile(r'extends\s+\w*Repository\w*\s*<'),
     "Interface JPA pura (generics complexos)"),
    (re.compile(r'@SpringBootApplication'),
     "Classe main Spring Boot"),
    (re.compile(r'@Document\b'),
     "MongoDB @Document — construtor usado em outros arquivos"),
    (re.compile(r'@Entity\b'),
     "JPA @Entity — construtor usado em outros arquivos"),
    (re.compile(r'(?m)^\s*[A-Z][A-Z_0-9]+\s*\([^)]+\)\s*[,;]'),
     "Enum com construtor parametrizado"),
]


# ---------------------------------------------------------------------------
# Solução 5 — Registro de falhas
# ---------------------------------------------------------------------------

class FailedFilesTracker:
    def __init__(self, logs_dir: str = "logs"):
        self._path   = os.path.join(logs_dir, "failed_files.json")
        self._entries: list[dict] = []
        os.makedirs(logs_dir, exist_ok=True)
        if os.path.exists(self._path):
            try:
                with open(self._path) as f:
                    self._entries = json.load(f)
            except Exception:
                self._entries = []

    def record(self, file_path: str, phase: str, reason: str) -> None:
        existing = [(e["file"], e["phase"]) for e in self._entries]
        if (file_path, phase) not in existing:
            self._entries.append({
                "file": file_path, "phase": phase, "reason": reason,
                "timestamp": datetime.now().isoformat(), "retried": False,
            })
            self._save()
            log(f"  → failed_files.json: {os.path.basename(file_path)}", "WARN")

    def _save(self):
        with open(self._path, "w") as f:
            json.dump(self._entries, f, indent=2, ensure_ascii=False)

    def get_pending(self) -> list[dict]:
        return [e for e in self._entries if not e["retried"]]

    def mark_retried(self, file_path: str, phase: str):
        for e in self._entries:
            if e["file"] == file_path and e["phase"] == phase:
                e["retried"] = True
        self._save()


_failed_tracker: FailedFilesTracker | None = None


def get_failed_tracker(logs_dir: str = "logs") -> FailedFilesTracker:
    global _failed_tracker
    if _failed_tracker is None:
        _failed_tracker = FailedFilesTracker(logs_dir)
    return _failed_tracker


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

def should_skip(file_path: str, code: str) -> tuple[bool, str]:
    if len(code.splitlines()) > MAX_FILE_LINES:
        return True, f"Arquivo muito grande ({len(code.splitlines())} linhas)"
    for pattern, reason in _SKIP_PATTERNS:
        if pattern.search(code):
            return True, reason
    return False, ""


def _mode_for(file_path: str) -> str:
    return "test" if "/test/" in file_path.replace("\\", "/") else "refactor"


def get_java_files(repo_path: str, tests: bool = False) -> list[str]:
    files = []
    for root, _, fs in os.walk(repo_path):
        if "target" in root.replace("\\", "/").split("/"):
            continue
        for f in fs:
            if not f.endswith(".java"):
                continue
            full       = os.path.join(root, f)
            normalized = full.replace("\\", "/")
            in_test    = "/test/" in normalized
            if tests and in_test:
                files.append(full)
            elif not tests and not in_test:
                files.append(full)
    return files


def _test_path_for(main_file: str, repo_path: str) -> str | None:
    normalized = main_file.replace("\\", "/")
    if "/main/" not in normalized:
        return None
    test_path = normalized.replace("/main/", "/test/")
    base, _   = os.path.splitext(test_path)
    return base + "Test.java"


# ---------------------------------------------------------------------------
# Ciclo de geração + validação com correção
# ---------------------------------------------------------------------------

from java.context import get_dependency_context

def _generate_and_validate(original: str, rules: str, mode: str,
                             file_name: str, file_path: str, phase: str = "") -> tuple[str | None, str]:
    """
    Chama a IA e valida o resultado com injeção de contexto de dependências.
    """
    # Skill: Contexto de Dependências do Repositório
    repo_path = os.path.dirname(os.path.dirname(file_path)) # Tentativa de achar o repo root
    # Na verdade, o repo_path é passado para refactor_file. 
    # Vou ajustar para que _generate_and_validate o receba ou use o original.
    
    # Para este teste, vamos assumir que o repo_path pode ser derivado ou passado.
    # Vou buscar o repo_path real no escopo superior.
    
    dep_context = ""
    try:
        # Busca no diretório pai até achar o root do repo (onde tem .git ou pom.xml)
        root = file_path
        while root != "/" and not os.path.exists(os.path.join(root, "pom.xml")):
            root = os.path.dirname(root)
        if os.path.exists(os.path.join(root, "pom.xml")):
            dep_context = get_dependency_context(original, root)
    except: pass

    enriched_rules = rules + "\n" + dep_context

    # Primeira tentativa normal
    new_code = call_ai(original, enriched_rules, mode, file_name, file_path=file_path, phase=phase)

    if not new_code:
        return None, "IA não gerou código"

    valid, reason = is_valid_java(original, new_code)
    if valid:
        return new_code, ""

    log(f"  Validator rejeitou: {reason} — tentando correção", "WARN")

    # Ciclos de correção
    rejected_code = new_code
    for attempt in range(1, MAX_VALIDATOR_RETRIES + 1):
        log(f"  Correção validator {attempt}/{MAX_VALIDATOR_RETRIES}: {reason[:60]}")

        corrected = call_ai_with_correction(
            original      = original,
            rules         = rules,
            mode          = mode,
            file_name     = file_name,
            file_path     = file_path,
            bad_output    = rejected_code,
            error_reason  = reason,
            phase         = phase
        )

        if not corrected:
            log(f"  Correção {attempt}: sem resposta", "WARN")
            break

        valid, reason = is_valid_java(original, corrected)
        if valid:
            log(f"  Correção {attempt}: aceita ✓", "OK")
            return corrected, ""

        log(f"  Correção {attempt}: ainda rejeitado — {reason}", "WARN")
        rejected_code = corrected

    return None, reason


# ---------------------------------------------------------------------------
# Refatoração — arquivo inteiro
# ---------------------------------------------------------------------------

def _refactor_whole_file(file: str, original: str, rules: str,
                          repo_path: str, phase: str,
                          reporter: PhaseReporter,
                          exec_logger: ExecutionLogger | None) -> bool:
    file_name = os.path.basename(file)
    mode      = _mode_for(file)

    new_code, reason = _generate_and_validate(original, rules, mode, file_name, file, phase=phase)

    if not new_code:
        log(f"  {file_name}: falhou — {reason}", "WARN")
        get_failed_tracker().record(file, phase, reason)
        if exec_logger:
            exec_logger.log_ai_failure(phase, file_name, "all-agents", reason)
        if "não gerou" in reason:
            reporter.record_skipped(phase, file_name, reason)
        else:
            reporter.record_rejected(phase, file_name, reason)
        return False

    write_file(file, new_code)
    success, build_output = maven_test(repo_path)

    if not success:
        log(f"  {file_name}: Build falhou. Analisando impacto global...", "WARN")
        
        # Skill: Detecção de Impacto em Cascata
        if "cannot find symbol" in build_output:
            log("  [Impacto Detectado] Mudança de contrato detectada. Tentando sincronização contextual...", "PHASE")
            _attempt_global_sync(build_output, repo_path, rules, phase)
            success, build_output = maven_test(repo_path)
            if success:
                log(f"  {file_name}: Sincronização global restaurou o build! ✓", "OK")

    if not success:
        log(f"  {file_name}: Build persiste com erro. Ativando Auto-Cura local...", "WARN")
        # Extrai linhas de erro para a IA
        error_lines = [l for l in build_output.splitlines() if "[ERROR]" in l][:10]
        error_msg = "\n".join(error_lines) or "Unknown Build Error (Maven)"
        
        corrected_code = call_ai_with_correction(
            original     = original,
            rules        = rules,
            mode         = mode,
            file_name    = file_name,
            file_path    = file,
            bad_output   = new_code,
            error_reason = f"Maven Build Error:\n{error_msg}",
            phase        = phase
        )

        if corrected_code:
            write_file(file, corrected_code)
            success, _ = maven_test(repo_path)
            if success:
                log(f"  {file_name}: Auto-Cura bem sucedida! ✓", "OK")
                new_code = corrected_code
            else:
                log(f"  {file_name}: Auto-Cura falhou.", "ERR")
                write_file(file, original)
                get_failed_tracker().record(file, phase, "build quebrou (auto-cura falhou)")
                return False
        else:
            write_file(file, original)
            log(f"  {file_name} REVERTIDO: build quebrou e IA não corrigiu", "WARN")
            get_failed_tracker().record(file, phase, "build quebrou")
            return False

    reporter.record_changed(phase, file_name, file, original, new_code)
    if exec_logger:
        exec_logger.log_file_accepted(phase, file_name, "+refactor")
    log(f"  {file_name} REFATORADO ✓", "OK")
    return True


# ---------------------------------------------------------------------------
# Refatoração — método a método
# ---------------------------------------------------------------------------

def _refactor_by_method(file: str, original: str, rules: str,
                         repo_path: str, phase: str,
                         reporter: PhaseReporter,
                         exec_logger: ExecutionLogger | None) -> bool:
    file_name = os.path.basename(file)
    mode      = _mode_for(file)

    header  = extract_class_header(original)
    methods = get_processable_methods(original)

    if not methods:
        log(f"  {file_name}: nenhum método extraível — tentando arquivo inteiro")
        return _refactor_whole_file(file, original, rules, repo_path, phase,
                                    reporter, exec_logger)

    log(f"  {file_name}: {len(methods)} métodos a processar")

    current_code    = original
    methods_changed = 0
    methods_failed  = 0

    for method in methods:
        log(f"    → {method.name}() [{len(method.full_text.splitlines())}L]")

        context = build_method_context(header, method)

        # Usa o mesmo ciclo de correção para métodos individuais
        ai_response, reason = _generate_and_validate(
            original  = context,
            rules     = rules,
            mode      = mode,
            file_name = file_name,
            file_path = file,
            phase     = phase,
        )

        if not ai_response:
            log(f"      {method.name}: {reason}", "WARN")
            methods_failed += 1
            continue

        new_method_text = extract_refactored_method(ai_response, method)

        if not new_method_text:
            log(f"      {method.name}: método não encontrado na resposta", "WARN")
            methods_failed += 1
            continue

        if new_method_text.strip() == method.full_text.strip():
            log(f"      {method.name}: sem alteração")
            continue

        updated_code = replace_method_in_file(current_code, method, new_method_text)
        valid_full, reason_full = is_valid_java(current_code, updated_code)
        if not valid_full:
            log(f"      {method.name}: inválido após substituição: {reason_full}", "WARN")
            methods_failed += 1
            continue

        current_code = updated_code
        methods_changed += 1
        log(f"      {method.name}: OK ✓")

    if methods_changed == 0:
        if methods_failed > 0:
            get_failed_tracker().record(
                file, phase, f"todos os {methods_failed} métodos falharam"
            )
        log(f"  {file_name}: nenhum método alterado", "WARN")
        reporter.record_skipped(phase, file_name, "nenhum método alterado")
        return False

    write_file(file, current_code)
    success, _ = maven_test(repo_path)

    if not success:
        write_file(file, original)
        log(f"  {file_name} REVERTIDO após {methods_changed} métodos", "WARN")
        get_failed_tracker().record(file, phase, "build quebrou após refatoração")
        if exec_logger:
            exec_logger.log_file_reverted(phase, file_name)
        reporter.record_build_failed(phase, file_name)
        return False

    reporter.record_changed(phase, file_name, file, original, current_code)
    if exec_logger:
        exec_logger.log_file_accepted(phase, file_name, f"+{methods_changed}methods")
    log(f"  {file_name} REFATORADO ✓ ({methods_changed} métodos)", "OK")
    return True


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

def refactor_file(file: str, rules: str, repo_path: str,
                  phase: str, reporter: PhaseReporter,
                  exec_logger: ExecutionLogger | None = None) -> bool:
    file_name = os.path.basename(file)

    log(f"Processando [{_mode_for(file)}]: {file_name}")

    if exec_logger:
        exec_logger.log_file_processing(phase, file_name, "unknown", "unknown")

    original = read_file(file)

    skip, reason = should_skip(file, original)
    if skip:
        log(f"  {file_name} PULADO: {reason}", "WARN")
        if exec_logger:
            exec_logger.log_file_skipped(phase, file_name, reason)
        reporter.record_skipped(phase, file_name, reason)
        return False

    if is_large_file(original, LARGE_FILE_THRESHOLD):
        log(f"  {file_name}: arquivo grande → processamento por método")
        return _refactor_by_method(file, original, rules, repo_path, phase,
                                   reporter, exec_logger)
    else:
        return _refactor_whole_file(file, original, rules, repo_path, phase,
                                    reporter, exec_logger)


# ---------------------------------------------------------------------------
# Geração de testes
# ---------------------------------------------------------------------------

def generate_tests(repo_path: str, phase: str, rules: str,
                   reporter: PhaseReporter,
                   exec_logger: ExecutionLogger | None = None) -> bool:
    any_changed = False
    main_files  = get_java_files(repo_path, tests=False)

    for main_file in main_files:
        original  = read_file(main_file)
        file_name = os.path.basename(main_file)

        skip, _ = should_skip(main_file, original)
        if skip:
            continue

        test_path = _test_path_for(main_file, repo_path)
        if not test_path or os.path.exists(test_path):
            continue

        test_name = os.path.basename(test_path)
        log(f"  Gerando teste: {test_name}")

        if exec_logger:
            exec_logger.log_file_processing(phase, test_name, "test", "new")

        # Usa ciclo de correção também para testes
        test_code, reason = _generate_and_validate(
            original  = original,
            rules     = rules,
            mode      = "test",
            file_name = file_name,
            file_path = test_path,
            phase     = phase,
        )

        if not test_code:
            log(f"  {test_name}: {reason}", "WARN")
            get_failed_tracker().record(test_path, phase, reason)
            if exec_logger:
                exec_logger.log_ai_failure(phase, test_name, "all-agents", reason)
            reporter.record_skipped(phase, test_name, reason)
            continue

        os.makedirs(os.path.dirname(test_path), exist_ok=True)
        write_file(test_path, test_code)

        success, _ = maven_test(repo_path)
        if not success:
            os.remove(test_path)
            log(f"  {test_name}: mvn falhou, removido", "WARN")
            get_failed_tracker().record(test_path, phase, "mvn falhou")
            if exec_logger:
                exec_logger.log_file_reverted(phase, test_name)
            reporter.record_build_failed(phase, test_name)
            continue

        reporter.record_changed(phase, test_name, test_path, "", test_code)
        if exec_logger:
            exec_logger.log_file_accepted(phase, test_name, "+test")
        log(f"  {test_name} CRIADO ✓", "OK")
        any_changed = True

    return any_changed
def _attempt_global_sync(build_output: str, repo_path: str, rules: str, phase: str):
    """
    Skill de Sincronia Contextual: Usa a IA para corrigir arquivos que quebraram
    devido a mudanças em dependências, evitando ambiguidades.
    """
    error_lines = [l for l in build_output.splitlines() if "cannot find symbol" in l]
    
    for line in error_lines[:3]: # Foca nos primeiros impactos
        symbol, failing_file_rel = _extract_missing_symbol_and_target(line)
        if not symbol or not failing_file_rel: continue
        
        failing_file_abs = os.path.join(repo_path, failing_file_rel)
        if not os.path.exists(failing_file_abs): continue
        
        log(f"  [Global Sync] Corrigindo impacto em {failing_file_rel}...", "WARN")
        
        old_content = read_file(failing_file_abs)
        sync_prompt = (
            f"O símbolo '{symbol}' não foi encontrado em {failing_file_rel} após uma refatoração.\n"
            f"Instrução: Analise o código e corrija as chamadas para este símbolo, "
            f"garantindo que a lógica e os tipos originais sejam respeitados.\n\n"
            f"Código Atual de {failing_file_rel}:\n{old_content}"
        )
        
        # Chama a IA para uma "Correção de Sincronia"
        new_content = call_ai(old_content, sync_prompt, "sync_fix", failing_file_rel, phase=phase)
        if new_content and new_content != old_content:
            write_file(failing_file_abs, new_content)

def _extract_missing_symbol_and_target(maven_line: str) -> tuple[str | None, str | None]:
    """Extrai o nome do símbolo e da classe desfalcada do log do Maven."""
    m = re.search(r'/([^/]+\.java):', maven_line)
    class_name = m.group(1) if m else None
    
    symbol = None
    if "method" in maven_line:
        m_sym = re.search(r'method (\w+)\(', maven_line)
        symbol = m_sym.group(1) if m_sym else None
        
    return symbol, class_name
