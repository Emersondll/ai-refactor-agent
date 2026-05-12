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
from java.compiler import maven_test, maven_test_with_coverage
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
    (re.compile(r'public\s+interface\b'),
     "Interface pura (sem lógica)"),
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

def _generate_and_validate(original: str, rules: str, mode: str,
                             file_name: str, file_path: str,
                             phase: str = "",
                             cache=None) -> tuple[str | None, str]:
    """
    Chama a IA e valida o resultado com injeção de contexto de dependências.
    dep_context é obtido do cache ou gerado, e passado separado para build_prompt.
    """
    from java.context import get_dependency_context

    dep_context = ""
    root = file_path
    try:
        while root != "/" and not os.path.exists(os.path.join(root, "pom.xml")):
            root = os.path.dirname(root)
        if os.path.exists(os.path.join(root, "pom.xml")):
            dep_context = get_dependency_context(original, root, cache=cache)
    except Exception:
        pass

    test_context = ""
    try:
        test_file = _test_path_for(file_path, root)
        if test_file and os.path.exists(test_file):
            from core.utils import read_file as _read
            test_code = _read(test_file)
            test_context = (
                "\n\n[CONTEXTO DE TESTE] O teste abaixo valida esta classe. "
                "Sua refatoração DEVE garantir que ele continue passando:\n\n"
                f"```java\n{test_code}\n```"
            )
            log("  [Contexto] Teste unitário injetado.", "OK")
    except Exception:
        pass

    phase_delta = rules + test_context

    new_code = call_ai(original, phase_delta, mode, file_name,
                       file_path=file_path, phase=phase,
                       dep_context=dep_context)

    if not new_code:
        return None, "IA não gerou código"

    valid, reason = is_valid_java(original, new_code)
    if valid:
        # Skill: Validador de Integridade de Nome
        from java.validator import validate_class_name_matches_file
        is_name_ok, name_error = validate_class_name_matches_file(new_code, file_path)
        if is_name_ok:
            return new_code, ""
        reason = f"ERRO DE INTEGRIDADE: {name_error}"

    log(f"  Validator rejeitou: {reason} — tentando correção", "WARN")

    # Ciclos de correção
    rejected_code = new_code
    for attempt in range(1, MAX_VALIDATOR_RETRIES + 1):
        log(f"  Correção validator {attempt}/{MAX_VALIDATOR_RETRIES}: {reason[:60]}")

        corrected = call_ai_with_correction(
            original      = original,
            rules         = phase_delta,
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
            # Skill: Validador de Integridade de Nome
            from java.validator import validate_class_name_matches_file
            is_name_ok, name_error = validate_class_name_matches_file(corrected, file_path)
            if is_name_ok:
                log(f"  Correção {attempt}: aceita ✓", "OK")
                return corrected, ""
            reason = f"ERRO DE INTEGRIDADE: {name_error}. O nome da classe deve ser '{file_name.replace('.java','')}'."

        log(f"  Correção {attempt}: ainda rejeitado — {reason}", "WARN")
        rejected_code = corrected

    return None, reason


# ---------------------------------------------------------------------------
# Refatoração — arquivo inteiro
# ---------------------------------------------------------------------------

def _refactor_whole_file(file: str, original: str, rules: str,
                          repo_path: str, phase: str,
                          reporter: PhaseReporter,
                          exec_logger: ExecutionLogger | None,
                          cache=None) -> bool:
    file_name = os.path.basename(file)
    mode      = _mode_for(file)

    new_code, reason = _generate_and_validate(
        original, rules, mode, file_name, file, phase=phase, cache=cache
    )

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
        if "cannot find symbol" in build_output or "does not override" in build_output:
            log("  [Impacto Detectado] Mudança de contrato detectada. Tentando sincronização contextual...", "PHASE")
            _attempt_global_sync(build_output, repo_path, rules, phase, new_code)
            success, build_output = maven_test(repo_path)
            if success:
                log(f"  {file_name}: Sincronização global restaurou o build! ✓", "OK")

    if not success:
        log(f"  {file_name}: Build persiste com erro. Ativando Diagnóstico de Precisão...", "WARN")
        
        # Skill: Identificação de Culpado Transversal
        # Se o erro for em OUTRO arquivo (ex: interface que sumiu), tentamos restaurar/corrigir o outro arquivo.
        culprit_match = re.search(r'([/\\].*\.java):\[\d+', build_output)
        if culprit_match:
            culprit_path = culprit_match.group(1)
            culprit_name = os.path.basename(culprit_path)
            if culprit_name != file_name:
                log(f"  [Auto-Cura] O culpado parece ser {culprit_name}. Tentando reparo de emergência...", "PHASE")
                # Se o erro for "does not contain class" ou "should be declared in file", é erro estrutural
                if "should be declared in a file" in build_output or "does not contain class" in build_output:
                    # Tenta restaurar o arquivo da interface/culpado para o estado estável
                    run_command(f"git checkout -- \"{culprit_path}\"", repo_path)
                    log(f"  [Auto-Cura] {culprit_name} restaurado para estado estável do Git.", "OK")
                    success, build_output = maven_test(repo_path)
                    if success: return True # Resolvido restaurando o culpado
        
        # Skill: Raio-X de Erros (Continua para o arquivo atual)
        error_diagnostics = []
        raw_error_lines = [l for l in build_output.splitlines() if "[ERROR]" in l and ".java:[" in l][:5]
        
        for err_line in raw_error_lines:
            # Regex melhorado para suportar espaços no caminho: /caminho/com espaço/Arquivo.java:[linha,coluna]
            m = re.search(r'([/\\].*\.java):\[(\d+)', err_line)
            if m:
                fpath, lnum = m.group(1), int(m.group(2))
                try:
                    code_snippet = _get_line_from_file(fpath, lnum)
                    diag = f"Erro em {os.path.basename(fpath)} L{lnum}: {code_snippet.strip()}\n      -> {err_line.split('] ', 1)[-1]}"
                    error_diagnostics.append(diag)
                    log(f"  [Raio-X] {diag}", "ERR")
                except: pass

        error_summary = "\n".join(error_diagnostics) or "\n".join(build_output.splitlines()[:5])
        
        # Skill: Registro de Diagnóstico para análise posterior
        exec_logger.log_detailed_diagnostic(phase, file_name, build_output, error_diagnostics)

        # Skill: Reforço de Import com Dicionário Global
        if "cannot find symbol" in error_summary:
            from java.dictionary import build_project_dictionary
            proj_map = None
            if cache is not None:
                proj_map = cache.get_project_dict()
            if proj_map is None:
                proj_map = build_project_dictionary(repo_path)
                if cache is not None:
                    cache.set_project_dict(proj_map)
            error_summary += f"\n\n{proj_map}\n\nDICA: Use o mapa acima para adicionar o IMPORT correto."
        
        corrected_code = call_ai_with_correction(
            original     = original,
            rules        = rules,
            mode         = mode,
            file_name    = file_name,
            file_path    = file,
            bad_output   = new_code,
            error_reason = f"Falha de Compilação Maven:\n{error_summary}",
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
                         exec_logger: ExecutionLogger | None,
                         cache=None) -> bool:
    file_name = os.path.basename(file)
    mode      = _mode_for(file)

    header  = extract_class_header(original)
    methods = get_processable_methods(original)

    if not methods:
        log(f"  {file_name}: nenhum método extraível — tentando arquivo inteiro")
        return _refactor_whole_file(file, original, rules, repo_path, phase,
                                    reporter, exec_logger, cache=cache)

    log(f"  {file_name}: {len(methods)} métodos a processar")

    current_code    = original
    methods_changed = 0
    methods_failed  = 0

    for method in methods:
        log(f"    → {method.name}() [{len(method.full_text.splitlines())}L]")

        context = build_method_context(header, method)

        ai_response, reason = _generate_and_validate(
            original  = context,
            rules     = rules,
            mode      = mode,
            file_name = file_name,
            file_path = file,
            phase     = phase,
            cache     = cache,
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
                  exec_logger: ExecutionLogger | None = None,
                  cache=None) -> bool:
    file_name = os.path.basename(file)

    # Phase skip: se já processamos este arquivo nesta fase neste run, pula
    if cache is not None:
        phase_name = phase.split("/")[-1].replace(".md", "")
        if cache.is_phase_done(file, phase_name):
            log(f"  {file_name}: cache hit — {phase_name} já aplicada neste run", "OK")
            reporter.record_skipped(phase, file_name, f"cache: {phase_name} já aplicada")
            return False

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
        success = _refactor_by_method(file, original, rules, repo_path, phase,
                                      reporter, exec_logger, cache=cache)
    else:
        success = _refactor_whole_file(file, original, rules, repo_path, phase,
                                       reporter, exec_logger, cache=cache)

    if success and cache is not None:
        phase_name = phase.split("/")[-1].replace(".md", "")
        cache.mark_phase_done(file, phase_name)

    return success


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

        success, combined_out, coverage, missed_lines = maven_test_with_coverage(repo_path, file_name)
        
        # Skill: Enforcement de Cobertura JaCoCo + Autocura Sistêmica
        for attempt in range(MAX_VALIDATOR_RETRIES):
            if success and coverage >= 90.0:
                log(f"  [{test_name}] Cobertura atingida: {coverage:.2f}% ✓", "OK")
                break
                
            if not success:
                log(f"  [{test_name}] Teste falhou (compilação ou lógica). Iniciando Autocura...", "WARN")
                error_msg = f"O teste que você gerou FALHOU.\n\nERRO DO MAVEN:\n{combined_out[-2000:]}\n\nAnalise o erro acima e corrija o teste. Se for um erro de asserção (ex: 200 vs 202), ajuste o teste para o valor real que o código retorna."
            else:
                log(f"  [{test_name}] Cobertura baixa: {coverage:.2f}%. Expandindo testes...", "WARN")
                error_msg = f"Seus testes passaram, mas a cobertura está em {coverage:.2f}%. O mínimo exigido é 90.0%.\nEscreva novos métodos de teste para cobrir as linhas: {missed_lines}."
            
            corrected_test = call_ai_with_correction(
                original=original, rules=rules, mode="test",
                file_name=file_name, file_path=test_path,
                bad_output=test_code, error_reason=error_msg, phase=phase
            )
            
            if not corrected_test:
                break
                
            write_file(test_path, corrected_test)
            test_code = corrected_test
            success, combined_out, coverage, missed_lines = maven_test_with_coverage(repo_path, file_name)

        if not success or coverage < 90.0:
            os.remove(test_path)
            err_reason = "mvn falhou" if not success else f"cobertura insuficiente ({coverage:.2f}%)"
            log(f"  {test_name}: {err_reason}, removido", "WARN")
            get_failed_tracker().record(test_path, phase, err_reason)
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
def _attempt_global_sync(build_output: str, repo_path: str, rules: str, phase: str, trigger_file_content: str):
    """
    Skill de Sincronia Contextual 2.0: Usa o código recém-refatorado como
    referência para consertar as dependências em outros arquivos.
    """
    error_lines = [l for l in build_output.splitlines() if "cannot find symbol" in l or "does not override" in l]
    
    for line in error_lines[:3]:
        symbol, failing_file_abs = _extract_missing_symbol_and_target(line)
        if not failing_file_abs: continue
        
        if not os.path.exists(failing_file_abs): continue
        
        failing_file_name = os.path.basename(failing_file_abs)
        failing_file_rel = os.path.relpath(failing_file_abs, repo_path)
        log(f"  [Sincronia] Corrigindo impacto em {failing_file_name} usando contrato atualizado...", "WARN")
        
        old_content = read_file(failing_file_abs)
        sync_prompt = (
            f"O arquivo {failing_file_rel} quebrou após a refatoração do arquivo original.\n"
            f"CONTRATO DE REFERÊNCIA (Código atualizado):\n{trigger_file_content}\n\n"
            f"INSTRUÇÃO: Atualize o arquivo {failing_file_rel} para que ele seja COMPATÍVEL com o Contrato de Referência acima.\n"
            f"- Se um método mudou, atualize a chamada ou a implementação.\n"
            f"- NUNCA transforme Interfaces em Classes.\n"
            f"- Mantenha a lógica original.\n\n"
            f"CÓDIGO QUE PRECISA DE AJUSTE:\n{old_content}"
        )
        
        new_content = call_ai(old_content, sync_prompt, "sync_fix", failing_file_rel, phase=phase)
        if new_content and new_content != old_content:
            write_file(failing_file_abs, new_content)

def _extract_missing_symbol_and_target(maven_line: str) -> tuple[str | None, str | None]:
    """Extrai o nome do símbolo e o caminho absoluto da classe desfalcada do log do Maven."""
    # O maven_line geralmente vem no formato: [ERROR] /caminho/completo/Arquivo.java:[linha,coluna] erro...
    m = re.search(r'(/.*?\.java):', maven_line)
    file_path = m.group(1) if m else None
    
    symbol = None
    if "method" in maven_line:
        m_sym = re.search(r'method (\w+)\(', maven_line)
        symbol = m_sym.group(1) if m_sym else None
        
    return symbol, file_path

def _get_line_from_file(file_path: str, line_number: int) -> str:
    """Retorna uma linha específica de um arquivo."""
    with open(file_path, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f, 1):
            if i == line_number:
                return line
    return ""
