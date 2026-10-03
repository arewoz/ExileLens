-- Item Check volume across opted-in ACTIVE INSTALLATIONS (not users), per complete UTC day,
-- from the nightly aggregates (metrics_daily). Two denominators are shown:
--   checks_per_item_check_install = checks / installations that ran at least one Item Check
--   checks_per_active_install     = checks / all active installations
SELECT day,
       active_installs,
       item_check_installs,
       item_checks_total,
       ROUND(1.0 * item_checks_total / NULLIF(item_check_installs, 0), 2) AS checks_per_item_check_install,
       ROUND(1.0 * item_checks_total / NULLIF(active_installs, 0), 2) AS checks_per_active_install
FROM (
  SELECT day,
         MAX(CASE WHEN metric = 'active_installs' THEN value END) AS active_installs,
         MAX(CASE WHEN metric = 'item_check_active_installs' THEN value END) AS item_check_installs,
         MAX(CASE WHEN metric = 'item_checks_total' THEN value END) AS item_checks_total
  FROM metrics_daily
  WHERE dim = ''
    AND metric IN ('active_installs', 'item_check_active_installs', 'item_checks_total')
    AND day >= date('now', '-14 day')
  GROUP BY day
)
ORDER BY day DESC
