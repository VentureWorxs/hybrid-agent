"""
MCP server exposing Ollama/Qwen3 tools + audit/orchestration tools to Claude Code.
Transport: stdio (Claude Code spawns this process directly).
Platform: macOS / Windows 11 (no platform-specific code required).
"""
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

OLLAMA_BASE = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:235b-a22b"
DEFAULT_CONTEXT = 8192

DB_PATH = Path(os.environ.get("HYBRID_AGENT_DB_PATH", Path.home() / ".hybrid-agent" / "audit.db"))
AGENT_VERSION = os.environ.get("AGENT_VERSION", "1.1.0")
TENANT_ID = os.environ.get("HYBRID_AGENT_TENANT", "sam-personal")
MACHINE_ID_FILE = Path.home() / ".hybrid-agent" / "machine_id"
SESSION_ID = str(uuid.uuid4())

app = Server("ollama-bridge")

# Lazy-initialised globals (set up after first use to avoid import failures if DB not yet present)
_storage = None
_audit = None


def _get_machine_id() -> str:
    if MACHINE_ID_FILE.exists():
        return MACHINE_ID_FILE.read_text().strip()
    mid = str(uuid.uuid4())
    MACHINE_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    MACHINE_ID_FILE.write_text(mid)
    return mid


def _init_audit():
    global _storage, _audit
    if _audit is not None:
        return

    try:
        from audit.migrate import apply_migrations
        from audit.sqlite_storage import SQLiteAuditStorage
        from audit.audit_logger import AuditLogger
        from modes.controller import ModeController

        apply_migrations(DB_PATH)
        _storage = SQLiteAuditStorage(DB_PATH)
        machine_id = _get_machine_id()
        _audit = AuditLogger(
            storage=_storage,
            tenant_id=TENANT_ID,
            machine_id=machine_id,
            session_id=SESSION_ID,
            agent_version=AGENT_VERSION,
        )
    except Exception as e:
        # Non-fatal: MCP server can run without audit in standalone mode
        print(f"[warn] Audit init failed: {e}", file=sys.stderr)


# ─── Ollama helpers ──────────────────────────────────────────────────────────

