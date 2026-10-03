/** Types for `import { env } from "cloudflare:workers"` inside tests. */
declare namespace Cloudflare {
  interface Env {
    TELEMETRY_DB: D1Database;
    ANALYTICS_PEPPER: string;
    DIAGNOSTIC_PEPPER: string;
    INGEST_ENABLED?: string;
    TEST_MIGRATIONS: import("@cloudflare/vitest-pool-workers").D1Migration[];
    // Patreon (Package B) test bindings
    PATREON_DB: D1Database;
    PATREON_CLIENT_SECRET: string;
    PATREON_ID_PEPPER: string;
    TOKEN_ENC_KEY: string;
    ENTITLEMENT_SIGNING_KEY: string;
    TEST_PATREON_MIGRATIONS: import("@cloudflare/vitest-pool-workers").D1Migration[];
  }
}
