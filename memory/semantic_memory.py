"""
memory/semantic_memory.py — Mem0 semantic memory wrapper.

SemanticMemory.store(text): saves a learning (success or failure note).
SemanticMemory.search(query): returns relevant past learnings as a string.

Runs fully locally: Ollama for LLM + embeddings, ChromaDB for storage.
Requires USE_MEM0=true and `ollama pull nomic-embed-text` run once.
"""

from config import USE_MEM0, OLLAMA_EMBED_MODEL, OLLAMA_BASE_URL

_MEM0_CONFIG = {
    "llm": {
        "provider": "ollama",
        "config": {
            "model": "qwen2.5-coder:7b",
            "ollama_base_url": OLLAMA_BASE_URL,
        },
    },
    "embedder": {
        "provider": "ollama",
        "config": {
            "model": OLLAMA_EMBED_MODEL,
            "ollama_base_url": OLLAMA_BASE_URL,
        },
    },
    "vector_store": {
        "provider": "chroma",
        "config": {
            "collection_name": "refactor_memories",
            "path": ".mem0_store",
        },
    },
}


class SemanticMemory:
    """Thin wrapper around Mem0 with lazy initialization and graceful fallback."""

    def __init__(self) -> None:
        self._mem0 = None

    def _get_mem0(self):
        if self._mem0 is None:
            from mem0 import Memory
            self._mem0 = Memory.from_config(_MEM0_CONFIG)
        return self._mem0

    def store(self, text: str, agent_id: str = "refactor") -> None:
        """Store a learning. Silently ignored when USE_MEM0=false or Ollama down."""
        if not USE_MEM0:
            return
        try:
            self._get_mem0().add(text, agent_id=agent_id)
        except Exception:
            pass

    def search(self, query: str, agent_id: str = "refactor",
               limit: int = 3) -> str:
        """Return relevant past learnings as a newline-joined string."""
        if not USE_MEM0:
            return ""
        try:
            results = self._get_mem0().search(query, agent_id=agent_id, limit=limit)
            entries = results.get("results", []) if isinstance(results, dict) else []
            return "\n".join(r["memory"] for r in entries if r.get("memory"))
        except Exception:
            return ""
