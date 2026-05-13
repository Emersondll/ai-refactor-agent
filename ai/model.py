"""
model.py — Localização: ai/model.py

ADICIONADO: call_ai_with_correction()
  Função separada que recebe o código rejeitado + motivo e monta
  um prompt de correção direcionado, enviando para o mesmo pipeline
  de agentes.
"""

import requests
import json
import anthropic

from config import (
    TIMEOUT, MAX_RETRIES,
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

PHASES_REQUIRING_POLISH: frozenset[str] = frozenset({
    "07_solid", "08_architecture", "09_patterns"
})

def _is_oom_error(text: str) -> bool:
    return any(sig in text.lower() for sig in _OOM_SIGNALS)

def call_model(model: str, prompt: str, temperature: float = 0.7) -> tuple[str | None, bool]:
    """
    Chama o Ollama via API HTTP para melhor controle e performance.
    """
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": 4096,
            "top_p": 0.9
        }
    }
    
    try:
        response = requests.post(url, json=payload, timeout=TIMEOUT)
        if response.status_code != 200:
            err_msg = response.text
            if _is_oom_error(err_msg):
                return None, True
            return None, False
            
        data = response.json()
        return data.get("response"), False

    except requests.exceptions.Timeout:
        log(f"[{model}] timeout na API após {TIMEOUT}s", "WARN")
        return None, False
    except Exception as e:
        if _is_oom_error(str(e)):
            return None, True
        log(f"[{model}] erro na API: {e}", "ERR")
        return None, False


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

