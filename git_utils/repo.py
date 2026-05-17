"""
repo.py — Localização: git/repo.py

ATUALIZADO com suporte a BRANCH automática.

Fluxo:
  1. Clone: cria branch refactor/ai-YYYYMMDD_HHMMSS
  2. Update: volta para main, faz pull, cria nova branch
  3. Nunca trabalha em main (seguro 100%)
  4. Retorna (repo_path, branch_name) para main.py fazer commits
"""

import os
from datetime import datetime
from core.utils import run_cmd
from core.logger import log


def clone_or_update(repo: str, base_dir: str) -> tuple[str | None, str | None]:
    """
    Clona ou atualiza um repositório, criando branch de trabalho.
    
    Returns:
        (repo_path, branch_name) ou (None, None) em caso de falha
    """
    name      = repo.rstrip("/").split("/")[-1].replace(".git", "")
    repo_path = os.path.join(base_dir, name)
    
    # Nome de branch fixo para evitar perda de progresso entre execuções
    branch_name = "refactor/ai-agent-automation"

    if not os.path.exists(repo_path):
        # --- NOVO CLONE ---
        log(f"Clonando {repo} → {repo_path}")
        code, _, err = run_cmd(f'git clone "{repo}" "{repo_path}"')
        if code != 0:
            log(f"Falha no clone: {err.strip()[:300]}", "ERR")
            return None, None
        
        log("Clone bem-sucedido", "OK")
    else:
        # --- REPOSITÓRIO JÁ EXISTE ---
        log(f"Repositório já existe em {repo_path}")
        
        # Volta para main/master antes de fazer pull
        code, current, _ = run_cmd("git rev-parse --abbrev-ref HEAD", cwd=repo_path)
        current_branch = current.strip() if code == 0 else "unknown"
        log(f"Branch atual: {current_branch}")
        
        # Detecta main ou master
        main_branch = None
        for candidate in ["main", "master"]:
            code, _, _ = run_cmd(f"git show-ref --verify --quiet refs/heads/{candidate}", cwd=repo_path)
            if code == 0:
                main_branch = candidate
                break
        
        if not main_branch:
            log("Não encontrou main ou master", "ERR")
            return None, None
        
        log(f"Voltando para {main_branch}")
        run_cmd(f"git checkout {main_branch}", cwd=repo_path)
        
        # Faz pull para atualizar
        log(f"Atualizando {main_branch}")
        code, _, err = run_cmd("git pull", cwd=repo_path)
        if code != 0:
            log(f"Aviso no pull: {err.strip()[:200]}", "WARN")

    # CRIA A BRANCH DE TRABALHO
    # CRIA OU VOLTA PARA A BRANCH DE TRABALHO
    log(f"Preparando branch: {branch_name}")
    code_exists, _, _ = run_cmd(f"git show-ref --verify --quiet refs/heads/{branch_name}", cwd=repo_path)
    
    if code_exists == 0:
        log(f"Branch {branch_name} já existe. Fazendo checkout...")
        code, _, err = run_cmd(f"git checkout {branch_name}", cwd=repo_path)
        if code == 0:
            # Sincroniza com o remote para evitar non-fast-forward no push final
            sync_code, _, sync_err = run_cmd(f"git pull --rebase origin {branch_name}", cwd=repo_path)
            if sync_code != 0:
                log(f"Aviso ao sincronizar branch remota: {sync_err.strip()[:200]}", "WARN")
            else:
                log(f"Branch sincronizada com origin/{branch_name}", "OK")
    else:
        log(f"Criando nova branch: {branch_name}")
        code, _, err = run_cmd(f"git checkout -b {branch_name}", cwd=repo_path)

    if code != 0:
        log(f"Falha ao acessar branch {branch_name}: {err.strip()[:300]}", "ERR")
        return None, None

    log(f"Branch preparada com sucesso", "OK")
    return repo_path, branch_name


_AGENT_GITIGNORE_ENTRIES = [
    ".refactor_cache/",
    ".rag_store/",
]

def _ensure_agent_gitignore(repo_path: str) -> None:
    """Garante que o .gitignore do repo alvo nunca inclua os diretórios internos do agente."""
    gitignore_path = os.path.join(repo_path, ".gitignore")
    try:
        existing = open(gitignore_path).read() if os.path.exists(gitignore_path) else ""
        missing = [e for e in _AGENT_GITIGNORE_ENTRIES if e not in existing]
        if missing:
            with open(gitignore_path, "a") as f:
                f.write("\n### AI Refactor Agent — internal cache (never commit) ###\n")
                f.write("\n".join(missing) + "\n")
            log(f"[gitignore] Entradas adicionadas: {missing}", "OK")
    except Exception as exc:
        log(f"[gitignore] Não foi possível atualizar .gitignore: {exc}", "WARN")


def commit_and_push(repo_path: str, branch_name: str, phase: str) -> bool:
    """
    Faz git add + commit + push após cada fase.
    
    Args:
        repo_path: caminho do repositório
        branch_name: nome da branch (ex: refactor/ai-20240115_140000)
        phase: nome da fase (ex: 01_javadoc.md)
    
    Returns:
        True se o commit foi criado com sucesso
    """
    _ensure_agent_gitignore(repo_path)
    run_cmd("git add .", cwd=repo_path)

    code, _, err = run_cmd(
        f'git commit -m "refactor({phase}): AI improvements"',
        cwd=repo_path,
    )

    if code != 0:
        log(f"Nenhuma mudança para commitar na fase {phase}", "WARN")
        return False

    # Push — com rebase automático em caso de non-fast-forward
    push_code, _, push_err = run_cmd(f"git push origin {branch_name}", cwd=repo_path)
    if push_code == 0:
        log(f"Commit + push realizados ({phase}) em {branch_name}", "OK")
        return True

    log(f"Push falhou ({push_err.strip()[:120]}), tentando rebase...", "WARN")
    rebase_code, _, rebase_err = run_cmd(f"git pull --rebase origin {branch_name}", cwd=repo_path)
    if rebase_code == 0:
        push_code2, _, push_err2 = run_cmd(f"git push origin {branch_name}", cwd=repo_path)
        if push_code2 == 0:
            log(f"Push realizado após rebase ({phase})", "OK")
            return True
        log(f"Push falhou mesmo após rebase: {push_err2.strip()[:200]}", "WARN")
    else:
        log(f"Rebase falhou: {rebase_err.strip()[:200]}", "WARN")

    # Fallback: force-with-lease (seguro — só força se ninguém mais empurrou)
    force_code, _, force_err = run_cmd(f"git push --force-with-lease origin {branch_name}", cwd=repo_path)
    if force_code == 0:
        log(f"Push com force-with-lease realizado ({phase})", "WARN")
        return True

    log(f"Push falhou definitivamente: {force_err.strip()[:200]}", "ERR")
    return False