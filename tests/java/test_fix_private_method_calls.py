import pytest
from java.refactor import _fix_private_method_calls, _extract_private_method_names

PROD_CLASS = '''package com.example;
public class Service {
    public String publicAction(String input) { return validate(input); }
    private String validate(String input) { return input.toUpperCase(); }
    private static int compute(int x) { return x * 2; }
}'''


def test_extracts_private_names():
    """Sanity check that the helper from M12 finds the private methods."""
    names = _extract_private_method_names(PROD_CLASS)
    assert set(names) == {"validate", "compute"}


def test_removes_test_method_calling_private():
    test_code = '''package com.example;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ServiceTest {

    @Test
    void testPublicAction() {
        assertEquals("HI", new Service().publicAction("hi"));
    }

    @Test
    void testValidate() {
        // BAD — calling a private method
        assertEquals("X", new Service().validate("x"));
    }

    @Test
    void testCompute() {
        // BAD — also calling a private static method
        assertEquals(4, Service.compute(2));
    }
}'''
    cleaned = _fix_private_method_calls(test_code, PROD_CLASS)
    # Tests calling privates removed
    assert "testValidate" not in cleaned
    assert "testCompute" not in cleaned
    # Public test preserved
    assert "testPublicAction" in cleaned


def test_leaves_unchanged_when_no_private_calls():
    test_code = '''class ServiceTest {
    @Test
    void testPublicOnly() {
        new Service().publicAction("x");
    }
}'''
    assert _fix_private_method_calls(test_code, PROD_CLASS) == test_code


def test_leaves_unchanged_when_class_has_no_privates():
    no_priv_class = '''public class Simple {
    public String hi() { return "hi"; }
}'''
    test_code = '''class SimpleTest {
    @Test
    void t() { new Simple().hi(); }
}'''
    assert _fix_private_method_calls(test_code, no_priv_class) == test_code


def test_does_not_remove_method_referenced_by_local_variable_with_same_name():
    """If a local variable happens to be named like a private method, the call
    `localVar.something()` isn't a call to the private method. Only patterns
    matching `.<privateName>(` should count as a hit (no whitelist needed since
    Java identifiers don't collide between local vars and method calls — but the
    test ensures we don't false-flag on substring matches like `validateAll` when
    private is `validate`)."""
    code = '''public class Holder {
    public void use() { validate(); }
    private void validate() {}
    private void validateAll() {}
}'''
    test_code = '''class HolderTest {
    @Test
    void t() {
        // calls validateAll (NOT validate) — must NOT trigger removal of this test
        new Holder().validateAll();
    }
}'''
    # Right now this test should fail validation BOTH ways — both validate and validateAll
    # are private. But the point is the matcher must use word boundaries so .validate(
    # does NOT match validateAll(. Adjust test to call a hypothetical PUBLIC method:
    code2 = '''public class Holder {
    public void validateAll() {}
    private void validate() {}
}'''
    test_code2 = '''class HolderTest {
    @Test
    void t() {
        new Holder().validateAll();  // public — must stay
    }
}'''
    out = _fix_private_method_calls(test_code2, code2)
    assert "validateAll" in out  # public method NOT removed
    assert "testPublicAction" not in out  # ensure we're checking the right output


def test_static_call_pattern_also_detected():
    test_code = '''class ServiceTest {
    @Test
    void t1() {
        Service.compute(5);
    }
    @Test
    void t2() {
        new Service().publicAction("x");
    }
}'''
    cleaned = _fix_private_method_calls(test_code, PROD_CLASS)
    assert "t1" not in cleaned   # called private static
    assert "t2" in cleaned


def test_removal_preserves_other_content():
    """After removing a @Test method, the surrounding class structure must remain intact."""
    test_code = '''package x;

import org.junit.jupiter.api.Test;

class ServiceTest {

    @Test
    void good() { /* keep me */ }

    @Test
    void bad() {
        new Service().validate("x");
    }
}'''
    cleaned = _fix_private_method_calls(test_code, PROD_CLASS)
    assert "class ServiceTest" in cleaned
    assert "void good()" in cleaned
    assert "void bad()" not in cleaned
    # Imports preserved
    assert "import org.junit.jupiter.api.Test;" in cleaned
    # Braces still balanced
    assert cleaned.count("{") == cleaned.count("}")
