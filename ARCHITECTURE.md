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

A local Ollama instance running **Qwen3** is available on both development machines. The specific model variant is chosen per machine based on available RAM (see README Pre-Flight).

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
│  │ localhost    │◄─────────────│  Qwen3 (local)    │                    │
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
- Model choice is RAM-constrained on Mac (16 GB → `qwen3:8b`; 24 GB → `qwen3:30b-a3b`); Windows with discrete GPU can run larger models
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

## Permission Capture via Claude Code Hooks

**Added:** 2026-05-12  
**File:** `hooks/audit_tool_use.py`

### Problem

The `approval_requested` / `approval_granted` / `approval_denied` event types existed in the schema and KPI catalog (KPI C — Approval Rate) but were never populated. Claude Code's native permission prompt system operates outside the MCP server, so the `audit_log_event` tool had no way to observe these decisions.

### Solution

A `PreToolUse` hook shim registered in `~/.claude/settings.json`. Claude Code fires `PreToolUse` before every tool call; the shim decides whether to log based on allowlist state.

**Hook payload (from Claude Code, via stdin):**
```json
{
  "hook_event_name": "PreToolUse",
  "tool_name": "Bash",
  "tool_input": { "command": "..." },
  "session_id": "<uuid>"
}
```

**Logic:**
```
PreToolUse fires
  ├── tool starts with "mcp__ollama-bridge__"  → skip (already logged by audit_log_event)
  ├── tool matches allowlist rule               → skip (auto-approved, no prompt shown)
  └── tool NOT in allowlist                    → user was prompted
        ├── log  approval_requested  (actor=claude-code, approval_status=pending)
        └── log  approval_granted    (actor=user, approval_status=granted)
            ↑ hook firing proves the user said yes
```

**Why denied prompts are not captured:** If the user denies a permission prompt, Claude Code cancels the tool call before `PreToolUse` fires. There is no hook event for denial. As a result, `approval_rate_pct` in the dashboard represents "granted / (granted + 0)" — it will read 100% until a denial mechanism is added. The count of `approval_requested` events is still useful as an absolute measure of prompt frequency.

**Fast path:** Tools in the allowlist exit before importing any Python modules (`sys.exit(0)` after reading `settings.json`). Overhead on auto-approved calls is ~5 ms (JSON parse + allowlist scan). On prompted calls the SQLite write adds ~20–30 ms, which is unnoticeable relative to human approval time.

**Session continuity:** The shim uses Claude Code's `session_id` from the hook payload, so permission events group with `agent_invoked`, `task_started`, and `task_completed` events from the same session.

**MCP tools skipped by fast path:** `mcp__ollama-bridge__*` tools are skipped explicitly because `audit_log_event` already records those invocations with richer metadata (tokens, cost, routing). Logging them in the hook shim too would double-count.

### Configuration

Registered globally in `~/.claude/settings.json`:
```json
{
  "hooks": {
    "PreToolUse": [{
      "hooks": [{
        "type": "command",
        "command": "/path/to/hybrid-agent/.venv/bin/python /path/to/hybrid-agent/hooks/audit_tool_use.py"
      }]
    }]
  }
}
```

The shim always exits `0` — audit failures are printed to stderr but never block tool execution.

### Effect on KPI C (Approval Rate)

The Permission Prompts panel on the venworxs dashboard now shows:
- **Total prompts** — count of `approval_requested` events in the period
- **Approval rate** — always 100% until denial capture is possible
- **Trend** — the real signal: prompt count should decrease over time as the allowlist grows

A decreasing prompt count across epochs proves the hybrid-agent is reducing friction, which is one of the three original goals (no persistent routing memory, no audit trail, no measurement).

---

## Permission Optimization Loop

**Added:** 2026-05-12  
**Files:** `audit/permission_advisor.py`, `audit/sqlite_storage.py` (`execute_fetchall`)  
**MCP tools:** `check_approval_history`, `suggest_allowlist`

Capturing permission events (above) is necessary but not sufficient — without a feedback loop, Claude has no way to consult that history before acting. Two MCP tools close the loop.

### `check_approval_history`

Called **proactively by Claude** before invoking a tool it suspects may need a prompt.

```
Input:  tool_name="Bash", pattern="wrangler d1", lookback_days=30
Output: {
  approved_count: 6,
  last_seen: "2026-05-11T...",
  recommendation: "add_to_allowlist",   // ≥5 approvals
  suggested_rule: "Bash(wrangler d1:*)"
}
```

