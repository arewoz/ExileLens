-- ANONYMOUS Patreon link funnel per UTC day, last 30 days (PATREON_DB; counts of link attempts,
-- not users or people). Source: link_metrics_daily, which holds only day / outcome / count.
-- started = link attempts begun in the app; the other columns are how those attempts ended.
SELECT
  day,
  SUM(CASE WHEN outcome = 'started' THEN count ELSE 0 END) AS started,
  SUM(CASE WHEN outcome = 'linked' THEN count ELSE 0 END) AS linked,
  SUM(CASE WHEN outcome = 'not_entitled' THEN count ELSE 0 END) AS not_entitled,
  SUM(CASE WHEN outcome = 'denied' THEN count ELSE 0 END) AS denied,
  SUM(CASE WHEN outcome = 'expired' THEN count ELSE 0 END) AS expired,
  SUM(CASE WHEN outcome = 'failed' THEN count ELSE 0 END) AS failed
FROM link_metrics_daily
WHERE day >= date('now', '-30 day')
GROUP BY day
ORDER BY day DESC;
