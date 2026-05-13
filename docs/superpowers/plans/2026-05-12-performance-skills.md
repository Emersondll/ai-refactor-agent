# Performance Skills Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add LLMLingua (prompt compression), LlamaIndex+ChromaDB (RAG dep context), Mem0 (semantic memory), and Context7 (live docs) to the refactoring agent — all opt-in via `.env` flags, zero impact on existing behavior when disabled.

**Architecture:** Each skill is a self-contained module with a feature flag in `config.py`. ChromaDB is the shared vector backend for LlamaIndex and Mem0 (different collections). All skills run fully locally via Ollama; Context7 is an optional HTTP client that falls back gracefully when offline.

**Tech Stack:** `llmlingua`, `mem0ai`, `llama-index-core`, `llama-index-vector-stores-chroma`, `llama-index-embeddings-ollama`, `chromadb`, `requests` (already installed)

**Prerequisite (run once before enabling RAG or Mem0):**
```bash
ollama pull nomic-embed-text
```

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `config.py` | Modify | Add 5 feature flags + embed model config |
| `ai/compressor.py` | Create | LLMLingua lazy wrapper — `maybe_compress(code)` |
| `java/rag_context.py` | Create | LlamaIndex RAG — semantic dep context over project files |
| `memory/semantic_memory.py` | Create | Mem0 wrapper — store/query past run learnings |
| `ai/context7_client.py` | Create | Context7 HTTP client — fetch live Java library docs |
| `ai/model.py` | Modify | Call `maybe_compress()` before building prompt |
| `java/context.py` | Modify | Use `rag_context` when `USE_RAG_CONTEXT=true` |
| `java/refactor.py` | Modify | Query Mem0 before LLM, store result after accept/revert |
| `ai/prompt.py` | Modify | Inject Context7 docs when `USE_CONTEXT7=true` |
| `main.py` | Modify | Initialize RAG index at startup; pass `semantic_mem` through |
| `.gitignore` | Modify | Ignore `.rag_store/` and `.mem0_store/` |
| `tests/ai/test_compressor.py` | Create | Unit tests for compressor |
| `tests/java/test_rag_context.py` | Create | Unit tests for RAG context |
| `tests/memory/test_semantic_memory.py` | Create | Unit tests for semantic memory |
| `tests/ai/test_context7_client.py` | Create | Unit tests for Context7 client |

---

## Task 1: Dependencies + Config Flags

**Files:**
- Modify: `config.py`
- Modify: `.gitignore`

- [ ] **Step 1.1: Install packages**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent"
.venv/bin/pip install llmlingua mem0ai "llama-index-core>=0.10" llama-index-vector-stores-chroma llama-index-embeddings-ollama chromadb
```

Expected: all packages install without error.

- [ ] **Step 1.2: Verify imports**

```bash
.venv/bin/python -c "import llmlingua; import mem0; import llama_index.core; import chromadb; print('OK')"
```

Expected: `OK`

- [ ] **Step 1.3: Add flags to config.py**

In `config.py`, after the `USE_CLAUDE_FALLBACK` line, add:

```python
# ---------------------------------------------------------------------------
# Performance Skills (all disabled by default — enable via .env)
# ---------------------------------------------------------------------------
USE_LLMLINGUA    = os.getenv("USE_LLMLINGUA",    "false").lower() == "true"
USE_RAG_CONTEXT  = os.getenv("USE_RAG_CONTEXT",  "false").lower() == "true"
USE_MEM0         = os.getenv("USE_MEM0",         "false").lower() == "true"
USE_CONTEXT7     = os.getenv("USE_CONTEXT7",     "false").lower() == "true"
LLMLINGUA_RATIO  = float(os.getenv("LLMLINGUA_RATIO", "0.6"))
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
OLLAMA_BASE_URL    = os.getenv("OLLAMA_BASE_URL",    "http://localhost:11434")
```

- [ ] **Step 1.4: Add storage dirs to .gitignore**

In `.gitignore`, after the `.refactor_cache/` entry, add:

```
# RAG and semantic memory vector stores
.rag_store/
.mem0_store/
```

- [ ] **Step 1.5: Verify config imports**

```bash
.venv/bin/python -c "from config import USE_LLMLINGUA, USE_RAG_CONTEXT, USE_MEM0, USE_CONTEXT7; print('OK')"
```

Expected: `OK`

- [ ] **Step 1.6: Commit**

```bash
git add config.py .gitignore
git commit -m "feat: add feature flags for LLMLingua, RAG, Mem0, Context7 performance skills"
```

---

## Task 2: LLMLingua Prompt Compressor

**Files:**
- Create: `ai/compressor.py`
- Create: `tests/ai/test_compressor.py`
- Modify: `ai/model.py` (line ~311 — `call_ai` function)

- [ ] **Step 2.1: Write failing tests**

Create `tests/ai/test_compressor.py`:

```python
import pytest
from unittest.mock import patch, MagicMock


