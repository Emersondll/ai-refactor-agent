"""
java/javadoc_runner.py — Insere Javadoc em todos os métodos públicos.

Fluxo por arquivo:
  1. Lê o arquivo Java completo
  2. Envia ao LLM com instruções de documentação
  3. LLM adiciona /** */ onde falta, sem tocar no corpo dos métodos
  4. mvn compile — aceita ou reverte
  5. Emite eventos para o dashboard (FILE_ACCEPTED / FILE_REVERTED / FILE_SKIPPED)
"""

import os
import re

from core.logger import log
from core.live_state import update as _live
from core.utils import read_file, write_file, run_cmd, load_skill
from ai.model import call_ai
from java.refactor import get_java_files
from java.compiler import ENV_WRAPPER

SKILL_ID = "javadoc"


def run_javadoc(repo_path: str, exec_logger=None) -> None:
    """Percorre todos os arquivos Java de produção e insere Javadoc nos métodos públicos."""
    rules = load_skill("java-javadoc", section="LLM INSTRUCTIONS")
    if not rules:
        log("[Javadoc] Skill 'java-javadoc' não encontrada — pulando fase", "WARN")
        return

    java_files = get_java_files(repo_path, tests=False)
    log(f"[Javadoc] {len(java_files)} arquivos candidatos")
    _live(active_skill=SKILL_ID, current_file="")

    for file_path in java_files:
        file_name = os.path.basename(file_path)
        code = read_file(file_path)
        if not code:
            continue

        # Pula arquivo que já tem Javadoc em todos os métodos públicos visíveis
        if _all_public_methods_documented(code):
            log(f"  [javadoc] {file_name} — já documentado, pulando")
            if exec_logger:
                exec_logger.log_file_skipped(SKILL_ID, file_name, "already_documented")
            continue

        _live(active_skill=SKILL_ID, current_file=file_name)
        if exec_logger:
            exec_logger.log_file_processing(SKILL_ID, file_name, "java", "javadoc")

        log(f"  [javadoc] {file_name}")
        new_code = call_ai(
            code, rules, "refactor", file_name,
            file_path=file_path,
            phase=SKILL_ID,
        )

        if not new_code or _normalize(new_code) == _normalize(code):
            log(f"  [javadoc] {file_name} — sem alteração")
            if exec_logger:
                exec_logger.log_file_skipped(SKILL_ID, file_name, "no_change")
            continue

        write_file(file_path, new_code)
        rc, _, _ = run_cmd(ENV_WRAPPER.format("mvn compile -q"), cwd=repo_path)
        if rc == 0:
            log(f"  [javadoc] {file_name} — aceito ✓", "OK")
            if exec_logger:
                exec_logger.log_file_accepted(SKILL_ID, file_name, "+javadoc")
        else:
            log(f"  [javadoc] {file_name} — compile falhou, revertendo", "WARN")
            write_file(file_path, code)
            if exec_logger:
                exec_logger.log_file_reverted(SKILL_ID, file_name, "compile_failed")

    _live(active_skill="", current_file="")


# ---------------------------------------------------------------------------
# Heurística: verifica se todos os métodos públicos visíveis já têm Javadoc
# ---------------------------------------------------------------------------

_RE_PUBLIC_METHOD = re.compile(
    r'(?<!\*/\s{0,80})'          # não precedido de fim de javadoc
    r'public\s+(?!class|interface|enum|@interface)'
    r'(?:(?:static|final|synchronized|abstract)\s+)*'
    r'[\w<>\[\]]+\s+\w+\s*\(',
    re.MULTILINE,
)

_RE_JAVADOC_BEFORE = re.compile(r'/\*\*[\s\S]*?\*/\s*\n\s*public\s', re.MULTILINE)


def _all_public_methods_documented(code: str) -> bool:
    """Retorna True se o número de métodos públicos documentados iguala o total."""
    total = len(_RE_PUBLIC_METHOD.findall(code))
    if total == 0:
        return True
    documented = len(_RE_JAVADOC_BEFORE.findall(code))
    return documented >= total


def _normalize(code: str) -> str:
    return re.sub(r'\s+', ' ', code.strip())
