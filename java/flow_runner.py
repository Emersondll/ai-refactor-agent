"""
java/flow_runner.py — Endpoint-flow-oriented refactoring runner.

Two passes:
  1. EXCLUSIVE files  → refactored with context of the single flow that uses them
  2. SHARED files     → refactored with context of ALL flows that use them

Behavioral validation:
  - mvn compile -q per file (syntax)
  - mvn test per flow (behavior) → repair loop on production code if it fails

DRY check (tool: flow-dry):
  - Detects groups of repeated methods in 2+ files
  - LLM extracts them into a utility class, validated with mvn test
"""

import os
import re

from core.logger import log
from core.live_state import update as _live
from core.utils import read_file, write_file, run_cmd, load_skill
from ai.model import call_ai, call_ai_with_correction
from java.maven_build import ENV_WRAPPER, maven_test
from config import MAX_RETRIES

_MAX_REPAIR = MAX_RETRIES


def run_skill(skill_config: dict, repo_path: str, cache=None, exec_logger=None) -> tuple[bool, str]:
    """
    Flow-aware refactoring.
    tool: flow → called by main.py.
    """
    from java.endpoint_mapper import build_flow_map

    skill_id = skill_config.get("skill", "flow-refactor")
    rules    = _load_rules(skill_config)

    if not rules:
        log(f"[FlowRunner] No rules found for '{skill_id}'", "ERR")
        return False, ""

    log("[FlowRunner] Mapping endpoint flows...")
    flow_map     = build_flow_map(repo_path)
    flows        = flow_map["flows"]
    file_sharing = flow_map["file_sharing"]
    shared_files = set(file_sharing.keys())

    if not flows:
        log("[FlowRunner] No endpoints found in the project", "WARN")
        return False, ""

    log(f"[FlowRunner] {len(flows)} flows | {len(shared_files)} shared files")

    any_changed = False

    # ------------------------------------------------------------------
    # Pass 1 — Exclusive files (belong to only 1 flow)
    # ------------------------------------------------------------------
    log("[FlowRunner] Pass 1: exclusive files...")
    processed_exclusive: set[str] = set()

    for flow in flows:
        exclusive = [f for f in flow["files"] if f not in shared_files
                     and f not in processed_exclusive]
        if not exclusive:
            continue

        flow_context = _build_flow_context(flow, file_sharing, repo_path)
        flow_changed = False

        for file_path in exclusive:
            if _refactor_file(file_path, rules, skill_id, flow_context, repo_path, cache, exec_logger):
                flow_changed = True
                any_changed  = True
            processed_exclusive.add(file_path)

        # Validate behavior at the end of each flow
        if flow_changed:
            _validate_and_repair(
                flow["files"], rules, skill_id, flow_context, repo_path, cache
            )

    # ------------------------------------------------------------------
    # Pass 2 — Shared files (belong to 2+ flows)
    # ------------------------------------------------------------------
    log("[FlowRunner] Pass 2: shared files...")

    for file_path, endpoints in file_sharing.items():
        if cache and cache.is_phase_done(file_path, skill_id):
            continue

        containing_flows = [f for f in flows if file_path in f["files"]]
        multi_context    = _build_multi_flow_context(file_path, containing_flows, repo_path)
        label            = os.path.basename(file_path)

        log(f"  [FlowRunner] {label} — shared across {len(endpoints)} flows")

        if _refactor_file(file_path, rules, skill_id, multi_context, repo_path, cache, exec_logger):
            any_changed = True
            # Shared files: validate with full test immediately (higher risk)
            _validate_and_repair(
                [file_path], rules, skill_id, multi_context, repo_path, cache
            )

    diff = _get_diff(repo_path)
    return any_changed, diff


