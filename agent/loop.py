import os
from core.logger import log
from core.utils import run_cmd
from core.execution_logger import ExecutionLogger
from core.reporter import PhaseReporter
from java.compiler import maven_test
from java.community_runner import run_skill
from java.llm_reviewer import review_diff
from agent.observation import build_observation
from agent.planner import call_planner
from agent.skill_catalog import load_skill_config, is_reactive, is_terminal
from config import AGENT_MAX_CYCLES, MODEL_SOLID


def run_agent_loop(repo_path: str, reporter: PhaseReporter,
                   exec_logger: ExecutionLogger, cache, semantic_mem) -> None:
    cycle = 0
    consecutive_no_progress = 0
    build_ok = True
    last_build_error: str | None = None

    log("=" * 60, "PHASE")
    log("AGENT MODE — Plan-then-Execute Loop (Community Tools)", "PHASE")
    log(f"Max cycles: {AGENT_MAX_CYCLES}", "PHASE")
    log("=" * 60, "PHASE")

    while cycle < AGENT_MAX_CYCLES:
        log(f"\n[Cycle {cycle + 1}/{AGENT_MAX_CYCLES}] Building observation...", "PHASE")
        observation = build_observation(
            repo_path, cache, cycle + 1, AGENT_MAX_CYCLES,
            build_ok=build_ok, last_build_error=last_build_error,
        )

        log(f"[Cycle {cycle + 1}] Calling planner...", "PHASE")
        plan = call_planner(observation)
        cycle += 1

        if not plan:
            log("[Agent] Empty plan — exiting", "WARN")
            break

        actions_accepted = 0
        build_broke_this_cycle = False

        for action in plan:
            skill  = action.get("skill", "")
            reason = action.get("reason", "")

            log(f"  → [{skill}] : {reason}")

            if is_terminal(skill):
                log("[Agent] Declared done — no more improvements available.", "OK")
                return

            if skill == "skip-file":
                log(f"  [Agent] skip-file: {reason}", "WARN")
                continue

            if skill == "fix-build":
                build_ok, _ = maven_test(repo_path)
                if build_ok:
                    last_build_error = None
                    actions_accepted += 1
                continue

            if skill == "analyze-state":
                continue

            skill_config = load_skill_config(skill)
            if skill_config is None:
                log(f"  [Agent] Unknown or missing skill '{skill}' — skipping", "WARN")
                continue

            changed, diff = run_skill(skill_config, repo_path)
            if not changed:
                log(f"  [Agent] [{skill}] no changes — skipping", "INFO")
                cache.mark_phase_done(skill)
                continue

            verdict = review_diff(diff, skill_config.get("review_criteria", ""), MODEL_SOLID)
            log(f"  [Agent] [{skill}] reviewer: {verdict}")

            if verdict == "REJECT":
                _git_restore(repo_path)
                cache.mark_phase_done(skill)
                log(f"  [Agent] [{skill}] reverted (REJECT)", "WARN")
                continue

            actions_accepted += 1
            build_ok, build_output = maven_test(repo_path)
            if not build_ok:
                last_build_error = _extract_errors(build_output)
                log(f"  [Agent] Build broke after [{skill}] — reverting", "WARN")
                _git_restore(repo_path)
                build_broke_this_cycle = True
                break
            else:
                last_build_error = None
                cache.mark_phase_done(skill)
                log(f"  [Agent] [{skill}] accepted and committed to build", "OK")

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


def _git_restore(repo_path: str) -> None:
    run_cmd("git restore .", cwd=repo_path)


def _extract_errors(build_output: str) -> str:
    lines = [l for l in build_output.splitlines() if "[ERROR]" in l]
    return "\n".join(lines[:10])
