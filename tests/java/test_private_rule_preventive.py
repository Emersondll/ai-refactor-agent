import pytest
from java.refactor import _build_active_rules

CLASS_WITH_PRIVATES = '''package com.example;

public class Service {
    private final Repository repo;

    public Service(Repository repo) {
        this.repo = repo;
    }

    public Result performAction(String input) {
        validateInput(input);
        return repo.findById(input);
    }

    private void validateInput(String input) {
        if (input == null) throw new IllegalArgumentException();
    }

    private static String formatKey(String raw) {
        return raw.trim().toUpperCase();
    }

    protected void onAction() { /* hook */ }
}'''

CLASS_NO_PRIVATES = '''package com.example;
public class Simple {
    public Simple() {}
    public String hello() { return "hi"; }
}'''


def _build(code):
    return _build_active_rules(
        original=code,
        _prod_imports=[],
        _self_import="import com.example.Service;",
        _test_cls_name="ServiceTest",
        _test_pkg="com.example",
        complement_mode=False,
        rules="STUB_SKILL_RULES",
    )


def test_private_block_injected_when_class_has_privates():
    out = _build(CLASS_WITH_PRIVATES)
    assert "### PRIVATE METHODS — NEVER CALL" in out
    assert "validateInput" in out
    assert "formatKey" in out


def test_private_block_lists_no_private_when_none_exist():
    out = _build(CLASS_NO_PRIVATES)
    assert "### PRIVATE METHODS" not in out


def test_protected_methods_not_listed_as_private():
    out = _build(CLASS_WITH_PRIVATES)
    # onAction is protected → must NOT appear in PRIVATE METHODS section
    if "### PRIVATE METHODS — NEVER CALL" in out:
        section_start = out.index("### PRIVATE METHODS — NEVER CALL")
        next_section = out.find("###", section_start + 10)
        section = out[section_start : next_section if next_section != -1 else len(out)]
        assert "onAction" not in section


def test_private_section_mentions_workaround():
    """The rule must explain WHAT to do instead — test via the public method that calls it."""
    out = _build(CLASS_WITH_PRIVATES)
    section_start = out.index("### PRIVATE METHODS — NEVER CALL")
    section = out[section_start:section_start + 500]
    # Workaround mentioned
    assert "public" in section.lower()
