import pytest
from unittest.mock import patch, MagicMock


def test_get_rag_context_returns_empty_when_disabled(monkeypatch):
    monkeypatch.setattr("java.rag_context.USE_RAG_CONTEXT", False)
    from java.rag_context import get_rag_context
    result = get_rag_context("public class Foo {}", "/fake/repo")
    assert result == ""


def test_get_rag_context_returns_empty_on_no_imports(monkeypatch):
    monkeypatch.setattr("java.rag_context.USE_RAG_CONTEXT", True)
    from java.rag_context import get_rag_context
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
