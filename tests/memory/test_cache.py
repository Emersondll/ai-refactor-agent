import os
import pytest
from memory.cache import Cache, sha12


# --- sha12 ---

def test_sha12_returns_12_char_hex():
    result = sha12("some content")
    assert len(result) == 12
    assert all(c in "0123456789abcdef" for c in result)

def test_sha12_deterministic():
    assert sha12("abc") == sha12("abc")

def test_sha12_different_inputs_differ():
    assert sha12("abc") != sha12("xyz")


# --- dep_context ---

def test_dep_context_miss_returns_none(tmp_path):
    c = Cache(str(tmp_path))
    assert c.get_dep_context("nonexistent") is None

def test_dep_context_round_trip(tmp_path):
    c = Cache(str(tmp_path))
    c.set_dep_context("abc123", "// some context")
    assert c.get_dep_context("abc123") == "// some context"

def test_dep_context_persists_across_instances(tmp_path):
    Cache(str(tmp_path)).set_dep_context("abc123", "// persisted")
    assert Cache(str(tmp_path)).get_dep_context("abc123") == "// persisted"

def test_dep_context_empty_string_round_trip(tmp_path):
    c = Cache(str(tmp_path))
    c.set_dep_context("empty", "")
    assert c.get_dep_context("empty") == ""


# --- phase tracking ---

def test_phase_done_false_initially(tmp_path):
    c = Cache(str(tmp_path))
    assert c.is_phase_done("/some/File.java", "01_javadoc") is False

def test_phase_done_after_mark(tmp_path):
    c = Cache(str(tmp_path))
    c.mark_phase_done("/some/File.java", "01_javadoc")
    assert c.is_phase_done("/some/File.java", "01_javadoc") is True

def test_phase_done_other_phase_still_false(tmp_path):
    c = Cache(str(tmp_path))
    c.mark_phase_done("/some/File.java", "01_javadoc")
    assert c.is_phase_done("/some/File.java", "04_nomenclature") is False

def test_phase_done_other_file_still_false(tmp_path):
    c = Cache(str(tmp_path))
    c.mark_phase_done("/some/FileA.java", "01_javadoc")
    assert c.is_phase_done("/some/FileB.java", "01_javadoc") is False

def test_phase_tracking_is_per_run(tmp_path):
    # New instance = blank in-memory state
    Cache(str(tmp_path)).mark_phase_done("/some/File.java", "01_javadoc")
    assert Cache(str(tmp_path)).is_phase_done("/some/File.java", "01_javadoc") is False


# --- project dict ---

def test_project_dict_miss_returns_none(tmp_path):
    assert Cache(str(tmp_path)).get_project_dict() is None

def test_project_dict_round_trip(tmp_path):
    c = Cache(str(tmp_path))
    c.set_project_dict("- CustomerService (com.ex.CustomerService)")
    assert c.get_project_dict() == "- CustomerService (com.ex.CustomerService)"

def test_project_dict_in_memory_after_set(tmp_path):
    c = Cache(str(tmp_path))
    c.set_project_dict("- MyClass")
    assert c.get_project_dict() == "- MyClass"

def test_project_dict_persists_across_instances(tmp_path):
    Cache(str(tmp_path)).set_project_dict("- MyClass (com.ex.MyClass)")
    assert Cache(str(tmp_path)).get_project_dict() == "- MyClass (com.ex.MyClass)"
