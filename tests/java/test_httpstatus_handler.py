import pytest
from java.refactor import _categorize_build_error


def test_handler_fires_on_httpstatus_mismatch():
    maven_out = """[ERROR] CtrlTest.test:42 expected: <202 ACCEPTED> but was: <200 OK>
[ERROR] Failed to execute..."""
    result = _categorize_build_error(maven_out)
    # New specific handler should mention HttpStatus or ResponseEntity context
    assert "HTTP" in result.upper() or "ResponseEntity" in result
    # Surgical hint: the actual status came from ResponseEntity
    assert "200" in result or "ok()" in result


def test_handler_fires_for_other_status_pairs():
    """Same logic for any X→Y status mismatch."""
    maven_out = "[ERROR] T.t:10 expected: <201 CREATED> but was: <200 OK>"
    result = _categorize_build_error(maven_out)
    assert "HTTP" in result.upper() or "ResponseEntity" in result


def test_does_not_fire_on_normal_assertion_mismatch():
    """A non-HTTP value mismatch should still use G1 (generic assertion handler)."""
    maven_out = "[ERROR] T.t:10 expected: <5> but was: <50>"
    result = _categorize_build_error(maven_out)
    # Should NOT pretend this is HTTP-related
    assert "HTTP" not in result.upper()
    assert "ResponseEntity" not in result


def test_handler_extracts_values():
    """The handler should mention BOTH the expected and actual status."""
    maven_out = "[ERROR] T.t:42 expected: <202 ACCEPTED> but was: <200 OK>"
    result = _categorize_build_error(maven_out)
    assert "202" in result and "200" in result
