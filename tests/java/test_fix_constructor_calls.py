import pytest
from java.refactor import _fix_constructor_calls

DEP_CONTEXT_TX = """
// other context...
public record TransactionModel(String account, BigDecimal amount, String merchant, String mcc) {}
// CONSTRUCTOR CALL: new TransactionModel(String account, BigDecimal amount, String merchant, String mcc)
"""

DEP_CONTEXT_BALANCE = """
public class BalanceDocument { /* ... */ }
// CONSTRUCTOR CALL: new BalanceDocument(String id, String accountId, BigDecimal totalCredit, BigDecimal totalDebit, BigDecimal balance, Long version)
"""

def test_rewrites_call_with_too_few_args():
    test_code = '''package x;
class T {
    void t() {
        var m = new TransactionModel(new BigDecimal("100"), "merch", "5411");
    }
}'''
    out = _fix_constructor_calls(test_code, DEP_CONTEXT_TX)
    # 4 args expected, 3 found — rewrite
    assert 'new TransactionModel("sampleA", new BigDecimal("100.00"), "sampleC", "sampleD")' in out
    # old call gone
    assert 'new TransactionModel(new BigDecimal("100"), "merch", "5411")' not in out

def test_rewrites_no_args_call():
    test_code = '''class T { void t() { var d = new BalanceDocument(); } }'''
    out = _fix_constructor_calls(test_code, DEP_CONTEXT_BALANCE)
    # 6 args expected, 0 found — rewrite with full canonical signature
    assert 'new BalanceDocument("sampleA", "sampleB", new BigDecimal("100.00"), new BigDecimal("250.50"), new BigDecimal("100.00"), 1L)' in out

def test_leaves_correct_call_untouched():
    test_code = '''class T { void t() {
        var m = new TransactionModel("acc1", new BigDecimal("50"), "shop", "1234");
    } }'''
    out = _fix_constructor_calls(test_code, DEP_CONTEXT_TX)
    # Correct arg count → leave alone, do NOT rewrite
    assert 'new TransactionModel("acc1", new BigDecimal("50"), "shop", "1234")' in out

def test_balanced_paren_counting():
    """Nested method calls inside args must not confuse the arg counter."""
    test_code = '''class T { void t() {
        var m = new TransactionModel(getId(), getAmount(), buildMerchant("x", "y"));
    } }'''
    out = _fix_constructor_calls(test_code, DEP_CONTEXT_TX)
    # 3 args found (getId(), getAmount(), buildMerchant(...)) — needs 4 — rewrite
    assert 'new TransactionModel("sampleA", new BigDecimal("100.00"), "sampleC", "sampleD")' in out

def test_generic_in_args():
    """Generics with comma should not be counted as extra arg."""
    test_code = '''class T { void t() {
        var m = new TransactionModel(new ArrayList<String>(), new BigDecimal("1"), "a", "b");
    } }'''
    out = _fix_constructor_calls(test_code, DEP_CONTEXT_TX)
    # 4 args (ArrayList counts as 1 even with <String>) — leave alone
    assert 'new TransactionModel(new ArrayList<String>(), new BigDecimal("1"), "a", "b")' in out

def test_string_with_comma():
    """Comma inside string literal must not be counted as arg separator."""
    test_code = '''class T { void t() {
        var m = new TransactionModel("a,b,c", new BigDecimal("1"), "x", "y");
    } }'''
    out = _fix_constructor_calls(test_code, DEP_CONTEXT_TX)
    # 4 args — leave alone
    assert 'new TransactionModel("a,b,c"' in out

def test_no_constructor_hint_returns_unchanged():
    """If dep_context has no hint for the class, leave the call alone."""
    test_code = '''class T { void t() { var z = new UnknownClass(1, 2); } }'''
    out = _fix_constructor_calls(test_code, DEP_CONTEXT_TX)
    assert out == test_code

def test_unsupported_type_returns_unchanged_call():
    """If a required type has no sample value (e.g. an enum), leave the call alone."""
    dep_ctx = """// CONSTRUCTOR CALL: new Holder(String name, SomeEnum status)"""
    test_code = '''class T { void t() { var h = new Holder("x"); } }'''
    out = _fix_constructor_calls(test_code, dep_ctx)
    # Can't generate sample for SomeEnum → leave alone (let LLM/repair loop handle)
    assert 'new Holder("x")' in out

def test_multiple_calls_rewritten():
    test_code = '''class T {
        void t() {
            var a = new TransactionModel();
            var b = new TransactionModel(new BigDecimal("1"));
        }
    }'''
    out = _fix_constructor_calls(test_code, DEP_CONTEXT_TX)
    # Both rewritten
    assert out.count('new TransactionModel("sampleA", new BigDecimal("100.00"), "sampleC", "sampleD")') == 2
