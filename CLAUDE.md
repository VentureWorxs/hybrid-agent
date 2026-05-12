# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

A hybrid inference routing system for Claude Code that routes tasks between Claude API (complex work) and a local Ollama/Qwen3 instance (bulk/sensitive tasks). Built in three ADR layers:

- **ADR-001** — MCP bridge: exposes Ollama as Claude Code tools via stdio MCP server
- **ADR-001.1** — Orchestration, decision cache, and dual-backend audit log (local SQLite + Cloudflare D1)
- **ADR-002.0** — Operating modes (baseline/hybrid/shadow), KPI scorecard

## Setup

```bash
# macOS
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

```powershell
# Windows
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```bash
# Bootstrap DB and machine identity (run once per machine)
python -m audit.bootstrap --tenant sam-personal

# Start MCP server (Claude Code does this automatically via .claude/settings.json)
python mcp_ollama_server.py
```

### Environment Variables

Copy `.env.example` to `.env` and fill in values before running the sync worker:

| Variable | Purpose |
|----------|---------|
| `SYNC_ENDPOINT_URL` | Cloudflare Worker URL (from `wrangler deploy` output) |
| `CF_ACCESS_CLIENT_ID` | CF Zero Trust service token client ID |
| `CF_ACCESS_CLIENT_SECRET` | CF Zero Trust service token secret |
| `HYBRID_AGENT_DB_PATH` | Override default `~/.hybrid-agent/audit.db` |
| `HYBRID_AGENT_TENANT` | Override default tenant (`sam-personal`) |
| `AGENT_VERSION` | Bumped on each release (default: `1.1.0`) |

## Common Commands

```bash
# Apply DB migrations
python -m audit.migrate

# Generate test events for a fresh DB
python -m audit.test_fixtures --tenant sam-personal --count 50

# Verify sanitization pipeline
python -m audit.test_sanitization

# Scorecard
python cli.py scorecard --tenant sam-personal
python cli.py scorecard --tenant propel --compare CURRENT,PREV --output md
python cli.py scorecard --tenant nicheworxs --period 30d --output json

# Config
python cli.py config show --tenant sam-personal
python cli.py config set --scope global --field operating_mode --value baseline
python cli.py config set --scope tenant --tenant propel --field audit_sync_enabled --value false

# Audit
python cli.py audit verify --machine-id <uuid-from-~/.hybrid-agent/machine_id>
python cli.py audit backfill --since 2026-01-01T00:00:00Z --dry-run

# Sync worker (runs continuously every 5 minutes)
python -m audit.sync_worker --tenant sam-personal

# Cloudflare Worker (deploy once)
cd worker && npm install && wrangler deploy
```

## Architecture Layers

```
mcp_ollama_server.py          ← Claude Code entry point (stdio MCP)
    ↓
modes/controller.py           ← Resolves operating_mode (global/tenant/session)
    ↓
orchestrator/routing_rules.py ← Routes task to ollama-local or claude-api
orchestrator/compliance_boundary.py  ← Enforces HIPAA: PHI → ollama-local only
orchestrator/decision_cache.py       ← Caches routing decisions across sessions
    ↓
audit/audit_logger.py         ← Appends hash-chained events to SQLite
audit/sync_worker.py          ← Pushes sanitized events to Cloudflare D1 (every 5 min)
    ↓
scorecard/generator.py        ← Computes 5 KPIs from audit_events
scorecard/cli.py              ← CLI output (table/markdown/JSON)
```

### Module Map

| Directory | Purpose |
|-----------|---------|
| `audit/` | Append-only event log, hash chain, SQLite/D1 storage, sanitization, sync |
| `orchestrator/` | Task classification, routing rules, compliance boundary, decision cache, async DAG executor |
| `modes/` | TOML config loader, mode controller (baseline/hybrid/shadow), shadow runner |
| `scorecard/` | Epoch detection, KPI calculators (A–E), scorecard generator, CLI/Markdown/JSON formatters |
| `schema/migrations/` | Forward-only SQL migrations (001–005); applied by `audit.migrate` |
| `worker/` | TypeScript Cloudflare Worker receiving sync batches from the local agent |
| `skills/` | Claude Code SKILL.md for routing guidance |
| `prompts/` | Reusable prompt templates for Ollama delegation |

## Routing Logic

Tasks are classified by `TaskClassifier` on two axes before hitting the `ComplianceBoundary`:

**Complexity** (0–10, heuristic keyword match against the action string):

