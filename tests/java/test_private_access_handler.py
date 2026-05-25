import pytest
from java.refactor import _categorize_build_error


def test_private_access_handler_extracts_method_name():
    maven_out = """[ERROR] /path/MerchantCategoryCodesServiceImplTest.java:[104,42] validateCategory(java.lang.String,com.caju.transactionauthorizer.document.MerchantCategoryCodesDocument) has private access in com.caju.transactionauthorizer.service.impl.MerchantCategoryCodesServiceImpl
[ERROR] Failed to execute goal..."""
    result = _categorize_build_error(maven_out)
    assert "PRIVATE METHOD ACCESS ERROR" in result
    assert "validateCategory" in result
    # Surgical fix instruction
    assert "REMOVE" in result or "remove" in result.lower()
    # Mentions the public method workaround
    assert "public" in result.lower()


def test_private_access_handler_works_without_explicit_method_name():
    """Even when the regex can't parse the method, the handler should still fire with generic advice."""
    maven_out = "[ERROR] has private access in com.example.Foo"
    result = _categorize_build_error(maven_out)
    assert "PRIVATE METHOD ACCESS ERROR" in result


def test_assertion_error_unchanged():
    """Regression: ASSERTION errors must still produce ASSERTION handler, not private-access."""
    maven_out = "[ERROR] FooTest.t:10 expected: <5> but was: <50>"
    result = _categorize_build_error(maven_out)
    assert "PRIVATE METHOD ACCESS" not in result
    assert "ASSERTION" in result or "expected" in result.lower()


def test_private_handler_fires_before_method_error():
    """If both 'cannot find symbol method' AND 'has private access' appear, prefer the more
    specific 'has private access' (since the symbol IS found, just inaccessible)."""
    maven_out = """[ERROR] doSomething(int) has private access in com.example.Service
[ERROR] another line: cannot find symbol"""
    result = _categorize_build_error(maven_out)
    assert "PRIVATE METHOD ACCESS" in result
    assert "doSomething" in result
