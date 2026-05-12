"""
One function per KPI. Each takes (storage, tenant_id, start, end) and returns a dict
matching the JSON scorecard schema defined in ADR-002.0 Section 10.3.
"""
from typing import Optional

_SHADOW_FILTER = "AND NOT (json_extract(details, '$.is_shadow') = 1)"


def calc_tokens_used(
    storage,
    tenant_id: str,
    start: str,
    end: str,
    include_shadow: bool = False,
) -> dict:
    sf = "" if include_shadow else _SHADOW_FILTER
    row = storage.execute_fetchone(
        f"""SELECT
              SUM(CASE WHEN agent_routed_to = 'claude-api' THEN tokens_used ELSE 0 END) AS actual,
              SUM(COALESCE(
                CAST(json_extract(details, '$.estimated_claude_tokens') AS INTEGER),
                tokens_used
              )) AS estimated,
              SUM(CASE WHEN agent_routed_to = 'claude-api' THEN cost_usd ELSE 0 END) AS actual_cost,
              SUM(COALESCE(
                CAST(json_extract(details, '$.estimated_claude_cost_usd') AS REAL),
                cost_usd
              )) AS estimated_cost,
              COUNT(*) AS n
            FROM audit_events
            WHERE event_type = 'agent_invoked'
              AND tenant_id = ? AND timestamp >= ? AND timestamp < ?
              {sf}""",
        (tenant_id, start, end),
    )
    row = row or {}
    actual = row.get("actual") or 0
    estimated = row.get("estimated") or 0
    n = row.get("n") or 0
    return {
        "actual_claude_tokens": actual,
        "estimated_all_claude_tokens": estimated,
        "savings_tokens": max(0, estimated - actual),
        "savings_pct": round((estimated - actual) / estimated * 100, 1) if estimated else 0.0,
        "actual_cost_usd": round(row.get("actual_cost") or 0, 6),
        "synthetic_cost_usd": round(row.get("estimated_cost") or 0, 6),
        "sample_size": n,
        "warnings": ["small_sample"] if n < 50 else [],
    }


def calc_throughput(
    storage,
    tenant_id: str,
    start: str,
    end: str,
    include_shadow: bool = False,
) -> dict:
    sf = "" if include_shadow else _SHADOW_FILTER
    row = storage.execute_fetchone(
        f"""SELECT
              COUNT(*) AS n,
              MIN(timestamp) AS first_task,
              MAX(timestamp) AS last_task,
              CAST(COUNT(*) AS REAL) /
                NULLIF((julianday(MAX(timestamp)) - julianday(MIN(timestamp))) * 24.0, 0)
                AS tasks_per_hour,
              AVG(execution_time_ms) AS avg_latency
            FROM audit_events
            WHERE event_type = 'task_completed'
              AND tenant_id = ? AND timestamp >= ? AND timestamp < ?
              {sf}""",
        (tenant_id, start, end),
    )

    # Median latency (approximate via SQLite window)
    median_row = storage.execute_fetchone(
        """WITH ranked AS (
             SELECT execution_time_ms,
               ROW_NUMBER() OVER (ORDER BY execution_time_ms) AS rn,
               COUNT(*) OVER () AS total
             FROM audit_events
             WHERE event_type = 'task_completed'
               AND tenant_id = ? AND timestamp >= ? AND timestamp < ?
               AND execution_time_ms IS NOT NULL
           )
           SELECT execution_time_ms AS median FROM ranked
           WHERE rn = total / 2 LIMIT 1""",
        (tenant_id, start, end),
    )

    # p95 latency
    p95_row = storage.execute_fetchone(
        """WITH ranked AS (
             SELECT execution_time_ms,
               ROW_NUMBER() OVER (ORDER BY execution_time_ms) AS rn,
               COUNT(*) OVER () AS total
             FROM audit_events
             WHERE event_type = 'task_completed'
               AND tenant_id = ? AND timestamp >= ? AND timestamp < ?
               AND execution_time_ms IS NOT NULL
           )
           SELECT execution_time_ms AS p95 FROM ranked
           WHERE rn = CAST(total * 0.95 AS INTEGER) LIMIT 1""",
        (tenant_id, start, end),
    )

    # Per-route breakdown
    route_rows = []
    for route in ("ollama-local", "claude-api"):
        r = storage.execute_fetchone(
            """SELECT COUNT(*) AS n, AVG(execution_time_ms) AS avg_ms
               FROM audit_events
               WHERE event_type = 'agent_invoked' AND agent_routed_to = ?
                 AND tenant_id = ? AND timestamp >= ? AND timestamp < ?""",
            (route, tenant_id, start, end),
        )
        route_rows.append((route, r or {}))

    row = row or {}
    n = row.get("n") or 0
    return {
        "tasks_per_hour": round(row.get("tasks_per_hour") or 0.0, 2),
        "latency_median_ms": (median_row or {}).get("median"),
        "latency_p95_ms": (p95_row or {}).get("p95"),
        "by_route": {
            r: {"count": d.get("n") or 0, "avg_latency_ms": round(d.get("avg_ms") or 0)}
            for r, d in route_rows
        },
        "sample_size": n,
        "warnings": ["small_sample"] if n < 50 else [],
    }


