import json
import logging
from pathlib import Path
from typing import Optional

from .config import load_global_config, save_global_config, CONFIG_PATH

log = logging.getLogger(__name__)

VALID_MODES = {"baseline", "hybrid", "shadow"}


class ModeController:
    """Single source of truth for resolved operating mode and sync state."""

    def __init__(self, storage, audit_logger, config_path: Path = CONFIG_PATH):
        self.storage = storage
        self.audit = audit_logger
        self.config_path = config_path
        self._global_config = load_global_config(config_path)
        self._session_overrides: dict = {}

    def resolve_mode(self, tenant_id: str) -> str:
        if "operating_mode" in self._session_overrides:
            return self._session_overrides["operating_mode"]
        tenant = self.storage.get_tenant(tenant_id)
        if tenant and tenant.get("metadata", {}).get("operating_mode"):
            return tenant["metadata"]["operating_mode"]
        return self._global_config["hybrid_agent"]["operating_mode"]

    def resolve_sync_enabled(self, tenant_id: str) -> bool:
        if "audit_sync_enabled" in self._session_overrides:
            return bool(self._session_overrides["audit_sync_enabled"])
        tenant = self.storage.get_tenant(tenant_id)
        if tenant and "audit_sync_enabled" in (tenant.get("metadata") or {}):
            return bool(tenant["metadata"]["audit_sync_enabled"])
        return bool(self._global_config["hybrid_agent"]["audit_sync_enabled"])

    def set_mode(
        self,
        mode: str,
        scope: str,
        tenant_id: Optional[str] = None,
        session_id: Optional[str] = None,
        actor: str = "user",
    ) -> None:
        if mode not in VALID_MODES:
            raise ValueError(f"Invalid mode '{mode}'. Must be one of {VALID_MODES}")

        old_value = self.resolve_mode(tenant_id or "sam-personal")

        if scope == "global":
            self._global_config["hybrid_agent"]["operating_mode"] = mode
            save_global_config(self._global_config, self.config_path)
        elif scope == "tenant":
            if not tenant_id:
                raise ValueError("tenant_id required for scope='tenant'")
            self.storage.update_tenant_metadata(tenant_id, {"operating_mode": mode})
        elif scope == "session":
            self._session_overrides["operating_mode"] = mode
        else:
            raise ValueError(f"Invalid scope '{scope}'. Must be global, tenant, or session")

        self.audit.log(
            event_type="config_changed",
            actor=actor,
            action=f"Operating mode: {old_value} → {mode} (scope: {scope})",
            details={
                "scope": scope,
                "field": "operating_mode",
                "old_value": old_value,
                "new_value": mode,
                "tenant_id": tenant_id,
                "session_id": session_id,
            },
        )
        log.info("Mode changed: %s → %s (scope=%s)", old_value, mode, scope)

    def set_sync_enabled(
        self,
        enabled: bool,
        scope: str,
        tenant_id: Optional[str] = None,
        actor: str = "user",
    ) -> None:
        old_value = self.resolve_sync_enabled(tenant_id or "sam-personal")

        if scope == "global":
            self._global_config["hybrid_agent"]["audit_sync_enabled"] = enabled
            save_global_config(self._global_config, self.config_path)
        elif scope == "tenant":
            if not tenant_id:
                raise ValueError("tenant_id required for scope='tenant'")
            self.storage.update_tenant_metadata(tenant_id, {"audit_sync_enabled": enabled})
        elif scope == "session":
            self._session_overrides["audit_sync_enabled"] = enabled
        else:
            raise ValueError(f"Invalid scope: {scope}")

        self.audit.log(
            event_type="config_changed",
            actor=actor,
            action=f"audit_sync_enabled: {old_value} → {enabled} (scope: {scope})",
            details={
                "scope": scope,
                "field": "audit_sync_enabled",
                "old_value": old_value,
                "new_value": enabled,
                "tenant_id": tenant_id,
            },
        )

    def get_estimation_config(self) -> dict:
        return self._global_config["hybrid_agent"].get("estimation", {})

    def reload_config(self) -> None:
        self._global_config = load_global_config(self.config_path)
