"""
repo.py — Location: git/repo.py

Updated with automatic BRANCH support.

Flow:
  1. Clone: creates branch refactor/ai-YYYYMMDD_HHMMSS
  2. Update: returns to main, pulls, creates new branch
  3. Never works on main (100% safe)
  4. Returns (repo_path, branch_name) for main.py to make commits
"""

import os
from datetime import datetime
from core.utils import run_cmd
from core.logger import log


def clone_or_update(repo: str, base_dir: str) -> tuple[str | None, str | None]:
    """
    Clone or update a repository, creating a working branch.

    Returns:
        (repo_path, branch_name) or (None, None) on failure
    """
    name      = repo.rstrip("/").split("/")[-1].replace(".git", "")
    repo_path = os.path.join(base_dir, name)

    # Fixed branch name to avoid losing progress between runs
    branch_name = "refactor/ai-agent-automation"

    if not os.path.exists(repo_path):
        # --- NEW CLONE ---
        log(f"Cloning {repo} → {repo_path}")
        code, _, err = run_cmd(f'git clone "{repo}" "{repo_path}"')
        if code != 0:
            log(f"Clone failed: {err.strip()[:300]}", "ERR")
            return None, None

        log("Clone successful", "OK")
    else:
        # --- REPOSITORY ALREADY EXISTS ---
        log(f"Repository already exists at {repo_path}")

        # Return to main/master before pulling
        code, current, _ = run_cmd("git rev-parse --abbrev-ref HEAD", cwd=repo_path)
        current_branch = current.strip() if code == 0 else "unknown"
        log(f"Current branch: {current_branch}")

        # Detect main or master
        main_branch = None
        for candidate in ["main", "master"]:
            code, _, _ = run_cmd(f"git show-ref --verify --quiet refs/heads/{candidate}", cwd=repo_path)
            if code == 0:
                main_branch = candidate
                break

        if not main_branch:
            log("Could not find main or master", "ERR")
            return None, None

        log(f"Switching to {main_branch}")
        run_cmd(f"git checkout {main_branch}", cwd=repo_path)

        # Pull to update
        log(f"Updating {main_branch}")
        code, _, err = run_cmd("git pull", cwd=repo_path)
        if code != 0:
            log(f"Warning on pull: {err.strip()[:200]}", "WARN")

    # CREATE THE WORKING BRANCH
    # CREATE OR SWITCH TO THE WORKING BRANCH
    log(f"Preparing branch: {branch_name}")
    code_exists, _, _ = run_cmd(f"git show-ref --verify --quiet refs/heads/{branch_name}", cwd=repo_path)

    if code_exists == 0:
        log(f"Branch {branch_name} already exists. Checking out...")
        code, _, err = run_cmd(f"git checkout {branch_name}", cwd=repo_path)
        if code == 0:
            # Sync with remote to avoid non-fast-forward on final push
            sync_code, _, sync_err = run_cmd(f"git pull --rebase origin {branch_name}", cwd=repo_path)
            if sync_code != 0:
                log(f"Warning syncing remote branch: {sync_err.strip()[:200]}", "WARN")
            else:
                log(f"Branch synced with origin/{branch_name}", "OK")
    else:
        log(f"Creating new branch: {branch_name}")
        code, _, err = run_cmd(f"git checkout -b {branch_name}", cwd=repo_path)

    if code != 0:
        log(f"Failed to access branch {branch_name}: {err.strip()[:300]}", "ERR")
        return None, None

    log(f"Branch ready", "OK")
    return repo_path, branch_name


_AGENT_GITIGNORE_ENTRIES = [
    ".refactor_cache/",
    ".rag_store/",
]

def _ensure_agent_gitignore(repo_path: str) -> None:
    """Ensures the target repo's .gitignore never includes agent internal directories."""
    gitignore_path = os.path.join(repo_path, ".gitignore")
    try:
        existing = open(gitignore_path).read() if os.path.exists(gitignore_path) else ""
        missing = [e for e in _AGENT_GITIGNORE_ENTRIES if e not in existing]
        if missing:
            with open(gitignore_path, "a") as f:
                f.write("\n### AI Refactor Agent — internal cache (never commit) ###\n")
                f.write("\n".join(missing) + "\n")
            log(f"[gitignore] Entries added: {missing}", "OK")
    except Exception as exc:
        log(f"[gitignore] Could not update .gitignore: {exc}", "WARN")


def commit_and_push(repo_path: str, branch_name: str, phase: str) -> bool:
    """
    Run git add + commit + push after each phase.

    Args:
        repo_path: repository path
        branch_name: branch name (e.g. refactor/ai-20240115_140000)
        phase: phase name (e.g. 01_javadoc.md)

    Returns:
        True if the commit was created successfully
    """
    _ensure_agent_gitignore(repo_path)
    run_cmd("git add .", cwd=repo_path)

    code, _, err = run_cmd(
        f'git commit -m "refactor({phase}): AI improvements"',
        cwd=repo_path,
    )

    if code != 0:
        log(f"No changes to commit in phase {phase}", "WARN")
        return False

    # Push — with automatic rebase on non-fast-forward
    push_code, _, push_err = run_cmd(f"git push origin {branch_name}", cwd=repo_path)
    if push_code == 0:
        log(f"Commit + push done ({phase}) on {branch_name}", "OK")
        return True

    log(f"Push failed ({push_err.strip()[:120]}), trying rebase...", "WARN")
    rebase_code, _, rebase_err = run_cmd(f"git pull --rebase origin {branch_name}", cwd=repo_path)
    if rebase_code == 0:
        push_code2, _, push_err2 = run_cmd(f"git push origin {branch_name}", cwd=repo_path)
        if push_code2 == 0:
            log(f"Push done after rebase ({phase})", "OK")
            return True
        log(f"Push failed even after rebase: {push_err2.strip()[:200]}", "WARN")
    else:
        log(f"Rebase failed: {rebase_err.strip()[:200]}", "WARN")

    # Fallback: force-with-lease (safe — only forces if nobody else pushed)
    force_code, _, force_err = run_cmd(f"git push --force-with-lease origin {branch_name}", cwd=repo_path)
    if force_code == 0:
        log(f"Push with force-with-lease done ({phase})", "WARN")
        return True

    log(f"Push failed definitively: {force_err.strip()[:200]}", "ERR")
    return False


def commit_single_file(repo_path: str, file_abs_path: str, message: str) -> bool:
    """Commit a single file locally (no push). Crash-safety for long test runs."""
    rel = os.path.relpath(file_abs_path, repo_path)
    run_cmd(f'git add "{rel}"', cwd=repo_path)
    code, _, _ = run_cmd(f'git commit -m "{message}" -- "{rel}"', cwd=repo_path)
    return code == 0
