"""
java/method_runner.py — LLM runner operating method by method.

Per-file flow:
  1. Extract all methods from the file
  2. For each unprocessed method:
     a. Check if it needs refactoring (_needs_method_refactoring)
     b. Build context: class skeleton + target method + flow context
     c. Call LLM — instruct it to return ONLY the modified method
     d. Extract method from response and merge back into the file
     e. mvn compile — accept or revert
     f. Mark method in cache
  3. For phases that need the full class (e.g. solid-dip):
     compress already-done methods and send the condensed class

Integration:
  Called by llm_runner when skill_config has 'method_level: true'.
  For skill_config with 'method_level: false' (solid-dip), uses class_compressor.
"""

import os
import re

from core.logger import log
from core.live_state import update as _live
from core.utils import read_file, write_file, run_cmd, load_skill
from ai.model import call_ai
from java.refactor import get_java_files
from java.maven_build import ENV_WRAPPER
from java.community_runner import format_single_file
from java.method_extractor import extract_methods, MethodDef
from java.class_context_builder import (
    build_method_context,
    compress_done_methods,
    merge_method,
    extract_method_from_response,
)


def run_method_skill(skill_config: dict, repo_path: str,
                     cache=None, exec_logger=None) -> tuple[bool, str]:
    """
    Method-by-method runner. Used by llm_runner when method_level=true.
    Returns (any_changed, diff).
    """
    skill_id         = skill_config.get("skill", "unknown")
    rules            = _load_rules(skill_config)
    class_level      = skill_config.get("class_level", False)
    skip_compression = skill_config.get("skip_compression", False)

    if not rules:
        log(f"[MethodRunner] No rules found for '{skill_id}'", "ERR")
        return False, ""

    java_files  = get_java_files(repo_path, tests=False)
    any_changed = False

    _live(active_skill=skill_id, current_file="")
    log(f"[MethodRunner] {skill_id}: {len(java_files)} candidate files")

    for file_path in java_files:
        file_name = os.path.basename(file_path)

        # Skip file already processed in all relevant phases
        if cache and cache.is_phase_done(file_path, skill_id):
            continue

        code = read_file(file_path)
        if not code:
            continue

        from java.llm_runner import _is_structural_type
        if _is_structural_type(code, file_path):
            if cache:
                cache.mark_phase_done(file_path, skill_id)
            if exec_logger:
                exec_logger.log_file_skipped(skill_id, file_name, "no_business_logic")
            continue

        if class_level:
            changed = _run_class_level(
                file_path, file_name, code, rules, skill_id,
                repo_path, cache, exec_logger,
                skip_compression=skip_compression,
            )
        else:
            # Method-level phase: iterate method by method
            changed = _run_method_level(
                file_path, file_name, code, rules, skill_id,
                repo_path, cache, exec_logger,
                skill_config=skill_config,
            )

        if changed:
            any_changed = True

    diff = _get_diff(repo_path)
    return any_changed, diff


# ---------------------------------------------------------------------------
# Method-by-method refactoring
# ---------------------------------------------------------------------------

def _run_method_level(file_path: str, file_name: str, code: str,
                      rules: str, skill_id: str, repo_path: str,
                      cache, exec_logger, skill_config: dict) -> bool:
    """Iterates over each method in the file, refactoring them individually."""
    # C1: controller-lean should only run on @RestController classes
    if skill_config.get("detect_pattern") == "controller_logic" and "@RestController" not in code:
        if cache:
            cache.mark_phase_done(file_path, skill_id)
        if exec_logger:
            exec_logger.log_file_skipped(skill_id, file_name, "not_a_controller")
        return False

    methods = extract_methods(code)
    if not methods:
        if cache:
            cache.mark_phase_done(file_path, skill_id)
        return False

    detect_fn = _get_method_detector(skill_config.get("detect_pattern", ""))
    file_changed = False

    for method in methods:
        if method.is_constructor:
            continue  # constructors are not refactored in these phases

        # Method-level cache
        if cache and cache.is_method_done(file_path, method.cache_key, skill_id):
            continue

        # Pre-filter: does the method contain the target pattern?
        if detect_fn and not detect_fn(method.body):
            if cache:
                cache.mark_method_done(file_path, method.cache_key, skill_id)
            continue

        log(f"  [{skill_id}] {file_name}::{method.cache_key[:60]}...")
        _live(active_skill=skill_id, current_file=f"{file_name}")

        if exec_logger:
            exec_logger.log_file_processing(skill_id, f"{file_name}::{_short_sig(method)}", "java", "refactor")

        # Read current file code (may have been modified by previous method edits)
        current_code = read_file(file_path)
        current_methods = extract_methods(current_code)
        current_method = _find_method(current_methods, method.cache_key)
        if not current_method:
            # Method not found after earlier edits — skip
            if cache:
                cache.mark_method_done(file_path, method.cache_key, skill_id)
            continue

        # Build prompt: class skeleton + target method
        method_context = build_method_context(current_code, current_method)
        method_rules = (
            f"{rules}\n\n"
            "### REFACTORING SCOPE\n"
            "Refactor ONLY the TARGET METHOD shown above.\n"
            "Return ONLY the refactored method (annotations + signature + body).\n"
            "Do NOT return the full class. Do NOT modify any other method.\n"
            "Do NOT change the method signature or return type.\n"
        )

        response = call_ai(
            current_method.full_text,
            method_rules,
            "refactor",
            file_name,
            file_path=file_path,
            phase=skill_id,
            dep_context=method_context,
            max_agent=skill_config.get("max_agent"),
        )

        if not response:
            if cache:
                cache.mark_method_done(file_path, method.cache_key, skill_id)
            continue

        new_method_text = extract_method_from_response(response)
        if not new_method_text or _normalize(new_method_text) == _normalize(current_method.full_text):
            log(f"  [{skill_id}] {file_name}::{_short_sig(method)} — no change")
            if cache:
                cache.mark_method_done(file_path, method.cache_key, skill_id)
            continue

        # Merge: replace only the target method in the file
        updated_code = merge_method(current_code, current_method, new_method_text)
        write_file(file_path, updated_code)

        if _mvn_compile(repo_path):
            log(f"  [{skill_id}] {file_name}::{_short_sig(method)} — accepted ✓", "OK")
            file_changed = True
            if cache:
                cache.mark_method_done(file_path, method.cache_key, skill_id)
            if exec_logger:
                exec_logger.log_file_accepted(skill_id, f"{file_name}::{_short_sig(method)}", "+refactor")
        else:
            log(f"  [{skill_id}] {file_name}::{_short_sig(method)} — compile failed, reverting", "WARN")
            write_file(file_path, current_code)  # revert to pre-merge state
            if exec_logger:
                exec_logger.log_file_reverted(skill_id, f"{file_name}::{_short_sig(method)}", "compile_failed")

        _live(active_skill="")

    # Mark file as done once all methods have been evaluated
    if cache:
        cache.mark_phase_done(file_path, skill_id)

    return file_changed


