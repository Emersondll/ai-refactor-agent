"""
java/javadoc_runner.py — Insere Javadoc em todos os métodos públicos.

Fluxo por arquivo:
  1. Lê o arquivo Java completo
  2. Envia ao LLM com instruções de documentação
  3. LLM adiciona /** */ onde falta, sem tocar no corpo dos métodos
  4. mvn compile — aceita ou reverte
  5. Emite eventos para o dashboard (FILE_ACCEPTED / FILE_REVERTED / FILE_SKIPPED)

Resiliência:
  - Cada arquivo processa em thread daemon com timeout de FILE_TIMEOUT_SECS
  - Exceções por arquivo não interrompem o loop principal
"""

import os
import re
import threading

from core.logger import log
from core.live_state import update as _live
from core.utils import read_file, write_file, run_cmd, load_skill
from ai.model import call_ai, call_model
from ai.sanitizer import clean_output
from java.refactor import get_java_files
from java.compiler import ENV_WRAPPER

SKILL_ID = "javadoc"
FILE_TIMEOUT_SECS = 300  # 5 minutos por arquivo

# C4: classes de bootstrap/configuração Spring não devem receber Javadoc (mesma regra do method_runner)
_BOOTSTRAP_RE = re.compile(r'@(SpringBootApplication|Configuration|SpringBootTest)\b')


def run_javadoc(repo_path: str, exec_logger=None) -> None:
    """Percorre todos os arquivos Java de produção e insere Javadoc nos métodos públicos."""
    rules = load_skill("java-javadoc", section="LLM INSTRUCTIONS")
    if not rules:
        log("[Javadoc] Skill 'java-javadoc' não encontrada — pulando fase", "WARN")
        return

    java_files = get_java_files(repo_path, tests=False)
    log(f"[Javadoc] {len(java_files)} arquivos candidatos")
    _live(active_skill=SKILL_ID, current_file="")

    # C3: salva conteúdo pré-javadoc de cada arquivo ANTES de lançar o thread.
    # Em caso de timeout o daemon pode ter escrito código parcial — restauramos o
    # conteúdo salvo (não o git), preservando refatorações de fases anteriores.
    pre_javadoc: dict[str, str] = {}

    for file_path in java_files:
        file_name = os.path.basename(file_path)
        try:
            pre_javadoc[file_path] = read_file(file_path) or ""
            t = threading.Thread(
                target=_process_one_file,
                args=(file_path, rules, repo_path, exec_logger),
                daemon=True,
            )
            t.start()
            t.join(FILE_TIMEOUT_SECS)
            if t.is_alive():
                log(f"  [javadoc] {file_name} — timeout ({FILE_TIMEOUT_SECS}s), pulando", "WARN")
                # Restaura o conteúdo anterior ao javadoc (preserva fases já aplicadas)
                saved = pre_javadoc.get(file_path, "")
                if saved:
                    write_file(file_path, saved)
                    log(f"  [javadoc] {file_name} — conteúdo pré-javadoc restaurado", "WARN")
                if exec_logger:
                    exec_logger.log_file_skipped(SKILL_ID, file_name, "timeout")
        except Exception as exc:
            log(f"  [javadoc] {file_name} — erro inesperado: {exc}", "WARN")
            if exec_logger:
                exec_logger.log_file_skipped(SKILL_ID, file_name, "error")

    _live(active_skill="", current_file="")


