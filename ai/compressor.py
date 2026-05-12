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
