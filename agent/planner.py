import json
import os
import anthropic

from config import CLAUDE_API_KEY, CLAUDE_MODEL
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


def call_planner(observation: dict) -> list[dict]:
    if not CLAUDE_API_KEY:
        log("[Planner] ANTHROPIC_API_KEY not set — returning done", "ERR")
        return [{"skill": "done", "file": None, "reason": "no API key configured"}]

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

        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        data = json.loads(raw)
        plan = data.get("plan", [])
        reasoning = data.get("reasoning", "")
        log(f"[Planner] {reasoning[:150]}")
        return plan

    except json.JSONDecodeError as e:
        log(f"[Planner] JSON parse error: {e}", "ERR")
        return [{"skill": "done", "file": None, "reason": "planner JSON parse error"}]
    except Exception as e:
        log(f"[Planner] Error: {e}", "ERR")
        return [{"skill": "done", "file": None, "reason": f"planner error: {e}"}]


def _load_soul() -> str:
    soul_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "soul.md"
    )
    try:
        return read_file(soul_path)
    except Exception:
        return ""
