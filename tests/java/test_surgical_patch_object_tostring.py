import pytest
from java.refactor import _try_surgical_patch


def test_assertnull_to_assertnotnull_when_actual_is_object_tostring():
    """Reproduces the production bug: P4 must NOT quote object toString as String literal."""
    test_code = '''package x;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class FooTest {

    @Test
    void shouldReturnNull() {
        Object result = service.call();
        assertNull(result);
    }
}
'''
    maven_out = (
        "[ERROR] FooTest.shouldReturnNull:9 "
        "expected: <null> but was: <TransactionCodeModel[code=null]>"
    )
    patched = _try_surgical_patch(test_code, maven_out)
    assert patched is not None
    # Must NOT quote the toString as a String literal — would compile but fail worse
    assert 'assertEquals("TransactionCodeModel[code=null]"' not in patched
    # Must use assertNotNull(result) — the only safe assertion
    assert 'assertNotNull(result)' in patched


def test_assertnull_to_assertnotnull_when_actual_has_parens():
    test_code = '''class T {
    @Test
    void t() { assertNull(svc.find()); }
}'''
    maven_out = "[ERROR] T.t:3 expected: <null> but was: <Foo(id=1, name=bar)>"
    patched = _try_surgical_patch(test_code, maven_out)
    assert patched is not None
    assert 'assertNotNull(svc.find())' in patched
    assert 'assertEquals(' not in patched.split('assertNotNull')[0]


def test_simple_string_value_still_uses_assertequals():
    """Regression: when actual is a plain identifier/value (no [/]/=/(/)),
    P4 should STILL use the existing assertEquals("value", expr) behavior."""
    test_code = '''class T {
    @Test
    void t() { assertNull(thing.getId()); }
}'''
    maven_out = "[ERROR] T.t:3 expected: <null> but was: <testId>"
    patched = _try_surgical_patch(test_code, maven_out)
    assert patched is not None
    # Simple identifier — keep the existing behavior
    assert 'assertEquals("testId", thing.getId())' in patched


def test_simple_numeric_value_still_uses_assertequals():
    test_code = '''class T {
    @Test
    void t() { assertNull(svc.count()); }
}'''
    maven_out = "[ERROR] T.t:3 expected: <null> but was: <42>"
    patched = _try_surgical_patch(test_code, maven_out)
    assert patched is not None
    assert 'assertEquals("42", svc.count())' in patched


def test_actual_with_equals_uses_assertnotnull():
    """Even a single = is enough to suggest object toString — go safe."""
    test_code = '''class T {
    @Test
    void t() { assertNull(svc.get()); }
}'''
    maven_out = "[ERROR] T.t:3 expected: <null> but was: <key=value>"
    patched = _try_surgical_patch(test_code, maven_out)
    assert patched is not None
    assert 'assertNotNull(svc.get())' in patched


def test_actual_with_only_brackets_uses_assertnotnull():
    test_code = '''class T {
    @Test
    void t() { assertNull(svc.list()); }
}'''
    maven_out = "[ERROR] T.t:3 expected: <null> but was: <[]>"
    patched = _try_surgical_patch(test_code, maven_out)
    assert patched is not None
    assert 'assertNotNull(svc.list())' in patched
