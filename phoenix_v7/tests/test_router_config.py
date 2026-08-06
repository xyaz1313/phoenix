import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from router.config import load_tier_overrides, write_enabled, resolve_candidate


def test_new_format_enabled_true():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "tiers.json"
        path.write_text(
            json.dumps({"enabled": True, "tiers": {"l2_deep": "smart-model"}}),
            encoding="utf-8",
        )
        enabled, overrides = load_tier_overrides(path=path)
        assert enabled is True
        assert overrides == {"l2_deep": "smart-model"}


def test_new_format_enabled_false():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "tiers.json"
        path.write_text(
            json.dumps({"enabled": False, "tiers": {"l2_deep": "smart-model"}}),
            encoding="utf-8",
        )
        enabled, overrides = load_tier_overrides(path=path)
        assert enabled is False
        # 关闭时 tiers 内容依然如实返回给调用方——是调用方决定要不要用，
        # load_tier_overrides 只负责如实读取文件内容
        assert overrides == {"l2_deep": "smart-model"}


def test_old_flat_format_still_works():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "tiers.json"
        path.write_text(json.dumps({"l2_deep": "smart-model"}), encoding="utf-8")
        enabled, overrides = load_tier_overrides(path=path)
        assert enabled is True
        assert overrides == {"l2_deep": "smart-model"}


def test_empty_dict_returns_enabled_true_empty_overrides():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "tiers.json"
        path.write_text("{}", encoding="utf-8")
        enabled, overrides = load_tier_overrides(path=path)
        assert enabled is True
        assert overrides == {}


def test_missing_file_returns_enabled_true_empty_overrides():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "does_not_exist.json"
        enabled, overrides = load_tier_overrides(path=path)
        assert enabled is True
        assert overrides == {}


def test_corrupted_json_returns_enabled_true_empty_overrides():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "tiers.json"
        path.write_text("{not valid json", encoding="utf-8")
        enabled, overrides = load_tier_overrides(path=path)
        assert enabled is True
        assert overrides == {}


