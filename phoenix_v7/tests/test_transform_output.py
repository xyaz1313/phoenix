from types import SimpleNamespace

import phoenix_v7
from privacy.warning import PRIVACY_WARNING_TEXT

def _reset_state():
    phoenix_v7._last_tier_by_session.clear()
    phoenix_v7._current_provider_by_session.clear()
    phoenix_v7._privacy_flagged_by_session.clear()
    phoenix_v7._privacy_warned_sessions.clear()

# ---- _check_privacy_warning 单独测试 ----

def test_check_privacy_warning_appends_when_flagged_and_not_local_and_unwarned():
    _reset_state()
    phoenix_v7._privacy_flagged_by_session["s1"] = True
    phoenix_v7._current_provider_by_session["s1"] = "nous"
    result = phoenix_v7._check_privacy_warning("原始回复内容", session_id="s1")
    assert result is not None
    assert result.startswith("原始回复内容")
    assert PRIVACY_WARNING_TEXT in result
    assert "s1" in phoenix_v7._privacy_warned_sessions

def test_check_privacy_warning_skips_on_unsupported_platform(monkeypatch):
    # 真实事故：Windows 用户装完 v7.5.0 看到这条提醒引导他们 /model turbofieldfare，
    # 但这个 provider 在非 Mac 平台根本不存在（turbofieldfare 是 MLX/Apple Silicon
    # 专属）。非 Mac 平台上这条提醒不该出现，即使敏感词命中、即使还没提醒过。
    _reset_state()
    monkeypatch.setattr(phoenix_v7, "is_turbofieldfare_supported_platform", lambda: False)
    phoenix_v7._privacy_flagged_by_session["s_win"] = True
    phoenix_v7._current_provider_by_session["s_win"] = "nous"
    result = phoenix_v7._check_privacy_warning("原始回复内容", session_id="s_win")
    assert result is None
    assert "s_win" not in phoenix_v7._privacy_warned_sessions

def test_check_privacy_warning_skips_when_not_flagged():
    _reset_state()
    phoenix_v7._privacy_flagged_by_session["s2"] = False
    phoenix_v7._current_provider_by_session["s2"] = "nous"
    result = phoenix_v7._check_privacy_warning("原始回复内容", session_id="s2")
    assert result is None

def test_check_privacy_warning_skips_when_already_on_turbofieldfare():
    _reset_state()
    phoenix_v7._privacy_flagged_by_session["s3"] = True
    phoenix_v7._current_provider_by_session["s3"] = "turbofieldfare"
    result = phoenix_v7._check_privacy_warning("原始回复内容", session_id="s3")
    assert result is None

def test_check_privacy_warning_skips_when_already_warned_this_session():
    _reset_state()
    phoenix_v7._privacy_flagged_by_session["s4"] = True
    phoenix_v7._current_provider_by_session["s4"] = "nous"
    phoenix_v7._privacy_warned_sessions.add("s4")
    result = phoenix_v7._check_privacy_warning("原始回复内容", session_id="s4")
    assert result is None

def test_check_privacy_warning_handles_missing_session_id():
    _reset_state()
    result = phoenix_v7._check_privacy_warning("原始回复内容", session_id="")
    assert result is None

# 存档点提醒的判定逻辑已经从"事后追加到回复文本"（_check_checkpoint_reminder，
# 挂在 transform_llm_output）搬到"事前直接拦截工具调用"（_guard_tool，挂在
# pre_tool_call），相关测试见 tests/test_guard_tool_loop.py。这里不再测
# _transform_output 对 checkpoint 的处理，因为它已经不做这件事了。

# ---- _transform_output 分发函数测试（合并幻觉核验+隐私提醒） ----