| Score | Task types |
|-------|-----------|
| 1–2 | status_check, data_extraction, template_fill, summarize |
| 3 | classification, doc_generation |
| 5 | pattern_analysis, comparison |
| 6–10 | code_review, multi_step_reasoning, strategic_recommendation, novel_problem, architectural_decision |

`OLLAMA_COMPLEXITY_THRESHOLD = 3` — tasks scoring ≤ 3 are proposed to `ollama-local`; higher scores propose `claude-api`. The compliance boundary then overrides as needed.

**Sensitivity routing overrides** (always wins over complexity):

| Sensitivity | Allowed routes |
|-------------|---------------|
| `public`, `internal` | `ollama-local` or `claude-api` |
| `confidential`, `sensitive_phi` | `ollama-local` only |

## Configuration Hierarchy

Mode resolution: **Session > Tenant > Global** (most-specific wins)

Global config: `~/.hybrid-agent/config.toml`  
Tenant overrides: `tenants.metadata` JSON column in SQLite  
Session overrides: in-memory, set via `ModeController.set_mode(scope='session')`

Three operating modes: `baseline` (all → Claude), `hybrid` (smart routing), `shadow` (parallel A/B)

## Key Design Rules

- **Hash chain integrity**: every audit event references the SHA-256 of the prior event. Run `audit verify` after any unexpected DB restart.
- **PHI confinement**: `sensitivity_level = 'sensitive_phi'` is always routed to `ollama-local` and blocked from D1 sync. Sanitization emits a shadow event instead.
- **Derived state is rebuildable**: `decision_cache` and all `analytics_*` tables can be deleted and rebuilt from `audit_events` via `audit.event_sourcing.rebuild_all_derived_state()`.
- **`sync_disabled = 1`**: events written when `audit_sync_enabled = false`. Never leave the machine unless explicitly backfilled with `python cli.py audit backfill`.
- **Shadow events excluded from KPIs by default**: filter `WHERE NOT (json_extract(details, '$.is_shadow') = 1)`.

## Storage

- Local SQLite: `~/.hybrid-agent/audit.db` (source of truth, hash-chain verified)
- Cloud replica: Cloudflare D1 `hybrid-agent-audit` (sanitized, dashboard-queryable)
- Machine identity: `~/.hybrid-agent/machine_id` (UUID, persists across reboots)
- Global config: `~/.hybrid-agent/config.toml`

## Cloudflare Worker

Sync endpoint: `POST /sync` — receives sanitized event batches from `audit.sync_worker`.  
Auth: Cloudflare Access (JWT assertion header, or service token `CF-Access-Client-Id/Secret`).

First-time deploy:
```bash
wrangler d1 create hybrid-agent-audit   # copy database_id into worker/wrangler.toml
# Fill in CF_ACCESS_AUD in worker/wrangler.toml, then:
cd worker && npm install && wrangler deploy
```

## Tenants

| tenant_id | Display | PHI allowed |
|-----------|---------|-------------|
| `sam-personal` | Sam (Personal) | No |
| `nicheworxs` | NicheWorxs | No |
| `propel` | Propel (HIPAA) | Yes — PHI confined locally, 7-year retention |

## MCP Tools (available to Claude Code)

| Tool | Purpose |
|------|---------|
| `ollama_summarize` | Local bulk summarization |
| `ollama_analyze_code` | Local code review |
| `ollama_infer` | General local inference |
| `ollama_health` | Check Ollama status |
| `audit_log_event` | Append event to audit log |
| `get_decision` | Look up cached routing decision |
| `cache_decision` | Store new routing decision |
| `verify_audit_chain` | Check hash-chain integrity |
| `get_scorecard` | Retrieve KPI scorecard mid-session |

## KPI Reference (Scorecard)

| ID | Name | Measures |
|----|------|---------|
| A | `tokens_used` | Actual vs. estimated Claude tokens; cost savings % |
| B | `throughput` | Tasks/hour, median/p95 latency by route |
| C | `approval_rate` | % of approval requests granted vs. denied |
| D | `system_error_rate` | System errors per 1,000 tasks started |
| E | `boundary_enforcement` | Compliance boundary enforcement count; PHI violations |

## Design Document

[ARCHITECTURE.md](ARCHITECTURE.md) is the canonical source of design decisions: context, rationale, rejected alternatives, schema reference, KPI catalog, operating modes, compliance rules, and future work.

## Platform Notes

- Python 3.11+ required (uses stdlib `tomllib`)
- Windows: use `.venv\Scripts\Activate.ps1`; Ollama runs as a Windows service
- macOS: `brew install ollama`; use `python3`/`.venv/bin/activate`
- The `python` command in `.claude/settings.json` must resolve to the venv Python
