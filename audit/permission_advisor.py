"""
Permission advisor — queries approval history to reduce future prompts.

Two public functions:
  check_approval_history  — how many times has a specific action been approved?
  suggest_allowlist       — which approved patterns are ready to promote to allowlist?
"""
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from .sqlite_storage import SQLiteAuditStorage


# ── Thresholds ────────────────────────────────────────────────────────────────

SUGGEST_THRESHOLD   = 3   # approvals needed before suggesting allowlist addition
CONFIDENT_THRESHOLD = 5   # approvals that warrant "add_to_allowlist" recommendation


# ── Pattern helpers ───────────────────────────────────────────────────────────

def _normalize_bash_pattern(cmd: str) -> str:
    """
    Collapse a Bash command into a minimal allowlist-ready glob pattern.

    Examples:
      "wrangler d1 execute hybrid-agent-audit --remote" → "wrangler d1:*"
      "git commit -m 'feat: ...'"                       → "git commit:*"
      "npm run deploy"                                   → "npm run:*"  (already covered by npm run:*)
      "ls -la"                                           → "ls:*"
    """
    words = cmd.strip().split()
    if not words:
        return cmd
    # Two-word prefix for well-known multi-word CLIs
    two_word_prefixes = {
        "npm run", "npm install", "npx tsc", "npx next", "pulumi up",
        "pulumi preview", "pulumi config", "wrangler d1", "wrangler pages",
        "wrangler deploy", "git commit", "git push", "git pull", "git log",
        "git diff", "git status", "python3 -m", "uv run", "uv sync",
    }
    if len(words) >= 2:
        two = f"{words[0]} {words[1]}"
        if two in two_word_prefixes:
            return f"{two}:*"
    return f"{words[0]}:*"


def _action_to_allowlist_entry(action: str) -> Optional[tuple[str, str]]:
    """
    Parse an action string from audit_events into (tool_name, allowlist_pattern).
    Returns None if no clean pattern can be derived.

    Action format from the hook shim:
      "Bash: <command>"
      "Read: <path>"
      "Write: <path>"
      "Edit: <path>"
      "WebFetch: <url>"
      "WebSearch: <query>"
      "MCP <server>: <op>"
    """
    if action.startswith("Bash: "):
        cmd = action[6:].strip()
        if not cmd:
            return None
        return ("Bash", _normalize_bash_pattern(cmd))

    for tool in ("Read", "Write", "Edit"):
        if action.startswith(f"{tool}: "):
            path = action[len(tool) + 2:].strip()
            if not path:
                return None
            p = Path(path)
            # Suggest directory glob rather than exact file
            return (tool, f"{p.parent}/**")

    if action.startswith("WebFetch: "):
        url = action[10:].strip()
        # Suggest origin-level pattern
        m = re.match(r"(https?://[^/]+)", url)
        return ("WebFetch", f"{m.group(1)}/*") if m else None

    if action.startswith("WebSearch: "):
        return None  # searches are too variable to pattern-match

    if action.startswith("MCP "):
        # "MCP ollama-bridge: sync_now" → tool_name is mcp__ollama-bridge__sync_now
        m = re.match(r"MCP ([^:]+): (.+)", action)
        if m:
            server, op = m.group(1).strip(), m.group(2).strip()
            return (f"mcp__{server}__{op}", None)

    return None


def _is_covered(tool: str, pattern: Optional[str], allowlist: list[str]) -> bool:
    """Check whether an (tool, pattern) pair is already in the allowlist."""
    for rule in allowlist:
        if pattern is None:
            if rule == tool:
                return True
        else:
            candidate = f"{tool}({pattern})" if pattern else tool
            if rule == candidate:
                return True
            # Check if existing wildcard rule covers this
            if rule.startswith(f"{tool}(") and rule.endswith(":*)"):
                existing_prefix = rule[len(tool) + 1 : -3]  # strip "Tool(" and ":*)"
                if pattern.startswith(existing_prefix):
                    return True
    return False


