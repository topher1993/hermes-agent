"""R9 routing-policy loading and validation for MiniMax fallback.

The policy is intentionally fail-safe: global fallback and per-profile
fallback opt-in both default to ``False``.  Malformed values do not coerce to
truthy behavior for RED-risk model routing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath
from typing import Mapping, Sequence, cast


DEFAULT_QC_GRADE_MODEL = "openai-codex/gpt-5.5"
DEFAULT_FALLBACK_TARGET = "minimax-oauth/MiniMax-M3"
TUSK_FALLBACK_ACTION = "ERROR_AND_STOP"
DEFAULT_AUDIT_LOG_PATH = "state/audit/fallbacks.jsonl"


class RoutingPolicyError(RuntimeError):
    """Base class for R9 routing-policy failures."""


class TuskNoFallbackError(RoutingPolicyError):
    """Raised when a fallback attempt is structurally prohibited for Tusk."""


class FallbackDisabledError(RoutingPolicyError):
    """Raised when R9 fallback is not explicitly enabled."""


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating a raw ``routing_policy`` config block."""

    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class FallbackTarget:
    """Resolved fallback target for a profile.

    ``action`` is ``ERROR_AND_STOP`` for Tusk and ``fallback`` otherwise.
    ``provider`` and ``model`` are populated only for fallback targets.
    """

    profile: str
    action: str
    provider: str | None
    model: str | None
    spec: str | None


@dataclass(frozen=True)
class RoutingPolicy:
    """Normalized R9 routing policy with fail-safe defaults."""

    non_qc_specialists_with_fallback: bool = False
    qc_grade_models: tuple[str, ...] = (DEFAULT_QC_GRADE_MODEL,)
    fallback_default: str = DEFAULT_FALLBACK_TARGET
    fallback_tusk: str = TUSK_FALLBACK_ACTION
    fallback_signal_window_seconds: int = 300
    telegram_ping_threshold_in_window: int = 3
    telegram_ping_cooldown_seconds: int = 300
    audit_log_path: str = DEFAULT_AUDIT_LOG_PATH
    config_block_hash: str = field(default="", compare=False)

    def canonical_dict(self) -> dict[str, object]:
        """Return the normalized policy dict used for canonical hashing."""

        return {
            "audit_log_path": self.audit_log_path,
            "fallback_signal_window_seconds": self.fallback_signal_window_seconds,
            "fallback_target": {
                "default": self.fallback_default,
                "tusk": self.fallback_tusk,
            },
            "non_qc_specialists_with_fallback": self.non_qc_specialists_with_fallback,
            "qc_grade_models": list(self.qc_grade_models),
            "telegram_ping_cooldown_seconds": self.telegram_ping_cooldown_seconds,
            "telegram_ping_threshold_in_window": self.telegram_ping_threshold_in_window,
        }


