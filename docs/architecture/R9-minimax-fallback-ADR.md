# R9-MINIMAX-FALLBACK Architecture Decision Record

## 1. Status / Date / Owner / Work card ref

Status: Proposed for R9 implementation.
Date: 2026-07-03.
Owner: Atlas, Tier-3 Architecture Specialist.
Work card: `C:/Users/tophe/AppData/Local/hermes/agent-army/work-cards/R9-MINIMAX-FALLBACK.md`.
Authoritative policy input: `/tmp/iron-r9-policy-draft.md`, drafted 2026-07-03.
Path decision: Path A — in-framework integration on branch `feat/r9-minimax-fallback` after Tusk pre-flight approval.
Risk class: RED — routing policy plus Tusk-grade integrity.

## 2. Decision

R9 introduces an opt-in routing policy for Chris's Agent Army specialist dispatch. When quota exhaustion hits an `openai-codex/gpt-5.5` dispatch from a non-QC specialist profile, and both the global routing policy and the active profile explicitly opt in, the dispatcher writes an audit row and switches the active provider/model to MiniMax-M3 for the retry.

Tusk is structurally protected. Tusk never falls back, even if `fallback_providers` or another existing fallback chain has a MiniMax entry. The Tusk gate must be enforced in code before any fallback target/model mutation, not only by profile config, prompt text, or operator convention.

All fallback events write an append-only audit row before proceeding. Audit write failure is fail-closed: no audit row means no fallback. Operator Telegram pings notify when at least 3 fallback/blocked events hit the configured 5-minute window; the ping is operational and non-blocking, while the audit write is integrity-critical and blocking.

R9 extends the existing fallback and quota surfaces instead of duplicating them:

- `hermes_cli/auth.py` already exposes `CODEX_RATE_LIMITED_CODE` and `is_rate_limited_auth_error()` for Codex quota/rate-limit classification.
- `hermes_cli/config.py` already has `fallback_providers` in `DEFAULT_CONFIG`.
- `hermes_cli/fallback_config.py` already merges `fallback_providers` and legacy `fallback_model`.
- `agent/agent_init.py` already initializes `agent._fallback_chain`.
- `agent/chat_completion_helpers.py::try_activate_fallback()` is already the central provider/model mutation point.
- `run_agent.py::_try_activate_fallback()` already forwards all AIAgent fallback activation through `try_activate_fallback()`.

R9 must not add a parallel fallback manager, a new core model tool, or new user-facing `HERMES_*` environment variables.

## 3. Verified existing files cited

Repository state verified before writing this ADR:

- Source: `C:/Users/tophe/AppData/Local/hermes/hermes-agent/`.
- Branch: `main`.
- HEAD: `65d45a0013238921b35f17b0d9d287ecaf898445`.
- Git status at verification: `main...origin/main [ahead 1, behind 1]`.

Verified files and line ranges:

1. `hermes_cli/auth.py` lines 711-746
   - Defines `CODEX_RATE_LIMITED_CODE = "codex_rate_limited"`, `AuthError`, and `is_rate_limited_auth_error()`.
   - Iron cite remains accurate.

2. `hermes_cli/auth.py` lines 3601-3623
   - `refresh_codex_oauth_pure()` handles token-refresh HTTP 429 and raises `AuthError(provider="openai-codex", code=CODEX_RATE_LIMITED_CODE, relogin_required=False)`.
   - Iron cite remains accurate.

3. `hermes_cli/auth.py` lines 3843-3848, 7323-7328, 7430-7435
   - Additional `CODEX_RATE_LIMITED_CODE` raises for Codex pool rate-limit state and login/device-token 429 throttling.
   - Iron's first range was 3842-3848; current raise statement starts at 3843, with message ending at 3842. No material shift.

4. `hermes_cli/config.py` lines 895-899
   - `DEFAULT_CONFIG` includes `"fallback_providers": []`.
   - Iron cite remains accurate.

5. `hermes_cli/fallback_config.py` lines 1-72
   - Reads the effective fallback chain from config.
   - `get_fallback_chain()` merges `fallback_providers` and legacy `fallback_model` with de-duplication.
   - Iron cite remains accurate.

6. `agent/agent_init.py` lines 1004-1020
   - Initializes `agent._fallback_chain`, `_fallback_index`, `_fallback_activated`, and legacy `_fallback_model`.
   - Iron cite remains accurate.

7. `agent/chat_completion_helpers.py::try_activate_fallback()` lines 1114-1329 shown during verification
   - Function starts at line 1114.
   - Current first executable fallback logic starts at line 1126 with rate-limit/billing cooldown handling.
   - Chain exhaustion check is lines 1135-1151.
   - First fallback entry is read and index advanced at lines 1152-1155.
   - Existing provider/model/base_url/api_mode mutation is lines 1259-1262.
   - R9 structural gate must be inserted immediately after the docstring, before current line 1126 and before lines 1152-1155 or 1259-1262.

8. `agent/chat_completion_helpers.py::interruptible_api_call()` lines 154-279 shown during verification
   - API call wrapper starts at line 154.
   - Worker call branches route Codex Responses, Anthropic Messages, Bedrock, MoA, and chat completions.
   - Exceptions are captured inside `_call()` beginning at line 274; R9 exception classification must integrate with the existing conversation-loop error classification rather than bypass the wrapper.