def calc_approval_rate(storage, tenant_id: str, start: str, end: str) -> dict:
    row = storage.execute_fetchone(
        """SELECT
             SUM(CASE WHEN event_type = 'approval_granted' THEN 1 ELSE 0 END) AS granted,
             SUM(CASE WHEN event_type = 'approval_denied'  THEN 1 ELSE 0 END) AS denied,
             SUM(CASE WHEN event_type IN ('approval_granted', 'approval_denied') THEN 1 ELSE 0 END) AS total,
             CAST(SUM(CASE WHEN event_type = 'approval_granted' THEN 1 ELSE 0 END) AS REAL) /
               NULLIF(SUM(CASE WHEN event_type IN ('approval_granted', 'approval_denied')
                              THEN 1 ELSE 0 END), 0) * 100 AS rate_pct
           FROM audit_events
           WHERE tenant_id = ? AND timestamp >= ? AND timestamp < ?""",
        (tenant_id, start, end),
    )
    row = row or {}
    total = row.get("total") or 0
    warnings = []
    if total < 20:
        warnings.append("small_sample")
    return {
        "approval_rate_pct": round(row.get("rate_pct") or 0.0, 1) if total >= 5 else None,
        "granted": row.get("granted") or 0,
        "denied": row.get("denied") or 0,
        "total_requests": total,
        "sample_size": total,
        "warnings": warnings,
    }


def calc_system_error_rate(storage, tenant_id: str, start: str, end: str) -> dict:
    row = storage.execute_fetchone(
        """WITH stats AS (
             SELECT
               SUM(CASE WHEN event_type IN ('system_error', 'task_failed')
                        AND NOT (json_extract(details, '$.cause') = 'user_cancelled')
                        THEN 1 ELSE 0 END) AS error_count,
               SUM(CASE WHEN event_type = 'task_started' THEN 1 ELSE 0 END) AS task_count
             FROM audit_events
             WHERE tenant_id = ? AND timestamp >= ? AND timestamp < ?
           )
           SELECT error_count, task_count,
                  CAST(error_count AS REAL) / NULLIF(task_count, 0) * 1000 AS errors_per_1000
           FROM stats""",
        (tenant_id, start, end),
    )
    row = row or {}
    task_count = row.get("task_count") or 0
    return {
        "errors_per_1000": round(row.get("errors_per_1000") or 0.0, 2),
        "error_count": row.get("error_count") or 0,
        "task_count": task_count,
        "sample_size": task_count,
        "warnings": ["small_sample"] if task_count < 100 else [],
    }


def calc_boundary_enforcement(storage, tenant_id: str, start: str, end: str) -> dict:
    row = storage.execute_fetchone(
        """SELECT
             COUNT(*) AS enforcement_count,
             SUM(CASE WHEN sensitivity_level = 'sensitive_phi'  THEN 1 ELSE 0 END) AS phi,
             SUM(CASE WHEN sensitivity_level = 'confidential'   THEN 1 ELSE 0 END) AS confidential,
             SUM(CASE WHEN sensitivity_level NOT IN ('sensitive_phi', 'confidential') THEN 1 ELSE 0 END) AS other
           FROM audit_events
           WHERE event_type = 'boundary_enforced'
             AND tenant_id = ? AND timestamp >= ? AND timestamp < ?""",
        (tenant_id, start, end),
    )

    violations_row = storage.execute_fetchone(
        """SELECT COUNT(*) AS violations
           FROM audit_events
           WHERE event_type = 'agent_invoked'
             AND sensitivity_level = 'sensitive_phi'
             AND agent_routed_to != 'ollama-local'
             AND tenant_id = ? AND timestamp >= ? AND timestamp < ?""",
        (tenant_id, start, end),
    )

    row = row or {}
    violations = (violations_row or {}).get("violations") or 0
    return {
        "enforcement_count": row.get("enforcement_count") or 0,
        "phi_enforced": row.get("phi") or 0,
        "confidential_enforced": row.get("confidential") or 0,
        "other_enforced": row.get("other") or 0,
        "suspected_violations": violations,
        "sample_size": row.get("enforcement_count") or 0,
        "warnings": ["VIOLATION_DETECTED"] if violations > 0 else [],
    }
