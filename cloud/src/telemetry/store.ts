/** Small D1 helpers shared by the usage and error ingest paths. */
import { StorageUnavailable, guardDb } from "../http";

/**
 * Run `statements` as one atomic D1 batch whose FIRST statement inserts the
 * ingest_batches row (plain INSERT). A primary-key conflict (a concurrent retry
 * of the same batch_id) rolls the whole batch back and is reported as "duplicate";
 * any other failure becomes StorageUnavailable (-> 503 + Retry-After).
 */
export async function writeBatchAtomic(
  db: D1Database,
  kind: "usage" | "errors",
  batchId: string,
  statements: D1PreparedStatement[],
): Promise<"ok" | "duplicate"> {
  try {
    await db.batch(statements);
    return "ok";
  } catch {
    const again = await guardDb(() =>
      db
        .prepare("SELECT 1 AS dup FROM ingest_batches WHERE batch_id = ?1 AND kind = ?2")
        .bind(batchId, kind)
        .first<{ dup: number }>(),
    );
    if (again?.dup) return "duplicate";
    throw new StorageUnavailable();
  }
}
