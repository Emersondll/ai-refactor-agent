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
from core.executor import run_cmd
from core.logger import log


def clone_or_update(repo: str, base_dir: str) -> tuple[str | None, str | None]:
    """
    Clona ou atualiza um repositório, criando branch de trabalho.
    
    Returns:
        (repo_path, branch_name) ou (None, None) em caso de falha
    """
    name      = repo.rstrip("/").split("/")[-1].replace(".git", "")
    repo_path = os.path.join(base_dir, name)
    
    # Branch com timestamp — identificar execução
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    branch_name = f"refactor/ai-{timestamp}"

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
    log(f"Criando branch: {branch_name}")
    code, _, err = run_cmd(f"git checkout -b {branch_name}", cwd=repo_path)
    if code != 0:
        log(f"Falha ao criar branch: {err.strip()[:300]}", "ERR")
        return None, None
    
    log(f"Branch criada com sucesso", "OK")
    return repo_path, branch_name


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
    run_cmd("git add .", cwd=repo_path)

    code, _, err = run_cmd(
        f'git commit -m "refactor({phase}): AI improvements"',
        cwd=repo_path,
    )

    if code != 0:
        log(f"Nenhuma mudança para commitar na fase {phase}", "WARN")
        return False

    # Push
    push_code, _, push_err = run_cmd(f"git push origin {branch_name}", cwd=repo_path)
    if push_code == 0:
        log(f"Commit + push realizados ({phase}) em {branch_name}", "OK")
        return True
    else:
        log(f"Commit OK mas push falhou: {push_err.strip()[:200]}", "WARN")
        return False