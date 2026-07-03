from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


class R9FakeAgent:
    def __init__(self, *, provider: str = "openai-codex", model: str = "gpt-5.5") -> None:
        self.provider = provider
        self.model = model
        self.base_url = "https://chatgpt.com/backend-api/codex"
        self.api_mode = "codex_responses"
        self.api_key = "primary-token"
        self.client = object()
        self._fallback_chain: list[dict[str, Any]] = []
        self._fallback_index = 0
        self._fallback_activated = False
        self._primary_runtime = {"provider": provider, "model": model}
        self._rate_limited_until = 0
        self._unavailable_fallback_keys: set[tuple[str, str, str]] = set()
        self._transport_cache: dict[str, Any] = {}
        self._credential_pool = None
        self._config_context_length = None
        self._cached_system_prompt = "Model: gpt-5.5\nProvider: openai-codex"
        self.context_compressor = None
        self.statuses: list[str] = []

    def _try_activate_fallback(self, reason=None) -> bool:
        from agent.chat_completion_helpers import try_activate_fallback

        return try_activate_fallback(self, reason)

    def _is_azure_openai_url(self, base_url: str) -> bool:
        return False

    def _is_direct_openai_url(self, base_url: str) -> bool:
        return False

    def _provider_model_requires_responses_api(self, model: str, *, provider: str) -> bool:
        return False

    def _anthropic_prompt_cache_policy(self, **_: Any) -> tuple[bool, bool]:
        return False, False

    def _ensure_lmstudio_runtime_loaded(self) -> None:
        return None

    def _buffer_status(self, message: str) -> None:
        self.statuses.append(message)


def _write_yaml(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _activate_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str) -> Path:
    root = tmp_path / "r9_home"
    profile_home = root / "profiles" / profile
    profile_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(profile_home))
    return profile_home


def _write_profile(profile_home: Path, *, allow: bool | str | None) -> None:
    if allow is None:
        body = "description: R9 test profile\ndescription_auto: false"
    elif isinstance(allow, bool):
        body = f"description: R9 test profile\ndescription_auto: false\nallow_minimax_fallback: {str(allow).lower()}"
    else:
        body = f"description: R9 test profile\ndescription_auto: false\nallow_minimax_fallback: {allow!r}"
    _write_yaml(profile_home / "profile.yaml", body)


def _write_config(
    profile_home: Path,
    *,
    global_enabled: bool = True,
    audit_log_path: str = "state/audit/fallbacks.jsonl",
    fallback_providers: str = "",
) -> None:
    fallback_block = fallback_providers or "[]"
    _write_yaml(
        profile_home / "config.yaml",
        f"""
model: gpt-5.5
provider: openai-codex
fallback_providers: {fallback_block}
routing_policy:
  non_qc_specialists_with_fallback: {str(global_enabled).lower()}
  qc_grade_models:
    - openai-codex/gpt-5.5
  fallback_target:
    default: minimax-oauth/MiniMax-M3
    tusk: ERROR_AND_STOP
  fallback_signal_window_seconds: 300
  telegram_ping_threshold_in_window: 3
  telegram_ping_cooldown_seconds: 300
  audit_log_path: {audit_log_path}
""",
    )


def _quota_exc() -> Any:
    from hermes_cli.quota_exceeded import QuotaExceeded

    return QuotaExceeded(
        "Codex provider quota exhausted",
        provider="openai-codex",
        requested_model="openai-codex/gpt-5.5",
        status_code=429,
        code="codex_rate_limited",
    )


def _install_minimax_oauth_test_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    import agent.anthropic_adapter as anthropic_adapter
    import hermes_cli.auth as auth

    token_provider = lambda: "oauth-access-token"  # noqa: E731 - deliberately callable token provider
    monkeypatch.setattr(
        auth,
        "resolve_minimax_oauth_runtime_credentials",
        lambda *, as_token_provider=False: {
            "api_key": token_provider if as_token_provider else "oauth-access-token",
            "base_url": "https://api.minimax.io/anthropic",
        },
    )
    monkeypatch.setattr(
        anthropic_adapter,
        "build_anthropic_client",
        lambda api_key, base_url, timeout=None: SimpleNamespace(api_key=api_key, base_url=base_url),
    )
    monkeypatch.setattr(anthropic_adapter, "_is_oauth_token", lambda token: callable(token))


