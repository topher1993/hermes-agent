"""Narrow R9 fallback-window operator notifier.

This module intentionally implements only the MiniMax fallback audit-window hook
from the R9 ADR.  It is not a generic event bus: callers append the audit row
first, then ask this helper to inspect the recent audit window and send at most
one non-blocking operator ping per cooldown period.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)

DEFAULT_SIGNAL_WINDOW_SECONDS = 300
DEFAULT_PING_THRESHOLD = 3
DEFAULT_PING_COOLDOWN_SECONDS = 300
DEFAULT_NOTIFY_TIMEOUT_SECONDS = 2.0

_LAST_NOTIFICATION_BY_AUDIT_PATH: dict[str, float] = {}


class FallbackWindowNotifier(Protocol):
    """Narrow Kaisel/operator hook specified by R9 ADR §6."""

    def notify_fallback_window(
        self,
        count: int,
        recent_profiles: list[str],
        audit_log_path: str,
    ) -> None:
        """Notify that an R9 fallback/blocked audit window crossed threshold."""


@dataclass(frozen=True)
class FallbackAuditEvent:
    """Sanitized subset of one R9 audit row used for notification windows."""

    event_type: str
    timestamp: float
    profile: str


@dataclass(frozen=True)
class FallbackWindowSummary:
    """Event-type-aware counts for one R9 audit notification window."""

    total_count: int
    fallback_activated_count: int
    blocked_no_fallback_count: int
    recent_profiles: list[str]
    audit_log_path: str


class OperatorFallbackWindowNotifier:
    """Default operator notifier using Hermes' existing send_message path."""

    def __init__(
        self,
        *,
        summary: FallbackWindowSummary | None = None,
        message_sender: Callable[[str], None] | None = None,
    ) -> None:
        self._summary = summary
        self._message_sender = message_sender or _send_operator_message

    def notify_fallback_window(
        self,
        count: int,
        recent_profiles: list[str],
        audit_log_path: str,
    ) -> None:
        """Send a sanitized R9 operator ping through the configured sender."""

        summary = self._summary or FallbackWindowSummary(
            total_count=count,
            fallback_activated_count=count,
            blocked_no_fallback_count=0,
            recent_profiles=recent_profiles,
            audit_log_path=audit_log_path,
        )
        self._message_sender(format_fallback_window_message(summary))


def reset_fallback_notifier_cooldowns_for_tests() -> None:
    """Clear in-process notifier cooldown state for deterministic tests."""

    _LAST_NOTIFICATION_BY_AUDIT_PATH.clear()


def read_recent_fallback_audit_events(
    audit_log_path: str,
    *,
    window_seconds: int = DEFAULT_SIGNAL_WINDOW_SECONDS,
    now: float | None = None,
) -> list[FallbackAuditEvent]:
    """Read recent R9 audit events from ``audit_log_path``.

    Only ``event_type``, ``timestamp``, and ``profile`` are retained.  Raw error
    payloads and chat content are never included in notifier state or messages.
    """

    cutoff = (time.time() if now is None else now) - window_seconds
    path = _resolve_audit_log_path(audit_log_path)
    if not path.exists():
        return []
    events: list[FallbackAuditEvent] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("R9 fallback notifier could not read audit log %s: %s", path, exc)
        return []
    for line in lines:
        event = _event_from_json_line(line)
        if event is not None and event.timestamp >= cutoff:
            events.append(event)
    return events


def summarize_fallback_window(
    events: Iterable[FallbackAuditEvent],
    audit_log_path: str,
) -> FallbackWindowSummary:
    """Build event-type-aware counts and profile list for notifier wording."""

    event_list = list(events)
    fallback_count = sum(1 for event in event_list if event.event_type == "fallback_activated")
    blocked_count = sum(1 for event in event_list if event.event_type == "blocked_no_fallback")
    profiles: list[str] = []
    seen: set[str] = set()
    for event in event_list:
        if event.profile and event.profile not in seen:
            seen.add(event.profile)
            profiles.append(event.profile)
    return FallbackWindowSummary(
        total_count=fallback_count + blocked_count,
        fallback_activated_count=fallback_count,
        blocked_no_fallback_count=blocked_count,
        recent_profiles=profiles,
        audit_log_path=str(_resolve_audit_log_path(audit_log_path)),
    )


def format_fallback_window_message(summary: FallbackWindowSummary) -> str:
    """Return sanitized operator-facing wording for an R9 event window."""

    parts: list[str] = []
    if summary.fallback_activated_count:
        parts.append(
            f"{summary.fallback_activated_count} actual MiniMax fallback"
            f"{'' if summary.fallback_activated_count == 1 else 's'}"
        )
    if summary.blocked_no_fallback_count:
        parts.append(
            f"{summary.blocked_no_fallback_count} Tusk/policy blocked/no fallback"
            f" event{'' if summary.blocked_no_fallback_count == 1 else 's'}"
        )
    count_text = "; ".join(parts) if parts else "0 R9 fallback/blocked events"
    profiles = ", ".join(summary.recent_profiles[:8]) if summary.recent_profiles else "unknown"
    if len(summary.recent_profiles) > 8:
        profiles += f", +{len(summary.recent_profiles) - 8} more"
    return (
        "R9 MiniMax fallback window threshold reached: "
        f"{count_text}. Recent profiles: {profiles}. "
        "Requested model: openai-codex/gpt-5.5. "
        "Fallback target: minimax-oauth/MiniMax-M3 for actual fallbacks only. "
        f"Audit log: {summary.audit_log_path}"
    )


