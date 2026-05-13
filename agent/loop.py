import os
from core.logger import log
from core.utils import read_file
from core.execution_logger import ExecutionLogger
from core.reporter import PhaseReporter
from java.refactor import refactor_file, get_failed_tracker
from java.compiler import maven_test
from agent.observation import build_observation
from agent.planner import call_planner
from agent.skill_catalog import resolve_phase_file, is_reactive, is_terminal
from config import AGENT_MAX_CYCLES


def run_agent_loop(repo_path: str, reporter: PhaseReporter,
                   exec_logger: ExecutionLogger, cache, semantic_mem) -> None:
    cycle = 0
    consecutive_no_progress = 0
    build_ok = True
    last_build_error: str | None = None

    log("=" * 60, "PHASE")
    log("AGENT MODE — Plan-then-Execute Loop", "PHASE")
    log(f"Max cycles: {AGENT_MAX_CYCLES}", "PHASE")
    log("=" * 60, "PHASE")

    while cycle < AGENT_MAX_CYCLES:
        log(f"\n[Cycle {cycle + 1}/{AGENT_MAX_CYCLES}] Building observation...", "PHASE")
        observation = build_observation(
            repo_path, cache, cycle + 1, AGENT_MAX_CYCLES,
            build_ok=build_ok, last_build_error=last_build_error,
        )

        log(f"[Cycle {cycle + 1}] Calling planner (Claude)...", "PHASE")
        plan = call_planner(observation)
        cycle += 1

        if not plan:
            log("[Agent] Empty plan — exiting", "WARN")
            break

        actions_accepted = 0
        build_broke_this_cycle = False

        for action in plan:
            skill     = action.get("skill", "")
            file_name = action.get("file")
            reason    = action.get("reason", "")

            log(f"  → [{skill}] {file_name or '—'} : {reason}")

            if is_terminal(skill):
                log("[Agent] Declared done — no more improvements available.", "OK")
                return

            if skill == "skip-file":
                _handle_skip(file_name, repo_path, reason, exec_logger)
                continue

            if skill == "fix-build":
                build_ok, _ = maven_test(repo_path)
                if build_ok:
                    last_build_error = None
                    actions_accepted += 1
                continue

            if skill == "analyze-state":
                continue

            phase_file = resolve_phase_file(skill)
            if not phase_file:
                log(f"  [Agent] Unknown or missing skill '{skill}' — skipping", "WARN")
                continue

            file_path = _find_java_file(file_name, repo_path)
            if not file_path:
                log(f"  [Agent] '{file_name}' not found — skipping", "WARN")
                continue

            rules    = read_file(phase_file)
            accepted = refactor_file(
                file_path, rules, repo_path, phase_file,
                reporter, exec_logger, cache=cache, semantic_mem=semantic_mem,
            )

            if accepted:
                actions_accepted += 1
                build_ok, build_output = maven_test(repo_path)
                if not build_ok:
                    last_build_error = _extract_errors(build_output)
                    log(f"  [Agent] Build broke after [{skill}] {file_name} — replanning", "WARN")
                    build_broke_this_cycle = True
                    break
                else:
                    last_build_error = None

        if build_broke_this_cycle or actions_accepted == 0:
            consecutive_no_progress += 1
        else:
            consecutive_no_progress = 0

        if consecutive_no_progress >= 3:
            log("[Agent] No progress in 3 consecutive cycles — exiting (stuck).", "WARN")
            break

        log(f"[Cycle {cycle}] Complete — {actions_accepted} action(s) accepted.", "OK")

    if cycle >= AGENT_MAX_CYCLES:
        log(f"[Agent] Budget exhausted ({AGENT_MAX_CYCLES} cycles).", "WARN")


def _find_java_file(file_name: str | None, repo_path: str) -> str | None:
    if not file_name:
        return None
    for root, _, files in os.walk(repo_path):
        if "target" in root.replace("\\", "/").split("/"):
            continue
        if file_name in files:
            return os.path.join(root, file_name)
    return None


def _handle_skip(file_name: str | None, repo_path: str, reason: str,
                  exec_logger: ExecutionLogger) -> None:
    file_path = _find_java_file(file_name, repo_path)
    if file_path:
        get_failed_tracker().record(file_path, "agent-skip", f"Agent: {reason}")
    if exec_logger and file_name:
        exec_logger.log_file_skipped("agent", file_name, reason)
    log(f"  [Agent] Skipped '{file_name}': {reason}", "WARN")


def _extract_errors(build_output: str) -> str:
    lines = [l for l in build_output.splitlines() if "[ERROR]" in l]
    return "\n".join(lines[:10])
