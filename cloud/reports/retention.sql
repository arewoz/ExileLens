-- Retention of opted-in INSTALLATIONS (not users), by weekly first-seen cohort (week starts
-- Monday, UTC). D1/D7/D30 = share of the cohort active exactly 1/7/30 days after its first
-- day; only installations old enough to have reached that day are counted.
-- Cohorts smaller than {{MIN_COHORT}} installations are suppressed (rates shown as NULL).
-- scripts/report.mjs defaults --min-cohort to 20 for --remote and 0 for --local.
WITH c AS (
  SELECT i.install_hash,
         i.first_day,
         date(i.first_day, 'weekday 0', '-6 days') AS cohort_week,
         EXISTS (SELECT 1 FROM telemetry_install_days d
                  WHERE d.install_hash = i.install_hash AND d.day = date(i.first_day, '+1 day')) AS r1,
         EXISTS (SELECT 1 FROM telemetry_install_days d
                  WHERE d.install_hash = i.install_hash AND d.day = date(i.first_day, '+7 day')) AS r7,
         EXISTS (SELECT 1 FROM telemetry_install_days d
                  WHERE d.install_hash = i.install_hash AND d.day = date(i.first_day, '+30 day')) AS r30
  FROM telemetry_installs i
  WHERE i.first_day >= date('now', '-120 day') AND i.first_day < date('now')
)
SELECT cohort_week,
       COUNT(*) AS cohort_installs,
       CASE WHEN COUNT(*) < {{MIN_COHORT}} THEN NULL ELSE
         ROUND(100.0 * SUM(CASE WHEN date(first_day, '+1 day') < date('now') THEN r1 ELSE 0 END)
           / NULLIF(SUM(CASE WHEN date(first_day, '+1 day') < date('now') THEN 1 ELSE 0 END), 0), 1) END AS d1_pct,
       CASE WHEN COUNT(*) < {{MIN_COHORT}} THEN NULL ELSE
         ROUND(100.0 * SUM(CASE WHEN date(first_day, '+7 day') < date('now') THEN r7 ELSE 0 END)
           / NULLIF(SUM(CASE WHEN date(first_day, '+7 day') < date('now') THEN 1 ELSE 0 END), 0), 1) END AS d7_pct,
       CASE WHEN COUNT(*) < {{MIN_COHORT}} THEN NULL ELSE
         ROUND(100.0 * SUM(CASE WHEN date(first_day, '+30 day') < date('now') THEN r30 ELSE 0 END)
           / NULLIF(SUM(CASE WHEN date(first_day, '+30 day') < date('now') THEN 1 ELSE 0 END), 0), 1) END AS d30_pct
FROM c
GROUP BY cohort_week
ORDER BY cohort_week DESC
