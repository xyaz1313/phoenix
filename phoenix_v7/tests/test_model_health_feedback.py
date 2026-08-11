"""最终整分支复审发现的真bug回归测试：_record_usage/_record_api_error 原来拿
context.get("model")（= agent.model，路由前的默认模型）给 _model_health 记信号，
但 _route() 真正换过模型之后，agent.model 并不会被同步更新（Hermes 的
llm_request middleware 只改写发出去的 request payload，不改 agent.model 本身）。
结果：候选链健康追踪永远收不到候选模型的真实成败信号，resolve_candidate() 只能
一直确定性返回候选链第一个——健康感知失效（安全地退化，但功能本身是死的）。

修法：_route() 在每次被调用时都把"这个session接下来这次调用实际会用的模型"
写进 _resolved_model_by_session[session_id]（不管有没有真的换过），
_record_usage/_record_api_error 优先读这份记录，读不到才落回 context.get("model")。
"""

import phoenix_v7

class _SpyHealth:
    def __init__(self):
        self.successes: list[str] = []
        self.failures: list[tuple[str, str]] = []

    def record_success(self, model: str) -> None:
        self.successes.append(model)

    def record_failure(self, model: str, error_type: str) -> None:
        self.failures.append((model, error_type))

    def is_available(self, model: str) -> bool:
        return True

    def ordered_candidates(self, models: list[str]) -> list[str]:
        return list(models)

def test_route_records_resolved_model_when_swap_happens(monkeypatch):
    # 2026-08-05修正：候选要用 dict 格式声明 provider 且跟当前请求 provider 匹配，
    # 改写才会生效——纯字符串格式的候选不再默认放行。
    monkeypatch.setattr(phoenix_v7, "_primary_provider", "nous")
    monkeypatch.setattr(
        phoenix_v7, "load_tier_overrides",
        lambda: (True, {"l2_deep": {"model": "smart-model", "provider": "nous"}}),
    )
    phoenix_v7._last_tier_by_session.clear()
    phoenix_v7._resolved_model_by_session.clear()
    request = {
        "model": "default-model",
        "messages": [{"role": "user", "content": "帮我设计一个分布式系统的一致性方案"}],
    }
    phoenix_v7._route(request, session_id="s-swap", provider="nous")
    assert phoenix_v7._resolved_model_by_session["s-swap"] == "smart-model"

def test_route_records_resolved_model_when_no_override(monkeypatch):
    monkeypatch.setattr(phoenix_v7, "load_tier_overrides", lambda: (True, {}))
    phoenix_v7._last_tier_by_session.clear()
    phoenix_v7._resolved_model_by_session.clear()
    request = {"model": "default-model", "messages": [{"role": "user", "content": "在吗"}]}
    phoenix_v7._route(request, session_id="s-no-override")
    assert phoenix_v7._resolved_model_by_session["s-no-override"] == "default-model"

def test_route_records_resolved_model_when_routing_disabled(monkeypatch):
    monkeypatch.setattr(
        phoenix_v7, "load_tier_overrides", lambda: (False, {"l2_deep": "smart-model"})
    )
    phoenix_v7._last_tier_by_session.clear()
    phoenix_v7._resolved_model_by_session.clear()
    request = {
        "model": "default-model",
        "messages": [{"role": "user", "content": "帮我设计一个分布式系统的一致性方案"}],
    }
    phoenix_v7._route(request, session_id="s-disabled")
    assert phoenix_v7._resolved_model_by_session["s-disabled"] == "default-model"

def test_route_refreshes_stale_entry_on_later_lower_tier_call(monkeypatch):
    # 2026-08-06 行为变更（会话粘滞）：同一个session先在高档位被换过模型后，
    # 下一轮掉回没有override的档位时，路由会"只升不降"地保持重模型——防本地26B的
    # prefix缓存被3B/26B乒乓打死（命中3s vs 冷启动60s，实测）。所以这里的期望值从
    # "刷新回default-model"改成"保持smart-model"——注意这并没有违背本测试的初衷
    # "记录必须是这一轮真正用的模型"：粘滞机制下这一轮真正用的恰恰还是smart-model。
    monkeypatch.setattr(phoenix_v7, "_primary_provider", "nous")
    monkeypatch.setattr(
        phoenix_v7, "load_tier_overrides",
        lambda: (True, {"l2_deep": {"model": "smart-model", "provider": "nous"}}),
    )
    phoenix_v7._last_tier_by_session.clear()
    phoenix_v7._resolved_model_by_session.clear()
    phoenix_v7._pinned_route_by_session.clear()
    phoenix_v7._route(
        {"model": "default-model", "messages": [{"role": "user", "content": "帮我设计一个分布式系统的一致性方案"}]},
        session_id="s-refresh", provider="nous",
    )
    assert phoenix_v7._resolved_model_by_session["s-refresh"] == "smart-model"

    phoenix_v7._route(
        {"model": "default-model", "messages": [{"role": "user", "content": "在吗"}]},
        session_id="s-refresh", provider="nous",
    )
    # 会话粘滞：本轮仍走 smart-model（这是本轮真实使用的模型，健康记账记它名下是对的）
    assert phoenix_v7._resolved_model_by_session["s-refresh"] == "smart-model"

def test_record_usage_prefers_resolved_model_over_stale_context_model(monkeypatch):
    spy = _SpyHealth()
    monkeypatch.setattr(phoenix_v7, "_model_health", spy)
    phoenix_v7._resolved_model_by_session.clear()
    phoenix_v7._resolved_model_by_session["s-usage"] = "candidate-model"

    # context 里的 model 是 agent.model（路由前的默认值），跟真正被路由到的
    # candidate-model 不一样——这正是bug现场。
    phoenix_v7._record_usage(session_id="s-usage", model="stale-default-model", usage={"total_tokens": 100})

    assert spy.successes == ["candidate-model"]

def test_record_api_error_prefers_resolved_model_over_stale_context_model(monkeypatch):
    spy = _SpyHealth()
    monkeypatch.setattr(phoenix_v7, "_model_health", spy)
    phoenix_v7._resolved_model_by_session.clear()
    phoenix_v7._resolved_model_by_session["s-error"] = "candidate-model"

    phoenix_v7._record_api_error(
        session_id="s-error",
        model="stale-default-model",
        error={"type": "TimeoutError", "message": "boom"},
    )

    assert spy.failures == [("candidate-model", "TimeoutError")]

def test_record_usage_falls_back_to_context_model_when_no_session_entry(monkeypatch):
    spy = _SpyHealth()
    monkeypatch.setattr(phoenix_v7, "_model_health", spy)
    phoenix_v7._resolved_model_by_session.clear()

    phoenix_v7._record_usage(session_id="s-unknown", model="fallback-model", usage={"total_tokens": 50})

    assert spy.successes == ["fallback-model"]

def test_record_usage_falls_back_when_no_session_id_provided(monkeypatch):
    spy = _SpyHealth()
    monkeypatch.setattr(phoenix_v7, "_model_health", spy)
    phoenix_v7._resolved_model_by_session.clear()

    phoenix_v7._record_usage(model="fallback-model", usage={"total_tokens": 50})

    assert spy.successes == ["fallback-model"]
