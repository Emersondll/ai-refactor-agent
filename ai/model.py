"""
model.py — Location: ai/model.py

Provides call_model (Ollama), call_ai (with routing + retry),
and call_ai_with_correction (targeted repair prompt on rejected code).
"""

import requests
import json
import time
import anthropic

from config import (
    TIMEOUT, TIMEOUT_TEST, MAX_RETRIES, OLLAMA_SEED,
    MODEL_DOC, MODEL_STRUCT, MODEL_CLEAN, MODEL_SOLID, MODEL_RECOVERY,
    CLAUDE_MODEL, CLAUDE_API_KEY, USE_CLAUDE_FALLBACK,
)
from ai.prompt import build_prompt
from ai.sanitizer import clean_output
from ai.agent_router import analyze_file, select_agent_priority, should_use_claude
from core.logger import log
from core.live_state import update as _live

_OOM_MODELS: set[str] = set()
_OOM_SIGNALS = ("model requires more system", "not enough memory", "out of memory", "insufficient memory", "500")
MAX_CORRECTIONS = 1
_last_successful_model: str = ""  # updated on every successful call_ai

# N9: per-file consecutive timeout counter. Each call_model timeout increments it;
# success resets it. _try_local_agent aborts early when _TIMEOUT_ABORT_THRESHOLD
# is reached to avoid useless timeout cascades.
# generate_tests must call reset_consecutive_timeouts() at the start of each file.
_consecutive_timeouts: int = 0
_TIMEOUT_ABORT_THRESHOLD: int = 2


def get_consecutive_timeouts() -> int:
    return _consecutive_timeouts


def reset_consecutive_timeouts() -> None:
    global _consecutive_timeouts
    _consecutive_timeouts = 0


def _set_consecutive_timeouts_for_test(value: int) -> None:
    """For tests only — do NOT use in production."""
    global _consecutive_timeouts
    _consecutive_timeouts = value


def get_last_model() -> str:
    return _last_successful_model

_OLLAMA_HEALTH_URL = "http://localhost:11434/api/version"
_OLLAMA_RECOVER_WAIT_S = 30
_OLLAMA_RECOVER_RETRIES = 3


def wait_for_ollama_recovery() -> bool:
    """Waits for Ollama to recover RAM after OOM. Returns True if recovered."""
    for attempt in range(1, _OLLAMA_RECOVER_RETRIES + 1):
        try:
            r = requests.get(_OLLAMA_HEALTH_URL, timeout=5)
            if r.status_code == 200:
                # Test whether at least one model responds to a minimal prompt
                test_model = next(
                    (m for m in [MODEL_SOLID, MODEL_CLEAN, MODEL_STRUCT, MODEL_DOC]
                     if m and m not in _OOM_MODELS),
                    None,
                )
                if not test_model:
                    return False
                payload = {"model": test_model, "prompt": "ok", "stream": False,
                           "options": {"num_predict": 1}}
                pr = requests.post("http://localhost:11434/api/generate", json=payload, timeout=30)
                if pr.status_code == 200:
                    log(f"  [Ollama] service recovered after {(attempt-1)*_OLLAMA_RECOVER_WAIT_S}s", "OK")
                    return True
                if _is_oom_error(pr.text):
                    log(f"  [Ollama] still OOM, waiting {_OLLAMA_RECOVER_WAIT_S}s (attempt {attempt}/{_OLLAMA_RECOVER_RETRIES})...", "WARN")
                    time.sleep(_OLLAMA_RECOVER_WAIT_S)
                    continue
        except Exception:
            pass
        log(f"  [Ollama] unavailable, waiting {_OLLAMA_RECOVER_WAIT_S}s (attempt {attempt}/{_OLLAMA_RECOVER_RETRIES})...", "WARN")
        time.sleep(_OLLAMA_RECOVER_WAIT_S)
    log("  [Ollama] did not recover after all attempts — skipping file", "ERR")
    return False

PHASES_REQUIRING_POLISH: frozenset[str] = frozenset({
    "07_solid", "08_architecture", "09_patterns"
})

_AGENT_ORDER = ["light", "standard", "advanced", "ultimate"]

def _is_oom_error(text: str) -> bool:
    return any(sig in text.lower() for sig in _OOM_SIGNALS)