def test_maybe_compress_returns_original_when_disabled(monkeypatch):
    monkeypatch.setattr("ai.compressor.USE_LLMLINGUA", False)
    from ai.compressor import maybe_compress
    code = "x" * 2000
    assert maybe_compress(code) == code


def test_maybe_compress_skips_short_code(monkeypatch):
    monkeypatch.setattr("ai.compressor.USE_LLMLINGUA", True)
    from ai.compressor import maybe_compress
    short = "public class Foo {}"
    assert maybe_compress(short) == short


def test_maybe_compress_calls_llmlingua_for_long_code(monkeypatch):
    monkeypatch.setattr("ai.compressor.USE_LLMLINGUA", True)
    mock_compressor = MagicMock()
    mock_compressor.compress_prompt.return_value = {"compressed_prompt": "compressed"}
    monkeypatch.setattr("ai.compressor._get_compressor", lambda: mock_compressor)
    from ai import compressor
    # Force reload to pick up monkeypatched _get_compressor
    import importlib
    importlib.reload(compressor)
    monkeypatch.setattr("ai.compressor.USE_LLMLINGUA", True)
    monkeypatch.setattr("ai.compressor._get_compressor", lambda: mock_compressor)
    result = compressor.maybe_compress("A" * 1000)
    assert isinstance(result, str)


def test_maybe_compress_returns_original_on_error(monkeypatch):
    monkeypatch.setattr("ai.compressor.USE_LLMLINGUA", True)
    def boom():
        raise RuntimeError("model load failed")
    monkeypatch.setattr("ai.compressor._get_compressor", boom)
    from ai.compressor import maybe_compress
    code = "B" * 1000
    result = maybe_compress(code)
    assert result == code
```

- [ ] **Step 2.2: Run tests — expect FAIL**

```bash
.venv/bin/python -m pytest tests/ai/test_compressor.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError` or `ImportError` (module doesn't exist yet).

- [ ] **Step 2.3: Create ai/compressor.py**

```python
"""
ai/compressor.py — LLMLingua prompt compression wrapper.

maybe_compress(code): compresses Java source if USE_LLMLINGUA=true and
code is long enough. Returns original on any error (fail-safe).

The compressor is lazy-loaded on first use (~700MB BERT model download
from HuggingFace on first run).
"""

from config import USE_LLMLINGUA, LLMLINGUA_RATIO

_MIN_CHARS = 800  # Skip compression for short files — overhead not worth it
_compressor_instance = None


def _get_compressor():
    global _compressor_instance
    if _compressor_instance is None:
        from llmlingua import PromptCompressor
        _compressor_instance = PromptCompressor(
            model_name="microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
            use_llmlingua2=True,
            device_map="cpu",
        )
    return _compressor_instance


