"""审计外发——把不死鸟自己判断出的警示事件（熔断跳闸/hardline 命令/幻觉核验/隐私
提醒）签名后推送到用户自配置的外部 HTTP 端点。

Hermes v0.20 原生 outbound webhook（agent/outbound_webhooks.py）只能转发
VALID_HOOKS 里的原生钩子事件，不给插件开放自定义事件名的公开注册接口——它直接
操作插件管理器的私有属性 manager._hooks，不死鸟的设计原则是只用
ctx.register_hook/ctx.register_middleware 公开接口。不死鸟自己算出来的判断没有
现成通道外发，这个模块自建一份精简版：设计思路照抄 Hermes 原生那套（HMAC-SHA256
签名 + 有界队列 + 后台 daemon 线程 fire-and-forget，不阻塞主流程等网络 I/O），
但不导入/依赖它的任何私有函数。"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import queue
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_QUEUE = 256
_queue: "queue.Queue[tuple[dict, dict]]" = queue.Queue(maxsize=_MAX_QUEUE)
_worker_started = False
_worker_lock = threading.Lock()


def _default_config_path() -> Path:
    from hermes_constants import get_hermes_home
    return get_hermes_home() / "phoenix_v7_state" / "webhooks.json"


def _load_config(path: Path | None = None) -> tuple[bool, list[dict]]:
    """返回 (enabled, targets)。文件缺失/损坏一律降级成 (False, [])——这是告警性
    功能，配置本身的错误不能反过来影响不死鸟其余逻辑或抛异常。"""
    target = path or _default_config_path()
    if not target.exists():
        return False, []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return False, []
    if not isinstance(data, dict):
        return False, []
    enabled = bool(data.get("enabled", False))
    targets = data.get("targets")
    if not isinstance(targets, list):
        return enabled, []
    valid = [
        t for t in targets
        if isinstance(t, dict) and isinstance(t.get("url"), str) and t["url"]
    ]
    return enabled, valid


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _build_payload(event: str, session_id: str, detail: dict) -> dict:
    return {
        "event": event,
        "session_id": session_id,
        "detail": detail,
        "delivery_id": str(uuid.uuid4()),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "phoenix_v7",
    }


def _deliver(target: dict, payload: dict) -> None:
    """实际发起一次 HTTP POST。失败只记日志、不抛异常——外发通道本身故障不能
    影响不死鸟的其余判断逻辑，也不能让后台工作线程崩掉退出。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Phoenix-v7-Outbound-Webhook",
        "X-Phoenix-Event": payload["event"],
        "X-Phoenix-Delivery": payload["delivery_id"],
    }
    secret_env = target.get("secret_env")
    if secret_env:
        secret = os.environ.get(secret_env)
        if secret:
            headers["X-Phoenix-Signature-256"] = _sign(body, secret)
    raw_timeout = target.get("timeout", 10)
    try:
        timeout = max(1, min(60, int(raw_timeout)))
    except (TypeError, ValueError):
        timeout = 10
    request = urllib.request.Request(
        target["url"], data=body, headers=headers, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            pass
    except Exception as exc:
        logger.warning(
            "phoenix_v7 webhook: delivery to %s failed: %s", target.get("url"), exc,
        )


def _worker_loop() -> None:
    while True:
        target, payload = _queue.get()
        try:
            _deliver(target, payload)
        finally:
            _queue.task_done()


def _ensure_worker() -> None:
    global _worker_started
    if _worker_started:
        return
    with _worker_lock:
        if _worker_started:
            return
        thread = threading.Thread(
            target=_worker_loop, name="phoenix-webhook-worker", daemon=True,
        )
        thread.start()
        _worker_started = True


def send_alert(
    event: str, session_id: str, detail: dict, *, path: Path | None = None,
) -> None:
    """公开入口——四个警示信号触发点调用这个函数。enabled=False 或没有配置
    target 时直接返回，不做任何多余工作。绝不阻塞调用方等网络 I/O：只入队，
    真正的 HTTP 请求在后台线程里发生。"""
    enabled, targets = _load_config(path)
    if not enabled or not targets:
        return
    payload = _build_payload(event, session_id, detail)
    _ensure_worker()
    for target in targets:
        try:
            _queue.put_nowait((target, payload))
        except queue.Full:
            logger.warning(
                "phoenix_v7 webhook: queue full, dropping alert event=%s", event,
            )


def flush(timeout: float = 5.0) -> bool:
    """等队列排空，供测试/诊断使用。返回是否在超时前排空。"""
    deadline = time.time() + timeout
    while not _queue.empty() and time.time() < deadline:
        time.sleep(0.01)
    return _queue.empty()
