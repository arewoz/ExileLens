import { readFileSync } from "node:fs";
import path from "node:path";
import { cloudflareTest, readD1Migrations } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

export default defineConfig(async () => {
  const migrations = await readD1Migrations(path.join(import.meta.dirname, "migrations", "telemetry"));
  const patreonMigrations = await readD1Migrations(path.join(import.meta.dirname, "migrations", "patreon"));
  // Test-only Ed25519 key (PKCS#8 DER, base64). Public key and golden vector: test/keys, contract/lease_vector.json.
  const testSigningKey = readFileSync(path.join(import.meta.dirname, "test", "keys", "entitlement-test-1.pkcs8.b64"), "utf8").trim();
  return {
    plugins: [
      cloudflareTest({
        main: "./src/index.ts",
        wrangler: { configPath: "./wrangler.toml" },
        miniflare: {
          // Test-only secrets (fake). Real secrets live in .dev.vars / wrangler secrets.
          bindings: {
            ANALYTICS_PEPPER: "test-analytics-pepper-0123456789abcdef",
            DIAGNOSTIC_PEPPER: "test-diagnostic-pepper-fedcba9876543210",
            TEST_MIGRATIONS: migrations,
            TEST_PATREON_MIGRATIONS: patreonMigrations,
            PATREON_CLIENT_SECRET: "test-patreon-client-secret-NOT-REAL",
            PATREON_ID_PEPPER: "test-patreon-id-pepper-0123456789abcdef",
            // 32 bytes of 0x01..0x20, base64 (fake)
            TOKEN_ENC_KEY: "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA=",
            ENTITLEMENT_SIGNING_KEY: testSigningKey,
          },
        },
      }),
    ],
    test: {
      setupFiles: ["./test/apply-migrations.ts"],
      include: ["test/**/*.test.ts"],
    },
  };
});
