"""Markdown report formatter for the scorecard."""
from datetime import datetime


def render_markdown(scorecard: dict) -> str:
    tenant = scorecard["tenant"]["display_name"]
    ep = scorecard["epoch"]
    period = scorecard["period"]
    sm = scorecard["summary"]
    kpis = scorecard["kpis"]
    gen = scorecard.get("generated_at", datetime.utcnow().isoformat())[:19]

    lines = [
        f"# Hybrid Agent Scorecard — {tenant}",
        "",
        f"**Generated**: {gen}",
        f"**Epoch**: {ep['epoch_id']} (sequence #{ep['sequence']})",
        f"**Period**: {period['start'][:10]} to {period['end'][:10]}",
        f"**Mode**: {ep['operating_mode']}",
        f"**Sync enabled**: {ep['audit_sync_enabled']}",
        "",
        "## Summary",
        "",
        f"- **Tasks completed**: {sm['tasks_completed']:,}",
        f"- **Throughput**: {sm['throughput_per_hour']:.2f} tasks/hour",
        f"- **Total Claude cost**: ${sm['total_cost_usd']:.4f} "
        f"(synthetic baseline: ${sm['synthetic_cost_usd']:.4f}, "
        f"savings: {sm['cost_savings_pct']:.1f}%)",
        f"- **System errors**: {sm['error_count']}",
        f"- **Compliance enforcements**: {sm['boundary_enforcement_count']}",
    ]

    if sm["suspected_violations"]:
        lines.append(f"\n> ⚠️ **ALERT**: {sm['suspected_violations']} suspected PHI boundary violation(s).")

    # KPI A
    t = kpis["tokens_used"]
    lines += [
        "", "## KPI Detail", "", "### A. Tokens Used",
        f"- Actual Claude tokens: {t['actual_claude_tokens']:,}",
        f"- Synthetic baseline: {t['estimated_all_claude_tokens']:,}",
        f"- Savings: {t['savings_tokens']:,} ({t['savings_pct']:.1f}%)",
        f"- Cost: ${t['actual_cost_usd']:.4f} vs ${t['synthetic_cost_usd']:.4f} (synthetic)",
        f"- Sample size: {t['sample_size']:,}",
    ]
    for w in t["warnings"]:
        lines.append(f"- ⚠ {w}")

    # KPI B
    tp = kpis["throughput"]
    lines += [
        "", "### B. Throughput",
        f"- Average: {tp['tasks_per_hour']:.2f} tasks/hour",
        f"- Latency (median / p95): {tp['latency_median_ms']} ms / {tp['latency_p95_ms']} ms",
        "- Per-route breakdown:",
    ]
    for route, stats in tp["by_route"].items():
        lines.append(f"  - {route}: {stats['count']:,} tasks, {stats['avg_latency_ms']} ms avg")
    lines.append(f"- Sample size: {tp['sample_size']:,}")
    for w in tp["warnings"]:
        lines.append(f"- ⚠ {w}")

    # KPI C
    ar = kpis["approval_rate"]
    rate_str = f"{ar['approval_rate_pct']:.1f}%" if ar["approval_rate_pct"] is not None else "n/a (too few samples)"
    lines += [
        "", "### C. Approval Rate",
        f"- Approval rate: {rate_str}",
        f"- Granted / Denied / Total: {ar['granted']} / {ar['denied']} / {ar['total_requests']}",
        f"- Sample size: {ar['sample_size']}",
    ]
    for w in ar["warnings"]:
        lines.append(f"- ⚠ {w}")

    # KPI D
    err = kpis["system_error_rate"]
    lines += [
        "", "### D. System Error Rate",
        f"- Rate: {err['errors_per_1000']:.2f} errors per 1,000 tasks",
        f"- Total: {err['error_count']} errors / {err['task_count']:,} tasks",
        f"- Sample size: {err['sample_size']:,}",
    ]
    for w in err["warnings"]:
        lines.append(f"- ⚠ {w}")

    # KPI E
    bc = kpis["boundary_enforcement"]
    violations_flag = "✓ 0" if bc["suspected_violations"] == 0 else f"⚠️ {bc['suspected_violations']} (INVESTIGATE)"
    lines += [
        "", "### E. Boundary Enforcement",
        f"- Total enforcements: {bc['enforcement_count']}",
        f"  - PHI: {bc['phi_enforced']}",
        f"  - Confidential: {bc['confidential_enforced']}",
        f"  - Other: {bc['other_enforced']}",
        f"- **Suspected violations**: {violations_flag}",
        f"- Sample size: {bc['sample_size']}",
    ]

    # Comparison
    if scorecard.get("comparison"):
        comp = scorecard["comparison"]
        deltas = comp["deltas"]
        ep_a = comp["epoch_a"]
        ep_b = comp["epoch_b"]

        def _delta(val, suffix="", higher_is_better=True):
            if val is None:
                return "n/a"
            sign = "+" if val > 0 else ""
            arrow = "↑" if val > 0 else "↓"
            return f"{arrow} {sign}{val:.1f}{suffix}"

        lines += [
            "", "## Comparison",
            "",
            f"| Metric | Epoch #{ep_a['sequence']} ({ep_a['operating_mode']}) "
            f"| Epoch #{ep_b['sequence']} ({ep_b['operating_mode']}) | Δ |",
            "|--------|------|------|---|",
            f"| Token savings | {ep_a['summary']['cost_savings_pct']:.1f}% "
            f"| {ep_b['summary']['cost_savings_pct']:.1f}% "
            f"| {_delta(deltas.get('tokens_used_pct'), '%', False)} |",
            f"| Throughput | {ep_a['summary']['throughput_per_hour']:.2f}/hr "
            f"| {ep_b['summary']['throughput_per_hour']:.2f}/hr "
            f"| {_delta(deltas.get('throughput_pct'), '%')} |",
            f"| Error rate | {ep_a['summary']['error_count']} "
            f"| {ep_b['summary']['error_count']} "
            f"| {_delta(deltas.get('error_rate_pct'), '%', False)} |",
            f"| Boundary enforcements | {ep_a['summary']['boundary_enforcement_count']} "
            f"| {ep_b['summary']['boundary_enforcement_count']} "
            f"| {deltas.get('boundary_count_delta', 'n/a')} |",
        ]
        for w in comp.get("comparability_warnings", []):
            lines.append(f"\n> ⚠️ {w}")

    lines.append("")
    return "\n".join(lines)