def _build_correction_prompt(original_prompt: str, bad_output: str,
                              error_reason: str) -> str:
    """Prompt genérico de correção de output inválido (formato)."""
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
                                        validator_error: str) -> str:
    """
    Prompt de correção específico para erros do validator Java.
    Inclui o erro de compilação/sintaxe exato para orientar o modelo.
    """
    return (
        f"{original_prompt}\n\n"
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
        log("ANTHROPIC_API_KEY não encontrada no .env", "ERR")
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
        log("ANTHROPIC_API_KEY inválida ou expirada", "ERR")
    except anthropic.RateLimitError:
        log("Rate limit da API Anthropic atingido", "WARN")
    except anthropic.APIConnectionError:
        log("Sem conexão com a API Anthropic", "ERR")
    except Exception as e:
        log(f"[claude-api] erro inesperado: {e}", "ERR")
    return None


# ---------------------------------------------------------------------------
# Agentes locais
# ---------------------------------------------------------------------------

def _try_local_agent(agent: str, model_name: str, prompt: str, temperature: float = 0.7) -> str | None:
    """Tenta um modelo local com MAX_RETRIES + self-correction."""
    last_output = None
    last_error  = None

    for attempt in range(1, MAX_RETRIES + 1):
        current_prompt = prompt
        if attempt > 1 and last_output and last_error:
            log(f"  [{model_name}] autocorreção: {last_error[:60]}")
            current_prompt = _build_correction_prompt(prompt, last_output, last_error)

        log(f"  [{model_name}] tentativa {attempt}/{MAX_RETRIES} (temp={temperature})")
        _live(current_model=model_name, active_skill="")
        raw, is_oom = call_model(model_name, current_prompt, temperature=temperature)

        if is_oom:
            _OOM_MODELS.add(model_name)
            log(f"  [{model_name}] marcado como indisponível por OOM", "WARN")
            return None

        result = clean_output(raw)
        if result:
            log(f"  [{model_name}] resposta válida obtida", "OK")
            return result

        log(f"  [{model_name}] falhou", "WARN")
        last_output = raw or ""
        last_error  = "Output did not contain a valid Java code block"

    # Correção extra
    if last_output and MAX_CORRECTIONS > 0:
        for correction in range(1, MAX_CORRECTIONS + 1):
            log(f"  [{model_name}] correção extra {correction}/{MAX_CORRECTIONS}")
            cp = _build_correction_prompt(prompt, last_output,
                                          last_error or "invalid output format")
            raw, is_oom = call_model(model_name, cp)
            if is_oom:
                _OOM_MODELS.add(model_name)
                return None
            result = clean_output(raw)
            if result:
                log(f"  [{model_name}] autocorreção bem-sucedida", "OK")
                return result

    return None


def _try_claude(prompt: str) -> str | None:
    if not CLAUDE_API_KEY:
        return None
    _live(current_model="claude-api", active_skill="")
    log("  [claude-api] acionado")
    raw    = call_claude(prompt)
    result = clean_output(raw)
    if result:
        log("  [claude-api] resposta válida obtida", "OK")
        return result
    if raw and MAX_CORRECTIONS > 0:
        log("  [claude-api] autocorreção")
        cp     = _build_correction_prompt(prompt, raw,
                                          "Output did not contain a valid Java code block")
        raw2   = call_claude(cp)
        result = clean_output(raw2)
        if result:
            log("  [claude-api] autocorreção bem-sucedida", "OK")
            return result
    log("  [claude-api] falhou", "ERR")
    return None


# ---------------------------------------------------------------------------
# Orquestrador principal
# ---------------------------------------------------------------------------

def _run_pipeline(prompt: str, code: str, file_path: str,
                  file_name: str, mode: str, phase: str = "") -> str | None:
    """Pipeline completo de agentes com Skill de Revisão Crítica."""
    file_type, complexity = analyze_file(code, file_path or file_name)
    
    # Skill: Temperatura dinâmica
    # SOLID/Arquitetura = more creative (0.7), Javadoc/Final = deterministic (0.1)
    is_creative = any(x in phase.lower() for x in ("solid", "architecture", "patterns", "clean_code"))
    temp = 0.7 if is_creative else 0.1

    agent_priority = select_agent_priority(file_type, complexity, mode, phase)

    agent_map = {
        "light":    MODEL_DOC,
        "standard": MODEL_STRUCT,
        "advanced": MODEL_CLEAN,
        "ultimate": MODEL_SOLID,
    }

    local_agents = [a for a in agent_priority if a != "claude"]
    attempts_failed = 0

    for agent in agent_priority:
        if agent == "claude":
            if attempts_failed >= len(local_agents) or USE_CLAUDE_FALLBACK or \
               should_use_claude(file_type, complexity, mode, attempts_failed):
                result = _try_claude(prompt)
                if result: return result
            continue

        model_name = agent_map.get(agent)
        if not model_name or model_name in _OOM_MODELS:
            attempts_failed += 1
            continue

        result = _try_local_agent(agent, model_name, prompt, temperature=temp)
        if result:
            # Polimento crítico: apenas em fases estruturais (SOLID/Architecture/Patterns)
            phase_name = phase.split("/")[-1].replace(".md", "") if phase else ""
            needs_polish = (
                agent != "ultimate"
                and phase_name in PHASES_REQUIRING_POLISH
                and MODEL_SOLID
                and MODEL_SOLID not in _OOM_MODELS
            )
            if needs_polish:
                log(f"  [Crítico] Revisando com {MODEL_SOLID} (fase estrutural: {phase_name})...")
                result = _polish_result(result, prompt, MODEL_SOLID)
            
            if result.strip() == code.strip() and agent in ("ultimate", "advanced", "standard"):
                log(f"  [{agent}] indicou que nenhuma alteração é necessária.")
                return result
            return result

        attempts_failed += 1

    if USE_CLAUDE_FALLBACK and "claude" not in agent_priority:
        log("  [Fallback] Todos os agentes locais falharam, acionando Claude...", "WARN")
        result = _try_claude(prompt)
        if result: return result

    return None


def _polish_result(draft: str, original_prompt: str, critic_model: str) -> str:
    """
    Skill de Polimento: Usa o modelo mais forte para revisar e refinar o código.
    """
    polish_prompt = (
        f"{original_prompt}\n\n"
        "### DRAFT FOR REVIEW\n"
        "The followign code was generated by a junior assistant. "
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
    
    refined, _ = call_model(critic_model, polish_prompt, temperature=0.1) # Baixa temp para correção
    clean_refined = clean_output(refined)
    
    if clean_refined:
        log(f"  [{critic_model}] Revisão concluída e aplicada.", "OK")
        return clean_refined
    
    return draft # Se falhou a revisão, mantém o original


def call_ai(code: str, rules: str, mode: str, file_name: str,
            file_path: str = "", phase: str = "",
            dep_context: str = "") -> str | None:
    """Entrada principal — gera código a partir das regras da fase."""
    from ai.compressor import maybe_compress
    compressed_dep = maybe_compress(dep_context) if dep_context else dep_context
    prompt = build_prompt(code, rules, mode, file_name, dep_context=compressed_dep)
    return _run_pipeline(prompt, code, file_path, file_name, mode, phase)


def call_ai_with_correction(original: str, rules: str, mode: str,
                             file_name: str, file_path: str,
                             bad_output: str, error_reason: str,
                             phase: str = "") -> str | None:
    """Entrada para correção após rejeição do validator."""
    base_prompt = build_prompt(original, rules, mode, file_name)
    correction_prompt = _build_validator_correction_prompt(
        base_prompt, bad_output, error_reason
    )
    
    log("  [Autocura] Acionando Claude para correção avançada...", "INFO")
    result = _try_claude(correction_prompt)
    if result:
        return result
        
    log(f"  [Autocura] Claude indisponível ou falhou. Acionando Médico Local (Second Opinion) com {MODEL_RECOVERY}...", "WARN")
    
    # Chama diretamente o modelo de recuperação (Second Opinion) com temperatura baixa
    recovery_result = _try_local_agent("recovery", MODEL_RECOVERY, correction_prompt, temperature=0.1)
    
    if recovery_result:
        return recovery_result
        
    log("  [Autocura] Médico Local também falhou.", "ERR")
    return None