export interface AuditEvent {
  event_id: string;
  sequence_number: number;
  previous_hash: string | null;
  event_hash: string;
  tenant_id: string;
  machine_id: string;
  session_id: string;
  agent_version: string;
  timestamp: string;
  event_type: string;
  actor: string;
  subject_type: string | null;
  subject_id: string | null;
  action: string;
  scope_level: number | null;
  approval_status: string | null;
  approval_by: string | null;
  sensitivity_level: string;
  tokens_used: number;
  cost_usd: number;
  execution_time_ms: number | null;
  agent_routed_to: string | null;
  boundary_enforced: number;
  details: string | null;
}

export type SyncResult = "success" | "duplicate_skipped" | string;

const INSERT_SQL = `
  INSERT OR IGNORE INTO audit_events (
    event_id, sequence_number, previous_hash, event_hash,
    tenant_id, machine_id, session_id, agent_version, timestamp,
    event_type, actor, subject_type, subject_id, action,
    scope_level, approval_status, approval_by,
    sensitivity_level, tokens_used, cost_usd, execution_time_ms,
    agent_routed_to, boundary_enforced, details
  ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
`.trim();

export async function writeEventBatch(
  db: D1Database,
  events: AuditEvent[]
): Promise<Record<string, SyncResult>> {
  const results: Record<string, SyncResult> = {};

  for (const event of events) {
    try {
      const result = await db
        .prepare(INSERT_SQL)
        .bind(
          event.event_id,
          event.sequence_number,
          event.previous_hash,
          event.event_hash,
          event.tenant_id,
          event.machine_id,
          event.session_id,
          event.agent_version,
          event.timestamp,
          event.event_type,
          event.actor,
          event.subject_type,
          event.subject_id,
          event.action,
          event.scope_level,
          event.approval_status,
          event.approval_by,
          event.sensitivity_level,
          event.tokens_used,
          event.cost_usd,
          event.execution_time_ms,
          event.agent_routed_to,
          event.boundary_enforced,
          event.details
        )
        .run();

      results[event.event_id] = result.meta.changes > 0 ? "success" : "duplicate_skipped";
    } catch (e) {
      results[event.event_id] = `error: ${(e as Error).message}`;
    }
  }

  return results;
}
