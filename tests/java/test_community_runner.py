import pytest
from unittest.mock import patch


def test_run_skill_openrewrite_returns_changed_true_when_diff_nonempty():
    config = {
        "tool": "openrewrite",
        "artifact_coordinates": ["org.openrewrite.recipe:rewrite-static-analysis:RELEASE"],
        "recipes": ["org.openrewrite.staticanalysis.FinalizeLocalVariables"],
    }
    diff_output = "diff --git a/Foo.java b/Foo.java\n+final int x = 1;"
    with patch("java.community_runner.run_cmd") as mock_run:
        mock_run.side_effect = [
            (0, "", ""),           # _run_openrewrite
            (0, diff_output, ""),  # _get_diff
        ]
        from java.community_runner import run_skill
        changed, diff = run_skill(config, "/repo")
    assert changed is True
    assert "final int x" in diff


def test_run_skill_openrewrite_returns_changed_false_when_diff_empty():
    config = {
        "tool": "openrewrite",
        "artifact_coordinates": [],
        "recipes": ["org.openrewrite.java.RemoveUnusedImports"],
    }
    with patch("java.community_runner.run_cmd") as mock_run:
        mock_run.side_effect = [
            (0, "", ""),  # _run_openrewrite
            (0, "", ""),  # _get_diff (empty diff)
        ]
        from java.community_runner import run_skill
        changed, diff = run_skill(config, "/repo")
    assert changed is False
    assert diff == ""


def test_run_skill_gjf_returns_changed_true_when_diff_nonempty(tmp_path):
    config = {"tool": "google-java-format"}
    java_file = tmp_path / "src" / "main" / "java" / "Foo.java"
    java_file.parent.mkdir(parents=True)
    java_file.write_text("class Foo {}")

    diff_output = "diff --git a/Foo.java b/Foo.java\n-class Foo{}\n+class Foo {}"
    with patch("java.community_runner.run_cmd") as mock_run:
        mock_run.side_effect = [
            (0, "", ""),           # _run_google_java_format
            (0, diff_output, ""),  # _get_diff
        ]
        from java.community_runner import run_skill
        changed, diff = run_skill(config, str(tmp_path))
    assert changed is True


def test_run_skill_unknown_tool_returns_changed_false():
    config = {"tool": "unknown-tool"}
    from java.community_runner import run_skill
    changed, diff = run_skill(config, "/repo")
    assert changed is False
    assert diff == ""


def test_run_openrewrite_includes_artifact_coords_in_cmd():
    with patch("java.community_runner.run_cmd") as mock_run:
        mock_run.return_value = (0, "", "")
        from java.community_runner import _run_openrewrite
        _run_openrewrite(
            "/repo",
            ["org.openrewrite.recipe:rewrite-static-analysis:RELEASE"],
            ["org.openrewrite.staticanalysis.FinalizeLocalVariables"],
        )
    cmd_used = mock_run.call_args[0][0]
    assert "rewrite.recipeArtifactCoordinates" in cmd_used
    assert "rewrite-static-analysis" in cmd_used
    assert "FinalizeLocalVariables" in cmd_used


def test_run_openrewrite_omits_artifact_coords_when_empty():
    with patch("java.community_runner.run_cmd") as mock_run:
        mock_run.return_value = (0, "", "")
        from java.community_runner import _run_openrewrite
        _run_openrewrite("/repo", [], ["org.openrewrite.java.RemoveUnusedImports"])
    cmd_used = mock_run.call_args[0][0]
    assert "recipeArtifactCoordinates" not in cmd_used
    assert "RemoveUnusedImports" in cmd_used


def test_get_diff_returns_stdout_on_success():
    with patch("java.community_runner.run_cmd") as mock_run:
        mock_run.return_value = (0, "some diff output", "")
        from java.community_runner import _get_diff
        result = _get_diff("/repo")
    assert result == "some diff output"


def test_get_diff_returns_empty_string_on_failure():
    with patch("java.community_runner.run_cmd") as mock_run:
        mock_run.return_value = (1, "", "error")
        from java.community_runner import _get_diff
        result = _get_diff("/repo")
    assert result == ""
