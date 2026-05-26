"""N6 — preventive rule: service with lookup logic is not a passthrough.

TDD tests for _build_active_rules(). Red phase verifies these fail before
the rule is injected; green phase verifies all pass after injection.

Run with:
    python -m pytest tests/java/test_service_lookup_rule.py -v
"""

import sys
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pytest
from java.refactor import _build_active_rules


def _build(code):
    return _build_active_rules(
        original=code, _prod_imports=[],
        _self_import="import com.example.Service;",
        _test_cls_name="ServiceTest",
        _test_pkg="com.example",
        complement_mode=False,
        rules="STUB",
    )


def test_rule_present_when_service_has_repo_with_logic():
    """Service class + repo.find call + conditional logic → inject rule."""
    code = '''package com.example;

@Service
public class MerchantCategoryCodesServiceImpl {
    private final Repository repo;

    public CategoryCodeName checkCategory(String mcc) {
        var doc = repo.findByMcc(mcc).orElse(null);
        if (doc == null) {
            return CategoryCodeName.CASH;  // fallback — NOT passthrough
        }
        return doc.getCategoryCodeName();
    }
}'''
    out = _build(code)
    assert "SERVICE LOOKUP" in out.upper() or "passthrough" in out.lower()


def test_rule_mentions_mock_vs_actual_value():
    code = '''package com.example;
public class FooService {
    private Repository repo;
    public String find(String id) {
        return repo.findById(id).orElseThrow().getName().toUpperCase();
    }
}'''
    out = _build(code)
    # The rule should warn about the difference between mock seed and actual return
    assert "mock" in out.lower() and "transform" in out.lower() or "passthrough" in out.lower()


def test_no_rule_when_pure_passthrough():
    """Pure passthrough service — no logic between repo call and return → no rule."""
    code = '''package com.example;
public class FooService {
    private Repository repo;
    public Foo findById(String id) {
        return repo.findById(id);
    }
}'''
    out = _build(code)
    assert "SERVICE LOOKUP" not in out.upper()


def test_no_rule_when_no_repo_calls():
    """Class that doesn't call any repo* / repository* → no rule."""
    code = '''package com.example;
public class Calc {
    public int add(int a, int b) {
        if (a < 0) return 0;
        return a + b;
    }
}'''
    out = _build(code)
    assert "SERVICE LOOKUP" not in out.upper()


def test_no_rule_when_repo_call_without_logic():
    """repo call but the return is the direct result, no orElse/.map/if → no rule."""
    code = '''package com.example;
public class Plain {
    private Repository repo;
    public List<Item> list() { return repo.findAll(); }
}'''
    out = _build(code)
    assert "SERVICE LOOKUP" not in out.upper()
