from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.test_r9_integration import (
    R9FakeAgent,
    _activate_profile,
    _install_minimax_oauth_test_hooks,
    _quota_exc,
    _write_config,
    _write_profile,
)


def test_tusk_structural_guard_never_mutates_provider_or_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_home = _activate_profile(tmp_path, monkeypatch, "tusk")
    _write_profile(profile_home, allow=False)
    _write_config(
        profile_home,
        global_enabled=True,
        fallback_providers='[{"provider": "minimax-oauth", "model": "MiniMax-M3"}]',
    )

    from agent.chat_completion_helpers import try_activate_fallback
    from hermes_cli.routing_policy import TuskNoFallbackError
    from run_agent import FailoverReason

    agent = R9FakeAgent()
    agent._fallback_chain = [{"provider": "minimax-oauth", "model": "MiniMax-M3"}]

    with pytest.raises(TuskNoFallbackError):
        try_activate_fallback(agent, reason=FailoverReason.rate_limit)

    assert agent.provider == "openai-codex"
    assert agent.model == "gpt-5.5"
    assert agent._fallback_index == 0
    assert agent._fallback_activated is False


def test_global_false_blocks_fallback_even_when_profile_opt_in_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_home = _activate_profile(tmp_path, monkeypatch, "igris")
    _write_profile(profile_home, allow=True)
    _write_config(profile_home, global_enabled=False)

    from agent.routing_policy_audit import evaluate_r9_routing_policy

    decision = evaluate_r9_routing_policy(R9FakeAgent(), _quota_exc())

    assert decision.event_type == "blocked_no_fallback"
    assert decision.reason == "fallback_disabled_global"
    assert decision.fallback_model is None


def test_profile_false_blocks_fallback_even_when_global_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_home = _activate_profile(tmp_path, monkeypatch, "igris")
    _write_profile(profile_home, allow=False)
    _write_config(profile_home, global_enabled=True)

    from agent.routing_policy_audit import evaluate_r9_routing_policy

    decision = evaluate_r9_routing_policy(R9FakeAgent(), _quota_exc())

    assert decision.event_type == "blocked_no_fallback"
    assert decision.reason == "fallback_disabled_profile"
    assert decision.fallback_model is None


def test_audit_write_precedes_fallback_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile_home = _activate_profile(tmp_path, monkeypatch, "igris")
    _write_profile(profile_home, allow=True)
    _write_config(profile_home)
    _install_minimax_oauth_test_hooks(monkeypatch)

    from agent.routing_policy_audit import evaluate_r9_routing_policy, write_fallback_audit_row_or_raise
    from agent.conversation_loop import _prepare_r9_fallback_chain
    from run_agent import FailoverReason

    agent = R9FakeAgent()
    decision = evaluate_r9_routing_policy(agent, _quota_exc())
    audit_log = profile_home / "state" / "audit" / "fallbacks.jsonl"

    assert not audit_log.exists()
    assert agent.provider == "openai-codex"

    write_fallback_audit_row_or_raise(decision, _quota_exc())
    rows_before_fallback = [json.loads(line) for line in audit_log.read_text(encoding="utf-8").splitlines()]
    assert rows_before_fallback[-1]["event_type"] == "fallback_activated"
    assert agent.provider == "openai-codex"
    assert agent.model == "gpt-5.5"

    _prepare_r9_fallback_chain(agent, decision.fallback_model)
    assert agent._try_activate_fallback(reason=FailoverReason.rate_limit) is True
    assert agent.provider == "minimax-oauth"
    assert agent.model == "MiniMax-M3"


def test_non_quota_errors_do_not_activate_r9_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile_home = _activate_profile(tmp_path, monkeypatch, "igris")
    _write_profile(profile_home, allow=True)
    _write_config(profile_home, global_enabled=True)

    from agent.conversation_loop import _r9_quota_from_error
    from hermes_cli.auth import AuthError

    agent = R9FakeAgent(provider="openai-codex", model="gpt-5.5")

    assert _r9_quota_from_error(ConnectionError("network down"), agent) is None
    assert _r9_quota_from_error(
        AuthError("invalid token", provider="openai-codex", code="invalid_token", relogin_required=True),
        agent,
    ) is None
    assert _r9_quota_from_error(AuthError("other provider 429", provider="anthropic", code="codex_rate_limited"), agent) is None


def test_provider_guard_requires_openai_codex_gpt55_before_r9_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_home = _activate_profile(tmp_path, monkeypatch, "igris")
    _write_profile(profile_home, allow=True)
    _write_config(profile_home, global_enabled=True)

    from agent.conversation_loop import _r9_quota_from_error
    from hermes_cli.auth import AuthError

    quota_error = AuthError(
        "rate limited",
        provider="openai-codex",
        code="codex_rate_limited",
        relogin_required=False,
    )

    assert _r9_quota_from_error(quota_error, R9FakeAgent(provider="openai-codex", model="gpt-5")) is None
    assert _r9_quota_from_error(quota_error, R9FakeAgent(provider="openrouter", model="gpt-5.5")) is None
    quota = _r9_quota_from_error(quota_error, R9FakeAgent(provider="openai-codex", model="gpt-5.5"))
    assert quota is not None
    assert quota.provider == "openai-codex"
    assert quota.requested_model == "openai-codex/gpt-5.5"