def _fake_client(content: str):
    def create(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

def test_transform_output_empty_response_returns_none():
    _reset_state()
    assert phoenix_v7._transform_output(response_text="", session_id="s5") is None

def test_transform_output_no_issues_returns_none(monkeypatch):
    _reset_state()
    phoenix_v7._last_tier_by_session["s6"] = "l1_daily"  # 低档位，幻觉核验直接跳过
    phoenix_v7._privacy_flagged_by_session["s6"] = False
    phoenix_v7._current_provider_by_session["s6"] = "nous"
    result = phoenix_v7._transform_output(response_text="正常回复", session_id="s6", model="z-ai/glm-5.2")
    assert result is None

def test_transform_output_privacy_only_preserves_original_text():
    _reset_state()
    phoenix_v7._last_tier_by_session["s7"] = "l1_daily"
    phoenix_v7._privacy_flagged_by_session["s7"] = True
    phoenix_v7._current_provider_by_session["s7"] = "nous"
    result = phoenix_v7._transform_output(
        response_text="这是模型的真实回复内容", session_id="s7", model="z-ai/glm-5.2",
    )
    assert result is not None
    assert "这是模型的真实回复内容" in result
    assert PRIVACY_WARNING_TEXT in result

def test_transform_output_hallucination_and_privacy_both_fire(monkeypatch):
    # l3_critical + get_text_auxiliary_client 返回一个会判"ISSUE"的假客户端 + 隐私命中
    # 两者都要生效：幻觉核验的前缀 + 原文 + 隐私提醒，全部在同一个返回字符串里。
    _reset_state()
    phoenix_v7._last_tier_by_session["s8"] = "l3_critical"
    phoenix_v7._privacy_flagged_by_session["s8"] = True
    phoenix_v7._current_provider_by_session["s8"] = "nous"

    def fake_get_client(task=None):
        return _fake_client("ISSUE: 这里的数字看起来是编造的"), "verifier-model"

    monkeypatch.setattr(phoenix_v7, "get_text_auxiliary_client", fake_get_client)

    result = phoenix_v7._transform_output(
        response_text="原始回复内容一字不改", session_id="s8", model="z-ai/glm-5.2",
    )
    assert result is not None
    assert "原始回复内容一字不改" in result
    assert "这里的数字看起来是编造的" in result
    assert PRIVACY_WARNING_TEXT in result


def test_transform_output_warns_when_context_size_crosses_threshold(monkeypatch):
    _reset_state()
    phoenix_v7._prompt_tokens_by_session.clear()
    phoenix_v7._context_size_warned_sessions.clear()
    phoenix_v7._last_tier_by_session["s-ctx1"] = "l1_daily"
    phoenix_v7._privacy_flagged_by_session["s-ctx1"] = False
    phoenix_v7._current_provider_by_session["s-ctx1"] = "nous"
    phoenix_v7._prompt_tokens_by_session["s-ctx1"] = 150_000
    result = phoenix_v7._transform_output(response_text="正常回复", session_id="s-ctx1", model="z-ai/glm-5.2")
    assert result is not None
    assert "150,000" in result


def test_transform_output_does_not_warn_below_threshold(monkeypatch):
    _reset_state()
    phoenix_v7._prompt_tokens_by_session.clear()
    phoenix_v7._context_size_warned_sessions.clear()
    phoenix_v7._last_tier_by_session["s-ctx2"] = "l1_daily"
    phoenix_v7._privacy_flagged_by_session["s-ctx2"] = False
    phoenix_v7._current_provider_by_session["s-ctx2"] = "nous"
    phoenix_v7._prompt_tokens_by_session["s-ctx2"] = 5_000
    result = phoenix_v7._transform_output(response_text="正常回复", session_id="s-ctx2", model="z-ai/glm-5.2")
    assert result is None


def test_transform_output_only_warns_once_per_session(monkeypatch):
    _reset_state()
    phoenix_v7._prompt_tokens_by_session.clear()
    phoenix_v7._context_size_warned_sessions.clear()
    phoenix_v7._last_tier_by_session["s-ctx3"] = "l1_daily"
    phoenix_v7._privacy_flagged_by_session["s-ctx3"] = False
    phoenix_v7._current_provider_by_session["s-ctx3"] = "nous"
    phoenix_v7._prompt_tokens_by_session["s-ctx3"] = 150_000
    first = phoenix_v7._transform_output(response_text="正常回复", session_id="s-ctx3", model="z-ai/glm-5.2")
    assert first is not None
    second = phoenix_v7._transform_output(response_text="第二轮回复", session_id="s-ctx3", model="z-ai/glm-5.2")
    assert second is None


def test_record_usage_tracks_prompt_tokens():
    phoenix_v7._prompt_tokens_by_session.clear()
    phoenix_v7._record_usage(session_id="s-ctx4", usage={"total_tokens": 200, "prompt_tokens": 180})
    assert phoenix_v7._prompt_tokens_by_session["s-ctx4"] == 180


def test_record_usage_missing_prompt_tokens_defaults_to_zero():
    phoenix_v7._prompt_tokens_by_session.clear()
    phoenix_v7._record_usage(session_id="s-ctx5", usage={"total_tokens": 200})
    assert phoenix_v7._prompt_tokens_by_session["s-ctx5"] == 0

