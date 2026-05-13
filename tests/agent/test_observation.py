import pytest
from unittest.mock import MagicMock, patch
import os


def _make_cache(phases_done: dict) -> MagicMock:
    cache = MagicMock()
    cache.is_phase_done.side_effect = lambda f, p: phases_done.get((f, p), False)
    return cache


def test_observation_has_required_keys(tmp_path):
    cache = _make_cache({})
    with patch("agent.observation.get_java_files", return_value=[]), \
         patch("agent.observation.get_failed_tracker") as mock_ft:
        mock_ft.return_value._entries = []
        mock_ft.return_value.get_build_failure_count.return_value = 0
        from agent.observation import build_observation
        obs = build_observation(str(tmp_path), cache, cycle=1, max_cycles=20)

    for key in ("project", "build", "cycle", "max_cycles", "files",
                "failed_files", "last_build_error", "skills_available"):
        assert key in obs, f"Missing key: {key}"


def test_observation_build_green_by_default(tmp_path):
    cache = _make_cache({})
    with patch("agent.observation.get_java_files", return_value=[]), \
         patch("agent.observation.get_failed_tracker") as mock_ft:
        mock_ft.return_value._entries = []
        mock_ft.return_value.get_build_failure_count.return_value = 0
        from agent.observation import build_observation
        obs = build_observation(str(tmp_path), cache, cycle=1, max_cycles=20, build_ok=True)

    assert obs["build"] == "green"


def test_observation_build_red_when_passed(tmp_path):
    cache = _make_cache({})
    with patch("agent.observation.get_java_files", return_value=[]), \
         patch("agent.observation.get_failed_tracker") as mock_ft:
        mock_ft.return_value._entries = []
        mock_ft.return_value.get_build_failure_count.return_value = 0
        from agent.observation import build_observation
        obs = build_observation(str(tmp_path), cache, cycle=2, max_cycles=20,
                                build_ok=False, last_build_error="[ERROR] cannot find symbol")

    assert obs["build"] == "red"
    assert "cannot find symbol" in obs["last_build_error"]


def test_observation_phases_applied_from_cache(tmp_path):
    java_file = tmp_path / "Foo.java"
    java_file.write_text("public class Foo {}")
    cache = _make_cache({(str(java_file), "final-keywords"): True})
    with patch("agent.observation.get_failed_tracker") as mock_ft:
        mock_ft.return_value._entries = []
        mock_ft.return_value.get_build_failure_count.return_value = 0
        with patch("agent.observation.get_java_files", return_value=[str(java_file)]):
            from agent.observation import build_observation
            obs = build_observation(str(tmp_path), cache, cycle=1, max_cycles=20)

    assert len(obs["files"]) == 1
    assert "final-keywords" in obs["files"][0]["phases_applied"]
    assert "final-keywords" not in obs["files"][0]["phases_pending"]
