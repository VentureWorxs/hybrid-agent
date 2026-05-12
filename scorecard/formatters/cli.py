"""CLI table formatter for the scorecard."""


def _row(label: str, value: str, width: int = 28) -> str:
    return f"  {label:<{width}} {value}"


def _warn(warnings: list[str]) -> str:
    return "  ⚠ " + ", ".join(warnings) if warnings else ""


def render_cli(scorecard: dict, verbose: bool = False) -> str:
    lines = []
    tenant = scorecard["tenant"]["display_name"]
    ep = scorecard["epoch"]
    period = scorecard["period"]
    sm = scorecard["summary"]
    kpis = scorecard["kpis"]

    lines.append(f"\n{'─' * 60}")
    lines.append(f"  Hybrid Agent Scorecard — {tenant}")
    lines.append(f"  Epoch #{ep['sequence']} ({ep['operating_mode']})  |  "
                 f"{period['start'][:10]} → {period['end'][:10]}")
    lines.append(f"{'─' * 60}")

    # Summary
    lines.append("\n  SUMMARY")
    lines.append(_row("Tasks completed:", f"{sm['tasks_completed']:,}"))
    lines.append(_row("Throughput:", f"{sm['throughput_per_hour']:.2f} tasks/hr"))
    lines.append(_row("Claude cost (actual):", f"${sm['total_cost_usd']:.4f}"))
    lines.append(_row("Claude cost (synthetic):", f"${sm['synthetic_cost_usd']:.4f}"))
    lines.append(_row("Cost savings:", f"${sm['cost_savings_usd']:.4f}  ({sm['cost_savings_pct']:.1f}%)"))
    lines.append(_row("Errors:", str(sm["error_count"])))
    lines.append(_row("Boundary enforcements:", str(sm["boundary_enforcement_count"])))
    if sm["suspected_violations"]:
        lines.append(f"\n  ⚠ ALERT: {sm['suspected_violations']} suspected PHI boundary violation(s)!")

    # KPI A
    t = kpis["tokens_used"]
    lines.append("\n  KPI A — Tokens Used")
    lines.append(_row("Actual Claude tokens:", f"{t['actual_claude_tokens']:,}"))
    lines.append(_row("Synthetic baseline:", f"{t['estimated_all_claude_tokens']:,}"))
    lines.append(_row("Savings:", f"{t['savings_tokens']:,}  ({t['savings_pct']:.1f}%)"))
    lines.append(_row("Sample size:", str(t["sample_size"])))
    if t["warnings"]:
        lines.append(_warn(t["warnings"]))

    # KPI B
    tp = kpis["throughput"]
    lines.append("\n  KPI B — Throughput")
    lines.append(_row("Tasks/hour:", f"{tp['tasks_per_hour']:.2f}"))
    lines.append(_row("Latency median:", f"{tp['latency_median_ms']} ms" if tp["latency_median_ms"] else "n/a"))
    lines.append(_row("Latency p95:", f"{tp['latency_p95_ms']} ms" if tp["latency_p95_ms"] else "n/a"))
    if verbose:
        for route, stats in tp["by_route"].items():
            lines.append(_row(f"  {route}:", f"{stats['count']:,} tasks, {stats['avg_latency_ms']} ms avg"))
    lines.append(_row("Sample size:", str(tp["sample_size"])))

    # KPI C
    ar = kpis["approval_rate"]
    lines.append("\n  KPI C — Approval Rate")
    rate_str = f"{ar['approval_rate_pct']:.1f}%" if ar["approval_rate_pct"] is not None else "n/a (too few samples)"
    lines.append(_row("Approval rate:", rate_str))
    lines.append(_row("Granted / Denied:", f"{ar['granted']} / {ar['denied']}"))
    lines.append(_row("Sample size:", str(ar["sample_size"])))
    if ar["warnings"]:
        lines.append(_warn(ar["warnings"]))

    # KPI D
    err = kpis["system_error_rate"]
    lines.append("\n  KPI D — System Error Rate")
    lines.append(_row("Errors per 1,000:", f"{err['errors_per_1000']:.2f}"))
    lines.append(_row("Errors / Tasks:", f"{err['error_count']} / {err['task_count']:,}"))
    if err["warnings"]:
        lines.append(_warn(err["warnings"]))

    # KPI E
    bc = kpis["boundary_enforcement"]
    lines.append("\n  KPI E — Boundary Enforcement")
    lines.append(_row("Total enforcements:", str(bc["enforcement_count"])))
    if verbose or bc["phi_enforced"]:
        lines.append(_row("  PHI:", str(bc["phi_enforced"])))
        lines.append(_row("  Confidential:", str(bc["confidential_enforced"])))
    violations_flag = "✓" if bc["suspected_violations"] == 0 else f"⚠ {bc['suspected_violations']} VIOLATIONS"
    lines.append(_row("Suspected violations:", violations_flag))

    # Comparison section
    if scorecard.get("comparison"):
        comp = scorecard["comparison"]
        deltas = comp["deltas"]
        lines.append(f"\n{'─' * 60}")
        lines.append(f"  COMPARISON  Epoch #{comp['epoch_a']['sequence']} → #{comp['epoch_b']['sequence']}")
        lines.append(f"{'─' * 60}")

        def _delta(val, suffix="", higher_is_better=True):
            if val is None:
                return "n/a"
            sign = "+" if val > 0 else ""
            direction = ("▲" if val > 0 else "▼") if higher_is_better else ("▼" if val > 0 else "▲")
            return f"{direction} {sign}{val:.1f}{suffix}"

        lines.append(_row("Token savings:", _delta(deltas.get("tokens_used_pct"), "%", higher_is_better=False)))
        lines.append(_row("Throughput:", _delta(deltas.get("throughput_pct"), "%")))
        lines.append(_row("Approval rate:", _delta(deltas.get("approval_rate_pp"), "pp")))
        lines.append(_row("Error rate:", _delta(deltas.get("error_rate_pct"), "%", higher_is_better=False)))

        for w in comp.get("comparability_warnings", []):
            lines.append(f"\n  ⚠ {w}")

    lines.append(f"\n{'─' * 60}\n")
    return "\n".join(lines)