def _since_ts(lookback_days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()


# ── Public API ────────────────────────────────────────────────────────────────

def check_approval_history(
    storage: SQLiteAuditStorage,
    tenant_id: str,
    tool_name: str,
    pattern: str,
    lookback_days: int = 30,
) -> dict:
    """
    Return approval history for a specific tool + pattern substring.

    Args:
        tool_name: e.g. "Bash", "Read", "mcp__Neon__run_sql"
        pattern:   substring to search within the action field,
                   e.g. "wrangler d1", "git commit", "/Users/samc/Projects"
    """
    since = _since_ts(lookback_days)
    search = f"%{pattern}%"

    row = storage.execute_fetchone(
        """
        SELECT
            COUNT(*)        AS approved_count,
            MAX(timestamp)  AS last_seen,
            MIN(timestamp)  AS first_seen
        FROM audit_events
        WHERE tenant_id              = ?
          AND event_type             = 'approval_granted'
          AND action                 LIKE ?
          AND timestamp              >= ?
          AND sensitivity_level      != 'sensitive_phi'
        """,
        (tenant_id, search, since),
    )

    count     = row["approved_count"] if row else 0
    last_seen = row["last_seen"]       if row else None
    first_seen= row["first_seen"]      if row else None

    if count >= CONFIDENT_THRESHOLD:
        recommendation = "add_to_allowlist"
    elif count >= 1:
        recommendation = "proceed"        # expect a prompt but historically approved
    else:
        recommendation = "expect_prompt"  # no history — user will be asked cold

    # Derive suggested allowlist pattern
    sample_action = f"{tool_name}: {pattern}"
    parsed = _action_to_allowlist_entry(sample_action)
    suggested_rule = f"{parsed[0]}({parsed[1]})" if parsed and parsed[1] else (parsed[0] if parsed else None)

    return {
        "tool_name":        tool_name,
        "pattern":          pattern,
        "approved_count":   count,
        "last_seen":        last_seen,
        "first_seen":       first_seen,
        "lookback_days":    lookback_days,
        "recommendation":   recommendation,
        "suggested_rule":   suggested_rule,
        "threshold_to_suggest": SUGGEST_THRESHOLD,
        "threshold_confident":  CONFIDENT_THRESHOLD,
    }


def suggest_allowlist(
    storage: SQLiteAuditStorage,
    tenant_id: str,
    min_approvals: int = SUGGEST_THRESHOLD,
    lookback_days: int = 90,
    current_allowlist: Optional[list[str]] = None,
) -> dict:
    """
    Analyse approval history and return patterns ready to promote to the allowlist.

    Groups approval_granted events by normalised action pattern, filters out
    patterns already covered by the allowlist, and ranks by approval count.
    """
    since = _since_ts(lookback_days)
    allowlist = current_allowlist or []

    rows = storage.execute_fetchall(
        """
        SELECT
            action,
            COUNT(*)       AS approvals,
            MAX(timestamp) AS last_seen
        FROM audit_events
        WHERE tenant_id         = ?
          AND event_type        = 'approval_granted'
          AND timestamp         >= ?
          AND sensitivity_level != 'sensitive_phi'
        GROUP BY action
        HAVING COUNT(*) >= ?
        ORDER BY approvals DESC
        """,
        (tenant_id, since, min_approvals),
    )

    suggestions, skipped_covered = [], 0

    for r in rows:
        parsed = _action_to_allowlist_entry(r["action"])
        if parsed is None:
            continue

        tool_name, pattern = parsed
        rule = f"{tool_name}({pattern})" if pattern else tool_name
        already_covered = _is_covered(tool_name, pattern, allowlist)

        if already_covered:
            skipped_covered += 1
            continue

        suggestions.append({
            "rule":            rule,
            "tool_name":       tool_name,
            "pattern":         pattern,
            "approvals":       r["approvals"],
            "last_seen":       r["last_seen"],
            "already_covered": False,
            "confidence":      "high" if r["approvals"] >= CONFIDENT_THRESHOLD else "medium",
        })

    # Deduplicate by rule (multiple raw actions can map to the same pattern)
    seen, deduped = set(), []
    for s in suggestions:
        if s["rule"] not in seen:
            seen.add(s["rule"])
            deduped.append(s)

    return {
        "suggestions":       deduped,
        "total_found":       len(deduped),
        "skipped_covered":   skipped_covered,
        "min_approvals":     min_approvals,
        "lookback_days":     lookback_days,
        "note": (
            "Add high-confidence rules to ~/.claude/settings.json "
            "permissions.allow to eliminate future prompts."
        ),
    }