def dry_check(skill_config: dict, repo_path: str, exec_logger=None) -> tuple[bool, str]:
    """
    Detects repeated code across 2+ files and extracts it to a utility class.
    tool: flow-dry → called by main.py.
    """
    from java.refactor import get_java_files
    from java.llm_runner import _is_structural_type

    skill_id = skill_config.get("skill", "dry-check")
    rules    = _load_rules(skill_config)

    if not rules:
        log(f"[DryCheck] No rules found for '{skill_id}'", "ERR")
        return False, ""

    java_files = get_java_files(repo_path, tests=False)

    # C2: filter structural types before detecting DRY candidates
    filtered: list[str] = []
    for f in java_files:
        code = read_file(f) or ""
        if _is_structural_type(code, f):
            log(f"  [DryCheck] {os.path.basename(f)} — structural type, skipping")
        else:
            filtered.append(f)
    skipped_structural = len(java_files) - len(filtered)
    if skipped_structural:
        log(f"[DryCheck] {skipped_structural} structural files filtered before detection")

    candidates = _find_dry_candidates(filtered)

    if not candidates:
        log("[DryCheck] No DRY pattern detected", "OK")
        return False, ""

    log(f"[DryCheck] {len(candidates)} candidate groups")
    any_changed = False
    seen_files: set[str] = set()  # C3: deduplication across groups

    for group in candidates:
        # C3: remove files already included in previously processed groups
        group_files = [f for f in group["files"] if f not in seen_files]
        if len(group_files) < 2:
            log(f"  [DryCheck] group '{group['method']}' — < 2 files after deduplication, skipping")
            continue
        seen_files |= set(group_files)

        names = [os.path.basename(f) for f in group_files]
        log(f"  [DryCheck] analyzing: {names} (method: {group['method']})")
        _live(active_skill=skill_id, current_model="")
        group_label = f"DRYGroup({','.join(names)})"
        if exec_logger:
            for n in names:
                exec_logger.log_file_processing(skill_id, n, "java", "dry")

        group_code = "\n\n".join(
            f"// FILE: {os.path.basename(f)}\n{read_file(f)}"
            for f in group_files
            if read_file(f)
        )

        result = call_ai(
            group_code, rules, "refactor",
            group_label,
            phase=skill_id,
        )
        _live(active_skill="")

        if not result:
            if exec_logger:
                for n in names:
                    exec_logger.log_file_skipped(skill_id, n, "no_change")
            continue

        changed = _apply_dry_result(result, group_files, repo_path)
        if not changed:
            if exec_logger:
                for n in names:
                    exec_logger.log_file_skipped(skill_id, n, "no_change")
            continue

        ok, _ = maven_test(repo_path)
        if ok:
            log(f"  [DryCheck] extraction accepted ✓", "OK")
            any_changed = True
            if exec_logger:
                for n in names:
                    exec_logger.log_file_accepted(skill_id, n, "+dry")
        else:
            log(f"  [DryCheck] mvn test failed after extraction — reverting", "WARN")
            run_cmd("git restore .", cwd=repo_path)
            if exec_logger:
                for n in names:
                    exec_logger.log_file_reverted(skill_id, n, "test_failed")

    diff = _get_diff(repo_path)
    return any_changed, diff


# ---------------------------------------------------------------------------
# Core per-file refactoring
# ---------------------------------------------------------------------------

def _refactor_file(file_path: str, rules: str, skill_id: str,
                   flow_context: str, repo_path: str, cache,
                   exec_logger=None) -> bool:
    """Refactors a file with flow context. Returns True if accepted."""
    file_name = os.path.basename(file_path)

    if cache and cache.is_phase_done(file_path, skill_id):
        return False

    code = read_file(file_path)
    if not code:
        return False

    from java.llm_runner import _is_structural_type
    if _is_structural_type(code, file_path):
        if cache:
            cache.mark_phase_done(file_path, skill_id)
        # M3: emit skip event to dashboard
        if exec_logger:
            exec_logger.log_file_skipped(skill_id, file_name, "no_business_logic")
        return False

    log(f"  [FlowRunner] processing {file_name}...")
    _live(active_skill=skill_id, current_model="")
    # M3: emit FILE_START so the dashboard can show progress
    if exec_logger:
        exec_logger.log_file_processing(skill_id, file_name, "java", "refactor")

    dep_context  = _get_dep_context(code, repo_path, cache)
    full_context = f"{flow_context}\n\n{dep_context}" if dep_context else flow_context

    new_code = call_ai(
        code, rules, "refactor", file_name,
        file_path=file_path,
        phase=skill_id,
        dep_context=full_context,
    )
    _live(active_skill="")

    if not new_code or new_code.strip() == code.strip():
        log(f"  [FlowRunner] {file_name} — no change")
        if cache:
            cache.mark_phase_done(file_path, skill_id)
        if exec_logger:
            exec_logger.log_file_skipped(skill_id, file_name, "no_change")
        return False

    write_file(file_path, new_code)

    if not _mvn_compile(repo_path):
        log(f"  [FlowRunner] {file_name} — compile failed, reverting", "WARN")
        run_cmd(f'git checkout -- "{file_path}"', cwd=repo_path)
        if exec_logger:
            exec_logger.log_file_reverted(skill_id, file_name, "compile_failed")
        return False

    log(f"  [FlowRunner] {file_name} — compile OK ✓", "OK")
    if cache:
        cache.mark_phase_done(file_path, skill_id)
    if exec_logger:
        exec_logger.log_file_accepted(skill_id, file_name, "+refactor")
    return True