def _chat(system: str, user: str, model: str = DEFAULT_MODEL, num_ctx: int = DEFAULT_CONTEXT) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"num_ctx": num_ctx},
    }
    with httpx.Client(timeout=300) as client:
        resp = client.post(f"{OLLAMA_BASE}/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()["message"]["content"]


# ─── Tool definitions ─────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="ollama_summarize",
            description=(
                "Summarize a large block of text or code using the local Qwen3 model. "
                "Use this for bulk summarization tasks where content is too long for efficient "
                "cloud processing, or when the content is sensitive and must not leave the machine."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The text or code to summarize."},
                    "instructions": {
                        "type": "string",
                        "description": "Specific summarization instructions.",
                        "default": "Provide a concise, accurate summary.",
                    },
                    "max_words": {"type": "integer", "default": 200},
                },
                "required": ["content"],
            },
        ),
        Tool(
            name="ollama_analyze_code",
            description=(
                "Analyze source code locally using Qwen3. Suitable for sensitive or proprietary "
                "code that should not be sent to external APIs."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "language": {"type": "string"},
                    "focus": {
                        "type": "string",
                        "enum": ["bugs", "security", "performance", "style", "all"],
                        "default": "all",
                    },
                },
                "required": ["code", "language"],
            },
        ),
        Tool(
            name="ollama_infer",
            description=(
                "Run a general-purpose prompt against the local Qwen3 model. "
                "Use for high-volume, cost-sensitive, or privacy-sensitive inference."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "system": {"type": "string", "default": "You are a helpful, precise assistant."},
                    "num_ctx": {"type": "integer", "default": 8192},
                },
                "required": ["prompt"],
            },
        ),
        Tool(
            name="ollama_health",
            description="Check whether the local Ollama server is reachable and Qwen3 is loaded.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        # ─── Audit tools ─────────────────────────────────────────────────────
        Tool(
            name="audit_log_event",
            description=(
                "Append an event to the local audit log. Records decisions, agent invocations, "
                "scope changes, or other significant actions. Events are hash-chained and synced "
                "to Cloudflare D1 every 5 minutes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "event_type": {"type": "string"},
                    "actor": {"type": "string"},
                    "action": {"type": "string"},
                    "sensitivity_level": {
                        "type": "string",
                        "enum": ["public", "internal", "confidential", "sensitive_phi"],
                        "default": "public",
                    },
                    "scope_level": {"type": "integer", "default": 1},
                    "agent_routed_to": {"type": "string"},
                    "tokens_used": {"type": "integer", "default": 0},
                    "cost_usd": {"type": "number", "default": 0.0},
                    "details": {"type": "object"},
                },
                "required": ["event_type", "actor", "action"],
            },
        ),
        Tool(
            name="get_decision",
            description=(
                "Look up a cached routing or permission decision for the given context. "
                "Returns null if no cached decision exists or it has expired."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tenant_id": {"type": "string"},
                    "context": {"type": "object"},
                    "decision_type": {"type": "string", "enum": ["routing", "permission", "scope_level"]},
                },
                "required": ["tenant_id", "context", "decision_type"],
            },
        ),
        Tool(
            name="cache_decision",
            description="Cache a decision for reuse across sessions. Logs a decision_made event.",
            inputSchema={
                "type": "object",
                "properties": {
                    "tenant_id": {"type": "string"},
                    "context": {"type": "object"},
                    "decision_type": {"type": "string"},
                    "decision_value": {"type": "object"},
                    "scope_level": {"type": "integer"},
                    "ttl_hours": {"type": "integer", "default": 24},
                },
                "required": ["tenant_id", "context", "decision_type", "decision_value", "scope_level"],
            },
        ),
        Tool(
            name="verify_audit_chain",
            description="Verify hash-chain integrity of the local audit log. Returns valid/invalid + error.",
            inputSchema={
                "type": "object",
                "properties": {
                    "machine_id": {"type": "string"},
                },
                "required": ["machine_id"],
            },
        ),
        Tool(
            name="get_scorecard",
            description=(
                "Retrieve a KPI scorecard for the hybrid agent. "
                "Returns metrics for the specified tenant and epoch/period."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tenant_id": {"type": "string"},
                    "epoch": {"type": "string", "default": "CURRENT"},
                    "period": {"type": "string", "description": "24h, 7d, 30d, or all"},
                    "format": {"type": "string", "enum": ["summary", "full", "json"], "default": "summary"},
                    "compare_to": {"type": "string"},
                },
                "required": ["tenant_id"],
            },
        ),
    ]


