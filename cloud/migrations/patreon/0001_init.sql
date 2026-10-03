-- PATREON_DB schema, migration 0001.
-- Patreon is NOT an account system here: it only yields a signed capability lease.
-- Stored: hashes of one-time OAuth secrets, AES-256-GCM encrypted Patreon tokens, an
-- HMAC of the Patreon user id (never the id itself), device-token hashes and anonymous
-- daily counters. NEVER stored: emails, names, addresses, IPs, User-Agents, raw
-- Patreon payloads, plaintext tokens. There is no users/accounts table.
-- This database shares no tables, identifiers or peppers with the usage-statistics database.

-- Device-link handshake sessions. Retention: deleted 24 h after expires_at.
-- status: pending | exchanging | linked | not_entitled | denied | expired | failed | consumed | cancelled
CREATE TABLE link_sessions (
  session_id TEXT PRIMARY KEY,
  state_hash TEXT UNIQUE,
  poll_token_hash TEXT,
  status TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  link_id TEXT,
  result_code TEXT,
  polls INTEGER NOT NULL DEFAULT 0,
  consumed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_link_sessions_expires ON link_sessions (expires_at);

-- One row per linked Patreon user (identified only by a keyed hash).
-- patreon_user_hmac = HMAC-SHA256(PATREON_ID_PEPPER, "patreon:" + patreon_user_id) hex.
-- *_enc = base64(iv || AES-256-GCM ciphertext), AAD = link_id. status: active | reauth_required.
-- Timestamps are epoch seconds. last_capabilities is a JSON array of capability names.
CREATE TABLE patreon_links (
  link_id TEXT PRIMARY KEY,
  patreon_user_hmac TEXT UNIQUE NOT NULL,
  access_token_enc TEXT,
  refresh_token_enc TEXT,
  token_expires_at INTEGER,
  token_version INTEGER NOT NULL DEFAULT 1,
  refresh_lock_until INTEGER,
  last_verified_at INTEGER,
  last_capabilities TEXT NOT NULL DEFAULT '[]',
  policy_version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'active',
  created_at INTEGER NOT NULL
);

-- Linked desktop installations. device_id = 16 random bytes hex; only SHA-256(device token) is stored.
-- At most 5 devices per link (the oldest is evicted). Retention: deleted after 60 idle days.
CREATE TABLE devices (
  device_id TEXT PRIMARY KEY,
  link_id TEXT NOT NULL,
  token_hash TEXT UNIQUE NOT NULL,
  created_at INTEGER NOT NULL,
  last_refresh_at INTEGER,
  last_lease_expires_at INTEGER,
  client_version TEXT
);
CREATE INDEX idx_devices_token_hash ON devices (token_hash);
CREATE INDEX idx_devices_link ON devices (link_id);

-- Anonymous link-funnel counters (no identifiers). Retention: 13 months.
-- outcome: started | linked | not_entitled | denied | expired | failed
CREATE TABLE link_metrics_daily (
  day TEXT NOT NULL,
  outcome TEXT NOT NULL,
  count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, outcome)
);

-- Anonymous lease-refresh counters (no identifiers). Retention: 13 months.
-- outcome: ok | not_eligible | patreon_unavailable | reauthorize_required | device_unknown | rate_limited | issuance_disabled
CREATE TABLE entitlement_refresh_daily (
  day TEXT NOT NULL,
  outcome TEXT NOT NULL,
  count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, outcome)
);
