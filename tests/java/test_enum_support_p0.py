import pytest
from java.data_holder_test_gen import (
    is_pure_data_holder,
    generate_data_holder_test,
    _extract_enum_constants,
)


def test_extract_enum_with_constructor_args():
    """Real-world enum: `APPROVED("00"), INSUFFICIENT_FUNDS("51")`."""
    dep_ctx = '''
public enum TransactionStatusCode {
    APPROVED("00"),
    INSUFFICIENT_FUNDS("51"),
    PROCESSING_ERROR("07");
    // ...
}
'''
    consts = _extract_enum_constants(dep_ctx, "TransactionStatusCode")
    assert consts == ["APPROVED", "INSUFFICIENT_FUNDS", "PROCESSING_ERROR"]


def test_extract_enum_simple():
    dep_ctx = '''
public enum Color { RED, GREEN, BLUE }
'''
    consts = _extract_enum_constants(dep_ctx, "Color")
    assert consts == ["RED", "GREEN", "BLUE"]


def test_extract_enum_not_present():
    dep_ctx = "public class Foo {}"
    assert _extract_enum_constants(dep_ctx, "Color") == []


def test_extract_specific_enum_among_multiple():
    dep_ctx = '''
public enum Color { RED, GREEN }
public enum Size { S, M, L }
'''
    assert _extract_enum_constants(dep_ctx, "Size") == ["S", "M", "L"]


MCC_CLASS = '''package com.caju.transactionauthorizer.document;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.mapping.Document;
import com.caju.transactionauthorizer.enums.CategoryCodeName;

@Document(collection = "merchant_category_codes")
public class MerchantCategoryCodesDocument {
    @Id
    private String id;
    private String name;
    private CategoryCodeName categoryCodeName;

    public MerchantCategoryCodesDocument(String id, String name, CategoryCodeName categoryCodeName) {
        this.id = id;
        this.name = name;
        this.categoryCodeName = categoryCodeName;
    }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public CategoryCodeName getCategoryCodeName() { return categoryCodeName; }
    public void setCategoryCodeName(CategoryCodeName categoryCodeName) { this.categoryCodeName = categoryCodeName; }
}'''

MCC_DEP_CONTEXT = '''
package com.caju.transactionauthorizer.enums;
public enum CategoryCodeName {
    FOOD("Food"),
    MEAL("Meal"),
    CASH("Cash");
}
'''


def test_generate_test_with_enum_field_uses_first_constant():
    out = generate_data_holder_test(
        MCC_CLASS,
        "MerchantCategoryCodesDocumentTest",
        "com.caju.transactionauthorizer.document",
        dep_context=MCC_DEP_CONTEXT,
    )
    assert out is not None, "should not return None when enum is in dep_context"
    # Constructor test uses the FIRST enum constant
    assert "CategoryCodeName.FOOD" in out
    # The enum import must be present
    assert "import com.caju.transactionauthorizer.enums.CategoryCodeName;" in out
    # Class is still package-private XTest
    assert "class MerchantCategoryCodesDocumentTest" in out


def test_generate_test_returns_none_when_enum_not_in_dep_context():
    """Without dep_context (or with no matching enum), we cannot resolve the type → fall back to LLM."""
    out = generate_data_holder_test(
        MCC_CLASS,
        "MerchantCategoryCodesDocumentTest",
        "com.caju.transactionauthorizer.document",
        dep_context="",  # no enum info
    )
    assert out is None  # unsupported type → None → LLM fallback


def test_backwards_compat_no_dep_context_arg():
    """Old callers that don't pass dep_context still work for fully-supported types."""
    SIMPLE = '''package x;
public class Simple {
    private String name;
    public Simple(String name) { this.name = name; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
}'''
    out = generate_data_holder_test(SIMPLE, "SimpleTest", "x")
    # No enum needed, no dep_context needed → works
    assert out is not None
    assert "class SimpleTest" in out
