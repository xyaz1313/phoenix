
import phoenix_v7

def test_route_disabled_updates_tier_state_but_returns_none(monkeypatch):
    monkeypatch.setattr(
        phoenix_v7, "load_tier_overrides", lambda: (False, {"l2_deep": "smart-model"})
    )
    phoenix_v7._last_tier_by_session.clear()
    request = {
        "model": "default-model",
        "messages": [{"role": "user", "content": "帮我设计一个分布式系统的一致性方案"}],
    }
    result = phoenix_v7._route(request, session_id="test-session-1")
    assert result is None
    assert phoenix_v7._last_tier_by_session["test-session-1"] == "l2_deep"

def test_route_enabled_switches_model_when_tier_has_override(monkeypatch):
    # 2026-08-05修正：候选必须用 dict 格式声明 provider 且跟当前请求 provider
    # 匹配，改写才会生效——纯字符串格式不再默认放行（见下面的 legacy 系列测试）。
    monkeypatch.setattr(phoenix_v7, "_primary_provider", "nous")
    monkeypatch.setattr(
        phoenix_v7, "load_tier_overrides",
        lambda: (True, {"l2_deep": {"model": "smart-model", "provider": "nous"}}),
    )
    phoenix_v7._last_tier_by_session.clear()
    request = {
        "model": "default-model",
        "messages": [{"role": "user", "content": "帮我设计一个分布式系统的一致性方案"}],
    }
    result = phoenix_v7._route(request, session_id="test-session-2", provider="nous")
    assert result is not None
    assert result["request"]["model"] == "smart-model"
    assert phoenix_v7._last_tier_by_session["test-session-2"] == "l2_deep"

def test_route_enabled_but_tier_has_no_override_returns_none(monkeypatch):
    monkeypatch.setattr(phoenix_v7, "load_tier_overrides", lambda: (True, {}))
    phoenix_v7._last_tier_by_session.clear()
    request = {"model": "default-model", "messages": [{"role": "user", "content": "在吗"}]}
    result = phoenix_v7._route(request, session_id="test-session-3")
    assert result is None
    assert phoenix_v7._last_tier_by_session["test-session-3"] == "l0_fast"

def test_load_primary_provider_reads_model_provider(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "model:\n  provider: nous\n  default: z-ai/glm-5.2\n", encoding="utf-8"
    )
    assert phoenix_v7._load_primary_provider(path=config_path) == "nous"

def test_load_primary_provider_missing_file_returns_empty(tmp_path):
    assert phoenix_v7._load_primary_provider(path=tmp_path / "does_not_exist.yaml") == ""

