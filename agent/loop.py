import os
from core.logger import log
from core.utils import run_cmd
from core.execution_logger import ExecutionLogger
from core.reporter import PhaseReporter
from java.maven_build import maven_test
from java.community_runner import run_skill
from java.diff_reviewer import review_diff
from agent.observation import build_observation
from agent.planner import call_planner
from agent.skill_catalog import load_skill_config, is_reactive, is_terminal
from config import AGENT_MAX_CYCLES, MODEL_REVIEWER as MODEL_SOLID


def _dispatch_skill(skill_config: dict, repo_path: str, cache) -> tuple[bool, str]:
    """Despacha a skill para o runner correto baseado no campo 'tool' do config."""
    tool = skill_config.get("tool", "community")
    if tool == "llm":
        from java.llm_runner import run_skill as _run_llm
        return _run_llm(skill_config, repo_path, cache)
    if tool == "flow":
        from java.flow_runner import run_skill as _run_flow
        return _run_flow(skill_config, repo_path, cache)
    if tool == "flow-dry":
        from java.flow_runner import dry_check as _dry_check
        return _dry_check(skill_config, repo_path)
    return run_skill(skill_config, repo_path)


def run_agent_loop(repo_path: str, reporter: PhaseReporter,
                   exec_logger: ExecutionLogger, cache, semantic_mem) -> None:
    cycle = 0
    consecutive_no_progress = 0
    build_ok = True
    last_build_error: str | None = None

    log("=" * 60, "PHASE")
    log("AGENT MODE — Plan-then-Execute Loop (Community + LLM)", "PHASE")
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

            tool = skill_config.get("tool", "community")
            exec_logger.log_phase_start(skill, f"Agent cycle {cycle} — tool={tool}")

            changed, diff = _dispatch_skill(skill_config, repo_path, cache)
            if not changed:
                log(f"  [Agent] [{skill}] no changes — skipping", "INFO")
                cache.mark_phase_done(skill, skill)
                continue

            verdict = review_diff(diff, skill_config.get("review_criteria", ""), MODEL_SOLID)
            log(f"  [Agent] [{skill}] reviewer: {verdict}")

            if verdict == "REJECT":
                _git_restore(repo_path)
                cache.mark_phase_done(skill, skill)
                log(f"  [Agent] [{skill}] reverted (REJECT)", "WARN")
                exec_logger.log_file_reverted(skill, skill, "REVIEWER_REJECT")
                continue

            actions_accepted += 1
            build_ok, build_output = maven_test(repo_path)
            if not build_ok:
                last_build_error = _extract_errors(build_output)
                log(f"  [Agent] Build broke after [{skill}] — reverting", "WARN")
                _git_restore(repo_path)
                build_broke_this_cycle = True
                exec_logger.log_compilation_failed(skill, skill)
                break
            else:
                last_build_error = None
                cache.mark_phase_done(skill, skill)
                log(f"  [Agent] [{skill}] accepted and committed to build", "OK")
                exec_logger.log_file_accepted(skill, skill, f"+{tool}")

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
