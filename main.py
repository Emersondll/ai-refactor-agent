"""
main.py — Localização: raiz do projeto (ai-refactor-agent/)
"""

import argparse
import datetime
import os
import subprocess
import sys
import threading
import time
from config import PHASES_DIR, REPOS_DIR, LOGS_DIR, USE_AGENT_MODE, BASE_DIR
from core.logger import log
from core.reporter import PhaseReporter
from core.execution_logger import ExecutionLogger
from git_utils.repo import clone_or_update, commit_and_push
from memory.cache import Cache
from memory.semantic_memory import SemanticMemory
from java.refactor import generate_tests, get_java_files, get_failed_tracker, FailedFilesTracker
from java.fix_metadata import get_fixes
from java.compiler import get_global_coverage, maven_test_with_coverage, maven_test
from java.sanitizer import run_sanitization


def _parse_cli_args() -> argparse.Namespace | None:
    """Parse CLI args. Returns parsed args, or None if no CLI commands were given
    (so main() proceeds to interactive mode)."""
    parser = argparse.ArgumentParser(
        description="AI Refactor Agent — manage permanent_skip entries via CLI",
        add_help=True,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--list-skips", action="store_true",
        help="Print all permanent_skip entries (with age + applicable fix_metadata) and exit",
    )
    group.add_argument(
        "--clear-skip", metavar="BASENAME",
        help="Remove permanent_skip for files whose basename matches (e.g. FooTest.java)",
    )
    group.add_argument(
        "--clear-all-skips", action="store_true",
        help="Remove ALL permanent_skip entries and exit",
    )
    if len(sys.argv) <= 1:
        return None
    return parser.parse_args()


def _cmd_list_skips() -> None:
    tracker = FailedFilesTracker(LOGS_DIR)
    fixes = get_fixes()
    now = datetime.datetime.now()
    permanent_entries = [e for e in tracker._entries if e.get("permanent_skip")]
    if not permanent_entries:
        print("No permanent_skip entries.")
        return
    print(f"{len(permanent_entries)} permanent_skip entries:\n")
    print(f"{'BASENAME':<55} {'AGE':>10}  COMPATIBLE FIXES")
    print("-" * 100)
    for e in permanent_entries:
        basename = e["file"].split("/")[-1]
        ts_raw = e.get("timestamp", "")
        try:
            ts = datetime.datetime.fromisoformat(ts_raw)
            age_days = (now - ts).days
            age = f"{age_days}d"
        except Exception:
            age = "?"
        haystack = (e.get("stack_trace") or "") + " " + (e.get("reason") or "")
        compatible = []
        for f in fixes:
            try:
                f_ts = datetime.datetime.fromisoformat(f.get("applied_at", ""))
            except Exception:
                continue
            try:
                if datetime.datetime.fromisoformat(ts_raw) >= f_ts:
                    continue  # entry newer than fix — won't help
            except Exception:
                pass
            if any(pat in haystack for pat in f.get("patterns", [])):
                compatible.append(f.get("id", "?"))
        compat_str = ",".join(compatible) if compatible else "(none)"
        print(f"{basename:<55} {age:>10}  {compat_str}")
    print()
    print("Hint: use --clear-skip <basename> or set FORCE_RETRY in .env to retest a file.")


def _cmd_clear_skip(basename: str) -> None:
    tracker = FailedFilesTracker(LOGS_DIR)
    matched = [e for e in tracker._entries if e.get("permanent_skip") and e["file"].split("/")[-1] == basename]
    if not matched:
        print(f"No permanent_skip entry for basename '{basename}'.")
        return
    total = 0
    for e in matched:
        total += tracker.clear_permanent_skips(e["file"])
    print(f"Cleared {total} entry/entries for {basename}.")


def _cmd_clear_all_skips() -> None:
    tracker = FailedFilesTracker(LOGS_DIR)
    n = tracker.clear_permanent_skips()
    print(f"Cleared {n} permanent_skip entries.")


