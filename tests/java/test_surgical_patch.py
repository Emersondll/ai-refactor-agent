import pytest
from java.refactor import _try_surgical_patch

# Realistic test file with line numbers matching what Maven would report
TEST_FILE_ASSERTNULL_BUG = '''package com.caju.transactionauthorizer.document;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import com.caju.transactionauthorizer.document.MerchantDocument;

class MerchantDocumentTest {

    private MerchantDocument document;

    @BeforeEach
    void setUp() {
        document = new MerchantDocument("testId", "Test Merchant", "5411");
    }

    @Test
    void testConstructorInitialization() {
        assertEquals("testId", document.getId());
    }

    @Test
    void testGetAndSetId() {
        String newId = "updatedId";
        assertNull(document.getId());
        document.setId(newId);
        assertEquals(newId, document.getId());
    }
}
'''

MAVEN_OUT_ASSERTNULL_BUG = """[ERROR] Tests run: 2, Failures: 1, Errors: 0
[ERROR] MerchantDocumentTest.testGetAndSetId:24 expected: <null> but was: <testId>
[ERROR] Failed to execute goal ..."""

def test_assertnull_to_assertequals_patch():
    out = _try_surgical_patch(TEST_FILE_ASSERTNULL_BUG, MAVEN_OUT_ASSERTNULL_BUG)
    assert out is not None, "patcher should produce output"
    # The assertNull line on test file line 24 should become assertEquals
    assert 'assertNull(document.getId())' not in out
    assert 'assertEquals("testId", document.getId())' in out
    # Other lines must remain unchanged
    assert 'document.setId(newId)' in out
    assert 'assertEquals(newId, document.getId())' in out

# expected=value, actual=null → assertEquals(X, expr) becomes assertNull(expr)
TEST_FILE_VALUE_BUT_NULL = '''package x;
import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;

class Demo {
    @Test
    void shouldBeAcc() {
        Object thing = null;
        assertEquals(Type.ACC, thing);
    }
}
'''
MAVEN_OUT_VALUE_BUT_NULL = "[ERROR] Demo.shouldBeAcc:9 expected: <ACC> but was: <null>"

def test_assertequals_to_assertnull_patch():
    out = _try_surgical_patch(TEST_FILE_VALUE_BUT_NULL, MAVEN_OUT_VALUE_BUT_NULL)
    assert out is not None
    assert 'assertEquals(Type.ACC, thing)' not in out
    assert 'assertNull(thing)' in out

# expected and actual both non-null, both non-"null" string → simple literal swap
TEST_FILE_VALUE_MISMATCH = '''package x;
import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;

class Demo {
    @Test
    void shouldBeFifty() {
        int got = 50;
        assertEquals(5, got);
    }
}
'''
MAVEN_OUT_VALUE_MISMATCH = "[ERROR] Demo.shouldBeFifty:9 expected: <5> but was: <50>"

def test_value_mismatch_swap_patch():
    out = _try_surgical_patch(TEST_FILE_VALUE_MISMATCH, MAVEN_OUT_VALUE_MISMATCH)
    assert out is not None
    # The "5" on line 9 should become "50" — but careful: "50" must not become "500"
    assert 'assertEquals(50, got)' in out

def test_no_assertion_failure_returns_none():
    maven_out_compile_err = "[ERROR] /path/Foo.java:[5,12] cannot find symbol\n  symbol: class Bar"
    out = _try_surgical_patch("class X {}", maven_out_compile_err)
    assert out is None

def test_line_number_out_of_range_returns_none():
    short_file = "package x;\nclass X {}\n"
    out = _try_surgical_patch(short_file, "[ERROR] X.t:99 expected: <a> but was: <b>")
    assert out is None