9. `run_agent.py::_try_activate_fallback()` lines 4392-4395
   - AIAgent forwarder imports and calls `agent.chat_completion_helpers.try_activate_fallback()`.
   - Iron cite remains accurate.

10. `profiles/tusk/profile.yaml` lines 1-2
    - Current content only:
      - `description: Tusk command profile for Agent Army v2.0 under Belion`
      - `description_auto: false`
    - No existing `allow_minimax_fallback` field.

11. `profiles/iron/profile.yaml` lines 1-2
    - Current content only:
      - `description: Iron command profile for Agent Army v2.0 under Belion`
      - `description_auto: false`
    - No existing `allow_minimax_fallback` field.

12. `AGENTS.md` contribution rubric clauses verified:
    - Prompt caching and narrow waist: lines 19-27.
    - Contribution rubric context: lines 29-50.
    - Fix real bugs / sibling paths: lines 54-57.
    - Expand reach at edges without raw env var: lines 58-64.
    - Keep core narrow / Footprint Ladder pointer: lines 71-74.
    - Extend, don't duplicate: lines 75-79.
    - Behavior contracts over snapshots: lines 80-83.
    - E2E validation: lines 84-87.
    - Cache-, alternation-, invariant-safe: lines 88-91.
    - Speculative infrastructure: lines 98-101.
    - No new `HERMES_*` env vars for non-secret config: lines 102-107.
    - No new core tool when terminal + file / skill suffice: lines 108-110.
    - Outbound telemetry opt-in: lines 118-121.
    - Change-detector / cache-breaking / plugin core-touch warning: lines 122-125.
    - Footprint Ladder: lines 182-211.
    - Adding config: lines 582-590.
    - Non-secret settings belong in `config.yaml`: lines 608-623.
    - Use `get_hermes_home()` for profile-safe state paths: lines 1214-1219.
    - E2E test wrapper and hermetic test expectations: lines 1279-1293.
    - Do not write change-detector tests: lines 1352-1399.

Scope shifts found during verification:

- `agent/auxiliary_client.py::_normalize_aux_provider()` lines 184-235 does not currently alias plain `minimax` to `minimax-oauth`; it only aliases `minimax-china` and `minimax_cn` to `minimax-cn`.
- `hermes_cli/auth.py::_resolve_provider()` lines 1535-1581 aliases `minimax-portal`, `minimax-global`, and `minimax_oauth` to `minimax-oauth`, but not plain `minimax`.
- `agent/auxiliary_client.py::resolve_provider_client()` lines 4477-4488 handles OAuth providers with auth types `oauth_device_code` and `oauth_external`, but does not handle `oauth_minimax`; the unhandled-auth-type fallback is lines 4490-4492. If R9 config uses `minimax-oauth/MiniMax-M3`, implementation must add an explicit `oauth_minimax` resolver branch or fallback activation through `resolve_provider_client()` will not resolve MiniMax OAuth. This is a material implementation scope item and is repeated in Open Questions / scope contradictions.

## 4. AGENTS.md rubric compliance verdict

1. Clause: "The core is a narrow waist; capability lives at the edges." (`AGENTS.md` lines 24-27)
   Verdict: PASS-with-tension.
   Rationale: R9 touches core routing, but it does not add a model tool or per-call tool schema. The footprint is acceptable only because GPT-5.5 quota exhaustion is an actual Agent Army operational failure and the change extends existing auth/fallback surfaces.

2. Clause: "Speculative infrastructure. Hooks, callbacks, or extension points with no concrete consumer." (`AGENTS.md` lines 98-101)
   Verdict: PASS.
   Rationale: The Kaisel `notifyFallbackWindow` hook has one concrete consumer: Chris operator notification for R9 fallback windows. R9 must not generalize it into a broad event bus.

3. Clause: "Extend, don't duplicate." (`AGENTS.md` lines 75-79)
   Verdict: PASS if implemented per this ADR; VIOLATE if a new parallel fallback manager is created.
   Rationale: R9 must extend `CODEX_RATE_LIMITED_CODE`, `fallback_providers`, `_fallback_chain`, and `try_activate_fallback()`. Creating a second fallback manager or quota detector detached from these surfaces would duplicate existing infrastructure.

4. Clause: "New `HERMES_*` env vars for non-secret config." (`AGENTS.md` lines 102-107)
   Verdict: PASS.
   Rationale: All new behavior is expressed in `config.yaml` under `routing_policy` and in `profile.yaml` under `allow_minimax_fallback`. No new user-facing non-secret env var is proposed.

5. Clause: "Cache-, alternation-, and invariant-safe." (`AGENTS.md` lines 88-91)
   Verdict: PASS-with-implementation-conditions.
   Rationale: R9 must not inject synthetic messages, mutate past messages, swap toolsets, reload skills, or rebuild the system prompt as a policy side effect. Existing fallback code already syncs provider/model after fallback; R9 must preserve byte-stable prompt rules as much as the existing fallback path allows.

6. Clause: "Behavior contracts over snapshots." (`AGENTS.md` lines 80-83 and 1352-1399)
   Verdict: PASS.
   Rationale: R9 tests should assert invariants: Tusk never mutates provider/model; global false blocks fallback; profile false blocks fallback; audit write precedes fallback; non-quota errors do not fallback. Tests must not freeze provider catalog counts, config version literals, or exact model-list snapshots.

