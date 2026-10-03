-- TELEMETRY_DB schema, migration 0001.
-- Stores ONLY opt-in usage statistics and error reports. No IP addresses, no
-- User-Agent, no raw client UUIDs: install_hash / diag_hash are
-- HMAC-SHA256(pepper, "<domain>:" + uuid) hex digests (see src/telemetry/hash.ts).
-- Nothing here may reference the Patreon database (PATREON_DB, Package B).
-- Retention (enforced by src/telemetry/maintenance.ts) is noted per table.

-- Batch de-duplication. Retention: 7 days.
CREATE TABLE ingest_batches (
  batch_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  day TEXT NOT NULL,
  PRIMARY KEY (batch_id, kind)
);
CREATE INDEX idx_ingest_batches_day ON ingest_batches (day);

-- Raw validated usage events. Retention: 30 days (by event day).
CREATE TABLE telemetry_events (
  id INTEGER PRIMARY KEY,
  install_hash TEXT NOT NULL,
  day TEXT NOT NULL,
  hour TEXT NOT NULL,
  event TEXT NOT NULL,
  app_version TEXT NOT NULL,
  props TEXT NOT NULL
);
CREATE INDEX idx_telemetry_events_day_event ON telemetry_events (day, event);
CREATE INDEX idx_telemetry_events_install ON telemetry_events (install_hash);

-- One row per opted-in installation. Retention: 13 months after last_day.
CREATE TABLE telemetry_installs (
  install_hash TEXT PRIMARY KEY,
  first_day TEXT NOT NULL,
  last_day TEXT NOT NULL,
  first_version TEXT NOT NULL,
  last_version TEXT NOT NULL
);
CREATE INDEX idx_telemetry_installs_last_day ON telemetry_installs (last_day);

-- Per-install per-day activity and the daily event cap counter. Retention: 120 days.
CREATE TABLE telemetry_install_days (
  install_hash TEXT NOT NULL,
  day TEXT NOT NULL,
  app_version TEXT NOT NULL,
  events_accepted INTEGER NOT NULL,
  PRIMARY KEY (install_hash, day)
);
CREATE INDEX idx_telemetry_install_days_day ON telemetry_install_days (day);

-- Anonymous daily aggregates. Retention: 13 months.
CREATE TABLE metrics_daily (
  day TEXT NOT NULL,
  metric TEXT NOT NULL,
  dim TEXT NOT NULL,
  value INTEGER NOT NULL,
  PRIMARY KEY (day, metric, dim)
);

-- Error groups keyed by a server-computed fingerprint. Retention: 12 months after last_seen_day.
CREATE TABLE error_groups (
  fingerprint TEXT PRIMARY KEY,
  error_code TEXT NOT NULL,
  component TEXT NOT NULL,
  exception_type TEXT NOT NULL,
  frames TEXT NOT NULL,
  first_seen_day TEXT NOT NULL,
  last_seen_day TEXT NOT NULL,
  first_version TEXT NOT NULL,
  last_version TEXT NOT NULL,
  occurrences INTEGER NOT NULL
);
CREATE INDEX idx_error_groups_last_seen ON error_groups (last_seen_day);

-- Per-group per-day per-version occurrences. Retention: 13 months.
CREATE TABLE error_group_days (
  fingerprint TEXT NOT NULL,
  day TEXT NOT NULL,
  app_version TEXT NOT NULL,
  occurrences INTEGER NOT NULL,
  PRIMARY KEY (fingerprint, day, app_version)
);
CREATE INDEX idx_error_group_days_day ON error_group_days (day);

-- Which diagnostic installs were affected by which group (once per day). Retention: 60 days.
CREATE TABLE error_group_installs (
  fingerprint TEXT NOT NULL,
  diag_hash TEXT NOT NULL,
  day TEXT NOT NULL,
  PRIMARY KEY (fingerprint, diag_hash, day)
);
CREATE INDEX idx_error_group_installs_day ON error_group_installs (day);
CREATE INDEX idx_error_group_installs_diag ON error_group_installs (diag_hash);

-- One row per diagnostic install, doubles as the per-day report cap counter.
-- Retention: 13 months after last_day.
CREATE TABLE error_installs (
  diag_hash TEXT PRIMARY KEY,
  first_day TEXT NOT NULL,
  last_day TEXT NOT NULL,
  reports_today_day TEXT NOT NULL,
  reports_today INTEGER NOT NULL
);
CREATE INDEX idx_error_installs_last_day ON error_installs (last_day);
