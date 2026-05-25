import pytest
from java.context import _extract_simplified_header


CLASS_WITH_PRIVATE = '''package com.example;

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

    void helperPackagePrivate() { /* same package */ }
}'''


def test_extracts_public_methods():
    out = _extract_simplified_header(CLASS_WITH_PRIVATE)
    assert "performAction" in out
    assert "Service(" in out  # constructor preserved


def test_excludes_private_methods():
    out = _extract_simplified_header(CLASS_WITH_PRIVATE)
    assert "validateInput" not in out
    assert "formatKey" not in out


def test_keeps_protected_methods():
    out = _extract_simplified_header(CLASS_WITH_PRIVATE)
    assert "onAction" in out


def test_keeps_package_private_methods():
    """Same package as test → package-private accessible. Don't filter."""
    out = _extract_simplified_header(CLASS_WITH_PRIVATE)
    assert "helperPackagePrivate" in out


def test_private_static_methods_excluded():
    """formatKey is private static — must still be filtered."""
    out = _extract_simplified_header(CLASS_WITH_PRIVATE)
    assert "formatKey" not in out


def test_constructor_with_private_field_init_still_included():
    """The constructor sets a private field — constructor itself is public, must be kept."""
    out = _extract_simplified_header(CLASS_WITH_PRIVATE)
    assert "Service(" in out


def test_enum_constants_preserved():
    """Existing behavior for enums (constants listed) is not broken."""
    enum_code = '''public enum Color {
    RED("ff0000"),
    GREEN("00ff00"),
    BLUE("0000ff");

    private final String hex;

    Color(String hex) {
        this.hex = hex;
    }

    public String getHex() { return hex; }
}'''
    out = _extract_simplified_header(enum_code)
    assert "RED" in out
    assert "GREEN" in out
    assert "BLUE" in out
    assert "getHex" in out
