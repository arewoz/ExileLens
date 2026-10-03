-- Update attempt outcomes reported by opted-in INSTALLATIONS (not users) over the last 30
-- complete UTC days, from the nightly aggregates. Counts are events (attempts), not installs.
-- Success = outcome ok (download) / success (install); everything else is listed per outcome.
WITH t AS (
  SELECT CASE metric WHEN 'update_download_by_outcome' THEN 'download' ELSE 'install' END AS stage,
         dim AS outcome,
         SUM(value) AS attempts
  FROM metrics_daily
  WHERE metric IN ('update_download_by_outcome', 'update_install_by_outcome')
    AND day >= date('now', '-30 day') AND day < date('now')
  GROUP BY metric, dim
)
SELECT stage,
       outcome,
       attempts,
       ROUND(100.0 * attempts / (SELECT SUM(attempts) FROM t t2 WHERE t2.stage = t.stage), 1) AS pct_of_stage_attempts,
       CASE WHEN outcome IN ('ok', 'success') THEN 'success' ELSE 'not_success' END AS result
FROM t
ORDER BY stage, attempts DESC
