"""
java/javadoc_runner.py — Inserts Javadoc on all public methods.

Per-file flow:
  1. Read the full Java file
  2. Send to the LLM with documentation instructions
  3. LLM adds /** */ where missing, without touching method bodies
  4. mvn compile — accept or revert
  5. Emit events for the dashboard (FILE_ACCEPTED / FILE_REVERTED / FILE_SKIPPED)

Resilience:
  - Each file is processed in a daemon thread with FILE_TIMEOUT_SECS timeout
  - Per-file exceptions do not interrupt the main loop
"""

import os
import re
import threading

from core.logger import log
from core.live_state import update as _live
from core.utils import read_file, write_file, run_cmd, load_skill
from ai.model import call_ai, call_model
from ai.sanitizer import clean_output
from java.refactor import get_java_files
from java.maven_build import ENV_WRAPPER
from java.community_runner import format_single_file

SKILL_ID = "javadoc"
FILE_TIMEOUT_SECS = 300  # 5 minutes per file

# C4: Spring bootstrap/config classes must not receive Javadoc (same rule as method_runner)
_BOOTSTRAP_RE = re.compile(r'@(SpringBootApplication|Configuration|SpringBootTest)\b')


def run_javadoc(repo_path: str, exec_logger=None) -> None:
    """Iterates over all production Java files and inserts Javadoc on public methods."""
    rules = load_skill("java-javadoc", section="LLM INSTRUCTIONS")
    if not rules:
        log("[Javadoc] Skill 'java-javadoc' not found — skipping phase", "WARN")
        return

    java_files = get_java_files(repo_path, tests=False)
    log(f"[Javadoc] {len(java_files)} candidate files")
    _live(active_skill=SKILL_ID, current_file="")

    # C3: save pre-javadoc content for each file BEFORE launching the thread.
    # On timeout the daemon may have written partial code — restore the saved
    # content (not from git), preserving refactoring from earlier phases.
    pre_javadoc: dict[str, str] = {}

    for file_path in java_files:
        file_name = os.path.basename(file_path)
        try:
            pre_javadoc[file_path] = read_file(file_path) or ""
            t = threading.Thread(
                target=_process_one_file,
                args=(file_path, rules, repo_path, exec_logger),
                daemon=True,
            )
            t.start()
            t.join(FILE_TIMEOUT_SECS)
            if t.is_alive():
                log(f"  [javadoc] {file_name} — timeout ({FILE_TIMEOUT_SECS}s), skipping", "WARN")
                # Restore pre-javadoc content (preserve refactoring from earlier phases)
                saved = pre_javadoc.get(file_path, "")
                if saved:
                    write_file(file_path, saved)
                    log(f"  [javadoc] {file_name} — pre-javadoc content restored", "WARN")
                if exec_logger:
                    exec_logger.log_file_skipped(SKILL_ID, file_name, "timeout")
        except Exception as exc:
            log(f"  [javadoc] {file_name} — unexpected error: {exc}", "WARN")
            if exec_logger:
                exec_logger.log_file_skipped(SKILL_ID, file_name, "error")

    _live(active_skill="", current_file="")


