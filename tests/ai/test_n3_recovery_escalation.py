import pytest
from unittest.mock import patch, MagicMock


def test_escalates_to_model_struct_when_recovery_fails():
    """When MODEL_RECOVERY (_try_local_agent) returns None, the function should
    try MODEL_STRUCT as a fallback BEFORE returning None."""
    from ai import model
    calls = []

    def fake_try_local(agent, model_name, prompt, **kwargs):
        calls.append(model_name)
        return None  # always fail

    with patch.object(model, "_try_local_agent", side_effect=fake_try_local):
        # also stub _try_claude so it doesn't trigger
        with patch.object(model, "_try_claude", return_value=None):
            with patch.object(model, "USE_CLAUDE_FALLBACK", False):
                result = model.call_ai_with_correction(
                    original="class X {}", rules="", mode="test",
                    file_name="X.java", file_path="/tmp/X.java",
                    bad_output="invalid", error_reason="some error",
                )
    # Two distinct models tried: MODEL_RECOVERY (14b) then MODEL_STRUCT (7b)
    assert len(calls) == 2
    assert calls[0] == model.MODEL_RECOVERY
    assert calls[1] == model.MODEL_STRUCT
    assert result is None  # both failed


def test_does_not_escalate_when_recovery_succeeds():
    """If MODEL_RECOVERY returns a non-None result, no escalation."""
    from ai import model
    calls = []

    def fake_try_local(agent, model_name, prompt, **kwargs):
        calls.append(model_name)
        return "```java\nclass X {}\n```"  # success on first call

    with patch.object(model, "_try_local_agent", side_effect=fake_try_local):
        with patch.object(model, "_try_claude", return_value=None):
            with patch.object(model, "USE_CLAUDE_FALLBACK", False):
                result = model.call_ai_with_correction(
                    original="class X {}", rules="", mode="test",
                    file_name="X.java", file_path="/tmp/X.java",
                    bad_output="invalid", error_reason="some error",
                )
    assert calls == [model.MODEL_RECOVERY]  # MODEL_STRUCT not called
    assert result is not None


def test_escalation_uses_same_prompt():
    """Both calls receive the same correction_prompt — no re-build."""
    from ai import model
    prompts_seen: list[str] = []

    def fake_try_local(agent, model_name, prompt, **kwargs):
        prompts_seen.append(prompt[:50])
        return None

    with patch.object(model, "_try_local_agent", side_effect=fake_try_local):
        with patch.object(model, "_try_claude", return_value=None):
            with patch.object(model, "USE_CLAUDE_FALLBACK", False):
                model.call_ai_with_correction(
                    original="class X {}", rules="", mode="test",
                    file_name="X.java", file_path="/tmp/X.java",
                    bad_output="invalid", error_reason="reason",
                )
    assert len(prompts_seen) == 2
    assert prompts_seen[0] == prompts_seen[1]


def test_skips_escalation_if_models_equal():
    """Defensive: if MODEL_RECOVERY == MODEL_STRUCT (user override), skip the
    second call — no point retrying the same model."""
    from ai import model
    calls = []

    def fake_try_local(agent, model_name, prompt, **kwargs):
        calls.append(model_name)
        return None

    # Force MODEL_STRUCT == MODEL_RECOVERY for this test
    with patch.object(model, "MODEL_STRUCT", model.MODEL_RECOVERY):
        with patch.object(model, "_try_local_agent", side_effect=fake_try_local):
            with patch.object(model, "_try_claude", return_value=None):
                with patch.object(model, "USE_CLAUDE_FALLBACK", False):
                    model.call_ai_with_correction(
                        original="class X {}", rules="", mode="test",
                        file_name="X.java", file_path="/tmp/X.java",
                        bad_output="invalid", error_reason="reason",
                    )
    # Only ONE call (no escalation since the models are identical)
    assert len(calls) == 1
