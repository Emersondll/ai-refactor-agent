"""
main.py — Localização: raiz do projeto (ai-refactor-agent/)

ATUALIZADO:
  - Exibe ao final quantos arquivos ficaram em failed_files.json
  - Informa o comando para reprocessar os falhos com Claude
"""

import os
from config import PHASES_DIR, REPOS_DIR, LOGS_DIR
from core.logger import log
from core.utils import read_file
from core.reporter import PhaseReporter
from core.execution_logger import ExecutionLogger
from git.repo import clone_or_update, commit_and_push
from java.refactor import refactor_file, generate_tests, get_java_files, get_failed_tracker


def main():
    log("=" * 60, "PHASE")
    log("AI Refactor Agent — Orquestrador Principal", "PHASE")
    log("=" * 60, "PHASE")

    reporter    = PhaseReporter()
    exec_logger = ExecutionLogger(LOGS_DIR)

    repo = input("Repo URL ou caminho local: ").strip()
    if not repo:
        log("Nenhum repositório informado.", "ERR")
        return

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

    if not os.path.isdir(PHASES_DIR):
        log(f"Diretório '{PHASES_DIR}/' não encontrado.", "ERR")
        return

    # Ordem de Execução Semântica (Elite Workflow):
    # SOLID -> CLEAN -> STRUCT -> DOC
    phases_execution_order = ["solid", "clean", "struct", "doc", "claude"]

    for model in phases_execution_order:
        model_dir = os.path.join(PHASES_DIR, model)
        if not os.path.isdir(model_dir):
            continue

        phases = sorted([f for f in os.listdir(model_dir) if f.endswith(".md")])
        if not phases:
            continue

        log("=" * 60, "PHASE")
        log(f"MODELO: {model.upper()}", "PHASE")
        log("=" * 60, "PHASE")

        for phase in phases:
            phase_path = os.path.join(model_dir, phase)
            log(f"Fase: {phase} (modelo={model})", "PHASE")

            exec_logger.log_phase_start(phase, model)

            rules       = read_file(phase_path)
            any_changed = False

            main_files = get_java_files(repo_path, tests=False)
            for file in main_files:
                if refactor_file(file, rules, repo_path, phase, reporter, exec_logger):
                    any_changed = True

            if "test" in phase.lower():
                test_files = get_java_files(repo_path, tests=True)
                for file in test_files:
                    if refactor_file(file, rules, repo_path, phase, reporter, exec_logger):
                        any_changed = True

                if generate_tests(repo_path, phase, rules, reporter, exec_logger):
                    any_changed = True

            if any_changed:
                if commit_and_push(repo_path, branch_name, phase):
                    exec_logger.log_git_commit(phase, branch_name)
                    log(f"Fase {phase} commitada", "OK")
                else:
                    log(f"Push falhou para fase {phase}", "WARN")
            else:
                log(f"Nenhuma mudança na fase {phase}", "WARN")

    # --- Relatório final ---
    log("=" * 60, "PHASE")
    log("Finalizando execução", "PHASE")
    log("=" * 60, "PHASE")

    report_path = reporter.save_report()
    log(f"Relatório: {report_path}", "OK")
    log(f"Branch: {branch_name}", "OK")
    log(f"Logs: {os.path.join(LOGS_DIR, 'execution.log')}", "OK")

    # Solução 5 — informa sobre arquivos que precisam de reprocessamento
    failed = get_failed_tracker(LOGS_DIR).get_pending()
    if failed:
        log(f"Arquivos que falharam e aguardam reprocessamento: {len(failed)}", "WARN")
        log(f"  → Veja: {os.path.join(LOGS_DIR, 'failed_files.json')}", "WARN")
        log(f"  → Para reprocessar com Claude: defina USE_CLAUDE_FALLBACK=true no .env", "WARN")
        for entry in failed[:5]:  # mostra até 5
            log(f"  {os.path.basename(entry['file'])} [{entry['phase']}]: {entry['reason']}", "WARN")
        if len(failed) > 5:
            log(f"  ... e mais {len(failed) - 5} arquivo(s)", "WARN")
    else:
        log("Nenhum arquivo pendente para reprocessamento", "OK")

    log("Agente finalizado com sucesso", "OK")


if __name__ == "__main__":
    main()