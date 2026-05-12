import { validateAccessJwt } from "./auth";
import { writeEventBatch, AuditEvent } from "./d1_writer";

export interface Env {
  AUDIT_DB: D1Database;
  CF_ACCESS_AUD: string;
}

interface SyncBatchPayload {
  machine_id: string;
  tenant_id: string;
  events: AuditEvent[];
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    // 1. Validate Cloudflare Access JWT (service token or user session)
    const jwt = request.headers.get("Cf-Access-Jwt-Assertion");
    const clientId = request.headers.get("CF-Access-Client-Id");
    const clientSecret = request.headers.get("CF-Access-Client-Secret");

    // Service tokens bypass JWT validation (they use client ID + secret)
    const isServiceToken = clientId && clientSecret;

    if (!isServiceToken) {
      if (!jwt) {
        return new Response("Unauthorized", { status: 401 });
      }
      const valid = await validateAccessJwt(jwt, env.CF_ACCESS_AUD);
      if (!valid) {
        return new Response("Forbidden — invalid Access JWT", { status: 403 });
      }
    }

    // 2. Route
    const url = new URL(request.url);

    if (request.method === "POST" && url.pathname === "/sync") {
      return handleSync(request, env);
    }

    if (request.method === "GET" && url.pathname === "/health") {
      return new Response(JSON.stringify({ status: "ok" }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    return new Response("Not found", { status: 404 });
  },
};

async function handleSync(request: Request, env: Env): Promise<Response> {
  let payload: SyncBatchPayload;
  try {
    payload = await request.json() as SyncBatchPayload;
  } catch {
    return new Response("Invalid JSON", { status: 400 });
  }

  if (!payload.events || !Array.isArray(payload.events)) {
    return new Response("Missing events array", { status: 400 });
  }

  const results = await writeEventBatch(env.AUDIT_DB, payload.events);

  const successCount = Object.values(results).filter((v) => v === "success").length;
  const dupCount = Object.values(results).filter((v) => v === "duplicate_skipped").length;
  const errCount = Object.values(results).filter(
    (v) => v !== "success" && v !== "duplicate_skipped"
  ).length;

  return new Response(
    JSON.stringify({
      results,
      summary: { success: successCount, duplicate_skipped: dupCount, errors: errCount },
    }),
    { headers: { "Content-Type": "application/json" } }
  );
}
