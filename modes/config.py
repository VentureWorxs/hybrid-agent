"""
TOML config loader/writer for ~/.hybrid-agent/config.toml.
Uses stdlib tomllib (Python 3.11+) for reading, tomli_w for writing.
"""
import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

import tomli_w

CONFIG_PATH = Path.home() / ".hybrid-agent" / "config.toml"


def default_config() -> dict:
    return {
        "hybrid_agent": {
            "operating_mode": "hybrid",
            "audit_sync_enabled": True,
            "agent_version": "1.1.0",
            "shadow_campaign": {
                "enabled": False,
                "start_at": "",
                "end_at": "",
            },
            "estimation": {
                "claude_input_cost_per_mtoken": 3.00,
                "claude_output_cost_per_mtoken": 15.00,
                "char_to_token_ratio": 4.0,
            },
        }
    }


def load_global_config(config_path: Path = CONFIG_PATH) -> dict:
    if not config_path.exists():
        cfg = default_config()
        save_global_config(cfg, config_path)
        return cfg
    with open(config_path, "rb") as f:
        return tomllib.load(f)


def save_global_config(config: dict, config_path: Path = CONFIG_PATH) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "wb") as f:
        tomli_w.dump(config, f)


def get_nested(config: dict, *keys: str, default: Any = None) -> Any:
    """Safe nested key access: get_nested(cfg, 'hybrid_agent', 'operating_mode')"""
    obj = config
    for key in keys:
        if not isinstance(obj, dict) or key not in obj:
            return default
        obj = obj[key]
    return obj
