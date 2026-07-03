"""Append-only R9 routing-policy audit log helper."""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from hermes_constants import get_hermes_home
from hermes_cli.quota_exceeded import QuotaExceeded
from hermes_cli.routing_policy import (
    DEFAULT_AUDIT_LOG_PATH,
    FallbackDisabledError,
    RoutingPolicy,
    TuskNoFallbackError,
    get_fallback_target,
    load_routing_policy,
    profile_allows_minimax_fallback,
)


_AUDIT_LOCK = threading.Lock()
_SECRET_VALUE_RE = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer|password|passwd|secret|token)"
    r"(\s*[:=]\s*|\s+)[^\s,'\"}]{4,}"
)
_BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}")


class FallbackAuditError(RuntimeError):
    """Raised when a RED-risk fallback audit row cannot be written."""


@dataclass(frozen=True)
class FallbackAuditDecision:
    """Decision row data used by R9 audit and fallback activation."""

    event_type: str
    profile: str
    requested_model: str
    fallback_model: str | None
    reason: str
    config_block_hash: str
    audit_log_path: str


def _active_profile_name() -> str:
    try:
        from hermes_cli.profiles import get_active_profile_name

        return get_active_profile_name() or "default"
    except Exception:
        return "default"


def _safe_error_message(exc: Exception) -> str:
    if isinstance(exc, QuotaExceeded):
        message = str(exc).strip() or "Codex provider quota exhausted"
    else:
        message = str(exc).strip()
    message = _BEARER_RE.sub("Bearer [REDACTED]", message)
    message = _SECRET_VALUE_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", message)
    if len(message) > 500:
        message = message[:497] + "..."
    return message


def _original_error_payload(exc: Exception) -> dict[str, object]:
    original = getattr(exc, "original_error", None)
    source = original if isinstance(original, Exception) else exc
    payload: dict[str, object] = {
        "type": type(exc).__name__,
        "message": _safe_error_message(exc),
    }
    status_code = getattr(exc, "status_code", None) or getattr(source, "status_code", None)
    code = getattr(exc, "code", None) or getattr(source, "code", None)
    if status_code is not None:
        payload["status_code"] = status_code
    if code is not None:
        payload["code"] = str(code)
    return payload


def _resolve_audit_path(policy_path: str) -> Path:
    cleaned = (policy_path or DEFAULT_AUDIT_LOG_PATH).strip().replace("\\", "/")
    pure = PurePosixPath(cleaned)
    if pure.is_absolute() or ":" in pure.parts[0] or ".." in pure.parts or pure.suffix != ".jsonl":
        raise FallbackAuditError("invalid routing_policy.audit_log_path")
    return get_hermes_home() / Path(*pure.parts)


def evaluate_r9_routing_policy(agent: Any, exc: QuotaExceeded) -> FallbackAuditDecision:
    """Evaluate R9 policy for a quota exception without mutating provider/model."""

    policy = load_routing_policy()
    profile = _active_profile_name().strip().lower()
    target = get_fallback_target(profile)
    if profile == "tusk":
        return FallbackAuditDecision(
            event_type="blocked_no_fallback",
            profile=profile,
            requested_model=exc.requested_model,
            fallback_model=None,
            reason="tusk_structural_gate",
            config_block_hash=policy.config_block_hash,
            audit_log_path=policy.audit_log_path,
        )
    if profile_allows_minimax_fallback(profile) is not True:
        return FallbackAuditDecision(
            event_type="blocked_no_fallback",
            profile=profile,
            requested_model=exc.requested_model,
            fallback_model=None,
            reason="fallback_disabled_profile",
            config_block_hash=policy.config_block_hash,
            audit_log_path=policy.audit_log_path,
        )
    if policy.non_qc_specialists_with_fallback is not True:
        return FallbackAuditDecision(
            event_type="blocked_no_fallback",
            profile=profile,
            requested_model=exc.requested_model,
            fallback_model=None,
            reason="fallback_disabled_global",
            config_block_hash=policy.config_block_hash,
            audit_log_path=policy.audit_log_path,
        )
    return FallbackAuditDecision(
        event_type="fallback_activated",
        profile=profile,
        requested_model=exc.requested_model,
        fallback_model=target.spec,
        reason="quota_exceeded",
        config_block_hash=policy.config_block_hash,
        audit_log_path=policy.audit_log_path,
    )


def _decision_to_row(decision: FallbackAuditDecision, exc: Exception) -> dict[str, object]:
    return {
        "event_type": decision.event_type,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "profile": decision.profile,
        "requested_model": decision.requested_model,
        "fallback_model": decision.fallback_model,
        "reason": decision.reason,
        "original_error": _original_error_payload(exc),
        "config_block_hash": decision.config_block_hash,
    }


def append_fallback_audit_row(decision: FallbackAuditDecision, exc: Exception) -> None:
    """Append one R9 audit row, raising FallbackAuditError on any failure."""

    row = _decision_to_row(decision, exc)
    missing = {
        "event_type",
        "timestamp",
        "profile",
        "requested_model",
        "fallback_model",
        "reason",
        "original_error",
        "config_block_hash",
    } - set(row)
    if missing:
        raise FallbackAuditError(f"audit row missing required fields: {sorted(missing)}")
    try:
        payload = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        path = _resolve_audit_path(decision.audit_log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_LOCK:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    raise
    except FallbackAuditError:
        raise
    except Exception as exc2:
        raise FallbackAuditError(f"failed to append R9 fallback audit row: {exc2}") from exc2


def write_fallback_audit_row_or_raise(decision: FallbackAuditDecision, exc: Exception) -> None:
    """Compatibility wrapper with the ADR's fail-closed name."""

    append_fallback_audit_row(decision, exc)


def raise_policy_exception_for_decision(decision: FallbackAuditDecision) -> None:
    """Raise the structural policy exception represented by a blocked decision."""

    if decision.reason == "tusk_structural_gate":
        raise TuskNoFallbackError("Tusk is structurally prohibited from MiniMax fallback")
    if decision.reason == "fallback_disabled_profile":
        raise FallbackDisabledError("MiniMax fallback is disabled for this profile")
    if decision.reason == "fallback_disabled_global":
        raise FallbackDisabledError("MiniMax fallback is disabled by routing_policy.non_qc_specialists_with_fallback")
