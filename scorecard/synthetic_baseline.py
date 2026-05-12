def estimate_claude_tokens(
    input_chars: int,
    output_chars: int,
    ratio: float = 4.0,
) -> dict:
    """Estimate Claude token counts from character counts."""
    input_tokens = int(input_chars / ratio)
    output_tokens = int(output_chars / ratio)
    return {
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_claude_tokens": input_tokens + output_tokens,
    }


def estimate_claude_cost_usd(
    input_tokens: int,
    output_tokens: int,
    input_rate: float = 3.00,   # USD per million
    output_rate: float = 15.00,
) -> float:
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


def make_baseline_details(
    input_chars: int,
    output_chars: int,
    ratio: float = 4.0,
    input_rate: float = 3.00,
    output_rate: float = 15.00,
) -> dict:
    """
    Produce the details dict stored on each Ollama agent_invoked event
    so KPI A can sum estimated_claude_tokens and estimated_claude_cost_usd.
    """
    tokens = estimate_claude_tokens(input_chars, output_chars, ratio)
    cost = estimate_claude_cost_usd(
        tokens["estimated_input_tokens"],
        tokens["estimated_output_tokens"],
        input_rate,
        output_rate,
    )
    return {
        "input_chars": input_chars,
        "output_chars": output_chars,
        **tokens,
        "estimated_claude_cost_usd": round(cost, 8),
    }