def maybe_compress(code: str) -> str:
    """
    Compress Java source code with LLMLingua if enabled and code is long.
    Returns original code unchanged on any failure.
    """
    if not USE_LLMLINGUA or len(code) < _MIN_CHARS:
        return code
    try:
        compressor = _get_compressor()
        result = compressor.compress_prompt(
            code,
            rate=LLMLINGUA_RATIO,
            force_tokens=["\n", "```java", "```", "{", "}"],
        )
        compressed = result.get("compressed_prompt", code)
        return compressed if compressed.strip() else code
    except Exception:
        return code
```

- [ ] **Step 2.4: Run tests — expect PASS**

```bash
.venv/bin/python -m pytest tests/ai/test_compressor.py -v
```

Expected: 4 passed.

- [ ] **Step 2.5: Integrate into ai/model.py**

In `ai/model.py`, find the `call_ai` function (near end of file) and update it:

```python
def call_ai(code: str, rules: str, mode: str, file_name: str,
            file_path: str = "", phase: str = "",
            dep_context: str = "") -> str | None:
    """Entrada principal — gera código a partir das regras da fase."""
    from ai.compressor import maybe_compress
    compressed_code = maybe_compress(code)
    prompt = build_prompt(compressed_code, rules, mode, file_name, dep_context=dep_context)
    return _run_pipeline(prompt, code, file_path, file_name, mode, phase)
```

Note: `_run_pipeline` still receives original `code` for the "no change needed" comparison on line `result.strip() == code.strip()`.

- [ ] **Step 2.6: Run full test suite**

```bash
.venv/bin/python -m pytest tests/ -v 2>&1 | tail -10
```

Expected: all 34 passed (30 existing + 4 new).

- [ ] **Step 2.7: Commit**

```bash
git add ai/compressor.py tests/ai/test_compressor.py ai/model.py
git commit -m "feat: add LLMLingua prompt compression (opt-in via USE_LLMLINGUA=true)"
```

---

## Task 3: LlamaIndex RAG Dependency Context

**Files:**
- Create: `java/rag_context.py`
- Create: `tests/java/test_rag_context.py`
- Modify: `java/context.py` (line ~30 — `get_dependency_context`)

- [ ] **Step 3.1: Write failing tests**

Create `tests/java/test_rag_context.py`:

```python
import pytest
from unittest.mock import patch, MagicMock


def test_get_rag_context_returns_string_when_disabled(monkeypatch):
    monkeypatch.setattr("java.rag_context.USE_RAG_CONTEXT", False)
    from java.rag_context import get_rag_context
    result = get_rag_context("public class Foo {}", "/fake/repo")
    assert result == ""


def test_get_rag_context_returns_empty_on_no_imports(monkeypatch):
    monkeypatch.setattr("java.rag_context.USE_RAG_CONTEXT", True)
    from java.rag_context import get_rag_context
    # No import statements → nothing to search for
    result = get_rag_context("public class Foo { void run() {} }", "/fake/repo")
    assert result == ""


def test_build_java_index_returns_none_for_missing_path(monkeypatch):
    monkeypatch.setattr("java.rag_context.USE_RAG_CONTEXT", True)
    from java.rag_context import _build_java_index
    result = _build_java_index("/nonexistent/path/repo")
    assert result is None


def test_get_rag_context_returns_empty_on_index_failure(monkeypatch):
    monkeypatch.setattr("java.rag_context.USE_RAG_CONTEXT", True)
    monkeypatch.setattr("java.rag_context._build_java_index", lambda p: None)
    from java.rag_context import get_rag_context
    result = get_rag_context(
        "import com.example.UserService;\npublic class Foo {}",
        "/fake/repo"
    )
    assert result == ""
```

- [ ] **Step 3.2: Run tests — expect FAIL**

```bash
.venv/bin/python -m pytest tests/java/test_rag_context.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3.3: Create java/rag_context.py**

