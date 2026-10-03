-- Top error groups seen in the last 30 days by opted-in DIAGNOSTIC INSTALLATIONS (not users;
-- the diagnostic id is unrelated to the usage-statistics id). affected_diag_installs counts
-- distinct diagnostic installations within the 60-day link retention window.
SELECT substr(g.fingerprint, 1, 12) AS fingerprint,
       g.error_code,
       g.component,
       g.exception_type,
       g.occurrences,
       (SELECT COUNT(DISTINCT i.diag_hash) FROM error_group_installs i
         WHERE i.fingerprint = g.fingerprint) AS affected_diag_installs,
       g.first_seen_day,
       g.last_seen_day,
       g.first_version,
       g.last_version
FROM error_groups g
WHERE g.last_seen_day >= date('now', '-30 day')
ORDER BY affected_diag_installs DESC, g.occurrences DESC
LIMIT 20
