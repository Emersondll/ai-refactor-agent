import pytest
from unittest.mock import patch
import os


def test_resolve_phase_file_returns_path_for_known_skill(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    phase_dir = tmp_path / "phases" / "solid"
    phase_dir.mkdir(parents=True)
    (phase_dir / "07_solid.md").write_text("# solid rules")

    from agent.skill_catalog import resolve_phase_file
    result = resolve_phase_file("solid")
    assert result is not None
    assert result.endswith("07_solid.md")


def test_resolve_phase_file_returns_none_for_unknown_skill():
    from agent.skill_catalog import resolve_phase_file
    assert resolve_phase_file("nonexistent-skill") is None


def test_is_reactive_true_for_fix_build():
    from agent.skill_catalog import is_reactive
    assert is_reactive("fix-build") is True


def test_is_reactive_false_for_phase_skill():
    from agent.skill_catalog import is_reactive
    assert is_reactive("solid") is False


def test_is_terminal_true_for_done():
    from agent.skill_catalog import is_terminal
    assert is_terminal("done") is True


def test_is_terminal_false_for_others():
    from agent.skill_catalog import is_terminal
    assert is_terminal("solid") is False
    assert is_terminal("fix-build") is False


def test_catalog_for_prompt_contains_all_skills():
    from agent.skill_catalog import catalog_for_prompt, SKILL_DESCRIPTIONS
    prompt = catalog_for_prompt()
    for skill_id in SKILL_DESCRIPTIONS:
        assert skill_id in prompt


def test_all_phase_skill_ids_returns_list():
    from agent.skill_catalog import all_phase_skill_ids
    ids = all_phase_skill_ids()
    assert "solid" in ids
    assert "extract-method" in ids
    assert len(ids) == 24  # 12 phase + 12 community