7. Clause: "E2E validation, not just green unit mocks." (`AGENTS.md` lines 84-87 and 1279-1293)
   Verdict: PASS-required.
   Rationale: R9 crosses config propagation, profile loading, auth classification, fallback mutation, audit file I/O, and notifier triggering. Unit tests are not enough; at least one integration test must run with a temp `HERMES_HOME` and real config/profile files.

8. Clause: "Outbound telemetry / usage attribution without opt-in gating." (`AGENTS.md` lines 118-121)
   Verdict: N/A-to-PASS-with-limits.
   Rationale: Telegram ping is first-party operator notification through Chris's configured Hermes gateway, not analytics attribution. The ping must avoid prompts, raw chat text, full error bodies, secrets, and PII unless Chris explicitly approves expanded fields.

9. Clause: "A new core tool when terminal + file already do the job, or when a skill would." (`AGENTS.md` lines 108-110)
   Verdict: N/A.
   Rationale: R9 adds no new model-facing tool.

10. Clause: "Plugins that touch core files." (`AGENTS.md` lines 122-125 and 779-784)
    Verdict: N/A under Chris's binding Path A.
    Rationale: Chris chose in-framework integration on a feature branch. This is not a plugin modifying core files; it is an explicit core routing change with Tusk pre-flight required.

## 5. Data shape / schema

### Routing policy YAML block

Defaults must match Chris's binding decisions: both fallback flags default to false. Operators opt in explicitly per profile and globally.

```yaml
routing_policy:
  non_qc_specialists_with_fallback: false
  qc_grade_models:
    - openai-codex/gpt-5.5
  fallback_target:
    default: minimax-oauth/MiniMax-M3
    tusk: ERROR_AND_STOP
  fallback_signal_window_seconds: 300
  telegram_ping_threshold_in_window: 3
  telegram_ping_cooldown_seconds: 300
  audit_log_path: state/audit/fallbacks.jsonl
```

Recommended validation rules:

- `routing_policy` must be a mapping when present.
- `non_qc_specialists_with_fallback` must be a strict bool; default false.
- `qc_grade_models` must be a non-empty list of provider/model strings; R9 default is exactly `openai-codex/gpt-5.5`.
- `fallback_target.default` must be a provider/model string. This ADR recommends `minimax-oauth/MiniMax-M3`, not `minimax/MiniMax-M3`, because local context says MiniMax is wired through `auth.json` active provider `minimax-oauth`.
- `fallback_target.tusk` must be `ERROR_AND_STOP` in R9.
- `fallback_signal_window_seconds` defaults to 300.
- `telegram_ping_threshold_in_window` defaults to 3.
- `telegram_ping_cooldown_seconds` defaults to 300.
- `audit_log_path` must be relative to `get_hermes_home()`, must not contain `..`, and must end in `.jsonl`.

### Per-profile field

Default for every profile is false. Tusk must also be set false explicitly by implementation for grep-able defense, but this ADR does not modify profile files.

```yaml
allow_minimax_fallback: false
```

Opt-in example for a non-QC specialist profile:

```yaml
description: Iron command profile for Agent Army v2.0 under Belion
description_auto: false
allow_minimax_fallback: true
```

Tusk required implementation target:

```yaml
description: Tusk command profile for Agent Army v2.0 under Belion
description_auto: false
allow_minimax_fallback: false
```

Malformed profile values must fail safe as false and should emit a validation warning. Do not coerce loose truthy strings such as `"yes"` for this RED-risk gate.

### Audit row JSONL shape

R9 uses a single append-only file: `state/audit/fallbacks.jsonl`, resolved under `get_hermes_home()`.

Because Tusk blocked events are not fallback events but still require reviewability, this ADR expands the schema with `event_type`. Fallback events use `event_type: "fallback_activated"`; Tusk blocked events use `event_type: "blocked_no_fallback"`.

Fallback event example:

```json
{"event_type":"fallback_activated","timestamp":"2026-07-03T00:00:00Z","profile":"iron","requested_model":"openai-codex/gpt-5.5","fallback_model":"minimax-oauth/MiniMax-M3","reason":"quota_exceeded","original_error":{"type":"QuotaExceeded","message":"Codex provider quota exhausted (429). Credentials are still valid; retry after the usage limit resets.","status_code":429,"code":"codex_rate_limited"},"config_block_hash":"<sha256-hex>"}
```

Tusk blocked event example:

```json
{"event_type":"blocked_no_fallback","timestamp":"2026-07-03T00:00:00Z","profile":"tusk","requested_model":"openai-codex/gpt-5.5","fallback_model":null,"reason":"tusk_structural_gate","original_error":{"type":"QuotaExceeded","message":"Codex provider quota exhausted (429). Credentials are still valid; retry after the usage limit resets.","status_code":429,"code":"codex_rate_limited"},"config_block_hash":"<sha256-hex>"}
```

Field contract:

- `event_type`: enum. R9 values: `fallback_activated`, `blocked_no_fallback`.
- `timestamp`: ISO-8601 UTC with `Z` suffix.
- `profile`: active profile name, e.g. `iron`, `igris`, `kaisel`, `tusk`, or `default`.
- `requested_model`: provider/model originally requested.
- `fallback_model`: provider/model selected for fallback, or `null` for blocked events.
- `reason`: enum. R9 values include `quota_exceeded`, `tusk_structural_gate`, `fallback_disabled_profile`, `fallback_disabled_global`.
- `original_error`: structured object with `type`, `message`, optional `status_code`, and optional `code`. It must be redacted before writing if raw provider text is included.
- `config_block_hash`: SHA-256 hex digest of canonical normalized `routing_policy` JSON: `json.dumps(policy, sort_keys=True, separators=(",", ":"))` encoded as UTF-8.

Write discipline:

- Synchronous append before fallback proceeds.
- Create parent directory on first write.
- Append-only; no truncation or clearing in R9.
- Use profile-safe paths via `get_hermes_home()`.
- Fail closed: if the audit row cannot be written, fallback must not proceed. For Tusk blocked events, audit failure must still not allow fallback; the terminal error should report the audit failure and QC blocked state.
- Use a process/thread lock and fsync where practical for RED-risk forensics.

### Typed QuotaExceeded exception class shape

Recommended Python shape:

```python
class QuotaExceeded(RuntimeError):
    provider: str
    requested_model: str
    status_code: int | None
    code: str | None
    original_error: Exception | None
```

Recommended placement: a small routing/error module importable by `hermes_cli/auth.py`, `agent/conversation_loop.py`, and tests, or a carefully located existing error module if Igris finds one. Preserve `AuthError` and `is_rate_limited_auth_error()` compatibility for existing auth UX.

## 6. Implementation contract

### WHERE in `hermes_cli/auth.py` the QuotaExceeded signal is raised

Current verified source already classifies Codex quota/rate-limit conditions:

- `hermes_cli/auth.py` lines 711-746: `CODEX_RATE_LIMITED_CODE`, `AuthError`, `is_rate_limited_auth_error()`.
- `hermes_cli/auth.py` lines 3601-3623: Codex refresh token HTTP 429 raises `AuthError(... code=CODEX_RATE_LIMITED_CODE, relogin_required=False)`.
- `hermes_cli/auth.py` lines 3843-3848: pool rate-limit state raises the same code.
- `hermes_cli/auth.py` lines 7323-7328 and 7430-7435: login/device/token exchange 429 throttling raises the same code.

Implementation must either:

1. Raise `QuotaExceeded` directly at the R9-relevant Codex runtime quota sites while preserving `AuthError` for interactive auth commands, or
2. Preferably, convert at the dispatcher boundary:

```python
try:
    response = interruptible_api_call(agent, api_kwargs)
except AuthError as exc:
    if is_rate_limited_auth_error(exc) and is_openai_codex_gpt55(agent):
        raise QuotaExceeded(
            provider="openai-codex",
            requested_model=current_requested_model(agent),
            status_code=429,
            code=CODEX_RATE_LIMITED_CODE,
            original_error=exc,
        ) from exc
    raise
```

The second shape is safer for existing `hermes auth` UX because it does not make every login/device-code throttle look like a dispatch-level fallback opportunity.

### HOW the dispatcher catches it

Existing dispatcher/error path verified:

- `agent/chat_completion_helpers.py::interruptible_api_call()` starts at line 154.
- `agent/conversation_loop.py` line 2407 calls `agent._recover_with_credential_pool(...)` before fallback.
- Eager fallback for rate-limit/billing/transport begins at `agent/conversation_loop.py` lines 2913-2931.
- Existing fallback activation call is `agent.conversation_loop.py` line 2952: `agent._try_activate_fallback(reason=classified.reason)`.

R9 wrapper ordering:

```python
try:
    response = interruptible_api_call(agent, api_kwargs)
except QuotaExceeded as exc:
    # Before generic AuthError handling or generic fallback status messages.
    # Before any provider/model mutation.
    decision = evaluate_r9_routing_policy(agent, exc)
    write_fallback_audit_row_or_raise(decision, exc)  # fail-closed
    maybe_notify_fallback_window_non_blocking(decision)
    if agent._try_activate_fallback(reason=FailoverReason.rate_limit):
        active_system_prompt = _sync_failover_system_message(...)
        retry_count = 0
        continue
    raise
except AuthError as exc:
    if is_rate_limited_auth_error(exc) and is_openai_codex_gpt55(agent):
        quota_exc = quota_from_auth_error(exc, agent)
        # Same path as QuotaExceeded above.
        ...
    # Existing AuthError behavior remains.
    raise
```

Ordering requirements:

- Catch `QuotaExceeded` and `AuthError + is_rate_limited_auth_error()` before generic auth-failure fallback and before generic rate-limit fallback status messaging.
- Do not classify `invalid_grant`, `invalid_token`, `invalid_request`, 401, 403, or `relogin_required=True` as quota.
- Do not swallow `TuskNoFallbackError`, `FallbackDisabledError`, or `FallbackAuditError`. These must terminate the fallback path explicitly.

### WHERE the structural Tusk gate lives

Insert the gate in `agent/chat_completion_helpers.py::try_activate_fallback()` immediately after the docstring and before current line 1126. This is before:

- Cooldown mutation at lines 1126-1134.
- Chain exhaustion checks at lines 1135-1151.
- First fallback target read/index advancement at lines 1152-1155.
- Provider/model/base_url/api_mode mutation at lines 1259-1262.