def test_write_enabled_upgrades_old_flat_format_without_losing_data():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "tiers.json"
        path.write_text(json.dumps({"l2_deep": "smart-model"}), encoding="utf-8")
        write_enabled(False, path=path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["enabled"] is False
        assert data["tiers"] == {"l2_deep": "smart-model"}


def test_write_enabled_upgrades_old_flat_format_keeps_list_and_dict_values():
    # 2026-08-05修正：以前升级旧格式时只保留 isinstance(v, str) 的值，list（候选链）
    # 和 dict（provider 归属声明）会被静默丢弃。真实审计报告指出的问题。
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "tiers.json"
        path.write_text(
            json.dumps({
                "l1_simple": "cheap-model",
                "l2_deep": ["candidate-a", "candidate-b"],
                "l3_critical": {"model": "careful-model", "provider": "nous"},
            }),
            encoding="utf-8",
        )
        write_enabled(False, path=path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["enabled"] is False
        assert data["tiers"] == {
            "l1_simple": "cheap-model",
            "l2_deep": ["candidate-a", "candidate-b"],
            "l3_critical": {"model": "careful-model", "provider": "nous"},
        }


def test_write_enabled_on_new_format_only_changes_enabled_field():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "tiers.json"
        path.write_text(
            json.dumps({"enabled": True, "tiers": {"l3_critical": "careful-model"}}),
            encoding="utf-8",
        )
        write_enabled(False, path=path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["enabled"] is False
        assert data["tiers"] == {"l3_critical": "careful-model"}


def test_write_enabled_on_missing_file_creates_it():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "nested" / "tiers.json"
        write_enabled(True, path=path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data == {"tiers": {}, "enabled": True}


def test_new_format_preserves_list_valued_tier_for_candidate_chains():
    # Task 4 real-machine verification 发现的真bug：isinstance(v, str) 这个过滤
    # 会把候选链（list值）静默丢掉，resolve_candidate() 永远看不到它。
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "tiers.json"
        path.write_text(
            json.dumps({"enabled": True, "tiers": {"l3_critical": ["model-a", "model-b"]}}),
            encoding="utf-8",
        )
        enabled, overrides = load_tier_overrides(path=path)
        assert enabled is True
        assert overrides == {"l3_critical": ["model-a", "model-b"]}


def test_old_flat_format_preserves_list_valued_tier():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "tiers.json"
        path.write_text(json.dumps({"l2_deep": ["model-a", "model-b"]}), encoding="utf-8")
        enabled, overrides = load_tier_overrides(path=path)
        assert enabled is True
        assert overrides == {"l2_deep": ["model-a", "model-b"]}


def test_list_with_non_string_entries_is_dropped():
    # 防御性过滤还是要保留——只是范围要从"只认str"扩大到"认str或纯str列表"
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "tiers.json"
        path.write_text(
            json.dumps({"enabled": True, "tiers": {
                "l2_deep": ["model-a", 123],
                "l3_critical": "still-valid",
            }}),
            encoding="utf-8",
        )
        enabled, overrides = load_tier_overrides(path=path)
        assert "l2_deep" not in overrides  # 混了非字符串元素，整条丢弃
        assert overrides["l3_critical"] == "still-valid"


def test_resolve_candidate_string_override_bypasses_health_tracking():
    from guardrails.model_health import ModelHealthTracker

    calls = []

    class _SpyTracker(ModelHealthTracker):
        def ordered_candidates(self, models):
            calls.append(models)
            return super().ordered_candidates(models)

    model, provider = resolve_candidate("some-model", "default-model", _SpyTracker())
    assert model == "some-model"
    assert provider is None  # 字符串格式（旧格式）不带 provider 信息
    assert calls == []  # 单字符串格式，健康追踪完全不介入


def test_resolve_candidate_none_uses_default():
    from guardrails.model_health import ModelHealthTracker

    model, provider = resolve_candidate(None, "default-model", ModelHealthTracker())
    assert model == "default-model"
    assert provider is None


def test_resolve_candidate_empty_list_uses_default():
    from guardrails.model_health import ModelHealthTracker

    model, provider = resolve_candidate([], "default-model", ModelHealthTracker())
    assert model == "default-model"
    assert provider is None


def test_resolve_candidate_list_picks_healthiest_first():
    from guardrails.model_health import ModelHealthTracker

    health = ModelHealthTracker(failure_threshold=1)
    health.record_failure("model-a", "TimeoutError")
    model, provider = resolve_candidate(["model-a", "model-b"], "default-model", health)
    assert model == "model-b"
    assert provider is None  # 候选链格式不支持 provider 归属声明


def test_resolve_candidate_list_all_healthy_picks_first():
    from guardrails.model_health import ModelHealthTracker

    model, provider = resolve_candidate(["model-a", "model-b"], "default-model", ModelHealthTracker())
    assert model == "model-a"
    assert provider is None



def test_resolve_candidate_dict_format_returns_model_and_provider():
    from guardrails.model_health import ModelHealthTracker

    tier_override = {"model": "gpt-5", "provider": "openai"}
    model, provider = resolve_candidate(tier_override, "default-model", ModelHealthTracker())
    assert model == "gpt-5"
    assert provider == "openai"


def test_resolve_candidate_dict_format_missing_model_uses_default():
    from guardrails.model_health import ModelHealthTracker

    tier_override = {"provider": "openai"}
    model, provider = resolve_candidate(tier_override, "default-model", ModelHealthTracker())
    assert model == "default-model"
    assert provider is None


def test_is_valid_tier_value_accepts_dict_with_model():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "tiers.json"
        path.write_text(
            json.dumps({"enabled": True, "tiers": {
                "l2_deep": {"model": "gpt-5", "provider": "openai"},
            }}),
            encoding="utf-8",
        )
        enabled, overrides = load_tier_overrides(path=path)
        assert overrides == {"l2_deep": {"model": "gpt-5", "provider": "openai"}}


def test_is_valid_tier_value_rejects_dict_without_model():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "tiers.json"
        path.write_text(
            json.dumps({"enabled": True, "tiers": {
                "l2_deep": {"provider": "openai"},
                "l3_critical": "still-valid",
            }}),
            encoding="utf-8",
        )
        enabled, overrides = load_tier_overrides(path=path)
        assert "l2_deep" not in overrides  # dict 缺 model 字段，整条丢弃
        assert overrides["l3_critical"] == "still-valid"
