from __future__ import annotations

from datetime import datetime, timezone
import logging
import time
from pathlib import Path

from hermes_cli.fallback_notifier import (
    FallbackWindowNotifier,
    notify_recent_fallback_window,
    reset_fallback_notifier_cooldowns_for_tests,
)


class RecordingNotifier(FallbackWindowNotifier):
    def __init__(self) -> None:
        self.calls: list[tuple[int, list[str], str]] = []

    def notify_fallback_window(
        self,
        count: int,
        recent_profiles: list[str],
        audit_log_path: str,
    ) -> None:
        self.calls.append((count, recent_profiles, audit_log_path))


def _now(timestamp: str = "2026-07-03T00:01:00Z") -> float:
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).timestamp()


def _write_row(
    path: Path,
    event_type: str,
    profile: str,
    timestamp: str = "2026-07-03T00:00:00Z",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fallback_model = '"minimax-oauth/MiniMax-M3"' if event_type == "fallback_activated" else "null"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(
            "{"
            f'"event_type":"{event_type}",'
            f'"timestamp":"{timestamp}",'
            f'"profile":"{profile}",'
            '"requested_model":"openai-codex/gpt-5.5",'
            f'"fallback_model":{fallback_model},'
            '"reason":"quota_exceeded",'
            '"original_error":{"type":"QuotaExceeded","message":"redacted","status_code":429,"code":"codex_rate_limited"},'
            '"config_block_hash":"abc"'
            "}\n"
        )


def setup_function() -> None:
    reset_fallback_notifier_cooldowns_for_tests()


def test_three_fallback_activated_events_send_one_operator_ping_with_actual_fallback_label(
    tmp_path: Path,
) -> None:
    audit_log = tmp_path / "fallbacks.jsonl"
    for profile in ("igris", "clix", "kaisel"):
        _write_row(audit_log, "fallback_activated", profile)
    sent: list[str] = []

    assert notify_recent_fallback_window(
        audit_log_path=str(audit_log),
        message_sender=sent.append,
        now=_now(),
    ) is True

    assert len(sent) == 1
    assert "3 actual MiniMax fallback" in sent[0]
    assert "blocked/no fallback" not in sent[0]
    assert "igris" in sent[0] and "clix" in sent[0] and "kaisel" in sent[0]


def test_three_blocked_no_fallback_events_label_tusk_policy_blocked_not_fallback(
    tmp_path: Path,
) -> None:
    audit_log = tmp_path / "fallbacks.jsonl"
    for profile in ("tusk", "tusk", "tusk"):
        _write_row(audit_log, "blocked_no_fallback", profile)
    sent: list[str] = []

    assert notify_recent_fallback_window(
        audit_log_path=str(audit_log),
        message_sender=sent.append,
        now=_now(),
    ) is True

    assert len(sent) == 1
    assert "3 Tusk/policy blocked/no fallback" in sent[0]
    assert "3 actual MiniMax fallback" not in sent[0]
    assert "successful fallback" not in sent[0].lower()


def test_mixed_events_send_one_ping_with_both_counts(tmp_path: Path) -> None:
    audit_log = tmp_path / "fallbacks.jsonl"
    _write_row(audit_log, "fallback_activated", "igris")
    _write_row(audit_log, "fallback_activated", "clix")
    _write_row(audit_log, "blocked_no_fallback", "tusk")
    sent: list[str] = []

    assert notify_recent_fallback_window(
        audit_log_path=str(audit_log),
        message_sender=sent.append,
        now=_now(),
    ) is True

    assert len(sent) == 1
    assert "2 actual MiniMax fallback" in sent[0]
    assert "1 Tusk/policy blocked/no fallback" in sent[0]


def test_protocol_notifier_receives_count_profiles_and_path(tmp_path: Path) -> None:
    audit_log = tmp_path / "fallbacks.jsonl"
    for profile in ("igris", "clix", "kaisel"):
        _write_row(audit_log, "fallback_activated", profile)
    notifier = RecordingNotifier()

    assert notify_recent_fallback_window(
        audit_log_path=str(audit_log),
        notifier=notifier,
        now=_now(),
    ) is True

    assert notifier.calls == [(3, ["igris", "clix", "kaisel"], str(audit_log))]


def test_notifier_timeout_is_logged_and_does_not_raise(tmp_path: Path, caplog) -> None:
    audit_log = tmp_path / "fallbacks.jsonl"
    for profile in ("igris", "clix", "kaisel"):
        _write_row(audit_log, "fallback_activated", profile)

    def slow_sender(message: str) -> None:
        time.sleep(0.2)

    caplog.set_level(logging.WARNING)

    assert notify_recent_fallback_window(
        audit_log_path=str(audit_log),
        message_sender=slow_sender,
        timeout_seconds=0.01,
        now=_now(),
    ) is False
    assert "timed out" in caplog.text


def test_notifier_exception_is_logged_and_does_not_raise(tmp_path: Path, caplog) -> None:
    audit_log = tmp_path / "fallbacks.jsonl"
    for profile in ("igris", "clix", "kaisel"):
        _write_row(audit_log, "fallback_activated", profile)

    def failing_sender(message: str) -> None:
        raise RuntimeError("send failed")

    caplog.set_level(logging.WARNING)

    assert notify_recent_fallback_window(
        audit_log_path=str(audit_log),
        message_sender=failing_sender,
        now=_now(),
    ) is False
    assert "failed" in caplog.text
    assert "send failed" in caplog.text


def test_cooldown_allows_only_one_ping_per_five_minutes(tmp_path: Path) -> None:
    audit_log = tmp_path / "fallbacks.jsonl"
    for profile in ("igris", "clix", "kaisel"):
        _write_row(audit_log, "fallback_activated", profile)
    sent: list[str] = []
    base_now = _now()

    assert notify_recent_fallback_window(
        audit_log_path=str(audit_log),
        message_sender=sent.append,
        now=base_now,
    ) is True
    assert notify_recent_fallback_window(
        audit_log_path=str(audit_log),
        message_sender=sent.append,
        now=base_now + 60,
    ) is False

    assert len(sent) == 1