The gate belongs in `try_activate_fallback()` because `run_agent.py::_try_activate_fallback()` lines 4392-4395 forward here, and the conversation loop's existing fallback paths call that forwarder.

### Audit write location and fail-closed semantics

Recommended implementation unit: a small profile-safe audit helper, for example `agent/routing_policy_audit.py` or a similarly narrow module, called from the dispatcher immediately before fallback activation.

Contract:

```python
decision = evaluate_r9_routing_policy(agent, quota_exc)
append_fallback_audit_row(decision, quota_exc)  # raises FallbackAuditError on failure
agent._try_activate_fallback(reason=FailoverReason.rate_limit)
```

`append_fallback_audit_row()` must:

- Resolve `routing_policy.audit_log_path` under `get_hermes_home()`.
- Reject absolute paths, `..`, and non-`.jsonl` paths.
- Create `state/audit/` if missing.
- Append one JSON object plus newline.
- Redact raw error text before writing.
- Raise a typed `FallbackAuditError` on any write/serialization/fsync error.

Fail-closed means `FallbackAuditError` prevents fallback. Telegram ping failure does not prevent fallback.

### Kaisel hook signature

Kaisel owns the Telegram/tooling execution. R9 core should expose a narrow hook and call it fire-and-forget after audit succeeds:

```ts
export interface FallbackWindowNotifier {
  notifyFallbackWindow(
    count: number,
    recentProfiles: readonly string[],
    auditLogPath: string,
  ): Promise<void>;
}
```

Dispatch signature requested by the work: `notifyFallbackWindow(count, recentProfiles, auditLogPath) -> Promise<void>`.

TypeScript requirements:

- TypeScript strict.
- No `any`.
- `recentProfiles` must be `readonly string[]` or equivalent immutable array type.
- Notification timeout recommended: 2 seconds.
- Notification failures are logged but non-blocking.

## 7. Quota vs non-quota exception classification

Explicit allow-list: R9 quota exceptions

1. `QuotaExceeded` typed exception.
2. `AuthError` where `is_rate_limited_auth_error(exc)` returns true:
   - `provider == "openai-codex"`
   - `code == CODEX_RATE_LIMITED_CODE` / `codex_rate_limited`
   - `relogin_required is False`
3. HTTP 429 from `openai-codex` where the response body/message has quota, rate-limit, usage-limit, or limit-reached semantics and does not indicate invalid credentials.
4. OpenAI SDK `RateLimitError` / equivalent where:
   - provider is `openai-codex`,
   - status code is 429,
   - requested model is the R9 QC-grade model (`openai-codex/gpt-5.5`), and
   - message/body indicates usage quota or rate limiting.

Explicit deny-list: not quota for R9

1. Network/connectivity/timeouts: connection errors, DNS failures, TLS failures, `APIConnectionError`, `APITimeoutError`, `httpx.ConnectError`.
2. Auth failures: `invalid_grant`, `invalid_token`, `invalid_request`, 401, 403, `relogin_required=True`.
3. Model-not-found / unsupported model: 404, `model_not_found`, `unsupported_model`, bad model 400s.
4. Billing/subscription errors outside the explicit `openai-codex/gpt-5.5` quota contract. Existing generic fallback may classify billing, but R9 MiniMax fallback must not broaden to other providers without Belion/Tusk approval.
5. Safety, policy, moderation, or content-filter errors. R9 must not route around safety enforcement.
6. Non-Codex provider 429s. R9 is not a broad provider fallback feature.

## 8. Tusk structural gate

Current insertion point: `agent/chat_completion_helpers.py::try_activate_fallback()` line 1114 function start; insert immediately after the docstring, before current line 1126.

Required order of checks:

1. `profile == "tusk"` → `TuskNoFallbackError`.
2. `allow_minimax_fallback is not True` → `FallbackDisabledError`.
3. `non_qc_specialists_with_fallback is not True` → `FallbackDisabledError`.
4. Only after those checks may code inspect `fallback_target.default` or `agent._fallback_chain`.

Pseudocode:

```python
def try_activate_fallback(agent, reason=None):
    """Existing docstring..."""

    if is_r9_specialist_fallback_context(agent, reason):
        policy = load_routing_policy()
        profile = get_active_profile_name().strip().lower() or "default"
        profile_policy = load_profile_policy(profile)

        if profile == "tusk":
            # Write blocked_no_fallback audit row in caller before this point
            # when the caller has a QuotaExceeded object. If this chokepoint is
            # reached directly without caller context, still hard-stop.
            raise TuskNoFallbackError(
                "Tusk profile never falls back; QC blocked on requested model"
            )

        if profile_policy.allow_minimax_fallback is not True:
            raise FallbackDisabledError(
                f"MiniMax fallback disabled for profile {profile}"
            )

        if policy.non_qc_specialists_with_fallback is not True:
            raise FallbackDisabledError(
                "Global non-QC MiniMax fallback disabled"
            )

        # Only here may code inspect policy.fallback_target.default or
        # agent._fallback_chain.

    # existing cooldown, chain, provider resolution, and mutation logic follows
```

Exception semantics:

- `TuskNoFallbackError` and `FallbackDisabledError` must not be converted into `False` by `try_activate_fallback()` and must not be silently swallowed by callers.
- The dispatcher must surface a clear operator-facing message: `QC BLOCKED — wrong model / quota exhausted; Tusk fallback prohibited` for Tusk, or `MiniMax fallback disabled by routing policy` for opt-in failures.
- If audit context is available, blocked events should be written before raising. If audit write fails, raise `FallbackAuditError` chained from the policy exception and still do not fallback.

## 9. Defense-in-depth: existing `fallback_providers` path

Recommendation: Option A — make `try_activate_fallback()` the single chokepoint, with all callers going through it.

Rationale:

- `try_activate_fallback()` is already the central provider/model mutation function.
- `run_agent.py::_try_activate_fallback()` lines 4392-4395 forwards to it.
- `conversation_loop.py` uses `agent._try_activate_fallback(...)` for eager rate-limit fallback at line 2952 and auth fallback at line 2985.
- `agent_init.py` only initializes `_fallback_chain`; it does not mutate the active provider/model.
- Gating at initialization (Option B) is less precise because initialization may not know the triggering reason/error, and it would make safe non-R9 fallback chains harder to reason about.
- Adding hooks to every fallback path (Option C) invites drift and violates extend-don't-duplicate.

Required pseudocode:

```python
def try_activate_fallback(agent, reason=None):
    if is_r9_specialist_fallback_context(agent, reason):
        profile = active_profile_name()
        if profile == "tusk":
            raise TuskNoFallbackError(...)
        if profile_allow_minimax_fallback(profile) is not True:
            raise FallbackDisabledError(...)
        if routing_policy_non_qc_enabled() is not True:
            raise FallbackDisabledError(...)

    # Only after the R9 gate may generic fallback logic inspect or mutate:
    # fb = agent._fallback_chain[agent._fallback_index]
    # agent.model/provider/base_url/api_mode = ...
```

Defense-in-depth interpretation for Iron contradiction #5:

- Any MiniMax specialist fallback caused by `openai-codex/gpt-5.5` quota must pass through this gate, even if the MiniMax target came from pre-existing `fallback_providers` instead of the new `routing_policy.fallback_target.default`.
- Tusk hard-stops before any fallback chain inspection, so Tusk cannot fall through via an existing `fallback_providers` MiniMax entry.
- R9 should add tests proving an existing `fallback_providers` MiniMax entry still cannot move Tusk off GPT-5.5.

## 10. Provider name resolution

Recommendation: use spec string `minimax-oauth/MiniMax-M3`.

Rationale:

- The work card context says MiniMax is wired locally via `auth.json active_provider=minimax-oauth`.
- `hermes_cli/auth.py` lines 286-303 defines two distinct providers:
  - `minimax`: API-key provider using `MINIMAX_API_KEY`.
  - `minimax-oauth`: OAuth provider using MiniMax OAuth and `auth.json`.
- `hermes_cli/auth.py::_resolve_provider()` lines 1535-1581 aliases `minimax-portal`, `minimax-global`, and `minimax_oauth` to `minimax-oauth`, but it does not alias plain `minimax` to `minimax-oauth`.
- `agent/auxiliary_client.py::_normalize_aux_provider()` lines 184-235 also does not alias plain `minimax` to `minimax-oauth`.
- Therefore `minimax/MiniMax-M3` would select the API-key provider and could fail on Chris's local setup if only OAuth is configured.

Handling the three candidate strings:

1. `minimax/MiniMax-M3`
   - `hermes_cli/auth.py::_resolve_provider()` treats `minimax` as the API-key provider in `PROVIDER_REGISTRY`.
   - `agent/auxiliary_client.py::resolve_provider_client()` would reach the API-key provider branch at lines 4301-4402 and use `resolve_api_key_provider_credentials("minimax")`.
   - This requires `MINIMAX_API_KEY` or equivalent API-key config. It does not use the stated `minimax-oauth` auth.json credential unless Igris adds an alias, which would be surprising because `minimax` and `minimax-oauth` are separate auth modes.
   - Rejected for R9.

2. `minimax-oauth/MiniMax-M3`
   - Config uses the actual provider identity from auth state.
   - `hermes_cli/auth.py` already has provider registry entries for `minimax-oauth` lines 294-303 and credential-pool seeding for it elsewhere.
   - Current `agent/auxiliary_client.py::resolve_provider_client()` does not yet handle auth type `oauth_minimax` in the generic fallback resolver; implementation must add a narrow resolver branch for `minimax-oauth`, likely mirroring the main-agent Anthropic Messages / token-provider path in `agent/agent_init.py` lines 669-705.
   - Accepted for R9.

3. `MiniMax-M3` only
   - Provider inference from `auth.json active_provider` is implicit and fragile.
   - It would be harder to audit because `fallback_model` alone cannot prove which provider/auth mode was selected.
   - Rejected for RED-risk routing because audit rows need explicit provider/model identity.

Implementation contract for provider resolution:

- Add/extend a narrow `minimax-oauth` resolver in the existing provider router instead of aliasing plain `minimax` to OAuth.
- Do not silently fall back from `minimax-oauth` to `minimax` API key or vice versa.
- Audit `fallback_model` exactly as configured/resolved: `minimax-oauth/MiniMax-M3`.

## 11. Tusk 429 blocked-event audit row