# ---------------------------------------------------------------------------
# Class-level refactoring with compression of already-done methods
# ---------------------------------------------------------------------------

def _run_class_level(file_path: str, file_name: str, code: str,
                     rules: str, skill_id: str, repo_path: str,
                     cache, exec_logger, skip_compression: bool = False) -> bool:
    """
    Sends the class to the LLM for structural refactoring (e.g. solid-dip).
    skip_compression=True: sends the full original code without method compression.
    skip_compression=False: compresses already-processed methods to reduce tokens.
    """
    # C4: pre-filter — no concrete instantiations (new ConcreteClass()) = DIP not applicable
    # Also skips bootstrap classes that are rarely candidates for injection
    _NO_NEW = not re.search(r'\bnew\s+[A-Z]\w+\s*\(', code)
    _BOOTSTRAP = bool(re.search(r'@(SpringBootApplication|SpringBootTest|Configuration)\b', code))
    if _NO_NEW or _BOOTSTRAP:
        reason = "no_new_instantiation" if _NO_NEW else "bootstrap_class"
        log(f"  [{skill_id}] {file_name} — pre-filter ({reason}), skipping")
        if cache:
            cache.mark_phase_done(file_path, skill_id)
        if exec_logger:
            exec_logger.log_file_skipped(skill_id, file_name, reason)
        return False

    # M4: avoid structural conflict — skip if flow-refactor already processed this file
    if cache and cache.is_phase_done(file_path, "flow-refactor"):
        log(f"  [{skill_id}] {file_name} — flow-refactor applied, deferring solid-dip")
        if cache:
            cache.mark_phase_done(file_path, skill_id)
        if exec_logger:
            exec_logger.log_file_skipped(skill_id, file_name, "deferred_flow_refactor")
        return False

    # C4b: skip files with repeated failures in this phase (avoids wasting ~56min on futile retries)
    from java.refactor import get_failed_tracker as _get_tracker
    _tracker = _get_tracker()
    if _tracker.is_permanent_skip(file_path, skill_id):
        log(f"  [{skill_id}] {file_name} — permanent skip (previous failures), skipping", "WARN")
        if cache:
            cache.mark_phase_done(file_path, skill_id)
        if exec_logger:
            exec_logger.log_file_skipped(skill_id, file_name, "permanent_skip")
        return False

    if skip_compression:
        payload = code
        log(f"  [{skill_id}] {file_name} — full class ({len(code.splitlines())} lines, no compression)")
    else:
        done_keys: set[str] = set()
        if cache:
            for phase in ("guard-clauses", "controller-lean", "method-extraction"):
                done_keys |= cache.done_method_keys(file_path, phase)
        payload = compress_done_methods(code, done_keys)
        log(f"  [{skill_id}] {file_name} — compressed class ({len(payload.splitlines())} lines vs {len(code.splitlines())} original)")

    _live(active_skill=skill_id, current_file=file_name)

    if exec_logger:
        exec_logger.log_file_processing(skill_id, file_name, "java", "refactor")

    new_code = call_ai(
        payload, rules, "refactor", file_name,
        file_path=file_path,
        phase=skill_id,
    )

    if not new_code or _normalize(new_code) == _normalize(payload):
        log(f"  [{skill_id}] {file_name} — no change")
        if cache:
            cache.mark_phase_done(file_path, skill_id)
        # A3: emit trackable event for dashboard even when there is no change
        if exec_logger:
            exec_logger.log_file_skipped(skill_id, file_name, "no_change")
        return False

    write_file(file_path, new_code)

    # A1: repair loop — up to MAX_RETRIES attempts if compile fails
    from config import MAX_RETRIES as _MAX_RETRIES
    from ai.model import call_ai_with_correction as _repair
    attempt = 0
    while not _mvn_compile(repo_path):
        attempt += 1
        _, stdout, stderr = run_cmd(ENV_WRAPPER.format("mvn compile -q"), cwd=repo_path)
        err_output = (stderr or stdout or "compile error").strip()

        if attempt > _MAX_RETRIES:
            log(f"  [{skill_id}] {file_name} — {attempt - 1} repairs exhausted, reverting", "WARN")
            run_cmd(f'git checkout -- "{file_path}"', cwd=repo_path)
            if cache:
                cache.mark_phase_done(file_path, skill_id)
            if exec_logger:
                exec_logger.log_file_reverted(skill_id, file_name, "compile_failed")
            # S4: record with stack trace for future diagnostics
            from java.refactor import get_failed_tracker as _get_ft
            _get_ft().record(file_path, skill_id, "compile_failed",
                             stack_trace=err_output[-800:])
            return False

        log(f"  [{skill_id}] {file_name} — compile failed (attempt {attempt}/{_MAX_RETRIES}), repairing...", "WARN")

        repaired = _repair(
            new_code, rules, "refactor", file_name,
            file_path=file_path,
            bad_output=new_code,
            error_reason=err_output,
            phase=skill_id,
        )
        if not repaired or _normalize(repaired) == _normalize(new_code):
            log(f"  [{skill_id}] {file_name} — repair produced no change, reverting", "WARN")
            run_cmd(f'git checkout -- "{file_path}"', cwd=repo_path)
            if cache:
                cache.mark_phase_done(file_path, skill_id)
            if exec_logger:
                exec_logger.log_file_reverted(skill_id, file_name, "repair_no_change")
            # S4: record with stack trace for future diagnostics
            from java.refactor import get_failed_tracker as _get_ft
            _get_ft().record(file_path, skill_id, "repair_no_change",
                             stack_trace=err_output[-800:])
            return False
        new_code = repaired
        write_file(file_path, new_code)

    format_single_file(file_path, repo_path)
    log(f"  [{skill_id}] {file_name} — accepted ✓", "OK")
    if cache:
        cache.mark_phase_done(file_path, skill_id)
    if exec_logger:
        exec_logger.log_file_accepted(skill_id, file_name, "+refactor")
    return True


