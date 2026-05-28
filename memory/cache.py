"""
memory/cache.py — Cache engine for token reduction.

Dep context: persisted to disk by file content hash.
Phase tracking: in-memory per run (reset each time a new instance is created).
Project dict: in-memory + disk for reuse across runs.
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
        # Persistent phase directory — keyed by (file_hash, phase, content_hash)
        self._phase_dir = os.path.join(self._base, "phases")
        os.makedirs(self._dep_dir, exist_ok=True)
        os.makedirs(self._phase_dir, exist_ok=True)

        # In-memory: speed boost for the current run
        self._phase_done: dict[str, set[str]] = {}
        self._project_dict: Optional[str] = None

    # --- Dep context (disk, keyed by file content hash) ---

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

    # --- Phase tracking (in-memory + disco persistente entre runs) ---

    def is_phase_done(self, file_path: str, phase_name: str) -> bool:
        if phase_name in self._phase_done.get(file_path, set()):
            return True
        # S1: check disk — True if the file hash matches the last successful hash
        return self._disk_phase_matches(file_path, phase_name)

    def mark_phase_done(self, file_path: str, phase_name: str) -> None:
        self._phase_done.setdefault(file_path, set()).add(phase_name)
        # S1: persist to disk with the hash of the current file content
        self._persist_phase(file_path, phase_name)

    def _phase_key(self, file_path: str, phase_name: str) -> str:
        return f"{sha12(os.path.abspath(file_path))}_{phase_name}"

    def _persist_phase(self, file_path: str, phase_name: str) -> None:
        try:
            with open(file_path, encoding="utf-8") as f:
                content_hash = sha12(f.read())
            path = os.path.join(self._phase_dir, f"{self._phase_key(file_path, phase_name)}.hash")
            with open(path, "w", encoding="utf-8") as f:
                f.write(content_hash)
        except OSError:
            pass

    def _disk_phase_matches(self, file_path: str, phase_name: str) -> bool:
        try:
            path = os.path.join(self._phase_dir, f"{self._phase_key(file_path, phase_name)}.hash")
            if not os.path.exists(path):
                return False
            with open(file_path, encoding="utf-8") as f:
                current_hash = sha12(f.read())
            with open(path, encoding="utf-8") as f:
                saved_hash = f.read().strip()
            return current_hash == saved_hash
        except OSError:
            return False

    # --- Method-level tracking (chave: file_path#method_cache_key) ---

    def is_method_done(self, file_path: str, method_key: str, phase_name: str) -> bool:
        key = f"{file_path}#{method_key}"
        return phase_name in self._phase_done.get(key, set())

    def mark_method_done(self, file_path: str, method_key: str, phase_name: str) -> None:
        key = f"{file_path}#{method_key}"
        self._phase_done.setdefault(key, set()).add(phase_name)

    def done_method_keys(self, file_path: str, phase_name: str) -> set[str]:
        """Returns all method keys already processed for a given file/phase."""
        prefix = f"{file_path}#"
        return {
            k[len(prefix):]
            for k, phases in self._phase_done.items()
            if k.startswith(prefix) and phase_name in phases
        }

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
