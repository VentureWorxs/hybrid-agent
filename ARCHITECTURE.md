# Architecture: Claude Code + Ollama Hybrid Agent

**Status:** Accepted  
**Authors:** sam@nicheworxs.com  
**Platforms:** macOS (Apple M3) · Windows 11 Pro · Cloudflare D1 (replica)

---

## Context

Claude Code requires cloud API calls for all model inference. Certain workloads are:

- **Cost-sensitive** — bulk summarization, repetitive inference across many files
- **Privacy-sensitive** — internal code, unreleased IP, PII-adjacent data that should not leave the machine
- **HIPAA-regulated** — Propel tenant requires documented evidence that PHI never crossed a network boundary

A local Ollama instance running **Qwen3-235B-A22B** (a 235B MoE model with 22B active parameters per forward pass) is available on both development machines. This model is competitive on coding and reasoning tasks at lower complexity levels.

Three gaps existed before this architecture:

1. **No persistent routing memory** — every Claude Code session starts cold; prior decisions, trust scores, and approvals are lost
2. **No audit trail** — decisions, agent invocations, and boundary enforcement events were not recorded; HIPAA evidence production was impossible
3. **No measurement** — token savings from Ollama routing were invisible; there was no way to prove the hybrid was working better than baseline

---

## Decision

Expose Ollama as a set of MCP tools, then layer orchestration, decision caching, a dual-backend audit log, operating modes, and a KPI scorecard on top. Claude Code remains the orchestrator; Qwen3 is a delegated worker.

### What Claude handles (cloud)
- High-stakes reasoning and planning
- Cross-file architectural decisions
- Tool orchestration and sequencing
- Final output synthesis

### What Qwen3/Ollama handles (local)
- Bulk text/code summarization
- Sensitivity-flagged code that must not leave the machine
- High-volume cheap inference (linting explanations, doc generation)
- Speculative drafts Claude then refines

### What was rejected

| Option | Rejected Because |
|--------|-----------------|
| Replace Claude with Qwen3 entirely | Loses Claude Code's orchestration, tool use, and reasoning quality |
| Use LangChain as top-level orchestrator | Adds complexity; Claude Code already provides the agentic loop |
| Call Ollama directly from Claude Code hooks | Hooks are fire-and-forget; can't return structured results to Claude |
| OpenAI-compatible proxy (LiteLLM) | Adds a network hop and a process; MCP is simpler and already supported |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          Developer Machine                                │
│                                                                          │
│  ┌─────────────────────┐    stdio    ┌─────────────────────────────┐    │
│  │    Claude Code CLI  │◄──────────►│  MCP Server (Python)        │    │
│  │  (orchestrator AI)  │            │  - ollama_summarize         │    │
│  │                     │            │  - ollama_analyze_code      │    │
│  │  Uses SKILL.md for  │            │  - ollama_infer             │    │
│  │  routing guidance   │            │  - ollama_health            │    │
│  │                     │            │  - audit_log_event          │    │
│  └────────┬────────────┘            │  - get_decision             │    │
│           │                          │  - cache_decision           │    │
│           │                          │  - verify_audit_chain       │    │
│           │                          │  - get_scorecard            │    │
│           │                          └───────┬─────────────────────┘    │
│           │                                  │                          │
│           ▼                                  ▼                          │
│  ┌────────────────┐              ┌──────────────────────────┐          │
│  │ Local FS       │              │  Storage Abstraction     │          │
│  │ Git / Bash     │              │  (SQLiteAuditStorage)    │          │
│  │ Other MCPs     │              └───────┬──────────────────┘          │
│  └────────────────┘                      │                              │
│                                          ▼                              │
│                              ┌───────────────────────┐                  │
│                              │ Local SQLite Database │                  │
│                              │ ~/.hybrid-agent/      │                  │
│                              │   audit.db            │                  │
│                              │ - audit_events        │                  │
│                              │ - decision_cache      │                  │
│                              └───────────┬───────────┘                  │
│                                          │                              │
│                              ┌───────────▼────────────┐                 │
│                              │ Sync Worker (5-min)    │                 │
│                              │ - Read unsynced rows   │                 │
│                              │ - Run sanitization     │                 │
│                              │ - POST to CF Worker    │                 │
│                              │ - Mark synced on 200   │                 │
│                              └───────────┬────────────┘                 │
│                                          │                              │
│  ┌──────────────┐              ┌─────────▼─────────┐                    │
│  │ Ollama REST  │              │  Ollama (local)   │                    │
│  │ localhost    │◄─────────────│  Qwen3-235B-A22B  │                    │
│  │ :11434       │              └───────────────────┘                    │
│  └──────────────┘                                                       │
└──────────────────────────────┼───────────────────────────────────────────┘
                               │
                               │ HTTPS (Cloudflare Access auth)
                               ▼
          ┌────────────────────────────────────────────────┐
          │              Cloudflare                          │
          │                                                  │
          │  ┌──────────────────────┐   ┌──────────────┐    │
          │  │ Audit Sync Worker    │──►│ Cloudflare   │    │
          │  │ (TypeScript)         │   │ D1 Database  │    │
          │  │ - Auth via CF Access │   │ (replica)    │    │
          │  │ - Receive batches    │   │ - audit      │    │
          │  │ - INSERT OR IGNORE   │   │ - analytics  │    │
          │  └──────────────────────┘   └──────┬───────┘    │
          │                                    │             │
          │                            ┌───────▼─────────┐  │
          │                            │ Future Dashboard│  │
          │                            │ venworxs.com    │  │
          │                            └─────────────────┘  │
          └────────────────────────────────────────────────┘

     HTTPS (Claude inference, unchanged)
               │
               ▼
      api.anthropic.com
