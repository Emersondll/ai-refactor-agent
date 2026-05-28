"""
reporter.py — Tracking and reporting of all changes per phase.

Generates two artifacts in logs/:
  - report.md          overall summary of all phases
  - <phase>/<file>.diff  unified diff for each changed file
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
    # Event recording
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
            "status": "BUILD_FAIL", "reason": "mvn clean test failed",
            "added": 0, "removed": 0,
        })

    def record_changed(self, phase: str, file_name: str, file_path: str,
                       original: str, new_code: str):
        """Records an accepted change and saves the diff to disk."""
        diff_lines = list(difflib.unified_diff(
            original.splitlines(keepends=True),
            new_code.splitlines(keepends=True),
            fromfile=f"original/{file_name}",
            tofile=f"refactored/{file_name}",
        ))

        added   = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))

        # Save diff to logs/<phase>/<file>.diff
        phase_slug = phase.replace(".md", "").replace(" ", "_")
        diff_dir   = os.path.join(LOGS_DIR, phase_slug)
        os.makedirs(diff_dir, exist_ok=True)
        diff_path  = os.path.join(diff_dir, f"{file_name}.diff")

        with open(diff_path, "w", encoding="utf-8") as f:
            f.writelines(diff_lines if diff_lines else ["(no differences)\n"])

        log(f"  Diff saved: +{added} -{removed} lines → {diff_path}")

        self._entries.append({
            "phase": phase, "file": file_name,
            "status": "CHANGED", "reason": "",
            "added": added, "removed": removed,
            "diff": diff_path,
        })

    # ------------------------------------------------------------------
    # Final report generation
    # ------------------------------------------------------------------

    def save_report(self):
        report_path = os.path.join(LOGS_DIR, "report.md")

        # Group by phase
        phases: dict[str, list[dict]] = {}
        for e in self._entries:
            phases.setdefault(e["phase"], []).append(e)

        lines = [
            f"# AI Refactor Agent — Execution Report\n",
            f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n",
        ]

        total_changed  = sum(1 for e in self._entries if e["status"] == "CHANGED")
        total_rejected = sum(1 for e in self._entries if e["status"] == "REJECTED")
        total_fail     = sum(1 for e in self._entries if e["status"] == "BUILD_FAIL")
        total_skip     = sum(1 for e in self._entries if e["status"] == "SKIP")

        lines += [
            "## Summary\n\n",
            f"| Metric | Value |\n",
            f"|---|---|\n",
            f"| Files successfully changed | {total_changed} |\n",
            f"| Rejected by validator | {total_rejected} |\n",
            f"| Reverted (build broke) | {total_fail} |\n",
            f"| Skipped (AI generated no code) | {total_skip} |\n\n",
        ]

        for phase, entries in phases.items():
            changed  = [e for e in entries if e["status"] == "CHANGED"]
            problems = [e for e in entries if e["status"] != "CHANGED"]

            lines.append(f"## Phase: `{phase}`\n\n")

            if changed:
                lines.append(f"### Accepted changes ({len(changed)})\n\n")
                lines.append("| File | +lines | -lines | Diff |\n")
                lines.append("|---|---|---|---|\n")
                for e in changed:
                    diff_link = f"[view]({e.get('diff', '')})" if e.get("diff") else "—"
                    lines.append(f"| `{e['file']}` | +{e['added']} | -{e['removed']} | {diff_link} |\n")
                lines.append("\n")

            if problems:
                lines.append(f"### Unchanged ({len(problems)})\n\n")
                lines.append("| File | Status | Reason |\n")
                lines.append("|---|---|---|\n")
                for e in problems:
                    lines.append(f"| `{e['file']}` | {e['status']} | {e['reason']} |\n")
                lines.append("\n")

        with open(report_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        log(f"Report saved to: {report_path}", "OK")
        return report_path