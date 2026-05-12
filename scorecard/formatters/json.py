import json as _json


def render_json(scorecard: dict, indent: int = 2) -> str:
    return _json.dumps(scorecard, indent=indent, default=str)
