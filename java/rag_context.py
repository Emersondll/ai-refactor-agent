"""
java/rag_context.py — LlamaIndex RAG-based dependency context.

get_rag_context(file_code, repo_path): finds related Java classes using
semantic vector search instead of import string matching. Requires
USE_RAG_CONTEXT=true and the nomic-embed-text model in Ollama.

Index is built once per repo_path and persisted to {repo_path}/.rag_store/.
"""

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
