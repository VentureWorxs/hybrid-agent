"""
HTTP client for the Cloudflare Worker sync endpoint.
Distinct from D1AuditStorage (which talks to the D1 REST API directly).
This client pushes sanitized event batches to the deployed Worker.
"""
import json
import logging
import os
from typing import Optional

import httpx

from .models import AuditEvent

log = logging.getLogger(__name__)


class D1WorkerClient:
    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ):
        self.endpoint_url = endpoint_url or os.environ["SYNC_ENDPOINT_URL"]
        self.client_id = client_id or os.environ.get("CF_ACCESS_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("CF_ACCESS_CLIENT_SECRET", "")

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.client_id:
            h["CF-Access-Client-Id"] = self.client_id
        if self.client_secret:
            h["CF-Access-Client-Secret"] = self.client_secret
        return h

    def _event_to_dict(self, event: AuditEvent) -> dict:
        return {
            "event_id": event.event_id,
            "sequence_number": event.sequence_number,
            "previous_hash": event.previous_hash,
            "event_hash": event.event_hash,
            "tenant_id": event.tenant_id,
            "machine_id": event.machine_id,
            "session_id": event.session_id,
            "agent_version": event.agent_version,
            "timestamp": event.timestamp,
            "event_type": event.event_type,
            "actor": event.actor,
            "subject_type": event.subject_type,
            "subject_id": event.subject_id,
            "action": event.action,
            "scope_level": event.scope_level,
            "approval_status": event.approval_status,
            "approval_by": event.approval_by,
            "sensitivity_level": event.sensitivity_level,
            "tokens_used": event.tokens_used,
            "cost_usd": event.cost_usd,
            "execution_time_ms": event.execution_time_ms,
            "agent_routed_to": event.agent_routed_to,
            "boundary_enforced": event.boundary_enforced,
            "details": event.details,
        }

    def push_batch(self, events: list[AuditEvent]) -> dict[str, str]:
        """
        POST a batch to the Cloudflare Worker.
        Returns {event_id: 'success' | 'duplicate_skipped' | error_message}.
        """
        if not events:
            return {}

        payload = {
            "machine_id": events[0].machine_id,
            "tenant_id": events[0].tenant_id,
            "events": [self._event_to_dict(e) for e in events],
        }

        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    self.endpoint_url,
                    headers=self._headers(),
                    json=payload,
                )
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as e:
            log.error("D1 push failed: %s", e)
            return {ev.event_id: f"transport_error: {e}" for ev in events}