def call_model(model: str, prompt: str, temperature: float = 0.7,
               timeout: int | None = None,
               num_predict: int = 4096) -> tuple[str | None, bool]:
    """Calls Ollama via HTTP API for better control and performance."""
    global _consecutive_timeouts  # N9: declared once at function top per Python rules
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
            "top_p": 0.9,
            "seed": OLLAMA_SEED,
        }
    }
    _timeout = timeout if timeout is not None else TIMEOUT
    try:
        response = requests.post(url, json=payload, timeout=_timeout)
        if response.status_code != 200:
            err_msg = response.text
            if _is_oom_error(err_msg):
                return None, True
            return None, False

        data = response.json()
        # N9: reset counter on any successful (non-timeout) response
        _consecutive_timeouts = 0
        return data.get("response"), False

    except requests.exceptions.Timeout:
        log(f"[{model}] API timeout after {_timeout}s", "WARN")
        _consecutive_timeouts += 1
        return None, False
    except Exception as e:
        if _is_oom_error(str(e)):
            return None, True
        log(f"[{model}] API error: {e}", "ERR")
        return None, False


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

def _build_correction_prompt(original_prompt: str, bad_output: str,
                              error_reason: str) -> str:
    """Generic correction prompt for invalid output format."""
    return (
        f"{original_prompt}\n\n"
        "### PREVIOUS ATTEMPT WAS REJECTED\n"
        f"Reason: {error_reason}\n\n"
        "Your previous output:\n"
        "```java\n"
        f"{bad_output[:2000]}\n"
        "```\n\n"
        "Fix ONLY the issue described above and return the complete corrected file."
    )


def _build_validator_correction_prompt(original_prompt: str, bad_output: str,
                                        validator_error: str,
                                        original_code: str = "",
                                        expected_class: str = "") -> str:
    """Correction prompt for Java validator errors.

    Injects package and class name — uses expected_class (destination file name) when
    available to avoid extracting the production class name (wrong in test mode).
    """
    import re as _re
    mandatory_lines = []
    if original_code:
        pkg_m = _re.search(r'^(package\s+[\w.]+;)', original_code, _re.MULTILINE)
        if pkg_m:
            mandatory_lines.append(f"- Package MUST be exactly: {pkg_m.group(1)}")
    # B: use expected_class when available — avoids using the production class name
    # as a constraint when the destination is a test file with a different name.
    if expected_class:
        mandatory_lines.append(f"- Class/record name MUST be exactly: {expected_class}")
    elif original_code:
        cls_m = _re.search(
            r'(?:public\s+)?(?:class|interface|record|enum)\s+(\w+)',
            original_code
        )
        if cls_m:
            mandatory_lines.append(f"- Class/record name MUST be exactly: {cls_m.group(1)}")

    mandatory_block = ""
    if mandatory_lines:
        mandatory_block = (
            "\n### MANDATORY CONSTRAINTS (non-negotiable)\n"
            + "\n".join(mandatory_lines)
            + "\n- Do NOT use com.example.*, com.test.*, or any invented package.\n"
        )

    return (
        f"{original_prompt}{mandatory_block}\n\n"
        "### YOUR PREVIOUS OUTPUT HAS A JAVA SYNTAX ERROR\n"
        f"Validator error: {validator_error}\n\n"
        "Your previous output (with the error):\n"
        "```java\n"
        f"{bad_output[:3000]}\n"
        "```\n\n"
        "Fix the Java syntax error described above.\n"
        "Common causes: missing closing brace `}`, unclosed string, "
        "broken import statement, incomplete method body.\n"
        "Return ONLY the complete corrected Java file in ```java format."
    )


# ---------------------------------------------------------------------------
# Claude API
# ---------------------------------------------------------------------------

def call_claude(prompt: str) -> str | None:
    if not CLAUDE_API_KEY:
        log("ANTHROPIC_API_KEY not found in .env", "ERR")
        return None
    try:
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8096,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except anthropic.AuthenticationError:
        log("ANTHROPIC_API_KEY invalid or expired", "ERR")
    except anthropic.RateLimitError:
        log("Anthropic API rate limit reached", "WARN")
    except anthropic.APIConnectionError:
        log("No connection to Anthropic API", "ERR")
    except Exception as e:
        log(f"[claude-api] unexpected error: {e}", "ERR")
    return None


# ---------------------------------------------------------------------------
# Agentes locais
# ---------------------------------------------------------------------------