**Recommendation thresholds:**

| `approved_count` | `recommendation`     | Meaning                                      |
|-----------------|----------------------|----------------------------------------------|
| 0               | `expect_prompt`      | No history — user will be asked cold         |
| 1–4             | `proceed`            | Historically approved; expect a prompt       |
| ≥ 5             | `add_to_allowlist`   | Consistent approval — ready to automate      |

**Usage pattern for Claude:**
```
# Before: wrangler d1 execute hybrid-agent-audit --remote ...
check_approval_history(tool_name="Bash", pattern="wrangler d1")
→ recommendation=add_to_allowlist
→ Claude informs user: "This command has been approved 6 times.
   Consider adding 'Bash(wrangler d1:*)' to your allowlist."
```

### `suggest_allowlist`

Called **at session start or when prompts feel repetitive**. Analyses the full approval history, normalises raw action strings into minimal glob patterns, excludes anything already covered by the allowlist, and returns a ranked list.

```
Input:  min_approvals=3, lookback_days=90
Output: {
  suggestions: [
    { rule: "Bash(wrangler d1:*)", approvals: 8, confidence: "high" },
    { rule: "Bash(git commit:*)",  approvals: 5, confidence: "high" },
    { rule: "Edit(/Users/samc/Projects/GitHub/**)", approvals: 3, confidence: "medium" },
  ],
  total_found: 3,
  skipped_covered: 12,
  note: "Add high-confidence rules to ~/.claude/settings.json ..."
}
```

Pattern normalisation rules:
- `Bash` commands → two-word prefix glob (`wrangler d1:*`, `git commit:*`, `npm run:*`)
- `Read`/`Write`/`Edit` paths → parent directory glob (`/Users/samc/Projects/GitHub/hybrid-agent/**`)
- `WebFetch` URLs → origin-level glob (`https://api.cloudflare.com/*`)
- `mcp__*` tools → exact tool name (MCP tools are already fully specified)

Already-covered patterns (matched against existing `permissions.allow` rules including wildcard expansion) are excluded from suggestions and counted in `skipped_covered`.

### The full optimisation loop

```
1. Session starts
   → call suggest_allowlist
   → review high-confidence suggestions
   → add approved rules to settings.json → fewer prompts next session

2. During session, before a potentially gated action
   → call check_approval_history(tool, pattern)
   → if recommend=add_to_allowlist: inform user proactively
   → if recommend=expect_prompt:    proceed, user will confirm
   → if recommend=expect_prompt (count=0): warn user before the cold prompt

3. Permission prompt fires (tool not in allowlist)
   → hook shim writes approval_requested + approval_granted to SQLite
   → sync_now or 5-min background sync pushes to D1
   → dashboard Permission Prompts panel updates

4. Over weeks/epochs
   → prompt count trends down (visible in dashboard)
   → allowlist grows from suggestions, not reactive approvals
   → KPI C approval rate and volume become meaningful baselines
```

### What this does NOT do (yet)

- **Auto-add to allowlist** — suggestions are advisory; a human or a future `apply_allowlist_suggestions` tool must write to `settings.json`
- **Capture denials** — hook never fires on denial; rate stays 100% until a denial-detection mechanism exists
- **Cross-machine sync** — allowlist lives in `~/.claude/settings.json` per machine; suggestions are local

---

## Future Work

Deferred to future design documents:

- **Statistical significance** — bootstrap confidence intervals or Welch's t-test for epoch comparisons
- **Quality scoring via shadow mode** — pair-wise semantic comparison of Ollama vs Claude outputs for the same input
- ~~**Audit dashboard**~~ — **shipped** at `venworxs.com/portal/hybrid-agent` (2026-05-12); D1 binding on Cloudflare Pages; Scorecard, Permission Prompts, Routing Effectiveness, Boundary & Compliance, and Audit Log panels; period toggle (24h/7d/30d); dynamic tenant selector
- **Long-term retention** — Propel events archived to compressed Parquet after 90 days in SQLite
- **Tokenizer-true estimation** — periodic recalibration using actual tokenizer calls or shadow-mode measurements
- **Auto-tuning** — adjust complexity threshold and routing rules based on observed KPI trends
- **Real-time alerts** — push notification when error rate exceeds threshold or boundary violation detected