def _canonical_hash(policy_dict: Mapping[str, object]) -> str:
    payload = json.dumps(policy_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _as_object_mapping(value: object) -> Mapping[object, object] | None:
    if isinstance(value, Mapping):
        return cast("Mapping[object, object]", value)
    return None


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _positive_int_or_default(value: object, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return default


def _is_provider_model_spec(value: object) -> bool:
    if not isinstance(value, str):
        return False
    cleaned = value.strip()
    return bool(cleaned and "/" in cleaned and not cleaned.startswith("/") and not cleaned.endswith("/"))


def _validate_audit_log_path(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return "audit_log_path must be a non-empty relative .jsonl path"
    cleaned = value.strip().replace("\\", "/")
    path = PurePosixPath(cleaned)
    if path.is_absolute() or ":" in path.parts[0]:
        return "audit_log_path must be relative to HERMES_HOME"
    if ".." in path.parts:
        return "audit_log_path must not contain '..'"
    if path.suffix != ".jsonl":
        return "audit_log_path must end with .jsonl"
    return None


def validate_routing_policy(block: object) -> ValidationResult:
    """Validate a raw ``routing_policy`` block from config.yaml.

    Missing blocks are valid and normalize to fail-safe defaults.  Invalid
    blocks are reported by errors; callers should raise/fail closed before
    activating fallback.
    """

    errors: list[str] = []
    warnings: list[str] = []
    if block is None:
        return ValidationResult(valid=True)
    data = _as_object_mapping(block)
    if data is None:
        return ValidationResult(valid=False, errors=("routing_policy must be a mapping",))

    non_qc = data.get("non_qc_specialists_with_fallback")
    if non_qc is not None and not isinstance(non_qc, bool):
        errors.append("routing_policy.non_qc_specialists_with_fallback must be a strict bool")

    qc_models = data.get("qc_grade_models")
    if qc_models is not None:
        if not isinstance(qc_models, Sequence) or isinstance(qc_models, (str, bytes)):
            errors.append("routing_policy.qc_grade_models must be a non-empty list of provider/model strings")
        else:
            cleaned = [m for m in qc_models if isinstance(m, str) and m.strip()]
            if not cleaned or any(not _is_provider_model_spec(m) for m in cleaned):
                errors.append("routing_policy.qc_grade_models must contain provider/model strings")

    target = data.get("fallback_target")
    target_data = _as_object_mapping(target)
    if target is not None and target_data is None:
        errors.append("routing_policy.fallback_target must be a mapping")
    elif target_data is not None:
        if "default" in target_data and not _is_provider_model_spec(target_data.get("default")):
            errors.append("routing_policy.fallback_target.default must be a provider/model string")
        tusk = target_data.get("tusk", TUSK_FALLBACK_ACTION)
        if tusk != TUSK_FALLBACK_ACTION:
            errors.append("routing_policy.fallback_target.tusk must be ERROR_AND_STOP")

    for key in (
        "fallback_signal_window_seconds",
        "telegram_ping_threshold_in_window",
        "telegram_ping_cooldown_seconds",
    ):
        value = data.get(key)
        if value is not None and not _is_positive_int(value):
            errors.append(f"routing_policy.{key} must be a positive integer")

    audit_value = data.get("audit_log_path", DEFAULT_AUDIT_LOG_PATH)
    audit_error = _validate_audit_log_path(audit_value)
    if audit_error:
        errors.append(audit_error)

    return ValidationResult(valid=not errors, errors=tuple(errors), warnings=tuple(warnings))


def _normalized_policy_from_block(block: object) -> RoutingPolicy:
    data = _as_object_mapping(block) or {}
    target_raw = data.get("fallback_target")
    target = _as_object_mapping(target_raw) or {}
    qc_raw = data.get("qc_grade_models")
    qc_models = (
        tuple(str(m).strip() for m in qc_raw)
        if isinstance(qc_raw, Sequence) and not isinstance(qc_raw, (str, bytes))
        else (DEFAULT_QC_GRADE_MODEL,)
    )
    non_qc_raw = data.get("non_qc_specialists_with_fallback")
    policy = RoutingPolicy(
        non_qc_specialists_with_fallback=non_qc_raw if isinstance(non_qc_raw, bool) else False,
        qc_grade_models=qc_models or (DEFAULT_QC_GRADE_MODEL,),
        fallback_default=str(target.get("default") or DEFAULT_FALLBACK_TARGET).strip(),
        fallback_tusk=str(target.get("tusk") or TUSK_FALLBACK_ACTION).strip(),
        fallback_signal_window_seconds=_positive_int_or_default(data.get("fallback_signal_window_seconds"), 300),
        telegram_ping_threshold_in_window=_positive_int_or_default(data.get("telegram_ping_threshold_in_window"), 3),
        telegram_ping_cooldown_seconds=_positive_int_or_default(data.get("telegram_ping_cooldown_seconds"), 300),
        audit_log_path=str(data.get("audit_log_path") or DEFAULT_AUDIT_LOG_PATH).strip().replace("\\", "/"),
    )
    canonical = policy.canonical_dict()
    return replace(policy, config_block_hash=_canonical_hash(canonical))


def load_routing_policy() -> RoutingPolicy:
    """Load and validate the R9 routing policy from config.yaml."""

    from hermes_cli.config import load_config_readonly

    cfg = load_config_readonly()
    block = cfg.get("routing_policy") if isinstance(cfg, Mapping) else None
    result = validate_routing_policy(block)
    if not result.valid:
        raise RoutingPolicyError("Invalid routing_policy: " + "; ".join(result.errors))
    policy = _normalized_policy_from_block(block)
    if policy.fallback_tusk != TUSK_FALLBACK_ACTION:
        raise RoutingPolicyError("routing_policy.fallback_target.tusk must be ERROR_AND_STOP")
    audit_error = _validate_audit_log_path(policy.audit_log_path)
    if audit_error:
        raise RoutingPolicyError(audit_error)
    return policy


def get_fallback_target(profile: str) -> FallbackTarget:
    """Return the configured fallback target for ``profile``.

    Tusk is always represented as ``ERROR_AND_STOP`` regardless of other config.
    """

    normalized = (profile or "").strip().lower()
    policy = load_routing_policy()
    if normalized == "tusk":
        return FallbackTarget(profile=normalized, action=TUSK_FALLBACK_ACTION, provider=None, model=None, spec=None)
    provider, _, model = policy.fallback_default.partition("/")
    return FallbackTarget(
        profile=normalized,
        action="fallback",
        provider=provider.strip().lower() or None,
        model=model.strip() or None,
        spec=policy.fallback_default,
    )


def profile_allows_minimax_fallback(profile: str) -> bool:
    """Return the strict per-profile MiniMax fallback opt-in value.

    Missing, malformed, or loose truthy values all fail safe to ``False``.
    """

    try:
        import yaml
        from hermes_cli.profiles import get_profile_dir, normalize_profile_name

        profile_dir = get_profile_dir(normalize_profile_name(profile or "default"))
        path = profile_dir / "profile.yaml"
        if not path.is_file():
            return False
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, Mapping):
            return False
        return loaded.get("allow_minimax_fallback") is True
    except Exception:
        return False
