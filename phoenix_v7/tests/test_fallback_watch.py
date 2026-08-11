from phoenix_v7.guardrails.fallback_watch import fallback_transition_text


def test_first_ever_check_no_notice():
    result = fallback_transition_text(
        previous_on_fallback=None, current_on_fallback=False, model="gpt-5.4",
    )
    assert result is None


def test_first_ever_check_no_notice_even_if_already_on_fallback():
    result = fallback_transition_text(
        previous_on_fallback=None, current_on_fallback=True, model="deepseek-chat",
    )
    assert result is None


def test_no_notice_when_staying_on_primary():
    result = fallback_transition_text(
        previous_on_fallback=False, current_on_fallback=False, model="gpt-5.4",
    )
    assert result is None


def test_no_notice_when_staying_on_fallback():
    result = fallback_transition_text(
        previous_on_fallback=True, current_on_fallback=True, model="deepseek-chat",
    )
    assert result is None


def test_notice_when_falling_back_includes_model_name():
    result = fallback_transition_text(
        previous_on_fallback=False, current_on_fallback=True, model="deepseek-chat",
    )
    assert result is not None
    assert "deepseek-chat" in result
    assert "兜底" in result


def test_notice_when_falling_back_without_model_name():
    result = fallback_transition_text(
        previous_on_fallback=False, current_on_fallback=True, model="",
    )
    assert result is not None
    assert "()" not in result
    assert "（）" not in result


def test_notice_when_recovering_to_primary():
    result = fallback_transition_text(
        previous_on_fallback=True, current_on_fallback=False, model="gpt-5.4",
    )
    assert result is not None
    assert "恢复" in result
    assert "切回" in result
