import pytest
from unittest.mock import patch, MagicMock


def _mock_claude(response_text: str):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=response_text)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg
    return mock_client


def test_call_planner_returns_plan_list(monkeypatch):
    monkeypatch.setattr("agent.planner.CLAUDE_API_KEY", "fake-key")
    valid_response = '{"reasoning": "apply solid", "plan": [{"skill": "solid", "file": "Foo.java", "reason": "pending"}]}'
    with patch("agent.planner.anthropic.Anthropic", return_value=_mock_claude(valid_response)):
        from agent.planner import call_planner
        plan = call_planner({"build": "green", "files": [], "skills_available": []})
    assert isinstance(plan, list)
    assert plan[0]["skill"] == "solid"


def test_call_planner_handles_json_parse_error(monkeypatch):
    monkeypatch.setattr("agent.planner.CLAUDE_API_KEY", "fake-key")
    with patch("agent.planner.anthropic.Anthropic", return_value=_mock_claude("not json at all")):
        from agent.planner import call_planner
        plan = call_planner({"build": "green", "files": [], "skills_available": []})
    assert plan[0]["skill"] == "done"


def test_call_planner_handles_missing_api_key(monkeypatch):
    monkeypatch.setattr("agent.planner.CLAUDE_API_KEY", None)
    from agent.planner import call_planner
    plan = call_planner({"build": "green", "files": [], "skills_available": []})
    assert plan[0]["skill"] == "done"


def test_call_planner_strips_markdown_fences(monkeypatch):
    monkeypatch.setattr("agent.planner.CLAUDE_API_KEY", "fake-key")
    fenced = '```json\n{"reasoning": "r", "plan": [{"skill": "done", "file": null, "reason": "ok"}]}\n```'
    with patch("agent.planner.anthropic.Anthropic", return_value=_mock_claude(fenced)):
        from agent.planner import call_planner
        plan = call_planner({"build": "green", "files": [], "skills_available": []})
    assert plan[0]["skill"] == "done"
