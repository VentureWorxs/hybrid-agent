ALLOWED_ROUTES: dict[str, list[str]] = {
    "public":        ["ollama-local", "claude-api"],
    "internal":      ["ollama-local", "claude-api"],
    "confidential":  ["ollama-local"],
    "sensitive_phi": ["ollama-local"],
}


class BoundaryViolationError(Exception):
    pass


class ComplianceBoundary:
    """Enforce routing rules based on sensitivity level."""

    def can_route_to(self, sensitivity_level: str, route: str) -> bool:
        allowed = ALLOWED_ROUTES.get(sensitivity_level, [])
        return route in allowed

    def enforce(self, sensitivity_level: str, proposed_route: str) -> str:
        """
        Return the compliant route. Raises BoundaryViolationError if the
        proposed_route is explicitly forbidden with no safe alternative.
        """
        if self.can_route_to(sensitivity_level, proposed_route):
            return proposed_route

        allowed = ALLOWED_ROUTES.get(sensitivity_level, [])
        if allowed:
            return allowed[0]  # fallback to first allowed (ollama-local)

        raise BoundaryViolationError(
            f"No compliant route for sensitivity_level='{sensitivity_level}'"
        )
