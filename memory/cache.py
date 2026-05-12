"""
memory/cache.py — Motor de cache para redução de tokens.

Dep context: persiste em disco por hash do conteúdo do arquivo.
Phase tracking: em memória por run (zerado a cada nova instância).
Project dict: em memória + disco para reutilização entre runs.
"""

import hashlib
import os
from typing import Optional


def sha12(content: str) -> str:
    """Hash SHA-256 truncado em 12 chars — usado como chave de cache."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


class Cache:
    def __init__(self, repo_path: str):
        repo_abs = os.path.abspath(repo_path)
        repo_key = hashlib.sha256(repo_abs.encode()).hexdigest()[:8]
        self._base = os.path.join(repo_abs, ".refactor_cache", repo_key)
        self._dep_dir = os.path.join(self._base, "dep_ctx")
        os.makedirs(self._dep_dir, exist_ok=True)

        # In-memory: zerado a cada run (nova instância)
        self._phase_done: dict[str, set[str]] = {}
        self._project_dict: Optional[str] = None

    # --- Dep context (disco, keyed by file content hash) ---

    def get_dep_context(self, file_hash: str) -> Optional[str]:
        path = os.path.join(self._dep_dir, f"{file_hash}.txt")
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return f.read()
            except OSError:
                return None
        return None

    def set_dep_context(self, file_hash: str, context: str) -> None:
        path = os.path.join(self._dep_dir, f"{file_hash}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(context)

    # --- Phase tracking (in-memory por run) ---

    def is_phase_done(self, file_path: str, phase_name: str) -> bool:
        return phase_name in self._phase_done.get(file_path, set())

    def mark_phase_done(self, file_path: str, phase_name: str) -> None:
        self._phase_done.setdefault(file_path, set()).add(phase_name)

    # --- Project dictionary (in-memory + disco) ---

    def get_project_dict(self) -> Optional[str]:
        if self._project_dict is not None:
            return self._project_dict
        path = os.path.join(self._base, "dict.txt")
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self._project_dict = f.read()
            except OSError:
                pass
        return self._project_dict

    def set_project_dict(self, content: str) -> None:
        self._project_dict = content
        path = os.path.join(self._base, "dict.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError:
            pass
