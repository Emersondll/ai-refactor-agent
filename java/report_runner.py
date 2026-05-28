"""
java/report_runner.py — Generates a Markdown refactoring report per class.

Flow:
  1. Reads execution.jsonl and groups events by file
  2. Builds a structured summary (what was applied, skipped, and why)
  3. Sends the summary to the LLM to generate a readable Markdown narrative
  4. Saves to logs/refactoring_report.md and src/main/resources/docs/ in the repo
"""

import json
import os
import re
from datetime import datetime

from core.logger import log
from core.live_state import update as _live
from config import BASE_DIR, REPO_GITHUB_URL

# ---------------------------------------------------------------------------
# Human-readable label mappings
# ---------------------------------------------------------------------------

_PHASE_LABELS = {
    "clean-imports":        "Removal of unused imports (OpenRewrite)",
    "format":               "Code formatting (Google Java Format)",
    "final-keywords":       "Addition of `final` modifiers",
    "naming-conventions":   "Naming convention corrections",
    "dead-code":            "Dead code removal",
    "simplify-code":        "Code simplification (expressions, ternaries)",
    "modernize-syntax":     "Java syntax modernization (streams, lambdas, var)",
    "static-analysis":      "Static analysis and fixes (SpotBugs/PMD patterns)",
    "guard-clauses":        "Guard clause refactoring (early return)",
    "method-extraction":    "Long method extraction",
    "solid-dip":            "DIP application — dependency injection via constructor",
    "controller-lean":      "Business logic removal from Controller",
    "flow-refactor":        "Control flow refactoring",
    "dry-check":            "Duplication detection and elimination (DRY)",
    "javadoc":              "Javadoc insertion on public methods",
    "initial_coverage_fix": "Automatic test coverage generation",
    "flow-dry":             "DRY check for flows (dry-run)",
}

_SKIP_LABELS = {
    "no_business_logic":        "Structural type without business logic (interface, @Document, @Entity, repository, DTO) — phase not applicable",
    "not_a_controller":         "Not a @RestController — controller-lean phase does not apply",
    "no_change":                "Code already compliant with phase criteria — no changes needed",
    "no_pattern_match":         "No method in the class matched the target pattern — phase not applicable",
    "compile_failed":           "Generation failed after multiple repair attempts — change reverted to preserve stable build",
    "already_documented":       "All public methods already have Javadoc",
    "deferred_field_injection": "Class uses @Autowired on field without explicit constructor — awaiting conversion to constructor injection (solid-dip)",
    "repair_no_change":         "Automatic repair produced no valid change — operation cancelled",
    "no_new_instantiation":     "Class has no concrete instantiations (new ConcreteClass()) — dependency injection not applicable",
    "bootstrap_class":          "Configuration/bootstrap class (@SpringBootApplication, @Configuration) — DIP not applicable",
    "deferred_flow_refactor":   "Class was already processed by flow-refactor — solid-dip deferred to avoid structural conflict",
    "deferred_repeat_failure":  "Class failed this phase in a previous cycle — deferred for manual review",
    "timeout":                  "Processing exceeded per-file time limit — operation cancelled to avoid blocking pipeline",
    "permanent_skip":           "Class reached the consecutive failure limit in this phase — marked for manual review",
    "code_structure_changed":   "LLM altered code structure beyond Javadoc comments — change rejected to preserve integrity",
}


# ---------------------------------------------------------------------------
# M11: Fix Candidates section
# ---------------------------------------------------------------------------