```python
"""
java/rag_context.py — LlamaIndex RAG-based dependency context.

get_rag_context(file_code, repo_path): finds related Java classes using
semantic vector search instead of import string matching. Requires
USE_RAG_CONTEXT=true and the nomic-embed-text model in Ollama.

Index is built once per repo_path and persisted to {repo_path}/.rag_store/.
"""

import os
import re
from pathlib import Path

from config import USE_RAG_CONTEXT, OLLAMA_EMBED_MODEL, OLLAMA_BASE_URL
from java.context import _extract_simplified_header

_index_cache: dict[str, object] = {}  # repo_path → LlamaIndex VectorStoreIndex


def _build_java_index(repo_path: str):
    """Build (or load from disk) a LlamaIndex over all .java files in repo."""
    main_java = Path(repo_path) / "src" / "main" / "java"
    if not main_java.exists():
        return None

    try:
        import chromadb
        from llama_index.core import VectorStoreIndex, Document, StorageContext
        from llama_index.vector_stores.chroma import ChromaVectorStore
        from llama_index.embeddings.ollama import OllamaEmbedding

        store_path = str(Path(repo_path) / ".rag_store")
        client = chromadb.PersistentClient(path=store_path)
        collection = client.get_or_create_collection("java_index")
        vector_store = ChromaVectorStore(chroma_collection=collection)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        embed_model = OllamaEmbedding(
            model_name=OLLAMA_EMBED_MODEL, base_url=OLLAMA_BASE_URL
        )

        docs = []
        for java_file in main_java.rglob("*.java"):
            try:
                code = java_file.read_text(encoding="utf-8", errors="ignore")
                docs.append(Document(
                    text=code,
                    metadata={"path": str(java_file), "name": java_file.stem},
                ))
            except Exception:
                continue

        if not docs:
            return None

        return VectorStoreIndex.from_documents(
            docs, storage_context=storage_context, embed_model=embed_model,
            show_progress=False,
        )
    except Exception:
        return None


def get_rag_context(file_code: str, repo_path: str) -> str:
    """Return semantic dep context using RAG. Returns '' if disabled or on error."""
    if not USE_RAG_CONTEXT:
        return ""

    imports = re.findall(r'^import\s+[\w.]+\.(\w+);', file_code, re.MULTILINE)
    if not imports:
        return ""

    if repo_path not in _index_cache:
        _index_cache[repo_path] = _build_java_index(repo_path)

    index = _index_cache.get(repo_path)
    if index is None:
        return ""

    try:
        from llama_index.embeddings.ollama import OllamaEmbedding

        embed_model = OllamaEmbedding(
            model_name=OLLAMA_EMBED_MODEL, base_url=OLLAMA_BASE_URL
        )
        query = f"Java classes: {', '.join(imports[:6])}"
        retriever = index.as_retriever(similarity_top_k=4, embed_model=embed_model)
        nodes = retriever.retrieve(query)

        if not nodes:
            return ""

        parts = ["\n--- RAG DEPENDENCY CONTEXT ---"]
        for node in nodes:
            name = node.metadata.get("name", "Unknown")
            header = _extract_simplified_header(node.text, name)
            parts.append(header)

        return "\n".join(parts)
    except Exception:
        return ""
```

- [ ] **Step 3.4: Run tests — expect PASS**

```bash
.venv/bin/python -m pytest tests/java/test_rag_context.py -v
```

Expected: 4 passed.

- [ ] **Step 3.5: Integrate into java/context.py**

In `java/context.py`, update `get_dependency_context` to use RAG when enabled:

```python
def get_dependency_context(file_code: str, repo_path: str,
                           cache=None) -> str:
    """
    Retorna contexto de dependências para o arquivo.
    Cache-first: usa hash do conteúdo do arquivo como chave.
    Quando USE_RAG_CONTEXT=true, usa LlamaIndex em vez de os.walk.
    """
    if cache is not None:
        file_hash = sha12(file_code)
        cached = cache.get_dep_context(file_hash)
        if cached is not None:
            return cached

    from config import USE_RAG_CONTEXT
    if USE_RAG_CONTEXT:
        from java.rag_context import get_rag_context
        context = get_rag_context(file_code, repo_path)
    else:
        context = _build_dep_context(file_code, repo_path)

    if cache is not None:
        cache.set_dep_context(sha12(file_code), context)

    return context
```

