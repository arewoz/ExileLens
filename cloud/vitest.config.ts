import path from "node:path";
import { cloudflareTest, readD1Migrations } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

export default defineConfig(async () => {
  const migrations = await readD1Migrations(path.join(import.meta.dirname, "migrations", "telemetry"));
  return {
    plugins: [
      cloudflareTest({
        main: "./src/index.ts",
        wrangler: { configPath: "./wrangler.toml" },
        miniflare: {
          // Test-only secrets (fake). Real peppers live in .dev.vars / wrangler secrets.
          bindings: {
            ANALYTICS_PEPPER: "test-analytics-pepper-0123456789abcdef",
            DIAGNOSTIC_PEPPER: "test-diagnostic-pepper-fedcba9876543210",
            TEST_MIGRATIONS: migrations,
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