def test_load_primary_provider_malformed_yaml_returns_empty(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("not: valid: yaml: [", encoding="utf-8")
    assert phoenix_v7._load_primary_provider(path=config_path) == ""

def test_load_primary_provider_missing_model_key_returns_empty(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("web:\n  backend: firecrawl\n", encoding="utf-8")
    assert phoenix_v7._load_primary_provider(path=config_path) == ""

def test_route_skips_when_provider_is_not_primary(monkeypatch):
    monkeypatch.setattr(phoenix_v7, "_primary_provider", "nous")
    monkeypatch.setattr(
        phoenix_v7, "load_tier_overrides", lambda: (True, {"l2_deep": "smart-model"})
    )
    phoenix_v7._last_tier_by_session.clear()
    request = {
        "model": "default-model",
        "messages": [{"role": "user", "content": "帮我设计一个分布式系统的一致性方案"}],
    }
    result = phoenix_v7._route(request, session_id="test-session-6", provider="custom")
    assert result is None

def test_route_proceeds_when_provider_matches_primary(monkeypatch):
    monkeypatch.setattr(phoenix_v7, "_primary_provider", "nous")
    monkeypatch.setattr(
        phoenix_v7, "load_tier_overrides",
        lambda: (True, {"l2_deep": {"model": "smart-model", "provider": "nous"}}),
    )
    phoenix_v7._last_tier_by_session.clear()
    request = {
        "model": "default-model",
        "messages": [{"role": "user", "content": "帮我设计一个分布式系统的一致性方案"}],
    }
    result = phoenix_v7._route(request, session_id="test-session-7", provider="nous")
    assert result is not None
    assert result["request"]["model"] == "smart-model"

def test_route_blocks_rewrite_when_provider_context_missing(monkeypatch):
    # 2026-08-05修正：context 里没带 provider 字段时，无法确认候选模型的归属，
    # 必须保留原模型——以前这里放行是真实审计报告指出的安全问题。
    monkeypatch.setattr(phoenix_v7, "_primary_provider", "nous")
    monkeypatch.setattr(
        phoenix_v7, "load_tier_overrides", lambda: (True, {"l2_deep": "smart-model"})
    )
    phoenix_v7._last_tier_by_session.clear()
    request = {
        "model": "default-model",
        "messages": [{"role": "user", "content": "帮我设计一个分布式系统的一致性方案"}],
    }
    result = phoenix_v7._route(request, session_id="test-session-8")
    assert result is None
    assert phoenix_v7._resolved_model_by_session["test-session-8"] == "default-model"

def test_route_blocks_rewrite_when_primary_provider_unresolved(monkeypatch):
    # _primary_provider 读取配置失败时是空字符串，不该让每次请求都被误判成"不在主线路上"
    # ——但归属确认仍然只看候选是否声明了 provider，旧格式没有声明，同样必须保留原模型。
    monkeypatch.setattr(phoenix_v7, "_primary_provider", "")
    monkeypatch.setattr(
        phoenix_v7, "load_tier_overrides", lambda: (True, {"l2_deep": "smart-model"})
    )
    phoenix_v7._last_tier_by_session.clear()
    request = {
        "model": "default-model",
        "messages": [{"role": "user", "content": "帮我设计一个分布式系统的一致性方案"}],
    }
    result = phoenix_v7._route(request, session_id="test-session-9", provider="anything")
    assert result is None
    assert phoenix_v7._resolved_model_by_session["test-session-9"] == "default-model"

def test_route_forces_stream_false_when_target_is_turbofieldfare(monkeypatch):
    monkeypatch.setattr(phoenix_v7, "load_tier_overrides", lambda: (False, {}))
    phoenix_v7._last_tier_by_session.clear()
    request = {
        "model": "gemma-4-26b-a4b-it",
        "messages": [{"role": "user", "content": "在吗"}],
        "stream": True,
    }
    result = phoenix_v7._route(request, session_id="test-stream-1", provider="turbofieldfare")
    assert result is not None
    assert result["request"]["stream"] is False

def test_route_does_not_touch_stream_for_non_turbofieldfare_provider(monkeypatch):
    monkeypatch.setattr(phoenix_v7, "load_tier_overrides", lambda: (False, {}))
    phoenix_v7._last_tier_by_session.clear()
    request = {
        "model": "z-ai/glm-5.2",
        "messages": [{"role": "user", "content": "在吗"}],
        "stream": True,
    }
    result = phoenix_v7._route(request, session_id="test-stream-2", provider="nous")
    assert result is None  # 没有任何改动，不应该返回替换

def test_route_leaves_stream_false_alone_for_turbofieldfare(monkeypatch):
    # stream 本来就是 False，不该因为这条逻辑触发一次"假变化"返回
    monkeypatch.setattr(phoenix_v7, "load_tier_overrides", lambda: (False, {}))
    phoenix_v7._last_tier_by_session.clear()
    request = {
        "model": "gemma-4-26b-a4b-it",
        "messages": [{"role": "user", "content": "在吗"}],
        "stream": False,
    }
    result = phoenix_v7._route(request, session_id="test-stream-3", provider="turbofieldfare")
    assert result is None

def test_route_caches_provider_and_privacy_flag_per_session(monkeypatch):
    monkeypatch.setattr(phoenix_v7, "load_tier_overrides", lambda: (False, {}))
    phoenix_v7._last_tier_by_session.clear()
    phoenix_v7._current_provider_by_session.clear()
    phoenix_v7._privacy_flagged_by_session.clear()
    request = {
        "model": "default-model",
        "messages": [{"role": "user", "content": "我的手机号是13812345678"}],
    }
    phoenix_v7._route(request, session_id="test-cache-1", provider="nous")
    assert phoenix_v7._current_provider_by_session["test-cache-1"] == "nous"
    assert phoenix_v7._privacy_flagged_by_session["test-cache-1"] is True

def test_route_caches_provider_even_when_not_primary(monkeypatch):
    # 早退路径（已经在非主线路上）也要刷新缓存——不然 transform_llm_output 侧
    # 读到的是上一轮的陈旧值。
    monkeypatch.setattr(phoenix_v7, "_primary_provider", "nous")
    phoenix_v7._current_provider_by_session.clear()
    phoenix_v7._privacy_flagged_by_session.clear()
    request = {"model": "default-model", "messages": [{"role": "user", "content": "在吗"}]}
    result = phoenix_v7._route(request, session_id="test-cache-2", provider="turbofieldfare")
    assert result is None  # 早退逻辑本身不变
    assert phoenix_v7._current_provider_by_session["test-cache-2"] == "turbofieldfare"
    assert phoenix_v7._privacy_flagged_by_session["test-cache-2"] is False

def test_route_skips_rewrite_when_candidate_provider_mismatches_current(monkeypatch):
    monkeypatch.setattr(phoenix_v7, "_primary_provider", "nous")
    monkeypatch.setattr(
        phoenix_v7, "load_tier_overrides",
        lambda: (True, {"l2_deep": {"model": "smart-model", "provider": "openai"}}),
    )
    phoenix_v7._last_tier_by_session.clear()
    request = {
        "model": "default-model",
        "messages": [{"role": "user", "content": "帮我设计一个分布式系统的一致性方案"}],
    }
    result = phoenix_v7._route(request, session_id="test-provider-mismatch", provider="nous")
    assert result is None  # provider不一致，不应该发生任何改写
    assert phoenix_v7._resolved_model_by_session["test-provider-mismatch"] == "default-model"

def test_route_applies_rewrite_when_candidate_provider_matches_current(monkeypatch):
    monkeypatch.setattr(phoenix_v7, "_primary_provider", "nous")
    monkeypatch.setattr(
        phoenix_v7, "load_tier_overrides",
        lambda: (True, {"l2_deep": {"model": "smart-model", "provider": "nous"}}),
    )
    phoenix_v7._last_tier_by_session.clear()
    request = {
        "model": "default-model",
        "messages": [{"role": "user", "content": "帮我设计一个分布式系统的一致性方案"}],
    }
    result = phoenix_v7._route(request, session_id="test-provider-match", provider="nous")
    assert result is not None
    assert result["request"]["model"] == "smart-model"

def test_route_legacy_string_format_no_longer_rewrites_without_provider(monkeypatch):
    # 2026-08-05修正：旧格式（纯字符串，没有provider字段）不再被当成"安全候选"放行。
    # 归属无法确认时必须保留原模型，直到用户把这个档位迁移成
    # {"model": ..., "provider": ...} 显式声明归属。这是真实审计报告指出的问题，
    # 原先的"缺省放行"是根因。
    monkeypatch.setattr(phoenix_v7, "_primary_provider", "some-provider")
    monkeypatch.setattr(
        phoenix_v7, "load_tier_overrides",
        lambda: (True, {"l2_deep": "smart-model"}),
    )
    phoenix_v7._last_tier_by_session.clear()
    request = {
        "model": "default-model",
        "messages": [{"role": "user", "content": "帮我设计一个分布式系统的一致性方案"}],
    }
    result = phoenix_v7._route(request, session_id="test-legacy-format", provider="some-provider")
    assert result is None
    assert phoenix_v7._resolved_model_by_session["test-legacy-format"] == "default-model"