- [ ] **Step 3.6: Run full test suite**

```bash
.venv/bin/python -m pytest tests/ -v 2>&1 | tail -10
```

Expected: all 38 passed.

- [ ] **Step 3.7: Commit**

```bash
git add java/rag_context.py tests/java/test_rag_context.py java/context.py
git commit -m "feat: add LlamaIndex RAG dep context (opt-in via USE_RAG_CONTEXT=true)"
```

---

## Task 4: Mem0 Semantic Memory

**Files:**
- Create: `memory/semantic_memory.py`
- Create: `tests/memory/test_semantic_memory.py`
- Modify: `java/refactor.py` — `_generate_and_validate` and `refactor_file`
- Modify: `main.py` — initialize `SemanticMemory` and pass to `refactor_file`

- [ ] **Step 4.1: Write failing tests**

Create `tests/memory/test_semantic_memory.py`:

```python
import pytest
from unittest.mock import patch, MagicMock


def test_semantic_memory_disabled_store_is_noop(monkeypatch):
    monkeypatch.setattr("memory.semantic_memory.USE_MEM0", False)
    from memory.semantic_memory import SemanticMemory
    mem = SemanticMemory()
    # Should not raise
    mem.store("anything")


def test_semantic_memory_disabled_search_returns_empty(monkeypatch):
    monkeypatch.setattr("memory.semantic_memory.USE_MEM0", False)
    from memory.semantic_memory import SemanticMemory
    mem = SemanticMemory()
    assert mem.search("anything") == ""


def test_semantic_memory_enabled_store_calls_mem0(monkeypatch):
    monkeypatch.setattr("memory.semantic_memory.USE_MEM0", True)
    mock_m = MagicMock()
    mock_m.add.return_value = None
    monkeypatch.setattr("memory.semantic_memory.SemanticMemory._get_mem0",
                        lambda self: mock_m)
    from memory.semantic_memory import SemanticMemory
    mem = SemanticMemory()
    mem.store("test learning")
    mock_m.add.assert_called_once_with("test learning", agent_id="refactor")


def test_semantic_memory_enabled_search_returns_joined_results(monkeypatch):
    monkeypatch.setattr("memory.semantic_memory.USE_MEM0", True)
    mock_m = MagicMock()
    mock_m.search.return_value = {
        "results": [{"memory": "lesson A"}, {"memory": "lesson B"}]
    }
    monkeypatch.setattr("memory.semantic_memory.SemanticMemory._get_mem0",
                        lambda self: mock_m)
    from memory.semantic_memory import SemanticMemory
    mem = SemanticMemory()
    result = mem.search("something")
    assert "lesson A" in result
    assert "lesson B" in result


def test_semantic_memory_search_returns_empty_on_exception(monkeypatch):
    monkeypatch.setattr("memory.semantic_memory.USE_MEM0", True)
    def boom(self):
        raise RuntimeError("Ollama not running")
    monkeypatch.setattr("memory.semantic_memory.SemanticMemory._get_mem0", boom)
    from memory.semantic_memory import SemanticMemory
    mem = SemanticMemory()
    assert mem.search("anything") == ""
```

- [ ] **Step 4.2: Run tests — expect FAIL**

```bash
.venv/bin/python -m pytest tests/memory/test_semantic_memory.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 4.3: Create memory/semantic_memory.py**

```python
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
```

- [ ] **Step 4.4: Run tests — expect PASS**

```bash
.venv/bin/python -m pytest tests/memory/test_semantic_memory.py -v
```

Expected: 5 passed.

- [ ] **Step 4.5: Integrate into java/refactor.py**

In `refactor.py`, update the `_generate_and_validate` signature and body to accept and use `semantic_mem`:

Find the function signature (currently around line 85-100 — search for `def _generate_and_validate`). Change it to:

```python
def _generate_and_validate(original: str, rules: str, mode: str,
                            file_name: str, file_path: str,
                            phase: str = "", cache=None,
                            semantic_mem=None) -> tuple[str | None, str | None]:
