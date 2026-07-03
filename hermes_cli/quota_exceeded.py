"""Typed quota-exceeded signal for R9 MiniMax fallback.

This module deliberately converts only the approved R9 source condition:
``openai-codex`` provider requesting exactly ``openai-codex/gpt-5.5`` and an
AuthError already classified by ``is_rate_limited_auth_error``.  All other
providers/models/errors raise ``QuotaNotApplicable`` so existing generic error
handling can proceed unchanged.
"""

from __future__ import annotations

from typing import Any


APPROVED_R9_PROVIDER = "openai-codex"
APPROVED_R9_REQUESTED_MODEL = "openai-codex/gpt-5.5"


class QuotaNotApplicable(RuntimeError):
    """Raised when an error is not the narrow R9 Codex GPT-5.5 quota signal."""


class QuotaExceeded(RuntimeError):
    """R9 dispatcher-level quota exhaustion signal.

    Attributes:
        provider: Provider that exhausted quota. R9 only permits
            ``openai-codex``.
        requested_model: Fully qualified requested model. R9 only permits
            ``openai-codex/gpt-5.5``.
        status_code: HTTP status code when known.
        code: Provider/auth error code when known.
        original_error: Original exception, preserved for normal error
            formatting and audit redaction.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        requested_model: str,
        status_code: int | None = None,
        code: str | None = None,
        original_error: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.requested_model = requested_model
        self.status_code = status_code
        self.code = code
        self.original_error = original_error


def _agent_requested_model(agent: Any) -> str:
    provider = (getattr(agent, "provider", "") or "").strip().lower()
    model = (getattr(agent, "model", "") or "").strip()
    return f"{provider}/{model}" if provider and "/" not in model else model


def quota_from_auth_error(exc: Exception, agent: Any) -> QuotaExceeded:
    """Convert a narrow Codex GPT-5.5 rate-limit AuthError to QuotaExceeded.

    If the exception is not an AuthError quota signal for provider
    ``openai-codex`` and requested model ``openai-codex/gpt-5.5``, this raises
    ``QuotaNotApplicable``.  Callers should catch that exception and continue
    through the pre-existing generic auth/rate-limit path.  The function never
    broadens R9 fallback to non-Codex providers or other Codex models.
    """

    from hermes_cli.auth import CODEX_RATE_LIMITED_CODE, AuthError, is_rate_limited_auth_error

    if not isinstance(exc, AuthError) or not is_rate_limited_auth_error(exc):
        raise QuotaNotApplicable("not a rate-limited AuthError")
    error_provider = (getattr(exc, "provider", "") or "").strip().lower()
    agent_provider = (getattr(agent, "provider", "") or "").strip().lower()
    if error_provider != APPROVED_R9_PROVIDER or agent_provider != APPROVED_R9_PROVIDER:
        raise QuotaNotApplicable("provider is not openai-codex")
    requested_model = _agent_requested_model(agent)
    if requested_model != APPROVED_R9_REQUESTED_MODEL:
        raise QuotaNotApplicable("requested model is not openai-codex/gpt-5.5")
    return QuotaExceeded(
        "Codex provider quota exhausted (429). Credentials are still valid; retry after the usage limit resets.",
        provider=APPROVED_R9_PROVIDER,
        requested_model=requested_model,
        status_code=getattr(exc, "status_code", None) or 429,
        code=getattr(exc, "code", None) or CODEX_RATE_LIMITED_CODE,
        original_error=exc,
    )


def quota_from_error_if_applicable(exc: Exception, agent: Any) -> QuotaExceeded | None:
    """Best-effort converter that returns ``None`` for non-R9 errors."""

    if isinstance(exc, QuotaExceeded):
        if (
            exc.provider == APPROVED_R9_PROVIDER
            and exc.requested_model == APPROVED_R9_REQUESTED_MODEL
        ):
            return exc
        return None
    try:
        return quota_from_auth_error(exc, agent)
    except QuotaNotApplicable:
        return None
