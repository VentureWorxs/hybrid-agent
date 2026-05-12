import re

_PHI_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                     # SSN
    re.compile(r"\bDOB\b|\bdate of birth\b", re.I),
    re.compile(r"\bpatient\b|\bmedical record\b|\bdiagnosis\b", re.I),
    re.compile(r"\bHIPAA\b|\bPHI\b|\bEHR\b|\bEMR\b", re.I),
]

_PII_PATTERNS = [
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),
]

COMPLEXITY_HEURISTICS: dict[str, int] = {
    "status_check": 1,
    "data_extraction": 2,
    "template_fill": 2,
    "summarize": 2,
    "classification": 3,
    "doc_generation": 3,
    "pattern_analysis": 5,
    "comparison": 5,
    "code_review": 6,
    "multi_step_reasoning": 8,
    "strategic_recommendation": 9,
    "novel_problem": 10,
    "architectural_decision": 10,
}


class TaskClassifier:
    """
    Classify tasks by complexity (0–10) and sensitivity level.
    Heuristic-based; intended to be refined with empirical data.
    """

    def assess_complexity(self, action: str, context: dict | None = None) -> int:
        action_lower = action.lower()
        for pattern, score in COMPLEXITY_HEURISTICS.items():
            if pattern.replace("_", " ") in action_lower or pattern in action_lower:
                return score
        return 5  # default: medium complexity

    def assess_sensitivity(self, text: str, tenant_id: str = "sam-personal") -> str:
        """Return the highest applicable sensitivity level."""
        if any(p.search(text) for p in _PHI_PATTERNS):
            return "sensitive_phi"
        if any(p.search(text) for p in _PII_PATTERNS):
            return "internal"
        if tenant_id == "propel":
            # Propel content defaults to confidential unless explicitly public
            return "confidential"
        return "public"
