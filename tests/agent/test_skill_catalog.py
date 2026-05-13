import pytest
import yaml


def test_load_skill_config_returns_dict_for_known_skill(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    configs_dir = tmp_path / "phases" / "configs"
    configs_dir.mkdir(parents=True)
    cfg = {
        "skill": "final-keywords",
        "tool": "openrewrite",
        "artifact_coordinates": ["org.openrewrite.recipe:rewrite-static-analysis:RELEASE"],
        "recipes": ["org.openrewrite.staticanalysis.FinalizeLocalVariables"],
        "review_criteria": "Only add final.",
    }
    (configs_dir / "03_final-keywords.yml").write_text(yaml.dump(cfg))

    import importlib
    import agent.skill_catalog as sc
    importlib.reload(sc)
    result = sc.load_skill_config("final-keywords")
    assert result is not None
    assert result["tool"] == "openrewrite"
    assert result["skill"] == "final-keywords"


def test_load_skill_config_returns_none_for_unknown_skill():
    from agent.skill_catalog import load_skill_config
    assert load_skill_config("nonexistent-skill") is None


def test_is_reactive_true_for_fix_build():
    from agent.skill_catalog import is_reactive
    assert is_reactive("fix-build") is True


def test_is_reactive_false_for_phase_skill():
    from agent.skill_catalog import is_reactive
    assert is_reactive("final-keywords") is False


def test_is_terminal_true_for_done():
    from agent.skill_catalog import is_terminal
    assert is_terminal("done") is True


def test_is_terminal_false_for_others():
    from agent.skill_catalog import is_terminal
    assert is_terminal("final-keywords") is False
    assert is_terminal("fix-build") is False


def test_all_phase_skill_ids_returns_8_skills():
    from agent.skill_catalog import all_phase_skill_ids
    ids = all_phase_skill_ids()
    assert "clean-imports" in ids
    assert "final-keywords" in ids
    assert "static-analysis" in ids
    assert len(ids) == 8


def test_catalog_for_prompt_contains_all_skills():
    from agent.skill_catalog import catalog_for_prompt, SKILL_DESCRIPTIONS
    prompt = catalog_for_prompt()
    for skill_id in SKILL_DESCRIPTIONS:
        assert skill_id in prompt
