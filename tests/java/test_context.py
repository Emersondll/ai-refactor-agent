import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from memory.cache import Cache


def make_cache(tmp_path):
    return Cache(str(tmp_path))


# --- _extract_simplified_header ---

def test_header_includes_public_method_signature():
    from java.dep_context import _extract_simplified_header
    code = """\
package com.ex;
public class MyService {
    private String name;
    public String getName() {
        return name;
    }
    private void helper() {}
}"""
    header = _extract_simplified_header(code, "com.ex.MyService")
    assert "getName()" in header
    assert "private String name" not in header
    assert "helper" not in header

def test_header_excludes_private_fields():
    from java.dep_context import _extract_simplified_header
    code = """\
package com.ex;
public class OrderService {
    private final OrderRepository repo;
    private int count;
    public void save(Order o) { repo.save(o); }
}"""
    header = _extract_simplified_header(code, "com.ex.OrderService")
    assert "private final OrderRepository" not in header
    assert "private int count" not in header

def test_header_includes_class_declaration():
    from java.dep_context import _extract_simplified_header
    code = "package com.ex;\npublic class Foo {\n    public void run() {}\n}"
    header = _extract_simplified_header(code, "com.ex.Foo")
    assert "class Foo" in header or "Foo" in header


# --- get_dependency_context cache behavior ---

def test_dep_context_cache_hit_avoids_rebuild(tmp_path):
    from java.dep_context import get_dependency_context
    from memory.cache import sha12

    cache = make_cache(tmp_path)
    file_code = "package com.ex;\nimport com.ex.MyDep;\npublic class A {}"
    file_hash = sha12(file_code)

    cached_value = "// CACHED CONTEXT"
    cache.set_dep_context(file_hash, cached_value)

    with patch("java.context._build_dep_context") as mock_build:
        result = get_dependency_context(file_code, "/any/repo", cache=cache)
        mock_build.assert_not_called()
    assert result == cached_value

def test_dep_context_cache_miss_calls_build_and_stores(tmp_path):
    from java.dep_context import get_dependency_context
    from memory.cache import sha12

    cache = make_cache(tmp_path)
    file_code = "package com.ex;\npublic class B {}"
    file_hash = sha12(file_code)

    with patch("config.USE_RAG_CONTEXT", False), \
         patch("java.context._build_dep_context", return_value="// BUILT") as mock_build:
        result = get_dependency_context(file_code, "/any/repo", cache=cache)
        mock_build.assert_called_once()

    assert result == "// BUILT"
    assert cache.get_dep_context(file_hash) == "// BUILT"

def test_dep_context_no_cache_calls_build_directly(tmp_path):
    from java.dep_context import get_dependency_context

    with patch("config.USE_RAG_CONTEXT", False), \
         patch("java.context._build_dep_context", return_value="// NO CACHE") as mock_build:
        result = get_dependency_context("public class C {}", "/any/repo", cache=None)
        mock_build.assert_called_once()
    assert result == "// NO CACHE"
