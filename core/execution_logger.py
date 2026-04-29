# core/execution_logger.py
#
# Logger estruturado — grava rastreamento completo em arquivo.
# Usado em: main.py (inicialização) e refactor.py (por arquivo/fase).
#
# Gera dois arquivos em logs/:
#   execution.log   → texto legível (para você ler durante/após a execução)
#   execution.jsonl → JSON Lines estruturado (para análise, grep, scripts)
#
# NÃO faz output no terminal. Para saída ao vivo no terminal, use logger.py.

import os
import json
from datetime import datetime


class ExecutionLogger:
    """Rastreamento auditável de todas as operações do agente."""

    def __init__(self, logs_dir: str = "logs") -> None:
        self.logs_dir = logs_dir
        os.makedirs(logs_dir, exist_ok=True)

        self._jsonl = os.path.join(logs_dir, "execution.jsonl")
        self._text  = os.path.join(logs_dir, "execution.log")

        with open(self._jsonl, "w") as f:
            f.write("")
        with open(self._text, "w") as f:
            f.write(f"=== Execução iniciada em {datetime.now().isoformat()} ===\n\n")

    # ------------------------------------------------------------------
    # Fase
    # ------------------------------------------------------------------

    def log_phase_start(self, phase: str, model: str) -> None:
        self._write(
            phase=phase, model=model,
            event="PHASE_START", status="INFO",
            message=f"Iniciando {phase} com {model}",
        )

    # ------------------------------------------------------------------
    # Git
    # ------------------------------------------------------------------

    def log_git_branch_created(self, branch: str) -> None:
        self._write(
            event="GIT_BRANCH_CREATED", status="OK",
            message=f"Branch criada: {branch}",
        )

    def log_git_commit(self, phase: str, branch: str) -> None:
        self._write(
            phase=phase, branch=branch,
            event="GIT_COMMIT", status="SUCCESS",
            message=f"Commit em {branch} após {phase}",
        )

    # ------------------------------------------------------------------
    # Arquivo — assinaturas compatíveis com refactor.py
    # ------------------------------------------------------------------

    def log_file_processing(self, phase: str, file: str,
                             file_type: str = "", mode: str = "") -> None:
        """
        Arquivo entrou no pipeline.
        Chamado em refactor.py como:
          exec_logger.log_file_processing(phase, file_name, "unknown", "unknown")
          exec_logger.log_file_processing(phase, test_name, "test", "new")
        """
        self._write(
            phase=phase, file=file,
            file_type=file_type, mode=mode,
            event="FILE_START", status="INFO",
            message=f"Processando {file}",
        )

    def log_file_skipped(self, phase: str, file: str, reason: str) -> None:
        """Arquivo pulado antes de chamar a IA (should_skip)."""
        self._write(
            phase=phase, file=file,
            event="FILE_SKIPPED", status="SKIP",
            message=f"Pulado: {reason}",
        )

    def log_file_accepted(self, phase: str, file: str,
                          change_type: str = "") -> None:
        """
        Arquivo aceito com sucesso.
        Chamado em refactor.py como:
          exec_logger.log_file_accepted(phase, file_name, "+refactor")
          exec_logger.log_file_accepted(phase, test_name, "+test")
        """
        self._write(
            phase=phase, file=file,
            change_type=change_type,
            event="FILE_ACCEPTED", status="SUCCESS",
            message=f"Aceito {change_type}",
        )

    def log_file_reverted(self, phase: str, file: str) -> None:
        """Arquivo revertido porque o build quebrou após a mudança."""
        self._write(
            phase=phase, file=file,
            event="FILE_REVERTED", status="REVERT",
            message="Revertido — build quebrou",
        )

    # ------------------------------------------------------------------
    # IA
    # ------------------------------------------------------------------

    def log_ai_attempt(self, phase: str, file: str,
                       agent: str, attempt: int) -> None:
        self._write(
            phase=phase, file=file, agent=agent,
            event="AI_ATTEMPT", status="INFO",
            message=f"[{agent}] tentativa {attempt}",
        )

    def log_ai_success(self, phase: str, file: str, agent: str) -> None:
        self._write(
            phase=phase, file=file, agent=agent,
            event="AI_SUCCESS", status="SUCCESS",
            message=f"[{agent}] resposta válida",
        )

    def log_ai_failure(self, phase: str, file: str,
                       agent: str, reason: str) -> None:
        self._write(
            phase=phase, file=file, agent=agent,
            event="AI_FAILURE", status="ERROR",
            message=f"[{agent}] falha: {reason}",
        )

    # ------------------------------------------------------------------
    # Validação e compilação
    # ------------------------------------------------------------------

    def log_validation_rejected(self, phase: str, file: str,
                                 reason: str) -> None:
        self._write(
            phase=phase, file=file,
            event="VALIDATION_REJECTED", status="REJECT",
            message=f"Validator: {reason}",
        )

    def log_compilation_passed(self, phase: str, file: str) -> None:
        self._write(
            phase=phase, file=file,
            event="COMPILATION_PASSED", status="SUCCESS",
            message="mvn clean test PASSOU",
        )

    def log_compilation_failed(self, phase: str, file: str) -> None:
        self._write(
            phase=phase, file=file,
            event="COMPILATION_FAILED", status="ERROR",
            message="mvn clean test FALHOU",
        )

    # ------------------------------------------------------------------
    # Escrita interna
    # ------------------------------------------------------------------

    def _write(self, **kwargs) -> None:
        entry = {"timestamp": datetime.now().isoformat(), **kwargs}

        with open(self._jsonl, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        phase   = kwargs.get("phase",   "")
        event   = kwargs.get("event",   "?")
        status  = kwargs.get("status",  "?")
        message = kwargs.get("message", "?")
        with open(self._text, "a") as f:
            f.write(
                f"[{entry['timestamp']}]"
                f" {phase:25}"
                f" | {event:25}"
                f" | {status:10}"
                f" | {message}\n"
            )