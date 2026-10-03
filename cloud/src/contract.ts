/**
 * Schema-driven validator for the ExileLens cloud contract v1.
 *
 * The ONLY source of truth is cloud/schema/events.v1.json; the Python client
 * implements the identical algorithm and cloud/contract/fixtures.json is ground
 * truth for both. Nothing about events is hard-coded here.
 */
import schemaJson from "../schema/events.v1.json";

export type BatchKind = "usage" | "errors";

export interface RejectedItem {
  index: number;
  code: string;
}

export interface BatchResult {
  /** "ok" or a batch-level code (invalid_envelope, unknown_field, ...). */
  batchCode: string;
  accepted: number[];
  rejected: RejectedItem[];
}

interface ValueSpec {
  kind?: string;
  ref?: string;
  values?: string[];
  regex?: string;
  max_len?: number;
  min?: number;
  max?: number;
  max_items?: number;
  item?: ObjectSpec;
}

interface ObjectSpec {
  required: string[];
  props: Record<string, ValueSpec>;
}

interface Schema {
  limits: Record<string, number>;
  types: Record<string, ValueSpec>;
  app: ObjectSpec;
  usage: {
    id_field: string;
    envelope_extra: Record<string, ValueSpec>;
    events: Record<string, ObjectSpec>;
  };
  errors: {
    id_field: string;
    envelope_extra: Record<string, ValueSpec>;
    report: ObjectSpec;
  };
  retention: {
    raw_events_days: number;
    install_activity_days: number;
    aggregates_months: number;
    error_groups_months: number;
    error_install_links_days: number;
  };
}

export const schema = schemaJson as unknown as Schema;

const HOUR_MS = 3_600_000;

const regexCache = new Map<string, RegExp>();
function regexFor(source: string): RegExp {
  let re = regexCache.get(source);
  if (!re) {
    re = new RegExp(source);
    regexCache.set(source, re);
  }
  return re;
}

export function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function has(obj: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

function resolve(spec: ValueSpec): ValueSpec {
  if (spec.ref !== undefined) {
    const target = schema.types[spec.ref];
    if (!target) throw new Error(`contract: unknown type ref ${spec.ref}`);
    return target;
  }
  return spec;
}

/** Validate one value against a spec. Returns null when valid, else a reject code. */
function validateValue(rawSpec: ValueSpec, value: unknown): string | null {
  const spec = resolve(rawSpec);
  switch (spec.kind) {
    case "enum":
      return typeof value === "string" && (spec.values ?? []).includes(value) ? null : "invalid_value";
    case "bool":
      return typeof value === "boolean" ? null : "invalid_value";
    case "int": {
      if (typeof value !== "number" || !Number.isInteger(value)) return "invalid_value";
      if (spec.min !== undefined && value < spec.min) return "invalid_value";
      if (spec.max !== undefined && value > spec.max) return "invalid_value";
      return null;
    }
    case "pattern": {
      if (typeof value !== "string") return "invalid_value";
      if (spec.max_len !== undefined && value.length > spec.max_len) return "invalid_value";
      return regexFor(spec.regex ?? "^$").test(value) ? null : "invalid_value";
    }
    case "list": {
      if (!Array.isArray(value)) return "invalid_value";
      if (spec.max_items !== undefined && value.length > spec.max_items) return "invalid_value";
      for (const item of value) {
        if (!isPlainObject(item)) return "invalid_value";
        const code = validateObject(spec.item as ObjectSpec, item);
        if (code !== null) return code;
      }
      return null;
    }
    default:
      throw new Error(`contract: unsupported kind ${String(spec.kind)}`);
  }
}

/** unknown_prop, then missing_prop, then invalid_value per present value. */
function validateObject(spec: ObjectSpec, obj: Record<string, unknown>): string | null {
  for (const key of Object.keys(obj)) {
    if (!has(spec.props, key)) return "unknown_prop";
  }
  for (const key of spec.required) {
    if (!has(obj, key)) return "missing_prop";
  }
  for (const key of Object.keys(obj)) {
    const code = validateValue(spec.props[key] as ValueSpec, obj[key]);
    if (code !== null) return code;
  }
  return null;
}

/** Parse "YYYY-MM-DDTHH:00Z" into epoch ms; null if not a real calendar hour. */
export function parseHour(t: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):00Z$/.exec(t);
  if (!m) return null;
  const ms = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]));
  if (Number.isNaN(ms)) return null;
  // Reject impossible dates that Date.UTC would silently roll over (2026-02-31, 24:00).
  return new Date(ms).toISOString().slice(0, 13) === t.slice(0, 13) ? ms : null;
}

