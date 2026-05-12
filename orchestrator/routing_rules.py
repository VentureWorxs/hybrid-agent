import json
import logging
from typing import Optional

from .compliance_boundary import ComplianceBoundary
from .decision_cache import DecisionCache
from .task_classifier import TaskClassifier

log = logging.getLogger(__name__)

OLLAMA_COMPLEXITY_THRESHOLD = 3  # complexity ≤ this → route to Ollama


class Router:
    """
    Core routing logic. Determines which agent handles each task.
    Respects operating_mode from ModeController when injected.
    """

    def __init__(
        self,
        decision_cache: DecisionCache,
        classifier: TaskClassifier,
        boundary: ComplianceBoundary,
        audit,
        mode_controller=None,
    ):
        self.cache = decision_cache
        self.classifier = classifier
        self.boundary = boundary
        self.audit = audit
        self.mode_controller = mode_controller

    def route(
        self,
        tenant_id: str,
        action: str,
        context: dict,
        data: str = "",
        sensitivity_override: Optional[str] = None,
    ) -> str:
        operating_mode = "hybrid"
        if self.mode_controller:
            operating_mode = self.mode_controller.resolve_mode(tenant_id)

        if operating_mode == "baseline":
            route = "claude-api"
            self._log_routing(tenant_id, action, route, complexity=None, sensitivity="public", from_cache=False)
            return route

        # Check cache
        cached = self.cache.lookup(tenant_id, context, "routing")
        if cached:
            decision = json.loads(cached["decision_value"])
            return decision.get("routed_to", "claude-api")

        # Classify
        complexity = self.classifier.assess_complexity(action, context)
        sensitivity = sensitivity_override or self.classifier.assess_sensitivity(
            data or action, tenant_id
        )

        # Determine naive route, then enforce compliance boundary
        if complexity <= OLLAMA_COMPLEXITY_THRESHOLD:
            proposed = "ollama-local"
        else:
            proposed = "claude-api"

        route = self.boundary.enforce(sensitivity, proposed)

        # Cache and audit
        self.cache.store(
            tenant_id=tenant_id,
            context=context,
            decision_type="routing",
            decision_value={"routed_to": route},
            scope_level=1,
            ttl_hours=24,
            complexity=complexity,
            sensitivity_level=sensitivity,
        )
        self._log_routing(tenant_id, action, route, complexity, sensitivity, from_cache=False)
        return route

    def _log_routing(
        self,
        tenant_id: str,
        action: str,
        route: str,
        complexity: Optional[int],
        sensitivity: str,
        from_cache: bool,
    ) -> None:
        self.audit.log(
            event_type="routing_decision",
            actor="orchestrator",
            action=f"Routed '{action}' → {route}" + (" (cached)" if from_cache else ""),
            sensitivity_level=sensitivity,
            agent_routed_to=route,
            details={
                "complexity": complexity,
                "sensitivity_level": sensitivity,
                "from_cache": from_cache,
            },
        )