Recommendation: use the same `state/audit/fallbacks.jsonl` file with an added `event_type` field.

Rationale:

- Tusk does not fallback, so writing a normal fallback row would be false evidence.
- Relying only on generic Hermes logs would make Tusk review harder and would not satisfy the work-card desire to audit Tusk 429 blocked behavior.
- A separate `tusk_blocks.jsonl` file would split one routing-control audit trail into two locations and make the Telegram window counter less direct.
- A single JSONL audit stream with `event_type` is easiest for Tusk to review and keeps the schema honest.

Schema expansion:

```json
{"event_type":"blocked_no_fallback","timestamp":"2026-07-03T00:00:00Z","profile":"tusk","requested_model":"openai-codex/gpt-5.5","fallback_model":null,"reason":"tusk_structural_gate","original_error":{"type":"QuotaExceeded","message":"Codex provider quota exhausted (429). Credentials are still valid; retry after the usage limit resets.","status_code":429,"code":"codex_rate_limited"},"config_block_hash":"<sha256-hex>"}
```

Rules:

- `fallback_model` must be `null` for blocked events.
- `event_type` must be required for all new R9 audit rows.
- Tusk blocked row write failure must not permit fallback.
- Telegram window counting may count both `fallback_activated` and `blocked_no_fallback`, but the ping text must label blocked events distinctly if count composition is exposed.

## 12. Rejected alternatives

1. R9 in Path B (user-side override layer)
   - Rejected because Chris's binding decision is Path A.
   - A user-side override could miss core fallback paths and would not reliably protect Tusk from existing `fallback_providers` behavior.
   - In-framework integration lets Tusk review the real routing chokepoint.

2. R9 with TRUE defaults (card spec)
   - Rejected because Chris approved Iron's safer defaults: both `non_qc_specialists_with_fallback` and `allow_minimax_fallback` default false.
   - TRUE defaults risk silent GPT-5.5 to MiniMax model swaps.
   - RED-risk model routing must require explicit operator opt-in.

3. R9 with new parallel fallback manager
   - Rejected by the AGENTS.md extend-don't-duplicate clause and by verified existing fallback infrastructure.
   - A parallel manager would create two model-switching paths and increase the chance that one path lacks the Tusk gate or audit discipline.
   - R9 must extend `fallback_providers`, `_fallback_chain`, and `try_activate_fallback()`.

4. R9 with broad provider fallback (any provider → any provider, not just openai-codex → MiniMax)
   - Rejected as scope creep.
   - R9 is specifically about `openai-codex/gpt-5.5` quota exhaustion for non-QC specialists.
   - Broad fallback would require a separate policy matrix, additional safety review, and new tests for every provider class.

5. R9 without Tusk structural gate (just config block)
   - Rejected because config alone is not defense-in-depth.
   - Existing `fallback_providers` could bypass a new policy block if the central fallback function does not enforce it.
   - Tusk requires code-level hard-stop semantics before any fallback target/model mutation.

## 13. Open questions routed to Belion/Chris

These require a human call before Tusk pre-flight approves implementation.

1. Audit log: include chat_id/session_id? (PII)
   - Iron's recommendation: avoid PII by default; do not include `chat_id` unless Chris explicitly approves. If traceability is required, prefer `session_id` over chat/user IDs and consider hashing.
   - Atlas disposition: leave out of R9 schema unless Belion/Chris approve; current ADR schema omits both.
   - Decision needed: include no identifier, include `session_id`, include hashed `chat_id`, or include both under a privacy gate?

2. Backoff: retry original model after N seconds? (backoff vs hard swap)
   - Iron's recommendation: hard swap for the current dispatch after quota classification; do not add automatic backoff/retry-to-original in R9.
   - Atlas disposition: keep R9 hard-swap only; use existing cooldown behavior where applicable. Backoff-to-original is a future R10 policy.
   - Decision needed: should R9 ever retry GPT-5.5 after N seconds within the same dispatch?

3. Triple-fallback: what if BOTH GPT-5.5 AND MiniMax quota-exhausted? (triple-fallback vs hard fail)
   - Iron's recommendation: hard fail after MiniMax quota exhaustion; do not add triple fallback in R9.
   - Atlas disposition: hard fail. Triple fallback would broaden provider policy beyond R9 and needs separate Tusk/Sentinel review.
   - Decision needed: confirm hard fail, or authorize a future R10 triple-fallback policy.

4. Telegram ping: link to Stronghold live dashboard?
   - Iron's recommendation: do not include dashboard links in R9 unless Stronghold feed URL and access controls are already stable.
   - Atlas disposition: omit dashboard link in R9 ping; include only count, recent profiles, requested/fallback model, and audit log path.
   - Decision needed: include no link, a local dashboard link, or a future placeholder once Stronghold is live?

5. auth.json quota signal: reused or fresh layer?
   - Iron's recommendation: reuse existing `CODEX_RATE_LIMITED_CODE` / auth classification and add only the minimal typed `QuotaExceeded` conversion needed at the dispatcher boundary.
   - Atlas disposition: reuse existing auth signal; do not create a fresh quota state layer in R9. Add a typed wrapper/converter only where dispatch needs policy evaluation.
   - Decision needed: confirm dispatcher-level conversion over a new auth.json quota state mechanism.