def _process_one_file(file_path: str, rules: str, repo_path: str, exec_logger) -> None:
    """Processes a single Java file — inserts Javadoc. Runs in a daemon thread."""
    file_name = os.path.basename(file_path)
    code = read_file(file_path)
    if not code:
        return

    # C4: bootstrap/config classes must not receive Javadoc
    if _BOOTSTRAP_RE.search(code):
        log(f"  [javadoc] {file_name} — bootstrap/config class, skipping")
        if exec_logger:
            exec_logger.log_file_skipped(SKILL_ID, file_name, "bootstrap_class")
        return

    # C: @Document/@Entity/record/enum are data holders with no relevant business logic.
    # Both models (J1 primary and retry) modify these types structurally →
    # skipping avoids cascading code_structure_changed and wasted time.
    if re.search(r'@(Document|Entity|Table)\b', code) or re.search(r'\b(record|enum)\b', code):
        log(f"  [javadoc] {file_name} — data holder (@Document/record/enum), skipping")
        if exec_logger:
            exec_logger.log_file_skipped(SKILL_ID, file_name, "data_holder")
        return

    if _all_public_methods_documented(code):
        log(f"  [javadoc] {file_name} — already documented, skipping")
        if exec_logger:
            exec_logger.log_file_skipped(SKILL_ID, file_name, "already_documented")
        return

    _live(active_skill=SKILL_ID, current_file=file_name)
    if exec_logger:
        exec_logger.log_file_processing(SKILL_ID, file_name, "java", "javadoc")

    log(f"  [javadoc] {file_name}")
    new_code = call_ai(
        code, rules, "refactor", file_name,
        file_path=file_path,
        phase=SKILL_ID,
    )

    if not new_code or _normalize(new_code) == _normalize(code):
        log(f"  [javadoc] {file_name} — no change")
        if exec_logger:
            exec_logger.log_file_skipped(SKILL_ID, file_name, "no_change")
        return

    # C1: structural integrity check — LLM may only have added comments
    if _strip_comments(new_code) != _strip_comments(code):
        log(f"  [javadoc] {file_name} — LLM modified code beyond comments, retrying with code-specialized model...", "WARN")

        # J1: retry with MODEL_STRUCT (qwen2.5-coder:7b) before rejecting — neural-chat:7b
        # modifies code systematically; a code-specialized model respects scope better.
        from config import MODEL_STRUCT
        from ai.prompt import build_prompt
        _retry_rules = (
            rules + "\n\n### CRITICAL: YOUR PREVIOUS ATTEMPT WAS REJECTED\n"
            "You modified code beyond adding Javadoc comments — this is FORBIDDEN.\n"
            "Add ONLY `/** ... */` blocks. Every method body, signature, import, "
            "field declaration, and blank line must remain byte-for-byte identical.\n"
        )
        _retry_prompt = build_prompt(code, _retry_rules, "refactor", file_name)
        _raw2, _ = call_model(MODEL_STRUCT, _retry_prompt, temperature=0.05, num_predict=4096)
        _retry_code = clean_output(_raw2)

        if _retry_code and _strip_comments(_retry_code) == _strip_comments(code):
            log(f"  [javadoc] {file_name} — retry with {MODEL_STRUCT} accepted ✓", "OK")
            new_code = _retry_code
        else:
            log(f"  [javadoc] {file_name} — retry also modified code, rejecting", "WARN")
            if exec_logger:
                exec_logger.log_file_skipped(SKILL_ID, file_name, "code_structure_changed")
            # S3: accumulate in FailedFilesTracker → permanent_skip after 3 consecutive cycles
            from java.refactor import get_failed_tracker as _get_ft
            _get_ft().record(file_path, SKILL_ID, "code_structure_changed")
            return

    write_file(file_path, new_code)
    rc, _, _ = run_cmd(ENV_WRAPPER.format("mvn compile -q"), cwd=repo_path)
    if rc == 0:
        format_single_file(file_path, repo_path)
        log(f"  [javadoc] {file_name} — accepted ✓", "OK")
        if exec_logger:
            exec_logger.log_file_accepted(SKILL_ID, file_name, "+javadoc")
    else:
        log(f"  [javadoc] {file_name} — compile failed, reverting", "WARN")
        write_file(file_path, code)
        if exec_logger:
            exec_logger.log_file_reverted(SKILL_ID, file_name, "compile_failed")


# ---------------------------------------------------------------------------
# Heuristic: check whether all visible public methods already have Javadoc
# ---------------------------------------------------------------------------

_RE_METHOD_LINE = re.compile(
    r'public\s+(?!class\b|interface\b|enum\b|@interface\b)'
    r'(?:(?:static|final|synchronized|abstract|default)\s+)*'
    r'[\w<>\[\],\s]+\s+\w+\s*\(',
)


def _all_public_methods_documented(code: str) -> bool:
    """
    Returns True if all visible public methods already have Javadoc.
    Uses a line-by-line scan to avoid variable-length lookbehind.
    """
    lines = code.splitlines()
    total = 0
    documented = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not _RE_METHOD_LINE.match(stripped):
            continue
        total += 1
        # Look back up to 6 lines for the end of a Javadoc block
        for j in range(i - 1, max(-1, i - 7), -1):
            prev = lines[j].strip()
            # End of multi-line Javadoc ('*/') or single-line Javadoc ('/** ... */')
            if prev.endswith('*/') and (prev == '*/' or prev.startswith('/*')):
                documented += 1
                break
            # Stop searching if non-Javadoc code found (not an annotation or comment)
            if prev and not prev.startswith('*') and not prev.startswith('/*') and not prev.startswith('@'):
                break
    if total == 0:
        return True
    return documented >= total


def _strip_comments(code: str) -> str:
    """Removes all Java comments for structural comparison.
    Detects whether the LLM changed code beyond adding /** */ blocks."""
    # Remove block comments (/** ... */ and /* ... */)
    stripped = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
    # Remove line comments (//)
    stripped = re.sub(r'//[^\n]*', '', stripped)
    # Normalize whitespace for robust comparison
    return re.sub(r'\s+', ' ', stripped.strip())


def _normalize(code: str) -> str:
    return re.sub(r'\s+', ' ', code.strip())
