# core/execution_logger.py
#
# Structured logger — writes complete audit trail to file.
# Used in: main.py (initialization) and refactor.py (per file/phase).
#
# Generates two files in logs/:
#   execution.log   → human-readable text (read during/after execution)
#   execution.jsonl → structured JSON Lines (for analysis, grep, scripts)
#
# Does NOT output to terminal. For live terminal output, use logger.py.

import os
import json
from datetime import datetime


class ExecutionLogger:
    """Auditable tracker for all agent operations."""

    def __init__(self, logs_dir: str = "logs") -> None:
        self.logs_dir = logs_dir
        os.makedirs(logs_dir, exist_ok=True)

        self._jsonl = os.path.join(logs_dir, "execution.jsonl")
        self._text  = os.path.join(logs_dir, "execution.log")

        with open(self._jsonl, "w") as f:
            f.write("")
        with open(self._text, "w") as f:
            f.write(f"=== Execution started at {datetime.now().isoformat()} ===\n\n")

    # ------------------------------------------------------------------
    # Phase
    # ------------------------------------------------------------------

    def log_phase_start(self, phase: str, model: str) -> None:
        self._write(
            phase=phase, model=model,
            event="PHASE_START", status="INFO",
            message=f"Starting {phase} with {model}",
        )

    # ------------------------------------------------------------------
    # Git
    # ------------------------------------------------------------------

    def log_coverage(self, coverage: float, label: str = "Current Global Coverage") -> None:
        self._write(
            event="COVERAGE", status="OK" if coverage >= 90.0 else "WARN",
            message=f"{label}: {coverage:.2f}%",
        )

    def log_files_total(self, count: int) -> None:
        self._write(event="FILES_TOTAL", status="INFO",
                    message=f"Total files to process: {count}", count=count)

    def log_files_queue(self, files: list) -> None:
        """Logs the full file queue so the dashboard can pre-populate the honeycomb."""
        self._write(event="FILES_QUEUE", status="INFO",
                    message=f"Queue: {len(files)} files", files=files)

    def log_git_branch_created(self, branch: str) -> None:
        self._write(
            event="GIT_BRANCH_CREATED", status="OK",
            message=f"Branch created: {branch}",
        )

    def log_git_commit(self, phase: str, branch: str) -> None:
        self._write(
            phase=phase, branch=branch,
            event="GIT_COMMIT", status="SUCCESS",
            message=f"Commit on {branch} after {phase}",
        )

    # ------------------------------------------------------------------
    # File — signatures compatible with refactor.py
    # ------------------------------------------------------------------

    def log_file_processing(self, phase: str, file: str,
                             file_type: str = "", mode: str = "") -> None:
        """File entered the pipeline.

        Called in refactor.py as:
          exec_logger.log_file_processing(phase, file_name, "unknown", "unknown")
          exec_logger.log_file_processing(phase, test_name, "test", "new")
        """
        self._write(
            phase=phase, file=file,
            file_type=file_type, mode=mode,
            event="FILE_START", status="INFO",
            message=f"Processing {file}",
        )

    def log_file_skipped(self, phase: str, file: str, reason: str) -> None:
        """File skipped before calling the LLM (should_skip)."""
        self._write(
            phase=phase, file=file,
            event="FILE_SKIPPED", status="SKIP",
            message=f"Skipped: {reason}",
        )

    def log_file_accepted(self, phase: str, file: str,
                          change_type: str = "") -> None:
        """File accepted successfully.

        Called in refactor.py as:
          exec_logger.log_file_accepted(phase, file_name, "+refactor")
          exec_logger.log_file_accepted(phase, test_name, "+test")
        """
        self._write(
            phase=phase, file=file,
            change_type=change_type,
            event="FILE_ACCEPTED", status="SUCCESS",
            message=f"Accepted {change_type}",
        )

    def log_file_reverted(self, phase: str, file: str, error_type: str = "") -> None:
        """File reverted because the build broke after the change."""
        message = f"Reverted — build broke [{error_type}]" if error_type else "Reverted — build broke"
        self._write(
            phase=phase, file=file,
            event="FILE_REVERTED", status="REVERT",
            message=message,
        )

    # ------------------------------------------------------------------
    # AI
    # ------------------------------------------------------------------

    def log_ai_attempt(self, phase: str, file: str,
                       agent: str, attempt: int) -> None:
        self._write(
            phase=phase, file=file, agent=agent,
            event="AI_ATTEMPT", status="INFO",
            message=f"[{agent}] attempt {attempt}",
        )

    def log_ai_success(self, phase: str, file: str, agent: str) -> None:
        self._write(
            phase=phase, file=file, agent=agent,
            event="AI_SUCCESS", status="SUCCESS",
            message=f"[{agent}] valid response",
        )

    def log_ai_failure(self, phase: str, file: str,
                       agent: str, reason: str) -> None:
        self._write(
            phase=phase, file=file, agent=agent,
            event="AI_FAILURE", status="ERROR",
            message=f"[{agent}] failure: {reason}",
        )

    def log_model_used(self, phase: str, file: str,
                       model: str, result: str = "") -> None:
        self._write(
            phase=phase, file=file, model=model,
            event="MODEL_USED", status="INFO",
            message=f"[{model}] → {result}",
        )

    # ------------------------------------------------------------------
    # Validation and compilation
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
            message="mvn clean test PASSED",
        )

    def log_compilation_failed(self, phase: str, file: str) -> None:
        self._write(
            phase=phase, file=file,
            event="COMPILATION_FAILED", status="ERROR",
            message="mvn clean test FAILED",
        )

    def log_detailed_diagnostic(self, phase: str, file: str, error_output: str, diagnostics: list) -> None:
        """Saves a complete failure report for later technical analysis."""
        diag_dir = os.path.join(self.logs_dir, "diagnostics")
        os.makedirs(diag_dir, exist_ok=True)

        safe_file_name = file.replace("/", "_").replace(".", "_")
        diag_file = os.path.join(diag_dir, f"diag_{phase}_{safe_file_name}_{datetime.now().strftime('%H%M%S')}.txt")

        with open(diag_file, "w", encoding="utf-8") as f:
            f.write("FAILURE DIAGNOSTIC REPORT\n")
            f.write("=" * 40 + "\n")
            f.write(f"File:  {file}\n")
            f.write(f"Phase: {phase}\n")
            f.write(f"Date:  {datetime.now().isoformat()}\n")
            f.write("=" * 40 + "\n\n")

            f.write("X-RAY SUMMARY (CODE EXCERPTS):\n")
            for d in diagnostics:
                f.write(f"- {d}\n")
            f.write("\n" + "=" * 40 + "\n\n")

            f.write("FULL MAVEN LOG:\n")
            f.write(error_output)
            f.write("\n" + "=" * 40 + "\n")

        self._write(
            phase=phase, file=file,
            event="DIAGNOSTIC_SAVED", status="INFO",
            message=f"Detailed log saved: {os.path.basename(diag_file)}"
        )

    # ------------------------------------------------------------------
    # Internal write
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