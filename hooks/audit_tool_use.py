#!/usr/bin/env python3
"""
Claude Code PreToolUse hook — hybrid-agent permission capture shim.

Fires before every Claude Code tool call. Logs permission prompt events to
local SQLite so they sync to D1 and appear in the Permission Prompts panel.

Logic:
  - Tool IS in allowlist  → auto-approved, exit immediately (zero overhead)
  - Tool NOT in allowlist → user was prompted; hook firing proves approval;
                            log approval_requested + approval_granted

Denied permissions are NOT capturable via hooks — Claude Code cancels the
call before PreToolUse fires.

Usage in ~/.claude/settings.json:
  {
    "hooks": {
      "PreToolUse": [{
        "hooks": [{"type": "command",
                   "command": "/Users/samc/Projects/GitHub/hybrid-agent/.venv/bin/python /Users/samc/Projects/GitHub/hybrid-agent/hooks/audit_tool_use.py"}]
      }]
    }
  }

Exit codes:
  0  — always (never block tool execution on audit failure)
"""
import json
import os
import sys
import uuid
from pathlib import Path

HYBRID_AGENT_DIR = Path(__file__).resolve().parent.parent
DB_PATH          = Path(os.environ.get("HYBRID_AGENT_DB_PATH",
                         Path.home() / ".hybrid-agent" / "audit.db"))
TENANT_ID        = os.environ.get("HYBRID_AGENT_TENANT", "sam-personal")
AGENT_VERSION    = os.environ.get("AGENT_VERSION", "1.1.0")
MACHINE_ID_FILE  = Path.home() / ".hybrid-agent" / "machine_id"
SETTINGS_PATH    = Path.home() / ".claude" / "settings.json"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_machine_id() -> str:
    if MACHINE_ID_FILE.exists():
        return MACHINE_ID_FILE.read_text().strip()
    mid = str(uuid.uuid4())
    MACHINE_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    MACHINE_ID_FILE.write_text(mid)
    return mid


def _load_allowlist() -> list[str]:
    try:
        data = json.loads(SETTINGS_PATH.read_text())
        return data.get("permissions", {}).get("allow", [])
    except Exception:
        return []


def _is_auto_approved(tool_name: str, tool_input: dict, allowlist: list[str]) -> bool:
    """Return True if this tool call matches any allowlist rule."""
    for rule in allowlist:
        # Exact tool name match (e.g. "Read")
        if rule == tool_name:
            return True
        # Prefixed rule match (e.g. "Bash(npm run:*)" or "mcp__Neon__run_sql")
        if rule.startswith(f"{tool_name}("):
            pattern = rule[len(tool_name) + 1 : -1]  # strip "ToolName(" and ")"
            if _matches_pattern(pattern, tool_input, tool_name):
                return True
        # MCP tool exact match
        if rule == tool_name:
            return True
    return False


def _matches_pattern(pattern: str, tool_input: dict, tool_name: str) -> bool:
    """Simple glob-style pattern match against the primary tool input value."""
    if pattern.endswith(":*"):
        # e.g. "npm run:*" — check if Bash command starts with prefix
        prefix = pattern[:-2]
        cmd = tool_input.get("command", "")
        return cmd.startswith(prefix)
    # Exact match
    cmd = tool_input.get("command", "")
    return cmd == pattern


def _format_action(tool_name: str, tool_input: dict) -> str:
    """Human-readable action string for the audit log."""
    if tool_name == "Bash":
        cmd = (tool_input.get("command") or "").strip()
        return f"Bash: {cmd[:120]}"
    if tool_name in ("Read", "Write", "Edit", "NotebookEdit"):
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        return f"{tool_name}: {path}"
    if tool_name in ("WebFetch", "WebSearch"):
        target = tool_input.get("url") or tool_input.get("query") or ""
        return f"{tool_name}: {target[:100]}"
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__", 2)
        server = parts[1] if len(parts) > 1 else tool_name
        op     = parts[2] if len(parts) > 2 else ""
        return f"MCP {server}: {op}"
    return f"{tool_name} invoked"


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    # Read hook payload from stdin
    try:
        payload    = json.loads(sys.stdin.read())
        tool_name  = payload.get("tool_name", "unknown")
        tool_input = payload.get("tool_input") or {}
        session_id = payload.get("session_id") or str(uuid.uuid4())
    except Exception:
        sys.exit(0)

    # Fast path — skip MCP tools that already log via audit_log_event
    if tool_name.startswith("mcp__ollama-bridge__"):
        sys.exit(0)

    # Fast path — check allowlist before importing heavy modules
    allowlist    = _load_allowlist()
    auto_approved = _is_auto_approved(tool_name, tool_input, allowlist)

    if auto_approved:
        sys.exit(0)  # No prompt was shown — nothing to record

    # ── User was prompted and approved (hook firing proves this) ──
    try:
        sys.path.insert(0, str(HYBRID_AGENT_DIR))
        from audit.migrate import apply_migrations
        from audit.sqlite_storage import SQLiteAuditStorage
        from audit.audit_logger import AuditLogger

        apply_migrations(DB_PATH)
        storage    = SQLiteAuditStorage(DB_PATH)
        machine_id = _get_machine_id()
        audit      = AuditLogger(
            storage=storage,
            tenant_id=TENANT_ID,
            machine_id=machine_id,
            session_id=session_id,
            agent_version=AGENT_VERSION,
        )

        action = _format_action(tool_name, tool_input)

        # 1. Record that a prompt was shown
        audit.log(
            event_type="approval_requested",
            actor="claude-code",
            action=action,
            approval_status="pending",
            scope_level=1,
            details={"tool_name": tool_name, "hook": "PreToolUse"},
        )

        # 2. Record that the user approved (same hook firing = approval)
        audit.log(
            event_type="approval_granted",
            actor="user",
            action=action,
            approval_status="granted",
            scope_level=1,
            details={"tool_name": tool_name, "hook": "PreToolUse"},
        )

    except Exception as e:
        # Never block tool execution on audit failure
        print(f"[audit-hook] warning: {e}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
