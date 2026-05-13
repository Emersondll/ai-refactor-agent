import pytest
from unittest.mock import patch, MagicMock


def test_semantic_memory_disabled_store_is_noop(monkeypatch):
    monkeypatch.setattr("memory.semantic_memory.USE_MEM0", False)
    from memory.semantic_memory import SemanticMemory
    mem = SemanticMemory()
    mem.store("anything")  # must not raise


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