def main():
    os.makedirs(LOGS_DIR, exist_ok=True)

    _cli_args = _parse_cli_args()
    if _cli_args is not None:
        if _cli_args.list_skips:
            _cmd_list_skips()
        elif _cli_args.clear_skip:
            _cmd_clear_skip(_cli_args.clear_skip)
        elif _cli_args.clear_all_skips:
            _cmd_clear_all_skips()
        return  # exit without starting pipeline

    # B2: limpa estado ao vivo do run anterior antes de qualquer coisa
    from core.live_state import update as _live_reset
    _live_reset(active_skill="", current_model="", current_file="")

    log("=" * 60, "PHASE")
    log("AI Refactor Orchestrator — Dashboard Ativo", "PHASE")
    log("=" * 60, "PHASE")

    reporter    = PhaseReporter()
    exec_logger = ExecutionLogger(LOGS_DIR)

    # --- Iniciar Servidor do Dashboard em Background ---
    def start_dashboard_server():
        try:
            # Tenta liberar a porta 8000 se estiver ocupada
            subprocess.run(["fuser", "-k", "8000/tcp"], capture_output=True)
            subprocess.Popen(["python3", "-m", "http.server", "8000"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log("Dashboard Server: ATIVO em http://localhost:8000/dashboard.html", "OK")
        except:
            log("Não foi possível iniciar o servidor do Dashboard automaticamente.", "WARN")

    def start_data_updater():
        while True:
            try:
                subprocess.run(["python3", "dashboard/data.py"], capture_output=True)
            except: pass
            time.sleep(10) # Atualiza o JSON a cada 10s

    # M15: warn about recent `fix:` commits not registered in fix_metadata.json
    try:
        from core.fix_metadata_audit import audit_fix_metadata
        _missing = audit_fix_metadata()
        if _missing:
            log(
                f"[fix_metadata] {len(_missing)} commit(s) `fix:` recente(s) "
                f"sem entrada em logs/fix_metadata.json: {', '.join(_missing[:10])}",
                "WARN",
            )
            log(
                "[fix_metadata] Considere `register_fix(...)` para que M3 "
                "(auto-expire) consiga aplicar.",
                "INFO",
            )
    except Exception:
        pass  # never break boot over an audit

    repo = input("Repo URL ou caminho local: ").strip()
    if not repo:
        log("Nenhum repositório informado.", "ERR")
        return

    threading.Thread(target=start_dashboard_server, daemon=True).start()
    threading.Thread(target=start_data_updater, daemon=True).start()

    os.makedirs(REPOS_DIR, exist_ok=True)

    log("Clonando/atualizando repositório...", "PHASE")
    if repo.startswith("http") or repo.startswith("git@"):
        repo_path, branch_name = clone_or_update(repo, REPOS_DIR)
        if not repo_path or not branch_name:
            log("Falha ao clonar/atualizar repositório", "ERR")
            return
    else:
        repo_path = os.path.abspath(repo)
        if not os.path.isdir(repo_path):
            log(f"Caminho não encontrado: {repo_path}", "ERR")
            return
        from datetime import datetime
        branch_name = f"refactor/ai-{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    log(f"Repositório: {repo_path}", "OK")
    log(f"Branch: {branch_name}", "OK")

    exec_logger.log_git_branch_created(branch_name)

    # Limpa falhas de runs anteriores para não bloquear arquivos fixáveis
    get_failed_tracker(LOGS_DIR).reset()

    if not os.path.isdir(PHASES_DIR):
        log(f"Diretório '{PHASES_DIR}/' não encontrado.", "ERR")
        return

    # --- Health Check Inicial ---
    log("Executando Health Check (Validação de Testes Existentes)...", "PHASE")
    exec_logger.log_phase_start("HEALTH_CHECK", "Validação de Testes Existentes")
    success, output = maven_test(repo_path)
    if not success:
        log("AVISO: O projeto já possui testes QUEBRADOS no estado inicial.", "WARN")
    else:
        log("Health Check: PROJETO SAUDÁVEL ✓", "OK")

    # --- Auditoria de Cobertura Inicial ---
    log("Iniciando Auditoria de Cobertura...", "PHASE")
    exec_logger.log_phase_start("AUDIT_COVERAGE", "Auditoria de Cobertura Inicial")
    success, _, _, _ = maven_test_with_coverage(repo_path, "")
    global_cov = get_global_coverage(repo_path)
    exec_logger.log_coverage(global_cov)
    log(f"Cobertura Global de Testes: {global_cov:.2f}%", "OK" if global_cov >= 90.0 else "WARN")

    if global_cov < 90.0:
        log(f"COBERTURA INSUFICIENTE ({global_cov:.2f}% < 90%). Ativando Geração Autônoma de Testes (Skill: java-tdd-unit-test)...", "WARN")
        from core.utils import load_skill
        rules_test = load_skill("java-tdd-unit-test", section="LLM INSTRUCTIONS")
        if not rules_test:
            rules_test = (
                "Generate comprehensive JUnit 5 + Mockito unit tests to increase coverage above 90%.\n"
                "Cover: happy path, edge cases, and error/exception scenarios.\n"
                "Test only the CURRENT behavior of the code — not what it should do in the future.\n"
                "Use only symbols (methods, enums, constructors) that exist in the source class."
            )
        generate_tests(repo_path, "initial_coverage_fix", rules_test, reporter, exec_logger)

        # Gate: revalida cobertura após geração — refatoração só prossegue com ≥ 90%
        success, _, _, _ = maven_test_with_coverage(repo_path, "")
        global_cov = get_global_coverage(repo_path)
        exec_logger.log_coverage(global_cov, "Cobertura Pós-Geração de Testes")
        log(f"Cobertura após geração: {global_cov:.2f}%", "OK" if global_cov >= 90.0 else "WARN")

        if global_cov < 90.0:
            log(f"ATENÇÃO: Cobertura {global_cov:.2f}% abaixo de 90% após geração autônoma.", "WARN")
            log("Verifique failed_files.json para classes que não atingiram a meta.", "WARN")
            log("Prosseguindo para refatoração — testes existentes protegem o comportamento atual.", "WARN")

    # A2: guarda cobertura pré-refatoração para gate no final
    _coverage_before_refactor = global_cov

    # --- Cache de tokens (dep context + phase skip) ---
    cache        = Cache(repo_path)
    semantic_mem = SemanticMemory()

    # --- Refatoração: Agent Loop ou Pipeline fixo ---
    _all_java_files = get_java_files(repo_path)
    exec_logger.log_files_total(len(_all_java_files))
    exec_logger.log_files_queue([os.path.basename(f) for f in _all_java_files])

    if USE_AGENT_MODE:
        log("Modo Agente ativado — Claude planeja, Ollama executa.", "PHASE")
        from agent.loop import run_agent_loop
        run_agent_loop(repo_path, reporter, exec_logger, cache, semantic_mem)
    else:
        log("Modo Pipeline fixo (USE_AGENT_MODE=false).", "PHASE")
        import glob as _glob
        import yaml as _yaml
        from java.community_runner import run_skill as _run_skill
        from java.llm_runner import run_skill as _run_llm_skill
        from java.llm_reviewer import review_diff as _review_diff
        from java.compiler import maven_test as _maven_test
        from core.utils import run_cmd as _run_cmd
        from config import MODEL_REVIEWER as _MODEL_SOLID

        configs_dir = os.path.join(BASE_DIR, "phases", "configs")
        config_paths = sorted(_glob.glob(os.path.join(configs_dir, "*.yml")))

        if not config_paths:
            log(f"Nenhum config .yml encontrado em {configs_dir}", "ERR")
            return

        for config_path in config_paths:
            with open(config_path, "r", encoding="utf-8") as _f:
                skill_config = _yaml.safe_load(_f)
            skill_id = skill_config.get("skill", os.path.basename(config_path))
            tool     = skill_config.get("tool", "")
            log(f"Iniciando Skill: {skill_id} (tool={tool})", "PHASE")
            exec_logger.log_phase_start(skill_id, f"Tool: {tool}")

            if tool == "llm":
                changed, diff = _run_llm_skill(skill_config, repo_path, cache, exec_logger=exec_logger)
            elif tool == "flow":
                from java.flow_runner import run_skill as _run_flow_skill
                changed, diff = _run_flow_skill(skill_config, repo_path, cache, exec_logger=exec_logger)
            elif tool == "flow-dry":
                from java.flow_runner import dry_check as _dry_check
                changed, diff = _dry_check(skill_config, repo_path, exec_logger=exec_logger)
            else:
                changed, diff = _run_skill(skill_config, repo_path)
            if not changed:
                log(f"  [{skill_id}] sem alterações — pulando", "OK")
                cache.mark_phase_done(skill_id, skill_id)
                continue

            verdict = _review_diff(diff, skill_config.get("review_criteria", ""), _MODEL_SOLID)
            log(f"  [{skill_id}] revisor: {verdict}")

            if verdict == "REJECT":
                _run_cmd("git restore .", cwd=repo_path)
                cache.mark_phase_done(skill_id, skill_id)
                log(f"  [{skill_id}] revertido (REJECT)", "WARN")
                continue

            build_ok, build_output = _maven_test(repo_path)
            if not build_ok:
                log(f"  [{skill_id}] build quebrado após APPROVE — revertendo", "WARN")
                _run_cmd("git restore .", cwd=repo_path)
            else:
                cache.mark_phase_done(skill_id, skill_id)
                log(f"  [{skill_id}] aceito ✓", "OK")
                # M1: emite FILE_ACCEPTED via diff só para fases community
                # fases llm/flow já emitem por conta própria via exec_logger interno
                if tool not in ("llm", "flow", "flow-dry"):
                    import re as _re
                    for _fname in sorted(set(_re.findall(
                        r'^\+\+\+ b/(?:.+/)?([\w]+\.java)', diff, _re.MULTILINE
                    ))):
                        exec_logger.log_file_accepted(skill_id, _fname, "+community")

        # S5: segunda passagem de testes para classes com field injection liberadas pelo solid-dip.
        # Na primeira passagem (AUDIT_COVERAGE), M7 adia classes que têm @Autowired sem construtor
        # mas também possuem `new ConcreteClass()` — esperando que solid-dip converta o construtor.
        # Aqui relemos o arquivo de produção já modificado; M7 não vai mais adiar essas classes.
        # Classes já cobertas (≥90%) são puladas por M8 sem custo adicional.
        log("S5: Re-auditando cobertura para classes liberadas pelo solid-dip...", "PHASE")
        exec_logger.log_phase_start(
            "AUDIT_COVERAGE_POST_DIP",
            "Geração de testes pós-solid-dip (classes com field injection convertidas)"
        )
        from core.utils import load_skill as _load_s5
        _rules_s5 = _load_s5("java-tdd-unit-test", section="LLM INSTRUCTIONS") or (
            "Generate comprehensive JUnit 5 + Mockito unit tests to increase coverage above 90%.\n"
            "Cover: happy path, edge cases, and error/exception scenarios.\n"
            "Test only the CURRENT behavior of the code — not what it should do in the future.\n"
            "Use only symbols (methods, enums, constructors) that exist in the source class."
        )
        generate_tests(repo_path, "post_solid_dip_coverage", _rules_s5, reporter, exec_logger)

    # --- Sanitização Final ---
    log("Iniciando Sanitização Final...", "PHASE")
    exec_logger.log_phase_start("SANITIZATION", "Limpando imports e código morto")
    run_sanitization(repo_path)

    # --- Javadoc ---
    # D: descarrega o modelo Ollama em uso antes de JAVADOC para liberar VRAM/RAM saturada
    # após ~3h de geração de testes — evita timeouts em cascata na fase de Javadoc.
    try:
        import urllib.request as _ur, json as _json
        from config import MODEL_CLEAN as _MODEL_CLEAN, OLLAMA_BASE_URL as _OLLAMA_URL
        _unload_req = _ur.Request(
            f"{_OLLAMA_URL}/api/generate",
            data=_json.dumps({"model": _MODEL_CLEAN, "keep_alive": 0}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _ur.urlopen(_unload_req, timeout=10):
            pass
        log(f"[Javadoc] Modelo {_MODEL_CLEAN} descarregado — VRAM liberada antes de Javadoc", "INFO")
    except Exception as _unload_err:
        log(f"[Javadoc] Aviso: falha ao descarregar modelo ({_unload_err}) — continuando", "WARN")

    log("Inserindo Javadoc nos métodos públicos...", "PHASE")
    exec_logger.log_phase_start("JAVADOC", "Inserção de Javadoc em métodos públicos")
    try:
        from java.javadoc_runner import run_javadoc
        run_javadoc(repo_path, exec_logger=exec_logger)
    except Exception as _javadoc_err:
        log(f"[Javadoc] Erro na fase: {_javadoc_err} — continuando pipeline", "WARN")

    # --- Validação Final ---
    log("Iniciando Validação Final...", "PHASE")
    exec_logger.log_phase_start("FINAL_VALIDATION", "Validação Final pós-refatoração")
    final_ok, _ = maven_test(repo_path)
    if final_ok:
        log("Validação Final: BUILD OK ✓", "OK")
        _, _, _, _ = maven_test_with_coverage(repo_path, "")
        final_cov = get_global_coverage(repo_path)
        exec_logger.log_coverage(final_cov, "Cobertura Final Atingida")
        log(f"Cobertura Final: {final_cov:.2f}%", "OK" if final_cov >= 90.0 else "WARN")
        # A2: alerta se cobertura caiu em relação ao pré-refatoração
        if final_cov < _coverage_before_refactor - 1.0:
            _drop = _coverage_before_refactor - final_cov
            log(f"ATENÇÃO: Cobertura regrediu {_drop:.2f}pp ({_coverage_before_refactor:.2f}% → {final_cov:.2f}%). Verifique fases 13/14.", "WARN")
            exec_logger.log_phase_start("COVERAGE_REGRESSION", f"Regressão de cobertura: -{_drop:.2f}pp")
    else:
        log("Validação Final: BUILD QUEBRADO após refatoração!", "ERR")
        exec_logger.log_phase_start("FINAL_VALIDATION_FAILED", "Build quebrado após refatoração")

    # --- Relatório de Refatoração ---
    log("Gerando relatório de refatoração...", "PHASE")
    exec_logger.log_phase_start("REPORT", "Relatório por classe — o que foi aplicado e por que foi pulado")
    from java.report_runner import run_report as _run_report
    _run_report(
        repo_path=repo_path,
        jsonl_path=os.path.join(LOGS_DIR, "execution.jsonl"),
        logs_dir=LOGS_DIR,
        exec_logger=exec_logger,
    )

    # --- Persistência Final ---
    log("Persistindo resultado final...", "PHASE")
    exec_logger.log_phase_start("COMMIT_PUSH", "Persistência Final — commit + push")
    try:
        commit_and_push(repo_path, branch_name, "final-refactoring")
        exec_logger.log_git_commit("COMMIT_PUSH", branch_name)
        log(f"Commit realizado em {branch_name} ✓", "OK")
    except Exception as _e:
        log(f"Erro no commit/push: {_e}", "ERR")
        exec_logger.log_phase_start("COMMIT_PUSH_FAILED", f"Erro: {_e}")

    # --- Finalização ---
    from core.live_state import update as _live_final
    _live_final(active_skill="", current_model="", current_file="")
    exec_logger.log_phase_start("PIPELINE_COMPLETE", "Pipeline finalizado")
    log("Refatoração Concluída!", "OK")
    failed_tracker = get_failed_tracker()
    if len(failed_tracker) > 0:
        log(f"Aviso: {len(failed_tracker)} arquivos falharam. Use o reprocessador.", "WARN")

    # Garante que o dashboard capture is_complete=True ANTES do processo sair.
    # O background updater roda a cada 10s e morre junto com o main thread —
    # sem esse write síncrono o último JSON pode não refletir PIPELINE_COMPLETE.
    try:
        subprocess.run(
            ["python3", os.path.join("dashboard", "data.py")],
            capture_output=True, timeout=15,
        )
        log("Dashboard final atualizado (is_complete=True persistido)", "OK")
    except Exception as _e:
        log(f"Falha ao atualizar dashboard final: {_e}", "WARN")

if __name__ == "__main__":
    main()