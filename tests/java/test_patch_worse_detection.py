"""Tests for _maven_output_got_worse — safety net for P4 surgical patch (N8)."""
import pytest
from java.refactor import _maven_output_got_worse


def test_same_error_count_not_worse():
    old = "[ERROR] FooTest:10 expected: <null> but was: <bar>"
    new = "[ERROR] FooTest:10 expected: <null> but was: <baz>"  # same shape
    assert _maven_output_got_worse(old, new) is False


def test_new_error_type_is_worse():
    """Original was assertion-only; new has compile error → worse."""
    old = "[ERROR] FooTest:10 expected: <null> but was: <bar>"
    new = ("[ERROR] FooTest:5 incompatible types: String cannot be converted to Foo\n"
           "[ERROR] FooTest:10 expected: <null> but was: <bar>")
    assert _maven_output_got_worse(old, new) is True


def test_more_failures_is_worse():
    """Same TYPE of error, but count went up → worse."""
    old = "[ERROR] FooTest:10 expected: <null> but was: <bar>"
    new = ("[ERROR] FooTest:10 expected: <null> but was: <bar>\n"
           "[ERROR] FooTest:20 expected: <null> but was: <baz>\n"
           "[ERROR] FooTest:30 expected: <null> but was: <qux>")
    assert _maven_output_got_worse(old, new) is True


def test_compile_error_appeared_is_worse():
    """The exact production scenario: assertion changed into a String-vs-Object."""
    old = "[ERROR] FooTest:63 expected: <null> but was: <TransactionCodeModel[code=null]>"
    new = ("[ERROR] FooTest:63 expected: java.lang.String<TransactionCodeModel[code=null]> "
           "but was: com.caju.TransactionCodeModel<TransactionCodeModel[code=null]>")
    # The new error has TYPE INFO (java.lang.String / com.caju...) that the old didn't.
    # This is the smoking gun of the N7 production bug.
    assert _maven_output_got_worse(old, new) is True


def test_fewer_errors_not_worse():
    """If the patch reduced the error count, it helped — not worse."""
    old = ("[ERROR] FooTest:10 expected: <X> but was: <Y>\n"
           "[ERROR] FooTest:20 expected: <A> but was: <B>")
    new = "[ERROR] FooTest:20 expected: <A> but was: <B>"
    assert _maven_output_got_worse(old, new) is False


def test_empty_new_output_not_worse():
    """Edge: if new output is empty (test passed), it's NOT worse."""
    old = "[ERROR] FooTest:10 expected: <null> but was: <bar>"
    new = ""
    assert _maven_output_got_worse(old, new) is False


def test_empty_old_output_handled():
    """Edge: if old was empty (unusual), don't crash."""
    assert _maven_output_got_worse("", "[ERROR] something") is True
    assert _maven_output_got_worse("", "") is False
