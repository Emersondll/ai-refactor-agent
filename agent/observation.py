import os
from java.refactor import get_java_files, get_failed_tracker
from agent.skill_catalog import all_phase_skill_ids, _PHASE_SKILLS, _REACTIVE_SKILLS


def build_observation(repo_path: str, cache, cycle: int, max_cycles: int,
                      build_ok: bool = True,
                      last_build_error: str | None = None) -> dict:
    java_files = get_java_files(repo_path)
    failed_tracker = get_failed_tracker()
    all_entries = failed_tracker._entries
    failed_paths: set[str] = {e["file"] for e in all_entries}
    all_skills = all_phase_skill_ids()

    files_data = []
    for f in java_files:
        phases_applied = [s for s in all_skills if cache.is_phase_done(f, s)]
        phases_pending  = [s for s in all_skills if s not in phases_applied]
        build_failures  = failed_tracker.get_build_failure_count(f)

        last_result = "pending"
        file_entries = [e for e in all_entries if e["file"] == f]
        if file_entries:
            last_reason = file_entries[-1].get("reason", "")
            last_result = "build_failed" if "build quebrou" in last_reason else "rejected"

        try:
            with open(f, encoding="utf-8") as fh:
                lines = sum(1 for _ in fh)
        except Exception:
            lines = 0

        files_data.append({
            "name": os.path.basename(f),
            "path": f,
            "lines": lines,
            "phases_applied": phases_applied,
            "phases_pending": phases_pending,
            "build_failures": build_failures,
            "last_result": last_result,
        })

    available_skills = (
        list(_PHASE_SKILLS.keys())
        + [s for s in _REACTIVE_SKILLS if s != "analyze-state"]
        + ["done"]
    )

    return {
        "project": os.path.basename(repo_path),
        "build": "green" if build_ok else "red",
        "cycle": cycle,
        "max_cycles": max_cycles,
        "files": files_data,
        "failed_files": [os.path.basename(p) for p in failed_paths],
        "last_build_error": last_build_error,
        "skills_available": available_skills,
    }
