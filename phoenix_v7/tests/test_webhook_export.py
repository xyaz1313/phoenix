import json

from guardrails.webhook_export import send_alert, flush, _load_config, _build_payload, _sign


def test_load_config_missing_file_returns_disabled(tmp_path):
    path = tmp_path / "webhooks.json"
    enabled, targets = _load_config(path)
    assert enabled is False
    assert targets == []


def test_load_config_corrupted_json_returns_disabled(tmp_path):
    path = tmp_path / "webhooks.json"
    path.write_text("{not valid json", encoding="utf-8")
    enabled, targets = _load_config(path)
    assert enabled is False
    assert targets == []


def test_load_config_reads_enabled_and_targets(tmp_path):
    path = tmp_path / "webhooks.json"
    path.write_text(json.dumps({
        "enabled": True,
        "targets": [{"url": "https://example.com/hook", "timeout": 5}],
    }), encoding="utf-8")
    enabled, targets = _load_config(path)
    assert enabled is True
    assert targets == [{"url": "https://example.com/hook", "timeout": 5}]


def test_load_config_drops_targets_without_url(tmp_path):
    path = tmp_path / "webhooks.json"
    path.write_text(json.dumps({
        "enabled": True,
        "targets": [{"timeout": 5}, {"url": "https://ok.example.com"}],
    }), encoding="utf-8")
    enabled, targets = _load_config(path)
    assert targets == [{"url": "https://ok.example.com"}]


def test_build_payload_has_required_fields():
    payload = _build_payload("circuit_breaker_tripped", "sess-1", {"foo": "bar"})
    assert payload["event"] == "circuit_breaker_tripped"
    assert payload["session_id"] == "sess-1"
    assert payload["detail"] == {"foo": "bar"}
    assert payload["source"] == "phoenix_v7"
    assert "delivery_id" in payload
    assert "timestamp" in payload


def test_sign_produces_stable_hmac():
    sig1 = _sign(b"hello", "secret")
    sig2 = _sign(b"hello", "secret")
    assert sig1 == sig2
    assert sig1.startswith("sha256=")


def test_sign_differs_with_different_secret():
    assert _sign(b"hello", "secret-a") != _sign(b"hello", "secret-b")


def test_send_alert_disabled_never_delivers(tmp_path, monkeypatch):
    path = tmp_path / "webhooks.json"
    path.write_text(json.dumps(
        {"enabled": False, "targets": [{"url": "https://x.example.com"}]}
    ), encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        "guardrails.webhook_export._deliver",
        lambda target, payload: calls.append((target, payload)),
    )
    send_alert("hardline_command_detected", "sess-2", {}, path=path)
    flush(timeout=1.0)
    assert calls == []


def test_send_alert_no_targets_never_delivers(tmp_path, monkeypatch):
    path = tmp_path / "webhooks.json"
    path.write_text(json.dumps({"enabled": True, "targets": []}), encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        "guardrails.webhook_export._deliver",
        lambda target, payload: calls.append((target, payload)),
    )
    send_alert("hardline_command_detected", "sess-3", {}, path=path)
    flush(timeout=1.0)
    assert calls == []


def test_send_alert_enabled_delivers_to_each_target(tmp_path, monkeypatch):
    path = tmp_path / "webhooks.json"
    path.write_text(json.dumps({
        "enabled": True,
        "targets": [{"url": "https://a.example.com"}, {"url": "https://b.example.com"}],
    }), encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        "guardrails.webhook_export._deliver",
        lambda target, payload: calls.append((target["url"], payload)),
    )
    send_alert("privacy_warning_triggered", "sess-4", {"note": "x"}, path=path)
    assert flush(timeout=2.0) is True
    urls = sorted(c[0] for c in calls)
    assert urls == ["https://a.example.com", "https://b.example.com"]
    assert all(c[1]["event"] == "privacy_warning_triggered" for c in calls)
    assert all(c[1]["session_id"] == "sess-4" for c in calls)


def test_deliver_sends_signature_header_when_secret_env_set(monkeypatch):
    from guardrails import webhook_export

    monkeypatch.setenv("TEST_PHOENIX_WEBHOOK_SECRET", "s3cr3t")
    captured = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(request, timeout=None):
        captured["headers"] = {k.lower(): v for k, v in request.header_items()}
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(webhook_export.urllib.request, "urlopen", fake_urlopen)
    target = {
        "url": "https://example.com/hook",
        "secret_env": "TEST_PHOENIX_WEBHOOK_SECRET",
        "timeout": 7,
    }
    payload = webhook_export._build_payload("hardline_command_detected", "sess-5", {})
    webhook_export._deliver(target, payload)
    assert "x-phoenix-signature-256" in captured["headers"]
    assert captured["timeout"] == 7


def test_deliver_skips_signature_when_no_secret_env(monkeypatch):
    from guardrails import webhook_export

    captured = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(request, timeout=None):
        captured["headers"] = {k.lower(): v for k, v in request.header_items()}
        return _FakeResponse()

    monkeypatch.setattr(webhook_export.urllib.request, "urlopen", fake_urlopen)
    target = {"url": "https://example.com/hook"}
    payload = webhook_export._build_payload("hardline_command_detected", "sess-6", {})
    webhook_export._deliver(target, payload)
    assert "x-phoenix-signature-256" not in captured["headers"]


def test_deliver_network_failure_does_not_raise(monkeypatch):
    from guardrails import webhook_export

    def fake_urlopen(request, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(webhook_export.urllib.request, "urlopen", fake_urlopen)
    target = {"url": "https://example.com/hook"}
    payload = webhook_export._build_payload("hardline_command_detected", "sess-7", {})
    webhook_export._deliver(target, payload)  # 不抛异常就是通过
