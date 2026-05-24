import pytest
from java.refactor import _categorize_build_error


def test_int_to_long_returns_dedicated_handler():
    maven_out = """[ERROR] /path/BalanceServiceImplTest.java:[38,137] incompatible types: int cannot be converted to java.lang.Long
[ERROR] Failed to execute goal..."""
    result = _categorize_build_error(maven_out)
    # Must NOT mention ResponseEntity (the misleading fallback)
    assert "ResponseEntity" not in result
    # Must give a concrete fix
    assert "1L" in result or "Long.valueOf" in result
    # Must mention Long
    assert "Long" in result


def test_int_to_bigdecimal_returns_dedicated_handler():
    maven_out = "[ERROR] X.java:[10,5] incompatible types: int cannot be converted to java.math.BigDecimal"
    result = _categorize_build_error(maven_out)
    assert "ResponseEntity" not in result
    assert "BigDecimal" in result
    # Should suggest the constructor form
    assert 'new BigDecimal' in result


def test_double_to_bigdecimal_returns_dedicated_handler():
    maven_out = "[ERROR] X.java:[10,5] incompatible types: double cannot be converted to java.math.BigDecimal"
    result = _categorize_build_error(maven_out)
    assert "ResponseEntity" not in result
    assert "BigDecimal" in result
    assert 'new BigDecimal' in result


def test_bigdecimal_to_long_still_uses_E_handler():
    """Pre-existing Fix E behavior must remain intact."""
    maven_out = "[ERROR] X.java:[10,5] incompatible types: java.math.BigDecimal cannot be converted to java.lang.Long"
    result = _categorize_build_error(maven_out)
    assert "1L" in result or "Long.valueOf" in result
    assert "ResponseEntity" not in result


def test_unrelated_type_mismatch_still_uses_fallback():
    """If no specific int/double/BigDecimal pattern matches, fall back to the generic handler."""
    maven_out = """[ERROR] X.java:[5,3] incompatible types: java.util.List<java.lang.String> cannot be converted to java.util.Set<java.lang.String>"""
    result = _categorize_build_error(maven_out)
    # Generic handler is fine here — no special-case
    assert "TYPE MISMATCH" in result or "incompatible" in result.lower()
