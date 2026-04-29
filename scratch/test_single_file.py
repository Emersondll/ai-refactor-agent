import os
import sys
from config import PHASES_DIR, LOGS_DIR
from core.logger import log
from core.utils import read_file
from core.reporter import PhaseReporter
from core.execution_logger import ExecutionLogger
from java.refactor import refactor_file

def test_single_file():
    target_file = "/home/emerson/Área de trabalho/ai-refactor-agent/repos/card-transaction-authorizer/src/main/java/com/caju/transactionauthorizer/service/impl/MerchantCategoryCodesServiceImpl.java"
    repo_path = "/home/emerson/Área de trabalho/ai-refactor-agent/repos/card-transaction-authorizer"

    if not os.path.exists(target_file):
        log(f"Arquivo não encontrado: {target_file}", "ERR")
        return

    log("=" * 60, "PHASE")
    log(f"Teste de Refatoração Unitária: {os.path.basename(target_file)}", "PHASE")
    log("=" * 60, "PHASE")

    reporter = PhaseReporter()
    exec_logger = ExecutionLogger(LOGS_DIR)

    # Nova Ordem de Execução: SOLID/Arquitetura -> Estrutura -> Javadoc
    phases_execution_order = ["quaternary", "tertiary", "fallback", "primary"]

    for model_tier in phases_execution_order:
        model_dir = os.path.join(PHASES_DIR, model_tier)
        if not os.path.isdir(model_dir):
            continue

        phases = sorted([f for f in os.listdir(model_dir) if f.endswith(".md")])
        if not phases:
            continue

        for phase in phases:
            phase_path = os.path.join(model_dir, phase)
            rules = read_file(phase_path)
            
            log(f"Iniciando Fase: {phase} [{model_tier}]", "PHASE")
            
            # Executa a refatoração para o arquivo específico
            refactor_file(target_file, rules, repo_path, phase, reporter, exec_logger)

    log("=" * 60, "PHASE")
    log("Teste finalizado.", "OK")
    report_path = reporter.save_report()
    log(f"Relatório gerado: {report_path}", "OK")

if __name__ == "__main__":
    test_single_file()