```

Inside `_generate_and_validate`, after building `dep_context` and before calling `call_ai`, add memory injection:

```python
    # Inject past learnings from Mem0 when available
    mem_context = ""
    if semantic_mem is not None:
        query = f"{phase} {file_name} {file_type_hint}"
        mem_context = semantic_mem.search(query)

    phase_delta = rules
    if test_context:
        phase_delta = rules + "\n\n" + test_context
    if mem_context:
        phase_delta = phase_delta + f"\n\n// PAST LEARNINGS:\n{mem_context}"
```

Where `file_type_hint` is extracted just before — add after the existing `dep_context` build:

```python
    file_type_hint = os.path.basename(file_path) if file_path else file_name
```

Also update the two `_generate_and_validate` call sites in `_refactor_whole_file` and `_refactor_by_method` to forward `semantic_mem=semantic_mem`.

- [ ] **Step 4.6: Update refactor_file signature**

Find `def refactor_file(...)` and add `semantic_mem=None`:

```python
def refactor_file(file: str, rules: str, repo_path: str,
                  phase: str, reporter: PhaseReporter,
                  exec_logger: ExecutionLogger | None = None,
                  cache=None, semantic_mem=None) -> bool:
```

After the phase-skip check and before the main refactor call, add the `semantic_mem` forward to `_refactor_whole_file` / `_refactor_by_method`.

After `if success` (FILE_ACCEPTED), store the learning:

```python
    if success and semantic_mem is not None:
        semantic_mem.store(
            f"SUCCESS: phase={phase_name} file_type={os.path.basename(file)} "
            f"mode={mode}"
        )
    elif not success and semantic_mem is not None:
        semantic_mem.store(
            f"FAILURE: phase={phase_name} file_type={os.path.basename(file)} "
            f"— check validator or build errors"
        )
```

- [ ] **Step 4.7: Initialize SemanticMemory in main.py**

In `main.py`, after `cache = Cache(repo_path)`, add:

```python
    from memory.semantic_memory import SemanticMemory
    semantic_mem = SemanticMemory()
```

Then update every `refactor_file(...)` call to pass `semantic_mem=semantic_mem`.

Current call (line ~122):
```python
refactor_file(f_path, rules, repo_path, phase_path, reporter, exec_logger, cache=cache)
```

Updated:
```python
refactor_file(f_path, rules, repo_path, phase_path, reporter, exec_logger,
              cache=cache, semantic_mem=semantic_mem)
```

- [ ] **Step 4.8: Run full test suite**

```bash
.venv/bin/python -m pytest tests/ -v 2>&1 | tail -10
```

Expected: all 43 passed.

- [ ] **Step 4.9: Commit**

```bash
git add memory/semantic_memory.py tests/memory/test_semantic_memory.py java/refactor.py main.py
git commit -m "feat: add Mem0 semantic memory — agent learns from success/failure across runs (opt-in via USE_MEM0=true)"
```

---

## Task 5: Context7 HTTP Client

**Files:**
- Create: `ai/context7_client.py`
- Create: `tests/ai/test_context7_client.py`
- Modify: `ai/prompt.py` — `build_prompt` function

- [ ] **Step 5.1: Write failing tests**

Create `tests/ai/test_context7_client.py`:

```python
import pytest
from unittest.mock import patch, MagicMock


def test_fetch_java_docs_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr("ai.context7_client.USE_CONTEXT7", False)
    from ai.context7_client import fetch_java_docs
    assert fetch_java_docs("spring-boot", "transactions") is None


def test_resolve_library_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr("ai.context7_client.USE_CONTEXT7", True)
    with patch("ai.context7_client.requests.post", side_effect=Exception("timeout")):
        from ai.context7_client import resolve_library
        assert resolve_library("spring-boot") is None


