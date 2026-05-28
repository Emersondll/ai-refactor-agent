import json
import os
import re
import anthropic
import requests

from config import CLAUDE_API_KEY, CLAUDE_MODEL, USE_LOCAL_PLANNER, OLLAMA_BASE_URL, MODEL_SOLID, MODEL_PLANNER
from agent.skill_catalog import catalog_for_prompt
from core.utils import read_file
from core.logger import log

_PLANNER_SYSTEM = """\
You are a Java refactoring agent planner. You do NOT write Java code.
Your job is to decide WHAT to refactor and in WHAT ORDER.

Rules:
- Prioritize files with build_failures == 0 over files with failures
- Apply javadoc/nomenclature before solid/architecture before community skills
- Include "done" as the last action only when no file has meaningful pending skills
- "fix-build" is only valid when build field is "red"
- Maximum 10 actions per plan
- Each (skill, file) pair must appear only once in the plan
- Return valid JSON only — no markdown, no explanation outside the JSON object

Response format (strict JSON):
{"reasoning": "...", "plan": [{"skill": "...", "file": "filename.java or null", "reason": "..."}, ...]}
"""

_LOCAL_PLANNER_PROMPT_TEMPLATE = """\
You are a Java refactoring planner. Respond with ONLY a JSON object, no other text.

## Project State
{obs_json}

## Available Skills
{catalog}

## Rules
- Prioritize files with build_failures == 0
- Apply javadoc/nomenclature before solid/architecture before community skills
- "fix-build" only when build is "red"
- Maximum 10 actions per plan
- Return "done" when no meaningful improvements remain

## Required JSON format (respond with ONLY this, no markdown, no explanation):
{{"reasoning": "one sentence why", "plan": [{{"skill": "skill-id", "file": "FileName.java", "reason": "why"}}]}}
"""


def call_planner(observation: dict) -> list[dict]:
    if USE_LOCAL_PLANNER:
        return _call_local_planner(observation)
    return _call_claude_planner(observation)


def _call_claude_planner(observation: dict) -> list[dict]:
    if not CLAUDE_API_KEY:
        log("[Planner] ANTHROPIC_API_KEY not set — falling back to local planner", "WARN")
        return _call_local_planner(observation)

    soul = _load_soul()
    catalog = catalog_for_prompt()
    obs_json = json.dumps(observation, indent=2, ensure_ascii=False)

    prompt = (
        f"{soul}\n\n"
        "## Current Project State\n"
        f"{obs_json}\n\n"
        "## Available Skills\n"
        f"{catalog}\n\n"
        "Decide the next batch of refactoring actions. Return JSON only."
    )

    try:
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=_PLANNER_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        plan = _parse_json_plan(raw)
        if plan is not None:
            return plan
        log("[Planner] Claude JSON parse error — falling back to local planner", "WARN")
        return _call_local_planner(observation)

    except Exception as e:
        log(f"[Planner] Claude error: {e} — falling back to local planner", "WARN")
        return _call_local_planner(observation)


def _compact_observation(observation: dict) -> dict:
    """Reduces observation size to fit the local model context window."""
    files = observation.get("files", [])
    # Sort: pending first, then by name; limit to 8 files per cycle
    pending = [f for f in files if f.get("phases_pending")]
    pending.sort(key=lambda f: (f.get("build_failures", 0), f["name"]))
    top_files = pending[:8]
    compact_files = [
        {
            "name": f["name"],
            "lines": f["lines"],
            "pending": len(f.get("phases_pending", [])),
            "pending_skills": f.get("phases_pending", [])[:6],
            "build_failures": f.get("build_failures", 0),
        }
        for f in top_files
    ]
    return {
        "project":          observation.get("project", ""),
        "build":            observation.get("build", "green"),
        "cycle":            observation.get("cycle", 1),
        "max_cycles":       observation.get("max_cycles", 20),
        "files":            compact_files,
        "failed_files":     observation.get("failed_files", []),
        "last_build_error": observation.get("last_build_error"),
    }


def _call_local_planner(observation: dict) -> list[dict]:
    catalog = catalog_for_prompt()
    obs_json = json.dumps(_compact_observation(observation), indent=2, ensure_ascii=False)
    prompt = _LOCAL_PLANNER_PROMPT_TEMPLATE.format(obs_json=obs_json, catalog=catalog)

    log(f"[Planner/Local] Chamando {MODEL_PLANNER}...", "INFO")
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": MODEL_PLANNER, "prompt": prompt, "stream": False,
                  "options": {"temperature": 0.2, "num_predict": 1024}},
            timeout=120,
        )
        if response.status_code != 200:
            log(f"[Planner/Local] Ollama retornou {response.status_code}", "ERR")
            return [{"skill": "done", "file": None, "reason": "local planner unavailable"}]

        raw = response.json().get("response", "")
        plan = _parse_json_plan(raw)
        if plan is not None:
            return plan

        log("[Planner/Local] Could not extract valid JSON from response", "ERR")
        return [{"skill": "done", "file": None, "reason": "local planner JSON parse error"}]

    except Exception as e:
        log(f"[Planner/Local] Erro: {e}", "ERR")
        return [{"skill": "done", "file": None, "reason": f"local planner error: {e}"}]


def _parse_json_plan(raw: str) -> list[dict] | None:
    raw = raw.strip()

    # Remove markdown fences
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    # Try direct parse
    try:
        data = json.loads(raw)
        plan = data.get("plan", [])
        reasoning = data.get("reasoning", "")
        log(f"[Planner] {reasoning[:150]}")
        return plan
    except json.JSONDecodeError:
        pass

    # Try extracting JSON object from surrounding text
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            plan = data.get("plan", [])
            reasoning = data.get("reasoning", "")
            log(f"[Planner] {reasoning[:150]}")
            return plan
        except json.JSONDecodeError:
            pass

    return None


def _load_soul() -> str:
    soul_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "soul.md"
    )
    try:
        return read_file(soul_path)
    except Exception:
        return ""
