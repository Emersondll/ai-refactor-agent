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
