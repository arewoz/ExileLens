-- Analyze Build adoption among opted-in ACTIVE INSTALLATIONS (not users), per complete UTC
-- day, from the nightly aggregates: installations that ran it, runs, and outcome counts.
SELECT day,
       active_installs,
       analyze_installs,
       ROUND(100.0 * analyze_installs / NULLIF(active_installs, 0), 1) AS adoption_pct_of_active_installs,
       runs_ok, runs_error, runs_no_signal
FROM (
  SELECT day,
         MAX(CASE WHEN metric = 'active_installs' THEN value END) AS active_installs,
         MAX(CASE WHEN metric = 'analyze_build_active_installs' THEN value END) AS analyze_installs,
         MAX(CASE WHEN metric = 'analyze_build_by_outcome' AND dim = 'ok' THEN value END) AS runs_ok,
         MAX(CASE WHEN metric = 'analyze_build_by_outcome' AND dim = 'error' THEN value END) AS runs_error,
         MAX(CASE WHEN metric = 'analyze_build_by_outcome' AND dim = 'no_signal' THEN value END) AS runs_no_signal
  FROM metrics_daily
  WHERE day >= date('now', '-14 day')
    AND metric IN ('active_installs', 'analyze_build_active_installs', 'analyze_build_by_outcome')
  GROUP BY day
)
ORDER BY day DESC