def _build_fix_candidates_section(entries: list[dict], fixes: list[dict] | None = None) -> str:
    """Return a Markdown section listing permanent_skip entries whose stack/reason
    is covered by a fix in fix_metadata.json that was applied AFTER the entry's
    timestamp. These files are likely to compile/pass on the next run if forced
    to retry. Returns empty string if no candidates.

    `entries`: contents of logs/failed_files.json
    `fixes`:   contents of logs/fix_metadata.json (or get_fixes() if None)
    """
    import datetime as _dt
    if fixes is None:
        try:
            from java.fix_metadata import get_fixes
            fixes = get_fixes()
        except Exception:
            fixes = []
    if not fixes:
        return ""

    candidates: list[tuple[str, list[str]]] = []  # (basename, [fix_ids])
    for e in entries or []:
        if not e.get("permanent_skip"):
            continue
        ts_raw = e.get("timestamp")
        if not ts_raw:
            continue
        try:
            entry_ts = _dt.datetime.fromisoformat(ts_raw)
        except Exception:
            continue
        haystack = (e.get("stack_trace") or "") + " " + (e.get("reason") or "")
        matching: list[str] = []
        for f in fixes:
            try:
                f_ts = _dt.datetime.fromisoformat(f.get("applied_at", ""))
            except Exception:
                continue
            if entry_ts >= f_ts:
                continue
            if any(p in haystack for p in f.get("patterns", [])):
                matching.append(f.get("id", "?"))
        if matching:
            basename = e["file"].split("/")[-1]
            candidates.append((basename, sorted(set(matching))))

    if not candidates:
        return ""

    lines = [
        "## Fix Candidates",
        "",
        "The following files are in `permanent_skip` but recent fixes "
        "in `logs/fix_metadata.json` cover their error patterns. "
        "Consider re-running with `FORCE_RETRY=<basename>` in `.env` "
        "or `python main.py --clear-skip <basename>` before the next run.",
        "",
        "| File | Candidate fixes |",
        "|---------|------------------|",
    ]
    for basename, fix_ids in candidates:
        lines.append(f"| `{basename}` | {', '.join(fix_ids)} |")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSONL data extraction
# ---------------------------------------------------------------------------

def _load_session(jsonl_path: str) -> list[dict]:
    with open(jsonl_path) as f:
        entries = [json.loads(l) for l in f if l.strip()]
    start = 0
    for i, e in enumerate(entries):
        if e.get("event") == "GIT_BRANCH_CREATED":
            start = i
    return entries[start:]


def _build_class_summaries(session: list[dict]) -> dict:
    """Returns dict {filename: {accepted:[phases], skipped:{phase:reason}, reverted:[phases]}}."""
    summaries = {}
    coverages = []

    for e in session:
        ev  = e.get("event", "")
        ph  = e.get("phase", "") or ""
        fi  = (e.get("file", "") or "").split("::")[0]
        msg = e.get("message", "")

        if ev == "COVERAGE":
            m = re.search(r"(\d+\.\d+)%", msg)
            if m:
                coverages.append((e["timestamp"], float(m.group(1)), msg))
            continue

        if not fi:
            continue

        if fi not in summaries:
            summaries[fi] = {"accepted": [], "skipped": {}, "reverted": []}

        if ev == "FILE_ACCEPTED":
            if ph not in summaries[fi]["accepted"]:
                summaries[fi]["accepted"].append(ph)

        elif ev == "FILE_SKIPPED":
            raw_reason = msg.replace("Pulado: ", "").replace("Skipped: ", "").strip()
            summaries[fi]["skipped"][ph] = raw_reason

        elif ev == "FILE_REVERTED":
            if ph not in summaries[fi]["reverted"]:
                summaries[fi]["reverted"].append(ph)

    return summaries, coverages