def _process_one_file(file_path: str, rules: str, repo_path: str, exec_logger) -> None:
    """Processa um único arquivo Java — inserção de Javadoc. Executado em thread daemon."""
    file_name = os.path.basename(file_path)
    code = read_file(file_path)
    if not code:
        return

    # C4: classes de bootstrap/configuração não devem receber Javadoc
    if _BOOTSTRAP_RE.search(code):
        log(f"  [javadoc] {file_name} — classe bootstrap/config, pulando")
        if exec_logger:
            exec_logger.log_file_skipped(SKILL_ID, file_name, "bootstrap_class")
        return

    # C: @Document/@Entity/record/enum são data holders sem lógica de negócio relevante.
    # Ambos os modelos (J1 primary e retry) modificam código estruturalmente nesses tipos →
    # pular evita code_structure_changed cascata e tempo desperdiçado.
    if re.search(r'@(Document|Entity|Table)\b', code) or re.search(r'\b(record|enum)\b', code):
        log(f"  [javadoc] {file_name} — data holder (@Document/record/enum), pulando")
        if exec_logger:
            exec_logger.log_file_skipped(SKILL_ID, file_name, "data_holder")
        return

    if _all_public_methods_documented(code):
        log(f"  [javadoc] {file_name} — já documentado, pulando")
        if exec_logger:
            exec_logger.log_file_skipped(SKILL_ID, file_name, "already_documented")
        return

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
        return

    # C1: verificação de integridade estrutural — LLM só pode ter adicionado comentários
    if _strip_comments(new_code) != _strip_comments(code):
        log(f"  [javadoc] {file_name} — LLM modificou código além dos comentários, tentando modelo code-specialized...", "WARN")

        # J1: retry com MODEL_STRUCT (qwen2.5-coder:7b) antes de rejeitar — neural-chat:7b
        # modifica código sistematicamente; código-especializado respeita melhor o scope.
        from config import MODEL_STRUCT
        from ai.prompt import build_prompt
        _retry_rules = (
            rules + "\n\n### CRITICAL: YOUR PREVIOUS ATTEMPT WAS REJECTED\n"
            "You modified code beyond adding Javadoc comments — this is FORBIDDEN.\n"
            "Add ONLY `/** ... */` blocks. Every method body, signature, import, "
            "field declaration, and blank line must remain byte-for-byte identical.\n"
        )
        _retry_prompt = build_prompt(code, _retry_rules, "refactor", file_name)
        _raw2, _ = call_model(MODEL_STRUCT, _retry_prompt, temperature=0.05, num_predict=4096)
        _retry_code = clean_output(_raw2)

        if _retry_code and _strip_comments(_retry_code) == _strip_comments(code):
            log(f"  [javadoc] {file_name} — retry com {MODEL_STRUCT} aceito ✓", "OK")
            new_code = _retry_code
        else:
            log(f"  [javadoc] {file_name} — retry também modificou código, rejeitando", "WARN")
            if exec_logger:
                exec_logger.log_file_skipped(SKILL_ID, file_name, "code_structure_changed")
            # S3: acumula no FailedFilesTracker → permanent_skip após 3 ciclos consecutivos
            from java.refactor import get_failed_tracker as _get_ft
            _get_ft().record(file_path, SKILL_ID, "code_structure_changed")
            return

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


# ---------------------------------------------------------------------------
# Heurística: verifica se todos os métodos públicos visíveis já têm Javadoc
# ---------------------------------------------------------------------------

_RE_METHOD_LINE = re.compile(
    r'public\s+(?!class\b|interface\b|enum\b|@interface\b)'
    r'(?:(?:static|final|synchronized|abstract|default)\s+)*'
    r'[\w<>\[\],\s]+\s+\w+\s*\(',
)


def _all_public_methods_documented(code: str) -> bool:
    """
    Retorna True se todos os métodos públicos visíveis já têm Javadoc.
    Usa scan linha a linha para evitar lookbehind de comprimento variável.
    """
    lines = code.splitlines()
    total = 0
    documented = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not _RE_METHOD_LINE.match(stripped):
            continue
        total += 1
        # Verifica até 6 linhas anteriores em busca de fim de javadoc
        for j in range(i - 1, max(-1, i - 7), -1):
            prev = lines[j].strip()
            # Fim de javadoc multi-linha ('*/') ou javadoc de linha única ('/** ... */')
            if prev.endswith('*/') and (prev == '*/' or prev.startswith('/*')):
                documented += 1
                break
            # Para de procurar se encontrar código não-Javadoc (não é anotação nem comentário)
            if prev and not prev.startswith('*') and not prev.startswith('/*') and not prev.startswith('@'):
                break
    if total == 0:
        return True
    return documented >= total


def _strip_comments(code: str) -> str:
    """Remove todos os comentários Java para comparação estrutural.
    Permite detectar se o LLM alterou código além de adicionar /** */ blocks."""
    # Remove comentários de bloco (/** ... */ e /* ... */)
    stripped = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
    # Remove comentários de linha (//)
    stripped = re.sub(r'//[^\n]*', '', stripped)
    # Normaliza espaços para comparação robusta
    return re.sub(r'\s+', ' ', stripped.strip())


def _normalize(code: str) -> str:
    return re.sub(r'\s+', ' ', code.strip())