# ---------------------------------------------------------------------------
# Behavioral validation + repair loop for production code
# ---------------------------------------------------------------------------

def _validate_and_repair(files: list[str], rules: str, skill_id: str,
                          flow_context: str, repo_path: str, cache) -> None:
    """
    Runs mvn test. If it fails, attempts to repair the files that changed.
    If repair fails, reverts the individual file.
    """
    ok, output = maven_test(repo_path)
    if ok:
        log("  [FlowRunner] mvn test — OK ✓", "OK")
        return

    log("  [FlowRunner] mvn test failed — starting production repair", "WARN")

    from java.refactor import _categorize_build_error
    error_reason = _categorize_build_error(output)

    for file_path in files:
        if not os.path.exists(file_path):
            continue

        current_code  = read_file(file_path)
        original_code = _git_original(file_path, repo_path)

        if not original_code or current_code.strip() == original_code.strip():
            continue  # not changed — not the culprit

        file_name = os.path.basename(file_path)
        repaired  = False

        for attempt in range(1, _MAX_REPAIR + 1):
            log(f"  [FlowRunner] {file_name} repair {attempt}/{_MAX_REPAIR}...")
            _live(active_skill=f"{skill_id}-repair", current_model="")

            fixed = call_ai_with_correction(
                original=original_code,
                rules=rules,
                mode="refactor",
                file_name=file_name,
                file_path=file_path,
                bad_output=current_code,
                error_reason=error_reason,
                phase=skill_id,
                dep_context=flow_context,
            )
            _live(active_skill="")

            if not fixed:
                continue

            write_file(file_path, fixed)
            ok2, output2 = maven_test(repo_path)
            if ok2:
                log(f"  [FlowRunner] {file_name} repair OK ✓", "OK")
                repaired = True
                break

            current_code = fixed
            error_reason = _categorize_build_error(output2)

        if not repaired:
            log(f"  [FlowRunner] {file_name} — repair failed, reverting", "WARN")
            run_cmd(f'git checkout -- "{file_path}"', cwd=repo_path)
            if cache:
                cache._phase_done.get(file_path, set()).discard(skill_id)


# ---------------------------------------------------------------------------
# Flow context builders
# ---------------------------------------------------------------------------

def _build_flow_context(flow: dict, file_sharing: dict,
                         repo_path: str) -> str:
    """Context for a file that belongs exclusively to a single flow."""
    from java.dep_context import _extract_simplified_header

    lines = [
        "=== ENDPOINT FLOW CONTEXT ===",
        f"Endpoint: {flow['endpoint']}",
        f"Controller: {flow['controller_class']}.{flow['controller_method']}()",
    ]

    for sc in flow.get("service_info", []):
        lines.append(f"  -> {sc['field_type']}.{sc['method']}()")

    lines += ["", "=== FILES IN THIS FLOW ==="]
    for f in flow["files"]:
        tag = " [SHARED — used by multiple endpoints]" if f in file_sharing else ""
        lines.append(f"  {os.path.basename(f)}{tag}")

    lines += ["", "=== FLOW SIGNATURES ==="]
    for f in flow["files"]:
        code = read_file(f)
        if code:
            lines.append(_extract_simplified_header(code, os.path.basename(f)))

    return "\n".join(lines)


