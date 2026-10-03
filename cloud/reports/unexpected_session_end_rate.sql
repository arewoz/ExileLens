-- "Unexpected session end" rate among app starts reported by opted-in INSTALLATIONS (not
-- users). It is NOT a crash rate and must never be presented as "crash-free": an unexpected
-- session end also covers power loss, task kill, and similar. Starts whose previous session
-- is first_run or unknown are excluded from the denominator.
SELECT day,
       MAX(CASE WHEN metric = 'unexpected_session_end' THEN value END) AS unexpected_session_end,
       MAX(CASE WHEN metric = 'clean_session_end' THEN value END) AS clean_session_end,
       ROUND(100.0 * MAX(CASE WHEN metric = 'unexpected_session_end' THEN value END)
         / NULLIF(MAX(CASE WHEN metric = 'unexpected_session_end' THEN value END)
                + MAX(CASE WHEN metric = 'clean_session_end' THEN value END), 0), 2) AS unexpected_session_end_pct
FROM metrics_daily
WHERE metric IN ('unexpected_session_end', 'clean_session_end')
  AND day >= date('now', '-14 day')
GROUP BY day
ORDER BY day DESC