def _build_text_summary(summaries: dict, coverages: list, session: list[dict]) -> str:
    """Serializes the structured summary as compact text for the LLM."""
    start_ts = session[0]["timestamp"]
    end_ts   = session[-1]["timestamp"]
    dur_sec  = int((datetime.fromisoformat(end_ts) - datetime.fromisoformat(start_ts)).total_seconds())
    h, r = divmod(dur_sec, 3600)
    m, _ = divmod(r, 60)

    lines = [
        f"CYCLE: {start_ts[:10]}  DURATION: {h}h {m}m",
        "",
    ]
    if coverages:
        for ts, val, msg in coverages:
            lines.append(f"COVERAGE [{ts[11:16]}]: {val:.2f}% — {msg}")
    lines.append("")

    for fname in sorted(summaries):
        s = summaries[fname]
        acc_labels = [_PHASE_LABELS.get(p, p) for p in s["accepted"]]
        rev_labels = [_PHASE_LABELS.get(p, p) for p in s["reverted"]]
        skip_items = {
            ph: _SKIP_LABELS.get(r, r)
            for ph, r in s["skipped"].items()
            if ph not in s["accepted"]  # ignore skips in phases where the file was later accepted
        }

        lines.append(f"FILE: {fname}")
        if acc_labels:
            lines.append(f"  IMPROVEMENTS APPLIED: {' | '.join(acc_labels)}")
        if rev_labels:
            lines.append(f"  REVERTED IN: {' | '.join(rev_labels)}")
        if skip_items:
            for ph, reason in skip_items.items():
                ph_label = _PHASE_LABELS.get(ph, ph)
                lines.append(f"  SKIPPED [{ph_label}]: {reason}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Chamada LLM
# ---------------------------------------------------------------------------

_REPORT_PROMPT = """You are a senior software engineer reviewing an automated refactoring cycle of a Java Spring Boot project.

Below are the structured execution data from the refactoring pipeline:

{summary}

Based on this data, generate a TECHNICAL REPORT in Markdown with the following structure:

# Refactoring Report — {date}

## Overview
[3-4 sentence paragraph describing the cycle: duration, initial and final coverage, how many classes were modified, skipped, and reverted.]

## Test Coverage
[Table or list showing the coverage trajectory: initial → post test generation → final.]

## Modified Classes
[For each file with APPLIED IMPROVEMENTS, one item with: class name in bold, list of applied improvements with description of the impact on the code.]

## Skipped Classes
[For each file that was SKIPPED in ALL refactoring phases, one item with: class name in bold, clear and objective reason (why the class did not need changes).]

## Reverted Classes
[For each file with REVERTED IN, one item with: class name in bold, phase that reverted, probable technical reason, and manual action recommendation.]

## Observations and Next Steps
[2-3 observations about patterns identified in the cycle and improvement suggestions.]

Rules:
- Write in Brazilian Portuguese
- Be objective and technical, but readable for developers without pipeline context
- Use affirmative language: "X improvements were applied", not "the agent tried"
- Do not mention internal agent details (model names, phase IDs, etc.)
"""


def _call_llm_for_report(summary_text: str, date: str) -> str | None:
    try:
        from ai.model import call_claude, _try_local_agent
        from config import MODEL_REVIEWER
    except Exception:
        return None

    prompt = _REPORT_PROMPT.format(summary=summary_text, date=date)

    # Try Claude first (best quality for narrative reports)
    try:
        result = call_claude(prompt)
        if result and len(result) > 200:
            log("[Report] Report generated via Claude ✓", "OK")
            return result
    except Exception:
        pass

    # Fallback: local model — call call_model directly (output is Markdown, not Java)
    try:
        from ai.model import call_model
        raw, is_oom = call_model(MODEL_REVIEWER, prompt, temperature=0.3,
                                 num_predict=4096, timeout=600)
        if raw and not is_oom and len(raw.strip()) > 200:
            log("[Report] Report generated via local model ✓", "OK")
            return raw.strip()
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Fallback generator (no LLM)
# ---------------------------------------------------------------------------

def _build_fallback_report(summaries: dict, coverages: list, session: list[dict]) -> str:
    """Pure structured report, no LLM narrative."""
    start_ts = session[0]["timestamp"]
    end_ts   = session[-1]["timestamp"]
    dur_sec  = int((datetime.fromisoformat(end_ts) - datetime.fromisoformat(start_ts)).total_seconds())
    h, r = divmod(dur_sec, 3600)
    m, _ = divmod(r, 60)
    date = start_ts[:10]

    accepted_files = [f for f, s in summaries.items() if s["accepted"]]
    reverted_files = [f for f, s in summaries.items() if s["reverted"]]
    skipped_only   = [
        f for f, s in summaries.items()
        if not s["accepted"] and not s["reverted"] and s["skipped"]
    ]

    lines = [
        f"# Refactoring Report — {date}",
        "",
        f"**Duration:** {h}h {m}m  |  **Modified classes:** {len(accepted_files)}  |  "
        f"**Skipped:** {len(skipped_only)}  |  **Reverted:** {len(reverted_files)}",
        "",
    ]

    if coverages:
        lines += ["## Test Coverage", ""]
        for _, val, msg in coverages:
            lines.append(f"- {msg}")
        lines.append("")

    if accepted_files:
        lines += ["## Modified Classes", ""]
        for fname in sorted(accepted_files):
            s = summaries[fname]
            lines.append(f"### {fname}")
            for ph in s["accepted"]:
                lines.append(f"- {_PHASE_LABELS.get(ph, ph)}")
            if s["reverted"]:
                lines.append(f"- ⚠ Reverted in: {', '.join(_PHASE_LABELS.get(p,p) for p in s['reverted'])}")
            lines.append("")

    if skipped_only:
        lines += ["## Skipped Classes", ""]
        for fname in sorted(skipped_only):
            s = summaries[fname]
            lines.append(f"### {fname}")
            seen = set()
            for ph, reason in s["skipped"].items():
                label = _SKIP_LABELS.get(reason, reason)
                if label not in seen:
                    lines.append(f"- {label}")
                    seen.add(label)
            lines.append("")

    if reverted_files:
        lines += ["## Reverted Classes", ""]
        for fname in sorted(reverted_files):
            s = summaries[fname]
            lines.append(f"### {fname}")
            for ph in s["reverted"]:
                lines.append(f"- Phase: {_PHASE_LABELS.get(ph, ph)}")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _build_report_with_header(report_body: str, repo_path: str) -> str:
    """Prepend the fixed Markdown header template to the LLM-generated report body."""
    template_path = os.path.join(BASE_DIR, "templates", "refactoring_report_header.md")
    try:
        with open(template_path, encoding="utf-8") as f:
            header = f.read()
    except Exception:
        header = ""

    if header:
        repo_name = os.path.basename(repo_path.rstrip("/\\"))
        repo_url  = REPO_GITHUB_URL or f"https://github.com/<org>/{repo_name}"
        header = header.replace("{repo_url}", repo_url).replace("{repo_name}", repo_name)
        # Strip the HTML comment block before rendering
        header = re.sub(r"<!--.*?-->", "", header, flags=re.DOTALL).strip()
        return header + "\n\n" + report_body
    return report_body


def run_report(repo_path: str, jsonl_path: str, logs_dir: str, exec_logger=None) -> None:
    """Generates the refactoring report and saves it to the logs directory and the repo."""
    _live(active_skill="report", current_file="")
    log("[Report] Loading cycle events...")

    if not os.path.exists(jsonl_path) or os.path.getsize(jsonl_path) == 0:
        log("[Report] execution.jsonl is empty — report not generated", "WARN")
        return

    session = _load_session(jsonl_path)
    summaries, coverages = _build_class_summaries(session)
    if not summaries:
        log("[Report] No file events found — report not generated", "WARN")
        return

    date = session[0]["timestamp"][:10]
    summary_text = _build_text_summary(summaries, coverages, session)

    log("[Report] Requesting narrative from LLM...")
    report_md = _call_llm_for_report(summary_text, date)

    if not report_md:
        log("[Report] LLM unavailable — generating structured report", "WARN")
        report_md = _build_fallback_report(summaries, coverages, session)

    # M11: Fix Candidates section
    try:
        import json as _json
        from java.fix_metadata import get_fixes as _get_fixes
        _failed_path = os.path.join(logs_dir, "failed_files.json")
        _failed_entries = []
        if os.path.exists(_failed_path):
            with open(_failed_path) as _f:
                _failed_entries = _json.load(_f)
        _section = _build_fix_candidates_section(_failed_entries, fixes=_get_fixes())
        if _section:
            report_md = report_md.rstrip() + "\n\n" + _section + "\n"
    except Exception as _exc:
        log(f"M11 fix-candidates section skipped: {_exc}", "WARN")

    # Build the full report: fixed header + LLM/fallback body
    full_report_md = _build_report_with_header(report_md, repo_path)

    # Save to logs directory (used by the dashboard)
    log_report_path = os.path.join(logs_dir, "refactoring_report.md")
    with open(log_report_path, "w", encoding="utf-8") as f:
        f.write(full_report_md)
    log(f"[Report] Saved to {log_report_path}", "OK")

    # Save to src/main/resources/docs/ inside the target repo (committed with the code)
    docs_dir = os.path.join(repo_path, "src", "main", "resources", "docs")
    os.makedirs(docs_dir, exist_ok=True)
    repo_report_path = os.path.join(docs_dir, "refactoring_report.md")
    with open(repo_report_path, "w", encoding="utf-8") as f:
        f.write(full_report_md)
    log(f"[Report] Saved to {repo_report_path}", "OK")

    if exec_logger:
        exec_logger.log_phase_start("REPORT_DONE", "Refactoring report generated")

    _live(active_skill="", current_file="")
