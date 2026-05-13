import pytest
from unittest.mock import patch


def test_review_diff_skip_when_diff_is_empty():
    from java.llm_reviewer import review_diff
    result = review_diff("", "some criteria", "model-name")
    assert result == "SKIP"


def test_review_diff_skip_when_diff_is_whitespace_only():
    from java.llm_reviewer import review_diff
    result = review_diff("   \n  ", "some criteria", "model-name")
    assert result == "SKIP"


def test_review_diff_returns_approve():
    with patch("java.llm_reviewer.call_model") as mock:
        mock.return_value = ("APPROVE: diff only adds final keywords", False)
        from java.llm_reviewer import review_diff
        result = review_diff("diff content here", "criteria text", "model-name")
    assert result == "APPROVE"


def test_review_diff_returns_reject():
    with patch("java.llm_reviewer.call_model") as mock:
        mock.return_value = ("REJECT: logic was changed", False)
        from java.llm_reviewer import review_diff
        result = review_diff("diff content here", "criteria text", "model-name")
    assert result == "REJECT"


def test_review_diff_approves_on_unparseable_response():
    with patch("java.llm_reviewer.call_model") as mock:
        mock.return_value = ("I think this looks fine but I cannot decide", False)
        from java.llm_reviewer import review_diff
        result = review_diff("diff content here", "criteria text", "model-name")
    assert result == "APPROVE"


def test_review_diff_approves_when_model_returns_none():
    with patch("java.llm_reviewer.call_model") as mock:
        mock.return_value = (None, False)
        from java.llm_reviewer import review_diff
        result = review_diff("diff content here", "criteria text", "model-name")
    assert result == "APPROVE"


def test_review_diff_case_insensitive_approve():
    with patch("java.llm_reviewer.call_model") as mock:
        mock.return_value = ("approve: looks good", False)
        from java.llm_reviewer import review_diff
        result = review_diff("diff", "criteria", "model")
    assert result == "APPROVE"


def test_build_prompt_includes_criteria_and_diff():
    from java.llm_reviewer import _build_prompt
    prompt = _build_prompt("MY_DIFF_CONTENT", "MY_CRITERIA")
    assert "MY_DIFF_CONTENT" in prompt
    assert "MY_CRITERIA" in prompt
    assert "APPROVE" in prompt
    assert "REJECT" in prompt
