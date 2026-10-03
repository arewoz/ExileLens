-- Distribution of Item Check verdicts over the last 30 complete UTC days, counting checks
-- reported by opted-in installations (not users), from the nightly aggregates.
WITH t AS (
  SELECT dim AS verdict, SUM(value) AS checks
  FROM metrics_daily
  WHERE metric = 'item_checks_by_verdict' AND day >= date('now', '-30 day') AND day < date('now')
  GROUP BY dim
)
SELECT verdict,
       checks,
       ROUND(100.0 * checks / (SELECT SUM(checks) FROM t), 1) AS pct_of_checks
FROM t
ORDER BY checks DESC
