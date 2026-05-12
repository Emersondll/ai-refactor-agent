"""
main.py — Localização: raiz do projeto (ai-refactor-agent/)
"""

import os
import subprocess
import threading
import time
from config import PHASES_DIR, REPOS_DIR, LOGS_DIR
from core.logger import log
from core.utils import read_file
from core.reporter import PhaseReporter
from core.execution_logger import ExecutionLogger
from git_utils.repo import clone_or_update, commit_and_push
from memory.cache import Cache
from java.refactor import refactor_file, generate_tests, get_java_files, get_failed_tracker
from java.compiler import get_global_coverage, maven_test_with_coverage, maven_test
from java.flow import get_vertical_slices
from java.sanitizer import run_sanitization


def main():
    os.makedirs(LOGS_DIR, exist_ok=True)
    
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
                subprocess.run(["python3", "ai/dashboard_data.py"], capture_output=True)
            except: pass
            time.sleep(10) # Atualiza o JSON a cada 10s

    threading.Thread(target=start_dashboard_server, daemon=True).start()
    threading.Thread(target=start_data_updater, daemon=True).start()

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

    # --- Health Check Inicial ---
    log("Executando Health Check (Validação de Testes Existentes)...", "PHASE")
    success, output = maven_test(repo_path)
    if not success:
        log("AVISO: O projeto já possui testes QUEBRADOS no estado inicial.", "WARN")
    else:
        log("Health Check: PROJETO SAUDÁVEL ✓", "OK")

    # --- Auditoria de Cobertura Inicial ---
    log("Iniciando Auditoria de Cobertura...", "PHASE")
    success, _, _, _ = maven_test_with_coverage(repo_path, "")
    global_cov = get_global_coverage(repo_path)
    log(f"Cobertura Global de Testes: {global_cov:.2f}%", "OK" if global_cov >= 90.0 else "WARN")
    
    if global_cov < 90.0:
        log(f"COBERTURA INSUFICIENTE ({global_cov:.2f}% < 90%). Ativando Geração Automática de Testes...", "WARN")
        rules_test = "Crie testes unitários para cobrir as classes com baixa cobertura."
        generate_tests(repo_path, "initial_coverage_fix", rules_test, reporter, exec_logger)
        global_cov = get_global_coverage(repo_path)

    # --- Cache de tokens (dep context + phase skip) ---
    cache = Cache(repo_path)

    # --- Fases de Refatoração (SOLID) ---
    phase_paths = sorted(
        os.path.join(root, fname)
        for root, _, files in os.walk(PHASES_DIR)
        for fname in files
        if fname.endswith(".md")
    )
    for phase_path in phase_paths:
        phase_file = os.path.basename(phase_path)
        rules = read_file(phase_path)
        log(f"Iniciando Fase: {phase_file}", "PHASE")
        exec_logger.log_phase_start(phase_file, f"Iniciando {phase_file}")

        # Pega fatias verticais ou arquivos soltos
        files = get_java_files(repo_path)
        for f_path in files:
            # Refatora com segurança
            refactor_file(f_path, rules, repo_path, phase_path, reporter, exec_logger, cache=cache)

    # --- Sanitização Final ---
    log("Iniciando Sanitização Final...", "PHASE")
    exec_logger.log_phase_start("SANITIZATION", "Limpando imports e código morto")
    run_sanitization(repo_path)

    # --- Finalização ---
    log("Refatoração Concluída!", "OK")
    failed_tracker = get_failed_tracker()
    if failed_tracker:
        log(f"Aviso: {len(failed_tracker)} arquivos falharam. Use o reprocessador.", "WARN")

if __name__ == "__main__":
    main()