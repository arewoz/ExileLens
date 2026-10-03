-- Version mix of opted-in ACTIVE INSTALLATIONS (not users) seen in the last 7 complete UTC
-- days, by the latest version each installation reported. "Latest" is the highest version
-- present in that population (beta 0.7.0b2 sorts before 0.7.0).
WITH v AS (
  SELECT last_version AS version, COUNT(*) AS installs
  FROM telemetry_installs
  WHERE last_day >= date('now', '-7 day') AND last_day < date('now')
  GROUP BY last_version
),
p1 AS (
  SELECT version, installs,
         CAST(substr(version, 1, instr(version, '.') - 1) AS INTEGER) AS major,
         substr(version, instr(version, '.') + 1) AS r1
  FROM v
),
p2 AS (
  SELECT version, installs, major,
         CAST(substr(r1, 1, instr(r1, '.') - 1) AS INTEGER) AS minor,
         substr(r1, instr(r1, '.') + 1) AS r2
  FROM p1
),
p3 AS (
  SELECT version, installs,
         printf('%05d.%05d.%05d.%06d', major, minor, CAST(r2 AS INTEGER),
                CASE WHEN instr(r2, 'b') > 0 THEN CAST(substr(r2, instr(r2, 'b') + 1) AS INTEGER) ELSE 999999 END) AS sort_key
  FROM p2
)
SELECT version,
       installs,
       ROUND(100.0 * installs / (SELECT SUM(installs) FROM p3), 1) AS pct_of_active_installs,
       CASE WHEN sort_key = (SELECT MAX(sort_key) FROM p3) THEN 'latest' ELSE '' END AS is_latest
FROM p3
ORDER BY sort_key DESC