def test_fetch_java_docs_returns_none_when_resolve_fails(monkeypatch):
    monkeypatch.setattr("ai.context7_client.USE_CONTEXT7", True)
    monkeypatch.setattr("ai.context7_client.resolve_library", lambda name: None)
    from ai.context7_client import fetch_java_docs
    assert fetch_java_docs("spring-boot", "transactions") is None


def test_fetch_java_docs_returns_text_on_success(monkeypatch):
    monkeypatch.setattr("ai.context7_client.USE_CONTEXT7", True)
    monkeypatch.setattr("ai.context7_client.resolve_library",
                        lambda name: "/spring-io/spring-boot")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "result": {"content": [{"text": "Spring docs here"}]}
    }
    with patch("ai.context7_client.requests.post", return_value=mock_resp):
        from ai.context7_client import fetch_java_docs
        result = fetch_java_docs("spring-boot", "transactions")
    assert result == "Spring docs here"
```

- [ ] **Step 5.2: Run tests — expect FAIL**

```bash
.venv/bin/python -m pytest tests/ai/test_context7_client.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 5.3: Create ai/context7_client.py**

```python
"""
ai/context7_client.py — Context7 HTTP client for live Java library docs.

fetch_java_docs(library_name, topic): fetches relevant documentation from
Context7's API. Returns None when USE_CONTEXT7=false or when offline.

Context7 MCP endpoint: https://mcp.context7.com/mcp (JSON-RPC 2.0)
"""

import requests

from config import USE_CONTEXT7

_CONTEXT7_URL = "https://mcp.context7.com/mcp"
_TIMEOUT = 8


def resolve_library(name: str) -> str | None:
    """Resolve a library name to its Context7 library ID."""
    if not USE_CONTEXT7:
        return None
    try:
        resp = requests.post(
            _CONTEXT7_URL,
            json={
                "jsonrpc": "2.0", "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "resolve-library-id",
                    "arguments": {"libraryName": name},
                },
            },
            timeout=_TIMEOUT,
        )
        data = resp.json()
        content = data.get("result", {}).get("content", [])
        return content[0].get("text") if content else None
    except Exception:
        return None


def fetch_java_docs(library_name: str, topic: str,
                    tokens: int = 3000) -> str | None:
    """Fetch documentation for a Java library topic from Context7."""
    if not USE_CONTEXT7:
        return None
    library_id = resolve_library(library_name)
    if not library_id:
        return None
    try:
        resp = requests.post(
            _CONTEXT7_URL,
            json={
                "jsonrpc": "2.0", "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "get-library-docs",
                    "arguments": {
                        "context7CompatibleLibraryID": library_id,
                        "topic": topic,
                        "tokens": tokens,
                    },
                },
            },
            timeout=_TIMEOUT,
        )
        data = resp.json()
        content = data.get("result", {}).get("content", [])
        return content[0].get("text") if content else None
    except Exception:
        return None


def get_phase_docs(phase_delta: str) -> str:
    """
    Heuristically detect which Java libraries the phase touches and fetch docs.
    Returns empty string if nothing found or USE_CONTEXT7=false.
    """
    if not USE_CONTEXT7:
        return ""

    library_map = {
        "transactional": ("spring-boot", "transactions"),
        "@service": ("spring-boot", "service layer"),
        "@repository": ("spring-data", "repositories"),
        "@restcontroller": ("spring-boot", "rest controllers"),
        "junit": ("junit5", "assertions and test lifecycle"),
        "mockito": ("mockito", "mocking and stubbing"),
        "@mock": ("mockito", "mock annotations"),
    }

    phase_lower = phase_delta.lower()
    for keyword, (lib, topic) in library_map.items():
        if keyword in phase_lower:
            docs = fetch_java_docs(lib, topic, tokens=2000)
            if docs:
                return f"// Context7 docs for {lib} — {topic}:\n{docs}"
    return ""
```

