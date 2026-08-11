from guardrails.context_watch import (
    CONTEXT_WARN_TOKENS,
    should_warn_context_size,
    context_size_warning_text,
)


def test_warn_threshold_constant_is_100000():
    assert CONTEXT_WARN_TOKENS == 100_000


def test_below_threshold_does_not_warn():
    assert should_warn_context_size(50_000) is False


def test_at_threshold_warns():
    assert should_warn_context_size(100_000) is True


def test_above_threshold_warns():
    assert should_warn_context_size(150_000) is True


def test_custom_threshold_overrides_default():
    assert should_warn_context_size(5_000, threshold=1_000) is True
    assert should_warn_context_size(500, threshold=1_000) is False


def test_warning_text_includes_formatted_token_count():
    text = context_size_warning_text(123456)
    assert "123,456" in text
    assert "新会话" in text
