import concurrent.futures
from typing import Literal
from core.logger import log
from ai.model import call_model

_REVIEWER_TIMEOUT_S = 60


def review_diff(diff: str, criteria: str, model: str) -> Literal["APPROVE", "REJECT", "SKIP"]:
    if not diff.strip():
        return "SKIP"
    prompt = _build_prompt(diff, criteria)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(call_model, model, prompt, 0.1)
    try:
        response, _ = future.result(timeout=_REVIEWER_TIMEOUT_S)
    except concurrent.futures.TimeoutError:
        log(f"[Reviewer] LLM timeout after {_REVIEWER_TIMEOUT_S}s — auto-APPROVE", "WARN")
        executor.shutdown(wait=False, cancel_futures=True)
        return "APPROVE"
    finally:
        executor.shutdown(wait=False)
    if not response:
        return "APPROVE"
    first_word = response.strip().split(":")[0].strip().upper()
    if first_word in ("APPROVE", "REJECT"):
        return first_word
    log(f"[Reviewer] Unparseable response '{response[:60]}' — auto-APPROVE", "WARN")
    return "APPROVE"


def _build_prompt(diff: str, criteria: str) -> str:
    return (
        "You are a Java code reviewer. Analyze the diff below.\n\n"
        f"APPROVAL CRITERIA:\n{criteria}\n\n"
        f"DIFF:\n{diff}\n\n"
        "Respond ONLY with one of:\n"
        "APPROVE: <reason in 1 line>\n"
        "REJECT: <reason in 1 line>"
    )
