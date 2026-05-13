import pytest
from unittest.mock import patch, MagicMock


def _mock_claude(response_text: str):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=response_text)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg
    return mock_client


def _mock_ollama(response_text: str, status_code: int = 200):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {"response": response_text}
    return mock_resp


# --- Claude planner tests ---

def test_call_planner_returns_plan_list(monkeypatch):
    monkeypatch.setattr("agent.planner.CLAUDE_API_KEY", "fake-key")
    monkeypatch.setattr("agent.planner.USE_LOCAL_PLANNER", False)
    valid_response = '{"reasoning": "apply solid", "plan": [{"skill": "solid", "file": "Foo.java", "reason": "pending"}]}'
    with patch("agent.planner.anthropic.Anthropic", return_value=_mock_claude(valid_response)):
        from agent.planner import call_planner
        plan = call_planner({"build": "green", "files": [], "skills_available": []})
    assert isinstance(plan, list)
    assert plan[0]["skill"] == "solid"


def test_call_planner_strips_markdown_fences(monkeypatch):
    monkeypatch.setattr("agent.planner.CLAUDE_API_KEY", "fake-key")
    monkeypatch.setattr("agent.planner.USE_LOCAL_PLANNER", False)
    fenced = '```json\n{"reasoning": "r", "plan": [{"skill": "done", "file": null, "reason": "ok"}]}\n```'
    with patch("agent.planner.anthropic.Anthropic", return_value=_mock_claude(fenced)):
        from agent.planner import call_planner
        plan = call_planner({"build": "green", "files": [], "skills_available": []})
    assert plan[0]["skill"] == "done"


def test_call_planner_falls_back_to_local_on_json_error(monkeypatch):
    monkeypatch.setattr("agent.planner.CLAUDE_API_KEY", "fake-key")
    monkeypatch.setattr("agent.planner.USE_LOCAL_PLANNER", False)
    local_resp = '{"reasoning": "local", "plan": [{"skill": "done", "file": null, "reason": "ok"}]}'
    with patch("agent.planner.anthropic.Anthropic", return_value=_mock_claude("not json")), \
         patch("agent.planner.requests.post", return_value=_mock_ollama(local_resp)):
        from agent.planner import call_planner
        plan = call_planner({"build": "green", "files": [], "skills_available": []})
    assert plan[0]["skill"] == "done"


def test_call_planner_falls_back_to_local_on_missing_api_key(monkeypatch):
    monkeypatch.setattr("agent.planner.CLAUDE_API_KEY", None)
    monkeypatch.setattr("agent.planner.USE_LOCAL_PLANNER", False)
    local_resp = '{"reasoning": "local", "plan": [{"skill": "solid", "file": "Foo.java", "reason": "pending"}]}'
    with patch("agent.planner.requests.post", return_value=_mock_ollama(local_resp)):
        from agent.planner import call_planner
        plan = call_planner({"build": "green", "files": [], "skills_available": []})
    assert plan[0]["skill"] == "solid"


# --- Local planner tests ---

def test_local_planner_returns_plan_list(monkeypatch):
    monkeypatch.setattr("agent.planner.USE_LOCAL_PLANNER", True)
    local_resp = '{"reasoning": "use local", "plan": [{"skill": "solid", "file": "Bar.java", "reason": "pending"}]}'
    with patch("agent.planner.requests.post", return_value=_mock_ollama(local_resp)):
        from agent.planner import call_planner
        plan = call_planner({"build": "green", "files": [], "skills_available": []})
    assert plan[0]["skill"] == "solid"
    assert plan[0]["file"] == "Bar.java"


def test_local_planner_extracts_json_from_surrounding_text(monkeypatch):
    monkeypatch.setattr("agent.planner.USE_LOCAL_PLANNER", True)
    messy = 'Sure! Here is the plan:\n{"reasoning": "r", "plan": [{"skill": "done", "file": null, "reason": "ok"}]}\nHope that helps!'
    with patch("agent.planner.requests.post", return_value=_mock_ollama(messy)):
        from agent.planner import call_planner
        plan = call_planner({"build": "green", "files": [], "skills_available": []})
    assert plan[0]["skill"] == "done"


def test_local_planner_returns_done_on_ollama_error(monkeypatch):
    monkeypatch.setattr("agent.planner.USE_LOCAL_PLANNER", True)
    with patch("agent.planner.requests.post", return_value=_mock_ollama("", status_code=500)):
        from agent.planner import call_planner
        plan = call_planner({"build": "green", "files": [], "skills_available": []})
    assert plan[0]["skill"] == "done"


def test_local_planner_returns_done_on_unparseable_response(monkeypatch):
    monkeypatch.setattr("agent.planner.USE_LOCAL_PLANNER", True)
    with patch("agent.planner.requests.post", return_value=_mock_ollama("I cannot decide right now.")):
        from agent.planner import call_planner
        plan = call_planner({"build": "green", "files": [], "skills_available": []})
    assert plan[0]["skill"] == "done"