Additional scope question discovered by Atlas:

6. MiniMax OAuth fallback resolver support
   - Current `agent/auxiliary_client.py::resolve_provider_client()` does not handle `oauth_minimax` for `minimax-oauth`; see verified lines 4477-4492. R9 fallback through `try_activate_fallback()` uses this resolver.
   - Atlas recommendation: add a narrow `minimax-oauth` resolver branch as part of R9 implementation; keep config string `minimax-oauth/MiniMax-M3`.
   - Decision needed: approve this as in-scope implementation plumbing, or require API-key `minimax/MiniMax-M3` instead.

## 14. Definition of done

Architectural DoD items resolved by this ADR:

- Quota-detection layer returns/normalizes to `QuotaExceeded` on `openai-codex/gpt-5.5` 429/quota errors.
- Routing policy block shape is defined with false defaults matching Chris's binding decision.
- Per-profile `allow_minimax_fallback` shape is defined with false default.
- Tusk structural gate placement is defined in `try_activate_fallback()` before chain/model mutation.
- Audit log path, JSONL schema, blocked-event schema, and fail-closed write discipline are defined.
- Telegram ping threshold/window/cooldown and Kaisel hook signature are defined.
- Exception allow-list and deny-list are defined.
- Existing fallback-provider defense-in-depth strategy is selected: Option A, single chokepoint.
- Provider name resolution is selected: `minimax-oauth/MiniMax-M3`.
- Rejected alternatives are documented.
- Open questions are routed to Belion/Chris.

Implementation items owned by Igris after Tusk pre-flight:

- Cut branch `feat/r9-minimax-fallback` after approval.
- Add routing-policy config loading/validation with defaults false.
- Add profile policy loading for `allow_minimax_fallback` with default false.
- Add or wrap `QuotaExceeded` classification at the dispatcher boundary.
- Add `minimax-oauth` fallback resolver support if Belion/Chris approve the scope question.
- Insert the structural gate in `try_activate_fallback()`.
- Add audit append helper with fail-closed semantics.
- Add Kaisel notifier hook integration without blocking fallback.
- Add tests for non-QC opt-in fallback, Tusk blocked no fallback, network passthrough, audit write success/failure, existing `fallback_providers` bypass prevention, and provider resolution.
- Run test suite per `AGENTS.md` expectations.

Items not owned by this ADR:

- Code implementation.
- Branch creation.
- Config/profile file mutation.
- Commit/merge.
- Tusk final QC signoff.

## 15. Tusk pre-flight request

Tusk pre-flight review is requested before Igris implementation begins.

Tusk reviews:

- The opt-in defaults: `routing_policy.non_qc_specialists_with_fallback: false` and per-profile `allow_minimax_fallback: false`.
- The Tusk structural gate placement in `agent/chat_completion_helpers.py::try_activate_fallback()` and exception semantics.
- The audit log fail-closed discipline.
- The AGENTS.md rubric compliance verdict.
- The defense-in-depth approach for existing `fallback_providers`.
- The provider-name resolution recommendation: `minimax-oauth/MiniMax-M3`.
- The Tusk blocked-event audit schema recommendation: same `fallbacks.jsonl` with `event_type: blocked_no_fallback`.
- The rejected alternatives.

Tusk must return one of:

- APPROVED
- APPROVED WITH NITS
- VETOED

VETO stops the dispatch. Igris must not cut `feat/r9-minimax-fallback` for implementation until Tusk pre-flight returns APPROVED or APPROVED WITH NITS.

## 16. Decisions recorded by Belion (Chris-approved)

These resolve the §13 open questions. They are BINDING for Tusk pre-flight review and for Igris implementation. Recorded 2026-07-03 by Belion on Chris's explicit approval ("go with your recommendation").

1. **Audit log identifiers**: omit both `chat_id` and `session_id` for R9. PII-safe default. If future traceability is required, raise a separate ADR.
2. **Backoff behavior**: hard-swap only in R9. No automatic retry-to-original within the same dispatch. Existing cooldown behavior remains. Future backoff-to-original is a separate card.
3. **Triple-fallback policy**: hard fail after MiniMax quota exhaustion. No triple fallback in R9. If needed in the future, raise a separate ADR with Sentinel review.
4. **Telegram ping dashboard link**: omit Stronghold dashboard link in R9 ping. Include only count, recent profiles, requested/fallback model, and audit log path.
5. **auth.json quota signal**: reuse existing `CODEX_RATE_LIMITED_CODE` / `is_rate_limited_auth_error()` classification. Add only a narrow dispatcher-level `QuotaExceeded` typed wrapper. Do not create a fresh auth.json quota state layer.
6. **MiniMax OAuth fallback resolver scope** (Atlas-discovered): approved as in-scope R9 plumbing. Implementation must add a narrow `oauth_minimax` resolver branch in `agent/auxiliary_client.py::resolve_provider_client()` (referenced lines 4477-4492) so the recommended config string `minimax-oauth/MiniMax-M3` actually resolves. Mirror the main-agent Anthropic Messages / token-provider pattern in `agent/agent_init.py` lines 669-705.

Additionally, audit log path is `state/audit/fallbacks.jsonl` (plural, as Atlas recommended and the work card specified). Single JSONL file with required `event_type` field.

These decisions are durable. Igris treats them as binding context.