def test_tusk_blocked_event_written_even_when_fallback_target_default_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_home = _activate_profile(tmp_path, monkeypatch, "tusk")
    _write_profile(profile_home, allow=False)
    _write_config(
        profile_home,
        global_enabled=True,
        fallback_providers='[{"provider": "unreachable-provider", "model": "Nope"}]',
    )

    from agent.routing_policy_audit import (
        evaluate_r9_routing_policy,
        raise_policy_exception_for_decision,
        write_fallback_audit_row_or_raise,
    )
    from hermes_cli.routing_policy import TuskNoFallbackError

    agent = R9FakeAgent()
    agent._fallback_chain = [{"provider": "unreachable-provider", "model": "Nope"}]
    decision = evaluate_r9_routing_policy(agent, _quota_exc())
    write_fallback_audit_row_or_raise(decision, _quota_exc())

    with pytest.raises(TuskNoFallbackError):
        raise_policy_exception_for_decision(decision)

    rows = [json.loads(line) for line in (profile_home / "state" / "audit" / "fallbacks.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["event_type"] == "blocked_no_fallback"
    assert rows[-1]["profile"] == "tusk"
    assert rows[-1]["fallback_model"] is None
    assert rows[-1]["reason"] == "tusk_structural_gate"
    assert agent.provider == "openai-codex"
    assert agent.model == "gpt-5.5"


def test_r9_fallback_truncates_chain_and_prevents_third_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_home = _activate_profile(tmp_path, monkeypatch, "igris")
    _write_profile(profile_home, allow=True)
    _write_config(
        profile_home,
        global_enabled=True,
        fallback_providers='[{"provider": "minimax-oauth", "model": "MiniMax-M3"}, {"provider": "third-provider", "model": "ThirdModel"}]',
    )
    _install_minimax_oauth_test_hooks(monkeypatch)

    from agent.conversation_loop import _prepare_r9_fallback_chain
    from run_agent import FailoverReason

    agent = R9FakeAgent()
    agent._fallback_chain = [
        {"provider": "deepseek", "model": "deepseek-chat"},
        {"provider": "third-provider", "model": "ThirdModel"},
    ]

    _prepare_r9_fallback_chain(agent, "minimax-oauth/MiniMax-M3")

    assert agent._fallback_chain == [{"provider": "minimax-oauth", "model": "MiniMax-M3"}]
    assert agent._try_activate_fallback(reason=FailoverReason.rate_limit) is True
    assert agent.provider == "minimax-oauth"
    assert agent.model == "MiniMax-M3"

    # A subsequent MiniMax failure in the same dispatch must hard-fail rather
    # than walking the pre-existing third-provider tail.
    assert agent._try_activate_fallback(reason=FailoverReason.rate_limit) is False
    assert agent.provider == "minimax-oauth"
    assert agent.model == "MiniMax-M3"


def test_non_r9_existing_fallback_path_does_not_require_minimax_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_home = _activate_profile(tmp_path, monkeypatch, "igris")
    _write_profile(profile_home, allow=False)
    _write_config(
        profile_home,
        global_enabled=False,
        fallback_providers='[{"provider": "custom-openai", "model": "CustomModel", "base_url": "https://example.test/v1", "api_key": "fallback-key"}]',
    )

    import agent.auxiliary_client as auxiliary_client
    from agent.chat_completion_helpers import try_activate_fallback
    from run_agent import FailoverReason

    def fake_resolve_provider_client(
        provider: str,
        *,
        model: str | None = None,
        raw_codex: bool = False,
        explicit_base_url: str | None = None,
        explicit_api_key: str | None = None,
        **_: Any,
    ) -> tuple[SimpleNamespace, str | None]:
        return SimpleNamespace(api_key=explicit_api_key or "fallback-key", base_url=explicit_base_url or "https://example.test/v1"), model

    monkeypatch.setattr(auxiliary_client, "resolve_provider_client", fake_resolve_provider_client)

    agent = R9FakeAgent(provider="openrouter", model="primary-model")
    agent._fallback_chain = [
        {"provider": "custom-openai", "model": "CustomModel", "base_url": "https://example.test/v1", "api_key": "fallback-key"}
    ]

    assert try_activate_fallback(agent, reason=None) is True
    assert agent.provider == "custom-openai"
    assert agent.model == "CustomModel"
    assert agent._fallback_activated is True
