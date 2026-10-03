/**
 * POST /v1/telemetry/forget and POST /v1/errors/forget.
 *
 * Idempotent (always 204 for a well-formed request). Removes the rows linked to
 * the hashed id. Aggregates (metrics_daily, error_groups, error_group_days) stay:
 * they are anonymous. Not subject to the INGEST_ENABLED kill switch, so people
 * can always withdraw.
 */
import { isPlainObject, matchesType } from "../contract";
import type { TelemetryEnv } from "../env";
import { failure, guardDb, noContent } from "../http";
import { requestPrelude } from "./guard";
import { hmacHex } from "./hash";

type ForgetKind = "telemetry" | "errors";

export async function handleForget(env: TelemetryEnv, request: Request, kind: ForgetKind): Promise<Response> {
  const pre = await requestPrelude(env, request, { respectKillSwitch: false });
  if (!pre.ok) return pre.response;

  const idField = kind === "telemetry" ? "analytics_id" : "diagnostic_id";
  const body = pre.body;
  if (!isPlainObject(body)) return failure(400, "invalid_envelope");
  for (const key of Object.keys(body)) {
    if (key !== "schema" && key !== idField) return failure(400, "unknown_field");
  }
  if (!("schema" in body) || !(idField in body)) return failure(400, "invalid_envelope");
  if (body.schema !== 1) return failure(422, "schema_unsupported");
  const id = body[idField];
  if (!matchesType("uuid", id)) return failure(400, "invalid_envelope");

  const db = env.TELEMETRY_DB;
  if (kind === "telemetry") {
    const hash = await hmacHex(env.ANALYTICS_PEPPER, "analytics", id as string);
    await guardDb(() =>
      db.batch([
        db.prepare("DELETE FROM telemetry_events WHERE install_hash = ?1").bind(hash),
        db.prepare("DELETE FROM telemetry_install_days WHERE install_hash = ?1").bind(hash),
        db.prepare("DELETE FROM telemetry_installs WHERE install_hash = ?1").bind(hash),
      ]),
    );
  } else {
    const hash = await hmacHex(env.DIAGNOSTIC_PEPPER, "diagnostic", id as string);
    await guardDb(() =>
      db.batch([
        db.prepare("DELETE FROM error_group_installs WHERE diag_hash = ?1").bind(hash),
        db.prepare("DELETE FROM error_installs WHERE diag_hash = ?1").bind(hash),
      ]),
    );
  }
  return noContent();
}