function windowCode(tMs: number, nowMs: number): string | null {
  if (tMs < nowMs - (schema.limits.max_event_age_hours as number) * HOUR_MS) return "stale_event";
  if (tMs > nowMs + (schema.limits.max_future_hours as number) * HOUR_MS) return "future_event";
  return null;
}

const ALLOWED_KEYS: Record<BatchKind, { keys: string[]; required: string[] }> = {
  usage: {
    keys: ["schema", "batch_id", "analytics_id", "queue_dropped", "app", "events"],
    required: ["schema", "batch_id", "analytics_id", "app", "events"],
  },
  errors: {
    keys: ["schema", "batch_id", "diagnostic_id", "app", "reports"],
    required: ["schema", "batch_id", "diagnostic_id", "app", "reports"],
  },
};

function fail(batchCode: string): BatchResult {
  return { batchCode, accepted: [], rejected: [] };
}

/** True when `value` fully matches the named schema type (e.g. "uuid"). */
export function matchesType(typeName: string, value: unknown): boolean {
  return validateValue({ ref: typeName }, value) === null;
}

export function idFieldFor(kind: BatchKind): string {
  return kind === "usage" ? schema.usage.id_field : schema.errors.id_field;
}

export function validateBatch(kind: BatchKind, body: unknown, nowMs: number): BatchResult {
  if (!isPlainObject(body)) return fail("invalid_envelope");
  const allowed = ALLOWED_KEYS[kind];
  const idField = idFieldFor(kind);
  const listField = kind === "usage" ? "events" : "reports";

  for (const key of Object.keys(body)) {
    if (!allowed.keys.includes(key)) return fail("unknown_field");
  }
  for (const key of allowed.required) {
    if (!has(body, key)) return fail("invalid_envelope");
  }
  if (body.schema !== 1) return fail("schema_unsupported");
  if (!matchesType("uuid", body.batch_id) || !matchesType("uuid", body[idField])) {
    return fail("invalid_envelope");
  }
  if (kind === "usage" && has(body, "queue_dropped")) {
    const spec = schema.usage.envelope_extra.queue_dropped as ValueSpec;
    if (validateValue(spec, body.queue_dropped) !== null) return fail("invalid_envelope");
  }
  if (!isPlainObject(body.app) || validateObject(schema.app, body.app) !== null) {
    return fail("invalid_app");
  }
  const items = body[listField];
  if (!Array.isArray(items) || items.length === 0) return fail("invalid_envelope");
  const maxItems =
    kind === "usage"
      ? (schema.limits.usage_batch_max_events as number)
      : (schema.limits.error_batch_max_reports as number);
  if (items.length > maxItems) return fail("too_many_events");

  const accepted: number[] = [];
  const rejected: RejectedItem[] = [];
  items.forEach((item: unknown, index: number) => {
    const code = kind === "usage" ? validateUsageEvent(item, nowMs) : validateErrorReport(item, nowMs);
    if (code === null) accepted.push(index);
    else rejected.push({ index, code });
  });
  return { batchCode: "ok", accepted, rejected };
}

function validateUsageEvent(item: unknown, nowMs: number): string | null {
  if (!isPlainObject(item)) return "invalid_event";
  const keys = Object.keys(item);
  if (keys.length !== 3 || !keys.every((k) => k === "name" || k === "t" || k === "props")) {
    return "invalid_event";
  }
  if (!isPlainObject(item.props)) return "invalid_event";
  if (typeof item.name !== "string" || !has(schema.usage.events, item.name)) return "unknown_event";
  if (!matchesType("hour", item.t)) return "invalid_value";
  const tMs = parseHour(item.t as string);
  if (tMs === null) return "invalid_value";
  const code = windowCode(tMs, nowMs);
  if (code !== null) return code;
  return validateObject(schema.usage.events[item.name] as ObjectSpec, item.props);
}

function validateErrorReport(item: unknown, nowMs: number): string | null {
  if (!isPlainObject(item)) return "invalid_event";
  const code = validateObject(schema.errors.report, item);
  if (code !== null) return code;
  const first = parseHour(item.first_t as string);
  const last = parseHour(item.last_t as string);
  if (first === null || last === null || first > last) return "invalid_value";
  return windowCode(last, nowMs);
}
