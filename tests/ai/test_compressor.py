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


def test_maybe_compress_calls_compressor_for_long_code(monkeypatch):
    monkeypatch.setattr("ai.compressor.USE_LLMLINGUA", True)
    mock_compressor = MagicMock()
    mock_compressor.compress_prompt.return_value = {"compressed_prompt": "compressed_output"}
    monkeypatch.setattr("ai.compressor._get_compressor", lambda: mock_compressor)
    from ai import compressor
    result = compressor.maybe_compress("A" * 1000)
    assert result == "compressed_output"
    mock_compressor.compress_prompt.assert_called_once()


def test_maybe_compress_returns_original_on_error(monkeypatch):
    monkeypatch.setattr("ai.compressor.USE_LLMLINGUA", True)
    def boom():
        raise RuntimeError("model load failed")
    monkeypatch.setattr("ai.compressor._get_compressor", boom)
    from ai.compressor import maybe_compress
    code = "B" * 1000
    assert maybe_compress(code) == code