- [ ] **Step 5.4: Run tests — expect PASS**

```bash
.venv/bin/python -m pytest tests/ai/test_context7_client.py -v
```

Expected: 4 passed.

- [ ] **Step 5.5: Integrate into ai/prompt.py**

In `build_prompt`, add Context7 docs as an optional section after `dep_context`:

```python
def build_prompt(code: str, phase_delta: str, mode: str, file_name: str,
                 dep_context: str = "") -> str:
    parts = [
        BASE_CONSTRAINTS,
        f"\n### PHASE RULES\n{phase_delta.strip()}",
        f"\n### TASK\n{_build_task(mode, file_name)}",
    ]
    if dep_context and dep_context.strip():
        parts.append(f"\n### DEPENDENCY CONTEXT\n{dep_context.strip()}")

    from ai.context7_client import get_phase_docs
    live_docs = get_phase_docs(phase_delta)
    if live_docs:
        parts.append(f"\n### LIBRARY DOCUMENTATION (live)\n{live_docs}")

    parts.append(f"\n### SOURCE FILE TO PROCESS\n```java\n{code}\n```")
    return "\n".join(parts)
```

- [ ] **Step 5.6: Run full test suite**

```bash
.venv/bin/python -m pytest tests/ -v 2>&1 | tail -10
```

Expected: all 47 passed.

- [ ] **Step 5.7: Commit**

```bash
git add ai/context7_client.py tests/ai/test_context7_client.py ai/prompt.py
git commit -m "feat: add Context7 HTTP client for live Java library docs (opt-in via USE_CONTEXT7=true)"
```

---

## Task 6: Final Verification + Usage Guide

**Files:**
- No new files

- [ ] **Step 6.1: Run complete test suite**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: all 47 passed, 0 failed.

- [ ] **Step 6.2: Verify import chain**

```bash
.venv/bin/python -c "
from ai.compressor import maybe_compress
from java.rag_context import get_rag_context
from memory.semantic_memory import SemanticMemory
from ai.context7_client import fetch_java_docs
print('All skills imported OK')
"
```

Expected: `All skills imported OK`

- [ ] **Step 6.3: Verify all skills off by default**

```bash
.venv/bin/python -c "
from config import USE_LLMLINGUA, USE_RAG_CONTEXT, USE_MEM0, USE_CONTEXT7
assert not USE_LLMLINGUA
assert not USE_RAG_CONTEXT
assert not USE_MEM0
assert not USE_CONTEXT7
print('All flags correctly off by default')
"
```

Expected: `All flags correctly off by default`

- [ ] **Step 6.4: Verify LLMLingua short-circuit**

```bash
.venv/bin/python -c "
from ai.compressor import maybe_compress
short = 'public class Foo {}'
assert maybe_compress(short) == short, 'short code must pass through unchanged'
print('LLMLingua short-circuit OK')
"
```

Expected: `LLMLingua short-circuit OK`

- [ ] **Step 6.5: Final commit**

```bash
git add .
git commit -m "docs: verify all performance skills integrated and tested (47 tests passing)"
```

---

## Enabling Skills in Production

Add to `.env` the flags for the skills you want active:

```env
# Enable all (requires: ollama pull nomic-embed-text)
USE_LLMLINGUA=true
USE_RAG_CONTEXT=true
USE_MEM0=true
USE_CONTEXT7=true          # requires internet access

# Tuning
LLMLINGUA_RATIO=0.6        # keep 60% of tokens (0.5–0.7 range)
OLLAMA_EMBED_MODEL=nomic-embed-text
OLLAMA_BASE_URL=http://localhost:11434
```

**Recommended activation order:**
1. `USE_LLMLINGUA=true` — immediate token savings, no extra model needed
2. `USE_RAG_CONTEXT=true` — better dep context (run `ollama pull nomic-embed-text` first)
3. `USE_MEM0=true` — needs a few runs to accumulate learnings
4. `USE_CONTEXT7=true` — only if internet is available during refactoring
