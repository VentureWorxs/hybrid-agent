"""
Shadow mode parallel execution.
Runs both the primary route and the opposing route concurrently.
The primary result is returned to the caller; the shadow result is logged only.
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from ulid import ULID

log = logging.getLogger(__name__)


@dataclass
class AgentResult:
    content: str
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    error: Optional[str] = None


class ShadowRunner:
    """
    Executes primary route and shadow route in parallel.
    Requires two async callables: ollama_invoke and claude_invoke.
    Both take (prompt: str) and return AgentResult.
    """

    def __init__(self, ollama_invoke, claude_invoke, audit_logger, synthetic_baseline_fn=None):
        self.ollama_invoke = ollama_invoke
        self.claude_invoke = claude_invoke
        self.audit = audit_logger
        self.synthetic_baseline_fn = synthetic_baseline_fn

    async def run_pair(
        self,
        prompt: str,
        primary_route: str,
        sensitivity_level: str = "public",
    ) -> dict[str, Any]:
        shadow_pair_id = str(ULID())
        shadow_route = "claude-api" if primary_route == "ollama-local" else "ollama-local"

        primary_coro = self._run_one(prompt, primary_route, shadow_pair_id, is_shadow=False, sensitivity_level=sensitivity_level)
        shadow_coro = self._run_one(prompt, shadow_route, shadow_pair_id, is_shadow=True, sensitivity_level=sensitivity_level)

        primary_result, shadow_result = await asyncio.gather(
            primary_coro, shadow_coro, return_exceptions=True
        )

        return {
            "primary": primary_result,
            "shadow_pair_id": shadow_pair_id,
            "primary_route": primary_route,
            "shadow_route": shadow_route,
        }

    async def _run_one(
        self,
        prompt: str,
        route: str,
        pair_id: str,
        is_shadow: bool,
        sensitivity_level: str,
    ) -> AgentResult:
        invoke = self.ollama_invoke if route == "ollama-local" else self.claude_invoke
        start = time.monotonic()
        try:
            result: AgentResult = await invoke(prompt)
        except Exception as e:
            result = AgentResult(content="", error=str(e))

        result.duration_ms = int((time.monotonic() - start) * 1000)

        details: dict = {
            "shadow_pair_id": pair_id,
            "is_shadow": is_shadow,
        }
        if self.synthetic_baseline_fn and route == "ollama-local":
            baseline = self.synthetic_baseline_fn(len(prompt), len(result.content))
            details.update(baseline)

        self.audit.log(
            event_type="agent_invoked",
            actor=f"agent:{route}",
            action=f"Shadow pair {pair_id} — {'shadow' if is_shadow else 'primary'} via {route}",
            sensitivity_level=sensitivity_level,
            agent_routed_to=route,
            tokens_used=result.tokens_used,
            cost_usd=result.cost_usd,
            execution_time_ms=result.duration_ms,
            details=details,
        )
        return result