def _try_local_agent(agent: str, model_name: str, prompt: str, temperature: float = 0.7,
                     timeout: int | None = None,
                     num_predict: int = 4096) -> str | None:
    """Tries a local model with MAX_RETRIES + self-correction."""
    last_output = None
    last_error  = None

    for attempt in range(1, MAX_RETRIES + 1):
        # N9: abort cascade if threshold consecutive timeouts on same file
        if _consecutive_timeouts >= _TIMEOUT_ABORT_THRESHOLD:
            log(
                f"  [{model_name}] aborting: {_consecutive_timeouts} consecutive "
                f"timeouts on file — saving wall-clock", "WARN",
            )
            return None
        current_prompt = prompt
        if attempt > 1 and last_output and last_error:
            log(f"  [{model_name}] self-correction: {last_error[:60]}")
            current_prompt = _build_correction_prompt(prompt, last_output, last_error)

        log(f"  [{model_name}] attempt {attempt}/{MAX_RETRIES} (temp={temperature})")
        _live(current_model=model_name, active_skill="")
        raw, is_oom = call_model(model_name, current_prompt, temperature=temperature,
                                 timeout=timeout, num_predict=num_predict)

        if is_oom:
            _OOM_MODELS.add(model_name)
            log(f"  [{model_name}] marked unavailable due to OOM", "WARN")
            return None

        result = clean_output(raw)
        if result:
            log(f"  [{model_name}] valid response obtained", "OK")
            return result

        log(f"  [{model_name}] failed", "WARN")
        last_output = raw or ""
        last_error  = "Output did not contain a valid Java code block"

    # Extra correction pass
    if last_output and MAX_CORRECTIONS > 0:
        for correction in range(1, MAX_CORRECTIONS + 1):
            log(f"  [{model_name}] extra correction {correction}/{MAX_CORRECTIONS}")
            cp = _build_correction_prompt(prompt, last_output,
                                          last_error or "invalid output format")
            raw, is_oom = call_model(model_name, cp, timeout=timeout, num_predict=num_predict)
            if is_oom:
                _OOM_MODELS.add(model_name)
                return None
            result = clean_output(raw)
            if result:
                log(f"  [{model_name}] self-correction succeeded", "OK")
                return result

    return None


def _try_claude(prompt: str) -> str | None:
    if not CLAUDE_API_KEY:
        return None
    _live(current_model="claude-api", active_skill="")
    log("  [claude-api] activated")
    raw    = call_claude(prompt)
    result = clean_output(raw)
    if result:
        log("  [claude-api] valid response obtained", "OK")
        return result
    if raw and MAX_CORRECTIONS > 0:
        log("  [claude-api] self-correction")
        cp     = _build_correction_prompt(prompt, raw,
                                          "Output did not contain a valid Java code block")
        raw2   = call_claude(cp)
        result = clean_output(raw2)
        if result:
            log("  [claude-api] self-correction succeeded", "OK")
            return result
    log("  [claude-api] failed", "ERR")
    return None


# ---------------------------------------------------------------------------
# Orquestrador principal
# ---------------------------------------------------------------------------

def _run_pipeline(prompt: str, code: str, file_path: str,
                  file_name: str, mode: str, phase: str = "",
                  max_agent: str | None = None) -> str | None:
    """Full agent pipeline with Critical Review Skill."""
    global _last_successful_model
    file_type, complexity = analyze_file(code, file_path or file_name)

    # Dynamic temperature: SOLID/Architecture = more creative (0.7), Javadoc/Final = deterministic (0.1)
    is_creative = any(x in phase.lower() for x in ("solid", "architecture", "patterns", "clean_code"))
    temp = 0.7 if is_creative else 0.1

    agent_priority = select_agent_priority(file_type, complexity, mode, phase)

    if max_agent and max_agent in _AGENT_ORDER:
        cap_idx = _AGENT_ORDER.index(max_agent)
        agent_priority = [
            a for a in agent_priority
            if a == "claude" or (a in _AGENT_ORDER and _AGENT_ORDER.index(a) <= cap_idx)
        ]
        log(f"  [Pipeline] max_agent={max_agent} — agents capped: {agent_priority}")

    agent_map = {
        "light":    MODEL_DOC,
        "standard": MODEL_STRUCT,
        "advanced": MODEL_CLEAN,
        "ultimate": MODEL_SOLID,
    }

    local_agents = [a for a in agent_priority if a != "claude"]
    attempts_failed = 0
    call_timeout    = TIMEOUT_TEST if mode == "test" else None
    call_num_predict = 8192 if mode == "test" else 4096

    for agent in agent_priority:
        if agent == "claude":
            # USE_CLAUDE_FALLBACK=false is a hard block — never call Claude regardless of local failures
            if USE_CLAUDE_FALLBACK and should_use_claude(file_type, complexity, mode, attempts_failed):
                result = _try_claude(prompt)
                if result: return result
            continue

        model_name = agent_map.get(agent)
        if not model_name or model_name in _OOM_MODELS:
            attempts_failed += 1
            continue

        result = _try_local_agent(agent, model_name, prompt, temperature=temp,
                                  timeout=call_timeout, num_predict=call_num_predict)
        if result:
            _last_successful_model = model_name
            # Critical polish: only in structural phases (SOLID/Architecture/Patterns)
            phase_name = phase.split("/")[-1].replace(".md", "") if phase else ""
            needs_polish = (
                agent != "ultimate"
                and phase_name in PHASES_REQUIRING_POLISH
                and MODEL_SOLID
                and MODEL_SOLID not in _OOM_MODELS
            )
            if needs_polish:
                log(f"  [Critic] Reviewing with {MODEL_SOLID} (structural phase: {phase_name})...")
                result = _polish_result(result, prompt, MODEL_SOLID)

            if result.strip() == code.strip() and agent in ("ultimate", "advanced", "standard"):
                log(f"  [{agent}] indicated no changes are necessary.")
                return result
            return result

        attempts_failed += 1

    if USE_CLAUDE_FALLBACK and "claude" not in agent_priority:
        log("  [Fallback] All local agents failed, activating Claude...", "WARN")
        result = _try_claude(prompt)
        if result:
            _last_successful_model = "claude-api"
            return result

    return None