# ---------------------------------------------------------------------------
# Method-level pattern detectors
# ---------------------------------------------------------------------------

def _get_method_detector(pattern_key: str):
    """Returns the detection function for the skill pattern, at method level."""
    detectors = {
        "nested_if":        _method_has_nested_if,
        "long_method":      _method_is_long,
        "controller_logic": _method_has_logic,
    }
    return detectors.get(pattern_key)


def _method_has_nested_if(body: str) -> bool:
    depth = 0
    max_depth = 0
    for line in body.splitlines():
        s = line.strip()
        if re.match(r'if\s*\(', s):
            depth += 1
            max_depth = max(max_depth, depth)
        depth -= s.count('}')
        depth = max(depth, 0)
    return max_depth >= 3


def _method_is_long(body: str) -> bool:
    return len([l for l in body.splitlines() if l.strip()]) > 30


def _method_has_logic(body: str) -> bool:
    return bool(re.search(r'(if\s*\(|for\s*\(|while\s*\(|\bswitch\s*\()', body))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_method(methods: list[MethodDef], cache_key: str) -> MethodDef | None:
    return next((m for m in methods if m.cache_key == cache_key), None)


def _short_sig(method: MethodDef) -> str:
    """Short version of the signature for logs (up to 60 chars)."""
    s = method.signature
    return s[:57] + "..." if len(s) > 60 else s


def _normalize(code: str) -> str:
    return re.sub(r'\s+', ' ', code.strip())


def _load_rules(skill_config: dict) -> str:
    rules = skill_config.get("rules", "")
    if rules:
        return rules
    skill_name = skill_config.get("skill_name", "") or skill_config.get("skill", "")
    section    = skill_config.get("skill_section", "LLM INSTRUCTIONS")
    if skill_name:
        loaded = load_skill(skill_name, section=section)
        if loaded:
            return loaded
    return ""


def _mvn_compile(repo_path: str) -> bool:
    cmd = ENV_WRAPPER.format("mvn compile -q")
    code, _, _ = run_cmd(cmd, cwd=repo_path)
    return code == 0


def _get_diff(repo_path: str) -> str:
    code, out, _ = run_cmd("git diff --unified=5", cwd=repo_path)
    return out if code == 0 else ""