def _build_multi_flow_context(file_path: str, flows: list[dict],
                               repo_path: str) -> str:
    """Context for a shared file — lists ALL flows that use it."""
    from java.dep_context import _extract_simplified_header

    lines = [
        "=== SHARED FILE — MULTI-FLOW CONTEXT ===",
        f"This file serves {len(flows)} endpoint flows simultaneously:",
    ]
    for flow in flows:
        lines.append(
            f"  - {flow['endpoint']}  "
            f"(via {flow['controller_class']}.{flow['controller_method']}())"
        )

    lines += [
        "",
        "CRITICAL: Your refactoring MUST preserve the contract for ALL flows above.",
        "Be conservative — only change what is unambiguously safe across all callers.",
        "",
        "=== ALL FLOW SIGNATURES ===",
    ]

    seen: set[str] = set()
    for flow in flows:
        for f in flow["files"]:
            if f in seen:
                continue
            seen.add(f)
            code = read_file(f)
            if code:
                lines.append(_extract_simplified_header(code, os.path.basename(f)))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DRY candidate detection
# ---------------------------------------------------------------------------

def _find_dry_candidates(java_files: list[str]) -> list[dict]:
    """
    Identifies methods with the same name across 2+ files — DRY candidates.
    Filters out trivial names and caps at 5 groups to avoid excessive LLM calls.
    """
    _TRIVIAL = {
        "get", "set", "toString", "equals", "hashCode", "main",
        "of", "from", "build", "create", "init", "setup",
    }

    method_files: dict[str, list[str]] = {}

    for file_path in java_files:
        code = read_file(file_path)
        if not code:
            continue
        methods = re.findall(
            r'(?:public|private|protected)\s+\w[\w<>\[\]]*\s+(\w+)\s*\([^)]{0,120}\)\s*\{',
            code,
        )
        for name in set(methods):
            if name not in _TRIVIAL and len(name) > 3:
                method_files.setdefault(name, []).append(file_path)

    candidates = []
    seen_groups: set[frozenset] = set()

    for method, files in method_files.items():
        if len(files) < 2:
            continue
        key = frozenset(files)
        if key in seen_groups:
            continue
        seen_groups.add(key)
        candidates.append({"method": method, "files": list(files)})

    # Prioritize groups with most files
    candidates.sort(key=lambda c: len(c["files"]), reverse=True)
    return candidates[:5]


def _apply_dry_result(result: str, original_files: list[str],
                       repo_path: str) -> bool:
    """
    Parses the LLM multi-file response and applies the changes.
    Expected format: // FILE: FileName.java\n```java\n...\n```
    """
    pattern = re.compile(
        r'//\s*FILE:\s*(\S+\.java)\s*\n```java\s*\n(.*?)```',
        re.DOTALL,
    )
    changed = False

    for m in pattern.finditer(result):
        target_name = m.group(1).strip()
        new_code    = m.group(2).strip()

        # Find matching existing file
        matching = [f for f in original_files
                    if os.path.basename(f) == target_name]

        if matching:
            file_path = matching[0]
            if new_code != read_file(file_path).strip():
                write_file(file_path, new_code + "\n")
                changed = True
        else:
            # New utility class — place next to the first original file
            dir_path  = os.path.dirname(original_files[0])
            new_path  = os.path.join(dir_path, target_name)
            write_file(new_path, new_code + "\n")
            changed = True

    return changed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git_original(file_path: str, repo_path: str) -> str | None:
    """Returns the file content as it exists in git HEAD."""
    rel  = os.path.relpath(file_path, repo_path)
    code, out, _ = run_cmd(f'git show HEAD:"{rel}"', cwd=repo_path)
    return out if code == 0 and out else None


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


def _get_dep_context(code: str, repo_path: str, cache) -> str:
    try:
        from java.dep_context import get_dependency_context
        return get_dependency_context(code, repo_path, cache)
    except Exception:
        return ""


def _mvn_compile(repo_path: str) -> bool:
    cmd  = ENV_WRAPPER.format("mvn compile -q")
    code, _, _ = run_cmd(cmd, cwd=repo_path)
    return code == 0


def _get_diff(repo_path: str) -> str:
    code, out, _ = run_cmd("git diff --unified=5", cwd=repo_path)
    return out if code == 0 else ""
