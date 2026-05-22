import pytest
from java.data_holder_test_gen import is_pure_data_holder, generate_data_holder_test

MERCHANT = '''package com.caju.transactionauthorizer.document;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.mapping.Document;

@Document(collection = "merchant")
public class MerchantDocument {
    @Id
    private String id;
    private String name;
    private String mcc;

    public MerchantDocument(String id, String name, String mcc) {
        this.id = id;
        this.name = name;
        this.mcc = mcc;
    }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public String getMcc() { return mcc; }
    public void setMcc(String mcc) { this.mcc = mcc; }
}'''

WITH_LOGIC = '''package x;
public class Calculator {
    private int total;
    public int getTotal() { return total; }
    public void addAmount(int v) { this.total = this.total + v; }
}'''

def test_merchant_is_pure_data_holder():
    assert is_pure_data_holder(MERCHANT) is True

def test_class_with_logic_is_not_data_holder():
    assert is_pure_data_holder(WITH_LOGIC) is False

def test_generate_merchant_test_produces_valid_structure():
    out = generate_data_holder_test(
        MERCHANT, "MerchantDocumentTest", "com.caju.transactionauthorizer.document")
    assert out is not None
    assert "package com.caju.transactionauthorizer.document;" in out
    assert "class MerchantDocumentTest" in out
    assert "new MerchantDocument(" in out
    assert "constructor_shouldInitializeAllFields" in out
    assert out.count("@Test") == 4
    assert "import com.caju.transactionauthorizer.document.MerchantDocument;" in out
    assert out.count("{") == out.count("}")

def test_unsupported_field_type_returns_none():
    enum_field = '''package x;
public class Holder {
    private SomeEnum status;
    public Holder(SomeEnum status) { this.status = status; }
    public SomeEnum getStatus() { return status; }
    public void setStatus(SomeEnum status) { this.status = status; }
}'''
    assert generate_data_holder_test(enum_field, "HolderTest", "x") is None

def test_timestamp_uses_sql_format():
    tx = '''package x;
import java.sql.Timestamp;
public class Tx {
    private Timestamp ts;
    public Tx(Timestamp ts) { this.ts = ts; }
    public Timestamp getTs() { return ts; }
    public void setTs(Timestamp ts) { this.ts = ts; }
}'''
    out = generate_data_holder_test(tx, "TxTest", "x")
    assert out is not None
    assert 'Timestamp.valueOf("2023-01-15 10:00:00")' in out
    assert "import java.sql.Timestamp;" in out
    assert "T10:00:00" not in out

def test_getter_with_ternary_logic_is_not_pure():
    code = '''package x;
public class Holder {
    private String id;
    public Holder(String id) { this.id = id; }
    public String getId() { return id != null ? id : ""; }
    public void setId(String id) { this.id = id; }
}'''
    assert is_pure_data_holder(code) is False

def test_getter_with_method_call_is_not_pure():
    code = '''package x;
public class Holder {
    private String id;
    public Holder(String id) { this.id = id; }
    public String getId() { return id.toUpperCase(); }
    public void setId(String id) { this.id = id; }
}'''
    assert is_pure_data_holder(code) is False

def test_setter_with_validation_logic_is_not_pure():
    code = '''package x;
public class Holder {
    private String id;
    public Holder(String id) { this.id = id; }
    public String getId() { return id; }
    public void setId(String id) { this.id = id.trim(); }
}'''
    assert is_pure_data_holder(code) is False