def _polish_result(draft: str, original_prompt: str, critic_model: str) -> str:
    """Polish Skill: uses the strongest model to review and refine generated code."""
    polish_prompt = (
        f"{original_prompt}\n\n"
        "### DRAFT FOR REVIEW\n"
        "The following code was generated by a junior assistant. "
        "Review it meticulously for:\n"
        "1. Java Best Practices & Clean Code\n"
        "2. Missing 'final' keywords in parameters or variables\n"
        "3. Syntax errors (missing semicolons, unbalanced braces)\n"
        "4. SOLID principles\n\n"
        "Draft Code:\n"
        "```java\n"
        f"{draft}\n"
        "```\n\n"
        "Return ONLY the complete, polished and corrected Java file in ```java format."
    )
    
    refined, _ = call_model(critic_model, polish_prompt, temperature=0.1)  # Low temp for corrections
    clean_refined = clean_output(refined)

    if clean_refined:
        log(f"  [{critic_model}] Review completed and applied.", "OK")
        return clean_refined

    return draft  # If review failed, keep the original


def call_ai(code: str, rules: str, mode: str, file_name: str,
            file_path: str = "", phase: str = "",
            dep_context: str = "",
            max_agent: str | None = None) -> str | None:
    """Main entry point — generates code from phase rules."""
    from ai.compressor import maybe_compress
    compressed_dep = maybe_compress(dep_context) if dep_context else dep_context
    prompt = build_prompt(code, rules, mode, file_name, dep_context=compressed_dep)
    return _run_pipeline(prompt, code, file_path, file_name, mode, phase, max_agent=max_agent)


def call_ai_with_correction(original: str, rules: str, mode: str,
                             file_name: str, file_path: str,
                             bad_output: str, error_reason: str,
                             phase: str = "",
                             dep_context: str = "") -> str | None:
    """Entry point for correction after validator rejection."""
    base_prompt = build_prompt(original, rules, mode, file_name, dep_context=dep_context)
    # B: passes file_name as expected_class so the mandatory block uses the destination
    # file name (e.g. MerchantCategoryCodesServiceImplTest), not the production class name.
    correction_prompt = _build_validator_correction_prompt(
        base_prompt, bad_output, error_reason,
        original_code=original, expected_class=file_name.replace(".java", ""),
    )
    call_num_predict = 8192 if mode == "test" else 4096

    if USE_CLAUDE_FALLBACK:
        log("  [Self-heal] Activating Claude for advanced correction...", "INFO")
        result = _try_claude(correction_prompt)
        if result:
            return result
        log("  [Self-heal] Claude unavailable or failed.", "WARN")

    log(f"  [Self-heal] Activating Local Doctor (Second Opinion) with {MODEL_RECOVERY}...", "WARN")
    call_timeout = TIMEOUT_TEST if mode == "test" else TIMEOUT
    recovery_result = _try_local_agent("recovery", MODEL_RECOVERY, correction_prompt,
                                       temperature=0.1, timeout=call_timeout,
                                       num_predict=call_num_predict)

    if recovery_result:
        return recovery_result

    # N3: escalate to MODEL_STRUCT (smaller, faster) when MODEL_RECOVERY exhausts.
    # Skip if both env vars point to the same model — no point retrying identical.
    if MODEL_STRUCT and MODEL_STRUCT != MODEL_RECOVERY:
        log(f"  [Self-heal] Escalating to smaller model ({MODEL_STRUCT}) after {MODEL_RECOVERY} failed...", "WARN")
        struct_result = _try_local_agent("recovery-fallback", MODEL_STRUCT, correction_prompt,
                                          temperature=0.1, timeout=call_timeout,
                                          num_predict=call_num_predict)
        if struct_result:
            log(f"  [Self-heal] {MODEL_STRUCT} (fallback) produced valid correction.", "OK")
            return struct_result

    log("  [Self-heal] Local Doctor also failed.", "ERR")
    return None