# ─── Tool handlers ────────────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        # ── Ollama tools ──────────────────────────────────────────────────────
        if name == "ollama_health":
            with httpx.Client(timeout=10) as client:
                resp = client.get(f"{OLLAMA_BASE}/api/tags")
                models = [m["name"] for m in resp.json().get("models", [])]
            available = any(DEFAULT_MODEL in m for m in models)
            status = "healthy" if available else "Ollama running but Qwen3 not found"
            return [TextContent(type="text", text=json.dumps({"status": status, "models": models}))]

        if name == "ollama_summarize":
            instructions = arguments.get("instructions", "Provide a concise, accurate summary.")
            max_words = arguments.get("max_words", 200)
            system = (
                f"You are a precise summarizer. {instructions} "
                f"Target length: approximately {max_words} words. "
                "Return only the summary — no preamble, no meta-commentary."
            )
            result = _chat(system, arguments["content"])
            return [TextContent(type="text", text=result)]

        if name == "ollama_analyze_code":
            focus_map = {
                "bugs": "Identify logic errors, off-by-one errors, null/undefined risks, and incorrect assumptions.",
                "security": "Identify injection risks, hardcoded secrets, insecure defaults, and authentication flaws.",
                "performance": "Identify algorithmic inefficiencies, redundant operations, and memory issues.",
                "style": "Identify naming inconsistencies, dead code, and readability issues.",
                "all": "Provide a comprehensive analysis covering bugs, security, performance, and style.",
            }
            code = arguments["code"]
            language = arguments["language"]
            focus = arguments.get("focus", "all")
            system = (
                f"You are an expert {language} code reviewer. {focus_map.get(focus, focus_map['all'])} "
                "Format: ## Summary / ## Findings (numbered, CRITICAL/HIGH/MEDIUM/LOW) / ## Recommendations"
            )
            result = _chat(system, f"```{language}\n{code}\n```")
            return [TextContent(type="text", text=result)]

        if name == "ollama_infer":
            system = arguments.get("system", "You are a helpful, precise assistant.")
            num_ctx = arguments.get("num_ctx", DEFAULT_CONTEXT)
            result = _chat(system, arguments["prompt"], num_ctx=num_ctx)
            return [TextContent(type="text", text=result)]

        # ── Audit tools ───────────────────────────────────────────────────────
        if name == "audit_log_event":
            _init_audit()
            if not _audit:
                return [TextContent(type="text", text=json.dumps({"error": "Audit not available"}))]
            event_id = _audit.log(
                event_type=arguments["event_type"],
                actor=arguments["actor"],
                action=arguments["action"],
                sensitivity_level=arguments.get("sensitivity_level", "public"),
                scope_level=arguments.get("scope_level", 1),
                agent_routed_to=arguments.get("agent_routed_to"),
                tokens_used=arguments.get("tokens_used", 0),
                cost_usd=arguments.get("cost_usd", 0.0),
                details=arguments.get("details"),
            )
            return [TextContent(type="text", text=json.dumps({"event_id": event_id, "status": "logged"}))]

        if name == "get_decision":
            _init_audit()
            if not _storage:
                return [TextContent(type="text", text="null")]
            from orchestrator.decision_cache import DecisionCache
            cache = DecisionCache(_storage, _audit)
            result = cache.lookup(arguments["tenant_id"], arguments["context"], arguments["decision_type"])
            return [TextContent(type="text", text=json.dumps(result))]

        if name == "cache_decision":
            _init_audit()
            if not _storage:
                return [TextContent(type="text", text=json.dumps({"error": "Storage not available"}))]
            from orchestrator.decision_cache import DecisionCache
            cache = DecisionCache(_storage, _audit)
            decision_id = cache.store(
                tenant_id=arguments["tenant_id"],
                context=arguments["context"],
                decision_type=arguments["decision_type"],
                decision_value=arguments["decision_value"],
                scope_level=arguments["scope_level"],
                ttl_hours=arguments.get("ttl_hours", 24),
            )
            return [TextContent(type="text", text=json.dumps({"decision_id": decision_id}))]

        if name == "verify_audit_chain":
            _init_audit()
            if not _storage:
                return [TextContent(type="text", text=json.dumps({"error": "Storage not available"}))]
            valid, error = _storage.verify_chain(arguments["machine_id"])
            return [TextContent(type="text", text=json.dumps({"valid": valid, "error": error}))]

        if name == "get_scorecard":
            _init_audit()
            if not _storage:
                return [TextContent(type="text", text=json.dumps({"error": "Storage not available"}))]
            from scorecard.generator import generate_scorecard
            from scorecard.formatters.cli import render_cli
            from scorecard.formatters.json import render_json

            data = generate_scorecard(
                storage=_storage,
                tenant_id=arguments["tenant_id"],
                epoch_selector=arguments.get("epoch", "CURRENT"),
                period=arguments.get("period"),
                compare_to=arguments.get("compare_to"),
            )
            fmt = arguments.get("format", "summary")
            if fmt == "json":
                text = render_json(data)
            elif fmt == "summary":
                text = render_cli(data, verbose=False)
            else:
                text = render_cli(data, verbose=True)
            return [TextContent(type="text", text=text)]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except httpx.ConnectError:
        return [TextContent(type="text", text="ERROR: Cannot connect to Ollama at localhost:11434. Is Ollama running?")]
    except Exception as e:
        return [TextContent(type="text", text=f"ERROR: {type(e).__name__}: {e}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
