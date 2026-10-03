-- Opted-in ACTIVE INSTALLATIONS, not users. Each opted-in installation is one anonymous
-- keyed hash; one person with several PCs/profiles counts several times and people who
-- did not opt in are not counted at all. Windows are the last N COMPLETE UTC days.
SELECT
  (SELECT COUNT(DISTINCT install_hash) FROM telemetry_install_days
    WHERE day = date('now', '-1 day')) AS active_installs_1d,
  (SELECT COUNT(DISTINCT install_hash) FROM telemetry_install_days
    WHERE day >= date('now', '-7 day') AND day < date('now')) AS active_installs_7d,
  (SELECT COUNT(DISTINCT install_hash) FROM telemetry_install_days
    WHERE day >= date('now', '-30 day') AND day < date('now')) AS active_installs_30d,
  (SELECT COUNT(*) FROM telemetry_installs) AS opted_in_installs_known
