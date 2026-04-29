"""
reporter.py — Rastreamento e relatório de todas as mudanças por fase.

Gera dois artefatos em logs/:
  - report.md          resumo geral de todas as fases
  - <fase>/<arq>.diff  diff unificado de cada arquivo alterado
"""

import difflib
import os
from datetime import datetime
from core.logger import log


LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")


class PhaseReporter:
    def __init__(self):
        self._entries: list[dict] = []
        os.makedirs(LOGS_DIR, exist_ok=True)

    # ------------------------------------------------------------------
    # Registro de eventos
    # ------------------------------------------------------------------

    def record_skipped(self, phase: str, file_name: str, reason: str):
        self._entries.append({
            "phase": phase, "file": file_name,
            "status": "SKIP", "reason": reason,
            "added": 0, "removed": 0,
        })

    def record_rejected(self, phase: str, file_name: str, reason: str):
        self._entries.append({
            "phase": phase, "file": file_name,
            "status": "REJECTED", "reason": reason,
            "added": 0, "removed": 0,
        })

    def record_build_failed(self, phase: str, file_name: str):
        self._entries.append({
            "phase": phase, "file": file_name,
            "status": "BUILD_FAIL", "reason": "mvn clean test falhou",
            "added": 0, "removed": 0,
        })

    def record_changed(self, phase: str, file_name: str, file_path: str,
                       original: str, new_code: str):
        """Registra uma mudança aceita e salva o diff em disco."""
        diff_lines = list(difflib.unified_diff(
            original.splitlines(keepends=True),
            new_code.splitlines(keepends=True),
            fromfile=f"original/{file_name}",
            tofile=f"refactored/{file_name}",
        ))

        added   = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))

        # Salva o diff em logs/<fase>/<arquivo>.diff
        phase_slug = phase.replace(".md", "").replace(" ", "_")
        diff_dir   = os.path.join(LOGS_DIR, phase_slug)
        os.makedirs(diff_dir, exist_ok=True)
        diff_path  = os.path.join(diff_dir, f"{file_name}.diff")

        with open(diff_path, "w", encoding="utf-8") as f:
            f.writelines(diff_lines if diff_lines else ["(sem diferenças)\n"])

        log(f"  Diff salvo: +{added} -{removed} linhas → {diff_path}")

        self._entries.append({
            "phase": phase, "file": file_name,
            "status": "CHANGED", "reason": "",
            "added": added, "removed": removed,
            "diff": diff_path,
        })

    # ------------------------------------------------------------------
    # Geração do relatório final
    # ------------------------------------------------------------------

    def save_report(self):
        report_path = os.path.join(LOGS_DIR, "report.md")

        # Agrupa por fase
        phases: dict[str, list[dict]] = {}
        for e in self._entries:
            phases.setdefault(e["phase"], []).append(e)

        lines = [
            f"# AI Refactor Agent — Relatório de Execução\n",
            f"Gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n",
        ]

        total_changed  = sum(1 for e in self._entries if e["status"] == "CHANGED")
        total_rejected = sum(1 for e in self._entries if e["status"] == "REJECTED")
        total_fail     = sum(1 for e in self._entries if e["status"] == "BUILD_FAIL")
        total_skip     = sum(1 for e in self._entries if e["status"] == "SKIP")

        lines += [
            "## Resumo\n\n",
            f"| Métrica | Valor |\n",
            f"|---|---|\n",
            f"| Arquivos alterados com sucesso | {total_changed} |\n",
            f"| Rejeitados pelo validator | {total_rejected} |\n",
            f"| Revertidos (build quebrou) | {total_fail} |\n",
            f"| Pulados (IA não gerou código) | {total_skip} |\n\n",
        ]

        for phase, entries in phases.items():
            changed  = [e for e in entries if e["status"] == "CHANGED"]
            problems = [e for e in entries if e["status"] != "CHANGED"]

            lines.append(f"## Fase: `{phase}`\n\n")

            if changed:
                lines.append(f"### Alterações aceitas ({len(changed)})\n\n")
                lines.append("| Arquivo | +linhas | -linhas | Diff |\n")
                lines.append("|---|---|---|---|\n")
                for e in changed:
                    diff_link = f"[ver]({e.get('diff', '')})" if e.get("diff") else "—"
                    lines.append(f"| `{e['file']}` | +{e['added']} | -{e['removed']} | {diff_link} |\n")
                lines.append("\n")

            if problems:
                lines.append(f"### Não alterados ({len(problems)})\n\n")
                lines.append("| Arquivo | Status | Motivo |\n")
                lines.append("|---|---|---|\n")
                for e in problems:
                    lines.append(f"| `{e['file']}` | {e['status']} | {e['reason']} |\n")
                lines.append("\n")

        with open(report_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        log(f"Relatório salvo em: {report_path}", "OK")
        return report_path