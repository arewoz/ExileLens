-- Opted-in installations (not users): per complete UTC day, how many active installations
-- were seen for the first time (new) and how many had been seen on an earlier day (returning).
SELECT d.day AS day,
       COUNT(*) AS active_installs,
       SUM(CASE WHEN i.first_day = d.day THEN 1 ELSE 0 END) AS new_installs,
       SUM(CASE WHEN i.first_day < d.day THEN 1 ELSE 0 END) AS returning_installs
FROM telemetry_install_days d
JOIN telemetry_installs i ON i.install_hash = d.install_hash
WHERE d.day >= date('now', '-14 day') AND d.day < date('now')
GROUP BY d.day
ORDER BY d.day DESC
