import pytest
from unittest.mock import patch, MagicMock


def test_consecutive_timeout_counter_increments():
    """Each call_model timeout increments the module counter."""
    from ai import model
    model.reset_consecutive_timeouts()
    assert model.get_consecutive_timeouts() == 0

    # Fake call_model to simulate timeout (returns None, is_oom=False)
    import requests
    def fake_post(*args, **kwargs):
        raise requests.exceptions.Timeout()
    with patch.object(model.requests, "post", side_effect=fake_post):
        model.call_model("any-model", "prompt", timeout=1)
        assert model.get_consecutive_timeouts() == 1
        model.call_model("any-model", "prompt", timeout=1)
        assert model.get_consecutive_timeouts() == 2


def test_successful_call_resets_counter():
    from ai import model
    model.reset_consecutive_timeouts()
    # Set counter manually
    model._set_consecutive_timeouts_for_test(5)
    assert model.get_consecutive_timeouts() == 5

    # Fake a successful call_model
    class FakeResp:
        status_code = 200
        text = ""
        def json(self):
            return {"response": "```java\nclass X {}\n```"}
    with patch.object(model.requests, "post", return_value=FakeResp()):
        model.call_model("any-model", "prompt", timeout=10)
    assert model.get_consecutive_timeouts() == 0


def test_try_local_agent_aborts_after_threshold():
    """When counter is already >= 2 at the start of an attempt, abort with None."""
    from ai import model
    model._set_consecutive_timeouts_for_test(2)  # threshold met

    # call_model should never be invoked because the guard aborts first
    call_count = []
    def fake_call_model(*args, **kwargs):
        call_count.append(args)
        return ("```java\nclass X {}\n```", False)

    with patch.object(model, "call_model", side_effect=fake_call_model):
        result = model._try_local_agent("recovery", "any-model", "prompt")
    assert result is None
    assert len(call_count) == 0  # nothing actually called


def test_try_local_agent_does_not_abort_below_threshold():
    """When counter is 1, attempts proceed normally."""
    from ai import model
    model._set_consecutive_timeouts_for_test(1)

    def fake_call_model(*args, **kwargs):
        return ("```java\nclass X {}\n```", False)

    with patch.object(model, "call_model", side_effect=fake_call_model):
        result = model._try_local_agent("recovery", "any-model", "prompt")
    assert result is not None


def test_reset_function_zeros_counter():
    from ai import model
    model._set_consecutive_timeouts_for_test(10)
    model.reset_consecutive_timeouts()
    assert model.get_consecutive_timeouts() == 0
