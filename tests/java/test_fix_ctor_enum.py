import pytest
from java.refactor import _fix_constructor_calls


DEP_CTX_WITH_ENUM = """
public class MerchantCategoryCodesDocument {
    private String id;
    private String mcc;
    private CategoryCodeName category;
}
// CONSTRUCTOR CALL: new MerchantCategoryCodesDocument(String id, String mcc, CategoryCodeName category)

public enum CategoryCodeName {
    FOOD("Food"),
    MEAL("Meal"),
    CASH("Cash");
}
"""


def test_rewrites_with_enum_first_constant():
    test_code = '''class T {
    void t() {
        var doc = new MerchantCategoryCodesDocument();
    }
}'''
    out = _fix_constructor_calls(test_code, DEP_CTX_WITH_ENUM)
    # 3 args expected, 0 found → rewrite using enum's first constant
    assert "new MerchantCategoryCodesDocument(" in out
    assert "CategoryCodeName.FOOD" in out
    assert "new MerchantCategoryCodesDocument()" not in out


def test_rewrites_with_enum_handles_string_args_in_pool():
    test_code = '''class T {
    void t() {
        var doc = new MerchantCategoryCodesDocument(null);
    }
}'''
    out = _fix_constructor_calls(test_code, DEP_CTX_WITH_ENUM)
    # Got 1 arg, expected 3 → rewrite. String slots get "sampleA"/"sampleB",
    # enum slot gets FOOD.
    assert "CategoryCodeName.FOOD" in out
    # And the string slots are populated
    assert '"sample' in out


def test_unresolved_type_still_bails():
    """Type that's neither in _TYPE_SAMPLES nor an enum in dep_context → leave alone."""
    dep_ctx = """
// CONSTRUCTOR CALL: new Foo(String x, ComplexCustomType y)
"""
    test_code = "class T { void t() { var f = new Foo(); } }"
    out = _fix_constructor_calls(test_code, dep_ctx)
    # ComplexCustomType not findable → leave the call alone
    assert "new Foo()" in out
    assert "ComplexCustomType.SOMETHING" not in out


def test_enum_without_dep_context_block_leaves_alone():
    """If the enum is REFERENCED in CONSTRUCTOR CALL but its definition is not in
    dep_context, we cannot resolve → leave alone."""
    dep_ctx = """
// CONSTRUCTOR CALL: new Foo(String x, UnknownEnum y)
"""
    test_code = "class T { void t() { var f = new Foo(); } }"
    out = _fix_constructor_calls(test_code, dep_ctx)
    assert "new Foo()" in out


def test_existing_correct_call_with_enum_unchanged():
    """If the LLM already wrote a correct call with enum, leave it alone."""
    test_code = '''class T {
    void t() {
        var doc = new MerchantCategoryCodesDocument("id", "mcc", CategoryCodeName.MEAL);
    }
}'''
    out = _fix_constructor_calls(test_code, DEP_CTX_WITH_ENUM)
    # 3 args present, count matches → no rewrite
    assert 'CategoryCodeName.MEAL' in out  # original value preserved
    assert out.count('CategoryCodeName.FOOD') == 0  # no rewrite happened


def test_multiple_enums_each_resolved():
    dep_ctx = """
// CONSTRUCTOR CALL: new Foo(StatusEnum s, ColorEnum c)

public enum StatusEnum { ACTIVE, INACTIVE }
public enum ColorEnum { RED, GREEN, BLUE }
"""
    test_code = "class T { void t() { var f = new Foo(); } }"
    out = _fix_constructor_calls(test_code, dep_ctx)
    assert "StatusEnum.ACTIVE" in out
    assert "ColorEnum.RED" in out
