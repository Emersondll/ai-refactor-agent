"""
ai/compressor.py — LLMLingua prompt compression wrapper.

maybe_compress(code): compresses Java source if USE_LLMLINGUA=true and
code is long enough. Returns original on any error (fail-safe).

The compressor is lazy-loaded on first use (~700MB BERT model download
from HuggingFace on first run).
"""

from config import USE_LLMLINGUA, LLMLINGUA_RATIO

_MIN_CHARS = 800  # Skip compression for short files — overhead not worth it
_MAX_SEQ_LEN = 512  # BERT-base max sequence length; overflow causes silent indexing errors
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
        # Guard: if input exceeds the model's max sequence length, skip compression.
        # Passing 513+ tokens through the 512-token BERT model causes silent indexing
        # errors that corrupt the output — safer to return the original unchanged.
        if hasattr(compressor, 'tokenizer'):
            token_count = len(compressor.tokenizer.encode(code, add_special_tokens=False))
            if token_count > _MAX_SEQ_LEN:
                return code
        result = compressor.compress_prompt(
            code,
            rate=LLMLINGUA_RATIO,
            force_tokens=["\n", "```java", "```", "{", "}"],
        )
        compressed = result.get("compressed_prompt", code)
        return compressed if compressed.strip() else code
    except Exception:
        return code
