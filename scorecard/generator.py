from datetime import datetime, timezone
from typing import Optional

from .epochs import resolve_epoch, get_epochs, Epoch
from .kpi_calculators import (
    calc_tokens_used,
    calc_throughput,
    calc_approval_rate,
    calc_system_error_rate,
    calc_boundary_enforcement,
)


def _summary_from_kpis(kpis: dict) -> dict:
    tokens = kpis["tokens_used"]
    tp = kpis["throughput"]
    err = kpis["system_error_rate"]
    bc = kpis["boundary_enforcement"]
    return {
        "tasks_completed": tp["sample_size"],
        "throughput_per_hour": tp["tasks_per_hour"],
        "total_cost_usd": tokens["actual_cost_usd"],
        "synthetic_cost_usd": tokens["synthetic_cost_usd"],
        "cost_savings_usd": round(tokens["synthetic_cost_usd"] - tokens["actual_cost_usd"], 6),
        "cost_savings_pct": tokens["savings_pct"],
        "error_count": err["error_count"],
        "boundary_enforcement_count": bc["enforcement_count"],
        "suspected_violations": bc["suspected_violations"],
    }


def _compute_kpis(storage, tenant_id: str, start: str, end: str, include_shadow: bool) -> dict:
    return {
        "tokens_used": calc_tokens_used(storage, tenant_id, start, end, include_shadow),
        "throughput": calc_throughput(storage, tenant_id, start, end, include_shadow),
        "approval_rate": calc_approval_rate(storage, tenant_id, start, end),
        "system_error_rate": calc_system_error_rate(storage, tenant_id, start, end),
        "boundary_enforcement": calc_boundary_enforcement(storage, tenant_id, start, end),
    }


def _epoch_end(epoch: Epoch) -> str:
    return epoch.ended_at or datetime.now(timezone.utc).isoformat()


def generate_scorecard(
    storage,
    tenant_id: str,
    epoch_selector: str = "CURRENT",
    period: Optional[str] = None,
    compare_to: Optional[str] = None,
    include_shadow: bool = False,
) -> dict:
    """
    Generate the full scorecard JSON structure.
    Returns a dict matching ADR-002.0 Section 10.3.
    """
    tenant = storage.get_tenant(tenant_id) or {
        "tenant_id": tenant_id,
        "display_name": tenant_id,
        "metadata": {},
    }

    primary = resolve_epoch(storage, tenant_id, epoch_selector, period)
    start, end = primary.started_at, _epoch_end(primary)
    kpis = _compute_kpis(storage, tenant_id, start, end, include_shadow)

    comparison = None
    notes = []

    if compare_to:
        comp_epoch = resolve_epoch(storage, tenant_id, compare_to)
        comp_start, comp_end = comp_epoch.started_at, _epoch_end(comp_epoch)
        comp_kpis = _compute_kpis(storage, tenant_id, comp_start, comp_end, include_shadow)

        tok_a = comp_kpis["tokens_used"]["estimated_all_claude_tokens"] or 0
        tok_b = kpis["tokens_used"]["estimated_all_claude_tokens"] or 0

        comparison = {
            "epoch_a": {
                "epoch_id": comp_epoch.epoch_id,
                "sequence": comp_epoch.sequence,
                "operating_mode": comp_epoch.operating_mode,
                "summary": _summary_from_kpis(comp_kpis),
            },
            "epoch_b": {
                "epoch_id": primary.epoch_id,
                "sequence": primary.sequence,
                "operating_mode": primary.operating_mode,
                "summary": _summary_from_kpis(kpis),
            },
            "deltas": {
                "tokens_used_pct": _safe_pct_delta(
                    comp_kpis["tokens_used"]["actual_claude_tokens"],
                    kpis["tokens_used"]["actual_claude_tokens"],
                ),
                "throughput_pct": _safe_pct_delta(
                    comp_kpis["throughput"]["tasks_per_hour"],
                    kpis["throughput"]["tasks_per_hour"],
                ),
                "approval_rate_pp": _safe_pp_delta(
                    comp_kpis["approval_rate"]["approval_rate_pct"],
                    kpis["approval_rate"]["approval_rate_pct"],
                ),
                "error_rate_pct": _safe_pct_delta(
                    comp_kpis["system_error_rate"]["errors_per_1000"],
                    kpis["system_error_rate"]["errors_per_1000"],
                ),
                "boundary_count_delta": (
                    kpis["boundary_enforcement"]["enforcement_count"]
                    - comp_kpis["boundary_enforcement"]["enforcement_count"]
                ),
            },
            "comparability_warnings": _comparability_warnings(primary, comp_epoch, kpis, comp_kpis),
        }

    return {
        "scorecard_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tenant": {
            "tenant_id": tenant["tenant_id"],
            "display_name": tenant.get("display_name", tenant_id),
        },
        "epoch": primary.to_dict(),
        "period": {"start": start, "end": end},
        "summary": _summary_from_kpis(kpis),
        "kpis": kpis,
        "comparison": comparison,
        "notes": notes,
    }


def _safe_pct_delta(a, b) -> Optional[float]:
    if a is None or b is None or a == 0:
        return None
    return round((b - a) / abs(a) * 100, 1)


def _safe_pp_delta(a, b) -> Optional[float]:
    if a is None or b is None:
        return None
    return round(b - a, 1)


def _comparability_warnings(ep_a: Epoch, ep_b: Epoch, kpis_a: dict, kpis_b: dict) -> list[str]:
    warnings = []
    n_a = kpis_a["throughput"]["sample_size"]
    n_b = kpis_b["throughput"]["sample_size"]
    if n_a and n_b and max(n_a, n_b) / max(min(n_a, n_b), 1) > 10:
        warnings.append("sample_sizes_differ_10x")
    if ep_a.operating_mode == "shadow" or ep_b.operating_mode == "shadow":
        warnings.append("shadow_mode_epoch_included — cost comparison may be misleading")
    return warnings
