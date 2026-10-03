/** Types for `import { env } from "cloudflare:workers"` inside tests. */
declare namespace Cloudflare {
  interface Env {
    TELEMETRY_DB: D1Database;
    ANALYTICS_PEPPER: string;
    DIAGNOSTIC_PEPPER: string;
    INGEST_ENABLED?: string;
    TEST_MIGRATIONS: import("@cloudflare/vitest-pool-workers").D1Migration[];
  }
}