```

**Data flow for a delegated task:**

1. User prompt → Claude Code
2. Claude classifies task complexity + sensitivity
3. Claude calls `get_decision` → checks cache for prior routing decision
4. Claude routes: Ollama (local) or Claude API (cloud)
5. Claude calls `audit_log_event` → event appended to local SQLite with hash chain
6. Claude calls `cache_decision` (if new decision) → cache materialized view updated
7. Sync worker (background, every 5 min) reads unsynced events
8. Sanitization pipeline scrubs PHI/PII based on `sensitivity_level`
9. Sanitized batch POSTed to Cloudflare Worker (auth via Cloudflare Access)
10. Worker writes to D1; sync worker marks events synced

---

## Consequences

### Positive
- Sensitive code never leaves the machine for the Ollama leg
- Ollama calls are free after hardware cost; reduces API spend on bulk tasks
- Claude retains full orchestration authority — reasoning quality doesn't degrade
- Every decision, agent invocation, and boundary enforcement is immutably logged
- HIPAA proof: audit trail demonstrates PHI never left the local boundary
- Tamper evidence: hash-chain integrity check detects any modification to historical events
- Derived state (decision cache, analytics) is fully rebuildable from the audit log
- Scorecard makes token savings provable, not just asserted

### Negative / Risks
- Qwen3 output quality is lower than Claude on complex reasoning — Claude must validate critical outputs
- Ollama must be running before Claude Code sessions start (no auto-launch)
- M3 MacBook Air RAM (16–24 GB) limits Qwen3-235B throughput; expect ~3–8 tok/s
- Shadow mode runs every task twice — ~2x Claude API cost during shadow campaigns
- Write amplification: ~1–3 audit events per agent invocation (~10 KB each in SQLite)
- Hash-chain rigidity: fixing a buggy event requires emitting a correction event

---

## Routing Logic

The `Router` combines two axes to select a route for each task:

**Complexity** (0–10, heuristic keyword match in `task_classifier.py`):

| Score | Task types |
|-------|-----------|
| 1–2 | status_check, data_extraction, template_fill, summarize |
| 3 | classification, doc_generation |
| 5 | pattern_analysis, comparison |
| 6–10 | code_review, multi_step_reasoning, strategic_recommendation, novel_problem, architectural_decision |

`OLLAMA_COMPLEXITY_THRESHOLD = 3` — tasks scoring ≤ 3 are proposed to `ollama-local`; higher scores propose `claude-api`.

**Compliance boundary** (`compliance_boundary.py`) always overrides complexity:

| Sensitivity level | Allowed routes |
|-------------------|---------------|
| `public`, `internal` | `ollama-local` or `claude-api` |
| `confidential`, `sensitive_phi` | `ollama-local` only |

PHI detection uses regex patterns for SSN, DOB, patient/medical record keywords, and HIPAA terminology. PII detection covers email and phone number patterns. The `propel` tenant defaults to `confidential` unless content is explicitly public.

Routing decisions are cached in `decision_cache` with a 24-hour TTL and reused across sessions.

---

## Schema

### Core Event Log

`audit_events` is the single source of truth. All other state (decision cache, analytics) is derived from it.

Key columns:

| Column | Purpose |
|--------|---------|
| `event_id` | ULID (sortable) primary key |
| `sequence_number` | Monotonic per `machine_id` |
| `previous_hash` | SHA-256 of prior event's `event_hash` |
| `event_hash` | SHA-256 of this event's canonical form |
| `tenant_id` | `sam-personal` \| `nicheworxs` \| `propel` |
| `machine_id` | UUID per physical machine (persists in `~/.hybrid-agent/machine_id`) |
| `session_id` | UUID per Claude Code session |
| `sensitivity_level` | `public` \| `internal` \| `confidential` \| `sensitive_phi` |
| `agent_routed_to` | `ollama-local` \| `claude-api` |
| `boundary_enforced` | 1 if compliance boundary overrode routing |
| `details` | JSON blob (queryable via `json_extract()`) |
| `sync_disabled` | 1 if written while `audit_sync_enabled = false` |
| `synced_to_d1` | 1 after successful push to Cloudflare D1 |

**Event type enum:**

```
task_started            task_completed          task_failed
subtask_started         subtask_completed       subtask_failed
classification_made     routing_decision        agent_invoked
agent_responded         decision_made           decision_reused
scope_escalated         approval_requested      approval_granted
approval_denied         boundary_enforced       cost_tracker
config_changed          system_error            sync_attempted
```

### Decision Cache

`decision_cache` is a materialized view of cacheable decisions. It is keyed on `(tenant_id, context_hash, decision_type)` where `context_hash` is SHA-256 of the serialized routing context. Rebuilt by replaying `decision_made` and `decision_reused` events.

### Analytics Tables

Pre-aggregated physical tables (refreshed by sync worker after each batch):
- `analytics_daily_cost` — tokens + cost per tenant, date, and route
- `analytics_ollama_savings` — Ollama vs Claude task counts and estimated savings
- `analytics_compliance` — PHI confinement counts and boundary violations
- `analytics_task_frequency` — top task patterns by week

### Migration Strategy

Forward-only numbered SQL files in `schema/migrations/`. Each migration runs once per database, tracked in `schema_version`. Applied by `python -m audit.migrate`. D1 uses `wrangler d1 migrations apply` with the same SQL files (with minor compatibility notes: no FTS5 on D1, no WAL pragma).

---

## Storage Abstraction

`AuditStorage` (in `audit/storage_abstraction.py`) is an abstract base class implemented by:
- `SQLiteAuditStorage` — source of truth, always available, full-fidelity, WAL mode
- `D1AuditStorage` — cloud replica, queried via Cloudflare HTTP API, used by dashboard

The local agent writes to SQLite only. The sync worker handles replication to D1. Application code is backend-agnostic.

**Hash chain:** `compute_event_hash()` builds a SHA-256 over a canonical JSON serialization of all non-sync-state fields. Fields are sorted; `previous_hash` is the prior event's `event_hash`. Tampering with any historical event invalidates all subsequent hashes.

---

## Sanitization Pipeline

Before any event leaves the machine for D1:

| Sensitivity | Action |
|-------------|--------|
| `public` | Sync as-is |
| `internal` | Redact PII fields (email, phone) from `details` |
| `confidential` | Drop raw content; keep metadata (type, timestamp, cost, route) |
| `sensitive_phi` | Drop event entirely; emit a **shadow event** — same `event_id`, `event_hash`, and aggregate metrics, but with `subject_type`, `subject_id`, and `details` replaced with a HIPAA confinement statement |

The shadow event pattern proves *an event happened* (HIPAA needs that) without revealing *what it contained* (HIPAA requires that). It is excluded from all primary KPI calculations by the `is_shadow` filter.

---

## Operating Modes

**Mode resolution**: Session > Tenant > Global (most-specific wins). Same hierarchy for `audit_sync_enabled`.

### `baseline`
All inference routes to Claude API. Ollama is never invoked. Used to establish pre-hybrid cost/performance baselines. The router still emits `routing_decision` events so the epoch's pattern is visible in the audit log.

### `hybrid`
Normal routing: Ollama for tasks with complexity ≤ 3 or `confidential`/`sensitive_phi` sensitivity; Claude for higher complexity. The default operating mode.

### `shadow`
Each task runs on both routes in parallel. Primary result returned to the user; secondary stored with `is_shadow: true` and a `shadow_pair_id`. Used for rigorous A/B quality validation. Should be run in bounded campaigns (recommended: 7 days per quarter), not continuously — it roughly doubles Claude API cost.

### `audit_sync_enabled = false`
Events still write to local SQLite but with `sync_disabled = 1`. The sync worker's query skips them. Re-enabling is non-destructive; `sync_disabled` events stay local unless explicitly backfilled with `python cli.py audit backfill` (which excludes `sensitive_phi` events regardless).

**Every toggle change emits a `config_changed` audit event.** This is what defines epoch boundaries.

---

## KPI Catalog

All KPIs derive from `audit_events` in local SQLite. Shadow events are excluded by default (`WHERE NOT (json_extract(details, '$.is_shadow') = 1)`).

### A — Tokens Used (Cost / Efficiency)

Source: `agent_invoked` events.

Actual Claude tokens vs. a synthetic all-Claude baseline. The synthetic baseline stores `estimated_claude_tokens` and `estimated_claude_cost_usd` in the event's `details` at write time for every Ollama invocation. Estimation uses a configurable `char_to_token_ratio` (default 4.0) and Claude pricing from `config.toml`. Estimation is a heuristic — shadow mode provides exact measured comparison.

### B — Throughput (Performance)

Source: `task_completed` events.

Tasks per hour over the reporting period. Auxiliary stats: latency median, p95, and per-route breakdown (`ollama-local` vs `claude-api`).

### C — Approval Rate (Quality / Effectiveness)

Source: `approval_granted` and `approval_denied` events.

Percentage of human-approval requests that were granted. A proxy for orchestrator correctness — low rate suggests over-escalation or proposals the user doesn't want. Expect small sample sizes (approvals are infrequent by design). Rate suppressed if n < 5.

### D — System Error Rate (Operational)

Source: `system_error` and `task_failed` (numerator), `task_started` (denominator).

Errors per 1,000 tasks. Excludes user-cancelled tasks (`details.cause = 'user_cancelled'`). Sensitive to Ollama service unavailability by design.

### E — Boundary Enforcement (Compliance)

Source: `boundary_enforced` events.

Count of compliance boundary interventions, broken down by sensitivity level. Also queries for **suspected violations** — `agent_invoked` events with `sensitivity_level = 'sensitive_phi'` and `agent_routed_to != 'ollama-local'`. Any suspected violation is a serious incident.

---

## Epochs & Comparison

An **epoch** is a period during which all configuration settings are constant. It begins with a `config_changed` event (or the genesis of the audit log) and ends at the next `config_changed` event.

Epoch selectors in CLI and MCP: `CURRENT`, `PREV`, `GENESIS`, or a numeric sequence number.

The scorecard can compare any two epochs side-by-side. Comparability warnings are emitted when: tenants differ, sample sizes differ by more than 10x, or one epoch was in shadow mode (which skews cost dramatically).

**Synthetic baseline enables cost comparison without a baseline epoch.** A measured comparison requires running in `baseline` mode for 7–14 days, then switching to `hybrid` and using `--compare CURRENT,PREV`.

---

## Compliance (HIPAA / Propel)

The `propel` tenant has `phi_allowed: true` in its `tenants.metadata`. Special handling:

| Sensitivity | Allowed routes |
|-------------|---------------|
| `public` | Ollama, Claude, any agent |
| `internal` | Ollama, Claude (with PII redaction at sync time) |
| `confidential` | Ollama only |
| `sensitive_phi` | **Ollama only — Claude API is explicitly blocked** |

`ComplianceBoundary.enforce()` raises `BoundaryViolationError` if PHI data is proposed for a non-local agent. On enforcement: the subtask is aborted, a `boundary_enforced` event is logged, and the user is notified.

**HIPAA evidence trail** for third-party audits:
- Audit log export for any date range
- Hash-chain verification proving log integrity
- PHI confinement report showing 100% of `sensitive_phi` events routed to `ollama-local`
- Machine identity records showing which physical devices handled PHI
- 7-year retention for `propel` (`retention_days: 2555` in tenant metadata)

D1 stores sanitized-only data for Propel. Cloudflare's BAA does not need to cover D1 usage (no raw PHI in D1). Local SQLite should reside on encrypted disk (FileVault / BitLocker).

---

## Future Work

Deferred to future design documents:

- **Statistical significance** — bootstrap confidence intervals or Welch's t-test for epoch comparisons
- **Quality scoring via shadow mode** — pair-wise semantic comparison of Ollama vs Claude outputs for the same input
- **Audit dashboard** — scorecard JSON consumed by venworxs.com or Propel dashboard; read-only Cloudflare Worker → D1; multi-tenant routing via CF Access JWT claims
- **Long-term retention** — Propel events archived to compressed Parquet after 90 days in SQLite
- **Tokenizer-true estimation** — periodic recalibration using actual tokenizer calls or shadow-mode measurements
- **Auto-tuning** — adjust complexity threshold and routing rules based on observed KPI trends
- **Real-time alerts** — push notification when error rate exceeds threshold or boundary violation detected
