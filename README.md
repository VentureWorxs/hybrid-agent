# hybrid-agent

A hybrid inference routing system for Claude Code that routes tasks between Claude API (complex work) and a local Ollama/Qwen3 instance (bulk/sensitive tasks). See [ARCHITECTURE.md](ARCHITECTURE.md) for full design rationale.

---

## What was built

**Foundation**
- `requirements.txt`, `.env.example`, `.claude/settings.json`, `prompts/`

**Schema** — `schema/migrations/001_initial.sql` through `005_add_sync_disabled.sql`

**Audit layer** (`audit/`) — append-only event log with SHA-256 hash chain, SQLite storage, D1 HTTP client, sanitization pipeline (public/internal/confidential/PHI shadow), sync worker, migration runner, bootstrap, and test fixtures

**Orchestrator** (`orchestrator/`) — task classifier (complexity 0–10 heuristics), compliance boundary enforcement (PHI → ollama-local always), decision cache (cross-session persistence with TTL), router, async DAG executor

**Modes** (`modes/`) — TOML config loader, mode controller (baseline/hybrid/shadow, global/tenant/session resolution), shadow runner (parallel asyncio execution)

**Scorecard** (`scorecard/`) — epoch detection from `config_changed` events, all 5 KPI calculators with the exact SQL from the ADR, scorecard generator, CLI/Markdown/JSON formatters

**MCP server** (`mcp_ollama_server.py`) — 4 original Ollama tools + 5 new tools: `audit_log_event`, `get_decision`, `cache_decision`, `verify_audit_chain`, `get_scorecard`

**Cloudflare Worker** (`worker/`) — TypeScript, Cloudflare Access JWT validation, batch D1 writer

**Entry points** — `cli.py` root dispatcher, `skills/hybrid-orchestrator/SKILL.md`

---

## Pre-Flight

Check these before running setup:

| Requirement | Min version | Check |
|-------------|-------------|-------|
| Python | 3.11+ | `python3.11 --version` |
| Ollama | 0.3+ | `ollama --version` |
| Qwen3 model pulled | — | `ollama list` |
| Claude Code CLI | latest | `claude --version` |

**macOS install (if missing):**

```bash
brew install python@3.11
brew install ollama
npm install -g @anthropic-ai/claude-code
```

**Pull the model (~5 GB):**

```bash
ollama pull qwen3:8b
```

> **macOS note:** Use `python3.11` explicitly — the system `python3` may resolve to an older version.

---

## Setup

```powershell
# Windows
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Bootstrap DB and machine identity (run once per machine)
python -m audit.bootstrap --tenant sam-personal
```

```bash
# macOS
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m audit.bootstrap --tenant sam-personal
```

---

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
python cli.py audit verify --machine-id $(cat ~/.hybrid-agent/machine_id)
python cli.py audit backfill --since 2026-01-01T00:00:00Z --dry-run

# Sync worker (runs continuously every 5 minutes)
python -m audit.sync_worker --tenant sam-personal

# Cloudflare Worker (deploy once)
cd worker && npm install && wrangler deploy
```

---

## MCP Setup

The MCP server is registered per-client. Each client reads its own config file at launch — restart the app after editing.

### Claude Code

Already configured via `.claude/settings.json` in this repo (project-scoped, picked up automatically).

### Claude Desktop / Cowork

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ollama-bridge": {
      "command": "/Users/samc/Projects/GitHub/hybrid-agent/.venv/bin/python",
      "args": [
        "/Users/samc/Projects/GitHub/hybrid-agent/mcp_ollama_server.py"
      ]
    }
  }
}
```

> Update the paths if the repo is cloned to a different location. The venv must exist (`pip install -r requirements.txt`) before Desktop will be able to spawn the server.

---

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

---

## Next Steps

1. Run `python -m audit.bootstrap --tenant sam-personal` to initialize the local DB
2. Run `python mcp_ollama_server.py` to verify the MCP server starts cleanly
3. Configure Cloudflare D1 and deploy the Worker (see `worker/wrangler.toml`)
4. Set `SYNC_ENDPOINT_URL` and Cloudflare Access credentials in `.env` (copy from `.env.example`)
5. Start the sync worker: `python -m audit.sync_worker --tenant sam-personal`

See [CLAUDE.md](CLAUDE.md) for commands and [ARCHITECTURE.md](ARCHITECTURE.md) for design decisions.
