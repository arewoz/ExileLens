import { applyD1Migrations } from "cloudflare:test";
import { env } from "cloudflare:workers";

await applyD1Migrations(env.TELEMETRY_DB, env.TEST_MIGRATIONS);
await applyD1Migrations(env.PATREON_DB, env.TEST_PATREON_MIGRATIONS);