def test_real_config_load_validation_profile_opt_in_and_audit_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile_home = _activate_profile(tmp_path, monkeypatch, "igris")
    _write_profile(profile_home, allow=True)
    _write_config(profile_home)

    from agent.routing_policy_audit import evaluate_r9_routing_policy, write_fallback_audit_row_or_raise
    from hermes_cli.config import load_config_readonly
    from hermes_cli.routing_policy import load_routing_policy, profile_allows_minimax_fallback, validate_routing_policy

    config = load_config_readonly()
    validation = validate_routing_policy(config.get("routing_policy"))
    assert validation.valid, validation.errors

    policy = load_routing_policy()
    assert policy.non_qc_specialists_with_fallback is True
    assert policy.fallback_default == "minimax-oauth/MiniMax-M3"
    assert profile_allows_minimax_fallback("igris") is True

    decision = evaluate_r9_routing_policy(R9FakeAgent(), _quota_exc())
    write_fallback_audit_row_or_raise(decision, _quota_exc())

    audit_log = profile_home / "state" / "audit" / "fallbacks.jsonl"
    rows = [json.loads(line) for line in audit_log.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["event_type"] == "fallback_activated"
    assert rows[0]["profile"] == "igris"
    assert rows[0]["requested_model"] == "openai-codex/gpt-5.5"
    assert rows[0]["fallback_model"] == "minimax-oauth/MiniMax-M3"
    assert rows[0]["reason"] == "quota_exceeded"
    assert rows[0]["original_error"]["code"] == "codex_rate_limited"
    assert rows[0]["config_block_hash"] == policy.config_block_hash


def test_existing_fallback_providers_minimax_entry_goes_through_try_activate_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_home = _activate_profile(tmp_path, monkeypatch, "igris")
    _write_profile(profile_home, allow=True)
    _write_config(
        profile_home,
        fallback_providers='[{"provider": "minimax-oauth", "model": "MiniMax-M3"}]',
    )
    _install_minimax_oauth_test_hooks(monkeypatch)

    from agent.chat_completion_helpers import try_activate_fallback
    from hermes_cli.fallback_config import get_fallback_chain
    from hermes_cli.config import load_config_readonly
    from run_agent import FailoverReason

    agent = R9FakeAgent()
    agent._fallback_chain = get_fallback_chain(load_config_readonly())

    assert try_activate_fallback(agent, reason=FailoverReason.rate_limit) is True
    assert agent.provider == "minimax-oauth"
    assert agent.model == "MiniMax-M3"
    assert agent.api_mode == "anthropic_messages"
    assert str(agent.base_url).rstrip("/") == "https://api.minimax.io/anthropic"
    assert callable(agent.api_key)
    assert "MiniMax-M3 via minimax-oauth" in agent.statuses[-1]


def test_audit_write_failure_is_fail_closed_before_try_activate_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_home = _activate_profile(tmp_path, monkeypatch, "igris")
    _write_profile(profile_home, allow=True)
    _write_config(profile_home, audit_log_path="state/audit/fallbacks.jsonl")
    # Block real file I/O cross-platform: the parent directory path is occupied by a file.
    blocked_parent = profile_home / "state" / "audit"
    blocked_parent.parent.mkdir(parents=True, exist_ok=True)
    blocked_parent.write_text("not a directory", encoding="utf-8")

    from agent.routing_policy_audit import FallbackAuditError, evaluate_r9_routing_policy, write_fallback_audit_row_or_raise

    agent = R9FakeAgent()
    decision = evaluate_r9_routing_policy(agent, _quota_exc())
    with pytest.raises(FallbackAuditError):
        write_fallback_audit_row_or_raise(decision, _quota_exc())

    assert agent.provider == "openai-codex"
    assert agent.model == "gpt-5.5"
    assert agent._fallback_activated is False


def test_minimax_oauth_provider_resolution_uses_oauth_branch_not_api_key_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_home = _activate_profile(tmp_path, monkeypatch, "igris")
    _write_profile(profile_home, allow=True)
    _write_config(profile_home)
    monkeypatch.setenv("MINIMAX_API_KEY", "api-key-path-must-not-be-used")
    _install_minimax_oauth_test_hooks(monkeypatch)

    from agent.auxiliary_client import resolve_provider_client

    client, resolved_model = resolve_provider_client("minimax-oauth", model="MiniMax-M3")

    assert client is not None
    assert resolved_model == "MiniMax-M3"
    assert str(client.base_url).rstrip("/") == "https://api.minimax.io/anthropic"
    assert callable(client.api_key)
    assert client.api_key() == "oauth-access-token"
    assert client.api_key != "api-key-path-must-not-be-used"


def test_real_config_defaults_are_false_false_and_minimax_oauth_m3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile_home = _activate_profile(tmp_path, monkeypatch, "igris")
    _write_profile(profile_home, allow=None)
    _write_yaml(profile_home / "config.yaml", "model: gpt-5.5\nprovider: openai-codex")

    from hermes_cli.routing_policy import load_routing_policy, profile_allows_minimax_fallback

    policy = load_routing_policy()
    assert policy.non_qc_specialists_with_fallback is False
    assert profile_allows_minimax_fallback("igris") is False
    assert policy.fallback_default == "minimax-oauth/MiniMax-M3"
    assert policy.qc_grade_models == ("openai-codex/gpt-5.5",)
