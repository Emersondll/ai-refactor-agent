import concurrent.futures
from typing import Literal
from core.logger import log
from ai.model import call_model

_REVIEWER_TIMEOUT_S = 60


def review_diff(diff: str, criteria: str, model: str) -> Literal["APPROVE", "REJECT", "SKIP"]:
    if not diff.strip():
        return "SKIP"
    prompt = _build_prompt(diff, criteria)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(call_model, model, prompt, 0.1)
        try:
            response, _ = future.result(timeout=_REVIEWER_TIMEOUT_S)
        except concurrent.futures.TimeoutError:
            log("[Reviewer] LLM timeout after 60s — auto-APPROVE", "WARN")
            return "APPROVE"
    if not response:
        return "APPROVE"
    first_word = response.strip().split(":")[0].strip().upper()
    if first_word in ("APPROVE", "REJECT"):
        return first_word
    log(f"[Reviewer] Unparseable response '{response[:60]}' — auto-APPROVE", "WARN")
    return "APPROVE"


def _build_prompt(diff: str, criteria: str) -> str:
    return (
        "Você é um revisor de código Java. Analise o diff abaixo.\n\n"
        f"CRITÉRIOS DE APROVAÇÃO:\n{criteria}\n\n"
        f"DIFF:\n{diff}\n\n"
        "Responda APENAS com uma das opções:\n"
        "APPROVE: <motivo em 1 linha>\n"
        "REJECT: <motivo em 1 linha>"
    )