def notify_recent_fallback_window(
    *,
    audit_log_path: str,
    notifier: FallbackWindowNotifier | None = None,
    message_sender: Callable[[str], None] | None = None,
    threshold: int | None = None,
    window_seconds: int | None = None,
    cooldown_seconds: int | None = None,
    timeout_seconds: float = DEFAULT_NOTIFY_TIMEOUT_SECONDS,
    now: float | None = None,
) -> bool:
    """Notify when recent R9 audit events cross threshold.

    Returns ``True`` only when the notifier completed before timeout.  Timeouts,
    send exceptions, unreadable logs, sub-threshold windows, and cooldown skips
    all return ``False`` and never raise, preserving the ADR's non-blocking
    notifier contract after the audit write has succeeded.
    """

    configured_threshold, configured_window, configured_cooldown = _notification_policy_values()
    active_threshold = threshold if threshold is not None else configured_threshold
    active_window = window_seconds if window_seconds is not None else configured_window
    active_cooldown = cooldown_seconds if cooldown_seconds is not None else configured_cooldown
    current_time = time.time() if now is None else now
    events = read_recent_fallback_audit_events(
        audit_log_path,
        window_seconds=active_window,
        now=current_time,
    )
    summary = summarize_fallback_window(events, audit_log_path)
    if summary.total_count < active_threshold:
        return False
    cooldown_key = summary.audit_log_path
    last_notification = _LAST_NOTIFICATION_BY_AUDIT_PATH.get(cooldown_key)
    if last_notification is not None and current_time - last_notification < active_cooldown:
        return False
    selected_notifier = notifier or OperatorFallbackWindowNotifier(
        summary=summary,
        message_sender=message_sender,
    )
    sent = _call_notifier_with_timeout(
        selected_notifier,
        summary,
        timeout_seconds=timeout_seconds,
    )
    if sent:
        _LAST_NOTIFICATION_BY_AUDIT_PATH[cooldown_key] = current_time
    return sent


def _call_notifier_with_timeout(
    notifier: FallbackWindowNotifier,
    summary: FallbackWindowSummary,
    *,
    timeout_seconds: float,
) -> bool:
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="r9-fallback-notifier",
    )
    future = executor.submit(
        notifier.notify_fallback_window,
        summary.total_count,
        list(summary.recent_profiles),
        summary.audit_log_path,
    )
    try:
        future.result(timeout=timeout_seconds)
        return True
    except concurrent.futures.TimeoutError:
        logger.warning("R9 fallback notifier timed out after %.1fs", timeout_seconds)
        executor.shutdown(wait=False, cancel_futures=True)
        return False
    except Exception as exc:
        logger.warning("R9 fallback notifier failed: %s", exc)
        return False
    finally:
        if future.done():
            executor.shutdown(wait=False)


def _notification_policy_values() -> tuple[int, int, int]:
    try:
        from hermes_cli.routing_policy import load_routing_policy

        policy = load_routing_policy()
        return (
            policy.telegram_ping_threshold_in_window,
            policy.fallback_signal_window_seconds,
            policy.telegram_ping_cooldown_seconds,
        )
    except Exception as exc:
        logger.warning("R9 fallback notifier using default policy values: %s", exc)
        return (
            DEFAULT_PING_THRESHOLD,
            DEFAULT_SIGNAL_WINDOW_SECONDS,
            DEFAULT_PING_COOLDOWN_SECONDS,
        )


def _send_operator_message(message: str) -> None:
    from tools.send_message_tool import send_message_tool

    result = send_message_tool({"action": "send", "target": "telegram", "message": message})
    try:
        payload = json.loads(result)
    except (TypeError, json.JSONDecodeError):
        payload = {}
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(str(payload["error"]))


def _resolve_audit_log_path(audit_log_path: str) -> Path:
    path = Path(audit_log_path)
    if path.is_absolute():
        return path
    return get_hermes_home() / path


def _event_from_json_line(line: str) -> FallbackAuditEvent | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    event_type = payload.get("event_type")
    if event_type not in {"fallback_activated", "blocked_no_fallback"}:
        return None
    timestamp = _parse_timestamp(payload.get("timestamp"))
    if timestamp is None:
        return None
    profile = payload.get("profile")
    return FallbackAuditEvent(
        event_type=event_type,
        timestamp=timestamp,
        profile=str(profile or "unknown")[:80],
    )


def _parse_timestamp(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()
