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
    Detecta quais bibliotecas Java a fase usa e busca docs relevantes.
    Retorna string vazia se USE_CONTEXT7=false ou sem conexão.
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
